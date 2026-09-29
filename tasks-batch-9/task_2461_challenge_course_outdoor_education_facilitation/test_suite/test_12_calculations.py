"""Derived values: filtered input sets, per-kind constants, thresholds and the ordered sweep."""

from test_helpers import (
    assert_course_counters,
    assert_posture,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_TEST_DATE,
    CLOCK_TEST_UTC,
    ELEMENT_NAME_GROUND,
    ELEMENT_NAME_ZIP,
)
from test_helpers.factories import belay_equipment_payload, facilitator_payload
from test_helpers.fixtures import (
    add_participant,
    add_training,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    create_safety_officer,
    create_staff_facilitator,
    set_clock,
    submit_packet,
)
from test_helpers.test_users import PROGRAM_DIRECTOR

DRILL_ON_THE_BOUNDARY = "2026-02-11"
DRILL_ONE_DAY_TOO_OLD = "2026-02-10"


class TestRosterInputSetFiltering:
    """Chaperones are counted for coverage but never as billable heads."""

    def test_a_roster_of_chaperones_alone_stays_incomplete(self, api):
        """The only member is fully screened and the booking still is not ready.

        PRD 3.6: "A booking whose participants are all chaperones, with no billable
        participant at all, is `INCOMPLETE` rather than `READY`."

        PRD 3.6: "Otherwise the participant is `ELIGIBLE`."

        PRD 3.6: "`is_chaperone`, which defaults to false and marks accompanying
        adults who supervise and are never billed."

        Design: Corner/calculations/roster_of_chaperones_only_stays_incomplete
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        gc_id = create_funded_client(api, amount_cents=0)
        b_id, _ = create_booking(api, course_id, gc_id, 1)
        p_chap_id = add_participant(api, gc_id, b_id, "CHAPERONE", screen=False)

        screened = submit_packet(api, gc_id, p_chap_id)

        assert screened["is_chaperone"] is True
        assert screened["health_form_status"] == "SUBMITTED"
        assert screened["screening_status"] == "ELIGIBLE"

        booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert booking["roster_status"] == "INCOMPLETE"


class TestEquipmentLifeConstantsAreIndexedByKind:
    """Each kind reads its own shelf life and its own in-service life."""

    def test_a_used_rope_scores_on_service_life_and_a_fresh_carabiner_on_shelf_life(self, api):
        """Two items manufactured the same day retire eight years apart.

        PRD 3.4: "The manufacture clock produces `mfg_life_forecast_date` by adding
        the shelf life for the kind to `manufactured_on`: ten years for a rope, ten
        for a harness, fifteen for a carabiner, eight for a lanyard."

        PRD 3.4: "The service clock produces `service_life_forecast_date` by adding
        the in-service life for the kind to `first_use_on`: five years for a rope,
        seven for a harness, ten for a carabiner, five for a lanyard; while
        `first_use_on` is null this date is null too and the item is scored on shelf
        life alone."

        PRD 3.4: "`retirement_basis` is decided in a fixed order: `CYCLE` whenever
        `usage_cycles` has reached `max_cycles`, since an exhausted item is finished
        today regardless of how much shelf or service life its dates still allow;
        otherwise `MANUFACTURE` when the service date is null; otherwise
        `MANUFACTURE` when the manufacture date is earlier than or equal to the
        service date; otherwise `SERVICE`."

        Design: Corner/calculations/equipment_service_life_constant_beats_shelf_life_for_a_rope
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)

        rope = validate_success(
            api.create_belay_equipment(
                belay_equipment_payload(course_id, "ROPE", first_use_on="2024-08-10"),
                PROGRAM_DIRECTOR,
            ),
            201,
        )
        carabiner = validate_success(
            api.create_belay_equipment(
                belay_equipment_payload(course_id, "CARABINER"), PROGRAM_DIRECTOR
            ),
            201,
        )

        assert rope["mfg_life_forecast_date"] == "2032-06-01"
        assert rope["service_life_forecast_date"] == "2029-08-10"
        assert rope["retirement_forecast_date"] == "2029-08-10"
        assert rope["retirement_basis"] == "SERVICE"
        assert rope["usage_cycles"] == 0
        assert rope["status"] == "IN_SERVICE"

        assert carabiner["mfg_life_forecast_date"] == "2037-06-01"
        assert carabiner["service_life_forecast_date"] is None
        assert carabiner["retirement_forecast_date"] == "2037-06-01"
        assert carabiner["retirement_basis"] == "MANUFACTURE"


