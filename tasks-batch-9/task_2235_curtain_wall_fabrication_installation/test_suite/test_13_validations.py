"""The rejection ladder as it applies to individual writes: the two header
gates, the window rule, the per-zone-and-date uniqueness, the closing coating
window, the missing deflection line, the retuned joint, the note burn-down, the
re-read zone roster and the once-per-cycle seal."""
import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_envelope_meta
from test_helpers.constants import (
    CLOCK_FIELD_TEST_DAY,
    CLOCK_HANG_DAY,
    CLOCK_T0,
    FABRICATED_UUID,
    TEST_DEFAULTS,
    USER_IDS,
)
from test_helpers.test_users import (
    TEST_USERS,
    headers_with_empty_role,
    headers_without_role,
    headers_without_user,
    make_architect_of_record_headers,
    make_delegated_engineer_headers,
    make_field_superintendent_headers,
    make_qc_inspector_headers,
)

PM = TEST_USERS["cw_project_manager_headers"]
DETAILER = TEST_USERS["cw_detailer_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]
QC = TEST_USERS["qc_inspector_headers"]


class TestRoleHeaderGate:
    """The role check outranks the body check and every not-found rule."""

    def test_an_absent_or_empty_role_is_reported_before_the_body_or_the_missing_row(self):
        """A zone create carrying only a package reference and a read of a
        fabricated package identifier both report the missing-role code at 401
        rather than the invalid-request or not-found codes, an empty role reads the
        same, and nothing is written.

        PRD: "`X-User-Role` absent or empty — `ERR_MISSING_ROLE` (401). Applies to every endpoint except the clock-setting capability."

        Design: Corner/validations/omitted_role_header_returns_unauthenticated
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        before = fx.refresh_package(ctx)

        headless_create = api_client.create_installation_zone(
            {"package_id": ctx["package_id"]}, headers_without_role()
        )
        error = validate_error(
            headless_create, ApiErrorId.ERR_MISSING_ROLE.value, expected_status=401
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        assert headless_create.json()["response_type"] == "error"
        assert_envelope_meta(headless_create.json())

        headless_read = api_client.get_facade_package(
            FABRICATED_UUID, headers_without_role()
        )
        missing = validate_error(
            headless_read, ApiErrorId.ERR_MISSING_ROLE.value, expected_status=401
        )
        assert missing["error_id"] != ApiErrorId.ERR_PACKAGE_NOT_FOUND.value

        validate_error(
            api_client.create_installation_zone(
                {"package_id": ctx["package_id"]}, headers_with_empty_role()
            ),
            ApiErrorId.ERR_MISSING_ROLE.value,
            expected_status=401,
        )
        validate_error(
            api_client.get_facade_package(FABRICATED_UUID, headers_with_empty_role()),
            ApiErrorId.ERR_MISSING_ROLE.value,
            expected_status=401,
        )

        rows, meta = validate_paginated(
            api_client.list_installation_zones(PM, params={"package_id": ctx["package_id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert fx.refresh_package(ctx)["version"] == before["version"]


class TestActorHeaderGate:
    """Only the five actor-recording writes demand an acting user."""

    def test_the_seal_and_the_crew_day_refuse_an_absent_user_while_a_zone_create_does_not(self):
        """A seal and a crew-day posting sent without an acting user both report
        the missing-user code at 401 and write nothing, a zone create with no user
        header at all succeeds, and repeating the seal with the engineer's
        identifier stores it.

        PRD: "`X-User-ID` absent or empty — `ERR_MISSING_USER` (401). Applies to the five operations named in §2.1: submittal seal, submittal review start, submittal review decision, defect re-inspection and crew-day posting."

        Design: Corner/validations/actor_recording_writes_reject_a_missing_user_header_unauthenticated
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        zone = fx.add_zone_a(ctx)
        submittal = fx.create_submittal(ctx, delegated_design_scope=True)

        validate_error(
            api_client.seal_submittal(
                submittal["id"],
                f.seal_payload(),
                headers_without_user("DelegatedEngineer"),
            ),
            ApiErrorId.ERR_MISSING_USER.value,
            expected_status=401,
        )
        assert (
            get_success_data(api_client.get_submittal(submittal["id"], DETAILER))[
                "sealed_by_user_id"
            ]
            is None
        )

        validate_error(
            api_client.post_crew_day(
                zone["id"],
                f.create_crew_day_payload("2026-08-10", 4, 8.0, 10),
                headers_without_user("FieldSuperintendent"),
            ),
            ApiErrorId.ERR_MISSING_USER.value,
            expected_status=401,
        )
        logs, meta = validate_paginated(
            api_client.list_crew_day_logs(PM, params={"zone_id": zone["id"]})
        )
        assert logs == []
        assert meta["total_count"] == 0

        second_zone = validate_success(
            api_client.create_installation_zone(
                f.zone_b_payload(ctx["package_id"]), headers_without_user("CWProjectManager")
            ),
            expected_status=201,
        )
        assert second_zone["install_status"] == "PLANNED"

        sealed = validate_success(
            api_client.seal_submittal(
                submittal["id"],
                f.seal_payload(),
                make_delegated_engineer_headers(USER_IDS["ENGINEER"]),
            ),
            expected_status=200,
        )
        assert sealed["sealed_by_user_id"] == USER_IDS["ENGINEER"]
        assert sealed["seal_license_no"] == TEST_DEFAULTS["SEAL_LICENSE_NO"]

    def test_the_reinspection_and_the_result_recording_refuse_an_absent_user_too(self):
        """The re-inspection is one of the five operations that demand an acting
        user, so it is refused without one and its row keeps its prior values;
        recording a field-test result is not one of the five, and it stamps the
        acting inspector when one is supplied.

        PRD: "`X-User-ID` absent or empty — `ERR_MISSING_USER` (401). Applies to the five operations named in §2.1: submittal seal, submittal review start, submittal review decision, defect re-inspection and crew-day posting."

        Design: Corner/validations/actor_recording_writes_reject_a_missing_user_header_unauthenticated
        """
        ctx = fx.setup_hung_zone()
        zone_id = ctx["zone_ids"][0]
        defect = fx.raise_defect(ctx, zone_id=zone_id, severity="MAJOR")
        fx.submit_remediation(ctx, defect["id"], "sealant re-tooled at grid 4")
        fx.set_clock(CLOCK_FIELD_TEST_DAY)
        water = fx.schedule_field_test(
            ctx, zone_id, "WATER_AAMA_501_2", CLOCK_FIELD_TEST_DAY
        )

        validate_error(
            api_client.reinspect_defect(
                defect["id"], f.reinspect_payload("PASS"), headers_without_user("QCInspector")
            ),
            ApiErrorId.ERR_MISSING_USER.value,
            expected_status=401,
        )
        held = get_success_data(api_client.get_defect_item(defect["id"], QC))
        assert held["status"] == "REMEDIATION_SUBMITTED"
        assert held["reinspected_by_user_id"] is None

        unrecorded = get_success_data(api_client.get_field_test(water["id"], QC))
        assert unrecorded["state"] == "SCHEDULED"
        assert unrecorded["recorded_by_user_id"] is None

        recorded = validate_success(
            api_client.record_field_test_result(
                water["id"],
                f.water_result_payload(False),
                make_qc_inspector_headers(USER_IDS["QC_2"]),
            ),
            expected_status=200,
        )
        assert recorded["state"] == "PASSED"
        assert recorded["recorded_by_user_id"] == USER_IDS["QC_2"]


class TestZeroLengthWindows:
    """The window rule fires before any overlap or capacity arithmetic."""

    def test_a_zero_length_or_inverted_window_is_refused_while_one_minute_books(self):
        """A reservation whose end equals its start and one whose end precedes its
        start are both refused as invalid windows and create nothing, a
        one-minute window on the same rig is accepted, and a mockup test obeys the
        same rule.

        PRD: "A window whose `window_end` is at or before its `window_start` is refused with `ERR_INVALID_WINDOW`."

        Design: Corner/validations/reservation_window_end_equal_to_start_is_rejected
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        zone = fx.add_zone_a(ctx)
        fx.create_rig(ctx, changeover_buffer_minutes=45)
        fx.create_lab(ctx)

        def reserve(window_start, window_end):
            return api_client.create_hoist_reservation(
                f.create_hoist_reservation_payload(
                    ctx["rig_id"], zone["id"], window_start, window_end,
                    planned_panel_count=36,
                ),
                SUPERINTENDENT,
            )

        validate_error(
            reserve("2026-08-10T06:00:00Z", "2026-08-10T06:00:00Z"),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            expected_status=400,
        )
        validate_error(
            reserve("2026-08-10T18:00:00Z", "2026-08-10T06:00:00Z"),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            expected_status=400,
        )

        accepted = validate_success(
            reserve("2026-08-10T06:00:00Z", "2026-08-10T06:01:00Z"), expected_status=201
        )
        assert accepted["status"] == "RESERVED"

        held = get_success_data(api_client.list_rig_reservations(ctx["rig_id"], PM))
        assert len(held) == 1
        assert held[0]["id"] == accepted["id"]

        validate_error(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    ctx["package_id"],
                    ctx["lab_id"],
                    window_start="2026-08-05T06:00:00Z",
                    window_end="2026-08-05T06:00:00Z",
                ),
                PM,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            expected_status=400,
        )
        _, meta = validate_paginated(
            api_client.list_mockup_tests(PM, params={"package_id": ctx["package_id"]})
        )
        assert meta["total_count"] == 0


class TestCrewDayUniqueness:
    """Uniqueness is scoped to the posted logs of one zone on one date."""

    def test_the_date_is_blocked_until_the_original_log_is_voided_and_then_reusable(self):
        """A second posting for the same zone and date is refused without touching
        the hour ledger, the same date on another zone is accepted, voiding the
        original frees the date for a heavier crew, and a third posting is refused
        again.

        PRD: "A second posted log for the same zone and the same `work_date` is refused with `ERR_CREW_DAY_DUPLICATE`."

        Design: Corner/validations/duplicate_crew_day_rejected_then_permitted_after_the_void
        """
        ctx = fx.new_project(clock=CLOCK_HANG_DAY)
        first_zone = fx.add_zone_a(ctx)
        second_zone = fx.add_zone_b(ctx)
        original = fx.post_crew_day(
            ctx, first_zone["id"], work_date="2026-08-10", crew_size=4, shift_hours=8.0,
            panels_installed=10,
        )

        def repost():
            return api_client.post_crew_day(
                first_zone["id"],
                f.create_crew_day_payload("2026-08-10", 6, 9.0, 12),
                make_field_superintendent_headers(USER_IDS["SUPERINTENDENT"]),
            )

        validate_error(
            repost(), ApiErrorId.ERR_CREW_DAY_DUPLICATE.value, expected_status=409
        )
        blocked = get_success_data(api_client.get_installation_zone(first_zone["id"], PM))
        assert blocked["consumed_crew_hours"] == pytest.approx(32.0, abs=0.01)

        other_zone_day = fx.post_crew_day(
            ctx, second_zone["id"], work_date="2026-08-10", crew_size=4, shift_hours=8.0,
            panels_installed=9,
        )
        assert other_zone_day["status"] == "POSTED"
        assert other_zone_day["day_index"] == 1

        voided = validate_success(
            api_client.void_crew_day(
                first_zone["id"],
                original["id"],
                f.void_crew_day_payload("wrong crew size"),
                SUPERINTENDENT,
            ),
            expected_status=200,
        )
        assert voided["status"] == "VOIDED"
        assert voided["day_index"] is None

        replacement = validate_success(repost(), expected_status=201)
        assert replacement["status"] == "POSTED"
        assert replacement["day_index"] == 1

        reposted = get_success_data(api_client.get_installation_zone(first_zone["id"], PM))
        assert reposted["consumed_crew_hours"] == pytest.approx(54.0, abs=0.01)
        assert reposted["remaining_crew_hours"] == pytest.approx(266.0, abs=0.01)

        validate_error(
            repost(), ApiErrorId.ERR_CREW_DAY_DUPLICATE.value, expected_status=409
        )


class TestCoatingRevisionWindow:
    """The revision window closes when the glass lands on site."""

    def test_the_same_revision_succeeds_in_production_and_is_refused_after_receipt(self):
        """The received order refuses the revision and keeps its coating, count and
        version, while the in-production order accepts the identical payload,
        returns to its ordered state, records the re-fire and rescores on the
        expedite-adjusted variant.

        PRD: "A coating revision attempted once the order is `RECEIVED` or `CLOSED` is refused with `ERR_COATING_REVISION_AFTER_RECEIPT` — the glass is already on site and cannot be re-specified."

        Design: Corner/validations/coating_revision_after_receipt_is_rejected
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        in_production = fx.create_glass_order(ctx, ordered_lites=240)
        fx.start_glass_production(ctx)
        received = get_success_data(
            api_client.create_glass_order(
                f.create_glass_order_payload(ctx["package_id"], ordered_lites=240),
                PROCUREMENT,
            )
        )
        get_success_data(
            api_client.start_glass_production(received["id"], {}, PROCUREMENT)
        )
        received = get_success_data(
            api_client.receive_glass_order(received["id"], f.receive_payload(240), PROCUREMENT)
        )
        assert received["state"] == "RECEIVED"

        validate_error(
            api_client.revise_coating(
                received["id"], f.coating_revision_payload("LOWE-340"), PROCUREMENT
            ),
            ApiErrorId.ERR_COATING_REVISION_AFTER_RECEIPT.value,
            expected_status=409,
        )
        untouched = get_success_data(api_client.get_glass_order(received["id"], PROCUREMENT))
        assert untouched["coating_code"] == TEST_DEFAULTS["COATING_CODE"]
        assert untouched["coating_revision_count"] == 0
        assert untouched["version"] == received["version"]

        revised = validate_success(
            api_client.revise_coating(
                in_production["id"], f.coating_revision_payload("LOWE-340"), PROCUREMENT
            ),
            expected_status=200,
        )
        assert revised["state"] == "ORDERED"
        assert revised["coating_code"] == "LOWE-340"
        assert revised["coating_revision_count"] == 1
        assert revised["re_fire_required"] is True
        assert revised["risk_variant"] == "EXPEDITE_ADJUSTED"
        assert revised["effective_lead_days"] == 111
        assert revised["risk_score"] == pytest.approx(64.39, abs=0.01)


class TestDeflectionSchedulingGate:
    """A pass line that does not exist yet cannot be booked against."""

    def test_only_the_deflection_kind_is_refused_while_the_system_fork_is_open(self):
        """With the package undecided the deflection booking is refused and no row
        appears, the water booking on the same zone succeeds, and once the fork is
        taken the same deflection booking lands against a computed limit of 13.33.

        PRD: "Scheduling a `STRUCTURAL_DEFLECTION` test on a zone whose package still has `system_type` `UNDECIDED` is refused with `ERR_DEFLECTION_LIMIT_UNSET`: without a system decision the zone's `deflection_limit_mm` is null, so there is no pass/fail line to test against."

        Design: Corner/validations/deflection_test_cannot_be_scheduled_before_the_system_decision
        """
        ctx = fx.new_project(clock=CLOCK_T0, system_type=None)
        zone = fx.add_zone_a(ctx)
        assert zone["span_mm"] == 3200
        assert zone["deflection_limit_mm"] is None

        validate_error(
            api_client.schedule_field_test(
                zone["id"],
                f.schedule_field_test_payload(
                    "STRUCTURAL_DEFLECTION", "2026-08-13T08:00:00Z"
                ),
                QC,
            ),
            ApiErrorId.ERR_DEFLECTION_LIMIT_UNSET.value,
            expected_status=422,
        )
        _, meta = validate_paginated(
            api_client.list_field_tests(
                QC, params={"zone_id": zone["id"], "test_kind": "STRUCTURAL_DEFLECTION"}
            )
        )
        assert meta["total_count"] == 0

        water = validate_success(
            api_client.schedule_field_test(
                zone["id"],
                f.schedule_field_test_payload("WATER_AAMA_501_2", "2026-08-13T08:00:00Z"),
                QC,
            ),
            expected_status=201,
        )
        assert water["state"] == "SCHEDULED"

        fx.decide_system(ctx, "UNITIZED")
        decided_zone = get_success_data(api_client.get_installation_zone(zone["id"], PM))
        assert decided_zone["deflection_limit_mm"] == pytest.approx(13.33, abs=0.01)

        deflection = validate_success(
            api_client.schedule_field_test(
                zone["id"],
                f.schedule_field_test_payload(
                    "STRUCTURAL_DEFLECTION", "2026-08-13T08:00:00Z"
                ),
                QC,
            ),
            expected_status=201,
        )
        assert deflection["state"] == "SCHEDULED"
        assert deflection["attempt_no"] == 1


class TestRetunedJointAgainstTheAllowance:
    """Certification compares two fields that move independently."""

    def test_a_joint_narrower_than_the_allowance_blocks_certification_until_it_is_widened(self):
        """Retuning the joint to 5.0 mm leaves the computed allowance at 7.34 mm
        and refuses the certification of an otherwise fully evidenced zone, and
        retuning back to 22.0 mm lets the identical call succeed and write the
        certified line.

        PRD: "When the computed movement no longer fits the detailed joint — typically because the joint was retuned narrower, or because the system decision widened the requirement — certification is refused with `ERR_THERMAL_MOVEMENT_EXCEEDED`."

        Design: Corner/validations/retuned_joint_below_the_thermal_allowance_blocks_certification
        """
        ctx = fx.setup_zone_ready_to_certify()
        zone_id = ctx["zone_ids"][0]

        narrowed = validate_success(
            api_client.retune_joint(zone_id, f.retune_joint_payload(5.0), DETAILER),
            expected_status=200,
        )
        assert narrowed["designed_joint_mm"] == pytest.approx(5.0, abs=0.01)
        assert narrowed["thermal_movement_allowance_mm"] == pytest.approx(7.34, abs=0.01)

        validate_error(
            api_client.certify_weather_tight(zone_id, f.certify_weather_tight_payload(), PM),
            ApiErrorId.ERR_THERMAL_MOVEMENT_EXCEEDED.value,
            expected_status=422,
        )
        assert (
            get_success_data(api_client.get_installation_zone(zone_id, PM))["weather_status"]
            == "NOT_TIGHT"
        )

        widened = validate_success(
            api_client.retune_joint(zone_id, f.retune_joint_payload(22.0), DETAILER),
            expected_status=200,
        )
        assert widened["thermal_movement_allowance_mm"] == pytest.approx(7.34, abs=0.01)

        certified = validate_success(
            api_client.certify_weather_tight(zone_id, f.certify_weather_tight_payload(), PM),
            expected_status=200,
        )
        assert certified["weather_status"] == "WEATHER_TIGHT"
        assert certified["certified_line_cents"] == 58266376

    def test_a_joint_exactly_equal_to_the_allowance_still_certifies(self):
        """The rule refuses only a joint the allowance exceeds, so a joint retuned
        to exactly 7.34 mm certifies.

        PRD: "The zone's computed `thermal_movement_allowance_mm` must not exceed its `designed_joint_mm`."

        Design: Corner/validations/retuned_joint_below_the_thermal_allowance_blocks_certification
        """
        ctx = fx.setup_zone_ready_to_certify()
        zone_id = ctx["zone_ids"][0]

        exact = validate_success(
            api_client.retune_joint(zone_id, f.retune_joint_payload(7.34), DETAILER),
            expected_status=200,
        )
        assert exact["designed_joint_mm"] == pytest.approx(7.34, abs=0.01)
        assert exact["thermal_movement_allowance_mm"] == pytest.approx(7.34, abs=0.01)

        certified = validate_success(
            api_client.certify_weather_tight(zone_id, f.certify_weather_tight_payload(), PM),
            expected_status=200,
        )
        assert certified["weather_status"] == "WEATHER_TIGHT"
        assert certified["weather_tight_cycle_count"] == 1


class TestNoteBurnDownBeforeCloseOut:
    """Close-out waits on a number, not on a state."""

    def test_close_out_is_refused_until_both_notes_are_burned_down(self):
        """A weather-tight package carrying an approved-as-noted set with two open
        notes is refused close-out, is still refused after one note is closed, and
        closes only when the count reaches zero — freezing the earned value where
        certification left it.

        PRD: "And the sum of `open_notes_count` across the package's submittals must be exactly 0 — an approved-as-noted set with two unclosed notes blocks close-out just as firmly as an unfinished review."

        Design: Corner/validations/open_review_notes_block_close_out_until_burned_down
        """
        ctx = fx.setup_certified_zone()
        assert fx.refresh_package(ctx)["state"] == "WEATHER_TIGHT_ACHIEVED"
        noted = fx.create_submittal(
            ctx, title="Sill flashing detail set", drawing_set_ref="SD-002"
        )
        fx.seal_submittal(ctx, noted["id"])
        fx.start_review(ctx, noted["id"])
        reviewed = fx.review_submittal(ctx, "APPROVED_AS_NOTED", noted["id"], notes_count=2)
        assert reviewed["state"] == "APPROVED_AS_NOTED"
        assert reviewed["open_notes_count"] == 2

        validate_error(
            api_client.close_out_package(ctx["package_id"], f.close_out_payload(), PM),
            ApiErrorId.ERR_PUNCH_LIST_OPEN.value,
            expected_status=422,
        )
        assert fx.refresh_package(ctx)["state"] == "WEATHER_TIGHT_ACHIEVED"

        architect = make_architect_of_record_headers(USER_IDS["ARCHITECT"])
        halfway = validate_success(
            api_client.close_submittal_notes(
                noted["id"], f.close_notes_payload(1), architect
            ),
            expected_status=200,
        )
        assert halfway["open_notes_count"] == 1
        assert halfway["state"] == "APPROVED_AS_NOTED"
        validate_error(
            api_client.close_out_package(ctx["package_id"], f.close_out_payload(), PM),
            ApiErrorId.ERR_PUNCH_LIST_OPEN.value,
            expected_status=422,
        )

        burned_down = validate_success(
            api_client.close_submittal_notes(
                noted["id"], f.close_notes_payload(1), architect
            ),
            expected_status=200,
        )
        assert burned_down["open_notes_count"] == 0
        assert burned_down["state"] == "APPROVED_AS_NOTED"

        closed = validate_success(
            api_client.close_out_package(ctx["package_id"], f.close_out_payload(), PM),
            expected_status=200,
        )
        assert closed["state"] == "CLOSED_OUT"
        assert closed["earned_value_certified_cents"] == 55353057
        assert closed["retention_held_cents"] == 2913319
        assert closed["certified_area_sqm"] == pytest.approx(412.37, abs=0.01)

        floored = validate_success(
            api_client.close_submittal_notes(
                noted["id"], f.close_notes_payload(1), architect
            ),
            expected_status=200,
        )
        assert floored["open_notes_count"] == 0


class TestCloseOutRereadsTheZoneRoster:
    """A new zone on a weather-tight package reopens the gate."""

    def test_a_zone_added_after_the_milestone_refuses_close_out_ahead_of_the_punch_list(self):
        """Registering a second zone leaves the package's state and its
        weather-tight count exactly as they were, yet close-out now reports the
        untight-zone code — and reports it even with an open review note present,
        because the roster is read before the punch list.

        PRD: "Every installation zone of the package must have `weather_status` `WEATHER_TIGHT` and `install_status` `PANELS_HUNG`; a zone that is not weather-tight refuses close-out with `ERR_ZONES_NOT_WEATHER_TIGHT`."

        Design: Corner/validations/zone_added_after_weather_tight_blocks_close_out
        """
        ctx = fx.setup_certified_zone()
        before = fx.refresh_package(ctx)
        assert before["state"] == "WEATHER_TIGHT_ACHIEVED"

        late_zone = fx.add_zone_b(ctx, planned_panel_count=30)
        assert late_zone["weather_status"] == "NOT_TIGHT"
        after_add = fx.refresh_package(ctx)
        assert after_add["state"] == "WEATHER_TIGHT_ACHIEVED"
        assert after_add["weather_tight_zone_count"] == 1
        assert after_add["earned_value_certified_cents"] == 55353057

        validate_error(
            api_client.close_out_package(ctx["package_id"], f.close_out_payload(), PM),
            ApiErrorId.ERR_ZONES_NOT_WEATHER_TIGHT.value,
            expected_status=422,
        )
        assert fx.refresh_package(ctx)["state"] == "WEATHER_TIGHT_ACHIEVED"

        noted = fx.create_submittal(
            ctx, title="Sill flashing detail set", drawing_set_ref="SD-002"
        )
        fx.seal_submittal(ctx, noted["id"])
        fx.start_review(ctx, noted["id"])
        fx.review_submittal(ctx, "APPROVED_AS_NOTED", noted["id"], notes_count=2)

        both_open = api_client.close_out_package(
            ctx["package_id"], f.close_out_payload(), PM
        )
        error = validate_error(
            both_open, ApiErrorId.ERR_ZONES_NOT_WEATHER_TIGHT.value, expected_status=422
        )
        assert error["error_id"] != ApiErrorId.ERR_PUNCH_LIST_OPEN.value


class TestSealIsUniquePerRevisionCycle:
    """A new drawing set, not a new request, is what licenses a new seal."""

    def test_the_second_seal_on_one_cycle_is_refused_and_the_resubmit_clears_the_first(self):
        """A second seal on revision cycle 1 is refused and leaves the original
        licence in place, a seal with no licence number is refused the same way,
        and the resubmit that opens cycle 2 clears all three seal fields so the
        engineer may seal again.

        PRD: "A seal request with no licence number, or one aimed at a submittal that already carries a seal for its current `revision_cycle`, is rejected with `ERR_SEAL_INVALID`."

        Design: Corner/validations/sealing_twice_within_one_revision_cycle_is_rejected
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        submittal = fx.create_submittal(ctx, delegated_design_scope=True)
        sealed = fx.seal_submittal(ctx, submittal["id"], user_id=USER_IDS["ENGINEER"])
        assert sealed["revision_cycle"] == 1
        assert sealed["sealed_by_user_id"] == USER_IDS["ENGINEER"]

        validate_error(
            api_client.seal_submittal(
                submittal["id"],
                f.seal_payload("PE-99999"),
                make_delegated_engineer_headers(USER_IDS["ENGINEER_ALT"]),
            ),
            ApiErrorId.ERR_SEAL_INVALID.value,
            expected_status=422,
        )
        still_first = get_success_data(api_client.get_submittal(submittal["id"], DETAILER))
        assert still_first["sealed_by_user_id"] == USER_IDS["ENGINEER"]
        assert still_first["seal_license_no"] == TEST_DEFAULTS["SEAL_LICENSE_NO"]
        assert still_first["state"] == "SUBMITTED"

        fx.start_review(ctx, submittal["id"])
        fx.review_submittal(ctx, "REVISION_REQUIRED", submittal["id"])
        resubmitted = fx.resubmit_submittal(ctx, "SD-002-R1", submittal["id"])
        assert resubmitted["revision_cycle"] == 2
        assert resubmitted["sealed_by_user_id"] is None
        assert resubmitted["seal_license_no"] is None
        assert resubmitted["sealed_at"] is None

        validate_error(
            api_client.seal_submittal(
                submittal["id"],
                {},
                make_delegated_engineer_headers(USER_IDS["ENGINEER"]),
            ),
            ApiErrorId.ERR_SEAL_INVALID.value,
            expected_status=422,
        )

        resealed = validate_success(
            api_client.seal_submittal(
                submittal["id"],
                f.seal_payload(),
                make_delegated_engineer_headers(USER_IDS["ENGINEER"]),
            ),
            expected_status=200,
        )
        assert resealed["revision_cycle"] == 2
        assert resealed["sealed_by_user_id"] == USER_IDS["ENGINEER"]
        assert resealed["seal_license_no"] == TEST_DEFAULTS["SEAL_LICENSE_NO"]
