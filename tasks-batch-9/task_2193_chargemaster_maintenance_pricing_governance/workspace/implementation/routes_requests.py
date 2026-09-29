"""Department change requests (PRD 3.5)."""

from flask import Blueprint

import validate
from auth import CO, DM, PCA, RIA, SA, require, scope_check, scope_owner_check
from calc import (
    gross_charge_from_price_rule,
    markup_compliance_ratio,
    reprice_item_value,
)
from derive import (
    find,
    item_mutation_cascade,
    recompute_department,
    stale_analyses_for_request,
)
from envelope import list_response, ok
from errors import fail
from routes_items import body_department, body_item, item_batches
from routes_pricing import body_revenue_code
from store import STORE, serialize

bp = Blueprint("routes_requests", __name__)

REQUEST_TYPES = ("NEW_ITEM", "PRICE_CHANGE", "REVENUE_CODE_REMAP", "DEACTIVATION")
OPEN_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "APPROVED")
DECISIONS = {
    "REVIEW": (RIA, ("SUBMITTED",), "UNDER_REVIEW"),
    "REQUEST_CHANGES": (RIA, ("UNDER_REVIEW",), "CHANGES_REQUESTED"),
    "REJECT": (PCA, ("UNDER_REVIEW",), "REJECTED"),
    "WITHDRAW": (DM, ("SUBMITTED", "CHANGES_REQUESTED"), "WITHDRAWN"),
}
REQUEST_READERS = [SA, RIA, PCA, CO, DM]


def effective_cost_basis(request_row, item):
    if request_row["request_type"] in ("NEW_ITEM", "PRICE_CHANGE"):
        proposed = request_row.get("proposed_cost_basis_cents")
        if proposed is not None:
            return proposed
    return item["cost_basis_cents"]


def effective_revenue_code(request_row, item):
    if request_row["request_type"] == "REVENUE_CODE_REMAP":
        proposed = request_row.get("proposed_revenue_code_id")
        if proposed is not None:
            return proposed
    return item["revenue_code_id"]


def refresh_projections(request_row, item, facility):
    cost = effective_cost_basis(request_row, item)
    gross, _conflict, _rule = gross_charge_from_price_rule(
        facility,
        effective_revenue_code(request_row, item),
        cost,
        item["medicare_rate_cents"],
        item["market_p75_cents"],
    )
    request_row["projected_gross_charge_cents"] = gross
    request_row["projected_markup_ratio_bp"] = markup_compliance_ratio(
        facility, item, gross, cost
    )


def sync_department(department, was_open, is_open):
    if was_open != is_open:
        recompute_department(department, bump=True)


@bp.route("/chargemaster/change-requests", methods=["POST"])
def create_change_request():
    user_id, role = require(DM)
    data = validate.body()
    scope_check(user_id, role, data.get("department_id"))
    department = body_department(data)
    body_revenue_code(data, "proposed_revenue_code_id", required=False)
    item = body_item(data, "charge_item_id", required=True)

    request_type = validate.req_enum(data, "request_type", REQUEST_TYPES)
    justification = validate.req_string(data, "justification", 10)
    proposed_cost = validate.opt_int(data, "proposed_cost_basis_cents")
    proposed_revenue_code_id = validate.opt_id(data, "proposed_revenue_code_id")
    proposed_description = validate.opt_string(data, "proposed_description")

    facility = STORE.facilities.get(item["facility_id"])
    request_row = {
        "department_id": department["id"],
        "charge_item_id": item["id"],
        "request_type": request_type,
        "proposed_cost_basis_cents": proposed_cost,
        "proposed_revenue_code_id": proposed_revenue_code_id,
        "proposed_description": proposed_description,
        "justification": justification,
        "status": "SUBMITTED",
        "revision_round": 0,
        "submitted_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "approved_by_user_id": None,
        "pinned_charge_item_version": None,
        "projected_gross_charge_cents": None,
        "projected_markup_ratio_bp": None,
        "decision_note": None,
    }
    refresh_projections(request_row, item, facility)
    STORE.stamp_new(request_row)
    STORE.change_requests[request_row["id"]] = request_row
    recompute_department(department, bump=True)
    return ok(serialize(request_row), 201)


