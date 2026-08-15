"""ReasonCodeRule endpoints (PRD 3.2) — immutable configuration."""

from flask import Blueprint, request

from db import db
from errors import ApiError
from records import new_rule
from response import ok_object
from routes.common import ALL_ROLES, authenticate, json_body, list_response
from serializers import serialize_rule
from util import Body, EVIDENCE_TYPES, NETWORKS, RULE_CATEGORIES, filter_enum

bp = Blueprint("rules", __name__)


def _windows_overlap(f1, t1, f2, t2):
    """Half-open [from, to) windows; None 'to' is open-ended; adjacency allowed."""
    left_open_ended = t1 is None
    right_open_ended = t2 is None
    if not left_open_ended and f2 >= t1:
        return False
    if not right_open_ended and f1 >= t2:
        return False
    return True


@bp.post("/acquirer/reason-code-rules")
def create_rule():
    authenticate(("AcquirerOps",))
    b = Body(json_body())
    network = b.req_enum("network", NETWORKS)
    reason_code = b.req_str("reason_code")
    category = b.req_enum("category", RULE_CATEGORIES)
    required_evidence_types = b.req_enum_list("required_evidence_types", EVIDENCE_TYPES)
    merchant_response_days = b.req_int("merchant_response_days", minv=1)
    representment_days = b.req_int("representment_days", minv=1)
    chargeback_fee_cents = b.req_int("chargeback_fee_cents", minv=0)
    effective_from = b.req_dt("effective_from")
    effective_to = b.opt_dt("effective_to")

    # Priority 7: half-open effective windows per (network, reason_code) must not overlap.
    if network is not None and reason_code is not None and effective_from is not None:
        for r in db.rules.values():
            if r["network"] == network and r["reason_code"] == reason_code:
                if _windows_overlap(effective_from, effective_to, r["effective_from"], r["effective_to"]):
                    raise ApiError(409, "ERR_RULE_WINDOW_OVERLAP",
                                   "Effective window overlaps an existing rule for (%s, %s)" % (network, reason_code))

    # Priority 11: payload shape.
    if effective_from is not None and effective_to is not None and effective_to <= effective_from:
        b._fail(("ERR_INVALID_REQUEST", 400), "effective_to must be after effective_from")
    b.raise_pending()

    rule = new_rule(network, reason_code, category, required_evidence_types or [],
                    merchant_response_days, representment_days, chargeback_fee_cents,
                    effective_from, effective_to)
    db.rules[rule["id"]] = rule
    return ok_object(serialize_rule(rule), status=201)


@bp.get("/acquirer/reason-code-rules")
def list_rules():
    authenticate(ALL_ROLES)
    network = filter_enum(request.args, "network", NETWORKS)
    reason_code = request.args.get("reason_code")
    records = list(db.rules.values())
    if network is not None:
        records = [r for r in records if r["network"] == network]
    if reason_code is not None:
        records = [r for r in records if r["reason_code"] == reason_code]
    return list_response(records, serialize_rule)


def find_governing_rule(network, reason_code, at):
    """The rule whose half-open window [effective_from, effective_to) covers `at`."""
    for r in db.rules.values():
        if r["network"] != network or r["reason_code"] != reason_code:
            continue
        if r["effective_from"] <= at and (r["effective_to"] is None or at < r["effective_to"]):
            return r
    return None
