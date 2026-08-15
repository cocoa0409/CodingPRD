"""1098-T box computation, lifecycle, correction chain, and uniqueness claims
(PRD §3.11)."""
from test_helpers import (
    ApiErrorId,
    create_posted_waiver,
    create_tax_form,
    make_payment,
    make_student,
    setup_account_with_enrollment,
    validate_error,
    validate_success,
)


def test_form1098t_box1_box5_amounts(api, bursar_staff_headers):
    """PRD §3.11: "Box 1, `box1_cents`, reports payments received for qualified
    tuition: it is the smaller of two in-scope sums — the signed sum of
    `PAYMENT` entries positive and `PAYMENT_REVERSAL` entries negative, and the
    signed sum of tuition-kind `CHARGE` entries positive and tuition-kind
    `CHARGE_REVERSAL` entries negative — floored at zero. Box 5, `box5_cents`,
    reports scholarships and waivers as the signed sum of `WAIVER` entries
    positive and `WAIVER_REVERSAL` entries negative over the same accounts,
    again floored at zero. Box 4, `box4_cents`, reports prior-year adjustments
    and is always zero in this version. A form is born `DRAFT` with
    `corrected_from_id` null."

    Design: Corner/calculations/form1098t_box1_box5_amounts
    """
    ctx = setup_account_with_enrollment(credit_hours=12, external_ref="S-1098")
    acc = ctx["account_id"]
    create_posted_waiver(acc, kind="SCHOLARSHIP", awarded_cents=100000)
    make_payment(acc, 200000)
    make_payment(acc, 150000, method="ACH")

    form = validate_success(
        api.create_tax_form(
            {"student_id": ctx["student"]["id"], "tax_year": 2026},
            bursar_staff_headers,
        ),
        201,
    )
    # Payments received 350000 vs QTRE (tuition-kind) charges 420000; the
    # 15000 FEE charge is not QTRE.
    assert form["box1_cents"] == 350000
    assert form["box5_cents"] == 100000
    assert form["box4_cents"] == 0
    assert form["status"] == "DRAFT"
    assert form["corrected_from_id"] is None


def test_tax_form_correction_chain(api, bursar_staff_headers,
                                   bursar_manager_headers):
    """PRD §3.11: "Correction, likewise manager-only, applies to a `FINALIZED`
    form: the original moves to terminal `SUPERSEDED`, and a fresh `DRAFT` form
    is created for the same student and tax year with its `corrected_from_id`
    pointing at the superseded original and its box amounts recomputed from the
    ledger as of correction time."

    Design: Corner/state_machines/tax_form_correction_chain
    """
    ctx = setup_account_with_enrollment(credit_hours=12, external_ref="S-TAX")
    form = create_tax_form(ctx["student"]["id"], 2026)
    finalized = validate_success(
        api.finalize_tax_form(form["id"], bursar_manager_headers), 200
    )
    assert finalized["status"] == "FINALIZED"

    replacement = validate_success(
        api.correct_tax_form(form["id"], bursar_manager_headers), 200
    )
    assert replacement["status"] == "DRAFT"
    assert replacement["corrected_from_id"] == form["id"]
    assert replacement["id"] != form["id"]
    assert replacement["student_id"] == ctx["student"]["id"]
    assert replacement["tax_year"] == 2026

    original = validate_success(
        api.get_tax_form(form["id"], bursar_staff_headers), 200
    )
    assert original["status"] == "SUPERSEDED"


def test_duplicate_tax_form_conflict(api, bursar_staff_headers):
    """PRD §3.11: "Only one live form may exist per student per year: creation
    while a `DRAFT` or `FINALIZED` form already exists for that pair is
    rejected with `ERR_DUPLICATE_TAX_FORM` (HTTP 409)."

    Design: Corner/validations/duplicate_tax_form_conflict
    """
    student = make_student("S-DUP", "Dup Form")
    create_tax_form(student["id"], 2026)
    res = api.create_tax_form({"student_id": student["id"], "tax_year": 2026},
                              bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_TAX_FORM, expected_status=409)
    forms = validate_success(
        api.list_student_tax_forms(student["id"], bursar_staff_headers), 200
    )
    assert len(forms) == 1


def test_tax_form_state_errors(api, bursar_manager_headers):
    """PRD §3.11: "Finalizing, a `BursarManager`-only act, moves a `DRAFT` form
    to `FINALIZED`; anything else yields `ERR_TAX_FORM_STATE_INVALID`
    (HTTP 409). Correction, likewise manager-only, applies to a `FINALIZED`
    form".

    Design: Corner/errors/tax_form_state_errors
    """
    student = make_student("S-TFS", "Tax States")
    form_draft = create_tax_form(student["id"], 2026)
    form_fin = create_tax_form(student["id"], 2025)
    validate_success(api.finalize_tax_form(form_fin["id"], bursar_manager_headers),
                     200)

    # Double finalize: the form is no longer DRAFT.
    res = api.finalize_tax_form(form_fin["id"], bursar_manager_headers)
    validate_error(res, ApiErrorId.ERR_TAX_FORM_STATE_INVALID,
                   expected_status=409)

    # Correct requires FINALIZED; the 2026 form is still DRAFT.
    res = api.correct_tax_form(form_draft["id"], bursar_manager_headers)
    validate_error(res, ApiErrorId.ERR_TAX_FORM_STATE_INVALID,
                   expected_status=409)
