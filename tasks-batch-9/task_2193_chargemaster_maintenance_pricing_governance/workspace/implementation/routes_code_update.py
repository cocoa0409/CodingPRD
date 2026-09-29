"""The annual CPT/HCPCS code update cycle (PRD 3.7)."""

from flask import Blueprint

import validate
from auth import CO, PCA, RIA, SA, require
from calc import code_update_crosswalk_price_carry
from derive import (
    cycle_entries,
    find,
    item_mutation_cascade,
    recompute_cycle_counters,
    recompute_facility,
)
from envelope import list_response, ok
from errors import fail
from routes_facilities import body_facility
from store import STORE, fmt_iso, serialize

bp = Blueprint("routes_code_update", __name__)

CODE_SETS = ("CPT", "HCPCS")
ENTRY_ACTIONS = ("ADD", "DELETE", "REVISE", "CROSSWALK")
CYCLE_ACTIONS = {
    "START_MAPPING": (RIA, "LOADED", "MAPPING"),
    "APPROVE_CROSSWALK": (PCA, "MAPPING", "CROSSWALK_APPROVED"),
    "ACTIVATE": (CO, "CROSSWALK_APPROVED", "ACTIVATED"),
    "ROLL_BACK": (CO, "ACTIVATED", "ROLLED_BACK"),
    "CANCEL": (CO, "MAPPING", "CANCELLED"),
}
CODE_UPDATE_READERS = [SA, RIA, PCA, CO]


def find_cycle(cycle_id):
    return find(
        STORE.code_update_cycles, cycle_id, "ERR_CODE_UPDATE_NOT_FOUND", "CodeUpdateCycle"
    )


def find_entry(entry_id):
    return find(
        STORE.code_update_entries, entry_id, "ERR_CODE_UPDATE_NOT_FOUND", "CodeUpdateEntry"
    )


@bp.route("/chargemaster/code-update-cycles", methods=["POST"])
def create_cycle():
    require(RIA)
    data = validate.body()
    facility = body_facility(data)
    cycle_year = validate.req_int(data, "cycle_year")
    code_set = validate.req_enum(data, "code_set", CODE_SETS)
    inflator = validate.opt_int(data, "cost_inflator_bp", 10300)
    for row in STORE.code_update_cycles.values():
        if (
            row["facility_id"] == facility["id"]
            and row["code_set"] == code_set
            and row["cycle_year"] == cycle_year
        ):
            fail(
                "ERR_DUPLICATE_KEY",
                "A cycle already exists for this facility, code set and year.",
            )
    cycle = {
        "facility_id": facility["id"],
        "cycle_year": cycle_year,
        "code_set": code_set,
        "cost_inflator_bp": inflator,
        "status": "LOADED",
        "entry_count": 0,
        "unmapped_entry_count": 0,
        "applied_entry_count": 0,
        "pre_activation_active_item_count": None,
        "pre_activation_aggregate_gross_charge_cents": None,
        "activated_at": None,
        "rolled_back_at": None,
    }
    STORE.stamp_new(cycle)
    STORE.code_update_cycles[cycle["id"]] = cycle
    return ok(serialize(cycle), 201)


@bp.route("/chargemaster/code-update-cycles", methods=["GET"])
def list_cycles():
    require(CODE_UPDATE_READERS)
    facility_id = validate.query_filter("facility_id")
    code_set = validate.query_filter("code_set")
    cycle_year = validate.query_int("cycle_year")
    status = validate.query_filter("status")

    def keep(row):
        if facility_id is not None and row["facility_id"] != facility_id:
            return False
        if code_set is not None and row["code_set"] != code_set:
            return False
        if cycle_year is not None and row["cycle_year"] != cycle_year:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return list_response(STORE.ordered(STORE.code_update_cycles, keep), serialize)


@bp.route("/chargemaster/code-update-cycles/<cycle_id>", methods=["GET"])
def read_cycle(cycle_id):
    require(CODE_UPDATE_READERS)
    return ok(serialize(find_cycle(cycle_id)))