@bp.route("/chargemaster/change-requests", methods=["GET"])
def list_change_requests():
    require(REQUEST_READERS)
    filters = {
        key: validate.query_filter(key)
        for key in (
            "department_id",
            "charge_item_id",
            "proposed_revenue_code_id",
            "status",
            "request_type",
        )
    }

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(STORE.ordered(STORE.change_requests, keep), serialize)


@bp.route("/chargemaster/change-requests/<change_request_id>", methods=["GET"])
def read_change_request(change_request_id):
    require(REQUEST_READERS)
    row = find(
        STORE.change_requests,
        change_request_id,
        "ERR_CHANGE_REQUEST_NOT_FOUND",
        "ChangeRequest",
    )
    return ok(serialize(row))


@bp.route("/chargemaster/change-requests/<change_request_id>/decisions", methods=["POST"])
def decide_change_request(change_request_id):
    user_id, role = require([RIA, PCA, DM])
    data = validate.body()
    raw_decision = data.get("decision")
    if isinstance(raw_decision, str) and raw_decision in DECISIONS:
        if role != DECISIONS[raw_decision][0]:
            fail(
                "ERR_ROLE_NOT_PERMITTED",
                "Role %s may not take decision %s." % (role, raw_decision),
            )
    existing = STORE.change_requests.get(change_request_id)
    if existing is not None and raw_decision == "WITHDRAW":
        scope_check(user_id, role, existing["department_id"])
        scope_owner_check(user_id, role, existing.get("submitted_by_user_id"))

    request_row = find(
        STORE.change_requests,
        change_request_id,
        "ERR_CHANGE_REQUEST_NOT_FOUND",
        "ChangeRequest",
    )
    decision = validate.req_enum(data, "decision", sorted(DECISIONS))
    decision_note = validate.opt_string(data, "decision_note")

    _actor, from_states, to_state = DECISIONS[decision]
    if request_row["status"] not in from_states:
        fail(
            "ERR_INVALID_REQUEST_STATE",
            "Decision %s is not declared out of %s." % (decision, request_row["status"]),
        )

    item = STORE.charge_items.get(request_row["charge_item_id"])
    if decision == "REVIEW":
        if item is not None and item["lifecycle_status"] == "ARCHIVED":
            fail(
                "ERR_INVALID_ITEM_LIFECYCLE_STATE",
                "The target charge item is ARCHIVED.",
            )
        if user_id == request_row.get("submitted_by_user_id"):
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "The reviewer must differ from the submitter.",
            )
    elif decision == "REQUEST_CHANGES":
        if user_id != request_row.get("reviewed_by_user_id"):
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "Only the reviewer of record may request changes.",
            )
    elif decision == "REJECT":
        if user_id == request_row.get("submitted_by_user_id"):
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "The rejecting approver must differ from the submitter.",
            )

    was_open = request_row["status"] in OPEN_STATUSES
    request_row["status"] = to_state
    if decision_note is not None:
        request_row["decision_note"] = decision_note
    if decision == "REVIEW":
        request_row["reviewed_by_user_id"] = user_id
    STORE.touch(request_row)

    if decision == "REJECT" and item is not None:
        if item["price_status"] == "REPRICE_PENDING" and not _other_approved(
            request_row["id"], item["id"]
        ):
            item["price_status"] = "PRICE_STALE"
            STORE.touch(item)

    department = STORE.departments.get(request_row["department_id"])
    if department is not None:
        sync_department(department, was_open, to_state in OPEN_STATUSES)
    return ok(serialize(request_row))


