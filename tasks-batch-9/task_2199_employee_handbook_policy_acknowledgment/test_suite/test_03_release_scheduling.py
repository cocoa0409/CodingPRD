"""Release-package scheduling: lead time, the deadline formula and window overlap."""
from test_helpers import (
    ApiErrorId,
    add_item,
    api_client,
    assert_same_instant,
    decide_review_as,
    make_admin_headers,
    make_localizer_headers,
    new_jurisdiction,
    new_package,
    refresh_package,
    schedule_package,
    set_clock,
    setup_approved_version,
    start_review_as,
    validate_error,
    validate_success,
)


def test_legal_review_deadline_uses_scope_wide_base_days_and_ample_slack_buffer():
    """PRD §3.6: "Step one: the **base days** is the largest
    `min_legal_review_days` among all jurisdictions named in the package's
    `scope_jurisdiction_ids` — all of them, regardless of whether any item
    version lists them as required. Step two: the **lead days** is the whole-day,
    floor-truncated difference from the logical clock at the instant of
    scheduling to the package's `effective_date`; the **slack days** is the lead
    days minus the base days; and the **buffer days** is 7 when the slack days is
    0 or negative, 3 when the slack days is between 1 and 9 inclusive, and 1 when
    the slack days is 10 or more. Step three: `legal_review_deadline` is the
    package's `effective_date` minus the sum of the base days and the buffer
    days, in whole days."

    Design: Difficulty/combinatorial_formula/legal_review_deadline_three_step_order_no_rederivation
    """
    ctx = setup_approved_version(jurisdiction={"min_legal_review_days": 10})
    ca = ctx["jurisdiction"]
    tx = new_jurisdiction(min_legal_review_days=20)

    package = new_package([ca["id"], tx["id"]], "2026-09-19T00:00:00Z")
    add_item(package["id"], ctx["version"]["id"])
    set_clock("2026-08-10T00:00:00Z")

    scheduled = validate_success(
        api_client.schedule_release_package(package["id"], make_admin_headers())
    )

    assert scheduled["status"] == "SCHEDULED", (
        f"the package must reach SCHEDULED, got {scheduled['status']}"
    )
    assert_same_instant(scheduled["scheduled_at"], "2026-08-10T00:00:00Z", "scheduled_at")
    assert_same_instant(
        scheduled["legal_review_deadline"],
        "2026-08-29T00:00:00.000Z",
        "legal_review_deadline",
    )


def test_legal_review_deadline_takes_the_mid_range_buffer_for_nine_days_of_slack():
    """PRD §3.6: "the **slack days** is the lead days minus the base days; and
    the **buffer days** is 7 when the slack days is 0 or negative, 3 when the
    slack days is between 1 and 9 inclusive, and 1 when the slack days is 10 or
    more. Step three: `legal_review_deadline` is the package's `effective_date`
    minus the sum of the base days and the buffer days, in whole days. The buffer
    is derived from the slack, which is derived from the base days alone; it must
    never be re-derived from the resulting deadline, which would itself shift the
    slack."

    Design: Difficulty/combinatorial_formula/legal_review_deadline_three_step_order_no_rederivation
    """
    ctx = setup_approved_version(jurisdiction={"min_legal_review_days": 10})

    package = new_package([ctx["jurisdiction"]["id"]], "2026-08-20T00:00:00Z")
    add_item(package["id"], ctx["version"]["id"])

    scheduled = schedule_package(package["id"])

    assert scheduled["status"] == "SCHEDULED"
    assert_same_instant(scheduled["scheduled_at"], "2026-08-01T00:00:00Z", "scheduled_at")
    assert_same_instant(
        scheduled["legal_review_deadline"],
        "2026-08-07T00:00:00.000Z",
        "legal_review_deadline",
    )


def _approved_version_decided_on(decided_on, min_legal_review_days=10):
    """An APPROVED, fully rendered version whose single legal review carries a
    `decided_at` at exactly `decided_on` (the clock is advanced mid-review)."""
    from test_helpers import (
        approve_version,
        drive_version_to_in_legal_review,
        mint_version,
        new_document,
        new_reviewer,
        publish_translation,
        refresh_review,
    )

    jurisdiction = new_jurisdiction(min_legal_review_days=min_legal_review_days)
    reviewer = new_reviewer(jurisdiction["id"])
    document = new_document()
    version = mint_version(document, [jurisdiction["id"]])
    version, _addenda, reviews = drive_version_to_in_legal_review(
        version, [(jurisdiction["id"], reviewer["id"])]
    )
    review = reviews[jurisdiction["id"]]
    set_clock(decided_on)
    start_review_as(review["id"], reviewer["id"])
    decide_review_as(review["id"], reviewer["id"], "APPROVE")
    assert_same_instant(
        refresh_review(review["id"])["decided_at"], decided_on, "review.decided_at"
    )
    version = approve_version(version["id"])
    publish_translation(version["id"])
    return jurisdiction, version


