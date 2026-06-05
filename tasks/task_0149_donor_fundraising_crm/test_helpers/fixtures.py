"""Composite setup helpers for the Donor & Fundraising CRM.

Tests run against a fresh, empty database (the harness restarts the server before
each test), so every helper builds its preconditions from scratch using only
PRD-declared endpoints. Helpers use get_success_data() (lenient) internally so a
broken setup surfaces a clear "Setup failed" rather than a confusing assertion.

All roles are opaque operators (PRD Section 2.1): there is no ownership threading,
so the shared TEST_USERS headers are correct everywhere.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

CM = TEST_USERS["campaign_manager_headers"]      # CampaignManager
GA = TEST_USERS["gift_admin_headers"]            # GiftAdmin
DR = TEST_USERS["donor_relations_headers"]       # DonorRelations


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the server's logical UTC clock (any role may; uses GiftAdmin)."""
    get_success_data(api_client.set_clock(iso, GA))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation / state progression
# ---------------------------------------------------------------------------
def create_campaign(**overrides) -> dict:
    """Create a DRAFT campaign. Returns the campaign."""
    return get_success_data(api_client.create_campaign(f.create_campaign_payload(**overrides), CM))


def create_open_campaign(**overrides) -> dict:
    """Create a campaign and open it. Returns the OPEN campaign (re-fetched)."""
    camp = create_campaign(**overrides)
    get_success_data(api_client.open_campaign(camp["id"], CM))
    return get_success_data(api_client.get_campaign(camp["id"], CM))


def create_closed_campaign(**overrides) -> dict:
    """Create -> open -> close a campaign. Returns the CLOSED campaign."""
    camp = create_campaign(**overrides)
    get_success_data(api_client.open_campaign(camp["id"], CM))
    get_success_data(api_client.close_campaign(camp["id"], CM))
    return get_success_data(api_client.get_campaign(camp["id"], CM))


def create_donor(**overrides) -> dict:
    """Create a donor. Returns the donor."""
    return get_success_data(api_client.create_donor(f.create_donor_payload(**overrides), GA))


def create_employer(**overrides) -> dict:
    """Create a matching-gift employer. Returns the employer."""
    return get_success_data(api_client.create_employer(f.create_employer_payload(**overrides), CM))


def create_household(**overrides) -> dict:
    """Create a household. Returns the household."""
    return get_success_data(api_client.create_household(f.create_household_payload(**overrides), CM))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------
def setup_open_campaign_with_donor(donor_overrides=None, **camp_overrides):
    """OPEN campaign + one donor. Returns (campaign, donor)."""
    camp = create_open_campaign(**camp_overrides)
    donor = create_donor(**(donor_overrides or {}))
    return camp, donor


def setup_open_campaign_with_donor_and_employer(employer_overrides=None, **camp_overrides):
    """OPEN campaign + employer + donor whose employer_id is set.
    Returns (campaign, donor, employer)."""
    camp = create_open_campaign(**camp_overrides)
    emp = create_employer(**(employer_overrides or {}))
    donor = create_donor(employer_id=emp["id"])
    return camp, donor, emp


def setup_household_with_members(policy="FULL_TO_ALL", member_count=3, **hh_overrides):
    """Household with `member_count` donors, created in order. The first donor is
    the canonical giver. Returns (household, [donors]).

    Donors are created sequentially so their created_at ordering is deterministic
    (used by SPLIT_EVEN remainder distribution)."""
    hh = create_household(soft_credit_policy=policy, **hh_overrides)
    donors = [create_donor(household_id=hh["id"]) for _ in range(member_count)]
    return hh, donors


# ---------------------------------------------------------------------------
# Tier 3: gift lifecycle shortcuts
# ---------------------------------------------------------------------------
def record_gift(campaign_id, donor_id, **overrides) -> dict:
    """Record a RECORDED gift. Returns the gift."""
    return get_success_data(
        api_client.create_gift(f.create_gift_payload(donor_id, campaign_id, **overrides), GA)
    )


def acknowledge_gift(gift_id) -> dict:
    """Acknowledge a RECORDED gift. Returns the post-acknowledge gift."""
    return get_success_data(api_client.acknowledge_gift(gift_id, DR))


def create_acknowledged_gift(campaign_id, donor_id, **overrides):
    """Record then acknowledge a gift. Returns (gift_after_ack, gift_id)."""
    gift = record_gift(campaign_id, donor_id, **overrides)
    acked = acknowledge_gift(gift["id"])
    return acked, gift["id"]


def receipt_gift(gift_id) -> dict:
    """Receipt an ACKNOWLEDGED gift. Returns the post-receipt gift."""
    return get_success_data(api_client.receipt_gift(gift_id, DR))


# ---------------------------------------------------------------------------
# Tier 3b: match-claim lifecycle shortcuts
# ---------------------------------------------------------------------------
def open_match_claim(gift_id) -> dict:
    """Open a SUBMITTED match claim against an acknowledged gift. Returns the claim."""
    return get_success_data(api_client.create_match_claim(f.create_match_claim_payload(gift_id), GA))


def approve_match_claim(claim_id) -> dict:
    return get_success_data(api_client.approve_match_claim(claim_id, GA))


def pay_match_claim(claim_id) -> dict:
    return get_success_data(api_client.pay_match_claim(claim_id, GA))


