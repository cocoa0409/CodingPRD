"""State-machine behavior: the cyclic event round-advance loop, the grading fork
(GRADED vs REJECTED), invalid-transition guards, precondition enforcement, the bye
side effect, and allocated-pre-order cancellation compensation.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_customer, create_inventory_item, create_inventory_item_with_stock,
    create_submitted_buylist, create_listed_consignment,
    setup_in_progress_event_with_two_players, create_pairing, report_pairing,
    create_open_event, create_checked_in_registration,
    create_release_product, create_requested_pre_order, create_allocated_pre_order,
    create_at_grader_submission, set_clock,
    ApiErrorId, TEST_USERS, make_customer_headers,
)

SM = TEST_USERS["store_manager_headers"]
JUDGE = TEST_USERS["judge_headers"]


# ─── non_linear_state_machine (difficulty) ──────────────────────────────────────
def test_event_advance_round_is_cyclic_self_loop(api):
    """PRD §3.5: "Advancing to the next round is a judge-staff action and a cyclic
    self-transition: it keeps the event `IN_PROGRESS` while incrementing
    `current_round` by one, opening a new round for pairing. It requires that every
    pairing in the event's current round has a result other than `PENDING`
    (otherwise `ERR_ROUND_NOT_COMPLETE`)"

    Design: Difficulty/non_linear_state_machine/event_cyclic_round_advance
    """
    ev, ca, cb, ra, rb = setup_in_progress_event_with_two_players(
        starts_at="2026-07-01T00:00:00Z", ends_at="2026-07-01T05:00:00Z")
    assert ev["current_round"] == 1
    pr = create_pairing(ev, ra, rb)
    report_pairing(pr, "A_WINS")
    advanced = validate_success(api.advance_round(ev["id"], JUDGE), 200)
    assert advanced["current_round"] == 2
    assert advanced["status"] == "IN_PROGRESS"


def test_grading_fork_graded_with_grade(api):
    """PRD §3.6: "When the body provides an `assigned_grade`, the result must lie
    between 1 and 10 inclusive (otherwise `ERR_INVALID_GRADE`); the submission moves
    to `GRADED` and the numeric grade is stored on `assigned_grade`."

    Design: Difficulty/non_linear_state_machine/grading_branch_graded_vs_rejected
    """
    item, owner = create_inventory_item_with_stock(market_price_cents=4000, quantity=1)
    gs = create_at_grader_submission(owner, item, declared_value_cents=10000,
                                     service_tier="STANDARD")
    graded = validate_success(
        api.return_grading_result(gs["id"], {"assigned_grade": 9.5}, SM), 200)
    assert graded["status"] == "GRADED"
    assert graded["assigned_grade"] == 9.5


def test_grading_fork_rejected_without_grade(api):
    """PRD §3.6: "When the body omits `assigned_grade` — the grader could not
    encapsulate the card — the submission moves to `REJECTED` and `assigned_grade`
    stays null."

    Design: Difficulty/non_linear_state_machine/grading_branch_graded_vs_rejected
    """
    item, owner = create_inventory_item_with_stock(market_price_cents=4000, quantity=1)
    gs = create_at_grader_submission(owner, item, declared_value_cents=10000,
                                     service_tier="STANDARD")
    rejected = validate_success(api.return_grading_result(gs["id"], {}, SM), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["assigned_grade"] is None


# ─── corner: invalid transitions ────────────────────────────────────────────────
def test_buylist_double_submit_rejected(api):
    """PRD §3.2: "Submitting the draft moves it from `DRAFT` to `SUBMITTED`". Per
    PRD §2.9 the system "check[s] that the target resource is in a state from which
    the requested transition is defined, failing with `ERR_INVALID_STATE` (HTTP
    409)".

    Design: Corner/state_machines/buylist_double_submit_invalid_state
    """
    cust = create_customer("DS", "ds@x.com")
    item = create_inventory_item(title="DS Card", market_price_cents=500)
    sub = create_submitted_buylist(cust, [(item, 1)], payout_method="CASH")
    res = api.submit_buylist(sub["id"], make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_consignment_settle_from_listed_rejected(api):
    """PRD §3.7: "Settling a sold case is a store-manager action defined only from
    `SOLD` (otherwise `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/consignment_settle_from_listed_terminal_guard
    """
    cust = create_customer("CS", "cs2@x.com")
    item = create_inventory_item(title="CS Card", market_price_cents=1000)
    cc = create_listed_consignment(cust, item, quantity=1, ask_price_cents=1000,
                                   commission_rate_bps=1500)
    res = api.settle_consignment_case(cc["id"], SM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


# ─── corner: precondition enforcement ───────────────────────────────────────────
def test_start_event_with_no_seated_players_rejected(api):
    """PRD §3.5: "Starting an event is a judge-staff action that moves it from
    `OPEN` to `IN_PROGRESS`. It requires the event's `seated_count` to be at least 1
    (otherwise `ERR_NO_SEATED_PLAYERS`) and sets `current_round` to 1."

    Design: Corner/state_machines/event_start_with_no_seated_players
    """
    set_clock("2026-06-01T00:00:00Z")
    ev = create_open_event(title="Empty Floor", format="DRAFT",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T03:00:00Z", capacity=8,
                           entry_fee_cents=1000)
    res = api.start_event(ev["id"], JUDGE)
    validate_error(res, ApiErrorId.ERR_NO_SEATED_PLAYERS)


def test_advance_round_with_pending_pairing_rejected(api):
    """PRD §3.5: "It requires that every pairing in the event's current round has a
    result other than `PENDING` (otherwise `ERR_ROUND_NOT_COMPLETE`) and that the
    current round is below the cap of 5 rounds (otherwise `ERR_MAX_ROUNDS_REACHED`)."

    Design: Corner/state_machines/event_advance_round_not_complete
    """
    ev, ca, cb, ra, rb = setup_in_progress_event_with_two_players(
        starts_at="2026-07-02T00:00:00Z", ends_at="2026-07-02T05:00:00Z")
    create_pairing(ev, ra, rb)  # left PENDING
    res = api.advance_round(ev["id"], JUDGE)
    validate_error(res, ApiErrorId.ERR_ROUND_NOT_COMPLETE)


# ─── corner: side effect execution (bye) ────────────────────────────────────────
def test_bye_awards_three_match_points(api):
    """PRD §3.5: "The bye outcome `BYE_A` is the symmetric case: it is valid only
    when the second player is absent (otherwise `ERR_INVALID_STATE`) and awards a
    win by adding 3 to player A's `match_points`."

    Design: Corner/state_machines/pairing_bye_awards_three_points
    """
    ev, ca, cb, ra, rb = setup_in_progress_event_with_two_players(
        starts_at="2026-07-03T00:00:00Z", ends_at="2026-07-03T05:00:00Z",
        event_format="COMMANDER")
    pr = create_pairing(ev, ra, None)  # bye: no second player
    reported = validate_success(api.report_pairing(pr["id"], {"result": "BYE_A"}, JUDGE), 200)
    assert reported["result"] == "BYE_A"
    reg_a = validate_success(api.get_registration(ra["id"], SM), 200)
    assert reg_a["match_points"] == 3


# ─── corner: compensation (cancel allocated pre-order) ──────────────────────────
def test_cancel_allocated_preorder_frees_pool(api):
    """PRD §3.3: "Cancellation of an `ALLOCATED` pre-order also moves it to
    `CANCELLED`, but additionally frees the allocation: the release product's
    `quantity_allocated` decreases by the pre-order's requested quantity and its
    `version` increments by one."

    Design: Corner/state_machines/preorder_cancel_allocated_frees_pool
    """
    cust = create_customer("Canc PO", "cancpo@x.com", credit_cents=5000)
    rp = create_release_product(title="Cancelable Box", allocation_pool=10,
                                unit_price_cents=1000, deposit_required_cents=500)
    po, rp_after = create_allocated_pre_order(cust, rp, requested_quantity=2,
                                              deposit_paid_cents=500)
    assert rp_after["quantity_allocated"] == 2
    cancelled = validate_success(
        api.cancel_pre_order(po["id"], make_customer_headers(cust["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    rp_final = validate_success(api.get_release_product(rp["id"], SM), 200)
    assert rp_final["quantity_allocated"] == 0
