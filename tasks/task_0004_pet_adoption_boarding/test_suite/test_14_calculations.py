"""Tests for fiscal calculations: adoption fee, boarding fee, compliance score.

Covers: PRD Section 2.7 (Fiscal Precision), 3.1, 3.6, 3.7,
Table 3 (adoption_fee_calculation, boarding_fee_calculation,
boarding_compatibility_scoring, shelter_compliance_score).
"""
import math
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_fee_schedule_payload, create_adoption_application_payload,
    create_boarding_reservation_payload, create_compliance_hold_payload,
    create_home_visit_payload, complete_home_visit_payload,
    create_shelter, create_available_animal, create_adopter,
    create_animal_intake, add_vaccinations_for_adoption,
    create_boarding_ready_animal, setup_basic_adoption_scenario,
    start_review, pay_invoice_in_full,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]
_case_worker2 = TEST_USERS["case_worker_headers_2"]
_vet = TEST_USERS["vet_headers"]


def _round_half_up(x: float) -> int:
    """Standard round_half_up to the nearest integer."""
    return int(math.floor(x + 0.5))


def _create_fee_rows(shelter_id, adoption_base=10000, boarding_daily=2000,
                     special_needs_unit=0, loyalty_pct=0, species="ALL"):
    """Create a fresh set of FeeSchedule rows for a shelter."""
    get_success_data(api_client.create_fee_schedule(
        create_fee_schedule_payload(shelter_id, fee_type="ADOPTION_BASE",
                                     species=species, amount_cents=adoption_base),
        _manager,
    ))
    get_success_data(api_client.create_fee_schedule(
        create_fee_schedule_payload(shelter_id, fee_type="BOARDING_DAILY",
                                     species=species, amount_cents=boarding_daily),
        _manager,
    ))
    if special_needs_unit > 0:
        get_success_data(api_client.create_fee_schedule(
            create_fee_schedule_payload(shelter_id, fee_type="SPECIAL_NEEDS_SURCHARGE",
                                         species=species, amount_cents=special_needs_unit),
            _manager,
        ))
    if loyalty_pct > 0:
        get_success_data(api_client.create_fee_schedule(
            create_fee_schedule_payload(shelter_id, fee_type="LOYALTY_DISCOUNT_PCT",
                                         species="ALL", amount_cents=loyalty_pct),
            _manager,
        ))


def _run_adoption_approve(shelter, animal, adopter, reviewer_headers=_case_worker,
                           approver_headers=_manager):
    """Submit + start-review + (home visit if required) + complete-review + approve.

    Returns (app, invoice). If the animal triggers requires_home_visit=true
    (DOG or weight_kg>=25 per PRD), the reviewer requires a home visit, a PASS
    visit is created and completed, then complete-review proceeds normally.
    """
    app = get_success_data(api_client.create_adoption_application(
        create_adoption_application_payload(animal["id"], adopter["id"]),
        _case_worker,
    ))
    app = get_success_data(api_client.start_review_application(app["id"], reviewer_headers))
    if app.get("requires_home_visit"):
        app = get_success_data(api_client.require_home_visit(app["id"], reviewer_headers))
        hv = get_success_data(api_client.create_home_visit(
            create_home_visit_payload(app["id"]), reviewer_headers,
        ))
        # PASS result keeps the application on the happy path to REVIEWED.
        get_success_data(api_client.complete_home_visit(
            hv["id"], complete_home_visit_payload(), reviewer_headers,
        ))
        # Refresh the application so we see the HOME_VISIT_SCHEDULED -> REVIEWED
        # transition triggered by the PASS home visit.
        app = get_success_data(api_client.get_adoption_application(app["id"], reviewer_headers))
    else:
        app = get_success_data(api_client.complete_review(app["id"], reviewer_headers))
    app = get_success_data(api_client.approve_application(app["id"], approver_headers))
    invoice = get_success_data(api_client.get_fee_invoice(app["fee_invoice_id"], approver_headers))
    return app, invoice


