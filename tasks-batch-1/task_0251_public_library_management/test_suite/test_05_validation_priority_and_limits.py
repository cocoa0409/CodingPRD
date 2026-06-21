"""Validation priority ordering, borrowing limits, and license-pool boundary.

Queue A: priority_pair_validation_conflict, boundary_precision_check (empty pool).
Queue B: validations section (title withdrawn, suspended card, renewal blocks,
limits).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_patron_headers, TEST_USERS,
    setup_blocked_patron_via_lost, setup_pool_with_active_ebook_loan,
    create_branch, create_patron, create_title, create_copy, create_loan,
    create_resource, create_reservation, current_resource_version, set_clock,
)
from test_helpers import api_client as _client  # noqa

LIBRARIAN = TEST_USERS["librarian_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


# =========================================================================
# Queue A — priority_pair_validation_conflict
# =========================================================================
def test_checkout_resource_unavailable_beats_limit(api):
    """PRD §2.10: "cross-entity reference availability yields
    `ERR_RESOURCE_NOT_AVAILABLE` (priority 6); patron card status yields
    `ERR_CARD_NOT_ACTIVE` (priority 7); patron fine-block yields
    `ERR_PATRON_BLOCKED` (priority 8); reservation interval conflict yields
    `ERR_RESERVATION_CONFLICT` (priority 9); patron limit checks yield
    `ERR_LIMIT_EXCEEDED` (priority 10)".
    PRD §3.3: "The copy must be `AVAILABLE` (otherwise `ERR_RESOURCE_NOT_AVAILABLE`)".

    Design: Difficulty/priority_pair_validation_conflict/checkout_state_beats_business_constraint
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    p = create_patron(branch["id"], full_name="Limit Pat", checkout_limit=1)
    p2 = create_patron(branch["id"], full_name="Other Pat")
    title = create_title(branch["id"], "9780000000009", title_text="Conf Book")
    c1 = create_copy(title["id"], branch["id"], "BC-X1")
    c2 = create_copy(title["id"], branch["id"], "BC-X2")
    create_loan(c1["id"], p["id"])   # p now at checkout_limit 1
    create_loan(c2["id"], p2["id"])  # c2 now ON_LOAN (not AVAILABLE)
    # p checking out c2 violates BOTH priority-6 (copy not available) and
    # priority-10 (limit). Higher priority wins.
    res = _client.create_loan({"copy_id": c2["id"], "patron_id": p["id"]}, LIBRARIAN)
    validate_error(res, "ERR_RESOURCE_NOT_AVAILABLE")


def test_reservation_patron_blocked_beats_conflict(api):
    """PRD §2.10: "patron fine-block yields `ERR_PATRON_BLOCKED` (priority 8);
    reservation interval conflict yields `ERR_RESERVATION_CONFLICT` (priority 9)".

    Design: Difficulty/priority_pair_validation_conflict/reservation_temporal_beats_fiscal_block_pair
    """
    # Blocked patron (2200c lost fine, threshold 1000) on a branch with no buffer.
    branch, blocked_patron, title, copy, loan = setup_blocked_patron_via_lost(
        block_threshold_cents=1000, default_replacement_cents=2000,
        clock="2026-06-01T00:00:00Z", isbn="9780000000010")
    # Confirm the patron is blocked at 2200 (flat 2000 + processing 200).
    bp = validate_success(api.get_patron(blocked_patron["id"], LIBRARIAN), 200)
    assert bp["total_owed_cents"] == 2200 and bp["borrowing_status"] == "BLOCKED"

    holder = create_patron(branch["id"], full_name="Holder Pat")
    resource = create_resource(branch["id"], "ROOM", "Room Z")
    # An existing CONFIRMED-equivalent active booking 10:00-11:00 by the holder.
    create_reservation(resource["id"], holder["id"], "2026-06-01T10:00:00Z",
                       "2026-06-01T11:00:00Z", resource["version"],
                       patron_headers=make_patron_headers(holder["id"]))
    v = current_resource_version(resource["id"])
    # Blocked patron books an overlapping window 10:30-11:30: violates BOTH
    # priority-8 (blocked) and priority-9 (conflict). Higher priority wins.
    res = _client.create_reservation(
        {"resource_id": resource["id"], "patron_id": blocked_patron["id"],
         "start_at": "2026-06-01T10:30:00Z", "end_at": "2026-06-01T11:30:00Z",
         "expected_resource_version": v}, make_patron_headers(blocked_patron["id"]))
    validate_error(res, "ERR_PATRON_BLOCKED")


