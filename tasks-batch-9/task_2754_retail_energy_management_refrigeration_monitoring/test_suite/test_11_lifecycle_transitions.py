"""Declared initial states, invalid edges, terminal lockdown and side effects."""
import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a, factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_energy_manager_headers,
    make_food_safety_officer_headers,
    make_maintenance_tech_headers,
)

HOT_DRY_STANDARD = {
    "climate_zone": "HOT_DRY",
    "store_format": "NEIGHBORHOOD",
    "season": "SUMMER",
    "cooling_setpoint_f": 76.0,
    "heating_setpoint_f": 69.0,
    "deadband_f": 2.5,
    "lighting_lux_target": 700,
}


class TestStandardPublicationStamps:
    def test_publication_stamps_the_clock_at_publication_not_at_drafting(self, api):
        """published_at_iso reads the clock as it stands when publish is called.

        The PRD states: "An `EnergyManager` publishing a standard advances it
        `DRAFT → PUBLISHED`, stamps `published_at_iso` from the logical clock and
        records the acting operator in `published_by_user_id`."

        Design: Corner/state_machines/standard_publish_stamps_publisher_and_publication_clock
        """
        fx.set_clock(api)
        draft = fx.create_standard(api, **HOT_DRY_STANDARD)
        assert draft["status"] == "DRAFT"
        assert draft["published_at_iso"] is None
        assert draft["published_by_user_id"] is None
        fx.set_clock(api, "2026-08-05T09:30:00Z")

        published = get_success_data(
            api.publish_setpoint_standard(
                draft["id"], make_energy_manager_headers("u_publisher_1")
            )
        )

        a.assert_setpoint_standard(published)
        assert published["id"] == draft["id"]
        assert published["status"] == "PUBLISHED"
        assert published["published_at_iso"].startswith("2026-08-05T09:30:00")
        assert published["published_by_user_id"] == "u_publisher_1"
        assert published["created_at"].startswith("2026-08-01T00:00:00")
        assert published["updated_at"].startswith("2026-08-05T09:30:00")
        assert published["version"] == 2

    def test_a_publication_with_no_predecessor_fires_no_cascade_link(self, api):
        """revision stays 1 and no other standard changes.

        The PRD states: "Its `revision` is 1 when the draft names no predecessor,
        and otherwise exactly one greater than the `revision` of the standard
        named in `supersedes_standard_id`".

        Design: Corner/state_machines/standard_publish_stamps_publisher_and_publication_clock
        """
        fx.set_clock(api)
        draft = fx.create_standard(api, **HOT_DRY_STANDARD)
        fx.set_clock(api, "2026-08-05T09:30:00Z")

        published = get_success_data(
            api.publish_setpoint_standard(
                draft["id"], make_energy_manager_headers("u_publisher_1")
            )
        )

        rows, meta = fx.list_standards(api)
        assert published["revision"] == 1
        assert published["supersedes_standard_id"] is None
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "PUBLISHED"


