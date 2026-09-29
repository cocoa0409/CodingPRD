"""Declared transitions, refused transitions and the edges of a resting state.

Certification records carry the only cycle in the specification, proposals carry
a sink with no outgoing edge at all, drives are strictly linear, and a pledge runs
two independent dimensions side by side. Each case here drives one edge and then
reads the record back, because a rejected transition must leave the row exactly
where it stood.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    DEVELOPMENT_HEADERS,
    DIRECTOR_HEADERS,
    OFFICER_ONE,
    OFFICER_TWO,
    TRAINER_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_volunteer_headers,
)

CLOCK = "2026-08-01T00:00:00Z"
CERT_EXPIRY = "2028-08-01T00:00:00Z"
COOLING_OFF_ELAPSED = "2026-08-15T00:00:00Z"
ONE_DAY_SHORT = "2026-08-14T00:00:00Z"
INCIDENT_AT = "2026-07-30T14:00:00Z"
SHIFT_START = "2026-08-02T18:00:00Z"
SHIFT_END = "2026-08-02T21:00:00Z"


def _volunteer_with_a_failed_board_record():
    """One roster row holding a single `FAILED` record graded at 70, which is the
    only source state the retake edge accepts."""
    fixtures.set_clock(CLOCK)
    volunteer = fixtures.create_volunteer()
    record = fixtures.add_certification(volunteer["id"], "BOARD_OPERATION", 70)
    assert record["status"] == "FAILED"
    assert record["attempt_count"] == 1
    assert record["issued_on"] is None
    assert record["expires_on"] is None
    return {"volunteer_id": volunteer["id"], "certification_id": record["id"]}


def _certified_author_with_a_draft():
    """A certified proposer holding one draft, so both of the submit conditions
    other than the state check are already satisfied."""
    fixtures.set_clock(CLOCK)
    host = fixtures.create_certified_host()
    proposal = fixtures.create_proposal(host["id"])
    return {"host_id": host["id"], "proposal_id": proposal["id"]}


class TestCertificationCycle:
    def test_a_record_opened_ungraded_rests_on_pending_exam_and_is_graded_later(self):
        """The two-step route stops on `PENDING_EXAM` before the score arrives.

        "A record opens on `status` `PENDING_EXAM` with `attempt_count` 0, a null
        `exam_score`, and null `issued_on`, `expires_on`, `last_attempt_at` and
        `revocation_reason`." Grading it later, "as a separate grading of a record
        sitting on `PENDING_EXAM`", moves it "`PENDING_EXAM → PASSED`" and stamps
        `issued_on`, `expires_on`, `last_attempt_at` and `attempt_count`. "The very
        first certification record opened for a volunteer moves that volunteer from
        `PROSPECT` to `IN_TRAINING`."

        Design: Corner/state_machines/certification_pending_exam_to_passed_is_a_valid_transition
        """
        fixtures.set_clock(CLOCK)
        volunteer = fixtures.create_volunteer()

        opened = fixtures.add_certification(volunteer["id"], "BOARD_OPERATION")
        assert opened["status"] == "PENDING_EXAM"
        assert opened["attempt_count"] == 0
        assert opened["exam_score"] is None
        assert opened["issued_on"] is None
        assert opened["expires_on"] is None
        assert opened["last_attempt_at"] is None

        graded = validate_success(
            api_client.grade_certification(
                opened["id"], factories.grade_certification_payload(exam_score=88), TRAINER_HEADERS
            ),
            200,
        )
        assert graded["status"] == "PASSED"
        assert graded["attempt_count"] == 1
        assertions.assert_instant_equals(graded["last_attempt_at"], CLOCK, "last_attempt_at")
        assertions.assert_instant_equals(graded["issued_on"], CLOCK, "issued_on")
        assertions.assert_instant_equals(graded["expires_on"], CERT_EXPIRY, "expires_on")
        assertions.assert_certification(graded)

        holder = validate_success(
            api_client.get_volunteer(volunteer["id"], TRAINER_HEADERS), 200
        )
        assert holder["status"] == "IN_TRAINING"
        assert holder["current_certification_count"] == 1

    def test_the_retake_reopens_the_record_and_keeps_the_attempt_counter(self):
        """The cycle re-enters `PENDING_EXAM` with the counter deliberately intact.

        "A failed record can be reopened for another attempt, moving `FAILED →
        PENDING_EXAM`, which clears `exam_score` back to null, leaves
        `attempt_count` exactly as it stands and advances the record's `version` by
        1." The clock "must have reached at least fourteen days past
        `last_attempt_at`", which it has.

        Design: Corner/state_machines/certification_failed_to_pending_exam_reopens_the_cycle
        """
        setup = _volunteer_with_a_failed_board_record()
        fixtures.set_clock(COOLING_OFF_ELAPSED)

        reopened = validate_success(
            api_client.retake_certification(setup["certification_id"], TRAINER_HEADERS), 200
        )
        assert reopened["status"] == "PENDING_EXAM"
        assert reopened["exam_score"] is None
        assert reopened["attempt_count"] == 1
        assert reopened["version"] > 1

        stored = validate_success(
            api_client.get_certification(setup["certification_id"], TRAINER_HEADERS), 200
        )
        assert stored["status"] == "PENDING_EXAM"
        assert stored["attempt_count"] == 1
        assert stored["issued_on"] is None

    def test_a_retake_one_day_short_of_the_window_is_refused(self):
        """Thirteen days is not fourteen, and the record does not move.

        "The station imposes a **fourteen-day cooling-off window**: the clock must
        have reached at least fourteen days past `last_attempt_at`, and an earlier
        request is refused with `ERR_RETAKE_TOO_SOON`."

        Design: Corner/state_machines/certification_retake_one_day_before_cooling_off_is_a_precondition_failure
        """
        setup = _volunteer_with_a_failed_board_record()
        fixtures.set_clock(ONE_DAY_SHORT)

        validate_error(
            api_client.retake_certification(setup["certification_id"], TRAINER_HEADERS),
            "ERR_RETAKE_TOO_SOON",
            409,
        )

        stored = validate_success(
            api_client.get_certification(setup["certification_id"], TRAINER_HEADERS), 200
        )
        assert stored["status"] == "FAILED"
        assert stored["exam_score"] == 70

    def test_a_passed_record_refuses_a_second_grading(self):
        """`PASSED` declares no grading edge, so the score on file survives.

        "Grading a record that is not on `PENDING_EXAM` — one already `PASSED`,
        `FAILED`, `EXPIRED` or `REVOKED` — is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/certification_passed_rejects_further_exam_results
        """
        fixtures.set_clock(CLOCK)
        volunteer = fixtures.create_volunteer()
        passed = fixtures.add_certification(volunteer["id"], "BOARD_OPERATION", 88)
        assert passed["status"] == "PASSED"

        validate_error(
            api_client.grade_certification(
                passed["id"], factories.grade_certification_payload(exam_score=95), TRAINER_HEADERS
            ),
            "ERR_INVALID_STATE",
            409,
        )

        stored = validate_success(
            api_client.get_certification(passed["id"], TRAINER_HEADERS), 200
        )
        assert stored["exam_score"] == 88
        assert stored["attempt_count"] == 1


class TestProposalStates:
    def test_a_fresh_proposal_rests_on_draft_with_no_tally_recorded(self):
        """Nothing has been scored yet and the record says so.

        "A fresh proposal sits on `status` `DRAFT` with `review_round` 1, a null
        `composite_score`, `decline_majority` false and a null `decided_at`." The
        draft "names its author in `proposer_volunteer_id`", and `version` "starts at
        1 on creation".

        Design: Corner/state_machines/proposal_initial_state_is_draft
        """
        fixtures.set_clock(CLOCK)
        host = fixtures.create_certified_host()

        drafted = validate_success(
            api_client.create_proposal(
                factories.create_proposal_payload(
                    host["id"],
                    title="Delta Blues Hour",
                    format_code="MUSIC",
                    language_code="EN",
                    requested_daypart="MIDDAY",
                    requested_duration_minutes=60,
                ),
                make_volunteer_headers(host["id"]),
            ),
            201,
        )

        assert drafted["status"] == "DRAFT"
        assert drafted["review_round"] == 1
        assert drafted["composite_score"] is None
        assert drafted["decline_majority"] is False
        assert drafted["decided_at"] is None
        assert drafted["proposer_volunteer_id"] == host["id"]
        assert drafted["version"] == 1
        assertions.assert_proposal(drafted)

    def test_a_withdrawn_proposal_cannot_be_submitted(self):
        """The rightful, certified author is still turned away on the state.

        `WITHDRAWN` is "always by the author alone, and always terminal", and a
        transition "not declared for the record's current state answers
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/proposal_withdrawn_rejects_a_later_submit
        """
        setup = _certified_author_with_a_draft()
        author = make_volunteer_headers(setup["host_id"])

        withdrawn = validate_success(
            api_client.withdraw_proposal(setup["proposal_id"], author), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"

        validate_error(
            api_client.submit_proposal(setup["proposal_id"], author),
            "ERR_INVALID_STATE",
            409,
        )

        stored = validate_success(
            api_client.get_proposal(setup["proposal_id"], DIRECTOR_HEADERS), 200
        )
        assert stored["status"] == "WITHDRAWN"

    def test_the_second_open_review_is_refused_and_writes_nothing(self):
        """A replay of a consumed transition is a refusal, not a silent no-op.

        Opening review takes the proposal "`SUBMITTED → IN_COMMITTEE`", so a second
        call finds a source state that no longer declares the edge and answers
        `ERR_INVALID_STATE`. Because `version` "increases by exactly 1 on every
        mutation of the row", a refused replay leaves it where the first call left
        it.

        Design: Corner/state_machines/proposal_open_review_is_not_idempotent_and_rejects_the_second_call
        """
        fixtures.set_clock(CLOCK)
        host = fixtures.create_certified_host()
        fixtures.create_committee_members(count=3)
        proposal = fixtures.create_proposal(host["id"])
        fixtures.submit_proposal(proposal["id"], host["id"])

        opened = fixtures.open_review(proposal["id"])
        assert opened["status"] == "IN_COMMITTEE"
        version_after_opening = opened["version"]

        validate_error(
            api_client.open_proposal_review(proposal["id"], DIRECTOR_HEADERS),
            "ERR_INVALID_STATE",
            409,
        )

        stored = validate_success(
            api_client.get_proposal(proposal["id"], DIRECTOR_HEADERS), 200
        )
        assert stored["status"] == "IN_COMMITTEE"
        assert stored["version"] == version_after_opening


class TestDriveStates:
    def test_a_planned_drive_cannot_be_closed_without_being_activated(self):
        """The middle state of a linear machine cannot be skipped.

        "A new drive sits on `status` `PLANNED`", "Activation moves it `PLANNED →
        ACTIVE`" and "Closing the drive itself moves it `ACTIVE → CLOSED`", so a
        close aimed at `PLANNED` is a transition "not declared for the record's
        current state" and answers `ERR_INVALID_STATE`.

        Design: Corner/state_machines/drive_close_from_planned_is_an_invalid_transition
        """
        fixtures.set_clock(CLOCK)
        drive = fixtures.create_drive(phone_line_count=2)
        assert drive["status"] == "PLANNED"

        validate_error(
            api_client.close_membership_drive(drive["id"], DEVELOPMENT_HEADERS),
            "ERR_INVALID_STATE",
            409,
        )

        stored = fixtures.read_drive(drive["id"])
        assert stored["status"] == "PLANNED"
        assert stored["version"] == 1


class TestIncidentAdjudicationFork:
    def test_an_unfounded_finding_charges_nothing_yet_records_the_officer(self):
        """The frozen figure stays on the row and is simply never charged.

        "The resulting `penalty_points` are written to the incident at creation and
        never recalculated", and for `VOLUNTEER_CONFLICT` the base "is likewise 1, 2
        and 4". "No other category is ever a safe-harbour violation." The officer
        "rules with a `finding` of `SUBSTANTIATED` or `UNFOUNDED`, and either way the
        officer's `X-User-ID` is written to `adjudicated_by_user_id`", while "An
        `UNFOUNDED` finding moves the incident `OPEN → UNFOUNDED`, charges nothing at
        all and is terminal." A `sanction` "defaults to `NONE`", and `NONE` "does
        nothing".

        Design: Corner/state_machines/incident_unfounded_finding_charges_nothing_but_still_stamps_the_officer
        """
        fixtures.set_clock(CLOCK)
        volunteer = fixtures.create_volunteer()

        filed = validate_success(
            api_client.create_compliance_incident(
                factories.create_incident_payload(
                    "VOLUNTEER_CONFLICT",
                    "MINOR",
                    INCIDENT_AT,
                    complainant_note="Two hosts booked the same production room.",
                    respondent_volunteer_id=volunteer["id"],
                ),
                make_compliance_officer_headers(OFFICER_ONE),
            ),
            201,
        )
        assert filed["status"] == "OPEN"
        assert filed["penalty_points"] == 1
        assert filed["safe_harbor_violation"] is False
        assert filed["adjudicated_by_user_id"] is None

        ruled = validate_success(
            api_client.adjudicate_compliance_incident(
                filed["id"],
                factories.adjudicate_incident_payload(finding="UNFOUNDED"),
                make_compliance_officer_headers(OFFICER_TWO),
            ),
            200,
        )
        assert ruled["status"] == "UNFOUNDED"
        assert ruled["penalty_points"] == 1
        assert ruled["adjudicated_by_user_id"] == OFFICER_TWO
        assert ruled["sanction"] == "NONE"
        assertions.assert_compliance_incident(ruled)

        respondent = validate_success(
            api_client.get_volunteer(volunteer["id"], DIRECTOR_HEADERS), 200
        )
        assert respondent["strike_count"] == 0
        assert respondent["status"] == "PROSPECT"


class TestPhoneBankStrikeBubblesUp:
    def test_closing_a_shift_as_a_no_show_strikes_the_volunteer(self):
        """A child row's close rewrites two fields on the roster entry.

        "`NO_SHOW` moves the shift `SCHEDULED → NO_SHOW` and is a disciplinary
        matter: it raises the volunteer's `strike_count` by 1, which lowers their
        `seniority_score` by 15 points through the strike term of §3.2, and moves
        them `CERTIFIED → PROBATION` when the new count reaches 2." The score is "the
        service term plus the certification term plus the performance term, minus the
        strike term", so forty-three whole months of service with no live
        certification and one strike is `28.00`.

        Design: Corner/state_machines/phone_bank_no_show_bubbles_a_strike_up_to_the_volunteer
        """
        fixtures.set_clock(CLOCK)
        fern = fixtures.create_volunteer(
            legal_name="Fern Duval",
            email="fern@krcr.example",
            role_track="DEVELOPMENT",
            seniority_start_date="2023-01-01",
        )
        drive = fixtures.create_active_drive(phone_line_count=2)
        shift = fixtures.create_shift(drive["id"], fern["id"], SHIFT_START, SHIFT_END)
        assert shift["status"] == "SCHEDULED"

        closed = validate_success(
            api_client.close_phone_bank_shift(
                shift["id"], factories.close_shift_payload(outcome="NO_SHOW"), DEVELOPMENT_HEADERS
            ),
            200,
        )
        assert closed["status"] == "NO_SHOW"

        struck = validate_success(
            api_client.get_volunteer(fern["id"], DEVELOPMENT_HEADERS), 200
        )
        assert struck["strike_count"] == 1
        assert struck["continuous_service_months"] == 43
        assertions.assert_two_decimals_equal(struck["seniority_score"], 28.00, "seniority_score")
        assert struck["status"] == "PROSPECT"


class TestPledgeParallelDimensions:
    def test_the_payment_and_premium_dimensions_move_one_at_a_time(self):
        """Settling the money leaves the gift alone, and shipping the gift leaves
        the money alone.

        "A new pledge sits on `payment_status` `PENDING` and `premium_status` as the
        allocation decides", the deductible being "the `amount_cents` less that
        premium's `fair_market_value_cents`". "An `outcome` of `PAID` moves the pledge
        `PENDING → PAID`", and a ship "lowers the premium's `reserved_qty` by 1,
        lowers its `on_hand_qty` by 1 and raises its `shipped_qty` by 1". A premium
        is `AVAILABLE` "while `on_hand_qty` minus `reserved_qty` is greater than 0".

        Design: Corner/state_machines/pledge_payment_and_premium_dimensions_advance_independently
        """
        fixtures.set_clock(CLOCK)
        mug = fixtures.create_premium(
            sku="MUG-01",
            name="Station mug",
            tier_threshold_cents=5000,
            fair_market_value_cents=1500,
            units_received_qty=2,
        )
        drive = fixtures.create_active_drive(phone_line_count=2)

        pledge = validate_success(
            api_client.create_pledge(
                factories.create_pledge_payload(
                    drive["id"],
                    donor_name="Iris Vance",
                    amount_cents=6000,
                    wants_premium=True,
                ),
                DEVELOPMENT_HEADERS,
            ),
            201,
        )
        assert pledge["payment_status"] == "PENDING"
        assert pledge["premium_status"] == "RESERVED"
        assert pledge["premium_item_id"] == mug["id"]
        assert pledge["tax_deductible_cents"] == 4500
        assertions.assert_pledge(pledge)

        paid = validate_success(
            api_client.settle_pledge(
                pledge["id"], factories.pledge_payment_payload(outcome="PAID"), DEVELOPMENT_HEADERS
            ),
            200,
        )
        assert paid["payment_status"] == "PAID"
        assert paid["premium_status"] == "RESERVED"

        shipped = validate_success(
            api_client.fulfill_pledge_premium(
                pledge["id"], factories.premium_fulfillment_payload(action="SHIP"),
                DEVELOPMENT_HEADERS,
            ),
            200,
        )
        assert shipped["premium_status"] == "SHIPPED"
        assert shipped["payment_status"] == "PAID"

        stock = fixtures.read_premium(mug["id"])
        assert stock["reserved_qty"] == 0
        assert stock["shipped_qty"] == 1
        assert stock["on_hand_qty"] == 1
        assert stock["status"] == "AVAILABLE"
        assertions.assert_premium_unit_conservation(stock)
