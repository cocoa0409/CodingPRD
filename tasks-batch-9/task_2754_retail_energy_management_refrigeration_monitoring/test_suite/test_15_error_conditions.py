"""Reachability of the declared error codes, and the boundaries that pick them."""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a, factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_energy_analyst_headers,
    make_energy_manager_headers,
    make_maintenance_tech_headers,
    make_store_manager_headers,
)


class TestEveryNotFoundFamilyReportsItsOwnCode:
    def test_eight_unknown_referents_yield_eight_distinct_codes(self, api):
        """Each entity family answers with its own 404 rather than a generic one.

        The PRD states: "Each entity family has its own not-found code, and when
        several could apply they are evaluated in this fixed order: store,
        setpoint standard, utility account, utility bill, demand-response event,
        refrigeration case, temperature excursion, lighting override, fault
        diagnostic, maintenance work order, retrofit project".

        Design: Corner/errors/every_remaining_not_found_code_is_reachable_on_its_own_path
        """
        fx.set_clock(api)

        account = api.get_utility_account(NON_EXISTENT_UUID, fx.ANALYST)
        bill = api.recompute_utility_bill(NON_EXISTENT_UUID, fx.ANALYST)
        event = api.notify_demand_response_event(NON_EXISTENT_UUID, fx.MANAGER)
        case = api.get_refrigeration_case(NON_EXISTENT_UUID, fx.OFFICER)
        override = api.revoke_lighting_override(NON_EXISTENT_UUID, fx.MANAGER)
        fault = api.triage_fault(
            NON_EXISTENT_UUID, f.triage_payload("WORK_ORDER"), fx.TECH
        )
        work_order = api.schedule_work_order(
            NON_EXISTENT_UUID,
            f.schedule_work_order_payload(
                "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z"
            ),
            fx.TECH,
        )
        project = api.approve_retrofit_project(
            NON_EXISTENT_UUID, f.approve_retrofit_payload("APPROVE"), fx.MANAGER
        )

        validate_error(account, ApiErrorId.ERR_ACCOUNT_NOT_FOUND, 404)
        validate_error(bill, ApiErrorId.ERR_BILL_NOT_FOUND, 404)
        validate_error(event, ApiErrorId.ERR_DR_EVENT_NOT_FOUND, 404)
        validate_error(case, ApiErrorId.ERR_CASE_NOT_FOUND, 404)
        validate_error(override, ApiErrorId.ERR_OVERRIDE_NOT_FOUND, 404)
        validate_error(fault, ApiErrorId.ERR_FAULT_NOT_FOUND, 404)
        validate_error(work_order, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND, 404)
        validate_error(project, ApiErrorId.ERR_RETROFIT_NOT_FOUND, 404)
        a.assert_envelope_meta(account.json())
        assert account.json()["meta"]["api_request_timestamp"].startswith(
            "2026-08-01T00:00:00"
        )

    def test_a_malformed_body_outranks_the_unknown_identifier(self, api):
        """Schema validity is checked before any referent is resolved.

        The PRD states: "Checks are therefore evaluated in a single global order,
        and the **first** violated check determines the response; later checks are
        never reached and never reported."

        Design: Corner/errors/every_remaining_not_found_code_is_reachable_on_its_own_path
        """
        fx.set_clock(api)

        bad_outcome = api.triage_fault(
            NON_EXISTENT_UUID, {"outcome": "CLOSE"}, fx.TECH
        )
        bad_window = api.schedule_work_order(
            NON_EXISTENT_UUID,
            f.schedule_work_order_payload(
                "2026-08-02T12:00:00Z", "2026-08-02T09:00:00Z"
            ),
            fx.TECH,
        )
        bad_decision = api.approve_retrofit_project(
            NON_EXISTENT_UUID, {"decision": "DEFER"}, fx.MANAGER
        )

        validate_error(bad_outcome, ApiErrorId.ERR_INVALID_REQUEST, 400)
        validate_error(bad_window, ApiErrorId.ERR_INVALID_REQUEST, 400)
        validate_error(bad_decision, ApiErrorId.ERR_INVALID_REQUEST, 400)


FAULT_AT_THE_CEILING = {
    "equipment_ref": "LTG-A",
    "equipment_class": "LIGHTING",
    "fault_code": "DRIVER-FAIL",
    "severity": "MAJOR",
    "occurrence_count": 2,
    "affected_load_kw": 2.0,
}
FAULT_BELOW_THE_CEILING = {
    "equipment_ref": "LTG-B",
    "equipment_class": "LIGHTING",
    "fault_code": "LAMP-OUT",
    "severity": "MINOR",
    "occurrence_count": 2,
    "affected_load_kw": 10.0,
}


def _two_lighting_faults_astride_the_suppression_ceiling(api):
    """Fault A scores exactly 50.0 and fault B scores 23.1; B is suppressed."""
    ctx = fx.setup_commissioned_store(api, code="STR-FS")
    fault_a = fx.create_fault(api, ctx["store_id"], **FAULT_AT_THE_CEILING)
    fault_b = fx.create_fault(api, ctx["store_id"], **FAULT_BELOW_THE_CEILING)
    ctx["fault_a"] = fault_a
    ctx["fault_b"] = fault_b
    ctx["suppressed_b"] = get_success_data(
        api.triage_fault(
            fault_b["id"], f.triage_payload("SUPPRESS"),
            make_maintenance_tech_headers("u_tech_fs"),
        )
    )
    return ctx


