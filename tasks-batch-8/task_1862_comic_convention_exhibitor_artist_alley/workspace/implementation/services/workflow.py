"""Cross-entity workflows: cascades, promotion sweeps, neighbor evaluation,
run-ops sweeps, eviction."""

from datetime import timedelta

import db
from services import calc

LIVE_APPLICATION_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_REVISION",
                             "JURIED_ACCEPTED", "JURIED_WAITLISTED", "CONTRACTED", "PLACED")
ACCEPTED_COUNT_STATUSES = ("JURIED_ACCEPTED", "CONTRACTED", "PLACED")


def quota_for(convention_id, category):
    for q in db.category_quotas.values():
        if q["convention_id"] == convention_id and q["category"] == category:
            return q
    return None


def moot_neighbor_requests(exhibitor_id):
    """Every PENDING NeighborRequest involving this exhibitor -> MOOT."""
    for nr in db.neighbor_requests.values():
        if nr["status"] != "PENDING":
            continue
        if nr["requester_exhibitor_id"] == exhibitor_id or nr["target_exhibitor_id"] == exhibitor_id:
            nr["status"] = "MOOT"
            db.touch(nr)


def promotion_sweep(convention_id, category):
    """Waitlist promotion: if accepted_count < max_accepted, promote exactly one
    JURIED_WAITLISTED application ordered by composite DESC, renewal_priority
    DESC, created_at ASC. Silent no-op when no candidates."""
    quota = quota_for(convention_id, category)
    if quota is None:
        return
    if quota["accepted_count"] >= quota["max_accepted"]:
        return
    candidates = [a for a in db.applications.values()
                  if a["convention_id"] == convention_id
                  and a["category"] == category
                  and a["status"] == "JURIED_WAITLISTED"]
    if not candidates:
        return

    def key(a):
        score = a.get("jury_composite_score")
        score_key = -(score if score is not None else -1)
        ex = db.exhibitors.get(a["exhibitor_id"])
        rps = ex["renewal_priority_score"] if ex else 0
        return (score_key, -rps, a["created_at"], a["id"])

    candidates.sort(key=key)
    promoted = candidates[0]
    promoted["status"] = "JURIED_ACCEPTED"
    promoted["decided_at"] = db.now_iso()
    db.touch(promoted)
    quota["waitlisted_count"] -= 1
    quota["accepted_count"] += 1
    db.touch(quota)


def _release_placement(placement):
    """Release one placement and free its space. Handles TENTATIVE (RESERVED
    space) and CONFIRMED (ASSIGNED space)."""
    if placement["status"] not in ("TENTATIVE", "CONFIRMED"):
        return
    su = db.space_units.get(placement["space_unit_id"])
    placement["status"] = "RELEASED"
    db.touch(placement)
    if su is not None and su["status"] in ("RESERVED", "ASSIGNED") \
            and su.get("current_application_id") == placement["application_id"]:
        su["status"] = "AVAILABLE"
        su["current_application_id"] = None
        db.touch(su)


def _release_application_placements(application):
    for p in list(db.placements.values()):
        if p["application_id"] == application["id"] and p["status"] in ("TENTATIVE", "CONFIRMED"):
            _release_placement(p)


def _revoke_application_badges(application):
    for sm in db.staff_members.values():
        if sm["exhibitor_id"] == application["exhibitor_id"] \
                and sm["convention_id"] == application["convention_id"] \
                and sm["badge_status"] == "ISSUED":
            sm["badge_status"] = "REVOKED"
            db.touch(sm)


def _cancel_application_freight(application):
    for fb in db.freight_bookings.values():
        if fb["application_id"] == application["id"] and fb["status"] in ("REQUESTED", "CONFIRMED"):
            fb["status"] = "CANCELLED"
            db.touch(fb)
            slot = db.load_slots.get(fb["load_slot_id"])
            if slot is not None:
                slot["reserved_pallets"] = max(0, slot["reserved_pallets"] - fb["pallet_count"])
                if slot["status"] == "FULL" and slot["reserved_pallets"] < slot["pallet_capacity"]:
                    slot["status"] = "OPEN"
                db.touch(slot)


def decline_application(application, reason_note=None):
    """JURIED_ACCEPTED -> DECLINED with the release cascade + promotion sweep.
    reason_note: OFFER_EXPIRED when fired by the run-ops expiry sweep."""
    application["status"] = "DECLINED"
    if reason_note is not None:
        application["cancellation_reason"] = reason_note
    db.touch(application)
    quota = quota_for(application["convention_id"], application["category"])
    if quota is not None and quota["accepted_count"] > 0:
        quota["accepted_count"] -= 1
        db.touch(quota)
    _release_application_placements(application)
    moot_neighbor_requests(application["exhibitor_id"])
    promotion_sweep(application["convention_id"], application["category"])


def cancel_application(application, reason):
    """CONTRACTED/PLACED -> CANCELLED. reason in {EXHIBITOR, DIRECTOR, EVICTION}.
    Eviction bypasses the refund rule with refund 0."""
    now = db.now_dt()
    convention = db.conventions.get(application["convention_id"])
    if reason == "EVICTION":
        refund = 0
    else:
        refund = calc.cancellation_refund(application["amount_paid_cents"], convention, now)
    application["status"] = "CANCELLED"
    application["cancellation_reason"] = reason
    application["refund_cents"] = refund
    db.touch(application)
    _release_application_placements(application)
    _revoke_application_badges(application)
    _cancel_application_freight(application)
    quota = quota_for(application["convention_id"], application["category"])
    if quota is not None and quota["accepted_count"] > 0:
        quota["accepted_count"] -= 1
        db.touch(quota)
    moot_neighbor_requests(application["exhibitor_id"])
    promotion_sweep(application["convention_id"], application["category"])


