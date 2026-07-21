"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly-launched server with an empty database and the
logical clock at its startup default (2026-07-01T00:00:00Z). These helpers rebuild
all preconditions from scratch through PRD-declared endpoints. They use
get_success_data() (lenient) so a setup break surfaces as a clear "setup failed".

Identity threading: after registering a Member, every ownership-gated call uses
make_member_headers(member["id"]) — never the shared fallback header.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    register_member_payload, create_membership_payload, create_verification_payload,
    decide_verification_payload, create_home_listing_payload,
    create_availability_window_payload, create_exchange_request_payload,
    accept_payload, points_adjustment_payload, create_damage_claim_payload,
    adjudicate_payload, create_dispute_payload, resolve_dispute_payload,
    set_clock_payload,
)
from .test_users import make_member_headers, make_admin_headers, make_anonymous_headers

ADMIN = make_admin_headers()
ANON = make_anonymous_headers()


# ─── Primitives ──────────────────────────────────────────────────────────────
def set_clock(iso: str) -> str:
    data = get_success_data(api_client.set_clock(set_clock_payload(iso), ADMIN))
    return data.get("current_utc")


def register_member(full_name="Test Member", home_city="Boston", **overrides):
    """Register a member (Anonymous). Returns the created member dict."""
    payload = register_member_payload(full_name=full_name, home_city=home_city, **overrides)
    return get_success_data(api_client.register_member(payload, ANON))


def subscribe(member_id, tier="PLUS"):
    """Create a PENDING_ACTIVATION membership for the member (self)."""
    return get_success_data(api_client.create_membership(
        create_membership_payload(member_id, tier), make_member_headers(member_id)))


def activate_membership(membership_id):
    """Admin-activates a membership (grants welcome bonus)."""
    return get_success_data(api_client.activate_membership(membership_id, ADMIN))


def subscribe_and_activate(member_id, tier="PLUS"):
    """Create + activate a membership. Returns the ACTIVE membership dict."""
    m = subscribe(member_id, tier)
    return activate_membership(m["id"])


def verify_identity(member_id):
    """Submit an IDENTITY verification (self) and admin-approve it → member VERIFIED."""
    v = get_success_data(api_client.create_verification(
        create_verification_payload(member_id, "IDENTITY"), make_member_headers(member_id)))
    return get_success_data(api_client.decide_verification(
        v["id"], decide_verification_payload("APPROVE"), ADMIN))


def adjust_points(member_id, amount, memo="adjustment"):
    """Admin posts an ADMIN_ADJUSTMENT ledger entry to seed/correct a balance."""
    return get_success_data(api_client.create_points_adjustment(
        member_id, points_adjustment_payload(amount, memo=memo), ADMIN))


def create_draft_listing(owner_id, **overrides):
    """Create a DRAFT listing owned by owner_id."""
    return get_success_data(api_client.create_home_listing(
        create_home_listing_payload(owner_id, **overrides), make_member_headers(owner_id)))


def create_active_listing(owner_id, **overrides):
    """Create + activate a listing (owner must already be VERIFIED). Returns the
    ACTIVE listing dict, whose 'version' is the post-activation version."""
    listing = create_draft_listing(owner_id, **overrides)
    return get_success_data(api_client.activate_home_listing(
        listing["id"], make_member_headers(owner_id)))


def add_window(listing_id, owner_id, start_date, end_date):
    """Publish an availability window on a listing (owner only)."""
    return get_success_data(api_client.create_availability_window(
        listing_id, create_availability_window_payload(start_date, end_date),
        make_member_headers(owner_id)))


def open_points_request(guest_id, listing_id, start_date, end_date):
    """Open a POINTS exchange request as the guest."""
    return get_success_data(api_client.create_exchange_request(
        create_exchange_request_payload(guest_id, listing_id, start_date, end_date, "POINTS"),
        make_member_headers(guest_id)))


def accept_request(request_id, host_id, window_id, expected_version):
    """Host accepts a request against a window with OCC version. Returns agreement."""
    return get_success_data(api_client.accept_exchange_request(
        request_id, accept_payload(window_id, expected_version), make_member_headers(host_id)))


def refetch_listing_version(listing_id, actor_id):
    listing = get_success_data(api_client.get_home_listing(listing_id, make_member_headers(actor_id)))
    return listing["version"]


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, ADMIN))


# ─── Verified/funded member shortcuts ────────────────────────────────────────
def create_ready_guest(tier="PLUS", verify=True):
    """Register a guest, activate a membership (welcome bonus), optionally verify.
    Returns the member dict."""
    g = register_member(full_name="Guest")
    if tier:
        subscribe_and_activate(g["id"], tier)
    if verify:
        verify_identity(g["id"])
    return register_refetch(g["id"])


