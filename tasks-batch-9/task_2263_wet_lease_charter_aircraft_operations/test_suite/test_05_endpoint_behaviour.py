"""Endpoint behaviour: the condition-clearing action, the computed settlement read, the
crew-qualification join, the guarded month close and the filtered collection listings.

Each test drives one endpoint through the shape the PRD gives it — response status, response
body, the filters that make the relationship reverse-reachable, and the paging window.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_leg_payload,
    clear_conditions_payload,
    create_crew_qualification_payload,
    file_reliability_report,
    get_success_data,
    schedule_leg,
    setup_active_lease,
    setup_approved_lease,
    setup_filed_lease,
    terminate_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
AUTHORITY = TEST_USERS["regulatory_authority_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

CONDITION_CODES = ["OPS_MANUAL_SUPP_B", "WET_LEASE_ENDORSEMENT_FILED"]


# --------------------------------------------------------------------------- #
# Scenario builders                                                            #
# --------------------------------------------------------------------------- #


def _lease_on_a_conditional_docket(api) -> dict:
    """Lease filed on docket CAA-2026-4471 and ruled CONDITIONAL on two condition codes,
    so the docket carries both codes in `conditions` and both in `open_condition_codes`."""
    return setup_filed_lease(
        api,
        determination="CONDITIONAL",
        determination_overrides={"conditions": list(CONDITION_CODES)},
        with_first_officer=False,
    )


def _active_lease_with_an_empty_september(api) -> dict:
    """ACTIVE lease over 2026-09-01..2026-12-31 whose OPEN 2026-09 period carries no legs
    at all, so the guarantee floor alone drives both charge variants."""
    return setup_active_lease(api)


def _approved_lease_and_an_unqualified_captain(api) -> dict:
    """APPROVED lease and an ACTIVE captain who holds no qualification on it yet."""
    return setup_approved_lease(api, with_first_officer=False)


def _active_lease_with_one_open_september_leg(api) -> dict:
    """ACTIVE lease whose OPEN 2026-09 period still carries one SCHEDULED revenue leg,
    EGSS-LEPA on 2026-09-08T06:00:00Z..08:25:00Z."""
    scenario = setup_active_lease(api)
    scenario["leg"] = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:25:00Z",
    )
    return scenario


def _terminated_lease_with_report_and_return_record(api) -> dict:
    """Lease on an APPROVED docket with an ACCEPTED 2026-09 reliability report, then served
    with termination so it is TERMINATING and owns one PENDING_INSPECTION return record."""
    scenario = setup_active_lease(api)
    scenario["report"] = file_reliability_report(
        api, scenario, period_month="2026-09", decision="ACCEPT"
    )
    terminate_lease(api, scenario["lease"]["id"])
    scenario["lease"] = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
    return scenario


class TestClearApprovalConditions:
    def test_draining_every_open_code_upgrades_the_docket_to_approved(self, api):
        """PRD §3.2: A `CONDITIONAL` ruling requires a non-empty `conditions` array and copies it into `open_condition_codes`.
        PRD §3.2: Conditions are cleared by supplying a `cleared_condition_codes` array.
        PRD §3.2: The clearance is admissible only while the `determination` is `CONDITIONAL`, and only when every code still listed in `open_condition_codes` appears in the supplied array — that is, when nothing would remain open afterwards.
        PRD §3.2: The named codes are removed, `open_condition_codes` becomes empty, `decided_at` is refreshed to the current logical instant, and the docket is upgraded from `CONDITIONAL` to `APPROVED`.
        PRD §3.2: When the lease owns no prior docket, a `RegulatoryApproval` row is created against it with `determination` `UNDER_REVIEW`, `review_round` 1, and both `conditions` and `open_condition_codes` empty.

        Design: Corner/endpoints/clear_conditions_drains_open_codes_and_flips_conditional_to_approved
        """
        scenario = _lease_on_a_conditional_docket(api)
        assert scenario["approval"]["open_condition_codes"] == CONDITION_CODES, (
            "the conditional ruling must copy both imposed codes into the working set"
        )

        cleared = validate_success(
            api.clear_approval_conditions(
                scenario["approval"]["id"],
                clear_conditions_payload(list(CONDITION_CODES)),
                AUTHORITY,
            ),
            200,
        )

        assert cleared["determination"] == "APPROVED", (
            "clearing the last open code upgrades the docket from CONDITIONAL to APPROVED"
        )
        assert cleared["open_condition_codes"] == [], (
            "every named code is removed, leaving the working set empty"
        )
        assert cleared["conditions"] == CONDITION_CODES, (
            "conditions is the authority's immutable record of what it imposed and must "
            "still list both codes after the clearance"
        )
        assert cleared["review_round"] == 1, (
            "the docket was never denied and refiled, so it is still on review round 1"
        )
        assert cleared["decided_at"] is not None, (
            "the clearance refreshes decided_at to the current logical instant"
        )

    def test_the_upgraded_docket_is_reachable_by_determination_and_leaves_the_lease_alone(
        self, api
    ):
        """PRD §3.2: Both `APPROVED` and `CONDITIONAL` advance the lease from `PENDING_REGULATORY_APPROVAL` to `APPROVED` — the same lease outcome, the difference being that a conditional lease carries open conditions to clear before its term ends.
        PRD §3.2: The named codes are removed, `open_condition_codes` becomes empty, `decided_at` is refreshed to the current logical instant, and the docket is upgraded from `CONDITIONAL` to `APPROVED`.
        PRD §2.3: Authority dockets may be filtered by `lease_id` and `determination`; certificates by `lease_id` and `status`.
        PRD §2.3: All filters are optional and combine conjunctively.

        Design: Corner/endpoints/clear_conditions_drains_open_codes_and_flips_conditional_to_approved
        """
        scenario = _lease_on_a_conditional_docket(api)
        lease_id = scenario["lease"]["id"]
        get_success_data(
            api.clear_approval_conditions(
                scenario["approval"]["id"],
                clear_conditions_payload(list(CONDITION_CODES)),
                AUTHORITY,
            )
        )

        rows, meta = validate_paginated(
            api.list_regulatory_approvals(
                OPS, {"lease_id": lease_id, "determination": "APPROVED"}
            )
        )

        assert meta["total_count"] == 1, (
            "the lease's single docket now matches the APPROVED determination filter"
        )
        assert rows[0]["id"] == scenario["approval"]["id"], (
            "the docket reached through the filter is the one that was cleared"
        )

        lease = validate_success(api.get_lease(lease_id, OPS), 200)
        assert lease["status"] == "APPROVED", (
            "the lease was already APPROVED from the conditional ruling, and upgrading "
            "the docket must not disturb it"
        )


class TestSettlementPreview:
    def test_empty_month_previews_both_variants_at_the_guarantee_floor(self, api):
        """PRD §3.8: A non-mutating computed read evaluates both variants side by side without persisting anything.
        PRD §3.8: It returns `period_id`, `period_month`, `mgh_effective_hours`, `provisional_credited_hours`, `provisional_gross_charge_cents`, `final_credited_hours`, `final_shortfall_hours`, `final_overrun_hours`, `final_gross_charge_cents`, `reliability_penalty_cents` and `projected_final_charge_cents`.
        PRD §3.8: `mgh_effective_hours` is the lease's `min_guaranteed_block_hours_per_month` multiplied by the number of covered days and divided by the number of calendar days in `period_month`, rounded half up to four decimal places.
        PRD §3.8: When `credited_hours` is strictly less than `mgh_effective_hours`, `shortfall_hours` is their difference rounded half up to four decimal places and `overrun_hours` is 0.
        PRD §3.8: `base_charge_cents` is `mgh_effective_hours` multiplied by the lease's `block_hour_rate_usd_cents`, rounded half up to whole cents.
        PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.
        PRD §3.8: If no accepted report exists for the month, `reliability_penalty_cents` is 0 and no penalty applies.

        Design: Corner/endpoints/settlement_preview_is_a_pure_read_that_persists_nothing
        """
        scenario = _active_lease_with_an_empty_september(api)
        period_id = scenario["period"]["id"]

        preview = validate_success(api.get_settlement_preview(period_id, BILLING), 200)

        assert preview["period_id"] == period_id, (
            "the projection names the period it was computed for"
        )
        assert preview["period_month"] == "2026-09", (
            "the first period of a lease starting 2026-09-01 covers 2026-09"
        )
        assert preview["mgh_effective_hours"] == pytest.approx(5.0000, abs=0.0001), (
            "the lease covers all 30 days of 2026-09, so the guarantee is the full 5.0000 "
            "hours"
        )
        assert preview["provisional_credited_hours"] == pytest.approx(
            0.0000, abs=0.0001
        ), "a month with no legs at all credits nothing under the provisional variant"
        assert preview["provisional_gross_charge_cents"] == 2400000, (
            "the provisional gross charge is 5.0000 guaranteed hours at 480,000 cents"
        )
        assert preview["final_credited_hours"] == pytest.approx(0.0000, abs=0.0001), (
            "the final variant has no completed and no lessee-cancelled leg to credit"
        )
        assert preview["final_shortfall_hours"] == pytest.approx(5.0000, abs=0.0001), (
            "zero credited hours fall the whole 5.0000-hour guarantee short"
        )
        assert preview["final_overrun_hours"] == pytest.approx(0.0000, abs=0.0001), (
            "a month below its guarantee produces no overrun hours"
        )
        assert preview["final_gross_charge_cents"] == 2400000, (
            "the shortfall is not lessor-attributable, so the final gross charge is the "
            "undiscounted 2,400,000-cent guarantee"
        )
        assert preview["reliability_penalty_cents"] == 0, (
            "no reliability report has been accepted for the month"
        )
        assert preview["projected_final_charge_cents"] == 2400000, (
            "the projected final charge is the final gross charge less a zero penalty"
        )

    def test_preview_persists_nothing_and_reads_the_same_for_the_lessee(self, api):
        """PRD §3.8: A non-mutating computed read evaluates both variants side by side without persisting anything.
        PRD §3.8: `shortfall_credit_cents` is `lessor_attributable_shortfall_hours` multiplied by that same rate and by the lease's `shortfall_credit_pct`, rounded half up to whole cents.
        PRD §2.4: `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.
        PRD §2.11: Whichever variant most recently wrote a period's credited and shortfall/overrun fields is recorded in `variant_applied`, which holds either `PROVISIONAL` or `FINAL`.
        PRD §2.1: When `X-User-Role` is `Lessee`, `X-User-ID` is the `id` of the acting `Lessee` row; ownership checks on any resource that references a `Lessee` compare the `lessee_id` of the `LeaseAgreement` that owns the target resource to `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

        Design: Corner/endpoints/settlement_preview_is_a_pure_read_that_persists_nothing
        """
        scenario = _active_lease_with_an_empty_september(api)
        period_id = scenario["period"]["id"]
        version_before = scenario["period"]["version"]

        get_success_data(api.get_settlement_preview(period_id, BILLING))
        between = validate_success(api.get_utilization_period(period_id, BILLING), 200)

        assert between["version"] == version_before, (
            "a non-mutating read must leave the period's version untouched"
        )
        assert between["status"] == "OPEN", (
            "previewing a month does not close it"
        )
        assert between["variant_applied"] == "PROVISIONAL", (
            "evaluating the final variant inside the preview must not rewrite "
            "variant_applied"
        )
        assert between["shortfall_credit_cents"] == 0, (
            "no leg was cancelled by the lessor, so no shortfall credit is persisted"
        )

        lessee_preview = validate_success(
            api.get_settlement_preview(period_id, scenario["lessee_headers"]), 200
        )
        assert lessee_preview["projected_final_charge_cents"] == 2400000, (
            "the lessee owning the lease reads the same projected charge as the desk"
        )

        after = validate_success(api.get_utilization_period(period_id, BILLING), 200)
        assert after["version"] == version_before, (
            "two previews in a row still leave the period's version untouched"
        )


class TestCrewQualificationJoin:
    def test_enrolment_creates_a_training_record_naming_both_sides(self, api):
        """PRD §3.4: Operations control enrols a crew member for a specific lease by supplying `crew_member_id` and `lease_id`, creating a `CrewQualification` in `status` `TRAINING` — the other states being `QUALIFIED`, `EXPIRED` and the terminal `REVOKED`.
        PRD §3.4: Operations control records it by supplying `differences_training_completed_on`, the `YYYY-MM-DD` date the lessee-procedures differences course was completed, and `checkride_valid_until`, the `YYYY-MM-DD` date the line check expires.
        PRD §4: Operations that bring a new resource into existence — registering a lessee, an airframe or a crew member, drafting a lease, filing a docket, attaching a certificate, enrolling a qualification, scheduling a leg, requesting a substitution, preparing an invoice, filing a reliability report, or serving termination (which creates the return-conditions record) — return `201 Created`.

        Design: Corner/endpoints/crew_qualification_joins_a_crew_member_to_a_lease_and_is_reachable_from_both_sides
        """
        scenario = _approved_lease_and_an_unqualified_captain(api)

        qualification = validate_success(
            api.create_crew_qualification(
                create_crew_qualification_payload(
                    scenario["captain"]["id"], scenario["lease"]["id"]
                ),
                OPS,
            ),
            201,
        )

        assert qualification["status"] == "TRAINING", (
            "enrolment starts the qualification in TRAINING, not QUALIFIED"
        )
        assert qualification["crew_member_id"] == scenario["captain"]["id"], (
            "the join row names the enrolled crew member"
        )
        assert qualification["lease_id"] == scenario["lease"]["id"], (
            "the join row names the lease the crew member is being trained for"
        )
        assert qualification["differences_training_completed_on"] is None, (
            "the differences-course date is only written when the checkride is recorded"
        )
        assert qualification["checkride_valid_until"] is None, (
            "the line-check expiry is only written when the checkride is recorded"
        )

    def test_the_same_qualification_is_reachable_from_crew_and_lease_and_partitioned_by_status(
        self, api
    ):
        """PRD §3.4: The pairing is many-to-many: one crew member may hold qualifications on several leases, and one lease qualifies many crew members.
        PRD §2.3: Crew qualifications accept `crew_member_id`, `lease_id` and `status`.
        PRD §2.3: All filters are optional and combine conjunctively.
        PRD §2.3: List responses report `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope.

        Design: Corner/endpoints/crew_qualification_joins_a_crew_member_to_a_lease_and_is_reachable_from_both_sides
        """
        scenario = _approved_lease_and_an_unqualified_captain(api)
        crew_id = scenario["captain"]["id"]
        lease_id = scenario["lease"]["id"]
        qualification = get_success_data(
            api.create_crew_qualification(
                create_crew_qualification_payload(crew_id, lease_id), OPS
            )
        )

        by_crew, crew_meta = validate_paginated(
            api.list_crew_qualifications(OPS, {"crew_member_id": crew_id})
        )
        assert crew_meta["total_count"] == 1, (
            "the join row is reachable from the crew member's side"
        )
        assert by_crew[0]["lease_id"] == lease_id, (
            "the row reached by crew_member_id carries the lease it joins to"
        )

        in_training, training_meta = validate_paginated(
            api.list_crew_qualifications(TECH, {"lease_id": lease_id, "status": "TRAINING"})
        )
        assert training_meta["total_count"] == 1, (
            "the same row is reachable from the lease's side under its TRAINING status"
        )
        assert in_training[0]["crew_member_id"] == crew_id, (
            "the row reached by lease_id carries the crew member it joins to"
        )
        assert in_training[0]["id"] == qualification["id"], (
            "both sides of the join reach one and the same qualification row"
        )

        _qualified, qualified_meta = validate_paginated(
            api.list_crew_qualifications(
                scenario["lessee_headers"], {"lease_id": lease_id, "status": "QUALIFIED"}
            )
        )
        assert qualified_meta["total_count"] == 0, (
            "the status filter must partition: the same lease_id query returns nothing "
            "under QUALIFIED while the row is still in TRAINING"
        )


class TestUtilizationPeriodClose:
    def test_close_is_refused_while_a_leg_is_open_and_settles_the_month_once_it_is_cancelled(
        self, api
    ):
        """PRD §3.8: A `BillingAdmin` closes an `OPEN` period, which is admissible only when no leg of the lease whose `scheduled_out` falls inside `period_month` is still `SCHEDULED` or `DISPATCHED`; otherwise the rejection is `ERR_PERIOD_INVALID_STATE` (HTTP 409), which is also the rejection for any period transition requested from an undeclared source status.
        PRD §3.6: A `SCHEDULED` leg cancelled by the lessee moves to `CANCELLED_LESSEE`; cancelled by the lessor it moves to `CANCELLED_LESSOR`.
        PRD §3.6: The leg is created with `status` `SCHEDULED` and `billing_state` `UNBILLED`; `actual_out`, `actual_in`, `cancelling_party` and `cancel_reason` are all null, `technical_delay_minutes` is 0, `block_minutes` and `billable_block_minutes` are 0, and `crew_requalification_required` is false.
        PRD §3.6: `billable_block_minutes` is then set by leg class.
        PRD §3.8: To that is added, for every leg whose `status` is `CANCELLED_LESSEE`, a contribution of half its `scheduled_block_minutes` — the lessee pays for half of what it cancelled.
        PRD §3.8: When `credited_hours` is strictly less than `mgh_effective_hours`, `shortfall_hours` is their difference rounded half up to four decimal places and `overrun_hours` is 0.
        PRD §3.8: Closing recomputes every charge field under the `FINAL` variant, sets `variant_applied` to `FINAL`, writes `final_charge_cents`, and increments the period's `version`.
        PRD §3.8: Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure.

        Design: Corner/endpoints/period_close_is_blocked_while_a_leg_is_still_open_and_succeeds_once_it_is_cancelled
        """
        scenario = _active_lease_with_one_open_september_leg(api)
        period_id = scenario["period"]["id"]

        validate_error(
            api.close_utilization_period(period_id, BILLING),
            ApiErrorId.ERR_PERIOD_INVALID_STATE,
        )

        blocked = validate_success(api.get_utilization_period(period_id, BILLING), 200)
        assert blocked["status"] == "OPEN", (
            "a refused close must leave the period OPEN"
        )

        cancelled = validate_success(
            api.cancel_flight_leg(
                scenario["leg"]["id"],
                cancel_leg_payload("LESSEE", "COMMERCIAL"),
                OPS,
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED_LESSEE", (
            "a SCHEDULED leg cancelled by the lessee lands in CANCELLED_LESSEE"
        )
        assert cancelled["billable_block_minutes"] == 0, (
            "a cancelled leg bills no block minutes of its own"
        )

        before_close = validate_success(
            api.get_utilization_period(period_id, BILLING), 200
        )

        closed = validate_success(api.close_utilization_period(period_id, BILLING), 200)

        assert closed["status"] == "PENDING_SETTLEMENT", (
            "with no open leg left the month closes into PENDING_SETTLEMENT"
        )
        assert closed["variant_applied"] == "FINAL", (
            "the close rewrites the charge fields under the final variant"
        )
        assert closed["credited_hours"] < closed["mgh_effective_hours"], (
            "the final variant credits only half of the lessee-cancelled leg, which "
            "leaves the month strictly below its 5.0000-hour guarantee"
        )
        assert closed["overrun_hours"] == pytest.approx(0.0000, abs=0.0001), (
            "a month decided strictly below its guarantee produces no overrun hours"
        )
        assert closed["lessor_attributable_shortfall_hours"] == pytest.approx(
            0.0000, abs=0.0001
        ), "the lessee cancelled the leg, so none of the shortfall is lessor-attributable"
        assert closed["shortfall_credit_cents"] == 0, (
            "with no lessor-attributable shortfall hours no credit is due"
        )
        assert closed["final_charge_cents"] == 2400000, (
            "the month settles at the bare 2,400,000-cent guarantee"
        )
        assert closed["version"] == before_close["version"] + 1, (
            "closing the month increments the period's version by exactly one"
        )


class TestCollectionListings:
    def test_each_listing_is_reachable_through_its_foreign_key_filter(self, api):
        """PRD §2.3: Leases may be filtered by `lessee_id`, `primary_aircraft_id` and `status`.
        PRD §2.3: Reliability reports accept `lease_id`, `aircraft_id`, `status` and `period_month`.
        PRD §2.3: Return-condition records accept `lease_id`, `aircraft_id`, `repositioning_leg_id` and `status`.
        PRD §2.3: All filters are optional and combine conjunctively.
        PRD §3.10: And a `ReturnCondition` record is created for the lease against the airframe that is the lease's `primary_aircraft_id` at that moment, with `status` `PENDING_INSPECTION`, `discrepancy_codes` empty, `discrepancy_cost_cents` 0, `billed_to_lessee_cents` 0 and `repositioning_leg_id` null.
        PRD §3.8: Acceptance moves the report from `SUBMITTED` to the terminal `ACCEPTED`, which both unblocks invoice approval for the same lease and month and feeds `technical_dispatch_reliability_pct` into the penalty on the next close.

        Design: Corner/endpoints/the_four_remaining_collection_listings_filter_by_fk_and_reject_out_of_range_paging
        """
        scenario = _terminated_lease_with_report_and_return_record(api)
        lease_id = scenario["lease"]["id"]
        aircraft_id = scenario["aircraft"]["id"]

        leases, leases_meta = validate_paginated(
            api.list_leases(BILLING, {"lessee_id": scenario["lessee"]["id"]})
        )
        assert leases_meta["total_count"] == 1, (
            "the lessee's single lease is reachable through the lessee_id filter"
        )
        assert leases[0]["id"] == lease_id, (
            "the lease reached through the filter is the terminated one"
        )
        assert leases[0]["status"] == "TERMINATING", (
            "the served termination left the lease TERMINATING"
        )

        _drafts, drafts_meta = validate_paginated(
            api.list_leases(BILLING, {"status": "DRAFT"})
        )
        assert drafts_meta["total_count"] == 0, (
            "a filter that matches nothing returns an empty page, never a 404"
        )

        dockets, dockets_meta = validate_paginated(
            api.list_lease_regulatory_approvals(lease_id, scenario["lessee_headers"])
        )
        assert dockets_meta["total_count"] == 1, (
            "the lease's docket is reachable from the nested lease path"
        )
        assert dockets[0]["authority_docket_no"] == "CAA-2026-4471", (
            "the docket carries the authority reference it was filed under"
        )
        assert dockets[0]["determination"] == "APPROVED", (
            "the docket was ruled APPROVED before activation"
        )

        reports, reports_meta = validate_paginated(
            api.list_reliability_reports(
                TECH, {"lease_id": lease_id, "aircraft_id": aircraft_id}
            )
        )
        assert reports_meta["total_count"] == 1, (
            "the lease-and-airframe filters combine conjunctively onto the one report"
        )
        assert reports[0]["status"] == "ACCEPTED", (
            "the lessee accepted the filed report"
        )
        assert reports[0]["period_month"] == "2026-09", (
            "the report was filed for 2026-09"
        )

        returns, returns_meta = validate_paginated(
            api.list_return_conditions(TECH, {"lease_id": lease_id})
        )
        assert returns_meta["total_count"] == 1, (
            "termination opened exactly one return record on the lease"
        )
        assert returns[0]["lease_id"] == lease_id, (
            "the return record is reachable from the lease that owns it"
        )
        assert returns[0]["aircraft_id"] == aircraft_id, (
            "the return record names the lease's primary airframe at termination"
        )
        assert returns[0]["status"] == "PENDING_INSPECTION", (
            "a freshly opened return record awaits inspection"
        )
        assert returns[0]["discrepancy_cost_cents"] == 0, (
            "no discrepancy has been priced before the inspection"
        )

        on_bounds, on_bounds_meta = validate_paginated(
            api.list_lease_regulatory_approvals(
                lease_id, scenario["lessee_headers"], {"limit": 100, "offset": 0}
            )
        )
        assert on_bounds_meta["total_count"] == 1, (
            "a limit of exactly 100 with an offset of exactly 0 sits on both accepted "
            "bounds and returns the docket"
        )
        assert on_bounds[0]["id"] == dockets[0]["id"], (
            "paging on the bounds returns the same docket as the unpaged listing"
        )

    @pytest.mark.parametrize(
        "listing,params",
        [
            ("leases", {"limit": 0}),
            ("return_conditions", {"limit": 101}),
            ("reliability_reports", {"offset": -1}),
        ],
    )
    def test_paging_outside_the_accepted_window_is_rejected(self, api, listing, params):
        """PRD §2.3: `limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum is 100.
        PRD §2.3: `offset` is the number of rows to skip; it defaults to 0 and its minimum accepted value is 0.
        PRD §2.3: A `limit` that is not an integer within the inclusive range from 1 to 100, or an `offset` that is not an integer of at least 0, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/endpoints/the_four_remaining_collection_listings_filter_by_fk_and_reject_out_of_range_paging
        """
        _terminated_lease_with_report_and_return_record(api)
        listers = {
            "leases": api.list_leases,
            "return_conditions": api.list_return_conditions,
            "reliability_reports": api.list_reliability_reports,
        }

        validate_error(listers[listing](BILLING, params), ApiErrorId.ERR_INVALID_REQUEST)
