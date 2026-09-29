"""Composite setup helpers.

Every helper drives the real API through PRD-declared endpoints only, using the
lenient success validator so that a broken precondition surfaces as a setup
failure rather than as a confusing assertion inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as f

ADMIN = TEST_USERS["admin_headers"]
REP = TEST_USERS["sales_rep_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]
CERTIFIER = TEST_USERS["hazmat_certifier_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

DEFAULT_WINDOW_START = "2026-08-05T08:00:00Z"
DEFAULT_WINDOW_END = "2026-08-05T18:00:00Z"


# --------------------------------------------------------------------------
# Tier 0: single-call primitives
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock and return the clock payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or ADMIN)
    )


def create_warehouse(**overrides) -> dict:
    return get_success_data(
        api_client.create_warehouse(f.warehouse_payload(**overrides), ADMIN)
    )


def create_carrier(**overrides) -> dict:
    return get_success_data(
        api_client.create_carrier(f.carrier_payload(**overrides), ADMIN)
    )


def create_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_account(f.account_payload(**overrides), ADMIN)
    )


def create_battery_model(preset="IB-31-FLD", **overrides) -> dict:
    return get_success_data(
        api_client.create_battery_model(f.battery_model_payload(preset, **overrides), ADMIN)
    )


def discontinue_battery_model(model_id, replacement_model_id) -> dict:
    return get_success_data(
        api_client.discontinue_battery_model(
            model_id, {"replacement_model_id": replacement_model_id}, ADMIN
        )
    )


def receive_lot(battery_model_id, warehouse_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_inventory_lot(
            f.inventory_lot_payload(battery_model_id, warehouse_id, **overrides), OPERATOR
        )
    )


def refresh_charge(lot_id, measured_open_circuit_voltage=12.75, headers=None) -> dict:
    return get_success_data(
        api_client.refresh_charge_lot(
            lot_id,
            {"measured_open_circuit_voltage": measured_open_circuit_voltage},
            headers or OPERATOR,
        )
    )


def scrap_lot(lot_id, disposal_manifest_id, headers=None) -> dict:
    return get_success_data(
        api_client.scrap_lot(
            lot_id, {"disposal_manifest_id": disposal_manifest_id}, headers or COMPLIANCE
        )
    )


def create_order(account_id, warehouse_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_order(
            f.order_payload(account_id, warehouse_id, **overrides), headers or REP
        )
    )


def add_line(order_id, battery_model_id, quantity=1, core_expected_count=0,
             headers=None) -> dict:
    return get_success_data(
        api_client.create_order_line(
            order_id,
            f.order_line_payload(
                battery_model_id, quantity, core_expected_count=core_expected_count
            ),
            headers or REP,
        )
    )


def submit_order(order_id, headers=None) -> dict:
    return get_success_data(api_client.submit_order(order_id, headers or REP))


def allocate_order(order_id, headers=None) -> dict:
    return get_success_data(api_client.allocate_order(order_id, headers or OPERATOR))


def cancel_order(order_id, reason="Customer deferred the retrofit to next quarter.",
                 headers=None) -> dict:
    return get_success_data(
        api_client.cancel_order(order_id, {"cancellation_reason": reason}, headers or REP)
    )


def read_order(order_id, headers=None) -> dict:
    return get_success_data(api_client.get_order(order_id, headers or REP))


def read_order_line(order_line_id, headers=None) -> dict:
    return get_success_data(api_client.get_order_line(order_line_id, headers or REP))


def read_account(account_id, headers=None) -> dict:
    return get_success_data(api_client.get_account(account_id, headers or ADMIN))


def read_lot(lot_id, headers=None) -> dict:
    return get_success_data(api_client.get_inventory_lot(lot_id, headers or OPERATOR))


def read_shipment(shipment_id, headers=None) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, headers or OPERATOR))


def read_core_return(core_return_id, headers=None) -> dict:
    return get_success_data(api_client.get_core_return(core_return_id, headers or REP))


def read_warranty_claim(claim_id, headers=None) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, headers or REP))


def read_service_contract(contract_id, headers=None) -> dict:
    return get_success_data(api_client.get_service_contract(contract_id, headers or REP))


def read_storm_event(storm_event_id, headers=None) -> dict:
    return get_success_data(api_client.get_storm_event(storm_event_id, headers or COMPLIANCE))


def read_manifest(manifest_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_disposal_manifest(manifest_id, headers or COMPLIANCE)
    )


def order_version(order_id) -> int:
    return read_order(order_id)["version"]


def pack_shipment(order_id, carrier_id, pickup_window_start=DEFAULT_WINDOW_START,
                  pickup_window_end=DEFAULT_WINDOW_END, expected_order_version=None,
                  headers=None) -> dict:
    """Pack an ALLOCATED order onto a carrier, reading the order's current
    version when the caller does not pin one."""
    if expected_order_version is None:
        expected_order_version = order_version(order_id)
    payload = f.shipment_payload(
        order_id,
        carrier_id,
        expected_order_version,
        pickup_window_start=pickup_window_start,
        pickup_window_end=pickup_window_end,
    )
    return get_success_data(api_client.create_shipment(payload, headers or OPERATOR))


def certify_shipment(shipment_id, decision="APPROVE", rejection_reason=None,
                     headers=None) -> dict:
    payload = {"certification_decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(
        api_client.certify_shipment(shipment_id, payload, headers or CERTIFIER)
    )


def dispatch_shipment(shipment_id, headers=None) -> dict:
    return get_success_data(api_client.dispatch_shipment(shipment_id, headers or OPERATOR))


def deliver_shipment(shipment_id, headers=None) -> dict:
    return get_success_data(api_client.deliver_shipment(shipment_id, headers or OPERATOR))


def create_core_return(account_id, order_id, battery_model_id, declared_core_count=1,
                       headers=None) -> dict:
    return get_success_data(
        api_client.create_core_return(
            f.core_return_payload(account_id, order_id, battery_model_id, declared_core_count),
            headers or REP,
        )
    )


def inspect_core_return(core_return_id, accepted_core_count, headers=None) -> dict:
    return get_success_data(
        api_client.inspect_core_return(
            core_return_id, {"accepted_core_count": accepted_core_count}, headers or OPERATOR
        )
    )


def dispute_core_return(core_return_id, reason="Buyer contests the grading of the cores.",
                        headers=None) -> dict:
    return get_success_data(
        api_client.dispute_core_return(
            core_return_id, {"dispute_reason": reason}, headers or REP
        )
    )


def credit_core_return(core_return_id, headers=None) -> dict:
    return get_success_data(api_client.credit_core_return(core_return_id, headers or REP))


def create_warranty_claim(account_id, battery_model_id, serial_number,
                          installed_on="2024-08-15", failed_on="2025-08-15",
                          headers=None) -> dict:
    return get_success_data(
        api_client.create_warranty_claim(
            f.warranty_claim_payload(
                account_id, battery_model_id, serial_number, installed_on, failed_on
            ),
            headers or REP,
        )
    )


def adjudicate_warranty_claim(claim_id, headers=None) -> dict:
    return get_success_data(
        api_client.adjudicate_warranty_claim(claim_id, headers or REP)
    )


def settle_warranty_claim(claim_id, settlement_mode="ACCOUNT_CREDIT",
                          replacement_warehouse_id=None, headers=None) -> dict:
    payload = {"settlement_mode": settlement_mode}
    if replacement_warehouse_id is not None:
        payload["replacement_warehouse_id"] = replacement_warehouse_id
    return get_success_data(
        api_client.settle_warranty_claim(claim_id, payload, headers or REP)
    )


def create_service_contract(account_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_contract(
            f.service_contract_payload(account_id, **overrides), headers or REP
        )
    )


def size_service_contract(contract_id, headers=None) -> dict:
    return get_success_data(api_client.size_service_contract(contract_id, headers or REP))


def attach_service_contract(contract_id, order_id, expected_order_version=None,
                            headers=None) -> dict:
    if expected_order_version is None:
        expected_order_version = order_version(order_id)
    payload = {"order_id": order_id, "expected_order_version": expected_order_version}
    return get_success_data(
        api_client.attach_service_contract(contract_id, payload, headers or REP)
    )


def declare_storm_event(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_storm_event(f.storm_event_payload(**overrides), headers or COMPLIANCE)
    )


def open_storm_allocation(storm_event_id, headers=None) -> dict:
    return get_success_data(
        api_client.open_storm_allocation(storm_event_id, headers or COMPLIANCE)
    )


def close_storm_event(storm_event_id, headers=None) -> dict:
    return get_success_data(
        api_client.close_storm_event(storm_event_id, headers or COMPLIANCE)
    )


def create_disposal_manifest(warehouse_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_disposal_manifest(
            f.disposal_manifest_payload(warehouse_id, **overrides), headers or COMPLIANCE
        )
    )


def attach_core_return_to_manifest(manifest_id, core_return_id,
                                   expected_disposal_manifest_version=None,
                                   headers=None) -> dict:
    if expected_disposal_manifest_version is None:
        expected_disposal_manifest_version = read_manifest(manifest_id)["version"]
    payload = {
        "core_return_id": core_return_id,
        "expected_disposal_manifest_version": expected_disposal_manifest_version,
    }
    return get_success_data(
        api_client.attach_core_return_to_manifest(manifest_id, payload, headers or COMPLIANCE)
    )


def submit_disposal_manifest(manifest_id, headers=None) -> dict:
    return get_success_data(
        api_client.submit_disposal_manifest(manifest_id, headers or COMPLIANCE)
    )


def file_disposal_manifest(manifest_id, headers=None) -> dict:
    """Filing must be performed by an officer other than the manifest's author."""
    from .test_users import make_compliance_officer_headers
    return get_success_data(
        api_client.file_disposal_manifest(
            manifest_id, headers or make_compliance_officer_headers("comp-2")
        )
    )


