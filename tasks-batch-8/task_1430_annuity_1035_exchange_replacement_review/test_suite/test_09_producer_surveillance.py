"""Producer churn surveillance: dual rate variants, the half-open 365-day
window, flag set/clear thresholds, and the manual discipline loop
(PRD §2.4, §3.8)."""
from test_helpers import (
    TEST_USERS,
    add_verified_documents,
    approve_case,
    create_analysis,
    get_producer,
    list_producer_events,
    make_producer_headers,
    open_case,
    recommend_case,
    register_client,
    register_contract,
    register_producer,
    set_clock,
    start_review,
    submit_case,
    validate_success,
)


def _drive_to_free_look(api, producer_id, client_id, contract_id, case_overrides=None):
    """Empty-DB-friendly pipeline: case -> SUBMITTED -> ... -> IN_FREE_LOOK.
    Returns (case_id, transfer_id)."""
    case = open_case(producer_id, client_id, contract_id, **(case_overrides or {}))
    submit_case(case["id"], producer_id)
    reviewed = start_review(case["id"])
    add_verified_documents(case["id"], producer_id)
    create_analysis(case["id"], reviewed["version"])
    recommend_case(case["id"])
    approve_case(case["id"])
    transfer = validate_success(
        api.request_funds(case["id"], TEST_USERS["ops_headers"]), expected_status=201
    )
    validate_success(api.mark_transfer_received(transfer["id"], TEST_USERS["ops_headers"]))
    validate_success(api.confirm_delivery(case["id"], TEST_USERS["ops_headers"]))
    return case["id"], transfer["id"]


def _register_kstd(api, producer_id, client_id, contract_number, rider=True):
    return register_contract(
        producer_id,
        client_id,
        contract_number=contract_number,
        living_benefit_rider=rider,
    )


def test_rescission_rates_differ_by_denominator(api):
    """PRD §3.8: "The completed-basis variant, `rescission_rate_completed_bps`,
    is 10,000 times the rescinded count divided by the completed count, rounded
    down — and zero when the producer has no completions in the window."
    PRD §3.8: "The submitted-basis variant, `rescission_rate_submitted_bps`,
    applies the same formula over submissions and is zero when there are none;
    because some submitted cases never complete, the two variants give
    different numbers for identical event data."
    Two submissions, one completion, one rescission: 10000 bps vs 5000 bps.

    Design: Difficulty/dual_variant_calc/rescission_rate_completed_vs_submitted_basis
    """
    producer = register_producer()
    client = register_client(producer["id"], date_of_birth="1990-06-15")
    k_a = _register_kstd(api, producer["id"], client["id"], "CN-A")
    k_b = _register_kstd(api, producer["id"], client["id"], "CN-B")
    case_a, _ = _drive_to_free_look(api, producer["id"], client["id"], k_a["id"])
    case_b, _ = _drive_to_free_look(api, producer["id"], client["id"], k_b["id"])
    # Case B rescinded inside its junior 20-day window (deadline 2026-08-21).
    validate_success(
        api.rescind_case(case_b, make_producer_headers(producer["id"]))
    )
    # Case A completed once its deadline (2026-08-21) has passed.
    set_clock("2026-08-22T00:00:00Z")
    validate_success(api.complete_case(case_a, TEST_USERS["ops_headers"]))

    producer_after = get_producer(producer["id"])
    assert producer_after["submitted_case_count_12m"] == 2
    assert producer_after["completed_exchange_count_12m"] == 1
    assert producer_after["rescinded_exchange_count_12m"] == 1
    assert producer_after["rescission_rate_completed_bps"] == 10000
    assert producer_after["rescission_rate_submitted_bps"] == 5000
    assert (
        producer_after["rescission_rate_completed_bps"]
        != producer_after["rescission_rate_submitted_bps"]
    )


