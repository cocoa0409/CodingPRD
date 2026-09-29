"""Composite setup helpers.

Every test starts against an empty database, so every precondition here is built
from scratch through the endpoints the PRD declares, and every instant is driven
through the logical-clock endpoint rather than assumed.

The recurring shape of this domain is one long chain: a seller, an asset listing
whose disclosures have been filed, optionally a county trustee sale, an auction
event, a lot on that event, one or more verified and funded bidders, bids, a
hammer-down close, a title finding, an executed purchase contract, and then
either escrow closing or fallout with a second-chance offer. The builders below
expose that chain at each of its useful stopping points, and each one returns the
records it created so a test can assert against them without re-reading.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    CLOCK_BIDDING,
    CLOCK_CONTRACT,
    CLOCK_EVENT_OPEN,
    CLOCK_LOT_CLOSE,
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    EVENT_END,
    EVENT_START,
    LOT_WINDOW_END,
    LOT_WINDOW_START,
    OPS_CLOSER,
    OPS_CONTRACT,
    STATE_CODE,
)
from .test_users import TEST_USERS, make_bidder_headers, make_seller_headers

ADMIN = TEST_USERS["platform_admin_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
TITLE_OFFICER = TEST_USERS["title_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["auction_ops_headers"]
OPS_CLOSER_HEADERS = TEST_USERS["auction_ops_closer_headers"]
OPS_CONTRACT_HEADERS = TEST_USERS["auction_ops_contract_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def _ok(response, expected_status: int = 200) -> dict:
    """Unwrap a setup response, reporting a broken precondition loudly."""
    assert response.status_code == expected_status, (
        f"setup call failed: expected {expected_status}, got {response.status_code}: "
        f"{response.text}"
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------


@dataclass
class AssetBundle:
    """A seller and one of its asset listings."""

    seller: dict
    listing: dict

    @property
    def seller_id(self) -> str:
        return self.seller["id"]

    @property
    def listing_id(self) -> str:
        return self.listing["id"]

    @property
    def seller_headers(self) -> dict:
        return make_seller_headers(self.seller["id"])


@dataclass
class Scenario:
    """Everything a lot-centred test needs, in one bag."""

    seller: Optional[dict] = None
    listing: Optional[dict] = None
    listings: List[dict] = field(default_factory=list)
    sale: Optional[dict] = None
    event: Optional[dict] = None
    lot: Optional[dict] = None
    lots: List[dict] = field(default_factory=list)
    bidders: List[dict] = field(default_factory=list)
    bids: List[dict] = field(default_factory=list)
    contract: Optional[dict] = None
    offer: Optional[dict] = None

    # --- ids -------------------------------------------------------------
    @property
    def seller_id(self) -> str:
        return self.seller["id"]

    @property
    def listing_id(self) -> str:
        return self.listing["id"]

    @property
    def sale_id(self) -> str:
        return self.sale["id"]

    @property
    def event_id(self) -> str:
        return self.event["id"]

    @property
    def lot_id(self) -> str:
        return self.lot["id"]

    @property
    def contract_id(self) -> str:
        return self.contract["id"]

    @property
    def offer_id(self) -> str:
        return self.offer["id"]

    @property
    def bidder(self) -> dict:
        return self.bidders[0]

    @property
    def bidder_id(self) -> str:
        return self.bidders[0]["id"]

    # --- headers ---------------------------------------------------------
    @property
    def seller_headers(self) -> dict:
        return make_seller_headers(self.seller["id"])

    @property
    def bidder_headers(self) -> dict:
        return make_bidder_headers(self.bidders[0]["id"])

    def headers_for(self, bidder: dict) -> dict:
        return make_bidder_headers(bidder["id"])


# ---------------------------------------------------------------------------
# Tier 1 — the logical clock and single-record builders
# ---------------------------------------------------------------------------


def set_clock(instant: str) -> None:
    """Move the server's logical clock. Setting the clock is inert with respect
    to data, so this only changes what later requests read."""
    _ok(api_client.set_clock(f.set_clock_payload(instant), ADMIN))


def create_seller(**overrides) -> dict:
    return _ok(api_client.create_seller(f.create_seller_payload(**overrides), ADMIN), 201)


def create_listing(seller: dict, **overrides) -> dict:
    return _ok(
        api_client.create_asset_listing(
            f.create_asset_listing_payload(seller["id"], **overrides),
            make_seller_headers(seller["id"]),
        ),
        201,
    )


def file_disclosures(
    seller: dict, listing: dict, occupancy_status: str = "VACANT", title_condition: str = "CLEAR"
) -> dict:
    return _ok(
        api_client.file_disclosures(
            listing["id"],
            f.disclosures_payload(occupancy_status, title_condition),
            make_seller_headers(seller["id"]),
        )
    )


def record_title_clearance(
    listing_id: str,
    clearance_outcome: str = "CLEARED",
    verified_title_condition: str = "CLEAR",
    title_report_reference: str = "TR-0001",
) -> dict:
    return _ok(
        api_client.record_title_clearance(
            listing_id,
            f.title_clearance_payload(
                clearance_outcome,
                verified_title_condition,
                title_report_reference=title_report_reference,
            ),
            TITLE_OFFICER,
        )
    )


def disclosed_asset(
    *,
    occupancy_status: str = "VACANT",
    title_condition: str = "CLEAR",
    county_code: str = COUNTY_PRIMARY,
    state_code: str = STATE_CODE,
    street_address: str = "9 Seaview Ter",
    city: str = "Alameda",
    estimated_value_cents: int = 29000000,
    seller: Optional[dict] = None,
    default_commission_bps: Optional[int] = None,
    org_name: str = "Coastline Bank REO",
    seller_type: str = "BANK",
    contact_email: str = "reo@coastline.example",
    settlement_account_ref: str = "ACH-COAST-5",
) -> AssetBundle:
    """A seller plus one asset listing that has filed its disclosures, so its
    `listing_status` reads `DISCLOSURE_READY` and it is ready to become a lot."""
    if seller is None:
        seller_kwargs = {
            "org_name": org_name,
            "seller_type": seller_type,
            "contact_email": contact_email,
            "settlement_account_ref": settlement_account_ref,
        }
        if default_commission_bps is not None:
            seller_kwargs["default_commission_bps"] = default_commission_bps
        seller = create_seller(**seller_kwargs)
    listing = create_listing(
        seller,
        street_address=street_address,
        city=city,
        county_code=county_code,
        state_code=state_code,
        estimated_value_cents=estimated_value_cents,
    )
    listing = file_disclosures(seller, listing, occupancy_status, title_condition)
    return AssetBundle(seller=seller, listing=listing)


def cleared_asset(
    *,
    verified_title_condition: str = "CLEAR",
    clearance_outcome: str = "CLEARED",
    **kwargs,
) -> AssetBundle:
    """A disclosed asset whose title axis has already been written, so contract
    execution is not blocked by `ERR_TITLE_CLEARANCE_PENDING`."""
    bundle = disclosed_asset(**kwargs)
    bundle.listing = record_title_clearance(
        bundle.listing_id, clearance_outcome, verified_title_condition
    )
    return bundle


# ---------------------------------------------------------------------------
# Tier 2 — the county leg and the auction calendar
# ---------------------------------------------------------------------------


def create_trustee_sale(
    listing_id: str,
    sale_scheduled_at: str,
    *,
    county_code: str = COUNTY_PRIMARY,
    statutory_max_postponements: Optional[int] = None,
) -> dict:
    payload = f.create_trustee_sale_payload(
        listing_id, sale_scheduled_at, county_code=county_code
    )
    if statutory_max_postponements is not None:
        payload["statutory_max_postponements"] = statutory_max_postponements
    return _ok(api_client.create_trustee_sale(payload, TRUSTEE), 201)


def confirm_sale(sale_id: str, confirmation_reference: str = "TS-ALA-7302") -> dict:
    return _ok(
        api_client.confirm_trustee_sale(
            sale_id,
            f.confirm_trustee_sale_payload(confirmation_reference=confirmation_reference),
            TRUSTEE,
        )
    )


def postpone_sale(
    sale_id: str, new_sale_at: str, reason: str = "county calendar congestion"
) -> dict:
    return _ok(
        api_client.postpone_trustee_sale(
            sale_id,
            f.postpone_trustee_sale_payload(new_sale_at, postponement_reason=reason),
            TRUSTEE,
        )
    )


def cancel_sale(sale_id: str, reason: str = "notice rescinded by beneficiary") -> dict:
    return _ok(
        api_client.cancel_trustee_sale(
            sale_id, f.cancel_trustee_sale_payload(cancellation_reason=reason), TRUSTEE
        )
    )


def confirmed_sale(
    listing_id: str,
    sale_scheduled_at: str,
    *,
    county_code: str = COUNTY_PRIMARY,
    statutory_max_postponements: Optional[int] = None,
) -> dict:
    """A noticed county sale already moved to `CONFIRMED`, which is what an event
    bound to it needs before it can be taken live."""
    sale = create_trustee_sale(
        listing_id,
        sale_scheduled_at,
        county_code=county_code,
        statutory_max_postponements=statutory_max_postponements,
    )
    return confirm_sale(sale["id"])


def create_event(
    *,
    title: str = "Alameda REO Session",
    county_code: str = COUNTY_PRIMARY,
    starts_at: str = EVENT_START,
    ends_at: str = EVENT_END,
    trustee_sale_id: Optional[str] = None,
) -> dict:
    payload = f.create_auction_event_payload(
        title=title, county_code=county_code, starts_at=starts_at, ends_at=ends_at
    )
    if trustee_sale_id is not None:
        payload["trustee_sale_id"] = trustee_sale_id
    return _ok(api_client.create_auction_event(payload, OPS), 201)


def read_event(event_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_auction_event(event_id, headers or OPS))


def add_lot(
    event_id: str,
    listing_id: str,
    *,
    lot_number: int = 1,
    lot_window_start_at: str = LOT_WINDOW_START,
    lot_window_end_at: str = LOT_WINDOW_END,
    opening_bid_cents: int = 20000000,
    reserve_price_cents: int = 20000000,
    min_increment_cents: Optional[int] = None,
    expected_auction_event_version: Optional[int] = None,
) -> dict:
    """Add one lot. The parent event's `version` advances on every addition, so
    when no expected version is supplied the event is re-read first."""
    if expected_auction_event_version is None:
        expected_auction_event_version = read_event(event_id)["version"]
    payload = f.add_lot_payload(
        listing_id,
        expected_auction_event_version,
        lot_number=lot_number,
        lot_window_start_at=lot_window_start_at,
        lot_window_end_at=lot_window_end_at,
        opening_bid_cents=opening_bid_cents,
        reserve_price_cents=reserve_price_cents,
    )
    if min_increment_cents is not None:
        payload["min_increment_cents"] = min_increment_cents
    return _ok(api_client.add_lot(event_id, payload, OPS), 201)


def open_event(event_id: str) -> dict:
    return _ok(api_client.open_auction_event(event_id, f.open_event_payload(), OPS))


def reschedule_event(event_id: str, new_starts_at: str, new_ends_at: str) -> dict:
    return _ok(
        api_client.reschedule_auction_event(
            event_id, f.reschedule_payload(new_starts_at, new_ends_at), OPS
        )
    )


def scheduled_lot(
    *,
    occupancy_status: str = "VACANT",
    title_condition: str = "CLEAR",
    county_code: str = COUNTY_PRIMARY,
    event_title: str = "Alameda REO Session",
    starts_at: str = EVENT_START,
    ends_at: str = EVENT_END,
    lot_window_start_at: str = LOT_WINDOW_START,
    lot_window_end_at: str = LOT_WINDOW_END,
    opening_bid_cents: int = 20000000,
    reserve_price_cents: int = 20000000,
    min_increment_cents: Optional[int] = None,
    trustee_sale_at: Optional[str] = None,
    confirm_trustee_sale: bool = True,
    statutory_max_postponements: Optional[int] = None,
    clear_title: bool = False,
    verified_title_condition: str = "CLEAR",
    clearance_outcome: str = "CLEARED",
    default_commission_bps: Optional[int] = None,
    estimated_value_cents: int = 29000000,
    clock: str = CLOCK_SETUP,
    **asset_kwargs,
) -> Scenario:
    """A `SCHEDULED` event carrying one `PENDING` lot on a disclosed asset,
    optionally bound to a county sale and optionally with its title axis already
    written. Any further keyword argument describes the seller or the asset and is
    forwarded to the asset builder. The clock is left at the quiet setup instant."""
    set_clock(clock)
    bundle = (
        cleared_asset(
            occupancy_status=occupancy_status,
            title_condition=title_condition,
            county_code=county_code,
            estimated_value_cents=estimated_value_cents,
            default_commission_bps=default_commission_bps,
            verified_title_condition=verified_title_condition,
            clearance_outcome=clearance_outcome,
            **asset_kwargs,
        )
        if clear_title
        else disclosed_asset(
            occupancy_status=occupancy_status,
            title_condition=title_condition,
            county_code=county_code,
            estimated_value_cents=estimated_value_cents,
            default_commission_bps=default_commission_bps,
            **asset_kwargs,
        )
    )
    sale = None
    if trustee_sale_at is not None:
        sale = create_trustee_sale(
            bundle.listing_id,
            trustee_sale_at,
            county_code=county_code,
            statutory_max_postponements=statutory_max_postponements,
        )
        if confirm_trustee_sale:
            sale = confirm_sale(sale["id"])
    event = create_event(
        title=event_title,
        county_code=county_code,
        starts_at=starts_at,
        ends_at=ends_at,
        trustee_sale_id=sale["id"] if sale else None,
    )
    lot = add_lot(
        event["id"],
        bundle.listing_id,
        lot_window_start_at=lot_window_start_at,
        lot_window_end_at=lot_window_end_at,
        opening_bid_cents=opening_bid_cents,
        reserve_price_cents=reserve_price_cents,
        min_increment_cents=min_increment_cents,
    )
    return Scenario(
        seller=bundle.seller,
        listing=bundle.listing,
        listings=[bundle.listing],
        sale=sale,
        event=event,
        lot=lot,
        lots=[lot],
    )


def live_lot(*, open_at: str = CLOCK_EVENT_OPEN, **kwargs) -> Scenario:
    """A `LIVE` event whose single lot is `OPEN` and accepting bids."""
    scenario = scheduled_lot(**kwargs)
    set_clock(open_at)
    scenario.event = open_event(scenario.event_id)
    scenario.lot = read_lot(scenario.lot_id)
    scenario.lots = [scenario.lot]
    return scenario


# ---------------------------------------------------------------------------
# Tier 2 — bidders
# ---------------------------------------------------------------------------


def register_bidder(
    *,
    legal_name: str = "Seaview Acquisitions LLC",
    email: str = "bid@seaviewacq.example",
    mailing_address: str = "2 Ferry Point, Alameda CA",
) -> dict:
    """A self-registered bidder: `UNVERIFIED` identity and `PENDING_REVIEW`
    registration."""
    return _ok(
        api_client.create_bidder(
            f.create_bidder_payload(
                legal_name=legal_name, email=email, mailing_address=mailing_address
            ),
            ANONYMOUS,
        ),
        201,
    )


def verify_bidder(
    bidder_id: str, decision: str = "VERIFIED", document_reference: str = "KYC-5151"
) -> dict:
    return _ok(
        api_client.record_identity_verification(
            bidder_id,
            f.identity_verification_payload(decision, document_reference=document_reference),
            COMPLIANCE,
        )
    )


def fund(bidder_id: str, amount_cents: int, funding_reference: str = "WIRE-13579") -> dict:
    return _ok(
        api_client.fund_deposit(
            bidder_id,
            f.fund_deposit_payload(amount_cents, funding_reference=funding_reference),
            make_bidder_headers(bidder_id),
        )
    )


def funded_bidder(
    amount_cents: int,
    *,
    legal_name: str = "Seaview Acquisitions LLC",
    email: str = "bid@seaviewacq.example",
    mailing_address: str = "2 Ferry Point, Alameda CA",
    document_reference: str = "KYC-5151",
    funding_reference: str = "WIRE-13579",
    verified: bool = True,
) -> dict:
    """A bidder that has cleared identity verification and funded its wallet, so
    it is `REGISTERED` with `deposit_available_cents` equal to the amount funded."""
    bidder = register_bidder(
        legal_name=legal_name, email=email, mailing_address=mailing_address
    )
    if verified:
        bidder = verify_bidder(bidder["id"], "VERIFIED", document_reference)
    if amount_cents > 0:
        bidder = fund(bidder["id"], amount_cents, funding_reference)
    return bidder


def funded_bidders(count: int, amount_cents: int, *, prefix: str = "Bidder") -> List[dict]:
    """Several verified, funded bidders with distinct names and emails."""
    bidders = []
    for index in range(1, count + 1):
        bidders.append(
            funded_bidder(
                amount_cents,
                legal_name=f"{prefix} {index} LLC",
                email=f"bidder{index}@example.test",
                mailing_address=f"{index} Market St, Oakland CA",
                document_reference=f"KYC-{index:04d}",
                funding_reference=f"WIRE-{index:04d}",
            )
        )
    return bidders


def create_exclusion(
    bidder_id: str,
    exclusion_type: str,
    effective_at: str,
    *,
    county_code: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    payload = f.create_exclusion_payload(bidder_id, exclusion_type, effective_at)
    if county_code is not None:
        payload["county_code"] = county_code
    if notes is not None:
        payload["notes"] = notes
    return _ok(api_client.create_eligibility_exclusion(payload, COMPLIANCE), 201)


def lift_exclusion(exclusion_id: str, notes: Optional[str] = None) -> dict:
    payload = f.lift_exclusion_payload()
    if notes is not None:
        payload["notes"] = notes
    return _ok(api_client.lift_eligibility_exclusion(exclusion_id, payload, COMPLIANCE))


# ---------------------------------------------------------------------------
# Tier 3 — bidding, close, contract
# ---------------------------------------------------------------------------


def place_bid(lot_id: str, bidder_id: str, amount_cents: int) -> dict:
    return _ok(
        api_client.place_bid(
            lot_id,
            f.place_bid_payload(bidder_id, amount_cents),
            make_bidder_headers(bidder_id),
        ),
        201,
    )


def close_lot(lot_id: str, closer_user_id: str = OPS_CLOSER) -> dict:
    from .test_users import make_auction_ops_headers

    return _ok(
        api_client.close_lot(
            lot_id, f.close_lot_payload(), make_auction_ops_headers(closer_user_id)
        )
    )


def execute_contract(
    lot_id: str,
    *,
    closing_window_days: Optional[int] = None,
    executor_user_id: str = OPS_CONTRACT,
) -> dict:
    from .test_users import make_auction_ops_headers

    payload = f.sale_contract_payload()
    if closing_window_days is not None:
        payload["closing_window_days"] = closing_window_days
    return _ok(
        api_client.execute_sale_contract(
            lot_id, payload, make_auction_ops_headers(executor_user_id)
        ),
        201,
    )


def close_contract(
    contract_id: str, closing_reference: str = "ESC-2026-4471", operator: str = OPS_CONTRACT
) -> dict:
    from .test_users import make_auction_ops_headers

    return _ok(
        api_client.close_sale_contract(
            contract_id,
            f.close_contract_payload(closing_reference=closing_reference),
            make_auction_ops_headers(operator),
        )
    )


def record_fallout(
    contract_id: str,
    reason: str = "buyer financing collapsed",
    operator: str = OPS_CONTRACT,
) -> dict:
    from .test_users import make_auction_ops_headers

    return _ok(
        api_client.record_fallout(
            contract_id,
            f.fallout_payload(fallout_reason=reason),
            make_auction_ops_headers(operator),
        )
    )


def create_offer(
    lot_id: str, *, expires_at: Optional[str] = None, operator: str = OPS_CONTRACT
) -> dict:
    from .test_users import make_auction_ops_headers

    payload = f.second_chance_offer_payload()
    if expires_at is not None:
        payload["expires_at"] = expires_at
    return _ok(
        api_client.create_second_chance_offer(
            lot_id, payload, make_auction_ops_headers(operator)
        ),
        201,
    )


def respond_to_offer(offer_id: str, bidder_id: str, decision: str = "ACCEPTED") -> dict:
    return _ok(
        api_client.respond_to_offer(
            offer_id, f.respond_to_offer_payload(decision), make_bidder_headers(bidder_id)
        )
    )


def sold_lot(
    *,
    bid_amount_cents: int = 20000000,
    funded_cents: int = 2000000,
    bid_at: str = CLOCK_BIDDING,
    close_at: str = CLOCK_LOT_CLOSE,
    closer_user_id: str = OPS_CLOSER,
    bidder_legal_name: str = "Seaview Acquisitions LLC",
    bidder_email: str = "bid@seaviewacq.example",
    **lot_kwargs,
) -> Scenario:
    """A lot hammered down `CLOSED_SOLD` to a single reserve-clearing bidder whose
    deposit hold is the only one still encumbered."""
    scenario = live_lot(**lot_kwargs)
    bidder = funded_bidder(
        funded_cents, legal_name=bidder_legal_name, email=bidder_email
    )
    scenario.bidders = [bidder]
    set_clock(bid_at)
    bid = place_bid(scenario.lot_id, bidder["id"], bid_amount_cents)
    scenario.bids = [bid]
    set_clock(close_at)
    scenario.lot = close_lot(scenario.lot_id, closer_user_id)
    return scenario


def executed_contract(
    *,
    clearance_outcome: str = "CLEARED",
    verified_title_condition: str = "CLEAR",
    clear_title_before_close: bool = False,
    execute_at: str = CLOCK_CONTRACT,
    closing_window_days: Optional[int] = 21,
    executor_user_id: str = OPS_CONTRACT,
    **sold_kwargs,
) -> Scenario:
    """A sold lot whose title work has landed and whose purchase contract has been
    executed, so `contract_status` reads `EXECUTED` and the settlement is `POSTED`."""
    if clear_title_before_close:
        sold_kwargs.setdefault("clear_title", True)
        sold_kwargs.setdefault("clearance_outcome", clearance_outcome)
        sold_kwargs.setdefault("verified_title_condition", verified_title_condition)
    scenario = sold_lot(**sold_kwargs)
    if not clear_title_before_close:
        scenario.listing = record_title_clearance(
            scenario.listing_id, clearance_outcome, verified_title_condition
        )
    set_clock(execute_at)
    scenario.contract = execute_contract(
        scenario.lot_id,
        closing_window_days=closing_window_days,
        executor_user_id=executor_user_id,
    )
    return scenario


def fallen_out_contract(*, fallout_at: str = "2026-09-20T00:00:00Z", **kwargs) -> Scenario:
    """An executed contract taken through fallout: the settlement is `VOID`, the
    winner's deposit is `CAPTURED` and the asset is `RELIST_PENDING`."""
    scenario = executed_contract(**kwargs)
    set_clock(fallout_at)
    scenario.contract = record_fallout(scenario.contract_id)
    return scenario


