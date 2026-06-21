"""Calculation correctness: surgery tiered pricing, estimate per-line rounding,
boarding inclusive-day count, vaccine schedule, and the flat vaccine fee.

Each test pins to a PRD-stated formula and copies the pre-computed expected
literal from the design index verbatim.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    assert_surgery, assert_estimate, assert_boarding_stay, assert_vaccination,
    create_estimate_payload, create_wellness_plan_payload, create_vaccination_payload,
    create_household, create_patient, create_operatory, create_kennel,
    create_wellness_plan, create_estimate, present_estimate,
    create_appointment_in_exam, book_surgery, reserve_boarding,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


class TestSurgeryTieredTotal:
    """The surgery charge is base + weight-banded anesthesia + time surcharge, clamped."""

    def test_surgery_total_medium_band_with_time_surcharge(self, api):
        """PRD 3.8: "The procedure base is 20,000 cents." and "for a weight greater
        than 5 kg but at most 25 kg it is `weight_kg` multiplied by 600 cents per kg"
        and "subtracts a free allowance of 60 minutes, and ... charges 150 cents for
        each excess minute."

        12.5kg MEDIUM -> 7500 anesthesia; 90 min window -> 30 excess * 150 = 4500;
        20000 + 7500 + 4500 = 32000, within [25000,500000].

        Design: Difficulty/combinatorial_formula/surgery_total_tiered_three_input_nonlinear
        """
        operatory = create_operatory(cleanup_buffer_minutes=30)
        hh = create_household("Pham")
        _, pat = create_patient(household_id=hh["id"], name="Zora",
                                species="DOG", weight_kg=12.5)
        est, _ = _approved_zero_deposit_estimate(api, pat["id"], hh, unit_price=32000)
        appt = create_appointment_in_exam(pat["id"],
                                          scheduled_start="2026-07-02T09:00:00Z",
                                          scheduled_end="2026-07-02T12:00:00Z")
        res = api.create_surgery({
            "appointment_id": appt["id"], "operatory_id": operatory["id"],
            "estimate_id": est["id"], "procedure_name": "Spay",
            "window_start": "2026-07-02T09:00:00Z",
            "window_end": "2026-07-02T10:30:00Z",
        }, VETERINARIAN)
        surgery = validate_success(res, 201)
        assert_surgery(surgery)
        assert surgery["surgery_total_cents"] == 32000, (
            f"Expected 32000, got {surgery['surgery_total_cents']}")

    def test_surgery_total_clamped_to_floor_when_raw_below_min(self, api):
        """PRD 3.8: "That raw total is finally clamped into a band: it is raised to a
        floor of 25,000 cents if it falls below that".

        Small dog 2kg SMALL band -> 2*800=1600 anesthesia; 30-min window (no excess
        over 60) -> 0 surcharge; raw = 20000 + 1600 = 21600 < 25000 -> clamped to 25000.

        Design: Difficulty/combinatorial_formula/surgery_total_tiered_three_input_nonlinear
        """
        operatory = create_operatory(cleanup_buffer_minutes=30)
        hh = create_household("Clamp")
        _, pat = create_patient(household_id=hh["id"], name="Tiny",
                                species="CAT", weight_kg=2)
        est, _ = _approved_zero_deposit_estimate(api, pat["id"], hh, unit_price=25000)
        appt = create_appointment_in_exam(pat["id"],
                                          scheduled_start="2026-07-02T08:00:00Z",
                                          scheduled_end="2026-07-02T14:00:00Z")
        res = api.create_surgery({
            "appointment_id": appt["id"], "operatory_id": operatory["id"],
            "estimate_id": est["id"], "procedure_name": "Minor",
            "window_start": "2026-07-02T09:00:00Z",
            "window_end": "2026-07-02T09:30:00Z",
        }, VETERINARIAN)
        surgery = validate_success(res, 201)
        assert surgery["surgery_total_cents"] == 25000, (
            f"Expected floor 25000, got {surgery['surgery_total_cents']}")


class TestEstimateRoundingOrder:
    """Plan discounts are rounded per line item before summing, not after (PRD 3.6)."""

    def test_estimate_per_line_rounding_then_sum_basic_plan(self, api):
        """PRD 3.6: "the order of operations is pinned: discounts are rounded per line
        item before summing, not after." and "the line's discount is the gross
        multiplied by the plan's `service_discount_pct`, rounded half up to whole cents".

        3 eligible lines each gross 2505 under BASIC (0.10): discount=round_half_up(250.5)
        =251 each -> net 2254 each -> 6762 total (sum-then-round would give 6763).

        Design: Difficulty/combinatorial_formula/estimate_rounding_order_per_line_then_sum
        """
        hh = create_household("Lind")
        _, pat = create_patient(household_id=hh["id"], name="Bo",
                                species="DOG", weight_kg=8)
        create_wellness_plan(pat["id"], tier="BASIC")
        line_items = [
            {"service_code": "A", "qty": 1, "unit_price_cents": 2505, "eligible_for_plan_discount": True},
            {"service_code": "B", "qty": 1, "unit_price_cents": 2505, "eligible_for_plan_discount": True},
            {"service_code": "C", "qty": 1, "unit_price_cents": 2505, "eligible_for_plan_discount": True},
        ]
        est = create_estimate(pat["id"], line_items=line_items)
        presented = present_estimate(est["id"])
        assert presented["estimated_total_cents"] == 6762, (
            f"Expected 6762 (round-per-line), got {presented['estimated_total_cents']}")

    def test_estimate_no_plan_no_discount(self, api):
        """PRD 3.6: "if the line is not eligible or the patient has no active plan, the
        line's net is simply its gross."

        With no wellness plan, three eligible lines of 2505 sum to 7515 (no discount).

        Design: Difficulty/combinatorial_formula/estimate_rounding_order_per_line_then_sum
        """
        hh = create_household("NoPlan")
        _, pat = create_patient(household_id=hh["id"], name="NoPlanPet",
                                species="DOG", weight_kg=8)
        line_items = [
            {"service_code": "A", "qty": 1, "unit_price_cents": 2505, "eligible_for_plan_discount": True},
            {"service_code": "B", "qty": 1, "unit_price_cents": 2505, "eligible_for_plan_discount": True},
            {"service_code": "C", "qty": 1, "unit_price_cents": 2505, "eligible_for_plan_discount": True},
        ]
        est = create_estimate(pat["id"], line_items=line_items)
        presented = present_estimate(est["id"])
        assert presented["estimated_total_cents"] == 7515, (
            f"Expected 7515 (no plan, no discount), got {presented['estimated_total_cents']}")


def test_boarding_total_inclusive_day_count(api):
    """PRD 3.9: "the number of days from `check_in_date` to `check_out_date` plus one,
    so that a same-day stay (check-in equal to check-out) counts as one night."

    A stay 2026-07-01..2026-07-04 inclusive is 4 nights; at 5000/night -> 20000.

    Design: Corner/calculations/boarding_total_inclusive_day_count
    """
    ken = create_kennel(capacity=3, name="KB")
    hh = create_household("Nu")
    _, pat = create_patient(household_id=hh["id"], name="Boarder",
                            species="DOG", weight_kg=12)
    res = api.create_boarding_stay({
        "patient_id": pat["id"], "kennel_id": ken["id"],
        "check_in_date": "2026-07-01T00:00:00Z",
        "check_out_date": "2026-07-04T00:00:00Z",
        "nightly_rate_cents": 5000,
    }, RECEPTIONIST)
    stay = validate_success(res, 201)
    assert_boarding_stay(stay)
    assert stay["board_total_cents"] == 20000, (
        f"Expected 20000 (4 nights), got {stay['board_total_cents']}")


def test_vaccine_reminder_lead_computed(api):
    """PRD 3.4: "The `next_due_at` is the `administered_at` plus the code's interval in
    days." and "The `reminder_at` is the `next_due_at` minus a fixed reminder lead of
    14 days".

    DHPP (21-day interval) administered 2026-03-01 -> next_due 2026-03-22,
    reminder 2026-03-08.

    Design: Corner/calculations/vaccine_reminder_lead_computed
    """
    hh = create_household("Xi")
    _, pat = create_patient(household_id=hh["id"], name="Pup",
                            species="DOG", weight_kg=6)
    res = api.create_vaccination({
        "patient_id": pat["id"], "vaccine_code": "DHPP",
        "administered_at": "2026-03-01T10:00:00Z",
    }, VETERINARIAN)
    vax = validate_success(res, 201)
    assert_vaccination(vax)
    assert vax["next_due_at"][:10] == "2026-03-22", (
        f"Expected next_due 2026-03-22, got {vax['next_due_at']}")
    assert vax["reminder_at"][:10] == "2026-03-08", (
        f"Expected reminder 2026-03-08, got {vax['reminder_at']}")


def test_nonbundled_vaccine_fee_charged(api):
    """PRD 3.4: "Otherwise the dose charges the flat standard vaccine fee of 4,500
    cents, which is the same for every `vaccine_code`."

    A non-bundled FVRCP dose (no plan) charges fee_cents == 4500.

    Design: Corner/calculations/nonbundled_vaccine_fee_charged
    """
    hh = create_household("Omn")
    _, pat = create_patient(household_id=hh["id"], name="Cat2",
                            species="CAT", weight_kg=5)
    res = api.create_vaccination({
        "patient_id": pat["id"], "vaccine_code": "FVRCP",
        "administered_at": "2026-04-01T10:00:00Z", "bundled": False,
    }, VETERINARIAN)
    vax = validate_success(res, 201)
    assert vax["fee_cents"] == 4500, f"Expected 4500, got {vax['fee_cents']}"


# ─── local helper ─────────────────────────────────────────────────────────────

def _approved_zero_deposit_estimate(api, patient_id, household, unit_price=30000):
    """Create an estimate with zero deposit_required, present and approve it."""
    line_items = [{"service_code": "SURG", "qty": 1,
                   "unit_price_cents": unit_price, "eligible_for_plan_discount": False}]
    est = create_estimate(patient_id, line_items=line_items, deposit_required_cents=0)
    present_estimate(est["id"])
    from test_helpers import approve_estimate
    approve_estimate(est["id"])
    final = validate_success(api.get_estimate(est["id"], VETERINARIAN), 200)
    return final, household["version"]
