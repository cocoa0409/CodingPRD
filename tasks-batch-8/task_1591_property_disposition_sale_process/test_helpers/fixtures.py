"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test) and the logical clock starts at exactly
2026-08-01T00:00:00Z, so these helpers build complete precondition chains out
of PRD-declared endpoints only.

Identity threading: Buyer calls are entity-backed by Bidder. Workspace dicts
carry "buyer_headers" built from the real Bidder.id via make_buyer_headers;
ownership-gated calls never fall back to the shared Buyer constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_AFTER_DEADLINE,
    CLOCK_PAST_DD_20,
    CLOSING_DATE_ALPHA,
    CLOSING_DATE_DELTA,
    DOCUMENT_CATEGORIES,
    ENGAGEMENT_WINDOW_END,
    ENGAGEMENT_WINDOW_START,
    OFFERS_DEADLINE,
    TAX_PERIOD_START,
)
from .factories import (
    create_analysis_payload,
    create_asset_payload,
    create_bid_payload,
    create_bidder_payload,
    create_dd_item_payload,
    create_engagement_payload,
    create_package_payload,
    create_payoff_payload,
    create_psa_payload,
    create_statement_payload,
    delta_asset_payload,
)
from .test_users import TEST_USERS, make_buyer_headers

DM = TEST_USERS["dm_headers"]
ANALYST = TEST_USERS["analyst_headers"]
IC = TEST_USERS["ic_headers"]
BROKER = TEST_USERS["broker_headers"]
CO = TEST_USERS["co_headers"]
LS = TEST_USERS["ls_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and single-step transitions
# ---------------------------------------------------------------------------

def create_asset(payload=None, **overrides) -> dict:
    """Create an Asset (born marketing EVALUATION, deal IDLE)."""
    body = payload if payload is not None else create_asset_payload(**overrides)
    return get_success_data(api_client.create_asset(body, DM))


def get_asset(asset_id) -> dict:
    return get_success_data(api_client.get_asset(asset_id, DM))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, DM))


def create_analysis(asset_id, expected_asset_version=None, creator=ANALYST,
                    **overrides) -> dict:
    """Create a HoldSellAnalysis (DRAFT). Reads the asset's current version
    for the OCC guard when expected_asset_version is not given."""
    if expected_asset_version is None:
        expected_asset_version = get_asset(asset_id)["version"]
    payload = create_analysis_payload(asset_id, expected_asset_version, **overrides)
    return get_success_data(api_client.create_analysis(payload, creator))


def submit_analysis(analysis_id, headers=ANALYST) -> dict:
    return get_success_data(api_client.submit_analysis(analysis_id, headers))


def decide_analysis(analysis_id, decision="APPROVE", headers=IC) -> dict:
    return get_success_data(api_client.decide_analysis(analysis_id, decision, headers))


def create_approved_analysis(asset_id, creator_headers=ANALYST,
                             decider_headers=IC, **overrides) -> dict:
    """Create -> submit -> APPROVE. Creator and decider are distinct users."""
    analysis = create_analysis(asset_id, creator=creator_headers, **overrides)
    submit_analysis(analysis["id"], creator_headers)
    return decide_analysis(analysis["id"], "APPROVE", decider_headers)


def create_engagement(asset_id, window_start=ENGAGEMENT_WINDOW_START,
                      window_end=ENGAGEMENT_WINDOW_END, **overrides) -> dict:
    payload = create_engagement_payload(asset_id, window_start, window_end, **overrides)
    return get_success_data(api_client.create_engagement(payload, DM))


def activate_engagement(engagement_id) -> dict:
    return get_success_data(api_client.activate_engagement(engagement_id, DM))


def create_active_engagement(asset_id, **kwargs) -> dict:
    engagement = create_engagement(asset_id, **kwargs)
    return activate_engagement(engagement["id"])


def create_package(asset_id) -> dict:
    return get_success_data(
        api_client.create_package(create_package_payload(asset_id), ANALYST))


