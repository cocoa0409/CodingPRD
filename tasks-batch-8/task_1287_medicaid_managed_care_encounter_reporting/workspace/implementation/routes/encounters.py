"""Encounter routes: intake, validate, correct, replace, void, lines, findings."""
from flask import Blueprint, request

from db import store, new_id, now_iso
from middleware import (
    get_auth, require_role, get_body, req_string, req_int, opt_string,
    apply_pagination, invalid_request, forbidden,
)
from response import success_object, success_list
from errors import not_found, invalid_state, ApiError
from services.core import (
    parse_date, touch, validate_lines, validate_line_sanity, validate_header_lines, attribute_cycle,
    check_ref_unique, run_validation, recompute_cycle_tallies,
    encounter_view, line_view, finding_view, get_scorecard,
)

bp = Blueprint("encounters", __name__)


def _build_lines(encounter_id, lines_payload):
    lines = []
    for lp in lines_payload:
        lid = new_id()
        line = {
            "id": lid,
            "created_at": now_iso(),
            "encounter_id": encounter_id,
            "line_number": lp["line_number"],
            "procedure_code": lp["procedure_code"],
            "modifiers": list(lp.get("modifiers") or []),
            "units": lp["units"],
            "billed_amount_cents": lp["billed_amount_cents"],
            "paid_amount_cents": lp["paid_amount_cents"],
        }
        store.encounter_lines[lid] = line
        lines.append(line)
    return lines


def _parse_encounter_payload(body):
    """Parse + validate encounter payload fields (well-formedness stage). Returns dict."""
    program_id = req_string(body, "program_id")
    member_id = req_string(body, "member_id")
    provider_id = req_string(body, "provider_id")
    encounter_ref = req_string(body, "encounter_ref")
    service_from_s = req_string(body, "service_from_date")
    service_to_s = req_string(body, "service_to_date")
    place_of_service = req_string(body, "place_of_service")
    diagnosis_codes = body.get("diagnosis_codes")
    if not isinstance(diagnosis_codes, list) or any(not isinstance(c, str) for c in diagnosis_codes):
        raise invalid_request("diagnosis_codes must be an array of strings")
    paid_amount_cents = req_int(body, "paid_amount_cents")
    if paid_amount_cents < 0:
        raise invalid_request("paid_amount_cents must not be negative")
    lines = body.get("lines")
    if not isinstance(lines, list):
        raise invalid_request("lines must be an array")
    validate_lines(lines)
    return {
        "program_id": program_id,
        "member_id": member_id,
        "provider_id": provider_id,
        "encounter_ref": encounter_ref,
        "service_from_s": service_from_s,
        "service_to_s": service_to_s,
        "place_of_service": place_of_service,
        "diagnosis_codes": diagnosis_codes,
        "paid_amount_cents": paid_amount_cents,
        "lines": lines,
    }


