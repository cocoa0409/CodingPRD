"""Distributions: allocation feasibility, agency weekly capacity, OCC on the event
version, and poundage conservation (PRD §2.4, §2.9, §3.4, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    cancel_distribution,
    coordinator_headers,
    create_distribution,
    create_distribution_payload,
    deliver_distribution,
    get_agency,
    get_event,
    new_agency,
    new_crew_leader,
    new_farm,
    new_volunteer,
    run_event_lifecycle,
    setup_harvested_event,
    setup_in_progress_event,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)

WEEK_TUE = "2026-08-12T10:00:00Z"
WEEK_TUE_LATE = "2026-08-12T11:00:00Z"
WEEK_WED = "2026-08-13T10:00:00Z"
WEEK_WED_LATE = "2026-08-13T11:00:00Z"


def attempt_distribution(api, event_id, agency_id, planned_lbs, delivery_date=WEEK_TUE):
    """Raw distribution create carrying the event's current version (may fail)."""
    event = get_event(event_id)
    payload = create_distribution_payload(
        event_id, agency_id, event["version"],
        planned_lbs=planned_lbs, delivery_date=delivery_date,
    )
    return api.create_distribution(payload, coordinator_headers())


class TestDistributionPreconditions:
    def test_create_distribution_requires_harvested_event(self, api):
        """PRD §3.5: "Once an event has reached `HARVESTED`, a coordinator allocates
        pounds from it to an agency by creating a **Distribution**"
        PRD §2.6: "4. **State compatibility** — the target resource must be in a state
        that permits the requested transition, failing with `ERR_INVALID_STATE` (HTTP
        409)."

        Design: Difficulty/cross_entity_state_dependency/distribution_create_requires_event_harvested
        """
        ctx = setup_in_progress_event(
            offer_over={"estimated_lbs": 150.0},
            lot_specs=[{"gross": 110.0, "verify": True}],  # net 100.0
        )
        agency = new_agency(weekly_capacity_lbs=100000.0)
        resp = attempt_distribution(api, ctx["event"]["id"], agency["id"], 50.0)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_create_distribution_succeeds_after_finish(self, api):
        """PRD §3.5: "A new distribution is born `SCHEDULED`, and creating one advances
        the event's `version`"

        Design: Difficulty/cross_entity_state_dependency/distribution_create_requires_event_harvested
        """
        ctx = setup_harvested_event(
            offer_over={"estimated_lbs": 150.0},
            lot_specs=[{"gross": 110.0, "verify": True}],
        )
        agency = new_agency(weekly_capacity_lbs=100000.0)
        v_before = get_event(ctx["event"]["id"])["version"]
        resp = attempt_distribution(api, ctx["event"]["id"], agency["id"], 50.0)
        dist = validate_success(resp, 201)
        assert dist["status"] == "SCHEDULED"
        assert get_event(ctx["event"]["id"])["version"] == v_before + 1

    def test_shortfall_delivery_counts_delivered_pounds(self, api):
        """PRD §3.5: "when it is greater than zero but less than planned, the
        distribution moves `SCHEDULED` → `SHORTFALL`, and the agency's committed total
        then counts the delivered pounds rather than the planned pounds."
        PRD §3.5: "it sums the `planned_lbs` of the agency's `SCHEDULED` distributions
        and the `delivered_lbs` of its `DELIVERED` and `SHORTFALL` distributions whose
        `delivery_date` falls in that week"

        Design: Corner/state_machines/distribution_shortfall_side_effects
        """
        ctx = setup_harvested_event(
            offer_over={"estimated_lbs": 150.0},
            lot_specs=[{"gross": 110.0, "verify": True}],  # harvested 100.0
        )
        agency = new_agency(weekly_capacity_lbs=10000.0)
        dist = create_distribution(ctx["event"]["id"], agency["id"], 70.0,
                                   delivery_date="2026-08-11T10:00:00Z")
        delivered = deliver_distribution(dist["id"], ctx["lead"]["id"], 55.0)
        assert delivered["status"] == "SHORTFALL", "0 < 55.0 < 70.0 lands SHORTFALL"
        committed = get_agency(agency["id"])["current_week_committed_lbs"]
        assert committed == pytest.approx(55.0), (
            "the agency's committed total counts the delivered pounds, "
            "not the planned pounds"
        )

    def test_inactive_agency_rejected_on_distribution_create(self, api):
        """PRD §3.5: "Agency standing: a distribution created against an agency whose
        `active_flag` is false is rejected with `ERR_AGENCY_INACTIVE`."

        Design: Corner/validations/agency_inactive_distribution_blocked
        """
        ctx = setup_harvested_event(
            offer_over={"estimated_lbs": 150.0},
            lot_specs=[{"gross": 110.0, "verify": True}],
        )
        agency = new_agency(agency_name="AGI", county_code="AI1", active_flag=False)
        resp = attempt_distribution(api, ctx["event"]["id"], agency["id"], 10.0)
        validate_error(resp, ApiErrorId.ERR_AGENCY_INACTIVE, 422)


