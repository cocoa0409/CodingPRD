"""Script drafting, accuracy review, the revision cycle, and publication."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_script,
    assert_script_version,
    create_room,
    create_route,
    create_script,
    get_route,
    get_script,
    publish_script,
    submit_script,
    validate_error,
    validate_success,
)

CURATOR = TEST_USERS["curator_headers"]
FRONT_DESK = TEST_USERS["front_desk_staff_headers"]


def _room_and_route():
    room = create_room()
    route = create_route([room["id"]])
    return room, route


class TestScriptInitialState:

    def test_script_initial_state_draft(self):
        """PRD section 3.2: "A fresh draft sits in `DRAFT`, where it may be
        edited freely."
        PRD section 3.2: "Each draft is stamped with a `version_no` that is
        monotonic per route: the route's first script receives 1, and every
        later draft receives the next number, one more than the highest
        existing `version_no` on that route."

        Design: Corner/state_machines/script_initial_state_draft
        """
        _room, route = _room_and_route()
        resp = api_client.create_script_version(
            route["id"],
            {"content_text": "Draft", "curriculum_standards": []},
            CURATOR,
        )
        data = validate_success(resp, expected_status=201)
        assert_script_version(data)
        assert data["status"] == "DRAFT"
        assert data["version_no"] == 1, (
            f"the route's first script must receive version_no 1, "
            f"got {data['version_no']}"
        )


class TestScriptInvalidTransitions:

    def test_script_submit_from_in_review_rejected(self):
        """PRD section 3.2: "Submission moves a script from `DRAFT` to
        `IN_REVIEW` and is a `Curator` action; it increments the script's
        `version`."
        PRD section 2.9, tier 5: "the target resource must be in a state that
        offers the requested transition; generic violations yield
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/script_submit_from_in_review_rejected
        """
        _room, route = _room_and_route()
        script = create_script(route["id"])
        submit_script(script["id"])
        resp = api_client.submit_script_version(script["id"], CURATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_script(script["id"])
        assert after["status"] == "IN_REVIEW", (
            f"script must remain IN_REVIEW after a rejected re-submit, "
            f"got {after['status']}"
        )

    def test_publish_from_in_review_returns_invalid_state(self):
        """PRD section 3.2: "Publishing an `APPROVED` script must carry
        `expected_route_version` per the optimistic-concurrency rule of
        §2.4; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)
        and nothing changes."
        PRD section 2.9, tier 5: "the target resource must be in a state that
        offers the requested transition; generic violations yield
        `ERR_INVALID_STATE`".

        Design: Corner/errors/publish_from_in_review_returns_invalid_state
        """
        _room, route = _room_and_route()
        script = create_script(route["id"])
        submit_script(script["id"])
        resp = api_client.publish_script_version(
            script["id"], {"expected_route_version": route["version"]},
            TEST_USERS["museum_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestScriptRevisionCycle:
    """The IN_REVIEW -> DRAFT loop is cyclic and does not mint version_no."""

    def test_revision_returns_to_draft_without_new_version_no(self):
        """PRD section 3.2: "With `decision` REQUEST_REVISION, no score is
        required; the script returns to `DRAFT` for another editing cycle
        with its `version_no` unchanged, and this draft–review–revision loop
        may repeat indefinitely."

        Design: Difficulty/non_linear_state_machine/script_version_revision_cycle
        """
        _room, route = _room_and_route()
        script = create_script(route["id"], content_text="Draft one")
        assert script["status"] == "DRAFT"
        assert script["version_no"] == 1
        submitted = submit_script(script["id"])
        assert submitted["status"] == "IN_REVIEW"
        resp = api_client.review_script_version(
            script["id"],
            {"decision": "REQUEST_REVISION",
             "reviewer_notes": "verify dates"},
            CURATOR,
        )
        data = validate_success(resp)
        assert data["status"] == "DRAFT", (
            f"REQUEST_REVISION must return the script to DRAFT, "
            f"got {data['status']}"
        )
        assert data["version_no"] == 1, (
            f"the revision loop must not mint a new version_no, "
            f"got {data['version_no']}"
        )

    def test_revision_cycle_completes_to_published(self):
        """PRD section 3.2: "With `decision` APPROVE, the `accuracy_score`
        must be provided and must be at least 80 — anything lower, or a
        missing score, is rejected with `ERR_REVIEW_SCORE_TOO_LOW`
        (HTTP 422) — and on success the score and notes are recorded on the
        script as it moves to `APPROVED`."
        PRD section 3.2: "On success, three things happen atomically: the
        route's `published_script_id` is set to the newly published script,
        the route's `version` increments by one, and any previously
        `PUBLISHED` script of the same route is moved by the system to
        `SUPERSEDED`."

        Design: Difficulty/non_linear_state_machine/script_version_revision_cycle
        """
        _room, route = _room_and_route()
        script = create_script(route["id"], content_text="Draft one")
        submit_script(script["id"])
        # Cycle through a revision before final approval.
        api_client.review_script_version(
            script["id"],
            {"decision": "REQUEST_REVISION", "reviewer_notes": "verify dates"},
            CURATOR,
        )
        submit_script(script["id"])
        approved = approve_script(script["id"], accuracy_score=92,
                                  reviewer_notes="accurate")
        assert approved["status"] == "APPROVED"
        assert approved["accuracy_score"] == 92
        published = publish_script(script["id"], route["version"])
        assert published["status"] == "PUBLISHED"
        route_after = get_route(route["id"])
        assert route_after["published_script_id"] == script["id"], (
            f"route published_script_id must point at the published script, "
            f"got {route_after['published_script_id']}"
        )


class TestPublishOptimisticConcurrency:

    def test_publish_script_with_stale_route_version_returns_412(self):
        """PRD section 2.4: "Publishing a script requires
        `expected_route_version`, matched against the parent tour route's
        current `version`. If the value no longer matches — because the
        route's version has advanced since the client last read it — the
        publish is rejected with `ERR_STALE_VERSION` (HTTP 412), and no
        script pointer is moved."
        PRD section 3.2: "Each draft is stamped with a `version_no` that is
        monotonic per route: the route's first script receives 1, and every
        later draft receives the next number, one more than the highest
        existing `version_no` on that route."

        Design: Corner/cross_cutting_layers/publish_script_with_stale_route_version_returns_412
        """
        _room, route = _room_and_route()
        route_version_at_create = route["version"]

        s1 = create_script(route["id"], content_text="Script one")
        submit_script(s1["id"])
        approve_script(s1["id"], accuracy_score=88)
        published = publish_script(s1["id"], route_version_at_create)
        assert published["status"] == "PUBLISHED"

        s2 = create_script(route["id"], content_text="Script two")
        assert s2["version_no"] == 2, (
            f"second draft must receive version_no 2, got {s2['version_no']}"
        )
        submit_script(s2["id"])
        approve_script(s2["id"], accuracy_score=91)

        resp = api_client.publish_script_version(
            s2["id"], {"expected_route_version": route_version_at_create},
            TEST_USERS["museum_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        s1_after = get_script(s1["id"])
        s2_after = get_script(s2["id"])
        assert s1_after["status"] == "PUBLISHED", (
            f"no script pointer may move on a stale publish; s1 must stay "
            f"PUBLISHED, got {s1_after['status']}"
        )
        assert s2_after["status"] == "APPROVED", (
            f"a stale publish must not move the candidate script; s2 must "
            f"stay APPROVED, got {s2_after['status']}"
        )


class TestReviewRoleDenial:

    def test_frontdesk_cannot_review_script_forbidden(self):
        """PRD section 2.1: "A request whose role is not on the endpoint's
        authorized list, or that fails an ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 4: POST /script-versions/{id}/review is authorized for
        Curator only.

        Design: Corner/rbac/frontdesk_cannot_review_script_forbidden
        """
        _room, route = _room_and_route()
        script = create_script(route["id"])
        submit_script(script["id"])
        resp = api_client.review_script_version(
            script["id"], {"decision": "APPROVE", "accuracy_score": 95},
            FRONT_DESK,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
