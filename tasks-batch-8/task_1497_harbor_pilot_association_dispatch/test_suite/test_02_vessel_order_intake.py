"""Vessel order intake, amendment, ETA rule, tariff pinning (PRD §3.2, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_agent_headers,
    assert_vessel_order, assert_instant_equals,
    make_order_payload, make_tariff_schedule_payload,
    create_main_tariff, place_order, get_order_fresh,
)

AGENT = "agent-1"


class TestOrderIntakeValidation:
    def test_vessel_order_create_missing_required_gt_returns_invalid_request(
            self, api, vessel_agent_headers):
        """PRD §3.2: "A `VesselAgent` opens a movement order by providing the
        `vessel_name`, the vessel's gross tonnage `gt` (a positive integer), the
        `draft_dm` (draft in decimeters, also positive), the `order_type` —
        `ARRIVAL`, `DEPARTURE`, or `SHIFT` — and the `eta`, the estimated time
        of arrival or startup."
        PRD §2.8: "Structural request validation — missing required fields, type
        mismatches, out-of-range enum values, non-positive quantities — is the
        final catch-all, surfacing `ERR_INVALID_REQUEST`."

        Design: Corner/entities/vessel_order_create_missing_required_gt_returns_invalid_request
        """
        create_main_tariff()
        payload = make_order_payload(vessel_name="MV NoGT")
        del payload["gt"]
        res = api.create_order(payload, vessel_agent_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_order_create_invalid_enum_returns_invalid_request(
            self, api, vessel_agent_headers):
        """PRD §3.2: "the `order_type` — `ARRIVAL`, `DEPARTURE`, or `SHIFT`".
        PRD §2.8: "Structural request validation — missing required fields, type
        mismatches, out-of-range enum values, non-positive quantities — is the
        final catch-all, surfacing `ERR_INVALID_REQUEST`."

        Design: Corner/entities/order_create_invalid_enum_returns_invalid_request
        """
        create_main_tariff()
        payload = make_order_payload(vessel_name="MV Enum", gt=1000, draft_dm=50,
                                     order_type="CIRCUMNAVIGATION")
        res = api.create_order(payload, vessel_agent_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    @pytest.mark.parametrize("bad_eta", ["2026-08-01T00:00:00Z", "2026-07-01T00:00:00Z"])
    def test_order_create_eta_equal_or_past_returns_422(
            self, api, vessel_agent_headers, bad_eta):
        """PRD §3.2: "The ETA must be strictly after the logical clock at intake;
        an ETA equal to the current clock reading fails with `ERR_ETA_IN_PAST`."

        The default logical clock reads 2026-08-01T00:00:00Z (PRD §2.4); the first
        parametrized case is exactly now, the second is in the past.

        Design: Corner/validations/order_create_eta_equal_or_past_returns_422
        """
        create_main_tariff()
        payload = make_order_payload(vessel_name="MV Eta", gt=1000, draft_dm=50,
                                     eta=bad_eta)
        res = api.create_order(payload, vessel_agent_headers)
        validate_error(res, ApiErrorId.ERR_ETA_IN_PAST)


class TestProvisionalFeeAtIntake:
    def test_order_create_computed_provisional_fee_input_ignored(
            self, api, vessel_agent_headers):
        """PRD §3.2: "the provisional tariff is computed over the declared `gt`
        and `draft_dm` under the **average-rate** variant of the tariff (see
        §3.6) and stored as `provisional_fee_cents`."
        PRD §3.6: "the single tier whose band contains the order's `gt` prices
        the entire tonnage at that tier's rate".

        gt 25000 falls in the (20000, inf) tier at 10c/gt: 25000 x 10 = 250000;
        draft 120 > 100 triggers the surcharge: x1.15 -> 287500. A client-
        supplied provisional_fee_cents is discarded in favour of the computation.

        Design: Corner/entities/order_create_computed_provisional_fee_input_ignored
        """
        create_main_tariff()
        payload = make_order_payload(vessel_name="MV Comp", gt=25000, draft_dm=120)
        payload["provisional_fee_cents"] = 1
        res = api.create_order(payload, vessel_agent_headers)
        order = validate_success(res, 201)
        assert_vessel_order(order)
        assert order["provisional_fee_cents"] == 287500


class TestTariffPinning:
    def test_calc_schedule_resolution_picks_latest_effective(
            self, api, admin_headers, vessel_agent_headers):
        """PRD §3.6: "the schedule with the greatest `effective_from` at or
        before the logical clock is `ACTIVE` (ties on equal `effective_from`
        broken by `created_at` ascending); any schedule whose `effective_from`
        is strictly after the clock is `SCHEDULED`; and every remaining row —
        including a future-dated schedule that a newer, already-effective
        schedule leapfrogs — is `SUPERSEDED`."
        PRD §3.2: "the schedule with the greatest `effective_from` at or before
        the logical clock — the schedule whose computed `status` is `ACTIVE` —
        is recorded as the order's `tariff_schedule_id`".

        S1 (2026-01-01, flat 20c/gt) is superseded by S2 (2026-07-01, flat
        100c/gt); a new order pins S2 and prices 1000 gt x 100 = 100000.

        Design: Corner/calculations/calc_schedule_resolution_picks_latest_effective
        """
        s1 = validate_success(api.create_tariff_schedule(
            make_tariff_schedule_payload(
                effective_from="2026-01-01T00:00:00Z",
                tiers=[{"min_gt_exclusive": 0, "max_gt_inclusive": None,
                        "rate_cents_per_gt": 20}]), admin_headers), 201)
        s2 = validate_success(api.create_tariff_schedule(
            make_tariff_schedule_payload(
                effective_from="2026-07-01T00:00:00Z",
                tiers=[{"min_gt_exclusive": 0, "max_gt_inclusive": None,
                        "rate_cents_per_gt": 100}]), admin_headers), 201)

        order = validate_success(api.create_order(
            make_order_payload(vessel_name="MV Sched", gt=1000, draft_dm=50),
            vessel_agent_headers), 201)
        assert order["tariff_schedule_id"] == s2["id"]
        assert order["provisional_fee_cents"] == 100000

        data, _ = validate_paginated(api.list_tariff_schedules(admin_headers))
        by_id = {row["id"]: row for row in data}
        assert by_id[s1["id"]]["status"] == "SUPERSEDED"
        assert by_id[s2["id"]]["status"] == "ACTIVE"


class TestOrderAmendment:
    def test_calc_provisional_recomputed_on_draft_amendment(
            self, api, vessel_agent_headers):
        """PRD §3.2: "A successful amendment re-pins the tariff schedule,
        recomputes `provisional_fee_cents` whenever `gt` or `draft_dm` was
        supplied, and increments the order's `version`."

        Draft 120 -> 90 drops the surcharge leg: 25000 x 10 with no surcharge.

        Design: Corner/calculations/calc_provisional_recomputed_on_draft_amendment
        """
        create_main_tariff()
        order = place_order(vessel_name="MV Amend", gt=25000, draft_dm=120)
        assert order["provisional_fee_cents"] == 287500

        res = api.patch_order(order["id"], {
            "draft_dm": 90, "expected_order_version": order["version"],
        }, vessel_agent_headers)
        amended = validate_success(res, 200)
        assert amended["provisional_fee_cents"] == 250000
        assert amended["version"] == order["version"] + 1

    def test_order_patch_occ_stale_version_returns_412(self, api, vessel_agent_headers):
        """PRD §2.7: "Amending a vessel order requires `expected_order_version`
        in the request body, carrying the client's last observed `version` of
        the target order. If the order's current `version` differs — because
        another writer amended the order in the meantime — the amendment is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/order_patch_occ_stale_version_returns_412
        """
        create_main_tariff()
        order = place_order(vessel_name="MV Occ")
        stale_v = order["version"]

        first = validate_success(api.patch_order(order["id"], {
            "eta": "2026-08-11T00:00:00Z", "expected_order_version": stale_v,
        }, vessel_agent_headers), 200)
        assert first["version"] == stale_v + 1

        res = api.patch_order(order["id"], {
            "eta": "2026-08-12T00:00:00Z", "expected_order_version": stale_v,
        }, vessel_agent_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

        after = get_order_fresh(order["id"])
        assert_instant_equals(after["eta"], "2026-08-11T00:00:00Z")  # loser's write absent
        assert after["version"] == stale_v + 1

    def test_order_patch_by_other_agent_forbidden(self, api, vessel_agent_headers):
        """PRD §2.1: "for a `VesselAgent`, the identifier is captured at order
        intake as the order's `agent_id` and later compared against `X-User-ID`
        on amendment and cancellation". "A request whose role is not permitted
        on the targeted endpoint, or that fails an ownership check, is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/order_patch_by_other_agent_forbidden
        """
        create_main_tariff()
        order = place_order(agent_id="agent-1", vessel_name="MV Own")

        res = api.patch_order(order["id"], {
            "eta": "2026-08-12T00:00:00Z",
            "expected_order_version": order["version"],
        }, make_agent_headers("agent-2"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

        after = get_order_fresh(order["id"])
        assert after["version"] == order["version"], "rejected amendment must not mutate"


class TestOrderCancelTerminal:
    def test_vessel_order_cancel_from_cancelled_returns_invalid_state(
            self, api, vessel_agent_headers):
        """PRD §2.8: "State-machine guards come after that — the generic
        from-state guard (`ERR_INVALID_STATE`) plus the order-specific guards
        `ERR_ORDER_LOCKED` and `ERR_ORDER_NOT_DISPATCHABLE`."
        PRD §3.2: "Cancelling a `BOOKED` order simply moves it to `CANCELLED`."

        CANCELLED is terminal; a second cancel by the owning agent fails the
        from-state guard.

        Design: Corner/state_machines/vessel_order_cancel_from_cancelled_returns_invalid_state
        """
        create_main_tariff()
        order = place_order()
        validate_success(api.cancel_order(order["id"], vessel_agent_headers), 200)

        res = api.cancel_order(order["id"], vessel_agent_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
