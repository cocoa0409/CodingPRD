"""Social listening: misinformation, platform escalation, corrections (PRD 3.8),
plus the post-crisis retrospective (PRD 3.9).

Endpoints in this module (10):
  POST   /crisis/misinformation-claims
  GET    /crisis/misinformation-claims/{claim_id}
  GET    /crisis/misinformation-claims
  POST   /crisis/misinformation-claims/{claim_id}/triage
  POST   /crisis/misinformation-claims/{claim_id}/escalate-platform
  POST   /crisis/misinformation-claims/{claim_id}/issue-correction
  POST   /crisis/misinformation-claims/{claim_id}/close
  GET    /crisis/post-crisis-reviews/{review_id}
  GET    /crisis/post-crisis-reviews
  POST   /crisis/post-crisis-reviews/{review_id}/score
"""

from flask import Blueprint

import logic as L
from core import (
    ALL_ROLES,
    D,
    Field,
    authenticate,
    enum_filter,
    fail,
    floor_minutes,
    new_record,
    ok,
    ok_list,
    pagination,
    paged,
    store,
    str_filter,
    touch,
    validate_body,
)

bp = Blueprint("claim", __name__)

CLAIM_STATES = ("DETECTED", "TRIAGED", "PLATFORM_ESCALATED", "CORRECTION_ISSUED", "CLOSED")


def claim_incident(claim):
    incident = store.incidents.get(claim["incident_id"])
    if incident is None:
        fail("ERR_INCIDENT_NOT_FOUND", "The claim's incident no longer resolves.")
    return incident


def claim_channel(claim):
    channel = store.channels.get(claim["channel_id"])
    if channel is None:
        fail("ERR_CHANNEL_NOT_FOUND", "The claim's channel no longer resolves.")
    return channel


@bp.post("/crisis/misinformation-claims")
def create_claim():
    authenticate(("SocialListener",))
    body = validate_body(
        [
            Field("incident_id", "id", required=True),
            Field("channel_id", "id", required=True),
            Field("claim_text", "string", required=True, max_len=500),
            Field(
                "virality_score",
                "number",
                required=True,
                min="0.00",
                max="100.00",
                places=2,
            ),
        ]
    )
    incident = L.get_incident(body["incident_id"])
    channel = L.get_channel(body["channel_id"])
    L.require_activated(incident)
    L.require_not_frozen(incident)
    claim = new_record(
        {
            "incident_id": incident["id"],
            "channel_id": channel["id"],
            "correction_statement_id": None,
            "claim_text": body["claim_text"],
            "virality_score": body["virality_score"],
            "correction_window_start": None,
            "correction_window_end": None,
            "correction_window_minutes": 0,
            "state": "DETECTED",
            "resolution_branch": None,
            "takedown_confirmed": False,
            "corrected": False,
            "outcome_note": None,
        }
    )
    store.claims[claim["id"]] = claim
    L.refresh(incident)
    return ok(claim, 201)


@bp.get("/crisis/misinformation-claims/<claim_id>")
def read_claim(claim_id):
    authenticate(ALL_ROLES)
    return ok(L.get_claim(claim_id))


