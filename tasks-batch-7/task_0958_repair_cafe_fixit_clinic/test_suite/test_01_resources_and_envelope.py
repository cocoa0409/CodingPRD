"""Resource creation defaults, envelope shape, not-found errors, list filtering
and pagination (PRD §2.2, §2.3, §2.6, §3.1, §3.2, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    TEST_USERS, ApiErrorId,
    assert_repair_event, assert_station, assert_repair_item,
    create_repair_event_payload, create_station_payload,
    create_repair_item_payload,
    set_logical_clock, create_event, create_station, register_fixer, add_skill,
    register_visitor, sign_waiver, setup_intake_open_event,
)

COORD = TEST_USERS["coordinator_headers"]
INTAKE = TEST_USERS["intake_volunteer_headers"]


def test_event_creation_required_fields_and_computed_defaults(api):
    """PRD §3.1: "New events are born in `DRAFT` status; the full lifecycle runs
    `DRAFT → PUBLISHED → INTAKE_OPEN → REPAIR_ACTIVE → CLOSED → REPORTED`, with
    `CANCELLED` reachable from any non-terminal state."
    PRD §2.9: "An event is `ACCEPTING` if and only if all three conditions hold:
    its `status` is `INTAKE_OPEN`, at least one of its stations is `OPEN`, and no
    `SafetyIncident` of severity `CRITICAL` in status `REPORTED` exists for that
    event. Otherwise the posture is `RESTRICTED`."
    PRD §2.5: "Malformed payloads — a missing required field, an invalid enum
    value, an out-of-range scalar, or an end timestamp that does not come after
    its start — are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/event_creation_required_fields_and_computed_defaults
    """
    set_logical_clock()

    # Missing required field `name` -> ERR_VALIDATION
    bad = create_repair_event_payload()
    del bad["name"]
    res = api.create_repair_event(bad, COORD)
    validate_error(res, ApiErrorId.ERR_VALIDATION)

    event = validate_success(api.create_repair_event(
        create_repair_event_payload(name="Cafe Tau"), COORD), 201)
    assert_repair_event(event)
    assert event["status"] == "DRAFT", "new events are born in DRAFT"
    # DRAFT is not INTAKE_OPEN, so posture cannot be ACCEPTING.
    assert event["posture"] == "RESTRICTED"
    assert event["active_item_count"] == 0
    # Version is a server-managed integer anchoring OCC (PRD §2.7); a publish
    # (a mutation) must increment it by exactly 1.
    created_version = event["version"]
    create_station(event["id"])
    published = validate_success(api.publish_event(event["id"], COORD), 200)
    assert published["version"] == created_version + 1, (
        "publish increments the event's version by exactly 1")


def test_station_invalid_enum_rejected(api):
    """PRD §3.1: "A `Coordinator` creates each `Station` with its hosting
    `event_id`, a `category` of `ELECTRONICS`, `TEXTILE`, or `BIKE`, a human
    `label`, and a `capacity` of at least 1 bounding how many fixers may be
    checked in at once."
    PRD §2.5: "Malformed payloads — a missing required field, an invalid enum
    value, an out-of-range scalar, or an end timestamp that does not come after
    its start — are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/station_invalid_enum_rejected
    """
    set_logical_clock()
    event = create_event(name="Cafe Upsilon")
    res = api.create_station(
        create_station_payload(event["id"], category="PLUMBING"), COORD)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_repair_item_not_found_returns_404(api):
    """PRD §2.6: "Each resource type reports its own not-found error, all with
    HTTP 404: `ERR_EVENT_NOT_FOUND` for a `RepairEvent`, `ERR_STATION_NOT_FOUND`
    for a `Station`, `ERR_FIXER_NOT_FOUND` for a `FixerProfile`,
    `ERR_VISITOR_NOT_FOUND` for a `Visitor`, `ERR_WAIVER_NOT_FOUND` for a
    `Waiver`, `ERR_ITEM_NOT_FOUND` for a `RepairItem`, `ERR_TRIAGE_NOT_FOUND`
    for a `TriageRecord`, `ERR_SHIFT_NOT_FOUND` for a `FixerShift`,
    `ERR_SKILL_NOT_FOUND` for a `FixerSkill`, `ERR_PART_STOCK_NOT_FOUND` for a
    `PartStock`, `ERR_RESERVATION_NOT_FOUND` for a `PartReservation`,
    `ERR_OUTCOME_NOT_FOUND` for a `RepairOutcome`, `ERR_INCIDENT_NOT_FOUND` for
    a `SafetyIncident`, `ERR_DONATION_NOT_FOUND` for a `Donation`, and
    `ERR_REPORT_NOT_FOUND` for an `EventReport`."

    Design: Corner/entities/repair_item_not_found_returns_404
    """
    res = api.get_repair_item(NON_EXISTENT_UUID, COORD)
    validate_error(res, ApiErrorId.ERR_ITEM_NOT_FOUND)


def test_item_intake_defaults_and_system_fields(api):
    """PRD §3.2: "The volunteer submits the hosting `event_id`, the owning
    `visitor_id`, the item's `category` (`ELECTRONICS`, `TEXTILE`, or `BIKE`), a
    free-text `description` of the problem, an optional `hazard_flag`
    (defaulting to false) marking mains-powered, fuel-bearing,
    sharps-containing, or similarly dangerous items, and a `weight_kg_estimated`
    of at least 0.1 kilograms."
    PRD §3.2: "A successfully accepted item is born in `REGISTERED` status and
    raises `active_item_count` by one."
    PRD §3.3: "Before any triage the score is 0. The item's
    `required_skill_level` is set equal to the triage record's
    `estimated_difficulty` (0 before triage)."

    Design: Corner/entities/item_intake_defaults_and_system_fields
    """
    ctx = setup_intake_open_event(event_name="Cafe Phi")
    # hazard_flag omitted entirely -> default false applies.
    item = validate_success(api.create_repair_item(
        create_repair_item_payload(ctx["event"]["id"], ctx["visitor"]["id"],
                                   category="TEXTILE", description="Torn coat",
                                   weight_kg_estimated=0.8),
        INTAKE), 201)
    assert_repair_item(item)
    assert item["hazard_flag"] is False, "hazard_flag defaults to false"
    assert item["status"] == "REGISTERED"
    assert item["priority_score"] == 0, "score is 0 before triage"
    assert item["required_skill_level"] == 0, "required level is 0 before triage"
    assert isinstance(item["version"], int)


def test_donation_monetary_missing_required_amount_rejected(api):
    """PRD §3.8: "The `donation_type` is either `MONETARY`, which requires an
    `amount_cents` of at least 1, or `IN_KIND`, which requires a non-empty
    `in_kind_lines` array whose entries each carry a `description`, a
    `category`, a `declared_value_cents`, and an `age_years`."
    PRD §2.5: "Malformed payloads — a missing required field, an invalid enum
    value, an out-of-range scalar, or an end timestamp that does not come after
    its start — are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/donation_monetary_missing_required_amount_rejected
    """
    res = api.create_donation({"donation_type": "MONETARY"}, INTAKE)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_fk_reverse_reachability_filtered_lists(api):
    """PRD §2.3: "List endpoints additionally accept optional filter query
    parameters named after fields of the listed resource (for example
    `event_id`, `status`, or `category`), which narrow the result set to exact
    matches."

    Design: Corner/entities/fk_reverse_reachability_filtered_lists
    """
    set_logical_clock()
    event = create_event(name="Cafe Chi")
    fixer = register_fixer()
    skill = add_skill(fixer["id"], category="BIKE", level=2)

    data, meta = validate_paginated(
        api.list_fixer_skills(COORD, params={"fixer_id": fixer["id"]}))
    assert [s["id"] for s in data] == [skill["id"]], (
        "fixer-skills?fixer_id must return exactly that fixer's skills")
    assert meta["total_count"] == 1

    data, meta = validate_paginated(
        api.list_repair_items(COORD, params={"event_id": event["id"]}))
    assert data == [] and meta["total_count"] == 0, (
        "repair-items?event_id on an item-less event returns an empty array")


def test_list_pagination_defaults_and_has_more(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10 when omitted, and must lie between 1 and 100
    inclusive. The `offset` parameter sets how many items to skip and defaults
    to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/list_pagination_defaults_and_has_more
    """
    set_logical_clock()
    ids = [register_visitor(full_name=f"V {i}")["id"] for i in range(3)]

    data, meta = validate_paginated(api.list_visitors(COORD))
    assert len(data) == 3, "default limit 10 returns all 3 rows"
    assert meta["total_count"] == 3 and meta["has_more"] is False
    assert meta["limit"] == 10 and meta["offset"] == 0

    data, meta = validate_paginated(api.list_visitors(COORD, params={"limit": 2}))
    assert len(data) == 2 and meta["has_more"] is True
    assert meta["total_count"] == 3 and meta["limit"] == 2

    data, meta = validate_paginated(
        api.list_visitors(COORD, params={"limit": 2, "offset": 2}))
    assert len(data) == 1, "offset 2 with 3 rows yields exactly 1 row"
    assert meta["has_more"] is False
    assert data[0]["id"] in ids


