"""CertifiedCopyRequest endpoints (PRD 3.6, 2.7)."""
from flask import Blueprint, g, request

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from util import new_common, serialize, touch
from services.common import (
    get_body, require_fields, require_str, require_enum, require_int, lookup,
    parse_pagination, sort_by_created,
)
from services import calculations as calc
from services import ledger as ledger_svc
from services import derived

bp = Blueprint("certified_copies", __name__)

REQUESTER_KINDS = {"PARTY", "GOVERNMENT", "PUBLIC"}


def _record_parties(record):
    app = None
    lic = store.licenses.get(record["license_id"])
    if lic is not None:
        app = store.applications.get(lic["application_id"])
    if app is None:
        return set()
    return {app["applicant_a_id"], app["applicant_b_id"]}


@bp.route("/certified-copies", methods=["POST"])
@require_roles("Clerk", "Applicant")
def create_copy():
    body = get_body()
    require_fields(body, "record_id", "requester_kind", "copies_requested")
    require_str(body["record_id"], "record_id")
    require_enum(body["requester_kind"], REQUESTER_KINDS, "requester_kind")
    require_int(body["copies_requested"], "copies_requested", minimum=1)

    # Existence: record_id, then optional fee_waiver_id.
    lookup("record", body["record_id"])
    fee_waiver_id = body.get("fee_waiver_id")
    if fee_waiver_id is not None:
        require_str(fee_waiver_id, "fee_waiver_id")
        lookup("fee_waiver", fee_waiver_id)

    ent = new_common("certified_copy")
    ent.update({
        "record_id": body["record_id"],
        "requester_kind": body["requester_kind"],
        "copies_requested": body["copies_requested"],
        "fee_waiver_id": fee_waiver_id,
        "status": "PENDING",
        "issued_by_user_id": None,
        "fee_cents": 0,
    })
    store.certified_copies[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/certified-copies", methods=["GET"])
@require_roles("Clerk", "Registrar")
def list_copies():
    limit, offset = parse_pagination()
    record_filter = request.args.get("record_id")
    waiver_filter = request.args.get("fee_waiver_id")
    items = list(store.certified_copies.values())
    if record_filter is not None:
        items = [c for c in items if c["record_id"] == record_filter]
    if waiver_filter is not None:
        items = [c for c in items if c["fee_waiver_id"] == waiver_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(c) for c in page], limit, offset, total)


