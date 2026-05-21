"""Entity assertions and domain invariant checkers.

Common-fields entities (PRD §2.4): Recruiter, HiringManager,
Interviewer, Requisition, Candidate, Application, Interview, Offer,
BackgroundCheck, ReferralBonus, DiversityGoal — carry id +
created_at + updated_at + version.

Append-only entities (PRD §2.4): EEORecord, InterviewFeedback,
OfferApprovalStep — carry only id + created_at; updated_at and
version MUST NOT appear on their payloads.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Envelope checks — common-fields vs append-only.
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Entities with the common-fields treatment ...
    additionally carry `created_at` and `updated_at` as ISO 8601 UTC
    timestamps with three fractional digits, and a `version` field
    which is an integer that starts at 1 on creation and increments by
    one on every mutation.\""""
    assert "id" in data, "common-fields row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID without prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing 'updated_at'"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing 'version'"
    assert isinstance(data["version"], int), (
        f"version must be int, got {type(data['version'])}"
    )
    assert data["version"] >= 1, (
        f"version must be >= 1, got {data['version']}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Two entities are deliberately exceptions and do NOT
    carry `updated_at` or `version` — they carry only `id` and
    `created_at`. These are `EEORecord` ... and `OfferApprovalStep` ...
    `InterviewFeedback` likewise carries only `id` and `created_at`
    and is immutable after submission.\""""
    assert "id" in data, "append-only row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" not in data, (
        "append-only entity must not expose 'updated_at' "
        f"(found: {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "append-only entity must not expose 'version' "
        f"(found: {data.get('version')!r})"
    )


def assert_status(data: Dict[str, Any], expected: str,
                  field: str = "status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_stage(data: Dict[str, Any], expected: str) -> None:
    actual = data.get("stage")
    assert actual == expected, (
        f"Expected stage={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.4: "a `version` field which is an integer that starts at
    1 on creation and increments by one on every mutation, whether
    direct (a `PATCH`) or indirect (a state transition or computed-
    field recompute).\""""
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] >= prior["version"] + delta, (
        f"Expected version >= {prior['version']} + {delta}, got "
        f"{current['version']}"
    )


# ---------------------------------------------------------------------------
# Recruiter — PRD §3.1
# ---------------------------------------------------------------------------
def assert_recruiter(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("email"), str) and data["email"], (
        "email must be non-empty string"
    )
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "full_name must be non-empty string"
    )
    assert isinstance(data.get("department_code"), str), (
        f"department_code must be string, got {data.get('department_code')!r}"
    )
    assert "is_active" in data, "Recruiter missing is_active"
    assert isinstance(data["is_active"], bool), (
        f"is_active must be bool, got {type(data['is_active'])}"
    )


# ---------------------------------------------------------------------------
# HiringManager — PRD §3.1
# ---------------------------------------------------------------------------
def assert_hiring_manager(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("department_code"), str)
    b = data.get("budget_cents")
    assert isinstance(b, int) and b >= 0, (
        f"budget_cents must be non-negative int, got {b!r}"
    )


# ---------------------------------------------------------------------------
# Interviewer — PRD §3.1
# ---------------------------------------------------------------------------
def assert_interviewer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("department_code"), str)
    assert "is_certified_for_eeo" in data, (
        "Interviewer missing is_certified_for_eeo"
    )
    assert isinstance(data["is_certified_for_eeo"], bool)


# ---------------------------------------------------------------------------
# Requisition — PRD §3.2
# ---------------------------------------------------------------------------
def assert_requisition(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("recruiter_id"), str)
    assert isinstance(data.get("hiring_manager_id"), str)
    assert isinstance(data.get("job_title"), str) and data["job_title"]
    assert isinstance(data.get("department_code"), str)
    assert data.get("seniority_level") in {
        "JUNIOR", "MID", "SENIOR", "STAFF", "PRINCIPAL",
    }, f"seniority_level invalid: {data.get('seniority_level')!r}"
    hc = data.get("headcount")
    assert isinstance(hc, int) and hc >= 1, (
        f"headcount must be int >= 1, got {hc!r}"
    )
    fc = data.get("filled_count")
    assert isinstance(fc, int) and fc >= 0, (
        f"filled_count must be non-negative int, got {fc!r}"
    )
    aoc = data.get("active_offer_count")
    assert isinstance(aoc, int) and aoc >= 0, (
        f"active_offer_count must be non-negative int, got {aoc!r}"
    )
    pa = data.get("posted_at", None)
    assert pa is None or is_iso8601_timestamp(str(pa)), (
        f"posted_at must be ISO 8601 or null, got {pa!r}"
    )
    ca = data.get("closed_at", None)
    assert ca is None or is_iso8601_timestamp(str(ca)), (
        f"closed_at must be ISO 8601 or null, got {ca!r}"
    )
    bc = data.get("budget_cents")
    assert isinstance(bc, int) and bc >= 0, (
        f"budget_cents must be non-negative int, got {bc!r}"
    )
    # target_diversity_goal_id may be null per PRD §3.2.
    tdg = data.get("target_diversity_goal_id", None)
    assert tdg is None or isinstance(tdg, str), (
        f"target_diversity_goal_id must be string or null, got {tdg!r}"
    )
    assert data.get("status") in {
        "DRAFT", "PENDING_APPROVAL", "OPEN", "ON_HOLD", "CLOSED", "CANCELLED",
    }, f"Requisition.status invalid: {data.get('status')!r}"


