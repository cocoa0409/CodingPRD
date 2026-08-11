"""Combinatorial formulas: tiered registration fee with nested min/max/floor,
per-component inspection rounding, and the pinned late-fee evaluation order
(PRD §3.4, §3.5, §3.6).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_permit_holder_headers,
    create_community, create_eligible_holder, create_vehicle,
    create_full_equipment_lsv, create_draft_registration,
    finalize_inspection_for_registration, create_insurance, deposit,
    set_clock,
    setup_activation_ready_registration,
    COMMUNITY_ADMIN,
    create_inspection_payload, finalize_inspection_payload,
    INSPECTOR,
)


def _setup_cf1():
    """Community with fleet program on; ELIGIBLE holder; cart A (minimum legal
    GOLF_CART equipment per PRD §3.3 — headlights + brake lights, no mirrors —
    4 seats) and cart B (8 equipment, 6 seats)."""
    community = create_community(name="C-CF1", fleet_program_enabled=True)
    holder = create_eligible_holder(community["id"], full_name="H CF1",
                                    birth_date="2010-05-01")
    v_a = create_vehicle(
        holder["id"], vehicle_type="GOLF_CART", seat_count=4,
        has_headlights=True, has_brake_lights=True, has_turn_signals=False,
        has_horn=False, has_windshield=False, has_seatbelts=False,
        has_reflectors=False, mirror_count=0)
    v_b = create_full_equipment_lsv(holder["id"], vehicle_type="GOLF_CART")
    return community, holder, v_a, v_b


class TestTieredEquipmentMultiplierFloor:
    def test_floor_binds_when_discounted_subtotal_below_base(self):
        """PRD §3.5: "The fee is the larger of that subtotal and the base: the fee
        never falls below the base amount."
        PRD §3.5: "When the fleet discount applies, the subtotal is then multiplied
        by 0.90 — a ten percent discount — and rounded half-up to whole cents again."

        Design: Difficulty/combinatorial_formula/registration_fee_tiered_equipment_multiplier_floor
        """
        _, holder, v_a, _ = _setup_cf1()
        hh = make_permit_holder_headers(holder["id"])
        reg_a = validate_success(api_client.create_registration(
            {"vehicle_id": v_a["id"], "holder_id": holder["id"],
             "registration_year": 2026}, hh), 201)
        # Minimum legal cart: equipment_count 2 -> mult 1.04; 7500 * 1.04 = 7800;
        # * 0.9 = 7020; floor max(7020, 7500) = 7500.
        assert reg_a["provisional_fee_cents"] == 7500, (
            f"floor case {reg_a['provisional_fee_cents']} != 7500")
        assert reg_a["status"] == "DRAFT"

    def test_cap_surcharge_and_discount_compose(self):
        """PRD §3.5: "An equipment multiplier starts at 1 and grows by a per-item
        rate for each counted equipment item in the vehicle's `equipment_count`,
        capped so the multiplier never exceeds 1.20; the per-item rate is 0.02 for
        the PROVISIONAL variant and 0.025 for the FINALIZED variant. A seat
        surcharge adds 500 cents for every seat beyond the first four — the first
        four seats are free."

        Design: Difficulty/combinatorial_formula/registration_fee_tiered_equipment_multiplier_floor
        """
        _, holder, _, v_b = _setup_cf1()
        hh = make_permit_holder_headers(holder["id"])
        reg_b = validate_success(api_client.create_registration(
            {"vehicle_id": v_b["id"], "holder_id": holder["id"],
             "registration_year": 2026}, hh), 201)
        # mult min(1+0.02*8, 1.20) = 1.16; 7500*1.16 = 8700; seats +1000 = 9700;
        # * 0.9 = 8730; >= 7500.
        assert reg_b["provisional_fee_cents"] == 8730, (
            f"capped/surcharged/discounted fee {reg_b['provisional_fee_cents']} != 8730")
        assert reg_b["status"] == "DRAFT"


def _setup_cf2():
    """Community, ELIGIBLE holder, full-equipment LSV, DRAFT registration and one
    SCHEDULED inspection."""
    community = create_community(name="C-CF2")
    holder = create_eligible_holder(community["id"], full_name="H CF2",
                                    birth_date="2010-05-01")
    vehicle = create_full_equipment_lsv(holder["id"], seat_count=4)
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    inspection = get_success_data(api_client.create_inspection(
        create_inspection_payload(registration["id"]), INSPECTOR))
    return community, holder, vehicle, registration, inspection


class TestInspectionScoreRoundPerComponentThenSum:
    def test_all_84_components_yield_83_99_not_84_00(self):
        """PRD §3.4: "For each component, the component's score is multiplied by
        its weight percent and divided by 100, and that contribution is rounded
        half-up to two decimal places before any summation. The `total_score` is
        the exact sum of the eight rounded contributions."

        Design: Difficulty/combinatorial_formula/inspection_score_round_per_component_then_sum
        """
        _, _, _, _, inspection = _setup_cf2()
        finalized = validate_success(api_client.finalize_inspection(
            inspection["id"], finalize_inspection_payload(score=84), INSPECTOR), 200)
        # Per-component round then sum: 14.00+14.00+11.20+5.60+8.40+8.40+13.99+8.40
        # = 83.99 (sum-then-round would give 84.00 — the per-component order is
        # normative).
        assert finalized["total_score"] == pytest.approx(83.99, abs=0.001), (
            f"total_score {finalized['total_score']} != 83.99")

    def test_83_99_is_above_pass_threshold(self):
        """PRD §3.4: "The `passed` flag is true when `total_score` is at least
        70.00 — a score of exactly 70.00 passes."
        PRD §3.4: "A finalized inspection whose total meets the threshold becomes
        `PASSED` — terminal — and triggers a recomputation of the registration's
        `finalized_fee_cents` using the FINALIZED variant of §3.5, with
        `total_due_cents` reset to the smaller of the finalized fee plus the late
        fee and twice the finalized fee."

        Design: Difficulty/combinatorial_formula/inspection_score_round_per_component_then_sum
        """
        _, _, _, _, inspection = _setup_cf2()
        finalized = validate_success(api_client.finalize_inspection(
            inspection["id"], finalize_inspection_payload(score=84), INSPECTOR), 200)
        assert finalized["passed"] is True
        assert finalized["status"] == "PASSED"


def _setup_cf3():
    """ACTIVE LSV registration (finalized 19000 at activation), expiry
    2027-05-01T00:00:00Z, wallet 81000; clock advanced to 2027-05-31 (EXPIRED,
    exactly 30 days overdue)."""
    ctx = setup_activation_ready_registration(
        community_name="C-CF3", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-CF3"})
    holder = ctx["holder"]
    hh = make_permit_holder_headers(holder["id"])
    registration = validate_success(api_client.activate_registration(
        ctx["registration"]["id"], hh), 200)
    set_clock("2027-05-31T00:00:00Z")
    return ctx, registration, hh


class TestLateFeeEvaluationOrderPinned:
    def test_renew_from_expired_computes_finalized_fee_and_late_fee(self):
        """PRD §3.6: "The late fee follows a pinned evaluation order, so the
        circular-looking dependency between fee, tier, late amount, cap, and total
        is well-defined. First, the finalized fee is taken as the base. Second, the
        base selects a tier: tier A when the base is below 10000 cents, tier B
        otherwise. Third, the days overdue are the whole days between `expiry_date`
        and now, partial days discarded. Fourth, the days overdue select a band:
        30 days or fewer lands in the first band (day 30 exactly is band one), 31
        through 60 days lands in the second, and 61 days through `late_grace_days`
        lands in the third."

        Design: Difficulty/combinatorial_formula/late_fee_evaluation_order_pinned
        """
        _, registration, hh = _setup_cf3()
        renewed = validate_success(
            api_client.renew_registration(registration["id"], hh), 200)
        assert renewed["status"] == "RENEWAL_PENDING"
        # FINALIZED variant recomputed on renew-from-EXPIRED.
        assert renewed["finalized_fee_cents"] == 19000
        # Tier B (19000 >= 10000); 30 days overdue -> band 1 (day 30 inclusive).
        assert renewed["late_fee_cents"] == 2500, (
            f"late_fee {renewed['late_fee_cents']} != 2500")

    def test_total_due_capped_at_twice_finalized_fee(self):
        """PRD §3.6: "Fifth, the total due is the smaller of the base plus the raw
        late fee and twice the base — the combined charge never exceeds double the
        finalized fee."
        PRD §3.6: "A late renewal opened while the registration is `EXPIRED`
        requires the current instant to be after `expiry_date` and no later than
        `late_grace_days` days past it — the lower bound exclusive, the upper bound
        inclusive."

        Design: Difficulty/combinatorial_formula/late_fee_evaluation_order_pinned
        """
        _, registration, hh = _setup_cf3()
        renewed = validate_success(
            api_client.renew_registration(registration["id"], hh), 200)
        # total_due = min(19000 + 2500, 2 * 19000) = 21500.
        assert renewed["total_due_cents"] == 21500, (
            f"total_due {renewed['total_due_cents']} != 21500")
        # No violations on this holder -> provisional score is 100.
        assert renewed["renewal_score_provisional"] == pytest.approx(100, abs=0.01)
