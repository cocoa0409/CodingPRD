"""Domain services: state-transition cascades and computed-field recomputes.

Every public function in this module is expected to run while holding store.lock.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from .calculations import (
    WAITING_DAYS,
    offer_total_comp_cents,
    panel_average,
    percentage_round_2,
    referral_bonus_amounts,
)
from .clock import iso_format, now, parse_iso
from .common import bump, stamp_new
from .errors import ApiError
from .store import store


REQ_ACTIVE_OFFER_STATUSES = {"DRAFT", "PENDING_APPROVAL", "NEGOTIATING", "APPROVED", "EXTENDED"}
OFFER_NON_TERMINAL = {"DRAFT", "PENDING_APPROVAL", "NEGOTIATING", "APPROVED", "EXTENDED"}
APP_NON_TERMINAL = {"APPLIED", "SCREENING", "INTERVIEWING", "OFFER_STAGE"}


# ---------- offer total comp ----------

def recompute_offer_total(offer: dict[str, Any]) -> None:
    """Update offer.total_first_year_comp_cents via the offer_total_comp rule."""
    offer["total_first_year_comp_cents"] = offer_total_comp_cents(
        offer["base_salary_cents"],
        offer["sign_on_bonus_cents"],
        offer["annual_equity_cents"],
    )


# ---------- panel average ----------

def recompute_panel_average(application_id: str) -> None:
    """Recompute Application.panel_average_score across COMPLETED interviews' feedback."""
    application = store.applications.get(application_id)
    if application is None:
        return
    interview_ids = {
        i["id"]
        for i in store.interviews.values()
        if i["application_id"] == application_id and i["status"] == "COMPLETED"
    }
    scores = [
        f["overall_score"]
        for f in store.interview_feedback.values()
        if f["interview_id"] in interview_ids
    ]
    new_score = panel_average(scores)
    if new_score != application.get("panel_average_score"):
        application["panel_average_score"] = new_score
        bump(application)


# ---------- diversity goal progress ----------

def _year_of(iso_ts: str) -> int:
    return parse_iso(iso_ts).year


def recompute_diversity_goal(goal_id: str) -> None:
    """Realised + projected percentages, per the diversity_goal_progress rule."""
    goal = store.diversity_goals.get(goal_id)
    if goal is None:
        return
    period_year = goal["period_year"]

    # Map requisition_id -> requisition for fast lookup.
    req_by_id = {r["id"]: r for r in store.requisitions.values()}

    # Realized set: stage == HIRED, tied requisition, application.updated_at year == period_year.
    realized_set = []
    projected_set = []
    for app in store.applications.values():
        req = req_by_id.get(app["requisition_id"])
        if req is None:
            continue
        if req.get("target_diversity_goal_id") != goal_id:
            continue
        if app["stage"] == "HIRED" and _year_of(app["updated_at"]) == period_year:
            realized_set.append(app)
        if app["stage"] in {"APPLIED", "SCREENING", "INTERVIEWING", "OFFER_STAGE", "HIRED"}:
            if _year_of(app["created_at"]) == period_year:
                projected_set.append(app)

    def _protected(apps):
        return sum(
            1
            for a in apps
            if store.candidates.get(a["candidate_id"], {}).get("is_in_eeo_protected_class")
        )

    realized_pct = percentage_round_2(_protected(realized_set), len(realized_set))
    projected_pct = percentage_round_2(_protected(projected_set), len(projected_set))

    if (
        goal.get("realized_percentage") != realized_pct
        or goal.get("projected_percentage") != projected_pct
    ):
        goal["realized_percentage"] = realized_pct
        goal["projected_percentage"] = projected_pct
        bump(goal)


def recompute_goal_for_requisition(requisition: dict[str, Any]) -> None:
    gid = requisition.get("target_diversity_goal_id")
    if gid:
        recompute_diversity_goal(gid)


# ---------- approval step helpers ----------

def steps_for_offer(offer_id: str) -> list[dict[str, Any]]:
    steps = [s for s in store.offer_approval_steps.values() if s["offer_id"] == offer_id]
    steps.sort(key=lambda s: s["step_order"])
    return steps


def max_step_order(offer_id: str) -> int:
    steps = steps_for_offer(offer_id)
    return max((s["step_order"] for s in steps), default=0)


def reset_approval_steps(offer_id: str) -> None:
    for s in store.offer_approval_steps.values():
        if s["offer_id"] == offer_id:
            s["decision"] = "PENDING"
            s["decided_at"] = None


# ---------- requisition active-offer counter ----------

