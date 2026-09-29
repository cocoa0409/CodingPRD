"""One call, several rows: the cascades that fire, the ones that stop, and the ledgers.

Every test here drives a single mutation and then reads the entities it was supposed to
reach -- the home's two dimensions, the derived posture, the showing calendar, the money
ledger and the case's realized group -- as well as the ones it was supposed to leave alone.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_home_dimensions,
    assert_money_group,
    created,
    ok,
)
from test_helpers.constants import (
    ASSET_PASSED,
    ASSET_STABILIZED,
    APP_CONDITIONAL_APPROVED,
    CASE_REJECTED,
    CLOCK_AUG_01,
    LEASE_EXECUTED,
    OBLIGATION_OPEN,
    OBLIGATION_RESOLVED,
    OCC_OCCUPIED,
    OCC_VACANT,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    PROJECT_SCOPING,
    SLOT_AVAILABLE,
    SLOT_BLOCKED_BY_POSTURE,
    SLOT_BOOKED,
    SLOT_CANCELLED,
)


def test_one_rejection_walks_the_home_to_passed_and_freezes_the_calendar(api):
    """Three levels in one decision -- and the occupancy dimension stays where it was.

    PRD SS3.2: "A rejection moves the case `SUBMITTED -> REJECTED`, stamps
    `decided_by_user_id`, and cascades further: the home advances `PIPELINE -> PASSED`, its
    posture becomes `FROZEN` because `PASSED` is a freezing asset state, and every showing
    window on that home whose `status` is `AVAILABLE` moves to `BLOCKED_BY_POSTURE`."  PRD
    SS2.8 clause 1: "If `asset_status` is `PASSED`, `RENOVATING` or `DISPOSED`, the posture is
    `FROZEN`", and "A transition on one dimension never implicitly moves the other."  The yield
    follows the ten-step skeleton off a single 292176-cent scope line -- PRD SS3.2 prices that
    line at "292176" and reports the same home's "net operating income of 1521184" -- so step
    (1)'s basis is 26042176 and step (10)'s "yield on cost in basis points is net operating
    income multiplied by 10,000, divided by the all-in basis, rounded half up."

    Design: Corner/state_machines/case_reject_cascades_home_to_passed_and_blocks_slots
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])
    slot = x.available_slot(api, home["id"])
    case = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home["id"], home["version"], [f.scope_line(paint["id"], 1)]
            ),
            x.ANALYST,
        )
    )
    ok(api.submit_underwriting_case(case["id"], {}, x.ANALYST))

    decided = ok(
        api.decide_underwriting_case(
            case["id"],
            f.decision_payload("REJECT", decision_note="Roof condition worse than modelled"),
            x.COMMITTEE,
        )
    )
    assert_fields(
        decided,
        status=CASE_REJECTED,
        decided_by_user_id="ic-1",
        underwritten_yield_on_cost_bps=584,
    )

    home_after = ok(api.get_home(home["id"], x.ANALYST))
    assert_home_dimensions(home_after, ASSET_PASSED, OCC_VACANT, POSTURE_FROZEN)
    assert_fields(
        # PRD SS4 does not list `AcquisitionAnalyst` among the roles authorized to read
        # `GET /homes/{homeId}/leasing-posture`; `LeasingAgent` is.
        ok(api.get_leasing_posture(home["id"], x.AGENT)),
        leasing_posture=POSTURE_FROZEN,
        deciding_clause=1,
    )
    assert_fields(
        ok(api.get_showing_slot(slot["id"], x.AGENT)), status=SLOT_BLOCKED_BY_POSTURE
    )


