"""Production batches: start, HACCP measurement, completion, release, reads."""

from flask import Blueprint

import clock
import db
import validate
from errors import fail
from middleware import PRODUCTION_SUPERVISOR, QA_OFFICER, actor, authenticate
from routes.helpers import created, guard_scope, one, resolve, simple_list
from services import calc, cascade
from timeutil import fmt_ms

bp = Blueprint("production", __name__)

BATCH_STATUSES = [
    "PLANNED", "IN_PRODUCTION", "HACCP_HOLD", "COMPLETED", "RELEASED",
    "REJECTED", "DISPOSED",
]
STORE_ZONES = ["CHILL", "HOT", "DRY"]
HACCP_STEPS = ["COOK_TEMP", "CHILL_DOWN", "HOLD_TEMP", "BLAST_CHILL"]


def batch_or_404(batch_id):
    return resolve("production_batches", batch_id, "ERR_BATCH_NOT_FOUND")


# ---------------------------------------------------------------------------
# start / restart


@bp.route("/production-batches/<batch_id>/start", methods=["POST"])
def start_batch(batch_id):
    authenticate(PRODUCTION_SUPERVISOR)
    validate.body([])
    batch = batch_or_404(batch_id)
    status = batch["production_status"]

    if status == "PLANNED":
        flight = db.get("flights", batch["flight_id"])
        if flight is None or flight["status"] != "PLANNED":
            fail("ERR_INVALID_BATCH_STATE")
    elif status != "HACCP_HOLD":
        fail("ERR_INVALID_BATCH_STATE")

    if clock.now() >= batch["_deadline"]:
        fail("ERR_RELEASE_DEADLINE_PASSED")

    if status == "HACCP_HOLD":
        batch["haccp_rework_rounds"] = batch["haccp_rework_rounds"] + 1
    batch["production_status"] = "IN_PRODUCTION"
    db.touch(batch)
    return one("production_batches", batch)


# ---------------------------------------------------------------------------
# HACCP measurement


@bp.route("/production-batches/<batch_id>/haccp-checks", methods=["POST"])
def record_check(batch_id):
    authenticate(QA_OFFICER)
    data = validate.body([
        ("step_code", {"type": "enum", "required": True, "values": HACCP_STEPS}),
        ("measured_temp_c", {
            "type": "number", "required": True,
            "min": -40.0, "max": 200.0, "decimals": 1,
        }),
    ])
    batch = batch_or_404(batch_id)
    if batch["production_status"] not in ("IN_PRODUCTION", "RELEASED"):
        fail("ERR_INVALID_BATCH_STATE")

    step = data["step_code"]
    existing = [
        c for c in db.where("haccp_checks", production_batch_id=batch["id"])
        if c["step_code"] == step
    ]
    verdict = calc.haccp_verdict(step, data["measured_temp_c"])
    now = clock.now()
    check = db.insert("haccp_checks", {
        "production_batch_id": batch["id"],
        "step_code": step,
        "measured_temp_c": data["measured_temp_c"],
        "measured_at_utc": fmt_ms(now),
        "verdict": verdict,
        "sequence_no": len(existing) + 1,
        "recorded_by_user_id": actor().user_id,
    }, common=False)

    if verdict == "FAIL":
        _apply_failure(batch)
    return created("haccp_checks", check)


def _apply_failure(batch):
    """The two FAIL branches: rework hold, pre-release scrap, or the cascade."""
    flight = db.get("flights", batch["flight_id"])
    airline_id = flight["airline_id"] if flight else None

    if batch["production_status"] == "RELEASED":
        cascade.reject_released_batch_cascade(batch)
        cascade.raise_finding(
            airline_id, batch["flight_id"], "HACCP_BREACH", "CRITICAL", "SYSTEM"
        )
        return

    if calc.fail_count(batch["id"]) <= calc.HACCP_MAX_FAILS:
        batch["production_status"] = "HACCP_HOLD"
        db.touch(batch)
        return

    cascade.reject_batch(batch)
    cascade.raise_finding(
        airline_id, batch["flight_id"], "HACCP_BREACH", "CRITICAL", "SYSTEM"
    )


