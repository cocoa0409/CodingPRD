"""Recoupment demands: interest accrual (period floor, tiers, cap, hold
exclusion), principal bounds, OCC on adjustments, hold/release cycling driven
by the appeal ladder, and the zero-outstanding boundary."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_remittance,
    decide_appeal,
    file_appeal,
    get_demand,
    make_payer_agent_headers,
    manual_offset,
    manual_offset_payload,
    open_appeal,
    setup_case_with_demand,
    setup_determined_case,
    setup_hold_cycle_scenario,
    setup_hold_follows_scenario,
    setup_tiered_interest_pair,
    adjust_demand_payload,
    validate_error,
    validate_success,
    withdraw_appeal,
)
from test_helpers import TEST_USERS

ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestInterestAccrual:
    def test_zero_interest_before_first_period_completes(self, api):
        """PRD §3.7: "The number of elapsed periods is the count of whole
        thirty-day periods inside the eligible time; a partial period counts
        for nothing, and zero periods means zero interest."

        Design: Corner/calculations/interest_zero_before_first_period
        """
        _ctx, demand = setup_case_with_demand(
            billed=1000000, principal=1000000,
            issued_at="2026-08-01T00:00:00Z")
        advance_clock("2026-08-30T00:00:00Z")
        assert get_demand(demand["id"])["accrued_interest_cents"] == 0, (
            "29 days is zero complete thirty-day periods")
        advance_clock("2026-08-31T00:00:00Z")
        assert get_demand(demand["id"])["accrued_interest_cents"] == 10000, (
            "30 days completes one period: 1000000 * 100bps / 10000")

    def test_interest_cap_binds_at_ceiling(self, api):
        """PRD §3.7: "That raw figure is then capped: the cap is the at-issue
        principal — the `principal_cents` recorded at creation, before any
        later adjustment — multiplied by the `interest_cap_pct_snapshot` and
        divided by one hundred, and the accrued interest is the smaller of the
        raw figure and the cap, rounded half up to whole cents."

        Design: Corner/calculations/interest_cap_binds_at_ceiling
        """
        _ctx, demand = setup_case_with_demand(
            billed=100000, principal=100000,
            payer_overrides={"interest_rate_bps_tier2": 1000},
            issued_at="2026-08-01T00:00:00Z")
        advance_clock("2027-06-07T00:00:00Z")
        demand = get_demand(demand["id"])
        assert demand["accrued_interest_cents"] == 25000, (
            "Ten periods of raw interest (82000) are capped at 25% of the "
            "at-issue principal")
        assert demand["interest_cap_pct_snapshot"] == 25

    def test_tiered_accrual_without_hold(self, api):
        """PRD §3.7: "the raw interest is the outstanding principal multiplied
        by the summed per-period charge — the tier-one snapshot rate applied
        once for each of the first two periods, and the tier-two snapshot rate
        applied once for each period beyond the second — divided by ten
        thousand."

        Design: Difficulty/combinatorial_formula/interest_accrual_tiered_with_hold_exclusion
        """
        scn = setup_tiered_interest_pair()
        d1 = get_demand(scn["d1"]["id"])
        assert d1["accrued_interest_cents"] == 40000, (
            "90 days is 3 periods: 1000000 * (100*2 + 200*1) / 10000")
        assert d1["accumulated_hold_seconds"] == 0

    def test_hold_seconds_excluded_from_accrual(self, api):
        """PRD §3.7: "The eligible time is the interval from `issued_at` to the
        logical now, minus the `accumulated_hold_seconds` already banked, minus
        — while a hold is currently open — the interval from `hold_started_at`
        to now."
        PRD §3.7: "Because hold intervals are excluded from eligible time, a
        demand accrues no interest while its collection is frozen by a live
        appeal."

        Design: Difficulty/combinatorial_formula/interest_accrual_tiered_with_hold_exclusion
        """
        scn = setup_tiered_interest_pair()
        d2 = get_demand(scn["d2"]["id"])
        assert d2["accumulated_hold_seconds"] == 2592000, (
            "The 30-day hold (2026-08-11 to 2026-09-10) is banked in seconds")
        assert d2["accrued_interest_cents"] == 20000, (
            "Only 60 eligible days: 2 periods at tier1 -> "
            "1000000 * 100 * 2 / 10000")


class TestDemandPrincipalBounds:
    def test_demand_exceeding_active_denied_total_rejected(self, api):
        """PRD §3.7: "The principal must be positive (`ERR_INVALID_REQUEST`)
        and may not exceed the case's `total_denied_active_cents`; a demand
        that overreaches the actively denied dollars is rejected with
        `ERR_DEMAND_EXCEEDS_DENIED` (HTTP 409)."

        Design: Corner/validations/demand_exceeds_denied_rejected
        """
        ctx = setup_determined_case(billed_amounts=(100000,))
        resp = api.create_recoupment_demand(
            ctx["case"]["id"], {"principal_cents": 100001},
            make_payer_agent_headers(ctx["payer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DEMAND_EXCEEDS_DENIED)


class TestDemandAdjustmentOcc:
    def test_stale_expected_version_rejected_then_fresh_succeeds(self, api):
        """PRD §2.7: "`POST /recoupment-demands/{id}/adjustments` requires the
        non-optional field `expected_recoupment_demand_version`, carrying the
        recoupment demand `version` the client last observed. A mismatch with
        the demand's current version is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "A successful adjustment recomputes
        `outstanding_principal_cents` and increments the demand's `version` by
        one; it never changes the demand's status."

        Design: Corner/cross_cutting/occ_demand_adjustment_stale_version
        """
        ctx, demand = setup_case_with_demand(billed=100000, principal=100000)
        assert demand["version"] == 1
        payer_id = ctx["payer"]["id"]
        adjusted = validate_success(api.adjust_recoupment_demand(
            demand["id"], adjust_demand_payload(80000, 1),
            make_payer_agent_headers(payer_id)), 200)
        assert adjusted["version"] == 2
        assert adjusted["outstanding_principal_cents"] == 80000
        assert adjusted["status"] == "DEMANDED"
        stale = api.adjust_recoupment_demand(
            demand["id"], adjust_demand_payload(70000, 1),
            make_payer_agent_headers(payer_id))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        retried = validate_success(api.adjust_recoupment_demand(
            demand["id"], adjust_demand_payload(70000, 2),
            make_payer_agent_headers(payer_id)), 200)
        assert retried["outstanding_principal_cents"] == 70000


class TestZeroOutstandingBoundary:
    def test_offset_leaving_one_cent_is_partial(self, api):
        """PRD §3.7: "An applied offset that covers some but not all of what is
        owed moves `DEMANDED → PARTIALLY_RECOUPED`."

        Design: Difficulty/boundary_precision_check/demand_zero_outstanding_full_vs_partial
        """
        _ctx, demand = setup_case_with_demand(billed=50000, principal=50000)
        rem = create_remittance(_ctx["payer"]["id"], 100000)
        offset = manual_offset(demand["id"], rem["id"], 49999)
        assert offset["interest_portion_cents"] == 0, (
            "Same-clock application accrues no interest")
        assert offset["principal_portion_cents"] == 49999
        after = get_demand(demand["id"])
        assert after["status"] == "PARTIALLY_RECOUPED"
        assert after["outstanding_principal_cents"] == 1

    def test_offset_to_exactly_zero_is_fully_recouped(self, api):
        """PRD §3.7: "One that drives the outstanding principal to zero —
        which, because interest is always satisfied before principal, means
        the accrued interest was covered in full at the same time — moves
        `DEMANDED` or `PARTIALLY_RECOUPED → FULLY_RECOUPED`."

        Design: Difficulty/boundary_precision_check/demand_zero_outstanding_full_vs_partial
        """
        _ctx, demand = setup_case_with_demand(billed=50000, principal=50000)
        rem = create_remittance(_ctx["payer"]["id"], 100000)
        manual_offset(demand["id"], rem["id"], 49999)
        manual_offset(demand["id"], rem["id"], 1)
        after = get_demand(demand["id"])
        assert after["status"] == "FULLY_RECOUPED"
        assert after["outstanding_principal_cents"] == 0


class TestDemandHoldFollowsAppeal:
    def test_filing_holds_demand_only_when_level_configured(self, api):
        """PRD §3.4: "Filing has a monetary side effect: when the filed
        appeal's `level` is among the payer's `hold_levels`, every recoupment
        demand of the case currently `DEMANDED` or `PARTIALLY_RECOUPED` moves
        to `ON_HOLD` with `hold_started_at` stamped (§3.7)."

        Design: Difficulty/cross_entity_state_dependency/demand_hold_follows_appeal_filing
        """
        scn = setup_hold_follows_scenario()
        file_appeal(scn["ap1"]["id"])
        assert get_demand(scn["d1"]["id"])["status"] == "DEMANDED", (
            "hold_levels empty: the filing does not gate the demand")
        file_appeal(scn["ap2"]["id"])
        assert get_demand(scn["d2"]["id"])["status"] == "ON_HOLD", (
            "LEVEL_1 in hold_levels: the filing holds the demand")

    def test_held_demand_rejects_offset_and_releases_on_withdraw(self, api):
        """PRD §3.8: "the demand must be `DEMANDED` or `PARTIALLY_RECOUPED` —
        an `ON_HOLD` demand is rejected with the specialized
        `ERR_DEMAND_ON_HOLD` (HTTP 409)"
        PRD §3.4: "From `PENDING_DECISION`, withdrawal moves `PENDING_DECISION
        → WITHDRAWN` and releases the recoupment hold the filing created
        (§3.7)."

        Design: Difficulty/cross_entity_state_dependency/demand_hold_follows_appeal_filing
        """
        scn = setup_hold_follows_scenario()
        file_appeal(scn["ap2"]["id"])
        assert get_demand(scn["d2"]["id"])["status"] == "ON_HOLD"
        resp = api.create_manual_offset(
            scn["d2"]["id"],
            manual_offset_payload(scn["rem2"]["id"], 50000), ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_DEMAND_ON_HOLD)
        withdraw_appeal(scn["ap2"]["id"])
        assert get_demand(scn["d2"]["id"])["status"] == "DEMANDED"
        offset = manual_offset(scn["d2"]["id"], scn["rem2"]["id"], 50000)
        assert offset["status"] == "APPLIED"


class TestHoldReleaseCycle:
    def test_first_hold_banks_ten_days_on_release(self, api):
        """PRD §3.7: "When that holding appeal is subsequently decided or
        withdrawn, each held demand returns to `DEMANDED` if it has no
        `APPLIED` offsets, or to `PARTIALLY_RECOUPED` if it has some; the
        just-ended hold interval is added into `accumulated_hold_seconds`; and
        `hold_started_at` is cleared to null."

        Design: Difficulty/non_linear_state_machine/recoupment_demand_hold_release_cycle
        """
        scn = setup_hold_cycle_scenario()
        demand_id = scn["demand"]["id"]
        file_appeal(scn["appeal"]["id"])
        assert get_demand(demand_id)["status"] == "ON_HOLD"
        advance_clock("2026-08-11T00:00:00Z")
        decide_appeal(scn["appeal"]["id"], scn["ctx"]["payer"]["id"],
                      "UNFAVORABLE", 500000)
        released = get_demand(demand_id)
        assert released["status"] == "DEMANDED"
        assert released["accumulated_hold_seconds"] == 864000, (
            "The ten-day first hold is banked")
        assert released["hold_started_at"] is None

    def test_cycle_repeats_at_next_level(self, api):
        """PRD §3.7: "When an appeal whose `level` appears in the payer's
        `hold_levels` reaches `PENDING_DECISION`, every demand of the case in
        `DEMANDED` or `PARTIALLY_RECOUPED` moves to `ON_HOLD` with
        `hold_started_at` stamped at the logical now."

        Design: Difficulty/non_linear_state_machine/recoupment_demand_hold_release_cycle
        """
        scn = setup_hold_cycle_scenario()
        demand_id = scn["demand"]["id"]
        payer_id = scn["ctx"]["payer"]["id"]
        line_id = scn["ctx"]["lines"][0]["id"]
        file_appeal(scn["appeal"]["id"])
        advance_clock("2026-08-11T00:00:00Z")
        decide_appeal(scn["appeal"]["id"], payer_id, "UNFAVORABLE", 500000)
        ap2 = open_appeal(line_id)
        assert ap2["level"] == "LEVEL_2"
        file_appeal(ap2["id"])
        assert get_demand(demand_id)["status"] == "ON_HOLD", (
            "The cycle repeats when the LEVEL_2 appeal reaches "
            "PENDING_DECISION")
