"""Composite setup helpers for multi-step test prerequisites.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty database) before every test. Helpers use
get_success_data() (lenient validator) so setup failures surface as clear "setup failed"
errors rather than confusing assertion failures.

The default policyholder identifier is "ph-1", matching TEST_USERS["policyholder_headers"];
all owner-scoped writes inside fixtures reuse that identity so ownership checks pass.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_policyholder_headers
from . import factories as F

PH_ID = "ph-1"
_admin = TEST_USERS["admin_headers"]
_uw = TEST_USERS["underwriter_headers"]
_ph = TEST_USERS["policyholder_headers"]
_adj = TEST_USERS["adjuster_headers"]


# ─── Reference-data helpers ───────────────────────────────────────────────
def create_cancellation_product(**overrides):
    return get_success_data(api_client.create_coverage_product(
        F.coverage_product_payload(**overrides), _admin))


def create_liability_product(**overrides):
    return get_success_data(api_client.create_coverage_product(
        F.liability_product_payload(**overrides), _admin))


def create_liquor_product(**overrides):
    return get_success_data(api_client.create_coverage_product(
        F.liquor_product_payload(**overrides), _admin))


def create_venue(**overrides):
    return get_success_data(api_client.create_vendor(F.vendor_payload(**overrides), _admin))


def create_caterer(**overrides):
    return get_success_data(api_client.create_vendor(F.caterer_payload(**overrides), _admin))


def create_defaulted_caterer(**overrides):
    """Create a caterer and walk SOLVENT -> FLAGGED -> DEFAULTED."""
    caterer = create_caterer(**overrides)
    api_client.flag_vendor(caterer["id"], _admin)
    return get_success_data(api_client.default_vendor(caterer["id"], _admin))


def create_active_peril(**overrides):
    """Create a peril and activate it (WATCH -> ACTIVE)."""
    peril = get_success_data(api_client.create_force_majeure_event(
        F.force_majeure_payload(**overrides), _admin))
    return get_success_data(api_client.activate_peril(peril["id"], _admin))


def set_clock(iso8601: str):
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, _admin))


# ─── Tier 1/2: Quote-stage policy assembly ────────────────────────────────
def create_quoted_policy(**policy_overrides):
    """Create a QUOTED policy owned by ph-1. Returns the policy."""
    return get_success_data(api_client.create_policy(
        F.policy_payload(**policy_overrides), make_policyholder_headers(PH_ID)))


def add_event_profile(policy_id, venue_id, **overrides):
    return get_success_data(api_client.create_event_profile(
        policy_id, F.event_profile_payload(venue_id, **overrides),
        make_policyholder_headers(PH_ID)))


def add_coverage(policy_id, product_id, **overrides):
    return get_success_data(api_client.create_coverage(
        policy_id, F.coverage_payload(product_id, **overrides),
        make_policyholder_headers(PH_ID)))


def add_rider(policy_id, rider_type, scheduled_value_cents, **overrides):
    return get_success_data(api_client.create_rider(
        policy_id, F.rider_payload(rider_type, scheduled_value_cents, **overrides),
        make_policyholder_headers(PH_ID)))


def add_certificate(policy_id, vendor_id, **overrides):
    return get_success_data(api_client.create_certificate(
        policy_id, F.certificate_payload(vendor_id, **overrides),
        make_policyholder_headers(PH_ID)))


def setup_quoted_single_event(product_payload=None, attendance=150):
    """Quoted SINGLE_EVENT policy + venue + one event profile + one CANCELLATION coverage.

    Returns dict with policy, venue, product, coverage.
    """
    product = create_cancellation_product() if product_payload is None else \
        get_success_data(api_client.create_coverage_product(product_payload, _admin))
    venue = create_venue()
    policy = create_quoted_policy()
    add_event_profile(policy["id"], venue["id"], expected_attendance=attendance)
    coverage = add_coverage(policy["id"], product["id"])
    return {"policy": policy, "venue": venue, "product": product, "coverage": coverage}


# ─── Tier 3: Lifecycle shortcuts ──────────────────────────────────────────
def bind_policy(policy_id):
    return get_success_data(api_client.bind_policy(policy_id, _uw))


def pay_policy(policy_id, amount_cents):
    return get_success_data(api_client.pay_policy(
        policy_id, {"amount_cents": amount_cents}, make_policyholder_headers(PH_ID)))


def activate_coverage(policy_id):
    return get_success_data(api_client.activate_coverage(policy_id, _uw))


def setup_bound_policy_canc_only():
    """Bound SINGLE_EVENT policy with one CANCELLATION coverage (attendance 150).

    total_premium_cents = 65000. billing UNPAID, lifecycle BOUND.
    Returns dict with policy (post-bind), venue, product, coverage.
    """
    ctx = setup_quoted_single_event()
    ctx["policy"] = bind_policy(ctx["policy"]["id"])
    return ctx


def setup_in_force_policy_canc_only():
    """In-force SINGLE_EVENT policy with one ACTIVE CANCELLATION coverage.

    Walks bind -> pay(65000) -> activate-coverage. Returns dict with policy, coverage, etc.
    """
    ctx = setup_bound_policy_canc_only()
    pay_policy(ctx["policy"]["id"], 65000)
    ctx["policy"] = activate_coverage(ctx["policy"]["id"])
    # refresh coverage view
    ctx["coverage"] = get_success_data(api_client.get_coverage(
        ctx["policy"]["id"], ctx["coverage"]["id"], _uw))
    return ctx


def setup_in_force_policy_liability_only():
    """In-force SINGLE_EVENT policy with one ACTIVE LIABILITY coverage (limit 2000000).

    Walks add LIABILITY coverage -> bind -> pay(45000) -> activate. Returns dict.
    """
    product = create_liability_product()
    venue = create_venue()
    policy = create_quoted_policy()
    add_event_profile(policy["id"], venue["id"], expected_attendance=150)
    coverage = add_coverage(policy["id"], product["id"])
    policy = bind_policy(policy["id"])
    pay_policy(policy["id"], 45000)
    policy = activate_coverage(policy["id"])
    coverage = get_success_data(api_client.get_coverage(policy["id"], coverage["id"], _uw))
    return {"policy": policy, "venue": venue, "product": product, "coverage": coverage}


# ─── Claim helpers ────────────────────────────────────────────────────────
def file_claim(policy_id, coverage_id, claim_type, claimed_amount_cents, **overrides):
    return get_success_data(api_client.create_claim(
        policy_id, F.claim_payload(coverage_id, claim_type, claimed_amount_cents, **overrides),
        make_policyholder_headers(PH_ID)))


def attach_document(policy_id, claim_id, **overrides):
    return get_success_data(api_client.create_claim_document(
        policy_id, claim_id, F.claim_document_payload(**overrides),
        make_policyholder_headers(PH_ID)))


def setup_submitted_claim(ctx=None, claim_type="CANCELLATION", claimed_amount_cents=1000000,
                          with_document=True, doc_overrides=None, claim_overrides=None):
    """In-force CANCELLATION-coverage policy + one SUBMITTED claim (optionally documented).

    If `ctx` is None, builds setup_in_force_policy_canc_only() first. Returns (ctx, claim).
    """
    if ctx is None:
        ctx = setup_in_force_policy_canc_only()
    claim = file_claim(ctx["policy"]["id"], ctx["coverage"]["id"], claim_type,
                       claimed_amount_cents, **(claim_overrides or {}))
    if with_document:
        attach_document(ctx["policy"]["id"], claim["id"], **(doc_overrides or {}))
    return ctx, claim


def claim_at_revision_cap(claimed_amount_cents=1000000):
    """In-force CANCELLATION policy with a claim cycled to revision_count==3, now in
    INFO_REQUESTED with a fresh document added (so only the revision-cap bars resubmit).

    Returns (ctx, claim_id).
    """
    ctx = setup_in_force_policy_canc_only()
    pid = ctx["policy"]["id"]
    claim = file_claim(pid, ctx["coverage"]["id"], "CANCELLATION", claimed_amount_cents)
    cid = claim["id"]
    attach_document(pid, cid, doc_type="INVOICE", file_uri="s3://docs/d0.pdf")
    # three full cycles: each request-info -> add doc -> resubmit bumps revision_count
    for i in range(1, 4):
        get_success_data(api_client.request_info_claim(pid, cid, _adj))
        attach_document(pid, cid, doc_type="RECEIPT", file_uri=f"s3://docs/d{i}.pdf")
        get_success_data(api_client.resubmit_claim(pid, cid, make_policyholder_headers(PH_ID)))
    # now revision_count == 3; request-info once more and add a new doc
    get_success_data(api_client.request_info_claim(pid, cid, _adj))
    attach_document(pid, cid, doc_type="RECEIPT", file_uri="s3://docs/d4.pdf")
    return ctx, cid


# ─── Endorsement helpers ──────────────────────────────────────────────────
def draft_endorsement(policy_id, endorsement_type, payload_json):
    return get_success_data(api_client.create_endorsement(
        policy_id, F.endorsement_payload(endorsement_type, payload_json), _uw))


def observed_policy_version(policy_id):
    return get_success_data(api_client.get_policy(policy_id, _uw))["version"]
