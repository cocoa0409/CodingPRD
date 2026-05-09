"""RoyaltyStatement routes."""
from flask import Blueprint, request

from clock import parse_iso
from common import get_json_body, paginate, stamp_new
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.royalty import compute_royalty

bp = Blueprint("royalty_statements", __name__)


VALID_VARIANT = {"PROVISIONAL", "FINAL"}


def _period_aligned(period_start, period_end, settlement_period: str) -> bool:
    """Check that (period_end - period_start) corresponds to the settlement_period unit."""
    delta = period_end - period_start
    days = delta.days
    seconds = delta.seconds + delta.microseconds / 1_000_000.0
    if seconds != 0:
        return False
    if settlement_period == "MONTHLY":
        # 28..31 days is acceptable
        return 28 <= days <= 31
    if settlement_period == "QUARTERLY":
        return 89 <= days <= 92
    if settlement_period == "ANNUAL":
        return 365 <= days <= 366
    return False


@bp.route("/licenses/<license_id>/royalty-statements", methods=["POST"])
def create_statement(license_id):
    user_id, role = require_roles(["RightsHolder"])
    license_obj = db.licenses.get(license_id)
    if not license_obj:
        raise api_error("ERR_NOT_FOUND", "license not found")

    body = get_json_body()

    # Caller must equal licensor.
    if user_id != license_obj["licensor_id"]:
        raise api_error("ERR_FORBIDDEN", "caller must be licensor")

    reversal_of_id = body.get("reversal_of_id")
    refund_cents = body.get("refund_cents")

    if reversal_of_id is not None:
        # Reversal entry path
        original = db.royalty_statements.get(reversal_of_id)
        if (not original or original.get("license_id") != license_id or
                original.get("status") != "SETTLED"):
            raise api_error("ERR_INVALID_REVERSAL",
                            "reversal_of_id does not refer to a SETTLED statement on this license")
        if not isinstance(refund_cents, int) or refund_cents < 0:
            raise api_error("ERR_VALIDATION", "refund_cents required for reversal entry")

        statement = {
            "license_id": license_id,
            "period_start_at": original.get("period_start_at"),
            "period_end_at": original.get("period_end_at"),
            "gross_revenue_cents": 0,
            "variant": "FINAL",
            "earned_royalty_cents": 0,
            "advance_recouped_cents": 0,
            "net_payable_cents": 0,
            "status": "DRAFT",
            "settled_at": None,
            "reversal_of_id": reversal_of_id,
            "refund_cents": int(refund_cents),
        }
        stamp_new(statement)
        db.royalty_statements[statement["id"]] = statement
        return success(statement, status=201)

    # Regular creation path.
    period_start_at = body.get("period_start_at")
    period_end_at = body.get("period_end_at")
    gross_revenue_cents = body.get("gross_revenue_cents")
    variant = body.get("variant")

    if variant not in VALID_VARIANT:
        raise api_error("ERR_VALIDATION", "variant must be PROVISIONAL or FINAL")
    if not isinstance(gross_revenue_cents, int) or gross_revenue_cents < 0:
        raise api_error("ERR_VALIDATION", "gross_revenue_cents must be non-negative integer")

    if not period_start_at or not period_end_at:
        raise api_error("ERR_INVALID_PERIOD", "period bounds required")
    ps = parse_iso(period_start_at)
    pe = parse_iso(period_end_at)
    if ps is None or pe is None or ps >= pe:
        raise api_error("ERR_INVALID_PERIOD", "period_start_at must be < period_end_at")
    if not _period_aligned(ps, pe, license_obj.get("settlement_period")):
        raise api_error("ERR_INVALID_PERIOD",
                        f"period duration does not align with {license_obj.get('settlement_period')}")

    # State eligibility — license must be EFFECTIVE
    if license_obj.get("status") != "EFFECTIVE":
        raise api_error("ERR_INVALID_STATE",
                        "license must be EFFECTIVE to create a statement")

    computed = compute_royalty(license_obj, gross_revenue_cents, variant)

    statement = {
        "license_id": license_id,
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "gross_revenue_cents": int(gross_revenue_cents),
        "variant": variant,
        "earned_royalty_cents": computed["earned_royalty_cents"],
        "advance_recouped_cents": computed["advance_recouped_cents"],
        "net_payable_cents": computed["net_payable_cents"],
        "status": "DRAFT",
        "settled_at": None,
        "reversal_of_id": None,
        "refund_cents": None,
    }
    stamp_new(statement)
    db.royalty_statements[statement["id"]] = statement
    return success(statement, status=201)


@bp.route("/licenses/<license_id>/royalty-statements/<statement_id>", methods=["GET"])
def get_statement(license_id, statement_id):
    require_roles(["PlatformAdmin", "RightsHolder"])
    license_obj = db.licenses.get(license_id)
    if not license_obj:
        raise api_error("ERR_NOT_FOUND", "license not found")
    s = db.royalty_statements.get(statement_id)
    if not s or s.get("license_id") != license_id:
        raise api_error("ERR_NOT_FOUND", "statement not found")
    return success(s)


@bp.route("/licenses/<license_id>/royalty-statements", methods=["GET"])
def list_statements(license_id):
    require_roles(["PlatformAdmin", "RightsHolder"])
    license_obj = db.licenses.get(license_id)
    if not license_obj:
        raise api_error("ERR_NOT_FOUND", "license not found")
    rows = [s for s in db.royalty_statements.values() if s.get("license_id") == license_id]
    status_filter = request.args.get("status")
    if status_filter:
        rows = [s for s in rows if s.get("status") == status_filter]
    page, meta = paginate(rows)
    return success(page, response_type="array", pagination=meta)
