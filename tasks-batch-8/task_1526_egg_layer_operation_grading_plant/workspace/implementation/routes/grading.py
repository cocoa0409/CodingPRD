"""Grading runs and egg lots: materialization, holds, allocation, shipping."""
from datetime import timedelta
from flask import Blueprint, request

from db import STORE, new_record, today, touch
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_SOD_VIOLATION,
    ERR_INSUFFICIENT_UNGRADED_EGGS, ERR_SIZE_DISTRIBUTION_MISMATCH,
    ERR_LOT_QUALITY_HELD, ERR_UNRESOLVED_POSITIVE, ERR_FARM_SUSPENDED,
    ERR_CONTRACT_INACTIVE, ERR_CLAIM_MISMATCH, ERR_CONTRACT_VOLUME_EXCEEDED,
    ERR_SHELF_LIFE_EXCEEDED,
)
from middleware import endpoint, ALL_ROLES
from response import ok, paginate, pub
from util import req_str, req_int, req_enum
from services.domain import (
    get_entity, farm_of_flock, farm_id_of_flock, flock_ungraded_pool,
    contract_allocated_dozen, contract_held_allocated_dozen, suspend_contract,
    SIZE_ORDER, SIZE_COUNT_FIELD, SIZE_RANK, SHELF_LIFE_DAYS, CLAIM_ACCEPTS,
)

bp = Blueprint("grading", __name__)

GRADES = {"AA", "A", "B"}
NINE_COUNT_FIELDS = [
    "peewee_count", "small_count", "medium_count", "large_count",
    "xlarge_count", "jumbo_count", "cracked_count", "dirty_count",
    "blood_spot_count",
]


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def _get_run(gradingRunId):
    return get_entity("grading_runs", gradingRunId, "GradingRun")


def _get_lot(lotId):
    return get_entity("lots", lotId, "EggLot")


def _release_allocation(lot):
    """Release a lot's contract allocation: clear contract_id, bump contract."""
    contract = STORE["contracts"].get(lot.get("contract_id") or "")
    lot["contract_id"] = None
    if contract is not None:
        touch(contract)


