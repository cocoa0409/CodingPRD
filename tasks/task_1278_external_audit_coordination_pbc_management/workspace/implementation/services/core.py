"""Core shared helpers: entity construction, common system fields, derived
field recomputation, posture, and cascade machinery."""
import uuid
from db import db
from clock import clock, format_iso


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    """Set system-managed common fields on a freshly created entity."""
    now = format_iso(clock.now())
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on modification."""
    entity["updated_at"] = format_iso(clock.now())
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Engagement derived fields (PRD §2.6, §2.7)
# ---------------------------------------------------------------------------

def rep_letter_for_engagement(engagement_id):
    for letter in db.representation_letters.values():
        if letter["engagement_id"] == engagement_id:
            return letter
    return None


def recompute_engagement_derived(eng):
    """Recompute derived counters and posture on the engagement row.
    - open_pbc_count: PBCRequest status in {OPEN, IN_PROGRESS, SUBMITTED, REJECTED}
    - open_query_count: AuditorQuery status in {OPEN, AWAITING_CLIENT}
    - passed_adjustment_total_cents: sum amount_cents where disposition == PASSED
    - total_fee_cents: base + sum APPROVED deltas; provisional (incl PROPOSED)
      while any PROPOSED fee change exists (PRD §2.7)
    - posture: LOCKED if rep letter SIGNED; CLOSING if status FIELDWORK_COMPLETE;
      else OPEN
    """
    eng_id = eng["id"]
    eng["open_pbc_count"] = sum(
        1
        for p in db.pbc_requests.values()
        if p["engagement_id"] == eng_id
        and p["status"] in ("OPEN", "IN_PROGRESS", "SUBMITTED", "REJECTED")
    )
    eng["open_query_count"] = sum(
        1
        for q in db.queries.values()
        if q["engagement_id"] == eng_id and q["status"] in ("OPEN", "AWAITING_CLIENT")
    )
    eng["passed_adjustment_total_cents"] = sum(
        a["amount_cents"]
        for a in db.adjustments.values()
        if a["engagement_id"] == eng_id and a["disposition"] == "PASSED"
    )
    approved_sum = sum(
        f["delta_cents"]
        for f in db.fee_change_requests.values()
        if f["engagement_id"] == eng_id and f["status"] == "APPROVED"
    )
    proposed_sum = sum(
        f["delta_cents"]
        for f in db.fee_change_requests.values()
        if f["engagement_id"] == eng_id and f["status"] == "PROPOSED"
    )
    if proposed_sum != 0 or any(
        f["engagement_id"] == eng_id and f["status"] == "PROPOSED"
        for f in db.fee_change_requests.values()
    ):
        eng["total_fee_cents"] = eng["base_fee_cents"] + approved_sum + proposed_sum
    else:
        eng["total_fee_cents"] = eng["base_fee_cents"] + approved_sum

    letter = rep_letter_for_engagement(eng_id)
    if letter is not None and letter["status"] == "SIGNED":
        eng["posture"] = "LOCKED"
    elif eng["status"] == "FIELDWORK_COMPLETE":
        eng["posture"] = "CLOSING"
    else:
        eng["posture"] = "OPEN"


def get_engagement_or_404(engagement_id):
    from errors import ApiError, ERR_ENGAGEMENT_NOT_FOUND

    eng = db.engagements.get(engagement_id)
    if eng is None:
        raise ApiError(
            ERR_ENGAGEMENT_NOT_FOUND, "AuditEngagement id not found", 404
        )
    return eng


def find_engagement_for_child(child):
    return db.engagements.get(child["engagement_id"])


# ---------------------------------------------------------------------------
# Cascades (PRD §3.1 cancel, §3.8 rep-letter sign)
# ---------------------------------------------------------------------------

def cascade_engagement_cancelled(eng):
    """Cascade for AuditEngagement -> CANCELLED."""
    eng_id = eng["id"]
    for p in db.pbc_requests.values():
        if p["engagement_id"] == eng_id and p["status"] in (
            "OPEN",
            "IN_PROGRESS",
            "SUBMITTED",
            "REJECTED",
        ):
            p["status"] = "FROZEN"
            touch(p)
    for e in db.evidence_uploads.values():
        if e["engagement_id"] == eng_id and e["status"] == "PENDING_REVIEW":
            e["status"] = "INVALIDATED"
            touch(e)
    for s in db.sampling_requests.values():
        if s["engagement_id"] == eng_id and s["status"] in (
            "DRAFT",
            "DISPATCHED",
            "IN_PROGRESS",
        ):
            s["status"] = "CANCELLED"
            touch(s)
    for v in db.fieldwork_visits.values():
        if v["engagement_id"] == eng_id and v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            touch(v)
    for a in db.adjustments.values():
        if a["engagement_id"] == eng_id and a["disposition"] == "PROPOSED":
            a["disposition"] = "REJECTED"
            a["disposition_rationale"] = "ENGAGEMENT_CANCELLED"
            touch(a)
    for f in db.fee_change_requests.values():
        if f["engagement_id"] == eng_id and f["status"] == "PROPOSED":
            f["status"] = "WITHDRAWN"
            touch(f)


def cascade_rep_letter_signed(eng):
    """Cascade for RepresentationLetter -> SIGNED."""
    eng_id = eng["id"]
    for p in db.pbc_requests.values():
        if p["engagement_id"] == eng_id and p["status"] in (
            "OPEN",
            "IN_PROGRESS",
            "SUBMITTED",
            "REJECTED",
        ):
            p["status"] = "FROZEN"
            touch(p)
    for e in db.evidence_uploads.values():
        if e["engagement_id"] == eng_id and e["status"] == "PENDING_REVIEW":
            e["status"] = "INVALIDATED"
            touch(e)
    for f in db.fee_change_requests.values():
        if f["engagement_id"] == eng_id and f["status"] == "PROPOSED":
            f["status"] = "WITHDRAWN"
            touch(f)


# ---------------------------------------------------------------------------
# Serializers (computed read-time fields)
# ---------------------------------------------------------------------------

def engagement_view(eng):
    recompute_engagement_derived(eng)
    return dict(eng)


def pbc_view(pbc):
    return dict(pbc)


def pbc_view_with_aging(pbc):
    """Attach pbc_aging_score for list responses on open-status requests."""
    from services.aging import compute_pbc_aging_score

    view = dict(pbc)
    if pbc["status"] in ("OPEN", "IN_PROGRESS", "SUBMITTED", "REJECTED"):
        view["pbc_aging_score"] = compute_pbc_aging_score(pbc)
    return view