def upload_all_categories(package_id, uploader=ANALYST) -> dict:
    docs = [{"category": cat, "file_name": f"{cat.lower()}.pdf"}
            for cat in DOCUMENT_CATEGORIES]
    return get_success_data(api_client.upload_documents(package_id, docs, uploader))


def verify_all_categories(package_id, verifier=DM, categories=None) -> dict:
    cats = categories if categories is not None else DOCUMENT_CATEGORIES
    return get_success_data(api_client.verify_documents(package_id, cats, verifier))


def publish_package(package_id) -> dict:
    return get_success_data(api_client.publish_package(package_id, DM))


def create_published_package(asset_id, uploader=ANALYST, verifier=DM) -> dict:
    """Package with all eight required categories uploaded and verified,
    published. Uploader and verifier are distinct users (segregation)."""
    package = create_package(asset_id)
    upload_all_categories(package["id"], uploader)
    verify_all_categories(package["id"], verifier)
    return publish_package(package["id"])


def list_asset_for_sale(asset_id) -> dict:
    return get_success_data(api_client.list_asset_for_sale(asset_id, DM))


def open_offers(asset_id, offers_deadline=OFFERS_DEADLINE) -> dict:
    return get_success_data(api_client.open_asset_offers(asset_id, offers_deadline, DM))


def close_offers(asset_id) -> dict:
    return get_success_data(api_client.close_asset_offers(asset_id, DM))


def register_bidder(asset_id, proof_of_funds_cents, organization_name="BuyerCo",
                    registrar=BROKER) -> dict:
    payload = create_bidder_payload(asset_id, proof_of_funds_cents,
                                    organization_name=organization_name)
    return get_success_data(api_client.create_bidder(payload, registrar))


def qualify_bidder(bidder_id) -> dict:
    return get_success_data(api_client.qualify_bidder(bidder_id, DM))


def register_qualified_bidder(asset_id, proof_of_funds_cents,
                              organization_name="BuyerCo") -> dict:
    bidder = register_bidder(asset_id, proof_of_funds_cents, organization_name)
    return qualify_bidder(bidder["id"])


def place_bid(asset_id, bidder_id, price_cents, deposit_cents, dd_period_days=30,
              closing_period_days=45) -> dict:
    """Submit a bid as the entity-backed Buyer (X-User-ID == bidder_id)."""
    payload = create_bid_payload(asset_id, bidder_id, price_cents, deposit_cents,
                                 dd_period_days, closing_period_days)
    return get_success_data(
        api_client.create_bid(payload, make_buyer_headers(bidder_id)))


def shortlist_bid(bid_id) -> dict:
    return get_success_data(api_client.shortlist_bid(bid_id, DM))


def select_bid(bid_id) -> dict:
    return get_success_data(api_client.select_bid(bid_id, DM))


def create_psa(asset_id, bid_id, convention="ACTUAL_365") -> dict:
    """Create a DRAFT PSA from a SELECTED bid; reads the asset's current
    version for the OCC guard."""
    version = get_asset(asset_id)["version"]
    payload = create_psa_payload(asset_id, bid_id, version, convention)
    return get_success_data(api_client.create_psa(payload, DM))


def execute_psa(psa_id, closing_date=CLOSING_DATE_ALPHA) -> dict:
    return get_success_data(api_client.execute_psa(psa_id, closing_date, DM))


def list_psa_deposits(psa_id) -> list:
    return get_success_data(api_client.list_psa_deposits(psa_id, CO))


def post_deposit(deposit_id) -> dict:
    return get_success_data(api_client.post_deposit(deposit_id, CO))


def open_dd(psa_id) -> dict:
    return get_success_data(api_client.open_dd(psa_id, DM))


def file_dd_item(psa_id, requested_reduction_cents, buyer_headers,
                 category="PHYSICAL", description="finding") -> dict:
    payload = create_dd_item_payload(psa_id, requested_reduction_cents,
                                     category=category, description=description)
    return get_success_data(api_client.create_dd_item(payload, buyer_headers))


# ---------------------------------------------------------------------------
# Tier 2-3: pipeline composites (marketing -> offers -> bid -> PSA -> DD)
# ---------------------------------------------------------------------------

