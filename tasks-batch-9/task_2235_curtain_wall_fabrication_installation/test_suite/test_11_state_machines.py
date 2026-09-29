"""The twelve machines: where each row starts, which triggers each state
declares, which states refuse everything, and what one accepted trigger does to
its neighbours."""
import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CLOCK_FIELD_TEST_DAY,
    CLOCK_HANG_DAY,
    CLOCK_T0,
    USER_IDS,
)
from test_helpers.test_users import TEST_USERS, make_architect_of_record_headers

PM = TEST_USERS["cw_project_manager_headers"]
DETAILER = TEST_USERS["cw_detailer_headers"]
ARCHITECT = TEST_USERS["architect_of_record_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
STRUCTURAL = TEST_USERS["structural_contractor_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]
QC = TEST_USERS["qc_inspector_headers"]


class TestInitialStates:
    """Twelve freshly created rows, twelve declared entry points."""

    def test_every_family_lands_on_its_own_declared_entry_state(self):
        """A submittal opens SUBMITTED at revision cycle 1, an order ORDERED, a
        release RELEASED, a lot BATCHED, a mockup and a field test SCHEDULED, a
        survey PENDING_SURVEY, a zone PLANNED and NOT_TIGHT, a defect OPEN, a
        reservation RESERVED, a draw DRAWN and a crew day POSTED at index 1.

        PRD: "Submittals open in state `SUBMITTED` with `revision_cycle` 1, `open_notes_count` 0, and `sealed_by_user_id`, `seal_license_no`, `sealed_at`, `reviewed_by_user_id`, `review_decision` and `escalation_ref` all null."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        ctx = fx.setup_ready_for_release()
        zone_id = ctx["zone_ids"][0]
        release = fx.create_release(ctx)
        lot = ctx["lots"][zone_id][0]

        second_submittal = validate_success(
            api_client.create_submittal(
                f.create_submittal_payload(
                    ctx["package_id"],
                    submittal_type="COATING_SPEC",
                    title="Coating spec set",
                    drawing_set_ref="CS-001",
                    delegated_design_scope=False,
                ),
                DETAILER,
            ),
            expected_status=201,
        )
        assert second_submittal["state"] == "SUBMITTED"
        assert second_submittal["revision_cycle"] == 1
        assert second_submittal["sealed_by_user_id"] is None
        assert second_submittal["open_notes_count"] == 0

        second_order = validate_success(
            api_client.create_glass_order(
                f.create_glass_order_payload(
                    ctx["package_id"],
                    supplier_name="Guardian Glass",
                    coating_code="LOWE-272",
                    quoted_lead_time_days=90,
                    ordered_lites=240,
                ),
                PROCUREMENT,
            ),
            expected_status=201,
        )
        assert second_order["state"] == "ORDERED"
        assert second_order["coating_revision_count"] == 0
        assert second_order["expedite_tier"] == 0
        assert second_order["received_lites"] == 0

        assert release["state"] == "RELEASED"
        assert lot["fabrication_status"] == "BATCHED"
        assert lot["hold_reason"] is None

        survey = fx.open_embed_survey(ctx, zone_id, planned_anchor_count=72)
        assert survey["state"] == "PENDING_SURVEY"
        assert survey["survey_attempt_count"] == 0

        second_mockup = fx.book_mockup(
            ctx, window_start="2026-08-07T06:00:00Z", window_end="2026-08-07T20:00:00Z"
        )
        assert second_mockup["state"] == "SCHEDULED"

        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["install_status"] == "PLANNED"
        assert zone["weather_status"] == "NOT_TIGHT"

        field_test = fx.schedule_field_test(
            ctx, zone_id, "WATER_AAMA_501_2", "2026-08-13T08:00:00Z"
        )
        assert field_test["state"] == "SCHEDULED"
        assert field_test["outcome_reason"] is None

        defect = fx.raise_defect(
            ctx,
            user_id=USER_IDS["QC_3"],
            zone_id=zone_id,
            origin="PUNCH_LIST",
            severity="MINOR",
            description="gasket dressing at grid 3",
        )
        assert defect["status"] == "OPEN"
        assert defect["reinspect_fail_count"] == 0

        fx.create_rig(ctx)
        reservation = fx.create_reservation(
            ctx, zone_id, "2026-08-10T06:00:00Z", "2026-08-10T18:00:00Z"
        )
        assert reservation["status"] == "RESERVED"

        crew_day = fx.post_crew_day(
            ctx, zone_id, work_date="2026-08-10", crew_size=4, shift_hours=9.0,
            panels_installed=10,
        )
        assert crew_day["status"] == "POSTED"
        assert crew_day["day_index"] == 1

        draw = fx.create_breakage_draw(ctx, lot["id"], 3, reason="FIELD_BREAKAGE")
        assert draw["status"] == "DRAWN"
        assert fx.refresh_glass_order(ctx)["available_stock_lites"] == 4


class TestEmbedSurveyWalk:
    """The one machine with a self-loop on its rejection state."""

    def test_two_rejections_then_an_acceptance_then_the_pour_count_four_versions(self):
        """A 31.0 mm deviation rejects, a deviation exactly equal to the 25.0 mm
        tolerance rejects again on a self-loop rather than accepting, 24.9 mm
        accepts on the third attempt, and the pour lands the row on its terminal
        state after exactly four versioned writes.

        PRD: "A rejected survey may be re-surveyed after embed remediation, and the re-survey either moves `REJECTED` → `ACCEPTED` under the same two conditions or self-loops `REJECTED` → `REJECTED`, closing the revision cycle."

        Design: Corner/state_machines/embed_survey_walks_pending_to_rejected_to_accepted_to_poured
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        zone = fx.add_zone_a(ctx)
        survey = fx.open_embed_survey(ctx, zone["id"], planned_anchor_count=72)
        assert survey["state"] == "PENDING_SURVEY"
        assert survey["version"] == 1

        first = fx.record_survey(
            ctx, zone["id"], surveyed_anchor_count=72, max_deviation_mm=31.0
        )
        assert first["state"] == "REJECTED"
        assert first["survey_attempt_count"] == 1
        assert first["version"] == 2

        at_tolerance = fx.record_survey(
            ctx, zone["id"], surveyed_anchor_count=72, max_deviation_mm=25.0
        )
        assert at_tolerance["state"] == "REJECTED"
        assert at_tolerance["survey_attempt_count"] == 2
        assert at_tolerance["version"] == 3

        accepted = fx.record_survey(
            ctx, zone["id"], surveyed_anchor_count=72, max_deviation_mm=24.9
        )
        assert accepted["state"] == "ACCEPTED"
        assert accepted["survey_attempt_count"] == 3
        assert accepted["max_deviation_mm"] == pytest.approx(24.9, abs=0.01)
        assert accepted["version"] == 4

        poured = fx.confirm_pour(ctx, zone["id"], "2026-08-06T12:00:00Z")
        assert poured["state"] == "POURED"
        assert poured["poured_at"] == "2026-08-06T12:00:00.000Z"
        assert poured["version"] == 5

    def test_a_short_anchor_count_rejects_even_with_a_tiny_deviation(self):
        """Acceptance is a conjunction, so 60 surveyed anchors against 72 planned
        rejects even though the 1.0 mm deviation is far inside the tolerance.

        PRD: "The outcome is `ACCEPTED` only when both conditions hold: the `surveyed_anchor_count` equals the `planned_anchor_count`, and the `max_deviation_mm` is strictly less than the survey's `tolerance_mm`."

        Design: Corner/state_machines/embed_survey_walks_pending_to_rejected_to_accepted_to_poured
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        zone = fx.add_zone_a(ctx)
        fx.open_embed_survey(ctx, zone["id"], planned_anchor_count=72)

        short = fx.record_survey(
            ctx, zone["id"], surveyed_anchor_count=60, max_deviation_mm=1.0
        )
        assert short["state"] == "REJECTED"
        assert short["surveyed_anchor_count"] == 60
        assert short["survey_attempt_count"] == 1


class TestTriggersAbsentFromTheCurrentState:
    """A trigger the state does not declare, on five machines."""

    @staticmethod
    def _released_zone_with_an_unsealed_second_submittal():
        ctx = fx.setup_released_zone()
        zone_id = ctx["zone_ids"][0]
        second = get_success_data(
            api_client.create_submittal(
                f.create_submittal_payload(
                    ctx["package_id"],
                    title="Delegated bracket calculations",
                    drawing_set_ref="SC-001",
                    delegated_design_scope=True,
                ),
                DETAILER,
            )
        )
        fx.create_rig(ctx)
        fx.create_reservation(
            ctx, zone_id, "2026-08-10T06:00:00Z", "2026-08-10T18:00:00Z"
        )
        fx.set_clock(CLOCK_HANG_DAY)
        return ctx, zone_id, second

    def test_four_undeclared_triggers_report_invalid_state_and_the_zone_reports_its_own(self):
        """Review and close-notes on a SUBMITTED set, a BATCHED lot asked to ship
        and close-out on a package still fabricating all report the invalid-state
        code, while the hang on a PLANNED zone reports the sequence violation
        instead — and every rejection leaves its row's version untouched.

        PRD: "State checks, in this internal order: the entity's current state has no transition for this trigger — `ERR_INVALID_STATE` (409), on every action endpoint that declares a transition; then the entity is already in a terminal state — `ERR_TERMINAL_STATE` (409), on every action endpoint against an entity with terminal states, the terminal values being `APPROVED`, `VOIDED`, `CLOSED`, `CLOSED_OUT`, `PASSED`, `FAILED`, `SHIPPED`, `POURED`, `CONSUMED`, `CANCELLED` and `WAIVED`; then the zone's `install_status` does not match the transition's from-state — `ERR_ZONE_SEQUENCE_VIOLATION` (409), on anchor setting, panel hanging and weather-tight certification; then an escalated submittal resubmitted without a dispute reference — `ERR_DISPUTE_REF_REQUIRED` (409); then a coating revision attempted after receipt — `ERR_COATING_REVISION_AFTER_RECEIPT` (409)."

        Design: Corner/state_machines/triggers_absent_from_the_current_state_are_rejected
        """
        ctx, zone_id, second = self._released_zone_with_an_unsealed_second_submittal()
        lot = ctx["lots"][zone_id][0]
        reservation_id = ctx["reservations"][zone_id]["id"]
        zone_before = get_success_data(api_client.get_installation_zone(zone_id, PM))
        package_before = fx.refresh_package(ctx)

        review = api_client.review_submittal(
            second["id"],
            f.review_payload("APPROVED"),
            make_architect_of_record_headers(USER_IDS["ARCHITECT"]),
        )
        error = validate_error(
            review, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_SEAL_REQUIRED.value

        validate_error(
            api_client.close_submittal_notes(
                second["id"], f.close_notes_payload(1), ARCHITECT
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            expected_status=409,
        )
        validate_error(
            api_client.advance_fabrication(
                lot["id"], f.advance_fabrication_payload("SHIPPED"), SUPERINTENDENT
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            expected_status=409,
        )
        validate_error(
            api_client.close_out_package(
                ctx["package_id"], f.close_out_payload(), PM
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            expected_status=409,
        )

        hang = api_client.hang_panels(
            zone_id, f.hang_panels_payload(reservation_id), SUPERINTENDENT
        )
        sequence = validate_error(
            hang, ApiErrorId.ERR_ZONE_SEQUENCE_VIOLATION.value, expected_status=409
        )
        assert sequence["error_id"] != ApiErrorId.ERR_PANEL_LOTS_NOT_SHIPPED.value

        assert (
            get_success_data(api_client.get_submittal(second["id"], DETAILER))["state"]
            == "SUBMITTED"
        )
        assert (
            get_success_data(api_client.get_panel_lot(lot["id"], PM))["fabrication_status"]
            == "BATCHED"
        )
        zone_after = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone_after["version"] == zone_before["version"]
        assert zone_after["install_status"] == "PLANNED"
        package_after = fx.refresh_package(ctx)
        assert package_after["version"] == package_before["version"]
        assert package_after["state"] == "IN_FABRICATION"


class TestTerminalRows:
    """Six terminal rows, six refusals."""

    def test_terminal_submittal_survey_lot_and_reservation_refuse_every_trigger(self):
        """An APPROVED submittal refuses resubmit, reopen-review, start-review and
        review; a POURED survey refuses another survey; a SHIPPED lot refuses
        another advance; and a CONSUMED reservation refuses cancellation.

        PRD: "`APPROVED` is terminal: the submittal accepts no further transitions."

        Design: Corner/state_machines/terminal_rows_accept_no_further_trigger
        """
        ctx = fx.setup_hung_zone()
        zone_id = ctx["zone_ids"][0]
        submittal_id = ctx["submittal_id"]
        survey = ctx["surveys"][zone_id]
        lot = ctx["lots"][zone_id][0]
        reservation_id = ctx["reservations"][zone_id]["id"]

        shipped_before = get_success_data(api_client.get_panel_lot(lot["id"], PM))
        assert shipped_before["fabrication_status"] == "SHIPPED"

        validate_error(
            api_client.resubmit_submittal(
                submittal_id, f.resubmit_payload("SD-001-R1"), DETAILER
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )
        validate_error(
            api_client.reopen_submittal_review(
                submittal_id,
                f.reopen_review_payload("late comment"),
                make_architect_of_record_headers(USER_IDS["ARCHITECT"]),
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )
        validate_error(
            api_client.start_submittal_review(
                submittal_id,
                f.start_review_payload(),
                make_architect_of_record_headers(USER_IDS["ARCHITECT"]),
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )
        validate_error(
            api_client.review_submittal(
                submittal_id,
                f.review_payload("REVISION_REQUIRED"),
                make_architect_of_record_headers(USER_IDS["ARCHITECT"]),
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )
        assert (
            get_success_data(api_client.get_submittal(submittal_id, DETAILER))["state"]
            == "APPROVED"
        )

        validate_error(
            api_client.record_embed_survey(
                survey["id"], f.record_survey_payload(72, 5.0), STRUCTURAL
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )
        poured = get_success_data(api_client.get_embed_survey(survey["id"], STRUCTURAL))
        assert poured["state"] == "POURED"
        assert poured["survey_attempt_count"] == 1

        validate_error(
            api_client.advance_fabrication(
                lot["id"], f.advance_fabrication_payload("GLAZED"), SUPERINTENDENT
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )
        assert (
            get_success_data(api_client.get_panel_lot(lot["id"], PM))["shipped_at"]
            == shipped_before["shipped_at"]
        )

        validate_error(
            api_client.cancel_hoist_reservation(
                reservation_id, f.cancel_reservation_payload("no longer needed"),
                SUPERINTENDENT,
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )
        assert (
            get_success_data(api_client.get_hoist_reservation(reservation_id, PM))["status"]
            == "CONSUMED"
        )


class TestReplayedTriggers:
    """The API is deliberately non-idempotent."""

    @staticmethod
    def _hung_zone_with_one_passed_water_test():
        ctx = fx.setup_hung_zone()
        zone_id = ctx["zone_ids"][0]
        fx.set_clock(CLOCK_FIELD_TEST_DAY)
        water = fx.schedule_field_test(
            ctx, zone_id, "WATER_AAMA_501_2", CLOCK_FIELD_TEST_DAY
        )
        water = fx.record_field_test(
            ctx, water["id"], f.water_result_payload(False), USER_IDS["QC_2"]
        )
        return ctx, zone_id, water

    def test_replaying_the_decision_the_pour_and_the_result_all_fail_without_side_effects(self):
        """A second system decision, a second pour confirmation carrying a later
        instant and a second result recording are each rejected, the three rows
        keep their first values, and not one version advances on the replays.

        PRD: "Attempting the decision a second time, or on a package that has already left `DESIGN_ASSIST`, fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/replaying_a_completed_trigger_is_rejected_not_absorbed
        """
        ctx, zone_id, water = self._hung_zone_with_one_passed_water_test()
        survey = ctx["surveys"][zone_id]
        package_before = fx.refresh_package(ctx)
        survey_before = get_success_data(
            api_client.get_embed_survey(survey["id"], STRUCTURAL)
        )
        test_before = get_success_data(api_client.get_field_test(water["id"], QC))

        validate_error(
            api_client.decide_system(
                ctx["package_id"], f.system_decision_payload("UNITIZED"), PM
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            expected_status=409,
        )
        validate_error(
            api_client.confirm_pour(
                survey["id"], f.confirm_pour_payload("2026-08-06T18:00:00Z"), STRUCTURAL
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )
        validate_error(
            api_client.record_field_test_result(
                water["id"], f.water_result_payload(False), QC
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )

        package_after = fx.refresh_package(ctx)
        assert package_after["system_type"] == "UNITIZED"
        assert package_after["planned_shop_hours"] == pytest.approx(4950.00, abs=0.01)
        assert package_after["version"] == package_before["version"]

        survey_after = get_success_data(
            api_client.get_embed_survey(survey["id"], STRUCTURAL)
        )
        assert survey_after["poured_at"] == "2026-08-06T12:00:00.000Z"
        assert survey_after["version"] == survey_before["version"]

        test_after = get_success_data(api_client.get_field_test(water["id"], QC))
        assert test_after["result_recorded_at"] == test_before["result_recorded_at"]
        assert test_after["version"] == test_before["version"]

    def test_an_identical_zone_payload_creates_a_second_distinct_row(self):
        """There is no idempotency key anywhere in the contract, so posting the
        same zone payload twice yields two independent rows.

        PRD: "Installation zones may be registered at any time, and the project manager typically lays out the whole elevation before the system decision is taken."

        Design: Corner/state_machines/replaying_a_completed_trigger_is_rejected_not_absorbed
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        payload = f.create_installation_zone_payload(ctx["package_id"])

        first = validate_success(
            api_client.create_installation_zone(payload, PM), expected_status=201
        )
        second = validate_success(
            api_client.create_installation_zone(payload, PM), expected_status=201
        )
        assert first["id"] != second["id"]
        assert first["floor_number"] == second["floor_number"]
        assert second["version"] == 1


class TestTransitionPreconditions:
    """Four preconditions on three machines, four distinct codes."""

    def test_each_precondition_reports_its_own_code_and_the_seal_survives_the_refusal(self):
        """An unsealed delegated set refuses the review start for the seal, an
        unaccepted survey refuses the pour, the engineer who sealed cannot start
        the review of his own set, and an anchor step over a rejected survey
        refuses for the embeds — after which the architect's review start lands.

        PRD: "If the submittal's `submittal_type` is `STRUCTURAL_CALCULATION`, or its `delegated_design_scope` is true, then `sealed_by_user_id` must not be null; an unsealed delegated-design set is refused with `ERR_SEAL_REQUIRED`."

        Design: Corner/state_machines/each_transition_precondition_maps_to_its_own_error
        """
        ctx = fx.setup_qualified_package()
        zone = fx.add_zone_a(ctx)
        submittal = fx.create_submittal(ctx, delegated_design_scope=True)
        survey = fx.open_embed_survey(ctx, zone["id"], planned_anchor_count=72)

        validate_error(
            api_client.start_submittal_review(
                submittal["id"],
                f.start_review_payload(),
                make_architect_of_record_headers(USER_IDS["ARCHITECT"]),
            ),
            ApiErrorId.ERR_SEAL_REQUIRED.value,
            expected_status=422,
        )
        assert (
            get_success_data(api_client.get_submittal(submittal["id"], DETAILER))["state"]
            == "SUBMITTED"
        )

        early_pour = api_client.confirm_pour(
            survey["id"], f.confirm_pour_payload("2026-08-06T12:00:00Z"), STRUCTURAL
        )
        pour_error = validate_error(
            early_pour, ApiErrorId.ERR_POUR_BEFORE_ACCEPTANCE.value, expected_status=422
        )
        assert pour_error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value

        sealed = fx.seal_submittal(ctx, submittal["id"], user_id=USER_IDS["ENGINEER"])
        assert sealed["sealed_by_user_id"] == USER_IDS["ENGINEER"]
        assert sealed["seal_license_no"] == "PE-44821"

        validate_error(
            api_client.start_submittal_review(
                submittal["id"],
                f.start_review_payload(),
                make_architect_of_record_headers(USER_IDS["ENGINEER"]),
            ),
            ApiErrorId.ERR_SEALER_CANNOT_REVIEW.value,
            expected_status=422,
        )

        rejected = fx.record_survey(
            ctx, zone["id"], surveyed_anchor_count=72, max_deviation_mm=31.0
        )
        assert rejected["state"] == "REJECTED"
        validate_error(
            api_client.set_anchors(zone["id"], f.set_anchors_payload(), SUPERINTENDENT),
            ApiErrorId.ERR_EMBED_SURVEY_NOT_ACCEPTED.value,
            expected_status=422,
        )
        assert (
            get_success_data(api_client.get_installation_zone(zone["id"], PM))[
                "install_status"
            ]
            == "PLANNED"
        )

        started = validate_success(
            api_client.start_submittal_review(
                submittal["id"],
                f.start_review_payload(),
                make_architect_of_record_headers(USER_IDS["ARCHITECT"]),
            ),
            expected_status=200,
        )
        assert started["state"] == "UNDER_REVIEW"
        assert started["sealed_by_user_id"] == USER_IDS["ENGINEER"]


class TestWaiverSeverityGate:
    """The waiver edge exists only for non-critical items."""

    @staticmethod
    def _zone_with_one_major_and_one_critical_field_test_defect():
        ctx = fx.setup_zone_ready_to_certify()
        zone_id = ctx["zone_ids"][0]
        air = fx.schedule_field_test(
            ctx, zone_id, "AIR_INFILTRATION", CLOCK_FIELD_TEST_DAY, attempt_no=2
        )
        air = fx.record_field_test(
            ctx, air["id"], f.air_result_payload(0.09), USER_IDS["QC_2"]
        )
        water = fx.schedule_field_test(
            ctx, zone_id, "WATER_AAMA_501_2", CLOCK_FIELD_TEST_DAY, attempt_no=2
        )
        water = fx.record_field_test(
            ctx, water["id"], f.water_result_payload(True), USER_IDS["QC_2"]
        )
        defects = get_success_data(
            api_client.list_defect_items(QC, params={"zone_id": zone_id})
        )
        by_test = {row["field_test_id"]: row for row in defects}
        return ctx, zone_id, air, water, by_test[air["id"]], by_test[water["id"]]

    def test_the_major_defect_waives_and_the_critical_one_cannot(self):
        """The air failure's MAJOR defect waives to WAIVED with its reference and
        a closing stamp, while the water failure's CRITICAL defect is refused,
        stays OPEN, and keeps the package restricted and uncertifiable.

        PRD: "Waivers are for non-critical items only: an item whose `severity` is `CRITICAL` is refused with `ERR_WAIVER_NOT_PERMITTED`."

        Design: Corner/state_machines/critical_defects_cannot_be_waived_while_major_defects_can
        """
        ctx, zone_id, air, water, major, critical = (
            self._zone_with_one_major_and_one_critical_field_test_defect()
        )
        assert air["state"] == "FAILED"
        assert air["outcome_reason"] == "AIR_LEAKAGE_EXCEEDED"
        assert water["state"] == "FAILED"
        assert water["outcome_reason"] == "WATER_PENETRATION"
        assert major["severity"] == "MAJOR"
        assert critical["severity"] == "CRITICAL"

        refused = api_client.waive_defect(
            critical["id"], f.waive_payload("W-CRIT-1"), ARCHITECT
        )
        validate_error(
            refused, ApiErrorId.ERR_WAIVER_NOT_PERMITTED.value, expected_status=422
        )
        assert (
            get_success_data(api_client.get_defect_item(critical["id"], QC))["status"]
            == "OPEN"
        )

        waived = validate_success(
            api_client.waive_defect(major["id"], f.waive_payload("W-MAJ-1"), ARCHITECT),
            expected_status=200,
        )
        assert waived["status"] == "WAIVED"
        assert waived["waiver_ref"] == "W-MAJ-1"
        assert waived["closed_at"] == "2026-08-13T09:00:00.000Z"

        package = fx.refresh_package(ctx)
        assert package["open_critical_defect_count"] == 1
        assert package["engineering_posture"] == "RESTRICTED"

        # The water retest is also still FAILED with an unclosed defect, and the
        # PRD names no error id for that bullet, so either safety code is faithful.
        refused_certification = api_client.certify_weather_tight(
            zone_id, f.certify_weather_tight_payload(), PM
        )
        assert refused_certification.status_code == 422
        validate_error_is_one_of(
            refused_certification,
            [
                ApiErrorId.ERR_OPEN_CRITICAL_DEFECT.value,
                ApiErrorId.ERR_NO_FIELD_TEST_EVIDENCE.value,
            ],
        )


class TestSystemDecisionSideEffects:
    """One accepted trigger, four writes."""

    def test_the_decision_prices_the_shop_and_regeometries_the_zone_registered_earlier(self):
        """Both derived limits read null while the fork is undecided, and the one
        decision call moves the package to SYSTEM_SELECTED, prices 4950.00 shop
        hours against a crew of 4, and retro-computes the existing zone to 7.34 mm
        and 13.33 mm.

        PRD: "Both branches then reconcile every installation zone that already exists on the package, recomputing that zone's `thermal_movement_allowance_mm` and `deflection_limit_mm` against the newly fixed system type, and both bump the package's `version` by 1."

        Design: Corner/state_machines/system_decision_side_effects_reprice_labor_and_regeometry_existing_zones
        """
        ctx = fx.new_project(clock=CLOCK_T0, system_type=None)
        zone = fx.add_zone_a(ctx)
        assert zone["thermal_movement_allowance_mm"] is None
        assert zone["deflection_limit_mm"] is None
        package_before = fx.refresh_package(ctx)
        assert package_before["system_type"] == "UNDECIDED"

        decided = validate_success(
            api_client.decide_system(
                ctx["package_id"], f.system_decision_payload("UNITIZED"), PM
            ),
            expected_status=200,
        )
        assert decided["state"] == "SYSTEM_SELECTED"
        assert decided["system_type"] == "UNITIZED"
        assert decided["planned_shop_hours"] == pytest.approx(4950.00, abs=0.01)
        assert decided["planned_field_crew_size"] == 4
        assert decided["version"] == package_before["version"] + 1
        assert decided["mockup_qualified"] is False

        regeometried = get_success_data(
            api_client.get_installation_zone(zone["id"], PM)
        )
        assert regeometried["thermal_movement_allowance_mm"] == pytest.approx(7.34, abs=0.01)
        assert regeometried["deflection_limit_mm"] == pytest.approx(13.33, abs=0.01)
        assert regeometried["version"] == zone["version"] + 1


class TestBubbleUpClosuresOnTheLastShipment:
    """One child write, two conditional parent closures."""

    @staticmethod
    def _order_released_before_receipt(ordered_lites):
        ctx = fx.setup_qualified_package()
        fx.add_approved_submittal(ctx)
        fx.add_zone_a(ctx)
        fx.create_glass_order(ctx, ordered_lites=ordered_lites)
        fx.start_glass_production(ctx)
        release = fx.create_release(ctx, panels_per_zone=36, lites_per_panel=2)
        fx.receive_glass(ctx, ordered_lites)
        lot = ctx["lots"][ctx["zone_ids"][0]][0]
        fx.advance_lot(ctx, lot["id"], "GLAZED")
        return ctx, release, lot

    def test_a_fully_consumed_order_closes_alongside_its_release(self):
        """Seventy-four lites received reserve two for breakage and allocate
        seventy-two to the single lot, so shipping that lot closes the release
        and — because the unallocated balance is exactly zero — the order too.

        PRD: "The order reaches its terminal `CLOSED` state as a system event, not by request: once the order has at least one panel lot, every panel lot of the order has reached `fabrication_status` `SHIPPED`, and `unallocated_lites` has fallen to 0, the order transitions `RECEIVED` → `CLOSED`."

        Design: Corner/state_machines/glass_order_and_release_auto_close_when_the_last_lot_ships
        """
        ctx, release, lot = self._order_released_before_receipt(74)
        order_before = fx.refresh_glass_order(ctx)
        release_before = get_success_data(
            api_client.get_fabrication_release(release["id"], PM)
        )
        assert order_before["state"] == "RECEIVED"
        assert order_before["unallocated_lites"] == 0

        shipped = fx.advance_lot(ctx, lot["id"], "SHIPPED")
        assert shipped["fabrication_status"] == "SHIPPED"
        assert shipped["shipped_at"] == "2026-08-03T08:00:00.000Z"

        closed_release = get_success_data(
            api_client.get_fabrication_release(release["id"], PM)
        )
        assert closed_release["state"] == "CLOSED"
        assert closed_release["version"] == release_before["version"] + 1

        closed_order = fx.refresh_glass_order(ctx)
        assert closed_order["state"] == "CLOSED"
        assert closed_order["committable_lites"] == 74
        assert closed_order["allocated_lites"] == 72
        assert closed_order["breakage_stock_lites"] == 2
        assert closed_order["unallocated_lites"] == 0
        assert closed_order["version"] == order_before["version"] + 1

    def test_two_lites_left_unallocated_keep_the_order_open_while_the_release_closes(self):
        """Seventy-six lites leave two unallocated after the same reserve and the
        same allocation, so the identical shipment closes the release but leaves
        the order at RECEIVED with its version untouched.

        PRD: "Shipping also triggers two bubble-up closures: when every lot of the release has reached `SHIPPED`, the release transitions `RELEASED` → `CLOSED`; and when every lot of the glass order has reached `SHIPPED` and the order's `unallocated_lites` is 0, the order transitions `RECEIVED` → `CLOSED`."

        Design: Corner/state_machines/glass_order_and_release_auto_close_when_the_last_lot_ships
        """
        ctx, release, lot = self._order_released_before_receipt(76)
        order_before = fx.refresh_glass_order(ctx)
        assert order_before["unallocated_lites"] == 2

        fx.advance_lot(ctx, lot["id"], "SHIPPED")

        assert (
            get_success_data(api_client.get_fabrication_release(release["id"], PM))["state"]
            == "CLOSED"
        )
        order_after = fx.refresh_glass_order(ctx)
        assert order_after["state"] == "RECEIVED"
        assert order_after["unallocated_lites"] == 2
        assert order_after["breakage_stock_lites"] == 2
        assert order_after["version"] == order_before["version"]


class TestMockupResultDrivesQualification:
    """One result reaches across three entities."""

    def test_only_the_passing_retest_qualifies_the_package_and_it_bears_the_surcharge(self):
        """The failing attempt mints a critical package-level defect and restricts
        the package without moving its state, a release in between is refused for
        qualification, and the surcharged retest both prices at 812240 and flips
        the package to MOCKUP_QUALIFIED.

        PRD: "Passing is what qualifies the package: it sets `mockup_qualified` to true and, when the package is sitting in `SYSTEM_SELECTED`, bubbles it `SYSTEM_SELECTED` → `MOCKUP_QUALIFIED`."

        Design: Corner/state_machines/mockup_result_drives_package_qualification_and_posture
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        first = fx.add_failed_mockup(
            ctx, window_start="2026-08-05T06:00:00Z", window_end="2026-08-05T20:00:00Z"
        )
        fx.add_approved_submittal(ctx)
        fx.add_received_glass_order(ctx, ordered_lites=240)
        fx.add_zone_a(ctx)

        assert first["state"] == "FAILED"
        mockup_defects = get_success_data(
            api_client.list_defect_items(
                QC, params={"package_id": ctx["package_id"], "origin": "MOCKUP_TEST"}
            )
        )
        assert len(mockup_defects) == 1
        defect = mockup_defects[0]
        assert defect["severity"] == "CRITICAL"
        assert defect["status"] == "OPEN"
        assert defect["zone_id"] is None
        assert defect["mockup_test_id"] == first["id"]

        restricted = fx.refresh_package(ctx)
        assert restricted["open_critical_defect_count"] == 1
        assert restricted["engineering_posture"] == "RESTRICTED"
        assert restricted["state"] == "SYSTEM_SELECTED"
        assert restricted["mockup_qualified"] is False

        fx.submit_remediation(ctx, defect["id"], "revised gasket profile and re-tooled sill")
        closed = fx.reinspect_defect(ctx, defect["id"], "PASS", USER_IDS["QC_2"])
        assert closed["status"] == "CLOSED"
        reopened = fx.refresh_package(ctx)
        assert reopened["engineering_posture"] == "OPEN"

        between = api_client.create_fabrication_release(
            f.create_fabrication_release_payload(
                ctx["package_id"],
                ctx["submittal_id"],
                ctx["glass_order_id"],
                list(ctx["zone_ids"]),
                fx.package_version(ctx),
            ),
            PM,
        )
        validate_error(
            between, ApiErrorId.ERR_MOCKUP_NOT_QUALIFIED.value, expected_status=422
        )

        retest = validate_success(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    ctx["package_id"],
                    ctx["lab_id"],
                    window_start="2026-08-08T06:00:00Z",
                    window_end="2026-08-08T20:00:00Z",
                    retest_of_test_id=first["id"],
                    attempt_no=2,
                ),
                PM,
            ),
            expected_status=201,
        )
        assert retest["attempt_no"] == 2
        assert retest["retest_of_test_id"] == first["id"]
        assert retest["invoice_subtotal_cents"] == 781000
        assert retest["surcharge_cents"] == 31240
        assert retest["invoice_cents"] == 812240

        passed = fx.record_mockup_result(ctx, retest["id"])
        assert passed["state"] == "PASSED"
        qualified = fx.refresh_package(ctx)
        assert qualified["mockup_qualified"] is True
        assert qualified["state"] == "MOCKUP_QUALIFIED"


class TestDefectReinspectionLoop:
    """A cyclic machine whose rounds are counted on a field, not in the state."""

    def test_a_failed_reinspection_reopens_the_item_clears_the_note_and_counts_once(self):
        """The first reinspection fails the item back to OPEN with the counter at
        1 and the narrative wiped, the posture stays restricted through both
        phases, and the second round closes the item with the counter still at 1
        after exactly four versioned writes.

        PRD: "A `FAIL` moves it `REMEDIATION_SUBMITTED` → `OPEN`, increments `reinspect_fail_count` by 1, sets `reinspected_by_user_id`, and clears `remediation_note` so a fresh narrative must be written — this is the cycle edge that lets an item bounce indefinitely."

        Design: Corner/state_machines/defect_reinspect_failure_loops_back_to_open_and_counts_cycles
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        fx.add_failed_mockup(ctx)
        defect = get_success_data(
            api_client.list_defect_items(
                QC, params={"package_id": ctx["package_id"], "origin": "MOCKUP_TEST"}
            )
        )[0]
        assert defect["version"] == 1
        assert defect["reinspect_fail_count"] == 0

        submitted = fx.submit_remediation(ctx, defect["id"], "first repair attempt")
        assert submitted["status"] == "REMEDIATION_SUBMITTED"
        assert submitted["remediation_note"] == "first repair attempt"
        assert submitted["version"] == 2
        holding = fx.refresh_package(ctx)
        assert holding["open_critical_defect_count"] == 1
        assert holding["engineering_posture"] == "RESTRICTED"

        failed = fx.reinspect_defect(ctx, defect["id"], "FAIL", USER_IDS["QC_2"])
        assert failed["status"] == "OPEN"
        assert failed["reinspect_fail_count"] == 1
        assert failed["remediation_note"] is None
        assert failed["reinspected_by_user_id"] == USER_IDS["QC_2"]
        assert failed["version"] == 3
        still_holding = fx.refresh_package(ctx)
        assert still_holding["open_critical_defect_count"] == 1
        assert still_holding["engineering_posture"] == "RESTRICTED"

        again = fx.submit_remediation(
            ctx, defect["id"], "second repair attempt with new gasket"
        )
        assert again["status"] == "REMEDIATION_SUBMITTED"
        assert again["version"] == 4

        closed = fx.reinspect_defect(ctx, defect["id"], "PASS", USER_IDS["QC_2"])
        assert closed["status"] == "CLOSED"
        assert closed["reinspect_fail_count"] == 1
        assert closed["closed_at"] is not None
        assert closed["version"] == 5

        released = fx.refresh_package(ctx)
        assert released["engineering_posture"] == "OPEN"
        assert released["open_critical_defect_count"] == 0
