"""Corner coverage: entity creation/defaults/computed fields, not-found,
listing, uniqueness, and the response envelope."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    NON_EXISTENT_UUID, is_valid_uuid, is_iso8601_timestamp,
    create_program, create_patient, get_patient, create_machine,
    create_draft_order,
    api_client, make_admin_headers, make_nurse_headers, make_biomed_headers,
    make_patient_headers, create_program_payload, create_patient_payload,
    create_training_attempt_payload,
)
from test_helpers.assertions import (
    assert_envelope_success, assert_envelope_error,
)


def test_program_creation_stores_config_and_catalog(api):
    """PRD §3.1: "A `ProgramAdmin` creates a DialysisProgram with a display
    `name` and three policy knobs: `review_cadence_treatments` (an integer of
    at least 1 — the unreviewed-log count at which the system auto-opens a
    cadence ClinicalReview, §3.6), `max_missed_log_streak` (an integer of at
    least 1 — the missed-log streak that pushes a patient toward `AT_RISK`,
    §3.6), and `waste_ratio_alert_threshold` (greater than 0 and at most 1 —
    the monthly waste ratio at which the waste alert latches, §3.8)."
    PRD §2.4: "`version` (integer): a system-managed integer that increments
    by one on every mutation of the resource, including mutations driven by
    cascades and derived-field recomputation."

    Design: Corner/entities/program_creation_stores_config_and_catalog
    """
    payload = create_program_payload(
        name="HD Program Z", review_cadence_treatments=4,
        max_missed_log_streak=2, waste_ratio_alert_threshold=0.2)
    resp = api.create_program(payload, make_admin_headers("admin-1"))
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert data["version"] == 1
    assert data["review_cadence_treatments"] == 4
    assert data["max_missed_log_streak"] == 2
    assert data["waste_ratio_alert_threshold"] == 0.2
    skus = {entry["sku"]: entry for entry in data["supply_catalog"]}
    assert "DIALYSATE_2L" in skus
    assert skus["DIALYSATE_2L"]["unit_price_cents"] == 1200


def test_program_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: "A `ProgramAdmin` creates a DialysisProgram with a display
    `name` and three policy knobs: `review_cadence_treatments` (an integer of
    at least 1 — the unreviewed-log count at which the system auto-opens a
    cadence ClinicalReview, §3.6), `max_missed_log_streak` (an integer of at
    least 1 — the missed-log streak that pushes a patient toward `AT_RISK`,
    §3.6), and `waste_ratio_alert_threshold` (greater than 0 and at most 1 —
    the monthly waste ratio at which the waste alert latches, §3.8)."

    Design: Corner/entities/program_missing_required_field_returns_invalid_request
    """
    resp = api.create_program(
        {"name": "HD Program Z", "review_cadence_treatments": 4,
         "max_missed_log_streak": 2, "supply_catalog": []},
        make_admin_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_patient_creation_applies_defaults_and_initial_state(api):
    """PRD §3.1: "A new patient starts with `program_status` `TRAINING` and
    posture `NOT_READY`; the latches `ever_home_ready`, `retraining_required`,
    and `waste_alert_active` all start false, `no_show_count` starts at 0,
    `storage_cap_units` is 0 until an assessment is accepted, and
    `on_hand_units` and `missed_log_streak` are derived continuously per §3.5
    and §3.6."

    Design: Corner/entities/patient_creation_applies_defaults_and_initial_state
    """
    program = create_program()
    resp = api.create_patient(create_patient_payload(program["id"]),
                              make_nurse_headers("nurse-1"))
    data = validate_success(resp, 201)
    assert data["program_status"] == "TRAINING"
    assert data["posture"] == "NOT_READY"
    assert data["storage_cap_units"] == 0
    assert data["on_hand_units"] == 0
    assert data["ever_home_ready"] is False
    assert data["missed_log_streak"] == 0
    assert data["no_show_count"] == 0


def test_patient_computed_posture_input_ignored(api):
    """PRD §2.10: "Posture is never stored as an input; it is re-evaluated on
    every read of the patient and after every mutation that touches one of its
    inputs — training sign-off, assessment acceptance, machine assignment or
    unassignment, maintenance start or completion, plan creation, drill, or
    lazy expiry, review sign-off or escalation, waste verification, log
    creation, and clock-driven lazy evaluation."

    Design: Corner/entities/patient_computed_posture_input_ignored
    """
    program = create_program()
    payload = create_patient_payload(program["id"])
    payload["posture"] = "HOME_READY"
    resp = api.create_patient(payload, make_nurse_headers("nurse-1"))
    data = validate_success(resp, 201)
    assert data["posture"] == "NOT_READY", (
        "server-computed posture; client input ignored")


def test_patient_not_found_returns_404(api):
    """PRD §2.7: "Requests that target nested resources validate path
    identifiers strictly from left to right. The request is rejected
    immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier in
    the path that does not correspond to an existing resource; the system does
    not evaluate later identifiers or business rules once an earlier segment
    has failed."

    Design: Corner/entities/patient_not_found_returns_404
    """
    resp = api.get_patient(NON_EXISTENT_UUID, make_admin_headers("admin-1"))
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert err.get("message"), "error message non-empty"


def test_fk_reverse_lists_return_children(api):
    """PRD §3.2: "A patient's attempts are listable with optional `module_code`
    and `status` filters."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns its rows
    sorted by `created_at` in ascending order, and pagination slices that
    deterministic order. Paginated list responses carry the fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    response envelope."

    Design: Corner/entities/fk_reverse_lists_return_children
    """
    program = create_program()
    patient = create_patient(program["id"])
    api.create_training_attempt(
        create_training_attempt_payload(patient["id"], "WATER_HANDLING",
                                        score_pct=90),
        make_nurse_headers("nurse-1"))
    api.create_training_attempt(
        create_training_attempt_payload(patient["id"], "MACHINE_OPERATION",
                                        score_pct=88),
        make_nurse_headers("nurse-1"))
    resp = api.list_patient_training_attempts(patient["id"],
                                              make_admin_headers("admin-1"))
    rows, meta = validate_paginated(resp)
    assert len(rows) == 2
    assert rows[0]["module_code"] == "WATER_HANDLING"
    assert rows[1]["module_code"] == "MACHINE_OPERATION"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_duplicate_serial_number_returns_conflict(api):
    """PRD §3.4: "A `BiomedTechnician` registers each dialysis machine with
    `program_id`, `serial_number` (unique within its program — a duplicate is
    `ERR_SERIAL_NUMBER_EXISTS`), and `model`; a new machine is `IN_STOCK` and
    unassigned (`assigned_patient_id` null)."

    Design: Corner/entities/duplicate_serial_number_returns_conflict
    """
    prog1 = create_program(name="HD Program Z1")
    prog2 = create_program(name="HD Program Z2")
    create_machine(prog1["id"], serial_number="SN-DUP")
    resp = api.create_machine(
        {"program_id": prog1["id"], "serial_number": "SN-DUP",
         "model": "HomeX"},
        make_biomed_headers("biomed-1"))
    validate_error(resp, ApiErrorId.ERR_SERIAL_NUMBER_EXISTS)
    # Uniqueness is program-scoped: the same serial in another program works.
    resp = api.create_machine(
        {"program_id": prog2["id"], "serial_number": "SN-DUP",
         "model": "HomeX"},
        make_biomed_headers("biomed-1"))
    validate_success(resp, 201)


def test_response_envelope_success_and_error_shapes(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/response_envelope_success_and_error_shapes
    """
    resp = api.create_program(create_program_payload(name="HD Program Z"),
                              make_admin_headers("admin-1"))
    ok = resp.json()
    assert_envelope_success(ok)
    assert ok["response_type"] == "object"
    assert ok["data"].get("id")
    err_resp = api.get_patient(NON_EXISTENT_UUID, make_admin_headers("admin-1"))
    body = err_resp.json()
    assert_envelope_error(body)
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"


def test_order_list_filter_and_pagination(api):
    """PRD §3.5: "Appointments are listable per order with a `status` filter,
    and orders are listable per patient with `order_month` and `order_status`
    filters."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns its rows
    sorted by `created_at` in ascending order, and pagination slices that
    deterministic order."

    Design: Corner/endpoints/order_list_filter_and_pagination
    """
    program = create_program()
    patient = create_patient(program["id"])
    pat = patient["id"]
    # TRAINING patient: create does not gate on posture (submit does).
    ord_a = create_draft_order(pat, "2026-05",
                               [{"sku": "DIALYSATE_2L", "quantity": 2}])
    ord_b = create_draft_order(pat, "2026-06",
                               [{"sku": "DIALYSATE_2L", "quantity": 3}])
    validate_success(api.cancel_supply_order(ord_a["id"],
                                             make_patient_headers(pat)))
    rows, meta = validate_paginated(api.list_patient_supply_orders(
        pat, make_admin_headers("admin-1")))
    assert meta["total_count"] == 2
    assert [r["id"] for r in rows] == [ord_a["id"], ord_b["id"]], (
        "created_at ASC")
    filtered, fmeta = validate_paginated(api.list_patient_supply_orders(
        pat, make_admin_headers("admin-1"), params={"order_status": "CANCELLED"}))
    assert len(filtered) == 1 and filtered[0]["id"] == ord_a["id"]
    page, pmeta = validate_paginated(api.list_patient_supply_orders(
        pat, make_admin_headers("admin-1"), params={"limit": 1, "offset": 0}))
    assert len(page) == 1 and page[0]["id"] == ord_a["id"]
    assert pmeta["has_more"] is True
