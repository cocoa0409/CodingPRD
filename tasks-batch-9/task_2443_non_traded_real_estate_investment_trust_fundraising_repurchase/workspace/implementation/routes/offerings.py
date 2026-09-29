"""Offerings (three status axes) and share classes — PRD §3.1."""

from flask import Blueprint

import domain
import validate as V
from auth import require_roles
from errors import fail
from routes.helpers import listing, new, resolve, single
from store import DB, all_rows, logical_date, new_row, parse_date, touch

bp = Blueprint("offerings", __name__)

REGISTRATION_STATES = ("DRAFT", "EFFECTIVE", "SUSPENDED", "CLOSED")
ESCROW_STATES = ("COLLECTING", "BROKEN", "FAILED")
PLAN_STATES = ("ACTIVE", "SUSPENDED", "TERMINATED")
CLASS_CODES = ("T", "S", "D", "I")
CLASS_STATES = ("ACTIVE", "CLOSED_TO_NEW")

READ_ROLES = ("SponsorOperator", "ComplianceOfficer", "TransferAgent",
              "BoardCommittee", "IndependentValuationAdvisor")
CLASS_READ_ROLES = ("SponsorOperator", "ComplianceOfficer", "TransferAgent",
                    "IndependentValuationAdvisor", "BrokerDealerRep", "InvestorUser")


# --------------------------------------------------------------------------
# Offering
# --------------------------------------------------------------------------

@bp.post("/offerings")
def create_offering():
    require_roles("SponsorOperator")
    body = V.json_body()
    name = V.string(body, "name", min_len=1, max_len=120)
    minimum = V.integer(body, "minimum_offering_amount_cents", minimum=1)
    maximum = V.integer(body, "maximum_offering_amount_cents", minimum=1)
    if maximum < minimum:
        fail("ERR_INVALID_REQUEST",
             "maximum_offering_amount_cents may not be smaller than minimum_offering_amount_cents.")
    deadline, deadline_date = V.date_field(body, "escrow_deadline_date")
    initial_price = V.integer(body, "initial_offering_price_cents", minimum=1)
    window_days = V.integer(body, "rescission_window_days", required=False,
                            default=5, minimum=0)

    row = new_row("offerings", {
        "name": name,
        "minimum_offering_amount_cents": minimum,
        "maximum_offering_amount_cents": maximum,
        "escrow_deadline_date": deadline,
        "_escrow_deadline": deadline_date,
        "initial_offering_price_cents": initial_price,
        "rescission_window_days": window_days,
        "registration_status": "DRAFT",
        "escrow_status": "COLLECTING",
        "repurchase_plan_status": "ACTIVE",
        "repurchase_plan_suspension_reason": None,
        "escrow_balance_cents": 0,
        "gross_proceeds_cents": 0,
        "aggregate_nav_cents": 0,
    })
    return new(row)


@bp.get("/offerings")
def list_offerings():
    require_roles(*READ_ROLES)
    limit, offset = V.pagination()
    registration = V.query_enum("registration_status", REGISTRATION_STATES)
    escrow = V.query_enum("escrow_status", ESCROW_STATES)
    plan = V.query_enum("repurchase_plan_status", PLAN_STATES)
    rows = [r for r in all_rows("offerings")
            if (registration is None or r["registration_status"] == registration)
            and (escrow is None or r["escrow_status"] == escrow)
            and (plan is None or r["repurchase_plan_status"] == plan)]
    return listing(rows, limit, offset)


@bp.get("/offerings/<offering_id>")
def get_offering(offering_id):
    require_roles(*READ_ROLES)
    return single(resolve("offerings", offering_id))


@bp.post("/offerings/<offering_id>/registration")
def drive_registration(offering_id):
    require_roles("ComplianceOfficer")
    body = V.json_body()
    action = V.enum(body, "action",
                    ("DECLARE_EFFECTIVE", "SUSPEND", "REINSTATE", "CLOSE"))
    V.string(body, "reason", required=False, default=None, min_len=0)
    offering = resolve("offerings", offering_id)
    status = offering["registration_status"]

    if action == "DECLARE_EFFECTIVE":
        if status != "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION")
        if not domain.classes_of(offering["id"]):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The offering has no share class attached.")
        if logical_date() > offering["_escrow_deadline"]:
            fail("ERR_ESCROW_DEADLINE_PASSED")
        offering["registration_status"] = "EFFECTIVE"
        touch(offering)
    elif action == "SUSPEND":
        if status != "EFFECTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        offering["registration_status"] = "SUSPENDED"
        touch(offering)
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if offering["escrow_status"] == "FAILED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A failed escrow is terminal; the offering may not be reinstated.")
        offering["registration_status"] = "EFFECTIVE"
        touch(offering)
    else:  # CLOSE
        if status not in ("EFFECTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE_TRANSITION")
        unfinished = [s for s in domain.subscriptions_of_offering(offering["id"])
                      if s["status"] in ("PENDING", "ESCROWED")]
        if unfinished:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The offering still has PENDING or ESCROWED subscriptions.")
        offering["registration_status"] = "CLOSED"
        touch(offering)
        domain.close_active_classes(offering)

    domain.sync_derived()
    return single(offering)


