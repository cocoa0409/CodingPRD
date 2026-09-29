"""Initial states, the transitions that are allowed, and the ones that are not.

A row's status dimension is only correct if the entry point, the accepted edges, the
refused edges and the terminal lockdowns all hold at once -- and if a refused edge writes
nothing at all, neither on the row itself nor on the ledgers it would have moved.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import ERR_INVALID_STATE
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_home_dimensions,
    assert_money_group,
    created,
    failed,
    ok,
)
from test_helpers.constants import (
    ASSET_ACQUIRED,
    ASSET_PIPELINE,
    ASSET_STABILIZED,
    CASE_SUBMITTED,
    CLOCK_AUG_01,
    IDENTITY_VERIFIED,
    OCC_VACANT,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    PROJECT_RENT_READY,
    PROJECT_SCOPING,
    SLOT_AVAILABLE,
    WO_COMPLETED,
    WO_PENDING_DISPATCH,
)


def test_a_new_home_enters_both_dimensions_at_their_initial_state(api):
    """No activation call: PIPELINE and VACANT together, with clause 5 already deciding.

    PRD SS2.8: "`asset_status` tracks the acquisition and disposition axis and takes one of
    `PIPELINE`, `PASSED`, `ACQUIRED`, `RENOVATING`, `STABILIZED`, `DISPOSITION_APPROVED` or
    `DISPOSED`; it starts at `PIPELINE` ... `occupancy_status` tracks the leasing axis and
    takes one of `VACANT`, `RESERVED` or `OCCUPIED`; it starts at `VACANT`".  Clause 5 of the
    posture ladder reads "Otherwise, if `asset_status` is `PIPELINE` or `ACQUIRED`, the posture
    is `RESTRICTED`", and the computed read "returns `home_id`, the resulting `leasing_posture`,
    `deciding_clause` as the integer number (1 through 6) of the clause that produced it,
    `blocking_obligation_ids` as the identifiers of the obligations that contributed to the
    decision, and `binder_expired` as a boolean stating whether the second clause's condition
    currently holds."

    Design: Corner/state_machines/home_dimensions_start_at_pipeline_and_vacant
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)

    home = created(api.create_home(f.home_payload(market["id"]), x.ANALYST))
    assert_home_dimensions(home, ASSET_PIPELINE, OCC_VACANT, POSTURE_RESTRICTED)

    decision = ok(api.get_leasing_posture(home["id"], x.OPS))
    assert_fields(
        decision,
        home_id=home["id"],
        leasing_posture=POSTURE_RESTRICTED,
        deciding_clause=5,
        blocking_obligation_ids=[],
        binder_expired=False,
    )


