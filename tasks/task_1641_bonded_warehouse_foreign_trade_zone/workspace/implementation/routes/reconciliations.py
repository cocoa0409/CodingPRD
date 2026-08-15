"""AnnualReconciliation endpoints (SCAFFOLD 1.5, PRD 3.7; OCC rule 1.2.1)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_ZONE_NOT_FOUND, ERR_RECONCILIATION_NOT_FOUND,
    ERR_RECONCILIATION_INVALID_TRANSITION, ERR_RECONCILIATION_ALREADY_SUBMITTED,
    ERR_STALE_ZONE_VERSION,
)
from middleware import authorized
from response import success_object, success_list
from serializers import recon_view
from services import (
    new_common, touch, compute_reconciliation_variance,
    enter_audit_hold, exit_audit_hold,
)
from validate import (
    get_body, reject_unknown_fields, req_str, req_int, require_path,
    require_body_fk, parse_pagination,
)

bp = Blueprint("reconciliations", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]


@bp.route("/zones/annual-reconciliations", methods=["POST"])
def create_reconciliation():
    caller = authorized(["ZoneOperator"])
    body = get_body()
    reject_unknown_fields(body, {"zone_id", "zone_year", "beginning_value_cents",
                                 "physical_ending_value_cents", "expected_zone_version"})
    zone_id = req_str(body, "zone_id")
    zone = require_body_fk("zones", zone_id, ERR_ZONE_NOT_FOUND, "zone_id")
    zone_year = req_int(body, "zone_year")
    beginning = req_int(body, "beginning_value_cents", non_negative=True)
    physical_ending = req_int(body, "physical_ending_value_cents", non_negative=True)
    expected_zone_version = req_int(body, "expected_zone_version")

    # OCC (state precondition, priority 6): expected_zone_version must equal the
    # zone's current version (SCAFFOLD 1.2.1).
    if zone["version"] != expected_zone_version:
        raise_error(ERR_STALE_ZONE_VERSION,
                    "expected_zone_version does not equal the zone's current version")
    # Resource constraint (priority 9): no stacking on an active SUBMITTED filing.
    for other in db["annual_reconciliations"].values():
        if (other["zone_id"] == zone["id"] and other["zone_year"] == zone_year
                and other["status"] == "SUBMITTED"):
            raise_error(ERR_RECONCILIATION_ALREADY_SUBMITTED,
                        "a SUBMITTED reconciliation already exists for this zone-year")

    recon = new_common()
    recon.update({
        "zone_id": zone["id"],
        "zone_year": zone_year,
        "beginning_value_cents": beginning,
        "physical_ending_value_cents": physical_ending,
        "book_receipts_value_cents": None,
        "book_withdrawals_value_cents": None,
        "book_ending_value_cents": None,
        "discrepancy_cents": None,
        "discrepancy_pct": None,
        "audit_flagged": None,
        "status": "DRAFT",
    })
    db["annual_reconciliations"][recon["id"]] = recon

    # An existing DRAFT for the same (zone_id, zone_year) is superseded.
    for other in db["annual_reconciliations"].values():
        if (other["id"] != recon["id"] and other["zone_id"] == zone["id"]
                and other["zone_year"] == zone_year and other["status"] == "DRAFT"):
            other["status"] = "SUPERSEDED"
            touch(other)

    # A successful create increments the zone's version by one.
    touch(zone)
    return success_object(recon_view(recon), status=201)


@bp.route("/zones/annual-reconciliations", methods=["GET"])
def list_reconciliations():
    authorized(ALL_ROLES)
    limit, offset = parse_pagination()
    zone_id = request.args.get("zone_id")
    zone_year = request.args.get("zone_year")
    status = request.args.get("status")
    items = sorted(db["annual_reconciliations"].values(), key=lambda r: (r["created_at"], r["id"]))
    if zone_id is not None:
        items = [r for r in items if r["zone_id"] == zone_id]
    if zone_year is not None:
        try:
            zy = int(zone_year)
            items = [r for r in items if r["zone_year"] == zy]
        except (ValueError, TypeError):
            items = []
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([recon_view(r) for r in page], total, limit, offset)


@bp.route("/zones/annual-reconciliations/<reconId>", methods=["GET"])
def get_reconciliation(reconId):
    authorized(ALL_ROLES)
    recon = require_path("annual_reconciliations", reconId, ERR_RECONCILIATION_NOT_FOUND)
    return success_object(recon_view(recon))


@bp.route("/zones/annual-reconciliations/<reconId>/submit", methods=["POST"])
def submit_reconciliation(reconId):
    caller = authorized(["ZoneOperator"])
    recon = require_path("annual_reconciliations", reconId, ERR_RECONCILIATION_NOT_FOUND)
    get_body()
    if recon["status"] != "DRAFT":
        raise_error(ERR_RECONCILIATION_INVALID_TRANSITION,
                    f"reconciliation cannot be submitted from {recon['status']}")
    zone = db["zones"][recon["zone_id"]]

    compute_reconciliation_variance(recon, zone)
    recon["status"] = "SUBMITTED"
    touch(recon)
    if recon["audit_flagged"]:
        enter_audit_hold(zone)
    return success_object(recon_view(recon))


@bp.route("/zones/annual-reconciliations/<reconId>/accept", methods=["POST"])
def accept_reconciliation(reconId):
    caller = authorized(["CustomsOfficer"])
    recon = require_path("annual_reconciliations", reconId, ERR_RECONCILIATION_NOT_FOUND)
    get_body()
    if recon["status"] != "SUBMITTED":
        raise_error(ERR_RECONCILIATION_INVALID_TRANSITION,
                    f"reconciliation cannot be accepted from {recon['status']}")
    zone = db["zones"][recon["zone_id"]]

    recon["status"] = "ACCEPTED"
    touch(recon)
    if zone["compliance_posture"] == "AUDIT_HOLD":
        exit_audit_hold(zone)
    return success_object(recon_view(recon))
