"""Shared entity factories, mutation helpers, and multi-entity cascades."""

from datetime import timedelta

import calc
import clock
import db
import util

LOCATION_BY_PRIOR_STATUS = {
    "REHABILITATION": "REHAB_PADDOCK",
    "ADOPTABLE": "MAIN_PASTURE",
    "ADOPTION_PENDING": "MAIN_PASTURE",
    "SANCTUARY": "SANCTUARY_PASTURE",
}


def new_entity(fields, ledger=False):
    """Base record. Ledgers (DailyHealthLog, FeedDayClose) carry only
    id + created_at; everything else also has updated_at + version."""
    now = clock.now()
    rec = {"id": util.new_id(), "created_at": now, "_seq": db.next_seq()}
    if not ledger:
        rec["updated_at"] = now
        rec["version"] = 1
    rec.update(fields)
    return rec


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = clock.now()


# --------------------------------------------------------------------------
# Sponsorship / sponsor / care-plan funding linkage
# --------------------------------------------------------------------------
def recompute_sponsor_status(sponsor_id):
    sponsor = db.sponsors.get(sponsor_id)
    if sponsor is None:
        return
    has_live = any(
        s["sponsor_id"] == sponsor_id and s["status"] in ("PLEDGED", "ACTIVE", "LAPSED")
        for s in db.sponsorships.values()
    )
    new_status = "ACTIVE" if has_live else "INACTIVE"
    if sponsor["status"] != new_status:
        sponsor["status"] = new_status
        touch(sponsor)


def active_pledge_sum(horse_id):
    return sum(
        s["monthly_pledge_cents"]
        for s in db.sponsorships.values()
        if s["horse_id"] == horse_id and s["status"] == "ACTIVE"
    )


def recompute_care_plan_coverage(horse_id):
    """Recompute funding on the horse's live (DRAFT/APPROVED) care plan."""
    for plan in db.care_plans.values():
        if plan["horse_id"] != horse_id or plan["status"] not in ("DRAFT", "APPROVED"):
            continue
        coverage = active_pledge_sum(horse_id)
        if coverage == 0:
            funding = "UNFUNDED"
        elif coverage < plan["monthly_cost_cents"]:
            funding = "PARTIALLY_FUNDED"
        else:
            funding = "FUNDED"
        if plan["funding_coverage_cents"] != coverage or plan["funding_status"] != funding:
            plan["funding_coverage_cents"] = coverage
            plan["funding_status"] = funding
            touch(plan)


# --------------------------------------------------------------------------
# Quarantine helpers
# --------------------------------------------------------------------------
def active_protocol_for(horse_id):
    for p in db.protocols.values():
        if p["horse_id"] == horse_id and p["status"] == "ACTIVE":
            return p
    return None


def create_protocol(horse_id, min_days, reason):
    rec = new_entity(
        {
            "horse_id": horse_id,
            "start_date": clock.now(),
            "min_days": min_days,
            "extension_days": 0,
            "reason": reason,
            "status": "ACTIVE",
            "cleared_at": None,
        }
    )
    db.protocols[rec["id"]] = rec
    return rec


def extend_active_protocol(horse_id, days):
    proto = active_protocol_for(horse_id)
    if proto is not None:
        proto["extension_days"] += days
        touch(proto)


# --------------------------------------------------------------------------
# Appointment cancellation cascades
# --------------------------------------------------------------------------
def cancel_appointments(where, reason):
    for appt in db.appointments.values():
        if appt["status"] in ("REQUESTED", "CONFIRMED") and where(appt):
            appt["status"] = "CANCELLED"
            appt["cancellation_reason"] = reason
            touch(appt)


# --------------------------------------------------------------------------
# Stall assignment cascade
# --------------------------------------------------------------------------
def end_active_stall_assignments(horse_id, end_dt):
    for a in db.stall_assignments.values():
        if a["horse_id"] == horse_id and a["status"] == "ACTIVE":
            a["status"] = "ENDED"
            a["end_date"] = end_dt
            touch(a)


# --------------------------------------------------------------------------
# Adoption cascades
# --------------------------------------------------------------------------
def complete_sponsorships_for_adoption(horse_id):
    for s in db.sponsorships.values():
        if s["horse_id"] != horse_id or s["status"] not in ("PLEDGED", "ACTIVE", "LAPSED"):
            continue
        was_active = s["status"] == "ACTIVE"
        s["status"] = "COMPLETED"
        s["completion_reason"] = "ADOPTED"
        touch(s)
        if was_active:
            recompute_care_plan_coverage(horse_id)
        recompute_sponsor_status(s["sponsor_id"])


