"""The access decision rule chain, schedule containment, and access-group
membership/deletion effects."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    access_check,
    create_access_group,
    create_building,
    create_credential,
    create_door,
    create_master_change_chain,
    create_person,
    get_door,
    get_success_data,
    issue_credential,
    set_clock,
    setup_access_ready_door,
    setup_building_with_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
DESK = TEST_USERS["front_desk_headers"]
OFFICER = TEST_USERS["security_officer_headers"]


def test_access_decision_simulated_persists_nothing(api):
    """PRD §3.3: "Under mode `SIMULATED`, the same outcome is computed and
    returned but nothing is persisted."
    PRD §3.3: "The response carries the `outcome`, the `credential_id`, the
    `door_id`, the evaluation timestamp `evaluated_at`, and the
    `access_event_id` of the appended row (null under `SIMULATED`)."

    Design: Corner/calculations/access_decision_simulated_persists_nothing
    """
    ctx = setup_access_ready_door("Sim House", clock="2026-08-01T08:00:00Z")
    result = access_check(ctx["door"]["id"], ctx["credential"]["id"], mode="SIMULATED")
    assert result["outcome"] == "GRANTED"
    assert result["access_event_id"] is None

    events, meta = validate_paginated(
        api.list_access_events(OFFICER, params={"door_id": ctx["door"]["id"]})
    )
    assert events == []
    assert meta["total_count"] == 0
    assert get_door(ctx["door"]["id"])["open_since"] is None


def test_access_decision_overnight_window_wrap(api):
    """PRD §3.3: "When the start is later than the end, containment means the
    test minute is at or after the start, or strictly before the end — the
    overnight wrap — and day membership still refers to the UTC weekday of the
    current instant."

    Design: Corner/calculations/access_decision_overnight_window_wrap
    """
    ctx = setup_access_ready_door("Night House", clock="2026-08-01T23:00:00Z",
                                  group_start="22:00", group_end="06:00")
    late = access_check(ctx["door"]["id"], ctx["credential"]["id"], mode="SIMULATED")
    assert late["outcome"] == "GRANTED"

    set_clock("2026-08-02T12:00:00Z")
    noon = access_check(ctx["door"]["id"], ctx["credential"]["id"], mode="SIMULATED")
    assert noon["outcome"] == "DENIED_OUTSIDE_WINDOW"


def test_access_decision_window_end_exclusive(api):
    """PRD §3.3: "When the start is earlier than the end, containment means the
    test minute is greater than or equal to the start and strictly less than the
    end — a half-open interval."

    Design: Corner/calculations/access_decision_window_end_exclusive
    """
    ctx = setup_access_ready_door("HalfOpen House", clock="2026-08-01T17:59:00Z",
                                  group_start="08:00", group_end="18:00")
    before = access_check(ctx["door"]["id"], ctx["credential"]["id"], mode="SIMULATED")
    assert before["outcome"] == "GRANTED"

    set_clock("2026-08-01T18:00:00Z")
    at_end = access_check(ctx["door"]["id"], ctx["credential"]["id"], mode="SIMULATED")
    assert at_end["outcome"] == "DENIED_OUTSIDE_WINDOW"


def test_access_decision_denied_not_authorized_when_no_group_covers_door(api):
    """PRD §3.3: "(4) the covering groups are those access groups of the door's
    building whose `person_ids` contain the credential's holder and whose
    `door_ids` contain the door — if none exist, the outcome is
    `DENIED_NOT_AUTHORIZED`;"

    Design: Corner/calculations/access_decision_denied_not_authorized_when_no_group_covers_door
    """
    ctx = setup_building_with_chain("Auth House", with_door=True)
    building, change, d1 = ctx["building"], ctx["change"], ctx["door"]
    set_clock("2026-08-01T08:00:00Z")
    d2 = create_door(building["id"], change["id"], "D-2")
    staff = create_person(building["id"], "Staff One", "STAFF")
    cred = create_credential(building["id"], change["id"], "K-1", "FOB")
    issue_credential(cred["id"], staff["id"])
    create_access_group(building["id"], "OtherDoor", door_ids=[d2["id"]],
                        person_ids=[staff["id"]])

    result = access_check(d1["id"], cred["id"], mode="SIMULATED")
    assert result["outcome"] == "DENIED_NOT_AUTHORIZED"


def test_vendor_expiry_equality_denies_access(api):
    """PRD §3.3: "(3) if the credential carries an `expires_at` and now is at or
    past it, the outcome is `DENIED_CREDENTIAL_EXPIRED`;"
    PRD §3.6: "the boundary is consistent with the access rule that a credential
    is valid only while now is strictly before `expires_at`."

    Design: Corner/calculations/vendor_expiry_equality_denies_access
    """
    ctx = setup_building_with_chain("Expiry House", with_door=True)
    building, change, door = ctx["building"], ctx["change"], ctx["door"]
    set_clock("2026-08-01T11:00:00Z")
    vendor = create_person(building["id"], "Vendor One", "VENDOR", employer_name="ACME")
    badge = create_credential(building["id"], change["id"], "VB-1", "FOB")
    issue_credential(badge["id"], vendor["id"], expires_at="2026-08-01T12:00:00Z")
    create_access_group(building["id"], "Vendors", door_ids=[door["id"]],
                        person_ids=[vendor["id"]])

    set_clock("2026-08-01T11:59:59Z")
    before = access_check(door["id"], badge["id"], mode="SIMULATED")
    assert before["outcome"] == "GRANTED"

    set_clock("2026-08-01T12:00:00Z")
    at_expiry = access_check(door["id"], badge["id"], mode="SIMULATED")
    assert at_expiry["outcome"] == "DENIED_CREDENTIAL_EXPIRED"


def test_access_decision_denied_credential_not_issued(api):
    """PRD §3.3: "(2) the credential's `status` must be `ISSUED`, else the
    outcome is `DENIED_CREDENTIAL_NOT_ISSUED`;"
    PRD §3.3: "Under mode `RECORDED`, an `AccessEvent` row is appended capturing
    `building_id` (copied from the door), `credential_id`, `door_id`, the
    logical-clock `occurred_at`, and the winning `outcome`; additionally, when
    the outcome is `GRANTED` and the door's `open_since` is currently null,
    `open_since` is set to now — but re-scans while the door already shows open
    do not refresh it."

    Design: Corner/calculations/access_decision_denied_credential_not_issued
    """
    ctx = setup_building_with_chain("NotIssued Check House", with_door=True)
    building, change, door = ctx["building"], ctx["change"], ctx["door"]
    set_clock("2026-08-01T08:00:00Z")
    staff = create_person(building["id"], "Staff One", "STAFF")
    cred = create_credential(building["id"], change["id"], "K-1", "FOB")
    create_access_group(building["id"], "All", door_ids=[door["id"]],
                        person_ids=[staff["id"]])

    result = access_check(door["id"], cred["id"], mode="RECORDED")
    assert result["outcome"] == "DENIED_CREDENTIAL_NOT_ISSUED"
    assert result["access_event_id"] is not None

    event = validate_success(api.get_access_event(result["access_event_id"], OFFICER))
    assert event["outcome"] == "DENIED_CREDENTIAL_NOT_ISSUED"
    assert get_door(door["id"])["open_since"] is None


def test_access_group_delete_revokes_future_grants(api):
    """PRD §3.3: "Groups can also be deleted outright."
    PRD §4: "deleting an access group returns `204 No Content`."
    PRD §3.3: "(4) the covering groups are those access groups of the door's
    building whose `person_ids` contain the credential's holder and whose
    `door_ids` contain the door — if none exist, the outcome is
    `DENIED_NOT_AUTHORIZED`;"

    Design: Corner/endpoints/access_group_delete_revokes_future_grants
    """
    ctx = setup_access_ready_door("Delete Group House", clock="2026-08-01T08:00:00Z")
    resp = api.delete_access_group(ctx["group"]["id"], ADMIN)
    assert resp.status_code == 204

    result = access_check(ctx["door"]["id"], ctx["credential"]["id"], mode="SIMULATED")
    assert result["outcome"] == "DENIED_NOT_AUTHORIZED"
    validate_error(api.get_access_group(ctx["group"]["id"], ADMIN),
                   ApiErrorId.ERR_NOT_FOUND)


def test_access_group_equal_window_bounds_rejected(api):
    """PRD §3.3: "The two window bounds must differ — equal bounds are
    `ERR_SCHEDULE_INVALID` — and a start later than the end is meaningful: the
    window wraps past midnight."

    Design: Corner/validations/access_group_equal_window_bounds_rejected
    """
    building = create_building("Sched House")
    resp = api.create_access_group(
        {"building_id": building["id"], "name": "Bad", "days_of_week": ["MON"],
         "window_start_utc": "08:00", "window_end_utc": "08:00"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_INVALID)


def test_cross_building_group_membership_rejected(api):
    """PRD §2.8: "Every operational entity belongs to exactly one `Building`,
    referenced by `building_id`, and references across entities must stay inside
    a single building. A credential's `key_node_id`, a door's `key_node_id`, the
    doors and persons named in an access group's `door_ids` and `person_ids`, a
    campaign's `key_node_id`, and a work order's `door_id` must all resolve to
    resources in the same building as the enclosing operation; any
    cross-building reference is rejected with `ERR_CROSS_BUILDING_REFERENCE`
    (HTTP 422)."

    Design: Corner/validations/cross_building_group_membership_rejected
    """
    b1 = create_building("B1")
    _, c1 = create_master_change_chain(b1["id"])
    d1 = create_door(b1["id"], c1["id"], "D-1")
    b2 = create_building("B2")
    create_master_change_chain(b2["id"])

    resp = api.create_access_group(
        {"building_id": b2["id"], "name": "BadGroup", "door_ids": [d1["id"]],
         "days_of_week": ["MON"], "window_start_utc": "08:00", "window_end_utc": "17:00"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_BUILDING_REFERENCE)
