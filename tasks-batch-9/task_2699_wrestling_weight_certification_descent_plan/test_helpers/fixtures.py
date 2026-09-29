"""
Composite setup builders.

The API server is restarted before every individual test, so each test starts
against an empty database with the logical clock back at its start instant.
Every precondition therefore has to be built through the declared endpoints, and
the chain most behaviour hangs off is long: a season has to be created and
opened, a team registered into it, an assessor registered and trained up to the
certification threshold, a wrestler added to the roster, an assessment opened and
finalized so the certified figures exist, and only then can a descent plan be
opened and certified, an event scheduled, an entry accepted and a weigh-in
recorded.

Builders take the client first and return the response bodies, so a test can
stop the chain wherever it needs to and vary any input that matters.  Setup
calls are read leniently: the exact status code of a setup call is the subject of
other tests, not of a fixture.
"""

import os
from typing import Any, Dict, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import ApiClient
from .constants import (
    ASSESSED_AT,
    ASSESSMENT_DAY_INSTANT,
    CANON_BODY_FAT_PCT,
    CANON_MEASURED_WEIGHT_LBS,
    CANON_TARGET_CLASS_LBS,
    CANON_USG_PASS,
    DEFAULT_ASSESSOR_MIN_TRAINING_HOURS,
    DEFAULT_ASSESSOR_NAME,
    DEFAULT_CREDENTIAL_EXPIRY,
    DEFAULT_CREDENTIAL_NUMBER,
    DEFAULT_TEAM_NAME,
    DEFAULT_WRESTLER_GRADE,
    DEFAULT_WRESTLER_NAME,
    EVENT_COMPLETED,
    EVENT_TYPE_TOURNAMENT,
    EVENT_WEIGH_IN_CLOSED,
    EVENT_WEIGH_IN_OPEN,
    METHOD_BIA,
    METHOD_SKINFOLD,
    PLAN_START_DATE,
    SEASON_CLOSED,
    SEASON_NAME,
    SEASON_OPEN,
    SEASON_START_DATE,
    SEX_MALE,
    VARIANT_WEEKLY_STEP,
)
from .test_users import (
    MEDICAL_REVIEWER,
    STATE_OFFICE,
    WEIGH_IN_OFFICIAL,
    assessor_headers,
    coach_headers,
)


# ── The client ───────────────────────────────────────────────────────

@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    base_url = os.environ.get("_PRD_BENCH_API_URL") or os.environ.get("API_BASE_URL")
    return ApiClient(base_url)


# ── The logical clock ────────────────────────────────────────────────

def move_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock to a UTC instant and return the echoed state."""
    response = api.set_clock(factories.clock_payload(to_iso8601), STATE_OFFICE)
    return get_success_data(response)


# ── Season ───────────────────────────────────────────────────────────

def create_season(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create a season, leaving every regulatory constant at its default."""
    payload = factories.season_payload(**overrides)
    return get_success_data(api.create_season(payload, STATE_OFFICE))


def set_season_status(api: ApiClient, season_id: str, status: str) -> Dict[str, Any]:
    response = api.set_season_status(
        season_id, factories.season_status_payload(status), STATE_OFFICE
    )
    return get_success_data(response)


