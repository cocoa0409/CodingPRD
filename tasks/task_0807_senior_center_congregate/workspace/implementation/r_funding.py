"""Grant awards, donations, the funding waterfall, funded services, OAA report."""
from flask import Blueprint, request

from store import db, base_common, touch
from core import (
    require_actor, authorize, get_body, ok_object, ok_array, paginate,
    req_str, req_enum, req_int, err, parse_dt, round_half_up,
)
from lookups import get_grant, get_donation, get_participant, get_funded_service
from serializers import ser_grant, ser_donation, ser_funded_service

bp = Blueprint("funding", __name__)

SERVICE_CATEGORIES = {"CONGREGATE_MEAL", "TRANSPORTATION", "WELLNESS", "ACTIVITY"}
DONATION_CATEGORIES = SERVICE_CATEGORIES | {"UNRESTRICTED"}
OAA_TITLES = {"IIIB", "IIIC1", "IIIC2", "IIID", "IIIE"}
UNIT_COST_CENTS = {
    "CONGREGATE_MEAL": 850,
    "TRANSPORTATION": 1200,
    "WELLNESS": 1500,
    "ACTIVITY": 400,
}


# ------------------------------- GrantAward --------------------------------
@bp.post("/grant-awards")
def create_grant():
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    body = get_body()
    title = req_str(body, "title")
    oaa_title = req_enum(body, "oaa_title", OAA_TITLES)
    category = req_enum(body, "category", SERVICE_CATEGORIES)
    authorized = req_int(body, "authorized_cents", minimum=1)
    rec = base_common()
    rec.update({
        "title": title,
        "oaa_title": oaa_title,
        "category": category,
        "authorized_cents": authorized,
        "committed_cents": 0,
        "available_cents": authorized,
        "status": "DRAFT",
    })
    db.grants[rec["id"]] = rec
    return ok_object(ser_grant(rec), 201)


