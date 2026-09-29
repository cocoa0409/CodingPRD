"""
Requests that break two rules at once, where the contract pins which rejection
must surface.

Issuing an oversized lot into a period that has already been soft-closed breaks
both the period-state gate and the per-issuance point cap; the container check
wins. Hard-closing a period whose approved estimate carries a blank memorandum
while one of its statements is still merely issued breaks both the audit-evidence
rule and the settlement rule; the memorandum wins. In each case a control call
proves the losing rule really was violated and was merely masked.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_error, assert_fields, assert_ok, assert_page
from test_helpers.constants import (
    CLOCK_EPOCH,
    ESTIMATE_APPROVED,
    PERIOD_AUG_END,
    PERIOD_SEP_CODE,
    PERIOD_SEP_END,
    PERIOD_SEP_START,
    PERIOD_SOFT_CLOSED,
    STATEMENT_ISSUED,
    STATEMENT_PAID,
    TIER_BASE,
    TIER_GOLD,
)
from test_helpers.test_users import ACCOUNTANT_HEADERS, CONTROLLER_HEADERS

# ─── The period-state versus issuance-cap pairing ────────────────────────────
# A GOLD member earns 12500 bp per base point, so 4000 base points measure to
# exactly the 5000-point cap and 4001 measure to 5001, one point above it.
CAPPED_BASE_POINTS = 4000
OVER_CAP_BASE_POINTS = 4001
CAPPED_POINTS_ISSUED = 5000

CAPPED_LOT_DEFERRED_CENTS = 4500
SINGLE_COHORT_RATE_BP = 8200
BAND_LOW_BP = 7700
BAND_HIGH_BP = 8700
AUG_REQUIRED_CENTS = 4920
AUG_CATCH_UP_CENTS = 420
AUG_BREAKAGE_RECOGNIZED_CENTS = -420

# ─── The memorandum versus unsettled-statement pairing ──────────────────────
PARTNER_BASE_POINTS = 4000
PARTNER_POINTS_ISSUED = 4000
PARTNER_LOT_DEFERRED_CENTS = 3600
PARTNER_MIN_INVOICE_CENTS = 1000
PARTNER_ISSUANCE_RECEIVABLE_CENTS = 3600
PARTNER_NET_DUE_CENTS = 3600
MEMO_PERIOD_REQUIRED_CENTS = 3936
MEMO_PERIOD_CLOSING_CENTS = 3936
MEMO_PERIOD_CATCH_UP_CENTS = 336
MEMO_PERIOD_BREAKAGE_RECOGNIZED_CENTS = -336
BLANK_MEMO = ""


def _soft_closed_period_and_open_control(api):
    """
    A soft-closed period holding one lot that already sits exactly on the
    issuance cap, plus a second period left OPEN as the control container for an
    identical issuance body.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(
        api, program["id"], escheatment_required=False, escheat_rate_bp=0
    )
    cohort = fixtures.new_cohort(
        api, program["id"], observed_redemption_rate_bp=SINGLE_COHORT_RATE_BP
    )
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(api, program["id"], cohort["id"], tier=TIER_GOLD)
    closed_period = fixtures.new_period(api, program["id"])
    lot = fixtures.issue_lot(
        api, member["id"], closed_period["id"], CAPPED_BASE_POINTS
    )

    fixtures.approved_estimate(
        api,
        program["id"],
        closed_period["id"],
        cohort_id=cohort["id"],
        memo_narrative="August single-cohort measurement.",
        sensitivity_low_bp=BAND_LOW_BP,
        sensitivity_high_bp=BAND_HIGH_BP,
    )
    fixtures.set_clock(api, PERIOD_AUG_END)
    closed_period = fixtures.soft_close(api, closed_period["id"])

    open_period = fixtures.new_period(
        api,
        program["id"],
        period_code=PERIOD_SEP_CODE,
        start_at=PERIOD_SEP_START,
        end_at=PERIOD_SEP_END,
    )
    return {
        "program": program,
        "member": member,
        "closed_period": closed_period,
        "open_period": open_period,
        "lot": lot,
    }