class TestSuppressionCeilingIsStrict:
    def test_a_score_of_exactly_fifty_may_not_be_suppressed(self, api):
        """The suppression gate excludes the boundary value.

        The PRD states: "A fault may be suppressed only when `fault_score` is
        strictly below 50.0, so a score of exactly 50.0 may not be suppressed."

        Design: Corner/errors/fault_suppression_is_forbidden_at_exactly_the_score_ceiling
        """
        ctx = _two_lighting_faults_astride_the_suppression_ceiling(api)
        assert ctx["fault_a"]["fault_score"] == pytest.approx(50.0, abs=0.05)
        assert ctx["fault_b"]["fault_score"] == pytest.approx(23.1, abs=0.05)
        assert ctx["suppressed_b"]["fault_state"] == "SUPPRESSED"
        assert ctx["suppressed_b"]["work_order_id"] is None

        response = api.triage_fault(
            ctx["fault_a"]["id"], f.triage_payload("SUPPRESS"),
            make_maintenance_tech_headers("u_tech_fs"),
        )

        validate_error(response, ApiErrorId.ERR_FAULT_SUPPRESSION_FORBIDDEN, 422)
        rows, meta = fx.list_faults(api, ctx["store_id"], state="DETECTED")
        assert fx.find_row(rows, ctx["fault_a"]["id"])["state"] == "DETECTED"
        assert meta["total_count"] == 1
        orders, order_meta = fx.list_work_orders(api, ctx["fault_a"]["id"])
        assert order_meta["total_count"] == 0
        assert orders == []

    def test_the_same_fault_is_admitted_for_a_routine_work_order(self, api):
        """Fifty points is below the urgency threshold but above suppression.

        The PRD states: "A work order raised from the fault is `URGENT` when
        `fault_score` is at or above 70.0 and `ROUTINE` otherwise, so a score of
        exactly 70.0 is urgent."

        Design: Corner/errors/fault_suppression_is_forbidden_at_exactly_the_score_ceiling
        """
        ctx = _two_lighting_faults_astride_the_suppression_ceiling(api)

        triaged = validate_success(
            api.triage_fault(
                ctx["fault_a"]["id"], f.triage_payload("WORK_ORDER"),
                make_maintenance_tech_headers("u_tech_fs"),
            )
        )

        assert triaged["fault_state"] == "TRIAGED"
        assert triaged["work_order_priority"] == "ROUTINE"
        assert triaged["work_order_state"] == "OPEN"
        assert triaged["store_bms_status"] == "ACTIVE"
        assert triaged["urgent_work_order_count"] == 0

    def test_triage_is_legal_only_from_detected(self, api):
        """A suppressed or already triaged fault refuses a second triage.

        The PRD states: "Triage is a `MaintenanceTech` decision expressed as an
        `outcome` of either `WORK_ORDER` or `SUPPRESS`, and it is legal only from
        `DETECTED` — a fault already `TRIAGED`, `SUPPRESSED` or `RESOLVED` yields
        `ERR_FAULT_STATE_INVALID`."

        Design: Corner/errors/fault_suppression_is_forbidden_at_exactly_the_score_ceiling
        """
        ctx = _two_lighting_faults_astride_the_suppression_ceiling(api)
        tech = make_maintenance_tech_headers("u_tech_fs")
        fx.triage_fault(api, ctx["fault_a"]["id"], "WORK_ORDER", headers=tech)

        from_suppressed = api.triage_fault(
            ctx["fault_b"]["id"], f.triage_payload("WORK_ORDER"), tech
        )
        from_triaged = api.triage_fault(
            ctx["fault_a"]["id"], f.triage_payload("WORK_ORDER"), tech
        )
        undeclared_outcome = api.triage_fault(
            ctx["fault_a"]["id"], {"outcome": "CLOSE"}, tech
        )

        validate_error(from_suppressed, ApiErrorId.ERR_FAULT_STATE_INVALID, 409)
        validate_error(from_triaged, ApiErrorId.ERR_FAULT_STATE_INVALID, 409)
        validate_error(undeclared_outcome, ApiErrorId.ERR_INVALID_REQUEST, 400)
        suppressed_orders, suppressed_meta = fx.list_work_orders(
            api, ctx["fault_b"]["id"]
        )
        assert suppressed_meta["total_count"] == 0
        assert suppressed_orders == []
        _, triaged_meta = fx.list_work_orders(api, ctx["fault_a"]["id"])
        assert triaged_meta["total_count"] == 1


DAIRY_CASE = {
    "case_code": "CASE-DP",
    "case_type": "MEDIUM_TEMP",
    "product_class": "DAIRY",
    "alarm_high_f": 41.0,
    "alarm_low_f": 28.0,
    "product_value_usd": 5200.00,
}
DISCARD_NOTE = "5200.00 USD of dairy destroyed, log 41-A"


