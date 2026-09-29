"""Charge items: creation, the two state dimensions, repricing (PRD 3.3, 3.4)."""

from decimal import Decimal, InvalidOperation

from flask import Blueprint

import validate
from auth import ALL_ROLES, CO, PCA, RIA, require
from calc import (
    SIMILARITY_THRESHOLD,
    duplicate_candidates,
    duplicate_similarity_score,
    markup_compliance_ratio,
    reprice_item_value,
)
from derive import (
    find,
    item_mutation_cascade,
    recompute_facility,
    stale_analyses_for_item,
)
from envelope import list_response, ok
from errors import fail
from routes_facilities import CODE_TYPES, body_facility
from routes_pricing import body_revenue_code
from store import STORE, fmt_iso, serialize

bp = Blueprint("routes_items", __name__)

LIFECYCLE_ACTIONS = {
    "SUBMIT_FOR_REVIEW": (RIA, "DRAFT", "PENDING_REVIEW"),
    "RETURN_TO_DRAFT": (RIA, "PENDING_REVIEW", "DRAFT"),
    "APPROVE": (PCA, "PENDING_REVIEW", "APPROVED"),
    "ACTIVATE": (PCA, "APPROVED", "ACTIVE"),
    "DEACTIVATE": (RIA, "ACTIVE", "INACTIVE"),
    "MARK_DUPLICATE": (RIA, "ACTIVE", "INACTIVE"),
    "REACTIVATE": (PCA, "INACTIVE", "ACTIVE"),
    "ARCHIVE": (RIA, "INACTIVE", "ARCHIVED"),
}


def body_department(data, field="department_id", required=True):
    """Rank 10 — body FK resolution for department_id."""
    if field in data and isinstance(data.get(field), str):
        row = STORE.departments.get(data[field])
        if row is None:
            fail(
                "ERR_REFERENCED_RESOURCE_NOT_FOUND",
                "Department %s does not exist." % data[field],
            )
        return row
    if required:
        validate.req_id(data, field)
    return None


def body_item(data, field, required=False):
    if field in data and isinstance(data.get(field), str):
        row = STORE.charge_items.get(data[field])
        if row is None:
            fail(
                "ERR_REFERENCED_RESOURCE_NOT_FOUND",
                "ChargeItem %s does not exist." % data[field],
            )
        return row
    if required:
        validate.req_id(data, field)
    return None


def mapping_legal(item_code_type, item_code_value, revenue_code):
    if item_code_type not in (revenue_code.get("allowed_code_types") or []):
        return False
    if revenue_code.get("requires_hcpcs"):
        if item_code_type not in ("CPT", "HCPCS"):
            return False
        if item_code_value is None:
            return False
    return True


def check_mapping(item_code_type, item_code_value, revenue_code):
    if not mapping_legal(item_code_type, item_code_value, revenue_code):
        fail(
            "ERR_REVENUE_CODE_MAPPING_INVALID",
            "The revenue-code mapping is not legal for this item.",
        )


def check_department_whitelist(department, revenue_code):
    allowed = department.get("allowed_revenue_code_values") or []
    if allowed and revenue_code["code"] not in allowed:
        fail(
            "ERR_DEPARTMENT_REVENUE_CODE_NOT_ALLOWED",
            "The department may not map items to revenue code %s." % revenue_code["code"],
        )


def item_batches(item_id, statuses):
    for line in STORE.captured_charges.values():
        if line.get("charge_item_id") != item_id:
            continue
        batch = STORE.batches.get(line["batch_id"])
        if batch is None:
            continue
        if statuses is None or batch["status"] in statuses:
            return True
    return False


def item_in_unclosed_batch(item_id):
    for line in STORE.captured_charges.values():
        if line.get("charge_item_id") != item_id:
            continue
        batch = STORE.batches.get(line["batch_id"])
        if batch is not None and batch["status"] != "CLOSED":
            return True
    return False


def item_has_open_request(item_id):
    for request in STORE.change_requests.values():
        if request["charge_item_id"] != item_id:
            continue
        if request["status"] in (
            "SUBMITTED",
            "UNDER_REVIEW",
            "CHANGES_REQUESTED",
            "APPROVED",
        ):
            return True
    return False