@bp.route("/chargemaster/code-update-cycles/<cycle_id>/entries", methods=["POST"])
def create_entry(cycle_id):
    require(RIA)
    cycle = find_cycle(cycle_id)
    data = validate.body()
    action = validate.req_enum(data, "action", ENTRY_ACTIONS)
    old_code_value = validate.opt_string(data, "old_code_value")
    new_code_value = validate.opt_string(data, "new_code_value")
    new_revenue_code_id = validate.opt_id(data, "new_revenue_code_id")
    if cycle["status"] not in ("LOADED", "MAPPING"):
        fail(
            "ERR_INVALID_CYCLE_STATE",
            "Entries cannot be added to a cycle in %s." % cycle["status"],
        )
    entry = {
        "cycle_id": cycle["id"],
        "action": action,
        "old_code_value": old_code_value,
        "new_code_value": new_code_value,
        "target_charge_item_id": None,
        "new_revenue_code_id": new_revenue_code_id,
        "status": "PENDING",
        "carried_gross_charge_cents": None,
        "prior_code_value": None,
        "prior_gross_charge_cents": None,
        "prior_revenue_code_id": None,
        "prior_lifecycle_status": None,
        "defer_reason": None,
        "mapped_by_user_id": None,
    }
    STORE.stamp_new(entry)
    STORE.code_update_entries[entry["id"]] = entry
    recompute_cycle_counters(cycle, bump=True)
    return ok(serialize(entry), 201)


@bp.route("/chargemaster/code-update-entries", methods=["GET"])
def list_entries():
    require(CODE_UPDATE_READERS)
    filters = {
        key: validate.query_filter(key)
        for key in (
            "cycle_id",
            "target_charge_item_id",
            "new_revenue_code_id",
            "prior_revenue_code_id",
            "status",
            "action",
        )
    }

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(STORE.ordered(STORE.code_update_entries, keep), serialize)


@bp.route("/chargemaster/code-update-entries/<entry_id>", methods=["GET"])
def read_entry(entry_id):
    require(CODE_UPDATE_READERS)
    return ok(serialize(find_entry(entry_id)))


