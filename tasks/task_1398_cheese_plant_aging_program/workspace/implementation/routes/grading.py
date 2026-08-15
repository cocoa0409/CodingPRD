"""Grading events: first grading, re-grade chain, condemnation cascade
(PRD 3.7)."""

from flask import request

from calc import assign_grade
from db import STORES, new_record, now, touch
from errors import ApiError, invalid_state
from helpers import auth, body, f_int, f_num, f_str, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp
from services import condemn_batch, unit_age_days

bp = make_bp("grading_events")

GET_ROLES = ("PlantAdmin", "QAGrader")


def _latest_grading_event(batch_id):
    events = [e for e in STORES["grading_events"].values() if e["cheese_batch_id"] == batch_id]
    if not events:
        return None
    return max(events, key=lambda e: e["_seq"])


@bp.post("/plant/grading-events")
def create_grading_event():
    uid, _role = auth("QAGrader")
    b = body()
    cheese_batch_id = f_str(b, "cheese_batch_id")
    moisture_pct = f_num(b, "moisture_pct")
    fat_dry_basis_pct = f_num(b, "fat_dry_basis_pct")
    body_score = f_int(b, "body_score")
    flavor_score = f_int(b, "flavor_score")
    if not 1 <= body_score <= 10 or not 1 <= flavor_score <= 10:
        from errors import invalid_request

        invalid_request("body_score and flavor_score must be integers from 1 to 10")
    batch = get_or_404("cheese_batches", cheese_batch_id, "cheese batch")
    # State gate: terminal or released batches may not be (re-)graded.
    if batch["status"] in ("CONDEMNED", "RELEASED", "ALLOCATED"):
        invalid_state("Batch may not be graded in its current state")
    if batch["status"] == "GRADED" and batch["release_decision"] != "PENDING":
        invalid_state("A released batch may not be re-graded")
    # Rung 7: segregation of duties — the grader must be independent of the
    # make; a grader in the make sheet's step_signer_ids is rejected.
    make_sheet = STORES["make_sheets"].get(batch["make_sheet_id"])
    if make_sheet is not None and uid in make_sheet["step_signer_ids"]:
        raise ApiError(
            "ERR_SOLE_OPERATOR",
            422,
            "Grader signed a make step on the originating make sheet",
        )
    if batch["status"] in ("GREEN", "AGING"):
        # First-grading gates (rungs 8 then 10): every produced wheel must
        # rest in the cellar, then the youngest IN_ROOM unit must meet the
        # variety minimum age (== passes).
        if batch["wheels_placed"] != batch["wheels_produced"]:
            raise ApiError(
                "ERR_WHEELS_UNPLACED",
                409,
                "Grading attempted before all produced wheels are placed in aging",
            )
        in_room = [
            u
            for u in STORES["aging_units"].values()
            if u["cheese_batch_id"] == batch["id"] and u["status"] == "IN_ROOM"
        ]
        youngest = min((unit_age_days(u) for u in in_room), default=0)
        if youngest < batch["min_age_days"]:
            raise ApiError(
                "ERR_AGE_MINIMUM_NOT_MET",
                422,
                "Youngest aging unit has not reached the variety minimum age",
            )
    grade = assign_grade(
        batch["variety"], moisture_pct, fat_dry_basis_pct, body_score, flavor_score
    )
    prior = _latest_grading_event(batch["id"])
    rec = new_record()
    rec.update(
        plant_id=batch["plant_id"],
        cheese_batch_id=batch["id"],
        grader_user_id=uid,
        moisture_pct=moisture_pct,
        fat_dry_basis_pct=fat_dry_basis_pct,
        body_score=body_score,
        flavor_score=flavor_score,
        assigned_grade=grade,
        graded_at=now(),
        supersedes_grading_event_id=prior["id"] if prior else None,
    )
    STORES["grading_events"][rec["id"]] = rec
    batch["moisture_pct"] = moisture_pct
    batch["fat_dry_basis_pct"] = fat_dry_basis_pct
    batch["current_grade"] = grade
    if grade == "CONDEMNED":
        condemn_batch(batch)
    else:
        batch["status"] = "GRADED"
    touch(batch)
    return success(serialize(rec), 201)


@bp.get("/plant/grading-events/<gradingEventId>")
def get_grading_event(gradingEventId):
    auth(*GET_ROLES)
    rec = get_or_404("grading_events", gradingEventId, "grading event")
    return success(serialize(rec))


@bp.get("/plant/grading-events")
def list_grading_events():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "grading_events",
        [
            ("plant_id", request.args.get("plant_id")),
            ("cheese_batch_id", request.args.get("cheese_batch_id")),
            ("supersedes_grading_event_id", request.args.get("supersedes_grading_event_id")),
        ],
        serialize,
    )
    return success(data, 200, pagination)