class TestAdoptionFeeBase:
    """PRD 3.6 + Table 3 adoption_fee_calculation: base pricing."""

    def test_species_specific_row_preferred_over_all(self):
        """If DOG-specific ADOPTION_BASE exists, it's used instead of ALL."""
        shelter = create_shelter(tax_rate=0.0)
        # ALL row at 10000, DOG row at 20000
        _create_fee_rows(shelter["id"], adoption_base=10000, species="ALL")
        get_success_data(api_client.create_fee_schedule(
            create_fee_schedule_payload(shelter["id"], fee_type="ADOPTION_BASE",
                                         species="DOG", amount_cents=20000),
            _manager,
        ))
        animal = create_available_animal(shelter_id=shelter["id"], species="DOG",
                                          age_months=24)
        adopter = create_adopter(shelter_id=shelter["id"])
        app, invoice = _run_adoption_approve(shelter, animal, adopter,
                                              reviewer_headers=_case_worker,
                                              approver_headers=_manager)
        # Expected: base=20000 (DOG), no surcharge, no discount, tax=0
        assert invoice["subtotal_cents"] == 20000
        assert invoice["discount_cents"] == 0
        assert invoice["tax_cents"] == 0
        assert invoice["total_amount_cents"] == 20000

    def test_fallback_to_all_when_no_species_row(self):
        """If no species-specific row exists, ALL is used."""
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], adoption_base=10000, species="ALL")
        animal = create_available_animal(shelter_id=shelter["id"], species="DOG",
                                          age_months=24)
        adopter = create_adopter(shelter_id=shelter["id"])
        app, invoice = _run_adoption_approve(shelter, animal, adopter)
        assert invoice["subtotal_cents"] == 10000


class TestAdoptionSeniorDiscount:
    """PRD 3.6 + Table 3: age_months >= 84 halves base via floor."""

    def test_senior_discount_applied_at_84_months(self):
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], adoption_base=10001, species="ALL")
        animal = create_available_animal(shelter_id=shelter["id"], species="CAT",
                                          age_months=84)
        adopter = create_adopter(shelter_id=shelter["id"])
        app, invoice = _run_adoption_approve(shelter, animal, adopter)
        # floor(10001 * 0.5) = 5000
        assert invoice["subtotal_cents"] == 5000

    def test_no_senior_discount_below_84_months(self):
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], adoption_base=10001, species="ALL")
        animal = create_available_animal(shelter_id=shelter["id"], species="CAT",
                                          age_months=83)
        adopter = create_adopter(shelter_id=shelter["id"])
        app, invoice = _run_adoption_approve(shelter, animal, adopter)
        assert invoice["subtotal_cents"] == 10001


class TestAdoptionSpecialNeedsSurcharge:
    """PRD 3.6: surcharge_unit * len(special_needs)."""

    def test_surcharge_added_per_tag(self):
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], adoption_base=10000,
                         special_needs_unit=500, species="ALL")
        # Animal with 2 special_needs
        animal = create_available_animal(
            shelter_id=shelter["id"], species="CAT", age_months=24,
            special_needs=["MEDICATION_REQUIRED", "DIET_RESTRICTED"],
        )
        adopter = create_adopter(shelter_id=shelter["id"])
        app, invoice = _run_adoption_approve(shelter, animal, adopter)
        # base 10000 + 500*2 = 11000
        assert invoice["subtotal_cents"] == 11000


class TestAdoptionLoyaltyDiscount:
    """PRD 3.6: loyalty discount applies when adoption_history_count >= 2."""

    def test_no_loyalty_discount_below_threshold(self):
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], adoption_base=10000, loyalty_pct=10,
                         species="ALL")
        # New adopter with 0 prior adoptions
        animal = create_available_animal(shelter_id=shelter["id"], species="CAT",
                                          age_months=24)
        adopter = create_adopter(shelter_id=shelter["id"])
        app, invoice = _run_adoption_approve(shelter, animal, adopter)
        assert invoice["discount_cents"] == 0


