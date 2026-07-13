"""Assignment parallel axes, direct assignment, OCC, season/state precedence,
ledger debit, immediate visibility, and money-axis RBAC."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_gardener_headers,
    ApiErrorId,
    set_clock, new_garden, new_plot, new_gardener, direct_assign, new_application,
    setup_assigned_plot,
    assign_plot_payload, pay_full,
)

MANAGER = TEST_USERS["manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


# ----------------------------------------------------------------------
# Difficulty: Assignment parallel occupancy x fee axes
# ----------------------------------------------------------------------

def test_pay_advances_fee_axis_while_occupancy_stays_active(api):
    """PRD §3.6: "The two move independently: an assignment can be settled on the
    occupancy axis while still `UNPAID`, or paid while still `ACTIVE`."
    PRD §3.6: "A payment moves `fee_status` from `UNPAID` to `PAID` and subtracts
    `amount_cents` from the gardener's `balance_owed_cents`."

    Design: Difficulty/non_linear_state_machine/assignment_parallel_occupancy_and_fee_axes
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    asg_id = ctx["assignment"]["id"]
    paid = pay_full(api, asg_id, 6000)
    assert paid["fee_status"] == "PAID"
    assert paid["occupancy_status"] == "ACTIVE"


def test_renewal_request_advances_occupancy_while_fee_paid(api):
    """PRD §3.7: "A leaseholder initiates renewal on their own assignment, which
    advances `occupancy_status` from `ACTIVE` to `RENEWAL_PENDING`."
    PRD §3.6: "The two move independently: an assignment can be settled on the
    occupancy axis while still `UNPAID`, or paid while still `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/assignment_parallel_occupancy_and_fee_axes
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    asg_id = ctx["assignment"]["id"]
    pay_full(api, asg_id, 6000)  # clears balance so the renewal gate passes
    renewed = validate_success(api.request_renewal(asg_id, ctx["gardener_headers"]), 200)
    assert renewed["occupancy_status"] == "RENEWAL_PENDING"
    assert renewed["fee_status"] == "PAID"


# ----------------------------------------------------------------------
# Difficulty: state check (ERR_PLOT_NOT_AVAILABLE) pre-empts temporal season check
# ----------------------------------------------------------------------

def _assigned_plot_then_second_assign(api):
    set_clock(api, "2026-03-10T00:00:00Z")
    garden = new_garden(api, name="Willow Garden")
    plot = new_plot(api, garden["id"], size="MEDIUM", label="M-7")
    ga = new_gardener(api, full_name="Ada Moss")
    gb = new_gardener(api, full_name="Bud Lark")
    assignment = direct_assign(api, plot["id"], ga["id"], plot["version"])
    current = validate_success(api.get_plot(plot["id"], MANAGER), 200)
    resp = api.assign_plot(plot["id"], assign_plot_payload(gb["id"], current["version"]), MANAGER)
    return {"plot": plot, "assignment": assignment, "resp": resp}


def test_second_assign_on_assigned_plot_returns_plot_not_available(api):
    """PRD §3.4: "The plot must be `AVAILABLE` (`ERR_PLOT_NOT_AVAILABLE` otherwise), and
    `expected_plot_version` must match the plot's current `version` or the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412). The assignment must also not
    double-book the season: if any non-terminal assignment already exists on this plot
    whose leased interval from `season_start` (inclusive) to `season_end` (exclusive)
    overlaps the garden's current season, the request fails with
    `ERR_PLOT_SEASON_CONFLICT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/plot_not_available_beats_season_conflict_returns_state_error
    """
    result = _assigned_plot_then_second_assign(api)
    validate_error(result["resp"], ApiErrorId.ERR_PLOT_NOT_AVAILABLE.value, 409)


def test_rejected_second_assign_does_not_supersede_holder(api):
    """PRD §3.4: "A successful direct assignment creates an `Assignment` ... advances
    the plot from `AVAILABLE` to `ASSIGNED`, sets the plot's `current_assignment_id`,
    and increments the plot's `version`."
    PRD §2.8: "Only once a request has passed authentication, authorization, existence,
    and shape validation are the domain-specific state, concurrency, safety,
    referential, constraint, fiscal, and temporal rules described throughout §3
    applied, roughly in that order of precedence".

    Design: Difficulty/priority_pair_validation_conflict/plot_not_available_beats_season_conflict_returns_state_error
    """
    result = _assigned_plot_then_second_assign(api)
    validate_error(result["resp"], ApiErrorId.ERR_PLOT_NOT_AVAILABLE.value, 409)
    plot = validate_success(api.get_plot(result["plot"]["id"], MANAGER), 200)
    assert plot["status"] == "ASSIGNED"
    assert plot["current_assignment_id"] == result["assignment"]["id"]


# ----------------------------------------------------------------------
# Corner: assignment terminal-state lockdown
# ----------------------------------------------------------------------

def test_settle_already_ended_assignment_rejected(api):
    """PRD §3.6: "Settling — permitted only when `occupancy_status` is `ACTIVE` or
    `RENEWAL_PENDING`, otherwise `ERR_ASSIGNMENT_NOT_ACTIVE` (HTTP 409) — moves
    occupancy to `ENDED`, computes `final_fee_cents`, and returns the plot from
    `ASSIGNED` to `AVAILABLE` (incrementing the plot's `version`) with no automatic
    re-offer."

    Design: Corner/state_machines/settle_twice_returns_assignment_not_active
    """
    ctx = setup_assigned_plot(api, size="SMALL")
    asg_id = ctx["assignment"]["id"]
    validate_success(api.settle_assignment(asg_id, MANAGER), 200)
    resp = api.settle_assignment(asg_id, MANAGER)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value, 409)


# ----------------------------------------------------------------------
# Corner: OCC stale plot version on direct assign
# ----------------------------------------------------------------------

def test_assign_with_stale_plot_version_rejected(api):
    """PRD §2.5: "If `expected_plot_version` does not equal the plot's current
    `version`, the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_plot_version_on_assign_returns_conflict
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    garden = new_garden(api, name="OCC Garden")
    plot = new_plot(api, garden["id"], size="MEDIUM", label="O-1")
    observed_version = plot["version"]
    ga = new_gardener(api, full_name="Occ Wan")
    gb = new_gardener(api, full_name="Occ Two")
    app = new_application(api, ga["id"], garden["id"], requested_size="MEDIUM")
    validate_success(api.offer_plot(plot["id"], MANAGER), 200)  # plot version advances
    validate_success(api.decline_application(app["id"], make_gardener_headers(ga["id"])), 200)  # advances again, AVAILABLE
    resp = api.assign_plot(plot["id"], assign_plot_payload(gb["id"], observed_version), MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


# ----------------------------------------------------------------------
# Corner: provisional fee debited to the gardener's ledger
# ----------------------------------------------------------------------

def test_direct_assign_debits_provisional_fee_to_ledger(api):
    """PRD §3.4: "computes its `provisional_fee_cents`, adds that to the gardener's
    `balance_owed_cents`, advances the plot from `AVAILABLE` to `ASSIGNED`, sets the
    plot's `current_assignment_id`, and increments the plot's `version`."

    Design: Corner/cross_cutting/derived_balance_owed_after_assignment
    """
    garden = new_garden(api, name="Ledger Garden")
    plot = new_plot(api, garden["id"], size="MEDIUM", label="LG-1")
    gardener = new_gardener(api, full_name="Led Ger")
    assignment = direct_assign(api, plot["id"], gardener["id"], plot["version"])
    refreshed = validate_success(api.get_gardener(gardener["id"], MANAGER), 200)
    assert refreshed["balance_owed_cents"] == 6000
    assert assignment["provisional_fee_cents"] == 6000


# ----------------------------------------------------------------------
# Corner: immediate consistency of the assign result
# ----------------------------------------------------------------------

def test_assign_visible_immediately_on_plot_read(api):
    """PRD §3.4: "A successful direct assignment creates an `Assignment` ... advances
    the plot from `AVAILABLE` to `ASSIGNED`, sets the plot's `current_assignment_id`,
    and increments the plot's `version`."

    Design: Corner/consistency_model/assign_result_visible_immediately
    """
    garden = new_garden(api, name="Now Garden")
    plot = new_plot(api, garden["id"], size="MEDIUM", label="N-1")
    gardener = new_gardener(api, full_name="Now Er")
    assignment = direct_assign(api, plot["id"], gardener["id"], plot["version"])
    read = validate_success(api.get_plot(plot["id"], MANAGER), 200)
    assert read["status"] == "ASSIGNED"
    assert read["current_assignment_id"] == assignment["id"]


# ----------------------------------------------------------------------
# Corner: reverse reachability of assignments by gardener
# ----------------------------------------------------------------------

def test_list_assignments_filtered_by_gardener_contains_assignment(api):
    """PRD §4: the `GET /assignments` endpoint lists/filters assignments.
    PRD §2.2: "The `data` field contains the resource object or an array of resource
    objects."

    Design: Corner/endpoints/reverse_reach_assignments_by_gardener
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    data, _ = validate_paginated(api.list_assignments(MANAGER, params={"gardener_id": ctx["gardener"]["id"]}))
    assert any(a["id"] == ctx["assignment"]["id"] for a in data), \
        "gardener's assignment list must contain the created assignment"


# ----------------------------------------------------------------------
# Corner: segregation of duties on the money axis
# ----------------------------------------------------------------------

def test_manager_cannot_waive_fee(api):
    """PRD §3.6: "The money axis is the exclusive province of the `Treasurer`."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or a gardener attempts to act on a resource they
    do not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/manager_cannot_waive_fee_returns_unauthorized
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    resp = api.waive_fee(ctx["assignment"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
