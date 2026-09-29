"""Composite setup helpers.

Most interesting claims about this program need the system in a state that takes
between five and twenty API calls to reach — a worker, a claim the adjuster has
cleared for transitional work, a credentialed clinician, a trained supervisor, a
job bank entry, a restriction set walked all the way to ACTIVE, and a placement
walked through routing, funding and activation. These helpers encapsulate those
chains so the tests can concentrate on assertions.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, and uses the lenient `get_success_data` validator so a broken
precondition surfaces as an explicit "Setup step failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO, TEST_DEFAULTS
from .factories import (
    adjuster_authorization_payload,
    auto_match_payload,
    case_review_payload,
    compliance_audit_payload,
    create_claim_payload,
    create_employee_payload,
    create_placement_payload,
    create_restriction_set_payload,
    create_supervisor_payload,
    create_training_record_payload,
    create_transitional_job_payload,
    create_treating_provider_payload,
    decide_directive_payload,
    hours_log_payload,
    reinjury_report_payload,
    vote_payload,
    wage_entry_payload,
)
from .test_users import (
    ADJUSTER_USER_ID,
    COORDINATOR_USER_ID,
    NURSE_USER_ID,
    TEST_USERS,
    make_adjuster_headers,
    make_employee_headers,
    make_supervisor_headers,
    make_treating_provider_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["rtw_coordinator_headers"]
NURSE = TEST_USERS["occ_health_nurse_headers"]
NURSE2 = TEST_USERS["second_nurse_headers"]
ADJUSTER = TEST_USERS["claim_adjuster_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock and return the endpoint's answer."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def reset_clock() -> dict:
    """Pin the clock at the fixed instant it holds at process startup."""
    return set_clock(CLOCK_DEFAULT_ISO)


# ─── Tier 1: individual records ───────────────────────────────────────────

def create_employee(**overrides) -> dict:
    return get_success_data(
        api_client.create_employee(create_employee_payload(**overrides), ADMIN)
    )


def create_treating_provider(**overrides) -> dict:
    return get_success_data(
        api_client.create_treating_provider(create_treating_provider_payload(**overrides), ADMIN)
    )


def create_supervisor(**overrides) -> dict:
    return get_success_data(
        api_client.create_supervisor(create_supervisor_payload(**overrides), ADMIN)
    )


def create_training_record(supervisor_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_training_record(
            supervisor_id, create_training_record_payload(**overrides), ADMIN
        )
    )


def create_transitional_job(supervisor_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_transitional_job(
            create_transitional_job_payload(supervisor_id, **overrides), ADMIN
        )
    )


def open_claim(employee_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_claim(employee_id, create_claim_payload(**overrides), ADMIN)
    )


def authorize_claim(claim_id, adjuster_user_id=ADJUSTER_USER_ID, **overrides) -> dict:
    """The adjuster's authorization step is the only operation that writes claim_status."""
    return get_success_data(
        api_client.set_adjuster_authorization(
            claim_id,
            adjuster_authorization_payload(**overrides),
            make_adjuster_headers(adjuster_user_id),
        )
    )


# ─── Reading current versions (for the concurrency guards) ────────────────

def current_claim_version(claim_id) -> int:
    return get_success_data(api_client.get_claim(claim_id, COORD))["version"]


def current_restriction_set_version(restriction_set_id) -> int:
    return get_success_data(api_client.get_restriction_set(restriction_set_id, COORD))["version"]


def current_case_review_version(case_review_id) -> int:
    return get_success_data(api_client.get_case_review(case_review_id, NURSE))["version"]


# ─── Tier 2: the program baseline ─────────────────────────────────────────

def setup_program(employee_overrides=None, claim_overrides=None, auth_overrides=None,
                  provider_overrides=None, supervisor_overrides=None,
                  training_overrides=None, job_overrides=None) -> dict:
    """Worker + claim cleared for transitional work + credentialed clinician +
    trained supervisor + one OPEN job bank entry.

    Returns a context dict carrying every id the later tiers need.
    """
    employee = create_employee(**(employee_overrides or {}))
    claim = open_claim(employee["id"], **(claim_overrides or {}))
    authorized = authorize_claim(claim["id"], **(auth_overrides or {}))
    provider = create_treating_provider(**(provider_overrides or {}))
    supervisor = create_supervisor(**(supervisor_overrides or {}))
    training = create_training_record(supervisor["id"], **(training_overrides or {}))
    job = create_transitional_job(supervisor["id"], **(job_overrides or {}))
    return {
        "employee": employee,
        "employee_id": employee["id"],
        "claim": authorized,
        "claim_id": claim["id"],
        "claim_version": authorized["version"],
        "adjuster_user_id": (claim_overrides or {}).get("adjuster_user_id", ADJUSTER_USER_ID),
        "provider": provider,
        "provider_id": provider["id"],
        "provider_headers": make_treating_provider_headers(provider["id"]),
        "supervisor": supervisor,
        "supervisor_id": supervisor["id"],
        "supervisor_headers": make_supervisor_headers(supervisor["id"]),
        "employee_headers": make_employee_headers(employee["id"]),
        "training": training,
        "training_id": training["id"],
        "job": job,
        "job_id": job["id"],
    }


