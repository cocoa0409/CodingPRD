"""Import entry endpoints: registration and OCC-guarded correction (PRD §3.3/§3.6)."""
from flask import Blueprint, request

from calc import (
    active_lines_on_entry,
    compute_line_amount,
    mint_entity,
    recompute_claim_estimate,
    recompute_entry,
    recompute_entry_quantities,
    touch,
)
from db import STORE
from errors import (
    ERR_CLASSIFICATION_NOT_CERTIFIED,
    ERR_CROSS_CLIENT_REFERENCE,
    ERR_DUPLICATE_ENTRY_NUMBER,
    ERR_ENTRY_LOCKED_BY_FILED_CLAIM,
    ERR_INVALID_REQUEST,
    ERR_MATCH_QUANTITY_EXCEEDED,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import (
    authenticate,
    get_body,
    opt_int,
    req_dt,
    req_int,
    req_str,
    require_client_scope,
    require_role,
)
from response import paginate, success_object
from serializers import serialize, sorted_by_creation

bp = Blueprint("entries", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}


def get_entry_or_404(entry_id):
    entry = STORE["import_entries"].get(entry_id)
    if entry is None:
        raise_err(ERR_NOT_FOUND, f"Import entry {entry_id} not found")
    return entry


@bp.route("/customs/import-entries", methods=["POST"])
def create_entry():
    _, role = authenticate()
    require_role(role, {"Analyst"})
    body = get_body()
    client_id = req_str(body, "client_id")
    classification_id = req_str(body, "classification_id")
    entry_number = req_str(body, "entry_number")
    entry_date = req_dt(body, "entry_date")
    port_code = req_str(body, "port_code")
    line_quantity = req_int(body, "line_quantity", minimum=1)
    entered_value_cents = req_int(body, "entered_value_cents", minimum=0)
    duty_paid_cents = req_int(body, "duty_paid_cents", minimum=0)

    client = STORE["clients"].get(client_id)
    if client is None:
        raise_err(ERR_NOT_FOUND, f"Client {client_id} not found")
    cls = STORE["classifications"].get(classification_id)
    if cls is None:
        raise_err(ERR_NOT_FOUND, f"Classification {classification_id} not found")
    if cls["status"] != "CERTIFIED":
        raise_err(
            ERR_CLASSIFICATION_NOT_CERTIFIED,
            "Import entries require a CERTIFIED classification",
        )
    if cls["client_id"] != client_id:
        raise_err(
            ERR_CROSS_CLIENT_REFERENCE,
            "Classification belongs to a different client",
        )
    for existing in STORE["import_entries"].values():
        if existing["client_id"] == client_id and existing["entry_number"] == entry_number:
            raise_err(ERR_DUPLICATE_ENTRY_NUMBER, "entry_number already exists for this client")

    entry = mint_entity()
    entry.update({
        "client_id": client_id,
        "classification_id": classification_id,
        "entry_number": entry_number,
        "entry_date": entry_date,
        "port_code": port_code,
        "line_quantity": line_quantity,
        "entered_value_cents": entered_value_cents,
        "duty_paid_cents": duty_paid_cents,
        "non_drawbackable_cents": 0,
        "drawback_eligible_duty_cents": 0,
        "matched_quantity": 0,
        "unclaimed_duty_cents": 0,
        "status": "UNMATCHED",
    })
    recompute_entry(entry)
    recompute_entry_quantities(entry)
    STORE["import_entries"][entry["id"]] = entry
    return success_object(serialize(entry), 201)


@bp.route("/customs/import-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    entry = get_entry_or_404(entry_id)
    require_client_scope(user_id, role, entry["client_id"])
    return success_object(serialize(entry))


@bp.route("/customs/import-entries", methods=["GET"])
def list_entries():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["import_entries"].values())
    if role == "ClientContact":
        items = [e for e in items if e["client_id"] == user_id]
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [e for e in items if e["client_id"] == client_id]
    classification_id = request.args.get("classification_id")
    if classification_id is not None:
        items = [e for e in items if e["classification_id"] == classification_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate([serialize(e) for e in items])


@bp.route("/customs/import-entries/<entry_id>/correct", methods=["POST"])
def correct_entry(entry_id):
    _, role = authenticate()
    require_role(role, {"Analyst"})
    entry = get_entry_or_404(entry_id)
    body = get_body()
    if "expected_import_entry_version" not in body or body["expected_import_entry_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_import_entry_version")
    expected = body["expected_import_entry_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_import_entry_version must be an integer")
    new_duty_paid = opt_int(body, "duty_paid_cents", minimum=0)
    new_entered_value = opt_int(body, "entered_value_cents", minimum=0)
    new_line_quantity = opt_int(body, "line_quantity", minimum=1)

    if expected != entry["version"]:
        raise_err(ERR_STALE_VERSION, "expected_import_entry_version does not match current version")

    # Quantity bound: corrected line_quantity may not drop below matched units.
    if new_line_quantity is not None and new_line_quantity < entry["matched_quantity"]:
        raise_err(
            ERR_MATCH_QUANTITY_EXCEEDED,
            "line_quantity may not drop below current matched_quantity",
        )

    # Frozen-ledger protection: any ACTIVE line on a non-DRAFT claim locks the entry.
    for line in active_lines_on_entry(entry["id"]):
        claim = STORE["claims"][line["claim_id"]]
        if claim["status"] != "DRAFT":
            raise_err(
                ERR_ENTRY_LOCKED_BY_FILED_CLAIM,
                "Entry is referenced by ACTIVE lines of a non-DRAFT claim",
            )

    # Link 1: entry fields updated + eligible-duty figures recomputed.
    if new_duty_paid is not None:
        entry["duty_paid_cents"] = new_duty_paid
    if new_entered_value is not None:
        entry["entered_value_cents"] = new_entered_value
    if new_line_quantity is not None:
        entry["line_quantity"] = new_line_quantity
    recompute_entry(entry)

    # Link 2: every ACTIVE line on a DRAFT claim re-evaluated against new figures.
    affected_claim_ids = []
    for line in active_lines_on_entry(entry["id"]):
        claim = STORE["claims"][line["claim_id"]]
        export = STORE["export_shipments"][line["export_shipment_id"]]
        line["drawback_amount_cents"] = compute_line_amount(
            entry, export, line["matched_quantity"], claim["claim_type"]
        )
        touch(line)
        if claim["id"] not in affected_claim_ids:
            affected_claim_ids.append(claim["id"])

    # unclaimed_duty_cents now nets against the re-rated lines.
    recompute_entry(entry)
    recompute_entry_quantities(entry)
    touch(entry)

    # Link 3: each affected draft claim's estimate recomputed.
    for claim_id in affected_claim_ids:
        claim = STORE["claims"][claim_id]
        recompute_claim_estimate(claim)
        touch(claim)

    return success_object(serialize(entry))