class TestDeclaredInitialStates:
    def test_a_reported_fault_and_a_future_override_land_in_their_initial_states(self, api):
        """A fault is DETECTED and a wholly future override is SCHEDULED.

        The PRD states: "The fault is persisted in `DETECTED` with
        `detected_at_iso` stamped from the logical clock and `triaged_by_user_id`
        null." and "a window entirely in the future is persisted in `SCHEDULED`
        instead, and is charged against the monthly allowance immediately
        regardless."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        ctx = fx.setup_commissioned_store(
            api, clock="2026-08-01T12:00:00Z", code="STR-IS",
        )
        override = fx.create_override(
            api, ctx["store_id"], zone="PARKING", override_type="OCCUPANCY_DISABLE",
            start_iso="2026-08-03T18:00:00Z", end_iso="2026-08-03T22:00:00Z",
            zone_load_kw=20.0, requested_reason="lot resurfacing",
        )

        fault = validate_success(
            api.create_fault_diagnostic(
                ctx["store_id"],
                f.create_fault_diagnostic_payload(
                    equipment_ref="RTU-2", equipment_class="HVAC",
                    fault_code="FAN-AMPS", severity="MINOR", occurrence_count=1,
                    affected_load_kw=12.0,
                ),
                fx.TECH,
            ),
            201,
        )

        a.assert_fault_diagnostic(fault)
        assert fault["state"] == "DETECTED"
        assert fault["detected_at_iso"].startswith("2026-08-01T12:00:00")
        assert fault["triaged_by_user_id"] is None
        assert override["state"] == "SCHEDULED"

    def test_a_bill_a_dr_event_a_case_and_a_project_start_where_declared(self, api):
        """Four families report their declared initial states at creation.

        The PRD states: "A recorded bill carries a `utility_account_id` pointing at
        the account it was billed against and lands in `validation_state`
        `RECEIVED` with every derived field null".

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        ctx = fx.setup_commissioned_store(
            api, clock="2026-08-01T12:00:00Z", code="STR-IS",
        )
        account = fx.create_account(api, ctx["store_id"])
        bill = fx.create_bill(
            api, account["id"], on_peak_kwh=36000, off_peak_kwh=54000,
            billed_kwh=90000, billed_peak_kw=300.0, billed_amount_usd=14410.88,
        )
        event = fx.create_event(
            api, account["id"], program_code="DR-PEAK-A",
            curtailment_start_iso="2026-08-10T14:00:00Z",
            curtailment_end_iso="2026-08-10T18:00:00Z", target_reduction_kw=200.0,
        )
        case = fx.create_case(api, ctx["store_id"], case_code="CASE-IS")
        project = fx.create_retrofit(api, ctx["store_id"], proposer_user_id="u_analyst_is")

        a.assert_bill_is_unrecomputed(bill)
        assert bill["validation_state"] == "RECEIVED"
        assert event["event_state"] == "SCHEDULED"
        assert event["settlement_state"] == "PENDING"
        assert case["monitoring_state"] == "ARMED"
        assert case["consecutive_breach_count"] == 0
        assert project["state"] == "PROPOSED"
        assert project["escalated_review"] is False

    def test_a_registered_store_starts_undeployed_and_normal(self, api):
        """Both store dimensions begin at their declared initial values.

        The PRD states: "A freshly registered store has nothing deployed. Its
        `bms_status` is `NOT_DEPLOYED`, its `active_standard_id` is null, its
        `energy_posture` is `NORMAL` and its `version` is 1."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        fx.set_clock(api, "2026-08-01T12:00:00Z")

        store = fx.create_store(api, code="STR-IS")
        standard = fx.create_standard(api, climate_zone="MIXED", store_format="SUPERCENTER")

        assert store["bms_status"] == "NOT_DEPLOYED"
        assert store["energy_posture"] == "NORMAL"
        assert store["active_standard_id"] is None
        assert store["version"] == 1
        assert standard["status"] == "DRAFT"


class TestBmsActivationInvalidEdges:
    def test_activation_from_not_deployed_is_refused_and_changes_nothing(self, api):
        """Activation demands the COMMISSIONING state exactly.

        The PRD states: "Activation takes no input at all. It requires
        `bms_status` to be exactly `COMMISSIONING` — anything else is
        `ERR_BMS_STATE_INVALID` — and it re-validates the binding rather than
        trusting it".

        Design: Corner/state_machines/bms_activation_without_commissioning_is_an_invalid_transition
        """
        fx.set_clock(api)
        store = fx.create_store(api, code="STR-IV")

        response = api.activate_bms(store["id"], fx.MANAGER)

        validate_error(response, ApiErrorId.ERR_BMS_STATE_INVALID.value, 409)
        after = fx.read_store(api, store["id"])
        assert after["bms_status"] == "NOT_DEPLOYED"
        assert after["version"] == 1
        assert after["active_standard_id"] is None

    def test_activation_from_active_is_refused_rather_than_treated_as_idempotent(self, api):
        """A second activation is an invalid edge, not a no-op success.

        The PRD states: "A successful activation advances `COMMISSIONING →
        ACTIVE`, increments `version` and recomputes the store's posture."

        Design: Corner/state_machines/bms_activation_without_commissioning_is_an_invalid_transition
        """
        ctx = fx.setup_commissioned_store(api, code="STR-IV")
        assert ctx["store"]["bms_status"] == "ACTIVE"
        assert ctx["store"]["version"] == 3

        response = api.activate_bms(ctx["store_id"], fx.MANAGER)

        validate_error(response, ApiErrorId.ERR_BMS_STATE_INVALID.value, 409)
        after = fx.read_store(api, ctx["store_id"])
        assert after["bms_status"] == "ACTIVE"
        assert after["version"] == 3


MARINE_STANDARD = {
    "climate_zone": "MARINE",
    "store_format": "EXPRESS",
    "season": "WINTER",
    "cooling_setpoint_f": 72.0,
    "heating_setpoint_f": 68.0,
    "deadband_f": 2.0,
    "lighting_lux_target": 600,
}


class TestRepublishingIsRefused:
    def test_the_second_publish_of_the_same_standard_is_rejected(self, api):
        """Publishing something already PUBLISHED is a state error.

        The PRD states: "Publishing anything that is already `PUBLISHED` or
        already `SUPERSEDED` is refused with `ERR_STANDARD_STATE_INVALID`, and
        publishing a successor whose named predecessor is not itself `PUBLISHED`
        is refused with `ERR_STANDARD_NOT_PUBLISHED`."

        Design: Corner/state_machines/publishing_an_already_published_standard_is_rejected
        """
        fx.set_clock(api, "2026-08-05T09:30:00Z")
        draft = fx.create_standard(api, **MARINE_STANDARD)
        get_success_data(
            api.publish_setpoint_standard(
                draft["id"], make_energy_manager_headers("u_publisher_1")
            )
        )
        fx.set_clock(api, "2026-08-06T11:00:00Z")

        response = api.publish_setpoint_standard(
            draft["id"], make_energy_manager_headers("u_publisher_2")
        )

        validate_error(response, ApiErrorId.ERR_STANDARD_STATE_INVALID.value, 409)

    def test_the_first_publishers_stamps_survive_the_rejected_retry(self, api):
        """Neither the publication clock nor the publisher is rewritten.

        The PRD states: "Checks are therefore evaluated in a single global order,
        and the **first** violated check determines the response; later checks are
        never reached and never reported."

        Design: Corner/state_machines/publishing_an_already_published_standard_is_rejected
        """
        fx.set_clock(api, "2026-08-05T09:30:00Z")
        draft = fx.create_standard(api, **MARINE_STANDARD)
        get_success_data(
            api.publish_setpoint_standard(
                draft["id"], make_energy_manager_headers("u_publisher_1")
            )
        )
        fx.set_clock(api, "2026-08-06T11:00:00Z")

        api.publish_setpoint_standard(draft["id"], make_energy_manager_headers("u_publisher_2"))

        after = get_success_data(api.get_setpoint_standard(draft["id"], fx.MANAGER))
        assert after["status"] == "PUBLISHED"
        assert after["published_at_iso"].startswith("2026-08-05T09:30:00")
        assert after["published_by_user_id"] == "u_publisher_1"
        assert after["version"] == 2


MIXED_SCOPE = {
    "climate_zone": "MIXED",
    "store_format": "SUPERCENTER",
    "season": "SUMMER",
    "heating_setpoint_f": 68.0,
    "deadband_f": 2.0,
}


def _superseded_predecessor(api):
    """Standard A is driven to SUPERSEDED by the publication of successor B."""
    fx.set_clock(api)
    predecessor = fx.create_standard(
        api, **MIXED_SCOPE, cooling_setpoint_f=74.0, lighting_lux_target=750
    )
    fx.publish_standard(api, predecessor["id"])
    successor = fx.create_standard(
        api, **MIXED_SCOPE, cooling_setpoint_f=75.0, lighting_lux_target=780,
        supersedes_standard_id=predecessor["id"],
    )
    published_successor = fx.publish_standard(api, successor["id"])
    return {
        "predecessor_id": predecessor["id"],
        "successor_id": successor["id"],
        "successor": published_successor,
    }


class TestSupersededStandardIsTerminal:
    def test_the_cascade_drives_the_predecessor_into_its_terminal_state(self, api):
        """The successor's publication supersedes the incumbent.

        The PRD states: "When the predecessor check passes and a predecessor
        exists, four things follow in order. First, the predecessor moves
        `PUBLISHED → SUPERSEDED` and its `version` increments."

        Design: Corner/state_machines/superseded_standard_admits_no_further_transition
        """
        ctx = _superseded_predecessor(api)

        predecessor = get_success_data(
            api.get_setpoint_standard(ctx["predecessor_id"], fx.MANAGER)
        )

        assert ctx["successor"]["status"] == "PUBLISHED"
        assert ctx["successor"]["revision"] == 2
        assert predecessor["status"] == "SUPERSEDED"

    def test_a_superseded_standard_cannot_be_published_again(self, api):
        """The terminal state refuses the only transition the API offers.

        The PRD states: "Publishing anything that is already `PUBLISHED` or
        already `SUPERSEDED` is refused with `ERR_STANDARD_STATE_INVALID`".

        Design: Corner/state_machines/superseded_standard_admits_no_further_transition
        """
        ctx = _superseded_predecessor(api)
        before = get_success_data(api.get_setpoint_standard(ctx["predecessor_id"], fx.MANAGER))

        response = api.publish_setpoint_standard(ctx["predecessor_id"], fx.MANAGER)

        validate_error(response, ApiErrorId.ERR_STANDARD_STATE_INVALID.value, 409)
        after = get_success_data(api.get_setpoint_standard(ctx["predecessor_id"], fx.MANAGER))
        assert after["status"] == "SUPERSEDED"
        assert after["published_at_iso"] == before["published_at_iso"]
        rows, meta = fx.list_standards(api, status="PUBLISHED")
        assert [row["id"] for row in rows] == [ctx["successor_id"]]
        assert meta["total_count"] == 1


DAIRY_CASE = {
    "case_code": "CASE-FD",
    "case_type": "MEDIUM_TEMP",
    "product_class": "DAIRY",
    "alarm_high_f": 41.0,
    "alarm_low_f": 28.0,
    "product_value_usd": 4200.00,
}


def _fifteen_minute_open_excursion(api):
    """A single fifteen-minute breach run: excursion OPEN, case ALARM, store
    CONSTRAINED and no disposition mandated."""
    ctx = fx.setup_open_excursion(
        api, clock="2026-08-01T10:20:00Z", store_overrides={"code": "STR-FD"},
        case_overrides=dict(DAIRY_CASE), breach_temp_f=42.0,
        first_iso="2026-08-01T10:00:00Z", second_iso="2026-08-01T10:15:00Z",
    )
    ctx["second_reading"] = ctx["readings"][-1]
    return ctx


class TestExcursionCloseRequiresDocumentation:
    def test_closing_an_undocumented_excursion_is_refused(self, api):
        """Missing paperwork outranks nothing else, because the state is legal.

        The PRD states: "Closure is also the `FoodSafetyOfficer`'s, and it is
        gated on the paperwork being complete: both `disposition` and
        `corrective_action_note` must already be recorded, and closing an
        excursion missing either is refused with
        `ERR_FOOD_SAFETY_DOC_INCOMPLETE` (HTTP 422)."

        Design: Corner/state_machines/excursion_close_without_documentation_is_refused
        """
        ctx = _fifteen_minute_open_excursion(api)
        reading = ctx["second_reading"]
        assert reading["excursion_state"] == "OPEN"
        assert reading["exposure_minutes"] == 15
        assert reading["monitoring_state"] == "ALARM"
        assert reading["consecutive_breach_count"] == 2
        assert reading["store_energy_posture"] == "CONSTRAINED"

        response = api.close_excursion(ctx["excursion_id"], fx.OFFICER)

        validate_error(response, ApiErrorId.ERR_FOOD_SAFETY_DOC_INCOMPLETE.value, 422)

    def test_the_refusal_leaves_the_excursion_the_case_and_the_store_alone(self, api):
        """No timestamp, no disposition and no posture release.

        The PRD states: "A successful closure moves the excursion from whichever
        non-closed state it held — `OPEN`, `ACKNOWLEDGED`, `ESCALATED` or
        `DISPOSITION_REQUIRED` — to `CLOSED`, and stamps `closed_at_iso` from the
        clock."

        Design: Corner/state_machines/excursion_close_without_documentation_is_refused
        """
        ctx = _fifteen_minute_open_excursion(api)

        api.close_excursion(ctx["excursion_id"], fx.OFFICER)

        excursion = fx.read_excursion(api, ctx["excursion_id"])
        case = get_success_data(api.get_refrigeration_case(ctx["case_id"], fx.OFFICER))
        store = fx.read_store(api, ctx["store_id"])
        assert excursion["state"] == "OPEN"
        assert excursion["closed_at_iso"] is None
        assert excursion["disposition"] is None
        assert excursion["corrective_action_note"] is None
        assert excursion["mandatory_disposition"] == "NONE"
        assert case["monitoring_state"] == "ALARM"
        assert store["energy_posture"] == "CONSTRAINED"
        assert store["alarm_case_count"] == 1


class TestExcursionCloseCascades:
    def test_documenting_records_the_officer_without_advancing_the_state(self, api):
        """Documentation is a distinct step from closure.

        The PRD states: "Documentation is accepted in any state other than
        `CLOSED`, and it explicitly does **not** change the excursion's state — an
        excursion that was `DISPOSITION_REQUIRED` before documentation is still
        `DISPOSITION_REQUIRED` after it."

        Design: Corner/state_machines/excursion_close_rearms_the_case_and_releases_the_store
        """
        ctx = _fifteen_minute_open_excursion(api)

        documented = get_success_data(
            api.document_excursion_disposition(
                ctx["excursion_id"],
                f.document_disposition_payload(
                    "RETAIN",
                    "door gasket reseated; product temperature verified in range",
                ),
                make_food_safety_officer_headers("u_fso_1"),
            )
        )

        assert documented["state"] == "OPEN"
        assert documented["disposition"] == "RETAIN"
        assert documented["documented_by_user_id"] == "u_fso_1"
        assert documented["documented_at_iso"].startswith("2026-08-01T10:20:00")
        assert documented["closed_at_iso"] is None

    def test_closure_stamps_the_clock_at_close_and_preserves_the_evidence(self, api):
        """closed_at_iso reads the clock at closure, not the documentation time.

        The PRD states: "Closing anything already `CLOSED` is
        `ERR_EXCURSION_STATE_INVALID`. A successful closure moves the excursion
        from whichever non-closed state it held — `OPEN`, `ACKNOWLEDGED`,
        `ESCALATED` or `DISPOSITION_REQUIRED` — to `CLOSED`, and stamps
        `closed_at_iso` from the clock."

        Design: Corner/state_machines/excursion_close_rearms_the_case_and_releases_the_store
        """
        ctx = _fifteen_minute_open_excursion(api)
        get_success_data(
            api.document_excursion_disposition(
                ctx["excursion_id"],
                f.document_disposition_payload(
                    "RETAIN",
                    "door gasket reseated; product temperature verified in range",
                ),
                make_food_safety_officer_headers("u_fso_1"),
            )
        )
        fx.set_clock(api, "2026-08-01T11:00:00Z")

        closed = get_success_data(
            api.close_excursion(ctx["excursion_id"], make_food_safety_officer_headers("u_fso_1"))
        )

        assert closed["state"] == "CLOSED"
        assert closed["closed_at_iso"].startswith("2026-08-01T11:00:00")
        assert closed["disposition"] == "RETAIN"
        assert closed["exposure_minutes"] == 15
        assert closed["peak_temp_f"] == pytest.approx(42.0, abs=0.05)

    def test_closure_rearms_the_case_and_releases_the_store_to_normal(self, api):
        """Both declared cascades run in the same request.

        The PRD states: "The owning refrigeration case rearms `ALARM → ARMED`, but
        only when no other non-closed excursion remains on that case, and rearming
        resets `consecutive_breach_count` to zero and decrements the store's
        `alarm_case_count`. Then the owning store recomputes its posture."

        Design: Corner/state_machines/excursion_close_rearms_the_case_and_releases_the_store
        """
        ctx = _fifteen_minute_open_excursion(api)
        get_success_data(
            api.document_excursion_disposition(
                ctx["excursion_id"],
                f.document_disposition_payload(
                    "RETAIN",
                    "door gasket reseated; product temperature verified in range",
                ),
                make_food_safety_officer_headers("u_fso_1"),
            )
        )
        fx.set_clock(api, "2026-08-01T11:00:00Z")

        get_success_data(
            api.close_excursion(ctx["excursion_id"], make_food_safety_officer_headers("u_fso_1"))
        )

        case = get_success_data(api.get_refrigeration_case(ctx["case_id"], fx.OFFICER))
        store = fx.read_store(api, ctx["store_id"])
        closed_rows, closed_meta = fx.list_excursions(api, ctx["case_id"], state="CLOSED")
        assert case["monitoring_state"] == "ARMED"
        assert case["consecutive_breach_count"] == 0
        assert case["last_reading_temp_f"] == pytest.approx(42.0, abs=0.05)
        assert store["energy_posture"] == "NORMAL"
        assert store["alarm_case_count"] == 0
        assert store["bms_status"] == "ACTIVE"
        assert closed_meta["total_count"] == 1
        assert len(closed_rows) == 1


URGENT_REFRIGERATION_FAULT = {
    "equipment_ref": "RACK-A",
    "equipment_class": "REFRIGERATION",
    "fault_code": "SUCTION-HI",
    "severity": "MAJOR",
    "occurrence_count": 3,
    "affected_load_kw": 120.0,
}

COMPLETION_NOTE = "compressor valve replaced; suction pressure normal"


def _completed_urgent_work_order(api):
    """An urgent refrigeration work order raised, then completed."""
    ctx = fx.setup_commissioned_store(
        api, clock="2026-08-01T08:00:00Z", code="STR-WT",
    )
    fault = fx.create_fault(api, ctx["store_id"], **URGENT_REFRIGERATION_FAULT)
    triage = fx.triage_fault(api, fault["id"])
    completed = get_success_data(
        api.complete_work_order(
            triage["work_order_id"],
            make_maintenance_tech_headers("u_tech_wt"),
            f.complete_work_order_payload(COMPLETION_NOTE),
        )
    )
    ctx["fault_id"] = fault["id"]
    ctx["fault_score"] = fault["fault_score"]
    ctx["triage"] = triage
    ctx["work_order_id"] = triage["work_order_id"]
    ctx["completed"] = completed
    return ctx


class TestCompletedWorkOrderIsTerminal:
    def test_completion_resolves_the_fault_and_releases_the_urgent_counter_once(self, api):
        """The three completion cascades each fire exactly once.

        The PRD states: "Completion carries a `completion_note` and is legal from
        `OPEN` or `SCHEDULED`, moving the order to `COMPLETED` and stamping
        `completed_at_iso` from the clock. Three cascades follow. The owning fault
        moves `TRIAGED → RESOLVED`. Because that fault is no longer triaged, the
        store's `urgent_work_order_count` decrements when the completed order was
        `URGENT`."

        Design: Corner/state_machines/completed_work_order_refuses_schedule_and_completion
        """
        ctx = _completed_urgent_work_order(api)

        assert ctx["fault_score"] == pytest.approx(82.5, abs=0.05)
        assert ctx["triage"]["work_order_state"] == "OPEN"
        assert ctx["triage"]["work_order_priority"] == "URGENT"
        assert ctx["triage"]["urgent_work_order_count"] == 1
        assert ctx["completed"]["state"] == "COMPLETED"
        assert ctx["completed"]["completed_at_iso"].startswith("2026-08-01T08:00:00")
        fault = get_success_data(api.get_fault_diagnostic(ctx["fault_id"], fx.TECH))
        store = fx.read_store(api, ctx["store_id"])
        assert fault["state"] == "RESOLVED"
        assert store["urgent_work_order_count"] == 0

    def test_scheduling_a_completed_order_is_refused(self, api):
        """The terminal order is locked against rescheduling.

        The PRD states: "A `COMPLETED` work order is locked and yields
        `ERR_WORK_ORDER_STATE_INVALID`."

        Design: Corner/state_machines/completed_work_order_refuses_schedule_and_completion
        """
        ctx = _completed_urgent_work_order(api)

        response = api.schedule_work_order(
            ctx["work_order_id"],
            f.schedule_work_order_payload("2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z"),
            fx.TECH,
        )

        validate_error(response, ApiErrorId.ERR_WORK_ORDER_STATE_INVALID.value, 409)
        rows, _ = fx.list_work_orders(api, ctx["fault_id"])
        order = fx.find_row(rows, ctx["work_order_id"])
        assert order["scheduled_start_iso"] is None
        assert order["scheduled_end_iso"] is None

    def test_a_second_completion_is_refused_and_never_double_releases(self, api):
        """The counter moved exactly once and the note is unchanged.

        The PRD states: "What completion does *not* do is repair the building
        management system: `bms_status` remains `DEGRADED` and requires an explicit
        re-commissioning and re-activation, as §3.2 sets out."

        Design: Corner/state_machines/completed_work_order_refuses_schedule_and_completion
        """
        ctx = _completed_urgent_work_order(api)

        response = api.complete_work_order(
            ctx["work_order_id"], fx.TECH, f.complete_work_order_payload("second attempt")
        )

        validate_error(response, ApiErrorId.ERR_WORK_ORDER_STATE_INVALID.value, 409)
        rows, _ = fx.list_work_orders(api, ctx["fault_id"])
        order = fx.find_row(rows, ctx["work_order_id"])
        store = fx.read_store(api, ctx["store_id"])
        assert order["completion_note"] == COMPLETION_NOTE
        assert store["urgent_work_order_count"] == 0
        assert store["bms_status"] == "DEGRADED"
        assert store["energy_posture"] == "CONSTRAINED"


PRODUCE_CASE = {
    "case_code": "CASE-BY",
    "case_type": "MEDIUM_TEMP",
    "product_class": "PRODUCE",
    "alarm_high_f": 41.0,
    "alarm_low_f": 28.0,
    "product_value_usd": 3100.00,
}


def _bypassed_case_with_a_banked_breach(api):
    """One breach banked below the grace threshold, then the case is bypassed."""
    ctx = fx.setup_case_on_commissioned_store(
        api, clock="2026-08-01T10:00:00Z", store_overrides={"code": "STR-BY"},
        case_overrides=dict(PRODUCE_CASE),
    )
    ctx["first_reading"] = fx.post_reading(
        api, ctx["case_id"], ctx["store_id"], 42.0, "2026-08-01T10:00:00Z"
    )
    ctx["bypassed"] = get_success_data(
        api.set_monitoring_state(
            ctx["case_id"], f.monitoring_state_payload("BYPASSED"), fx.TECH
        )
    )
    return ctx


class TestBypassedCaseSuppressesEvaluation:
    def test_the_bypass_resets_a_breach_run_already_in_progress(self, api):
        """One banked breach is wiped by the transition into BYPASSED.

        The PRD states: "A `MaintenanceTech` who needs to service a case takes it
        out of monitoring by supplying a `target_state` of `BYPASSED`, and returns
        it by supplying `ARMED`. Both transitions reset `consecutive_breach_count`
        to zero."

        Design: Corner/state_machines/bypassed_case_readings_are_stored_but_never_evaluated
        """
        ctx = _bypassed_case_with_a_banked_breach(api)

        assert ctx["first_reading"]["consecutive_breach_count"] == 1
        assert ctx["first_reading"]["monitoring_state"] == "ARMED"
        assert ctx["first_reading"]["excursion_id"] is None
        assert ctx["bypassed"]["monitoring_state"] == "BYPASSED"
        assert ctx["bypassed"]["consecutive_breach_count"] == 0

    def test_three_further_breaches_open_no_excursion_while_bypassed(self, api):
        """Stored but not evaluated: no excursion, no posture movement.

        The PRD states: "While a case is `BYPASSED`, readings posted against it are
        still stored — `last_reading_temp_f` and `last_reading_iso` are updated as
        usual — but they take no part in breach evaluation and can neither open nor
        extend an excursion."

        Design: Corner/state_machines/bypassed_case_readings_are_stored_but_never_evaluated
        """
        ctx = _bypassed_case_with_a_banked_breach(api)
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 44.0, "2026-08-01T10:15:00Z")
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 45.0, "2026-08-01T10:30:00Z")

        last = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 46.5, "2026-08-01T10:45:00Z"
        )

        assert last["monitoring_state"] == "BYPASSED"
        assert last["consecutive_breach_count"] == 0
        assert last["last_reading_temp_f"] == pytest.approx(46.5, abs=0.05)
        assert last["last_reading_iso"].startswith("2026-08-01T10:45:00")
        assert last["excursion_id"] is None
        assert last["excursion_state"] is None
        assert last["exposure_minutes"] is None
        assert last["peak_temp_f"] is None
        assert last["mandatory_disposition"] is None
        assert last["store_energy_posture"] == "NORMAL"
        assert last["dr_events_opted_out"] == 0
        assert last["overrides_revoked"] == 0

    def test_the_case_holds_no_excursion_row_and_the_store_no_alarm(self, api):
        """Three breaches produced nothing to inspect.

        The PRD states: "Excursions of a case can be listed with a filter on
        `state`, and any single excursion can be retrieved to inspect its exposure,
        mandate and documentation fields."

        Design: Corner/state_machines/bypassed_case_readings_are_stored_but_never_evaluated
        """
        ctx = _bypassed_case_with_a_banked_breach(api)
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 44.0, "2026-08-01T10:15:00Z")
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 45.0, "2026-08-01T10:30:00Z")
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 46.5, "2026-08-01T10:45:00Z")

        rows, meta = fx.list_excursions(api, ctx["case_id"])
        store = fx.read_store(api, ctx["store_id"])

        assert rows == []
        assert meta["total_count"] == 0
        assert store["alarm_case_count"] == 0
        assert store["energy_posture"] == "NORMAL"
