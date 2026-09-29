"""Certificate holders: registration, the certification lifecycle, licensing."""
import re

from flask import Blueprint, request

import calc
import common as C
import domain as D
import store as S
import validators as V
from common import add_days, clock_now, iso, new_id, now_iso, vol
from errors import ApiError
from response import created, listing, ok
from store import ordered, touch_once

bp = Blueprint("holders", __name__)

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def new_holder_row(legal_name, holder_type, country_code, product_code):
    row = {
        "id": new_id(),
        "legal_name": legal_name,
        "holder_type": holder_type,
        "country_code": country_code,
        "product_code": product_code,
        "certificate_status": "PENDING",
        "certified_at": None,
        "suspension_reason": "NONE",
        "transition_deadline_at": None,
        "compliance_score": 100,
        "open_critical_count": 0,
        "open_major_count": 0,
        "open_minor_count": 0,
        "next_audit_due_at": None,
        "annual_certified_volume_kg": vol(0),
        "label_license_status": "NONE",
        "license_year": None,
        "licensed_volume_kg": None,
        "license_tier": None,
        "license_fee_cents": 0,
        "license_fee_paid_cents": 0,
        "license_fee_settled": False,
    }
    return S.stamp_new(row)


def new_fund_row(holder_id):
    row = {
        "id": new_id(),
        "holder_id": holder_id,
        "fiscal_year": clock_now().year,
        "total_accrued_cents": 0,
        "balance_cents": 0,
        "committed_cents": 0,
        "disbursed_cents": 0,
        "pending_proposal_count": 0,
    }
    return S.stamp_new(row)


@bp.post("/certificate-holders")
def register_holder():
    from auth import authorize
    authorize("CertificationOfficer")
    data = V.body()
    legal_name = V.req_str(data, "legal_name", 200)
    holder_type = V.req_enum(data, "holder_type", C.HOLDER_TYPES)
    country_code = V.req_str(data, "country_code")
    if not _COUNTRY_RE.match(country_code):
        V.fail("country_code must be exactly two uppercase letters")
    product_code = V.req_enum(data, "product_code", C.PRODUCT_CODES)

    holder = new_holder_row(legal_name, holder_type, country_code, product_code)
    S.holders[holder["id"]] = holder
    if holder_type == "PRODUCER_ORG":
        fund = new_fund_row(holder["id"])
        S.funds[fund["id"]] = fund
    return created(holder)


@bp.get("/certificate-holders")
def list_holders():
    from auth import authorize
    authorize(*C.ROLES)
    holder_type = V.enum_filter("holder_type", C.HOLDER_TYPES)
    status = V.enum_filter("certificate_status", C.CERT_STATUSES)
    country_code = V.str_filter("country_code")
    product_code = V.enum_filter("product_code", C.PRODUCT_CODES)
    rows = ordered(list(S.holders.values()))
    if holder_type:
        rows = [r for r in rows if r["holder_type"] == holder_type]
    if status:
        rows = [r for r in rows if r["certificate_status"] == status]
    if country_code:
        rows = [r for r in rows if r["country_code"] == country_code]
    if product_code:
        rows = [r for r in rows if r["product_code"] == product_code]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)


@bp.get("/certificate-holders/<holder_id>")
def read_holder(holder_id):
    from auth import authorize
    authorize(*C.ROLES)
    return ok(S.holder_or_404(holder_id))


@bp.get("/certificate-holders/<holder_id>/traceability-summary")
def read_traceability_summary(holder_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "BrandLicensee",
              "ProducerRepresentative")
    holder = S.holder_or_404(holder_id)
    return ok(D.traceability_summary(holder))


def _invalid_transition(current, action):
    return ApiError("ERR_INVALID_STATE_TRANSITION",
                    "holder in %s cannot %s" % (current, action))


@bp.post("/certificate-holders/<holder_id>/certify")
def certify_holder(holder_id):
    from auth import authorize
    authorize("CertificationOfficer")
    V.body()
    holder = S.holder_or_404(holder_id)
    if holder["certificate_status"] != "PENDING":
        raise _invalid_transition(holder["certificate_status"], "be certified")
    registered = [n for n in S.nodes_of(holder_id) if n["status"] == "REGISTERED"]
    if not registered:
        raise _invalid_transition(holder["certificate_status"],
                                  "be certified without a registered node")

    holder["certificate_status"] = "CERTIFIED"
    holder["certified_at"] = now_iso()
    for node in registered:
        node["status"] = "ACTIVE"
        touch_once(node)
    D.recompute_holder_aggregates(holder)
    touch_once(holder)
    return ok(holder)