def horse_adopted_cascade(horse, pickup_date):
    """Horse -> ADOPTED with stall/sponsorship cascades (shared by the
    primary horse and the bonded companion in pair adoptions)."""
    horse["status"] = "ADOPTED"
    horse["current_location"] = "OFFSITE_ADOPTED"
    horse["active_application_id"] = None
    touch(horse)
    end_active_stall_assignments(horse["id"], pickup_date)
    complete_sponsorships_for_adoption(horse["id"])


def reject_competing_applications(horse_id, except_app_id):
    for app in db.applications.values():
        if app["id"] == except_app_id or app["horse_id"] != horse_id:
            continue
        if app["status"] in ("SUBMITTED", "UNDER_REVIEW", "HOME_CHECK_SCHEDULED", "HOME_CHECK_PASSED"):
            app["status"] = "REJECTED"
            app["decision_reason"] = "SUPERSEDED_BY_FINALIZED_ADOPTION"
            touch(app)


def create_follow_ups(app):
    for visit_type, days in (("DAY_30", 30), ("DAY_90", 90), ("DAY_180", 180)):
        rec = new_entity(
            {
                "application_id": app["id"],
                "visit_type": visit_type,
                "scheduled_date": app["finalized_at"] + timedelta(days=days),
                "status": "SCHEDULED",
                "outcome": None,
                "completed_at": None,
                "findings": None,
            }
        )
        db.follow_ups[rec["id"]] = rec


def adoption_finalize_cascade(app):
    horse = db.horses[app["horse_id"]]
    horse_adopted_cascade(horse, app["proposed_pickup_date"])
    if app["adopt_with_bonded_companion"] and horse["bonded_companion_id"]:
        companion = db.horses.get(horse["bonded_companion_id"])
        if companion is not None and companion["status"] == "ADOPTABLE":
            horse_adopted_cascade(companion, app["proposed_pickup_date"])
    reject_competing_applications(horse["id"], app["id"])
    create_follow_ups(app)


def return_cascade(app):
    """Failed follow-up: FINALIZED -> RETURN_COMPLETED, horse return,
    auto-quarantine, remaining visits cancelled."""
    now = clock.now()
    if now <= app["finalized_at"] + timedelta(days=90):
        app["refund_cents"] = calc.rhu_int(calc.D(app["final_fee_cents"]) * calc.D("0.5"))
    else:
        app["refund_cents"] = calc.rhu_int(calc.D(app["final_fee_cents"]) * calc.D("0.25"))
    app["decision_reason"] = "RETURNED_AFTER_FAILED_FOLLOW_UP"
    app["status"] = "RETURN_COMPLETED"
    touch(app)

    horse = db.horses[app["horse_id"]]
    horse["status"] = "REHABILITATION"
    horse["current_location"] = "QUARANTINE_STALL"
    touch(horse)
    create_protocol(horse["id"], 14, "AUTO_RETURN")

    for v in db.follow_ups.values():
        if v["application_id"] == app["id"] and v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            touch(v)


# --------------------------------------------------------------------------
# End-of-life cascades
# --------------------------------------------------------------------------
def horse_eol_restore(horse):
    prior = horse["prior_status"]
    horse["status"] = prior
    horse["prior_status"] = None
    horse["current_location"] = LOCATION_BY_PRIOR_STATUS.get(prior, horse["current_location"])
    touch(horse)


def cancel_sponsorships_for_death(horse_id):
    for s in db.sponsorships.values():
        if s["horse_id"] != horse_id or s["status"] not in ("PLEDGED", "ACTIVE", "LAPSED"):
            continue
        was_active = s["status"] == "ACTIVE"
        s["status"] = "CANCELLED"
        s["cancellation_reason"] = "HORSE_DECEASED"
        touch(s)
        if was_active:
            recompute_care_plan_coverage(horse_id)
        recompute_sponsor_status(s["sponsor_id"])


def close_care_plans_for_death(horse_id):
    for plan in db.care_plans.values():
        if plan["horse_id"] == horse_id and plan["status"] in ("DRAFT", "APPROVED"):
            plan["status"] = "CLOSED"
            touch(plan)


def horse_deceased_cascade(horse):
    now = clock.now()
    horse["status"] = "DECEASED"
    horse["prior_status"] = None
    horse["current_location"] = "NOT_APPLICABLE"
    touch(horse)
    cancel_sponsorships_for_death(horse["id"])
    close_care_plans_for_death(horse["id"])
    cancel_appointments(
        lambda a: a["horse_id"] == horse["id"], "HORSE_DECEASED"
    )
    end_active_stall_assignments(horse["id"], now)


def requarantine_appointment_cascade(horse_id):
    cancel_appointments(
        lambda a: a["horse_id"] == horse_id, "QUARANTINE_REENTRY"
    )


def practitioner_deactivation_cascade(practitioner_id):
    cancel_appointments(
        lambda a: a["practitioner_id"] == practitioner_id, "PRACTITIONER_INACTIVE"
    )
