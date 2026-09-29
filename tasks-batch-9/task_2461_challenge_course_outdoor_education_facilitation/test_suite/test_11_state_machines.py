"""Transitions, terminal states, initial states and the bubble-up edge."""

from test_helpers import (
    ERR_DEBRIEF_NOT_RECORDED,
    ERR_ELEMENT_RETIRED,
    ERR_INCIDENT_NOT_UNDER_REVIEW,
    ERR_INSPECTION_NOT_FILED,
    assert_belay_requirement,
    assert_course_counters,
    assert_element_forecast,
    assert_ledger,
    assert_money,
    assert_posture,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_TEST_UTC,
    ELEMENT_INSPECTION_DUE_ON,
    ELEMENT_NAME_LOW,
    ELEMENT_NAME_ZIP,
)
from test_helpers.factories import (
    facilitator_payload,
    incident_payload,
    professional_inspection_payload,
)
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    assign_facilitator,
    confirm_booking,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    create_safety_officer,
    quote_booking,
    rig_equipment,
    set_clock,
    staffed_course,
    submit_packet,
    with_inspector,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_safety_officer_headers

MINOR_NARRATIVE = "Rope burn on the left palm, treated with first aid"
DEPOSIT_CENTS = 341
PAYMENT_CENTS = 20000


def _reported_incident_on_a_rigged_low_element(api):
    """A staff facilitator's minor incident report naming an element with one rope on it."""
    set_clock(api, CLOCK_TEST_UTC)
    world = staffed_course(api)
    l_id = create_element(
        api, world["course_id"], "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW
    )
    rope_id = rig_equipment(api, world["course_id"], l_id, "ROPE")
    incident = validate_success(
        api.create_incident(
            incident_payload(
                world["course_id"],
                world["f1_id"],
                severity="MINOR",
                narrative=MINOR_NARRATIVE,
                ems_activated=False,
                element_id=l_id,
            ),
            world["f1_headers"],
        ),
        201,
    )

    world.update({"l_id": l_id, "rope_id": rope_id, "incident": incident})
    return world


class TestIncidentReviewAndCorrectiveClose:
    """The reported-review-close path, and what the corrective action actually does."""

    def test_a_reviewed_incident_closes_with_its_corrective_action_applied(self, api):
        """The close stores the action, quarantines the rigged rope and re-derives posture.

        PRD 3.9: "A report opens at `status` `REPORTED` with `corrective_action`
        `NONE`, except that a `MODERATE` or `SERIOUS` severity opens a review
        immediately and lands at `UNDER_REVIEW` on creation."

        PRD 3.9: "A `SafetyOfficer` opens a review explicitly on a report that
        arrived at `REPORTED`; an incident already `UNDER_REVIEW` or closed refuses
        the call with `ERR_INCIDENT_NOT_REPORTED`."

        PRD 3.9: "A `CORRECTIVE` disposition moves it `UNDER_REVIEW →
        CLOSED_CORRECTIVE` and records the supplied `corrective_action`, which must
        be either `ELEMENT_RESTRICTED` or `EQUIPMENT_QUARANTINED` and must be
        accompanied by a non-null `element_id` on the incident"

        PRD 3.9: "`EQUIPMENT_QUARANTINED` instead moves every belay item rigged to
        that element whose `status` is `IN_SERVICE` to `QUARANTINED`, re-derives the
        element's `belay_ready`, and pushes dependent `SCHEDULED` blocks to
        `BLOCKED_UNSAFE`. Either way the course posture is re-derived and the
        course's `version` increments."

        Design: Corner/state_machines/incident_review_then_close_records_corrective_action
        """
        world = _reported_incident_on_a_rigged_low_element(api)
        inc_id = world["incident"]["id"]

        assert world["incident"]["status"] == "REPORTED"
        assert world["incident"]["corrective_action"] == "NONE"
        assert world["incident"]["ems_activated"] is False

        reviewed = validate_success(api.review_incident(inc_id, world["so_headers"]))
        assert reviewed["status"] == "UNDER_REVIEW"

        closed = validate_success(
            api.close_incident(
                inc_id,
                {"disposition": "CORRECTIVE", "corrective_action": "EQUIPMENT_QUARANTINED"},
                world["so_headers"],
            )
        )

        assert closed["status"] == "CLOSED_CORRECTIVE"
        assert closed["corrective_action"] == "EQUIPMENT_QUARANTINED"

        rope = validate_success(api.get_belay_equipment(world["rope_id"], PROGRAM_DIRECTOR))
        assert rope["status"] == "QUARANTINED"

        element = validate_success(api.get_element(world["l_id"], PROGRAM_DIRECTOR))
        assert_belay_requirement(element, required_sets=0, ready=False)
        assert element["status"] == "SERVICEABLE"

        course = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert_course_counters(course, restricted=0, quarantined=1)
        assert_posture(course, "OPEN", "NONE")

    def test_closing_an_already_closed_incident_is_refused(self, api):
        """A terminal disposition cannot be overwritten by a second close.

        PRD 3.9: "The incident must be `UNDER_REVIEW`, or the refusal is
        `ERR_INCIDENT_NOT_UNDER_REVIEW`, and the reporter may not close their own
        report per §2.7."

        PRD 3.9: "A `NO_ACTION` disposition moves the incident `UNDER_REVIEW →
        CLOSED_NO_ACTION`, leaves `corrective_action` at `NONE`, and re-derives the
        course posture, which is how the `SERIOUS_INCIDENT` clause finally clears."

        Design: Corner/state_machines/close_incident_twice_rejects_second_attempt
        """
        world = _reported_incident_on_a_rigged_low_element(api)
        inc_id = world["incident"]["id"]
        validate_success(api.review_incident(inc_id, world["so_headers"]))

        first = validate_success(
            api.close_incident(inc_id, {"disposition": "NO_ACTION"}, world["so_headers"])
        )
        assert first["status"] == "CLOSED_NO_ACTION"
        assert first["corrective_action"] == "NONE"

        validate_error(
            api.close_incident(
                inc_id,
                {"disposition": "CORRECTIVE", "corrective_action": "ELEMENT_RESTRICTED"},
                world["so_headers"],
            ),
            ERR_INCIDENT_NOT_UNDER_REVIEW,
            409,
        )

        incident = validate_success(api.get_incident(inc_id, PROGRAM_DIRECTOR))
        assert incident["status"] == "CLOSED_NO_ACTION"
        assert incident["corrective_action"] == "NONE"

        element = validate_success(api.get_element(world["l_id"], PROGRAM_DIRECTOR))
        assert element["status"] == "SERVICEABLE"


