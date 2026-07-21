from flask import Blueprint
from middleware import get_caller, require_role
from response import object_response
from services.billing import run_billing_cycle

billing_bp = Blueprint("billing", __name__)


@billing_bp.post("/_billing/run-cycle")
def billing_run_cycle():
    caller = get_caller()
    require_role(caller, {"PlatformAdmin"})
    run_billing_cycle()
    return object_response({}, 200)