@bp.route("/chargemaster/change-requests/<change_request_id>/approve", methods=["POST"])
def approve_change_request(change_request_id):
    user_id, _role = require(PCA)
    request_row = find(
        STORE.change_requests,
        change_request_id,
        "ERR_CHANGE_REQUEST_NOT_FOUND",
        "ChangeRequest",
    )
    data = validate.body()
    expected = validate.req_int(data, "expected_charge_item_version", 0)
    decision_note = validate.opt_string(data, "decision_note")

    if request_row["status"] != "UNDER_REVIEW":
        fail(
            "ERR_INVALID_REQUEST_STATE",
            "APPROVE is not declared out of %s." % request_row["status"],
        )

    item = STORE.charge_items.get(request_row["charge_item_id"])
    facility = STORE.facilities.get(item["facility_id"])
    request_type = request_row["request_type"]

    if request_type == "REVENUE_CODE_REMAP":
        if facility["chargemaster_posture"] == "RESTRICTED":
            fail("ERR_FACILITY_RESTRICTED", "The facility chargemaster is restricted.")
    if expected != item["version"]:
        fail(
            "ERR_STALE_ITEM_VERSION",
            "expected_charge_item_version %s does not match the live item version %s."
            % (expected, item["version"]),
        )
    if user_id == request_row.get("submitted_by_user_id") or user_id == request_row.get(
        "reviewed_by_user_id"
    ):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approver must differ from the submitter and the reviewer.",
        )
    if request_row.get("reviewed_by_user_id") is None:
        fail("ERR_REQUEST_NOT_REVIEWED", "The request has not been reviewed.")
    if request_type == "REVENUE_CODE_REMAP":
        proposed = STORE.revenue_codes.get(request_row.get("proposed_revenue_code_id"))
        if (
            proposed is None
            or proposed["status"] != "ACTIVE"
            or item["code_type"] not in (proposed.get("allowed_code_types") or [])
        ):
            fail(
                "ERR_REVENUE_CODE_MAPPING_INVALID",
                "The proposed revenue code cannot carry this item.",
            )

    ratio = markup_compliance_ratio(
        facility,
        item,
        request_row.get("projected_gross_charge_cents") or 0,
        effective_cost_basis(request_row, item),
    )
    if ratio > facility["aggregate_markup_limit_bp"]:
        fail(
            "ERR_AGGREGATE_MARKUP_LIMIT",
            "The projected facility markup ratio %d exceeds the limit." % ratio,
        )

    request_row["status"] = "APPROVED"
    request_row["approved_by_user_id"] = user_id
    if decision_note is not None:
        request_row["decision_note"] = decision_note
    pinned = item["version"]
    if request_type in ("PRICE_CHANGE", "NEW_ITEM"):
        item["price_status"] = "REPRICE_PENDING"
        STORE.touch(item)
        pinned = item["version"]
    request_row["pinned_charge_item_version"] = pinned
    STORE.touch(request_row)
    return ok(serialize(request_row))


@bp.route("/chargemaster/change-requests/<change_request_id>/resubmit", methods=["POST"])
def resubmit_change_request(change_request_id):
    user_id, role = require(DM)
    data = validate.body()
    existing = STORE.change_requests.get(change_request_id)
    if existing is not None:
        scope_check(user_id, role, existing["department_id"])
        scope_owner_check(user_id, role, existing.get("submitted_by_user_id"))
    request_row = find(
        STORE.change_requests,
        change_request_id,
        "ERR_CHANGE_REQUEST_NOT_FOUND",
        "ChangeRequest",
    )
    body_revenue_code(data, "proposed_revenue_code_id", required=False)
    justification = validate.req_string(data, "justification", 10)
    proposed_cost = validate.opt_int(data, "proposed_cost_basis_cents")
    proposed_revenue_code_id = validate.opt_id(data, "proposed_revenue_code_id")
    proposed_description = validate.opt_string(data, "proposed_description")

    if request_row["status"] != "CHANGES_REQUESTED":
        fail(
            "ERR_INVALID_REQUEST_STATE",
            "A resubmit is not declared out of %s." % request_row["status"],
        )
    if not request_row["revision_round"] < 3:
        fail(
            "ERR_REVISION_LIMIT_EXCEEDED",
            "revision_round %d has reached the limit." % request_row["revision_round"],
        )

    item = STORE.charge_items.get(request_row["charge_item_id"])
    facility = STORE.facilities.get(item["facility_id"])
    request_row["justification"] = justification
    if proposed_cost is not None:
        request_row["proposed_cost_basis_cents"] = proposed_cost
    if proposed_revenue_code_id is not None:
        request_row["proposed_revenue_code_id"] = proposed_revenue_code_id
    if proposed_description is not None:
        request_row["proposed_description"] = proposed_description
    refresh_projections(request_row, item, facility)
    request_row["revision_round"] = request_row["revision_round"] + 1
    request_row["reviewed_by_user_id"] = None
    request_row["status"] = "SUBMITTED"
    STORE.touch(request_row)
    return ok(serialize(request_row))


