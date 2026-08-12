"""Parts sourcing and the stock conservation law: reservation, compensating
release, atomic stock-gate abort, outstanding-lines gate, superseded-part
rejection, and part-line listing filters."""

import test_helpers as fx
from test_helpers import (
    PM,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)

STOCK_PARTS_SPEC = [
    {"oem_status": "ACTIVE", "unit_cost_cents": 1_250_000, "stock_quantity": 10, "quantity": 2},
]


class TestPartStockConservation:
    def test_begin_sourcing_reserves_stock(self, api):
        """PRD §3.4: "When all gates pass, every `PENDING` line on an `ACTIVE` part becomes `RESERVED` and the part's `reserved_quantity` grows by each line's `quantity`; every `PENDING` line on an `OBSOLETE` part instead becomes `RE_PENDING` and the system auto-creates a ReverseEngineeringJob in `REQUESTED` for that line; and the machine under rebuild moves from `ASSESSED` to `IN_PROJECT`."
        PRD §2.9: "The part ledger obeys a strict conservation law: for every Part, `available_quantity` plus `reserved_quantity` always equals `stock_quantity`."

        Design: Difficulty/compensating_invariant/part_stock_conservation_across_reserve_and_cancel
        """
        ctx = fx.setup_project_approved(parts_spec=STOCK_PARTS_SPEC)
        part = ctx.parts[0]
        line = ctx.lines[0]

        project = validate_success(api.begin_sourcing(ctx.project["id"], PM), 200)
        assert project["work_status"] == "PARTS_SOURCING"

        line_after = validate_success(api.get_part_line(line["id"], PM), 200)
        assert line_after["status"] == "RESERVED"

        part_after = fx.get_part(part["id"])
        assert part_after["reserved_quantity"] == 2
        assert part_after["available_quantity"] == 8
        assert part_after["stock_quantity"] == 10
        fx.assert_part_stock_conservation(part_after)

        machine_after = fx.get_machine(ctx.machine["id"])
        assert machine_after["status"] == "IN_PROJECT"

    def test_line_cancel_releases_reservation_without_drift(self, api):
        """PRD §3.4: "A `ProjectManager` may cancel a line instead: a `PENDING` line may be cancelled only while the project is `DECIDED` (and doing so raises `quote_stale`), while a `RESERVED` line may be cancelled while the project is `DECIDED` or `PARTS_SOURCING` (which additionally releases the reservation, decreasing the part's `reserved_quantity` by the line's `quantity`)."
        PRD §2.9: "Releasing a reservation — through a line cancellation or a project-level cancellation cascade — decreases `reserved_quantity` alone (so `available_quantity` recomputes upward)."

        Design: Difficulty/compensating_invariant/part_stock_conservation_across_reserve_and_cancel
        """
        ctx = fx.setup_project_approved(parts_spec=STOCK_PARTS_SPEC)
        part = ctx.parts[0]
        line = ctx.lines[0]
        validate_success(api.begin_sourcing(ctx.project["id"], PM), 200)

        cancelled = validate_success(api.cancel_part_line(line["id"], PM), 200)
        assert cancelled["status"] == "CANCELLED"

        part_after = fx.get_part(part["id"])
        assert part_after["reserved_quantity"] == 0
        assert part_after["available_quantity"] == 10
        assert part_after["stock_quantity"] == 10
        fx.assert_part_stock_conservation(part_after)


