"""Computed-field recomputation, state bubbling and multi-hop cascades."""

import calc
import enums as E
import queries as Q
from db import new_row, now, plus_days, set_fields, store, touch

SYSTEM = "SYSTEM"
LIVE_SESSION_STATES = ("SCHEDULED", "IN_PROGRESS")


# ------------------------------------------------------------------ laboratory

def recompute_lab_minutes(lab):
    total = sum(s["reserved_minutes"] for s in Q.sessions_for_lab(lab["id"])
                if s["state"] in LIVE_SESSION_STATES)
    set_fields(lab, reserved_bench_minutes=total)


def cancel_session(session):
    if session["state"] not in LIVE_SESSION_STATES:
        return
    set_fields(session, state="CANCELLED")
    lab = store.laboratories.get(session["laboratory_id"])
    if lab is not None:
        recompute_lab_minutes(lab)


# ------------------------------------------------------------------- test plan

def void_plan(plan, reason):
    if plan["state"] == "VOIDED":
        return
    set_fields(plan, state="VOIDED", voided_reason=reason)
    for session in Q.sessions_for_plan(plan["id"]):
        cancel_session(session)


def plan_progress_after_completion(plan):
    """PRD 3.5: IN_EXECUTION -> COMPLETE when the plan has nothing live left,
    at least one COMPLETE session, and full mandatory result coverage."""
    if plan["state"] != "IN_EXECUTION":
        return
    sessions = Q.sessions_for_plan(plan["id"])
    if any(s["state"] in LIVE_SESSION_STATES for s in sessions):
        return
    completed = [s for s in sessions if s["state"] == "COMPLETE"]
    if not completed:
        return
    covered = set()
    for session in completed:
        for line in session["result_lines"]:
            covered.add(line["feature_set_id"])
    for fs_id in plan["included_feature_set_ids"]:
        fs = store.feature_sets.get(fs_id)
        if fs is None:
            continue
        if fs["obligation"] in ("MANDATORY", "CONDITIONAL") and fs_id not in covered:
            return
    set_fields(plan, state="COMPLETE")


def mandatory_coverage_complete(plan):
    covered = set()
    for session in Q.sessions_for_plan(plan["id"]):
        if session["state"] != "COMPLETE":
            continue
        for line in session["result_lines"]:
            covered.add(line["feature_set_id"])
    for fs_id in plan["included_feature_set_ids"]:
        fs = store.feature_sets.get(fs_id)
        if fs is None:
            continue
        if fs["obligation"] in ("MANDATORY", "CONDITIONAL") and fs_id not in covered:
            return False
    return True


# ---------------------------------------------------------------------- member

def recompute_member(member):
    escrowed = calc.member_escrow_cents(member["id"])
    balance = member["credits_purchased_cents"] - member["credits_consumed_cents"] - escrowed
    standing = (
        member["onboarding_state"] == "TOOLS_GRANTED"
        and member["ip_commitment_type"] is not None
        and member["ip_withdrawn_at"] is None
    )
    open_cases = sum(
        1 for case in Q.cases_for_member(member["id"])
        if case["state"] in ("OPEN", "EVIDENCE_REVIEW", "REMEDIATION_ORDERED", "WITHDRAWAL_ORDERED")
    )
    set_fields(
        member,
        escrowed_credit_cents=escrowed,
        credit_balance_cents=balance,
        good_standing=standing,
        open_case_count=open_cases,
    )


# ------------------------------------------------------------------ submission

def refresh_provisional_readiness(submission):
    """Null until the first result line exists (PRD 3.9)."""
    if not _has_result_line(submission):
        return
    result = calc.readiness(submission, "PROVISIONAL")
    set_fields(submission, provisional_readiness_score=result["score"])


def _has_result_line(submission):
    plan = Q.live_plan(submission["id"])
    if plan is None:
        return False
    for session in Q.sessions_for_plan(plan["id"]):
        if session["result_lines"]:
            return True
    return False


def apply_plugfest_pass(submission):
    """One mutation: the credit count and the refreshed provisional score."""
    count = sum(1 for p in Q.participations_for_submission(submission["id"])
                if p["state"] == "PASSED")
    fields = {"plugfest_credit_count": count}
    if _has_result_line(submission):
        fields["provisional_readiness_score"] = calc.readiness(
            submission, "PROVISIONAL", credits_override=count)["score"]
    set_fields(submission, **fields)


def release_escrow(submission):
    """Rejection or withdrawal returns the escrow to the member's balance."""
    if submission["fee_escrowed_cents"] == 0:
        return
    set_fields(submission, fee_escrowed_cents=0)
    member = store.members.get(submission["member_id"])
    if member is not None:
        recompute_member(member)


# ------------------------------------------------------------------- plugfest

def recompute_distinct_vendors(plugfest):
    vendors = {
        p["member_id"] for p in Q.participations_for_plugfest(plugfest["id"])
        if p["state"] in ("REGISTERED", "PASSED", "FAILED")
    }
    set_fields(plugfest, distinct_vendor_count=len(vendors))


