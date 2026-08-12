"""Encounter lifecycle claims: close gates (clinical work, billing coding,
clearance posture), child lockout after close, fee-covered billing rules, pool
visit subsidy, and role exclusivity (PRD §3.5, §2.1)."""
from test_helpers import (
    ApiErrorId,
    assert_encounter,
    book_and_check_in,
    create_invoice_payload,
    create_lab_order_payload,
    create_prescription_payload,
    get_pool_by_term,
    get_student,
    make_pool,
    make_provider,
    make_stock,
    make_student,
    set_clock,
    setup_clearance_blocked_encounter,
    setup_open_encounter,
    validate_error,
    validate_success,
)


def test_encounter_close_gates_and_child_lockout(api, clinician_headers,
                                                 billing_officer_headers):
    """PRD §3.5: "All of its prescriptions must be terminal — every one in
    `DISPENSED` or `CANCELLED` — and every lab order must be `REVIEWED`; any
    residue is rejected with `ERR_UNRESOLVED_CLINICAL_WORK`."
    PRD §3.5: "If the encounter is chargeable, an invoice must already exist for
    it (`ERR_BILLING_NOT_CODED`)".
    PRD §3.5: "each creation requiring the parent encounter to be `OPEN` and
    failing with `ERR_ENCOUNTER_NOT_OPEN` otherwise".
    PRD §3.5: "A successful close ... cascades the linked appointment from
    `CHECKED_IN` to `COMPLETED`, its terminal state."

    Design: Corner/state_machines/encounter_close_gates_and_child_lockout
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S13", "Gate Test")
    provider = make_provider("Dr D")

    # enc1: urgent encounter with an ORDERED (never reviewed) lab order.
    appt1, enc1 = book_and_check_in(
        student["id"], provider["id"], "PRIMARY_URGENT",
        "2026-05-02T09:00:00Z", "2026-05-02T09:30:00Z",
    )
    validate_success(
        api.create_lab_order(enc1["id"], create_lab_order_payload("CBC"),
                             clinician_headers),
        201,
    )

    # enc2: chargeable SPORTS_PHYSICAL encounter with no invoice yet.
    appt2, enc2 = book_and_check_in(
        student["id"], provider["id"], "SPORTS_PHYSICAL",
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    stock = make_stock("GATE1", 10, 0)

    # Gate 1: unresolved clinical work blocks the close.
    res1 = api.close_encounter(enc1["id"], {}, clinician_headers)
    validate_error(res1, ApiErrorId.ERR_UNRESOLVED_CLINICAL_WORK, expected_status=409)

    # Gate 2: a chargeable encounter without an invoice is not coded.
    res2 = api.close_encounter(enc2["id"], {}, clinician_headers)
    validate_error(res2, ApiErrorId.ERR_BILLING_NOT_CODED, expected_status=409)

    # Code the encounter, then close succeeds and cascades the appointment.
    validate_success(
        api.create_invoice(
            enc2["id"],
            create_invoice_payload([
                {"service_category": "SPORTS_FEE", "charge_cents": 3000}
            ]),
            billing_officer_headers,
        ),
        201,
    )
    closed = validate_success(api.close_encounter(enc2["id"], {}, clinician_headers), 200)
    assert closed["status"] == "CLOSED"
    appt2_after = validate_success(api.get_appointment(appt2["id"], clinician_headers), 200)
    assert appt2_after["status"] == "COMPLETED"

    # After close the encounter rejects new children.
    res3 = api.create_prescription(
        enc2["id"],
        create_prescription_payload(stock["id"], 1),
        clinician_headers,
    )
    validate_error(res3, ApiErrorId.ERR_ENCOUNTER_NOT_OPEN, expected_status=409)


def test_invoice_rejected_for_fee_covered_encounter(api, clinician_headers,
                                                    billing_officer_headers):
    """PRD §3.5: "The encounter is fee-covered when its `visit_type` is one of
    `PRIMARY_URGENT`, `SAME_DAY_TRIAGE`, or `FOLLOW_UP` **and** the student's
    `enrollment_status` is `ENROLLED` at the moment of closing; the derived
    `fee_covered` flag records the verdict. Fee-covered encounters carry no
    invoice — generating one is rejected with `ERR_INVOICE_NOT_ALLOWED`".

    Design: Corner/state_machines/invoice_rejected_for_fee_covered_encounter
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, enc = setup_open_encounter(external_ref="S16")

    res = api.create_invoice(
        enc["id"],
        create_invoice_payload([{"service_category": "CONSULT", "charge_cents": 5000}]),
        billing_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVOICE_NOT_ALLOWED, expected_status=409)

    # The fee-covered encounter closes with no invoice at all.
    closed = validate_success(api.close_encounter(enc["id"], {}, clinician_headers), 200)
    assert_encounter(closed)
    assert closed["status"] == "CLOSED"
    assert closed["fee_covered"] is True


