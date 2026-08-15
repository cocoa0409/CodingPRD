"""Script governance: authoring, review, publication chain, supersession cascade,
and self-help resource currency (PRD §2.2, §2.3, §3.2, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equal,
    assert_rights_script,
    author_submit_publish_script,
    create_counselor,
    create_jurisdiction,
    create_script_payload,
    create_self_help_resource,
    get_case,
    get_referral,
    get_resource,
    get_script,
    make_counselor_headers,
    move_case_in_progress,
    open_case,
    propose_self_help_referral,
    set_clock,
    setup_hotline,
    start_active_session,
    validate_error,
    validate_paginated,
    validate_success,
)


def _author_and_reviewer(jur):
    author = create_counselor(display_name="Author A", is_script_reviewer=False)
    reviewer = create_counselor(display_name="Reviewer R", is_script_reviewer=True)
    return author, reviewer


def test_script_author_stamped(api):
    """PRD §3.2: "The new script is born `DRAFT`, and `author_counselor_id` is taken
    from the author's `X-User-ID`."

    Design: Corner/entities/script_author_stamped
    """
    jur = create_jurisdiction()
    author = create_counselor(display_name="Author A")
    resp = api.create_script(
        create_script_payload(jur["id"], "EVICTION", version_no=1, body="script v1"),
        make_counselor_headers(author["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert_rights_script(data)
    assert data["author_counselor_id"] == author["id"]
    assert data["status"] == "DRAFT"
    assert data.get("reviewer_counselor_id") is None


def test_script_publish_valid_transition(api):
    """PRD §3.2: "A successful publish writes `reviewer_counselor_id` from the
    publisher's `X-User-ID` and sets the script `PUBLISHED`."
    PRD §3.2: "Only the author can submit a draft for review, moving it `DRAFT` →
    `IN_REVIEW` (an actor whose `X-User-ID` differs from `author_counselor_id` is
    rejected with `ERR_FORBIDDEN`)."

    Design: Corner/state_machines/script_publish_valid_transition
    """
    jur = create_jurisdiction()
    author, reviewer = _author_and_reviewer(jur)
    script = validate_success(api.create_script(
        create_script_payload(jur["id"], "EVICTION", version_no=1, body="script v1"),
        make_counselor_headers(author["id"]),
    ), expected_status=201)

    submitted = validate_success(api.transition_script(
        script["id"], {"to_status": "IN_REVIEW"}, make_counselor_headers(author["id"])
    ))
    assert submitted["status"] == "IN_REVIEW"

    published = validate_success(api.transition_script(
        script["id"],
        {"to_status": "PUBLISHED", "effective_from": "2026-08-01T00:00:00Z"},
        make_counselor_headers(reviewer["id"]),
    ))
    assert published["status"] == "PUBLISHED"
    assert_instant_equal(published["effective_from"], "2026-08-01T00:00:00Z",
                         "effective_from")
    assert published["reviewer_counselor_id"] == reviewer["id"]


def test_script_draft_to_published_rejected(api):
    """PRD §2.10: "The requested transition must be listed for the resource's
    current state, terminal states reject everything, a session cannot go active
    while an interpreter request is pending, a case can only be opened from a
    session that is active or wrapped up, notes and referrals attach only to cases
    in an open counseling state, and manual escalation is reserved for critical
    cases — otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/script_draft_to_published_rejected
    """
    jur = create_jurisdiction()
    author, reviewer = _author_and_reviewer(jur)
    script = validate_success(api.create_script(
        create_script_payload(jur["id"], "EVICTION", version_no=1, body="script v1"),
        make_counselor_headers(author["id"]),
    ), expected_status=201)

    # DRAFT -> PUBLISHED is not a listed edge, even for a qualified reviewer who
    # is not the author.
    resp = api.transition_script(
        script["id"],
        {"to_status": "PUBLISHED", "effective_from": "2026-08-01T00:00:00Z"},
        make_counselor_headers(reviewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = validate_success(
        api.get_script(script["id"], make_counselor_headers(author["id"]))
    )
    assert current["status"] == "DRAFT"


def test_counselor_cannot_publish_own_script(api):
    """PRD §3.2: "The publisher must hold `is_script_reviewer` and must not be the
    author — segregation of duties, enforced as `ERR_SCRIPT_REVIEWER_CONFLICT`."

    Design: Corner/rbac/counselor_cannot_publish_own_script
    """
    jur = create_jurisdiction()
    author = create_counselor(display_name="Author A", is_script_reviewer=True)
    script = validate_success(api.create_script(
        create_script_payload(jur["id"], "EVICTION", version_no=1, body="script v1"),
        make_counselor_headers(author["id"]),
    ), expected_status=201)
    validate_success(api.transition_script(
        script["id"], {"to_status": "IN_REVIEW"}, make_counselor_headers(author["id"])
    ))

    resp = api.transition_script(
        script["id"],
        {"to_status": "PUBLISHED", "effective_from": "2026-08-01T00:00:00Z"},
        make_counselor_headers(author["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SCRIPT_REVIEWER_CONFLICT)
    current = validate_success(
        api.get_script(script["id"], make_counselor_headers(author["id"]))
    )
    assert current["status"] == "IN_REVIEW"


def test_duplicate_published_script_rejected(api):
    """PRD §3.2: "When `supersedes_script_id` is null, `version_no` must be 1 and no
    other `PUBLISHED` script may exist for the pair, or the publish fails with
    `ERR_DUPLICATE_PUBLISHED_SCRIPT`."

    Design: Corner/validations/duplicate_published_script_rejected
    """
    bundle = setup_hotline()
    s1 = bundle["script"]
    assert s1["status"] == "PUBLISHED"

    rogue = validate_success(api.create_script(
        create_script_payload(bundle["jurisdiction"]["id"], "EVICTION",
                              version_no=1, body="rogue v1"),
        bundle["author_headers"],
    ), expected_status=201)
    validate_success(api.transition_script(
        rogue["id"], {"to_status": "IN_REVIEW"}, bundle["author_headers"]
    ))
    resp = api.transition_script(
        rogue["id"],
        {"to_status": "PUBLISHED", "effective_from": "2026-08-01T00:00:00Z"},
        bundle["reviewer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PUBLISHED_SCRIPT)
    current = get_script(bundle, s1["id"])
    assert current["status"] == "PUBLISHED"


def test_version_chain_broken_rejected(api):
    """PRD §3.2: "When `supersedes_script_id` is set, its target must be `PUBLISHED`
    at publish time, must belong to the same (`jurisdiction_id`, `issue_category`)
    pair, and the new `version_no` must be exactly one greater than the target's —
    a chain break is rejected with `ERR_SCRIPT_VERSION_CHAIN_BROKEN`."

    Design: Corner/validations/version_chain_broken_rejected
    """
    bundle = setup_hotline()
    s1 = bundle["script"]
    set_clock("2026-08-01T01:00:00Z")
    gap = validate_success(api.create_script(
        create_script_payload(bundle["jurisdiction"]["id"], "EVICTION",
                              version_no=3, body="script v3-gap",
                              supersedes_script_id=s1["id"]),
        bundle["author_headers"],
    ), expected_status=201)
    validate_success(api.transition_script(
        gap["id"], {"to_status": "IN_REVIEW"}, bundle["author_headers"]
    ))
    resp = api.transition_script(
        gap["id"],
        {"to_status": "PUBLISHED", "effective_from": "2026-08-01T01:00:00Z"},
        bundle["reviewer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SCRIPT_VERSION_CHAIN_BROKEN)
    current = get_script(bundle, s1["id"])
    assert current["status"] == "PUBLISHED"


def test_script_superseded_terminal_lockdown(api):
    """PRD §3.2: "`SUPERSEDED` and `RETIRED` are terminal."
    PRD §2.9: "Terminal states are absolute: a resource in a terminal state rejects
    every further transition, and a call session reaching a terminal state freezes
    both of its status dimensions."

    Design: Corner/state_machines/script_superseded_terminal_lockdown
    """
    bundle = setup_hotline()
    s1 = bundle["script"]
    set_clock("2026-08-01T01:00:00Z")
    author_submit_publish_script(
        bundle["jurisdiction"]["id"], "EVICTION",
        bundle["author"]["id"], bundle["reviewer"]["id"],
        effective_from="2026-08-01T01:00:00Z", version_no=2,
        supersedes_script_id=s1["id"], body="script v2",
    )
    resp = api.transition_script(
        s1["id"], {"to_status": "RETIRED"}, TEST_USERS["supervisor_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_script(bundle, s1["id"])
    assert current["status"] == "SUPERSEDED"
    assert_instant_equal(current["effective_until"], "2026-08-01T01:00:00Z",
                         "effective_until")


def _publish_cascade_scene(api):
    """v1 published + linked resource + PROPOSED self-help referral; then v2
    published at 2026-08-01T01:00:00Z superseding v1."""
    bundle = setup_hotline()
    s1 = bundle["script"]
    resource = create_self_help_resource(bundle, s1["id"], title="Eviction FAQ")
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    case = move_case_in_progress(bundle, case)
    referral = propose_self_help_referral(bundle, case["id"], resource["id"])
    set_clock("2026-08-01T01:00:00Z")
    s2 = author_submit_publish_script(
        bundle["jurisdiction"]["id"], "EVICTION",
        bundle["author"]["id"], bundle["reviewer"]["id"],
        effective_from="2026-08-01T01:00:00Z", version_no=2,
        supersedes_script_id=s1["id"], body="script v2",
    )
    return bundle, s1, resource, case, referral, s2


def test_publish_cascade_supersedes_predecessor_and_outdates_resources(api):
    """PRD §3.2: "The cascade then runs in three links: the superseded script (if
    any) moves to `SUPERSEDED` with its `effective_until` set to the new script's
    `effective_from`; every self-help resource still `CURRENT` whose
    `linked_script_id` names the superseded script becomes `OUTDATED`; and every
    referral still `PROPOSED` that references one of those newly outdated resources
    is `CANCELLED` with `cancel_reason` `SCRIPT_OUTDATED`."

    Design: Difficulty/transitive_cascade/script_publish_cascade
    """
    bundle, s1, resource, case, referral, s2 = _publish_cascade_scene(api)

    assert s2["status"] == "PUBLISHED"
    assert_instant_equal(s2["effective_from"], "2026-08-01T01:00:00Z",
                         "v2 effective_from")
    old = get_script(bundle, s1["id"])
    assert old["status"] == "SUPERSEDED"
    assert_instant_equal(old["effective_until"], "2026-08-01T01:00:00Z",
                         "v1 effective_until")
    assert_instant_equal(old["effective_until"], s2["effective_from"],
                         "v1 effective_until == v2 effective_from")

    res = get_resource(bundle, resource["id"])
    assert res["status"] == "OUTDATED", (
        "resource linked to the superseded script must flip OUTDATED by cascade"
    )


def test_publish_cascade_cancels_proposed_referrals(api):
    """PRD §3.2: "The cascade then runs in three links: the superseded script (if
    any) moves to `SUPERSEDED` with its `effective_until` set to the new script's
    `effective_from`; every self-help resource still `CURRENT` whose
    `linked_script_id` names the superseded script becomes `OUTDATED`; and every
    referral still `PROPOSED` that references one of those newly outdated resources
    is `CANCELLED` with `cancel_reason` `SCRIPT_OUTDATED`."

    Design: Difficulty/transitive_cascade/script_publish_cascade
    """
    bundle, s1, resource, case, referral, s2 = _publish_cascade_scene(api)

    ref = get_referral(bundle, referral["id"])
    assert ref["status"] == "CANCELLED"
    assert ref["cancel_reason"] == "SCRIPT_OUTDATED"

    current_case = get_case(bundle, case["id"])
    assert current_case["status"] == "IN_PROGRESS", (
        "the cascade's three links do not touch the counseling case"
    )


def _three_version_chain(api):
    """Publish v1 at 08-01, v2 at 08-05, v3 at 08-07 (each superseding)."""
    bundle = setup_hotline()
    s1 = bundle["script"]
    set_clock("2026-08-05T00:00:00Z")
    s2 = author_submit_publish_script(
        bundle["jurisdiction"]["id"], "EVICTION",
        bundle["author"]["id"], bundle["reviewer"]["id"],
        effective_from="2026-08-05T00:00:00Z", version_no=2,
        supersedes_script_id=s1["id"], body="script v2",
    )
    set_clock("2026-08-07T00:00:00Z")
    s3 = author_submit_publish_script(
        bundle["jurisdiction"]["id"], "EVICTION",
        bundle["author"]["id"], bundle["reviewer"]["id"],
        effective_from="2026-08-07T00:00:00Z", version_no=3,
        supersedes_script_id=s2["id"], body="script v3",
    )
    return bundle, s1["id"], s2["id"], s3["id"]


def test_script_chain_singleton_invariant(api):
    """PRD §3.2: "Two invariants are conserved across every publish pair: at most
    one script per (`jurisdiction_id`, `issue_category`) pair is `PUBLISHED` at any
    time, and the half-open windows from `effective_from` (inclusive) to
    `effective_until` (exclusive) across a chain never overlap and never gap — each
    superseded window's `effective_until` equals its successor's `effective_from`."

    Design: Difficulty/compensating_invariant/script_chain_continuity_invariant
    """
    bundle, s1_id, s2_id, s3_id = _three_version_chain(api)
    statuses = {sid: get_script(bundle, sid)["status"] for sid in (s1_id, s2_id, s3_id)}
    assert statuses[s1_id] == "SUPERSEDED"
    assert statuses[s2_id] == "SUPERSEDED"
    assert statuses[s3_id] == "PUBLISHED"
    assert list(statuses.values()).count("PUBLISHED") == 1, (
        "at most one PUBLISHED script per (jurisdiction, category) chain"
    )


def test_script_chain_window_continuity(api):
    """PRD §3.2: "Two invariants are conserved across every publish pair: at most
    one script per (`jurisdiction_id`, `issue_category`) pair is `PUBLISHED` at any
    time, and the half-open windows from `effective_from` (inclusive) to
    `effective_until` (exclusive) across a chain never overlap and never gap — each
    superseded window's `effective_until` equals its successor's `effective_from`."

    Design: Difficulty/compensating_invariant/script_chain_continuity_invariant
    """
    bundle, s1_id, s2_id, s3_id = _three_version_chain(api)
    s1 = get_script(bundle, s1_id)
    s2 = get_script(bundle, s2_id)
    s3 = get_script(bundle, s3_id)

    assert_instant_equal(s1["effective_until"], "2026-08-05T00:00:00Z",
                         "v1 effective_until")
    assert_instant_equal(s1["effective_until"], s2["effective_from"],
                         "v1 end == v2 start")
    assert_instant_equal(s2["effective_until"], "2026-08-07T00:00:00Z",
                         "v2 effective_until")
    assert_instant_equal(s2["effective_until"], s3["effective_from"],
                         "v2 end == v3 start")
    assert s3.get("effective_until") is None, "current head of chain stays open"
    assert_instant_equal(s1["effective_from"], "2026-08-01T00:00:00Z",
                         "v1 effective_from")


def test_listing_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned;
    it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter sets the number of items skipped and defaults to 0. Unless otherwise
    specified, every list endpoint returns its resources sorted by creation
    timestamp in ascending order. The `meta` envelope of a list response carries
    the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/listing_pagination_envelope
    """
    jur = create_jurisdiction()
    author = create_counselor(display_name="Author A")
    headers = make_counselor_headers(author["id"])
    for body in ("d1", "d2", "d3"):
        validate_success(api.create_script(
            create_script_payload(jur["id"], "EVICTION", version_no=1, body=body),
            headers,
        ), expected_status=201)

    page1, meta1 = validate_paginated(
        api.list_scripts(headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_scripts(headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_resource_refresh_cycle(api):
    """PRD §3.3: "An outdated resource is refreshed back to `CURRENT` by supplying a
    new `linked_script_id` naming a `PUBLISHED` script for the resource's own
    (`jurisdiction_id`, `issue_category`) pair — `ERR_SCRIPT_NOT_PUBLISHED` if none
    qualifies — which updates `linked_script_id` in place."

    Design: Corner/state_machines/resource_refresh_cycle
    """
    bundle = setup_hotline()
    s1 = bundle["script"]
    resource = create_self_help_resource(bundle, s1["id"], title="Eviction FAQ")
    set_clock("2026-08-01T01:00:00Z")
    s2 = author_submit_publish_script(
        bundle["jurisdiction"]["id"], "EVICTION",
        bundle["author"]["id"], bundle["reviewer"]["id"],
        effective_from="2026-08-01T01:00:00Z", version_no=2,
        supersedes_script_id=s1["id"], body="script v2",
    )
    assert get_resource(bundle, resource["id"])["status"] == "OUTDATED"

    s3 = validate_success(api.create_script(
        create_script_payload(bundle["jurisdiction"]["id"], "EVICTION",
                              version_no=3, body="script v3 draft",
                              supersedes_script_id=s2["id"]),
        bundle["author_headers"],
    ), expected_status=201)

    # Refresh onto a still-DRAFT script fails.
    bad = api.transition_self_help_resource(
        resource["id"], {"to_status": "CURRENT", "linked_script_id": s3["id"]},
        bundle["worker_headers"],
    )
    validate_error(bad, ApiErrorId.ERR_SCRIPT_NOT_PUBLISHED)

    # Refresh onto the currently PUBLISHED script completes the cycle.
    good = validate_success(api.transition_self_help_resource(
        resource["id"], {"to_status": "CURRENT", "linked_script_id": s2["id"]},
        bundle["worker_headers"],
    ))
    assert good["status"] == "CURRENT"
    assert good["linked_script_id"] == s2["id"]


def test_resource_outdated_referral_rejected(api):
    """PRD §3.8: "For a self-help referral, the resource must be `CURRENT`; an
    `OUTDATED` or `RETIRED` resource fails with `ERR_RESOURCE_OUTDATED`."

    Design: Corner/validations/resource_outdated_referral_rejected
    """
    bundle = setup_hotline()
    s1 = bundle["script"]
    resource = create_self_help_resource(bundle, s1["id"], title="FAQ")
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    case = move_case_in_progress(bundle, case)

    set_clock("2026-08-01T01:00:00Z")
    author_submit_publish_script(
        bundle["jurisdiction"]["id"], "EVICTION",
        bundle["author"]["id"], bundle["reviewer"]["id"],
        effective_from="2026-08-01T01:00:00Z", version_no=2,
        supersedes_script_id=s1["id"], body="script v2",
    )
    assert get_resource(bundle, resource["id"])["status"] == "OUTDATED"

    current = get_case(bundle, case["id"])
    resp = api.create_referral(
        case["id"],
        {"referral_type": "SELF_HELP", "self_help_resource_id": resource["id"],
         "expected_case_version": current["version"]},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_OUTDATED)
    referrals = validate_success(api.list_referrals(bundle["worker_headers"]))
    assert referrals == [], "rejected proposal creates no referral row"


def test_immediate_consistency_read_after_write(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §2.6: "A successful guarded write itself advances the parent's `version` by
    one."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    bundle = setup_hotline()
    # The just-published script is immediately readable in its new state.
    script = get_script(bundle, bundle["script"]["id"])
    assert script["status"] == "PUBLISHED"
    assert script["reviewer_counselor_id"] == bundle["reviewer"]["id"]

    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    case = move_case_in_progress(bundle, case)
    observed_version = case["version"]

    validate_success(api.create_case_note(
        case["id"],
        {"body": "sync check", "is_confidential": False,
         "expected_case_version": observed_version},
        bundle["worker_headers"],
    ), expected_status=201)
    after = get_case(bundle, case["id"])
    assert after["version"] == observed_version + 1, (
        "the guarded note write's version bump is visible on the very next read"
    )
