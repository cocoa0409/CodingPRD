"""UncertainTaxPosition endpoints: identify, list, get (interest recomputed on
read), measure (with the strict >50% recognition threshold), disclose
(cross-aggregate gate on a READY/FILED/ACCEPTED filing for the pair), settle.
"""
from flask import Blueprint

from db import db, new_record, touch, bump_year
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_TAX_YEAR_NOT_OPEN,
    ERR_PROBABILITY_OUT_OF_RANGE,
    ERR_INVALID_AMOUNT,
    ERR_RETURN_NOT_READY,
)
from middleware import authorized, READER_ROLES
from response import success_object, success_list
from routes.common import get_or_404, apply_filters, paginate
from serializers import serialize, serialize_utp
from services.calc import (
    compute_utp_measurement,
    compute_utp_interest,
    recompute_utp_reserve,
    recompute_etrs,
)
from util import CLOCK
from validate import body_json, present_int, req_str, req_int

bp = Blueprint("utps", __name__)

# UTP identification is admitted in every pre-CLOSED posture (PRD §3.4).
_UTP_CREATE_POSTURES = ("OPEN", "PROVISION_LOCKED", "RETURNS_FILED")


@bp.route("/tax/uncertain-tax-positions", methods=["POST"])
def create_utp():
    authorized(("TaxAccountant",))
    data = body_json()

    # Priority 3 (existence): body FK references resolve.
    tax_year_id = data.get("tax_year_id")
    year = None
    if isinstance(tax_year_id, str):
        year = get_or_404(db.tax_years, tax_year_id, "TaxYear")
    jur_probe = data.get("jurisdiction_id")
    if isinstance(jur_probe, str):
        get_or_404(db.jurisdictions, jur_probe, "Jurisdiction")

    # Priority 5 (tax-year posture): not admitted once the year is CLOSED.
    if year is not None and year["status"] not in _UTP_CREATE_POSTURES:
        raise_error(ERR_TAX_YEAR_NOT_OPEN,
                    "uncertain tax positions may be identified only before the year is CLOSED")

    # Priority 10 (amount sanity): the claimed benefit must be positive.
    amount_probe = present_int(data, "position_amount_cents")
    if amount_probe is not None and amount_probe <= 0:
        raise_error(ERR_INVALID_AMOUNT, "position_amount_cents must be > 0")

    # Priority 11 (structural).
    tax_year_id = req_str(data, "tax_year_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    description = req_str(data, "description")
    position_amount = req_int(data, "position_amount_cents")
    if year is None:
        raise_error(ERR_NOT_FOUND, f"TaxYear '{tax_year_id}' does not exist")
    get_or_404(db.jurisdictions, jurisdiction_id, "Jurisdiction")

    pos = new_record({
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "description": description,
        "position_amount_cents": position_amount,
        "cumulative_probability_bp": None,
        "recognized_benefit_cents": 0,
        "liability_cents": 0,
        "measured_on": None,
        "interest_accrued_cents": 0,
        "disclosure_required": False,
        "settled_amount_cents": None,
        "status": "IDENTIFIED",
    })
    db.utps[pos["id"]] = pos
    return success_object(serialize_utp(pos), status=201)


@bp.route("/tax/uncertain-tax-positions", methods=["GET"])
def list_utps():
    authorized(READER_ROLES)
    recs = apply_filters(db.utps.values(), {
        "tax_year_id": "tax_year_id",
        "jurisdiction_id": "jurisdiction_id",
        "status": "status",
    })
    page, total, limit, offset = paginate(recs)
    return success_list([serialize_utp(r) for r in page], total, limit, offset)


@bp.route("/tax/uncertain-tax-positions/<positionId>", methods=["GET"])
def get_utp(positionId):
    authorized(READER_ROLES)
    return success_object(serialize_utp(get_or_404(db.utps, positionId, "UncertainTaxPosition")))


@bp.route("/tax/uncertain-tax-positions/<positionId>/measure", methods=["POST"])
def measure_utp(positionId):
    authorized(("TaxManager",))
    pos = get_or_404(db.utps, positionId, "UncertainTaxPosition")
    if pos["status"] not in ("IDENTIFIED", "MEASURED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"measure is not defined from position status {pos['status']}")
    data = body_json()

    # Priority 10: cumulative probability must lie within 0..10000.
    prob_probe = present_int(data, "cumulative_probability_bp")
    if prob_probe is not None and not (0 <= prob_probe <= 10000):
        raise_error(ERR_PROBABILITY_OUT_OF_RANGE,
                    "cumulative_probability_bp must be within 0..10000")

    # Priority 11 (structural).
    prob = req_int(data, "cumulative_probability_bp")

    recognized, liability, disclosure_required = compute_utp_measurement(
        pos["position_amount_cents"], prob)
    pos["cumulative_probability_bp"] = prob
    pos["recognized_benefit_cents"] = recognized
    pos["liability_cents"] = liability
    pos["disclosure_required"] = disclosure_required
    pos["measured_on"] = CLOCK.today().isoformat()
    pos["interest_accrued_cents"] = compute_utp_interest(pos, CLOCK.today())
    pos["status"] = "MEASURED"
    touch(pos)

    year = db.tax_years.get(pos["tax_year_id"])
    if year is not None:
        recompute_utp_reserve(year)
        recompute_etrs(year)
        bump_year(year)
    return success_object(serialize_utp(pos))


@bp.route("/tax/uncertain-tax-positions/<positionId>/disclose", methods=["POST"])
def disclose_utp(positionId):
    authorized(("TaxManager",))
    pos = get_or_404(db.utps, positionId, "UncertainTaxPosition")
    if pos["status"] != "MEASURED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"disclose is not defined from position status {pos['status']}")

    # Priority 9 (cross-aggregate gate): a Filing for the same
    # (tax_year_id, jurisdiction_id) must be READY, FILED, or ACCEPTED.
    ready = any(f["tax_year_id"] == pos["tax_year_id"]
                and f["jurisdiction_id"] == pos["jurisdiction_id"]
                and f["status"] in ("READY", "FILED", "ACCEPTED")
                for f in db.filings.values())
    if not ready:
        raise_error(ERR_RETURN_NOT_READY,
                    "no READY/FILED/ACCEPTED Filing exists for the position's "
                    "(tax_year_id, jurisdiction_id) pair")

    pos["status"] = "DISCLOSED"
    touch(pos)
    return success_object(serialize_utp(pos))


@bp.route("/tax/uncertain-tax-positions/<positionId>/settle", methods=["POST"])
def settle_utp(positionId):
    authorized(("TaxManager",))
    pos = get_or_404(db.utps, positionId, "UncertainTaxPosition")
    if pos["status"] != "DISCLOSED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"settle is not defined from position status {pos['status']}")
    data = body_json()

    # Priority 10 (amount sanity): the settlement payment is nonnegative.
    amount_probe = present_int(data, "settled_amount_cents")
    if amount_probe is not None and amount_probe < 0:
        raise_error(ERR_INVALID_AMOUNT, "settled_amount_cents must be >= 0")

    # Priority 11 (structural).
    settled = req_int(data, "settled_amount_cents")

    pos["settled_amount_cents"] = settled
    pos["status"] = "SETTLED"
    pos["interest_accrued_cents"] = compute_utp_interest(pos, CLOCK.today())
    touch(pos)

    year = db.tax_years.get(pos["tax_year_id"])
    if year is not None:
        recompute_utp_reserve(year)  # SETTLED positions drop out of the reserve
        recompute_etrs(year)
        bump_year(year)
    return success_object(serialize_utp(pos))