def outstanding_offer(
    *,
    offer_at: str = "2026-09-20T00:10:00Z",
    expires_at: Optional[str] = None,
    **kwargs,
) -> Scenario:
    """A fallen-out lot carrying one `OUTSTANDING` second-chance offer."""
    scenario = fallen_out_contract(**kwargs)
    set_clock(offer_at)
    scenario.offer = create_offer(scenario.lot_id, expires_at=expires_at)
    return scenario


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def read_seller(seller_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_seller(seller_id, headers or ADMIN))


def read_listing(listing_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_asset_listing(listing_id, headers or ADMIN))


def read_sale(sale_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_trustee_sale(sale_id, headers or ADMIN))


def read_lot(lot_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_auction_lot(lot_id, headers or OPS))


def read_bidder(bidder_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_bidder(bidder_id, headers or ADMIN))


def read_bid(bid_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_bid(bid_id, headers or ADMIN))


def read_hold(hold_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_deposit_hold(hold_id, headers or ADMIN))


def read_contract(contract_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_sale_contract(contract_id, headers or ADMIN))


def read_offer(offer_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_second_chance_offer(offer_id, headers or ADMIN))


def _collection(response) -> List[dict]:
    assert response.status_code == 200, f"list call failed: {response.text}"
    return get_success_data(response)


