"""The nightly batch entry point (PRD 3.10)."""
from flask import Blueprint

import config
import validation as v
from middleware import auth
from response import object_response
from services import billing_run

bp = Blueprint("billing_runs", __name__)


@bp.post("/billing-runs")
@auth(config.ROLE_OPS)
def create_billing_run():
    data = v.body()
    scope = v.get_enum(data, "scope", config.BILLING_RUN_SCOPES, required=True)
    return object_response(billing_run.run(scope))
