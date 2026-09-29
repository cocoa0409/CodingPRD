"""Federal receipts, monitor runs, transfers and recall execution."""

from flask import Blueprint, g, request

import calc
import serializers as ser
import services as svc
import validators as val
from db import base_row, db, now, ordered, touch
from errors import fail
from middleware import ANY_ROLE, body, endpoint, paginate, pagination
from response import collection, created, ok

bp = Blueprint("inventory", __name__)

RECALL_CLASSES = ("CLASS_I", "CLASS_II", "CLASS_III")
HOLD_SCOPES = ("LOT_ONLY", "COMMODITY_WIDE")
DISPOSITIONS = ("DESTROYED", "RETURNED_TO_STATE", "NOT_RECEIVED")
RECALLABLE_LOT_STATUSES = ("RECEIVED", "AVAILABLE", "WATCH")


def _page(rows):
    limit, offset = pagination()
    return limit, offset, len(rows), paginate(rows, limit, offset)


def _filter(name):
    value = request.args.get(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


# ---------------------------------------------------------------------------
# InventoryLot (PRD §3.3)
# ---------------------------------------------------------------------------
@bp.post("/efap/inventory-lots")
@endpoint("StateAdmin")
def create_lot():
    payload = body()
    val.req_id(payload, "commodity_id")
    val.req_id(payload, "warehouse_id")
    federal_lot_code = val.req_string(payload, "federal_lot_code", 1, 40)
    cases_received = val.req_int(payload, "cases_received", minimum=1)
    pack_date = val.req_date(payload, "pack_date")
    best_by_date = val.req_date(payload, "best_by_date")
    if best_by_date <= pack_date:
        fail("ERR_INVALID_REQUEST", "best_by_date must be after pack_date")
    item = svc.commodity(payload["commodity_id"])
    house = svc.warehouse(payload["warehouse_id"])
    for existing in db.lots.values():
        if (
            existing["warehouse_id"] == house["id"]
            and existing["federal_lot_code"] == federal_lot_code
        ):
            fail(
                "ERR_DUPLICATE_CODE",
                "federal_lot_code %s already exists at this warehouse" % federal_lot_code,
            )
    row = base_row()
    row.update(
        {
            "commodity_id": item["id"],
            "warehouse_id": house["id"],
            "federal_lot_code": federal_lot_code,
            "cases_received": cases_received,
            "cases_on_hand": 0,
            "cases_committed": 0,
            "cases_shipped_to_date": 0,
            "pack_date": pack_date,
            "best_by_date": best_by_date,
            "entitlement_value_cents": cases_received
            * item["entitlement_value_cents_per_case"],
            "status": "RECEIVED",
            "monitor_flag": "NONE",
            "slow_moving_index": calc.ZERO_4,
            "last_monitored_at": None,
            "posted_at": None,
            "hold_recall_id": None,
        }
    )
    db.lots[row["id"]] = row
    return created(ser.inventory_lot(row))


@bp.get("/efap/inventory-lots")
@endpoint(*ANY_ROLE)
def list_lots():
    warehouse_id = _filter("warehouse_id")
    commodity_id = _filter("commodity_id")
    hold_recall_id = _filter("hold_recall_id")
    status = _filter("status")
    monitor_flag = _filter("monitor_flag")
    rows = ordered(db.lots.values())
    if warehouse_id is not None:
        rows = [r for r in rows if r["warehouse_id"] == warehouse_id]
    if commodity_id is not None:
        rows = [r for r in rows if r["commodity_id"] == commodity_id]
    if hold_recall_id is not None:
        rows = [r for r in rows if r["hold_recall_id"] == hold_recall_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if monitor_flag is not None:
        rows = [r for r in rows if r["monitor_flag"] == monitor_flag]
    limit, offset, total, page = _page(rows)
    return collection([ser.inventory_lot(r) for r in page], limit, offset, total)


@bp.get("/efap/inventory-lots/<inventory_lot_id>")
@endpoint(*ANY_ROLE)
def read_lot(inventory_lot_id):
    return ok(ser.inventory_lot(svc.lot(inventory_lot_id)))


@bp.post("/efap/inventory-lots/<inventory_lot_id>/post")
@endpoint("StateAdmin")
def post_lot(inventory_lot_id):
    row = svc.lot(inventory_lot_id)
    if row["status"] != "RECEIVED":
        fail("ERR_INVALID_LOT_STATE", "Only a RECEIVED lot may be posted")
    if svc.lot_under_open_recall(row):
        fail("ERR_RECALL_HOLD_ACTIVE", "An open recall covers this lot")
    row["cases_on_hand"] = row["cases_received"]
    row["cases_committed"] = 0
    row["posted_at"] = now()
    row["status"] = "AVAILABLE"
    touch(row)
    return ok(ser.inventory_lot(row))


@bp.post("/efap/inventory-monitor-runs")
@endpoint("StateAdmin")
def monitor_run():
    payload = body()
    warehouse_id = None
    if val.present(payload, "warehouse_id"):
        val.req_id(payload, "warehouse_id")
        warehouse_id = svc.warehouse(payload["warehouse_id"])["id"]
    scored = []
    for row in ordered(db.lots.values()):
        if row["status"] not in svc.LIVE_LOT_STATUSES:
            continue
        if warehouse_id is not None and row["warehouse_id"] != warehouse_id:
            continue
        scored.append(svc.score_lot(row))
    return collection([ser.inventory_lot(r) for r in scored])


# ---------------------------------------------------------------------------
# InventoryTransfer (PRD §3.3)
# ---------------------------------------------------------------------------
@bp.post("/efap/inventory-transfers")
@endpoint("StateAdmin")
def propose_transfer():
    payload = body()
    val.req_id(payload, "from_lot_id")
    val.req_id(payload, "to_agency_id")
    cases = val.req_int(payload, "cases", minimum=1)
    expected = val.req_int(payload, "expected_inventory_lot_version")
    source = svc.lot(payload["from_lot_id"])
    receiver = svc.agency(payload["to_agency_id"])
    if source["version"] != expected:
        fail(
            "ERR_STALE_VERSION",
            "expected_inventory_lot_version %s does not match %s"
            % (expected, source["version"]),
        )
    if source["status"] == "HOLD":
        fail("ERR_RECALL_HOLD_ACTIVE", "The source lot is on recall hold")
    if source["status"] not in svc.LIVE_LOT_STATUSES:
        fail("ERR_INVALID_LOT_STATE", "The source lot is %s" % source["status"])
    if svc.lot_under_open_recall(source):
        fail("ERR_RECALL_HOLD_ACTIVE", "An open recall covers the source lot")
    available = source["cases_on_hand"] - source["cases_committed"]
    if cases > available:
        fail("ERR_LOT_CASES_UNAVAILABLE", "Only %d uncommitted cases remain" % available)
    item = svc.commodity(source["commodity_id"])
    row = base_row()
    row.update(
        {
            "from_lot_id": source["id"],
            "to_agency_id": receiver["id"],
            "cases": cases,
            "status": "PROPOSED",
            "transferred_value_cents": cases * item["entitlement_value_cents_per_case"],
            "decline_reason": None,
            "accepted_at": None,
        }
    )
    db.transfers[row["id"]] = row
    source["cases_committed"] = source["cases_committed"] + cases
    touch(source)
    return created(ser.inventory_transfer(row))


@bp.get("/efap/inventory-transfers")
@endpoint(*ANY_ROLE)
def list_transfers():
    from_lot_id = _filter("from_lot_id")
    to_agency_id = _filter("to_agency_id")
    status = _filter("status")
    rows = ordered(db.transfers.values())
    if from_lot_id is not None:
        rows = [r for r in rows if r["from_lot_id"] == from_lot_id]
    if to_agency_id is not None:
        rows = [r for r in rows if r["to_agency_id"] == to_agency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    limit, offset, total, page = _page(rows)
    return collection([ser.inventory_transfer(r) for r in page], limit, offset, total)


@bp.get("/efap/inventory-transfers/<transfer_id>")
@endpoint(*ANY_ROLE)
def read_transfer(transfer_id):
    return ok(ser.inventory_transfer(svc.transfer(transfer_id)))


@bp.post("/efap/inventory-transfers/<transfer_id>/accept")
@endpoint("AgencyCoordinator")
def accept_transfer(transfer_id):
    row = svc.transfer(transfer_id)
    if g.user_id != row["to_agency_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the receiving agency may accept")
    if row["status"] != "PROPOSED":
        fail("ERR_INVALID_TRANSFER_STATE", "The transfer is %s" % row["status"])
    source = db.lots.get(row["from_lot_id"])
    if source is None:
        fail("ERR_INVENTORY_LOT_NOT_FOUND", "The source lot no longer exists")
    if source["status"] == "HOLD":
        fail("ERR_RECALL_HOLD_ACTIVE", "The source lot is on recall hold")
    if source["status"] not in svc.LIVE_LOT_STATUSES:
        fail("ERR_INVALID_LOT_STATE", "The source lot is %s" % source["status"])
    receiver = svc.agency(row["to_agency_id"])
    svc.require_posture(receiver, ("ELIGIBLE",))
    cases = row["cases"]
    source["cases_on_hand"] = source["cases_on_hand"] - cases
    source["cases_committed"] = source["cases_committed"] - cases
    source["cases_shipped_to_date"] = source["cases_shipped_to_date"] + cases
    svc.deplete_if_empty(source)
    touch(source)
    receiver["agency_cases_on_hand"] = receiver["agency_cases_on_hand"] + cases
    touch(receiver)
    row["status"] = "ACCEPTED"
    row["accepted_at"] = now()
    touch(row)
    return ok(ser.inventory_transfer(row))


@bp.post("/efap/inventory-transfers/<transfer_id>/decline")
@endpoint("AgencyCoordinator")
def decline_transfer(transfer_id):
    row = svc.transfer(transfer_id)
    payload = body()
    decline_reason = val.req_string(payload, "decline_reason", 1, 400)
    if g.user_id != row["to_agency_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the receiving agency may decline")
    if row["status"] != "PROPOSED":
        fail("ERR_INVALID_TRANSFER_STATE", "The transfer is %s" % row["status"])
    source = db.lots.get(row["from_lot_id"])
    if source is not None and source["status"] != "DISPOSED":
        source["cases_committed"] = source["cases_committed"] - row["cases"]
        touch(source)
    row["status"] = "DECLINED"
    row["decline_reason"] = decline_reason
    touch(row)
    return ok(ser.inventory_transfer(row))


# ---------------------------------------------------------------------------
# Recall (PRD §3.8)
# ---------------------------------------------------------------------------
@bp.post("/efap/recalls")
@endpoint("StateAdmin")
def create_recall():
    payload = body()
    val.req_id(payload, "source_lot_id")
    recall_class = val.req_enum(payload, "recall_class", RECALL_CLASSES)
    hold_scope = val.req_enum(payload, "hold_scope", HOLD_SCOPES)
    reason = val.req_string(payload, "reason", 1, 400)
    source = svc.lot(payload["source_lot_id"])
    for existing in db.recalls.values():
        if (
            existing["source_lot_id"] == source["id"]
            and existing["status"] in svc.OPEN_RECALL_STATUSES
        ):
            fail("ERR_RECALL_ALREADY_OPEN", "An open recall already names this lot")
    if source["status"] not in RECALLABLE_LOT_STATUSES:
        fail("ERR_INVALID_LOT_STATE", "A %s lot cannot be recalled" % source["status"])
    item = db.commodities.get(source["commodity_id"])
    row = base_row()
    row.update(
        {
            "source_lot_id": source["id"],
            "commodity_code": item["code"] if item else None,
            "recall_class": recall_class,
            "hold_scope": hold_scope,
            "reason": reason,
            "initiated_by_user_id": g.user_id,
            "status": "INITIATED",
            "held_lot_count": 0,
            "action_count": 0,
            "acknowledged_count": 0,
            "dispositioned_count": 0,
            "accounted_cases": 0,
            "notices_dispatched_at": None,
        }
    )
    db.recalls[row["id"]] = row

    # coverage: the source lot alone, or every live lot of the same commodity
    if hold_scope == "COMMODITY_WIDE":
        covered = [
            candidate
            for candidate in ordered(db.lots.values())
            if candidate["commodity_id"] == source["commodity_id"]
            and candidate["status"] in svc.LIVE_LOT_STATUSES
        ]
    else:
        covered = [source] if source["status"] in svc.LIVE_LOT_STATUSES else []
    for candidate in covered:
        candidate["status"] = "HOLD"
        candidate["hold_recall_id"] = row["id"]
        touch(candidate)
        row["held_lot_count"] = row["held_lot_count"] + 1
    for candidate in covered:
        svc.block_downstream(candidate["id"])

    # downstream exposure becomes one action per receiving agency
    exposure = svc.exposure_by_agency([candidate["id"] for candidate in covered])
    for target in ordered(db.agencies.values()):
        cases = exposure.get(target["id"], 0)
        if cases <= 0:
            continue
        action = base_row()
        action.update(
            {
                "recall_id": row["id"],
                "agency_id": target["id"],
                "status": "PENDING_NOTICE",
                "exposed_cases": cases,
                "disposition": None,
                "cases_accounted": 0,
                "notified_at": None,
                "acknowledged_at": None,
                "dispositioned_at": None,
            }
        )
        db.recall_actions[action["id"]] = action
        row["action_count"] = row["action_count"] + 1
    return created(ser.recall(row))


@bp.get("/efap/recalls")
@endpoint(*ANY_ROLE)
def list_recalls():
    source_lot_id = _filter("source_lot_id")
    recall_class = _filter("recall_class")
    status = _filter("status")
    rows = ordered(db.recalls.values())
    if source_lot_id is not None:
        rows = [r for r in rows if r["source_lot_id"] == source_lot_id]
    if recall_class is not None:
        rows = [r for r in rows if r["recall_class"] == recall_class]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    limit, offset, total, page = _page(rows)
    return collection([ser.recall(r) for r in page], limit, offset, total)


@bp.get("/efap/recalls/<recall_id>")
@endpoint(*ANY_ROLE)
def read_recall(recall_id):
    return ok(ser.recall(svc.recall(recall_id)))


@bp.post("/efap/recalls/<recall_id>/dispatch-notices")
@endpoint("StateAdmin")
def dispatch_notices(recall_id):
    row = svc.recall(recall_id)
    if row["status"] not in ("INITIATED", "NOTIFYING") or row["action_count"] < 1:
        fail("ERR_INVALID_RECALL_STATE", "Notices cannot be dispatched now")
    stamp = now()
    for action in ordered(db.recall_actions.values()):
        if action["recall_id"] != row["id"] or action["status"] != "PENDING_NOTICE":
            continue
        action["status"] = "NOTIFIED"
        action["notified_at"] = stamp
        touch(action)
    row["status"] = "NOTIFYING"
    row["notices_dispatched_at"] = stamp
    touch(row)
    return ok(ser.recall(row))


@bp.post("/efap/recalls/<recall_id>/expand")
@endpoint("StateAdmin")
def expand_recall(recall_id):
    row = svc.recall(recall_id)
    payload = body()
    val.req_id(payload, "agency_id")
    target = svc.agency(payload["agency_id"])
    if row["status"] != "MONITORING":
        fail("ERR_INVALID_RECALL_STATE", "Only a MONITORING recall may be expanded")
    for existing in db.recall_actions.values():
        if existing["recall_id"] == row["id"] and existing["agency_id"] == target["id"]:
            fail("ERR_DUPLICATE_RECALL_ACTION", "That agency already has an action")
    exposure = svc.exposure_by_agency(svc.held_lot_ids(row))
    action = base_row()
    action.update(
        {
            "recall_id": row["id"],
            "agency_id": target["id"],
            "status": "PENDING_NOTICE",
            "exposed_cases": exposure.get(target["id"], 0),
            "disposition": None,
            "cases_accounted": 0,
            "notified_at": None,
            "acknowledged_at": None,
            "dispositioned_at": None,
        }
    )
    db.recall_actions[action["id"]] = action
    row["action_count"] = row["action_count"] + 1
    row["status"] = "NOTIFYING"
    touch(row)
    return created(ser.recall_action(action))


@bp.post("/efap/recalls/<recall_id>/close")
@endpoint("StateAdmin")
def close_recall(recall_id):
    row = svc.recall(recall_id)
    actions = [r for r in ordered(db.recall_actions.values()) if r["recall_id"] == row["id"]]
    monitoring_done = (
        row["status"] == "MONITORING" and row["dispositioned_count"] == row["action_count"]
    )
    zero_exposure = row["status"] == "INITIATED" and row["action_count"] == 0
    if not (monitoring_done or zero_exposure):
        fail("ERR_INVALID_RECALL_STATE", "The recall cannot be closed in %s" % row["status"])
    if row["recall_class"] == "CLASS_I":
        for action in actions:
            if action["status"] == "DISPOSITIONED" and (
                action["cases_accounted"] != action["exposed_cases"]
            ):
                fail(
                    "ERR_RECALL_CASES_UNACCOUNTED",
                    "A CLASS_I recall requires every exposed case to be accounted for",
                )
    if g.user_id == row["initiated_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The initiating admin may not close the recall")
    destroyed = any(
        action["status"] == "DISPOSITIONED" and action["disposition"] == "DESTROYED"
        for action in actions
    )
    for lot_id in svc.held_lot_ids(row):
        target = db.lots.get(lot_id)
        if target is None:
            continue
        if destroyed:
            svc.dispose_lot(target)
        else:
            svc.release_lot(target)
    row["status"] = "CLOSED"
    touch(row)
    return ok(ser.recall(row))


@bp.get("/efap/recalls/<recall_id>/actions")
@endpoint(*ANY_ROLE)
def list_recall_actions_of(recall_id):
    row = svc.recall(recall_id)
    rows = [r for r in ordered(db.recall_actions.values()) if r["recall_id"] == row["id"]]
    limit, offset, total, page = _page(rows)
    return collection([ser.recall_action(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# RecallAction (PRD §3.8)
# ---------------------------------------------------------------------------
@bp.get("/efap/recall-actions")
@endpoint(*ANY_ROLE)
def list_recall_actions():
    recall_id = _filter("recall_id")
    agency_id = _filter("agency_id")
    status = _filter("status")
    rows = ordered(db.recall_actions.values())
    if recall_id is not None:
        rows = [r for r in rows if r["recall_id"] == recall_id]
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    limit, offset, total, page = _page(rows)
    return collection([ser.recall_action(r) for r in page], limit, offset, total)


@bp.get("/efap/recall-actions/<recall_action_id>")
@endpoint(*ANY_ROLE)
def read_recall_action(recall_action_id):
    return ok(ser.recall_action(svc.recall_action(recall_action_id)))


@bp.post("/efap/recall-actions/<recall_action_id>/acknowledge")
@endpoint("AgencyCoordinator")
def acknowledge_action(recall_action_id):
    row = svc.recall_action(recall_action_id)
    if g.user_id != row["agency_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the notified agency may acknowledge")
    if row["status"] != "NOTIFIED":
        fail("ERR_INVALID_RECALL_ACTION_STATE", "The action is %s" % row["status"])
    row["status"] = "ACKNOWLEDGED"
    row["acknowledged_at"] = now()
    touch(row)
    parent = db.recalls.get(row["recall_id"])
    if parent is not None:
        parent["acknowledged_count"] = sum(
            1
            for action in db.recall_actions.values()
            if action["recall_id"] == parent["id"]
            and action["status"] in ("ACKNOWLEDGED", "DISPOSITIONED")
        )
        if (
            parent["status"] == "NOTIFYING"
            and parent["acknowledged_count"] == parent["action_count"]
        ):
            parent["status"] = "MONITORING"
        touch(parent)
    return ok(ser.recall_action(row))


@bp.post("/efap/recall-actions/<recall_action_id>/report-disposition")
@endpoint("AgencyCoordinator")
def report_disposition(recall_action_id):
    row = svc.recall_action(recall_action_id)
    payload = body()
    disposition = val.req_enum(payload, "disposition", DISPOSITIONS)
    cases_accounted = val.req_int(payload, "cases_accounted", minimum=0)
    if cases_accounted > row["exposed_cases"]:
        fail("ERR_INVALID_REQUEST", "cases_accounted exceeds exposed_cases")
    if g.user_id != row["agency_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the notified agency may report")
    if row["status"] != "ACKNOWLEDGED":
        fail("ERR_INVALID_RECALL_ACTION_STATE", "The action is %s" % row["status"])
    reporter = svc.agency(row["agency_id"])
    if disposition == "RETURNED_TO_STATE":
        if cases_accounted > reporter["agency_cases_on_hand"]:
            fail(
                "ERR_AGENCY_INVENTORY_INSUFFICIENT",
                "The agency holds only %d cases" % reporter["agency_cases_on_hand"],
            )
    row["status"] = "DISPOSITIONED"
    row["disposition"] = disposition
    row["cases_accounted"] = cases_accounted
    row["dispositioned_at"] = now()
    touch(row)
    parent = db.recalls.get(row["recall_id"])
    if parent is not None:
        parent["dispositioned_count"] = parent["dispositioned_count"] + 1
        parent["accounted_cases"] = parent["accounted_cases"] + cases_accounted
        touch(parent)
    if disposition == "RETURNED_TO_STATE" and cases_accounted:
        reporter["agency_cases_on_hand"] = (
            reporter["agency_cases_on_hand"] - cases_accounted
        )
        touch(reporter)
        if parent is not None:
            source = db.lots.get(parent["source_lot_id"])
            if source is not None:
                source["cases_on_hand"] = source["cases_on_hand"] + cases_accounted
                touch(source)
    return ok(ser.recall_action(row))
