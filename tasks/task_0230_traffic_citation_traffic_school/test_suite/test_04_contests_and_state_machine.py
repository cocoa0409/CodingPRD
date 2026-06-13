"""Contest/hearing cyclic state machine, parallel citation dimensions, verdicts, FTA."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_citation_payload,
    create_charge_payload,
    create_payment_payload,
    create_contest_request_payload,
    create_schedule_payload,
    create_decide_payload,
    make_driver_headers,
)
from test_helpers.fixtures import (
    setup_jurisdiction_and_driver,
    setup_assessed_citation,
    setup_contest_hearing_set,
    file_contest,
    set_clock,
    find_hold,
    list_warrants,
    list_point_ledger,
    CLERK,
    HEARING,
)


def test_contest_request_cyclic_continuance_loop(api):
    """PRD §3.7: "a `HearingOfficer` may grant a continuance, moving the request
    from `HEARING_SET` to `CONTINUANCE`, incrementing `continuance_count` by one and
    clearing the `hearing_at`; from `CONTINUANCE` the clerk schedules again back to
    `HEARING_SET` with a new future `hearing_at`."
    PRD §3.7: "At most two continuances may be granted — a third request, when
    `continuance_count` has already reached 2, is rejected with
    `ERR_CONTINUANCE_LIMIT`."

    Design: Difficulty/non_linear_state_machine/contest_request_cyclic_continuance_loop
    """
    jur, driver, cit, contest = setup_contest_hearing_set(clock="2026-01-05T00:00:00Z")
    # continue -> CONTINUANCE (count 1)
    c1 = validate_success(api.continue_hearing(contest["id"], HEARING), 200)
    assert c1["status"] == "CONTINUANCE"
    assert c1["continuance_count"] == 1
    # re-schedule -> HEARING_SET
    validate_success(
        api.schedule_hearing(contest["id"], create_schedule_payload("2026-03-15T00:00:00Z"), CLERK),
        200,
    )
    # continue again -> CONTINUANCE (count 2)
    c2 = validate_success(api.continue_hearing(contest["id"], HEARING), 200)
    assert c2["continuance_count"] == 2
    assert c2["status"] == "CONTINUANCE"


def test_third_continuance_rejected_at_limit(api):
    """PRD §3.7: "At most two continuances may be granted — a third request, when
    `continuance_count` has already reached 2, is rejected with
    `ERR_CONTINUANCE_LIMIT`."

    Design: Difficulty/non_linear_state_machine/contest_request_cyclic_continuance_loop
    """
    jur, driver, cit, contest = setup_contest_hearing_set(clock="2026-01-05T00:00:00Z")
    api.continue_hearing(contest["id"], HEARING)
    api.schedule_hearing(contest["id"], create_schedule_payload("2026-03-10T00:00:00Z"), CLERK)
    api.continue_hearing(contest["id"], HEARING)  # count 2
    api.schedule_hearing(contest["id"], create_schedule_payload("2026-03-20T00:00:00Z"), CLERK)
    res = api.continue_hearing(contest["id"], HEARING)
    validate_error(res, "ERR_CONTINUANCE_LIMIT")


def test_continuance_limit_exceeded_returns_error(api):
    """PRD §3.7: "At most two continuances may be granted — a third request, when
    `continuance_count` has already reached 2, is rejected with
    `ERR_CONTINUANCE_LIMIT`."

    Design: Corner/state_machines/continuance_limit_exceeded_returns_error
    """
    jur, driver, cit, contest = setup_contest_hearing_set(clock="2026-01-05T00:00:00Z")
    api.continue_hearing(contest["id"], HEARING)
    api.schedule_hearing(contest["id"], create_schedule_payload("2026-03-10T00:00:00Z"), CLERK)
    api.continue_hearing(contest["id"], HEARING)
    api.schedule_hearing(contest["id"], create_schedule_payload("2026-03-20T00:00:00Z"), CLERK)
    res = api.continue_hearing(contest["id"], HEARING)
    validate_error(res, "ERR_CONTINUANCE_LIMIT")
    after = validate_success(api.get_contest_request(contest["id"], HEARING), 200)
    assert after["continuance_count"] == 2


def test_citation_parallel_financial_and_adjudication_dimensions(api):
    """PRD §3.2: "The two status fields are independent: `financial_status` tracks
    money (`DRAFT`, `ASSESSED`, `PARTIALLY_PAID`, `PAID`, `VOID`) and
    `adjudication_status` tracks the legal dispute (`NONE`, `CONTESTED`, `DISMISSED`,
    `UPHELD`)."
    PRD §3.4: "When a payment leaves the balance still above zero, an `ASSESSED`
    citation moves to `PARTIALLY_PAID`, and a citation already `PARTIALLY_PAID`
    stays there."
    PRD §3.7: "Filing one opens the request in `REQUESTED` and sets the citation's
    `adjudication_status` to `CONTESTED`."

    Design: Difficulty/non_linear_state_machine/citation_parallel_financial_and_adjudication_dimensions
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    # Partial payment 10000 -> PARTIALLY_PAID.
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(10000, method="CASH"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    # File a contest -> CONTESTED, independent of financial dimension.
    file_contest(cit["id"], driver["id"], grounds="Wrong driver")
    citation = validate_success(
        api.get_citation(cit["id"], make_driver_headers(driver["id"])), 200
    )
    assert citation["financial_status"] == "PARTIALLY_PAID"
    assert citation["adjudication_status"] == "CONTESTED"
    assert citation["balance_cents"] == 19000
    assert citation["disposition"] == "OPEN"


def test_disposition_stays_open_while_both_dimensions_non_closing(api):
    """PRD §3.2: "The `disposition` flips from `OPEN` to `CLOSED` exactly when the
    citation becomes `PAID`, when its adjudication becomes `DISMISSED`, or when it
    becomes `VOID`."
    PRD §3.2: "The two status fields are independent: `financial_status` tracks money
    (`DRAFT`, `ASSESSED`, `PARTIALLY_PAID`, `PAID`, `VOID`) and `adjudication_status`
    tracks the legal dispute (`NONE`, `CONTESTED`, `DISMISSED`, `UPHELD`)."

    Design: Difficulty/non_linear_state_machine/citation_parallel_financial_and_adjudication_dimensions
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    # Partial payment leaves balance > 0 (PARTIALLY_PAID, not a closing state).
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(5000, method="CARD"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    # Contest moves adjudication to CONTESTED (not a closing state).
    file_contest(cit["id"], driver["id"], grounds="Still disputing")
    citation = validate_success(
        api.get_citation(cit["id"], make_driver_headers(driver["id"])), 200
    )
    assert citation["financial_status"] == "PARTIALLY_PAID"
    assert citation["adjudication_status"] == "CONTESTED"
    assert citation["disposition"] == "OPEN"


def test_contest_request_starts_in_requested(api):
    """PRD §3.7: "Filing one opens the request in `REQUESTED` and sets the
    citation's `adjudication_status` to `CONTESTED`."
    PRD §3.7: "The request tracks a `hearing_at` time (set once a hearing is
    scheduled), a `continuance_count` that begins at zero, and a `status` that walks
    `REQUESTED`, `HEARING_SET`, `CONTINUANCE`, and the terminal `DISMISSED`,
    `UPHELD`, or `FTA`."

    Design: Corner/state_machines/contest_request_starts_in_requested
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    contest = validate_success(
        api.create_contest_request(
            cit["id"], create_contest_request_payload(grounds="I was not speeding"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    assert contest["status"] == "REQUESTED"
    assert contest["continuance_count"] == 0
    citation = validate_success(
        api.get_citation(cit["id"], make_driver_headers(driver["id"])), 200
    )
    assert citation["adjudication_status"] == "CONTESTED"


def test_dismiss_zeroes_balance_and_closes_citation(api):
    """PRD §3.7: "A `verdict` of `DISMISS` moves the request to `DISMISSED`, sets the
    citation's `adjudication_status` to `DISMISSED`, and closes the citation's
    `disposition`; as a cascade the citation's `balance_cents` is forced directly to
    zero because the charges are vacated, with `financial_status` left untouched
    unless it was already `PAID`, any open hold for the citation released, any active
    warrant quashed, and no points posted."

    Design: Corner/state_machines/dismiss_zeroes_balance_and_closes_citation
    """
    jur, driver, cit, contest = setup_contest_hearing_set(
        clock="2026-01-05T00:00:00Z",
        charge_overrides={"base_fine_cents": 20000},
    )
    decided = validate_success(
        api.decide_contest(contest["id"], create_decide_payload("DISMISS"), HEARING), 200
    )
    assert decided["status"] == "DISMISSED"
    citation = validate_success(
        api.get_citation(cit["id"], make_driver_headers(driver["id"])), 200
    )
    assert citation["adjudication_status"] == "DISMISSED"
    assert citation["balance_cents"] == 0
    assert citation["disposition"] == "CLOSED"
    entries = list_point_ledger(driver_id=driver["id"])
    assert len(entries) == 0


def test_fta_creates_warrant_and_fta_hold(api):
    """PRD §3.7: "Failure to appear moves the request's `status` to `FTA` while
    leaving the citation's `adjudication_status` at `CONTESTED`, and cascades three
    levels deep: it creates an `ACTIVE` **Warrant** whose `reason` is `FTA_HEARING`,
    the warrant opens a failure-to-appear hold for the citation, and that hold
    re-derives the driver's `license_status` to `HELD`."
    PRD §2.7: "The `fta_warrant_active` flag is true exactly when the driver has at
    least one active warrant."

    Design: Corner/state_machines/fta_creates_warrant_and_fta_hold
    """
    jur, driver, cit, contest = setup_contest_hearing_set(
        clock="2026-01-05T00:00:00Z",
        hearing_at="2026-03-01T00:00:00Z",
        charge_overrides={"base_fine_cents": 20000},
    )
    set_clock("2026-03-02T00:00:00Z")
    fta = validate_success(api.fail_to_appear(contest["id"], CLERK), 200)
    assert fta["status"] == "FTA"
    warrants = list_warrants(citation_id=cit["id"], status="ACTIVE")
    assert len(warrants) == 1
    assert warrants[0]["reason"] == "FTA_HEARING"
    hold = find_hold(citation_id=cit["id"], hold_type="FTA_HOLD", status="OPEN")
    assert hold is not None
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["license_status"] == "HELD"
    assert driver_after["fta_warrant_active"] is True


def test_continue_before_hearing_set_returns_invalid_state(api):
    """PRD §3.7: "The track is cyclic: a `HearingOfficer` may grant a continuance,
    moving the request from `HEARING_SET` to `CONTINUANCE`, incrementing
    `continuance_count` by one and clearing the `hearing_at`; from `CONTINUANCE` the
    clerk schedules again back to `HEARING_SET` with a new future `hearing_at`."
    PRD §2.9: "Only then are state-machine preconditions evaluated, with an
    out-of-state target yielding `ERR_INVALID_STATE`; followed by time-gating checks
    yielding `ERR_NOT_YET_LATE`; followed by the remaining business constraints
    described throughout §3."

    Design: Corner/state_machines/continue_before_hearing_set_returns_invalid_state
    """
    jur, driver, cit = setup_assessed_citation(charge_overrides={"base_fine_cents": 20000})
    contest = file_contest(cit["id"], driver["id"])  # REQUESTED, never scheduled
    res = api.continue_hearing(contest["id"], HEARING)
    validate_error(res, "ERR_INVALID_STATE")


def test_warrant_quash_after_citation_closed_succeeds(api):
    """PRD §3.8: "Quashing stamps `quashed_at` and re-derives the driver's
    `fta_warrant_active`."
    PRD §3.4: "any active warrant for the citation is quashed and the driver's
    `fta_warrant_active` flag is re-derived; and any active installment plan is
    marked `COMPLETED` with its remaining scheduled installments flipped to `PAID`."

    Design: Corner/state_machines/warrant_quash_after_citation_closed_succeeds
    """
    jur, driver, cit, contest = setup_contest_hearing_set(
        clock="2026-01-05T00:00:00Z",
        hearing_at="2026-03-01T00:00:00Z",
        charge_overrides={"base_fine_cents": 20000},
    )
    set_clock("2026-03-02T00:00:00Z")
    api.fail_to_appear(contest["id"], CLERK)
    # Pay in full -> warrant auto-quashed.
    citation = validate_success(api.get_citation(cit["id"], CLERK), 200)
    validate_success(
        api.create_payment(
            cit["id"], create_payment_payload(citation["balance_cents"], method="CARD"),
            make_driver_headers(driver["id"]),
        ),
        201,
    )
    paid = validate_success(api.get_citation(cit["id"], CLERK), 200)
    assert paid["financial_status"] == "PAID"
    warrants = list_warrants(citation_id=cit["id"])
    assert len(warrants) == 1
    assert warrants[0]["status"] == "QUASHED"
    driver_after = validate_success(api.get_driver(driver["id"], CLERK), 200)
    assert driver_after["fta_warrant_active"] is False
