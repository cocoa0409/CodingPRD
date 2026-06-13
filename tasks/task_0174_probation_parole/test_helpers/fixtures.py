"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the case to be in a specific posture/state that
takes 5-15 API calls to reach (open officer -> open supervisee -> create
assessment -> adopt -> activate, then accumulate points/balances). These helpers
encapsulate those preambles so tests focus on assertions.

Uses get_success_data() (lenient validator) internally so a setup failure shows
a clear "Setup failed" error rather than a confusing assertion failure.

IDENTITY THREADING (PRD §2.1): Officer is entity_backed. After creating an
Officer, every officer-acting call must use make_officer_headers(officer["id"]),
never the shared fallback, so filed_by_officer_id / ownership comparisons match.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_officer_payload,
    create_supervisee_payload,
    create_risk_assessment_payload,
    create_condition_payload,
    create_check_in_payload,
    create_violation_payload,
    create_obligation_payload,
    create_payment_payload,
    create_transfer_payload,
    create_early_termination_payload,
    domain_scores_uniform,
    domain_scores_for_total,
)
from .test_users import (
    make_officer_headers,
    make_judge_headers,
    make_compact_admin_headers,
)

# Monotonic counters so docket/badge numbers stay unique within one test even
# when a fixture is invoked multiple times. Each test runs against a fresh DB
# (server restart), but a single test may build several supervisees/officers.
_BADGE_SEQ = itertools.count(1)
_DOCKET_SEQ = itertools.count(1)


def _next_badge() -> str:
    return f"B-{next(_BADGE_SEQ):06d}"


def _next_docket() -> str:
    return f"DK-{next(_DOCKET_SEQ):06d}"


# ─── Tier 0: primitives ──────────────────────────────────────────────────
def create_officer(role_type: str = "PROBATION", active: bool = True, **overrides):
    """Register an Officer (CompactAdministrator-only op). Returns the Officer dict."""
    payload = create_officer_payload(
        badge_number=_next_badge(), role_type=role_type, active=active, **overrides
    )
    res = api_client.create_officer(payload, make_compact_admin_headers())
    return get_success_data(res)


def open_supervisee(officer_id: str, supervision_type: str = "PROBATION",
                    docket_number: str = None, **overrides):
    """Open a case in INTAKE. Acts as the assigned officer (entity-backed id).

    A caller-supplied `docket_number` (e.g. to force a duplicate) takes
    precedence over the auto-generated unique docket.
    """
    payload = create_supervisee_payload(
        officer_id,
        docket_number=docket_number if docket_number is not None else _next_docket(),
        supervision_type=supervision_type,
        **overrides,
    )
    res = api_client.create_supervisee(payload, make_officer_headers(officer_id))
    return get_success_data(res)


def add_draft_assessment(supervisee_id: str, officer_id: str,
                         total: int = None, domain_scores: dict = None, **overrides):
    """Create a DRAFT LSI-R assessment. Provide `total` to target a band, or a
    full `domain_scores` map, otherwise defaults to a uniform low (total 10)."""
    if domain_scores is None:
        domain_scores = (domain_scores_for_total(total) if total is not None
                         else domain_scores_uniform(1))
    payload = create_risk_assessment_payload(domain_scores=domain_scores, **overrides)
    res = api_client.create_risk_assessment(
        supervisee_id, payload, make_officer_headers(officer_id)
    )
    return get_success_data(res)


def adopt_assessment(supervisee_id: str, ra_id: str, officer_id: str):
    res = api_client.adopt_risk_assessment(
        supervisee_id, ra_id, make_officer_headers(officer_id)
    )
    return get_success_data(res)


