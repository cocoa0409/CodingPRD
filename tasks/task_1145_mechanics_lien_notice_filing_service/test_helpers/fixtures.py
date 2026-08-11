"""Composite setup helpers for multi-step test prerequisites.

Setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup failed" error rather than a confusing assertion failure.
Every helper builds its state from scratch — the harness restarts the server
before every test, so nothing carries over.

Standard CA profile used throughout: prelim required, 20 CALENDAR days,
90-day filing window, 90-day foreclosure deadline, UNCAPPED, retainage
excluded, counts_punch_list false. With a BASE_CONTRACT span of
2026-05-02..2026-06-10 this yields:
  prelim service deadline 2026-05-22, filing window end 2026-09-08,
  foreclosure deadline (filed 2026-07-01) 2026-09-29, stop-notice deadline
  2026-07-10, bond-claim deadline 2026-07-25.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    DEFAULTS,
    create_bond_claim_payload,
    create_bonding_request_payload,
    create_company_payload,
    create_foreclosure_referral_payload,
    create_furnishing_span_payload,
    create_jurisdiction_rule_payload,
    create_lien_claim_payload,
    create_notice_payload,
    create_party_payload,
    create_payment_payload,
    create_project_payload,
    create_stop_notice_payload,
    create_waiver_payload,
)
from .test_users import TEST_USERS, make_customer_admin_headers

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]
_COUNSEL = TEST_USERS["counsel_headers"]


# ─── Tier 0: thin authenticated wrappers ─────────────────────────────

def get_company(company_id) -> dict:
    return get_success_data(api_client.get_company(company_id, _PLATFORM_ADMIN))


def get_project(project_id) -> dict:
    return get_success_data(api_client.get_project(project_id, _OPS_AGENT))


def get_notice(notice_id) -> dict:
    return get_success_data(api_client.get_notice(notice_id, _OPS_AGENT))


def get_lien_claim(claim_id) -> dict:
    return get_success_data(api_client.get_lien_claim(claim_id, _OPS_AGENT))


def get_deadline_calendar(project_id) -> dict:
    return get_success_data(api_client.get_deadline_calendar(project_id, _OPS_AGENT))


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, _PLATFORM_ADMIN)
    )


# ─── Tier 1: single-entity creation ──────────────────────────────────

def create_company(name="Test Claimant Co", seed_balance_cents=None) -> dict:
    """Create a company; optionally seed its prepaid balance with one
    OCC-guarded adjustment (PRD §3.1). Returns the company."""
    company = get_success_data(
        api_client.create_company(
            create_company_payload(name=name, contact_email=f"billing@{name.replace(' ', '').lower()}.com"),
            _PLATFORM_ADMIN,
        )
    )
    if seed_balance_cents:
        company = get_success_data(
            api_client.create_balance_adjustment(
                company["id"],
                {
                    "amount_cents": seed_balance_cents,
                    "reason": "seed",
                    "expected_company_version": company["version"],
                },
                _PLATFORM_ADMIN,
            )
        )
    return company


def publish_rule(**overrides) -> dict:
    """Publish a jurisdiction rule; defaults to the standard CA
    COMMERCIAL_PRIVATE profile."""
    return get_success_data(
        api_client.create_jurisdiction_rule(
            create_jurisdiction_rule_payload(**overrides), _PLATFORM_ADMIN
        )
    )


def supersede_rule(rule_id, rule_version, **overrides) -> dict:
    """Supersede a PUBLISHED rule; returns the PUBLISHED successor."""
    payload = create_jurisdiction_rule_payload(**overrides)
    payload.pop("state_code", None)
    payload.pop("project_type", None)
    payload["expected_jurisdiction_rule_version"] = rule_version
    return get_success_data(
        api_client.supersede_jurisdiction_rule(rule_id, payload, _PLATFORM_ADMIN)
    )


def create_project(company_id, **overrides) -> dict:
    """Create a project owned by the given company (company_id comes from the
    CustomerAdmin caller's X-User-ID)."""
    return get_success_data(
        api_client.create_project(
            create_project_payload(**overrides),
            make_customer_admin_headers(company_id),
        )
    )


def create_party(project_id, company_id, party_role="OWNER", verify=True, **overrides) -> dict:
    """Add a party to a project; when verify=True an OpsAgent immediately
    adjudicates the research to VERIFIED."""
    party = get_success_data(
        api_client.create_party(
            create_party_payload(project_id, party_role=party_role, **overrides),
            make_customer_admin_headers(company_id),
        )
    )
    if verify:
        party = get_success_data(
            api_client.decide_party(party["id"], {"outcome": "VERIFIED"}, _OPS_AGENT)
        )
    return party


def advance_research(project_id) -> dict:
    """One OpsAgent research-advance step. Returns the project."""
    return get_success_data(api_client.research_advance(project_id, _OPS_AGENT))


def record_span(project_id, company_id, span_kind="BASE_CONTRACT",
                start_date="2026-05-02", end_date="2026-06-10") -> dict:
    """Record a furnishing span, threading expected_project_version from a
    fresh read so the OCC guard passes (PRD §2.9)."""
    current = get_project(project_id)
    return get_success_data(
        api_client.create_furnishing_span(
            create_furnishing_span_payload(
                project_id,
                current["version"],
                span_kind=span_kind,
                start_date=start_date,
                end_date=end_date,
            ),
            make_customer_admin_headers(company_id),
        )
    )


def order_notice(project_id, company_id, recipient_party_id,
                 delivery_method="CERTIFIED_MAIL") -> dict:
    return get_success_data(
        api_client.create_notice(
            create_notice_payload(
                project_id, recipient_party_id, delivery_method=delivery_method
            ),
            make_customer_admin_headers(company_id),
        )
    )


def serve_notice(notice_id, served_at="2026-05-20") -> dict:
    return get_success_data(
        api_client.serve_notice(notice_id, {"served_at": served_at}, _OPS_AGENT)
    )


def record_proof(notice_id, result="DELIVERED", proof_url=DEFAULTS["PROOF_URL"]) -> dict:
    return get_success_data(
        api_client.record_notice_proof(
            notice_id, {"result": result, "proof_url": proof_url}, _OPS_AGENT
        )
    )


def create_draft_claim(project_id, company_id) -> dict:
    return get_success_data(
        api_client.create_lien_claim(
            create_lien_claim_payload(project_id),
            make_customer_admin_headers(company_id),
        )
    )


def lock_claim(claim_id, company_id) -> dict:
    return get_success_data(
        api_client.lock_lien_claim(claim_id, make_customer_admin_headers(company_id))
    )


def file_claim(claim_id, filed_at="2026-07-01") -> dict:
    return get_success_data(
        api_client.file_lien_claim(claim_id, {"filed_at": filed_at}, _OPS_AGENT)
    )


def create_waiver(project_id, company_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_waiver(
            create_waiver_payload(project_id, **overrides),
            make_customer_admin_headers(company_id),
        )
    )


def apply_waiver(waiver_id) -> dict:
    return get_success_data(api_client.apply_waiver(waiver_id, _OPS_AGENT))


def create_payment(project_id, company_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_payment(
            create_payment_payload(project_id, **overrides),
            make_customer_admin_headers(company_id),
        )
    )


def verify_payment(payment_id) -> dict:
    return get_success_data(api_client.verify_payment(payment_id, _OPS_AGENT))


# ─── Tier 2: research-verified project hierarchy ─────────────────────

def create_verified_project(company_id, **project_overrides):
    """Project + VERIFIED OWNER/GC/LENDER parties, research advanced to
    VERIFIED. The LENDER is created and verified unconditionally so the
    precondition holds whether or not the effective rule requires a prelim
    notice. Returns (project, parties-by-role)."""
    project = create_project(company_id, **project_overrides)
    parties = {
        "OWNER": create_party(project["id"], company_id, "OWNER",
                              legal_name="Owner LLC", address="1 Main St"),
        "GC": create_party(project["id"], company_id, "GC",
                           legal_name="GC Inc", address="2 Main St"),
        "LENDER": create_party(project["id"], company_id, "LENDER",
                               legal_name="Bank NA", address="3 Main St"),
    }
    advance_research(project["id"])
    project = advance_research(project["id"])
    return project, parties


def setup_verified_ca_project(company=None, rule=None,
                              seed_balance_cents=TEST_DEFAULTS["SEED_BALANCE_CENTS"],
                              span_start="2026-05-02", span_end="2026-06-10",
                              **project_overrides) -> dict:
    """Company (seeded balance) + standard CA rule + VERIFIED project +
    ACTIVE BASE_CONTRACT span. Returns a context dict."""
    company = company or create_company(seed_balance_cents=seed_balance_cents)
    rule = rule or publish_rule()
    project, parties = create_verified_project(company["id"], **project_overrides)
    span = record_span(project["id"], company["id"],
                       start_date=span_start, end_date=span_end)
    return {
        "company": company,
        "rule": rule,
        "project": project,
        "parties": parties,
        "span": span,
    }


# ─── Tier 3: notice / claim lifecycle shortcuts ──────────────────────

def setup_project_with_proofed_notice(notice_role="OWNER",
                                      delivery_method="CERTIFIED_MAIL",
                                      served_at="2026-05-20",
                                      **kwargs) -> dict:
    """Verified CA project + ACTIVE span + a notice carried through
    DRAFT -> SERVED -> PROOF_CONFIRMED."""
    ctx = setup_verified_ca_project(**kwargs)
    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"][notice_role]["id"], delivery_method)
    serve_notice(notice["id"], served_at)
    ctx["notice"] = record_proof(notice["id"])
    return ctx


def setup_draft_claim(**kwargs) -> dict:
    """Proofed-notice project plus a DRAFT lien claim."""
    ctx = setup_project_with_proofed_notice(**kwargs)
    ctx["claim"] = create_draft_claim(ctx["project"]["id"], ctx["company"]["id"])
    return ctx


def setup_locked_claim(**kwargs) -> dict:
    """Claim carried to AMOUNT_LOCKED (rule pinned at lock)."""
    ctx = setup_draft_claim(**kwargs)
    ctx["claim"] = lock_claim(ctx["claim"]["id"], ctx["company"]["id"])
    return ctx


def setup_filed_claim(filed_at="2026-07-01", **kwargs) -> dict:
    """Claim carried to FILED; Project.open_lien_count is 1 and posture is
    ENCUMBERED."""
    ctx = setup_locked_claim(**kwargs)
    ctx["claim"] = file_claim(ctx["claim"]["id"], filed_at)
    return ctx


def setup_filed_claim_with_sent_referral(counsel_name="Counsel LLP", **kwargs) -> dict:
    """FILED claim plus a foreclosure referral sent to counsel (SENT)."""
    ctx = setup_filed_claim(**kwargs)
    referral = get_success_data(
        api_client.create_foreclosure_referral(
            create_foreclosure_referral_payload(
                ctx["claim"]["id"], counsel_name=counsel_name
            ),
            make_customer_admin_headers(ctx["company"]["id"]),
        )
    )
    referral = get_success_data(
        api_client.send_foreclosure_referral(referral["id"], {}, _OPS_AGENT)
    )
    ctx["referral"] = referral
    return ctx


# ─── Tier 4: public-project remedies ─────────────────────────────────

def setup_tx_public_project(seed_balance_cents=None, **project_overrides) -> dict:
    """Company + TX STATE_PUBLIC rule + project + ACTIVE BASE_CONTRACT span.
    Public projects skip research gating for stop notices / bond claims."""
    company = create_company(name="TX Public Co", seed_balance_cents=seed_balance_cents)
    rule = publish_rule(
        state_code="TX",
        project_type="STATE_PUBLIC",
        prelim_notice_required=False,
        prelim_days=15,
        refused_counts_as_served=True,
        allowed_delivery_methods=["CERTIFIED_MAIL", "PERSONAL_SERVICE", "EMAIL_STATUTORY"],
        counts_punch_list=True,
        retainage_claimable=True,
    )
    defaults = {
        "name": "TX Public Job",
        "state_code": "TX",
        "county": "Travis",
        "project_type": "STATE_PUBLIC",
        "contract_value_cents": 900000,
    }
    defaults.update(project_overrides)
    project = create_project(company["id"], **defaults)
    span = record_span(project["id"], company["id"])
    return {"company": company, "rule": rule, "project": project, "span": span}


def create_stop_notice(project_id, company_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_stop_notice(
            create_stop_notice_payload(project_id, **overrides),
            make_customer_admin_headers(company_id),
        )
    )


def create_bond_claim(project_id, company_id, surety_party_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_bond_claim(
            create_bond_claim_payload(project_id, surety_party_id, **overrides),
            make_customer_admin_headers(company_id),
        )
    )
