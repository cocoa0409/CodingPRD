"""Composite setup helpers for multi-step test prerequisites.

Most interesting test claims for the Legal Case Management API require
the system to be in a specific state that takes 5–15 API calls to reach
(register a partner lawyer, register a case, add a verified plaintiff
and defendant, activate the case, then drive whichever sub-resource the
test cares about). These fixtures encapsulate those preambles.

PRD §2.1: PartnerLawyer / SeniorLawyer / JuniorLawyer roles are
**entity_backed on Lawyer**. Every fixture that creates a Lawyer threads
that lawyer's id into ``make_<role>_headers`` so the resulting header
dictionary's ``X-User-ID`` matches the actual Lawyer.id — a hard-coded
fallback would cause every ownership / segregation check to reject the
request.

Helpers use ``get_success_data`` (lenient) so setup failures surface as
"Setup failed" rather than confusing assertion errors mid-test.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_lawyer_payload,
    create_case_payload,
    create_party_payload,
    create_template_payload,
    create_draft_payload,
    create_hearing_payload,
    create_evidence_payload,
    create_custody_event_payload,
    create_rebuttal_payload,
    create_time_entry_payload,
    adjust_time_entry_payload,
    create_bill_payload,
    payment_event_payload,
    unique_hash,
)
from .test_users import (
    TEST_USERS,
    make_partner_headers,
    make_senior_headers,
    make_junior_headers,
)


# ===========================================================================
# Time helpers
# ===========================================================================
DEFAULT_NOW = "2026-06-01T12:00:00.000Z"


def parse_iso(ts: str) -> datetime:
    s = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def iso_z(dt: datetime) -> str:
    """Format datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_seconds(ts: str, seconds: int) -> str:
    return iso_z(parse_iso(ts) + timedelta(seconds=seconds))


def add_minutes(ts: str, minutes: int) -> str:
    return iso_z(parse_iso(ts) + timedelta(minutes=minutes))


def add_hours(ts: str, hours: int) -> str:
    return iso_z(parse_iso(ts) + timedelta(hours=hours))


def add_days(ts: str, days: int) -> str:
    return iso_z(parse_iso(ts) + timedelta(days=days))


# ===========================================================================
# Clock control
# ===========================================================================
def advance_clock(target_ts: str) -> Dict[str, Any]:
    """Advance the server's logical clock (PRD §2.9, §3.7).

    Lenient — uses get_success_data so callers see a clear "setup failed"
    if the implementation rejects the call.
    """
    res = api_client.advance_clock(
        target_ts, TEST_USERS["system_integrator_headers"]
    )
    return get_success_data(res)


def run_sweep() -> Dict[str, Any]:
    res = api_client.run_sweep(TEST_USERS["system_integrator_headers"])
    return get_success_data(res)


