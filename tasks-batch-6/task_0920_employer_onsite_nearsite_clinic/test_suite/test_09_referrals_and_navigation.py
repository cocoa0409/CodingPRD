"""Referral steerage, the dual-variant navigation SLA, the redirect cycle and
segregation of duties."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_referral,
    assert_same_instant,
    make_navigator_headers,
    new_shift,
    raise_referral,
    set_clock,
    setup_completed_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


def _referral_world(code, name, member, closure_dates=None, navigator_count=1):
    site = {"site_name": f"{code} Clinic", "daily_slot_capacity": 8}
    if closure_dates is not None:
        site["closure_dates"] = closure_dates
    return setup_completed_visit(
        visit_type="PRIMARY_CARE",
        scheduled_start="2026-06-08T09:00:00Z",
        visit_clock="2026-06-08T10:00:00Z",
        employer={"legal_name": name, "employer_code": code},
        site=site,
        with_navigator=True,
        navigator_count=navigator_count,
        eligibility={
            "subscriber_external_id": f"S-{member}",
            "member_external_id": f"M-{member}",
        },
        participant={"display_name": f"{code} Tester"},
        completion={"clinical_note": "Refer onward"},
    )


def test_emergent_and_routine_sla_deadlines_diverge_from_one_instant():
    """PRD §3.7: "For `EMERGENT` and `URGENT` referrals the deadline is pure
    wall-clock arithmetic from the logical clock instant at creation: four calendar
    hours for `EMERGENT`, forty-eight calendar hours for `URGENT`."
    PRD §3.7: "Counting begins with the day **after** the creation date — the creation
    date itself never counts, whether or not the site is open on it — and advances
    through dates that are site-open, meaning dates whose ISO weekday appears in that
    site's `operating_weekdays` and which do not appear in that site's
    `closure_dates`. The tenth such site-open date is the due date, and `sla_due_at`
    is that date at the site's `close_time_utc`."
    PRD §3.7: "A referral to a `CENTER_OF_EXCELLENCE` or a `PREFERRED` destination is
    auto-authorized by the system at the moment of creation, moving
    `SUBMITTED → AUTHORIZED` immediately; `authorized_by_provider_id` stays null on
    that path precisely because no human authorized it."

    Design: Corner/calculations/emergent_and_routine_sla_variants_diverge_from_one_base_instant
    """
    world = _referral_world("URG", "Urgency Co", "4401", closure_dates=["2026-06-12"])

    emergent = raise_referral(
        world.participant_id,
        world.visit_id,
        world.clinician_headers,
        specialty="CARDIOLOGY",
        steerage_tier="PREFERRED",
        urgency="EMERGENT",
    )
    routine = raise_referral(
        world.participant_id,
        world.visit_id,
        world.clinician_headers,
        specialty="ORTHOPEDICS",
        steerage_tier="PREFERRED",
        urgency="ROUTINE",
    )

    assert_referral(emergent)
    assert_same_instant(emergent["sla_due_at"], "2026-06-08T14:00:00Z")
    assert_same_instant(routine["sla_due_at"], "2026-06-23T17:00:00Z")

    for referral in (emergent, routine):
        assert referral["status"] == "AUTHORIZED"
        assert referral["raised_by_provider_id"] == world.clinician_id
        assert referral["authorized_by_provider_id"] is None


def test_referral_escalates_only_strictly_after_its_sla():
    """PRD §3.7: "**Escalation** is not requested by anyone; it is swept by the clock.
    A referral standing at `SUBMITTED` or `AUTHORIZED` whose `sla_due_at` falls
    strictly before a new clock instant moves to `ESCALATED` with `escalated_at`
    stamped to that new instant. The comparison is strict on purpose: a referral
    standing at exactly its `sla_due_at` has not breached and does not escalate."
    PRD §3.7: "A `CareNavigator` closes the loop on a referral standing at
    `AUTHORIZED` or at `ESCALATED` by supplying the `consult_note_reference` of the
    returned note, which moves the referral to `CLOSED_LOOP` and stamps
    `loop_closed_at` with the clock instant. Closing an escalated referral
    **preserves** its `escalated_at` — the breach happened and the record of it
    survives closure, because that is exactly what navigation performance reporting
    needs to see."

    Design: Corner/state_machines/referral_escalates_only_when_the_clock_passes_the_sla_strictly
    """
    world = _referral_world("SLA", "SLA Co", "4101")
    referral = raise_referral(
        world.participant_id,
        world.visit_id,
        world.clinician_headers,
        specialty="CARDIOLOGY",
        steerage_tier="CENTER_OF_EXCELLENCE",
        urgency="URGENT",
    )
    assert_same_instant(referral["sla_due_at"], "2026-06-10T10:00:00Z")
    assert referral["status"] == "AUTHORIZED"

    on_deadline = set_clock("2026-06-10T10:00:00Z")
    assert on_deadline["escalated_referral_ids"] == []
    unbreached = validate_success(
        api_client.get_referral(referral["id"], world.navigator_headers)
    )
    assert unbreached["status"] == "AUTHORIZED"
    assert unbreached["escalated_at"] is None

    past_deadline = set_clock("2026-06-10T10:00:01Z")
    assert referral["id"] in past_deadline["escalated_referral_ids"]
    escalated = validate_success(
        api_client.get_referral(referral["id"], world.navigator_headers)
    )
    assert escalated["status"] == "ESCALATED"
    assert_same_instant(escalated["escalated_at"], "2026-06-10T10:00:01Z")

    closed = validate_success(
        api_client.close_referral_loop(
            referral["id"],
            {"consult_note_reference": "CONSULT-2026-0610-A"},
            world.navigator_headers,
        )
    )
    assert closed["status"] == "CLOSED_LOOP"
    assert_same_instant(closed["loop_closed_at"], "2026-06-10T10:00:01Z")
    assert_same_instant(closed["escalated_at"], "2026-06-10T10:00:01Z")
    assert closed["consult_note_reference"] == "CONSULT-2026-0610-A"


def test_redirect_moves_predecessor_and_links_the_successor():
    """PRD §3.7: "A redirect supplies a fresh `specialty`, `steerage_tier` and
    `urgency`; it moves the declined referral to `REDIRECTED`, which is terminal for
    it, and creates a successor referral that copies `participant_id` and `visit_id`
    from its predecessor, takes the three supplied values, and records
    `redirected_from_referral_id` pointing back at the referral it came from."
    PRD §3.7: "And it starts at `SUBMITTED` **whatever its `steerage_tier`**: the
    auto-authorization that applies at original creation does not apply to a redirect
    successor, which must be authorized by a navigator like any other submission."
    PRD §3.7: "Its `raised_by_provider_id` is **copied unchanged** from the
    predecessor, so a navigator cannot launder a referral it raised through a redirect
    and then authorize the successor — the segregation-of-duties constraint survives
    the whole chain."

    Design: Difficulty/non_linear_state_machine/referral_decline_redirect_cycle_spawns_successor_without_double_counting
    """
    world = _referral_world("RLC", "Referral Loop Co", "8001", closure_dates=["2026-06-12"])
    original = raise_referral(
        world.participant_id,
        world.visit_id,
        world.clinician_headers,
        specialty="ORTHOPEDICS",
        steerage_tier="STANDARD",
        urgency="ROUTINE",
    )
    assert original["status"] == "SUBMITTED"
    assert_same_instant(original["sla_due_at"], "2026-06-23T17:00:00Z")

    validate_success(
        api_client.decline_referral(original["id"], world.navigator_headers)
    )
    successor = validate_success(
        api_client.redirect_referral(
            original["id"],
            {
                "specialty": "ORTHOPEDICS",
                "steerage_tier": "CENTER_OF_EXCELLENCE",
                "urgency": "ROUTINE",
            },
            world.navigator_headers,
        ),
        201,
    )

    predecessor = validate_success(
        api_client.get_referral(original["id"], world.navigator_headers)
    )
    assert predecessor["status"] == "REDIRECTED"
    assert predecessor["redirected_from_referral_id"] is None

    assert successor["redirected_from_referral_id"] == original["id"]
    assert successor["status"] == "SUBMITTED", (
        "auto-authorization does not apply to a redirect successor"
    )
    assert successor["raised_by_provider_id"] == original["raised_by_provider_id"]
    assert successor["participant_id"] == world.participant_id
    assert successor["visit_id"] == world.visit_id


def test_redirected_chain_keeps_exactly_one_head():
    """PRD §3.7: "For counting purposes only chain heads count — a referral whose
    `redirected_from_referral_id` is null — so a redirected chain is counted once
    however long it grows."
    PRD §3.7: "Referrals can be listed and filtered by `participant_id`, by
    `visit_id`, by `redirected_from_referral_id`, by `raised_by_provider_id`, by
    `status` and by `urgency`."

    Design: Difficulty/non_linear_state_machine/referral_decline_redirect_cycle_spawns_successor_without_double_counting
    """
    world = _referral_world("RLC", "Referral Loop Co", "8001", closure_dates=["2026-06-12"])
    original = raise_referral(
        world.participant_id,
        world.visit_id,
        world.clinician_headers,
        specialty="ORTHOPEDICS",
        steerage_tier="STANDARD",
        urgency="ROUTINE",
    )
    api_client.decline_referral(original["id"], world.navigator_headers)
    validate_success(
        api_client.redirect_referral(
            original["id"],
            {
                "specialty": "ORTHOPEDICS",
                "steerage_tier": "CENTER_OF_EXCELLENCE",
                "urgency": "ROUTINE",
            },
            world.navigator_headers,
        ),
        201,
    )

    chain, meta = validate_paginated(
        api_client.list_referrals(
            world.navigator_headers, params={"visit_id": world.visit_id}
        )
    )
    assert meta["total_count"] == 2
    heads = [row for row in chain if row["redirected_from_referral_id"] is None]
    assert len(heads) == 1, f"a redirected chain must keep one head, found {len(heads)}"
    assert heads[0]["id"] == original["id"]


def test_navigator_cannot_authorize_the_referral_it_raised():
    """PRD §3.7: "The segregation-of-duties rule governs it: the acting navigator's
    `X-User-ID` must differ from the referral's `raised_by_provider_id`, because
    whoever raised a referral may not also authorize it, and a violation is refused
    with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.7: "Success sets `authorized_by_provider_id` to the acting navigator's
    provider identifier and moves the referral `SUBMITTED → AUTHORIZED`."

    Design: Corner/rbac/navigator_cannot_authorize_a_referral_it_raised_itself
    """
    world = _referral_world("SOD", "SoD Co", "5201", navigator_count=2)
    first_navigator, second_navigator = world.navigators[0], world.navigators[1]
    navigation_shift = new_shift(
        world.site_id,
        first_navigator["id"],
        shift_start="2026-06-08T08:00:00Z",
        shift_end="2026-06-08T12:00:00Z",
        coverage_role="NAVIGATION",
    )
    assert navigation_shift["coverage_role"] == "NAVIGATION"
    assert navigation_shift["staffed_hours"] == 4.0

    referral = raise_referral(
        world.participant_id,
        world.visit_id,
        make_navigator_headers(first_navigator["id"]),
        specialty="NEUROLOGY",
        steerage_tier="OUT_OF_NETWORK",
        urgency="URGENT",
    )
    assert referral["raised_by_provider_id"] == first_navigator["id"]

    validate_error(
        api_client.authorize_referral(
            referral["id"], make_navigator_headers(first_navigator["id"])
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    unchanged = validate_success(
        api_client.get_referral(
            referral["id"], make_navigator_headers(second_navigator["id"])
        )
    )
    assert unchanged["status"] == "SUBMITTED"

    authorized = validate_success(
        api_client.authorize_referral(
            referral["id"], make_navigator_headers(second_navigator["id"])
        )
    )
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["authorized_by_provider_id"] == second_navigator["id"]