def _excursion_under_a_discard_mandate(api):
    """Four hours of continuous exposure, so the mandate is DISCARD."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T09:00:00Z", code="STR-DP"
    )
    case = fx.create_case(api, ctx["store_id"], **DAIRY_CASE)
    ctx["case_id"] = case["id"]
    ctx["first"] = fx.post_reading(
        api, case["id"], ctx["store_id"], 43.0, "2026-08-01T04:00:00Z"
    )
    ctx["second"] = fx.post_reading(
        api, case["id"], ctx["store_id"], 43.0, "2026-08-01T04:15:00Z"
    )
    ctx["third"] = fx.post_reading(
        api, case["id"], ctx["store_id"], 43.5, "2026-08-01T08:00:00Z"
    )
    ctx["excursion_id"] = ctx["second"]["excursion_id"]
    return ctx


class TestDiscardMandateRemovesTheOfficersDiscretion:
    def test_a_retain_disposition_against_a_mandated_discard_is_refused(self, api):
        """Four hours of exposure mandates DISCARD and RETAIN is rejected.

        The PRD states: "Where the exposure ladder has already set
        `mandatory_disposition` to `DISCARD`, the documented `disposition` must be
        `DISCARD` as well; recording `RETAIN` against a mandated discard is
        refused with `ERR_DISPOSITION_MANDATE_VIOLATION` (HTTP 422)."

        Design: Corner/errors/discard_mandate_forbids_a_retain_disposition_and_closure_is_terminal
        """
        ctx = _excursion_under_a_discard_mandate(api)
        assert ctx["first"]["consecutive_breach_count"] == 1
        assert ctx["first"]["excursion_id"] is None
        assert ctx["second"]["excursion_state"] == "OPEN"
        assert ctx["second"]["exposure_minutes"] == 15
        assert ctx["third"]["excursion_state"] == "DISPOSITION_REQUIRED"
        assert ctx["third"]["exposure_minutes"] == 240
        assert ctx["third"]["mandatory_disposition"] == "DISCARD"
        assert ctx["third"]["peak_temp_f"] == pytest.approx(43.5, abs=0.05)
        assert ctx["third"]["store_energy_posture"] == "LOCKED"

        response = api.document_excursion_disposition(
            ctx["excursion_id"],
            f.document_disposition_payload(
                "RETAIN", "product still within spec by probe check"
            ),
            fx.OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_DISPOSITION_MANDATE_VIOLATION, 422)
        excursion = fx.read_excursion(api, ctx["excursion_id"])
        assert excursion["disposition"] is None
        assert excursion["corrective_action_note"] is None
        assert excursion["documented_by_user_id"] is None
        assert excursion["documented_at_iso"] is None

    def test_documenting_the_mandated_discard_then_closing_releases_the_store(self, api):
        """Documentation does not transition; closure rearms and unlocks.

        The PRD states: "Documentation is accepted in any state other than
        `CLOSED`, and it explicitly does **not** change the excursion's state — an
        excursion that was `DISPOSITION_REQUIRED` before documentation is still
        `DISPOSITION_REQUIRED` after it."

        Design: Corner/errors/discard_mandate_forbids_a_retain_disposition_and_closure_is_terminal
        """
        ctx = _excursion_under_a_discard_mandate(api)

        documented = validate_success(
            api.document_excursion_disposition(
                ctx["excursion_id"],
                f.document_disposition_payload("DISCARD", DISCARD_NOTE),
                fx.OFFICER,
            )
        )
        closed = validate_success(api.close_excursion(ctx["excursion_id"], fx.OFFICER))

        assert documented["state"] == "DISPOSITION_REQUIRED"
        assert documented["disposition"] == "DISCARD"
        assert documented["documented_at_iso"].startswith("2026-08-01T09:00:00")
        assert closed["state"] == "CLOSED"
        assert closed["closed_at_iso"].startswith("2026-08-01T09:00:00")
        case = validate_success(api.get_refrigeration_case(ctx["case_id"], fx.OFFICER))
        assert case["monitoring_state"] == "ARMED"
        assert case["consecutive_breach_count"] == 0
        store = fx.read_store(api, ctx["store_id"])
        assert store["energy_posture"] == "NORMAL"
        assert store["alarm_case_count"] == 0

    def test_a_closed_excursion_refuses_every_further_action(self, api):
        """Closure is terminal and the state code outranks the mandate code.

        The PRD states: "Closing anything already `CLOSED` is
        `ERR_EXCURSION_STATE_INVALID`."

        Design: Corner/errors/discard_mandate_forbids_a_retain_disposition_and_closure_is_terminal
        """
        ctx = _excursion_under_a_discard_mandate(api)
        get_success_data(
            api.document_excursion_disposition(
                ctx["excursion_id"],
                f.document_disposition_payload("DISCARD", DISCARD_NOTE),
                fx.OFFICER,
            )
        )
        get_success_data(api.close_excursion(ctx["excursion_id"], fx.OFFICER))

        acknowledged = api.acknowledge_excursion(
            ctx["excursion_id"], make_store_manager_headers(ctx["store_id"])
        )
        redocumented = api.document_excursion_disposition(
            ctx["excursion_id"],
            f.document_disposition_payload("RETAIN", "reversal"),
            fx.OFFICER,
        )
        reclosed = api.close_excursion(ctx["excursion_id"], fx.OFFICER)

        validate_error(acknowledged, ApiErrorId.ERR_EXCURSION_STATE_INVALID, 409)
        # The state check at rank seven precedes the mandate check.
        validate_error(redocumented, ApiErrorId.ERR_EXCURSION_STATE_INVALID, 409)
        validate_error(reclosed, ApiErrorId.ERR_EXCURSION_STATE_INVALID, 409)
        excursion = fx.read_excursion(api, ctx["excursion_id"])
        assert excursion["state"] == "CLOSED"
        assert excursion["disposition"] == "DISCARD"
        assert excursion["acknowledged_by_user_id"] is None


SU_EVENTS = [
    ("DR-A", "2026-08-20T14:00:00Z", "2026-08-20T16:00:00Z"),
    ("DR-B", "2026-08-20T21:00:00Z", "2026-08-20T23:00:00Z"),
    ("DR-C", "2026-08-21T04:00:00Z", "2026-08-21T06:00:00Z"),
]
SU_CASE = {
    "case_code": "CASE-SU",
    "case_type": "MEDIUM_TEMP",
    "product_class": "DAIRY",
    "alarm_high_f": 41.0,
    "alarm_low_f": 28.0,
    "product_value_usd": 3000.00,
}


def _account_holding_three_notified_events(api):
    """Three NOTIFIED events, each window separated by five hours, and a case one
    reading away from escalation."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T09:00:00Z", code="STR-SU"
    )
    account = fx.create_account(api, ctx["store_id"], utility_name="Statewide Power")
    ctx["account_id"] = account["id"]
    fx.ingest_intervals(
        api, account["id"], [f.demand_interval("2026-07-15T14:00:00Z", 1200.0, True)]
    )
    ctx["event_ids"] = []
    ctx["baselines"] = []
    for program_code, start_iso, end_iso in SU_EVENTS:
        event = fx.create_event(
            api, account["id"], program_code=program_code,
            curtailment_start_iso=start_iso, curtailment_end_iso=end_iso,
            target_reduction_kw=200.0,
        )
        notified = fx.notify_event(api, event["id"])
        ctx["event_ids"].append(event["id"])
        ctx["baselines"].append(notified["baseline_kw"])
    case = fx.create_case(api, ctx["store_id"], **SU_CASE)
    ctx["case_id"] = case["id"]
    fx.post_reading(api, case["id"], ctx["store_id"], 42.0, "2026-08-01T04:00:00Z")
    ctx["opening"] = fx.post_reading(
        api, case["id"], ctx["store_id"], 42.0, "2026-08-01T04:15:00Z"
    )
    return ctx


