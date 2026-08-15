"""District CRUD + lifecycle transitions + district-scoped list endpoints."""
from flask import Blueprint, request

import errors
import shape
import services
from envelope import ok_object
from helpers import (get_or_404, list_response, sort_created,
                     sort_due_date, sort_parcel_number)
from security import (ALL_ROLES, STAFF_ROLES, authenticate, require_role)
from serializers import (ser_assessment, ser_change_order, ser_district,
                         ser_estimate, ser_hearing, ser_objection,
                         ser_parcel, ser_petition, ser_phase, ser_resolution,
                         ser_invoice)
from store import STORE, new_id, now, touch

bp = Blueprint("districts", __name__)

_ABANDONABLE = {"DRAFT", "PETITIONING", "SCOPING", "HEARING_SCHEDULED", "OBJECTION_WINDOW"}


def _district_or_404(did):
    return get_or_404("districts", did, errors.DISTRICT_NOT_FOUND, "District not found")


@bp.route("/districts", methods=["POST"])
def create_district():
    body = shape.get_body()
    name = shape.req_str(body, "name")
    methodology = shape.req_enum(body, "methodology", {"PER_PARCEL", "FRONT_FOOT"})
    interest_method = shape.req_enum(body, "interest_method", {"SIMPLE", "COMPOUND"})
    rate_bp = shape.opt_int(body, "annual_interest_rate_bp", 400)
    if rate_bp < 0 or rate_bp > 2000:
        errors.raise_err(errors.INVALID_REQUEST,
                         "annual_interest_rate_bp must be between 0 and 2000")
    season_start = shape.req_mmdd(body, "season_start_mmdd")
    season_end = shape.req_mmdd(body, "season_end_mmdd")
    if season_start > season_end:
        errors.raise_err(errors.INVALID_REQUEST,
                         "season_start_mmdd must be on or before season_end_mmdd")
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    ts = now()
    d = {
        "id": new_id(),
        "name": name,
        "methodology": methodology,
        "interest_method": interest_method,
        "annual_interest_rate_bp": rate_bp,
        "season_start_mmdd": season_start,
        "season_end_mmdd": season_end,
        "status": "DRAFT",
        "remand_count": 0,
        "protest_frontage_pct": None,
        "approved_estimate_id": None,
        "final_total_cost_cents": None,
        "levy_date": None,
        "payment_option_deadline": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("districts", d)
    return ok_object(ser_district(d), 201)


@bp.route("/districts", methods=["GET"])
def list_districts():
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    records = list(STORE.districts.values())
    status = request.args.get("status")
    if status:
        records = [d for d in records if d["status"] == status]
    return list_response(sort_created(records), ser_district, paginated=True)


@bp.route("/districts/<did>", methods=["GET"])
def get_district(did):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    d = _district_or_404(did)
    return ok_object(ser_district(d))


@bp.route("/districts/<did>/abandon", methods=["POST"])
def abandon(did):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    d = _district_or_404(did)
    if d["status"] not in _ABANDONABLE:
        errors.raise_err(errors.DISTRICT_NOT_ABANDONABLE,
                         "District cannot be abandoned from its current status")
    services.abandon_district(d)
    return ok_object(ser_district(d))


@bp.route("/districts/<did>/close-objection-window", methods=["POST"])
def close_objection_window(did):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    d = _district_or_404(did)
    if d["status"] != "OBJECTION_WINDOW":
        errors.raise_err(errors.DISTRICT_NOT_IN_OBJECTION_WINDOW,
                         "District must be in OBJECTION_WINDOW")
    unresolved = any(o["district_id"] == did and o["status"] in ("FILED", "UNDER_REVIEW")
                     for o in STORE.objections.values())
    if unresolved:
        errors.raise_err(errors.UNRESOLVED_OBJECTIONS,
                         "Objections remain FILED or UNDER_REVIEW")
    hearing = next((h for h in STORE.hearings.values()
                    if h["district_id"] == did and h["status"] == "HELD"), None)
    pct = services.compute_protest_pct(district=d, hearing=hearing)
    if pct is None:
        errors.raise_err(errors.UNRESOLVED_OBJECTIONS,
                         "No eligible frontage remains")
    if hearing is not None and now() <= hearing["objection_window_end"]:
        errors.raise_err(errors.OBJECTION_WINDOW_STILL_OPEN,
                         "Objection window has not ended")
    d["protest_frontage_pct"] = pct
    if hearing is not None:
        hearing["status"] = "CLOSED"
        touch(hearing)
    d["status"] = "COUNCIL_REVIEW"
    touch(d)
    return ok_object(ser_district(d))


@bp.route("/districts/<did>/complete-construction", methods=["POST"])
def complete_construction(did):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    d = _district_or_404(did)
    if d["status"] != "CONSTRUCTION":
        errors.raise_err(errors.DISTRICT_NOT_IN_CONSTRUCTION,
                         "District must be in CONSTRUCTION")
    phases = [p for p in STORE.phases.values() if p["district_id"] == did]
    if (not phases
            or any(p["status"] not in ("COMPLETED", "CANCELLED") for p in phases)
            or not any(p["status"] == "COMPLETED" for p in phases)):
        errors.raise_err(errors.PHASES_NOT_ALL_COMPLETE,
                         "All phases must be COMPLETED or CANCELLED with at least one COMPLETED")
    d["status"] = "TRUE_UP"
    touch(d)
    return ok_object(ser_district(d))


@bp.route("/districts/<did>/finalize-true-up", methods=["POST"])
def finalize_true_up(did):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["FinanceOfficer"])
    d = _district_or_404(did)
    if d["status"] != "TRUE_UP":
        errors.raise_err(errors.DISTRICT_NOT_IN_TRUE_UP,
                         "District must be in TRUE_UP")
    services.finalize_true_up(d)
    return ok_object(ser_district(d))


