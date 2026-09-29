"""Endpoint contracts: read-after-write, bulk rollback, computed reads, branches."""
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
)

MARINE_WINTER = {
    "climate_zone": "MARINE",
    "store_format": "NEIGHBORHOOD",
    "season": "WINTER",
    "cooling_setpoint_f": 73.0,
    "heating_setpoint_f": 67.5,
    "deadband_f": 2.5,
    "lighting_lux_target": 700,
}

COLD_WINTER = {
    "climate_zone": "COLD",
    "store_format": "NEIGHBORHOOD",
    "season": "WINTER",
    "cooling_setpoint_f": 72.0,
    "heating_setpoint_f": 66.0,
    "deadband_f": 2.0,
    "lighting_lux_target": 700,
}


def _two_drafted_standards(api):
    fx.set_clock(api)
    subject = fx.create_standard(api, **MARINE_WINTER)
    other = fx.create_standard(api, **COLD_WINTER)
    return {"subject": subject, "other": other}


class TestSetpointStandardReadAfterWrite:
    def test_the_single_read_returns_the_created_row_field_for_field(self, api):
        """Creation and retrieval agree on every declared field.

        The PRD states: "A standard is born in `DRAFT` with `published_at_iso` and
        `published_by_user_id` both null. Its `revision` is 1 when the draft names
        no predecessor".

        Design: Corner/endpoints/setpoint_standard_create_read_and_filtered_list_agree
        """
        ctx = _two_drafted_standards(api)
        subject = ctx["subject"]
        assert subject["status"] == "DRAFT"
        assert subject["revision"] == 1

        retrieved = validate_success(
            api.get_setpoint_standard(
                subject["id"], make_energy_analyst_headers("u_analyst_st")
            )
        )

        for field, expected in MARINE_WINTER.items():
            assert retrieved[field] == expected
        assert retrieved["status"] == "DRAFT"
        assert retrieved["revision"] == 1
        assert retrieved["supersedes_standard_id"] is None
        assert retrieved["published_at_iso"] is None
        assert retrieved["published_by_user_id"] is None
        assert retrieved["version"] == 1
        assert retrieved["created_at"].startswith("2026-08-01T00:00:00")
        a.assert_setpoint_standard(retrieved)

    def test_the_filtered_list_agrees_with_both_and_carries_the_defaults(self, api):
        """Filters narrow the page and the meta block reports the declared defaults.

        The PRD states: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count` and `has_more`, where `total_count` is the number of
        rows matching the filters before pagination is applied and `has_more` is
        true when rows remain beyond the current page."

        Design: Corner/endpoints/setpoint_standard_create_read_and_filtered_list_agree
        """
        ctx = _two_drafted_standards(api)

        both_rows, both_meta = fx.list_standards(
            api, status="DRAFT", store_format="NEIGHBORHOOD"
        )
        marine_rows, marine_meta = fx.list_standards(api, climate_zone="MARINE")
        chain_rows, chain_meta = fx.list_standards(
            api, supersedes_standard_id=ctx["subject"]["id"]
        )

        assert both_meta["total_count"] == 2
        assert both_meta["has_more"] is False
        assert both_meta["limit"] == 10
        assert both_meta["offset"] == 0
        assert {row["id"] for row in both_rows} == {
            ctx["subject"]["id"], ctx["other"]["id"]
        }
        assert marine_meta["total_count"] == 1
        assert marine_rows[0]["id"] == ctx["subject"]["id"]
        # The filter matches the foreign key's value, not the id itself.
        assert chain_meta["total_count"] == 0
        assert chain_rows == []

    def test_publication_moves_only_the_publication_fields(self, api):
        """The drafted body survives the publish action untouched.

        The PRD states: "An `EnergyManager` publishing a standard advances it
        `DRAFT → PUBLISHED`, stamps `published_at_iso` from the logical clock and
        records the acting operator in `published_by_user_id`."

        Design: Corner/endpoints/setpoint_standard_create_read_and_filtered_list_agree
        """
        ctx = _two_drafted_standards(api)
        subject_id = ctx["subject"]["id"]

        get_success_data(
            api.publish_setpoint_standard(
                subject_id, make_energy_manager_headers("u_manager_st")
            )
        )
        retrieved = validate_success(api.get_setpoint_standard(subject_id, fx.MANAGER))
        draft_rows, draft_meta = fx.list_standards(api, status="DRAFT")

        for field, expected in MARINE_WINTER.items():
            assert retrieved[field] == expected
        assert retrieved["status"] == "PUBLISHED"
        assert retrieved["published_by_user_id"] == "u_manager_st"
        assert retrieved["published_at_iso"].startswith("2026-08-01T00:00:00")
        assert retrieved["version"] == 2
        assert draft_meta["total_count"] == 1
        assert draft_rows[0]["id"] == ctx["other"]["id"]