def list_holds(headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(api_client.list_deposit_holds(headers or ADMIN, params=params or None))


def list_bids(headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(api_client.list_bids(headers or ADMIN, params=params or None))


def list_offers(headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(
        api_client.list_second_chance_offers(headers or ADMIN, params=params or None)
    )


def list_lots(headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(api_client.list_auction_lots(headers or ADMIN, params=params or None))


def list_events(headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(api_client.list_auction_events(headers or ADMIN, params=params or None))


def list_listings(headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(api_client.list_asset_listings(headers or ADMIN, params=params or None))


def list_lot_contracts(lot_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(
        api_client.list_lot_sale_contracts(lot_id, headers or ADMIN, params=params or None)
    )


def list_exclusions(bidder_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(
        api_client.list_bidder_exclusions(bidder_id, headers or ADMIN, params=params or None)
    )


def list_sale_events(sale_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(
        api_client.list_trustee_sale_auction_events(
            sale_id, headers or ADMIN, params=params or None
        )
    )


def list_listing_sales(listing_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(
        api_client.list_asset_listing_trustee_sales(
            listing_id, headers or ADMIN, params=params or None
        )
    )


def list_seller_listings(seller_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return _collection(
        api_client.list_seller_asset_listings(seller_id, headers or ADMIN, params=params or None)
    )


def settlement_preview(lot_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(api_client.get_settlement_preview(lot_id, headers or OPS))


def eligibility_assessment(
    bidder_id: str,
    *,
    mode: Optional[str] = None,
    auction_lot_id: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    params = {}
    if mode is not None:
        params["mode"] = mode
    if auction_lot_id is not None:
        params["auction_lot_id"] = auction_lot_id
    return _ok(
        api_client.get_eligibility_assessment(
            bidder_id, headers or COMPLIANCE, params=params or None
        )
    )


def holds_for_bidder(bidder_id: str) -> List[dict]:
    return list_holds(bidder_id=bidder_id)


def sole_hold(bidder_id: str) -> dict:
    holds = holds_for_bidder(bidder_id)
    assert len(holds) == 1, f"expected exactly one hold, got {len(holds)}"
    return holds[0]