# ---------------------------------------------------------------------------
# Candidate — PRD §3.1
# ---------------------------------------------------------------------------
def assert_candidate(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("source") in {
        "DIRECT", "AGENCY", "REFERRAL", "EVENT", "INBOUND",
    }, f"Candidate.source invalid: {data.get('source')!r}"
    ref = data.get("referrer_employee_id", None)
    assert ref is None or isinstance(ref, str), (
        f"referrer_employee_id must be string or null, got {ref!r}"
    )
    assert "is_in_eeo_protected_class" in data, (
        "Candidate missing is_in_eeo_protected_class"
    )
    assert isinstance(data["is_in_eeo_protected_class"], bool)


# ---------------------------------------------------------------------------
# EEORecord — PRD §3.1 (append-only)
# ---------------------------------------------------------------------------
def assert_eeo_record(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("candidate_id"), str)
    assert data.get("gender") in {
        "MALE", "FEMALE", "NON_BINARY", "DECLINE",
    }, f"gender invalid: {data.get('gender')!r}"
    assert data.get("ethnicity") in {
        "HISPANIC_LATINO", "WHITE", "BLACK_AFRICAN_AMERICAN",
        "NATIVE_HAWAIIAN_PI", "ASIAN", "AMERICAN_INDIAN_AN",
        "TWO_OR_MORE", "DECLINE",
    }, f"ethnicity invalid: {data.get('ethnicity')!r}"
    assert data.get("veteran_status") in {
        "NOT_VETERAN", "PROTECTED_VETERAN", "OTHER_VETERAN", "DECLINE",
    }, f"veteran_status invalid: {data.get('veteran_status')!r}"
    assert data.get("disability_status") in {
        "YES", "NO", "DECLINE",
    }, f"disability_status invalid: {data.get('disability_status')!r}"
    assert is_iso8601_timestamp(str(data.get("submitted_at", ""))), (
        f"submitted_at must be ISO 8601, got {data.get('submitted_at')!r}"
    )


# ---------------------------------------------------------------------------
# Application — PRD §3.3
# ---------------------------------------------------------------------------
def assert_application(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("requisition_id"), str)
    assert isinstance(data.get("candidate_id"), str)
    assert data.get("stage") in {
        "APPLIED", "SCREENING", "INTERVIEWING",
        "OFFER_STAGE", "HIRED", "REJECTED", "WITHDRAWN",
    }, f"Application.stage invalid: {data.get('stage')!r}"
    rr = data.get("rejection_reason", None)
    assert rr is None or rr in {
        "NOT_QUALIFIED", "FAILED_INTERVIEW", "FAILED_BACKGROUND_CHECK",
        "OFFER_DECLINED", "DUPLICATE", "OTHER",
    }, f"rejection_reason invalid: {rr!r}"
    pas = data.get("panel_average_score", None)
    assert pas is None or isinstance(pas, (int, float)), (
        f"panel_average_score must be number or null, got {pas!r}"
    )


# ---------------------------------------------------------------------------
# Interview — PRD §3.4
# ---------------------------------------------------------------------------
def assert_interview(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("interviewer_id"), str)
    assert is_iso8601_timestamp(str(data.get("scheduled_start_at", "")))
    assert is_iso8601_timestamp(str(data.get("scheduled_end_at", "")))
    assert data.get("status") in {
        "SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED",
    }, f"Interview.status invalid: {data.get('status')!r}"


# ---------------------------------------------------------------------------
# InterviewFeedback — PRD §3.4 (append-only)
# ---------------------------------------------------------------------------
def assert_interview_feedback(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("interview_id"), str)
    assert isinstance(data.get("interviewer_id"), str)
    score = data.get("overall_score")
    assert isinstance(score, int) and 1 <= score <= 5, (
        f"overall_score must be int 1..5, got {score!r}"
    )
    assert data.get("recommendation") in {
        "STRONG_HIRE", "HIRE", "NO_HIRE", "STRONG_NO_HIRE",
    }, f"recommendation invalid: {data.get('recommendation')!r}"
    assert is_iso8601_timestamp(str(data.get("submitted_at", "")))


# ---------------------------------------------------------------------------
# Offer — PRD §3.5
# ---------------------------------------------------------------------------
def assert_offer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("requisition_id"), str)
    bs = data.get("base_salary_cents")
    assert isinstance(bs, int) and bs >= 0, (
        f"base_salary_cents must be non-negative int, got {bs!r}"
    )
    sob = data.get("sign_on_bonus_cents")
    assert isinstance(sob, int) and sob >= 0, (
        f"sign_on_bonus_cents must be non-negative int, got {sob!r}"
    )
    ae = data.get("annual_equity_cents")
    assert isinstance(ae, int) and ae >= 0, (
        f"annual_equity_cents must be non-negative int, got {ae!r}"
    )
    total = data.get("total_first_year_comp_cents")
    assert isinstance(total, int) and total >= 0, (
        f"total_first_year_comp_cents must be non-negative int, got {total!r}"
    )
    # PRD §3.5: "total_first_year_comp_cents always ends in 00 (the
    # cents portion is always zero, since the value is a whole-dollar
    # amount expressed in cents)."
    assert total % 100 == 0, (
        f"total_first_year_comp_cents must end in 00 (whole dollars in "
        f"cents), got {total}"
    )
    assert data.get("status") in {
        "DRAFT", "PENDING_APPROVAL", "NEGOTIATING", "APPROVED",
        "EXTENDED", "ACCEPTED", "DECLINED", "RESCINDED", "EXPIRED",
    }, f"Offer.status invalid: {data.get('status')!r}"
    ea = data.get("expires_at", None)
    assert ea is None or is_iso8601_timestamp(str(ea)), (
        f"expires_at must be ISO 8601 or null, got {ea!r}"
    )
    nr = data.get("negotiation_round")
    assert isinstance(nr, int) and nr >= 0, (
        f"negotiation_round must be non-negative int, got {nr!r}"
    )


