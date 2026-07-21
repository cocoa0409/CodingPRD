"""Statement generation rounding, the payment/aging parallel axes, and the
suspend/reinstate cycle.

Queue A: cf_statement_total_nested_rounding_mode_b, nlsm_member_active_suspended_active_cycle,
nlsm_statement_parallel_payment_vs_aging.
Queue B: OCC stale-version and statement-not-found corners.

Note: the difficulty instance ppvc_state_beats_fiscal_on_reservation_create is
intentionally NOT translated — see the generation summary (PRD §3.4 does not name a
member-account_status check for reservation creation, so ERR_MEMBER_SUSPENDED there
is not uniquely derivable).
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    generate_statement_payload,
    make_member_headers,
    new_member,
    pay_statement_payload,
    set_clock,
    setup_member_with_statement,
    setup_suspended_member,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── cf_statement_total_nested_rounding_mode_b ────────────────────────────

def test_statement_lines_rounded_independently(api):
    """PRD §3.9: "maintenance_fee_cents is the member's owned_points multiplied by the
    maintenance rate of 0.0653 US dollars per point, converted to cents and rounded
    half up to a whole cent; club_dues_cents is the member's owned_points multiplied by
    the club-dues rate of 0.0089 US dollars per point, converted to cents and rounded
    half up to a whole cent."

    Design: Difficulty/combinatorial_formula/cf_statement_total_nested_rounding_mode_b
    """
    world = setup_member_with_statement(owned_points=4750, special_assessment_cents=25000)
    st = world["statement"]
    assert st["maintenance_fee_cents"] == 31018  # round_half_up(4750 * 0.0653 * 100)
    assert st["club_dues_cents"] == 4228  # round_half_up(4750 * 0.0089 * 100)


def test_statement_total_is_sum_of_rounded_lines(api):
    """PRD §3.9: "The total_due_cents is the sum of these two independently rounded
    lines plus the special_assessment_cents." PRD §2.7: "the system must not round a
    single combined rate, because per-line rounding can differ from that by a cent."

    Design: Difficulty/combinatorial_formula/cf_statement_total_nested_rounding_mode_b
    """
    world = setup_member_with_statement(owned_points=4750, special_assessment_cents=25000)
    st = world["statement"]
    assert st["total_due_cents"] == 60246  # 31018 + 4228 + 25000


# ─── nlsm_member_active_suspended_active_cycle ────────────────────────────

def test_payoff_reinstates_suspended_member(api):
    """PRD §3.9: "When a payoff clears a member's last outstanding delinquent statement
    and that member is SUSPENDED, the payoff also reinstates the member to ACTIVE".

    Design: Difficulty/non_linear_state_machine/nlsm_member_active_suspended_active_cycle
    """
    world = setup_suspended_member(owned_points=5000)  # total 37100, member SUSPENDED
    assert world["member"]["account_status"] == "SUSPENDED"
    validate_success(
        api.pay_statement(world["statement"]["id"], pay_statement_payload(37100), world["member_headers"]),
        200,
    )
    member = validate_success(api.get_member(world["member"]["id"], ADMIN), 200)
    assert member["account_status"] == "ACTIVE"


def test_full_payoff_marks_statement_paid_and_current(api):
    """PRD §3.9: "If the payment brings amount_paid_cents to at least total_due_cents,
    the statement reaches PAID: amount_paid_cents rises by the paid amount, and on that
    payoff the aging_status is set to CURRENT, clearing any delinquency on the aging axis."

    Design: Difficulty/non_linear_state_machine/nlsm_member_active_suspended_active_cycle
    """
    world = setup_suspended_member(owned_points=5000)
    st = validate_success(
        api.pay_statement(world["statement"]["id"], pay_statement_payload(37100), world["member_headers"]),
        200,
    )
    assert st["payment_status"] == "PAID"
    assert st["aging_status"] == "CURRENT"


# ─── nlsm_statement_parallel_payment_vs_aging ─────────────────────────────

def test_partial_payment_moves_only_payment_axis(api):
    """PRD §3.9: "If the payment is a positive amount that is strictly less than the
    remaining balance (the total_due_cents minus the current amount_paid_cents), the
    statement moves from UNPAID to PARTIALLY_PAID". The aging axis only clears on payoff.

    Design: Difficulty/non_linear_state_machine/nlsm_statement_parallel_payment_vs_aging
    """
    world = setup_suspended_member(owned_points=5000)  # statement PAST_DUE, UNPAID
    st = validate_success(
        api.pay_statement(world["statement"]["id"], pay_statement_payload(100), world["member_headers"]),
        200,
    )
    assert st["payment_status"] == "PARTIALLY_PAID"
    assert st["aging_status"] == "PAST_DUE"


def test_partial_payment_accumulates_amount_paid(api):
    """PRD §3.9: "the statement moves from `UNPAID` to `PARTIALLY_PAID` and
    `amount_paid_cents` rises by the paid amount."

    Design: Difficulty/non_linear_state_machine/nlsm_statement_parallel_payment_vs_aging
    """
    world = setup_suspended_member(owned_points=5000)
    st = validate_success(
        api.pay_statement(world["statement"]["id"], pay_statement_payload(100), world["member_headers"]),
        200,
    )
    assert st["amount_paid_cents"] == 100


# ─── Queue B corners ──────────────────────────────────────────────────────

def test_stale_member_version_on_generate(api):
    """PRD §2.8: "If that value does not match the target member's current version —
    because another writer has generated the current-period statement and advanced the
    member since the client last read it — the request is rejected with ERR_STALE_VERSION
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_member_version_on_statement_generate
    """
    world = setup_member_with_statement(owned_points=5000)  # first generate, member.version 1 -> 2
    stale_version = world["member"]["version"]  # 1, now stale
    resp = api.generate_statement(world["member"]["id"], generate_statement_payload(stale_version), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_pay_unknown_statement_not_found(api):
    """PRD §2.9: "a missing statement `ERR_STATEMENT_NOT_FOUND`, and a missing transfer
    `ERR_TRANSFER_NOT_FOUND`, each with HTTP 404."

    Design: Corner/validations/corner_not_found_statement_on_pay
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    resp = api.pay_statement(NON_EXISTENT_UUID, pay_statement_payload(100), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_FOUND.value, 404)
