"""Case lifecycle basics: idempotent-trigger rejection, silent DRAFT
withdrawal, terminal lockdown, immediate consistency, and counter
reconciliation (PRD §2.3, §2.8, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_logical_instant,
    get_case,
    get_producer,
    list_producer_events,
    make_principal_headers,
    make_producer_headers,
    make_reviewer_headers,
    open_case,
    rationale_payload,
    register_client,
    register_contract,
    register_producer,
    setup_case_in_review,
    start_review,
    submit_case,
    validate_error,
    validate_success,
)


def test_submit_twice_rejected_invalid_state(api):
    """PRD §2.8: "Sixth, state legality of the requested transition is checked
    (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — or
    `ERR_CONTRACT_NOT_IN_FORCE` for the contract precondition on case
    submission)."
    PRD §3.2: "Submitting a case — the `DRAFT` → `SUBMITTED` transition by the
    owning producer — is where the desk's protective gates run, and they run in
    a fixed order." The second submit no longer has a declared from-state.

    Design: Corner/state_machines/submit_twice_returns_invalid_state
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"], living_benefit_rider=False,
        surrender_schedule=[{"contract_year": 1, "pct_bps": 700}],
    )
    case = open_case(producer["id"], client["id"], contract["id"])
    submit_case(case["id"], producer["id"])

    res = api.submit_case(case["id"], make_producer_headers(producer["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    case_after = get_case(case["id"])
    assert case_after["status"] == "SUBMITTED"
    assert case_after["version"] == 2
    submitted_events = [
        e for e in list_producer_events(producer["id"])
        if e["event_type"] == "CASE_SUBMITTED"
    ]
    assert len(submitted_events) == 1, "exactly one CASE_SUBMITTED event"


def test_withdraw_from_draft_emits_no_activity_event(api):
    """PRD §3.2: "Withdrawal from `DRAFT` is silent (no activity event, since
    the case was never submitted); withdrawal from any of the later states
    appends `CASE_WITHDRAWN` and recomputes the producer counters."

    Design: Corner/state_machines/withdraw_from_draft_leaves_no_activity
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"], living_benefit_rider=False,
        surrender_schedule=[{"contract_year": 1, "pct_bps": 700}],
    )
    case = open_case(producer["id"], client["id"], contract["id"])

    withdrawn = validate_success(
        api.withdraw_case(case["id"], make_producer_headers(producer["id"]))
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["version"] == 2
    assert list_producer_events(producer["id"]) == [], (
        "no CASE_WITHDRAWN for a never-submitted case"
    )


def test_rejected_case_is_terminal_and_releases_contract(api):
    """PRD §3.2: "The full lifecycle vocabulary is `DRAFT`, `SUBMITTED`,
    `SUITABILITY_REVIEW`, `INFO_REQUESTED`, `PENDING_PRINCIPAL`, `APPROVED`,
    `FUNDS_REQUESTED`, `FUNDS_RECEIVED`, `IN_FREE_LOOK`, `COMPLETED`,
    `REJECTED`, `WITHDRAWN`, and `RESCINDED`, with `COMPLETED`, `REJECTED`,
    `WITHDRAWN`, and `RESCINDED` terminal."
    PRD §3.5: "Either stage can kill the case. The reviewer rejects from
    `SUITABILITY_REVIEW`, the principal from `PENDING_PRINCIPAL`; rejection
    moves the case to `REJECTED`, appends a review decision whose `stage`
    matches the rejecting role with decision `REJECT` and the supplied
    `rationale`, and appends a `CASE_REJECTED` activity event for the
    producer."

    Design: Corner/state_machines/terminal_rejected_case_lockdown
    """
    bundle = setup_case_in_review()
    producer_id = bundle["producer"]["id"]
    case_id = bundle["case_id"]
    rejected = validate_success(
        api.reject_case(
            case_id, rationale_payload("unsuitable"), make_reviewer_headers("rev-1")
        )
    )
    assert rejected["status"] == "REJECTED"

    for res in (
        api.submit_case(case_id, make_producer_headers(producer_id)),
        api.recommend_case(
            case_id, rationale_payload("retry"), make_reviewer_headers("rev-1")
        ),
        api.approve_case(
            case_id, rationale_payload("override"), make_principal_headers("prin-1")
        ),
    ):
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_case(case_id)["status"] == "REJECTED"

    rejected_events = [
        e for e in list_producer_events(producer_id)
        if e["event_type"] == "CASE_REJECTED"
    ]
    assert len(rejected_events) == 1

    # The terminal rejection closed the occupation interval on the contract.
    case_b = open_case(producer_id, bundle["client"]["id"], bundle["contract"]["id"])
    submitted = validate_success(
        api.submit_case(case_b["id"], make_producer_headers(producer_id))
    )
    assert submitted["status"] == "SUBMITTED"


def test_read_after_submit_immediately_reflects_transition(api, principal_headers):
    """PRD §3.2: "A successful submission stamps `submitted_at` with the
    logical clock, bumps the case `version`, appends a `CASE_SUBMITTED`
    activity event for the producer, recomputes the producer's twelve-month
    counters, and runs the churn evaluation of §3.8."
    The platform's consistency model is immediate: the very next read shows the
    transitioned state with no staleness window.

    Design: Corner/consistency_model/immediate_read_after_transition
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"], living_benefit_rider=False,
        surrender_schedule=[{"contract_year": 1, "pct_bps": 700}],
    )
    case = open_case(producer["id"], client["id"], contract["id"])
    validate_success(api.submit_case(case["id"], make_producer_headers(producer["id"])))

    read_back = validate_success(api.get_case(case["id"], principal_headers))
    assert read_back["status"] == "SUBMITTED"
    assert read_back["version"] == 2
    assert_logical_instant(
        read_back["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at"
    )


def test_producer_counters_reconcile_on_first_submit(api):
    """PRD §3.1: "A newly registered producer starts in `ACTIVE` status with
    all twelve-month counters at zero and `last_churn_eval_at` null until the
    first churn evaluation runs."
    PRD §3.2: "A successful submission stamps `submitted_at` with the logical
    clock, bumps the case `version`, appends a `CASE_SUBMITTED` activity event
    for the producer, recomputes the producer's twelve-month counters, and runs
    the churn evaluation of §3.8."

    Design: Corner/cross_cutting_layers/derived_counters_after_first_submit
    """
    producer = register_producer()
    before = get_producer(producer["id"])
    assert before["status"] == "ACTIVE"
    assert before["submitted_case_count_12m"] == 0
    assert before["completed_exchange_count_12m"] == 0
    assert before["rescinded_exchange_count_12m"] == 0
    assert before["rescission_rate_completed_bps"] == 0
    assert before["rescission_rate_submitted_bps"] == 0

    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"], living_benefit_rider=False,
        surrender_schedule=[{"contract_year": 1, "pct_bps": 700}],
    )
    case = open_case(producer["id"], client["id"], contract["id"])
    submit_case(case["id"], producer["id"])

    after = get_producer(producer["id"])
    assert after["submitted_case_count_12m"] == 1
    assert after["completed_exchange_count_12m"] == 0
    assert after["rescinded_exchange_count_12m"] == 0
