"""Business logic: project status recomputation, quote expiry, cascades, settlement.

These helpers mutate db records and bump version/updated_at (db.touch) on every
record they change, including parent records touched only by cascade (PRD §2.5).
"""
from db import db, touch
from clock import clock, parse_iso8601, add_days, format_iso8601
import calculations


# ---------------------------------------------------------------------------
# Reverse lookups (children of a project / quote / consultation / crew)
# ---------------------------------------------------------------------------
def consultations_of_project(pid):
    return [c for c in db.consultations.values() if c["project_id"] == pid]


def openings_of_consultation(cid):
    return [o for o in db.openings.values() if o["consultation_id"] == cid]


def quotes_of_project(pid):
    return [q for q in db.quotes.values() if q["project_id"] == pid]


def financing_of_quote(qid):
    return [f for f in db.financing_applications.values() if f["quote_id"] == qid]


def manufacture_of_project(pid):
    return [m for m in db.manufacture_orders.values() if m["project_id"] == pid]


def install_jobs_of_project(pid):
    return [j for j in db.install_jobs.values() if j["project_id"] == pid]


def install_jobs_of_crew(crew_id):
    return [j for j in db.install_jobs.values() if j["crew_id"] == crew_id]


def permits_of_project(pid):
    return [p for p in db.permits.values() if p["project_id"] == pid]


def service_tickets_of_project(pid):
    return [t for t in db.service_tickets.values() if t["project_id"] == pid]


# ---------------------------------------------------------------------------
# Quote expiry (lazy)
# ---------------------------------------------------------------------------
def expire_quote_if_due(quote):
    """Flip a SENT quote to EXPIRED if the logical clock has reached expires_at.

    Returns True if it expired (and recompute parent project status)."""
    if quote["status"] != "SENT":
        return False
    expires = parse_iso8601(quote["expires_at"]) if quote.get("expires_at") else None
    if expires is None:
        return False
    if clock.get() >= expires:
        quote["status"] = "EXPIRED"
        touch(quote)
        recompute_project_status(db.projects[quote["project_id"]])
        return True
    return False


def expire_project_quotes(project):
    for q in quotes_of_project(project["id"]):
        expire_quote_if_due(q)


def expire_all_quotes():
    for q in list(db.quotes.values()):
        expire_quote_if_due(q)


# ---------------------------------------------------------------------------
# Compound Project status recomputation
# ---------------------------------------------------------------------------
PROJECT_RANK = {
    "LEAD": 0,
    "CONSULTING": 1,
    "QUOTING": 2,
    "CONTRACTED": 3,
    "IN_PRODUCTION": 4,
    "INSTALLING": 5,
    "INSPECTION": 6,
    "COMPLETED": 7,
}


def derive_project_status(project):
    """Derive the compound status from child stages. CANCELLED is sticky and
    handled by the caller (cancel cascade sets it directly)."""
    pid = project["id"]
    if project["status"] == "CANCELLED":
        return "CANCELLED"

    # Highest reached milestone wins (monotonic forward progression).
    # COMPLETED: a permit is INSPECTION_PASSED.
    if any(p["status"] == "INSPECTION_PASSED" for p in permits_of_project(pid)):
        return "COMPLETED"
    # INSPECTION: an install job COMPLETED.
    if any(j["status"] == "COMPLETED" for j in install_jobs_of_project(pid)):
        return "INSPECTION"
    # INSTALLING: an install job EN_ROUTE.
    if any(j["status"] == "EN_ROUTE" for j in install_jobs_of_project(pid)):
        return "INSTALLING"
    # IN_PRODUCTION: a manufacture order IN_BUILD or READY.
    if any(m["status"] in ("IN_BUILD", "READY") for m in manufacture_of_project(pid)):
        return "IN_PRODUCTION"
    # CONTRACTED: a quote ACCEPTED (accepted_quote_id set).
    if project.get("accepted_quote_id"):
        return "CONTRACTED"
    # QUOTING: any quote ever reached SENT (i.e. a quote is currently in a
    # post-DRAFT state that is not part of the contracted path). The first SENT
    # advances to QUOTING; rejected/expired/superseded quotes still indicate the
    # project progressed past CONSULTING only while a live SENT quote exists.
    if any(q["status"] == "SENT" for q in quotes_of_project(pid)):
        return "QUOTING"
    # CONSULTING: any consultation exists.
    if consultations_of_project(pid):
        return "CONSULTING"
    return "LEAD"


def recompute_project_status(project):
    """Recompute compound status; bump version/updated_at only if it changed
    OR always when called as part of a cascade touch? Per PRD §2.5 a cascade
    that alters the project refreshes updated_at + version. We bump only when
    the status value actually changes to avoid spurious version churn on reads."""
    new_status = derive_project_status(project)
    if new_status != project["status"]:
        project["status"] = new_status
        touch(project)
        # Capture the COMPLETED instant (= updated_at at that moment) once, used
        # as the start of the 2-logical-year warranty window for service charges.
        if new_status == "COMPLETED":
            project["completed_at"] = project["updated_at"]
        return True
    return False


# ---------------------------------------------------------------------------
# Referral settlement / voiding
# ---------------------------------------------------------------------------
def recompute_homeowner_credit(homeowner_id):
    total = 0
    for r in db.referrals.values():
        if r["status"] != "SETTLED":
            continue
        referrer = db.projects.get(r["referrer_project_id"])
        if referrer and referrer["homeowner_id"] == homeowner_id:
            total += r["reward_amount_cents"]
    ho = db.homeowners.get(homeowner_id)
    if ho is not None and ho.get("referral_credit_cents") != total:
        ho["referral_credit_cents"] = total
        touch(ho)


def settle_referrals_for_referred_project(project):
    """When a project reaches CONTRACTED, settle PENDING referrals pointing at it."""
    accepted_quote = db.quotes.get(project.get("accepted_quote_id"))
    if accepted_quote is None:
        return
    for r in db.referrals.values():
        if r["status"] == "PENDING" and r["referred_project_id"] == project["id"]:
            r["reward_amount_cents"] = calculations.referral_reward(accepted_quote["estimate_total_cents"])
            r["status"] = "SETTLED"
            touch(r)
            referrer = db.projects.get(r["referrer_project_id"])
            if referrer is not None:
                recompute_homeowner_credit(referrer["homeowner_id"])


def void_referrals_for_referred_project(project):
    for r in db.referrals.values():
        if r["status"] == "PENDING" and r["referred_project_id"] == project["id"]:
            r["status"] = "VOID"
            touch(r)