# ---------------------------------------------------------------------------
# completion and release


@bp.route("/production-batches/<batch_id>/complete", methods=["POST"])
def complete_batch(batch_id):
    authenticate(PRODUCTION_SUPERVISOR)
    data = validate.body([("produced_qty", {"type": "int", "required": True, "min": 0})])
    batch = batch_or_404(batch_id)
    if batch["production_status"] != "IN_PRODUCTION":
        fail("ERR_INVALID_BATCH_STATE")
    if data["produced_qty"] > batch["planned_qty"]:
        fail("ERR_PRODUCED_QTY_EXCEEDS_PLAN")

    batch["produced_qty"] = data["produced_qty"]
    batch["scrapped_qty"] = batch["planned_qty"] - data["produced_qty"]
    batch["production_status"] = "COMPLETED"
    db.touch(batch)
    # PRD 3.5: completion recomputes the flight's units_produced,
    # units_scrapped and unit_balance; PRD 2.9 makes that a flight mutation.
    flight = db.get("flights", batch["flight_id"])
    if flight is not None:
        db.touch(flight)
    return one("production_batches", batch)


@bp.route("/production-batches/<batch_id>/release", methods=["POST"])
def release_batch(batch_id):
    authenticate(PRODUCTION_SUPERVISOR)
    validate.body([])
    batch = batch_or_404(batch_id)
    if batch["production_status"] != "COMPLETED":
        fail("ERR_INVALID_BATCH_STATE")

    spec = calc.spec_of_batch(batch)
    required = list(spec["required_haccp_steps"]) if spec else []

    latest = {}
    for step in required:
        latest[step] = calc.latest_check_for_step(batch["id"], step)
    if any(latest[step] is None for step in required):
        fail("ERR_HACCP_STEP_MISSING")
    if any(latest[step]["verdict"] == "FAIL" for step in required):
        fail("ERR_HACCP_HOLD_ACTIVE")
    if batch["haccp_rework_rounds"] >= calc.HACCP_MAX_REWORK_ROUNDS:
        fail("ERR_HACCP_REWORK_LIMIT")
    now = clock.now()
    if now > batch["_deadline"]:
        fail("ERR_RELEASE_DEADLINE_PASSED")

    batch["production_status"] = "RELEASED"
    batch["released_at"] = fmt_ms(now)
    batch["released_by_user_id"] = actor().user_id
    db.touch(batch)
    return one("production_batches", batch)


# ---------------------------------------------------------------------------
# reads


@bp.route("/production-batches", methods=["GET"])
def list_batches():
    authenticate()
    return simple_list("production_batches", {
        "flight_id": {"type": "string"},
        "meal_specification_id": {"type": "string"},
        "store_zone": {"type": "enum", "values": STORE_ZONES},
        "production_status": {"type": "enum", "values": BATCH_STATUSES},
        "is_overflow": {"type": "bool"},
    })


@bp.route("/production-batches/<batch_id>", methods=["GET"])
def read_batch(batch_id):
    authenticate()
    batch = batch_or_404(batch_id)
    guard_scope("production_batches", batch)
    return one("production_batches", batch)


@bp.route("/haccp-checks", methods=["GET"])
def list_checks():
    authenticate()
    return simple_list("haccp_checks", {
        "production_batch_id": {"type": "string"},
        "step_code": {"type": "enum", "values": HACCP_STEPS},
        "verdict": {"type": "enum", "values": ["PASS", "FAIL"]},
    })


@bp.route("/haccp-checks/<check_id>", methods=["GET"])
def read_check(check_id):
    authenticate()
    return one("haccp_checks", resolve("haccp_checks", check_id))
