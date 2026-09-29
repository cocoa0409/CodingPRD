"""Composite state builders and pytest fixtures.

The server starts empty for every test, so every fixture here builds the state it
needs from scratch through the public API: it sets the logical clock, seeds the
statutory rule, opens the store, stocks the unit, hires the crew, onboards and
verifies the renter, signs the agreement and, where the scenario needs the goods
in the customer's hands, schedules and completes the delivery.

``RtoWorld`` is the workhorse: one method per workflow step, each of which
tolerates any 2xx so that setup never fails on a status-code nuance, leaving the
tests themselves to pin the statuses their scenario is about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import RtoApiClient
from .constants import (
    AUSTIN_MAIN,
    CLOCK_EPOCH,
    DAY_12,
    DAY_18,
    MN_CREW_A,
    TX_CREW_A,
    Category,
    CheckStatus,
    Channel,
    Decision,
    Outcome,
    PaymentMethod,
    Resolution,
    ReturnReason,
    ServiceType,
    TermType,
)
from .test_users import (
    ADMIN,
    COLLECTOR,
    MANAGER,
    OFFICER,
    OFFICER_USER_ID,
    SALES,
    SALES_USER_ID,
    TECHNICIAN,
    TECH_USER_ID,
    make_collector_headers,
    make_officer_headers,
    make_sales_headers,
    make_technician_headers,
)

JsonDict = Dict[str, Any]

CANONICAL_WINDOW_START = "2026-08-01T09:00:00Z"
CANONICAL_WINDOW_END = "2026-08-01T11:00:00Z"


# ---------------------------------------------------------------------------
# The workhorse
# ---------------------------------------------------------------------------


class RtoWorld:
    """Drives the API through whole workflows so tests can start mid-story."""

    def __init__(self, api: RtoApiClient) -> None:
        self.api = api

    # -- the logical clock ------------------------------------------------

    def set_clock(self, to_iso8601: str) -> str:
        data = get_success_data(self.api.set_clock(to_iso8601, ADMIN))
        return data.get("current_utc", to_iso8601)

    def read_clock(self) -> str:
        return get_success_data(self.api.get_clock(ADMIN))["current_utc"]

    # -- statutory rules ---------------------------------------------------

    def seed_rule(self, payload: JsonDict) -> JsonDict:
        return get_success_data(self.api.create_state_rule(payload, ADMIN))

    def seed_tx_rule(self, **overrides: Any) -> JsonDict:
        return self.seed_rule(f.tx_rule_payload(**overrides))

    def seed_mn_rule(self, **overrides: Any) -> JsonDict:
        return self.seed_rule(f.mn_rule_payload(**overrides))

    def seed_nv_rule(self, **overrides: Any) -> JsonDict:
        return self.seed_rule(f.nv_rule_payload(**overrides))

    # -- stores, units, crews ---------------------------------------------

    def open_store(
        self,
        name: str = AUSTIN_MAIN,
        state_code: str = "TX",
        service_bay_capacity: Optional[int] = 1,
    ) -> JsonDict:
        return get_success_data(
            self.api.create_store(
                f.store_payload(name, state_code, service_bay_capacity), ADMIN
            )
        )

    def add_unit(self, store_id: str, payload: JsonDict) -> JsonDict:
        return get_success_data(
            self.api.create_inventory_unit(store_id, payload, MANAGER)
        )

    def add_sofa(self, store_id: str, serial_number: str) -> JsonDict:
        return self.add_unit(store_id, f.sofa_payload(serial_number))

    def add_washer(self, store_id: str, serial_number: str) -> JsonDict:
        return self.add_unit(store_id, f.washer_payload(serial_number))

    def add_crew(
        self,
        store_id: str,
        crew_name: str = TX_CREW_A,
        setup_certified: bool = True,
        status: Optional[str] = None,
    ) -> JsonDict:
        return get_success_data(
            self.api.create_delivery_crew(
                store_id, f.crew_payload(crew_name, setup_certified, status), MANAGER
            )
        )

    # -- renters -----------------------------------------------------------

    def create_customer(self, payload: JsonDict) -> JsonDict:
        return get_success_data(self.api.create_customer(payload, SALES))

    def add_reference(self, customer_id: str, payload: JsonDict) -> JsonDict:
        return get_success_data(
            self.api.create_customer_reference(customer_id, payload, SALES)
        )

    def check_reference(
        self,
        reference_id: str,
        result: str = CheckStatus.VERIFIED,
        as_user_id: str = SALES_USER_ID,
    ) -> JsonDict:
        return get_success_data(
            self.api.check_customer_reference(
                reference_id, f.check_payload(result), make_sales_headers(as_user_id)
            )
        )

    def verify_customer(
        self,
        customer_id: str,
        decision: str = Decision.APPROVE,
        credit_score: Optional[int] = None,
        as_user_id: str = OFFICER_USER_ID,
    ) -> JsonDict:
        return get_success_data(
            self.api.verify_customer(
                customer_id,
                f.verify_payload(decision, credit_score),
                make_officer_headers(as_user_id),
            )
        )

    def onboard(
        self,
        customer_payload: JsonDict,
        references: Sequence[JsonDict],
        results: Optional[Sequence[str]] = None,
        verify: bool = True,
        officer_user_id: str = OFFICER_USER_ID,
    ) -> JsonDict:
        """Create a renter, telephone its references and take the approval decision."""
        customer = self.create_customer(customer_payload)
        outcomes = list(results) if results is not None else [CheckStatus.VERIFIED] * len(
            references
        )
        for payload, outcome in zip(references, outcomes):
            reference = self.add_reference(customer["id"], payload)
            self.check_reference(reference["id"], outcome)
        if verify:
            self.verify_customer(
                customer["id"], Decision.APPROVE, as_user_id=officer_user_id
            )
        return self.get_customer(customer["id"])

    def onboard_dana(
        self, verify: bool = True, officer_user_id: str = OFFICER_USER_ID
    ) -> JsonDict:
        return self.onboard(
            f.dana_reyes_payload(),
            f.dana_reyes_references(),
            verify=verify,
            officer_user_id=officer_user_id,
        )

    # -- agreements --------------------------------------------------------

    def sign(
        self,
        customer_id: str,
        unit_id: str,
        term_type: str = TermType.WEEKLY,
        renewal_count: int = 52,
        disclosure_acknowledged: Optional[bool] = True,
        headers: Optional[JsonDict] = None,
    ) -> JsonDict:
        return get_success_data(
            self.api.create_agreement(
                f.agreement_payload(
                    customer_id,
                    unit_id,
                    term_type,
                    renewal_count,
                    disclosure_acknowledged,
                ),
                headers or SALES,
            )
        )

    def get_agreement(self, agreement_id: str) -> JsonDict:
        return get_success_data(self.api.get_agreement(agreement_id, MANAGER))

    def agreement_version(self, agreement_id: str) -> int:
        return self.get_agreement(agreement_id)["version"]

    def disclosure(self, agreement_id: str) -> JsonDict:
        return get_success_data(self.api.get_agreement_disclosure(agreement_id, MANAGER))

    # -- delivery ----------------------------------------------------------

    def schedule_delivery(
        self,
        agreement_id: str,
        crew_id: str,
        window_start_at: str = CANONICAL_WINDOW_START,
        window_end_at: str = CANONICAL_WINDOW_END,
        service_type: str = ServiceType.DELIVERY_ONLY,
        expected_agreement_version: Optional[int] = None,
    ) -> JsonDict:
        version = (
            expected_agreement_version
            if expected_agreement_version is not None
            else self.agreement_version(agreement_id)
        )
        return get_success_data(
            self.api.create_delivery_order(
                agreement_id,
                f.delivery_order_payload(
                    crew_id, version, window_start_at, window_end_at, service_type
                ),
                MANAGER,
            )
        )

    def complete_delivery(self, order_id: str, setup_completed: bool = False) -> JsonDict:
        return get_success_data(
            self.api.complete_delivery_order(
                order_id, f.complete_delivery_payload(setup_completed), MANAGER
            )
        )

    def fail_attempt(self, order_id: str, reason: str) -> JsonDict:
        return get_success_data(
            self.api.fail_delivery_attempt(order_id, f.fail_attempt_payload(reason), MANAGER)
        )

    def deliver(
        self,
        agreement_id: str,
        crew_id: str,
        window_start_at: str = CANONICAL_WINDOW_START,
        window_end_at: str = CANONICAL_WINDOW_END,
        service_type: str = ServiceType.DELIVERY_ONLY,
        setup_completed: bool = False,
    ) -> JsonDict:
        """Schedule and then complete a delivery, starting the billing cycle."""
        order = self.schedule_delivery(
            agreement_id, crew_id, window_start_at, window_end_at, service_type
        )
        self.complete_delivery(order["id"], setup_completed)
        return order

    # -- payments ----------------------------------------------------------

    def pay(
        self,
        agreement_id: str,
        amount_cents: int,
        payment_method: str = PaymentMethod.CASH,
        apply_customer_credit: Optional[bool] = None,
        headers: Optional[JsonDict] = None,
    ) -> JsonDict:
        return get_success_data(
            self.api.post_renewal_payment(
                agreement_id,
                f.payment_payload(amount_cents, payment_method, apply_customer_credit),
                headers or SALES,
            )
        )

    def reverse(self, payment_id: str, reason: str) -> JsonDict:
        return get_success_data(
            self.api.reverse_renewal_payment(payment_id, f.reversal_payload(reason), MANAGER)
        )

    def day_close(self, store_id: str) -> JsonDict:
        return get_success_data(self.api.run_day_close(store_id, MANAGER))

    # -- service -----------------------------------------------------------

    def open_ticket(
        self,
        agreement_id: str,
        issue_code: str,
        window_start_at: str,
        window_end_at: str,
        headers: Optional[JsonDict] = None,
    ) -> JsonDict:
        return get_success_data(
            self.api.create_service_ticket(
                agreement_id,
                f.service_ticket_payload(issue_code, window_start_at, window_end_at),
                headers or TECHNICIAN,
            )
        )

    def issue_swap(self, ticket_id: str, replacement_unit_id: str) -> JsonDict:
        return get_success_data(
            self.api.issue_swap(
                ticket_id, f.issue_swap_payload(replacement_unit_id), TECHNICIAN
            )
        )

    def resolve_ticket(
        self, ticket_id: str, resolution: str = Resolution.REPAIRED, rent_credit_days: int = 0
    ) -> JsonDict:
        return get_success_data(
            self.api.resolve_service_ticket(
                ticket_id, f.resolve_ticket_payload(resolution, rent_credit_days), TECHNICIAN
            )
        )

    # -- returns and grading ----------------------------------------------

    def start_return(
        self, agreement_id: str, return_reason: str = ReturnReason.VOLUNTARY_RETURN
    ) -> JsonDict:
        return get_success_data(
            self.api.return_agreement(agreement_id, f.return_payload(return_reason), MANAGER)
        )

    def grade(
        self,
        inspection_id: str,
        assessed_grade: str,
        damage_deduction_cents: int = 0,
        missing_parts_count: int = 0,
        as_user_id: str = TECH_USER_ID,
    ) -> JsonDict:
        return get_success_data(
            self.api.grade_return_inspection(
                inspection_id,
                f.grade_payload(
                    assessed_grade, damage_deduction_cents, missing_parts_count
                ),
                make_technician_headers(as_user_id),
            )
        )

    # -- early purchase ----------------------------------------------------

    def issue_quote(
        self,
        agreement_id: str,
        expected_agreement_version: Optional[int] = None,
        headers: Optional[JsonDict] = None,
    ) -> JsonDict:
        version = (
            expected_agreement_version
            if expected_agreement_version is not None
            else self.agreement_version(agreement_id)
        )
        return get_success_data(
            self.api.issue_early_purchase_quote(
                agreement_id, f.quote_payload(version), headers or MANAGER
            )
        )

    def accept_quote(self, quote_id: str, payment_amount_cents: int) -> JsonDict:
        return get_success_data(
            self.api.accept_early_purchase_quote(
                quote_id, f.accept_quote_payload(payment_amount_cents), MANAGER
            )
        )

    # -- collections -------------------------------------------------------

    def log_contact(
        self,
        agreement_id: str,
        channel: str = Channel.PHONE,
        outcome: str = Outcome.NO_ANSWER,
        as_user_id: Optional[str] = None,
    ) -> JsonDict:
        headers = make_collector_headers(as_user_id) if as_user_id else COLLECTOR
        return get_success_data(
            self.api.log_collection_contact(
                agreement_id, f.collection_contact_payload(channel, outcome), headers
            )
        )

    def repossess(
        self, agreement_id: str, headers: Optional[JsonDict] = None
    ) -> JsonDict:
        return get_success_data(
            self.api.repossess_agreement(
                agreement_id, f.repossess_payload(True), headers or COLLECTOR
            )
        )

    # -- reads -------------------------------------------------------------

    def get_store(self, store_id: str) -> JsonDict:
        return get_success_data(self.api.get_store(store_id, MANAGER))

    def get_unit(self, unit_id: str) -> JsonDict:
        return get_success_data(self.api.get_inventory_unit(unit_id, MANAGER))

    def get_customer(self, customer_id: str) -> JsonDict:
        return get_success_data(self.api.get_customer(customer_id, MANAGER))

    def get_ticket(self, ticket_id: str) -> JsonDict:
        return get_success_data(self.api.get_service_ticket(ticket_id, TECHNICIAN))

    def get_delivery_order(self, order_id: str) -> JsonDict:
        return get_success_data(self.api.get_delivery_order(order_id, MANAGER))

    def get_inspection(self, inspection_id: str) -> JsonDict:
        return get_success_data(self.api.get_return_inspection(inspection_id, MANAGER))

    def _rows(self, response) -> List[JsonDict]:
        return get_success_data(response)

    def payments(self, agreement_id: str, **params: Any) -> List[JsonDict]:
        return self._rows(
            self.api.list_renewal_payments(agreement_id, MANAGER, params or None)
        )

    def windows(self, agreement_id: str, **params: Any) -> List[JsonDict]:
        return self._rows(
            self.api.list_reinstatement_windows(agreement_id, MANAGER, params or None)
        )

    def quotes(self, agreement_id: str, **params: Any) -> List[JsonDict]:
        return self._rows(
            self.api.list_early_purchase_quotes(agreement_id, MANAGER, params or None)
        )

    def contacts(self, agreement_id: str, **params: Any) -> List[JsonDict]:
        return self._rows(
            self.api.list_collection_contacts(agreement_id, COLLECTOR, params or None)
        )

    def ledger(self, **params: Any) -> List[JsonDict]:
        return self._rows(self.api.list_loyalty_ledger_entries(MANAGER, params or None))

    def inspections(self, **params: Any) -> List[JsonDict]:
        return self._rows(self.api.list_return_inspections(MANAGER, params or None))

    def units(self, **params: Any) -> List[JsonDict]:
        return self._rows(self.api.list_inventory_units(MANAGER, params or None))

    def agreements(self, **params: Any) -> List[JsonDict]:
        return self._rows(self.api.list_agreements(MANAGER, params or None))

    def tickets(self, **params: Any) -> List[JsonDict]:
        return self._rows(self.api.list_service_tickets(MANAGER, params or None))

    def delivery_orders(self, **params: Any) -> List[JsonDict]:
        return self._rows(self.api.list_delivery_orders(MANAGER, params or None))


# ---------------------------------------------------------------------------
# Scenario container
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """A built-up story: the rows a test starts from, plus the world that made them."""

    world: RtoWorld
    rule: JsonDict
    store: JsonDict
    customer: JsonDict
    units: List[JsonDict] = field(default_factory=list)
    crew: Optional[JsonDict] = None
    agreement: Optional[JsonDict] = None
    agreement_v1: Optional[int] = None
    delivery_order: Optional[JsonDict] = None

    @property
    def api(self) -> RtoApiClient:
        return self.world.api

    @property
    def store_id(self) -> str:
        return self.store["id"]

    @property
    def customer_id(self) -> str:
        return self.customer["id"]

    @property
    def unit(self) -> JsonDict:
        return self.units[0]

    @property
    def unit_id(self) -> str:
        return self.units[0]["id"]

    @property
    def crew_id(self) -> str:
        assert self.crew is not None, "this scenario has no crew"
        return self.crew["id"]

    @property
    def agreement_id(self) -> str:
        assert self.agreement is not None, "this scenario has no agreement"
        return self.agreement["id"]

    # -- convenience re-reads ---------------------------------------------

    def read_agreement(self) -> JsonDict:
        return self.world.get_agreement(self.agreement_id)

    def read_store(self) -> JsonDict:
        return self.world.get_store(self.store_id)

    def read_customer(self) -> JsonDict:
        return self.world.get_customer(self.customer_id)

    def read_unit(self, index: int = 0) -> JsonDict:
        return self.world.get_unit(self.units[index]["id"])


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def build_tx_floor(
    world: RtoWorld,
    service_bay_capacity: int = 1,
    serials: Sequence[str] = ("SN-TX-0001",),
    category: str = Category.FURNITURE,
    with_crew: bool = True,
    verify_customer: bool = True,
) -> Scenario:
    """Clock at the epoch, the Texas rule seeded, a store stocked and a renter verified."""
    world.set_clock(CLOCK_EPOCH)
    rule = world.seed_tx_rule()
    store = world.open_store(AUSTIN_MAIN, "TX", service_bay_capacity)
    units = [
        world.add_sofa(store["id"], serial)
        if category == Category.FURNITURE
        else world.add_washer(store["id"], serial)
        for serial in serials
    ]
    crew = world.add_crew(store["id"], TX_CREW_A, setup_certified=True) if with_crew else None
    customer = world.onboard_dana(verify=verify_customer)
    return Scenario(
        world=world, rule=rule, store=store, customer=customer, units=units, crew=crew
    )


def sign_on(
    scenario: Scenario,
    unit_index: int = 0,
    term_type: str = TermType.WEEKLY,
    renewal_count: int = 52,
) -> Scenario:
    """Sign the canonical term against one of the scenario's units."""
    agreement = scenario.world.sign(
        scenario.customer_id,
        scenario.units[unit_index]["id"],
        term_type,
        renewal_count,
    )
    scenario.agreement = agreement
    scenario.agreement_v1 = agreement["version"]
    return scenario


