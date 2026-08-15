"""Assignment lifecycle: submission, review cycle, acceptance cascade, kill fee
(PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_assignment,
    commission_assignment,
    create_accepted_assignment,
    create_photographer,
    create_story,
    get_assignment_fresh,
    get_image_fresh,
    get_photographer_fresh,
    make_photographer_headers,
    submit_assignment_image,
    submit_assignment,
    validate_error,
    validate_success,
)


def test_assignment_accept_from_in_progress_rejected(api, photo_editor_headers):
    """PRD §3.4: "Acceptance moves `SUBMITTED` to `ACCEPTED` and fires a two-hop
    cascade". PRD §2.8: "State-machine from-state preconditions for action
    endpoints; terminal states reject all further transitions; else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/assignment_accept_from_in_progress_rejected
    """
    photographer = create_photographer()
    story = create_story()
    _, assignment_id = commission_assignment(photographer["id"], story_id=story["id"])
    submit_assignment_image(assignment_id, photographer["id"])

    assignment = get_assignment_fresh(assignment_id)
    assert assignment["status"] == "IN_PROGRESS"

    resp = api.accept_assignment(assignment_id, photo_editor_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_assignment_fresh(assignment_id)
    assert after["status"] == "IN_PROGRESS", "rejected accept must leave the assignment untouched"


def test_assignment_cancel_from_accepted_terminal_rejected(api, photo_editor_headers):
    """PRD §3.4: "`ACCEPTED` is terminal." PRD §2.8: "State-machine from-state
    preconditions for action endpoints; terminal states reject all further
    transitions; else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/assignment_cancel_from_accepted_terminal_rejected
    """
    bundle = create_accepted_assignment()
    assert bundle["assignment"]["status"] == "ACCEPTED"

    resp = api.cancel_assignment(bundle["assignment_id"], photo_editor_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_image_limit_exceeded_rejected(api, photo_editor_headers):
    """PRD §3.4: "The assignment accepts at most `max_image_count` images; a
    submission that would exceed the ceiling is rejected with
    `ERR_IMAGE_LIMIT_EXCEEDED`."

    Design: Corner/validations/image_limit_exceeded_rejected
    """
    photographer = create_photographer()
    story = create_story()
    _, assignment_id = commission_assignment(
        photographer["id"], story_id=story["id"], max_image_count=1,
    )
    submit_assignment_image(assignment_id, photographer["id"])

    resp = api.submit_assignment_image(
        assignment_id,
        {
            "caption": "Smoke over the river at sunrise",
            "credit_line": "Sam Staff / ACME News",
        },
        make_photographer_headers(photographer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_IMAGE_LIMIT_EXCEEDED)


def test_min_images_not_met_rejected(api, photo_editor_headers):
    """PRD §3.4: "Submission requires at least `min_image_count` images in
    `INGESTED` status on the assignment; otherwise it is rejected with
    `ERR_MIN_IMAGES_NOT_MET`."

    Design: Corner/validations/min_images_not_met_rejected
    """
    photographer = create_photographer()
    story = create_story()
    _, assignment_id = commission_assignment(
        photographer["id"], story_id=story["id"], min_image_count=2,
    )
    submit_assignment_image(assignment_id, photographer["id"])

    resp = api.submit_assignment(assignment_id, make_photographer_headers(photographer["id"]))
    validate_error(resp, ApiErrorId.ERR_MIN_IMAGES_NOT_MET)


def test_kill_fee_credited_on_cancel_from_submitted(api, photo_editor_headers):
    """PRD §3.4: "Cancelling from `SUBMITTED` or `REVISION_REQUESTED` runs the
    kill-fee rule: `kill_fee_cents` is set to the photographer's `day_rate_cents`
    multiplied by the assignment's `day_count`, multiplied by one half, rounded
    half-up to integer cents, and that amount is added to the photographer's
    `accrued_earnings_cents`."

    Design: Corner/calculations/kill_fee_credited_on_cancel_from_submitted
    """
    photographer = create_photographer()  # STAFF, day_rate 25000
    story = create_story()
    _, assignment_id = commission_assignment(
        photographer["id"], story_id=story["id"],
        shoot_start="2026-08-10T09:00:00Z", shoot_end="2026-08-11T17:00:00Z",
    )
    submit_assignment_image(assignment_id, photographer["id"])
    submit_assignment(assignment_id, photographer["id"])

    cancelled = validate_success(api.cancel_assignment(assignment_id, photo_editor_headers), 200)
    assert_assignment(cancelled)
    assert cancelled["status"] == "CANCELLED"
    # round_half_up(25000 x day_count 2 x 0.5) = 25000
    assert cancelled["kill_fee_cents"] == 25000, (
        f"kill fee must be day_rate x day_count x 0.5 = 25000, got {cancelled['kill_fee_cents']}"
    )

    photographer_after = get_photographer_fresh(photographer["id"], headers=photo_editor_headers)
    assert photographer_after["accrued_earnings_cents"] == 25000, (
        "kill fee must be added to the photographer's accrued earnings"
    )


def test_revision_cycle_returns_assignment_to_submitted(api, photo_editor_headers):
    """PRD §3.4: "Requesting a revision moves `SUBMITTED` to `REVISION_REQUESTED`,
    increments `revision_count` by one, and may carry an optional `feedback` note;
    the photographer's next image submission cycles the assignment back to
    `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/assignment_revision_cycle_returns_to_submitted
    """
    photographer = create_photographer()
    story = create_story()
    _, assignment_id = commission_assignment(
        photographer["id"], story_id=story["id"], max_image_count=3,
    )
    submit_assignment_image(assignment_id, photographer["id"])
    submit_assignment(assignment_id, photographer["id"])

    revised = validate_success(
        api.request_revision(assignment_id, {"feedback": "Need a wider angle"}, photo_editor_headers),
        200,
    )
    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["revision_count"] == 1, "revision_count must increment by one per request"

    submit_assignment_image(assignment_id, photographer["id"],
                            caption="Wide shot of the bridge fire scene")
    after_image = get_assignment_fresh(assignment_id)
    assert after_image["status"] == "IN_PROGRESS", (
        "a submission while REVISION_REQUESTED must return the assignment to IN_PROGRESS"
    )

    resubmitted = validate_success(
        api.submit_assignment(assignment_id, make_photographer_headers(photographer["id"])), 200,
    )
    assert resubmitted["status"] == "SUBMITTED"


def test_assignment_acceptance_after_revision_cycle_clears_all_images(api, photo_editor_headers):
    """PRD §3.4: "Acceptance moves `SUBMITTED` to `ACCEPTED` and fires a two-hop
    cascade: the assignment's `accepted_at` is set to the logical now; every image
    on the assignment still `INGESTED` moves to `CLEARED`; and for each image so
    cleared, the photographer's `accrued_earnings_cents` increases by that
    photographer's `per_image_fee_cents`, with the photographer's `version`
    incrementing."

    Design: Difficulty/non_linear_state_machine/assignment_revision_cycle_returns_to_submitted
    """
    photographer = create_photographer()  # STAFF, per_image_fee 40000
    story = create_story()
    _, assignment_id = commission_assignment(
        photographer["id"], story_id=story["id"], max_image_count=3,
    )
    image1 = submit_assignment_image(assignment_id, photographer["id"])
    submit_assignment(assignment_id, photographer["id"])
    validate_success(
        api.request_revision(assignment_id, {"feedback": "Need a wider angle"}, photo_editor_headers), 200,
    )
    image2 = submit_assignment_image(assignment_id, photographer["id"],
                                     caption="Wide shot of the bridge fire scene")
    submit_assignment(assignment_id, photographer["id"])

    accepted = validate_success(api.accept_assignment(assignment_id, photo_editor_headers), 200)
    assert accepted["status"] == "ACCEPTED"

    for image in (image1, image2):
        fresh = get_image_fresh(image["id"], headers=photo_editor_headers)
        assert fresh["status"] == "CLEARED", "every still-INGESTED image must clear on acceptance"

    photographer_after = get_photographer_fresh(photographer["id"], headers=photo_editor_headers)
    assert photographer_after["accrued_earnings_cents"] == 80000, (
        "two cleared images at per_image_fee 40000 must accrue 80000, "
        f"got {photographer_after['accrued_earnings_cents']}"
    )


def test_assignment_accept_cascade_clears_images(api, photo_editor_headers):
    """PRD §3.4: "Acceptance moves `SUBMITTED` to `ACCEPTED` and fires a two-hop
    cascade: the assignment's `accepted_at` is set to the logical now; every image
    on the assignment still `INGESTED` moves to `CLEARED`; and for each image so
    cleared, the photographer's `accrued_earnings_cents` increases by that
    photographer's `per_image_fee_cents`, with the photographer's `version`
    incrementing."

    Design: Difficulty/transitive_cascade/assignment_accept_cascade_images_accrual
    """
    bundle = create_accepted_assignment(num_images=2, decide_overrides={"max_image_count": 3})
    assignment = bundle["assignment"]
    assert assignment["status"] == "ACCEPTED"
    assert assignment["accepted_at"], "accepted_at must be stamped at acceptance"

    for image in bundle["images"]:
        fresh = get_image_fresh(image["id"], headers=photo_editor_headers)
        assert fresh["status"] == "CLEARED", "hop 1: every INGESTED image must move to CLEARED"


def test_assignment_accept_cascade_accrues_per_image_fees(api, photo_editor_headers):
    """PRD §3.4: "Acceptance moves `SUBMITTED` to `ACCEPTED` and fires a two-hop
    cascade: the assignment's `accepted_at` is set to the logical now; every image
    on the assignment still `INGESTED` moves to `CLEARED`; and for each image so
    cleared, the photographer's `accrued_earnings_cents` increases by that
    photographer's `per_image_fee_cents`, with the photographer's `version`
    incrementing."

    Design: Difficulty/transitive_cascade/assignment_accept_cascade_images_accrual
    """
    bundle = create_accepted_assignment(num_images=2, decide_overrides={"max_image_count": 3})
    photographer_after = get_photographer_fresh(
        bundle["photographer"]["id"], headers=photo_editor_headers,
    )
    assert photographer_after["accrued_earnings_cents"] == 80000, (
        "hop 2: two cleared images at per_image_fee 40000 must accrue 80000, "
        f"got {photographer_after['accrued_earnings_cents']}"
    )
