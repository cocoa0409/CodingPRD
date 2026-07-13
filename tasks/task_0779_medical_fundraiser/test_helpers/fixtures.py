"""Composite setup helpers (PRD §3).

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty database) before
every test. Helpers use ``get_success_data`` (lenient) so a broken setup step
raises a clear "Setup step failed" error rather than a confusing assertion.

Identity threading: after creating an entity-backed actor (Organizer /
Beneficiary / Donor), every ownership-gated call uses
``make_<role>_headers(entity["id"])`` — never a shared placeholder constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_organizer_headers,
    make_beneficiary_headers,
    make_donor_headers,
)
from .factories import (
    create_organizer_payload,
    create_beneficiary_payload,
    create_donor_payload,
    create_campaign_payload,
    create_donation_payload,
    create_payout_payload,
    create_dispute_payload,
    create_hold_payload,
    create_feature_placement_payload,
)

GUEST = TEST_USERS["guest_headers"]
TS_AGENT = TEST_USERS["ts_agent_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _data(resp) -> dict:
    return get_success_data(resp)


# --------------------------------------------------------------- clock (PRD §2.10)
def set_clock(api, iso: str):
    return _data(api.set_clock({"to_iso8601": iso}, ADMIN))


# ----------------------------------------------------------- actor registration
def register_organizer(api, **overrides) -> dict:
    return _data(api.create_organizer(create_organizer_payload(**overrides), GUEST))


def register_beneficiary(api, **overrides) -> dict:
    return _data(api.create_beneficiary(create_beneficiary_payload(**overrides), GUEST))


def register_donor(api, **overrides) -> dict:
    return _data(api.create_donor(create_donor_payload(**overrides), GUEST))


# --------------------------------------------------- beneficiary verification (§3.1)
def verify_beneficiary(api, beneficiary_id: str, stripe_ref: str = "acct_test") -> dict:
    """Drive a beneficiary all the way to VERIFIED: connect a Stripe account,
    submit KYC, and approve it (PRD §3.1)."""
    ben_headers = make_beneficiary_headers(beneficiary_id)
    _data(api.withdrawal_setup(beneficiary_id, {"stripe_account_ref": stripe_ref}, ben_headers))
    _data(api.submit_verification(beneficiary_id, ben_headers))
    return _data(api.approve_verification(beneficiary_id, TS_AGENT))


def submit_beneficiary_pending(api, beneficiary_id: str, stripe_ref: str = "acct_test") -> dict:
    """Connect Stripe + submit KYC → beneficiary PENDING (not approved)."""
    ben_headers = make_beneficiary_headers(beneficiary_id)
    _data(api.withdrawal_setup(beneficiary_id, {"stripe_account_ref": stripe_ref}, ben_headers))
    return _data(api.submit_verification(beneficiary_id, ben_headers))


# ------------------------------------------------------------- campaign (PRD §3.2)
def create_draft_campaign(api, organizer_id: str, beneficiary_id: str, **overrides) -> dict:
    payload = create_campaign_payload(beneficiary_id, **overrides)
    return _data(api.create_campaign(payload, make_organizer_headers(organizer_id)))


def publish_campaign(api, campaign_id: str, organizer_id: str) -> dict:
    return _data(api.publish_campaign(campaign_id, make_organizer_headers(organizer_id)))


def create_active_campaign(api, organizer_id: str, beneficiary_id: str, **overrides) -> dict:
    camp = create_draft_campaign(api, organizer_id, beneficiary_id, **overrides)
    return publish_campaign(api, camp["id"], organizer_id)


def get_campaign(api, campaign_id: str) -> dict:
    return _data(api.get_campaign(campaign_id, GUEST))


def campaign_version(api, campaign_id: str) -> int:
    return get_campaign(api, campaign_id)["version"]


# --------------------------------------------------------------- donation (§3.4)
def make_donation(api, campaign_id: str, donor_id: str, amount_cents: int, **overrides) -> dict:
    payload = create_donation_payload(campaign_id, donor_id, amount_cents, **overrides)
    return _data(api.create_donation(payload, make_donor_headers(donor_id)))


# --------------------------------------------------------------- payout (§3.7)
def request_payout(api, campaign_id: str, organizer_id: str, amount_cents: int,
                   scheduled_at=None) -> dict:
    """Request a payout, reading the campaign's current version for the OCC guard."""
    version = campaign_version(api, campaign_id)
    extra = {}
    if scheduled_at is not None:
        extra["scheduled_at"] = scheduled_at
    payload = create_payout_payload(campaign_id, amount_cents, version, **extra)
    return _data(api.create_payout(payload, make_organizer_headers(organizer_id)))