@bp.route("/programs/encounters", methods=["POST"])
def create_encounter():
    user_id, role = get_auth()
    require_role(role, {"McoEncounterOps", "DelegatedSubmitter"})
    body = get_body()
    parsed = _parse_encounter_payload(body)
    submitter_id = body.get("submitter_id")
    if submitter_id is not None and not isinstance(submitter_id, str):
        raise invalid_request("submitter_id must be a string")
    # DelegatedSubmitter: submitter_id required and must equal X-User-ID
    if role == "DelegatedSubmitter":
        if submitter_id is None:
            raise forbidden("DelegatedSubmitter must act with submitter_id equal to X-User-ID")
        if submitter_id != user_id:
            raise forbidden("DelegatedSubmitter may only act with submitter_id == X-User-ID")
    # existence
    if parsed["program_id"] not in store.programs:
        raise not_found("program not found")
    member = store.members.get(parsed["member_id"])
    if member is None:
        raise not_found("member not found")
    provider = store.providers.get(parsed["provider_id"])
    if provider is None:
        raise not_found("provider not found")
    submitter = None
    if submitter_id is not None:
        submitter = store.submitters.get(submitter_id)
        if submitter is None:
            raise not_found("submitter not found")
    # suspended-party gates
    if provider["contract_status"] == "SUSPENDED":
        raise ApiError("ERR_PROVIDER_SUSPENDED", "Encounter create names a SUSPENDED provider", 409)
    if submitter is not None and submitter["status"] == "SUSPENDED":
        raise ApiError("ERR_SUBMITTER_SUSPENDED", "Encounter create carries a SUSPENDED submitter", 409)
    # cycle attribution
    sfd = parse_date(parsed["service_from_s"], "service_from_date")
    std = parse_date(parsed["service_to_s"], "service_to_date")
    cycle = attribute_cycle(parsed["program_id"], sfd)
    # fiscal checks
    validate_header_lines(parsed["paid_amount_cents"], parsed["lines"])
    validate_line_sanity(parsed["lines"])
    # ref uniqueness
    check_ref_unique(parsed["program_id"], submitter_id, parsed["encounter_ref"])

    eid = new_id()
    e = {
        "id": eid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "program_id": parsed["program_id"],
        "member_id": parsed["member_id"],
        "provider_id": parsed["provider_id"],
        "submitter_id": submitter_id,
        "attributed_cycle_id": cycle["id"],
        "batch_id": None,
        "replaces_encounter_id": None,
        "encounter_ref": parsed["encounter_ref"],
        "service_from_date": parsed["service_from_s"],
        "service_to_date": parsed["service_to_s"],
        "place_of_service": parsed["place_of_service"],
        "diagnosis_codes": list(parsed["diagnosis_codes"]),
        "paid_amount_cents": parsed["paid_amount_cents"],
        "correction_sequence": 0,
        "validation_run_seq": 0,
        "status": "RECEIVED",
        "_service_from_date": sfd,
        "_service_to_date": std,
        "_lines": [],
    }
    e["_lines"] = _build_lines(eid, parsed["lines"])
    store.encounters[eid] = e
    recompute_cycle_tallies(cycle)
    return success_object(encounter_view(e), 201)


@bp.route("/programs/encounters/<eid>", methods=["GET"])
def get_encounter(eid):
    get_auth()
    e = store.encounters.get(eid)
    if e is None:
        raise not_found()
    return success_object(encounter_view(e))


@bp.route("/programs/encounters", methods=["GET"])
def list_encounters():
    get_auth()
    filters = {
        "program_id": request.args.get("program_id"),
        "member_id": request.args.get("member_id"),
        "provider_id": request.args.get("provider_id"),
        "submitter_id": request.args.get("submitter_id"),
        "attributed_cycle_id": request.args.get("attributed_cycle_id"),
        "batch_id": request.args.get("batch_id"),
        "replaces_encounter_id": request.args.get("replaces_encounter_id"),
        "status": request.args.get("status"),
    }
    items = list(store.encounters.values())
    for k, v in filters.items():
        if v is not None:
            items = [e for e in items if e.get(k) == v]
    page, limit, offset, total = apply_pagination(items)
    return success_list([encounter_view(e) for e in page], limit, offset, total)


@bp.route("/programs/encounters/<eid>/lines", methods=["GET"])
def list_lines(eid):
    get_auth()
    e = store.encounters.get(eid)
    if e is None:
        raise not_found()
    items = list(e["_lines"])
    page, limit, offset, total = apply_pagination(items)
    return success_list([line_view(l) for l in page], limit, offset, total)


@bp.route("/programs/encounters/<eid>/findings", methods=["GET"])
def list_findings(eid):
    get_auth()
    e = store.encounters.get(eid)
    if e is None:
        raise not_found()
    run_seq = request.args.get("run_seq")
    severity = request.args.get("severity")
    items = [f for f in store.findings.values() if f["encounter_id"] == eid]
    if run_seq is not None:
        try:
            rs = int(run_seq)
        except ValueError:
            raise invalid_request("run_seq must be an integer")
        items = [f for f in items if f["run_seq"] == rs]
    if severity is not None:
        items = [f for f in items if f["severity"] == severity]
    page, limit, offset, total = apply_pagination(items)
    return success_list([finding_view(f) for f in page], limit, offset, total)


