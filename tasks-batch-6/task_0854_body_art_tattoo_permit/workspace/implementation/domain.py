"""Derived-field recomputation and state-machine cascades."""

import calc
import config
import store
from envelope import force, mark_new, watch
from util import days, minutes, new_id


# ---------------------------------------------------------------------------
# record construction
# ---------------------------------------------------------------------------
def new_record(fields, versioned=True):
    now = store.now()
    rec = {"id": new_id(), "created_at": now, "_seq": store.next_seq()}
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    rec.update(fields)
    mark_new(rec)
    return rec


def rows_for(collection, **match):
    out = []
    for rec in store.sorted_rows(collection):
        if all(rec.get(k) == v for k, v in match.items()):
            out.append(rec)
    return out


def establishment_artists(est_id):
    return rows_for(store.artists, establishment_id=est_id)


def establishment_inspections(est_id):
    return rows_for(store.inspections, establishment_id=est_id)


def establishment_violations(est_id):
    ids = set(i["id"] for i in store.inspections.values()
              if i["establishment_id"] == est_id)
    return [v for v in store.sorted_rows(store.violations)
            if v["inspection_id"] in ids]


# ---------------------------------------------------------------------------
# derived-field recomputation
# ---------------------------------------------------------------------------
def recompute_counters(est):
    watch(est)
    open_rows = [
        v
        for v in establishment_violations(est["id"])
        if v["status"] in config.VIOLATION_OPEN_STATUSES
    ]
    est["open_violation_count"] = len(open_rows)
    est["open_critical_violation_count"] = sum(
        1 for v in open_rows if v["severity"] == "CRITICAL"
    )


def recompute_active_artist_count(est):
    watch(est)
    est["active_artist_count"] = sum(
        1
        for a in store.artists.values()
        if a["establishment_id"] == est["id"] and a["permit_status"] == "ACTIVE"
    )


def recompute_sterilization(est):
    watch(est)
    status, _candidates, _passes = calc.sterilization_status(est["id"], store.now())
    est["sterilization_compliance_status"] = status


def recompute_posture(est):
    watch(est)
    est["operating_posture"] = calc.operating_posture(
        est["permit_status"], est["risk_score"], est["open_critical_violation_count"]
    )


def recompute_risk(est):
    """Sterilization is refreshed whenever the risk figure is recomputed
    (PRD §3.5), then the PROVISIONAL variant is persisted."""
    watch(est)
    recompute_sterilization(est)
    est["risk_score"] = calc.risk_score(est, store.now(), "PROVISIONAL")


def recompute_risk_and_posture(est):
    recompute_risk(est)
    recompute_posture(est)


def recompute_fees(est):
    watch(est)
    paid = 0
    refunded = 0
    for app in store.renewal_applications.values():
        if app["establishment_id"] != est["id"]:
            continue
        paid += app["fee_paid_cents"]
        refunded += app["fee_refunded_cents"]
    est["fees_paid_cents"] = paid
    est["fees_refunded_cents"] = refunded


# ---------------------------------------------------------------------------
# artist roster cascades
# ---------------------------------------------------------------------------
def deactivate_roster(est):
    """Every ACTIVE or PROBATION artist drops to INACTIVE, created_at ASC."""
    for artist in establishment_artists(est["id"]):
        if artist["permit_status"] in ("ACTIVE", "PROBATION"):
            watch(artist)
            artist["permit_status"] = "INACTIVE"


def reactivate_roster(est):
    """Every INACTIVE artist returns to ACTIVE with permit_expires_on
    refreshed from the establishment, created_at ASC."""
    for artist in establishment_artists(est["id"]):
        if artist["permit_status"] == "INACTIVE":
            watch(artist)
            artist["permit_status"] = "ACTIVE"
            artist["permit_expires_on"] = est["permit_expires_on"]


def cancel_scheduled_routine_inspections(est):
    for insp in establishment_inspections(est["id"]):
        if insp["status"] == "SCHEDULED" and insp["inspection_type"] == "ROUTINE":
            watch(insp)
            insp["status"] = "CANCELLED"


# ---------------------------------------------------------------------------
# establishment lifecycle transitions
# ---------------------------------------------------------------------------
def suspend_establishment(est):
    """ACTIVE -> SUSPENDED (system trigger)."""
    if est["permit_status"] != "ACTIVE":
        return False
    force(est)
    est["permit_status"] = "SUSPENDED"
    deactivate_roster(est)
    cancel_scheduled_routine_inspections(est)
    recompute_active_artist_count(est)
    est["operating_posture"] = "CLOSED"
    return True


def revoke_establishment(est):
    """ACTIVE -> REVOKED (system trigger).  Per PRD §3.8 the revocation branch
    does NOT cancel routine inspections and does NOT recompute
    active_artist_count; only the suspension branch does."""
    if est["permit_status"] != "ACTIVE":
        return False
    force(est)
    est["permit_status"] = "REVOKED"
    deactivate_roster(est)
    est["operating_posture"] = "CLOSED"
    return True


def expire_establishment(est):
    """ACTIVE -> EXPIRED (clock sweep)."""
    force(est)
    est["permit_status"] = "EXPIRED"
    deactivate_roster(est)
    recompute_active_artist_count(est)
    est["operating_posture"] = "CLOSED"