# =========================================================================
# Queue A — boundary_precision_check (empty license pool)
# =========================================================================
def test_ebook_checkout_at_zero_licenses_rejected(api):
    """PRD §3.9: "the pool must have at least one available license —
    `available_licenses` of at least one — or the checkout is rejected with
    `ERR_NO_LICENSE_AVAILABLE`."

    Design: Difficulty/boundary_precision_check/ebook_checkout_empty_pool_boundary
    """
    # total_licenses=1, one ACTIVE ebook loan already consumes it -> available 0.
    branch, patron_a, title, pool, ebook_loan = setup_pool_with_active_ebook_loan(
        total_licenses=1, clock="2026-06-01T00:00:00Z", isbn="9780000000012")
    pool_after = validate_success(api.get_license_pool(pool["id"], LIBRARIAN), 200)
    assert pool_after["available_licenses"] == 0

    patron_b = create_patron(branch["id"], full_name="Ebook Pat B")
    res = _client.create_ebook_loan(
        {"pool_id": pool["id"], "patron_id": patron_b["id"]},
        make_patron_headers(patron_b["id"]))
    validate_error(res, "ERR_NO_LICENSE_AVAILABLE")


def test_ebook_checkout_at_one_license_succeeds(api):
    """PRD §3.9: "the pool must have at least one available license —
    `available_licenses` of at least one — or the checkout is rejected with
    `ERR_NO_LICENSE_AVAILABLE`."
    PRD §3.9: "On success an `EbookLoan` is created in `ACTIVE` status".

    Design: Difficulty/boundary_precision_check/ebook_checkout_empty_pool_boundary
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Ebook One Pat")
    title = create_title(branch["id"], "9780000000099", title_text="One License")
    pool = get_success_data(_client.create_license_pool(
        {"title_id": title["id"], "total_licenses": 1, "loan_term_days": 14}, LIBRARIAN))
    # available_licenses == 1 permits checkout (boundary X-side).
    res = validate_success(_client.create_ebook_loan(
        {"pool_id": pool["id"], "patron_id": patron["id"]},
        make_patron_headers(patron["id"])), 201)
    assert res["status"] == "ACTIVE"


# =========================================================================
# Queue B — validations section
# =========================================================================
def test_title_withdrawn_blocks_new_copy(api):
    """PRD §2.6: "New copies and new holds may not be created against a
    `WITHDRAWN` title; such attempts are rejected with `ERR_TITLE_WITHDRAWN`."

    Design: Corner/validations/title_withdrawn_blocks_new_copy
    """
    branch = create_branch()
    title = create_title(branch["id"], "9780000000022", title_text="Wd Book")
    validate_success(api.withdraw_title(title["id"], MANAGER), 200)
    res = _client.create_copy(
        {"title_id": title["id"], "branch_id": branch["id"], "barcode": "BC-WD",
         "acquired_on": "2025-06-01T00:00:00Z"}, LIBRARIAN)
    validate_error(res, "ERR_TITLE_WITHDRAWN")


def test_suspended_card_blocks_checkout(api):
    """PRD §2.8: "only an `ACTIVE` card may check out a physical item, place a hold,
    book a room or computer, check out an e-book, or submit an ILL request, and a
    `SUSPENDED` or `EXPIRED` card is rejected with `ERR_CARD_NOT_ACTIVE`."

    Design: Corner/validations/suspended_card_blocks_checkout
    """
    branch = create_branch(loan_period_days=7)
    patron = create_patron(branch["id"], full_name="Susp Pat")
    get_success_data(api.set_card_status(patron["id"], "SUSPENDED", LIBRARIAN))
    title = create_title(branch["id"], "9780000000023", title_text="Susp Book")
    copy = create_copy(title["id"], branch["id"], "BC-SU")
    res = _client.create_loan({"copy_id": copy["id"], "patron_id": patron["id"]}, LIBRARIAN)
    validate_error(res, "ERR_CARD_NOT_ACTIVE")


def test_renew_blocked_by_outstanding_hold(api):
    """PRD §3.3: "no `WAITING` or `READY` hold may exist on the title of the loan's
    copy, because outstanding hold demand takes precedence over an incumbent
    borrower — if such a hold exists the renewal is refused with
    `ERR_RENEWAL_BLOCKED_BY_HOLD`."

    Design: Corner/validations/renew_blocked_by_outstanding_hold
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    pa = create_patron(branch["id"], full_name="RBH Pat A")
    pb = create_patron(branch["id"], full_name="RBH Pat B")
    title = create_title(branch["id"], "9780000000024", title_text="RBH Book")
    copy = create_copy(title["id"], branch["id"], "BC-RB")
    loan = create_loan(copy["id"], pa["id"])
    get_success_data(_client.create_hold(
        {"title_id": title["id"], "patron_id": pb["id"]}, make_patron_headers(pb["id"])))
    res = api.renew_loan(loan["id"], make_patron_headers(pa["id"]))
    validate_error(res, "ERR_RENEWAL_BLOCKED_BY_HOLD")
    after = validate_success(api.get_loan(loan["id"], LIBRARIAN), 200)
    assert after["renewal_count"] == 0