@bp.get("/grant-awards/<gid>")
def get_grant_route(gid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Auditor"})
    return ok_object(ser_grant(get_grant(gid)))


@bp.post("/grant-awards/<gid>/activate")
def activate_grant(gid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    rec = get_grant(gid)
    if rec["status"] not in ("DRAFT", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Grant can only be activated from DRAFT or SUSPENDED")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok_object(ser_grant(rec))


@bp.post("/grant-awards/<gid>/suspend")
def suspend_grant(gid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    rec = get_grant(gid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE grant can be suspended")
    rec["status"] = "SUSPENDED"
    # CASCADE hop B/C: reverse every APPLIED funded service drawing on this grant.
    for fs in db.funded_services.values():
        if fs["grant_award_id"] != gid or fs["status"] != "APPLIED":
            continue
        _reverse_funding(fs, rec)
    touch(rec)
    return ok_object(ser_grant(rec))


# -------------------------------- Donation ---------------------------------
@bp.post("/donations")
def create_donation():
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    body = get_body()
    donor_name = req_str(body, "donor_name")
    category = req_enum(body, "category", DONATION_CATEGORIES)
    amount = req_int(body, "amount_cents", minimum=1)
    rec = base_common()
    rec.update({
        "donor_name": donor_name,
        "category": category,
        "amount_cents": amount,
        "remaining_cents": amount,
        "restricted": category != "UNRESTRICTED",
    })
    db.donations[rec["id"]] = rec
    return ok_object(ser_donation(rec), 201)


@bp.get("/donations/<did>")
def get_donation_route(did):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Auditor"})
    return ok_object(ser_donation(get_donation(did)))


# ----------------------------- FundedService -------------------------------
def _reverse_funding(fs, grant):
    """Compensating waterfall: return funds to sources, bump all touched rows."""
    ga = fs["grant_amount_cents"]
    da = fs["donation_amount_cents"]
    grant["committed_cents"] -= ga
    grant["available_cents"] += ga
    if fs.get("donation_id"):
        donation = db.donations.get(fs["donation_id"])
        if donation is not None:
            donation["remaining_cents"] += da
            touch(donation)
    participant = db.participants.get(fs["participant_id"])
    if participant is not None:
        participant["funded_cents"] -= (ga + da)
        touch(participant)
    fs["grant_amount_cents"] = 0
    fs["donation_amount_cents"] = 0
    fs["unfunded_amount_cents"] = fs["billable_cents"]
    fs["funding_status"] = "UNFUNDED"
    fs["status"] = "REVERSED"
    touch(fs)


@bp.post("/funded-services")
def create_funded_service():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator"})
    body = get_body()
    participant_id = req_str(body, "participant_id")
    category = req_enum(body, "category", SERVICE_CATEGORIES)
    quantity = req_int(body, "quantity", minimum=1)
    service_raw = req_str(body, "service_date")
    parse_dt(service_raw, "service_date")
    grant_award_id = req_str(body, "grant_award_id")
    donation_id = body.get("donation_id")
    if donation_id is not None and (not isinstance(donation_id, str) or donation_id == ""):
        raise err("ERR_VALIDATION", "Invalid 'donation_id'")
    expected_version = req_int(body, "expected_grant_award_version")

    # Existence, left-to-right: participant, grant, donation.
    participant = get_participant(participant_id)
    grant = get_grant(grant_award_id)
    donation = get_donation(donation_id) if donation_id else None

    # OCC on the grant pool.
    if expected_version != grant["version"]:
        raise err("ERR_STALE_VERSION", "Stale grant award version")

    # State: grant must be ACTIVE.
    if grant["status"] != "ACTIVE":
        raise err("ERR_GRANT_NOT_ACTIVE", "Grant is not ACTIVE")

    # Funding-category coherence.
    if category != grant["category"]:
        raise err("ERR_GRANT_CATEGORY_MISMATCH", "Funded service category != grant category")
    if donation is not None and donation["category"] not in (category, "UNRESTRICTED"):
        raise err("ERR_DONATION_CATEGORY_MISMATCH", "Donation category mismatch")

    # Waterfall (on_apply): grant first, then donation.
    billable = quantity * UNIT_COST_CENTS[category]
    grant_amount = min(billable, grant["available_cents"])
    remaining = billable - grant_amount
    donation_amount = min(remaining, donation["remaining_cents"]) if donation else 0
    unfunded = remaining - donation_amount
    if unfunded == 0:
        funding_status = "FUNDED"
    elif (grant_amount + donation_amount) == 0:
        funding_status = "UNFUNDED"
    else:
        funding_status = "PARTIALLY_FUNDED"

    rec = base_common()
    rec.update({
        "participant_id": participant_id,
        "category": category,
        "quantity": quantity,
        "service_date": service_raw,
        "grant_award_id": grant_award_id,
        "donation_id": donation_id,
        "billable_cents": billable,
        "grant_amount_cents": grant_amount,
        "donation_amount_cents": donation_amount,
        "unfunded_amount_cents": unfunded,
        "funding_status": funding_status,
        "status": "APPLIED",
    })
    # Commit side effects.
    grant["committed_cents"] += grant_amount
    grant["available_cents"] -= grant_amount
    if donation is not None:
        donation["remaining_cents"] -= donation_amount
    participant["funded_cents"] += (grant_amount + donation_amount)
    touch(grant)  # only the grant pool advances its version on apply (PRD 3.3)

    db.funded_services[rec["id"]] = rec
    return ok_object(ser_funded_service(rec), 201)


@bp.get("/funded-services/<fid>")
def get_funded_service_route(fid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Auditor"})
    return ok_object(ser_funded_service(get_funded_service(fid)))


@bp.get("/funded-services")
def list_funded_services():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Auditor"})
    args = request.args
    rows = list(db.funded_services.values())
    for key in ("participant_id", "grant_award_id", "donation_id", "category"):
        if key in args:
            rows = [r for r in rows if r.get(key) == args.get(key)]
    window, page = paginate(rows)
    return ok_array([ser_funded_service(r) for r in window], page)


@bp.post("/funded-services/<fid>/reverse")
def reverse_funded_service(fid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator"})
    fs = get_funded_service(fid)
    if fs["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Only an APPLIED funded service can be reversed")
    grant = db.grants.get(fs["grant_award_id"])
    _reverse_funding(fs, grant)
    if grant is not None:
        touch(grant)
    return ok_object(ser_funded_service(fs))


# ------------------------------- OAA report --------------------------------
@bp.get("/reports/oaa-units")
def oaa_units_report():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Auditor"})
    args = request.args
    category = args.get("category")
    if category not in SERVICE_CATEGORIES:
        raise err("ERR_VALIDATION", "category must be a valid service category")
    if "from" not in args or "to" not in args:
        raise err("ERR_VALIDATION", "from and to are required")
    dfrom = parse_dt(args.get("from"), "from")
    dto = parse_dt(args.get("to"), "to")

    total_units = 0
    total_billable = 0
    grant_funded = 0
    donation_funded = 0
    unfunded = 0
    for fs in db.funded_services.values():
        if fs["category"] != category or fs["status"] != "APPLIED":
            continue
        sd = parse_dt(fs["service_date"], "service_date")
        if not (dfrom <= sd <= dto):
            continue
        total_units += fs["quantity"]
        total_billable += fs["billable_cents"]
        grant_funded += fs["grant_amount_cents"]
        donation_funded += fs["donation_amount_cents"]
        unfunded += fs["unfunded_amount_cents"]
    cost_per_unit = round_half_up(total_billable, total_units) if total_units > 0 else 0
    return ok_object({
        "category": category,
        "total_units": total_units,
        "total_billable_cents": total_billable,
        "grant_funded_cents": grant_funded,
        "donation_funded_cents": donation_funded,
        "unfunded_cents": unfunded,
        "cost_per_unit_cents": cost_per_unit,
    })
