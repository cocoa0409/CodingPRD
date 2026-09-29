"""PRD 3.6 - print vendors and the three dimensions of a proof."""
from datetime import timedelta

from flask import Blueprint, request

import calc
from cascade import refresh_proof_state
from core import db, dec, fmt_dt, new_row, parse_dt, rows, touch
from errors import fail, invalid
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    created,
    filter_exists,
    load,
    need_code_array,
    need_datetime,
    need_enum,
    need_int,
    need_nonempty,
    need_number,
    need_string,
    ok,
    paginate,
    query_bool,
    raw_body,
)
from serialize import printer_json, proof_json

bp = Blueprint("printers", __name__)


@bp.route("/printers", methods=["POST"])
def create_printer():
    auth(["PlatformAdmin"])
    body = body_fields(
        ["name", "color_standard", "certified_substrates", "recovery_liability_cap_cents"]
    )
    name = need_string(body, "name", 3, 80)
    color_standard = need_enum(body, "color_standard", calc.COLOR_STANDARDS)
    substrates = need_code_array(
        body, "certified_substrates", None, 1, 4, members=calc.SUBSTRATE_CLASSES
    )
    cap = need_int(body, "recovery_liability_cap_cents", 0)

    for existing in rows("printers"):
        if existing["name"] == name:
            fail("ERR_DUPLICATE_PRINTER_NAME", "printer name %s is already registered" % name)

    row = new_row(
        "printers",
        {
            "name": name,
            "color_standard": color_standard,
            "certified_substrates": substrates,
            "recovery_liability_cap_cents": cap,
            "certification_status": "CERTIFIED",
            "performance_score": dec("100.0"),
        },
    )
    return created(printer_json(row))


@bp.route("/printers/<printer_id>", methods=["GET"])
def get_printer(printer_id):
    auth(ALL_ROLES)
    return ok(printer_json(load("printers", printer_id)))


@bp.route("/printers", methods=["GET"])
def list_printers():
    auth(ALL_ROLES)
    items = rows("printers")
    status = request.args.get("certification_status")
    if status:
        items = [p for p in items if p["certification_status"] == status]
    items = sorted(items, key=lambda p: (p["name"], p["created_at"], p["_seq"]))
    return paginate(items, printer_json)


# ------------------------------------------------------------------ proofs
@bp.route("/printer-proofs", methods=["POST"])
def create_proof():
    user_id, _role = auth(["PrinterRep"])
    raw = raw_body()
    version = None
    version_ref = raw.get("artwork_version_id")
    if isinstance(version_ref, str) and version_ref:
        version = load("versions", version_ref)
    printer = None
    printer_ref = raw.get("printer_id")
    if isinstance(printer_ref, str) and printer_ref:
        printer = load("printers", printer_ref)

    if printer is not None and printer["id"] != user_id:
        fail(
            "ERR_PRINTER_IDENTITY_MISMATCH",
            "a PrinterRep may only submit proofs for its own vendor",
        )

    body = body_fields(["artwork_version_id", "printer_id", "substrate_code"], ["proof_note"])
    need_nonempty(body, "artwork_version_id")
    need_nonempty(body, "printer_id")
    substrate_code = need_enum(body, "substrate_code", calc.SUBSTRATE_CLASSES)
    note = body.get("proof_note")
    if note is not None and not isinstance(note, str):
        invalid("proof_note must be a string")

    version = load("versions", body["artwork_version_id"])
    printer = load("printers", body["printer_id"])
    if printer["id"] != user_id:
        fail(
            "ERR_PRINTER_IDENTITY_MISMATCH",
            "a PrinterRep may only submit proofs for its own vendor",
        )

    if version["state"] not in ("APPROVED", "RELEASED_TO_PRINT"):
        fail("ERR_VERSION_STATE_INVALID", "only an APPROVED or RELEASED_TO_PRINT version may be proofed")
    if substrate_code not in printer["certified_substrates"]:
        fail("ERR_SUBSTRATE_NOT_CERTIFIED", "the vendor is not certified for %s" % substrate_code)
    if printer["certification_status"] != "CERTIFIED":
        fail("ERR_PRINTER_ON_PROBATION", "a vendor on PROBATION may not submit proofs")

    asset = db.assets[version["artwork_asset_id"]]
    proof_no = len([p for p in rows("proofs") if p["artwork_version_id"] == version["id"]]) + 1
    press_required = bool(asset["brand_critical_color"]) or substrate_code == "FILM"
    row = new_row(
        "proofs",
        {
            "artwork_version_id": version["id"],
            "printer_id": printer["id"],
            "substrate_code": substrate_code,
            "proof_no": proof_no,
            "proof_note": note,
            "color_status": "COLOR_PENDING",
            "substrate_status": "SUBSTRATE_PENDING",
            "press_check_status": "PRESS_CHECK_REQUIRED" if press_required else "NOT_REQUIRED",
            "press_check_required": press_required,
            "proof_state": "PROOF_IN_REVIEW",
            "requires_recheck": False,
            "effective_tolerance": calc.effective_tolerance(
                printer["color_standard"], substrate_code, asset["brand_critical_color"]
            ),
            "measured_delta_e_max": None,
            "press_line_code": None,
            "press_check_start_utc": None,
            "press_check_end_utc": None,
            "attended_by_user_id": None,
        },
    )
    row["proof_state"] = calc.derive_proof_state(row)
    return created(proof_json(row))


