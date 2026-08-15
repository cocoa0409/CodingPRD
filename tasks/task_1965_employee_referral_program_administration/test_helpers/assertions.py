"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_instant_eq(actual: str, expected_iso: str):
    """Compare ISO-8601 UTC timestamps by instant.

    PRD pins the instant each derived/stamped field must hold (e.g. the clock
    reads exactly 2026-08-01T00:00:00Z) and pins three fractional digits only
    for `created_at`/`api_request_timestamp`; the serialization of other
    datetime fields is not fixed, so equality is judged on the instant.
    """
    assert is_iso8601_timestamp(actual), f"not an ISO-8601 UTC timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"instant mismatch: {actual!r} != {expected_iso!r}"
    )


def assert_employee(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("employee_number"), str) and data["employee_number"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("department"), str) and data["department"]
    assert data.get("job_level") in ("IC", "SENIOR", "MANAGER", "DIRECTOR", "EXECUTIVE")
    assert data.get("employment_status") in ("ACTIVE", "TERMINATED")
    assert isinstance(data.get("fraud_strikes"), int)
    assert isinstance(data.get("tenure_days"), int)
    assert isinstance(data.get("referral_suspended"), bool)
    assert isinstance(data.get("annual_provisional_cents"), int)
    assert isinstance(data.get("annual_committed_cents"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_candidate(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]
    assert data.get("global_status") in ("AVAILABLE", "IN_PROCESS", "HIRED", "DEPARTED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_requisition(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("req_number"), str) and data["req_number"]
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("department"), str) and data["department"]
    assert data.get("level") in ("IC", "SENIOR", "MANAGER", "DIRECTOR", "EXECUTIVE")
    assert data.get("status") in ("DRAFT", "OPEN", "PAUSED", "FILLED", "CANCELLED")
    assert isinstance(data.get("openings"), int) and data["openings"] >= 1
    assert isinstance(data.get("filled_count"), int)
    assert isinstance(data.get("open_referral_count"), int)
    assert isinstance(data.get("version"), int)


def assert_policy_version(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ("DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED")
    for f in ("min_tenure_days", "duplicate_cooldown_months", "referral_expiry_days",
              "hire_pct", "retention_days", "clawback_days", "annual_cap_cents",
              "velocity_limit", "tier_ic_cents", "tier_senior_cents",
              "tier_manager_cents", "tier_director_cents", "tier_executive_cents"):
        assert isinstance(data.get(f), int), f"{f} must be int"
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert isinstance(data.get("version"), int)


def assert_campaign(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ("DRAFT", "ACTIVE", "PAUSED", "EXHAUSTED", "ENDED", "CANCELLED")
    assert isinstance(data.get("multiplier_bps"), int)
    assert isinstance(data.get("flat_addon_cents"), int)
    assert isinstance(data.get("budget_cents"), int)
    assert isinstance(data.get("reserved_cents"), int)
    assert isinstance(data.get("spent_cents"), int)
    assert isinstance(data.get("payouts_count"), int)
    assert isinstance(data.get("version"), int)


def assert_referral(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("referrer_id", ""))
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert is_valid_uuid(data.get("job_requisition_id", ""))
    assert data.get("status") in (
        "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "QUALIFIED", "SCREENING",
        "INTERVIEWING", "OFFER_EXTENDED", "HIRED", "COMPLETED",
        "REJECTED_DUPLICATE", "REJECTED_PRIOR_CANDIDATE", "REJECTED_OTHER",
        "NOT_SELECTED", "WITHDRAWN", "EXPIRED", "FORFEITED", "RETENTION_FAILED",
    )
    assert isinstance(data.get("bonus_base_cents"), int)
    assert isinstance(data.get("campaign_uplift_cents"), int)
    assert isinstance(data.get("bonus_total_cents"), int)
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert isinstance(data.get("version"), int)


def assert_milestone(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("referral_id", ""))
    assert data.get("kind") in ("HIRE", "RETENTION")
    assert data.get("status") in ("PENDING", "EARNED", "APPROVED", "BATCHED", "PAID", "FORFEITED", "CLAWED_BACK")
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("version"), int)


def assert_payroll_batch(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("period_label"), str) and data["period_label"]
    assert data.get("status") in ("OPEN", "SEALED", "EXPORTED", "CONFIRMED_PAID", "CANCELLED")
    assert isinstance(data.get("total_gross_cents"), int)
    assert isinstance(data.get("total_withholding_cents"), int)
    assert isinstance(data.get("total_net_cents"), int)
    assert isinstance(data.get("milestone_count"), int)
    assert isinstance(data.get("version"), int)


def assert_abuse_case(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data.get("case_type") in ("SELF_REFERRAL", "VELOCITY", "DUPLICATE_RING", "RESUME_FARM", "MANUAL")
    assert data.get("status") in ("OPEN", "UNDER_REVIEW", "CONFIRMED", "DISMISSED")
    assert isinstance(data.get("risk_weight"), int)
    assert isinstance(data.get("raised_by_user_id"), str)
    assert isinstance(data.get("version"), int)


def assert_tax_profile(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data.get("filing_status") in ("SINGLE", "MARRIED", "HEAD_OF_HOUSEHOLD")
    assert data.get("withholding_method") in ("FLAT", "AGGREGATE")
    assert data.get("status") in ("SUBMITTED", "VERIFIED")
    assert isinstance(data.get("ytd_carryover_cents"), int)
    assert isinstance(data.get("ytd_paid_gross_cents"), int)
    assert isinstance(data.get("version"), int)


def assert_referral_event(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("referral_id", ""))
    assert isinstance(data.get("event_type"), str) and data["event_type"]
    assert isinstance(data.get("actor_user_id"), str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    # append-only: no updated_at, no version
    assert "updated_at" not in data, "ReferralEvent must not carry updated_at"
    assert "version" not in data, "ReferralEvent must not carry version"


def assert_campaign_invariant(campaign: dict):
    """The pinned campaign conservation invariant."""
    total = campaign["reserved_cents"] + campaign["spent_cents"] + campaign["remaining_cents"]
    assert total == campaign["budget_cents"], (
        f"reserved+spent+remaining must equal budget: {campaign['reserved_cents']} + "
        f"{campaign['spent_cents']} + {campaign['remaining_cents']} != {campaign['budget_cents']}"
    )
    assert campaign["reserved_cents"] >= 0
    assert campaign["spent_cents"] >= 0
    assert campaign["remaining_cents"] >= 0


def assert_batch_totals(batch: dict):
    """Payroll batch derived-total invariant: net == gross - withholding."""
    assert batch["total_net_cents"] == batch["total_gross_cents"] - batch["total_withholding_cents"], (
        f"net != gross - withholding: {batch['total_net_cents']} != "
        f"{batch['total_gross_cents']} - {batch['total_withholding_cents']}"
    )
