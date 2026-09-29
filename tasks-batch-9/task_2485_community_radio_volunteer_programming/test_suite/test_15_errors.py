"""Error codes reachable only on their own path, each isolated from its neighbours.

Every case here is built so that exactly one rule can fire: the role refusal is
handed an otherwise perfect payload, the self-vote bar is reached only after the
seat check has been satisfied, and the attempt cap is reached at a clock where the
cooling-off window has provably elapsed.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    DEVELOPMENT_HEADERS,
    DIRECTOR_HEADERS,
    OFFICER_ONE,
    TRAINER_HEADERS,
    api_client,
    factories,
    fixtures,
    make_committee_member_headers,
    make_compliance_officer_headers,
)

CLOCK = "2026-08-01T00:00:00Z"
INCIDENT_AT = "2026-07-30T14:00:00Z"
SECOND_ATTEMPT_AT = "2026-08-15T00:00:00Z"
THIRD_ATTEMPT_AT = "2026-08-29T00:00:00Z"
FOURTH_REQUEST_AT = "2026-09-12T00:00:00Z"


def _proposal_in_committee():
    """One certified author's proposal carried to `IN_COMMITTEE` with three seats
    filled and no ballot yet on file."""
    fixtures.set_clock(CLOCK)
    host = fixtures.create_certified_host()
    members = fixtures.create_committee_members(count=3)
    chain = fixtures.open_review_chain(host["id"], members)
    return {"host_id": host["id"], "members": members, "proposal_id": chain["proposal_id"]}


class TestRoleRefusal:
    def test_a_director_cannot_enrol_even_with_a_perfect_payload(self):
        """The role check runs before any field of the body is looked at.

        Enrolment is authorised for the `TrainingCoordinator` alone, and "a request
        whose `X-User-Role` is not among the roles authorised for the endpoint it
        addresses" is "rejected with `ERR_UNAUTHORIZED` (HTTP 403). This check is the
        first thing any endpoint does".

        Design: Corner/errors/err_unauthorized_when_a_director_tries_to_enrol_a_volunteer
        """
        fixtures.set_clock(CLOCK)

        validate_error(
            api_client.create_volunteer(
                factories.create_volunteer_payload(
                    legal_name="Ada Reyes",
                    email="ada@krcr.example",
                    role_track="PROGRAMMER",
                    seniority_start_date="2024-08-01",
                ),
                DIRECTOR_HEADERS,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        _, meta = validate_paginated(api_client.list_volunteers(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0


class TestBallotRefusals:
    def test_a_criterion_score_of_six_is_outside_the_scoring_domain(self):
        """The numeric domain is checked before the ballot is ever written.

        The three criterion scores are "each an integer from 1 through 5 inclusive",
        so a six is a structural failure and is "rejected with `ERR_VALIDATION`
        (HTTP 400)".

        Design: Corner/errors/err_validation_when_a_ballot_score_leaves_the_one_to_five_domain
        """
        setup = _proposal_in_committee()
        caster = setup["members"][0]["id"]

        validate_error(
            api_client.cast_vote(
                setup["proposal_id"],
                factories.cast_vote_payload(
                    caster,
                    format_fit_score=6,
                    diversity_score=4,
                    quality_score=4,
                    recommendation="APPROVE",
                ),
                make_committee_member_headers(caster),
            ),
            "ERR_VALIDATION",
            400,
        )

        _, meta = validate_paginated(api_client.list_committee_votes(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0

    def test_a_second_ballot_from_the_same_member_in_the_same_round_is_refused(self):
        """Uniqueness is scoped to the round, and the first ballot stands unchanged.

        "Each seated member then casts exactly one ballot", and "a second ballot from
        the same member in the same round answers `ERR_DUPLICATE_VOTE`". Ballots are
        "readable individually but never amendable", so the recommendation on file
        cannot be overwritten by the retry.

        Design: Corner/errors/err_duplicate_vote_on_a_second_ballot_in_the_same_round
        """
        setup = _proposal_in_committee()
        caster = setup["members"][0]["id"]
        fixtures.cast_ballot(setup["proposal_id"], caster, recommendation="APPROVE")

        validate_error(
            api_client.cast_vote(
                setup["proposal_id"],
                factories.cast_vote_payload(
                    caster,
                    format_fit_score=2,
                    diversity_score=2,
                    quality_score=2,
                    recommendation="DECLINE",
                ),
                make_committee_member_headers(caster),
            ),
            "ERR_DUPLICATE_VOTE",
            409,
        )

        rows, meta = validate_paginated(api_client.list_committee_votes(DIRECTOR_HEADERS))
        assert meta["total_count"] == 1
        assert rows[0]["recommendation"] == "APPROVE"

    def test_a_seated_author_still_cannot_score_their_own_show(self):
        """The seat check passes, so only the segregation rule can refuse the ballot.

        Amending a roster entry "lets the `TrainingCoordinator` or the
        `ProgramDirector` change `legal_name`, `email` and `committee_seat`", so the
        author genuinely holds a seat and cannot answer `ERR_NOT_COMMITTEE_MEMBER`.
        "a `member_volunteer_id` equal to the proposal's `proposer_volunteer_id`
        answers `ERR_SELF_VOTE_FORBIDDEN`, because the station's
        segregation-of-duties policy forbids a member from scoring their own show".

        Design: Corner/errors/err_self_vote_forbidden_when_the_author_also_holds_a_seat
        """
        setup = _proposal_in_committee()
        seated_author = validate_success(
            api_client.update_volunteer(
                setup["host_id"], {"committee_seat": True}, TRAINER_HEADERS
            ),
            200,
        )
        assert seated_author["committee_seat"] is True

        validate_error(
            api_client.cast_vote(
                setup["proposal_id"],
                factories.cast_vote_payload(
                    setup["host_id"],
                    format_fit_score=5,
                    diversity_score=5,
                    quality_score=5,
                    recommendation="APPROVE",
                ),
                make_committee_member_headers(setup["host_id"]),
            ),
            "ERR_SELF_VOTE_FORBIDDEN",
            403,
        )

        _, meta = validate_paginated(api_client.list_committee_votes(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0


class TestPolymorphicTargetRefusal:
    def test_a_volunteer_conflict_without_a_respondent_is_refused(self):
        """Which pointer is mandatory depends on the category being filed.

        "A `respondent_volunteer_id` is required for `VOLUNTEER_CONFLICT`, which is
        the one category directed at a person rather than at a show. Any of these
        omissions is refused with `ERR_INCIDENT_TARGET_REQUIRED`."

        Design: Corner/errors/err_incident_target_required_when_the_category_names_no_target
        """
        fixtures.set_clock(CLOCK)

        validate_error(
            api_client.create_compliance_incident(
                factories.create_incident_payload(
                    "VOLUNTEER_CONFLICT",
                    "MINOR",
                    INCIDENT_AT,
                    complainant_note="Dispute reported with no respondent named.",
                ),
                make_compliance_officer_headers(OFFICER_ONE),
            ),
            "ERR_INCIDENT_TARGET_REQUIRED",
            422,
        )

        _, meta = validate_paginated(api_client.list_compliance_incidents(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0


class TestFulfilmentRefusal:
    def test_a_waived_pledge_has_no_unit_to_ship(self):
        """The donor declined the gift, so the ship has nothing reserved to send.

        "`wants_premium` false leaves `premium_item_id` null, sets `premium_status`
        `WAIVED`, and makes `tax_deductible_cents` the full `amount_cents`."
        "`SHIP` requires the pledge's `premium_status` to be `RESERVED` — otherwise
        `ERR_PREMIUM_NOT_RESERVED` — and the `payment_status` to be `PAID`", and the
        pledge here is deliberately settled first so `ERR_PLEDGE_NOT_PAID` cannot be
        the answer. A refused ship moves no unit.

        Design: Corner/errors/err_premium_not_reserved_when_shipping_a_waived_pledge
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

        waived = validate_success(
            api_client.create_pledge(
                factories.create_pledge_payload(
                    drive["id"],
                    donor_name="Jo Farrow",
                    amount_cents=6000,
                    wants_premium=False,
                ),
                DEVELOPMENT_HEADERS,
            ),
            201,
        )
        assert waived["premium_status"] == "WAIVED"
        assert waived["premium_item_id"] is None
        assert waived["tax_deductible_cents"] == 6000

        paid = fixtures.settle_pledge(waived["id"], outcome="PAID")
        assert paid["payment_status"] == "PAID"

        validate_error(
            api_client.fulfill_pledge_premium(
                waived["id"],
                factories.premium_fulfillment_payload(action="SHIP"),
                DEVELOPMENT_HEADERS,
            ),
            "ERR_PREMIUM_NOT_RESERVED",
            409,
        )

        stock = validate_success(
            api_client.get_premium_item(mug["id"], DEVELOPMENT_HEADERS), 200
        )
        assert stock["reserved_qty"] == 0
        assert stock["shipped_qty"] == 0
        assert stock["on_hand_qty"] == 2


