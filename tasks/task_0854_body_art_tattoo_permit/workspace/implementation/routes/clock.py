"""Logical-clock control and the two-step sweep — PRD §2.5, §3.3, §3.4."""

from flask import Blueprint

import config
import domain
import store
import validate as V
from auth import authenticate
from envelope import send, watch
from errors import ApiError
from util import render_ts

bp = Blueprint("clock", __name__)


@bp.post("/body-art/_clock/set_current_utc")
def set_current_utc():
    authenticate(config.ROLES)
    data = V.body()
    target = V.req_datetime(data, "to_iso8601")
    if target <= store.now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")

    store.set_now(target)

    expired_establishment_ids = []
    escalated_violation_ids = []

    # sweep step 1 — permit expiry, Establishment.created_at ASC
    for est in store.sorted_rows(store.establishments):
        if est["permit_status"] != "ACTIVE":
            continue
        expires = est["permit_expires_on"]
        if expires is not None and expires <= target:
            domain.expire_establishment(est)
            expired_establishment_ids.append(est["id"])

    # sweep step 2 — abatement escalation, Violation.created_at ASC
    for violation in store.sorted_rows(store.violations):
        if violation["status"] != "ISSUED":
            continue
        due = violation["abatement_due_at"]
        if due is not None and due <= target:
            watch(violation)
            violation["status"] = "ESCALATED"
            escalated_violation_ids.append(violation["id"])
            inspection = store.inspections.get(violation["inspection_id"])
            est = (
                store.establishments.get(inspection["establishment_id"])
                if inspection is not None
                else None
            )
            if est is not None:
                domain.recompute_risk_and_posture(est)

    # the trailing sterilization window has moved: refresh every premises
    # (PRD §3.5 — yesterday's compliance can lapse without anybody filing).
    for est in store.sorted_rows(store.establishments):
        domain.recompute_risk_and_posture(est)

    payload = {
        "current_utc": render_ts(target),
        "expired_establishment_ids": expired_establishment_ids,
        "escalated_violation_ids": escalated_violation_ids,
    }
    return send(payload, 200)
