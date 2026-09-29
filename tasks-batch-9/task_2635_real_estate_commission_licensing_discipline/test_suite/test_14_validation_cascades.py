"""Gates that only bite on one branch of an endpoint, and caps that close one door."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_AMENDMENT_LIMIT,
    ERR_CE_HOURS_INSUFFICIENT,
    ERR_CONSENT_ALREADY_OPEN,
    ERR_CONTINUANCE_LIMIT,
    ERR_DISCIPLINE_HOLD,
    ERR_PRELICENSE_HOURS_INSUFFICIENT,
    ERR_STATUTE_DEADLINE_PASSED,
)
from test_helpers.assertions import assert_ce_standing, assert_posture, expected_priority_score
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.test_users import (
    make_analyst_headers,
    make_chair_headers,
    make_counsel_headers,
    make_salesperson_headers,
)

FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"
SECOND_FIRM_NAME = "Cove Realty"
SECOND_BROKER_NAME = "Cal Broker"
SALESPERSON_NAME = "Sam Reed"
SHARED_HOURS = 90
SAT_ON = "2026-07-15"
PASSING_SCORE = 76


def _record_exam(client, licensee_id, score, taken_on=SAT_ON):
    return client.record_exam_result(
        licensee_id, factories.exam_result_payload(score, taken_on), make_analyst_headers()
    )


class TestThePreLicenceHourFloorIsPerLicenceClass:
    """Ninety hours qualifies one applicant and disqualifies the other."""

    def test_a_broker_with_ninety_hours_is_refused_at_the_result(self, client):
        """The broker floor is 180 hours, and the shortfall is caught on recording.

        The PRD says "Second the education gate: `prelicense_hours` must be at
        least the threshold for the applicant's class, which is 90 classroom hours
        for a `SALESPERSON` and 180 for a `BROKER`; a shortfall is refused with
        `ERR_PRELICENSE_HOURS_INSUFFICIENT`."

        Design: Corner/validations/prelicense_hours_below_the_class_requirement_block_the_exam_result
        """
        applicant = fixtures.create_applicant(
            client, "BROKER", "Bea Broker", prelicense_hours=SHARED_HOURS
        )
        assert applicant["prelicense_hours"] == SHARED_HOURS

        validate_error(
            _record_exam(client, applicant["id"], PASSING_SCORE),
            ERR_PRELICENSE_HOURS_INSUFFICIENT,
            expected_status=422,
        )

    def test_the_refused_result_does_not_consume_an_attempt(self, client):
        """Only a result that clears both gates counts against the applicant.

        The PRD says "Once past both gates, every recorded result increments
        `exam_attempt_count` by one and raises `exam_best_score` to the greater of
        its previous value and the score just recorded."

        Design: Corner/validations/prelicense_hours_below_the_class_requirement_block_the_exam_result
        """
        applicant = fixtures.create_applicant(
            client, "BROKER", "Bea Broker", prelicense_hours=SHARED_HOURS
        )
        validate_error(
            _record_exam(client, applicant["id"], PASSING_SCORE),
            ERR_PRELICENSE_HOURS_INSUFFICIENT,
        )

        untouched = fixtures.read_licensee(client, applicant["id"])
        assert untouched["exam_attempt_count"] == 0
        assert untouched["exam_best_score"] == 0
        assert untouched["exam_passed_at"] is None
        assert untouched["license_status"] == "APPLICANT"

    def test_the_same_hours_carry_a_salesperson_through(self, client):
        """Ninety hours meets the salesperson floor, and the clock stamps the pass.

        The PRD says "A score of 75 or higher is a pass: the applicant advances
        `APPLICANT → EXAM_PASSED`, and `exam_passed_at` is stamped with the current
        logical instant — the first passing result stamps it and no later result
        overwrites it, because a passing candidate has left `APPLICANT` behind."

        Design: Corner/validations/prelicense_hours_below_the_class_requirement_block_the_exam_result
        """
        applicant = fixtures.create_applicant(
            client, "SALESPERSON", SALESPERSON_NAME, prelicense_hours=SHARED_HOURS
        )

        examined = validate_success(_record_exam(client, applicant["id"], PASSING_SCORE))
        assert examined["license_status"] == "EXAM_PASSED"
        assert examined["exam_attempt_count"] == 1
        assert examined["exam_best_score"] == PASSING_SCORE
        assert examined["exam_passed_at"] == CLOCK_STARTUP_DEFAULT, (
            "the stamp comes from the logical clock, not from the date the exam was sat"
        )


TEAM_BRAND_TEXT = "Sam Reed Partners"
SCHOOL_NAME = "Coastal Institute"
INSTRUCTOR_NAME = "Ivy Teach"
CE_HOURS = 12


def _two_firms_a_shared_agent_and_a_team_brand(client):
    """Sam Reed leads an approved team brand at the firm he is about to leave."""
    first = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    second = fixtures.bootstrap_active_brokerage(
        client,
        name=SECOND_FIRM_NAME,
        broker_name=SECOND_BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    sam = fixtures.affiliate_new_salesperson(
        client, first["brokerage"]["id"], first["broker"]["id"], SALESPERSON_NAME
    )
    brand = fixtures.submit_advertising_name(
        client,
        first["brokerage"]["id"],
        TEAM_BRAND_TEXT,
        kind="TEAM",
        team_lead_licensee_id=sam["id"],
    )
    approved = fixtures.review_advertising_name(client, brand["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    school = fixtures.approved_provider_with_instructor(
        client, provider_name=SCHOOL_NAME, instructor_name=INSTRUCTOR_NAME
    )
    return {
        "first": first,
        "second": second,
        "sam": sam,
        "brand": approved,
        "school": school,
    }


def _transfer(client, world):
    receiving = fixtures.read_brokerage(client, world["second"]["brokerage"]["id"])
    return client.create_affiliation(
        world["sam"]["id"],
        factories.affiliation_payload(
            receiving["id"], world["second"]["broker"]["id"], receiving["version"]
        ),
        make_analyst_headers(),
    )


class TestTheTransferBranchCarriesAContinuingEducationGate:
    """A freshly issued licensee is already deficient, so the first move is refused."""

    def test_a_deficient_transferor_is_refused(self, client):
        """Zero valid hours against a twelve-hour requirement bars the move.

        The PRD says "And the licensee must not be continuing-education deficient:
        `ce_deficient` must be false, meaning their `ce_hours_valid` is at least
        their `ce_hours_required`, which for an `ACTIVE` licensee is the base
        requirement of 12 hours."

        The PRD says "A deficient transferor is refused with
        `ERR_CE_HOURS_INSUFFICIENT` — the same rule and the same error that gate
        reactivation in §3.4."

        Design: Corner/validations/a_ce_deficient_licensee_cannot_transfer_and_the_transfer_revokes_the_team_name
        """
        world = _two_firms_a_shared_agent_and_a_team_brand(client)
        issued = fixtures.read_licensee(client, world["sam"]["id"])
        assert_ce_standing(issued, valid=0, required=CE_HOURS)
        assert issued["ce_deficient"] is True
        receiving_before = fixtures.read_brokerage(client, world["second"]["brokerage"]["id"])

        validate_error(_transfer(client, world), ERR_CE_HOURS_INSUFFICIENT, expected_status=409)

        stayed = fixtures.read_licensee(client, world["sam"]["id"])
        assert stayed["sponsoring_brokerage_id"] == world["first"]["brokerage"]["id"]
        receiving_after = fixtures.read_brokerage(client, world["second"]["brokerage"]["id"])
        assert receiving_after["version"] == receiving_before["version"]
        assert receiving_after["affiliated_licensee_count"] == 1

    def test_twelve_core_hours_unlock_the_identical_request(self, client):
        """The completion cures the deficit and the transfer rewrites the chain.

        The PRD says "Its effect on the student depends on the course class:
        `CE_CORE` and `CE_ELECTIVE` hours are added to the student's
        `ce_hours_valid` when `completed_on` falls on or after that licensee's
        `ce_period_start_on`, `PRELICENSE` hours are added to the student's
        `prelicense_hours` — which is how an applicant who is short of the 90- or
        180-hour examination threshold gets there — and `POST_LICENSE` hours count
        toward neither."

        The PRD says "Which transition results depends on the licensee's current
        `license_status`: an `EXAM_PASSED` candidate is issued a licence and
        advances `EXAM_PASSED → ACTIVE`, while an already-`ACTIVE` licensee performs
        a transfer and stays `ACTIVE → ACTIVE`, a self-transition that nonetheless
        rewrites their supervisory chain and touches two brokerages."

        Design: Corner/validations/a_ce_deficient_licensee_cannot_transfer_and_the_transfer_revokes_the_team_name
        """
        world = _two_firms_a_shared_agent_and_a_team_brand(client)
        validate_error(_transfer(client, world), ERR_CE_HOURS_INSUFFICIENT)

        completion = validate_success(
            client.create_course_completion(
                factories.course_completion_payload(
                    world["sam"]["id"],
                    world["school"]["instructor"]["id"],
                    world["school"]["provider"]["id"],
                    CE_HOURS,
                    "2026-08-01",
                    "CE_CORE",
                ),
                make_analyst_headers(),
            ),
            expected_status=201,
        )
        assert completion["credit_status"] == "VALID"
        banked = fixtures.read_licensee(client, world["sam"]["id"])
        assert_ce_standing(banked, valid=CE_HOURS, required=CE_HOURS)
        assert banked["ce_deficient"] is False

        moved = validate_success(_transfer(client, world))
        assert moved["license_status"] == "ACTIVE"
        assert moved["sponsoring_brokerage_id"] == world["second"]["brokerage"]["id"]
        assert moved["supervising_broker_id"] == world["second"]["broker"]["id"]

    def test_the_transfer_re_stamps_nothing_and_revokes_the_team_brand(self, client):
        """A move is not an issuance, but it does cost the lead his brand.

        The PRD says "Initial issuance stamps the licence's calendar."

        The PRD says "Every advertising name of `kind` `TEAM` whose
        `team_lead_licensee_id` is this licensee and whose `status` is `APPROVED` is
        revoked — moved to `REVOKED` with `rejection_reason` `TEAM_LEAD_INELIGIBLE`
        — because a team brand cannot outlive its lead's departure from the firm
        that registered it."

        The PRD says "The receiving firm's `version` advances by one, and
        `affiliated_licensee_count` and `supervision_posture` are recomputed on
        **both** the firm being left and the firm being joined; forgetting the
        former leaves the departed firm overstating its supervisory load and, worse,
        mis-grading its posture."

        Design: Corner/validations/a_ce_deficient_licensee_cannot_transfer_and_the_transfer_revokes_the_team_name
        """
        world = _two_firms_a_shared_agent_and_a_team_brand(client)
        fixtures.record_completion(
            client,
            world["sam"]["id"],
            world["school"]["instructor"]["id"],
            world["school"]["provider"]["id"],
            credit_hours=CE_HOURS,
        )
        before = fixtures.read_licensee(client, world["sam"]["id"])
        leaving_before = fixtures.read_brokerage(client, world["first"]["brokerage"]["id"])
        joining_before = fixtures.read_brokerage(client, world["second"]["brokerage"]["id"])
        assert leaving_before["affiliated_licensee_count"] == 2

        after = validate_success(_transfer(client, world))
        assert after["license_expires_at"] == before["license_expires_at"]
        assert after["license_issued_at"] == before["license_issued_at"]
        assert after["ce_period_start_on"] == before["ce_period_start_on"]
        assert after["ce_hours_valid"] == CE_HOURS

        brand = fixtures.read_advertising_name(client, world["brand"]["id"])
        assert brand["status"] == "REVOKED"
        assert brand["rejection_reason"] == "TEAM_LEAD_INELIGIBLE"

        leaving_after = fixtures.read_brokerage(client, world["first"]["brokerage"]["id"])
        joining_after = fixtures.read_brokerage(client, world["second"]["brokerage"]["id"])
        assert leaving_after["affiliated_licensee_count"] == 1
        assert joining_after["affiliated_licensee_count"] == 2
        assert joining_after["version"] == joining_before["version"] + 1
        assert leaving_after["version"] == leaving_before["version"], (
            "only the receiving firm's version advances"
        )


ALLEGED_LOSS_CENTS = 300000
INVESTIGATOR = "counsel-01"


def _sanctioned_agent_with_a_clean_ce_record(client):
    """Sam Reed holds a reprimand, twelve CE hours and a live licence at Harbor."""
    world = _two_firms_a_shared_agent_and_a_team_brand(client)
    fixtures.record_completion(
        client,
        world["sam"]["id"],
        world["school"]["instructor"]["id"],
        world["school"]["provider"]["id"],
        credit_hours=CE_HOURS,
    )
    complaint = fixtures.complaint_at_probable_cause(
        client, world["sam"]["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS, INVESTIGATOR
    )
    order = fixtures.issue_order_by_consent(
        client, complaint["id"], world["sam"]["id"], "REPRIMAND", 0, 0
    )
    assert order["sanction_type"] == "REPRIMAND"
    world["complaint"] = complaint
    world["order"] = order
    return world


class TestOneDisciplineHoldWithTwoDifferentBlockingSets:
    """A reprimand stops the move to another firm but not the trip to the shelf."""

    def test_the_reprimand_sanctions_the_agent_without_touching_the_licence(self, client):
        """`SANCTIONED` and `ACTIVE` are two dimensions, and only one moved.

        The PRD says "A `REPRIMAND`, `FINE` or `PROBATION` leaves `license_status`
        alone."

        The PRD says "`prior_sanction_count` itself counts the sanction orders
        naming this licensee as respondent whose `status` is `ISSUED`, `IN_DEFAULT`
        or `SATISFIED`; a `VACATED` order is excluded, so a successful
        reconsideration genuinely lowers the respondent's future scores."

        Design: Corner/validations/a_sanctioned_licensee_may_park_the_licence_but_may_not_transfer_it
        """
        world = _sanctioned_agent_with_a_clean_ce_record(client)

        sam = fixtures.read_licensee(client, world["sam"]["id"])
        assert sam["discipline_status"] == "SANCTIONED"
        assert sam["license_status"] == "ACTIVE"
        assert sam["prior_sanction_count"] == 1

    def test_the_transfer_is_refused_by_the_discipline_hold_alone(self, client):
        """Neither the CE gate nor the posture gate can be masking this refusal.

        The PRD says "The licensee's `discipline_status` must be neither
        `PENDING_HEARING` nor `SANCTIONED`, or the transfer is refused with
        `ERR_DISCIPLINE_HOLD`."

        Design: Corner/validations/a_sanctioned_licensee_may_park_the_licence_but_may_not_transfer_it
        """
        world = _sanctioned_agent_with_a_clean_ce_record(client)
        sam = fixtures.read_licensee(client, world["sam"]["id"])
        assert sam["ce_deficient"] is False, "the education gate is satisfied"
        receiving_before = fixtures.read_brokerage(client, world["second"]["brokerage"]["id"])
        assert_posture(receiving_before, "COMPLIANT")

        validate_error(_transfer(client, world), ERR_DISCIPLINE_HOLD, expected_status=409)

        stayed = fixtures.read_licensee(client, world["sam"]["id"])
        assert stayed["sponsoring_brokerage_id"] == world["first"]["brokerage"]["id"]
        receiving_after = fixtures.read_brokerage(client, world["second"]["brokerage"]["id"])
        assert receiving_after["version"] == receiving_before["version"]
        assert receiving_after["affiliated_licensee_count"] == 1

    def test_the_same_agent_may_still_park_the_licence(self, client):
        """Inactivation is barred only by a pending hearing, so this one goes through.

        The PRD says "Their `discipline_status` must not be `PENDING_HEARING` — a
        respondent awaiting a hearing may not go quiet, and the attempt is refused
        with `ERR_DISCIPLINE_HOLD`."

        The PRD says "Parking stamps `inactive_since` with the current logical
        instant and clears both `sponsoring_brokerage_id` and
        `supervising_broker_id`."

        Design: Corner/validations/a_sanctioned_licensee_may_park_the_licence_but_may_not_transfer_it
        """
        world = _sanctioned_agent_with_a_clean_ce_record(client)
        validate_error(_transfer(client, world), ERR_DISCIPLINE_HOLD)

        parked = validate_success(
            fixtures.status_change(
                client,
                world["sam"]["id"],
                "GO_INACTIVE",
                headers=make_salesperson_headers(world["sam"]["id"]),
            )
        )
        assert parked["license_status"] == "INACTIVE"
        assert parked["discipline_status"] == "SANCTIONED"
        assert parked["inactive_since"] == CLOCK_STARTUP_DEFAULT
        assert parked["sponsoring_brokerage_id"] is None
        assert parked["supervising_broker_id"] is None

        left = fixtures.read_brokerage(client, world["first"]["brokerage"]["id"])
        assert left["affiliated_licensee_count"] == 1
        assert_posture(left, "COMPLIANT")


COUNSEL = "counsel-01"
SCREENER = "counsel-05"
CHAIR = "chair-01"
HEARING_START = "2026-08-10T09:00:00Z"
HEARING_END = "2026-08-10T11:00:00Z"
HEARING_ROOM = "ROOM_A"
COUNTER_FINE_CENTS = 100000


def _case_ready_for_either_channel(client):
    """A probable-cause misrepresentation case with both roads still open."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    sam = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], SALESPERSON_NAME
    )
    complaint = fixtures.complaint_at_probable_cause(
        client, sam["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS, SCREENER
    )
    assert complaint["status"] == "PROBABLE_CAUSE"
    return {"firm": firm, "sam": sam, "complaint": complaint}


def _offer(client, complaint_id):
    return client.create_consent_agreement(
        complaint_id,
        factories.consent_offer_payload("SUSPENSION", 200000, 30),
        make_counsel_headers(COUNSEL),
    )


def _try_to_schedule(client, complaint_id):
    return client.schedule_hearing(
        complaint_id,
        factories.hearing_payload(CHAIR, HEARING_START, HEARING_END, HEARING_ROOM),
        make_counsel_headers(COUNSEL),
    )


class TestAnOpenConsentChannelClosesBothRoads:
    """The exclusivity answer is preferred over the bare state complaint."""

    def test_a_second_offer_is_refused_by_exclusivity_not_by_state(self, client):
        """The complaint has left `PROBABLE_CAUSE`, yet the answer is the channel error.

        The PRD says "A second attempt is refused with `ERR_CONSENT_ALREADY_OPEN` —
        and, as §2.11 explains, that exclusivity answer is preferred over the
        generic from-state answer even though the complaint has by then left
        `PROBABLE_CAUSE`."

        Design: Corner/validations/an_open_consent_negotiation_blocks_both_a_second_offer_and_a_hearing
        """
        world = _case_ready_for_either_channel(client)
        complaint_id = world["complaint"]["id"]

        first = validate_success(_offer(client, complaint_id), expected_status=201)
        assert first["round_number"] == 1
        assert first["status"] == "OFFERED"
        assert first["offered_by_user_id"] == COUNSEL
        assert fixtures.read_complaint(client, complaint_id)["status"] == "CONSENT_PENDING"

        validate_error(_offer(client, complaint_id), ERR_CONSENT_ALREADY_OPEN, expected_status=409)

        rows, meta = validate_paginated(
            client.list_consent_agreements(complaint_id, make_counsel_headers(COUNSEL))
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

    def test_the_hearing_road_is_shut_while_the_offer_is_open_or_countered(self, client):
        """A countered offer is still an open channel, so the panel cannot be seated.

        The PRD says "Both channels are opened by a `CommissionCounsel`, and both
        are guarded by the same exclusivity rule: neither may be opened while the
        complaint already has a consent agreement in `OFFERED`, `COUNTERED` or
        `ACCEPTED`, or a hearing in `SCHEDULED`, `CONVENED` or `CONTINUED`."

        Design: Corner/validations/an_open_consent_negotiation_blocks_both_a_second_offer_and_a_hearing
        """
        world = _case_ready_for_either_channel(client)
        complaint_id = world["complaint"]["id"]
        agreement = validate_success(_offer(client, complaint_id), expected_status=201)

        validate_error(_try_to_schedule(client, complaint_id), ERR_CONSENT_ALREADY_OPEN)
        _rows, meta = validate_paginated(
            client.list_hearings(complaint_id, make_counsel_headers(COUNSEL))
        )
        assert meta["total_count"] == 0

        countered = fixtures.respondent_replies(
            client,
            agreement["id"],
            world["sam"]["id"],
            "COUNTER",
            counter_fine_cents=COUNTER_FINE_CENTS,
        )
        assert countered["status"] == "COUNTERED"
        assert countered["round_number"] == 1
        assert countered["counter_fine_cents"] == COUNTER_FINE_CENTS
        assert countered["responded_by_user_id"] == world["sam"]["id"]

        validate_error(_try_to_schedule(client, complaint_id), ERR_CONSENT_ALREADY_OPEN)

    def test_withdrawal_reopens_the_byte_identical_hearing_request(self, client):
        """Closing the consent channel without adjudication reopens both roads.

        The PRD says "When a channel closes without an adjudication the complaint
        returns to `PROBABLE_CAUSE` and both roads reopen."

        Design: Corner/validations/an_open_consent_negotiation_blocks_both_a_second_offer_and_a_hearing
        """
        world = _case_ready_for_either_channel(client)
        complaint_id = world["complaint"]["id"]
        agreement = validate_success(_offer(client, complaint_id), expected_status=201)
        fixtures.respondent_replies(
            client,
            agreement["id"],
            world["sam"]["id"],
            "COUNTER",
            counter_fine_cents=COUNTER_FINE_CENTS,
        )
        validate_error(_try_to_schedule(client, complaint_id), ERR_CONSENT_ALREADY_OPEN)

        withdrawn = fixtures.commission_replies(
            client, agreement["id"], "WITHDRAW", counsel_user_id=COUNSEL
        )
        assert withdrawn["status"] == "REJECTED"
        assert fixtures.read_complaint(client, complaint_id)["status"] == "PROBABLE_CAUSE"

        hearing = validate_success(_try_to_schedule(client, complaint_id), expected_status=201)
        assert hearing["status"] == "SCHEDULED"
        assert hearing["continuance_count"] == 0
        assert fixtures.read_complaint(client, complaint_id)["status"] == "HEARING_SCHEDULED"
        assert fixtures.read_licensee(client, world["sam"]["id"])["discipline_status"] == (
            "PENDING_HEARING"
        )


FIRST_SLOT_START = "2026-08-11T09:00:00Z"
FIRST_SLOT_END = "2026-08-11T11:00:00Z"
SECOND_SLOT_START = "2026-08-12T09:00:00Z"
SECOND_SLOT_END = "2026-08-12T11:00:00Z"
SECOND_ROOM = "ROOM_B"


def _hearing_scheduled_on_a_misrepresentation_case(client):
    """A panel seated for Sam Reed's case, chaired by someone who did not investigate."""
    world = _case_ready_for_either_channel(client)
    hearing = fixtures.schedule_hearing(
        client,
        world["complaint"]["id"],
        CHAIR,
        HEARING_START,
        HEARING_END,
        HEARING_ROOM,
        counsel_user_id=COUNSEL,
    )
    assert hearing["status"] == "SCHEDULED"
    assert hearing["continuance_count"] == 0
    world["hearing"] = hearing
    return world


def _convene(client, hearing_id, at_instant):
    fixtures.move_clock(client, at_instant)
    convened = fixtures.dispose_hearing(client, hearing_id, CHAIR, "CONVENE")
    assert convened["status"] == "CONVENED"
    assert convened["convened_at"] == at_instant
    return convened


def _continue_raw(client, hearing_id, start_at, end_at, hearing_room=None):
    return client.hearing_disposition(
        hearing_id,
        factories.hearing_disposition_payload(
            "CONTINUE",
            rescheduled_start_at=start_at,
            rescheduled_end_at=end_at,
            hearing_room=hearing_room,
        ),
        make_chair_headers(CHAIR),
    )


class TestTheContinuanceCapClosesOnlyTheRescheduleChannel:
    """Two postponements are the chair's allowance; the decision survives the third."""

    def test_the_two_permitted_continuances_move_the_slot_and_the_room(self, client):
        """Each continuance costs a convene, and the room override is optional.

        The PRD says "On success `continuance_count` is incremented by one,
        `scheduled_start_at`, `scheduled_end_at` and `hearing_room` are overwritten
        with the new slot, and `convened_at` is reset to null."

        The PRD says "The observable end state of a granted continuance is therefore
        `SCHEDULED`, and the cycle `SCHEDULED → CONVENED → CONTINUED → SCHEDULED` may
        run at most twice."

        Design: Corner/validations/the_continuance_cap_closes_the_reschedule_channel_but_not_the_decision
        """
        world = _hearing_scheduled_on_a_misrepresentation_case(client)
        hearing_id = world["hearing"]["id"]

        _convene(client, hearing_id, HEARING_START)
        first = validate_success(
            _continue_raw(client, hearing_id, FIRST_SLOT_START, FIRST_SLOT_END)
        )
        assert first["continuance_count"] == 1
        assert first["status"] == "SCHEDULED"
        assert first["scheduled_start_at"] == FIRST_SLOT_START
        assert first["hearing_room"] == HEARING_ROOM, "no room was supplied, so the room holds"
        assert first["convened_at"] is None

        _convene(client, hearing_id, FIRST_SLOT_START)
        second = validate_success(
            _continue_raw(
                client, hearing_id, SECOND_SLOT_START, SECOND_SLOT_END, hearing_room=SECOND_ROOM
            )
        )
        assert second["continuance_count"] == 2
        assert second["status"] == "SCHEDULED"
        assert second["hearing_room"] == SECOND_ROOM

    def test_the_third_continuance_is_refused_and_changes_nothing(self, client):
        """At the cap the postponement channel closes while the panel sits convened.

        The PRD says "It is permitted only while `continuance_count` is strictly
        below 2, and a third continuance is refused with `ERR_CONTINUANCE_LIMIT`."

        Design: Corner/validations/the_continuance_cap_closes_the_reschedule_channel_but_not_the_decision
        """
        world = _hearing_scheduled_on_a_misrepresentation_case(client)
        hearing_id = world["hearing"]["id"]
        _convene(client, hearing_id, HEARING_START)
        fixtures.dispose_hearing(
            client,
            hearing_id,
            CHAIR,
            "CONTINUE",
            rescheduled_start_at=FIRST_SLOT_START,
            rescheduled_end_at=FIRST_SLOT_END,
        )
        _convene(client, hearing_id, FIRST_SLOT_START)
        fixtures.dispose_hearing(
            client,
            hearing_id,
            CHAIR,
            "CONTINUE",
            rescheduled_start_at=SECOND_SLOT_START,
            rescheduled_end_at=SECOND_SLOT_END,
            hearing_room=SECOND_ROOM,
        )
        _convene(client, hearing_id, SECOND_SLOT_START)

        validate_error(
            _continue_raw(client, hearing_id, "2026-08-13T09:00:00Z", "2026-08-13T11:00:00Z"),
            ERR_CONTINUANCE_LIMIT,
            expected_status=409,
        )

        held = validate_success(client.get_hearing(hearing_id, make_chair_headers(CHAIR)))
        assert held["status"] == "CONVENED"
        assert held["continuance_count"] == 2
        assert held["scheduled_start_at"] == SECOND_SLOT_START
        assert held["hearing_room"] == SECOND_ROOM

    def test_the_decision_still_runs_from_the_same_convened_state(self, client):
        """The other move out of `CONVENED` is untouched by the continuance cap.

        The PRD says "A finding of `NO_VIOLATION` creates no order at all: the
        complaint moves `HEARING_SCHEDULED → CLOSED_NO_ACTION` and the respondent's
        `discipline_status` returns to `CLEARED`, subject to the same requirement
        that no other open complaint against them remains."

        Design: Corner/validations/the_continuance_cap_closes_the_reschedule_channel_but_not_the_decision
        """
        world = _hearing_scheduled_on_a_misrepresentation_case(client)
        hearing_id = world["hearing"]["id"]
        complaint_id = world["complaint"]["id"]
        _convene(client, hearing_id, HEARING_START)
        fixtures.dispose_hearing(
            client,
            hearing_id,
            CHAIR,
            "CONTINUE",
            rescheduled_start_at=FIRST_SLOT_START,
            rescheduled_end_at=FIRST_SLOT_END,
        )
        _convene(client, hearing_id, FIRST_SLOT_START)
        fixtures.dispose_hearing(
            client,
            hearing_id,
            CHAIR,
            "CONTINUE",
            rescheduled_start_at=SECOND_SLOT_START,
            rescheduled_end_at=SECOND_SLOT_END,
            hearing_room=SECOND_ROOM,
        )
        _convene(client, hearing_id, SECOND_SLOT_START)
        validate_error(
            _continue_raw(client, hearing_id, "2026-08-13T09:00:00Z", "2026-08-13T11:00:00Z"),
            ERR_CONTINUANCE_LIMIT,
        )

        decided = fixtures.dispose_hearing(
            client, hearing_id, CHAIR, "DECIDE", finding="NO_VIOLATION"
        )
        assert decided["status"] == "DECIDED"
        assert decided["finding"] == "NO_VIOLATION"
        assert decided["decided_at"] == SECOND_SLOT_START

        assert fixtures.read_complaint(client, complaint_id)["status"] == "CLOSED_NO_ACTION"
        assert fixtures.read_licensee(client, world["sam"]["id"])["discipline_status"] == "CLEARED"
        assert fixtures.orders_for_complaint(client, complaint_id) == []
        firm = fixtures.read_brokerage(client, world["firm"]["brokerage"]["id"])
        assert firm["open_complaint_count"] == 0
        assert_posture(firm, "COMPLIANT")


AMENDED_LOSS_CENTS = 1200000
STATUTE_DEADLINE = "2027-01-28T00:00:00Z"
ONE_SECOND_IN_HAND = "2027-01-27T23:59:59Z"


def _case_under_investigation(client):
    """Sam Reed's misrepresentation case, screened in on the day it was filed."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    sam = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], SALESPERSON_NAME
    )
    complaint = fixtures.file_complaint(
        client, sam["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS
    )
    screened = fixtures.dispose_complaint(
        client, complaint["id"], "INVESTIGATE", investigator_user_id=SCREENER
    )
    assert screened["status"] == "INVESTIGATION"
    assert screened["statute_deadline_at"] == STATUTE_DEADLINE
    return {"firm": firm, "sam": sam, "complaint": complaint}


def _request_amendment(client, complaint_id):
    return client.complaint_disposition(
        complaint_id,
        factories.complaint_disposition_payload("REQUEST_AMENDMENT"),
        make_counsel_headers(SCREENER),
    )


def _amend(client, complaint_id, amended_alleged_loss_cents=None):
    return client.create_amendment(
        complaint_id,
        factories.amendment_payload(
            "The complainant restates the loss.", amended_alleged_loss_cents
        ),
        make_analyst_headers(),
    )


def _find_probable_cause(client, complaint_id):
    return client.complaint_disposition(
        complaint_id,
        factories.complaint_disposition_payload("PROBABLE_CAUSE"),
        make_counsel_headers(SCREENER),
    )


class TestTheAmendmentCapAndTheStatuteDeadlineCloseTheCase:
    """A counted cap on one side of the case and a wall clock on the other."""

    def test_the_complainant_s_filing_is_what_advances_the_count_and_the_score(self, client):
        """The request pauses the case; the answer counts and re-scores it.

        The PRD says "This returns the case `AMENDMENT_REQUESTED → INVESTIGATION`,
        increments `amendment_count` by one, overwrites `alleged_loss_cents` with
        the amended value when one was supplied, and re-scores the case under the
        investigation variant — which is precisely how a complainant can lift a
        borderline case over the probable-cause floor."

        Design: Corner/validations/the_amendment_cap_and_the_statute_deadline_close_the_case_from_two_directions
        """
        world = _case_under_investigation(client)
        complaint_id = world["complaint"]["id"]

        paused = validate_success(_request_amendment(client, complaint_id))
        assert paused["status"] == "AMENDMENT_REQUESTED"
        assert paused["amendment_count"] == 0, "the count follows the complainant, not the request"

        amended = validate_success(_amend(client, complaint_id, AMENDED_LOSS_CENTS))
        assert amended["status"] == "INVESTIGATION"
        assert amended["amendment_count"] == 1
        assert amended["alleged_loss_cents"] == AMENDED_LOSS_CENTS
        assert amended["priority_score"] == expected_priority_score(
            "MISREPRESENTATION",
            AMENDED_LOSS_CENTS,
            prior_sanction_count=0,
            supervision_posture="COMPLIANT",
            include_prior_and_posture=True,
        )
        assert amended["priority_score"] == 52

    def test_the_third_request_is_refused_once_two_amendments_have_landed(self, client):
        """A silent second amendment leaves the figures alone and shuts the loop.

        The PRD says "It is available only while `amendment_count` is below 2, and a
        third request is refused with `ERR_AMENDMENT_LIMIT`."

        Design: Corner/validations/the_amendment_cap_and_the_statute_deadline_close_the_case_from_two_directions
        """
        world = _case_under_investigation(client)
        complaint_id = world["complaint"]["id"]
        validate_success(_request_amendment(client, complaint_id))
        validate_success(_amend(client, complaint_id, AMENDED_LOSS_CENTS))
        validate_success(_request_amendment(client, complaint_id))

        second = validate_success(_amend(client, complaint_id))
        assert second["amendment_count"] == 2
        assert second["alleged_loss_cents"] == AMENDED_LOSS_CENTS
        assert second["priority_score"] == 52

        validate_error(
            _request_amendment(client, complaint_id), ERR_AMENDMENT_LIMIT, expected_status=409
        )
        held = fixtures.read_complaint(client, complaint_id)
        assert held["status"] == "INVESTIGATION"
        assert held["amendment_count"] == 2

    def test_at_exactly_the_deadline_probable_cause_is_out_of_time(self, client):
        """The comparison is strict, so the deadline instant itself is too late.

        The PRD says "Two gates apply: the current instant must be strictly before
        `statute_deadline_at`, and a request at or after that instant is refused
        with `ERR_STATUTE_DEADLINE_PASSED`; and the investigation-variant
        `priority_score` must be at least 40, with anything lower refused as
        `ERR_PROBABLE_CAUSE_SCORE_TOO_LOW`."

        Design: Corner/validations/the_amendment_cap_and_the_statute_deadline_close_the_case_from_two_directions
        """
        world = _case_under_investigation(client)
        complaint_id = world["complaint"]["id"]
        validate_success(_request_amendment(client, complaint_id))
        scored = validate_success(_amend(client, complaint_id, AMENDED_LOSS_CENTS))
        assert scored["priority_score"] == 52, "the score gate is satisfied"

        fixtures.move_clock(client, STATUTE_DEADLINE)
        validate_error(
            _find_probable_cause(client, complaint_id),
            ERR_STATUTE_DEADLINE_PASSED,
            expected_status=409,
        )
        assert fixtures.read_complaint(client, complaint_id)["status"] == "INVESTIGATION"

    def test_one_second_earlier_the_same_request_is_in_time(self, client):
        """A single second on the right side of the limitation period saves the case.

        The PRD says "The complaint opens in `SUBMITTED` with `filed_at` stamped at
        the current logical instant and `statute_deadline_at` set to that instant
        plus a 180-day limitation period, expressed as 180 multiples of 86,400
        seconds."

        Design: Corner/validations/the_amendment_cap_and_the_statute_deadline_close_the_case_from_two_directions
        """
        world = _case_under_investigation(client)
        complaint_id = world["complaint"]["id"]
        validate_success(_request_amendment(client, complaint_id))
        validate_success(_amend(client, complaint_id, AMENDED_LOSS_CENTS))

        fixtures.move_clock(client, ONE_SECOND_IN_HAND)
        found = validate_success(_find_probable_cause(client, complaint_id))
        assert found["status"] == "PROBABLE_CAUSE"
        assert found["statute_deadline_at"] == STATUTE_DEADLINE
        assert fixtures.read_licensee(client, world["sam"]["id"])["discipline_status"] == (
            "UNDER_INVESTIGATION"
        )