class TestAttemptCap:
    def test_a_fourth_attempt_is_refused_once_three_have_been_graded(self):
        """The cap bites at a clock where the cooling-off window has already elapsed.

        "the station caps attempts at three: a record whose `attempt_count` has
        reached 3 is refused with `ERR_MAX_ATTEMPTS_REACHED` and is permanently stuck
        on `FAILED`. Because the cooling-off check is evaluated before the cap, a
        record that is both exhausted and inside its window answers
        `ERR_RETAKE_TOO_SOON`." Each retake here is taken a full fourteen days after
        the previous attempt, so the window is satisfied and only the cap can fire.
        "anything below 80 fails", and on a failure "`attempt_count` rises by 1".

        Design: Corner/errors/err_max_attempts_reached_after_three_graded_failures
        """
        fixtures.set_clock(CLOCK)
        volunteer = fixtures.create_volunteer()
        record = fixtures.add_certification(volunteer["id"], "BOARD_OPERATION", 70)
        assert record["status"] == "FAILED"
        assert record["attempt_count"] == 1

        fixtures.set_clock(SECOND_ATTEMPT_AT)
        validate_success(
            api_client.retake_certification(record["id"], TRAINER_HEADERS), 200
        )
        second = validate_success(
            api_client.grade_certification(
                record["id"],
                factories.grade_certification_payload(exam_score=72),
                TRAINER_HEADERS,
            ),
            200,
        )
        assert second["status"] == "FAILED"
        assert second["attempt_count"] == 2

        fixtures.set_clock(THIRD_ATTEMPT_AT)
        validate_success(
            api_client.retake_certification(record["id"], TRAINER_HEADERS), 200
        )
        third = validate_success(
            api_client.grade_certification(
                record["id"],
                factories.grade_certification_payload(exam_score=75),
                TRAINER_HEADERS,
            ),
            200,
        )
        assert third["status"] == "FAILED"
        assert third["attempt_count"] == 3

        fixtures.set_clock(FOURTH_REQUEST_AT)
        validate_error(
            api_client.retake_certification(record["id"], TRAINER_HEADERS),
            "ERR_MAX_ATTEMPTS_REACHED",
            409,
        )

        stored = validate_success(
            api_client.get_certification(record["id"], TRAINER_HEADERS), 200
        )
        assert stored["status"] == "FAILED"
        assert stored["attempt_count"] == 3
