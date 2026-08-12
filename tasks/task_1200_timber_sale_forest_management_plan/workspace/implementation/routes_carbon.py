"""Carbon valuations and conservation enrollment."""
from decimal import Decimal

from flask import Blueprint, g

from core import (
    db, new_common, bump, pub, success, require_roles, get_body, check_known,
    f_str, f_int, f_num, f_date, err, paginate, get_tract, get_valuation,
    check_transition, parse_date_str, add_years_date, D, rhu,
)
from routes_sales import cancel_sale

bp = Blueprint("carbon", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")

VALUATION_TERMINAL = {"ACCEPTED", "REJECTED", "SUPERSEDED"}

DISCOUNT_RATE = Decimal("0.05")
CREDIT_YEARS = 20
CONSERVATION_PREMIUM = Decimal("1.10")

# contract states that block a conservation acceptance
NON_TERMINAL_CONTRACT_STATES = {"PENDING_BOND", "ACTIVE", "HARVESTING",
                                "SUSPENDED", "HARVEST_COMPLETE", "DEFAULTED"}
CANCELLABLE_SALE_STATES = {"DRAFT", "OFFERED", "BIDDING_OPEN",
                           "BIDDING_CLOSED", "NO_SALE"}


def _annuity_factor():
    # (1 - (1 + r)^(-n)) / r at full precision, no intermediate rounding
    return (Decimal("1") - (Decimal("1") + DISCOUNT_RATE) ** (-CREDIT_YEARS)) / DISCOUNT_RATE


@bp.route("/forestry/carbon-valuations", methods=["POST"])
@require_roles("Forester")
def create_valuation():
    body = get_body()
    tr = body.get("tract_id")
    if isinstance(tr, str):
        get_tract(tr)
    check_known(body, {"tract_id", "expected_tract_version",
                       "annual_credits_tco2e", "baseline_credits_tco2e",
                       "price_cents_per_tco2e", "estimated_timber_net_cents",
                       "enrollment_start"})
    tract_id = f_str(body, "tract_id")
    tract = get_tract(tract_id)
    expected = f_int(body, "expected_tract_version")
    annual = f_num(body, "annual_credits_tco2e", gt=0)
    baseline = f_num(body, "baseline_credits_tco2e", minv=0)
    if not baseline < annual:
        from core import bad_request
        bad_request("baseline_credits_tco2e must be < annual_credits_tco2e")
    price = f_int(body, "price_cents_per_tco2e", minv=1)
    estimated = f_int(body, "estimated_timber_net_cents", minv=0)
    enrollment_start = f_date(body, "enrollment_start")
    if tract["status"] != "OPEN":
        err("ERR_CONSERVATION_ENROLLMENT_CONFLICT", 409,
            "tract is not OPEN")
    if expected != tract["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_tract_version does not match tract version")
    annuity = _annuity_factor()
    gross_npv = rhu(D(annual) * D(price) * annuity)
    net_npv = rhu((D(annual) - D(baseline)) * D(price) * annuity)
    threshold = rhu(D(estimated) * CONSERVATION_PREMIUM)
    recommendation = ("CONSERVATION_FAVORED" if net_npv >= threshold
                      else "TIMBER_FAVORED")
    enrollment_end = add_years_date(parse_date_str(enrollment_start),
                                    CREDIT_YEARS).isoformat()
    # supersede a prior VALUED valuation on the tract
    for v in db["valuations"].values():
        if v["tract_id"] == tract_id and v["status"] == "VALUED":
            v["status"] = "SUPERSEDED"
            bump(v)
    ent = new_common({
        "tract_id": tract_id,
        "annual_credits_tco2e": annual,
        "baseline_credits_tco2e": baseline,
        "price_cents_per_tco2e": price,
        "estimated_timber_net_cents": estimated,
        "enrollment_start": enrollment_start,
        "enrollment_end": enrollment_end,
        "gross_npv_cents": gross_npv,
        "net_npv_cents": net_npv,
        "recommendation": recommendation,
        "status": "VALUED",
    })
    db["valuations"][ent["id"]] = ent
    bump(tract)
    return success(pub(ent), 201)


@bp.route("/forestry/carbon-valuations/<vid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_valuation_ep(vid):
    return success(pub(get_valuation(vid)), 200)


@bp.route("/forestry/carbon-valuations", methods=["GET"])
@require_roles(*READ_ROLES)
def list_valuations():
    page, meta = paginate(db["valuations"].values(), {
        "tract_id": "tract_id",
        "status": "status",
    })
    return success([pub(v) for v in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/carbon-valuations/<vid>/accept", methods=["POST"])
@require_roles("Landowner")
def accept_valuation(vid):
    v = get_valuation(vid)
    body = get_body()
    check_known(body, set())
    tract = get_tract(v["tract_id"])
    if tract["landowner_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "landowner does not own this tract")
    check_transition(v, {"VALUED"}, VALUATION_TERMINAL, "valuation")
    # blocked while any contract on any sale of the tract is live
    tract_sale_ids = {s["id"] for s in db["sales"].values()
                      if s["tract_id"] == tract["id"]}
    for c in db["contracts"].values():
        if (c["sale_id"] in tract_sale_ids
                and c["status"] in NON_TERMINAL_CONTRACT_STATES):
            err("ERR_ACTIVE_CONTRACT_BLOCKS_CONSERVATION", 409,
                "a live contract on this tract blocks conservation")
    v["status"] = "ACCEPTED"
    bump(v)
    # enroll the tract
    tract["status"] = "ENROLLED_CONSERVATION"
    tract["conservation_enrollment_start"] = v["enrollment_start"]
    tract["conservation_enrollment_end"] = v["enrollment_end"]
    bump(tract)
    # cancel open sales (and withdraw their SUBMITTED bids)
    for s in db["sales"].values():
        if s["tract_id"] == tract["id"] and s["status"] in CANCELLABLE_SALE_STATES:
            cancel_sale(s)
    return success(pub(v), 200)


@bp.route("/forestry/carbon-valuations/<vid>/reject", methods=["POST"])
@require_roles("Landowner")
def reject_valuation(vid):
    v = get_valuation(vid)
    body = get_body()
    check_known(body, set())
    tract = get_tract(v["tract_id"])
    if tract["landowner_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "landowner does not own this tract")
    check_transition(v, {"VALUED"}, VALUATION_TERMINAL, "valuation")
    v["status"] = "REJECTED"
    bump(v)
    return success(pub(v), 200)