@bp.get("/crisis/misinformation-claims")
def list_claims():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    incident_id = str_filter("incident_id")
    channel_id = str_filter("channel_id")
    correction_statement_id = str_filter("correction_statement_id")
    state = enum_filter("state", CLAIM_STATES)
    rows = list(store.claims.values())
    if incident_id is not None:
        rows = [r for r in rows if r["incident_id"] == incident_id]
    if channel_id is not None:
        rows = [r for r in rows if r["channel_id"] == channel_id]
    if correction_statement_id is not None:
        rows = [r for r in rows if r["correction_statement_id"] == correction_statement_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/misinformation-claims/<claim_id>/triage")
def triage_claim(claim_id):
    authenticate(("SocialListener",))
    validate_body([])
    claim = L.get_claim(claim_id)
    if claim["state"] != "DETECTED":
        fail("ERR_CLAIM_STATE_INVALID", "Only a DETECTED claim may be triaged.")
    incident = claim_incident(claim)
    L.require_activated(incident)
    L.require_not_frozen(incident)
    claim["state"] = "TRIAGED"
    touch(claim)
    L.recompute_containment(incident)
    L.refresh(incident)
    touch(incident)
    return ok(claim)


@bp.post("/crisis/misinformation-claims/<claim_id>/escalate-platform")
def escalate_platform(claim_id):
    authenticate(("SocialListener", "CommsLead"))
    validate_body([])
    claim = L.get_claim(claim_id)
    if claim["state"] != "TRIAGED":
        fail("ERR_CLAIM_STATE_INVALID", "Only a TRIAGED claim may take the platform fork.")
    incident = claim_incident(claim)
    L.require_not_frozen(incident)
    channel = claim_channel(claim)
    # 29. the trust-and-safety path must be verified.
    if channel["escalation_path_state"] != "VERIFIED":
        fail("ERR_ESCALATION_PATH_UNVERIFIED", "The channel escalation path is UNVERIFIED.")
    # 30. virality threshold.
    if D(claim["virality_score"]) < L.VIRALITY_ESCALATION_THRESHOLD:
        fail("ERR_VIRALITY_THRESHOLD_NOT_MET", "The claim virality_score is below 60.00.")
    claim["state"] = "PLATFORM_ESCALATED"
    touch(claim)
    L.recompute_open_escalation_count(channel)
    touch(channel)
    L.refresh(incident)
    return ok(claim)


@bp.post("/crisis/misinformation-claims/<claim_id>/issue-correction")
def issue_correction(claim_id):
    caller = authenticate(("CommsLead",))
    body = validate_body(
        [
            Field("correction_statement_id", "id", required=True),
            Field("correction_window_start", "datetime", required=True),
            Field("correction_window_end", "datetime", required=True),
            Field("expected_channel_version", "int", required=True),
        ]
    )
    # 4. the half-open window must satisfy end strictly after start.
    if body["correction_window_end"] <= body["correction_window_start"]:
        fail(
            "ERR_INVALID_REQUEST",
            "correction_window_end must be strictly after correction_window_start.",
        )
    claim = L.get_claim(claim_id)
    # 6. body foreign key.
    statement = L.get_statement(body["correction_statement_id"])
    channel = claim_channel(claim)
    # 9. optimistic concurrency on the channel (PRD 2.8).
    if body["expected_channel_version"] != channel["version"]:
        fail(
            "ERR_STALE_CHANNEL_VERSION",
            "expected_channel_version %s does not match the channel version %s."
            % (body["expected_channel_version"], channel["version"]),
        )
    # 10. from-state.
    if claim["state"] != "TRIAGED":
        fail("ERR_CLAIM_STATE_INVALID", "Only a TRIAGED claim may take the correction fork.")
    incident = claim_incident(claim)
    # 12. posture gate.
    L.require_not_frozen(incident)
    # 13. privileged correction material stays inside the circle.
    if statement["privilege_marked"]:
        L.require_privilege(caller)
    # 17. the cited statement must be a PUBLISHED CORRECTION on the same incident.
    if (
        statement["statement_type"] != "CORRECTION"
        or statement["state"] != "PUBLISHED"
        or statement["incident_id"] != claim["incident_id"]
    ):
        fail(
            "ERR_CORRECTION_STATEMENT_REQUIRED",
            "The cited statement must be a PUBLISHED CORRECTION on the claim's incident.",
        )
    # 33. half-open overlap capacity on the channel.
    start = body["correction_window_start"]
    end = body["correction_window_end"]
    overlapping = 0
    for other in store.claims.values():
        if other["channel_id"] != channel["id"] or other["state"] != "CORRECTION_ISSUED":
            continue
        if other["correction_window_start"] is None or other["correction_window_end"] is None:
            continue
        if other["correction_window_start"] < end and other["correction_window_end"] > start:
            overlapping += 1
    if overlapping >= channel["max_concurrent_corrections"]:
        fail(
            "ERR_CHANNEL_CORRECTION_CAPACITY",
            "The channel has no correction capacity for the requested window.",
        )
    claim["state"] = "CORRECTION_ISSUED"
    claim["correction_statement_id"] = statement["id"]
    claim["correction_window_start"] = start
    claim["correction_window_end"] = end
    claim["correction_window_minutes"] = floor_minutes(start, end)
    touch(claim)
    L.recompute_reserved_correction_minutes(channel)
    touch(channel)
    L.refresh(incident)
    return ok(claim)


@bp.post("/crisis/misinformation-claims/<claim_id>/close")
def close_claim(claim_id):
    authenticate(("SocialListener", "CommsLead"))
    body = validate_body([Field("outcome_note", "string", required=True)])
    claim = L.get_claim(claim_id)
    if claim["state"] not in ("PLATFORM_ESCALATED", "CORRECTION_ISSUED"):
        fail(
            "ERR_CLAIM_STATE_INVALID",
            "Only a PLATFORM_ESCALATED or CORRECTION_ISSUED claim may be closed.",
        )
    incident = claim_incident(claim)
    L.require_not_frozen(incident)
    channel = claim_channel(claim)
    from_state = claim["state"]
    claim["state"] = "CLOSED"
    claim["outcome_note"] = body["outcome_note"]
    if from_state == "PLATFORM_ESCALATED":
        claim["resolution_branch"] = "PLATFORM"
        claim["takedown_confirmed"] = True
    else:
        claim["resolution_branch"] = "CORRECTION"
        claim["corrected"] = True
    touch(claim)
    if from_state == "PLATFORM_ESCALATED":
        L.recompute_open_escalation_count(channel)
    else:
        # Compensation: restore the conserved channel airtime ledger.
        L.recompute_reserved_correction_minutes(channel)
    touch(channel)
    L.recompute_containment(incident)
    L.refresh(incident)
    touch(incident)
    return ok(claim)


# ---------------------------------------------------------------------------
# PostCrisisReview
# ---------------------------------------------------------------------------
@bp.get("/crisis/post-crisis-reviews/<review_id>")
def read_review(review_id):
    authenticate(ALL_ROLES)
    return ok(L.get_review(review_id))


@bp.get("/crisis/post-crisis-reviews")
def list_reviews():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    incident_id = str_filter("incident_id")
    state = enum_filter("state", ("OPEN", "SCORED"))
    rows = list(store.reviews.values())
    if incident_id is not None:
        rows = [r for r in rows if r["incident_id"] == incident_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/post-crisis-reviews/<review_id>/score")
def score_review(review_id):
    authenticate(("ExecSponsor",))
    body = validate_body(
        [
            Field("scoring_method", "enum", required=True, values=("RAW", "ADJUSTED")),
            Field("playbook_update_count", "int", required=True, min=0),
        ]
    )
    review = L.get_review(review_id)
    # 10. from-state.
    if review["state"] != "OPEN":
        fail("ERR_REVIEW_STATE_INVALID", "Only an OPEN review may be scored.")
    incident = store.incidents.get(review["incident_id"])
    if incident is None:
        fail("ERR_INCIDENT_NOT_FOUND", "The review's incident no longer resolves.")
    if incident["response_state"] != "RESOLVED":
        fail("ERR_INCIDENT_NOT_ACTIVATED", "The review's incident is not RESOLVED.")
    # Scoring is the third operation a FROZEN posture does not block.
    raw, adjusted = L.reputation_deltas(review)
    review["reputation_delta_raw"] = raw
    review["reputation_delta_adjusted"] = adjusted
    review["scoring_method"] = body["scoring_method"]
    review["reported_delta"] = raw if body["scoring_method"] == "RAW" else adjusted
    review["playbook_update_count"] = body["playbook_update_count"]
    review["scored_at"] = store.now()
    review["state"] = "SCORED"
    touch(review)
    # Ledger sync so the incident and the retrospective never disagree.
    incident["reputation_delta_reported"] = review["reported_delta"]
    L.refresh(incident)
    touch(incident)
    return ok(review)
