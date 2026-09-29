"""Application endpoints (PRD 3.3 - 3.7)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

from db import base_row, db, touch
from errors import ApiError
from middleware import authenticate, require_owner
from response import created, listing, ok, pagination
from services import calc, cascade, lookup, serialize
from validation import Payload, body_fk, raw_body

bp = Blueprint("applications", __name__)

APPLICATION_STATUSES = (
    "RECEIVED",
    "RANKED",
    "OFFER_ISSUED",
    "COUNTERED",
    "ACCEPTED",
    "CLOSED_RECORDED",
    "NOT_SELECTED",
    "WITHDRAWN",
    "LAPSED",
)
CLOSING_STATUSES = (
    "NOT_APPLICABLE",
    "PENDING_REQUIREMENTS",
    "BLOCKED",
    "CLEARED",
    "CLOSED",
    "CANCELLED",
)
FUNDING_PLAN_STATUSES = (
    "UNFUNDED",
    "FUNDED",
    "UNDERFUNDED",
    "OBLIGATED",
    "DISBURSED",
    "RELEASED",
)
STRUCTURES = ("FULL_PURCHASE", "BARGAIN_SALE", "INSTALLMENT")
NEGOTIATION_KINDS = ("OFFER", "COUNTER", "ACCEPTANCE", "EXPIRATION", "WITHDRAWAL")
REQUIREMENT_TYPES = ("TITLE_COMMITMENT", "MORTGAGE_SUBORDINATION", "BOUNDARY_SURVEY")
REQUIREMENT_STATUSES = ("OUTSTANDING", "SUBMITTED", "SATISFIED", "DEFICIENT", "WAIVED")
PERMITTED_USES = (
    "CROP_PRODUCTION",
    "LIVESTOCK",
    "DAIRY",
    "ORCHARD",
    "FARM_STAND",
    "AGRITOURISM",
    "FORESTRY",
)

READ_ROLES = ("ProgramAdmin", "AcquisitionOfficer", "AppraisalReviewer", "Landowner")


def _certified_appraisal(app):
    for appraisal in lookup.appraisals_of(app["id"]):
        if appraisal["status"] == "CERTIFIED":
            return appraisal
    return None


def _check_certified_ceiling(app, amount_cents):
    if _certified_appraisal(app) is None or app["certified_easement_value_cents"] is None:
        raise ApiError(
            "ERR_OFFER_EXCEEDS_CERTIFIED_VALUE",
            "no CERTIFIED appraisal exists on this application",
        )
    if amount_cents > app["certified_easement_value_cents"]:
        raise ApiError(
            "ERR_OFFER_EXCEEDS_CERTIFIED_VALUE",
            "amount exceeds certified_easement_value_cents",
        )


# --------------------------------------------------------------------- create
@bp.post("/applications")
def create_application():
    authenticate(("Landowner",))
    body = raw_body()
    rnd = lookup.get_round(body_fk(body, "funding_round_id"))
    parcel = lookup.get_parcel(body_fk(body, "parcel_id"))
    landowner = lookup.get_landowner(body_fk(body, "landowner_id"))
    payload = Payload(
        body, ("funding_round_id", "parcel_id", "landowner_id", "requested_price_cents")
    )
    payload.string("funding_round_id", min_len=1)
    payload.string("parcel_id", min_len=1)
    payload.string("landowner_id", min_len=1)
    requested = payload.integer("requested_price_cents", minimum=1)

    require_owner(landowner["id"])
    if parcel["landowner_id"] != landowner["id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "the parcel is not owned by the named landowner"
        )

    if landowner["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", "the landowner is not ACTIVE")

    if rnd["status"] != "OPEN":
        raise ApiError("ERR_ROUND_WINDOW_CLOSED", "the round is not OPEN")
    if not (rnd["opens_on"] <= db.clock <= rnd["closes_on"]):
        raise ApiError(
            "ERR_ROUND_WINDOW_CLOSED", "the logical clock is outside the round window"
        )

    if parcel["status"] != "ELIGIBLE":
        raise ApiError("ERR_PARCEL_NOT_ELIGIBLE", "the parcel is not ELIGIBLE")
    if parcel["restricted_value_cents"] >= parcel["unrestricted_value_cents"]:
        raise ApiError(
            "ERR_PARCEL_NOT_ELIGIBLE",
            "restricted_value_cents is not strictly below unrestricted_value_cents",
        )

    preliminary = calc.preliminary_easement_value_cents(
        parcel["unrestricted_value_cents"], parcel["restricted_value_cents"]
    )
    if requested > calc.requested_price_ceiling_cents(preliminary):
        raise ApiError(
            "ERR_REQUESTED_PRICE_ABOVE_PRELIMINARY_CEILING",
            "requested_price_cents exceeds 110% of the preliminary easement value",
        )

    row = base_row()
    row.update(
        {
            "funding_round_id": rnd["id"],
            "parcel_id": parcel["id"],
            "landowner_id": landowner["id"],
            "requested_price_cents": requested,
            "status": "RECEIVED",
            "closing_status": "NOT_APPLICABLE",
            "funding_plan_status": "UNFUNDED",
            "contiguity_acres_at_receipt": parcel["contiguous_preserved_acres"],
            "composite_score": None,
            "rank_position": None,
            "preliminary_easement_value_cents": preliminary,
            "certified_easement_value_cents": None,
            "structure": None,
            "donation_pct": Decimal(0),
            "installment_years": None,
            "proposed_price_cents": None,
            "current_offer_cents": None,
            "current_offer_expires_on": None,
            "last_counter_cents": None,
            "agreed_price_cents": None,
            "donation_cents": 0,
            "bargain_sale_price_cents": None,
            "admin_fee_cents": None,
            "total_program_cost_cents": None,
            "funded_cost_cents": None,
            "first_installment_cents": None,
            "final_installment_cents": None,
            "installment_interest_total_cents": None,
            "offer_issued_by_user_id": None,
            "withdrawal_reason": None,
        }
    )
    db.applications[row["id"]] = row

    parcel["status"] = "UNDER_APPLICATION"
    touch(parcel)
    touch(rnd)
    return created(serialize.application(row))


@bp.get("/applications/<application_id>")
def read_application(application_id):
    authenticate(READ_ROLES)
    return ok(serialize.application(lookup.get_application(application_id)))


@bp.get("/applications")
def list_applications():
    authenticate(READ_ROLES)
    limit, offset = pagination(request.args)
    rows = list(db.applications.values())
    for key in ("funding_round_id", "parcel_id", "landowner_id"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    status = request.args.get("status")
    if status is not None:
        if status not in APPLICATION_STATUSES:
            raise ApiError("ERR_INVALID_REQUEST", "status filter is not valid")
        rows = [r for r in rows if r["status"] == status]
    closing_status = request.args.get("closing_status")
    if closing_status is not None:
        if closing_status not in CLOSING_STATUSES:
            raise ApiError("ERR_INVALID_REQUEST", "closing_status filter is not valid")
        rows = [r for r in rows if r["closing_status"] == closing_status]
    funding_plan_status = request.args.get("funding_plan_status")
    if funding_plan_status is not None:
        if funding_plan_status not in FUNDING_PLAN_STATUSES:
            raise ApiError("ERR_INVALID_REQUEST", "funding_plan_status filter is not valid")
        rows = [r for r in rows if r["funding_plan_status"] == funding_plan_status]
    rows.sort(
        key=lambda r: (
            0 if r["rank_position"] is not None else 1,
            r["rank_position"] if r["rank_position"] is not None else 0,
            r["created_at"],
            r["_seq"],
        )
    )
    return listing(rows, limit, offset, serialize.application)


# --------------------------------------------------------------------- offers
@bp.post("/applications/<application_id>/offers")
def issue_offer(application_id):
    user_id, role = authenticate(("AcquisitionOfficer",))
    app = lookup.get_application(application_id)
    payload = Payload(
        raw_body(),
        (
            "expected_application_version",
            "offer_cents",
            "structure",
            "offer_expires_on",
            "donation_pct",
            "installment_years",
        ),
    )
    expected = payload.integer("expected_application_version", minimum=0)
    offer_cents = payload.integer("offer_cents", minimum=1)
    structure = payload.enum("structure", STRUCTURES)
    offer_expires_on = payload.instant("offer_expires_on")
    donation_pct = payload.decimal(
        "donation_pct",
        required=False,
        default=Decimal(0),
        minimum=0,
        exclusive_max=1,
        max_decimals=4,
    )
    installment_years = payload.integer(
        "installment_years", required=False, minimum=2, maximum=10
    )

    if structure != "BARGAIN_SALE" and donation_pct != Decimal(0):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "donation_pct must be 0 unless structure is BARGAIN_SALE",
        )
    if structure != "INSTALLMENT" and installment_years is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "installment_years must be absent unless structure is INSTALLMENT",
        )
    if structure == "INSTALLMENT" and installment_years is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "installment_years is required when structure is INSTALLMENT",
        )
    if offer_expires_on <= db.clock:
        raise ApiError(
            "ERR_INVALID_REQUEST", "offer_expires_on must be strictly later than now"
        )

    if expected != app["version"]:
        raise ApiError(
            "ERR_STALE_APPLICATION_VERSION",
            "expected_application_version does not match Application.version",
        )
    if app["status"] not in ("RANKED", "COUNTERED"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "an offer may only be issued from RANKED or COUNTERED",
        )

    program = lookup.program_of_application(app)
    current_rounds = lookup.application_negotiation_round_count(app["id"])
    if current_rounds >= program["max_negotiation_rounds"]:
        raise ApiError(
            "ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
            "the program negotiation round budget is exhausted",
        )

    _check_certified_ceiling(app, offer_cents)

    cascade.append_negotiation_round(
        app,
        "OFFER",
        current_rounds + 1,
        offer_cents,
        role,
        user_id,
        offer_expires_on=offer_expires_on,
    )
    app["status"] = "OFFER_ISSUED"
    app["structure"] = structure
    app["donation_pct"] = donation_pct
    app["installment_years"] = installment_years
    app["current_offer_cents"] = offer_cents
    app["current_offer_expires_on"] = offer_expires_on
    app["proposed_price_cents"] = offer_cents
    app["offer_issued_by_user_id"] = user_id
    cascade.rewrite_cost_build_up(app, offer_cents)
    touch(app)
    return ok(serialize.application(app))


# ------------------------------------------------------------------- counters
@bp.post("/applications/<application_id>/counters")
def counter_offer(application_id):
    user_id, role = authenticate(("Landowner",))
    app = lookup.get_application(application_id)
    payload = Payload(raw_body(), ("counter_cents", "rationale"))
    counter_cents = payload.integer("counter_cents", minimum=1)
    rationale = payload.string(
        "rationale", required=False, default=None, min_len=1, max_len=500
    )

    require_owner(app["landowner_id"])

    if app["status"] != "OFFER_ISSUED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "a counter requires the application to be OFFER_ISSUED",
        )
    if counter_cents <= app["current_offer_cents"]:
        raise ApiError(
            "ERR_COUNTER_NOT_HIGHER",
            "the counter must be strictly greater than current_offer_cents",
        )
    if db.clock > app["current_offer_expires_on"]:
        raise ApiError("ERR_COUNTER_NOT_HIGHER", "the offer has already expired")

    _check_certified_ceiling(app, counter_cents)

    cascade.append_negotiation_round(
        app,
        "COUNTER",
        max(1, lookup.application_negotiation_round_count(app["id"])),
        counter_cents,
        role,
        user_id,
        rationale=rationale,
    )
    app["status"] = "COUNTERED"
    app["last_counter_cents"] = counter_cents
    app["proposed_price_cents"] = counter_cents
    cascade.rewrite_cost_build_up(app, counter_cents)
    if app["funding_plan_status"] == "FUNDED":
        app["funding_plan_status"] = "UNDERFUNDED"
    touch(app)
    return ok(serialize.application(app))


# ----------------------------------------------------------------- acceptance
@bp.post("/applications/<application_id>/acceptance")
def accept(application_id):
    user_id, role = authenticate(("Landowner", "AcquisitionOfficer"))
    app = lookup.get_application(application_id)
    Payload(raw_body(), ())

    if role == "Landowner":
        require_owner(app["landowner_id"])
        if app["status"] != "OFFER_ISSUED":
            raise ApiError(
                "ERR_INVALID_APPLICATION_STATE",
                "a Landowner accepts only from OFFER_ISSUED",
            )
        if db.clock > app["current_offer_expires_on"]:
            raise ApiError(
                "ERR_INVALID_APPLICATION_STATE", "the offer has already expired"
            )
        price = app["current_offer_cents"]
    else:
        if app["status"] != "COUNTERED":
            raise ApiError(
                "ERR_INVALID_APPLICATION_STATE",
                "an AcquisitionOfficer accepts only from COUNTERED",
            )
        price = app["last_counter_cents"]

    _check_certified_ceiling(app, price)

    if app["funding_plan_status"] != "FUNDED":
        raise ApiError(
            "ERR_FUNDING_PLAN_INCOMPLETE", "funding_plan_status must be exactly FUNDED"
        )
    if app["funded_cost_cents"] != app["total_program_cost_cents"]:
        raise ApiError(
            "ERR_FUNDING_PLAN_INCOMPLETE",
            "funded_cost_cents does not equal total_program_cost_cents",
        )

    reserved = [
        c
        for c in lookup.commitments_of_application(app["id"])
        if c["status"] == "RESERVED"
    ]
    per_source = {}
    for commitment in reserved:
        per_source[commitment["funding_source_id"]] = (
            per_source.get(commitment["funding_source_id"], 0) + commitment["amount_cents"]
        )
    for source_id, amount in per_source.items():
        source = db.funding_sources[source_id]
        if lookup.source_committed_cents(source_id) + amount > source["authorized_cents"]:
            raise ApiError(
                "ERR_SOURCE_WINDOW_CAPACITY_EXCEEDED",
                "obligating this plan would exceed the source's authorized_cents",
            )

    cascade.append_negotiation_round(
        app,
        "ACCEPTANCE",
        max(1, lookup.application_negotiation_round_count(app["id"])),
        price,
        role,
        user_id,
    )
    app["agreed_price_cents"] = price
    app["status"] = "ACCEPTED"

    for commitment in reserved:
        commitment["status"] = "OBLIGATED"
        touch(commitment)
    app["funding_plan_status"] = "OBLIGATED"
    for source_id in per_source:
        source = db.funding_sources[source_id]
        touch(source)
        cascade.apply_threshold_flip(source)

    cascade.create_closing_requirements(app)
    app["closing_status"] = "PENDING_REQUIREMENTS"
    touch(app)
    return ok(serialize.application(app))


# ----------------------------------------------------------------- withdrawal
@bp.post("/applications/<application_id>/withdrawal")
def withdraw(application_id):
    user_id, role = authenticate(("Landowner",))
    app = lookup.get_application(application_id)
    payload = Payload(raw_body(), ("withdrawal_reason",))
    reason = payload.string("withdrawal_reason", min_len=1, max_len=500)

    require_owner(app["landowner_id"])

    if app["status"] not in ("RECEIVED", "RANKED", "OFFER_ISSUED", "COUNTERED"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "withdrawal is only available before acceptance",
        )

    cascade.append_negotiation_round(
        app,
        "WITHDRAWAL",
        max(1, lookup.application_negotiation_round_count(app["id"])),
        None,
        role,
        user_id,
    )
    app["status"] = "WITHDRAWN"
    app["withdrawal_reason"] = reason
    cascade.release_application_commitments(
        app, ("RESERVED", "OBLIGATED"), cascade.LAPSE_APPLICATION_WITHDRAWN
    )
    cascade.parcel_release(app)
    touch(app)
    return ok(serialize.application(app))


# --------------------------------------------------------------- funding plan
@bp.post("/applications/<application_id>/funding-plan")
def assemble_funding_plan(application_id):
    authenticate(("ProgramAdmin",))
    app = lookup.get_application(application_id)
    payload = Payload(
        raw_body(), ("expected_application_version", "target_closing_date")
    )
    expected = payload.integer("expected_application_version", minimum=0)
    target_closing_date = payload.instant("target_closing_date")

    if expected != app["version"]:
        raise ApiError(
            "ERR_STALE_APPLICATION_VERSION",
            "expected_application_version does not match Application.version",
        )
    if app["status"] not in ("RANKED", "OFFER_ISSUED", "COUNTERED"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "a funding plan may only be assembled before acceptance",
        )
    if app["funding_plan_status"] not in ("UNFUNDED", "FUNDED", "UNDERFUNDED"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "the funding dimension admits no re-assembly",
        )
    if app["total_program_cost_cents"] is None:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "no offer has been issued, so there is no program cost to fund",
        )

    program = lookup.program_of_application(app)
    takes, federal_total, local_total, state_total = cascade.run_waterfall(
        app, program, target_closing_date
    )

    cascade.release_application_commitments(
        app, ("RESERVED",), cascade.LAPSE_PLAN_SUPERSEDED
    )
    commitments = cascade.materialise_commitments(app, takes)
    app["funded_cost_cents"] = app["total_program_cost_cents"]
    app["funding_plan_status"] = "FUNDED"
    touch(app)

    return ok(
        {
            "application_id": app["id"],
            "funded_cost_cents": app["funded_cost_cents"],
            "commitment_count": len(commitments),
            "federal_total_cents": federal_total,
            "local_total_cents": local_total,
            "state_total_cents": state_total,
            "remainder_absorbed_cents": sum(
                c["absorbed_remainder_cents"] for c in commitments
            ),
            "commitment_ids": [c["id"] for c in commitments],
        }
    )


# ------------------------------------------------------------ nested listings
@bp.get("/applications/<application_id>/negotiation-rounds")
def list_negotiation_rounds(application_id):
    authenticate(("ProgramAdmin", "AcquisitionOfficer", "Landowner"))
    app = lookup.get_application(application_id)
    limit, offset = pagination(request.args)
    kind = request.args.get("kind")
    if kind is not None and kind not in NEGOTIATION_KINDS:
        raise ApiError("ERR_INVALID_REQUEST", "kind filter is not valid")
    rows = lookup.negotiation_rounds_of(app["id"])
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.negotiation_round)


@bp.get("/applications/<application_id>/closing-requirements")
def list_application_requirements(application_id):
    authenticate(("ProgramAdmin", "AcquisitionOfficer", "Landowner"))
    app = lookup.get_application(application_id)
    limit, offset = pagination(request.args)
    status = request.args.get("status")
    requirement_type = request.args.get("requirement_type")
    if status is not None and status not in REQUIREMENT_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST", "status filter is not valid")
    if requirement_type is not None and requirement_type not in REQUIREMENT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "requirement_type filter is not valid")
    rows = lookup.requirements_of(app["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if requirement_type is not None:
        rows = [r for r in rows if r["requirement_type"] == requirement_type]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.closing_requirement)


# -------------------------------------------------------------------- closing
@bp.post("/applications/<application_id>/closing")
def record_closing(application_id):
    authenticate(("ProgramAdmin",))
    app = lookup.get_application(application_id)
    payload = Payload(
        raw_body(),
        (
            "recorded_on",
            "protected_acres",
            "residential_rights_retained",
            "subdivision_permitted",
            "permitted_uses",
        ),
    )
    recorded_on = payload.instant("recorded_on")
    protected_acres = payload.decimal("protected_acres", exclusive_min=0)
    retained = payload.integer("residential_rights_retained", minimum=0)
    subdivision = payload.boolean("subdivision_permitted", required=False, default=False)
    permitted_uses = payload.enum_array("permitted_uses", PERMITTED_USES, min_items=1)
    if recorded_on > db.clock:
        raise ApiError("ERR_INVALID_REQUEST", "recorded_on may not lie in the future")

    if app["closing_status"] != "CLEARED":
        raise ApiError(
            "ERR_INVALID_CLOSING_STATE", "closing requires closing_status == CLEARED"
        )
    if app["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "closing requires status == ACCEPTED"
        )

    parcel = lookup.parcel_of_application(app)
    if retained > parcel["baseline_dwelling_rights"]:
        raise ApiError(
            "ERR_RESIDENTIAL_RIGHTS_OVERDRAWN",
            "residential_rights_retained exceeds the parcel baseline",
        )

    survey = None
    for requirement in lookup.requirements_of(app["id"]):
        if requirement["requirement_type"] == "BOUNDARY_SURVEY":
            survey = requirement
            break
    if survey is None:
        raise ApiError(
            "ERR_REQUIREMENT_SCOPE_MISMATCH",
            "the application has no BOUNDARY_SURVEY requirement",
        )
    if survey["status"] == "WAIVED":
        expected_acres = parcel["acres"]
    elif survey["status"] == "SATISFIED" and survey["surveyed_acres"] is not None:
        expected_acres = survey["surveyed_acres"]
    else:
        raise ApiError(
            "ERR_REQUIREMENT_SCOPE_MISMATCH",
            "the BOUNDARY_SURVEY requirement is neither accepted nor waived",
        )
    if protected_acres != expected_acres:
        raise ApiError(
            "ERR_REQUIREMENT_SCOPE_MISMATCH",
            "protected_acres does not match the accepted survey acreage",
        )

    if app["funding_plan_status"] != "OBLIGATED":
        raise ApiError(
            "ERR_FUNDING_PLAN_STALE",
            "the funding plan is not in the OBLIGATED posture required to close",
        )

    program = lookup.program_of_application(app)
    easement = base_row()
    easement.update(
        {
            "application_id": app["id"],
            "parcel_id": parcel["id"],
            "recorded_on": recorded_on,
            "protected_acres": protected_acres,
            "impervious_allowance_sqft": calc.impervious_allowance_sqft(
                protected_acres, program["impervious_allowance_pct"]
            ),
            "impervious_used_sqft": 0,
            "residential_rights_retained": retained,
            "subdivision_permitted": subdivision,
            "permitted_uses": permitted_uses,
            "status": "RECORDED",
            "stewardship_status": "MONITORING_CURRENT",
            "compliance_status": "COMPLIANT",
            "stewardship_hold": False,
            "last_monitored_on": None,
            "next_monitoring_due_on": recorded_on
            + timedelta(days=int(program["monitoring_interval_days"])),
        }
    )
    db.easements[easement["id"]] = easement

    app["status"] = "CLOSED_RECORDED"
    app["closing_status"] = "CLOSED"
    sources = []
    for commitment in lookup.commitments_of_application(app["id"]):
        if commitment["status"] != "OBLIGATED":
            continue
        commitment["status"] = "DISBURSED"
        touch(commitment)
        source = db.funding_sources.get(commitment["funding_source_id"])
        if source is not None and source not in sources:
            sources.append(source)
    app["funding_plan_status"] = "DISBURSED"
    for source in sources:
        touch(source)
    parcel["status"] = "ENCUMBERED"
    touch(parcel)
    touch(program)
    touch(app)

    return created(serialize.easement(easement))


@bp.post("/applications/<application_id>/closing-cancellation")
def cancel_closing(application_id):
    authenticate(("ProgramAdmin",))
    app = lookup.get_application(application_id)
    payload = Payload(raw_body(), ("reason",))
    reason = payload.string("reason", min_len=1, max_len=500)

    if app["closing_status"] not in ("PENDING_REQUIREMENTS", "BLOCKED", "CLEARED"):
        raise ApiError(
            "ERR_INVALID_CLOSING_STATE",
            "closing cancellation requires a pending, blocked or cleared closing",
        )
    if app["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "closing cancellation requires status == ACCEPTED",
        )

    app["closing_status"] = "CANCELLED"
    cascade.release_application_commitments(
        app, ("RESERVED", "OBLIGATED"), cascade.LAPSE_CLOSING_CANCELLED
    )
    for requirement in lookup.requirements_of(app["id"]):
        if requirement["status"] in ("OUTSTANDING", "SUBMITTED", "DEFICIENT"):
            requirement["status"] = "WAIVED"
            requirement["waiver_reason"] = cascade.LAPSE_CLOSING_CANCELLED
            touch(requirement)
    app["status"] = "WITHDRAWN"
    app["withdrawal_reason"] = cascade.LAPSE_CLOSING_CANCELLED
    cascade.parcel_release(app)
    touch(app)
    return ok(serialize.application(app))
