"""Visit settlement: cash charges, insurance superbills, and their divergence.

Covers the dual-variant calculation difficulty instance (cash Charge vs insurance
Superbill diverge) and the rounding-order-pinned superbill difficulty instance, plus
corner instances for the cash-discount calculation, derived-field reconciliation, and
the add-on endpoint.
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_practitioner_headers,
    assert_charge, assert_superbill, assert_addon,
    setup_clinic_scenario, book_appointment, add_addon, check_in_and_complete,
    book_check_in_complete,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def _only_charge_for(api, appt_id):
    data, _ = _list(api.list_charges(ADMIN, params={"appointment_id": appt_id}))
    assert len(data) == 1, f"expected exactly one charge for {appt_id}, got {len(data)}"
    return data[0]


def _only_superbill_for(api, appt_id):
    data, _ = _list(api.list_superbills(ADMIN, params={"appointment_id": appt_id}))
    assert len(data) == 1, f"expected exactly one superbill for {appt_id}, got {len(data)}"
    return data[0]


def _list(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)


# ─── Dual-variant divergence (queue A) ─────────────────────────────────────
def test_cash_charge_vs_insurance_superbill_diverge(api):
    """PRD 3.8: "Its total_due_cents, the patient responsibility, is the subtotal minus
    the cash discount."
    PRD 3.8: "The insurance_allowed_cents is computed by rounding each individual line
    amount times the patient's coinsurance_rate to whole cents and then summing those
    per-line rounded results — the rounding is performed per line and then the lines are
    summed, never the reverse."
    PRD 3.8: "The patient_responsibility_cents is the sum of all line amounts minus
    insurance_allowed_cents."

    Design: Difficulty/dual_variant_calc/visit_charge_cash_vs_insurance_diverge
    """
    # CASH patient: subtotal 18030, discount 1803, total_due 16227.
    cash_ctx = setup_clinic_scenario(payer_mode="CASH")
    cash = book_check_in_complete(
        cash_ctx, base_fee_cents=12010,
        addons=[("CUPPING", 3510), ("MOXA", 2510)],
        scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T10:45:00Z",
        clock_iso="2026-06-01T10:00:00Z")
    charge = _only_charge_for(api, cash["appointment"]["id"])
    assert_charge(charge)
    assert charge["subtotal_cents"] == 18030
    assert charge["cash_discount_cents"] == 1803
    assert charge["total_due_cents"] == 16227

    # INSURANCE patient (coinsurance 0.65): allowed 11721, patient_resp 6309.
    ins_ctx = setup_clinic_scenario(
        payer_mode="INSURANCE",
        patient_overrides={"insurance_member_id": "M-1", "coinsurance_rate": 0.65})
    ins = book_check_in_complete(
        ins_ctx, base_fee_cents=12010,
        addons=[("CUPPING", 3510), ("MOXA", 2510)],
        scheduled_start="2026-06-01T12:00:00Z", scheduled_end="2026-06-01T12:45:00Z",
        clock_iso="2026-06-01T12:00:00Z")
    superbill = _only_superbill_for(api, ins["appointment"]["id"])
    assert_superbill(superbill)
    assert superbill["insurance_allowed_cents"] == 11721
    assert superbill["patient_responsibility_cents"] == 6309

    # The two patient-owed figures diverge for the identical subtotal.
    assert charge["total_due_cents"] != superbill["patient_responsibility_cents"]


def test_insurance_patient_produces_superbill_not_charge(api):
    """PRD 3.8: "For an insurance patient (payer_mode of INSURANCE), a Superbill is
    produced instead, and no cash discount applies."

    Design: Difficulty/dual_variant_calc/visit_charge_cash_vs_insurance_diverge
    """
    ctx = setup_clinic_scenario(
        payer_mode="INSURANCE",
        patient_overrides={"insurance_member_id": "M-9", "coinsurance_rate": 0.65})
    res = book_check_in_complete(
        ctx, base_fee_cents=12010, addons=[("CUPPING", 3510), ("MOXA", 2510)],
        scheduled_start="2026-06-01T14:00:00Z", scheduled_end="2026-06-01T14:45:00Z",
        clock_iso="2026-06-01T14:00:00Z")
    appt_id = res["appointment"]["id"]
    charges, _ = _list(api.list_charges(ADMIN, params={"appointment_id": appt_id}))
    assert charges == [], "insurance visit must not produce a Charge"
    superbill = _only_superbill_for(api, appt_id)
    assert superbill["status"] == "ISSUED"


# ─── Round-per-line-then-sum order pinned (queue A) ────────────────────────
def test_superbill_rounds_per_line_then_sums(api):
    """PRD 3.8: "the rounding is performed per line and then the lines are summed,
    never the reverse."

    Design: Difficulty/combinatorial_formula/superbill_round_per_line_then_sum_order_pinned
    """
    ctx = setup_clinic_scenario(
        payer_mode="INSURANCE",
        patient_overrides={"insurance_member_id": "M-2", "coinsurance_rate": 0.65})
    res = book_check_in_complete(
        ctx, base_fee_cents=12010, addons=[("CUPPING", 3510), ("MOXA", 2510)],
        scheduled_start="2026-06-04T09:00:00Z", scheduled_end="2026-06-04T09:45:00Z",
        clock_iso="2026-06-04T09:00:00Z")
    superbill = _only_superbill_for(api, res["appointment"]["id"])
    # round-per-line: 7807 + 2282 + 1632 = 11721 (sum-then-round would give 11720).
    assert superbill["insurance_allowed_cents"] == 11721
    assert superbill["insurance_allowed_cents"] != 11720
    assert superbill["patient_responsibility_cents"] == 6309


def test_superbill_line_charges_order_base_first(api):
    """PRD 3.8: "The line_charges_cents is an ordered list of cents amounts: the
    base_fee_cents first, then each ATTACHED add-on's fee_cents in ascending
    created_at order."

    Design: Difficulty/combinatorial_formula/superbill_round_per_line_then_sum_order_pinned
    """
    ctx = setup_clinic_scenario(
        payer_mode="INSURANCE",
        patient_overrides={"insurance_member_id": "M-3", "coinsurance_rate": 0.65})
    res = book_check_in_complete(
        ctx, base_fee_cents=12010, addons=[("CUPPING", 3510), ("MOXA", 2510)],
        scheduled_start="2026-06-04T11:00:00Z", scheduled_end="2026-06-04T11:45:00Z",
        clock_iso="2026-06-04T11:00:00Z")
    superbill = _only_superbill_for(api, res["appointment"]["id"])
    assert superbill["line_charges_cents"] == [12010, 3510, 2510]


# ─── Cash discount calculation (corner) ────────────────────────────────────
def test_cash_charge_no_addons_discount_applied(api):
    """PRD 3.8: "Its cash_discount_cents is the subtotal multiplied by the cash discount
    fraction of ten percent (0.10), rounded half up to whole cents — and is 0 for any
    patient who is not cash."
    PRD 3.8: "Its total_due_cents, the patient responsibility, is the subtotal minus the
    cash discount."
    PRD 3.8: "A visit charge has charge_type of VISIT, as opposed to the PENALTY
    charge_type produced by penalties, and opens with status of OPEN; a charge moves to
    VOID when its appointment's cancellation reverses it."

    Design: Corner/calculations/cash_charge_no_addons_discount_applied
    """
    ctx = setup_clinic_scenario(payer_mode="CASH")
    res = book_check_in_complete(
        ctx, base_fee_cents=10000, addons=[],
        scheduled_start="2026-06-21T10:00:00Z", scheduled_end="2026-06-21T10:45:00Z",
        clock_iso="2026-06-21T10:00:00Z")
    charge = _only_charge_for(api, res["appointment"]["id"])
    assert charge["subtotal_cents"] == 10000
    assert charge["cash_discount_cents"] == 1000
    assert charge["total_due_cents"] == 9000
    assert charge["charge_type"] == "VISIT"


def test_charge_subtotal_reconciles_with_addon(api):
    """PRD 3.8: "the visit subtotal is the appointment's base_fee_cents plus the sum of
    the fee_cents of every add-on on the appointment whose status is ATTACHED; add-ons
    that have been voided are excluded from the subtotal."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconcile_after_addon_added
    """
    ctx = setup_clinic_scenario(payer_mode="CASH")
    res = book_check_in_complete(
        ctx, base_fee_cents=10000, addons=[("MOXA", 4000)],
        scheduled_start="2026-06-27T10:00:00Z", scheduled_end="2026-06-27T10:45:00Z",
        clock_iso="2026-06-27T10:00:00Z")
    charge = _only_charge_for(api, res["appointment"]["id"])
    assert charge["subtotal_cents"] == 14000
    assert charge["cash_discount_cents"] == 1400
    assert charge["total_due_cents"] == 12600


# ─── Add-on endpoint (corner) ──────────────────────────────────────────────
def test_addon_attached_to_scheduled_appointment(api):
    """PRD 3.5: "During a scheduled appointment's life a ClinicAdmin or a Practitioner
    may attach a cupping or moxibustion add-on, supplying the modality (CUPPING or MOXA)
    and the add-on fee_cents."
    PRD 3.5: "An attached add-on begins with status of ATTACHED and increments the parent
    appointment's version; its fee participates in the visit's billing totals as
    described below."

    Design: Corner/endpoints/addon_attached_to_scheduled_appointment
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-25T10:00:00Z",
                            scheduled_end="2026-06-25T10:45:00Z")
    ph = make_practitioner_headers(ctx["practitioner"]["id"])
    addon = validate_success(
        api.add_addon(appt["id"], {"modality": "CUPPING", "fee_cents": 3500}, ph), 201)
    assert_addon(addon)
    assert addon["status"] == "ATTACHED"
    assert addon["modality"] == "CUPPING"
    assert addon["fee_cents"] == 3500
    listed, _ = _list(api.list_addons(ADMIN, params={"appointment_id": appt["id"]}))
    assert any(a["id"] == addon["id"] for a in listed)
