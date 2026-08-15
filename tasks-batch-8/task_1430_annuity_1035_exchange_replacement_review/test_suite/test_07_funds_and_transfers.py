"""Funds movement: request-time computation and snapshots, the receipt
cascade that surrenders the contract, the failure compensation loop, and
value/basis conservation across rescission (PRD §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    assert_funds_transfer,
    assert_logical_instant,
    get_case,
    get_single_contract,
    list_transfers,
    setup_case_approved,
    setup_case_in_free_look,
    validate_success,
)


def test_request_funds_computes_transfer_and_snapshots_contract(api):
    """PRD §3.6: "The transfer's `amount_cents` — the cash the ceding carrier
    remits — is the exchange base minus the surrender charge recomputed under
    the at-settlement variant at request time, and `surrender_charge_cents` is
    the charge so withheld; `basis_transferred_cents` follows the allocation
    rules of §3.4."
    PRD §3.6: "Critically, the transfer snapshots the contract's
    `account_value_cents` and `tax_basis_cents` into `pre_exchange_value_cents`
    and `pre_exchange_basis_cents` at request time, and stamps `requested_at`;
    these snapshots are what a later rescission restores from. In the same
    operation the contract moves `IN_FORCE` → `SURRENDER_PENDING` with its
    `version` bumped."

    Design: Difficulty/transitive_cascade/funds_receipt_chain_surrenders_contract
    """
    bundle = setup_case_approved()
    transfer = validate_success(
        api.request_funds(bundle["case_id"], TEST_USERS["ops_headers"]),
        expected_status=201,
    )
    assert_funds_transfer(transfer)
    assert transfer["status"] == "REQUESTED"
    # At-settlement variant at 2026-08-01: year 6 -> 200 bps -> 200,000.
    assert transfer["amount_cents"] == 9800000
    assert transfer["surrender_charge_cents"] == 200000
    assert transfer["basis_transferred_cents"] == 8000000  # FULL: entire basis
    assert transfer["pre_exchange_value_cents"] == 10000000
    assert transfer["pre_exchange_basis_cents"] == 8000000
    assert_logical_instant(
        transfer["requested_at"], "2026-08-01T00:00:00Z", "requested_at"
    )
    assert get_case(bundle["case_id"])["status"] == "FUNDS_REQUESTED"
    contract = get_single_contract(bundle["client"]["id"])
    assert contract["status"] == "SURRENDER_PENDING"


def test_mark_received_cascades_case_and_surrenders_contract(api):
    """PRD §3.6: "When the ceding carrier's money arrives, the desk records
    receipt: the transfer moves `REQUESTED` → `RECEIVED` with `received_at`
    stamped, and this single mutation cascades. The parent case moves
    `FUNDS_REQUESTED` → `FUNDS_RECEIVED`; the contract moves
    `SURRENDER_PENDING` → `EXCHANGED`; and the contract's balances are reduced
    — for a `FULL` exchange `account_value_cents` and `tax_basis_cents` both
    become zero, while for a `PARTIAL` exchange the `exchange_amount_cents` is
    subtracted from the account value and the transfer's
    `basis_transferred_cents` is subtracted from the basis."

    Design: Difficulty/transitive_cascade/funds_receipt_chain_surrenders_contract
    """
    bundle = setup_case_approved()
    transfer = validate_success(
        api.request_funds(bundle["case_id"], TEST_USERS["ops_headers"]),
        expected_status=201,
    )
    received = validate_success(
        api.mark_transfer_received(transfer["id"], TEST_USERS["ops_headers"])
    )
    assert received["status"] == "RECEIVED"
    assert_logical_instant(
        received["received_at"], "2026-08-01T00:00:00Z", "received_at"
    )

    case_after = get_case(bundle["case_id"])
    assert case_after["status"] == "FUNDS_RECEIVED", (
        "the case is mutated by the transfer's receipt, not a direct case call"
    )
    contract = get_single_contract(bundle["client"]["id"])
    assert contract["status"] == "EXCHANGED"
    assert contract["account_value_cents"] == 0
    assert contract["tax_basis_cents"] == 0


def test_full_exchange_value_conserved_across_round_trip(api):
    """PRD §3.6: "The transfer's `amount_cents` — the cash the ceding carrier
    remits — is the exchange base minus the surrender charge recomputed under
    the at-settlement variant at request time, and `surrender_charge_cents` is
    the charge so withheld"
    The forward decomposition is exact: remitted cash plus withheld charge
    equals the snapshotted pre-exchange account value.

    Design: Difficulty/compensating_invariant/full_exchange_value_conservation
    """
    bundle = setup_case_in_free_look()  # junior client, delivered at default
    transfer = bundle["transfer"]
    assert transfer["amount_cents"] == 9800000
    assert transfer["surrender_charge_cents"] == 200000
    assert (
        transfer["amount_cents"] + transfer["surrender_charge_cents"]
        == transfer["pre_exchange_value_cents"]
        == 10000000
    )
    contract = get_single_contract(bundle["client"]["id"])
    assert contract["status"] == "EXCHANGED"
    assert contract["account_value_cents"] == 0


def test_full_exchange_rescission_restores_exact_account_value(api):
    """PRD §3.7: "the contract moves `EXCHANGED` → `IN_FORCE` with its
    `account_value_cents` and `tax_basis_cents` restored verbatim from the
    transfer's `pre_exchange_value_cents` and `pre_exchange_basis_cents`
    snapshots; the restore stamps the client's `last_rescinded_at`; and an
    `EXCHANGE_RESCINDED` event fires for the producer, followed by counter
    recomputation and churn evaluation."
    The charge withheld by the ceding carrier returns with the policy, so no
    value leaks from the round trip.

    Design: Difficulty/compensating_invariant/full_exchange_value_conservation
    """
    from test_helpers import make_producer_headers

    bundle = setup_case_in_free_look()
    validate_success(
        api.rescind_case(
            bundle["case_id"], make_producer_headers(bundle["producer"]["id"])
        )
    )
    contract = get_single_contract(bundle["client"]["id"])
    assert contract["status"] == "IN_FORCE"
    assert contract["account_value_cents"] == 10000000
    assert contract["tax_basis_cents"] == 8000000


def test_partial_exchange_basis_conserved_forward(api):
    """PRD §3.6: "for a `FULL` exchange `account_value_cents` and
    `tax_basis_cents` both become zero, while for a `PARTIAL` exchange the
    `exchange_amount_cents` is subtracted from the account value and the
    transfer's `basis_transferred_cents` is subtracted from the basis."
    PRD §3.4: "For a `PARTIAL` exchange, `basis_transferred_cents` is the
    `tax_basis_cents` multiplied by `exchange_amount_cents` and then divided by
    `account_value_cents`, rounded down"

    Design: Difficulty/compensating_invariant/partial_exchange_basis_conservation
    """
    bundle = setup_case_approved(
        dob="1990-06-15",
        case_overrides={"exchange_type": "PARTIAL", "exchange_amount_cents": 3333333},
    )
    transfer = validate_success(
        api.request_funds(bundle["case_id"], TEST_USERS["ops_headers"]),
        expected_status=201,
    )
    assert transfer["basis_transferred_cents"] == 2666666
    assert transfer["pre_exchange_basis_cents"] == 8000000

    validate_success(api.mark_transfer_received(transfer["id"], TEST_USERS["ops_headers"]))
    contract = get_single_contract(bundle["client"]["id"])
    assert contract["tax_basis_cents"] == 5333334
    assert contract["account_value_cents"] == 6666667
    assert transfer["basis_transferred_cents"] + contract["tax_basis_cents"] == 8000000, (
        "tax basis is conserved across the forward partial exchange"
    )


def test_partial_exchange_rescission_restores_basis_without_drift(api):
    """PRD §3.7: "the contract moves `EXCHANGED` → `IN_FORCE` with its
    `account_value_cents` and `tax_basis_cents` restored verbatim from the
    transfer's `pre_exchange_value_cents` and `pre_exchange_basis_cents`
    snapshots"

    Design: Difficulty/compensating_invariant/partial_exchange_basis_conservation
    """
    from test_helpers import make_producer_headers

    bundle = setup_case_in_free_look(
        dob="1990-06-15",
        case_overrides={"exchange_type": "PARTIAL", "exchange_amount_cents": 3333333},
    )
    validate_success(
        api.rescind_case(
            bundle["case_id"], make_producer_headers(bundle["producer"]["id"])
        )
    )
    contract = get_single_contract(bundle["client"]["id"])
    assert contract["status"] == "IN_FORCE"
    assert contract["tax_basis_cents"] == 8000000, "snapshot restore: no basis drift"
    assert contract["account_value_cents"] == 10000000


def test_transfer_failure_compensates_case_and_contract(api):
    """PRD §3.6: "When the transfer fails, the desk records that instead: the
    transfer moves `REQUESTED` → `FAILED`, and the compensating cascade reverts
    the case `FUNDS_REQUESTED` → `APPROVED` and the contract
    `SURRENDER_PENDING` → `IN_FORCE`, again bumping each version. The
    compensation path leaves the case eligible to request funds again from
    `APPROVED`."

    Design: Corner/state_machines/transfer_failure_compensates_case_and_contract
    """
    bundle = setup_case_approved()
    transfer1 = validate_success(
        api.request_funds(bundle["case_id"], TEST_USERS["ops_headers"]),
        expected_status=201,
    )
    failed = validate_success(
        api.mark_transfer_failed(transfer1["id"], TEST_USERS["ops_headers"])
    )
    assert failed["status"] == "FAILED"

    assert get_case(bundle["case_id"])["status"] == "APPROVED"
    contract = get_single_contract(bundle["client"]["id"])
    assert contract["status"] == "IN_FORCE"
    assert contract["account_value_cents"] == 10000000
    assert contract["tax_basis_cents"] == 8000000

    transfer2 = validate_success(
        api.request_funds(bundle["case_id"], TEST_USERS["ops_headers"]),
        expected_status=201,
    )
    assert transfer2["status"] == "REQUESTED"

    transfers = list_transfers(bundle["case_id"])
    assert len(transfers) == 2
    by_id = {t["id"]: t for t in transfers}
    assert by_id[transfer1["id"]]["status"] == "FAILED"
    assert by_id[transfer2["id"]]["status"] == "REQUESTED"
