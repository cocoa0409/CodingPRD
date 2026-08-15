"""The seven submission gates of PRD §3.2: ownership, contract state,
producer standing, cooling-off, anti-churn, occupation, and partial bounds."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_case,
    get_producer,
    get_single_contract,
    make_producer_headers,
    open_case,
    register_client,
    register_contract,
    register_producer,
    set_clock,
    setup_case_completed,
    setup_case_in_free_look,
    setup_case_in_review,
    setup_case_rescinded,
    submit_case,
    validate_error,
    validate_success,
)


# ── Contract state gate (cross-entity dependency) ─────────────────────────


def test_submit_case_on_exchanged_contract_rejected(api):
    """PRD §3.2: "Second, the contract must be `IN_FORCE`, else
    `ERR_CONTRACT_NOT_IN_FORCE`."
    PRD §3.2: "Submitting a case — the `DRAFT` → `SUBMITTED` transition by the
    owning producer — is where the desk's protective gates run, and they run in
    a fixed order."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_contract_in_force
    """
    bundle = setup_case_completed()  # contract now EXCHANGED, marker 2026-08-22
    producer = bundle["producer"]
    case_b = open_case(
        producer["id"], bundle["client"]["id"], bundle["contract"]["id"]
    )

    res = api.submit_case(case_b["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_IN_FORCE)
    assert get_case(case_b["id"])["status"] == "DRAFT"


def test_exchanged_contract_blocks_submit_even_after_anti_churn_window(api):
    """PRD §3.2: "Second, the contract must be `IN_FORCE`, else
    `ERR_CONTRACT_NOT_IN_FORCE`."
    PRD §3.2: "Fifth, anti-churn: if the contract's
    `last_exchange_completed_at` is set and fewer than 365 days have elapsed,
    submission is rejected with `ERR_CONTRACT_EXCHANGED_WITHIN_12M`."
    Moving the clock 366 days past the completion marker discharges the
    anti-churn gate, but the EXCHANGED contract still blocks submission.

    Design: Difficulty/cross_entity_state_dependency/submit_requires_contract_in_force
    """
    bundle = setup_case_completed()  # completed at 2026-08-22
    producer = bundle["producer"]
    case_b = open_case(
        producer["id"], bundle["client"]["id"], bundle["contract"]["id"]
    )
    set_clock("2027-08-23T00:00:00Z")  # 366 days after the marker: anti-churn passes

    res = api.submit_case(case_b["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_IN_FORCE)
    assert get_case(case_b["id"])["status"] == "DRAFT"
    assert get_single_contract(bundle["client"]["id"])["status"] == "EXCHANGED"


# ── Occupation gate (temporal overlap on the contract) ────────────────────


def test_second_case_on_occupied_contract_rejected(api):
    """PRD §3.2: "Sixth, occupation: if any other case on the same contract is
    in a non-terminal status — anything other than `COMPLETED`, `REJECTED`,
    `WITHDRAWN`, or `RESCINDED` — submission is rejected with
    `ERR_CONTRACT_EXCHANGE_IN_PROGRESS`."

    Design: Difficulty/resource_temporal_overlap/contract_occupation_overlap
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(producer["id"], client["id"])
    case_a = open_case(producer["id"], client["id"], contract["id"])
    submit_case(case_a["id"], producer["id"])  # A occupies the contract
    case_b = open_case(producer["id"], client["id"], contract["id"])

    res = api.submit_case(case_b["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_CONTRACT_EXCHANGE_IN_PROGRESS)
    assert get_case(case_b["id"])["status"] == "DRAFT"


def test_case_submits_after_occupying_case_withdrawn(api):
    """PRD §3.2: "Sixth, occupation: if any other case on the same contract is
    in a non-terminal status — anything other than `COMPLETED`, `REJECTED`,
    `WITHDRAWN`, or `RESCINDED` — submission is rejected with
    `ERR_CONTRACT_EXCHANGE_IN_PROGRESS`."
    The occupation interval closes at the first case's terminal transition, so
    the second case submits once the first is WITHDRAWN.

    Design: Difficulty/resource_temporal_overlap/contract_occupation_overlap
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(producer["id"], client["id"])
    case_a = open_case(producer["id"], client["id"], contract["id"])
    submit_case(case_a["id"], producer["id"])
    case_b = open_case(producer["id"], client["id"], contract["id"])

    validate_error(
        api.submit_case(case_b["id"], make_producer_headers(producer["id"])),
        ApiErrorId.ERR_CONTRACT_EXCHANGE_IN_PROGRESS,
    )
    withdraw = api.withdraw_case(case_a["id"], make_producer_headers(producer["id"]))
    assert validate_success(withdraw)["status"] == "WITHDRAWN"

    submitted = validate_success(
        api.submit_case(case_b["id"], make_producer_headers(producer["id"]))
    )
    assert submitted["status"] == "SUBMITTED"


# ── Cooling-off gate (minimum gap on the client) ──────────────────────────


def _setup_case_b_after_rescission(api):
    """Case A rescinded at 2026-08-22 (its deadline day); case B pre-created
    on a second contract of the same client. Returns the bundle + case B."""
    producer = register_producer()
    client = register_client(producer["id"], date_of_birth="1990-06-15")
    no_rider = {"living_benefit_rider": False}
    contract_a = register_contract(
        producer["id"], client["id"], contract_number="CN-A", **no_rider
    )
    contract_b = register_contract(
        producer["id"], client["id"], contract_number="CN-B", **no_rider
    )
    # Case A: delivered 2026-08-02 (junior -> deadline 2026-08-22).
    case_a = open_case(producer["id"], client["id"], contract_a["id"])
    _drive_to_free_look(api, case_a["id"], producer["id"], "2026-08-02T00:00:00Z")
    # Case B pre-created before the rescission so only cooling-off gates it.
    case_b = open_case(producer["id"], client["id"], contract_b["id"])
    set_clock("2026-08-22T00:00:00Z")
    rescinded = validate_success(
        api.rescind_case(case_a["id"], make_producer_headers(producer["id"]))
    )
    assert rescinded["status"] == "RESCINDED"
    return producer, client, case_b


def _drive_to_free_look(api, case_id, producer_id, delivery_clock):
    from test_helpers import (
        add_verified_documents,
        approve_case,
        create_analysis,
        recommend_case,
        request_and_receive_funds,
        start_review,
    )

    submit_case(case_id, producer_id)
    reviewed = start_review(case_id)
    add_verified_documents(case_id, producer_id)
    create_analysis(case_id, reviewed["version"])
    recommend_case(case_id)
    approve_case(case_id)
    request_and_receive_funds(case_id)
    set_clock(delivery_clock)
    validate_success(api.confirm_delivery(case_id, TEST_USERS["ops_headers"]))


def test_submit_during_client_cooling_off_rejected(api):
    """PRD §3.2: "Fourth, client cooling-off: if the client's
    `last_rescinded_at` is set and fewer than 30 days have elapsed since it,
    submission is rejected with `ERR_COOLING_OFF_ACTIVE`; a client who has
    never rescinded passes."

    Design: Difficulty/resource_temporal_overlap/client_rescission_cooling_off_gap
    """
    producer, client, case_b = _setup_case_b_after_rescission(api)
    assert get_client_ts(client) == "2026-08-22"

    set_clock("2026-09-20T00:00:00Z")  # 29 days after the rescission
    res = api.submit_case(case_b["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_COOLING_OFF_ACTIVE)
    assert get_case(case_b["id"])["status"] == "DRAFT"


def test_submit_exactly_30_days_after_rescission_allowed(api):
    """PRD §3.2: "Fourth, client cooling-off: if the client's
    `last_rescinded_at` is set and fewer than 30 days have elapsed since it,
    submission is rejected with `ERR_COOLING_OFF_ACTIVE`; a client who has
    never rescinded passes."
    Exactly 30 days after the rescission the gap is no longer "fewer than 30
    days", so the gate passes.

    Design: Difficulty/resource_temporal_overlap/client_rescission_cooling_off_gap
    """
    producer, client, case_b = _setup_case_b_after_rescission(api)

    set_clock("2026-09-21T00:00:00Z")  # exactly 30 days after the rescission
    submitted = validate_success(
        api.submit_case(case_b["id"], make_producer_headers(producer["id"]))
    )
    assert submitted["status"] == "SUBMITTED"


def get_client_ts(client):
    from test_helpers import get_client

    return get_client(client["id"])["last_rescinded_at"][:10]


# ── Partial amount bounds (fiscal gates) ──────────────────────────────────


def test_partial_amount_equal_to_account_value_rejected(api):
    """PRD §3.2: "Seventh, for `PARTIAL` exchanges, the `exchange_amount_cents`
    must be at least 100,000 cents (one thousand dollars), else
    `ERR_PARTIAL_BELOW_MINIMUM`, and must be strictly less than the contract's
    current `account_value_cents`, else `ERR_PARTIAL_AMOUNT_INVALID`."

    Design: Difficulty/boundary_precision_check/partial_amount_equals_value_boundary
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(producer["id"], client["id"])
    case = open_case(
        producer["id"],
        client["id"],
        contract["id"],
        exchange_type="PARTIAL",
        exchange_amount_cents=10000000,  # == account value
    )

    res = api.submit_case(case["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_PARTIAL_AMOUNT_INVALID)
    assert get_case(case["id"])["status"] == "DRAFT"


def test_partial_amount_one_cent_below_value_accepted(api):
    """PRD §3.2: "Seventh, for `PARTIAL` exchanges, the `exchange_amount_cents`
    must be at least 100,000 cents (one thousand dollars), else
    `ERR_PARTIAL_BELOW_MINIMUM`, and must be strictly less than the contract's
    current `account_value_cents`, else `ERR_PARTIAL_AMOUNT_INVALID`."
    One cent below the account value is strictly less, so the gate passes.

    Design: Difficulty/boundary_precision_check/partial_amount_equals_value_boundary
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(producer["id"], client["id"])
    case = open_case(
        producer["id"],
        client["id"],
        contract["id"],
        exchange_type="PARTIAL",
        exchange_amount_cents=9999999,  # account value - 1
    )

    submitted = validate_success(
        api.submit_case(case["id"], make_producer_headers(producer["id"]))
    )
    assert submitted["status"] == "SUBMITTED"


def test_partial_below_minimum_rejected_and_at_minimum_accepted(api):
    """PRD §3.2: "Seventh, for `PARTIAL` exchanges, the `exchange_amount_cents`
    must be at least 100,000 cents (one thousand dollars), else
    `ERR_PARTIAL_BELOW_MINIMUM`, and must be strictly less than the contract's
    current `account_value_cents`, else `ERR_PARTIAL_AMOUNT_INVALID`."

    Design: Corner/validations/partial_below_minimum_boundary
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract_a = register_contract(
        producer["id"], client["id"], contract_number="CN-A", living_benefit_rider=False
    )
    contract_b = register_contract(
        producer["id"], client["id"], contract_number="CN-B", living_benefit_rider=False
    )
    case_a = open_case(
        producer["id"], client["id"], contract_a["id"],
        exchange_type="PARTIAL", exchange_amount_cents=99999,
    )
    case_b = open_case(
        producer["id"], client["id"], contract_b["id"],
        exchange_type="PARTIAL", exchange_amount_cents=100000,
    )

    res = api.submit_case(case_a["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_PARTIAL_BELOW_MINIMUM)
    assert get_case(case_a["id"])["status"] == "DRAFT"

    submitted = validate_success(
        api.submit_case(case_b["id"], make_producer_headers(producer["id"]))
    )
    assert submitted["status"] == "SUBMITTED"


# ── Producer suspension vs partial bounds (priority pair) ─────────────────


def test_suspended_producer_submit_reports_suspension_not_amount(api):
    """PRD §3.2: "Third, the producer must not be `SUSPENDED`, else
    `ERR_PRODUCER_SUSPENDED`." — and the partial-amount bounds are only the
    seventh gate, so the suspension error fires first when both hold.
    PRD §3.8: "a suspended producer cannot submit cases (§3.2's
    `ERR_PRODUCER_SUSPENDED`)."

    Design: Difficulty/priority_pair_validation_conflict/producer_suspension_beats_partial_amount_bounds
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(producer["id"], client["id"])
    case = open_case(
        producer["id"], client["id"], contract["id"],
        exchange_type="PARTIAL", exchange_amount_cents=10000000,
    )
    validate_success(
        api.suspend_producer(producer["id"], TEST_USERS["compliance_headers"])
    )

    res = api.submit_case(case["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_PRODUCER_SUSPENDED)
    assert get_case(case["id"])["status"] == "DRAFT"


def test_reinstated_producer_submit_hits_partial_amount_bound(api):
    """PRD §3.8: "Reinstatement moves `SUSPENDED` → `ACTIVE` with a
    `PRODUCER_REINSTATED` event and immediately re-runs the churn evaluation in
    the same request — so if the thresholds are still met, the producer lands
    on `FLAGGED` rather than `ACTIVE`."
    PRD §3.2: "Seventh, for `PARTIAL` exchanges, the `exchange_amount_cents`
    must be at least 100,000 cents (one thousand dollars), else
    `ERR_PARTIAL_BELOW_MINIMUM`, and must be strictly less than the contract's
    current `account_value_cents`, else `ERR_PARTIAL_AMOUNT_INVALID`."
    Once the suspension gate (third) is cleared, the fiscal gate underneath it
    becomes the one that fires.

    Design: Difficulty/priority_pair_validation_conflict/producer_suspension_beats_partial_amount_bounds
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(producer["id"], client["id"])
    case = open_case(
        producer["id"], client["id"], contract["id"],
        exchange_type="PARTIAL", exchange_amount_cents=10000000,
    )
    validate_success(
        api.suspend_producer(producer["id"], TEST_USERS["compliance_headers"])
    )
    validate_success(
        api.reinstate_producer(producer["id"], TEST_USERS["compliance_headers"])
    )
    assert get_producer(producer["id"])["status"] == "ACTIVE"

    res = api.submit_case(case["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_PARTIAL_AMOUNT_INVALID)
    assert get_case(case["id"])["status"] == "DRAFT"


# ── Anti-churn gate (temporal boundary) ───────────────────────────────────


def test_anti_churn_blocks_contract_exchanged_364_days_ago(api):
    """PRD §3.2: "Fifth, anti-churn: if the contract's
    `last_exchange_completed_at` is set and fewer than 365 days have elapsed,
    submission is rejected with `ERR_CONTRACT_EXCHANGED_WITHIN_12M`."
    PRD §3.1: "A contract that was itself acquired via a completed exchange
    arrives with `last_exchange_completed_at` set; it is null when the contract
    was never exchanged into."

    Design: Corner/validations/anti_churn_12m_boundary
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"],
        living_benefit_rider=False,
        last_exchange_completed_at="2025-08-02T00:00:00Z",  # 364 days ago
    )
    case = open_case(producer["id"], client["id"], contract["id"])

    res = api.submit_case(case["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_CONTRACT_EXCHANGED_WITHIN_12M)
    assert get_case(case["id"])["status"] == "DRAFT"


def test_anti_churn_allows_contract_exchanged_exactly_365_days_ago(api):
    """PRD §3.2: "Fifth, anti-churn: if the contract's
    `last_exchange_completed_at` is set and fewer than 365 days have elapsed,
    submission is rejected with `ERR_CONTRACT_EXCHANGED_WITHIN_12M`."
    At exactly 365 days the elapsed time is no longer "fewer than 365 days",
    so the gate passes at the default clock of 2026-08-01T00:00:00Z.

    Design: Corner/validations/anti_churn_12m_boundary
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"],
        living_benefit_rider=False,
        last_exchange_completed_at="2025-08-01T00:00:00Z",  # exactly 365 days ago
    )
    case = open_case(producer["id"], client["id"], contract["id"])

    submitted = validate_success(
        api.submit_case(case["id"], make_producer_headers(producer["id"]))
    )
    assert submitted["status"] == "SUBMITTED"


# ── Ownership and contract uniqueness ─────────────────────────────────────


def test_producer_cannot_submit_another_producers_case(api):
    """PRD §3.2: "First, ownership: a producer-role caller whose `X-User-ID`
    differs from the case's `producer_id` is rejected with
    `ERR_CASE_NOT_OWNED_BY_PRODUCER`."

    Design: Corner/validations/producer_cannot_touch_other_producers_case
    """
    producer1 = register_producer()
    producer2 = register_producer(license_number="LIC-002", full_name="Pete Other")
    client = register_client(producer1["id"])
    contract = register_contract(
        producer1["id"], client["id"], living_benefit_rider=False
    )
    case = open_case(producer1["id"], client["id"], contract["id"])

    res = api.submit_case(case["id"], make_producer_headers(producer2["id"]))
    validate_error(res, ApiErrorId.ERR_CASE_NOT_OWNED_BY_PRODUCER)
    assert get_case(case["id"])["status"] == "DRAFT"


def test_duplicate_contract_number_case_insensitive_rejected(api):
    """PRD §3.1: "The (`carrier_name`, `contract_number`) pair is unique
    case-insensitively across all registered contracts, and a colliding
    registration is rejected with `ERR_DUPLICATE_CONTRACT_NUMBER` (HTTP 409)."

    Design: Corner/validations/duplicate_contract_number_case_insensitive
    """
    producer = register_producer()
    client = register_client(producer["id"])
    register_contract(
        producer["id"], client["id"],
        contract_number="CN-A", living_benefit_rider=False,
        surrender_schedule=[{"contract_year": 1, "pct_bps": 700}],
    )

    res = api.create_contract(
        {
            "client_id": client["id"],
            "carrier_name": "OldLine",
            "contract_number": "cn-a",  # differs only by case
            "issue_date": "2020-01-01",
            "account_value_cents": 500000,
            "tax_basis_cents": 400000,
            "surrender_schedule": [{"contract_year": 1, "pct_bps": 700}],
            "living_benefit_rider": False,
        },
        make_producer_headers(producer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CONTRACT_NUMBER)
