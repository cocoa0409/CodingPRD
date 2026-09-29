"""
State-machine behaviour of the Loyalty Liability & Breakage Accounting API.

Every test here drives one entity's declared edges: the initial state a resource
is born in, the preconditions guarding a transition, the side effects a
transition fires, the bounded correction cycles, and the refusals that a
terminal state or an already-performed action produces.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_error,
    assert_fields,
    assert_null_fields,
    assert_ok,
    assert_page,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AGREEMENT_SUSPENDED,
    AGREEMENT_TERMINATED,
    BASIS_GROSS,
    CHANGE_EXPIRY_DAYS,
    CHANGE_SSP,
    CLOCK_EPOCH,
    ENTRY_TYPE_ALLOCATION,
    ESTIMATE_APPROVED,
    ESTIMATE_DRAFT,
    ESTIMATE_SUBMITTED,
    IDENTITY_MULTIPLIER_BP,
    LOT_EXPIRED,
    LOT_OUTSTANDING,
    LOT_PARTIALLY_REDEEMED,
    MEMBER_ACTIVE,
    MEMBER_DORMANT,
    ORDER_APPROVED,
    ORDER_CANCELLED,
    ORDER_MODELED,
    PERIOD_AUG_END,
    PERIOD_HARD_CLOSED,
    PERIOD_OPEN,
    PERIOD_SOFT_CLOSED,
    PROGRAM_ACTIVE,
    PROGRAM_CLOSED,
    PROGRAM_DRAFT,
    PROGRAM_SUSPENDED,
    REDEMPTION_ALLOCATED,
    REDEMPTION_REQUESTED,
    SETTLEMENT_NOT_APPLICABLE,
    SETTLEMENT_PENDING,
    SETTLEMENT_SETTLED,
    SETTLEMENT_WRITTEN_OFF,
    STATEMENT_ISSUED,
    STATEMENT_DISPUTED,
    STATEMENT_PAID,
    STATEMENT_WRITTEN_OFF,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    PREPARER_AS_CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    make_partner_operator_headers,
)

# ─── The reference figures every test below reuses ───────────────────────────
# The programme is configured at 1200 millicents per point with a historical
# redemption rate of 7500 basis points, so the first activation seeds a breakage
# rate of 10000 - 7500 = 2500 basis points.
SEEDED_BREAKAGE_RATE_BP = 2500
COHORT_OBSERVED_RATE_BP = 8200
# 10000 - 8200, the rate an approved single-candidate estimate installs.
APPROVED_BREAKAGE_RATE_BP = 1800

# One BASE lot of 1000 points at 1200 millicents: gross 1200, reserve
# round_half_up(1200 * 2500 / 10000) = 300, deferral 1200 - 300 = 900.
BASE_POINTS = 1000
LOT_GROSS_CENTS = 1200
LOT_RESERVE_CENTS = 300
LOT_DEFERRED_CENTS = 900

# A 100-point allocation off that lot at the lot's own frozen 2500 basis points:
# line gross round_half_up(100 * 1200 / 1000) = 120, reserve
# round_half_up(120 * 2500 / 10000) = 30, provisional release 120 - 30 = 90.
ALLOCATED_POINTS = 100
LINE_GROSS_CENTS = 120
LINE_PROVISIONAL_CENTS = 90

# The close of a period holding the whole 1000-point lot, at the approved rate
# 8200: pre-catch-up 900, at-close gross 1200, required
# round_half_up(1200 * 8200 / 10000) = 984, catch-up 84, closing 984.
FULL_REQUIRED_LIABILITY_CENTS = 984
FULL_CATCH_UP_CENTS = 84
FULL_BREAKAGE_RECOGNIZED_CENTS = -84

# The same close after 100 of those points have been redeemed: pre-catch-up
# 900 - 90 = 810, at-close gross round_half_up(900 * 1200 / 1000) = 1080,
# required round_half_up(1080 * 8200 / 10000) = 886, catch-up 76, closing 886.
REDEEMED_PRE_CATCHUP_CENTS = 810
REDEEMED_REQUIRED_LIABILITY_CENTS = 886
REDEEMED_CATCH_UP_CENTS = 76
REDEEMED_BREAKAGE_RECOGNIZED_CENTS = -76

# The partner leg: a 5000-point partner lot at 900 millicents per issued point
# bills round_half_up(5000 * 900 / 1000) = 4500 cents, and the 2026-09-01 period
# end plus 30 whole days of lag falls due on 2026-10-01.
PARTNER_POINTS = 5000
PARTNER_ISSUANCE_RECEIVABLE_CENTS = 4500
PARTNER_LOT_DEFERRED_CENTS = 4500
PARTNER_MIN_INVOICE_CENTS = 1000
PARTNER_DUE_DATE = "2026-10-01T00:00:00Z"

# Clock instants the tests move to.
CLOCK_MID_AUGUST = "2026-08-15T00:00:00Z"
CLOCK_AUGUST_FIFTH = "2026-08-05T00:00:00Z"
CLOCK_TWO_YEARS_ON = "2028-08-05T00:00:00Z"
CLOCK_DECEMBER = "2026-12-01T00:00:00Z"

# 2026-08-05 plus 730 whole days, and 2028-08-05 plus 730 whole days.
LOT_EXPIRES_AT = "2028-08-04T00:00:00Z"
REVIVED_LOT_EXPIRES_AT = "2030-08-05T00:00:00Z"

# 2026-08-01 plus 730 whole days, then the same issuance plus the new 365 days.
EPOCH_LOT_EXPIRES_AT = "2028-07-31T00:00:00Z"
RE_DATED_LOT_EXPIRES_AT = "2027-08-01T00:00:00Z"

# The second accounting period the dormancy sweep books into.
PERIOD_2028_CODE = "2028-08"
PERIOD_2028_START = "2028-08-01T00:00:00Z"
PERIOD_2028_END = "2028-09-01T00:00:00Z"

# The change-order leg. An applied order rests in the terminal state EFFECTIVE.
ORDER_EFFECTIVE = "EFFECTIVE"
DEFAULT_POINT_EXPIRY_DAYS = 730
NEW_POINT_EXPIRY_DAYS = 365
COMPETING_POINT_EXPIRY_DAYS = 400
NEW_SSP_MILLICENTS_PER_POINT = 1500
DEFAULT_SSP_MILLICENTS_PER_POINT = 1200
# A cohort starts at 0 and a single applied order of -400 leaves it at -400,
# comfortably inside the -5000 through 5000 clamp.
APPLIED_ELASTICITY_BP = -400
COHORT_ADJUSTMENT_AFTER_APPLY = -400
COMPETING_ELASTICITY_BP = 300
OTHER_TYPE_ELASTICITY_BP = -200
ORDER_A_EFFECTIVE_AT = "2026-10-01T00:00:00Z"
ORDER_B_EFFECTIVE_AT = "2026-11-01T00:00:00Z"


# ─── Setup shared by several tests ───────────────────────────────────────────
def _draft_program(api, **program_overrides):
    """
    A DRAFT programme carrying the one state expiry rule and the one cohort that
    activation demands. Returned as ``{"program", "cohort"}``.
    """
    program = fixtures.new_program(api, **program_overrides)
    fixtures.new_state_expiry_rule(
        api, program["id"], escheatment_required=False, escheat_rate_bp=0
    )
    cohort = fixtures.new_cohort(api, program["id"])
    return {"program": program, "cohort": cohort}


def _active_program(api, clock=CLOCK_EPOCH, **program_overrides):
    """The clock placed and that same programme driven DRAFT to ACTIVE."""
    fixtures.set_clock(api, clock)
    bundle = _draft_program(api, **program_overrides)
    bundle["program"] = fixtures.activate(api, bundle["program"]["id"])
    return bundle


def _ledger_ready(api, clock=CLOCK_EPOCH, **program_overrides):
    """An ACTIVE programme with one member and one OPEN August period."""
    bundle = _active_program(api, clock, **program_overrides)
    program_id = bundle["program"]["id"]
    bundle["member"] = fixtures.new_member(api, program_id, bundle["cohort"]["id"])
    bundle["period"] = fixtures.new_period(api, program_id)
    return bundle


def _lot_ready(api, clock=CLOCK_EPOCH):
    """:func:`_ledger_ready` plus one BASE lot of 1000 points inside the period."""
    bundle = _ledger_ready(api, clock)
    bundle["lot"] = fixtures.issue_lot(
        api, bundle["member"]["id"], bundle["period"]["id"], BASE_POINTS
    )
    return bundle


def _partner_statement_ready(api):
    """
    An ACTIVE programme with a GROSS third-party agreement, one 5000-point
    partner lot inside the August period, and that pairing's statement ISSUED.
    Returned as ``{"program", "cohort", "member", "period", "agreement",
    "partner_lot", "statement"}``.
    """
    bundle = _ledger_ready(api)
    bundle["agreement"] = fixtures.new_agreement(
        api,
        bundle["program"]["id"],
        min_invoice_cents=PARTNER_MIN_INVOICE_CENTS,
        net_settlement_enabled=False,
    )
    bundle["partner_lot"] = fixtures.issue_lot(
        api,
        bundle["member"]["id"],
        bundle["period"]["id"],
        PARTNER_POINTS,
        partner_agreement_id=bundle["agreement"]["id"],
    )
    bundle["statement"] = fixtures.issued_statement(
        api, bundle["agreement"]["id"], bundle["period"]["id"]
    )
    return bundle


def _program(api, program_id):
    """The programme as it stands now."""
    return assert_ok(api.get_program(program_id, PROGRAM_ADMIN_HEADERS))


def _period(api, period_id):
    """The accounting period as it stands now."""
    return assert_ok(api.get_period(period_id, CONTROLLER_HEADERS))


def _lot(api, lot_id):
    """The point lot as it stands now."""
    return assert_ok(api.get_point_lot(lot_id, ACCOUNTANT_HEADERS))


def _agreement(api, agreement_id):
    """The partner agreement as it stands now."""
    return assert_ok(api.get_agreement(agreement_id, ACCOUNTANT_HEADERS))


def _statement(api, statement_id):
    """The settlement statement as it stands now."""
    return assert_ok(api.get_statement(statement_id, ACCOUNTANT_HEADERS))


def _order(api, order_id):
    """The programme change order as it stands now."""
    return assert_ok(api.get_change_order(order_id, CONTROLLER_HEADERS))


# ─── LoyaltyProgram: the initial state ──────────────────────────────────────
def test_program_starts_in_draft_and_blocks_issuance(api):
    """
    A programme the client never assigns a status to is born DRAFT with a zero
    breakage rate, and DRAFT is not a status the ledger will work against: the
    issuance of a lot into an OPEN period of that programme is refused with
    ERR_PROGRAM_NOT_ACTIVE, no lot is minted and the member's balance stays 0.
    Enrolling the member and opening the period, by contrast, both succeed
    against a DRAFT programme, because only the ledger operations require ACTIVE.

    "A freshly created programme is born in status `DRAFT`, with `current_breakage_rate_bp` at 0, `total_escheat_accrual_cents` at 0, `escheat_disclosure_required` false, and `version` at 1."
    "Issuance, redemption, estimate preparation and settlement all require the programme to be `ACTIVE`, and an attempt against a programme in any other status is rejected with `ERR_PROGRAM_NOT_ACTIVE`."
    "That first activation seeds the programme's live breakage rate: `current_breakage_rate_bp` becomes 10000 basis points less `historical_redemption_rate_bp`."

    Design: Corner/state_machines/state_program_starts_in_draft_and_blocks_issuance
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    bundle = _draft_program(api)
    program_id = bundle["program"]["id"]
    assert_fields(
        bundle["program"],
        status=PROGRAM_DRAFT,
        current_breakage_rate_bp=0,
        total_escheat_accrual_cents=0,
        escheat_disclosure_required=False,
        version=1,
    )

    member = fixtures.new_member(api, program_id, bundle["cohort"]["id"])
    period = fixtures.new_period(api, program_id)
    assert_fields(period, state=PERIOD_OPEN)

    refused = api.create_point_lot(
        factories.point_lot_payload(
            member["id"],
            period["id"],
            BASE_POINTS,
            promo_multiplier_bp=IDENTITY_MULTIPLIER_BP,
        ),
        ACCOUNTANT_HEADERS,
    )
    assert_error(refused, ApiErrorId.PROGRAM_NOT_ACTIVE.value)

    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, period_id=period["id"]), total_count=0
    )
    assert_fields(
        _program(api, program_id),
        status=PROGRAM_DRAFT,
        current_breakage_rate_bp=0,
        version=1,
    )
    assert_fields(
        assert_ok(api.get_member(member["id"], ACCOUNTANT_HEADERS)), point_balance=0
    )