class TestAgencyCapacityMultiInput:
    def _capacity_setup(self, api):
        """Harvest 800.0; agency weekly capacity 500.0; dist1 planned 300.0 SCHEDULED;
        dist2 planned 150.0 delivered 100.0 SHORTFALL. Committed = 400.0."""
        ctx = setup_harvested_event(
            offer_over={"estimated_lbs": 800.0},
            lot_specs=[{"gross": 810.0, "verify": True}],
            container_over={"capacity_lbs": 1000.0},
        )
        agency = new_agency(agency_name="AGC", county_code="CAP",
                            weekly_capacity_lbs=500.0)
        dist1 = create_distribution(ctx["event"]["id"], agency["id"], 300.0,
                                    delivery_date=WEEK_TUE)
        dist2 = create_distribution(ctx["event"]["id"], agency["id"], 150.0,
                                    delivery_date=WEEK_TUE_LATE)
        dist2 = deliver_distribution(dist2["id"], ctx["lead"]["id"], 100.0)
        assert dist2["status"] == "SHORTFALL"
        return ctx, agency, dist1, dist2

    def test_delivered_pounds_count_and_equality_allowed(self, api):
        """PRD §3.5: "the agency's committed pounds for the delivery's ISO week plus
        the new `planned_lbs` may not exceed `weekly_capacity_lbs`, with a total
        exactly equal to the capacity allowed"
        PRD §3.5: "it sums the `planned_lbs` of the agency's `SCHEDULED` distributions
        and the `delivered_lbs` of its `DELIVERED` and `SHORTFALL` distributions whose
        `delivery_date` falls in that week"

        Design: Difficulty/combinatorial_formula/agency_capacity_multi_input_nonlinear
        """
        ctx, agency, dist1, dist2 = self._capacity_setup(api)
        # Committed = 300.0 (SCHEDULED planned) + 100.0 (SHORTFALL delivered) = 400.0
        resp = attempt_distribution(api, ctx["event"]["id"], agency["id"], 100.0,
                                    delivery_date=WEEK_WED)
        dist3 = validate_success(resp, 201)
        assert dist3["status"] == "SCHEDULED", (
            "400.0 committed + 100.0 planned == 500.0 capacity: equality is allowed"
        )
        assert get_agency(agency["id"])["current_week_committed_lbs"] == pytest.approx(500.0)

    def test_one_tenth_over_capacity_rejected(self, api):
        """PRD §3.5: "Agency weekly capacity: the agency's committed pounds for the
        delivery's ISO week plus the new `planned_lbs` may not exceed
        `weekly_capacity_lbs`, with a total exactly equal to the capacity allowed; an
        excess is rejected with `ERR_AGENCY_CAPACITY_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/agency_capacity_multi_input_nonlinear
        """
        ctx, agency, dist1, dist2 = self._capacity_setup(api)
        create_distribution(ctx["event"]["id"], agency["id"], 100.0,
                            delivery_date=WEEK_WED)
        resp = attempt_distribution(api, ctx["event"]["id"], agency["id"], 100.1,
                                    delivery_date=WEEK_WED_LATE)
        validate_error(resp, ApiErrorId.ERR_AGENCY_CAPACITY_EXCEEDED, 422)
        assert get_agency(agency["id"])["current_week_committed_lbs"] == pytest.approx(500.0), (
            "rejected create adds nothing: 300.0 SCHEDULED planned + 100.0 "
            "SHORTFALL delivered + 100.0 SCHEDULED planned"
        )


class TestAllocationFeasibilityOrder:
    def _allocated_event(self, api):
        """Harvest 200.0; dist1 planned 120.0, dist2 planned 80.0 -> available 0.0."""
        ctx = setup_harvested_event(
            offer_over={"estimated_lbs": 300.0},
            lot_specs=[{"gross": 210.0, "verify": True}],
        )
        agency = new_agency(weekly_capacity_lbs=100000.0)
        dist1 = create_distribution(ctx["event"]["id"], agency["id"], 120.0,
                                    delivery_date=WEEK_TUE)
        dist2 = create_distribution(ctx["event"]["id"], agency["id"], 80.0,
                                    delivery_date=WEEK_TUE_LATE)
        return ctx, agency, dist1, dist2

    def test_over_allocation_rejected_when_fully_allocated(self, api):
        """PRD §3.5: "Allocation feasibility: `planned_lbs` may not exceed the event's
        available pounds — computed as `total_harvested_lbs` minus the `planned_lbs`
        of the event's `SCHEDULED` distributions, minus the `delivered_lbs` of its
        `DELIVERED` and `SHORTFALL` distributions, minus the `condemned_lbs` of its
        resolved incidents — although a plan exactly equal to the available pounds is
        allowed and fully allocates the event; an excess is rejected with
        `ERR_ALLOCATION_EXCEEDS_HARVEST`."

        Design: Difficulty/combinatorial_formula/event_allocation_circular_order_pinned
        """
        ctx, agency, dist1, dist2 = self._allocated_event(api)
        resp = attempt_distribution(api, ctx["event"]["id"], agency["id"], 0.1,
                                    delivery_date="2026-08-12T12:00:00Z")
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_HARVEST, 422)

    def test_cancel_frees_pounds_for_new_allocation(self, api):
        """PRD §3.5: "A coordinator may also cancel a `SCHEDULED` distribution, moving
        it to `CANCELLED` and recomputing the agency's committed pounds."
        PRD §3.4: "`undistributed_lbs` — the pounds remaining of `total_harvested_lbs`
        after subtracting `total_distributed_lbs` and the condemned pounds of the
        event's resolved incidents."

        Design: Difficulty/combinatorial_formula/event_allocation_circular_order_pinned
        """
        ctx, agency, dist1, dist2 = self._allocated_event(api)
        cancel_distribution(dist1["id"])
        resp = attempt_distribution(api, ctx["event"]["id"], agency["id"], 100.0,
                                    delivery_date="2026-08-12T13:00:00Z")
        dist3 = validate_success(resp, 201)
        assert dist3["status"] == "SCHEDULED", "cancel frees 120.0, so 100.0 fits"
        event = get_event(ctx["event"]["id"])
        assert event["undistributed_lbs"] == pytest.approx(20.0), (
            "200.0 harvested - 80.0 - 100.0 SCHEDULED"
        )


class TestAgencyCapacityEqualityBoundary:
    def _equality_setup(self, api):
        """Harvest 1000.0; agency capacity 500.0; dist1 planned 300.0 SCHEDULED."""
        ctx = setup_harvested_event(
            offer_over={"estimated_lbs": 1100.0},
            lot_specs=[{"gross": 1010.0, "verify": True}],
            container_over={"capacity_lbs": 1200.0},
        )
        agency = new_agency(agency_name="AGE", county_code="EEE",
                            weekly_capacity_lbs=500.0)
        dist1 = create_distribution(ctx["event"]["id"], agency["id"], 300.0,
                                    delivery_date=WEEK_TUE)
        return ctx, agency, dist1

    def test_exact_capacity_equality_allowed(self, api):
        """PRD §3.5: "Agency weekly capacity: the agency's committed pounds for the
        delivery's ISO week plus the new `planned_lbs` may not exceed
        `weekly_capacity_lbs`, with a total exactly equal to the capacity allowed"

        Design: Difficulty/boundary_precision_check/agency_capacity_equality_allowed
        """
        ctx, agency, dist1 = self._equality_setup(api)
        resp = attempt_distribution(api, ctx["event"]["id"], agency["id"], 200.0,
                                    delivery_date=WEEK_WED)
        dist2 = validate_success(resp, 201)
        assert dist2["status"] == "SCHEDULED"
        assert get_agency(agency["id"])["current_week_committed_lbs"] == pytest.approx(500.0)

    def test_strictly_over_capacity_rejected(self, api):
        """PRD §3.5: "Agency weekly capacity: the agency's committed pounds for
        the delivery's ISO week plus the new `planned_lbs` may not exceed
        `weekly_capacity_lbs`, with a total exactly equal to the capacity allowed; an
        excess is rejected with `ERR_AGENCY_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/agency_capacity_equality_allowed
        """
        ctx, agency, dist1 = self._equality_setup(api)
        create_distribution(ctx["event"]["id"], agency["id"], 200.0,
                            delivery_date=WEEK_WED)
        resp = attempt_distribution(api, ctx["event"]["id"], agency["id"], 200.1,
                                    delivery_date=WEEK_WED_LATE)
        validate_error(resp, ApiErrorId.ERR_AGENCY_CAPACITY_EXCEEDED, 422)
        assert get_agency(agency["id"])["current_week_committed_lbs"] == pytest.approx(500.0)


