"""Every cascade completes inside the triggering request (PRD 2.10)."""
import calc
import derive
from store import S, now, sort_created, touch


def _sorted_granted(prequalification_id):
    rows = [
        g
        for g in derive.grants_of_prequal(prequalification_id)
        if g["status"] == "GRANTED"
    ]
    return sort_created(rows)


def revoke_grant(grant, reason):
    """Shared revocation body: every cascade revocation behaves identically and
    differs only in the reason it records."""
    grant["status"] = "REVOKED"
    grant["revocation_reason"] = reason
    grant["revoked_at"] = now()
    touch(grant)
    derive.recompute_site(S.sites[grant["site_id"]])


def expire_grant(grant):
    """Expiry leaves revoked_at null, so no cooldown window opens."""
    grant["status"] = "EXPIRED"
    touch(grant)
    derive.recompute_site(S.sites[grant["site_id"]])


def revoke_all_granted(prequalification_id, reason):
    for grant in _sorted_granted(prequalification_id):
        revoke_grant(grant, reason)


# ----------------------------------------------------------------- join --------


def evaluate_join(preq):
    """Fork-join: SUBMITTED -> UNDER_REVIEW once both dimensions are satisfied.
    Whichever request completes the last dimension performs the join."""
    if preq["status"] != "SUBMITTED":
        return False
    if derive.statistics_verification_status(preq["id"]) != "VERIFIED":
        return False
    if derive.document_review_status(preq) != "COMPLETE":
        return False
    preq["status"] = "UNDER_REVIEW"
    touch(preq)
    derive.recompute_flow_down(preq["id"])
    return True


# -------------------------------------------------- prequalification chains ----


def expire_prequal(preq):
    """Supersede and annual-expiry chain."""
    preq["status"] = "EXPIRED"
    touch(preq)
    revoke_all_granted(preq["id"], "PREQUAL_EXPIRED")
    derive.recompute_flow_down(preq["id"])
    derive.recompute_open_deficiency_count(S.contractors[preq["contractor_id"]])


def suspend_prequal(preq):
    """Incident-review freeze; conditional_expires_at is deliberately preserved."""
    preq["status"] = "SUSPENDED"
    touch(preq)
    revoke_all_granted(preq["id"], "PREQUAL_SUSPENDED")
    derive.recompute_flow_down(preq["id"])
    derive.recompute_open_deficiency_count(S.contractors[preq["contractor_id"]])


def reject_prequal_uncured(preq):
    """Requalification-run step 1: the plan closure drags the row to REJECTED.
    deficiency_codes are preserved; expires_at is nulled."""
    for plan in sort_created(derive.plans_of(preq["id"])):
        if plan["status"] in ("OPEN", "SUBMITTED"):
            plan["status"] = "OVERDUE"
            plan["closed_at"] = now()
            touch(plan)
    preq["status"] = "REJECTED"
    preq["expires_at"] = None
    touch(preq)
    revoke_all_granted(preq["id"], "PREQUAL_REJECTED")
    derive.recompute_open_deficiency_count(S.contractors[preq["contractor_id"]])
    derive.recompute_flow_down(preq["id"])


def supersede_older_standings(contractor, client_id, new_cycle_year):
    """PRD 3.2: ascending cycle_year, then ascending created_at."""
    rows = [
        p
        for p in derive.preqs_of_contractor(contractor["id"])
        if p["client_id"] == client_id
        and p["cycle_year"] < new_cycle_year
        and p["status"] in ("APPROVED", "CONDITIONAL", "SUSPENDED")
    ]
    rows.sort(key=lambda r: (r["cycle_year"], r["created_at"], r["_seq"]))
    for row in rows:
        expire_prequal(row)


# ------------------------------------------------------- incident cascades -----


def freeze_contractor(contractor, report):
    """Review flag flipped false -> true: freeze the contractor's whole active
    standing across every client, ascending created_at."""
    rows = [
        p
        for p in derive.preqs_of_contractor(contractor["id"])
        if p["status"] in ("APPROVED", "CONDITIONAL")
    ]
    for preq in sort_created(rows):
        suspend_prequal(preq)
        report["triggered_suspension_count"] += 1


def unfreeze_contractor(contractor):
    """Review flag flipped true -> false: suspended rows return to review with
    their grading wiped. The badges are deliberately NOT given back."""
    rows = [
        p for p in derive.preqs_of_contractor(contractor["id"]) if p["status"] == "SUSPENDED"
    ]
    for preq in sort_created(rows):
        preq["status"] = "UNDER_REVIEW"
        preq["grade"] = None
        preq["final_composite_score"] = None
        preq["effective_thresholds"] = None
        preq["deficiency_codes"] = []
        preq["conditional_expires_at"] = None
        preq["expires_at"] = None
        touch(preq)
        derive.recompute_flow_down(preq["id"])
    derive.recompute_open_deficiency_count(contractor)