# ─── Tier 3: the restriction-intake ladder ────────────────────────────────

def file_restriction_set(ctx, expected_claim_version=None, **overrides) -> dict:
    """File a restriction set underneath the claim, authored by the context's
    clinician. Reads the claim's live version unless one is supplied."""
    version = (
        expected_claim_version
        if expected_claim_version is not None
        else current_claim_version(ctx["claim_id"])
    )
    payload = create_restriction_set_payload(ctx["provider_id"], version, **overrides)
    return get_success_data(
        api_client.create_restriction_set(ctx["claim_id"], payload, ctx["provider_headers"])
    )


def walk_restriction_set_to_active(ctx, restriction_set_id) -> dict:
    """DRAFT -> SUBMITTED -> VERIFIED -> ACTIVE."""
    get_success_data(api_client.submit_restriction_set(restriction_set_id, ctx["provider_headers"]))
    get_success_data(api_client.verify_restriction_set(restriction_set_id, NURSE))
    return get_success_data(api_client.activate_restriction_set(restriction_set_id, COORD))


def walk_restriction_set_to_verified(ctx, restriction_set_id) -> dict:
    """DRAFT -> SUBMITTED -> VERIFIED, stopping short of activation."""
    get_success_data(api_client.submit_restriction_set(restriction_set_id, ctx["provider_headers"]))
    return get_success_data(api_client.verify_restriction_set(restriction_set_id, NURSE))


def setup_active_restriction_set(restriction_overrides=None, **program_kwargs) -> dict:
    """Program baseline plus one restriction set walked all the way to ACTIVE."""
    ctx = setup_program(**program_kwargs)
    filed = file_restriction_set(ctx, **(restriction_overrides or {}))
    activated = walk_restriction_set_to_active(ctx, filed["id"])
    ctx.update({
        "restriction_set": activated,
        "restriction_set_id": filed["id"],
        "restriction_set_version": activated["version"],
    })
    return ctx


# ─── Tier 4: the placement lifecycle ──────────────────────────────────────

def create_placement(ctx, job_id=None, expected_restriction_set_version=None,
                     headers=None, **overrides) -> dict:
    """Create a transitional placement against an explicitly named job."""
    version = (
        expected_restriction_set_version
        if expected_restriction_set_version is not None
        else current_restriction_set_version(ctx["restriction_set_id"])
    )
    payload = create_placement_payload(
        ctx["restriction_set_id"], job_id or ctx["job_id"], version, **overrides
    )
    return get_success_data(api_client.create_placement(payload, headers or COORD))


def setup_proposed_placement(restriction_overrides=None, placement_overrides=None,
                             **program_kwargs) -> dict:
    """Program baseline + ACTIVE restriction set + one PROPOSED placement."""
    ctx = setup_active_restriction_set(restriction_overrides=restriction_overrides,
                                       **program_kwargs)
    placement = create_placement(
        ctx,
        expected_restriction_set_version=ctx["restriction_set_version"],
        **(placement_overrides or {}),
    )
    ctx.update({"placement": placement, "placement_id": placement["id"]})
    return ctx


def route_to_adjuster(ctx, placement_id=None) -> dict:
    """PROPOSED -> ADJUSTER_PENDING; mints the directive and takes the job seat."""
    placement = get_success_data(
        api_client.submit_placement_to_adjuster(placement_id or ctx["placement_id"], COORD)
    )
    if placement_id in (None, ctx.get("placement_id")):
        ctx["directive_id"] = placement["current_adjuster_directive_id"]
    return placement


def setup_routed_placement(**kwargs) -> dict:
    """...through to ADJUSTER_PENDING with a PENDING directive."""
    ctx = setup_proposed_placement(**kwargs)
    ctx["placement"] = route_to_adjuster(ctx)
    return ctx


def decide_directive(ctx, directive_id=None, adjuster_user_id=None, **overrides) -> dict:
    """The adjuster who owns the claim decides the placement's funding."""
    return get_success_data(
        api_client.decide_adjuster_directive(
            directive_id or ctx["directive_id"],
            decide_directive_payload(**overrides),
            make_adjuster_headers(adjuster_user_id or ctx["adjuster_user_id"]),
        )
    )


