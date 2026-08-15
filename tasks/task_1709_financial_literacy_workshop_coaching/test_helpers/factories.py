"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS as _D

# Monotonic counter so default emails/codes stay unique within a test run
# (each test starts on an empty database, but factories may be called several
# times inside one test).
_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_curriculum_module_payload(**overrides) -> dict:
    defaults = {
        "module_code": f"{_D['MODULE_CODE']}-{_n()}",
        "title": _D["MODULE_TITLE"],
        "session_count": _D["SESSION_COUNT"],
        "incentive_cents_per_hour": _D["INCENTIVE_CENTS_PER_HOUR"],
        "completion_bonus_cents": _D["COMPLETION_BONUS_CENTS"],
        "completion_threshold": _D["COMPLETION_THRESHOLD"],
    }
    defaults.update(overrides)
    return defaults


def create_coach_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"{_D['COACH_NAME']} {n}",
        "email": f"coach{n}@test.org",
        "max_caseload": _D["COACH_MAX_CASELOAD"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"{_D['PARTICIPANT_NAME']} {n}",
        "email": f"participant{n}@test.org",
        "annual_income_cents": _D["ANNUAL_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_workshop_payload(module_id, coach_id, **overrides) -> dict:
    defaults = {
        "module_id": module_id,
        "coach_id": coach_id,
        "location": _D["WORKSHOP_LOCATION"],
        "start_at": "2026-08-10T10:00:00Z",
        "end_at": "2026-08-10T11:00:00Z",
        "capacity": _D["WORKSHOP_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(workshop_id, participant_id, **overrides) -> dict:
    defaults = {
        "workshop_id": workshop_id,
        "participant_id": participant_id,
    }
    defaults.update(overrides)
    return defaults


def create_coaching_case_payload(participant_id, coach_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "coach_id": coach_id,
        "intake_date": _D["INTAKE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_goal_plan_payload(case_id, expected_case_version, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "monthly_savings_goal_cents": _D["MONTHLY_SAVINGS_GOAL_CENTS"],
        "credit_score_target": _D["CREDIT_SCORE_TARGET"],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_outcome_snapshot_payload(participant_id, recorded_at, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "recorded_at": recorded_at,
    }
    defaults.update(overrides)
    return defaults


def create_match_pool_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "name": f"{_D['POOL_NAME']} {n}",
        "total_funded_cents": _D["POOL_TOTAL_FUNDED_CENTS"],
        "income_threshold_cents": _D["POOL_INCOME_THRESHOLD_CENTS"],
        "match_ratio_below": _D["POOL_MATCH_RATIO_BELOW"],
        "match_ratio_above": _D["POOL_MATCH_RATIO_ABOVE"],
        "per_participant_cap_cents": _D["POOL_PER_PARTICIPANT_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_match_enrollment_payload(participant_id, pool_id, goal_plan_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "pool_id": pool_id,
        "goal_plan_id": goal_plan_id,
        "savings_goal_cents": _D["ENROLLMENT_SAVINGS_GOAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_referral_payload(participant_id, coach_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "coach_id": coach_id,
        "partner_name": _D["PARTNER_NAME"],
        "partner_type": _D["PARTNER_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_funder_report_payload(period_start, period_end, variant, **overrides) -> dict:
    defaults = {
        "period_start": period_start,
        "period_end": period_end,
        "variant": variant,
    }
    defaults.update(overrides)
    return defaults
