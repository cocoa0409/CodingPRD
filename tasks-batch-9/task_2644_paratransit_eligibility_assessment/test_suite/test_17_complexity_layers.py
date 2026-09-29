"""Layer interactions: OCC against a bubbled-up write, and sweep step order."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_PROCEEDING_STATE_INVALID,
    ERR_SLOT_FULL,
    ERR_STALE_APPLICANT_VERSION,
    ERR_STALE_APPLICATION_VERSION,
)
from test_helpers.assertions import (
    assert_conduct_mirrors,
    assert_day_ledger_conserved,
    assert_eligibility_mirrors,
    assert_slot_mirror,
    assert_sweep_counters,
)
from test_helpers.fixtures import (
    assessment_required,
    create_applicant,
    create_slot,
    ingest_trip_event,
    ingest_trip_events,
    issued_determination,
    run_day_close,
    scored_assessment,
    set_clock,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    CONDUCT_OFFICER_2_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
    SPECIALIST_2_HEADERS,
    SPECIALIST_HEADERS,
    make_applicant_headers,
)


def test_a_version_read_before_sign_off_is_stale_for_the_determination_draft(api):
    """The sign-off bubble-up consumes the version the specialist had read.

    "A `POST /applications/{id}/determinations` request must carry
    `expected_application_version` as a required field of its body, holding the
    `version` of the target `Application` as the client last observed it. If that
    value does not equal the application's current `version`, the draft is
    rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

    "A successful sign-off writes `signed_off_by_user_id` from the acting header,
    moves the scoring dimension `SCORED → SIGNED_OFF`, and bubbles up to the
    parent packet: an application sitting in `ASSESSMENT_SCHEDULED` whose
    assessment has attendance `ATTENDED` and scoring `SCORED` advances to
    `ASSESSMENT_COMPLETE`, and the packet's `version` increments with it."

    Design: Corner/cross_cutting_complexity_layers/a_version_observed_before_sign_off_is_stale_for_the_determination_draft
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Dilnoza Rakhimova",
        date_of_birth="1958-08-18",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    context = scored_assessment(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=False,
            max_walk_distance_meters=95,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        claimed_conditions=["end stage renal disease"],
        score_overrides={
            "board_alight_score": 0,
            "wayfinding_score": 2,
            "distance_meters_walked": 95,
            "heat_sensitivity_flag": False,
        },
    )
    application_id = context["application"]["id"]
    assert context["assessment"]["scoring_status"] == "SCORED"
    assert context["assessment"]["recommended_category"] == "UNCONDITIONAL"

    scored_view = validate_success(
        api.get_application(application_id, SPECIALIST_HEADERS)
    )
    assert scored_view["status"] == "ASSESSMENT_SCHEDULED"
    stale_version = scored_view["version"]

    signed = validate_success(
        api.sign_off_assessment(
            context["assessment"]["id"], factories.sign_off_payload(), SPECIALIST_2_HEADERS
        )
    )
    assert signed["scoring_status"] == "SIGNED_OFF"
    assert signed["signed_off_by_user_id"] == "spec-2"

    complete_view = validate_success(
        api.get_application(application_id, SPECIALIST_HEADERS)
    )
    assert complete_view["status"] == "ASSESSMENT_COMPLETE"
    assert complete_view["version"] == stale_version + 1

    validate_error(
        api.draft_determination(
            application_id,
            factories.determination_draft_payload(
                stale_version,
                category="UNCONDITIONAL",
                effective_date="2026-08-06",
                rationale="written from a pre-signoff view",
            ),
            SPECIALIST_HEADERS,
        ),
        ERR_STALE_APPLICATION_VERSION,
        412,
    )

    determination = validate_success(
        api.draft_determination(
            application_id,
            factories.determination_draft_payload(
                complete_view["version"],
                category="UNCONDITIONAL",
                effective_date="2026-08-06",
                rationale="cannot board fixed-route steps",
            ),
            SPECIALIST_HEADERS,
        ),
        201,
    )
    assert determination["status"] == "DRAFT"

    validate_error(
        api.draft_determination(
            application_id,
            factories.determination_draft_payload(
                stale_version,
                category="CONDITIONAL",
                effective_date="2026-08-06",
                rationale="replay from the same stale view",
                trip_conditions=[factories.trip_condition_payload()],
            ),
            SPECIALIST_HEADERS,
        ),
        ERR_STALE_APPLICATION_VERSION,
        412,
    )

    determinations, meta = validate_paginated(
        api.list_determinations(
            SPECIALIST_HEADERS, params={"application_id": application_id}
        )
    )
    assert meta["total_count"] == 1
    assert determinations[0]["id"] == determination["id"]


