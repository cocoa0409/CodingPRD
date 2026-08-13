"""DonorSite endpoints, including tax-receipt issuance."""
from flask import Blueprint, request

from db import DB, STATE, new_id
from errors import ApiError
from middleware import auth
from response import ok
from services import (
    OFFER_IN_FLIGHT,
    clock_dt,
    clock_iso,
    compute_receipt_lines,
    get_donor,
    rate_card_for_period_end,
    ser_donor,
    ser_offer,
    ser_receipt,
    stamp,
    suspend_donor_cascade,
    touch,
    verified_runs_in_period,
)
from util import (
    as_bool,
    as_enum,
    as_int,
    as_iso_dt,
    as_str,
    body,
    paginate,
    parse_dt,
    reject_unknown,
    required,
)

bp = Blueprint("donors", __name__)

DONOR_STATUSES = ("PENDING_REVIEW", "ACTIVE", "SUSPENDED", "DEACTIVATED")


@bp.post("/api/donor-sites")
def create_donor():
    auth(["DispatchAdmin"])
    data = body()
    reject_unknown(data, {"legal_name", "ein", "contact_email", "enhanced_deduction_eligible"})
    legal_name = as_str(required(data, "legal_name"), "legal_name")
    ein = as_str(required(data, "ein"), "ein")
    contact_email = as_str(required(data, "contact_email"), "contact_email")
    enhanced = False
    if "enhanced_deduction_eligible" in data:
        enhanced = as_bool(data["enhanced_deduction_eligible"], "enhanced_deduction_eligible")
    rec = {
        "id": new_id(),
        "legal_name": legal_name,
        "ein": ein,
        "contact_email": contact_email,
        "enhanced_deduction_eligible": enhanced,
        "status": "PENDING_REVIEW",
        "strike_count": 0,
        "lifetime_weight_lbs": 0,
        "pending_estimated_lbs": 0,
        "lifetime_tax_value_cents": 0,
    }
    stamp(rec)
    DB["donor_sites"][rec["id"]] = rec
    return ok(ser_donor(rec), status=201)


@bp.get("/api/donor-sites/<did>")
def get_one_donor(did):
    user_id, role = auth(["DispatchAdmin", "DonorCoordinator"])
    return ok(ser_donor(get_donor(did, user_id, role)))


@bp.patch("/api/donor-sites/<did>/status")
def patch_donor_status(did):
    auth(["DispatchAdmin"])
    data = body()
    reject_unknown(data, {"target_status"})
    target = as_enum(required(data, "target_status"), "target_status", DONOR_STATUSES)
    donor = get_donor(did)
    cur = donor["status"]
    if target == "ACTIVE":
        if cur == "PENDING_REVIEW":
            donor["status"] = "ACTIVE"
            touch(donor)
        elif cur == "SUSPENDED":
            donor["status"] = "ACTIVE"
            donor["strike_count"] = 0
            touch(donor)
        else:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION", 409,
                f"Cannot move donor from {cur} to ACTIVE",
            )
    elif target == "SUSPENDED":
        if cur != "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION", 409,
                f"Cannot move donor from {cur} to SUSPENDED",
            )
        suspend_donor_cascade(donor)
    elif target == "DEACTIVATED":
        if cur not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION", 409,
                f"Cannot move donor from {cur} to DEACTIVATED",
            )
        for offer in DB["offers"].values():
            if offer["donor_site_id"] == donor["id"] and offer["status"] in OFFER_IN_FLIGHT:
                raise ApiError(
                    "ERR_INVALID_STATE_TRANSITION", 409,
                    "Donor has in-flight offers and cannot be deactivated",
                )
        donor["status"] = "DEACTIVATED"
        touch(donor)
    else:  # PENDING_REVIEW is never a valid target
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409,
            f"Cannot move donor from {cur} to {target}",
        )
    return ok(ser_donor(donor))


@bp.get("/api/donor-sites/<did>/donation-offers")
def list_donor_offers(did):
    user_id, role = auth(["DispatchAdmin", "DonorCoordinator"])
    donor = get_donor(did, user_id, role)
    items = [o for o in DB["offers"].values() if o["donor_site_id"] == donor["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return paginate(items, ser_offer)


@bp.get("/api/donor-sites/<did>/tax-receipts")
def list_donor_receipts(did):
    user_id, role = auth(["DispatchAdmin", "DonorCoordinator"])
    donor = get_donor(did, user_id, role)
    items = [r for r in DB["receipts"].values() if r["donor_site_id"] == donor["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate(items, ser_receipt)


@bp.post("/api/donor-sites/<did>/tax-receipts")
def issue_tax_receipt(did):
    auth(["DispatchAdmin"])
    data = body()
    reject_unknown(data, {"period_start", "period_end", "expected_donor_version"})
    period_start = as_iso_dt(required(data, "period_start"), "period_start")
    period_end = as_iso_dt(required(data, "period_end"), "period_end")
    expected_donor_version = as_int(
        required(data, "expected_donor_version"), "expected_donor_version"
    )
    if parse_dt(period_start) >= parse_dt(period_end):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "period_start must be before period_end"
        )
    if parse_dt(period_end) > clock_dt():
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "period_end must not be after the current time"
        )
    donor = get_donor(did)
    # OCC guard (priority 7)
    if expected_donor_version != donor["version"]:
        raise ApiError(
            "ERR_STALE_DONOR_VERSION", 412, "DonorSite version has advanced"
        )
    # Fiscal gates in fixed sequence: verified-run set first, rate card second.
    runs = verified_runs_in_period(donor["id"], period_start, period_end)
    if not runs:
        raise ApiError(
            "ERR_RECEIPT_NO_VERIFIED_RESCUES", 409,
            "No VERIFIED rescues in the receipt period",
        )
    card = rate_card_for_period_end(period_end)
    if card is None:
        raise ApiError(
            "ERR_NO_RATE_CARD_EFFECTIVE", 409,
            "No rate card effective for the receipt period end",
        )
    lines = compute_receipt_lines(runs, card)
    total_standard = sum(l["standard_cents"] for l in lines)
    total_enhanced = sum(l["enhanced_cents"] for l in lines)
    total_weight = sum(l["weight_lbs"] for l in lines)
    deductible = total_enhanced if donor["enhanced_deduction_eligible"] else total_standard
    # Amendment: supersede any ISSUED receipt with an identical period.
    for r in DB["receipts"].values():
        if (
            r["donor_site_id"] == donor["id"]
            and r["status"] == "ISSUED"
            and parse_dt(r["period_start"]) == parse_dt(period_start)
            and parse_dt(r["period_end"]) == parse_dt(period_end)
        ):
            r["status"] = "AMENDED"
            touch(r)
    rec = {
        "id": new_id(),
        "donor_site_id": donor["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "ISSUED",
        "rate_card_version": card["card_version"],
        "lines": lines,
        "total_standard_value_cents": total_standard,
        "total_enhanced_value_cents": total_enhanced,
        "deductible_value_cents": deductible,
        "total_weight_lbs": total_weight,
        "issued_at": clock_iso(),
    }
    stamp(rec)
    DB["receipts"][rec["id"]] = rec
    # Issuance increments the donor's version by one.
    touch(donor)
    return ok(ser_receipt(rec), status=201)