def setup_authorized_placement(directive_overrides=None, **kwargs) -> dict:
    """...through to ADJUSTER_PENDING with an AUTHORIZED directive."""
    ctx = setup_routed_placement(**kwargs)
    ctx["directive"] = decide_directive(ctx, **(directive_overrides or {}))
    return ctx


def activate_placement(ctx, placement_id=None) -> dict:
    """ADJUSTER_PENDING -> ACTIVE; creates the step-1 progression review."""
    placement = get_success_data(
        api_client.activate_placement(placement_id or ctx["placement_id"], COORD)
    )
    if placement_id in (None, ctx.get("placement_id")):
        ctx["progression_review_id"] = placement["current_progression_review_id"]
    return placement


def setup_active_placement(**kwargs) -> dict:
    """The workhorse fixture: one ACTIVE placement on a two-seat LOW-risk job under
    an ACTIVE restriction set, with an AUTHORIZED directive and a SCHEDULED
    step-1 progression review."""
    ctx = setup_authorized_placement(**kwargs)
    ctx["placement"] = activate_placement(ctx)
    return ctx


# ─── Tier 5: accumulation and targeting helpers ───────────────────────────

def log_hours(ctx, work_date, hours_worked, placement_id=None, headers=None):
    """Upsert one { work_date, hours_worked } observation into logged_hours."""
    return get_success_data(
        api_client.log_placement_hours(
            placement_id or ctx["placement_id"],
            hours_log_payload(work_date=work_date, hours_worked=hours_worked),
            headers or ctx["supervisor_headers"],
        )
    )


def log_hours_across(ctx, work_dates, hours_worked=4, placement_id=None):
    """Log the same daily hours across a list of calendar days."""
    result = None
    for work_date in work_dates:
        result = log_hours(ctx, work_date, hours_worked, placement_id=placement_id)
    return result


def file_compliance_audit(ctx, placement_id=None, headers=None, **overrides) -> dict:
    """File one workplace monitoring observation against a placement."""
    return get_success_data(
        api_client.create_compliance_audit(
            placement_id or ctx["placement_id"],
            compliance_audit_payload(**overrides),
            headers or ctx["supervisor_headers"],
        )
    )


def drive_placement_to_watch(ctx, observed_on="2026-08-01") -> dict:
    """One MINOR finding moves the placement COMPLIANT -> WATCH, which drives the
    claim's posture to RESTRICTED."""
    return file_compliance_audit(
        ctx, observed_on=observed_on, finding_severity="MINOR", finding_code="DOCUMENTATION"
    )


def drive_supervisor_to_suspension(ctx, observed_on="2026-08-04") -> dict:
    """A MAJOR then a CRITICAL finding take the supervisor's effective strike
    points to 3, past the suspension threshold of 2."""
    file_compliance_audit(
        ctx, observed_on=observed_on, finding_severity="MAJOR", finding_code="SUPERVISION_GAP"
    )
    return file_compliance_audit(
        ctx,
        observed_on=observed_on,
        finding_severity="CRITICAL",
        finding_code="RESTRICTION_DEVIATION",
        restriction_deviation_detected=True,
        corrective_action_note="Worker observed lifting 30 lb",
    )


def file_reinjury_report(ctx, placement_id=None, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_reinjury_report(
            placement_id or ctx["placement_id"],
            reinjury_report_payload(**overrides),
            headers or ctx["supervisor_headers"],
        )
    )


def open_progression_review(ctx, review_id=None) -> dict:
    return get_success_data(
        api_client.open_progression_review(review_id or ctx["progression_review_id"], COORD)
    )


def decide_progression_review(ctx, decision, review_id=None, outcome_note=None) -> dict:
    payload = {"decision": decision}
    if outcome_note is not None:
        payload["outcome_note"] = outcome_note
    return get_success_data(
        api_client.decide_progression_review(
            review_id or ctx["progression_review_id"], payload, COORD
        )
    )


def advance_progression_steps(ctx, steps: int) -> dict:
    """Walk the progression ladder up by `steps` ADVANCE decisions, returning the
    placement as it stands afterwards."""
    review_id = ctx["progression_review_id"]
    placement = None
    for step in range(steps):
        open_progression_review(ctx, review_id)
        decide_progression_review(ctx, "ADVANCE", review_id=review_id,
                                  outcome_note=f"Step {step + 1} tolerated")
        placement = get_success_data(api_client.get_placement(ctx["placement_id"], COORD))
        review_id = placement["current_progression_review_id"]
    ctx["progression_review_id"] = review_id
    ctx["placement"] = placement
    return placement


# ─── Tier 5: the case-review panel ────────────────────────────────────────

def convene_panel(ctx, placement_id=None, headers=None, **overrides) -> dict:
    """Convene a case-review panel; the claim's posture is recomputed to FROZEN."""
    panel = get_success_data(
        api_client.create_case_review(
            placement_id or ctx["placement_id"], case_review_payload(**overrides), headers or NURSE
        )
    )
    ctx["case_review_id"] = panel["id"]
    return panel