def pipeline_through_offers(asset_payload=None, analysis_overrides=None,
                            offers_deadline=OFFERS_DEADLINE) -> dict:
    """Asset created, analysis APPROVED, engagement ACTIVE, package PUBLISHED,
    asset LISTED then OFFERS_OPEN. Returns the workspace dict."""
    asset = create_asset(asset_payload)
    analysis = create_approved_analysis(asset["id"], **(analysis_overrides or {}))
    engagement = create_active_engagement(asset["id"])
    package = create_published_package(asset["id"])
    list_asset_for_sale(asset["id"])
    asset = open_offers(asset["id"], offers_deadline)
    return {
        "asset": asset,
        "analysis": analysis,
        "engagement": engagement,
        "package": package,
    }


def pipeline_to_bid(ws=None, price_cents=5_000_000_000, deposit_cents=150_000_000,
                    dd_period_days=30, closing_period_days=45,
                    proof_of_funds=1_500_000_000, **kwargs) -> dict:
    """Adds a QUALIFIED bidder and its SUBMITTED bid to a marketed asset."""
    if ws is None:
        ws = pipeline_through_offers(**kwargs)
    bidder = register_qualified_bidder(ws["asset"]["id"], proof_of_funds)
    bid = place_bid(ws["asset"]["id"], bidder["id"], price_cents, deposit_cents,
                    dd_period_days, closing_period_days)
    ws.update({
        "bidder": bidder,
        "bid": bid,
        "buyer_headers": make_buyer_headers(bidder["id"]),
    })
    return ws


def pipeline_to_psa_draft(ws=None, convention="ACTUAL_365",
                          close_clock=CLOCK_AFTER_DEADLINE, **kwargs) -> dict:
    """Advances the logical clock past the offers deadline, closes the round,
    shortlists and selects the bid, then creates the DRAFT PSA (asset deal
    dimension IDLE -> PSA_DRAFT)."""
    if ws is None:
        ws = pipeline_to_bid(**kwargs)
    set_clock(close_clock)
    close_offers(ws["asset"]["id"])
    shortlist_bid(ws["bid"]["id"])
    bid = select_bid(ws["bid"]["id"])
    psa = create_psa(ws["asset"]["id"], ws["bid"]["id"], convention)
    ws.update({
        "bid": bid,
        "psa": psa,
        "asset": get_asset(ws["asset"]["id"]),
    })
    return ws


def pipeline_to_executed(ws=None, closing_date=CLOSING_DATE_ALPHA, **kwargs) -> dict:
    """Executes the DRAFT PSA; the two-row deposit schedule (INITIAL then
    ADDITIONAL, both DUE) is attached to the workspace."""
    if ws is None:
        ws = pipeline_to_psa_draft(**kwargs)
    psa = execute_psa(ws["psa"]["id"], closing_date)
    deposits = list_psa_deposits(psa["id"])
    ws.update({
        "psa": psa,
        "deposits": deposits,
        "asset": get_asset(ws["asset"]["id"]),
    })
    return ws


def pipeline_to_dd_active(ws=None, post_additional=True, **kwargs) -> dict:
    """Posts the INITIAL deposit (and the ADDITIONAL by default) and opens due
    diligence; asset deal dimension reaches DD_ACTIVE."""
    if ws is None:
        ws = pipeline_to_executed(**kwargs)
    post_deposit(ws["deposits"][0]["id"])
    if post_additional:
        post_deposit(ws["deposits"][1]["id"])
    psa = open_dd(ws["psa"]["id"])
    ws.update({
        "psa": psa,
        "deposits": list_psa_deposits(psa["id"]),
        "asset": get_asset(ws["asset"]["id"]),
    })
    return ws


