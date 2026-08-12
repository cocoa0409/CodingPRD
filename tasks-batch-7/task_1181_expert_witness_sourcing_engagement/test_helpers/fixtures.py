"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the server is restarted before every test, so each test starts empty).
Uses get_success_data() (lenient) so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_expert_payload, create_case_payload, create_engagement_request_payload,
    create_conflict_check_payload, create_credential_review_payload,
    create_engagement_payload, create_document_production_payload,
    create_report_payload, create_venue_payload, create_schedule_payload,
    create_invoice_payload, create_evaluation_payload,
)
from .test_users import TEST_USERS, make_expert_headers, make_case_manager_headers

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]           # X-User-ID "cm-1"
CONFLICT = TEST_USERS["conflict_analyst_headers"]
CREDENTIAL = TEST_USERS["credential_analyst_headers"]
BILLING = TEST_USERS["billing_reviewer_headers"]  # X-User-ID "br-1"


# ─── Tier 1: single-entity creation ─────────────────────────────────────────

def create_expert(full_name="Test Expert", specialty_area="med", **overrides) -> dict:
    res = api_client.create_expert(
        create_expert_payload(full_name=full_name, specialty_area=specialty_area, **overrides), ADMIN)
    return get_success_data(res)


def create_case(budget_cents=1_000_000, trial_date="2026-09-01T00:00:00Z",
                report_deadline="2026-07-01T17:00:00Z", cm_user_id="cm-1", **overrides) -> dict:
    res = api_client.create_case(
        create_case_payload(budget_cents=budget_cents, trial_date=trial_date,
                            report_deadline=report_deadline, **overrides),
        make_case_manager_headers(cm_user_id))
    return get_success_data(res)


def create_venue(name="Suite 4A", location="NYC", **overrides) -> dict:
    return get_success_data(api_client.create_venue(
        create_venue_payload(name=name, location=location, **overrides), ADMIN))


def open_request(case_id, specialty_area="med", cm_user_id="cm-1", **overrides) -> dict:
    return get_success_data(api_client.create_engagement_request(
        create_engagement_request_payload(case_id, specialty_area=specialty_area, **overrides),
        make_case_manager_headers(cm_user_id)))


def screen_candidate(request_id, expert_id, conflict_outcome="CLEARED",
                     credential_outcome="PASSED", adverse_parties=None,
                     conflict_rationale="ok", credential_daubert_notes=None):
    """Open + resolve a conflict check and a credential review for (request, expert).
    Returns (conflict_check, credential_review) in their resolved states."""
    cc = get_success_data(api_client.create_conflict_check(
        request_id, create_conflict_check_payload(
            expert_id, adverse_parties=adverse_parties if adverse_parties is not None else []),
        CONFLICT))
    if conflict_outcome is not None:
        cc = get_success_data(api_client.resolve_conflict_check(
            cc["id"], {"outcome": conflict_outcome, "rationale": conflict_rationale},
            CONFLICT if conflict_outcome != "WAIVED" else ADMIN))
    cr = get_success_data(api_client.create_credential_review(
        request_id, create_credential_review_payload(expert_id), CREDENTIAL))
    if credential_outcome is not None:
        payload = {"outcome": credential_outcome}
        if credential_daubert_notes is not None:
            payload["daubert_notes"] = credential_daubert_notes
        cr = get_success_data(api_client.resolve_credential_review(cr["id"], payload, CREDENTIAL))
    return cc, cr


# ─── Tier 2: engagement lifecycle progression ───────────────────────────────

def create_draft_engagement(request_id, expert_id, hourly_rate_cents=40_000,
                            retainer_cents=0, expense_cap_cents=0, cm_user_id="cm-1") -> dict:
    return get_success_data(api_client.create_engagement(
        create_engagement_payload(request_id, expert_id, hourly_rate_cents=hourly_rate_cents,
                                  retainer_cents=retainer_cents, expense_cap_cents=expense_cap_cents),
        make_case_manager_headers(cm_user_id)))


def propose_engagement(engagement_id, cm_user_id="cm-1", payload=None) -> dict:
    return get_success_data(api_client.propose_engagement(
        engagement_id, payload or {}, make_case_manager_headers(cm_user_id)))