def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §2.6: "Each resource type reports its own not-found error, all with
    HTTP 404: `ERR_EVENT_NOT_FOUND` for a `RepairEvent`, `ERR_STATION_NOT_FOUND`
    for a `Station`, `ERR_FIXER_NOT_FOUND` for a `FixerProfile`,
    `ERR_VISITOR_NOT_FOUND` for a `Visitor`, `ERR_WAIVER_NOT_FOUND` for a
    `Waiver`, `ERR_ITEM_NOT_FOUND` for a `RepairItem`, `ERR_TRIAGE_NOT_FOUND`
    for a `TriageRecord`, `ERR_SHIFT_NOT_FOUND` for a `FixerShift`,
    `ERR_SKILL_NOT_FOUND` for a `FixerSkill`, `ERR_PART_STOCK_NOT_FOUND` for a
    `PartStock`, `ERR_RESERVATION_NOT_FOUND` for a `PartReservation`,
    `ERR_OUTCOME_NOT_FOUND` for a `RepairOutcome`, `ERR_INCIDENT_NOT_FOUND` for
    a `SafetyIncident`, `ERR_DONATION_NOT_FOUND` for a `Donation`, and
    `ERR_REPORT_NOT_FOUND` for an `EventReport`."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    res = api.get_repair_event(NON_EXISTENT_UUID, COORD)
    validate_error(res, ApiErrorId.ERR_EVENT_NOT_FOUND)
    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"]
    assert "api_request_timestamp" in body["meta"]
