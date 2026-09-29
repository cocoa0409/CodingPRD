"""Recovery reporting under both readings, and the compliance checkpoint."""

import pytest

from test_helpers import (
    create_listing,
    intake_lockbox,
    list_charges,
    place_lockbox,
    read_association,
    read_placement,
    register_association,
    remove_placement,
    run_checkpoint,
    setup_placed_box,
    validate_success,
)
from test_helpers.fixtures import (
    AUDITOR,
    assign_lockbox,
    close_listing,
    listing_action,
    set_clock,
    setup_association_with_agent,
    withdraw_listing,
)

SUMMARY_WINDOW = {
    "window_start": "2026-06-01T00:00:00Z",
    "window_end": "2026-08-31T00:00:00Z",
}


def _three_placements_with_divergent_outcomes():
    """Listing A closed and its box retrieved on time, listing B closed and its box still
    delinquent, listing C withdrawn and its box retrieved late."""
    ctx = setup_association_with_agent()
    boxes, listings, placements = [], [], []
    for index, (serial, mls, address) in enumerate(
        [
            ("LB-0001", "MLS-1001", "12 Pine St"),
            ("LB-0002", "MLS-1002", "34 Cedar Ave"),
            ("LB-0003", "MLS-1003", "56 Alder Way"),
        ]
    ):
        box = intake_lockbox(
            ctx["association_id"],
            serial_number=serial,
            model="LB_STD",
            replacement_cost_cents=9000,
        )
        assign_lockbox(box["id"], ctx["agent_id"])
        listing = create_listing(
            ctx["association_id"], ctx["agent_id"], mls_number=mls, address_line=address
        )
        boxes.append(box)
        listings.append(listing)
        placements.append(place_lockbox(box["id"], listing["id"], ctx["agent_id"]))

    set_clock("2026-08-08T00:00:00Z")
    withdraw_listing(listings[2]["id"], ctx["agent_id"])

    set_clock("2026-08-10T00:00:00Z")
    for listing in listings[:2]:
        listing_action(listing["id"], "MARK_UNDER_CONTRACT", agent_id=ctx["agent_id"])
        listing_action(
            listing["id"], "CLOSE", agent_id=ctx["agent_id"], close_date="2026-08-10"
        )

    set_clock("2026-08-12T00:00:00Z")
    remove_placement(placements[0]["id"], ctx["agent_id"])
    remove_placement(placements[2]["id"], ctx["agent_id"])

    set_clock("2026-08-20T00:00:00Z")
    run_checkpoint(ctx["association_id"])

    ctx["placements"] = placements
    ctx["listings"] = listings
    return ctx


def test_closing_cohort_counts_only_boxes_from_closed_deals(api, admin_headers):
    """PRD §3.9: "Its denominator is the set of placements whose listing is in `CLOSED` and
    whose listing's `close_date` falls inside the window inclusive of both bounds. Its
    numerator is those denominator members whose `placement_status` is `REMOVED` and whose
    `on_time` flag is true. A withdrawn listing's placement never counts at all, and a late
    removal counts as a miss."
    PRD §3.4: "The `on_time` flag is then true exactly when `removed_at` is set and either no
    `removal_deadline` was ever set or `removed_at` is at or before it."

    Design: Difficulty/dual_variant_calc/recovery_rate_closing_cohort_vs_removal_activity
    """
    ctx = _three_placements_with_divergent_outcomes()

    response = api.get_recovery_summary(
        ctx["association_id"],
        admin_headers,
        params={"variant": "closing_cohort", **SUMMARY_WINDOW},
    )
    data = validate_success(response, 200)
    assert data["denominator_count"] == 2
    assert data["numerator_count"] == 1
    assert float(data["recovery_rate_pct"]) == pytest.approx(50.00, abs=0.01)

    first = read_placement(ctx["placements"][0]["id"])
    assert first["placement_status"] == "REMOVED"
    assert first["on_time"] is True


def test_removal_activity_counts_a_late_removal_as_a_success(api, admin_headers):
    """PRD §3.9: "Its denominator is the set of placements that either are in `REMOVED` with a
    `removed_at` inside the window, or are in `DELINQUENT` with a `removal_deadline` inside the
    window — both bounds inclusive in each case — regardless of the listing's status, so
    withdrawn listings do participate. Its numerator is those denominator members whose
    `placement_status` is `REMOVED`, which means a late removal counts here as a success."
    PRD §3.9: "Under either reading, the rate is the numerator count multiplied by 100 and
    divided by the denominator count, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/recovery_rate_closing_cohort_vs_removal_activity
    """
    ctx = _three_placements_with_divergent_outcomes()

    response = api.get_recovery_summary(
        ctx["association_id"],
        admin_headers,
        params={"variant": "removal_activity", **SUMMARY_WINDOW},
    )
    data = validate_success(response, 200)
    assert data["denominator_count"] == 3
    assert data["numerator_count"] == 2
    assert float(data["recovery_rate_pct"]) == pytest.approx(66.67, abs=0.01)

    delinquent = read_placement(ctx["placements"][1]["id"])
    assert delinquent["placement_status"] == "DELINQUENT"
    assert delinquent["billing_status"] == "ACCRUED"

    withdrawn_placement = read_placement(ctx["placements"][2]["id"])
    assert withdrawn_placement["placement_status"] == "REMOVED"
    assert withdrawn_placement["on_time"] is False


