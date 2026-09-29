"""Purchase offer development, presentation and retirement."""
from datetime import timedelta

from flask import Blueprint

import calc
import lookups
import store
import web
from core import clock_now, fail, fmt_dt, parse_datetime
from web import endpoint

bp = Blueprint("offers", __name__)

_BASIS_PAIRS = {"PRE_EVENT_FMV": "PRE_EVENT", "POST_EVENT_FMV": "POST_EVENT"}


def _revert_parcel_after_offer_exit(parcel, exiting_offer_id):
    """OFFER_OUTSTANDING -> VALUE_ESTABLISHED only when no other offer is still PRESENTED."""
    if parcel["acquisition_status"] != "OFFER_OUTSTANDING":
        return False
    for other in calc.parcel_offers(parcel["id"]):
        if other["id"] == exiting_offer_id:
            continue
        if other["status"] == "PRESENTED":
            return False
    parcel["acquisition_status"] = "VALUE_ESTABLISHED"
    return True


@bp.post("/parcels/<parcel_id>/purchase-offers")
@endpoint("SubrecipientCoordinator")
def create_offer(parcel_id):
    parcel = lookups.get_parcel(parcel_id)
    web.scope_project(parcel["project_id"])
    body = web.get_body()
    appraisal_id = web.req_string(body, "source_appraisal_id")
    offer_basis = web.req_enum(body, "offer_basis", store.OFFER_BASES)
    expected = web.int_field(body, "expected_parcel_version", minimum=1)

    appraisal = lookups.get_appraisal(appraisal_id)
    if appraisal["parcel_id"] != parcel_id:
        fail("ERR_PARCEL_PROJECT_MISMATCH")
    if expected != int(parcel["version"]):
        fail("ERR_STALE_PARCEL_VERSION")
    project = lookups.project_of_parcel(parcel)
    if project is None or project["status"] != "APPROVED":
        fail("ERR_PROJECT_NOT_APPROVED")
    if parcel["participation_status"] not in ("INTERESTED", "VOLUNTARY_CONFIRMED"):
        fail("ERR_PARTICIPATION_NOT_VOLUNTARY")
    if appraisal["appraisal_type"] != "REVIEW" or appraisal["status"] != "ACCEPTED":
        fail("ERR_REVIEW_APPRAISAL_REQUIRED")
    if int(parcel["dob_deduction_total_cents"]) > int(appraisal["indicated_value_cents"]):
        fail("ERR_DOB_EXCEEDS_BASE_VALUE")
    if _BASIS_PAIRS[offer_basis] != appraisal["valuation_basis"]:
        fail("ERR_VALUATION_BASIS_MISMATCH")

    amounts = calc.net_offer_amount(parcel, appraisal)
    record = store.new_record("PurchaseOffer", {
        "parcel_id": parcel_id,
        "source_appraisal_id": appraisal_id,
        "offer_basis": offer_basis,
        "base_value_cents": amounts["base_value_cents"],
        "dob_deduction_cents": amounts["dob_deduction_cents"],
        "pre_incentive_net_cents": amounts["pre_incentive_net_cents"],
        "incentive_cents": amounts["incentive_cents"],
        "net_offer_cents": amounts["net_offer_cents"],
        "presented_at": None,
        "expires_at": None,
        "withdrawal_reason": None,
        "superseded_by_offer_id": None,
        "status": "DRAFT",
        "expected_parcel_version": expected,
    })
    store.offers[record["id"]] = record

    for other in store.by_created(calc.parcel_offers(parcel_id)):
        if other["id"] == record["id"]:
            continue
        if other["status"] not in ("DRAFT", "DECLINED", "EXPIRED"):
            continue
        other["status"] = "SUPERSEDED"
        other["superseded_by_offer_id"] = record["id"]
        store.touch(other)
    store.touch(parcel)
    return web.respond_object(record, 201)


@bp.get("/purchase-offers")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "RelocationSpecialist",
          "ComplianceMonitor")
def list_offers():
    parcel_id = web.query_str("parcel_id")
    appraisal_id = web.query_str("source_appraisal_id")
    superseded_by = web.query_str("superseded_by_offer_id")
    status = web.query_enum("status", store.OFFER_STATUSES)
    rows = list(store.offers.values())
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if appraisal_id is not None:
        rows = [r for r in rows if r["source_appraisal_id"] == appraisal_id]
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_offer_id"] == superseded_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return web.list_response(rows)


@bp.get("/purchase-offers/<offer_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "RelocationSpecialist",
          "ComplianceMonitor")
def read_offer(offer_id):
    return web.respond_object(lookups.get_offer(offer_id))