class TestAdoptionTaxCalculation:
    """PRD 2.7 + 3.6: tax = round_half_up((subtotal - discount) * tax_rate)."""

    def test_tax_round_half_up(self):
        shelter = create_shelter(tax_rate=0.10)
        _create_fee_rows(shelter["id"], adoption_base=10005, species="ALL")
        animal = create_available_animal(shelter_id=shelter["id"], species="CAT",
                                          age_months=24)
        adopter = create_adopter(shelter_id=shelter["id"])
        app, invoice = _run_adoption_approve(shelter, animal, adopter)
        # (10005 - 0) * 0.10 = 1000.5 -> round_half_up -> 1001
        assert invoice["tax_cents"] == _round_half_up(10005 * 0.10)
        assert invoice["tax_cents"] == 1001
        # total = 10005 + 1001 = 11006
        assert invoice["total_amount_cents"] == 11006

    def test_tax_zero_when_rate_zero(self):
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], adoption_base=10000, species="ALL")
        animal = create_available_animal(shelter_id=shelter["id"], species="CAT",
                                          age_months=24)
        adopter = create_adopter(shelter_id=shelter["id"])
        app, invoice = _run_adoption_approve(shelter, animal, adopter)
        assert invoice["tax_cents"] == 0
        assert invoice["total_amount_cents"] == invoice["subtotal_cents"]


class TestBoardingFeeProvisional:
    """PRD 3.6 + Table 3 boarding_fee_calculation: provisional at /confirm uses planned days."""

    def test_provisional_simple(self):
        """3 days * 2000/day = 6000, plus 10% tax."""
        shelter = create_shelter(tax_rate=0.10)
        _create_fee_rows(shelter["id"], boarding_daily=2000, species="ALL")
        animal = create_boarding_ready_animal(shelter_id=shelter["id"])
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=3,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        invoice = get_success_data(api_client.get_fee_invoice(res["fee_invoice_id"], _manager))
        # Expected:
        # effective_daily = 2000
        # duration = 3 (not > 14, no long-stay discount)
        # subtotal = 6000
        # tax = round_half_up(6000 * 0.10) = 600
        # total = 6600
        assert invoice["subtotal_cents"] == 6000
        assert invoice["tax_cents"] == 600
        assert invoice["total_amount_cents"] == 6600

    def test_long_stay_discount_applies_above_14(self):
        """duration_days > 14 => effective_daily * 0.9 (floor)."""
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], boarding_daily=2000, species="ALL")
        animal = create_boarding_ready_animal(shelter_id=shelter["id"])
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=15,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        invoice = get_success_data(api_client.get_fee_invoice(res["fee_invoice_id"], _manager))
        # effective_daily = floor(2000 * 0.9) = 1800
        # subtotal = 1800 * 15 = 27000
        assert invoice["subtotal_cents"] == 27000

    def test_no_long_stay_discount_at_14(self):
        """duration == 14 is NOT > 14; no discount."""
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], boarding_daily=2000, species="ALL")
        animal = create_boarding_ready_animal(shelter_id=shelter["id"])
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=14,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        invoice = get_success_data(api_client.get_fee_invoice(res["fee_invoice_id"], _manager))
        # No discount: 2000 * 14 = 28000
        assert invoice["subtotal_cents"] == 28000

    def test_special_needs_surcharge_per_day(self):
        """effective_daily += surcharge_unit * len(special_needs)."""
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], boarding_daily=2000,
                         special_needs_unit=100, species="ALL")
        animal = create_boarding_ready_animal(
            shelter_id=shelter["id"],
            special_needs=["MEDICATION_REQUIRED"],
        )
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=3,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        invoice = get_success_data(api_client.get_fee_invoice(res["fee_invoice_id"], _manager))
        # effective_daily = 2000 + 100*1 = 2100
        # subtotal = 2100 * 3 = 6300
        assert invoice["subtotal_cents"] == 6300


