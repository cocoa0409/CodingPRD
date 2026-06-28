"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors instead of confusing assertion failures.

Every fixture builds its preconditions from scratch against an empty database using
only PRD-declared endpoints. Identity threading: Homeowner and Electrician are
entity-backed, so ownership-gated calls use make_homeowner_headers(homeowner_id) /
make_electrician_headers(electrician_id) with the real entity id — never the shared
TEST_USERS constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_homeowner_payload,
    create_property_payload,
    create_charger_product_payload,
    create_electrician_payload,
    create_install_job_payload,
    create_site_assessment_payload,
    create_quote_payload,
    create_permit_application_payload,
    create_interconnection_request_payload,
    create_dispatch_assignment_payload,
    create_warranty_ticket_payload,
)
from .test_users import (
    TEST_USERS,
    make_homeowner_headers,
    make_electrician_headers,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
UTILITY = TEST_USERS["utility_reviewer_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Unique-value generators so parallel/serial fixtures never collide on unique keys.
_email_counter = itertools.count(1)
_sku_counter = itertools.count(1)


def _unique_email() -> str:
    return f"ho{next(_email_counter)}_{id(object())}@example.com"


def _unique_sku() -> str:
    return f"SKU{next(_sku_counter)}_{id(object())}"


# ─── Atomic creators (entity primitives) ─────────────────────────────────

def create_homeowner(**overrides):
    """Create a Homeowner. Returns the entity dict."""
    payload = create_homeowner_payload(**overrides)
    payload.setdefault("email", _unique_email())
    return get_success_data(api_client.create_homeowner(payload, ANON))


def create_charger_product(**overrides):
    """Create a ChargerProduct. Returns the entity dict."""
    payload = create_charger_product_payload(**overrides)
    payload.setdefault("sku", _unique_sku())
    return get_success_data(api_client.create_charger_product(payload, COORDINATOR))


def create_property(homeowner_id, **overrides):
    """Create a Property owned by homeowner_id. Returns the entity dict."""
    return get_success_data(
        api_client.create_property(create_property_payload(homeowner_id, **overrides), COORDINATOR)
    )


def create_electrician(**overrides):
    """Create an Electrician (ACTIVE). Returns the entity dict."""
    return get_success_data(
        api_client.create_electrician(create_electrician_payload(**overrides), COORDINATOR)
    )


def create_install_job(property_id, charger_product_sku, **overrides):
    """Create an InstallJob (CREATED / PENDING_REVIEW). Returns the entity dict."""
    return get_success_data(
        api_client.create_install_job(
            create_install_job_payload(property_id, charger_product_sku, **overrides), COORDINATOR
        )
    )


# ─── Tier 1: Base setup (homeowner + charger + property + job) ──────

def setup_base_job(charger_overrides=None, property_overrides=None):
    """Create homeowner + charger + property + CREATED install job scoping the charger.

    Defaults to a CA / PGE / 200A property scoping a 40A-circuit charger (fits).
    Returns dict with keys: homeowner, charger, property, job.
    """
    homeowner = create_homeowner()
    charger = create_charger_product(**(charger_overrides or {}))
    prop = create_property(homeowner["id"], **(property_overrides or {}))
    job = create_install_job(prop["id"], charger["sku"])
    return {"homeowner": homeowner, "charger": charger, "property": prop, "job": job}


# ─── Tier 1: State progression — workflow axis ───────────────────────────

def create_draft_assessment(ctx, **assessment_overrides):
    """Create a DRAFT SiteAssessment on ctx['job']. Returns the assessment dict."""
    sa = get_success_data(
        api_client.create_site_assessment(
            create_site_assessment_payload(
                ctx["property"]["id"], ctx["job"]["id"], **assessment_overrides
            ),
            COORDINATOR,
        )
    )
    return sa


def setup_assessed_job(charger_overrides=None, property_overrides=None,
                       assessment_overrides=None):
    """Reach workflow_status=ASSESSED: base job + DRAFT assessment + accept.

    Uses LOAD_STUDY_220_87 / max_measured 7200 by default so the charger fits and
    no panel-upgrade referral cascades (job stays PENDING_REVIEW on the compliance axis).
    Returns ctx dict augmented with key: assessment.
    """
    ctx = setup_base_job(charger_overrides, property_overrides)
    sa = create_draft_assessment(ctx, **(assessment_overrides or {}))
    get_success_data(api_client.accept_site_assessment(sa["id"], COORDINATOR))
    ctx["assessment"] = sa
    return ctx


def setup_quote_sent(ctx=None, quote_overrides=None, **setup_kwargs):
    """Reach a SENT quote on an ASSESSED job. Returns ctx augmented with key: quote."""
    if ctx is None:
        ctx = setup_assessed_job(**setup_kwargs)
    quote = get_success_data(
        api_client.create_quote(
            create_quote_payload(ctx["job"]["id"], **(quote_overrides or {})), COORDINATOR
        )
    )
    get_success_data(api_client.send_quote(quote["id"], COORDINATOR))
    ctx["quote"] = quote
    return ctx


def setup_quoted_job(ctx=None, quote_overrides=None, **setup_kwargs):
    """Reach workflow_status=QUOTED: assessed job -> quote -> send -> accept (OCC).

    Returns ctx augmented with key: quote.
    """
    ctx = setup_quote_sent(ctx, quote_overrides, **setup_kwargs)
    job = get_success_data(api_client.get_install_job(ctx["job"]["id"], COORDINATOR))
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(
        api_client.accept_quote(
            ctx["quote"]["id"], {"expected_install_job_version": job["version"]}, ho_headers
        )
    )
    return ctx


# ─── Tier 1: State progression — compliance axis ─────────────────────────

def setup_permit_pending(ctx=None, **setup_kwargs):
    """Reach compliance_status=PERMIT_PENDING by filing a permit on a job.

    Builds a QUOTED job (so the dispatch path is reachable later), files a permit.
    Returns ctx augmented with key: permit.
    """
    if ctx is None:
        ctx = setup_quoted_job(**setup_kwargs)
    permit = get_success_data(
        api_client.create_permit_application(
            create_permit_application_payload(ctx["job"]["id"]), COORDINATOR
        )
    )
    ctx["permit"] = permit
    return ctx


def setup_compliance_cleared(ctx=None, **setup_kwargs):
    """Reach compliance_status=CLEARED: file + approve permit, file + review + approve
    interconnection. Job remains on its current workflow status (QUOTED by default).

    Returns ctx augmented with keys: permit, interconnection.
    """
    ctx = setup_permit_pending(ctx, **setup_kwargs)
    get_success_data(api_client.approve_permit_application(ctx["permit"]["id"], COORDINATOR))
    ic = get_success_data(
        api_client.create_interconnection_request(
            create_interconnection_request_payload(ctx["job"]["id"]), COORDINATOR
        )
    )
    get_success_data(api_client.start_review_interconnection_request(ic["id"], UTILITY))
    get_success_data(api_client.approve_interconnection_request(ic["id"], UTILITY))
    ctx["interconnection"] = ic
    return ctx


# ─── Tier 3: Full lifecycle shortcuts (workflow + compliance to INSTALLED/ACTIVATED) ─

def setup_scheduled_job(ctx=None, electrician_overrides=None, dispatch_overrides=None,
                        **setup_kwargs):
    """Reach workflow_status=SCHEDULED with compliance CLEARED.

    QUOTED job -> compliance cleared -> register electrician -> book dispatch (BOOKED).
    Returns ctx augmented with keys: permit, interconnection, electrician, dispatch.
    """
    ctx = setup_compliance_cleared(ctx, **setup_kwargs)
    if "electrician" not in ctx:
        ctx["electrician"] = create_electrician(**(electrician_overrides or {}))
    dispatch = get_success_data(
        api_client.create_dispatch_assignment(
            create_dispatch_assignment_payload(
                ctx["job"]["id"], ctx["electrician"]["id"], **(dispatch_overrides or {})
            ),
            COORDINATOR,
        )
    )
    ctx["dispatch"] = dispatch
    return ctx


def setup_installed_job(ctx=None, **kwargs):
    """Reach workflow_status=INSTALLED: scheduled job -> depart -> complete.

    Returns ctx augmented through 'dispatch'; job now carries activation_pairing_code.
    """
    ctx = setup_scheduled_job(ctx, **kwargs)
    el_headers = make_electrician_headers(ctx["electrician"]["id"])
    get_success_data(api_client.depart_dispatch_assignment(ctx["dispatch"]["id"], el_headers))
    get_success_data(api_client.complete_dispatch_assignment(ctx["dispatch"]["id"], el_headers))
    ctx["job"] = get_success_data(api_client.get_install_job(ctx["job"]["id"], COORDINATOR))
    return ctx


def setup_activated_job(ctx=None, **kwargs):
    """Reach workflow_status=ACTIVATED: installed job -> activate with the minted code.

    Returns ctx; ctx['job'] re-read to the ACTIVATED state.
    """
    ctx = setup_installed_job(ctx, **kwargs)
    ho_headers = make_homeowner_headers(ctx["homeowner"]["id"])
    code = ctx["job"]["activation_pairing_code"]
    get_success_data(
        api_client.activate_install_job(ctx["job"]["id"], {"pairing_code": code}, ho_headers)
    )
    ctx["job"] = get_success_data(api_client.get_install_job(ctx["job"]["id"], COORDINATOR))
    return ctx


# ─── Tier 2/4: Panel-upgrade / BLOCKED-compliance scenarios ───────────────

def setup_blocked_job(charger_overrides=None):
    """Reach compliance_status=BLOCKED via the panel-upgrade cascade.

    Builds a 100A property + STANDARD_220_83 assessment with declared_fixed_appliance_va
    16000 (charger does NOT fit) -> accept cascades a PanelUpgradeReferral (OPEN) and
    drives compliance PENDING_REVIEW -> BLOCKED.
    Returns ctx augmented with keys: assessment, referral.
    """
    ctx = setup_base_job(
        charger_overrides=charger_overrides,
        property_overrides={"main_breaker_amps": 100},
    )
    sa = create_draft_assessment(
        ctx, assessment_method="STANDARD_220_83",
        declared_fixed_appliance_va=16000, max_measured_demand_va=0,
    )
    get_success_data(api_client.accept_site_assessment(sa["id"], COORDINATOR))
    ctx["assessment"] = sa
    referrals, _ = _list_data(
        api_client.list_panel_upgrade_referrals(COORDINATOR, params={"install_job_id": ctx["job"]["id"]})
    )
    ctx["referral"] = referrals[0] if referrals else None
    return ctx


# ─── Tier 3: Incentive lifecycle helpers ─────────────────────────────────

def submit_federal_claim(ctx, eligible_cost_cents):
    """On an ACTIVATED job, create a FEDERAL_45W claim and submit it (DRAFT->SUBMITTED).

    Returns the submitted claim dict.
    """
    from .factories import create_incentive_claim_payload
    claim = get_success_data(
        api_client.create_incentive_claim(
            create_incentive_claim_payload(ctx["job"]["id"], "FEDERAL_45W", eligible_cost_cents),
            COORDINATOR,
        )
    )
    get_success_data(api_client.submit_incentive_claim(claim["id"], COORDINATOR))
    return claim


# ─── Helper: list-response unpacking that tolerates the success envelope ──

def _list_data(response):
    """Return (data_list, meta_dict) from a list response using get_success_data.

    get_success_data returns the data payload; for array responses that is the list.
    """
    body = response.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta
