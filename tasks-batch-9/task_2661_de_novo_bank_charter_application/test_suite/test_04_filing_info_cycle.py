"""
The information-request cycle and the ceiling that converts a fourth request into a denial.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    validate_success,
)

from test_helpers import CHARTERING_EXAMINER_HEADERS, fixtures as fx
from test_helpers.assertions import assert_fields_equal
from test_helpers.factories import filing_decision_payload
from test_helpers.types import (
    AUTHORITY_CHARTERING,
    BLOCKED_REASON_FILING_INFO_REQUESTED,
    DECISION_ADDITIONAL_INFO_REQUESTED,
    FILING_ADDITIONAL_INFO_REQUESTED,
    FILING_DENIED,
    FILING_FILED,
    PLAN_SUBMITTED,
    STAGE_ORGANIZING,
    STAGE_UNDER_REVIEW,
)


def _chartering_filing_at_round_three(api):
    """
    Both filings under review, with the chartering application having been round the
    information-request loop three times and re-filed each time, so it sits back in
    FILED with its round counter exhausted at 3.
    """
    world = fx.filing_ready_group(api)
    fx.both_filings_filed(api, world)
    for _ in range(3):
        fx.decide_filing(
            api, world["f_ca"], DECISION_ADDITIONAL_INFO_REQUESTED, AUTHORITY_CHARTERING
        )
        fx.file_filing(api, world["f_ca"])
    return world


# ---------------------------------------------------------------------------
# Difficulty / non_linear_state_machine
# ---------------------------------------------------------------------------
def test_the_first_three_information_requests_each_consume_one_round(api):
    """
    Rounds one, two and three are genuine information requests: each moves the filing out
    to counsel with the counter one higher, and each re-filing brings it back to FILED with
    the counter untouched. The counter is never reset along the way.

    PRD: "When the filing's `info_request_round` is currently less than 3, the decision increments `info_request_round` by one and moves `status` to `ADDITIONAL_INFO_REQUESTED`."
    PRD: "Rounds one, two and three are therefore information requests; the fourth attempt closes the file."

    Design: Difficulty/non_linear_state_machine/filing_info_request_cycle_bounded_at_three_rounds_then_denied
    """
    world = fx.filing_ready_group(api)
    fx.both_filings_filed(api, world)

    for expected_round in (1, 2, 3):
        requested = fx.decide_filing(
            api, world["f_ca"], DECISION_ADDITIONAL_INFO_REQUESTED, AUTHORITY_CHARTERING
        )
        assert_fields_equal(
            requested,
            status=FILING_ADDITIONAL_INFO_REQUESTED,
            info_request_round=expected_round,
        )
        refiled = fx.file_filing(api, world["f_ca"])
        assert_fields_equal(
            refiled, status=FILING_FILED, info_request_round=expected_round
        )

    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_UNDER_REVIEW)


def test_a_fourth_information_request_is_reinterpreted_as_an_outright_denial(api):
    """
    Asking a fourth time is neither honoured nor refused. The request succeeds, but the
    ceiling converts it: the filing goes straight to denied, the round counter stays at
    three rather than climbing to four, and the decision instant is stamped from the
    logical clock.

    PRD: "When `info_request_round` is already exactly 3, the very same request does **not** produce a fourth information round and is **not** rejected — the ceiling converts it into an outright denial, so `status` becomes `DENIED` with the full denial cascade below."

    Design: Difficulty/non_linear_state_machine/filing_info_request_cycle_bounded_at_three_rounds_then_denied
    """
    world = _chartering_filing_at_round_three(api)
    before = fx.read_filing(api, world["f_ca"])
    assert_fields_equal(before, status=FILING_FILED, info_request_round=3)

    response = api.record_filing_decision(
        world["f_ca"],
        filing_decision_payload(DECISION_ADDITIONAL_INFO_REQUESTED),
        CHARTERING_EXAMINER_HEADERS,
    )
    assert response.status_code == 200, (
        "the fourth information request must be accepted and reinterpreted, not refused"
    )
    denied = validate_success(response, expected_status=200)
    assert_fields_equal(denied, status=FILING_DENIED, info_request_round=3)
    assert is_iso8601_timestamp(denied["decision_at"]), (
        f"decision_at must carry the logical clock: {denied['decision_at']!r}"
    )
    assert denied["decision_at"].startswith("2026-08-01T00:00:00"), (
        "decision_at must be stamped from the logical clock's startup value"
    )


def test_the_denial_unwinds_the_group_and_leaves_the_other_authority_alone(api):
    """
    One authority closing its file drags the whole project back to organizing with the
    information-request block recorded on the group. The deposit insurer's application is
    untouched — still filed, still on round zero — and the plan, never pinned by anyone,
    remains submitted.

    PRD: "The group reverts from `UNDER_REVIEW` to `ORGANIZING` with `opening_blocked_reason` set to `FILING_INFO_REQUESTED`, every business plan of the group whose `status` is `PINNED` reverts to `SUBMITTED` with a version bump, and the group's `version` increments by one."

    Design: Difficulty/non_linear_state_machine/filing_info_request_cycle_bounded_at_three_rounds_then_denied
    """
    world = _chartering_filing_at_round_three(api)
    get_success_data(
        api.record_filing_decision(
            world["f_ca"],
            filing_decision_payload(DECISION_ADDITIONAL_INFO_REQUESTED),
            CHARTERING_EXAMINER_HEADERS,
        )
    )

    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        stage=STAGE_ORGANIZING,
        opening_blocked_reason=BLOCKED_REASON_FILING_INFO_REQUESTED,
    )
    assert_fields_equal(
        fx.read_filing(api, world["f_di"]), status=FILING_FILED, info_request_round=0
    )
    assert_fields_equal(fx.read_plan(api, world["plan_id"]), status=PLAN_SUBMITTED)
