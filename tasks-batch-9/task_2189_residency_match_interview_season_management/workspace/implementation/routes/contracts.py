"""PGY-1 contracts and the onboarding credential packet."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import acting_faculty, endpoint, require_faculty_program, require_owns_applicant
from envelope import object_response
from errors import ApiError
from store import find, insert, must_find, new_row, now_iso, rows, touch
from validators import body, fk, q_enum, q_str, req_int, req_str
from routes.common import keep, listing

bp = Blueprint("contracts", __name__)

CONTRACT_STATUSES = ("DRAFT", "ISSUED", "SIGNED", "ACTIVE", "VOID", "RESCINDED")
CREDENTIAL_TYPES = ("STATE_LICENSE", "DEA", "VISA", "BLS")
ITEM_STATUSES = ("PENDING", "SUBMITTED", "VERIFIED", "REJECTED", "VOIDED")


def _applicant_of_contract(contract):
    application = helpers.application_of_contract(contract)
    return application["applicant_id"] if application else None


def _program_of_contract(contract):
    application = helpers.application_of_contract(contract)
    return find("programs", application["program_id"]) if application else None


# ================================================================== Contract
@bp.post("/contracts")
@endpoint("ProgramCoordinator")
def create_contract():
    data = body()
    result = fk(data, "match_result_id", "match_results")
    if result is None:
        req_str(data, "match_result_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    salary_cents = req_int(data, "salary_cents", minimum=0)

    helpers.require_state(result, "outcome", ("MATCHED",))

    for other in rows("contracts"):
        if other["match_result_id"] == result["id"]:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE", "A contract already exists for this match result."
            )

    contract = new_row(
        match_result_id=result["id"],
        salary_cents=salary_cents,
        status="ISSUED",
        issued_at=now_iso(),
        signed_at=None,
        reason=None,
    )
    insert("contracts", contract)

    application = helpers.application_of_result(result)
    applicant = (
        find("applicants", application["applicant_id"]) if application is not None else None
    )
    program = find("programs", application["program_id"]) if application is not None else None

    packet = [("STATE_LICENSE", True), ("BLS", True)]
    packet.append(("DEA", program is None or program["specialty_code"] != "PATH"))
    if applicant is not None and applicant["visa_status"] in ("NEEDS_J1", "NEEDS_H1B"):
        packet.append(("VISA", True))

    for credential_type, mandatory in packet:
        insert(
            "credential_items",
            new_row(
                contract_id=contract["id"],
                credential_type=credential_type,
                is_mandatory=mandatory,
                status="PENDING",
                reference_number=None,
                verified_at=None,
                reason=None,
            ),
        )

    return object_response(serializers.contract(contract), 201)


@bp.get("/contracts")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def list_contracts():
    items = rows("contracts")
    items = keep(items, "match_result_id", q_str("match_result_id"))
    items = keep(items, "status", q_enum("status", CONTRACT_STATUSES))
    return listing(items, serializers.contract)


@bp.get("/contracts/<contract_id>")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def read_contract(contract_id):
    return object_response(serializers.contract(must_find("contracts", contract_id)))


@bp.post("/contracts/<contract_id>/sign")
@endpoint("Applicant")
def sign_contract(contract_id):
    contract = must_find("contracts", contract_id)
    helpers.require_state(contract, "status", ("ISSUED",))
    require_owns_applicant(_applicant_of_contract(contract))

    contract["status"] = "SIGNED"
    contract["signed_at"] = now_iso()
    touch(contract)
    return object_response(serializers.contract(contract))


@bp.post("/contracts/<contract_id>/activate")
@endpoint("ProgramCoordinator")
def activate_contract(contract_id):
    contract = must_find("contracts", contract_id)
    helpers.require_state(contract, "status", ("SIGNED",))

    if calc.verified_credential_count(contract) != calc.mandatory_credential_count(contract):
        raise ApiError("ERR_CREDENTIALS_INCOMPLETE")

    contract["status"] = "ACTIVE"
    touch(contract)
    return object_response(serializers.contract(contract))


@bp.post("/contracts/<contract_id>/void")
@endpoint("ProgramCoordinator")
def void_contract(contract_id):
    contract = must_find("contracts", contract_id)
    data = body()
    reason = req_str(data, "reason", max_len=2000)

    helpers.require_state(contract, "status", ("ISSUED",))

    contract["status"] = "VOID"
    contract["reason"] = reason
    helpers.void_packet(contract)
    touch(contract)
    return object_response(serializers.contract(contract))


@bp.post("/contracts/<contract_id>/rescind")
@endpoint("ProgramDirector")
def rescind_contract(contract_id):
    contract = must_find("contracts", contract_id)
    data = body()
    reason = req_str(data, "reason", max_len=2000)

    helpers.require_state(contract, "status", ("SIGNED", "ACTIVE"))

    program = _program_of_contract(contract)
    faculty = acting_faculty()
    require_faculty_program(faculty, program["id"] if program else None)

    contract["status"] = "RESCINDED"
    contract["reason"] = reason
    helpers.rescind_cascade(contract)
    touch(contract)
    return object_response(serializers.contract(contract))


# ============================================================ CredentialItem
@bp.get("/contracts/<contract_id>/credential-items")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def list_credential_items(contract_id):
    contract = must_find("contracts", contract_id)
    items = calc.contract_items(contract["id"])
    items = keep(items, "status", q_enum("status", ITEM_STATUSES))
    items = keep(items, "credential_type", q_enum("credential_type", CREDENTIAL_TYPES))
    return listing(items, serializers.credential_item)


@bp.get("/credential-items/<item_id>")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def read_credential_item(item_id):
    return object_response(serializers.credential_item(must_find("credential_items", item_id)))


@bp.post("/credential-items/<item_id>/submit")
@endpoint("Applicant")
def submit_credential_item(item_id):
    item = must_find("credential_items", item_id)
    data = body()
    reference_number = req_str(data, "reference_number", max_len=200)

    helpers.require_state(item, "status", ("PENDING", "REJECTED"))
    contract = helpers.contract_of_item(item)
    if contract is None or contract["status"] not in ("ISSUED", "SIGNED"):
        helpers.invalid_state("The contract no longer accepts credential submissions.")

    require_owns_applicant(_applicant_of_contract(contract))

    item["status"] = "SUBMITTED"
    item["reference_number"] = reference_number
    touch(item)
    return object_response(serializers.credential_item(item))


@bp.post("/credential-items/<item_id>/verify")
@endpoint("ComplianceOfficer")
def verify_credential_item(item_id):
    item = must_find("credential_items", item_id)
    helpers.require_state(item, "status", ("SUBMITTED",))

    item["status"] = "VERIFIED"
    item["verified_at"] = now_iso()
    touch(item)

    if item["is_mandatory"]:
        touch(helpers.contract_of_item(item))
    return object_response(serializers.credential_item(item))


@bp.post("/credential-items/<item_id>/reject")
@endpoint("ComplianceOfficer")
def reject_credential_item(item_id):
    item = must_find("credential_items", item_id)
    data = body()
    reason = req_str(data, "reason", max_len=2000)

    helpers.require_state(item, "status", ("SUBMITTED",))

    item["status"] = "REJECTED"
    item["reason"] = reason
    touch(item)
    return object_response(serializers.credential_item(item))