class TestThreeSystemOptOutsSuspendEnrollment:
    def test_one_escalating_reading_opts_out_all_three_events(self, api):
        """The cascade counts every notified event of the account in one request.

        The PRD states: "Each system opt-out increments the account's
        `dr_optout_count`, and as soon as that count reaches three the account's
        `dr_enrollment_state` becomes `SUSPENDED` — a store that keeps failing its
        cases out of curtailment events loses its place in the program."

        Design: Corner/errors/three_system_opt_outs_suspend_the_demand_response_enrollment
        """
        ctx = _account_holding_three_notified_events(api)
        assert ctx["baselines"] == pytest.approx([1200.00, 1200.00, 1200.00], abs=0.01)
        assert ctx["opening"]["excursion_state"] == "OPEN"
        assert ctx["opening"]["dr_events_opted_out"] == 0

        escalating = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 42.0, "2026-08-01T06:00:00Z"
        )

        assert escalating["excursion_state"] == "ESCALATED"
        assert escalating["exposure_minutes"] == 120
        assert escalating["dr_events_opted_out"] == 3
        assert escalating["store_energy_posture"] == "LOCKED"
        account = fx.read_account(api, ctx["account_id"])
        assert account["dr_optout_count"] == 3
        assert account["dr_enrollment_state"] == "SUSPENDED"
        rows, _ = fx.list_events(api, ctx["account_id"])
        for event_id in ctx["event_ids"]:
            row = fx.find_row(rows, event_id)
            assert row["event_state"] == "OPTED_OUT"
            assert row["opt_out_reason"] == "FOOD_SAFETY_POSTURE"

    def test_a_suspended_account_admits_no_new_enrollment(self, api):
        """Creation is gated on the enrollment posture.

        The PRD states: "Creation is refused with `ERR_DR_ENROLLMENT_SUSPENDED`
        when the account's `dr_enrollment_state` is `SUSPENDED`."

        Design: Corner/errors/three_system_opt_outs_suspend_the_demand_response_enrollment
        """
        ctx = _account_holding_three_notified_events(api)
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 42.0, "2026-08-01T06:00:00Z")

        response = api.create_demand_response_event(
            ctx["account_id"],
            f.create_demand_response_event_payload(
                program_code="DR-D",
                curtailment_start_iso="2026-08-25T14:00:00Z",
                curtailment_end_iso="2026-08-25T16:00:00Z",
                target_reduction_kw=200.0,
            ),
            make_energy_manager_headers("u_manager_su"),
        )

        validate_error(response, ApiErrorId.ERR_DR_ENROLLMENT_SUSPENDED, 409)
        _, meta = fx.list_events(api, ctx["account_id"])
        assert meta["total_count"] == 3

    def test_the_state_check_outranks_the_enrollment_gate_on_notify(self, api):
        """Notifying an opted-out event reports the event's own state code.

        The PRD states: "Notification requires `event_state` to be `SCHEDULED`
        (otherwise `ERR_DR_EVENT_STATE_INVALID`) and the account still to be
        `ENROLLED` (otherwise `ERR_DR_ENROLLMENT_SUSPENDED`)".

        Design: Corner/errors/three_system_opt_outs_suspend_the_demand_response_enrollment
        """
        ctx = _account_holding_three_notified_events(api)
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 42.0, "2026-08-01T06:00:00Z")

        response = api.notify_demand_response_event(
            ctx["event_ids"][0], make_energy_manager_headers("u_manager_su")
        )

        validate_error(response, ApiErrorId.ERR_DR_EVENT_STATE_INVALID, 409)
        rows, _ = fx.list_events(api, ctx["account_id"])
        assert fx.find_row(rows, ctx["event_ids"][0])["event_state"] == "OPTED_OUT"


NIGHT_OVERRIDE = {
    "zone": "SALES_FLOOR",
    "override_type": "SCHEDULE_EXTEND",
    "start_iso": "2026-08-01T00:00:00Z",
    "end_iso": "2026-08-01T06:00:00Z",
    "zone_load_kw": 25.0,
    "requested_reason": "inventory night",
}


def _store_with_one_active_override(api):
    """A 500.00 kWh allowance carrying a single 150.00 kWh live override."""
    ctx = fx.setup_commissioned_store(api, code="STR-OR", override_budget_kwh_month=500.0)
    override = fx.create_override(api, ctx["store_id"], **NIGHT_OVERRIDE)
    ctx["override_id"] = override["id"]
    ctx["override"] = override
    ctx["store_after_request"] = fx.read_store(api, ctx["store_id"])
    return ctx


