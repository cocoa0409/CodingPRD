"""Entity CRUD, system/computed field behavior, listing/pagination, and RBAC.

Queue B: entities, endpoints, rbac sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_patron_headers, build_user_headers, TEST_USERS, NON_EXISTENT_UUID,
    assert_branch, assert_patron, assert_title,
    create_branch, create_patron, create_title, create_copy, create_loan, set_clock,
)
from test_helpers import api_client as _client  # noqa

LIBRARIAN = TEST_USERS["librarian_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


# =========================================================================
# Queue B — entities
# =========================================================================
def test_create_branch_applies_policy_defaults(api):
    """PRD §3.1: "A branch is the unit of policy, created by a `BranchManager`
    with a display `name` and a set of policy knobs that default if omitted:
    `fine_free` (default false) declares whether the branch assesses any overdue
    money at all; `daily_fine_cents` (default 25) is the per-day overdue charge
    per loan; `max_fine_cents` (default 1000) caps the accrued overdue fine on any
    one loan; `grace_days` (default 1) is the number of whole days past the due
    date that accrue no fine; `loan_period_days` (default 21) is the default loan
    length used to compute and to extend due dates; `block_threshold_cents`
    (default 1000) is the unpaid-balance level at which a patron is blocked from
    new borrowing; and `reservation_buffer_minutes` (default 15) is the cleanup
    gap required between two room bookings on the same resource."

    Design: Corner/entities/create_branch_returns_201_with_policy_defaults
    """
    res = validate_success(_client.create_branch({"name": "Default Branch"}, MANAGER), 201)
    assert_branch(res)
    assert res["fine_free"] is False
    assert res["daily_fine_cents"] == 25
    assert res["grace_days"] == 1
    assert res["loan_period_days"] == 21
    assert res["block_threshold_cents"] == 1000
    assert res["reservation_buffer_minutes"] == 15


def test_create_patron_missing_branch_id_invalid_request(api):
    """PRD §3.1: "Patron cards are registered by a `Librarian` or `BranchManager`
    against a home `branch_id` with a `full_name`".
    PRD §2.10: "Then request well-formedness — required body fields present and
    correctly typed, enum values within their declared domain, and `end_at`
    strictly after `start_at` — yields `ERR_INVALID_REQUEST` on failure
    (priority 4)."

    Design: Corner/entities/create_patron_missing_required_branch_id_returns_invalid_request
    """
    res = _client.create_patron({"full_name": "No Branch"}, LIBRARIAN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_patron_nonexistent_not_found(api):
    """PRD §2.10: "existence of every path- and body-referenced resource is checked
    left-to-right, with any unresolved id yielding `ERR_NOT_FOUND` (priority 3)."

    Design: Corner/entities/get_patron_nonexistent_returns_not_found
    """
    res = api.get_patron(NON_EXISTENT_UUID, LIBRARIAN)
    validate_error(res, "ERR_NOT_FOUND")


def test_patron_system_fields_server_minted(api):
    """PRD §3.1: "A new patron starts with `card_status` of `ACTIVE`,
    `borrowing_status` of `CLEAR`, and every counter at zero."
    PRD §2.4: "an integer `version` that begins at its initial value and increments
    by one on every mutation."

    Design: Corner/entities/patron_system_fields_generated_and_input_ignored
    """
    branch = create_branch(name="SysBr")
    res = validate_success(_client.create_patron(
        {"branch_id": branch["id"], "full_name": "Sys Pat"}, LIBRARIAN), 201)
    assert_patron(res)
    assert res["card_status"] == "ACTIVE"
    assert res["borrowing_status"] == "CLEAR"
    assert res["version"] == 1


def test_create_copy_invalid_title_fk_not_found(api):
    """PRD §2.11: "References are validated left-to-right in the order they appear,
    and the first reference that does not resolve produces `ERR_NOT_FOUND` before
    any later reference or business rule is considered."

    Design: Corner/entities/create_copy_invalid_title_fk_returns_not_found
    """
    branch = create_branch(name="FKBr")
    res = _client.create_copy(
        {"title_id": NON_EXISTENT_UUID, "branch_id": branch["id"],
         "barcode": "BC-NF", "acquired_on": "2025-06-01T00:00:00Z"}, LIBRARIAN)
    validate_error(res, "ERR_NOT_FOUND")


def test_patron_type_invalid_enum_invalid_request(api):
    """PRD §2.10: "Then request well-formedness — required body fields present and
    correctly typed, enum values within their declared domain, and `end_at`
    strictly after `start_at` — yields `ERR_INVALID_REQUEST` on failure
    (priority 4)."
    PRD §3.1: "an optional `patron_type` of `ADULT` (the default), `JUVENILE`, or
    `STAFF`."

    Design: Corner/entities/patron_type_invalid_enum_returns_invalid_request
    """
    branch = create_branch(name="EnumBr")
    res = _client.create_patron(
        {"branch_id": branch["id"], "full_name": "Bad Type", "patron_type": "ROBOT"},
        LIBRARIAN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_title_copy_counts_computed_after_two_copies(api):
    """PRD §2.6: "`available_copy_count` is the number of that title's copies in
    `AVAILABLE` status, `total_copy_count` is the number of that title's copies
    that are not `WITHDRAWN`".

    Design: Corner/entities/title_available_copy_count_computed_after_two_copies
    """
    branch = create_branch(name="CompBr")
    title = create_title(branch["id"], "9781111111111", title_text="Count Book")
    create_copy(title["id"], branch["id"], "BC-K1")
    create_copy(title["id"], branch["id"], "BC-K2")
    res = validate_success(api.get_title(title["id"], LIBRARIAN), 200)
    assert res["available_copy_count"] == 2
    assert res["total_copy_count"] == 2


# =========================================================================
# Queue B — endpoints (listing / pagination)
# =========================================================================
def test_list_copies_filtered_by_title_id(api):
    """PRD §3.2: "Copies are read individually and can be listed filtered by
    `title_id` and/or `branch_id`."
    PRD §2.3: "Every paginated response carries the fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_copies_filtered_by_title_id
    """
    branch = create_branch(name="LCBr")
    ta = create_title(branch["id"], "9780000000028", title_text="LC Book A")
    tb = create_title(branch["id"], "9780000000029", title_text="LC Book B")
    create_copy(ta["id"], branch["id"], "BC-LA1")
    create_copy(ta["id"], branch["id"], "BC-LA2")
    create_copy(tb["id"], branch["id"], "BC-LB1")
    data, meta = validate_paginated(api.list_copies(LIBRARIAN, params={"title_id": ta["id"]}))
    assert all(c["title_id"] == ta["id"] for c in data)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_list_patrons_limit_out_of_range_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`,
    is rejected with `ERR_VALIDATION_PARAM`".

    Design: Corner/endpoints/list_patrons_pagination_limit_out_of_range
    """
    branch = create_branch(name="PgBr")
    res = api.list_patrons(LIBRARIAN, params={"branch_id": branch["id"], "limit": 500})
    validate_error(res, "ERR_VALIDATION_PARAM")