# ─── Tier 1: State progression to ACTIVE ─────────────────────────────────
def setup_active_supervisee(level_total: int = 10, supervision_type: str = "PROBATION",
                            ordered_term_months: int = 24,
                            supervision_start_date: str = "2025-01-01T00:00:00.000Z",
                            override_level: str = None, override_reason: str = None,
                            sentence_state_code: str = "CA"):
    """Officer + supervisee + adopted assessment + ACTIVE.

    `level_total` controls the adopted assessment's total_score (and thus the
    derived supervision_level). `override_level`/`override_reason` exercise the
    clinical-override variant. Returns (officer, supervisee_after_activate).
    """
    officer = create_officer(role_type=supervision_type)
    sup = open_supervisee(
        officer["id"], supervision_type=supervision_type,
        ordered_term_months=ordered_term_months,
        supervision_start_date=supervision_start_date,
        sentence_state_code=sentence_state_code,
    )
    extra = {}
    if override_level is not None:
        extra["override_level"] = override_level
        extra["override_reason"] = override_reason or "documented risk"
    ra = add_draft_assessment(sup["id"], officer["id"], total=level_total, **extra)
    adopt_assessment(sup["id"], ra["id"], officer["id"])
    act = api_client.activate_supervisee(sup["id"], make_officer_headers(officer["id"]))
    return officer, get_success_data(act)


def setup_intake_supervisee(level_total: int = 10, supervision_type: str = "PROBATION",
                            **overrides):
    """Officer + supervisee in INTAKE with one ADOPTED assessment (so activation
    would be permitted). Returns (officer, supervisee, adopted_assessment)."""
    officer = create_officer(role_type=supervision_type)
    sup = open_supervisee(officer["id"], supervision_type=supervision_type, **overrides)
    ra = add_draft_assessment(sup["id"], officer["id"], total=level_total)
    adopt_assessment(sup["id"], ra["id"], officer["id"])
    return officer, sup, ra


# ─── Tier 2: Conditions ──────────────────────────────────────────────────
def add_condition(supervisee_id: str, officer_id: str,
                  condition_type: str = "CURFEW",
                  minimum_level_required: str = None, **overrides):
    extra = dict(overrides)
    if minimum_level_required is not None:
        extra["minimum_level_required"] = minimum_level_required
    payload = create_condition_payload(condition_type=condition_type, **extra)
    res = api_client.create_condition(
        supervisee_id, payload, make_officer_headers(officer_id)
    )
    return get_success_data(res)


def add_active_condition(supervisee_id: str, officer_id: str,
                         condition_type: str = "EMPLOYMENT",
                         minimum_level_required: str = "ADMINISTRATIVE", **overrides):
    """Propose then activate a condition. Requires supervisee ACTIVE and level
    >= minimum_level_required. Returns the activated condition dict."""
    cond = add_condition(
        supervisee_id, officer_id, condition_type=condition_type,
        minimum_level_required=minimum_level_required, **overrides,
    )
    res = api_client.activate_condition(
        supervisee_id, cond["id"], make_officer_headers(officer_id)
    )
    return get_success_data(res)


# ─── Tier 3: Violations / sustaining (with segregation of duties) ─────────
def file_violation(supervisee_id: str, officer_id: str, violation_class: str,
                   **overrides):
    payload = create_violation_payload(violation_class, officer_id, **overrides)
    res = api_client.create_violation(
        supervisee_id, payload, make_officer_headers(officer_id)
    )
    return get_success_data(res)


def sustain_violation(supervisee_id: str, v_id: str, judge_user_id: str = "judge-1"):
    """Sustain as a judge whose opaque id differs from the filing officer."""
    res = api_client.sustain_violation(
        supervisee_id, v_id, make_judge_headers(judge_user_id)
    )
    return get_success_data(res)


def file_and_sustain(supervisee_id: str, officer_id: str, violation_class: str,
                     judge_user_id: str = "judge-1"):
    """File a violation then sustain it. Returns the sustained violation dict."""
    v = file_violation(supervisee_id, officer_id, violation_class)
    return sustain_violation(supervisee_id, v["id"], judge_user_id=judge_user_id)


def setup_supervisee_with_points(target_points_class_sequence,
                                 supervision_type: str = "PROBATION",
                                 ordered_term_months: int = 36):
    """ACTIVE supervisee, then file+sustain a sequence of violation classes to
    accumulate cumulative_violation_points deterministically.

    `target_points_class_sequence` is a list of violation_class strings sustained
    in order. Returns (officer, supervisee_id, [sustained_violation_dicts]).
    """
    officer, sup = setup_active_supervisee(
        level_total=30, supervision_type=supervision_type,
        ordered_term_months=ordered_term_months,
    )
    sustained = []
    for vclass in target_points_class_sequence:
        sustained.append(file_and_sustain(sup["id"], officer["id"], vclass))
    return officer, sup["id"], sustained