class TestRevokingATwiceRevokedOverrideReleasesNothingTwice:
    def test_the_first_revocation_releases_the_projection(self, api):
        """A user revocation frees the charged kilowatt-hours.

        The PRD states: "An `EnergyManager` revoking an override moves it from
        `SCHEDULED` or `ACTIVE` to `REVOKED`, sets `revoke_source` to `USER`,
        records the acting operator in `revoked_by_user_id`, and releases the
        override's `projected_kwh` from the store's monthly usage."

        Design: Corner/errors/revoking_an_already_revoked_override_is_refused_and_releases_nothing_twice
        """
        ctx = _store_with_one_active_override(api)
        assert ctx["override"]["state"] == "ACTIVE"
        assert ctx["override"]["projected_kwh"] == pytest.approx(150.00, abs=0.01)
        assert ctx["store_after_request"]["override_kwh_used_month"] == pytest.approx(
            150.00, abs=0.01
        )

        revoked = validate_success(
            api.revoke_lighting_override(
                ctx["override_id"], make_energy_manager_headers("u_mgr_ov")
            )
        )

        assert revoked["state"] == "REVOKED"
        assert revoked["revoke_source"] == "USER"
        assert revoked["revoked_by_user_id"] == "u_mgr_ov"
        store = fx.read_store(api, ctx["store_id"])
        assert store["override_kwh_used_month"] == pytest.approx(0.00, abs=0.001)

    def test_the_second_revocation_is_refused_and_the_ledger_holds(self, api):
        """The monthly counter does not go negative.

        The PRD states: "Revoking an override that is already `EXPIRED` or
        `REVOKED` is refused with `ERR_OVERRIDE_STATE_INVALID` (HTTP 409)."

        Design: Corner/errors/revoking_an_already_revoked_override_is_refused_and_releases_nothing_twice
        """
        ctx = _store_with_one_active_override(api)
        fx.revoke_override(api, ctx["override_id"], manager_user_id="u_mgr_ov")

        response = api.revoke_lighting_override(
            ctx["override_id"], make_energy_manager_headers("u_mgr_ov")
        )

        validate_error(response, ApiErrorId.ERR_OVERRIDE_STATE_INVALID, 409)
        store = fx.read_store(api, ctx["store_id"])
        assert store["override_kwh_used_month"] == pytest.approx(0.00, abs=0.001)
        assert store["override_kwh_used_month"] >= 0.0
        rows, _ = fx.list_overrides(api, ctx["store_id"], state="REVOKED")
        assert fx.find_row(rows, ctx["override_id"])["revoke_source"] == "USER"

    def test_a_revoked_override_is_outside_the_sweeps_expiry_set(self, api):
        """The sweep expires nothing once the row has left SCHEDULED or ACTIVE.

        The PRD states: "third, every lighting override in `SCHEDULED` or `ACTIVE`
        whose window has ended at or before the new clock value is expired".

        Design: Corner/errors/revoking_an_already_revoked_override_is_refused_and_releases_nothing_twice
        """
        ctx = _store_with_one_active_override(api)
        fx.revoke_override(api, ctx["override_id"], manager_user_id="u_mgr_ov")

        sweep = fx.set_clock(api, "2026-08-01T07:00:00Z")
        response = api.revoke_lighting_override(
            ctx["override_id"], make_energy_manager_headers("u_mgr_ov")
        )

        assert sweep["overrides_expired"] == 0
        validate_error(response, ApiErrorId.ERR_OVERRIDE_STATE_INVALID, 409)
        store = fx.read_store(api, ctx["store_id"])
        assert store["override_kwh_used_month"] == pytest.approx(0.00, abs=0.001)

    def test_an_expired_override_keeps_its_charge_and_refuses_revocation(self, api):
        """Expiry is the other refused origin and it releases nothing.

        The PRD states: "a merely scheduled override is charged exactly as a live
        one is, and an expired override stays charged for the remainder of its
        month, because the energy was actually spent."

        Design: Corner/errors/revoking_an_already_revoked_override_is_refused_and_releases_nothing_twice
        """
        ctx = _store_with_one_active_override(api)

        sweep = fx.set_clock(api, "2026-08-01T07:00:00Z")
        response = api.revoke_lighting_override(
            ctx["override_id"], make_energy_manager_headers("u_mgr_ov")
        )

        assert sweep["overrides_expired"] == 1
        validate_error(response, ApiErrorId.ERR_OVERRIDE_STATE_INVALID, 409)
        rows, _ = fx.list_overrides(api, ctx["store_id"])
        override = fx.find_row(rows, ctx["override_id"])
        assert override["state"] == "EXPIRED"
        assert override["projected_kwh"] == pytest.approx(150.00, abs=0.01)
        assert override["revoked_by_user_id"] is None
        store = fx.read_store(api, ctx["store_id"])
        assert store["override_kwh_used_month"] == pytest.approx(150.00, abs=0.01)


