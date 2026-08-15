"""Workshop enrollment billing waterfall, drops, refunds, waitlist promotion."""
from datetime import timedelta

import db
import middleware as mw
from services import billing

WORKSHOP_REFUND_WINDOW_DAYS = 7


def select_group_package(family_id):
    candidates = [
        p for p in db.packages.values()
        if p["family_id"] == family_id and p["track"] == "GROUP" and p["status"] == "ACTIVE"
        and (p["credits_total"] - p["credits_consumed"] - p["credits_forfeited"]) >= 1
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["expires_at_dt"], p["created_at"], p["seq"]))
    return candidates[0]


def apply_enrollment_billing(enr, workshop, family_id):
    """Waterfall: GROUP package credit first, else money charge."""
    pkg = select_group_package(family_id)
    if pkg is not None:
        enr["billing_source"] = "PACKAGE_CREDIT"
        enr["charged_cents"] = 0
        enr["package_id"] = pkg["id"]
        pkg["credits_consumed"] += 1
        mw.touch(pkg)
        billing.recompute_package_status(pkg)
    else:
        enr["billing_source"] = "MONEY"
        enr["charged_cents"] = workshop["price_cents"]
        enr["package_id"] = None
        fam = db.families[family_id]
        billing.charge_family(fam, workshop["price_cents"])
        mw.touch(fam)


def renumber_waitlist(workshop_id):
    waitlisted = [
        e for e in db.enrollments.values()
        if e["workshop_id"] == workshop_id and e["status"] == "WAITLISTED"
    ]
    waitlisted.sort(key=lambda e: (e["created_at"], e["seq"]))
    for idx, e in enumerate(waitlisted, start=1):
        if e["waitlist_position"] != idx:
            e["waitlist_position"] = idx
            mw.touch(e)


def promote_waitlist_head(workshop):
    head_candidates = [
        e for e in db.enrollments.values()
        if e["workshop_id"] == workshop["id"] and e["status"] == "WAITLISTED"
    ]
    if not head_candidates:
        return
    head_candidates.sort(key=lambda e: (e["created_at"], e["seq"]))
    head = head_candidates[0]
    head["status"] = "ENROLLED"
    head["waitlist_position"] = None
    client = db.clients[head["client_id"]]
    apply_enrollment_billing(head, workshop, client["family_id"])
    mw.touch(head)
    workshop["seats_taken"] += 1
    renumber_waitlist(workshop["id"])


def refund_enrollment(enr, workshop, honor_money_window):
    """Refund/return an ENROLLED enrollment's billing. Sets status REFUNDED."""
    client = db.clients[enr["client_id"]]
    fam = db.families[client["family_id"]]
    if enr["billing_source"] == "MONEY":
        do_refund = True
        if honor_money_window:
            do_refund = db.clock <= workshop["window_start_dt"] - timedelta(days=WORKSHOP_REFUND_WINDOW_DAYS)
        if do_refund and enr["charged_cents"] > 0:
            billing.refund_family(fam, enr["charged_cents"])
            mw.touch(fam)
    elif enr["billing_source"] == "PACKAGE_CREDIT":
        pkg = db.packages.get(enr["package_id"])
        # Credit returns apply to ACTIVE and EXHAUSTED packages (revival path);
        # EXPIRED / REFUNDED packages yield no compensation.
        if pkg is not None and pkg["status"] in ("ACTIVE", "EXHAUSTED"):
            pkg["credits_consumed"] -= 1
            mw.touch(pkg)
            billing.recompute_package_status(pkg)
    enr["status"] = "REFUNDED"
    enr["waitlist_position"] = None
    mw.touch(enr)
