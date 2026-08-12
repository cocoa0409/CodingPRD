"""Scale tickets: log rules, overrun allowance, verify/dispute/resolve."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from flask import Blueprint, g

from core import (
    db, new_common, bump, pub, success, require_roles, get_body, check_known,
    f_str, f_int, f_num, f_date, f_enum, err, paginate, get_contract,
    get_ticket, sale_of_contract, prescription_of_sale, tract_of_contract,
    check_transition, now, now_iso, D, rhu, parse_iso_datetime,
)

bp = Blueprint("tickets", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")

TICKET_TERMINAL = {"VOID"}
OVERRUN_ALLOWANCE_PCT = Decimal("110.00")
DISPUTE_WINDOW_DAYS = 10


def _certified_volumes_for_contract(contract):
    sale = sale_of_contract(contract)
    prescription = prescription_of_sale(sale)
    cruise = db["cruises"].get(prescription["cruise_id"])
    if not cruise or not cruise.get("certified_volume_by_species"):
        return {}
    return {e["species"]: e["volume_bf"]
            for e in cruise["certified_volume_by_species"]}


@bp.route("/forestry/scale-tickets", methods=["POST"])
@require_roles("Contractor", "Forester")
def create_ticket():
    body = get_body()
    c_ref = body.get("contract_id")
    if isinstance(c_ref, str):
        get_contract(c_ref)
    check_known(body, {"contract_id", "scaled_date", "species",
                       "small_end_diameter_in", "length_ft", "log_count"})
    contract_id = f_str(body, "contract_id")
    contract = get_contract(contract_id)
    # ownership: a Contractor may record only on contracts assigned to them
    if g.role == "Contractor" and contract["contractor_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "contract is not assigned to this contractor")
    scaled_date = f_date(body, "scaled_date")
    species = f_str(body, "species")
    diam = f_num(body, "small_end_diameter_in", gt=0)
    length = f_num(body, "length_ft", gt=0)
    log_count = f_int(body, "log_count", minv=1)
    if contract["status"] != "HARVESTING":
        err("ERR_CONTRACT_SUSPENDED", 409,
            "scale tickets require a HARVESTING contract")
    # log rules: per-log rounding BEFORE multiplying by log_count
    Dd = D(diam)
    Ll = D(length)
    doyle_per = int(((((Dd - 4) / 4) ** 2) * Ll).to_integral_value(
        rounding=ROUND_FLOOR))
    intl_per = rhu((Decimal("0.79") * Dd * Dd - 2 * Dd - 4) * Ll / 16)
    bf_doyle = doyle_per * log_count
    bf_international = intl_per * log_count
    bf_governing = (bf_doyle if contract["governing_scaling_rule"] == "DOYLE"
                    else bf_international)
    # overrun allowance: cumulative non-VOID bf per species vs 110% certified
    volumes = _certified_volumes_for_contract(contract)
    allowance = rhu(D(volumes.get(species, 0)) * OVERRUN_ALLOWANCE_PCT / 100)
    cumulative = 0
    for t in db["tickets"].values():
        if (t["contract_id"] == contract["id"] and t["species"] == species
                and t["status"] in ("DRAFT", "VERIFIED", "DISPUTED")):
            cumulative += t["bf_governing"]
    if cumulative + bf_governing > allowance:
        err("ERR_VOLUME_ALLOWANCE_EXCEEDED", 422,
            "cumulative species volume exceeds 110%% of certified volume")
    ent = new_common({
        "contract_id": contract_id,
        "scaled_date": scaled_date,
        "species": species,
        "small_end_diameter_in": diam,
        "length_ft": length,
        "log_count": log_count,
        "bf_doyle": bf_doyle,
        "bf_international": bf_international,
        "bf_governing": bf_governing,
        "status": "DRAFT",
        "flagged_for_review": False,
        "recorded_by_id": g.uid,
        "verified_by_id": None,
        "verified_at": None,
    })
    db["tickets"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/scale-tickets/<tid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_ticket_ep(tid):
    return success(pub(get_ticket(tid)), 200)


@bp.route("/forestry/scale-tickets", methods=["GET"])
@require_roles(*READ_ROLES)
def list_tickets():
    page, meta = paginate(db["tickets"].values(), {
        "contract_id": "contract_id",
        "status": "status",
    })
    return success([pub(t) for t in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/scale-tickets/<tid>/verify", methods=["POST"])
@require_roles("Forester")
def verify_ticket(tid):
    t = get_ticket(tid)
    body = get_body()
    check_known(body, set())
    check_transition(t, {"DRAFT"}, TICKET_TERMINAL, "scale ticket")
    contract = get_contract(t["contract_id"])
    if contract["status"] != "HARVESTING":
        err("ERR_CONTRACT_SUSPENDED", 409,
            "ticket verification requires a HARVESTING contract")
    if g.uid == t["recorded_by_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403,
            "verifier must differ from the recorder")
    t["status"] = "VERIFIED"
    t["verified_at"] = now_iso()
    t["verified_by_id"] = g.uid
    t["flagged_for_review"] = False
    bump(t)
    bump(contract)
    return success(pub(t), 200)


@bp.route("/forestry/scale-tickets/<tid>/dispute", methods=["POST"])
@require_roles("Landowner", "Buyer")
def dispute_ticket(tid):
    t = get_ticket(tid)
    body = get_body()
    check_known(body, {"reason"})
    f_str(body, "reason", required=False)
    contract = get_contract(t["contract_id"])
    if g.role == "Landowner":
        tract = tract_of_contract(contract)
        if tract is None or tract["landowner_id"] != g.uid:
            err("ERR_NOT_RESOURCE_OWNER", 403,
                "landowner does not own this tract")
    else:  # Buyer
        if contract["buyer_id"] != g.uid:
            err("ERR_NOT_RESOURCE_OWNER", 403,
                "contract does not belong to buyer")
    check_transition(t, {"VERIFIED"}, TICKET_TERMINAL, "scale ticket")
    if now() > parse_iso_datetime(t["verified_at"]) + timedelta(
            days=DISPUTE_WINDOW_DAYS):
        err("ERR_DISPUTE_WINDOW_PASSED", 422,
            "dispute window (10 days) has passed")
    t["status"] = "DISPUTED"
    bump(t)
    return success(pub(t), 200)


@bp.route("/forestry/scale-tickets/<tid>/resolve", methods=["POST"])
@require_roles("Forester")
def resolve_ticket(tid):
    t = get_ticket(tid)
    body = get_body()
    check_known(body, {"resolution"})
    resolution = f_enum(body, "resolution", {"ACCEPT", "VOID"})
    check_transition(t, {"DISPUTED"}, TICKET_TERMINAL, "scale ticket")
    t["status"] = "VERIFIED" if resolution == "ACCEPT" else "VOID"
    bump(t)
    return success(pub(t), 200)


@bp.route("/forestry/scale-tickets/<tid>/void", methods=["POST"])
@require_roles("Forester")
def void_ticket(tid):
    t = get_ticket(tid)
    body = get_body()
    check_known(body, set())
    check_transition(t, {"DRAFT"}, TICKET_TERMINAL, "scale ticket")
    t["status"] = "VOID"
    bump(t)
    return success(pub(t), 200)
