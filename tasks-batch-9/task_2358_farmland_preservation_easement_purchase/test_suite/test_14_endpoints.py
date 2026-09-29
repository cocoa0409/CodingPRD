"""Endpoint surfaces: the CRUD triple, the action posts and the bulk sweep.

Each case exercises one surface end to end — its filters and ordering, the fields
it writes, the derived values it returns and the replay it refuses.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLOCK_2026_12_15,
    CLOCK_2027_12_20,
    SWEEP_COUNTERS,
    TEST_USERS,
    ApiErrorId,
    api_client,
    complete_visit,
    create_program,
    create_standard_sources,
    make_landowner_headers,
    open_violation_payload,
    read_application,
    read_easement,
    read_parcel,
    read_source,
    requirement_of_type,
    run_sweep,
    schedule_visit,
    set_clock,
    setup_accepted_application,
    setup_filed_application,
    setup_recorded_easement,
    setup_small_recorded_easement,
    submit_and_accept_requirement,
    submit_subordination_payload,
    submit_title_payload,
    waiver_payload,
    withdrawal_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]
MONITOR = TEST_USERS["stewardship_monitor_headers"]


class TestFundingSourceSurface:
    """Create, read one, and filter the collection."""

    def test_the_detail_read_and_the_collection_filters_agree(self):
        """Three appropriations, read singly and then sliced two ways.

        PRD §2.3: "Funding sources filter on `program_id`, `level` and `status`."

        Design: Corner/endpoints/funding_source_crud_surface_creates_reads_and_filters_the_collection
        """
        program = create_program()
        sources = create_standard_sources(program["id"])

        federal = validate_success(
            api_client.get_funding_source(sources["federal"]["id"], ADMIN)
        )
        assert federal["level"] == "FEDERAL"
        assert federal["authorized_cents"] == 200_000_000
        assert federal["requires_match"] is True
        assert federal["match_ratio"] == pytest.approx(1.0, abs=0.01)
        assert federal["priority_order"] == 3
        # No application has been filed, so the whole ledger is still at zero.
        assert federal["reserved_cents"] == 0
        assert federal["committed_cents"] == 0
        assert federal["disbursed_cents"] == 0
        assert federal["available_cents"] == 200_000_000
        assert federal["status"] == "ACTIVE"
        assert federal["suspension_reason"] is None
        assert federal["version"] == 1

        by_level, level_meta = validate_paginated(
            api_client.list_funding_sources(
                OFFICER, {"program_id": program["id"], "level": "FEDERAL"}
            )
        )
        assert level_meta["total_count"] == 1
        assert [row["id"] for row in by_level] == [sources["federal"]["id"]]

    def test_the_collection_paginates_in_sweep_order(self):
        """`priority_order` ascending, split across two pages of two.

        PRD §2.3: "`GET /funding-sources` is ordered by `priority_order`
        ascending and then `created_at` ascending."

        Design: Corner/endpoints/funding_source_crud_surface_creates_reads_and_filters_the_collection
        """
        program = create_program()
        sources = create_standard_sources(program["id"])
        query = {"program_id": program["id"], "status": "ACTIVE"}

        first_page, first_meta = validate_paginated(
            api_client.list_funding_sources(ADMIN, {**query, "limit": 2, "offset": 0})
        )
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert [row["id"] for row in first_page] == [
            sources["local"]["id"],
            sources["state"]["id"],
        ]

        second_page, second_meta = validate_paginated(
            api_client.list_funding_sources(ADMIN, {**query, "limit": 2, "offset": 2})
        )
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert [row["id"] for row in second_page] == [sources["federal"]["id"]]


class TestWithdrawalAction:
    """One reason string, a terminal application and a freed parcel."""

    def test_withdrawal_records_its_reason_and_hands_the_parcel_back(self):
        """The action writes the reason verbatim and refuses its own replay.

        PRD §3.5: "A landowner may withdraw from `RECEIVED`, `RANKED`,
        `OFFER_ISSUED` or `COUNTERED` by supplying a `withdrawal_reason`, provided
        `X-User-ID` matches the application's `landowner_id`. Withdrawal appends a
        `WITHDRAWAL` entry with a null amount, stores the reason, and moves the
        application to `WITHDRAWN`."

        Design: Corner/endpoints/withdrawal_action_endpoint_records_its_reason_and_releases_the_parcel
        """
        scenario = setup_filed_application()
        application_id = scenario["application"]["id"]
        parcel_id = scenario["parcel"]["id"]
        landowner_headers = make_landowner_headers(scenario["landowner"]["id"])
        assert read_parcel(parcel_id)["status"] == "UNDER_APPLICATION"
        reason = "landowner enrolled in a lease program instead"

        withdrawn = validate_success(
            api_client.withdraw_application(
                application_id, withdrawal_payload(reason), landowner_headers
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason"] == reason

        released = read_parcel(parcel_id)
        assert released["status"] == "ELIGIBLE"
        # Registered at 1, taken to UNDER_APPLICATION by the filing, returned here.
        assert released["version"] == 3

        rows, meta = validate_paginated(
            api_client.list_applications(
                ADMIN,
                {"funding_round_id": scenario["round"]["id"], "status": "WITHDRAWN"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == application_id

        replay = api_client.withdraw_application(
            application_id, withdrawal_payload("duplicate request"), landowner_headers
        )
        validate_error(replay, ApiErrorId.ERR_INVALID_APPLICATION_STATE.value, 409)
        assert read_application(application_id)["withdrawal_reason"] == reason


class TestStewardshipSweepBulkAction:
    """One bodyless post that reports what it did, per category."""

    def test_two_sweeps_cross_two_boundaries_and_a_third_changes_nothing(self):
        """Due, then delinquent plus three expiries, then a no-op.

        PRD §2.5: "Every consequence of the clock advancing is realised by an
        explicit operational sweep — `POST /stewardship-sweeps` — which is
        idempotent with respect to the current clock reading and reports what it
        did through the counters `swept_easement_count`, `due_count`,
        `delinquent_count`, `cleared_to_compliant_count`,
        `terminated_easement_count`, `lapsed_offer_count`,
        `escalated_violation_count`, `expired_source_count` and
        `closed_round_count`."

        Design: Corner/endpoints/stewardship_sweep_is_one_bulk_action_that_reports_per_category_counts_and_is_idempotent
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        round_id = scenario["round"]["id"]
        sources = scenario["sources"]
        assert scenario["easement"]["next_monitoring_due_on"].startswith("2027-12-15")

        set_clock(CLOCK_2027_12_20)
        first = run_sweep(ADMIN)
        assert set(SWEEP_COUNTERS) <= set(first)
        assert first["due_count"] == 1
        assert first["delinquent_count"] == 0
        # The round's only application is CLOSED_RECORDED, so nothing on it
        # remains outside the terminal set.
        assert first["closed_round_count"] == 1
        for counter in (
            "expired_source_count",
            "lapsed_offer_count",
            "escalated_violation_count",
            "cleared_to_compliant_count",
            "terminated_easement_count",
        ):
            assert first[counter] == 0
        assert read_easement(easement_id)["stewardship_status"] == "MONITORING_DUE"
        assert (
            validate_success(api_client.get_funding_round(round_id, ADMIN))["status"]
            == "CLOSED"
        )

        # 2027-12-15 plus the 30-day grace lands exactly on 2028-01-14, and the
        # grace boundary itself is already delinquent.
        set_clock("2028-01-14T00:00:00Z")
        second = run_sweep(MONITOR)
        assert second["due_count"] == 0
        assert second["delinquent_count"] == 1
        # Every obligation window ended 2027-12-31, now strictly in the past.
        assert second["expired_source_count"] == 3
        assert second["closed_round_count"] == 0
        settled = read_easement(easement_id)
        assert settled["stewardship_status"] == "MONITORING_DELINQUENT"
        for key in ("local", "state", "federal"):
            assert read_source(sources[key]["id"])["status"] == "EXPIRED"

        third = run_sweep(MONITOR)
        for counter in SWEEP_COUNTERS:
            assert isinstance(third[counter], int)
        for counter in (
            "due_count",
            "delinquent_count",
            "expired_source_count",
            "closed_round_count",
            "lapsed_offer_count",
            "escalated_violation_count",
            "cleared_to_compliant_count",
            "terminated_easement_count",
        ):
            assert third[counter] == 0
        idempotent = read_easement(easement_id)
        assert idempotent["version"] == settled["version"]
        assert idempotent["stewardship_status"] == "MONITORING_DELINQUENT"