def deliver_on(
    scenario: Scenario,
    window_start_at: str = CANONICAL_WINDOW_START,
    window_end_at: str = CANONICAL_WINDOW_END,
    service_type: str = ServiceType.DELIVERY_ONLY,
    setup_completed: bool = False,
) -> Scenario:
    """Put the goods in the customer's hands, which is where billing begins."""
    scenario.delivery_order = scenario.world.deliver(
        scenario.agreement_id,
        scenario.crew_id,
        window_start_at,
        window_end_at,
        service_type,
        setup_completed,
    )
    return scenario


def build_mn_floor(
    world: RtoWorld,
    store_name: str,
    service_bay_capacity: int = 1,
    serials: Sequence[str] = ("SN-MN-0001",),
    customer_payload: Optional[JsonDict] = None,
    references: Optional[Sequence[JsonDict]] = None,
) -> Scenario:
    """The Minnesota counterpart: a milder late fee, a longer window, no processing fee."""
    world.set_clock(CLOCK_EPOCH)
    rule = world.seed_mn_rule()
    store = world.open_store(store_name, "MN", service_bay_capacity)
    units = [world.add_sofa(store["id"], serial) for serial in serials]
    crew = world.add_crew(store["id"], MN_CREW_A, setup_certified=True)
    customer = world.onboard(
        customer_payload if customer_payload is not None else f.ivar_holm_payload(),
        references if references is not None else f.ivar_holm_references(),
    )
    return Scenario(
        world=world, rule=rule, store=store, customer=customer, units=units, crew=crew
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> RtoApiClient:
    """A transport client pointed at the server under test."""
    return RtoApiClient()


@pytest.fixture
def world(api: RtoApiClient) -> RtoWorld:
    """A workflow driver over the empty server."""
    return RtoWorld(api)


@pytest.fixture
def tx_floor(world: RtoWorld) -> Scenario:
    """Texas rule, one store, one brand-new sofa, one crew, one verified renter."""
    return build_tx_floor(world)


@pytest.fixture
def tx_signed(tx_floor: Scenario) -> Scenario:
    """The canonical weekly, fifty-two-renewal agreement, unit reserved, anchors null."""
    return sign_on(tx_floor)


@pytest.fixture
def tx_delivered(tx_signed: Scenario) -> Scenario:
    """The canonical agreement with the goods delivered on the first of the month."""
    return deliver_on(tx_signed)


@pytest.fixture
def tx_delinquent(tx_delivered: Scenario) -> Scenario:
    """The canonical agreement four days past a three-day grace period, after a day-close."""
    tx_delivered.world.set_clock(DAY_12)
    tx_delivered.world.day_close(tx_delivered.store_id)
    return tx_delivered


@pytest.fixture
def tx_defaulted(tx_delinquent: Scenario) -> Scenario:
    """The canonical agreement whose five-day reinstatement window has run out."""
    tx_delinquent.world.set_clock(DAY_18)
    tx_delinquent.world.day_close(tx_delinquent.store_id)
    return tx_delinquent