def test_churn_counters_do_not_flag_below_completed_threshold(api):
    """PRD §3.8: "a producer is set to `FLAGGED` when
    `completed_exchange_count_12m` is at least 2 and
    `rescission_rate_completed_bps` is at least 5,000 basis points, and a later
    evaluation that finds the condition no longer holding automatically clears
    the producer back to `ACTIVE`."
    With only one completion the count threshold is unmet, so the producer
    stays ACTIVE even at a 10000 bps completed-basis rate.

    Design: Difficulty/dual_variant_calc/rescission_rate_completed_vs_submitted_basis
    """
    producer = register_producer()
    client = register_client(producer["id"], date_of_birth="1990-06-15")
    k_a = _register_kstd(api, producer["id"], client["id"], "CN-A")
    k_b = _register_kstd(api, producer["id"], client["id"], "CN-B")
    case_a, _ = _drive_to_free_look(api, producer["id"], client["id"], k_a["id"])
    case_b, _ = _drive_to_free_look(api, producer["id"], client["id"], k_b["id"])
    validate_success(api.rescind_case(case_b, make_producer_headers(producer["id"])))
    set_clock("2026-08-22T00:00:00Z")
    validate_success(api.complete_case(case_a, TEST_USERS["ops_headers"]))

    producer_after = get_producer(producer["id"])
    assert producer_after["completed_exchange_count_12m"] == 1
    assert producer_after["rescission_rate_completed_bps"] == 10000
    assert producer_after["status"] == "ACTIVE", (
        "completed count 1 < 2, so the flag must not set despite the rate"
    )
    flagged_events = [
        e for e in list_producer_events(producer["id"])
        if e["event_type"] == "PRODUCER_FLAGGED"
    ]
    assert flagged_events == []


def test_churn_window_excludes_events_exactly_365_days_old(api):
    """PRD §3.8: "The evaluation works over a trailing 365-day half-open
    window: activity events of that producer whose `event_at` is strictly more
    recent than 365 days before now and at or before now are in — an event
    exactly 365 days old is excluded, an event at exactly the current instant
    is included."
    PRD §2.4: "Setting the clock has a mandatory side effect: the producer
    churn evaluation described in §3.8 is re-run for every registered producer,
    because rolling-window membership may shift with the new "now"."

    Design: Corner/calculations/churn_window_half_open_boundary
    """
    set_clock("2025-08-01T00:00:00Z")
    producer = register_producer()
    client = register_client(producer["id"])
    k_a = _register_kstd(api, producer["id"], client["id"], "CN-A", rider=False)
    k_b = _register_kstd(api, producer["id"], client["id"], "CN-B", rider=False)
    case_a = open_case(producer["id"], client["id"], k_a["id"])
    submit_case(case_a["id"], producer["id"])  # event at 2025-08-01

    set_clock("2025-08-02T00:00:00Z")
    case_b = open_case(producer["id"], client["id"], k_b["id"])
    submit_case(case_b["id"], producer["id"])  # event at 2025-08-02

    set_clock("2026-08-01T00:00:00Z")  # exactly 365 days after A's event
    producer_after = get_producer(producer["id"])
    assert producer_after["submitted_case_count_12m"] == 1, (
        "case A's event at exactly now-365d is excluded; case B's is inside"
    )
    assert producer_after["completed_exchange_count_12m"] == 0
    assert producer_after["rescinded_exchange_count_12m"] == 0


