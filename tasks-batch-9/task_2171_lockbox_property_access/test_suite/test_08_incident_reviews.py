"""Post-incident review of the access log: evidence locking, scoring and reopening."""

import pytest

from test_helpers import (
    ApiErrorId,
    credential_action,
    device_attempt,
    issue_active_credential,
    lock_evidence,
    only_charge,
    open_incident_review,
    read_access_event,
    read_incident_review,
    report_lockbox_lost,
    report_lockbox_stolen,
    review_action,
    setup_assigned_box,
    setup_placed_box,
    setup_placed_box_with_credential,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    AUDITOR,
    SECOND_AUDITOR,
    register_association,
    intake_lockbox,
    set_clock,
)

WINDOW_START = "2026-08-06T00:00:00Z"
WINDOW_END = "2026-08-06T23:59:59Z"


def _three_event_evidence_set():
    """One anonymous after-hours denial, one granted daytime member entry with no booking to
    explain it, and one after-hours contractor attempt on a credential suspended in between."""
    ctx = setup_placed_box_with_credential(clock="2026-08-06T00:00:00Z")
    ctx["anonymous_event"] = device_attempt(
        ctx["lockbox_id"], actor_type="UNKNOWN", occurred_at="2026-08-06T02:30:00Z"
    )
    ctx["granted_event"] = device_attempt(
        ctx["lockbox_id"],
        actor_type="MEMBER",
        credential_id=ctx["credential_id"],
        occurred_at="2026-08-06T10:00:00Z",
    )
    credential_action(ctx["credential_id"], "SUSPEND")
    ctx["stale_credential_event"] = device_attempt(
        ctx["lockbox_id"],
        actor_type="CONTRACTOR",
        credential_id=ctx["credential_id"],
        occurred_at="2026-08-06T21:15:00Z",
    )
    review = open_incident_review(
        ctx["association_id"], WINDOW_START, WINDOW_END, AUDITOR, lockbox_id=ctx["lockbox_id"]
    )
    ctx["review"] = review
    ctx["review_id"] = review["id"]
    return ctx


def test_locked_evidence_weights_each_event_by_outcome_hours_and_actor(api, admin_headers):
    """PRD §3.8: "Its `risk_weight` is the outcome weight for its `outcome`, multiplied by 1.5
    when the event's `after_hours` flag is true and by 1.0 otherwise, multiplied by the actor
    multiplier for its `actor_type`, and the product is rounded half up to two decimal places
    **per event**."
    PRD §3.8: "The outcome weights are 2 for `GRANTED`, 9 for `DENIED_OUTSIDE_WINDOW`, 12 for
    `DENIED_NO_CREDENTIAL`, 18 for `DENIED_CREDENTIAL_INACTIVE` and 25 for
    `DENIED_BOX_MISSING` — a box that is known missing yet still being tried is the loudest
    signal in the catalogue. The actor multipliers are 1.0 for `MEMBER`, 1.25 for `CONTRACTOR`
    and 2.0 for `UNKNOWN`."

    Design: Difficulty/combinatorial_formula/incident_risk_score_nested_multiplier_product_mode_a
    """
    ctx = _three_event_evidence_set()
    lock_evidence(ctx["review_id"], AUDITOR)

    anonymous = read_access_event(ctx["anonymous_event"]["id"])
    assert anonymous["outcome"] == "DENIED_NO_CREDENTIAL"
    assert anonymous["after_hours"] is True
    assert float(anonymous["risk_weight"]) == pytest.approx(36.00, abs=0.01)

    granted = read_access_event(ctx["granted_event"]["id"])
    assert granted["outcome"] == "GRANTED"
    assert granted["after_hours"] is False
    assert float(granted["risk_weight"]) == pytest.approx(2.00, abs=0.01)
    assert granted.get("matched_appointment_id") is None

    stale = read_access_event(ctx["stale_credential_event"]["id"])
    assert stale["outcome"] == "DENIED_CREDENTIAL_INACTIVE"
    assert stale["after_hours"] is True
    assert float(stale["risk_weight"]) == pytest.approx(33.75, abs=0.01)


