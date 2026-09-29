"""
Composite fixtures.

The API server is restarted before every test, so every fixture builds its
preconditions from scratch through the declared endpoints. Fixtures that create
a row return the created resource dict; fixtures that need to be parametrised
return a callable taking **overrides.

Identity threading is mandatory for the three entity-backed roles: the operator
headers carry the Warehouse.id, the depositor headers the depositor Party.id and
the lender headers the lender Party.id.
"""

from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    BASE_RECEIPT_NUMBER,
    CLOCK_BASE_UTC,
)
from .test_users import (
    REGULATOR_HEADERS,
    make_depositor_headers,
    make_lender_headers,
    make_warehouse_operator_headers,
)


# ---------------------------------------------------------------------------
# Tier 1 — client and logical clock
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture
def set_clock(api):
    """Move the server's logical clock to an explicit instant."""

    def _set(current_utc: str, headers: Dict[str, str] = REGULATOR_HEADERS) -> None:
        response = api.set_clock(f.clock_payload(current_utc), headers)
        assert response.status_code == 200, (
            f"Setting the logical clock to {current_utc} failed: {response.text}"
        )

    return _set


@pytest.fixture
def base_clock(set_clock) -> str:
    """Pin the logical clock at the shared base instant 2026-08-05T08:00:00Z."""
    set_clock(CLOCK_BASE_UTC)
    return CLOCK_BASE_UTC


# ---------------------------------------------------------------------------
# Tier 2 — root rows
# ---------------------------------------------------------------------------
@pytest.fixture
def new_warehouse(api, base_clock):
    """Create a warehouse licence application in license_state APPLIED."""

    def _make(**overrides) -> Dict[str, Any]:
        return get_success_data(
            api.create_warehouse(f.warehouse_payload(**overrides), REGULATOR_HEADERS),
            201,
        )

    return _make


@pytest.fixture
def licensed_warehouse(api, new_warehouse):
    """Create a warehouse and drive its licensing dimension to LICENSED."""

    def _make(**overrides) -> Dict[str, Any]:
        warehouse = new_warehouse(**overrides)
        return get_success_data(
            api.license_decision(
                warehouse["id"], f.license_issue_payload(), REGULATOR_HEADERS
            ),
            200,
        )

    return _make


@pytest.fixture
def new_producer(api, base_clock):
    """Register a PRODUCER_DEPOSITOR party."""

    def _make(**overrides) -> Dict[str, Any]:
        return get_success_data(
            api.create_party(f.producer_payload(**overrides), REGULATOR_HEADERS), 201
        )

    return _make


@pytest.fixture
def new_commercial_depositor(api, base_clock):
    """Register a COMMERCIAL_DEPOSITOR party (never indemnity-fund eligible)."""

    def _make(**overrides) -> Dict[str, Any]:
        return get_success_data(
            api.create_party(f.commercial_depositor_payload(**overrides), REGULATOR_HEADERS),
            201,
        )

    return _make


@pytest.fixture
def new_lender(api, base_clock):
    """Register a LENDER party with a committed credit line."""

    def _make(**overrides) -> Dict[str, Any]:
        return get_success_data(
            api.create_party(f.lender_payload(**overrides), REGULATOR_HEADERS), 201
        )

    return _make


# ---------------------------------------------------------------------------
# Tier 3 — warehouse-scoped rows
# ---------------------------------------------------------------------------
@pytest.fixture
def new_agreement(api):
    """Open a storage agreement, acting as the warehouse's operator."""

    def _make(warehouse_id: str, depositor_party_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            api.create_storage_agreement(
                f.storage_agreement_payload(warehouse_id, depositor_party_id, **overrides),
                make_warehouse_operator_headers(warehouse_id),
            ),
            201,
        )

    return _make


@pytest.fixture
def new_bin(api):
    """Add a bin to a warehouse in condition_state SOUND."""

    def _make(warehouse_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            api.create_bin(
                f.bin_payload(warehouse_id, **overrides),
                make_warehouse_operator_headers(warehouse_id),
            ),
            201,
        )

    return _make