class TestInspectionDisposalHasNoDraftEdge:
    """Disposal is the join on a filed record, so `DRAFT` has no route to it."""

    def test_disposing_a_draft_inspection_is_refused(self, api):
        """The record is open but nothing has been filed for the officer to accept.

        PRD 3.3: "Disposal is the join, and it is the `SafetyOfficer`'s acceptance
        of the filing. It carries a `disposition_note`, requires the record to be
        in `FILED_PASS`, `FILED_CONDITIONAL` or `FILED_FAIL` — otherwise
        `ERR_INSPECTION_NOT_FILED` — and is barred to the filing inspector under
        §2.7."

        PRD 3.3: "A disposed `PASS` advances the element's
        `next_professional_inspection_due_on` by 12 months, sets
        `latest_inspection_outcome` to `PASS`, and resets
        `consecutive_conditional_count` to zero; this is the disposal that can clear
        an `INSPECTION_OVERDUE` posture."

        Design: Corner/state_machines/dispose_professional_inspection_before_filing_rejects
        """
        set_clock(api, CLOCK_TEST_UTC)
        world = with_inspector(api, staffed_course(api))
        l_id = create_element(
            api, world["course_id"], "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW
        )
        inspection = validate_success(
            api.create_professional_inspection(
                professional_inspection_payload(l_id, world["insp_id"]),
                world["insp_headers"],
            ),
            201,
        )

        validate_error(
            api.dispose_professional_inspection(
                inspection["id"],
                {"disposition_note": "Trying to accept an unfiled inspection"},
                world["so_headers"],
            ),
            ERR_INSPECTION_NOT_FILED,
            409,
        )

        stored = validate_success(
            api.get_professional_inspection(inspection["id"], PROGRAM_DIRECTOR)
        )
        assert stored["status"] == "DRAFT"
        assert stored["outcome"] == "NONE"
        assert stored["disposed_on"] is None

        element = validate_success(api.get_element(l_id, PROGRAM_DIRECTOR))
        assert element["next_professional_inspection_due_on"] == ELEMENT_INSPECTION_DUE_ON