def _completed_event_awaiting_settlement(api):
    """An event completed by the sweep whose settlement set is empty: the only
    interval of the account lies a month outside the curtailment window."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-ST")
    account = fx.create_account(api, store["id"], utility_name="Statewide Power")
    fx.ingest_intervals(
        api, account["id"], [f.demand_interval("2026-07-15T14:00:00Z", 1200.0, True)]
    )
    event = fx.create_event(
        api, account["id"], program_code="DR-S",
        curtailment_start_iso="2026-08-20T14:00:00Z",
        curtailment_end_iso="2026-08-20T16:00:00Z", target_reduction_kw=200.0,
    )
    fx.notify_event(api, event["id"])
    return {
        "store_id": store["id"],
        "account_id": account["id"],
        "event_id": event["id"],
    }


def _advance_to_completion(api, event_id):
    fx.set_clock(api, "2026-08-20T14:00:00Z")
    fx.activate_event(api, event_id)
    return fx.set_clock(api, "2026-08-20T16:30:00Z")


class TestSettlementActionsAreRefusedOutsideTheirState:
    def test_settling_before_the_participation_completes_is_refused(self, api):
        """The money dimension waits on the lifecycle dimension.

        The PRD states: "It requires `settlement_state` to be `PENDING` and
        `event_state` to be `COMPLETED` — settling an event whose participation has
        not completed, or settling one already settled, is
        `ERR_SETTLEMENT_STATE_INVALID`".

        Design: Corner/errors/settlement_actions_are_refused_outside_their_settlement_state
        """
        ctx = _completed_event_awaiting_settlement(api)

        response = api.settle_demand_response_event(
            ctx["event_id"], make_energy_analyst_headers("u_analyst_st")
        )

        validate_error(response, ApiErrorId.ERR_SETTLEMENT_STATE_INVALID, 409)
        rows, _ = fx.list_events(api, ctx["account_id"])
        event = fx.find_row(rows, ctx["event_id"])
        assert event["event_state"] == "NOTIFIED"
        assert event["settlement_state"] == "PENDING"

    def test_reversing_a_settlement_that_never_happened_is_refused(self, api):
        """Reversal requires a settled event, not merely a completed one.

        The PRD states: "Reversal requires the settlement to be `SETTLED`;
        reversing something still `PENDING` or already `REVERSED` is
        `ERR_SETTLEMENT_STATE_INVALID`."

        Design: Corner/errors/settlement_actions_are_refused_outside_their_settlement_state
        """
        ctx = _completed_event_awaiting_settlement(api)
        sweep = _advance_to_completion(api, ctx["event_id"])

        response = api.reverse_demand_response_settlement(
            ctx["event_id"], f.reversal_payload("utility recalculation"),
            make_energy_manager_headers("u_manager_st"),
        )

        assert sweep["dr_events_completed"] == 1
        validate_error(response, ApiErrorId.ERR_SETTLEMENT_STATE_INVALID, 409)
        rows, _ = fx.list_events(api, ctx["account_id"])
        event = fx.find_row(rows, ctx["event_id"])
        assert event["event_state"] == "COMPLETED"
        assert event["settlement_state"] == "PENDING"
        assert event["reversal_reason"] is None
        account = fx.read_account(api, ctx["account_id"])
        assert account["dr_incentive_accrued_usd"] == pytest.approx(0.00, abs=0.01)
        store = fx.read_store(api, ctx["store_id"])
        assert store["energy_posture"] == "NORMAL"

    def test_the_empty_settlement_settles_once_and_only_once(self, api):
        """A defined zero settlement still closes the money dimension.

        The PRD states: "Where the settlement set is empty the numbers are defined
        rather than undefined: `total_reduction_kwh` is 0.00, the obligation is
        0.00, `performance_pct` is 0.0 without any division being attempted, both
        money fields are 0.00, and the event settles normally."

        Design: Corner/errors/settlement_actions_are_refused_outside_their_settlement_state
        """
        ctx = _completed_event_awaiting_settlement(api)
        _advance_to_completion(api, ctx["event_id"])
        analyst = make_energy_analyst_headers("u_analyst_st")

        settled = validate_success(
            api.settle_demand_response_event(ctx["event_id"], analyst)
        )
        again = api.settle_demand_response_event(ctx["event_id"], analyst)

        assert settled["settlement_state"] == "SETTLED"
        assert settled["event_state"] == "COMPLETED"
        assert settled["total_reduction_kwh"] == pytest.approx(0.00, abs=0.01)
        assert settled["performance_pct"] == pytest.approx(0.0, abs=0.05)
        assert settled["incentive_usd"] == pytest.approx(0.00, abs=0.01)
        assert settled["penalty_usd"] == pytest.approx(0.00, abs=0.01)
        validate_error(again, ApiErrorId.ERR_SETTLEMENT_STATE_INVALID, 409)
        account = fx.read_account(api, ctx["account_id"])
        assert account["dr_incentive_accrued_usd"] == pytest.approx(0.00, abs=0.01)


SHORT_PERIOD = {
    "install_completed_iso": "2026-05-01T00:00:00Z",
    "baseline_period_kwh": 100000.00,
    "post_period_kwh": 30000.00,
    "mv_period_days": 59,
}
FUTURE_INSTALL = dict(SHORT_PERIOD, install_completed_iso="2026-09-01T00:00:00Z",
                      mv_period_days=90)
BOUNDARY_PERIOD = dict(SHORT_PERIOD, mv_period_days=60)


def _approved_project_awaiting_measurement(api):
    ctx = fx.setup_commissioned_store(api, code="STR-MV")
    project = fx.create_retrofit(
        api, ctx["store_id"], proposer_user_id="u_analyst_rt",
        measure_type="ECM_MOTORS", capex_usd=240240.00,
        projected_annual_savings_kwh=520000.00,
    )
    ctx["project_id"] = project["id"]
    ctx["approved"] = fx.decide_retrofit(
        api, project["id"], "APPROVE", approver_user_id="u_mgr_rt"
    )
    return ctx


class TestMeasurementPeriodGuards:
    def test_a_period_one_day_short_of_the_minimum_is_refused(self, api):
        """Fifty-nine days does not reach the inclusive floor.

        The PRD states: "Two temporal conditions gate it, both refused with
        `ERR_MV_PERIOD_TOO_SHORT` (HTTP 422): `mv_period_days` must be at least 60,
        and `install_completed_iso` must be at or before the logical clock."

        Design: Corner/errors/measurement_period_below_the_minimum_is_refused
        """
        ctx = _approved_project_awaiting_measurement(api)
        assert ctx["approved"]["state"] == "APPROVED"
        assert ctx["approved"]["priority_basis"] == "RISK_ADJUSTED"
        assert ctx["approved"]["priority_score"] == pytest.approx(50.6, abs=0.05)

        response = api.submit_retrofit_measurement(
            ctx["project_id"], f.submit_measurement_payload(**SHORT_PERIOD),
            make_energy_analyst_headers("u_analyst_rt"),
        )

        validate_error(response, ApiErrorId.ERR_MV_PERIOD_TOO_SHORT, 422)
        rows, _ = fx.list_projects(api, ctx["store_id"])
        project = fx.find_row(rows, ctx["project_id"])
        assert project["state"] == "APPROVED"
        assert project["adjusted_baseline_kwh"] is None
        assert project["measured_savings_kwh"] is None
        assert project["realization_rate"] is None
        store = fx.read_store(api, ctx["store_id"])
        assert store["verified_savings_kwh_ytd"] == pytest.approx(0.00, abs=0.001)
        assert store["portfolio_realization_rate"] == pytest.approx(0.85, abs=0.0001)

    def test_an_install_date_after_the_clock_is_refused_with_the_same_code(self, api):
        """One code covers both temporal guards on the same body.

        The PRD states: "Two temporal conditions gate it, both refused with
        `ERR_MV_PERIOD_TOO_SHORT` (HTTP 422): `mv_period_days` must be at least 60,
        and `install_completed_iso` must be at or before the logical clock."

        Design: Corner/errors/measurement_period_below_the_minimum_is_refused
        """
        ctx = _approved_project_awaiting_measurement(api)

        response = api.submit_retrofit_measurement(
            ctx["project_id"], f.submit_measurement_payload(**FUTURE_INSTALL),
            make_energy_analyst_headers("u_analyst_rt"),
        )

        validate_error(response, ApiErrorId.ERR_MV_PERIOD_TOO_SHORT, 422)
        rows, _ = fx.list_projects(api, ctx["store_id"])
        assert fx.find_row(rows, ctx["project_id"])["install_completed_iso"] is None

    def test_exactly_sixty_days_is_admitted_and_verifies(self, api):
        """The floor is inclusive and the arithmetic then runs.

        The PRD states: "What the engineering estimate promised over the same span
        is the `projected_annual_savings_kwh` multiplied by `mv_period_days` and
        divided by 365 days, rounded half up to two decimal places."

        Design: Corner/errors/measurement_period_below_the_minimum_is_refused
        """
        ctx = _approved_project_awaiting_measurement(api)

        measured = validate_success(
            api.submit_retrofit_measurement(
                ctx["project_id"], f.submit_measurement_payload(**BOUNDARY_PERIOD),
                make_energy_analyst_headers("u_analyst_rt"),
            )
        )

        assert measured["state"] == "VERIFIED"
        assert measured["mv_period_days"] == 60
        assert measured["adjusted_baseline_kwh"] == pytest.approx(100000.00, abs=0.01)
        assert measured["measured_savings_kwh"] == pytest.approx(70000.00, abs=0.01)
        assert measured["realization_rate"] == pytest.approx(0.8189, abs=0.0001)
        store = fx.read_store(api, ctx["store_id"])
        assert store["verified_savings_kwh_ytd"] == pytest.approx(70000.00, abs=0.001)
        assert store["portfolio_realization_rate"] == pytest.approx(0.8189, abs=0.0001)


def _account_ready_for_a_justified_switch(api):
    """The justification check would pass, so only the timing gate can refuse."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-TL")
    account = fx.create_account(
        api, store["id"], utility_name="Statewide Power",
        **f.candidate_tariff_fields(),
    )
    fx.ingest_intervals(
        api, account["id"], [f.demand_interval("2026-06-15T14:00:00Z", 1200.0, True)]
    )
    bill = fx.create_bill(api, account["id"])
    recomputed = fx.recompute_bill(api, bill["id"])
    return {
        "account_id": account["id"],
        "account_v1": account["version"],
        "bill": recomputed,
        "account_at_creation": account,
    }