@pytest.fixture
def assess_bin(api):
    """Record a moisture/temperature reading and re-derive the bin condition."""

    def _assess(
        warehouse_id: str, bin_id: str, moisture_pct: float, temperature_f: float, **overrides
    ) -> Dict[str, Any]:
        return get_success_data(
            api.assess_bin_condition(
                bin_id,
                f.condition_assessment_payload(moisture_pct, temperature_f, **overrides),
                make_warehouse_operator_headers(warehouse_id),
            ),
            200,
        )

    return _assess


# ---------------------------------------------------------------------------
# Tier 4 — grain intake
# ---------------------------------------------------------------------------
@pytest.fixture
def weighed_ticket(api):
    """Weigh an inbound load, leaving the ticket in ticket_state WEIGHED."""

    def _make(
        warehouse_id: str, agreement_id: str, bin_id: str, **overrides
    ) -> Dict[str, Any]:
        return get_success_data(
            api.create_deposit_ticket(
                f.deposit_ticket_payload(agreement_id, bin_id, **overrides),
                make_warehouse_operator_headers(warehouse_id),
            ),
            201,
        )

    return _make


@pytest.fixture
def accept_ticket(api):
    """Accept a weighed ticket, reading the bin version immediately beforehand."""

    def _accept(warehouse_id: str, bin_id: str, ticket_id: str) -> Dict[str, Any]:
        headers = make_warehouse_operator_headers(warehouse_id)
        bin_row = get_success_data(api.get_bin(bin_id, headers), 200)
        return get_success_data(
            api.accept_deposit_ticket(
                ticket_id, f.accept_ticket_payload(bin_row["version"]), headers
            ),
            200,
        )

    return _accept


@pytest.fixture
def accepted_ticket(weighed_ticket, accept_ticket):
    """Weigh and accept a load in one step."""

    def _make(
        warehouse_id: str, agreement_id: str, bin_id: str, **overrides
    ) -> Dict[str, Any]:
        ticket = weighed_ticket(warehouse_id, agreement_id, bin_id, **overrides)
        accept_ticket(warehouse_id, bin_id, ticket["id"])
        return ticket

    return _make


# ---------------------------------------------------------------------------
# Tier 4 — receipt issuance
# ---------------------------------------------------------------------------
@pytest.fixture
def issue_receipt(api):
    """
    Issue a receipt against an accepted ticket, reading the warehouse version
    immediately beforehand so the optimistic-concurrency check passes.
    """

    def _issue(
        warehouse_id: str, ticket_id: str, holder_party_id: str, **overrides
    ) -> Dict[str, Any]:
        headers = make_warehouse_operator_headers(warehouse_id)
        warehouse = get_success_data(api.get_warehouse(warehouse_id, headers), 200)
        return get_success_data(
            api.create_receipt(
                f.receipt_payload(
                    ticket_id, holder_party_id, warehouse["version"], **overrides
                ),
                headers,
            ),
            201,
        )

    return _issue


# ---------------------------------------------------------------------------
# Tier 5 — the shared base chain
# ---------------------------------------------------------------------------
@pytest.fixture
def base_pre(licensed_warehouse, new_producer, new_lender, new_agreement, new_bin, accepted_ticket):
    """
    The shared precondition chain up to (and including) acceptance:
    logical clock at the base instant, a licensed STATE warehouse, a producer
    and a lender party, a COMMINGLED agreement, bin B1 and one ACCEPTED
    949-bushel ticket of US_NO_1 corn. No receipt has been issued yet.
    """
    warehouse = licensed_warehouse()
    producer = new_producer()
    lender = new_lender()
    agreement = new_agreement(warehouse["id"], producer["id"])
    storage_bin = new_bin(warehouse["id"])
    ticket = accepted_ticket(warehouse["id"], agreement["id"], storage_bin["id"])
    return {
        "warehouse": warehouse,
        "warehouse_id": warehouse["id"],
        "depositor": producer,
        "depositor_id": producer["id"],
        "lender": lender,
        "lender_id": lender["id"],
        "agreement": agreement,
        "agreement_id": agreement["id"],
        "bin": storage_bin,
        "bin_id": storage_bin["id"],
        "ticket": ticket,
        "ticket_id": ticket["id"],
        "operator_headers": make_warehouse_operator_headers(warehouse["id"]),
        "depositor_headers": make_depositor_headers(producer["id"]),
        "lender_headers": make_lender_headers(lender["id"]),
    }


