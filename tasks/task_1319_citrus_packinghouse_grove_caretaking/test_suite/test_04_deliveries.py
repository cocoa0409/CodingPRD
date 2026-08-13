"""Deliveries: receiving gates and computed fields, the two parallel status
dimensions, regulatory hold/release/condemn, close gating on pool pricing,
and close-intake exclusion of condemned fruit."""
from test_helpers import (
    ApiErrorId,
    assert_delivery,
    create_assignment_payload,
    create_delivery_payload,
    create_quarantine,
    get_delivery,
    get_grower,
    get_sort_run,
    get_success_data,
    juice_spec,
    record_maturity_test,
    set_clock,
    setup_assignment_in_progress,
    setup_delivery_received,
    setup_posted_scenario,
    sort_run_lifecycle,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    close_intake_and_set_price,
    create_crew,
    create_grove,
    create_grower,
    create_pool,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_officer_headers,
    make_operator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestDeliveryCreation:
    def test_delivery_net_boxes_computed_and_tare_boundary(self, api):
        """PRD §3.3: "The system stamps `received_at` from the logical clock,
        copies `variety` from the grove at creation, computes `net_boxes` as
        `gross_boxes` minus `tare_boxes`, and resolves `pool_id` to the `OPEN`
        pool whose variety matches and whose week — the seven dates from the
        pool's `week_start` through six days later, inclusive — contains
        `received_at`." PRD §3.3: tare_boxes "must be zero or more and
        strictly fewer than `gross_boxes` (`ERR_INVALID_REQUEST` otherwise)".

        Design: Corner/entities/delivery_net_boxes_computed_and_tare_boundary
        """
        scenario = setup_assignment_in_progress("E8", planned_boxes=100)
        pool = create_pool("HAMLIN", "2026-07-27")
        delivery = validate_success(api_client.create_delivery(
            create_delivery_payload(scenario["grove"]["id"],
                                    scenario["assignment"]["id"],
                                    gross_boxes=80, tare_boxes=5),
            SUPERVISOR), expected_status=201)
        assert_delivery(delivery)
        assert delivery["net_boxes"] == 75, "80 gross - 5 tare"
        assert delivery["variety"] == "HAMLIN", "copied from the grove"
        assert delivery["processing_status"] == "RECEIVED"
        assert delivery["regulatory_status"] == "CLEAR"
        assert delivery["pool_id"] == pool["id"]
        # tare == gross would leave net 0; rejected at the boundary.
        resp = api_client.create_delivery(
            create_delivery_payload(scenario["grove"]["id"],
                                    scenario["assignment"]["id"],
                                    gross_boxes=10, tare_boxes=10),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_delivery_requires_active_assignment_and_open_pool(self, api):
        """PRD §3.3: "the referenced assignment must be `IN_PROGRESS` and
        belong to the same grove as the delivery
        (`ERR_ASSIGNMENT_NOT_ACTIVE`)". PRD §3.3: "If no such `OPEN` pool
        exists, receiving fails with `ERR_POOL_NOT_ACCEPTING`."

        Design: Corner/validations/delivery_requires_active_assignment_and_open_pool
        """
        set_clock("2026-08-01T00:00:00Z")
        grower = create_grower("GR-V10", "Referential Groves")
        grove_h = create_grove(grower["id"], "H1", "HAMLIN", 50, "POLK")
        record_maturity_test(grove_h["id"], inspector_id="qi-v10")
        grove_v = create_grove(grower["id"], "V1", "VALENCIA", 50, "POLK")
        record_maturity_test(grove_v["id"], inspector_id="qi-v10")
        create_pool("HAMLIN", "2026-07-27")  # no VALENCIA pool exists
        crew_a = create_crew("CR-V10A", 400)
        crew_b = create_crew("CR-V10B", 400)
        assignment_idle = get_success_data(api_client.create_assignment(
            create_assignment_payload(crew_a["id"], grove_h["id"],
                                      "2026-08-01T00:00:00Z",
                                      "2026-08-01T12:00:00Z", 50), SUPERVISOR))
        assignment_active = get_success_data(api_client.create_assignment(
            create_assignment_payload(crew_b["id"], grove_v["id"],
                                      "2026-08-01T00:00:00Z",
                                      "2026-08-01T12:00:00Z", 50), SUPERVISOR))
        get_success_data(api_client.start_assignment(
            assignment_active["id"], SUPERVISOR))
        # A SCHEDULED (never started) assignment cannot receive fruit.
        resp = api_client.create_delivery(
            create_delivery_payload(grove_h["id"], assignment_idle["id"], 10, 0),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE)
        # An IN_PROGRESS assignment still cannot receive without an OPEN pool.
        resp = api_client.create_delivery(
            create_delivery_payload(grove_v["id"], assignment_active["id"], 10, 0),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_POOL_NOT_ACCEPTING)


class TestParallelStatusDimensions:
    def test_hold_freezes_regulatory_dimension_only_and_blocks_sort(self, api):
        """PRD §2.10: "Deliveries carry two independent status dimensions on
        the same row: `processing_status` tracks the fruit's physical progress
        (`RECEIVED`, `IN_DEGREENING`, `READY_TO_SORT`, `SORTED`, `CLOSED`),
        while `regulatory_status` tracks its compliance standing (`CLEAR`,
        `HELD`, `RELEASED`, `CONDEMNED`)." PRD §3.3: "Placing a hold moves the
        regulatory dimension `CLEAR` → `HELD`, and while a delivery is `HELD`
        its sort runs cannot be created, verified, or posted — those
        operations fail with `ERR_DELIVERY_REGULATORY_HOLD`."

        Design: Difficulty/non_linear_state_machine/delivery_parallel_dimensions_independent
        """
        scenario = setup_delivery_received(
            "PD1", gross_boxes=100,
            channel_specs=[juice_spec("JU-PD1", "HAMLIN")])
        delivery_id = scenario["delivery"]["id"]
        held = validate_success(api_client.hold_delivery(
            delivery_id, make_officer_headers("co-pd1")))
        assert held["regulatory_status"] == "HELD"
        assert held["processing_status"] == "RECEIVED", \
            "the hold touches only the regulatory dimension"
        resp = api_client.create_sort_run(
            {"delivery_id": delivery_id, "fancy_boxes": 90, "choice_boxes": 0,
             "standard_boxes": 0, "juice_boxes": 10, "cull_boxes": 0,
             "color_score": 8, "defect_pct": 5,
             "expected_delivery_version": held["version"]},
            make_operator_headers("op-pd1"))
        validate_error(resp, ApiErrorId.ERR_DELIVERY_REGULATORY_HOLD)

    def test_release_then_sort_settles_both_dimensions_independently(self, api):
        """PRD §3.3: "Releasing moves `HELD` → `RELEASED`." — a third
        regulatory value distinct from the original CLEAR — while the
        processing dimension still reads RECEIVED until a sort run advances it
        (PRD §3.5: creating the run moves a non-degreening delivery
        `RECEIVED` → `READY_TO_SORT`, and posting moves it to `SORTED`).

        Design: Difficulty/non_linear_state_machine/delivery_parallel_dimensions_independent
        """
        scenario = setup_delivery_received(
            "PD1B", gross_boxes=100,
            channel_specs=[juice_spec("JU-PD1B", "HAMLIN")])
        delivery_id = scenario["delivery"]["id"]
        validate_success(api_client.hold_delivery(
            delivery_id, make_officer_headers("co-pd1")))
        released = validate_success(api_client.release_delivery(
            delivery_id, make_officer_headers("co-pd1")))
        assert released["regulatory_status"] == "RELEASED"
        assert released["processing_status"] == "RECEIVED", \
            "release does not advance the processing dimension"
        run = sort_run_lifecycle(delivery_id, 90, 0, 0, 10, 0, 8, 5,
                                 operator_id="op-pd1", inspector_id="qi-pd1")
        assert run["status"] == "POSTED"
        final = get_delivery(delivery_id)
        assert final["processing_status"] == "SORTED"
        assert final["regulatory_status"] == "RELEASED"


class TestDeliveryCloseGate:
    def test_delivery_close_requires_priced_pool(self, api):
        """PRD §3.3: "a `LineOperator` moves a `SORTED` delivery to the
        terminal `CLOSED` once the delivery's pool has been priced — that is,
        the pool is in `PRICED` or `SETTLED`; while the pool is still in an
        earlier state the close fails with `ERR_POOL_NOT_ACCEPTING`." PRD
        §3.5: "The `fresh_eligible` flag is true exactly when `color_score` is
        at least 6, `defect_pct` is at most 20, and the delivery's regulatory
        status is `CLEAR` or `RELEASED`."

        Design: Corner/state_machines/delivery_close_requires_priced_pool
        """
        scenario = setup_posted_scenario(
            "SM4", gross_boxes=10, fancy_boxes=10, choice_boxes=0,
            standard_boxes=0, juice_boxes=0, cull_boxes=0,
            color_score=4, defect_pct=5, planned_boxes=50,
            channel_specs=[juice_spec("JU-SM4", "HAMLIN")])
        run = scenario["sort_run"]
        assert run["status"] == "POSTED"
        assert run["fresh_eligible"] is False, "color_score 4 < 6"
        # Not fresh-eligible: the entire fresh volume is juiced at 220/box.
        assert run["proceeds_cents"] == 2200
        assert run["ge_boxes"] == 11.5
        delivery_id = scenario["delivery"]["id"]
        assert get_delivery(delivery_id)["processing_status"] == "SORTED"
        # Close while the pool is still OPEN is refused.
        resp = api_client.close_delivery(delivery_id, make_operator_headers("op-sm4"))
        validate_error(resp, ApiErrorId.ERR_POOL_NOT_ACCEPTING)
        # Once the pool is PRICED the close succeeds.
        close_intake_and_set_price(scenario["pool"]["id"])
        closed = validate_success(api_client.close_delivery(
            delivery_id, make_operator_headers("op-sm4")))
        assert closed["processing_status"] == "CLOSED"


class TestTemporalBeatsFiscalPriority:
    def _setup_expired_maturity_suspended_grower(self, tag):
        """Assignment started while its maturity test was valid; the clock
        then advances past expiry and the grower is suspended."""
        set_clock("2026-07-30T12:00:00Z")
        grower = create_grower(f"GR-{tag}", "Temporal Fiscal Groves")
        grove = create_grove(grower["id"], "B1", "HAMLIN", 50, "POLK")
        record_maturity_test(grove["id"], sampled_at="2026-07-26T00:00:00Z",
                             inspector_id=f"qi-{tag}")
        create_pool("HAMLIN", "2026-07-27")
        crew = create_crew(f"CR-{tag}", 400)
        assignment = get_success_data(api_client.create_assignment(
            create_assignment_payload(crew["id"], grove["id"],
                                      "2026-07-30T06:00:00Z",
                                      "2026-08-01T06:00:00Z", 50), SUPERVISOR))
        get_success_data(api_client.start_assignment(assignment["id"], SUPERVISOR))
        # Now past the test's expiry (2026-07-31T00:00:00Z = sampled + 120h).
        set_clock("2026-08-01T00:00:01Z")
        get_success_data(api_client.suspend_grower(grower["id"], ACCOUNTANT))
        return grower, grove, assignment

    def test_temporal_vs_fiscal_delivery_create_error(self, api):
        """PRD §2.6: "a request that would fail checks in two different tiers
        is rejected with the error from the earlier tier, so a failure higher
        on the ladder is never masked by one lower down." Tier 11 temporal
        gates (`ERR_MATURITY_TEST_EXPIRED`) precede tier 12 fiscal gates
        (`ERR_GROWER_NOT_ACTIVE`): receiving against an expired maturity test
        for a suspended grower surfaces the temporal error.

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_delivery_create
        """
        grower, grove, assignment = \
            self._setup_expired_maturity_suspended_grower("PP2")
        resp = api_client.create_delivery(
            create_delivery_payload(grove["id"], assignment["id"], 10, 0),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_MATURITY_TEST_EXPIRED)

    def test_temporal_vs_fiscal_delivery_create_persists_nothing(self, api):
        """PRD §2.6: the rejected receive surfaces the tier-11 error and
        creates nothing (PRD §3.3 receiving is gated on "the full standing of
        the source"); the grower's suspension is untouched (PRD §3.1:
        "Suspending moves a grower `ACTIVE` → `SUSPENDED`").

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_delivery_create
        """
        grower, grove, assignment = \
            self._setup_expired_maturity_suspended_grower("PP2B")
        validate_error(api_client.create_delivery(
            create_delivery_payload(grove["id"], assignment["id"], 10, 0),
            SUPERVISOR), ApiErrorId.ERR_MATURITY_TEST_EXPIRED)
        rows, meta = validate_paginated(api_client.list_deliveries(
            ADMIN, params={"grove_id": grove["id"]}))
        assert meta["total_count"] == 0, "no delivery may be persisted"
        assert get_grower(grower["id"])["status"] == "SUSPENDED"


class TestSafetyBeatsTemporalPriority:
    def test_quarantine_safety_beats_maturity_temporal(self, api):
        """PRD §2.6: "a request that would fail checks in two different tiers
        is rejected with the error from the earlier tier". Tier 7 regulatory
        gates (`ERR_GROVE_QUARANTINED`) precede tier 11 temporal gates
        (`ERR_MATURITY_TEST_EXPIRED`): receiving from a quarantined grove
        whose maturity test has lapsed surfaces the quarantine error.

        Design: Corner/validations/quarantine_safety_beats_maturity_temporal
        """
        set_clock("2026-07-30T12:00:00Z")
        grower = create_grower("GR-V3", "Safety Temporal Groves")
        grove = create_grove(grower["id"], "B1", "HAMLIN", 50, "POLK")
        record_maturity_test(grove["id"], sampled_at="2026-07-26T00:00:00Z",
                             inspector_id="qi-v3")
        create_pool("HAMLIN", "2026-07-27")
        crew = create_crew("CR-V3", 400)
        assignment = get_success_data(api_client.create_assignment(
            create_assignment_payload(crew["id"], grove["id"],
                                      "2026-07-30T06:00:00Z",
                                      "2026-08-01T06:00:00Z", 50), SUPERVISOR))
        get_success_data(api_client.start_assignment(assignment["id"], SUPERVISOR))
        # Advance past the maturity expiry, then quarantine the grove.
        set_clock("2026-08-01T00:00:01Z")
        create_quarantine("GROVE", "CANKER", grove_id=grove["id"],
                          officer_id="co-v3")
        resp = api_client.create_delivery(
            create_delivery_payload(grove["id"], assignment["id"], 10, 0),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_GROVE_QUARANTINED)


class TestCloseIntakeGate:
    def test_pool_close_intake_blocked_and_condemned_excluded(self, api):
        """PRD §3.6: "Closing intake moves the pool `OPEN` → `INTAKE_CLOSED`
        and requires that no delivery assigned to the pool remains unfinished:
        a delivery with `processing_status` `RECEIVED`, `IN_DEGREENING`, or
        `READY_TO_SORT` and a regulatory status other than `CONDEMNED` blocks
        the close with `ERR_POOL_HAS_OPEN_DELIVERIES`." PRD §3.3:
        "condemnation auto-voids any sort run of the delivery that is `OPEN`
        or `VERIFIED`".

        Design: Corner/state_machines/pool_close_intake_blocked_and_condemned_excluded
        """
        scenario = setup_delivery_received("SM7", gross_boxes=10)
        delivery_id = scenario["delivery"]["id"]
        run = sort_run_lifecycle(delivery_id, 10, 0, 0, 0, 0, 8, 5,
                                 operator_id="op-sm7", inspector_id="qi-sm7",
                                 stop_at="verified")
        pool_id = scenario["pool"]["id"]
        # The verified-but-unposted delivery blocks the intake close.
        resp = api_client.close_pool_intake(pool_id, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_POOL_HAS_OPEN_DELIVERIES)
        # Condemn the delivery: its VERIFIED run is auto-voided.
        validate_success(api_client.hold_delivery(
            delivery_id, make_officer_headers("co-sm7")))
        condemned = validate_success(api_client.condemn_delivery(
            delivery_id, make_officer_headers("co-sm7")))
        assert condemned["regulatory_status"] == "CONDEMNED"
        assert get_sort_run(run["id"])["status"] == "VOIDED", \
            "the condemn cascade auto-voids the VERIFIED run"
        # Condemned fruit no longer blocks the intake close.
        closed = validate_success(api_client.close_pool_intake(pool_id, ACCOUNTANT))
        assert closed["status"] == "INTAKE_CLOSED"