def create_open_season(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create a season and drive it to open, which most work requires."""
    season = create_season(api, **overrides)
    return set_season_status(api, season["id"], SEASON_OPEN)


def close_season(api: ApiClient, season_id: str) -> Dict[str, Any]:
    return set_season_status(api, season_id, SEASON_CLOSED)


def publish_growth_allowance(
    api: ApiClient,
    season_id: str,
    effective_date: str,
    allowance_lbs: float,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish one growth-allowance date; ``allowance_lbs`` is a JSON number."""
    payload = (
        factories.growth_allowance_payload(effective_date, allowance_lbs)
        if note is None
        else factories.growth_allowance_payload(effective_date, allowance_lbs, note)
    )
    return get_success_data(
        api.create_growth_allowance(season_id, payload, STATE_OFFICE)
    )


def run_compliance(api: ApiClient, season_id: str) -> Dict[str, Any]:
    """Run the season-wide compliance sweep."""
    return get_success_data(api.run_compliance(season_id, STATE_OFFICE))


# ── Team ─────────────────────────────────────────────────────────────

def create_team(
    api: ApiClient, season_id: str, school_name: str = DEFAULT_TEAM_NAME
) -> Dict[str, Any]:
    payload = factories.team_payload(season_id, school_name)
    return get_success_data(api.create_team(payload, STATE_OFFICE))


def read_team(api: ApiClient, team_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_team(team_id, STATE_OFFICE))


# ── Assessor ─────────────────────────────────────────────────────────

def create_assessor(
    api: ApiClient,
    full_name: str = DEFAULT_ASSESSOR_NAME,
    credential_number: str = DEFAULT_CREDENTIAL_NUMBER,
    certified_methods: Optional[Sequence[str]] = None,
    certification_expires_on: str = DEFAULT_CREDENTIAL_EXPIRY,
) -> Dict[str, Any]:
    """Register an assessor, who starts provisional until training accumulates."""
    payload = factories.assessor_payload(
        full_name=full_name,
        credential_number=credential_number,
        certified_methods=certified_methods,
        certification_expires_on=certification_expires_on,
    )
    return get_success_data(api.create_assessor(payload, STATE_OFFICE))


def log_training(
    api: ApiClient, assessor_id: str, hours: float, credential_code: Optional[str] = None
) -> Dict[str, Any]:
    """Log completed training hours; ``hours`` is a JSON number."""
    payload = (
        factories.training_record_payload(hours)
        if credential_code is None
        else factories.training_record_payload(hours, credential_code)
    )
    return get_success_data(
        api.create_training_record(assessor_id, payload, STATE_OFFICE)
    )


def create_certified_assessor(
    api: ApiClient,
    full_name: str = DEFAULT_ASSESSOR_NAME,
    credential_number: str = DEFAULT_CREDENTIAL_NUMBER,
    certified_methods: Optional[Sequence[str]] = None,
    hours: float = DEFAULT_ASSESSOR_MIN_TRAINING_HOURS,
    certification_expires_on: str = DEFAULT_CREDENTIAL_EXPIRY,
) -> Dict[str, Any]:
    """Register an assessor and train them up to the season threshold."""
    assessor = create_assessor(
        api,
        full_name=full_name,
        credential_number=credential_number,
        certified_methods=certified_methods,
        certification_expires_on=certification_expires_on,
    )
    log_training(api, assessor["id"], hours)
    return read_assessor(api, assessor["id"])


def read_assessor(api: ApiClient, assessor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_assessor(assessor_id, STATE_OFFICE))


def suspend_assessor(
    api: ApiClient, assessor_id: str, reason: str = "Administrative review."
) -> Dict[str, Any]:
    response = api.suspend_assessor(
        assessor_id, factories.suspension_payload(reason), STATE_OFFICE
    )
    return get_success_data(response)


# ── Wrestler ─────────────────────────────────────────────────────────

def create_wrestler(
    api: ApiClient,
    team_id: str,
    full_name: str = DEFAULT_WRESTLER_NAME,
    sex: str = SEX_MALE,
    grade: int = DEFAULT_WRESTLER_GRADE,
) -> Dict[str, Any]:
    """Add a wrestler to a roster, acting as that team's coach."""
    payload = factories.wrestler_payload(full_name, sex, grade)
    return get_success_data(
        api.create_wrestler(team_id, payload, coach_headers(team_id))
    )


def read_wrestler(api: ApiClient, wrestler_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_wrestler(wrestler_id, STATE_OFFICE))


def wrestler_version(api: ApiClient, wrestler_id: str) -> int:
    """The wrestler's current version, for the plan-creation version pin."""
    return read_wrestler(api, wrestler_id)["version"]


def disqualify_wrestler(
    api: ApiClient,
    wrestler_id: str,
    health_flag_id: str,
    reason: str = "Escalated weigh-in deficit.",
) -> Dict[str, Any]:
    response = api.disqualify_wrestler(
        wrestler_id,
        factories.disqualification_payload(health_flag_id, reason),
        STATE_OFFICE,
    )
    return get_success_data(response)


# ── Assessment ───────────────────────────────────────────────────────

def create_assessment(
    api: ApiClient,
    wrestler_id: str,
    assessor_id: str,
    method: str = METHOD_SKINFOLD,
    assessed_at: str = ASSESSED_AT,
    measured_weight_lbs: float = CANON_MEASURED_WEIGHT_LBS,
    body_fat_pct: float = CANON_BODY_FAT_PCT,
    urine_specific_gravity: float = CANON_USG_PASS,
    **extra: Any,
) -> Dict[str, Any]:
    """Open a draft assessment, acting as the measuring assessor."""
    payload = factories.assessment_payload(
        assessor_id=assessor_id,
        method=method,
        assessed_at=assessed_at,
        measured_weight_lbs=measured_weight_lbs,
        body_fat_pct=body_fat_pct,
        urine_specific_gravity=urine_specific_gravity,
        **extra,
    )
    return get_success_data(
        api.create_assessment(wrestler_id, payload, assessor_headers(assessor_id))
    )


def finalize_assessment(
    api: ApiClient, assessment_id: str, assessor_id: str
) -> Dict[str, Any]:
    """Finalize an assessment, which runs hydration verification and forks it."""
    return get_success_data(
        api.finalize_assessment(assessment_id, assessor_headers(assessor_id))
    )


def create_validated_assessment(
    api: ApiClient,
    wrestler_id: str,
    assessor_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open and finalize a hydrated assessment, producing the certified figures."""
    assessment = create_assessment(api, wrestler_id, assessor_id, **overrides)
    return finalize_assessment(api, assessment["id"], assessor_id)


def read_assessment(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_assessment(assessment_id, STATE_OFFICE))


# ── Appeal ───────────────────────────────────────────────────────────

def file_appeal(
    api: ApiClient,
    assessment_id: str,
    team_id: str,
    reason: str = "Skinfold caliper reading disputed.",
) -> Dict[str, Any]:
    """File a coach appeal against a validated assessment."""
    payload = factories.appeal_payload(team_id, reason)
    return get_success_data(
        api.create_appeal(assessment_id, payload, coach_headers(team_id))
    )


def assign_reviewer(
    api: ApiClient, appeal_id: str, reviewing_assessor_id: str
) -> Dict[str, Any]:
    payload = factories.assign_reviewer_payload(reviewing_assessor_id)
    return get_success_data(
        api.assign_appeal_reviewer(appeal_id, payload, STATE_OFFICE)
    )


def order_retest(api: ApiClient, appeal_id: str, reviewer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.order_appeal_retest(appeal_id, assessor_headers(reviewer_id))
    )


def decide_appeal(
    api: ApiClient,
    appeal_id: str,
    reviewer_id: str,
    outcome: str,
    decision_note: str = "Reviewed against the retest measurement.",
) -> Dict[str, Any]:
    payload = factories.appeal_decision_payload(outcome, decision_note)
    return get_success_data(
        api.decide_appeal(appeal_id, payload, assessor_headers(reviewer_id))
    )


def read_appeal(api: ApiClient, appeal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_appeal(appeal_id, STATE_OFFICE))


# ── Descent plan ─────────────────────────────────────────────────────

def create_plan(
    api: ApiClient,
    wrestler_id: str,
    team_id: str,
    source_assessment_id: str,
    target_class_lbs: int = CANON_TARGET_CLASS_LBS,
    plan_start_date: str = PLAN_START_DATE,
    plan_variant: str = VARIANT_WEEKLY_STEP,
    expected_wrestler_version: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Open a draft plan as the coach, pinning the wrestler's current version."""
    if expected_wrestler_version is None:
        expected_wrestler_version = wrestler_version(api, wrestler_id)
    payload = factories.descent_plan_payload(
        source_assessment_id=source_assessment_id,
        target_class_lbs=target_class_lbs,
        plan_start_date=plan_start_date,
        expected_wrestler_version=expected_wrestler_version,
        plan_variant=plan_variant,
        **extra,
    )
    return get_success_data(
        api.create_descent_plan(wrestler_id, payload, coach_headers(team_id))
    )


def certify_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    """Certify a plan, which generates the whole weekly progression."""
    return get_success_data(api.certify_descent_plan(plan_id, STATE_OFFICE))


def revise_plan(
    api: ApiClient, plan_id: str, team_id: str, plan_start_date: str, **extra: Any
) -> Dict[str, Any]:
    payload = factories.plan_revision_payload(plan_start_date, **extra)
    return get_success_data(
        api.revise_descent_plan(plan_id, payload, coach_headers(team_id))
    )


def read_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_descent_plan(plan_id, STATE_OFFICE))


def milestones_of(api: ApiClient, plan_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Every milestone of a plan, in week-index ascending order."""
    response = api.list_plan_milestones(plan_id, STATE_OFFICE, {"limit": limit})
    rows, _meta = validate_paginated(response)
    return rows


def create_certified_plan(
    api: ApiClient,
    wrestler_id: str,
    team_id: str,
    source_assessment_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a plan and certify it in one step."""
    plan = create_plan(api, wrestler_id, team_id, source_assessment_id, **overrides)
    return certify_plan(api, plan["id"])


# ── Event ────────────────────────────────────────────────────────────

def create_event(
    api: ApiClient,
    season_id: str,
    name: str,
    event_date: str,
    event_type: str = EVENT_TYPE_TOURNAMENT,
    **extra: Any,
) -> Dict[str, Any]:
    """Schedule a competition; the shape parameters default unless supplied."""
    payload = factories.event_payload(name, event_date, event_type, **extra)
    return get_success_data(api.create_event(season_id, payload, STATE_OFFICE))


def set_event_status(api: ApiClient, event_id: str, status: str) -> Dict[str, Any]:
    payload = factories.event_status_payload(status)
    return get_success_data(api.set_event_status(event_id, payload, STATE_OFFICE))


def open_weigh_ins(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return set_event_status(api, event_id, EVENT_WEIGH_IN_OPEN)


def close_weigh_ins(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return set_event_status(api, event_id, EVENT_WEIGH_IN_CLOSED)


def complete_event(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return set_event_status(api, event_id, EVENT_COMPLETED)


def seed_event(api: ApiClient, event_id: str) -> Dict[str, Any]:
    """Seed or reseed the bracket."""
    return get_success_data(api.seed_event(event_id, STATE_OFFICE))


def read_event(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_event(event_id, STATE_OFFICE))


# ── Tournament entry ─────────────────────────────────────────────────

def create_entry(
    api: ApiClient,
    event_id: str,
    wrestler_id: str,
    team_id: str,
    weight_class_lbs: int,
    **extra: Any,
) -> Dict[str, Any]:
    """Enter a wrestler in a weight class, acting as that team's coach."""
    payload = factories.entry_payload(wrestler_id, weight_class_lbs, **extra)
    return get_success_data(
        api.create_entry(event_id, payload, coach_headers(team_id))
    )


def change_weight_class(
    api: ApiClient,
    entry_id: str,
    weight_class_lbs: int,
    expected_entry_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Move an entry to another class, pinning the entry's current version."""
    if expected_entry_version is None:
        expected_entry_version = read_entry(api, entry_id)["version"]
    payload = factories.weight_class_change_payload(
        weight_class_lbs, expected_entry_version
    )
    return get_success_data(
        api.change_entry_weight_class(entry_id, payload, STATE_OFFICE)
    )


def read_entry(api: ApiClient, entry_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_entry(entry_id, STATE_OFFICE))


def entries_of_event(api: ApiClient, event_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    response = api.list_entries(STATE_OFFICE, {"event_id": event_id, "limit": limit})
    rows, _meta = validate_paginated(response)
    return rows


# ── Weigh-in ─────────────────────────────────────────────────────────

def record_weigh_in(
    api: ApiClient,
    event_id: str,
    entry_id: str,
    day_index: int,
    recorded_weight_lbs: float,
) -> Dict[str, Any]:
    """Record an official weigh-in; the scale reading is a JSON number."""
    payload = factories.weigh_in_payload(entry_id, day_index, recorded_weight_lbs)
    return get_success_data(api.create_weigh_in(event_id, payload, WEIGH_IN_OFFICIAL))


# ── Eligibility check ────────────────────────────────────────────────

def run_eligibility_check(
    api: ApiClient, wrestler_id: str, event_id: str, requested_class_lbs: int
) -> Dict[str, Any]:
    """Run and log the certification-database check."""
    payload = factories.eligibility_check_payload(event_id, requested_class_lbs)
    return get_success_data(
        api.create_eligibility_check(wrestler_id, payload, STATE_OFFICE)
    )


# ── Health flag ──────────────────────────────────────────────────────

def flags_of_wrestler(
    api: ApiClient,
    wrestler_id: str,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Every health flag of one wrestler, optionally narrowed by status."""
    params: Dict[str, Any] = {"wrestler_id": wrestler_id, "limit": limit}
    if status is not None:
        params["status"] = status
    rows, _meta = validate_paginated(api.list_health_flags(STATE_OFFICE, params))
    return rows


def review_flag(
    api: ApiClient,
    flag_id: str,
    outcome: str,
    review_note: str = "Medical review completed.",
) -> Dict[str, Any]:
    """Review a flag as the medical reviewer: reviewed, dismissed or escalated."""
    payload = factories.flag_review_payload(outcome, review_note)
    return get_success_data(api.review_health_flag(flag_id, payload, MEDICAL_REVIEWER))


def read_flag(api: ApiClient, flag_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_health_flag(flag_id, STATE_OFFICE))


# ── Program audit ────────────────────────────────────────────────────

def open_audit(
    api: ApiClient,
    season_id: str,
    audit_type: str,
    scoring_variant: str,
    sample_window_start: str,
    **extra: Any,
) -> Dict[str, Any]:
    """Open a program audit, optionally carrying remeasured samples."""
    payload = factories.audit_payload(
        audit_type, scoring_variant, sample_window_start, **extra
    )
    return get_success_data(api.create_audit(season_id, payload, STATE_OFFICE))


def finalize_audit(api: ApiClient, audit_id: str) -> Dict[str, Any]:
    """Score the audit, launching the suspension cascade on failure."""
    return get_success_data(api.finalize_audit(audit_id, STATE_OFFICE))


def read_audit(api: ApiClient, audit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_audit(audit_id, STATE_OFFICE))


# ── Composite scenarios ──────────────────────────────────────────────

class Scenario(dict):
    """A bag of created rows with attribute access, for readable tests."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - a typo in a test
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def open_season_with_team(
    api: ApiClient,
    school_name: str = DEFAULT_TEAM_NAME,
    clock: Optional[str] = ASSESSMENT_DAY_INSTANT,
    **season_overrides: Any,
) -> Scenario:
    """An open season with one registered team, and the clock inside the season."""
    season = create_open_season(api, **season_overrides)
    team = create_team(api, season["id"], school_name)
    if clock is not None:
        move_clock(api, clock)
    return Scenario(
        season=season,
        season_id=season["id"],
        team=team,
        team_id=team["id"],
        coach=coach_headers(team["id"]),
    )


def assessed_wrestler(
    api: ApiClient,
    full_name: str = DEFAULT_WRESTLER_NAME,
    sex: str = SEX_MALE,
    grade: int = DEFAULT_WRESTLER_GRADE,
    measured_weight_lbs: float = CANON_MEASURED_WEIGHT_LBS,
    body_fat_pct: float = CANON_BODY_FAT_PCT,
    urine_specific_gravity: float = CANON_USG_PASS,
    assessed_at: str = ASSESSED_AT,
    method: str = METHOD_SKINFOLD,
    school_name: str = DEFAULT_TEAM_NAME,
    clock: Optional[str] = ASSESSMENT_DAY_INSTANT,
    **season_overrides: Any,
) -> Scenario:
    """The canonical chain up to a finalized assessment.

    A season is opened, a team registered, an assessor trained to the
    certification threshold, a wrestler rostered, and one assessment opened and
    finalized, so the wrestler carries the derived certified figures and is
    provisionally certified pending a plan.
    """
    scenario = open_season_with_team(
        api, school_name=school_name, clock=clock, **season_overrides
    )
    assessor = create_certified_assessor(api)
    wrestler = create_wrestler(api, scenario.team_id, full_name, sex, grade)
    assessment = create_validated_assessment(
        api,
        wrestler["id"],
        assessor["id"],
        method=method,
        assessed_at=assessed_at,
        measured_weight_lbs=measured_weight_lbs,
        body_fat_pct=body_fat_pct,
        urine_specific_gravity=urine_specific_gravity,
    )
    scenario.update(
        assessor=assessor,
        assessor_id=assessor["id"],
        assessor_auth=assessor_headers(assessor["id"]),
        wrestler=read_wrestler(api, wrestler["id"]),
        wrestler_id=wrestler["id"],
        assessment=assessment,
        assessment_id=assessment["id"],
    )
    return scenario


def certified_wrestler(
    api: ApiClient,
    target_class_lbs: int = CANON_TARGET_CLASS_LBS,
    plan_start_date: str = PLAN_START_DATE,
    plan_variant: str = VARIANT_WEEKLY_STEP,
    **kwargs: Any,
) -> Scenario:
    """The canonical chain all the way to a certified plan.

    On top of the finalized assessment a descent plan is opened and certified,
    which is what moves the wrestler to certified and eligible and increments the
    season's certified-wrestler counter.
    """
    scenario = assessed_wrestler(api, **kwargs)
    plan = create_plan(
        api,
        scenario.wrestler_id,
        scenario.team_id,
        scenario.assessment_id,
        target_class_lbs=target_class_lbs,
        plan_start_date=plan_start_date,
        plan_variant=plan_variant,
    )
    plan = certify_plan(api, plan["id"])
    scenario.update(
        plan=plan,
        plan_id=plan["id"],
        wrestler=read_wrestler(api, scenario.wrestler_id),
    )
    return scenario


def entered_wrestler(
    api: ApiClient,
    event_name: str = "Region Duals",
    event_date: str = "2026-12-12",
    weight_class_lbs: int = CANON_TARGET_CLASS_LBS,
    event_type: str = EVENT_TYPE_TOURNAMENT,
    event_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Scenario:
    """A certified wrestler entered in a scheduled event."""
    scenario = certified_wrestler(api, **kwargs)
    event = create_event(
        api,
        scenario.season_id,
        event_name,
        event_date,
        event_type,
        **(event_overrides or {}),
    )
    entry = create_entry(
        api, event["id"], scenario.wrestler_id, scenario.team_id, weight_class_lbs
    )
    scenario.update(
        event=event,
        event_id=event["id"],
        entry=entry,
        entry_id=entry["id"],
    )
    return scenario
