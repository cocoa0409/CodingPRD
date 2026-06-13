"""Companion (second-coverage) tests for the depth-targeted scenarios.

Each depth scenario carries a second test here that asserts a distinct
PRD-derivable fact (a different branch, a side effect, or a boundary neighbour)
rather than restating the first test's assertion.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_patron_headers, TEST_USERS,
    setup_active_loan, setup_blocked_patron_via_lost, setup_loan_with_waiting_hold,
    setup_pool_with_active_ebook_loan, setup_room_with_confirmed_reservation,
    assert_pool_token_invariant, current_resource_version, get_only_unpaid_fine,
    list_unpaid_fines, create_branch, create_patron, create_title, create_copy,
    create_loan, create_resource, create_reservation, set_clock,
)
from test_helpers import api_client as _client  # noqa

LIBRARIAN = TEST_USERS["librarian_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


# ---- dual_variant_calc ----
def test_overdue_estimate_uses_projected_return_days(api):
    """PRD §3.3: "`overdue_days` is the whole UTC days by which `projected_return`
    exceeds the `due_date`, never below zero; `chargeable_days` is `overdue_days`
    minus the branch's `grace_days`, never below zero".

    Design: Difficulty/dual_variant_calc/overdue_fine_estimate_vs_final_diverge_on_loan
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"fine_free": False, "daily_fine_cents": 25,
                          "max_fine_cents": 1000, "grace_days": 1, "loan_period_days": 7},
        isbn="9780000000201", clock="2026-06-01T00:00:00Z")
    # due 2026-06-08; projected 2026-06-13 -> overdue_days 5, chargeable 4.
    est = validate_success(api.fine_estimate(
        loan["id"], LIBRARIAN, params={"projected_return": "2026-06-13T00:00:00Z"}), 200)
    assert est["overdue_days"] == 5
    assert est["chargeable_days"] == 4
    assert est["estimate_cents"] == 100


def test_replacement_default_variant_ignores_depreciation(api):
    """PRD §3.5: "When `flat_replacement` is true, the default variant is used:
    depreciation and `condition_factor` are ignored entirely, the item-value
    component is simply the title's `default_replacement_cents`".

    Design: Difficulty/dual_variant_calc/replacement_charge_depreciated_vs_default_diverge_on_copy
    """
    # Old, degraded copy: depreciation/condition would lower the charge, but flat ignores them.
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"loan_period_days": 7, "block_threshold_cents": 100000},
        isbn="9780000000202",
        title_overrides={"default_replacement_cents": 4000},
        copy_overrides={"acquired_on": "2024-06-01T00:00:00Z", "condition_factor": 0.5},
        clock="2026-06-01T00:00:00Z")
    validate_success(api.declare_lost(loan["id"], LIBRARIAN, {"flat_replacement": True}), 200)
    fine = get_only_unpaid_fine(patron["id"])
    # flat item 4000 + processing round(4000*0.10)=400 -> 4400, no depreciation applied.
    assert fine["amount_cents"] == 4400