def recompute_active_offer_count(requisition: dict[str, Any]) -> None:
    """Authoritative count from current offer rows; called after any offer state change."""
    rid = requisition["id"]
    n = sum(
        1
        for o in store.offers.values()
        if o["requisition_id"] == rid and o["status"] in REQ_ACTIVE_OFFER_STATUSES
    )
    if requisition.get("active_offer_count", 0) != n:
        requisition["active_offer_count"] = n
        bump(requisition)


# ---------- hire cascade & post-hire revoke ----------

def cascade_application_to_hired(application: dict[str, Any], offer: dict[str, Any]) -> None:
    """Hop 1->2->3: Application OFFER_STAGE -> HIRED; req.filled_count++; possibly close req."""
    requisition = store.requisitions[application["requisition_id"]]

    # Hop 2 precondition: headcount check.
    if requisition.get("filled_count", 0) + 1 > requisition["headcount"]:
        raise ApiError("ERR_HEADCOUNT_EXCEEDED", "Requisition.headcount has been filled")

    # Hop 1: application -> HIRED.
    application["stage"] = "HIRED"
    application["rejection_reason"] = None
    bump(application)

    # Hop 2: increment filled_count.
    requisition["filled_count"] = requisition.get("filled_count", 0) + 1
    bump(requisition)

    # Trigger any referral bonus tied to (candidate, requisition).
    _trigger_referral_bonus(application, offer)

    # Hop 3: if last seat, close the requisition.
    if requisition["filled_count"] == requisition["headcount"]:
        requisition["status"] = "CLOSED"
        requisition["closed_at"] = iso_format(now())
        bump(requisition)
        # Auto-reject remaining non-terminal applications on this requisition.
        for other in list(store.applications.values()):
            if other["id"] == application["id"]:
                continue
            if other["requisition_id"] == requisition["id"] and other["stage"] in APP_NON_TERMINAL:
                _system_reject_application(other, reason="OTHER")

    # Final recompute hooks for diversity goal (realized + projected both shift on this).
    recompute_goal_for_requisition(requisition)


def _trigger_referral_bonus(application: dict[str, Any], offer: dict[str, Any]) -> None:
    candidate = store.candidates.get(application["candidate_id"])
    requisition = store.requisitions.get(application["requisition_id"])
    if candidate is None or requisition is None:
        return
    if candidate.get("source") != "REFERRAL":
        return

    # Find an existing bonus (if any) tied to (candidate, requisition).
    rb = next(
        (
            b
            for b in store.referral_bonuses.values()
            if b["candidate_id"] == candidate["id"] and b["requisition_id"] == requisition["id"]
        ),
        None,
    )

    base, uplift = referral_bonus_amounts(
        requisition["seniority_level"],
        bool(candidate.get("is_in_eeo_protected_class", False)),
        requisition.get("target_diversity_goal_id") is not None,
    )
    payable_dt = now() + timedelta(days=WAITING_DAYS)

    if rb is None:
        rb = stamp_new({
            "candidate_id": candidate["id"],
            "referrer_employee_id": candidate.get("referrer_employee_id"),
            "requisition_id": requisition["id"],
            "base_amount_cents": base,
            "diversity_uplift_cents": uplift,
            "total_amount_cents": base + uplift,
            "status": "ACCRUED",
            "payable_at": iso_format(payable_dt),
        })
        store.referral_bonuses[rb["id"]] = rb
    else:
        rb["base_amount_cents"] = base
        rb["diversity_uplift_cents"] = uplift
        rb["total_amount_cents"] = base + uplift
        rb["status"] = "ACCRUED"
        rb["payable_at"] = iso_format(payable_dt)
        bump(rb)


def _system_reject_application(application: dict[str, Any], *, reason: str) -> None:
    """System-initiated auto reject (cascading cancellation/closure path)."""
    if application["stage"] not in APP_NON_TERMINAL:
        return
    application["stage"] = "REJECTED"
    application["rejection_reason"] = reason
    bump(application)
    requisition = store.requisitions.get(application["requisition_id"])
    if requisition:
        recompute_goal_for_requisition(requisition)


def system_reject_application(application: dict[str, Any], *, reason: str) -> None:
    _system_reject_application(application, reason=reason)


# ---------- offer-driven cascades ----------

def cascade_offer_rescind(offer: dict[str, Any], *, reason_for_app: str) -> None:
    """RESCINDED side-effects: active_offer_count--, manager credit, application reject."""
    requisition = store.requisitions[offer["requisition_id"]]
    application = store.applications[offer["application_id"]]
    manager = store.hiring_managers.get(requisition["hiring_manager_id"])

    offer["status"] = "RESCINDED"
    bump(offer)
    recompute_active_offer_count(requisition)
    if manager is not None:
        manager["budget_cents"] = manager.get("budget_cents", 0) + offer["total_first_year_comp_cents"]
        bump(manager)

    # Auto reject the parent application if it has no other ACCEPTED offer.
    if not _has_other_accepted_offer(application, offer["id"]):
        if application["stage"] in APP_NON_TERMINAL:
            _system_reject_application(application, reason=reason_for_app)


