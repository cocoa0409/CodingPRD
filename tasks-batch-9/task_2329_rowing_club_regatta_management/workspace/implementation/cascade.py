"""Server-initiated transitions (PRD 2.10). Every touched row is mutated in its
own right: updated_at refreshed and version incremented."""
import clock
import db
import derive

LIVE_ENTRY_STATUSES = ("LINEUP_DECLARED", "SUBMITTED", "CONFIRMED")


# --------------------------------------------------------------------------- #
# Shells and sessions                                                         #
# --------------------------------------------------------------------------- #
def release_shell(shell, ignore_session_id=None):
    """ASSIGNED -> AVAILABLE once no other CLEARED/LAUNCHED session holds the hull."""
    if shell is None or shell["status"] != "ASSIGNED":
        return
    for sess in db.sessions.values():
        if sess["id"] == ignore_session_id:
            continue
        if sess["shell_id"] == shell["id"] and sess["status"] in ("CLEARED", "LAUNCHED"):
            return
    shell["status"] = "AVAILABLE"
    db.touch(shell)


def cancel_session(session):
    if session["status"] not in ("PLANNED", "CLEARED"):
        return
    was_cleared = session["status"] == "CLEARED"
    session["status"] = "CANCELLED"
    db.touch(session)
    if was_cleared:
        release_shell(db.shells.get(session["shell_id"]), ignore_session_id=session["id"])


def cancel_sessions_for_shell(shell_id):
    for sess in db.ordered(db.sessions, lambda s: s["shell_id"] == shell_id
                           and s["status"] in ("PLANNED", "CLEARED")):
        cancel_session(sess)


def cancel_sessions_for_member(member_id):
    for sess in db.ordered(db.sessions, lambda s: s["status"] in ("PLANNED", "CLEARED")
                           and member_id in derive.session_member_ids(s)):
        cancel_session(sess)


def member_on_launched_session(member_id):
    for sess in db.sessions.values():
        if sess["status"] == "LAUNCHED" and member_id in derive.session_member_ids(sess):
            return True
    return False


# --------------------------------------------------------------------------- #
# Lanes and heats                                                             #
# --------------------------------------------------------------------------- #
def void_lane(lane):
    lane["lane_status"] = "VOIDED"
    db.touch(lane)
    db.touch(db.heats.get(lane["heat_id"]))


def demote_heat(heat):
    """LANES_ASSIGNED -> SCHEDULED: the whole heat must be re-seeded."""
    if heat is None or heat["status"] != "LANES_ASSIGNED":
        return
    for lane in derive.heat_lanes(heat["id"]):
        if lane["lane_status"] == "PENDING":
            void_lane(lane)
    heat["status"] = "SCHEDULED"
    db.touch(heat)


def void_entry_pending_lanes(entry):
    heat_ids = []
    for lane in db.ordered(db.lanes, lambda l: l["regatta_entry_id"] == entry["id"]
                           and l["lane_status"] == "PENDING"):
        void_lane(lane)
        if lane["heat_id"] not in heat_ids:
            heat_ids.append(lane["heat_id"])
    for heat_id in heat_ids:
        demote_heat(db.heats.get(heat_id))


# --------------------------------------------------------------------------- #
# Entries and seats                                                           #
# --------------------------------------------------------------------------- #
def demote_entry(entry):
    """SUBMITTED -> LINEUP_DECLARED, voiding the lanes the crew was holding."""
    if entry["status"] != "SUBMITTED":
        return
    entry["status"] = "LINEUP_DECLARED"
    db.touch(entry)
    db.touch(db.regattas.get(entry["regatta_id"]))
    void_entry_pending_lanes(entry)


def entry_needs_demotion(entry):
    for seat in derive.entry_seats(entry["id"]):
        if seat["weigh_in_status"] == "FAILED":
            return True
        if seat["eligibility_status"] != "ELIGIBLE":
            return True
    return False


def apply_entry_demotion(entry):
    if entry["status"] == "SUBMITTED" and entry_needs_demotion(entry):
        demote_entry(entry)


def recompute_seat_eligibility(seat, member=None):
    member = member or db.members.get(seat["member_id"])
    if member is None:
        return
    value = derive.seat_eligibility(member, seat["seat_role"])
    if seat["eligibility_status"] != value:
        seat["eligibility_status"] = value
        db.touch(seat)