def eviction_cascade(exhibitor):
    """Fired when exhibitor.standing becomes EVICTED."""
    for app in list(db.applications.values()):
        if app["exhibitor_id"] == exhibitor["id"] and app["status"] in ACCEPTED_COUNT_STATUSES:
            cancel_application(app, "EVICTION")
    moot_neighbor_requests(exhibitor["id"])
    exhibitor["renewal_priority_score"] = calc.renewal_priority_score(exhibitor)


def apply_strikes(exhibitor, points):
    exhibitor["strike_points"] += points
    exhibitor["renewal_priority_score"] = calc.renewal_priority_score(exhibitor)
    new_standing = calc.standing_for(exhibitor["strike_points"])
    became_evicted = new_standing == "EVICTED" and exhibitor["standing"] != "EVICTED"
    exhibitor["standing"] = new_standing
    db.touch(exhibitor)
    if became_evicted:
        eviction_cascade(exhibitor)
        db.touch(exhibitor)


def evaluate_neighbor_requests(convention_id):
    """Placement-confirm sweep: a PENDING request is evaluated once both
    parties hold at least one CONFIRMED placement in the convention."""
    def confirmed_spaces(exhibitor_id):
        spaces = []
        for p in db.placements.values():
            if p["status"] != "CONFIRMED":
                continue
            app = db.applications.get(p["application_id"])
            if app is None or app["exhibitor_id"] != exhibitor_id or app["convention_id"] != convention_id:
                continue
            su = db.space_units.get(p["space_unit_id"])
            if su is not None:
                spaces.append(su)
        return spaces

    for nr in db.neighbor_requests.values():
        if nr["convention_id"] != convention_id or nr["status"] != "PENDING":
            continue
        req_spaces = confirmed_spaces(nr["requester_exhibitor_id"])
        tgt_spaces = confirmed_spaces(nr["target_exhibitor_id"])
        if not req_spaces or not tgt_spaces:
            continue
        adjacent = any(
            a["block"] == b["block"] and abs(a["unit_number"] - b["unit_number"]) == 1
            for a in req_spaces for b in tgt_spaces
        )
        if nr["kind"] == "ADJACENT_TO":
            nr["status"] = "HONORED" if adjacent else "DECLINED"
        else:  # AWAY_FROM
            nr["status"] = "HONORED" if not adjacent else "DECLINED"
        db.touch(nr)


# ---------------------------------------------------------------------------
# run-ops sweeps (fixed order: offers, permits, freight, slots)
# ---------------------------------------------------------------------------

def run_ops(convention):
    now = db.now_dt()
    conv_id = convention["id"]

    # 1. Offer-expiry sweep
    for app in list(db.applications.values()):
        if app["convention_id"] != conv_id or app["status"] != "JURIED_ACCEPTED":
            continue
        decided = db._parse_iso(app["decided_at"]) if app.get("decided_at") else None
        if decided is None:
            continue
        if decided + timedelta(days=convention["deposit_window_days"]) < now:
            # OFFER_EXPIRED recorded per the state machine note; the
            # transition target is DECLINED (§3.5).
            decline_application(app, reason_note="OFFER_EXPIRED")

    # 2. Permit-expiry sweep
    for app in list(db.applications.values()):
        if app["convention_id"] != conv_id:
            continue
        if app.get("permit_status") == "VERIFIED" and app.get("permit_expires_at"):
            if db._parse_iso(app["permit_expires_at"]) < now:
                app["permit_status"] = "EXPIRED"
                db.touch(app)

    # 3. Freight sweeps: CONFIRMED past slot end -> NO_SHOW (keeps capacity);
    #    CHECKED_IN past slot end -> COMPLETED (releases pallets)
    for fb in list(db.freight_bookings.values()):
        slot = db.load_slots.get(fb["load_slot_id"])
        if slot is None or slot["convention_id"] != conv_id:
            continue
        slot_end = db._parse_iso(slot["ends_at"])
        if slot_end >= now:
            continue
        if fb["status"] == "CONFIRMED":
            fb["status"] = "NO_SHOW"
            db.touch(fb)
        elif fb["status"] == "CHECKED_IN":
            fb["status"] = "COMPLETED"
            db.touch(fb)
            slot["reserved_pallets"] = max(0, slot["reserved_pallets"] - fb["pallet_count"])
            if slot["status"] == "FULL" and slot["reserved_pallets"] < slot["pallet_capacity"]:
                slot["status"] = "OPEN"
            db.touch(slot)

    # 4. Load-slot close sweep
    for slot in list(db.load_slots.values()):
        if slot["convention_id"] != conv_id:
            continue
        if slot["status"] in ("OPEN", "FULL") and db._parse_iso(slot["ends_at"]) < now:
            slot["status"] = "CLOSED"
            db.touch(slot)

    convention["ops_run_count"] = convention.get("ops_run_count", 0) + 1
    db.touch(convention)
