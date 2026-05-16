"""EmergencyContact routes."""

from flask import Blueprint

from config import (
    EMERGENCY_CONTACT_MAX_PER_CHILD,
    EMERGENCY_CONTACT_NAME_MAX,
    EMERGENCY_CONTACT_NAME_MIN,
    EMERGENCY_PRIORITY_MAX,
    EMERGENCY_PRIORITY_MIN,
    EMERGENCY_RELATIONSHIP_MAX,
    EMERGENCY_RELATIONSHIP_MIN,
    PHONE_MAX,
    PHONE_MIN,
    ROLE_GUARDIAN,
    ROLE_PROGRAM_ADMIN,
)
from db import db, init_common_fields, touch
from errors import APIError
from middleware import get_json_body, require_auth
from response import empty_response, success_response
from services.lookups import assert_family_scope, get_child, get_emergency_contact
from services.projection import recount_emergency_contacts
from services.serializers import serialize_emergency_contact
from services.validators import require_int, require_string


emergency_bp = Blueprint("emergency", __name__)


@emergency_bp.route("/children/<child_id>/emergency-contacts", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def create_emergency_contact(child_id):
    child = get_child(child_id)
    assert_family_scope(child["family_id"])
    body = get_json_body()
    full_name = require_string(body, "full_name", min_len=EMERGENCY_CONTACT_NAME_MIN, max_len=EMERGENCY_CONTACT_NAME_MAX)
    phone = require_string(body, "phone", min_len=PHONE_MIN, max_len=PHONE_MAX)
    relationship = require_string(body, "relationship", min_len=EMERGENCY_RELATIONSHIP_MIN, max_len=EMERGENCY_RELATIONSHIP_MAX)
    priority = require_int(body, "priority", minimum=EMERGENCY_PRIORITY_MIN, maximum=EMERGENCY_PRIORITY_MAX)

    # Uniqueness: (child_id, priority) among non-archived
    for ec in db.emergency_contacts.values():
        if ec["child_id"] == child_id and not ec.get("archived", False) and ec["priority"] == priority:
            raise APIError("ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN")

    # At most 9 non-archived contacts per child (enforced via priority window)
    non_archived = [
        ec for ec in db.emergency_contacts.values()
        if ec["child_id"] == child_id and not ec.get("archived", False)
    ]
    if len(non_archived) >= EMERGENCY_CONTACT_MAX_PER_CHILD:
        raise APIError("ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN", "Maximum 9 non-archived emergency contacts per child.")

    row = init_common_fields({
        "child_id": child_id,
        "full_name": full_name,
        "phone": phone,
        "relationship": relationship,
        "priority": priority,
        "archived": False,
    })
    db.emergency_contacts[row["id"]] = row
    child["emergency_contact_count"] = child.get("emergency_contact_count", 0) + 1
    touch(child)
    return success_response(serialize_emergency_contact(row), status=201)


@emergency_bp.route("/emergency-contacts/<contact_id>", methods=["DELETE"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def archive_emergency_contact(contact_id):
    ec = get_emergency_contact(contact_id)
    child = db.children.get(ec["child_id"])
    if child is None:
        raise APIError("ERR_RESOURCE_NOT_FOUND", "Parent child not found.")
    assert_family_scope(child["family_id"])
    if ec.get("archived", False):
        # Idempotent — but spec doesn't require so; treat as no-op? Use ERR_INVALID_STATE.
        raise APIError("ERR_INVALID_STATE", "Emergency contact already archived.")
    ec["archived"] = True
    touch(ec)
    recount_emergency_contacts(child)
    return empty_response()
