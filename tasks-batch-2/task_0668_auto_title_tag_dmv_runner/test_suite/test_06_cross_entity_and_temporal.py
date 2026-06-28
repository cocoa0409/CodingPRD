"""Cross-entity state dependencies and resource temporal-overlap conflicts.

Queue A (Difficulty) — rules cross_entity_state_dependency and resource_temporal_overlap.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_schedule_and_account, setup_trip_dispatched, setup_lien_transaction_submitted,
    create_transaction_verified_and_quoted, submit_transaction, create_planned_trip,
    attach_leg, set_clock, create_runner_trip_payload, make_lien_officer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]
DISPATCHER = TEST_USERS["runner_dispatcher_headers"]
LIEN_OFFICER = TEST_USERS["lien_officer_headers"]


# ─── cross_entity_state_dependency ────────────────────────────────────

def test_submission_decision_requires_trip_returned(api):
    """PRD §3.4: "a decision may only be taken once the submission is ASSIGNED and its
    leg's trip has reached RETURNED; recording a decision before the trip is returned is
    rejected with ERR_TRIP_NOT_RETURNED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/submission_decision_requires_trip_returned
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    # Trip DISPATCHED but NOT yet RETURNED.
    txn, submission, trip, _leg = setup_trip_dispatched(account["id"], "REGISTRATION")
    assert trip["trip_status"] == "DISPATCHED"

    res = api.submission_decision(submission["id"], {"outcome": "ACCEPTED"}, DISPATCHER)
    validate_error(res, "ERR_TRIP_NOT_RETURNED", expected_status=409)

    sub_after = validate_success(api.get_submission(submission["id"], DISPATCHER), 200)
    assert sub_after["submission_status"] == "ASSIGNED"


def test_lien_perfect_requires_transaction_approved(api):
    """PRD §3.8: "A packet may be perfected only when its owning transaction's
    lifecycle_status is APPROVED and that transaction's submission has reached ACCEPTED."
    PRD §2.6: "then whether the target resource is in a state from which the requested
    transition is legal (ERR_INVALID_STATE)."

    Design: Difficulty/cross_entity_state_dependency/lien_perfect_requires_transaction_approved_and_submission_accepted
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    # LIEN transaction still SUBMITTED (trip DISPATCHED, not decided), DRAFT packet.
    txn, packet, _sub, _trip = setup_lien_transaction_submitted(
        account["id"], submitting_user_id="clerk-1")
    assert txn["lifecycle_status"] == "SUBMITTED"

    res = api.perfect_lien_packet(packet["id"], make_lien_officer_headers("lien-officer-7"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    packet_after = validate_success(api.get_lien_packet(packet["id"], LIEN_OFFICER), 200)
    assert packet_after["packet_status"] == "DRAFT"


# ─── resource_temporal_overlap ────────────────────────────────────────

def test_trip_window_half_open_overlap_same_office_rejected(api):
    """PRD §3.4: "a new trip to the same dmv_office_code is rejected with
    ERR_TRIP_WINDOW_OVERLAP (HTTP 409) if its half-open window overlaps that of any
    existing trip to the same office whose trip_status is PLANNED, DISPATCHED, or
    RETURNED. Because the interval is half-open, a trip that begins exactly when another
    ends does not overlap and is allowed."

    Design: Difficulty/resource_temporal_overlap/trip_window_half_open_overlap_same_office_rejected
    """
    set_clock()
    # Existing [09:00, 12:00).
    validate_success(api.create_runner_trip(create_runner_trip_payload(
        dmv_office_code="CA-DMV-01", capacity=5,
        window_start_at="2026-04-01T09:00:00Z", window_end_at="2026-04-01T12:00:00Z"),
        DISPATCHER), 201)
    # Adjacent [12:00, 14:00): start == existing end -> allowed (201).
    validate_success(api.create_runner_trip(create_runner_trip_payload(
        dmv_office_code="CA-DMV-01", capacity=5,
        window_start_at="2026-04-01T12:00:00Z", window_end_at="2026-04-01T14:00:00Z"),
        DISPATCHER), 201)

    # Overlapping [09:30, 11:00) against the existing [09:00, 12:00) -> rejected.
    res = api.create_runner_trip(create_runner_trip_payload(
        dmv_office_code="CA-DMV-01", capacity=5,
        window_start_at="2026-04-01T09:30:00Z", window_end_at="2026-04-01T11:00:00Z"),
        DISPATCHER)
    validate_error(res, "ERR_TRIP_WINDOW_OVERLAP", expected_status=409)


def test_trip_window_adjacent_same_office_allowed(api):
    """PRD §3.4: "Because the interval is half-open, a trip that begins exactly when
    another ends does not overlap and is allowed."

    Design: Difficulty/resource_temporal_overlap/trip_window_half_open_overlap_same_office_rejected
    """
    set_clock()
    validate_success(api.create_runner_trip(create_runner_trip_payload(
        dmv_office_code="CA-DMV-05", capacity=5,
        window_start_at="2026-04-01T09:00:00Z", window_end_at="2026-04-01T12:00:00Z"),
        DISPATCHER), 201)
    adjacent = validate_success(api.create_runner_trip(create_runner_trip_payload(
        dmv_office_code="CA-DMV-05", capacity=5,
        window_start_at="2026-04-01T12:00:00Z", window_end_at="2026-04-01T14:00:00Z"),
        DISPATCHER), 201)
    assert adjacent["trip_status"] == "PLANNED"


def test_expedite_sla_window_open_upper_bound_at_deadline_rejected(api):
    """PRD §3.4: "When the submission is expedited, its sla_deadline_at is set to the
    logical clock's current instant plus the expedite SLA window of 48 hours"
    PRD §3.4: "if the submission is expedited, attaching is allowed only while the
    logical clock's current instant is strictly before the submission's sla_deadline_at,
    and attaching at or after that deadline is rejected as an expired window with
    ERR_SLA_EXPIRED (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/expedite_sla_window_open_upper_bound_at_deadline_rejected
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    # Queue an EXPEDITE submission at 2026-04-01T00:00:00Z -> sla_deadline_at = +48h.
    txn, _q = create_transaction_verified_and_quoted(
        account["id"], "REGISTRATION", txn_overrides={"expedite": True})
    submission = submit_transaction(txn["id"])
    # PRD §3.4 pins the deadline instant (+48h of the logical clock = 2026-04-03T00:00:00Z)
    # but is silent on the textual fractional-digit format of sla_deadline_at; compare the
    # parsed instant rather than the exact string so '...00Z' and '...00.000Z' both pass.
    from datetime import datetime, timezone
    _deadline = datetime.fromisoformat(submission["sla_deadline_at"].replace("Z", "+00:00"))
    assert _deadline == datetime(2026, 4, 3, 0, 0, 0, tzinfo=timezone.utc)

    trip = create_planned_trip(dmv_office_code="CA-DMV-02",
                               window_start_at="2026-04-03T09:00:00Z",
                               window_end_at="2026-04-03T12:00:00Z")
    # Advance clock to exactly the deadline; open upper bound -> expired.
    set_clock("2026-04-03T00:00:00Z")

    res = api.attach_leg(trip["id"], {
        "submission_id": submission["id"],
        "expected_runnertrip_version": trip["version"]}, DISPATCHER)
    validate_error(res, "ERR_SLA_EXPIRED", expected_status=409)