# ===========================================================================
# Lawyer helpers
# ===========================================================================
def register_lawyer(
    *,
    role: str = "PARTNER",
    hourly_rate_cents: int = 30_000,
    client_history: Optional[List[str]] = None,
    bootstrap_partner_headers: Optional[Dict[str, str]] = None,
    full_name: Optional[str] = None,
    bar_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a new Lawyer.

    PRD §4 says ``POST /lawyers`` is PartnerLawyer-only. To satisfy that
    in a fresh environment we use the well-known ``partner_headers_fallback``
    constant ONLY for this single bootstrap step. After the first
    PARTNER lawyer exists, callers should pass ``bootstrap_partner_headers``
    minted via ``make_partner_headers(<existing partner id>)`` so further
    registrations are issued by a real lawyer.

    NOTE: this helper deliberately accepts the fallback for the very
    first lawyer because no real Lawyer.id exists yet to thread through
    ``X-User-ID``. Implementations that compare the registering caller's
    id to an entity must be implemented to allow this bootstrap pattern,
    or tests that need a real partner caller can register the first
    lawyer themselves and then call ``register_lawyer`` with that
    lawyer's headers.
    """
    headers = (
        bootstrap_partner_headers
        or TEST_USERS["partner_headers_fallback"]
    )
    payload = create_lawyer_payload(
        full_name=full_name,
        bar_number=bar_number,
        role=role,
        hourly_rate_cents=hourly_rate_cents,
        client_history=client_history,
    )
    res = api_client.create_lawyer(payload, headers)
    return get_success_data(res)


def make_partner_lawyer(
    *,
    hourly_rate_cents: int = 30_000,
    client_history: Optional[List[str]] = None,
    bootstrap_partner_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Register a PARTNER and return (lawyer, headers) where headers carry
    that lawyer's id as X-User-ID."""
    lawyer = register_lawyer(
        role="PARTNER",
        hourly_rate_cents=hourly_rate_cents,
        client_history=client_history,
        bootstrap_partner_headers=bootstrap_partner_headers,
    )
    return lawyer, make_partner_headers(lawyer["id"])


def make_senior_lawyer(
    *,
    bootstrap_partner_headers: Dict[str, str],
    hourly_rate_cents: int = 20_000,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    lawyer = register_lawyer(
        role="SENIOR",
        hourly_rate_cents=hourly_rate_cents,
        bootstrap_partner_headers=bootstrap_partner_headers,
    )
    return lawyer, make_senior_headers(lawyer["id"])


def make_junior_lawyer(
    *,
    bootstrap_partner_headers: Dict[str, str],
    hourly_rate_cents: int = 10_000,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    lawyer = register_lawyer(
        role="JUNIOR",
        hourly_rate_cents=hourly_rate_cents,
        bootstrap_partner_headers=bootstrap_partner_headers,
    )
    return lawyer, make_junior_headers(lawyer["id"])


# ===========================================================================
# Case helpers
# ===========================================================================
def register_case(
    *,
    lead_lawyer_id: str,
    actor_headers: Dict[str, str],
    case_type: str = "CIVIL",
    claim_amount_cents: int = 5_000_000,
    title: Optional[str] = None,
    client_identity_hash: Optional[str] = None,
    opposing_identity_hash: Optional[str] = None,
    intake_document_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_case_payload(
        lead_lawyer_id=lead_lawyer_id,
        case_type=case_type,
        title=title,
        claim_amount_cents=claim_amount_cents,
        client_identity_hash=client_identity_hash,
        opposing_identity_hash=opposing_identity_hash,
        intake_document_id=intake_document_id,
    )
    res = api_client.create_case(payload, actor_headers)
    return get_success_data(res)


def add_verified_party(
    *,
    case_id: str,
    party_role: str,
    actor_headers: Dict[str, str],
    verifier_headers: Optional[Dict[str, str]] = None,
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Party AND verify identity (two PRD calls — §3.2)."""
    party = get_success_data(api_client.create_party(
        case_id,
        create_party_payload(party_role=party_role, full_name=full_name),
        actor_headers,
    ))
    res = api_client.verify_party_identity(
        party["id"], verifier_headers or actor_headers
    )
    return get_success_data(res)


def activate_case(case_id: str, partner_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.activate_case(case_id, partner_headers)
    return get_success_data(res)


# ===========================================================================
# Tier 2 — Case + parties + activation
# ===========================================================================
def setup_partner_and_active_case(
    *,
    case_type: str = "CIVIL",
    claim_amount_cents: int = 5_000_000,
    partner_rate_cents: int = 30_000,
    bootstrap_partner_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    """Bootstrap path:

      1. Register a PARTNER lawyer via the fallback bootstrap header.
      2. Re-mint partner headers with that lawyer's real id.
      3. Register a Case with that partner as lead.
      4. Add verified PLAINTIFF + DEFENDANT (PRD §3.1 activation
         preconditions).
      5. Activate the case.

    Returns ``(partner_lawyer, partner_headers, active_case)``.
    """
    partner, partner_headers = make_partner_lawyer(
        hourly_rate_cents=partner_rate_cents,
        bootstrap_partner_headers=bootstrap_partner_headers,
    )
    case = register_case(
        lead_lawyer_id=partner["id"],
        actor_headers=partner_headers,
        case_type=case_type,
        claim_amount_cents=claim_amount_cents,
    )
    add_verified_party(
        case_id=case["id"],
        party_role="PLAINTIFF",
        actor_headers=partner_headers,
    )
    add_verified_party(
        case_id=case["id"],
        party_role="DEFENDANT",
        actor_headers=partner_headers,
    )
    active = activate_case(case["id"], partner_headers)
    return partner, partner_headers, active


def setup_three_lawyers_and_active_case(
    *,
    case_type: str = "CIVIL",
    claim_amount_cents: int = 5_000_000,
    partner_rate_cents: int = 30_000,
    senior_rate_cents: int = 20_000,
    junior_rate_cents: int = 10_000,
) -> Dict[str, Any]:
    """Convenience: bootstrap PARTNER, register SENIOR + JUNIOR, register
    a case led by the partner with verified plaintiff/defendant, and
    activate it. Returns a dict with all artifacts."""
    partner, partner_headers, case = setup_partner_and_active_case(
        case_type=case_type,
        claim_amount_cents=claim_amount_cents,
        partner_rate_cents=partner_rate_cents,
    )
    senior, senior_headers = make_senior_lawyer(
        bootstrap_partner_headers=partner_headers,
        hourly_rate_cents=senior_rate_cents,
    )
    junior, junior_headers = make_junior_lawyer(
        bootstrap_partner_headers=partner_headers,
        hourly_rate_cents=junior_rate_cents,
    )
    return {
        "partner": partner,
        "partner_headers": partner_headers,
        "senior": senior,
        "senior_headers": senior_headers,
        "junior": junior,
        "junior_headers": junior_headers,
        "case": case,
    }


# ===========================================================================
# Tier 3 — Document drafts
# ===========================================================================
def register_template(
    *,
    case_type: str = "CIVIL",
    partner_headers: Dict[str, str],
    body_template: str = "Case {{case_number}} — body.",
    variables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload = create_template_payload(
        case_type=case_type,
        body_template=body_template,
        variables=variables,
    )
    res = api_client.create_template(payload, partner_headers)
    return get_success_data(res)


def create_draft(
    *,
    case_id: str,
    template_id: str,
    drafter_lawyer_id: str,
    actor_headers: Dict[str, str],
    variable_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = create_draft_payload(
        case_id=case_id,
        template_id=template_id,
        drafter_lawyer_id=drafter_lawyer_id,
        variable_overrides=variable_overrides,
    )
    res = api_client.create_draft(payload, actor_headers)
    return get_success_data(res)


def setup_draft_in_review(
    *,
    case_type: str = "CIVIL",
) -> Dict[str, Any]:
    """Returns artifacts (partner, senior, junior, case, template, draft)
    with the draft in IN_REVIEW state, drafted by the JUNIOR."""
    bundle = setup_three_lawyers_and_active_case(case_type=case_type)
    template = register_template(
        case_type=case_type,
        partner_headers=bundle["partner_headers"],
    )
    draft = create_draft(
        case_id=bundle["case"]["id"],
        template_id=template["id"],
        drafter_lawyer_id=bundle["junior"]["id"],
        actor_headers=bundle["junior_headers"],
    )
    in_review = get_success_data(api_client.submit_draft_for_review(
        draft["id"], bundle["junior_headers"]
    ))
    bundle.update({"template": template, "draft": in_review})
    return bundle


def setup_draft_locked(
    *,
    case_type: str = "CIVIL",
) -> Dict[str, Any]:
    """Walk the draft all the way to LOCKED.

    Sequence: junior drafts → submit-for-review → senior pass (returns to
    DRAFTING with senior_reviewer_lawyer_id set) → junior submits again
    (back to IN_REVIEW) → partner signoff → partner lock.
    """
    bundle = setup_draft_in_review(case_type=case_type)
    draft_id = bundle["draft"]["id"]
    # Senior pass (back to DRAFTING)
    get_success_data(api_client.senior_pass(
        draft_id, bundle["senior_headers"]
    ))
    # Junior re-submits for review
    get_success_data(api_client.submit_draft_for_review(
        draft_id, bundle["junior_headers"]
    ))
    # Partner sign-off
    get_success_data(api_client.partner_signoff(
        draft_id, bundle["partner_headers"]
    ))
    # Partner lock
    locked = get_success_data(api_client.lock_draft(
        draft_id, bundle["partner_headers"]
    ))
    bundle["draft"] = locked
    return bundle


# ===========================================================================
# Tier 3 — Hearings
# ===========================================================================
def schedule_hearing(
    *,
    case_id: str,
    actor_headers: Dict[str, str],
    scheduled_start: str,
    scheduled_end: str,
    court_room: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_hearing_payload(
        case_id=case_id,
        court_room=court_room,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    res = api_client.create_hearing(payload, actor_headers)
    return get_success_data(res)


# ===========================================================================
# Tier 3 — Evidence + custody chain
# ===========================================================================
def collect_evidence(
    *,
    case_id: str,
    collected_by_lawyer_id: str,
    collected_at: str,
    actor_headers: Dict[str, str],
    evidence_type: str = "DOCUMENTARY",
    case_fact_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload = create_evidence_payload(
        case_id=case_id,
        evidence_type=evidence_type,
        collected_at=collected_at,
        collected_by_lawyer_id=collected_by_lawyer_id,
        case_fact_refs=case_fact_refs,
    )
    res = api_client.create_evidence(payload, actor_headers)
    return get_success_data(res)


def append_custody(
    *,
    evidence_id: str,
    actor_lawyer_id: str,
    action: str,
    occurred_at: str,
    actor_headers: Dict[str, str],
    location: str = "Office Storage",
) -> Dict[str, Any]:
    payload = create_custody_event_payload(
        actor_lawyer_id=actor_lawyer_id,
        action=action,
        occurred_at=occurred_at,
        location=location,
    )
    res = api_client.append_custody_event(evidence_id, payload, actor_headers)
    return get_success_data(res)


def setup_submitted_evidence(
    *,
    case_type: str = "CIVIL",
) -> Dict[str, Any]:
    """Bundle with active case + one Evidence row in SUBMITTED status.

    Adds an EXAMINED custody event to keep the chain non-empty before
    submission so the chain rule still permits the submit call.
    """
    bundle = setup_three_lawyers_and_active_case(case_type=case_type)
    t0 = DEFAULT_NOW
    advance_clock(t0)
    evidence = collect_evidence(
        case_id=bundle["case"]["id"],
        collected_by_lawyer_id=bundle["partner"]["id"],
        collected_at=t0,
        actor_headers=bundle["partner_headers"],
    )
    append_custody(
        evidence_id=evidence["id"],
        actor_lawyer_id=bundle["partner"]["id"],
        action="EXAMINED",
        occurred_at=add_minutes(t0, 5),
        actor_headers=bundle["partner_headers"],
    )
    submitted = get_success_data(api_client.submit_evidence(
        evidence["id"], bundle["partner_headers"]
    ))
    bundle["evidence"] = submitted
    return bundle


# ===========================================================================
# Tier 3 — Time entries + bill issuance
# ===========================================================================
def log_time_entry(
    *,
    case_id: str,
    lawyer_id: str,
    minutes: int,
    actor_headers: Dict[str, str],
    billable: bool = True,
    task_label: str = "Draft motion",
) -> Dict[str, Any]:
    payload = create_time_entry_payload(
        lawyer_id=lawyer_id,
        task_label=task_label,
        minutes=minutes,
        billable=billable,
    )
    res = api_client.create_time_entry(case_id, payload, actor_headers)
    return get_success_data(res)


def adjust_entry_to_zero(
    *,
    time_entry_id: str,
    actor_headers: Dict[str, str],
) -> Dict[str, Any]:
    res = api_client.adjust_time_entry(
        time_entry_id, adjust_time_entry_payload(adjustment_minutes=0),
        actor_headers,
    )
    return get_success_data(res)


def setup_case_at_awaiting_settlement(
    *,
    case_type: str = "CIVIL",
    claim_amount_cents: int = 5_000_000,
    time_entry_minutes: Optional[int] = 60,
    partner_rate_cents: int = 30_000,
) -> Dict[str, Any]:
    """Active case → optionally one ADJUSTED time entry → AWAITING_SETTLEMENT.

    PRD §3.1: 'the case may move from ACTIVE to AWAITING_SETTLEMENT
    provided ... every Hearing on the case has already settled into either
    COMPLETED or CANCELLED' (we add no hearings, so trivially satisfied).
    """
    partner, partner_headers, case = setup_partner_and_active_case(
        case_type=case_type,
        claim_amount_cents=claim_amount_cents,
        partner_rate_cents=partner_rate_cents,
    )
    bundle: Dict[str, Any] = {
        "partner": partner,
        "partner_headers": partner_headers,
        "case": case,
    }
    if time_entry_minutes is not None and time_entry_minutes > 0:
        entry = log_time_entry(
            case_id=case["id"],
            lawyer_id=partner["id"],
            minutes=time_entry_minutes,
            actor_headers=partner_headers,
        )
        adjusted = adjust_entry_to_zero(
            time_entry_id=entry["id"], actor_headers=partner_headers,
        )
        bundle["time_entry"] = adjusted
    awaiting = get_success_data(api_client.await_settlement(
        case["id"], partner_headers
    ))
    bundle["case"] = awaiting
    return bundle


def issue_bill_for(
    *,
    case_id: str,
    partner_headers: Dict[str, str],
    billing_mode: str = "FIXED",
    fixed_fee_cents: Optional[int] = 10_000,
    contingent_rate_bps: Optional[int] = None,
    recovered_amount_cents: Optional[int] = None,
    expense_reimbursement_cents: Optional[int] = None,
    cost_recovery_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Bill and immediately issue it. Returns (draft, issued)."""
    payload = create_bill_payload(
        billing_mode=billing_mode,
        fixed_fee_cents=fixed_fee_cents if billing_mode == "FIXED" else None,
        contingent_rate_bps=(
            contingent_rate_bps if billing_mode == "CONTINGENT" else None
        ),
        recovered_amount_cents=recovered_amount_cents,
        expense_reimbursement_cents=expense_reimbursement_cents,
        cost_recovery_cents=cost_recovery_cents,
    )
    draft = get_success_data(api_client.create_bill(
        case_id, payload, partner_headers
    ))
    issued = get_success_data(api_client.issue_bill(
        draft["id"], partner_headers
    ))
    return draft, issued


def pay_bill(
    *,
    bill_id: str,
    amount_cents: int,
) -> Dict[str, Any]:
    res = api_client.emit_payment(
        payment_event_payload(bill_id=bill_id, amount_cents=amount_cents),
        TEST_USERS["system_integrator_headers"],
    )
    return get_success_data(res)


def setup_paid_case(
    *,
    case_type: str = "CIVIL",
    claim_amount_cents: int = 5_000_000,
    fixed_fee_cents: int = 10_000,
    expense_reimbursement_cents: int = 0,
    cost_recovery_cents: int = 0,
    partner_rate_cents: int = 30_000,
    time_entry_minutes: Optional[int] = 60,
) -> Dict[str, Any]:
    """Active → time entry → AWAITING_SETTLEMENT → bill (FIXED) → issue → pay."""
    bundle = setup_case_at_awaiting_settlement(
        case_type=case_type,
        claim_amount_cents=claim_amount_cents,
        time_entry_minutes=time_entry_minutes,
        partner_rate_cents=partner_rate_cents,
    )
    draft, issued = issue_bill_for(
        case_id=bundle["case"]["id"],
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED",
        fixed_fee_cents=fixed_fee_cents,
        expense_reimbursement_cents=expense_reimbursement_cents,
        cost_recovery_cents=cost_recovery_cents,
    )
    paid = pay_bill(
        bill_id=issued["id"], amount_cents=issued["total_due_cents"],
    )
    bundle["bill"] = paid
    return bundle


def setup_closed_case(
    *,
    case_type: str = "CIVIL",
    claim_amount_cents: int = 5_000_000,
    fixed_fee_cents: int = 10_000,
    expense_reimbursement_cents: int = 0,
    cost_recovery_cents: int = 0,
) -> Dict[str, Any]:
    """Drive the case all the way to CLOSED."""
    bundle = setup_paid_case(
        case_type=case_type,
        claim_amount_cents=claim_amount_cents,
        fixed_fee_cents=fixed_fee_cents,
        expense_reimbursement_cents=expense_reimbursement_cents,
        cost_recovery_cents=cost_recovery_cents,
    )
    closed = get_success_data(api_client.close_case(
        bundle["case"]["id"], bundle["partner_headers"],
    ))
    bundle["case"] = closed
    return bundle


# ===========================================================================
# Difficulty-design composite fixtures
# ===========================================================================
def setup_provisional_vs_final_billed(
    *,
    junior_rate_cents: int = 30_000,
    second_junior_rate_cents: int = 40_000,
) -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN dual_variant_calc instance #1.

    Two JUNIOR lawyers exist, each with a different hourly_rate. A 60-minute
    billable entry is logged by each on the same case. The first entry is
    written off; both are then driven to ADJUSTED. Returns a bundle with
    everything needed to compare provisional vs final-billed totals.
    """
    bundle = setup_three_lawyers_and_active_case(case_type="CIVIL")
    junior2, _ = make_junior_lawyer(
        bootstrap_partner_headers=bundle["partner_headers"],
        hourly_rate_cents=second_junior_rate_cents,
    )
    bundle["junior2"] = junior2
    # First junior's rate is the default 10000 in the bundle — bump it so
    # both juniors are "rate=30000" and "rate=40000" per the scaffold recipe.
    # We register a fresh JUNIOR with the requested 30k rate as L_DRAFTER.
    drafter, _ = make_junior_lawyer(
        bootstrap_partner_headers=bundle["partner_headers"],
        hourly_rate_cents=junior_rate_cents,
    )
    drafter2 = junior2
    bundle["drafter"] = drafter
    bundle["drafter2"] = drafter2
    case_id = bundle["case"]["id"]
    e1 = log_time_entry(
        case_id=case_id,
        lawyer_id=drafter["id"],
        minutes=60,
        actor_headers=bundle["partner_headers"],
    )
    e2 = log_time_entry(
        case_id=case_id,
        lawyer_id=drafter2["id"],
        minutes=60,
        actor_headers=bundle["partner_headers"],
    )
    e1_adj = adjust_entry_to_zero(
        time_entry_id=e1["id"], actor_headers=bundle["partner_headers"],
    )
    e2_adj = adjust_entry_to_zero(
        time_entry_id=e2["id"], actor_headers=bundle["partner_headers"],
    )
    e1_wo = get_success_data(api_client.write_off_time_entry(
        e1_adj["id"], bundle["partner_headers"],
    ))
    bundle["entry_e1"] = e1_wo
    bundle["entry_e2"] = e2_adj
    return bundle


def setup_chronological_replay_recovery_exceeds_fees() -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN dual_variant_calc instance #2.

    A CIVIL case with claim_amount=5,000,000 cents, one billable
    PARTNER 60-minute time entry (rate 30000 → fee 30000), then a bill
    with FIXED fee=20000, expense=0, recovery=100000 (exceeding fees).

    Returns a bundle including the issued+paid bill and the case
    pre-close. Final settlement is asserted by the test.
    """
    bundle = setup_three_lawyers_and_active_case(
        case_type="CIVIL", claim_amount_cents=5_000_000,
        partner_rate_cents=30_000,
    )
    case_id = bundle["case"]["id"]
    entry = log_time_entry(
        case_id=case_id,
        lawyer_id=bundle["partner"]["id"],
        minutes=60,
        actor_headers=bundle["partner_headers"],
    )
    adjust_entry_to_zero(
        time_entry_id=entry["id"],
        actor_headers=bundle["partner_headers"],
    )
    awaiting = get_success_data(api_client.await_settlement(
        case_id, bundle["partner_headers"]
    ))
    bundle["case"] = awaiting
    draft, issued = issue_bill_for(
        case_id=case_id,
        partner_headers=bundle["partner_headers"],
        billing_mode="FIXED",
        fixed_fee_cents=20_000,
        expense_reimbursement_cents=0,
        cost_recovery_cents=100_000,
    )
    paid = pay_bill(
        bill_id=issued["id"], amount_cents=issued["total_due_cents"],
    )
    bundle["bill"] = paid
    return bundle


def setup_two_cases_for_court_fee_civil_vs_arbitration(
    claim_amount_cents: int = 5_000_000,
) -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN combinatorial_formula instance #1.

    Returns ``{partner, partner_headers, civil_case, arbitration_case}``.
    Each case has been activated (verified plaintiff/defendant) and moved
    to AWAITING_SETTLEMENT so a bill can be created.

    Note: ARBITRATION matters require ``claim_amount_cents > 0``
    (PRD §3.1). The default 5,000,000 satisfies that.
    """
    partner, partner_headers, civil = setup_partner_and_active_case(
        case_type="CIVIL", claim_amount_cents=claim_amount_cents,
    )
    arb_case = register_case(
        lead_lawyer_id=partner["id"],
        actor_headers=partner_headers,
        case_type="ARBITRATION",
        claim_amount_cents=claim_amount_cents,
    )
    add_verified_party(
        case_id=arb_case["id"], party_role="PLAINTIFF",
        actor_headers=partner_headers,
    )
    add_verified_party(
        case_id=arb_case["id"], party_role="DEFENDANT",
        actor_headers=partner_headers,
    )
    arb_active = activate_case(arb_case["id"], partner_headers)
    civil_aw = get_success_data(api_client.await_settlement(
        civil["id"], partner_headers
    ))
    arb_aw = get_success_data(api_client.await_settlement(
        arb_active["id"], partner_headers
    ))
    return {
        "partner": partner,
        "partner_headers": partner_headers,
        "civil_case": civil_aw,
        "arbitration_case": arb_aw,
    }


def setup_three_one_minute_billable_entries() -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN combinatorial_formula instance #2.

    Three 1-minute billable entries logged by a JUNIOR with rate=10000
    (cents/hour), all adjusted to 0, on a CIVIL case at AWAITING_SETTLEMENT.
    Bill created with billing_mode=HOURLY. Returns the full bundle
    including the draft bill (test issues it).
    """
    bundle = setup_three_lawyers_and_active_case(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000, junior_rate_cents=10_000,
    )
    case_id = bundle["case"]["id"]
    entries = []
    for _ in range(3):
        e = log_time_entry(
            case_id=case_id,
            lawyer_id=bundle["junior"]["id"],
            minutes=1,
            actor_headers=bundle["partner_headers"],
        )
        adj = adjust_entry_to_zero(
            time_entry_id=e["id"],
            actor_headers=bundle["partner_headers"],
        )
        entries.append(adj)
    awaiting = get_success_data(api_client.await_settlement(
        case_id, bundle["partner_headers"]
    ))
    bundle["case"] = awaiting
    bill_payload = create_bill_payload(
        billing_mode="HOURLY",
    )
    bill = get_success_data(api_client.create_bill(
        case_id, bill_payload, bundle["partner_headers"]
    ))
    bundle["entries"] = entries
    bundle["bill"] = bill
    return bundle


def setup_total_due_clamp() -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN combinatorial_formula instance #3.

    CIVIL case, claim=1,000,000 cents (= $10k bracket1 boundary, fee=50000
    cents), bill with billing_mode=FIXED, fixed_fee_cents=0 (so attorney
    fee is 0), expense=10000, recovery=200000.

    Returns the bundle with a draft bill ready for the test to issue.

    NOTE: PRD §3.6 requires ``billing_mode=FIXED`` to carry
    ``fixed_fee_cents > 0``. Setting it to 0 would surface
    ERR_BILLING_MODE_INVALID. We therefore use HOURLY mode with no
    billable entries — which yields attorney_fee=0 by aggregation —
    instead of FIXED 0 to stay PRD-faithful.
    """
    bundle = setup_three_lawyers_and_active_case(
        case_type="CIVIL", claim_amount_cents=1_000_000,
        partner_rate_cents=10_000,
    )
    case_id = bundle["case"]["id"]
    awaiting = get_success_data(api_client.await_settlement(
        case_id, bundle["partner_headers"]
    ))
    bundle["case"] = awaiting
    bill_payload = create_bill_payload(
        billing_mode="HOURLY",
        expense_reimbursement_cents=10_000,
        cost_recovery_cents=200_000,
    )
    bill = get_success_data(api_client.create_bill(
        case_id, bill_payload, bundle["partner_headers"]
    ))
    bundle["bill"] = bill
    return bundle


# ===========================================================================
# Hearing-conflict fixtures
# ===========================================================================
def setup_hearing_baseline(
    *,
    base_ts: str = "2026-06-01T08:00:00.000Z",
) -> Dict[str, Any]:
    """Active case + advanced clock to base_ts. Returns bundle including
    the base timestamp and a partner for scheduling further hearings."""
    bundle = setup_three_lawyers_and_active_case(case_type="CIVIL")
    advance_clock(base_ts)
    bundle["base_ts"] = base_ts
    return bundle


__all__ = [
    "DEFAULT_NOW",
    "parse_iso",
    "iso_z",
    "add_seconds",
    "add_minutes",
    "add_hours",
    "add_days",
    "advance_clock",
    "run_sweep",
    "register_lawyer",
    "make_partner_lawyer",
    "make_senior_lawyer",
    "make_junior_lawyer",
    "register_case",
    "add_verified_party",
    "activate_case",
    "setup_partner_and_active_case",
    "setup_three_lawyers_and_active_case",
    "register_template",
    "create_draft",
    "setup_draft_in_review",
    "setup_draft_locked",
    "schedule_hearing",
    "collect_evidence",
    "append_custody",
    "setup_submitted_evidence",
    "log_time_entry",
    "adjust_entry_to_zero",
    "setup_case_at_awaiting_settlement",
    "issue_bill_for",
    "pay_bill",
    "setup_paid_case",
    "setup_closed_case",
    "setup_provisional_vs_final_billed",
    "setup_chronological_replay_recovery_exceeds_fees",
    "setup_two_cases_for_court_fee_civil_vs_arbitration",
    "setup_three_one_minute_billable_entries",
    "setup_total_due_clamp",
    "setup_hearing_baseline",
]