# -------------------------------------------------------------------- listing

def next_listing_reference():
    return "LST-%06d" % (len(store.listings) + 1)


def resolve_declared_features(submission):
    plan = Q.live_plan(submission["id"])
    if plan is None:
        return []
    rows = []
    for fs_id in plan["included_feature_set_ids"]:
        fs = store.feature_sets.get(fs_id)
        if fs is not None:
            rows.append(fs)
    rows.sort(key=lambda fs: fs["feature_code"])
    return [fs["feature_code"] for fs in rows]


def revoke_credential(submission):
    if submission is not None and submission["dac_state"] == "ISSUED":
        set_fields(submission, dac_state="REVOKED")


# ----------------------------------------------------------- noncompliance case

def make_case(listing, category, evidence_summary, claimed_impact_units, opened_by_user_id,
              auto_opened=False):
    subtotal, surcharge, total = calc.penalty(claimed_impact_units, category)
    case = new_row(
        listing_id=listing["id"],
        category=category,
        evidence_summary=evidence_summary,
        claimed_impact_units=claimed_impact_units,
        state="OPEN",
        opened_by_user_id=opened_by_user_id,
        closed_by_user_id=None,
        auto_opened=auto_opened,
        assessment_subtotal_cents=subtotal,
        surcharge_cents=surcharge,
        penalty_total_cents=total,
        remediation_deadline_at=None,
    )
    store.cases[case["id"]] = case
    return case


# ---------------------------------------------------------- specification hops

def deprecation_cascade(spec):
    """PRD 2.7: three chained hops plus one independent listing fan-out."""
    hop1 = [s for s in Q.submissions_for_spec(spec["id"])
            if s["state"] in ("SUBMITTED", "IN_REVIEW", "RETURNED_FOR_INFO")]
    for submission in hop1:
        set_fields(
            submission,
            conformance_review_state="RETURNED",
            state="RETURNED_FOR_INFO",
            revision_round=min(submission["revision_round"] + 1, E.MAX_REVISION_ROUNDS),
            conformance_reviewer_user_id=SYSTEM,
        )
        for plan in Q.plans_for_submission(submission["id"]):
            if plan["state"] in ("DRAFT", "ISSUED", "IN_EXECUTION", "COMPLETE"):
                void_plan(plan, "SPECIFICATION_DEPRECATED")

    due = plus_days(now(), E.SPECIFICATION_DEPRECATION_RECERT_DUE_DAYS)
    for submission in Q.submissions_for_spec(spec["id"]):
        listing = Q.listing_for_submission(submission["id"])
        if listing is not None and listing["publication_status"] == "PUBLISHED":
            set_fields(listing,
                       recertification_due_at=due,
                       recert_trigger_reason="SPECIFICATION_DEPRECATED")


def laboratory_revocation_cascade(lab):
    """PRD 2.7: session cancellation, orphaned-plan voiding, plugfest fan-out."""
    touched_plan_ids = set()
    for session in Q.sessions_for_lab(lab["id"]):
        if session["state"] in LIVE_SESSION_STATES:
            set_fields(session, state="CANCELLED")
            touched_plan_ids.add(session["test_plan_id"])
    set_fields(lab, reserved_bench_minutes=0)

    for plan_id in sorted(touched_plan_ids):
        plan = store.test_plans.get(plan_id)
        if plan is None or plan["state"] != "IN_EXECUTION":
            continue
        remaining = [s for s in Q.sessions_for_plan(plan_id)
                     if s["state"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETE")]
        if not remaining:
            set_fields(plan, state="VOIDED", voided_reason="SPECIFICATION_DEPRECATED")

    for plugfest in Q.plugfests_for_host(lab["id"]):
        if plugfest["state"] in ("REGISTRATION_OPEN", "LOCKED"):
            set_fields(plugfest, state="CANCELLED")
            for participation in Q.participations_for_plugfest(plugfest["id"]):
                if participation["state"] == "REGISTERED":
                    set_fields(participation, state="NO_SHOW")
            recompute_distinct_vendors(plugfest)


def ip_withdrawal_cascade(member):
    """PRD 3.2 four-hop cascade."""
    recompute_member(member)
    suppressed = []
    for listing in Q.listings_for_member(member["id"]):
        if listing["publication_status"] == "PUBLISHED":
            set_fields(listing,
                       publication_status="SUPPRESSED",
                       compliance_status="UNDER_INVESTIGATION")
            suppressed.append(listing)
    for listing in suppressed:
        submission = store.submissions.get(listing["submission_id"])
        if submission is not None and submission["dac_state"] == "ISSUED":
            set_fields(submission, dac_state="REVOKED")
            make_case(
                listing,
                "IP_WITHDRAWAL",
                "Auto-opened: IP commitment withdrawn by member",
                0,
                SYSTEM,
                auto_opened=True,
            )
    recompute_member(member)
