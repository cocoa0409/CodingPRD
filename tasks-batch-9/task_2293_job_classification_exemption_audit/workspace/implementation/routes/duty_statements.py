"""Duty documentation (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint

import db
from constants import DISCRETION_LEVELS
from errors import fail
from middleware import body, endpoint
from response import success
from services import derive, lookup, serialize
from services.numbers import dec
from validation import opt_enum, req_bool, req_num, req_str

bp = Blueprint("duty_statements", __name__)


@bp.post("/duty-statements")
@endpoint(["ComplianceAnalyst"])
def create_duty_statement():
    payload = body()
    position_id = req_str(payload, "position_id")
    duty_code = req_str(payload, "duty_code")
    description = req_str(payload, "description")
    claimed_time_pct = req_num(payload, "claimed_time_pct", minimum=0, maximum=100)
    is_exempt_duty = req_bool(payload, "is_exempt_duty")
    discretion_level = opt_enum(
        payload, "discretion_level", DISCRETION_LEVELS, default="NONE"
    )

    # rank 5: foreign key
    position = lookup.position(position_id)

    # rank 13: the claimed shares allocate one person's time
    total = Decimal(0)
    for existing in derive.duty_statements_of(position["id"]):
        total += dec(existing["claimed_time_pct"])
    if total + dec(claimed_time_pct) > Decimal(100):
        fail("ERR_DUTY_TIME_OVERALLOCATED")

    row = db.make_row(
        position_id=position["id"],
        duty_code=duty_code,
        description=description,
        claimed_time_pct=claimed_time_pct,
        is_exempt_duty=is_exempt_duty,
        discretion_level=discretion_level,
    )
    db.duty_statements[row["id"]] = row

    # the position's self-reported picture and the family's score both move
    lookup.touch_position_chain(position, include_project=False)
    return success(serialize.duty_statement(row), 201)
