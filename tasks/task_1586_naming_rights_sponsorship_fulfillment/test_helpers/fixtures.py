"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: SponsorContact calls are entity-backed by SponsorAccount;
the countersign and report-acknowledge helpers thread the real sponsor id into
X-User-ID via make_sponsor_contact_headers(). Evidence review is four-eyes:
submitter and reviewer are opaque ActivationManager identities that must
differ, so evidence helpers take explicit acting user ids.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import INITIAL_SEASON
from .factories import (
    create_asset_payload,
    create_contract_payload,
    create_credit_payload,
    create_deliverable_payload,
    create_evidence_payload,
    create_grant_payload,
    create_opportunity_payload,
    create_payment_payload,
    create_report_payload,
    create_rights_window_payload,
    create_sponsor_payload,
    create_venue_payload,
)
from .test_users import (
    TEST_USERS,
    make_activation_headers,
    make_sponsor_contact_headers,
)

ADMIN = TEST_USERS["venue_admin_headers"]
SALES = TEST_USERS["sales_headers"]
FINANCE = TEST_USERS["finance_headers"]

# Opaque ActivationManager identities used for the four-eyes review split.
AM_SUBMITTER = "am-1"
AM_REVIEWER = "am-2"
AM_THIRD = "am-3"


def am_headers(user_id):
    return make_activation_headers(user_id)


def sponsor_headers(sponsor_id):
    return make_sponsor_contact_headers(sponsor_id)


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and simple lifecycle moves
# ---------------------------------------------------------------------------

def create_venue(display_name="Vector Arena", city="Austin"):
    """Create a venue; current_season starts at the initial epoch."""
    return get_success_data(
        api_client.create_venue(create_venue_payload(
            display_name=display_name, city=city), ADMIN))


def create_active_sponsor(legal_name="FizzCo Beverages LLC",
                          display_name="FizzCo", industry_category="BEVERAGE"):
    """Create a sponsor and QUALIFY it to ACTIVE. Returns the sponsor."""
    sponsor = get_success_data(api_client.create_sponsor(
        create_sponsor_payload(legal_name=legal_name, display_name=display_name,
                               industry_category=industry_category), SALES))
    return get_success_data(api_client.transition_sponsor(
        sponsor["id"], {"action": "QUALIFY"}, SALES))


def create_asset(venue_id, name="Bowl LED Ribbon", asset_class="SIGNAGE",
                 rate_card_unit_cents=50_000, avg_impressions_per_unit=120_000,
                 cpm_cents=2_500):
    """Register an inventory asset (born AVAILABLE)."""
    return get_success_data(api_client.create_asset(
        create_asset_payload(
            venue_id, name=name, asset_class=asset_class,
            rate_card_unit_cents=rate_card_unit_cents,
            avg_impressions_per_unit=avg_impressions_per_unit,
            cpm_cents=cpm_cents), ADMIN))


def create_draft_contract(venue_id, sponsor_id, title="Stadium Naming Rights",
                          term_first_season=INITIAL_SEASON,
                          term_last_season=INITIAL_SEASON,
                          base_fee_cents=10_000_000, escalator_pct=0,
                          escalator_mode="SIMPLE", **extra):
    """Create a DRAFT contract."""
    return get_success_data(api_client.create_contract(
        create_contract_payload(
            venue_id, sponsor_id, title=title,
            term_first_season=term_first_season,
            term_last_season=term_last_season,
            base_fee_cents=base_fee_cents, escalator_pct=escalator_pct,
            escalator_mode=escalator_mode, **extra), SALES))


def propose_contract(contract_id):
    return get_success_data(
        api_client.transition_contract(contract_id, {"action": "PROPOSE"}, SALES))


def countersign_contract(contract_id, sponsor_id, expected_contract_version):
    """SponsorContact countersigns; threads the sponsor's own id as X-User-ID."""
    return get_success_data(api_client.countersign_contract(
        contract_id, {"expected_contract_version": expected_contract_version},
        sponsor_headers(sponsor_id)))


def activate_contract(contract_id):
    return get_success_data(
        api_client.transition_contract(contract_id, {"action": "ACTIVATE"}, SALES))


def create_grant(contract_id, category="BEVERAGE",
                 first_season=INITIAL_SEASON, last_season=INITIAL_SEASON):
    """Create a PENDING exclusivity grant."""
    return get_success_data(api_client.create_grant(
        create_grant_payload(contract_id, category=category,
                             first_season=first_season,
                             last_season=last_season), SALES))


def activate_grant(grant_id):
    return get_success_data(
        api_client.transition_grant(grant_id, {"action": "ACTIVATE"}, ADMIN))


def create_league_window(venue_id, category="BEVERAGE",
                         first_season=INITIAL_SEASON, last_season=INITIAL_SEASON):
    """Create a LEAGUE rights window (born RESERVED)."""
    return get_success_data(api_client.create_rights_window(
        create_rights_window_payload(venue_id, holder="LEAGUE", category=category,
                                     first_season=first_season,
                                     last_season=last_season), ADMIN))