class TestViolationVisitCrossReference:
    """The optional `monitoring_visit_id` must stay inside its own easement."""

    def test_a_cross_easement_link_is_refused_and_the_paired_link_is_visible(self):
        """Two easements, two visits, one accepted link and one rejected.

        PRD §3.8: "When a `monitoring_visit_id` is supplied, that visit's own
        `easement_id` must equal the body's `easement_id`, else
        `ERR_VISIT_EASEMENT_MISMATCH`."

        Design: Corner/endpoints/violation_links_to_the_monitoring_visit_that_produced_it_and_cross_easement_links_are_rejected
        """
        big = setup_recorded_easement()
        small = setup_small_recorded_easement()
        big_easement_id = big["easement"]["id"]
        small_easement_id = small["easement"]["id"]
        assert big["easement"]["impervious_allowance_sqft"] == 139_392
        assert small["easement"]["impervious_allowance_sqft"] == 34_848
        assert small["easement"]["protected_acres"] == pytest.approx(40.00, abs=0.01)

        set_clock(CLOCK_2027_12_20)
        small_visit = schedule_visit(small_easement_id)
        big_visit = schedule_visit(big_easement_id)
        completed = complete_visit(big_visit["id"], 41_000)
        # 41,000 is inside the 139,392 allowance, so the visit finds nothing.
        assert completed["finding"] == "NO_ISSUE"

        cross_linked = api_client.open_violation(
            open_violation_payload(
                big_easement_id,
                violation_type="PROHIBITED_USE",
                monitoring_visit_id=small_visit["id"],
                notes="cross-linked to the wrong easement's visit",
            ),
            MONITOR,
        )
        validate_error(cross_linked, ApiErrorId.ERR_VISIT_EASEMENT_MISMATCH.value, 409)

        linked = validate_success(
            api_client.open_violation(
                open_violation_payload(
                    big_easement_id,
                    violation_type="PROHIBITED_USE",
                    monitoring_visit_id=big_visit["id"],
                    notes="commercial equipment storage observed on the visit",
                ),
                MONITOR,
            ),
            201,
        )
        assert linked["monitoring_visit_id"] == big_visit["id"]
        assert linked["easement_id"] == big_easement_id
        # A PROHIBITED_USE carries no excess square footage, so it opens MINOR.
        assert linked["severity"] == "MINOR"
        assert linked["status"] == "OPEN"

        from_visit, visit_meta = validate_paginated(
            api_client.list_visit_violations(big_visit["id"], ADMIN)
        )
        assert visit_meta["total_count"] == 1
        assert [row["id"] for row in from_visit] == [linked["id"]]

        _, other_meta = validate_paginated(
            api_client.list_easement_violations(small_easement_id, MONITOR)
        )
        # The rejected cross-link left no row anywhere.
        assert other_meta["total_count"] == 0

        assert read_easement(big_easement_id)["compliance_status"] == "VIOLATION_OPEN"
        assert read_easement(small_easement_id)["compliance_status"] == "COMPLIANT"


