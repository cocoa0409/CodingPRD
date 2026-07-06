"""Optimistic-concurrency on reservation create, and Manager hierarchical override."""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_customer,
    create_series,
    create_issue,
    create_reservation_payload,
    create_checkout_payload,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Queue B — cross_cutting: OCC correct version succeeds and bumps
# ---------------------------------------------------------------------------
def test_reservation_correct_version_succeeds_and_bumps(api, clerk_headers):
    """PRD §3.2: "creating it raises the issue's `copies_reserved` by `requested_qty` and increments the issue's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/reservation_create_correct_version_succeeds_and_bumps
    """
    cust = create_customer()
    series = create_series()
    issue = create_issue(series["id"], copies_ordered=5)
    v0 = issue["version"]
    res = validate_success(
        api.create_reservation(
            create_reservation_payload(cust["id"], issue["id"], v0, requested_qty=1),
            clerk_headers,
        ),
        201,
    )
    assert res["status"] == "RESERVED"
    issue_after = validate_success(api.get_comic_issue(issue["id"], clerk_headers), 200)
    assert issue_after["version"] == v0 + 1
    assert issue_after["copies_reserved"] == 1


# ---------------------------------------------------------------------------
# Queue B — cross_cutting: OCC stale version conflict
# ---------------------------------------------------------------------------
def test_reservation_stale_version_conflict(api, clerk_headers):
    """PRD §2.6: "If `expected_comic_issue_version` does not equal the issue's
    current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/reservation_create_stale_version_conflict
    """
    c1 = create_customer()
    c2 = create_customer()
    series = create_series()
    issue = create_issue(series["id"], copies_ordered=5)
    stale_v = issue["version"]
    # First create against the fresh version succeeds and advances the issue.
    validate_success(
        api.create_reservation(
            create_reservation_payload(c1["id"], issue["id"], stale_v, requested_qty=1),
            clerk_headers,
        ),
        201,
    )
    # Second create still carries the pre-first-create version -> stale.
    res = api.create_reservation(
        create_reservation_payload(c2["id"], issue["id"], stale_v, requested_qty=1),
        clerk_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


# ---------------------------------------------------------------------------
# Queue B — rbac: Manager can perform Clerk checkout (hierarchical override)
# ---------------------------------------------------------------------------
def test_manager_can_perform_clerk_checkout(api, manager_headers):
    """PRD §2.1: "A `Manager` is a hierarchical superset of `Clerk` — every operation a `Clerk` may perform, a `Manager` may also perform"

    Design: Corner/rbac/manager_can_perform_clerk_checkout
    """
    cust = validate_success(
        api.create_customer({"email": "mgr-co@x.com", "full_name": "Mgr"}, manager_headers), 201
    )
    resp = validate_success(
        api.checkout(
            create_checkout_payload(cust["id"], [{"unit_price_cents": 2000, "quantity": 1}]),
            manager_headers,
        ),
        200,
    )
    assert resp["amount_due_cents"] == 2000
