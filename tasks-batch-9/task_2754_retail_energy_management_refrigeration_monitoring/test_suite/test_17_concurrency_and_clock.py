"""Expected-version guards, the scheduled-action sweep and immediate visibility."""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_bms_gateway_headers,
    make_energy_manager_headers,
    make_maintenance_tech_headers,
)

COLD_DRAFT = {
    "climate_zone": "COLD",
    "store_format": "EXPRESS",
    "season": "WINTER",
    "cooling_setpoint_f": 72.0,
    "heating_setpoint_f": 66.0,
    "deadband_f": 2.0,
    "lighting_lux_target": 600,
}


def _store_activated_after_the_client_read_version_one(api):
    """A store created at version 1, commissioned to 2 and activated to 3, while
    the client still holds the version-1 token it read at creation."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-OC")
    standard = fx.create_published_standard(api)
    commissioned = fx.commission_store(api, store["id"], standard["id"], store["version"])
    activated = fx.activate_store_bms(api, store["id"])
    return {
        "store_id": store["id"],
        "standard_id": standard["id"],
        "version_at_creation": store["version"],
        "commissioned": commissioned,
        "activated": activated,
    }


class TestCommissioningRejectsAViewThatPredatesTheActivation:
    def test_the_activation_advanced_the_version_the_client_never_saw(self, api):
        """Replaying the version-1 token is refused and writes nothing.

        The PRD states: "A commissioning request must carry
        `expected_store_version`, a non-optional field holding the client's last
        observed `version` of the target store. If that value does not equal the
        store's current `version` — because another commissioning, a posture
        recomputation, or a cascade has advanced it since the client read the
        store — the request is rejected with `ERR_STALE_STORE_VERSION` (HTTP 412)
        and nothing is written."

        Design: Corner/cross_cutting_complexity_layers/occ_store_commissioning_rejects_a_view_that_predates_the_activation
        """
        ctx = _store_activated_after_the_client_read_version_one(api)
        assert ctx["version_at_creation"] == 1
        assert ctx["commissioned"]["version"] == 2
        assert ctx["commissioned"]["bms_status"] == "COMMISSIONING"
        assert ctx["activated"]["version"] == 3
        assert ctx["activated"]["bms_status"] == "ACTIVE"

        validate_error(
            api.commission_bms(
                ctx["store_id"],
                f.commission_bms_payload(ctx["standard_id"], ctx["version_at_creation"]),
                fx.MANAGER,
            ),
            ApiErrorId.ERR_STALE_STORE_VERSION,
            412,
        )

        store = fx.read_store(api, ctx["store_id"])
        assert store["bms_status"] == "ACTIVE"
        assert store["version"] == 3
        assert store["active_standard_id"] == ctx["standard_id"]

    def test_the_current_token_re_standardises_and_the_replay_hits_the_state_gate(self, api):
        """Re-commissioning from ACTIVE is legal; replaying the token is refused.

        The PRD states: "Two write operations in this system are legitimate to
        repeat: a store may be re-commissioned against a different setpoint
        standard at any time, and a tariff switch may be re-scheduled over a
        pending one."

        The replay lands on a store that is now mid-commissioning, and the PRD
        fixes which of the two competing refusals wins: "State admissibility
        outranks stale-view protection, so a commissioning attempt against a
        store already mid-commissioning is reported as `ERR_BMS_STATE_INVALID`
        even when the supplied version is also stale."

        Design: Corner/cross_cutting_complexity_layers/occ_store_commissioning_rejects_a_view_that_predates_the_activation
        """
        ctx = _store_activated_after_the_client_read_version_one(api)

        recommissioned = validate_success(
            api.commission_bms(
                ctx["store_id"],
                f.commission_bms_payload(ctx["standard_id"], 3),
                fx.MANAGER,
            )
        )

        assert recommissioned["bms_status"] == "COMMISSIONING"
        assert recommissioned["version"] == 4

        validate_error(
            api.commission_bms(
                ctx["store_id"],
                f.commission_bms_payload(ctx["standard_id"], 3),
                fx.MANAGER,
            ),
            ApiErrorId.ERR_BMS_STATE_INVALID,
            409,
        )
        assert fx.read_store(api, ctx["store_id"])["version"] == 4

    def test_a_token_from_the_future_is_a_mismatch_too(self, api):
        """The check is equality, not an ordering comparison.

        The PRD states: "If that value does not equal the store's current
        `version` — because another commissioning, a posture recomputation, or a
        cascade has advanced it since the client read the store — the request is
        rejected with `ERR_STALE_STORE_VERSION` (HTTP 412) and nothing is
        written."

        Design: Corner/cross_cutting_complexity_layers/occ_store_commissioning_rejects_a_view_that_predates_the_activation
        """
        ctx = _store_activated_after_the_client_read_version_one(api)

        validate_error(
            api.commission_bms(
                ctx["store_id"], f.commission_bms_payload(ctx["standard_id"], 99), fx.MANAGER
            ),
            ApiErrorId.ERR_STALE_STORE_VERSION,
            412,
        )

        store = fx.read_store(api, ctx["store_id"])
        assert store["version"] == 3
        assert store["bms_status"] == "ACTIVE"

    def test_existence_precedes_and_the_referential_gate_follows_the_stale_check(self, api):
        """An unknown store is a 404; an unpublished standard is still a 412.

        The PRD states: "Checks are therefore evaluated in a single global order,
        and the **first** violated check determines the response; later checks are
        never reached and never reported." — with "4. Existence of every
        referenced resource, in the family order given in §2.6." ahead of
        "8. Stale-view protection — `ERR_STALE_STORE_VERSION`, then
        `ERR_STALE_ACCOUNT_VERSION`." and that in turn ahead of
        "10. Referential business gates — `ERR_STANDARD_NOT_PUBLISHED`, then
        `ERR_STANDARD_SCOPE_MISMATCH`, then `ERR_BMS_NOT_COMMISSIONED`, then
        `ERR_DR_ENROLLMENT_SUSPENDED`, then `ERR_TARIFF_SWITCH_IN_PROGRESS`."

        Design: Corner/cross_cutting_complexity_layers/occ_store_commissioning_rejects_a_view_that_predates_the_activation
        """
        ctx = _store_activated_after_the_client_read_version_one(api)
        draft = fx.create_standard(api, **COLD_DRAFT)

        validate_error(
            api.commission_bms(
                ctx["store_id"], f.commission_bms_payload(draft["id"], 1), fx.MANAGER
            ),
            ApiErrorId.ERR_STALE_STORE_VERSION,
            412,
        )
        validate_error(
            api.commission_bms(
                NON_EXISTENT_UUID,
                f.commission_bms_payload(ctx["standard_id"], 1),
                fx.MANAGER,
            ),
            ApiErrorId.ERR_STORE_NOT_FOUND,
            404,
        )

        assert get_success_data(api.get_setpoint_standard(draft["id"], fx.MANAGER))[
            "status"
        ] == "DRAFT"
        assert fx.read_store(api, ctx["store_id"])["version"] == 3


EXPENSIVE_CANDIDATE = {
    "candidate_rate_schedule_code": "GS-4",
    "candidate_rate_family": "TOU_DEMAND",
    "candidate_demand_charge_per_kw": 20.00,
    "candidate_rate_on_peak": 0.2000,
    "candidate_rate_off_peak": 0.1200,
}


def _account_whose_switch_is_already_pending(api):
    """A validated bill, a cheaper candidate tariff and one switch already
    scheduled for 2026-09-01, which took the account to version 2."""
    ctx = fx.setup_validated_bill(api, account_overrides=f.candidate_tariff_fields())
    ctx["version_at_creation"] = ctx["account"]["version"]
    ctx["scheduled"] = validate_success(
        api.tariff_switch(
            ctx["account_id"],
            f.tariff_switch_payload("2026-09-01T00:00:00Z", ctx["version_at_creation"]),
            make_energy_manager_headers("u_mgr_oa"),
        )
    )
    return ctx


class TestTariffSwitchRejectsAViewThatPredatesThePendingSwitch:
    def test_a_second_writer_replaying_the_creation_token_cannot_overwrite(self, api):
        """The pending switch survives the stale supersession attempt.

        The PRD states: "Similarly, a tariff-switch request must carry
        `expected_utility_account_version` holding the client's last observed
        `version` of the target utility account; a mismatch against the account's
        current `version` is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP
        412)."

        Design: Corner/cross_cutting_complexity_layers/occ_tariff_switch_rejects_a_view_that_predates_the_pending_switch
        """
        ctx = _account_whose_switch_is_already_pending(api)
        assert ctx["bill"]["validation_state"] == "VALIDATED"
        assert ctx["version_at_creation"] == 1
        assert ctx["scheduled"]["version"] == 2
        assert ctx["scheduled"]["tariff_state"] == "PENDING_SWITCH"
        assert ctx["scheduled"]["tariff_switch_effective_from_iso"].startswith(
            "2026-09-01T00:00:00"
        )

        validate_error(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-10-01T00:00:00Z", 1),
                make_energy_manager_headers("u_mgr_second"),
            ),
            ApiErrorId.ERR_STALE_ACCOUNT_VERSION,
            412,
        )

        account = fx.read_account(api, ctx["account_id"])
        assert account["tariff_switch_effective_from_iso"].startswith("2026-09-01T00:00:00")
        assert account["tariff_state"] == "PENDING_SWITCH"
        assert account["version"] == 2

    def test_the_current_token_supersedes_the_pending_switch_legitimately(self, api):
        """Superseding is a write with no state precondition to fail.

        The PRD states: "Crucially, scheduling a switch on an account that is
        *already* `PENDING_SWITCH` is a legitimate operation: it supersedes the
        pending switch by overwriting the same two fields."

        Design: Corner/cross_cutting_complexity_layers/occ_tariff_switch_rejects_a_view_that_predates_the_pending_switch
        """
        ctx = _account_whose_switch_is_already_pending(api)

        superseded = validate_success(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-10-01T00:00:00Z", 2),
                make_energy_manager_headers("u_mgr_second"),
            )
        )

        assert superseded["tariff_state"] == "PENDING_SWITCH"
        assert superseded["tariff_switch_effective_from_iso"].startswith(
            "2026-10-01T00:00:00"
        )
        assert superseded["version"] == 3
        assert superseded["tariff_locked_until_iso"] is None

    def test_the_stale_check_precedes_the_timing_gate(self, api):
        """A stale token beats an instantaneous effective date.

        The PRD states: "Three business gates apply after the stale-view check,
        in order. First, timing: the request is refused with
        `ERR_TARIFF_LOCK_ACTIVE` (HTTP 409) when the logical clock is still before
        the account's `tariff_locked_until_iso`, and with the same code when
        `effective_from_iso` is not strictly after the clock — a switch cannot be
        backdated or made instantaneous."

        Design: Corner/cross_cutting_complexity_layers/occ_tariff_switch_rejects_a_view_that_predates_the_pending_switch
        """
        ctx = _account_whose_switch_is_already_pending(api)

        validate_error(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-08-01T00:00:00Z", 1),
                make_energy_manager_headers("u_mgr_second"),
            ),
            ApiErrorId.ERR_STALE_ACCOUNT_VERSION,
            412,
        )
        validate_error(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-08-01T00:00:00Z", 2),
                make_energy_manager_headers("u_mgr_second"),
            ),
            ApiErrorId.ERR_TARIFF_LOCK_ACTIVE,
            409,
        )

        assert fx.read_account(api, ctx["account_id"])["version"] == 2

    def test_the_stale_check_precedes_the_justification_gate(self, api):
        """A mismatched token beats an unjustifiable candidate tariff.

        The PRD states: "Second, justification: the projection above is
        evaluated, and a request whose `switch_recommended` is false is refused
        with `ERR_TARIFF_SWITCH_NOT_JUSTIFIED` (HTTP 422). The same refusal
        applies when the account has no validated or adjusted reference bill, and
        when any of the five candidate fields is null, because in either case
        there is nothing to justify the move with."

        Design: Corner/cross_cutting_complexity_layers/occ_tariff_switch_rejects_a_view_that_predates_the_pending_switch
        """
        _account_whose_switch_is_already_pending(api)
        other_store = fx.create_store(api, code="STR-OA2", floor_area_sqft=118000)
        other = fx.create_account(
            api, other_store["id"], rate_schedule_code="GS-7", **EXPENSIVE_CANDIDATE
        )
        assert other["version"] == 1

        validate_error(
            api.tariff_switch(
                other["id"],
                f.tariff_switch_payload("2026-09-01T00:00:00Z", 1),
                make_energy_manager_headers("u_mgr_second"),
            ),
            ApiErrorId.ERR_TARIFF_SWITCH_NOT_JUSTIFIED,
            422,
        )
        validate_error(
            api.tariff_switch(
                other["id"],
                f.tariff_switch_payload("2026-09-01T00:00:00Z", 99),
                make_energy_manager_headers("u_mgr_second"),
            ),
            ApiErrorId.ERR_STALE_ACCOUNT_VERSION,
            412,
        )

        account = fx.read_account(api, other["id"])
        assert account["tariff_state"] == "STABLE"
        assert account["version"] == 1


NIGHT_WINDOW = {
    "zone": "SALES_FLOOR",
    "override_type": "SCHEDULE_EXTEND",
    "start_iso": "2026-08-02T02:00:00Z",
    "end_iso": "2026-08-02T08:00:00Z",
    "zone_load_kw": 20.0,
    "requested_reason": "overnight restock",
}


def _store_with_a_scheduled_override_and_a_notified_event(api):
    """An activated store holding a future override window and an account whose
    event has been notified for the following morning."""
    ctx = fx.setup_commissioned_store(api, code="STR-SW")
    account = fx.create_account(api, ctx["store_id"])
    fx.ingest_intervals(
        api, account["id"], [f.demand_interval("2026-07-15T14:00:00Z", 1200.0, True)]
    )
    ctx["account_id"] = account["id"]
    ctx["override"] = fx.create_override(api, ctx["store_id"], **NIGHT_WINDOW)
    ctx["override_id"] = ctx["override"]["id"]
    event = fx.create_event(
        api,
        account["id"],
        program_code="DR-SW",
        curtailment_start_iso="2026-08-02T10:00:00Z",
        curtailment_end_iso="2026-08-02T12:00:00Z",
        target_reduction_kw=200.0,
    )
    ctx["event_id"] = event["id"]
    ctx["notified"] = fx.notify_event(api, event["id"])
    return ctx


class TestTheClockSweepActivatesExpiresAndCompletesThenReportsZeros:
    def test_the_first_advance_activates_the_override_and_counts_only_that(self, api):
        """The sweep reports exactly which rows moved.

        The PRD states: "A `PlatformAdmin` may move it forward by supplying a
        `current_utc` instant to the clock-control capability, which both sets the
        clock and runs the scheduled-action sweep in a fixed order: first, every
        demand-response event whose participation dimension is `ACTIVE` and whose
        curtailment end instant is at or before the new clock value is completed;
        second, every lighting override sitting in `SCHEDULED` whose window now
        contains the new clock value is activated; third, every lighting override
        in `SCHEDULED` or `ACTIVE` whose window has ended at or before the new
        clock value is expired; fourth, every store touched by any of the first
        three steps recomputes its energy posture."

        Design: Corner/cross_cutting_complexity_layers/the_clock_sweep_activates_expires_and_completes_then_reports_zeros
        """
        ctx = _store_with_a_scheduled_override_and_a_notified_event(api)
        assert ctx["override"]["state"] == "SCHEDULED"
        assert ctx["override"]["projected_kwh"] == pytest.approx(120.00, abs=0.01)
        assert fx.read_store(api, ctx["store_id"])[
            "override_kwh_used_month"
        ] == pytest.approx(120.0, abs=0.01)

        sweep = fx.set_clock(api, "2026-08-02T03:00:00Z")

        assert sweep["overrides_activated"] == 1
        assert sweep["overrides_expired"] == 0
        assert sweep["dr_events_completed"] == 0
        assert sweep["stores_posture_recomputed"] == 1

        overrides, _ = fx.list_overrides(api, ctx["store_id"])
        assert fx.find_row(overrides, ctx["override_id"])["state"] == "ACTIVE"
        assert fx.read_store(api, ctx["store_id"])[
            "override_kwh_used_month"
        ] == pytest.approx(120.0, abs=0.01)

    def test_expiry_keeps_the_projection_charged_unlike_revocation(self, api):
        """The second advance expires the window and the budget stays spent.

        The PRD states: "Note carefully which rows are counted: a merely
        scheduled override is charged exactly as a live one is, and an expired
        override stays charged for the remainder of its month, because the energy
        was actually spent."

        Design: Corner/cross_cutting_complexity_layers/the_clock_sweep_activates_expires_and_completes_then_reports_zeros
        """
        ctx = _store_with_a_scheduled_override_and_a_notified_event(api)
        fx.set_clock(api, "2026-08-02T03:00:00Z")

        sweep = fx.set_clock(api, "2026-08-02T10:00:00Z")

        assert sweep["overrides_activated"] == 0
        assert sweep["overrides_expired"] == 1

        overrides, _ = fx.list_overrides(api, ctx["store_id"])
        assert fx.find_row(overrides, ctx["override_id"])["state"] == "EXPIRED"
        assert fx.read_store(api, ctx["store_id"])[
            "override_kwh_used_month"
        ] == pytest.approx(120.0, abs=0.01)

    def test_the_sweep_completes_the_curtailment_and_then_reports_zeros(self, api):
        """One more advance completes the event; repeating it moves nothing.

        The PRD states: "The sweep is idempotent: setting the clock twice to the
        same instant reports zero for all four counters on the second call,
        because no row remains eligible."

        Design: Corner/cross_cutting_complexity_layers/the_clock_sweep_activates_expires_and_completes_then_reports_zeros
        """
        ctx = _store_with_a_scheduled_override_and_a_notified_event(api)
        fx.set_clock(api, "2026-08-02T03:00:00Z")
        fx.set_clock(api, "2026-08-02T10:00:00Z")
        activated = fx.activate_event(api, ctx["event_id"])
        assert activated["event_state"] == "ACTIVE"
        assert fx.read_store(api, ctx["store_id"])["energy_posture"] == "CURTAILED"

        sweep = fx.set_clock(api, "2026-08-02T12:30:00Z")

        assert sweep["current_utc"].startswith("2026-08-02T12:30:00")
        assert sweep["dr_events_completed"] == 1
        assert sweep["overrides_expired"] == 0
        assert sweep["overrides_activated"] == 0
        assert sweep["stores_posture_recomputed"] == 1

        events, _ = fx.list_events(api, ctx["account_id"])
        event = fx.find_row(events, ctx["event_id"])
        assert event["event_state"] == "COMPLETED"
        assert event["settlement_state"] == "PENDING"
        assert fx.read_store(api, ctx["store_id"])["energy_posture"] == "NORMAL"

        again = fx.set_clock(api, "2026-08-02T12:30:00Z")
        assert again["dr_events_completed"] == 0
        assert again["overrides_activated"] == 0
        assert again["overrides_expired"] == 0
        assert again["stores_posture_recomputed"] == 0
        rows, _ = fx.list_events(api, ctx["account_id"])
        assert fx.find_row(rows, ctx["event_id"])["event_state"] == "COMPLETED"

    def test_a_jump_over_the_whole_window_expires_without_activating(self, api):
        """A still-scheduled override whose window has fully passed is expired.

        The PRD states: "From there the clock sweep drives the rest of the
        lifecycle: `SCHEDULED → ACTIVE` when the clock enters the window, and
        `SCHEDULED → EXPIRED` or `ACTIVE → EXPIRED` when the clock reaches or
        passes `end_iso`, with the projection remaining charged."

        Design: Corner/cross_cutting_complexity_layers/the_clock_sweep_activates_expires_and_completes_then_reports_zeros
        """
        ctx = fx.setup_commissioned_store(api, code="STR-SW2")
        override = fx.create_override(
            api,
            ctx["store_id"],
            **dict(
                NIGHT_WINDOW,
                start_iso="2026-08-03T02:00:00Z",
                end_iso="2026-08-03T08:00:00Z",
            ),
        )
        assert override["state"] == "SCHEDULED"

        sweep = fx.set_clock(api, "2026-08-03T09:00:00Z")

        assert sweep["overrides_activated"] == 0
        assert sweep["overrides_expired"] == 1

        overrides, _ = fx.list_overrides(api, ctx["store_id"])
        assert fx.find_row(overrides, override["id"])["state"] == "EXPIRED"
        assert fx.read_store(api, ctx["store_id"])[
            "override_kwh_used_month"
        ] == pytest.approx(120.0, abs=0.01)


CRITICAL_REFRIGERATION_FAULT = {
    "equipment_ref": "RACK-IM",
    "equipment_class": "REFRIGERATION",
    "fault_code": "COMP-TRIP",
    "severity": "CRITICAL",
    "occurrence_count": 5,
    "affected_load_kw": 60.0,
}


def _activated_store_with_two_proposals_and_a_capped_fault(api):
    """An activated store carrying two PROPOSED retrofit projects and one
    refrigeration fault whose score has hit the 100.0 cap."""
    ctx = fx.setup_commissioned_store(api, code="STR-IM")
    ctx["project_1"] = fx.create_retrofit(
        api, ctx["store_id"], proposer_user_id="u_analyst_rt", measure_type="CASE_DOORS"
    )
    ctx["project_2"] = fx.create_retrofit(
        api,
        ctx["store_id"],
        proposer_user_id="u_analyst_rt",
        measure_type="ECM_MOTORS",
        capex_usd=120000.00,
        projected_annual_savings_kwh=260000.00,
    )
    ctx["fault"] = fx.create_fault(
        api,
        ctx["store_id"],
        headers=make_bms_gateway_headers(ctx["store_id"]),
        **CRITICAL_REFRIGERATION_FAULT,
    )
    ctx["fault_id"] = ctx["fault"]["id"]
    return ctx


class TestTheTriageResponseAlreadyReflectsTheWholeCascade:
    def test_one_response_carries_all_four_links(self, api):
        """The triage response is post-cascade, not pre-cascade.

        The PRD states: "Triage reports the whole cascade back as `fault_id`,
        `fault_state`, `fault_score`, `work_order_id`, `work_order_priority`,
        `work_order_state`, `store_bms_status`, `store_energy_posture`,
        `urgent_work_order_count` and `escalated_retrofit_count`; on a suppression
        the three work-order fields are null."

        Design: Corner/consistency_model/the_triage_response_already_reflects_the_whole_cascade
        """
        ctx = _activated_store_with_two_proposals_and_a_capped_fault(api)
        assert ctx["store"]["bms_status"] == "ACTIVE"
        assert ctx["store"]["energy_posture"] == "NORMAL"
        assert ctx["project_1"]["escalated_review"] is False
        assert ctx["fault"]["fault_score"] == pytest.approx(100.0, abs=0.05)
        assert ctx["fault"]["state"] == "DETECTED"

        triage = validate_success(
            api.triage_fault(
                ctx["fault_id"],
                f.triage_payload("WORK_ORDER"),
                make_maintenance_tech_headers("u_tech_im"),
            )
        )

        assert triage["fault_id"] == ctx["fault_id"]
        assert triage["fault_state"] == "TRIAGED"
        assert triage["fault_score"] == pytest.approx(100.0, abs=0.05)
        assert triage["work_order_id"] is not None
        assert triage["work_order_priority"] == "URGENT"
        assert triage["work_order_state"] == "OPEN"
        assert triage["store_bms_status"] == "DEGRADED"
        assert triage["store_energy_posture"] == "CONSTRAINED"
        assert triage["urgent_work_order_count"] == 1
        assert triage["escalated_retrofit_count"] == 2

    def test_every_follow_up_read_agrees_with_that_single_response(self, api):
        """No second call is needed for the reads to converge.

        The PRD states: "The fourth link sets `escalated_review` to true on every
        retrofit project of that store still in `PROPOSED`."

        Design: Corner/consistency_model/the_triage_response_already_reflects_the_whole_cascade
        """
        ctx = _activated_store_with_two_proposals_and_a_capped_fault(api)

        triage = validate_success(
            api.triage_fault(
                ctx["fault_id"],
                f.triage_payload("WORK_ORDER"),
                make_maintenance_tech_headers("u_tech_im"),
            )
        )

        fault = get_success_data(api.get_fault_diagnostic(ctx["fault_id"], fx.TECH))
        orders, order_meta = fx.list_work_orders(api, ctx["fault_id"])
        store = fx.read_store(api, ctx["store_id"])
        escalated, escalated_meta = fx.list_projects(
            api, ctx["store_id"], escalated_review="true"
        )

        assert fault["state"] == "TRIAGED"
        assert fault["fault_score"] == pytest.approx(100.0, abs=0.05)
        assert order_meta["total_count"] == 1
        order = fx.find_row(orders, triage["work_order_id"])
        assert order["priority"] == "URGENT"
        assert order["state"] == "OPEN"
        assert store["bms_status"] == "DEGRADED"
        assert store["energy_posture"] == "CONSTRAINED"
        assert store["urgent_work_order_count"] == 1
        assert escalated_meta["total_count"] == 2
        for project_id in (ctx["project_1"]["id"], ctx["project_2"]["id"]):
            project = fx.find_row(escalated, project_id)
            assert project["state"] == "PROPOSED"
            assert project["priority_basis"] == "SIMPLE_PAYBACK"

    def test_the_cascades_writes_are_visible_to_the_concurrency_layer_at_once(self, api):
        """The store's own version advanced with the cascade.

        The PRD states: "When a cascade touches a parent that the caller did not
        name in the request — a store degraded because the standard it was bound
        to was superseded, for instance — that parent's `version` still advances
        and its `updated_at` still refreshes."

        Design: Corner/consistency_model/the_triage_response_already_reflects_the_whole_cascade
        """
        ctx = _activated_store_with_two_proposals_and_a_capped_fault(api)
        version_before_triage = ctx["store"]["version"]

        api.triage_fault(
            ctx["fault_id"],
            f.triage_payload("WORK_ORDER"),
            make_maintenance_tech_headers("u_tech_im"),
        )

        validate_error(
            api.commission_bms(
                ctx["store_id"],
                f.commission_bms_payload(ctx["standard_id"], version_before_triage),
                fx.MANAGER,
            ),
            ApiErrorId.ERR_STALE_STORE_VERSION,
            412,
        )
        assert fx.read_store(api, ctx["store_id"])["version"] > version_before_triage