def item_pending_code_update(item_id):
    for entry in STORE.code_update_entries.values():
        if entry.get("target_charge_item_id") != item_id:
            continue
        if entry["status"] != "MAPPED":
            continue
        cycle = STORE.code_update_cycles.get(entry["cycle_id"])
        if cycle is not None and cycle["status"] == "CROSSWALK_APPROVED":
            return True
    return False


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------
@bp.route("/chargemaster/charge-items", methods=["POST"])
def create_charge_item():
    require(RIA)
    data = validate.body()
    facility = body_facility(data)
    department = body_department(data)
    revenue_code = body_revenue_code(data)
    companion = body_item(data, "companion_required_item_id")

    cdm_number = validate.req_string(data, "cdm_number")
    description = validate.req_string(data, "description")
    code_type = validate.req_enum(data, "code_type", CODE_TYPES)
    cost_basis = validate.req_int(data, "cost_basis_cents")
    medicare_rate = validate.req_int(data, "medicare_rate_cents")
    market_p75 = validate.req_int(data, "market_p75_cents")
    effective_from = validate.req_dt(data, "effective_from")
    code_value = validate.opt_string(data, "code_value")
    window_hours = validate.opt_int(data, "companion_window_hours", 24)
    if code_value is None and code_type in ("CPT", "HCPCS"):
        fail("ERR_VALIDATION", "code_value is required when code_type is CPT or HCPCS.")

    if facility["chargemaster_posture"] == "FROZEN":
        fail("ERR_FACILITY_FROZEN", "The facility chargemaster is frozen.")
    if facility["chargemaster_posture"] == "RESTRICTED" and code_type in ("CPT", "HCPCS"):
        fail("ERR_FACILITY_RESTRICTED", "The facility chargemaster is restricted.")

    check_mapping(code_type, code_value, revenue_code)
    check_department_whitelist(department, revenue_code)

    if companion is not None:
        if (
            companion["facility_id"] != facility["id"]
            or companion["lifecycle_status"] == "ARCHIVED"
        ):
            fail("ERR_COMPANION_ITEM_INVALID", "The companion item is not usable.")

    if effective_from < STORE.now:
        fail("ERR_EFFECTIVE_DATE_IN_PAST", "effective_from may not be back-dated.")

    for row in STORE.charge_items.values():
        if row["facility_id"] == facility["id"] and row["cdm_number"] == cdm_number:
            fail("ERR_DUPLICATE_CDM_NUMBER", "cdm_number is already used in this facility.")

    item = {
        "facility_id": facility["id"],
        "department_id": department["id"],
        "revenue_code_id": revenue_code["id"],
        "duplicate_of_item_id": None,
        "companion_required_item_id": companion["id"] if companion else None,
        "companion_window_hours": window_hours,
        "cdm_number": cdm_number,
        "description": description,
        "code_type": code_type,
        "code_value": code_value,
        "cost_basis_cents": cost_basis,
        "medicare_rate_cents": medicare_rate,
        "market_p75_cents": market_p75,
        "gross_charge_cents": 0,
        "prior_gross_charge_cents": 0,
        "applied_price_rule_id": None,
        "price_conflict": False,
        "lifecycle_status": "DRAFT",
        "price_status": "PRICE_STALE",
        "effective_from": fmt_iso(effective_from),
        "approved_by_user_id": None,
        "last_code_cycle_id": None,
        "_effective_from": effective_from,
    }
    STORE.stamp_new(item)
    STORE.charge_items[item["id"]] = item
    return ok(serialize(item), 201)


@bp.route("/chargemaster/charge-items", methods=["GET"])
def list_charge_items():
    require(ALL_ROLES)
    filters = {
        key: validate.query_filter(key)
        for key in (
            "facility_id",
            "department_id",
            "revenue_code_id",
            "duplicate_of_item_id",
            "companion_required_item_id",
            "applied_price_rule_id",
            "last_code_cycle_id",
            "lifecycle_status",
            "price_status",
            "code_value",
            "cdm_number",
        )
    }

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(STORE.ordered(STORE.charge_items, keep), serialize)


@bp.route("/chargemaster/charge-items/<charge_item_id>", methods=["GET"])
def read_charge_item(charge_item_id):
    require(ALL_ROLES)
    item = find(
        STORE.charge_items, charge_item_id, "ERR_CHARGE_ITEM_NOT_FOUND", "ChargeItem"
    )
    return ok(serialize(item))