class TestGateOrderAllocationBeforeCapacity:
    def _pair_setup(self, api):
        """Two harvested events (400.0 and 200.0) sharing one agency (capacity 500.0).
        ev1: dist 300.0 SCHEDULED + dist 100.0 DELIVERED -> committed 400.0."""
        farm = new_farm(farm_name="FQ", county_code="QQQ")
        lead = new_crew_leader()
        coord = new_volunteer(full_name="Coord Q", email=unique_email("coord"))
        agency = new_agency(agency_name="AGQ", county_code="QQQ",
                            weekly_capacity_lbs=500.0)
        shared = {"farm": farm, "lead": lead, "coord": coord}
        ctx1 = run_event_lifecycle(
            stop_at="harvested", shared=shared,
            offer_over={"estimated_lbs": 400.0,
                        "window_start": "2026-08-05T00:00:00Z",
                        "window_end": "2026-08-09T00:00:00Z"},
            event_start="2026-08-06T08:00:00Z", event_end="2026-08-06T12:00:00Z",
            clock_iso="2026-08-06T09:00:00Z",
            lot_specs=[{"gross": 410.0, "verify": True}],
        )
        create_distribution(ctx1["event"]["id"], agency["id"], 300.0,
                            delivery_date=WEEK_TUE)
        dist2 = create_distribution(ctx1["event"]["id"], agency["id"], 100.0,
                                    delivery_date=WEEK_TUE_LATE)
        deliver_distribution(dist2["id"], lead["id"], 100.0)
        ctx2 = run_event_lifecycle(
            stop_at="harvested", shared=shared,
            offer_over={"estimated_lbs": 300.0,
                        "window_start": "2026-08-10T00:00:00Z",
                        "window_end": "2026-08-20T00:00:00Z"},
            event_start="2026-08-11T08:00:00Z", event_end="2026-08-11T12:00:00Z",
            clock_iso="2026-08-11T09:00:00Z",
            lot_specs=[{"gross": 210.0, "verify": True}],
        )
        return ctx2, agency

    def test_allocation_violation_outranks_capacity_violation(self, api):
        """PRD §3.5: "Creation enforces a fixed sequence of business gates after
        the generic state check."
        PRD §2.6: "14. **Allocation feasibility** — `ERR_ALLOCATION_EXCEEDS_HARVEST`
        (§3.5)."
        PRD §2.6: "17. **Agency weekly capacity** — `ERR_AGENCY_CAPACITY_EXCEEDED`
        (§3.5)."
        PRD §2.6: "Every request is evaluated against a fixed, ordered sequence of
        gates, and the first gate that fails determines the error returned — later
        gates are never consulted on a failed request."

        Design: Difficulty/priority_pair_validation_conflict/distribution_referential_vs_fiscal_pair
        """
        ctx2, agency = self._pair_setup(api)
        # planned 300.0 > available 200.0 (allocation, earlier gate) AND
        # committed 400.0 + 300.0 > 500.0 (capacity, later gate).
        resp = attempt_distribution(api, ctx2["event"]["id"], agency["id"], 300.0,
                                    delivery_date="2026-08-12T12:00:00Z")
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_HARVEST, 422)

    def test_capacity_violation_fires_when_allocation_passes(self, api):
        """PRD §3.5: "an excess is rejected with `ERR_AGENCY_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/distribution_referential_vs_fiscal_pair
        """
        ctx2, agency = self._pair_setup(api)
        # planned 150.0 <= available 200.0 (allocation passes);
        # committed 400.0 + 150.0 = 550.0 > 500.0 (capacity fails alone).
        resp = attempt_distribution(api, ctx2["event"]["id"], agency["id"], 150.0,
                                    delivery_date="2026-08-12T12:00:00Z")
        validate_error(resp, ApiErrorId.ERR_AGENCY_CAPACITY_EXCEEDED, 422)