# ---------------------------------------------------------------------------
# Grading runs
# ---------------------------------------------------------------------------
@bp.route("/api/grading-runs", methods=["POST"])
@endpoint(["QualityGrader"])
def create_grading_run(actor):
    body = _body()
    flock_id = body.get("flock_id")
    if isinstance(flock_id, str) and flock_id:
        get_entity("flocks", flock_id, "Flock")
    flock_id = req_str(body, "flock_id")
    flock = get_entity("flocks", flock_id, "Flock")
    grade = req_enum(body, "grade", GRADES)
    eggs_to_grade = req_int(body, "eggs_to_grade", min_v=1)
    # Tier 11: pool sufficiency at create.
    if eggs_to_grade > flock_ungraded_pool(flock):
        raise ApiError(ERR_INSUFFICIENT_UNGRADED_EGGS, 422, "eggs_to_grade exceeds the ungraded egg pool")
    rec = new_record()
    rec.update({
        "flock_id": flock_id,
        "grade": grade,
        "eggs_to_grade": eggs_to_grade,
        "peewee_count": None,
        "small_count": None,
        "medium_count": None,
        "large_count": None,
        "xlarge_count": None,
        "jumbo_count": None,
        "cracked_count": None,
        "dirty_count": None,
        "blood_spot_count": None,
        "status": "DRAFT",
        "submitted_by": None,
        "confirmed_by": None,
        "pack_date": None,
        "lot_ids": [],
    })
    STORE["grading_runs"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.route("/api/grading-runs/<gradingRunId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_grading_run(gradingRunId, actor):
    return ok(pub(_get_run(gradingRunId)), status=200)


@bp.route("/api/grading-runs", methods=["GET"])
@endpoint(ALL_ROLES)
def list_grading_runs(actor):
    items = list(STORE["grading_runs"].values())
    flock_id = request.args.get("flock_id")
    status = request.args.get("status")
    if flock_id is not None:
        items = [g for g in items if g["flock_id"] == flock_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items.sort(key=lambda g: (g["created_at"], g["_seq"]))
    return paginate(items, pub)


@bp.route("/api/grading-runs/<gradingRunId>/submit", methods=["POST"])
@endpoint(["QualityGrader"])
def submit_grading_run(gradingRunId, actor):
    run = _get_run(gradingRunId)
    body = _body()
    # Tier 5: nine counts present, integers >= 0.
    counts = {f: req_int(body, f, min_v=0) for f in NINE_COUNT_FIELDS}
    # Tier 6: state DRAFT -> SUBMITTED.
    if run["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Grading run must be DRAFT to submit")
    # Tier 11: nine counts must sum exactly to eggs_to_grade.
    if sum(counts.values()) != run["eggs_to_grade"]:
        raise ApiError(ERR_SIZE_DISTRIBUTION_MISMATCH, 422, "Size and undergrade counts do not sum to eggs_to_grade")
    run.update(counts)
    run["status"] = "SUBMITTED"
    run["submitted_by"] = actor
    touch(run)
    return ok(pub(run), status=200)


@bp.route("/api/grading-runs/<gradingRunId>/confirm", methods=["POST"])
@endpoint(["QAManager"])
def confirm_grading_run(gradingRunId, actor):
    run = _get_run(gradingRunId)
    # Tier 3: segregation of duties — confirmer must differ from submitter.
    if run.get("submitted_by") is not None and actor == run["submitted_by"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Confirmer must differ from submitter")
    # Tier 6: state SUBMITTED -> CONFIRMED.
    if run["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Grading run must be SUBMITTED to confirm")
    flock = STORE["flocks"][run["flock_id"]]
    # Tier 11: pool re-validated at confirm.
    if run["eggs_to_grade"] > flock_ungraded_pool(flock):
        raise ApiError(ERR_INSUFFICIENT_UNGRADED_EGGS, 422, "Ungraded egg pool no longer covers eggs_to_grade")
    # size_distribution_materialization: fixed order JUMBO..PEEWEE.
    pack_date = today()
    farm = farm_of_flock(flock)
    claim = farm["certification_program"]
    lot_ids = []
    for size in SIZE_ORDER:
        count = run[SIZE_COUNT_FIELD[size]] or 0
        dozen = count // 12
        if dozen <= 0:
            continue
        lot = new_record()
        lot.update({
            "grading_run_id": run["id"],
            "flock_id": flock["id"],
            "farm_id": farm["id"],
            "contract_id": None,
            "recall_id": None,
            "size_class": size,
            "grade": run["grade"],
            "dozen_count": dozen,
            "claim_program": claim,
            "pack_date": pack_date,
            "sell_by_date": pack_date + timedelta(days=SHELF_LIFE_DAYS[claim]),
            "ship_date": None,
            "lifecycle_status": "FRESH",
            "hold_status": "CLEAR",
        })
        STORE["lots"][lot["id"]] = lot
        lot_ids.append(lot["id"])
    run["status"] = "CONFIRMED"
    run["confirmed_by"] = actor
    run["pack_date"] = pack_date
    run["lot_ids"] = lot_ids
    touch(run)
    touch(flock)  # pool/loose ledgers shift -> flock version +1
    return ok(pub(run), status=200)


@bp.route("/api/grading-runs/<gradingRunId>/void", methods=["POST"])
@endpoint(["QAManager"])
def void_grading_run(gradingRunId, actor):
    run = _get_run(gradingRunId)
    if run["status"] == "VOIDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Grading run is already VOIDED")
    if run["status"] == "CONFIRMED":
        children = [l for l in STORE["lots"].values() if l["grading_run_id"] == run["id"]]
        if any(l["lifecycle_status"] in ("SHIPPED", "CLOSED", "RECALLED") for l in children):
            raise ApiError(ERR_INVALID_STATE, 409, "A child lot has shipped, closed, or been recalled")
        # Compensation: FRESH/RELEASED/ALLOCATED -> EXPIRED (ALLOCATED releases first).
        for lot in children:
            if lot["lifecycle_status"] not in ("FRESH", "RELEASED", "ALLOCATED"):
                continue
            if lot["lifecycle_status"] == "ALLOCATED":
                _release_allocation(lot)
            lot["lifecycle_status"] = "EXPIRED"
            touch(lot)
        flock = STORE["flocks"][run["flock_id"]]
        touch(flock)  # egg draw returns to the pool; loose remainders reclaimed
    run["status"] = "VOIDED"
    touch(run)
    return ok(pub(run), status=200)


# ---------------------------------------------------------------------------
# Egg lots (created only via grading-run confirm)
# ---------------------------------------------------------------------------
@bp.route("/api/lots/<lotId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_lot(lotId, actor):
    return ok(pub(_get_lot(lotId)), status=200)


@bp.route("/api/lots", methods=["GET"])
@endpoint(ALL_ROLES)
def list_lots(actor):
    items = list(STORE["lots"].values())
    for param, field in (
        ("grading_run_id", "grading_run_id"), ("flock_id", "flock_id"),
        ("farm_id", "farm_id"), ("contract_id", "contract_id"),
        ("recall_id", "recall_id"), ("lifecycle_status", "lifecycle_status"),
        ("hold_status", "hold_status"), ("size_class", "size_class"),
    ):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if l.get(field) == val]
    # created_at ASC, size-class rank DESC tie-break (JUMBO first).
    items.sort(key=lambda l: (l["created_at"], -SIZE_RANK[l["size_class"]], l["_seq"]))
    return paginate(items, pub)


@bp.route("/api/lots/<lotId>/release", methods=["POST"])
@endpoint(["QAManager"])
def release_lot(lotId, actor):
    lot = _get_lot(lotId)
    # Tier 6: lifecycle FRESH -> RELEASED.
    if lot["lifecycle_status"] != "FRESH":
        raise ApiError(ERR_INVALID_STATE, 409, "Lot must be FRESH to release")
    flock = STORE["flocks"][lot["flock_id"]]
    farm = STORE["farms"][lot["farm_id"]]
    # Tier 8: farm posture gate.
    if farm["compliance_posture"] == "SUSPENDED":
        raise ApiError(ERR_FARM_SUSPENDED, 409, "Farm compliance posture is SUSPENDED")
    # Tier 9: hold gate, then quarantine gate.
    if lot["hold_status"] != "CLEAR":
        raise ApiError(ERR_LOT_QUALITY_HELD, 409, "Lot is quality held")
    if flock["quarantine_status"] != "CLEAR":
        raise ApiError(ERR_UNRESOLVED_POSITIVE, 409, "Flock is quarantined")
    lot["lifecycle_status"] = "RELEASED"
    touch(lot)
    return ok(pub(lot), status=200)


@bp.route("/api/lots/<lotId>/hold", methods=["POST"])
@endpoint(["QAManager"])
def hold_lot(lotId, actor):
    lot = _get_lot(lotId)
    if lot["lifecycle_status"] not in ("FRESH", "RELEASED", "ALLOCATED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Lot cannot be held in its current lifecycle state")
    if lot["hold_status"] != "CLEAR":
        raise ApiError(ERR_INVALID_STATE, 409, "Lot is already HELD")
    lot["hold_status"] = "HELD"
    touch(lot)
    # Holding an ALLOCATED lot auto-suspends its contract (cascade).
    if lot["lifecycle_status"] == "ALLOCATED" and lot.get("contract_id"):
        contract = STORE["contracts"].get(lot["contract_id"])
        if contract is not None and contract_held_allocated_dozen(contract) > 0:
            suspend_contract(contract)
    return ok(pub(lot), status=200)


@bp.route("/api/lots/<lotId>/clear-hold", methods=["POST"])
@endpoint(["QAManager"])
def clear_hold_lot(lotId, actor):
    lot = _get_lot(lotId)
    if lot["lifecycle_status"] not in ("FRESH", "RELEASED", "ALLOCATED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Lot hold cannot be cleared in its current lifecycle state")
    if lot["hold_status"] != "HELD":
        raise ApiError(ERR_INVALID_STATE, 409, "Lot is not HELD")
    flock = STORE["flocks"][lot["flock_id"]]
    # Tier 9: quarantine holds cannot be cleared manually.
    if flock["quarantine_status"] != "CLEAR":
        raise ApiError(ERR_UNRESOLVED_POSITIVE, 409, "Flock is quarantined")
    lot["hold_status"] = "CLEAR"
    touch(lot)
    return ok(pub(lot), status=200)


@bp.route("/api/lots/<lotId>/allocate", methods=["POST"])
@endpoint(["ContractManager"])
def allocate_lot(lotId, actor):
    lot = _get_lot(lotId)
    body = _body()
    # Tier 4: body FK existence.
    contract_id = body.get("contract_id")
    if isinstance(contract_id, str) and contract_id:
        get_entity("contracts", contract_id, "RetailerContract")
    contract_id = req_str(body, "contract_id")
    contract = get_entity("contracts", contract_id, "RetailerContract")
    # Tier 6: lifecycle RELEASED -> ALLOCATED.
    if lot["lifecycle_status"] != "RELEASED":
        raise ApiError(ERR_INVALID_STATE, 409, "Lot must be RELEASED to allocate")
    # Tier 8: contract must be ACTIVE and currently in force.
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_INACTIVE, 409, "Contract is not ACTIVE")
    today_d = today()
    if not (contract["effective_start"] <= today_d < contract["effective_end"]):
        raise ApiError(ERR_CONTRACT_INACTIVE, 409, "Clock date is outside the contract's effective window")
    # Tier 9: hold gate, then claim compatibility.
    if lot["hold_status"] != "CLEAR":
        raise ApiError(ERR_LOT_QUALITY_HELD, 409, "Lot is quality held")
    if lot["claim_program"] not in CLAIM_ACCEPTS[contract["claim_required"]]:
        raise ApiError(ERR_CLAIM_MISMATCH, 409, "Lot claim_program does not satisfy contract claim_required")
    # Tier 12: volume cap.
    if contract_allocated_dozen(contract) + lot["dozen_count"] > contract["max_open_dozen"]:
        raise ApiError(ERR_CONTRACT_VOLUME_EXCEEDED, 422, "Allocation would exceed max_open_dozen")
    lot["lifecycle_status"] = "ALLOCATED"
    lot["contract_id"] = contract["id"]
    touch(lot)
    touch(contract)
    return ok(pub(lot), status=200)


@bp.route("/api/lots/<lotId>/ship", methods=["POST"])
@endpoint(["ContractManager"])
def ship_lot(lotId, actor):
    lot = _get_lot(lotId)
    # Tier 6: lifecycle ALLOCATED -> SHIPPED.
    if lot["lifecycle_status"] != "ALLOCATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Lot must be ALLOCATED to ship")
    # Tier 9: hold gate.
    if lot["hold_status"] != "CLEAR":
        raise ApiError(ERR_LOT_QUALITY_HELD, 409, "Lot is quality held")
    # Tier 10: shelf life — equality ships on the last day.
    if today() > lot["sell_by_date"]:
        raise ApiError(ERR_SHELF_LIFE_EXCEEDED, 422, "Clock date is past sell_by_date")
    lot["lifecycle_status"] = "SHIPPED"
    lot["ship_date"] = today()
    touch(lot)
    contract = STORE["contracts"].get(lot.get("contract_id") or "")
    if contract is not None:
        touch(contract)
    return ok(pub(lot), status=200)
