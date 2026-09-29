"""Derived counters, posture re-derivation and the shared cascade routines."""

import calc
from envelope import mark
from store import db, ordered


# --------------------------------------------------------------- primitives
def setf(entity, key, value):
    """Assign a field, marking the record dirty only when the value moves."""
    if entity.get(key) != value:
        entity[key] = value
        mark(entity)
        return True
    return False


def touch(entity):
    mark(entity)


# ------------------------------------------------------------------ ledgers
def recompute_gallery_slots(gallery):
    if gallery is None:
        return
    count = 0
    for booking in db.bookings.values():
        if booking["gallery_id"] == gallery["id"] and (
            booking["status"] in calc.OCCUPYING_BOOKING_STATUSES
        ):
            count += 1
    setf(gallery, "booked_slot_count", count)


def recompute_channel_gift_liability(channel):
    if channel is None:
        return
    total = 0
    for booking in db.bookings.values():
        if booking["channel_id"] != channel["id"]:
            continue
        if not booking["gift_issued"]:
            continue
        if booking["status"] in calc.GIFT_ACCRUING_STATUSES:
            total += booking["gift_value_cents"]
    setf(channel, "gift_liability_cents", total)


def recompute_channel_rate(channel):
    setf(channel, "historical_no_show_rate", calc.channel_no_show_rate(channel))


def gallery_available_reps(gallery_id):
    count = 0
    for rep in db.reps.values():
        if rep["gallery_id"] == gallery_id and rep["status"] in calc.AVAILABLE_REP_STATUSES:
            count += 1
    return count


def recompute_gallery_reps(gallery):
    """Recompute available_rep_count and re-derive the OPEN/RESTRICTED posture."""
    if gallery is None:
        return
    setf(gallery, "available_rep_count", gallery_available_reps(gallery["id"]))
    rederive_gallery_posture(gallery)


def rederive_gallery_posture(gallery):
    if gallery["status"] == "CLOSED":
        return
    if gallery["available_rep_count"] == 0:
        if gallery["status"] == "OPEN":
            setf(gallery, "status", "RESTRICTED")
    else:
        if gallery["status"] == "RESTRICTED":
            setf(gallery, "status", "OPEN")


def recompute_prospect_owner(prospect):
    if prospect is None:
        return
    owner = False
    for agreement in db.agreements.values():
        if agreement["prospect_id"] != prospect["id"]:
            continue
        if agreement["fulfillment_status"] in calc.OWNER_FULFILLMENT_STATUSES:
            owner = True
            break
    setf(prospect, "is_existing_owner", owner)


# ------------------------------------------------------- presentation score
def presentation_findings(presentation_id):
    return [
        f for f in ordered(db.findings.values()) if f["presentation_id"] == presentation_id
    ]


def presentation_acks(presentation_id):
    return [
        a
        for a in ordered(db.acknowledgments.values())
        if a["presentation_id"] == presentation_id
    ]


def distinct_required_acks(presentation_id):
    codes = set()
    for ack in db.acknowledgments.values():
        if ack["presentation_id"] != presentation_id:
            continue
        if ack["counts_toward_required"]:
            codes.add(ack["disclosure_code"])
    return len(codes)


def recompute_disclosures(presentation):
    count = distinct_required_acks(presentation["id"])
    setf(presentation, "disclosure_ack_count", count)
    required = presentation["required_disclosure_count"]
    if count >= required:
        status = "COMPLETE"
    elif count > 0:
        status = "PARTIAL"
    else:
        status = "PENDING"
    setf(presentation, "disclosure_status", status)
    recompute_compliance_score(presentation)


def recompute_claim_points(presentation):
    points = 0
    for finding in db.findings.values():
        if finding["presentation_id"] == presentation["id"]:
            points += finding["penalty_points"]
    setf(presentation, "prohibited_claim_points", points)
    recompute_compliance_score(presentation)


def recompute_compliance_score(presentation):
    score = calc.compliance_score(
        presentation["prohibited_claim_points"],
        presentation["required_disclosure_count"],
        presentation["disclosure_ack_count"],
    )
    setf(presentation, "compliance_score", score)
    return score


