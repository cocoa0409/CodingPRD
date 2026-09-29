"""
Gates that read the state of an entity the addressed resource does not own.

Issuing a point lot answers to two ancestors that are not each other's parent —
the addressed accounting period and the owning programme — and hard-closing a
period answers to a sibling subtree of settlement statements it never created.
Both families of test hold everything else still and move only the far entity,
so the refusal, and the later acceptance of the byte-identical request, can only
be explained by the far entity's state.
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
    CLOCK_EPOCH,
    IDENTITY_MULTIPLIER_BP,
    LOT_OUTSTANDING,
    PERIOD_AUG_END,
    PERIOD_HARD_CLOSED,
    PERIOD_OPEN,
    PERIOD_SOFT_CLOSED,
    PROGRAM_ACTIVE,
    PROGRAM_SUSPENDED,
    SETTLEMENT_PENDING,
    SETTLEMENT_SETTLED,
    STATEMENT_ISSUED,
    STATEMENT_PAID,
    STATE_TX,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)

# ─── The reference programme both families of test build on ──────────────────
SEEDED_BREAKAGE_RATE_BP = 2500  # 10000 - historical_redemption_rate_bp 7500

# ─── The programme-gate figures: one BASE lot of 1000 base points ────────────
GATE_BASE_POINTS = 1000
GATE_POINTS_ISSUED = 1000  # BASE multiplier 10000 bp is an identity
GATE_GROSS_CENTS = 1200  # 1000 * 1200 / 1000
GATE_RESERVE_CENTS = 300  # 1200 * 2500 / 10000
GATE_DEFERRED_CENTS = 900  # 1200 - 300
GATE_REDEMPTION_POINTS = 500

# ─── The settlement-gate figures: one partner lot of 4000 base points ────────
PARTNER_BASE_POINTS = 4000
PARTNER_POINTS_ISSUED = 4000
PARTNER_GROSS_CENTS = 4800  # 4000 * 1200 / 1000
PARTNER_DEFERRED_CENTS = 3600  # 4800 - 4800 * 2500 / 10000

MIN_INVOICE_CENTS = 1000
ISSUANCE_RECEIVABLE_CENTS = 3600  # 4000 * 900 / 1000
NET_DUE_CENTS = 3600  # GROSS basis, no carry-forward, above the minimum
DUE_DATE = "2026-10-01T00:00:00Z"  # period end_at plus 30 whole days

# The single cohort pins the estimate to its own clamped adjusted rate.
SINGLE_COHORT_RATE_BP = 8200
SINGLE_COHORT_BREAKAGE_BP = 1800
ESTIMATE_BAND_LOW_BP = 7700
ESTIMATE_BAND_HIGH_BP = 8700
ESTIMATE_REQUIRED_CENTS = 3936  # 4800 * 8200 / 10000

# The eight-step rollforward August produces with only that one partner lot.
CLOSE_PRE_CATCHUP_CENTS = 3600  # 0 + 3600 - 0 - 0 - 0
CLOSE_REQUIRED_CENTS = 3936  # at-close gross 4800 * 8200 / 10000
CLOSE_CATCH_UP_CENTS = 336  # 3936 - 3600
CLOSE_CLOSING_CENTS = 3936  # 3600 + 336
CLOSE_BREAKAGE_RECOGNIZED_CENTS = -336  # the negation of the catch-up

MEMO_NARRATIVE = "August 2026 single-cohort estimate supporting the partner issuance."


# ─── Setup shared by several tests ───────────────────────────────────────────
def _live_program(api, **program_overrides):
    """
    An ACTIVE programme carrying the expiry policy and the enrolment vintage its
    first activation demands, returned as ``(programme, cohort)``.
    """
    program = fixtures.new_program(api, **program_overrides)
    fixtures.new_state_expiry_rule(
        api,
        program["id"],
        state_code=STATE_TX,
        escheatment_required=False,
        escheat_rate_bp=0,
    )
    cohort = fixtures.new_cohort(api, program["id"])
    return fixtures.activate(api, program["id"]), cohort


def _program_gate_bundle(api):
    """
    An ACTIVE programme with one OPEN period, one BASE member and one lot already
    issued, so a second issuance of the identical body is otherwise feasible.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program, cohort = _live_program(api)
    member = fixtures.new_member(api, program["id"], cohort["id"])
    period = fixtures.new_period(api, program["id"])
    lot = fixtures.issue_lot(api, member["id"], period["id"], GATE_BASE_POINTS)
    return {
        "program": program,
        "cohort": cohort,
        "member": member,
        "period": period,
        "lot": lot,
    }


