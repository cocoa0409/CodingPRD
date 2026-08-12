"""Corner coverage: clock-sweep side effects — amenity delinquency cascade,
application expiry with construction-start guard, notice supersede gating,
event completion, notice send sweep."""
from test_helpers import (
    api_client,
    create_active_community,
    create_amenity_in_state,
    create_application,
    create_event_payload,
    create_and_schedule_notice,
    create_lot,
    create_phase,
    create_builder,
    create_proposed_budget,
    set_clock,
    get_success_data,
    validate_error,
    make_builder_rep_headers,
    make_design_reviewer_headers,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]
REVIEWER = TEST_USERS["design_reviewer_headers"]


class TestAmenityHardDeadlineDelinquencySweep:
    def test_sweep_past_hard_deadline_cascades(self):
        """PRD §3.2: "Two independent breach conditions drop a not-yet-open amenity into `DELINQUENT`: the sweep passing its `hard_deadline_date`, or a closing-driven trigger breach — whenever the trigger phase's `closed_lot_count` increments, every amenity keyed to that phase whose status is not already `OPEN` or `DELINQUENT` is checked, and a count strictly greater than `trigger_unit_count` breaches it (the closing that makes the count exactly equal to `trigger_unit_count` is safe). Entering `DELINQUENT` stamps `delinquency_recorded_at` with the logical clock and fires a three-part cascade: every `SCHEDULED` community event whose venue maps to this amenity's type is cancelled, with its RSVPs cancelled in turn (this is reachable precisely because scheduling an event only requires the venue's amenity to be under construction); and a `DRAFT` resident notice of type `AMENITY_DELINQUENCY` is auto-created for the community."

        Design: Corner/state_machines/amenity_hard_deadline_delinquency_sweep
        """
        community = create_active_community("Deadline Downs", 50)
        amenity = create_amenity_in_state(
            community["id"], "UNDER_CONSTRUCTION", "CLUBHOUSE",
            hard_deadline_date="2026-06-01T00:00:00Z",
        )
        # Scheduled at the default clock: 40-day lead is satisfied and the
        # amenity is UNDER_CONSTRUCTION, which the safety gate allows.
        event = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="Preview Night", venue="CLUBHOUSE",
                    start_at="2026-06-10T18:00:00Z", end_at="2026-06-10T21:00:00Z",
                    capacity=30,
                ),
                LIFESTYLE,
            )
        )
        scheduled = get_success_data(api_client.schedule_event(event["id"], LIFESTYLE))
        assert scheduled["status"] == "SCHEDULED"

        set_clock("2026-06-02T00:00:00Z")

        amenity_read = get_success_data(api_client.get_amenity(amenity["id"], EXEC))
        assert amenity_read["status"] == "DELINQUENT"
        assert amenity_read["delinquency_recorded_at"] == "2026-06-02T00:00:00.000Z"

        event_read = get_success_data(api_client.get_event(event["id"], LIFESTYLE))
        assert event_read["status"] == "CANCELLED"

        notices_resp = api_client.list_notices(LIFESTYLE, params={"community_id": community["id"]})
        notices = get_success_data(notices_resp)
        assert len(notices) >= 1
        auto = notices[0]
        assert auto["notice_type"] == "AMENITY_DELINQUENCY"
        assert auto["status"] == "DRAFT"


