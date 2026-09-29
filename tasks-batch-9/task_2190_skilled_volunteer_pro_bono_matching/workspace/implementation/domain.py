"""Cascades and state-machine side effects (PRD 3.1 - 3.9)."""
from datetime import timedelta
from decimal import Decimal

import calc
import config as C
import store as S
from calc import dec, rnd


# --------------------------------------------------------------------------- #
# scope revisions
# --------------------------------------------------------------------------- #
def supersede_approved_revision(req):
    for scope in S.where("scope_definitions", project_request_id=req["id"]):
        if scope["status"] == "APPROVED":
            scope["status"] = "SUPERSEDED"
            S.touch(scope)


def withdraw_draft_revisions(req, keep_id=None):
    for scope in S.where("scope_definitions", project_request_id=req["id"]):
        if scope["id"] == keep_id:
            continue
        if scope["status"] == "DRAFT":
            scope["status"] = "WITHDRAWN"
            S.touch(scope)


def stamp_forced_rescope_result(req, revision_no):
    """A VOIDED escalated change request records the revision the forced
    re-scope produced; it stays null when no re-scope ever followed."""
    engagement_ids = {
        e["id"]
        for e in S.all_rows("engagements")
        if e["project_request_id"] == req["id"]
    }
    for scr in S.all_rows("scope_change_requests"):
        if (
            scr["engagement_id"] in engagement_ids
            and scr["status"] == "VOIDED"
            and scr["decision_tier"] == "RESCOPE_REQUIRED"
            and scr["resulting_scope_revision_no"] is None
        ):
            scr["resulting_scope_revision_no"] = revision_no
            S.touch(scr)


# --------------------------------------------------------------------------- #
# offer releases and the three request branches (PRD 3.5)
# --------------------------------------------------------------------------- #
def release_offer(offer, new_status, decline_reason=None, withdraw_reason=None,
                  bump_failed=True):
    """Move an OFFERED offer to a terminal status; hours and slots are derived
    from live rows, so they are released by this very transition."""
    offer["status"] = new_status
    offer["responded_at"] = S.now()
    if decline_reason is not None:
        offer["decline_reason"] = decline_reason
    if withdraw_reason is not None:
        offer["withdraw_reason"] = withdraw_reason
    S.touch(offer)
    req = S.get("project_requests", offer["project_request_id"])
    if req is not None:
        resolve_request_after_release(req, bump_failed)
    return offer


def resolve_request_after_release(req, bump_failed=True):
    if req["status"] != "MATCHING":
        return req
    candidate = int(req["failed_match_rounds"]) + 1
    if candidate < C.MAX_FAILED_MATCH_ROUNDS:
        req["status"] = "SCOPED"
        if bump_failed:
            req["failed_match_rounds"] = candidate
    elif int(req["rescope_count"]) < C.MAX_RESCOPES:
        req["status"] = "RESCOPING"
        req["failed_match_rounds"] = 0
        req["rescope_count"] = int(req["rescope_count"]) + 1
        supersede_approved_revision(req)
    else:
        req["status"] = "ABANDONED"
        req["closed_at"] = S.now()
        if bump_failed:
            req["failed_match_rounds"] = candidate
        supersede_approved_revision(req)
    S.touch(req)
    return req


def withdraw_open_offers_of_request(req, reason, bump_failed=False):
    for offer in S.where("match_offers", project_request_id=req["id"]):
        if offer["status"] == "OFFERED":
            release_offer(
                offer, "WITHDRAWN", withdraw_reason=reason, bump_failed=bump_failed
            )


def withdraw_open_offers_of_volunteer(volunteer_id, reason, bump_failed=True):
    for offer in S.all_rows("match_offers"):
        if offer["volunteer_id"] == volunteer_id and offer["status"] == "OFFERED":
            release_offer(
                offer, "WITHDRAWN", withdraw_reason=reason, bump_failed=bump_failed
            )


def withdraw_frozen_cycle_offers(cycle_id, exclude_request_id):
    for offer in S.all_rows("match_offers"):
        if offer["status"] != "OFFERED":
            continue
        req = S.get("project_requests", offer["project_request_id"])
        if req is None or req["cycle_id"] != cycle_id:
            continue
        if req["id"] == exclude_request_id:
            continue
        release_offer(
            offer, "WITHDRAWN", withdraw_reason="CYCLE_FROZEN", bump_failed=True
        )