def sign_engagement(engagement_id, expert_id) -> dict:
    return get_success_data(api_client.sign_engagement(engagement_id, make_expert_headers(expert_id)))


def fund_retainer(engagement_id, amount_cents, cm_user_id="cm-1") -> dict:
    return get_success_data(api_client.fund_retainer(
        engagement_id, {"amount_cents": amount_cents}, make_case_manager_headers(cm_user_id)))


def close_engagement(engagement_id, cm_user_id="cm-1") -> dict:
    return get_success_data(api_client.close_engagement(engagement_id, make_case_manager_headers(cm_user_id)))


def terminate_engagement(engagement_id, reason="settlement", cm_user_id="cm-1") -> dict:
    return get_success_data(api_client.terminate_engagement(
        engagement_id, {"reason": reason}, make_case_manager_headers(cm_user_id)))


# ─── Tier 3: composite scenario (expert + case + request + screening + engagement) ───

def setup_scenario(expert_overrides=None, case_overrides=None, engagement_overrides=None,
                   specialty_area="med", cm_user_id="cm-1",
                   conflict_outcome="CLEARED", credential_outcome="PASSED",
                   adverse_parties=None, target_state="ACTIVE", fund=True):
    """
    Full pipeline: expert -> case -> request -> cleared/passed screening -> engagement,
    then walk the engagement to `target_state` (DRAFT, PROPOSED, SIGNED, ACTIVE, CLOSED).
    Returns dict with keys: expert, case, request, conflict_check, credential_review, engagement.
    """
    expert = create_expert(specialty_area=specialty_area, **(expert_overrides or {}))
    case = create_case(cm_user_id=cm_user_id, **(case_overrides or {}))
    request = open_request(case["id"], specialty_area=specialty_area, cm_user_id=cm_user_id)
    cc, cr = screen_candidate(request["id"], expert["id"],
                              conflict_outcome=conflict_outcome,
                              credential_outcome=credential_outcome,
                              adverse_parties=adverse_parties)
    engagement = create_draft_engagement(
        request["id"], expert["id"], cm_user_id=cm_user_id, **(engagement_overrides or {}))

    order = ["DRAFT", "PROPOSED", "SIGNED", "ACTIVE", "CLOSED"]
    target = target_state.upper()
    if order.index(target) >= order.index("PROPOSED"):
        engagement = propose_engagement(engagement["id"], cm_user_id=cm_user_id)
    if order.index(target) >= order.index("SIGNED"):
        engagement = sign_engagement(engagement["id"], expert["id"])
    if order.index(target) >= order.index("ACTIVE"):
        if fund:
            engagement = fund_retainer(
                engagement["id"], engagement["retainer_cents"], cm_user_id=cm_user_id)
    if target == "CLOSED":
        engagement = close_engagement(engagement["id"], cm_user_id=cm_user_id)

    return {
        "expert": expert,
        "case": case,
        "request": request,
        "conflict_check": cc,
        "credential_review": cr,
        "engagement": engagement,
    }


def setup_active_engagement(**kwargs) -> dict:
    """The most common setup: an ACTIVE engagement on a screened READY request."""
    kwargs["target_state"] = "ACTIVE"
    return setup_scenario(**kwargs)


def setup_closed_engagement(**kwargs) -> dict:
    """Engagement walked all the way to CLOSED (evaluation-eligible)."""
    kwargs["target_state"] = "CLOSED"
    return setup_scenario(**kwargs)


# ─── Tier 4: deliverables ────────────────────────────────────────────────────

def create_report(engagement_id, title="Expert Report", report_type="LIABILITY",
                  cm_user_id="cm-1", **overrides) -> dict:
    return get_success_data(api_client.create_report(
        engagement_id, create_report_payload(title=title, report_type=report_type, **overrides),
        make_case_manager_headers(cm_user_id)))


def submit_report(report_id, expert_id) -> dict:
    return get_success_data(api_client.submit_report(report_id, make_expert_headers(expert_id)))


def finalize_report(report_id, cm_user_id="cm-1") -> dict:
    return get_success_data(api_client.review_report(
        report_id, {"decision": "FINALIZE"}, make_case_manager_headers(cm_user_id)))


