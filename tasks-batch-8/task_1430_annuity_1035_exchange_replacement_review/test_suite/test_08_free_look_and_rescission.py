"""Free-look window boundaries, completion gating, and the transitive
rescission cascade (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_logical_instant,
    get_case,
    get_client,
    get_producer,
    get_single_contract,
    list_producer_events,
    list_transfers,
    make_producer_headers,
    set_clock,
    setup_case_approved,
    setup_case_in_free_look,
    validate_error,
    validate_success,
    request_and_receive_funds,
)


def test_rescind_on_deadline_date_succeeds(api):
    """PRD §3.7: "Rescission — `IN_FREE_LOOK` → `RESCINDED` — is performed by
    the owning producer (ownership enforced via
    `ERR_CASE_NOT_OWNED_BY_PRODUCER`) or by a `CarrierAdmin` as backstop, and
    requires the current date to be on or before `free_look_deadline_date`, the
    boundary inclusive; a later attempt is rejected with
    `ERR_FREE_LOOK_EXPIRED` (HTTP 409)."
    Junior client delivered 2026-08-02: the 20-day deadline is 2026-08-22, and
    rescission on exactly that date succeeds.

    Design: Difficulty/boundary_precision_check/free_look_deadline_inclusive_boundary
    """
    bundle = setup_case_in_free_look(delivery_clock="2026-08-02T00:00:00Z")
    case = get_case(bundle["case_id"])
    assert case["free_look_deadline_date"] == "2026-08-22"

    set_clock("2026-08-22T00:00:00Z")
    rescinded = validate_success(
        api.rescind_case(
            bundle["case_id"], make_producer_headers(bundle["producer"]["id"])
        )
    )
    assert rescinded["status"] == "RESCINDED", "deadline date is inclusive"


def test_rescind_one_day_past_deadline_rejected(api):
    """PRD §3.7: "Rescission — `IN_FREE_LOOK` → `RESCINDED` — is performed by
    the owning producer (ownership enforced via
    `ERR_CASE_NOT_OWNED_BY_PRODUCER`) or by a `CarrierAdmin` as backstop, and
    requires the current date to be on or before `free_look_deadline_date`, the
    boundary inclusive; a later attempt is rejected with
    `ERR_FREE_LOOK_EXPIRED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/free_look_deadline_inclusive_boundary
    """
    bundle = setup_case_in_free_look(delivery_clock="2026-08-02T00:00:00Z")
    assert get_case(bundle["case_id"])["free_look_deadline_date"] == "2026-08-22"

    set_clock("2026-08-23T00:00:00Z")  # one day past the deadline
    res = api.rescind_case(
        bundle["case_id"], make_producer_headers(bundle["producer"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_FREE_LOOK_EXPIRED)
    assert get_case(bundle["case_id"])["status"] == "IN_FREE_LOOK"


def test_rescission_chain_restores_transfer_contract_client(api):
    """PRD §3.7: "Rescission is a synchronous transitive chain. The case stamps
    `rescinded_at` and becomes `RESCINDED`; the transfer moves `RECEIVED` →
    `RETURNED` with `returned_at` stamped; the contract moves `EXCHANGED` →
    `IN_FORCE` with its `account_value_cents` and `tax_basis_cents` restored
    verbatim from the transfer's `pre_exchange_value_cents` and
    `pre_exchange_basis_cents` snapshots; the restore stamps the client's
    `last_rescinded_at`; and an `EXCHANGE_RESCINDED` event fires for the
    producer, followed by counter recomputation and churn evaluation."

    Design: Difficulty/transitive_cascade/rescission_full_chain_restores_contract_and_stamps_client
    """
    bundle = setup_case_in_free_look()  # junior; delivered at the default clock
    rescinded = validate_success(
        api.rescind_case(
            bundle["case_id"], make_producer_headers(bundle["producer"]["id"])
        )
    )
    assert rescinded["status"] == "RESCINDED"
    assert_logical_instant(
        rescinded["rescinded_at"], "2026-08-01T00:00:00Z", "rescinded_at"
    )

    transfers = list_transfers(bundle["case_id"])
    assert len(transfers) == 1
    assert transfers[0]["status"] == "RETURNED", (
        "the transfer is mutated by the case's rescission, not a direct call"
    )
    assert_logical_instant(
        transfers[0]["returned_at"], "2026-08-01T00:00:00Z", "returned_at"
    )

    contract = get_single_contract(bundle["client"]["id"])
    assert contract["status"] == "IN_FORCE"
    assert contract["account_value_cents"] == 10000000
    assert contract["tax_basis_cents"] == 8000000

    client = get_client(bundle["client"]["id"])
    assert_logical_instant(
        client["last_rescinded_at"], "2026-08-01T00:00:00Z", "last_rescinded_at"
    )


def test_rescission_stamps_client_and_producer_counters(api):
    """PRD §3.7: "the restore stamps the client's `last_rescinded_at`; and an
    `EXCHANGE_RESCINDED` event fires for the producer, followed by counter
    recomputation and churn evaluation."
    PRD §3.8: "a producer is set to `FLAGGED` when
    `completed_exchange_count_12m` is at least 2 and
    `rescission_rate_completed_bps` is at least 5,000 basis points, and a later
    evaluation that finds the condition no longer holding automatically clears
    the producer back to `ACTIVE`." With zero completions the flag cannot set.

    Design: Difficulty/transitive_cascade/rescission_full_chain_restores_contract_and_stamps_client
    """
    bundle = setup_case_in_free_look()
    validate_success(
        api.rescind_case(
            bundle["case_id"], make_producer_headers(bundle["producer"]["id"])
        )
    )

    producer = get_producer(bundle["producer"]["id"])
    assert producer["rescinded_exchange_count_12m"] == 1
    assert producer["submitted_case_count_12m"] == 1
    assert producer["completed_exchange_count_12m"] == 0
    assert producer["status"] == "ACTIVE"

    events = [
        e for e in list_producer_events(bundle["producer"]["id"])
        if e["event_type"] == "EXCHANGE_RESCINDED"
    ]
    assert len(events) == 1
    assert events[0]["case_id"] == bundle["case_id"]
    assert_logical_instant(
        events[0]["event_at"], "2026-08-01T00:00:00Z", "event_at"
    )


def test_complete_on_deadline_date_rejected_then_succeeds_next_day(api):
    """PRD §3.7: "Closing the case — `IN_FREE_LOOK` → `COMPLETED` — requires
    the current date to be strictly after `free_look_deadline_date`; attempting
    completion on or before that date is rejected with
    `ERR_FREE_LOOK_STILL_ACTIVE` (HTTP 409)."
    PRD §3.7: "Completion stamps `completed_at`, stamps the old contract's
    `last_exchange_completed_at` with the same instant (the anti-churn marker
    consulted at submission), appends an `EXCHANGE_COMPLETED` event for the
    producer, recomputes the producer counters, and runs the churn evaluation,
    which may set or clear `FLAGGED`."
    Junior client delivered 2026-08-01: deadline 2026-08-21.

    Design: Corner/state_machines/complete_before_deadline_returns_free_look_still_active
    """
    bundle = setup_case_in_free_look()
    assert get_case(bundle["case_id"])["free_look_deadline_date"] == "2026-08-21"

    set_clock("2026-08-21T00:00:00Z")
    res = api.complete_case(bundle["case_id"], TEST_USERS["ops_headers"])
    validate_error(res, ApiErrorId.ERR_FREE_LOOK_STILL_ACTIVE)

    set_clock("2026-08-22T00:00:00Z")
    completed = validate_success(
        api.complete_case(bundle["case_id"], TEST_USERS["ops_headers"])
    )
    assert completed["status"] == "COMPLETED"
    assert_logical_instant(
        completed["completed_at"], "2026-08-22T00:00:00Z", "completed_at"
    )
    contract = get_single_contract(bundle["client"]["id"])
    assert_logical_instant(
        contract["last_exchange_completed_at"],
        "2026-08-22T00:00:00Z",
        "last_exchange_completed_at",
    )


def test_rescind_before_free_look_rejected_invalid_state(api):
    """PRD §3.7 names rescission as "`IN_FREE_LOOK` → `RESCINDED`", so from
    APPROVED the request has no declared from-state.
    PRD §2.8: "Sixth, state legality of the requested transition is checked
    (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — or
    `ERR_CONTRACT_NOT_IN_FORCE` for the contract precondition on case
    submission)."

    Design: Corner/state_machines/rescind_before_free_look_returns_invalid_state
    """
    bundle = setup_case_approved()
    res = api.rescind_case(
        bundle["case_id"], make_producer_headers(bundle["producer"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    events = [
        e for e in list_producer_events(bundle["producer"]["id"])
        if e["event_type"] == "EXCHANGE_RESCINDED"
    ]
    assert events == []
    assert get_single_contract(bundle["client"]["id"])["status"] == "IN_FORCE"


def test_carrier_admin_may_rescind_as_backstop(api, carrier_admin_headers):
    """PRD §3.7: "Rescission — `IN_FREE_LOOK` → `RESCINDED` — is performed by
    the owning producer (ownership enforced via
    `ERR_CASE_NOT_OWNED_BY_PRODUCER`) or by a `CarrierAdmin` as backstop, and
    requires the current date to be on or before `free_look_deadline_date`, the
    boundary inclusive; a later attempt is rejected with
    `ERR_FREE_LOOK_EXPIRED` (HTTP 409)."

    Design: Corner/endpoints/rescind_by_carrier_admin_shared_operation
    """
    bundle = setup_case_in_free_look(
        contract_overrides={"living_benefit_rider": False}
    )
    rescinded = validate_success(
        api.rescind_case(bundle["case_id"], carrier_admin_headers)
    )
    assert rescinded["status"] == "RESCINDED", (
        "CarrierAdmin is not the owning producer; the ownership check does not apply"
    )
    contract = get_single_contract(bundle["client"]["id"])
    assert contract["status"] == "IN_FORCE"
    assert contract["account_value_cents"] == 10000000
    assert contract["tax_basis_cents"] == 8000000


def test_free_look_length_30_days_senior_20_days_standard(api):
    """PRD §3.7: "That instant stamps `free_look_started_at`, and the server
    computes `free_look_deadline_date` as the delivery date plus the free-look
    length: 30 days when the client `is_senior` (at least 65 years old at
    delivery), 20 days otherwise. The delivery date itself is day 0, and
    boundaries are evaluated on whole UTC dates."

    Design: Corner/calculations/free_look_senior_vs_junior_days
    """
    from test_helpers import (
        add_verified_documents,
        approve_case,
        create_analysis,
        open_case,
        recommend_case,
        register_client,
        register_contract,
        register_producer,
        start_review,
        submit_case,
    )

    producer = register_producer()
    cases = {}
    for tag, dob, number in (
        ("senior", "1960-01-01", "CN-A"),
        ("junior", "1990-06-15", "CN-B"),
    ):
        client = register_client(producer["id"], full_name=tag.title(), date_of_birth=dob)
        contract = register_contract(
            producer["id"], client["id"],
            contract_number=number, living_benefit_rider=False,
            surrender_schedule=[{"contract_year": 1, "pct_bps": 700}],
        )
        case = open_case(producer["id"], client["id"], contract["id"])
        submit_case(case["id"], producer["id"])
        reviewed = start_review(case["id"])
        add_verified_documents(case["id"], producer["id"])
        create_analysis(case["id"], reviewed["version"])
        recommend_case(case["id"])
        approve_case(case["id"])
        request_and_receive_funds(case["id"])
        validate_success(api.confirm_delivery(case["id"], TEST_USERS["ops_headers"]))
        cases[tag] = case["id"]

    senior = {"case_id": cases["senior"]}
    junior = {"case_id": cases["junior"]}
    senior_case = get_case(senior["case_id"])
    junior_case = get_case(junior["case_id"])
    assert_logical_instant(
        senior_case["free_look_started_at"], "2026-08-01T00:00:00Z",
        "senior free_look_started_at",
    )
    assert_logical_instant(
        junior_case["free_look_started_at"], "2026-08-01T00:00:00Z",
        "junior free_look_started_at",
    )
    assert senior_case["free_look_deadline_date"] == "2026-08-31"  # 30 days
    assert junior_case["free_look_deadline_date"] == "2026-08-21"  # 20 days