class TestDerivedReads:
    """Two path-only reads that return values no client ever supplied."""

    def test_the_program_rollup_and_the_easement_projection_are_both_computed(self):
        """`total_preserved_acres` aggregates and the due date projects forward.

        PRD §3.1: "That rollup is the sum of `protected_acres` over every easement
        whose `status` is `RECORDED` or `AMENDED` that is reachable through this
        program's funding rounds, carried to 2 decimals and rounded half up, and
        it is recomputed whenever an easement is recorded or terminated."

        Design: Corner/endpoints/program_and_easement_reads_expose_only_derived_aggregates_never_stored_copies
        """
        scenario = setup_recorded_easement()
        program = validate_success(
            api_client.get_program(scenario["program"]["id"], MONITOR)
        )
        assert program["total_preserved_acres"] == pytest.approx(160.00, abs=0.01)
        assert program["status"] == "ACTIVE"

        easement = validate_success(
            api_client.get_easement(
                scenario["easement"]["id"],
                make_landowner_headers(scenario["landowner"]["id"]),
            )
        )
        assert easement["recorded_on"].startswith("2026-12-15")
        # The anchor is `recorded_on` advanced by the 365-day interval.
        assert easement["next_monitoring_due_on"].startswith("2027-12-15")
        assert easement["impervious_allowance_sqft"] == 139_392
        assert easement["impervious_used_sqft"] == 0
        assert easement["residential_rights_retained"] == 2
        assert easement["residential_rights_extinguished"] == 2
        assert easement["status"] == "RECORDED"
        assert easement["stewardship_status"] == "MONITORING_CURRENT"
        assert easement["compliance_status"] == "COMPLIANT"
        assert easement["stewardship_hold"] is False
        assert easement["last_monitored_on"] is None
        assert easement["amendment_count"] == 0
        assert easement["open_violation_count"] == 0

        application = read_application(scenario["application"]["id"])
        assert application["closing_status"] == "CLOSED"
        assert application["funding_plan_status"] == "DISBURSED"
        assert read_parcel(scenario["parcel"]["id"])["status"] == "ENCUMBERED"


