"""Participation fee variants, tier boundaries, credit caps, and contract-driven
cross-entity transitions (PRD §3.3)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_and_open_booking,
    create_venue,
    book_stop,
    create_and_send_contract,
    create_and_sign_contract,
    setup_contracted_stop,
    setup_closed_stop,
    current_tour_version,
)

TM = TEST_USERS["tour_manager_headers"]
VR = TEST_USERS["venue_registrar_headers"]


class TestTierBoundary:
    def test_attendance_at_10000_no_uplift(self, api):
        """PRD §3.3: "Attendance drives an uplift on the base fee: attendance of
        at most ten thousand draws no uplift; above ten thousand and at most
        fifty thousand, the uplift is ten percent of `base_fee_cents`."
        PRD §3.3: "The PROVISIONAL variant, computed at send time, feeds the
        stop's `projected_attendance` through this formula and lands in
        `provisional_fee_cents`."

        Design: Difficulty/boundary_precision_check/attendance_tier_boundary_10000_vs_10001
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="V1")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=10000)
        contract = create_and_send_contract(
            tour["id"], stop["id"], base_fee_cents=2000000, sponsorship_credit_cents=0
        )
        assert contract["provisional_fee_cents"] == 2000000

    def test_attendance_at_10001_tier2_uplift(self, api):
        """PRD §3.3: "Attendance drives an uplift on the base fee: attendance of
        at most ten thousand draws no uplift; above ten thousand and at most
        fifty thousand, the uplift is ten percent of `base_fee_cents`."
        PRD §3.3: "The PROVISIONAL variant, computed at send time, feeds the
        stop's `projected_attendance` through this formula and lands in
        `provisional_fee_cents`."

        Design: Difficulty/boundary_precision_check/attendance_tier_boundary_10000_vs_10001
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="V2")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=10001)
        contract = create_and_send_contract(
            tour["id"], stop["id"], base_fee_cents=2000000, sponsorship_credit_cents=0
        )
        assert contract["provisional_fee_cents"] == 2200000


class TestCreditCap:
    def test_venue_cap_binds_over_contract_credit(self, api):
        """PRD §3.3: "The fee before credit is the base plus the uplift; the
        sponsorship credit actually applied is the smallest of three figures —
        the contract's `sponsorship_credit_cents`, the venue's
        `local_sponsorship_cap_cents`, and that fee before credit — and the fee
        is what remains after the credit is subtracted."
        PRD §3.3: "above ten thousand and at most fifty thousand, the uplift is
        ten percent of `base_fee_cents`."

        Design: Difficulty/combinatorial_formula/participation_fee_tiered_uplift_with_credit_cap
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Fiber Hall", local_sponsorship_cap_cents=150000)
        stop = book_stop(tour["id"], venue["id"], projected_attendance=20000)
        contract = create_and_send_contract(
            tour["id"], stop["id"], base_fee_cents=1000000, sponsorship_credit_cents=200000
        )
        # uplift = 10% of 1000000 = 100000; fee_before = 1100000;
        # credit = min(200000, 150000, 1100000) = 150000 -> 950000.
        assert contract["provisional_fee_cents"] == 950000

    def test_contract_credit_binds_when_below_venue_cap(self, api):
        """PRD §3.3: "the sponsorship credit actually applied is the smallest of
        three figures — the contract's `sponsorship_credit_cents`, the venue's
        `local_sponsorship_cap_cents`, and that fee before credit — and the fee
        is what remains after the credit is subtracted."

        Design: Difficulty/combinatorial_formula/participation_fee_tiered_uplift_with_credit_cap
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Fiber Hall", local_sponsorship_cap_cents=500000)
        stop = book_stop(tour["id"], venue["id"], projected_attendance=5000)
        contract = create_and_send_contract(
            tour["id"], stop["id"], base_fee_cents=1000000, sponsorship_credit_cents=200000
        )
        # tier1 (no uplift); fee_before = 1000000; credit = min(200000, 500000,
        # 1000000) = 200000 -> 800000.
        assert contract["provisional_fee_cents"] == 800000


class TestProvisionalVsFinalDiverge:
    def _run_full_lifecycle(self, api):
        """DINOSAURS scenario: one stop through close with divergent attendance."""
        tour, crates, venue, stop, contract, shipment = setup_closed_stop(
            actual_attendance=60000,
            venue_overrides={
                "name": "City Museum",
                "city": "Denver",
                "local_sponsorship_cap_cents": 500000,
            },
            stop_overrides={
                "install_start": "2026-09-01T00:00:00Z",
                "open_date": "2026-09-05T00:00:00Z",
                "close_date": "2026-11-01T00:00:00Z",
                "teardown_end": "2026-11-05T00:00:00Z",
                "projected_attendance": 8000,
            },
            contract_overrides={"base_fee_cents": 2000000, "sponsorship_credit_cents": 300000},
            title="Dinosaurs",
            exhibit_code="DINO-2026",
            declared_value_cents=5000000,
            refurbishment_gap_days=7,
        )
        return tour, stop, contract

    def test_provisional_fee_uses_projected_attendance(self, api):
        """PRD §3.3: "The PROVISIONAL variant, computed at send time, feeds the
        stop's `projected_attendance` through this formula and lands in
        `provisional_fee_cents`."
        PRD §3.3: "attendance of at most ten thousand draws no uplift".

        Design: Difficulty/dual_variant_calc/participation_fee_provisional_vs_final_diverge
        """
        tour, _ = create_and_open_booking(declared_value_cents=5000000)
        venue = create_venue(name="City Museum", local_sponsorship_cap_cents=500000)
        stop = book_stop(tour["id"], venue["id"], projected_attendance=8000)
        contract = create_and_send_contract(
            tour["id"], stop["id"], base_fee_cents=2000000, sponsorship_credit_cents=300000
        )
        # tier1, fee_before 2000000, credit min(300000, 500000, 2000000)=300000.
        assert contract["provisional_fee_cents"] == 1700000

    def test_final_fee_uses_actual_attendance_and_finalizes(self, api):
        """PRD §3.3: "The FINAL variant, computed when the stop closes (§3.8),
        feeds `actual_attendance` through the same formula and lands in
        `final_fee_cents`."
        PRD §3.3: "above fifty thousand, it is twenty-five percent."
        PRD §3.8: "On close, the system finalizes the contract: the FINAL fee
        variant computed from `actual_attendance` supersedes the provisional
        figure and lands in `final_fee_cents`, and the tour's
        `total_billed_cents` is recomputed."

        Design: Difficulty/dual_variant_calc/participation_fee_provisional_vs_final_diverge
        """
        tour, stop, contract = self._run_full_lifecycle(api)
        contracts = validate_success(api.get_contract(tour["id"], stop["id"], TM), 200)
        target = [c for c in contracts if c["id"] == contract["id"]][0]
        assert target["status"] == "FINALIZED"
        assert target["provisional_fee_cents"] == 1700000
        # FINAL: att 60000 -> tier3 uplift 500000; fee_before 2500000;
        # credit min(300000, 500000, 2500000) = 300000 -> 2200000.
        assert target["final_fee_cents"] == 2200000
        tour_after = validate_success(api.get_tour(tour["id"], TM), 200)
        assert tour_after["total_billed_cents"] == 2200000

    def test_ledger_conservation_billed_and_waived(self, api):
        """PRD §3.3: "A successful signature flips the stop `TENTATIVE` →
        `CONTRACTED` and credits the tour's `total_waived_cents` with the waiver
        actually applied — the smaller of the contract's
        `sponsorship_credit_cents` and its `provisional_fee_cents`."
        PRD §3.9: "Throughout the lifecycle, the tour's ledger reads back through
        its financial summary: `total_billed_cents` of final fees billed across
        all stops, `total_collected_cents` of payments applied to participation
        fees, `total_waived_cents` of sponsorship waivers granted at signature,
        and the derived `outstanding_cents` still to be collected."

        Design: Difficulty/compensating_invariant/tour_fee_ledger_conservation_billed_equals_waived_plus_expected
        """
        tour, stop, contract = self._run_full_lifecycle(api)
        summary = validate_success(api.get_financial_summary(tour["id"], TM), 200)
        assert summary["total_billed_cents"] == 2200000
        assert summary["total_waived_cents"] == 300000
        # final_fee 2200000 == base 2000000 + uplift 500000 - credit 300000.
        assert 2200000 == 2000000 + 500000 - 300000

    def test_waived_credit_applied_at_signature(self, api):
        """PRD §3.3: "A successful signature flips the stop `TENTATIVE` →
        `CONTRACTED` and credits the tour's `total_waived_cents` with the waiver
        actually applied — the smaller of the contract's
        `sponsorship_credit_cents` and its `provisional_fee_cents`."

        Design: Difficulty/compensating_invariant/tour_fee_ledger_conservation_billed_equals_waived_plus_expected
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="City Museum", local_sponsorship_cap_cents=500000)
        stop = book_stop(tour["id"], venue["id"], projected_attendance=8000)
        create_and_sign_contract(
            tour["id"], stop["id"], base_fee_cents=2000000, sponsorship_credit_cents=300000
        )
        tour_after = validate_success(api.get_tour(tour["id"], TM), 200)
        assert tour_after["total_waived_cents"] == 300000