# ─── LoyaltyProgram: DRAFT → ACTIVE preconditions ───────────────────────────
def test_program_activate_without_any_cohort_rejected(api):
    """
    The first activation quantifies over two different children, and a
    programme holding a state expiry rule but no enrolment cohort satisfies only
    half of that: the activation is refused with ERR_PROGRAM_CONFIG_INCOMPLETE,
    the programme stays DRAFT with a zero rate and its version is untouched
    because a refused transition runs no side effect. Adding one cohort and
    repeating the identical call then succeeds and seeds 10000 - 7500 = 2500.

    "The first activation moves the programme `DRAFT → ACTIVE`, and it is permitted only when the programme already has at least one state expiry rule and at least one cohort; a programme missing either is rejected with `ERR_PROGRAM_CONFIG_INCOMPLETE`."
    "That first activation seeds the programme's live breakage rate: `current_breakage_rate_bp` becomes 10000 basis points less `historical_redemption_rate_bp`."
    "It also increments the programme's `version` by 1."

    Design: Corner/state_machines/state_program_activate_without_any_cohort_rejected
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(
        api, program["id"], escheatment_required=False, escheat_rate_bp=0
    )

    refused = api.activate_program(program["id"], None, PROGRAM_ADMIN_HEADERS)
    assert_error(refused, ApiErrorId.PROGRAM_CONFIG_INCOMPLETE.value)
    assert_fields(
        _program(api, program["id"]),
        status=PROGRAM_DRAFT,
        current_breakage_rate_bp=0,
        version=1,
    )

    fixtures.new_cohort(api, program["id"])
    activated = fixtures.activate(api, program["id"])
    assert_fields(
        activated,
        status=PROGRAM_ACTIVE,
        current_breakage_rate_bp=SEEDED_BREAKAGE_RATE_BP,
        version=2,
    )


def test_program_activate_without_any_state_expiry_rule_rejected(api):
    """
    The mirror half of the same precondition: a programme holding an enrolment
    cohort but no state expiry rule is equally missing one of the two children
    the first activation demands, so it too is refused with
    ERR_PROGRAM_CONFIG_INCOMPLETE and stays DRAFT at version 1. Declaring the
    rule and repeating the call then activates the programme and seeds 2500.

    "The first activation moves the programme `DRAFT → ACTIVE`, and it is permitted only when the programme already has at least one state expiry rule and at least one cohort; a programme missing either is rejected with `ERR_PROGRAM_CONFIG_INCOMPLETE`."
    "That first activation seeds the programme's live breakage rate: `current_breakage_rate_bp` becomes 10000 basis points less `historical_redemption_rate_bp`."

    Design: Corner/state_machines/state_program_activate_without_any_cohort_rejected
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_cohort(api, program["id"])

    refused = api.activate_program(program["id"], None, PROGRAM_ADMIN_HEADERS)
    assert_error(refused, ApiErrorId.PROGRAM_CONFIG_INCOMPLETE.value)
    assert_fields(
        _program(api, program["id"]),
        status=PROGRAM_DRAFT,
        current_breakage_rate_bp=0,
        version=1,
    )

    fixtures.new_state_expiry_rule(
        api, program["id"], escheatment_required=False, escheat_rate_bp=0
    )
    activated = fixtures.activate(api, program["id"])
    assert_fields(
        activated,
        status=PROGRAM_ACTIVE,
        current_breakage_rate_bp=SEEDED_BREAKAGE_RATE_BP,
        version=2,
    )


# ─── LoyaltyProgram: activation seeds, reactivation does not ─────────────────
def test_program_activate_seeds_rate_but_reactivation_does_not(api):
    """
    One endpoint carries two different transitions with different side effects.
    The first activation seeds the live breakage rate from the historical
    redemption rate, 10000 - 7500 = 2500, and a lot issued at that moment freezes
    2500. An approved estimate then overwrites the live rate with its own
    10000 - 8200 = 1800. Suspending and reactivating the programme walks the same
    endpoint again, and the reactivation must leave the rate where the approval
    put it: 1800, never re-seeded back to 2500. The proof is a second lot issued
    after the reactivation, which freezes 1800.

    "That first activation seeds the programme's live breakage rate: `current_breakage_rate_bp` becomes 10000 basis points less `historical_redemption_rate_bp`."
    "The second form is reactivation, `SUSPENDED → ACTIVE`, which explicitly does **not** reseed the rate — `current_breakage_rate_bp` is left exactly as the most recent estimate approval left it — and increments `version` by 1."
    "Suspension, `ACTIVE → SUSPENDED`, likewise increments `version` by 1; it blocks issuance and redemption while leaving period close and partner settlement fully available."
    "The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1."
    "`breakage_rate_bp_at_issue` takes the programme's `current_breakage_rate_bp` as it stands at this instant."

    Design: Corner/state_machines/state_program_activate_seeds_rate_but_reactivation_does_not
    """
    bundle = _ledger_ready(api)
    program_id = bundle["program"]["id"]
    assert_fields(
        bundle["program"],
        status=PROGRAM_ACTIVE,
        current_breakage_rate_bp=SEEDED_BREAKAGE_RATE_BP,
        version=2,
    )

    first_lot = fixtures.issue_lot(
        api, bundle["member"]["id"], bundle["period"]["id"], BASE_POINTS
    )
    assert_fields(
        first_lot,
        breakage_rate_bp_at_issue=SEEDED_BREAKAGE_RATE_BP,
        gross_ssp_cents=LOT_GROSS_CENTS,
        breakage_reserve_cents=LOT_RESERVE_CENTS,
        deferred_revenue_cents=LOT_DEFERRED_CENTS,
    )

    estimate = fixtures.approved_estimate(api, program_id, bundle["period"]["id"])
    assert_fields(
        estimate,
        state=ESTIMATE_APPROVED,
        estimated_redemption_rate_bp=COHORT_OBSERVED_RATE_BP,
        breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP,
    )
    assert_fields(
        _program(api, program_id),
        status=PROGRAM_ACTIVE,
        current_breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP,
        version=3,
    )

    suspended = assert_ok(api.suspend_program(program_id, None, PROGRAM_ADMIN_HEADERS))
    assert_fields(
        suspended,
        status=PROGRAM_SUSPENDED,
        current_breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP,
        version=4,
    )

    reactivated = assert_ok(api.activate_program(program_id, None, PROGRAM_ADMIN_HEADERS))
    assert_fields(
        reactivated,
        status=PROGRAM_ACTIVE,
        current_breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP,
        version=5,
    )

    second_lot = fixtures.issue_lot(
        api, bundle["member"]["id"], bundle["period"]["id"], BASE_POINTS
    )
    assert_fields(second_lot, breakage_rate_bp_at_issue=APPROVED_BREAKAGE_RATE_BP)