def test_submitting_a_case_reprices_it_and_leaves_the_home_in_pipeline(api):
    """Submit is the pricing gate: the whole underwritten group plus a stamped submitter.

    PRD SS3.2: "A case sits in `DRAFT` until its analyst submits it, which requires the case to
    be in `DRAFT` and to carry at least one planned scope line, and which moves it `DRAFT ->
    SUBMITTED` while stamping `submitted_by_user_id` from the caller's `X-User-ID`. Submission
    recomputes `planned_renovation_budget_cents` and the whole underwritten group *before*
    checking the yield floor, so a stale draft is never approved on stale numbers."  The
    numbers are the PRD's own worked case: "Rounding per line gives 559906, 627761 and 292176
    for a total of 1479843", and that case "yields a basis of 27229843 ... effective gross
    income of 2425200 ... net operating income of 1521184 and an underwritten yield of 559
    basis points."  Only the committee's approval moves the home: "An approval moves the case
    `SUBMITTED -> APPROVED` ... the home advances `PIPELINE -> ACQUIRED`".

    Design: Corner/state_machines/underwriting_case_submit_prices_the_case_and_advances_to_submitted
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    templates = x.three_trade_catalogue(api)
    home = x.create_home(api, market["id"])
    case = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home["id"],
                home["version"],
                [
                    f.scope_line(templates.floor["id"], 1150),
                    f.scope_line(templates.hvac["id"], 1),
                    f.scope_line(templates.paint["id"], 1),
                ],
            ),
            x.ANALYST,
        )
    )

    submitted = ok(api.submit_underwriting_case(case["id"], {}, x.ANALYST))
    assert_fields(
        submitted,
        status=CASE_SUBMITTED,
        submitted_by_user_id="analyst-1",
        revision_round=0,
        underwritten_yield_on_cost_bps=559,
    )
    assert_money_group(
        submitted,
        planned_renovation_budget_cents=1479843,
        underwritten_all_in_basis_cents=27229843,
        underwritten_effective_gross_income_cents=2425200,
        underwritten_noi_cents=1521184,
    )
    assert_home_dimensions(
        ok(api.get_home(home["id"], x.ANALYST)), ASSET_PIPELINE, OCC_VACANT
    )


def test_a_second_submit_on_the_same_case_is_refused_and_rewrites_nothing(api):
    """SUBMITTED is not a `from` state for submit, and the failed replay keeps analyst-1.

    PRD SS3.2: "`APPROVED`, `REJECTED` and `SUPERSEDED` are terminal: any submit, decision or
    rework attempted against a case in one of those states is refused with
    `ERR_INVALID_STATE`, as is a rework of a case that is not in `REVISION_REQUESTED` or a
    submit of a case that is not in `DRAFT`."  Because submission "moves it `DRAFT ->
    SUBMITTED` while stamping `submitted_by_user_id` from the caller's `X-User-ID`", a refused
    second submit by a different analyst must leave the first stamp in place.  PRD SS2.9: "if a
    guard rejects the operation, nothing at all is written".

    Design: Corner/state_machines/underwriting_case_second_submit_returns_409
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    templates = x.three_trade_catalogue(api)
    home = x.create_home(api, market["id"])
    case = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home["id"],
                home["version"],
                [
                    f.scope_line(templates.floor["id"], 1150),
                    f.scope_line(templates.hvac["id"], 1),
                    f.scope_line(templates.paint["id"], 1),
                ],
            ),
            x.ANALYST,
        )
    )
    ok(api.submit_underwriting_case(case["id"], {}, x.ANALYST))

    failed(
        api.submit_underwriting_case(case["id"], {}, x.ANALYST_2), ERR_INVALID_STATE
    )

    stored = ok(api.get_underwriting_case(case["id"], x.ANALYST))
    assert_fields(
        stored,
        status=CASE_SUBMITTED,
        submitted_by_user_id="analyst-1",
        underwritten_yield_on_cost_bps=559,
    )
    assert_home_dimensions(
        ok(api.get_home(home["id"], x.ANALYST)), ASSET_PIPELINE, OCC_VACANT
    )


def test_completing_a_pending_work_order_is_refused_and_records_no_actual(api):
    """PENDING_DISPATCH is not a completion source, so the ledger keeps the quote.

    PRD SS3.5: "Completion is reachable from exactly two states, and each has its own actor: a
    vendor-channel work order is completed from `ACCEPTED` by the assigned `Vendor`, and an
    in-house work order is completed from `IN_PROGRESS` by an `OperationsManager`. Any other
    originating status is refused with `ERR_INVALID_STATE`."  PRD SS3.3 fixes what the refused
    call must not have written: "A new work order is created in `PENDING_DISPATCH` with
    `vendor_id` the empty string, `actual_cost_cents` 0, `completed_on` the empty string".  PRD
    SS2.9: "For every renovation project, `committed_cost_cents` plus `budget_remaining_cents`
    always equals `approved_budget_cents`", and "if a guard rejects the operation, nothing at
    all is written, including the cascade targets."

    Design: Corner/state_machines/work_order_complete_from_pending_dispatch_returns_409
    """
    ctx = x.acquired_home(api)
    project = created(
        api.create_renovation_project(f.renovation_project_payload(ctx.home_id, 400000), x.OPS)
    )
    order = created(
        api.create_work_order(
            f.work_order_payload(ctx.home_id, ctx.paint_id, project_id=project["id"]), x.OPS
        )
    )
    assert_fields(order, status=WO_PENDING_DISPATCH)

    failed(
        api.complete_work_order(
            order["id"], f.complete_work_order_payload(295000, "2026-08-12"), x.OPS
        ),
        ERR_INVALID_STATE,
    )

    stored = ok(api.get_work_order(order["id"], x.OPS))
    assert_fields(stored, status=WO_PENDING_DISPATCH)
    assert_money_group(stored, actual_cost_cents=0)
    assert_absent_or_empty(stored, "completed_on")

    ledger = ok(api.get_renovation_project(project["id"], x.OPS))
    assert_fields(ledger, status=PROJECT_SCOPING)
    assert_money_group(
        ledger, committed_cost_cents=300000, budget_remaining_cents=100000
    )
    assert_home_dimensions(
        ok(api.get_home(ctx.home_id, x.OPS)), ASSET_ACQUIRED, OCC_VACANT
    )