# -------------------------------------------------------- retraining helper
def open_assignment(rep_id, trigger_reason):
    for assignment in db.retrainings.values():
        if assignment["rep_id"] != rep_id:
            continue
        if assignment["trigger_reason"] != trigger_reason:
            continue
        if assignment["status"] in ("ASSIGNED", "IN_PROGRESS"):
            return assignment
    return None


def has_open_assignment(rep_id):
    for assignment in db.retrainings.values():
        if assignment["rep_id"] != rep_id:
            continue
        if assignment["status"] in ("ASSIGNED", "IN_PROGRESS"):
            return True
    return False


def new_assignment(rep, trigger_reason, module_count, cancellation_rate=None):
    now = db.now()
    assignment = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "rep_id": rep["id"],
        "trigger_reason": trigger_reason,
        "required_module_count": module_count,
        "modules_completed": 0,
        "status": "ASSIGNED",
        "cycle_index": 1,
        "cancellation_rate_at_assignment": cancellation_rate,
        "strike_count_at_assignment": rep["compliance_strike_count"],
        "assigned_at": now,
        "started_at": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.retrainings[assignment["id"]] = assignment
    return assignment


# ------------------------------------------------------------ flag cascade
def enter_flagged(presentation):
    """Three-step strike cascade run on every entry into review_status FLAGGED."""
    setf(presentation, "review_status", "FLAGGED")
    setf(presentation, "flag_count", presentation["flag_count"] + 1)
    rep = db.reps.get(presentation["rep_id"])
    if rep is None:
        return
    # CASCADE STEP 1
    setf(rep, "compliance_strike_count", rep["compliance_strike_count"] + 1)
    # CASCADE STEP 2
    if rep["compliance_strike_count"] >= calc.COMPLIANCE_STRIKE_SUSPEND_THRESHOLD:
        setf(rep, "status", "SUSPENDED")
        new_assignment(
            rep, "PROHIBITED_CLAIM_POINTS", calc.AUTO_RETRAINING_MODULE_COUNT
        )
        # CASCADE STEP 3
        recompute_gallery_reps(db.galleries.get(rep["gallery_id"]))


def maybe_auto_flag(presentation):
    score = recompute_compliance_score(presentation)
    findings = presentation_findings(presentation["id"])
    if calc.auto_flag(score, findings) and presentation["review_status"] != "FLAGGED":
        enter_flagged(presentation)


# ------------------------------------------------- rep cancellation posture
def recompute_rep_cancellation(rep):
    analysis = calc.cancellation_analysis(
        db.agreements.values(), rep["id"], db.now()
    )
    setf(rep, "cancellation_rate", analysis["cancellation_rate"])
    return analysis


def recompute_rescinded_count(rep):
    count = 0
    for agreement in db.agreements.values():
        if agreement["rep_id"] == rep["id"] and agreement["rescission_status"] == "RESCINDED":
            count += 1
    setf(rep, "rescinded_agreement_count", count)


# ----------------------------------------------------- channel suspend path
def suspend_channel_cascade(channel):
    """Cascade steps 3-5 of the no-show path."""
    if channel["booked_count"] < calc.NO_SHOW_MIN_SAMPLE:
        return
    if channel["historical_no_show_rate"] < calc.NO_SHOW_SUSPEND_THRESHOLD:
        return
    if channel["status"] != "ACTIVE":
        return
    setf(channel, "status", "SUSPENDED")
    touched = []
    for booking in ordered(db.bookings.values()):
        if booking["channel_id"] != channel["id"]:
            continue
        if booking["status"] not in ("SCHEDULED", "RESCHEDULE_PENDING"):
            continue
        setf(booking, "status", "CANCELLED")
        setf(booking, "cancel_reason", "CHANNEL_SUSPENDED")
        if booking["gallery_id"] not in touched:
            touched.append(booking["gallery_id"])
    for gallery_id in touched:
        recompute_gallery_slots(db.galleries.get(gallery_id))
