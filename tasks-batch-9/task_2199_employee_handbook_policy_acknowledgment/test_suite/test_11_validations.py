"""Validation rules: capture gates, accessibility shape and thresholds, guards."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_acknowledgment_payload,
    create_translation_payload,
    make_admin_headers,
    make_employee_headers,
    make_localizer_headers,
    mint_version,
    new_document,
    new_jurisdiction,
    refresh_assignment,
    refresh_employee,
    refresh_package,
    refresh_translation,
    setup_released_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def _started_track(section_count=2):
    """An en localization track in IN_TRANSLATION on a DRAFT two-section version."""
    jurisdiction = new_jurisdiction()
    version = mint_version(new_document(), [jurisdiction["id"]], section_count=section_count)
    track = validate_success(
        api_client.create_translation(
            version["id"], create_translation_payload("en"), make_localizer_headers()
        ),
        201,
    )
    return version, validate_success(
        api_client.start_translation(track["id"], make_localizer_headers())
    )


def test_esign_proxy_and_rendition_gates_are_three_separate_capture_rules():
    """PRD §3.7: "When `method` is `ESIGN`, the assignment jurisdiction's
    `esign_permitted` must be true, or `ERR_ESIGN_NOT_PERMITTED` (409). When `method`
    is `ATTESTED`, the assignment jurisdiction's `proxy_ack_permitted` must be true
    **and** the actor must be an `HRComplianceAdmin`, or
    `ERR_PROXY_ACK_NOT_PERMITTED` (409). Finally, the supplied `language_code` must
    match a rendition on the assignment's version whose `status` is `PUBLISHED`, or
    `ERR_RENDITION_LANGUAGE_UNKNOWN` (409). A `WET_SIGNATURE` acknowledgment is
    subject to neither the e-sign nor the proxy gate."

    Design: Corner/validations/corner_acknowledgment_capture_gates_by_method_and_language
    """
    ctx = setup_released_scenario(
        jurisdiction={
            "esign_permitted": False,
            "proxy_ack_permitted": False,
            "ack_deadline_days": 30,
            "min_legal_review_days": 5,
        },
        effective_date="2026-09-01T00:00:00Z",
    )
    assignment, employee = ctx["assignment"], ctx["employee"]
    assert assignment["ack_state"] == "PENDING"
    subject_headers = make_employee_headers(employee["id"])

    validate_error(
        api_client.create_acknowledgment(
            create_acknowledgment_payload(assignment["id"], method="ESIGN"),
            subject_headers,
        ),
        ApiErrorId.ERR_ESIGN_NOT_PERMITTED,
    )
    validate_error(
        api_client.create_acknowledgment(
            create_acknowledgment_payload(
                assignment["id"], method="ATTESTED", signature_text="HR attests by phone"
            ),
            make_admin_headers(),
        ),
        ApiErrorId.ERR_PROXY_ACK_NOT_PERMITTED,
    )
    validate_error(
        api_client.create_acknowledgment(
            create_acknowledgment_payload(
                assignment["id"],
                method="WET_SIGNATURE",
                language_code="es",
                signature_text="scan-0001",
            ),
            subject_headers,
        ),
        ApiErrorId.ERR_RENDITION_LANGUAGE_UNKNOWN,
    )

    assert refresh_assignment(assignment["id"])["ack_state"] == "PENDING", (
        "three refused captures must leave the assignment PENDING"
    )
    assert refresh_employee(employee["id"])["open_ack_count"] == 1
    _rows, meta = validate_paginated(
        api_client.list_acknowledgments(
            make_admin_headers(), params={"assignment_id": assignment["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, (
        f"a refused capture must append no evidence row, got {meta['total_count']}"
    )

    accepted = validate_success(
        api_client.create_acknowledgment(
            create_acknowledgment_payload(
                assignment["id"], method="WET_SIGNATURE", signature_text="scan-0002"
            ),
            subject_headers,
        ),
        201,
    )
    assert accepted["status"] == "EFFECTIVE"
    assert accepted["method"] == "WET_SIGNATURE", (
        "a wet signature bypasses both the e-sign and the proxy gate, got "
        f"{accepted['method']}"
    )
    assert refresh_assignment(assignment["id"])["ack_state"] == "ACKNOWLEDGED"
    assert refresh_employee(employee["id"])["open_ack_count"] == 0
    assert refresh_package(ctx["package"]["id"])["status"] == "CLOSED", (
        "the only open assignment closed, so the package must reach CLOSED"
    )


def test_section_score_shape_is_a_schema_failure_and_the_gate_is_a_business_refusal():
    """PRD §3.5: "That array must have exactly as many entries as the owning version's
    `section_count`, in document order, and every entry must be a number in the
    inclusive range from 0 to 1 with up to six decimal digits; a wrong length or an
    out-of-range element is refused with `ERR_SECTION_SCORE_SHAPE` at HTTP 422." ...
    "A new track starts with `status` of `PENDING`, an empty `section_scores` array,
    `a11y_index` null, `a11y_round_no` at 0, and `conformance_level` null." ...
    "Publishing moves the track `A11Y_REVIEW → PUBLISHED` and is gated on the
    conformance band: it is permitted only when `conformance_level` is `AA` or `AAA`,
    and a `FAIL` band is refused with `ERR_A11Y_GATE_NOT_MET` (409)."

    Design: Corner/validations/corner_a11y_submission_shape_and_publication_gate_violations
    """
    _version, track = _started_track(section_count=2)

    validate_error(
        api_client.submit_a11y(
            track["id"], {"section_scores": [0.8]}, make_localizer_headers()
        ),
        ApiErrorId.ERR_SECTION_SCORE_SHAPE,
    )
    validate_error(
        api_client.submit_a11y(
            track["id"], {"section_scores": [0.8, 1.5]}, make_localizer_headers()
        ),
        ApiErrorId.ERR_SECTION_SCORE_SHAPE,
    )

    untouched = refresh_translation(track["id"])
    assert untouched["status"] == "IN_TRANSLATION", (
        f"a shape failure must not move the track, got {untouched['status']}"
    )
    assert untouched["a11y_index"] is None, (
        "the shape rule runs before any index is computed, so a11y_index stays null; "
        f"got {untouched['a11y_index']}"
    )
    assert untouched["section_scores"] == [], (
        "a refused submission must leave the declared empty array in place, got "
        f"{untouched['section_scores']}"
    )

    scored = validate_success(
        api_client.submit_a11y(
            track["id"], {"section_scores": [0.80, 0.80]}, make_localizer_headers()
        )
    )
    assert scored["status"] == "A11Y_REVIEW", (
        f"a well-shaped submission parks the track in A11Y_REVIEW, got {scored['status']}"
    )
    assert float(scored["a11y_index"]) == 80.00, (
        f"two sections at 0.80 give an index of 80.00, got {scored['a11y_index']}"
    )
    assert scored["conformance_level"] == "FAIL", (
        f"80.00 is below the 90.00 AA floor, so the level is FAIL, got {scored['conformance_level']}"
    )

    validate_error(
        api_client.publish_translation(track["id"], make_localizer_headers()),
        ApiErrorId.ERR_A11Y_GATE_NOT_MET,
    )
    held = refresh_translation(track["id"])
    assert held["status"] == "A11Y_REVIEW", (
        f"a refused publish must leave the track in A11Y_REVIEW, got {held['status']}"
    )
    assert held["a11y_round_no"] == 0, (
        f"no rework lap happened, so a11y_round_no stays 0, got {held['a11y_round_no']}"
    )


def test_an_index_exactly_at_the_aa_floor_publishes_after_a_rework_lap():
    """PRD §3.5: "it is `FAIL` when the index is below 90.00, `AA` when the index is at
    least 90.00 and below 96.00, and `AAA` when the index is at least 96.00." ...
    "Reworking moves the track `A11Y_REVIEW → IN_TRANSLATION` and increases
    `a11y_round_no` by 1" ... "No prior submission's scores are carried forward — each
    submission fully replaces `section_scores`."

    Design: Corner/validations/corner_a11y_index_exactly_at_the_aa_floor_is_publishable
    """
    _version, track = _started_track(section_count=2)
    failed = validate_success(
        api_client.submit_a11y(
            track["id"], {"section_scores": [0.80, 0.80]}, make_localizer_headers()
        )
    )
    assert float(failed["a11y_index"]) == 80.00
    assert failed["conformance_level"] == "FAIL"

    reworked = validate_success(
        api_client.rework_translation(track["id"], make_localizer_headers())
    )
    assert reworked["status"] == "IN_TRANSLATION", (
        f"a rework lap returns the track to IN_TRANSLATION, got {reworked['status']}"
    )
    assert reworked["a11y_round_no"] == 1, (
        f"the rework lap must raise a11y_round_no to 1, got {reworked['a11y_round_no']}"
    )

    rescored = validate_success(
        api_client.submit_a11y(
            track["id"], {"section_scores": [0.90, 0.90]}, make_localizer_headers()
        )
    )
    assert float(rescored["a11y_index"]) == 90.00, (
        f"two sections at 0.90 give an index of exactly 90.00, got {rescored['a11y_index']}"
    )
    assert rescored["conformance_level"] == "AA", (
        "90.00 is the inclusive lower edge of the AA band, got "
        f"{rescored['conformance_level']}"
    )

    published = validate_success(
        api_client.publish_translation(track["id"], make_localizer_headers())
    )
    assert published["status"] == "PUBLISHED", (
        f"an AA track clears the publication gate, got {published['status']}"
    )
    assert [float(s) for s in published["section_scores"]] == [0.90, 0.90], (
        "the second submission fully replaces the earlier array, got "
        f"{published['section_scores']}"
    )
    assert published["a11y_round_no"] == 1, (
        f"exactly one rework lap happened, got {published['a11y_round_no']}"
    )


def test_delivery_needs_a_higher_index_than_publication_for_an_accessible_assignee():
    """PRD §3.5: "Delivery to an individual employee requires a `PUBLISHED` track whose
    `language_code` matches that employee's `preferred_language_code`, and — when that
    employee's `needs_accessible_format` is true — that track's `a11y_index` must be at
    least 96.00, the same threshold that separates the `AAA` band from `AA`. A failure
    of either condition is refused with `ERR_ACCESSIBLE_RENDITION_UNAVAILABLE` (409)."

    Design: Corner/validations/corner_accessible_employee_needs_a_higher_a11y_index_than_publication
    """
    from test_helpers import deliver, sole_assignment

    ctx = setup_released_scenario(
        jurisdiction={"min_legal_review_days": 5, "ack_deadline_days": 30},
        employee={"needs_accessible_format": True},
        extra_employees=1,
        section_scores=[0.9575, 0.9575],
        effective_date="2026-09-01T00:00:00Z",
        deliver=False,
    )
    track = ctx["translation"]
    assert float(track["a11y_index"]) == 95.75, (
        f"two sections at 0.9575 give an index of 95.75, got {track['a11y_index']}"
    )
    assert track["conformance_level"] == "AA"
    assert track["status"] == "PUBLISHED", (
        "95.75 clears the AA publication gate, got " f"{track['status']}"
    )
    assert ctx["package"]["roster_snapshot_size"] == 2
    assert ctx["package"]["status"] == "RELEASED"

    standard = sole_assignment(ctx["package"]["id"], ctx["extras"][0]["id"])
    delivered = deliver(standard["id"])
    assert delivered["ack_state"] == "PENDING", (
        "the standard assignee is served by the same AA rendition, got "
        f"{delivered['ack_state']}"
    )

    accessible = ctx["assignment"]
    validate_error(
        api_client.deliver_assignment(accessible["id"], make_admin_headers()),
        ApiErrorId.ERR_ACCESSIBLE_RENDITION_UNAVAILABLE,
    )
    blocked = refresh_assignment(accessible["id"])
    assert blocked["ack_state"] == "UNDELIVERED", (
        "95.75 is below the 96.00 accessibility floor, so the row must stay "
        f"UNDELIVERED, got {blocked['ack_state']}"
    )
    assert blocked["delivered_at"] is None, (
        f"a refused delivery must leave delivered_at null, got {blocked['delivered_at']}"
    )
    assert refresh_employee(ctx["employee"]["id"])["open_ack_count"] == 1
    assert refresh_package(ctx["package"]["id"])["status"] == "RELEASED"


def test_empty_release_and_a_present_effective_date_are_reported_independently():
    """PRD §3.6: the package must carry "at least one item, or it is refused with
    `ERR_RELEASE_EMPTY` (409)." ... "Then the `effective_date` must be strictly later
    than the logical clock, or the attempt is refused with
    `ERR_EFFECTIVE_DATE_IN_PAST` (409) — a package may not be scheduled to take effect
    at the current instant or in the past." ... "Finally the legal-review lead-time
    rule runs, yielding `ERR_LEGAL_REVIEW_LEAD_TIME_SHORT` (409)."

    Design: Corner/validations/corner_schedule_requires_items_and_a_strictly_future_effective_date
    """
    from test_helpers import add_item, new_package, setup_approved_version

    ctx = setup_approved_version(jurisdiction={"min_legal_review_days": 5})
    jurisdiction = ctx["jurisdiction"]

    empty = new_package([jurisdiction["id"]], "2026-09-01T00:00:00Z")
    validate_error(
        api_client.schedule_release_package(empty["id"], make_admin_headers()),
        ApiErrorId.ERR_RELEASE_EMPTY,
    )
    assert refresh_package(empty["id"])["status"] == "DRAFT"
    assert refresh_package(empty["id"])["scheduled_at"] is None

    today = new_package([jurisdiction["id"]], "2026-08-01T00:00:00Z")
    add_item(today["id"], ctx["version"]["id"])
    validate_error(
        api_client.schedule_release_package(today["id"], make_admin_headers()),
        ApiErrorId.ERR_EFFECTIVE_DATE_IN_PAST,
    )
    blocked = refresh_package(today["id"])
    assert blocked["status"] == "DRAFT", (
        "an effective_date equal to the clock is not strictly later, so the package "
        f"must stay DRAFT, got {blocked['status']}"
    )
    assert blocked["legal_review_deadline"] is None, (
        f"legal_review_deadline must stay null, got {blocked['legal_review_deadline']}"
    )


def test_global_and_composite_uniqueness_keys_are_enforced_on_their_own_terms():
    """PRD §3.2: "Uniqueness across the whole system is enforced with a single error,
    `ERR_DUPLICATE_RESOURCE` at 409. It guards: `state_code` globally on
    jurisdictions; `bar_number` per `jurisdiction_id` on reviewers; `work_email`
    globally on employees; `title` globally on policy documents; `name` globally on
    release packages; the pair of `policy_version_id` and `jurisdiction_id` on
    addenda; the pair of `policy_version_id` and `language_code` on translations; the
    pair of `release_package_id` and `policy_version_id` on release items; and the pair
    of `policy_version_id` and `jurisdiction_id` on legal reviews."

    Design: Corner/validations/corner_uniqueness_violations_across_global_and_composite_keys
    """
    from test_helpers import (
        create_employee_payload,
        create_jurisdiction_payload,
        create_legal_reviewer_payload,
        new_employee,
        new_reviewer,
    )

    ca = new_jurisdiction(min_legal_review_days=5)
    ny = new_jurisdiction()
    employee = new_employee(ca["id"])
    new_reviewer(ca["id"], bar_number="SHARED-1")
    document = new_document()
    v1 = mint_version(document, [ca["id"]])
    v2 = mint_version(document, [ca["id"]])
    validate_success(
        api_client.create_translation(
            v1["id"], create_translation_payload("en"), make_localizer_headers()
        ),
        201,
    )

    validate_error(
        api_client.create_jurisdiction(
            create_jurisdiction_payload(state_code=ca["state_code"]), make_admin_headers()
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )
    validate_error(
        api_client.create_employee(
            create_employee_payload(ny["id"], work_email=employee["work_email"]),
            make_admin_headers(),
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )
    validate_error(
        api_client.create_translation(
            v1["id"], create_translation_payload("en"), make_localizer_headers()
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )

    reused_language = validate_success(
        api_client.create_translation(
            v2["id"], create_translation_payload("en"), make_localizer_headers()
        ),
        201,
    )
    assert reused_language["language_code"] == "en", (
        "the translation key is composite, so the same language is reusable on a "
        "different version"
    )
    reused_bar = validate_success(
        api_client.create_legal_reviewer(
            create_legal_reviewer_payload(ny["id"], bar_number="SHARED-1"),
            make_admin_headers(),
        ),
        201,
    )
    assert reused_bar["bar_number"] == "SHARED-1", (
        "bar_number is unique only within a jurisdiction, so a second state may reuse it"
    )

    _rows, meta = validate_paginated(
        api_client.list_jurisdictions(
            make_admin_headers(), params={"state_code": ca["state_code"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"the rejected duplicate state_code must not have been stored, got {meta['total_count']}"
    )
    for version_id in (v1["id"], v2["id"]):
        _t, t_meta = validate_paginated(
            api_client.list_translations(
                make_localizer_headers(),
                params={"policy_version_id": version_id, "limit": 100},
            )
        )
        assert t_meta["total_count"] == 1, (
            f"each version must carry exactly one en track, got {t_meta['total_count']}"
        )
    stored = validate_success(api_client.get_jurisdiction(ca["id"], make_admin_headers()))
    assert stored["min_legal_review_days"] == 5, (
        "the rejected duplicate must not have overwritten the incumbent row, got "
        f"{stored['min_legal_review_days']}"
    )


def test_pagination_bounds_are_four_hundred_and_the_clock_admits_an_equal_instant():
    """PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100.
    `offset` defaults to 0 and has a minimum of 0; there is no upper bound on it. A
    `limit` that is not an integer inside the inclusive range from 1 to 100, or an
    `offset` that is not an integer of at least 0, is rejected with
    `ERR_INVALID_PAGINATION` at HTTP 400."  PRD §2.5: "The clock is strictly
    forward-only: a requested `to_iso8601` earlier than the current logical clock is
    rejected with `ERR_CLOCK_REWIND` (409), while a value equal to the current reading
    is accepted as a no-op advance."

    Design: Corner/validations/corner_pagination_bounds_and_clock_monotonicity_guards
    """
    from test_helpers import assert_same_instant, new_employee, set_clock

    jurisdictions = [new_jurisdiction() for _ in range(3)]
    set_clock("2026-08-10T00:00:00Z")

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api_client.list_jurisdictions(make_admin_headers(), params=params),
            ApiErrorId.ERR_INVALID_PAGINATION,
        )

    rows, meta = validate_paginated(
        api_client.list_jurisdictions(make_admin_headers(), params={"limit": 100, "offset": 0})
    )
    assert meta["limit"] == 100, f"meta must echo the requested limit, got {meta['limit']}"
    assert meta["offset"] == 0, f"meta must echo the requested offset, got {meta['offset']}"
    assert meta["total_count"] == 3, (
        f"three jurisdictions satisfy the empty filter set, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"the whole result set fits inside the window, got {meta['has_more']}"
    )
    assert len(rows) == 3

    validate_error(
        api_client.set_clock("2026-08-09T23:59:59Z", make_admin_headers()),
        ApiErrorId.ERR_CLOCK_REWIND,
    )
    set_clock("2026-08-10T00:00:00Z")

    witness = new_employee(jurisdictions[0]["id"])
    assert_same_instant(
        witness["created_at"],
        "2026-08-10T00:00:00.000Z",
        "the rejected rewind must have left the clock at 2026-08-10, so created_at",
    )


def test_reviewer_capacity_counts_touching_intervals_and_inactivity_is_a_separate_rule():
    """PRD §3.3: "Count the reviewer's existing reviews whose `status` is `REQUESTED` or
    `IN_PROGRESS` and whose own closed interval from `assigned_at` through `due_at`
    intersects that candidate interval. Because both intervals are closed, merely
    touching endpoints counts as an intersection — a candidate whose start instant
    equals an existing review's `due_at` overlaps it. That count must be **strictly
    less than** the reviewer's `concurrent_review_limit`; if it has already reached the
    limit, the request is refused with `ERR_REVIEWER_CAPACITY_EXCEEDED` (409)."  PRD
    §3.1: "`is_active` defaults to true and controls whether the reviewer may receive
    new work: requesting a review from a reviewer whose `is_active` is false is refused
    with `ERR_REVIEWER_INACTIVE`".

    Design: Corner/validations/corner_reviewer_capacity_interval_touching_and_inactivity
    """
    from test_helpers import (
        add_addendum,
        create_legal_review_payload,
        decide_review_as,
        make_author_headers,
        new_reviewer,
        refresh_review,
        request_review,
        set_clock,
        start_review_as,
        submit_for_review,
    )
    from test_helpers import assert_same_instant

    jurisdiction = new_jurisdiction()
    r1 = new_reviewer(jurisdiction["id"], concurrent_review_limit=1)
    r_off = new_reviewer(jurisdiction["id"], is_active=False)
    document = new_document()
    v1 = mint_version(document, [jurisdiction["id"]])
    v2 = mint_version(document, [jurisdiction["id"]])
    add_addendum(v1["id"], jurisdiction["id"])
    lr1 = request_review(
        v1["id"], jurisdiction["id"], r1["id"], due_at="2026-08-20T00:00:00Z"
    )
    submit_for_review(v1["id"])

    def _request_on_v2(reviewer_id, due_at):
        return api_client.create_legal_review(
            v2["id"],
            create_legal_review_payload(jurisdiction["id"], reviewer_id, due_at=due_at),
            make_author_headers(),
        )

    validate_error(
        _request_on_v2(r1["id"], "2026-08-25T00:00:00Z"),
        ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED,
    )

    set_clock("2026-08-20T00:00:00Z")
    validate_error(
        _request_on_v2(r1["id"], "2026-08-30T00:00:00Z"),
        ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED,
    )
    validate_error(
        _request_on_v2(r_off["id"], "2026-08-30T00:00:00Z"),
        ApiErrorId.ERR_REVIEWER_INACTIVE,
    )

    start_review_as(lr1["id"], r1["id"])
    decide_review_as(lr1["id"], r1["id"], "APPROVE")
    closed = refresh_review(lr1["id"])
    assert closed["status"] == "APPROVED", (
        f"the incumbent must leave the open set, got {closed['status']}"
    )
    assert_same_instant(closed["decided_at"], "2026-08-20T00:00:00.000Z", "decided_at")

    lr2 = validate_success(_request_on_v2(r1["id"], "2026-08-30T00:00:00Z"), 201)
    assert lr2["status"] == "REQUESTED", (
        "the slot freed by the decided incumbent admits the new request, got "
        f"{lr2['status']}"
    )
    assert_same_instant(lr2["assigned_at"], "2026-08-20T00:00:00.000Z", "assigned_at")

    _rows, meta = validate_paginated(
        api_client.list_legal_reviews(
            make_admin_headers(), params={"reviewer_id": r1["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2, (
        f"only two review rows may exist for the busy reviewer, got {meta['total_count']}"
    )
    _off_rows, off_meta = validate_paginated(
        api_client.list_legal_reviews(
            make_admin_headers(), params={"reviewer_id": r_off["id"], "limit": 100}
        )
    )
    assert off_meta["total_count"] == 0, (
        f"the inactive reviewer must hold no review rows, got {off_meta['total_count']}"
    )


def test_exception_request_without_a_resolvable_pending_assignment_is_refused():
    """PRD §3.9: "The requester must have exactly one assignment on that version whose
    `ack_state` is `PENDING`, and that assignment becomes the request's
    `assignment_id`; if no such pending assignment exists, the request is refused with
    `ERR_NO_PENDING_ASSIGNMENT` (409)" ... "Creating a request increments the
    requesting employee's `version` by 1."

    Design: Corner/validations/corner_exception_request_without_a_pending_assignment_is_refused
    """
    from test_helpers import create_policy_exception_payload, new_employee

    jurisdiction = new_jurisdiction()
    employee = new_employee(jurisdiction["id"])
    version = mint_version(new_document(), [jurisdiction["id"]])
    token = employee["version"]

    validate_error(
        api_client.create_policy_exception(
            create_policy_exception_payload(
                version["id"],
                token,
                reason_code="MEDICAL",
                justification="Extended medical absence",
                requested_days=30,
            ),
            make_employee_headers(employee["id"]),
        ),
        ApiErrorId.ERR_NO_PENDING_ASSIGNMENT,
    )

    _rows, meta = validate_paginated(
        api_client.list_policy_exceptions(
            make_admin_headers(), params={"employee_id": employee["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, (
        f"a refused request must append no exception row, got {meta['total_count']}"
    )
    stored = refresh_employee(employee["id"])
    assert stored["version"] == token, (
        "the refused request must not have consumed the employee's version token, "
        f"expected {token}, got {stored['version']}"
    )
    assert stored["open_ack_count"] == 0, (
        f"the employee holds no obligations, got {stored['open_ack_count']}"
    )
