"""ExtensionRequest lifecycle and the pinned grant clamp (PRD section 3.6)."""

from fractions import Fraction

from flask import g

import calc
import domain
import guards
import repo
import validation as v
from db import clock_date
from errors import ApiError
from middleware import ANY_ROLE, BRAND_MANAGER, FRANCHISEE_OWNER
from routing import route

DECISIONS = ("APPROVE", "DENY", "REQUEST_MORE_JUSTIFICATION")

PENDING_STATUSES = ("SUBMITTED", "NEEDS_MORE_JUSTIFICATION")


def _justification(body, field="business_justification"):
    text = v.get_str(body, field, min_len=1)
    if len(text.strip()) < calc.JUSTIFICATION_MIN_CHARS:
        raise ApiError(
            "ERR_JUSTIFICATION_INSUFFICIENT",
            "business_justification must be at least %d characters"
            % calc.JUSTIFICATION_MIN_CHARS,
        )
    return text


def _pressure_ratio(plan):
    """Step 1 of the grant clamp: read the deadlines as they stand now."""
    horizon = calc.add_days(clock_date(), calc.DEADLINE_PRESSURE_HORIZON_DAYS)
    numerator = 0
    denominator = 0
    for item in domain.plan_items(plan["id"]):
        if item["status"] not in ("REMOVED_BY_DISPUTE", "VOIDED", "ACCEPTED"):
            denominator += 1
        if item["status"] in ("SCOPED", "DEFERRED_PENDING_EXTENSION", "IN_PROGRESS"):
            deadline = calc.parse_date(item["deadline_date"])
            if deadline is not None and deadline <= horizon:
                numerator += 1
    if denominator == 0:
        return Fraction(0)
    return calc.round_half_up(Fraction(numerator, denominator), 4)


@route("/pip/extension-requests", ["POST"], (FRANCHISEE_OWNER,))
def create_extension_request():
    body = v.body_json()
    item = guards.resolve_body_fk(body, "item_id", "items")

    v.require(body, "item_id", "requested_days", "business_justification")
    requested_days = v.get_int(body, "requested_days", minimum=1)
    justification = _justification(body)

    plan = repo.find("plans", item["plan_id"])

    # band 7
    deadline = calc.parse_date(item["deadline_date"]) if item["deadline_date"] else None
    if deadline is not None and clock_date() > deadline:
        raise ApiError(
            "ERR_EXTENSION_AFTER_DEADLINE",
            "the item's deadline has already passed",
        )

    # band 8
    guards.require_owner(domain.property_of_plan(plan))

    # band 9
    for existing in domain.extension_requests_of_item(item["id"]):
        if existing["status"] in PENDING_STATUSES:
            raise ApiError(
                "ERR_EXTENSION_ALREADY_PENDING",
                "the item already has an extension request in flight",
            )

    row = repo.new_row(
        {
            "item_id": item["id"],
            "requested_days": requested_days,
            "business_justification": justification,
            "round_number": 1,
            "status": "SUBMITTED",
            "granted_days": 0,
            "pressure_ratio_at_decision": None,
            "decided_by_user_id": None,
            "decision_note": None,
        }
    )
    repo.insert("extension_requests", row)

    if item["status"] == "SCOPED":
        item["status"] = "DEFERRED_PENDING_EXTENSION"
        domain.recompute_item_overdue(item)
        repo.touch(item)
    return repo.single(row, 201)


@route("/pip/extension-requests/<row_id>", ["GET"], ANY_ROLE)
def get_extension_request(row_id):
    return repo.single(repo.must_find("extension_requests", row_id))