def test_recovery_summary_with_an_empty_cohort_returns_zero(api, auditor_headers):
    """PRD §3.9: "Under either reading, the rate is the numerator count multiplied by 100 and
    divided by the denominator count, rounded half up to two decimal places. When the
    denominator count is zero the rate is exactly 0.00 — never empty, never an error."
    PRD §3.9: "Only placements reached through lockboxes belonging to the association in
    question are considered, and placements still in `PLACED` or `REMOVAL_DUE` fall into
    neither the numerator nor the denominator under either reading."

    Design: Difficulty/boundary_precision_check/recovery_summary_empty_denominator_returns_zero_not_error
    """
    ctx = setup_placed_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)

    response = api.get_recovery_summary(
        ctx["association_id"],
        auditor_headers,
        params={"variant": "closing_cohort", **SUMMARY_WINDOW},
    )
    data = validate_success(response, 200)
    assert data["denominator_count"] == 0
    assert data["numerator_count"] == 0
    assert float(data["recovery_rate_pct"]) == pytest.approx(0.00, abs=0.01)


def test_recovery_summary_reports_the_board_target_and_posture(api, auditor_headers):
    """PRD §3.9: "The summary response reports the `variant` that was applied, the
    `window_start` and `window_end` that bounded it, the `denominator_count`, the
    `numerator_count`, the computed `recovery_rate_pct`, the board's `recovery_target_pct` for
    comparison, and the association's current `posture`."
    PRD §3.1: "A freshly registered association starts with `posture` set to `OPEN`,
    `recovery_rate_pct` set to 0.00, and every counter at zero."

    Design: Difficulty/boundary_precision_check/recovery_summary_empty_denominator_returns_zero_not_error
    """
    ctx = setup_placed_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)

    response = api.get_recovery_summary(
        ctx["association_id"],
        auditor_headers,
        params={"variant": "closing_cohort", **SUMMARY_WINDOW},
    )
    data = validate_success(response, 200)
    assert float(data["recovery_target_pct"]) == pytest.approx(95.00, abs=0.01)
    assert data["posture"] == "OPEN"

    association = read_association(ctx["association_id"])
    assert float(association["recovery_rate_pct"]) == pytest.approx(0.00, abs=0.01)


def test_recovery_summary_defaults_to_the_closing_cohort_reading(api, admin_headers):
    """PRD §3.9: "The **closing-cohort** reading — the default, used when `variant` is omitted
    or is given as `closing_cohort` — asks: of the deals that closed in this window, how many
    boxes came back on time?"
    PRD §3.9: "The summary response reports the `variant` that was applied, the `window_start`
    and `window_end` that bounded it, the `denominator_count`, the `numerator_count`, the
    computed `recovery_rate_pct`, the board's `recovery_target_pct` for comparison, and the
    association's current `posture`."

    Design: Corner/calculations/recovery_summary_defaults_to_closing_cohort_variant
    """
    association = register_association()

    response = api.get_recovery_summary(association["id"], admin_headers)
    data = validate_success(response, 200)
    assert data["variant"] == "closing_cohort"
    assert data["denominator_count"] == 0
    assert float(data["recovery_rate_pct"]) == pytest.approx(0.00, abs=0.01)
    assert data["posture"] == "OPEN"
    assert float(data["recovery_target_pct"]) == pytest.approx(95.00, abs=0.01)


def test_compliance_run_with_nothing_due_reports_all_zero_counts(api, admin_headers):
    """PRD §3.9: "The checkpoint reports what it did, returning the `run_at` instant it
    executed at together with `expired_grant_count`, `expired_credential_count`,
    `expired_member_count`, `delinquent_placement_count`, `accrued_charge_count`, and the
    resulting `recovery_rate_pct` and `posture`."
    PRD §2.4: "Before any caller sets it, the clock reads exactly `2026-08-01T00:00:00Z`, and
    it never falls back to the host's real time."

    Design: Corner/endpoints/compliance_run_with_nothing_due_returns_all_zero_counts
    """
    ctx = setup_placed_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)

    response = api.run_compliance_checkpoint(ctx["association_id"], admin_headers)
    data = validate_success(response, 200)
    assert data["run_at"].startswith("2026-08-01T00:00:00")
    assert data["expired_grant_count"] == 0
    assert data["expired_credential_count"] == 0
    assert data["expired_member_count"] == 0
    assert data["delinquent_placement_count"] == 0
    assert data["accrued_charge_count"] == 0
    assert float(data["recovery_rate_pct"]) == pytest.approx(0.00, abs=0.01)
    assert data["posture"] == "OPEN"

    placement = read_placement(ctx["placement_id"])
    assert placement["placement_status"] == "PLACED"
    assert placement["billing_status"] == "NONE"

    assert list_charges(member_id=ctx["agent_id"]) == []