def test_locked_review_scores_the_frozen_evidence_set(api, admin_headers):
    """PRD §3.8: "The base is the sum of those already-rounded per-event weights; per-event
    rounding first, then summation, is the pinned order. A penalty is then added for entries
    that cannot be explained by a booking: the count of events in the evidence set whose
    `outcome` is `GRANTED`, whose `actor_type` is `MEMBER`, and whose `matched_appointment_id`
    is empty, multiplied by 10."
    PRD §3.8: "Severity follows from thresholds compared with at-or-above semantics: a score of
    70.00 or more is `CRITICAL`, a score of 35.00 or more but below 70.00 is `ELEVATED`, and
    anything below 35.00 is `LOW`."

    Design: Difficulty/combinatorial_formula/incident_risk_score_nested_multiplier_product_mode_a
    """
    ctx = _three_event_evidence_set()
    lock_evidence(ctx["review_id"], AUDITOR)

    review = read_incident_review(ctx["review_id"], AUDITOR)
    assert review["status"] == "EVIDENCE_LOCKED"
    assert review["event_count"] == 3
    assert float(review["risk_score"]) == pytest.approx(81.75, abs=0.01)
    assert review["severity"] == "CRITICAL"


def _locked_and_closed_review():
    """A single after-hours anonymous denial, locked by auditor-1 and closed by auditor-2, with
    a second denial landing inside the same window afterwards."""
    ctx = setup_placed_box(clock="2026-08-06T00:00:00Z")
    device_attempt(
        ctx["lockbox_id"], actor_type="UNKNOWN", occurred_at="2026-08-06T02:30:00Z"
    )
    review = open_incident_review(
        ctx["association_id"], WINDOW_START, WINDOW_END, AUDITOR, lockbox_id=ctx["lockbox_id"]
    )
    lock_evidence(review["id"], AUDITOR)
    review_action(
        review["id"],
        "CLOSE",
        SECOND_AUDITOR,
        findings="Single anonymous attempt, no entry.",
    )
    device_attempt(
        ctx["lockbox_id"], actor_type="UNKNOWN", occurred_at="2026-08-06T03:30:00Z"
    )
    ctx["review_id"] = review["id"]
    return ctx


def test_reopening_a_closed_review_clears_the_closing_auditor(api, admin_headers):
    """PRD §3.8: "Closing a review moves it `EVIDENCE_LOCKED → CLOSED` and records the
    auditor's narrative in `findings` and their identity in `closed_by_user_id`."
    PRD §3.8: "A closed review may be reopened, moving it `CLOSED → EVIDENCE_LOCKED`, which
    clears `closed_by_user_id`, re-stamps the evidence set to pick up any access event that has
    landed inside the review's window since the last lock, and recomputes `event_count`,
    `risk_score` and `severity` over the enlarged set."

    Design: Difficulty/non_linear_state_machine/incident_review_lock_close_reopen_cycle_rescores
    """
    ctx = _locked_and_closed_review()

    before = read_incident_review(ctx["review_id"], AUDITOR)
    assert before["status"] == "CLOSED"
    assert before["event_count"] == 1
    assert float(before["risk_score"]) == pytest.approx(36.00, abs=0.01)
    assert before["severity"] == "ELEVATED"
    assert before["closed_by_user_id"] == "auditor-2"

    reopened = review_action(ctx["review_id"], "REOPEN", AUDITOR)
    assert reopened["status"] == "EVIDENCE_LOCKED"
    assert reopened.get("closed_by_user_id") is None


def test_reopening_rescores_over_the_enlarged_evidence_set(api, auditor_headers):
    """PRD §3.8: "A closed review may be reopened, moving it `CLOSED → EVIDENCE_LOCKED`, which
    clears `closed_by_user_id`, re-stamps the evidence set to pick up any access event that has
    landed inside the review's window since the last lock, and recomputes `event_count`,
    `risk_score` and `severity` over the enlarged set."
    PRD §3.8: "Severity follows from thresholds compared with at-or-above semantics: a score of
    70.00 or more is `CRITICAL`, a score of 35.00 or more but below 70.00 is `ELEVATED`, and
    anything below 35.00 is `LOW`."

    Design: Difficulty/non_linear_state_machine/incident_review_lock_close_reopen_cycle_rescores
    """
    ctx = _locked_and_closed_review()
    review_action(ctx["review_id"], "REOPEN", AUDITOR)

    review = read_incident_review(ctx["review_id"], AUDITOR)
    assert review["event_count"] == 2
    assert float(review["risk_score"]) == pytest.approx(72.00, abs=0.01)
    assert review["severity"] == "CRITICAL"

    rows, _ = validate_paginated(
        api.list_access_events(
            auditor_headers, params={"incident_review_id": ctx["review_id"]}
        )
    )
    assert len(rows) == 2