# ─── Repeating an action already performed ──────────────────────────────────
def test_program_activate_from_active_returns_invalid_state_transition(api):
    """
    ACTIVE is a legal target of the activation endpoint but never a legal source
    of it, so activating an already-ACTIVE programme is a repeat of an action
    already performed and is refused with ERR_INVALID_STATE_TRANSITION. The
    refusal must run no side effect at all: in particular the live breakage rate
    that a prior estimate approval installed, 1800, must not be re-seeded back to
    2500, and the programme's version must not move.

    "This covers every attempt to leave a terminal state and every repeat of an action already performed."
    "That first activation seeds the programme's live breakage rate: `current_breakage_rate_bp` becomes 10000 basis points less `historical_redemption_rate_bp`."
    "The second form is reactivation, `SUSPENDED → ACTIVE`, which explicitly does **not** reseed the rate — `current_breakage_rate_bp` is left exactly as the most recent estimate approval left it — and increments `version` by 1."

    Design: Corner/state_machines/state_program_activate_from_active_returns_invalid_state_transition
    """
    bundle = _lot_ready(api)
    program_id = bundle["program"]["id"]
    fixtures.approved_estimate(api, program_id, bundle["period"]["id"])
    before = _program(api, program_id)
    assert_fields(
        before,
        status=PROGRAM_ACTIVE,
        current_breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP,
        version=3,
    )

    refused = api.activate_program(program_id, None, PROGRAM_ADMIN_HEADERS)
    assert_error(refused, ApiErrorId.INVALID_STATE_TRANSITION.value)

    assert_fields(
        _program(api, program_id),
        status=PROGRAM_ACTIVE,
        current_breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP,
        version=3,
    )


def test_repeated_suspend_and_repeated_submit_are_also_invalid_transitions(api):
    """
    The same rung governs every action endpoint, not just activation. Submitting
    an estimate that is already SUBMITTED is a repeat of a performed action and
    is refused with ERR_INVALID_STATE_TRANSITION, leaving the estimate's state
    and version untouched; suspending a programme that is already SUSPENDED is
    refused the same way, leaving its status and version untouched.

    "This covers every attempt to leave a terminal state and every repeat of an action already performed."
    "A `LoyaltyAccountant` submits a `DRAFT` estimate, moving it `DRAFT → SUBMITTED`, which requires the supporting period to be `OPEN`, sets `submitted_at` to the clock reading and increments `version` by 1."
    "Suspension, `ACTIVE → SUSPENDED`, likewise increments `version` by 1; it blocks issuance and redemption while leaving period close and partner settlement fully available."

    Design: Corner/state_machines/state_program_activate_from_active_returns_invalid_state_transition
    """
    bundle = _lot_ready(api)
    program_id = bundle["program"]["id"]

    estimate = fixtures.submitted_estimate(api, program_id, bundle["period"]["id"])
    assert_fields(estimate, state=ESTIMATE_SUBMITTED, version=2)

    refused_submit = api.submit_estimate(estimate["id"], None, ACCOUNTANT_HEADERS)
    assert_error(refused_submit, ApiErrorId.INVALID_STATE_TRANSITION.value)
    assert_fields(
        assert_ok(api.get_estimate(estimate["id"], ACCOUNTANT_HEADERS)),
        state=ESTIMATE_SUBMITTED,
        version=2,
    )

    suspended = assert_ok(api.suspend_program(program_id, None, PROGRAM_ADMIN_HEADERS))
    assert_fields(suspended, status=PROGRAM_SUSPENDED, version=3)

    refused_suspend = api.suspend_program(program_id, None, PROGRAM_ADMIN_HEADERS)
    assert_error(refused_suspend, ApiErrorId.INVALID_STATE_TRANSITION.value)
    assert_fields(
        _program(api, program_id), status=PROGRAM_SUSPENDED, version=3
    )


# ─── LoyaltyProgram: CLOSED is terminal ─────────────────────────────────────
def test_program_closed_is_terminal_and_locks_all_transitions(api):
    """
    A programme with no accounting periods satisfies the closure precondition
    vacuously — every period has reached HARD_CLOSED because there are none — so
    it closes at version 3. CLOSED is then terminal in the strong sense: it is
    not a legal source state for any of the three transitions the programme
    exposes, so activation, suspension and a second closure are each refused with
    ERR_INVALID_STATE_TRANSITION and the status and version never move again.

    "Closure moves the programme `ACTIVE → CLOSED` or `SUSPENDED → CLOSED`, increments `version` by 1, and is permitted only when every accounting period of the programme has reached `HARD_CLOSED`; otherwise the attempt is rejected with `ERR_PERIODS_NOT_CLOSED`."
    "`CLOSED` is terminal."
    "This covers every attempt to leave a terminal state and every repeat of an action already performed."

    Design: Corner/state_machines/state_program_closed_is_terminal_and_locks_all_transitions
    """
    bundle = _active_program(api)
    program_id = bundle["program"]["id"]

    closed = assert_ok(api.close_program(program_id, None, PROGRAM_ADMIN_HEADERS))
    assert_fields(closed, status=PROGRAM_CLOSED, version=3)

    for refused in (
        api.activate_program(program_id, None, PROGRAM_ADMIN_HEADERS),
        api.suspend_program(program_id, None, PROGRAM_ADMIN_HEADERS),
        api.close_program(program_id, None, PROGRAM_ADMIN_HEADERS),
    ):
        assert_error(refused, ApiErrorId.INVALID_STATE_TRANSITION.value)

    assert_fields(_program(api, program_id), status=PROGRAM_CLOSED, version=3)


# ─── AccountingPeriod: the soft-close preconditions, one at a time ───────────
def test_soft_close_before_period_end_rejected(api):
    """
    The clock precondition is isolated by satisfying the two that outrank it: an
    APPROVED estimate exists and no redemption of the period is still merely
    requested. With the clock parked mid-window, at 2026-08-15, the period's
    2026-09-01 end has not been reached, so the close is refused with
    ERR_PERIOD_NOT_ENDED. The refusal is total: the period stays OPEN, all seven
    close-derived figures stay 0 and soft_closed_at stays null.

    "This requires the period to be `OPEN`, the logical clock to have reached or passed `end_at` (otherwise `ERR_PERIOD_NOT_ENDED`), an `APPROVED` estimate to exist for this period (otherwise `ERR_ESTIMATE_NOT_APPROVED`), and no `RedemptionEvent` of this period to still be in state `REQUESTED` (otherwise `ERR_UNALLOCATED_REDEMPTIONS`, since an unallocated request would leave revenue unmeasured)."
    "The same inclusive reading governs soft-close (permitted once the clock reaches the period's `end_at`, not before) and change-order application (permitted once the clock reaches the order's `effective_at`)."
    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."

    Design: Corner/state_machines/state_period_soft_close_preconditions_each_rejected_in_turn
    """
    bundle = _lot_ready(api)
    fixtures.approved_estimate(api, bundle["program"]["id"], bundle["period"]["id"])

    fixtures.set_clock(api, CLOCK_MID_AUGUST)
    refused = api.soft_close_period(bundle["period"]["id"], None, CONTROLLER_HEADERS)
    assert_error(refused, ApiErrorId.PERIOD_NOT_ENDED.value)

    period = _period(api, bundle["period"]["id"])
    assert_fields(
        period,
        state=PERIOD_OPEN,
        opening_liability_cents=0,
        pre_catchup_liability_cents=0,
        required_liability_cents=0,
        catch_up_adjustment_cents=0,
        closing_liability_cents=0,
        breakage_recognized_cents=0,
        approved_estimate_rate_bp=0,
        reopen_count=0,
    )
    assert_null_fields(period, "soft_closed_at")


def test_soft_close_without_approved_estimate_rejected(api):
    """
    With the clock advanced to the period's own end_at, the window precondition
    is satisfied and the estimate precondition is the one left standing: no
    estimate has ever been prepared for this period, so the close is refused with
    ERR_ESTIMATE_NOT_APPROVED. The period stays OPEN with every close-derived
    figure at 0, while the issuance movement the period already accumulated, 900
    cents of deferral, is untouched by the refusal.

    "This requires the period to be `OPEN`, the logical clock to have reached or passed `end_at` (otherwise `ERR_PERIOD_NOT_ENDED`), an `APPROVED` estimate to exist for this period (otherwise `ERR_ESTIMATE_NOT_APPROVED`), and no `RedemptionEvent` of this period to still be in state `REQUESTED` (otherwise `ERR_UNALLOCATED_REDEMPTIONS`, since an unallocated request would leave revenue unmeasured)."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."

    Design: Corner/state_machines/state_period_soft_close_preconditions_each_rejected_in_turn
    """
    bundle = _lot_ready(api)

    fixtures.set_clock(api, PERIOD_AUG_END)
    refused = api.soft_close_period(bundle["period"]["id"], None, CONTROLLER_HEADERS)
    assert_error(refused, ApiErrorId.ESTIMATE_NOT_APPROVED.value)

    period = _period(api, bundle["period"]["id"])
    assert_fields(
        period,
        state=PERIOD_OPEN,
        issuance_deferred_cents=LOT_DEFERRED_CENTS,
        required_liability_cents=0,
        closing_liability_cents=0,
        breakage_recognized_cents=0,
        approved_estimate_rate_bp=0,
    )
    assert_null_fields(period, "soft_closed_at")


