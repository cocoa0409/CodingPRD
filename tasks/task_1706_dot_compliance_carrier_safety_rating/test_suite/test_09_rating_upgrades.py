"""Rating upgrade requests: eligibility gates, cooling-off, single-open
constraint, adjudication states, and the denial side effect."""
from test_helpers import (
    ApiErrorId,
    assert_timestamp_at,
    create_upgrade_request_payload,
    get_carrier,
    make_carrier,
    make_rated_carrier,
    make_upgrade_request,
    set_clock,
    setup_upgrade_conflict_case,
    validate_error,
    validate_success,
)


def _conditional_carrier_with_open_request(dot_number):
    """Carrier downgraded NONE -> CONDITIONAL (audit 0 acute / 2 critical);
    clock advanced past any cooling-off; one SUBMITTED upgrade request."""
    carrier = make_rated_carrier("CONDITIONAL", dot_number=dot_number)
    set_clock("2027-02-01T00:00:00Z")
    request = make_upgrade_request(carrier["id"], requested_rating="SATISFACTORY")
    return carrier, request


class TestUpgradeEligibility:
    def test_upgrade_rating_not_upgradable(self, api, manager_headers):
        """PRD §3.8: "Filing is rejected with `ERR_RATING_NOT_UPGRADABLE` when
        the carrier's current rating is `NONE` or `SATISFACTORY`, or when the
        requested rating does not rank strictly above the current one."
        PRD §3.8: the request carries "a `requested_rating` of `SATISFACTORY` or
        `CONDITIONAL`" — any other enum member fails request-shape validation
        with `ERR_INVALID_REQUEST` (PRD §2.6 stage 3, which precedes the
        cross-entity holds of stage 10).

        Design: Corner/validations/upgrade_rating_not_upgradable
        """
        carrier = make_carrier(dot_number="DOT-2310")
        assert carrier["safety_rating"] == "NONE"

        not_upgradable = api.create_upgrade_request(
            create_upgrade_request_payload(carrier["id"], requested_rating="SATISFACTORY"),
            manager_headers,
        )
        validate_error(not_upgradable, ApiErrorId.ERR_RATING_NOT_UPGRADABLE)

        bad_enum = api.create_upgrade_request(
            create_upgrade_request_payload(
                carrier["id"], requested_rating="UNSATISFACTORY"
            ),
            manager_headers,
        )
        validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST)

    def test_second_open_upgrade_request_rejected(self, api, manager_headers):
        """PRD §3.8: "Only one open request — one in `SUBMITTED` or
        `UNDER_REVIEW` — may exist per carrier at a time
        (`ERR_OPEN_UPGRADE_REQUEST_EXISTS`)."

        Design: Corner/validations/second_open_upgrade_request_rejected
        """
        carrier, _r1 = _conditional_carrier_with_open_request("DOT-2336")

        second = api.create_upgrade_request(
            create_upgrade_request_payload(
                carrier["id"], requested_rating="SATISFACTORY",
                justification_note="second",
            ),
            manager_headers,
        )
        validate_error(second, ApiErrorId.ERR_OPEN_UPGRADE_REQUEST_EXISTS)