def test_pharmacist_cannot_close_encounter_forbidden(api, pharmacist_headers):
    """PRD §2.1: "an authenticated caller whose role is not on the endpoint's
    authorized list is rejected with `ERR_FORBIDDEN`." PRD §4: closing an
    encounter is authorized for `Clinician` only.

    Design: Corner/rbac/pharmacist_cannot_close_encounter_forbidden
    """
    set_clock("2026-05-01T00:00:00Z")
    _, _, _, enc = setup_open_encounter(external_ref="S62")
    res = api.close_encounter(enc["id"], {}, pharmacist_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_fee_covered_close_debits_pool_visit_cost(api, clinician_headers):
    """PRD §3.5: "If the encounter is fee-covered and an `OPEN` health-fee pool
    exists, the pool's `spent_cents` increases by the standard visit subsidy of
    12000 cents".

    Design: Corner/calculations/fee_covered_close_debits_pool_visit_cost
    """
    set_clock("2026-05-01T00:00:00Z")
    make_pool(term_code="SP26", budget_cents=100000)
    _, _, _, enc = setup_open_encounter(external_ref="S46")

    closed = validate_success(api.close_encounter(enc["id"], {}, clinician_headers), 200)
    assert closed["status"] == "CLOSED"
    assert closed["fee_covered"] is True

    pool = get_pool_by_term("SP26")
    assert pool["spent_cents"] == 12000, (
        f"fee-covered close must debit the open pool exactly 12000 cents, "
        f"got {pool['spent_cents']}"
    )


# ---------------------------------------------------------------------------
# Depth probes: sports clearance gated by the student's derived posture
# ---------------------------------------------------------------------------

def test_clearance_cleared_blocked_under_registration_hold(api, clinician_headers):
    """PRD §3.5: "a `clearance_outcome` of `CLEARED` additionally requires the
    student's `compliance_posture` to be `CLEAR`, failing with
    `ERR_CLEARANCE_BLOCKED` otherwise."
    PRD §3.1: "The posture is `REGISTRATION_HOLD` whenever either an
    immunization hold or a financial hold is present".

    Design: Difficulty/cross_entity_state_dependency/clearance_gated_by_student_posture
    """
    student, provider, appt, encounter, _ = setup_clearance_blocked_encounter()

    held = get_student(student["id"])
    assert held["compliance_posture"] == "REGISTRATION_HOLD", (
        "setup must leave the student in REGISTRATION_HOLD"
    )

    res = api.close_encounter(
        encounter["id"], {"clearance_outcome": "CLEARED"}, clinician_headers
    )
    validate_error(res, ApiErrorId.ERR_CLEARANCE_BLOCKED, expected_status=403)


def test_clearance_not_cleared_closes_despite_hold(api, clinician_headers,
                                                   front_desk_headers):
    """PRD §3.5: "The clearance outcome may also be recorded as `NOT_CLEARED`,
    which carries no posture gate."
    PRD §3.5: "A successful close stamps `closed_at`, moves the encounter from
    `OPEN` to `CLOSED`, and cascades the linked appointment from `CHECKED_IN` to
    `COMPLETED`, its terminal state."

    Design: Difficulty/cross_entity_state_dependency/clearance_gated_by_student_posture
    """
    student, provider, appt, encounter, _ = setup_clearance_blocked_encounter()

    closed = validate_success(
        api.close_encounter(
            encounter["id"], {"clearance_outcome": "NOT_CLEARED"}, clinician_headers
        ),
        200,
    )
    assert closed["status"] == "CLOSED"
    assert closed["clearance_outcome"] == "NOT_CLEARED"

    appt_after = validate_success(api.get_appointment(appt["id"], front_desk_headers), 200)
    assert appt_after["status"] == "COMPLETED"
