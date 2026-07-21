"""Subscription billing lifecycle, the thirty-day grace window and the release-slot economy."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_subscription, set_clock, create_plan, create_artist,
    create_pending_subscription, create_active_subscription, activate_subscription,
    lapse_subscription, expire_subscription, create_release, add_track,
    read_subscription, read_release, submit_release, CLOCK_BASE, upc, isrc,
    make_admin_headers, make_artist_headers,
)


def _artist_on_plan(plan_kwargs=None, email="artist@example.com"):
    set_clock(CLOCK_BASE)
    plan = create_plan(**(plan_kwargs or {}))
    artist = create_artist(email=email)
    return plan, artist


def test_subscription_starts_in_pending_initial_state(api, admin_headers):
    """PRD §3.2: "The subscription is born in `PENDING` with `releases_used` at 0, `activated_at`
    null and `past_due_since` null."

    Design: Corner/state_machines/subscription_starts_in_pending_initial_state
    """
    plan, artist = _artist_on_plan(email="vela@example.com")

    sub = validate_success(
        api.create_subscription({"artist_id": artist["id"], "plan_id": plan["id"],
                                 "auto_renew": True}, admin_headers),
        201,
    )

    assert_subscription(sub)
    assert sub["status"] == "PENDING"
    assert sub["activated_at"] is None
    assert sub["past_due_since"] is None
    assert sub["releases_used"] == 0


def test_subscription_cycles_active_past_due_active_and_clears_grace_marker(api, admin_headers):
    """PRD §3.2: "When billing fails, a `PlatformAdmin` lapses the subscription: `ACTIVE →
    PAST_DUE` stamps `past_due_since` with the current instant and advances `version`."
    PRD §3.2: "From `PAST_DUE` the same activation operation restores the subscription —
    `PAST_DUE → ACTIVE` again stamps `activated_at`, again clears `past_due_since`, and again
    advances `version`, so a subscription may cycle between `ACTIVE` and `PAST_DUE` indefinitely."

    Design: Corner/state_machines/subscription_cycles_active_past_due_active_and_clears_grace_marker
    """
    plan, artist = _artist_on_plan(email="horo@example.com")
    sub = create_active_subscription(artist["id"], plan["id"])
    lapsed = lapse_subscription(sub["id"])
    assert lapsed["status"] == "PAST_DUE"
    assert lapsed["past_due_since"].startswith("2026-07-01T00:00:00")

    set_clock("2026-07-10T00:00:00Z")
    restored = validate_success(
        api.activate_subscription(sub["id"], "pay-horo-2", admin_headers)
    )

    assert restored["status"] == "ACTIVE"
    assert restored["past_due_since"] is None
    assert restored["activated_at"].startswith("2026-07-10T00:00:00")


def test_expired_subscription_blocks_release_submit(api):
    """PRD §3.2: "A `PAST_DUE` subscription may be expired, taking it to `EXPIRED`."
    PRD §3.2: "A subscription that is `PENDING`, `EXPIRED`, `CANCELLED`, or `PAST_DUE` beyond that
    thirty-day window, fails this gate with `ERR_SUBSCRIPTION_INACTIVE` (HTTP 402)."

    Design: Corner/state_machines/expired_subscription_blocks_release_submit_outside_grace
    """
    plan, artist = _artist_on_plan(email="reti@example.com")
    sub = create_active_subscription(artist["id"], plan["id"])
    release = create_release(artist["id"], title="Net", upc=upc(1))
    add_track(release["id"], artist["id"], title="Mesh", isrc=isrc(1))
    lapse_subscription(sub["id"])
    expired = expire_subscription(sub["id"])
    assert expired["status"] == "EXPIRED"

    resp = api.submit_release(release["id"], make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_INACTIVE.value)

    assert read_release(release["id"], artist["id"])["status"] == "DRAFT"
    assert read_subscription(sub["id"])["releases_used"] == 0


def test_submit_inside_thirty_day_grace_window_is_permitted(api):
    """PRD §3.2: "The first is entitlement: the artist's subscription must be `ACTIVE`, or else
    `PAST_DUE` with the current instant strictly earlier than thirty days after `past_due_since` —
    the grace window during which submissions remain permitted."

    Design: Difficulty/cross_entity_state_dependency/release_submit_allowed_while_subscription_past_due_inside_grace
    """
    plan, artist = _artist_on_plan(email="lepus@example.com")
    sub = create_active_subscription(artist["id"], plan["id"])
    lapse_subscription(sub["id"])
    release = create_release(artist["id"], title="Hare", upc=upc(1))
    add_track(release["id"], artist["id"], title="Leap", isrc=isrc(1))

    set_clock("2026-07-30T00:00:00Z")
    submitted = validate_success(
        api.submit_release(release["id"], make_artist_headers(artist["id"]))
    )

    assert submitted["status"] == "SUBMITTED", "29 days after past_due_since is inside the window"
    sub_now = read_subscription(sub["id"])
    assert sub_now["status"] == "PAST_DUE"
    assert sub_now["past_due_since"].startswith("2026-07-01T00:00:00")
    assert sub_now["releases_used"] == 1


def test_submit_at_exactly_thirty_days_past_due_is_refused(api):
    """PRD §3.2: "The first is entitlement: the artist's subscription must be `ACTIVE`, or else
    `PAST_DUE` with the current instant strictly earlier than thirty days after `past_due_since` —
    the grace window during which submissions remain permitted."
    PRD §3.2: "A subscription that is `PENDING`, `EXPIRED`, `CANCELLED`, or `PAST_DUE` beyond that
    thirty-day window, fails this gate with `ERR_SUBSCRIPTION_INACTIVE` (HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/release_submit_allowed_while_subscription_past_due_inside_grace
    """
    plan, artist = _artist_on_plan(email="lepus2@example.com")
    sub = create_active_subscription(artist["id"], plan["id"])
    lapse_subscription(sub["id"])
    release = create_release(artist["id"], title="Doe", upc=upc(2))
    add_track(release["id"], artist["id"], title="Bound", isrc=isrc(2))

    set_clock("2026-07-31T00:00:00Z")
    resp = api.submit_release(release["id"], make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_INACTIVE.value)

    assert read_release(release["id"], artist["id"])["status"] == "DRAFT"
    assert read_subscription(sub["id"])["releases_used"] == 0


def test_submit_then_withdraw_restores_the_release_slot_count(api):
    """PRD §3.2: "`releases_used` is a derived count, never an input, and it is defined
    identically everywhere it is recomputed: it is the number of releases belonging to this
    subscription's artist whose editorial `status` is one of `SUBMITTED`, `IN_REVIEW`, `APPROVED`
    or `LIVE`."
    PRD §3.2: "Because submit and withdraw are exact compensating pairs, the counter returns to
    its prior value whenever an artist reverses a submission."

    Design: Difficulty/compensating_invariant/submit_then_withdraw_conserves_subscription_release_slots
    """
    plan, artist = _artist_on_plan({"code": "DUO", "name": "Duo", "included_release_slots": 2},
                                   email="fornax@example.com")
    sub = create_active_subscription(artist["id"], plan["id"])
    rel_one = create_release(artist["id"], title="One", upc=upc(1))
    add_track(rel_one["id"], artist["id"], title="Kiln", isrc=isrc(1))
    rel_two = create_release(artist["id"], title="Two", upc=upc(2))
    add_track(rel_two["id"], artist["id"], title="Forge", isrc=isrc(2))
    submit_release(rel_one["id"], artist["id"])

    assert read_subscription(sub["id"])["releases_used"] == 1

    validate_success(api.submit_release(rel_two["id"], make_artist_headers(artist["id"])))
    assert read_subscription(sub["id"])["releases_used"] == 2

    validate_success(api.withdraw_release(rel_two["id"], make_artist_headers(artist["id"])))
    assert read_subscription(sub["id"])["releases_used"] == 1, (
        "withdraw exactly undoes the submission"
    )


def test_withdraw_returns_release_to_draft_and_clears_submitted_at(api, admin_headers):
    """PRD §3.5: "From `SUBMITTED` it returns the release to `DRAFT`, clears `submitted_at` back
    to null, recomputes `releases_used` — which falls by one, exactly undoing the submission —
    and advances `version` by 1."

    Design: Difficulty/compensating_invariant/submit_then_withdraw_conserves_subscription_release_slots
    """
    plan, artist = _artist_on_plan({"code": "DUO", "name": "Duo", "included_release_slots": 2},
                                   email="fornax2@example.com")
    create_active_subscription(artist["id"], plan["id"])
    rel_one = create_release(artist["id"], title="One", upc=upc(1))
    add_track(rel_one["id"], artist["id"], title="Kiln", isrc=isrc(1))
    rel_two = create_release(artist["id"], title="Two", upc=upc(2))
    add_track(rel_two["id"], artist["id"], title="Forge", isrc=isrc(2))
    submit_release(rel_one["id"], artist["id"])
    submit_release(rel_two["id"], artist["id"])

    withdrawn = validate_success(
        api.withdraw_release(rel_two["id"], make_artist_headers(artist["id"]))
    )

    assert withdrawn["status"] == "DRAFT"
    assert withdrawn["submitted_at"] is None
    assert read_release(rel_one["id"], artist["id"])["status"] == "SUBMITTED"

    still_submitted, meta = validate_paginated(
        api.list_releases(admin_headers,
                          params={"artist_id": artist["id"], "status": "SUBMITTED"})
    )
    assert meta["total_count"] == 1


def test_submit_on_a_full_plan_is_refused_with_slots_exhausted(api):
    """PRD §3.2: "The second gate is capacity: `releases_used` must be strictly less than the
    plan's `included_release_slots`."
    PRD §3.2: "An artist who already has as many releases in flight as the plan permits is
    refused with `ERR_RELEASE_SLOTS_EXHAUSTED` (HTTP 402)."

    Design: Corner/errors/release_slots_exhausted_error_triggerable
    """
    plan, artist = _artist_on_plan({"code": "SOLO", "name": "Solo", "included_release_slots": 1},
                                   email="lynx@example.com")
    sub = create_active_subscription(artist["id"], plan["id"])
    rel_1 = create_release(artist["id"], title="One", upc=upc(1))
    add_track(rel_1["id"], artist["id"], title="Paw", isrc=isrc(1))
    rel_2 = create_release(artist["id"], title="Two", upc=upc(2))
    add_track(rel_2["id"], artist["id"], title="Claw", isrc=isrc(2))
    submit_release(rel_1["id"], artist["id"])

    resp = api.submit_release(rel_2["id"], make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_RELEASE_SLOTS_EXHAUSTED.value)

    assert read_release(rel_2["id"], artist["id"])["status"] == "DRAFT"
    assert read_subscription(sub["id"])["releases_used"] == 1


def test_resubmitting_a_submitted_release_reports_state_not_slot_exhaustion(api):
    """PRD §2.8: "7. State legality — the target resource is in a state from which the requested
    transition is declared: `ERR_INVALID_STATE`."
    PRD §3.5: "A release may be submitted only from `DRAFT`, and only when it holds at least one
    track; a submission of an empty release, or of a release that is not in `DRAFT`, is refused
    with `ERR_INVALID_STATE`."
    PRD §3.5: "Beyond that, three further conditions apply, evaluated after the state check in the
    global precedence order: the scheduled `release_date` must be at least seven whole days after
    the current instant, otherwise `ERR_RELEASE_DATE_TOO_SOON` (HTTP 422); the artist's
    subscription must be active or inside its thirty-day grace window, otherwise
    `ERR_SUBSCRIPTION_INACTIVE`; and a release slot must remain, otherwise
    `ERR_RELEASE_SLOTS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_resubmitting_an_already_submitted_release
    """
    plan, artist = _artist_on_plan({"code": "SOLO", "name": "Solo", "included_release_slots": 1},
                                   email="cetus@example.com")
    sub = create_active_subscription(artist["id"], plan["id"])
    release = create_release(artist["id"], title="Mira", upc=upc(1))
    add_track(release["id"], artist["id"], title="Wave", isrc=isrc(1))
    submit_release(release["id"], artist["id"])

    resp = api.submit_release(release["id"], make_artist_headers(artist["id"]))
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    assert error["error_id"] != ApiErrorId.ERR_RELEASE_SLOTS_EXHAUSTED.value, (
        "the state check precedes the capacity gate even though both are violated"
    )
    assert read_release(release["id"], artist["id"])["status"] == "SUBMITTED"
    assert read_subscription(sub["id"])["releases_used"] == 1


def test_slot_exhaustion_still_fires_for_a_draft_release_on_the_same_full_plan(api):
    """PRD §3.5: "Beyond that, three further conditions apply, evaluated after the state check in
    the global precedence order: the scheduled `release_date` must be at least seven whole days
    after the current instant, otherwise `ERR_RELEASE_DATE_TOO_SOON` (HTTP 422); the artist's
    subscription must be active or inside its thirty-day grace window, otherwise
    `ERR_SUBSCRIPTION_INACTIVE`; and a release slot must remain, otherwise
    `ERR_RELEASE_SLOTS_EXHAUSTED`."
    PRD §3.2: "An artist who already has as many releases in flight as the plan permits is
    refused with `ERR_RELEASE_SLOTS_EXHAUSTED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_resubmitting_an_already_submitted_release
    """
    plan, artist = _artist_on_plan({"code": "SOLO", "name": "Solo", "included_release_slots": 1},
                                   email="cetus2@example.com")
    sub = create_active_subscription(artist["id"], plan["id"])
    first = create_release(artist["id"], title="Mira", upc=upc(1))
    add_track(first["id"], artist["id"], title="Wave", isrc=isrc(1))
    submit_release(first["id"], artist["id"])

    second = create_release(artist["id"], title="Nova", upc=upc(2))
    add_track(second["id"], artist["id"], title="Crest", isrc=isrc(2))

    resp = api.submit_release(second["id"], make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_RELEASE_SLOTS_EXHAUSTED.value)

    assert read_subscription(sub["id"])["releases_used"] == 1


def test_release_date_must_be_at_least_seven_whole_days_ahead(api):
    """PRD §3.5: "Beyond that, three further conditions apply, evaluated after the state check in
    the global precedence order: the scheduled `release_date` must be at least seven whole days
    after the current instant, otherwise `ERR_RELEASE_DATE_TOO_SOON` (HTTP 422); the artist's
    subscription must be active or inside its thirty-day grace window, otherwise
    `ERR_SUBSCRIPTION_INACTIVE`; and a release slot must remain, otherwise
    `ERR_RELEASE_SLOTS_EXHAUSTED`."

    Design: Corner/errors/release_date_too_soon_error_triggerable
    """
    plan, artist = _artist_on_plan(email="camelo@example.com")
    sub = create_active_subscription(artist["id"], plan["id"])

    early = create_release(artist["id"], title="Early", upc=upc(1),
                           release_date="2026-07-07T00:00:00Z")
    add_track(early["id"], artist["id"], title="Hump", isrc=isrc(1))
    exact = create_release(artist["id"], title="Exact", upc=upc(2),
                           release_date="2026-07-08T00:00:00Z")
    add_track(exact["id"], artist["id"], title="Dune", isrc=isrc(2))

    resp = api.submit_release(early["id"], make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_RELEASE_DATE_TOO_SOON.value)
    assert read_release(early["id"], artist["id"])["status"] == "DRAFT"

    ok = validate_success(api.submit_release(exact["id"], make_artist_headers(artist["id"])))
    assert ok["status"] == "SUBMITTED", "exactly seven whole days ahead is accepted"
    assert read_subscription(sub["id"])["releases_used"] == 1