def test_churn_flag_sets_at_threshold_and_clears_on_aging(api):
    """PRD §3.8: "a producer is set to `FLAGGED` when
    `completed_exchange_count_12m` is at least 2 and
    `rescission_rate_completed_bps` is at least 5,000 basis points, and a later
    evaluation that finds the condition no longer holding automatically clears
    the producer back to `ACTIVE`."
    PRD §3.8: "Flag transitions fire `PRODUCER_FLAGGED` and
    `PRODUCER_UNFLAGGED` events."
    PRD §2.4: "Setting the clock has a mandatory side effect: the producer
    churn evaluation described in §3.8 is re-run for every registered producer,
    because rolling-window membership may shift with the new "now"."

    Design: Corner/cross_cutting_layers/churn_flag_set_at_threshold_then_aged_out
    """
    producer = register_producer()
    client = register_client(producer["id"], date_of_birth="1990-06-15")
    ks = [
        _register_kstd(api, producer["id"], client["id"], n, rider=False)
        for n in ("CN-A", "CN-B", "CN-C")
    ]
    cases = [
        _drive_to_free_look(api, producer["id"], client["id"], k["id"])[0]
        for k in ks
    ]
    case_a, case_b, case_c = cases

    # Case C rescinded at 2026-08-10 (inside its 20-day window).
    set_clock("2026-08-10T00:00:00Z")
    validate_success(api.rescind_case(case_c, make_producer_headers(producer["id"])))

    set_clock("2026-08-22T00:00:00Z")
    validate_success(api.complete_case(case_a, TEST_USERS["ops_headers"]))
    mid = get_producer(producer["id"])
    assert mid["completed_exchange_count_12m"] == 1
    assert mid["status"] == "ACTIVE", (
        "count threshold not yet met even though the rate is 10000 bps"
    )

    validate_success(api.complete_case(case_b, TEST_USERS["ops_headers"]))
    flagged = get_producer(producer["id"])
    assert flagged["completed_exchange_count_12m"] == 2
    assert flagged["rescinded_exchange_count_12m"] == 1
    assert flagged["rescission_rate_completed_bps"] == 5000
    assert flagged["status"] == "FLAGGED", "both inclusive thresholds met exactly"
    flag_events = [
        e for e in list_producer_events(producer["id"])
        if e["event_type"] == "PRODUCER_FLAGGED"
    ]
    assert len(flag_events) == 1, "PRODUCER_FLAGGED fires when the second completion lands"

    set_clock("2027-08-23T00:00:00Z")  # every event ages out of the window
    cleared = get_producer(producer["id"])
    assert cleared["submitted_case_count_12m"] == 0
    assert cleared["completed_exchange_count_12m"] == 0
    assert cleared["rescinded_exchange_count_12m"] == 0
    assert cleared["status"] == "ACTIVE", "automatic clear on clock-set re-evaluation"
    unflag_events = [
        e for e in list_producer_events(producer["id"])
        if e["event_type"] == "PRODUCER_UNFLAGGED"
    ]
    assert len(unflag_events) == 1, "the clock-set evaluation appends PRODUCER_UNFLAGGED"


def test_suspend_reinstate_cycle_with_audit_events(api, compliance_headers):
    """PRD §3.8: "A `ComplianceOfficer` suspends a producer from `ACTIVE` or
    `FLAGGED`, moving them to `SUSPENDED` with a `PRODUCER_SUSPENDED` event"
    PRD §3.8: "Reinstatement moves `SUSPENDED` → `ACTIVE` with a
    `PRODUCER_REINSTATED` event and immediately re-runs the churn evaluation in
    the same request — so if the thresholds are still met, the producer lands
    on `FLAGGED` rather than `ACTIVE`."
    PRD §2.9: "An **activity event** captures a `producer_id`, a `case_id`
    (null for producer-level events), an `event_type`, and the `event_at`
    logical-clock timestamp at which the event fired."

    Design: Corner/state_machines/producer_suspend_reinstate_cycle
    """
    producer = register_producer()

    suspended = validate_success(api.suspend_producer(producer["id"], compliance_headers))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2

    reinstated = validate_success(
        api.reinstate_producer(producer["id"], compliance_headers)
    )
    assert reinstated["status"] == "ACTIVE", (
        "empty counters: the churn re-evaluation cannot trip the flag"
    )
    assert reinstated["version"] == 3

    events = list_producer_events(producer["id"])
    assert [e["event_type"] for e in events] == [
        "PRODUCER_SUSPENDED",
        "PRODUCER_REINSTATED",
    ]
    assert all(e["case_id"] is None for e in events), (
        "producer-level events carry a null case_id"
    )