# --------------------------------------------------------------------------- #
# milestones
# --------------------------------------------------------------------------- #
def waive_scheduled_milestones(engagement_id, reason):
    for milestone in S.where("milestones", engagement_id=engagement_id):
        if milestone["checkin_status"] == "SCHEDULED":
            milestone["checkin_status"] = "WAIVED"
            milestone["waiver_reason"] = reason
            S.touch(milestone)


def waive_milestones_of_request(req, reason):
    for eng in S.all_rows("engagements"):
        if eng["project_request_id"] != req["id"]:
            continue
        if eng["work_status"] not in C.LIVE_WORK_STATUSES:
            continue
        waive_scheduled_milestones(eng["id"], reason)


# --------------------------------------------------------------------------- #
# valuation
# --------------------------------------------------------------------------- #
def post_valuation_record(engagement, volunteer, method, variant_label):
    amounts = calc.valuation_amounts(engagement, volunteer, method)
    sequence_no = 1
    for rec in S.where("valuation_records", engagement_id=engagement["id"]):
        if rec["method"] == method:
            sequence_no = max(sequence_no, int(rec["sequence_no"]) + 1)
    row = {
        "engagement_id": engagement["id"],
        "method": method,
        "sequence_no": sequence_no,
        "hours_included": amounts["hours_included"],
        "rate_applied_usd": amounts["rate_applied_usd"],
        "base_amount_usd": amounts["base_amount_usd"],
        "admin_overhead_usd": amounts["admin_overhead_usd"],
        "total_amount_usd": amounts["total_amount_usd"],
        "variant_label": variant_label,
        "superseded_at": None,
        "posted_at": S.now(),
    }
    return S.insert("valuation_records", row)


def supersede_records(engagement_id, method=None):
    for rec in S.where("valuation_records", engagement_id=engagement_id):
        if method is not None and rec["method"] != method:
            continue
        if rec["superseded_at"] is None:
            rec["superseded_at"] = S.now()
            S.touch(rec)


def restate_valuation(engagement):
    """Termination compensation: supersede live records and post a RESTATED one."""
    live = [
        r
        for r in S.where("valuation_records", engagement_id=engagement["id"])
        if r["superseded_at"] is None
    ]
    if not live:
        return False
    if engagement["valuation_status"] not in ("PROVISIONAL", "FINAL"):
        return False
    supersede_records(engagement["id"])
    volunteer = S.get("volunteers", engagement["volunteer_id"])
    post_valuation_record(engagement, volunteer, "INDEPENDENT_SECTOR", "RESTATED")
    engagement["valuation_status"] = "RESTATED"
    return True


# --------------------------------------------------------------------------- #
# reliability and the auto-pause threshold
# --------------------------------------------------------------------------- #
def refresh_reliability(volunteer):
    """Rerun both variants and apply the floor consequence."""
    if volunteer is None:
        return
    decay, lifetime = calc.reliability(volunteer["id"])
    volunteer["reliability_score"] = decay
    volunteer["reliability_score_lifetime"] = lifetime
    if decay < C.RELIABILITY_FLOOR and volunteer["status"] == "ACTIVE":
        volunteer["status"] = "PAUSED"
        volunteer["pause_reason"] = "RELIABILITY_FLOOR"
        S.touch(volunteer)
        withdraw_open_offers_of_volunteer(
            volunteer["id"], "VOLUNTEER_PAUSED", bump_failed=True
        )


# --------------------------------------------------------------------------- #
# termination (PRD 3.9)
# --------------------------------------------------------------------------- #
def terminate_engagement(engagement, reason):
    engagement["work_status"] = "TERMINATED"
    engagement["terminated_at"] = S.now()
    engagement["termination_reason"] = reason
    S.touch(engagement)

    waive_scheduled_milestones(engagement["id"], "ENGAGEMENT_TERMINATED")

    for scr in S.where("scope_change_requests", engagement_id=engagement["id"]):
        if scr["status"] in ("PENDING", "ESCALATED"):
            scr["status"] = "VOIDED"
            S.touch(scr)

    for agreement in S.where("agreements", engagement_id=engagement["id"]):
        if agreement["status"] in ("DRAFTED", "SENT", "COUNTERED"):
            agreement["status"] = "VOIDED"
            agreement["void_reason"] = "ENGAGEMENT_TERMINATED"
            S.touch(agreement)

    restate_valuation(engagement)

    volunteer = S.get("volunteers", engagement["volunteer_id"])
    refresh_reliability(volunteer)

    req = S.get("project_requests", engagement["project_request_id"])
    if req is not None and reason in ("QUALITY_FAILURE", "AGREEMENT_VOIDED"):
        live = [
            e
            for e in S.all_rows("engagements")
            if e["project_request_id"] == req["id"]
            and e["work_status"] in C.LIVE_WORK_STATUSES
        ]
        if (
            not live
            and int(req["rescope_count"]) >= C.MAX_RESCOPES
            and req["status"] == "IN_DELIVERY"
        ):
            req["status"] = "ABANDONED"
            req["closed_at"] = S.now()
            S.touch(req)
    return engagement


