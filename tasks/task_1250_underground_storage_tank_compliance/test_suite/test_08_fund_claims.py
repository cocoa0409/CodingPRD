"""State fund claims: dual-election payable math, fund-cap accounting,
adjudication, and creation gates (PRD §3.8)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_owner_headers,
    set_clock, create_facility, create_tank, create_release_event_payload,
    setup_confirmed_release_site, create_draft_claim, get_facility,
    setup_active_facility_with_tank,
    setup_failed_cp_order, create_technician, create_order, schedule_order,
    start_order, record_results, tightness_readings, get_tank,
    FUND_YEAR_CAP_CENTS, OCCURRENCE_DEDUCTIBLE_CENTS,
    AGGREGATE_YEAR_DEDUCTIBLE_CENTS,
    api_client,
)

OWNER = TEST_USERS["facility_owner_headers"]
OWNER2 = TEST_USERS["facility_owner_2_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
REGULATOR = TEST_USERS["state_regulator_headers"]
READER = TEST_USERS["any_headers"]


class TestElectionVariants:
    def _setup_both_elections(self):
        set_clock("2026-05-01T00:00:00Z")
        site1 = setup_confirmed_release_site("owner-1", "PER_OCCURRENCE")
        site2 = setup_confirmed_release_site("owner-2", "AGGREGATE")
        return site1, site2

    def test_per_occurrence_payable_math(self, api):
        """PRD §3.8: "Under the `PER_OCCURRENCE` election, `deductible_applied_cents`
        is the lesser of the expense total and the fixed per-occurrence deductible
        of 1000000 cents (ten thousand dollars); `eligible_amount_cents` is the
        expense total minus the deductible, floored at zero; and
        `payable_amount_cents` is the eligible amount multiplied by a coinsurance
        rate of 0.90, with the single product rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/fund_claim_election_changes_payable
        """
        site1, _ = self._setup_both_elections()
        claim = create_draft_claim(site1["facility"]["id"], site1["release"]["id"],
                                   3000000, "owner-1")
        assert claim["deductible_applied_cents"] == 1000000
        assert claim["eligible_amount_cents"] == 2000000
        # round_half_up(2000000 * 0.90) = 1800000
        assert claim["payable_amount_cents"] == 1800000

    def test_aggregate_election_changes_payable(self, api):
        """PRD §3.8: "Under the `AGGREGATE` election, `deductible_applied_cents` is
        instead the lesser of the expense total and the facility's remaining
        `fund_year_deductible_remaining_cents` pool; `eligible_amount_cents` is the
        expense total minus that deductible; and `payable_amount_cents` equals the
        eligible amount in full — the fund pays 100% once the aggregate deductible
        is exhausted. Identical expense lines therefore yield different payables
        under the two elections."

        Design: Difficulty/dual_variant_calc/fund_claim_election_changes_payable
        """
        site1, site2 = self._setup_both_elections()
        claim1 = create_draft_claim(site1["facility"]["id"], site1["release"]["id"],
                                    3000000, "owner-1")
        claim2 = create_draft_claim(site2["facility"]["id"], site2["release"]["id"],
                                    3000000, "owner-2")
        assert claim2["deductible_applied_cents"] == 2000000, (
            "aggregate pool drained first (min(3000000, 2000000))")
        assert claim2["eligible_amount_cents"] == 1000000
        assert claim2["payable_amount_cents"] == 1000000, "100% after deductible"
        assert claim1["payable_amount_cents"] != claim2["payable_amount_cents"], (
            "identical expense lines diverge across the two elections")


class TestFundCapBoundary:
    def _setup_claim_at_cap(self):
        """Claim whose payable equals the full fund-year cap:
        round_half_up((112111111 - 1000000) * 0.90) = round_half_up(99999999.9)
        = 100000000."""
        set_clock("2026-05-01T00:00:00Z")
        site = setup_confirmed_release_site("owner-1", "PER_OCCURRENCE")
        claim = create_draft_claim(site["facility"]["id"], site["release"]["id"],
                                   112111111, "owner-1")
        return site, claim

    def test_fund_claim_payable_equals_cap_submits(self, api):
        """PRD §3.8: "Submitting a claim moves it `DRAFT` → `SUBMITTED`
        (`ERR_CLAIM_NOT_DRAFT` otherwise), re-checks the payable against
        `fund_cap_remaining_cents` (`ERR_FUND_CAP_EXCEEDED`), and reserves the
        money by subtracting `payable_amount_cents` from the facility's cap."

        Design: Difficulty/boundary_precision_check/fund_claim_payable_equals_cap_submits
        """
        site, claim = self._setup_claim_at_cap()
        assert claim["payable_amount_cents"] == FUND_YEAR_CAP_CENTS == 100000000
        submitted = validate_success(
            api.submit_claim(claim["id"], make_owner_headers("owner-1")), 200)
        assert submitted["status"] == "SUBMITTED", (
            "payable == cap remaining satisfies the inclusive reservation check")

    def test_fund_claim_at_cap_drives_remaining_to_zero(self, api):
        """PRD §3.8: "reserves the money by subtracting `payable_amount_cents` from
        the facility's cap."

        Design: Difficulty/boundary_precision_check/fund_claim_payable_equals_cap_submits
        """
        site, claim = self._setup_claim_at_cap()
        validate_success(api.submit_claim(claim["id"], make_owner_headers("owner-1")), 200)
        facility = get_facility(site["facility"]["id"])
        assert facility["fund_cap_remaining_cents"] == 0, (
            "boundary: cap driven exactly to zero, not negative, not rejected")


class TestSubmitWithdrawInvariant:
    def _setup_3m_claim(self):
        set_clock("2026-05-01T00:00:00Z")
        site = setup_confirmed_release_site("owner-1", "PER_OCCURRENCE")
        claim = create_draft_claim(site["facility"]["id"], site["release"]["id"],
                                   3000000, "owner-1")
        return site, claim

    def test_submit_reserves_payable_against_cap(self, api):
        """PRD §3.8: "reserves the money by subtracting `payable_amount_cents` from
        the facility's cap."

        Design: Difficulty/compensating_invariant/claim_submit_withdraw_restores_fund_cap
        """
        site, claim = self._setup_3m_claim()
        assert claim["payable_amount_cents"] == 1800000
        assert get_facility(site["facility"]["id"])["fund_cap_remaining_cents"] == 100000000

        validate_success(api.submit_claim(claim["id"], make_owner_headers("owner-1")), 200)
        facility = get_facility(site["facility"]["id"])
        assert facility["fund_cap_remaining_cents"] == 100000000 - 1800000 == 98200000

    def test_withdraw_releases_reservation_exactly(self, api):
        """PRD §3.8: "withdrawing a `SUBMITTED` claim releases the reservation,
        adding `payable_amount_cents` back to the cap, while withdrawing a `DRAFT`
        claim releases nothing because nothing was reserved."

        Design: Difficulty/compensating_invariant/claim_submit_withdraw_restores_fund_cap
        """
        site, claim = self._setup_3m_claim()
        owner = make_owner_headers("owner-1")
        validate_success(api.submit_claim(claim["id"], owner), 200)
        withdrawn = validate_success(api.withdraw_claim(claim["id"], owner), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        facility = get_facility(site["facility"]["id"])
        assert facility["fund_cap_remaining_cents"] == 100000000, (
            "submit + withdraw leaves the fund-year cap exactly unchanged")


class TestAdjudication:
    def test_adjudicate_partial_denied_approved_cap_effects(self, api):
        """PRD §3.8: "An approval sets `approved_amount_cents` equal to
        `payable_amount_cents` and consumes the reservation; a partial approval
        sets it to the supplied value and releases the unused difference back into
        the cap; a denial sets it to zero and releases the entire reservation."

        Design: Corner/endpoints/adjudicate_partial_denied_approved_cap_effects
        """
        set_clock("2026-05-01T00:00:00Z")
        site = setup_confirmed_release_site("owner-1", "PER_OCCURRENCE")
        fac_id, rel_id = site["facility"]["id"], site["release"]["id"]
        c1 = create_draft_claim(fac_id, rel_id, 3000000)   # payable 1800000
        c2 = create_draft_claim(fac_id, rel_id, 3000000)   # payable 1800000
        c3 = create_draft_claim(fac_id, rel_id, 1500000)   # payable 450000
        owner = make_owner_headers("owner-1")

        validate_success(api.submit_claim(c1["id"], owner), 200)
        partial = validate_success(api.adjudicate_claim(
            c1["id"], {"decision": "PARTIALLY_APPROVED", "approved_amount_cents": 1000000},
            REGULATOR), 200)
        assert partial["status"] == "PARTIALLY_APPROVED"
        assert partial["approved_amount_cents"] == 1000000
        # 100000000 - 1800000 reserved + (1800000 - 1000000) released
        assert get_facility(fac_id)["fund_cap_remaining_cents"] == 99000000

        validate_success(api.submit_claim(c2["id"], owner), 200)
        denied = validate_success(api.adjudicate_claim(
            c2["id"], {"decision": "DENIED"}, REGULATOR), 200)
        assert denied["status"] == "DENIED" and denied["approved_amount_cents"] == 0
        # 99000000 - 1800000 reserved + 1800000 released
        assert get_facility(fac_id)["fund_cap_remaining_cents"] == 99000000

        validate_success(api.submit_claim(c3["id"], owner), 200)
        approved = validate_success(api.adjudicate_claim(
            c3["id"], {"decision": "APPROVED"}, REGULATOR), 200)
        assert approved["status"] == "APPROVED"
        # approved = payable = round_half_up((1500000 - 1000000) * 0.90) = 450000
        assert approved["approved_amount_cents"] == 450000
        # 99000000 - 450000 reserved, consumed on approval
        assert get_facility(fac_id)["fund_cap_remaining_cents"] == 98550000

        data, meta = validate_paginated(
            api.list_fund_claims(READER, params={"facility_id": fac_id}))
        assert meta["total_count"] == 3

    def test_claim_state_transitions_rejected(self, api):
        """PRD §3.8: "Submitting a claim moves it `DRAFT` → `SUBMITTED`
        (`ERR_CLAIM_NOT_DRAFT` otherwise)"; "Withdrawal is the owner's escape hatch
        from `DRAFT` or `SUBMITTED` (`ERR_CLAIM_NOT_WITHDRAWABLE` otherwise)";
        "Adjudication belongs to the `StateRegulator` and requires `SUBMITTED`
        (`ERR_CLAIM_NOT_SUBMITTED`)"

        Design: Corner/errors/claim_state_transitions_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        site = setup_confirmed_release_site("owner-1", "PER_OCCURRENCE")
        claim = create_draft_claim(site["facility"]["id"], site["release"]["id"],
                                   3000000, "owner-1")
        owner = make_owner_headers("owner-1")

        res = api.adjudicate_claim(claim["id"], {"decision": "APPROVED"}, REGULATOR)
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED, expected_status=409)

        validate_success(api.submit_claim(claim["id"], owner), 200)
        res = api.submit_claim(claim["id"], owner)
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_DRAFT, expected_status=409)

        validate_success(api.adjudicate_claim(claim["id"], {"decision": "APPROVED"},
                                              REGULATOR), 200)
        res = api.withdraw_claim(claim["id"], owner)
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_WITHDRAWABLE, expected_status=409)


