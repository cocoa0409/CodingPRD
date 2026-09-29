"""Conserved quantities: the three-way money partition and the seat ledger."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ASSET_HEADERS, PLANNER_HEADERS
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_budget_partition
from test_helpers.factories import reason_payload
from test_helpers.fixtures import approve_all_permits, build_request_context


def _permitted_request_with_a_watched_budget(api):
    """A permit-pending request, its appropriation read before the encumbrance."""
    ctx = build_request_context(
        api,
        stage="permit_pending",
        school_overrides={"name": "Kestrel Middle", "site_acreage": 8.0,
                          "electrical_spare_capacity_kw": 40,
                          "sewer_spare_connections": 1},
        unit_overrides={"asset_tag": "PU-R101"},
    )
    ctx["budget_at_authorisation"] = validate_success(
        api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)
    )
    approve_all_permits(api, ctx["request_id"])
    ctx["budget_while_encumbered"] = validate_success(
        api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)
    )
    return ctx


def test_withdrawal_releases_exactly_the_encumbrance_the_request_stored(api):
    """PRD §3.5: withdrawal "unwinds everything the request had claimed:
    `encumbered_cost_cents` is released back out of the appropriation's
    `encumbered_cents` and then zeroed, `uncommitted_cents` is recomputed, the unit
    returns to `IN_STORAGE`, the pad's `occupied_by_unit_id` is cleared". PRD §2.9 fixes
    the conserved quantity: "After every mutation of either of the first two buckets, the
    invariant must hold that `authorized_cents` is equal to the sum of
    `uncommitted_cents`, `encumbered_cents` and `expended_cents`."

    Design: Difficulty/compensating_invariant/capital_budget_partition_restored_on_withdrawal
    """
    ctx = _permitted_request_with_a_watched_budget(api)

    assert_budget_partition(
        ctx["budget_at_authorisation"],
        authorized_cents=500_000_000, encumbered_cents=0, expended_cents=0,
        uncommitted_cents=500_000_000,
    )
    assert_budget_partition(
        ctx["budget_while_encumbered"],
        authorized_cents=500_000_000, encumbered_cents=7_741_440, expended_cents=0,
        uncommitted_cents=492_258_560,
    )

    withdrawn = validate_success(
        api.withdraw_request(ctx["request_id"], reason_payload(), PLANNER_HEADERS)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["encumbered_cost_cents"] == 0
    assert withdrawn["estimated_relocation_cost_cents"] == 7_741_440

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=0, expended_cents=0,
        uncommitted_cents=500_000_000,
    )

    assert validate_success(
        api.get_portable_unit(ctx["unit_id"], PLANNER_HEADERS)
    )["allocation_status"] == "IN_STORAGE"
    assert validate_success(
        api.get_placement_site(ctx["site_id"], PLANNER_HEADERS)
    )["occupied_by_unit_id"] is None


def test_a_second_withdrawal_cannot_release_the_same_money_twice(api):
    """PRD §3.5: "`WITHDRAWN`, like `REJECTED` and `DECOMMISSIONED`, is terminal." PRD
    §2.6 rule 10: "The target row is in a state from which the requested transition is
    declared — ... `ERR_REQUEST_STATE_INVALID` ... 409, on every action endpoint." PRD
    §2.9: "The expended bucket is a monotone accumulator that never decreases".

    Design: Difficulty/compensating_invariant/capital_budget_partition_restored_on_withdrawal
    """
    ctx = _permitted_request_with_a_watched_budget(api)

    validate_success(
        api.withdraw_request(ctx["request_id"], reason_payload(), PLANNER_HEADERS)
    )
    second = api.withdraw_request(ctx["request_id"], reason_payload(), PLANNER_HEADERS)
    validate_error(second, ApiErrorId.REQUEST_STATE_INVALID, expected_status=409)

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=0, expended_cents=0,
        uncommitted_cents=500_000_000,
    )
    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "WITHDRAWN"


def _installed_portable(api):
    """One 24-seat portable standing on a 56-seat campus."""
    return build_request_context(
        api,
        stage="installed",
        school_overrides={"name": "Meadowlark Middle", "site_acreage": 8.0,
                          "electrical_spare_capacity_kw": 40,
                          "sewer_spare_connections": 1},
        unit_overrides={"asset_tag": "PU-S101"},
    )


def test_installation_adds_the_units_own_rated_seats_to_the_campus_ledger(api):
    """PRD §3.8: "The unit moves `SCHEDULED → INSTALLED`, has its `current_school_id` set
    to the request's `school_id`, has its `lifetime_relocation_count` incremented by 1,
    and has the request's `encumbered_cost_cents` added to its
    `accumulated_relocation_cost_cents` ... The campus has the unit's `rated_seats` added
    to its `hosted_portable_seats` and its `reliance_flag` recomputed." PRD §3.9:
    "`portable_seat_share_pct` is the hosted portable seats multiplied by 100, divided by
    the sum of the permanent seats and the hosted portable seats, rounded half up to one
    decimal place. The campus's `reliance_flag` is `LONG_TERM_RELIANCE` when that share
    reaches 15.0 percent or more".

    Design: Difficulty/compensating_invariant/hosted_seat_ledger_restored_on_decommission
    """
    ctx = _installed_portable(api)

    school = validate_success(api.get_school(ctx["school_id"], PLANNER_HEADERS))
    assert school["hosted_portable_seats"] == 24
    assert school["reliance_flag"] == "LONG_TERM_RELIANCE"

    report = validate_success(api.get_reliance_report(ctx["school_id"], PLANNER_HEADERS))
    assert report["permanent_seats"] == 56
    assert report["hosted_portable_seats"] == 24
    assert report["portable_seat_share_pct"] == 30.0
    assert report["narrative_required"] is True

    unit = validate_success(api.get_portable_unit(ctx["unit_id"], ASSET_HEADERS))
    assert unit["allocation_status"] == "INSTALLED"
    assert unit["current_school_id"] == ctx["school_id"]
    assert unit["rated_seats"] == 24
    assert unit["lifetime_relocation_count"] == 1
    assert unit["accumulated_relocation_cost_cents"] == 7_741_440

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=0, expended_cents=7_741_440,
        uncommitted_cents=492_258_560,
    )


def test_decommissioning_removes_those_same_seats_and_charges_the_removal(api):
    """PRD §3.9: "the unit moves `PENDING_REMOVAL → IN_STORAGE`, which subtracts the
    unit's `rated_seats` from the campus's `hosted_portable_seats`, clears the unit's
    `current_school_id`, clears the pad's `occupied_by_unit_id` and recomputes the
    campus's `reliance_flag`", while "that removal charge is added to the appropriation's
    `expended_cents` and `uncommitted_cents` is recomputed" — "1,600,000 cents for a
    `SINGLE_24x40`". PRD §3.9: "A narrative to the board is required exactly when the
    flag is `LONG_TERM_RELIANCE`".

    Design: Difficulty/compensating_invariant/hosted_seat_ledger_restored_on_decommission
    """
    ctx = _installed_portable(api)

    opened = validate_success(
        api.request_decommission(ctx["request_id"],
                                 reason_payload("Permanent addition opened."),
                                 ASSET_HEADERS)
    )
    assert opened["status"] == "DECOMMISSION_REQUESTED"
    assert validate_success(
        api.get_portable_unit(ctx["unit_id"], ASSET_HEADERS)
    )["allocation_status"] == "PENDING_REMOVAL"

    completed = validate_success(
        api.complete_decommission(ctx["request_id"], {}, ASSET_HEADERS)
    )
    assert completed["status"] == "DECOMMISSIONED"

    school = validate_success(api.get_school(ctx["school_id"], PLANNER_HEADERS))
    assert school["hosted_portable_seats"] == 0
    assert school["reliance_flag"] == "NONE"

    unit = validate_success(api.get_portable_unit(ctx["unit_id"], ASSET_HEADERS))
    assert unit["allocation_status"] == "IN_STORAGE"
    assert unit["current_school_id"] is None
    assert unit["rated_seats"] == 24
    assert unit["lifetime_relocation_count"] == 1
    assert unit["accumulated_relocation_cost_cents"] == 7_741_440

    assert validate_success(
        api.get_placement_site(ctx["site_id"], PLANNER_HEADERS)
    )["occupied_by_unit_id"] is None

    report = validate_success(api.get_reliance_report(ctx["school_id"], PLANNER_HEADERS))
    assert report["hosted_portable_seats"] == 0
    assert report["portable_seat_share_pct"] == 0.0
    assert report["narrative_required"] is False

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=0, expended_cents=9_341_440,
        uncommitted_cents=490_658_560,
    )