# --------------------------------------------------------------------------- #
# partner standing (PRD 3.1 and 3.9)
# --------------------------------------------------------------------------- #
def suspend_partner(partner):
    partner["status"] = "SUSPENDED"
    partner["suspended_at"] = S.now()
    S.touch(partner)

    for req in S.where("project_requests", partner_org_id=partner["id"]):
        if req["status"] in ("DRAFT", "SCOPING", "SCOPED", "MATCHING", "RESCOPING"):
            req["status"] = "ABANDONED"
            req["closed_at"] = S.now()
            S.touch(req)
            withdraw_open_offers_of_request(
                req, "PARTNER_SUSPENDED", bump_failed=False
            )

    for eng in S.all_rows("engagements"):
        if eng["work_status"] not in C.LIVE_WORK_STATUSES:
            continue
        req = S.get("project_requests", eng["project_request_id"])
        if req is not None and req["partner_org_id"] == partner["id"]:
            terminate_engagement(eng, "PARTNER_SUSPENDED")


def rebuild_satisfaction(partner):
    pool = calc.satisfaction_pool(partner["id"])
    used = pool[: C.SATISFACTION_SAMPLE_MAX]
    used_ids = {s["id"] for s in used}
    for survey in S.where("satisfaction_surveys", partner_org_id=partner["id"]):
        survey["counted_in_index"] = survey["id"] in used_ids
    partner["satisfaction_sample_size"] = len(used)
    partner["satisfaction_index"] = calc.satisfaction_index(used)
    S.touch(partner)

    sample = len(used)
    index = partner["satisfaction_index"]
    if sample >= C.PROBATION_MIN_SAMPLE and index is not None:
        if index < C.PROBATION_CEILING and partner["status"] == "ACTIVE":
            partner["status"] = "PROBATION"
            partner["probation_reason"] = "LOW_SATISFACTION"
            S.touch(partner)
        elif index >= C.RECOVERY_FLOOR and partner["status"] == "PROBATION":
            partner["status"] = "ACTIVE"
            partner["probation_reason"] = None
            S.touch(partner)


# --------------------------------------------------------------------------- #
# the cycle checkpoint (PRD 3.1)
# --------------------------------------------------------------------------- #
def recalculate_cycle(cycle):
    clock = S.now()

    # 1. expiry sweep
    for offer in list(S.all_rows("match_offers")):
        if offer["status"] != "OFFERED":
            continue
        req = S.get("project_requests", offer["project_request_id"])
        if req is None or req["cycle_id"] != cycle["id"]:
            continue
        if offer["expires_at"] <= clock:
            release_offer(offer, "EXPIRED", bump_failed=True)

    # 2. neglected check-ins
    for eng in list(calc.cycle_engagements(cycle["id"])):
        if eng["work_status"] != "IN_PROGRESS":
            continue
        missed_any = False
        for milestone in S.where("milestones", engagement_id=eng["id"]):
            if milestone["checkin_status"] != "SCHEDULED":
                continue
            if milestone["due_at"] + timedelta(hours=C.MILESTONE_GRACE_HOURS) < clock:
                milestone["checkin_status"] = "MISSED"
                S.touch(milestone)
                missed_any = True
        if missed_any:
            S.touch(eng)
            volunteer = S.get("volunteers", eng["volunteer_id"])
            refresh_reliability(volunteer)
            if (
                calc.engagement_missed_checkins(eng["id"])
                >= C.MISSED_CHECKIN_TERMINATION_THRESHOLD
                and eng["work_status"] in C.LIVE_WORK_STATUSES
            ):
                terminate_engagement(eng, "ADMIN")

    # 3. capacity figures
    cycle["last_recalculated_at"] = clock
    cycle["recalc_epoch"] = int(cycle["recalc_epoch"]) + 1
    S.touch(cycle)
    return cycle