def reject_disposal_manifest(manifest_id,
                             reason="EPA generator identifier does not match the site permit.",
                             headers=None) -> dict:
    return get_success_data(
        api_client.reject_disposal_manifest(
            manifest_id, {"rejection_reason": reason}, headers or COMPLIANCE
        )
    )


# --------------------------------------------------------------------------
# Tier 1: reference data environment
# --------------------------------------------------------------------------

def setup_base_env(model_preset="IB-31-FLD", model_overrides=None,
                   warehouse_overrides=None, carrier_overrides=None,
                   account_overrides=None, lot_overrides=None,
                   with_carrier=True, with_lot=True) -> dict:
    """Warehouse + carrier + account + catalog model + one lot.

    Returns a dict keyed warehouse / carrier / account / model / lot.
    """
    env = {}
    env["warehouse"] = create_warehouse(**(warehouse_overrides or {}))
    env["carrier"] = create_carrier(**(carrier_overrides or {})) if with_carrier else None
    env["account"] = create_account(**(account_overrides or {}))
    env["model"] = create_battery_model(model_preset, **(model_overrides or {}))
    if with_lot:
        env["lot"] = receive_lot(
            env["model"]["id"], env["warehouse"]["id"], **(lot_overrides or {})
        )
    else:
        env["lot"] = None
    return env