class TestRescueDrillRecencyThreshold:
    """The drill-age comparison is strictly greater than 180 days."""

    def test_a_drill_exactly_one_hundred_eighty_days_old_is_still_current(self, api):
        """One day apart, two otherwise identical facilitators land on opposite sides.

        PRD 3.2: "The drill-age comparison is strictly greater than 180 days, so a
        drill passed exactly 180 days ago is still current and a drill passed 181
        days ago is not."

        PRD 3.2: "`rescue_drill_last_passed_on` is the most recent `completed_on`
        among the facilitator's training records of kind `RESCUE_DRILL`."

        PRD 3.2: "`refresher_hours_24mo` is the sum of `hours` across the
        facilitator's training records of kind `REFRESHER` or `RECERTIFICATION`
        whose `completed_on` falls within 730 days — two years — of the clock date."

        Design: Corner/calculations/rescue_drill_exactly_one_hundred_eighty_days_old_still_scores_active
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)

        edge_id = validate_success(
            api.create_facilitator(
                facilitator_payload(course_id, "STAFF_FACILITATOR", full_name="Nadia Frost"),
                PROGRAM_DIRECTOR,
            ),
            201,
        )["id"]
        over_id = validate_success(
            api.create_facilitator(
                facilitator_payload(course_id, "STAFF_FACILITATOR", full_name="Owen Pike"),
                PROGRAM_DIRECTOR,
            ),
            201,
        )["id"]
        add_training(api, edge_id, "REFRESHER")
        add_training(api, over_id, "REFRESHER")

        add_training(api, edge_id, "RESCUE_DRILL", completed_on=DRILL_ON_THE_BOUNDARY)
        add_training(api, over_id, "RESCUE_DRILL", completed_on=DRILL_ONE_DAY_TOO_OLD)

        edge = validate_success(api.get_facilitator(edge_id, PROGRAM_DIRECTOR))
        over = validate_success(api.get_facilitator(over_id, PROGRAM_DIRECTOR))

        assert edge["rescue_drill_last_passed_on"] == DRILL_ON_THE_BOUNDARY
        assert edge["refresher_hours_24mo"] == 8
        assert edge["cert_status"] == "ACTIVE"

        assert over["rescue_drill_last_passed_on"] == DRILL_ONE_DAY_TOO_OLD
        assert over["refresher_hours_24mo"] == 8
        assert over["cert_status"] == "PROBATION"


class TestDailyOpenSweepOrdering:
    """The element sweep runs before posture is re-scored, so the pass sees its own work."""

    def test_the_checkpoint_takes_a_life_expired_element_out_of_service(self, api):
        """One expired element restricts the site; its healthy neighbour is untouched.

        PRD 3.1: "Step four walks the course's elements whose `status` is not
        `RETIRED`, in ascending `created_at` order, re-derives the retirement
        forecast, and — when `retirement_forecast_date` has arrived at or before the
        clock date and the element is not already `OUT_OF_SERVICE` — moves it to
        `OUT_OF_SERVICE`, adding one to `out_of_service_element_count` and cascading
        its `SCHEDULED` blocks to `BLOCKED_UNSAFE` and their `CONFIRMED` bookings to
        `AT_RISK`."

        PRD 3.1: "Step one increments `daily_open_index` and sets
        `last_daily_open_date` to the clock date."

        PRD 3.1: "Step seven re-derives posture from the results of steps two
        through six."

        PRD 2.5: "`restricted_element_count` is greater than zero, or
        `out_of_service_element_count` is greater than zero. Result: `RESTRICTED`,
        reason `ELEMENT_RESTRICTED`."

        Design: Corner/calculations/daily_open_checkpoint_moves_life_expired_element_out_of_service
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        create_safety_officer(api, course_id)
        create_staff_facilitator(api, course_id)
        z_id = create_element(
            api,
            course_id,
            "ZIP_LINE",
            element_name=ELEMENT_NAME_ZIP,
            installed_on="2010-08-10",
        )
        g_id = create_element(
            api, course_id, "GROUND_INITIATIVE", element_name=ELEMENT_NAME_GROUND
        )

        opened = validate_success(api.daily_open(course_id, PROGRAM_DIRECTOR))

        assert_posture(opened, "RESTRICTED", "ELEMENT_RESTRICTED")
        assert opened["daily_open_index"] == 1
        assert opened["last_daily_open_date"] == CLOCK_TEST_DATE
        assert_course_counters(opened, restricted=0, out_of_service=1)
        assert opened["rescue_ready_facilitator_count"] == 2
        assert opened["rescue_readiness_ok"] is True

        zip_line = validate_success(api.get_element(z_id, PROGRAM_DIRECTOR))
        assert zip_line["status"] == "OUT_OF_SERVICE"
        assert zip_line["retirement_forecast_date"] == "2020-08-10"

        ground = validate_success(api.get_element(g_id, PROGRAM_DIRECTOR))
        assert ground["status"] == "SERVICEABLE"