class TestFacilitatorInitialState:
    """An unexpired certificate is not enough to be current."""

    def test_a_facilitator_with_no_training_history_opens_at_probation(self, api):
        """The currency clauses fail even though the expiry clause passes.

        PRD 3.2: "If `cert_expires_on` falls strictly before the clock date, the
        status is `LAPSED`. Otherwise, if `rescue_drill_last_passed_on` is null, or
        more than 180 days have elapsed between the drill date and the clock date,
        or `refresher_hours_24mo` is below eight hours, the status is `PROBATION`.
        Otherwise the status is `ACTIVE`."

        PRD 3.2: "A newly hired facilitator with no training history therefore
        starts at `PROBATION`."

        PRD 3.2: "The record's `supervision_capacity` is derived directly from the
        level: eight participants for `LEVEL_1`, twelve for `LEVEL_2`, sixteen for
        `LEVEL_3`."

        Design: Corner/state_machines/new_facilitator_without_training_starts_in_probation
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)

        facilitator = validate_success(
            api.create_facilitator(
                facilitator_payload(
                    course_id,
                    "STAFF_FACILITATOR",
                    full_name="Sam Ito",
                    certification_level="LEVEL_1",
                    cert_expires_on="2028-01-31",
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        assert facilitator["cert_status"] == "PROBATION"
        assert facilitator["supervision_capacity"] == 8
        assert facilitator["refresher_hours_24mo"] == 0
        assert facilitator["rescue_drill_last_passed_on"] is None


class TestRetiredElementIsTerminal:
    """A life-expired element leaves the estate and never comes back."""

    def test_a_retired_zip_line_cannot_be_returned_to_service(self, api):
        """The forecast date has passed, the retirement lands, and the row locks.

        PRD 3.1: "Permanent retirement is an explicit `ProgramDirector` act
        carrying a `reason`, and it drives the element to the terminal `RETIRED`
        state from `SERVICEABLE`, `RESTRICTED` or `OUT_OF_SERVICE` alike. At least
        one retirement criterion must hold: `retirement_forecast_date` is on or
        before the clock date, or `consecutive_conditional_count` has reached two,
        or `latest_inspection_outcome` is `FAIL`."

        PRD 3.8: "an element at `RESTRICTED` or `OUT_OF_SERVICE` is refused with
        `ERR_ELEMENT_NOT_SERVICEABLE`, and an element at `RETIRED` with the more
        specific `ERR_ELEMENT_RETIRED`."

        PRD 2.5: "The course-level `next_professional_inspection_due_on` is the
        earliest `next_professional_inspection_due_on` among the course's elements
        whose `status` is not `RETIRED`; when the course has no such element the
        value is null and clause 4 cannot fire."

        Design: Corner/state_machines/retired_element_cannot_return_to_service
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        so_id = create_safety_officer(api, course_id)
        z_id = create_element(
            api,
            course_id,
            "ZIP_LINE",
            element_name=ELEMENT_NAME_ZIP,
            installed_on="2010-08-10",
        )

        retired = validate_success(
            api.retire_element(
                z_id,
                {"reason": "Calendar life expired in 2020; cable and trolley decommissioned"},
                PROGRAM_DIRECTOR,
            )
        )
        assert retired["status"] == "RETIRED"
        assert retired["design_life_years"] == 10
        assert_element_forecast(
            retired,
            calendar="2020-08-10",
            usage=None,
            forecast="2020-08-10",
            basis="CALENDAR",
        )

        validate_error(
            api.return_element_to_service(
                z_id,
                {"note": "Attempting to resurrect a retired zip line"},
                make_safety_officer_headers(so_id),
            ),
            ERR_ELEMENT_RETIRED,
            409,
        )

        element = validate_success(api.get_element(z_id, PROGRAM_DIRECTOR))
        assert element["status"] == "RETIRED"

        course = validate_success(api.get_course(course_id, PROGRAM_DIRECTOR))
        assert course["next_professional_inspection_due_on"] is None