@route("/pip/extension-requests", ["GET"], ANY_ROLE)
def list_extension_requests():
    limit, offset = v.pagination()
    rows = repo.rows("extension_requests")
    for field in ("item_id", "status"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/pip/extension-requests/<row_id>/decide", ["POST"], (BRAND_MANAGER,))
def decide_extension_request(row_id):
    request_row = repo.must_find("extension_requests", row_id)
    body = v.body_json()

    v.require(body, "decision")
    decision = v.get_enum(body, "decision", DECISIONS)
    override_days = v.get_int(body, "granted_days", required=False)
    note = v.get_str(body, "decision_note", required=False, min_len=0)

    if request_row["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_EXTENSION_NOT_DECIDABLE",
            "only a SUBMITTED extension request may be decided",
        )

    item = repo.find("items", request_row["item_id"])
    plan = repo.find("plans", item["plan_id"])
    prop = domain.property_of_plan(plan)

    if decision == "REQUEST_MORE_JUSTIFICATION":
        request_row["status"] = "NEEDS_MORE_JUSTIFICATION"
        request_row["decided_by_user_id"] = g.user_id
        request_row["decision_note"] = note
        repo.touch(request_row)
        return repo.single(request_row)

    ratio = _pressure_ratio(plan)

    if decision == "DENY":
        request_row["status"] = "DENIED"
        request_row["granted_days"] = 0
        request_row["pressure_ratio_at_decision"] = calc.as_number(ratio, 4)
        request_row["decided_by_user_id"] = g.user_id
        request_row["decision_note"] = note
        repo.touch(request_row)

        if item["status"] == "DEFERRED_PENDING_EXTENSION":
            item["status"] = "SCOPED"
            domain.recompute_item_overdue(item)
            repo.touch(item)
        domain.recompute_plan_overdue(plan)
        domain.recompute_property(prop)
        return repo.single(request_row)

    # decision == APPROVE — the pinned six-step clamp
    effective = (
        override_days if override_days is not None else request_row["requested_days"]
    )
    multiplier = (
        calc.DEADLINE_PRESSURE_CLAMP_MULTIPLIER
        if ratio >= calc.DEADLINE_PRESSURE_CLAMP_RATIO
        else Fraction(1)
    )
    category_max = calc.CATEGORY_MAX_EXT_DAYS[item["category"]]
    raw_cap = calc.floor_div(Fraction(category_max) * multiplier)
    remaining = category_max - item["extension_days_granted"]
    granted = min(effective, raw_cap, remaining)

    if granted <= 0:
        raise ApiError(
            "ERR_EXTENSION_CAP_EXHAUSTED",
            "the item's extension budget leaves no days to grant",
        )

    request_row["status"] = "APPROVED" if granted == effective else "APPROVED_PARTIAL"
    request_row["granted_days"] = granted
    request_row["pressure_ratio_at_decision"] = calc.as_number(ratio, 4)
    request_row["decided_by_user_id"] = g.user_id
    request_row["decision_note"] = note
    repo.touch(request_row)

    item["extension_days_granted"] += granted
    if item["status"] == "DEFERRED_PENDING_EXTENSION":
        item["status"] = "SCOPED"
    domain.recompute_item_deadline(item, plan)
    domain.recompute_item_overdue(item)
    repo.touch(item)

    domain.append_ledger(
        plan["id"],
        item["id"],
        "EXTENSION_GRANTED",
        0,
        "extension of %d days granted" % granted,
    )
    domain.recompute_plan_overdue(plan)
    domain.recompute_property(prop)
    return repo.single(request_row)


@route("/pip/extension-requests/<row_id>/resubmit", ["POST"], (FRANCHISEE_OWNER,))
def resubmit_extension_request(row_id):
    request_row = repo.must_find("extension_requests", row_id)
    body = v.body_json()

    v.require(body, "requested_days", "business_justification")
    requested_days = v.get_int(body, "requested_days", minimum=1)
    justification = _justification(body)

    if request_row["status"] != "NEEDS_MORE_JUSTIFICATION":
        raise ApiError(
            "ERR_EXTENSION_NOT_RESUBMITTABLE",
            "only a returned extension request may be resubmitted",
        )

    item = repo.find("items", request_row["item_id"])
    plan = repo.find("plans", item["plan_id"])
    guards.require_owner(domain.property_of_plan(plan))

    if request_row["round_number"] >= calc.MAX_EXTENSION_ROUNDS:
        raise ApiError(
            "ERR_EXTENSION_ROUNDS_EXHAUSTED",
            "the bounded revision loop is exhausted",
        )

    request_row["round_number"] += 1
    request_row["requested_days"] = requested_days
    request_row["business_justification"] = justification
    request_row["status"] = "SUBMITTED"
    repo.touch(request_row)
    return repo.single(request_row)