@bp.post("/offerings/<offering_id>/escrow")
def drive_escrow(offering_id):
    require_roles("ComplianceOfficer")
    body = V.json_body()
    action = V.enum(body, "action", ("BREAK", "FAIL"))
    offering = resolve("offerings", offering_id)

    if offering["escrow_status"] != "COLLECTING":
        fail("ERR_INVALID_STATE_TRANSITION")

    if action == "BREAK":
        if offering["registration_status"] != "EFFECTIVE":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The offering's registration status is not EFFECTIVE.")
        if logical_date() > offering["_escrow_deadline"]:
            fail("ERR_ESCROW_DEADLINE_PASSED")
        if offering["escrow_balance_cents"] < offering["minimum_offering_amount_cents"]:
            fail("ERR_MINIMUM_OFFERING_NOT_MET")
        _break_escrow(offering)
    else:  # FAIL
        late = logical_date() > offering["_escrow_deadline"]
        suspended = offering["registration_status"] == "SUSPENDED"
        if not (late or suspended):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Escrow may fail only past the deadline or while registration is SUSPENDED.")
        _fail_escrow(offering)

    domain.sync_derived()
    return single(offering)


def _break_escrow(offering):
    """PRD §3.5 — batch acceptance in ascending created_at order."""
    from store import fmt_instant, logical_now

    offering["escrow_status"] = "BROKEN"
    touch(offering)
    investors = []
    now = fmt_instant(logical_now())
    for sub in domain.subscriptions_of_offering(offering["id"]):
        if sub["status"] != "ESCROWED":
            continue
        cls = DB["share_classes"].get(sub["share_class_id"])
        sub["status"] = "ACCEPTED"
        sub["accepted_at"] = now
        touch(sub)
        if cls is not None:
            domain.mint_lot(sub, cls)
        investor = DB["investors"].get(sub["investor_id"])
        domain.note_lot_minted(investor)
        if investor is not None and investor not in investors:
            investors.append(investor)
    domain.sync_derived()
    for investor in investors:
        domain.reevaluate_suitability(investor)


def _fail_escrow(offering):
    offering["escrow_status"] = "FAILED"
    touch(offering)
    for sub in domain.subscriptions_of_offering(offering["id"]):
        if sub["status"] == "ESCROWED":
            sub["status"] = "REFUNDED"
            sub["rejection_reason"] = "ESCROW_FAILED"
            touch(sub)
    if offering["repurchase_plan_status"] != "TERMINATED":
        offering["repurchase_plan_status"] = "TERMINATED"
        touch(offering)


@bp.post("/offerings/<offering_id>/repurchase-plan")
def drive_repurchase_plan(offering_id):
    require_roles("ComplianceOfficer")
    body = V.json_body()
    action = V.enum(body, "action", ("SUSPEND", "RESUME", "TERMINATE"))
    reason = V.string(body, "reason", required=False, default=None, min_len=0)
    offering = resolve("offerings", offering_id)
    status = offering["repurchase_plan_status"]

    if action == "SUSPEND":
        if status != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        domain.suspend_plan(offering, reason)
    elif action == "RESUME":
        if status != "SUSPENDED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if offering["escrow_status"] != "BROKEN":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The repurchase plan may resume only once escrow has broken.")
        domain.resume_plan(offering)
    else:  # TERMINATE
        if status not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE_TRANSITION")
        domain.terminate_plan(offering)

    domain.sync_derived()
    return single(offering)


# --------------------------------------------------------------------------
# ShareClass
# --------------------------------------------------------------------------

@bp.post("/share-classes")
def create_share_class():
    require_roles("SponsorOperator")
    body = V.json_body()
    offering_id = V.fk(body, "offering_id")
    class_code = V.enum(body, "class_code", CLASS_CODES)
    commission = V.integer(body, "upfront_selling_commission_bps", minimum=0, maximum=1000)
    dealer = V.integer(body, "dealer_manager_fee_bps", minimum=0, maximum=300)
    annual = V.integer(body, "annual_distribution_fee_bps", minimum=0, maximum=1500)
    cap = V.integer(body, "distribution_fee_cap_bps", minimum=0, maximum=2000)
    converts = V.enum(body, "converts_to_class_code", CLASS_CODES,
                      required=False, default=None)

    offering = resolve("offerings", offering_id)

    for sibling in domain.classes_of(offering["id"]):
        if sibling["class_code"] == class_code:
            fail("ERR_DUPLICATE_SHARE_CLASS_CODE")

    row = new_row("share_classes", {
        "offering_id": offering["id"],
        "class_code": class_code,
        "upfront_selling_commission_bps": commission,
        "dealer_manager_fee_bps": dealer,
        "annual_distribution_fee_bps": annual,
        "distribution_fee_cap_bps": cap,
        "converts_to_class_code": converts,
        "status": "ACTIVE",
        "shares_outstanding_e4": 0,
    })
    return new(row)


@bp.get("/share-classes")
def list_share_classes():
    require_roles(*CLASS_READ_ROLES)
    limit, offset = V.pagination()
    offering_id = V.query_string("offering_id")
    class_code = V.query_enum("class_code", CLASS_CODES)
    status = V.query_enum("status", CLASS_STATES)
    rows = [c for c in all_rows("share_classes")
            if (offering_id is None or c["offering_id"] == offering_id)
            and (class_code is None or c["class_code"] == class_code)
            and (status is None or c["status"] == status)]
    return listing(rows, limit, offset)


@bp.get("/share-classes/<share_class_id>")
def get_share_class(share_class_id):
    require_roles(*CLASS_READ_ROLES)
    return single(resolve("share_classes", share_class_id))


@bp.post("/share-classes/<share_class_id>/status")
def drive_share_class(share_class_id):
    require_roles("SponsorOperator")
    body = V.json_body()
    to_status = V.enum(body, "to_status", CLASS_STATES)
    cls = resolve("share_classes", share_class_id)

    if to_status != "CLOSED_TO_NEW" or cls["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION")
    offering = domain.offering_of_class(cls)
    if offering is None or offering["registration_status"] != "EFFECTIVE":
        fail("ERR_OFFERING_NOT_EFFECTIVE")

    cls["status"] = "CLOSED_TO_NEW"
    touch(cls)
    domain.sync_derived()
    return single(cls)