@bp.route("/printer-proofs/<proof_id>", methods=["GET"])
def get_proof(proof_id):
    auth(ALL_ROLES)
    return ok(proof_json(load("proofs", proof_id)))


@bp.route("/printer-proofs", methods=["GET"])
def list_proofs():
    auth(ALL_ROLES)
    version_id = filter_exists("versions", "artwork_version_id")
    printer_id = filter_exists("printers", "printer_id")
    items = rows("proofs")
    if version_id:
        items = [p for p in items if p["artwork_version_id"] == version_id]
    if printer_id:
        items = [p for p in items if p["printer_id"] == printer_id]
    proof_state = request.args.get("proof_state")
    if proof_state:
        items = [p for p in items if p["proof_state"] == proof_state]
    requires_recheck = query_bool("requires_recheck")
    if requires_recheck is not None:
        items = [p for p in items if p["requires_recheck"] == requires_recheck]
    items = sorted(items, key=lambda p: (p["proof_no"], p["created_at"], p["_seq"]))
    return paginate(items, proof_json)


def _assert_writable(proof):
    if proof["proof_state"] in ("PROOF_APPROVED", "PROOF_REJECTED"):
        fail("ERR_PROOF_STATE_INVALID", "a terminal proof is closed to further dimension writes")


@bp.route("/printer-proofs/<proof_id>/color-decision", methods=["POST"])
def color_decision(proof_id):
    auth(["QualityReviewer"])
    proof = load("proofs", proof_id)
    body = body_fields(["measured_delta_e_max"])
    measured = need_number(body, "measured_delta_e_max", 0)

    _assert_writable(proof)
    if proof["color_status"] != "COLOR_PENDING":
        fail("ERR_PROOF_DIMENSION_ALREADY_DECIDED", "the colour dimension is already decided")

    value = dec(measured)
    proof["measured_delta_e_max"] = value
    # The comparison against effective_tolerance is inclusive (PRD 3.6).
    proof["color_status"] = "COLOR_PASS" if value <= proof["effective_tolerance"] else "COLOR_FAIL"
    refresh_proof_state(proof)
    return ok(proof_json(proof))


@bp.route("/printer-proofs/<proof_id>/substrate-decision", methods=["POST"])
def substrate_decision(proof_id):
    auth(["QualityReviewer"])
    proof = load("proofs", proof_id)
    body = body_fields(["decision"])
    decision = need_enum(body, "decision", ("SUBSTRATE_APPROVED", "SUBSTRATE_REJECTED"))

    _assert_writable(proof)
    if proof["substrate_status"] != "SUBSTRATE_PENDING":
        fail("ERR_PROOF_DIMENSION_ALREADY_DECIDED", "the substrate dimension is already decided")

    proof["substrate_status"] = decision
    refresh_proof_state(proof)
    return ok(proof_json(proof))


@bp.route("/printer-proofs/<proof_id>/press-check", methods=["POST"])
def press_check(proof_id):
    auth(["QualityReviewer"])
    proof = load("proofs", proof_id)
    body = body_fields(
        ["press_line_code", "press_check_start_utc", "press_check_end_utc"],
        ["attended_by_user_id"],
    )
    press_line_code = need_nonempty(body, "press_line_code")
    start = need_datetime(body, "press_check_start_utc")
    end = need_datetime(body, "press_check_end_utc")
    if not end > start:
        invalid("press_check_end_utc must be strictly after press_check_start_utc")
    attended = body.get("attended_by_user_id")
    if attended is not None and (not isinstance(attended, str) or not attended.strip()):
        invalid("attended_by_user_id must be a non-empty string when supplied")

    _assert_writable(proof)
    if proof["press_check_status"] not in ("PRESS_CHECK_REQUIRED", "PRESS_CHECK_SCHEDULED"):
        fail("ERR_PRESS_CHECK_NOT_REQUIRED", "the press-check track does not admit a write")

    buffer = timedelta(minutes=calc.PRESS_CHECK_BUFFER_MINUTES)
    widened_start = start - buffer
    widened_end = end + buffer
    for other in rows("proofs"):
        if other["id"] == proof["id"]:
            continue
        if other["printer_id"] != proof["printer_id"]:
            continue
        if other.get("press_line_code") != press_line_code:
            continue
        if other["press_check_status"] not in ("PRESS_CHECK_SCHEDULED", "PRESS_CHECK_ATTENDED"):
            continue
        other_start = parse_dt(other.get("press_check_start_utc"))
        other_end = parse_dt(other.get("press_check_end_utc"))
        if other_start is None or other_end is None:
            continue
        if widened_start < other_end + buffer and other_start - buffer < widened_end:
            fail(
                "ERR_PRESS_CHECK_OVERLAP",
                "the requested window collides with another booking on this press line",
            )

    proof["press_line_code"] = press_line_code
    proof["press_check_start_utc"] = fmt_dt(start)
    proof["press_check_end_utc"] = fmt_dt(end)
    if attended is not None:
        proof["attended_by_user_id"] = attended
        proof["press_check_status"] = "PRESS_CHECK_ATTENDED"
    else:
        proof["press_check_status"] = "PRESS_CHECK_SCHEDULED"
    refresh_proof_state(proof)
    return ok(proof_json(proof))
