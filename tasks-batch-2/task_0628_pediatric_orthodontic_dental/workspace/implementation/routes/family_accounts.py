"""FamilyAccount endpoints (PRD §3.1)."""

from flask import Blueprint

from db import db, lock
from helpers import get_json_body, require_str, stamp_new
from lookups import get_or_404, require_guardian_owns_family
from middleware import require_roles
from response import success
from serializers import public

bp = Blueprint("family_accounts", __name__)


@bp.post("/family-accounts")
@require_roles("FrontDesk", "ClinicAdmin")
def create_family_account():
    body = get_json_body()
    family_name = require_str(body, "family_name")
    billing_email = require_str(body, "billing_email")
    guardian_user_id = require_str(body, "guardian_user_id")
    with lock:
        rec = {
            "family_name": family_name,
            "billing_email": billing_email,
            "guardian_user_id": guardian_user_id,
            "discount_tier_pct": 0,
            "active_plan_count": 0,
        }
        stamp_new(rec)
        db.family_accounts[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/family-accounts/<account_id>")
@require_roles("FrontDesk", "ClinicAdmin", "BillingSpecialist", "Guardian")
def get_family_account(account_id):
    with lock:
        rec = get_or_404(db.family_accounts, account_id)
        require_guardian_owns_family(rec)
        return success(public(rec), 200)