# --------------------------------------------------------------------------
# Tier 2: order lifecycle shortcuts
# --------------------------------------------------------------------------

def setup_draft_order(env, quantity=1, core_expected_count=0, order_overrides=None,
                      model_id=None) -> dict:
    """Add a DRAFT order carrying one line to an existing environment."""
    order = create_order(
        env["account"]["id"], env["warehouse"]["id"], **(order_overrides or {})
    )
    line = add_line(
        order["id"],
        model_id or env["model"]["id"],
        quantity,
        core_expected_count=core_expected_count,
    )
    env = dict(env)
    env["order"] = order
    env["line"] = line
    return env


def setup_submitted_order(env=None, quantity=1, core_expected_count=0,
                          order_overrides=None, **env_kwargs) -> dict:
    """Environment + one submitted (priced, credit-cleared) order."""
    env = env if env is not None else setup_base_env(**env_kwargs)
    env = setup_draft_order(env, quantity, core_expected_count, order_overrides)
    env["order"] = submit_order(env["order"]["id"])
    return env


def setup_allocated_order(env=None, quantity=1, core_expected_count=0,
                          order_overrides=None, **env_kwargs) -> dict:
    """Environment + one order walked through to ALLOCATED."""
    env = setup_submitted_order(env, quantity, core_expected_count, order_overrides,
                                **env_kwargs)
    env["order"] = allocate_order(env["order"]["id"])
    return env


