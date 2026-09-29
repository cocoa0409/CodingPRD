"""State-machine conventions: initial states, valid hops, wrong-state refusals, lockdown."""
from test_helpers import (
    ApiErrorId,
    add_addendum,
    api_client,
    approve_addendum,
    assert_same_instant,
    create_translation_payload,
    make_admin_headers,
    make_counsel_headers,
    make_localizer_headers,
    mint_version,
    new_document,
    new_jurisdiction,
    new_package,
    new_reviewer,
    refresh_package,
    refresh_review,
    refresh_version,
    request_review,
    setup_open_escalation_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def _new_translation(policy_version_id, language_code="en"):
    return validate_success(
        api_client.create_translation(
            policy_version_id,
            create_translation_payload(language_code),
            make_localizer_headers(),
        ),
        201,
    )


def test_the_three_authoring_machines_start_in_their_declared_initial_states():
    """PRD §3.2: "The minted version receives `version_no` equal to the document's
    `latest_version_no` plus 1 and enters status `DRAFT`" ... "A version's
    `effective_date`, `window_end_date` and `approved_at` all start null".  PRD §3.5:
    "A new track starts with `status` of `PENDING`, an empty `section_scores` array,
    `a11y_index` null, `a11y_round_no` at 0, and `conformance_level` null."  PRD §3.6:
    "A new package starts in `status` `DRAFT` with `scheduled_at`, `released_at`,
    `legal_review_deadline`, `coverage_snapshot_pct` and `coverage_live_pct` all null,
    and `roster_snapshot_size` at 0."

    Design: Corner/state_machines/corner_initial_states_of_the_three_authoring_machines
    """
    jurisdiction = new_jurisdiction()
    document = new_document()

    version = mint_version(document, [jurisdiction["id"]])
    assert version["status"] == "DRAFT", (
        f"a minted version starts in DRAFT, got {version['status']}"
    )
    assert version["approved_at"] is None

    track = _new_translation(version["id"])
    assert track["status"] == "PENDING", (
        f"a new localization track starts in PENDING, got {track['status']}"
    )
    assert track["a11y_index"] is None
    assert track["conformance_level"] is None
    assert track["a11y_round_no"] == 0
    assert track["section_scores"] == []

    package = new_package([jurisdiction["id"]], "2026-09-01T00:00:00Z")
    assert package["status"] == "DRAFT", (
        f"a new release package starts in DRAFT, got {package['status']}"
    )
    assert package["scheduled_at"] is None
    assert package["released_at"] is None
    assert package["legal_review_deadline"] is None
    assert package["coverage_snapshot_pct"] is None
    assert package["coverage_live_pct"] is None
    assert package["roster_snapshot_size"] == 0


def test_starting_a_translation_advances_the_track_without_scoring_it():
    """PRD §3.5: "Work begins with the move `PENDING → IN_TRANSLATION`, which
    additionally requires the owning version to be in `DRAFT`, `IN_LEGAL_REVIEW` or
    `APPROVED`".  PRD §2.4: "`version`, a monotonic integer that starts at 1 when the
    row is created and increases by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/corner_translation_pending_to_in_translation_is_a_valid_transition
    """
    jurisdiction = new_jurisdiction()
    document = new_document()
    version = mint_version(document, [jurisdiction["id"]])
    track = _new_translation(version["id"])

    data = validate_success(
        api_client.start_translation(track["id"], make_localizer_headers())
    )

    assert data["status"] == "IN_TRANSLATION", (
        f"PENDING -> IN_TRANSLATION expected, got {data['status']}"
    )
    assert data["version"] == track["version"] + 1, (
        f"the hop must bump the track version to {track['version'] + 1}, got {data['version']}"
    )
    assert data["a11y_index"] is None, (
        "scoring only happens at accessibility submission, so a11y_index stays null"
    )
    assert data["conformance_level"] is None
    assert refresh_version(version["id"])["status"] == "DRAFT", (
        "localization runs in parallel and must not move the version"
    )


def test_transitions_attempted_from_the_wrong_source_state_are_rejected():
    """PRD §3.4: "Approving a version requires it to be in `IN_LEGAL_REVIEW`;
    anything else is `ERR_VERSION_INVALID_STATE` (409)."  PRD §3.3: "The decision
    endpoint requires the review to be in `IN_PROGRESS`" ... "A hop attempted from
    any other source state is refused with `ERR_REVIEW_INVALID_STATE` (409)."

    Design: Corner/state_machines/corner_transitions_from_the_wrong_source_state_are_rejected
    """
    jurisdiction = new_jurisdiction()
    reviewer = new_reviewer(jurisdiction["id"])
    document = new_document()
    version = mint_version(document, [jurisdiction["id"]])
    approve_addendum(
        add_addendum(version["id"], jurisdiction["id"])["id"], reviewer["id"]
    )
    review = request_review(version["id"], jurisdiction["id"], reviewer["id"])
    assert version["status"] == "DRAFT"
    assert review["status"] == "REQUESTED"

    validate_error(
        api_client.approve_policy_version(version["id"], make_admin_headers()),
        ApiErrorId.ERR_VERSION_INVALID_STATE,
    )
    still_draft = refresh_version(version["id"])
    assert still_draft["status"] == "DRAFT", (
        "approval from DRAFT skips a mandatory state, so the version must not move; "
        f"got {still_draft['status']}"
    )
    assert still_draft["approved_at"] is None, (
        f"a refused approval must leave approved_at null, got {still_draft['approved_at']}"
    )

    validate_error(
        api_client.decide_legal_review(
            review["id"], {"verdict": "APPROVE"}, make_counsel_headers(reviewer["id"])
        ),
        ApiErrorId.ERR_REVIEW_INVALID_STATE,
    )
    still_requested = refresh_review(review["id"])
    assert still_requested["status"] == "REQUESTED", (
        "a decision skips the IN_PROGRESS step, so the review must stay REQUESTED; "
        f"got {still_requested['status']}"
    )
    assert still_requested["decided_at"] is None, (
        f"a refused decision must leave decided_at null, got {still_requested['decided_at']}"
    )


def test_a_cancelled_release_package_is_locked_against_every_further_hop():
    """PRD §3.6: "Cancellation is available from `DRAFT` or `SCHEDULED` and moves
    the package to `CANCELLED`; from any other status the attempt is refused with
    `ERR_RELEASE_NOT_CANCELLABLE` (409). `CANCELLED` and `CLOSED` are terminal." ...
    "Scheduling requires the package to be in `DRAFT` (`ERR_RELEASE_NOT_DRAFT`)".

    Design: Corner/state_machines/corner_cancelled_release_package_is_locked_against_further_hops
    """
    jurisdiction = new_jurisdiction()
    package = new_package([jurisdiction["id"]], "2026-09-01T00:00:00Z")

    cancelled = validate_success(
        api_client.cancel_release_package(package["id"], make_admin_headers())
    )
    assert cancelled["status"] == "CANCELLED", (
        f"cancellation from DRAFT must reach CANCELLED, got {cancelled['status']}"
    )
    locked_version = cancelled["version"]

    validate_error(
        api_client.cancel_release_package(package["id"], make_admin_headers()),
        ApiErrorId.ERR_RELEASE_NOT_CANCELLABLE,
    )

    validate_error(
        api_client.schedule_release_package(package["id"], make_admin_headers()),
        ApiErrorId.ERR_RELEASE_NOT_DRAFT,
    )

    frozen = refresh_package(package["id"])
    assert frozen["status"] == "CANCELLED", (
        f"a terminal package must stay CANCELLED, got {frozen['status']}"
    )
    assert frozen["version"] == locked_version, (
        "two refused hops must leave the package version untouched at "
        f"{locked_version}, got {frozen['version']}"
    )
    assert frozen["scheduled_at"] is None, (
        f"scheduled_at must stay null, got {frozen['scheduled_at']}"
    )
    assert frozen["legal_review_deadline"] is None, (
        f"legal_review_deadline must stay null, got {frozen['legal_review_deadline']}"
    )


def test_publishing_an_already_published_rendition_is_refused_not_replayed():
    """PRD §3.5: "`ABANDONED` and `PUBLISHED` are terminal." ... "A hop attempted
    from any other source state is refused with `ERR_TRANSLATION_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/corner_second_publish_of_the_same_translation_is_refused_not_replayed
    """
    from test_helpers import publish_translation, setup_approved_version

    ctx = setup_approved_version(publish_translation_track=False)
    track = publish_translation(ctx["version"]["id"], "en")
    assert track["status"] == "PUBLISHED"
    assert float(track["a11y_index"]) == 96.00, (
        f"section scores of 0.96 yield an index of 96.00, got {track['a11y_index']}"
    )
    assert track["conformance_level"] == "AAA"
    published_version = track["version"]

    validate_error(
        api_client.publish_translation(track["id"], make_localizer_headers()),
        ApiErrorId.ERR_TRANSLATION_INVALID_STATE,
    )

    frozen = validate_success(
        api_client.get_translation(track["id"], make_localizer_headers())
    )
    assert frozen["status"] == "PUBLISHED", (
        f"PUBLISHED is terminal so the track must stay there, got {frozen['status']}"
    )
    assert float(frozen["a11y_index"]) == 96.00, (
        f"a refused publish must not rescore the track, got {frozen['a11y_index']}"
    )
    assert frozen["conformance_level"] == "AAA"
    assert frozen["a11y_round_no"] == 0, (
        "no rework happened, so a11y_round_no must stay 0, got "
        f"{frozen['a11y_round_no']}"
    )
    assert frozen["version"] == published_version, (
        "a refused hop must not increment the track version off "
        f"{published_version}, got {frozen['version']}"
    )

    rows, meta = validate_paginated(
        api_client.list_translations(
            make_localizer_headers(),
            params={"policy_version_id": ctx["version"]["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, (
        "a refused publish must not append a second track row, got "
        f"{meta['total_count']}"
    )
    assert len(rows) == 1
    assert rows[0]["id"] == track["id"]


def test_unschedule_reverses_every_side_effect_that_schedule_wrote():
    """PRD §3.6: "Unscheduling moves `SCHEDULED → DRAFT` and clears both
    `scheduled_at` and `legal_review_deadline` back to null; it requires the package
    to be in `SCHEDULED`, or the attempt is refused with
    `ERR_RELEASE_NOT_SCHEDULED`."

    Design: Corner/state_machines/corner_unschedule_reverses_every_side_effect_of_schedule
    """
    from test_helpers import add_item, setup_approved_version

    ctx = setup_approved_version(jurisdiction={"min_legal_review_days": 5})
    package = new_package([ctx["jurisdiction"]["id"]], "2026-09-01T00:00:00Z")
    add_item(package["id"], ctx["version"]["id"])
    with_item = refresh_package(package["id"])
    baseline_version = with_item["version"]

    scheduled = validate_success(
        api_client.schedule_release_package(package["id"], make_admin_headers())
    )
    assert scheduled["status"] == "SCHEDULED"
    assert_same_instant(scheduled["scheduled_at"], "2026-08-01T00:00:00Z", "scheduled_at")
    assert_same_instant(
        scheduled["legal_review_deadline"],
        "2026-08-26T00:00:00.000Z",
        "legal_review_deadline",
    )
    assert scheduled["version"] == baseline_version + 1, (
        f"scheduling must bump the package version to {baseline_version + 1}, got "
        f"{scheduled['version']}"
    )

    reverted = validate_success(
        api_client.unschedule_release_package(package["id"], make_admin_headers())
    )
    assert reverted["status"] == "DRAFT", (
        f"unscheduling must return the package to DRAFT, got {reverted['status']}"
    )
    assert reverted["scheduled_at"] is None, (
        f"unscheduling must clear scheduled_at, got {reverted['scheduled_at']}"
    )
    assert reverted["legal_review_deadline"] is None, (
        "unscheduling must clear the stale legal_review_deadline rather than leave it "
        f"behind, got {reverted['legal_review_deadline']}"
    )
    assert reverted["version"] == baseline_version + 2, (
        f"the second hop must bump the version to {baseline_version + 2}, got "
        f"{reverted['version']}"
    )

    items, meta = validate_paginated(
        api_client.list_release_items(
            make_admin_headers(), params={"release_package_id": package["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"unscheduling must not drop the package's item, got {meta['total_count']}"
    )
    assert items[0]["policy_version_id"] == ctx["version"]["id"]


def test_escalate_hr_is_gated_on_the_recomputed_tier_not_merely_on_notified():
    """PRD §3.8: "The HR escalation moves `NOTIFIED → ESCALATED_HR` and additionally
    requires the case's `tier` to be exactly 3; a lower tier is refused with
    `ERR_ESCALATION_TIER_TOO_LOW` (409)." ... "the base tier is 1 when
    `days_overdue` is at least 1 and less than 7, 2 when it is at least 7 and less
    than 14, and 3 when it is 14 or more" ... "The same checkpoint also re-tiers
    every case whose `status` is `OPEN` or `NOTIFIED`".

    Design: Corner/state_machines/corner_escalate_hr_precondition_is_the_recomputed_tier_not_the_state
    """
    from test_helpers import refresh_assignment, refresh_case, set_clock, sweep

    ctx = setup_open_escalation_case(
        clock_to="2026-09-18T00:00:00Z",
        jurisdiction={"ack_deadline_days": 10},
        effective_date="2026-09-01T00:00:00Z",
    )
    assignment, case = ctx["assignment"], ctx["case"]
    assert_same_instant(
        refresh_assignment(assignment["id"])["due_date"],
        "2026-09-11T00:00:00Z",
        "due_date",
    )
    assert refresh_assignment(assignment["id"])["days_overdue"] == 7, (
        "a due_date of 2026-09-11 read at 2026-09-18 is 7 whole days overdue, got "
        f"{refresh_assignment(assignment['id'])['days_overdue']}"
    )
    assert case["tier"] == 2, (
        f"7 days overdue falls in the [7,14) band, which is tier 2, got {case['tier']}"
    )

    notified = validate_success(api_client.notify_escalation(case["id"], make_admin_headers()))
    assert notified["status"] == "NOTIFIED", (
        f"OPEN -> NOTIFIED expected, got {notified['status']}"
    )
    assert notified["notice_count"] == 1
    assert notified["tier"] == 2, (
        f"notification must not change the tier, got {notified['tier']}"
    )

    validate_error(
        api_client.escalate_hr(case["id"], make_admin_headers()),
        ApiErrorId.ERR_ESCALATION_TIER_TOO_LOW,
    )
    held = refresh_case(case["id"])
    assert held["status"] == "NOTIFIED", (
        "being in NOTIFIED is not sufficient for the HR hop, so the case must stay "
        f"NOTIFIED, got {held['status']}"
    )
    assert held["closed_at"] is None

    set_clock("2026-09-25T00:00:00Z")
    sweep()
    retiered = refresh_case(case["id"])
    assert refresh_assignment(assignment["id"])["days_overdue"] == 14, (
        "a due_date of 2026-09-11 read at 2026-09-25 is 14 whole days overdue, got "
        f"{refresh_assignment(assignment['id'])['days_overdue']}"
    )
    assert retiered["tier"] == 3, (
        f"14 days overdue lifts the NOTIFIED case to tier 3, got {retiered['tier']}"
    )
    assert retiered["status"] == "NOTIFIED", (
        f"re-tiering must not move the case's status, got {retiered['status']}"
    )

    escalated = validate_success(api_client.escalate_hr(case["id"], make_admin_headers()))
    assert escalated["status"] == "ESCALATED_HR", (
        "the identical call must succeed once the tier reaches 3, got "
        f"{escalated['status']}"
    )
    assert escalated["tier"] == 3

    rows, meta = validate_paginated(
        api_client.list_escalations(
            make_admin_headers(), params={"assignment_id": assignment["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"the sweep must not open a second case for the same assignment, got {meta['total_count']}"
    )
    assert rows[0]["id"] == case["id"]
