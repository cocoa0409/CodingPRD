"""Multi-hop cascades and the logical-clock sweeps (PRD 3.2, 3.5, 3.7)."""

from datetime import timedelta

import calculations as calc
import lookups as lk
import services as svc
from db import db, new_row, set_fields, sorted_rows

ZERO = calc.ZERO


# ------------------------------------------------------------------------
# integration plan helpers
# ------------------------------------------------------------------------

def cancel_proposed_introductions(plan):
    for intro in sorted_rows(lk.introductions_of_plan(plan["id"])):
        if intro["status"] == "PROPOSED":
            set_fields(intro, status="CANCELLED")


def close_plan(plan, new_status):
    was_active = plan["status"] == "ACTIVE"
    set_fields(plan, status=new_status)
    cancel_proposed_introductions(plan)
    svc.sync_plan_counters(plan)
    if was_active:
        group = db.practice_groups.get(plan["practice_group_id"])
        if group is not None:
            svc.sync_group_onboarding(group)


# ------------------------------------------------------------------------
# candidate withdrawal (PRD 3.2, four hops)
# ------------------------------------------------------------------------

LAPSABLE = ("DRAFTED", "COMMITTEE_REVIEW", "APPROVED",
            "COUNTER_REQUESTED", "REPRICE_REQUIRED")


def withdraw_candidate(candidate):
    set_fields(candidate, pipeline_status="WITHDRAWN", open_offer_id=None)

    # Hop 2 -- questionnaires abandoned, live offers lapse.
    for questionnaire in sorted_rows(lk.questionnaires_of_candidate(candidate["id"])):
        if questionnaire["status"] not in ("ACCEPTED", "ABANDONED"):
            set_fields(questionnaire, status="ABANDONED")

    for offer in sorted_rows(lk.offers_of_candidate(candidate["id"])):
        if offer["status"] not in LAPSABLE:
            continue
        prior = offer["status"]
        set_fields(offer, status="LAPSED")
        # Hop 3 -- release the reservation (only the two holding statuses do),
        # and abandon any integration plan naming that offer.
        svc.sync_group_for_offer(offer)
        if prior in ("COMMITTEE_REVIEW", "APPROVED"):
            for plan in sorted_rows(lk.plans_of_candidate(candidate["id"])):
                if plan["offer_id"] == offer["id"] and plan["status"] in ("DRAFT", "ACTIVE"):
                    # Hop 4 -- cancel proposed slots, return the onboarding slot.
                    close_plan(plan, "ABANDONED")


# ------------------------------------------------------------------------
# declination cascade (PRD 3.5, hops 2-5)
# ------------------------------------------------------------------------

def blocked_check_cascade(check):
    # Hop 2
    set_fields(check, status="BLOCKED")

    entry = db.client_book_entries.get(check["client_book_entry_id"])
    if entry is None:
        return

    # Hop 3
    set_fields(entry, portable_status="DECLINED", validated_portable_amount_usd=ZERO)
    matter_types = entry["matter_types"]
    shares = calc.declination_shares(entry["baseline_portable_amount_usd"],
                                     len(matter_types))
    for index, matter_type in enumerate(matter_types):
        row = new_row({
            "conflict_check_id": check["id"],
            "client_book_entry_id": entry["id"],
            "matter_type": matter_type,
            "foregone_annual_revenue_usd": shares[index],
            "status": "ACTIVE",
            "rescinded_at": None,
        })
        db.declinations[row["id"]] = row

    candidate = svc.candidate_of_entry(entry)
    if candidate is not None:
        set_fields(candidate, clearance_status="BLOCKED")

    # Hops 4 and 5
    svc.stale_current_assessments(entry["questionnaire_id"])


def resolve_waiver_negative(waiver, new_status, note=None):
    """Refusal and expiry run the identical downstream cascade."""
    fields = {"status": new_status, "decided_at": db.clock}
    if note is not None:
        fields["resolution_note"] = note
    set_fields(waiver, **fields)
    check = db.conflict_checks.get(waiver["conflict_check_id"])
    if check is not None and check["status"] == "WAIVER_PENDING":
        blocked_check_cascade(check)


# ------------------------------------------------------------------------
# logical clock sweeps (PRD 3.1, 3.5, 3.7)
# ------------------------------------------------------------------------

def advance_clock(new_clock):
    db.clock = new_clock

    # Sweep 1: expire engagements whose tail-off has fully elapsed (inclusive).
    for engagement in sorted_rows(list(db.engagements.values())):
        if engagement["status"] != "ACTIVE":
            continue
        tail_end = (engagement["exclusivity_end_date"]
                    + timedelta(days=engagement["tail_off_days"]))
        if tail_end <= new_clock:
            set_fields(engagement, status="EXPIRED")

    # Sweep 2: expire overdue waivers (strictly earlier deadline), in
    # response_deadline_date ascending order then created_at ascending.
    overdue = [w for w in db.waivers.values()
               if w["status"] == "REQUESTED"
               and w["response_deadline_date"] < new_clock]
    overdue.sort(key=lambda w: (w["response_deadline_date"], w["created_at"], w["_seq"]))
    for waiver in overdue:
        resolve_waiver_negative(waiver, "EXPIRED")

    # Sweep 3: complete active plans whose onboarding window has closed
    # (strictly past), in onboarding_end_date ascending then created_at.
    finished = [p for p in db.integration_plans.values()
                if p["status"] == "ACTIVE" and new_clock > p["onboarding_end_date"]]
    finished.sort(key=lambda p: (p["onboarding_end_date"], p["created_at"], p["_seq"]))
    for plan in finished:
        close_plan(plan, "COMPLETED")