class TestEventPoundageConservation:
    def _harvested_200(self, api):
        ctx = setup_harvested_event(
            offer_over={"estimated_lbs": 250.0},
            lot_specs=[{"gross": 210.0, "verify": True}],  # net 200.0
        )
        agency = new_agency(weekly_capacity_lbs=100000.0)
        return ctx, agency

    def test_distribution_create_shifts_pounds_to_distributed(self, api):
        """PRD §3.5: "A successful creation also recomputes the agency's
        `current_week_committed_lbs` and the event's `total_distributed_lbs`."
        PRD §3.4: "`undistributed_lbs` — the pounds remaining of `total_harvested_lbs`
        after subtracting `total_distributed_lbs` and the condemned pounds of the
        event's resolved incidents."

        Design: Difficulty/compensating_invariant/event_poundage_conservation
        """
        ctx, agency = self._harvested_200(api)
        pre = get_event(ctx["event"]["id"])
        assert pre["undistributed_lbs"] == pytest.approx(200.0)
        create_distribution(ctx["event"]["id"], agency["id"], 120.0,
                            delivery_date=WEEK_TUE)
        mid = get_event(ctx["event"]["id"])
        assert mid["total_distributed_lbs"] == pytest.approx(120.0)
        assert mid["undistributed_lbs"] == pytest.approx(80.0)

    def test_compensating_cancel_restores_split_exactly(self, api):
        """PRD §3.5: "A coordinator may also cancel a `SCHEDULED` distribution, moving
        it to `CANCELLED` and recomputing the agency's committed pounds."
        PRD §3.5: "`CANCELLED` distributions are excluded entirely."

        Design: Difficulty/compensating_invariant/event_poundage_conservation
        """
        ctx, agency = self._harvested_200(api)
        dist = create_distribution(ctx["event"]["id"], agency["id"], 120.0,
                                   delivery_date=WEEK_TUE)
        cancel_distribution(dist["id"])
        post = get_event(ctx["event"]["id"])
        assert post["total_distributed_lbs"] == pytest.approx(0.0)
        assert post["undistributed_lbs"] == pytest.approx(200.0), (
            "the compensating cancel restores the conserved split with zero drift"
        )


class TestAgencyWeeklyCommitmentConservation:
    def _commitment_setup(self, api):
        """E1 harvested 400.0, E2 harvested 300.0; distA 100.0 SCHEDULED on E1;
        distB 150.0 -> 100.0 SHORTFALL on E1; distC 150.0 SCHEDULED on E2."""
        farm = new_farm(farm_name="FJ", county_code="JJJ")
        lead = new_crew_leader()
        coord = new_volunteer(full_name="Coord J", email=unique_email("coord"))
        agency = new_agency(agency_name="AGJ", county_code="JJJ",
                            weekly_capacity_lbs=10000.0)
        shared = {"farm": farm, "lead": lead, "coord": coord}
        ctx1 = run_event_lifecycle(
            stop_at="harvested", shared=shared,
            offer_over={"estimated_lbs": 450.0,
                        "window_start": "2026-08-05T00:00:00Z",
                        "window_end": "2026-08-09T00:00:00Z"},
            event_start="2026-08-06T08:00:00Z", event_end="2026-08-06T12:00:00Z",
            clock_iso="2026-08-06T09:00:00Z",
            lot_specs=[{"gross": 410.0, "verify": True}],
        )
        ctx2 = run_event_lifecycle(
            stop_at="harvested", shared=shared,
            offer_over={"estimated_lbs": 350.0,
                        "window_start": "2026-08-10T00:00:00Z",
                        "window_end": "2026-08-20T00:00:00Z"},
            event_start="2026-08-11T08:00:00Z", event_end="2026-08-11T12:00:00Z",
            clock_iso="2026-08-11T09:00:00Z",
            lot_specs=[{"gross": 310.0, "verify": True}],
        )
        dist_a = create_distribution(ctx1["event"]["id"], agency["id"], 100.0,
                                     delivery_date=WEEK_TUE)
        dist_b = create_distribution(ctx1["event"]["id"], agency["id"], 150.0,
                                     delivery_date=WEEK_TUE_LATE)
        dist_c = create_distribution(ctx2["event"]["id"], agency["id"], 150.0,
                                     delivery_date="2026-08-12T12:00:00Z")
        dist_b = deliver_distribution(dist_b["id"], lead["id"], 100.0)
        assert dist_b["status"] == "SHORTFALL"
        return agency, dist_a, dist_b, dist_c

    def test_committed_sums_status_keyed_amounts(self, api):
        """PRD §3.5: "it sums the `planned_lbs` of the agency's `SCHEDULED`
        distributions and the `delivered_lbs` of its `DELIVERED` and `SHORTFALL`
        distributions whose `delivery_date` falls in that week; `CANCELLED`
        distributions are excluded entirely."

        Design: Difficulty/compensating_invariant/agency_weekly_commitment_conservation
        """
        agency, dist_a, dist_b, dist_c = self._commitment_setup(api)
        committed = get_agency(agency["id"])["current_week_committed_lbs"]
        assert committed == pytest.approx(350.0), (
            "100.0 SCHEDULED planned + 100.0 SHORTFALL delivered + 150.0 SCHEDULED planned"
        )

    def test_compensating_cancel_restores_committed(self, api):
        """PRD §3.5: "`CANCELLED` distributions are excluded entirely."
        PRD §3.5: "A coordinator may also cancel a `SCHEDULED` distribution, moving it
        to `CANCELLED` and recomputing the agency's committed pounds."

        Design: Difficulty/compensating_invariant/agency_weekly_commitment_conservation
        """
        agency, dist_a, dist_b, dist_c = self._commitment_setup(api)
        cancel_distribution(dist_c["id"])
        committed = get_agency(agency["id"])["current_week_committed_lbs"]
        assert committed == pytest.approx(200.0), (
            "cancelling the 150.0 SCHEDULED distribution compensates exactly"
        )


