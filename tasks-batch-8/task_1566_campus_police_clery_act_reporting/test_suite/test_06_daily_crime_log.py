"""Daily crime log tests: auto-creation, dispositions, public access (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_geography, create_draft_incident, create_submitted_incident,
    create_classified_incident, create_unfounded_incident,
    create_offense_count_payload, get_log_entry_for_incident, list_log_for_incident,
    set_clock, ApiErrorId, assert_log_entry, TEST_USERS,
)

CHIEF = TEST_USERS["chief_headers"]
COORD = TEST_USERS["coordinator_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_log_entry_auto_created_on_submit(api):
    """PRD §3.4: "Submitting an incident creates exactly one
    `DailyCrimeLogEntry` for it — never more, never fewer — with a
    server-minted `entry_number` of the form CL-<seq6> that is unique and never
    reused. The entry copies `date_reported` from the incident's `reported_at`
    and `date_occurred` from its `occurred_at`, starts with `nature` set to the
    literal label "Unclassified", and opens with `disposition` `OPEN`."
    PRD §3.4: "An entry's `is_public` is false when its parent incident is
    `DRAFT`, `WITHDRAWN`, or `UNFOUNDED`, and true otherwise."

    Design: Corner/entities/log_entry_auto_created_on_submit
    """
    geography = create_geography(name="Mall", category="ON_CAMPUS")
    incident = create_draft_incident(
        geography["id"], reported_at="2026-07-30T09:00:00Z",
        occurred_at="2026-07-30T08:00:00Z",
    )
    validate_success(api.submit_incident(incident["id"], CHIEF), 200)

    data, meta = validate_paginated(api.list_crime_log(CHIEF, params={"incident_id": incident["id"]}))
    assert meta["total_count"] == 1, "Exactly one log entry per submitted incident"
    entry = data[0]
    assert_log_entry(entry)
    assert entry["disposition"] == "OPEN"
    assert entry["nature"] == "Unclassified"
    assert entry["is_public"] is True
    assert entry["date_reported"] == "2026-07-30T09:00:00Z"


def test_disposition_unfound_via_patch_returns_invalid_state(api):
    """PRD §3.4: "The disposition value `UNFOUNDED` is never settable through
    the disposition endpoint — it arrives only via the incident-unfound
    cascade — and the request body carries the target `disposition`."
    PRD §3.4: "Attempting a move outside these pairs is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/disposition_unfound_via_patch_returns_invalid_state
    """
    geography = create_geography(name="Lane", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-07-28T09:00:00Z",
        occurred_at="2026-07-28T08:00:00Z",
    )
    entry = get_log_entry_for_incident(incident["id"])

    res = api.update_disposition(entry["id"], {"disposition": "UNFOUNDED"}, CHIEF)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    after = get_log_entry_for_incident(incident["id"])
    assert after["disposition"] == "OPEN"


def test_log_entry_cardinality_conserved_through_dispositions(api):
    """PRD §3.4: "Submitting an incident creates exactly one
    `DailyCrimeLogEntry` for it — never more, never fewer — with a
    server-minted `entry_number` of the form CL-<seq6> that is unique and never
    reused."
    PRD §3.4: "A `PoliceChief` moves an entry's disposition through a small
    machine: `OPEN → INVESTIGATION_PENDING`; from `INVESTIGATION_PENDING` to
    `CLEARED_BY_ARREST` or `CLEARED_EXCEPTIONAL`; from either cleared state
    back to `OPEN` on reopen; and from `INVESTIGATION_PENDING` back to `OPEN`."

    Design: Difficulty/compensating_invariant/log_entry_cardinality_conservation
    """
    geography = create_geography(name="North Walk", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-04-02T10:00:00Z",
        occurred_at="2026-04-02T09:00:00Z",
    )
    entry = get_log_entry_for_incident(incident["id"])
    entry_number = entry["entry_number"]

    updated = validate_success(api.update_disposition(
        entry["id"], {"disposition": "INVESTIGATION_PENDING"}, CHIEF
    ), 200)
    assert updated["disposition"] == "INVESTIGATION_PENDING"
    updated = validate_success(api.update_disposition(
        entry["id"], {"disposition": "CLEARED_BY_ARREST"}, CHIEF
    ), 200)
    assert updated["disposition"] == "CLEARED_BY_ARREST"
    updated = validate_success(api.update_disposition(
        entry["id"], {"disposition": "OPEN"}, CHIEF
    ), 200)
    assert updated["disposition"] == "OPEN", "Reopen from a cleared state restores OPEN"

    data, meta = validate_paginated(api.list_crime_log(CHIEF, params={"incident_id": incident["id"]}))
    assert meta["total_count"] == 1, (
        "Disposition changes mutate in place; cardinality stays exactly 1"
    )
    assert data[0]["entry_number"] == entry_number, (
        "entry_number identity is conserved across disposition mutations"
    )
    assert data[0]["disposition"] == "OPEN"
    assert data[0]["updated_at"] >= data[0]["created_at"]


def test_log_entry_identity_survives_forward_backward_disposition(api):
    """PRD §3.4: "Each mutation refreshes `last_disposition_change_at` and
    recomputes `disposition_update_overdue`. Attempting a move outside these
    pairs is rejected with `ERR_INVALID_STATE`."
    PRD §3.4: "Submitting an incident creates exactly one `DailyCrimeLogEntry`
    for it — never more, never fewer."

    Design: Difficulty/compensating_invariant/log_entry_cardinality_conservation
    """
    geography = create_geography(name="South Walk", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-04-03T10:00:00Z",
        occurred_at="2026-04-03T09:00:00Z",
    )
    entry = get_log_entry_for_incident(incident["id"])

    validate_success(api.update_disposition(
        entry["id"], {"disposition": "INVESTIGATION_PENDING"}, CHIEF
    ), 200)
    # INVESTIGATION_PENDING -> OPEN is a declared pair in the small machine.
    updated = validate_success(api.update_disposition(
        entry["id"], {"disposition": "OPEN"}, CHIEF
    ), 200)
    assert updated["id"] == entry["id"]
    assert updated["disposition"] == "OPEN"

    data, meta = validate_paginated(api.list_crime_log(CHIEF, params={"incident_id": incident["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["entry_number"] == entry["entry_number"]


def test_daily_log_public_access_hides_unfounded(api):
    """PRD §3.4: "An entry's `is_public` is false when its parent incident is
    `DRAFT`, `WITHDRAWN`, or `UNFOUNDED`, and true otherwise. The crime log is
    readable by the `Anonymous` role as well as staff; anonymous callers see
    only public entries ... Staff callers may pass `include_unfounded` to
    surface entries the public cannot see."

    Design: Corner/endpoints/daily_log_public_access_hides_unfounded
    """
    geography = create_geography(name="S", category="ON_CAMPUS")
    incident = create_unfounded_incident(
        geography["id"],
        reported_at="2026-03-05T09:00:00Z", occurred_at="2026-03-05T08:00:00Z",
        offense_counts=[create_offense_count_payload(offense_type="MOTOR_VEHICLE_THEFT")],
        justification="Recovered; owner error",
    )

    anon_data, anon_meta = validate_paginated(api.list_crime_log(ANON))
    assert anon_meta["total_count"] == 0, (
        "Anonymous callers must not see the non-public (unfounded) entry"
    )

    staff_data, staff_meta = validate_paginated(
        api.list_crime_log(CHIEF, params={"include_unfounded": True})
    )
    assert staff_meta["total_count"] == 1
    assert staff_data[0]["disposition"] == "UNFOUNDED"


def test_anonymous_get_unfounded_entry_forbidden(api):
    """PRD §3.4: "anonymous access to a non-public entry — directly or through
    the single-entry read — is rejected with `ERR_ENTRY_NOT_PUBLIC`
    (HTTP 403)."

    Design: Corner/endpoints/anonymous_get_unfounded_entry_forbidden
    """
    geography = create_geography(name="R", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-03-06T09:00:00Z",
        occurred_at="2026-03-06T08:00:00Z",
    )
    entry = get_log_entry_for_incident(incident["id"])

    # Move UNDER_CLASSIFICATION, then unfound (a valid unfound source state).
    validate_success(api.begin_classification(incident["id"], COORD), 200)
    validate_success(api.unfound_incident(
        incident["id"], {"justification": "False report"}, CHIEF
    ), 200)

    res = api.get_crime_log_entry(entry["id"], ANON)
    validate_error(res, ApiErrorId.ERR_ENTRY_NOT_PUBLIC.value, expected_status=403)


def test_log_entry_timeliness_business_day_skip_weekend(api):
    """PRD §3.4: "`entry_overdue` is set at entry creation and is true when
    more than 2 business days elapsed between the incident's `reported_at` and
    the entry's creation."
    PRD §3.4: "the count of business days between two instants means the number
    of dates strictly after the earlier date, up to and including the later
    date, that fall on a Monday through Friday."

    Design: Corner/calculations/log_entry_timeliness_business_day_skip_weekend
    """
    geography = create_geography(name="North", category="ON_CAMPUS")

    # Incident X: reported Friday 2026-07-31T20:00:00Z, entered Monday
    # 2026-08-03T10:00:00Z -> 1 business day (Monday) -> not overdue.
    set_clock("2026-08-03T10:00:00Z")
    incident_x = create_submitted_incident(
        geography["id"], reported_at="2026-07-31T20:00:00Z",
        occurred_at="2026-07-31T19:00:00Z",
    )
    entry_x = get_log_entry_for_incident(incident_x["id"])
    assert entry_x["entry_overdue"] is False, (
        "Friday report entered Monday is 1 business day (Mon), not > 2"
    )

    # Incident Y: reported Friday 2026-07-31T20:00:00Z, entered Wednesday
    # 2026-08-05T10:00:00Z -> Mon, Tue, Wed = 3 business days -> overdue.
    set_clock("2026-08-05T10:00:00Z")
    incident_y = create_submitted_incident(
        geography["id"], reported_at="2026-07-31T20:00:00Z",
        occurred_at="2026-07-31T19:30:00Z",
    )
    entry_y = get_log_entry_for_incident(incident_y["id"])
    assert entry_y["entry_overdue"] is True, (
        "Friday report entered Wednesday is 3 business days (Mon, Tue, Wed) > 2"
    )
