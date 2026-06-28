"""Pricing (estimate vs invoice variants, per-line rounding) and controlled-stock
reconciliation difficulty tests.

Queue A — Difficulty rules: dual_variant_calc, combinatorial_formula,
compensating_invariant (drug conservation), plus corner-design calculation and
consistency claims that share the same pricing machinery.
"""
import pytest

from test_helpers import (
    api_client as _ac,  # noqa: F401  (kept for symmetry; tests use the `api` fixture)
    TEST_USERS,
    make_clinician_headers,
    validate_success,
    get_success_data,
    setup_in_visit_with_estimate,
    setup_booked_appointment,
    setup_euthanasia_reconciled,
    setup_in_visit,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ===========================================================================
# dual_variant_calc / estimate_vs_invoice_total_on_estimate
# ===========================================================================

def test_estimate_total_projects_full_vaccine_qty(api):
    """PRD §3.4: "At estimate time, before the visit, every line is billed at its
    full requested quantity — an optimistic projection of the full plan."

    A VACCINE_DOSE line at qty 2 (unit 6500) plus an EXAM_FEE 9000x1 plus a 2000
    travel surcharge projects 9000 + 13000 + 2000 == 24000 at estimate time.

    Design: Difficulty/dual_variant_calc/estimate_vs_invoice_total_on_estimate
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[
            {"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1},
            {"code": "VACCINE_DOSE", "label": "Vaccine", "unit_cents": 6500, "qty": 2},
        ],
        approve=True,
        visit_type="VACCINE",
        vaccine_doses=1,
        travel_surcharge_cents=2000,
        vaccine_stock_count=10,
    )
    est = ctx["estimate"]
    assert est["estimate_total_cents"] == 24000, \
        f"estimate_total should project full qty: 9000+13000+2000, got {est['estimate_total_cents']}"


def test_invoice_total_caps_vaccine_at_administered_doses(api):
    """PRD §3.4: "a line whose `code` is `VACCINE_DOSE` is billed not for its full
    quantity but for the lesser of its quantity and the doses the appointment
    actually administered (its `vaccine_doses`); every other line bills its full
    quantity."
    PRD §3.5: "Closing the visit finalizes the estimate, moving it from `APPROVED`
    to `INVOICED` and computing its `invoice_total_cents` by the invoice variant of
    §3.4."

    EXAM 9000 + min(2,1)*6500 + 2000 travel == 17500 at visit close.

    Design: Difficulty/dual_variant_calc/estimate_vs_invoice_total_on_estimate
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[
            {"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1},
            {"code": "VACCINE_DOSE", "label": "Vaccine", "unit_cents": 6500, "qty": 2},
        ],
        approve=True,
        visit_type="VACCINE",
        vaccine_doses=1,
        travel_surcharge_cents=2000,
        vaccine_stock_count=10,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    validate_success(api.complete_visit(ctx["appointment"]["id"], clin))
    est = validate_success(api.get_estimate(ctx["estimate"]["id"], clin))
    assert est["status"] == "INVOICED"
    assert est["invoice_total_cents"] == 17500, \
        f"invoice_total should cap vaccine qty to 1: 9000+6500+2000, got {est['invoice_total_cents']}"
    assert est["estimate_total_cents"] == 24000, \
        "estimate_total should remain the optimistic projection"


# ===========================================================================
# combinatorial_formula / invoice_min_cap_nonlinear_branch
# ===========================================================================

def test_invoice_min_cap_branch_and_vaccine_stock_decrement(api):
    """PRD §3.4: "a line whose `code` is `VACCINE_DOSE` is billed not for its full
    quantity but for the lesser of its quantity and the doses the appointment
    actually administered (its `vaccine_doses`); every other line bills its full
    quantity."
    PRD §3.5: "When the visit was a vaccination, the van's `vaccine_stock_count` is
    decremented by the administered `vaccine_doses`, cascading the vehicle
    inventory."

    9000 + min(2,1)*6500 + 2000 == 17500; vaccine stock 10 -> 9 (one dose given).

    Design: Difficulty/combinatorial_formula/invoice_min_cap_nonlinear_branch
    """
    ctx = setup_in_visit_with_estimate(
        line_items=[
            {"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1},
            {"code": "VACCINE_DOSE", "label": "Vaccine", "unit_cents": 6500, "qty": 2},
        ],
        approve=True,
        visit_type="VACCINE",
        vaccine_doses=1,
        travel_surcharge_cents=2000,
        vaccine_stock_count=10,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    validate_success(api.complete_visit(ctx["appointment"]["id"], clin))
    est = validate_success(api.get_estimate(ctx["estimate"]["id"], clin))
    assert est["invoice_total_cents"] == 17500
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], DISPATCHER))
    assert van["vaccine_stock_count"] == 9, \
        f"vaccine_stock_count should drop by administered doses (1), got {van['vaccine_stock_count']}"


# ===========================================================================
# combinatorial_formula / estimate_round_per_line_then_sum_order
# ===========================================================================

def test_estimate_rounds_per_line_then_sums(api):
    """PRD §3.4: "Each line's contribution is the unit price multiplied by the
    quantity, rounded half-up to whole cents on that line alone; `subtotal_cents`
    is the running sum of those per-line rounded amounts, accumulated in the array
    order of the line items."
    PRD §2.7: "the system never sums raw products and rounds once at the end."

    Two lines of unit 333 x qty 0.5 round per line (167 + 167 = 334), not 333.

    Design: Difficulty/combinatorial_formula/estimate_round_per_line_then_sum_order
    """
    ctx = setup_booked_appointment(
        visit_type="VACCINE", travel_surcharge_cents=0, vaccine_doses=1,
        species="CAT", weight_kg=4, vaccine_stock_count=5,
    )
    clin = make_clinician_headers(ctx["clinician_id"])
    est = validate_success(
        api.create_estimate(
            {"appointment_id": ctx["appointment"]["id"],
             "line_items": [
                 {"code": "SUPPLY", "label": "Half A", "unit_cents": 333, "qty": 0.5},
                 {"code": "SUPPLY", "label": "Half B", "unit_cents": 333, "qty": 0.5},
             ]},
            clin,
        ),
        expected_status=201,
    )
    assert est["subtotal_cents"] == 334, \
        f"per-line rounding 167+167 must give 334 (sum-then-round gives 333), got {est['subtotal_cents']}"
    assert est["estimate_total_cents"] == 334


# ===========================================================================
# Corner / calculations / estimate_total_includes_travel_surcharge
# ===========================================================================

def test_estimate_copies_travel_surcharge_from_service_area(api):
    """PRD §3.4: "The system then reads the `travel_surcharge_cents` from the
    service area resolved through the appointment's patient and copies it onto the
    estimate, and `estimate_total_cents` is the subtotal plus that travel
    surcharge."

    subtotal 9000 + surcharge 1500 == 10500.

    Design: Corner/calculations/estimate_total_includes_travel_surcharge
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=1500)
    clin = make_clinician_headers(ctx["clinician_id"])
    est = validate_success(
        api.create_estimate(
            {"appointment_id": ctx["appointment"]["id"],
             "line_items": [{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}]},
            clin,
        ),
        expected_status=201,
    )
    assert est["subtotal_cents"] == 9000
    assert est["travel_surcharge_cents"] == 1500
    assert est["estimate_total_cents"] == 10500


# ===========================================================================
# Corner / consistency_model / immediate_visibility_estimate_total_in_create_response
# ===========================================================================

def test_estimate_total_present_in_create_response(api):
    """PRD §3.4: "From its line items the system derives the money fields
    bottom-up."
    PRD §2.2: "operations that create or modify a resource will return the created
    or updated resource object in the data field."

    estimate_total_cents == 12000 is returned in the POST /estimates response
    itself, not on a later read (single 12000 line, surcharge 0).

    Design: Corner/consistency_model/immediate_visibility_estimate_total_in_create_response
    """
    ctx = setup_booked_appointment(travel_surcharge_cents=0)
    clin = make_clinician_headers(ctx["clinician_id"])
    est = validate_success(
        api.create_estimate(
            {"appointment_id": ctx["appointment"]["id"],
             "line_items": [{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 12000, "qty": 1}]},
            clin,
        ),
        expected_status=201,
    )
    assert est["estimate_total_cents"] == 12000, \
        "estimate_total_cents must be present and correct in the create response"


# ===========================================================================
# dual_variant_calc / controlled_running_balance_vs_recount_on_rolling_clinic
# compensating_invariant / controlled_drug_conservation_dispense_waste
# ===========================================================================

def test_controlled_running_balance_and_recount_agree_after_reconcile(api):
    """PRD §3.7: "Reconciliation passes only if this independent recount equals the
    running `controlled_stock_ml` balance the day's side effects produced."
    PRD §3.5: "Each accepted entry appends to the log and decrements the vehicle's
    `controlled_stock_ml` by the entry's `amount_ml`."

    A 6.0 DISPENSE and a 2.0 WASTE on a 50.0 start leave both the running balance
    and the independent recount at 42.0.

    Design: Difficulty/dual_variant_calc/controlled_running_balance_vs_recount_on_rolling_clinic
    """
    ctx = setup_euthanasia_reconciled(dispense_ml=6.0, waste_ml=2.0, controlled_stock_ml=50)
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], COMPLIANCE))
    assert van["controlled_stock_ml"] == 42.0, \
        f"running balance 50 - 6 - 2 == 42.0, got {van['controlled_stock_ml']}"
    assert van["controlled_reconciled_ml"] == 42.0, \
        f"independent recount must agree at 42.0, got {van['controlled_reconciled_ml']}"
    rd = validate_success(api.get_route_day(ctx["route_day"]["id"], COMPLIANCE))
    assert rd["posture"] == "RECONCILED"


def test_controlled_drug_conservation_dispense_plus_waste(api):
    """PRD §3.7: "subtracting each entry's `amount_ml` — both `DISPENSE` and
    `WASTE` remove drug from the van."
    PRD §3.7: "Reconciliation passes only if this independent recount equals the
    running `controlled_stock_ml` balance the day's side effects produced."

    Conservation: starting 50.0 == remaining 42.0 + dispensed 6.0 + wasted 2.0,
    and the recount confirms controlled_reconciled_ml == controlled_stock_ml.

    Design: Difficulty/compensating_invariant/controlled_drug_conservation_dispense_waste
    """
    ctx = setup_euthanasia_reconciled(dispense_ml=6.0, waste_ml=2.0, controlled_stock_ml=50)
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], COMPLIANCE))
    remaining = van["controlled_stock_ml"]
    assert remaining == 42.0
    assert van["controlled_reconciled_ml"] == 42.0
    # 50.0 == 42.0 + 6.0 + 2.0
    assert remaining + 6.0 + 2.0 == 50.0, "conserved drug mL: start == remaining + dispensed + wasted"


# ===========================================================================
# Corner / calculations / euthanasia_dose_floor_applies_for_small_animal
# ===========================================================================

def test_dose_floor_honored_for_small_animal(api):
    """PRD §3.5: "the required volume is the larger of the weight-derived figure
    and the 1.0-milliliter floor."
    PRD §3.5: "Each accepted entry appends to the log and decrements the vehicle's
    `controlled_stock_ml` by the entry's `amount_ml`."

    For a 4kg cat raw 4*0.2=0.8 < floor 1.0, so a DISPENSE of exactly 1.0 succeeds;
    stock 50.0 -> 49.0.

    Design: Corner/calculations/euthanasia_dose_floor_applies_for_small_animal
    """
    from test_helpers import setup_euthanasia_in_visit, dispense
    ctx = setup_euthanasia_in_visit(weight_kg=4, controlled_stock_ml=50,
                                    clock="2026-03-15T08:00:00Z")
    log = dispense(ctx["appointment"]["id"], ctx["van"]["id"], ctx["clinician_id"], 1.0)
    assert log["amount_ml"] == 1.0
    van = validate_success(api.get_rolling_clinic(ctx["van"]["id"], DISPATCHER))
    assert van["controlled_stock_ml"] == 49.0, \
        f"stock 50.0 - 1.0 floor dose == 49.0, got {van['controlled_stock_ml']}"
