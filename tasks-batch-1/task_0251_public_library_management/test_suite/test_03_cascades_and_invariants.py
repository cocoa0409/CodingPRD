"""Cross-aggregate cascades and conserved-quantity invariants.

Queue A: transitive_cascade, compensating_invariant. Queue B: hold queue
position, ebook-expiry derived field, immediate consistency.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    make_patron_headers, TEST_USERS,
    setup_active_loan, setup_loan_with_waiting_hold,
    setup_pool_with_active_ebook_loan, assert_pool_token_invariant,
    get_only_unpaid_fine, create_branch, create_patron, create_title,
    create_copy, create_loan, create_license_pool, set_clock,
)
from test_helpers import api_client as _client  # noqa

LIBRARIAN = TEST_USERS["librarian_headers"]


# =========================================================================
# Queue A — transitive_cascade
# =========================================================================
def test_declare_lost_cascades_to_patron_block(api):
    """PRD §3.5: "Declaring lost triggers a deep cascade: the loan moves to `LOST`,
    the copy moves to `LOST`, a replacement `Fine` is created, the patron's balance
    is recomputed, and if that balance now reaches or exceeds the branch's
    `block_threshold_cents` the patron's `borrowing_status` flips to `BLOCKED`."

    Design: Difficulty/transitive_cascade/declare_lost_cascade_to_patron_block_depth4
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"loan_period_days": 7, "block_threshold_cents": 1000},
        isbn="9780000000007",
        title_overrides={"default_replacement_cents": 3000},
        copy_overrides={"acquired_on": "2026-06-01T00:00:00Z", "condition_factor": 1.0},
        clock="2026-06-01T00:00:00Z")
    validate_success(api.declare_lost(loan["id"], LIBRARIAN, {"flat_replacement": True}), 200)

    copy_after = validate_success(api.get_copy(copy["id"], LIBRARIAN), 200)
    assert copy_after["status"] == "LOST"

    fine = get_only_unpaid_fine(patron["id"])
    assert fine["fine_type"] == "LOST"
    assert fine["amount_cents"] == 3300, "flat 3000 + processing 300"

    patron_after = validate_success(api.get_patron(patron["id"], LIBRARIAN), 200)
    assert patron_after["total_owed_cents"] == 3300
    assert patron_after["borrowing_status"] == "BLOCKED", "3300 >= 1000"


def test_checkin_return_promotes_head_hold(api):
    """PRD §3.4: "If any `WAITING` hold exists on the returned copy's title, the
    head hold — the one with the lowest `queue_position`, which is to say the
    earliest by `created_at` — is promoted `WAITING → READY`: the just-freed copy
    is reserved on the hold shelf (its status goes `AVAILABLE → ON_HOLD_SHELF`),
    the hold's `ready_copy_id` is set to that copy, `ready_at` is set to the clock,
    the hold's `pickup_deadline` is set, and the promoted patron's
    `ready_pickup_count` is reconciled."

    Design: Difficulty/transitive_cascade/checkin_return_promotes_head_hold_depth3
    """
    branch, pa, pb, title, copy, loan, hold = setup_loan_with_waiting_hold(
        clock="2026-06-01T00:00:00Z", isbn="9780000000008")
    validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)

    hold_after = validate_success(api.get_hold(hold["id"], LIBRARIAN), 200)
    assert hold_after["status"] == "READY"
    assert hold_after["ready_copy_id"] == copy["id"]

    copy_after = validate_success(api.get_copy(copy["id"], LIBRARIAN), 200)
    assert copy_after["status"] == "ON_HOLD_SHELF"

    pb_after = validate_success(api.get_patron(pb["id"], LIBRARIAN), 200)
    assert pb_after["ready_pickup_count"] == 1