class TestClaimCreationGates:
    def test_claim_release_not_confirmed_rejected(self, api):
        """PRD §3.8: "the release must be `CONFIRMED`, `CLEANUP_IN_PROGRESS`, or
        `CLOSED` (`ERR_CLAIM_RELEASE_NOT_CONFIRMED`)"

        Design: Corner/errors/claim_release_not_confirmed_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank(
            facility_overrides={"fund_program_election": "PER_OCCURRENCE"})
        release = validate_success(api.create_release_event(
            create_release_event_payload(facility["id"], source_description="odor"),
            OWNER), 201)  # stays SUSPECTED
        res = api.create_fund_claim(
            {"facility_id": facility["id"], "release_event_id": release["id"],
             "expense_lines": [{"description": "c", "amount_cents": 3000000}]}, OWNER)
        validate_error(res, ApiErrorId.ERR_CLAIM_RELEASE_NOT_CONFIRMED,
                       expected_status=402)

    def test_claim_release_mismatch_rejected(self, api):
        """PRD §3.8: "the release must belong to the same facility
        (`ERR_CLAIM_RELEASE_MISMATCH`)"

        Design: Corner/validations/claim_release_mismatch_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        site1 = setup_confirmed_release_site("owner-1", "PER_OCCURRENCE")
        site2 = setup_confirmed_release_site("owner-2", "PER_OCCURRENCE")
        res = api.create_fund_claim(
            {"facility_id": site1["facility"]["id"],
             "release_event_id": site2["release"]["id"],
             "expense_lines": [{"description": "cleanup", "amount_cents": 3000000}]},
            OWNER)
        validate_error(res, ApiErrorId.ERR_CLAIM_RELEASE_MISMATCH)

    def test_fees_not_current_blocks_claim(self, api):
        """PRD §3.8: "the facility's `annual_fee_paid_through` must be at or after
        the logical clock (`ERR_FEES_NOT_CURRENT`)"

        Design: Corner/validations/fees_not_current_blocks_claim
        """
        set_clock("2026-05-01T00:00:00Z")
        site = setup_confirmed_release_site(
            "owner-1", "PER_OCCURRENCE", fees_through="2026-06-01T00:00:00Z")
        set_clock("2026-07-01T00:00:00Z")  # fees lapsed
        res = api.create_fund_claim(
            {"facility_id": site["facility"]["id"],
             "release_event_id": site["release"]["id"],
             "expense_lines": [{"description": "cleanup", "amount_cents": 3000000}]},
            OWNER)
        validate_error(res, ApiErrorId.ERR_FEES_NOT_CURRENT, expected_status=402)
        data, meta = validate_paginated(api.list_fund_claims(
            READER, params={"facility_id": site["facility"]["id"]}))
        assert meta["total_count"] == 0, "no claim persisted"

    def test_fund_cap_exceeded_at_create_rejected(self, api):
        """PRD §3.8: "the computed payable must fit within the facility's
        `fund_cap_remaining_cents` (`ERR_FUND_CAP_EXCEEDED`)"

        Design: Corner/errors/fund_cap_exceeded_at_create_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        site = setup_confirmed_release_site("owner-1", "PER_OCCURRENCE")
        # payable = round_half_up((200000000 - 1000000) * 0.90) = 179100000 > cap.
        res = api.create_fund_claim(
            {"facility_id": site["facility"]["id"],
             "release_event_id": site["release"]["id"],
             "expense_lines": [{"description": "huge cleanup",
                                "amount_cents": 200000000}]},
            OWNER)
        validate_error(res, ApiErrorId.ERR_FUND_CAP_EXCEEDED, expected_status=402)


class TestPostureGatePriority:
    def _setup_non_compliant_facility(self):
        """Facility driven to posture 50 (NON_COMPLIANT): a MAJOR deficiency from
        a failed CP survey (-15), plus a CRITICAL deficiency and CONFIRMED release
        from a failed tightness test (-25, -10). Returns (facility, release)."""
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_failed_cp_order()  # MAJOR open -> 85
        t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="Tightness Tester")
        tt_order = create_order(ctx["facility"]["id"], ctx["tank"]["id"],
                                "TANK_TIGHTNESS",
                                line_items=[{"description": "tightness", "qty": 1,
                                             "unit_price_cents": 60000}])
        schedule_order(tt_order["id"], t_tt["id"],
                       "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z")
        start_order(tt_order["id"], t_tt["id"], "2026-05-03T10:30:00Z")
        record_results(tt_order["id"], t_tt["id"], tightness_readings(0.5))  # FAIL
        data, _ = validate_paginated(api_client.list_release_events(
            READER, params={"tank_system_id": ctx["tank"]["id"],
                            "status": "SUSPECTED"}))
        release = data[0]
        validate_success(api_client.confirm_release(release["id"], REGULATOR), 200)
        return ctx["facility"], release

    def test_posture_gate_fires_before_fund_cap(self, api):
        """PRD §3.8: "Creation is gated, in the validation precedence of §2.7: the
        facility's `compliance_posture` must not be `NON_COMPLIANT`
        (`ERR_FACILITY_POSTURE_BLOCKS_CLAIM`)"
        PRD §2.7: "9. The facility posture gate on fund claim creation." and "18.
        Fund fiscal gates (release status, fee currency, fund cap)."

        Design: Difficulty/priority_pair_validation_conflict/claim_posture_gate_precedes_fund_cap
        """
        facility, release = self._setup_non_compliant_facility()
        facility = get_facility(facility["id"])
        assert facility["posture_score"] == 50, "100 - 15 MAJOR - 25 CRITICAL - 10 release"
        assert facility["compliance_posture"] == "NON_COMPLIANT"

        # Payable would be 179100000 > 100000000 cap, yet the posture gate (§2.7
        # step 9) must beat the fund-cap gate (§2.7 step 18).
        res = api.create_fund_claim(
            {"facility_id": facility["id"], "release_event_id": release["id"],
             "expense_lines": [{"description": "cleanup",
                                "amount_cents": 200000000}]},
            OWNER)
        validate_error(res, ApiErrorId.ERR_FACILITY_POSTURE_BLOCKS_CLAIM,
                       expected_status=422)

    def test_posture_gate_error_is_422_not_fiscal_402(self, api):
        """PRD §2.9: "The posture gate has teeth: a facility in `NON_COMPLIANT`
        posture cannot open a state fund claim."
        PRD §2.7: "9. The facility posture gate on fund claim creation." and "18.
        Fund fiscal gates (release status, fee currency, fund cap)."

        Design: Difficulty/priority_pair_validation_conflict/claim_posture_gate_precedes_fund_cap
        """
        facility, release = self._setup_non_compliant_facility()
        res = api.create_fund_claim(
            {"facility_id": facility["id"], "release_event_id": release["id"],
             "expense_lines": [{"description": "cleanup",
                                "amount_cents": 200000000}]},
            OWNER)
        error = validate_error(res, ApiErrorId.ERR_FACILITY_POSTURE_BLOCKS_CLAIM,
                               expected_status=422)
        assert res.status_code == 422, "posture (422) fired, not the fiscal 402"
        data, meta = validate_paginated(api.list_fund_claims(
            READER, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 0