def test_renew_at_max_renewals_rejected(api):
    """PRD §3.3: "the loan's `renewal_count` must be below the maximum of two
    renewals, or the request is rejected with `ERR_RENEWAL_LIMIT`".

    Design: Corner/validations/renew_at_max_renewals_returns_renewal_limit
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Max Pat")
    title = create_title(branch["id"], "9780000000025", title_text="Max Book")
    copy = create_copy(title["id"], branch["id"], "BC-MX")
    loan = create_loan(copy["id"], patron["id"])
    ph = make_patron_headers(patron["id"])
    validate_success(api.renew_loan(loan["id"], ph), 200)
    validate_success(api.renew_loan(loan["id"], ph), 200)
    res = api.renew_loan(loan["id"], ph)  # third renewal, renewal_count == 2
    validate_error(res, "ERR_RENEWAL_LIMIT")
    after = validate_success(api.get_loan(loan["id"], LIBRARIAN), 200)
    assert after["renewal_count"] == 2


def test_hold_limit_exceeded_rejected(api):
    """PRD §3.6: "the patron's open-hold count — holds in `WAITING` or `READY`
    status — must be below their `hold_limit`, or the placement is rejected with
    `ERR_LIMIT_EXCEEDED`."

    Design: Corner/validations/hold_limit_exceeded_returns_limit_exceeded
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    p = create_patron(branch["id"], full_name="HL Pat", hold_limit=1)
    owner = create_patron(branch["id"], full_name="HL Owner")
    t1 = create_title(branch["id"], "9780000000026", title_text="HL Book 1")
    t2 = create_title(branch["id"], "9780000000027", title_text="HL Book 2")
    c1 = create_copy(t1["id"], branch["id"], "BC-H1")
    c2 = create_copy(t2["id"], branch["id"], "BC-H2")
    create_loan(c1["id"], owner["id"])  # t1's only copy ON_LOAN
    create_loan(c2["id"], owner["id"])  # t2's only copy ON_LOAN
    ph = make_patron_headers(p["id"])
    get_success_data(_client.create_hold({"title_id": t1["id"], "patron_id": p["id"]}, ph))
    res = _client.create_hold({"title_id": t2["id"], "patron_id": p["id"]}, ph)
    validate_error(res, "ERR_LIMIT_EXCEEDED")
