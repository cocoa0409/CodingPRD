"""Post-incident access-log reviews (PRD §3.8)."""
from flask import Blueprint

import calc
import serialize
from core import (
    ADMIN, AUDITOR, authenticate, body, db, fail, is_str, lookup, new_common,
    ok, ordered, paginate, parse_dt, present, qfilter, touch,
)
from ladder import (
    assert_transition, assert_version, require_action, require_version_field,
)

bp = Blueprint("review", __name__)

REVIEW_TRANSITIONS = {
    "LOCK_EVIDENCE": ("OPEN",),
    "CLOSE": ("EVIDENCE_LOCKED",),
    "REOPEN": ("CLOSED",),
}


def _in_scope(review, event):
    matched = False
    if review.get("lockbox_id") and event.get("lockbox_id") == review["lockbox_id"]:
        matched = True
    if review.get("listing_id") and event.get("listing_id") == review["listing_id"]:
        matched = True
    if not matched:
        return False
    occurred_at = parse_dt(event["occurred_at"])
    start = parse_dt(review["window_start"])
    end = parse_dt(review["window_end"])
    if occurred_at is None or start is None or end is None:
        return False
    return start <= occurred_at <= end


def _lock_evidence(review):
    for event in ordered(db.events):
        if not _in_scope(review, event):
            continue
        stamped = event.get("incident_review_id")
        if stamped and stamped != review["id"]:
            continue
        event["incident_review_id"] = review["id"]
    evidence = [e for e in ordered(db.events) if e.get("incident_review_id") == review["id"]]
    review["event_count"] = len(evidence)
    score, severity = calc.incident_risk_score(evidence)
    review["risk_score"] = score
    review["severity"] = severity


@bp.post("/incident-reviews")
def open_review():
    user_id, _ = authenticate([AUDITOR])
    payload = body()

    # Rung 4 — body foreign keys, in declared input order.
    association = None
    listing = None
    lockbox = None
    if present(payload, "association_id"):
        association = lookup("associations", payload["association_id"])
    if present(payload, "listing_id"):
        listing = lookup("listings", payload["listing_id"])
    if present(payload, "lockbox_id"):
        lockbox = lookup("lockboxes", payload["lockbox_id"])

    # Rung 5 — request shape.
    if association is None:
        fail("ERR_INVALID_REQUEST", "association_id is required.")
    if not present(payload, "window_start") or not present(payload, "window_end"):
        fail("ERR_INVALID_REQUEST", "window_start and window_end are required.")
    if parse_dt(payload["window_start"]) is None or parse_dt(payload["window_end"]) is None:
        fail("ERR_INVALID_REQUEST", "window_start and window_end must be ISO 8601 instants.")

    rec = new_common()
    rec.update({
        "association_id": association["id"],
        "listing_id": listing["id"] if listing else None,
        "lockbox_id": lockbox["id"] if lockbox else None,
        "window_start": payload["window_start"],
        "window_end": payload["window_end"],
        "opened_by_user_id": user_id,
        "closed_by_user_id": None,
        "status": "OPEN",
        "event_count": 0,
        "risk_score": 0.00,
        "severity": "LOW",
        "findings": None,
    })

    # Rung 19 — evidence immutability.
    for event in db.events.values():
        if event.get("incident_review_id") and _in_scope(rec, event):
            fail("ERR_EVIDENCE_LOCKED",
                 "The proposed scope covers events already locked to another review.")

    db.reviews[rec["id"]] = rec
    return ok(serialize.review(rec), 201)


@bp.get("/incident-reviews/<review_id>")
def read_review(review_id):
    authenticate([ADMIN, AUDITOR])
    return ok(serialize.review(lookup("reviews", review_id)))


@bp.get("/incident-reviews")
def list_reviews():
    authenticate([ADMIN, AUDITOR])
    rows = ordered(db.reviews)
    rows = qfilter(rows, "association_id")
    rows = qfilter(rows, "listing_id")
    rows = qfilter(rows, "lockbox_id")
    rows = qfilter(rows, "status")
    return paginate(rows, serialize.review)


@bp.post("/incident-reviews/<review_id>/state")
def review_state(review_id):
    user_id, _ = authenticate([AUDITOR])
    review = lookup("reviews", review_id)
    payload = body()

    # Rung 5 — request shape.
    action = require_action(payload, tuple(REVIEW_TRANSITIONS))
    expected = require_version_field(payload, "expected_review_version")
    findings = payload.get("findings")
    if present(payload, "findings") and not is_str(findings):
        fail("ERR_INVALID_REQUEST", "findings must be a string.")
    if action == "CLOSE" and review.get("severity") == "CRITICAL":
        if not is_str(findings) or not findings.strip():
            fail("ERR_INVALID_REQUEST", "findings are mandatory when severity is CRITICAL.")

    # Rung 7 — segregation of duties.
    if action == "CLOSE" and user_id == review.get("opened_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The auditor who opened a review may not close it.")

    # Rung 8 — optimistic concurrency.
    assert_version(expected, review)

    # Rung 9 — declared transitions (IncidentReview has no terminal state).
    assert_transition(review["status"], REVIEW_TRANSITIONS, action)

    if action == "LOCK_EVIDENCE":
        review["status"] = "EVIDENCE_LOCKED"
        _lock_evidence(review)
    elif action == "CLOSE":
        review["status"] = "CLOSED"
        review["closed_by_user_id"] = user_id
        if present(payload, "findings"):
            review["findings"] = findings
    elif action == "REOPEN":
        review["status"] = "EVIDENCE_LOCKED"
        review["closed_by_user_id"] = None
        _lock_evidence(review)

    touch(review)
    return ok(serialize.review(review))
