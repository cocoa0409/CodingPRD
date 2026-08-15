"""Logical clock and the pinned four-step daily sweep (PRD sections 2.4, 3.9)."""
from flask import Blueprint

from db import db
from middleware import require_roles
from response import ok_object
from services import derived
from services.case_ops import close_case
from services.common import delete_waitlist_entry_for, touch
from validators import body, check_allowed, parse_iso_datetime, req_str  # noqa: F401

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(["ProgramDirector"])
def set_clock():
    b = body()
    check_allowed(b, ["to_iso8601"])
    db.clock = parse_iso_datetime(b.get("to_iso8601"))
    return ok_object({})


@bp.route("/ops/run-daily-sweep", methods=["POST"])
@require_roles(["ProgramDirector"])
def run_daily_sweep():
    b = body()
    check_allowed(b, [])
    current = db.clock

    # Step 1: conflict-check expiry (CLEAR/WAIVED with valid_until < now).
    expired_checks = 0
    for check in db.conflict_checks.values():
        if (check["result"] in ("CLEAR", "WAIVED")
                and check["valid_until"] < current):
            check["result"] = "EXPIRED"
            touch(check)
            expired_checks += 1

    # Step 2: referral expiry (OFFERED with response_deadline < now).
    expired_referrals = 0
    for ref in db.referrals.values():
        if ref["status"] == "OFFERED" and ref["response_deadline"] < current:
            ref["status"] = "EXPIRED"
            touch(ref)
            expired_referrals += 1

    # Step 3: advice auto-close (ADVICE_ONLY, OPEN, advice_deadline < now).
    # Full close side effects fire; ADMINISTRATIVE is non-billable so grant
    # reservations are released.
    auto_closed = 0
    for case in list(db.cases.values()):
        if (case["service_level"] == "ADVICE_ONLY"
                and case["status"] == "OPEN"
                and case["advice_deadline"] is not None
                and case["advice_deadline"] < current):
            close_case(case, "ADMINISTRATIVE", "ADVICE_WINDOW_EXPIRED")
            auto_closed += 1

    # Step 4: waitlist promotion waterfall against post-step-3 capacity.
    promoted = 0
    pool = derived.active_attorney_pool()
    entries = sorted(db.waitlist_entries.values(),
                     key=lambda e: (-e["priority_score_snapshot"],
                                    e["created_at"], e["_seq"]))
    for entry in entries:
        if entry["required_weight"] <= pool:
            app = db.applications.get(entry["application_id"])
            if app is not None and app["status"] == "WAITLISTED":
                app["status"] = "ELIGIBLE"
                app["promoted_from_waitlist"] = True
                touch(app)
            delete_waitlist_entry_for(entry["application_id"])
            pool -= entry["required_weight"]
            promoted += 1
        # No head-of-line blocking: entries that do not fit are skipped.

    return ok_object({
        "expired_conflict_checks": expired_checks,
        "expired_referrals": expired_referrals,
        "auto_closed_cases": auto_closed,
        "promoted_applications": promoted,
    })
