"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before every test.
Helpers use get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion mismatches.

The canonical timeline these helpers walk (PRD reference scenario):
  clock default 2026-03-01  -> create facility/tenant/unit + lien notice
                               (provisional lien 89000, cure_deadline 2026-03-15)
  clock 2026-03-20          -> mature (final lien 94000, tenant REVOKED)
  auction window [2026-03-21, 2026-03-22)
  clock 2026-03-21T01:00    -> open (unit IN_AUCTION)
  bid 150000
  clock 2026-03-22          -> close (Sale created, deposit 20000 held)
  pay                        -> Settlement finalized (surplus 41000)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_platform_admin_headers,
    make_facility_operator_headers,
    make_buyer_headers,
    make_tenant_headers,
)
from .factories import (
    create_facility_payload,
    create_tenant_payload,
    create_unit_payload,
    create_lien_notice_payload,
    create_buyer_payload,
    fund_deposit_payload,
    create_auction_payload,
    place_bid_payload,
)
from .constants import (
    CANONICAL,
    CLOCK_MATURE,
    CLOCK_OPEN,
    CLOCK_CLOSE,
    AUCTION_START,
    AUCTION_END,
)

ADMIN = make_platform_admin_headers()


# --------------------------------------------------------------------------
# Low-level building blocks
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Advance the logical clock (PlatformAdmin only)."""
    return api.set_clock({"to_iso8601": iso}, ADMIN)


def create_facility(api, **overrides) -> dict:
    resp = api.create_facility(create_facility_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_tenant(api, facility_id, **overrides) -> dict:
    resp = api.create_tenant(create_tenant_payload(facility_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_unit(api, facility_id, tenant_id, **overrides) -> dict:
    resp = api.create_unit(create_unit_payload(facility_id, tenant_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_buyer(api, **overrides) -> dict:
    resp = api.create_buyer(create_buyer_payload(**overrides), ADMIN)
    return get_success_data(resp)


def fund_buyer(api, buyer_id, amount_cents=CANONICAL["deposit_funded_cents"]) -> dict:
    resp = api.fund_deposit(buyer_id, fund_deposit_payload(amount_cents), make_buyer_headers(buyer_id))
    return get_success_data(resp)


def create_lien_notice(api, unit_id, facility_id, **overrides) -> dict:
    resp = api.create_lien_notice(
        unit_id, create_lien_notice_payload(**overrides), make_facility_operator_headers(facility_id)
    )
    return get_success_data(resp)


def get_sale_for_auction(api, auction_id) -> dict:
    resp = api.list_sales(ADMIN, params={"auction_id": auction_id})
    data = get_success_data(resp)
    assert data, f"Setup failed: no sale found for auction {auction_id}"
    return data[0]


# --------------------------------------------------------------------------
# Tier 1/2: onboarding + lien maturation
# --------------------------------------------------------------------------
def setup_matured_unit(api, mature_clock=CLOCK_MATURE, unit_number="A1", **unit_overrides) -> dict:
    """Facility + tenant + unit, lien notice declared at the clock default, then
    matured at `mature_clock`. Leaves the clock at `mature_clock` and the unit in
    LIEN_MATURED. Returns a ctx dict with fac/ten/unit ids plus the notice id and
    the facility-operator headers."""
    facility = create_facility(api)
    fac = facility["id"]
    tenant = create_tenant(api, fac)
    ten = tenant["id"]
    unit = create_unit(api, fac, ten, unit_number=unit_number, **unit_overrides)
    unit_id = unit["id"]
    notice = create_lien_notice(api, unit_id, fac)
    fac_hdr = make_facility_operator_headers(fac)
    set_clock(api, mature_clock)
    get_success_data(api.mature_lien_notice(notice["id"], fac_hdr))
    return {
        "facility": facility,
        "fac": fac,
        "fac_hdr": fac_hdr,
        "tenant": tenant,
        "ten": ten,
        "ten_hdr": make_tenant_headers(ten),
        "unit": unit,
        "unit_id": unit_id,
        "notice": notice,
        "notice_id": notice["id"],
    }


def setup_scheduled_auction(api, mode="ONLINE", start_at=AUCTION_START, end_at=AUCTION_END,
                            reserve_cents=50000, min_increment_cents=5000, **matured_kwargs) -> dict:
    """Matured unit + one SCHEDULED auction. Clock still at maturation instant."""
    ctx = setup_matured_unit(api, **matured_kwargs)
    resp = api.create_auction(
        create_auction_payload(
            ctx["unit_id"], mode=mode, start_at=start_at, end_at=end_at,
            reserve_cents=reserve_cents, min_increment_cents=min_increment_cents,
        ),
        ctx["fac_hdr"],
    )
    auction = get_success_data(resp)
    ctx["auction"] = auction
    ctx["auc"] = auction["id"]
    return ctx


def setup_live_auction(api, open_clock=CLOCK_OPEN, reserve_cents=50000,
                       min_increment_cents=5000, **matured_kwargs) -> dict:
    """Matured unit + SCHEDULED auction opened to LIVE (unit IN_AUCTION). Captures
    the auction version at open in ctx['auc_version']. Clock left at open_clock."""
    ctx = setup_scheduled_auction(
        api, reserve_cents=reserve_cents, min_increment_cents=min_increment_cents, **matured_kwargs
    )
    set_clock(api, open_clock)
    opened = get_success_data(api.open_auction(ctx["auc"], ctx["fac_hdr"]))
    ctx["auction"] = opened
    ctx["auc_version"] = opened["version"]
    return ctx


def setup_funded_live_auction(api, deposit=CANONICAL["deposit_funded_cents"], **kwargs) -> dict:
    """LIVE auction + one registered, funded buyer. ctx adds buyer/buyer_id/buyer_hdr."""
    ctx = setup_live_auction(api, **kwargs)
    buyer = create_buyer(api)
    fund_buyer(api, buyer["id"], deposit)
    ctx["buyer"] = buyer
    ctx["buyer_id"] = buyer["id"]
    ctx["buyer_hdr"] = make_buyer_headers(buyer["id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 3/4: bid -> close -> sale -> pay
# --------------------------------------------------------------------------
def setup_sale(api, winning_amount_cents=CANONICAL["winning_amount_cents"],
               deposit=CANONICAL["deposit_funded_cents"], close_clock=CLOCK_CLOSE, **kwargs) -> dict:
    """Full pipeline through auction close with one winning bid: a Sale exists in
    payment_status UNPAID / cleanout_status PENDING, with 20000 of the winner's
    deposit held. Clock left at close_clock. ctx adds sale/sale_id."""
    ctx = setup_funded_live_auction(api, deposit=deposit, **kwargs)
    get_success_data(api.place_bid(
        ctx["auc"],
        place_bid_payload(ctx["buyer_id"], winning_amount_cents, ctx["auc_version"]),
        ctx["buyer_hdr"],
    ))
    set_clock(api, close_clock)
    get_success_data(api.close_auction(ctx["auc"], ctx["fac_hdr"]))
    sale = get_sale_for_auction(api, ctx["auc"])
    ctx["sale"] = sale
    ctx["sale_id"] = sale["id"]
    return ctx


def setup_paid_sale(api, **kwargs) -> dict:
    """Full pipeline through payment: Settlement finalized, tenant surplus and
    facility recovery credited, auction SETTLED. ctx adds settlement/settlement_id."""
    ctx = setup_sale(api, **kwargs)
    get_success_data(api.pay_sale(ctx["sale_id"], ctx["buyer_hdr"]))
    settlement = get_success_data(api.get_sale_settlement(ctx["sale_id"], ADMIN))
    assert settlement, f"Setup failed: no settlement for sale {ctx['sale_id']}"
    ctx["settlement"] = settlement[0]
    ctx["settlement_id"] = settlement[0]["id"]
    return ctx


def setup_reviewed_sale_dispute(api, raised_by="BUYER", **kwargs) -> dict:
    """Paid sale + a SALE dispute raised and moved to UNDER_REVIEW. ctx adds
    dispute/dispute_id. Raiser defaults to the buyer."""
    ctx = setup_paid_sale(api, **kwargs)
    if raised_by == "BUYER":
        raiser_hdr = ctx["buyer_hdr"]
    else:
        raiser_hdr = ctx["ten_hdr"]
    dispute = get_success_data(api.create_dispute(
        {"subject_type": "SALE", "sale_id": ctx["sale_id"], "raised_by": raised_by,
         "reason": "contents misrepresented"},
        raiser_hdr,
    ))
    get_success_data(api.review_dispute(dispute["id"], ADMIN))
    ctx["dispute"] = dispute
    ctx["dispute_id"] = dispute["id"]
    return ctx


def setup_buyer_suspended_with_open_sale(api) -> dict:
    """One buyer wins two auctions (units u1, u2) at the same facility -> sale_a
    and sale_b; the clock advances past both payment deadlines and sale_a is
    forfeited, SUSPENDING the buyer while sale_b remains UNPAID. Returns a ctx dict
    with fac/ten, buyer, sale_a_id, sale_b_id, and the buyer/operator headers.
    Clock left inside sale_b's still-open payment window (2026-03-23) so that a pay
    attempt on sale_b trips only the suspension guard."""
    facility = create_facility(api)
    fac = facility["id"]
    fac_hdr = make_facility_operator_headers(fac)
    tenant = create_tenant(api, fac)
    ten = tenant["id"]
    u1 = create_unit(api, fac, ten, unit_number="U1")["id"]
    u2 = create_unit(api, fac, ten, unit_number="U2")["id"]
    n1 = create_lien_notice(api, u1, fac)["id"]
    n2 = create_lien_notice(api, u2, fac)["id"]
    set_clock(api, CLOCK_MATURE)
    get_success_data(api.mature_lien_notice(n1, fac_hdr))
    get_success_data(api.mature_lien_notice(n2, fac_hdr))
    a1 = get_success_data(api.create_auction(
        create_auction_payload(u1, start_at=AUCTION_START, end_at=AUCTION_END), fac_hdr))["id"]
    a2 = get_success_data(api.create_auction(
        create_auction_payload(u2, start_at=AUCTION_START, end_at=AUCTION_END), fac_hdr))["id"]
    set_clock(api, CLOCK_OPEN)
    a1v = get_success_data(api.open_auction(a1, fac_hdr))["version"]
    a2v = get_success_data(api.open_auction(a2, fac_hdr))["version"]
    buyer = create_buyer(api)
    bid = buyer["id"]
    buyer_hdr = make_buyer_headers(bid)
    fund_buyer(api, bid, CANONICAL["deposit_funded_cents"])
    get_success_data(api.place_bid(a1, place_bid_payload(bid, 150000, a1v), buyer_hdr))
    get_success_data(api.place_bid(a2, place_bid_payload(bid, 150000, a2v), buyer_hdr))
    set_clock(api, CLOCK_CLOSE)
    get_success_data(api.close_auction(a1, fac_hdr))
    get_success_data(api.close_auction(a2, fac_hdr))
    sale_a = get_sale_for_auction(api, a1)
    sale_b = get_sale_for_auction(api, a2)
    from .constants import CLOCK_PAST_PAYMENT_DEADLINE, CLOCK_WITHIN_PAYMENT_WINDOW
    set_clock(api, CLOCK_PAST_PAYMENT_DEADLINE)
    get_success_data(api.forfeit_sale(sale_a["id"], fac_hdr))
    # Forfeiting sale_a past its deadline SUSPENDS the buyer. sale_a and sale_b were
    # created at the same close (identical 2026-03-24 payment_deadline), so leaving
    # the clock past that deadline confounds a pay attempt on sale_b: both the
    # expired-window guard AND the suspension guard would trip, and PRD Sec 3.6 lists
    # the window check before the suspension check. Reset the clock into sale_b's
    # still-open window so a pay attempt trips ONLY ERR_BUYER_SUSPENDED.
    set_clock(api, CLOCK_WITHIN_PAYMENT_WINDOW)
    return {
        "facility": facility, "fac": fac, "fac_hdr": fac_hdr,
        "tenant": tenant, "ten": ten,
        "buyer": buyer, "buyer_id": bid, "buyer_hdr": buyer_hdr,
        "sale_a": sale_a, "sale_a_id": sale_a["id"],
        "sale_b": sale_b, "sale_b_id": sale_b["id"],
    }


def setup_reviewed_settlement_dispute(api, **kwargs) -> dict:
    """Paid sale + a SETTLEMENT dispute (raised by the tenant) moved to
    UNDER_REVIEW. ctx adds dispute/dispute_id."""
    ctx = setup_paid_sale(api, **kwargs)
    dispute = get_success_data(api.create_dispute(
        {"subject_type": "SETTLEMENT", "settlement_id": ctx["settlement_id"],
         "raised_by": "TENANT", "reason": "surplus miscomputed"},
        ctx["ten_hdr"],
    ))
    get_success_data(api.review_dispute(dispute["id"], ADMIN))
    ctx["dispute"] = dispute
    ctx["dispute_id"] = dispute["id"]
    return ctx