def setup_paid_match(campaign_id=None, donor=None, employer_overrides=None,
                     gift_amount_cents=100000, **camp_overrides):
    """Reach a PAID MatchClaim against an acknowledged gift.

    If campaign_id/donor are not supplied, builds an OPEN campaign and a donor
    with the employer attached. Returns
    (campaign, donor, employer, gift_id, claim_paid).
    """
    if campaign_id is None:
        camp = create_open_campaign(**camp_overrides)
        emp = create_employer(**(employer_overrides or {}))
        donor = create_donor(employer_id=emp["id"])
        campaign_id = camp["id"]
    else:
        camp = get_success_data(api_client.get_campaign(campaign_id, CM))
        emp = None
    _, gift_id = create_acknowledged_gift(campaign_id, donor["id"], amount_cents=gift_amount_cents)
    claim = open_match_claim(gift_id)
    approve_match_claim(claim["id"])
    paid = pay_match_claim(claim["id"])
    return camp, donor, emp, gift_id, paid


# ---------------------------------------------------------------------------
# Tier 4: pledge setups (threshold / accumulation targeting)
# ---------------------------------------------------------------------------
def create_pledge(campaign_id, donor_id, **overrides) -> dict:
    """Create a pledge (cascades the installment schedule). Returns the pledge."""
    return get_success_data(
        api_client.create_pledge(f.create_pledge_payload(donor_id, campaign_id, **overrides), GA)
    )


def setup_pledge(total_amount_cents=10000, installment_count=2, frequency="MONTHLY",
                 schedule_basis="FRONT_LOADED", **camp_overrides):
    """OPEN campaign + donor + a pledge with the given schedule.
    Returns (campaign, donor, pledge)."""
    camp = create_open_campaign(**camp_overrides)
    donor = create_donor()
    pledge = create_pledge(
        camp["id"], donor["id"],
        total_amount_cents=total_amount_cents,
        installment_count=installment_count,
        frequency=frequency,
        schedule_basis=schedule_basis,
    )
    return camp, donor, pledge


def setup_delinquent_pledge(total_amount_cents=10000, installment_count=2,
                            start_clock="2026-01-01T00:00:00Z",
                            overdue_clock="2026-02-15T00:00:00Z"):
    """Build a pledge whose early installment(s) are overdue, then evaluate it into
    DELINQUENT.

    Clock is set to start_clock before pledge creation (pins due_on offsets), then
    advanced to overdue_clock, then evaluate-delinquency is invoked. Campaign window
    is widened so it covers start_clock. Returns (campaign, donor, pledge_after_eval).
    """
    set_clock(start_clock)
    camp = create_open_campaign(starts_on="2025-12-01T00:00:00Z", ends_on="2026-12-31T00:00:00Z")
    donor = create_donor()
    pledge = create_pledge(
        camp["id"], donor["id"],
        total_amount_cents=total_amount_cents,
        installment_count=installment_count,
        frequency="MONTHLY",
        schedule_basis="FRONT_LOADED",
    )
    set_clock(overdue_clock)
    pledge_after = get_success_data(api_client.evaluate_pledge_delinquency(pledge["id"], GA))
    return camp, donor, pledge_after


def get_installments_sorted(pledge_id):
    """Return the pledge's installments sorted by sequence_no ascending."""
    resp = api_client.list_pledge_installments(pledge_id, GA, params={"limit": 100})
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("items", data)
    return sorted(rows, key=lambda r: r["sequence_no"])


# ---------------------------------------------------------------------------
# Tier 5: donor lifecycle setups
# ---------------------------------------------------------------------------
def setup_active_donor_via_gift(start_clock="2026-01-01T00:00:00Z",
                                lapse_threshold_days=365, gift_amount_cents=5000):
    """Clock set to start_clock; create OPEN campaign + donor + an ACKNOWLEDGED gift
    so the donor auto-transitions PROSPECT -> ACTIVE with last_gift_at == start_clock.
    Returns (campaign, donor_id, gift_id)."""
    set_clock(start_clock)
    camp = create_open_campaign(starts_on="2025-12-01T00:00:00Z", ends_on="2026-12-31T00:00:00Z")
    donor = create_donor(lapse_threshold_days=lapse_threshold_days)
    _, gift_id = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=gift_amount_cents)
    return camp, donor["id"], gift_id


def setup_lapsed_donor(start_clock="2026-01-01T00:00:00Z", lapse_clock="2026-03-01T00:00:00Z",
                       lapse_threshold_days=30):
    """Build an ACTIVE donor (via a gift at start_clock), advance the clock past the
    lapse window, and flag the donor LAPSED. Returns (campaign, donor_id, gift_id).
    The clock is left at lapse_clock."""
    camp, donor_id, gift_id = setup_active_donor_via_gift(
        start_clock=start_clock, lapse_threshold_days=lapse_threshold_days
    )
    set_clock(lapse_clock)
    get_success_data(api_client.flag_lapsed_donor(donor_id, DR))
    return camp, donor_id, gift_id


# ---------------------------------------------------------------------------
# Planned giving
# ---------------------------------------------------------------------------
def create_planned_gift(donor_id, **overrides) -> dict:
    return get_success_data(api_client.create_planned_gift(f.create_planned_gift_payload(donor_id, **overrides), DR))


def setup_confirmed_planned_gift(campaign=None, **camp_overrides):
    """Donor + a CONFIRMED planned gift. If campaign is None, also builds an OPEN
    campaign (returned). Returns (campaign_or_none, donor, planned_gift)."""
    donor = create_donor()
    pg = create_planned_gift(donor["id"])
    get_success_data(api_client.confirm_planned_gift(pg["id"], DR))
    return campaign, donor, pg


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------
def create_segment(**overrides) -> dict:
    return get_success_data(api_client.create_segment(f.create_segment_payload(**overrides), CM))


# ---------------------------------------------------------------------------
# List-envelope helper
# ---------------------------------------------------------------------------
def rows_of(data):
    """Normalize a list-data payload to a plain list of rows."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    return data