class TestDistributionOcc:
    def _occ_setup(self, api):
        ctx = setup_harvested_event(
            offer_over={"estimated_lbs": 600.0},
            lot_specs=[{"gross": 510.0, "verify": True}],  # net 500.0
        )
        agency = new_agency(weekly_capacity_lbs=100000.0)
        return ctx, agency

    def test_stale_event_version_rejected_and_version_advances_once(self, api):
        """PRD §2.9: "If the event's current `version` has advanced since that
        observation — for instance because another writer has just created or
        cancelled a distribution on the same event, advancing the event's version —
        the create is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)"
        PRD §2.4: "`version` (integer): a system-managed integer that increments by
        one on every mutation of the resource"

        Design: Difficulty/compensating_invariant/occ_version_monotonicity_invariant
        """
        ctx, agency = self._occ_setup(api)
        event_id = ctx["event"]["id"]
        v = get_event(event_id)["version"]
        payload = create_distribution_payload(event_id, agency["id"], v,
                                              planned_lbs=100.0,
                                              delivery_date=WEEK_TUE)
        first = validate_success(api.create_distribution(payload, coordinator_headers()), 201)
        assert first["status"] == "SCHEDULED"
        replay = api.create_distribution(
            create_distribution_payload(event_id, agency["id"], v, planned_lbs=100.0,
                                        delivery_date=WEEK_TUE_LATE),
            coordinator_headers(),
        )
        validate_error(replay, ApiErrorId.ERR_STALE_EVENT_VERSION, 412)
        assert get_event(event_id)["version"] == v + 1, (
            "exactly one version increment despite two create attempts"
        )

    def test_fresh_version_create_succeeds_after_mutation(self, api):
        """PRD §2.9: "Creating a distribution requires the request to carry
        `expected_event_version`, holding the client's last observed `version` of the
        parent glean event."

        Design: Difficulty/compensating_invariant/occ_version_monotonicity_invariant
        """
        ctx, agency = self._occ_setup(api)
        event_id = ctx["event"]["id"]
        create_distribution(event_id, agency["id"], 100.0, delivery_date=WEEK_TUE)
        resp = attempt_distribution(api, event_id, agency["id"], 100.0,
                                    delivery_date=WEEK_TUE_LATE)
        validate_success(resp, 201)
        data, meta = validate_paginated(
            api.list_distributions(coordinator_headers(),
                                   params={"glean_event_id": event_id})
        )
        assert meta["total_count"] == 2 and len(data) == 2
