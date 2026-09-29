"""A division order and a suspense release each blocked by a neighbour's state."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_acreage, assert_decimal_interest, assert_money
from test_helpers.test_users import (
    ADMIN_ALT_HEADERS,
    ADMIN_HEADERS,
    ADMIN_USER_ID_ALT,
)


def _interest_and_unit(api):
    """Certified tract, PROSPECT interest on it, unit holding one ACTIVE allocation."""
    tract = fx.create_certified_tract(api)
    owner = fx.create_owner(api)
    interest = fx.create_interest(api, tract["id"], owner["id"])
    unit = fx.create_unit(api)
    allocation = fx.create_allocation(api, unit["id"], tract["id"])
    return {
        "tract": tract,
        "owner": owner,
        "interest": interest,
        "unit": unit,
        "allocation": allocation,
    }


def test_terminated_allocation_still_covering_the_clock_blocks_the_order(api):
    """The selector reaches a TERMINATED row and reports its posture, not absence.

    PRD: "if the selected candidate's `allocation_status` is `TERMINATED` rather
    than `ACTIVE` or `PUGH_RELEASED`, the request is `ERR_ALLOCATION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/division_order_creation_blocked_by_terminated_unit_tract_allocation
    """
    world = _interest_and_unit(api)
    fx.terminate_allocation(api, world["allocation"]["id"])

    version = fx.unit_version(api, world["unit"]["id"])
    response = api.create_division_order(
        f.division_order_payload(world["interest"]["id"], world["unit"]["id"], version),
        ADMIN_HEADERS,
    )

    validate_error(response, "ERR_ALLOCATION_NOT_ACTIVE", 409)


def test_reallocating_the_identical_interval_after_termination_is_legal(api):
    """A TERMINATED row is not in the overlap set, so the same span reopens.

    PRD: "The new interval must not overlap the interval of any existing
    allocation on the same unit-and-tract pairing whose `allocation_status` is
    `ACTIVE` or `PUGH_RELEASED`; an overlap is `ERR_ALLOCATION_INTERVAL_OVERLAP`."

    Design: Difficulty/cross_entity_state_dependency/division_order_creation_blocked_by_terminated_unit_tract_allocation
    """
    world = _interest_and_unit(api)
    fx.terminate_allocation(api, world["allocation"]["id"])

    replacement = fx.create_allocation(api, world["unit"]["id"], world["tract"]["id"])

    assert replacement["allocation_status"] == "ACTIVE"
    assert replacement["effective_from"] == "2026-01-01"
    assert replacement["effective_to"] == "2028-01-01"
    unit = fx.read_unit(api, world["unit"]["id"])
    assert unit["active_allocation_count"] == 1
    assert_acreage(unit["unallocated_acres"], "960.0000", "unallocated_acres")


def test_order_issued_after_reallocation_points_at_the_live_row(api):
    """The replacement allocation is the one the decimal is built from.

    PRD: "The first candidate wins, and its identifier is stored on the order as
    `allocation_id`; that stored pointer is a convenience, since the authoritative
    link is the allocation's own `unit_id` and `tract_id` pairing, and it is
    recomputed on every correction."

    Design: Difficulty/cross_entity_state_dependency/division_order_creation_blocked_by_terminated_unit_tract_allocation
    """
    world = _interest_and_unit(api)
    fx.terminate_allocation(api, world["allocation"]["id"])
    replacement = fx.create_allocation(api, world["unit"]["id"], world["tract"]["id"])

    order = fx.create_division_order(api, world["interest"]["id"], world["unit"]["id"])

    assert order["allocation_id"] == replacement["id"]
    assert order["allocation_id"] != world["allocation"]["id"]
    assert_decimal_interest(order["expected_decimal"], "0.00195313", "expected_decimal")
    assert order["do_status"] == "SENT"


def test_release_to_an_unlocatable_payee_is_refused(api):
    """The owner turns UNLOCATABLE between the hold and the release attempt.

    PRD: "The payee of record's `contact_status` must be `LOCATED`, or the request
    is `ERR_OWNER_UNLOCATABLE`."

    Design: Difficulty/cross_entity_state_dependency/suspense_release_blocked_by_unlocatable_royalty_owner
    """
    world = fx.variance_held_ready(api)
    fx.patch_owner(api, world["owner"]["id"], {"contact_status": "UNLOCATABLE"})

    response = api.release_suspense(world["suspense"]["id"], ADMIN_ALT_HEADERS)

    validate_error(response, "ERR_OWNER_UNLOCATABLE", 409)


def test_refused_release_leaves_the_account_untouched(api):
    """Nothing is disbursed and nothing is stamped on the way out.

    PRD: "On success `months_held`, `interest_accrued` and `release_amount` are
    recomputed against the logical clock, `suspense_status` moves
    `ACCRUING → RELEASED`, `released_by_user_id` is stamped from the acting
    `X-User-ID`, and `accrued_amount` and `held_detail_count` are zeroed to 0.00
    and 0."

    Design: Difficulty/cross_entity_state_dependency/suspense_release_blocked_by_unlocatable_royalty_owner
    """
    world = fx.variance_held_ready(api)
    fx.patch_owner(api, world["owner"]["id"], {"contact_status": "UNLOCATABLE"})

    api.release_suspense(world["suspense"]["id"], ADMIN_ALT_HEADERS)

    account = fx.read_suspense(api, world["suspense"]["id"])
    assert account["suspense_status"] == "ACCRUING"
    assert account["released_by_user_id"] is None
    assert_money(account["accrued_amount"], "106.47", "accrued_amount")
    assert account["held_detail_count"] == 1
    assert fx.read_division_order(api, world["order"]["id"])["do_status"] == "SUSPENDED"


def test_relocating_the_owner_reopens_the_release(api):
    """With the payee LOCATED again the same call disburses and re-opens the order.

    PRD: "The cascade then reaches the parent order: every one of its revenue lines
    whose `check_status` was `VARIANCE_HELD` becomes `PAID`, the order's
    `paid_net_total` becomes its previous value plus the released `accrued_amount`
    rounded to cents, its `cumulative_variance_amount` resets to 0.00, and its
    `do_status` returns `SUSPENDED → EXECUTED` so the revenue channel re-opens."

    Design: Difficulty/cross_entity_state_dependency/suspense_release_blocked_by_unlocatable_royalty_owner
    """
    world = fx.variance_held_ready(api)
    fx.patch_owner(api, world["owner"]["id"], {"contact_status": "UNLOCATABLE"})
    api.release_suspense(world["suspense"]["id"], ADMIN_ALT_HEADERS)
    fx.patch_owner(api, world["owner"]["id"], {"contact_status": "LOCATED"})

    released = validate_success(
        api.release_suspense(world["suspense"]["id"], ADMIN_ALT_HEADERS), 200
    )

    assert released["suspense_status"] == "RELEASED"
    assert released["released_by_user_id"] == ADMIN_USER_ID_ALT
    assert_money(released["accrued_amount"], "0.00", "accrued_amount")
    assert fx.read_division_order(api, world["order"]["id"])["do_status"] == "EXECUTED"
