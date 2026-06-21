"""Encounter endpoints (PRD §3.3, §3.4, §3.9)."""

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.common import base_entity, parse_date, date_of, touch
from services.encounter_ops import (
    issued_clearance_for,
    apply_clearance_to_worker,
    revert_worker_if_set_from,
)
from services.serialize import public

bp = Blueprint("encounters", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}
ENCOUNTER_TYPES = {"PHYSICAL", "DRUG_SCREEN", "INJURY", "SURVEILLANCE"}
PANEL_CODES = {"PHYSICAL", "DRUG_DOT", "DRUG_NON_DOT", "AUDIOMETRIC", "RESPIRATOR_FIT"}

# Which panel codes are legal for each encounter type.
TYPE_TO_PANELS = {
    "PHYSICAL": {"PHYSICAL"},
    "DRUG_SCREEN": {"DRUG_DOT", "DRUG_NON_DOT"},
    "SURVEILLANCE": {"AUDIOMETRIC", "RESPIRATOR_FIT"},
}

PANEL_TO_EXAM_KIND = {"AUDIOMETRIC": "AUDIOMETRIC", "RESPIRATOR_FIT": "RESPIRATOR_FIT"}


def _active_protocol_for(employer_id):
    for p in db.protocols.values():
        if p["employer_id"] == employer_id and p["status"] == "ACTIVE":
            return p
    return None


def _panel_in_protocol(protocol, panel_code):
    if protocol is None:
        return None
    for panel in protocol.get("panels", []):
        if panel["panel_code"] == panel_code:
            return panel
    return None


@bp.route("/clinic/encounters", methods=["POST"])
def create_encounter():
    caller = authenticate()
    require_role(caller, {"ClinicAdmin", "Clinician"})
    body = get_json_body()

    with LOCK:
        # Priority 4: body FK existence + employer consistency. A missing OR
        # not-found OR cross-employer body reference -> ERR_CROSS_EMPLOYER_REFERENCE.
        employer_id = body.get("employer_id")
        if employer_id is None or employer_id not in db.employers:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE,
                      "employer_id missing or not found")
        employer = db.employers[employer_id]

        worker_id = body.get("worker_id")
        worker = db.workers.get(worker_id) if worker_id is not None else None
        if worker is None or worker["employer_id"] != employer_id:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE,
                      "worker missing, not found, or not under this employer")

        # Priority 5: body well-formedness.
        encounter_type = body.get("encounter_type")
        if encounter_type not in ENCOUNTER_TYPES:
            raise err(errors.ERR_INVALID_REQUEST, "invalid encounter_type")

        panel_code = body.get("panel_code")
        if panel_code is not None and panel_code not in PANEL_CODES:
            raise err(errors.ERR_INVALID_REQUEST, "invalid panel_code")

        # A non-injury encounter must carry a panel_code (missing required field
        # is body well-formedness, priority 5). The INJURY-must-omit-panel rule is
        # part of the §3.3 encounter_type/panel_code consistency rule and is
        # evaluated as a business rule below, yielding ERR_PANEL_NOT_IN_PROTOCOL.
        if encounter_type != "INJURY" and panel_code is None:
            raise err(errors.ERR_INVALID_REQUEST,
                      "panel_code is required for non-injury encounters")

        active_protocol = _active_protocol_for(employer_id)

        # Business rules begin (after foundational layers).
        # Note: employer must be ACTIVE to schedule (PROSPECT/SUSPENDED block work).
        if employer["account_status"] != "ACTIVE":
            raise err(errors.ERR_EMPLOYER_NOT_ACTIVE,
                      "Employer must be ACTIVE to schedule encounters")

        # PRD §3.3: "The `encounter_type` and `panel_code` must be mutually
        # consistent ... an `INJURY` carries no panel code ... a mismatch ... is
        # rejected with `ERR_PANEL_NOT_IN_PROTOCOL`." An INJURY presented with a
        # panel_code is such a mismatch.
        if encounter_type == "INJURY" and panel_code is not None:
            raise err(errors.ERR_PANEL_NOT_IN_PROTOCOL,
                      "An INJURY encounter must omit panel_code")

        panel = None
        if encounter_type != "INJURY":
            # Priority 11: encounter_type vs panel_code consistency + presence in
            # the active protocol.
            allowed = TYPE_TO_PANELS[encounter_type]
            if panel_code not in allowed:
                raise err(errors.ERR_PANEL_NOT_IN_PROTOCOL,
                          "panel_code inconsistent with encounter_type")
            panel = _panel_in_protocol(active_protocol, panel_code)
            if panel is None:
                raise err(errors.ERR_PANEL_NOT_IN_PROTOCOL,
                          "panel_code not present in active protocol")

            # Priority 12: job-category match.
            if worker["job_category"] != panel["required_for_job_category"]:
                raise err(errors.ERR_JOB_CATEGORY_PANEL_MISMATCH,
                          "worker job_category does not match the panel")

            # Priority 13: DOT eligibility.
            if panel_code == "DRUG_DOT" and not employer.get("dot_regulated"):
                raise err(errors.ERR_DOT_NOT_ALLOWED,
                          "DRUG_DOT requires a DOT-regulated employer")

            # Priority 14: surveillance recheck window.
            if encounter_type == "SURVEILLANCE":
                exam_kind = PANEL_TO_EXAM_KIND[panel_code]
                interval = panel["recheck_interval_days"]
                if interval and interval > 0:
                    current = parse_date(employer["current_date"])
                    for ex in db.surveillance_exams.values():
                        if (ex["worker_id"] == worker_id
                                and ex["exam_kind"] == exam_kind
                                and ex["status"] == "FINALIZED"):
                            # The prior exam date is its parent encounter's
                            # completion/record date; use the exam's updated_at as
                            # the reference for the prior finalized exam.
                            prior = date_of(ex.get("_finalized_on") or ex["updated_at"])
                            if prior is not None and current is not None:
                                days = (current - prior).days
                                if days < interval:
                                    raise err(errors.ERR_SURVEILLANCE_TOO_EARLY,
                                              "Surveillance recheck scheduled too early")

        enc = base_entity()
        enc.update({
            "employer_id": employer_id,
            "worker_id": worker_id,
            "protocol_id": active_protocol["id"] if active_protocol else None,
            "encounter_type": encounter_type,
            "panel_code": panel_code,
            "clinician_user_id": caller.user_id,
            "status": "SCHEDULED",
            "billable_amount_cents": 0,
            "is_billed": False,
        })
        db.encounters[enc["id"]] = enc
        return object_response(public(enc), 201)


