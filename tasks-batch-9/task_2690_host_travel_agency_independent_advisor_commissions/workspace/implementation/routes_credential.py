"""Compliance credentials: filing, review decisions and lapse (PRD 3.3)."""

from flask import Blueprint

import calc
from envelope import created, ok
from errors import ApiError
from guards import (authenticate, field_dt, field_enum, field_int,
                    field_state_code, field_str, read_body)
from listing import list_response
from lookup import get_advisor, get_credential, get_supplier
from store import new_row, serialize, store, touch

bp = Blueprint("credential", __name__)

READ_ROLES = ("HostOperations", "HostController", "ComplianceOfficer", "Advisor")

CREDENTIAL_TYPES = ("SELLER_OF_TRAVEL", "EO_POLICY", "TRAINING_CERT",
                    "SUPPLIER_ACCREDITATION")

# credential_type -> (the column it requires, the columns that must stay null)
SHAPE = {
    "SELLER_OF_TRAVEL": ("jurisdiction_state_code",
                         ("supplier_id", "coverage_amount_cents")),
    "EO_POLICY": ("coverage_amount_cents",
                  ("jurisdiction_state_code", "supplier_id")),
    "SUPPLIER_ACCREDITATION": ("supplier_id",
                               ("jurisdiction_state_code", "coverage_amount_cents")),
    "TRAINING_CERT": (None, ("jurisdiction_state_code", "supplier_id",
                             "coverage_amount_cents")),
}


def coverage_key(credential):
    """PRD 3.3: what makes two credentials cover 'the same thing'."""
    kind = credential["credential_type"]
    if kind == "SELLER_OF_TRAVEL":
        return credential["jurisdiction_state_code"]
    if kind == "SUPPLIER_ACCREDITATION":
        return credential["supplier_id"]
    return None


@bp.post("/advisors/<advisor_id>/credentials")
def file_credential(advisor_id):
    authenticate(("HostOperations", "Advisor"))
    body = read_body(("credential_type", "credential_number", "effective_on",
                      "expires_on", "jurisdiction_state_code", "supplier_id",
                      "coverage_amount_cents"))
    kind = field_enum(body, "credential_type", CREDENTIAL_TYPES)
    number = field_str(body, "credential_number", max_len=100)
    effective_on = field_dt(body, "effective_on")
    expires_on = field_dt(body, "expires_on")
    state_code = field_state_code(body, "jurisdiction_state_code", required=False)
    supplier_id = field_str(body, "supplier_id", required=False)
    coverage = field_int(body, "coverage_amount_cents", required=False, minimum=0)

    advisor = get_advisor(advisor_id)
    if supplier_id is not None:
        get_supplier(supplier_id)

    # Polymorphic coherence (PRD 2.8 band 11).
    required_field, forbidden_fields = SHAPE[kind]
    supplied = {
        "jurisdiction_state_code": state_code,
        "supplier_id": supplier_id,
        "coverage_amount_cents": coverage,
    }
    if required_field is not None and supplied[required_field] is None:
        raise ApiError("ERR_CREDENTIAL_FIELDS_INCOHERENT")
    for name in forbidden_fields:
        if supplied[name] is not None:
            raise ApiError("ERR_CREDENTIAL_FIELDS_INCOHERENT")

    row = new_row({
        "advisor_id": advisor["id"],
        "credential_type": kind,
        "jurisdiction_state_code": state_code,
        "supplier_id": supplier_id,
        "credential_number": number,
        "coverage_amount_cents": coverage,
        "effective_on": effective_on,
        "expires_on": expires_on,
        "status": "PENDING_REVIEW",
        "verified_by_user_id": None,
        "verified_at": None,
    })

    # Closed-interval overlap, adjacency is a collision (PRD 2.8 band 13).
    key = coverage_key(row)
    for existing in calc.advisor_credentials(advisor["id"]):
        if existing["status"] not in ("PENDING_REVIEW", "VERIFIED"):
            continue
        if existing["credential_type"] != kind:
            continue
        if coverage_key(existing) != key:
            continue
        if (effective_on <= existing["expires_on"]
                and existing["effective_on"] <= expires_on):
            raise ApiError("ERR_CREDENTIAL_COVERAGE_OVERLAP")

    if not expires_on > effective_on:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    store.credentials[row["id"]] = row
    return created(serialize(row))


@bp.get("/compliance-credentials/<credential_id>")
def read_credential(credential_id):
    authenticate(READ_ROLES)
    return ok(serialize(get_credential(credential_id)))


@bp.get("/compliance-credentials")
def list_credentials():
    authenticate(READ_ROLES)
    return list_response(store.credentials.values(),
                         (("advisor_id", "advisor_id"),
                          ("supplier_id", "supplier_id"),
                          ("credential_type", "credential_type"),
                          ("status", "status")))


@bp.post("/compliance-credentials/<credential_id>/decision")
def decide_credential(credential_id):
    caller = authenticate(("ComplianceOfficer",))
    body = read_body(("decision", "note"))
    decision = field_enum(body, "decision", ("VERIFY", "REJECT", "REVOKE"))
    field_str(body, "note", required=False, allow_empty=True, max_len=2000)

    credential = get_credential(credential_id)
    advisor = store.advisors.get(credential["advisor_id"])

    if decision in ("VERIFY", "REJECT"):
        if credential["status"] != "PENDING_REVIEW":
            raise ApiError("ERR_INVALID_CREDENTIAL_STATE")
    else:
        if credential["status"] != "VERIFIED":
            raise ApiError("ERR_INVALID_CREDENTIAL_STATE")

    if decision == "VERIFY":
        # Verifying an already-lapsed window is not a declared transition.
        if not store.clock < credential["expires_on"]:
            raise ApiError("ERR_INVALID_CREDENTIAL_STATE")
        credential["status"] = "VERIFIED"
        credential["verified_by_user_id"] = caller.user_id
        credential["verified_at"] = store.clock
        touch(credential)
        if credential["credential_type"] == "EO_POLICY" and advisor is not None:
            calc.recompute_eo_coverage(advisor)
        return ok(serialize(credential))

    if decision == "REJECT":
        credential["status"] = "REJECTED"
        touch(credential)
        return ok(serialize(credential))

    credential["status"] = "REVOKED"
    touch(credential)
    if advisor is not None:
        if credential["credential_type"] == "EO_POLICY":
            calc.recompute_eo_coverage(advisor)
        elif credential["credential_type"] == "SELLER_OF_TRAVEL":
            # Losing the last valid registration suspends the advisor.
            if (advisor["status"] == "ACTIVE"
                    and not calc.has_seller_of_travel(advisor, store.clock)):
                advisor["status"] = "SUSPENDED"
                touch(advisor)
    return ok(serialize(credential))