@pytest.fixture
def base_full(base_pre, issue_receipt):
    """
    The shared base chain including receipt WR-0001: NEGOTIABLE, ELECTRONIC,
    ISSUED for 949 bushels of US_NO_1 corn, held by the producer,
    encumbrance_state UNENCUMBERED.
    """
    receipt = issue_receipt(
        base_pre["warehouse_id"],
        base_pre["ticket_id"],
        base_pre["depositor_id"],
        receipt_number=BASE_RECEIPT_NUMBER,
    )
    scenario = dict(base_pre)
    scenario["receipt"] = receipt
    scenario["receipt_id"] = receipt["id"]
    return scenario


@pytest.fixture
def request_lien(api):
    """Record a lender's advance request against a receipt (lien_state REQUESTED)."""

    def _request(receipt_id: str, lender_party_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            api.create_collateral_lien(
                f.collateral_lien_payload(receipt_id, lender_party_id, **overrides),
                make_lender_headers(lender_party_id),
            ),
            201,
        )

    return _request


@pytest.fixture
def perfected_lien(api, request_lien):
    """Request and perfect a lien in one step."""

    def _make(receipt_id: str, lender_party_id: str, **overrides) -> Dict[str, Any]:
        lien = request_lien(receipt_id, lender_party_id, **overrides)
        return get_success_data(
            api.perfect_lien(
                lien["id"], f.perfect_payload(), make_lender_headers(lender_party_id)
            ),
            200,
        )

    return _make


@pytest.fixture
def submitted_report(api):
    """Open a DRAFT position report and submit declared figures against it."""

    def _make(
        warehouse_id: str,
        reported_physical_bushels: int,
        reported_obligation_bushels: int,
        **overrides,
    ) -> Dict[str, Any]:
        headers = make_warehouse_operator_headers(warehouse_id)
        report = get_success_data(
            api.create_position_report(
                f.position_report_payload(warehouse_id, **overrides), headers
            ),
            201,
        )
        return get_success_data(
            api.submit_position_report(
                report["id"],
                f.submit_report_payload(
                    reported_physical_bushels, reported_obligation_bushels
                ),
                headers,
            ),
            200,
        )

    return _make


@pytest.fixture
def booked_delivery_order(api):
    """Exercise the delivery right on a receipt and book a loadout lane."""

    def _make(
        depositor_party_id: str,
        receipt_id: str,
        requested_bushels: int,
        appointment_start_at: str,
        appointment_end_at: str,
        **overrides,
    ) -> Dict[str, Any]:
        return get_success_data(
            api.create_delivery_order(
                f.delivery_order_payload(
                    receipt_id,
                    requested_bushels,
                    appointment_start_at,
                    appointment_end_at,
                    **overrides,
                ),
                make_depositor_headers(depositor_party_id),
            ),
            201,
        )

    return _make


@pytest.fixture
def claims_open_warehouse(api):
    """Drive a warehouse's insolvency dimension from SOLVENT to CLAIMS_OPEN."""

    def _open(warehouse_id: str, insolvency_price_cents_per_bushel: int = 400) -> Dict[str, Any]:
        get_success_data(
            api.insolvency_action(
                warehouse_id,
                f.insolvency_payload(
                    "DECLARE",
                    insolvency_price_cents_per_bushel=insolvency_price_cents_per_bushel,
                    note="operator default",
                ),
                REGULATOR_HEADERS,
            ),
            200,
        )
        return get_success_data(
            api.insolvency_action(
                warehouse_id, f.insolvency_payload("OPEN_CLAIMS"), REGULATOR_HEADERS
            ),
            200,
        )

    return _open


@pytest.fixture
def filed_claim(api):
    """File an indemnity claim as the claimant party."""

    def _file(
        warehouse_id: str, receipt_id: str, claimant_party_id: str, claimed_cents: int
    ) -> Dict[str, Any]:
        return get_success_data(
            api.create_indemnity_claim(
                f.indemnity_claim_payload(
                    warehouse_id, receipt_id, claimant_party_id, claimed_cents
                ),
                make_depositor_headers(claimant_party_id),
            ),
            201,
        )

    return _file