@bp.route("/clinic/encounters", methods=["GET"])
def list_encounters():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    args = request.args
    items = list(db.encounters.values())
    for key in ("employer_id", "worker_id", "protocol_id", "status", "encounter_type"):
        val = args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    return paginated(sort_by_created(items))


@bp.route("/clinic/encounters/<encounter_id>", methods=["GET"])
def get_encounter(encounter_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    enc = lookup.get_encounter(encounter_id)
    return object_response(public(enc), 200)


@bp.route("/clinic/encounters/<encounter_id>/check-in", methods=["POST"])
def check_in(encounter_id):
    caller = authenticate()
    require_role(caller, {"Clinician"})
    with LOCK:
        enc = lookup.get_encounter(encounter_id)
        if enc["status"] != "SCHEDULED":
            raise err(errors.ERR_ENCOUNTER_NOT_SCHEDULED,
                      "Encounter must be SCHEDULED to check in")
        employer = db.employers.get(enc["employer_id"])
        if employer is None or employer["account_status"] != "ACTIVE":
            raise err(errors.ERR_EMPLOYER_NOT_ACTIVE, "Employer must be ACTIVE")
        enc["status"] = "IN_PROGRESS"
        touch(enc)
        return object_response(public(enc), 200)


def _snapshot_panel_price(enc):
    """price_cents of the snapshotted protocol panel matching enc.panel_code."""
    proto = db.protocols.get(enc.get("protocol_id"))
    if proto is None:
        return 0
    for panel in proto.get("panels", []):
        if panel["panel_code"] == enc["panel_code"]:
            return panel["price_cents"]
    return 0


@bp.route("/clinic/encounters/<encounter_id>/complete", methods=["POST"])
def complete(encounter_id):
    caller = authenticate()
    require_role(caller, {"Clinician"})
    with LOCK:
        enc = lookup.get_encounter(encounter_id)
        etype = enc["encounter_type"]

        # PRD §3.4: completion takes one of two forms keyed on the encounter's
        # current from-state. An encounter in IN_PROGRESS follows the
        # direct-completion path, which requires encounter_type == PHYSICAL
        # (otherwise ERR_ENCOUNTER_TYPE_NOT_DIRECT_COMPLETE). An encounter in
        # PENDING_RESULTS follows the result-completion path, which requires
        # encounter_type to be one of DRUG_SCREEN, SURVEILLANCE, or INJURY
        # (otherwise ERR_ENCOUNTER_TYPE_NOT_RESULT_COMPLETE).
        if enc["status"] == "IN_PROGRESS":
            # Direct-completion path is reserved to PHYSICAL.
            if etype != "PHYSICAL":
                raise err(errors.ERR_ENCOUNTER_TYPE_NOT_DIRECT_COMPLETE,
                          "Only a PHYSICAL encounter completes directly from IN_PROGRESS")
            clearance = issued_clearance_for(enc["id"])
            if clearance is None:
                raise err(errors.ERR_CLEARANCE_REQUIRED,
                          "An ISSUED clearance is required to complete")
            _finish_completion(enc, clearance)
            return object_response(public(enc), 200)

        # Result-completion path (DRUG_SCREEN, SURVEILLANCE, INJURY) from PENDING_RESULTS.
        if enc["status"] != "PENDING_RESULTS":
            # Not a completable from-state. A PHYSICAL that is not IN_PROGRESS is a
            # direct-path type error; the result types are reachable only from
            # PENDING_RESULTS, so any other state is a result-path type error.
            if etype == "PHYSICAL":
                raise err(errors.ERR_ENCOUNTER_TYPE_NOT_DIRECT_COMPLETE,
                          "PHYSICAL completes directly only from IN_PROGRESS")
            raise err(errors.ERR_ENCOUNTER_TYPE_NOT_RESULT_COMPLETE,
                      "Result encounters complete only from PENDING_RESULTS")

        # status == PENDING_RESULTS: result-completion path requires a result type.
        if etype == "PHYSICAL":
            raise err(errors.ERR_ENCOUNTER_TYPE_NOT_RESULT_COMPLETE,
                      "A PHYSICAL encounter does not complete from PENDING_RESULTS")

        if etype == "DRUG_SCREEN":
            ds = _child_drug_screen(enc["id"])
            if ds is None or ds["status"] not in ("VERIFIED", "CANCELLED"):
                raise err(errors.ERR_DRUG_SCREEN_NOT_VERIFIED,
                          "DrugScreen must be VERIFIED or CANCELLED")
        elif etype == "SURVEILLANCE":
            ex = _child_surveillance_exam(enc["id"])
            if ex is None or ex["status"] != "FINALIZED":
                raise err(errors.ERR_EXAM_NOT_FINALIZED,
                          "SurveillanceExam must be FINALIZED")
        elif etype == "INJURY":
            ic = _child_injury_case(enc["id"])
            if ic is None or ic["status"] != "CLOSED":
                raise err(errors.ERR_INJURY_CASE_NOT_CLOSED,
                          "InjuryCase must be CLOSED")

        clearance = None
        if etype != "INJURY":
            clearance = issued_clearance_for(enc["id"])
            if clearance is None:
                raise err(errors.ERR_CLEARANCE_REQUIRED,
                          "An ISSUED clearance is required to complete")
        _finish_completion(enc, clearance)
        return object_response(public(enc), 200)


def _finish_completion(enc, clearance):
    enc["status"] = "COMPLETED"
    if enc["encounter_type"] == "INJURY":
        enc["billable_amount_cents"] = 0
    else:
        enc["billable_amount_cents"] = _snapshot_panel_price(enc)
    touch(enc)
    # hire_status cascade from clearance (types that carry a clearance).
    if clearance is not None:
        worker = db.workers.get(enc["worker_id"])
        if worker is not None:
            apply_clearance_to_worker(worker, clearance)


@bp.route("/clinic/encounters/<encounter_id>/cancel", methods=["POST"])
def cancel(encounter_id):
    caller = authenticate()
    require_role(caller, {"Clinician"})
    with LOCK:
        enc = lookup.get_encounter(encounter_id)
        if enc["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise err(errors.ERR_ENCOUNTER_NOT_CANCELLABLE,
                      "Encounter must be SCHEDULED or IN_PROGRESS to cancel")
        enc["status"] = "CANCELLED"
        # billable stays 0
        touch(enc)
        return object_response(public(enc), 200)


@bp.route("/clinic/encounters/<encounter_id>/void", methods=["POST"])
def void(encounter_id):
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    with LOCK:
        enc = lookup.get_encounter(encounter_id)
        if enc["status"] != "COMPLETED":
            raise err(errors.ERR_ENCOUNTER_NOT_VOIDABLE,
                      "Encounter must be COMPLETED to void")
        if enc.get("is_billed"):
            raise err(errors.ERR_ENCOUNTER_ALREADY_BILLED,
                      "Encounter is already billed; cannot void")

        enc["status"] = "VOIDED"
        enc["billable_amount_cents"] = 0
        touch(enc)

        # Cascade: ISSUED clearance -> RESCINDED, then revert worker hire_status.
        clearance = issued_clearance_for(enc["id"])
        if clearance is not None:
            clearance["status"] = "RESCINDED"
            touch(clearance)
            worker = db.workers.get(enc["worker_id"])
            revert_worker_if_set_from(worker, clearance["id"])

        return object_response(public(enc), 200)


# --- child lookups for completion preconditions ---

def _child_drug_screen(encounter_id):
    for ds in db.drug_screens.values():
        if ds["encounter_id"] == encounter_id:
            return ds
    return None


def _child_surveillance_exam(encounter_id):
    for ex in db.surveillance_exams.values():
        if ex["encounter_id"] == encounter_id:
            return ex
    return None


def _child_injury_case(encounter_id):
    for ic in db.injury_cases.values():
        if ic["encounter_id"] == encounter_id:
            return ic
    return None
