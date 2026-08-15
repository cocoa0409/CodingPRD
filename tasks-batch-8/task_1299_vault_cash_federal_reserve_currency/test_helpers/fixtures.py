"""Composite setup helpers.

Each helper builds PRD-visible preconditions from scratch via the public API
(the server restarts before every test, so nothing persists across tests).
All helpers use get_success_data() so setup failures surface as clear
"Setup step failed" errors instead of confusing assertion failures.

Identity threading rule: after creating a StaffMember (or Carrier), every
site-scoped / ownership-gated call uses make_*_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_atm_forecast_payload,
    create_atm_machine_payload,
    create_carrier_payload,
    create_cash_shipment_payload,
    create_counterfeit_case_payload,
    create_denomination_line_payload,
    create_fed_order_payload,
    create_fitness_batch_payload,
    create_reconciliation_payload,
    create_seasonal_window_payload,
    create_staff_member_payload,
    create_vault_site_payload,
)
from .test_users import (
    TEST_USERS,
    make_atm_analyst_headers,
    make_carrier_dispatcher_headers,
    make_compliance_officer_headers,
    make_custodian_headers,
    make_fed_coordinator_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: atomic creators (single POST each, validated)
# ---------------------------------------------------------------------------

def create_site(**overrides) -> dict:
    resp = api_client.create_vault_site(create_vault_site_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_staff(site_id: str, full_name: str = "Staff Member") -> dict:
    resp = api_client.create_staff_member(
        create_staff_member_payload(full_name=full_name, home_site_id=site_id), ADMIN
    )
    return get_success_data(resp)


def create_carrier(**overrides) -> dict:
    resp = api_client.create_carrier(create_carrier_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_atm(site_id: str, **overrides) -> dict:
    resp = api_client.create_atm_machine(
        create_atm_machine_payload(site_id=site_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_seasonal_window(site_id: str, **overrides) -> dict:
    resp = api_client.create_seasonal_window(
        create_seasonal_window_payload(site_id=site_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def get_site(site_id: str) -> dict:
    return get_success_data(api_client.get_vault_site(site_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: staffed site — site plus the staff members tests commonly need
# ---------------------------------------------------------------------------

def create_staffed_site(
    staff_roles=("custodian",),
    site_overrides=None,
) -> dict:
    """Create a site plus named staff anchored to it.

    Returns {"site": site, "staff": {label: {"id", "headers"}}} where headers
    carry the correct role for each label:
      custodian -> VaultCustodian, coordinator -> FedCoordinator,
      analyst -> AtmAnalyst, compliance -> ComplianceOfficer,
      peer -> a second VaultCustodian of the same site (SoD scenarios).
    """
    site = create_site(**(site_overrides or {}))
    staff: dict = {}
    builders = {
        "custodian": make_custodian_headers,
        "coordinator": make_fed_coordinator_headers,
        "analyst": make_atm_analyst_headers,
        "compliance": make_compliance_officer_headers,
        "peer": make_custodian_headers,
    }
    for label in staff_roles:
        member = create_staff(site["id"], full_name=f"{label.title()} {label}")
        staff[label] = {"id": member["id"], "headers": builders[label](member["id"])}
    return {"site": site, "staff": staff}


# ---------------------------------------------------------------------------
# Tier 3: Fed order lifecycle
# ---------------------------------------------------------------------------

def create_draft_order_with_line(
    site_id: str,
    coordinator_headers: dict,
    direction: str = "ORDER",
    business_date: str = "2026-08-03",
    denomination_cents: int = 2000,
    strap_count: int = 10,
) -> dict:
    """Create an empty order and add one denomination line (OCC-threaded).

    Returns the order dict refreshed after the line add.
    """
    order = get_success_data(
        api_client.create_fed_order(
            create_fed_order_payload(
                site_id=site_id, direction=direction, business_date=business_date
            ),
            coordinator_headers,
        )
    )
    get_success_data(
        api_client.add_denomination_line(
            order["id"],
            create_denomination_line_payload(
                denomination_cents=denomination_cents,
                strap_count=strap_count,
                expected_fed_order_version=order["version"],
            ),
            coordinator_headers,
        )
    )
    return get_success_data(api_client.get_fed_order(order["id"], coordinator_headers))


def create_submitted_order(
    site_id: str,
    coordinator_headers: dict,
    direction: str = "ORDER",
    business_date: str = "2026-08-04",
    denomination_cents: int = 2000,
    strap_count: int = 10,
) -> dict:
    """Order walked DRAFT -> SUBMITTED. Returns the submitted order."""
    order = create_draft_order_with_line(
        site_id,
        coordinator_headers,
        direction=direction,
        business_date=business_date,
        denomination_cents=denomination_cents,
        strap_count=strap_count,
    )
    return get_success_data(api_client.submit_fed_order(order["id"], coordinator_headers))


def create_acknowledged_order(
    site_id: str,
    coordinator_headers: dict,
    direction: str = "ORDER",
    business_date: str = "2026-08-04",
    denomination_cents: int = 2000,
    strap_count: int = 10,
) -> dict:
    """Order walked DRAFT -> SUBMITTED -> ACKNOWLEDGED. Returns the order."""
    order = create_submitted_order(
        site_id,
        coordinator_headers,
        direction=direction,
        business_date=business_date,
        denomination_cents=denomination_cents,
        strap_count=strap_count,
    )
    return get_success_data(api_client.acknowledge_fed_order(order["id"], coordinator_headers))


# ---------------------------------------------------------------------------
# Tier 4: shipment lifecycle
# ---------------------------------------------------------------------------

def create_order_shipment(
    order_id: str,
    carrier_id: str,
    coordinator_headers: dict,
    departure: str = "2026-08-02T10:00:00Z",
    arrival: str = "2026-08-02T12:00:00Z",
) -> dict:
    """Schedule a Fed-order-linked shipment (origin/destination/declared derived)."""
    return get_success_data(
        api_client.create_cash_shipment(
            create_cash_shipment_payload(
                fed_order_id=order_id,
                carrier_id=carrier_id,
                scheduled_departure_at=departure,
                scheduled_arrival_at=arrival,
            ),
            coordinator_headers,
        )
    )


def create_inter_site_shipment(
    origin_site_id: str,
    destination_site_id: str,
    carrier_id: str,
    coordinator_headers: dict,
    declared_value_cents: int = 1000000,
    departure: str = "2026-08-10T10:00:00Z",
    arrival: str = "2026-08-10T12:00:00Z",
) -> dict:
    """Schedule an inter-site transfer with a client-supplied declared value."""
    return get_success_data(
        api_client.create_cash_shipment(
            create_cash_shipment_payload(
                origin_site_id=origin_site_id,
                destination_site_id=destination_site_id,
                carrier_id=carrier_id,
                declared_value_cents=declared_value_cents,
                scheduled_departure_at=departure,
                scheduled_arrival_at=arrival,
            ),
            coordinator_headers,
        )
    )


def create_in_transit_order_shipment(
    site_id: str,
    coordinator_headers: dict,
    carrier_id: str,
    business_date: str = "2026-08-04",
    denomination_cents: int = 2000,
    strap_count: int = 10,
    departure: str = "2026-08-02T10:00:00Z",
    arrival: str = "2026-08-02T12:00:00Z",
) -> dict:
    """Full chain: ACKNOWLEDGED order + shipment LOADED + departed (IN_TRANSIT).

    Returns {"order": ..., "shipment": ...} refreshed after departure.
    """
    order = create_acknowledged_order(
        site_id,
        coordinator_headers,
        direction="ORDER",
        business_date=business_date,
        denomination_cents=denomination_cents,
        strap_count=strap_count,
    )
    shipment = create_order_shipment(
        order["id"], carrier_id, coordinator_headers, departure=departure, arrival=arrival
    )
    get_success_data(api_client.load_cash_shipment(shipment["id"], coordinator_headers))
    get_success_data(
        api_client.depart_cash_shipment(
            shipment["id"], make_carrier_dispatcher_headers(carrier_id)
        )
    )
    return {
        "order": get_success_data(api_client.get_fed_order(order["id"], coordinator_headers)),
        "shipment": get_success_data(
            api_client.get_cash_shipment(shipment["id"], coordinator_headers)
        ),
    }


def create_received_order_shipment(
    site_id: str,
    coordinator_headers: dict,
    carrier_id: str,
    direction: str = "ORDER",
    business_date: str = "2026-08-04",
    denomination_cents: int = 2000,
    strap_count: int = 10,
    departure: str = "2026-08-02T10:00:00Z",
    arrival: str = "2026-08-02T12:00:00Z",
    counted_value_cents=None,
) -> dict:
    """Full chain through a matched verify: order RECEIVED, shipment VERIFIED.

    Works for both directions: ORDER (inbound, Fed origin) and DEPOSIT (outbound,
    Fed destination). Returns {"order": ..., "shipment": ...} refreshed.
    """
    if direction == "ORDER":
        bundle = create_in_transit_order_shipment(
            site_id,
            coordinator_headers,
            carrier_id,
            business_date=business_date,
            denomination_cents=denomination_cents,
            strap_count=strap_count,
            departure=departure,
            arrival=arrival,
        )
    else:
        order = create_acknowledged_order(
            site_id,
            coordinator_headers,
            direction="DEPOSIT",
            business_date=business_date,
            denomination_cents=denomination_cents,
            strap_count=strap_count,
        )
        shipment = create_order_shipment(
            order["id"], carrier_id, coordinator_headers, departure=departure, arrival=arrival
        )
        get_success_data(api_client.load_cash_shipment(shipment["id"], coordinator_headers))
        get_success_data(
            api_client.depart_cash_shipment(
                shipment["id"], make_carrier_dispatcher_headers(carrier_id)
            )
        )
        bundle = {
            "order": get_success_data(
                api_client.get_fed_order(order["id"], coordinator_headers)
            ),
            "shipment": get_success_data(
                api_client.get_cash_shipment(shipment["id"], coordinator_headers)
            ),
        }
    declared = bundle["shipment"]["declared_value_cents"]
    payload = {"counted_value_cents": counted_value_cents if counted_value_cents is not None else declared}
    get_success_data(
        api_client.verify_cash_shipment(
            bundle["shipment"]["id"], payload, make_carrier_dispatcher_headers(carrier_id)
        )
    )
    return {
        "order": get_success_data(
            api_client.get_fed_order(bundle["order"]["id"], coordinator_headers)
        ),
        "shipment": get_success_data(
            api_client.get_cash_shipment(bundle["shipment"]["id"], coordinator_headers)
        ),
    }


# ---------------------------------------------------------------------------
# Tier 5: fitness / counterfeit / reconciliation / forecast lifecycles
# ---------------------------------------------------------------------------

def create_open_fitness_batch(
    site_id: str, custodian_headers: dict, input_unfit_cents: int = 500000
) -> dict:
    return get_success_data(
        api_client.create_fitness_batch(
            create_fitness_batch_payload(site_id=site_id, input_unfit_cents=input_unfit_cents),
            custodian_headers,
        )
    )


def create_sorted_fitness_batch(
    site_id: str,
    custodian_headers: dict,
    input_unfit_cents: int = 500000,
    fit_recovered_cents: int = 300000,
    unfit_remaining_cents: int = 200000,
    counterfeit_face_cents: int = 0,
) -> dict:
    """Batch created and sorted (OPEN -> SORTED). Returns the sorted batch."""
    batch = create_open_fitness_batch(site_id, custodian_headers, input_unfit_cents)
    return get_success_data(
        api_client.record_sort_results(
            batch["id"],
            {
                "fit_recovered_cents": fit_recovered_cents,
                "unfit_remaining_cents": unfit_remaining_cents,
                "counterfeit_face_cents": counterfeit_face_cents,
            },
            custodian_headers,
        )
    )


def create_seized_counterfeit_case(
    site_id: str,
    custodian_headers: dict,
    denomination_cents: int = 2000,
    note_count: int = 25,
) -> dict:
    """Direct detection by the custodian, then seized by the same custodian."""
    case = get_success_data(
        api_client.create_counterfeit_case(
            create_counterfeit_case_payload(
                site_id=site_id,
                denomination_cents=denomination_cents,
                note_count=note_count,
            ),
            custodian_headers,
        )
    )
    return get_success_data(api_client.seize_counterfeit_case(case["id"], custodian_headers))


def create_balanced_reconciliation(
    site_id: str,
    custodian_headers: dict,
    business_date: str = "2026-08-02",
    opening_balance_cents: int = 5000000,
    counted_on_hand_cents=None,
) -> dict:
    """Reconciliation opened and counted within tolerance -> BALANCED."""
    recon = get_success_data(
        api_client.create_reconciliation(
            create_reconciliation_payload(
                site_id=site_id,
                business_date=business_date,
                opening_balance_cents=opening_balance_cents,
            ),
            custodian_headers,
        )
    )
    counted = (
        counted_on_hand_cents if counted_on_hand_cents is not None else opening_balance_cents
    )
    return get_success_data(
        api_client.count_reconciliation(
            recon["id"], {"counted_on_hand_cents": counted}, custodian_headers
        )
    )


def create_draft_forecast(
    atm_id: str,
    analyst_headers: dict,
    forecast_date: str = "2026-08-10",
    w1_cents: int = 1000000,
    w2_cents: int = 2000000,
    w3_cents: int = 3000000,
) -> dict:
    return get_success_data(
        api_client.create_atm_forecast(
            create_atm_forecast_payload(
                atm_id=atm_id,
                forecast_date=forecast_date,
                w1_cents=w1_cents,
                w2_cents=w2_cents,
                w3_cents=w3_cents,
            ),
            analyst_headers,
        )
    )


def create_published_forecast(
    atm_id: str,
    analyst_headers: dict,
    forecast_date: str = "2026-08-10",
    w1_cents: int = 1000000,
    w2_cents: int = 2000000,
    w3_cents: int = 3000000,
) -> dict:
    """Forecast created and published (OCC reads the ATM version fresh)."""
    forecast = create_draft_forecast(
        atm_id,
        analyst_headers,
        forecast_date=forecast_date,
        w1_cents=w1_cents,
        w2_cents=w2_cents,
        w3_cents=w3_cents,
    )
    atm = get_success_data(api_client.get_atm_machine(atm_id, analyst_headers))
    return get_success_data(
        api_client.publish_atm_forecast(
            forecast["id"], {"expected_atm_version": atm["version"]}, analyst_headers
        )
    )