class TestApplicationExpirySweepAndConstructionStartGuard:
    def _setup_two_approved(self):
        community = create_active_community("Expiry Estates", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        lot1 = create_lot(phase["id"], "L1")
        lot2 = create_lot(phase["id"], "L2")
        builder = create_builder(community["id"], "Expiry Builders", "A")
        rev1 = make_design_reviewer_headers("rev-1")

        app1 = create_application(
            community["id"], lot1["id"], applicant_builder_id=builder["id"],
        )
        get_success_data(api_client.begin_review(app1["id"], rev1))
        approved1 = get_success_data(api_client.approve_application(app1["id"], rev1))

        app2 = create_application(
            community["id"], lot2["id"], applicant_builder_id=builder["id"],
        )
        get_success_data(api_client.begin_review(app2["id"], rev1))
        get_success_data(api_client.approve_application(app2["id"], rev1))
        get_success_data(
            api_client.record_construction_start(
                app2["id"], make_builder_rep_headers(builder["id"])
            )
        )
        return app1["id"], app2["id"], approved1

    def test_approved_application_expires_past_window(self):
        """PRD §3.7: "An `APPROVED` application is protected from expiry once the applicant records the start of construction; otherwise, when the logical clock passes `construction_start_by` with no construction start recorded, the sweep lapses it to `EXPIRED`."
        PRD §3.7: "Approval stamps `construction_start_by` at the logical clock plus 180 days; conditional approval records `conditions_text` and leaves the application `CONDITIONALLY_APPROVED` until the reviewer verifies the conditions, at which point it becomes `APPROVED` and `construction_start_by` is set the same way."

        Design: Corner/state_machines/application_expiry_sweep_and_construction_start_guard
        """
        app1_id, _, approved1 = self._setup_two_approved()
        assert approved1["construction_start_by"] == "2026-10-28T00:00:00.000Z"
        set_clock("2026-10-29T00:00:00Z")
        app1 = get_success_data(api_client.get_application(app1_id, REVIEWER))
        assert app1["status"] == "EXPIRED"

    def test_recorded_construction_start_prevents_expiry(self):
        """PRD §3.7: "An `APPROVED` application is protected from expiry once the applicant records the start of construction; otherwise, when the logical clock passes `construction_start_by` with no construction start recorded, the sweep lapses it to `EXPIRED`."

        Design: Corner/state_machines/application_expiry_sweep_and_construction_start_guard
        """
        _, app2_id, _ = self._setup_two_approved()
        set_clock("2026-10-29T00:00:00Z")
        app2 = get_success_data(api_client.get_application(app2_id, REVIEWER))
        assert app2["status"] == "APPROVED"


class TestNoticeSupersedeBreaksBudgetGating:
    def test_superseded_sent_notice_no_longer_satisfies_adopt_gate(self):
        """PRD §3.9: "Correction works by supersession: superseding a notice creates a fresh `DRAFT` successor from the supplied `subject`, `body`, `send_at`, and optional `effective_date`, carrying over the `notice_type`, `budget_id`, and `assessment_rate_id` of its predecessor and recording it as `supersedes_notice_id`, while the old notice — whether `DRAFT`, `SCHEDULED`, or even `SENT` — becomes `SUPERSEDED`. A superseded notice no longer satisfies the budget-adoption or rate-arm gating of §3.5, even if it had already been sent."

        Design: Corner/state_machines/notice_supersede_breaks_budget_gating
        """
        community = create_active_community("Supersede Shores", 10)
        budget = create_proposed_budget(community["id"], 2027, [("MANAGEMENT", 100000)])
        notice = create_and_schedule_notice(
            community["id"], "BUDGET_ADOPTION", "2026-05-02T00:00:00Z",
            budget_id=budget["id"], subject="v1", body="adoption",
        )
        set_clock("2026-05-02T00:00:00Z")
        set_clock("2026-05-17T00:00:00Z")

        successor = get_success_data(
            api_client.supersede_notice(
                notice["id"],
                {"subject": "v2 corrected", "body": "corrected figures",
                 "send_at": "2026-05-18T00:00:00Z"},
                LIFESTYLE,
            )
        )
        assert successor["status"] == "DRAFT"
        assert successor["supersedes_notice_id"] == notice["id"]

        old = get_success_data(api_client.get_notice(notice["id"], LIFESTYLE))
        assert old["status"] == "SUPERSEDED"

        resp = api_client.adopt_budget(budget["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_SENT)


class TestEventCompletionSweep:
    def test_event_completed_once_end_passes(self):
        """PRD §3.8: "Events whose `end_at` has passed are swept to `COMPLETED`."
        PRD §2.5: "Setting the clock runs a sweep that applies every scheduled transition whose moment has arrived: tranches whose due date is within thirty days open (`SCHEDULED` → `OPEN`), tranches past due with an unmet count are marked `MISSED` (demoting their builder to `PROBATION`), scheduled notices are sent (`SCHEDULED` → `SENT`), events whose end has passed complete (`SCHEDULED` → `COMPLETED`), armed assessment rates become `EFFECTIVE` at fiscal-year start, approved design applications past their construction-start window lapse to `EXPIRED`, called elections past their deadline lapse to `LAPSED`, and amenities whose statutory outside date has passed without opening become `DELINQUENT`.".

        Design: Corner/state_machines/event_completion_sweep
        """
        community = create_active_community("Completion Cove", 10)
        event = get_success_data(
            api_client.create_event(
                create_event_payload(
                    community_id=community["id"], title="Tour Day",
                    start_at="2026-05-20T10:00:00Z", end_at="2026-05-20T12:00:00Z",
                ),
                LIFESTYLE,
            )
        )
        get_success_data(api_client.schedule_event(event["id"], LIFESTYLE))
        set_clock("2026-05-21T00:00:00Z")
        read = get_success_data(api_client.get_event(event["id"], LIFESTYLE))
        assert read["status"] == "COMPLETED"


class TestNoticeSendSweepAndCancellation:
    def test_notice_sent_at_send_at_and_cancelled_stays_cancelled(self):
        """PRD §3.9: "Scheduling moves the notice from `DRAFT` to `SCHEDULED`; when the clock reaches `send_at`, the sweep sends it — `sent_at` is set to `send_at` — moving it to `SENT`. A `DRAFT` or `SCHEDULED` notice may be cancelled."

        Design: Corner/cross_cutting_complexity_layers/notice_send_sweep_and_cancellation
        """
        community = create_active_community("Sweep Shores", 10)
        n1 = create_and_schedule_notice(
            community["id"], "GENERAL_MEETING", "2026-05-10T00:00:00Z",
            subject="n1", body="one",
        )
        n2 = create_and_schedule_notice(
            community["id"], "GENERAL_MEETING", "2026-05-10T00:00:00Z",
            subject="n2", body="two",
        )
        set_clock("2026-05-09T00:00:00Z")
        pre = get_success_data(api_client.get_notice(n1["id"], LIFESTYLE))
        assert pre["status"] == "SCHEDULED"

        get_success_data(api_client.cancel_notice(n2["id"], LIFESTYLE))

        set_clock("2026-05-10T00:00:00Z")
        post1 = get_success_data(api_client.get_notice(n1["id"], LIFESTYLE))
        assert post1["status"] == "SENT"
        assert post1["sent_at"] == "2026-05-10T00:00:00.000Z"

        post2 = get_success_data(api_client.get_notice(n2["id"], LIFESTYLE))
        assert post2["status"] == "CANCELLED"