class TestTariffSwitchTimingGate:
    def test_a_backdated_effective_instant_is_refused(self, api):
        """An effective date before the clock cannot be scheduled.

        The PRD states: "First, timing: the request is refused with
        `ERR_TARIFF_LOCK_ACTIVE` (HTTP 409) when the logical clock is still before
        the account's `tariff_locked_until_iso`, and with the same code when
        `effective_from_iso` is not strictly after the clock — a switch cannot be
        backdated or made instantaneous."

        Design: Corner/errors/a_tariff_switch_effective_at_or_before_the_clock_is_refused
        """
        ctx = _account_ready_for_a_justified_switch(api)
        assert ctx["bill"]["validation_state"] == "VALIDATED"
        assert ctx["account_at_creation"]["tariff_locked_until_iso"] is None

        response = api.tariff_switch(
            ctx["account_id"],
            f.tariff_switch_payload("2026-07-01T00:00:00Z", ctx["account_v1"]),
            make_energy_manager_headers("u_manager_tl"),
        )

        validate_error(response, ApiErrorId.ERR_TARIFF_LOCK_ACTIVE, 409)
        account = fx.read_account(api, ctx["account_id"])
        assert account["tariff_state"] == "STABLE"
        assert account["tariff_switch_effective_from_iso"] is None
        assert account["version"] == 1

    def test_an_instant_equal_to_the_clock_is_refused(self, api):
        """The timing gate outranks the justification gate and excludes equality.

        The PRD states: "Three business gates apply after the stale-view check, in
        order."

        Design: Corner/errors/a_tariff_switch_effective_at_or_before_the_clock_is_refused
        """
        ctx = _account_ready_for_a_justified_switch(api)

        response = api.tariff_switch(
            ctx["account_id"],
            f.tariff_switch_payload("2026-08-01T00:00:00Z", ctx["account_v1"]),
            make_energy_manager_headers("u_manager_tl"),
        )

        validate_error(response, ApiErrorId.ERR_TARIFF_LOCK_ACTIVE, 409)
        account = fx.read_account(api, ctx["account_id"])
        assert account["tariff_state"] == "STABLE"
        assert account["version"] == 1

    def test_one_second_after_the_clock_is_admitted(self, api):
        """Strictly after is satisfied by the smallest representable step.

        The PRD states: "An accepted switch sets `tariff_state` to
        `PENDING_SWITCH`, records `tariff_switch_effective_from_iso` from the
        supplied instant, and increments the account's `version`."

        Design: Corner/errors/a_tariff_switch_effective_at_or_before_the_clock_is_refused
        """
        ctx = _account_ready_for_a_justified_switch(api)

        switched = validate_success(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-08-01T00:00:01Z", ctx["account_v1"]),
                make_energy_manager_headers("u_manager_tl"),
            )
        )

        assert switched["tariff_state"] == "PENDING_SWITCH"
        assert switched["version"] == 2
        assert switched["tariff_switch_effective_from_iso"].startswith(
            "2026-08-01T00:00:01"
        )


