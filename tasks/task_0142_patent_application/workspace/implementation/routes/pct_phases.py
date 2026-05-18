"""PCT Phase endpoints (SCAFFOLD §1.5).

GET    /pct-phases/{id}                 -> Applicant, Examiner, USPTOAdmin
POST   /pct-phases/{id}/enter-national  -> Applicant
"""

from flask import Blueprint

from config import ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN
from db import store
from errors import make_error
from middleware import require_auth
from response import success
from services.patent_engine import _check_ownership_application, enter_national_phase
from services.serializers import serialize_pct_phase


pct_phases_bp = Blueprint("pct_phases", __name__)


@pct_phases_bp.get("/pct-phases/<pct_id>")
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN])
def get_pct_phase_route(pct_id: str):
    pct = store.pct_phases.get(pct_id)
    if pct is None:
        raise make_error("ERR_NOT_FOUND", f"PCTPhase {pct_id} not found.")
    application = store.applications.get(pct["application_id"])
    if application is not None:
        _check_ownership_application(application)
    return success(serialize_pct_phase(pct))


@pct_phases_bp.post("/pct-phases/<pct_id>/enter-national")
@require_auth(allowed_roles=[ROLE_APPLICANT])
def enter_national_phase_route(pct_id: str):
    with store.lock:
        pct = enter_national_phase(pct_id)
    return success(serialize_pct_phase(pct))