def setup_packed_shipment(env=None, quantity=1, core_expected_count=0,
                          pickup_window_start=DEFAULT_WINDOW_START,
                          pickup_window_end=DEFAULT_WINDOW_END,
                          order_overrides=None, **env_kwargs) -> dict:
    """Environment + an ALLOCATED order packed onto the carrier (PACKED)."""
    env = setup_allocated_order(env, quantity, core_expected_count, order_overrides,
                                **env_kwargs)
    env["shipment"] = pack_shipment(
        env["order"]["id"],
        env["carrier"]["id"],
        pickup_window_start=pickup_window_start,
        pickup_window_end=pickup_window_end,
    )
    return env


def setup_certified_shipment(env=None, quantity=1, core_expected_count=0,
                             pickup_window_start=DEFAULT_WINDOW_START,
                             pickup_window_end=DEFAULT_WINDOW_END,
                             order_overrides=None, **env_kwargs) -> dict:
    """Environment + a shipment approved by a certifier who did not pack it."""
    env = setup_packed_shipment(env, quantity, core_expected_count,
                                pickup_window_start, pickup_window_end,
                                order_overrides, **env_kwargs)
    env["shipment"] = certify_shipment(env["shipment"]["id"], "APPROVE")
    return env


def setup_dispatched_shipment(env=None, quantity=1, core_expected_count=0,
                              dispatch_clock="2026-08-05T09:00:00Z",
                              pickup_window_start=DEFAULT_WINDOW_START,
                              pickup_window_end=DEFAULT_WINDOW_END,
                              order_overrides=None, **env_kwargs) -> dict:
    """Environment + a certified shipment tendered inside its pickup window."""
    env = setup_certified_shipment(env, quantity, core_expected_count,
                                   pickup_window_start, pickup_window_end,
                                   order_overrides, **env_kwargs)
    set_clock(dispatch_clock)
    env["shipment"] = dispatch_shipment(env["shipment"]["id"])
    return env


def setup_delivered_order(env=None, quantity=10, core_expected_count=10,
                          dispatch_clock="2026-08-05T09:00:00Z",
                          pickup_window_start=DEFAULT_WINDOW_START,
                          pickup_window_end=DEFAULT_WINDOW_END,
                          order_overrides=None, **env_kwargs) -> dict:
    """Environment + one order driven all the way to DELIVERED."""
    env = setup_dispatched_shipment(env, quantity, core_expected_count, dispatch_clock,
                                    pickup_window_start, pickup_window_end,
                                    order_overrides, **env_kwargs)
    env["shipment"] = deliver_shipment(env["shipment"]["id"])
    env["order"] = read_order(env["order"]["id"])
    return env


# --------------------------------------------------------------------------
# Tier 3: core-exchange shortcuts
# --------------------------------------------------------------------------

