"""Composite setup builders and the pytest fixtures that expose them.

Storage is in-memory and the server is restarted before every test, so nothing
here may assume seeded data: every row a test needs is created through the
declared endpoints by that test's own fixtures.

The builder deliberately keeps entity-backed identity threaded through: the
headers used for a Manufacturer or Retailer call are always derived from the
row that call acts on, never from a shared constant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ClearinghouseClient
from .constants import (
    CANONICAL_EXPIRATION_DATE,
    CANONICAL_GRACE_DAYS,
    CLOCK_START_DATE,
    PREFIX_A,
    PREFIX_B,
    databar_payload,
)
from .test_users import (
    ADMIN,
    ANALYST,
    ANALYST_2,
    CLERK,
    OFFICER,
    OFFICER_2,
    make_manufacturer_headers,
    make_retailer_headers,
)
from .types import BarcodeFamily, Channel


class ClearinghouseBuilder:
    """Drives the API to assemble the composite states the tests need."""

    def __init__(self, api: ClearinghouseClient):
        self.api = api

    # -----------------------------------------------------------------
    # Clock
    # -----------------------------------------------------------------

    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(current_utc))

    # -----------------------------------------------------------------
    # Market participants
    # -----------------------------------------------------------------

    def manufacturer(self, gs1_company_prefix: str = PREFIX_A,
                     legal_name: str = "Northbrook Foods Incorporated",
                     handling_fee_policy: Optional[str] = None,
                     dispute_window_days: Optional[int] = None) -> Dict[str, Any]:
        payload = f.manufacturer_payload(
            legal_name=legal_name,
            gs1_company_prefix=gs1_company_prefix,
            handling_fee_policy=handling_fee_policy,
            dispute_window_days=dispute_window_days,
        )
        return get_success_data(self.api.create_manufacturer(payload, ADMIN))

    def retailer(self, legal_name: str = "Harborline Markets LLC",
                 channel_capability: Optional[str] = None,
                 payment_terms: Optional[str] = None,
                 base_fee_tier: Optional[str] = None,
                 fraud_scoring_mode: Optional[str] = None) -> Dict[str, Any]:
        payload = f.retailer_payload(
            legal_name=legal_name,
            channel_capability=channel_capability,
            payment_terms=payment_terms,
            base_fee_tier=base_fee_tier,
            fraud_scoring_mode=fraud_scoring_mode,
        )
        return get_success_data(self.api.create_retailer(payload, ADMIN))

    def suspend_retailer(self, retailer_id: str,
                         reason: str = "Fraud referral opened") -> Dict[str, Any]:
        return get_success_data(self.api.suspend_retailer(
            retailer_id, f.suspend_payload(reason), ADMIN))

    def reinstate_retailer(self, retailer_id: str,
                           reason: str = "Referral closed with no finding"
                           ) -> Dict[str, Any]:
        return get_success_data(self.api.reinstate_retailer(
            retailer_id, f.reinstate_payload(reason), ADMIN))

    def suspend_manufacturer(self, manufacturer_id: str,
                             reason: str = "Unfunded invoices past ninety days"
                             ) -> Dict[str, Any]:
        return get_success_data(self.api.suspend_manufacturer(
            manufacturer_id, f.suspend_payload(reason), ADMIN))

    def rescore(self, retailer_id: str,
                expected_retailer_version: Optional[int] = None) -> Dict[str, Any]:
        if expected_retailer_version is None:
            current = get_success_data(self.api.get_retailer(retailer_id, ANALYST))
            expected_retailer_version = current["version"]
        return get_success_data(self.api.fraud_rescore(
            retailer_id, expected_retailer_version, ANALYST))

    # -----------------------------------------------------------------
    # Offers
    # -----------------------------------------------------------------

    def offer(self, manufacturer_id: str, **overrides) -> Dict[str, Any]:
        payload = f.offer_payload(manufacturer_id, **overrides)
        return get_success_data(
            self.api.create_offer(payload, make_manufacturer_headers(manufacturer_id)))

    def register(self, offer: Dict[str, Any]) -> Dict[str, Any]:
        headers = make_manufacturer_headers(offer["manufacturer_id"])
        return get_success_data(self.api.register_offer(offer["id"], headers))

    def activate(self, offer_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.activate_offer(offer_id, ADMIN))

    def active_offer(self, manufacturer_id: str, **overrides) -> Dict[str, Any]:
        """Create, register and activate one offer in a single step."""
        created = self.offer(manufacturer_id, **overrides)
        self.register(created)
        return self.activate(created["id"])

    def withdraw(self, offer: Dict[str, Any],
                 withdrawn_reason: str = "Promotion pulled by brand team"
                 ) -> Dict[str, Any]:
        headers = make_manufacturer_headers(offer["manufacturer_id"])
        return get_success_data(
            self.api.withdraw_offer(offer["id"], withdrawn_reason, headers))

    # -----------------------------------------------------------------
    # Intake
    # -----------------------------------------------------------------

    def submission(self, retailer_id: str, declared_count: int,
                   postmark_window_start: str, postmark_window_end: str,
                   channel: str = Channel.MAIL) -> Dict[str, Any]:
        payload = f.submission_payload(
            retailer_id, declared_count, postmark_window_start,
            postmark_window_end, channel)
        return get_success_data(self.api.create_submission(payload, CLERK))

    def verify(self, submission_id: str, verified_count: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.verify_count(submission_id, verified_count, CLERK))

    def verified_submission(self, retailer_id: str, counted: int,
                            postmark_window_start: str = "2026-07-01",
                            postmark_window_end: str = "2026-07-31",
                            channel: str = Channel.MAIL) -> Dict[str, Any]:
        """A submission whose declared count has been recounted exactly."""
        created = self.submission(retailer_id, counted, postmark_window_start,
                                  postmark_window_end, channel)
        self.verify(created["id"], counted)
        return created

    def lot(self, submission_id: str, offer_id: str, manufacturer_id: str,
            counted_qty: int) -> Dict[str, Any]:
        payload = f.lot_payload(offer_id, manufacturer_id, counted_qty)
        return get_success_data(self.api.create_lot(submission_id, payload, CLERK))

    def capture(self, lot_id: str, items: List[Dict[str, Any]]) -> List[Dict]:
        return get_success_data(self.api.capture_items(lot_id, items, CLERK))

    def purchase_record(self, retailer_id: str, offer_id: str,
                        pos_transaction_ref: str, transaction_date: str,
                        qualifying_units: int) -> Dict[str, Any]:
        payload = f.purchase_record_payload(
            retailer_id, offer_id, pos_transaction_ref, transaction_date,
            qualifying_units)
        return get_success_data(self.api.create_purchase_record(payload, CLERK))

    def finalize(self, lot_id: str, headers: Optional[Dict] = None
                 ) -> Dict[str, Any]:
        return get_success_data(
            self.api.finalize_lot(lot_id, headers or ANALYST))

    def adjudicate(self, item_id: str, headers: Optional[Dict] = None
                   ) -> Dict[str, Any]:
        return get_success_data(
            self.api.adjudicate_item(item_id, headers or ANALYST))

    # -----------------------------------------------------------------
    # Settlement, invoicing and disputes
    # -----------------------------------------------------------------

    def issue_statement(self, submission_id: str,
                        prior_chargeback_offset_cents: Optional[int] = None,
                        headers: Optional[Dict] = None) -> Dict[str, Any]:
        """Re-read the submission for its current version, then issue."""
        officer = headers or OFFICER
        current = get_success_data(
            self.api.get_submission(submission_id, officer))
        return get_success_data(self.api.issue_statement(
            submission_id, current["version"], officer,
            prior_chargeback_offset_cents))

    def schedule(self, statement_id: str,
                 headers: Optional[Dict] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.schedule_statement(statement_id, headers or OFFICER))

    def release(self, statement_id: str,
                headers: Optional[Dict] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.release_payment(statement_id, headers or OFFICER_2))

    def invoice(self, manufacturer_id: str, billing_period_start: str,
                billing_period_end: str,
                statement_ids: List[str]) -> Dict[str, Any]:
        payload = f.invoice_payload(manufacturer_id, billing_period_start,
                                    billing_period_end, statement_ids)
        return get_success_data(self.api.create_invoice(payload, OFFICER))

    def fund(self, invoice: Dict[str, Any], amount_cents: int) -> Dict[str, Any]:
        headers = make_manufacturer_headers(invoice["manufacturer_id"])
        return get_success_data(
            self.api.fund_invoice(invoice["id"], amount_cents, headers))

    def reverse_funding(self, invoice_id: str,
                        reason: str = "Wire sent against the wrong period"
                        ) -> Dict[str, Any]:
        return get_success_data(
            self.api.reverse_funding(invoice_id, reason, ADMIN))

    def file_dispute(self, lot_id: str, retailer_id: str,
                     reason_code: str = "IMAGE_QUALITY",
                     narrative: str = "Rescan shows a clean barcode."
                     ) -> Dict[str, Any]:
        return get_success_data(self.api.file_dispute(
            lot_id, reason_code, narrative, make_retailer_headers(retailer_id)))

    def resolve_dispute(self, dispute_id: str, outcome: str,
                        resolution_note: str = "Evidence reviewed by a second analyst.",
                        headers: Optional[Dict] = None) -> Dict[str, Any]:
        return get_success_data(self.api.resolve_dispute(
            dispute_id, outcome, resolution_note, headers or ANALYST_2))

    def clip(self, offer_id: str, consumer_ref: str,
             retailer_id: Optional[str] = None) -> Dict[str, Any]:
        headers = make_retailer_headers(retailer_id) if retailer_id else ADMIN
        return get_success_data(
            self.api.create_clip(offer_id, consumer_ref, headers))

    def redemption_event(self, offer_id: str, retailer_id: str,
                         consumer_ref: str) -> Dict[str, Any]:
        return get_success_data(self.api.create_redemption_event(
            offer_id, retailer_id, consumer_ref,
            make_retailer_headers(retailer_id)))

    # -----------------------------------------------------------------
    # Higher-order composites
    # -----------------------------------------------------------------

    def market(self, gs1_company_prefix: str = PREFIX_A,
               handling_fee_policy: Optional[str] = None,
               dispute_window_days: Optional[int] = None,
               channel_capability: Optional[str] = None,
               payment_terms: Optional[str] = None,
               base_fee_tier: Optional[str] = None,
               fraud_scoring_mode: Optional[str] = None,
               **offer_overrides) -> Dict[str, Any]:
        """An issuer, a retailer and one ACTIVE canonical offer.

        Returns the three rows plus the headers each entity-backed caller must
        use, so no test has to rebuild an identity by hand.
        """
        mfr = self.manufacturer(
            gs1_company_prefix=gs1_company_prefix,
            handling_fee_policy=handling_fee_policy,
            dispute_window_days=dispute_window_days,
        )
        ret = self.retailer(
            channel_capability=channel_capability,
            payment_terms=payment_terms,
            base_fee_tier=base_fee_tier,
            fraud_scoring_mode=fraud_scoring_mode,
        )
        overrides = {
            "redemption_grace_days": CANONICAL_GRACE_DAYS,
        }
        overrides.update(offer_overrides)
        offer = self.active_offer(mfr["id"], **overrides)
        return {
            "manufacturer": mfr,
            "retailer": ret,
            "offer": offer,
            "manufacturer_id": mfr["id"],
            "retailer_id": ret["id"],
            "offer_id": offer["id"],
            "barcode": offer["barcode_payload"],
            "mfr_headers": make_manufacturer_headers(mfr["id"]),
            "ret_headers": make_retailer_headers(ret["id"]),
        }

    def clean_lot(self, world: Dict[str, Any], submission_id: str,
                  counted_qty: int = 1, pos_ref: Optional[str] = None,
                  qualifying_units: Optional[int] = None,
                  claimed_units: Optional[int] = None,
                  redeemed_at: str = "2026-07-05",
                  transaction_date: str = "2026-07-05",
                  serial_numbers: Optional[List[Optional[str]]] = None,
                  finalize: bool = False) -> Dict[str, Any]:
        """One lot whose coupons are all backed by a qualifying basket."""
        ref = pos_ref or f.unique_pos_ref()
        units = claimed_units or 1
        required = qualifying_units
        if required is None:
            required = units * max(
                1, world["offer"].get("purchase_requirement_units", 1))
        record = self.purchase_record(
            world["retailer_id"], world["offer_id"], ref, transaction_date,
            required)
        lot = self.lot(submission_id, world["offer_id"], world["manufacturer_id"],
                       counted_qty)
        items = f.item_batch(
            lot["sample_size"], world["barcode"], redeemed_at,
            pos_transaction_ref=ref, claimed_units=claimed_units,
            serial_numbers=serial_numbers)
        created = self.capture(lot["id"], items)
        result = {"lot": lot, "lot_id": lot["id"], "items": created,
                  "item_ids": [row["id"] for row in created],
                  "record": record, "record_id": record["id"],
                  "pos_ref": ref}
        if finalize:
            result["lot"] = self.finalize(lot["id"])
        return result

    def rejected_lot(self, world: Dict[str, Any], submission_id: str,
                     counted_qty: int = 1, redeemed_at: str = "2026-07-05",
                     finalize: bool = True) -> Dict[str, Any]:
        """One lot whose coupons carry a payload the offer never minted."""
        lot = self.lot(submission_id, world["offer_id"],
                       world["manufacturer_id"], counted_qty)
        counterfeit = databar_payload(
            world["manufacturer"]["gs1_company_prefix"], 40, 1,
            CANONICAL_EXPIRATION_DATE, CANONICAL_GRACE_DAYS)
        items = f.item_batch(lot["sample_size"], counterfeit, redeemed_at,
                             pos_transaction_ref=f.unique_pos_ref())
        created = self.capture(lot["id"], items)
        result = {"lot": lot, "lot_id": lot["id"], "items": created,
                  "item_ids": [row["id"] for row in created],
                  "barcode": counterfeit}
        if finalize:
            result["lot"] = self.finalize(lot["id"])
        return result

    def settled_submission(self, world: Dict[str, Any],
                           postmark_window_start: str = "2026-07-01",
                           postmark_window_end: str = "2026-07-31",
                           counted_qty: int = 1,
                           claimed_units: Optional[int] = None
                           ) -> Dict[str, Any]:
        """A CLOSED submission with exactly one validated lot."""
        submission = self.verified_submission(
            world["retailer_id"], counted_qty,
            postmark_window_start, postmark_window_end)
        lot = self.clean_lot(world, submission["id"], counted_qty=counted_qty,
                            claimed_units=claimed_units, finalize=True)
        return {"submission": submission, "submission_id": submission["id"],
                **lot}

    def scheduled_statement(self, world: Dict[str, Any],
                            postmark_window_start: str = "2026-07-01",
                            postmark_window_end: str = "2026-07-31",
                            counted_qty: int = 1,
                            claimed_units: Optional[int] = None
                            ) -> Dict[str, Any]:
        """A settled submission whose statement is on the payment calendar."""
        settled = self.settled_submission(
            world, postmark_window_start, postmark_window_end, counted_qty,
            claimed_units)
        statement = self.issue_statement(settled["submission_id"])
        scheduled = self.schedule(statement["id"])
        return {**settled, "statement": scheduled,
                "statement_id": scheduled["id"]}

    def funded_chain(self, world: Dict[str, Any],
                     billing_period_start: str = "2026-07-01",
                     billing_period_end: str = "2026-07-31",
                     counted_qty: int = 1) -> Dict[str, Any]:
        """A scheduled statement whose invoice has been funded in full."""
        chain = self.scheduled_statement(
            world, counted_qty=counted_qty)
        invoice = self.invoice(world["manufacturer_id"], billing_period_start,
                              billing_period_end, [chain["statement_id"]])
        funded = self.fund(invoice, invoice["billed_total_cents"])
        return {**chain, "invoice": funded, "invoice_id": funded["id"]}


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def api() -> ClearinghouseClient:
    """A fresh client against the server the harness just restarted."""
    return ClearinghouseClient()


@pytest.fixture
def build(api: ClearinghouseClient) -> ClearinghouseBuilder:
    """The composite setup driver."""
    return ClearinghouseBuilder(api)


@pytest.fixture
def world(build: ClearinghouseBuilder) -> Dict[str, Any]:
    """An issuer, a retailer on every default, and one ACTIVE offer."""
    return build.market()


@pytest.fixture
def preferred_world(build: ClearinghouseBuilder) -> Dict[str, Any]:
    """The same market with the retailer on the PREFERRED contractual tier."""
    return build.market(base_fee_tier="PREFERRED")


@pytest.fixture
def tiered_world(build: ClearinghouseBuilder) -> Dict[str, Any]:
    """A market whose issuer prices handling fees on the banded schedule."""
    return build.market(handling_fee_policy="TIERED_RATE")


@pytest.fixture
def digital_world(build: ClearinghouseBuilder) -> Dict[str, Any]:
    """A market whose canonical offer is enabled for digital distribution."""
    return build.market(digital_enabled=True)


@pytest.fixture
def two_manufacturer_world(build: ClearinghouseBuilder) -> Dict[str, Any]:
    """Two issuers on distinct prefixes sharing one retailer."""
    primary = build.market(gs1_company_prefix=PREFIX_A)
    second = build.manufacturer(gs1_company_prefix=PREFIX_B,
                                legal_name="Eastgate Brands Company")
    return {**primary, "manufacturer_b": second,
            "manufacturer_b_id": second["id"],
            "mfr_b_headers": make_manufacturer_headers(second["id"])}


@pytest.fixture
def settled(build: ClearinghouseBuilder, world: Dict[str, Any]) -> Dict[str, Any]:
    """One CLOSED submission carrying a single cleared coupon."""
    return {"world": world, **build.settled_submission(world)}


@pytest.fixture
def scheduled(build: ClearinghouseBuilder, world: Dict[str, Any]) -> Dict[str, Any]:
    """One statement already on the payment calendar."""
    return {"world": world, **build.scheduled_statement(world)}


@pytest.fixture
def funded(build: ClearinghouseBuilder, world: Dict[str, Any]) -> Dict[str, Any]:
    """A scheduled statement whose invoice is FUNDED in full."""
    return {"world": world, **build.funded_chain(world)}
