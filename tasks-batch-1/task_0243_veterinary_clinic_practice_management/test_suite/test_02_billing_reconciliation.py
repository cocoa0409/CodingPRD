"""Invoice estimate-vs-actual reconciliation, wellness realized savings, the
derived lifetime-invoiced field, and the household-version OCC guard.

The dual-variant billing instances are the depth core of this PRD: the
forward-looking estimate and the chronological actual diverge for the same visit.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_invoice, assert_wellness_plan,
    create_household, create_patient, create_wellness_plan, create_operatory,
    create_estimate, present_estimate, approve_estimate, post_deposit,
    create_appointment, appointment_check_in, appointment_begin_exam,
    appointment_complete, book_surgery, surgery_start, surgery_complete,
    create_resulted_lab_order, setup_completed_appointment_with_lab,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


class TestInvoiceEstimateVsActualDivergence:
    """estimate_total_cents (forward) and actual_total_cents (chronological) differ."""

    def _build_divergent_visit(self, api):
        operatory = create_operatory(cleanup_buffer_minutes=30, name="OR-1")
        hh = create_household("Rivera")
        _, pat = create_patient(household_id=hh["id"], name="Rex",
                                species="DOG", weight_kg=12.5)
        create_wellness_plan(pat["id"], tier="PLUS")
        line_items = [
            {"service_code": "DENTAL", "qty": 1, "unit_price_cents": 50000, "eligible_for_plan_discount": True},
            {"service_code": "MEDS", "qty": 1, "unit_price_cents": 20000, "eligible_for_plan_discount": False},
        ]
        est = create_estimate(pat["id"], line_items=line_items, deposit_required_cents=30000)
        hh_after = post_deposit(hh["id"], 30000, hh["version"], estimate_id=est["id"])
        present_estimate(est["id"])
        approve_estimate(est["id"])
        appt = create_appointment(pat["id"], scheduled_start="2026-07-01T09:00:00Z",
                                  scheduled_end="2026-07-01T11:00:00Z",
                                  visit_reason="Dental + surgery")
        appointment_check_in(appt["id"])
        appointment_begin_exam(appt["id"])
        surgery = book_surgery(appt["id"], operatory["id"], est["id"],
                               window_start="2026-07-01T09:00:00Z",
                               window_end="2026-07-01T10:30:00Z",
                               procedure_name="Dental extraction")
        lo = create_resulted_lab_order(appt["id"], fee_cents=8000, order_type="DENTAL_XRAY")
        surgery_start(surgery["id"])
        surgery_complete(surgery["id"])
        appointment_complete(appt["id"])
        hh_now = validate_success(api.get_household(hh["id"], PRACTICE_MANAGER), 200)
        return hh, pat, est, appt, hh_now["version"]

    def test_invoice_estimate_total_copies_estimate_projection(self, api):
        """PRD 3.11: "The forward-looking `estimate_total_cents` is a copy of the linked
        estimate's `estimated_total_cents` captured at finalize time, or zero if no
        estimate is linked."

        PLUS plan, one eligible 50000 line (discount 10000) + one non-eligible 20000 line
        -> estimated_total 60000, copied onto the invoice.

        Design: Difficulty/dual_variant_calc/invoice_estimate_vs_actual_billing_divergence
        """
        hh, pat, est, appt, hv = self._build_divergent_visit(api)
        res = api.create_invoice({
            "household_id": hh["id"], "appointment_id": appt["id"],
            "estimate_id": est["id"], "expected_household_version": hv,
        }, PRACTICE_MANAGER)
        inv = validate_success(res, 201)
        assert_invoice(inv)
        assert inv["estimate_total_cents"] == 60000, (
            f"Expected estimate_total 60000, got {inv['estimate_total_cents']}")

    def test_invoice_actual_and_variance_diverge_from_estimate(self, api):
        """PRD 3.11: "then every `DONE` surgery on the appointment ... contributing each
        surgery's `surgery_total_cents` minus its already-settled `deposit_consumed_cents`"
        and "The `variance_cents` records the difference, `actual_total_cents` minus
        `estimate_total_cents`, and may be negative."

        Surgery total 32000 - deposit_consumed 30000 = 2000; lab 8000; raw actual 10000;
        credit 0 -> actual 10000; variance 10000 - 60000 = -50000.

        Design: Difficulty/dual_variant_calc/invoice_estimate_vs_actual_billing_divergence
        """
        hh, pat, est, appt, hv = self._build_divergent_visit(api)
        res = api.create_invoice({
            "household_id": hh["id"], "appointment_id": appt["id"],
            "estimate_id": est["id"], "expected_household_version": hv,
        }, PRACTICE_MANAGER)
        inv = validate_success(res, 201)
        assert inv["actual_total_cents"] == 10000, (
            f"Expected actual 10000, got {inv['actual_total_cents']}")
        assert inv["variance_cents"] == -50000, (
            f"Expected variance -50000, got {inv['variance_cents']}")


class TestWellnessProjectedVsRealizedSavings:
    """realized_savings_cents tallies actual savings; projected is optimistic."""

    def test_bundled_vaccine_accrues_realized_savings_and_decrements_bundle(self, api):
        """PRD 3.4: "in that case the plan's `bundled_vaccines_remaining` is decremented
        by one and its `realized_savings_cents` is increased by the standard vaccine fee
        of 4,500 cents".

        PLUS plan starts with 4 bundled; after one bundled FVRCP dose,
        realized_savings_cents == 4500 and bundled_vaccines_remaining == 3.

        Design: Difficulty/dual_variant_calc/wellness_projected_vs_realized_savings_divergence
        """
        hh = create_household("Okafor")
        _, pat = create_patient(household_id=hh["id"], name="Milo",
                                species="CAT", weight_kg=4)
        wp = create_wellness_plan(pat["id"], tier="PLUS")
        api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "FVRCP",
            "administered_at": "2026-06-01T10:00:00Z", "bundled": True,
        }, VETERINARIAN)
        plan = validate_success(api.get_wellness_plan(wp["id"], VETERINARIAN), 200)
        assert_wellness_plan(plan)
        assert plan["realized_savings_cents"] == 4500, (
            f"Expected realized 4500, got {plan['realized_savings_cents']}")
        assert plan["bundled_vaccines_remaining"] == 3, (
            f"Expected 3 remaining, got {plan['bundled_vaccines_remaining']}")

    def test_realized_savings_zero_before_any_consumption(self, api):
        """PRD 3.2: "The plan also carries `realized_savings_cents`, a running tally
        initialized to zero".

        A freshly enrolled PLUS plan has realized_savings_cents == 0 and the full
        bundle of 4 remaining, distinct from the optimistic projection.

        Design: Difficulty/dual_variant_calc/wellness_projected_vs_realized_savings_divergence
        """
        hh = create_household("Fresh")
        _, pat = create_patient(household_id=hh["id"], name="New",
                                species="CAT", weight_kg=4)
        wp = create_wellness_plan(pat["id"], tier="PLUS")
        plan = validate_success(api.get_wellness_plan(wp["id"], VETERINARIAN), 200)
        assert plan["realized_savings_cents"] == 0, (
            f"Expected realized 0, got {plan['realized_savings_cents']}")
        assert plan["bundled_vaccines_remaining"] == 4, (
            f"Expected 4 remaining, got {plan['bundled_vaccines_remaining']}")


def test_derived_lifetime_invoiced_reconciles_after_finalize(api):
    """PRD 3.11: "its `lifetime_invoiced_cents` is increased by the finalized
    `actual_total_cents`".

    One invoice with actual_total 7000 -> Household.lifetime_invoiced_cents == 7000.

    Design: Corner/cross_cutting_complexity_layers/derived_lifetime_invoiced_reconciles_after_finalize
    """
    ctx = setup_completed_appointment_with_lab(fee_cents=7000)
    res = api.create_invoice({
        "household_id": ctx["household"]["id"],
        "appointment_id": ctx["appointment"]["id"],
        "expected_household_version": ctx["household_version"],
    }, PRACTICE_MANAGER)
    inv = validate_success(res, 201)
    assert inv["actual_total_cents"] == 7000, (
        f"Expected actual 7000, got {inv['actual_total_cents']}")
    hh = validate_success(api.get_household(ctx["household"]["id"], PRACTICE_MANAGER), 200)
    assert hh["lifetime_invoiced_cents"] == 7000, (
        f"Expected lifetime_invoiced 7000, got {hh['lifetime_invoiced_cents']}")


class TestHouseholdOccGuard:
    """Invoice finalize is OCC-guarded on expected_household_version (PRD 2.6)."""

    def test_stale_household_version_on_invoice_rejected(self, api):
        """PRD 2.6: "The server compares this value against the household's current
        `version`; if they do not match ... the finalize is rejected with
        `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412) before any credit is applied."

        A deposit bumps the household version after v0 capture; finalizing with the
        stale v0 is rejected with ERR_STALE_HOUSEHOLD_VERSION.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_household_version_on_invoice_rejected
        """
        hh = validate_success(api.create_household({"account_name": "Occ"}, PRACTICE_MANAGER), 201)
        v0 = hh["version"]
        _, pat = create_patient(household_id=hh["id"], name="OccPet",
                                species="DOG", weight_kg=10)
        post_deposit(hh["id"], 1000, v0)  # advances version to 2
        appt = create_appointment(pat["id"], scheduled_start="2026-08-10T09:00:00Z",
                                  scheduled_end="2026-08-10T10:00:00Z", visit_reason="Lab")
        appointment_check_in(appt["id"])
        appointment_begin_exam(appt["id"])
        create_resulted_lab_order(appt["id"], fee_cents=7000)
        appointment_complete(appt["id"])
        res = api.create_invoice({
            "household_id": hh["id"], "appointment_id": appt["id"],
            "expected_household_version": v0,
        }, PRACTICE_MANAGER)
        validate_error(res, "ERR_STALE_HOUSEHOLD_VERSION", expected_status=412)