def test_a_score_of_exactly_seventy_is_critical(api, admin_headers):
    """PRD §3.8: "Severity follows from thresholds compared with at-or-above semantics: a
    score of 70.00 or more is `CRITICAL`, a score of 35.00 or more but below 70.00 is
    `ELEVATED`, and anything below 35.00 is `LOW`. A score of exactly 70.00 is `CRITICAL`."
    PRD §3.6: "If the box's `status` is `MISSING`, the outcome is `DENIED_BOX_MISSING`."

    Design: Corner/calculations/incident_risk_score_critical_threshold_at_exactly_seventy
    """
    ctx = setup_placed_box_with_credential(clock="2026-08-06T00:00:00Z")
    credential_action(ctx["credential_id"], "SUSPEND")

    first = device_attempt(
        ctx["lockbox_id"],
        actor_type="CONTRACTOR",
        credential_id=ctx["credential_id"],
        occurred_at="2026-08-06T09:30:00Z",
    )
    second = device_attempt(
        ctx["lockbox_id"],
        actor_type="CONTRACTOR",
        credential_id=ctx["credential_id"],
        occurred_at="2026-08-06T10:30:00Z",
    )
    report_lockbox_lost(ctx["lockbox_id"])
    third = device_attempt(
        ctx["lockbox_id"], actor_type="MEMBER", occurred_at="2026-08-06T11:00:00Z"
    )

    review = open_incident_review(
        ctx["association_id"], WINDOW_START, WINDOW_END, AUDITOR, lockbox_id=ctx["lockbox_id"]
    )
    lock_evidence(review["id"], AUDITOR)

    for event_id, expected_weight, expected_outcome in (
        (first["id"], 22.50, "DENIED_CREDENTIAL_INACTIVE"),
        (second["id"], 22.50, "DENIED_CREDENTIAL_INACTIVE"),
        (third["id"], 25.00, "DENIED_BOX_MISSING"),
    ):
        event = read_access_event(event_id)
        assert event["outcome"] == expected_outcome
        assert float(event["risk_weight"]) == pytest.approx(expected_weight, abs=0.01)

    scored = read_incident_review(review["id"], AUDITOR)
    assert scored["event_count"] == 3
    assert float(scored["risk_score"]) == pytest.approx(70.00, abs=0.01)
    assert scored["severity"] == "CRITICAL"


def test_risk_score_is_clamped_at_the_ceiling(api, admin_headers):
    """PRD §3.8: "That total is rounded half up to two decimal places and then clamped into the
    range from 0.00 to 100.00 inclusive, and the clamped figure is the review's `risk_score`."
    PRD §3.6: "If the box's `status` is `MISSING`, the outcome is `DENIED_BOX_MISSING`."

    Design: Corner/calculations/incident_risk_score_clamped_at_score_ceiling
    """
    ctx = setup_assigned_box(
        clock="2026-08-06T00:00:00Z",
        serial="LB-0001",
        model="LB_PRO",
        replacement_cost_cents=12000,
    )
    report_lockbox_stolen(ctx["lockbox_id"], "SPD-2026-9001")

    first = device_attempt(
        ctx["lockbox_id"], actor_type="UNKNOWN", occurred_at="2026-08-06T02:00:00Z"
    )
    second = device_attempt(
        ctx["lockbox_id"], actor_type="UNKNOWN", occurred_at="2026-08-06T03:00:00Z"
    )

    review = open_incident_review(
        ctx["association_id"], WINDOW_START, WINDOW_END, AUDITOR, lockbox_id=ctx["lockbox_id"]
    )
    lock_evidence(review["id"], AUDITOR)

    for event_id in (first["id"], second["id"]):
        event = read_access_event(event_id)
        assert event["after_hours"] is True
        assert float(event["risk_weight"]) == pytest.approx(75.00, abs=0.01)

    scored = read_incident_review(review["id"], AUDITOR)
    assert float(scored["risk_score"]) == pytest.approx(100.00, abs=0.01)
    assert scored["severity"] == "CRITICAL"

    charge = only_charge(lockbox_id=ctx["lockbox_id"])
    assert charge["variant_applied"] == "DEPRECIATED_BOOK"


