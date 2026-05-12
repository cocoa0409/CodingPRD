"""Fund-level helpers."""
import re
import db
from db import funds, orders, stamp_update
from errors import err
from services import audit
from services.calculations import (
    confirmation_cycle_days_for_type,
    validate_fee_tiers,
)


VALID_FUND_TYPES = {"EQUITY", "BOND", "HYBRID", "MONEY_MARKET", "QDII"}
VALID_RISK_RATING = {"R1", "R2", "R3", "R4", "R5"}
FUND_CODE_RE = re.compile(r"^[0-9]{6}$")


def find_fund_by_code(code: str):
    for f in funds.values():
        if f["fund_code"] == code:
            return f
    return None


def cascade_suspend(fund: dict, actor_id: str, actor_role: str):
    """When a fund moves ON_SHELF -> SUSPENDED: every Order with status SUBMITTED for this fund
    transitions to REJECTED with rejection_error_id ERR_FUND_SUSPENDED."""
    for o in orders.values():
        if o["fund_id"] == fund["id"] and o["status"] == "SUBMITTED":
            prev = o["status"]
            o["status"] = "REJECTED"
            o["rejection_error_id"] = "ERR_FUND_SUSPENDED"
            stamp_update(o)
            audit.write(actor_id, actor_role, "ORDER_STATUS_CHANGE", "Order", o["id"],
                        prev, "REJECTED", {"reason": "fund_suspended"})


def stamp_confirmation_cycle(fund: dict):
    fund["confirmation_cycle_days"] = confirmation_cycle_days_for_type(fund["fund_type"])
