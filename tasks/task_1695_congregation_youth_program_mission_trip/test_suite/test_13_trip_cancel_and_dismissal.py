"""Trip cancel depth-3 cascade, dismissal gates and the barred-participant
safety gate."""
from test_helpers import (
    ApiErrorId,
    add_cleared_chaperone_to_trip,
    add_donation,
    add_lodging,
    assert_fund_conserved,
    assert_same_instant,
    create_application,
    create_approved_registration,
    create_confirmed_registration,
    create_program,
    create_registration_payload,
    create_trip,
    decide_application,
    get_account,
    get_account_for_registration,
    get_application,
    get_program,
    get_registration,
    make_director_headers,
    make_guardian_headers,
    open_trip_registration,
    post_payment,
    setup_in_progress_trip_with_confirmed,
    setup_program_with_open_trip,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = make_director_headers()


def _cancel_cascade_setup(api):
    """Trip Alpha, REGISTRATION_CLOSED; one CONFIRMED registration with three
    VERIFIED forms, a RECEIVED donation, one POSTED payment, and an APPROVED
    scholarship of 70000."""
    program = create_program(scholarship_fund_total_cents=500000)
    trip = create_trip(program["id"])
    add_lodging(trip["id"], room_code="R1", room_capacity=30, cost_cents=0)
    open_trip_registration(trip["id"])
    add_cleared_chaperone_to_trip(trip["id"], program["id"])

    participant, registration, forms = create_approved_registration(
        trip["id"], "guardian-1",
        participant_overrides={"annual_income_bracket": "BAND_A",
                               "household_size": 5})
    account = get_account_for_registration(registration["id"])
    donation = add_donation(account["id"], 10000, "CASH")

    # need 70 = 50 + 15 + 0 + 5 (gross 10000 > 0, goal 0) ->
    # cap round_half_up(0.70*0.5*200000) = 70000 on the no-lodging basis.
    application = create_application(registration["id"], 100000, "guardian-1")
    approved_app = decide_application(application["id"], "APPROVE")
    assert approved_app["award_cents"] == 70000

    payment = post_payment(registration["id"], 50000, method="CHECK")
    confirmed = validate_success(
        api.confirm_registration(registration["id"], DIRECTOR), 200)
    validate_success(api.close_registration(trip["id"], DIRECTOR), 200)
    return {"program": program, "trip": trip, "participant": participant,
            "registration": confirmed, "forms": forms, "account": account,
            "donation": donation, "payment": payment,
            "application": approved_app}


class TestTripCancelDepth3Cascade:
    def test_cancel_cascades_registration_account_forms_payments(self, api):
        """PRD §3.2: "From `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`,
        `ROSTER_LOCKED`, or `IN_PROGRESS`, cancel runs the full depth-3 cascade.
        Hop 1: every registration in `DRAFT`, `SUBMITTED`, `APPROVED`,
        `WAITLISTED`, or `CONFIRMED` moves to `CANCELLED`. Hop 2, per cancelled
        registration: its `OPEN` fundraising account closes; each of its consent
        forms in `SUBMITTED`, `VERIFIED`, or `REJECTED` is `VOIDED`; ... and
        every `POSTED` payment is auto-refunded to `REFUNDED`, flipping the
        registration's `payment_status` to `REFUNDED` if at least one payment
        was refunded."

        Design: Difficulty/transitive_cascade/trip_cancel_depth3_registration_scholarship_program
        """
        ctx = _cancel_cascade_setup(api)
        cancelled = api.cancel_trip(ctx["trip"]["id"], DIRECTOR,
                                    payload={"reason": "host site withdrew"})
        assert validate_success(cancelled, 200)["status"] == "CANCELLED"

        registration = get_registration(ctx["registration"]["id"])
        assert registration["registration_status"] == "CANCELLED"
        assert registration["payment_status"] == "REFUNDED"

        listed, _ = validate_paginated(
            api.list_consent_forms(ctx["registration"]["id"], DIRECTOR))
        statuses = {f["id"]: f["status"] for f in listed}
        assert len(statuses) == 3
        assert all(status == "VOIDED" for status in statuses.values()), (
            f"all three consent forms VOIDED, got {statuses}")

        assert get_account(ctx["account"]["id"])["status"] == "CLOSED"

        payments, _ = validate_paginated(
            api.list_payments(ctx["registration"]["id"], DIRECTOR))
        assert [p["status"] for p in payments] == ["REFUNDED"]

    def test_cancel_cascades_scholarship_hop_into_program_fund(self, api):
        """PRD §3.2: "Hop 2, per cancelled registration: ... its scholarship
        application moves `UNDER_REVIEW` to `WITHDRAWN`, `APPROVED` to
        `RESCINDED`, or `DISBURSED` to `RETURNED` ... Hop 3: each scholarship
        status change recomputes the program fund triple — a `RESCINDED`
        application releases its reserved amount back to available, while a
        `RETURNED` application releases its disbursed amount."
        PRD §3.4: "When the registration finally reaches any terminal status ...
        its account closes; `RECEIVED` donations in a closed account stay
        refundable".

        Design: Difficulty/transitive_cascade/trip_cancel_depth3_registration_scholarship_program
        """
        ctx = _cancel_cascade_setup(api)
        pre = get_program(ctx["program"]["id"])
        assert pre["scholarship_reserved_cents"] == 70000
        assert pre["scholarship_available_cents"] == 430000

        api.cancel_trip(ctx["trip"]["id"], DIRECTOR)

        application = get_application(ctx["application"]["id"])
        assert application["status"] == "RESCINDED", (
            "APPROVED at cancel time -> RESCINDED through the cascade hop")

        post = get_program(ctx["program"]["id"])
        assert post["scholarship_reserved_cents"] == 0
        assert post["scholarship_available_cents"] == 500000, (
            "the fund mutation happens only THROUGH the rescind hop")
        assert_fund_conserved(post)

        donations, _ = validate_paginated(
            api.list_donations(ctx["account"]["id"], DIRECTOR))
        assert [d["status"] for d in donations] == ["RECEIVED"], (
            "account closure does not refund donations")


class TestDismissRequiresInProgress:
    def test_dismiss_rejected_before_trip_in_progress(self, api):
        """PRD §3.7: "Dismissal is the discipline instrument: a
        `ProgramDirector` may dismiss only a `CONFIRMED` registration, moving it
        to the terminal `DISMISSED` status, only while the trip is
        `IN_PROGRESS`" — on a `REGISTRATION_OPEN` trip the call fails the trip
        state gate (`ERR_TRIP_STATE_FORBIDS_ACTION`, §5).

        Design: Difficulty/cross_entity_state_dependency/dismiss_requires_trip_in_progress
        """
        program, trip = setup_program_with_open_trip(
            destination_type="IN_STATE", start_date="2027-06-15",
            end_date="2027-06-16", emergency_protocol_text="")
        _, registration, _, _ = create_confirmed_registration(
            trip["id"], guardian_user_id="guardian-1",
            payment_amount_cents=80000,
            registration_overrides={"insurance_tier": "NONE"})
        assert registration["registration_status"] == "CONFIRMED"

        resp = api.dismiss_registration(
            registration["id"],
            {"sanction": "BARRED_FROM_FUTURE", "reason": "curfew violation"},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_TRIP_STATE_FORBIDS_ACTION, 409)

    def test_dismiss_in_progress_records_sanction_and_keeps_payment(self, api):
        """PRD §3.7: "The sanction and rationale are recorded in
        `dismiss_sanction` and `dismiss_reason`; a `BARRED_FROM_FUTURE` sanction
        additionally sets the participant's `barred_until` to the current
        logical clock plus 730 days — two full screening cycles". "Unlike
        withdrawal, dismissal performs no payment auto-refund."

        Design: Difficulty/cross_entity_state_dependency/dismiss_requires_trip_in_progress
        """
        bundle = setup_in_progress_trip_with_confirmed(
            num_confirmed=1, room_capacity=2, payment_amount_cents=80000)
        registration = bundle["bundles"][0]["registration"]
        participant = bundle["bundles"][0]["participant"]
        assert bundle["trip"]["status"] == "IN_PROGRESS"

        dismissed = api.dismiss_registration(
            registration["id"],
            {"sanction": "BARRED_FROM_FUTURE", "reason": "curfew violation"},
            DIRECTOR)
        data = validate_success(dismissed, 200)
        assert data["registration_status"] == "DISMISSED"
        assert data["dismiss_sanction"] == "BARRED_FROM_FUTURE"
        assert data["dismiss_reason"] == "curfew violation"

        # dismissal clock 2027-06-15T00:00:00Z + 730 days
        participant_after = api.get_participant(participant["id"], DIRECTOR) \
            .json()["data"]
        assert_same_instant(participant_after["barred_until"],
                            "2029-06-14T00:00:00Z", "barred_until")

        registration_after = get_registration(registration["id"])
        assert registration_after["covered_cents"] == 80000, (
            "no payment auto-refund on dismissal")
        payments, _ = validate_paginated(
            api.list_payments(registration["id"], DIRECTOR))
        assert [p["status"] for p in payments] == ["POSTED"]


class TestBarredParticipantGate:
    def test_barred_participant_blocked_from_new_registration(self, api):
        """PRD §3.3: "the participant must not be barred — `barred_until` empty
        or earlier than the clock (`ERR_PARTICIPANT_BARRED`, HTTP 409)".
        PRD §3.7: a `BARRED_FROM_FUTURE` dismissal "sets the participant's
        `barred_until` to the current logical clock plus 730 days ... which then
        blocks that participant from new registrations and approvals until it
        passes."

        Design: Corner/validations/barred_participant_blocked_from_new_registration
        """
        bundle = setup_in_progress_trip_with_confirmed(
            num_confirmed=1, room_capacity=2, payment_amount_cents=80000)
        program = bundle["program"]
        registration = bundle["bundles"][0]["registration"]
        participant = bundle["bundles"][0]["participant"]
        validate_success(api.dismiss_registration(
            registration["id"],
            {"sanction": "BARRED_FROM_FUTURE",
             "reason": "repeated curfew violations"}, DIRECTOR), 200)

        # A second trip whose registration window covers the dismissal clock
        # (2027-06-15): the bar follows the participant, not the trip.
        theta = create_trip(
            program["id"], name="Theta", destination_type="IN_STATE",
            start_date="2027-08-01", end_date="2027-08-03",
            capacity_youth=10, base_cost_cents=50000, deposit_cents=10000,
            registration_open_at="2027-01-01T00:00:00Z",
            registration_close_at="2027-07-01T00:00:00Z",
            deposit_due_at="2027-07-10T00:00:00Z",
            final_payment_due_at="2027-07-20T00:00:00Z",
            emergency_protocol_text="")
        open_trip_registration(theta["id"])

        resp = api.create_registration(
            create_registration_payload(theta["id"], participant["id"],
                                        insurance_tier="NONE"),
            make_guardian_headers("guardian-1"))
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_BARRED, 409)
