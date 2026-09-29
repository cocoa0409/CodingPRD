"""Logical clock, terminals and shipper accounts."""
from flask import Blueprint

import auth
import clock
import db
import response
import serialize
import validation
from constants import BASE_DISPUTE_WINDOW_DAYS, BILLING_POSTURES
from errors import fail
from util import rhu

bp = Blueprint("core", __name__)

POSTURE_MOVES = {
    ("OPEN", "CREDIT_HOLD"),
    ("CREDIT_HOLD", "OPEN"),
    ("OPEN", "CLOSED"),
    ("CREDIT_HOLD", "CLOSED"),
}


# ---------------------------------------------------------------------------
# logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authenticate(("PricingAnalyst",))
    body = validation.body()
    moment = validation.req_datetime(body, "to_iso8601")
    clock.set_now(moment)
    return response.ok({"current_utc": clock.iso(clock.now())})


# ---------------------------------------------------------------------------
# terminals (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.post("/ltl/terminals")
def create_terminal():
    auth.authenticate(("PricingAnalyst",))
    body = validation.body()
    code = validation.req_str(body, "code", min_len=3, max_len=10)
    name = validation.req_str(body, "name")
    interval = validation.opt_int(body, "calibration_interval_captures", default=250, minimum=1)

    for row in db.all_rows("terminals"):
        if row["code"] == code:
            fail("ERR_INVALID_REQUEST", "Terminal code %s already exists." % code)

    row = db.insert(
        "terminals",
        {
            "code": code,
            "name": name,
            "calibration_interval_captures": interval,
            "captures_since_calibration": 0,
            "dimensioner_status": "CALIBRATED",
            "last_capture_at": None,
        },
    )
    return response.created(serialize.terminal(row))


@bp.get("/ltl/terminals/<terminal_id>")
def read_terminal(terminal_id):
    auth.authenticate(("PricingAnalyst", "TerminalOperator", "ClassificationAuditor"))
    row = validation.path_row("terminals", terminal_id, "ERR_TERMINAL_NOT_FOUND")
    return response.ok(serialize.terminal(row))


# ---------------------------------------------------------------------------
# customers (PRD 3.2, 3.8)
# ---------------------------------------------------------------------------
@bp.post("/ltl/customers")
def create_customer():
    auth.authenticate(("PricingAnalyst",))
    body = validation.body()
    account_code = validation.req_str(body, "account_code")
    name = validation.req_str(body, "name")
    interval = validation.opt_int(body, "education_strike_interval", default=3, minimum=1)

    for row in db.all_rows("customers"):
        if row["account_code"] == account_code:
            fail("ERR_INVALID_REQUEST", "Account code %s already exists." % account_code)

    row = db.insert(
        "customers",
        {
            "account_code": account_code,
            "name": name,
            "billing_posture": "OPEN",
            "education_status": "NONE",
            "education_strike_interval": interval,
            "education_threshold_strikes": interval,
            "education_required_at": None,
            "offender_strike_count": 0,
            "liability_index_rolling": rhu(0, 2),
            "liability_index_lifetime": rhu(0, 2),
            "offender_tier": "TIER_0",
            "dispute_window_days": BASE_DISPUTE_WINDOW_DAYS,
            "active_program_type": None,
        },
    )
    return response.created(serialize.customer(row))


@bp.get("/ltl/customers/<customer_id>")
def read_customer(customer_id):
    auth.authenticate(
        ("PricingAnalyst", "ClassificationAuditor", "DisputeReviewer", "Shipper")
    )
    row = validation.path_row("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    auth.require_shipper_owner(row["id"])
    return response.ok(serialize.customer(row))


@bp.post("/ltl/customers/<customer_id>/posture")
def move_posture(customer_id):
    auth.authenticate(("PricingAnalyst",))
    row = validation.path_row("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    body = validation.body()
    posture = validation.req_enum(body, "billing_posture", BILLING_POSTURES)
    expected = validation.req_int(body, "expected_customer_version")

    if expected != int(row["version"]):
        fail(
            "ERR_STALE_CUSTOMER_VERSION",
            "Customer version is %s, not %s." % (row["version"], expected),
        )

    if (row["billing_posture"], posture) not in POSTURE_MOVES:
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Cannot move billing_posture %s -> %s." % (row["billing_posture"], posture),
        )

    row["billing_posture"] = posture
    db.touch(row)
    return response.ok(serialize.customer(row))


@bp.post("/ltl/customers/<customer_id>/education/complete")
def complete_education(customer_id):
    auth.authenticate(("PricingAnalyst",))
    row = validation.path_row("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    if row["education_status"] != "REQUIRED":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "education_status is %s, not REQUIRED." % row["education_status"],
        )
    row["education_status"] = "COMPLETED"
    row["education_threshold_strikes"] = int(row["offender_strike_count"]) + int(
        row["education_strike_interval"]
    )
    db.touch(row)
    return response.ok(serialize.customer(row))
