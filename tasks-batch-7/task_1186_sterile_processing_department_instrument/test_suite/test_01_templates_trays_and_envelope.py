"""Template/tray/instrument/technician registration, response envelope, and
list pagination — the CRUD baseline corner claims.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_tray,
    is_valid_uuid,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]
SCHED = TEST_USERS["or_scheduler_headers"]


def test_template_create_persists_fields_and_system_columns(api):
    """PRD §2.5: "a unique, server-minted identifier formatted as a UUID, with
    no type prefix" and "initialized to 1 at creation and incremented by 1 on
    every mutation". PRD §2.4: "At startup, before any adjustment, the logical
    clock reads exactly `2026-05-01T00:00:00Z`."

    Design: Corner/entities/template_create_persists_fields_and_system_columns
    """
    resp = api.create_tray_template(f.create_tray_template_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"]), "template id must be a bare UUID"
    assert data["version"] == 1, f"version must initialize to 1, got {data['version']}"
    assert_instant_equals(data["created_at"], "2026-05-01T00:00:00Z",
                          "created_at must follow the logical clock default")
    got = validate_success(api.get_tray_template(data["id"], ADMIN), 200)
    assert got["code"] == "GEN-01"
    assert got["packaging_type"] == "WRAPPED"
    assert got["instrument_requirements"] == [
        {"instrument_type": "SCALPEL", "quantity": 2}
    ]


def test_tray_create_initial_state_and_defaults(api):
    """PRD §3.2: "A new tray begins its life `AWAITING_DECONTAMINATION`, with
    `current_load_id` null, `cycles_completed` at 0, `quarantine_reason` null,
    and `sterility_expires_at` null."

    Design: Corner/entities/tray_create_initial_state_and_defaults
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    resp = api.create_tray(
        f.create_tray_payload(tpl["id"], label="N1"),
        make_technician_headers(tech["id"]),
    )
    data = validate_success(resp, 201)
    assert_tray(data)
    assert data["status"] == "AWAITING_DECONTAMINATION"
    assert data["cycles_completed"] == 0
    assert data["sterility_expires_at"] is None
    assert data["current_load_id"] is None
    assert data["quarantine_reason"] is None


def test_tray_get_not_found_returns_404(api):
    """PRD §2.8: "the system validates existence in a strict left-to-right
    order and rejects the request with `ERR_NOT_FOUND` (404) at the *first*
    identifier that does not correspond to an existing resource."

    Design: Corner/entities/tray_get_not_found_returns_404
    """
    resp = api.get_tray(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_tray_create_missing_required_returns_invalid_request(api):
    """PRD §2.6: "Required fields are present, types are valid, enum values
    fall inside their declared sets, justification strings are at least 20
    characters, and body foreign-key references (`tray_id`, `case_id`,
    `instrument_id`, `sterilizer_id`, `template_id`) resolve to existing rows
    — otherwise one of `ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM_VALUE`, or
    `ERR_JUSTIFICATION_TOO_SHORT` (all 400)."

    Design: Corner/entities/tray_create_missing_required_returns_invalid_request
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    resp = api.create_tray({"template_id": tpl["id"]}, make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    # No tray was created as a side effect of the rejection.
    rows, meta = validate_paginated(api.list_trays(ADMIN))
    assert meta["total_count"] == 0, f"rejected create must not persist a tray: {rows}"


def test_instrument_create_duplicate_serial_rejected(api):
    """PRD §3.3: "a unique `serial_number` (duplicates rejected with
    `ERR_DUPLICATE_SERIAL_NUMBER`)".

    Design: Corner/entities/instrument_create_duplicate_serial_rejected
    """
    fx.create_instrument(api, serial_number="SN-D1", max_cycles=50,
                         replacement_cost_cents=100000, criticality="ROUTINE")
    resp = api.create_instrument(
        f.create_instrument_payload(serial_number="SN-D1", max_cycles=40,
                                    replacement_cost_cents=90000,
                                    criticality="CRITICAL"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL_NUMBER)


def test_template_create_invalid_packaging_enum_rejected(api):
    """PRD §3.1: "a `packaging_type` of either `WRAPPED` or `RIGID_CONTAINER`";
    PRD §2.6: "enum values fall inside their declared sets ... otherwise one of
    `ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM_VALUE`, or
    `ERR_JUSTIFICATION_TOO_SHORT` (all 400)".

    Design: Corner/entities/template_create_invalid_packaging_enum_rejected
    """
    resp = api.create_tray_template(
        f.create_tray_template_payload(packaging_type="FOAM"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM_VALUE)


def test_tray_create_with_unknown_template_rejected(api):
    """PRD §2.6: "body foreign-key references (`tray_id`, `case_id`,
    `instrument_id`, `sterilizer_id`, `template_id`) resolve to existing rows
    — otherwise one of `ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM_VALUE`, or
    `ERR_JUSTIFICATION_TOO_SHORT` (all 400)".

    Design: Corner/entities/tray_create_with_unknown_template_rejected
    """
    tech = fx.create_technician(api)
    resp = api.create_tray(
        f.create_tray_payload(NON_EXISTENT_UUID, label="X1"),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_technician_create_defaults_active_with_full_scores(api):
    """PRD §3.8: "New technicians are `ACTIVE` with both `competency_score`
    and `competency_score_lifetime` at 100."

    Design: Corner/entities/technician_create_defaults_active_with_full_scores
    """
    resp = api.create_technician(
        f.create_technician_payload(name="Tech A", certification_level=1), ADMIN
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["competency_score"] == 100
    assert data["competency_score_lifetime"] == 100


def test_template_create_duplicate_code_rejected(api):
    """PRD §3.1: "A `FacilityAdmin` registers a template with a unique `code`
    (a second registration of the same code is rejected with
    `ERR_DUPLICATE_TEMPLATE_CODE`)".

    Design: Corner/errors/error_duplicate_template_code_trigger
    """
    fx.create_template(api, code="GEN-01")
    resp = api.create_tray_template(
        f.create_tray_template_payload(
            code="GEN-01", name="General Dup", packaging_type="RIGID_CONTAINER",
            instrument_requirements=[{"instrument_type": "FORCEPS", "quantity": 1}],
            assembly_minutes=5,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TEMPLATE_CODE)


def test_response_envelope_shape_on_success_and_error(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources." and "The `error_id` is a unique,
    machine-readable string that identifies the specific error."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    resp = api.create_technician(f.create_technician_payload(certification_level=1), ADMIN)
    body = resp.json()
    assert resp.status_code == 201
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object"
    assert body["data"]["name"] == "Tech A"

    err_resp = api.get_tray(NON_EXISTENT_UUID, ADMIN)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND)


def test_tray_list_pagination_and_status_filter(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    response envelope." PRD §3.2: "Trays can be listed with filters on
    `template_id`, `current_load_id`, and `status`".

    Design: Corner/entities/tray_list_pagination_and_status_filter
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    for label in ("L1", "L2", "L3"):
        fx.create_tray(api, tpl["id"], tech["id"], label=label)

    page1, meta1 = validate_paginated(
        api.list_trays(ADMIN, params={"template_id": tpl["id"], "limit": 2})
    )
    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_trays(ADMIN, params={"template_id": tpl["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False

    sterile, meta3 = validate_paginated(api.list_trays(ADMIN, params={"status": "STERILE"}))
    assert sterile == [] and meta3["total_count"] == 0
