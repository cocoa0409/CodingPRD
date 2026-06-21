"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for setup calls so setup failures
surface as clear "setup failed" errors rather than confusing assertions.

Identity threading: a Customer's X-User-ID must equal the acting Customer.id and an
Attorney's X-User-ID must equal the acting Attorney.id for ownership-gated calls.
Every helper that creates a customer/attorney threads that entity's id into the
headers via make_customer_headers / make_attorney_headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_subscription_plan_payload, create_subscription_payload,
    create_clause_template_payload, create_document_project_payload, create_attorney_payload,
    create_attorney_review_payload, create_document_revision_payload,
    create_signature_request_payload, full_answers, partial_answers,
)
from .test_users import make_customer_headers, make_attorney_headers, TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


# ─── Primitive creators ───────────────────────────────

def create_plan(**plan_overrides):
    """Create a SubscriptionPlan (PlatformAdmin). Returns the plan dict."""
    res = api_client.create_subscription_plan(
        create_subscription_plan_payload(**plan_overrides), ADMIN
    )
    return get_success_data(res)


def create_customer(state="CA", **overrides):
    """Create a Customer. Returns (customer, customer_headers) with id threaded."""
    res = api_client.create_customer(
        create_customer_payload(state_of_residence=state, **overrides), TEST_USERS["customer_headers"]
    )
    cust = get_success_data(res)
    return cust, make_customer_headers(cust["id"])


def create_attorney(bar_state="CA", **overrides):
    """Create an Attorney (PlatformAdmin). Returns (attorney, attorney_headers)."""
    res = api_client.create_attorney(create_attorney_payload(bar_state=bar_state, **overrides), ADMIN)
    att = get_success_data(res)
    return att, make_attorney_headers(att["id"])


def create_clause_template(clause_key, document_type, state_code, is_mandatory=True, body_text="c"):
    res = api_client.create_clause_template(
        create_clause_template_payload(clause_key, document_type, state_code, is_mandatory, body_text),
        ADMIN,
    )
    return get_success_data(res)


def create_clause_templates(document_type, state_code, mandatory_count, optional_count, key_prefix="C"):
    """Create N mandatory + M optional clause templates for (type,state). Returns the list."""
    out = []
    idx = 1
    for _ in range(mandatory_count):
        out.append(create_clause_template(f"{key_prefix}{idx}", document_type, state_code, True, f"c{idx}"))
        idx += 1
    for _ in range(optional_count):
        out.append(create_clause_template(f"{key_prefix}{idx}", document_type, state_code, False, f"c{idx}"))
        idx += 1
    return out


# ─── Tier 1: subscription state progression ───────────

def create_active_subscription(customer, customer_headers, plan):
    """Subscribe customer to plan and activate. Returns the active subscription dict."""
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(customer["id"], plan["id"]), customer_headers
    ))
    activated = get_success_data(api_client.transition_subscription(
        sub["id"], {"to_status": "ACTIVE"}, ADMIN
    ))
    return activated


def setup_active_account(state="CA", **plan_overrides):
    """Plan + customer + ACTIVE subscription. Returns (plan, customer, customer_headers, subscription)."""
    plan = create_plan(**plan_overrides)
    cust, ch = create_customer(state=state)
    sub = create_active_subscription(cust, ch, plan)
    return plan, cust, ch, sub


# ─── Tier 2: project hierarchy ────────────────────────

def create_project(customer, customer_headers, subscription, document_type, state_code,
                   title="Test Project", **proj_overrides):
    """Create a DocumentProject (DRAFT). Returns the project dict."""
    res = api_client.create_document_project(
        create_document_project_payload(
            customer["id"], subscription["id"], document_type, state_code, title, **proj_overrides
        ),
        customer_headers,
    )
    return get_success_data(res)


def setup_project_in_progress(state="CA", document_type="WILL", answer_count=None,
                              addon=False, mandatory_clauses=1, optional_clauses=0,
                              create_templates=True, **plan_overrides):
    """
    Plan + active subscription + project moved to IN_PROGRESS via a questionnaire upsert.
    By default answers all required questions (provisional_completeness == 1.0).
    Returns dict of {plan, customer, customer_headers, subscription, project}.
    """
    plan, cust, ch, sub = setup_active_account(state=state, **plan_overrides)
    if create_templates:
        create_clause_templates(document_type, state, mandatory_clauses, optional_clauses)
    proj = create_project(cust, ch, sub, document_type, state, attorney_review_addon=addon)
    if answer_count is None:
        answers = full_answers(document_type)
    else:
        answers = partial_answers(answer_count)
    get_success_data(api_client.upsert_questionnaire(proj["id"], {"answers": answers}, ch))
    proj = get_success_data(api_client.get_document_project(proj["id"], ch))
    return {
        "plan": plan, "customer": cust, "customer_headers": ch,
        "subscription": sub, "project": proj,
    }


def setup_assembled_project(state="CA", document_type="WILL", addon=False,
                            mandatory_clauses=1, optional_clauses=0, **plan_overrides):
    """
    Project taken through ASSEMBLED (full questionnaire + assemble). Templates created.
    Returns dict adding {project: assembled-project}.
    """
    ctx = setup_project_in_progress(
        state=state, document_type=document_type, addon=addon,
        mandatory_clauses=mandatory_clauses, optional_clauses=optional_clauses,
        **plan_overrides,
    )
    ch = ctx["customer_headers"]
    assembled = get_success_data(api_client.assemble_document_project(ctx["project"]["id"], ch))
    ctx["project"] = assembled
    return ctx