def _over_cap_issuance(api, member_id, period_id):
    """An issuance body whose measured point count lands one point above the cap."""
    return api.create_point_lot(
        factories.point_lot_payload(member_id, period_id, OVER_CAP_BASE_POINTS),
        ACCOUNTANT_HEADERS,
    )


def _blank_memo_close_with_issued_statement(api):
    """
    A soft-closed period whose approved estimate carries the empty memorandum and
    which still owns one settlement statement in ISSUED.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(
        api, program["id"], escheatment_required=False, escheat_rate_bp=0
    )
    cohort = fixtures.new_cohort(
        api, program["id"], observed_redemption_rate_bp=SINGLE_COHORT_RATE_BP
    )
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(api, program["id"], cohort["id"], tier=TIER_BASE)
    agreement = fixtures.new_agreement(
        api, program["id"], min_invoice_cents=PARTNER_MIN_INVOICE_CENTS
    )
    period = fixtures.new_period(api, program["id"])
    lot = fixtures.issue_lot(
        api,
        member["id"],
        period["id"],
        PARTNER_BASE_POINTS,
        partner_agreement_id=agreement["id"],
    )

    estimate = fixtures.approved_estimate(
        api,
        program["id"],
        period["id"],
        cohort_id=cohort["id"],
        memo_narrative=BLANK_MEMO,
        sensitivity_low_bp=BAND_LOW_BP,
        sensitivity_high_bp=BAND_HIGH_BP,
    )
    statement = fixtures.issued_statement(api, agreement["id"], period["id"])

    fixtures.set_clock(api, PERIOD_AUG_END)
    period = fixtures.soft_close(api, period["id"])
    return {
        "program": program,
        "agreement": agreement,
        "period": period,
        "lot": lot,
        "estimate": estimate,
        "statement": statement,
    }


# ─── Period state outranks the issuance cap ─────────────────────────────────
def test_period_not_open_outranks_the_issuance_cap(api):
    """
    One issuance body breaks two rules at once: the addressed period is
    SOFT_CLOSED and the measured point count is 5001 against a cap of 5000. The
    arithmetic check is the cheap one and the tempting one to run first, but the
    container-state check sits above it, so the only acceptable answer is
    ERR_PERIOD_NOT_OPEN.

    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."
    "Issuing a point lot into a period that is no longer `OPEN`, with a point count that would also breach the programme's per-issuance cap, is reported as `ERR_PERIOD_NOT_OPEN` — the period-state rung sits above the fiscal-cap rung."

    Design: Difficulty/priority_pair_validation_conflict/priority_period_not_open_outranks_issuance_cap_exceeded
    """
    setup = _soft_closed_period_and_open_control(api)
    assert_fields(setup["closed_period"], state=PERIOD_SOFT_CLOSED)

    response = _over_cap_issuance(
        api, setup["member"]["id"], setup["closed_period"]["id"]
    )
    assert_error(response, ApiErrorId.PERIOD_NOT_OPEN.value)


def test_identical_body_against_an_open_period_reports_the_issuance_cap(api):
    """
    The masked rule is proved to have been violated by sending the same body a
    second time, changing only the period identifier. Against the OPEN period the
    period-state rung no longer fires, the fiscal-cap rung is reached, and the
    answer becomes ERR_ISSUANCE_CAP_EXCEEDED — which is what makes the first
    rejection an ordering decision rather than an accident.

    "Only once `points_issued` has been measured is the cap tested: a `points_issued` strictly greater than the programme's `per_issuance_point_cap` is rejected with `ERR_ISSUANCE_CAP_EXCEEDED`, and a value exactly equal to the cap passes."
    "Issuing a point lot into a period that is no longer `OPEN`, with a point count that would also breach the programme's per-issuance cap, is reported as `ERR_PERIOD_NOT_OPEN` — the period-state rung sits above the fiscal-cap rung."

    Design: Difficulty/priority_pair_validation_conflict/priority_period_not_open_outranks_issuance_cap_exceeded
    """
    setup = _soft_closed_period_and_open_control(api)

    masked = _over_cap_issuance(
        api, setup["member"]["id"], setup["closed_period"]["id"]
    )
    assert_error(masked, ApiErrorId.PERIOD_NOT_OPEN.value)

    control = _over_cap_issuance(
        api, setup["member"]["id"], setup["open_period"]["id"]
    )
    assert_error(control, ApiErrorId.ISSUANCE_CAP_EXCEEDED.value)


def test_neither_masked_nor_control_rejection_books_any_issuance(api):
    """
    A rejection at any rung of the ladder must be total: no lot is written into
    either period, the member's balance still shows only the one lot that sat
    exactly on the cap, and the soft-closed period's frozen figures do not move.
    The hard case is the soft-closed period, where a partially applied issuance
    would corrupt a close that has already been reported.

    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."
    "`issuance_deferred_cents` grows by each issued lot's `deferred_revenue_cents`."

    Design: Difficulty/priority_pair_validation_conflict/priority_period_not_open_outranks_issuance_cap_exceeded
    """
    setup = _soft_closed_period_and_open_control(api)
    closed_id = setup["closed_period"]["id"]
    open_id = setup["open_period"]["id"]
    version_before = setup["closed_period"]["version"]

    assert_error(
        _over_cap_issuance(api, setup["member"]["id"], closed_id),
        ApiErrorId.PERIOD_NOT_OPEN.value,
    )
    assert_error(
        _over_cap_issuance(api, setup["member"]["id"], open_id),
        ApiErrorId.ISSUANCE_CAP_EXCEEDED.value,
    )

    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, period_id=closed_id),
        expected_ids=[setup["lot"]["id"]],
        total_count=1,
    )
    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, period_id=open_id), total_count=0
    )

    closed_period = assert_ok(api.get_period(closed_id, CONTROLLER_HEADERS))
    assert_fields(
        closed_period,
        state=PERIOD_SOFT_CLOSED,
        issuance_deferred_cents=CAPPED_LOT_DEFERRED_CENTS,
        required_liability_cents=AUG_REQUIRED_CENTS,
        catch_up_adjustment_cents=AUG_CATCH_UP_CENTS,
        breakage_recognized_cents=AUG_BREAKAGE_RECOGNIZED_CENTS,
        version=version_before,
    )
    member = assert_ok(api.get_member(setup["member"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(member, point_balance=CAPPED_POINTS_ISSUED)


# ─── The memorandum outranks the unsettled statement ────────────────────────
def test_memo_narrative_outranks_unsettled_statements(api):
    """
    One hard-close request breaks two preconditions at once: the period's approved
    estimate carries the empty memorandum, and the period still owns a statement
    resting in ISSUED. Both are stated as preconditions of the same transition, so
    only the declared ordering decides, and the answer is ERR_MEMO_NARRATIVE_REQUIRED.

    "And hard-closing a period whose approved estimate carries an empty actuarial memorandum while a statement of that period is also still unsettled is reported as `ERR_MEMO_NARRATIVE_REQUIRED` — the memorandum rung sits above the settlement rung."
    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."

    Design: Difficulty/priority_pair_validation_conflict/priority_memo_narrative_outranks_unsettled_statements
    """
    setup = _blank_memo_close_with_issued_statement(api)
    assert_fields(setup["estimate"], state=ESTIMATE_APPROVED, memo_narrative=BLANK_MEMO)
    assert_fields(
        setup["statement"],
        state=STATEMENT_ISSUED,
        partner_issued_points=PARTNER_POINTS_ISSUED,
        issuance_receivable_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
        net_due_cents=PARTNER_NET_DUE_CENTS,
    )

    response = api.hard_close_period(setup["period"]["id"], None, CONTROLLER_HEADERS)
    assert_error(response, ApiErrorId.MEMO_NARRATIVE_REQUIRED.value)


def test_settling_the_statement_leaves_the_memorandum_still_blocking(api):
    """
    Clearing the lower-ranked breach does not change the answer, which is the proof
    that the memorandum rung was decided on rank and not because the settlement
    rung was somehow satisfied: after the statement is paid the period owns nothing
    unsettled, yet the hard close is still refused for the empty memorandum.

    "Two preconditions apply: the `APPROVED` estimate for this period must carry a non-empty `memo_narrative` (otherwise `ERR_MEMO_NARRATIVE_REQUIRED`) — the memorandum that could be left empty at estimate creation must exist by the time the books are sealed — and every `SettlementStatement` of this period must be in `PAID`, `WRITTEN_OFF` or `SUPERSEDED` (otherwise `ERR_UNSETTLED_STATEMENTS`)."
    "And hard-closing a period whose approved estimate carries an empty actuarial memorandum while a statement of that period is also still unsettled is reported as `ERR_MEMO_NARRATIVE_REQUIRED` — the memorandum rung sits above the settlement rung."

    Design: Difficulty/priority_pair_validation_conflict/priority_memo_narrative_outranks_unsettled_statements
    """
    setup = _blank_memo_close_with_issued_statement(api)
    period_id = setup["period"]["id"]

    assert_error(
        api.hard_close_period(period_id, None, CONTROLLER_HEADERS),
        ApiErrorId.MEMO_NARRATIVE_REQUIRED.value,
    )

    paid = assert_ok(
        api.pay_statement(setup["statement"]["id"], None, CONTROLLER_HEADERS)
    )
    assert_fields(paid, state=STATEMENT_PAID)
    agreement = assert_ok(
        api.get_agreement(setup["agreement"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_fields(agreement, outstanding_settlement_cents=0)

    assert_error(
        api.hard_close_period(period_id, None, CONTROLLER_HEADERS),
        ApiErrorId.MEMO_NARRATIVE_REQUIRED.value,
    )


def test_the_refused_hard_close_leaves_the_period_and_the_ledger_untouched(api):
    """
    A precondition failure on the seal must leave every close-derived figure exactly
    as the soft close left it: the period stays SOFT_CLOSED with its closing
    liability and its signed breakage figure intact, the estimate keeps its empty
    memorandum rather than being quietly patched, and the programme's year-to-date
    breakage is unmoved.

    "`closing_liability_cents` is `pre_catchup_liability_cents` plus `catch_up_adjustment_cents`."
    "`memo_narrative` is the actuarial memorandum text of at most 2000 characters; the field must be present in the create request, but the empty string is accepted at this stage — the memorandum only becomes mandatory later, when the period it supports is hard-closed."

    Design: Difficulty/priority_pair_validation_conflict/priority_memo_narrative_outranks_unsettled_statements
    """
    setup = _blank_memo_close_with_issued_statement(api)
    period_id = setup["period"]["id"]
    version_before = setup["period"]["version"]

    assert_error(
        api.hard_close_period(period_id, None, CONTROLLER_HEADERS),
        ApiErrorId.MEMO_NARRATIVE_REQUIRED.value,
    )

    period = assert_ok(api.get_period(period_id, CONTROLLER_HEADERS))
    assert_fields(
        period,
        state=PERIOD_SOFT_CLOSED,
        issuance_deferred_cents=PARTNER_LOT_DEFERRED_CENTS,
        required_liability_cents=MEMO_PERIOD_REQUIRED_CENTS,
        catch_up_adjustment_cents=MEMO_PERIOD_CATCH_UP_CENTS,
        closing_liability_cents=MEMO_PERIOD_CLOSING_CENTS,
        breakage_recognized_cents=MEMO_PERIOD_BREAKAGE_RECOGNIZED_CENTS,
        reopen_count=0,
        version=version_before,
    )

    estimate = assert_ok(api.get_estimate(setup["estimate"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(estimate, state=ESTIMATE_APPROVED, memo_narrative=BLANK_MEMO)

    program = assert_ok(api.get_program(setup["program"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        program,
        recognized_breakage_ytd_cents=MEMO_PERIOD_BREAKAGE_RECOGNIZED_CENTS,
    )