# =========================================================================
# Queue A — compensating_invariant
# =========================================================================
def test_physical_copy_count_conserved_across_checkout_return(api):
    """PRD §2.6: "`available_copy_count` is the number of that title's copies in
    `AVAILABLE` status, `total_copy_count` is the number of that title's copies
    that are not `WITHDRAWN`".
    PRD §3.4: "the copy moves `ON_LOAN → AVAILABLE` and the title's
    `available_copy_count` is reconciled."

    Design: Difficulty/compensating_invariant/physical_copy_count_conserved_across_checkout_return
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"loan_period_days": 7}, isbn="9780000000014",
        clock="2026-06-01T00:00:00Z")
    during = validate_success(api.get_title(title["id"], LIBRARIAN), 200)
    assert during["available_copy_count"] == 0 and during["total_copy_count"] == 1

    validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)
    after = validate_success(api.get_title(title["id"], LIBRARIAN), 200)
    assert after["available_copy_count"] == 1, "available restored"
    assert after["total_copy_count"] == 1, "total conserved at 1"


def test_license_token_count_conserved_across_checkout_return(api):
    """PRD §3.9: "The pool tracks two derived figures: `loaned_licenses`, the
    number of its e-book loans currently `ACTIVE`, and `available_licenses`, which
    is `total_licenses` minus `loaned_licenses` and is never allowed below zero."
    PRD §3.9: "moving the loan `ACTIVE → RETURNED` and releasing the license back
    to the pool (both pool counters reconciled, the conserved token returned)".

    Design: Difficulty/compensating_invariant/license_token_count_conserved_across_checkout_return
    """
    branch, patron, title, pool, ebook_loan = setup_pool_with_active_ebook_loan(
        total_licenses=3, clock="2026-06-01T00:00:00Z", isbn="9780000000015")
    during = validate_success(api.get_license_pool(pool["id"], LIBRARIAN), 200)
    assert during["loaned_licenses"] == 1 and during["available_licenses"] == 2
    assert_pool_token_invariant(during)

    validate_success(api.return_ebook_loan(ebook_loan["id"], make_patron_headers(patron["id"])), 200)
    after = validate_success(api.get_license_pool(pool["id"], LIBRARIAN), 200)
    assert after["loaned_licenses"] == 0 and after["available_licenses"] == 3
    assert_pool_token_invariant(after)


# =========================================================================
# Queue B — derived-field / queue / consistency corners
# =========================================================================
def test_hold_queue_position_ordered_by_created_at(api):
    """PRD §3.6: "The `queue_position` is a 1-based rank among the `WAITING` holds
    on the title, ordered by `created_at` ascending with the tie-break always on
    `created_at` and never on `id`".

    Design: Corner/calculations/hold_queue_position_ordered_by_created_at
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    pa = create_patron(branch["id"], full_name="Q Pat A")
    pb = create_patron(branch["id"], full_name="Q Pat B")
    pc = create_patron(branch["id"], full_name="Q Pat C")
    title = create_title(branch["id"], "9780000000021", title_text="Q Book")
    copy = create_copy(title["id"], branch["id"], "BC-Q")
    create_loan(copy["id"], pa["id"])  # only copy ON_LOAN
    hb = get_success_data(_client.create_hold(
        {"title_id": title["id"], "patron_id": pb["id"]}, make_patron_headers(pb["id"])))
    hc = get_success_data(_client.create_hold(
        {"title_id": title["id"], "patron_id": pc["id"]}, make_patron_headers(pc["id"])))

    hb_after = validate_success(api.get_hold(hb["id"], LIBRARIAN), 200)
    hc_after = validate_success(api.get_hold(hc["id"], LIBRARIAN), 200)
    assert hb_after["queue_position"] == 1, "earlier created_at is position 1"
    assert hc_after["queue_position"] == 2


def test_ebook_expiry_releases_license_derived_field(api):
    """PRD §3.9: "a librarian runs the pool's expiry sweep, and every `ACTIVE`
    e-book loan on that pool whose `expires_at` is at or before the current clock
    is moved `ACTIVE → EXPIRED`, releasing its license; the pool's
    `loaned_licenses` and `available_licenses` are reconciled afterward."

    Design: Corner/cross_cutting_complexity_layers/ebook_expiry_releases_license_derived_field
    """
    branch, patron, title, pool, ebook_loan = setup_pool_with_active_ebook_loan(
        total_licenses=2, clock="2026-06-01T00:00:00Z", isbn="9780000000032",
        loan_term_days=14)
    # expires_at = 2026-06-15; advance past it.
    set_clock("2026-06-20T00:00:00Z")
    pool_after = validate_success(api.run_expiry(pool["id"], LIBRARIAN), 200)
    assert pool_after["loaned_licenses"] == 0
    assert pool_after["available_licenses"] == 2
    assert_pool_token_invariant(pool_after)

    el_after = validate_success(api.get_ebook_loan(ebook_loan["id"], LIBRARIAN), 200)
    assert el_after["status"] == "EXPIRED"


def test_checkout_side_effects_immediately_visible(api):
    """PRD §3.3: "The copy moves `AVAILABLE → ON_LOAN`, the title's
    `available_copy_count` is reconciled, and the patron's `active_loan_count` is
    reconciled."

    Design: Corner/consistency_model/checkout_side_effects_visible_in_same_response_immediate
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Imm Pat")
    title = create_title(branch["id"], "9780000000033", title_text="Imm Book")
    copy = create_copy(title["id"], branch["id"], "BC-IM")
    create_loan(copy["id"], patron["id"])

    copy_after = validate_success(api.get_copy(copy["id"], LIBRARIAN), 200)
    assert copy_after["status"] == "ON_LOAN"
    title_after = validate_success(api.get_title(title["id"], LIBRARIAN), 200)
    assert title_after["available_copy_count"] == 0
