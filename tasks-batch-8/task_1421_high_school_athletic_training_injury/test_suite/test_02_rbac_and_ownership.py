"""Role authorization, ownership scope, and segregation of duties (PRD §2.1)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_athlete_as_trainer,
    create_budget,
    create_eap_for,
    create_injury_for,
    create_order,
    create_supply_item,
    create_venue,
    director_headers,
    first_notification_for_athlete,
    make_coach,
    make_director,
    make_nurse,
    make_parent_guardian_headers,
    make_physician,
    make_team_coach_headers,
    make_trainer,
    nurse_headers,
    physician_headers,
    record_physical,
    schedule_referral,
    create_referral_for,
    submit_order,
    trainer_headers,
    validate_error,
    validate_success,
)


class TestCoachBoundaries:

    def test_coach_cannot_read_or_write_injuries(self):
        """PRD §2.1: "coaches may read staff, athletes, clearance summaries,
        venues, venue activity status, events, coverage status, coverage
        assignments, emergency action plans, supply items, and weather
        readings, but requests to injury, referral, return-to-play, physical,
        baseline-test, or guardian-notification resources are rejected with
        `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/coach_cannot_read_or_write_injuries
        """
        coach = make_coach()
        coach_h = make_team_coach_headers(coach["id"])
        resp = api_client.list_injuries(headers=coach_h)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        # Role authorization (pipeline stage 2) fires before field-shape
        # validation, so even an empty body draws the role error.
        resp = api_client.create_injury({}, coach_h)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestPhysicianBoundaries:

    def test_physician_cannot_document_injuries(self):
        """PRD §4: "POST | `/injuries` | Document an injury evaluation |
        AthleticTrainer".
        PRD §2.1: "When the caller's role is not among the roles an endpoint
        authorizes, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/physician_cannot_document_injuries
        """
        md = make_physician()
        tr1 = make_trainer()
        create_athlete_as_trainer(tr1, guardian_email=None)
        resp = api_client.create_injury({}, physician_headers(md))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_referral_completion_is_personal_to_named_physician(self):
        """PRD §3.6: "Completion is personal: the caller's `X-User-ID` must
        equal the referral's `physician_staff_id`, else
        `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/physician_complete_ownership_rejected
        """
        tr1 = make_trainer()
        md1 = make_physician("Doc One")
        md2 = make_physician("Doc Two")
        athlete = create_athlete_as_trainer(tr1, primary_sport="LACROSSE")
        injury = create_injury_for(athlete["id"], tr1, body_region="SHOULDER",
                                   severity="MODERATE", mechanism="check")
        referral = create_referral_for(injury["id"], md1, tr1,
                                       reason="shoulder eval")
        schedule_referral(referral["id"], tr1, "2026-08-02T10:00:00Z")

        resp = api_client.complete_referral(
            referral["id"],
            {"report_diagnosis": "wrong physician",
             "report_clearance": "CLEARED_FULL"},
            physician_headers(md2))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

        data = validate_success(api_client.complete_referral(
            referral["id"],
            {"report_diagnosis": "strain", "report_clearance": "CLEARED_FULL"},
            physician_headers(md1)))
        assert data["status"] == "COMPLETED"


class TestGuardianOwnership:

    def test_guardian_reads_own_athlete_only(self):
        """PRD §2.1: "A `ParentGuardian` may read an athlete's detail, list
        guardian notifications, and acknowledge a notification only for the
        athlete whose `guardian_user_id` equals the caller's `X-User-ID`."

        Design: Corner/rbac/guardian_reads_own_athlete_only
        """
        tr1 = make_trainer()
        athlete_a = create_athlete_as_trainer(
            tr1, primary_sport="SOFTBALL", team_level="JV",
            guardian_user_id="g-9705")
        athlete_b = create_athlete_as_trainer(
            tr1, primary_sport="BASEBALL", team_level="VARSITY",
            guardian_user_id="g-9706")
        guardian_a = make_parent_guardian_headers("g-9705")

        data = validate_success(api_client.get_athlete(
            athlete_a["id"], guardian_a))
        assert data["id"] == athlete_a["id"], "own child must be readable"

        resp = api_client.get_athlete(athlete_b["id"], guardian_a)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

        # The athletes collection is outside the guardian role entirely.
        resp = api_client.list_athletes(headers=guardian_a)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_guardian_acknowledge_ownership_scoped(self):
        """PRD §3.8: "a `ParentGuardian` may acknowledge a notification in
        either `SENT` or `ESCALATED`, moving it to `ACKNOWLEDGED` and stamping
        `acknowledged_at`, provided the caller's `X-User-ID` equals the
        athlete's `guardian_user_id` (otherwise `ERR_OWNERSHIP_MISMATCH`)."

        Design: Corner/rbac/guardian_ack_ownership_rejected
        """
        tr1 = make_trainer()
        coach = make_coach()
        athlete_a = create_athlete_as_trainer(
            tr1, team_level="JV", guardian_user_id="g-9701",
            guardian_email="ga@x.com")
        create_athlete_as_trainer(tr1, guardian_user_id="g-9702",
                                  guardian_email="gb@x.com")
        create_injury_for(athlete_a["id"], tr1)
        notification = first_notification_for_athlete(athlete_a["id"], tr1)
        sent = validate_success(api_client.send_guardian_notification(
            notification["id"], trainer_headers(tr1)))
        assert sent["status"] == "SENT"

        # A guardian of a different athlete is ownership-rejected.
        resp = api_client.acknowledge_guardian_notification(
            notification["id"], make_parent_guardian_headers("g-9702"))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

        # A TeamCoach lacks the acknowledge operation entirely.
        resp = api_client.acknowledge_guardian_notification(
            notification["id"], make_team_coach_headers(coach["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        data = validate_success(api_client.acknowledge_guardian_notification(
            notification["id"], make_parent_guardian_headers("g-9701")))
        assert data["status"] == "ACKNOWLEDGED"
        assert data["acknowledged_at"]


class TestSegregationOfDuties:

    def test_physical_recorder_cannot_verify(self):
        """PRD §3.1: "the verifying nurse may not be the staff member who
        recorded it: when `X-User-ID` equals the record's
        `recorded_by_staff_id`, the attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/physical_self_verify_rejected
        """
        nurse1 = make_nurse("Nurse One")
        nurse2 = make_nurse("Nurse Two")
        # Athlete registry writes are trainer/admin-only, so the admin
        # registers the athlete while the nurse records the physical.
        athlete = validate_success(api_client.create_athlete(
            {
                "full_name": "Athlete A",
                "date_of_birth": "2009-05-01",
                "grade": 10,
                "sex": "F",
                "primary_sport": "VOLLEYBALL",
                "team_level": "JV",
                "guardian_name": "GA",
                "guardian_user_id": "g-9602",
            },
            ADMIN), expected_status=201)
        physical = record_physical(athlete["id"], nurse1,
                                   recorder_role="SchoolNurse")
        assert physical["recorded_by_staff_id"] == nurse1["id"]

        resp = api_client.verify_physical(physical["id"],
                                          nurse_headers(nurse1))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        data = validate_success(api_client.verify_physical(
            physical["id"], nurse_headers(nurse2)))
        assert data["status"] == "VERIFIED"
        assert data["verified_by_staff_id"] == nurse2["id"]

    def test_eap_author_cannot_approve(self):
        """PRD §3.2: "the approver may not be the plan's author, so when
        `X-User-ID` equals `authored_by_staff_id` the approval is rejected
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/eap_author_cannot_approve_rejected
        """
        ad1 = make_director("Director One")
        ad2 = make_director("Director Two")
        tr1 = make_trainer()
        venue = create_venue()
        eap = create_eap_for(venue["id"], ad1,
                             author_role="AthleticDirector")
        assert eap["authored_by_staff_id"] == ad1["id"]
        validate_success(api_client.submit_eap(eap["id"],
                                               trainer_headers(tr1)))

        resp = api_client.approve_eap(eap["id"], director_headers(ad1))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        data = validate_success(api_client.approve_eap(
            eap["id"], director_headers(ad2)))
        assert data["status"] == "APPROVED"
        assert data["approved_by_staff_id"] == ad2["id"]

    def test_order_requester_cannot_approve(self):
        """PRD §3.9: "the approver may not be the requester — `X-User-ID`
        equal to `requested_by_staff_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES`, the third segregation rule".

        Design: Corner/rbac/order_requester_cannot_approve_rejected
        """
        ad1 = make_director("Director One")
        ad2 = make_director("Director Two")
        create_budget(2026, 100000)
        item = create_supply_item(category="FIRST_AID", unit="EACH",
                                  par_level=20, reorder_threshold=5,
                                  unit_cost_cents=500)
        order = create_order(item["id"], ad1,
                             requester_role="AthleticDirector",
                             quantity=4, unit_cost_cents=500)
        submit_order(order["id"], ad1, submitter_role="AthleticDirector")

        resp = api_client.approve_restock_order(order["id"],
                                                director_headers(ad1))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        data = validate_success(api_client.approve_restock_order(
            order["id"], director_headers(ad2)))
        assert data["status"] == "APPROVED"
        assert data["approved_by_staff_id"] == ad2["id"]
        budget = api_client.list_supply_budgets(
            ADMIN, params={"fiscal_year": 2026})
        rows = validate_success(budget)
        assert rows[0]["committed_spend_cents"] == 2000, (
            "only the successful approval commits budget")