BAD_BATCH = [
    f.demand_interval("2026-06-15T14:00:00Z", 1200.0, True),
    f.demand_interval("2026-06-15T13:45:00Z", 1150.0, True),
    f.demand_interval("2026-06-15T14:15:00Z", -5.0, True),
]

GOOD_BATCH = [
    f.demand_interval("2026-06-15T14:00:00Z", 1200.0, True),
    f.demand_interval("2026-06-15T13:45:00Z", 1150.0, True),
    f.demand_interval("2026-06-15T14:15:00Z", 1100.0, True),
]


def _account_with_no_intervals(api):
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-BK", floor_area_sqft=120000)
    account = fx.create_account(api, store["id"], utility_name="Statewide Power")
    return account["id"]


class TestBulkIngestIsAllOrNothing:
    def test_a_batch_whose_third_element_is_invalid_persists_nothing(self, api):
        """The two valid elements ahead of the failure are rolled back.

        The PRD states: "Ingestion is all-or-nothing: if any element fails
        validation the entire batch is rejected with `ERR_INVALID_REQUEST` and
        nothing is persisted."

        Design: Corner/endpoints/demand_interval_bulk_ingest_is_all_or_nothing
        """
        account_id = _account_with_no_intervals(api)

        response = api.ingest_demand_intervals(
            account_id, f.ingest_intervals_payload(BAD_BATCH), fx.ANALYST
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        rows, meta = fx.list_intervals(api, account_id)
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_corrected_batch_is_persisted_in_submission_order(self, api):
        """Rows keep the order supplied rather than chronological order.

        The PRD states: "Accepted intervals are persisted in the order supplied,
        each carrying a `utility_account_id` that points at the account they were
        ingested under and each stamped with `created_at` from the logical clock,
        and each is immutable thereafter — nothing in the API edits or deletes an
        interval."

        Design: Corner/endpoints/demand_interval_bulk_ingest_is_all_or_nothing
        """
        account_id = _account_with_no_intervals(api)
        api.ingest_demand_intervals(
            account_id, f.ingest_intervals_payload(BAD_BATCH), fx.ANALYST
        )

        created = get_success_data(
            api.ingest_demand_intervals(
                account_id, f.ingest_intervals_payload(GOOD_BATCH), fx.ANALYST
            ),
            201,
        )

        assert [row["interval_start_iso"][:19] for row in created] == [
            "2026-06-15T14:00:00", "2026-06-15T13:45:00", "2026-06-15T14:15:00"
        ]
        for row in created:
            assert row["utility_account_id"] == account_id
            assert row["is_dr_event_day"] is False
            assert row["created_at"].startswith("2026-08-01T00:00:00")
        _, meta = fx.list_intervals(api, account_id)
        assert meta["total_count"] == 3

    def test_an_empty_array_is_rejected_and_no_bill_is_touched(self, api):
        """The payload must be a non-empty array and ingestion never recomputes.

        The PRD states: "Either the store's gateway or an `EnergyAnalyst` may
        submit an `intervals` payload, a non-empty array in which each element
        carries `interval_start_iso`, the inclusive start of a fifteen-minute
        metering interval".

        Design: Corner/endpoints/demand_interval_bulk_ingest_is_all_or_nothing
        """
        account_id = _account_with_no_intervals(api)
        bill = fx.create_bill(api, account_id)

        response = api.ingest_demand_intervals(
            account_id, f.ingest_intervals_payload([]), fx.ANALYST
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        rows, meta = fx.list_bills(api, account_id)
        assert meta["total_count"] == 1
        assert fx.find_row(rows, bill["id"])["validation_state"] == "RECEIVED"
        assert fx.find_row(rows, bill["id"])["recomputed_amount_usd"] is None


def _store_and_published_standard(api):
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-XR")
    standard = fx.create_published_standard(api)
    return {
        "store_id": store["id"],
        "store_v1": store["version"],
        "standard_id": standard["id"],
    }


class TestCommissioningResolvesBothReferents:
    def test_an_unknown_store_in_the_path_beats_the_body_referent(self, api):
        """The path segment is resolved first even when the body is good.

        The PRD states: "Path segments are always resolved left to right, and the
        leftmost unresolvable segment determines the error."

        Design: Corner/endpoints/bms_commissioning_links_a_standard_to_a_store_by_reference
        """
        ctx = _store_and_published_standard(api)

        response = api.commission_bms(
            NON_EXISTENT_UUID,
            f.commission_bms_payload(ctx["standard_id"], ctx["store_v1"]),
            make_energy_manager_headers("u_manager_xr"),
        )

        validate_error(response, ApiErrorId.ERR_STORE_NOT_FOUND, 404)
        store = fx.read_store(api, ctx["store_id"])
        assert store["bms_status"] == "NOT_DEPLOYED"
        assert store["active_standard_id"] is None
        assert store["version"] == 1

    def test_an_unknown_standard_in_the_body_is_the_same_not_found_check(self, api):
        """A body referent that does not resolve yields the standard's own code.

        The PRD states: "A setpoint standard named in the body rather than the
        path — as `standard_id` when commissioning, or as
        `supersedes_standard_id` when drafting — is subject to the same
        `ERR_STANDARD_NOT_FOUND` check."

        Design: Corner/endpoints/bms_commissioning_links_a_standard_to_a_store_by_reference
        """
        ctx = _store_and_published_standard(api)

        response = api.commission_bms(
            ctx["store_id"],
            f.commission_bms_payload(NON_EXISTENT_UUID, ctx["store_v1"]),
            make_energy_manager_headers("u_manager_xr"),
        )

        validate_error(response, ApiErrorId.ERR_STANDARD_NOT_FOUND, 404)
        store = fx.read_store(api, ctx["store_id"])
        # The refusal consumed nothing, so the same OCC token still applies.
        assert store["version"] == ctx["store_v1"]
        assert store["active_standard_id"] is None

    def test_two_resolvable_referents_create_the_binding_once(self, api):
        """The binding is written on the store and leaves the standard alone.

        The PRD states: "When all of that passes, `bms_status` advances to
        `COMMISSIONING`, `active_standard_id` is set to the supplied
        `standard_id`, `version` increments by one and `updated_at` is
        refreshed."

        Design: Corner/endpoints/bms_commissioning_links_a_standard_to_a_store_by_reference
        """
        ctx = _store_and_published_standard(api)

        commissioned = validate_success(
            api.commission_bms(
                ctx["store_id"],
                f.commission_bms_payload(ctx["standard_id"], ctx["store_v1"]),
                make_energy_manager_headers("u_manager_xr"),
            )
        )

        assert commissioned["bms_status"] == "COMMISSIONING"
        assert commissioned["active_standard_id"] == ctx["standard_id"]
        assert commissioned["version"] == 2
        bound_rows, bound_meta = fx.list_stores(
            api, active_standard_id=ctx["standard_id"]
        )
        assert bound_meta["total_count"] == 1
        assert bound_rows[0]["id"] == ctx["store_id"]
        standard = validate_success(
            api.get_setpoint_standard(ctx["standard_id"], fx.MANAGER)
        )
        assert standard["status"] == "PUBLISHED"
        assert standard["version"] == 2


TC_CANDIDATE = f.candidate_tariff_fields(
    rate_schedule_code="GS-4", demand_charge_per_kw=14.60,
    rate_on_peak=0.1460, rate_off_peak=0.0805,
)
TC_INTERVALS = [
    f.demand_interval("2026-05-15T14:00:00Z", 300.0, True),
    f.demand_interval("2026-06-15T14:00:00Z", 1200.0, True),
]
MAY_BILL = {
    "period_start_iso": "2026-05-01T00:00:00Z",
    "period_end_iso": "2026-06-01T00:00:00Z",
    "on_peak_kwh": 36000,
    "off_peak_kwh": 54000,
    "billed_kwh": 90000,
    "billed_peak_kw": 300.0,
    "billed_amount_usd": 14410.88,
}


def _account_whose_bills_were_recorded_out_of_period_order(api):
    """June's bill is created first and May's second, so max(created_at) and
    latest period_end disagree about which bill is the reference."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-TC")
    account = fx.create_account(
        api, store["id"], utility_name="Statewide Power",
        rate_schedule_code="GS-3", **TC_CANDIDATE,
    )
    fx.ingest_intervals(api, account["id"], TC_INTERVALS)
    june = fx.create_bill(api, account["id"])
    june_recomputed = fx.recompute_bill(api, june["id"])
    may = fx.create_bill(api, account["id"], **MAY_BILL)
    may_recomputed = fx.recompute_bill(api, may["id"])
    return {
        "store_id": store["id"],
        "account_id": account["id"],
        "june_bill_id": june["id"],
        "may_bill_id": may["id"],
        "june": june_recomputed,
        "may": may_recomputed,
    }


class TestTariffComparisonIsAComputedRead:
    def test_the_reference_bill_is_the_latest_period_not_the_latest_row(self, api):
        """Selection is by period_end, not by creation order.

        The PRD states: "It first selects a reference bill: among the account's
        bills whose `validation_state` is `VALIDATED` or `ADJUSTED`, the one with
        the latest `period_end_iso`, breaking ties by the later `created_at`."

        Design: Corner/endpoints/tariff_comparison_is_a_computed_read_over_the_latest_validated_bill
        """
        ctx = _account_whose_bills_were_recorded_out_of_period_order(api)
        assert ctx["june"]["validation_state"] == "VALIDATED"
        assert ctx["june"]["recomputed_amount_usd"] == pytest.approx(58208.15, abs=0.01)
        assert ctx["june"]["billable_demand_kw"] == pytest.approx(1200.0, abs=0.05)
        assert ctx["may"]["validation_state"] == "VALIDATED"
        assert ctx["may"]["recomputed_amount_usd"] == pytest.approx(14410.88, abs=0.01)

        comparison = validate_success(
            api.get_tariff_comparison(
                ctx["account_id"], make_energy_analyst_headers("u_analyst_tc")
            )
        )

        assert comparison["reference_bill_id"] == ctx["june_bill_id"]
        assert comparison["current_annual_cost_usd"] == pytest.approx(698497.80, abs=0.01)

    def test_the_candidate_side_reprices_the_reference_bill(self, api):
        """The candidate rates are annualised and the delta reported.

        The PRD states: "Annualising the candidate total over twelve months,
        again rounded half up to two decimal places, gives
        `candidate_annual_cost_usd`, and `annual_delta_usd` is the candidate
        annual cost minus the current annual cost — negative when the candidate
        is cheaper."

        Design: Corner/endpoints/tariff_comparison_is_a_computed_read_over_the_latest_validated_bill
        """
        ctx = _account_whose_bills_were_recorded_out_of_period_order(api)

        comparison = validate_success(
            api.get_tariff_comparison(
                ctx["account_id"], make_energy_analyst_headers("u_analyst_tc")
            )
        )

        assert comparison["candidate_peak_basis"] == "COINCIDENT_PEAK"
        assert comparison["candidate_billable_demand_kw"] == pytest.approx(1200.0, abs=0.05)
        assert comparison["candidate_annual_cost_usd"] == pytest.approx(703198.68, abs=0.01)
        assert comparison["annual_delta_usd"] == pytest.approx(4700.88, abs=0.01)
        assert comparison["switch_recommended"] is False
        # A pure projection writes nothing.
        account = fx.read_account(api, ctx["account_id"])
        assert account["version"] == 1
        assert account["tariff_state"] == "STABLE"
        rows, _ = fx.list_bills(api, ctx["account_id"])
        assert fx.find_row(rows, ctx["june_bill_id"])["validation_state"] == "VALIDATED"
        assert fx.find_row(rows, ctx["may_bill_id"])["validation_state"] == "VALIDATED"

    def test_an_account_with_only_a_received_bill_reports_nulls(self, api):
        """The read succeeds with every output null rather than 404ing.

        The PRD states: "When the account has no `VALIDATED` or `ADJUSTED` bill at
        all, all of the projection's outputs are null."

        Design: Corner/endpoints/tariff_comparison_is_a_computed_read_over_the_latest_validated_bill
        """
        ctx = _account_whose_bills_were_recorded_out_of_period_order(api)
        second = fx.create_account(
            api, ctx["store_id"], utility_name="Statewide Power",
            rate_schedule_code="GS-7", **TC_CANDIDATE,
        )
        received = fx.create_bill(api, second["id"])
        assert received["validation_state"] == "RECEIVED"

        comparison = validate_success(
            api.get_tariff_comparison(
                second["id"], make_energy_analyst_headers("u_analyst_tc")
            )
        )

        assert comparison["reference_bill_id"] is None
        assert comparison["current_annual_cost_usd"] is None
        assert comparison["candidate_annual_cost_usd"] is None
        assert comparison["annual_delta_usd"] is None
        assert comparison["switch_recommended"] is None
        assert comparison["candidate_peak_basis"] is None
        assert comparison["candidate_billable_demand_kw"] is None


def _account_whose_candidate_tariff_is_cheaper(api):
    """A TOU_DEMAND account with a candidate at 0.1100 / 0.0700 / 11.00 and one
    VALIDATED June bill of 58208.15."""
    fx.set_clock(api)
    store = fx.create_store(api, code="STR-TJ")
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
    }


class TestTariffSwitchIsAdmittedWhenJustified:
    def test_a_saving_beyond_the_threshold_recommends_the_switch(self, api):
        """The cheaper candidate produces a large negative delta.

        The PRD states: "Finally, `switch_recommended` is true when
        `annual_delta_usd` is at or below negative two thousand five hundred
        dollars, meaning the switch must save at least 2500.00 dollars a year to
        be worth doing; a saving of exactly that amount qualifies."

        Design: Corner/endpoints/tariff_switch_is_admitted_only_when_the_projection_justifies_it
        """
        ctx = _account_whose_candidate_tariff_is_cheaper(api)
        assert ctx["bill"]["validation_state"] == "VALIDATED"

        comparison = validate_success(
            api.get_tariff_comparison(
                ctx["account_id"], make_energy_analyst_headers("u_analyst_tj")
            )
        )

        assert comparison["current_annual_cost_usd"] == pytest.approx(698497.80, abs=0.01)
        assert comparison["candidate_annual_cost_usd"] == pytest.approx(554438.88, abs=0.01)
        assert comparison["annual_delta_usd"] == pytest.approx(-144058.92, abs=0.01)
        assert comparison["switch_recommended"] is True

    def test_the_accepted_switch_schedules_without_moving_the_live_rates(self, api):
        """Two fields and the version move; the lock stamp does not.

        The PRD states: "An accepted switch sets `tariff_state` to
        `PENDING_SWITCH`, records `tariff_switch_effective_from_iso` from the
        supplied instant, and increments the account's `version`. It does not
        stamp `tariff_locked_until_iso`".

        Design: Corner/endpoints/tariff_switch_is_admitted_only_when_the_projection_justifies_it
        """
        ctx = _account_whose_candidate_tariff_is_cheaper(api)

        switched = validate_success(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-09-01T00:00:00Z", ctx["account_v1"]),
                make_energy_manager_headers("u_manager_tj"),
            )
        )

        assert switched["tariff_state"] == "PENDING_SWITCH"
        assert switched["tariff_switch_effective_from_iso"].startswith(
            "2026-09-01T00:00:00"
        )
        assert switched["version"] == 2
        assert switched["tariff_locked_until_iso"] is None
        assert switched["rate_schedule_code"] == "GS-3"
        assert switched["rate_on_peak"] == pytest.approx(0.1450, abs=0.0001)

    def test_a_second_switch_supersedes_rather_than_stacks(self, api):
        """The pending switch is overwritten, leaving exactly one.

        The PRD states: "Crucially, scheduling a switch on an account that is
        *already* `PENDING_SWITCH` is a legitimate operation: it supersedes the
        pending switch by overwriting the same two fields."

        Design: Corner/endpoints/tariff_switch_is_admitted_only_when_the_projection_justifies_it
        """
        ctx = _account_whose_candidate_tariff_is_cheaper(api)
        first = validate_success(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-09-01T00:00:00Z", ctx["account_v1"]),
                make_energy_manager_headers("u_manager_tj"),
            )
        )

        second = validate_success(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-10-01T00:00:00Z", first["version"]),
                make_energy_manager_headers("u_manager_tj"),
            )
        )

        assert second["tariff_state"] == "PENDING_SWITCH"
        assert second["tariff_switch_effective_from_iso"].startswith(
            "2026-10-01T00:00:00"
        )
        assert second["version"] == 3
        assert second["tariff_locked_until_iso"] is None
        account = fx.read_account(api, ctx["account_id"])
        assert account["tariff_switch_effective_from_iso"].startswith(
            "2026-10-01T00:00:00"
        )


REJECT_MEASUREMENT = {
    "install_completed_iso": "2026-08-01T00:00:00Z",
    "baseline_period_kwh": 300000.00,
    "post_period_kwh": 200000.00,
    "mv_period_days": 90,
}


def _proposed_project_on_an_active_store(api):
    """One PROPOSED project scoring 58.0 on the simple-payback basis."""
    ctx = fx.setup_commissioned_store(api, code="STR-RJ")
    project = fx.create_retrofit(
        api, ctx["store_id"], proposer_user_id="u_analyst_rt",
        measure_type="LED_RETROFIT", capex_usd=240240.00,
        projected_annual_savings_kwh=520000.00,
    )
    ctx["project_id"] = project["id"]
    ctx["proposed"] = project
    return ctx


class TestRetrofitRejectionIsTerminal:
    def test_the_reject_branch_stamps_the_decider_and_rescores_nothing(self, api):
        """The proposal-time numbers and basis survive the rejection.

        The PRD states: "A rejection moves the project `PROPOSED → REJECTED` and
        leaves `priority_basis` at `SIMPLE_PAYBACK` with the proposal-time numbers
        intact — `REJECTED` is terminal."

        Design: Corner/endpoints/retrofit_rejection_is_terminal_and_keeps_the_simple_payback_basis
        """
        ctx = _proposed_project_on_an_active_store(api)
        assert ctx["proposed"]["priority_basis"] == "SIMPLE_PAYBACK"
        assert ctx["proposed"]["priority_score"] == pytest.approx(58.0, abs=0.05)

        rejected = validate_success(
            api.approve_retrofit_project(
                ctx["project_id"], f.approve_retrofit_payload("REJECT"),
                make_energy_manager_headers("u_mgr_rt"),
            )
        )

        assert rejected["state"] == "REJECTED"
        assert rejected["priority_basis"] == "SIMPLE_PAYBACK"
        assert rejected["annual_savings_usd"] == pytest.approx(57200.00, abs=0.01)
        assert rejected["payback_years"] == pytest.approx(4.20, abs=0.01)
        assert rejected["priority_score"] == pytest.approx(58.0, abs=0.05)
        assert rejected["approved_by_user_id"] == "u_mgr_rt"
        assert rejected["escalated_review"] is False
        store = fx.read_store(api, ctx["store_id"])
        assert store["verified_savings_kwh_ytd"] == pytest.approx(0.00, abs=0.001)
        assert store["portfolio_realization_rate"] == pytest.approx(0.85, abs=0.0001)

    def test_no_later_project_action_is_admitted_from_rejected(self, api):
        """Approval, measurement and revocation are all refused on the state gate.

        The PRD states: "Revocation is legal only from `VERIFIED` — anything else
        is `ERR_RETROFIT_STATE_INVALID` — and moves the project `VERIFIED →
        SHORTFALL_REVIEW`".

        Design: Corner/endpoints/retrofit_rejection_is_terminal_and_keeps_the_simple_payback_basis
        """
        ctx = _proposed_project_on_an_active_store(api)
        fx.decide_retrofit(api, ctx["project_id"], "REJECT", approver_user_id="u_mgr_rt")

        second_decision = api.approve_retrofit_project(
            ctx["project_id"], f.approve_retrofit_payload("APPROVE"),
            make_energy_manager_headers("u_mgr_rt"),
        )
        measurement = api.submit_retrofit_measurement(
            ctx["project_id"], f.submit_measurement_payload(**REJECT_MEASUREMENT),
            make_energy_analyst_headers("u_analyst_mv"),
        )
        revocation = api.revoke_retrofit_verification(
            ctx["project_id"], make_energy_manager_headers("u_mgr_rt"),
            f.revoke_verification_payload("meter fault"),
        )

        validate_error(second_decision, ApiErrorId.ERR_RETROFIT_STATE_INVALID, 409)
        validate_error(measurement, ApiErrorId.ERR_RETROFIT_STATE_INVALID, 409)
        validate_error(revocation, ApiErrorId.ERR_RETROFIT_STATE_INVALID, 409)
        rows, _ = fx.list_projects(api, ctx["store_id"])
        project = fx.find_row(rows, ctx["project_id"])
        assert project["state"] == "REJECTED"
        assert project["priority_basis"] == "SIMPLE_PAYBACK"
        assert project["measured_savings_kwh"] is None
        assert project["realization_rate"] is None

    def test_the_state_filter_reports_the_project_only_under_rejected(self, api):
        """The rejected project leaves the proposable set for good.

        The PRD states: "Projects of a store can be listed with filters on
        `state`, `measure_type`, `priority_basis` and `escalated_review`."

        Design: Corner/endpoints/retrofit_rejection_is_terminal_and_keeps_the_simple_payback_basis
        """
        ctx = _proposed_project_on_an_active_store(api)
        fx.decide_retrofit(api, ctx["project_id"], "REJECT", approver_user_id="u_mgr_rt")

        rejected_rows, rejected_meta = fx.list_projects(
            api, ctx["store_id"], state="REJECTED"
        )
        proposed_rows, proposed_meta = fx.list_projects(
            api, ctx["store_id"], state="PROPOSED"
        )

        assert rejected_meta["total_count"] == 1
        assert rejected_rows[0]["id"] == ctx["project_id"]
        assert proposed_meta["total_count"] == 0
        assert proposed_rows == []