def test_lead_time_passes_when_effective_date_equals_decision_plus_min_days():
    """PRD §3.6: "For every item version and for every jurisdiction that appears
    both in the package's `scope_jurisdiction_ids` and in that version's
    `required_jurisdiction_ids`, take that version's review for that
    jurisdiction, add that jurisdiction's `min_legal_review_days` whole days to
    the review's `decided_at`, and require the result to be earlier than or equal
    to the package's `effective_date`. The bound is inclusive: an exact equality
    passes."

    Design: Difficulty/boundary_precision_check/lead_time_equality_is_inclusive_at_exactly_min_legal_review_days
    """
    jurisdiction, version = _approved_version_decided_on("2026-08-05T00:00:00Z")

    package = new_package([jurisdiction["id"]], "2026-08-15T00:00:00Z")
    add_item(package["id"], version["id"])

    scheduled = schedule_package(package["id"])

    assert scheduled["status"] == "SCHEDULED", (
        "decided_at 2026-08-05 plus 10 whole days equals the effective_date "
        f"2026-08-15, which the inclusive bound admits; got {scheduled['status']}"
    )
    assert_same_instant(scheduled["scheduled_at"], "2026-08-05T00:00:00Z", "scheduled_at")
    assert_same_instant(
        scheduled["legal_review_deadline"],
        "2026-07-29T00:00:00.000Z",
        "legal_review_deadline",
    )


def test_lead_time_refuses_one_day_short_of_min_legal_review_days():
    """PRD §3.6: "add that jurisdiction's `min_legal_review_days` whole days to
    the review's `decided_at`, and require the result to be earlier than or equal
    to the package's `effective_date`" ... "Finally the legal-review lead-time
    rule runs, yielding `ERR_LEGAL_REVIEW_LEAD_TIME_SHORT` (409)."

    Design: Difficulty/boundary_precision_check/lead_time_equality_is_inclusive_at_exactly_min_legal_review_days
    """
    jurisdiction, version = _approved_version_decided_on("2026-08-05T00:00:00Z")

    package = new_package([jurisdiction["id"]], "2026-08-14T00:00:00Z")
    add_item(package["id"], version["id"])

    validate_error(
        api_client.schedule_release_package(package["id"], make_admin_headers()),
        ApiErrorId.ERR_LEGAL_REVIEW_LEAD_TIME_SHORT,
    )

    unchanged = refresh_package(package["id"])
    assert unchanged["status"] == "DRAFT", (
        f"a refused schedule must leave the package in DRAFT, got {unchanged['status']}"
    )
    assert unchanged["scheduled_at"] is None, (
        f"scheduled_at must stay null, got {unchanged['scheduled_at']}"
    )
    assert unchanged["legal_review_deadline"] is None, (
        "legal_review_deadline must stay null when scheduling is refused, got "
        f"{unchanged['legal_review_deadline']}"
    )


def test_scheduling_is_refused_until_the_rendition_track_reaches_published():
    """PRD §3.5: "Scheduling a release requires, for every jurisdiction in the
    release scope and for every language in that jurisdiction's
    `required_language_codes`, a track on each item version with a matching
    `language_code` and a `status` of `PUBLISHED`; a missing rendition is refused
    with `ERR_TRANSLATION_NOT_PUBLISHED` (409)."

    Design: Difficulty/cross_entity_state_dependency/release_scheduling_gated_on_translation_publication_state
    """
    from test_helpers import track_at_a11y_review

    ctx = setup_approved_version(publish_translation_track=False)
    track = track_at_a11y_review(ctx["version"]["id"], "en")
    assert track["status"] == "A11Y_REVIEW"
    assert track["conformance_level"] == "AAA"

    package = new_package([ctx["jurisdiction"]["id"]], "2026-09-01T00:00:00Z")
    add_item(package["id"], ctx["version"]["id"])

    validate_error(
        api_client.schedule_release_package(package["id"], make_admin_headers()),
        ApiErrorId.ERR_TRANSLATION_NOT_PUBLISHED,
    )
    blocked = refresh_package(package["id"])
    assert blocked["status"] == "DRAFT", (
        f"a refused schedule must leave the package in DRAFT, got {blocked['status']}"
    )
    assert blocked["scheduled_at"] is None

    published = validate_success(
        api_client.publish_translation(track["id"], make_localizer_headers())
    )
    assert published["status"] == "PUBLISHED"

    scheduled = validate_success(
        api_client.schedule_release_package(package["id"], make_admin_headers())
    )
    assert scheduled["status"] == "SCHEDULED", (
        "the very same schedule request must succeed once the rendition is "
        f"PUBLISHED, got {scheduled['status']}"
    )
    assert_same_instant(scheduled["scheduled_at"], "2026-08-01T00:00:00Z", "scheduled_at")