def payout_to_paid(api, payout_id: str) -> dict:
    """Process then settle a REQUESTED payout to PAID (PRD §3.7)."""
    _data(api.process_payout(payout_id, ADMIN))
    return _data(api.settle_payout(payout_id, ADMIN))


# --------------------------------------------------------------- dispute (§3.6)
def open_dispute(api, donation_id: str, donor_id: str, reason: str = "FRAUD") -> dict:
    payload = create_dispute_payload(donation_id, reason)
    return _data(api.create_dispute(payload, make_donor_headers(donor_id)))


def open_dispute_under_review(api, donation_id: str, donor_id: str, reason: str = "FRAUD") -> dict:
    """Open a dispute then assign it → UNDER_REVIEW (PRD §3.6)."""
    dsp = open_dispute(api, donation_id, donor_id, reason)
    _data(api.assign_dispute(dsp["id"], TS_AGENT))
    return dsp


# --------------------------------------------------------------- hold (§3.8)
def place_hold(api, campaign_id: str, locked_amount_cents: int = 0,
               severity: str = "STANDARD", reason: str = "Under review") -> dict:
    payload = create_hold_payload(campaign_id, reason=reason, severity=severity,
                                  locked_amount_cents=locked_amount_cents)
    return _data(api.create_hold(payload, TS_AGENT))


# --------------------------------------------------- feature placement (§3.8)
def book_placement(api, campaign_id: str, **overrides) -> dict:
    payload = create_feature_placement_payload(campaign_id, **overrides)
    return _data(api.create_feature_placement(payload, ADMIN))


# ==========================================================================
#  Composite scenario bundles (reused by the two tests of each instance)
# ==========================================================================
def setup_actor_trio(api, is_anonymous_default=None):
    """Register organizer + beneficiary + donor. Returns their dicts."""
    org = register_organizer(api)
    ben = register_beneficiary(api)
    donor_kwargs = {}
    if is_anonymous_default is not None:
        donor_kwargs["is_anonymous_default"] = is_anonymous_default
    donor = register_donor(api, **donor_kwargs)
    return org, ben, donor


def setup_published_campaign(api, verified=False, is_charity=None, **camp_overrides):
    """Register the actor trio and open a published (ACTIVE) campaign.

    Returns dict: organizer, beneficiary, donor, campaign.
    When ``verified`` is True the beneficiary is driven to VERIFIED first.
    """
    org, ben, donor = setup_actor_trio(api)
    if verified:
        verify_beneficiary(api, ben["id"])
    overrides = dict(camp_overrides)
    if is_charity is not None:
        overrides["is_charity"] = is_charity
    campaign = create_active_campaign(api, org["id"], ben["id"], **overrides)
    return {"organizer": org, "beneficiary": ben, "donor": donor, "campaign": campaign}


def setup_dual_variant_scenario(api):
    """Published campaign, two CAPTURED donations of net 10000 each, one OPEN
    dispute locking donation D1 (PRD §2.6). Returns bundle with camp_id, d1, d2, dispute."""
    b = setup_published_campaign(api)
    camp_id = b["campaign"]["id"]
    donor_id = b["donor"]["id"]
    d1 = make_donation(api, camp_id, donor_id, 10000)
    d2 = make_donation(api, camp_id, donor_id, 10000)
    dsp = open_dispute(api, d1["id"], donor_id, "FRAUD")
    return {**b, "camp_id": camp_id, "d1": d1, "d2": d2, "dispute": dsp}