def create_finalized_report(engagement_id, expert_id, cm_user_id="cm-1", **overrides) -> dict:
    """DRAFT -> IN_REVIEW -> FINALIZED."""
    report = create_report(engagement_id, cm_user_id=cm_user_id, **overrides)
    report = submit_report(report["id"], expert_id)
    return finalize_report(report["id"], cm_user_id=cm_user_id)


def create_disclosed_report(engagement_id, expert_id, cm_user_id="cm-1", **overrides) -> dict:
    """FINALIZED -> DISCLOSED."""
    report = create_finalized_report(engagement_id, expert_id, cm_user_id=cm_user_id, **overrides)
    return get_success_data(api_client.disclose_report(report["id"], make_case_manager_headers(cm_user_id)))


def create_document(engagement_id, privilege_tier="DISCOVERABLE", title="Doc",
                    content_ref="s3://bucket/doc", cm_user_id="cm-1") -> dict:
    return get_success_data(api_client.create_document_production(
        engagement_id, create_document_production_payload(
            title=title, privilege_tier=privilege_tier, content_ref=content_ref),
        make_case_manager_headers(cm_user_id)))


def deliver_document(production_id, cm_user_id="cm-1") -> dict:
    return get_success_data(api_client.advance_document_production(
        production_id, {"action": "DELIVER"}, make_case_manager_headers(cm_user_id)))


def create_schedule(engagement_id, kind="DEPOSITION",
                    start_at="2026-06-15T10:00:00Z", end_at="2026-06-15T12:00:00Z",
                    estimated_hours=2, venue_id=None, cm_user_id="cm-1", **overrides) -> dict:
    payload = create_schedule_payload(kind=kind, start_at=start_at, end_at=end_at,
                                      estimated_hours=estimated_hours, **overrides)
    if venue_id is not None:
        payload["venue_id"] = venue_id
    return get_success_data(api_client.create_testimony_schedule(
        engagement_id, payload, make_case_manager_headers(cm_user_id)))


def confirm_schedule(schedule_id, cm_user_id="cm-1") -> dict:
    return get_success_data(api_client.confirm_schedule(
        schedule_id, make_case_manager_headers(cm_user_id)))


def create_confirmed_schedule(engagement_id, **kwargs) -> dict:
    schedule = create_schedule(engagement_id, **kwargs)
    return confirm_schedule(schedule["id"], cm_user_id=kwargs.get("cm_user_id", "cm-1"))


# ─── Tier 5: invoices and money ──────────────────────────────────────────────

def submit_invoice(engagement_id, expert_id, line_items, total_cents,
                   travel_expense_cents=0, period_start="2026-05-04T00:00:00Z",
                   period_end="2026-05-08T00:00:00Z") -> dict:
    return get_success_data(api_client.create_invoice(
        engagement_id,
        create_invoice_payload(period_start=period_start, period_end=period_end,
                               line_items=line_items,
                               travel_expense_cents=travel_expense_cents,
                               total_cents=total_cents),
        make_expert_headers(expert_id)))


def approve_invoice(invoice_id, br_user_id="br-1") -> dict:
    return get_success_data(api_client.approve_invoice(
        invoice_id, TEST_USERS["billing_reviewer_headers"] if br_user_id == "br-1"
        else make_billing_reviewer_headers(br_user_id)))


def pay_invoice(invoice_id, br_user_id="br-1") -> dict:
    return get_success_data(api_client.settle_invoice(
        invoice_id, {"outcome": "PAID"},
        TEST_USERS["billing_reviewer_headers"] if br_user_id == "br-1"
        else make_billing_reviewer_headers(br_user_id)))


def approve_and_pay_invoice(invoice_id, br_user_id="br-1") -> dict:
    approve_invoice(invoice_id, br_user_id=br_user_id)
    return pay_invoice(invoice_id, br_user_id=br_user_id)


def create_evaluation(engagement_id, overall_score, cm_user_id="cm-1", **overrides) -> dict:
    return get_success_data(api_client.create_evaluation(
        engagement_id, create_evaluation_payload(overall_score=overall_score, **overrides),
        make_case_manager_headers(cm_user_id)))


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