class TestUpgradeAdjudication:
    def test_upgrade_decide_before_review_rejected(self, api, director_headers):
        """PRD §3.8: "Adjudication belongs to the `SafetyDirector`. Starting
        review moves `SUBMITTED` → `UNDER_REVIEW`; the decision takes an
        `outcome` of `APPROVED` or `DENIED` and requires `UNDER_REVIEW`. Either
        action from the wrong state — including a decision on an already
        `APPROVED` or `DENIED` request — is rejected with
        `ERR_UPGRADE_INVALID_STATE`."

        Design: Corner/validations/upgrade_decide_before_review_rejected
        """
        carrier, request = _conditional_carrier_with_open_request("DOT-2329")

        early = api.decide_upgrade(request["id"], {"outcome": "APPROVED"}, director_headers)
        validate_error(early, ApiErrorId.ERR_UPGRADE_INVALID_STATE)

        validate_success(api.start_review_upgrade(request["id"], director_headers), 200)
        validate_success(
            api.decide_upgrade(request["id"], {"outcome": "APPROVED"}, director_headers),
            200,
        )
        terminal = api.decide_upgrade(request["id"], {"outcome": "DENIED"}, director_headers)
        validate_error(terminal, ApiErrorId.ERR_UPGRADE_INVALID_STATE)

    def test_upgrade_denied_sets_cooling_off(self, api, director_headers):
        """PRD §3.8: "A denial sets `rating_cooling_off_until` to 90 days after
        the current clock, increments the carrier's `version`, and stamps
        `decided_at`."

        Design: Corner/state_machines/upgrade_denied_sets_cooling_off
        """
        carrier, request = _conditional_carrier_with_open_request("DOT-2111")
        validate_success(api.start_review_upgrade(request["id"], director_headers), 200)

        denied = validate_success(
            api.decide_upgrade(request["id"], {"outcome": "DENIED"}, director_headers),
            200,
        )
        assert denied["status"] == "DENIED"
        assert_timestamp_at(denied["decided_at"], "2027-02-01T00:00:00")

        after = get_carrier(carrier["id"])
        assert after["safety_rating"] == "CONDITIONAL"
        # 2027-02-01 + 90 days = 2027-05-02.
        assert str(after["rating_cooling_off_until"]).startswith("2027-05-02")


class TestCoolingOffVsOpenRequest:
    def test_cooling_off_beats_open_request_constraint(self, api, manager_headers):
        """PRD §2.6: "Every request is validated against the following stages,
        evaluated in the order given; a request that fails several checks
        receives the error from the earliest failing stage." — temporal gates
        (stage 8: `ERR_COOLING_OFF_ACTIVE`) precede uniqueness and limits
        (stage 9: `ERR_OPEN_UPGRADE_REQUEST_EXISTS`).
        PRD §3.8: "While the carrier's `rating_cooling_off_until` lies in the
        future of the clock, filing is rejected with `ERR_COOLING_OFF_ACTIVE`".

        Design: Difficulty/priority_pair_validation_conflict/conflict_temporal_beats_constraint_upgrade
        """
        env = setup_upgrade_conflict_case()
        # Clock is 2027-02-01; the second downgrade (CONDITIONAL ->
        # UNSATISFACTORY on 2027-02-01) re-armed cooling-off 180 days out, and
        # request R1 is still SUBMITTED.
        resp = api.create_upgrade_request(
            create_upgrade_request_payload(
                env["carrier"]["id"], requested_rating="SATISFACTORY",
                justification_note="Second attempt",
            ),
            manager_headers,
        )
        error = validate_error(resp, ApiErrorId.ERR_COOLING_OFF_ACTIVE)
        assert error["error_id"] != ApiErrorId.ERR_OPEN_UPGRADE_REQUEST_EXISTS

    def test_open_request_constraint_fires_once_cooling_off_elapsed(
        self, api, manager_headers
    ):
        """PRD §3.8: "Only one open request — one in `SUBMITTED` or
        `UNDER_REVIEW` — may exist per carrier at a time
        (`ERR_OPEN_UPGRADE_REQUEST_EXISTS`)." — with the clock advanced beyond
        `rating_cooling_off_until`, the temporal gate passes and the
        single-open-request limit is what fires.

        Design: Difficulty/priority_pair_validation_conflict/conflict_temporal_beats_constraint_upgrade
        """
        env = setup_upgrade_conflict_case()
        # 2027-02-01 + 180 days = 2027-07-31; move strictly past it.
        set_clock("2027-08-02T00:00:00Z")
        resp = api.create_upgrade_request(
            create_upgrade_request_payload(
                env["carrier"]["id"], requested_rating="SATISFACTORY",
                justification_note="Third attempt",
            ),
            manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_UPGRADE_REQUEST_EXISTS)
