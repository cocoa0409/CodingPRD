"""Cascade & compensating-invariant tests: the depth-3 change-order cascade, the
project-cancel fan-out, change-order reject/accept invariants, and install-cancel
posture reversal.

Queue A: transitive_cascade, compensating_invariant.
Queue B: consistency_model corner instance.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    make_customer_headers,
    fixtures as fx,
)

_SALES = TEST_USERS["sales_rep_headers"]
_SCHED = TEST_USERS["scheduler_headers"]


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================

def test_change_order_accept_cascade_cancels_install_and_reverts_project(api):
    """PRD §3.7: "**Hop two:** if a material order for this quote exists and is in
    `PLACED` or `READY`, the `lead_time_delta_days` is added to that order's
    `lead_extension_days` and its `ready_at` is recomputed. **Hop three:** if an
    install job references that material order, is in `SCHEDULED`, and its
    `window_start` falls before the newly recomputed `ready_at`, that install job
    is transitioned `SCHEDULED → CANCELLED` and the project is reverted
    `IN_PRODUCTION → SOLD`."

    Design: Difficulty/transitive_cascade/change_order_accept_cascade_depth3_to_install_cancel
    """
    fx.reset_clock()
    # Approved REFACE/WOOD_VENEER quote (lf=25,d=18); place material order
    # (base lead 33 days -> ready_at 2026-05-04); schedule install before that
    # under an extended ready_at; raise +4lf/+2d (lead +11 -> ready_at 2026-05-15).
    cust, proj, meas, quote = fx.setup_approved_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    mo = fx.place_material_order(proj["id"], quote["id"])
    assert mo["ready_at"].startswith("2026-05-04"), \
        f"setup expected ready_at 2026-05-04, got {mo['ready_at']}"
    crew = fx.create_crew(skill_finishes=("WOOD_VENEER",), daily_job_capacity=2)
    ij = fx.schedule_install_job(proj["id"], mo["id"], crew["id"],
                                 window_start="2026-05-05T08:00:00Z",
                                 window_end="2026-05-05T17:00:00Z")
    co = fx.raise_change_order(quote["id"], delta_linear_feet=4, delta_door_count=2, rush=False)

    accepted = validate_success(api.accept_change_order(
        co["id"], {"expected_quote_version": quote["version"]},
        make_customer_headers(cust["id"])))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["price_delta_cents"] == 110000, \
        f"expected price delta 110000, got {accepted['price_delta_cents']}"

    quote_read = validate_success(api.get_quote(quote["id"], _SALES))
    mo_read = validate_success(api.get_material_order(mo["id"], _SCHED))
    ij_read = validate_success(api.get_install_job(ij["id"], _SCHED))
    proj_read = validate_success(api.get_project(proj["id"], _SALES))
    # firm 715000 + 110000 = 825000; lead_extension 11; ready_at 2026-05-15.
    assert quote_read["firm_total_cents"] == 825000, \
        f"expected re-priced firm 825000, got {quote_read['firm_total_cents']}"
    assert mo_read["lead_extension_days"] == 11, \
        f"expected lead_extension_days 11, got {mo_read['lead_extension_days']}"
    assert mo_read["ready_at"].startswith("2026-05-15"), \
        f"expected ready_at pushed to 2026-05-15, got {mo_read['ready_at']}"
    assert ij_read["status"] == "CANCELLED", \
        f"expected install job CANCELLED, got {ij_read['status']}"
    assert proj_read["status"] == "SOLD", \
        f"expected project reverted to SOLD, got {proj_read['status']}"


def test_change_order_accept_reprices_quote_firm_total(api):
    """PRD §3.7: "**Hop one:** the accepted change order re-prices the quote —
    `price_delta_cents` is added to the project price by recomputing the quote's
    `firm_total_cents` — and the quote's `version` increments by one."

    Design: Difficulty/transitive_cascade/change_order_accept_cascade_depth3_to_install_cancel
    """
    cust, proj, meas, quote, co = fx.setup_approved_quote_with_pending_change_order(
        delta_linear_feet=4, delta_door_count=2, rush=False,
        scope="REFACE", finish_code="WOOD_VENEER")
    validate_success(api.accept_change_order(
        co["id"], {"expected_quote_version": quote["version"]},
        make_customer_headers(cust["id"])))
    quote_read = validate_success(api.get_quote(quote["id"], _SALES))
    # 715000 + 110000 = 825000; version bumped beyond the approve version.
    assert quote_read["firm_total_cents"] == 825000, \
        f"expected re-priced firm 825000, got {quote_read['firm_total_cents']}"
    assert quote_read["version"] == quote["version"] + 1, \
        f"accept must bump quote version by 1: {quote['version']} -> {quote_read['version']}"


def test_project_cancel_cascade_cancels_measure_and_supersedes_quote(api):
    """PRD §3.1: "Cancellation cancels every measure on the project that is still in
    the `SCHEDULED` state and marks any active quote as superseded."

    Design: Difficulty/transitive_cascade/project_cancel_cascade_depth2_measure_and_quote
    """
    cust, proj, meas_a = fx.setup_project_with_completed_measure(
        linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    quote = fx.create_draft_quote(proj["id"], meas_a["id"], scope="REFACE")
    validate_success(api.issue_quote(quote["id"], _SALES))  # project -> QUOTED, quote active.
    # A second SCHEDULED measure remains open.
    meas_b = fx.schedule_measure(proj["id"], scheduled_for="2026-04-10T15:00:00Z")

    cancelled = validate_success(api.cancel_project(proj["id"], _SALES))
    assert cancelled["status"] == "CANCELLED", \
        f"expected project CANCELLED, got {cancelled['status']}"
    meas_b_read = validate_success(api.get_measure(meas_b["id"], _SALES))
    quote_read = validate_success(api.get_quote(quote["id"], _SALES))
    assert meas_b_read["status"] == "CANCELLED", \
        f"expected SCHEDULED measure cancelled, got {meas_b_read['status']}"
    assert quote_read["status"] == "SUPERSEDED", \
        f"expected active quote SUPERSEDED, got {quote_read['status']}"
    assert quote_read["is_active"] is False, "superseded quote must not be active"


def test_project_cancel_lands_in_cancelled_from_quoted(api):
    """PRD §3.1: "transitioning it `LEAD → CANCELLED` (the transition is defined
    out of the pre-sale states and lands the project in `CANCELLED`)."

    Design: Difficulty/transitive_cascade/project_cancel_cascade_depth2_measure_and_quote
    """
    cust, proj, meas = fx.setup_project_with_completed_measure()
    quote = fx.create_draft_quote(proj["id"], meas["id"], scope="REFACE")
    validate_success(api.issue_quote(quote["id"], _SALES))  # project QUOTED.
    cancelled = validate_success(api.cancel_project(proj["id"], _SALES))
    assert cancelled["status"] == "CANCELLED", \
        f"expected project CANCELLED from QUOTED, got {cancelled['status']}"


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================

def test_change_order_reject_leaves_firm_total_unchanged(api):
    """PRD §3.7: "A `Customer` who owns the project may reject a pending change
    order, moving it `PENDING → REJECTED` with no price or lead-time change."

    Design: Difficulty/compensating_invariant/change_order_reject_leaves_quote_price_unchanged
    """
    cust, proj, meas, quote, co = fx.setup_approved_quote_with_pending_change_order(
        delta_linear_feet=4, delta_door_count=2, rush=False,
        scope="REFACE", finish_code="WOOD_VENEER")
    firm_before = validate_success(api.get_quote(quote["id"], _SALES))["firm_total_cents"]
    assert firm_before == 715000, f"setup expected firm 715000, got {firm_before}"
    rejected = validate_success(api.reject_change_order(co["id"], make_customer_headers(cust["id"])))
    assert rejected["status"] == "REJECTED", f"expected REJECTED, got {rejected['status']}"
    firm_after = validate_success(api.get_quote(quote["id"], _SALES))["firm_total_cents"]
    assert firm_after == 715000, \
        f"firm_total_cents must be unchanged by a rejected change order, got {firm_after}"


def test_change_order_reject_leaves_project_posture_sold(api):
    """PRD §3.7: "A `Customer` who owns the project may reject a pending change
    order, moving it `PENDING → REJECTED` with no price or lead-time change."

    Design: Difficulty/compensating_invariant/change_order_reject_leaves_quote_price_unchanged
    """
    cust, proj, meas, quote, co = fx.setup_approved_quote_with_pending_change_order(
        delta_linear_feet=4, delta_door_count=2, rush=False,
        scope="REFACE", finish_code="WOOD_VENEER")
    assert validate_success(api.get_project(proj["id"], _SALES))["status"] == "SOLD"
    validate_success(api.reject_change_order(co["id"], make_customer_headers(cust["id"])))
    proj_after = validate_success(api.get_project(proj["id"], _SALES))
    # Reject drives no cascade -> project stays exactly SOLD.
    assert proj_after["status"] == "SOLD", \
        f"rejected change order must not alter project posture, got {proj_after['status']}"


def test_install_cancel_conserves_project_posture(api):
    """PRD §3.8: "Placement bubbles the project up `SOLD → IN_PRODUCTION`".
    PRD §3.10: "cancellation is permitted only when the job is in `SCHEDULED` and
    reverts the project `IN_PRODUCTION → SOLD` if it was in production."

    Design: Difficulty/compensating_invariant/install_cancel_reverts_project_posture_conserving_lifecycle
    """
    cust, proj, meas, quote, mo, crew, ij = fx.setup_scheduled_install(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z",
        window_start="2026-06-10T08:00:00Z", window_end="2026-06-10T17:00:00Z")
    in_prod = validate_success(api.get_project(proj["id"], _SALES))
    assert in_prod["status"] == "IN_PRODUCTION", \
        f"setup expected IN_PRODUCTION, got {in_prod['status']}"
    cancelled = validate_success(api.cancel_install_job(ij["id"], _SCHED))
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    proj_read = validate_success(api.get_project(proj["id"], _SALES))
    assert proj_read["status"] == "SOLD", \
        f"project posture must return to exactly SOLD, got {proj_read['status']}"


def test_install_cancel_does_not_disturb_material_order(api):
    """PRD §3.10: "A `Scheduler` may cancel a scheduled job, moving it
    `SCHEDULED → CANCELLED`; cancellation is permitted only when the job is in
    `SCHEDULED` and reverts the project `IN_PRODUCTION → SOLD` if it was in
    production."

    Design: Difficulty/compensating_invariant/install_cancel_reverts_project_posture_conserving_lifecycle
    """
    cust, proj, meas, quote, mo, crew, ij = fx.setup_scheduled_install(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z",
        window_start="2026-06-10T08:00:00Z", window_end="2026-06-10T17:00:00Z")
    # The material order was marked READY in setup.
    assert validate_success(api.get_material_order(mo["id"], _SCHED))["status"] == "READY"
    validate_success(api.cancel_install_job(ij["id"], _SCHED))
    mo_after = validate_success(api.get_material_order(mo["id"], _SCHED))
    # Cancelling the install only reverts the project; it does not touch the order.
    assert mo_after["status"] == "READY", \
        f"material order must remain READY after install cancel, got {mo_after['status']}"


# ===========================================================================
# Queue B — consistency_model corner instance
# ===========================================================================

def test_change_order_accept_price_delta_visible_immediately(api):
    """PRD §2.5: "Mutations are committed immediately and consistently — there is no
    deferred or eventual reconciliation."
    PRD §3.7: "On acceptance the system computes the signed `price_delta_cents` and
    the non-negative `lead_time_delta_days` from the change order's deltas".

    Design: Corner/consistency_model/change_order_accept_visible_in_same_response
    """
    cust, proj, meas, quote, co = fx.setup_approved_quote_with_pending_change_order(
        delta_linear_feet=4, delta_door_count=2, rush=False,
        scope="REFACE", finish_code="WOOD_VENEER")
    accepted = validate_success(api.accept_change_order(
        co["id"], {"expected_quote_version": quote["version"]},
        make_customer_headers(cust["id"])))
    # price_delta_cents present in the accept response itself (no deferred read).
    assert accepted["price_delta_cents"] == 110000, \
        f"accept response must carry price_delta_cents 110000, got {accepted['price_delta_cents']}"
    quote_read = validate_success(api.get_quote(quote["id"], _SALES))
    assert quote_read["firm_total_cents"] == 825000, \
        f"expected re-priced firm 825000, got {quote_read['firm_total_cents']}"