def test_scheduling_requires_every_required_language_of_the_scope_jurisdiction():
    """PRD §3.5: "Scheduling a release requires, for every jurisdiction in the
    release scope and for every language in that jurisdiction's
    `required_language_codes`, a track on each item version with a matching
    `language_code` and a `status` of `PUBLISHED`; a missing rendition is refused
    with `ERR_TRANSLATION_NOT_PUBLISHED` (409)."

    Design: Difficulty/cross_entity_state_dependency/release_scheduling_gated_on_translation_publication_state
    """
    ctx = setup_approved_version(
        jurisdiction={"required_language_codes": ["en", "es"]},
        publish_translation_track=True,
        language_code="en",
    )
    assert ctx["translation"]["status"] == "PUBLISHED"
    assert ctx["jurisdiction"]["required_language_codes"] == ["en", "es"]

    package = new_package([ctx["jurisdiction"]["id"]], "2026-09-01T00:00:00Z")
    add_item(package["id"], ctx["version"]["id"])

    validate_error(
        api_client.schedule_release_package(package["id"], make_admin_headers()),
        ApiErrorId.ERR_TRANSLATION_NOT_PUBLISHED,
    )
    assert refresh_package(package["id"])["status"] == "DRAFT"


def test_release_state_gate_is_reported_before_the_unreached_effective_date():
    """PRD §3.6: "It moves the package `SCHEDULED → RELEASED`, requires the
    package to be in `SCHEDULED` (`ERR_RELEASE_NOT_SCHEDULED`), requires
    `expected_release_package_version` to match the package's current `version` as
    described in §2.6, requires the logical clock to have reached or passed the
    package's `effective_date` — a clock strictly earlier than the effective date
    is refused with `ERR_EFFECTIVE_DATE_NOT_REACHED` (409)".

    Design: Difficulty/priority_pair_validation_conflict/release_state_gate_outranks_effective_date_not_reached
    """
    from test_helpers import assignments_of

    ctx = setup_approved_version()
    package = new_package([ctx["jurisdiction"]["id"]], "2026-09-01T00:00:00Z")
    add_item(package["id"], ctx["version"]["id"])
    current = refresh_package(package["id"])
    assert current["status"] == "DRAFT"

    validate_error(
        api_client.release_release_package(
            package["id"],
            {"expected_release_package_version": current["version"]},
            make_admin_headers(),
        ),
        ApiErrorId.ERR_RELEASE_NOT_SCHEDULED,
    )

    unchanged = refresh_package(package["id"])
    assert unchanged["status"] == "DRAFT", (
        f"a refused release must leave the package in DRAFT, got {unchanged['status']}"
    )
    assert unchanged["released_at"] is None, (
        f"released_at must stay null, got {unchanged['released_at']}"
    )
    assert unchanged["roster_snapshot_size"] == 0, (
        "a refused release must mint no roster, so roster_snapshot_size stays 0, got "
        f"{unchanged['roster_snapshot_size']}"
    )
    assert assignments_of(package["id"]) == [], (
        "a refused release must mint no assignments"
    )


def test_cancelled_package_release_reports_the_state_gate_not_the_clock():
    """PRD §3.6: "requires the package to be in `SCHEDULED`
    (`ERR_RELEASE_NOT_SCHEDULED`), requires `expected_release_package_version` to
    match the package's current `version` as described in §2.6, requires the
    logical clock to have reached or passed the package's `effective_date` — a
    clock strictly earlier than the effective date is refused with
    `ERR_EFFECTIVE_DATE_NOT_REACHED` (409)".

    Design: Difficulty/priority_pair_validation_conflict/release_state_gate_outranks_effective_date_not_reached
    """
    ctx = setup_approved_version()
    package = new_package([ctx["jurisdiction"]["id"]], "2026-09-01T00:00:00Z")
    add_item(package["id"], ctx["version"]["id"])
    schedule_package(package["id"])
    cancelled = validate_success(
        api_client.cancel_release_package(package["id"], make_admin_headers())
    )
    assert cancelled["status"] == "CANCELLED"

    validate_error(
        api_client.release_release_package(
            package["id"],
            {"expected_release_package_version": cancelled["version"]},
            make_admin_headers(),
        ),
        ApiErrorId.ERR_RELEASE_NOT_SCHEDULED,
    )
    assert refresh_package(package["id"])["status"] == "CANCELLED"
    assert refresh_package(package["id"])["released_at"] is None


