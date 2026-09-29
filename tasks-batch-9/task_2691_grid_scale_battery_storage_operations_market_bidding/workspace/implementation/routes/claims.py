"""Warranty claims, adjudication and augmentation (PRD 3.9)."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as v
from errors import ApiError
from services import calc, core

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("CAPACITY_SHORTFALL", "THROUGHPUT_BREACH")
STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "DENIED", "REMEDIED")
DECISIONS = ("APPROVE", "DENY")
DENIAL_REASONS = ("NO_SHORTFALL", "THROUGHPUT_EXCEEDED_WARRANTY", "LATE_FILING")
CLAIM_FILING_WINDOW_DAYS = 30
LIVE_CLAIM_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REMEDIED")


def _filing_deadline(test):
    return db.add_days(db.parse_dt(test["scheduled_date"]),
                       CLAIM_FILING_WINDOW_DAYS)


@bp.post("/warranty-claims")
def draft_claim():
    user_id, _role = middleware.authorize("AssetManager")
    body = v.json_body()

    asset_id = v.ident(body, "asset_id")
    test_id = v.ident(body, "capacity_test_id")
    claim_type = v.enum(body, "claim_type", CLAIM_TYPES)

    core.get_asset(asset_id)
    test = core.get_test(test_id)
    if test["asset_id"] != asset_id:
        raise ApiError(errors.ERR_ASSET_SCOPE_MISMATCH, 409,
                       "The capacity test belongs to a different asset.")

    citing = [c for c in db.warranty_claims.values()
              if c["capacity_test_id"] == test_id
              and c["status"] in LIVE_CLAIM_STATUSES]
    if (test["status"] != "COMPLETED" or not test["warranty_claim_triggered"]
            or citing):
        raise ApiError(errors.ERR_NO_WARRANTY_TRIGGER, 422,
                       "The cited capacity test is not a completed, triggered "
                       "and un-claimed test.")

    if db.clock_now() > _filing_deadline(test):
        raise ApiError(errors.ERR_CLAIM_FILING_WINDOW_EXPIRED, 422,
                       "The claim filing window has expired.")

    claim = db.new_row()
    claim.update({
        "asset_id": asset_id,
        "capacity_test_id": test_id,
        "claim_type": claim_type,
        "claimed_shortfall_pct": test["soh_deficit_pct"],
        "status": "DRAFT",
        "remedy_energy_add_mwh": None,
        "remedy_install_date": None,
        "remedy_outage_days": None,
        "denial_reason": None,
        "created_by_user_id": user_id,
        "submitted_by_user_id": None,
        "adjudicated_by_user_id": None,
    })
    db.warranty_claims[claim["id"]] = claim
    return response.created(db.serialize(claim))


@bp.get("/warranty-claims/<claim_id>")
def read_claim(claim_id):
    middleware.any_role()
    return response.ok(db.serialize(core.get_claim(claim_id)))


@bp.get("/warranty-claims")
def list_claims():
    middleware.any_role()
    limit, offset = v.pagination()
    asset_id = v.query_str("asset_id")
    capacity_test_id = v.query_str("capacity_test_id")
    status = v.query_enum("status", STATUSES)

    rows = list(db.warranty_claims.values())
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if capacity_test_id is not None:
        rows = [r for r in rows if r["capacity_test_id"] == capacity_test_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = core.newest_first(rows)
    page, total = core.paginate(rows, limit, offset)
    return response.ok_list([db.serialize(r) for r in page], limit, offset, total)


@bp.post("/warranty-claims/<claim_id>/submit")
def submit_claim(claim_id):
    user_id, _role = middleware.authorize("AssetManager")
    claim = core.get_claim(claim_id)

    if claim["status"] != "DRAFT":
        raise ApiError(errors.ERR_CLAIM_NOT_DRAFT, 409, "The claim is not a DRAFT.")

    test = db.capacity_tests.get(claim["capacity_test_id"])
    if test is None or test["status"] != "COMPLETED" or not test["warranty_claim_triggered"]:
        raise ApiError(errors.ERR_NO_WARRANTY_TRIGGER, 422,
                       "The cited capacity test no longer supports a claim.")
    if db.clock_now() > _filing_deadline(test):
        raise ApiError(errors.ERR_CLAIM_FILING_WINDOW_EXPIRED, 422,
                       "The claim filing window has expired.")

    claim["status"] = "SUBMITTED"
    claim["submitted_by_user_id"] = user_id
    db.touch(claim)
    return response.ok(db.serialize(claim))


@bp.post("/warranty-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    user_id, _role = middleware.authorize("PlatformAdmin")
    body = v.json_body()
    decision = v.enum(body, "decision", DECISIONS)

    if decision == "APPROVE":
        install_raw, _install = v.timestamp(body, "remedy_install_date")
        outage_days = v.integer(body, "remedy_outage_days", ge=1)
        if v.present(body, "denial_reason"):
            raise errors.bad_request(
                "denial_reason must be absent on the approval branch.")
        denial_reason = None
    else:
        denial_reason = v.enum(body, "denial_reason", DENIAL_REASONS)
        if v.present(body, "remedy_install_date") or v.present(body, "remedy_outage_days"):
            raise errors.bad_request(
                "remedy_install_date and remedy_outage_days must be absent on "
                "the denial branch.")
        install_raw = None
        outage_days = None

    claim = core.get_claim(claim_id)

    if user_id == claim["created_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "A claim may not be adjudicated by the user who created "
                       "it.")

    if claim["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_CLAIM_NOT_SUBMITTED, 409,
                       "The claim is not SUBMITTED.")

    if decision == "APPROVE":
        asset = core.get_asset(claim["asset_id"])
        pre_remedy_rated = core.rated_energy(asset)
        claim["remedy_energy_add_mwh"] = calc.remedy_energy(
            pre_remedy_rated, claim["claimed_shortfall_pct"])
        claim["remedy_install_date"] = install_raw
        claim["remedy_outage_days"] = outage_days
        claim["status"] = "APPROVED"
    else:
        claim["denial_reason"] = denial_reason
        claim["status"] = "DENIED"
    claim["adjudicated_by_user_id"] = user_id
    db.touch(claim)
    return response.ok(db.serialize(claim))


@bp.post("/warranty-claims/<claim_id>/install-remedy")
def install_remedy(claim_id):
    middleware.authorize("AssetManager")
    claim = core.get_claim(claim_id)
    asset = core.get_asset(claim["asset_id"])

    if claim["status"] != "APPROVED":
        raise ApiError(errors.ERR_CLAIM_NOT_APPROVED, 409,
                       "The claim is not APPROVED.")
    install_date = db.parse_dt(claim["remedy_install_date"])
    if install_date is not None and db.clock_now() < install_date:
        raise ApiError(errors.ERR_CLAIM_NOT_APPROVED, 409,
                       "The remedy install date has not arrived yet.")
    core.gate_lockout(asset)

    claim["status"] = "REMEDIED"
    db.touch(claim)

    # step 6 of the model — the pinned propagation order
    core.recompute_rated(asset)
    core.recompute_available(asset)
    core.recompute_efc(asset)
    core.reprice_draft_bids(asset)
    core.recompute_free(asset)
    db.touch(asset)
    return response.ok(db.serialize(claim))