# ---------------------------------------------------------------------------
# OfferApprovalStep — PRD §3.5 (append-only)
# ---------------------------------------------------------------------------
def assert_offer_approval_step(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("offer_id"), str)
    so = data.get("step_order")
    assert isinstance(so, int) and so >= 1, (
        f"step_order must be int >= 1, got {so!r}"
    )
    assert data.get("approver_role") in {
        "HIRING_MANAGER", "COMPENSATION", "EXECUTIVE",
    }, f"approver_role invalid: {data.get('approver_role')!r}"
    assert isinstance(data.get("required_approver_id"), str)
    assert data.get("decision") in {
        "PENDING", "APPROVED", "REJECTED",
    }, f"OfferApprovalStep.decision invalid: {data.get('decision')!r}"
    da = data.get("decided_at", None)
    assert da is None or is_iso8601_timestamp(str(da)), (
        f"decided_at must be ISO 8601 or null, got {da!r}"
    )


# ---------------------------------------------------------------------------
# BackgroundCheck — PRD §3.7
# ---------------------------------------------------------------------------
def assert_background_check(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("offer_id"), str)
    assert data.get("vendor") in {
        "ACME_BG", "VERIFY_INC", "FED_CHECKS",
    }, f"vendor invalid: {data.get('vendor')!r}"
    assert data.get("status") in {
        "PENDING", "PASSED", "FAILED", "CANCELLED",
    }, f"BackgroundCheck.status invalid: {data.get('status')!r}"
    assert is_iso8601_timestamp(str(data.get("ordered_at", "")))
    rr = data.get("result_received_at", None)
    assert rr is None or is_iso8601_timestamp(str(rr)), (
        f"result_received_at must be ISO 8601 or null, got {rr!r}"
    )


