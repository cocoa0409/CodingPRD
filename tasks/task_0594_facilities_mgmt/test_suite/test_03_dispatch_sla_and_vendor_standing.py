"""Dispatch, the SLA clocks, and vendor standing: the inclusive response deadline,
the strike ladder up to suspension, the four-level completion cascade, and the two
performance-score variants that legitimately disagree on identical data.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_dispatch,
    assert_vendor,
    assert_work_order,
    complete_dispatch,
    create_asset,
    create_building,
    create_vendor,
    create_work_order,
    dispatch_work_order,
    make_vendor_tech_headers,
    read_dispatch,
    read_vendor,
    read_work_order,
    set_clock,
    setup_building_and_vendor,
    setup_suspended_vendor_via_missed_shifts,
    setup_vendor_at_third_strike_with_pending_offer,
    setup_vendor_with_four_completed_dispatches,
    setup_work_order_dispatched,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]


# ---------------------------------------------------------------------------
# The two performance-score variants
# ---------------------------------------------------------------------------
def test_rolling_performance_score_ages_out_the_old_breach(api):
    """PRD §3.2: "The **rolling** score, exposed as `performance_score`, considers only
    the 3 most recent entries of that ordered set, so that old failures age out of the
    figure a facility manager reads before choosing a vendor."
    PRD §3.2: "Otherwise compute three rates over the selected dispatches: the response
    rate is the fraction of them whose `sla_response_met` is true; the resolve rate is
    the fraction whose `sla_resolve_met` is true; and the QA rate is the fraction whose
    work order has a `failed_qa_count` of zero. The score is 100 multiplied by the sum
    of the response rate weighted at 0.4, the resolve rate weighted at 0.3, and the QA
    rate weighted at 0.3, rounded half up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/vendor_rolling_window_vs_lifetime_performance_score
    """
    ctx = setup_vendor_with_four_completed_dispatches()
    vendor = validate_success(api.get_vendor(ctx["vendor"]["id"], FM))
    assert_vendor(vendor)

    assert vendor["completed_dispatch_count"] == 4
    # The three most recent completions all met both legs and carry no failed QA.
    assert vendor["performance_score"] == pytest.approx(100.00, abs=0.01)


def test_lifetime_performance_score_retains_the_old_breach(api):
    """PRD §3.2: "The **lifetime** score, exposed as `lifetime_performance_score`,
    considers every completed dispatch the vendor has ever had; with four or more
    dispatches and one old breach the two figures legitimately disagree on identical
    data."
    PRD §3.2: "A vendor earns one strike whenever a dispatch of theirs completes having
    missed either SLA leg, and one strike whenever one of their soft-service shifts is
    marked as missed during an operational epoch run."
    PRD §3.2: "When the incremented count reaches exactly 2, the vendor's `status`
    becomes `PROBATION`; when it reaches 3 or more, the vendor's `status` becomes
    `SUSPENDED`."

    Design: Difficulty/dual_variant_calc/vendor_rolling_window_vs_lifetime_performance_score
    """
    ctx = setup_vendor_with_four_completed_dispatches()
    vendor = read_vendor(ctx["vendor"]["id"])
    assert_vendor(vendor)

    # Over all four: response rate 3/4, resolve rate 4/4, QA rate 4/4
    # -> 100 * (0.4*0.75 + 0.3*1.0 + 0.3*1.0) = 90.00
    assert vendor["lifetime_performance_score"] == pytest.approx(90.00, abs=0.01)
    assert vendor["lifetime_performance_score"] != vendor["performance_score"], (
        "the two variants must disagree once an old breach has aged out of the window"
    )
    assert vendor["strike_count"] == 1
    assert vendor["status"] == "ACTIVE", "one strike is short of PROBATION"


# ---------------------------------------------------------------------------
# The completion cascade: breach -> strike -> suspension -> board reshuffle
# ---------------------------------------------------------------------------
def test_third_strike_on_completion_suspends_the_vendor(api):
    """PRD §3.5: "At the second level, the vendor's counters move: if either SLA leg was
    missed, the vendor's `strike_count` rises by 1; `completed_dispatch_count` rises by
    1 regardless; and both `performance_score` and `lifetime_performance_score` are
    recomputed. At the third level, the strike ladder is consulted: a `strike_count`
    that has just reached exactly 2 puts the vendor into `PROBATION`, and one that has
    reached 3 or more puts it into `SUSPENDED`."
    PRD §3.5: "The dispatch's `penalty_pct` is then the sum of 0.10 if the response leg
    was missed and 0.15 if the resolve leg was missed, capped at 0.25; if both legs were
    met it is 0."

    Design: Difficulty/transitive_cascade/dispatch_completion_strike_suspension_cancels_other_offered_dispatch
    """
    ctx = setup_vendor_at_third_strike_with_pending_offer()
    vendor_id = ctx["vendor"]["id"]
    assert ctx["vendor"]["strike_count"] == 2
    assert ctx["vendor"]["status"] == "PROBATION"

    dispatch = validate_success(
        api.complete_dispatch(
            ctx["third_dispatch"]["id"],
            {"actual_labor_hours": 1, "actual_parts_cost": 0},
            make_vendor_tech_headers(vendor_id),
        )
    )
    assert_dispatch(dispatch)

    # L1 — the completion itself: the response leg was missed, the resolve leg was met.
    assert dispatch["status"] == "COMPLETED"
    assert dispatch["sla_response_met"] is False
    assert dispatch["sla_resolve_met"] is True
    assert dispatch["penalty_pct"] == pytest.approx(0.10, abs=0.001)

    # L2/L3 — the breach strikes the vendor a third time, which suspends it.
    vendor = read_vendor(vendor_id)
    assert vendor["strike_count"] == 3
    assert vendor["status"] == "SUSPENDED"

    # The completing order itself is untouched by the suspension.
    assert read_work_order(ctx["third_work_order"]["id"])["status"] == "PENDING_QA"


def test_vendor_suspension_cancels_its_other_offered_dispatch_and_reverts_that_order(api):
    """PRD §3.2: "At the moment a vendor crosses into `SUSPENDED` — whether through a
    completion breach or a missed shift — every dispatch of that vendor still sitting in
    `OFFERED` moves `OFFERED → CANCELLED`, and each of those cancelled dispatches' work
    orders reverts `DISPATCHED → NEW`, with `dispatched_at`, `sla_response_due_at`, and
    `sla_resolve_due_at` all cleared back to unset."
    PRD §3.5: "At the fourth level, if the vendor has just been suspended, every one of
    its dispatches still in `OFFERED` — anywhere in the portfolio, on any building —
    moves `OFFERED → CANCELLED`, and each of those dispatches' work orders reverts
    `DISPATCHED → NEW` with `dispatched_at` and both SLA deadlines cleared."

    Design: Difficulty/transitive_cascade/dispatch_completion_strike_suspension_cancels_other_offered_dispatch
    """
    ctx = setup_vendor_at_third_strike_with_pending_offer()
    vendor_id = ctx["vendor"]["id"]
    assert ctx["pending_dispatch"]["status"] == "OFFERED"
    assert ctx["pending_work_order"]["status"] == "DISPATCHED"

    complete_dispatch(ctx["third_dispatch"]["id"], vendor_id, actual_labor_hours=1,
                      actual_parts_cost=0)

    assert read_vendor(vendor_id)["status"] == "SUSPENDED"

    # L4 — the still-OFFERED dispatch is swept up and its order goes back on the board.
    swept = read_dispatch(ctx["pending_dispatch"]["id"])
    assert swept["status"] == "CANCELLED"

    reverted = read_work_order(ctx["pending_work_order"]["id"])
    assert_work_order(reverted)
    assert reverted["status"] == "NEW"
    assert reverted["dispatched_at"] is None
    assert reverted["sla_response_due_at"] is None
    assert reverted["sla_resolve_due_at"] is None


# ---------------------------------------------------------------------------
# The inclusive SLA response deadline
# ---------------------------------------------------------------------------
def test_accepting_at_exactly_the_response_deadline_is_a_hit(api):
    """PRD §3.5: "It then evaluates `sla_response_met`, which is true when `accepted_at`
    is at or before `sla_response_due_at` — the boundary is inclusive, so accepting at
    exactly the deadline is a hit, not a miss."
    PRD §3.5: "`sla_response_due_at` is `dispatched_at` advanced by the vendor's
    `sla_response_minutes` minutes, and `sla_resolve_due_at` is `dispatched_at` advanced
    by the vendor's `sla_resolve_minutes` minutes."

    Design: Difficulty/boundary_precision_check/sla_response_met_at_exact_deadline_inclusive
    """
    ctx = setup_work_order_dispatched(
        clock="2026-05-04T09:00:00Z",
        wo_overrides={"priority": "P3", "estimated_labor_hours": 1,
                      "estimated_parts_cost": 0},
    )
    # dispatched at 09:00 with a 60-minute response window -> due at exactly 10:00.
    set_clock("2026-05-04T10:00:00Z")

    dispatch = validate_success(
        api.accept_dispatch(ctx["dispatch"]["id"],
                            make_vendor_tech_headers(ctx["vendor"]["id"]))
    )
    assert_dispatch(dispatch)
    assert dispatch["sla_response_met"] is True, (
        "accepting at exactly sla_response_due_at is inclusive and therefore met"
    )
    assert dispatch["status"] == "ACCEPTED"


def test_response_minutes_are_whole_minutes_and_sla_state_stays_within(api):
    """PRD §3.5: "Acceptance stamps `accepted_at` from the clock and computes
    `response_minutes` as the whole minutes elapsed from `dispatched_at` to
    `accepted_at`, taking the elapsed seconds and discarding the remainder below a whole
    minute."
    PRD §3.5: "When the response is missed, the work order's `sla_state` moves to
    `RESPONSE_BREACHED`."
    PRD §3.5: "A `VendorTech` may **accept** an offer, which moves the dispatch
    `OFFERED → ACCEPTED` and the work order `DISPATCHED → IN_PROGRESS`."

    Design: Difficulty/boundary_precision_check/sla_response_met_at_exact_deadline_inclusive
    """
    ctx = setup_work_order_dispatched(
        clock="2026-05-04T09:00:00Z",
        wo_overrides={"priority": "P3", "estimated_labor_hours": 1,
                      "estimated_parts_cost": 0},
    )
    set_clock("2026-05-04T10:00:00Z")

    dispatch = validate_success(
        api.accept_dispatch(ctx["dispatch"]["id"],
                            make_vendor_tech_headers(ctx["vendor"]["id"]))
    )
    assert dispatch["response_minutes"] == 60

    work_order = read_work_order(ctx["work_order"]["id"])
    assert work_order["sla_state"] == "WITHIN", (
        "the deadline was met, so no breach is recorded"
    )
    assert work_order["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Vendor eligibility gates dispatch
# ---------------------------------------------------------------------------
def test_dispatch_to_a_suspended_vendor_is_refused(api):
    """PRD §3.2: "A vendor in `ACTIVE` or `PROBATION` standing may be given new work; a
    `SUSPENDED` vendor may not, and any attempt to dispatch to one is refused with
    `ERR_VENDOR_SUSPENDED`."
    PRD §3.8: "Each miss adds 1 to the vendor's `strike_count` and runs the same
    standing ladder as a completion breach — exactly 2 strikes puts the vendor in
    `PROBATION`, 3 or more puts it in `SUSPENDED`, and a fresh suspension cancels that
    vendor's `OFFERED` dispatches everywhere and reverts their work orders
    `DISPATCHED → NEW`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_creation_depends_on_vendor_status
    """
    ctx = setup_suspended_vendor_via_missed_shifts(clock_after="2026-05-04T09:00:00Z")
    suspended = ctx["suspended_vendor"]
    assert suspended["strike_count"] == 3
    assert suspended["status"] == "SUSPENDED"

    work_order = create_work_order(ctx["building"]["id"], priority="P3",
                                   estimated_labor_hours=1, estimated_parts_cost=0)

    response = api.create_dispatch(
        work_order["id"],
        {"vendor_id": suspended["id"],
         "expected_work_order_version": work_order["version"]},
        FM,
    )
    validate_error(response, ApiErrorId.ERR_VENDOR_SUSPENDED.value)
    assert response.status_code == 409

    assert read_work_order(work_order["id"])["status"] == "NEW"


def test_dispatch_to_a_probation_vendor_is_accepted(api):
    """PRD §3.2: "A vendor in `ACTIVE` or `PROBATION` standing may be given new work; a
    `SUSPENDED` vendor may not, and any attempt to dispatch to one is refused with
    `ERR_VENDOR_SUSPENDED`."
    PRD §3.5: "Dispatching an order sends it to a vendor and moves it
    `NEW → DISPATCHED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_creation_depends_on_vendor_status
    """
    ctx = setup_suspended_vendor_via_missed_shifts(clock_after="2026-05-04T09:00:00Z")
    probation = ctx["probation_vendor"]
    assert probation["strike_count"] == 2
    assert probation["status"] == "PROBATION"

    work_order = create_work_order(ctx["building"]["id"], priority="P3",
                                   estimated_labor_hours=1, estimated_parts_cost=0)

    dispatch = validate_success(
        api.create_dispatch(
            work_order["id"],
            {"vendor_id": probation["id"],
             "expected_work_order_version": work_order["version"]},
            FM,
        ),
        201,
    )
    assert dispatch["status"] == "OFFERED"
    assert read_work_order(work_order["id"])["status"] == "DISPATCHED"


# ---------------------------------------------------------------------------
# Dispatch actionability, decline, and trade competence
# ---------------------------------------------------------------------------
def test_accepting_an_already_accepted_dispatch_is_refused(api):
    """PRD §3.5: "Accepting or declining a dispatch that is not in `OFFERED` is refused
    with `ERR_DISPATCH_NOT_ACTIONABLE` (HTTP 409), as is completing a dispatch that is
    not in `ACCEPTED`."

    Design: Corner/state_machines/accept_dispatch_twice_rejected_as_not_actionable
    """
    ctx = setup_work_order_dispatched(
        clock="2026-05-04T09:00:00Z",
        wo_overrides={"priority": "P3", "estimated_labor_hours": 1,
                      "estimated_parts_cost": 0},
    )
    set_clock("2026-05-04T09:30:00Z")
    headers = make_vendor_tech_headers(ctx["vendor"]["id"])
    first = validate_success(api.accept_dispatch(ctx["dispatch"]["id"], headers))
    accepted_at = first["accepted_at"]

    response = api.accept_dispatch(ctx["dispatch"]["id"], headers)
    validate_error(response, ApiErrorId.ERR_DISPATCH_NOT_ACTIONABLE.value)
    assert response.status_code == 409

    dispatch = read_dispatch(ctx["dispatch"]["id"])
    assert dispatch["status"] == "ACCEPTED"
    assert dispatch["accepted_at"] == accepted_at, "the refused call must not re-stamp"
    assert dispatch["accepted_at"].startswith("2026-05-04T09:30:00")
    assert read_work_order(ctx["work_order"]["id"])["status"] == "IN_PROGRESS"


def test_declining_reverts_the_order_to_new_on_the_standard_rate_basis(api):
    """PRD §3.5: "The dispatch moves `OFFERED → DECLINED` and the work order reverts
    `DISPATCHED → NEW`. Its `dispatched_at`, `sla_response_due_at`, and
    `sla_resolve_due_at` are all cleared back to unset — a superseded or declined
    offer's timing is discarded entirely — and its `estimated_amount` is recomputed by
    the provisional variant back onto the standard labour rate basis, since no vendor is
    attached any more; any funding project's `committed_amount` moves by that estimate
    delta."
    PRD §3.5: "The declining vendor's `strike_count` is untouched: a decline is a
    refusal, not a breach."

    Design: Corner/state_machines/dispatch_decline_reverts_order_to_new_and_restores_standard_rate_estimate
    """
    ctx = setup_work_order_dispatched(
        clock="2026-05-04T09:00:00Z",
        wo_overrides={"priority": "P3", "estimated_labor_hours": 4,
                      "estimated_parts_cost": 0},
    )

    dispatch = validate_success(
        api.decline_dispatch(
            ctx["dispatch"]["id"],
            make_vendor_tech_headers(ctx["vendor"]["id"]),
            {"reason": "No crew available"},
        )
    )
    assert dispatch["status"] == "DECLINED"

    work_order = read_work_order(ctx["work_order"]["id"])
    assert_work_order(work_order)
    assert work_order["status"] == "NEW"
    assert work_order["dispatched_at"] is None
    assert work_order["sla_response_due_at"] is None
    assert work_order["sla_resolve_due_at"] is None
    # Back onto the house rate: 4h * 80.00 = 320.00, no P3 surcharge, no parts.
    assert work_order["estimated_amount"] == pytest.approx(320.00, abs=0.01)

    assert read_vendor(ctx["vendor"]["id"])["strike_count"] == 0


def test_dispatching_a_wrong_trade_vendor_to_an_asset_is_refused(api):
    """PRD §3.5: "And when the order names an asset, the vendor's `trade` must equal the
    asset's `category` — a plumber cannot be sent to a lift, and the mismatch is refused
    with `ERR_VENDOR_TRADE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/vendor_trade_mismatch_on_dispatch_rejected
    """
    set_clock("2026-05-04T09:00:00Z")
    building = create_building()
    asset = create_asset(building["id"], asset_tag="AHU-01", category="HVAC",
                         criticality="STANDARD")
    lift_vendor = create_vendor(name="LiftCo", trade="ELEVATOR", hourly_rate=90.00,
                                sla_response_minutes=60, sla_resolve_minutes=240)
    work_order = create_work_order(
        building["id"], asset_id=asset["id"], wo_type="CORRECTIVE", priority="P3",
        estimated_labor_hours=2, estimated_parts_cost=0,
    )
    version_at_create = work_order["version"]

    response = api.create_dispatch(
        work_order["id"],
        {"vendor_id": lift_vendor["id"],
         "expected_work_order_version": version_at_create},
        FM,
    )
    validate_error(response, ApiErrorId.ERR_VENDOR_TRADE_MISMATCH.value)
    assert response.status_code == 422

    reread = read_work_order(work_order["id"])
    assert reread["status"] == "NEW"
    assert reread["dispatched_at"] is None
    assert reread["version"] == version_at_create, "the refused dispatch mutated nothing"

    _, meta = validate_paginated(
        api.list_dispatches(FM, params={"work_order_id": work_order["id"]})
    )
    assert meta["total_count"] == 0
