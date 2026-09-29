"""Composite setup helpers.

Most interesting claims in this API need the system driven through five to
fifteen calls before the behaviour under test is even reachable: a vault, a
depositor, a machine, an intake ticket, sealed bags, a custody chain, a booked
counting window, an opened bag, a started session, a completed count and its
cascade. These helpers encapsulate those preambles.

Every helper uses only PRD-declared endpoints and the lenient success validator
so a broken precondition surfaces as a clear setup failure.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    approve_claim_payload,
    approve_coin_order_payload,
    coin_order_line,
    complete_count_session_payload,
    correction_note_payload,
    confirm_fed_deposit_payload,
    create_coin_order_payload,
    create_count_session_payload,
    create_counterfeit_report_payload,
    create_counting_machine_payload,
    create_customer_account_payload,
    create_deposit_ticket_payload,
    create_discrepancy_claim_payload,
    create_fed_deposit_payload,
    create_sealed_bag_payload,
    create_vault_payload,
    custody_event_payload,
    deny_claim_payload,
    hold_payload,
    inventory_adjustment_payload,
    lot_entry,
    release_coin_order_payload,
    request_info_payload,
    resubmit_claim_payload,
    return_coin_order_payload,
    reverse_provisional_credit_payload,
    set_clock_payload,
    vault_posture_payload,
)
from .test_users import (
    CARRIER_1,
    COMPLIANCE_1,
    FED_AGENT_1,
    MANAGER_1,
    TELLER_1,
    TELLER_2,
    make_carrier_headers,
    make_compliance_headers,
    make_customer_account_holder_headers,
    make_fed_agent_headers,
    make_manager_headers,
    make_teller_headers,
)

DEFAULT_WINDOW_START = "2026-08-03T09:00:00Z"
DEFAULT_WINDOW_END = "2026-08-03T10:00:00Z"


# ─── Window helpers ───────────────────────────────────────────────────────

def window_pair(index: int = 0, day: str = "2026-08-03", base_hour: int = 9) -> tuple:
    """Non-colliding counting windows on one machine.

    Consecutive indices are two hours apart, which comfortably clears the
    quarter-hour cleaning buffer appended to each window's end.
    """
    start_hour = base_hour + index * 2
    return (f"{day}T{start_hour:02d}:00:00Z", f"{day}T{start_hour + 1:02d}:00:00Z")


# ─── Logical clock ────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock and return the projection it reports."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), make_manager_headers(MANAGER_1))
    )


# ─── Tier 1: single-row creation ──────────────────────────────────────────

def create_vault(manager_user_id: str = MANAGER_1, **overrides) -> dict:
    return get_success_data(
        api_client.create_vault(create_vault_payload(**overrides), make_manager_headers(manager_user_id))
    )


def create_account(manager_user_id: str = MANAGER_1, **overrides) -> dict:
    return get_success_data(
        api_client.create_customer_account(
            create_customer_account_payload(**overrides), make_manager_headers(manager_user_id)
        )
    )


def create_machine(vault_id: str, manager_user_id: str = MANAGER_1, **overrides) -> dict:
    return get_success_data(
        api_client.create_counting_machine(
            create_counting_machine_payload(vault_id, **overrides),
            make_manager_headers(manager_user_id),
        )
    )


def create_ticket(
    customer_account_id: str, vault_id: str, carrier_user_id: str = CARRIER_1, **overrides
) -> dict:
    return get_success_data(
        api_client.create_deposit_ticket(
            create_deposit_ticket_payload(customer_account_id, vault_id, **overrides),
            make_carrier_headers(carrier_user_id),
        )
    )


def create_bag(deposit_ticket_id: str, carrier_user_id: str = CARRIER_1, **overrides) -> dict:
    return get_success_data(
        api_client.create_sealed_bag(
            create_sealed_bag_payload(deposit_ticket_id, **overrides),
            make_carrier_headers(carrier_user_id),
        )
    )


# ─── Reads ────────────────────────────────────────────────────────────────

def read_vault(vault_id: str) -> dict:
    return get_success_data(api_client.get_vault(vault_id, make_manager_headers(MANAGER_1)))


def read_account(account_id: str) -> dict:
    return get_success_data(
        api_client.get_customer_account(account_id, make_manager_headers(MANAGER_1))
    )


def read_ticket(ticket_id: str) -> dict:
    return get_success_data(
        api_client.get_deposit_ticket(ticket_id, make_manager_headers(MANAGER_1))
    )


def read_bag(bag_id: str) -> dict:
    return get_success_data(api_client.get_sealed_bag(bag_id, make_manager_headers(MANAGER_1)))


def read_session(session_id: str) -> dict:
    return get_success_data(
        api_client.get_count_session(session_id, make_manager_headers(MANAGER_1))
    )


def read_report(report_id: str) -> dict:
    return get_success_data(
        api_client.get_counterfeit_report(report_id, make_manager_headers(MANAGER_1))
    )


def read_claim(claim_id: str) -> dict:
    return get_success_data(
        api_client.get_discrepancy_claim(claim_id, make_manager_headers(MANAGER_1))
    )


def read_fed_deposit(fed_deposit_id: str) -> dict:
    return get_success_data(
        api_client.get_fed_deposit(fed_deposit_id, make_manager_headers(MANAGER_1))
    )


def read_coin_order(order_id: str) -> dict:
    return get_success_data(api_client.get_coin_order(order_id, make_manager_headers(MANAGER_1)))


def read_inventory(vault_id: str, denomination: Optional[str] = None) -> List[dict]:
    params = {"denomination": denomination} if denomination else None
    body = api_client.list_vault_inventory(vault_id, make_manager_headers(MANAGER_1), params=params)
    return get_success_data(body)


def read_inventory_position(vault_id: str, denomination: str) -> Optional[dict]:
    for position in read_inventory(vault_id):
        if position["denomination"] == denomination:
            return position
    return None


def read_coin_order_lines(order_id: str) -> List[dict]:
    return get_success_data(
        api_client.list_coin_order_lines(order_id, make_manager_headers(MANAGER_1))
    )


def read_session_lots(session_id: str, category: Optional[str] = None) -> List[dict]:
    params = {"category": category} if category else None
    return get_success_data(
        api_client.list_session_fitness_lots(
            session_id, make_manager_headers(MANAGER_1), params=params
        )
    )


def read_bag_version(bag_id: str) -> int:
    return read_bag(bag_id)["version"]


def read_vault_version(vault_id: str) -> int:
    return read_vault(vault_id)["version"]


# ─── Tier 2: custody chain ────────────────────────────────────────────────

def add_custody_hop(
    bag_id: str,
    event_type: str,
    observed_seal_number: str,
    location_code: str = "SITE-CUST",
    headers: Optional[dict] = None,
) -> dict:
    if headers is None:
        headers = (
            make_carrier_headers(CARRIER_1)
            if event_type in ("PICKUP", "TRANSFER")
            else make_teller_headers(TELLER_1)
        )
    return get_success_data(
        api_client.create_custody_event(
            bag_id, custody_event_payload(event_type, observed_seal_number, location_code), headers
        )
    )


def deliver_bag_to_vault(bag_id: str, seal_number: str, location_code: str = "VAULT-DOCK") -> None:
    """PICKUP then VAULT_RECEIPT: the bag ends at custody_status VAULT_RECEIVED."""
    add_custody_hop(bag_id, "PICKUP", seal_number, "SITE-CUST")
    add_custody_hop(bag_id, "VAULT_RECEIPT", seal_number, location_code)


def open_bag(bag_id: str, seal_number: str, location_code: str = "VAULT-FLOOR") -> dict:
    """OPEN hop — legal only once a SCHEDULED session exists on the bag."""
    return add_custody_hop(bag_id, "OPEN", seal_number, location_code)


# ─── Tier 3: ticket lifecycle ─────────────────────────────────────────────

def verify_ticket(ticket_id: str, teller_user_id: str = TELLER_1) -> dict:
    return get_success_data(
        api_client.verify_deposit_ticket(ticket_id, make_teller_headers(teller_user_id))
    )


def extend_provisional_credit(ticket_id: str, teller_user_id: str = TELLER_1) -> dict:
    return get_success_data(
        api_client.extend_provisional_credit(ticket_id, make_teller_headers(teller_user_id))
    )


def reverse_provisional_credit(ticket_id: str, reason: Optional[str] = None) -> dict:
    payload = reverse_provisional_credit_payload(reason) if reason else reverse_provisional_credit_payload()
    return get_success_data(
        api_client.reverse_provisional_credit(ticket_id, payload, make_manager_headers(MANAGER_1))
    )


def hold_ticket(ticket_id: str, hold_reason: Optional[str] = None) -> dict:
    payload = hold_payload(hold_reason) if hold_reason else hold_payload()
    return get_success_data(
        api_client.hold_deposit_ticket(ticket_id, payload, make_manager_headers(MANAGER_1))
    )


def settle_ticket(ticket_id: str, manager_user_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.settle_deposit_ticket(ticket_id, make_manager_headers(manager_user_id))
    )


def set_posture(vault_id: str, posture: str) -> dict:
    return get_success_data(
        api_client.set_vault_posture(
            vault_id, vault_posture_payload(posture), make_manager_headers(MANAGER_1)
        )
    )


def adjust_inventory(vault_id: str, denomination: str, delta_boxes: int) -> dict:
    return get_success_data(
        api_client.adjust_vault_inventory(
            vault_id,
            inventory_adjustment_payload(denomination, delta_boxes),
            make_manager_headers(MANAGER_1),
        )
    )


# ─── Tier 4: counting sessions ────────────────────────────────────────────

def schedule_session(
    bag_id: str,
    machine_id: str,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    operator_user_id: str = TELLER_1,
    expected_sealed_bag_version: Optional[int] = None,
) -> dict:
    if expected_sealed_bag_version is None:
        expected_sealed_bag_version = read_bag_version(bag_id)
    return get_success_data(
        api_client.create_count_session(
            create_count_session_payload(
                bag_id, machine_id, expected_sealed_bag_version, window_start, window_end
            ),
            make_teller_headers(operator_user_id),
        )
    )


def start_session(session_id: str, teller_user_id: str = TELLER_1) -> dict:
    return get_success_data(
        api_client.start_count_session(session_id, make_teller_headers(teller_user_id))
    )


def complete_session(
    session_id: str,
    counted_amount_cents: int,
    counted_note_count: int,
    lots: List[dict],
    counted_coin_weight_grams: int = 0,
    verifier_user_id: str = TELLER_2,
) -> dict:
    return get_success_data(
        api_client.complete_count_session(
            session_id,
            complete_count_session_payload(
                counted_amount_cents, counted_note_count, lots, counted_coin_weight_grams
            ),
            make_teller_headers(verifier_user_id),
        )
    )


def default_lots(counted_amount_cents: int, counted_note_count: int) -> List[dict]:
    """One FIT lot whose face value and note count reconcile with the totals."""
    if counted_note_count == 0:
        assert counted_amount_cents == 0, (
            "a lot breakdown cannot reconcile a non-zero amount with zero notes"
        )
        return []
    assert counted_amount_cents % counted_note_count == 0, (
        "default_lots needs a whole-cent denomination; pass explicit lots instead"
    )
    return [lot_entry("FIT", counted_amount_cents // counted_note_count, counted_note_count)]


def count_bag(
    bag_id: str,
    seal_number: str,
    machine_id: str,
    counted_amount_cents: int,
    counted_note_count: int,
    lots: Optional[List[dict]] = None,
    counted_coin_weight_grams: int = 0,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    operator_user_id: str = TELLER_1,
    verifier_user_id: str = TELLER_2,
    location_code: str = "VAULT-FLOOR",
) -> dict:
    """Schedule → open the bag → start → complete. Returns the COMPLETED session."""
    if lots is None:
        lots = default_lots(counted_amount_cents, counted_note_count)
    session = schedule_session(
        bag_id, machine_id, window_start, window_end, operator_user_id=operator_user_id
    )
    open_bag(bag_id, seal_number, location_code)
    start_session(session["id"], teller_user_id=operator_user_id)
    return complete_session(
        session["id"],
        counted_amount_cents,
        counted_note_count,
        lots,
        counted_coin_weight_grams,
        verifier_user_id=verifier_user_id,
    )


# ─── Tier 5: whole-scenario composites ────────────────────────────────────

def setup_processing_center(
    tier: str = "STANDARD",
    account_status: str = "ACTIVE",
    machine_type: str = "CURRENCY_SORTER",
    machine_status: str = "AVAILABLE",
    pickup_concurrency_limit: Optional[int] = None,
    with_machine: bool = True,
) -> Dict[str, dict]:
    """A vault, a depositor account and (optionally) one counting machine."""
    vault_overrides = {}
    if pickup_concurrency_limit is not None:
        vault_overrides["pickup_concurrency_limit"] = pickup_concurrency_limit
    vault = create_vault(**vault_overrides)
    account = create_account(tier=tier, status=account_status)
    scenario = {
        "vault": vault,
        "account": account,
        "customer_headers": make_customer_account_holder_headers(account["id"]),
    }
    if with_machine:
        scenario["machine"] = create_machine(
            vault["id"], machine_type=machine_type, status=machine_status
        )
    return scenario


def setup_intake_ticket(
    bag_specs: Optional[List[dict]] = None,
    declared_bag_count: Optional[int] = None,
    deliver: bool = True,
    **center_overrides,
) -> Dict[str, object]:
    """Vault + account + machine + an INTAKE ticket carrying registered bags.

    `bag_specs` entries are overrides for the sealed-bag payload. When
    `deliver` is true every bag is walked PICKUP → VAULT_RECEIPT.
    """
    if bag_specs is None:
        bag_specs = [{}]
    scenario = setup_processing_center(**center_overrides)
    ticket = create_ticket(
        scenario["account"]["id"],
        scenario["vault"]["id"],
        declared_bag_count=declared_bag_count if declared_bag_count is not None else len(bag_specs),
    )
    bags = []
    for spec in bag_specs:
        bag = create_bag(ticket["id"], **spec)
        if deliver:
            deliver_bag_to_vault(bag["id"], bag["seal_number"])
        bags.append(bag)
    scenario["ticket"] = ticket
    scenario["bags"] = bags
    scenario["bag"] = bags[0] if bags else None
    return scenario


def setup_verified_ticket(
    bag_specs: Optional[List[dict]] = None,
    credit_branch: Optional[str] = None,
    **overrides,
) -> Dict[str, object]:
    """An intake ticket verified into VERIFIED, optionally pushed onto one branch
    of the fork: `credit_branch="provisional"` or `credit_branch="hold"`."""
    scenario = setup_intake_ticket(bag_specs=bag_specs, **overrides)
    scenario["ticket"] = verify_ticket(scenario["ticket"]["id"])
    if credit_branch == "provisional":
        scenario["ticket"] = extend_provisional_credit(scenario["ticket"]["id"])
    elif credit_branch == "hold":
        scenario["ticket"] = hold_ticket(scenario["ticket"]["id"])
    return scenario


def setup_counted_bag(
    declared_amount_cents: int = 100_000,
    declared_note_count: int = 100,
    declared_coin_weight_grams: int = 0,
    counted_amount_cents: int = 100_000,
    counted_note_count: int = 100,
    counted_coin_weight_grams: int = 0,
    lots: Optional[List[dict]] = None,
    bag_type: str = "CURRENCY",
    credit_branch: Optional[str] = None,
    operator_user_id: str = TELLER_1,
    verifier_user_id: str = TELLER_2,
    **overrides,
) -> Dict[str, object]:
    """One ticket, one bag, counted through to count_status COUNTED.

    Returns vault, account, machine, ticket (re-read after the cascade), bag
    (re-read), session and the account holder's headers.
    """
    scenario = setup_verified_ticket(
        bag_specs=[
            {
                "bag_type": bag_type,
                "declared_amount_cents": declared_amount_cents,
                "declared_note_count": declared_note_count,
                "declared_coin_weight_grams": declared_coin_weight_grams,
            }
        ],
        credit_branch=credit_branch,
        **overrides,
    )
    bag = scenario["bags"][0]
    session = count_bag(
        bag["id"],
        bag["seal_number"],
        scenario["machine"]["id"],
        counted_amount_cents,
        counted_note_count,
        lots=lots,
        counted_coin_weight_grams=counted_coin_weight_grams,
        operator_user_id=operator_user_id,
        verifier_user_id=verifier_user_id,
    )
    scenario["session"] = session
    scenario["bag"] = read_bag(bag["id"])
    scenario["bags"] = [scenario["bag"]]
    scenario["ticket"] = read_ticket(scenario["ticket"]["id"])
    return scenario


def setup_two_counted_bags(
    first: dict,
    second: dict,
    credit_branch: Optional[str] = None,
    complete_second: bool = True,
    **overrides,
) -> Dict[str, object]:
    """A two-bag ticket where the first bag is fully counted and the second is
    either left IN_PROGRESS (``complete_second=False``) or counted too.

    `first` / `second` are dicts carrying declared_amount_cents,
    declared_note_count, counted_amount_cents, counted_note_count and optional
    lots / bag_type / counted_coin_weight_grams.
    """
    def bag_spec(spec):
        return {
            "bag_type": spec.get("bag_type", "CURRENCY"),
            "declared_amount_cents": spec["declared_amount_cents"],
            "declared_note_count": spec.get("declared_note_count", 0),
            "declared_coin_weight_grams": spec.get("declared_coin_weight_grams", 0),
        }

    scenario = setup_verified_ticket(
        bag_specs=[bag_spec(first), bag_spec(second)],
        credit_branch=credit_branch,
        **overrides,
    )
    machine_id = scenario["machine"]["id"]
    bag_one, bag_two = scenario["bags"]

    first_window = window_pair(0)
    session_one = count_bag(
        bag_one["id"],
        bag_one["seal_number"],
        machine_id,
        first["counted_amount_cents"],
        first.get("counted_note_count", 0),
        lots=first.get("lots"),
        counted_coin_weight_grams=first.get("counted_coin_weight_grams", 0),
        window_start=first_window[0],
        window_end=first_window[1],
    )

    second_window = window_pair(1)
    session_two = schedule_session(
        bag_two["id"], machine_id, second_window[0], second_window[1]
    )
    open_bag(bag_two["id"], bag_two["seal_number"])
    start_session(session_two["id"])
    if complete_second:
        session_two = complete_session(
            session_two["id"],
            second["counted_amount_cents"],
            second.get("counted_note_count", 0),
            second.get("lots")
            or default_lots(second["counted_amount_cents"], second.get("counted_note_count", 0)),
            second.get("counted_coin_weight_grams", 0),
        )

    scenario["sessions"] = [session_one, session_two]
    scenario["session"] = session_one
    scenario["second_session"] = session_two
    scenario["second_window"] = second_window
    scenario["bags"] = [read_bag(bag_one["id"]), read_bag(bag_two["id"])]
    scenario["bag"] = scenario["bags"][0]
    scenario["second_bag"] = scenario["bags"][1]
    scenario["ticket"] = read_ticket(scenario["ticket"]["id"])
    return scenario


def setup_bag_with_suspect_lot(
    declared_amount_cents: int = 100_000,
    fit_note_count: int = 8,
    suspect_note_count: int = 2,
    denomination_cents: int = 10_000,
    credit_branch: Optional[str] = None,
    **overrides,
) -> Dict[str, object]:
    """A counted bag sorted into one FIT lot and one COUNTERFEIT_SUSPECT lot."""
    note_count = fit_note_count + suspect_note_count
    lots = [
        lot_entry("FIT", denomination_cents, fit_note_count),
        lot_entry("COUNTERFEIT_SUSPECT", denomination_cents, suspect_note_count),
    ]
    scenario = setup_counted_bag(
        declared_amount_cents=declared_amount_cents,
        declared_note_count=note_count,
        counted_amount_cents=denomination_cents * note_count,
        counted_note_count=note_count,
        lots=lots,
        credit_branch=credit_branch,
        **overrides,
    )
    session_id = scenario["session"]["id"]
    scenario["fit_lot"] = read_session_lots(session_id, category="FIT")[0]
    scenario["suspect_lot"] = read_session_lots(session_id, category="COUNTERFEIT_SUSPECT")[0]
    return scenario


def setup_bag_with_fit_and_unfit_lots(
    declared_amount_cents: int = 100_000,
    fit_note_count: int = 8,
    unfit_note_count: int = 2,
    denomination_cents: int = 10_000,
    **overrides,
) -> Dict[str, object]:
    """A counted bag sorted into one FIT lot and one UNFIT lot — both eligible
    for a cash letter."""
    note_count = fit_note_count + unfit_note_count
    lots = [
        lot_entry("FIT", denomination_cents, fit_note_count),
        lot_entry("UNFIT", denomination_cents, unfit_note_count),
    ]
    scenario = setup_counted_bag(
        declared_amount_cents=declared_amount_cents,
        declared_note_count=note_count,
        counted_amount_cents=denomination_cents * note_count,
        counted_note_count=note_count,
        lots=lots,
        **overrides,
    )
    session_id = scenario["session"]["id"]
    scenario["fit_lot"] = read_session_lots(session_id, category="FIT")[0]
    scenario["unfit_lot"] = read_session_lots(session_id, category="UNFIT")[0]
    return scenario


def draft_counterfeit_report(
    fitness_lot_id: str,
    denomination_cents: int,
    note_count: int,
    officer_user_id: str = COMPLIANCE_1,
) -> dict:
    return get_success_data(
        api_client.create_counterfeit_report(
            create_counterfeit_report_payload(fitness_lot_id, denomination_cents, note_count),
            make_compliance_headers(officer_user_id),
        )
    )


def submit_counterfeit_report(report_id: str, officer_user_id: str = COMPLIANCE_1) -> dict:
    return get_success_data(
        api_client.submit_counterfeit_report(report_id, make_compliance_headers(officer_user_id))
    )


def return_counterfeit_report(report_id: str, note: Optional[str] = None) -> dict:
    payload = correction_note_payload(note) if note else correction_note_payload()
    return get_success_data(
        api_client.return_counterfeit_report_for_correction(
            report_id, payload, make_compliance_headers(COMPLIANCE_1)
        )
    )


def setup_drafted_counterfeit_report(
    denomination_cents: int = 10_000,
    suspect_note_count: int = 2,
    report_note_count: Optional[int] = None,
    **overrides,
) -> Dict[str, object]:
    """A counted bag with a COUNTERFEIT_SUSPECT lot and a DRAFT report on it."""
    scenario = setup_bag_with_suspect_lot(
        denomination_cents=denomination_cents, suspect_note_count=suspect_note_count, **overrides
    )
    scenario["report"] = draft_counterfeit_report(
        scenario["suspect_lot"]["id"],
        denomination_cents,
        report_note_count if report_note_count is not None else suspect_note_count,
    )
    return scenario


def setup_submitted_counterfeit_report(**overrides) -> Dict[str, object]:
    """The seizure cascade has already fired: lot SEIZED, value removed."""
    scenario = setup_drafted_counterfeit_report(**overrides)
    scenario["report"] = submit_counterfeit_report(scenario["report"]["id"])
    return scenario


# ─── Cash letters ─────────────────────────────────────────────────────────

def prepare_cash_letter(vault_id: str, fitness_lot_ids: List[str], **overrides) -> dict:
    return get_success_data(
        api_client.create_fed_deposit(
            create_fed_deposit_payload(vault_id, fitness_lot_ids, **overrides),
            make_manager_headers(MANAGER_1),
        )
    )


def ship_cash_letter(fed_deposit_id: str) -> dict:
    return get_success_data(
        api_client.submit_fed_deposit(fed_deposit_id, make_manager_headers(MANAGER_1))
    )


def confirm_cash_letter(fed_deposit_id: str, credited_total_cents: int) -> dict:
    return get_success_data(
        api_client.confirm_fed_deposit(
            fed_deposit_id,
            confirm_fed_deposit_payload(credited_total_cents),
            make_fed_agent_headers(FED_AGENT_1),
        )
    )


def setup_prepared_cash_letter(**overrides) -> Dict[str, object]:
    """A PREPARED cash letter holding one eligible FIT lot."""
    scenario = setup_bag_with_fit_and_unfit_lots(**overrides)
    scenario["fed_deposit"] = prepare_cash_letter(
        scenario["vault"]["id"], [scenario["fit_lot"]["id"]]
    )
    return scenario


def setup_shipped_cash_letter(**overrides) -> Dict[str, object]:
    """A SUBMITTED cash letter whose attached FIT lot has moved to DEPOSITED."""
    scenario = setup_prepared_cash_letter(**overrides)
    scenario["fed_deposit"] = ship_cash_letter(scenario["fed_deposit"]["id"])
    return scenario


# ─── Discrepancy claims ───────────────────────────────────────────────────

def file_claim(
    bag_id: str,
    account_id: str,
    claimed_amount_cents: int,
    claim_type: str = "COUNT_VARIANCE",
) -> dict:
    return get_success_data(
        api_client.create_discrepancy_claim(
            create_discrepancy_claim_payload(bag_id, claimed_amount_cents, claim_type),
            make_customer_account_holder_headers(account_id),
        )
    )


def request_claim_info(claim_id: str, note: Optional[str] = None) -> dict:
    payload = request_info_payload(note) if note else request_info_payload()
    return get_success_data(
        api_client.request_claim_info(claim_id, payload, make_manager_headers(MANAGER_1))
    )


def resubmit_claim(claim_id: str, account_id: str, claimed_amount_cents: int) -> dict:
    return get_success_data(
        api_client.resubmit_discrepancy_claim(
            claim_id,
            resubmit_claim_payload(claimed_amount_cents),
            make_customer_account_holder_headers(account_id),
        )
    )


def approve_claim(claim_id: str, resolution_amount_cents: int, manager_user_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.approve_discrepancy_claim(
            claim_id,
            approve_claim_payload(resolution_amount_cents),
            make_manager_headers(manager_user_id),
        )
    )


def deny_claim(claim_id: str, reason: Optional[str] = None, manager_user_id: str = MANAGER_1) -> dict:
    payload = deny_claim_payload(reason) if reason else deny_claim_payload()
    return get_success_data(
        api_client.deny_discrepancy_claim(claim_id, payload, make_manager_headers(manager_user_id))
    )


def setup_claim_under_review(
    declared_amount_cents: int = 102_500,
    declared_note_count: Optional[int] = None,
    counted_amount_cents: int = 100_000,
    counted_note_count: int = 100,
    claimed_amount_cents: int = 2_500,
    rounds: int = 1,
    leave_in_info_requested: bool = False,
    **overrides,
) -> Dict[str, object]:
    """A counted, materially short bag with a SUBMITTED claim on it.

    `rounds` drives the SUBMITTED → INFO_REQUESTED → SUBMITTED cycle that many
    times; `leave_in_info_requested` stops after the final request-info so the
    claim sits in INFO_REQUESTED at review_round == rounds.
    """
    scenario = setup_counted_bag(
        declared_amount_cents=declared_amount_cents,
        declared_note_count=(
            declared_note_count if declared_note_count is not None else counted_note_count
        ),
        counted_amount_cents=counted_amount_cents,
        counted_note_count=counted_note_count,
        **overrides,
    )
    account_id = scenario["account"]["id"]
    claim = file_claim(scenario["bag"]["id"], account_id, claimed_amount_cents)
    review_rounds = [claim["review_round"]]
    for _ in range(rounds - 1):
        request_claim_info(claim["id"])
        claim = resubmit_claim(claim["id"], account_id, claimed_amount_cents)
        review_rounds.append(claim["review_round"])
    if leave_in_info_requested:
        claim = request_claim_info(claim["id"])
    scenario["claim"] = claim
    scenario["review_rounds"] = review_rounds
    return scenario


# ─── Coin orders and inventory ────────────────────────────────────────────

def setup_vault_with_inventory(
    inventory: Dict[str, int], pickup_concurrency_limit: Optional[int] = None
) -> Dict[str, object]:
    """A vault stocked with the named box counts plus an ACTIVE depositor."""
    scenario = setup_processing_center(
        pickup_concurrency_limit=pickup_concurrency_limit, with_machine=False
    )
    for denomination, boxes in inventory.items():
        adjust_inventory(scenario["vault"]["id"], denomination, boxes)
    scenario["vault"] = read_vault(scenario["vault"]["id"])
    return scenario


def place_coin_order(
    account_id: str,
    vault_id: str,
    lines: List[dict],
    pickup_window_start: str = "2026-08-05T10:00:00Z",
    pickup_window_end: str = "2026-08-05T12:00:00Z",
) -> dict:
    return get_success_data(
        api_client.create_coin_order(
            create_coin_order_payload(
                account_id, vault_id, lines, pickup_window_start, pickup_window_end
            ),
            make_customer_account_holder_headers(account_id),
        )
    )


def approve_coin_order(order_id: str, allow_partial: bool, manager_user_id: str = MANAGER_1) -> dict:
    return get_success_data(
        api_client.approve_coin_order(
            order_id,
            approve_coin_order_payload(allow_partial),
            make_manager_headers(manager_user_id),
        )
    )


def release_coin_order(
    order_id: str, vault_id: str, teller_user_id: str = TELLER_1, expected_vault_version: Optional[int] = None
) -> dict:
    if expected_vault_version is None:
        expected_vault_version = read_vault_version(vault_id)
    return get_success_data(
        api_client.release_coin_order(
            order_id,
            release_coin_order_payload(expected_vault_version),
            make_teller_headers(teller_user_id),
        )
    )


def return_coin_order(order_id: str, reason: Optional[str] = None, teller_user_id: str = TELLER_1) -> dict:
    payload = return_coin_order_payload(reason) if reason else return_coin_order_payload()
    return get_success_data(
        api_client.return_coin_order(order_id, payload, make_teller_headers(teller_user_id))
    )


def setup_approved_coin_order(
    inventory: Dict[str, int],
    requested: Dict[str, int],
    allow_partial: bool = False,
    approver_user_id: str = MANAGER_1,
    pickup_concurrency_limit: Optional[int] = None,
) -> Dict[str, object]:
    """A stocked vault plus a coin order already run through allocation.

    `inventory` maps denomination → boxes on hand; `requested` maps
    denomination → boxes requested.
    """
    scenario = setup_vault_with_inventory(inventory, pickup_concurrency_limit)
    lines = [coin_order_line(denom, boxes) for denom, boxes in requested.items()]
    order = place_coin_order(scenario["account"]["id"], scenario["vault"]["id"], lines)
    scenario["order"] = approve_coin_order(
        order["id"], allow_partial, manager_user_id=approver_user_id
    )
    scenario["vault"] = read_vault(scenario["vault"]["id"])
    return scenario


__all__ = [
    "DEFAULT_WINDOW_START",
    "DEFAULT_WINDOW_END",
    "window_pair",
    "set_clock",
    "create_vault",
    "create_account",
    "create_machine",
    "create_ticket",
    "create_bag",
    "read_vault",
    "read_account",
    "read_ticket",
    "read_bag",
    "read_session",
    "read_report",
    "read_claim",
    "read_fed_deposit",
    "read_coin_order",
    "read_inventory",
    "read_inventory_position",
    "read_coin_order_lines",
    "read_session_lots",
    "read_bag_version",
    "read_vault_version",
    "add_custody_hop",
    "deliver_bag_to_vault",
    "open_bag",
    "verify_ticket",
    "extend_provisional_credit",
    "reverse_provisional_credit",
    "hold_ticket",
    "settle_ticket",
    "set_posture",
    "adjust_inventory",
    "schedule_session",
    "start_session",
    "complete_session",
    "default_lots",
    "count_bag",
    "setup_processing_center",
    "setup_intake_ticket",
    "setup_verified_ticket",
    "setup_counted_bag",
    "setup_two_counted_bags",
    "setup_bag_with_suspect_lot",
    "setup_bag_with_fit_and_unfit_lots",
    "draft_counterfeit_report",
    "submit_counterfeit_report",
    "return_counterfeit_report",
    "setup_drafted_counterfeit_report",
    "setup_submitted_counterfeit_report",
    "prepare_cash_letter",
    "ship_cash_letter",
    "confirm_cash_letter",
    "setup_prepared_cash_letter",
    "setup_shipped_cash_letter",
    "file_claim",
    "request_claim_info",
    "resubmit_claim",
    "approve_claim",
    "deny_claim",
    "setup_claim_under_review",
    "setup_vault_with_inventory",
    "place_coin_order",
    "approve_coin_order",
    "release_coin_order",
    "return_coin_order",
    "setup_approved_coin_order",
]
