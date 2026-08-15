"""Daily operations sweep — six steps in the fixed PRD §2.4 order."""
from datetime import timedelta

import db
import middleware as mw
from services import billing, supervision

CHECKIN_GRACE = timedelta(hours=72)


def run_daily_sweep():
    summary = {
        "packages_expired": 0,
        "packages_exhausted": 0,
        "checkins_missed": 0,
        "consents_expired": 0,
        "coaches_recomputed": 0,
    }
    now = db.clock

    # (1) Expire ACTIVE packages: EXPIRED when credits remain, EXHAUSTED at zero.
    for pkg in sorted(db.packages.values(), key=lambda p: (p["created_at"], p["seq"])):
        if pkg["status"] == "ACTIVE" and now >= pkg["expires_at_dt"]:
            if billing.package_credits_remaining(pkg) > 0:
                pkg["status"] = "EXPIRED"
                summary["packages_expired"] += 1
            else:
                pkg["status"] = "EXHAUSTED"
                summary["packages_exhausted"] += 1
            mw.touch(pkg)
            billing.recompute_family_plan_postures(pkg["family_id"])

    # (2) Check-ins past due_at + 72h -> MISSED (streak reset).
    for ci in sorted(db.checkins.values(), key=lambda c: (c["created_at"], c["seq"])):
        if ci["status"] == "PENDING" and now > ci["due_at_dt"] + CHECKIN_GRACE:
            ci["status"] = "MISSED"
            mw.touch(ci)
            summary["checkins_missed"] += 1
            plan = db.plans[ci["plan_id"]]
            client = db.clients[plan["client_id"]]
            client["checkin_streak"] = 0
            mw.touch(client)

    # (3) ACTIVE consents past expiry -> EXPIRED + note-seal cascade.
    for cg in sorted(db.consents.values(), key=lambda c: (c["created_at"], c["seq"])):
        if cg["status"] == "ACTIVE" and now >= cg["expires_at_dt"]:
            cg["status"] = "EXPIRED"
            mw.touch(cg)
            summary["consents_expired"] += 1
            billing.seal_notes_shared_to(cg["contact_id"])

    # (4) Coach supervision recompute (window slide).
    for coach in sorted(db.coaches.values(), key=lambda c: (c["created_at"], c["seq"])):
        before = (coach["status"], coach["active_caseload"],
                  coach["required_supervision_hours"], coach["verified_supervision_hours_30d"])
        supervision.recompute_coach(coach)
        after = (coach["status"], coach["active_caseload"],
                 coach["required_supervision_hours"], coach["verified_supervision_hours_30d"])
        summary["coaches_recomputed"] += 1
        if before != after:
            mw.touch(coach)

    # (5) Plan posture recompute.
    for plan in sorted(db.plans.values(), key=lambda p: (p["created_at"], p["seq"])):
        billing.recompute_plan_posture(plan)

    # (6) Family billing recompute.
    for fam in sorted(db.families.values(), key=lambda f: (f["created_at"], f["seq"])):
        before = (fam.get("outstanding_balance_cents"), fam.get("billing_status"))
        billing.recompute_family_billing(fam)
        if before != (fam["outstanding_balance_cents"], fam["billing_status"]):
            mw.touch(fam)

    return summary