def activate_window(window_id):
    return get_success_data(
        api_client.transition_rights_window(window_id, {"action": "ACTIVATE"}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2/3: contract lifecycle composites
# ---------------------------------------------------------------------------

def create_countersigned_contract(venue_id, sponsor_id, **contract_kwargs):
    """DRAFT -> PROPOSE -> COUNTERSIGNED. Returns the contract."""
    contract = create_draft_contract(venue_id, sponsor_id, **contract_kwargs)
    proposed = propose_contract(contract["id"])
    return countersign_contract(contract["id"], sponsor_id, proposed["version"])


def create_active_contract(venue_id, sponsor_id, **contract_kwargs):
    """Full path to ACTIVE (no grants). Returns the contract."""
    contract = create_countersigned_contract(venue_id, sponsor_id,
                                             **contract_kwargs)
    return activate_contract(contract["id"])


def setup_venue_sponsor_asset(sponsor_name="FizzCo Beverages LLC",
                              asset_name="Bowl LED Ribbon", **asset_kwargs):
    """Venue + ACTIVE sponsor + one asset. Returns (venue, sponsor, asset)."""
    venue = create_venue()
    sponsor = create_active_sponsor(legal_name=sponsor_name)
    asset = create_asset(venue["id"], name=asset_name, **asset_kwargs)
    return venue, sponsor, asset


def setup_active_contract_scenario(base_fee_cents=10_000_000, escalator_pct=0,
                                   escalator_mode="SIMPLE",
                                   term_first_season=INITIAL_SEASON,
                                   term_last_season=INITIAL_SEASON,
                                   with_asset=True, **asset_kwargs):
    """Venue + ACTIVE sponsor + ACTIVE contract (+ asset). Returns a dict."""
    venue = create_venue()
    sponsor = create_active_sponsor()
    asset = (create_asset(venue["id"], **asset_kwargs) if with_asset else None)
    contract = create_active_contract(
        venue["id"], sponsor["id"], base_fee_cents=base_fee_cents,
        escalator_pct=escalator_pct, escalator_mode=escalator_mode,
        term_first_season=term_first_season,
        term_last_season=term_last_season)
    return {"venue": venue, "sponsor": sponsor, "asset": asset,
            "contract": contract}


# ---------------------------------------------------------------------------
# Tier 3: deliverable / evidence composites
# ---------------------------------------------------------------------------

def create_open_deliverable(contract_id, asset_id, season=INITIAL_SEASON,
                            unit_kind="GAME_DISPLAY", contracted_units=10,
                            **extra):
    """Create a deliverable in the venue's current season (born IN_PROGRESS)."""
    return get_success_data(api_client.create_deliverable(
        create_deliverable_payload(contract_id, asset_id, season=season,
                                   unit_kind=unit_kind,
                                   contracted_units=contracted_units, **extra),
        am_headers(AM_SUBMITTER)))


def submit_evidence(deliverable_id, units_claimed,
                    evidence_uri="s3://pop/evidence.pdf", submitter=AM_SUBMITTER):
    """Submit evidence; submission_status SUBMITTED, submitted_by = submitter."""
    return get_success_data(api_client.create_evidence(
        create_evidence_payload(deliverable_id, units_claimed=units_claimed,
                                evidence_uri=evidence_uri),
        am_headers(submitter)))


def approve_evidence(submission_id, reviewer=AM_REVIEWER, review_note=None):
    payload = {"action": "APPROVE"}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(
        api_client.transition_evidence(submission_id, payload,
                                       am_headers(reviewer)))


def reject_evidence(submission_id, reviewer=AM_REVIEWER,
                    review_note="insufficient proof"):
    return get_success_data(api_client.transition_evidence(
        submission_id, {"action": "REJECT", "review_note": review_note},
        am_headers(reviewer)))


def submit_and_approve(deliverable_id, units_claimed, submitter=AM_SUBMITTER,
                       reviewer=AM_REVIEWER,
                       evidence_uri="s3://pop/evidence.pdf"):
    """Submit evidence then approve it with a distinct reviewer. Returns it."""
    submission = submit_evidence(deliverable_id, units_claimed,
                                 evidence_uri=evidence_uri, submitter=submitter)
    return approve_evidence(submission["id"], reviewer=reviewer)


# ---------------------------------------------------------------------------
# Tier 4: season-close / make-good composites
# ---------------------------------------------------------------------------

def advance_season(venue_id):
    """Run the advance-season checkpoint. Returns the updated venue."""
    return get_success_data(api_client.advance_season(venue_id, ADMIN))


def setup_missed_deliverable_with_credit(contract, venue_id, asset_id,
                                         contracted_units=10, approved_units=7,
                                         season=INITIAL_SEASON):
    """Build one deliverable, approve `approved_units`, advance the season so
    the deliverable flips MISSED and the auto-credit lands REQUESTED.
    Returns (deliverable, credit)."""
    deliverable = create_open_deliverable(contract["id"], asset_id,
                                          season=season,
                                          contracted_units=contracted_units)
    if approved_units > 0:
        submit_and_approve(deliverable["id"], approved_units)
    advance_season(venue_id)
    credits, _meta = validate_paginated(api_client.list_credits(
        FINANCE, params={"deliverable_id": deliverable["id"]}))
    assert len(credits) >= 1, "expected an auto-created make-good credit"
    return deliverable, credits[0]


def list_contract_invoices(contract_id):
    """All invoices of a contract in created_at ASC order (= installment_seq)."""
    invoices, _meta = validate_paginated(api_client.list_invoices(
        FINANCE, params={"contract_id": contract_id}))
    return invoices


def issue_invoice(invoice_id):
    return get_success_data(
        api_client.transition_invoice(invoice_id, {"action": "ISSUE"}, FINANCE))


def post_payment(invoice_id, amount_cents, method="ACH"):
    return get_success_data(api_client.post_payment(
        invoice_id, create_payment_payload(amount_cents=amount_cents,
                                           method=method), FINANCE))


def create_report(contract_id, season):
    return get_success_data(
        api_client.create_report(create_report_payload(contract_id, season),
                                 am_headers(AM_SUBMITTER)))


def create_opportunity(contract_id, proposed_fee_cents=12_000_000):
    return get_success_data(api_client.create_opportunity(
        create_opportunity_payload(contract_id,
                                   proposed_fee_cents=proposed_fee_cents), SALES))
