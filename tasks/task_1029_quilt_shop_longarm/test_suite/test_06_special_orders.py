"""Special orders and the re-quote loop: the cyclic QUOTED->QUOTED revision (recompute +
version bump), the optimistic-concurrency stale-version guard, and Member ownership on
creation."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_member, create_special_order, revise_order,
    make_member_headers, ApiErrorId, TEST_USERS,
)
from test_helpers import factories as f

CLERK = TEST_USERS["clerk_headers"]


# =========================================================================
# Difficulty/non_linear_state_machine/special_order_requote_cycle
# =========================================================================
def test_requote_stays_quoted_and_recomputes_price_and_version(api):
    """PRD §3.6: "A successful re-quote replaces the stored est_unit_cost and quantity,
    recomputes quoted_price under the estimate variant, and increments the order's version by
    one". A QUOTED order (est 10.00 x qty 2 => quoted 30.00, version 1) re-quoted to est 20.00
    x qty 2 stays QUOTED with quoted_price 60.00 and version 2.

    Design: Difficulty/non_linear_state_machine/special_order_requote_cycle
    """
    order, _ = create_special_order(api, quantity=2, est_unit_cost=10.00, description="Bobbins")
    assert order["quoted_price"] == 30.00 and order["version"] == 1
    revised = revise_order(api, order["id"], est_unit_cost=20.00, quantity=2,
                           expected_version=order["version"])
    assert revised["status"] == "QUOTED"
    assert revised["quoted_price"] == 60.00, f"expected 60.00, got {revised['quoted_price']}"
    assert revised["version"] == 2, f"expected version 2, got {revised['version']}"


def test_requote_advances_version_each_accepted_round(api):
    """PRD §3.6: "increments the order's version by one — so each accepted revision advances
    the version the next re-quote must present." Two successive accepted re-quotes, each
    carrying the version the previous round produced, move the order from version 1 to 2 to 3
    while it stays QUOTED.

    Design: Difficulty/non_linear_state_machine/special_order_requote_cycle
    """
    order, _ = create_special_order(api, quantity=2, est_unit_cost=10.00, description="Bobbins")
    r1 = revise_order(api, order["id"], est_unit_cost=15.00, quantity=2, expected_version=1)
    assert r1["version"] == 2
    r2 = revise_order(api, order["id"], est_unit_cost=20.00, quantity=2, expected_version=r1["version"])
    assert r2["version"] == 3, f"expected version 3, got {r2['version']}"
    assert r2["status"] == "QUOTED"


# =========================================================================
# Corner/cross_cutting/special_order_revise_stale_version_returns_412
# =========================================================================
def test_requote_with_stale_version_rejected(api):
    """PRD §2.7: "a request whose expected_special_order_version does not equal the order's
    current version means another revision has already moved the order forward since the
    client read it; such a request is rejected with ERR_STALE_VERSION (HTTP 412)." After one
    accepted revise advances the order from version 1 to 2, a second revise still carrying
    expected_special_order_version 1 is stale and rejected.

    Design: Corner/cross_cutting/special_order_revise_stale_version_returns_412
    """
    order, _ = create_special_order(api, quantity=1, est_unit_cost=10.00, description="Needle set")
    revise_order(api, order["id"], est_unit_cost=12.00, quantity=1, expected_version=1)
    resp = api.revise_special_order(
        order["id"],
        {"est_unit_cost": 14.00, "quantity": 1, "expected_special_order_version": 1},
        CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# =========================================================================
# Corner/rbac/member_cannot_create_special_order_for_another_member
# =========================================================================
def test_member_cannot_open_special_order_for_another_member(api):
    """PRD §2.1: "when a Member creates or acts on a longarm job, an enrollment, or a special
    order, the member_id recorded on (or referenced by) that resource must equal the caller's
    X-User-ID; a mismatch is rejected with ERR_NOT_RESOURCE_OWNER." A Member acting as m1 who
    creates a special order for m2 is rejected.

    Design: Corner/rbac/member_cannot_create_special_order_for_another_member
    """
    m1 = create_member(api)
    m2 = create_member(api)
    resp = api.create_special_order(
        f.create_special_order_payload(m2["id"], description="Not mine", quantity=1, est_unit_cost=10.00),
        make_member_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