def test_soft_close_with_unallocated_redemption_rejected(api):
    """
    With the window elapsed and an APPROVED estimate in place, the only
    precondition left is the one about unmeasured revenue: a redemption event of
    this period is still in REQUESTED because it was never allocated, so the
    close is refused with ERR_UNALLOCATED_REDEMPTIONS. Nothing moves — the period
    is still OPEN with a zero closing liability, the event is still REQUESTED
    with all four of its monetary figures at 0, and no revenue has been booked
    into the period's redemption_recognized_cents.

    "This requires the period to be `OPEN`, the logical clock to have reached or passed `end_at` (otherwise `ERR_PERIOD_NOT_ENDED`), an `APPROVED` estimate to exist for this period (otherwise `ERR_ESTIMATE_NOT_APPROVED`), and no `RedemptionEvent` of this period to still be in state `REQUESTED` (otherwise `ERR_UNALLOCATED_REDEMPTIONS`, since an unallocated request would leave revenue unmeasured)."
    "The new **RedemptionEvent** is born in `state` `REQUESTED` with `requested_at` set to the clock reading, `allocated_at` null, `reversal_reason` null, and its four monetary figures — `provisional_release_cents`, `final_release_cents`, `remeasurement_delta_cents` and `partner_cost_cents` — all at 0."

    Design: Corner/state_machines/state_period_soft_close_preconditions_each_rejected_in_turn
    """
    bundle = _lot_ready(api)
    fixtures.approved_estimate(api, bundle["program"]["id"], bundle["period"]["id"])
    event = fixtures.request_redemption(
        api, bundle["member"]["id"], bundle["period"]["id"], ALLOCATED_POINTS
    )
    assert_fields(event, state=REDEMPTION_REQUESTED, provisional_release_cents=0)

    fixtures.set_clock(api, PERIOD_AUG_END)
    refused = api.soft_close_period(bundle["period"]["id"], None, CONTROLLER_HEADERS)
    assert_error(refused, ApiErrorId.UNALLOCATED_REDEMPTIONS.value)

    period = _period(api, bundle["period"]["id"])
    assert_fields(
        period,
        state=PERIOD_OPEN,
        redemption_recognized_cents=0,
        closing_liability_cents=0,
        approved_estimate_rate_bp=0,
    )
    assert_fields(
        assert_ok(api.get_redemption(event["id"], ACCOUNTANT_HEADERS)),
        state=REDEMPTION_REQUESTED,
    )


def test_soft_close_succeeds_once_every_precondition_is_met(api):
    """
    Once the same period has an APPROVED estimate, the requested redemption has
    been allocated and the clock stands at end_at, the identical call succeeds and
    the rollforward runs. Opening is 0 because no sibling period is closed;
    pre-catch-up is 0 + 900 - 90 = 810; the at-close gross of the 900 points
    still outstanding is 1080 cents; the required liability at the approved 8200
    basis points is 886 cents; the catch-up is 886 - 810 = 76; the closing
    liability is 886; and the recognised breakage is the negation of the catch-up,
    -76.

    "A `Controller` soft-closes a period, driving it `OPEN → SOFT_CLOSED`."
    "`pre_catchup_liability_cents` is `opening_liability_cents` **plus** `issuance_deferred_cents`, **less** `redemption_recognized_cents`, **less** `remeasurement_delta_cents`, **less** `expiry_released_cents`."
    "`required_liability_cents` is that at-close gross multiplied by `approved_estimate_rate_bp`, divided by 10000, rounded half up."
    "`catch_up_adjustment_cents` is `required_liability_cents` less `pre_catchup_liability_cents`, and may be negative."
    "`closing_liability_cents` is `pre_catchup_liability_cents` plus `catch_up_adjustment_cents`."
    "`breakage_recognized_cents` is the negation of `catch_up_adjustment_cents` — negative when the liability must be topped up and positive when it is released."
    "It also records `provisional_release_cents` for the line: the line's gross less the reserve on that line, where the reserve is the line gross multiplied by **that lot's own** `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."

    Design: Corner/state_machines/state_period_soft_close_preconditions_each_rejected_in_turn
    """
    bundle = _lot_ready(api)
    program_id = bundle["program"]["id"]
    period_id = bundle["period"]["id"]
    fixtures.approved_estimate(api, program_id, period_id)

    event = fixtures.allocated_redemption(
        api, bundle["member"]["id"], period_id, ALLOCATED_POINTS
    )
    assert_fields(
        event,
        state=REDEMPTION_ALLOCATED,
        provisional_release_cents=LINE_PROVISIONAL_CENTS,
    )
    rows = assert_page(
        api.list_redemption_allocations(event["id"], ACCOUNTANT_HEADERS), total_count=1
    )
    assert_fields(
        rows[0],
        entry_type=ENTRY_TYPE_ALLOCATION,
        allocation_seq=1,
        points_allocated=ALLOCATED_POINTS,
        line_gross_ssp_cents=LINE_GROSS_CENTS,
        provisional_release_cents=LINE_PROVISIONAL_CENTS,
    )
    assert_fields(
        _lot(api, bundle["lot"]["id"]),
        lifecycle_state=LOT_PARTIALLY_REDEEMED,
        points_remaining=BASE_POINTS - ALLOCATED_POINTS,
    )

    fixtures.set_clock(api, PERIOD_AUG_END)
    closed = fixtures.soft_close(api, period_id)
    assert_fields(
        closed,
        state=PERIOD_SOFT_CLOSED,
        opening_liability_cents=0,
        issuance_deferred_cents=LOT_DEFERRED_CENTS,
        redemption_recognized_cents=LINE_PROVISIONAL_CENTS,
        remeasurement_delta_cents=0,
        expiry_released_cents=0,
        pre_catchup_liability_cents=REDEEMED_PRE_CATCHUP_CENTS,
        approved_estimate_rate_bp=COHORT_OBSERVED_RATE_BP,
        required_liability_cents=REDEEMED_REQUIRED_LIABILITY_CENTS,
        catch_up_adjustment_cents=REDEEMED_CATCH_UP_CENTS,
        closing_liability_cents=REDEEMED_REQUIRED_LIABILITY_CENTS,
        breakage_recognized_cents=REDEEMED_BREAKAGE_RECOGNIZED_CENTS,
        reopen_count=0,
    )


# ─── AccountingPeriod: the reopen budget is two and is never reset ───────────
def test_period_third_reopen_rejected_after_two(api):
    """
    The SOFT_CLOSED to OPEN edge is budgeted, not free. Each reopen fully
    compensates the close — all seven close-derived figures back to 0,
    soft_closed_at back to null, and the programme's year-to-date recognised
    breakage back to its exact pre-close value — while deliberately leaving the
    issuance movement of 900 cents alone, because that belongs to the issuance,
    not to the close. Two reopens are permitted and each raises reopen_count. The
    period can be closed a third time, but the third reopen is refused with
    ERR_REOPEN_LIMIT_EXCEEDED: the counter is never reset by anything, so the
    budget of two is spent for good.

    "A `Controller` may reopen a soft-closed period, `SOFT_CLOSED → OPEN`, provided `reopen_count` is below 2 (otherwise `ERR_REOPEN_LIMIT_EXCEEDED`)."
    "The reopen is a full compensation: `opening_liability_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `breakage_recognized_cents`, `closing_liability_cents` and `approved_estimate_rate_bp` all reset to 0, `soft_closed_at` becomes null, `reopen_count` increments by 1 and `version` increments by 1."
    "The movement accumulators are deliberately **not** reset — they belong to the events that produced them, not to the close."
    "None of the three counters is ever reset — not by a resolution, not by a reopen, not by any other operation."
    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."

    Design: Corner/state_machines/state_period_third_reopen_rejected_after_two
    """
    bundle = _lot_ready(api)
    program_id = bundle["program"]["id"]
    period_id = bundle["period"]["id"]
    fixtures.approved_estimate(api, program_id, period_id)
    fixtures.set_clock(api, PERIOD_AUG_END)

    expected_version = 1
    for expected_reopens in (0, 1, 2):
        closed = fixtures.soft_close(api, period_id)
        expected_version += 1
        assert_fields(
            closed,
            state=PERIOD_SOFT_CLOSED,
            issuance_deferred_cents=LOT_DEFERRED_CENTS,
            pre_catchup_liability_cents=LOT_DEFERRED_CENTS,
            approved_estimate_rate_bp=COHORT_OBSERVED_RATE_BP,
            required_liability_cents=FULL_REQUIRED_LIABILITY_CENTS,
            catch_up_adjustment_cents=FULL_CATCH_UP_CENTS,
            closing_liability_cents=FULL_REQUIRED_LIABILITY_CENTS,
            breakage_recognized_cents=FULL_BREAKAGE_RECOGNIZED_CENTS,
            reopen_count=expected_reopens,
            version=expected_version,
        )
        assert_fields(
            _program(api, program_id),
            recognized_breakage_ytd_cents=FULL_BREAKAGE_RECOGNIZED_CENTS,
        )

        if expected_reopens == 2:
            break

        reopened = assert_ok(api.reopen_period(period_id, None, CONTROLLER_HEADERS))
        expected_version += 1
        assert_fields(
            reopened,
            state=PERIOD_OPEN,
            opening_liability_cents=0,
            pre_catchup_liability_cents=0,
            required_liability_cents=0,
            catch_up_adjustment_cents=0,
            breakage_recognized_cents=0,
            closing_liability_cents=0,
            approved_estimate_rate_bp=0,
            issuance_deferred_cents=LOT_DEFERRED_CENTS,
            redemption_recognized_cents=0,
            remeasurement_delta_cents=0,
            expiry_released_cents=0,
            reopen_count=expected_reopens + 1,
            version=expected_version,
        )
        assert_null_fields(reopened, "soft_closed_at")
        assert_fields(_program(api, program_id), recognized_breakage_ytd_cents=0)

    refused = api.reopen_period(period_id, None, CONTROLLER_HEADERS)
    assert_error(refused, ApiErrorId.REOPEN_LIMIT_EXCEEDED.value)
    assert_fields(
        _period(api, period_id),
        state=PERIOD_SOFT_CLOSED,
        reopen_count=2,
        closing_liability_cents=FULL_REQUIRED_LIABILITY_CENTS,
        version=expected_version,
    )


