"""Import entries (prior notice, entry filing, FDA disposition) and receipt lots."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store, new_entity, touch
from errors import (
    ApiError, ERR_SUPPLIER_NOT_FOUND, ERR_IMPORT_ENTRY_NOT_FOUND,
    ERR_RECEIPT_LOT_NOT_FOUND, ERR_INVALID_STATE, ERR_VALIDATION_FAILED,
    ERR_SUPPLIER_NOT_APPROVED, ERR_PRIOR_NOTICE_WINDOW_MISSED,
    ERR_ENTRY_NOT_RELEASED, ERR_VERIFICATION_REQUIRED,
    ERR_HISTAMINE_CRITICAL_LIMIT, ERR_TEMPERATURE_ABUSE_EXCEEDED,
    ERR_FREEZE_PROTOCOL_NOT_MET, ERR_OPEN_CORRECTIVE_ACTIONS,
)
from middleware import (
    require_roles, ANY_OPERATIONAL, ROLE_IMPORT_COORDINATOR,
    ROLE_RECEIVING_INSPECTOR, ROLE_QA_TECH, ROLE_COMPLIANCE_MANAGER,
)
from response import success
from services import (
    serialize_entry, serialize_lot, run_entry_cost_allocation,
    PRIOR_NOTICE_LEAD_HOURS, HISTAMINE_SUSCEPTIBLE_SPECIES, OPEN_CA_STATUSES,
)
from utils import (
    get_body, req_str, req_int, req_num, req_enum, req_dt, opt_num, opt_enum,
    opt_str, q1, q2, q3, q0_int, paginate,
)
import uuid as _uuid

bp = Blueprint("entries", __name__)


def get_entry_or_404(entry_id):
    e = store.entries.get(entry_id)
    if e is None:
        raise ApiError(ERR_IMPORT_ENTRY_NOT_FOUND,
                       "Import entry %s not found" % entry_id, 404)
    return e


def get_lot_or_404(lot_id):
    l = store.lots.get(lot_id)
    if l is None:
        raise ApiError(ERR_RECEIPT_LOT_NOT_FOUND,
                       "Receipt lot %s not found" % lot_id, 404)
    return l


# ---------------------------------------------------------------- entries
@bp.route("/seafood/import-entries", methods=["POST"])
@require_roles(ROLE_IMPORT_COORDINATOR)
def create_entry():
    body = get_body()
    supplier_id = body.get("supplier_id")
    if isinstance(supplier_id, str) and supplier_id not in store.suppliers:
        raise ApiError(ERR_SUPPLIER_NOT_FOUND,
                       "Supplier %s not found" % supplier_id, 404)
    supplier_id = req_str(body, "supplier_id")
    entry_number = req_str(body, "entry_number")
    species_declared = req_str(body, "species_declared")
    transport_mode = req_enum(body, "transport_mode", ("VESSEL", "AIR", "ROAD"))
    scheduled_arrival = req_dt(body, "scheduled_arrival")
    port_code = req_str(body, "port_code")
    goods = req_int(body, "goods_value_cents")
    if goods <= 0:
        raise ApiError(ERR_VALIDATION_FAILED, "goods_value_cents must be > 0", 400)
    freight = req_int(body, "freight_cost_cents")
    if freight < 0:
        raise ApiError(ERR_VALIDATION_FAILED, "freight_cost_cents must be >= 0", 400)
    duty_rate = req_num(body, "duty_rate_pct")
    if duty_rate < 0:
        raise ApiError(ERR_VALIDATION_FAILED, "duty_rate_pct must be >= 0", 400)
    total_weight = req_num(body, "total_weight_kg")
    if total_weight <= 0:
        raise ApiError(ERR_VALIDATION_FAILED, "total_weight_kg must be > 0", 400)
    for e in store.entries.values():
        if e["entry_number"] == entry_number:
            raise ApiError(ERR_VALIDATION_FAILED,
                           "entry_number %s already exists" % entry_number, 400)
    entry = new_entity(
        supplier_id=supplier_id,
        entry_number=entry_number,
        species_declared=species_declared,
        transport_mode=transport_mode,
        scheduled_arrival=scheduled_arrival,
        port_code=port_code,
        goods_value_cents=goods,
        freight_cost_cents=freight,
        duty_rate_pct=q2(duty_rate),
        total_weight_kg=q3(total_weight),
        prior_notice_filed_at=None,
        prior_notice_confirmation=None,
        entry_filed_at=None,
        duty_cents=None,
        allocatable_total_cents=None,
        status="DRAFT",
    )
    store.entries[entry["id"]] = entry
    return success(serialize_entry(entry), "object", 201)


@bp.route("/seafood/import-entries/<eid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_entry(eid):
    return success(serialize_entry(get_entry_or_404(eid)))


@bp.route("/seafood/import-entries", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_entries():
    items = list(store.entries.values())
    supplier_id = request.args.get("supplier_id")
    status = request.args.get("status")
    if supplier_id is not None:
        items = [e for e in items if e["supplier_id"] == supplier_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(items)
    return success([serialize_entry(e) for e in page], "array", 200, meta)


def _require_supplier_approved(entry):
    supplier = store.suppliers.get(entry["supplier_id"])
    if supplier is None or supplier["fsvp_status"] != "APPROVED":
        raise ApiError(
            ERR_SUPPLIER_NOT_APPROVED,
            "Supplier must be APPROVED at the time of filing", 422)


@bp.route("/seafood/import-entries/<eid>/file-prior-notice", methods=["POST"])
@require_roles(ROLE_IMPORT_COORDINATOR)
def file_prior_notice(eid):
    entry = get_entry_or_404(eid)
    if entry["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE,
                       "Prior notice can only be filed from DRAFT", 409)
    _require_supplier_approved(entry)
    lead = PRIOR_NOTICE_LEAD_HOURS[entry["transport_mode"]]
    deadline = entry["scheduled_arrival"] - timedelta(hours=lead)
    if store.clock > deadline:
        raise ApiError(
            ERR_PRIOR_NOTICE_WINDOW_MISSED,
            "Prior notice must be filed at least %d hours before scheduled arrival"
            % lead, 422)
    entry["status"] = "PRIOR_NOTICE_FILED"
    entry["prior_notice_filed_at"] = store.clock
    entry["prior_notice_confirmation"] = "PN" + _uuid.uuid4().hex[:12].upper()
    touch(entry)
    return success(serialize_entry(entry))


@bp.route("/seafood/import-entries/<eid>/file-entry", methods=["POST"])
@require_roles(ROLE_IMPORT_COORDINATOR)
def file_entry(eid):
    entry = get_entry_or_404(eid)
    if entry["status"] != "PRIOR_NOTICE_FILED":
        raise ApiError(ERR_INVALID_STATE,
                       "Entry summary can only be filed after prior notice", 409)
    _require_supplier_approved(entry)
    entry["status"] = "ENTRY_FILED"
    entry["entry_filed_at"] = store.clock
    touch(entry)
    return success(serialize_entry(entry))


def _release_entry(entry):
    entry["duty_cents"] = q0_int(
        Decimal(entry["goods_value_cents"]) * entry["duty_rate_pct"])
    entry["allocatable_total_cents"] = (
        entry["goods_value_cents"] + entry["freight_cost_cents"] + entry["duty_cents"])
    entry["status"] = "RELEASED"
    run_entry_cost_allocation(entry)
    touch(entry)


@bp.route("/seafood/import-entries/<eid>/fda-disposition", methods=["POST"])
@require_roles(ROLE_IMPORT_COORDINATOR)
def fda_disposition(eid):
    entry = get_entry_or_404(eid)
    body = get_body()
    outcome = req_enum(body, "outcome", ("RELEASED", "DETAINED", "REFUSED"))
    status = entry["status"]
    if status == "ENTRY_FILED":
        if outcome == "RELEASED":
            _release_entry(entry)
        elif outcome == "DETAINED":
            entry["status"] = "DETAINED"
            touch(entry)
        else:
            entry["status"] = "REFUSED"
            touch(entry)
    elif status == "DETAINED":
        if outcome == "RELEASED":
            _release_entry(entry)
        elif outcome == "REFUSED":
            entry["status"] = "REFUSED"
            touch(entry)
        else:
            raise ApiError(ERR_INVALID_STATE,
                           "DETAINED entry cannot be DETAINED again", 409)
    else:
        raise ApiError(
            ERR_INVALID_STATE,
            "FDA disposition not allowed from status %s" % status, 409)
    return success(serialize_entry(entry))


# ---------------------------------------------------------------- receipt lots
@bp.route("/seafood/receipt-lots", methods=["POST"])
@require_roles(ROLE_RECEIVING_INSPECTOR)
def create_lot():
    body = get_body()
    entry_id = body.get("import_entry_id")
    if isinstance(entry_id, str) and entry_id not in store.entries:
        raise ApiError(ERR_IMPORT_ENTRY_NOT_FOUND,
                       "Import entry %s not found" % entry_id, 404)
    entry_id = req_str(body, "import_entry_id")
    entry = store.entries[entry_id]
    vessel_name = req_str(body, "vessel_name")
    harvest_date = req_dt(body, "harvest_date")
    catch_area_code = req_str(body, "catch_area_code")
    harvest_country_code = req_str(body, "harvest_country_code")
    production_method = req_enum(body, "production_method", ("WILD", "FARMED"))
    species_declared = req_str(body, "species_declared")
    grade = req_enum(body, "grade", ("A", "B", "C"))
    quantity_received = req_num(body, "quantity_received_kg")
    if quantity_received <= 0:
        raise ApiError(ERR_VALIDATION_FAILED,
                       "quantity_received_kg must be > 0", 400)
    ice = opt_num(body, "ice_deduction_pct", Decimal("0"))
    if ice < 0 or ice > 50:
        raise ApiError(ERR_VALIDATION_FAILED,
                       "ice_deduction_pct must be within 0-50", 400)
    receiving_temp = req_num(body, "receiving_temp_c")
    freeze_protocol = opt_enum(body, "freeze_protocol",
                               ("NONE", "STANDARD", "BLAST", "COMBO"), "NONE")
    # p7: entry must be RELEASED
    if entry["status"] != "RELEASED":
        raise ApiError(ERR_ENTRY_NOT_RELEASED,
                       "Receipt lots can only be created against a RELEASED entry",
                       409)
    quantity_received = q3(quantity_received)
    ice = q2(ice)
    accepted = q3(quantity_received * (Decimal("1") - ice / Decimal("100")))
    lot = new_entity(
        import_entry_id=entry["id"],
        vessel_name=vessel_name,
        harvest_date=harvest_date,
        catch_area_code=catch_area_code,
        harvest_country_code=harvest_country_code,
        production_method=production_method,
        species_declared=species_declared,
        species_verified=None,
        grade=grade,
        quantity_received_kg=quantity_received,
        ice_deduction_pct=ice,
        quantity_accepted_kg=accepted,
        consumed_kg=Decimal("0.000"),
        receiving_temp_c=q1(receiving_temp),
        freeze_protocol=freeze_protocol,
        freeze_compliant=False,
        cumulative_abuse_minutes=0,
        mislabel_flag=False,
        allocated_cost_cents=0,
        status="UNDER_INSPECTION",
    )
    store.lots[lot["id"]] = lot
    return success(serialize_lot(lot), "object", 201)


@bp.route("/seafood/receipt-lots/<lid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_lot(lid):
    return success(serialize_lot(get_lot_or_404(lid)))


@bp.route("/seafood/receipt-lots", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_lots():
    items = list(store.lots.values())
    entry_id = request.args.get("import_entry_id")
    status = request.args.get("status")
    if entry_id is not None:
        items = [l for l in items if l["import_entry_id"] == entry_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, meta = paginate(items)
    return success([serialize_lot(l) for l in page], "array", 200, meta)


# ---- shared accept / quarantine-release gates (PRD §3.5 bullet order)
def _has_passing_verification(lot):
    return any(
        v["receipt_lot_id"] == lot["id"]
        and v["status"] in ("CONFIRMED", "RESOLVED_RELABELED")
        for v in store.verifications.values())


def _check_histamine_gate(lot):
    if lot["species_declared"] not in HISTAMINE_SUSCEPTIBLE_SPECIES:
        return
    ok = any(
        r.get("receipt_lot_id") == lot["id"]
        and r["hazard_type"] == "HISTAMINE"
        and r["verdict"] == "PASS"
        for r in store.haccp_records.values())
    if not ok:
        raise ApiError(
            ERR_HISTAMINE_CRITICAL_LIMIT,
            "Histamine-susceptible lot requires a PASS HISTAMINE record", 422)


def _check_abuse_gate(lot):
    if lot["cumulative_abuse_minutes"] >= 240:
        raise ApiError(
            ERR_TEMPERATURE_ABUSE_EXCEEDED,
            "cumulative_abuse_minutes must be < 240 to accept", 422)


def _check_freeze_gate(lot):
    if lot["freeze_protocol"] != "NONE" and not lot["freeze_compliant"]:
        raise ApiError(
            ERR_FREEZE_PROTOCOL_NOT_MET,
            "freeze_compliant must be true for freeze_protocol %s"
            % lot["freeze_protocol"], 422)


def _check_open_ca_gate(lot):
    for c in store.corrective_actions.values():
        if c.get("receipt_lot_id") == lot["id"] and c["status"] in OPEN_CA_STATUSES:
            raise ApiError(
                ERR_OPEN_CORRECTIVE_ACTIONS,
                "Lot has OPEN or INVESTIGATING corrective actions", 422)


def _accept_lot(lot):
    lot["status"] = "ACCEPTED"
    entry = store.entries.get(lot["import_entry_id"])
    if entry is not None:
        run_entry_cost_allocation(entry)
    touch(lot)


@bp.route("/seafood/receipt-lots/<lid>/accept", methods=["POST"])
@require_roles(ROLE_RECEIVING_INSPECTOR)
def accept_lot(lid):
    lot = get_lot_or_404(lid)
    if lot["status"] != "UNDER_INSPECTION":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an UNDER_INSPECTION lot can be accepted", 409)
    # PRD §3.5 bullet order: verification -> histamine -> abuse -> freeze -> CA
    if not _has_passing_verification(lot):
        raise ApiError(
            ERR_VERIFICATION_REQUIRED,
            "A CONFIRMED or RESOLVED_RELABELED species verification is required",
            422)
    _check_histamine_gate(lot)
    _check_abuse_gate(lot)
    _check_freeze_gate(lot)
    _check_open_ca_gate(lot)
    _accept_lot(lot)
    return success(serialize_lot(lot))


@bp.route("/seafood/receipt-lots/<lid>/reject", methods=["POST"])
@require_roles(ROLE_RECEIVING_INSPECTOR)
def reject_lot(lid):
    lot = get_lot_or_404(lid)
    get_body()  # reason accepted but not persisted on the lot
    if lot["status"] not in ("UNDER_INSPECTION", "QUARANTINED"):
        raise ApiError(ERR_INVALID_STATE,
                       "Only UNDER_INSPECTION or QUARANTINED lots can be rejected",
                       409)
    lot["status"] = "REJECTED"
    touch(lot)
    return success(serialize_lot(lot))


@bp.route("/seafood/receipt-lots/<lid>/quarantine", methods=["POST"])
@require_roles(ROLE_QA_TECH)
def quarantine_lot_endpoint(lid):
    lot = get_lot_or_404(lid)
    get_body()  # reason accepted but not persisted on the lot
    if lot["status"] not in ("UNDER_INSPECTION", "ACCEPTED"):
        raise ApiError(ERR_INVALID_STATE,
                       "Only UNDER_INSPECTION or ACCEPTED lots can be quarantined",
                       409)
    from services import quarantine_lot as _quarantine
    _quarantine(lot)
    return success(serialize_lot(lot))


@bp.route("/seafood/receipt-lots/<lid>/quarantine-release", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def quarantine_release(lid):
    lot = get_lot_or_404(lid)
    if lot["status"] != "QUARANTINED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a QUARANTINED lot can be released", 409)
    # PRD §3.5 quarantine-release order: open CA -> verification -> histamine
    # -> abuse -> freeze
    _check_open_ca_gate(lot)
    if not _has_passing_verification(lot):
        raise ApiError(
            ERR_VERIFICATION_REQUIRED,
            "A CONFIRMED or RESOLVED_RELABELED species verification is required",
            422)
    _check_histamine_gate(lot)
    _check_abuse_gate(lot)
    _check_freeze_gate(lot)
    _accept_lot(lot)
    return success(serialize_lot(lot))
