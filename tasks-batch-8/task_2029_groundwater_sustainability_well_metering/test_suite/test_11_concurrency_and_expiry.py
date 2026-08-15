"""Optimistic concurrency on account updates and the 72-hour transfer expiry sweep
(PRD §2.4, §2.5, §2.9, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_account,
    get_account,
    propose_transfer,
    set_clock,
    setup_account_with_active_production_well,
    submit_and_verify_report,
    validate_error,
    validate_success,
)


def test_stale_account_version_patch_conflict(api, water_master_headers):
    """PRD §2.9: "Mutations to a `WaterUserAccount` — specifically, the endpoint that updates `base_allocation_af` and/or `status` — require the request to carry `expected_account_version`, a non-optional input field carrying the client's last observed `version` of the account. If the account's current `version` has advanced since that observation — for instance because a report-verification cascade legitimately moved `extracted_af_ytd` and `pending_extraction_af` forward — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the writer from overwriting a state it never saw."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources (for example, when verifying an extraction report advances both the report's `version` and the owning account's `version`)."

    Design: Corner/cross_cutting_layers/stale_account_version_patch_conflict
    """
    account, well = setup_account_with_active_production_well(holder_name="Pumper OC")
    observed_version = account["version"]
    assert observed_version == 1

    # Two account mutations without the client re-reading: report create moves
    # pending_extraction_af (+1) and the verify cascade moves the ledgers (+1).
    submit_and_verify_report(well["id"], account["id"], month=6, reported_af=5.000)

    stale = api.update_account(
        account["id"],
        {"base_allocation_af": 120.000, "expected_account_version": observed_version},
        water_master_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = get_account(account["id"])
    assert fresh["version"] == 3, (
        f"create (1) + report-create cascade (+1) + verify cascade (+1) = 3, got "
        f"{fresh['version']}"
    )

    updated = validate_success(
        api.update_account(
            account["id"],
            {"base_allocation_af": 120.000, "expected_account_version": fresh["version"]},
            water_master_headers,
        )
    )
    assert updated["base_allocation_af"] == pytest.approx(120.000, abs=1e-9)
    assert updated["version"] == 4


def test_transfer_expires_at_72h_boundary(api, water_master_headers):
    """PRD §3.4: "A created order lands in `PROPOSED`, its `expires_at` is stamped at creation time plus 72 hours, and the seller's `transfer_reserved_af` increases by `quantity_af` — a reservation against double-selling that blocks the same water from being committed twice."
    PRD §2.5: "Setting the clock also triggers an expiry sweep: every `TransferOrder` still in `PROPOSED` status whose `expires_at` is strictly before the new time transitions to `EXPIRED`, and each such expiry releases the seller's reservation."

    Design: Corner/cross_cutting_layers/transfer_expires_at_72h_boundary
    """
    seller = create_account(holder_name="Seller ES", base_allocation_af=100.000)
    buyer = create_account(holder_name="Buyer EB", base_allocation_af=50.000)
    order = propose_transfer(seller["id"], buyer["id"], 5.000)
    assert order["status"] == "PROPOSED"
    # Created at the default clock 2026-08-01T00:00:00Z -> expiry 2026-08-04T00:00:00Z.
    assert order["expires_at"].startswith("2026-08-04T00:00:00"), (
        f"expires_at must be created_at + 72 hours, got {order['expires_at']}"
    )

    # At exactly expires_at the order is NOT swept (strictly-before rule).
    set_clock("2026-08-04T00:00:00Z")
    at_expiry = validate_success(api.get_transfer_order(order["id"], water_master_headers))
    assert at_expiry["status"] == "PROPOSED", (
        f"expiry requires the clock strictly past expires_at, got {at_expiry['status']}"
    )

    set_clock("2026-08-04T00:00:01Z")
    after = validate_success(api.get_transfer_order(order["id"], water_master_headers))
    assert after["status"] == "EXPIRED"
    assert get_account(seller["id"])["transfer_reserved_af"] == pytest.approx(0.0, abs=1e-9), (
        "the sweep releases the seller's 5.000-af reservation"
    )