def test_a_conduct_write_invalidates_the_version_and_a_new_proposal_voids_the_old(api):
    """The OCC guard and the supersede edge are two halves of one rule.

    "A `POST /applicants/{id}/suspension-proceedings` request must carry
    `expected_applicant_version` as a required field of its body, holding the
    `version` of the target `Applicant` as the client last observed it. If that
    value does not equal the applicant's current `version`, the proposal is
    rejected with `ERR_STALE_APPLICANT_VERSION` (HTTP 412)."

    "Creating it also consolidates the record: every *other* proceeding of that
    rider still in `PROPOSED` moves `PROPOSED → VOID`, keeping `duration_days`,
    `days_served` and `days_forgiven` at zero, because the newer review supersedes
    the earlier proposal rather than running alongside it. The rider's `version`
    increments — which is exactly why this operation is version-guarded."

    "The event is stored with `recorded_at` stamped from the logical clock,
    `excused` false, `excuse_reason` null, and `points_assessed` set to 2 for an
    unexcused `NO_SHOW`, 1 for an unexcused `LATE_CANCEL`, and 0 for every other
    event type. The rider's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/a_conduct_write_invalidates_the_applicant_version_and_supersedes_the_open_proposal
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Emil Vartanyan",
        date_of_birth="1985-05-05",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    ingest_trip_events(
        api,
        rider["id"],
        [("2026-07-11", "NO_SHOW"), ("2026-07-18", "NO_SHOW")],
    )

    before = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert_conduct_mirrors(
        before, event_basis=4, miss_count=2, scheduled_count=2, ratio_pct=100.0
    )
    stale_version = before["version"]

    _none, empty_meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert empty_meta["total_count"] == 0

    completed = ingest_trip_event(
        api, rider["id"], trip_date="2026-07-25", event_type="COMPLETED"
    )
    assert completed["points_assessed"] == 0

    validate_error(
        api.propose_suspension(
            rider["id"],
            factories.suspension_proposal_payload(
                stale_version, grounds_note="written before the last event landed"
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        ERR_STALE_APPLICANT_VERSION,
        412,
    )

    fresh = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert fresh["version"] == stale_version + 1
    assert_conduct_mirrors(
        fresh, event_basis=4, miss_count=2, scheduled_count=3, ratio_pct=66.7
    )

    first = validate_success(
        api.propose_suspension(
            rider["id"],
            factories.suspension_proposal_payload(
                fresh["version"], grounds_note="first proposal"
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        201,
    )
    assert first["status"] == "PROPOSED"
    assert first["origin"] == "MANUAL"
    assert first["proposed_by_user_id"] == "co-1"
    assert first["points_at_proposal"] == 4

    validate_error(
        api.propose_suspension(
            rider["id"],
            factories.suspension_proposal_payload(
                fresh["version"], grounds_note="replay of the consumed version"
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        ERR_STALE_APPLICANT_VERSION,
        412,
    )

    consumed = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert consumed["version"] == fresh["version"] + 1

    second = validate_success(
        api.propose_suspension(
            rider["id"],
            factories.suspension_proposal_payload(
                consumed["version"],
                grounds_note="second proposal supersedes the first",
            ),
            CONDUCT_OFFICER_2_HEADERS,
        ),
        201,
    )
    assert second["status"] == "PROPOSED"
    assert second["proposed_by_user_id"] == "co-2"

    superseded = validate_success(
        api.get_suspension_proceeding(first["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert superseded["status"] == "VOID"
    assert superseded["duration_days"] == 0
    assert superseded["days_served"] == 0
    assert superseded["days_forgiven"] == 0
    assert_day_ledger_conserved(superseded)

    proceedings, meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 2
    assert {record["id"] for record in proceedings} == {first["id"], second["id"]}


def test_one_sweep_expires_the_grant_and_then_grants_presumptive_eligibility(api):
    """Step 3 clears the guard that step 4 tests, inside the same sweep.

    "Several steps may write the same rider's `current_eligibility_status` in one
    sweep. There is no precedence table: the last writer in step order simply
    wins. The ordering of steps 3 and 4 is therefore contractual and
    outcome-changing."

    "The sweep walks the rider's applications in `created_at` ascending order and
    grants presumptive eligibility to a packet when **all four** of the following
    hold at that moment: `days_pending_statutory` is at least 21; the packet's
    `status` is none of `DRAFT`, `RETURNED_INCOMPLETE` or `DETERMINED`;
    `presumptive_granted_at` is still null; and the rider holds no determination
    in `ISSUED` at that instant. When they hold, `presumptive_granted_at` is
    stamped with the sweep's instant and the rider's `current_eligibility_status`
    becomes `PRESUMPTIVE`."

    "**Hop 2**, caused by hop 1: the rider's `current_eligibility_status` becomes
    `EXPIRED`, `eligibility_category` becomes null, and `active_determination_id`
    becomes null."

    "The sweep is idempotent at a fixed clock: invoking it twice without moving
    the clock changes nothing on the second call."

    Design: Corner/cross_cutting_complexity_layers/day_close_step_three_runs_before_step_four_so_the_rider_ends_presumptive
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Fatou Diallo",
        date_of_birth="1979-09-29",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    slot = create_slot(
        api,
        starts_at="2026-02-05T09:00:00Z",
        ends_at="2026-02-05T10:00:00Z",
        capacity=2,
        site_is_wheelchair_accessible=True,
    )
    context = issued_determination(
        api,
        applicant=rider,
        slot=slot,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=180,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        claimed_conditions=["recovering hip fracture"],
        attests_permanent=False,
        score_overrides={
            "board_alight_score": 1,
            "wayfinding_score": 3,
            "distance_meters_walked": 180,
            "heat_sensitivity_flag": False,
        },
        attendance_at="2026-02-05T09:30:00Z",
        draft_overrides={
            "category": "TEMPORARY",
            "effective_date": "2026-02-06",
            "rationale": "recovery expected within six months",
        },
    )
    determination = context["determination"]
    assert context["assessment"]["recommended_category"] == "TEMPORARY"
    assert context["assessment"]["recommended_term_days"] == 180
    assert determination["status"] == "ISSUED"
    assert determination["term_days"] == 180
    assert determination["expires_at"] == "2026-08-05"
    assert_eligibility_mirrors(
        context["applicant"], "ELIGIBLE", "TEMPORARY", determination["id"]
    )

    set_clock(api, "2026-07-10T00:00:00Z")
    recert = validate_success(
        api.create_application(
            factories.application_payload(
                rider["id"],
                application_type="RECERTIFICATION",
                functional_answers=factories.functional_answers(
                    can_board_bus_steps=False,
                    can_navigate_unfamiliar_route=True,
                    max_walk_distance_meters=175,
                    uses_mobility_aid_outdoors=True,
                    has_cognitive_impairment=False,
                ),
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    recert = validate_success(
        api.submit_application(recert["id"], factories.submit_payload(), CLERK_HEADERS)
    )
    assert recert["status"] == "SUBMITTED"
    assert recert["determination_due_date"] == "2026-07-31"

    set_clock(api, "2026-08-05T00:00:00Z")
    sweep = run_day_close(api)
    assert_sweep_counters(
        sweep, determinations_expired_count=1, presumptive_granted_count=1
    )

    expired = validate_success(
        api.get_determination(determination["id"], SPECIALIST_HEADERS)
    )
    assert expired["status"] == "EXPIRED"

    holder = validate_success(api.get_applicant(rider["id"], SPECIALIST_HEADERS))
    assert_eligibility_mirrors(holder, "PRESUMPTIVE", None, None)

    packet = validate_success(api.get_application(recert["id"], CLERK_HEADERS))
    assert packet["days_pending_statutory"] == 26
    assert packet["presumptive_granted_at"] == "2026-08-05T00:00:00.000Z"

    again = run_day_close(api)
    assert_sweep_counters(
        again, determinations_expired_count=0, presumptive_granted_count=0
    )
    unchanged = validate_success(api.get_applicant(rider["id"], SPECIALIST_HEADERS))
    assert_eligibility_mirrors(unchanged, "PRESUMPTIVE", None, None)
    still_expired = validate_success(
        api.get_determination(determination["id"], SPECIALIST_HEADERS)
    )
    assert still_expired["status"] == "EXPIRED"


def test_the_response_lapse_fires_the_day_after_the_deadline_and_only_once(api):
    """The lapse is keyed to the date, so the deadline day itself is a no-op.

    "A `ConductOfficer` sends the written notice on a proceeding in `PROPOSED`,
    moving it `PROPOSED → NOTICE_SENT`, stamping `notice_sent_at` from the logical
    clock, and setting `response_deadline_date` to the calendar date of
    `notice_sent_at` plus 14 days."

    "Every `SuspensionProceeding` in `NOTICE_SENT` whose `response_deadline_date`
    falls strictly before today's date advances to `RESPONSE_LAPSED`, changing
    nothing but its status and `updated_at` — the lapse itself is the due-process
    evidence."

    "Sending a notice from any other status is `ERR_PROCEEDING_STATE_INVALID`
    (409), and that same code guards every other transition in this workflow whose
    source status is wrong."

    "The service mirror is `service_status`, which reads `SUSPENDED` for as long as
    any of the rider's suspension proceedings sits in `ACTIVE` and reads `ACTIVE`
    otherwise; it starts at `ACTIVE`."

    Design: Corner/cross_cutting_complexity_layers/the_response_lapse_sweep_fires_the_day_after_the_deadline_and_only_once
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Gustav Lindholm",
        date_of_birth="1965-05-15",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    ingest_trip_events(
        api,
        rider["id"],
        [("2026-07-12", "NO_SHOW"), ("2026-07-19", "NO_SHOW")],
    )
    observed = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert_conduct_mirrors(observed, event_basis=4, miss_count=2)

    proposal = validate_success(
        api.propose_suspension(
            rider["id"],
            factories.suspension_proposal_payload(
                observed["version"], grounds_note="two missed trips"
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        201,
    )
    assert proposal["status"] == "PROPOSED"

    set_clock(api, "2026-08-05T00:00:00Z")
    notice = validate_success(
        api.send_suspension_notice(
            proposal["id"], factories.send_notice_payload(), CONDUCT_OFFICER_HEADERS
        )
    )
    assert notice["status"] == "NOTICE_SENT"
    assert notice["notice_sent_at"] == "2026-08-05T00:00:00.000Z"
    assert notice["response_deadline_date"] == "2026-08-19"

    set_clock(api, "2026-08-19T23:59:59Z")
    on_deadline = run_day_close(api)
    assert_sweep_counters(on_deadline, proceedings_advanced_count=0)
    still_open = validate_success(
        api.get_suspension_proceeding(proposal["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert still_open["status"] == "NOTICE_SENT"

    set_clock(api, "2026-08-20T00:00:00Z")
    after_deadline = run_day_close(api)
    assert_sweep_counters(after_deadline, proceedings_advanced_count=1)
    lapsed = validate_success(
        api.get_suspension_proceeding(proposal["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert lapsed["status"] == "RESPONSE_LAPSED"
    assert lapsed["rider_response_at"] is None
    assert lapsed["duration_days"] == 0
    assert_day_ledger_conserved(lapsed)

    repeated = run_day_close(api)
    assert_sweep_counters(repeated, proceedings_advanced_count=0)
    unchanged = validate_success(
        api.get_suspension_proceeding(proposal["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert unchanged["status"] == "RESPONSE_LAPSED"

    validate_error(
        api.respond_to_suspension(
            proposal["id"],
            factories.rider_response_payload(rider_response_note="after the lapse"),
            make_applicant_headers(rider["id"]),
        ),
        ERR_PROCEEDING_STATE_INVALID,
        409,
    )

    final = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert final["service_status"] == "ACTIVE"


def test_the_auto_proposal_needs_all_three_thresholds_and_fires_at_six_points(api):
    """Five points with three misses at a hundred percent proposes nothing.

    "Three thresholds together define a suspendable pattern, and all three must
    hold simultaneously: `no_show_points_event_basis` at least 6,
    `chargeable_miss_count_90d` at least 3, and `no_show_ratio_pct` strictly
    greater than 10.0 percent. Whenever a trip event is ingested and all three
    hold, the system opens a proceeding on its own, provided no proceeding of that
    rider is already live"

    "The auto-created proceeding starts in `PROPOSED` with `origin`
    `AUTO_THRESHOLD`, `proposed_by_user_id` null, `grounds_note` null,
    `review_window_end_date` set to today's date as the last date of the window
    just evaluated, and `points_at_proposal` holding the rider's
    `no_show_points_event_basis` at that instant."

    Design: Corner/cross_cutting_complexity_layers/the_auto_proposal_needs_all_three_conditions_and_fires_exactly_at_six_points
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Halima Yusuf",
        date_of_birth="1992-12-12",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    events = ingest_trip_events(
        api,
        rider["id"],
        [
            ("2026-07-06", "NO_SHOW"),
            ("2026-07-13", "NO_SHOW"),
            ("2026-07-20", "LATE_CANCEL"),
        ],
    )
    assert [event["points_assessed"] for event in events] == [2, 2, 1]

    five_points = validate_success(
        api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert_conduct_mirrors(
        five_points, event_basis=5, miss_count=3, scheduled_count=3, ratio_pct=100.0
    )
    _none, empty_meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert empty_meta["total_count"] == 0

    fourth = ingest_trip_event(
        api, rider["id"], trip_date="2026-07-27", event_type="LATE_CANCEL"
    )
    assert fourth["points_assessed"] == 1

    six_points = validate_success(
        api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert_conduct_mirrors(
        six_points, event_basis=6, miss_count=4, scheduled_count=4, ratio_pct=100.0
    )

    proceedings, meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 1
    auto = proceedings[0]
    assert auto["status"] == "PROPOSED"
    assert auto["origin"] == "AUTO_THRESHOLD"
    assert auto["proposed_by_user_id"] is None
    assert auto["grounds_note"] is None
    assert auto["points_at_proposal"] == 6
    assert auto["review_window_end_date"] == "2026-08-01"

    ingest_trip_event(api, rider["id"], trip_date="2026-07-28", event_type="NO_SHOW")
    eight_points = validate_success(
        api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert eight_points["no_show_points_event_basis"] == 8

    still_one, still_one_meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert still_one_meta["total_count"] == 1
    assert still_one[0]["id"] == auto["id"]


def _packet_waiting_for_a_slot(
    api, full_name, date_of_birth, mobility_aid, walk_meters, condition
):
    """A rider whose packet has reached ASSESSMENT_REQUIRED, ready to be booked."""
    rider = create_applicant(
        api,
        full_name=full_name,
        date_of_birth=date_of_birth,
        residence_zone="IN_SERVICE_AREA",
        mobility_aid=mobility_aid,
    )
    return assessment_required(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=walk_meters,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        claimed_conditions=[condition],
    )


def test_the_slot_booked_count_and_status_reconcile_after_create_and_release(api):
    """Both derived slot fields are recomputed together, in both directions.

    "An `AssessmentSlot` maintains `booked_count`, the number of assessments on
    that slot whose `attendance_status` is `SCHEDULED` or `ATTENDED`, and derives
    `status` from it: `FULL` exactly when `booked_count` equals `capacity`, `OPEN`
    otherwise, starting at `OPEN` with a `booked_count` of 0."

    "The chosen slot must be `OPEN` — a slot at capacity is `ERR_SLOT_FULL` (409)"

    "The slot's `booked_count` decreases by one, and a slot that was `FULL` returns
    to `OPEN` as soon as its `booked_count` falls below its `capacity`."

    "It leaves the slot's `booked_count` unchanged, because an attended assessment
    still occupies its seat"

    Design: Corner/cross_cutting_complexity_layers/the_slot_booked_count_mirror_reconciles_after_create_and_after_release
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    slot = create_slot(
        api,
        site_name="Central Mobility Center",
        evaluator_user_id="eval-1",
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T10:00:00Z",
        capacity=2,
        site_is_wheelchair_accessible=True,
    )
    assert_slot_mirror(slot, booked_count=0, status="OPEN")

    first_packet = _packet_waiting_for_a_slot(
        api, "Ivo Petrescu", "1954-04-14", "CANE", 190, "copd"
    )
    second_packet = _packet_waiting_for_a_slot(
        api, "Jana Kowalczyk", "1961-01-31", "WALKER", 200, "lupus"
    )
    third_packet = _packet_waiting_for_a_slot(
        api, "Kwame Boateng", "1988-08-08", "NONE", 210, "epilepsy"
    )

    first = validate_success(
        api.book_assessment(
            first_packet["application"]["id"],
            factories.assessment_booking_payload(
                slot["id"], requires_wheelchair_position=False
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    after_one = validate_success(api.get_assessment_slot(slot["id"], CLERK_HEADERS))
    assert_slot_mirror(after_one, booked_count=1, status="OPEN")

    second = validate_success(
        api.book_assessment(
            second_packet["application"]["id"],
            factories.assessment_booking_payload(
                slot["id"], requires_wheelchair_position=False
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    after_two = validate_success(api.get_assessment_slot(slot["id"], CLERK_HEADERS))
    assert_slot_mirror(after_two, booked_count=2, status="FULL")

    validate_error(
        api.book_assessment(
            third_packet["application"]["id"],
            factories.assessment_booking_payload(
                slot["id"], requires_wheelchair_position=False
            ),
            CLERK_HEADERS,
        ),
        ERR_SLOT_FULL,
        409,
    )
    refused = validate_success(api.get_assessment_slot(slot["id"], CLERK_HEADERS))
    assert_slot_mirror(refused, booked_count=2, status="FULL")
    blocked = validate_success(
        api.get_application(third_packet["application"]["id"], CLERK_HEADERS)
    )
    assert blocked["status"] == "ASSESSMENT_REQUIRED"

    set_clock(api, "2026-08-05T09:10:00Z")
    missed = validate_success(
        api.record_attendance(
            first["id"], factories.attendance_payload("NO_SHOW"), EVALUATOR_HEADERS
        )
    )
    assert missed["attendance_status"] == "NO_SHOW"
    released = validate_success(api.get_assessment_slot(slot["id"], CLERK_HEADERS))
    assert_slot_mirror(released, booked_count=1, status="OPEN")
    regressed = validate_success(
        api.get_application(first_packet["application"]["id"], CLERK_HEADERS)
    )
    assert regressed["status"] == "ASSESSMENT_REQUIRED"

    attended = validate_success(
        api.record_attendance(
            second["id"], factories.attendance_payload("ATTENDED"), EVALUATOR_HEADERS
        )
    )
    assert attended["attendance_status"] == "ATTENDED"
    kept = validate_success(api.get_assessment_slot(slot["id"], CLERK_HEADERS))
    assert_slot_mirror(kept, booked_count=1, status="OPEN")