def _document_with_two_published_generations():
    """One document, no employees anywhere: v1 published on 2026-08-10 then
    superseded by v2 published on 2026-08-20, plus a third APPROVED version v3
    waiting for a slot.  The clock ends at 2026-08-20."""
    from test_helpers import (
        add_approved_version_to_document,
        refresh_version,
        released_package_for,
    )

    ctx = setup_approved_version(jurisdiction={"min_legal_review_days": 5})
    jurisdiction, reviewer, document = (
        ctx["jurisdiction"], ctx["reviewer"], ctx["document"]
    )
    v1 = ctx["version"]
    released_package_for([v1["id"]], [jurisdiction["id"]], "2026-08-10T00:00:00Z")

    v2 = add_approved_version_to_document(document, jurisdiction["id"], reviewer["id"])
    released_package_for([v2["id"]], [jurisdiction["id"]], "2026-08-20T00:00:00Z")

    v1 = refresh_version(v1["id"])
    assert v1["status"] == "SUPERSEDED"
    assert_same_instant(v1["window_end_date"], "2026-08-20T00:00:00Z", "window_end_date")

    v3 = add_approved_version_to_document(document, jurisdiction["id"], reviewer["id"])
    return jurisdiction, document, v1, v2, v3


def test_candidate_inside_a_superseded_window_is_refused_as_an_overlap():
    """PRD §3.6: "Clause (a): the candidate `effective_date` must not fall inside
    the half-open occupied window of any sibling whose `status` is `SUPERSEDED` —
    that window starts at the sibling's `effective_date` inclusive and ends at the
    sibling's `window_end_date` exclusive." ... "Then the effective-window overlap
    rule described below runs, yielding `ERR_EFFECTIVE_WINDOW_OVERLAP` (409). Then
    the `effective_date` must be strictly later than the logical clock, or the
    attempt is refused with `ERR_EFFECTIVE_DATE_IN_PAST` (409)".

    Design: Difficulty/resource_temporal_overlap/policy_document_effective_window_half_open_adjacency_permitted
    """
    jurisdiction, document, v1, v2, v3 = _document_with_two_published_generations()

    package = new_package([jurisdiction["id"]], "2026-08-15T00:00:00Z")
    add_item(package["id"], v3["id"])

    validate_error(
        api_client.schedule_release_package(package["id"], make_admin_headers()),
        ApiErrorId.ERR_EFFECTIVE_WINDOW_OVERLAP,
    )
    blocked = refresh_package(package["id"])
    assert blocked["status"] == "DRAFT", (
        f"a refused schedule must leave the package in DRAFT, got {blocked['status']}"
    )
    assert blocked["scheduled_at"] is None


def test_superseded_window_includes_its_lower_edge_and_admits_a_later_slot():
    """PRD §3.6: "that window starts at the sibling's `effective_date` inclusive
    and ends at the sibling's `window_end_date` exclusive." ... "Clause (b): when a
    sibling of the same document has `status` `PUBLISHED`, its window is
    open-ended, and the candidate `effective_date` must be strictly greater than
    that sibling's `effective_date`."

    Design: Difficulty/resource_temporal_overlap/policy_document_effective_window_half_open_adjacency_permitted
    """
    jurisdiction, document, v1, v2, v3 = _document_with_two_published_generations()

    on_edge = new_package([jurisdiction["id"]], "2026-08-10T00:00:00Z")
    add_item(on_edge["id"], v3["id"])
    validate_error(
        api_client.schedule_release_package(on_edge["id"], make_admin_headers()),
        ApiErrorId.ERR_EFFECTIVE_WINDOW_OVERLAP,
    )
    assert refresh_package(on_edge["id"])["status"] == "DRAFT", (
        "the superseded window's lower edge is inclusive, so a candidate exactly on "
        "it overlaps and the package must stay in DRAFT"
    )

    later = new_package([jurisdiction["id"]], "2026-09-05T00:00:00Z")
    add_item(later["id"], v3["id"])
    scheduled = schedule_package(later["id"])
    assert scheduled["status"] == "SCHEDULED", (
        "a candidate strictly after the PUBLISHED sibling's effective_date clears "
        f"both clauses, got {scheduled['status']}"
    )
    assert_same_instant(
        scheduled["legal_review_deadline"],
        "2026-08-30T00:00:00.000Z",
        "legal_review_deadline",
    )
