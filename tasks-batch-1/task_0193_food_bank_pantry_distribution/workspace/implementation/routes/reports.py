"""PoundageReport standalone endpoint."""
from flask import Blueprint

from middleware import get_identity, require_role
from response import object_response
from services import models
from services.poundage import compute_poundage_report
from routes.lookups import get_cycle

bp = Blueprint("reports", __name__)

READ_ROLES_NO_COORD = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor"}


@bp.get("/poundage-reports/<allocation_cycle_id>")
def poundage_report(allocation_cycle_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_NO_COORD)
    cycle = get_cycle(allocation_cycle_id)
    report = compute_poundage_report(cycle["id"])
    return object_response(models.serialize_poundage_report(report))
