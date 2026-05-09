from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from db import db


INSTRUMENT_SET_BASE_FEE = Decimal("150.00")
STAFF_MAX_WORKING_MINUTES_PER_DAY = 720
STERILIZATION_EXPIRY_MINUTES = 4320


def to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value: Decimal, places: int = 2) -> Decimal:
    quant = Decimal(10) ** -places
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def billable_hours(duration_minutes: int) -> int:
    if duration_minutes <= 0:
        return 0
    # ceil(duration / 60)
    q = (duration_minutes + 59) // 60
    return int(q)


def case_assignments_for(case_id: str):
    return [a for a in db.case_assignments.values() if a.get("case_id") == case_id]


def provisional_cost_estimate(case: dict, room: dict) -> tuple[Decimal, Decimal]:
    """Return (estimated_total_amount, implant_component)."""
    duration = case["planned_end_minute"] - case["planned_start_minute"]
    bh = billable_hours(duration)
    room_component = round_half_up(Decimal(bh) * to_decimal(room["hourly_rate"]))
    staff_total = Decimal("0.00")
    for a in case_assignments_for(case["id"]):
        if a["status"] == "RESERVED":
            staff = db.staff_members.get(a["staff_id"])
            if staff is None:
                continue
            staff_total += round_half_up(Decimal(bh) * to_decimal(staff["hourly_rate"]))
    instrument_component = round_half_up(INSTRUMENT_SET_BASE_FEE)
    implant_component = round_half_up(to_decimal(case.get("implant_cost_estimate") or 0))
    total = room_component + staff_total + instrument_component + implant_component
    return total, implant_component


def final_settlement_cost(case: dict, room: dict) -> tuple[Decimal, Decimal]:
    duration = case["actual_end_minute"] - case["actual_start_minute"]
    bh = billable_hours(duration)
    room_component = round_half_up(Decimal(bh) * to_decimal(room["hourly_rate"]))
    staff_total = Decimal("0.00")
    for a in case_assignments_for(case["id"]):
        if a["status"] == "COMPLETED":
            staff = db.staff_members.get(a["staff_id"])
            if staff is None:
                continue
            staff_total += round_half_up(Decimal(bh) * to_decimal(staff["hourly_rate"]))
    instrument_component = round_half_up(INSTRUMENT_SET_BASE_FEE)
    implant_actual = case.get("implant_cost_actual")
    if implant_actual is None:
        implant_actual = case.get("implant_cost_estimate") or 0
    implant_component = round_half_up(to_decimal(implant_actual))
    total = room_component + staff_total + instrument_component + implant_component
    return total, implant_component


def build_line_items(case: dict, room: dict, implant_component: Decimal) -> list:
    """Build per-component line items from the FINAL settlement breakdown."""
    duration = case["actual_end_minute"] - case["actual_start_minute"]
    bh = billable_hours(duration)
    items = []

    room_fee = round_half_up(Decimal(bh) * to_decimal(room["hourly_rate"]))
    items.append({
        "description": f"Operating room {room.get('room_number', '')} ({bh} billable hours)",
        "category": "ROOM",
        "fee": room_fee,
    })

    for a in case_assignments_for(case["id"]):
        if a["status"] != "COMPLETED":
            continue
        staff = db.staff_members.get(a["staff_id"])
        if staff is None:
            continue
        fee = round_half_up(Decimal(bh) * to_decimal(staff["hourly_rate"]))
        items.append({
            "description": f"Staff {staff.get('staff_name', '')} ({a.get('role_in_case', '')})",
            "category": "STAFF",
            "fee": fee,
        })

    items.append({
        "description": "Instrument set base fee",
        "category": "INSTRUMENT",
        "fee": round_half_up(INSTRUMENT_SET_BASE_FEE),
    })
    items.append({
        "description": "Implant cost",
        "category": "IMPLANT",
        "fee": round_half_up(implant_component),
    })
    return items


def insurance_split_calculation(total: Decimal, splits: list) -> list:
    """Return list of {payer_id, amount} aligned with input order; primary absorbs remainder."""
    out = []
    for entry in splits:
        amt = round_half_up(total * to_decimal(entry["percentage"]) / Decimal(100))
        out.append({"payer_id": entry["payer_id"], "amount": amt})
    if out:
        ssum = sum((x["amount"] for x in out), Decimal("0.00"))
        remainder = round_half_up(total - ssum)
        out[0]["amount"] = round_half_up(out[0]["amount"] + remainder)
    return out


def staff_working_hours_total(staff_id: str, planned_start: int, planned_end: int) -> int:
    """Total minutes within 1440-min window centered at planned_start, including new schedule."""
    window_start = planned_start - 720
    window_end = planned_start + 720
    existing = 0
    for a in db.case_assignments.values():
        if a["staff_id"] != staff_id:
            continue
        if a["status"] not in {"RESERVED", "CONFIRMED", "COMPLETED"}:
            continue
        a_start = a["assigned_start_minute"]
        a_end = a["assigned_end_minute"]
        # half-open intersect
        if a_start < window_end and a_end > window_start:
            existing += (a_end - a_start)
    new = planned_end - planned_start
    return existing + new


def planned_workload_minutes(staff_id: str) -> int:
    total = 0
    for a in db.case_assignments.values():
        if a["staff_id"] != staff_id:
            continue
        if a["status"] not in {"RESERVED", "CONFIRMED", "COMPLETED"}:
            continue
        total += a["assigned_end_minute"] - a["assigned_start_minute"]
    return total


def actual_workload_minutes(staff_id: str) -> int:
    total = 0
    for a in db.case_assignments.values():
        if a["staff_id"] != staff_id:
            continue
        if a["status"] != "COMPLETED":
            continue
        case = db.surgical_cases.get(a["case_id"])
        if not case:
            continue
        if case.get("actual_start_minute") is None or case.get("actual_end_minute") is None:
            continue
        total += case["actual_end_minute"] - case["actual_start_minute"]
    return total
