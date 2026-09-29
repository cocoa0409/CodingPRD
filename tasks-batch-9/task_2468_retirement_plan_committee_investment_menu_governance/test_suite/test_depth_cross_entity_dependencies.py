"""Gates that read a row other than the one being written.

Two families live here.  The first is the documentation gate of PRD 2.8: a
policy-statement adoption is refused because of the state of the *motion* row
and of the *meeting* row behind it, and because of which statement the plan
currently has adopted (PRD 3.3) — never because the statement being adopted is
in the wrong state itself.  In every case below the subject row is left exactly
as it was and the identical call succeeds once the other row is put right.

The second family is interval arithmetic on two different kinds of term.  A
committee seat's term interval (PRD 3.2) is only consulted for appointments that
are still live, and the seat-occupancy check at priority 42 fires before the
interval check at priority 66 — so a temporally disjoint successor is still
refused while the seat is filled.  A provider engagement's term interval
(PRD 3.9) is scoped to one plan and one `provider_role` over the `PENDING`,
`ACTIVE` and `UNDER_RFP` statuses, and adjacency is allowed there, which is the
opposite of the seat rule.
"""

from typing import Any, Dict

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_fields,
    assert_status,
    assert_version_unchanged,
    get_success_data,
    validate_error,
)
from test_helpers.factories import (
    Paths,
    end_term_payload,
    engagement_payload,
    ips_adopt_payload,
    member_payload,
    seat_fund_payload,
)
from test_helpers.fixtures import (
    Ctx,
    adjourn,
    adopt_ips,
    appoint_member,
    approve_minutes,
    carry_motion_unanimously,
    cast_vote,
    close_motion,
    create_engagement,
    create_fund,
    create_seat,
    create_slot,
    draft_ips,
    hold_meeting_and_carry_motion,
    move_motion,
    open_meeting,
    read_fund,
    read_motion,
    read_slot,
    register_plan,
    seat_fund,
)
from test_helpers.test_users import consultant_headers, sponsor_headers
from test_helpers.types import (
    AssetClass,
    CreditAccrualStatus,
    EndTermReason,
    EngagementStatus,
    FundMenuStatus,
    IpsStatus,
    MemberStatus,
    MenuPosture,
    MotionStatus,
    MotionSubjectType,
    ProviderRole,
    SeatClass,
    SeatStatus,
    SlotStatus,
    Vote,
)

#: The quarter every scenario here runs in, because the logical clock is pinned
#: to 2026-08-01 and no test advances it.
QUARTER_ZERO = 0

#: The incumbent recordkeeper's contract term, used as the reference interval
#: for every overlap probe.
INCUMBENT_TERM = {"term_start_date": "2026-01-01", "term_end_date": "2026-12-31"}


def _read_ips(client: ApiClient, ips_id: str) -> Dict[str, Any]:
    return get_success_data(client.get(Paths.ips(ips_id), sponsor_headers()))


def _read_seat(client: ApiClient, seat_id: str) -> Dict[str, Any]:
    return get_success_data(client.get(Paths.seat(seat_id), sponsor_headers()))


def _attempt_adoption(ctx: Ctx, ips_id: str, motion_id: str):
    """The chair's adoption call, issued verbatim however many times a test
    needs it."""
    return ctx.client.post(Paths.ips_adopt(ips_id), ips_adopt_payload(motion_id), ctx.chair)


def _attempt_seating(ctx: Ctx, slot_id: str, fund_id: str):
    return ctx.client.post(
        Paths.seat_fund(slot_id), seat_fund_payload(fund_id), consultant_headers()
    )


def _appoint(client: ApiClient, seat_id: str, name: str, email: str, start: str, end: str):
    """The raw appointment call, so a test can assert either outcome."""
    return client.post(
        Paths.MEMBERS,
        member_payload(
            seat_id,
            member_name=name,
            person_email=email,
            term_start_date=start,
            term_end_date=end,
        ),
        sponsor_headers(),
    )


def _attempt_engagement(ctx: Ctx, provider_name: str, start: str, end: str, role: str):
    return ctx.client.post(
        Paths.ENGAGEMENTS,
        engagement_payload(
            ctx.plan_id,
            provider_name=provider_name,
            provider_role=role,
            term_start_date=start,
            term_end_date=end,
        ),
        sponsor_headers(),
    )


