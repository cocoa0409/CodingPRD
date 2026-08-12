"""Corner coverage: validation pipeline — auth headers, existence, ownership,
posture gate, and aggregate month/window checks."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, get_success_data,
    NON_EXISTENT_UUID,
    create_program, create_patient, create_draft_order,
    create_active_home_patient, create_approved_order,
    create_machine, assign_machine, record_and_sign_all_modules,
    create_accepted_assessment, create_active_plan,
    api_client, make_admin_headers, make_nurse_headers,
    make_patient_headers, make_coordinator_headers,
    make_nephrologist_headers,
    create_supply_order_payload,
)


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the capacity in
    which they act. A request in which either header is missing or empty is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    # Call with no auth headers at all (Content-Type only is also absent).
    resp = api._request("POST", "/api/dialysis-programs",
                        {"name": "HD Program Z", "review_cadence_treatments": 2,
                         "max_missed_log_streak": 3,
                         "waste_ratio_alert_threshold": 0.1,
                         "supply_catalog": []},
                        headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_order_submit_unknown_id_returns_not_found(api):
    """PRD §2.7: "Requests that target nested resources validate path
    identifiers strictly from left to right. The request is rejected
    immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier in
    the path that does not correspond to an existing resource; the system does
    not evaluate later identifiers or business rules once an earlier segment
    has failed."

    Design: Corner/validations/order_submit_unknown_id_returns_not_found
    """
    resp = api.submit_supply_order(NON_EXISTENT_UUID,
                                   make_patient_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_order_create_unknown_patient_returns_not_found(api):
    """PRD §2.7: "The same `ERR_NOT_FOUND` rejection applies to foreign-key
    references supplied in a request body — for example, a payload naming a
    `patient_id`, `machine_id`, `supply_order_id`, `chair_id`,
    `assessment_id`, `backup_machine_id`, or `reversal_of_id` that does not
    exist."

    Design: Corner/validations/order_create_unknown_patient_returns_not_found
    """
    program = create_program()
    resp = api.create_supply_order(
        create_supply_order_payload(NON_EXISTENT_UUID, "2026-05",
                                    [{"sku": "DIALYSATE_2L", "quantity": 2}],
                                    expected_patient_version=1),
        make_patient_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_ownership_foreign_order_submit_returns_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of
    the acting Patient; ownership checks on any resource that references a
    Patient compare the resource's foreign-key field to `X-User-ID`. A
    Patient-role caller may therefore only create or act upon their own records
    — their own supply orders (create, line edits, submit, cancel), their own
    treatment logs (create, amend), their own backup slot reservations (book,
    cancel), their own waste and return reports, and their own transition
    requests. Any Patient-role write whose target belongs to a different
    patient is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/validations/ownership_foreign_order_submit_returns_forbidden
    """
    program = create_program()
    pat_a = create_patient(program["id"], full_name="Pat A")
    pat_b = create_patient(program["id"], full_name="Pat B")
    order = create_draft_order(pat_a["id"], "2026-05",
                               [{"sku": "DIALYSATE_2L", "quantity": 2}])
    # Patient B attempts to submit patient A's order.
    resp = api.submit_supply_order(order["id"], make_patient_headers(pat_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_submit_while_training_returns_posture_error(api):
    """PRD §3.5: "Submission runs a gate ladder in a pinned order, and the
    state check outranks every business check: the order must be `DRAFT` or
    `CHANGES_REQUESTED` (`ERR_ORDER_INVALID_STATE`); the month must not be in
    the past (`ERR_ORDER_MONTH_IN_PAST`); the patient's posture must be
    `HOME_READY` or `AT_RISK` (`ERR_POSTURE_NOT_ORDERABLE`);"

    Design: Corner/validations/submit_while_training_returns_posture_error
    """
    program = create_program()
    patient = create_patient(program["id"])
    pat = patient["id"]
    order = create_draft_order(pat, "2026-05",
                               [{"sku": "DIALYSATE_2L", "quantity": 2}])
    resp = api.submit_supply_order(order["id"], make_patient_headers(pat))
    validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_ORDERABLE)
    assert order["order_status"] == "DRAFT"
    after = get_success_data(api.get_supply_order(order["id"],
                                                  make_admin_headers("admin-1")))
    assert after["order_status"] == "DRAFT", "no state change on rejection"


def test_month_order_exists_and_bad_window_battery(api):
    """PRD §3.5: "Creation is a create-with-supersede: if a `DRAFT` order
    already exists for the same patient and month, it becomes `SUPERSEDED`; but
    if an order for that patient and month exists in `SUBMITTED`, `APPROVED`,
    or `CLOSED`, creation is rejected outright with `ERR_MONTH_ORDER_EXISTS`."
    PRD §3.5: "A `SupplyCoordinator` schedules a DeliveryAppointment with
    `supply_order_id`, `window_start`, and `window_end`; the order must be
    `APPROVED` (`ERR_ORDER_INVALID_STATE`), at most one appointment per order
    may be `SCHEDULED` at a time (`ERR_ACTIVE_APPOINTMENT_EXISTS`), the
    `window_start` must not be in the past and its calendar date must fall
    inside the order month (`ERR_APPOINTMENT_OUTSIDE_ORDER_MONTH`), and the
    window must run at least 120 and at most 720 minutes with the end after
    the start (`ERR_INVALID_REQUEST`)."

    Design: Corner/validations/month_order_exists_and_bad_window_battery
    """
    ctx = create_active_home_patient()
    pat = ctx["patient"]["id"]
    order = create_approved_order(pat, "2026-05",
                                  [{"sku": "DIALYSATE_2L", "quantity": 10}])
    # Second create for the same month while the first is APPROVED.
    pat_doc = api.get_patient(pat, make_admin_headers("admin-1")).json()["data"]
    resp = api.create_supply_order(
        create_supply_order_payload(pat, "2026-05",
                                    [{"sku": "DIALYSATE_2L", "quantity": 4}],
                                    expected_patient_version=pat_doc["version"]),
        make_patient_headers(pat))
    validate_error(resp, ApiErrorId.ERR_MONTH_ORDER_EXISTS)
    # Backwards appointment window (end before start).
    resp = api.create_delivery_appointment(
        {"supply_order_id": order["id"],
         "window_start": "2026-05-06T12:00:00Z",
         "window_end": "2026-05-06T08:00:00Z"},
        make_coordinator_headers("coord-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_activate_gate_ladder_enforced_in_order(api):
    """PRD §3.1: "Activation moves a patient from `TRAINING` to `ACTIVE_HOME`
    and is performed by a `Nephrologist`. Four readiness gates are checked in a
    fixed order, and the first failure is what the caller sees: training
    certification first (every `module_code` must have a `SIGNED_OFF` passing
    attempt whose `signed_off_at` is strictly more recent than 365 days ago,
    else `ERR_TRAINING_INCOMPLETE`), then assessment currency (the latest
    `ACCEPTED` assessment must have `accepted_at` strictly more recent than 730
    days ago, else `ERR_ASSESSMENT_NOT_CURRENT`), then machine assignment (a
    machine with status `ASSIGNED` and `assigned_patient_id` naming this
    patient must exist, else `ERR_NO_MACHINE_ASSIGNED`), and finally the
    emergency plan (an EmergencyBackupPlan in `ACTIVE` must exist, else
    `ERR_NO_ACTIVE_PLAN`)."

    Design: Corner/validations/activate_gate_ladder_enforced_in_order
    """
    program = create_program()
    patient = create_patient(program["id"])
    pat = patient["id"]
    nephro = make_nephrologist_headers("nephro-1")
    resp = api.activate_patient(pat, nephro)
    validate_error(resp, ApiErrorId.ERR_TRAINING_INCOMPLETE)
    record_and_sign_all_modules(pat)
    resp = api.activate_patient(pat, nephro)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_CURRENT)
    create_accepted_assessment(pat)
    resp = api.activate_patient(pat, nephro)
    validate_error(resp, ApiErrorId.ERR_NO_MACHINE_ASSIGNED)
    mach = create_machine(program["id"])
    assign_machine(mach["id"], pat)
    resp = api.activate_patient(pat, nephro)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PLAN)
    create_active_plan(pat)
    activated = validate_success(api.activate_patient(pat, nephro))
    assert activated["program_status"] == "ACTIVE_HOME"
    assert activated["ever_home_ready"] is True


def test_log_create_while_training_returns_not_active_home(api):
    """PRD §3.6: "Day-to-day care produces the TreatmentLog. A patient — who
    must be `ACTIVE_HOME` (`ERR_PATIENT_NOT_ACTIVE_HOME`) — submits a log with
    `patient_id`, `machine_id`, `treatment_date`, `duration_minutes`, and
    `consumption`."

    Design: Corner/validations/log_create_while_training_returns_not_active_home
    """
    program = create_program()
    patient = create_patient(program["id"])
    pat = patient["id"]
    mach = create_machine(program["id"])
    assign_machine(mach["id"], pat)
    resp = api.create_treatment_log(
        {"patient_id": pat, "machine_id": mach["id"],
         "treatment_date": "2026-05-01", "duration_minutes": 240,
         "consumption": []},
        make_patient_headers(pat))
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_ACTIVE_HOME)
