from flask import Blueprint

from store import touch, ser, parcels_of_district, rolls_of_district, bonds_of_district
from web import protected, ok, ApiError
from fetch import get_bond, get_district
import logic
from util import rhu, to_fraction

bp = Blueprint("bonds", __name__)


def _window(bond):
    start = bond["issuance_date"].year
    return start, start + bond["term_years"]


@bp.post("/bonds/<bid>/issue")
@protected(["DistrictAdministrator"])
def issue_bond(bid):
    bond = get_bond(bid)
    if bond["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_BOND_STATE")
    district = get_district(bond["district_id"])
    if not any(r["status"] == "CONFIRMED" for r in rolls_of_district(district["id"])):
        raise ApiError("ERR_NO_CONFIRMED_ROLL")

    s0, e0 = _window(bond)
    for other in bonds_of_district(district["id"]):
        if other["id"] == bond["id"] or other["status"] != "ISSUED":
            continue
        s1, e1 = _window(other)
        if s0 < e1 and s1 < e0:  # half-open overlap
            raise ApiError("ERR_BOND_TERM_OVERLAP")

    tap = district["total_apportioned_principal_cents"] or 0
    reserve = rhu(to_fraction(tap) * to_fraction(bond["reserve_fund_pct"]))
    bond["reserve_fund_cents"] = reserve
    bond["par_amount_cents"] = tap + reserve + bond["issuance_cost_cents"]

    for p in parcels_of_district(district["id"]):
        if p["status"] == "ACTIVE":
            logic.generate_installments(p, bond, p["assessed_principal_cents"])

    bond["status"] = "ISSUED"
    touch(bond)
    return ok(ser(bond))