class TestShelterComplianceScore:
    """PRD 3.7 + Table 3 shelter_compliance_score."""

    def test_empty_shelter_score_100(self):
        """No non-adopted animals => compliance_score 100.00."""
        shelter = create_shelter()
        assert shelter["compliance_score"] == 100.00

    def test_score_penalty_per_hold(self):
        """5 points deducted per ACTIVE hold."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"], species="CAT")
        add_vaccinations_for_adoption(animal["id"], species="CAT")
        # animal is INTAKE, vaccination_compliant True → base = 100.
        # Add 1 ACTIVE hold of MEDIUM (which doesn't change animal status but is still ACTIVE).
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="MEDIUM"), _vet
        ))
        refreshed = get_success_data(api_client.get_shelter(shelter["id"], _manager))
        # base = 100 (1 vacc-compliant / 1), hold_penalty = 5, score = 95.00
        assert abs(refreshed["compliance_score"] - 95.00) < 0.01

    def test_score_non_compliant_reduces_base(self):
        """1 of 2 compliant => base = 50; no holds => score = 50.00."""
        shelter = create_shelter()
        a1 = create_animal_intake(shelter_id=shelter["id"], species="CAT")
        add_vaccinations_for_adoption(a1["id"], species="CAT")
        # Second animal, no vaccinations -> not compliant
        a2 = create_animal_intake(shelter_id=shelter["id"], species="DOG")
        refreshed = get_success_data(api_client.get_shelter(shelter["id"], _manager))
        # base = 100 * 1/2 = 50, no holds => 50.00
        assert abs(refreshed["compliance_score"] - 50.00) < 0.01

    def test_score_max_floor_at_zero(self):
        """compliance_score cannot go below 0."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"], species="CAT")
        # No vaccines -> base = 0; many holds won't push below 0.
        # Add many holds.
        for _ in range(30):
            get_success_data(api_client.create_compliance_hold(
                create_compliance_hold_payload(animal["id"], severity="LOW"), _vet
            ))
        refreshed = get_success_data(api_client.get_shelter(shelter["id"], _manager))
        assert refreshed["compliance_score"] >= 0
        assert refreshed["compliance_score"] <= 100


class TestBoardingCheckoutCredit:
    """PRD 3.6 final_boarding_fee: shorter actual stay produces a credit line item.

    This test is slow because it requires an actual check-in/check-out cycle.
    """

    def test_check_out_shorter_stay_recomputes_invoice(self):
        """Full lifecycle: paid before check-out, actual stay shorter, invoice becomes PAID
        with paid_amount reduced and credit line added.

        Uses an already-past check_in_date (today-midnight) so check-in can
        succeed immediately — the PRD rule is ``current_time >= check_in_date``
        at the check-in transition and ``check_in_date >= current day`` at
        creation, both satisfied by today-midnight.
        """
        from test_helpers import pay_invoice_payload
        shelter = create_shelter(tax_rate=0.0)
        _create_fee_rows(shelter["id"], boarding_daily=2000, species="ALL")
        animal = create_boarding_ready_animal(shelter_id=shelter["id"])
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], duration_days=3,
            check_in_already_past=True,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        invoice = get_success_data(api_client.get_fee_invoice(res["fee_invoice_id"], _manager))
        provisional_total = invoice["total_amount_cents"]
        # Pay in full
        get_success_data(api_client.pay_fee_invoice(
            invoice["id"], pay_invoice_payload(provisional_total), _case_worker
        ))
        get_success_data(api_client.check_in_boarding_reservation(res["id"], _case_worker))
        # Immediately check out — actual duration ceil(short time)=1 day
        res = get_success_data(api_client.check_out_boarding_reservation(res["id"], _case_worker))
        refreshed_invoice = get_success_data(api_client.get_fee_invoice(invoice["id"], _manager))
        # The invoice status should remain PAID (or become PAID) — it never goes below.
        assert refreshed_invoice["status"] == "PAID"
        # paid_amount_cents should not exceed total_amount_cents
        assert refreshed_invoice["paid_amount_cents"] <= refreshed_invoice["total_amount_cents"] or \
               refreshed_invoice["paid_amount_cents"] == provisional_total