class TestWaiverConditionalAction:
    """One requirement type, one use, and the acreage it defers to."""

    def test_only_the_survey_is_waivable_and_only_once(self):
        """A title waiver is refused, the survey waiver clears the file.

        PRD §3.7: "A `ProgramAdmin` waives a requirement from `OUTSTANDING` or
        `DEFICIENT` — from any other status the waiver is
        `ERR_INVALID_REQUIREMENT_STATE` — by supplying a `waiver_reason`, and a
        waiver attempted on any `requirement_type` other than `BOUNDARY_SURVEY` is
        rejected with `ERR_REQUIREMENT_NOT_WAIVABLE`: title work and mortgage
        subordination are never waived."

        Design: Corner/endpoints/waiver_is_a_conditional_action_offered_only_on_the_boundary_survey_requirement
        """
        scenario = setup_accepted_application()
        application_id = scenario["application"]["id"]
        title = requirement_of_type(application_id, "TITLE_COMMITMENT")
        subordination = requirement_of_type(application_id, "MORTGAGE_SUBORDINATION")
        survey = requirement_of_type(application_id, "BOUNDARY_SURVEY")

        refused = api_client.waive_closing_requirement(
            title["id"],
            waiver_payload("title work handled by the land trust"),
            ADMIN,
        )
        validate_error(refused, ApiErrorId.ERR_REQUIREMENT_NOT_WAIVABLE.value, 409)
        assert (
            validate_success(api_client.get_closing_requirement(title["id"], ADMIN))[
                "status"
            ]
            == "OUTSTANDING"
        )

        submit_and_accept_requirement(title["id"], submit_title_payload(0))
        submit_and_accept_requirement(subordination["id"], submit_subordination_payload())
        midway = read_application(application_id)
        assert midway["requirement_satisfied_count"] == 2
        assert midway["closing_status"] == "PENDING_REQUIREMENTS"

        reason = "prior recorded survey accepted by counsel"
        waived = validate_success(
            api_client.waive_closing_requirement(
                survey["id"], waiver_payload(reason), ADMIN
            )
        )
        assert waived["status"] == "WAIVED"
        assert waived["waiver_reason"] == reason
        # A waiver is not a submission, so no acreage was ever recorded.
        assert waived["surveyed_acres"] is None

        cleared = read_application(application_id)
        # The counter counts SATISFIED or WAIVED rows, which is why a waiver
        # can complete the file.
        assert cleared["requirement_satisfied_count"] == 3
        assert cleared["closing_status"] == "CLEARED"

        again = api_client.waive_closing_requirement(
            survey["id"], waiver_payload("second attempt"), ADMIN
        )
        validate_error(again, ApiErrorId.ERR_INVALID_REQUIREMENT_STATE.value, 409)

        set_clock(CLOCK_2026_12_15)
        easement = validate_success(
            api_client.record_closing(
                application_id,
                {
                    "recorded_on": CLOCK_2026_12_15,
                    "protected_acres": 160.00,
                    "residential_rights_retained": 2,
                    "subdivision_permitted": False,
                    "permitted_uses": ["CROP_PRODUCTION", "LIVESTOCK"],
                },
                ADMIN,
            ),
            201,
        )
        # With the survey waived the closing acreage defers to the parcel's own.
        assert easement["protected_acres"] == pytest.approx(160.00, abs=0.01)
        assert (
            validate_success(api_client.get_closing_requirement(survey["id"], ADMIN))[
                "surveyed_acres"
            ]
            is None
        )
