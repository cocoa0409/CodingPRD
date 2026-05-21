"""Owner endpoints: POST /owners, GET /owners/{id}.

PRD §3.1: An Owner is created by Applicant or PlatformAdmin with
full_name (1..100), date_of_birth (YYYY-MM-DD), residency_state
(ISO 3166-2:US, 2 chars).
"""

from flask import Blueprint

from config import (
    ROLE_APPLICANT,
    ROLE_PLATE_ISSUER,
    ROLE_PLATFORM_ADMIN,
    ROLE_REAL_ID_REVIEWER,
    ROLE_TAX_ASSESSOR,
)
from db import store
from errors import make_error
from middleware import parse_json_body, require_auth
from response import success
from routes._helpers import require_field, require_str
from services.engine import create_owner
from services.serializers import serialize_owner
from utils import ISO_DATE_REGEX, STATE_REGEX

owners_bp = Blueprint("owners", __name__)


@owners_bp.route("/owners", methods=["POST"])
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_PLATFORM_ADMIN])
def create_owner_endpoint():
    body = parse_json_body()
    full_name = require_str(require_field(body, "full_name"), "full_name",
                            min_len=1, max_len=100)
    date_of_birth = require_field(body, "date_of_birth")
    if not isinstance(date_of_birth, str) or not ISO_DATE_REGEX.match(date_of_birth):
        raise make_error("ERR_VALIDATION", "date_of_birth must be YYYY-MM-DD.")
    residency_state = require_field(body, "residency_state")
    if not isinstance(residency_state, str) or not STATE_REGEX.match(residency_state):
        raise make_error("ERR_VALIDATION", "residency_state must be a 2-letter uppercase code.")

    with store.lock:
        owner = create_owner(
            full_name=full_name,
            date_of_birth=date_of_birth,
            residency_state=residency_state,
            now=store.now(),
        )
    return success(serialize_owner(owner), status=201)


@owners_bp.route("/owners/<owner_id>", methods=["GET"])
@require_auth(allowed_roles=[
    ROLE_PLATFORM_ADMIN, ROLE_REAL_ID_REVIEWER, ROLE_TAX_ASSESSOR,
    ROLE_PLATE_ISSUER, ROLE_APPLICANT,
])
def read_owner(owner_id: str):
    owner = store.owners.get(owner_id)
    if owner is None:
        raise make_error("ERR_RESOURCE_NOT_FOUND")
    return success(serialize_owner(owner))