class TestContractSignCrossEntity:
    def test_sign_flips_stop_to_contracted(self, api):
        """PRD §3.3: "A successful signature flips the stop `TENTATIVE` →
        `CONTRACTED` and credits the tour's `total_waived_cents` with the waiver
        actually applied — the smaller of the contract's
        `sponsorship_credit_cents` and its `provisional_fee_cents`."

        Design: Difficulty/cross_entity_state_dependency/contract_sign_transitions_stop_tentative_to_contracted
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Atlas Hall")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=2000)
        assert stop["status"] == "TENTATIVE"
        create_and_send_contract(
            tour["id"], stop["id"], base_fee_cents=100000, sponsorship_credit_cents=0
        )
        res = api.transition_contract(tour["id"], stop["id"], {"action": "SIGN"}, VR)
        contract = validate_success(res, 200)
        assert contract["status"] == "SIGNED"
        stop_after = validate_success(api.get_stop(tour["id"], stop["id"], TM), 200)
        assert stop_after["status"] == "CONTRACTED"

    def test_sign_requires_sent_state(self, api):
        """PRD §3.3: "The contract lifecycle runs `DRAFT` → `SENT` → `SIGNED` →
        `FINALIZED`, with one amendment loop."
        PRD §2.8: "then transition state validity — a transition attempted from a
        state that does not permit it fails with `ERR_INVALID_STATE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/contract_sign_transitions_stop_tentative_to_contracted
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Atlas Hall")
        stop = book_stop(tour["id"], venue["id"])
        get_success_data(
            api.create_contract(
                tour["id"],
                stop["id"],
                {"base_fee_cents": 100000, "sponsorship_credit_cents": 0},
                TM,
            )
        )
        # SIGN from DRAFT (never SENT) is not a permitted transition.
        res = api.transition_contract(tour["id"], stop["id"], {"action": "SIGN"}, VR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        stop_after = validate_success(api.get_stop(tour["id"], stop["id"], TM), 200)
        assert stop_after["status"] == "TENTATIVE"


class TestContractValidations:
    def test_sponsorship_over_cap_rejected_at_sign(self, api):
        """PRD §3.3: "Signature (`SIGN`) belongs to the `VenueRegistrar` alone: at
        that moment the committed `sponsorship_credit_cents` is checked against
        the venue's `local_sponsorship_cap_cents`, and an over-cap commitment is
        refused with `ERR_SPONSORSHIP_OVER_CAP`."

        Design: Corner/validations/sponsorship_over_cap_rejected_at_sign
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Rail Hall", local_sponsorship_cap_cents=100000)
        stop = book_stop(tour["id"], venue["id"], projected_attendance=100)
        create_and_send_contract(
            tour["id"], stop["id"], base_fee_cents=500000, sponsorship_credit_cents=200000
        )
        res = api.transition_contract(tour["id"], stop["id"], {"action": "SIGN"}, VR)
        validate_error(res, ApiErrorId.ERR_SPONSORSHIP_OVER_CAP)

    def test_duplicate_contract_rejected(self, api):
        """PRD §3.3: "A stop may carry at most one non-terminal contract:
        attempting to create a second while an earlier one is still open fails
        with `ERR_DUPLICATE_CONTRACT`."

        Design: Corner/validations/duplicate_contract_rejected
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Harbor Hall")
        stop = book_stop(tour["id"], venue["id"])
        get_success_data(
            api.create_contract(
                tour["id"],
                stop["id"],
                {"base_fee_cents": 100000, "sponsorship_credit_cents": 0},
                TM,
            )
        )
        res = api.create_contract(
            tour["id"],
            stop["id"],
            {"base_fee_cents": 200000, "sponsorship_credit_cents": 0},
            TM,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CONTRACT)