def reinstate_establishment(est, action_id):
    """SUSPENDED -> ACTIVE when the suspending action is lifted."""
    if est["permit_status"] != "SUSPENDED":
        return False
    others = [
        a
        for a in store.enforcement_actions.values()
        if a.get("establishment_id") == est["id"]
        and a["status"] == "ACTIVE"
        and a["id"] != action_id
    ]
    if others:
        return False
    if est["permit_expires_on"] is None or est["permit_expires_on"] <= store.now():
        return False
    force(est)
    est["permit_status"] = "ACTIVE"
    reactivate_roster(est)
    recompute_active_artist_count(est)
    recompute_risk_and_posture(est)
    return True


def renew_establishment(est, decided_at):
    """EXPIRED -> ACTIVE or ACTIVE -> ACTIVE driven by renewal approval."""
    if est["permit_status"] not in ("EXPIRED", "ACTIVE"):
        return
    revival = est["permit_status"] == "EXPIRED"
    force(est)
    est["permit_status"] = "ACTIVE"
    est["permit_issued_on"] = decided_at
    est["permit_expires_on"] = decided_at + days(config.PERMIT_TERM_DAYS)
    if revival:
        reactivate_roster(est)
        recompute_active_artist_count(est)
        recompute_risk_and_posture(est)
    else:
        for artist in establishment_artists(est["id"]):
            if artist["permit_status"] == "ACTIVE":
                watch(artist)
                artist["permit_expires_on"] = est["permit_expires_on"]


# ---------------------------------------------------------------------------
# enforcement helpers
# ---------------------------------------------------------------------------
def active_enforcement_for_establishment(est_id):
    for a in store.sorted_rows(store.enforcement_actions):
        if a.get("establishment_id") == est_id and a["status"] == "ACTIVE":
            return a
    return None


def active_enforcement_for_artist(artist_id):
    for a in store.sorted_rows(store.enforcement_actions):
        if a.get("artist_id") == artist_id and a["status"] == "ACTIVE":
            return a
    return None


def create_enforcement_action(
    subject_type,
    establishment_id,
    artist_id,
    action_type,
    reason_code,
    issued_by_user_id,
    auto_generated=False,
):
    rec = new_record(
        {
            "establishment_id": establishment_id,
            "artist_id": artist_id,
            "subject_type": subject_type,
            "action_type": action_type,
            "reason_code": reason_code,
            "status": "ACTIVE",
            "issued_by_user_id": issued_by_user_id,
            "issued_at": store.now(),
            "lifted_by_user_id": None,
            "lifted_at": None,
            "auto_generated": auto_generated,
            "suspension_days": None,
            "reinstatement_base_cents": None,
            "reinstatement_admin_fee_cents": None,
            "reinstatement_total_cents": None,
        }
    )
    store.enforcement_actions[rec["id"]] = rec
    return rec


def apply_artist_enforcement(artist, est, action_type):
    status = artist["permit_status"]
    if action_type == "SUSPENSION":
        if status == "ACTIVE":
            watch(artist)
            artist["permit_status"] = "SUSPENDED"
            recompute_active_artist_count(est)
            recompute_posture(est)
        elif status == "PROBATION":
            watch(artist)
            artist["permit_status"] = "SUSPENDED"
    else:  # REVOCATION
        if status == "ACTIVE":
            watch(artist)
            artist["permit_status"] = "REVOKED"
            recompute_active_artist_count(est)


def reinstate_artist(artist, est):
    """SUSPENDED -> ACTIVE, provided the parent establishment is ACTIVE."""
    if artist["permit_status"] != "SUSPENDED":
        return False
    if est is None or est["permit_status"] != "ACTIVE":
        return False
    watch(artist)
    artist["permit_status"] = "ACTIVE"
    recompute_active_artist_count(est)
    recompute_posture(est)
    return True


# ---------------------------------------------------------------------------
# the violation-issuance auto-suspension cascade (PRD §3.4 hops 3-5)
# ---------------------------------------------------------------------------
def maybe_auto_suspend(est):
    if est["risk_score"] < config.RISK_SUSPENSION_THRESHOLD:
        recompute_posture(est)
        return None
    if active_enforcement_for_establishment(est["id"]) is not None:
        recompute_posture(est)
        return None
    action = create_enforcement_action(
        subject_type="ESTABLISHMENT",
        establishment_id=est["id"],
        artist_id=None,
        action_type="SUSPENSION",
        reason_code="RISK_THRESHOLD",
        issued_by_user_id="SYSTEM",
        auto_generated=True,
    )
    if not suspend_establishment(est):
        recompute_posture(est)
    return action


# ---------------------------------------------------------------------------
# inspection window exclusivity (PRD §3.3, buffered closed intervals)
# ---------------------------------------------------------------------------
def inspection_window_conflicts(est_id, start, end, exclude_id=None):
    buffer = minutes(config.INSPECTION_BUFFER_MINUTES)
    new_start = start - buffer
    new_end = end + buffer
    for insp in establishment_inspections(est_id):
        if insp["id"] == exclude_id:
            continue
        if insp["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        other_start = insp["scheduled_start_at"] - buffer
        other_end = insp["scheduled_end_at"] + buffer
        # closed intervals: touching endpoints conflict
        if new_start <= other_end and other_start <= new_end:
            return True
    return False


def create_inspection(
    est_id, inspection_type, start, end, source_complaint_id=None
):
    rec = new_record(
        {
            "establishment_id": est_id,
            "source_complaint_id": source_complaint_id,
            "inspection_type": inspection_type,
            "status": "SCHEDULED",
            "scheduled_start_at": start,
            "scheduled_end_at": end,
            "inspector_user_id": None,
            "score": None,
            "open_violation_count_at_start": 0,
            "finalized_at": None,
        }
    )
    store.inspections[rec["id"]] = rec
    return rec
