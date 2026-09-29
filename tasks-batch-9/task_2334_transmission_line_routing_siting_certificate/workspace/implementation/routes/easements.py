"""Landowners, easement tracts, offers, condemnation and payment (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint, g

import response as resp
from db import insert, store
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import calc, derive
from validation import (
    collection_list,
    find_path,
    fk,
    get_body,
    opt_int,
    opt_str,
    req_enum,
    req_id,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("easements", __name__)

RESPONSES = ("ACCEPT", "REJECT")
ACQUISITION_TERMINAL = ("AGREED", "AWARDED")


# ------------------------------------------------------- landowners ----
@bp.get("/siting/landowners")
@endpoint(ALL_ROLES)
def list_landowners():
    rows, pagination = collection_list(store.landowners, [])
    return resp.listing(rows, pagination)


@bp.get("/siting/landowners/<landowner_id>")
@endpoint(ALL_ROLES)
def read_landowner(landowner_id):
    return resp.ok(find_path(store.landowners, landowner_id))


@bp.post("/siting/landowners")
@endpoint(["Developer", "CommissionStaff"])
def create_landowner():
    body = get_body()
    row = insert(
        store.landowners,
        {
            "name": req_str(body, "name"),
            "email": req_str(body, "email"),
            "mailing_address": req_str(body, "mailing_address"),
        },
    )
    return resp.created(row)


# ---------------------------------------------------- easement tracts ----
@bp.get("/siting/easement-tracts")
@endpoint(ALL_ROLES)
def list_tracts():
    rows, pagination = collection_list(
        store.easement_tracts,
        ["project_id", "segment_id", "landowner_id", "acquisition_status", "payment_status"],
    )
    return resp.listing(rows, pagination)


@bp.get("/siting/easement-tracts/<tract_id>")
@endpoint(ALL_ROLES)
def read_tract(tract_id):
    return resp.ok(find_path(store.easement_tracts, tract_id))


@bp.post("/siting/easement-tracts")
@endpoint(["Developer"])
def create_tract():
    body = get_body()
    fk(body, "project_id", store.projects)
    segment = fk(body, "segment_id", store.route_segments)
    fk(body, "landowner_id", store.landowners)

    project_id = req_id(body, "project_id")
    segment_id = req_id(body, "segment_id")
    landowner_id = req_id(body, "landowner_id")
    parcel_number = req_str(body, "parcel_number")
    acres = req_num(body, "acres", exclusive_min=0)
    per_acre_value_cents = req_int(body, "per_acre_value_cents", minimum=0)
    easement_factor = req_num(body, "easement_factor", exclusive_min=0, maximum=1)
    structure_damages_cents = opt_int(body, "structure_damages_cents", default=0, minimum=0)
    before_value_cents = opt_int(body, "before_value_cents", default=0, minimum=0)
    after_value_cents = opt_int(body, "after_value_cents", default=0, minimum=0)
    severance_damages_cents = opt_int(body, "severance_damages_cents", default=0, minimum=0)

    route = store.routes.get(segment["route_id"]) if segment else None
    if route is None or route["project_id"] != project_id:
        raise ApiError(
            "ERR_TRACT_SEGMENT_MISMATCH",
            "The named segment does not belong to a route on the tract's project.",
        )

    row = insert(
        store.easement_tracts,
        {
            "project_id": project_id,
            "segment_id": segment_id,
            "landowner_id": landowner_id,
            "parcel_number": parcel_number,
            "acres": acres,
            "per_acre_value_cents": per_acre_value_cents,
            "easement_factor": easement_factor,
            "structure_damages_cents": structure_damages_cents,
            "before_value_cents": before_value_cents,
            "after_value_cents": after_value_cents,
            "severance_damages_cents": severance_damages_cents,
            "offer_round": 0,
            "offered_compensation_cents": None,
            "agreed_compensation_cents": None,
            "award_cents": None,
            "committed_cents": 0,
            "acquisition_status": "NOT_STARTED",
            "payment_status": "UNPAID",
            "paid_amount_cents": 0,
            "paid_at": None,
            "court_docket_number": None,
            "deposit_cents": None,
        },
    )
    return resp.created(row)


def _certificate_for(tract):
    return derive.certificate_of_project(tract["project_id"])


@bp.post("/siting/easement-tracts/<tract_id>/offers")
@endpoint(["Developer"])
def extend_offer(tract_id):
    tract = find_path(store.easement_tracts, tract_id)
    body = get_body()
    expected_version = req_int(body, "expected_tract_version")
    opt_str(body, "offer_note")

    if expected_version != tract["version"]:
        raise ApiError(
            "ERR_STALE_TRACT_VERSION",
            "expected_tract_version %s does not match version %s." % (expected_version, tract["version"]),
        )

    if tract["acquisition_status"] in ACQUISITION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The tract is already %s." % tract["acquisition_status"])
    if tract["acquisition_status"] not in ("NOT_STARTED", "REJECTED"):
        raise ApiError(
            "ERR_INVALID_STATE", "No offer transition leaves %s." % tract["acquisition_status"]
        )

    certificate = _certificate_for(tract)
    if certificate is None or certificate["status"] != "ISSUED":
        raise ApiError(
            "ERR_INVALID_STATE", "The project carries no issued certificate to support an offer."
        )
    if certificate["posture"] == "REVOKED":
        raise ApiError("ERR_CERTIFICATE_REVOKED", "The certificate has been revoked.")

    if tract["offer_round"] >= calc.MAX_OFFER_ROUNDS:
        raise ApiError(
            "ERR_OFFER_LIMIT_REACHED",
            "The tract has already received %d offers." % calc.MAX_OFFER_ROUNDS,
        )

    next_round = tract["offer_round"] + 1
    derive.apply(
        tract,
        offer_round=next_round,
        offered_compensation_cents=calc.negotiated_offer_cents(tract, next_round),
        acquisition_status="OFFERED",
    )
    return resp.created(tract)


@bp.post("/siting/easement-tracts/<tract_id>/offer-response")
@endpoint(["Landowner"])
def respond_to_offer(tract_id):
    tract = find_path(store.easement_tracts, tract_id)
    body = get_body()
    response = req_enum(body, "response", RESPONSES)
    opt_str(body, "response_note")

    if tract["landowner_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The tract belongs to another landowner.")

    if tract["acquisition_status"] in ACQUISITION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The tract is already %s." % tract["acquisition_status"])
    if tract["acquisition_status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "There is no standing offer to respond to.")

    if response == "ACCEPT":
        agreed = tract["offered_compensation_cents"]
        derive.apply(
            tract,
            agreed_compensation_cents=agreed,
            committed_cents=agreed,
            acquisition_status="AGREED",
        )
        project = store.projects.get(tract["project_id"])
        if project is not None:
            derive.recompute_project_committed(project)
    else:
        derive.apply(tract, acquisition_status="REJECTED")
    return resp.created(tract)


@bp.post("/siting/easement-tracts/<tract_id>/condemnation")
@endpoint(["Developer"])
def file_condemnation(tract_id):
    tract = find_path(store.easement_tracts, tract_id)
    body = get_body()
    court_docket_number = req_str(body, "court_docket_number")
    deposit_cents = req_int(body, "deposit_cents", minimum=0)

    if tract["acquisition_status"] in ACQUISITION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The tract is already %s." % tract["acquisition_status"])
    if tract["acquisition_status"] != "REJECTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A condemnation proceeding is filed out of REJECTED, not %s." % tract["acquisition_status"],
        )

    certificate = _certificate_for(tract)
    if certificate is None or certificate["status"] != "ISSUED":
        raise ApiError(
            "ERR_INVALID_STATE", "The project carries no issued certificate to support condemnation."
        )
    if certificate["posture"] == "REVOKED":
        raise ApiError("ERR_CERTIFICATE_REVOKED", "The certificate has been revoked.")

    if not certificate["eminent_domain_authorized"] or tract["offer_round"] < 2:
        raise ApiError(
            "ERR_EMINENT_DOMAIN_NOT_AUTHORIZED",
            "Condemnation requires eminent-domain authority and at least two extended offers.",
        )

    project = store.projects.get(tract["project_id"])
    if project is not None and project["right_of_way_hold"]:
        raise ApiError("ERR_RIGHT_OF_WAY_HOLD", "The project carries a right-of-way hold.")

    derive.apply(
        tract,
        court_docket_number=court_docket_number,
        deposit_cents=deposit_cents,
        acquisition_status="CONDEMNATION_FILED",
    )
    return resp.created(tract)


@bp.post("/siting/easement-tracts/<tract_id>/award")
@endpoint(["CommissionStaff"])
def record_award(tract_id):
    tract = find_path(store.easement_tracts, tract_id)
    body = get_body()
    opt_str(body, "award_note")

    if tract["acquisition_status"] in ACQUISITION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The tract is already %s." % tract["acquisition_status"])
    if tract["acquisition_status"] != "CONDEMNATION_FILED":
        raise ApiError(
            "ERR_INVALID_STATE", "An award is recorded out of CONDEMNATION_FILED, not %s."
            % tract["acquisition_status"],
        )

    before = int(tract.get("before_value_cents") or 0)
    after = int(tract.get("after_value_cents") or 0)
    if before - after <= 0:
        raise ApiError(
            "ERR_NO_VALUE_DIMINUTION", "before_value_cents must exceed after_value_cents."
        )

    award = calc.condemnation_award_cents(tract)
    derive.apply(tract, award_cents=award, committed_cents=award, acquisition_status="AWARDED")
    project = store.projects.get(tract["project_id"])
    if project is not None:
        derive.recompute_project_committed(project)
    return resp.created(tract)


@bp.post("/siting/easement-tracts/<tract_id>/payments")
@endpoint(["Developer"])
def pay_tract(tract_id):
    tract = find_path(store.easement_tracts, tract_id)
    body = get_body()
    req_str(body, "payment_reference")

    if tract["payment_status"] == "PAID":
        raise ApiError("ERR_INVALID_STATE", "The tract has already been paid.")
    if tract["acquisition_status"] not in ("AGREED", "AWARDED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Payment requires an AGREED or AWARDED tract, not %s."
            % tract["acquisition_status"],
        )

    amount = int(tract["committed_cents"] or 0)
    project = store.projects.get(tract["project_id"])
    balance = project["escrow_balance_cents"] if project is not None else 0
    if balance < amount:
        raise ApiError(
            "ERR_ESCROW_INSUFFICIENT",
            "Project escrow balance %d is below the committed %d." % (balance, amount),
        )

    derive.apply(tract, paid_amount_cents=amount, paid_at=store.now(), payment_status="PAID")
    if project is not None:
        derive.escrow_disburse(project, amount)
    return resp.created(tract)


@bp.post("/siting/easement-tracts/<tract_id>/payment-rescission")
@endpoint(["CommissionStaff"])
def rescind_payment(tract_id):
    tract = find_path(store.easement_tracts, tract_id)
    body = get_body()
    req_str(body, "rescission_reason")

    if tract["payment_status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", "Only a PAID tract may be rescinded.")

    paid_at = tract["paid_at"]
    if paid_at is None or store.now() >= paid_at + timedelta(days=calc.RESCISSION_WINDOW_DAYS):
        raise ApiError(
            "ERR_RESCISSION_WINDOW_EXPIRED",
            "The %d-day statutory rescission window has expired." % calc.RESCISSION_WINDOW_DAYS,
        )

    amount = int(tract["paid_amount_cents"] or 0)
    derive.apply(tract, paid_amount_cents=0, payment_status="RESCINDED")
    project = store.projects.get(tract["project_id"])
    if project is not None:
        derive.escrow_restore(project, amount)
    return resp.created(tract)