@bp.route(
    "/chargemaster/charge-items/<charge_item_id>/duplicate-candidates", methods=["GET"]
)
def read_duplicate_candidates(charge_item_id):
    require([RIA, PCA, CO])
    item = find(
        STORE.charge_items, charge_item_id, "ERR_CHARGE_ITEM_NOT_FOUND", "ChargeItem"
    )
    facility = STORE.facilities.get(item["facility_id"])
    raw_min = validate.query_filter("min_score")
    minimum = None
    if raw_min is not None:
        try:
            minimum = Decimal(raw_min)
        except (InvalidOperation, ValueError):
            fail("ERR_VALIDATION", "min_score must be a decimal number.")
    pairs = duplicate_candidates(facility, item)
    if minimum is not None:
        pairs = [pair for pair in pairs if pair[1] >= minimum]
    return list_response([pair[0] for pair in pairs], serialize)


# ---------------------------------------------------------------------------
# Reprice
# ---------------------------------------------------------------------------
@bp.route("/chargemaster/charge-items/<charge_item_id>/reprice", methods=["POST"])
def reprice_charge_item(charge_item_id):
    require(RIA)
    item = find(
        STORE.charge_items, charge_item_id, "ERR_CHARGE_ITEM_NOT_FOUND", "ChargeItem"
    )
    facility = STORE.facilities.get(item["facility_id"])
    if item["lifecycle_status"] == "ARCHIVED":
        fail(
            "ERR_INVALID_ITEM_LIFECYCLE_STATE",
            "An ARCHIVED item cannot be repriced.",
        )
    if facility["chargemaster_posture"] == "FROZEN":
        fail("ERR_FACILITY_FROZEN", "The facility chargemaster is frozen.")
    if item["price_status"] == "PRICE_FROZEN":
        fail("ERR_ITEM_PRICE_FROZEN", "The item price is frozen for publication.")

    gross, conflict, rule = reprice_item_value(facility, item)
    item["prior_gross_charge_cents"] = item["gross_charge_cents"]
    item["gross_charge_cents"] = gross
    item["applied_price_rule_id"] = rule["id"]
    item["price_conflict"] = conflict
    item["price_status"] = "PRICED_CURRENT"
    STORE.touch(item)
    if item["lifecycle_status"] == "ACTIVE":
        item_mutation_cascade(facility)
    stale_analyses_for_item(item["id"])
    return ok(serialize(item))


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@bp.route("/chargemaster/charge-items/<charge_item_id>/lifecycle", methods=["POST"])
def charge_item_lifecycle(charge_item_id):
    user_id, role = require([RIA, PCA])
    data = validate.body()
    raw_action = data.get("action")
    if isinstance(raw_action, str) and raw_action in LIFECYCLE_ACTIONS:
        if role != LIFECYCLE_ACTIONS[raw_action][0]:
            fail(
                "ERR_ROLE_NOT_PERMITTED",
                "Role %s may not perform action %s." % (role, raw_action),
            )

    item = find(
        STORE.charge_items, charge_item_id, "ERR_CHARGE_ITEM_NOT_FOUND", "ChargeItem"
    )
    target_item = body_item(data, "duplicate_of_item_id")

    action = validate.req_enum(data, "action", sorted(LIFECYCLE_ACTIONS))
    validate.opt_string(data, "note")
    if action == "MARK_DUPLICATE" and target_item is None:
        validate.req_id(data, "duplicate_of_item_id")

    from_state, to_state = LIFECYCLE_ACTIONS[action][1], LIFECYCLE_ACTIONS[action][2]
    if item["lifecycle_status"] != from_state:
        fail(
            "ERR_INVALID_ITEM_LIFECYCLE_STATE",
            "Action %s is not declared out of %s." % (action, item["lifecycle_status"]),
        )

    facility = STORE.facilities.get(item["facility_id"])
    if facility["chargemaster_posture"] == "FROZEN":
        fail("ERR_FACILITY_FROZEN", "The facility chargemaster is frozen.")

    revenue_code = STORE.revenue_codes.get(item["revenue_code_id"])
    department = STORE.departments.get(item["department_id"])

    if action == "SUBMIT_FOR_REVIEW":
        check_mapping(item["code_type"], item.get("code_value"), revenue_code)
        check_department_whitelist(department, revenue_code)
    elif action == "APPROVE":
        if item["price_status"] != "PRICED_CURRENT":
            fail("ERR_ITEM_PRICE_NOT_CURRENT", "The pricing dimension is not settled.")
        ratio = markup_compliance_ratio(
            facility, item, item["gross_charge_cents"], item["cost_basis_cents"]
        )
        if ratio > facility["aggregate_markup_limit_bp"]:
            fail(
                "ERR_AGGREGATE_MARKUP_LIMIT",
                "The projected facility markup ratio %d exceeds the limit." % ratio,
            )
    elif action == "ACTIVATE":
        if revenue_code["status"] != "ACTIVE":
            fail("ERR_REVENUE_CODE_RETIRED", "The mapped revenue code is retired.")
        if item["_effective_from"] > STORE.now:
            fail("ERR_ITEM_NOT_YET_EFFECTIVE", "The item is not yet effective.")
        if item_pending_code_update(item["id"]):
            fail(
                "ERR_ITEM_PENDING_CODE_UPDATE",
                "An approved crosswalk is pending for this item.",
            )
    elif action == "DEACTIVATE":
        if item_batches(item["id"], ("INGESTED", "RECONCILING")):
            fail("ERR_ITEM_IN_OPEN_BATCH", "The item appears in an open capture batch.")
    elif action == "MARK_DUPLICATE":
        if (
            target_item["id"] == item["id"]
            or target_item["facility_id"] != item["facility_id"]
            or target_item["lifecycle_status"] != "ACTIVE"
            or target_item.get("duplicate_of_item_id") is not None
        ):
            fail("ERR_DUPLICATE_TARGET_INVALID", "The duplicate target is not usable.")
        if item_batches(item["id"], ("INGESTED", "RECONCILING")):
            fail("ERR_ITEM_IN_OPEN_BATCH", "The item appears in an open capture batch.")
        score = duplicate_similarity_score(
            facility["duplicate_detection_mode"], item, target_item
        )
        if score < SIMILARITY_THRESHOLD:
            fail(
                "ERR_DUPLICATE_SIMILARITY_TOO_LOW",
                "The duplicate similarity score %s is below the threshold." % score,
            )
    elif action == "REACTIVATE":
        if revenue_code["status"] != "ACTIVE":
            fail("ERR_REVENUE_CODE_RETIRED", "The mapped revenue code is retired.")
        if item["price_status"] != "PRICED_CURRENT":
            fail("ERR_ITEM_PRICE_NOT_CURRENT", "The pricing dimension is not settled.")
        if item.get("duplicate_of_item_id") is not None:
            fail(
                "ERR_ITEM_RETIRED_AS_DUPLICATE",
                "An item retired as a duplicate cannot be reactivated.",
            )
    elif action == "ARCHIVE":
        if item_in_unclosed_batch(item["id"]):
            fail(
                "ERR_ITEM_IN_OPEN_BATCH",
                "The item appears in a capture batch that is not CLOSED.",
            )
        if item_has_open_request(item["id"]):
            fail("ERR_ITEM_HAS_OPEN_REQUEST", "An open change request targets this item.")

    item["lifecycle_status"] = to_state
    if action == "APPROVE":
        item["approved_by_user_id"] = user_id
    if action == "MARK_DUPLICATE":
        item["duplicate_of_item_id"] = target_item["id"]
    STORE.touch(item)
    # PRD 3.6: COMPUTED -> STALE fires whenever the target item is mutated.
    stale_analyses_for_item(item["id"])

    if action in ("ACTIVATE", "DEACTIVATE", "MARK_DUPLICATE", "REACTIVATE"):
        item_mutation_cascade(facility)
    elif action == "ARCHIVE":
        archive_entry_cascade(item)
    return ok(serialize(item))


def archive_entry_cascade(item):
    from derive import recompute_cycle_counters

    touched_cycles = set()
    for entry in STORE.ordered(STORE.code_update_entries):
        if entry.get("target_charge_item_id") != item["id"]:
            continue
        if entry["status"] != "MAPPED":
            continue
        cycle = STORE.code_update_cycles.get(entry["cycle_id"])
        if cycle is None or cycle["status"] not in (
            "MAPPING",
            "CROSSWALK_APPROVED",
            "CANCELLED",
        ):
            continue
        entry["status"] = "DEFERRED"
        entry["defer_reason"] = "TARGET_ARCHIVED"
        entry["target_charge_item_id"] = None
        STORE.touch(entry)
        touched_cycles.add(entry["cycle_id"])
    for cycle_id in touched_cycles:
        cycle = STORE.code_update_cycles.get(cycle_id)
        if cycle is not None:
            recompute_cycle_counters(cycle, bump=False)
