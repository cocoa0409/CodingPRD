"""Endpoint contracts: the calendar collection's create-read-list triple, the
return action, the segregation dashboard, the visit-item junction row, and the
accrual gate that only a published calendar opens.
"""

from test_helpers import (
    ANALYST_ONE,
    MANAGER_ONE,
    REVIEWER_ONE,
    accrual_payload,
    api_client,
    assert_write_once_identity,
    assert_summary_matches_study,
    build_calendar_generation,
    create_study_calendar_payload,
    create_visit_charge_route_payload,
    item_spec,
    make_analyst_headers,
    make_manager_headers,
    make_reviewer_headers,
    post_charge,
    publish_calendar,
    read_analysis,
    read_calendar,
    read_study,
    return_analysis_payload,
    review_charge,
    route_spec,
    setup_study_with_analysis_under_review,
    setup_study_with_approved_analysis,
    setup_study_with_executed_budget,
    validate_error,
    validate_paginated,
    validate_success,
    visit_spec,
)

SPONSOR_INFUSION = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=50000,
    negotiated_unit_cents=40000,
    expected_occurrences=2,
)
MILESTONE_FEE = item_spec(
    "S9999",
    classification="RESEARCH_PAID",
    budget_category="INVOICEABLE",
    charge_master_unit_cents=125000,
    negotiated_unit_cents=125000,
    expected_occurrences=1,
)
ROUTINE_PANEL = item_spec(
    "80053",
    classification="ROUTINE_CARE",
    budget_category="PER_PATIENT",
    medicare_coverage_basis="STANDARD_OF_CARE",
    charge_master_unit_cents=9000,
    negotiated_unit_cents=9000,
    expected_occurrences=3,
)


def _new_calendar(study_id, analysis_id):
    return api_client.create_study_calendar(
        create_study_calendar_payload(study_id, analysis_id),
        make_analyst_headers(ANALYST_ONE),
    )


class TestCalendarCollectionRoundTrip:
    """Create, read back, then find the row again through the collection."""

    def test_01_a_generation_is_created_read_back_and_found_by_filter(self):
        """The POST computes the generation number and opens all three counters at
        zero, the by-id read echoes the stored row, and the collection filters and
        pages over it.

        PRD §3.4: "The new calendar's `build_generation` is one greater than the
        highest `build_generation` among the study's existing calendars, so the
        first is generation 1; it opens at `status` `DRAFT` with `visit_count`,
        `routed_item_count`, and `unrouted_per_patient_item_count` all at zero and
        `published_at` null."

        Design: Corner/endpoints/calendar_create_read_and_filtered_list_round_trip
        """
        ctx = setup_study_with_approved_analysis(
            [SPONSOR_INFUSION],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-C40"},
        )
        other = setup_study_with_approved_analysis(
            [SPONSOR_INFUSION],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-C40B"},
        )

        created = validate_success(
            _new_calendar(ctx["study"]["id"], ctx["analysis"]["id"]), 201
        )
        assert created["study_id"] == ctx["study"]["id"]
        assert created["source_analysis_id"] == ctx["analysis"]["id"]
        assert created["build_generation"] == 1
        assert created["status"] == "DRAFT"
        assert created["visit_count"] == 0
        assert created["routed_item_count"] == 0
        assert created["unrouted_per_patient_item_count"] == 0
        assert created["published_at"] is None
        assert created["version"] == 1

        fetched = validate_success(
            api_client.get_study_calendar(
                created["id"], make_manager_headers(MANAGER_ONE)
            ),
            200,
        )
        for field, value in created.items():
            assert fetched[field] == value, f"by-id read changed {field}"

        second = validate_success(
            _new_calendar(ctx["study"]["id"], ctx["analysis"]["id"]), 201
        )
        assert second["build_generation"] == 2
        # A generation on a different study never enters this study's numbering.
        elsewhere = validate_success(
            _new_calendar(other["study"]["id"], other["analysis"]["id"]), 201
        )
        assert elsewhere["build_generation"] == 1

        rows, meta = validate_paginated(
            api_client.list_study_calendars(
                make_manager_headers(MANAGER_ONE),
                params={"source_analysis_id": ctx["analysis"]["id"]},
            )
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert {row["id"] for row in rows} == {created["id"], second["id"]}

        first_page, first_meta = validate_paginated(
            api_client.list_study_calendars(
                make_manager_headers(MANAGER_ONE),
                params={
                    "source_analysis_id": ctx["analysis"]["id"],
                    "limit": 1,
                    "offset": 0,
                },
            )
        )
        assert len(first_page) == 1
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 2
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api_client.list_study_calendars(
                make_manager_headers(MANAGER_ONE),
                params={
                    "source_analysis_id": ctx["analysis"]["id"],
                    "limit": 1,
                    "offset": 1,
                },
            )
        )
        assert len(second_page) == 1
        assert second_meta["has_more"] is False
        assert {first_page[0]["id"], second_page[0]["id"]} == {
            created["id"],
            second["id"],
        }

        by_study, study_meta = validate_paginated(
            api_client.list_study_calendars(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": other["study"]["id"]},
            )
        )
        assert study_meta["total_count"] == 1
        assert by_study[0]["id"] == elsewhere["id"]


