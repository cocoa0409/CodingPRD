"""Breaking news: the three-hop bump cascade, the conditional ON_HOLD guard,
the bubble-up resume, and the staffing call-in selector and lifecycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_event,
    add_staff_to,
    create_greenlit_story,
    create_slot,
    declare_and_activate_event,
    declare_event,
    drive_story_to_cleared,
    event_call_ins,
    get_success_data,
    patch_staff,
    propose_and_accept,
    propose_assignment,
    schedule,
    set_clock,
    setup_newsroom,
    validate_error,
    validate_paginated,
    validate_success,
)

ND = TEST_USERS["news_director_headers"]


def _scheduled_story_and_declared_event(api):
    """A STANDARD FEATURES story (desk-forward score 22.00, below the band-2
    bump floor of 60) crewed by one ACCEPTED reporter on [10:00,12:00) and
    SCHEDULED into a PRINT slot; a band-2 event over [09:00,13:00) with an
    empty call-in pool sits DECLARED."""
    ctx = setup_newsroom(copy_editor=True, fact_checker=True,
                         legal_reviewer=True, reporter_desk="FEATURES")
    set_clock("2026-08-01T00:00:00Z")
    _pitch, story_id = create_greenlit_story(
        ctx, title="Park profile", desk="FEATURES",
        deadline_at="2026-08-04T00:00:00Z", urgency="STANDARD")
    asg = propose_and_accept(
        ctx, story_id, "reporter",
        start_at="2026-08-01T10:00:00Z", end_at="2026-08-01T12:00:00Z",
        planned_effort_minutes=120)
    drive_story_to_cleared(ctx, story_id, crew=False)
    slot = create_slot(ctx["desk_headers"],
                       window_start="2026-08-01T18:00:00Z",
                       window_end="2026-08-01T19:00:00Z", capacity=2)
    schedule(ctx, story_id, slot["id"])
    assert get_success_data(api.get_slot(slot["id"], ND))["reserved_count"] == 1
    event = declare_event(title="Bridge collapse", priority_band=2,
                          window_start="2026-08-01T09:00:00Z",
                          window_end="2026-08-01T13:00:00Z",
                          call_in_pool_size=0)
    return ctx, story_id, slot, asg, event


class TestBumpCascade:
    def test_hop1_assignment_bumped_and_linked(self, api):
        """PRD §3.8: "Hop one bumps assignments: every `ACCEPTED` assignment
        whose half-open window intersects the event's window — the
        assignment's `start_at` falls before the event's `window_end` and its
        `end_at` falls after the event's `window_start` — and whose story's
        `priority_score` sits strictly below the bump floor for the event's
        `priority_band` moves to `BUMPED`."
        PRD §3.8: "The floor is 9,999 for band 1 (which clears essentially
        everything in the window), 60 for band 2, and 30 for band 3."
        PRD §3.8: "Each bumped assignment records the event in
        `bumped_by_event_id`, and each affected staff member's
        `active_assignment_count` is recomputed down by one."

        Design: Difficulty/transitive_cascade/breaking_activation_bump_chain
        """
        ctx, story_id, slot, asg, event = \
            _scheduled_story_and_declared_event(api)
        activate_event(event["id"])

        bumped, meta = validate_paginated(
            api.get_event_assignments(event["id"], ND))
        assert meta["total_count"] == 1
        assert bumped[0]["id"] == asg["id"]
        assert bumped[0]["status"] == "BUMPED", \
            "22.00 < 60 and the windows intersect"
        assert bumped[0]["bumped_by_event_id"] == event["id"]

    def test_hops2_and3_story_held_and_slot_released(self, api):
        """PRD §3.8: "Hop two re-evaluates each bumped story: if the story now
        has zero `REPORTER` assignments in `PROPOSED` or `ACCEPTED`, it moves
        from its current pre-publication state — `DRAFT`, `IN_EDIT`,
        `FACT_CHECK`, `LEGAL_REVIEW`, `CLEARED`, or `SCHEDULED` — to
        `ON_HOLD`, incrementing its `version`; §3.3's bubble-up describes how
        a later reporter acceptance resumes it."
        PRD §3.8: "Hop three releases capacity: each such held story that was
        `SCHEDULED` drops its slot — the slot's `reserved_count` falls by one
        and the story's `slot_id` clears."

        Design: Difficulty/transitive_cascade/breaking_activation_bump_chain
        """
        ctx, story_id, slot, asg, event = \
            _scheduled_story_and_declared_event(api)
        activate_event(event["id"])

        story = get_success_data(api.get_story(story_id, ND))
        assert story["status"] == "ON_HOLD", \
            "hop 2: the last active reporter assignment was bumped"
        assert story["slot_id"] is None, "hop 3 cleared the link"
        slot_after = get_success_data(api.get_slot(slot["id"], ND))
        assert slot_after["reserved_count"] == 0, "hop 3 released the slot"
        staff = get_success_data(api.get_staff(ctx["reporter"]["id"], ND))
        assert staff["active_assignment_count"] == 0


class TestBumpIntersectionGuard:
    def test_only_intersecting_assignment_bumps(self, api):
        """PRD §3.8: "Hop one bumps assignments: every `ACCEPTED` assignment
        whose half-open window intersects the event's window — the
        assignment's `start_at` falls before the event's `window_end` and its
        `end_at` falls after the event's `window_start` — and whose story's
        `priority_score` sits strictly below the bump floor for the event's
        `priority_band` moves to `BUMPED`."
        PRD §3.8: "Hop two re-evaluates each bumped story: if the story now
        has zero `REPORTER` assignments in `PROPOSED` or `ACCEPTED`, it moves
        from its current pre-publication state — `DRAFT`, `IN_EDIT`,
        `FACT_CHECK`, `LEGAL_REVIEW`, `CLEARED`, or `SCHEDULED` — to
        `ON_HOLD`, incrementing its `version`; §3.3's bubble-up describes how
        a later reporter acceptance resumes it."

        Design: Corner/state_machines/bump_intersection_guard_keeps_story_active
        """
        ctx = setup_newsroom(copy_editor=True, reporter_desk="FEATURES")
        rep_b = add_staff_to(ctx, "reporter_b", "REPORTER",
                             full_name="Rep B BG", home_desk="FEATURES")
        set_clock("2026-08-01T00:00:00Z")
        _pitch, story_id = create_greenlit_story(
            ctx, title="BG", desk="FEATURES",
            deadline_at="2026-08-04T00:00:00Z", urgency="STANDARD")
        a1 = propose_and_accept(ctx, story_id, "reporter",
                                start_at="2026-08-01T10:00:00Z",
                                end_at="2026-08-01T11:00:00Z")
        a2 = propose_and_accept(ctx, story_id, "reporter_b",
                                start_at="2026-08-01T14:00:00Z",
                                end_at="2026-08-01T15:00:00Z")
        get_success_data(
            api.submit_story_edit(story_id, ctx["reporter_headers"]))
        event = declare_and_activate_event(
            priority_band=2, window_start="2026-08-01T09:00:00Z",
            window_end="2026-08-01T12:00:00Z", call_in_pool_size=0,
            title="Partial bump")

        assignments, _meta = validate_paginated(
            api.get_story_assignments(story_id, ND))
        by_id = {a["id"]: a for a in assignments}
        assert by_id[a1["id"]]["status"] == "BUMPED", \
            "the intersecting window bumps"
        assert by_id[a2["id"]]["status"] == "ACCEPTED", \
            "the non-intersecting window is untouched"
        story = get_success_data(api.get_story(story_id, ND))
        assert story["status"] == "IN_EDIT", \
            "one active reporter remains, so no ON_HOLD"
        assert event["status"] == "ACTIVE"


class TestHoldResumeBubbleUp:
    def test_accept_on_held_story_resumes_to_draft(self, api):
        """PRD §3.3: "One bubble-up exception links acceptance back to the
        story pipeline: when a story is sitting in `ON_HOLD` because its
        reporting crew was stripped by a breaking-news bump, and the accepted
        assignment is a `REPORTER` assignment on that story, the story resumes
        from `ON_HOLD` to `DRAFT` and its `version` increments."
        PRD §3.3: "A story in `DRAFT`, `IN_EDIT`, or `ON_HOLD` may be crewed;
        proposing an assignment against a story in any other state is rejected
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/hold_resume_bubble_up_on_accept
        """
        ctx = setup_newsroom(reporter_desk="FEATURES")
        rep_b = add_staff_to(ctx, "reporter_b", "REPORTER",
                             full_name="Rep B HR", home_desk="METRO")
        set_clock("2026-08-01T00:00:00Z")
        _pitch, story_id = create_greenlit_story(
            ctx, title="HR", desk="FEATURES",
            deadline_at="2026-08-04T00:00:00Z", urgency="STANDARD")
        propose_and_accept(ctx, story_id, "reporter",
                           start_at="2026-08-01T10:00:00Z",
                           end_at="2026-08-01T11:00:00Z")
        get_success_data(
            api.submit_story_edit(story_id, ctx["reporter_headers"]))
        declare_and_activate_event(
            priority_band=2, window_start="2026-08-01T09:00:00Z",
            window_end="2026-08-01T12:00:00Z", call_in_pool_size=0,
            title="Full bump")
        story = get_success_data(api.get_story(story_id, ND))
        assert story["status"] == "ON_HOLD", "the bump stranded the story"

        # ON_HOLD is a crewable state; accepting the fresh reporter resumes.
        a2 = propose_assignment(ctx, story_id, rep_b["id"],
                                start_at="2026-08-01T13:00:00Z",
                                end_at="2026-08-01T14:00:00Z",
                                planned_effort_minutes=45)
        assert a2["status"] == "PROPOSED"
        get_success_data(api.accept_assignment(
            a2["id"], ctx["reporter_b_headers"]))
        story = get_success_data(api.get_story(story_id, ND))
        assert story["status"] == "DRAFT", "accept bubble-up auto-resume"


class TestCallInLifecycle:
    def _paged_call_in(self, api, band=2, pool=1):
        """One ACTIVE reporter; an activated event pages them. Returns
        (reporter, event, call_in)."""
        ctx = setup_newsroom()
        event = declare_and_activate_event(
            priority_band=band, call_in_pool_size=pool)
        call_ins = event_call_ins(event["id"])
        assert len(call_ins) == 1
        return ctx, event, call_ins[0]

    def test_resolve_expires_paged_callins(self, api):
        """PRD §3.8: "Resolution closes the event. A `NewsDirector` resolves
        an `ACTIVE` event — any other state yields `ERR_INVALID_STATE` —
        stamping `resolved_at` with the logical clock, moving every
        still-`PAGED` call-in of the event to `EXPIRED`, and incrementing the
        event's `version`."

        Design: Corner/state_machines/resolve_expires_paged_callins
        """
        ctx, event, call_in = self._paged_call_in(api, band=3)
        assert call_in["status"] == "PAGED"
        get_success_data(api.resolve_breaking_event(event["id"], ND))
        after = event_call_ins(event["id"])
        assert after[0]["status"] == "EXPIRED", "resolve cascade"

    def test_callin_double_confirm_rejected(self, api):
        """PRD §3.8: "Paged staff answer for themselves — `Reporter` or
        `Photographer` roles whose `X-User-ID` equals the call-in's
        `staff_id`, with `ERR_FORBIDDEN` otherwise — and only a `PAGED`
        call-in can be answered (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/callin_double_confirm_rejected
        """
        ctx, event, call_in = self._paged_call_in(api, band=1)
        first = api.confirm_call_in(call_in["id"], ctx["reporter_headers"])
        assert validate_success(first)["status"] == "CONFIRMED"
        second = api.confirm_call_in(call_in["id"], ctx["reporter_headers"])
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    def test_callin_decline_works_and_survives_resolve(self, api):
        """PRD §3.8: "Paged staff answer for themselves — `Reporter` or
        `Photographer` roles whose `X-User-ID` equals the call-in's
        `staff_id`, with `ERR_FORBIDDEN` otherwise — and only a `PAGED`
        call-in can be answered (`ERR_INVALID_STATE`)."
        PRD §3.8: "Expiry also arrives on its own: the operations checkpoint
        of §3.5 expires every `PAGED` call-in whose `expires_at` has been
        reached, and resolving the event does the same for its outstanding
        pages."

        Design: Corner/state_machines/callin_decline_works_and_survives_resolve
        """
        ctx, event, call_in = self._paged_call_in(api, band=2)
        declined = api.decline_call_in(call_in["id"], ctx["reporter_headers"])
        assert validate_success(declined)["status"] == "DECLINED"
        get_success_data(api.resolve_breaking_event(event["id"], ND))
        after = event_call_ins(event["id"])
        assert after[0]["status"] == "DECLINED", \
            "the resolve sweep touches only PAGED records"

    def test_call_in_confirm_after_expiry(self, api):
        """PRD §3.8: "Each page creates a `StaffCallIn` in `PAGED` status, in
        ranking order, recording the `event_id` and `staff_id`, stamping
        `paged_at` with the logical clock, and setting `expires_at` sixty
        minutes after the page."
        PRD §3.8: "Both answers must arrive before `expires_at`: a late answer
        finds the call-in auto-transitioned to `EXPIRED` and is rejected with
        `ERR_CALL_IN_EXPIRED` (HTTP 409)."
        PRD §2.4: "At startup, before any adjustment, the logical clock reads
        exactly `2026-08-01T00:00:00Z`; the server must not fall back to
        wall-clock time under any circumstance."

        Design: Corner/errors/call_in_confirm_after_expiry
        """
        ctx = setup_newsroom()
        # Activated at the startup clock 2026-08-01T00:00:00Z; the page
        # expires at 01:00.
        event = declare_and_activate_event(
            priority_band=1, window_start="2026-08-01T00:30:00Z",
            window_end="2026-08-01T02:00:00Z", call_in_pool_size=1,
            title="EX event")
        call_in = event_call_ins(event["id"])[0]
        assert call_in["expires_at"].startswith("2026-08-01T01:00:00"), \
            "paged_at + 60 minutes"

        set_clock("2026-08-01T01:00:00Z")
        resp = api.confirm_call_in(call_in["id"], ctx["reporter_headers"])
        validate_error(resp, ApiErrorId.ERR_CALL_IN_EXPIRED)
        after = event_call_ins(event["id"])
        assert after[0]["status"] == "EXPIRED", \
            "confirm at exactly expires_at is too late"


class TestCallInSelector:
    def test_selector_ranking_and_tiebreak(self, api):
        """PRD §3.8: "Eligible staff are those whose `employment_status` is
        `ACTIVE` and whose `role_capability` is `REPORTER` or `PHOTOGRAPHER`."
        PRD §3.8: "They are ranked by `active_assignment_count` ascending,
        ties broken by `created_at` ascending — the least-loaded, then the
        longest-serving record first — and up to `call_in_pool_size` of them
        are paged."

        Design: Corner/cross_cutting_layers/callin_selector_ranking_and_tiebreak
        """
        ctx = setup_newsroom()
        rep_a = ctx["reporter"]
        photog_b = add_staff_to(ctx, "photographer", "PHOTOGRAPHER",
                                full_name="Phot B SL", hourly_rate_cents=5000)
        rep_c = add_staff_to(ctx, "reporter_c", "REPORTER",
                             full_name="Rep C SL")
        rep_e = add_staff_to(ctx, "reporter_e", "REPORTER",
                             full_name="Rep E SL", home_desk="SPORTS")
        rep_d = add_staff_to(ctx, "reporter_d", "REPORTER",
                             full_name="Rep D SL", home_desk="BUSINESS")
        patch_staff(rep_d["id"], employment_status="ON_LEAVE")

        # Load repC with two ACCEPTED assignments and repE with one; all
        # windows sit outside the event window so no bumps distort counts.
        stories = [create_greenlit_story(ctx, title=f"SL {t}",
                                         deadline_at="2026-08-04T00:00:00Z")[1]
                   for t in ("one", "two", "three")]
        propose_and_accept(ctx, stories[0], "reporter_c",
                           start_at="2026-08-01T14:00:00Z",
                           end_at="2026-08-01T15:00:00Z")
        propose_and_accept(ctx, stories[1], "reporter_c",
                           start_at="2026-08-01T15:00:00Z",
                           end_at="2026-08-01T16:00:00Z")
        propose_and_accept(ctx, stories[2], "reporter_e",
                           start_at="2026-08-01T16:00:00Z",
                           end_at="2026-08-01T17:00:00Z")

        event = declare_and_activate_event(
            priority_band=2, window_start="2026-08-01T09:00:00Z",
            window_end="2026-08-01T13:00:00Z", call_in_pool_size=2,
            title="SL event")
        data, meta = validate_paginated(
            api.get_event_call_ins(event["id"], ND))
        assert meta["total_count"] == 2, \
            "repE and repC are not paged; repD is ineligible as ON_LEAVE"
        assert data[0]["staff_id"] == rep_a["id"], \
            "0 active; earliest created among the 0-count tie"
        assert data[1]["staff_id"] == photog_b["id"], \
            "0 active; created after repA"

        staff_c = get_success_data(api.get_staff(rep_c["id"], ND))
        assert staff_c["active_assignment_count"] == 2, \
            "no bumps: assignment windows sit outside the event window"

    def test_selector_empty_pool_still_activates(self, api):
        """PRD §3.8: "An empty eligible pool simply produces zero call-ins and
        the activation still succeeds."

        Design: Corner/cross_cutting_layers/callin_selector_empty_pool
        """
        ctx = setup_newsroom()
        patch_staff(ctx["reporter"]["id"], employment_status="INACTIVE")
        event = declare_event(title="EP event", priority_band=1,
                              call_in_pool_size=2)
        activated = activate_event(event["id"])
        assert activated["status"] == "ACTIVE", \
            "activation succeeds despite the empty pool"
        data, meta = validate_paginated(
            api.get_event_call_ins(event["id"], ND))
        assert meta["total_count"] == 0 and data == []
