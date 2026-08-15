"""Crimp pull tests: first-article qualification and lot-sample tripwire (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (raise_error, ERR_FIRST_ARTICLE_PREREQUISITE,
                    ERR_APPLICATOR_NOT_QUALIFIED, ERR_OPERATOR_NOT_CERTIFIED,
                    ERR_APPLICATOR_PROGRAM_MISMATCH)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import (SAMPLE_KINDS, record_fields, has_active_cert,
                      apply_first_article_pass, apply_lot_sample_fail,
                      ser_pull_test, paginated)
from util import CLOCK, dec
from validate import get_body, req_str, req_num, req_enum, require_path, require_fk

bp = Blueprint("crimp_pull_tests", __name__)

QUALITY_INSPECTOR = {"QualityInspector"}


@bp.route("/plant/crimp-pull-tests", methods=["POST"])
def create_pull_test():
    body = get_body()
    # Tier 1
    applicator_id = req_str(body, "applicator_id")
    program_id = req_str(body, "program_id")
    sample_kind = req_enum(body, "sample_kind", SAMPLE_KINDS)
    measured_force_n = req_num(body, "measured_force_n")
    # Tiers 2-3
    caller = authenticate(QUALITY_INSPECTOR)
    # Tier 4, left-to-right
    applicator = require_fk("applicators", applicator_id, "applicator_id")
    program = require_fk("machine_programs", program_id, "program_id")
    # Tier 6: tooling preconditions per sample kind
    if sample_kind == "FIRST_ARTICLE":
        closed_setup_exists = any(
            s["applicator_id"] == applicator["id"]
            and s["program_id"] == program["id"]
            and s["status"] == "CLOSED"
            for s in db["applicator_setups"].values())
        if (applicator["status"] != "AVAILABLE"
                or applicator["current_program_id"] != program["id"]
                or not closed_setup_exists
                or program["status"] not in ("DRAFT", "HELD")):
            raise_error(ERR_FIRST_ARTICLE_PREREQUISITE,
                        "FIRST_ARTICLE requires applicator AVAILABLE with the program "
                        "loaded, a CLOSED setup for the pair, and program DRAFT or HELD")
    else:  # LOT_SAMPLE
        if applicator["status"] != "QUALIFIED":
            raise_error(ERR_APPLICATOR_NOT_QUALIFIED,
                        "LOT_SAMPLE requires a QUALIFIED applicator")
    # Tier 7: certification gate on the program's drawing's workmanship class.
    drawing = db["drawings"][program["drawing_id"]]
    if not has_active_cert(caller.user_id, drawing["workmanship_class"]):
        raise_error(ERR_OPERATOR_NOT_CERTIFIED,
                    "acting inspector lacks an ACTIVE certification for the "
                    "program's drawing class")
    # Tier 8: a lot sample must reference the program actually loaded.
    if sample_kind == "LOT_SAMPLE" and applicator["current_program_id"] != program["id"]:
        raise_error(ERR_APPLICATOR_PROGRAM_MISMATCH,
                    "LOT_SAMPLE program_id != applicator.current_program_id")

    snapshot = program["min_pull_force_n"]
    result = "PASS" if dec(measured_force_n) >= dec(snapshot) else "FAIL"

    record = record_fields()
    record.update({
        "applicator_id": applicator["id"],
        "program_id": program["id"],
        "operator_id": caller.user_id,
        "sample_kind": sample_kind,
        "measured_force_n": float(measured_force_n),
        "min_pull_force_n_snapshot": snapshot,
        "result": result,
        "tested_at": CLOCK.now(),
    })
    db["crimp_pull_tests"][record["id"]] = record

    if sample_kind == "FIRST_ARTICLE" and result == "PASS":
        apply_first_article_pass(applicator, program)
    elif sample_kind == "LOT_SAMPLE" and result == "FAIL":
        apply_lot_sample_fail(applicator)

    return success_object(ser_pull_test(record), 201)


@bp.route("/plant/crimp-pull-tests/<tid>", methods=["GET"])
def get_pull_test(tid):
    authenticate(ALL_ROLES)
    record = require_path("crimp_pull_tests", tid)
    return success_object(ser_pull_test(record), 200)


@bp.route("/plant/crimp-pull-tests", methods=["GET"])
def list_pull_tests():
    authenticate(ALL_ROLES)
    items = list(db["crimp_pull_tests"].values())
    applicator_id = request.args.get("applicator_id")
    if applicator_id is not None:
        items = [t for t in items if t["applicator_id"] == applicator_id]
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [t for t in items if t["program_id"] == program_id]
    operator_id = request.args.get("operator_id")
    if operator_id is not None:
        items = [t for t in items if t["operator_id"] == operator_id]
    return paginated(items, ser_pull_test)