# ─── SettlementStatement: the dispute budget is two and is never reset ───────
def test_statement_third_dispute_rejected_after_two(api):
    """
    A statement billing a 5000-point partner issuance at 900 millicents per point
    is due 4500 cents, above the 1000-cent invoice minimum, and falls due 30 whole
    days after the period's 2026-09-01 end, on 2026-10-01. Once issued it may be
    pushed back twice: each dispute raises dispute_count and each resolution
    returns the statement to ISSUED without re-measuring the amount due. The
    third dispute is refused with ERR_DISPUTE_LIMIT_EXCEEDED, because resolution
    never gives the budget back, and the agreement's outstanding balance of 4500
    is unmoved by the whole cycle.

    "An issued statement may be disputed by its partner while its `dispute_count` is below 2, and each dispute increments that counter; a third dispute is rejected with `ERR_DISPUTE_LIMIT_EXCEEDED`."
    "The dispute stores the reason, increments `dispute_count` by 1 and increments `version` by 1."
    "A `LoyaltyAccountant` resolves the dispute, moving the statement `DISPUTED → ISSUED` with a `resolution_note`, which is stored alongside a refreshed `issued_at`, and incrementing `version` by 1."
    "Resolution never re-measures `net_due_cents`; the bounded cycle `ISSUED → DISPUTED → ISSUED` may therefore run at most twice before `ERR_DISPUTE_LIMIT_EXCEEDED` closes it off."
    "None of the three counters is ever reset — not by a resolution, not by a reopen, not by any other operation."
    "From those two counts, `issuance_receivable_cents` is `partner_issued_points` multiplied by the agreement's `issuance_rate_millicents_per_point`, divided by 1000, rounded half up, and `redemption_payable_cents` is `partner_redeemed_points` multiplied by the agreement's `redemption_rate_millicents_per_point`, divided by 1000, rounded half up."
    "`due_date` is the period's `end_at` advanced by the agreement's `settlement_lag_days` whole days."
    "Issuing a statement is a `LoyaltyAccountant` action that moves it `DRAFT → ISSUED`, requires the owning agreement to be `ACTIVE`, sets `issued_at` to the clock reading, adds the statement's `net_due_cents` to the agreement's `outstanding_settlement_cents`, and increments both the agreement's and the statement's `version` by 1."

    Design: Corner/state_machines/state_statement_third_dispute_rejected_after_two
    """
    bundle = _partner_statement_ready(api)
    statement_id = bundle["statement"]["id"]
    agreement_id = bundle["agreement"]["id"]
    partner_headers = make_partner_operator_headers(agreement_id)

    assert_fields(
        bundle["statement"],
        state=STATEMENT_ISSUED,
        settlement_basis=BASIS_GROSS,
        partner_issued_points=PARTNER_POINTS,
        partner_redeemed_points=0,
        issuance_receivable_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
        redemption_payable_cents=0,
        carried_forward_cents=0,
        net_due_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
        deferred_below_minimum_cents=0,
        due_date=PARTNER_DUE_DATE,
        dispute_count=0,
        version=2,
    )
    assert_fields(
        _agreement(api, agreement_id),
        status=AGREEMENT_ACTIVE,
        outstanding_settlement_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
    )

    expected_version = 2
    for expected_disputes in (1, 2):
        disputed = assert_ok(
            api.dispute_statement(statement_id, factories.dispute_payload(), partner_headers)
        )
        expected_version += 1
        assert_fields(
            disputed,
            state=STATEMENT_DISPUTED,
            dispute_count=expected_disputes,
            net_due_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
            version=expected_version,
        )

        resolved = assert_ok(
            api.resolve_statement(
                statement_id, factories.resolution_payload(), ACCOUNTANT_HEADERS
            )
        )
        expected_version += 1
        assert_fields(
            resolved,
            state=STATEMENT_ISSUED,
            dispute_count=expected_disputes,
            net_due_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
            version=expected_version,
        )

    refused = api.dispute_statement(
        statement_id, factories.dispute_payload(), partner_headers
    )
    assert_error(refused, ApiErrorId.DISPUTE_LIMIT_EXCEEDED.value)
    assert_fields(
        _statement(api, statement_id),
        state=STATEMENT_ISSUED,
        dispute_count=2,
        net_due_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
        version=expected_version,
    )
    assert_fields(
        _agreement(api, agreement_id),
        status=AGREEMENT_ACTIVE,
        outstanding_settlement_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
    )
    assert_fields(
        _lot(api, bundle["partner_lot"]["id"]),
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_PENDING,
    )


# ─── Member: DORMANT is not terminal ────────────────────────────────────────
def test_member_dormant_then_reactivated_by_new_issuance(api):
    """
    A lot issued on 2026-08-05 expires 730 whole days later, on 2028-08-04, so a
    sweep run on 2028-08-05 finds it eligible under the inclusive comparison. The
    sweep captures the lot's remaining gross of 1200 and its remaining deferral of
    900 before emptying it, moves it OUTSTANDING to EXPIRED, and books the 900
    into the swept period. With escheatment switched off the lot rests at EXPIRED
    and nothing accrues to the state. The member, now holding a zero balance and
    731 days of dormancy, falls ACTIVE to DORMANT in the same request. A second
    sweep changes nothing, because an EXPIRED lot is never re-swept. DORMANT is
    then shown not to be terminal: a fresh 500-point issuance revives the member
    to ACTIVE, refreshes last_activity_at and rebuilds the balance.

    "Candidates are the programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` and whose `expires_at` is at or before the clock reading; the comparison is inclusive, so a lot whose `expires_at` is exactly the current clock reading is eligible while one an instant later is not."
    "`issued_at` takes the current logical clock reading, and `expires_at` is set to `issued_at` advanced by the programme's `point_expiry_days` whole days."
    "`points_remaining` is then set to 0 and `lifecycle_state` moves `OUTSTANDING → EXPIRED` or `PARTIALLY_REDEEMED → EXPIRED`."
    "The captured released deferral is added to the **swept** period's `expiry_released_cents`, and the lot's `version` increments by 1."
    "When `escheatment_required` is false, `escheated_cents` stays 0 and the lot rests at `EXPIRED`."
    "Lots already `EXPIRED` or `ESCHEATED` are never re-swept, and `settlement_state` is irrelevant to eligibility."
    "A member whose `status` is `ACTIVE`, whose `point_balance` is 0 after the pass, and whose `dormancy_days` is at least 730 — two years since `last_activity_at` — moves `ACTIVE → DORMANT` with `version` incremented by 1."
    "Dormancy is not terminal: the next issuance to that member revives it."
    "If that member was `DORMANT`, the issuance revives it: the member moves `DORMANT → ACTIVE`, and the member's `version` increments by 1."
    "`last_activity_at` on the holder is set to the current clock reading."

    Design: Corner/state_machines/state_member_dormant_then_reactivated_by_new_issuance
    """
    bundle = _ledger_ready(api)
    program_id = bundle["program"]["id"]
    member_id = bundle["member"]["id"]
    later_period = fixtures.new_period(
        api,
        program_id,
        period_code=PERIOD_2028_CODE,
        start_at=PERIOD_2028_START,
        end_at=PERIOD_2028_END,
    )

    fixtures.set_clock(api, CLOCK_AUGUST_FIFTH)
    first_lot = fixtures.issue_lot(api, member_id, bundle["period"]["id"], BASE_POINTS)
    assert_fields(
        first_lot,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_NOT_APPLICABLE,
        issued_at=CLOCK_AUGUST_FIFTH,
        expires_at=LOT_EXPIRES_AT,
        breakage_rate_bp_at_issue=SEEDED_BREAKAGE_RATE_BP,
        deferred_revenue_cents=LOT_DEFERRED_CENTS,
        points_remaining=BASE_POINTS,
    )
    assert_fields(
        assert_ok(api.get_member(member_id, ACCOUNTANT_HEADERS)),
        status=MEMBER_ACTIVE,
        point_balance=BASE_POINTS,
        last_activity_at=CLOCK_AUGUST_FIFTH,
        dormancy_days=0,
    )

    fixtures.set_clock(api, CLOCK_TWO_YEARS_ON)
    assert_ok(api.run_expiry_sweep(later_period["id"], None, ACCOUNTANT_HEADERS))

    assert_fields(
        _lot(api, first_lot["id"]),
        lifecycle_state=LOT_EXPIRED,
        points_remaining=0,
        expired_gross_ssp_cents=LOT_GROSS_CENTS,
        escheated_cents=0,
    )
    assert_fields(
        _period(api, later_period["id"]),
        state=PERIOD_OPEN,
        expiry_released_cents=LOT_DEFERRED_CENTS,
        escheat_accrual_cents=0,
    )
    assert_fields(
        _program(api, program_id),
        total_escheat_accrual_cents=0,
        escheat_disclosure_required=False,
    )
    assert_fields(
        assert_ok(api.get_member(member_id, ACCOUNTANT_HEADERS)),
        status=MEMBER_DORMANT,
        point_balance=0,
        dormancy_days=731,
    )

    assert_ok(api.run_expiry_sweep(later_period["id"], None, ACCOUNTANT_HEADERS))
    assert_fields(
        _period(api, later_period["id"]),
        expiry_released_cents=LOT_DEFERRED_CENTS,
        escheat_accrual_cents=0,
    )
    assert_fields(
        _lot(api, first_lot["id"]), lifecycle_state=LOT_EXPIRED, points_remaining=0
    )

    revived_lot = fixtures.issue_lot(api, member_id, later_period["id"], 500)
    assert_fields(
        revived_lot,
        lifecycle_state=LOT_OUTSTANDING,
        points_remaining=500,
        gross_ssp_cents=600,
        breakage_rate_bp_at_issue=SEEDED_BREAKAGE_RATE_BP,
        deferred_revenue_cents=450,
        expires_at=REVIVED_LOT_EXPIRES_AT,
    )
    assert_fields(
        assert_ok(api.get_member(member_id, ACCOUNTANT_HEADERS)),
        status=MEMBER_ACTIVE,
        point_balance=500,
        last_activity_at=CLOCK_TWO_YEARS_ON,
        dormancy_days=0,
    )