FROZEN_CASE = {
    "case_type": "LOW_TEMP",
    "product_class": "FROZEN",
    "alarm_high_f": 10.0,
    "alarm_low_f": -20.0,
    "product_value_usd": 4000.00,
}


def _one_armed_case_and_one_alarming_case(api):
    """Case A holds a single ungraced breach; case B has been driven to ALARM."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T09:00:00Z", code="STR-MS"
    )
    case_a = fx.create_case(api, ctx["store_id"], case_code="CASE-A", **FROZEN_CASE)
    case_b = fx.create_case(api, ctx["store_id"], case_code="CASE-B", **FROZEN_CASE)
    ctx["case_a"] = case_a
    ctx["case_b_id"] = case_b["id"]
    ctx["case_a_reading"] = fx.post_reading(
        api, case_a["id"], ctx["store_id"], 12.0, "2026-08-01T04:00:00Z"
    )
    fx.post_reading(api, case_b["id"], ctx["store_id"], 12.0, "2026-08-01T04:00:00Z")
    ctx["case_b_alarm"] = fx.post_reading(
        api, case_b["id"], ctx["store_id"], 12.0, "2026-08-01T04:15:00Z"
    )
    return ctx


class TestMonitoringStateHasOnlyTwoLegalEdges:
    def test_rearming_an_already_armed_case_is_refused_and_resets_nothing(self, api):
        """A target equal to the current state is rejected.

        The PRD states: "Rearming is permitted only from `BYPASSED`, and a
        `target_state` equal to the case's current `monitoring_state` is refused
        with the same code."

        Design: Corner/errors/monitoring_state_transitions_are_refused_outside_the_bypass_pair
        """
        ctx = _one_armed_case_and_one_alarming_case(api)
        assert ctx["case_a"]["monitoring_state"] == "ARMED"
        assert ctx["case_a_reading"]["consecutive_breach_count"] == 1
        assert ctx["case_a_reading"]["excursion_id"] is None

        response = api.set_monitoring_state(
            ctx["case_a"]["id"], f.monitoring_state_payload("ARMED"),
            make_maintenance_tech_headers("u_tech_ms"),
        )

        validate_error(response, ApiErrorId.ERR_CASE_STATE_INVALID, 409)
        case = validate_success(
            api.get_refrigeration_case(ctx["case_a"]["id"], fx.OFFICER)
        )
        assert case["monitoring_state"] == "ARMED"
        assert case["consecutive_breach_count"] == 1

    def test_a_case_in_alarm_may_not_be_bypassed(self, api):
        """Bypassing is permitted only from ARMED.

        The PRD states: "Bypassing is permitted only from `ARMED`: a case in
        `ALARM` may not be bypassed, because that would be a way of hiding an
        active food-safety event, and the attempt is refused with
        `ERR_CASE_STATE_INVALID` (HTTP 409)."

        Design: Corner/errors/monitoring_state_transitions_are_refused_outside_the_bypass_pair
        """
        ctx = _one_armed_case_and_one_alarming_case(api)
        assert ctx["case_b_alarm"]["monitoring_state"] == "ALARM"
        excursion_id = ctx["case_b_alarm"]["excursion_id"]
        assert excursion_id is not None

        response = api.set_monitoring_state(
            ctx["case_b_id"], f.monitoring_state_payload("BYPASSED"),
            make_maintenance_tech_headers("u_tech_ms"),
        )

        validate_error(response, ApiErrorId.ERR_CASE_STATE_INVALID, 409)
        case = validate_success(api.get_refrigeration_case(ctx["case_b_id"], fx.OFFICER))
        assert case["monitoring_state"] == "ALARM"
        excursion = fx.read_excursion(api, excursion_id)
        assert excursion["state"] == "OPEN"

    def test_the_two_legal_edges_reset_the_breach_counter(self, api):
        """Bypass and rearm are admitted in that order and nothing else is.

        The PRD states: "A `MaintenanceTech` who needs to service a case takes it
        out of monitoring by supplying a `target_state` of `BYPASSED`, and returns
        it by supplying `ARMED`. Both transitions reset `consecutive_breach_count`
        to zero."

        Design: Corner/errors/monitoring_state_transitions_are_refused_outside_the_bypass_pair
        """
        ctx = _one_armed_case_and_one_alarming_case(api)
        tech = make_maintenance_tech_headers("u_tech_ms")

        bypassed = validate_success(
            api.set_monitoring_state(
                ctx["case_a"]["id"], f.monitoring_state_payload("BYPASSED"), tech
            )
        )
        rearmed = validate_success(
            api.set_monitoring_state(
                ctx["case_a"]["id"], f.monitoring_state_payload("ARMED"), tech
            )
        )
        assert bypassed["monitoring_state"] == "BYPASSED"
        assert bypassed["consecutive_breach_count"] == 0
        assert rearmed["monitoring_state"] == "ARMED"
        assert rearmed["consecutive_breach_count"] == 0
