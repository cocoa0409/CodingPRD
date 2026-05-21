"""Centralised entity lookups that raise the correct error_id when missing."""
from __future__ import annotations

from typing import Any

from .errors import ApiError
from .store import store


def _get_or_raise(table: dict, ent_id: Any, error_id: str, label: str) -> dict[str, Any]:
    if not isinstance(ent_id, str):
        raise ApiError(error_id, f"{label} not found")
    obj = table.get(ent_id)
    if obj is None:
        raise ApiError(error_id, f"{label} not found")
    return obj


# Path-resource lookups: missing -> 404 ERR_NOT_FOUND
def path_recruiter(rid: Any) -> dict[str, Any]:
    return _get_or_raise(store.recruiters, rid, "ERR_NOT_FOUND", "Recruiter")


def path_hiring_manager(hid: Any) -> dict[str, Any]:
    return _get_or_raise(store.hiring_managers, hid, "ERR_NOT_FOUND", "HiringManager")


def path_interviewer(iid: Any) -> dict[str, Any]:
    return _get_or_raise(store.interviewers, iid, "ERR_NOT_FOUND", "Interviewer")


def path_candidate(cid: Any) -> dict[str, Any]:
    return _get_or_raise(store.candidates, cid, "ERR_NOT_FOUND", "Candidate")


def path_requisition(rid: Any) -> dict[str, Any]:
    return _get_or_raise(store.requisitions, rid, "ERR_NOT_FOUND", "Requisition")


def path_application(aid: Any) -> dict[str, Any]:
    return _get_or_raise(store.applications, aid, "ERR_NOT_FOUND", "Application")


def path_interview(iid: Any) -> dict[str, Any]:
    return _get_or_raise(store.interviews, iid, "ERR_NOT_FOUND", "Interview")


def path_offer(oid: Any) -> dict[str, Any]:
    return _get_or_raise(store.offers, oid, "ERR_NOT_FOUND", "Offer")


def path_background_check(bid: Any) -> dict[str, Any]:
    return _get_or_raise(store.background_checks, bid, "ERR_NOT_FOUND", "BackgroundCheck")


def path_referral_bonus(rid: Any) -> dict[str, Any]:
    return _get_or_raise(store.referral_bonuses, rid, "ERR_NOT_FOUND", "ReferralBonus")


def path_diversity_goal(gid: Any) -> dict[str, Any]:
    return _get_or_raise(store.diversity_goals, gid, "ERR_NOT_FOUND", "DiversityGoal")


# Body-foreign-key lookups: missing -> 422 ERR_REFERENCE_NOT_FOUND
def ref_recruiter(rid: Any) -> dict[str, Any]:
    return _get_or_raise(store.recruiters, rid, "ERR_REFERENCE_NOT_FOUND", "Recruiter reference")


def ref_hiring_manager(hid: Any) -> dict[str, Any]:
    return _get_or_raise(store.hiring_managers, hid, "ERR_REFERENCE_NOT_FOUND", "HiringManager reference")


def ref_interviewer(iid: Any) -> dict[str, Any]:
    return _get_or_raise(store.interviewers, iid, "ERR_REFERENCE_NOT_FOUND", "Interviewer reference")


def ref_candidate(cid: Any) -> dict[str, Any]:
    return _get_or_raise(store.candidates, cid, "ERR_REFERENCE_NOT_FOUND", "Candidate reference")


def ref_diversity_goal(gid: Any) -> dict[str, Any]:
    return _get_or_raise(store.diversity_goals, gid, "ERR_REFERENCE_NOT_FOUND", "DiversityGoal reference")


def employee_exists(employee_id: Any) -> bool:
    """Referral employee may be any of Recruiter / HiringManager / Interviewer."""
    if not isinstance(employee_id, str):
        return False
    return (
        employee_id in store.recruiters
        or employee_id in store.hiring_managers
        or employee_id in store.interviewers
    )