@bp.route("/chargemaster/code-update-cycles/<cycle_id>/lifecycle", methods=["POST"])
def cycle_lifecycle(cycle_id):
    user_id, role = require([RIA, PCA, CO])
    data = validate.body()
    raw_action = data.get("action")
    if isinstance(raw_action, str) and raw_action in CYCLE_ACTIONS:
        if role != CYCLE_ACTIONS[raw_action][0]:
            fail(
                "ERR_ROLE_NOT_PERMITTED",
                "Role %s may not perform action %s." % (role, raw_action),
            )
    cycle = find_cycle(cycle_id)
    action = validate.req_enum(data, "action", sorted(CYCLE_ACTIONS))
    validate.opt_string(data, "note")

    from_state, to_state = CYCLE_ACTIONS[action][1], CYCLE_ACTIONS[action][2]
    if cycle["status"] != from_state:
        fail(
            "ERR_INVALID_CYCLE_STATE",
            "Action %s is not declared out of %s." % (action, cycle["status"]),
        )
    entries = cycle_entries(cycle["id"])
    if action == "CANCEL":
        if any(entry["status"] == "APPLIED" for entry in entries):
            fail(
                "ERR_INVALID_CYCLE_STATE",
                "A cycle with applied entries cannot be cancelled.",
            )

    facility = STORE.facilities.get(cycle["facility_id"])
    if action in ("ACTIVATE", "ROLL_BACK"):
        if facility["chargemaster_posture"] == "FROZEN":
            fail("ERR_FACILITY_FROZEN", "The facility chargemaster is frozen.")

    if action == "APPROVE_CROSSWALK":
        for entry in entries:
            if entry.get("mapped_by_user_id") == user_id:
                fail(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "The crosswalk approver may not have mapped any entry.",
                )
        if any(entry["status"] == "PENDING" for entry in entries):
            fail("ERR_UNMAPPED_CODE_ENTRIES", "Every entry must be mapped or deferred.")
        if not any(entry["status"] == "MAPPED" for entry in entries):
            fail("ERR_CYCLE_HAS_NO_MAPPED_ENTRIES", "No entry of this cycle is MAPPED.")
    elif action == "START_MAPPING":
        if not entries:
            fail("ERR_CYCLE_HAS_NO_ENTRIES", "A cycle with no entries cannot be mapped.")
    elif action == "ACTIVATE":
        mapped_targets = set(
            entry["target_charge_item_id"]
            for entry in entries
            if entry["status"] == "MAPPED" and entry.get("target_charge_item_id")
        )
        for request_row in STORE.change_requests.values():
            if request_row["status"] != "APPROVED":
                continue
            if request_row["charge_item_id"] in mapped_targets:
                fail(
                    "ERR_ITEM_HAS_OPEN_REQUEST",
                    "An approved change request targets an item of this cycle.",
                )
    elif action == "ROLL_BACK":
        applied_targets = set(
            entry["target_charge_item_id"]
            for entry in entries
            if entry["status"] == "APPLIED" and entry.get("target_charge_item_id")
        )
        for line in STORE.captured_charges.values():
            if line.get("charge_item_id") not in applied_targets:
                continue
            batch = STORE.batches.get(line["batch_id"])
            if batch is not None and batch["status"] == "RECONCILING":
                fail(
                    "ERR_ITEM_IN_OPEN_BATCH",
                    "An item of this cycle appears in a reconciling batch.",
                )

    if action == "ACTIVATE":
        cycle["pre_activation_active_item_count"] = facility["active_item_count"]
        cycle["pre_activation_aggregate_gross_charge_cents"] = facility[
            "aggregate_gross_charge_cents"
        ]
        cycle["status"] = to_state
        cycle["activated_at"] = fmt_iso(STORE.now)
        STORE.touch(cycle)
        _apply_entries(cycle, entries)
        item_mutation_cascade(facility)
        recompute_cycle_counters(cycle, bump=False)
    elif action == "ROLL_BACK":
        _revert_entries(cycle, entries)
        cycle["status"] = to_state
        cycle["rolled_back_at"] = fmt_iso(STORE.now)
        STORE.touch(cycle)
        item_mutation_cascade(facility)
        recompute_cycle_counters(cycle, bump=False)
    elif action == "CANCEL":
        cycle["status"] = to_state
        STORE.touch(cycle)
        for entry in entries:
            if entry["status"] not in ("PENDING", "MAPPED"):
                continue
            entry["status"] = "DEFERRED"
            entry["defer_reason"] = "CYCLE_CANCELLED"
            entry["target_charge_item_id"] = None
            STORE.touch(entry)
        recompute_cycle_counters(cycle, bump=False)
        recompute_facility(facility, bump=True)
    else:
        cycle["status"] = to_state
        STORE.touch(cycle)
        recompute_facility(facility, bump=True)
    return ok(serialize(cycle))


def _apply_entries(cycle, entries):
    for entry in entries:
        if entry["status"] != "MAPPED":
            continue
        target = STORE.charge_items.get(entry.get("target_charge_item_id"))
        if target is None or target["lifecycle_status"] == "ARCHIVED":
            continue
        entry["prior_code_value"] = target.get("code_value")
        entry["prior_revenue_code_id"] = target["revenue_code_id"]
        entry["prior_gross_charge_cents"] = target["gross_charge_cents"]
        entry["prior_lifecycle_status"] = target["lifecycle_status"]
        entry["status"] = "APPLIED"
        STORE.touch(entry)
        if entry["action"] in ("CROSSWALK", "REVISE"):
            target["code_value"] = entry.get("new_code_value")
            if entry.get("new_revenue_code_id") is not None:
                target["revenue_code_id"] = entry["new_revenue_code_id"]
            target["gross_charge_cents"] = entry.get("carried_gross_charge_cents")
            target["price_status"] = "PRICE_STALE"
        elif entry["action"] == "DELETE":
            target["lifecycle_status"] = "INACTIVE"
        target["last_code_cycle_id"] = cycle["id"]
        STORE.touch(target)


