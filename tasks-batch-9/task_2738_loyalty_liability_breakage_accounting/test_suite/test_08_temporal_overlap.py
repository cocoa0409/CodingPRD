"""
Two coexisting window conventions, and the buffer one of them carries.

An accounting period's window is half-open, so touching is legal and a single
millisecond of genuine overlap is not. A partner agreement's window is closed and
additionally has to clear the prior agreement's settlement tail, so adjacency is
not enough. Both families of test also pin the ladder: a degenerate window is
caught above the relational check, so a body that is both malformed and colliding
is reported as malformed.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_created,
    assert_error,
    assert_fields,
    assert_ok,
    assert_page,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AGREEMENT_TERMINATED,
    CLOCK_EPOCH,
    PERIOD_AUG_END,
    PERIOD_AUG_START,
    PERIOD_OPEN,
    PERIOD_SEP_END,
    PERIOD_SEP_START,
    RELATIONSHIP_INTERCOMPANY,
    RELATIONSHIP_THIRD_PARTY,
    STATE_TX,
)
from test_helpers.test_users import CONTROLLER_HEADERS, PROGRAM_ADMIN_HEADERS

# ─── Accounting period windows, all half-open [start_at, end_at) ─────────────
AUG_CODE = "2026-08"
SEP_CODE = "2026-09"
NOV_CODE = "2026-11"
NOV_START = "2026-11-01T00:00:00Z"
NOV_END = "2026-12-01T00:00:00Z"

# One millisecond before August's end_at is still inside August's window.
OVERLAP_CODE = "2026-08X"
OVERLAP_START = "2026-08-31T23:59:59.999Z"
OVERLAP_END = "2026-09-15T00:00:00Z"

# August's window again under an unused label, so only the window rule can fire.
TWIN_CODE = "2026-08Y"

# A window whose start is strictly after its end, and which also collides.
DEGENERATE_CODE = "2026-08Z"
DEGENERATE_START = "2026-08-15T00:00:00Z"
DEGENERATE_END = "2026-08-01T00:00:00Z"

# ─── Partner agreement windows, closed at both ends plus a lag buffer ────────
PARTNER_CODE = "PG"
OTHER_PARTNER_CODE = "PH"
LAG_DAYS = 30

FIRST_START = "2026-01-01T00:00:00Z"
FIRST_END = "2026-06-30T00:00:00Z"

# FIRST_END advanced by the prior agreement's own 30 whole days, inclusive.
BUFFER_BOUNDARY_START = "2026-07-30T00:00:00Z"
CLEAR_OF_BUFFER_START = "2026-07-31T00:00:00Z"
SUCCESSOR_END = "2026-12-31T00:00:00Z"

# A malformed successor window that would also land on the buffer boundary.
BAD_WINDOW_START = "2026-07-30T00:00:00Z"
BAD_WINDOW_END = "2026-07-01T00:00:00Z"

# A malformed successor window well clear of every buffer.
LATE_BAD_WINDOW_START = "2027-06-01T00:00:00Z"
LATE_BAD_WINDOW_END = "2027-05-01T00:00:00Z"

ISSUANCE_RATE_MILLICENTS = 900
REDEMPTION_RATE_MILLICENTS = 1100


# ─── Setup shared by several tests ───────────────────────────────────────────
def _live_program(api):
    """An ACTIVE programme with no period and no partner agreement of its own."""
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(
        api,
        program["id"],
        state_code=STATE_TX,
        escheatment_required=False,
        escheat_rate_bp=0,
    )
    fixtures.new_cohort(api, program["id"])
    return fixtures.activate(api, program["id"])


def _open_period(api, program_id, period_code, start_at, end_at):
    """Attempt one accounting period window; the raw response, unchecked."""
    return api.create_period(
        factories.period_payload(
            program_id, period_code=period_code, start_at=start_at, end_at=end_at
        ),
        CONTROLLER_HEADERS,
    )


def _register_agreement(
    api, program_id, partner_code, start_at, end_at, **overrides
):
    """Attempt one partner agreement window; the raw response, unchecked."""
    payload = factories.agreement_payload(
        program_id,
        partner_code=partner_code,
        settlement_lag_days=LAG_DAYS,
        issuance_rate_millicents_per_point=ISSUANCE_RATE_MILLICENTS,
        redemption_rate_millicents_per_point=REDEMPTION_RATE_MILLICENTS,
        effective_start_date=start_at,
        effective_end_date=end_at,
        **overrides,
    )
    return api.create_agreement(payload, PROGRAM_ADMIN_HEADERS)


# ─── Half-open accounting period windows ─────────────────────────────────────
def test_adjacent_period_windows_are_accepted_and_gaps_are_permitted(api):
    """
    September starts at exactly the instant August ends, and under the half-open
    reading those windows merely touch rather than overlap, so the second create
    must be accepted with its start_at equal byte-for-byte to the first's end_at.
    A November window that leaves October entirely uncovered is accepted too, so
    the calendar is allowed to have holes in it.

    "An accounting period's window runs from `start_at` inclusive to `end_at` exclusive — a half-open interval, so two periods that merely touch at an instant do not overlap."
    "The new window must not overlap any existing period of the same programme, and a violation is `ERR_PERIOD_OVERLAP` — but because the interval is half-open, a window that begins at exactly the instant another window ends is adjacent rather than overlapping and is accepted, and gaps between windows are permitted too."

    Design: Difficulty/resource_temporal_overlap/temporal_accounting_period_adjacent_allowed_overlap_rejected
    """
    program = _live_program(api)

    august = assert_created(
        _open_period(api, program["id"], AUG_CODE, PERIOD_AUG_START, PERIOD_AUG_END)
    )
    assert_fields(
        august,
        state=PERIOD_OPEN,
        start_at=PERIOD_AUG_START,
        end_at=PERIOD_AUG_END,
        reopen_count=0,
    )

    september = assert_created(
        _open_period(api, program["id"], SEP_CODE, PERIOD_SEP_START, PERIOD_SEP_END)
    )
    assert_fields(september, state=PERIOD_OPEN, start_at=august["end_at"])

    november = assert_created(
        _open_period(api, program["id"], NOV_CODE, NOV_START, NOV_END)
    )
    assert_fields(november, state=PERIOD_OPEN, start_at=NOV_START, end_at=NOV_END)

    assert_page(
        api.list_periods(CONTROLLER_HEADERS, program_id=program["id"]),
        expected_ids=[august["id"], september["id"], november["id"]],
        total_count=3,
    )


def test_period_window_overlapping_by_one_millisecond_or_wholly_is_rejected(api):
    """
    The half-open reading cuts both ways: a window beginning at
    2026-08-31T23:59:59.999Z is still inside August's window and is refused, and so
    is a second attempt at August's exact window under an unused label — which
    proves the refusal comes from the window rule rather than from the uniqueness
    of the period code. Neither refusal leaves a row behind.

    "The new window must not overlap any existing period of the same programme, and a violation is `ERR_PERIOD_OVERLAP` — but because the interval is half-open, a window that begins at exactly the instant another window ends is adjacent rather than overlapping and is accepted, and gaps between windows are permitted too."
    "The label must be unique within the programme, else `ERR_DUPLICATE_CODE`."
    "**Period windows do not overlap** — `ERR_PERIOD_OVERLAP` (409), on period create."

    Design: Difficulty/resource_temporal_overlap/temporal_accounting_period_adjacent_allowed_overlap_rejected
    """
    program = _live_program(api)
    august = assert_created(
        _open_period(api, program["id"], AUG_CODE, PERIOD_AUG_START, PERIOD_AUG_END)
    )
    september = assert_created(
        _open_period(api, program["id"], SEP_CODE, PERIOD_SEP_START, PERIOD_SEP_END)
    )

    assert_error(
        _open_period(api, program["id"], OVERLAP_CODE, OVERLAP_START, OVERLAP_END),
        ApiErrorId.PERIOD_OVERLAP.value,
    )
    assert_error(
        _open_period(api, program["id"], TWIN_CODE, PERIOD_AUG_START, PERIOD_AUG_END),
        ApiErrorId.PERIOD_OVERLAP.value,
    )

    assert_page(
        api.list_periods(CONTROLLER_HEADERS, program_id=program["id"]),
        expected_ids=[august["id"], september["id"]],
        total_count=2,
    )
    assert_page(
        api.list_periods(CONTROLLER_HEADERS, period_code=OVERLAP_CODE), total_count=0
    )
    assert_page(
        api.list_periods(CONTROLLER_HEADERS, period_code=TWIN_CODE), total_count=0
    )


def test_degenerate_period_window_is_reported_above_the_overlap_check(api):
    """
    The window from 2026-08-15 back to 2026-08-01 is malformed and also collides
    with the existing August period, so two rungs are violated at once. The
    malformed-window rung sits above the overlap rung, so the answer must be
    ERR_INVALID_WINDOW; reporting the collision instead would mean the ladder had
    been walked in the wrong order.

    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."
    "**Window sanity** — `ERR_INVALID_WINDOW` (409), on period create and partner-agreement create."
    "**Period windows do not overlap** — `ERR_PERIOD_OVERLAP` (409), on period create."
    "The end must fall strictly after the start; a window whose start is at or after its end is rejected with `ERR_INVALID_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/temporal_accounting_period_adjacent_allowed_overlap_rejected
    """
    program = _live_program(api)
    august = assert_created(
        _open_period(api, program["id"], AUG_CODE, PERIOD_AUG_START, PERIOD_AUG_END)
    )

    assert_error(
        _open_period(
            api, program["id"], DEGENERATE_CODE, DEGENERATE_START, DEGENERATE_END
        ),
        ApiErrorId.INVALID_WINDOW.value,
    )
    assert_error(
        _open_period(api, program["id"], DEGENERATE_CODE, PERIOD_AUG_START, PERIOD_AUG_START),
        ApiErrorId.INVALID_WINDOW.value,
    )

    assert_page(
        api.list_periods(CONTROLLER_HEADERS, program_id=program["id"]),
        expected_ids=[august["id"]],
        total_count=1,
    )


# ─── Closed partner-agreement windows plus their settlement-lag buffer ───────
def test_successor_partner_window_must_begin_after_the_prior_settlement_tail(api):
    """
    The prior agreement's window closes on 2026-06-30 and carries 30 whole days of
    lag, so its settlement tail runs through 2026-07-30 inclusive. A successor
    beginning on that very instant is still inside the tail and must be refused,
    while a successor beginning one whole day later must be accepted — which shows
    the boundary is inclusive on the refusing side and that mere adjacency to the
    prior window would not have been enough.

    "It is the number of whole days added to a period's `end_at` to obtain a statement's `due_date`, and it is also the mandatory buffer between two agreements that share a `partner_code`."
    "Concretely: a new agreement conflicts with any existing non-`TERMINATED` agreement on the same programme carrying the same `partner_code` whenever the new agreement's `effective_start_date` falls on or before that prior agreement's `effective_end_date` advanced by the prior agreement's own `settlement_lag_days` whole days."
    "Adjacency is therefore not sufficient — the new window must begin strictly after the prior window's settlement tail — and a conflict is rejected with `ERR_PARTNER_WINDOW_CONFLICT`."
    "A new agreement is born with `status` `ACTIVE`, `deferred_below_minimum_cents` at 0 and `outstanding_settlement_cents` at 0."

    Design: Difficulty/resource_temporal_overlap/temporal_partner_agreement_window_needs_settlement_lag_buffer
    """
    program = _live_program(api)

    prior = assert_created(
        _register_agreement(
            api, program["id"], PARTNER_CODE, FIRST_START, FIRST_END
        )
    )
    assert_fields(
        prior,
        partner_code=PARTNER_CODE,
        relationship_type=RELATIONSHIP_THIRD_PARTY,
        status=AGREEMENT_ACTIVE,
        settlement_lag_days=LAG_DAYS,
        effective_start_date=FIRST_START,
        effective_end_date=FIRST_END,
        deferred_below_minimum_cents=0,
        outstanding_settlement_cents=0,
    )

    assert_error(
        _register_agreement(
            api,
            program["id"],
            PARTNER_CODE,
            BUFFER_BOUNDARY_START,
            SUCCESSOR_END,
        ),
        ApiErrorId.PARTNER_WINDOW_CONFLICT.value,
    )

    successor = assert_created(
        _register_agreement(
            api,
            program["id"],
            PARTNER_CODE,
            CLEAR_OF_BUFFER_START,
            SUCCESSOR_END,
        )
    )
    assert_fields(
        successor,
        status=AGREEMENT_ACTIVE,
        effective_start_date=CLEAR_OF_BUFFER_START,
        effective_end_date=SUCCESSOR_END,
    )

    assert_page(
        api.list_agreements(
            PROGRAM_ADMIN_HEADERS, program_id=program["id"], partner_code=PARTNER_CODE
        ),
        expected_ids=[prior["id"], successor["id"]],
        total_count=2,
    )


def test_partner_window_buffer_is_scoped_to_one_partner_code_of_one_programme(api):
    """
    The buffer only ever looks at agreements of the same programme carrying the same
    partner code, so a different partner may hold the byte-identical window, and so
    may the same partner code under a different programme. Both must be accepted
    while the original agreement stays untouched, which rules out an implementation
    that treats the window as globally exclusive.

    "Concretely: a new agreement conflicts with any existing non-`TERMINATED` agreement on the same programme carrying the same `partner_code` whenever the new agreement's `effective_start_date` falls on or before that prior agreement's `effective_end_date` advanced by the prior agreement's own `settlement_lag_days` whole days."
    "A cohort's enrolment window (`enrollment_start_date` through `enrollment_end_date`) and a partner agreement's effective window (`effective_start_date` through `effective_end_date`) are closed intervals, inclusive at both ends."
    "Partner agreements may be filtered by `program_id`, `partner_code`, `status` and `relationship_type`."

    Design: Difficulty/resource_temporal_overlap/temporal_partner_agreement_window_needs_settlement_lag_buffer
    """
    first_program = _live_program(api)
    second_program = _live_program(api)

    prior = assert_created(
        _register_agreement(
            api, first_program["id"], PARTNER_CODE, FIRST_START, FIRST_END
        )
    )

    other_partner = assert_created(
        _register_agreement(
            api,
            first_program["id"],
            OTHER_PARTNER_CODE,
            FIRST_START,
            FIRST_END,
            relationship_type=RELATIONSHIP_INTERCOMPANY,
        )
    )
    assert_fields(
        other_partner,
        partner_code=OTHER_PARTNER_CODE,
        relationship_type=RELATIONSHIP_INTERCOMPANY,
        status=AGREEMENT_ACTIVE,
        effective_start_date=FIRST_START,
        effective_end_date=FIRST_END,
    )

    same_code_elsewhere = assert_created(
        _register_agreement(
            api, second_program["id"], PARTNER_CODE, FIRST_START, FIRST_END
        )
    )
    assert_fields(
        same_code_elsewhere,
        program_id=second_program["id"],
        partner_code=PARTNER_CODE,
        status=AGREEMENT_ACTIVE,
    )

    assert_fields(
        assert_ok(api.get_agreement(prior["id"], PROGRAM_ADMIN_HEADERS)),
        status=AGREEMENT_ACTIVE,
        version=prior["version"],
        effective_start_date=FIRST_START,
        effective_end_date=FIRST_END,
    )
    assert_page(
        api.list_agreements(PROGRAM_ADMIN_HEADERS, program_id=first_program["id"]),
        expected_ids=[prior["id"], other_partner["id"]],
        total_count=2,
    )
    assert_page(
        api.list_agreements(PROGRAM_ADMIN_HEADERS, partner_code=PARTNER_CODE),
        expected_ids=[prior["id"], same_code_elsewhere["id"]],
        total_count=2,
    )


def test_terminated_predecessor_stops_reserving_its_settlement_tail(api):
    """
    The buffer is measured only against agreements that are not TERMINATED, so once
    the predecessor is terminated the window that was refused a moment earlier must
    be accepted verbatim. The predecessor may be terminated because its outstanding
    settlement balance is exactly 0, and termination bumps its version.

    "Concretely: a new agreement conflicts with any existing non-`TERMINATED` agreement on the same programme carrying the same `partner_code` whenever the new agreement's `effective_start_date` falls on or before that prior agreement's `effective_end_date` advanced by the prior agreement's own `settlement_lag_days` whole days."
    "Terminating an agreement is a `ProgramAdmin` action, permitted from `ACTIVE → TERMINATED` and from `SUSPENDED → TERMINATED`, and only when the agreement's `outstanding_settlement_cents` is exactly 0; a non-zero balance is rejected with `ERR_OUTSTANDING_SETTLEMENT`."
    "Termination increments the agreement's `version` by 1, and `TERMINATED` is terminal."

    Design: Difficulty/resource_temporal_overlap/temporal_partner_agreement_window_needs_settlement_lag_buffer
    """
    program = _live_program(api)
    prior = assert_created(
        _register_agreement(api, program["id"], PARTNER_CODE, FIRST_START, FIRST_END)
    )

    assert_error(
        _register_agreement(
            api, program["id"], PARTNER_CODE, BUFFER_BOUNDARY_START, SUCCESSOR_END
        ),
        ApiErrorId.PARTNER_WINDOW_CONFLICT.value,
    )

    terminated = assert_ok(
        api.terminate_agreement(prior["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert_fields(
        terminated,
        status=AGREEMENT_TERMINATED,
        outstanding_settlement_cents=0,
        version=prior["version"] + 1,
    )

    successor = assert_created(
        _register_agreement(
            api, program["id"], PARTNER_CODE, BUFFER_BOUNDARY_START, SUCCESSOR_END
        )
    )
    assert_fields(
        successor,
        status=AGREEMENT_ACTIVE,
        effective_start_date=BUFFER_BOUNDARY_START,
        effective_end_date=SUCCESSOR_END,
    )

    assert_page(
        api.list_agreements(
            PROGRAM_ADMIN_HEADERS, program_id=program["id"], status=AGREEMENT_ACTIVE
        ),
        expected_ids=[successor["id"]],
        total_count=1,
    )


def test_degenerate_partner_window_is_reported_above_the_buffer_check(api):
    """
    A successor window running from 2026-07-30 back to 2026-07-01 is malformed and
    also sits inside the predecessor's settlement tail, so two rungs are violated by
    one body. Window sanity is the higher rung, so ERR_INVALID_WINDOW must win;
    answering with the buffer conflict would betray the wrong evaluation order. A
    window clear of every tail, and one whose ends coincide, are refused the same
    way, and no agreement is created by any of the three attempts.

    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."
    "The agreement's effective window is the closed interval from `effective_start_date` through `effective_end_date`, and the end must fall strictly after the start, else `ERR_INVALID_WINDOW`."
    "**Window sanity** — `ERR_INVALID_WINDOW` (409), on period create and partner-agreement create."
    "**Partner windows do not conflict** — `ERR_PARTNER_WINDOW_CONFLICT` (409), on partner-agreement create."

    Design: Difficulty/resource_temporal_overlap/temporal_partner_agreement_window_needs_settlement_lag_buffer
    """
    program = _live_program(api)
    prior = assert_created(
        _register_agreement(api, program["id"], PARTNER_CODE, FIRST_START, FIRST_END)
    )

    assert_error(
        _register_agreement(
            api, program["id"], PARTNER_CODE, BAD_WINDOW_START, BAD_WINDOW_END
        ),
        ApiErrorId.INVALID_WINDOW.value,
    )
    assert_error(
        _register_agreement(
            api,
            program["id"],
            PARTNER_CODE,
            LATE_BAD_WINDOW_START,
            LATE_BAD_WINDOW_END,
        ),
        ApiErrorId.INVALID_WINDOW.value,
    )
    assert_error(
        _register_agreement(
            api,
            program["id"],
            PARTNER_CODE,
            CLEAR_OF_BUFFER_START,
            CLEAR_OF_BUFFER_START,
        ),
        ApiErrorId.INVALID_WINDOW.value,
    )

    assert_page(
        api.list_agreements(PROGRAM_ADMIN_HEADERS, program_id=program["id"]),
        expected_ids=[prior["id"]],
        total_count=1,
    )