class TestReturnActionWritesThreeFieldsAtOnce:
    """A return is a review event, not a lifecycle event."""

    def test_02_returning_an_analysis_stamps_the_reviewer_and_counts_the_return(self):
        """Status, `return_count` and `returned_by_user_id` all move in the one
        request, and the study's lifecycle does not.

        PRD §3.3: "A `ComplianceReviewer` who is not satisfied returns the
        analysis with a `return_reason`, moving it `UNDER_REVIEW → RETURNED`. The
        reason is stored, the acting user is stamped into `returned_by_user_id`,
        and `return_count` increases by one."

        Design: Corner/endpoints/return_action_moves_analysis_and_stamps_the_reason
        """
        ctx = setup_study_with_analysis_under_review(
            [SPONSOR_INFUSION],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-C41"},
        )
        assert ctx["analysis"]["status"] == "UNDER_REVIEW"
        # create, one item, submit.
        assert ctx["analysis"]["version"] == 3
        assert ctx["analysis"]["return_count"] == 0
        assert ctx["analysis"]["returned_by_user_id"] is None
        assert ctx["study"]["lifecycle_status"] == "COVERAGE_PENDING"
        study_version = ctx["study"]["version"]

        returned = validate_success(
            api_client.return_coverage_analysis(
                ctx["analysis"]["id"],
                return_analysis_payload(
                    return_reason="Classify the metabolic panel against the standard-of-care footnote."
                ),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            200,
        )
        assert returned["status"] == "RETURNED"
        assert returned["return_count"] == 1
        assert returned["returned_by_user_id"] == REVIEWER_ONE
        assert returned["approved_at"] is None
        assert returned["approved_by_user_id"] is None
        assert returned["version"] == 4

        stored = read_analysis(ctx["analysis"]["id"])
        assert stored["status"] == "RETURNED"
        assert stored["return_count"] == 1

        study = read_study(ctx["study"]["id"])
        assert study["lifecycle_status"] == "COVERAGE_PENDING"
        assert study["version"] == study_version


class TestSegregationDashboardIsAComputedRead:
    """Every figure on the dashboard is the study's own ledger, read back."""

    def test_03_the_summary_reports_the_unreviewed_charge_only_as_a_count(self):
        """Two reviewed charges land in two different money positions while the
        third shows up only in `unrouted_charge_count`.

        PRD §3.7: "The billing office watches all of this through a per-study
        segregation dashboard, a computed read that returns the `study_id`, the
        current `billing_hold_posture`, an `unrouted_charge_count` giving the
        number of the study's charges still at `routing_state` `UNROUTED`, and the
        study's `sponsor_unbilled_cents`, `sponsor_receivable_cents`,
        `payer_billed_cents`, `payer_refunded_cents`,
        `improper_payer_exposure_cents`, `delinquent_sponsor_cents`, and
        `open_finding_count`."

        Design: Corner/endpoints/charge_review_summary_matches_the_stored_ledger
        """
        ctx = setup_study_with_approved_analysis(
            [ROUTINE_PANEL, SPONSOR_INFUSION],
            qct_registry_number="NCT10000142",
            study_overrides={
                "protocol_number": "AMC-2390-C42",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        assert ctx["study"]["billing_hold_posture"] == "OPEN"

        payer_charge = post_charge(
            ctx["study"]["id"],
            charge_code="80053",
            service_date="2026-08-01",
            amount_cents=9000,
        )
        sponsor_charge = post_charge(
            ctx["study"]["id"],
            charge_code="J9999",
            service_date="2026-08-01",
            amount_cents=40000,
        )
        unreviewed = post_charge(
            ctx["study"]["id"],
            charge_code="80053",
            service_date="2026-08-01",
            amount_cents=5000,
        )
        review_charge(payer_charge["id"], "CLEAR_TO_PAYER")
        review_charge(sponsor_charge["id"], "HOLD_FOR_SPONSOR")
        assert unreviewed["routing_state"] == "UNROUTED"

        summary = validate_success(
            api_client.get_charge_review_summary(
                ctx["study"]["id"], make_reviewer_headers(REVIEWER_ONE)
            ),
            200,
        )
        assert summary["study_id"] == ctx["study"]["id"]
        assert summary["billing_hold_posture"] == "OPEN"
        # The 5,000-cent charge is in no money position at all.
        assert summary["unrouted_charge_count"] == 1
        assert summary["payer_billed_cents"] == 9000
        assert summary["payer_refunded_cents"] == 0
        assert summary["sponsor_unbilled_cents"] == 40000
        assert summary["sponsor_receivable_cents"] == 0
        assert summary["improper_payer_exposure_cents"] == 0
        assert summary["delinquent_sponsor_cents"] == 0
        assert summary["open_finding_count"] == 0

        assert_summary_matches_study(summary, read_study(ctx["study"]["id"]))


class TestVisitChargeRouteIsTheJunctionRow:
    """The only place a calendar visit and a coverage item meet."""

    def test_04_a_route_snapshots_the_target_prices_it_and_refuses_a_repeat(self):
        """Two occurrences of a 40,000-cent sponsor item price the link at 80,000,
        the visit and the calendar counters follow, and the same pair cannot be
        linked twice.

        PRD §3.4: "`expected_amount_cents` is the money the route is expected to
        drop, computed as the route's `occurrences` multiplied by the coverage
        item's `units_per_occurrence`, multiplied by a unit price chosen from the
        snapshotted target: the item's `charge_master_unit_cents` when the target
        is `PAYER`, its `negotiated_unit_cents` when the target is `SPONSOR`, and
        zero when the target is `NONE`."

        Design: Corner/endpoints/visit_charge_route_links_item_to_visit_and_prices_it
        """
        ctx = setup_study_with_approved_analysis(
            [SPONSOR_INFUSION, MILESTONE_FEE],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-C43"},
        )
        ctx = build_calendar_generation(ctx, [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)])
        visit = ctx["visit_by_name"]["Cycle 1 Day 1"]
        item = ctx["item_by_code"]["J9999"]
        before = read_calendar(ctx["calendar"]["id"])
        assert before["routed_item_count"] == 0
        assert visit["expected_charge_total_cents"] == 0

        route = validate_success(
            api_client.create_visit_charge_route(
                create_visit_charge_route_payload(visit["id"], item["id"], occurrences=2),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert route["calendar_visit_id"] == visit["id"]
        assert route["coverage_item_id"] == item["id"]
        assert route["occurrences"] == 2
        assert route["routing_target"] == "SPONSOR"
        assert route["expected_amount_cents"] == 80000
        assert_write_once_identity(route, "visit charge route")

        fetched = validate_success(
            api_client.get_visit_charge_route(
                route["id"], make_manager_headers(MANAGER_ONE)
            ),
            200,
        )
        assert fetched["id"] == route["id"]
        assert fetched["expected_amount_cents"] == 80000
        assert fetched["routing_target"] == "SPONSOR"

        rows, meta = validate_paginated(
            api_client.list_visit_charge_routes(
                make_manager_headers(MANAGER_ONE), params={"calendar_visit_id": visit["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == route["id"]

        visits, _ = validate_paginated(
            api_client.list_calendar_visits_of_calendar(
                ctx["calendar"]["id"], make_manager_headers(MANAGER_ONE)
            )
        )
        assert visits[0]["expected_charge_total_cents"] == 80000

        after = read_calendar(ctx["calendar"]["id"])
        assert after["routed_item_count"] == 1
        # The invoiceable milestone is not per-patient, so nothing is unrouted.
        assert after["unrouted_per_patient_item_count"] == 0
        assert after["version"] > before["version"]

        validate_error(
            api_client.create_visit_charge_route(
                create_visit_charge_route_payload(visit["id"], item["id"]),
                make_analyst_headers(ANALYST_ONE),
            ),
            "ERR_DUPLICATE_VISIT_ROUTE",
            409,
        )
        assert read_calendar(ctx["calendar"]["id"])["routed_item_count"] == 1


class TestAccrualNeedsAPublishedCalendar:
    """Four preconditions hold; the fifth is the whole difference."""

    def test_05_publishing_the_only_calendar_is_what_opens_accrual(self):
        """The identical accrual request is refused while the generation is
        `DRAFT` and accepted once it is published.

        PRD §3.6: "with `OPEN_TO_ACCRUAL` the study moves `COVERAGE_APPROVED →
        OPEN_TO_ACCRUAL` only when all of the following hold: `budget_status` is
        `EXECUTED`; at least one of the study's calendars stands at `PUBLISHED`;
        `qct_determination` is something other than `UNDETERMINED`; and, when
        `qct_determination` is either `DEEMED_QUALIFYING` or
        `SELF_CERTIFIED_QUALIFYING`, the study's `registry_number` is present and
        matches the pattern of the literal characters `NCT` followed by exactly
        eight digits — a qualifying trial without a registry number is refused with
        `ERR_REGISTRY_NUMBER_REQUIRED`."

        Design: Corner/endpoints/accrual_opening_is_conditional_on_a_published_calendar
        """
        ctx = setup_study_with_executed_budget(
            [SPONSOR_INFUSION],
            qct_registry_number="NCT10000144",
            study_overrides={
                "protocol_number": "AMC-2390-C44",
                "funding_source": "INDUSTRY_SPONSORED",
            },
        )
        ctx = build_calendar_generation(
            ctx,
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [route_spec("Cycle 1 Day 1", "J9999")],
        )
        assert ctx["study"]["lifecycle_status"] == "COVERAGE_APPROVED"
        assert ctx["study"]["budget_status"] == "EXECUTED"
        assert ctx["study"]["qct_determination"] == "DEEMED_QUALIFYING"
        assert ctx["study"]["registry_number"] == "NCT10000144"
        assert ctx["calendar"]["status"] == "DRAFT"
        assert ctx["calendar"]["unrouted_per_patient_item_count"] == 0
        version_before = ctx["study"]["version"]

        validate_error(
            api_client.set_accrual(
                ctx["study"]["id"],
                accrual_payload(target_status="OPEN_TO_ACCRUAL"),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        refused = read_study(ctx["study"]["id"])
        assert refused["lifecycle_status"] == "COVERAGE_APPROVED"
        assert refused["version"] == version_before

        published = publish_calendar(ctx["calendar"]["id"])
        assert published["status"] == "PUBLISHED"
        after_publish = read_study(ctx["study"]["id"])

        opened = validate_success(
            api_client.set_accrual(
                ctx["study"]["id"],
                accrual_payload(target_status="OPEN_TO_ACCRUAL"),
                make_manager_headers(MANAGER_ONE),
            ),
            200,
        )
        assert opened["lifecycle_status"] == "OPEN_TO_ACCRUAL"
        assert opened["budget_status"] == "EXECUTED"
        assert opened["version"] == after_publish["version"] + 1