# ─── Tier 3: revisions / signature / review lifecycle ──

def create_revision(project, customer_headers, expected_version=None):
    """Create a FINAL DocumentRevision against the project's current version.
    If expected_version is None, reads the live project version first."""
    if expected_version is None:
        live = get_success_data(api_client.get_document_project(project["id"], customer_headers))
        expected_version = live["version"]
    res = api_client.create_document_revision(
        create_document_revision_payload(project["id"], expected_version), customer_headers
    )
    return get_success_data(res)


def setup_assembled_with_revision(state="CA", document_type="WILL", addon=False,
                                  mandatory_clauses=1, **plan_overrides):
    """ASSEMBLED project + one FINAL revision. Returns ctx with {revision}."""
    ctx = setup_assembled_project(
        state=state, document_type=document_type, addon=addon,
        mandatory_clauses=mandatory_clauses, **plan_overrides,
    )
    ctx["revision"] = create_revision(ctx["project"], ctx["customer_headers"])
    ctx["project"] = get_success_data(
        api_client.get_document_project(ctx["project"]["id"], ctx["customer_headers"])
    )
    return ctx


def setup_finalized_with_sent_envelope(state="CA", document_type="WILL",
                                       signer_emails=None, notary_required=None,
                                       clock_iso=None, mandatory_clauses=1, **plan_overrides):
    """
    Project: ASSEMBLED -> revision -> FINALIZED -> signature request -> SENT.
    No attorney review (addon=false). Optionally sets the clock first.
    Returns ctx with {revision, signature_request}.
    """
    if clock_iso is not None:
        get_success_data(api_client.set_clock({"to_iso8601": clock_iso}, ADMIN))
    ctx = setup_assembled_with_revision(
        state=state, document_type=document_type, addon=False,
        mandatory_clauses=mandatory_clauses, **plan_overrides,
    )
    ch = ctx["customer_headers"]
    if signer_emails is None:
        signer_emails = ["s1@x.com"]
    sig_payload = create_signature_request_payload(ctx["revision"]["id"], signer_emails)
    if notary_required is not None:
        sig_payload["notary_required"] = notary_required
    sig = get_success_data(api_client.create_signature_request(sig_payload, ch))
    get_success_data(api_client.transition_document_project(
        ctx["project"]["id"], {"to_status": "FINALIZED"}, ch
    ))
    sig = get_success_data(api_client.transition_signature_request(
        sig["id"], {"to_status": "SENT"}, ch
    ))
    ctx["signature_request"] = sig
    ctx["project"] = get_success_data(api_client.get_document_project(ctx["project"]["id"], ch))
    return ctx


# ─── Attorney-review lifecycle helpers ────────────────

def request_review(project, customer_headers, attorney,
                   window_start="2026-03-01T10:00:00.000Z",
                   window_end="2026-03-01T12:00:00.000Z"):
    """Request an attorney review on an ASSEMBLED project. Returns the review dict."""
    res = api_client.create_attorney_review(
        create_attorney_review_payload(project["id"], attorney["id"], window_start, window_end),
        customer_headers,
    )
    return get_success_data(res)


def setup_review_in_review(state="CA", document_type="WILL", mandatory_clauses=1,
                           optional_clauses=0, window_start="2026-03-01T10:00:00.000Z",
                           window_end="2026-03-01T12:00:00.000Z", **plan_overrides):
    """
    Assembled project with addon -> review REQUESTED/ASSIGNED -> attorney moves to IN_REVIEW.
    Returns ctx with {attorney, attorney_headers, review}.
    """
    ctx = setup_assembled_project(
        state=state, document_type=document_type, addon=True,
        mandatory_clauses=mandatory_clauses, optional_clauses=optional_clauses, **plan_overrides,
    )
    att, ah = create_attorney(bar_state=state)
    review = request_review(ctx["project"], ctx["customer_headers"], att, window_start, window_end)
    review = get_success_data(api_client.transition_attorney_review(
        review["id"], {"to_status": "IN_REVIEW"}, ah
    ))
    ctx["attorney"] = att
    ctx["attorney_headers"] = ah
    ctx["review"] = review
    ctx["project"] = get_success_data(
        api_client.get_document_project(ctx["project"]["id"], ctx["customer_headers"])
    )
    return ctx


def setup_review_approved(state="CA", document_type="WILL", mandatory_clauses=1,
                          optional_clauses=0, **plan_overrides):
    """
    Project with addon -> review IN_REVIEW -> APPROVED (project back to ASSEMBLED).
    Returns ctx with {attorney, attorney_headers, review} (review APPROVED).
    """
    ctx = setup_review_in_review(
        state=state, document_type=document_type, mandatory_clauses=mandatory_clauses,
        optional_clauses=optional_clauses, **plan_overrides,
    )
    review = get_success_data(api_client.transition_attorney_review(
        ctx["review"]["id"], {"to_status": "APPROVED"}, ctx["attorney_headers"]
    ))
    ctx["review"] = review
    ctx["project"] = get_success_data(
        api_client.get_document_project(ctx["project"]["id"], ctx["customer_headers"])
    )
    return ctx
