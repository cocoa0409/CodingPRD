"""SoiledManifest endpoints (PRD 3.4, 3.5)."""
from decimal import Decimal

from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_ALREADY_TERMINAL, ERR_CART_RUN_ALREADY_LINKED, \
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_ISOLATION_PROTOCOL_REQUIRED, \
    ERR_NEGATIVE_INVENTORY, ERR_NOT_FOUND, raise_err
from serializers import manifest_out
from util import body_json, bump, fk_ref, get_or_404, list_response, new_record, \
    opt_bool, rhu0, dec, success_object

bp = Blueprint("manifests", __name__)


@bp.route("/soiled-manifests", methods=["POST"])
def create_manifest():
    uid, role = authenticate()
    authorize(role, ["EVSOperator"])
    body = body_json()

    fac = fk_ref(body, "facility_id", store.facilities, "Facility")

    # cart_run_ids: each element must exist and belong to the facility
    raw_run_ids = body.get("cart_run_ids")
    if not isinstance(raw_run_ids, list):
        raise_err(ERR_INVALID_REQUEST, "cart_run_ids is required and must be a list")
    runs = []
    for rid in raw_run_ids:
        r = store.cart_runs.get(rid) if isinstance(rid, str) else None
        if r is None:
            raise_err(ERR_NOT_FOUND, "CartExchangeRun not found: %s" % rid)
        run_unit = store.units.get(r["unit_id"])
        if run_unit is None or run_unit["facility_id"] != fac["id"]:
            raise_err(ERR_NOT_FOUND,
                      "CartExchangeRun %s is outside facility %s" % (rid, fac["id"]))
        runs.append(r)

    # lines: stock FK existence + facility scope, then per-line shape
    raw_lines = body.get("lines")
    if not isinstance(raw_lines, list):
        raise_err(ERR_INVALID_REQUEST, "lines is required and must be a list")
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "lines entries must be objects")
        sid = entry.get("stock_id")
        stock = store.stocks.get(sid) if isinstance(sid, str) else None
        if stock is None:
            raise_err(ERR_NOT_FOUND, "LinenStock not found: %s" % sid)
        if stock["facility_id"] != fac["id"]:
            raise_err(ERR_NOT_FOUND,
                      "LinenStock %s is outside facility %s" % (sid, fac["id"]))
    parsed_lines = []
    for entry in raw_lines:
        weight = entry.get("weight_lbs")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            raise_err(ERR_INVALID_REQUEST, "lines.weight_lbs must be a number > 0")
        iso = entry.get("isolation_flag")
        if not isinstance(iso, bool):
            raise_err(ERR_INVALID_REQUEST, "lines.isolation_flag must be a boolean")
        parsed_lines.append({
            "stock_id": entry["stock_id"],
            "weight_lbs": weight,
            "isolation_flag": iso,
        })
    ack = opt_bool(body, "isolation_protocol_ack", False)

    # safety (priority 8): isolation handling acknowledgement
    if any(l["isolation_flag"] for l in parsed_lines) and ack is not True:
        raise_err(ERR_ISOLATION_PROTOCOL_REQUIRED,
                  "isolation-flagged lines require isolation_protocol_ack true")

    # referential (priority 10): linked runs must be RECONCILED and unlinked
    for r in runs:
        if r["status"] != "RECONCILED" or r["manifest_id"] is not None:
            raise_err(ERR_CART_RUN_ALREADY_LINKED,
                      "cart run %s is already linked or not RECONCILED" % r["id"])

    # expected_pieces per line (round_half_up(weight / piece_weight))
    for line in parsed_lines:
        stock = store.stocks[line["stock_id"]]
        line["expected_pieces"] = rhu0(dec(line["weight_lbs"]) / dec(stock["piece_weight_lbs"]))

    # dock-scale recount adjustment: in_wash += expected - soiled recorded
    # for that stock across the linked cart runs
    soiled_totals = {}
    for r in runs:
        for e in r["soiled_lines"]:
            soiled_totals[e["stock_id"]] = soiled_totals.get(e["stock_id"], 0) + e["pieces"]
    touched = set()
    for line in parsed_lines:
        stock = store.stocks[line["stock_id"]]
        delta = line["expected_pieces"] - soiled_totals.get(line["stock_id"], 0)
        if delta != 0:
            stock["in_wash"] += delta
            touched.add(stock["id"])
    for sid in touched:
        bump(store.stocks[sid])

    rec = new_record()
    rec.update({
        "facility_id": fac["id"],
        "invoice_id": None,
        "lines": parsed_lines,
        "isolation_protocol_ack": ack,
        "returned_lines": [],
        "status": "DISPATCHED",
        "recorded_by_user_id": uid,
    })
    store.manifests[rec["id"]] = rec

    for r in runs:
        r["manifest_id"] = rec["id"]
        bump(r)

    return success_object(manifest_out(rec), 201)


@bp.route("/soiled-manifests/<manifest_id>", methods=["GET"])
def get_manifest(manifest_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.manifests, manifest_id, "SoiledManifest")
    return success_object(manifest_out(rec))


@bp.route("/soiled-manifests", methods=["GET"])
def list_manifests():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.manifests.values())
    facility_id = request.args.get("facility_id")
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    invoice_id = request.args.get("invoice_id")
    if invoice_id is not None:
        records = [r for r in records if r["invoice_id"] == invoice_id]
    return list_response(records, manifest_out)


