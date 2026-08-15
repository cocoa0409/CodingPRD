"""Composite setup helpers for the farmland auction workflows (PRD §3).

Every helper builds its preconditions from scratch via PRD-declared endpoints —
the harness restarts the server (empty database) before each test. Setup calls
use get_success_data() so a setup failure surfaces as a clear "Setup failed"
error rather than a confusing assertion deep inside a test.

Identity threading: after creating an entity-backed party, all ownership-gated
calls use make_<role>_headers(entity["id"]) — never the shared TEST_USERS
fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AUCTION_END,
    AUCTION_START,
    IA_COMPARABLE_C1,
    IA_COMPARABLES_TRIPLE,
    QUALIFICATION_EXPIRY,
    TARGET_CLOSING_DATE,
)
from .factories import (
    create_agent_payload,
    create_auction_payload,
    create_buyer_payload,
    create_closing_payload,
    create_comparable_payload,
    create_disclosure_payload,
    create_listing_payload,
    create_rights_payload,
    create_seller_payload,
    create_tract_payload,
    place_bid_payload,
    qualify_buyer_payload,
    record_payment_payload,
    track_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_agent_headers,
    make_buyer_headers,
    make_seller_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Tier 0: clock + parties ─────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock and run all time sweeps (PRD §2.5)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_seller(full_name: str = "Seller One", email: str = "s1@x.com") -> dict:
    return get_success_data(
        api_client.create_seller(create_seller_payload(full_name=full_name, email=email), ADMIN)
    )


def create_agent(full_name: str = "Agent One", license_number: str = "LIC-001") -> dict:
    return get_success_data(
        api_client.create_agent(
            create_agent_payload(full_name=full_name, license_number=license_number),
            ADMIN,
        )
    )


def create_buyer(
    full_name: str = "Buyer One",
    email: str = "b1@x.com",
    proof_of_funds_amount=2000000,
) -> dict:
    """Buyer starts UNVERIFIED (PRD §3.1)."""
    return get_success_data(
        api_client.create_buyer(
            create_buyer_payload(
                full_name=full_name,
                email=email,
                proof_of_funds_amount=proof_of_funds_amount,
            ),
            ADMIN,
        )
    )


def qualify_buyer(buyer_id: str, expires_at: str = QUALIFICATION_EXPIRY) -> dict:
    return get_success_data(
        api_client.qualify_buyer(
            buyer_id, qualify_buyer_payload(qualification_expires_at=expires_at), ADMIN
        )
    )


def create_qualified_buyer(**kwargs) -> dict:
    expires_at = kwargs.pop("expires_at", QUALIFICATION_EXPIRY)
    buyer = create_buyer(**kwargs)
    return qualify_buyer(buyer["id"], expires_at)


def make_parties():
    """Seller + agent pair; returns (seller, agent). Headers derive from ids."""
    return create_seller(), create_agent()


# ─── Tier 1: comparables ─────────────────────────────────────────────

def post_comparable(**overrides) -> dict:
    return get_success_data(
        api_client.create_comparable(create_comparable_payload(**overrides), ADMIN)
    )


def post_standard_ia_comparables() -> list:
    """The three-county IA set used by the valuation and settlement flows."""
    return [
        get_success_data(api_client.create_comparable(dict(comp), ADMIN))
        for comp in IA_COMPARABLES_TRIPLE
    ]


def post_single_ia_comparable() -> dict:
    """One IA comp (C1): a 100ac/SPI80 tract provisionally values at 900000."""
    return get_success_data(
        api_client.create_comparable(dict(IA_COMPARABLE_C1), ADMIN)
    )


# ─── Tier 2: listing assembly (DRAFT -> PACKAGED -> MARKETED) ────────

def create_draft_listing(
    agent: dict,
    seller: dict,
    title: str = "L1",
    county: str = "Dallas",
    state_code: str = "IA",
    total_gross_acres=100,
    packaging_strategy: str = "WHOLE",
    reserve_price_total=770000,
) -> dict:
    return get_success_data(
        api_client.create_listing(
            create_listing_payload(
                seller["id"],
                title=title,
                county=county,
                state_code=state_code,
                total_gross_acres=total_gross_acres,
                packaging_strategy=packaging_strategy,
                reserve_price_total=reserve_price_total,
            ),
            make_agent_headers(agent["id"]),
        )
    )


def read_listing(listing_id: str, headers) -> dict:
    return get_success_data(api_client.get_listing(listing_id, headers))


def listing_version(listing_id: str, headers) -> int:
    return read_listing(listing_id, headers)["version"]


def add_tract(
    agent: dict,
    listing_id: str,
    tract_number: int = 1,
    gross_acres=100,
    tillable_acres=90,
    soil_productivity_index=80,
    min_price=700000,
) -> dict:
    """Add a tract with a freshly-read listing version (OCC per PRD §2.7)."""
    headers = make_agent_headers(agent["id"])
    version = listing_version(listing_id, headers)
    return get_success_data(
        api_client.create_tract(
            create_tract_payload(
                listing_id,
                version,
                tract_number=tract_number,
                gross_acres=gross_acres,
                tillable_acres=tillable_acres,
                soil_productivity_index=soil_productivity_index,
                min_price=min_price,
            ),
            headers,
        )
    )


def declare_rights(
    agent: dict,
    tract_id: str,
    mineral_rights: str = "CONVEYED",
    wind_rights: str = "CONVEYED",
) -> dict:
    return get_success_data(
        api_client.create_rights(
            create_rights_payload(
                tract_id, mineral_rights=mineral_rights, wind_rights=wind_rights
            ),
            make_agent_headers(agent["id"]),
        )
    )


def create_lease_disclosure(
    agent: dict,
    tract_id: str,
    tenant_name: str = "Tenant A",
    lease_start_date: str = "2025-03-01T00:00:00Z",
    lease_end_date: str = "2026-10-15T00:00:00Z",
    annual_rent=18000,
) -> dict:
    return get_success_data(
        api_client.create_disclosure(
            create_disclosure_payload(
                tract_id,
                tenant_name=tenant_name,
                lease_start_date=lease_start_date,
                lease_end_date=lease_end_date,
                annual_rent=annual_rent,
            ),
            make_agent_headers(agent["id"]),
        )
    )


def package_listing(agent: dict, listing_id: str) -> dict:
    return get_success_data(
        api_client.package_listing(listing_id, make_agent_headers(agent["id"]))
    )


def market_listing(agent: dict, listing_id: str) -> dict:
    return get_success_data(
        api_client.market_listing(listing_id, make_agent_headers(agent["id"]))
    )


DEFAULT_TRACT_SPEC = {
    "tract_number": 1,
    "gross_acres": 100,
    "tillable_acres": 90,
    "soil_productivity_index": 80,
    "min_price": 700000,
}


def setup_marketed_listing(
    agent=None,
    seller=None,
    title: str = "L1",
    county: str = "Dallas",
    state_code: str = "IA",
    total_gross_acres=100,
    packaging_strategy: str = "WHOLE",
    reserve_price_total=770000,
    tract_specs=None,
    comparables: str = "single",
    with_disclosure: bool = False,
    disclosure_kwargs=None,
) -> dict:
    """DRAFT -> PACKAGED -> MARKETED listing with rights DECLARED per tract.

    tract_specs: list of per-tract kwargs (defaults to one 100ac/SPI80 tract).
    comparables: "single" (C1 only), "triple" (C1+C2+C3), or "none".
    Returns {seller, agent, listing, tracts, disclosure}.
    """
    if seller is None or agent is None:
        seller, agent = make_parties()
    if comparables == "single":
        post_single_ia_comparable()
    elif comparables == "triple":
        post_standard_ia_comparables()

    listing = create_draft_listing(
        agent,
        seller,
        title=title,
        county=county,
        state_code=state_code,
        total_gross_acres=total_gross_acres,
        packaging_strategy=packaging_strategy,
        reserve_price_total=reserve_price_total,
    )
    specs = tract_specs if tract_specs is not None else [dict(DEFAULT_TRACT_SPEC)]
    tracts = [add_tract(agent, listing["id"], **spec) for spec in specs]
    for tract in tracts:
        declare_rights(agent, tract["id"])
    disclosure = None
    if with_disclosure:
        disclosure = create_lease_disclosure(
            agent, tracts[0]["id"], **(disclosure_kwargs or {})
        )
    package_listing(agent, listing["id"])
    listing = market_listing(agent, listing["id"])
    return {
        "seller": seller,
        "agent": agent,
        "listing": listing,
        "tracts": tracts,
        "disclosure": disclosure,
    }


# ─── Tier 3: auction scheduling and bidding ──────────────────────────

def schedule_auction(
    agent: dict,
    listing_id: str,
    method: str = "ONLINE",
    scheduled_start: str = AUCTION_START,
    scheduled_end: str = AUCTION_END,
    soft_close_window_minutes=None,
    extension_minutes=None,
) -> dict:
    payload_kwargs = {}
    if soft_close_window_minutes is not None:
        payload_kwargs["soft_close_window_minutes"] = soft_close_window_minutes
    if extension_minutes is not None:
        payload_kwargs["extension_minutes"] = extension_minutes
    return get_success_data(
        api_client.create_auction(
            create_auction_payload(
                listing_id,
                method=method,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                **payload_kwargs,
            ),
            make_agent_headers(agent["id"]),
        )
    )


def open_auction_at(agent: dict, auction_id: str, at_iso: str) -> dict:
    """Drive the clock into the window, then open (PRD §3.5)."""
    set_clock(at_iso)
    return get_success_data(
        api_client.open_auction(auction_id, make_agent_headers(agent["id"]))
    )


def read_auction(auction_id: str, headers) -> dict:
    return get_success_data(api_client.get_auction(auction_id, headers))


def auction_version(auction_id: str, headers) -> int:
    return read_auction(auction_id, headers)["version"]


def place_bid_fresh(buyer: dict, auction_id: str, amount, tract_ids):
    """Place a bid with the auction's current version. Returns raw Response
    so the caller decides whether success or an error is expected."""
    buyer_headers = make_buyer_headers(buyer["id"])
    version = auction_version(auction_id, buyer_headers)
    return api_client.place_bid(
        place_bid_payload(auction_id, amount, tract_ids, version), buyer_headers
    )


def setup_open_auction(
    method: str = "ONLINE",
    open_at: str = AUCTION_START,
    scheduled_start: str = AUCTION_START,
    scheduled_end: str = AUCTION_END,
    **listing_kwargs,
) -> dict:
    """Marketed listing + auction opened inside its window.

    Returns setup_marketed_listing's dict plus {auction}.
    """
    soft_close = listing_kwargs.pop("soft_close_window_minutes", None)
    extension = listing_kwargs.pop("extension_minutes", None)
    env = setup_marketed_listing(**listing_kwargs)
    auction = schedule_auction(
        env["agent"],
        env["listing"]["id"],
        method=method,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        soft_close_window_minutes=soft_close,
        extension_minutes=extension,
    )
    auction = open_auction_at(env["agent"], auction["id"], open_at)
    env["auction"] = auction
    return env


def award_auction_at(agent: dict, auction_id: str, at_iso: str) -> dict:
    """Drive the clock to effective_end (close sweep runs), then award."""
    set_clock(at_iso)
    return get_success_data(
        api_client.award_auction(auction_id, make_agent_headers(agent["id"]))
    )


def winning_deposit(bid_id: str, headers) -> dict:
    """A winning bid spawns exactly one deposit (PRD §3.7)."""
    deposits = get_success_data(api_client.list_bid_deposits(bid_id, headers))
    assert isinstance(deposits, list) and len(deposits) == 1, (
        f"expected exactly one deposit for winning bid, got {deposits!r}"
    )
    return deposits[0]


# ─── Tier 4: full awarded flows ──────────────────────────────────────

def setup_awarded_whole(
    bid_amount=770000,
    method: str = "LIVE",
    buyer_kwargs=None,
    **listing_kwargs,
) -> dict:
    """WHOLE listing carried through award: listing UNDER_CONTRACT, the single
    tract SOLD, the winning bid CONFIRMED_WINNER, deposit PENDING.

    Defaults: 100ac tract (min 700000), reserve 770000, single C1 comp,
    auction 2026-08-10 17:00-19:00Z, bid placed at open and awarded at end.
    """
    env = setup_open_auction(method=method, **listing_kwargs)
    buyer = create_qualified_buyer(**(buyer_kwargs or {}))
    bid = get_success_data(
        place_bid_fresh(buyer, env["auction"]["id"], bid_amount, [env["tracts"][0]["id"]])
    )
    auction = award_auction_at(env["agent"], env["auction"]["id"], AUCTION_END)
    agent_headers = make_agent_headers(env["agent"]["id"])
    deposit = winning_deposit(bid["id"], agent_headers)
    env.update(
        {
            "buyer": buyer,
            "bid": bid,
            "auction": auction,
            "deposit": deposit,
            "listing": read_listing(env["listing"]["id"], agent_headers),
        }
    )
    return env


COMBINATION_TRACT_SPECS = [
    {
        "tract_number": 1,
        "gross_acres": 100,
        "tillable_acres": 90,
        "soil_productivity_index": 80,
        "min_price": 700000,
    },
    {
        "tract_number": 2,
        "gross_acres": 60,
        "tillable_acres": 30,
        "soil_productivity_index": 70,
        "min_price": 350000,
    },
]


def setup_awarded_combination(
    combo_amount=1400000,
    with_disclosure: bool = False,
    buyer_kwargs=None,
) -> dict:
    """COMBINATION listing (160ac, T1 100ac/SPI80 + T2 60ac/SPI70, reserve
    1200000) carried through award: one combination bid over both tracts wins,
    listing UNDER_CONTRACT, both tracts SOLD, deposit PENDING (3% of the
    winning amount; 42000.00 at the default amount).

    Returns {seller, agent, listing, tracts, disclosure, auction, buyer, bid, deposit}.
    """
    env = setup_open_auction(
        method="ONLINE",
        total_gross_acres=160,
        packaging_strategy="COMBINATION",
        reserve_price_total=1200000,
        tract_specs=[dict(spec) for spec in COMBINATION_TRACT_SPECS],
        comparables="triple",
        with_disclosure=with_disclosure,
    )
    buyer = create_qualified_buyer(
        full_name="Buyer Three", email="b3@x.com", **(buyer_kwargs or {})
    )
    tract_ids = [t["id"] for t in env["tracts"]]
    bid = get_success_data(
        place_bid_fresh(buyer, env["auction"]["id"], combo_amount, tract_ids)
    )
    auction = award_auction_at(env["agent"], env["auction"]["id"], AUCTION_END)
    agent_headers = make_agent_headers(env["agent"]["id"])
    deposit = winning_deposit(bid["id"], agent_headers)
    env.update(
        {
            "buyer": buyer,
            "bid": bid,
            "auction": auction,
            "deposit": deposit,
            "listing": read_listing(env["listing"]["id"], agent_headers),
        }
    )
    return env


# ─── Tier 5: escrow, closing, and terminal states ────────────────────

def record_payment(agent: dict, deposit_id: str, amount) -> dict:
    return get_success_data(
        api_client.record_payment(
            deposit_id, record_payment_payload(amount), make_agent_headers(agent["id"])
        )
    )


def verify_deposit(deposit_id: str) -> dict:
    """Verification is PlatformAdmin-only (PRD §3.7 segregation of duties)."""
    return get_success_data(api_client.verify_deposit(deposit_id, ADMIN))


def pay_and_verify_deposit(agent: dict, deposit_id: str, amount) -> dict:
    record_payment(agent, deposit_id, amount)
    return verify_deposit(deposit_id)


def acknowledge_disclosure(buyer: dict, disclosure_id: str) -> dict:
    return get_success_data(
        api_client.acknowledge_disclosure(
            disclosure_id, make_buyer_headers(buyer["id"])
        )
    )


def create_closing(
    agent: dict,
    auction_id: str,
    target_closing_date: str = TARGET_CLOSING_DATE,
    payoff_amount=0,
) -> dict:
    return get_success_data(
        api_client.create_closing(
            create_closing_payload(
                auction_id,
                target_closing_date=target_closing_date,
                payoff_amount=payoff_amount,
            ),
            make_agent_headers(agent["id"]),
        )
    )


def track_event(closing_id: str, headers, axis: str, event: str, seller_consent=None):
    payload = track_event_payload(axis, event)
    if seller_consent is not None:
        payload["seller_consent"] = seller_consent
    return get_success_data(api_client.post_track_event(closing_id, payload, headers))


def drive_to_ready_to_close(agent: dict, closing_id: str, survey_style: str = "WAIVE") -> dict:
    """Walk title to CLEARED and survey to WAIVED/COMPLETED; overall becomes
    READY_TO_CLOSE (PRD §3.8). TITLE/SURVEY events are BrokerAgent-only."""
    headers = make_agent_headers(agent["id"])
    track_event(closing_id, headers, "TITLE", "ORDER_COMMITMENT")
    track_event(closing_id, headers, "TITLE", "RECEIVE_COMMITMENT")
    track_event(closing_id, headers, "TITLE", "CLEAR")
    if survey_style == "WAIVE":
        result = track_event(
            closing_id, headers, "SURVEY", "WAIVE", seller_consent=True
        )
    else:
        track_event(closing_id, headers, "SURVEY", "ORDER")
        result = track_event(closing_id, headers, "SURVEY", "COMPLETE")
    return result


def setup_closing_ready(
    with_disclosure: bool = True,
    payoff_amount=200000,
    target_closing_date: str = TARGET_CLOSING_DATE,
    survey_style: str = "COMPLETE",
) -> dict:
    """Full flow: awarded COMBINATION listing, deposit paid (42000.00) and
    VERIFIED, disclosure ACKNOWLEDGED (when present), closing created and
    driven to READY_TO_CLOSE. Returns the awarded-flow dict plus {closing}."""
    env = setup_awarded_combination(with_disclosure=with_disclosure)
    pay_and_verify_deposit(env["agent"], env["deposit"]["id"], 42000)
    if with_disclosure and env["disclosure"] is not None:
        env["disclosure"] = acknowledge_disclosure(
            env["buyer"], env["disclosure"]["id"]
        )
    closing = create_closing(
        env["agent"],
        env["auction"]["id"],
        target_closing_date=target_closing_date,
        payoff_amount=payoff_amount,
    )
    closing = drive_to_ready_to_close(env["agent"], closing["id"], survey_style)
    env["closing"] = closing
    return env