class TestFlaggedParticipantNeedsClearance:
    """`FLAGGED → CLEARED` is the only route out, and only the officer may open it."""

    def test_medical_clearance_lifts_the_participant_and_the_roster_together(self, api):
        """A blocking flag holds the roster until the safety officer signs it off.

        PRD 3.6: "Four of those flags are blocking — `CARDIAC`, `SEIZURE`,
        `PREGNANCY` and `RECENT_SURGERY` — and a packet whose flags intersect that
        set moves the participant `MISSING → FLAGGED`; a packet with no blocking
        flag moves it `MISSING → SUBMITTED`."

        PRD 3.6: "Failing that, the participant is `CONDITIONAL` if
        `health_form_status` is `FLAGGED` and `medical_clearance_granted` is false —
        the packet arrived but the medical decision is outstanding."

        PRD 3.6: "The transition `FLAGGED → CLEARED` sets
        `medical_clearance_granted` true."

        PRD 3.6: "A booking where any participant — chaperones included — is
        `BLOCKED` or `CONDITIONAL` is `BLOCKED`."

        Design: Corner/state_machines/flagged_participant_reaches_eligible_only_after_medical_clearance
        """
        set_clock(api, CLOCK_TEST_UTC)
        world = staffed_course(api)
        gc_id = create_funded_client(api, amount_cents=0)
        b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
        p1_id = add_participant(api, gc_id, b_id, "ADULT", screen=False)

        flagged = submit_packet(api, gc_id, p1_id, health_flags=["CARDIAC"])
        assert flagged["health_form_status"] == "FLAGGED"
        assert flagged["screening_status"] == "CONDITIONAL"

        blocked_booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert blocked_booking["roster_status"] == "BLOCKED"

        cleared = validate_success(
            api.grant_medical_clearance(
                p1_id,
                {
                    "clearance_note": (
                        "Cardiology letter on file; cleared for low elements and high elements"
                    )
                },
                world["so_headers"],
            )
        )

        assert cleared["health_form_status"] == "CLEARED"
        assert cleared["medical_clearance_granted"] is True
        assert cleared["screening_status"] == "ELIGIBLE"

        booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert booking["roster_status"] == "READY"


class TestBookingBubblesUpOnTheLastBlock:
    """The debrief flag is the deliverable, and it is what closes the engagement."""

    def test_completing_the_debrief_delivers_the_booking_and_earns_the_deposit(self, api):
        """Without the flag the completion is refused; with it the booking bubbles up.

        PRD 3.8: "A block whose `phase` is `DEBRIEF` may only be completed with
        `debrief_completed` true, since recording that the debrief practice actually
        happened is the deliverable of that phase; a debrief closed without it is
        refused with `ERR_DEBRIEF_NOT_RECORDED`."

        PRD 3.8: "When every program block of the booking has reached `COMPLETED`
        or `ABANDONED`, and the booking has at least one block, the booking bubbles
        up `CONFIRMED → DELIVERED` on its own. That transition converts the held
        deposit into earned revenue: `retained_cents` is set to the current
        `deposit_allocated_cents`, `deposit_allocated_cents` becomes zero, and both
        the booking's and the group client's `version` increment."

        PRD 3.8: "The client-funds identity of §3.5 stays balanced, because the
        money moves from allocated to retained without ever passing back through
        `credit_balance_cents`."

        Design: Corner/state_machines/booking_bubbles_up_to_delivered_when_every_block_is_terminal
        """
        set_clock(api, CLOCK_TEST_UTC)
        world = staffed_course(api)
        gc_id = create_funded_client(api, amount_cents=PAYMENT_CENTS)
        b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
        add_participant(api, gc_id, b_id, "ADULT")
        block_ids = add_blocks(
            api,
            b_id,
            [
                (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z"),
                (2, "DEBRIEF", "2026-09-15T10:15:00Z", "2026-09-15T10:45:00Z"),
            ],
        )
        quote_booking(api, b_id)
        confirm_booking(api, gc_id, b_id)
        assign_facilitator(api, block_ids[0], world["f1_id"])
        assign_facilitator(api, block_ids[1], world["f1_id"])

        validate_success(api.start_program_block(block_ids[0], world["f1_headers"]))
        validate_success(
            api.complete_program_block(block_ids[0], {}, world["f1_headers"])
        )
        validate_success(api.start_program_block(block_ids[1], world["f1_headers"]))

        validate_error(
            api.complete_program_block(block_ids[1], {}, world["f1_headers"]),
            ERR_DEBRIEF_NOT_RECORDED,
            422,
        )

        debrief = validate_success(
            api.complete_program_block(
                block_ids[1], {"debrief_completed": True}, world["f1_headers"]
            )
        )

        assert debrief["status"] == "COMPLETED"
        assert debrief["debrief_completed"] is True
        assert debrief["actual_head_count"] == 1

        icebreaker = validate_success(
            api.get_program_block(block_ids[0], PROGRAM_DIRECTOR)
        )
        assert icebreaker["status"] == "COMPLETED"

        booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert booking["status"] == "DELIVERED"
        assert_money(booking["retained_cents"], DEPOSIT_CENTS, "retained_cents")
        assert_money(booking["deposit_allocated_cents"], 0, "deposit_allocated_cents")

        client = validate_success(api.get_group_client(gc_id, PROGRAM_DIRECTOR))
        assert_ledger(client, credit=PAYMENT_CENTS - DEPOSIT_CENTS, payments=PAYMENT_CENTS)
