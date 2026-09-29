"""Branch endpoints."""
from flask import Blueprint

from core import (
    ALL_ROLES,
    ROLE_MANAGER,
    authenticate,
    base_row,
    bool_filter,
    db,
    paginate,
    pagination,
    respond,
    sorted_rows,
    str_filter,
    touch,
)
from domain import get_branch
from serial import branch_out
from validate import Field, validate

bp = Blueprint("branches", __name__)

CREATE_FIELDS = [
    Field("name", "string", required=True, min_len=1, max_len=120),
    Field("state_code", "string", required=True, pattern=r"^[A-Z]{2}$"),
    Field("competitive_bid_area", "boolean", default=False),
    Field("liquid_oxygen_certified", "boolean", default=False),
    Field("refill_capacity_per_day", "integer", default=4, minimum=0, maximum=40),
    Field(
        "tank_exchange_buffer_minutes", "integer", default=30, minimum=0, maximum=120
    ),
]

PATCH_FIELDS = [
    Field("refill_capacity_per_day", "integer", minimum=0, maximum=40),
    Field("tank_exchange_buffer_minutes", "integer", minimum=0, maximum=120),
    Field("liquid_oxygen_certified", "boolean"),
]


@bp.post("/branches")
def create_branch():
    authenticate((ROLE_MANAGER,))
    data = validate(CREATE_FIELDS)
    row = base_row()
    row.update(
        {
            "name": data["name"],
            "state_code": data["state_code"],
            "competitive_bid_area": data["competitive_bid_area"],
            "liquid_oxygen_certified": data["liquid_oxygen_certified"],
            "refill_capacity_per_day": data["refill_capacity_per_day"],
            "tank_exchange_buffer_minutes": data["tank_exchange_buffer_minutes"],
        }
    )
    db.branches[row["id"]] = row
    return respond(branch_out(row), 201)


@bp.get("/branches")
def list_branches():
    authenticate(ALL_ROLES)
    state_code = str_filter("state_code")
    bid_area = bool_filter("competitive_bid_area")
    liquid = bool_filter("liquid_oxygen_certified")
    limit, offset = pagination()
    rows = sorted_rows(db.branches.values())
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if bid_area is not None:
        rows = [r for r in rows if r["competitive_bid_area"] is bid_area]
    if liquid is not None:
        rows = [r for r in rows if r["liquid_oxygen_certified"] is liquid]
    return paginate(rows, limit, offset, branch_out)


@bp.get("/branches/<branch_id>")
def read_branch(branch_id):
    authenticate(ALL_ROLES)
    return respond(branch_out(get_branch(branch_id)))


@bp.patch("/branches/<branch_id>")
def patch_branch(branch_id):
    authenticate((ROLE_MANAGER,))
    row = get_branch(branch_id)
    data = validate(PATCH_FIELDS)
    for key in (
        "refill_capacity_per_day",
        "tank_exchange_buffer_minutes",
        "liquid_oxygen_certified",
    ):
        if key in data:
            row[key] = data[key]
    touch(row)
    return respond(branch_out(row))
