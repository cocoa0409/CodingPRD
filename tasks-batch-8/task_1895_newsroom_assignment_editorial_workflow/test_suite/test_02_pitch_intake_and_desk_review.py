"""Pitch intake, the SUBMITTED <-> DESK_REVIEW rework cycle, withdrawal, and
greenlight FK wiring."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_pitch,
    assert_story,
    create_greenlit_story,
    create_pitch_payload,
    get_success_data,
    greenlight,
    make_reporter_headers,
    make_staff,
    setup_newsroom,
    submit_pitch,
    validate_error,
    validate_paginated,
)

ND = TEST_USERS["news_director_headers"]


class TestInitialStates:
    def test_pitch_and_story_initial_state(self, api):
        """PRD §3.2: "The server records the submitter in `submitting_staff_id`
        from `X-User-ID`, and the pitch lands in `SUBMITTED` status with
        `rework_round` at 0."
        PRD §3.2: "Greenlighting is the generative exit: the editor supplies a
        `story_type` of `PRINT`, `DIGITAL`, or `BROADCAST`, the pitch moves to
        `GREENLIT`, and the system spawns a new story in `DRAFT` status whose
        `pitch_id` points back to the pitch, whose `desk` is copied from the
        pitch, whose `author_staff_id` is the pitch's submitter, and whose
        `word_count` is 0, `embargo_until` and `slot_id` null, and
        `correction_count` 0."

        Design: Corner/state_machines/story_initial_state_draft
        """
        ctx = setup_newsroom()
        pitch = submit_pitch(ctx, title="IS")
        assert_pitch(pitch)
        assert pitch["status"] == "SUBMITTED"
        assert pitch["rework_round"] == 0
        assert pitch["submitting_staff_id"] == ctx["reporter"]["id"]

        pitch = greenlight(ctx, pitch["id"], story_type="PRINT")
        story = get_success_data(
            api.get_story(pitch["greenlit_story_id"], ND))
        assert_story(story)
        assert story["status"] == "DRAFT"
        assert story["word_count"] == 0
        assert story["correction_count"] == 0
        assert story["slot_id"] is None
        assert story["embargo_until"] is None
        assert story["pitch_id"] == pitch["id"]
        assert story["author_staff_id"] == ctx["reporter"]["id"]


class TestReworkCycle:
    def test_three_returns_traverse_the_cycle(self, api):
        """PRD §3.2: "Returning the pitch sends it back to `SUBMITTED` for
        rework and increments `rework_round`; the desk will not return a pitch
        forever — once `rework_round` has reached 3, a further return is
        rejected with `ERR_PITCH_REWORK_LIMIT` (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/pitch_rework_cycle
        """
        ctx = setup_newsroom()
        pitch = submit_pitch(ctx, title="Zoo expansion")
        rounds = []
        for _ in range(3):
            get_success_data(
                api.start_pitch_review(pitch["id"], ctx["desk_headers"]))
            returned = get_success_data(
                api.return_pitch(pitch["id"], ctx["desk_headers"]))
            rounds.append(returned["rework_round"])
            assert returned["status"] == "SUBMITTED"
        assert rounds == [1, 2, 3], \
            "each return increments rework_round by one across the cycle"

    def test_fourth_return_rejected_at_rework_limit(self, api):
        """PRD §3.2: "Returning the pitch sends it back to `SUBMITTED` for
        rework and increments `rework_round`; the desk will not return a pitch
        forever — once `rework_round` has reached 3, a further return is
        rejected with `ERR_PITCH_REWORK_LIMIT` (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/pitch_rework_cycle
        """
        ctx = setup_newsroom()
        pitch = submit_pitch(ctx, title="Zoo expansion")
        for _ in range(3):
            get_success_data(
                api.start_pitch_review(pitch["id"], ctx["desk_headers"]))
            get_success_data(
                api.return_pitch(pitch["id"], ctx["desk_headers"]))
        get_success_data(
            api.start_pitch_review(pitch["id"], ctx["desk_headers"]))
        resp = api.return_pitch(pitch["id"], ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_PITCH_REWORK_LIMIT)

        final = get_success_data(api.get_pitch(pitch["id"], ND))
        assert final["status"] == "DESK_REVIEW", \
            "the rejected return changed nothing"
        assert final["rework_round"] == 3


class TestWithdrawal:
    def test_withdraw_from_greenlit_rejected(self, api):
        """PRD §3.2: "From either `SUBMITTED` or `DESK_REVIEW`, the pitch's
        owner may withdraw it to `WITHDRAWN`; the attempt is rejected with
        `ERR_FORBIDDEN` unless `X-User-ID` equals the pitch's
        `submitting_staff_id`, and with `ERR_INVALID_STATE` once the pitch has
        reached any other state."

        Design: Corner/state_machines/pitch_withdraw_from_greenlit_rejected
        """
        ctx = setup_newsroom()
        _pitch, _story_id = create_greenlit_story(ctx)
        resp = api.withdraw_pitch(_pitch["id"], ctx["reporter_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_withdraw_by_non_owner_forbidden(self, api):
        """PRD §3.2: "From either `SUBMITTED` or `DESK_REVIEW`, the pitch's
        owner may withdraw it to `WITHDRAWN`; the attempt is rejected with
        `ERR_FORBIDDEN` unless `X-User-ID` equals the pitch's
        `submitting_staff_id`, and with `ERR_INVALID_STATE` once the pitch has
        reached any other state."

        Design: Corner/validations/withdraw_by_non_owner_forbidden
        """
        ctx = setup_newsroom()
        pitch = submit_pitch(ctx, title="WO")
        other = make_staff("Rep Two WO", "REPORTER")
        other_h = make_reporter_headers(other["id"])
        resp = api.withdraw_pitch(pitch["id"], other_h)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_pitch(pitch["id"], ND))
        assert after["status"] == "SUBMITTED", "no drift on the forbidden call"


class TestDeskReviewTransitions:
    def test_start_review_from_rejected_rejected(self, api):
        """PRD §3.2: "Every transition out of a state the pitch is not in is
        rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/pitch_start_review_from_rejected_rejected
        """
        ctx = setup_newsroom()
        pitch = submit_pitch(ctx, title="TL")
        get_success_data(
            api.start_pitch_review(pitch["id"], ctx["desk_headers"]))
        get_success_data(api.reject_pitch(pitch["id"], ctx["desk_headers"]))
        resp = api.start_pitch_review(pitch["id"], ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_pitch(pitch["id"], ND))
        assert after["status"] == "REJECTED", "terminal state did not drift"

    def test_greenlight_as_reporter_forbidden(self, api):
        """PRD §2.1: "A request whose role is not listed among an endpoint's
        permitted roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.2: "An `AssignmentEditor` works the queue."

        Design: Corner/validations/greenlight_as_reporter_forbidden
        """
        ctx = setup_newsroom()
        pitch = submit_pitch(ctx, title="GF")
        get_success_data(
            api.start_pitch_review(pitch["id"], ctx["desk_headers"]))
        # The pitch is in DESK_REVIEW, so a permitted role would succeed; only
        # the role check can explain the rejection.
        resp = api.greenlight_pitch(pitch["id"], {"story_type": "PRINT"},
                                    ctx["reporter_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestPitchSchema:
    def test_pitch_create_invalid_enum_returns_400(self, api):
        """PRD §2.7: "3. Request-body schema — required fields present, types
        correct, and enum values inside their declared domains (`urgency`,
        `story_type`, `severity`, `review_type`, `verdict`, `variant`,
        `channel`, `role_capability`, `home_desk`, `employment_status`,
        `assignment_role`); failures yield `ERR_VALIDATION` (HTTP 400)."
        PRD §3.2: "an optional `urgency` of `STANDARD`, `URGENT`, or `BREAKING`
        defaults to `STANDARD`."

        Design: Corner/entities/pitch_create_invalid_enum_returns_400
        """
        ctx = setup_newsroom()
        payload = create_pitch_payload(title="Bad enum", urgency="MEGA")
        resp = api.create_pitch(payload, ctx["reporter_headers"])
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestGreenlightFkWiring:
    def test_greenlight_wires_both_directions(self, api):
        """PRD §3.2: "The pitch's `greenlit_story_id` is set to the new story —
        the reverse lookup of stories spawned from a pitch therefore returns at
        most one element — and the pitch's `version` increments."
        PRD §3.2: "The pitch list supports pagination and filtering by
        `status`, `desk`, `submitting_staff_id`, and `greenlit_story_id`."

        Design: Corner/entities/pitch_greenlight_fk_reverse
        """
        ctx = setup_newsroom()
        pitch, story_id = create_greenlit_story(ctx)
        assert pitch["greenlit_story_id"] == story_id

        pitches, meta = validate_paginated(api.list_pitches(
            ctx["desk_headers"], params={"greenlit_story_id": story_id}))
        assert meta["total_count"] == 1
        assert pitches[0]["id"] == pitch["id"], \
            "the filter reverse-reaches the pitch from the story id"

        stories, meta2 = validate_paginated(
            api.get_pitch_stories(pitch["id"], ctx["desk_headers"]))
        assert meta2["total_count"] == 1
        assert stories[0]["id"] == story_id
        assert stories[0]["pitch_id"] == pitch["id"]


class TestPitchListing:
    def test_pitches_list_pagination(self, api):
        """PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by `created_at` in ascending order."
        PRD §2.3: "Every list response carries `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/pitches_list_pagination
        """
        ctx = setup_newsroom()
        p1 = submit_pitch(ctx, title="Page one")
        p2 = submit_pitch(ctx, title="Page two", desk="BUSINESS")

        page1, meta1 = validate_paginated(api.list_pitches(
            ctx["desk_headers"], params={"limit": 1, "offset": 0}))
        page2, meta2 = validate_paginated(api.list_pitches(
            ctx["desk_headers"], params={"limit": 1, "offset": 1}))

        assert page1[0]["id"] == p1["id"], "created_at ASC: oldest first"
        assert page2[0]["id"] == p2["id"]
        assert meta1["total_count"] == 2 and meta1["has_more"] is True
        assert meta2["total_count"] == 2 and meta2["has_more"] is False
