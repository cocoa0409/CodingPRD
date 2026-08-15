"""Cross-aggregate cascades (PRD §2.7) and shared workflow helpers.

Every cascade hop independently mutates the affected resource: updated_at is
refreshed and version incremented per hop.
"""

from datetime import timedelta

from core import db, now_dt, now_iso, touch

MISSION_TERMINAL = {"COMPLETED", "ABORTED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Ground coordination indicator (Mission.ground_coordination_status)
# ---------------------------------------------------------------------------


def compute_ground_coordination(mission_id):
    legs = [l for l in db.ground_legs.values() if l["mission_id"] == mission_id]
    legs.sort(key=lambda l: (l["_created_dt"], l["_seq"]))
    # NEEDS_REPLAN: a CANCELLED DESTINATION leg exists with no later-created
    # non-CANCELLED DESTINATION leg.
    dest_legs = [l for l in legs if l["leg_type"] == "DESTINATION"]
    for leg in dest_legs:
        if leg["status"] == "CANCELLED":
            later_ok = any(
                l["leg_type"] == "DESTINATION" and l["status"] != "CANCELLED"
                and (l["_created_dt"], l["_seq"]) > (leg["_created_dt"], leg["_seq"])
                for l in legs
            )
            if not later_ok:
                return "NEEDS_REPLAN"
    # PENDING: any non-CANCELLED leg not yet COMPLETED.
    if any(l["status"] != "CANCELLED" and l["status"] != "COMPLETED" for l in legs):
        return "PENDING"
    return "COORDINATED"


def recompute_ground_coordination(mission, touch_if_changed=True):
    new_val = compute_ground_coordination(mission["id"])
    if new_val != mission["ground_coordination_status"]:
        mission["ground_coordination_status"] = new_val
        if touch_if_changed:
            touch(mission)


# ---------------------------------------------------------------------------
# Aircraft release: returns to AVAILABLE only when the LAST non-terminal
# mission bound to the tail resolves (PRD §3.5).
# ---------------------------------------------------------------------------


def release_aircraft_if_last(aircraft_id):
    aircraft = db.aircraft.get(aircraft_id)
    if aircraft is None:
        return
    others_open = any(
        m["aircraft_id"] == aircraft_id and m["status"] not in MISSION_TERMINAL
        for m in db.missions.values()
    )
    if not others_open and aircraft["status"] == "ASSIGNED":
        aircraft["status"] = "AVAILABLE"
        touch(aircraft)


# ---------------------------------------------------------------------------
# Ground leg cancellation (shared by manual cancel, divert hop 2, abort)
# ---------------------------------------------------------------------------


def cancel_ground_leg(leg):
    """Move a SCHEDULED/ENROUTE leg to CANCELLED and release its linked bed
    when it is a DESTINATION leg whose bed is still HELD/CONFIRMED."""
    leg["status"] = "CANCELLED"
    touch(leg)
    if leg["leg_type"] == "DESTINATION" and leg.get("bed_reservation_id"):
        bed = db.bed_reservations.get(leg["bed_reservation_id"])
        if bed is not None and bed["status"] in {"HELD", "CONFIRMED"}:
            bed["status"] = "RELEASED"
            touch(bed)


# ---------------------------------------------------------------------------
# Mission teardown cascade (abort / cancel — PRD §3.5)
# ---------------------------------------------------------------------------


def mission_teardown_cascade(mission):
    # Crew assignments ASSIGNED -> RELEASED
    for a in db.crew_assignments.values():
        if a["mission_id"] == mission["id"] and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            touch(a)
    # Ground legs SCHEDULED/ENROUTE -> CANCELLED; hop 2 releases linked beds
    legs = [l for l in db.ground_legs.values()
            if l["mission_id"] == mission["id"] and l["status"] in {"SCHEDULED", "ENROUTE"}]
    legs.sort(key=lambda l: (l["_created_dt"], l["_seq"]))
    for leg in legs:
        cancel_ground_leg(leg)
    # Aircraft returns to service only when it is the last open booking
    release_aircraft_if_last(mission["aircraft_id"])
    # Ground coordination recomputed (mission already mutating; set in place)
    mission["ground_coordination_status"] = compute_ground_coordination(mission["id"])


# ---------------------------------------------------------------------------
# Mission completion cascade (PRD §3.5)
# ---------------------------------------------------------------------------


def mission_completion_cascade(mission):
    for a in db.crew_assignments.values():
        if a["mission_id"] == mission["id"] and a["status"] == "ASSIGNED":
            a["status"] = "COMPLETED"
            touch(a)
    for bed in db.bed_reservations.values():
        if bed["mission_id"] == mission["id"] and bed["status"] in {"HELD", "CONFIRMED"}:
            bed["status"] = "CONSUMED"
            touch(bed)
    release_aircraft_if_last(mission["aircraft_id"])
    mission["ground_coordination_status"] = compute_ground_coordination(mission["id"])


# ---------------------------------------------------------------------------
# Divert cascade (PRD §3.5, three hops)
# ---------------------------------------------------------------------------


def divert_cascade(mission, new_destination_facility):
    # Hop 1: release mismatched beds still HELD/CONFIRMED
    released_bed_ids = set()
    for bed in db.bed_reservations.values():
        if (bed["mission_id"] == mission["id"]
                and bed["facility_name"] != new_destination_facility
                and bed["status"] in {"HELD", "CONFIRMED"}):
            bed["status"] = "RELEASED"
            touch(bed)
            released_bed_ids.add(bed["id"])
    # Hop 2: cancel legs pointing at beds released in hop 1
    for leg in db.ground_legs.values():
        if (leg["mission_id"] == mission["id"]
                and leg.get("bed_reservation_id") in released_bed_ids
                and leg["status"] in {"SCHEDULED", "ENROUTE"}):
            leg["status"] = "CANCELLED"
            touch(leg)
    # Hop 3: recompute the indicator (mission itself is being mutated by the
    # divert, so assign in place — the mission touch happens once per request)
    mission["ground_coordination_status"] = compute_ground_coordination(mission["id"])


# ---------------------------------------------------------------------------
# Repatriation document validity (verify + launch-gate revalidation)
# ---------------------------------------------------------------------------

DOC_TYPES = {"PASSPORT", "VISA", "FIT_TO_FLY", "CUSTOMS_PRECLEARANCE"}


def _latest_docs_by_type(case):
    latest = {}
    for idx, doc in enumerate(case["documents"]):
        latest[doc["doc_type"]] = doc  # last appended wins (renewal = append)
    return latest


def documents_valid(case):
    """True iff the latest PASSPORT/VISA entries are unexpired (expires_iso
    strictly later than logical now) and the latest FIT_TO_FLY was issued no
    more than 72h ago (exactly 72h passes). Missing required entries count as
    *complete* here — completeness is a separate check."""
    now = now_dt()
    latest = _latest_docs_by_type(case)
    for dtype in ("PASSPORT", "VISA"):
        doc = latest.get(dtype)
        if doc is not None:
            exp = doc.get("_expires_dt")
            if exp is None or not (exp > now):
                return False
    ftf = latest.get("FIT_TO_FLY")
    if ftf is not None:
        issued = ftf.get("_issued_dt")
        if issued is None or (now - issued) > timedelta(hours=72):
            return False
    return True


def documents_complete(case):
    present = {d["doc_type"] for d in case["documents"]}
    return DOC_TYPES.issubset(present)


# ---------------------------------------------------------------------------
# Invoice ledger waterfall (C6)
# ---------------------------------------------------------------------------


def recompute_patient_responsibility(invoice):
    invoice["patient_responsibility_cents"] = (
        invoice["final_total_cents"]
        - invoice["insurer_paid_cents"]
        - invoice["contractual_adjustment_cents"]
        - invoice["member_writeoff_cents"]
    )