def _returned_lines_shape(body):
    raw = body.get("returned_lines")
    if not isinstance(raw, list):
        raise_err(ERR_INVALID_REQUEST, "returned_lines is required and must be a list")
    for entry in raw:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "returned_lines entries must be objects")
        sid = entry.get("stock_id")
        if not isinstance(sid, str) or sid not in store.stocks:
            raise_err(ERR_NOT_FOUND, "LinenStock not found: %s" % sid)
    out = []
    for entry in raw:
        pieces = entry.get("pieces")
        condemned = entry.get("condemned_pieces")
        for key, v in (("pieces", pieces), ("condemned_pieces", condemned)):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise_err(ERR_INVALID_REQUEST,
                          "returned_lines.%s must be an integer >= 0" % key)
        out.append({
            "stock_id": entry["stock_id"],
            "pieces": pieces,
            "condemned_pieces": condemned,
        })
    return out


@bp.route("/soiled-manifests/<manifest_id>/return", methods=["POST"])
def return_manifest(manifest_id):
    """wash_life_retirement calc (PRD 3.5): FIFO-crossing retirement on the
    cumulative wash count; condemned and retired pieces leave circulation."""
    _, role = authenticate()
    authorize(role, ["LaundryVendor"])
    manifest = get_or_404(store.manifests, manifest_id, "SoiledManifest")
    body = body_json()

    returned = _returned_lines_shape(body)
    # every returned line's stock must appear among the manifest's lines
    for rl in returned:
        if services.find_manifest_line(manifest, rl["stock_id"]) is None:
            raise_err(ERR_INVALID_REQUEST,
                      "stock %s does not appear in the manifest's lines" % rl["stock_id"])

    # state guard (priority 7)
    if manifest["status"] == "RECONCILED":
        raise_err(ERR_ALREADY_TERMINAL, "manifest is RECONCILED (terminal)")
    if manifest["status"] != "DISPATCHED":
        raise_err(ERR_INVALID_STATE,
                  "return requires status DISPATCHED, got %s" % manifest["status"])

    # fiscal guard (priority 11), all lines checked before any mutation
    lost_by_stock = {}
    pending = {}
    for rl in returned:
        line = services.find_manifest_line(manifest, rl["stock_id"])
        lost = max(0, line["expected_pieces"] - rl["pieces"] - rl["condemned_pieces"])
        lost_by_stock[rl["stock_id"]] = lost_by_stock.get(rl["stock_id"], 0) + lost
        stock = store.stocks[rl["stock_id"]]
        need = rl["pieces"] + rl["condemned_pieces"] + lost
        if stock["in_wash"] - pending.get(stock["id"], 0) - need < 0:
            raise_err(ERR_NEGATIVE_INVENTORY,
                      "return would drive in_wash negative for stock %s" % stock["id"])
        pending[stock["id"]] = pending.get(stock["id"], 0) + need

    touched = []
    for rl in returned:
        stock = store.stocks[rl["stock_id"]]
        before = stock["wash_cycles_completed"]
        stock["wash_cycles_completed"] += rl["pieces"]
        newly_retired = min(
            rl["pieces"],
            (stock["wash_cycles_completed"] // stock["max_wash_cycles"])
            - (before // stock["max_wash_cycles"]),
        )
        lost = max(0, services.find_manifest_line(manifest, rl["stock_id"])["expected_pieces"]
                   - rl["pieces"] - rl["condemned_pieces"])
        stock["retired_pieces"] += rl["condemned_pieces"] + newly_retired
        stock["in_circulation"] += rl["pieces"] - newly_retired
        stock["in_wash"] -= rl["pieces"] + rl["condemned_pieces"] + lost
        if stock["id"] not in touched:
            touched.append(stock["id"])
    for sid in touched:
        bump(store.stocks[sid])

    manifest["returned_lines"] = returned
    manifest["status"] = "RETURNED"
    bump(manifest)
    return success_object(manifest_out(manifest), 200)


@bp.route("/soiled-manifests/<manifest_id>/reconcile", methods=["POST"])
def reconcile_manifest(manifest_id):
    """loss_rate_pct calc (PRD 3.5): cumulative over RECONCILED manifests,
    2dp round-half-up, INVESTIGATION at >= 5.00 (sticky). VERIFIED complaints
    on this manifest auto-resolve."""
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    manifest = get_or_404(store.manifests, manifest_id, "SoiledManifest")
    body_json()

    if manifest["status"] == "RECONCILED":
        raise_err(ERR_ALREADY_TERMINAL, "manifest is RECONCILED (terminal)")
    if manifest["status"] != "RETURNED":
        raise_err(ERR_INVALID_STATE,
                  "reconcile requires status RETURNED, got %s" % manifest["status"])

    manifest["status"] = "RECONCILED"
    bump(manifest)

    changed_stocks = {}
    ordered_ids = []
    for line in manifest["lines"]:
        rl = services.find_returned_line(manifest, line["stock_id"])
        pieces = rl["pieces"] if rl else 0
        condemned = rl["condemned_pieces"] if rl else 0
        lost = max(0, line["expected_pieces"] - pieces - condemned)
        stock = store.stocks[line["stock_id"]]
        if stock["id"] not in changed_stocks:
            changed_stocks[stock["id"]] = False
            ordered_ids.append(stock["id"])
        if lost:
            stock["lost_pieces"] += lost
            changed_stocks[stock["id"]] = True

    for sid in ordered_ids:
        stock = store.stocks[sid]
        rate = services.loss_rate_reached(stock)
        if rate >= Decimal("5.00") and stock["shrinkage_status"] != "INVESTIGATION":
            stock["shrinkage_status"] = "INVESTIGATION"
            changed_stocks[sid] = True
        if changed_stocks[sid]:
            bump(stock)

    for c in store.complaints.values():
        if c["manifest_id"] == manifest["id"] and c["status"] == "VERIFIED":
            c["status"] = "RESOLVED"
            bump(c)

    return success_object(manifest_out(manifest), 200)