@bp.route("/certified-copies/<copy_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def get_copy(copy_id):
    ent = lookup("certified_copy", copy_id)
    return success(serialize(ent), status=200)


@bp.route("/certified-copies/<copy_id>/decide", methods=["POST"])
@require_roles("Clerk")
def decide_copy(copy_id):
    copy = lookup("certified_copy", copy_id)
    body = get_body()
    require_fields(body, "decision")
    require_enum(body["decision"], {"ISSUE", "DENY"}, "decision")
    decision = body["decision"]

    record = store.records.get(copy["record_id"])
    waiver = store.fee_waivers.get(copy["fee_waiver_id"]) if copy.get("fee_waiver_id") else None

    # OCC (priority 5) — checked before the state gate (PRD 2.7, 3.10).
    exp_record_v = body.get("expected_record_version")
    if exp_record_v is not None:
        if record is None or exp_record_v != record["version"]:
            raise ApiError("ERR_STALE_VERSION", "Stale record version")
    exp_waiver_v = body.get("expected_waiver_version")
    if exp_waiver_v is not None:
        if waiver is None or exp_waiver_v != waiver["version"]:
            raise ApiError("ERR_STALE_VERSION", "Stale waiver version")

    # State gate (priority 6).
    if copy["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Copy request is not PENDING")

    if decision == "DENY":
        copy["status"] = "DENIED"
        touch(copy)
        return success(serialize(copy), status=200)

    # ISSUE — business preconditions in PRD 3.6 order.
    # 1) Sealed record may be copied only for GOVERNMENT.
    if record["status"] == "SEALED" and copy["requester_kind"] != "GOVERNMENT":
        raise ApiError("ERR_RECORD_SEALED", "Sealed record requires a GOVERNMENT requester")
    # 2) Confidential record requires PARTY or GOVERNMENT.
    if record["is_confidential"] and copy["requester_kind"] not in ("PARTY", "GOVERNMENT"):
        raise ApiError("ERR_CONFIDENTIAL_ACCESS_DENIED", "Confidential record access denied")
    # 3) Waiver checks.
    if waiver is not None:
        parties = _record_parties(record)
        if waiver["status"] != "GRANTED" or waiver["applicant_id"] not in parties:
            raise ApiError("ERR_WAIVER_NOT_GRANTED", "Waiver is not granted or not a record party's")
        # 4) Segregation: issuing clerk must differ from waiver adjudicator.
        if waiver.get("adjudicated_by_user_id") is not None \
                and g.user_id == waiver["adjudicated_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "Clerk cannot consume a waiver they adjudicated")

    # Compute fee: tier -> surcharge -> gov-exempt -> waiver.
    gross = calc.certified_copy_gross(
        copy["copies_requested"], record["is_confidential"], copy["requester_kind"]
    )
    absorbed = 0
    if waiver is not None:
        absorbed, fee_cents = calc.waiver_absorption(gross, waiver)
    else:
        fee_cents = gross

    copy["status"] = "ISSUED"
    copy["issued_by_user_id"] = g.user_id
    copy["fee_cents"] = fee_cents
    copy["_absorbed_cents"] = absorbed
    touch(copy)

    # Ledger: CHARGE for the net fee.
    app = _owning_application(record)
    app_id = app["id"] if app else None
    ledger_svc.append_entry(app_id, "CHARGE", fee_cents, "CERTIFIED_COPY", copy["id"])

    if waiver is not None and absorbed > 0:
        ledger_svc.append_entry(app_id, "WAIVE", absorbed, "CERTIFIED_COPY", copy["id"])
        waiver["consumed_cents"] += absorbed
        if waiver["consumed_cents"] >= waiver["max_waivable_cents"]:
            waiver["status"] = "CONSUMED"
        touch(waiver)

    derived.recompute_and_store_certified_copies_issued(record)
    if app is not None:
        ledger_svc.recompute_total_charged(app)

    return success(serialize(copy), status=200)


@bp.route("/certified-copies/<copy_id>/refund", methods=["POST"])
@require_roles("Clerk")
def refund_copy(copy_id):
    copy = lookup("certified_copy", copy_id)
    if copy["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Copy request is not ISSUED")

    record = store.records.get(copy["record_id"])
    app = _owning_application(record) if record else None
    app_id = app["id"] if app else None

    copy["status"] = "REFUNDED"
    touch(copy)

    ledger_svc.append_entry(app_id, "REFUND", copy["fee_cents"], "CERTIFIED_COPY", copy["id"])

    absorbed = copy.get("_absorbed_cents", 0)
    waiver = store.fee_waivers.get(copy["fee_waiver_id"]) if copy.get("fee_waiver_id") else None
    if waiver is not None and absorbed > 0:
        # Reverse the absorption: offsetting WAIVE entry for the negative amount.
        ledger_svc.append_entry(app_id, "WAIVE", -absorbed, "CERTIFIED_COPY", copy["id"])
        waiver["consumed_cents"] -= absorbed
        if waiver["status"] == "CONSUMED":
            waiver["status"] = "GRANTED"
        touch(waiver)

    if record is not None:
        derived.recompute_and_store_certified_copies_issued(record)
    if app is not None:
        ledger_svc.recompute_total_charged(app)

    return success(serialize(copy), status=200)


@bp.route("/certified-copies/<copy_id>/apostilles", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def list_copy_apostilles(copy_id):
    lookup("certified_copy", copy_id)
    limit, offset = parse_pagination()
    items = [a for a in store.apostilles.values() if a["copy_request_id"] == copy_id]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(a) for a in page], limit, offset, total)


def _owning_application(record):
    if record is None:
        return None
    lic = store.licenses.get(record["license_id"])
    if lic is None:
        return None
    return store.applications.get(lic["application_id"])