@bp.post("/purchase-offers/<offer_id>/present")
@endpoint("SubrecipientCoordinator")
def present_offer(offer_id):
    offer = lookups.get_offer(offer_id)
    parcel = store.parcels.get(offer["parcel_id"])
    web.scope_parcel(parcel)
    project = lookups.project_of_parcel(parcel) if parcel else None
    if offer["status"] != "DRAFT":
        fail("ERR_INVALID_OFFER_STATE")
    if parcel is None or parcel["acquisition_status"] != "VALUE_ESTABLISHED":
        fail("ERR_INVALID_OFFER_STATE")
    if parcel["participation_status"] != "VOLUNTARY_CONFIRMED":
        fail("ERR_PARTICIPATION_NOT_VOLUNTARY")
    source = store.appraisals.get(offer["source_appraisal_id"])
    if (source is None or source["appraisal_type"] != "REVIEW"
            or source["status"] != "ACCEPTED"):
        fail("ERR_REVIEW_APPRAISAL_REQUIRED")
    item = calc.federal_item(offer["net_offer_cents"], project["cost_share_federal_pct"])
    if int(project["federal_obligated_cents"]) + item > int(project["total_federal_share_cap_cents"]):
        fail("ERR_FEDERAL_SHARE_CAP_EXCEEDED")

    now = clock_now()
    offer["status"] = "PRESENTED"
    offer["presented_at"] = fmt_dt(now)
    offer["expires_at"] = fmt_dt(now + timedelta(days=store.OFFER_VALIDITY_DAYS))
    store.touch(offer)
    parcel["acquisition_status"] = "OFFER_OUTSTANDING"
    store.touch(parcel)
    calc.recompute_federal_obligated(project)
    store.touch(project)
    return web.respond_object(offer)


@bp.post("/purchase-offers/<offer_id>/owner-response")
@endpoint("SubrecipientCoordinator")
def owner_response(offer_id):
    offer = lookups.get_offer(offer_id)
    parcel = store.parcels.get(offer["parcel_id"])
    web.scope_parcel(parcel)
    project = lookups.project_of_parcel(parcel) if parcel else None
    body = web.get_body()
    response = web.req_enum(body, "response", ["ACCEPT", "DECLINE"])
    web.opt_string(body, "response_note")
    if offer["status"] != "PRESENTED":
        fail("ERR_INVALID_OFFER_STATE")
    expires_at = parse_datetime(offer.get("expires_at") or "")
    if expires_at is not None and clock_now() > expires_at:
        fail("ERR_OFFER_EXPIRED")

    if response == "ACCEPT":
        if parcel["participation_status"] != "VOLUNTARY_CONFIRMED":
            fail("ERR_PARTICIPATION_NOT_VOLUNTARY")
        offer["status"] = "ACCEPTED"
        store.touch(offer)
        if parcel["acquisition_status"] == "OFFER_OUTSTANDING":
            parcel["acquisition_status"] = "OFFER_ACCEPTED"
            store.touch(parcel)
        return web.respond_object(offer)

    offer["status"] = "DECLINED"
    store.touch(offer)
    if _revert_parcel_after_offer_exit(parcel, offer_id):
        store.touch(parcel)
    calc.recompute_federal_obligated(project)
    store.touch(project)
    return web.respond_object(offer)


@bp.post("/purchase-offers/<offer_id>/expire")
@endpoint("ProgramAdministrator")
def expire_offer(offer_id):
    offer = lookups.get_offer(offer_id)
    parcel = store.parcels.get(offer["parcel_id"])
    project = lookups.project_of_parcel(parcel) if parcel else None
    if offer["status"] != "PRESENTED":
        fail("ERR_INVALID_OFFER_STATE")
    expires_at = parse_datetime(offer.get("expires_at") or "")
    if expires_at is None or clock_now() <= expires_at:
        fail("ERR_OFFER_NOT_YET_EXPIRED")

    offer["status"] = "EXPIRED"
    store.touch(offer)
    if _revert_parcel_after_offer_exit(parcel, offer_id):
        store.touch(parcel)
    calc.recompute_federal_obligated(project)
    store.touch(project)
    return web.respond_object(offer)


@bp.post("/purchase-offers/<offer_id>/withdraw")
@endpoint("SubrecipientCoordinator")
def withdraw_offer(offer_id):
    offer = lookups.get_offer(offer_id)
    parcel = store.parcels.get(offer["parcel_id"])
    web.scope_parcel(parcel)
    project = lookups.project_of_parcel(parcel) if parcel else None
    body = web.get_body()
    reason = web.req_string(body, "withdrawal_reason")
    if offer["status"] not in ("DRAFT", "PRESENTED"):
        fail("ERR_INVALID_OFFER_STATE")

    was_presented = offer["status"] == "PRESENTED"
    offer["status"] = "WITHDRAWN"
    offer["withdrawal_reason"] = reason
    store.touch(offer)
    if was_presented:
        if _revert_parcel_after_offer_exit(parcel, offer_id):
            store.touch(parcel)
        calc.recompute_federal_obligated(project)
        store.touch(project)
    return web.respond_object(offer)
