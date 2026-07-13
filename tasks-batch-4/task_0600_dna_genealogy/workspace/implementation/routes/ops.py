"""Ops surface: the purge checkpoint and the logical clock (PRD §2.4, §3.10)."""
from flask import Blueprint

import db
import services as S
from auth import endpoint
from errors import ApiError
from response import ok
from routes.common import body

bp = Blueprint("ops", __name__)


def _purge_customer(customer):
    customer["account_status"] = "PURGED"
    customer["dna_status"] = "PURGED"
    db.touch(customer)

    for grant in db.db.grants.values():
        if grant["customer_id"] == customer["id"] and grant["status"] == "ACTIVE":
            grant["status"] = "WITHDRAWN"
            grant["withdrawn_at"] = db.now()
            db.touch(grant)

    for report in db.db.reports.values():
        if report["customer_id"] == customer["id"] and report["status"] in ("DRAFT", "PUBLISHED"):
            report["status"] = "REVOKED"
            db.touch(report)

    for match in list(db.db.matches.values()):
        if customer["id"] not in (match["customer_a_id"], match["customer_b_id"]):
            continue
        if match["status"] == "PURGED":
            continue
        was_active = match["status"] == "ACTIVE"
        match["status"] = "PURGED"
        db.touch(match)
        if was_active:
            for side_id in (match["customer_a_id"], match["customer_b_id"]):
                side = db.db.customers.get(side_id)
                if side:
                    side["visible_match_count"] = max(0, side["visible_match_count"] - 1)
                    db.touch(side)
        S.withdraw_hints_of_match(match)

    if customer["visible_match_count"] != 0:
        customer["visible_match_count"] = 0
        db.touch(customer)


@bp.post("/dna/_ops/purge-run")
@endpoint(["PlatformAdmin"])
def purge_run():
    now = db.now()
    eligible = [
        r
        for r in db.db.data_requests.values()
        if r["status"] == "SCHEDULED"
        and r["scheduled_purge_at"] is not None
        and r["scheduled_purge_at"] <= now
    ]

    def sort_key(record):
        customer = db.db.customers.get(record["customer_id"])
        return (record["created_at"], customer["email"] if customer else "", record["_seq"])

    eligible.sort(key=sort_key)

    completed_request_ids = []
    purged_count = 0
    for record in eligible:
        record["status"] = "COMPLETED"
        db.touch(record)
        completed_request_ids.append(record["id"])

        customer = db.db.customers.get(record["customer_id"])
        if customer and customer["account_status"] != "PURGED":
            _purge_customer(customer)
            purged_count += 1

    return ok({"purged_count": purged_count, "completed_request_ids": completed_request_ids})


@bp.post("/dna/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_clock():
    payload = body()
    S.require_fields(payload, ["to_iso8601"])
    target = db.parse_dt(payload["to_iso8601"])
    if target is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    db.db.clock = target
    return ok({"current_utc": db.iso(target)})