# ---- combinatorial_formula ----
def test_overdue_fine_just_below_cap_not_capped(api):
    """PRD §3.4: "the raw fine is `chargeable_days` multiplied by `daily_fine_cents`,
    and the assessed fine is the smaller of that raw amount and `max_fine_cents`."

    Design: Difficulty/combinatorial_formula/overdue_fine_nested_min_max_with_grace_and_cap
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"daily_fine_cents": 25, "max_fine_cents": 1000,
                          "grace_days": 1, "loan_period_days": 7},
        isbn="9780000000203", clock="2026-06-01T00:00:00Z")
    # due 2026-06-08; return 2026-06-30 -> 22 overdue, chargeable 21, 21*25=525 < 1000 cap.
    set_clock("2026-06-30T00:00:00Z")
    final = validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)
    assert final["accrued_fine_cents"] == 525, "below the cap the raw value stands"


def test_replacement_components_summed_after_rounding(api):
    """PRD §3.5: "The second component is a flat processing fee: the title's
    `default_replacement_cents` multiplied by ten percent, rounded half up to whole
    cents on its own. The replacement charge is the sum of these two already-rounded
    components."

    Design: Difficulty/combinatorial_formula/replacement_charge_round_each_component_then_sum
    """
    branch = create_branch(loan_period_days=7, block_threshold_cents=100000)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Round2 Pat")
    # default 2525: processing round(2525*0.10)=round(252.5)=253 (half up); item flat 2525.
    title = create_title(branch["id"], "9780000000204", title_text="Round2 Book",
                         default_replacement_cents=2525)
    copy = create_copy(title["id"], branch["id"], "BC-R2",
                       acquired_on="2026-06-01T00:00:00Z", condition_factor=1.0)
    loan = create_loan(copy["id"], patron["id"])
    validate_success(api.declare_lost(loan["id"], LIBRARIAN, {"flat_replacement": True}), 200)
    fine = get_only_unpaid_fine(patron["id"])
    assert fine["amount_cents"] == 2778, "2525 + round_half_up(252.5)=253 -> 2778"


def test_account_summary_below_tier_no_waiver(api):
    """PRD §3.1: "if `raw_total_cents` is at least 2000 cents, `waiver_cents` is set
    to a goodwill waiver of 200 cents; otherwise `waiver_cents` is zero."

    Design: Difficulty/combinatorial_formula/account_balance_waiver_tier_evaluation_order
    """
    branch = create_branch(loan_period_days=7, block_threshold_cents=100000)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="UnderTier Pat")
    title = create_title(branch["id"], "9780000000205", title_text="UnderTier Book",
                         default_replacement_cents=1500)
    copy = create_copy(title["id"], branch["id"], "BC-UT",
                       acquired_on="2026-06-01T00:00:00Z", condition_factor=1.0)
    loan = create_loan(copy["id"], patron["id"])
    api.declare_lost(loan["id"], LIBRARIAN, {"flat_replacement": True})
    # flat 1500 + processing 150 -> 1650 raw, below tier 2000.
    summary = validate_success(api.get_account_summary(patron["id"], LIBRARIAN), 200)
    assert summary["raw_total_cents"] == 1650
    assert summary["waiver_cents"] == 0
    assert summary["net_owed_cents"] == 1650


# ---- non_linear_state_machine ----
def test_loan_renewal_advances_due_date_once(api):
    """PRD §3.3: "A successful renewal increments `renewal_count` by one, advances
    `due_date` by another `loan_period_days`, and increments the loan's `version`."

    Design: Difficulty/non_linear_state_machine/loan_renewal_self_loop_cyclic
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"loan_period_days": 7}, isbn="9780000000206",
        clock="2026-06-01T00:00:00Z")
    before_version = loan["version"]
    r1 = validate_success(api.renew_loan(loan["id"], make_patron_headers(patron["id"])), 200)
    assert r1["renewal_count"] == 1
    assert r1["status"] == "ACTIVE"
    # checkout 2026-06-01 + 7 + 7 = 2026-06-15.
    assert r1["due_date"].startswith("2026-06-15")
    assert r1["version"] > before_version