# ─── BreakageEstimate: DRAFT is not a legal source of approve or reject ──────
def test_estimate_approve_from_draft_returns_invalid_state_transition(api):
    """
    Both approval and rejection depart from SUBMITTED, so a DRAFT estimate is not
    a legal source state for either and both are refused with
    ERR_INVALID_STATE_TRANSITION. Because the state check is ranked above the
    segregation-of-duties check, even an approval offered by the very person who
    prepared the estimate is diagnosed as the wrong state rather than as a
    duties conflict. The refusals write nothing: the estimate stays DRAFT at
    version 1 with approved_by_user_id, approved_at, submitted_at and
    rejection_reason all still null, and the programme's live breakage rate stays
    at the seeded 2500. Submitting first and offering the identical approval body
    then succeeds and installs 1800.

    "The estimate is then persisted in `state` `DRAFT`, with `prepared_by_user_id` set to the acting `X-User-ID`, `revision_count` at 0, `supersedes_estimate_id` null, `approved_by_user_id` null, `rejection_reason` null, and `submitted_at` and `approved_at` both null."
    "Approval is a `Controller` action, moves the estimate `SUBMITTED → APPROVED`, and is the most consequential single request in the system."
    "A `Controller` may push back, moving the estimate `SUBMITTED → REJECTED` with a `rejection_reason` that is stored on the estimate, incrementing `version` by 1."
    "**Current state is a legal source state for the requested transition** — `ERR_INVALID_STATE_TRANSITION` (409), on every action endpoint that drives a state machine."
    "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (409), on estimate approval."
    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."
    "A `LoyaltyAccountant` submits a `DRAFT` estimate, moving it `DRAFT → SUBMITTED`, which requires the supporting period to be `OPEN`, sets `submitted_at` to the clock reading and increments `version` by 1."
    "The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1."

    Design: Corner/state_machines/state_estimate_approve_from_draft_returns_invalid_state_transition
    """
    bundle = _lot_ready(api)
    program_id = bundle["program"]["id"]
    estimate = fixtures.draft_estimate(api, program_id, bundle["period"]["id"])
    assert_fields(
        estimate,
        state=ESTIMATE_DRAFT,
        revision_count=0,
        estimated_redemption_rate_bp=COHORT_OBSERVED_RATE_BP,
        breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP,
        version=1,
    )
    assert_null_fields(
        estimate,
        "approved_by_user_id",
        "approved_at",
        "submitted_at",
        "rejection_reason",
        "supersedes_estimate_id",
    )

    approval = factories.approval_payload(fixtures.program_version(api, program_id))
    assert_error(
        api.approve_estimate(estimate["id"], approval, CONTROLLER_HEADERS),
        ApiErrorId.INVALID_STATE_TRANSITION.value,
    )
    assert_error(
        api.reject_estimate(estimate["id"], factories.rejection_payload(), CONTROLLER_HEADERS),
        ApiErrorId.INVALID_STATE_TRANSITION.value,
    )
    assert_error(
        api.approve_estimate(estimate["id"], approval, PREPARER_AS_CONTROLLER_HEADERS),
        ApiErrorId.INVALID_STATE_TRANSITION.value,
    )

    unchanged = assert_ok(api.get_estimate(estimate["id"], ACCOUNTANT_HEADERS))
    assert_fields(unchanged, state=ESTIMATE_DRAFT, version=1)
    assert_null_fields(
        unchanged, "approved_by_user_id", "approved_at", "submitted_at", "rejection_reason"
    )
    assert_fields(
        _program(api, program_id),
        current_breakage_rate_bp=SEEDED_BREAKAGE_RATE_BP,
        version=2,
    )

    submitted = assert_ok(api.submit_estimate(estimate["id"], None, ACCOUNTANT_HEADERS))
    assert_fields(submitted, state=ESTIMATE_SUBMITTED, version=2)

    approved = assert_ok(
        api.approve_estimate(estimate["id"], approval, CONTROLLER_HEADERS)
    )
    assert_fields(approved, state=ESTIMATE_APPROVED, version=3)
    assert_fields(
        _program(api, program_id),
        current_breakage_rate_bp=APPROVED_BREAKAGE_RATE_BP,
        version=3,
    )


# ─── SettlementStatement: write-off cascades onto agreement and lots ─────────
def test_statement_write_off_suspends_agreement_and_marks_lots(api):
    """
    A write-off is not a private fact about one statement. Writing off the 4500
    cents due on a partner statement clears the agreement's outstanding balance to
    0, drives the agreement ACTIVE to SUSPENDED, and marks the matching
    PENDING_SETTLEMENT lot WRITTEN_OFF on the billing dimension while leaving its
    lifecycle dimension entirely alone: the lot is still OUTSTANDING with all
    5000 points remaining, because the member's promise survives the partner's
    failure to pay. A sibling lot issued with no partner named stays
    NOT_APPLICABLE and is never touched. With the agreement suspended, a further
    statement is refused with ERR_AGREEMENT_NOT_ACTIVE.

    "A write-off stores the supplied `write_off_reason`, subtracts `net_due_cents` from the agreement's `outstanding_settlement_cents`, drives every matching `PENDING_SETTLEMENT` lot of the same agreement-and-period pair to `WRITTEN_OFF` in `created_at` ascending order with each lot's `version` incremented by 1, additionally drives the owning agreement `ACTIVE → SUSPENDED` — no new statement may be created while an agreement is suspended — and increments both the agreement's and the statement's `version` by 1."
    "Write-off is available from `ISSUED → WRITTEN_OFF` and equally from `DISPUTED → WRITTEN_OFF`; both paths behave identically."
    "The partner-billing dimension, `settlement_state`, is born `NOT_APPLICABLE` when no partner was named, and is born `PENDING_SETTLEMENT` when one was — the dimension-two assignment `NOT_APPLICABLE → PENDING_SETTLEMENT` happens at creation, so a partner lot is born `PENDING_SETTLEMENT` on one dimension while being born `OUTSTANDING` on the other."
    "The independence is real and testable: an `OUTSTANDING` lot may be `SETTLED`, and a `FULLY_REDEEMED` lot may still be `PENDING_SETTLEMENT`."
    "The agreement must be `ACTIVE` — a `SUSPENDED` or `TERMINATED` agreement yields `ERR_AGREEMENT_NOT_ACTIVE` — the period must not be `HARD_CLOSED`, and the period and the agreement must belong to the same programme, else `ERR_PERIOD_PROGRAM_MISMATCH` or `ERR_AGREEMENT_PROGRAM_MISMATCH` as appropriate."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."

    Design: Corner/state_machines/state_statement_write_off_suspends_agreement_and_marks_lots
    """
    bundle = _ledger_ready(api)
    period_id = bundle["period"]["id"]
    agreement = fixtures.new_agreement(
        api,
        bundle["program"]["id"],
        min_invoice_cents=PARTNER_MIN_INVOICE_CENTS,
        net_settlement_enabled=False,
    )
    partner_lot = fixtures.issue_lot(
        api,
        bundle["member"]["id"],
        period_id,
        PARTNER_POINTS,
        partner_agreement_id=agreement["id"],
    )
    house_lot = fixtures.issue_lot(api, bundle["member"]["id"], period_id, BASE_POINTS)
    assert_fields(
        partner_lot,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_PENDING,
        deferred_revenue_cents=PARTNER_LOT_DEFERRED_CENTS,
    )
    assert_fields(
        house_lot,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_NOT_APPLICABLE,
        deferred_revenue_cents=LOT_DEFERRED_CENTS,
    )
    assert_fields(
        _period(api, period_id),
        issuance_deferred_cents=PARTNER_LOT_DEFERRED_CENTS + LOT_DEFERRED_CENTS,
    )

    statement = fixtures.issued_statement(api, agreement["id"], period_id)
    assert_fields(
        statement,
        state=STATEMENT_ISSUED,
        partner_issued_points=PARTNER_POINTS,
        net_due_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
    )
    before = _agreement(api, agreement["id"])
    assert_fields(
        before,
        status=AGREEMENT_ACTIVE,
        outstanding_settlement_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
    )

    written_off = assert_ok(
        api.write_off_statement(
            statement["id"], factories.write_off_payload(), CONTROLLER_HEADERS
        )
    )
    assert_fields(
        written_off,
        state=STATEMENT_WRITTEN_OFF,
        write_off_reason=factories.write_off_payload()["write_off_reason"],
        net_due_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
        version=statement["version"] + 1,
    )
    assert_fields(
        _agreement(api, agreement["id"]),
        status=AGREEMENT_SUSPENDED,
        outstanding_settlement_cents=0,
        version=before["version"] + 1,
    )
    assert_fields(
        _lot(api, partner_lot["id"]),
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_WRITTEN_OFF,
        points_remaining=PARTNER_POINTS,
        version=partner_lot["version"] + 1,
    )
    assert_fields(
        _lot(api, house_lot["id"]),
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_NOT_APPLICABLE,
        points_remaining=BASE_POINTS,
        version=house_lot["version"],
    )

    refused = api.create_statement(
        factories.statement_payload(
            agreement["id"], period_id, fixtures.agreement_version(api, agreement["id"])
        ),
        ACCOUNTANT_HEADERS,
    )
    assert_error(refused, ApiErrorId.AGREEMENT_NOT_ACTIVE.value)


