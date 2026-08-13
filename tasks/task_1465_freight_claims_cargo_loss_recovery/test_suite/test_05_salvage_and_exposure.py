"""Salvage dispositions and the claim net-exposure ledger: execution timing,
net-credit computation, event emission, derived-field reconciliation across
multiple postings, and clock-driven auto-execution."""
from test_helpers import (
    ApiErrorId,
    assert_salvage,
    create_salvage_payload,
    get_claim,
    get_success_data,
    set_clock,
    setup_claim_under_review,
    setup_claim_under_review_with_pending_salvage,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

SALVAGE = TEST_USERS["salvage_headers"]
CLERK = TEST_USERS["clerk_headers"]


class TestSalvageExecutionCascade:
    def test_salvage_execute_computes_net_credit_and_updates_claim(self, api):
        """PRD §3.5: "On execution the disposition's `net_credit_cents` is computed as its gross proceeds minus its handling cost, floored at zero; that credit is added to the claim's `salvage_credit_cents` — additively, and it may push the total credit past the computed liability, because the zero floor is applied separately on the exposure — and the claim's `net_exposure_cents` is recomputed."

        Design: Difficulty/transitive_cascade/salvage_execute_cascade_depth2
        """
        # The disposition is scheduled while the claim is ACKNOWLEDGED and the
        # clock crosses scheduled_at before the claim reaches UNDER_REVIEW, so
        # the §2.7 sweep cannot pre-empt the manual execution under test.
        ctx = setup_claim_under_review_with_pending_salvage(
            salvage_specs=[{
                "gross_proceeds_cents": 12_000,
                "handling_cost_cents": 2_000,
                "scheduled_at": "2026-06-15T00:00:00Z",
            }],
            advance_clock_to="2026-06-15T00:00:01Z",
        )  # computed liability 40_000
        claim_id = ctx["claim"]["id"]
        salvage = ctx["salvage_list"][0]
        executed = validate_success(
            api.execute_salvage(claim_id, salvage["id"], SALVAGE), 200
        )
        assert_salvage(executed)
        assert executed["state"] == "EXECUTED"
        assert executed["net_credit_cents"] == 10_000  # max(12_000 - 2_000, 0)
        claim = get_claim(claim_id)
        assert claim["salvage_credit_cents"] == 10_000
        assert claim["net_exposure_cents"] == 30_000  # max(40_000 - 10_000, 0)

    def test_salvage_execute_appends_event_and_bumps_version(self, api):
        """PRD §3.5: "On execution the disposition's `net_credit_cents` is computed as its gross proceeds minus its handling cost, floored at zero; that credit is added to the claim's `salvage_credit_cents` — additively, and it may push the total credit past the computed liability, because the zero floor is applied separately on the exposure — and the claim's `net_exposure_cents` is recomputed. A `SALVAGE_POSTED` event is appended and the claim's `version` increments."

        Design: Difficulty/transitive_cascade/salvage_execute_cascade_depth2
        """
        # Same scheduling window as above: the §2.7 sweep skips the disposition
        # while the claim is ACKNOWLEDGED, so the manual execute drives the
        # SCHEDULED -> EXECUTED transition.
        ctx = setup_claim_under_review_with_pending_salvage(
            salvage_specs=[{
                "gross_proceeds_cents": 12_000,
                "handling_cost_cents": 2_000,
                "scheduled_at": "2026-06-15T00:00:00Z",
            }],
            advance_clock_to="2026-06-15T00:00:01Z",
        )
        claim_id = ctx["claim"]["id"]
        salvage = ctx["salvage_list"][0]
        version_before = ctx["claim"]["version"]
        validate_success(api.execute_salvage(claim_id, salvage["id"], SALVAGE), 200)
        claim = get_claim(claim_id)
        assert claim["version"] > version_before, (
            "Salvage execution must increment the claim's version"
        )
        events, _meta = validate_paginated(
            api.list_claim_events(claim_id, CLERK, params={"event_kind": "SALVAGE_POSTED"})
        )
        assert len(events) >= 1, "SALVAGE_POSTED event must be appended"


class TestSalvageTiming:
    def test_salvage_execute_before_scheduled_time_rejected(self, api):
        """PRD §3.5: "Execution — performed by a `SalvageCoordinator`, or by the system itself once the logical clock reaches `scheduled_at` — requires the disposition still be `SCHEDULED` (otherwise `ERR_SALVAGE_INVALID_STATE`), the logical time be at or past `scheduled_at` (otherwise `ERR_SALVAGE_NOT_YET_DUE`), and the claim be in `UNDER_REVIEW`, `OFFERED`, `DECLINED`, or `APPEALED` (otherwise `ERR_CLAIM_INVALID_STATE`)."

        Design: Difficulty/resource_temporal_overlap/salvage_execute_before_scheduled_at_rejected
        """
        ctx = setup_claim_under_review()
        claim_id = ctx["claim"]["id"]
        salvage = get_success_data(
            api.schedule_salvage(
                claim_id,
                create_salvage_payload(
                    gross_proceeds_cents=5_000,
                    handling_cost_cents=500,
                    scheduled_at="2026-06-20T00:00:00Z",
                ),
                SALVAGE,
            )
        )
        set_clock("2026-06-15T00:00:00Z")  # before scheduled_at
        resp = api.execute_salvage(claim_id, salvage["id"], SALVAGE)
        validate_error(resp, ApiErrorId.ERR_SALVAGE_NOT_YET_DUE)

    def test_salvage_execute_at_scheduled_time_succeeds(self, api):
        """PRD §3.5: "Execution — performed by a `SalvageCoordinator`, or by the system itself once the logical clock reaches `scheduled_at` — requires the disposition still be `SCHEDULED` (otherwise `ERR_SALVAGE_INVALID_STATE`), the logical time be at or past `scheduled_at` (otherwise `ERR_SALVAGE_NOT_YET_DUE`), and the claim be in `UNDER_REVIEW`, `OFFERED`, `DECLINED`, or `APPEALED` (otherwise `ERR_CLAIM_INVALID_STATE`)."

        Design: Difficulty/resource_temporal_overlap/salvage_execute_before_scheduled_at_rejected
        """
        # The clock lands exactly at scheduled_at while the claim is still
        # ACKNOWLEDGED, so the §2.7 sweep leaves the disposition SCHEDULED;
        # once the claim reaches UNDER_REVIEW (no further clock advance), a
        # manual execute at exactly scheduled_at exercises the inclusive
        # "at or past" boundary.
        ctx = setup_claim_under_review_with_pending_salvage(
            salvage_specs=[{
                "gross_proceeds_cents": 5_000,
                "handling_cost_cents": 500,
                "scheduled_at": "2026-06-20T00:00:00Z",
            }],
            advance_clock_to="2026-06-20T00:00:00Z",
        )
        claim_id = ctx["claim"]["id"]
        salvage = ctx["salvage_list"][0]
        executed = validate_success(
            api.execute_salvage(claim_id, salvage["id"], SALVAGE), 200
        )
        assert executed["state"] == "EXECUTED"


class TestNetExposureReconciliation:
    def test_net_exposure_reconciles_across_sequential_salvage(self, api):
        """PRD §3.5: "A claim's `net_exposure_cents` is the thread that ties this section together: it is always the claim's `computed_liability_cents` minus its accumulated `salvage_credit_cents`, floored at zero, and it is recomputed on every assessment and on every salvage posting."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_net_exposure
        """
        # Both dispositions are scheduled while the claim is ACKNOWLEDGED so
        # the §2.7 sweep at the clock advance leaves both SCHEDULED; the two
        # sequential manual executions then drive the additive accumulation.
        ctx = setup_claim_under_review_with_pending_salvage(
            salvage_specs=[
                {
                    "gross_proceeds_cents": 5_000,
                    "handling_cost_cents": 500,
                    "scheduled_at": "2026-06-11T00:00:00Z",
                },
                {
                    "disposition_kind": "RETURN_TO_SHIPPER",
                    "gross_proceeds_cents": 3_000,
                    "handling_cost_cents": 200,
                    "scheduled_at": "2026-06-13T00:00:00Z",
                },
            ],
            advance_clock_to="2026-06-14T00:00:00Z",
        )  # computed liability 40_000
        claim_id = ctx["claim"]["id"]
        salvage1, salvage2 = ctx["salvage_list"]
        get_success_data(api.execute_salvage(claim_id, salvage1["id"], SALVAGE))
        get_success_data(api.execute_salvage(claim_id, salvage2["id"], SALVAGE))
        claim = get_claim(claim_id)
        # Credits accumulate additively: 4_500 + 2_800 = 7_300.
        assert claim["salvage_credit_cents"] == 7_300
        assert claim["net_exposure_cents"] == 32_700  # max(40_000 - 7_300, 0)


class TestScheduledSalvageExecution:
    def test_salvage_auto_executes_when_clock_reaches_scheduled_at(self, api):
        """PRD §2.7: "Fourth, salvage execution: a disposition whose `scheduled_at` has been reached is executed by the system exactly as if a coordinator had executed it by hand."

        Design: Corner/cross_cutting_layers/scheduled_action_salvage_auto_execute
        """
        ctx = setup_claim_under_review()
        claim_id = ctx["claim"]["id"]
        salvage = get_success_data(
            api.schedule_salvage(
                claim_id,
                create_salvage_payload(
                    gross_proceeds_cents=5_000,
                    handling_cost_cents=500,
                    scheduled_at="2026-06-15T00:00:00Z",
                ),
                SALVAGE,
            )
        )
        assert salvage["state"] == "SCHEDULED"
        set_clock("2026-06-20T00:00:00Z")  # past scheduled_at
        after = validate_success(api.get_salvage(claim_id, salvage["id"], CLERK), 200)
        assert after["state"] == "EXECUTED", (
            "Clock advance past scheduled_at must drive the system execution"
        )
        claim = get_claim(claim_id)
        assert claim["salvage_credit_cents"] == 4_500