def _issue_again(api, bundle):
    """The byte-identical issuance body, sent again."""
    return api.create_point_lot(
        factories.point_lot_payload(
            bundle["member"]["id"],
            bundle["period"]["id"],
            GATE_BASE_POINTS,
            promo_multiplier_bp=IDENTITY_MULTIPLIER_BP,
        ),
        ACCOUNTANT_HEADERS,
    )


def _settlement_gate_bundle(api):
    """
    A SOFT_CLOSED August whose only settlement statement is still ISSUED, over a
    partner-issued lot that is therefore still PENDING_SETTLEMENT.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program, cohort = _live_program(api)
    member = fixtures.new_member(api, program["id"], cohort["id"])
    agreement = fixtures.new_agreement(
        api, program["id"], min_invoice_cents=MIN_INVOICE_CENTS
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
        memo_narrative=MEMO_NARRATIVE,
        sensitivity_low_bp=ESTIMATE_BAND_LOW_BP,
        sensitivity_high_bp=ESTIMATE_BAND_HIGH_BP,
    )
    statement = fixtures.issued_statement(api, agreement["id"], period["id"])
    fixtures.set_clock(api, PERIOD_AUG_END)
    period = fixtures.soft_close(api, period["id"])
    return {
        "program": program,
        "member": member,
        "agreement": agreement,
        "period": period,
        "lot": lot,
        "estimate": estimate,
        "statement": statement,
    }


# ─── The programme gate, with the period held OPEN throughout ────────────────
def test_issuance_is_refused_for_the_programme_status_while_its_period_stays_open(api):
    """
    Suspending the programme and leaving the period alone must produce
    ERR_PROGRAM_NOT_ACTIVE rather than ERR_PERIOD_NOT_OPEN: the two gates sit on
    ancestors that are not each other's parent, and only the programme's has been
    tripped. The period is read back mid-test to prove it is still OPEN at the
    instant of the refusal, and the lot listing proves the refused call left no
    row behind.

    "Issuance, redemption, estimate preparation and settlement all require the programme to be `ACTIVE`, and an attempt against a programme in any other status is rejected with `ERR_PROGRAM_NOT_ACTIVE`."
    "Suspension, `ACTIVE → SUSPENDED`, likewise increments `version` by 1; it blocks issuance and redemption while leaving period close and partner settlement fully available."
    "Issuing a lot, requesting a redemption, allocating, fulfilling or reversing one, preparing an estimate, submitting an estimate, approving an estimate and running the expiry sweep all require the addressed period to be `OPEN`; against a `SOFT_CLOSED` or `HARD_CLOSED` period each of these is rejected with `ERR_PERIOD_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_point_lot_requires_open_period_and_active_program
    """
    bundle = _program_gate_bundle(api)

    suspended = assert_ok(
        api.suspend_program(bundle["program"]["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert_fields(
        suspended,
        status=PROGRAM_SUSPENDED,
        current_breakage_rate_bp=SEEDED_BREAKAGE_RATE_BP,
    )

    assert_error(_issue_again(api, bundle), ApiErrorId.PROGRAM_NOT_ACTIVE.value)

    period = assert_ok(api.get_period(bundle["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        period,
        state=PERIOD_OPEN,
        reopen_count=0,
        issuance_deferred_cents=GATE_DEFERRED_CENTS,
    )
    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, period_id=bundle["period"]["id"]),
        expected_ids=[bundle["lot"]["id"]],
        total_count=1,
    )


def test_redemption_request_shares_the_programme_gate_and_reads_stay_open(api):
    """
    The same ancestor gate covers a different child entity: with the period still
    OPEN and the member's balance ample, a redemption request against a SUSPENDED
    programme is refused with ERR_PROGRAM_NOT_ACTIVE and no event row is created.
    Reads are deliberately not gated, so the programme and its lot still answer
    200 while the programme is suspended.

    "Issuance, redemption, estimate preparation and settlement all require the programme to be `ACTIVE`, and an attempt against a programme in any other status is rejected with `ERR_PROGRAM_NOT_ACTIVE`."
    "**Owning programme is `ACTIVE`** — `ERR_PROGRAM_NOT_ACTIVE` (409), on point-lot issuance, redemption request, redemption allocation, breakage-estimate create, change-order approve and change-order apply."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_point_lot_requires_open_period_and_active_program
    """
    bundle = _program_gate_bundle(api)
    assert_ok(api.suspend_program(bundle["program"]["id"], None, PROGRAM_ADMIN_HEADERS))

    refusal = api.create_redemption(
        factories.redemption_payload(
            bundle["member"]["id"], bundle["period"]["id"], GATE_REDEMPTION_POINTS
        ),
        ACCOUNTANT_HEADERS,
    )
    assert_error(refusal, ApiErrorId.PROGRAM_NOT_ACTIVE.value)

    assert_page(
        api.list_redemptions(ACCOUNTANT_HEADERS, period_id=bundle["period"]["id"]),
        total_count=0,
    )

    program = assert_ok(api.get_program(bundle["program"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(program, status=PROGRAM_SUSPENDED)
    lot = assert_ok(api.get_point_lot(bundle["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(lot, lifecycle_state=LOT_OUTSTANDING, points_remaining=GATE_POINTS_ISSUED)


def test_reactivation_admits_the_same_issuance_without_reseeding_the_rate(api):
    """
    Reactivation alone unblocks the request: the body refused twice is accepted
    unchanged, the period was never touched, and the reactivated programme keeps
    the rate the first activation seeded instead of reseeding it a second time —
    which the new lot's frozen ``breakage_rate_bp_at_issue`` confirms.

    "The second form is reactivation, `SUSPENDED → ACTIVE`, which explicitly does **not** reseed the rate — `current_breakage_rate_bp` is left exactly as the most recent estimate approval left it — and increments `version` by 1."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_point_lot_requires_open_period_and_active_program
    """
    bundle = _program_gate_bundle(api)
    assert_ok(api.suspend_program(bundle["program"]["id"], None, PROGRAM_ADMIN_HEADERS))
    assert_error(_issue_again(api, bundle), ApiErrorId.PROGRAM_NOT_ACTIVE.value)

    reactivated = assert_ok(
        api.activate_program(bundle["program"]["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert_fields(
        reactivated,
        status=PROGRAM_ACTIVE,
        current_breakage_rate_bp=SEEDED_BREAKAGE_RATE_BP,
    )

    second_lot = assert_created(_issue_again(api, bundle))
    assert_fields(
        second_lot,
        points_issued=GATE_POINTS_ISSUED,
        points_remaining=GATE_POINTS_ISSUED,
        gross_ssp_cents=GATE_GROSS_CENTS,
        breakage_reserve_cents=GATE_RESERVE_CENTS,
        deferred_revenue_cents=GATE_DEFERRED_CENTS,
        breakage_rate_bp_at_issue=SEEDED_BREAKAGE_RATE_BP,
        lifecycle_state=LOT_OUTSTANDING,
    )

    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, period_id=bundle["period"]["id"]),
        total_count=2,
    )
    period = assert_ok(api.get_period(bundle["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        period,
        state=PERIOD_OPEN,
        reopen_count=0,
        issuance_deferred_cents=2 * GATE_DEFERRED_CENTS,
    )
    member = assert_ok(api.get_member(bundle["member"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(member, point_balance=2 * GATE_POINTS_ISSUED)


# ─── The settlement gate, with the period held still throughout ──────────────
def test_hard_close_is_refused_while_a_statement_of_the_period_is_still_issued(api):
    """
    Hard-close reads a sibling subtree it does not own. August is soft-closed and
    correct, its estimate carries a non-empty memorandum, and the only thing wrong
    is that a statement of the period sits in ISSUED rather than in one of the
    three settled states — so the refusal is ERR_UNSETTLED_STATEMENTS and the
    period comes out of it byte-identical, version included.

    "A `Controller` hard-closes a soft-closed period, `SOFT_CLOSED → HARD_CLOSED`, which is terminal."
    "Two preconditions apply: the `APPROVED` estimate for this period must carry a non-empty `memo_narrative` (otherwise `ERR_MEMO_NARRATIVE_REQUIRED`) — the memorandum that could be left empty at estimate creation must exist by the time the books are sealed — and every `SettlementStatement` of this period must be in `PAID`, `WRITTEN_OFF` or `SUPERSEDED` (otherwise `ERR_UNSETTLED_STATEMENTS`)."
    "**Every statement of the period is settled** — `ERR_UNSETTLED_STATEMENTS` (409), on hard-close."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_hard_close_requires_every_statement_settled
    """
    bundle = _settlement_gate_bundle(api)

    assert_fields(
        bundle["estimate"],
        estimated_redemption_rate_bp=SINGLE_COHORT_RATE_BP,
        breakage_rate_bp=SINGLE_COHORT_BREAKAGE_BP,
        outstanding_points_at_estimate=PARTNER_POINTS_ISSUED,
        outstanding_gross_ssp_cents_at_estimate=PARTNER_GROSS_CENTS,
        required_liability_cents=ESTIMATE_REQUIRED_CENTS,
        memo_narrative=MEMO_NARRATIVE,
    )

    statement = assert_ok(
        api.get_statement(bundle["statement"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_fields(
        statement,
        state=STATEMENT_ISSUED,
        partner_issued_points=PARTNER_POINTS_ISSUED,
        issuance_receivable_cents=ISSUANCE_RECEIVABLE_CENTS,
        partner_redeemed_points=0,
        redemption_payable_cents=0,
        net_due_cents=NET_DUE_CENTS,
        deferred_below_minimum_cents=0,
        due_date=DUE_DATE,
    )

    before = assert_ok(api.get_period(bundle["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        before,
        state=PERIOD_SOFT_CLOSED,
        pre_catchup_liability_cents=CLOSE_PRE_CATCHUP_CENTS,
        required_liability_cents=CLOSE_REQUIRED_CENTS,
        catch_up_adjustment_cents=CLOSE_CATCH_UP_CENTS,
        closing_liability_cents=CLOSE_CLOSING_CENTS,
        breakage_recognized_cents=CLOSE_BREAKAGE_RECOGNIZED_CENTS,
        approved_estimate_rate_bp=SINGLE_COHORT_RATE_BP,
    )

    refusal = api.hard_close_period(bundle["period"]["id"], None, CONTROLLER_HEADERS)
    assert_error(refusal, ApiErrorId.UNSETTLED_STATEMENTS.value)

    after = assert_ok(api.get_period(bundle["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        after,
        state=PERIOD_SOFT_CLOSED,
        version=before["version"],
        pre_catchup_liability_cents=CLOSE_PRE_CATCHUP_CENTS,
        required_liability_cents=CLOSE_REQUIRED_CENTS,
        catch_up_adjustment_cents=CLOSE_CATCH_UP_CENTS,
        closing_liability_cents=CLOSE_CLOSING_CENTS,
        breakage_recognized_cents=CLOSE_BREAKAGE_RECOGNIZED_CENTS,
        approved_estimate_rate_bp=SINGLE_COHORT_RATE_BP,
    )

    lot = assert_ok(api.get_point_lot(bundle["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        settlement_state=SETTLEMENT_PENDING,
        lifecycle_state=LOT_OUTSTANDING,
        gross_ssp_cents=PARTNER_GROSS_CENTS,
        deferred_revenue_cents=PARTNER_DEFERRED_CENTS,
    )


def test_paying_the_sibling_statement_settles_the_partner_lot_and_unblocks_hard_close(api):
    """
    Nothing about the period changes between the refused and the accepted attempt:
    the unblocking event is a transition on a different entity driven by a
    different role, and that same payment clears the agreement's balance and
    drives the partner lot to SETTLED on its billing dimension while its lifecycle
    dimension stays OUTSTANDING. Hard-close then recomputes nothing, and because
    both closed states are inside the summed set the programme's recognised
    breakage is identical on either side of the seal.

    "Payment moves the statement `ISSUED → PAID`, which is terminal: it sets `paid_at` to the clock reading, subtracts `net_due_cents` from the agreement's `outstanding_settlement_cents`, increments the agreement's `version` by 1 and the statement's `version` by 1, and drives every lot sharing the statement's `partner_agreement_id` and `period_id` whose `settlement_state` is `PENDING_SETTLEMENT` to `SETTLED`, walking those lots in `created_at` ascending order and incrementing each lot's `version` by 1."
    "The independence is real and testable: an `OUTSTANDING` lot may be `SETTLED`, and a `FULLY_REDEEMED` lot may still be `PENDING_SETTLEMENT`."
    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_hard_close_requires_every_statement_settled
    """
    bundle = _settlement_gate_bundle(api)
    assert_error(
        api.hard_close_period(bundle["period"]["id"], None, CONTROLLER_HEADERS),
        ApiErrorId.UNSETTLED_STATEMENTS.value,
    )

    agreement_before = assert_ok(
        api.get_agreement(bundle["agreement"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_fields(agreement_before, outstanding_settlement_cents=NET_DUE_CENTS)
    program_before = assert_ok(
        api.get_program(bundle["program"]["id"], CONTROLLER_HEADERS)
    )
    assert_fields(
        program_before, recognized_breakage_ytd_cents=CLOSE_BREAKAGE_RECOGNIZED_CENTS
    )

    paid = assert_ok(
        api.pay_statement(bundle["statement"]["id"], None, CONTROLLER_HEADERS)
    )
    assert_fields(paid, state=STATEMENT_PAID, paid_at=PERIOD_AUG_END)

    agreement_after = assert_ok(
        api.get_agreement(bundle["agreement"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_fields(agreement_after, outstanding_settlement_cents=0)
    lot = assert_ok(api.get_point_lot(bundle["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot, settlement_state=SETTLEMENT_SETTLED, lifecycle_state=LOT_OUTSTANDING
    )

    sealed = assert_ok(
        api.hard_close_period(bundle["period"]["id"], None, CONTROLLER_HEADERS)
    )
    assert_fields(
        sealed,
        state=PERIOD_HARD_CLOSED,
        closing_liability_cents=CLOSE_CLOSING_CENTS,
        catch_up_adjustment_cents=CLOSE_CATCH_UP_CENTS,
        breakage_recognized_cents=CLOSE_BREAKAGE_RECOGNIZED_CENTS,
        approved_estimate_rate_bp=SINGLE_COHORT_RATE_BP,
    )

    program_after = assert_ok(
        api.get_program(bundle["program"]["id"], CONTROLLER_HEADERS)
    )
    assert_fields(
        program_after, recognized_breakage_ytd_cents=CLOSE_BREAKAGE_RECOGNIZED_CENTS
    )


def test_hard_closed_period_locks_issuance_and_its_settlement_subtree_differently(api):
    """
    The two rungs that guard a sealed period speak to disjoint endpoint sets, so
    the same terminal state produces two different codes. Point-lot issuance is on
    the period-must-be-OPEN rung and is refused with ERR_PERIOD_NOT_OPEN, while
    statement creation is not on that rung at all and is refused one rung lower
    with ERR_PERIOD_HARD_CLOSED — even though the statement request carries a
    perfectly current agreement version and the agreement is still ACTIVE.

    "**Addressed period is `OPEN`** — `ERR_PERIOD_NOT_OPEN` (409), on point-lot issuance, redemption request, redemption allocation, redemption fulfilment, redemption reversal, breakage-estimate create, estimate submit, estimate approve and the expiry sweep."
    "**Addressed period is not `HARD_CLOSED`** — `ERR_PERIOD_HARD_CLOSED` (409), on period reopen, statement create, statement issue, statement pay and statement write-off."
    "Separately, and at a lower rung of the ladder, no child of a `HARD_CLOSED` period may be mutated at all: reopening the period, or creating, issuing, paying or writing off one of its statements, is rejected with `ERR_PERIOD_HARD_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_hard_close_requires_every_statement_settled
    """
    bundle = _settlement_gate_bundle(api)
    assert_ok(api.pay_statement(bundle["statement"]["id"], None, CONTROLLER_HEADERS))
    sealed = assert_ok(
        api.hard_close_period(bundle["period"]["id"], None, CONTROLLER_HEADERS)
    )
    assert_fields(sealed, state=PERIOD_HARD_CLOSED)

    issuance = api.create_point_lot(
        factories.point_lot_payload(
            bundle["member"]["id"], bundle["period"]["id"], GATE_BASE_POINTS
        ),
        ACCOUNTANT_HEADERS,
    )
    assert_error(issuance, ApiErrorId.PERIOD_NOT_OPEN.value)

    statement = api.create_statement(
        factories.statement_payload(
            bundle["agreement"]["id"],
            bundle["period"]["id"],
            fixtures.agreement_version(api, bundle["agreement"]["id"]),
        ),
        ACCOUNTANT_HEADERS,
    )
    assert_error(statement, ApiErrorId.PERIOD_HARD_CLOSED.value)