# ---------------------------------------------------------------------------
# ReferralBonus — PRD §3.6
# ---------------------------------------------------------------------------
def assert_referral_bonus(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("candidate_id"), str)
    assert isinstance(data.get("referrer_employee_id"), str)
    assert isinstance(data.get("requisition_id"), str)
    ba = data.get("base_amount_cents")
    assert isinstance(ba, int) and ba >= 0, (
        f"base_amount_cents must be non-negative int, got {ba!r}"
    )
    du = data.get("diversity_uplift_cents")
    assert isinstance(du, int) and du >= 0, (
        f"diversity_uplift_cents must be non-negative int, got {du!r}"
    )
    ta = data.get("total_amount_cents")
    assert isinstance(ta, int) and ta >= 0, (
        f"total_amount_cents must be non-negative int, got {ta!r}"
    )
    # PRD §3.6: "The `total_amount_cents` is the sum
    # `base_amount_cents + diversity_uplift_cents`."
    assert ta == ba + du, (
        f"total_amount_cents must equal base + uplift; "
        f"got {ta} vs {ba} + {du} = {ba + du}"
    )
    assert data.get("status") in {
        "ACCRUED", "PAYABLE", "PAID", "CLAWED_BACK",
    }, f"ReferralBonus.status invalid: {data.get('status')!r}"
    pa = data.get("payable_at", None)
    assert pa is None or is_iso8601_timestamp(str(pa)), (
        f"payable_at must be ISO 8601 or null, got {pa!r}"
    )


# ---------------------------------------------------------------------------
# DiversityGoal — PRD §3.1, §3.6
# ---------------------------------------------------------------------------
def assert_diversity_goal(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("department_code"), str)
    py = data.get("period_year")
    assert isinstance(py, int) and py >= 2020, (
        f"period_year must be int >= 2020, got {py!r}"
    )
    tg = data.get("target_protected_class_percentage")
    assert isinstance(tg, (int, float)) and 0 < tg <= 100.0, (
        f"target_protected_class_percentage must be (0, 100.0], got {tg!r}"
    )
    rp = data.get("realized_percentage")
    assert isinstance(rp, (int, float)) and 0.0 <= rp <= 100.0, (
        f"realized_percentage must be in [0, 100.0], got {rp!r}"
    )
    pp = data.get("projected_percentage")
    assert isinstance(pp, (int, float)) and 0.0 <= pp <= 100.0, (
        f"projected_percentage must be in [0, 100.0], got {pp!r}"
    )


# ---------------------------------------------------------------------------
# Domain invariant helpers
# ---------------------------------------------------------------------------
def assert_offer_total_is_per_component_round(
    *,
    base_salary_cents: int,
    sign_on_bonus_cents: int,
    annual_equity_cents: int,
    total_first_year_comp_cents: int,
) -> None:
    """PRD §3.5: "convert `base_salary_cents` to dollars by dividing by
    100 and rounding half up to a whole number, convert
    `sign_on_bonus_cents` to dollars by dividing by 100 and rounding
    half up to a whole number, convert `annual_equity_cents` to
    dollars by dividing by 100 and rounding half up to a whole number,
    add the three whole-dollar values together, then multiply that
    sum by 100 to express the final result in cents.\""""

    def _round_half_up_dollars(cents: int) -> int:
        from decimal import Decimal, ROUND_HALF_UP
        return int(
            (Decimal(cents) / Decimal(100)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    expected_dollars = (
        _round_half_up_dollars(base_salary_cents)
        + _round_half_up_dollars(sign_on_bonus_cents)
        + _round_half_up_dollars(annual_equity_cents)
    )
    expected_cents = expected_dollars * 100
    assert total_first_year_comp_cents == expected_cents, (
        f"PRD §3.5 per-component-then-sum: expected {expected_cents}, "
        f"got {total_first_year_comp_cents}"
    )


def assert_net_referral_payout_cents(bonuses: list) -> int:
    """Conservation invariant — net_payout_cents := SUM over
    ReferralBonus.total_amount_cents where status == PAID."""
    total = 0
    for rb in bonuses:
        if rb.get("status") == "PAID":
            ta = rb.get("total_amount_cents")
            assert isinstance(ta, int) and ta >= 0
            total += ta
    return total


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_stage",
    "assert_version_incremented_by",
    "assert_recruiter",
    "assert_hiring_manager",
    "assert_interviewer",
    "assert_requisition",
    "assert_candidate",
    "assert_eeo_record",
    "assert_application",
    "assert_interview",
    "assert_interview_feedback",
    "assert_offer",
    "assert_offer_approval_step",
    "assert_background_check",
    "assert_referral_bonus",
    "assert_diversity_goal",
    "assert_offer_total_is_per_component_round",
    "assert_net_referral_payout_cents",
]