def create_ready_host(tier="PLUS", verify=True):
    """Register a host, optionally activate a membership and verify identity.
    A host must be verified to activate a listing."""
    h = register_member(full_name="Host", home_city="Denver")
    if tier:
        subscribe_and_activate(h["id"], tier)
    if verify:
        verify_identity(h["id"])
    return register_refetch(h["id"])


def register_refetch(member_id):
    return get_member(member_id)


# ─── Composite: full POINTS agreement scenarios ──────────────────────────────
def build_points_scenario(stage, *, points_per_night=100, start_date="2026-07-10",
                          end_date="2026-07-12", guest_tier="PLUS", host_tier="PLUS",
                          min_trust_score=0, confirm_as="guest", complete_as="guest"):
    """Build a POINTS exchange up to the requested lifecycle `stage`.

    stage in:
      'request'   -> guest + verified host + ACTIVE listing + OPEN window + PROPOSED request
      'pending'   -> + accept  (agreement PENDING_CONFIRMATION, window BOOKED)
      'confirmed' -> + confirm (coverage from host tier, insurance ACTIVE)
      'completed' -> + start + complete (both trust recomputed)

    Clock is set to 2026-07-01 up front; for 'completed' the clock is advanced to
    check_in for start and check_out for complete.

    Returns a dict with keys: guest, host, listing, window, request, agreement (when
    present), and version.
    """
    set_clock("2026-07-01T00:00:00Z")
    guest = register_member(full_name="Guest", home_city="Boston")
    host = register_member(full_name="Host", home_city="Denver")

    if guest_tier:
        subscribe_and_activate(guest["id"], guest_tier)
    if host_tier:
        subscribe_and_activate(host["id"], host_tier)

    verify_identity(guest["id"])
    verify_identity(host["id"])

    listing = create_active_listing(host["id"], points_per_night=points_per_night,
                                    min_trust_score=min_trust_score)
    window = add_window(listing["id"], host["id"], start_date, end_date)
    request = open_points_request(guest["id"], listing["id"], start_date, end_date)

    out = {"guest": guest, "host": host, "listing": listing, "window": window,
           "request": request, "version": listing["version"]}
    if stage == "request":
        return out

    agreement = accept_request(request["id"], host["id"], window["id"], listing["version"])
    out["agreement"] = agreement
    if stage == "pending":
        return out

    confirm_id = guest["id"] if confirm_as == "guest" else host["id"]
    agreement = get_success_data(api_client.confirm_agreement(
        agreement["id"], make_member_headers(confirm_id)))
    out["agreement"] = agreement
    if stage == "confirmed":
        return out

    # Advance clock and run the stay to COMPLETED.
    set_clock(f"{start_date}T00:00:00Z")
    get_success_data(api_client.start_agreement(agreement["id"], ADMIN))
    set_clock(f"{end_date}T00:00:00Z")
    complete_id = guest["id"] if complete_as == "guest" else host["id"]
    agreement = get_success_data(api_client.complete_agreement(
        agreement["id"], make_member_headers(complete_id)))
    out["agreement"] = agreement
    return out


def build_completed_agreement(**kwargs):
    """Shortcut: a COMPLETED POINTS agreement. Returns the scenario dict."""
    return build_points_scenario("completed", **kwargs)


def file_damage_claim(agreement_id, claimant_id, claimed_amount):
    """A party files a damage claim on a COMPLETED agreement."""
    return get_success_data(api_client.create_damage_claim(
        agreement_id, create_damage_claim_payload(claimant_id, claimed_amount),
        make_member_headers(claimant_id)))


def adjudicate_claim(claim_id, decision="APPROVE", assessed_amount=None):
    return get_success_data(api_client.adjudicate_damage_claim(
        claim_id, adjudicate_payload(decision, assessed_amount), ADMIN))


def open_dispute(agreement_id, opener_id, penalty_points, reason="conduct"):
    return get_success_data(api_client.create_dispute(
        agreement_id, create_dispute_payload(opener_id, penalty_points, reason=reason),
        make_member_headers(opener_id)))


def review_dispute(dispute_id):
    return get_success_data(api_client.review_dispute(dispute_id, ADMIN))


def resolve_dispute(dispute_id, decision, resolution_note=None, opener_id=None):
    """Resolve a dispute. FOR_CLAIMANT/FOR_RESPONDENT are admin; WITHDRAW is the opener."""
    if decision == "WITHDRAW":
        headers = make_member_headers(opener_id)
    else:
        headers = ADMIN
    return get_success_data(api_client.resolve_dispute(
        dispute_id, resolve_dispute_payload(decision, resolution_note), headers))