def pipeline_to_binding(ws=None, lapse_clock=None, **kwargs) -> dict:
    """Lapses the due-diligence termination right once the logical clock is
    strictly after dd_deadline; agreement reaches BINDING."""
    if ws is None:
        ws = pipeline_to_dd_active(**kwargs)
    psa = get_success_data(api_client.get_psa(ws["psa"]["id"], DM))
    dd_deadline = psa["dd_deadline"]
    if lapse_clock is None:
        lapse_clock = CLOCK_PAST_DD_20 if str(dd_deadline) <= "2026-10-07" \
            else "2026-10-17T00:00:00Z"
    set_clock(lapse_clock)
    psa = get_success_data(api_client.lapse_dd(ws["psa"]["id"], DM))
    ws.update({"psa": psa, "asset": get_asset(ws["asset"]["id"])})
    return ws


# ---------------------------------------------------------------------------
# Tier 4-5: payoff / statement / full closing composites
# ---------------------------------------------------------------------------

def create_confirmed_payoff(asset_id, method="PAYOFF", reinvestment_rate_bps=300,
                            accrued_days=15,
                            anticipated_settlement_date=CLOSING_DATE_DELTA) -> dict:
    payload = create_payoff_payload(
        asset_id, method=method, reinvestment_rate_bps=reinvestment_rate_bps,
        accrued_days=accrued_days,
        anticipated_settlement_date=anticipated_settlement_date)
    payoff = get_success_data(api_client.create_payoff(payload, DM))
    return get_success_data(api_client.confirm_payoff(payoff["id"], LS))


def create_approved_statement(psa_id, property_tax_annual_cents=0,
                              tax_period_start=TAX_PERIOD_START,
                              rent_monthly_cents=0, cam_annual_cents=0,
                              preparer=CO, approver=DM) -> dict:
    """DRAFT -> PENDING_REVIEW -> APPROVED; preparer and approver differ."""
    payload = create_statement_payload(
        psa_id, property_tax_annual_cents=property_tax_annual_cents,
        tax_period_start=tax_period_start, rent_monthly_cents=rent_monthly_cents,
        cam_annual_cents=cam_annual_cents)
    statement = get_success_data(api_client.create_statement(payload, preparer))
    submit = get_success_data(api_client.submit_statement(statement["id"], preparer))
    return get_success_data(api_client.approve_statement(submit["id"], approver))


def setup_closed_delta_deal() -> dict:
    """Full sale of the Delta (STEP_DOWN) asset end to end: bid pipeline ->
    PSA executed (closing 2026-10-15) -> both deposits POSTED -> DD_ACTIVE ->
    payoff CONFIRMED -> statement APPROVED -> BINDING -> CLOSING -> payoff
    SETTLED -> record_closing. Returns the workspace including the
    auto-created EscrowHoldback."""
    ws = pipeline_to_dd_active(
        asset_payload=delta_asset_payload(),
        analysis_overrides={
            "cap_rate_bps": 650, "exit_cap_rate_bps": 700,
            "est_sale_price_cents": 1_900_000_000,
            "est_selling_costs_cents": 50_000_000,
        },
        proof_of_funds=500_000_000,
        price_cents=1_800_000_000,
        deposit_cents=54_000_000,
        dd_period_days=20,
        closing_date=CLOSING_DATE_DELTA,
    )
    payoff = create_confirmed_payoff(ws["asset"]["id"])
    statement = create_approved_statement(
        ws["psa"]["id"],
        property_tax_annual_cents=18_250_000,
        rent_monthly_cents=4_960_000,
        cam_annual_cents=7_300_000,
    )
    set_clock(CLOCK_PAST_DD_20)
    psa = get_success_data(api_client.lapse_dd(ws["psa"]["id"], DM))
    psa = get_success_data(api_client.begin_closing(psa["id"], DM))
    payoff = get_success_data(api_client.settle_payoff(payoff["id"], CO))
    psa = get_success_data(api_client.record_closing(psa["id"], CO))
    escrows = get_success_data(api_client.list_psa_escrows(psa["id"], DM))
    ws.update({
        "psa": psa,
        "payoff": payoff,
        "statement": statement,
        "escrow": escrows[0],
        "asset": get_asset(ws["asset"]["id"]),
        "engagement": get_success_data(
            api_client.list_asset_engagements(ws["asset"]["id"], DM))[0],
    })
    return ws
