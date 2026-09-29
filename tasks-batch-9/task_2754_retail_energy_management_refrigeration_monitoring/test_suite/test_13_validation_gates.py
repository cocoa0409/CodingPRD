"""Conditional gates, temporal guards and the satisfaction mirrors of each."""
import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a, factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    NO_IDENTITY_HEADERS,
    EMPTY_IDENTITY_HEADERS,
    make_energy_manager_headers,
)

MIXED_SUPERCENTER = {
    "climate_zone": "MIXED",
    "store_format": "SUPERCENTER",
    "season": "SUMMER",
    "cooling_setpoint_f": 74.0,
    "heating_setpoint_f": 68.0,
    "deadband_f": 2.0,
    "lighting_lux_target": 750,
}

COLD_EXPRESS = {
    "climate_zone": "COLD",
    "store_format": "EXPRESS",
    "season": "WINTER",
    "cooling_setpoint_f": 72.0,
    "heating_setpoint_f": 66.0,
    "deadband_f": 2.0,
    "lighting_lux_target": 600,
}


def _store_with_a_draft_and_an_out_of_scope_standard(api):
    """One MIXED/SUPERCENTER store, a matching standard left in DRAFT and a
    published standard governing a different scope."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-SC", floor_area_sqft=120000)
    draft = fx.create_standard(api, **MIXED_SUPERCENTER)
    out_of_scope = fx.create_published_standard(api, **COLD_EXPRESS)
    return {
        "store_id": store["id"],
        "store_version": store["version"],
        "draft_id": draft["id"],
        "out_of_scope_id": out_of_scope["id"],
    }


class TestCommissioningStandardGates:
    def test_a_draft_standard_of_the_right_scope_is_refused(self, api):
        """Publication status is checked even when the scope matches exactly.

        The PRD states: "The named standard must resolve, must be in `PUBLISHED`
        status (a `DRAFT` or `SUPERSEDED` standard yields
        `ERR_STANDARD_NOT_PUBLISHED`)".

        Design: Corner/validations/commissioning_rejects_draft_then_out_of_scope_standard
        """
        ctx = _store_with_a_draft_and_an_out_of_scope_standard(api)

        response = api.commission_bms(
            ctx["store_id"],
            f.commission_bms_payload(ctx["draft_id"], ctx["store_version"]),
            make_energy_manager_headers("u_manager_sc"),
        )

        validate_error(response, ApiErrorId.ERR_STANDARD_NOT_PUBLISHED, 409)

    def test_a_published_standard_of_the_wrong_scope_is_refused(self, api):
        """A scope mismatch is a separate, later refusal at 422.

        The PRD states: "and must govern this store's scope: both its
        `climate_zone` and its `store_format` must equal the store's, and any
        mismatch on either yields `ERR_STANDARD_SCOPE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/commissioning_rejects_draft_then_out_of_scope_standard
        """
        ctx = _store_with_a_draft_and_an_out_of_scope_standard(api)

        response = api.commission_bms(
            ctx["store_id"],
            f.commission_bms_payload(ctx["out_of_scope_id"], ctx["store_version"]),
            make_energy_manager_headers("u_manager_sc"),
        )

        validate_error(response, ApiErrorId.ERR_STANDARD_SCOPE_MISMATCH, 422)

    def test_neither_refusal_binds_the_standard_or_bumps_the_version(self, api):
        """After both refusals the store is still untouched.

        The PRD states: "When all of that passes, `bms_status` advances to
        `COMMISSIONING`, `active_standard_id` is set to the supplied
        `standard_id`, `version` increments by one and `updated_at` is refreshed."

        Design: Corner/validations/commissioning_rejects_draft_then_out_of_scope_standard
        """
        ctx = _store_with_a_draft_and_an_out_of_scope_standard(api)
        manager = make_energy_manager_headers("u_manager_sc")

        api.commission_bms(
            ctx["store_id"],
            f.commission_bms_payload(ctx["draft_id"], ctx["store_version"]), manager,
        )
        api.commission_bms(
            ctx["store_id"],
            f.commission_bms_payload(ctx["out_of_scope_id"], ctx["store_version"]), manager,
        )
        store = fx.read_store(api, ctx["store_id"])

        assert store["bms_status"] == "NOT_DEPLOYED"
        assert store["active_standard_id"] is None
        assert store["version"] == 1


class TestCommissioningAdmittedWhenEveryGateIsSatisfied:
    def test_commissioning_binds_the_standard_and_bumps_the_version(self, api):
        """Every guard satisfied produces the declared side effects.

        The PRD states: "When all of that passes, `bms_status` advances to
        `COMMISSIONING`, `active_standard_id` is set to the supplied
        `standard_id`, `version` increments by one and `updated_at` is refreshed."

        Design: Corner/validations/commissioning_admitted_when_standard_published_and_in_scope
        """
        fx.set_clock(api)
        store = fx.create_store(api, code="STR-OK", floor_area_sqft=120000)
        standard = fx.create_published_standard(api, **MIXED_SUPERCENTER)

        commissioned = validate_success(
            api.commission_bms(
                store["id"],
                f.commission_bms_payload(standard["id"], store["version"]),
                make_energy_manager_headers("u_manager_ok"),
            )
        )

        assert commissioned["bms_status"] == "COMMISSIONING"
        assert commissioned["active_standard_id"] == standard["id"]
        assert commissioned["energy_posture"] == "NORMAL"
        assert commissioned["version"] == 2
        assert commissioned["updated_at"].startswith("2026-08-01T00:00:00")

    def test_activation_then_advances_the_gateway_to_active(self, api):
        """Activation is legal from COMMISSIONING and increments again.

        The PRD states: "A successful activation advances `COMMISSIONING →
        ACTIVE`, increments `version` and recomputes the store's posture."

        Design: Corner/validations/commissioning_admitted_when_standard_published_and_in_scope
        """
        fx.set_clock(api)
        store = fx.create_store(api, code="STR-OK", floor_area_sqft=120000)
        standard = fx.create_published_standard(api, **MIXED_SUPERCENTER)
        fx.commission_store(api, store["id"], standard["id"], store["version"])

        activated = validate_success(api.activate_bms(store["id"], fx.MANAGER))

        assert activated["bms_status"] == "ACTIVE"
        assert activated["version"] == 3
        assert activated["energy_posture"] == "NORMAL"

    def test_the_deployed_store_admits_a_case_that_an_undeployed_one_refuses(self, api):
        """The same call is admitted on the ACTIVE store and refused on a fresh one.

        The PRD states: "A store whose `bms_status` is `NOT_DEPLOYED` or
        `COMMISSIONING` cannot have refrigeration cases registered against it,
        cannot have fault diagnostics reported against it, cannot have lighting
        overrides created for it, and cannot have retrofit projects approved on it;
        all four refusals carry `ERR_BMS_NOT_COMMISSIONED` (HTTP 409)."

        Design: Corner/validations/commissioning_admitted_when_standard_published_and_in_scope
        """
        fx.set_clock(api)
        store = fx.create_store(api, code="STR-OK", floor_area_sqft=120000)
        standard = fx.create_published_standard(api, **MIXED_SUPERCENTER)
        fx.commission_store(api, store["id"], standard["id"], store["version"])
        fx.activate_store_bms(api, store["id"])
        undeployed = fx.create_store(api, code="STR-OK-2", floor_area_sqft=90000)

        admitted = get_success_data(
            api.create_refrigeration_case(
                store["id"], f.create_refrigeration_case_payload(case_code="CASE-OK"),
                fx.MANAGER,
            ),
            201,
        )
        refused = api.create_refrigeration_case(
            undeployed["id"], f.create_refrigeration_case_payload(case_code="CASE-NO"),
            fx.MANAGER,
        )

        assert admitted["monitoring_state"] == "ARMED"
        validate_error(refused, ApiErrorId.ERR_BMS_NOT_COMMISSIONED, 409)


HOT_DRY_SCOPE = {
    "climate_zone": "HOT_DRY",
    "store_format": "EXPRESS",
    "season": "SUMMER",
    "cooling_setpoint_f": 76.0,
    "heating_setpoint_f": 69.0,
    "deadband_f": 2.0,
    "lighting_lux_target": 650,
}

COMPETITOR = {**HOT_DRY_SCOPE, "cooling_setpoint_f": 77.0, "lighting_lux_target": 660}

SCOPE_QUERY = {"climate_zone": "HOT_DRY", "store_format": "EXPRESS", "season": "SUMMER"}


class TestDuplicateScopeIsConditionalOnSuccession:
    def test_a_bare_second_draft_for_a_governed_scope_is_refused(self, api):
        """A competitor for the same triple is rejected and nothing is persisted.

        The PRD states: "Only one standard may hold each scope at a time.
        Drafting is refused with `ERR_DUPLICATE_STANDARD_SCOPE` (HTTP 409) when a
        standard in `DRAFT` or `PUBLISHED` already governs the same combination of
        climate zone, store format and season."

        Design: Corner/validations/duplicate_standard_scope_rejected_unless_successor_names_predecessor
        """
        fx.set_clock(api)
        incumbent = fx.create_published_standard(api, **HOT_DRY_SCOPE)

        response = api.create_setpoint_standard(
            f.create_setpoint_standard_payload(**COMPETITOR),
            make_energy_manager_headers("u_manager_ds"),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_STANDARD_SCOPE, 409)
        rows, meta = fx.list_standards(api, **SCOPE_QUERY)
        assert meta["total_count"] == 1
        assert rows[0]["id"] == incumbent["id"]

    def test_a_draft_naming_the_incumbent_is_admitted_as_its_successor(self, api):
        """The orderly-succession exemption admits the intended replacement.

        The PRD states: "The single exception is the orderly-succession case: a
        draft that explicitly names that incumbent `PUBLISHED` standard in
        `supersedes_standard_id` is admitted, because it is the intended
        replacement rather than a competitor."

        Design: Corner/validations/duplicate_standard_scope_rejected_unless_successor_names_predecessor
        """
        fx.set_clock(api)
        incumbent = fx.create_published_standard(api, **HOT_DRY_SCOPE)

        successor = get_success_data(
            api.create_setpoint_standard(
                f.create_setpoint_standard_payload(
                    supersedes_standard_id=incumbent["id"], **COMPETITOR
                ),
                make_energy_manager_headers("u_manager_ds"),
            ),
            201,
        )

        assert successor["status"] == "DRAFT"
        assert successor["supersedes_standard_id"] == incumbent["id"]
        # Its revision is exactly one greater than the predecessor's.
        assert successor["revision"] == incumbent["revision"] + 1
        assert successor["published_at_iso"] is None
        assert successor["published_by_user_id"] is None

    def test_both_standards_are_then_visible_through_the_chain_filters(self, api):
        """The scope holds two rows and the reverse filter finds the successor.

        The PRD states: "Standards can be listed with filters on `climate_zone`,
        `store_format`, `season`, `status` and `supersedes_standard_id`, the last
        being the reverse-reachability filter over the self-referential chain."

        Design: Corner/validations/duplicate_standard_scope_rejected_unless_successor_names_predecessor
        """
        fx.set_clock(api)
        incumbent = fx.create_published_standard(api, **HOT_DRY_SCOPE)
        successor = fx.create_standard(
            api, supersedes_standard_id=incumbent["id"], **COMPETITOR
        )

        scoped_rows, scoped_meta = fx.list_standards(api, **SCOPE_QUERY)
        chain_rows, chain_meta = fx.list_standards(
            api, supersedes_standard_id=incumbent["id"]
        )

        assert scoped_meta["total_count"] == 2
        assert fx.find_row(scoped_rows, incumbent["id"])["status"] == "PUBLISHED"
        assert fx.find_row(scoped_rows, successor["id"])["status"] == "DRAFT"
        assert chain_meta["total_count"] == 1
        assert chain_rows[0]["id"] == successor["id"]


RACK_FAULT = {
    "equipment_ref": "RACK-A",
    "equipment_class": "REFRIGERATION",
    "fault_code": "SUCTION-HI",
    "severity": "MINOR",
    "occurrence_count": 2,
    "affected_load_kw": 20.0,
}

SECOND_RACK_FAULT = {**RACK_FAULT, "fault_code": "OIL-LOW"}

AHU_FAULT = {
    "equipment_ref": "AHU-9",
    "equipment_class": "HVAC",
    "fault_code": "FAN-AMPS",
    "severity": "MINOR",
    "occurrence_count": 2,
    "affected_load_kw": 20.0,
}


def _three_work_orders_with_one_scheduled(api):
    """Two work orders on RACK-A and one on AHU-9; the first occupies
    2026-08-02T09:00Z..12:00Z."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T08:00:00Z", code="STR-WC", floor_area_sqft=120000
    )
    orders = {}
    for key, spec in (("wo1", RACK_FAULT), ("wo2", SECOND_RACK_FAULT), ("wo3", AHU_FAULT)):
        fault = fx.create_fault(api, ctx["store_id"], **spec)
        triage = fx.triage_fault(api, fault["id"])
        assert triage["work_order_priority"] == "ROUTINE"
        orders[key] = triage["work_order_id"]
        ctx[key + "_fault_id"] = fault["id"]
    ctx.update(orders)
    ctx["wo1_scheduled"] = fx.schedule_work_order(
        api, orders["wo1"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z"
    )
    return ctx


class TestWorkOrderWindowConflict:
    def test_a_window_starting_exactly_when_another_ends_still_conflicts(self, api):
        """Closed intervals make touching endpoints a conflict.

        The PRD states: "The first is per-equipment: no two work orders may occupy
        intersecting windows on the same `equipment_ref`, reached through each
        order's fault, where windows are compared as closed intervals against other
        orders in `SCHEDULED`, and the order being rescheduled is excluded from its
        own conflict set so that a reschedule onto an overlapping window of its own
        is not self-defeating."

        Design: Corner/validations/work_order_window_conflict_on_the_same_equipment_ref
        """
        ctx = _three_work_orders_with_one_scheduled(api)
        assert ctx["wo1_scheduled"]["state"] == "SCHEDULED"

        response = api.schedule_work_order(
            ctx["wo2"],
            f.schedule_work_order_payload("2026-08-02T12:00:00Z", "2026-08-02T15:00:00Z"),
            fx.TECH,
        )

        validate_error(response, ApiErrorId.ERR_WORK_ORDER_WINDOW_CONFLICT, 409)
        rows, _ = fx.list_work_orders(api, ctx["wo2_fault_id"])
        blocked = fx.find_row(rows, ctx["wo2"])
        assert blocked["state"] == "OPEN"
        assert blocked["scheduled_start_iso"] is None
        assert blocked["scheduled_end_iso"] is None

    def test_a_row_is_excluded_from_its_own_conflict_set(self, api):
        """Rescheduling onto a window overlapping its own is admitted.

        The PRD states: "Scheduling a work order supplies `scheduled_start_iso`
        and `scheduled_end_iso` and is legal from `OPEN`, which advances the order
        `OPEN → SCHEDULED`, and equally from `SCHEDULED`, which is a rescheduling
        that leaves the state at `SCHEDULED` while overwriting both stored
        instants."

        Design: Corner/validations/work_order_window_conflict_on_the_same_equipment_ref
        """
        ctx = _three_work_orders_with_one_scheduled(api)

        rescheduled = validate_success(
            api.schedule_work_order(
                ctx["wo1"],
                f.schedule_work_order_payload(
                    "2026-08-02T11:00:00Z", "2026-08-02T14:00:00Z"
                ),
                fx.TECH,
            )
        )

        assert rescheduled["state"] == "SCHEDULED"
        assert rescheduled["scheduled_start_iso"].startswith("2026-08-02T11:00:00")
        assert rescheduled["scheduled_end_iso"].startswith("2026-08-02T14:00:00")

    def test_the_rule_is_scoped_by_equipment_rather_than_by_store(self, api):
        """A different equipment_ref shares the window freely.

        The PRD states: "The second is per-store crew capacity: at most two work
        orders of the same store may occupy mutually overlapping windows, so a
        request is refused with `ERR_WORK_ORDER_CAPACITY_EXCEEDED` (HTTP 422) when
        two or more *other* `SCHEDULED` work orders of that store already overlap
        the requested window — and this rule ignores `equipment_ref` entirely,
        because the constraint is technicians, not machines."

        Design: Corner/validations/work_order_window_conflict_on_the_same_equipment_ref
        """
        ctx = _three_work_orders_with_one_scheduled(api)

        scheduled = validate_success(
            api.schedule_work_order(
                ctx["wo3"],
                f.schedule_work_order_payload(
                    "2026-08-02T11:00:00Z", "2026-08-02T14:00:00Z"
                ),
                fx.TECH,
            )
        )

        assert scheduled["state"] == "SCHEDULED"
        assert scheduled["priority"] == "ROUTINE"


def _notified_event_one_minute_early(api):
    """A NOTIFIED event for 14:00Z..18:00Z with the clock at 13:59Z."""
    fx.set_clock(api, "2026-08-10T13:00:00Z")
    store = fx.create_store(api, code="STR-CT", floor_area_sqft=120000)
    account = fx.create_account(api, store["id"], utility_name="Statewide Power")
    fx.ingest_intervals(
        api, account["id"], [f.demand_interval("2026-08-09T14:00:00Z", 1200.0, True)]
    )
    event = fx.create_event(
        api, account["id"], program_code="DR-PEAK-A",
        curtailment_start_iso="2026-08-10T14:00:00Z",
        curtailment_end_iso="2026-08-10T18:00:00Z", target_reduction_kw=200.0,
    )
    notified = fx.notify_event(api, event["id"])
    assert notified["event_state"] == "NOTIFIED"
    assert notified["baseline_kw"] == pytest.approx(1200.0, abs=0.01)
    fx.set_clock(api, "2026-08-10T13:59:00Z")
    return {"store_id": store["id"], "account_id": account["id"], "event_id": event["id"]}


class TestCurtailmentStartIsInclusive:
    def test_activation_one_minute_early_is_refused(self, api):
        """The clock must have reached the curtailment start.

        The PRD states: "and requires the logical clock to have reached or passed
        `curtailment_start_iso`, an earlier attempt being refused with
        `ERR_CURTAILMENT_NOT_ELAPSED` (HTTP 422)."

        Design: Corner/validations/dr_activation_before_curtailment_start_is_refused
        """
        ctx = _notified_event_one_minute_early(api)

        response = api.activate_demand_response_event(
            ctx["event_id"], make_energy_manager_headers("u_manager_ct")
        )

        validate_error(response, ApiErrorId.ERR_CURTAILMENT_NOT_ELAPSED, 422)
        rows, _ = fx.list_events(api, ctx["account_id"])
        assert fx.find_row(rows, ctx["event_id"])["event_state"] == "NOTIFIED"
        assert fx.read_store(api, ctx["store_id"])["energy_posture"] == "NORMAL"

    def test_activation_exactly_at_the_start_curtails_the_store(self, api):
        """The boundary instant admits the identical call.

        The PRD states: "A successful activation advances `NOTIFIED → ACTIVE`, and
        the owning store immediately recomputes its posture and rises to
        `CURTAILED`."

        Design: Corner/validations/dr_activation_before_curtailment_start_is_refused
        """
        ctx = _notified_event_one_minute_early(api)
        fx.set_clock(api, "2026-08-10T14:00:00Z")

        activated = validate_success(
            api.activate_demand_response_event(
                ctx["event_id"], make_energy_manager_headers("u_manager_ct")
            )
        )

        assert activated["event_state"] == "ACTIVE"
        assert fx.read_store(api, ctx["store_id"])["energy_posture"] == "CURTAILED"


OFF_PEAK_ONLY_INTERVALS = [
    f.demand_interval("2026-06-10T02:00:00Z", 1100.0, False),
    f.demand_interval("2026-06-20T03:00:00Z", 1150.0, False),
    f.demand_interval("2026-07-15T14:00:00Z", 1300.0, True),
]

JUNE_BILL = {
    "period_start_iso": "2026-06-01T00:00:00Z",
    "period_end_iso": "2026-07-01T00:00:00Z",
    "on_peak_kwh": 60000,
    "off_peak_kwh": 120000,
    "billed_kwh": 180000,
    "billed_peak_kw": 900.0,
    "billed_amount_usd": 37294.33,
}


def _bill_with_no_eligible_on_peak_interval(api):
    """A TOU account whose only in-period intervals are off-peak, plus one on-peak
    interval that falls outside the billing period."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-DM", floor_area_sqft=120000)
    account = fx.create_account(
        api, store["id"], utility_name="Statewide Power", rate_family="TOU_DEMAND"
    )
    fx.ingest_intervals(api, account["id"], OFF_PEAK_ONLY_INTERVALS)
    bill = fx.create_bill(api, account["id"], **JUNE_BILL)
    return {"account_id": account["id"], "bill_id": bill["id"]}


class TestEmptinessIsJudgedPerVariant:
    def test_a_time_of_use_recompute_with_only_off_peak_data_is_refused(self, api):
        """Off-peak rows are not eligible under the coincident variant.

        The PRD states: "If the eligible set is empty the recompute is refused with
        `ERR_DEMAND_DATA_MISSING` (HTTP 422), the bill stays in `RECEIVED`, and no
        derived field is written — and note that emptiness is judged per variant, so
        an account holding only off-peak intervals fails under the coincident
        variant while identical data would have succeeded under the anytime
        variant."

        Design: Corner/validations/bill_recompute_without_eligible_intervals_is_refused
        """
        ctx = _bill_with_no_eligible_on_peak_interval(api)

        response = api.recompute_utility_bill(ctx["bill_id"], fx.ANALYST)

        validate_error(response, ApiErrorId.ERR_DEMAND_DATA_MISSING, 422)

    def test_the_failed_recompute_writes_no_derived_field(self, api):
        """The bill is still exactly as it was created.

        The PRD states: "A recorded bill carries a `utility_account_id` pointing
        at the account it was billed against and lands in `validation_state`
        `RECEIVED` with every derived field null: `recomputed_energy_cost_usd`,
        `recomputed_demand_cost_usd`, `recomputed_rider_cost_usd`,
        `recomputed_surcharge_usd`, `recomputed_amount_usd`, `billable_demand_kw`,
        `peak_basis` and `variance_pct`."

        Design: Corner/validations/bill_recompute_without_eligible_intervals_is_refused
        """
        ctx = _bill_with_no_eligible_on_peak_interval(api)

        api.recompute_utility_bill(ctx["bill_id"], fx.ANALYST)

        rows, meta = fx.list_bills(api, ctx["account_id"])
        assert meta["total_count"] == 1
        bill = fx.find_row(rows, ctx["bill_id"])
        assert bill["validation_state"] == "RECEIVED"
        a.assert_bill_is_unrecomputed(bill)


DEARER_CANDIDATE = {
    "candidate_rate_schedule_code": "GS-4",
    "candidate_rate_family": "TOU_DEMAND",
    "candidate_demand_charge_per_kw": 14.60,
    "candidate_rate_on_peak": 0.1460,
    "candidate_rate_off_peak": 0.0805,
}

VALIDATED_BILL = {
    "period_start_iso": "2026-06-01T00:00:00Z",
    "period_end_iso": "2026-07-01T00:00:00Z",
    "on_peak_kwh": 144000,
    "off_peak_kwh": 216000,
    "billed_kwh": 360000,
    "billed_peak_kw": 1200.0,
    "billed_amount_usd": 58208.15,
}


def _account_whose_candidate_tariff_is_dearer(api):
    """A TOU account with a fully priced but slightly more expensive candidate and
    one VALIDATED reference bill."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-TN", floor_area_sqft=120000)
    account = fx.create_account(
        api, store["id"], utility_name="Statewide Power", **DEARER_CANDIDATE
    )
    fx.ingest_intervals(
        api, account["id"], [f.demand_interval("2026-06-15T14:00:00Z", 1200.0, True)]
    )
    bill = fx.create_bill(api, account["id"], **VALIDATED_BILL)
    recomputed = fx.recompute_bill(api, bill["id"])
    assert recomputed["validation_state"] == "VALIDATED"
    assert recomputed["recomputed_amount_usd"] == pytest.approx(58208.15, abs=0.01)
    return {"account_id": account["id"], "account_version": account["version"]}


class TestTariffSwitchNeedsAProjectedSaving:
    def test_a_dearer_candidate_projects_a_positive_delta(self, api):
        """The comparison prices both sides and recommends nothing.

        The PRD states: "Finally, `switch_recommended` is true when
        `annual_delta_usd` is at or below negative two thousand five hundred
        dollars, meaning the switch must save at least 2500.00 dollars a year to be
        worth doing; a saving of exactly that amount qualifies."

        Design: Corner/validations/tariff_switch_without_projected_savings_is_refused
        """
        ctx = _account_whose_candidate_tariff_is_dearer(api)

        comparison = validate_success(
            api.get_tariff_comparison(
                ctx["account_id"], make_energy_manager_headers("u_manager_tn")
            )
        )

        assert comparison["current_annual_cost_usd"] == pytest.approx(698497.80, abs=0.01)
        assert comparison["candidate_annual_cost_usd"] == pytest.approx(703198.68, abs=0.01)
        assert comparison["annual_delta_usd"] == pytest.approx(4700.88, abs=0.01)
        assert comparison["switch_recommended"] is False

    def test_the_switch_is_refused_for_want_of_justification(self, api):
        """A positive delta is not a saving, whatever its magnitude.

        The PRD states: "Second, justification: the projection above is evaluated,
        and a request whose `switch_recommended` is false is refused with
        `ERR_TARIFF_SWITCH_NOT_JUSTIFIED` (HTTP 422)."

        Design: Corner/validations/tariff_switch_without_projected_savings_is_refused
        """
        ctx = _account_whose_candidate_tariff_is_dearer(api)

        response = api.tariff_switch(
            ctx["account_id"],
            {
                "effective_from_iso": "2026-09-01T00:00:00Z",
                "expected_utility_account_version": ctx["account_version"],
            },
            make_energy_manager_headers("u_manager_tn"),
        )

        validate_error(response, ApiErrorId.ERR_TARIFF_SWITCH_NOT_JUSTIFIED, 422)
        account = fx.read_account(api, ctx["account_id"])
        assert account["tariff_state"] == "STABLE"
        assert account["tariff_switch_effective_from_iso"] is None
        assert account["version"] == 1


class TestAuthenticationOutranksEverythingElse:
    def test_a_request_with_no_identity_is_rejected_before_the_path_resolves(self, api):
        """An unknown store and an invalid body are never reported to an anonymous
        caller.

        The PRD states: "Checks are therefore evaluated in a single global order,
        and the **first** violated check determines the response; later checks are
        never reached and never reported." — and the first check of that order is
        "Presence of `X-User-ID` — `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_request_outranks_path_resolution
        """
        fx.set_clock(api)

        response = api.create_refrigeration_case(
            "str_00000000-0000-0000-0000-000000000000",
            {"case_code": "CASE-NA"},
            NO_IDENTITY_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_an_empty_identity_header_behaves_identically(self, api):
        """A blank X-User-ID is no identity at all.

        The PRD states: "Presence of `X-User-ID` — `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_request_outranks_path_resolution
        """
        fx.set_clock(api)

        response = api.create_refrigeration_case(
            "str_00000000-0000-0000-0000-000000000000",
            {"case_code": "CASE-NA"},
            EMPTY_IDENTITY_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
