"""Composite setup helpers and pytest fixtures.

The PRD's interesting rules all sit several states deep — a tender can only be
processed inside an offering that is effective, whose escrow has broken, whose
class has a published valuation and whose repurchase period has closed. The
``ReitWorld`` helper below walks those chains once so that a test body contains
only the step under examination and its assertions.

Two identity rules from PRD §2.1 are threaded through every helper: a
``BrokerDealerRep`` acts with its own firm's id in ``X-User-ID`` and an
``InvestorUser`` acts with its own account's id, so ownership-gated calls take
headers built from the row that was just created rather than a shared constant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
import requests
from prd_bench_local_runner.testing import get_success_data

from . import api_errors  # noqa: F401  (registers the error/status map)
from .api_client import ApiClient
from .constants import CLOCK_BOOT_INSTANT
from .factories import (
    broker_dealer_payload,
    declaration_payload,
    investor_payload,
    liquidity_event_payload,
    nav_record_payload,
    offering_payload,
    repurchase_period_payload,
    repurchase_request_payload,
    selling_agreement_payload,
    share_class_payload,
    stockholder_vote_payload,
    subscription_payload,
)
from .test_users import (
    ADVISOR,
    BOARD,
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    make_broker_dealer_rep_headers,
    make_investor_user_headers,
)
from .types import (
    DeclarationAction,
    EscrowAction,
    Json,
    NavRecordStatus,
    RegistrationAction,
    SellingAgreementStatus,
    SubscriptionStatus,
)


class ReitWorld:
    """Drives multi-step PRD workflows and returns the rows they produce."""

    def __init__(self, api: ApiClient):
        self.api = api

    # ─── Logical clock (PRD §2.6) ─────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Optional[Dict[str, str]] = None) -> Json:
        return get_success_data(
            self.api.set_clock(current_utc, headers or TRANSFER_AGENT)
        )

    # ─── Offering and class structure (PRD §3.1) ──────────────────────

    def offering(self, **overrides: Any) -> Json:
        return get_success_data(
            self.api.create_offering(offering_payload(**overrides), SPONSOR)
        )

    def share_class(self, offering_id: str, **overrides: Any) -> Json:
        return get_success_data(
            self.api.create_share_class(
                share_class_payload(offering_id, **overrides), SPONSOR
            )
        )

    def declare_effective(self, offering_id: str) -> Json:
        return get_success_data(
            self.api.drive_registration(
                offering_id, {"action": RegistrationAction.DECLARE_EFFECTIVE}, COMPLIANCE
            )
        )

    def drive_registration(self, offering_id: str, action: str, **extra: Any) -> Json:
        payload = {"action": action}
        payload.update(extra)
        return get_success_data(
            self.api.drive_registration(offering_id, payload, COMPLIANCE)
        )

    def drive_repurchase_plan(self, offering_id: str, action: str, **extra: Any) -> Json:
        payload = {"action": action}
        payload.update(extra)
        return get_success_data(
            self.api.drive_repurchase_plan(offering_id, payload, COMPLIANCE)
        )

    # ─── Distribution channel (PRD §3.3) ──────────────────────────────

    def broker_dealer(self, **overrides: Any) -> Json:
        return get_success_data(
            self.api.create_broker_dealer(broker_dealer_payload(**overrides), COMPLIANCE)
        )

    def selling_agreement(
        self, offering_id: str, broker_dealer_id: str, **overrides: Any
    ) -> Json:
        return get_success_data(
            self.api.create_selling_agreement(
                selling_agreement_payload(offering_id, broker_dealer_id, **overrides),
                COMPLIANCE,
            )
        )

    def activate_agreement(self, selling_agreement_id: str) -> Json:
        return get_success_data(
            self.api.set_selling_agreement_status(
                selling_agreement_id, {"to_status": SellingAgreementStatus.ACTIVE}, COMPLIANCE
            )
        )

    def set_agreement_status(self, selling_agreement_id: str, to_status: str, **extra: Any) -> Json:
        payload = {"to_status": to_status}
        payload.update(extra)
        return get_success_data(
            self.api.set_selling_agreement_status(selling_agreement_id, payload, COMPLIANCE)
        )

    def record_finding(
        self, selling_agreement_id: str, action: str, severity: str, **extra: Any
    ) -> Json:
        payload = {"action": action, "severity": severity}
        payload.update(extra)
        return get_success_data(
            self.api.record_supervision_finding(selling_agreement_id, payload, COMPLIANCE)
        )

    def set_supervision_status(self, broker_dealer_id: str, to_status: str, **extra: Any) -> Json:
        payload = {"to_status": to_status}
        payload.update(extra)
        return get_success_data(
            self.api.set_supervision_status(broker_dealer_id, payload, COMPLIANCE)
        )

    # ─── Stockholders (PRD §3.2) ──────────────────────────────────────

    def investor(self, **overrides: Any) -> Json:
        return get_success_data(
            self.api.create_investor(investor_payload(**overrides), SPONSOR)
        )

    def document_suitability(
        self,
        investor_id: str,
        documentation_reference: str = "SUIT-2026-08",
        headers: Optional[Dict[str, str]] = None,
    ) -> Json:
        return get_success_data(
            self.api.record_suitability_documentation(
                investor_id,
                {"documentation_reference": documentation_reference},
                headers or COMPLIANCE,
            )
        )

    def documented_investor(self, **overrides: Any) -> Json:
        """An investor whose suitability file is DOCUMENTED (PRD §3.2)."""
        investor = self.investor(**overrides)
        self.document_suitability(investor["id"], f"SUIT-{investor['id'][:8]}")
        return get_success_data(self.api.get_investor(investor["id"], SPONSOR))

    def statement(self, investor_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
        return get_success_data(
            self.api.get_investor_statement(investor_id, headers or TRANSFER_AGENT)
        )

    # ─── Subscriptions, escrow and lots (PRD §3.4, §3.5) ──────────────

    def subscription(
        self,
        offering_id: str,
        share_class_id: str,
        investor_id: str,
        selling_agreement_id: str,
        gross_investment_cents: int,
        headers: Optional[Dict[str, str]] = None,
    ) -> Json:
        return get_success_data(
            self.api.create_subscription(
                subscription_payload(
                    offering_id,
                    share_class_id,
                    investor_id,
                    selling_agreement_id,
                    gross_investment_cents=gross_investment_cents,
                ),
                headers or SPONSOR,
            )
        )

    def escrow_subscription(self, subscription_id: str) -> Json:
        return get_success_data(
            self.api.set_subscription_status(
                subscription_id, {"to_status": SubscriptionStatus.ESCROWED}, TRANSFER_AGENT
            )
        )

    def accept_subscription(self, subscription_id: str) -> Json:
        return get_success_data(
            self.api.set_subscription_status(
                subscription_id, {"to_status": SubscriptionStatus.ACCEPTED}, SPONSOR
            )
        )

    def break_escrow(self, offering_id: str) -> Json:
        return get_success_data(
            self.api.drive_escrow(offering_id, {"action": EscrowAction.BREAK}, COMPLIANCE)
        )

    def fail_escrow(self, offering_id: str) -> Json:
        return get_success_data(
            self.api.drive_escrow(offering_id, {"action": EscrowAction.FAIL}, COMPLIANCE)
        )

    def lots(self, **filters: Any) -> List[Json]:
        return get_success_data(self.api.list_share_lots(filters, TRANSFER_AGENT))

    def lot_of_subscription(self, subscription_id: str) -> Json:
        rows = self.lots(subscription_id=subscription_id)
        assert rows, f"no lot was minted for subscription {subscription_id}"
        return rows[0]

    # ─── Valuation (PRD §3.6) ─────────────────────────────────────────

    def share_class_version(self, share_class_id: str) -> int:
        return get_success_data(self.api.get_share_class(share_class_id, SPONSOR))["version"]

    def offering_version(self, offering_id: str) -> int:
        return get_success_data(self.api.get_offering(offering_id, SPONSOR))["version"]

    def nav_record(
        self,
        share_class_id: str,
        period_start_date: str,
        period_end_date: str,
        gross_asset_value_cents: int,
        other_liabilities_cents: int = 0,
        expected_share_class_version: Optional[int] = None,
    ) -> Json:
        version = (
            expected_share_class_version
            if expected_share_class_version is not None
            else self.share_class_version(share_class_id)
        )
        return get_success_data(
            self.api.create_nav_record(
                nav_record_payload(
                    share_class_id,
                    version,
                    period_start_date=period_start_date,
                    period_end_date=period_end_date,
                    gross_asset_value_cents=gross_asset_value_cents,
                    other_liabilities_cents=other_liabilities_cents,
                ),
                SPONSOR,
            )
        )

    def submit_nav_for_review(self, nav_record_id: str) -> Json:
        return get_success_data(
            self.api.set_nav_record_status(
                nav_record_id, {"to_status": NavRecordStatus.ADVISOR_REVIEW}, SPONSOR
            )
        )

    def confirm_nav(
        self, nav_record_id: str, advisor_opinion_reference: Optional[str] = None
    ) -> Json:
        payload: Json = {"to_status": NavRecordStatus.ADVISOR_CONFIRMED}
        if advisor_opinion_reference is not None:
            payload["advisor_opinion_reference"] = advisor_opinion_reference
        return get_success_data(self.api.set_nav_record_status(nav_record_id, payload, ADVISOR))

    def publish_nav_record(self, nav_record_id: str) -> Json:
        return get_success_data(
            self.api.set_nav_record_status(
                nav_record_id, {"to_status": NavRecordStatus.PUBLISHED}, SPONSOR
            )
        )

    def published_nav(
        self,
        share_class_id: str,
        period_start_date: str,
        period_end_date: str,
        gross_asset_value_cents: int,
        other_liabilities_cents: int = 0,
        advisor_opinion_reference: Optional[str] = None,
    ) -> Json:
        """Walk DRAFT → ADVISOR_REVIEW → ADVISOR_CONFIRMED → PUBLISHED (PRD §3.6)."""
        record = self.nav_record(
            share_class_id,
            period_start_date,
            period_end_date,
            gross_asset_value_cents,
            other_liabilities_cents,
        )
        self.submit_nav_for_review(record["id"])
        self.confirm_nav(record["id"], advisor_opinion_reference)
        return self.publish_nav_record(record["id"])

    # ─── Declarations (PRD §3.7) ──────────────────────────────────────

    def declaration(
        self, offering_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
    ) -> Json:
        version = overrides.pop(
            "expected_offering_version", self.offering_version(offering_id)
        )
        return get_success_data(
            self.api.create_distribution_declaration(
                declaration_payload(offering_id, version, **overrides), headers or SPONSOR
            )
        )

    def pay_declaration(self, declaration_id: str) -> Json:
        return get_success_data(
            self.api.drive_declaration_payment(
                declaration_id, {"action": DeclarationAction.PAY}, TRANSFER_AGENT
            )
        )

    def cancel_declaration(self, declaration_id: str) -> Json:
        return get_success_data(
            self.api.drive_declaration_payment(
                declaration_id, {"action": DeclarationAction.CANCEL}, BOARD
            )
        )

    # ─── Repurchase plan (PRD §3.8) ───────────────────────────────────

    def repurchase_period(self, offering_id: str, **overrides: Any) -> Json:
        return get_success_data(
            self.api.create_repurchase_period(
                repurchase_period_payload(offering_id, **overrides), TRANSFER_AGENT
            )
        )

    def tender(
        self,
        repurchase_period_id: str,
        share_class_id: str,
        shares_requested_e4: int,
        investor_id: str,
        **overrides: Any,
    ) -> Json:
        return get_success_data(
            self.api.create_repurchase_request(
                repurchase_request_payload(
                    repurchase_period_id, share_class_id, shares_requested_e4, **overrides
                ),
                make_investor_user_headers(investor_id),
            )
        )

    def process_period(self, repurchase_period_id: str) -> Json:
        return get_success_data(
            self.api.process_repurchase_period(repurchase_period_id, None, TRANSFER_AGENT)
        )

    # ─── Liquidity events and ballots (PRD §3.9) ──────────────────────

    def liquidity_event(self, offering_id: str, **overrides: Any) -> Json:
        return get_success_data(
            self.api.create_liquidity_event(
                liquidity_event_payload(offering_id, **overrides), SPONSOR
            )
        )

    def drive_liquidity_event(
        self, liquidity_event_id: str, action: str, headers: Optional[Dict[str, str]] = None,
        **extra: Any,
    ) -> Json:
        payload = {"action": action}
        payload.update(extra)
        return get_success_data(
            self.api.drive_liquidity_event(liquidity_event_id, payload, headers or SPONSOR)
        )

    def cast_vote(self, liquidity_event_id: str, investor_id: str, **overrides: Any) -> Json:
        return get_success_data(
            self.api.cast_stockholder_vote(
                stockholder_vote_payload(liquidity_event_id, **overrides),
                make_investor_user_headers(investor_id),
            )
        )

    # ─── Reads ────────────────────────────────────────────────────────

    def read_offering(self, offering_id: str) -> Json:
        return get_success_data(self.api.get_offering(offering_id, SPONSOR))

    def read_share_class(self, share_class_id: str) -> Json:
        return get_success_data(self.api.get_share_class(share_class_id, SPONSOR))

    def read_investor(self, investor_id: str) -> Json:
        return get_success_data(self.api.get_investor(investor_id, SPONSOR))

    def read_broker_dealer(self, broker_dealer_id: str) -> Json:
        return get_success_data(self.api.get_broker_dealer(broker_dealer_id, COMPLIANCE))

    def read_agreement(self, selling_agreement_id: str) -> Json:
        return get_success_data(
            self.api.get_selling_agreement(selling_agreement_id, COMPLIANCE)
        )

    def read_subscription(self, subscription_id: str) -> Json:
        return get_success_data(self.api.get_subscription(subscription_id, SPONSOR))

    def read_lot(self, share_lot_id: str) -> Json:
        return get_success_data(self.api.get_share_lot(share_lot_id, TRANSFER_AGENT))

    def read_nav_record(self, nav_record_id: str) -> Json:
        return get_success_data(self.api.get_nav_record(nav_record_id, SPONSOR))

    def read_declaration(self, declaration_id: str) -> Json:
        return get_success_data(
            self.api.get_distribution_declaration(declaration_id, SPONSOR)
        )

    def read_period(self, repurchase_period_id: str) -> Json:
        return get_success_data(
            self.api.get_repurchase_period(repurchase_period_id, TRANSFER_AGENT)
        )

    def read_request(self, repurchase_request_id: str) -> Json:
        return get_success_data(
            self.api.get_repurchase_request(repurchase_request_id, TRANSFER_AGENT)
        )

    def read_liquidity_event(self, liquidity_event_id: str) -> Json:
        return get_success_data(self.api.get_liquidity_event(liquidity_event_id, SPONSOR))

    # ─── Composite chains ─────────────────────────────────────────────

    def effective_offering(
        self,
        offering: Optional[Dict[str, Any]] = None,
        share_class: Optional[Dict[str, Any]] = None,
        agreement: Optional[Dict[str, Any]] = None,
        activate_agreement: bool = True,
    ) -> Json:
        """Offering EFFECTIVE with one class, one firm and an ACTIVE agreement.

        PRD §3.3 requires the covered offering to be EFFECTIVE before an
        agreement may be activated, so the registration is driven first.
        """
        off = self.offering(**(offering or {}))
        cls = self.share_class(off["id"], **(share_class or {}))
        firm = self.broker_dealer()
        self.declare_effective(off["id"])
        sa = self.selling_agreement(off["id"], firm["id"], **(agreement or {}))
        if activate_agreement:
            self.activate_agreement(sa["id"])
        return {
            "offering": self.read_offering(off["id"]),
            "share_class": self.read_share_class(cls["id"]),
            "broker_dealer": firm,
            "selling_agreement": self.read_agreement(sa["id"]),
            "offering_id": off["id"],
            "share_class_id": cls["id"],
            "broker_dealer_id": firm["id"],
            "selling_agreement_id": sa["id"],
        }

    def escrowed_subscription(
        self,
        world: Json,
        gross_investment_cents: int,
        investor: Optional[Json] = None,
        share_class_id: Optional[str] = None,
    ) -> Json:
        """A documented stockholder with money sitting in escrow (PRD §3.5)."""
        holder = investor or self.documented_investor()
        sub = self.subscription(
            world["offering_id"],
            share_class_id or world["share_class_id"],
            holder["id"],
            world["selling_agreement_id"],
            gross_investment_cents,
        )
        self.escrow_subscription(sub["id"])
        return {"investor": holder, "subscription": sub}

    def broken_escrow_offering(
        self,
        gross_investment_cents: int = 30000000,
        offering: Optional[Dict[str, Any]] = None,
        share_class: Optional[Dict[str, Any]] = None,
        agreement: Optional[Dict[str, Any]] = None,
    ) -> Json:
        """One stockholder funded and escrow broken, so a lot exists (PRD §3.5)."""
        world = self.effective_offering(offering, share_class, agreement)
        seeded = self.escrowed_subscription(world, gross_investment_cents)
        world["escrow_break"] = self.break_escrow(world["offering_id"])
        world["investor"] = self.read_investor(seeded["investor"]["id"])
        world["investor_id"] = seeded["investor"]["id"]
        world["subscription"] = self.read_subscription(seeded["subscription"]["id"])
        world["subscription_id"] = seeded["subscription"]["id"]
        world["lot"] = self.lot_of_subscription(seeded["subscription"]["id"])
        world["offering"] = self.read_offering(world["offering_id"])
        world["share_class"] = self.read_share_class(world["share_class_id"])
        return world

    def priced_offering(
        self,
        gross_investment_cents: int = 30000000,
        period_start_date: str = "2026-07-01",
        period_end_date: str = "2026-07-31",
        gross_asset_value_cents: Optional[int] = None,
        offering: Optional[Dict[str, Any]] = None,
        share_class: Optional[Dict[str, Any]] = None,
        agreement: Optional[Dict[str, Any]] = None,
    ) -> Json:
        """Broken escrow plus a PUBLISHED valuation for the class (PRD §3.6)."""
        world = self.broken_escrow_offering(
            gross_investment_cents, offering, share_class, agreement
        )
        gav = (
            gross_asset_value_cents
            if gross_asset_value_cents is not None
            else world["offering"]["gross_proceeds_cents"]
        )
        world["nav_record"] = self.published_nav(
            world["share_class_id"], period_start_date, period_end_date, gav
        )
        world["offering"] = self.read_offering(world["offering_id"])
        world["share_class"] = self.read_share_class(world["share_class_id"])
        return world

    def approved_liquidity_event(
        self, world: Json, investor_ids: List[str], **event_overrides: Any
    ) -> Json:
        """Board-approve, open the vote, collect FOR ballots and close it."""
        event = self.liquidity_event(world["offering_id"], **event_overrides)
        self.drive_liquidity_event(event["id"], "BOARD_APPROVE", BOARD)
        self.drive_liquidity_event(event["id"], "OPEN_VOTE", SPONSOR)
        for investor_id in investor_ids:
            self.cast_vote(event["id"], investor_id)
        return self.drive_liquidity_event(event["id"], "CLOSE_VOTE", SPONSOR)


# ─── pytest fixtures ──────────────────────────────────────────────────


@pytest.fixture
def api() -> ApiClient:
    """HTTP client bound to the running service."""
    return ApiClient()


@pytest.fixture
def world(api: ApiClient) -> ReitWorld:
    """Workflow driver over a freshly booted, empty service."""
    return ReitWorld(api)


@pytest.fixture
def boot_clock() -> str:
    """PRD §2.6: at boot the logical clock reads 2026-08-01T00:00:00Z."""
    return CLOCK_BOOT_INSTANT


@pytest.fixture
def effective_offering(world: ReitWorld) -> Json:
    """An EFFECTIVE offering with one zero-load class I and an ACTIVE agreement."""
    return world.effective_offering()


@pytest.fixture
def broken_escrow_offering(world: ReitWorld) -> Json:
    """An offering whose escrow has broken on a single 30,000,000-cent ticket."""
    return world.broken_escrow_offering()


@pytest.fixture
def priced_offering(world: ReitWorld) -> Json:
    """A funded offering whose class carries a PUBLISHED valuation."""
    return world.priced_offering()


__all__ = [
    "ReitWorld",
    "api",
    "world",
    "boot_clock",
    "effective_offering",
    "broken_escrow_offering",
    "priced_offering",
    "make_broker_dealer_rep_headers",
    "make_investor_user_headers",
    "requests",
]
