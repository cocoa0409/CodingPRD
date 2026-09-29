"""Qualification rows, volume aggregates, rank evaluation, sell-through."""

from common import clock_str, new_row, touch, trunc_div
from db import db
from services import planlib
from services.genealogy import by_created, children_of


def rows_of_period(period_id):
    return by_created([r for r in db.qualifications.values() if r["qualification_period_id"] == period_id])


def row_for(period_id, consultant_id):
    for row in rows_of_period(period_id):
        if row["consultant_id"] == consultant_id:
            return row
    return None


def ensure_row(period, consultant_id):
    existing = row_for(period["id"], consultant_id)
    if existing is not None:
        return existing
    row = new_row()
    row.update(
        {
            "consultant_id": consultant_id,
            "qualification_period_id": period["id"],
            "period_code": period["period_code"],
            "personal_volume_points": 0,
            "returned_volume_points": 0,
            "net_personal_volume_points": 0,
            "retail_volume_points": 0,
            "inventory_volume_points": 0,
            "attested_personal_use_points": 0,
            "group_volume_points": 0,
            "active_leg_count": 0,
            "sell_through_bp": 0,
            "qualified_rank_code": None,
            "qualified_rank_order": 0,
            "paid_as_rank_code": None,
            "evaluated_at": None,
        }
    )
    db.qualifications[row["id"]] = row
    return row


def _net_map(period_id):
    return {
        r["consultant_id"]: int(r["net_personal_volume_points"]) for r in rows_of_period(period_id)
    }


def subtree_volume(period_id, consultant_id, nets=None):
    """Own net personal volume plus that of every descendant at unlimited depth."""
    if nets is None:
        nets = _net_map(period_id)
    total = nets.get(consultant_id, 0)
    for child in children_of(consultant_id):
        total += subtree_volume(period_id, child["id"], nets)
    return total


def compute_group_fields(period, plan, consultant_id, nets=None):
    if nets is None:
        nets = _net_map(period["id"])
    group_volume = subtree_volume(period["id"], consultant_id, nets)
    threshold = int(plan["active_leg_min_points"])
    legs = 0
    for child in children_of(consultant_id):
        if child.get("status") == "TERMINATED":
            continue
        if subtree_volume(period["id"], child["id"], nets) >= threshold:
            legs += 1
    return group_volume, legs


def recompute_group_fields_for_period(period):
    plan = db.plans.get(period["compensation_plan_id"])
    if plan is None:
        return
    nets = _net_map(period["id"])
    for row in rows_of_period(period["id"]):
        group_volume, legs = compute_group_fields(period, plan, row["consultant_id"], nets)
        if row["group_volume_points"] != group_volume or row["active_leg_count"] != legs:
            row["group_volume_points"] = group_volume
            row["active_leg_count"] = legs
            touch(row)


def recompute_live_group_fields():
    """Refresh group volume and active legs on every OPEN/REOPENED period only."""
    for period in db.periods.values():
        if period["status"] in ("OPEN", "REOPENED"):
            recompute_group_fields_for_period(period)


def refresh_period_totals(period):
    rows = rows_of_period(period["id"])
    count = len(rows)
    total = sum(int(r["net_personal_volume_points"]) for r in rows)
    if period["qualification_count"] != count or period["total_net_personal_volume_points"] != total:
        period["qualification_count"] = count
        period["total_net_personal_volume_points"] = total
        touch(period)


def stamp_sell_through(row):
    purchased = int(row["inventory_volume_points"])
    credited = min(
        purchased, int(row["retail_volume_points"]) + int(row["attested_personal_use_points"])
    )
    if purchased == 0:
        row["sell_through_bp"] = 10000
    else:
        row["sell_through_bp"] = trunc_div(credited * 10000, purchased)


def evaluate_rank(plan, consultant, row):
    matched = None
    for rung in plan["rank_ladder"]:
        if (
            int(row["net_personal_volume_points"]) >= int(rung["required_pv_points"])
            and int(row["group_volume_points"]) >= int(rung["required_gv_points"])
            and int(row["active_leg_count"]) >= int(rung["required_active_legs"])
        ):
            if matched is None or rung["rank_order"] > matched["rank_order"]:
                matched = rung
    if matched is None:
        row["qualified_rank_code"] = None
        row["qualified_rank_order"] = 0
        row["paid_as_rank_code"] = None
        return
    row["qualified_rank_code"] = matched["rank_code"]
    row["qualified_rank_order"] = matched["rank_order"]
    paid_order = min(int(consultant["rank_order"]), int(matched["rank_order"]))
    paid_rung = planlib.rung_by_order(plan, paid_order)
    row["paid_as_rank_code"] = paid_rung["rank_code"] if paid_rung else None


def lock_period(period, plan):
    """Materialise rows, finalise aggregates, evaluate rank and sell-through."""
    for consultant in db.consultants.values():
        if consultant["compensation_plan_id"] != plan["id"]:
            continue
        if consultant["status"] == "TERMINATED":
            continue
        ensure_row(period, consultant["id"])

    nets = _net_map(period["id"])
    for row in rows_of_period(period["id"]):
        consultant = db.consultants.get(row["consultant_id"])
        row["net_personal_volume_points"] = int(row["personal_volume_points"]) - int(
            row["returned_volume_points"]
        )
        nets[row["consultant_id"]] = int(row["net_personal_volume_points"])

    for row in rows_of_period(period["id"]):
        consultant = db.consultants.get(row["consultant_id"])
        group_volume, legs = compute_group_fields(period, plan, row["consultant_id"], nets)
        row["group_volume_points"] = group_volume
        row["active_leg_count"] = legs
        stamp_sell_through(row)
        if consultant is not None:
            evaluate_rank(plan, consultant, row)
        row["evaluated_at"] = clock_str()
        touch(row)


def latest_closed_row(plan_id, consultant_id):
    """The consultant's row for the most recent CLOSED period, period_start desc."""
    closed = [p for p in db.periods.values() if p["compensation_plan_id"] == plan_id and p["status"] == "CLOSED"]
    if not closed:
        return None
    closed.sort(key=lambda p: (p["_period_start_dt"], p["created_at"], p["_seq"]), reverse=True)
    return row_for(closed[0]["id"], consultant_id)