def test_the_opening_auditor_may_not_close_the_review(api, auditor_headers, second_auditor_headers):
    """PRD §3.8: "The closing auditor's `X-User-ID` must differ from `opened_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES` — the association's rule is that the officer who raises a
    concern is not the officer who disposes of it."
    PRD §3.8: "It opens in `OPEN` with `opened_by_user_id` set to the auditor's `X-User-ID`,
    `event_count` at 0, `risk_score` at 0.00 and `severity` at `LOW`."

    Design: Corner/validations/incident_close_by_the_opening_auditor_violates_segregation
    """
    association = register_association()
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
    )
    review = open_incident_review(
        association["id"], WINDOW_START, WINDOW_END, AUDITOR, lockbox_id=lockbox["id"]
    )
    locked = lock_evidence(review["id"], AUDITOR)

    refused = api.incident_review_state(
        review["id"],
        {
            "action": "CLOSE",
            "findings": "No anomalies.",
            "expected_review_version": locked["version"],
        },
        auditor_headers,
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    still_locked = read_incident_review(review["id"], AUDITOR)
    assert still_locked["status"] == "EVIDENCE_LOCKED"
    assert still_locked.get("closed_by_user_id") is None

    accepted = api.incident_review_state(
        review["id"],
        {
            "action": "CLOSE",
            "findings": "No anomalies.",
            "expected_review_version": locked["version"],
        },
        second_auditor_headers,
    )
    closed = validate_success(accepted, 200)
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == "auditor-2"
    assert closed["event_count"] == 0
    assert float(closed["risk_score"]) == pytest.approx(0.00, abs=0.01)
    assert closed["severity"] == "LOW"


def test_locking_an_already_locked_review_reports_the_state_error(api, auditor_headers):
    """PRD §2.6: "Second, the transition check at step 9 outranks evidence immutability at step
    19: locking evidence on a review that is already `EVIDENCE_LOCKED` returns
    `ERR_INVALID_STATE`, not `ERR_EVIDENCE_LOCKED`."

    Design: Corner/validations/lock_evidence_on_locked_review_state_check_precedes_evidence_rule
    """
    association = register_association()
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
    )
    review = open_incident_review(
        association["id"], WINDOW_START, WINDOW_END, AUDITOR, lockbox_id=lockbox["id"]
    )
    locked = lock_evidence(review["id"], AUDITOR)

    response = api.incident_review_state(
        review["id"],
        {"action": "LOCK_EVIDENCE", "expected_review_version": locked["version"]},
        auditor_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert error["error_id"] != ApiErrorId.ERR_EVIDENCE_LOCKED.value

    stored = read_incident_review(review["id"], AUDITOR)
    assert stored["status"] == "EVIDENCE_LOCKED"
    assert stored["version"] == 2


def test_a_second_review_over_already_stamped_events_is_refused(api, auditor_headers, second_auditor_headers):
    """PRD §3.8: "Opening is refused, however, when the proposed scope and window would reach
    events that already belong to another review: an access event carrying a non-empty
    `incident_review_id` may never be pulled into a second review, and an attempt to open one
    over such events is rejected with `ERR_EVIDENCE_LOCKED`."
    PRD §3.8: "It stamps this review's identifier into the `incident_review_id` of every access
    event that matches the review's scope — the review's `lockbox_id` when one was named, or
    its `listing_id` when one was named — and whose `occurred_at` falls inside the inclusive
    window bounded by the review's `window_start` and `window_end`."

    Design: Corner/validations/second_review_over_already_stamped_events_evidence_locked
    """
    association = register_association()
    set_clock("2026-08-06T00:00:00Z")
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
    )
    event = device_attempt(
        lockbox["id"], actor_type="UNKNOWN", occurred_at="2026-08-06T02:30:00Z"
    )
    first_review = open_incident_review(
        association["id"],
        "2026-08-06T00:00:00Z",
        "2026-08-06T12:00:00Z",
        AUDITOR,
        lockbox_id=lockbox["id"],
    )
    lock_evidence(first_review["id"], AUDITOR)

    response = api.create_incident_review(
        {
            "association_id": association["id"],
            "window_start": "2026-08-06T01:00:00Z",
            "window_end": "2026-08-06T23:59:59Z",
            "lockbox_id": lockbox["id"],
        },
        second_auditor_headers,
    )
    validate_error(response, ApiErrorId.ERR_EVIDENCE_LOCKED.value)

    stamped = read_access_event(event["id"])
    assert stamped["incident_review_id"] == first_review["id"]

    rows, _ = validate_paginated(
        api.list_incident_reviews(
            auditor_headers, params={"association_id": association["id"]}
        )
    )
    assert len(rows) == 1