# ─── PartnerAgreement: termination needs a cleared balance ───────────────────
def test_agreement_terminate_with_outstanding_settlement_rejected(api):
    """
    Termination is guarded by money, not only by state. While the agreement still
    owes 4500 cents on an issued statement, termination is refused with
    ERR_OUTSTANDING_SETTLEMENT and the agreement stays ACTIVE with the balance and
    version untouched. Paying the statement clears the balance to 0 and marks the
    partner lot SETTLED on the billing dimension while its lifecycle dimension
    stays OUTSTANDING with all 5000 points intact. Termination then succeeds, and
    because TERMINATED is terminal a second termination is refused with
    ERR_INVALID_STATE_TRANSITION rather than with the money check, since the state
    check is evaluated first.

    "Terminating an agreement is a `ProgramAdmin` action, permitted from `ACTIVE → TERMINATED` and from `SUSPENDED → TERMINATED`, and only when the agreement's `outstanding_settlement_cents` is exactly 0; a non-zero balance is rejected with `ERR_OUTSTANDING_SETTLEMENT`."
    "Termination increments the agreement's `version` by 1, and `TERMINATED` is terminal."
    "Payment moves the statement `ISSUED → PAID`, which is terminal: it sets `paid_at` to the clock reading, subtracts `net_due_cents` from the agreement's `outstanding_settlement_cents`, increments the agreement's `version` by 1 and the statement's `version` by 1, and drives every lot sharing the statement's `partner_agreement_id` and `period_id` whose `settlement_state` is `PENDING_SETTLEMENT` to `SETTLED`, walking those lots in `created_at` ascending order and incrementing each lot's `version` by 1."
    "The independence is real and testable: an `OUTSTANDING` lot may be `SETTLED`, and a `FULLY_REDEEMED` lot may still be `PENDING_SETTLEMENT`."
    "This covers every attempt to leave a terminal state and every repeat of an action already performed."
    "The server evaluates the checks below in the stated order and the **first** violation decides the response; later violations are never reported."

    Design: Corner/state_machines/state_agreement_terminate_with_outstanding_settlement_rejected
    """
    bundle = _partner_statement_ready(api)
    agreement_id = bundle["agreement"]["id"]
    statement_id = bundle["statement"]["id"]

    before = _agreement(api, agreement_id)
    assert_fields(
        before,
        status=AGREEMENT_ACTIVE,
        outstanding_settlement_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
    )
    refused = api.terminate_agreement(agreement_id, None, PROGRAM_ADMIN_HEADERS)
    assert_error(refused, ApiErrorId.OUTSTANDING_SETTLEMENT.value)
    assert_fields(
        _agreement(api, agreement_id),
        status=AGREEMENT_ACTIVE,
        outstanding_settlement_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
        version=before["version"],
    )

    paid = assert_ok(api.pay_statement(statement_id, None, CONTROLLER_HEADERS))
    assert_fields(
        paid,
        state=STATEMENT_PAID,
        paid_at=CLOCK_EPOCH,
        net_due_cents=PARTNER_ISSUANCE_RECEIVABLE_CENTS,
    )
    assert_fields(
        _lot(api, bundle["partner_lot"]["id"]),
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_SETTLED,
        points_remaining=PARTNER_POINTS,
    )
    cleared = _agreement(api, agreement_id)
    assert_fields(
        cleared,
        status=AGREEMENT_ACTIVE,
        outstanding_settlement_cents=0,
        version=before["version"] + 1,
    )

    terminated = assert_ok(
        api.terminate_agreement(agreement_id, None, PROGRAM_ADMIN_HEADERS)
    )
    assert_fields(
        terminated,
        status=AGREEMENT_TERMINATED,
        outstanding_settlement_cents=0,
        version=cleared["version"] + 1,
    )

    again = api.terminate_agreement(agreement_id, None, PROGRAM_ADMIN_HEADERS)
    assert_error(again, ApiErrorId.INVALID_STATE_TRANSITION.value)
    assert_fields(
        _agreement(api, agreement_id),
        status=AGREEMENT_TERMINATED,
        version=terminated["version"],
    )


