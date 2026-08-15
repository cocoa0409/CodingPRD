"""MainExtension endpoints: design, quote, revise, as-built, finalize."""

from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE_MAIN_EXTENSION,
    ERR_FORBIDDEN_OWNER,
    ERR_INVOICE_HAS_PAYMENTS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_QUOTE_EXPIRED,
    ERR_STALE_VERSION,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    parse_iso_date,
    require_fields,
    require_int,
    require_roles,
    spine_at_least,
    validate_crossings,
)
from response import success_list, success_object
from services.calculations import (
    ciac_final_true_up,
    ciac_provisional,
    commitment_dates,
)
from services.domain import (
    commitment_for_application,
    get_application,
    get_main_extension,
    invoice_for_main_extension,
    main_extension_for_application,
    touch,
)

bp = Blueprint("main_extensions", __name__)


def _create_invoice_and_commitment(me, app, actor_user_id):
    """approve-design side effects: CIACInvoice + TimelineCommitment."""
    now = db.now_iso()
    amount_due = me["provisional_total_due_cents"]
    invoice = {
        "id": new_id(),
        "main_extension_id": me["id"],
        "service_application_id": app["id"],
        "amount_due_cents": amount_due,
        "payments_applied_cents": 0,
        "refunds_issued_cents": 0,
        "balance_due_cents": amount_due,
        "refund_required_cents": 0,
        "status": "PAID" if amount_due == 0 else "ISSUED",
        "issued_by_user_id": actor_user_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.ciac_invoices[invoice["id"]] = invoice

    base_date = db.today_date()
    optimistic, conservative = commitment_dates(
        base_date, me["design_footage_ft"], me["crossings_count"]
    )
    commitment = {
        "id": new_id(),
        "service_application_id": app["id"],
        "base_date": base_date.isoformat(),
        "optimistic_completion_date": optimistic,
        "conservative_completion_date": conservative,
        "committed_completion_date": conservative,
        "requested_completion_date": None,
        "delay_attribution": None,
        "penalty_credit_cents": 0,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.timeline_commitments[commitment["id"]] = commitment
    return invoice, commitment


@bp.route("/main-extensions", methods=["POST"])
def create_main_extension():
    require_roles("DesignEngineer")
    body = get_body()
    require_fields(body, "service_application_id", "design_footage_ft")
    app = get_application(body["service_application_id"])
    footage = require_int(body, "design_footage_ft", minimum=1)
    crossings = validate_crossings(body.get("crossings", []))
    rock = body.get("rock_excavation_expected", False)
    if not isinstance(rock, bool):
        raise_error(ERR_INVALID_REQUEST, "rock_excavation_expected must be a boolean")
    check_app_mutable(app)
    existing = main_extension_for_application(app["id"])
    if existing is not None:
        raise_error(ERR_DUPLICATE_MAIN_EXTENSION, "A non-CANCELLED main extension already exists")
    if app["status"] != "LOAD_CONFIRMED":
        raise_error(ERR_INVALID_STATE, "Application must be LOAD_CONFIRMED to create a main extension")
    calc = ciac_provisional(footage, crossings, rock, app["appliance_count"])
    now = db.now_iso()
    me = {
        "id": new_id(),
        "service_application_id": app["id"],
        "design_footage_ft": footage,
        "crossings": crossings,
        "rock_excavation_expected": rock,
        "crossings_count": calc["crossings_count"],
        "allowance_ft": calc["allowance_ft"],
        "provisional_base_cost_cents": calc["provisional_base_cost_cents"],
        "provisional_surcharges_cents": calc["provisional_surcharges_cents"],
        "provisional_net_ciac_cents": calc["provisional_net_ciac_cents"],
        "provisional_gross_up_cents": calc["provisional_gross_up_cents"],
        "provisional_total_due_cents": calc["provisional_total_due_cents"],
        "actual_footage_ft": None,
        "actual_unit_cost_cents": None,
        "actual_rock_excavation": None,
        "actual_crossings": None,
        "final_net_ciac_cents": None,
        "final_gross_up_cents": None,
        "final_total_due_cents": None,
        "ciac_delta_cents": None,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.main_extensions[me["id"]] = me
    # System transition: application LOAD_CONFIRMED → DESIGN
    app["status"] = "DESIGN"
    touch(app)
    return success_object(me, 201)


@bp.route("/main-extensions/<mid>", methods=["GET"])
def get_one_main_extension(mid):
    require_roles(*ANY_ROLE)
    return success_object(get_main_extension(mid))


@bp.route("/main-extensions", methods=["GET"])
def list_main_extensions():
    require_roles(*ANY_ROLE)
    records = list(db.main_extensions.values())
    app_id = request.args.get("service_application_id")
    if app_id is not None:
        records = [m for m in records if m["service_application_id"] == app_id]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/main-extensions/<mid>/submit-design", methods=["POST"])
def submit_design(mid):
    require_roles("DesignEngineer")
    me = get_main_extension(mid)
    app = get_application(me["service_application_id"])
    check_app_mutable(app)
    if me["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Only DRAFT designs can be submitted")
    me["status"] = "DESIGN_SUBMITTED"
    touch(me)
    return success_object(me)


@bp.route("/main-extensions/<mid>/approve-design", methods=["POST"])
def approve_design(mid):
    user_id, _ = require_roles("NewBusinessRep")
    me = get_main_extension(mid)
    app = get_application(me["service_application_id"])
    check_app_mutable(app)
    if me["status"] != "DESIGN_SUBMITTED":
        raise_error(ERR_INVALID_STATE, "Only DESIGN_SUBMITTED designs can be approved")
    if app["status"] != "DESIGN":
        raise_error(ERR_INVALID_STATE, "Application must be in DESIGN to approve the design")
    _create_invoice_and_commitment(me, app, user_id)
    me["status"] = "QUOTED"
    touch(me)
    # Application DESIGN → QUOTED with quote_valid_until = today + 30 days
    import datetime as _dt
    app["quote_valid_until"] = (db.today_date() + _dt.timedelta(days=30)).isoformat()
    app["status"] = "QUOTED"
    touch(app)
    return success_object(me)


@bp.route("/main-extensions/<mid>/accept-quote", methods=["POST"])
def accept_quote(mid):
    user_id, _ = require_roles("Builder")
    me = get_main_extension(mid)
    app = get_application(me["service_application_id"])
    if app["builder_id"] != user_id:
        raise_error(ERR_FORBIDDEN_OWNER, "Builder does not own this application")
    check_app_mutable(app)
    if me["status"] != "QUOTED":
        raise_error(ERR_INVALID_STATE, "Only QUOTED designs can be accepted")
    if app["quote_valid_until"] is not None:
        qvu = parse_iso_date(app["quote_valid_until"], "quote_valid_until")
        if db.today_date() > qvu:
            raise_error(ERR_QUOTE_EXPIRED, "The quote has expired")
    me["status"] = "ACCEPTED"
    touch(me)
    # Application QUOTED → CIAC_PENDING; zero-CIAC chain fires immediately
    app["status"] = "CIAC_PENDING"
    touch(app)
    invoice = invoice_for_main_extension(me["id"])
    if invoice is not None and invoice["amount_due_cents"] == 0:
        invoice["status"] = "PAID"
        touch(invoice)
        app["status"] = "APPROVED_FOR_CONSTRUCTION"
        touch(app)
    return success_object(me)


@bp.route("/main-extensions/<mid>/revise", methods=["POST"])
def revise(mid):
    require_roles("DesignEngineer")
    me = get_main_extension(mid)
    body = get_body()
    require_fields(body, "expected_main_extension_version")
    if body["expected_main_extension_version"] != me["version"]:
        raise_error(ERR_STALE_VERSION, "Main extension version is stale")
    app = get_application(me["service_application_id"])
    check_app_mutable(app)
    if me["status"] != "QUOTED":
        raise_error(ERR_INVALID_STATE, "Only QUOTED designs can be revised")
    invoice = invoice_for_main_extension(me["id"])
    if invoice is not None and invoice["payments_applied_cents"] != 0:
        raise_error(ERR_INVOICE_HAS_PAYMENTS, "Cannot revise a design whose invoice has payments")
    # Optional design input updates
    if "design_footage_ft" in body:
        me["design_footage_ft"] = require_int(body, "design_footage_ft", minimum=1)
    if "crossings" in body:
        me["crossings"] = validate_crossings(body["crossings"])
    if "rock_excavation_expected" in body:
        rock = body["rock_excavation_expected"]
        if not isinstance(rock, bool):
            raise_error(ERR_INVALID_REQUEST, "rock_excavation_expected must be a boolean")
        me["rock_excavation_expected"] = rock
    # Unwind: invoice → VOID, commitment PROPOSED → CANCELLED, app QUOTED → DESIGN
    if invoice is not None and invoice["status"] == "ISSUED":
        invoice["status"] = "VOID"
        touch(invoice)
    commitment = commitment_for_application(app["id"])
    if commitment is not None and commitment["status"] == "PROPOSED":
        commitment["status"] = "CANCELLED"
        touch(commitment)
    app["status"] = "DESIGN"
    app["quote_valid_until"] = None
    touch(app)
    # Recompute provisional figures from (possibly updated) design inputs
    calc = ciac_provisional(
        me["design_footage_ft"], me["crossings"], me["rock_excavation_expected"], app["appliance_count"]
    )
    me.update(calc)
    me["status"] = "DRAFT"
    touch(me)
    return success_object(me)


@bp.route("/main-extensions/<mid>/record-as-built", methods=["POST"])
def record_as_built(mid):
    require_roles("FieldSupervisor")
    me = get_main_extension(mid)
    app = get_application(me["service_application_id"])
    body = get_body()
    require_fields(
        body, "actual_footage_ft", "actual_unit_cost_cents", "actual_rock_excavation", "actual_crossings"
    )
    footage = require_int(body, "actual_footage_ft", minimum=1)
    unit_cost = require_int(body, "actual_unit_cost_cents", minimum=1)
    rock = body["actual_rock_excavation"]
    if not isinstance(rock, bool):
        raise_error(ERR_INVALID_REQUEST, "actual_rock_excavation must be a boolean")
    crossings = validate_crossings(body["actual_crossings"])
    check_app_mutable(app)
    if me["status"] != "CONSTRUCTED":
        raise_error(ERR_INVALID_STATE, "Only CONSTRUCTED main extensions can record as-built")
    if not spine_at_least(app, "SERVICE_INSTALLED"):
        raise_error(ERR_INVALID_STATE, "Application must be at SERVICE_INSTALLED or later")
    me["actual_footage_ft"] = footage
    me["actual_unit_cost_cents"] = unit_cost
    me["actual_rock_excavation"] = rock
    me["actual_crossings"] = crossings
    me["status"] = "AS_BUILT_RECORDED"
    touch(me)
    return success_object(me)


@bp.route("/main-extensions/<mid>/finalize", methods=["POST"])
def finalize(mid):
    require_roles("BillingClerk")
    me = get_main_extension(mid)
    app = get_application(me["service_application_id"])
    check_app_mutable(app)
    if me["status"] != "AS_BUILT_RECORDED":
        raise_error(ERR_INVALID_STATE, "Only AS_BUILT_RECORDED main extensions can be finalized")
    result = ciac_final_true_up(
        me["actual_footage_ft"],
        me["actual_unit_cost_cents"],
        me["actual_crossings"],
        me["actual_rock_excavation"],
        me["allowance_ft"],
        me["provisional_total_due_cents"],
    )
    me.update(result)
    me["status"] = "FINALIZED"
    touch(me)
    # Invoice true-up
    invoice = invoice_for_main_extension(me["id"])
    if invoice is not None:
        delta = result["ciac_delta_cents"]
        final_total = result["final_total_due_cents"]
        if invoice["status"] == "PAID":
            # The true-up reprices the amount due to the final total on every branch;
            # §3.3: "The balance may go momentarily negative only inside a finalization
            # true-up, in which case refund_required_cents ... carries the magnitude."
            invoice["amount_due_cents"] = final_total
            if delta > 0:
                invoice["status"] = "ISSUED"
            elif delta < 0:
                invoice["status"] = "REFUND_PENDING"
                invoice["refund_required_cents"] = -delta
            else:
                invoice["status"] = "SETTLED"
            invoice["balance_due_cents"] = invoice["amount_due_cents"] - invoice["payments_applied_cents"]
            touch(invoice)
        elif invoice["status"] in ("ISSUED", "PARTIALLY_PAID"):
            invoice["amount_due_cents"] = final_total
            invoice["balance_due_cents"] = final_total - invoice["payments_applied_cents"]
            touch(invoice)
    return success_object(me)