def _adopt_successor_statement(
    ctx: Ctx, version_label: str, meeting_date: str, minutes_doc_ref: str
) -> Dict[str, Any]:
    """Draft a second statement and take it through the whole authorising cycle,
    which supersedes whatever the plan had adopted before."""
    statement = draft_ips(ctx.client, ctx.plan_id, version_label=version_label)
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.IPS_ADOPTION,
        statement["id"],
        meeting_date=meeting_date,
        minutes_doc_ref=minutes_doc_ref,
        key="successor",
    )
    return adopt_ips(ctx, statement["id"], motion["id"])


def test_statement_adoption_waits_for_the_motion_row_to_close(api: ApiClient, governed_plan: Ctx):
    """A statement in DRAFT is adoptable, yet the adoption is refused while the
    motion naming it is still OPEN, and the identical call succeeds once only
    that motion and its meeting have moved.

    Design: Difficulty/cross_entity_state_dependency/ips_adopt_gated_by_motion_and_meeting_rows_not_by_its_own_status
    """
    ctx = governed_plan
    statement = draft_ips(api, ctx.plan_id, version_label="IPS-2026-A")
    assert_status(statement, IpsStatus.DRAFT)
    assert_fields(ctx.refresh_plan(), menu_posture=MenuPosture.FROZEN)

    meeting = open_meeting(ctx, "2026-08-03", QUARTER_ZERO, key="adoption")
    motion = move_motion(
        ctx, meeting["id"], MotionSubjectType.IPS_ADOPTION, statement["id"], key="adoption"
    )
    for member_id in ctx.member_ids:
        cast_vote(ctx, motion["id"], member_id, Vote.FOR)
    assert_status(read_motion(api, motion["id"]), MotionStatus.OPEN)

    refused = _attempt_adoption(ctx, statement["id"], motion["id"])
    validate_error(refused, ApiErrorId.MOTION_NOT_CARRIED)
    still_draft = _read_ips(api, statement["id"])
    assert_status(still_draft, IpsStatus.DRAFT)
    assert_fields(still_draft, adopted_quarter_index=None, approving_motion_id=None)
    assert_version_unchanged(statement, still_draft)

    # Close the motion and finish the paperwork; the statement row is untouched.
    closed = close_motion(ctx, motion["id"])
    assert_status(closed, MotionStatus.CARRIED)
    adjourn(ctx, meeting["id"])
    approve_minutes(ctx, meeting["id"], "MIN-2026-Q0-001")

    adopted = get_success_data(_attempt_adoption(ctx, statement["id"], motion["id"]))
    assert_status(adopted, IpsStatus.ADOPTED)
    assert_fields(
        adopted, adopted_quarter_index=QUARTER_ZERO, approving_motion_id=motion["id"]
    )
    assert_fields(ctx.refresh_plan(), menu_posture=MenuPosture.OPEN)


def test_statement_adoption_waits_for_the_meeting_row_to_reach_approved_minutes(
    api: ApiClient, governed_plan: Ctx
):
    """With the motion already CARRIED the adoption still fails on the meeting
    row, both while it is IN_SESSION and after it has merely ADJOURNED, and
    succeeds the moment the minutes are approved.

    Design: Difficulty/cross_entity_state_dependency/ips_adopt_gated_by_motion_and_meeting_rows_not_by_its_own_status
    """
    ctx = governed_plan
    statement = draft_ips(api, ctx.plan_id, version_label="IPS-2026-A")
    meeting = open_meeting(ctx, "2026-08-03", QUARTER_ZERO, key="adoption")
    motion = carry_motion_unanimously(
        ctx, meeting["id"], MotionSubjectType.IPS_ADOPTION, statement["id"], key="adoption"
    )
    assert_status(motion, MotionStatus.CARRIED)

    in_session = _attempt_adoption(ctx, statement["id"], motion["id"])
    validate_error(in_session, ApiErrorId.MINUTES_NOT_APPROVED)
    assert_status(_read_ips(api, statement["id"]), IpsStatus.DRAFT)

    adjourn(ctx, meeting["id"])
    adjourned = _attempt_adoption(ctx, statement["id"], motion["id"])
    validate_error(adjourned, ApiErrorId.MINUTES_NOT_APPROVED)
    assert_status(_read_ips(api, statement["id"]), IpsStatus.DRAFT)

    approve_minutes(ctx, meeting["id"], "MIN-2026-Q0-001")
    adopted = get_success_data(_attempt_adoption(ctx, statement["id"], motion["id"]))
    assert_status(adopted, IpsStatus.ADOPTED)
    assert_fields(
        adopted, adopted_quarter_index=QUARTER_ZERO, approving_motion_id=motion["id"]
    )