def _revert_entries(cycle, entries):
    for entry in reversed(entries):
        if entry["status"] != "APPLIED":
            continue
        target = STORE.charge_items.get(entry.get("target_charge_item_id"))
        if target is not None:
            target["code_value"] = entry.get("prior_code_value")
            target["revenue_code_id"] = entry.get("prior_revenue_code_id")
            target["gross_charge_cents"] = entry.get("prior_gross_charge_cents")
            target["lifecycle_status"] = entry.get("prior_lifecycle_status")
            target["price_status"] = "PRICE_STALE"
            target["last_code_cycle_id"] = None
            STORE.touch(target)
        entry["status"] = "REVERTED"
        STORE.touch(entry)


@bp.route("/chargemaster/code-update-entries/<entry_id>/disposition", methods=["POST"])
def entry_disposition(entry_id):
    user_id, _role = require(RIA)
    entry = find_entry(entry_id)
    data = validate.body()
    action = validate.req_enum(data, "action", ("DEFER", "MAP"))
    payload_revenue_code_id = validate.opt_id(data, "new_revenue_code_id")
    defer_reason = None
    if action == "DEFER":
        defer_reason = validate.req_string(data, "defer_reason", 1)

    cycle = STORE.code_update_cycles.get(entry["cycle_id"])
    if cycle is None or cycle["status"] != "MAPPING":
        fail(
            "ERR_INVALID_CYCLE_STATE",
            "Entries may only be dispositioned while the cycle is MAPPING.",
        )
    if entry["status"] != "PENDING":
        fail(
            "ERR_INVALID_ENTRY_STATE",
            "An entry in %s cannot be dispositioned." % entry["status"],
        )

    if action == "DEFER":
        entry["status"] = "DEFERRED"
        entry["defer_reason"] = defer_reason
        entry["mapped_by_user_id"] = user_id
        STORE.touch(entry)
        recompute_cycle_counters(cycle, bump=True)
        return ok(serialize(entry))

    facility = STORE.facilities.get(cycle["facility_id"])
    new_revenue_code_id = (
        payload_revenue_code_id
        if payload_revenue_code_id is not None
        else entry.get("new_revenue_code_id")
    )
    revenue_code = None
    if new_revenue_code_id is not None:
        revenue_code = STORE.revenue_codes.get(new_revenue_code_id)
        if revenue_code is None or revenue_code["status"] != "ACTIVE":
            fail(
                "ERR_REVENUE_CODE_MAPPING_INVALID",
                "The remapped revenue code is not an ACTIVE revenue code.",
            )

    target = None
    if entry["action"] != "ADD":
        matches = []
        old_code_value = entry.get("old_code_value")
        if old_code_value is not None:
            for item in STORE.ordered(STORE.charge_items):
                if item["facility_id"] != facility["id"]:
                    continue
                if item.get("code_value") != old_code_value:
                    continue
                if item["lifecycle_status"] not in ("ACTIVE", "INACTIVE", "APPROVED"):
                    continue
                matches.append(item)
        if not matches:
            fail(
                "ERR_CROSSWALK_TARGET_NOT_FOUND",
                "No charge item carries the retiring code value.",
            )
        if len(matches) > 1:
            fail(
                "ERR_CROSSWALK_TARGET_AMBIGUOUS",
                "More than one charge item carries the retiring code value.",
            )
        target = matches[0]

    if revenue_code is not None and target is not None:
        if target["code_type"] not in (revenue_code.get("allowed_code_types") or []):
            fail(
                "ERR_REVENUE_CODE_MAPPING_INVALID",
                "The remapped revenue code cannot carry this item.",
            )

    carried = None
    if target is not None:
        carried = code_update_crosswalk_price_carry(
            cycle, entry, target, facility, new_revenue_code_id
        )

    entry["new_revenue_code_id"] = new_revenue_code_id
    entry["target_charge_item_id"] = target["id"] if target is not None else None
    entry["carried_gross_charge_cents"] = carried
    entry["mapped_by_user_id"] = user_id
    entry["status"] = "MAPPED"
    STORE.touch(entry)
    recompute_cycle_counters(cycle, bump=True)
    return ok(serialize(entry))