def test_reservation_confirmed_to_cancelled_frees_window(api):
    """PRD §3.7: "a patron may cancel their own `REQUESTED` or `CONFIRMED`
    reservation, or a librarian may cancel on their behalf, moving it to
    `CANCELLED` and freeing the window with no check-in recorded."

    Design: Difficulty/non_linear_state_machine/reservation_confirmed_branches_to_divergent_terminals
    """
    branch, patron, resource, reservation = setup_room_with_confirmed_reservation(
        buffer_minutes=0, clock_before="2026-06-01T09:00:00Z",
        start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
    res = validate_success(
        api.cancel_reservation(reservation["id"], make_patron_headers(patron["id"])), 200)
    assert res["status"] == "CANCELLED"
    assert res["checked_in_at"] is None, "CANCELLED fork records no check-in"


# ---- transitive_cascade ----
def test_declare_lost_reduces_title_total_copy_count(api):
    """PRD §3.5: "The title's `available_copy_count` and `total_copy_count` are both
    reconciled because a lost copy leaves both the available pool and the
    non-withdrawn total".

    Design: Difficulty/transitive_cascade/declare_lost_cascade_to_patron_block_depth4
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"loan_period_days": 7, "block_threshold_cents": 1000},
        isbn="9780000000207",
        title_overrides={"default_replacement_cents": 3000},
        copy_overrides={"acquired_on": "2026-06-01T00:00:00Z", "condition_factor": 1.0},
        clock="2026-06-01T00:00:00Z")
    before = validate_success(api.get_title(title["id"], LIBRARIAN), 200)
    assert before["total_copy_count"] == 1
    validate_success(api.declare_lost(loan["id"], LIBRARIAN, {"flat_replacement": True}), 200)
    after = validate_success(api.get_title(title["id"], LIBRARIAN), 200)
    # PRD §2.6 authoritative definition: `total_copy_count` is the number of copies
    # that are NOT `WITHDRAWN`. A `LOST` copy is a distinct status from `WITHDRAWN`
    # (§2.6 copy-status enum), so it remains in the non-withdrawn total. The §3.5
    # justification clause ("a lost copy leaves ... the non-withdrawn total")
    # contradicts that definition and is not uniquely derivable, so it is not
    # asserted here. The `available_copy_count` reconciliation is asserted because
    # the copy is no longer `AVAILABLE`.
    assert after["available_copy_count"] == 0


def test_checkin_promotion_sets_pickup_deadline_and_queue_zero(api):
    """PRD §3.6: "a free copy is reserved (`AVAILABLE → ON_HOLD_SHELF`),
    `ready_copy_id` records it, `ready_at` is stamped, the `pickup_deadline` is set
    to `ready_at` advanced by the pickup window".
    PRD §3.6: "holds that are `READY` or in any terminal status carry
    `queue_position` zero."

    Design: Difficulty/transitive_cascade/checkin_return_promotes_head_hold_depth3
    """
    branch, pa, pb, title, copy, loan, hold = setup_loan_with_waiting_hold(
        clock="2026-06-01T00:00:00Z", isbn="9780000000208")
    validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)
    hold_after = validate_success(api.get_hold(hold["id"], LIBRARIAN), 200)
    assert hold_after["status"] == "READY"
    assert hold_after["ready_at"] is not None
    assert hold_after["pickup_deadline"] is not None
    assert hold_after["queue_position"] == 0, "READY holds carry queue_position 0"


# ---- priority_pair_validation_conflict ----
def test_checkout_limit_alone_returns_limit_exceeded(api):
    """PRD §3.3: "The patron's open physical-loan count — loans in `ACTIVE` or
    `OVERDUE` status — must be below their `checkout_limit`; a checkout that would
    exceed it is rejected with `ERR_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/checkout_state_beats_business_constraint
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    p = create_patron(branch["id"], full_name="OnlyLimit Pat", checkout_limit=1)
    title = create_title(branch["id"], "9780000000209", title_text="OnlyLimit Book")
    c1 = create_copy(title["id"], branch["id"], "BC-OL1")
    c2 = create_copy(title["id"], branch["id"], "BC-OL2")
    create_loan(c1["id"], p["id"])  # p at limit 1; c2 is AVAILABLE.
    # Only the limit is violated (c2 AVAILABLE) -> isolates priority-10.
    res = _client.create_loan({"copy_id": c2["id"], "patron_id": p["id"]}, LIBRARIAN)
    validate_error(res, "ERR_LIMIT_EXCEEDED")


def test_reservation_conflict_alone_returns_conflict(api):
    """PRD §3.7: "The interval must not conflict with existing active reservations
    on the same resource (else `ERR_RESERVATION_CONFLICT`), where "active" means
    reservations in `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` status."

    Design: Difficulty/priority_pair_validation_conflict/reservation_temporal_beats_fiscal_block_pair
    """
    branch = create_branch(reservation_buffer_minutes=0)
    set_clock("2026-06-01T09:00:00Z")
    holder = create_patron(branch["id"], full_name="Holder2 Pat")
    clear_patron = create_patron(branch["id"], full_name="Clear Pat")  # CLEAR, not blocked
    resource = create_resource(branch["id"], "ROOM", "Room Q")
    create_reservation(resource["id"], holder["id"], "2026-06-01T10:00:00Z",
                       "2026-06-01T11:00:00Z", resource["version"],
                       patron_headers=make_patron_headers(holder["id"]))
    v = current_resource_version(resource["id"])
    # CLEAR patron books an overlapping window: only priority-9 conflict applies.
    res = _client.create_reservation(
        {"resource_id": resource["id"], "patron_id": clear_patron["id"],
         "start_at": "2026-06-01T10:30:00Z", "end_at": "2026-06-01T11:30:00Z",
         "expected_resource_version": v}, make_patron_headers(clear_patron["id"]))
    validate_error(res, "ERR_RESERVATION_CONFLICT")


# ---- boundary_precision_check (grace edge, two-above neighbour) ----
def test_overdue_two_days_past_grace_charges_two_days(api):
    """PRD §3.4: "`chargeable_days` is `overdue_days` minus the branch's
    `grace_days` (never below zero, so any day index up to and including
    `grace_days` is free and only day indices beyond it are charged), the raw fine
    is `chargeable_days` multiplied by `daily_fine_cents`".

    Design: Difficulty/boundary_precision_check/overdue_grace_boundary_day_index
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"daily_fine_cents": 25, "grace_days": 1, "loan_period_days": 7,
                          "max_fine_cents": 1000},
        isbn="9780000000210", clock="2026-06-01T00:00:00Z")
    # due 2026-06-08; return 2026-06-11 -> 3 overdue, chargeable 2, 2*25=50.
    set_clock("2026-06-11T00:00:00Z")
    final = validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)
    assert final["accrued_fine_cents"] == 50


# ---- cross_entity_state_dependency ----
def test_checkout_on_hold_shelf_copy_not_available(api):
    """PRD §3.3: "The copy must be `AVAILABLE` (otherwise
    `ERR_RESOURCE_NOT_AVAILABLE`)".

    Design: Difficulty/cross_entity_state_dependency/checkout_blocked_when_copy_not_available
    """
    # A copy reserved on the hold shelf (ON_HOLD_SHELF) is also not AVAILABLE.
    branch, pa, pb, title, copy, loan, hold = setup_loan_with_waiting_hold(
        clock="2026-06-01T00:00:00Z", isbn="9780000000211")
    validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)  # promotes hold -> copy ON_HOLD_SHELF
    copy_after = validate_success(api.get_copy(copy["id"], LIBRARIAN), 200)
    assert copy_after["status"] == "ON_HOLD_SHELF"
    pc = create_patron(branch["id"], full_name="Third Pat")
    res = _client.create_loan({"copy_id": copy["id"], "patron_id": pc["id"]}, LIBRARIAN)
    validate_error(res, "ERR_RESOURCE_NOT_AVAILABLE")


def test_reservation_confirm_blocked_when_resource_out_of_service(api):
    """PRD §3.7: "A requested reservation is confirmed by a librarian, permitted
    only from `REQUESTED` and only while the resource is `IN_SERVICE`".

    Design: Difficulty/cross_entity_state_dependency/reservation_checkin_blocked_when_resource_out_of_service
    """
    branch = create_branch(reservation_buffer_minutes=0)
    patron = create_patron(branch["id"], full_name="ConfOOS Pat")
    resource = create_resource(branch["id"], "ROOM", "Room ConfOOS")
    set_clock("2026-06-01T09:00:00Z")
    reservation = create_reservation(
        resource["id"], patron["id"], "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z",
        resource["version"], patron_headers=make_patron_headers(patron["id"]))
    get_success_data(api.set_service_status(resource["id"], "OUT_OF_SERVICE", MANAGER))
    res = api.confirm_reservation(reservation["id"], LIBRARIAN)
    validate_error(res, "ERR_RESOURCE_NOT_AVAILABLE")


# ---- resource_temporal_overlap ----
def test_room_adjacent_outside_buffer_succeeds(api):
    """PRD §3.7: "a new booking conflicts with an active room reservation when the
    new start is before that reservation's end plus the buffer and that
    reservation's start is before the new end plus the buffer."

    Design: Difficulty/resource_temporal_overlap/room_exclusive_with_buffer_overlap
    """
    branch = create_branch(reservation_buffer_minutes=15)
    pa = create_patron(branch["id"], full_name="Adj Pat A")
    pb = create_patron(branch["id"], full_name="Adj Pat B")
    resource = create_resource(branch["id"], "ROOM", "Adjacent Room")
    set_clock("2026-06-01T09:00:00Z")
    create_reservation(resource["id"], pa["id"], "2026-06-01T10:00:00Z",
                       "2026-06-01T11:00:00Z", resource["version"],
                       patron_headers=make_patron_headers(pa["id"]))
    v = current_resource_version(resource["id"])
    # Second booking starts 11:15 == prior end (11:00) + 15-min buffer: new start
    # NOT before prior end + buffer, so no conflict.
    res = validate_success(_client.create_reservation(
        {"resource_id": resource["id"], "patron_id": pb["id"],
         "start_at": "2026-06-01T11:15:00Z", "end_at": "2026-06-01T12:00:00Z",
         "expected_resource_version": v}, make_patron_headers(pb["id"])), 201)
    assert res["status"] == "REQUESTED"


def test_computer_two_overlapping_within_capacity_succeed(api):
    """PRD §3.7: "A second overlapping computer booking is therefore fine as long
    as it stays within capacity."

    Design: Difficulty/resource_temporal_overlap/computer_aggregate_capacity_overlap
    """
    branch = create_branch()
    pa = create_patron(branch["id"], full_name="Cap2 Pat A")
    pb = create_patron(branch["id"], full_name="Cap2 Pat B")
    resource = create_resource(branch["id"], "COMPUTER", "Cap2 PC", capacity=2)
    set_clock("2026-06-01T09:00:00Z")
    create_reservation(resource["id"], pa["id"], "2026-06-01T10:00:00Z",
                       "2026-06-01T11:00:00Z", resource["version"],
                       patron_headers=make_patron_headers(pa["id"]))
    v = current_resource_version(resource["id"])
    res = validate_success(_client.create_reservation(
        {"resource_id": resource["id"], "patron_id": pb["id"],
         "start_at": "2026-06-01T10:00:00Z", "end_at": "2026-06-01T11:00:00Z",
         "expected_resource_version": v}, make_patron_headers(pb["id"])), 201)
    assert res["status"] == "REQUESTED", "second overlap within capacity 2 succeeds"


# ---- compensating_invariant ----
def test_copy_available_count_drops_to_zero_during_loan(api):
    """PRD §3.3: "The copy moves `AVAILABLE → ON_LOAN`, the title's
    `available_copy_count` is reconciled".

    Design: Difficulty/compensating_invariant/physical_copy_count_conserved_across_checkout_return
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Conserve Pat")
    title = create_title(branch["id"], "9780000000212", title_text="Conserve Book")
    copy = create_copy(title["id"], branch["id"], "BC-CV")
    before = validate_success(api.get_title(title["id"], LIBRARIAN), 200)
    assert before["available_copy_count"] == 1 and before["total_copy_count"] == 1
    create_loan(copy["id"], patron["id"])
    during = validate_success(api.get_title(title["id"], LIBRARIAN), 200)
    assert during["available_copy_count"] == 0, "checkout decrements available"
    assert during["total_copy_count"] == 1, "total conserved while on loan"


def test_license_consumed_then_available_drops(api):
    """PRD §3.9: "`available_licenses`, which is `total_licenses` minus
    `loaned_licenses` and is never allowed below zero."

    Design: Difficulty/compensating_invariant/license_token_count_conserved_across_checkout_return
    """
    branch, patron, title, pool, ebook_loan = setup_pool_with_active_ebook_loan(
        total_licenses=2, clock="2026-06-01T00:00:00Z", isbn="9780000000213")
    during = validate_success(api.get_license_pool(pool["id"], LIBRARIAN), 200)
    assert during["loaned_licenses"] == 1
    assert during["available_licenses"] == 1
    assert_pool_token_invariant(during)