def test_a_sibling_draft_cannot_ride_the_motion_that_names_another_statement(
    api: ApiClient, governed_plan: Ctx
):
    """Two DRAFT statements sit on the plan and one fully carried, fully minuted
    motion names the first; the sibling is refused on the subject reference while
    the named statement is adopted and the sibling is retired by that adoption.

    Design: Difficulty/cross_entity_state_dependency/ips_adopt_gated_by_motion_and_meeting_rows_not_by_its_own_status
    """
    ctx = governed_plan
    named = draft_ips(api, ctx.plan_id, version_label="IPS-2026-A")
    sibling = draft_ips(api, ctx.plan_id, version_label="IPS-2026-B")
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.IPS_ADOPTION,
        named["id"],
        meeting_date="2026-08-03",
        minutes_doc_ref="MIN-2026-Q0-001",
        key="adoption",
    )

    decoy = _attempt_adoption(ctx, sibling["id"], motion["id"])
    validate_error(decoy, ApiErrorId.MOTION_SUBJECT_MISMATCH)
    unchanged_sibling = _read_ips(api, sibling["id"])
    assert_status(unchanged_sibling, IpsStatus.DRAFT)
    assert_version_unchanged(sibling, unchanged_sibling)

    adopted = get_success_data(_attempt_adoption(ctx, named["id"], motion["id"]))
    assert_status(adopted, IpsStatus.ADOPTED)
    assert_fields(adopted, adopted_quarter_index=QUARTER_ZERO)
    assert_status(_read_ips(api, sibling["id"]), IpsStatus.RETIRED)
    assert_fields(ctx.refresh_plan(), menu_posture=MenuPosture.OPEN)


def test_seating_is_refused_when_the_slots_pin_was_superseded_on_another_row(
    api: ApiClient, adopted_ips: Ctx
):
    """The identical seating call succeeds while the slot's pinned statement is
    the adopted one and is refused with a stale-version error once a second
    statement is adopted, even though the slot is EMPTY, the fund is a CANDIDATE
    that clears every criterion, the posture is OPEN and capacity is free.

    Design: Difficulty/cross_entity_state_dependency/slot_seat_fund_blocked_by_pinned_ips_superseded_on_another_row
    """
    ctx = adopted_ips
    original = ctx.ips
    create_fund(ctx, "lc_a")
    create_fund(ctx, "bond")
    create_slot(ctx, "lc", AssetClass.US_LARGE_CAP, 1)
    create_slot(ctx, "bond", AssetClass.CORE_BOND, 2)

    # Control: with the pin still current the call shape works.
    seated = seat_fund(ctx, "lc", "lc_a")
    assert_status(seated, SlotStatus.ACTIVE)
    assert_capacity_triple(ctx.refresh_plan(), occupied=1, reserved=0, available=5)

    successor = _adopt_successor_statement(ctx, "IPS-2026-B", "2026-08-05", "MIN-2026-Q0-002")
    assert_status(successor, IpsStatus.ADOPTED)
    assert_status(_read_ips(api, original["id"]), IpsStatus.SUPERSEDED)

    before_slot = read_slot(api, ctx.slot("bond")["id"])
    assert_fields(
        before_slot,
        status=SlotStatus.EMPTY,
        ips_id=original["id"],
        current_fund_id=None,
    )
    assert_fields(read_fund(api, ctx.fund("bond")["id"]), menu_status=FundMenuStatus.CANDIDATE)
    before_plan = ctx.refresh_plan()
    assert_fields(before_plan, menu_posture=MenuPosture.OPEN)
    assert_capacity_triple(before_plan, occupied=1, reserved=0, available=5)

    refused = _attempt_seating(ctx, before_slot["id"], ctx.fund("bond")["id"])
    validate_error(refused, ApiErrorId.IPS_VERSION_STALE)

    # The refused call must not quietly re-pin the slot to the new statement.
    after_slot = read_slot(api, before_slot["id"])
    assert_fields(
        after_slot,
        status=SlotStatus.EMPTY,
        ips_id=original["id"],
        current_fund_id=None,
    )
    assert_version_unchanged(before_slot, after_slot)
    assert_fields(read_fund(api, ctx.fund("bond")["id"]), menu_status=FundMenuStatus.CANDIDATE)
    assert_capacity_triple(ctx.refresh_plan(), occupied=1, reserved=0, available=5)