def recompute_member_seats(member):
    """Recompute eligibility on the member's seats whose entry is not terminal."""
    affected = []
    for seat in db.ordered(db.seats, lambda s: s["member_id"] == member["id"]):
        entry = db.entries.get(seat["regatta_entry_id"])
        if entry is None or entry["status"] in ("RACED", "SCRATCHED"):
            continue
        recompute_seat_eligibility(seat, member)
        if entry["id"] not in [e["id"] for e in affected]:
            affected.append(entry)
    for entry in affected:
        apply_entry_demotion(entry)


def block_member_seats_for_dues(member):
    """Delinquency hop 3 and 4."""
    affected = []
    for seat in db.ordered(db.seats, lambda s: s["member_id"] == member["id"]):
        entry = db.entries.get(seat["regatta_entry_id"])
        if entry is None or entry["status"] not in LIVE_ENTRY_STATUSES:
            continue
        if seat["eligibility_status"] != "BLOCKED_DUES":
            seat["eligibility_status"] = "BLOCKED_DUES"
            db.touch(seat)
        if entry["id"] not in [e["id"] for e in affected]:
            affected.append(entry)
    for entry in affected:
        apply_entry_demotion(entry)


def release_rack(entry):
    load = db.trailers.get(entry.get("trailer_load_id")) if entry.get("trailer_load_id") else None
    entry["trailer_load_id"] = None
    entry["rack_tier"] = None
    entry["rack_position"] = None
    db.touch(entry)
    if load is not None:
        db.touch(load)


def scratch_entry(entry, refund_cents, release_rack_units=True, void_lanes=True,
                  touch_regatta=True):
    entry["refund_cents"] = refund_cents
    entry["status"] = "SCRATCHED"
    db.touch(entry)
    if touch_regatta:
        db.touch(db.regattas.get(entry["regatta_id"]))
    if void_lanes:
        void_entry_pending_lanes(entry)
    if release_rack_units and entry.get("rack_tier") is not None:
        release_rack(entry)
    elif entry.get("trailer_load_id"):
        db.touch(db.trailers.get(entry["trailer_load_id"]))


# --------------------------------------------------------------------------- #
# Condemnation                                                                #
# --------------------------------------------------------------------------- #
def condemn_shell(shell):
    shell["status"] = "RETIRED"
    db.touch(shell)
    for entry in db.ordered(db.entries, lambda e: e["shell_id"] == shell["id"]
                            and e["status"] in ("DRAFT",) + LIVE_ENTRY_STATUSES):
        refund = entry["refund_cents"]
        if entry["status"] in ("SUBMITTED", "CONFIRMED"):
            refund = derive.scratch_refund(entry, db.regattas[entry["regatta_id"]])
        else:
            refund = 0
        scratch_entry(entry, refund)
    cancel_sessions_for_shell(shell["id"])


# --------------------------------------------------------------------------- #
# Water conditions                                                            #
# --------------------------------------------------------------------------- #
def revert_cleared_sessions(observed_at):
    for sess in db.ordered(db.sessions, lambda s: s["status"] == "CLEARED"):
        start = db.dt(sess, "planned_start_at")
        if start is None or start <= observed_at:
            continue
        sess["status"] = "PLANNED"
        sess["reading_id"] = None
        sess["required_launch_count"] = 0
        db.touch(sess)
        release_shell(db.shells.get(sess["shell_id"]), ignore_session_id=sess["id"])


# --------------------------------------------------------------------------- #
# Money                                                                       #
# --------------------------------------------------------------------------- #
def clear_member_dues_hold(member):
    """Money settling to zero drives DUES_HOLD -> ACTIVE and unblocks the seats
    that the fiscal gate had blocked."""
    if derive.dues_balance_cents(member["id"]) != 0:
        return
    if member["membership_status"] == "DUES_HOLD":
        member["membership_status"] = "ACTIVE"
        db.touch(member)
    for seat in db.ordered(db.seats, lambda s: s["member_id"] == member["id"]
                           and s["eligibility_status"] == "BLOCKED_DUES"):
        entry = db.entries.get(seat["regatta_entry_id"])
        if entry is None or entry["status"] in ("RACED", "SCRATCHED"):
            continue
        recompute_seat_eligibility(seat, member)


def now():
    return clock.now()
