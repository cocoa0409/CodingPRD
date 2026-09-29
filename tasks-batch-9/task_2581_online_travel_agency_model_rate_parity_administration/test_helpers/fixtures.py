"""Precondition builders.

Every test starts against an empty database, so each scenario is assembled from
scratch here. :class:`Builder` wraps the client, drives one workflow step per
method, asserts the step succeeded and hands back the stored row, so a test body
contains only the step under test plus its assertions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    BOOKING_AGENT,
    COMMERCIAL_MANAGER,
    COMPLIANCE_OFFICER,
    PARITY_ANALYST,
    PLATFORM_ADMIN,
    supplier_user_headers,
)
from .types import Ctx, Headers, Json

DEFAULT_INSTANT = "2026-08-05T00:00:00Z"
DEFAULT_TRAVEL_DATE = "2026-09-20"
DEFAULT_PERIOD = ("2026-08-01", "2026-09-30")


class Builder:
    """Drives the API to assemble scenario preconditions."""

    def __init__(self, client: ApiClient) -> None:
        self.client = client

    # ------------------------------------------------------------------- plumbing
    @staticmethod
    def _created(response) -> Json:
        return validate_success(response, expected_status=201)

    @staticmethod
    def _ok(response) -> Json:
        return validate_success(response, expected_status=200)

    # ---------------------------------------------------------------------- clock
    def set_clock(self, instant: str = DEFAULT_INSTANT) -> Json:
        return self._ok(
            self.client.set_clock({"current_utc": instant}, PLATFORM_ADMIN)
        )

    # -------------------------------------------------------------------- markets
    def market(self, **overrides: Any) -> Json:
        return self._created(
            self.client.create_market(f.market_payload(**overrides), PLATFORM_ADMIN)
        )

    # ------------------------------------------------------------------ suppliers
    def supplier(self, market_id: str, **overrides: Any) -> Json:
        return self._created(
            self.client.create_supplier(
                f.supplier_payload(market_id, **overrides), PLATFORM_ADMIN
            )
        )

    def read_supplier(self, supplier_id: str) -> Json:
        return self._ok(self.client.get_supplier(supplier_id, PLATFORM_ADMIN))

    # ------------------------------------------------------------- certifications
    def submit_certification(self, supplier_id: str, **overrides: Any) -> Json:
        return self._created(
            self.client.create_certification(
                supplier_id, f.certification_payload(**overrides), COMMERCIAL_MANAGER
            )
        )

    def certify(
        self,
        supplier_id: str,
        decision: str = "CERTIFY",
        content_score: int = 88,
        connectivity_score: int = 91,
        **submit_overrides: Any,
    ) -> Json:
        """Submit, open review and adjudicate in one step."""
        cert = self.submit_certification(supplier_id, **submit_overrides)
        self._ok(
            self.client.start_certification_review(
                cert["id"], {}, COMPLIANCE_OFFICER
            )
        )
        return self._ok(
            self.client.decide_certification(
                cert["id"],
                f.certification_decision_payload(
                    decision=decision,
                    content_score=content_score,
                    connectivity_score=connectivity_score,
                ),
                COMPLIANCE_OFFICER,
            )
        )

    # ------------------------------------------------------------ model agreements
    def draft_agreement(
        self, supplier_id: str, model: str = "AGENCY", **overrides: Any
    ) -> Json:
        payload = (
            f.agency_agreement_payload(**overrides)
            if model == "AGENCY"
            else f.merchant_agreement_payload(**overrides)
        )
        return self._created(
            self.client.create_model_agreement(
                supplier_id, payload, COMMERCIAL_MANAGER
            )
        )

    def activate_agreement(self, agreement_id: str, headers: Headers = None) -> Json:
        return self._ok(
            self.client.activate_model_agreement(
                agreement_id, {}, headers or COMPLIANCE_OFFICER
            )
        )

    def agreement(
        self, supplier_id: str, model: str = "AGENCY", activate: bool = True, **overrides: Any
    ) -> Json:
        row = self.draft_agreement(supplier_id, model=model, **overrides)
        if activate:
            row = self.activate_agreement(row["id"])
        return row

    # ------------------------------------------------------- commission overrides
    def override(
        self, supplier_id: str, approve: bool = True, **overrides: Any
    ) -> Json:
        row = self._created(
            self.client.create_commission_override(
                f.override_payload(supplier_id, **overrides), COMMERCIAL_MANAGER
            )
        )
        if approve:
            row = self._ok(
                self.client.approve_commission_override(
                    row["id"], {}, COMPLIANCE_OFFICER
                )
            )
        return row

    # ----------------------------------------------------------------- rate plans
    def rate_plan(self, supplier_id: str, market_id: str, **overrides: Any) -> Json:
        return self._created(
            self.client.create_rate_plan(
                supplier_id, f.rate_plan_payload(market_id, **overrides), COMMERCIAL_MANAGER
            )
        )

    def read_rate_plan(self, plan_id: str) -> Json:
        return self._ok(self.client.get_rate_plan(plan_id, PLATFORM_ADMIN))

    def plan_version(self, plan_id: str) -> int:
        return self.read_rate_plan(plan_id)["version"]

    # --------------------------------------------------------------------- offers
    def offer(
        self,
        plan_id: str,
        travel_date: str = DEFAULT_TRAVEL_DATE,
        net_rate_cents: int = 24000,
        expected_rate_plan_version: Optional[int] = None,
        **overrides: Any,
    ) -> Json:
        version = (
            self.plan_version(plan_id)
            if expected_rate_plan_version is None
            else expected_rate_plan_version
        )
        return self._created(
            self.client.create_offer(
                plan_id,
                f.offer_payload(travel_date, net_rate_cents, version, **overrides),
                COMMERCIAL_MANAGER,
            )
        )

    def publish_offer(self, offer_id: str) -> Json:
        return self._ok(
            self.client.publish_offer(offer_id, {}, COMMERCIAL_MANAGER)
        )

    def live_offer(self, plan_id: str, **overrides: Any) -> Json:
        row = self.offer(plan_id, **overrides)
        return self.publish_offer(row["id"])

    def read_offer(self, offer_id: str) -> Json:
        return self._ok(self.client.get_offer(offer_id, PLATFORM_ADMIN))

    def suppress_offer(self, offer_id: str, reason: str = "MANUAL_REVIEW") -> Json:
        return self._ok(
            self.client.suppress_offer(
                offer_id, {"suppression_reason": reason}, PARITY_ANALYST
            )
        )

    # ---------------------------------------------------------- parity observations
    def observation(
        self,
        plan_id: str,
        travel_date: str = DEFAULT_TRAVEL_DATE,
        direct_total_cents: int = 24000,
        **overrides: Any,
    ) -> Json:
        return self._created(
            self.client.create_parity_observation(
                plan_id,
                f.observation_payload(travel_date, direct_total_cents, **overrides),
                PARITY_ANALYST,
            )
        )

    def read_parity_case(self, case_id: str) -> Json:
        return self._ok(self.client.get_parity_case(case_id, PLATFORM_ADMIN))

    def notify_parity(self, case_id: str) -> Json:
        return self._ok(
            self.client.notify_parity_supplier(case_id, {}, PARITY_ANALYST)
        )

    def respond_parity(
        self, case_id: str, supplier_id: str, code: str = "DISPUTED"
    ) -> Json:
        return self._ok(
            self.client.respond_parity_case(
                case_id,
                {"supplier_response_code": code},
                supplier_user_headers(supplier_id),
            )
        )

    def escalate_parity(self, case_id: str, reason: str = "No correction made.") -> Json:
        return self._ok(
            self.client.escalate_parity_case(
                case_id, {"escalation_reason": reason}, PARITY_ANALYST
            )
        )

    def close_parity(self, case_id: str, outcome: str = "COMPLIANT") -> Json:
        headers = COMPLIANCE_OFFICER if outcome == "WAIVED" else PARITY_ANALYST
        return self._ok(
            self.client.close_parity_case(case_id, {"outcome": outcome}, headers)
        )

    # --------------------------------------------------------------- placement deals
    def placement(
        self, supplier_id: str, market_id: str, approve: bool = True, **overrides: Any
    ) -> Json:
        row = self._created(
            self.client.create_placement_agreement(
                f.placement_payload(supplier_id, market_id, **overrides),
                COMMERCIAL_MANAGER,
            )
        )
        if approve:
            row = self._ok(
                self.client.approve_placement_agreement(row["id"], {}, PLATFORM_ADMIN)
            )
        return row

    # ---------------------------------------------------------------- ranking runs
    def ranking_run(
        self, market_id: str, travel_date: str = DEFAULT_TRAVEL_DATE, **overrides: Any
    ) -> Json:
        return self._created(
            self.client.create_ranking_run(
                f.ranking_run_payload(market_id, travel_date, **overrides),
                COMMERCIAL_MANAGER,
            )
        )

    def publish_ranking_run(self, run_id: str) -> Json:
        return self._ok(
            self.client.publish_ranking_run(run_id, {}, COMPLIANCE_OFFICER)
        )

    def read_ranking_run(self, run_id: str) -> Json:
        return self._ok(self.client.get_ranking_run(run_id, PLATFORM_ADMIN))

    def ranking_entries(self, run_id: str) -> List[Json]:
        data, _meta = validate_paginated(
            self.client.list_ranking_entries(
                PLATFORM_ADMIN, params={"ranking_run_id": run_id, "limit": 100}
            )
        )
        return data

    # -------------------------------------------------------------------- packages
    def package(
        self, market_id: str, travel_date: str = DEFAULT_TRAVEL_DATE, **overrides: Any
    ) -> Json:
        return self._created(
            self.client.create_package(
                f.package_payload(market_id, travel_date, **overrides),
                COMMERCIAL_MANAGER,
            )
        )

    def component(self, package_id: str, offer_id: str, component_type: str) -> Json:
        return self._created(
            self.client.create_package_component(
                package_id,
                f.component_payload(offer_id, component_type),
                COMMERCIAL_MANAGER,
            )
        )

    def read_package(self, package_id: str) -> Json:
        return self._ok(self.client.get_package(package_id, PLATFORM_ADMIN))

    def price_package(
        self, package_id: str, expected_package_version: Optional[int] = None
    ) -> Json:
        version = (
            self.read_package(package_id)["version"]
            if expected_package_version is None
            else expected_package_version
        )
        return self._ok(
            self.client.price_package(
                package_id,
                {"expected_package_version": version},
                COMMERCIAL_MANAGER,
            )
        )

    def publish_package(self, package_id: str, **overrides: Any) -> Json:
        payload: Dict[str, Any] = {"reveal_supplier_names": False}
        payload.update(overrides)
        return self._ok(
            self.client.publish_package(package_id, payload, COMMERCIAL_MANAGER)
        )

    def read_component(self, component_id: str) -> Json:
        return self._ok(
            self.client.get_package_component(component_id, PLATFORM_ADMIN)
        )

    def components_of(self, package_id: str) -> List[Json]:
        data, _meta = validate_paginated(
            self.client.list_package_components(
                PLATFORM_ADMIN, params={"package_id": package_id, "limit": 100}
            )
        )
        return data

    # -------------------------------------------------------------------- bookings
    def booking(
        self,
        *,
        offer: Optional[Json] = None,
        package: Optional[Json] = None,
        quoted_total_cents: Optional[int] = None,
        **overrides: Any,
    ) -> Json:
        if offer is not None:
            total = (
                offer["display_total_cents"]
                if quoted_total_cents is None
                else quoted_total_cents
            )
            payload = f.booking_payload(total, offer_id=offer["id"], **overrides)
        else:
            assert package is not None
            total = (
                package["package_total_cents"]
                if quoted_total_cents is None
                else quoted_total_cents
            )
            payload = f.booking_payload(total, package_id=package["id"], **overrides)
        return self._created(self.client.create_booking(payload, BOOKING_AGENT))

    def read_booking(self, booking_id: str) -> Json:
        return self._ok(self.client.get_booking(booking_id, PLATFORM_ADMIN))

    def capture(self, booking_id: str) -> Json:
        return self._ok(self.client.capture_booking(booking_id, {}, BOOKING_AGENT))

    def confirm(self, booking_id: str, supplier_id: str) -> Json:
        return self._ok(
            self.client.confirm_booking(
                booking_id,
                {"supplier_confirmation_code": "CONF-0001"},
                supplier_user_headers(supplier_id),
            )
        )

    def cancel(self, booking_id: str, reason: str = "Traveller changed plans.") -> Json:
        return self._ok(
            self.client.cancel_booking(
                booking_id, {"cancellation_reason": reason}, BOOKING_AGENT
            )
        )

    def complete(self, booking_id: str, supplier_id: str) -> Json:
        return self._ok(
            self.client.complete_booking(
                booking_id, {}, supplier_user_headers(supplier_id)
            )
        )

    def chargeback(self, booking_id: str, reason_code: str = "FRAUDULENT") -> Json:
        return self._ok(
            self.client.simulate_chargeback(
                {"booking_id": booking_id, "reason_code": reason_code}, PLATFORM_ADMIN
            )
        )

    # -------------------------------------------------------------------- disputes
    def dispute(
        self,
        booking_id: str,
        dispute_type: str = "REFUND_PASSTHROUGH",
        claim_cents: int = 1000,
        headers: Headers = None,
        **overrides: Any,
    ) -> Json:
        return self._created(
            self.client.create_dispute_case(
                booking_id,
                f.dispute_payload(dispute_type, claim_cents, **overrides),
                headers or BOOKING_AGENT,
            )
        )

    def read_dispute(self, dispute_id: str) -> Json:
        return self._ok(self.client.get_dispute_case(dispute_id, PLATFORM_ADMIN))

    def resolve_dispute(self, dispute_id: str, outcome: str = "SPLIT") -> Json:
        return self._ok(
            self.client.resolve_dispute_case(
                dispute_id, {"outcome": outcome}, COMPLIANCE_OFFICER
            )
        )

    # ------------------------------------------------------------------ scorecards
    def scorecard(
        self,
        supplier_id: str,
        period_start: str = DEFAULT_PERIOD[0],
        period_end: str = DEFAULT_PERIOD[1],
        **overrides: Any,
    ) -> Json:
        return self._created(
            self.client.create_scorecard(
                supplier_id,
                f.scorecard_payload(period_start, period_end, **overrides),
                COMMERCIAL_MANAGER,
            )
        )

    def finalize_scorecard(self, scorecard_id: str) -> Json:
        return self._ok(
            self.client.finalize_scorecard(scorecard_id, {}, COMPLIANCE_OFFICER)
        )


# ============================================================ composite scenarios
def certified_hotel(
    b: Builder,
    *,
    instant: str = DEFAULT_INSTANT,
    decision: str = "CERTIFY",
    content_score: int = 88,
    connectivity_score: int = 91,
    market: Optional[Json] = None,
    **supplier_overrides: Any,
) -> Ctx:
    """A market plus a certified HOTEL supplier at a known logical instant."""
    if instant:
        b.set_clock(instant)
    mkt = market if market is not None else b.market()
    sup = b.supplier(mkt["id"], supplier_type="HOTEL", **supplier_overrides)
    cert = b.certify(
        sup["id"],
        decision=decision,
        content_score=content_score,
        connectivity_score=connectivity_score,
    )
    return Ctx(market=mkt, supplier=b.read_supplier(sup["id"]), certification=cert)


def certified_air(
    b: Builder,
    market: Json,
    *,
    content_score: int = 88,
    connectivity_score: int = 91,
    **supplier_overrides: Any,
) -> Ctx:
    """A certified AIR supplier inside an existing market."""
    sup = b.supplier(market["id"], supplier_type="AIR", **supplier_overrides)
    cert = b.certify(
        sup["id"], content_score=content_score, connectivity_score=connectivity_score
    )
    return Ctx(supplier=b.read_supplier(sup["id"]), certification=cert)


def hotel_agency_offer(
    b: Builder,
    *,
    instant: str = DEFAULT_INSTANT,
    travel_date: str = DEFAULT_TRAVEL_DATE,
    net_rate_cents: int = 24000,
    tax_fee_pct: float = 0.01,
    publish: bool = True,
    market: Optional[Json] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    offer_overrides: Optional[Dict[str, Any]] = None,
) -> Ctx:
    """Certified hotel supplier under an ACTIVE AGENCY agreement with one offer.

    With ``publish`` the offer is driven to LIVE; the default money shape at
    ``net_rate_cents`` 24000 and ``tax_fee_pct`` 0.01 is a 24240-cent display total.
    """
    ctx = certified_hotel(b, instant=instant, market=market)
    ctx["agreement"] = b.agreement(
        ctx.supplier["id"], model="AGENCY", **(agreement_overrides or {})
    )
    ctx["rate_plan"] = b.rate_plan(
        ctx.supplier["id"],
        ctx.market["id"],
        tax_fee_pct=tax_fee_pct,
        **(plan_overrides or {}),
    )
    offer = b.offer(
        ctx.rate_plan["id"],
        travel_date=travel_date,
        net_rate_cents=net_rate_cents,
        **(offer_overrides or {}),
    )
    if publish:
        offer = b.publish_offer(offer["id"])
    ctx["offer"] = offer
    ctx["travel_date"] = travel_date
    return ctx


def air_merchant_offer(
    b: Builder,
    ctx: Ctx,
    *,
    travel_date: Optional[str] = None,
    net_rate_cents: int = 119936,
    base_markup_pct: float = 0.12,
    tax_fee_pct: float = 0.05,
    publish: bool = True,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
) -> Ctx:
    """Adds a certified AIR supplier on a MERCHANT agreement with one offer.

    The default money shape grosses 119936 up at a 0.12 markup to 136291 cents and
    lands a 143106-cent display total at a 0.05 tax rate.
    """
    date = travel_date or ctx.get("travel_date", DEFAULT_TRAVEL_DATE)
    air = certified_air(b, ctx.market)
    ctx["air_supplier"] = air.supplier
    ctx["air_certification"] = air.certification
    ctx["air_agreement"] = b.agreement(
        air.supplier["id"],
        model="MERCHANT",
        base_markup_pct=base_markup_pct,
        **(agreement_overrides or {}),
    )
    ctx["air_rate_plan"] = b.rate_plan(
        air.supplier["id"],
        ctx.market["id"],
        cancellation_policy_code="MODERATE",
        free_cancel_cutoff_hours=72,
        tax_fee_pct=tax_fee_pct,
        parity_monitored=False,
        **(plan_overrides or {}),
    )
    offer = b.offer(
        ctx.air_rate_plan["id"], travel_date=date, net_rate_cents=net_rate_cents
    )
    if publish:
        offer = b.publish_offer(offer["id"])
    ctx["air_offer"] = offer
    return ctx


def two_leg_package(
    b: Builder,
    *,
    instant: str = DEFAULT_INSTANT,
    travel_date: str = DEFAULT_TRAVEL_DATE,
    hotel_net_rate_cents: int = 24000,
    hotel_tax_fee_pct: float = 0.01,
    air_net_rate_cents: int = 119936,
    air_tax_fee_pct: float = 0.05,
    air_markup_pct: float = 0.12,
    price: bool = False,
    publish: bool = False,
) -> Ctx:
    """An opaque package with a HOTEL leg attached before an AIR leg.

    The hotel offer is created first, so it is also first in the ascending
    offer-``created_at`` order that component processing and remainder tie-breaks
    both read.
    """
    ctx = hotel_agency_offer(
        b,
        instant=instant,
        travel_date=travel_date,
        net_rate_cents=hotel_net_rate_cents,
        tax_fee_pct=hotel_tax_fee_pct,
    )
    ctx = air_merchant_offer(
        b,
        ctx,
        travel_date=travel_date,
        net_rate_cents=air_net_rate_cents,
        base_markup_pct=air_markup_pct,
        tax_fee_pct=air_tax_fee_pct,
    )
    ctx["package"] = b.package(ctx.market["id"], travel_date=travel_date, opaque=True)
    ctx["hotel_component"] = b.component(
        ctx.package["id"], ctx.offer["id"], "HOTEL"
    )
    ctx["air_component"] = b.component(
        ctx.package["id"], ctx.air_offer["id"], "AIR"
    )
    if price or publish:
        ctx["package"] = b.price_package(ctx.package["id"])
    if publish:
        ctx["package"] = b.publish_package(ctx.package["id"])
    return ctx


def captured_booking(
    b: Builder,
    *,
    instant: str = DEFAULT_INSTANT,
    travel_date: str = DEFAULT_TRAVEL_DATE,
    net_rate_cents: int = 24000,
    tax_fee_pct: float = 0.01,
    confirm: bool = False,
    plan_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
) -> Ctx:
    """A LIVE agency offer booked and captured, optionally supplier-confirmed."""
    ctx = hotel_agency_offer(
        b,
        instant=instant,
        travel_date=travel_date,
        net_rate_cents=net_rate_cents,
        tax_fee_pct=tax_fee_pct,
        plan_overrides=plan_overrides,
        agreement_overrides=agreement_overrides,
    )
    booking = b.booking(offer=ctx.offer)
    b.capture(booking["id"])
    if confirm:
        b.confirm(booking["id"], ctx.supplier["id"])
    ctx["booking"] = b.read_booking(booking["id"])
    return ctx


def parity_case_at(
    b: Builder,
    ctx: Ctx,
    direct_total_cents: int,
    *,
    travel_date: Optional[str] = None,
) -> Tuple[Json, Json]:
    """Posts one direct-rate observation and returns it with its parity case."""
    date = travel_date or ctx.get("travel_date", DEFAULT_TRAVEL_DATE)
    observation = b.observation(
        ctx.rate_plan["id"], travel_date=date, direct_total_cents=direct_total_cents
    )
    case = (
        b.read_parity_case(observation["parity_case_id"])
        if observation.get("parity_case_id")
        else None
    )
    return observation, case
