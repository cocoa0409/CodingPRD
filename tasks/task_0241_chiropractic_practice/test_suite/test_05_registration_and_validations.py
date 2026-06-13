"""Patient registration, CRUD/listing, payer-mode coherence, plan-readiness,
SOAP-provider match, regression-severity, and fee-schedule supersede.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_provider_headers,
    create_patient_payload,
    create_insurance_policy_payload,
    create_appointment_payload,
    create_soap_note_payload,
    setup_base_practice,
    create_cash_patient,
    create_wellness_plan,
    create_finalized_exam,
    propose_plan,
    add_phase,
    activate_plan,
    book_appointment,
    setup_active_plan,
    setup_plan_with_corrective_in_progress,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
ADMIN = TEST_USERS["admin_headers"]
BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# Corner: entities / create_patient_returns_201_with_defaults
# ===========================================================================
def test_create_patient_returns_201_with_defaults(api):
    """PRD §3.2: "A newly registered patient starts `ACTIVE` with a
    `no_show_strike_count` of 0, a `ledger_balance_cents` of 0, and `is_dismissed`
    false."
    PRD §2.4: "`version`: an integer that starts at the resource's creation value
    and increments by one with every mutation."

    Design: Corner/entities/create_patient_returns_201_with_defaults
    """
    res = api.create_patient(
        create_patient_payload(full_name="New Nora", date_of_birth="1990-05-05", payer_mode="CASH"),
        FRONTDESK,
    )
    pt = validate_success(res, 201)
    assert pt["status"] == "ACTIVE"
    assert pt["no_show_strike_count"] == 0
    assert pt["ledger_balance_cents"] == 0
    assert pt["is_dismissed"] is False
    assert pt["version"] == 1


# ===========================================================================
# Corner: entities / get_patient_returns_stored_entity
# ===========================================================================
def test_get_patient_returns_stored_entity(api):
    """PRD §3.2: "A `FrontDesk` operator (or a `PracticeAdmin`) registers a patient
    with a `full_name`, a `date_of_birth` given as an ISO 8601 date, and a
    `payer_mode` selecting which billing algorithm will apply to that patient's
    visits."

    A GET echoes the stored full_name and payer_mode the patient was registered
    with.

    Design: Corner/entities/get_patient_returns_stored_entity
    """
    created = validate_success(
        api.create_patient(
            create_patient_payload(full_name="Read Rita", date_of_birth="1990-05-05", payer_mode="CASH"),
            FRONTDESK,
        ),
        201,
    )
    got = validate_success(api.get_patient(created["id"], FRONTDESK), 200)
    assert got["full_name"] == "Read Rita"
    assert got["payer_mode"] == "CASH"


# ===========================================================================
# Corner: entities / list_patients_paginated_envelope
# ===========================================================================
def test_list_patients_paginated_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_patients_paginated_envelope
    """
    validate_success(api.create_patient(create_patient_payload(full_name="P1"), FRONTDESK), 201)
    validate_success(api.create_patient(create_patient_payload(full_name="P2"), FRONTDESK), 201)
    data, meta = validate_paginated(api.list_patients(FRONTDESK, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ===========================================================================
# Corner: entities / get_patient_not_found
# ===========================================================================
def test_get_patient_not_found(api):
    """PRD §2.6: "It first confirms the patient named by the leading path segment
    exists, rejecting with `ERR_PATIENT_NOT_FOUND` if it does not".

    Design: Corner/entities/get_patient_not_found
    """
    res = api.get_patient(NON_EXISTENT_UUID, FRONTDESK)
    validate_error(res, "ERR_PATIENT_NOT_FOUND")


# ===========================================================================
# Corner: entities / create_patient_missing_required_field
# ===========================================================================
def test_create_patient_missing_payer_mode_defaults_or_invalid(api):
    """PRD §2.2: malformed body -> `ERR_INVALID_REQUEST`.

    payer_mode defaults to CASH (PRD §3.2), but full_name is required; omitting it
    is a malformed body. We omit full_name to pin ERR_INVALID_REQUEST.

    Design: Corner/entities/create_patient_missing_required_field
    """
    res = api.create_patient({"date_of_birth": "1990-05-05", "payer_mode": "CASH"}, FRONTDESK)
    validate_error(res, "ERR_INVALID_REQUEST")


# ===========================================================================
# Corner: entities / create_appointment_bad_enum_visit_type
# ===========================================================================
def test_create_appointment_bad_enum_visit_type(api):
    """PRD §3.6: "then well-formedness and enum-domain validity of the body".
    A visit_type outside the declared domain is a malformed body ->
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/create_appointment_bad_enum_visit_type
    """
    base = setup_base_practice()
    patient = create_cash_patient("Enum Ed")
    res = api.book_appointment(
        patient["id"],
        create_appointment_payload(
            base["provider"]["id"], base["room"]["id"], visit_type="MASSAGE",
            scheduled_start="2026-03-03T17:00:00Z",
        ),
        FRONTDESK,
    )
    validate_error(res, "ERR_INVALID_REQUEST")


# ===========================================================================
# Corner: entities / computed_fields_system_minted_input_ignored
# ===========================================================================
def test_computed_fields_are_system_minted(api):
    """PRD §3.2: "The `no_show_strike_count`, `ledger_balance_cents`, and
    `is_dismissed` flags on a patient are computed, never client-supplied."
    PRD §3.2: "A newly registered patient starts `ACTIVE` with a
    `no_show_strike_count` of 0, a `ledger_balance_cents` of 0".

    Design: Corner/entities/computed_fields_system_minted_input_ignored
    """
    res = api.create_patient(
        create_patient_payload(full_name="Sys Sam", date_of_birth="1990-05-05", payer_mode="CASH"),
        FRONTDESK,
    )
    pt = validate_success(res, 201)
    assert pt["ledger_balance_cents"] == 0
    assert pt["status"] == "ACTIVE"
    assert pt["version"] == 1


# ===========================================================================
# Corner: entities / immutable_ledger_entry_no_version_field
# ===========================================================================
def test_ledger_entry_has_no_version_field(api):
    """PRD §2.4: "A `LedgerEntry` and the `PracticeClock` are append-only or
    singleton records that are never mutated in place; each carries only `id` and
    `created_at`, and neither has an `updated_at` nor a `version` field."
    PRD §3.9: "The payment appends a `PATIENT_PAYMENT` ledger entry carrying the
    negative of `amount_cents`".

    Design: Corner/entities/immutable_ledger_entry_no_version_field
    """
    patient = create_cash_patient("Led Lee")
    pid = patient["id"]
    validate_success(api.post_payment(pid, {"amount_cents": 1000}, FRONTDESK), 201)
    entries, _ = validate_paginated(
        api.list_patient_ledger_entries(pid, BILLING, params={"entry_type": "PATIENT_PAYMENT"})
    )
    assert len(entries) == 1
    e = entries[0]
    assert e["entry_type"] == "PATIENT_PAYMENT"
    assert e["amount_cents"] == -1000
    assert "version" not in e
    assert "updated_at" not in e


# ===========================================================================
# Corner: entities / insurance_policy_parent_must_exist
# ===========================================================================
def test_insurance_policy_under_missing_patient(api):
    """PRD §2.6: "It first confirms the patient named by the leading path segment
    exists, rejecting with `ERR_PATIENT_NOT_FOUND` if it does not".

    Design: Corner/entities/insurance_policy_parent_must_exist
    """
    res = api.create_insurance_policy(
        NON_EXISTENT_UUID, create_insurance_policy_payload(annual_visit_cap=10), BILLING
    )
    validate_error(res, "ERR_PATIENT_NOT_FOUND")


# ===========================================================================
# Corner: validations / payer_mode_mismatch_wellness_without_plan
# ===========================================================================
def test_wellness_without_plan_rejected(api):
    """PRD §3.2: "a `WELLNESS` registration without a `wellness_plan_id`, or a
    `CASH`/`INSURANCE` registration that carries one, is rejected with
    `ERR_PAYER_MODE_MISMATCH`."

    Design: Corner/validations/payer_mode_mismatch_wellness_without_plan
    """
    res = api.create_patient(
        create_patient_payload(full_name="Well Wally", date_of_birth="1990-05-05", payer_mode="WELLNESS"),
        FRONTDESK,
    )
    validate_error(res, "ERR_PAYER_MODE_MISMATCH")


# ===========================================================================
# Corner: validations / payer_mode_mismatch_cash_with_plan
# ===========================================================================
def test_cash_with_wellness_plan_rejected(api):
    """PRD §3.2: "a `CASH`/`INSURANCE` registration that carries one, is rejected
    with `ERR_PAYER_MODE_MISMATCH`."

    Design: Corner/validations/payer_mode_mismatch_cash_with_plan
    """
    wp = create_wellness_plan()
    res = api.create_patient(
        create_patient_payload(
            full_name="Cash Cal", date_of_birth="1990-05-05", payer_mode="CASH", wellness_plan_id=wp["id"]
        ),
        FRONTDESK,
    )
    validate_error(res, "ERR_PAYER_MODE_MISMATCH")


# ===========================================================================
# Corner: validations / second_active_plan_rejected
# ===========================================================================
def test_second_active_plan_rejected(api):
    """PRD §3.3: "if the patient already holds an `ACTIVE` plan, it is rejected
    with `ERR_ACTIVE_PLAN_EXISTS`."

    Design: Corner/validations/second_active_plan_rejected
    """
    ctx = setup_active_plan(
        payer_mode="CASH",
        phases=[{"phase_type": "ACUTE", "sequence_index": 0, "visits_per_week": 3, "planned_visit_count": 2}],
    )
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    exam2 = create_finalized_exam(pid, prov_id, exam_type="RE_EXAM", severity_score=4)
    plan2 = propose_plan(pid, prov_id, exam2["id"])
    add_phase(pid, plan2["id"], prov_id, planned_visit_count=2)
    fresh = validate_success(api.get_patient(pid, make_provider_headers(prov_id)), 200)
    res = api.activate_plan(
        pid, plan2["id"], {"expected_patient_version": fresh["version"]}, make_provider_headers(prov_id)
    )
    validate_error(res, "ERR_ACTIVE_PLAN_EXISTS")


# ===========================================================================
# Corner: validations / plan_from_draft_exam_not_ready
# ===========================================================================
def test_plan_from_draft_exam_not_ready(api):
    """PRD §3.3: "Only a `FINALIZED` exam may justify a treatment plan."
    PRD §3.3: "If the referenced exam is not finalized, or activation is attempted
    with zero phases, the request is rejected with `ERR_PLAN_NOT_READY`".

    Design: Corner/validations/plan_from_draft_exam_not_ready
    """
    base = setup_base_practice()
    patient = create_cash_patient("Draft Dan")
    pid = patient["id"]
    prov_id = base["provider"]["id"]
    # DRAFT exam — never finalized.
    exam = validate_success(
        api.create_exam(pid, {"provider_id": prov_id, "exam_type": "INITIAL", "severity_score": 6}, make_provider_headers(prov_id)),
        201,
    )
    res = api.create_treatment_plan(pid, {"exam_record_id": exam["id"]}, make_provider_headers(prov_id))
    validate_error(res, "ERR_PLAN_NOT_READY")


# ===========================================================================
# Corner: validations / soap_provider_mismatch_rejected
# ===========================================================================
def test_soap_provider_mismatch_rejected(api):
    """PRD §3.7: "The note's author must match the appointment's provider, so a
    `provider_id` that differs from the appointment's `provider_id` is rejected
    with `ERR_SOAP_PROVIDER_MISMATCH`."

    Design: Corner/validations/soap_provider_mismatch_rejected
    """
    from test_helpers import create_provider

    base = setup_base_practice()
    p1 = base["provider"]["id"]
    p2 = create_provider(full_name="Dr Lin", npi="1234567891")["id"]
    patient = create_cash_patient("Soap Sue")
    pid = patient["id"]
    appt = book_appointment(pid, p1, base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z")
    validate_success(api.check_in(pid, appt["id"], FRONTDESK), 200)
    res = api.create_soap_note(pid, appt["id"], create_soap_note_payload(p2), make_provider_headers(p2))
    validate_error(res, "ERR_SOAP_PROVIDER_MISMATCH")


# ===========================================================================
# Corner: validations / regression_without_severity_rejected
# ===========================================================================
def test_regression_below_severity_rejected(api):
    """PRD §3.4: "when the referenced re-exam is a `FINALIZED` `RE_EXAM` whose
    `severity_score` is at least the regression severity threshold of 6; any other
    combination is rejected with `ERR_REGRESSION_NOT_ALLOWED`."

    A FINALIZED RE_EXAM with severity 3 (< 6) cannot drive a regression.

    Design: Corner/validations/regression_without_severity_rejected
    """
    ctx = setup_plan_with_corrective_in_progress(reexam_severity=3)
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    res = api.re_exam_regress(
        pid,
        ctx["plan"]["id"],
        {"exam_record_id": ctx["reexam"]["id"], "plan_phase_id": ctx["corrective_phase"]["id"]},
        make_provider_headers(prov_id),
    )
    validate_error(res, "ERR_REGRESSION_NOT_ALLOWED")


# ===========================================================================
# Corner: endpoints / fee_schedule_supersede_retires_prior
# ===========================================================================
def test_fee_schedule_supersede_retires_prior(api):
    """PRD §3.1: "creating a new fee schedule for a `visit_type` retires any prior
    `ACTIVE` schedule for the same `visit_type`, moving it to `RETIRED` while the
    new one becomes `ACTIVE`."

    Design: Corner/endpoints/fee_schedule_supersede_retires_prior
    """
    fs1 = validate_success(
        api.create_fee_schedule({"visit_type": "ADJUSTMENT", "cash_rate_cents": 5000, "billed_amount_cents": 8000}, ADMIN),
        201,
    )
    fs2 = validate_success(
        api.create_fee_schedule({"visit_type": "ADJUSTMENT", "cash_rate_cents": 6000, "billed_amount_cents": 9000}, ADMIN),
        201,
    )
    active, _ = validate_paginated(
        api.list_fee_schedules(ADMIN, params={"visit_type": "ADJUSTMENT", "status": "ACTIVE"})
    )
    assert len(active) == 1
    assert active[0]["id"] == fs2["id"]
    retired, _ = validate_paginated(
        api.list_fee_schedules(ADMIN, params={"visit_type": "ADJUSTMENT", "status": "RETIRED"})
    )
    assert any(f["id"] == fs1["id"] for f in retired)


# ===========================================================================
# Corner: endpoints / reference_not_found_provider_on_booking
# ===========================================================================
def test_reference_not_found_provider_on_booking(api):
    """PRD §2.6: "any foreign key supplied in a request body — a referenced
    provider, room, fee schedule, policy, wellness plan, exam, or phase — that
    does not resolve to an existing resource is rejected with
    `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/endpoints/reference_not_found_provider_on_booking
    """
    base = setup_base_practice()
    patient = create_cash_patient("Ref Ray")
    res = api.book_appointment(
        patient["id"],
        create_appointment_payload(NON_EXISTENT_UUID, base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z"),
        FRONTDESK,
    )
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")
