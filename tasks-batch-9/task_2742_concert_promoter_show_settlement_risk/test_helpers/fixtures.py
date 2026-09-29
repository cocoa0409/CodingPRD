"""Composite setup builders.

Every test starts against an empty database, so all preconditions have to be
built through the declared endpoints. ``Builder`` wraps one client and exposes
progressively richer setups, from a single row up to a fully performed show
with an open settlement book.

Setup calls use the lenient ``get_success_data`` reader: a fixture is not the
thing under test, so it asserts only that the call succeeded.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing.validators import get_success_data

from . import factories as f
from .api_client import ShowSettlementApiClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    make_artist_rep_headers,
    make_risk_officer_headers,
    make_talent_buyer_headers,
    make_tour_accountant_headers,
    make_venue_operator_headers,
)

# Stable actor identities so that segregation-of-duties pairs can be composed
# deliberately rather than by accident.
BUYER_ID = "buyer-quinn"
ACCOUNTANT_ALICE = "acct-alice"
ACCOUNTANT_BOB = "acct-bob"
RISK_RITA = "risk-rita"
RISK_ROB = "risk-rob"


class Builder:
    """Composes preconditions for one client against an empty database."""

    def __init__(self, api: ShowSettlementApiClient) -> None:
        self.api = api
        self.buyer = make_talent_buyer_headers(BUYER_ID)
        self.accountant = make_tour_accountant_headers(ACCOUNTANT_ALICE)
        self.accountant_two = make_tour_accountant_headers(ACCOUNTANT_BOB)
        self.risk = make_risk_officer_headers(RISK_RITA)
        self.risk_two = make_risk_officer_headers(RISK_ROB)

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------

    def artist_rep(self, artist_id: str) -> Dict[str, str]:
        return make_artist_rep_headers(artist_id)

    def venue_operator(self, venue_id: str) -> Dict[str, str]:
        return make_venue_operator_headers(venue_id)

    # ------------------------------------------------------------------
    # Clock and housekeeping
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str = DEFAULT_CLOCK) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(current_utc, self.risk))

    def run_housekeeping(self) -> Dict[str, Any]:
        return get_success_data(self.api.run_housekeeping(self.risk))

    # ------------------------------------------------------------------
    # Tier 1 — single rows
    # ------------------------------------------------------------------

    def market(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_market(f.market_payload(**kwargs), self.risk)
        )

    def artist(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_artist(f.artist_payload(**kwargs), self.buyer)
        )

    def venue(self, market_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_venue(f.venue_payload(market_id, **kwargs), self.buyer)
        )

    def show(self, artist_id: str, venue_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_show(f.show_payload(artist_id, venue_id, **kwargs), self.buyer)
        )

    def tier(self, show_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_ticket_tier(
                f.ticket_tier_payload(show_id, **kwargs), self.buyer
            )
        )

    def hold(self, ticket_tier_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_ticket_hold(
                f.ticket_hold_payload(ticket_tier_id, **kwargs), self.buyer
            )
        )

    def budget_line(self, show_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_budget_line(
                f.budget_line_payload(show_id, **kwargs), self.accountant
            )
        )

    # ------------------------------------------------------------------
    # Tier 2 — a market, an act and a venue that agree with each other
    # ------------------------------------------------------------------

    def world(
        self,
        guarantee_exposure_limit_cents: int = 10_000_000,
        gross_capacity: int = 3000,
        facility_fee_cents_per_ticket: int = 350,
        ticket_tax_pct: float = 8.00,
        withholding_pct: Optional[float] = 0,
        market_name: Optional[str] = None,
        venue_name: Optional[str] = None,
        artist_name: Optional[str] = None,
        tier: str = "ARENA",
    ) -> Dict[str, Any]:
        market = self.market(
            name=market_name,
            guarantee_exposure_limit_cents=guarantee_exposure_limit_cents,
        )
        artist = self.artist(name=artist_name, tier=tier, withholding_pct=withholding_pct)
        venue = self.venue(
            market["id"],
            name=venue_name,
            gross_capacity=gross_capacity,
            facility_fee_cents_per_ticket=facility_fee_cents_per_ticket,
            ticket_tax_pct=ticket_tax_pct,
        )
        return {"market": market, "artist": artist, "venue": venue}

    def planned_show(self, **world_kwargs: Any) -> Dict[str, Any]:
        """A market, an act, a venue and a PLANNED show on that venue."""
        show_kwargs = world_kwargs.pop("show", {}) or {}
        ctx = self.world(**world_kwargs)
        ctx["show"] = self.show(ctx["artist"]["id"], ctx["venue"]["id"], **show_kwargs)
        return ctx

    # ------------------------------------------------------------------
    # Tier 3 — offers and a confirmed show
    # ------------------------------------------------------------------

    def offer(self, show_id: str, expected_show_version: Optional[int] = None, **kwargs: Any) -> Dict[str, Any]:
        if expected_show_version is None:
            expected_show_version = self.read_show(show_id)["version"]
        return get_success_data(
            self.api.create_offer(
                f.offer_payload(show_id, expected_show_version, **kwargs), self.buyer
            )
        )

    def submitted_offer(self, show_id: str, **kwargs: Any) -> Dict[str, Any]:
        offer = self.offer(show_id, **kwargs)
        return get_success_data(self.api.submit_offer(offer["id"], self.buyer))

    def accepted_offer(self, show_id: str, artist_id: str, **kwargs: Any) -> Dict[str, Any]:
        offer = self.submitted_offer(show_id, **kwargs)
        return get_success_data(
            self.api.accept_offer(offer["id"], self.artist_rep(artist_id))
        )

    def confirmed_show(
        self,
        guarantee_cents: int = 2_000_000,
        deposit_cents: int = 0,
        expense_cap_cents: int = 4_000_000,
        deal_structure: str = "FLAT_GUARANTEE",
        versus_pct: Optional[float] = None,
        backend_split_artist_pct: Optional[float] = None,
        **world_kwargs: Any,
    ) -> Dict[str, Any]:
        ctx = self.planned_show(**world_kwargs)
        ctx["offer"] = self.accepted_offer(
            ctx["show"]["id"],
            ctx["artist"]["id"],
            deal_structure=deal_structure,
            guarantee_cents=guarantee_cents,
            deposit_cents=deposit_cents,
            expense_cap_cents=expense_cap_cents,
            versus_pct=versus_pct,
            backend_split_artist_pct=backend_split_artist_pct,
        )
        ctx["show"] = self.read_show(ctx["show"]["id"])
        return ctx

    # ------------------------------------------------------------------
    # Tier 4 — inventory, sales and a performed show
    # ------------------------------------------------------------------

    def on_sale_show(
        self,
        tiers: Optional[List[Dict[str, Any]]] = None,
        announce_at: str = "2026-08-15T15:00:00.000Z",
        **confirmed_kwargs: Any,
    ) -> Dict[str, Any]:
        show_kwargs = confirmed_kwargs.pop("show", {}) or {}
        show_kwargs.setdefault("announce_at", announce_at)
        ctx = self.confirmed_show(show=show_kwargs, **confirmed_kwargs)
        specs = tiers if tiers is not None else [{"tier_name": "GA"}]
        ctx["tiers"] = [self.tier(ctx["show"]["id"], **spec) for spec in specs]
        self.set_clock(announce_at)
        get_success_data(self.api.put_show_on_sale(ctx["show"]["id"], self.buyer))
        ctx["show"] = self.read_show(ctx["show"]["id"])
        ctx["tiers"] = [self.read_tier(t["id"]) for t in ctx["tiers"]]
        return ctx

    def sell(self, ticket_tier_id: str, qty: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.record_sales(ticket_tier_id, self.buyer, qty=qty)
        )

    def reprice(self, ticket_tier_id: str, show_id: str, new_price_cents: int) -> Dict[str, Any]:
        version = self.read_show(show_id)["version"]
        return get_success_data(
            self.api.adjust_tier_price(
                ticket_tier_id,
                self.buyer,
                new_price_cents=new_price_cents,
                expected_show_version=version,
                reason="sustained demand after the first sales week",
            )
        )

    def performed_show(
        self,
        event_at: str = "2026-10-10T02:00:00.000Z",
        perform_at: str = "2026-10-10T06:00:00.000Z",
        **on_sale_kwargs: Any,
    ) -> Dict[str, Any]:
        show_kwargs = on_sale_kwargs.pop("show", {}) or {}
        show_kwargs.setdefault("event_at", event_at)
        ctx = self.on_sale_show(show=show_kwargs, **on_sale_kwargs)
        self.set_clock(perform_at)
        get_success_data(self.api.perform_show(ctx["show"]["id"], self.accountant))
        ctx["show"] = self.read_show(ctx["show"]["id"])
        return ctx

    # ------------------------------------------------------------------
    # Tier 4 — invoices and variance decisions
    # ------------------------------------------------------------------

    def approved_invoice(
        self, show_id: str, budget_line_id: str, amount_cents: int, **kwargs: Any
    ) -> Dict[str, Any]:
        """Submit, verify and approve an invoice with two distinct actors."""
        invoice = get_success_data(
            self.api.create_vendor_invoice(
                f.vendor_invoice_payload(
                    show_id, budget_line_id, amount_cents=amount_cents, **kwargs
                ),
                self.accountant,
            )
        )
        get_success_data(self.api.verify_vendor_invoice(invoice["id"], self.accountant))
        return get_success_data(
            self.api.approve_vendor_invoice(invoice["id"], self.accountant_two)
        )

    def verified_invoice(
        self, show_id: str, budget_line_id: str, amount_cents: int, **kwargs: Any
    ) -> Dict[str, Any]:
        invoice = get_success_data(
            self.api.create_vendor_invoice(
                f.vendor_invoice_payload(
                    show_id, budget_line_id, amount_cents=amount_cents, **kwargs
                ),
                self.accountant,
            )
        )
        return get_success_data(
            self.api.verify_vendor_invoice(invoice["id"], self.accountant)
        )

    def submitted_invoice(
        self, show_id: str, budget_line_id: str, amount_cents: int, **kwargs: Any
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_vendor_invoice(
                f.vendor_invoice_payload(
                    show_id, budget_line_id, amount_cents=amount_cents, **kwargs
                ),
                self.accountant,
            )
        )

    def line_with_actual(
        self,
        show_id: str,
        budgeted_cents: int,
        actual_cents: int,
        category: str = "PRODUCTION",
        is_artist_deductible: Optional[bool] = None,
        vendor_name: str = "Cascade Staging",
    ) -> Dict[str, Any]:
        """A budget line whose actual_cents has been driven by one approved invoice."""
        line = self.budget_line(
            show_id,
            category=category,
            budgeted_cents=budgeted_cents,
            is_artist_deductible=is_artist_deductible,
        )
        self.approved_invoice(
            show_id, line["id"], actual_cents, vendor_name=vendor_name
        )
        return self.read_budget_line(line["id"])

    def approve_variance(
        self, budget_line_id: str, approved_cap_cents: int, as_risk_officer: bool = False
    ) -> Dict[str, Any]:
        headers = self.risk if as_risk_officer else self.accountant_two
        return get_success_data(
            self.api.decide_variance(
                budget_line_id,
                headers,
                decision="APPROVE",
                approved_cap_cents=approved_cap_cents,
                variance_justification="overage reviewed against the signed change order",
            )
        )

    def reject_variance(
        self, budget_line_id: str, as_risk_officer: bool = False
    ) -> Dict[str, Any]:
        headers = self.risk if as_risk_officer else self.accountant_two
        return get_success_data(
            self.api.decide_variance(
                budget_line_id,
                headers,
                decision="REJECT",
                variance_justification="the overage was not authorised in advance",
            )
        )

    # ------------------------------------------------------------------
    # Tier 5 — settlement book
    # ------------------------------------------------------------------

    def settlement(self, show_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_settlement(f.settlement_payload(show_id), self.accountant)
        )

    def calculated_settlement(self, show_id: str) -> Dict[str, Any]:
        book = self.settlement(show_id)
        return get_success_data(
            self.api.calculate_settlement(book["id"], self.accountant)
        )

    def signed_settlement(self, show_id: str, artist_id: str) -> Dict[str, Any]:
        book = self.calculated_settlement(show_id)
        return get_success_data(
            self.api.respond_to_settlement(
                book["id"], self.artist_rep(artist_id), response="SIGN"
            )
        )

    def paid_settlement(
        self, show_id: str, artist_id: str, payment_method: str = "WIRE"
    ) -> Dict[str, Any]:
        book = self.signed_settlement(show_id, artist_id)
        return get_success_data(
            self.api.pay_settlement(
                book["id"],
                self.accountant_two,
                payment_method=payment_method,
                payment_reference="WIRE-000001",
            )
        )

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancellation_event(self, show_id: str, kind: str = "CANCELLED", **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_cancellation_event(
                f.cancellation_event_payload(show_id, kind=kind, **kwargs), self.buyer
            )
        )

    def refunds_processed_event(self, show_id: str, kind: str = "CANCELLED") -> Dict[str, Any]:
        event = self.cancellation_event(show_id, kind=kind)
        return get_success_data(
            self.api.process_refunds(event["id"], self.accountant)
        )

    def claim_filed_event(
        self, show_id: str, claim_amount_cents: int, kind: str = "CANCELLED"
    ) -> Dict[str, Any]:
        event = self.refunds_processed_event(show_id, kind=kind)
        return get_success_data(
            self.api.file_claim(
                event["id"],
                self.risk,
                claim_amount_cents=claim_amount_cents,
                claim_documentation_ref="CLAIM-00001",
            )
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def read_market(self, market_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_market(market_id, self.risk))

    def read_artist(self, artist_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_artist(artist_id, self.buyer))

    def read_venue(self, venue_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_venue(venue_id, self.buyer))

    def read_show(self, show_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_show(show_id, self.buyer))

    def read_offer(self, offer_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_offer(offer_id, self.buyer))

    def read_budget_line(self, budget_line_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_budget_line(budget_line_id, self.accountant))

    def read_invoice(self, vendor_invoice_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_vendor_invoice(vendor_invoice_id, self.accountant)
        )

    def read_tier(self, ticket_tier_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_ticket_tier(ticket_tier_id, self.buyer))

    def read_hold(self, ticket_hold_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_ticket_hold(ticket_hold_id, self.buyer))

    def read_settlement(self, settlement_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_settlement(settlement_id, self.accountant))

    def read_event(self, cancellation_event_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_cancellation_event(cancellation_event_id, self.buyer)
        )

    # ------------------------------------------------------------------
    # Named composite fixtures used by the heavier money cases
    # ------------------------------------------------------------------

    def big_copromote_show(self) -> Dict[str, Any]:
        """A 3000-seat co-promote show carried through to PERFORMED.

        Harbor Arena, 8.00 percent ticket tax, 350 cents per paid ticket
        facility fee, a GUARANTEE_PLUS_BACKEND deal of 5,000,000 at 85.00
        percent, GA 2000 seats repriced from 5000 to 6000 mid-run and PIT 500
        seats at 9500, 60 GA comps and 50 PIT production holds, four budget
        lines and 1800 paid tickets.
        """
        self.set_clock(DEFAULT_CLOCK)
        market = self.market(
            name="Pacific Northwest",
            region_code="PNW",
            guarantee_exposure_limit_cents=10_000_000,
        )
        artist = self.artist(
            name="Aurora Sky",
            agency="Meridian Talent",
            tier="ARENA",
            historical_sellthrough_pct=82.00,
            withholding_pct=0,
        )
        venue = self.venue(
            market["id"],
            name="Harbor Arena",
            gross_capacity=3000,
            facility_fee_cents_per_ticket=350,
            ticket_tax_pct=8.00,
        )
        show = self.show(
            artist["id"],
            venue["id"],
            event_at="2026-10-10T02:00:00.000Z",
            load_in_at="2026-10-09T14:00:00.000Z",
            load_out_at="2026-10-10T08:00:00.000Z",
            announce_at="2026-08-15T15:00:00.000Z",
            venue_arrangement="CO_PROMOTE",
            copromote_venue_share_pct=15.00,
            venue_expense_pct_production=50.00,
            venue_expense_pct_marketing=25.00,
            venue_expense_pct_staffing=100.00,
            venue_expense_pct_hospitality=0,
        )
        offer = self.accepted_offer(
            show["id"],
            artist["id"],
            expected_show_version=show["version"],
            deal_structure="GUARANTEE_PLUS_BACKEND",
            guarantee_cents=5_000_000,
            deposit_cents=1_000_000,
            expense_cap_cents=4_000_000,
            backend_split_artist_pct=85.00,
        )
        ga = self.tier(show["id"], tier_name="GA", price_cents=5_000, allocation_qty=2_000)
        pit = self.tier(show["id"], tier_name="PIT", price_cents=9_500, allocation_qty=500)
        comp_hold = self.hold(
            ga["id"], kind="COMP", qty=60, holder="artist guest list"
        )
        prod_hold = self.hold(
            pit["id"],
            kind="PRODUCTION_HOLD",
            qty=50,
            holder="front of house mix position",
        )
        lines = {
            "production": self.budget_line(
                show["id"],
                category="PRODUCTION",
                description="stage, lighting and audio package",
                budgeted_cents=1_500_000,
                is_artist_deductible=True,
            ),
            "marketing": self.budget_line(
                show["id"],
                category="MARKETING",
                description="radio and outdoor buy",
                budgeted_cents=800_000,
                is_artist_deductible=True,
            ),
            "staffing": self.budget_line(
                show["id"],
                category="STAFFING",
                description="ushers, ticket takers and security",
                budgeted_cents=600_000,
                is_artist_deductible=False,
            ),
            "hospitality": self.budget_line(
                show["id"],
                category="HOSPITALITY",
                description="catering and dressing rooms",
                budgeted_cents=200_000,
                is_artist_deductible=True,
            ),
        }
        self.set_clock("2026-08-15T15:00:00.000Z")
        get_success_data(self.api.put_show_on_sale(show["id"], self.buyer))
        self.sell(ga["id"], 800)
        self.reprice(ga["id"], show["id"], 6_000)
        self.sell(ga["id"], 600)
        self.sell(pit["id"], 400)
        self.approved_invoice(
            show["id"],
            lines["production"]["id"],
            1_650_000,
            vendor_name="Cascade Staging",
            documentation_ref="INV-PROD-0001",
        )
        self.approved_invoice(
            show["id"],
            lines["marketing"]["id"],
            900_000,
            vendor_name="Northline Media",
            documentation_ref="INV-MKT-0001",
        )
        self.approved_invoice(
            show["id"],
            lines["staffing"]["id"],
            600_000,
            vendor_name="Harbor Crowd Services",
            invoice_date="2026-10-10",
            documentation_ref="INV-STAFF-0001",
        )
        self.approved_invoice(
            show["id"],
            lines["hospitality"]["id"],
            260_000,
            vendor_name="Elliott Bay Catering",
            invoice_date="2026-10-10",
            documentation_ref="INV-HOSP-0001",
        )
        self.approve_variance(lines["marketing"]["id"], 900_000)
        self.approve_variance(lines["hospitality"]["id"], 250_000, as_risk_officer=True)
        self.set_clock("2026-10-10T06:00:00.000Z")
        get_success_data(self.api.perform_show(show["id"], self.accountant))
        return {
            "market": self.read_market(market["id"]),
            "artist": self.read_artist(artist["id"]),
            "venue": self.read_venue(venue["id"]),
            "show": self.read_show(show["id"]),
            "offer": self.read_offer(offer["id"]),
            "ga": self.read_tier(ga["id"]),
            "pit": self.read_tier(pit["id"]),
            "comp_hold": self.read_hold(comp_hold["id"]),
            "prod_hold": self.read_hold(prod_hold["id"]),
            "lines": {k: self.read_budget_line(v["id"]) for k, v in lines.items()},
        }

    def small_rental_show(self) -> Dict[str, Any]:
        """A 1200-seat rental show: 10.00 percent tax, 300 cents facility fee,
        FLAT_GUARANTEE 2,000,000 against a 500,000 rental fee, GA 1000 seats at
        5000 with 400 sold, carried through to PERFORMED.
        """
        self.set_clock(DEFAULT_CLOCK)
        market = self.market(
            name="Gulf Coast", region_code="GULF", guarantee_exposure_limit_cents=10_000_000
        )
        artist = self.artist(
            name="Rivermouth",
            agency="Delta Bookings",
            tier="THEATER",
            historical_sellthrough_pct=60.00,
            withholding_pct=0,
        )
        venue = self.venue(
            market["id"],
            name="Riverside Hall",
            gross_capacity=1_200,
            facility_fee_cents_per_ticket=300,
            ticket_tax_pct=10.00,
        )
        show = self.show(
            artist["id"],
            venue["id"],
            event_at="2026-10-10T02:00:00.000Z",
            load_in_at="2026-10-09T14:00:00.000Z",
            load_out_at="2026-10-10T08:00:00.000Z",
            announce_at="2026-08-15T15:00:00.000Z",
            venue_arrangement="RENTAL",
            rental_fee_cents=500_000,
        )
        offer = self.accepted_offer(
            show["id"],
            artist["id"],
            expected_show_version=show["version"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=2_000_000,
            deposit_cents=0,
            expense_cap_cents=4_000_000,
        )
        ga = self.tier(show["id"], tier_name="GA", price_cents=5_000, allocation_qty=1_000)
        self.set_clock("2026-08-15T15:00:00.000Z")
        get_success_data(self.api.put_show_on_sale(show["id"], self.buyer))
        self.sell(ga["id"], 400)
        self.set_clock("2026-10-10T06:00:00.000Z")
        get_success_data(self.api.perform_show(show["id"], self.accountant))
        return {
            "market": self.read_market(market["id"]),
            "artist": self.read_artist(artist["id"]),
            "venue": self.read_venue(venue["id"]),
            "show": self.read_show(show["id"]),
            "offer": self.read_offer(offer["id"]),
            "ga": self.read_tier(ga["id"]),
        }
