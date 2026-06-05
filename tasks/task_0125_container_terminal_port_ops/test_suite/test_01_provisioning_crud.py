"""Provisioning, CRUD, defaults, type constraints, listing, FK integrity.

Translates the entities-section corner instances. Every test builds its own
state from scratch (the harness restarts the server before each test).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    BOGUS_UUID,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx
import test_helpers.api_client as ac

ADMIN = TEST_USERS["terminal_admin_headers"]
YARD = TEST_USERS["yard_planner_headers"]


def test_create_berth_returns_201_with_defaults(api):
    """PRD §3.1: "A berth also carries an operational `status` that is `AVAILABLE`
    by default and may also be `CLOSED`".
    PRD §2.5: "The `version` is an integer that starts at its initial value on
    creation and increments by one on every mutation of the resource".

    Design: Corner/entities/create_berth_returns_201_with_all_fields
    """
    resp = api.create_berth({"code": "B-100", "length_m": 350, "draft_m": 15.5}, ADMIN)
    data = validate_success(resp, 201)
    assert data["code"] == "B-100"
    assert data["length_m"] == 350
    assert data["status"] == "AVAILABLE"
    assert data["version"] == 1


def test_get_vessel_returns_stored_data(api):
    """PRD §3.1: "A **vessel** is registered with a seven-digit `imo_number`
    (unique across vessels and consisting of exactly seven digits), a non-empty
    `name`, a length overall `loa_m` ..., a laden `draft_m` ..., and a contracted
    demurrage `free_time_days`".

    Design: Corner/entities/get_vessel_returns_stored_data
    """
    created = fx.provision_vessel(
        imo_number="2000001", name="Get Me", loa_m=280, draft_m=13.0, free_time_days=7
    )
    data = validate_success(api.get_vessel(created["id"], ADMIN), 200)
    assert data["imo_number"] == "2000001"
    assert data["free_time_days"] == 7


def test_list_berths_paginated_envelope(api):
    """PRD §2.3: "Each list response carries the pagination bookkeeping inside the
    envelope's `meta` object, specifically the `limit`, `offset`, `total_count`,
    and `has_more` fields."

    Design: Corner/entities/list_berths_paginated_envelope
    """
    fx.provision_berth(code="B-201", length_m=300, draft_m=14.0)
    fx.provision_berth(code="B-202", length_m=300, draft_m=14.0)
    data, meta = validate_paginated(api.list_berths(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_container_not_found_returns_404(api):
    """PRD §2.8: "the first path identifier that names no existing resource yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_container_not_found_returns_404
    """
    resp = api.get_container("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_container_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "the system validates the **shape** of the request body: required
    fields must be present, enum-valued fields must carry one of their permitted
    values, and types must be correct. A malformed body yields `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/create_container_missing_required_field_returns_invalid_request
    """
    _, vessel, window = fx.provision_berthed_window()
    # omit container_number
    resp = api.create_container(
        {"vessel_id": vessel["id"], "berth_window_id": window["id"]}, YARD
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_container_defaults_is_reefer_false_pending_on_vessel(api):
    """PRD §3.3: "A container declares whether it `is_reefer` (a refrigerated unit,
    defaulting to false)".
    PRD §3.3: "The physical `handling_status` begins at `ON_VESSEL` and proceeds to
    `GROUNDED` and then to the terminal `GATED_OUT`."
    PRD §3.3: "The regulatory `customs_status` begins at `PENDING` and resolves to
    either `HELD` or `CLEARED`."

    Design: Corner/entities/container_default_is_reefer_false_and_pending_pending
    """
    _, vessel, window = fx.provision_berthed_window()
    data = validate_success(
        api.create_container(
            {
                "container_number": "DEFL220220",
                "vessel_id": vessel["id"],
                "berth_window_id": window["id"],
            },
            YARD,
        ),
        201,
    )
    assert data["is_reefer"] is False
    assert data["customs_status"] == "PENDING"
    assert data["handling_status"] == "ON_VESSEL"


def test_container_system_fields_input_ignored(api):
    """PRD §3.3: "The physical `handling_status` begins at `ON_VESSEL`".
    PRD §3.3: "A container also tracks the `yard_slot_id` it currently occupies
    (null until grounded and cleared again on gate-out)".

    Design: Corner/entities/container_system_fields_input_ignored
    """
    _, vessel, window = fx.provision_berthed_window()
    data = validate_success(
        api.create_container(
            {
                "container_number": "SYSF230230",
                "vessel_id": vessel["id"],
                "berth_window_id": window["id"],
                "handling_status": "GATED_OUT",
                "yard_slot_id": BOGUS_UUID,
            },
            YARD,
        ),
        201,
    )
    assert data["handling_status"] == "ON_VESSEL"
    assert data["yard_slot_id"] is None


def test_vessel_invalid_imo_number_rejected(api):
    """PRD §2.8: "an `imo_number` must be exactly seven digits". This is one of the
    shape failures yielding `ERR_INVALID_REQUEST` (HTTP 422).

    Design: Corner/entities/vessel_invalid_imo_number_rejected
    """
    resp = api.create_vessel(
        {"imo_number": "123456", "name": "Bad IMO", "loa_m": 280, "draft_m": 13.0}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_reefer_setpoint_required_when_is_reefer_true(api):
    """PRD §2.8: "`setpoint_c` must be present when and only when `is_reefer` is
    true". A mismatch is a shape failure yielding `ERR_INVALID_REQUEST` (HTTP 422).

    Design: Corner/entities/reefer_setpoint_required_when_is_reefer_true
    """
    _, vessel, window = fx.provision_berthed_window()
    resp = api.create_container(
        {
            "container_number": "RFRQ240240",
            "vessel_id": vessel["id"],
            "berth_window_id": window["id"],
            "is_reefer": True,
        },
        YARD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_gate_appointment_window_not_60_min_rejected(api):
    """PRD §2.8: "a gate appointment's `window_end` must be exactly sixty minutes
    after its `window_start`". A mismatch yields `ERR_INVALID_REQUEST` (HTTP 422).

    Design: Corner/entities/gate_appointment_window_not_60_min_rejected
    """
    _, _, container, _ = fx.setup_grounded_cleared_container()
    resp = api.create_gate_appointment(
        {
            "container_id": container["id"],
            "truck_plate": "TRK-250",
            "window_start": "2026-03-01T10:00:00.000Z",
            "window_end": "2026-03-01T11:30:00.000Z",
        },
        TEST_USERS["gate_operator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_reefer_reading_is_append_only_no_version(api):
    """PRD §2.5: "Two resource types are append-only audit records ... and therefore
    carry **only** `id` and `created_at` — they have neither `updated_at` nor
    `version`: the **reefer reading** and the **equipment interchange receipt**."

    Design: Corner/entities/reefer_reading_immutable_no_version_field
    """
    container = fx.setup_reefer_container(setpoint_c=-18.0)
    data = validate_success(
        api.record_reefer_reading(
            container["id"],
            {"recorded_at": "2026-02-01T01:00:00.000Z", "temperature_c": -18.0},
            TEST_USERS["reefer_technician_headers"],
        ),
        201,
    )
    assert "id" in data and data["id"]
    assert "version" not in data
    assert "updated_at" not in data


def test_container_fk_vessel_not_found(api):
    """PRD §2.8: "It then validates that **every foreign key carried in the request
    body** — among them `vessel_id`, `berth_id`, `container_id`, `yard_slot_id`,
    `berth_window_id`, and `gate_appointment_id` — points to a resource that exists;
    an unresolved body reference yields `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/container_fk_vessel_not_found
    """
    _, _, window = fx.provision_berthed_window()
    resp = api.create_container(
        {
            "container_number": "FKNF270270",
            "vessel_id": "00000000-0000-4000-8000-000000000099",
            "berth_window_id": window["id"],
        },
        YARD,
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_yard_slot_below_fk_validated(api):
    """PRD §2.8: "It then validates that **every foreign key carried in the request
    body** ... points to a resource that exists; an unresolved body reference yields
    `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/flat_topology_yard_slot_below_fk_validated
    """
    resp = api.create_yard_slot(
        {
            "block": "Z",
            "bay": 1,
            "row": 1,
            "tier": 2,
            "below_slot_id": "00000000-0000-4000-8000-0000000000aa",
        },
        YARD,
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)