def test_a_completed_work_order_refuses_the_void_and_keeps_its_settlement(api):
    """COMPLETED is terminal, so the compensating unwind never runs on the ledger.

    PRD SS3.5: "An `OperationsManager` may void a work order with a `void_reason` from any of
    `PENDING_DISPATCH`, `DISPATCHED`, `ACCEPTED` or `IN_PROGRESS`; a work order already
    `COMPLETED` or already `VOIDED` refuses the void with `ERR_INVALID_STATE`."  Had it not
    been refused, "if the work order named a `project_id`, that project's
    `committed_cost_cents` decreases by `quoted_cost_cents` and its `budget_remaining_cents`
    increases by the same amount".  The settlement it must not disturb is the PRD's own: "If
    the turn ran 32 days, the overage is 2, which falls in the 1-to-3 band for a
    `holdback_rate_bps` of 1000" -- here on a gross of 300000, for a raw holdback of 30000
    under a cap of 45000 and a net of 270000.

    Design: Corner/state_machines/completed_work_order_cannot_be_voided
    """
    ctx = x.renovated_home(api)
    completed = ok(api.get_work_order(ctx.work_order_id, x.OPS))
    assert_fields(completed, status=WO_COMPLETED)

    failed(
        api.void_work_order(
            ctx.work_order_id, f.void_work_order_payload("Duplicate scope line"), x.OPS
        ),
        ERR_INVALID_STATE,
    )

    stored = ok(api.get_work_order(ctx.work_order_id, x.OPS))
    assert_fields(stored, status=WO_COMPLETED)
    assert_money_group(stored, actual_cost_cents=300000)
    assert_absent_or_empty(stored, "void_reason")

    project = ok(api.get_renovation_project(ctx.project_id, x.OPS))
    assert_fields(project, status=PROJECT_RENT_READY, turn_days=32, holdback_rate_bps=1000)
    assert_money_group(
        project,
        committed_cost_cents=300000,
        budget_remaining_cents=100000,
        gross_turn_cost_cents=300000,
        vendor_holdback_cents=30000,
        net_turn_cost_cents=270000,
    )
    assert_home_dimensions(
        ok(api.get_home(ctx.home_id, x.OPS)), ASSET_STABILIZED, OCC_VACANT, POSTURE_OPEN
    )


def test_cancelling_a_booked_window_returns_it_to_the_calendar_and_decrements(api):
    """Four writes in one call, and the released window is immediately re-bookable.

    PRD SS3.7: "From `BOOKED` the window returns `BOOKED` -> `AVAILABLE`, its `prospect_id` is
    cleared, the `reason` is stored in `cancel_reason`, and the home's `booked_showing_count`
    decreases by 1, restoring the count invariant; the acting role may be the booking
    `Prospect`, whose `X-User-ID` must equal the stored `prospect_id`, or a `LeasingAgent`."
    PRD SS2.9: "For every home, `booked_showing_count` always equals the number of showing
    windows on that home whose `status` is `BOOKED`."  The prospect is the PRD's own verified
    one: "The same prospect then verifies with a document score of 9200, liveness true, a
    verified income of 560000, a device reputation of 8800 and 15 km of geo distance ... and
    the score falls to 1093 basis points".

    Design: Corner/state_machines/slot_cancel_from_booked_returns_slot_to_available_and_decrements_count
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    prospect = x.verified_prospect(api, market["id"])
    assert_fields(
        prospect.verified, identity_status=IDENTITY_VERIFIED, fraud_risk_score_bps=1093
    )
    slot = x.available_slot(api, home["id"])
    booked = ok(
        api.book_showing_slot(
            slot["id"], f.book_slot_payload(prospect.prospect_id), prospect.headers
        )
    )
    assert_fields(booked, prospect_id=prospect.prospect_id)
    assert_fields(ok(api.get_home(home["id"], x.AGENT)), booked_showing_count=1)

    released = ok(
        api.cancel_showing_slot(
            slot["id"], f.cancel_slot_payload("Prospect schedule conflict"), prospect.headers
        )
    )
    assert_fields(
        released, status=SLOT_AVAILABLE, cancel_reason="Prospect schedule conflict"
    )
    assert_absent_or_empty(released, "prospect_id")
    assert_fields(ok(api.get_home(home["id"], x.AGENT)), booked_showing_count=0)
    assert_fields(
        ok(api.get_prospect(prospect.prospect_id, x.AGENT)),
        identity_status=IDENTITY_VERIFIED,
        fraud_risk_score_bps=1093,
    )
