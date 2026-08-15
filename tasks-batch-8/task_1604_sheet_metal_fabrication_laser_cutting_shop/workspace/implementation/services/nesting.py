"""Nest & yield engine: guillotine grid packing, stock selection, remnant generation."""
import math
from decimal import Decimal

from db import store, new_id, touch, new_common
from errors import ApiError
from services.pricing import dec, rhu, part_area_cm2

STANDARD_SHEET_W_MM = 1200
STANDARD_SHEET_H_MM = 2400
KERF_ALLOWANCE_PER_SHEET_CM2 = 5000
MIN_REMNANT_AREA_CM2 = 2000


def _eligible_pool(line, pool):
    """AVAILABLE FULL_SHEET/REMNANT rows matching grade+thickness that can hold the part."""
    thickness = dec(line["thickness_mm"])
    pw = line["bbox_width_mm"]
    ph = line["bbox_height_mm"]
    part_area_mm2 = pw * ph
    out = []
    for s in pool:
        if s["grade_id"] != line["grade_id"]:
            continue
        if dec(s["thickness_mm"]) != thickness:
            continue
        if s["width_mm"] * s["height_mm"] < part_area_mm2:
            continue
        if s["width_mm"] < pw or s["height_mm"] < ph:
            continue
        out.append(s)
    # remnants preferred, then smallest area, ties by created_at ASC
    out.sort(key=lambda s: (0 if s["kind"] == "REMNANT" else 1,
                            s["width_mm"] * s["height_mm"], s["created_at"], s["_seq"]))
    return out


def simulate_nest(lines, pool, now=None):
    """Pure nest plan: returns placements [(sheet, line, placed, cols, rows)].
    Raises ERR_NEST_INFEASIBLE if any line cannot be fully placed. No mutation."""
    placements = []
    used = set()
    for line in lines:
        remaining = line["qty"]
        pw = line["bbox_width_mm"]
        ph = line["bbox_height_mm"]
        for sheet in _eligible_pool(line, pool):
            if remaining <= 0:
                break
            if sheet["id"] in used:
                continue
            cols = sheet["width_mm"] // pw
            rows = sheet["height_mm"] // ph
            capacity = cols * rows
            if capacity <= 0:
                continue
            placed = min(capacity, remaining)
            placements.append((sheet, line, placed, cols, rows))
            used.add(sheet["id"])
            remaining -= placed
        if remaining > 0:
            raise ApiError("ERR_NEST_INFEASIBLE", 409,
                           "Available stock cannot hold every part")
    return placements


def apply_nest(order, placements):
    """Commit a nest plan: consume stock, create NestSheet rows and remnant stock."""
    sheet_index = 0
    total_plate = Decimal(0)
    for sheet, line, placed, cols, rows in placements:
        pw = line["bbox_width_mm"]
        ph = line["bbox_height_mm"]
        part_area = part_area_cm2(line)
        chargeable = rhu(Decimal(placed) * part_area, 1)
        plate_in = chargeable + Decimal(KERF_ALLOWANCE_PER_SHEET_CM2)
        yield_pct = rhu(chargeable / plate_in, 4)

        sheet["status"] = "CONSUMED"
        touch(sheet)

        # remnant candidates: right strip vs top strip (tie -> right strip)
        cols_used = cols if placed > cols else placed
        rows_used = int(math.ceil(placed / cols)) if cols else 0
        right_w = sheet["width_mm"] - cols_used * pw
        right_area_mm2 = right_w * sheet["height_mm"]
        top_h = sheet["height_mm"] - rows_used * ph
        top_area_mm2 = (cols_used * pw) * top_h
        if right_area_mm2 >= top_area_mm2:
            rem_w, rem_h, rem_area = right_w, sheet["height_mm"], right_area_mm2
        else:
            rem_w, rem_h, rem_area = cols_used * pw, top_h, top_area_mm2
        remnant_id = None
        if Decimal(rem_area) >= Decimal(MIN_REMNANT_AREA_CM2 * 100) and rem_w > 0 and rem_h > 0:
            remnant = {
                "id": new_id(),
                "grade_id": sheet["grade_id"],
                "thickness_mm": sheet["thickness_mm"],
                "width_mm": int(rem_w),
                "height_mm": int(rem_h),
                "kind": "REMNANT",
                "status": "AVAILABLE",
                "source_order_id": order["id"],
            }
            new_common(remnant)
            store.sheet_stock[remnant["id"]] = remnant
            remnant_id = remnant["id"]

        nest = {
            "id": new_id(),
            "order_id": order["id"],
            "sheet_stock_id": sheet["id"],
            "sheet_index": sheet_index,
            "chargeable_area_cm2": float(chargeable),
            "kerf_allowance_cm2": float(KERF_ALLOWANCE_PER_SHEET_CM2),
            "plate_in_area_cm2": float(plate_in),
            "yield_pct": float(yield_pct),
            "remnant_stock_id": remnant_id,
        }
        new_common(nest)
        store.nest_sheets[nest["id"]] = nest
        sheet_index += 1
        total_plate += plate_in
    order["total_plate_area_cm2"] = int(rhu(total_plate, 0))
    return sheet_index


def release_nest(order):
    """Discard an order's nest: consumed sheets back to AVAILABLE, generated
    REMNANT rows to SCRAPPED, NestSheet rows deleted."""
    own = [ns for ns in store.nest_sheets.values() if ns["order_id"] == order["id"]]
    for ns in own:
        sheet = store.sheet_stock.get(ns["sheet_stock_id"])
        if sheet is not None and sheet["status"] == "CONSUMED":
            sheet["status"] = "AVAILABLE"
            touch(sheet)
        if ns["remnant_stock_id"]:
            remnant = store.sheet_stock.get(ns["remnant_stock_id"])
            if remnant is not None and remnant["status"] != "SCRAPPED":
                remnant["status"] = "SCRAPPED"
                touch(remnant)
        del store.nest_sheets[ns["id"]]
    order["total_plate_area_cm2"] = 0
