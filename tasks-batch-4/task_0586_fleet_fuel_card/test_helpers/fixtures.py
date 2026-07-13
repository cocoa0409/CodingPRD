"""Composite setup helpers.

The harness restarts the API server (empty database) before every individual
test, so every helper here builds its preconditions from scratch using only
PRD-declared endpoints. Helpers use get_success_data() (the lenient validator)
so a broken precondition surfaces as a clear "Setup step failed" message rather
than as a confusing assertion failure deep inside a test.

Identity threading: FleetManager is the one role whose X-User-ID is a real
entity id (PRD §2.1 — it is the id of the acting FleetAccount). Every
ownership-gated call below therefore passes make_fleet_manager_headers(account_id)
with the account actually created in the same helper, never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .constants import TEST_DEFAULTS
from .factories import (
    authorize_transaction_payload,
    create_card_assignment_payload,
    create_driver_payload,
    create_fleet_account_payload,
    create_fuel_card_payload,
    create_ifta_report_payload,
    create_telematics_fault_payload,
    create_vehicle_payload,
    resolution_note_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_fleet_manager_headers

ADMIN = TEST_USERS["program_admin_headers"]
MERCHANT = TEST_USERS["merchant_headers"]
ANALYST = TEST_USERS["fraud_analyst_headers"]
GATEWAY = TEST_USERS["telematics_gateway_headers"]


# --------------------------------------------------------------------------- #
# Primitive steps
# --------------------------------------------------------------------------- #

def set_clock(api, to_iso8601: str) -> dict:
    """PRD §2.4 — drive the server logical clock."""
    return get_success_data(api.set_clock(set_clock_payload(to_iso8601), ADMIN))


def make_fleet_account(api, **overrides) -> dict:
    return get_success_data(
        api.create_fleet_account(create_fleet_account_payload(**overrides), ADMIN)
    )


def make_vehicle(api, account_id, **overrides) -> dict:
    return get_success_data(
        api.create_vehicle(
            create_vehicle_payload(account_id, **overrides),
            make_fleet_manager_headers(account_id),
        )
    )


def make_driver(api, account_id, **overrides) -> dict:
    return get_success_data(
        api.create_driver(
            create_driver_payload(account_id, **overrides),
            make_fleet_manager_headers(account_id),
        )
    )


def make_fuel_card(api, account_id, **overrides) -> dict:
    return get_success_data(
        api.create_fuel_card(
            create_fuel_card_payload(account_id, **overrides),
            make_fleet_manager_headers(account_id),
        )
    )


def activate_fuel_card(api, account_id, card_id) -> dict:
    return get_success_data(
        api.activate_fuel_card(card_id, make_fleet_manager_headers(account_id))
    )


def suspend_fuel_card(api, account_id, card_id) -> dict:
    return get_success_data(
        api.suspend_fuel_card(card_id, make_fleet_manager_headers(account_id))
    )


def cancel_fuel_card(api, account_id, card_id) -> dict:
    return get_success_data(
        api.cancel_fuel_card(card_id, make_fleet_manager_headers(account_id))
    )


def make_card_assignment(api, account_id, card_id, vehicle_id, driver_id,
                         expected_card_version, **overrides) -> dict:
    return get_success_data(
        api.create_card_assignment(
            create_card_assignment_payload(
                card_id, vehicle_id, driver_id, expected_card_version, **overrides
            ),
            make_fleet_manager_headers(account_id),
        )
    )


def authorize_fill(api, card_id, **overrides) -> dict:
    """PRD §3.4 — a Merchant terminal authorizes a purchase."""
    return get_success_data(
        api.authorize_transaction(authorize_transaction_payload(card_id, **overrides), MERCHANT)
    )


def capture_fill(api, transaction_id) -> dict:
    return get_success_data(api.capture_transaction(transaction_id, MERCHANT))


def settle_fill(api, transaction_id) -> dict:
    return get_success_data(api.settle_transaction(transaction_id, MERCHANT))


def void_fill(api, transaction_id) -> dict:
    return get_success_data(api.void_transaction(transaction_id, MERCHANT))


def read_account(api, account_id) -> dict:
    return get_success_data(api.get_fleet_account(account_id, ADMIN))


def read_transaction(api, transaction_id) -> dict:
    return get_success_data(api.get_transaction(transaction_id, MERCHANT))


def read_card(api, account_id, card_id) -> dict:
    return get_success_data(
        api.get_fuel_card(card_id, make_fleet_manager_headers(account_id))
    )


def read_vehicle(api, account_id, vehicle_id) -> dict:
    return get_success_data(
        api.get_vehicle(vehicle_id, make_fleet_manager_headers(account_id))
    )


def read_assignment(api, account_id, assignment_id) -> dict:
    return get_success_data(
        api.get_card_assignment(assignment_id, make_fleet_manager_headers(account_id))
    )


def read_alert(api, alert_id) -> dict:
    return get_success_data(api.get_fraud_alert(alert_id, ANALYST))


def read_fault(api, fault_id) -> dict:
    return get_success_data(api.get_telematics_fault(fault_id, GATEWAY))


def read_report(api, report_id) -> dict:
    return get_success_data(api.get_ifta_report(report_id, ADMIN))


def make_telematics_fault(api, vehicle_id, **overrides) -> dict:
    """PRD §3.7 — the TelematicsGateway reports a fault."""
    return get_success_data(
        api.create_telematics_fault(
            create_telematics_fault_payload(vehicle_id, **overrides), GATEWAY
        )
    )


def make_critical_fault(api, vehicle_id, window_start, window_end, **overrides) -> dict:
    return make_telematics_fault(
        api,
        vehicle_id,
        severity="CRITICAL",
        maintenance_window_start=window_start,
        maintenance_window_end=window_end,
        **overrides,
    )


def make_ifta_report(api, account_id, quarter="2026-Q1") -> dict:
    return get_success_data(
        api.create_ifta_report(create_ifta_report_payload(account_id, quarter), ADMIN)
    )


def file_ifta_report(api, report_id) -> dict:
    return get_success_data(api.file_ifta_report(report_id, ADMIN))


# --------------------------------------------------------------------------- #
# Fraud-alert helpers
# --------------------------------------------------------------------------- #

def find_alert_for_transaction(api, transaction_id) -> dict:
    """The system creates the alert; tests locate it through the list endpoint
    (PRD §3.6 — alerts are listed by transaction)."""
    resp = api.list_fraud_alerts(ANALYST, params={"transaction_id": transaction_id})
    body = resp.json()
    assert 200 <= resp.status_code < 300, f"Setup step failed listing alerts: {resp.text}"
    alerts = body["data"]
    assert alerts, f"Setup step failed: no fraud alert was created for transaction {transaction_id}"
    return alerts[0]


def investigate_alert(api, alert_id) -> dict:
    return get_success_data(api.investigate_fraud_alert(alert_id, ANALYST))


def confirm_alert(api, alert_id, note="confirmed") -> dict:
    return get_success_data(
        api.confirm_fraud_alert(alert_id, ANALYST, resolution_note_payload(note))
    )


def dismiss_alert(api, alert_id, note="false positive") -> dict:
    return get_success_data(
        api.dismiss_fraud_alert(alert_id, ANALYST, resolution_note_payload(note))
    )


def reopen_alert(api, alert_id, note="need another look") -> dict:
    return get_success_data(
        api.reopen_fraud_alert(alert_id, ANALYST, resolution_note_payload(note))
    )


# --------------------------------------------------------------------------- #
# Tier 1–3: the canonical "ready to pump" scenario
# --------------------------------------------------------------------------- #

def setup_fueling_scenario(
    api,
    clock=TEST_DEFAULTS["CLOCK"],
    account_overrides=None,
    vehicle_overrides=None,
    driver_overrides=None,
    card_overrides=None,
    assignment_overrides=None,
    activate_card=True,
    create_assignment=True,
) -> dict:
    """Fleet account -> vehicle -> driver -> fuel card -> (activate) -> assignment.

    This is the preamble that every purchase-side claim needs: an authorization
    requires an ACTIVE card whose ACTIVE assignment covers `purchased_at`
    (PRD §3.4), and an assignment requires a card version for the OCC guard
    (PRD §3.3).

    Returns a dict with keys: account, vehicle, driver, card, assignment (None
    when create_assignment is False), and fm (the FleetManager headers bound to
    this account's id).
    """
    if clock is not None:
        set_clock(api, clock)

    account = make_fleet_account(api, **(account_overrides or {}))
    account_id = account["id"]
    fm = make_fleet_manager_headers(account_id)

    vehicle = make_vehicle(api, account_id, **(vehicle_overrides or {}))
    driver = make_driver(api, account_id, **(driver_overrides or {}))
    card = make_fuel_card(api, account_id, **(card_overrides or {}))

    if activate_card:
        card = activate_fuel_card(api, account_id, card["id"])

    assignment = None
    if create_assignment:
        assignment = make_card_assignment(
            api,
            account_id,
            card["id"],
            vehicle["id"],
            driver["id"],
            card["version"],
            **(assignment_overrides or {}),
        )

    return {
        "account": account,
        "vehicle": vehicle,
        "driver": driver,
        "card": card,
        "assignment": assignment,
        "fm": fm,
    }


# --------------------------------------------------------------------------- #
# Tier 4: accumulation / threshold targeting
# --------------------------------------------------------------------------- #

def setup_captured_fills(api, fills, clock=TEST_DEFAULTS["CLOCK"], **scenario_kwargs) -> dict:
    """Build the canonical scenario and then authorize + capture one fill per
    entry of `fills` (each entry a dict of authorize overrides), driving the
    account's month-to-date gallon total (PRD §3.5) to a chosen point on the
    rebate-tier schedule.

    Returns the scenario dict plus a "transactions" list in creation order.
    """
    scenario = setup_fueling_scenario(api, clock=clock, **scenario_kwargs)
    card_id = scenario["card"]["id"]
    transactions = []
    for fill in fills:
        txn = authorize_fill(api, card_id, **fill)
        transactions.append(capture_fill(api, txn["id"]))
    scenario["transactions"] = transactions
    return scenario


def setup_authorized_fills(api, fills, clock=TEST_DEFAULTS["CLOCK"], **scenario_kwargs) -> dict:
    """Build the canonical scenario and authorize (but do not capture) one fill
    per entry of `fills`. Each fill's hold is live against the account's
    available credit (PRD §3.4).

    Returns the scenario dict plus a "transactions" list in creation order.
    """
    scenario = setup_fueling_scenario(api, clock=clock, **scenario_kwargs)
    card_id = scenario["card"]["id"]
    scenario["transactions"] = [
        authorize_fill(api, card_id, **fill) for fill in fills
    ]
    return scenario


def setup_settled_fills(api, fills, clock="2026-02-10T12:00:00Z", **scenario_kwargs) -> dict:
    """Authorize -> capture -> settle one fill per entry of `fills`, where each
    entry is a dict of authorize overrides (gallons, odometer, jurisdiction...).

    Settled in-period transactions are the sole input to IFTA generation
    (PRD §3.9), so this is the fixture behind every IFTA claim.
    """
    scenario = setup_fueling_scenario(api, clock=clock, **scenario_kwargs)
    card_id = scenario["card"]["id"]
    transactions = []
    for fill in fills:
        txn = authorize_fill(api, card_id, **fill)
        capture_fill(api, txn["id"])
        transactions.append(settle_fill(api, txn["id"]))
    scenario["transactions"] = transactions
    return scenario


def setup_multi_assignment_scenario(api, clock="2026-05-15T12:00:00Z",
                                    account_overrides=None) -> dict:
    """Two ACTIVE vehicles, two drivers and two ACTIVE fuel cards on one account —
    enough independent resources to exercise the assignment guards (driver
    double-booking, and the card-version OCC guard) each in isolation, without a
    second guard also being violated.

    Returns keys: account, fm, vehicles (list of 2), drivers (list of 2),
    cards (list of 2, both ACTIVE with their post-activation version).
    """
    set_clock(api, clock)
    account = make_fleet_account(api, **(account_overrides or {}))
    account_id = account["id"]

    vehicles = [make_vehicle(api, account_id, plate=f"VMA{i}") for i in (1, 2)]
    drivers = [
        make_driver(api, account_id, full_name=f"Driver {i}", pin=f"{i}{i}{i}{i}")
        for i in (1, 2)
    ]
    cards = []
    for i in (1, 2):
        card = make_fuel_card(api, account_id, last4=f"020{i}")
        cards.append(activate_fuel_card(api, account_id, card["id"]))

    return {
        "account": account,
        "fm": make_fleet_manager_headers(account_id),
        "vehicles": vehicles,
        "drivers": drivers,
        "cards": cards,
    }


# --------------------------------------------------------------------------- #
# Tier 5: fraud / cascade entry points
# --------------------------------------------------------------------------- #

def setup_flagged_transaction(api, tank_capacity_gallons=100, gallons=200,
                              clock=TEST_DEFAULTS["CLOCK"], odometer=100,
                              capture_txn=False, **scenario_kwargs) -> dict:
    """Authorize a fill whose gallons exceed the vehicle's tank capacity, which
    (PRD §3.4) still authorizes but sets review_status FLAGGED and opens a
    FraudAlert. Optionally captures the transaction first so that a later cascade
    has an accrued rebate to reverse.

    Returns the scenario dict plus "transaction" and "alert".
    """
    vehicle_overrides = dict(scenario_kwargs.pop("vehicle_overrides", None) or {})
    vehicle_overrides.setdefault("tank_capacity_gallons", tank_capacity_gallons)
    vehicle_overrides.setdefault("expected_mpg_min", 1)
    vehicle_overrides.setdefault("expected_mpg_max", 50)

    scenario = setup_fueling_scenario(
        api, clock=clock, vehicle_overrides=vehicle_overrides, **scenario_kwargs
    )
    txn = authorize_fill(api, scenario["card"]["id"], gallons=gallons, odometer=odometer)
    if capture_txn:
        txn = capture_fill(api, txn["id"])
    scenario["transaction"] = txn
    scenario["alert"] = find_alert_for_transaction(api, txn["id"])
    return scenario


def setup_investigating_alert(api, **kwargs) -> dict:
    """A flagged transaction whose alert has been moved OPEN -> INVESTIGATING,
    the only state from which confirm and dismiss are permitted (PRD §3.6)."""
    scenario = setup_flagged_transaction(api, **kwargs)
    scenario["alert"] = investigate_alert(api, scenario["alert"]["id"])
    return scenario


def setup_cascade_scenario(api, clock=TEST_DEFAULTS["CLOCK"]) -> dict:
    """The deepest cascade's precondition: one healthy CAPTURED fill that has
    accrued a rebate, plus one over-tank fill that opened a FraudAlert now moved
    to INVESTIGATING.

    Confirming that alert (PRD §3.6) suspends the card, which voids BOTH open
    transactions, which releases their holds and reverses the accrued rebate.

    Returns keys: account, vehicle, driver, card, assignment, fm, normal_txn,
    flagged_txn, alert.
    """
    scenario = setup_fueling_scenario(
        api,
        clock=clock,
        account_overrides={"company_name": "Cascade Fleet"},
        vehicle_overrides={
            "tank_capacity_gallons": 100, "expected_mpg_min": 1,
            "expected_mpg_max": 50, "starting_odometer": 10000,
        },
        card_overrides={"last4": "7777"},
    )
    card_id = scenario["card"]["id"]

    normal = authorize_fill(api, card_id, gallons=100, odometer=10100)
    scenario["normal_txn"] = capture_fill(api, normal["id"])

    flagged = authorize_fill(api, card_id, gallons=200, odometer=10200)
    scenario["flagged_txn"] = flagged
    scenario["alert"] = investigate_alert(api, find_alert_for_transaction(api, flagged["id"])["id"])
    return scenario


def setup_confirmed_alert(api, **kwargs) -> dict:
    """A flagged transaction whose alert has been confirmed — the root of the
    FraudAlert -> FuelCard -> Transaction -> FleetAccount cascade (PRD §3.6)."""
    scenario = setup_investigating_alert(api, **kwargs)
    scenario["alert"] = confirm_alert(api, scenario["alert"]["id"])
    return scenario