def _has_other_accepted_offer(application: dict[str, Any], exclude_offer_id: str) -> bool:
    return any(
        o["id"] != exclude_offer_id
        and o["application_id"] == application["id"]
        and o["status"] == "ACCEPTED"
        for o in store.offers.values()
    )


def cascade_offer_decline(offer: dict[str, Any]) -> None:
    requisition = store.requisitions[offer["requisition_id"]]
    application = store.applications[offer["application_id"]]
    offer["status"] = "DECLINED"
    bump(offer)
    recompute_active_offer_count(requisition)
    if not _has_other_accepted_offer(application, offer["id"]):
        if application["stage"] in APP_NON_TERMINAL:
            _system_reject_application(application, reason="OFFER_DECLINED")


def cascade_offer_expire(offer: dict[str, Any]) -> None:
    requisition = store.requisitions[offer["requisition_id"]]
    application = store.applications[offer["application_id"]]
    offer["status"] = "EXPIRED"
    bump(offer)
    recompute_active_offer_count(requisition)
    if not _has_other_accepted_offer(application, offer["id"]):
        if application["stage"] in APP_NON_TERMINAL:
            _system_reject_application(application, reason="OTHER")


# ---------- post-hire revoke (background-check FAIL on an ACCEPTED offer) ----------

def post_hire_revoke(offer: dict[str, Any]) -> None:
    """BG FAIL after ACCEPTED — unwind the hire all the way back up."""
    application = store.applications[offer["application_id"]]
    requisition = store.requisitions[offer["requisition_id"]]
    manager = store.hiring_managers.get(requisition["hiring_manager_id"])

    # Offer ACCEPTED -> RESCINDED.
    offer["status"] = "RESCINDED"
    bump(offer)

    # Application HIRED -> REJECTED.
    application["stage"] = "REJECTED"
    application["rejection_reason"] = "FAILED_BACKGROUND_CHECK"
    bump(application)

    # filled_count decrement; reopen requisition if it was CLOSED.
    requisition["filled_count"] = max(requisition.get("filled_count", 0) - 1, 0)
    if requisition["status"] == "CLOSED":
        requisition["status"] = "OPEN"
        requisition["closed_at"] = None
    bump(requisition)

    if manager is not None:
        manager["budget_cents"] = manager.get("budget_cents", 0) + offer["total_first_year_comp_cents"]
        bump(manager)

    # ReferralBonus on this hire -> CLAWED_BACK.
    for rb in store.referral_bonuses.values():
        if (
            rb["candidate_id"] == application["candidate_id"]
            and rb["requisition_id"] == requisition["id"]
            and rb["status"] in {"ACCRUED", "PAYABLE"}
        ):
            rb["status"] = "CLAWED_BACK"
            bump(rb)

    recompute_goal_for_requisition(requisition)


# ---------- offer state-change side effects on requisition counter ----------

def offer_state_change(offer: dict[str, Any]) -> None:
    """Helper invoked whenever an offer's status changes so counters track reality."""
    requisition = store.requisitions.get(offer["requisition_id"])
    if requisition is not None:
        recompute_active_offer_count(requisition)


# ---------- referral bonus sweep ----------

def sweep_referral_payable() -> None:
    """ACCRUED -> PAYABLE for every bonus whose payable_at <= now() and app still HIRED."""
    n_now = now()
    for rb in store.referral_bonuses.values():
        if rb["status"] != "ACCRUED":
            continue
        if not rb.get("payable_at"):
            continue
        try:
            payable_dt = parse_iso(rb["payable_at"])
        except ValueError:
            continue
        if payable_dt > n_now:
            continue
        # Need linked application stage == HIRED.
        linked_app = _application_for_referral(rb)
        if linked_app is None or linked_app["stage"] != "HIRED":
            continue
        rb["status"] = "PAYABLE"
        bump(rb)


def _application_for_referral(rb: dict[str, Any]) -> dict[str, Any] | None:
    for app in store.applications.values():
        if app["candidate_id"] == rb["candidate_id"] and app["requisition_id"] == rb["requisition_id"]:
            return app
    return None


# ---------- offer expiry sweep ----------

def sweep_offer_expiry() -> None:
    """EXTENDED -> EXPIRED for every offer whose expires_at <= now()."""
    n_now = now()
    for offer in list(store.offers.values()):
        if offer["status"] != "EXTENDED":
            continue
        if not offer.get("expires_at"):
            continue
        try:
            expires_dt = parse_iso(offer["expires_at"])
        except ValueError:
            continue
        if expires_dt > n_now:
            continue
        cascade_offer_expire(offer)
