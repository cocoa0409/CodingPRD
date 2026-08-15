"""Drought curtailment: effectuation gates, allocation curtailment, the
latest-start-first cancellation cascade, and lifting."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_amount,
    assert_drought_declaration,
    create_drought,
    create_open_season,
    effectuate_drought,
    get_allocation,
    get_drought,
    get_order,
    get_work_order,
    place_order,
    schedule_order,
    setup_open_season_with_allocation,
    validate_error,
    validate_success,
)


class TestEffectuationCascade:
    def _setup_overcommitted_junior(self):
        """JUNIOR account (5.0 acres -> 10.00 af base) with two SCHEDULED
        orders of 4.13 af each; a PROPOSED STAGE_2 declaration."""
        scenario = setup_open_season_with_allocation(
            holder_name="Junior J", parcel_number="APN-009",
            priority_date="1922-05-01T00:00:00Z",
        )
        order_a = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T18:00:00Z",
        )
        order_b = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-06-03T08:00:00Z", end="2026-06-03T18:00:00Z",
        )
        _a, _wo_a = schedule_order(order_a["id"], "rider-1")
        _b, wo_b = schedule_order(order_b["id"], "rider-2")
        drought = create_drought(scenario["season"]["id"], "STAGE_2")
        scenario.update({"order_a": order_a, "order_b": order_b,
                         "wo_b": wo_b, "drought": drought})
        return scenario

    def test_effectuation_curtails_junior_allocation(self, api):
        """PRD §3.7: "Effectuation moves the declaration `PROPOSED →
        EFFECTIVE` and propagates curtailment through every allocation of the
        season: each allocation's `curtailed_entitlement_af` is computed as
        its `base_entitlement_af` reduced by the percentage matching its
        account's priority class — rounded half-up to 2 decimal places — its
        `effective_entitlement_af` switches to the curtailed value, and its
        status becomes `CURTAILED`."
        PRD §2.9: "Stage 2 curtails seniors by 10 percent and juniors by 40
        percent."
        The JUNIOR allocation's entitlement drops to 10.00 x (1 - 0.40) =
        6.00 af.

        Design: Difficulty/transitive_cascade/drought_effectuation_cascade
        """
        scenario = self._setup_overcommitted_junior()
        resp = api.effectuate_drought(scenario["drought"]["id"], ADMIN)
        declaration = validate_success(resp, expected_status=200)
        assert_drought_declaration(declaration)
        assert declaration["status"] == "EFFECTIVE"

        allocation = get_allocation(scenario["allocation"]["id"])
        assert allocation["status"] == "CURTAILED"
        assert_amount(allocation["curtailed_entitlement_af"], 6.00,
                      "curtailed_entitlement_af (10.00 x (1 - 0.40))")
        assert_amount(allocation["effective_entitlement_af"], 6.00,
                      "effective_entitlement_af switches to the curtailed value")

    def test_effectuation_cancels_latest_start_order_first(self, api):
        """PRD §3.7: "For each allocation whose `committed_af` now exceeds its
        recomputed `available_af`, the system cancels that allocation's orders
        in `REQUESTED` or `SCHEDULED` status, selecting them in descending
        `requested_start_at` order — latest-starting first — with ties broken
        by `created_at` descending, and continues cancelling until
        `committed_af` no longer exceeds `available_af`. Each cancelled order
        releases its committed water from the allocation and cascades
        `CANCELLED` onto its non-terminal rider work order."
        The latest-starting order (2026-06-03) is the first cancellation
        victim, and its work order is cancelled alongside.

        Design: Difficulty/transitive_cascade/drought_effectuation_cascade
        """
        scenario = self._setup_overcommitted_junior()
        validate_success(api.effectuate_drought(scenario["drought"]["id"], ADMIN))

        assert get_order(scenario["order_b"]["id"])["status"] == "CANCELLED", (
            "The latest-starting order is cancelled first"
        )
        assert get_work_order(scenario["wo_b"]["id"])["status"] == "CANCELLED", (
            "Its non-terminal work order is cancelled alongside"
        )


class TestEffectuationGates:
    def test_effectuate_second_drought_rejected(self, api):
        """PRD §3.7: "Effectuating a `PROPOSED` declaration requires the
        season to be `OPEN` (else `ERR_SEASON_NOT_OPEN`) and requires that no
        other declaration on the season is currently `EFFECTIVE` (else
        `ERR_INVALID_DROUGHT_STATE`)."

        Design: Corner/state_machines/effectuate_second_drought_rejected
        """
        season = create_open_season()
        d1 = create_drought(season["id"], "STAGE_1")
        d2 = create_drought(season["id"], "STAGE_2")
        validate_success(api.effectuate_drought(d1["id"], ADMIN))

        resp = api.effectuate_drought(d2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_DROUGHT_STATE)

        assert get_drought(d2["id"])["status"] == "PROPOSED"
        assert get_drought(d1["id"])["status"] == "EFFECTIVE"


class TestDroughtLift:
    def test_drought_lift_restores_entitlement_keeps_cancellations(self, api):
        """PRD §3.7: "Lifting an `EFFECTIVE` declaration moves it `EFFECTIVE →
        LIFTED`: every `CURTAILED` allocation of the season has its
        `effective_entitlement_af` restored to `base_entitlement_af` and its
        status returned to `ACTIVE`. Orders cancelled by the curtailment
        cascade are not resurrected — they remain `CANCELLED`."
        STAGE_3 curtails the JUNIOR allocation to 10.00 x (1 - 0.75) = 2.50
        af, below the single 4.13 af commitment, so that order is cancelled by
        the cascade and stays cancelled after the lift.

        Design: Corner/state_machines/drought_lift_restores_entitlement_keeps_cancellations
        """
        scenario = setup_open_season_with_allocation(
            holder_name="Lift L", parcel_number="APN-114",
            priority_date="1922-05-01T00:00:00Z",
        )
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T18:00:00Z",
        )
        order, _wo = schedule_order(order["id"], "rider-1")
        drought = create_drought(scenario["season"]["id"], "STAGE_3")
        effectuate_drought(drought["id"])

        # Cascade cancelled the only order (4.13 committed > 2.50 curtailed).
        assert get_order(order["id"])["status"] == "CANCELLED"

        resp = api.lift_drought(drought["id"], ADMIN)
        lifted = validate_success(resp, expected_status=200)
        assert lifted["status"] == "LIFTED"

        allocation = get_allocation(scenario["allocation"]["id"])
        assert allocation["status"] == "ACTIVE"
        assert_amount(allocation["effective_entitlement_af"], 10.00,
                      "effective_entitlement_af restored to base")
        assert_amount(allocation["committed_af"], 0.00,
                      "The cancelled order's commitment stays released")
        assert get_order(order["id"])["status"] == "CANCELLED", (
            "Cancelled orders are not resurrected"
        )