def setup_organizer_risk_scenario(api):
    """Organizer with raised 100000, one UPHELD dispute (refund 5000) and one
    REJECTED dispute; beneficiary VERIFIED (PRD §2.9). Returns organizer id."""
    org, ben, donor = setup_actor_trio(api)
    verify_beneficiary(api, ben["id"])
    camp = create_active_campaign(api, org["id"], ben["id"], goal_cents=1_000_000)
    donor_id = donor["id"]
    da = make_donation(api, camp["id"], donor_id, 100000)   # stays CAPTURED
    db = make_donation(api, camp["id"], donor_id, 5000)     # will be upheld -> refunded
    # dispute on db -> upheld
    dsp_b = open_dispute_under_review(api, db["id"], donor_id, "FRAUD")
    _data(api.uphold_dispute(dsp_b["id"], TS_AGENT))
    # dispute on da -> rejected
    dsp_a = open_dispute_under_review(api, da["id"], donor_id, "OTHER")
    _data(api.reject_dispute(dsp_a["id"], TS_AGENT))
    return org["id"]


def setup_uphold_cascade_scenario(api):
    """Verified campaign, two net-10000 donations, one REQUESTED payout of 19000
    consuming all provisional availability, and a dispute on D1 at UNDER_REVIEW
    (PRD §3.6, §3.7). Returns camp_id, d1, payout, dispute."""
    b = setup_published_campaign(api, verified=True)
    camp_id = b["campaign"]["id"]
    org_id = b["organizer"]["id"]
    donor_id = b["donor"]["id"]
    d1 = make_donation(api, camp_id, donor_id, 10000)
    make_donation(api, camp_id, donor_id, 10000)
    payout = request_payout(api, camp_id, org_id, 19000)
    dsp = open_dispute_under_review(api, d1["id"], donor_id, "FRAUD")
    return {**b, "camp_id": camp_id, "d1": d1, "payout": payout, "dispute": dsp}


def setup_reject_cascade_scenario(api):
    """Verified campaign with a net-10000 donation and one REQUESTED payout of
    5000 (PRD §2.8). Returns beneficiary id, camp_id, payout."""
    b = setup_published_campaign(api, verified=True)
    camp_id = b["campaign"]["id"]
    org_id = b["organizer"]["id"]
    donor_id = b["donor"]["id"]
    make_donation(api, camp_id, donor_id, 10000)
    payout = request_payout(api, camp_id, org_id, 5000)
    return {**b, "camp_id": camp_id, "payout": payout}


def setup_settled_payout_scenario(api, clock_iso="2026-05-01T00:00:00Z"):
    """Verified campaign, net-100000 donation, one payout of 1000 processed and
    settled at ``clock_iso`` (PRD §3.7). Returns bundle with camp_id, payout, clock."""
    set_clock(api, clock_iso)
    b = setup_published_campaign(api, verified=True, goal_cents=1_000_000)
    camp_id = b["campaign"]["id"]
    org_id = b["organizer"]["id"]
    donor_id = b["donor"]["id"]
    make_donation(api, camp_id, donor_id, 100000)
    payout = request_payout(api, camp_id, org_id, 1000, scheduled_at=clock_iso)
    payout_to_paid(api, payout["id"])
    return {**b, "camp_id": camp_id, "payout": payout, "clock": clock_iso}


def setup_paid_payout_scenario(api):
    """Verified campaign, net-100000 donation, a payout of 1000 taken to PAID
    (PRD §3.7). Returns bundle with camp_id, beneficiary, payout."""
    b = setup_published_campaign(api, verified=True, goal_cents=1_000_000)
    camp_id = b["campaign"]["id"]
    org_id = b["organizer"]["id"]
    donor_id = b["donor"]["id"]
    make_donation(api, camp_id, donor_id, 100000)
    payout = request_payout(api, camp_id, org_id, 1000)
    payout_to_paid(api, payout["id"])
    return {**b, "camp_id": camp_id, "payout": payout}