def test_a_slot_created_after_the_supersession_pins_the_new_statement_and_seats(
    api: ApiClient, adopted_ips: Ctx
):
    """A slot created once the second statement is adopted pins that statement,
    so the same fund the stale slot could not take is seated normally and the
    capacity triple and plan assets move by exactly one seat.

    Design: Difficulty/cross_entity_state_dependency/slot_seat_fund_blocked_by_pinned_ips_superseded_on_another_row
    """
    ctx = adopted_ips
    original = ctx.ips
    create_fund(ctx, "bond")

    successor = _adopt_successor_statement(ctx, "IPS-2026-B", "2026-08-05", "MIN-2026-Q0-002")
    assert_status(successor, IpsStatus.ADOPTED)
    assert successor["id"] != original["id"]
    ctx.ips = successor

    fresh = create_slot(ctx, "bond", AssetClass.CORE_BOND, 1)
    assert_fields(fresh, ips_id=successor["id"], status=SlotStatus.EMPTY)

    seated = get_success_data(_attempt_seating(ctx, fresh["id"], ctx.fund("bond")["id"]))
    assert_fields(
        seated, status=SlotStatus.ACTIVE, current_fund_id=ctx.fund("bond")["id"]
    )
    assert_fields(
        read_fund(api, ctx.fund("bond")["id"]),
        menu_status=FundMenuStatus.ACTIVE,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
        qdia_flag=False,
    )
    plan = ctx.refresh_plan()
    assert_capacity_triple(plan, occupied=1, reserved=0, available=5)
    assert_fields(
        plan, menu_posture=MenuPosture.OPEN, total_plan_assets_cents=400000000
    )


def test_seat_occupancy_outranks_the_term_interval_check(api: ApiClient):
    """A filled seat refuses a successor whose term cannot possibly overlap the
    incumbent's, and the very same interval is accepted on a seat that is still
    VACANT — so the refusal is about occupancy, not about the interval.

    Design: Difficulty/resource_temporal_overlap/seat_occupancy_preempts_term_interval_and_terminal_terms_are_ignored
    """
    plan = register_plan(api)
    filled = create_seat(
        api,
        plan["id"],
        seat_code="S-IND-1",
        seat_class=SeatClass.INDEPENDENT,
        seat_index=4,
        voting=False,
    )
    incumbent = appoint_member(
        api,
        filled["id"],
        member_name="Abel Nwosu",
        person_email="abel.nwosu@example.com",
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
    )
    assert_status(incumbent, MemberStatus.APPOINTED)
    assert_status(_read_seat(api, filled["id"]), SeatStatus.FILLED)

    # 2027-01-01 starts a full day after the incumbent's term ends, so the two
    # closed intervals are disjoint; the seat is what blocks the appointment.
    refused = _appoint(
        api,
        filled["id"],
        "Bree Salas",
        "bree.salas@example.com",
        "2027-01-01",
        "2027-12-31",
    )
    validate_error(refused, ApiErrorId.SEAT_NOT_VACANT)
    assert_status(_read_seat(api, filled["id"]), SeatStatus.FILLED)

    vacant = create_seat(
        api,
        plan["id"],
        seat_code="S-IND-2",
        seat_class=SeatClass.INDEPENDENT,
        seat_index=5,
        voting=False,
    )
    accepted = get_success_data(
        _appoint(
            api,
            vacant["id"],
            "Bree Salas",
            "bree.salas@example.com",
            "2027-01-01",
            "2027-12-31",
        ),
        201,
    )
    assert_status(accepted, MemberStatus.APPOINTED)
    assert_fields(accepted, term_start_date="2027-01-01", term_end_date="2027-12-31")
    assert_status(_read_seat(api, vacant["id"]), SeatStatus.FILLED)


def test_a_terminal_appointment_is_invisible_to_the_seat_term_interval_check(api: ApiClient):
    """Once the incumbent is REMOVED the seat is VACANT again and its historical
    term is out of scope, so a successor whose term overlaps that history is
    accepted — and the now-filled seat refuses the next disjoint term again.

    Design: Difficulty/resource_temporal_overlap/seat_occupancy_preempts_term_interval_and_terminal_terms_are_ignored
    """
    plan = register_plan(api)
    seat = create_seat(
        api,
        plan["id"],
        seat_code="S-IND-1",
        seat_class=SeatClass.INDEPENDENT,
        seat_index=4,
        voting=False,
    )
    incumbent = appoint_member(
        api,
        seat["id"],
        member_name="Abel Nwosu",
        person_email="abel.nwosu@example.com",
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
    )

    removed = get_success_data(
        api.post(
            Paths.end_term(incumbent["id"]),
            end_term_payload(EndTermReason.REMOVAL_FOR_CAUSE),
            sponsor_headers(),
        )
    )
    assert_status(removed, MemberStatus.REMOVED)
    assert_status(_read_seat(api, seat["id"]), SeatStatus.VACANT)

    # 2026-06-01 through 2027-05-31 sits squarely inside the removed member's
    # term, which no longer counts.
    successor = get_success_data(
        _appoint(
            api,
            seat["id"],
            "Cleo Bright",
            "cleo.bright@example.com",
            "2026-06-01",
            "2027-05-31",
        ),
        201,
    )
    assert_status(successor, MemberStatus.APPOINTED)
    assert_fields(successor, term_start_date="2026-06-01", term_end_date="2027-05-31")
    assert_status(_read_seat(api, seat["id"]), SeatStatus.FILLED)

    later = _appoint(
        api,
        seat["id"],
        "Dov Harel",
        "dov.harel@example.com",
        "2028-01-01",
        "2028-12-31",
    )
    validate_error(later, ApiErrorId.SEAT_NOT_VACANT)