# =========================================================================
# Queue B — rbac
# =========================================================================
def test_unauthenticated_unknown_role_rejected(api):
    """PRD §2.1: "A request that omits either header, or that carries an
    `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_unknown_role_returns_401
    """
    res = api.list_branches(build_user_headers("ghost-1", "Ghost"))
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_patron_cannot_create_branch_forbidden(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted to perform
    the requested operation — or a `Patron` attempting to act on a resource they do
    not own — is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/patron_cannot_create_branch_returns_forbidden
    """
    branch = create_branch(name="RbacBr")
    patron = create_patron(branch["id"], full_name="Rbac Pat")
    res = _client.create_branch({"name": "Sneaky Branch"}, make_patron_headers(patron["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_patron_cannot_cancel_another_patrons_hold_forbidden(api):
    """PRD §2.1: "a `Patron` may renew, cancel, return, or otherwise act on a
    `Loan`, `Hold`, `Reservation`, or `EbookLoan` only when that resource's
    `patron_id` equals `X-User-ID`; an attempt against another patron's resource
    yields `ERR_FORBIDDEN`."

    Design: Corner/rbac/patron_cannot_cancel_another_patrons_hold_returns_forbidden
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    pa = create_patron(branch["id"], full_name="Own Pat A")
    pb = create_patron(branch["id"], full_name="Own Pat B")
    title = create_title(branch["id"], "9780000000030", title_text="Own Book")
    copy = create_copy(title["id"], branch["id"], "BC-OW")
    create_loan(copy["id"], pa["id"])  # copy ON_LOAN so pb's hold stays WAITING
    hold = get_success_data(_client.create_hold(
        {"title_id": title["id"], "patron_id": pb["id"]}, make_patron_headers(pb["id"])))
    # Patron A tries to cancel patron B's hold.
    res = api.cancel_hold(hold["id"], make_patron_headers(pa["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_librarian_cannot_waive_fine_forbidden(api):
    """PRD §3.10: "A waiver is the manager-only counterpart: only a `BranchManager`
    may waive an `UNPAID` fine".

    Design: Corner/rbac/librarian_cannot_waive_fine_returns_forbidden
    """
    branch = create_branch(loan_period_days=7, block_threshold_cents=100000)
    set_clock("2026-06-01T00:00:00Z")
    patron = create_patron(branch["id"], full_name="Wa Pat")
    title = create_title(branch["id"], "9780000000031", title_text="Wa Book",
                         default_replacement_cents=1500)
    copy = create_copy(title["id"], branch["id"], "BC-WA",
                       acquired_on="2026-06-01T00:00:00Z", condition_factor=1.0)
    loan = create_loan(copy["id"], patron["id"])
    get_success_data(_client.declare_lost(loan["id"], LIBRARIAN, {"flat_replacement": True}))
    fines = get_success_data(api.list_fines(LIBRARIAN, params={
        "patron_id": patron["id"], "settlement_status": "UNPAID"}))
    fine_id = (fines if isinstance(fines, list) else fines)[0]["id"]
    res = api.waive_fine(fine_id, LIBRARIAN)
    validate_error(res, "ERR_FORBIDDEN")