@bp.post("/certificate-holders/<holder_id>/suspend")
def suspend_holder_route(holder_id):
    from auth import authorize
    authorize("CertificationOfficer")
    data = V.body()
    reason = V.req_enum(data, "reason", C.SUSPEND_INPUT_REASONS)
    holder = S.holder_or_404(holder_id)
    if holder["certificate_status"] != "CERTIFIED":
        raise _invalid_transition(holder["certificate_status"], "be suspended")
    D.suspend_holder(holder, reason)
    return ok(holder)


@bp.post("/certificate-holders/<holder_id>/reinstate")
def reinstate_holder(holder_id):
    from auth import authorize
    authorize("CertificationOfficer")
    V.body()
    holder = S.holder_or_404(holder_id)
    if holder["certificate_status"] != "SUSPENDED":
        raise _invalid_transition(holder["certificate_status"], "be reinstated")
    if holder["open_critical_count"] != 0:
        raise _invalid_transition(holder["certificate_status"],
                                  "be reinstated with an open critical finding")
    for finding in S.findings_of_holder(holder_id):
        if finding["status"] == "ESCALATED":
            raise _invalid_transition(holder["certificate_status"],
                                      "be reinstated with an escalated finding")

    holder["certificate_status"] = "CERTIFIED"
    holder["suspension_reason"] = "NONE"
    for node in S.nodes_of(holder_id):
        if node["status"] == "SUSPENDED":
            node["status"] = "ACTIVE"
            touch_once(node)
    if holder["license_year"] is not None and holder["label_license_status"] == "SUSPENDED":
        holder["label_license_status"] = "ACTIVE"
    touch_once(holder)
    return ok(holder)


@bp.post("/certificate-holders/<holder_id>/transition")
def transition_holder(holder_id):
    from auth import authorize
    authorize("CertificationOfficer")
    V.body()
    holder = S.holder_or_404(holder_id)
    if holder["certificate_status"] != "SUSPENDED":
        raise _invalid_transition(holder["certificate_status"],
                                  "be granted a sell-down window")
    holder["certificate_status"] = "TRANSITIONING"
    holder["transition_deadline_at"] = iso(
        add_days(clock_now(), C.TRANSITION_WINDOW_DAYS))
    for node in S.nodes_of(holder_id):
        if node["status"] == "SUSPENDED":
            node["status"] = "ACTIVE"
            touch_once(node)
    touch_once(holder)
    return ok(holder)


@bp.post("/certificate-holders/<holder_id>/decertify")
def decertify_holder_route(holder_id):
    from auth import authorize
    authorize("CertificationOfficer")
    data = V.body()
    V.opt_str(data, "reason", 1000)
    holder = S.holder_or_404(holder_id)
    status = holder["certificate_status"]
    if status not in ("PENDING", "SUSPENDED"):
        raise _invalid_transition(status, "be decertified")
    D.decertify_holder(holder, unwind_pipeline=(status != "PENDING"))
    return ok(holder)


@bp.post("/certificate-holders/<holder_id>/label-license")
def issue_label_license(holder_id):
    from auth import authorize
    authorize("CertificationOfficer")
    data = V.body()
    license_year = V.req_int(data, "license_year", minimum=1)
    licensed_volume_kg = V.req_number(data, "licensed_volume_kg", 3, minimum=0)
    holder = S.holder_or_404(holder_id)
    if holder["label_license_status"] == "TERMINATED":
        raise _invalid_transition("TERMINATED", "have its licence re-issued")

    priced = calc.label_license_fee(licensed_volume_kg)
    holder["label_license_status"] = "ACTIVE"
    holder["license_year"] = license_year
    holder["licensed_volume_kg"] = licensed_volume_kg
    holder["license_tier"] = priced["license_tier"]
    holder["license_fee_cents"] = priced["license_fee_cents"]
    holder["license_fee_paid_cents"] = 0
    D.refresh_license_settlement(holder)
    touch_once(holder)
    return ok(holder)


@bp.post("/certificate-holders/<holder_id>/label-license/payments")
def pay_label_license(holder_id):
    from auth import authorize
    user_id, role = authorize("BrandLicensee")
    data = V.body()
    amount_cents = V.req_int(data, "amount_cents", minimum=0)
    holder = S.holder_or_404(holder_id)
    if user_id != holder["id"]:
        raise ApiError("ERR_HOLDER_OWNERSHIP_MISMATCH",
                       "X-User-ID does not own this certificate holder")
    holder["license_fee_paid_cents"] = holder["license_fee_paid_cents"] + amount_cents
    D.refresh_license_settlement(holder)
    touch_once(holder)
    return created(holder)
