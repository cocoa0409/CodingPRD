"""Derived state is readable in the same request cycle that produced it."""
from test_helpers import (
    acknowledge,
    api_client,
    assert_same_instant,
    make_admin_headers,
    make_author_headers,
    patch_employee,
    refresh_package,
    validate_paginated,
    validate_success,
)


def test_release_acknowledgment_and_termination_are_all_visible_to_the_next_read():
    """PRD §3.6: "The shared numerator is the count of the package's assignments whose
    `ack_state` is `ACKNOWLEDGED` or `EXEMPT`" ... "The `snapshot_roster` variant divides
    that numerator by `roster_snapshot_size`, the mint count frozen at release time,
    which still includes rows later voided and rows whose assignee has since become
    `TERMINATED`" ... "The `live_roster` variant divides the same numerator by the count
    of the package's assignments whose `ack_state` is anything other than `VOIDED` and
    whose assignee's `employment_status` is `ACTIVE` or `ON_LEAVE`" ... "Both variants
    are computed when the package is released, and again when it closes, and again on
    every coverage read; the coverage read recomputes and returns both numbers
    **without** incrementing the package's `version`."

    Design: Corner/consistency model/corner_coverage_is_readable_immediately_in_the_same_request
    """
    from test_helpers import deliver, retention_rows_for, setup_released_scenario, sole_assignment

    ctx = setup_released_scenario(
        jurisdiction={
            "min_legal_review_days": 5,
            "ack_deadline_days": 30,
            "esign_permitted": True,
        },
        extra_employees=1,
        effective_date="2026-09-01T00:00:00Z",
    )
    package, subject, other = ctx["package"], ctx["employee"], ctx["extras"][0]
    assert package["status"] == "RELEASED", (
        f"the release response itself must report RELEASED, got {package['status']}"
    )
    assert package["roster_snapshot_size"] == 2, (
        "the release response already carries the mint count, got "
        f"{package['roster_snapshot_size']}"
    )
    assert float(package["coverage_snapshot_pct"]) == 0.00, (
        "the release response already carries both variants, got "
        f"{package['coverage_snapshot_pct']}"
    )
    assert float(package["coverage_live_pct"]) == 0.00

    asg2 = deliver(sole_assignment(package["id"], other["id"])["id"])
    assert asg2["ack_state"] == "PENDING"

    ack = acknowledge(ctx["assignment"], subject["id"])
    assert ack["status"] == "EFFECTIVE", (
        f"a capture on the window's own start instant is accepted, got {ack['status']}"
    )
    assert_same_instant(ack["captured_at"], "2026-09-01T00:00:00.000Z", "captured_at")

    first = validate_success(api_client.get_coverage(package["id"], make_admin_headers()))
    baseline_version = first["version"]
    assert float(first["coverage_snapshot_pct"]) == 50.00, (
        "one of two acknowledged is 50.00 with no sweep in between, got "
        f"{first['coverage_snapshot_pct']}"
    )
    assert float(first["coverage_live_pct"]) == 50.00, (
        f"the live denominator is still 2, got {first['coverage_live_pct']}"
    )

    _rows, meta = validate_paginated(
        api_client.list_acknowledgments(
            make_admin_headers(),
            params={"assignment_id": ctx["assignment"]["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, (
        f"the capture is listable in the same request cycle, got {meta['total_count']}"
    )
    rows = retention_rows_for(subject["id"])
    assert len(rows) == 1, f"one capture appends one retention row, got {len(rows)}"
    assert rows[0]["record_kind"] == "CAPTURE"
    assert rows[0]["signed_delta"] == 1, (
        f"a CAPTURE row carries signed_delta +1, got {rows[0]['signed_delta']}"
    )

    patch_employee(other["id"], employment_status="TERMINATED")
    second = validate_success(api_client.get_coverage(package["id"], make_author_headers()))
    assert float(second["coverage_snapshot_pct"]) == 50.00, (
        "the frozen denominator of 2 still includes the terminated assignee, got "
        f"{second['coverage_snapshot_pct']}"
    )
    assert float(second["coverage_live_pct"]) == 100.00, (
        "the live denominator drops to 1 on the very next read, got "
        f"{second['coverage_live_pct']}"
    )
    assert second["version"] == baseline_version, (
        "no coverage read may increment the package version off "
        f"{baseline_version}, got {second['version']}"
    )
    assert refresh_package(package["id"])["status"] == "RELEASED", (
        "the second assignment is still PENDING even though its assignee is "
        f"TERMINATED, got {refresh_package(package['id'])['status']}"
    )
