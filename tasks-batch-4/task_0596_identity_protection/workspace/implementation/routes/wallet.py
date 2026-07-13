from flask import Blueprint

from db import db, now_iso, touch
from errors import ApiError
from middleware import (
    auth,
    body,
    must_exist,
    require_enrollment_active,
    require_subscriber_owner,
)
from response import ok
from serializers import ser
from services import calc
from services.alerts import create_alert

bp = Blueprint("wallet", __name__)

# PRD §3.4: the alert classification depends on what was lost.
LOST_ITEM_ALERT = {
    "SSN_CARD": ("SSN_TRACE", "CRITICAL"),
    "CREDIT_CARD": ("ACCOUNT_TAKEOVER", "HIGH"),
    "DEBIT_CARD": ("ACCOUNT_TAKEOVER", "HIGH"),
}
LOST_ITEM_ALERT_DEFAULT = ("DARK_WEB", "MEDIUM")


@bp.post("/idp/wallet-items/<item_id>/report-lost")
def report_lost(item_id):
    role, user_id = auth("Subscriber", "PlatformAdmin")
    item = must_exist("wallet_items", item_id)
    require_subscriber_owner(role, user_id, item["subscriber_id"])
    subscriber = db.subscribers[item["subscriber_id"]]
    body()

    if item["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Wallet item is not ACTIVE.")
    require_enrollment_active(subscriber)

    item["status"] = "REPORTED_LOST"
    item["reported_lost_at"] = now_iso()
    touch(item)

    alert_type, severity = LOST_ITEM_ALERT.get(item["item_type"], LOST_ITEM_ALERT_DEFAULT)
    create_alert(
        subscriber_id=subscriber["id"],
        family_member_id=None,
        alert_type=alert_type,
        severity=severity,
        source_detail="LOST_WALLET_ITEM:" + item["id"],
    )

    # Freeze assist: a lost SSN card freezes every bureau file not already cycling.
    if item["item_type"] == "SSN_CARD":
        for profile in calc.profiles_of(subscriber["id"]):
            if profile["freeze_status"] == "UNFROZEN":
                profile["freeze_status"] = "FREEZE_PENDING"
                touch(profile)

    calc.recompute_risk(subscriber)
    touch(subscriber)
    return ok(ser(item))
