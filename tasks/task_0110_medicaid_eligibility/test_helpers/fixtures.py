"""Composite setup helpers — multi-step preambles tests can reuse.

The Medicaid pipeline is long: state policy → household → applicant(s)
→ income/asset records → application create → submit (snapshots) →
decide (APPROVE → enrollments) → /_clock/advance → /_sweep/redeterminations
→ redetermination submit. Many test claims need the system in a late
pipeline state; these helpers encapsulate the multi-step preambles.

IDENTITY THREADING — PRD §2.1:

All four roles (IntakeWorker, EligibilityCaseworker, AppealsOfficer,
PolicyAdmin) have opaque identity. The shared TEST_USERS constants are
the canonical form for every call. The system records the acting
X-User-ID on FairHearing.officer_id, on Appeal.officer_id, and on
prior EligibilityDeterminations to enforce segregation-of-duties.

Tests that need to exercise segregation-of-duties (re-decide after
DENY; appeal grant/uphold by an officer different from the denying
caseworker) call helpers that accept distinct opaque headers via the
*_headers and *_headers_alt entries in TEST_USERS.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing
downstream assertion failure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    COVERAGE_PERIOD_DAYS,
    SECONDS_PER_DAY,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_applicant_payload,
    create_application_payload,
    create_appeal_payload,
    create_asset_record_payload,
    create_emergency_declaration_payload,
    create_household_payload,
    create_income_record_payload,
    create_state_policy_payload,
    decide_application_payload,
    grant_appeal_payload,
    iso_now,
    iso_offset,
    iso_utc,
    parse_iso,
    random_state_code,
    random_suffix,
    schedule_hearing_payload,
    submit_redetermination_payload,
)
from .test_users import TEST_USERS


# ===========================================================================
# Clock helpers — PRD §2.11 (PolicyAdmin only)
# ===========================================================================
def advance_clock_to(to: str,
                     headers: Optional[Dict[str, str]] = None) -> None:
    """POST /_clock/advance with the supplied ISO 8601 instant.

    PRD §2.11: "An admin-only test-driving capability advances the
    logical clock to a supplied target instant carried in the request
    body as `to`."
    """
    headers = headers or TEST_USERS["policy_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to=to), headers,
    )
    get_success_data(resp)


def server_now_iso(headers: Optional[Dict[str, str]] = None) -> str:
    """Read the server's current logical-clock instant from a cheap
    side-effect-free response meta.

    PRD §2.2: "api_request_timestamp is a server-generated ISO 8601 UTC
    timestamp". The runner-managed clock drives this value, so reading
    it back is the only PRD-faithful way for tests to learn `clock_now`.
    """
    headers = headers or TEST_USERS["policy_admin_headers"]
    # List emergency declarations is GET-only, available to all roles
    # (PRD §4), and never mutates state.
    resp = api_client.list_emergency_declarations(
        headers, params={"limit": 1},
    )
    body = resp.json()
    return body["meta"]["api_request_timestamp"]


def server_now_dt(headers: Optional[Dict[str, str]] = None) -> datetime:
    """As `server_now_iso`, but returns a parsed datetime in UTC."""
    return parse_iso(server_now_iso(headers))


# ===========================================================================
# Tier 1: StatePolicy
# ===========================================================================
def create_state_policy(
    *,
    state_code: Optional[str] = None,
    fpl_year: int = TEST_DEFAULTS["FPL_YEAR"],
    fpl_base_amount: float = TEST_DEFAULTS["FPL_BASE_AMOUNT"],
    fpl_per_member_amount: float = TEST_DEFAULTS["FPL_PER_MEMBER_AMOUNT"],
    magi_income_limit_pct: float = TEST_DEFAULTS["MAGI_INCOME_LIMIT_PCT"],
    asset_test_applies: Optional[bool] = None,
    asset_limit_per_member: Optional[float] = None,
    state_disregard_amount: Optional[float] = None,
    state_exempt_asset_types: Optional[List[str]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /state-policies — PolicyAdmin only per PRD §4."""
    headers = headers or TEST_USERS["policy_admin_headers"]
    code = state_code or random_state_code()
    resp = api_client.create_state_policy(
        create_state_policy_payload(
            state_code=code,
            fpl_year=fpl_year,
            fpl_base_amount=fpl_base_amount,
            fpl_per_member_amount=fpl_per_member_amount,
            magi_income_limit_pct=magi_income_limit_pct,
            asset_test_applies=asset_test_applies,
            asset_limit_per_member=asset_limit_per_member,
            state_disregard_amount=state_disregard_amount,
            state_exempt_asset_types=state_exempt_asset_types,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Household + applicants
# ===========================================================================
def create_household(
    *,
    state_code: str,
    address_line: str = TEST_DEFAULTS["DEFAULT_ADDRESS_LINE"],
    filing_status: str = TEST_DEFAULTS["DEFAULT_FILING_STATUS"],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /households — IntakeWorker only per PRD §4."""
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.create_household(
        create_household_payload(
            state_code=state_code,
            address_line=address_line,
            filing_status=filing_status,
        ),
        headers,
    )
    return get_success_data(resp)


def add_applicant(
    *,
    household: Dict[str, Any],
    full_name: Optional[str] = None,
    date_of_birth: str = TEST_DEFAULTS["DEFAULT_DATE_OF_BIRTH"],
    dependent_status: str = TEST_DEFAULTS["DEFAULT_DEPENDENT_STATUS"],
    is_disabled: Optional[bool] = None,
    is_pregnant: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /households/{id}/applicants — IntakeWorker only per PRD §4."""
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.create_applicant(
        household["id"],
        create_applicant_payload(
            full_name=full_name,
            date_of_birth=date_of_birth,
            dependent_status=dependent_status,
            is_disabled=is_disabled,
            is_pregnant=is_pregnant,
        ),
        headers,
    )
    return get_success_data(resp)


def add_income(
    *,
    household: Dict[str, Any],
    applicant: Dict[str, Any],
    source_type: str = "WAGES",
    gross_amount: float = 1000.00,
    frequency: str = "MONTHLY",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /households/{id}/applicants/{id}/income — IntakeWorker only."""
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.create_income_record(
        household["id"], applicant["id"],
        create_income_record_payload(
            source_type=source_type,
            gross_amount=gross_amount,
            frequency=frequency,
        ),
        headers,
    )
    return get_success_data(resp)


def add_asset(
    *,
    household: Dict[str, Any],
    applicant: Dict[str, Any],
    asset_type: str = "CHECKING",
    market_value: float = 1000.00,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /households/{id}/applicants/{id}/assets — IntakeWorker only."""
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.create_asset_record(
        household["id"], applicant["id"],
        create_asset_record_payload(
            asset_type=asset_type,
            market_value=market_value,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Application creation + submit + decide
# ===========================================================================
def create_application(
    *,
    household: Dict[str, Any],
    program: str = "MAGI_ADULT",
    rule_variant: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /households/{id}/applications — IntakeWorker only.

    PRD §3.3: rule_variant defaults to STATE when omitted.
    """
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.create_application(
        household["id"],
        create_application_payload(
            program=program, rule_variant=rule_variant,
        ),
        headers,
    )
    return get_success_data(resp)


def submit_application(
    *,
    household: Dict[str, Any],
    application: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /households/{id}/applications/{id}/submit — IntakeWorker."""
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.submit_application(
        household["id"], application["id"], headers,
    )
    return get_success_data(resp)


def decide_application(
    *,
    household: Dict[str, Any],
    application: Dict[str, Any],
    decision: str,
    ineligibility_reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /households/{id}/applications/{id}/decide — EligibilityCaseworker.

    PRD §3.3: required input is decision (APPROVE/DENY); optional
    ineligibility_reason when denying.

    Defaults to TEST_USERS["eligibility_caseworker_headers"]. For
    re-decide scenarios after a prior DENY, pass `*_headers_alt` to
    satisfy the segregation-of-duties rule (PRD §2.1).
    """
    headers = headers or TEST_USERS["eligibility_caseworker_headers"]
    resp = api_client.decide_application(
        household["id"], application["id"],
        decide_application_payload(
            decision=decision,
            ineligibility_reason=ineligibility_reason,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4: Composite shortcuts
# ===========================================================================
def setup_basic_household(
    *,
    state_code: Optional[str] = None,
    state_policy_kwargs: Optional[Dict[str, Any]] = None,
    applicants: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Compose: StatePolicy + Household + N applicants.

    Returns (state_policy, household, applicants_list).

    PRD §3.1: head_applicant_id is filled in automatically when the
    first non-EXCLUDED applicant is added.

    `applicants` is a list of dicts each accepted by `add_applicant`
    (`dependent_status`, `date_of_birth`, `is_disabled`, `is_pregnant`,
    `full_name`). Defaults to a single PRIMARY applicant.
    """
    policy_kwargs = state_policy_kwargs or {}
    if state_code is None:
        state_code = random_state_code()
    state_policy = create_state_policy(state_code=state_code, **policy_kwargs)
    household = create_household(state_code=state_code)
    applicants = applicants or [{"dependent_status": "PRIMARY"}]
    created: List[Dict[str, Any]] = []
    for spec in applicants:
        a = add_applicant(household=household, **spec)
        created.append(a)
    # Adding an applicant refreshes the household's computed fields
    # (household_size, head_applicant_id, ...) per PRD §2.4, which bumps
    # the household's version. Refetch so the returned household carries
    # the post-applicants version — otherwise consumer tests that pass
    # `household["version"]` to PATCH see ERR_VERSION_CONFLICT.
    household = get_household(household["id"])
    return state_policy, household, created


def setup_eligible_application(
    *,
    state_code: Optional[str] = None,
    state_policy_kwargs: Optional[Dict[str, Any]] = None,
    program: str = "MAGI_ADULT",
    rule_variant: Optional[str] = None,
    applicants: Optional[List[Dict[str, Any]]] = None,
    incomes: Optional[List[Dict[str, Any]]] = None,
    assets: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[
    Dict[str, Any],  # state_policy
    Dict[str, Any],  # household
    List[Dict[str, Any]],  # applicants
    Dict[str, Any],  # application (submitted)
]:
    """Compose: StatePolicy + Household + applicants + incomes + assets
    + Application(DRAFT) → submit.

    Returns the submitted application (with snapshots populated).
    `incomes` is a list of dicts each accepted by add_income (must
    include `applicant_index` to choose which applicant receives the
    income record). Similarly for `assets`.
    """
    state_policy, household, created = setup_basic_household(
        state_code=state_code,
        state_policy_kwargs=state_policy_kwargs,
        applicants=applicants,
    )
    for inc in incomes or []:
        idx = inc.pop("applicant_index", 0)
        add_income(
            household=household, applicant=created[idx], **inc,
        )
    for ast in assets or []:
        idx = ast.pop("applicant_index", 0)
        add_asset(
            household=household, applicant=created[idx], **ast,
        )
    application = create_application(
        household=household, program=program, rule_variant=rule_variant,
    )
    application = submit_application(
        household=household, application=application,
    )
    return state_policy, household, created, application


def setup_approved_application(
    *,
    state_code: Optional[str] = None,
    state_policy_kwargs: Optional[Dict[str, Any]] = None,
    program: str = "MAGI_ADULT",
    rule_variant: Optional[str] = None,
    applicants: Optional[List[Dict[str, Any]]] = None,
    incomes: Optional[List[Dict[str, Any]]] = None,
    assets: Optional[List[Dict[str, Any]]] = None,
    decider_headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],  # state_policy
    Dict[str, Any],  # household
    List[Dict[str, Any]],  # applicants
    Dict[str, Any],  # application
    Dict[str, Any],  # determination
    List[Dict[str, Any]],  # enrollments
]:
    """Compose: full submit + APPROVE flow.

    Returns (state_policy, household, applicants, application,
    determination, enrollments). Enrollments are fetched via
    GET /enrollments?applicant_id=... per applicant.
    """
    state_policy, household, created, application = setup_eligible_application(
        state_code=state_code,
        state_policy_kwargs=state_policy_kwargs,
        program=program, rule_variant=rule_variant,
        applicants=applicants, incomes=incomes, assets=assets,
    )
    determination = decide_application(
        household=household, application=application, decision="APPROVE",
        headers=decider_headers,
    )
    enrollments: List[Dict[str, Any]] = []
    admin = TEST_USERS["policy_admin_headers"]
    for applicant in created:
        if applicant["dependent_status"] == "EXCLUDED":
            continue
        resp = api_client.list_enrollments(
            admin, params={"applicant_id": applicant["id"]},
        )
        body = resp.json()
        # Pick the most recently created enrollment (created_at desc).
        rows = body.get("data", [])
        if rows:
            # Sort by created_at ascending (PRD default), then take last.
            rows_sorted = sorted(rows, key=lambda r: r["created_at"])
            enrollments.append(rows_sorted[-1])
    return (
        state_policy, household, created, application,
        determination, enrollments,
    )


def setup_denied_application(
    *,
    state_code: Optional[str] = None,
    state_policy_kwargs: Optional[Dict[str, Any]] = None,
    program: str = "MAGI_ADULT",
    rule_variant: Optional[str] = None,
    applicants: Optional[List[Dict[str, Any]]] = None,
    incomes: Optional[List[Dict[str, Any]]] = None,
    assets: Optional[List[Dict[str, Any]]] = None,
    ineligibility_reason: str = "INCOME_EXCEEDS_LIMIT",
    decider_headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],  # state_policy
    Dict[str, Any],  # household
    List[Dict[str, Any]],  # applicants
    Dict[str, Any],  # application (DENIED)
    Dict[str, Any],  # determination (INELIGIBLE)
]:
    """Compose: full submit + DENY flow.

    The decider_headers default to TEST_USERS[
    "eligibility_caseworker_headers"]. Tests that need to exercise the
    re-decide segregation-of-duties rule (PRD §2.1) should pass the
    *_alt variant when re-deciding after appeal grant.
    """
    state_policy, household, created, application = setup_eligible_application(
        state_code=state_code,
        state_policy_kwargs=state_policy_kwargs,
        program=program, rule_variant=rule_variant,
        applicants=applicants, incomes=incomes, assets=assets,
    )
    determination = decide_application(
        household=household, application=application, decision="DENY",
        ineligibility_reason=ineligibility_reason,
        headers=decider_headers,
    )
    return state_policy, household, created, application, determination


# ===========================================================================
# Tier 5: Appeal lifecycle
# ===========================================================================
def file_appeal(
    *,
    determination: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /appeals — IntakeWorker only per PRD §4."""
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.create_appeal(
        create_appeal_payload(determination_id=determination["id"]),
        headers,
    )
    return get_success_data(resp)


def schedule_hearing(
    *,
    appeal: Dict[str, Any],
    officer_id: str,
    scheduled_start: str,
    scheduled_end: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /appeals/{id}/schedule-hearing — AppealsOfficer only.

    Defaults to TEST_USERS["appeals_officer_headers"]. Pass *_alt to
    satisfy SoD when the deciding caseworker was the primary id (PRD
    §2.1).
    """
    headers = headers or TEST_USERS["appeals_officer_headers"]
    resp = api_client.schedule_hearing(
        appeal["id"],
        schedule_hearing_payload(
            officer_id=officer_id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        ),
        headers,
    )
    return get_success_data(resp)


def hold_hearing(
    *,
    fair_hearing: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /fair-hearings/{id}/hold — AppealsOfficer only."""
    headers = headers or TEST_USERS["appeals_officer_headers"]
    resp = api_client.hold_fair_hearing(fair_hearing["id"], headers)
    return get_success_data(resp)


def grant_appeal(
    *,
    appeal: Dict[str, Any],
    outcome_reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /appeals/{id}/grant — AppealsOfficer only."""
    headers = headers or TEST_USERS["appeals_officer_headers"]
    resp = api_client.grant_appeal(
        appeal["id"], grant_appeal_payload(outcome_reason=outcome_reason),
        headers,
    )
    return get_success_data(resp)


def setup_appeal_under_review(
    *,
    denied_setup: Optional[Tuple] = None,
    deny_caseworker_headers: Optional[Dict[str, str]] = None,
    appeals_officer_headers: Optional[Dict[str, str]] = None,
    state_policy_kwargs: Optional[Dict[str, Any]] = None,
    incomes: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[
    Dict[str, Any],  # household
    Dict[str, Any],  # application
    Dict[str, Any],  # determination
    Dict[str, Any],  # appeal
    Dict[str, Any],  # fair_hearing (HELD)
]:
    """Compose: full setup through Appeal.status == UNDER_REVIEW with
    FairHearing.status == HELD. Tests that want to call /grant or
    /uphold start from here.

    PRD §2.1 SoD: deny_caseworker_headers defaults to the primary
    caseworker; appeals_officer_headers defaults to the *_alt officer
    (i.e., a different X-User-ID) so /schedule-hearing and /grant
    succeed without tripping ERR_FORBIDDEN_SAME_ACTOR.
    """
    deny_headers = deny_caseworker_headers or TEST_USERS[
        "eligibility_caseworker_headers"
    ]
    officer_headers = appeals_officer_headers or TEST_USERS[
        "appeals_officer_headers"
    ]
    if denied_setup is None:
        denied_setup = setup_denied_application(
            state_policy_kwargs=state_policy_kwargs or {
                "magi_income_limit_pct": 50.0,
            },
            incomes=incomes or [
                {"source_type": "WAGES", "gross_amount": 100_000.00,
                 "frequency": "ANNUAL"},
            ],
            decider_headers=deny_headers,
        )
    _sp, household, _apps, application, determination = denied_setup
    appeal = file_appeal(determination=determination)
    # Schedule a hearing far enough in the future to be valid but at
    # least a few seconds out so /hold needs a clock advance. Use the
    # officer_id matching the X-User-ID of the scheduling officer
    # (PRD §3.6 stamps officer_id on the appeal from the schedule call).
    officer_id = officer_headers["X-User-ID"]
    start = iso_offset(days=1, base=server_now_dt())
    end = iso_offset(days=1, hours=1, base=server_now_dt())
    fair_hearing = schedule_hearing(
        appeal=appeal, officer_id=officer_id,
        scheduled_start=start, scheduled_end=end,
        headers=officer_headers,
    )
    # Advance clock past scheduled_start to enable /hold.
    advance_clock_to(end)
    fair_hearing = hold_hearing(
        fair_hearing=fair_hearing, headers=officer_headers,
    )
    # Refetch appeal (status now UNDER_REVIEW).
    resp = api_client.get_appeal(appeal["id"], officer_headers)
    appeal = get_success_data(resp)
    return household, application, determination, appeal, fair_hearing


# ===========================================================================
# Tier 6: Redetermination sweep
# ===========================================================================
def advance_to_redetermination_due(
    *,
    enrollment: Dict[str, Any],
) -> None:
    """Advance clock to or past Enrollment.redetermination_due_at so the
    next /_sweep/redeterminations transitions the enrollment to
    REDETERMINATION_DUE (PRD §3.4)."""
    advance_clock_to(enrollment["redetermination_due_at"])


def run_redetermination_sweep(
    headers: Optional[Dict[str, str]] = None,
) -> None:
    """POST /_sweep/redeterminations — PolicyAdmin only per PRD §4."""
    headers = headers or TEST_USERS["policy_admin_headers"]
    resp = api_client.run_redetermination_sweep(headers)
    get_success_data(resp)


def _discover_redetermination_id(
    enrollment_refreshed: Dict[str, Any],
    admin_headers: Dict[str, str],
) -> Optional[str]:
    """Try several PRD-plausible channels to locate the PENDING
    redetermination id for an enrollment that just transitioned to
    REDETERMINATION_DUE.

    PRD §3.4 does not pin a specific channel for clients to discover
    the redetermination_id; each of the following is a faithful
    implementer choice:
      - Surface `redetermination_id` (or a similarly-named pointer
        field) on the Enrollment object.
      - Expose a nested `redetermination` object on the Enrollment.
      - Provide a `GET /redeterminations` list endpoint (not in §4 but
        not forbidden either) with an `enrollment_id` filter.
      - Provide a `GET /enrollments/{id}/redeterminations` nested list.

    Returns the discovered id, or None if no channel exposed it.
    """
    # 1. Field on the enrollment response.
    for key in (
        "redetermination_id",
        "current_redetermination_id",
        "pending_redetermination_id",
        "active_redetermination_id",
    ):
        val = enrollment_refreshed.get(key)
        if val:
            return val
    # 2. Nested object on the enrollment response.
    nested = enrollment_refreshed.get("redetermination")
    if isinstance(nested, dict) and nested.get("id"):
        return nested["id"]
    # 3. Probe a top-level GET /redeterminations list (filtered).
    try:
        resp = api_client._request(
            "GET", "/redeterminations", headers=admin_headers,
            params={"enrollment_id": enrollment_refreshed["id"]},
        )
        if resp.status_code == 200:
            body = resp.json()
            rows = body.get("data", [])
            # Pick the most recent PENDING redetermination tied to this
            # enrollment.
            pending = [
                r for r in rows
                if r.get("status") == "PENDING"
                and r.get("enrollment_id") == enrollment_refreshed["id"]
            ]
            if pending:
                # Sort by created_at ascending then take the last.
                pending.sort(key=lambda r: r.get("created_at", ""))
                return pending[-1]["id"]
    except Exception:
        pass
    # 4. Probe a nested GET /enrollments/{id}/redeterminations.
    try:
        resp = api_client._request(
            "GET",
            f"/enrollments/{enrollment_refreshed['id']}/redeterminations",
            headers=admin_headers,
        )
        if resp.status_code == 200:
            body = resp.json()
            rows = body.get("data", [])
            pending = [r for r in rows if r.get("status") == "PENDING"]
            if pending:
                pending.sort(key=lambda r: r.get("created_at", ""))
                return pending[-1]["id"]
    except Exception:
        pass
    return None


def setup_redetermination_pending(
    *,
    state_policy_kwargs: Optional[Dict[str, Any]] = None,
    incomes: Optional[List[Dict[str, Any]]] = None,
    applicants: Optional[List[Dict[str, Any]]] = None,
    decider_headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any],  # state_policy
    Dict[str, Any],  # household
    List[Dict[str, Any]],  # applicants
    List[Dict[str, Any]],  # enrollments (now REDETERMINATION_DUE)
    Dict[str, Any],  # redetermination (PENDING) for the first enrollment
]:
    """Compose: APPROVE → advance clock → sweep → first PENDING
    Redetermination.

    Returns the freshly created PENDING redetermination for the first
    enrollment. The enrollment is refetched after sweep so its
    coverage_status is REDETERMINATION_DUE.

    PRD §3.4 does not pin a single discovery channel for finding the
    redetermination_id; _discover_redetermination_id tries the
    plausible options. If none is available, the helper raises a
    pytest.skip so consumer tests escalate under the silence-pattern
    category rather than reporting a confusing setup failure.
    """
    state_policy, household, created, _app, _det, enrollments = (
        setup_approved_application(
            state_policy_kwargs=state_policy_kwargs,
            applicants=applicants,
            incomes=incomes,
            decider_headers=decider_headers,
        )
    )
    assert enrollments, "approved application must produce at least one enrollment"
    enrollment = enrollments[0]
    advance_to_redetermination_due(enrollment=enrollment)
    run_redetermination_sweep()
    admin = TEST_USERS["policy_admin_headers"]
    resp = api_client.get_enrollment(enrollment["id"], admin)
    enrollment_refreshed = get_success_data(resp)
    redet_id = _discover_redetermination_id(enrollment_refreshed, admin)
    if redet_id is None:
        import pytest as _pytest
        _pytest.skip(
            "Implementation does not expose a discovery channel for the "
            "PENDING redetermination_id created by /_sweep/"
            "redeterminations; PRD §3.4 names the redetermination but "
            "does not pin a discovery channel (difficulty-coverage-"
            "blocked-by-prd-silence)."
        )
    resp = api_client.get_redetermination(redet_id, admin)
    redetermination = get_success_data(resp)
    enrollments[0] = enrollment_refreshed
    return state_policy, household, created, enrollments, redetermination


# ===========================================================================
# Tier 7: Premium boundary fixtures
# ===========================================================================
def setup_redetermination_for_premium_test(
    *,
    state_code: Optional[str] = None,
    fpl_base_amount: float = 15_000.00,
    fpl_per_member_amount: float = 5_000.00,
    magi_income_limit_pct: float = 138.0,
    applicant_dobs: List[str] = None,
    decider_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """For premium-estimate tests (PRD §3.7). Create a household with
    applicants whose dates of birth pin specific ages at clock_now,
    drive the system to a PENDING Redetermination, and return the
    redetermination plus its household.

    Returns (state_policy, household, applicants, redetermination_pending).
    """
    if applicant_dobs is None:
        applicant_dobs = [TEST_DEFAULTS["DEFAULT_DATE_OF_BIRTH"]]
    applicants_spec = [
        {"dependent_status": "PRIMARY" if i == 0 else "SPOUSE",
         "date_of_birth": dob}
        for i, dob in enumerate(applicant_dobs)
    ]
    incomes = [
        {"applicant_index": 0, "source_type": "WAGES",
         "gross_amount": 100.00, "frequency": "ANNUAL"},
    ]
    state_policy, household, created, _enrollments, redetermination = (
        setup_redetermination_pending(
            state_policy_kwargs={
                "state_code": state_code,
                "fpl_base_amount": fpl_base_amount,
                "fpl_per_member_amount": fpl_per_member_amount,
                "magi_income_limit_pct": magi_income_limit_pct,
            } if state_code is not None else {
                "fpl_base_amount": fpl_base_amount,
                "fpl_per_member_amount": fpl_per_member_amount,
                "magi_income_limit_pct": magi_income_limit_pct,
            },
            applicants=applicants_spec,
            incomes=incomes,
            decider_headers=decider_headers,
        )
    )
    return state_policy, household, created, redetermination


# ===========================================================================
# Tier 8: Emergency declaration
# ===========================================================================
def issue_emergency_declaration(
    *,
    scope: str = "STATE",
    state_code: Optional[str] = None,
    declared_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /emergency-declarations — PolicyAdmin only per PRD §4."""
    headers = headers or TEST_USERS["policy_admin_headers"]
    resp = api_client.create_emergency_declaration(
        create_emergency_declaration_payload(
            scope=scope, state_code=state_code,
            declared_at=declared_at, expires_at=expires_at,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 9: Refetch helpers
# ===========================================================================
def get_household(household_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """GET /households/{id}."""
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.get_household(household_id, headers)
    return get_success_data(resp)


def get_application(household_id: str, application_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    """GET /households/{id}/applications/{id}."""
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.get_application(
        household_id, application_id, headers,
    )
    return get_success_data(resp)


def get_applicant(household_id: str, applicant_id: str,
                  headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    """GET /households/{id}/applicants/{id}."""
    headers = headers or TEST_USERS["intake_worker_headers"]
    resp = api_client.get_applicant(household_id, applicant_id, headers)
    return get_success_data(resp)


def get_enrollment(enrollment_id: str,
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    """GET /enrollments/{id}."""
    headers = headers or TEST_USERS["policy_admin_headers"]
    resp = api_client.get_enrollment(enrollment_id, headers)
    return get_success_data(resp)


def get_redetermination(redetermination_id: str,
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    """GET /redeterminations/{id}."""
    headers = headers or TEST_USERS["policy_admin_headers"]
    resp = api_client.get_redetermination(redetermination_id, headers)
    return get_success_data(resp)


def get_appeal(appeal_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """GET /appeals/{id}."""
    headers = headers or TEST_USERS["appeals_officer_headers"]
    resp = api_client.get_appeal(appeal_id, headers)
    return get_success_data(resp)


def get_fair_hearing(fair_hearing_id: str,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """GET /fair-hearings/{id}."""
    headers = headers or TEST_USERS["appeals_officer_headers"]
    resp = api_client.get_fair_hearing(fair_hearing_id, headers)
    return get_success_data(resp)


__all__ = [
    # Clock
    "advance_clock_to", "server_now_iso", "server_now_dt",
    # Tier 1
    "create_state_policy",
    # Tier 2
    "create_household", "add_applicant", "add_income", "add_asset",
    # Tier 3
    "create_application", "submit_application", "decide_application",
    # Tier 4
    "setup_basic_household", "setup_eligible_application",
    "setup_approved_application", "setup_denied_application",
    # Tier 5
    "file_appeal", "schedule_hearing", "hold_hearing", "grant_appeal",
    "setup_appeal_under_review",
    # Tier 6
    "advance_to_redetermination_due", "run_redetermination_sweep",
    "setup_redetermination_pending",
    # Tier 7
    "setup_redetermination_for_premium_test",
    # Tier 8
    "issue_emergency_declaration",
    # Tier 9
    "get_household", "get_application", "get_applicant",
    "get_enrollment", "get_redetermination", "get_appeal",
    "get_fair_hearing",
]
