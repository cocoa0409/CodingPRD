"""Explicit cascades: bed holds, deferral-queue promotion, the capability
cascade and the operational capacity sweep (PRD 2.5, 2.11, 3.4, 3.8)."""
import clock
import derive
from db import base_record, db, touch

HOLD_MINUTES_ANTENATAL = 720
HOLD_MINUTES_DEFAULT = 240


def create_hold(unit, referral):
    """Create a HELD BedReservation for a referral (waterfall bed_class)."""
    committed = derive.occupied_bed_count(unit) + derive.held_bed_count(unit)
    bed_class = "STAFFED" if committed < unit["staffed_bed_target"] else "ESCALATION"
    held_at = clock.now()
    minutes = (HOLD_MINUTES_ANTENATAL
               if referral["referral_kind"] == "MATERNAL_ANTENATAL"
               else HOLD_MINUTES_DEFAULT)
    reservation = base_record()
    reservation.update({
        "unit_id": unit["id"],
        "referral_id": referral["id"],
        "bed_class": bed_class,
        "held_at": held_at,
        "expires_at": clock.plus_minutes(held_at, minutes),
        "status": "HELD",
        "released_reason": None,
    })
    db.reservations[reservation["id"]] = reservation
    return reservation


def live_hold(referral_id):
    for reservation in derive.referral_reservations(referral_id):
        if reservation["status"] == "HELD":
            return reservation
    return None


def release_hold(reservation, reason, status="RELEASED"):
    reservation["status"] = status
    reservation["released_reason"] = reason
    touch(reservation)


def runs_for_reservation(reservation_id):
    return [r for r in db.runs.values() if r["reservation_id"] == reservation_id]


def abort_run(run, reason):
    run["status"] = "ABORTED"
    run["abort_reason"] = reason
    asset = db.assets.get(run["isolette_asset_id"])
    if asset is not None:
        asset["decontamination_ready_at"] = clock.plus_minutes(
            clock.now(), run["decontamination_minutes"])
        touch(asset)
    touch(run)


# --------------------------------------------------------------------------
# Deferral-queue promotion (PRD 3.4)
# --------------------------------------------------------------------------
def promote_queue(unit, bump_version=True):
    """Drain the unit's deferral queue while committed beds remain."""
    promoted = 0
    while derive.available_bed_count(unit) >= 1:
        pool = derive.deferral_pool(unit)
        if not pool:
            break
        referral = pool[0]
        referral["status"] = "ACCEPTED"
        referral["decision_reason"] = None
        touch(referral)
        create_hold(unit, referral)
        if bump_version:
            touch(unit)
        promoted += 1
    return promoted


# --------------------------------------------------------------------------
# Capability cascade (PRD 3.8)
# --------------------------------------------------------------------------
def capability_cascade(unit):
    """Divert commitments the unit's new effective_level can no longer honour."""
    cap = derive.rank(derive.effective_level(unit))
    for referral in list(db.referrals.values()):
        if referral["receiving_unit_id"] != unit["id"]:
            continue
        if referral["status"] not in ("PENDING", "INFO_REQUESTED", "DEFERRED", "ACCEPTED"):
            continue
        if derive.rank(derive.required_level(referral)) <= cap:
            continue
        referral["status"] = "DIVERTED"
        referral["decision_reason"] = "CAPABILITY_LOST"
        touch(referral)
        hold = live_hold(referral["id"])
        if hold is not None:
            release_hold(hold, "CAPABILITY_LOST")
            for run in runs_for_reservation(hold["id"]):
                if run["status"] in derive.NON_TERMINAL_RUN_STATUSES:
                    abort_run(run, "CAPABILITY_LOST")
    for admission in list(db.admissions.values()):
        if admission["unit_id"] != unit["id"]:
            continue
        if admission["care_status"] not in ("ADMITTED", "STABILIZED"):
            continue
        if derive.rank(derive.current_care_level(admission)) <= cap:
            continue
        admission["care_status"] = "BACK_TRANSFER_REQUIRED"
        touch(admission)


def divert_open_referrals(unit, reason="CAPABILITY_LOST"):
    """Review denial: every PENDING / INFO_REQUESTED / DEFERRED referral diverts."""
    for referral in list(db.referrals.values()):
        if referral["receiving_unit_id"] != unit["id"]:
            continue
        if referral["status"] not in ("PENDING", "INFO_REQUESTED", "DEFERRED"):
            continue
        referral["status"] = "DIVERTED"
        referral["decision_reason"] = reason
        touch(referral)


# --------------------------------------------------------------------------
# Operational capacity sweep (PRD 2.5)
# --------------------------------------------------------------------------
def run_capacity_sweep(unit_id=None):
    now = clock.now()
    changed_units = {}
    touched_units = {}
    holds_expired = 0
    escalations_expired = 0
    enrollments_lapsed = 0
    referrals_promoted = 0

    def mark(uid, bed_picture):
        unit = db.units.get(uid)
        if unit is None:
            return
        touched_units[uid] = unit
        if bed_picture:
            changed_units[uid] = unit

    # Pass 1 — hold expiry
    for reservation in sorted(db.reservations.values(),
                              key=lambda r: (r["created_at"], r["_seq"])):
        if unit_id is not None and reservation["unit_id"] != unit_id:
            continue
        if reservation["status"] != "HELD":
            continue
        if reservation["expires_at"] > now:
            continue
        release_hold(reservation, "HOLD_EXPIRED", status="EXPIRED")
        holds_expired += 1
        referral = db.referrals.get(reservation["referral_id"])
        if referral is not None and referral["status"] == "ACCEPTED":
            referral["status"] = "DIVERTED"
            referral["decision_reason"] = "HOLD_EXPIRED"
            touch(referral)
        mark(reservation["unit_id"], True)

    # Pass 2 — escalation expiry
    for escalation in sorted(db.escalations.values(),
                             key=lambda e: (e["created_at"], e["_seq"])):
        if unit_id is not None and escalation["unit_id"] != unit_id:
            continue
        if escalation["status"] != "ACTIVE":
            continue
        if not escalation["effective_to"] < now:
            continue
        escalation["status"] = "EXPIRED"
        touch(escalation)
        escalations_expired += 1
        mark(escalation["unit_id"], True)

    # Pass 3 — follow-up lapse
    for enrollment in sorted(db.enrollments.values(),
                             key=lambda e: (e["created_at"], e["_seq"])):
        if enrollment["status"] != "ENROLLED":
            continue
        if enrollment.get("confirmed_appointment_date") is not None:
            continue
        if not enrollment["appointment_window_end"] < now:
            continue
        if unit_id is not None and enrollment["clinic_unit_id"] != unit_id:
            continue
        enrollment["status"] = "LOST_TO_FOLLOWUP"
        touch(enrollment)
        enrollments_lapsed += 1

    # Pass 4 — deferral-queue promotion for every unit whose bed picture moved
    for unit in list(changed_units.values()):
        referrals_promoted += promote_queue(unit, bump_version=False)

    for unit in touched_units.values():
        touch(unit)

    return {
        "holds_expired": holds_expired,
        "escalations_expired": escalations_expired,
        "enrollments_lapsed": enrollments_lapsed,
        "referrals_promoted": referrals_promoted,
        "units_touched": len(touched_units),
    }