def setup_submitted_core_return(env=None, quantity=10, core_expected_count=10,
                                declared_core_count=10, **kwargs) -> dict:
    """A delivered order plus a declared core return in status SUBMITTED."""
    env = setup_delivered_order(env, quantity, core_expected_count, **kwargs)
    env["core_return"] = create_core_return(
        env["account"]["id"], env["order"]["id"], env["model"]["id"], declared_core_count
    )
    return env


def setup_inspected_core_return(env=None, quantity=10, core_expected_count=10,
                                declared_core_count=10, accepted_core_count=10,
                                **kwargs) -> dict:
    """A core return that has been inspected once and stands in INSPECTED."""
    env = setup_submitted_core_return(env, quantity, core_expected_count,
                                      declared_core_count, **kwargs)
    env["core_return"] = inspect_core_return(
        env["core_return"]["id"], accepted_core_count
    )
    return env


def setup_credited_core_return(env=None, quantity=10, core_expected_count=10,
                               declared_core_count=10, accepted_core_count=10,
                               **kwargs) -> dict:
    """A core return carried through to CREDITED, releasing its deposit."""
    env = setup_inspected_core_return(env, quantity, core_expected_count,
                                      declared_core_count, accepted_core_count, **kwargs)
    env["core_return"] = credit_core_return(env["core_return"]["id"])
    return env


# --------------------------------------------------------------------------
# Tier 4: credit-hold accumulation
# --------------------------------------------------------------------------

def setup_account_in_credit_hold() -> dict:
    """Drive one account into CREDIT_HOLD through the delivery cascade.

    Order A is left SUBMITTED with credit_status HELD by the cascade; order B is
    the DELIVERED order whose 12 promised cores book a 600000 cent liability.
    Returns the environment plus order_a, order_b and line_b.
    """
    env = setup_base_env(
        "IB-IND-2V",
        account_overrides={"name": "Bayou Standby", "storm_priority_rank": 6},
        lot_overrides={"quantity_on_hand": 50},
    )
    order_a = create_order(
        env["account"]["id"], env["warehouse"]["id"], requested_ship_date="2026-08-20"
    )
    add_line(order_a["id"], env["model"]["id"], 1, core_expected_count=0)
    order_a = submit_order(order_a["id"])

    order_b = create_order(
        env["account"]["id"], env["warehouse"]["id"], requested_ship_date="2026-08-06"
    )
    line_b = add_line(order_b["id"], env["model"]["id"], 12, core_expected_count=12)
    order_b = submit_order(order_b["id"])
    order_b = allocate_order(order_b["id"])
    shipment_b = pack_shipment(order_b["id"], env["carrier"]["id"])
    certify_shipment(shipment_b["id"], "APPROVE")
    set_clock("2026-08-05T09:00:00Z")
    dispatch_shipment(shipment_b["id"])
    shipment_b = deliver_shipment(shipment_b["id"])

    env = dict(env)
    env.update({
        "order_a": order_a,
        "order_b": read_order(order_b["id"]),
        "line_b": line_b,
        "shipment_b": shipment_b,
    })
    return env


# --------------------------------------------------------------------------
# Tier 5: disposal manifest accumulation
# --------------------------------------------------------------------------

def setup_manifest_with_credited_return_and_scrapped_lot() -> dict:
    """A DRAFT manifest carrying one credited core return and one expired lot."""
    env = setup_credited_core_return(lot_overrides={"quantity_on_hand": 60})
    env["expired_lot"] = receive_lot(
        env["model"]["id"], env["warehouse"]["id"],
        manufactured_on="2024-01-01", quantity_on_hand=4,
    )
    env["manifest"] = create_disposal_manifest(env["warehouse"]["id"])
    env["manifest"] = attach_core_return_to_manifest(
        env["manifest"]["id"], env["core_return"]["id"], env["manifest"]["version"]
    )
    scrap_lot(env["expired_lot"]["id"], env["manifest"]["id"])
    env["manifest"] = read_manifest(env["manifest"]["id"])
    return env
