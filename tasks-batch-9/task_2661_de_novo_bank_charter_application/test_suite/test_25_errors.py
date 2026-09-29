"""
Refusals in their own right: the unauthenticated request, the wrong role, the right
role on the wrong authority, the clock that will not run backwards and the
zero-length outage window.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    CHARTERING_EXAMINER_HEADERS,
    COUNSEL_HEADERS,
    ESCROW_AGENT_HEADERS,
    INSURANCE_EXAMINER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    fixtures as fx,
    headers_without_role,
)
from test_helpers.assertions import assert_fields_equal, assert_two_decimal_places
from test_helpers.factories import (
    advance_payload,
    conversion_window_payload,
    filing_decision_payload,
)
from test_helpers.types import (
    BLOCKED_REASON_NONE,
    DECISION_CONDITIONALLY_APPROVED,
    FILING_CONDITIONALLY_APPROVED,
    FILING_FILED,
    PLAN_PINNED,
    STAGE_FILING_READY,
    STAGE_ORGANIZING,
    STAGE_UNDER_REVIEW,
    WINDOW_RESERVED,
)


# ---------------------------------------------------------------------------
# Corner / errors
# ---------------------------------------------------------------------------
def test_a_request_with_no_declared_role_is_stopped_before_anything_is_read(
    api, composition_met_group
):
    """
    The two header checks run ahead of everything. With no role declared at all the request is
    unauthenticated even though the group it names exists and could have been read, so the
    refusal is not about permissions and the body carries no trace of the group. Nothing is
    written.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the seven declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD: "These two checks run before anything else in the request, in that order."

    Design: Corner/errors/error_missing_x_user_role_header_is_unauthenticated
    """
    world = composition_met_group

    error = validate_error(
        api.get_organizing_group(world["group_id"], headers_without_role()),
        "ERR_UNAUTHENTICATED",
        expected_status=401,
    )
    assert error["error_id"] != "ERR_ROLE_NOT_PERMITTED", (
        "an absent role is an authentication failure, not an authorization one"
    )
    assert "stage" not in error, (
        "the refusal must not leak any field of the group it never read"
    )
    assert_fields_equal(
        fx.read_group(api, world["group_id"]), stage=STAGE_ORGANIZING
    )


def test_the_escrow_agent_cannot_move_the_project_forward(api, submitted_plan_group):
    """
    Every business precondition for leaving the organizing stage is satisfied — the board is
    complete, the composite is 71.80 and a plan has been submitted — so the only thing standing
    in the way is the caller. The escrow agent is refused on the role, and the identical request
    from counsel goes through and clears the blocking reason.

    PRD: "If the role is declared but is not among the roles authorized for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD: "Advancing `ORGANIZING` to `FILING_READY` requires the group's `composition_status` to be `COMPOSITION_MET` (`ERR_GROUP_COMPOSITION_INCOMPLETE`), then its `management_composite_score` to be at least 70.00 (`ERR_MANAGEMENT_SCORE_BELOW_MINIMUM`), then at least one business plan of the group in `SUBMITTED` status (`ERR_NO_SUBMITTED_BUSINESS_PLAN`) — in that order."
    PRD: "On success `opening_blocked_reason` is reset to `NONE`."

    Design: Corner/errors/error_escrow_agent_cannot_advance_the_group
    """
    world = submitted_plan_group
    before = fx.read_group(api, world["group_id"])
    assert_two_decimal_places(
        before["management_composite_score"], 71.80, "management_composite_score"
    )

    validate_error(
        api.advance_group(
            world["group_id"], advance_payload(STAGE_FILING_READY), ESCROW_AGENT_HEADERS
        ),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_ORGANIZING)

    advanced = validate_success(
        api.advance_group(
            world["group_id"], advance_payload(STAGE_FILING_READY), COUNSEL_HEADERS
        ),
        expected_status=200,
    )
    assert_fields_equal(
        advanced, stage=STAGE_FILING_READY, opening_blocked_reason=BLOCKED_REASON_NONE
    )


def test_the_deposit_insurer_s_examiner_may_not_decide_the_chartering_application(api):
    """
    The deposit insurer's examiner is genuinely on the decision endpoint's roster, so this is
    not a role refusal — it is a refusal to let one authority sign the other's file. The
    chartering application is left filed and undecided. Its own examiner then approves it,
    which pins the plan, while the project stays under review because the insurer's own
    application has not been decided at all.

    PRD: "Because the role genuinely is in the endpoint's role list, a cross-authority attempt is `ERR_EXAMINER_AUTHORITY_MISMATCH` (HTTP 403) and never `ERR_ROLE_NOT_PERMITTED`."
    PRD: "This check applies to recording a filing decision, to attaching a condition of approval to a filing, and to adjudicating a condition (evaluated through the condition's parent filing)."
    PRD: "When the filing's `authority` is `CHARTERING_AUTHORITY`, its pinned business plan moves from `SUBMITTED` to `PINNED` and that plan's `version` increments by one — this is the moment the plan becomes the fixed benchmark for heightened supervision."

    Design: Corner/errors/error_insurance_examiner_cannot_decide_the_chartering_filing
    """
    world = fx.filing_ready_group(api)
    fx.both_filings_filed(api, world)

    error = validate_error(
        api.record_filing_decision(
            world["f_ca"],
            filing_decision_payload(DECISION_CONDITIONALLY_APPROVED),
            INSURANCE_EXAMINER_HEADERS,
        ),
        "ERR_EXAMINER_AUTHORITY_MISMATCH",
        expected_status=403,
    )
    assert error["error_id"] != "ERR_ROLE_NOT_PERMITTED", (
        "the insurance examiner is on the decision endpoint's roster, so the "
        "refusal must name the authority mismatch"
    )
    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]), status=FILING_FILED, decision_at=None
    )

    decided = validate_success(
        api.record_filing_decision(
            world["f_ca"],
            filing_decision_payload(DECISION_CONDITIONALLY_APPROVED),
            CHARTERING_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(decided, status=FILING_CONDITIONALLY_APPROVED)
    assert_fields_equal(fx.read_plan(api, world["plan_id"]), status=PLAN_PINNED)
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_UNDER_REVIEW)
    assert_fields_equal(fx.read_filing(api, world["f_di"]), status=FILING_FILED)


def test_the_logical_clock_stands_still_but_never_walks_back(api):
    """
    From the first of September, a second earlier is refused: the clock is monotonic. Re-setting
    it to the very instant it already reads is accepted, which is what makes the rule "at or
    after" rather than "after", and a second later is accepted as well.

    PRD: "The clock moves forward only: a `to_iso8601` earlier than the clock's current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), while a value equal to the current instant is accepted."
    PRD: "A `PlatformAdmin` moves the clock forward by supplying `to_iso8601`; the response carries the new value as `current_utc`."

    Design: Corner/errors/error_clock_cannot_move_backwards
    """
    fx.set_clock(api, "2026-09-01T00:00:00Z")

    validate_error(
        api.set_clock("2026-08-31T23:59:59Z", PLATFORM_ADMIN_HEADERS),
        "ERR_CLOCK_NOT_MONOTONIC",
        expected_status=422,
    )

    same = validate_success(
        api.set_clock("2026-09-01T00:00:00Z", PLATFORM_ADMIN_HEADERS),
        expected_status=200,
    )
    assert same["current_utc"].startswith("2026-09-01T00:00:00"), (
        f"the equality case must be accepted and reported: {same['current_utc']!r}"
    )

    later = validate_success(
        api.set_clock("2026-09-01T00:00:01Z", PLATFORM_ADMIN_HEADERS),
        expected_status=200,
    )
    assert later["current_utc"].startswith("2026-09-01T00:00:01"), (
        f"the clock must move forward on request: {later['current_utc']!r}"
    )


def test_a_zero_length_outage_window_is_refused_and_a_one_hour_one_is_not(api):
    """
    An outage that ends when it begins is not an outage. The zero-length request is refused and
    the contract is left untouched — same empty calendar, same version, because a refused create
    is not a mutation of the parent. Pushing the end out by a single hour is enough: the window
    is reserved and reports 1.00 hours exactly.

    PRD: "The end must be strictly after the start, so a zero-length window is refused with `ERR_WINDOW_END_NOT_AFTER_START` (HTTP 422), and the start must be at or after the current logical clock, so a window starting exactly now is fine but one starting a second ago is refused with `ERR_WINDOW_START_IN_PAST` (HTTP 422)."
    PRD: "`duration_hours` is derived as the elapsed seconds between the two instants divided by 3600 and rounded half up to two decimal places, and it may not exceed 72.00 hours — a three-day outage is the ceiling, so exactly 72.00 hours is accepted and 72.01 is refused with `ERR_WINDOW_TOO_LONG` (HTTP 422)."
    PRD: "On success the window begins in `RESERVED`, the contract's `active_window_count` is recomputed as the number of its `RESERVED` or `CONFIRMED` windows — counting all occupants, not merely the overlapping ones — and the contract's `version` increments by one."

    Design: Corner/errors/error_window_end_equal_to_start_is_rejected
    """
    world = fx.open_group(api)
    contract_id = fx.signed_core_vendor(api, world)
    before = fx.read_contract(api, contract_id)
    assert_fields_equal(before, active_window_count=0)

    validate_error(
        api.create_conversion_window(
            conversion_window_payload(
                contract_id,
                before["version"],
                "2026-09-02T12:00:00Z",
                "2026-09-02T12:00:00Z",
            ),
            COUNSEL_HEADERS,
        ),
        "ERR_WINDOW_END_NOT_AFTER_START",
        expected_status=422,
    )
    assert_fields_equal(
        fx.read_contract(api, contract_id),
        active_window_count=0,
        version=before["version"],
    )

    window = get_success_data(
        api.create_conversion_window(
            conversion_window_payload(
                contract_id,
                before["version"],
                "2026-09-02T12:00:00Z",
                "2026-09-02T13:00:00Z",
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(window, status=WINDOW_RESERVED)
    assert_two_decimal_places(window["duration_hours"], 1.00, "duration_hours")
    assert_fields_equal(fx.read_contract(api, contract_id), active_window_count=1)