@bp.route("/programs/encounters/<eid>/validate", methods=["POST"])
def validate_encounter(eid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    get_body(required=False)
    e = store.encounters.get(eid)
    if e is None:
        raise not_found()
    if e["status"] != "RECEIVED":
        raise invalid_state("Encounter is not RECEIVED")
    fatal = run_validation(e)
    e["status"] = "VALIDATED" if fatal == 0 else "REJECTED"
    touch(e)
    return success_object(encounter_view(e))


@bp.route("/programs/encounters/<eid>/correct", methods=["POST"])
def correct_encounter(eid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    body = get_body()
    e = store.encounters.get(eid)
    if e is None:
        raise not_found()
    if e["status"] != "REJECTED":
        raise invalid_state("Encounter is not REJECTED")

    # Parse corrected fields (well-formedness)
    new_sfd = e["_service_from_date"]
    new_sfd_s = e["service_from_date"]
    new_std = e["_service_to_date"]
    new_std_s = e["service_to_date"]
    new_pos = e["place_of_service"]
    new_diag = e["diagnosis_codes"]
    new_paid = e["paid_amount_cents"]
    new_lines_payload = None

    if "service_from_date" in body and body["service_from_date"] is not None:
        new_sfd_s = req_string(body, "service_from_date")
        new_sfd = parse_date(new_sfd_s, "service_from_date")
    if "service_to_date" in body and body["service_to_date"] is not None:
        new_std_s = req_string(body, "service_to_date")
        new_std = parse_date(new_std_s, "service_to_date")
    if "place_of_service" in body and body["place_of_service"] is not None:
        new_pos = req_string(body, "place_of_service")
    if "diagnosis_codes" in body and body["diagnosis_codes"] is not None:
        new_diag = body["diagnosis_codes"]
        if not isinstance(new_diag, list) or any(not isinstance(c, str) for c in new_diag):
            raise invalid_request("diagnosis_codes must be an array of strings")
    if "paid_amount_cents" in body and body["paid_amount_cents"] is not None:
        new_paid = req_int(body, "paid_amount_cents")
        if new_paid < 0:
            raise invalid_request("paid_amount_cents must not be negative")
    if "lines" in body and body["lines"] is not None:
        new_lines_payload = body["lines"]
        if not isinstance(new_lines_payload, list):
            raise invalid_request("lines must be an array")
        validate_lines(new_lines_payload)

    # Attribution re-check (referential business rule)
    cycle = attribute_cycle(e["program_id"], new_sfd)
    # Fiscal checks over corrected values
    lines_for_check = new_lines_payload if new_lines_payload is not None else e["_lines"]
    validate_header_lines(new_paid, lines_for_check)
    validate_line_sanity(lines_for_check)

    # Apply corrections
    e["service_from_date"] = new_sfd_s
    e["_service_from_date"] = new_sfd
    e["service_to_date"] = new_std_s
    e["_service_to_date"] = new_std
    e["place_of_service"] = new_pos
    e["diagnosis_codes"] = list(new_diag)
    e["paid_amount_cents"] = new_paid
    if new_lines_payload is not None:
        for l in e["_lines"]:
            store.encounter_lines.pop(l["id"], None)
        e["_lines"] = _build_lines(e["id"], new_lines_payload)

    old_cycle_id = e["attributed_cycle_id"]
    e["attributed_cycle_id"] = cycle["id"]

    fatal = run_validation(e)
    e["status"] = "VALIDATED" if fatal == 0 else "REJECTED"
    touch(e)
    if old_cycle_id != cycle["id"]:
        old_cycle = store.cycles.get(old_cycle_id)
        if old_cycle is not None:
            recompute_cycle_tallies(old_cycle)
        recompute_cycle_tallies(cycle)
    return success_object(encounter_view(e))


@bp.route("/programs/encounters/<eid>/replace", methods=["POST"])
def replace_encounter(eid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    body = get_body()
    parsed = _parse_encounter_payload_minimal(body)
    e = store.encounters.get(eid)
    if e is None:
        raise not_found()
    if e["status"] not in ("DENIED", "ACKNOWLEDGED"):
        raise ApiError("ERR_ENCOUNTER_NOT_REPLACEABLE",
                       "Replace attempted from a status outside {DENIED, ACKNOWLEDGED}", 409)

    sfd = parse_date(parsed["service_from_s"], "service_from_date")
    std = parse_date(parsed["service_to_s"], "service_to_date")
    cycle = attribute_cycle(e["program_id"], sfd)
    validate_header_lines(parsed["paid_amount_cents"], parsed["lines"])
    validate_line_sanity(parsed["lines"])
    # ref uniqueness within (program, submitter scope); exclude the original being superseded
    check_ref_unique(e["program_id"], e.get("submitter_id"), parsed["encounter_ref"], exclude_id=e["id"])

    was_acknowledged = e["status"] == "ACKNOWLEDGED"
    old_cycle = store.cycles.get(e["attributed_cycle_id"])

    # supersede original
    e["status"] = "SUPERSEDED"
    touch(e)

    # create replacement
    nid = new_id()
    replacement = {
        "id": nid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "program_id": e["program_id"],
        "member_id": e["member_id"],
        "provider_id": e["provider_id"],
        "submitter_id": e.get("submitter_id"),
        "attributed_cycle_id": cycle["id"],
        "batch_id": None,
        "replaces_encounter_id": e["id"],
        "encounter_ref": parsed["encounter_ref"],
        "service_from_date": parsed["service_from_s"],
        "service_to_date": parsed["service_to_s"],
        "place_of_service": parsed["place_of_service"],
        "diagnosis_codes": list(parsed["diagnosis_codes"]),
        "paid_amount_cents": parsed["paid_amount_cents"],
        "correction_sequence": e["correction_sequence"] + 1,
        "validation_run_seq": 0,
        "status": "RECEIVED",
        "_service_from_date": sfd,
        "_service_to_date": std,
        "_lines": [],
    }
    replacement["_lines"] = _build_lines(nid, parsed["lines"])
    store.encounters[nid] = replacement

    # ledger compensation + intake tallies
    if old_cycle is not None:
        recompute_cycle_tallies(old_cycle)
    if cycle["id"] != (old_cycle["id"] if old_cycle else None):
        recompute_cycle_tallies(cycle)

    return success_object(encounter_view(replacement), 201)


def _parse_encounter_payload_minimal(body):
    """Parse the replace payload (no program/member/provider — inherited)."""
    encounter_ref = req_string(body, "encounter_ref")
    service_from_s = req_string(body, "service_from_date")
    service_to_s = req_string(body, "service_to_date")
    place_of_service = req_string(body, "place_of_service")
    diagnosis_codes = body.get("diagnosis_codes")
    if not isinstance(diagnosis_codes, list) or any(not isinstance(c, str) for c in diagnosis_codes):
        raise invalid_request("diagnosis_codes must be an array of strings")
    paid_amount_cents = req_int(body, "paid_amount_cents")
    if paid_amount_cents < 0:
        raise invalid_request("paid_amount_cents must not be negative")
    lines = body.get("lines")
    if not isinstance(lines, list):
        raise invalid_request("lines must be an array")
    validate_lines(lines)
    return {
        "encounter_ref": encounter_ref,
        "service_from_s": service_from_s,
        "service_to_s": service_to_s,
        "place_of_service": place_of_service,
        "diagnosis_codes": diagnosis_codes,
        "paid_amount_cents": paid_amount_cents,
        "lines": lines,
    }


@bp.route("/programs/encounters/<eid>/void", methods=["POST"])
def void_encounter(eid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    body = get_body(required=False)
    e = store.encounters.get(eid)
    if e is None:
        raise not_found()
    if body.get("void_reason") is not None and not isinstance(body["void_reason"], str):
        raise invalid_request("void_reason must be a string")
    if e["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_ENCOUNTER_NOT_VOIDABLE",
                       "Void attempted from a status other than ACKNOWLEDGED", 409)
    e["status"] = "VOIDED"
    if body.get("void_reason") is not None:
        e["void_reason"] = body["void_reason"]
    touch(e)
    cycle = store.cycles.get(e["attributed_cycle_id"])
    if cycle is not None:
        recompute_cycle_tallies(cycle)
    return success_object(encounter_view(e))
