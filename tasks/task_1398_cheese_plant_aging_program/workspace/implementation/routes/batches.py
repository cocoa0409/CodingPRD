"""Cheese batch reads, release, and allocation preview (PRD 3.7, 3.8)."""

from flask import request

from db import STORES, touch
from errors import ApiError, invalid_state
from helpers import auth, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp

bp = make_bp("cheese_batches")

GET_ROLES = (
    "PlantAdmin",
    "MakePlanner",
    "Cheesemaker",
    "QAGrader",
    "AgingRoomOperator",
    "SalesPlanner",
    "CutWrapOperator",
    "ComplianceOfficer",
)


@bp.get("/plant/cheese-batches/<cheeseBatchId>")
def get_batch(cheeseBatchId):
    auth(*GET_ROLES)
    rec = get_or_404("cheese_batches", cheeseBatchId, "cheese batch")
    return success(serialize(rec))


@bp.get("/plant/cheese-batches")
def list_batches():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "cheese_batches",
        [
            ("plant_id", request.args.get("plant_id")),
            ("make_sheet_id", request.args.get("make_sheet_id")),
            ("variety", request.args.get("variety")),
            ("status", request.args.get("status")),
            ("current_grade", request.args.get("current_grade")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.post("/plant/cheese-batches/<cheeseBatchId>/release")
def release_batch(cheeseBatchId):
    auth("QAGrader")
    from helpers import body as _body

    _body(required=False)
    rec = get_or_404("cheese_batches", cheeseBatchId, "cheese batch")
    if rec["status"] != "GRADED" or rec["release_decision"] != "PENDING":
        invalid_state("Only a GRADED batch with a PENDING release decision may be released")
    if rec["current_grade"] not in ("GRADE_A", "GRADE_B"):
        raise ApiError(
            "ERR_GRADE_NOT_RELEASABLE",
            409,
            "Only GRADE_A and GRADE_B batches are releasable",
        )
    rec["release_decision"] = "RELEASED"
    rec["status"] = "RELEASED"
    touch(rec)
    return success(serialize(rec))


@bp.get("/plant/cheese-batches/<cheeseBatchId>/allocation-preview")
def allocation_preview(cheeseBatchId):
    auth("PlantAdmin", "SalesPlanner", "QAGrader")
    batch = get_or_404("cheese_batches", cheeseBatchId, "cheese batch")
    # Candidate set: this batch's orders in OPEN or PARTIALLY_FILLED, ranked
    # by priority ascending, ties broken by created_at ascending (earliest
    # first, never by identifier); creation sequence breaks exact ties.
    candidates = [
        o
        for o in STORES["allocation_orders"].values()
        if o["cheese_batch_id"] == batch["id"] and o["status"] in ("OPEN", "PARTIALLY_FILLED")
    ]
    candidates.sort(key=lambda o: (o["priority"], o["created_at"], o["_seq"]))
    # Wheel pool per PRD 3.8.
    pool = (
        batch["wheels_produced"]
        - batch["wheels_placed"]
        - sum(o["wheels_cut"] for o in candidates)
    )
    order_sequence = []
    wheels_allocated = []
    for o in candidates:
        need = o["wheels_requested"] - o["wheels_cut"]
        alloc = min(need, pool)
        if alloc < 0:
            alloc = 0
        order_sequence.append(o["id"])
        wheels_allocated.append(alloc)
        pool -= alloc
    return success({"order_sequence": order_sequence, "wheels_allocated": wheels_allocated})
