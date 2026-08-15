"""Policy violations (penalty assessment at creation) and operating-hours closure
waivers (the fourteen-day buffer rule, range coherence, state legality)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_violation,
    create_violation_payload,
    create_waiver,
    create_waiver_payload,
    make_tenant_headers,
    setup_active_lease,
    transition_waiver,
    validate_error,
    validate_success,
)


class TestOperatingHoursPenalty:
    def test_hours_penalty_ceils_partial_hour_per_event(self, api, analyst_headers):
        """PRD §3.9: "An operating-hours violation costs 25,000 cents — two hundred
        fifty dollars — per commenced hour of shortfall, so any partial hour counts
        as a full hour."
        PRD §3.9: "The `penalty_cents` is assessed once, at creation."

        Design: Difficulty/combinatorial_formula/hours_penalty_per_event_ceil_then_sum
        """
        sc = setup_active_lease()
        violation = create_violation(
            sc["lease"],
            kind="OPERATING_HOURS",
            observed_date="2026-08-03",
            shortfall_minutes=30,
        )
        # ceil(30 / 60) = 1 commenced hour -> 25,000 cents.
        assert violation["penalty_cents"] == 25_000

    def test_hours_penalties_sum_per_event_not_minutes(self, api):
        """PRD §3.9: "When exposure is aggregated for a month, the per-violation
        penalties are summed; the shortfall minutes of separate events are never
        summed first and converted once."

        Design: Difficulty/combinatorial_formula/hours_penalty_per_event_ceil_then_sum
        """
        sc = setup_active_lease()
        v1 = create_violation(
            sc["lease"],
            kind="OPERATING_HOURS",
            observed_date="2026-08-03",
            shortfall_minutes=30,
        )
        v2 = create_violation(
            sc["lease"],
            kind="OPERATING_HOURS",
            observed_date="2026-08-10",
            shortfall_minutes=30,
        )
        # Each event ceils independently: 25,000 + 25,000 = 50,000; summing the
        # minutes first (60 -> 1 hour) would wrongly yield 25,000.
        assert v1["penalty_cents"] == 25_000
        assert v2["penalty_cents"] == 25_000
        assert v1["penalty_cents"] + v2["penalty_cents"] == 50_000


class TestStreetPricingPenalty:
    def test_pricing_violation_penalty_min_and_multiplier(self, api):
        """PRD §3.9: "A street-pricing violation costs the greater of 5,000 cents —
        a fifty-dollar minimum — or twice the overcharged amount."

        Design: Corner/calculations/pricing_violation_penalty_min_and_multiplier
        """
        sc = setup_active_lease()
        floor_hit = create_violation(
            sc["lease"],
            kind="STREET_PRICING",
            observed_date="2026-08-03",
            overcharge_cents=2_000,
        )
        # max(5,000, 2 * 2,000) = 5,000 — the minimum binds.
        assert floor_hit["penalty_cents"] == 5_000

        doubled = create_violation(
            sc["lease"],
            kind="STREET_PRICING",
            observed_date="2026-08-04",
            overcharge_cents=10_000,
        )
        # max(5,000, 2 * 10,000) = 20,000 — the multiplier binds.
        assert doubled["penalty_cents"] == 20_000


class TestViolationResolution:
    def test_resolve_resolved_violation_returns_violation_already_resolved(
        self, api, analyst_headers
    ):
        """PRD §3.9: "A violation is born `OPEN`, and an analyst resolves it to
        `RESOLVED`; resolving a violation that is not `OPEN` is rejected with
        `ERR_VIOLATION_ALREADY_RESOLVED`."

        Design: Corner/validations/resolve_resolved_violation_returns_violation_already_resolved
        """
        sc = setup_active_lease()
        violation = create_violation(
            sc["lease"],
            kind="OPERATING_HOURS",
            observed_date="2026-08-03",
            shortfall_minutes=45,
        )
        resolved = validate_success(
            api.resolve_violation(violation["id"], analyst_headers), 200
        )
        assert resolved["status"] == "RESOLVED"

        res = api.resolve_violation(violation["id"], analyst_headers)
        validate_error(res, ApiErrorId.ERR_VIOLATION_ALREADY_RESOLVED)


class TestWaiverBufferRule:
    def test_buffer_five_day_gap_rejected(self, api, admin_headers):
        """PRD §3.9: "Approval enforces a fourteen-day buffer against the lease's
        other approved closures: for every other `APPROVED` waiver of the same lease,
        the two windows must be separated by at least fourteen days, measured from
        the end of one window to the start of the other with at least one direction
        yielding fourteen days or more — overlapping windows yield a negative gap in
        both directions and always fail. A violation of the buffer is rejected with
        `ERR_WAIVER_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/waiver_buffer_gap_rule
        """
        sc = setup_active_lease()
        w1 = create_waiver(sc["lease"], sc["tenant"], "2026-10-01", "2026-10-05")
        transition_waiver(w1, "APPROVE")
        w2 = create_waiver(sc["lease"], sc["tenant"], "2026-10-10", "2026-10-12",
                           reason="deep clean")
        # Gap from 2026-10-05 to 2026-10-10 is 5 days < 14.
        res = api.transition_waiver(w2["id"], {"action": "APPROVE"}, admin_headers)
        validate_error(res, ApiErrorId.ERR_WAIVER_BUFFER_VIOLATION)

    def test_buffer_fourteen_day_gap_allowed(self, api, admin_headers):
        """PRD §3.9: "Approval enforces a fourteen-day buffer against the lease's
        other approved closures: for every other `APPROVED` waiver of the same lease,
        the two windows must be separated by at least fourteen days, measured from
        the end of one window to the start of the other with at least one direction
        yielding fourteen days or more — overlapping windows yield a negative gap in
        both directions and always fail."

        Design: Difficulty/resource_temporal_overlap/waiver_buffer_gap_rule
        """
        sc = setup_active_lease()
        w1 = create_waiver(sc["lease"], sc["tenant"], "2026-10-01", "2026-10-05")
        transition_waiver(w1, "APPROVE")
        w3 = create_waiver(sc["lease"], sc["tenant"], "2026-10-19", "2026-10-20",
                           reason="equipment swap")
        # Gap from 2026-10-05 to 2026-10-19 is exactly 14 days >= 14.
        approved = validate_success(
            api.transition_waiver(w3["id"], {"action": "APPROVE"}, admin_headers), 200
        )
        assert approved["status"] == "APPROVED"


class TestWaiverGuards:
    def test_waiver_inverted_range_returns_invalid_date_range(self, api):
        """PRD §3.9: "The owning tenant requests a window from `closure_start_date`
        to `closure_end_date`, both days inclusive, with a free-form `reason`; the
        start must not be after the end, else `ERR_INVALID_DATE_RANGE`, and the lease
        must be `ACTIVE`, else `ERR_LEASE_NOT_ACTIVE`."

        Design: Corner/validations/waiver_inverted_range_returns_invalid_date_range
        """
        sc = setup_active_lease()
        res = api.create_waiver(
            create_waiver_payload(
                sc["lease"]["id"],
                closure_start_date="2026-11-10",
                closure_end_date="2026-11-05",
                reason="bad range",
            ),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_waiver_approve_after_reject_returns_waiver_state_forbids(
        self, api, admin_headers
    ):
        """PRD §3.9: "An `AirportAdmin` then decides it with an `action` of `APPROVE`
        or `REJECT`; acting on a waiver that has left `REQUESTED` is rejected with
        `ERR_WAIVER_STATE_FORBIDS`."

        Design: Corner/state_machines/waiver_approve_after_reject_returns_waiver_state_forbids
        """
        sc = setup_active_lease()
        waiver = create_waiver(sc["lease"], sc["tenant"], "2026-10-01", "2026-10-05")
        rejected = validate_success(
            api.transition_waiver(waiver["id"], {"action": "REJECT"}, admin_headers),
            200,
        )
        assert rejected["status"] == "REJECTED"

        res = api.transition_waiver(waiver["id"], {"action": "APPROVE"}, admin_headers)
        validate_error(res, ApiErrorId.ERR_WAIVER_STATE_FORBIDS)
