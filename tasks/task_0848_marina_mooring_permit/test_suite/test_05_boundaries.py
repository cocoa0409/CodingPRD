"""Boundary-precision checks: the liveaboard cap '>=' boundary on activation and
the pump-out interval '>' boundary on the maintenance sweep."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_marina,
    create_berth,
    create_boater,
    create_vessel,
    apply_permit,
    pay,
    setup_active_permit,
    get_permit,
    get_marina,
    get_vessel,
)

HARBOR = TEST_USERS["harbormaster_headers"]


class TestLiveaboardCapBoundary:
    def _first_active_second_offered(self, api):
        set_clock(api, "2026-05-15T00:00:00Z")
        marina = create_marina(api, liveaboard_cap=1)
        create_berth(api, marina["id"])
        create_berth(api, marina["id"])
        boater1 = create_boater(api, full_name="Live One", email="l1@example.com")
        vessel1 = create_vessel(api, boater1["id"], has_holding_tank=True, length_ft=30)
        permit1 = apply_permit(api, marina["id"], boater1["id"], vessel1["id"], is_liveaboard=True)
        boater2 = create_boater(api, full_name="Live Two", email="l2@example.com")
        vessel2 = create_vessel(api, boater2["id"], has_holding_tank=True, length_ft=30)
        permit2 = apply_permit(api, marina["id"], boater2["id"], vessel2["id"], is_liveaboard=True)
        pay(api, permit1["invoice_id"], 170000)  # activate first -> liveaboard_count 1
        return marina, permit1, permit2

    def test_second_liveaboard_activation_rejected_at_cap(self, api):
        """PRD §3.4: "If the permit is a liveaboard permit, activation additionally
        requires that the marina's `liveaboard_count` be strictly below its
        `liveaboard_cap`; when the count has already reached the cap the activation
        is rejected with `ERR_LIVEABOARD_LIMIT_REACHED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/liveaboard_cap_ge_boundary_on_activation
        """
        _, _, permit2 = self._first_active_second_offered(api)
        validate_error(
            api.pay_invoice(permit2["invoice_id"], {"amount_cents": 170000}, HARBOR),
            ApiErrorId.ERR_LIVEABOARD_LIMIT_REACHED,
        )
        assert get_permit(api, permit2["id"])["status"] == "OFFERED"

    def test_first_liveaboard_activation_below_cap_succeeds(self, api):
        """PRD §3.4: "If the permit is a liveaboard permit, activation additionally
        requires that the marina's `liveaboard_count` be strictly below its
        `liveaboard_cap`; when the count has already reached the cap the activation
        is rejected with `ERR_LIVEABOARD_LIMIT_REACHED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/liveaboard_cap_ge_boundary_on_activation
        """
        marina, permit1, _ = self._first_active_second_offered(api)
        assert get_permit(api, permit1["id"])["status"] == "ACTIVE"
        assert get_marina(api, marina["id"])["liveaboard_count"] == 1


class TestPumpoutIntervalBoundary:
    def _active(self, api):
        return setup_active_permit(
            api,
            clock="2026-05-15T00:00:00Z",
            marina_overrides={"pumpout_interval_days": 30},
            vessel_overrides={"has_holding_tank": True, "length_ft": 30},
        )

    def test_thirty_one_days_overdue_suspends_permit(self, api):
        """PRD §3.7: "A vessel becomes non-compliant precisely when the number of
        days since its reference pump-out date is strictly greater than that
        interval; at or below the interval it is compliant."
        PRD §3.7: "When the maintenance sweep finds an `ACTIVE` permit whose vessel
        has a holding tank and whose days since last pump-out have crossed strictly
        beyond the interval, it moves the permit from `ACTIVE` to `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/pumpout_interval_gt_boundary_on_maintenance
        """
        b = self._active(api)
        set_clock(api, "2026-06-14T00:00:00Z")  # 30 days: still compliant
        validate_success(api.run_maintenance(b["marina"]["id"], HARBOR))
        set_clock(api, "2026-06-15T00:00:00Z")  # 31 days: overdue
        validate_success(api.run_maintenance(b["marina"]["id"], HARBOR))
        assert get_permit(api, b["permit"]["id"])["status"] == "SUSPENDED"
        assert get_vessel(api, b["vessel"]["id"])["pumpout_status"] == "OVERDUE"

    def test_thirty_days_at_boundary_stays_active(self, api):
        """PRD §3.7: "A vessel becomes non-compliant precisely when the number of
        days since its reference pump-out date is strictly greater than that
        interval; at or below the interval it is compliant."

        Design: Difficulty/boundary_precision_check/pumpout_interval_gt_boundary_on_maintenance
        """
        b = self._active(api)
        set_clock(api, "2026-06-14T00:00:00Z")  # exactly 30 days since activation
        validate_success(api.run_maintenance(b["marina"]["id"], HARBOR))
        assert get_permit(api, b["permit"]["id"])["status"] == "ACTIVE"
        assert get_vessel(api, b["vessel"]["id"])["pumpout_status"] == "COMPLIANT"
