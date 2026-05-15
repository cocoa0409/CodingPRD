"""Halls, FloorPlanVersions, and Booths (§3.2)."""

from __future__ import annotations

import db
import clock
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_FIRE_SAFETY_CELL,
    ERR_FLOOR_PLAN_LOCKED,
)
from services.common import (
    stamp_create,
    stamp_create_appendonly,
    bump,
    check_occ,
    must_dict,
)
from services import calculations


# ----------------------- HALL -----------------------
def create_hall(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    body = must_dict(body)
    required = ("hall_code", "zone_label", "aisle_label", "grid_rows", "grid_cols")
    for f in required:
        if f not in body or body[f] in (None, ""):
            raise AppError(ERR_INVALID_INPUT, f"Missing required field '{f}'.", 422)
    if not isinstance(body["grid_rows"], int) or body["grid_rows"] <= 0:
        raise AppError(ERR_INVALID_INPUT, "grid_rows must be a positive integer.", 422)
    if not isinstance(body["grid_cols"], int) or body["grid_cols"] <= 0:
        raise AppError(ERR_INVALID_INPUT, "grid_cols must be a positive integer.", 422)
    fire_cells = body.get("fire_safety_zone_cells") or []
    if not isinstance(fire_cells, list):
        raise AppError(ERR_INVALID_INPUT, "fire_safety_zone_cells must be an array.", 422)
    # hall_code uniqueness within exhibition
    for h in db.halls.values():
        if h["exhibition_id"] == exhibition_id and h["hall_code"] == body["hall_code"]:
            raise AppError(ERR_INVALID_INPUT, "hall_code already exists in this exhibition.", 422)
    row = {
        "exhibition_id": exhibition_id,
        "hall_code": body["hall_code"],
        "zone_label": body["zone_label"],
        "aisle_label": body["aisle_label"],
        "grid_rows": int(body["grid_rows"]),
        "grid_cols": int(body["grid_cols"]),
        "fire_safety_zone_cells": list(fire_cells),
        "floor_plan_active_version": 1,
    }
    stamp_create(row)
    db.halls[row["id"]] = row
    return row


# ----------------------- FLOOR PLAN -----------------------
def create_floor_plan(hall_id: str, body: dict) -> dict:
    hall = db.halls.get(hall_id)
    if hall is None:
        raise AppError(ERR_NOT_FOUND, "Hall not found.", 404)
    body = must_dict(body)
    cells = body.get("cells")
    if not isinstance(cells, list) or not cells:
        raise AppError(ERR_INVALID_INPUT, "cells must be a non-empty array.", 422)
    # Validate per-cell shape.
    valid_kinds = {"FIXED", "MODULAR", "FIRE_SAFETY"}
    for c in cells:
        if not isinstance(c, dict):
            raise AppError(ERR_INVALID_INPUT, "Each cell must be an object.", 422)
        for fk in ("row", "col", "kind"):
            if fk not in c:
                raise AppError(ERR_INVALID_INPUT, f"Cell missing '{fk}'.", 422)
        if c["kind"] not in valid_kinds:
            raise AppError(ERR_INVALID_INPUT, f"Invalid cell kind '{c['kind']}'.", 422)
    # Compute next version_number for this hall.
    prior_versions = [
        fp["version_number"] for fp in db.floor_plans.values() if fp["hall_id"] == hall_id
    ]
    next_version = (max(prior_versions) + 1) if prior_versions else 1
    row = {
        "hall_id": hall_id,
        "version_number": next_version,
        "status": "DRAFT",
        "published_at": None,
        "cells": [
            {
                "row": int(c["row"]),
                "col": int(c["col"]),
                "kind": c["kind"],
                "power_kw": c.get("power_kw", 0),
                "water_lpm": c.get("water_lpm", 0),
                "network_mbps": int(c.get("network_mbps", 0) or 0),
            }
            for c in cells
        ],
    }
    stamp_create_appendonly(row)
    db.floor_plans[row["id"]] = row
    return row


def activate_floor_plan(hall_id: str, plan_id: str, body: dict) -> dict:
    hall = db.halls.get(hall_id)
    if hall is None:
        raise AppError(ERR_NOT_FOUND, "Hall not found.", 404)
    plan = db.floor_plans.get(plan_id)
    if plan is None or plan["hall_id"] != hall_id:
        raise AppError(ERR_NOT_FOUND, "Floor plan not found.", 404)
    ex = db.exhibitions.get(hall["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if plan["status"] != "DRAFT":
        raise AppError(ERR_INVALID_STATE, "Floor plan not in DRAFT.", 409)
    if ex["status"] != "DRAFT":
        raise AppError(ERR_FLOOR_PLAN_LOCKED, "Cannot activate after intake opens.", 409)
    # Cells must exactly cover the grid; no duplicate (row, col).
    seen = set()
    for c in plan["cells"]:
        if not (1 <= c["row"] <= hall["grid_rows"] and 1 <= c["col"] <= hall["grid_cols"]):
            # Allow row/col indexed from 0 as well — only verify uniqueness + coverage.
            if not (0 <= c["row"] < hall["grid_rows"] and 0 <= c["col"] < hall["grid_cols"]):
                raise AppError(ERR_INVALID_INPUT, "Cell out of grid bounds.", 422)
        key = (c["row"], c["col"])
        if key in seen:
            raise AppError(ERR_INVALID_INPUT, "Duplicate cell (row,col) in plan.", 422)
        seen.add(key)
    expected = hall["grid_rows"] * hall["grid_cols"]
    if len(seen) != expected:
        raise AppError(ERR_INVALID_INPUT, "Cells do not cover full grid.", 422)
    # body may carry OCC version; plan has no version though. Accept body silently.
    must_dict(body)
    # Supersede prior ACTIVE plans on the same hall.
    for prior in db.floor_plans.values():
        if prior["hall_id"] == hall_id and prior["status"] == "ACTIVE":
            prior["status"] = "SUPERSEDED"
            # Cascade booths.
            for booth in db.booths.values():
                if booth["floor_plan_version_id"] == prior["id"]:
                    booth["status"] = "BLOCKED"
                    bump(booth)
    plan["status"] = "ACTIVE"
    plan["published_at"] = clock.iso()
    hall["floor_plan_active_version"] = plan["version_number"]
    bump(hall)
    return plan


# ----------------------- BOOTH -----------------------
def _is_corner(cells, hall) -> bool:
    """Touches at least two perpendicular aisle edges = corner.

    We treat the hall's outer perimeter as aisle edges. A corner is when the
    booth's occupied-cell set touches both a horizontal edge (row == min_row or
    row == max_row of the hall) AND a vertical edge (col == min_col or col ==
    max_col of the hall).
    """
    rows = [int(c["row"]) for c in cells]
    cols = [int(c["col"]) for c in cells]
    if not rows:
        return False
    grid_rows = int(hall["grid_rows"])
    grid_cols = int(hall["grid_cols"])
    # Support both 0-indexed and 1-indexed grids.
    if min(rows) >= 1:
        min_r, max_r = 1, grid_rows
    else:
        min_r, max_r = 0, grid_rows - 1
    if min(cols) >= 1:
        min_c, max_c = 1, grid_cols
    else:
        min_c, max_c = 0, grid_cols - 1
    touches_h = any(r in (min_r, max_r) for r in rows)
    touches_v = any(c in (min_c, max_c) for c in cols)
    return touches_h and touches_v


def create_booth(hall_id: str, body: dict) -> dict:
    hall = db.halls.get(hall_id)
    if hall is None:
        raise AppError(ERR_NOT_FOUND, "Hall not found.", 404)
    ex = db.exhibitions.get(hall["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    body = must_dict(body)
    for f in ("code", "cells", "tier"):
        if f not in body or body[f] in (None, ""):
            raise AppError(ERR_INVALID_INPUT, f"Missing required field '{f}'.", 422)
    if body["tier"] not in ("STANDARD", "PREMIUM", "ISLAND"):
        raise AppError(ERR_INVALID_INPUT, "Invalid tier.", 422)
    if not isinstance(body["cells"], list) or not body["cells"]:
        raise AppError(ERR_INVALID_INPUT, "cells must be a non-empty array.", 422)
    # code unique within hall
    for b in db.booths.values():
        if b["hall_id"] == hall_id and b["code"] == body["code"]:
            raise AppError(ERR_INVALID_INPUT, "Booth code already exists in this hall.", 422)

    # Find the ACTIVE floor plan for this hall.
    active_plan = None
    for fp in db.floor_plans.values():
        if fp["hall_id"] == hall_id and fp["status"] == "ACTIVE":
            active_plan = fp
            break
    if active_plan is None:
        raise AppError(ERR_INVALID_STATE, "No ACTIVE floor plan on this hall.", 409)

    # Build cell lookup from the active plan.
    plan_cells = {(c["row"], c["col"]): c for c in active_plan["cells"]}

    # Verify each booth cell exists in the plan and is kind FIXED/MODULAR.
    for bc in body["cells"]:
        if not isinstance(bc, dict) or "row" not in bc or "col" not in bc:
            raise AppError(ERR_INVALID_INPUT, "Each booth cell must have row/col.", 422)
        key = (int(bc["row"]), int(bc["col"]))
        plan_cell = plan_cells.get(key)
        if plan_cell is None:
            raise AppError(ERR_INVALID_INPUT, f"Cell {key} not in plan.", 422)
        if plan_cell["kind"] == "FIRE_SAFETY":
            raise AppError(ERR_FIRE_SAFETY_CELL, "Cannot place booth on fire-safety cell.", 422)
        if plan_cell["kind"] not in ("FIXED", "MODULAR"):
            raise AppError(ERR_INVALID_INPUT, "Booth cells must be FIXED or MODULAR.", 422)

    # Compute capacities.
    cells_simple = [{"row": int(c["row"]), "col": int(c["col"])} for c in body["cells"]]
    power = 0.0
    water = 0.0
    network = 0
    for bc in cells_simple:
        pc = plan_cells[(bc["row"], bc["col"])]
        power += float(pc.get("power_kw") or 0)
        water += float(pc.get("water_lpm") or 0)
        network += int(pc.get("network_mbps") or 0)
    is_corner = _is_corner(cells_simple, hall)
    row = {
        "hall_id": hall_id,
        "floor_plan_version_id": active_plan["id"],
        "code": body["code"],
        "cells": cells_simple,
        "tier": body["tier"],
        "is_corner": is_corner,
        "power_kw_capacity": power,
        "water_lpm_capacity": water,
        "network_mbps_capacity": network,
        "status": "AVAILABLE",
    }
    stamp_create(row)
    row["base_price_cents"] = calculations.booth_quoted_price(row, ex)
    db.booths[row["id"]] = row
    return row


def list_booths_in_hall(hall_id: str, status_filter: str | None, limit: int, offset: int):
    hall = db.halls.get(hall_id)
    if hall is None:
        raise AppError(ERR_NOT_FOUND, "Hall not found.", 404)
    items = [b for b in db.booths.values() if b["hall_id"] == hall_id]
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    items.sort(key=lambda b: b["created_at"])
    return items[offset:offset + limit], len(items)


def get_booth(booth_id: str) -> dict:
    booth = db.booths.get(booth_id)
    if booth is None:
        raise AppError(ERR_NOT_FOUND, "Booth not found.", 404)
    return booth
