"""Blackout rules: closed intervals with a mandatory 24-hour buffer."""
from datetime import timedelta

from flask import Blueprint

import constants as K
from auth import enforce_scope, guard
from calc import blackout_hours, blackout_key_rules
from cascades import block_window, recompute_titles, window_order
from common import (
    ALL_READ_ROLES,
    created,
    list_endpoint,
    ok,
    read_endpoint,
    scope_from_body_agreement,
)
from errors import ApiError
from lookup import must, put
from store import D, db, month_key, new_entity, now, touch
from validation import bad, check_body, field

bp = Blueprint("blackouts", __name__)
BASE = "/carriage/blackout-rules"

BUFFER = timedelta(hours=K.BLACKOUT_MIN_SEPARATION_HOURS)


@bp.route(BASE, methods=["POST"])
def create_blackout():
    caller = guard(["RightsAdministrator"])
    scope_from_body_agreement(caller)
    body = check_body(
        {
            "agreement_id": field("id", required=True),
            "territory_code": field("territory", required=True),
            "blackout_start": field("datetime", required=True),
            "blackout_end": field("datetime", required=True),
            "substitution_required": field("bool", default=True),
            "substitute_content_title_id": field("id"),
        }
    )
    if body["blackout_end"] <= body["blackout_start"]:
        bad("blackout_end must be strictly later than blackout_start")

    agreement = must("agreement", body["agreement_id"])
    substitute = None
    if body["substitute_content_title_id"] is not None:
        substitute = must("title", body["substitute_content_title_id"])

    start = body["blackout_start"]
    end = body["blackout_end"]
    peers = blackout_key_rules(agreement["distributor_id"], body["territory_code"])

    # separation first: closed intervals inflated by the 24-hour buffer
    for peer in peers:
        if peer["blackout_start"] - BUFFER <= end and start - BUFFER <= peer[
            "blackout_end"
        ]:
            raise ApiError(
                "ERR_BLACKOUT_SEPARATION_VIOLATION",
                "the proposed rule comes within a day of an existing rule",
            )

    own_hours = blackout_hours(start, end)
    month = month_key(start)
    monthly = own_hours + sum(
        D(peer["blackout_hours"])
        for peer in peers
        if month_key(peer["blackout_start"]) == month
    )
    if monthly > K.MAX_BLACKOUT_HOURS_PER_MONTH:
        raise ApiError(
            "ERR_BLACKOUT_MONTHLY_CAP_EXCEEDED",
            "more than 72 blackout hours in one operator territory in one month",
        )

    # the substitution check runs after both interval checks
    if body["substitution_required"]:
        if substitute is None or substitute["rights_status"] != "OWNED_CLEARED":
            raise ApiError(
                "ERR_SUBSTITUTION_TITLE_REQUIRED",
                "substitution requires a title whose rights are OWNED_CLEARED",
            )

    record = new_entity()
    record.update(
        {
            "agreement_id": agreement["id"],
            "territory_code": body["territory_code"],
            "blackout_start": start,
            "blackout_end": end,
            "substitution_required": body["substitution_required"],
            "substitute_content_title_id": body["substitute_content_title_id"],
            "blackout_hours": own_hours,
            "monthly_blackout_hours": monthly,
            "status": "SCHEDULED",
            "enforced_at": None,
        }
    )
    put("blackout", record)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_blackouts():
    return list_endpoint(
        "blackout",
        ALL_READ_ROLES,
        ["agreement_id", "substitute_content_title_id", "territory_code", "status"],
    )


@bp.route(BASE + "/<rule_id>", methods=["GET"])
def read_blackout(rule_id):
    return read_endpoint("blackout", ALL_READ_ROLES, rule_id)


@bp.route(BASE + "/<rule_id>/lifecycle", methods=["POST"])
def blackout_lifecycle(rule_id):
    caller = guard(["RightsAdministrator"])
    body = check_body(
        {"action": field("enum", required=True, enum=["ENFORCE", "WAIVE"])}
    )
    rule = must("blackout", rule_id)
    agreement = db.agreements.get(rule["agreement_id"])
    enforce_scope(caller, agreement["distributor_id"] if agreement else None)

    if rule["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_BLACKOUT_STATE", "the rule is no longer SCHEDULED"
        )

    if body["action"] == "WAIVE":
        rule["status"] = "WAIVED"
        touch(rule)
        return ok(rule)

    rule["status"] = "ENFORCED"
    rule["enforced_at"] = now()
    touch(rule)

    touched = []
    candidates = [
        w
        for w in db.rights_windows.values()
        if w["agreement_id"] == rule["agreement_id"]
        and w["territory_code"] == rule["territory_code"]
        and w["status"] in ("CLEARED", "ACTIVE")
        and rule["blackout_start"] < w["window_end"]
        and w["window_start"] <= rule["blackout_end"]
    ]
    for window in window_order(candidates):
        touched.append(block_window(window, "BLACKOUT_CONFLICT"))
    recompute_titles(touched)
    return ok(rule)