def test_each_work_order_posts_its_quote_to_the_ledger_as_it_is_created(api):
    """Two creates, two ledger positions, and the conserved identity after both.

    PRD SS2.9: "For every renovation project, `committed_cost_cents` plus
    `budget_remaining_cents` always equals `approved_budget_cents`. Creating a work order
    inside a project adds the work order's `quoted_cost_cents` to `committed_cost_cents` and
    subtracts the same amount from `budget_remaining_cents`".  PRD SS3.3: "when a `project_id`
    is supplied, the quote is added to the project's `committed_cost_cents` and subtracted from
    `budget_remaining_cents`", and each order also computes its own pair -- "Continuing the
    interior-paint example whose benchmark was 292176, a quote of 300000 gives 268 basis points
    and is accepted against a tolerance of 1000" -- while the HVAC line's benchmark is the
    PRD's own "627761".

    Design: Corner/state_machines/work_order_create_syncs_the_project_budget_ledger
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    hvac = x.create_scope_template(api, f.scope_template_hvac())
    home = x.create_home(api, market["id"])
    x.underwrite_and_approve(
        api, home["id"], home["version"], [f.scope_line(paint["id"], 1)]
    )
    project = created(
        api.create_renovation_project(
            f.renovation_project_payload(home["id"], 1600000), x.OPS
        )
    )
    assert_money_group(
        project, committed_cost_cents=0, budget_remaining_cents=1600000
    )

    first = created(
        api.create_work_order(
            f.work_order_payload(home["id"], paint["id"], project_id=project["id"]), x.OPS
        )
    )
    after_first = ok(api.get_renovation_project(project["id"], x.OPS))
    assert_money_group(
        after_first, committed_cost_cents=300000, budget_remaining_cents=1300000
    )

    second = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                hvac["id"],
                fulfillment_channel="VENDOR",
                quoted_cost_cents=640000,
                project_id=project["id"],
            ),
            x.OPS,
        )
    )
    after_second = ok(api.get_renovation_project(project["id"], x.OPS))
    assert_money_group(
        after_second, committed_cost_cents=940000, budget_remaining_cents=660000
    )
    assert (
        after_second["committed_cost_cents"] + after_second["budget_remaining_cents"]
        == 1600000
    )
    assert_fields(after_second, status=PROJECT_SCOPING)

    assert_fields(first, variance_bps=268)
    assert_money_group(first, benchmark_total_cents=292176)
    assert_fields(second, variance_bps=195)
    assert_money_group(second, benchmark_total_cents=627761)


def test_executing_the_lease_occupies_the_home_and_cancels_its_open_windows(api):
    """One execute reaches the occupancy dimension, the calendar and the realized group.

    PRD SS3.8: "Execution cascades three ways: the home's `occupancy_status` moves `RESERVED ->
    OCCUPIED`; every showing window on that home whose `status` is `AVAILABLE` moves `AVAILABLE`
    -> `CANCELLED` with `cancel_reason` set to `HOME_LEASED`, since a leased home holds no more
    tours; and the home's `APPROVED` underwriting case has its realized field group recomputed
    off the executed `monthly_rent_cents` rather than the home's `asking_rent_cents`, which in
    turn refreshes `hold_sell_score_bps` and `disposition_flagged`."  PRD SS3.2: the realized
    "renovation figure is the sum of `actual_cost_cents` over every work order whose `status` is
    `COMPLETED`", and `hold_sell_score_bps` "is the case's `realized_yield_on_cost_bps` ...
    minus the market's `disposition_yield_floor_bps`", with "`disposition_flagged` ... true
    exactly when that score is below zero".  PRD SS3.8 also fixes the deposit stack this lease
    inherits: the 215000-rent home with "a fraud score of 1093 and one pet ... lands in clause 5
    as `CONDITIONAL_APPROVED` with a multiplier of 15000, a `security_deposit_cents` of 322500,
    a `pet_deposit_cents` of 30000 and a `total_move_in_deposit_cents` of 352500."

    Design: Corner/state_machines/lease_execute_occupies_the_home_and_cancels_its_available_slots
    """
    ctx = x.reserved_home(api)
    assert_fields(ctx.screened, status=APP_CONDITIONAL_APPROVED)
    assert_money_group(ctx.screened, total_move_in_deposit_cents=352500)
    slot_a = x.available_slot(
        api, ctx.home_id, starts_at="2026-09-08T15:00:00Z", ends_at="2026-09-08T15:30:00Z"
    )
    slot_b = x.available_slot(
        api,
        ctx.home_id,
        starts_at="2026-09-08T16:00:00Z",
        ends_at="2026-09-08T16:30:00Z",
        access_mode="LOCKBOX",
    )
    lease = x.funded_draft_lease(api, ctx.application_id)

    executed = ok(api.execute_lease(lease["id"], f.execute_lease_payload("2026-09-06"), x.AGENT))
    assert_fields(executed, status=LEASE_EXECUTED, signed_on="2026-09-06")
    assert_money_group(
        executed, required_deposit_cents=352500, deposit_paid_cents=352500
    )

    home = ok(api.get_home(ctx.home_id, x.AGENT))
    assert_home_dimensions(home, ASSET_STABILIZED, OCC_OCCUPIED, POSTURE_OPEN)
    assert_fields(home, booked_showing_count=0, hold_sell_score_bps=16, disposition_flagged=False)

    for slot in (slot_a, slot_b):
        assert_fields(
            ok(api.get_showing_slot(slot["id"], x.AGENT)),
            status=SLOT_CANCELLED,
            cancel_reason="HOME_LEASED",
        )

    case = ok(api.get_underwriting_case(ctx.case_id, x.ANALYST))
    assert_fields(
        case, realized_yield_on_cost_bps=556, underwritten_yield_on_cost_bps=584
    )
    assert_money_group(
        case,
        realized_renovation_cost_cents=300000,
        realized_all_in_basis_cents=26050000,
        realized_noi_cents=1448541,
    )


def test_a_critical_obligation_blocks_the_window_and_its_resolution_gives_it_back(api):
    """AVAILABLE and BLOCKED_BY_POSTURE cycle both ways, with no call on the window.

    PRD SS3.9: "Creation immediately recomputes the home's `leasing_posture`: a `CRITICAL`
    obligation drives the posture to `FROZEN` and therefore moves every `AVAILABLE` showing
    window on that home to `BLOCKED_BY_POSTURE`", and on review "`ACCEPT` moves it
    `RESOLUTION_SUBMITTED` -> `RESOLVED`. Every one of the three branches recomputes the home's
    `leasing_posture`, since `RESOLVED` and `WAIVED` obligations both stop blocking, and may
    therefore move `BLOCKED_BY_POSTURE` windows back to `AVAILABLE`."  PRD SS2.8: the freeze
    holds "if the home has at least one compliance obligation whose `severity` is `CRITICAL` and
    whose `status` is one of `OPEN`, `PLANNED`, `RESOLUTION_SUBMITTED` or
    `RESOLUTION_REJECTED`", and "`CANCELLED` is the only terminal state on this dimension;
    `AVAILABLE` and `BLOCKED_BY_POSTURE` cycle back and forth as the home's posture changes"
    (PRD SS3.7).

    Design: Corner/state_machines/slot_cycles_blocked_then_available_as_critical_obligation_resolves
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    slot = x.available_slot(api, home["id"])
    assert_fields(slot, status=SLOT_AVAILABLE)

    obligation = x.open_obligation(
        api,
        home["id"],
        severity="CRITICAL",
        description="Structural deck failure",
    )
    assert_fields(ok(api.get_home(home["id"], x.OPS)), leasing_posture=POSTURE_FROZEN)
    blocked = ok(api.get_showing_slot(slot["id"], x.AGENT))
    assert_fields(blocked, status=SLOT_BLOCKED_BY_POSTURE)
    assert_absent_or_empty(blocked, "cancel_reason")

    ok(
        api.plan_obligation(
            obligation["id"], f.plan_obligation_payload("2026-08-25"), x.COMPLIANCE
        )
    )
    assert_fields(
        ok(api.get_showing_slot(slot["id"], x.AGENT)), status=SLOT_BLOCKED_BY_POSTURE
    )
    ok(
        api.submit_obligation_resolution(
            obligation["id"],
            f.submit_resolution_payload(evidence_ref="deck-permit-901"),
            x.COMPLIANCE,
        )
    )
    assert_fields(
        ok(api.get_showing_slot(slot["id"], x.AGENT)), status=SLOT_BLOCKED_BY_POSTURE
    )

    reviewed = ok(
        api.review_obligation_resolution(
            obligation["id"],
            f.review_resolution_payload("ACCEPT", review_note="Deck rebuilt and inspected"),
            x.DIRECTOR,
        )
    )
    assert_fields(reviewed, status=OBLIGATION_RESOLVED)
    assert_fields(ok(api.get_home(home["id"], x.OPS)), leasing_posture=POSTURE_RESTRICTED)
    assert_fields(
        ok(api.get_showing_slot(slot["id"], x.AGENT)),
        status=SLOT_AVAILABLE,
        starts_at="2026-08-20T15:00:00Z",
    )


def test_a_minor_obligation_moves_no_window_and_a_freeze_spares_the_booked_one(api):
    """Doubly conditional: MINOR changes nothing, and CRITICAL never touches a BOOKED tour.

    PRD SS2.8: "Obligations whose `severity` is `MINOR` never affect posture, in any status",
    and "Whenever a recomputation lands the posture on `FROZEN`, every showing window on that
    home whose `status` is `AVAILABLE` moves `AVAILABLE` -> `BLOCKED_BY_POSTURE`. ... Windows
    whose `status` is `BOOKED` are never touched by posture recomputation, so a tour a prospect
    has already scheduled is never silently cancelled."  PRD SS3.9: "a `MINOR` obligation
    changes nothing at all", while a `CRITICAL` one "drives the posture to `FROZEN`".  PRD
    SS2.9: "For every home, `booked_showing_count` always equals the number of showing windows
    on that home whose `status` is `BOOKED`."

    Design: Corner/state_machines/posture_cascade_skips_minor_obligations_and_booked_slots
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    prospect = x.verified_prospect(api, market["id"])
    booked_slot = x.available_slot(api, home["id"])
    open_slot = x.available_slot(
        api,
        home["id"],
        starts_at="2026-08-20T16:00:00Z",
        ends_at="2026-08-20T16:30:00Z",
        access_mode="LOCKBOX",
    )
    ok(
        api.book_showing_slot(
            booked_slot["id"], f.book_slot_payload(prospect.prospect_id), prospect.headers
        )
    )

    minor = x.open_obligation(api, home["id"], severity="MINOR", description="Mailbox needs paint")
    assert_fields(ok(api.get_home(home["id"], x.OPS)), leasing_posture=POSTURE_RESTRICTED)
    assert_fields(ok(api.get_showing_slot(open_slot["id"], x.AGENT)), status=SLOT_AVAILABLE)
    assert_fields(ok(api.get_showing_slot(booked_slot["id"], x.AGENT)), status=SLOT_BOOKED)

    critical = x.open_obligation(
        api,
        home["id"],
        obligation_type="INSURANCE_DEFICIENCY",
        severity="CRITICAL",
        description="Wind coverage lapsed",
        due_on="2026-11-30",
    )
    home_after = ok(api.get_home(home["id"], x.OPS))
    assert_fields(home_after, leasing_posture=POSTURE_FROZEN, booked_showing_count=1)
    assert_fields(
        ok(api.get_showing_slot(open_slot["id"], x.AGENT)), status=SLOT_BLOCKED_BY_POSTURE
    )
    assert_fields(
        ok(api.get_showing_slot(booked_slot["id"], x.AGENT)),
        status=SLOT_BOOKED,
        prospect_id=prospect.prospect_id,
    )
    assert_fields(
        ok(api.get_compliance_obligation(minor["id"], x.COMPLIANCE)), status=OBLIGATION_OPEN
    )
    assert_fields(
        ok(api.get_compliance_obligation(critical["id"], x.COMPLIANCE)), status=OBLIGATION_OPEN
    )