def open_voting(ctx, case_review_id=None) -> dict:
    return get_success_data(
        api_client.open_case_review_voting(case_review_id or ctx["case_review_id"], NURSE)
    )


def cast_vote(ctx, ballot, headers, case_review_id=None,
              expected_case_review_version=None, rationale=None) -> dict:
    """Cast one panel ballot, reading the panel's live version unless one is given."""
    panel_id = case_review_id or ctx["case_review_id"]
    version = (
        expected_case_review_version
        if expected_case_review_version is not None
        else current_case_review_version(panel_id)
    )
    payload = vote_payload(ballot, version)
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(api_client.cast_case_review_vote(panel_id, payload, headers))


def setup_voting_panel(ctx=None, ballots=("CONTINUE", "CONTINUE", "CONTINUE"),
                       quorum_required=3, trigger_reason="COMPLIANCE_CRITICAL",
                       **kwargs) -> dict:
    """An ACTIVE placement whose panel is in VOTING and already carries `ballots`.

    The ballots are cast in turn by the nurse, the adjuster, the supervisor and the
    treating clinician — never by the coordinator who created the placement, whom
    the segregation-of-duties bar excludes from voting.
    """
    if ctx is None:
        ctx = setup_active_placement(**kwargs)
    convene_panel(ctx, trigger_reason=trigger_reason, quorum_required=quorum_required)
    open_voting(ctx)
    voter_headers = [
        NURSE,
        ADJUSTER,
        ctx["supervisor_headers"],
        ctx["provider_headers"],
    ]
    votes = []
    for index, ballot in enumerate(ballots):
        votes.append(
            cast_vote(ctx, ballot, voter_headers[index % len(voter_headers)],
                      rationale=f"Panel opinion {index + 1}")
        )
    ctx["votes"] = votes
    return ctx


# ─── Tier 5: the wage-differential ledger ─────────────────────────────────

def post_wage_entry(ctx, placement_id=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_wage_entry(
            placement_id or ctx["placement_id"], wage_entry_payload(**overrides), ADMIN
        )
    )


def reverse_wage_entry(entry_id, reason="Period reopened by the adjuster") -> dict:
    return get_success_data(api_client.reverse_wage_entry(entry_id, {"reason": reason}, ADMIN))


def setup_placement_with_logged_week(work_dates=("2026-08-03", "2026-08-04", "2026-08-05",
                                                 "2026-08-06", "2026-08-07"),
                                     hours_worked=4, **kwargs) -> dict:
    """An ACTIVE placement carrying one logged-hours row per named calendar day."""
    ctx = setup_active_placement(**kwargs)
    log_hours_across(ctx, work_dates, hours_worked)
    return ctx


# ─── Tier 5: second actors ────────────────────────────────────────────────

def add_second_worker(ctx, employee_overrides=None, claim_overrides=None,
                      restriction_overrides=None) -> dict:
    """Register a second worker with her own claim and her own ACTIVE restriction
    set authored by the same clinician. Returns a small context of her ids."""
    employee = create_employee(**{
        "full_name": "Rae Lindqvist",
        "employee_number": "EMP-2202",
        "pre_injury_weekly_wage_cents": 118_000,
        **(employee_overrides or {}),
    })
    claim = open_claim(employee["id"], **{
        "claim_number": "CLM-2202",
        "adjuster_user_id": ctx["adjuster_user_id"],
        "injury_date": "2026-06-20",
        **(claim_overrides or {}),
    })
    authorize_claim(claim["id"], adjuster_user_id=ctx["adjuster_user_id"])
    sub_ctx = {
        "claim_id": claim["id"],
        "provider_id": ctx["provider_id"],
        "provider_headers": ctx["provider_headers"],
    }
    filed = file_restriction_set(sub_ctx, **(restriction_overrides or {}))
    activated = walk_restriction_set_to_active(sub_ctx, filed["id"])
    return {
        "employee": employee,
        "employee_id": employee["id"],
        "employee_headers": make_employee_headers(employee["id"]),
        "claim_id": claim["id"],
        "restriction_set_id": filed["id"],
        "restriction_set_version": activated["version"],
    }


def add_second_supervisor(full_name="Jo Park", **overrides) -> dict:
    return create_supervisor(full_name=full_name, **overrides)


def add_second_placement(ctx, job_id=None, **overrides) -> dict:
    """A second placement for the same worker on the same job, created after the
    first, re-reading the restriction set's live version."""
    placement = create_placement(ctx, job_id=job_id, **overrides)
    ctx["second_placement"] = placement
    ctx["second_placement_id"] = placement["id"]
    return placement