@bp.route("/districts/<did>/billing-run", methods=["POST"])
def billing_run(did):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["FinanceOfficer"])
    d = _district_or_404(did)
    if d["status"] != "BILLING":
        errors.raise_err(errors.DISTRICT_NOT_IN_BILLING,
                         "District must be in BILLING")
    result = services.billing_run(d)
    return ok_object(result)


@bp.route("/districts/<did>/accept", methods=["POST"])
def accept(did):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CouncilPresident"])
    d = _district_or_404(did)
    if d["status"] != "BILLING":
        errors.raise_err(errors.DISTRICT_NOT_ACCEPTABLE,
                         "District must be in BILLING")
    from serializers import district_assessment_counts
    paid, total = district_assessment_counts(d)
    if not (total > 0 and paid == total):
        errors.raise_err(errors.ASSESSMENTS_NOT_ALL_PAID,
                         "All assessments must be PAID_OFF")
    d["status"] = "ACCEPTED"
    touch(d)
    return ok_object(ser_district(d))


# --- district-scoped list endpoints ---

@bp.route("/districts/<did>/parcels", methods=["GET"])
def district_parcels(did):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _district_or_404(did)
    records = [p for p in STORE.parcels.values() if p["district_id"] == did]
    return list_response(sort_parcel_number(records), ser_parcel, paginated=True)


@bp.route("/districts/<did>/petitions", methods=["GET"])
def district_petitions(did):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _district_or_404(did)
    records = [p for p in STORE.petitions.values() if p["district_id"] == did]
    return list_response(sort_created(records), ser_petition, paginated=False)


@bp.route("/districts/<did>/cost-estimates", methods=["GET"])
def district_estimates(did):
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    _district_or_404(did)
    records = [e for e in STORE.estimates.values() if e["district_id"] == did]
    return list_response(sort_created(records), ser_estimate, paginated=False)


@bp.route("/districts/<did>/parcel-assessments", methods=["GET"])
def district_assessments(did):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _district_or_404(did)
    records = [a for a in STORE.assessments.values() if a["district_id"] == did]
    status = request.args.get("status")
    if status:
        records = [a for a in records if a["status"] == status]
    return list_response(sort_parcel_number(records), ser_assessment, paginated=True)


@bp.route("/districts/<did>/hearings", methods=["GET"])
def district_hearings(did):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _district_or_404(did)
    records = [h for h in STORE.hearings.values() if h["district_id"] == did]
    return list_response(sort_created(records), ser_hearing, paginated=False)


@bp.route("/districts/<did>/objections", methods=["GET"])
def district_objections(did):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _district_or_404(did)
    records = [o for o in STORE.objections.values() if o["district_id"] == did]
    return list_response(sort_created(records), ser_objection, paginated=False)


@bp.route("/districts/<did>/resolutions", methods=["GET"])
def district_resolutions(did):
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    _district_or_404(did)
    records = [r for r in STORE.resolutions.values() if r["district_id"] == did]
    return list_response(sort_created(records), ser_resolution, paginated=False)


@bp.route("/districts/<did>/construction-phases", methods=["GET"])
def district_phases(did):
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    _district_or_404(did)
    records = [p for p in STORE.phases.values() if p["district_id"] == did]
    return list_response(sort_created(records), ser_phase, paginated=False)


@bp.route("/districts/<did>/change-orders", methods=["GET"])
def district_change_orders(did):
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    _district_or_404(did)
    records = [c for c in STORE.change_orders.values() if c["district_id"] == did]
    return list_response(sort_created(records), ser_change_order, paginated=False)


@bp.route("/districts/<did>/invoices", methods=["GET"])
def district_invoices(did):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _district_or_404(did)
    records = [i for i in STORE.invoices.values() if i["district_id"] == did]
    status = request.args.get("status")
    if status:
        records = [i for i in records if i["status"] == status]
    return list_response(sort_due_date(records), ser_invoice, paginated=True)
