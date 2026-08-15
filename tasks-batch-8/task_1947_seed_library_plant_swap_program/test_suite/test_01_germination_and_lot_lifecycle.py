"""Germination assays, certification, and lot lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    certify_test,
    create_seed_lot,
    create_site,
    create_swap_event,
    create_variety,
    create_volunteer,
    create_packing_session,
    get_lot,
    record_test,
    setup_active_lot,
    setup_quarantine_lot,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestViabilityVariants:
    def test_provisional_viability_drives_viable_seed_count_before_certification(self):
        """PRD §3.3: "The effective viability of a lot — the figure behind
        every viability-dependent decision — is the `final_viability_pct` when
        at least one certified assay exists, and the donor-declared
        `provisional_viability_pct` otherwise. The lot's `viable_seed_count` is
        the loose-seed count multiplied by that effective percentage, divided
        by one hundred, and rounded down to a whole seed".

        1000 seeds at declared 80.00% -> floor(1000 * 80.00 / 100) == 800 while
        no certified assay exists.

        Design: Difficulty/dual_variant_calc/germination_viability_provisional_vs_certified_final
        """
        ctx = setup_quarantine_lot(
            seeds_received=1000, provisional_viability_pct=80.00
        )
        # A RECORDED (not yet certified) assay must not change the valuation.
        record_test(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            seeds_tested=100, sprouted_count=90,
        )
        lot = get_lot(ctx["lot"]["id"])
        assert lot["viable_seed_count"] == 800, (
            f"Expected PROVISIONAL variant floor(1000*80.00/100)=800, "
            f"got {lot['viable_seed_count']}"
        )

    def test_certified_final_viability_overrides_provisional_on_same_lot(self):
        """PRD §3.3: "A `PASS` on a quarantined lot activates it: the lot moves
        `QUARANTINE` → `ACTIVE`, its `final_viability_pct` takes the test's
        `result_pct`, and its `viable_seed_count` is recomputed from the
        loose-seed count against that certified figure."

        Same 1000 loose seeds: certified 90.00% -> floor(1000 * 90.00 / 100)
        == 900, and the lot becomes ACTIVE.

        Design: Difficulty/dual_variant_calc/germination_viability_provisional_vs_certified_final
        """
        ctx = setup_quarantine_lot(
            seeds_received=1000, provisional_viability_pct=80.00
        )
        test = record_test(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            seeds_tested=100, sprouted_count=90,
        )
        certified = certify_test(test["id"], "PASS")
        assert certified["status"] == "CERTIFIED"
        lot = get_lot(ctx["lot"]["id"])
        assert lot["status"] == "ACTIVE", (
            f"Expected lot ACTIVE after PASS, got {lot['status']}"
        )
        assert lot["final_viability_pct"] == 90.0
        assert lot["viable_seed_count"] == 900, (
            f"Expected CERTIFIED_FINAL variant floor(1000*90.00/100)=900, "
            f"got {lot['viable_seed_count']}"
        )


class TestLotRecheckCycle:
    def test_recheck_moves_active_lot_back_to_quarantine(self):
        """PRD §3.2: "A lot already in circulation can be sent back through the
        same door: the scheduled re-test loop moves an `ACTIVE` lot to
        `QUARANTINE` so a fresh assay can be recorded."

        Design: Difficulty/non_linear_state_machine/seed_lot_active_quarantine_recheck_cycle
        """
        ctx = setup_active_lot(seeds_received=500, provisional_viability_pct=90.00)
        assert ctx["lot"]["status"] == "ACTIVE"
        resp = api_client.recheck_seed_lot(ctx["lot"]["id"], ADMIN)
        lot = validate_success(resp, 200)
        assert lot["status"] == "QUARANTINE", (
            f"Expected ACTIVE -> QUARANTINE loop edge, got {lot['status']}"
        )

    def test_second_certification_rewrites_final_viability_and_reactivates(self):
        """PRD §3.3: "A `PASS` on a quarantined lot activates it: the lot moves
        `QUARANTINE` → `ACTIVE`, its `final_viability_pct` takes the test's
        `result_pct`, and its `viable_seed_count` is recomputed from the
        loose-seed count against that certified figure."

        Full A->B->A cycle: second certified assay (85.00) overwrites the first
        (90.00); viable_seed_count becomes floor(500 * 85.00 / 100) == 425.

        Design: Difficulty/non_linear_state_machine/seed_lot_active_quarantine_recheck_cycle
        """
        ctx = setup_active_lot(seeds_received=500, provisional_viability_pct=90.00)
        api_client.recheck_seed_lot(ctx["lot"]["id"], ADMIN)
        test2 = record_test(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            seeds_tested=100, sprouted_count=85,
        )
        certify_test(test2["id"], "PASS")
        lot = get_lot(ctx["lot"]["id"])
        assert lot["status"] == "ACTIVE", (
            f"Expected QUARANTINE -> ACTIVE on second PASS, got {lot['status']}"
        )
        assert lot["final_viability_pct"] == 85.0, (
            f"Second certification must overwrite the first (90.00 -> 85.00), "
            f"got {lot['final_viability_pct']}"
        )
        assert lot["viable_seed_count"] == 425, (
            f"Expected floor(500*85.00/100)=425, got {lot['viable_seed_count']}"
        )


class TestViabilityThresholdBoundary:
    def test_result_exactly_70_admits_pass_and_activates_lot(self):
        """PRD §3.3: "The declared `outcome` must agree with the measured band:
        `PASS` requires a `result_pct` of at least 70.00, and `FAIL` requires
        one strictly below 70.00; disagreement is rejected with
        `ERR_VIABILITY_OUTCOME_MISMATCH`."

        35/50 == 70.00 sits inside the PASS band (inclusive boundary).

        Design: Difficulty/boundary_precision_check/viability_threshold_exactly_70_passes
        """
        ctx = setup_quarantine_lot(
            seeds_received=100, provisional_viability_pct=70.00
        )
        test = record_test(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            seeds_tested=50, sprouted_count=35,
        )
        assert test["result_pct"] == 70.0
        certified = certify_test(test["id"], "PASS")
        assert certified["status"] == "CERTIFIED"
        lot = get_lot(ctx["lot"]["id"])
        assert lot["status"] == "ACTIVE", (
            f"70.00 >= 70.00 admits PASS; lot should be ACTIVE, "
            f"got {lot['status']}"
        )

    def test_result_69_90_rejects_pass_and_fail_condemns_never_circulated_lot(self):
        """PRD §3.3: "The declared `outcome` must agree with the measured band:
        `PASS` requires a `result_pct` of at least 70.00, and `FAIL` requires
        one strictly below 70.00; disagreement is rejected with
        `ERR_VIABILITY_OUTCOME_MISMATCH`."
        PRD §3.3: "A `FAIL` on a lot that has never circulated — no packets
        ever created — condemns it: the lot moves `QUARANTINE` → `REJECTED`,
        terminal."

        699/1000 == 69.90 rejects outcome=PASS; outcome=FAIL certifies and the
        never-circulated lot goes REJECTED.

        Design: Difficulty/boundary_precision_check/viability_threshold_exactly_70_passes
        """
        ctx = setup_quarantine_lot(
            seeds_received=100, provisional_viability_pct=69.90
        )
        test = record_test(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            seeds_tested=1000, sprouted_count=699,
        )
        assert test["result_pct"] == 69.9
        resp = api_client.certify_germination_test(
            test["id"], {"outcome": "PASS"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_VIABILITY_OUTCOME_MISMATCH)
        certified = certify_test(test["id"], "FAIL")
        assert certified["status"] == "CERTIFIED"
        lot = get_lot(ctx["lot"]["id"])
        assert lot["status"] == "REJECTED", (
            f"FAIL on a lot with zero packets created must condemn it to "
            f"REJECTED, got {lot['status']}"
        )


class TestGerminationResultRounding:
    def test_result_pct_rounds_half_up_to_two_decimals(self):
        """PRD §3.3: "The system computes `result_pct` as the sprouted share of
        the tested seeds expressed as a percentage — sprouted divided by
        tested, multiplied by one hundred — rounded half up to two decimal
        places".

        1 sprout of 3 tested -> 33.333... -> 33.33.

        Design: Corner/calculations/calc_germination_result_rounding_half_up
        """
        ctx = setup_quarantine_lot(
            seeds_received=10, provisional_viability_pct=50.00
        )
        test = record_test(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            seeds_tested=3, sprouted_count=1,
        )
        assert test["result_pct"] == pytest.approx(33.33, abs=1e-9), (
            f"Expected round_half_up(1/3*100, 2) = 33.33, "
            f"got {test['result_pct']}"
        )


class TestTerminalLockdown:
    def test_certified_test_rejects_second_certify(self):
        """PRD §3.3: "certifying one already in the terminal `CERTIFIED` or
        `VOIDED` state falls under terminal lockdown with
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/sm_terminal_lockdown_certified_test_recertify
        """
        ctx = setup_active_lot(seeds_received=100, provisional_viability_pct=80.00)
        resp = api_client.certify_germination_test(
            ctx["test"]["id"], {"outcome": "PASS"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestInitialStates:
    def test_initial_states_on_creation(self):
        """PRD §3.2: "A new lot begins in `DRAFT`".
        PRD §3.6: "the event begins in `DRAFT`."
        PRD §3.7: "A new session begins `SCHEDULED`".
        PRD §3.1: "Registration captures a unique `email` and `full_name` and
        leaves the record in `APPLIED`; an explicit approval moves it to
        `ACTIVE`."

        Design: Corner/state_machines/sm_initial_states_on_creation
        """
        site = create_site(site_type="GARDEN", region_zone="ZONE_7A")
        variety = create_variety(
            category="HERB", approved_zones=["ZONE_7A"]
        )
        volunteer = create_volunteer(approve=False)
        assert volunteer["status"] == "APPLIED"

        lot = create_seed_lot(
            variety["id"], site["id"],
            seeds_received=10, provisional_viability_pct=80.00,
        )
        assert lot["status"] == "DRAFT"

        event = create_swap_event(
            site["id"],
            start_at="2026-10-17T10:00:00Z", end_at="2026-10-17T12:00:00Z",
        )
        assert event["status"] == "DRAFT"

        session = create_packing_session(
            site["id"],
            start_at="2026-10-18T09:00:00Z", end_at="2026-10-18T11:00:00Z",
            capacity=3,
        )
        assert session["status"] == "SCHEDULED"

        approved = validate_success(
            api_client.approve_volunteer(volunteer["id"], ADMIN), 200
        )
        assert approved["status"] == "ACTIVE"


class TestLotCodeUniqueness:
    def test_duplicate_lot_code_rejected_but_different_harvest_year_allowed(self):
        """PRD §3.2: "The combination of variety, harvest year, and lot code
        must be unique; a collision is rejected with
        `ERR_DUPLICATE_LOT_CODE`."

        Design: Corner/entities/entity_lot_duplicate_code_rejected
        """
        site = create_site(site_type="GARDEN", region_zone="ZONE_6B")
        variety = create_variety(category="HERB", approved_zones=["ZONE_6B"])
        create_seed_lot(
            variety["id"], site["id"],
            lot_code="DUP", harvest_year=2026,
            seeds_received=50, provisional_viability_pct=75.00,
        )
        resp = api_client.create_seed_lot(
            {
                "variety_id": variety["id"],
                "home_site_id": site["id"],
                "lot_code": "DUP",
                "harvest_year": 2026,
                "seeds_received": 60,
                "provisional_viability_pct": 80.00,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOT_CODE)
        # A different harvest_year escapes the (variety, year, code) scope.
        resp = api_client.create_seed_lot(
            {
                "variety_id": variety["id"],
                "home_site_id": site["id"],
                "lot_code": "DUP",
                "harvest_year": 2027,
                "seeds_received": 60,
                "provisional_viability_pct": 80.00,
            },
            ADMIN,
        )
        ok = validate_success(resp, 201)
        assert ok["id"], "same lot_code under a different harvest_year succeeds"