def test_engagement_term_overlap_is_scoped_to_one_provider_role(api: ApiClient):
    """Three different ways of intersecting the incumbent recordkeeper's term are
    all refused, while the identical 2026 window is free for an advisor.

    Design: Difficulty/resource_temporal_overlap/engagement_term_overlap_scoped_by_role_and_live_status_adjacency_allowed
    """
    ctx = Ctx(api)
    ctx.plan = register_plan(api)
    incumbent = create_engagement(
        ctx,
        "incumbent",
        provider_name="Northwind Recordkeeping LLC",
        provider_role=ProviderRole.RECORDKEEPER,
        **INCUMBENT_TERM,
    )
    assert_status(incumbent, EngagementStatus.PENDING)
    assert_fields(incumbent, **INCUMBENT_TERM)

    probes = (
        ("2026-12-31", "2027-06-30"),  # a one-day touch on the incumbent's last day
        ("2026-03-01", "2026-06-30"),  # fully inside the incumbent's term
        ("2025-01-01", "2027-12-31"),  # fully wrapping the incumbent's term
    )
    for start, end in probes:
        refused = _attempt_engagement(
            ctx, "Southwind Recordkeeping LLC", start, end, ProviderRole.RECORDKEEPER
        )
        validate_error(refused, ApiErrorId.ENGAGEMENT_TERM_OVERLAP)

    advisor = get_success_data(
        _attempt_engagement(
            ctx,
            "Trailhead Retirement Advisors LLC",
            INCUMBENT_TERM["term_start_date"],
            INCUMBENT_TERM["term_end_date"],
            ProviderRole.ADVISOR,
        ),
        201,
    )
    assert_status(advisor, EngagementStatus.PENDING)
    assert_fields(advisor, provider_role=ProviderRole.ADVISOR, **INCUMBENT_TERM)


def test_an_adjacent_engagement_term_is_allowed_and_termination_frees_the_window(
    api: ApiClient,
):
    """A successor term starting the day after the incumbent's ends is accepted —
    the opposite of the seat rule — and once the incumbent is TERMINATED the
    window it used to block is free.

    Design: Difficulty/resource_temporal_overlap/engagement_term_overlap_scoped_by_role_and_live_status_adjacency_allowed
    """
    ctx = Ctx(api)
    ctx.plan = register_plan(api)
    incumbent = create_engagement(
        ctx,
        "incumbent",
        provider_name="Northwind Recordkeeping LLC",
        provider_role=ProviderRole.RECORDKEEPER,
        **INCUMBENT_TERM,
    )

    successor = get_success_data(
        _attempt_engagement(
            ctx,
            "Southwind Recordkeeping LLC",
            "2027-01-01",
            "2027-12-31",
            ProviderRole.RECORDKEEPER,
        ),
        201,
    )
    assert_status(successor, EngagementStatus.PENDING)

    contained = _attempt_engagement(
        ctx, "Eastwind Recordkeeping LLC", "2026-02-01", "2026-11-30", ProviderRole.RECORDKEEPER
    )
    validate_error(contained, ApiErrorId.ENGAGEMENT_TERM_OVERLAP)

    # The plan keeps a live recordkeeper in the 2027 successor, so the incumbent
    # may be terminated.
    terminated = get_success_data(
        api.post(
            Paths.engagement_terminate(incumbent["id"]),
            {"reason": "The 2027 successor takes over the recordkeeping mandate early."},
            sponsor_headers(),
        )
    )
    assert_status(terminated, EngagementStatus.TERMINATED)

    freed = get_success_data(
        _attempt_engagement(
            ctx,
            "Eastwind Recordkeeping LLC",
            "2026-02-01",
            "2026-11-30",
            ProviderRole.RECORDKEEPER,
        ),
        201,
    )
    assert_status(freed, EngagementStatus.PENDING)
    assert_fields(freed, term_start_date="2026-02-01", term_end_date="2026-11-30")