# ─── LoyaltyProgram: closure quantifies over every period ────────────────────
def test_program_close_with_open_period_rejected(api):
    """
    Closure is a quantified precondition over children, and it is satisfied only
    by HARD_CLOSED. With the period still OPEN the closure is refused with
    ERR_PERIODS_NOT_CLOSED. Soft-closing the period books the rollforward — a
    required liability of 984 cents against a pre-catch-up of 900, hence a
    catch-up of 84 and recognised breakage of -84 — but SOFT_CLOSED is still not
    HARD_CLOSED, so the closure is refused a second time with the same error. Only
    after the hard close does the programme close, at version 4, with its
    year-to-date recognised breakage reading -84 from the one sealed period.

    "Closure moves the programme `ACTIVE → CLOSED` or `SUSPENDED → CLOSED`, increments `version` by 1, and is permitted only when every accounting period of the programme has reached `HARD_CLOSED`; otherwise the attempt is rejected with `ERR_PERIODS_NOT_CLOSED`."
    "A `Controller` hard-closes a soft-closed period, `SOFT_CLOSED → HARD_CLOSED`, which is terminal."
    "`catch_up_adjustment_cents` is `required_liability_cents` less `pre_catchup_liability_cents`, and may be negative."
    "`breakage_recognized_cents` is the negation of `catch_up_adjustment_cents` — negative when the liability must be topped up and positive when it is released."
    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."

    Design: Corner/state_machines/state_program_close_with_open_period_rejected
    """
    bundle = _lot_ready(api)
    program_id = bundle["program"]["id"]
    period_id = bundle["period"]["id"]
    fixtures.approved_estimate(api, program_id, period_id)
    fixtures.set_clock(api, PERIOD_AUG_END)

    assert_error(
        api.close_program(program_id, None, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.PERIODS_NOT_CLOSED.value,
    )
    assert_fields(_program(api, program_id), status=PROGRAM_ACTIVE, version=3)

    closed_period = fixtures.soft_close(api, period_id)
    assert_fields(
        closed_period,
        state=PERIOD_SOFT_CLOSED,
        pre_catchup_liability_cents=LOT_DEFERRED_CENTS,
        required_liability_cents=FULL_REQUIRED_LIABILITY_CENTS,
        catch_up_adjustment_cents=FULL_CATCH_UP_CENTS,
        closing_liability_cents=FULL_REQUIRED_LIABILITY_CENTS,
        breakage_recognized_cents=FULL_BREAKAGE_RECOGNIZED_CENTS,
    )

    assert_error(
        api.close_program(program_id, None, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.PERIODS_NOT_CLOSED.value,
    )
    assert_fields(_program(api, program_id), status=PROGRAM_ACTIVE, version=3)

    sealed = assert_ok(api.hard_close_period(period_id, None, CONTROLLER_HEADERS))
    assert_fields(
        sealed,
        state=PERIOD_HARD_CLOSED,
        closing_liability_cents=FULL_REQUIRED_LIABILITY_CENTS,
        breakage_recognized_cents=FULL_BREAKAGE_RECOGNIZED_CENTS,
    )

    closed_program = assert_ok(api.close_program(program_id, None, PROGRAM_ADMIN_HEADERS))
    assert_fields(
        closed_program,
        status=PROGRAM_CLOSED,
        version=4,
        recognized_breakage_ytd_cents=FULL_BREAKAGE_RECOGNIZED_CENTS,
    )


# ─── ProgramChangeOrder: application waits for its instant ───────────────────
def test_change_order_apply_before_effective_at_rejected(api):
    """
    An approved order that shortens the expiry horizon from 730 days to 365 may
    not be applied until the clock reaches its 2026-12-01 effective instant: the
    early attempt is refused with ERR_CHANGE_NOT_YET_EFFECTIVE and the whole
    three-link cascade is suppressed — the order stays APPROVED with a null
    applied_at, the programme still reads 730 days, the lot issued at the epoch
    still expires on 2028-07-31, and the cohort's behavioural adjustment is still
    0. Once the clock stands exactly on the effective instant the same call
    succeeds, the order rests in the terminal state EFFECTIVE, the programme takes
    365 days, the lot's expiry is recomputed from its own issuance instant to
    2027-08-01, and the cohort's adjustment moves by -400. Applying the terminal
    order again is refused with ERR_INVALID_STATE_TRANSITION.

    "A `Controller` applies an approved order, `APPROVED → EFFECTIVE`, which is terminal, and only once the clock has reached or passed `effective_at` — an earlier attempt is rejected with `ERR_CHANGE_NOT_YET_EFFECTIVE`."
    "The same inclusive reading governs soft-close (permitted once the clock reaches the period's `end_at`, not before) and change-order application (permitted once the clock reaches the order's `effective_at`)."
    "The order's new value is written onto the programme — `new_point_expiry_days` onto `point_expiry_days`, `new_ssp_millicents_per_point` onto `ssp_millicents_per_point`, or `new_tier_multiplier_bp` onto `tier_multiplier_bp` — and the programme's `version` increments by 1."
    "Every lot of the programme whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` has its `expires_at` recomputed as its own `issued_at` plus the **new** `point_expiry_days` whole days, processed in `created_at` ascending order, each lot's `version` incrementing by 1."
    "Every cohort of the programme has its `program_change_adjustment_bp` increased by the order's `behavior_elasticity_bp`, with the result clamped into the range -5000 through 5000, processed in `enrollment_start_date` ascending then `created_at` ascending order, each cohort's `version` incrementing by 1."
    "`applied_at` is set to the clock reading and the order's `version` increments by 1."
    "This covers every attempt to leave a terminal state and every repeat of an action already performed."

    Design: Corner/state_machines/state_change_order_apply_before_effective_at_rejected
    """
    bundle = _lot_ready(api)
    program_id = bundle["program"]["id"]
    cohort_id = bundle["cohort"]["id"]
    lot = bundle["lot"]
    assert_fields(lot, issued_at=CLOCK_EPOCH, expires_at=EPOCH_LOT_EXPIRES_AT)

    order = fixtures.approved_change_order(
        api,
        program_id,
        CLOCK_DECEMBER,
        change_type=CHANGE_EXPIRY_DAYS,
        behavior_elasticity_bp=APPLIED_ELASTICITY_BP,
        new_point_expiry_days=NEW_POINT_EXPIRY_DAYS,
    )
    assert_fields(
        order,
        state=ORDER_APPROVED,
        change_type=CHANGE_EXPIRY_DAYS,
        new_point_expiry_days=NEW_POINT_EXPIRY_DAYS,
        effective_at=CLOCK_DECEMBER,
        behavior_elasticity_bp=APPLIED_ELASTICITY_BP,
    )
    assert_null_fields(order, "applied_at", "cancelled_by_order_id")

    refused = api.apply_change_order(order["id"], None, CONTROLLER_HEADERS)
    assert_error(refused, ApiErrorId.CHANGE_NOT_YET_EFFECTIVE.value)

    still_approved = _order(api, order["id"])
    assert_fields(still_approved, state=ORDER_APPROVED, version=order["version"])
    assert_null_fields(still_approved, "applied_at")
    assert_fields(
        _program(api, program_id),
        point_expiry_days=DEFAULT_POINT_EXPIRY_DAYS,
        version=2,
    )
    assert_fields(_lot(api, lot["id"]), expires_at=EPOCH_LOT_EXPIRES_AT, version=1)
    assert_fields(
        assert_ok(api.get_cohort(cohort_id, PROGRAM_ADMIN_HEADERS)),
        program_change_adjustment_bp=0,
        version=1,
    )

    fixtures.set_clock(api, CLOCK_DECEMBER)
    applied = assert_ok(api.apply_change_order(order["id"], None, CONTROLLER_HEADERS))
    assert_fields(
        applied,
        state=ORDER_EFFECTIVE,
        applied_at=CLOCK_DECEMBER,
        version=order["version"] + 1,
    )
    assert_fields(
        _program(api, program_id),
        point_expiry_days=NEW_POINT_EXPIRY_DAYS,
        version=3,
    )
    assert_fields(
        _lot(api, lot["id"]),
        lifecycle_state=LOT_OUTSTANDING,
        issued_at=CLOCK_EPOCH,
        expires_at=RE_DATED_LOT_EXPIRES_AT,
        version=2,
    )
    assert_fields(
        assert_ok(api.get_cohort(cohort_id, PROGRAM_ADMIN_HEADERS)),
        program_change_adjustment_bp=COHORT_ADJUSTMENT_AFTER_APPLY,
        version=2,
    )

    again = api.apply_change_order(order["id"], None, CONTROLLER_HEADERS)
    assert_error(again, ApiErrorId.INVALID_STATE_TRANSITION.value)
    assert_fields(
        _order(api, order["id"]), state=ORDER_EFFECTIVE, version=order["version"] + 1
    )


# ─── ProgramChangeOrder: approval is exclusive within its change type ────────
def test_change_order_approve_cancels_competing_modeled_order(api):
    """
    Approving one order cancels its rivals, but only the rivals of the same change
    type. Three orders are modelled: two expiry-days changes and one standalone
    selling price change. Approving the second expiry-days order drives the first
    MODELED to CANCELLED with cancelled_by_order_id naming the approved order,
    while the selling price order is left untouched in MODELED with a null
    cancelled_by_order_id. Approval writes nothing onto the programme — the expiry
    horizon is still 730 days and the selling price still 1200 millicents, because
    the change lands only when the order is applied. Approving the approved order
    again, or the cancelled one, is refused with ERR_INVALID_STATE_TRANSITION.

    "A `Controller` approves an order, `MODELED → APPROVED`, which requires the programme's `status` to be `ACTIVE`."
    "Approval is exclusive within its change type: every **other** order of the same programme with the same `change_type` and `state` `MODELED` moves `MODELED → CANCELLED` with `cancelled_by_order_id` set to the approved order's `id`, processed in `created_at` ascending order and each incrementing its own `version` by 1."
    "Competing orders of a *different* change type are untouched."
    "The order is born in `state` `MODELED`, the programme is untouched, and the projection is **never** re-measured when the order is later approved or applied."
    "The order's new value is written onto the programme — `new_point_expiry_days` onto `point_expiry_days`, `new_ssp_millicents_per_point` onto `ssp_millicents_per_point`, or `new_tier_multiplier_bp` onto `tier_multiplier_bp` — and the programme's `version` increments by 1."
    "This covers every attempt to leave a terminal state and every repeat of an action already performed."

    Design: Corner/state_machines/state_change_order_approve_cancels_competing_modeled_order
    """
    bundle = _active_program(api)
    program_id = bundle["program"]["id"]

    first_expiry_order = fixtures.modeled_change_order(
        api,
        program_id,
        ORDER_A_EFFECTIVE_AT,
        change_type=CHANGE_EXPIRY_DAYS,
        behavior_elasticity_bp=APPLIED_ELASTICITY_BP,
        new_point_expiry_days=NEW_POINT_EXPIRY_DAYS,
    )
    ssp_order = fixtures.modeled_change_order(
        api,
        program_id,
        ORDER_B_EFFECTIVE_AT,
        change_type=CHANGE_SSP,
        behavior_elasticity_bp=OTHER_TYPE_ELASTICITY_BP,
        new_point_expiry_days=None,
        new_ssp_millicents_per_point=NEW_SSP_MILLICENTS_PER_POINT,
    )
    second_expiry_order = fixtures.modeled_change_order(
        api,
        program_id,
        CLOCK_DECEMBER,
        change_type=CHANGE_EXPIRY_DAYS,
        behavior_elasticity_bp=COMPETING_ELASTICITY_BP,
        new_point_expiry_days=COMPETING_POINT_EXPIRY_DAYS,
    )
    for order in (first_expiry_order, ssp_order, second_expiry_order):
        assert_fields(order, state=ORDER_MODELED, version=1)
        assert_null_fields(order, "applied_at", "cancelled_by_order_id")

    approved = assert_ok(
        api.approve_change_order(second_expiry_order["id"], None, CONTROLLER_HEADERS)
    )
    assert_fields(
        approved,
        state=ORDER_APPROVED,
        change_type=CHANGE_EXPIRY_DAYS,
        new_point_expiry_days=COMPETING_POINT_EXPIRY_DAYS,
        version=2,
    )
    assert_null_fields(approved, "applied_at", "cancelled_by_order_id")

    assert_fields(
        _order(api, first_expiry_order["id"]),
        state=ORDER_CANCELLED,
        cancelled_by_order_id=second_expiry_order["id"],
        version=2,
    )
    untouched = _order(api, ssp_order["id"])
    assert_fields(
        untouched,
        state=ORDER_MODELED,
        change_type=CHANGE_SSP,
        new_ssp_millicents_per_point=NEW_SSP_MILLICENTS_PER_POINT,
        version=1,
    )
    assert_null_fields(untouched, "cancelled_by_order_id")

    assert_fields(
        _program(api, program_id),
        point_expiry_days=DEFAULT_POINT_EXPIRY_DAYS,
        ssp_millicents_per_point=DEFAULT_SSP_MILLICENTS_PER_POINT,
        version=2,
    )

    assert_page(
        api.list_change_orders(
            CONTROLLER_HEADERS, program_id=program_id, state=ORDER_MODELED
        ),
        expected_ids=[ssp_order["id"]],
        total_count=1,
    )
    assert_page(
        api.list_change_orders(
            CONTROLLER_HEADERS, cancelled_by_order_id=second_expiry_order["id"]
        ),
        expected_ids=[first_expiry_order["id"]],
        total_count=1,
    )

    assert_error(
        api.approve_change_order(second_expiry_order["id"], None, CONTROLLER_HEADERS),
        ApiErrorId.INVALID_STATE_TRANSITION.value,
    )
    assert_error(
        api.approve_change_order(first_expiry_order["id"], None, CONTROLLER_HEADERS),
        ApiErrorId.INVALID_STATE_TRANSITION.value,
    )
    assert_fields(_order(api, second_expiry_order["id"]), state=ORDER_APPROVED, version=2)
    assert_fields(_order(api, first_expiry_order["id"]), state=ORDER_CANCELLED, version=2)