@bp.route("/chargemaster/change-requests/<change_request_id>/implement", methods=["POST"])
def implement_change_request(change_request_id):
    require(RIA)
    request_row = find(
        STORE.change_requests,
        change_request_id,
        "ERR_CHANGE_REQUEST_NOT_FOUND",
        "ChangeRequest",
    )
    data = validate.body()
    validate.opt_string(data, "implementation_note")

    item = STORE.charge_items.get(request_row["charge_item_id"])
    facility = STORE.facilities.get(item["facility_id"])
    request_type = request_row["request_type"]

    # PRD 2.9 rank 13: the nine entity-state rules are mutually exclusive and
    # distinguished by target entity; for change-request implementation the rule
    # is ERR_INVALID_ITEM_PRICE_STATE, so it precedes the request-state check.
    if request_type in ("PRICE_CHANGE", "NEW_ITEM"):
        if item["price_status"] != "REPRICE_PENDING":
            fail(
                "ERR_INVALID_ITEM_PRICE_STATE",
                "The target item is not REPRICE_PENDING.",
            )
    if request_row["status"] != "APPROVED":
        fail(
            "ERR_INVALID_REQUEST_STATE",
            "An implementation is not declared out of %s." % request_row["status"],
        )
    if request_type == "DEACTIVATION":
        if item["lifecycle_status"] != "ACTIVE":
            fail(
                "ERR_INVALID_ITEM_LIFECYCLE_STATE",
                "The target item is not ACTIVE.",
            )
    if facility["chargemaster_posture"] == "FROZEN":
        fail("ERR_FACILITY_FROZEN", "The facility chargemaster is frozen.")
    if request_row.get("pinned_charge_item_version") != item["version"]:
        fail(
            "ERR_PINNED_VERSION_STALE",
            "The pinned charge item version no longer matches the live version.",
        )
    if request_type == "DEACTIVATION":
        if item_batches(item["id"], ("INGESTED", "RECONCILING")):
            fail("ERR_ITEM_IN_OPEN_BATCH", "The item appears in an open capture batch.")

    if request_type in ("PRICE_CHANGE", "NEW_ITEM"):
        proposed_cost = request_row.get("proposed_cost_basis_cents")
        if proposed_cost is not None:
            item["cost_basis_cents"] = proposed_cost
        if request_row.get("proposed_description") is not None:
            item["description"] = request_row["proposed_description"]
        gross, conflict, rule = reprice_item_value(facility, item)
        item["prior_gross_charge_cents"] = item["gross_charge_cents"]
        item["gross_charge_cents"] = gross
        item["applied_price_rule_id"] = rule["id"]
        item["price_conflict"] = conflict
        item["price_status"] = "PRICED_CURRENT"
    elif request_type == "REVENUE_CODE_REMAP":
        item["revenue_code_id"] = request_row["proposed_revenue_code_id"]
        item["price_status"] = "PRICE_STALE"
    elif request_type == "DEACTIVATION":
        item["lifecycle_status"] = "INACTIVE"
    STORE.touch(item)

    request_row["status"] = "IMPLEMENTED"
    STORE.touch(request_row)
    item_mutation_cascade(facility)

    touched_departments = set()
    for sibling in STORE.ordered(STORE.change_requests):
        if sibling["id"] == request_row["id"]:
            continue
        if sibling["charge_item_id"] != item["id"]:
            continue
        if sibling["status"] != "APPROVED":
            continue
        if sibling.get("pinned_charge_item_version") == item["version"]:
            continue
        sibling["status"] = "VOIDED_STALE"
        STORE.touch(sibling)
        touched_departments.add(sibling["department_id"])
    for department_id in touched_departments:
        department = STORE.departments.get(department_id)
        if department is not None:
            recompute_department(department, bump=True)

    department = STORE.departments.get(request_row["department_id"])
    if department is not None:
        recompute_department(department, bump=True)
    stale_analyses_for_request(request_row["id"])
    return ok(serialize(request_row))


def _other_approved(request_id, item_id):
    for row in STORE.change_requests.values():
        if row["id"] == request_id:
            continue
        if row["charge_item_id"] != item_id:
            continue
        if row["status"] == "APPROVED":
            return True
    return False
