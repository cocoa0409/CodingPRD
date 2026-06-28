"""Entity creation, retrieval, listing, defaults, required fields, type constraints,
not-found, immutability, and parent-existence. Corner section: entities.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_member_headers,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_facility,
    create_lane,
    create_member,
    sign_waiver,
)

MANAGER = {"X-User-ID": "test-manager-1", "X-User-Role": "FacilityManager", "Content-Type": "application/json"}


# ─── entities corner: create_facility_returns_defaults_and_system_fields ───────

def test_create_facility_defaults_and_system_fields(api):
    """PRD §3.1: "A newly created facility opens with posture set to OPEN, epoch_index at
    0, and open_incident_count at 0." PRD §3.1: "a token_price_cents ... defaulting to 500".
    PRD §2.4: "a version integer that begins at 1".

    Design: Corner/entities/create_facility_returns_defaults_and_system_fields
    """
    res = api.create_facility({"name": "Fac"}, MANAGER)
    facility = validate_success(res, 201)
    assert facility["posture"] == "OPEN"
    assert facility["epoch_index"] == 0
    assert facility["token_price_cents"] == 500
    assert facility["version"] == 1


# ─── entities corner: get_lane_returns_stored_data ─────────────────────────────

def test_get_lane_returns_stored_data(api):
    """PRD §3.1: 'is described by a human label such as "Cage 1", a kind that is one of
    CAGE, TUNNEL, or LANE'. PRD §3.1: "A lane is born AVAILABLE in its maint_status."

    Design: Corner/entities/get_lane_returns_stored_data
    """
    facility = create_facility()
    lane = create_lane(facility["id"], kind="CAGE", label="Cage 1", buffer_minutes=0)
    res = api.get_lane(lane["id"], MANAGER)
    fetched = validate_success(res, 200)
    assert fetched["label"] == "Cage 1"
    assert fetched["maint_status"] == "AVAILABLE"


# ─── entities corner: list_members_paginated_envelope ──────────────────────────

def test_list_members_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the meta object
    of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_members_paginated_envelope
    """
    facility = create_facility()
    create_member(facility["id"], tier="NONE", full_name="A")
    create_member(facility["id"], tier="NONE", full_name="B")
    data, meta = validate_paginated(
        api.list_members(MANAGER, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ─── entities corner: get_member_nonexistent_returns_not_found ─────────────────

def test_get_member_nonexistent_returns_not_found(api):
    """PRD §2.9: "The first identifier that does not resolve produces ERR_NOT_FOUND".
    PRD §5: ERR_NOT_FOUND maps to 404.

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    create_facility()
    res = api.get_member(NON_EXISTENT_UUID, MANAGER)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ─── entities corner: create_lane_missing_kind_required_field ──────────────────

def test_create_lane_missing_kind_rejected(api):
    """PRD §3.1: "a kind that is one of CAGE, TUNNEL, or LANE". PRD §2.11: "a missing
    required field ... yields ERR_INVALID_REQUEST."

    Design: Corner/entities/create_lane_missing_kind_required_field
    """
    facility = create_facility()
    payload = {
        "facility_id": facility["id"], "label": "Cage 1", "kind": None, "buffer_minutes": 0
    }
    res = api.create_lane(payload, MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── entities corner: member_tier_defaults_to_none ─────────────────────────────

def test_member_tier_defaults_to_none(api):
    """PRD §3.1: "a membership tier that is one of NONE, BRONZE, or GOLD, defaulting to
    NONE". PRD §3.1: "A newly registered member starts with a token_balance of 0,
    no_show_strikes of 0, and waiver_ok false."

    Design: Corner/entities/member_tier_defaults_to_none
    """
    facility = create_facility()
    res = api.create_member(
        {"facility_id": facility["id"], "full_name": "Defaulty"}, MANAGER
    )
    member = validate_success(res, 201)
    assert member["tier"] == "NONE"
    assert member["token_balance"] == 0
    assert member["waiver_ok"] is False


# ─── entities corner: booking_invalid_kind_enum_rejected ───────────────────────

def test_booking_invalid_kind_enum_rejected(api):
    """PRD §3.4: "it is polymorphic over its kind, which is one of OPEN_SLOT, LESSON,
    TEAM_BLOCK, or PARTY". PRD §2.11: "a bad enum value ... yields ERR_INVALID_REQUEST."

    Design: Corner/entities/booking_invalid_kind_enum_rejected
    """
    facility = create_facility()
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")
    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "GOLF", "pay_mode": "HOURLY",
        "start_utc": "2026-04-02T09:00:00Z", "end_utc": "2026-04-02T10:00:00Z",
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── entities corner: waiver_immutable_no_version_field ────────────────────────

def test_waiver_is_immutable_signed_with_no_version(api):
    """PRD §2.4: "The Waiver resource is the sole exception: a waiver is immutable once
    written, so it carries only an id and a created_at timestamp. A Waiver has no
    updated_at field and no version field at all." PRD §3.2: "A waiver's status is SIGNED
    on creation".

    Design: Corner/entities/waiver_immutable_no_version_field
    """
    facility = create_facility()
    member = create_member(facility["id"], tier="NONE")
    waiver = sign_waiver(facility["id"], member["id"])
    data, _ = validate_paginated(
        api.list_waivers(make_member_headers(member["id"]))
    )
    assert data[0]["status"] == "SIGNED"
    assert data[0]["id"] == waiver["id"]
    assert "version" not in data[0]


# ─── entities corner: machine_requires_existing_lane_parent ────────────────────

def test_machine_requires_existing_lane(api):
    """PRD §2.9: "the server confirms each referenced resource exists within facility
    scope in path order. The first identifier that does not resolve produces ERR_NOT_FOUND".
    PRD §3.1: "a PitchingMachine is equipment installed on a single lane".

    Design: Corner/entities/machine_requires_existing_lane_parent
    """
    facility = create_facility()
    payload = {
        "facility_id": facility["id"], "lane_id": NON_EXISTENT_UUID, "model": "WHEEL"
    }
    res = api.create_machine(payload, MANAGER)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
