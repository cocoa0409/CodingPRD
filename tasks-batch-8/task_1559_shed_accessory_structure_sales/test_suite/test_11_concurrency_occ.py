"""Optimistic concurrency on order amend and jurisdiction update (PRD §2.7, §2.8, §3.2)."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_book, create_draft_order, submit_site_check, get_order,
    QUOTED_8X8_WINDOW,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]


def test_stale_order_version_rejected(api):
    """PRD §2.7: "Amending an order requires the request to carry
    `expected_order_version`, holding the `version` the client last observed for that
    order; if the order's current `version` has advanced past the supplied value, the
    amend is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.8: "**Stale-version guards** — the OCC checks of §2.7 (`ERR_STALE_VERSION`)."
    PRD §2.8: "Every request is validated in a fixed order, and a failure at any stage
    masks every later check"

    Design: Corner/complexity_layers/occ_stale_order_version_rejected
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"])
    observed = order["version"]
    submit_site_check(order["id"])  # system-driven transition bumps the version
    res = api.amend_order(
        order["id"], {"expected_order_version": observed, "width_ft": 11}, SALES
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    refreshed = get_order(order["id"])
    assert refreshed["width_ft"] == 10, "stale amend applied nothing"


def test_correct_version_amend_succeeds(api):
    """PRD §2.7: "Amending an order requires the request to carry
    `expected_order_version`, holding the `version` the client last observed for that
    order; if the order's current `version` has advanced past the supplied value, the
    amend is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "A successful amend increments the order's `version` and recomputes
    `area_sqft`, `structure_price_cents`, and `quoted_total_cents`."

    Design: Corner/complexity_layers/occ_correct_version_amend_succeeds
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
    amended = validate_success(
        api.amend_order(
            order["id"],
            {"expected_order_version": order["version"], "width_ft": 8, "depth_ft": 8},
            SALES,
        ),
        200,
    )
    assert amended["width_ft"] == 8
    assert amended["area_sqft"] == 64
    assert amended["version"] == order["version"] + 1
    # 8x8 + [WINDOW] repriced through the pinned pipeline
    assert amended["quoted_total_cents"] == QUOTED_8X8_WINDOW
    assert amended["status"] == "DRAFT", "amending never changes the order's state"


def test_stale_jurisdiction_version_rejected(api):
    """PRD §2.7: "Updating a jurisdiction's rule set works the same way with
    `expected_jurisdiction_version` and the same `ERR_STALE_VERSION` (HTTP 412)
    rejection: rule edits do not change the jurisdiction's own state, so the version
    check is the only thing standing between a stale writer and a silent overwrite."

    Design: Corner/complexity_layers/occ_stale_jurisdiction_version_rejected
    """
    jur, _, _ = setup_book()
    observed = jur["version"]
    first = validate_success(
        api.update_jurisdiction(
            jur["id"],
            {"expected_jurisdiction_version": observed, "permit_base_fee_cents": 17500},
            PERMIT,
        ),
        200,
    )
    assert first["version"] == observed + 1
    assert first["permit_base_fee_cents"] == 17500

    res = api.update_jurisdiction(
        jur["id"],
        {"expected_jurisdiction_version": observed, "permit_base_fee_cents": 19999},
        PERMIT,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    refreshed = validate_success(api.get_jurisdiction(jur["id"], PERMIT), 200)
    assert refreshed["permit_base_fee_cents"] == 17500, "stale update applied nothing"
