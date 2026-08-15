"""Grade stamping, re-stamping, and the release cascade on allocated packages."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    publish_price_list, get_package, get_order,
    produce_dry_packages, produce_stamped_packages, setup_order_with_allocation,
    make_grader_headers, make_sales_rep_headers,
)


def _stamped_package_for_rework(measured=10.5):
    """One DF NO_2 len-12 package, dried to the given measured tally and stamped."""
    _run, packages = produce_stamped_packages([{"green_mbf": 12.0}], [measured])
    return packages[0]


def _allocated_scenario(volume=9):
    """Spot order (NO_2, len 12) allocated against one stamped package of dry 10.5."""
    publish_price_list()
    order, packages, _run = setup_order_with_allocation(
        [{"green_mbf": 12.0}], [10.5],
        order_overrides={"volume_mbf": volume, "length_spec": 12},
    )
    return order, packages[0]


class TestStampGuard:
    def test_stamp_twice_second_returns_invalid_state(self, api):
        """PRD Section 3.6: "Attempting a `STAMP` on a package that is not `DRY`, or a `RESTAMP` on one that is neither `STAMPED` nor `ALLOCATED`, is an `ERR_INVALID_STATE` rejection."

        Design: Corner/state_machines/stamp_twice_second_returns_invalid_state
        """
        pkg = _stamped_package_for_rework(measured=18.8)
        res = api.create_grade_inspection(
            pkg["id"], {"inspector_grade": "NO_3", "action": "STAMP"}, make_grader_headers()
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_package(pkg["id"])
        assert after["stamped_grade"] == "NO_2", (
            f"rejected second STAMP must not re-grade, got {after['stamped_grade']}"
        )


class TestRestampOnAllocated:
    def test_restamp_same_grade_keeps_allocation(self, api):
        """PRD Section 3.6: "When the `inspector_grade` equals the holding order's `grade`, nothing is released: the package stays `ALLOCATED`, keeps its `sales_order_id`, the row is appended, and `version` increments."

        Design: Corner/state_machines/restamp_same_grade_keeps_allocation
        """
        order, pkg = _allocated_scenario(volume=9)
        res = api.create_grade_inspection(
            pkg["id"],
            {"inspector_grade": "NO_2", "action": "RESTAMP", "note": "re-inspection confirms"},
            make_grader_headers(),
        )
        validate_success(res, 201)
        after_pkg = get_package(pkg["id"])
        assert after_pkg["status"] == "ALLOCATED", f"same grade — no release, got {after_pkg['status']}"
        assert after_pkg["sales_order_id"] == order["id"]
        after_order = get_order(order["id"])
        assert after_order["status"] == "ALLOCATED"
        assert after_order["allocated_mbf"] == pytest.approx(10.5, abs=1e-6)

    def test_restamp_downfall_releases_package(self, api):
        """PRD Section 3.6: "When the `inspector_grade` differs, the release cascade fires: the package's `stamped_grade` is replaced with the `inspector_grade`, its `sales_order_id` is cleared, and it falls back from `ALLOCATED` to `STAMPED`; the order it left recomputes `allocated_mbf` and `total_cents` without it; and an order left with zero allocated packages by the release flips from `ALLOCATED` back to `PLACED`."

        Design: Difficulty/transitive_cascade/restamp_downfall_deallocates_order
        """
        order, pkg = _allocated_scenario(volume=9)
        assert order["allocated_mbf"] == pytest.approx(10.5, abs=1e-6)
        res = api.create_grade_inspection(
            pkg["id"],
            {"inspector_grade": "NO_3", "action": "RESTAMP", "note": "wane over limit"},
            make_grader_headers(),
        )
        validate_success(res, 201)
        after_pkg = get_package(pkg["id"])
        assert after_pkg["stamped_grade"] == "NO_3", "downfall recorded"
        assert after_pkg["status"] == "STAMPED"
        assert after_pkg["sales_order_id"] is None, "release clears the order link"

    def test_restamp_downfall_reverts_order_to_placed(self, api):
        """PRD Section 3.6: "When the `inspector_grade` differs, the release cascade fires: the package's `stamped_grade` is replaced with the `inspector_grade`, its `sales_order_id` is cleared, and it falls back from `ALLOCATED` to `STAMPED`; the order it left recomputes `allocated_mbf` and `total_cents` without it; and an order left with zero allocated packages by the release flips from `ALLOCATED` back to `PLACED`."

        Design: Difficulty/transitive_cascade/restamp_downfall_deallocates_order
        """
        order, pkg = _allocated_scenario(volume=9)
        res = api.create_grade_inspection(
            pkg["id"],
            {"inspector_grade": "NO_3", "action": "RESTAMP", "note": "wane over limit"},
            make_grader_headers(),
        )
        validate_success(res, 201)
        after_order = get_order(order["id"])
        assert after_order["status"] == "PLACED", (
            f"order left with zero allocated packages falls back, got {after_order['status']}"
        )
        assert after_order["allocated_mbf"] == 0
        assert after_order["total_cents"] == 0