# ─── Tier 4: Financial obligations / payments ────────────────────────────
def add_obligation(supervisee_id: str, officer_id: str, obligation_type: str,
                   principal_cents: int, **overrides):
    payload = create_obligation_payload(obligation_type, principal_cents, **overrides)
    res = api_client.create_obligation(
        supervisee_id, payload, make_officer_headers(officer_id)
    )
    return get_success_data(res)


def make_payment(supervisee_id: str, officer_id: str, amount_cents: int, **overrides):
    payload = create_payment_payload(amount_cents, **overrides)
    res = api_client.create_payment(
        supervisee_id, payload, make_officer_headers(officer_id)
    )
    return get_success_data(res)


def setup_supervisee_with_obligation(obligation_type: str = "RESTITUTION",
                                     principal_cents: int = 10000,
                                     supervision_type: str = "PROBATION",
                                     **ob_overrides):
    """ACTIVE supervisee + one OPEN obligation. Returns (officer, supervisee, obligation)."""
    officer, sup = setup_active_supervisee(supervision_type=supervision_type)
    ob = add_obligation(
        sup["id"], officer["id"], obligation_type, principal_cents, **ob_overrides
    )
    return officer, sup, ob


# ─── Tier 5: Transfers ───────────────────────────────────────────────────
def request_transfer(supervisee_id: str, officer_id: str, receiving_state_code: str,
                     expected_supervisee_version: int):
    payload = create_transfer_payload(
        receiving_state_code, expected_supervisee_version
    )
    res = api_client.create_transfer(
        supervisee_id, payload, make_officer_headers(officer_id)
    )
    return get_success_data(res)


def current_version(supervisee_id: str, officer_id: str) -> int:
    res = api_client.get_supervisee(supervisee_id, make_officer_headers(officer_id))
    return get_success_data(res)["version"]


def setup_supervisee_with_open_transfer(supervision_type: str = "PROBATION",
                                        receiving_state_code: str = "NV"):
    """ACTIVE supervisee with one REQUESTED transfer. Returns
    (officer, supervisee_after_activate, transfer)."""
    officer, sup = setup_active_supervisee(supervision_type=supervision_type)
    xfer = request_transfer(
        sup["id"], officer["id"], receiving_state_code, sup["version"]
    )
    return officer, sup, xfer


# ─── Tier 6: Check-ins (clock-driven) ────────────────────────────────────
def set_clock(iso: str, officer_id: str = None):
    """Set the server clock. Any role may; use officer headers for consistency."""
    headers = make_officer_headers(officer_id) if officer_id else make_judge_headers()
    return get_success_data(api_client.set_clock(iso, headers))


def add_check_in(supervisee_id: str, officer_id: str, scheduled_for: str,
                 window_minutes: int = 60, **overrides):
    payload = create_check_in_payload(
        scheduled_for, window_minutes=window_minutes, **overrides
    )
    res = api_client.create_check_in(
        supervisee_id, payload, make_officer_headers(officer_id)
    )
    return get_success_data(res)


def attend_check_in(supervisee_id: str, ci_id: str, officer_id: str, attended_at: str):
    res = api_client.attend_check_in(
        supervisee_id, ci_id, {"attended_at": attended_at},
        make_officer_headers(officer_id),
    )
    return get_success_data(res)


# ─── Tier 7: Early termination ───────────────────────────────────────────
def file_early_termination(supervisee_id: str, officer_id: str, requested_on: str):
    payload = create_early_termination_payload(requested_on)
    res = api_client.create_early_termination(
        supervisee_id, payload, make_officer_headers(officer_id)
    )
    return get_success_data(res)


# ─── Tier 8: Terminal-state shortcuts ────────────────────────────────────
def setup_completed_supervisee(supervision_type: str = "PROBATION"):
    """ACTIVE supervisee with zero balances and no open violations, completed by
    a judge. Returns (officer, supervisee_id). The case is in COMPLETED."""
    officer, sup = setup_active_supervisee(supervision_type=supervision_type)
    res = api_client.complete_supervisee(sup["id"], make_judge_headers())
    get_success_data(res)
    return officer, sup["id"]