def test_insufficient_stock_aborts_begin_sourcing_atomically(api):
    """PRD §3.4: "Then comes the stock gate: for every `PENDING` line on an `ACTIVE` part, examined in ascending order of line creation, the part's `available_quantity` must cover the line's `quantity`; the first line that fails aborts the entire operation with `ERR_INSUFFICIENT_STOCK` and no reservations whatsoever are applied — the check is atomic."
    PRD §2.9: "Any reservation that would drive a part's `available_quantity` negative is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/insufficient_stock_aborts_begin_sourcing_atomically
    """
    ctx = fx.setup_project_approved(
        parts_spec=[
            {"oem_status": "ACTIVE", "unit_cost_cents": 1_250_000, "stock_quantity": 1,
             "quantity": 2, "lead_time_days": 30, "description": "Rare encoder"},
        ]
    )
    part = ctx.parts[0]

    res = api.begin_sourcing(ctx.project["id"], PM)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)

    project_after = fx.get_project(ctx.project["id"])
    assert project_after["work_status"] == "DECIDED"

    part_after = fx.get_part(part["id"])
    assert part_after["reserved_quantity"] == 0
    assert part_after["available_quantity"] == 1
    assert part_after["stock_quantity"] == 1


def test_start_rebuild_with_reserved_lines_rejected(api):
    """PRD §3.4: "Once every line of the project sits in `FULFILLED`, `RE_FULFILLED`, or `CANCELLED`, a `ProjectManager` may start the physical rebuild; if any line is still `PENDING`, `RESERVED`, or `RE_PENDING`, the attempt fails with `ERR_LINES_OUTSTANDING`."

    Design: Corner/validations/start_rebuild_with_reserved_lines_rejected
    """
    ctx = fx.setup_project_approved(parts_spec=STOCK_PARTS_SPEC)
    validate_success(api.begin_sourcing(ctx.project["id"], PM), 200)
    # Line stays RESERVED — never fulfilled.

    res = api.start_rebuild(ctx.project["id"], PM)
    validate_error(res, ApiErrorId.ERR_LINES_OUTSTANDING.value)

    project_after = fx.get_project(ctx.project["id"])
    assert project_after["work_status"] == "PARTS_SOURCING"


def test_part_superseded_cannot_be_lined_and_reverse_lookup(api):
    """PRD §3.4: "Referencing a part whose `oem_status` is `SUPERSEDED` is rejected with `ERR_PART_SUPERSEDED` — the replacement must be ordered instead."
    PRD §3.4: "Parts can be listed with an optional `superseded_by_id` filter to trace obsolescence chains."

    Design: Corner/validations/part_superseded_cannot_be_lined_and_reverse_lookup
    """
    ctx = fx.setup_project_decided()
    replacement = fx.create_part(
        part_number="P-NEW-1", description="Servo drive gen2", oem_status="ACTIVE",
        unit_cost_cents=2_000_000, stock_quantity=4, lead_time_days=21,
    )
    old = fx.create_part(
        part_number="P-OLD-1", description="Servo drive gen1", oem_status="SUPERSEDED",
        superseded_by_id=replacement["id"], unit_cost_cents=1_500_000,
        stock_quantity=2, lead_time_days=21,
    )

    res = api.add_part_line(
        ctx.project["id"],
        {"part_id": old["id"], "quantity": 1},
        PM,
    )
    validate_error(res, ApiErrorId.ERR_PART_SUPERSEDED.value)

    listed, meta = validate_paginated(
        api.list_parts(PM, params={"superseded_by_id": replacement["id"]})
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == old["id"]


def test_part_lines_filtered_list_isolates_by_part(api):
    """PRD §3.4: "Part lines can be listed with optional `project_id` and `part_id` filters."

    Design: Corner/endpoints/part_lines_filtered_list_isolates_by_part
    """
    ctx = fx.setup_project_decided(
        parts_spec=[
            {"oem_status": "ACTIVE", "unit_cost_cents": 1_250_000, "stock_quantity": 10,
             "quantity": 2},
            {"oem_status": "OBSOLETE", "unit_cost_cents": 800_000, "stock_quantity": 0,
             "quantity": 3, "lead_time_days": 60, "description": "NC board"},
        ]
    )
    part_a = ctx.parts[0]

    data, meta = validate_paginated(api.list_part_lines(PM, params={"part_id": part_a["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["part_id"] == part_a["id"]
    assert data[0]["quantity"] == 2
    assert data[0]["project_id"] == ctx.project["id"]
