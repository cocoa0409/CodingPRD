"""Validation gates: threshold edges, the precedence ladder and untouched ledgers.

Each test drives one gate of PRD section 3 to the exact value the PRD calls
admissible and then one step past it, and — where the PRD fixes an order between
two gates that a single request violates at once — asserts which of the two
answers. Every test builds its own state from scratch through the endpoints of
PRD section 4, because the server is restarted and the database wiped before
every individual test.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_cents,
    assert_ratio,
    assert_zone_occupancy,
    factories as f,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_BELOW_PREVAILING_WAGE,
    ERR_BMP_INSPECTION_OVERDUE,
    ERR_CHANGE_ORDER_CAP_EXCEEDED,
    ERR_DISTURBED_ACREAGE_EXCEEDED,
    ERR_EARTHWORK_WINDOW_CONFLICT,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW_BOUNDS,
    ERR_PROJECT_NOT_FOUND,
    ERR_TORQUE_TUBE_TOLERANCE_EXCEEDED,
)
from test_helpers.fixtures import (
    accepted_area,
    accepted_module_delivery,
    create_grading_area,
    create_payroll_week,
    create_project,
    create_yard_zone,
    piles_complete_block,
    reset_clock,
)


def test_bmp_inspection_currency_gate_fires_at_the_interval_edge(api, civil_headers):
    """A start exactly at the interval edge is current; twelve hours later is overdue.

    PRD 3.2: "Third is inspection currency: the proposed `work_start_at` may be no later than `bmp_last_inspected_at` advanced by `bmp_inspection_interval_days` whole days, and a later start is refused with `ERR_BMP_INSPECTION_OVERDUE`."

    Design: Corner/validations/bmp_inspection_currency_gate_fires_at_the_interval_edge
    """
    reset_clock(api)
    project = create_project(api, name="Inspection Mesa")
    area = create_grading_area(
        api, project["id"], bmp_inspection_interval_days=14, disturbed_acreage_limit=40.00
    )
    assert area["bmp_last_inspected_at"].startswith("2026-08-01T00:00:00"), (
        "the area is stamped with the logical clock at the moment it opens"
    )

    # 2026-08-01T00:00:00Z advanced by 14 whole days is exactly 2026-08-15T00:00:00Z.
    at_the_edge = validate_success(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "CLEARING", "2026-08-15T00:00:00Z", "2026-08-15T08:00:00Z", 10.00
            ),
            civil_headers,
        )
    )
    assert at_the_edge["status"] == "CLEARED"
    assert_ratio(
        at_the_edge["disturbed_acreage_current"], 10.00, "disturbed_acreage_current"
    )

    validate_error(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "GRADING", "2026-08-15T12:00:00Z", "2026-08-15T20:00:00Z", 10.00
            ),
            civil_headers,
        ),
        ERR_BMP_INSPECTION_OVERDUE,
    )
    unchanged = validate_success(api.get_grading_area(area["id"], civil_headers))
    assert_ratio(
        unchanged["disturbed_acreage_current"], 10.00, "disturbed_acreage_current"
    )
    assert len(unchanged["earthwork_windows"]) == 1
    assert unchanged["status"] == "CLEARED"

    inspected = validate_success(
        api.create_site_event(
            area["id"],
            f.bmp_inspection_payload("2026-08-20T00:00:00Z", False),
            civil_headers,
        )
    )
    assert inspected["bmp_last_inspected_at"].startswith("2026-08-20T00:00:00")
    assert inspected["bmp_deficiency_open"] is False

    reopened = validate_success(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "GRADING", "2026-08-15T12:00:00Z", "2026-08-15T20:00:00Z", 10.00
            ),
            civil_headers,
        )
    )
    assert reopened["status"] == "GRADED", "a clean inspection restarts the interval"
    assert_ratio(
        reopened["disturbed_acreage_current"], 20.00, "disturbed_acreage_current"
    )
    assert len(reopened["earthwork_windows"]) == 2


def test_torque_tube_deviation_at_the_declared_tolerance_is_accepted(
    api, foreman_headers
):
    """25.0 mm of deviation is inside the tolerance; 25.1 mm is refused and writes nothing.

    PRD 3.4: "The surveyed deviation may not exceed a torque-tube tolerance of 25.0 millimetres, and a wider deviation is refused with `ERR_TORQUE_TUBE_TOLERANCE_EXCEEDED`."

    Design: Corner/validations/torque_tube_deviation_at_the_declared_tolerance_is_accepted
    """
    project = create_project(api, name="Torque Tube Flat")
    area = accepted_area(api, project["id"])
    zone = create_yard_zone(api, project["id"])
    accepted_module_delivery(api, project["id"], zone["id"])
    block = piles_complete_block(api, project["id"], area["id"])

    validate_error(
        api.declare_mechanical_completion(
            block["id"], f.mechanical_completion_payload(50, 25.1), foreman_headers
        ),
        ERR_TORQUE_TUBE_TOLERANCE_EXCEEDED,
    )
    refused = validate_success(api.get_block(block["id"], foreman_headers))
    assert refused["mechanical_status"] == "PILES_COMPLETE"
    assert refused["modules_installed_qty"] is None
    assert refused["max_torque_tube_deviation_mm"] is None

    accepted = validate_success(
        api.declare_mechanical_completion(
            block["id"], f.mechanical_completion_payload(50, 25.0), foreman_headers
        )
    )
    assert accepted["mechanical_status"] == "MECH_COMPLETE"
    assert accepted["modules_installed_qty"] == 50
    assert_ratio(
        accepted["max_torque_tube_deviation_mm"], 25.0, "max_torque_tube_deviation_mm"
    )


def test_role_check_outranks_shape_check_which_outranks_existence(
    api, civil_headers, epc_headers
):
    """One request failing role, shape and existence at once answers with the role.

    PRD 2.7: "The server therefore evaluates checks in a fixed global precedence order and returns the **first** failure it encounters, never a later one that happens to be easier to detect."

    Design: Corner/validations/role_check_outranks_shape_check_which_outranks_existence_and_is_rejected
    """
    project = create_project(api, name="Ladder Ridge")
    shapeless = {"amount_cents": 100000}

    validate_error(
        api.create_change_order(NON_EXISTENT_UUID, shapeless, civil_headers),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.create_change_order(NON_EXISTENT_UUID, shapeless, epc_headers),
        ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_change_order(
            NON_EXISTENT_UUID, f.change_order_payload(100000), epc_headers
        ),
        ERR_PROJECT_NOT_FOUND,
    )

    accepted = validate_success(
        api.create_change_order(
            project["id"], f.change_order_payload(100000), epc_headers
        )
    )
    assert_cents(
        accepted["approved_change_order_cents"], 100000, "approved_change_order_cents"
    )
    assert accepted["version"] == 2, "only the admissible request advanced the project"


def test_zero_length_and_inverted_windows_are_rejected_before_conflict_checks(
    api, civil_headers, procurement_headers
):
    """Bound ordering answers ahead of occupancy, and the rejected write reserves nothing.

    PRD 2.7: "A non-strictly-ordered pair is `ERR_INVALID_WINDOW_BOUNDS` (HTTP 400)."

    Design: Corner/validations/zero_length_and_inverted_windows_are_rejected_before_conflict_checks
    """
    reset_clock(api)
    project = create_project(api, name="Bounds Basin")
    area = create_grading_area(api, project["id"], disturbed_acreage_limit=40.00)
    occupied = validate_success(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "CLEARING", "2026-08-01T12:00:00Z", "2026-08-01T20:00:00Z", 5.00
            ),
            civil_headers,
        )
    )
    assert len(occupied["earthwork_windows"]) == 1

    validate_error(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "GRADING", "2026-08-01T20:00:00Z", "2026-08-01T12:00:00Z", 5.00
            ),
            civil_headers,
        ),
        ERR_INVALID_WINDOW_BOUNDS,
    )
    validate_error(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "GRADING", "2026-08-01T16:00:00Z", "2026-08-01T16:00:00Z", 5.00
            ),
            civil_headers,
        ),
        ERR_INVALID_WINDOW_BOUNDS,
    )
    # Written forward, the very same span reaches the occupancy check behind it.
    validate_error(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "GRADING", "2026-08-01T12:00:00Z", "2026-08-01T20:00:00Z", 5.00
            ),
            civil_headers,
        ),
        ERR_EARTHWORK_WINDOW_CONFLICT,
    )
    intact = validate_success(api.get_grading_area(area["id"], civil_headers))
    assert len(intact["earthwork_windows"]) == 1
    assert_ratio(intact["disturbed_acreage_current"], 5.00, "disturbed_acreage_current")

    zone = create_yard_zone(api, project["id"], pallet_capacity=100)
    validate_error(
        api.create_delivery(
            f.delivery_payload(
                project["id"],
                zone["id"],
                zone["version"],
                laydown_window_start="2026-08-03T00:00:00Z",
                laydown_window_end="2026-08-03T00:00:00Z",
            ),
            procurement_headers,
        ),
        ERR_INVALID_WINDOW_BOUNDS,
    )
    untouched_zone = validate_success(api.get_yard_zone(zone["id"], procurement_headers))
    assert_zone_occupancy(untouched_zone, reserved_pallets=0, available_pallets=100)
    assert untouched_zone["version"] == zone["version"], (
        "a rejected reservation neither holds pallets nor advances the zone"
    )


def test_change_orders_are_individually_valid_but_capped_in_aggregate(api, epc_headers):
    """The cap is measured against the base contract, so it admits the sum exactly and no cent more.

    PRD 3.1: "Acceptance is capped: the cumulative total of accepted change orders — the project's existing `approved_change_order_cents` plus the new `amount_cents` — may not exceed twenty percent of the **base** contract value, computed as `contract_value_cents` multiplied by 0.20 and rounded half up to whole cents."

    Design: Corner/validations/change_orders_are_individually_valid_but_capped_in_aggregate
    """
    project = create_project(
        api, name="Aggregate Cap Ranch", contract_value_cents=10000000
    )
    # 10000000 * 0.20 is a cap of 2000000 cents on the cumulative total.
    first = validate_success(
        api.create_change_order(
            project["id"], f.change_order_payload(1500000), epc_headers
        )
    )
    assert_cents(
        first["approved_change_order_cents"], 1500000, "approved_change_order_cents"
    )
    second = validate_success(
        api.create_change_order(
            project["id"], f.change_order_payload(500000), epc_headers
        )
    )
    assert_cents(
        second["approved_change_order_cents"], 2000000, "approved_change_order_cents"
    )

    validate_error(
        api.create_change_order(project["id"], f.change_order_payload(1), epc_headers),
        ERR_CHANGE_ORDER_CAP_EXCEEDED,
    )
    after = validate_success(api.get_project(project["id"], epc_headers))
    assert_cents(
        after["approved_change_order_cents"], 2000000, "approved_change_order_cents"
    )
    assert after["version"] == second["version"], (
        "the breaching request leaves the project untouched"
    )

    summary = validate_success(api.get_settlement_summary(project["id"], epc_headers))
    assert_cents(
        summary["adjusted_contract_cents"], 12000000, "adjusted_contract_cents"
    )


def test_underpayment_gate_applies_only_under_a_strict_wage_election(api, labor_headers):
    """A STRICT election refuses the under-prevailing line; REMEDIABLE accrues it instead.

    PRD 3.8: "When `prevailing_wage_election` is `STRICT`, an under-prevailing line never enters the ledger at all: the post is refused with `ERR_BELOW_PREVAILING_WAGE` before persistence, on the grounds that the sum of `paid_rate_cents` and `fringe_rate_cents` must be at least `prevailing_rate_cents`."

    Design: Corner/validations/underpayment_gate_applies_only_under_a_strict_wage_election
    """
    strict = create_project(
        api, name="Strict Election Mesa", prevailing_wage_election="STRICT"
    )
    strict_week = create_payroll_week(api, strict["id"], week_start_date="2026-08-03")
    validate_error(
        api.create_labor_entry(
            strict_week["id"],
            f.labor_entry_payload(
                worker_ref="W-LOW",
                hours=50.00,
                paid_rate_cents=4000,
                fringe_rate_cents=500,
                prevailing_rate_cents=5000,
            ),
            labor_headers,
        ),
        ERR_BELOW_PREVAILING_WAGE,
    )
    empty = validate_success(api.get_payroll_week(strict_week["id"], labor_headers))
    assert_ratio(empty["total_hours"], 0.00, "total_hours")
    assert empty["entry_count"] == 0

    at_par = validate_success(
        api.create_labor_entry(
            strict_week["id"],
            f.labor_entry_payload(
                worker_ref="W-PAR",
                hours=50.00,
                paid_rate_cents=4500,
                fringe_rate_cents=500,
                prevailing_rate_cents=5000,
            ),
            labor_headers,
        ),
        expected_status=201,
    )
    assert at_par["status"] == "POSTED", "a line paying exactly the determination posts"
    assert_cents(at_par["shortfall_cents_per_hour"], 0, "shortfall_cents_per_hour")
    assert_cents(at_par["restitution_cents"], 0, "restitution_cents")

    remediable = create_project(
        api, name="Remediable Election Mesa", prevailing_wage_election="REMEDIABLE"
    )
    remediable_week = create_payroll_week(
        api, remediable["id"], week_start_date="2026-08-03"
    )
    accrued = validate_success(
        api.create_labor_entry(
            remediable_week["id"],
            f.labor_entry_payload(
                worker_ref="W-LOW",
                hours=50.00,
                paid_rate_cents=4000,
                fringe_rate_cents=500,
                prevailing_rate_cents=5000,
            ),
            labor_headers,
        ),
        expected_status=201,
    )
    assert accrued["status"] == "POSTED"
    assert_cents(accrued["shortfall_cents_per_hour"], 500, "shortfall_cents_per_hour")
    assert_cents(accrued["restitution_cents"], 25000, "restitution_cents")
    ledger = validate_success(api.get_payroll_week(remediable_week["id"], labor_headers))
    assert_ratio(ledger["total_hours"], 50.00, "total_hours")
    assert ledger["entry_count"] == 1


def test_acreage_gate_runs_after_the_window_conflict_check(api, civil_headers):
    """A log that both collides and overdraws answers with the conflict and moves no acreage.

    PRD 3.2: "Fourth, the candidate interval is checked against crew occupancy under the closed, unbuffered convention of §2.11: if the candidate's `work_start_at` is at or before the `work_end_at` of any record already in `earthwork_windows`, and the candidate's `work_end_at` is at or after that record's `work_start_at`, the log is refused with `ERR_EARTHWORK_WINDOW_CONFLICT`."

    Design: Corner/validations/acreage_gate_runs_after_the_window_conflict_check_and_leaves_the_ledger_untouched
    """
    reset_clock(api)
    project = create_project(api, name="Order Of Gates Draw")
    area = create_grading_area(api, project["id"], disturbed_acreage_limit=20.00)
    opened = validate_success(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "CLEARING", "2026-08-01T12:00:00Z", "2026-08-01T20:00:00Z", 19.00
            ),
            civil_headers,
        )
    )
    assert_ratio(opened["disturbed_acreage_current"], 19.00, "disturbed_acreage_current")

    validate_error(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "GRADING", "2026-08-01T16:00:00Z", "2026-08-01T18:00:00Z", 5.00
            ),
            civil_headers,
        ),
        ERR_EARTHWORK_WINDOW_CONFLICT,
    )
    validate_error(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "GRADING", "2026-08-02T12:00:00Z", "2026-08-02T20:00:00Z", 5.00
            ),
            civil_headers,
        ),
        ERR_DISTURBED_ACREAGE_EXCEEDED,
    )
    held = validate_success(api.get_grading_area(area["id"], civil_headers))
    assert_ratio(held["disturbed_acreage_current"], 19.00, "disturbed_acreage_current")
    assert len(held["earthwork_windows"]) == 1
    assert held["status"] == "CLEARED", "neither rejection advanced the area"

    admitted = validate_success(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "GRADING", "2026-08-02T12:00:00Z", "2026-08-02T20:00:00Z", 1.00
            ),
            civil_headers,
        )
    )
    assert_ratio(
        admitted["disturbed_acreage_current"], 20.00, "disturbed_acreage_current"
    )
    assert admitted["status"] == "GRADED"
    assert len(admitted["earthwork_windows"]) == 2
