"""Commission entry endpoints (PRD 3.6): reads, release, pay."""

from flask import Blueprint

from core import calc
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import authorize, producer_scope, resolve
from core.serialize import commission_entry as serialize_entry
from core.store import db, bump

bp = Blueprint("commissions", __name__)

_READ_ROLES = (
    "LicensingCoordinator", "ComplianceOfficer", "FinanceOps",
    "CarrierAdmin", "Producer",
)
_LIST_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "FinanceOps", "CarrierAdmin")


@bp.route("/api/commission-entries/<commissionEntryId>", methods=["GET"])
def get_entry(commissionEntryId):
    ctx = authorize(*_READ_ROLES)
    row = resolve("commission_entries", commissionEntryId)
    producer_scope(ctx, row["producer_id"])
    return object_response(serialize_entry(row), 200)


@bp.route("/api/commission-entries", methods=["GET"])
def list_entries():
    authorize(*_LIST_ROLES)
    rows = db.ordered("commission_entries")
    rows = filter_exact(rows, "application_id")
    rows = filter_exact(rows, "producer_id")
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize_entry)


@bp.route("/api/commission-entries/<commissionEntryId>/release", methods=["POST"])
def release_entry(commissionEntryId):
    authorize("ComplianceOfficer")
    entry = resolve("commission_entries", commissionEntryId)
    if entry["status"] != "HELD":
        fail("ERR_INVALID_STATE", "Only a HELD commission entry can be released.")
    app = db.applications.get(entry["application_id"])
    producer = db.producers.get(entry["producer_id"])
    if entry["hold_reason"] == "UNLICENSED_AT_SALE":
        fail("ERR_HOLD_NOT_RELEASABLE", "An UNLICENSED_AT_SALE hold is never releasable.")
    if entry["hold_reason"] == "APPOINTMENT_PENDING":
        appt = None
        if app is not None and producer is not None:
            appt, _ = calc.covering_appointment(producer, app["state_code"], app["line_of_authority"])
        if appt is None:
            fail(
                "ERR_APPOINTMENT_NOT_ACTIVE",
                "No ACTIVE appointment (own or affiliated agency) covers this line in this state.",
            )
    elif entry["hold_reason"] == "REGULATORY_HOLD":
        lic = None
        if app is not None:
            lic = calc.active_license_in_state(
                "producer_id", entry["producer_id"], app["state_code"]
            )
        if lic is None:
            fail(
                "ERR_REGULATORY_HOLD_ACTIVE",
                "The producer's license in the application state is not ACTIVE.",
            )
    entry["status"] = "PAYABLE"
    entry["hold_reason"] = None
    bump(entry)
    calc.recompute_producer_held(entry["producer_id"])
    return object_response(serialize_entry(entry), 200)


@bp.route("/api/commission-entries/<commissionEntryId>/pay", methods=["POST"])
def pay_entry(commissionEntryId):
    authorize("FinanceOps")
    entry = resolve("commission_entries", commissionEntryId)
    # Domain-specific state error (PRD 2.9): paying anything not PAYABLE.
    if entry["status"] != "PAYABLE":
        fail("ERR_COMMISSION_NOT_PAYABLE", "Commission entry is not PAYABLE.")
    entry["status"] = "PAID"
    bump(entry)
    return object_response(serialize_entry(entry), 200)
