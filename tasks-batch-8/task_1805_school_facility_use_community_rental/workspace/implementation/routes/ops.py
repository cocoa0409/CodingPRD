"""Rental requests, permits, payments, work orders, invoices, damage
assessments, seasonal permits."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import response
import services
import util
from middleware import get_auth, require_roles
from validation import (
    body_json, req_string, opt_string, req_int, opt_int, opt_bool, req_enum,
    req_datetime, opt_datetime, opt_number, init_common, touch, get_site,
    get_facility, get_renter, get_request, get_permit, get_wo, get_invoice,
    get_assessment, get_payment, get_series, site_of_facility, policy_for,
    insurance_sufficient, calendar_conflict, permit_blocked_conflict,
    derive_priority_class, post_txn, fee_payments_total,
    open_assessment_exists, recompute_standing, run_waitlist_sweep,
    cancel_permit_record, issue_invoice, void_invoice, now_iso,
)

bp = Blueprint("ops", __name__)

ALL_ROLES = ("DistrictAdmin", "FacilitiesDirector", "SiteCoordinator",
             "CustodialSupervisor", "RenterOrgRep")
DENIAL_REASONS = {"CAPACITY", "CALENDAR_CONFLICT", "INSURANCE", "POLICY",
                  "DISCRETIONARY"}
PAYMENT_KINDS = {"DEPOSIT_CAPTURE", "FEE_PAYMENT"}


# ---------------------------------------------------------------------------
# Rental requests
# ---------------------------------------------------------------------------

def request_out(r):
    return {k: r.get(k) for k in (
        "id", "created_at", "updated_at", "version", "renter_org_id",
        "facility_id", "event_title", "headcount_estimate", "starts_at",
        "ends_at", "request_priority_class", "district_sponsored",
        "request_status", "revision_round", "denial_reason_code",
        "submitted_at", "seasonal_permit_id")}


def _rep_request_scope(org_id, request_id):
    """Auth (tier 2) then left-to-right existence (tier 3) for
    /renters/{org_id}/requests/{request_id} paths."""
    uid, role = get_auth()
    if role != "RenterOrgRep" or uid != org_id:
        raise errors.forbidden()
    get_renter(org_id)
    req = get_request(request_id)
    if req["renter_org_id"] != org_id:
        raise errors.not_found("Request does not belong to the path organization")
    return uid, req


def _check_temporal_window(starts_at, ends_at):
    if ends_at <= starts_at:
        raise errors.invalid_time_window("ends_at must be strictly after starts_at")
    if ends_at - starts_at > timedelta(hours=12):
        raise errors.invalid_time_window("duration must be at most 12 hours")


@bp.post("/district/renters/<org_id>/requests")
def create_request(org_id):
    uid, role = get_auth()
    if role != "RenterOrgRep" or uid != org_id:
        raise errors.forbidden()
    renter = get_renter(org_id)
    body = body_json()
    facility_id = req_string(body, "facility_id")
    event_title = req_string(body, "event_title")
    headcount = req_int(body, "headcount_estimate")
    starts_at = req_datetime(body, "starts_at")
    ends_at = req_datetime(body, "ends_at")
    sponsored = opt_bool(body, "district_sponsored", False)
    if headcount < 1:
        raise errors.invalid_request("headcount_estimate must be >= 1")
    fac = get_facility(facility_id)
    site = site_of_facility(fac)
    # Temporal sanity (tier 6).
    _check_temporal_window(starts_at, ends_at)
    # Availability and schedule conflict (tier 7): site ACTIVE, facility
    # AVAILABLE, no calendar collision, and no ISSUED/ACTIVE permit whose
    # blocked interval collides with the requested interval.
    if site is None or site["site_status"] != "ACTIVE":
        raise errors.site_closed()
    if fac["facility_status"] != "AVAILABLE":
        raise errors.facility_not_available()
    if calendar_conflict(fac, starts_at, ends_at):
        raise errors.schedule_conflict()
    if permit_blocked_conflict(fac["id"], starts_at, ends_at):
        raise errors.schedule_conflict()
    # Referential integrity (tier 8): a covering ACTIVE policy must exist for
    # the renter's rate class, the facility's tier, and the event start date.
    if policy_for(renter["rate_class"], fac["facility_tier"], starts_at) is None:
        raise errors.reference_invalid(
            "No ACTIVE RateClassPolicy covers starts_at for (rate_class, facility_tier)")
    rec = init_common()
    rec.update({
        "renter_org_id": org_id,
        "facility_id": facility_id,
        "event_title": event_title,
        "headcount_estimate": headcount,
        "starts_at": util.iso_z(starts_at),
        "ends_at": util.iso_z(ends_at),
        "request_priority_class": None,
        "district_sponsored": sponsored,
        "request_status": "DRAFT",
        "revision_round": 0,
        "denial_reason_code": None,
        "submitted_at": None,
        "seasonal_permit_id": None,
    })
    db.requests[rec["id"]] = rec
    return response.success(request_out(rec), 201)


@bp.get("/district/requests/<request_id>")
def get_request_ep(request_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    req = get_request(request_id)
    if role == "RenterOrgRep" and uid != req["renter_org_id"]:
        raise errors.forbidden()
    return response.success(request_out(req))


@bp.get("/district/requests")
def list_requests():
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator")
    rows = list(db.requests.values())
    for param in ("request_status", "facility_id", "renter_org_id"):
        v = request.args.get(param)
        if v:
            rows = [r for r in rows if r.get(param) == v]
    rows.sort(key=lambda r: r["created_at"])
    return response.paginate([request_out(r) for r in rows])


@bp.get("/district/renters/<org_id>/requests")
def list_org_requests(org_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    if role == "RenterOrgRep" and uid != org_id:
        raise errors.forbidden()
    get_renter(org_id)
    status = request.args.get("request_status")
    rows = [r for r in db.requests.values() if r["renter_org_id"] == org_id]
    if status:
        rows = [r for r in rows if r["request_status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    return response.paginate([request_out(r) for r in rows])


def _submit_gates(req, renter, fac):
    """Shared gate set for submit/resubmit, in pipeline priority order:
    safety (capacity, insurance) -> temporal -> availability/conflict ->
    standing."""
    if req["headcount_estimate"] > fac["capacity"]:
        raise errors.capacity_exceeded()
    starts_at = util.parse_iso(req["starts_at"])
    ends_at = util.parse_iso(req["ends_at"])
    # Insurance hard gate (tier 5; §3.3) — runs at submission and resubmission.
    if not insurance_sufficient(renter, req["headcount_estimate"], ends_at):
        raise errors.insurance_insufficient()
    _check_temporal_window(starts_at, ends_at)
    if starts_at <= util.clock_now():
        raise errors.invalid_time_window("starts_at must lie strictly after the logical clock now")
    site = site_of_facility(fac)
    if site is None or site["site_status"] != "ACTIVE":
        raise errors.site_closed()
    if fac["facility_status"] != "AVAILABLE":
        raise errors.facility_not_available()
    if calendar_conflict(fac, starts_at, ends_at):
        raise errors.schedule_conflict()
    if permit_blocked_conflict(fac["id"], starts_at, ends_at):
        raise errors.schedule_conflict()
    if renter["org_standing"] != "GOOD_STANDING":
        raise errors.renter_not_good_standing()


@bp.post("/district/renters/<org_id>/requests/<request_id>/submit")
def submit_request(org_id, request_id):
    uid, req = _rep_request_scope(org_id, request_id)
    if req["request_status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT request can be submitted")
    renter = db.renters[org_id]
    fac = get_facility(req["facility_id"])
    _submit_gates(req, renter, fac)
    req["request_status"] = "SUBMITTED"
    if req.get("submitted_at") is None:
        req["submitted_at"] = now_iso()
    req["request_priority_class"] = derive_priority_class(
        renter, req.get("district_sponsored", False))
    touch(req)
    return response.success(request_out(req))


@bp.post("/district/renters/<org_id>/requests/<request_id>/resubmit")
def resubmit_request(org_id, request_id):
    uid, req = _rep_request_scope(org_id, request_id)
    body = body_json(required=False)
    if req["request_status"] != "REVISION_REQUESTED":
        raise errors.invalid_state(
            "Only a REVISION_REQUESTED request can be resubmitted")
    headcount = opt_int(body, "headcount_estimate")
    starts_at = opt_datetime(body, "starts_at")
    ends_at = opt_datetime(body, "ends_at")
    event_title = opt_string(body, "event_title")
    if headcount is not None:
        if headcount < 1:
            raise errors.invalid_request("headcount_estimate must be >= 1")
        req["headcount_estimate"] = headcount
    if starts_at is not None:
        req["starts_at"] = util.iso_z(starts_at)
    if ends_at is not None:
        req["ends_at"] = util.iso_z(ends_at)
    if event_title is not None:
        req["event_title"] = event_title
    renter = db.renters[org_id]
    fac = get_facility(req["facility_id"])
    _submit_gates(req, renter, fac)
    req["request_status"] = "RESUBMITTED"
    req["revision_round"] += 1
    # submitted_at is NOT refreshed — original seniority is preserved.
    req["request_priority_class"] = derive_priority_class(
        renter, req.get("district_sponsored", False))
    touch(req)
    return response.success(request_out(req))


@bp.post("/district/renters/<org_id>/requests/<request_id>/withdraw")
def withdraw_request(org_id, request_id):
    uid, req = _rep_request_scope(org_id, request_id)
    if req["request_status"] not in (
            "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "WAITLISTED"):
        raise errors.invalid_state(
            "Only DRAFT, SUBMITTED, REVISION_REQUESTED, or WAITLISTED requests can be withdrawn")
    req["request_status"] = "WITHDRAWN"
    touch(req)
    return response.success(request_out(req))


@bp.post("/district/requests/<request_id>/begin_review")
def begin_review(request_id):
    require_roles("SiteCoordinator")
    req = get_request(request_id)
    if req["request_status"] not in ("SUBMITTED", "RESUBMITTED"):
        raise errors.invalid_state(
            "Only SUBMITTED or RESUBMITTED requests can enter review")
    fac = get_facility(req["facility_id"])
    if fac["facility_status"] != "AVAILABLE":
        raise errors.facility_not_available()
    req["request_status"] = "UNDER_REVIEW"
    touch(req)
    return response.success(request_out(req))


@bp.post("/district/requests/<request_id>/request_revision")
def request_revision(request_id):
    require_roles("SiteCoordinator")
    req = get_request(request_id)
    body = body_json()
    req_string(body, "revision_note")
    if req["request_status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Only UNDER_REVIEW requests can be sent back for revision")
    if req["revision_round"] >= 3:
        raise errors.revision_limit()
    req["request_status"] = "REVISION_REQUESTED"
    touch(req)
    return response.success(request_out(req))


@bp.post("/district/requests/<request_id>/approve")
def approve_request_ep(request_id):
    require_roles("FacilitiesDirector")
    req = get_request(request_id)
    body = body_json()
    expected = body.get("expected_request_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.invalid_request("expected_request_version is required")
    if req["request_status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Only UNDER_REVIEW requests can be approved")
    if expected != req["version"]:
        raise errors.stale_version(
            "expected_request_version does not match the request's current version")
    renter = db.renters[req["renter_org_id"]]
    fac = get_facility(req["facility_id"])
    site = site_of_facility(fac)
    starts_at = util.parse_iso(req["starts_at"])
    ends_at = util.parse_iso(req["ends_at"])
    # Safety gates: capacity, insurance (INTERNAL exempt).
    if req["headcount_estimate"] > fac["capacity"]:
        raise errors.capacity_exceeded()
    if not insurance_sufficient(renter, req["headcount_estimate"], ends_at):
        raise errors.insurance_insufficient()
    # Availability and schedule conflict.
    if site is None or site["site_status"] != "ACTIVE":
        raise errors.site_closed()
    if fac["facility_status"] != "AVAILABLE":
        raise errors.facility_not_available()
    if calendar_conflict(fac, starts_at, ends_at):
        raise errors.schedule_conflict()
    blocked_start = starts_at - timedelta(minutes=fac["setup_buffer_minutes"])
    blocked_end = ends_at + timedelta(minutes=fac["teardown_buffer_minutes"])
    if permit_blocked_conflict(fac["id"], blocked_start, blocked_end):
        raise errors.schedule_conflict()
    # Referential: exactly one ACTIVE policy covering the event start.
    if policy_for(renter["rate_class"], fac["facility_tier"], starts_at) is None:
        raise errors.reference_invalid(
            "No ACTIVE RateClassPolicy covers starts_at for (rate_class, facility_tier)")
    # Fiscal gate: standing.
    if renter["org_standing"] != "GOOD_STANDING":
        raise errors.renter_not_good_standing()
    permit = services.approve_request(req)
    return response.success(permit_out(permit))


@bp.post("/district/requests/<request_id>/deny")
def deny_request(request_id):
    require_roles("FacilitiesDirector")
    req = get_request(request_id)
    body = body_json()
    code = req_enum(body, "denial_reason_code", DENIAL_REASONS)
    if req["request_status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Only UNDER_REVIEW requests can be denied")
    req["request_status"] = "DENIED"
    req["denial_reason_code"] = code
    touch(req)
    return response.success(request_out(req))


@bp.post("/district/requests/<request_id>/waitlist")
def waitlist_request(request_id):
    require_roles("FacilitiesDirector")
    req = get_request(request_id)
    body = body_json()
    req_string(body, "hold_reason")
    if req["request_status"] not in ("SUBMITTED", "UNDER_REVIEW", "RESUBMITTED"):
        raise errors.invalid_state(
            "Only SUBMITTED, UNDER_REVIEW, or RESUBMITTED requests can be waitlisted")
    req["request_status"] = "WAITLISTED"
    touch(req)
    return response.success(request_out(req))


@bp.get("/district/requests/<request_id>/permits")
def list_request_permits(request_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    req = get_request(request_id)
    if role == "RenterOrgRep" and uid != req["renter_org_id"]:
        raise errors.forbidden()
    rows = [p for p in db.permits.values() if p["rental_request_id"] == request_id]
    rows.sort(key=lambda p: p["created_at"])
    return response.paginate([permit_out(p) for p in rows])


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------

def permit_out(p):
    return {k: p.get(k) for k in (
        "id", "created_at", "updated_at", "version", "rental_request_id",
        "renter_org_id", "facility_id", "occupancy_start", "occupancy_end",
        "blocked_start", "blocked_end", "lifecycle_status", "financial_status",
        "deposit_required_cents", "deposit_held_cents", "seasonal_permit_id",
        "superseded_by_permit_id")}


@bp.get("/district/permits/<permit_id>")
def get_permit_ep(permit_id):
    uid, role = get_auth()
    if role not in ALL_ROLES:
        raise errors.forbidden()
    permit = get_permit(permit_id)
    if role == "RenterOrgRep" and uid != permit["renter_org_id"]:
        raise errors.forbidden()
    return response.success(permit_out(permit))


@bp.get("/district/permits")
def list_permits():
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                  "CustodialSupervisor")
    rows = list(db.permits.values())
    for param in ("facility_id", "renter_org_id", "lifecycle_status",
                  "financial_status", "seasonal_permit_id",
                  "rental_request_id", "superseded_by_permit_id"):
        v = request.args.get(param)
        if v:
            rows = [p for p in rows if (p.get(param) or "") == v]
    rows.sort(key=lambda p: p["created_at"])
    return response.paginate([permit_out(p) for p in rows])


@bp.post("/district/permits/<permit_id>/cancel")
def cancel_permit(permit_id):
    uid, role = get_auth()
    if role not in ("RenterOrgRep", "FacilitiesDirector"):
        raise errors.forbidden()
    permit = get_permit(permit_id)
    if role == "RenterOrgRep" and uid != permit["renter_org_id"]:
        raise errors.forbidden()
    body = body_json()
    req_string(body, "cancellation_reason")
    refund_destination = opt_string(body, "refund_destination")
    if refund_destination is not None and refund_destination not in ("CREDIT", "CARD"):
        raise errors.invalid_request("refund_destination must be CREDIT or CARD")
    if permit["lifecycle_status"] != "ISSUED":
        raise errors.permit_not_cancellable()
    permit["lifecycle_status"] = "CANCELLED"
    cancel_permit_record(permit, "STANDARD", refund_destination)
    return response.success(permit_out(permit))


@bp.post("/district/permits/<permit_id>/complete")
def complete_permit(permit_id):
    require_roles("SiteCoordinator")
    permit = get_permit(permit_id)
    if permit["lifecycle_status"] != "ACTIVE":
        raise errors.invalid_state("Only ACTIVE permits can be completed")
    if util.clock_now() < util.parse_iso(permit["occupancy_end"]):
        raise errors.invalid_state(
            "Cannot complete a permit before the logical clock passes occupancy_end")
    renter = db.renters[permit["renter_org_id"]]
    fac = db.facilities[permit["facility_id"]]
    occ_start = util.parse_iso(permit["occupancy_start"])
    occ_end = util.parse_iso(permit["occupancy_end"])
    policy = policy_for(renter["rate_class"], fac["facility_tier"], occ_start)
    if policy is None:
        raise errors.reference_invalid(
            "No ACTIVE RateClassPolicy covers the occupancy start")

    permit["lifecycle_status"] = "COMPLETED"
    touch(permit)

    # PROVISIONAL superseded by FINAL.
    prov = services.provisional_invoice(permit["id"])
    if prov is not None:
        void_invoice(prov)

    # FINAL invoice from actuals: verified actual hours when the work order
    # has already been verified, otherwise the estimated span.
    wo = services.permit_work_order(permit["id"])
    hours = None
    if wo is not None:
        hours = wo["actual_hours"] if wo["actual_hours"] is not None else wo["estimated_hours"]
    rental_c, staffing_c, after_c, discount_c, total_c = \
        services.build_invoice_amounts(policy, fac, occ_start, occ_end, wo, hours)
    final = issue_invoice(permit, renter, "FINAL",
                          rental_c, staffing_c, after_c, discount_c, total_c)

    if permit["financial_status"] != "INVOICED":
        permit["financial_status"] = "INVOICED"
        touch(permit)

    # A zero-total FINAL settles automatically at issuance (INTERNAL bookings).
    if total_c == 0:
        final["invoice_status"] = "PAID"
        touch(final)
        if open_assessment_exists(permit["id"]):
            permit["financial_status"] = "FORFEIT_PENDING"
        else:
            permit["financial_status"] = "SETTLED"
            if permit["deposit_held_cents"] > 0:
                post_txn(permit["id"], None, "DEPOSIT_REFUND",
                         permit["deposit_held_cents"])
                permit["deposit_held_cents"] = 0
        touch(permit)
        recompute_standing(renter)
    return response.success(permit_out(permit))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

def payment_out(p):
    return {k: p.get(k) for k in (
        "id", "created_at", "permit_id", "invoice_id", "txn_kind",
        "amount_cents", "posted_at", "idempotency_key")}


@bp.post("/district/permits/<permit_id>/payments")
def post_payment(permit_id):
    uid, role = get_auth()
    if role != "RenterOrgRep":
        raise errors.forbidden()
    permit = get_permit(permit_id)
    if uid != permit["renter_org_id"]:
        raise errors.forbidden()
    body = body_json()
    txn_kind = req_enum(body, "txn_kind", PAYMENT_KINDS)
    amount = req_int(body, "amount_cents")
    key = req_string(body, "idempotency_key")
    invoice_id = opt_string(body, "invoice_id")
    if amount <= 0:
        raise errors.invalid_request("amount_cents must be positive")
    if txn_kind == "FEE_PAYMENT" and not invoice_id:
        raise errors.invalid_request("invoice_id is required for FEE_PAYMENT")
    if txn_kind == "DEPOSIT_CAPTURE" and invoice_id is not None:
        raise errors.invalid_request("invoice_id must be null for DEPOSIT_CAPTURE")

    # Idempotency: identical payload replays the original row; a different
    # payload conflicts.
    signature = (permit_id, txn_kind, amount, invoice_id)
    if key in db.idempotency:
        prior_sig, prior_id = db.idempotency[key]
        if prior_sig != signature:
            raise errors.idempotency_conflict()
        return response.success(payment_out(db.payments[prior_id]), 201)

    renter = db.renters[permit["renter_org_id"]]
    if renter["org_standing"] != "GOOD_STANDING":
        raise errors.renter_not_good_standing()

    if txn_kind == "DEPOSIT_CAPTURE":
        if permit["lifecycle_status"] != "ISSUED" or \
                permit["financial_status"] != "DEPOSIT_PENDING":
            raise errors.invalid_state(
                "Deposit capture requires an ISSUED permit in DEPOSIT_PENDING")
        if amount != permit["deposit_required_cents"]:
            raise errors.payment_amount_mismatch()
        rec = post_txn(permit["id"], None, "DEPOSIT_CAPTURE", amount, key)
        permit["deposit_held_cents"] = amount
        permit["financial_status"] = "SECURED"
        touch(permit)
    else:  # FEE_PAYMENT
        invoice = db.invoices.get(invoice_id)
        if invoice is None or invoice["permit_id"] != permit["id"]:
            raise errors.reference_invalid(
                "invoice_id does not reference an invoice of this permit")
        # A FEE_PAYMENT may not exceed the invoice's remaining balance — a PAID
        # invoice has remaining balance zero, so any positive amount overpays.
        remaining = invoice["total_cents"] - invoice["amount_paid_cents"]
        if amount > remaining:
            raise errors.overpayment()
        if invoice["invoice_status"] != "ISSUED":
            raise errors.invalid_state("Fee payment requires an ISSUED invoice")
        rec = post_txn(permit["id"], invoice_id, "FEE_PAYMENT", amount, key)
        invoice["amount_paid_cents"] += amount
        if invoice["invoice_kind"] in ("FINAL", "DAMAGE"):
            renter["outstanding_balance_cents"] = max(
                0, renter["outstanding_balance_cents"] - amount)
            touch(renter)
        if invoice["amount_paid_cents"] == invoice["total_cents"]:
            invoice["invoice_status"] = "PAID"
            if invoice["invoice_kind"] == "FINAL":
                if open_assessment_exists(permit["id"]):
                    permit["financial_status"] = "FORFEIT_PENDING"
                    touch(permit)
                elif permit["financial_status"] == "INVOICED":
                    # Settling the FINAL releases the deposit.
                    permit["financial_status"] = "SETTLED"
                    if permit["deposit_held_cents"] > 0:
                        post_txn(permit["id"], None, "DEPOSIT_REFUND",
                                 permit["deposit_held_cents"])
                        permit["deposit_held_cents"] = 0
                    touch(permit)
        touch(invoice)
        recompute_standing(renter)
    db.idempotency[key] = (signature, rec["id"])
    return response.success(payment_out(rec), 201)


@bp.get("/district/payments/<payment_id>")
def get_payment_ep(payment_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    payment = get_payment(payment_id)
    if role == "RenterOrgRep":
        permit = db.permits.get(payment["permit_id"])
        if permit is None or uid != permit["renter_org_id"]:
            raise errors.forbidden()
    return response.success(payment_out(payment))


@bp.get("/district/payments")
def list_payments():
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator")
    rows = list(db.payments.values())
    for param in ("permit_id", "invoice_id", "txn_kind"):
        v = request.args.get(param)
        if v:
            rows = [p for p in rows if (p.get(param) or "") == v]
    rows.sort(key=lambda p: p["created_at"])
    return response.paginate([payment_out(p) for p in rows])


@bp.get("/district/permits/<permit_id>/payments")
def list_permit_payments(permit_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    permit = get_permit(permit_id)
    if role == "RenterOrgRep" and uid != permit["renter_org_id"]:
        raise errors.forbidden()
    kind = request.args.get("txn_kind")
    rows = [p for p in db.payments.values() if p["permit_id"] == permit_id]
    if kind:
        rows = [p for p in rows if p["txn_kind"] == kind]
    rows.sort(key=lambda p: p["created_at"])
    return response.paginate([payment_out(p) for p in rows])


# ---------------------------------------------------------------------------
# Custodial work orders
# ---------------------------------------------------------------------------

def wo_out(w):
    return {k: w.get(k) for k in (
        "id", "created_at", "updated_at", "version", "permit_id",
        "facility_id", "scheduled_start", "scheduled_end", "estimated_hours",
        "actual_hours", "after_hours_flag", "weekend_flag", "wo_status")}


@bp.get("/district/work_orders/<wo_id>")
def get_wo_ep(wo_id):
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                  "CustodialSupervisor")
    return response.success(wo_out(get_wo(wo_id)))


@bp.get("/district/work_orders")
def list_wos():
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                  "CustodialSupervisor")
    rows = list(db.work_orders.values())
    for param in ("wo_status", "facility_id", "permit_id"):
        v = request.args.get(param)
        if v:
            rows = [w for w in rows if (w.get(param) or "") == v]
    rows.sort(key=lambda w: w["created_at"])
    return response.paginate([wo_out(w) for w in rows])


@bp.get("/district/permits/<permit_id>/work_orders")
def list_permit_wos(permit_id):
    uid, role = get_auth()
    if role not in ALL_ROLES:
        raise errors.forbidden()
    permit = get_permit(permit_id)
    if role == "RenterOrgRep" and uid != permit["renter_org_id"]:
        raise errors.forbidden()
    rows = [w for w in db.work_orders.values() if w["permit_id"] == permit_id]
    rows.sort(key=lambda w: w["created_at"])
    return response.paginate([wo_out(w) for w in rows])


@bp.post("/district/work_orders/<wo_id>/verify")
def verify_wo(wo_id):
    require_roles("CustodialSupervisor")
    wo = get_wo(wo_id)
    body = body_json()
    actual = opt_number(body, "actual_hours")
    if actual is None:
        raise errors.invalid_request("actual_hours is required")
    if actual <= 0:
        raise errors.invalid_request("actual_hours must be > 0")
    permit = get_permit(wo["permit_id"])
    if permit["lifecycle_status"] != "COMPLETED":
        raise errors.invalid_state(
            "Work order verification requires the permit to be COMPLETED")
    if wo["wo_status"] != "IN_PROGRESS":
        raise errors.invalid_state("Only IN_PROGRESS work orders can be verified")
    wo["actual_hours"] = round(float(actual), 2)
    wo["wo_status"] = "VERIFIED"
    touch(wo)

    # Recompute the FINAL invoice's staffing/after-hours from actual hours.
    final = services.final_invoice(permit["id"])
    if final is not None:
        renter = db.renters[permit["renter_org_id"]]
        fac = db.facilities[permit["facility_id"]]
        policy = policy_for(renter["rate_class"], fac["facility_tier"],
                            util.parse_iso(permit["occupancy_start"]))
        if policy is not None:
            old_total = final["total_cents"]
            rental_c, staffing_c, after_c, discount_c, total_c = \
                services.build_invoice_amounts(
                    policy, fac, util.parse_iso(permit["occupancy_start"]),
                    util.parse_iso(permit["occupancy_end"]), wo,
                    wo["actual_hours"])
            final["rental_fee_cents"] = rental_c
            final["staffing_charge_cents"] = staffing_c
            final["after_hours_charge_cents"] = after_c
            final["discount_cents"] = discount_c
            final["total_cents"] = total_c
            touch(final)
            if final["invoice_status"] == "ISSUED" and old_total != total_c:
                new_balance = max(
                    0, renter["outstanding_balance_cents"] - old_total + total_c)
                if renter["outstanding_balance_cents"] == 0 and new_balance > 0:
                    renter["_balance_since"] = now_iso()
                renter["outstanding_balance_cents"] = new_balance
                touch(renter)
                recompute_standing(renter)
    return response.success(wo_out(wo))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def invoice_out(i):
    return {k: i.get(k) for k in (
        "id", "created_at", "updated_at", "version", "permit_id",
        "renter_org_id", "invoice_kind", "rental_fee_cents",
        "staffing_charge_cents", "after_hours_charge_cents", "discount_cents",
        "total_cents", "amount_paid_cents", "invoice_status")}


@bp.get("/district/invoices/<invoice_id>")
def get_invoice_ep(invoice_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    invoice = get_invoice(invoice_id)
    if role == "RenterOrgRep" and uid != invoice["renter_org_id"]:
        raise errors.forbidden()
    return response.success(invoice_out(invoice))


@bp.get("/district/invoices")
def list_invoices():
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator")
    rows = list(db.invoices.values())
    for param in ("renter_org_id", "invoice_kind", "invoice_status", "permit_id"):
        v = request.args.get(param)
        if v:
            rows = [i for i in rows if (i.get(param) or "") == v]
    rows.sort(key=lambda i: i["created_at"])
    return response.paginate([invoice_out(i) for i in rows])


@bp.get("/district/permits/<permit_id>/invoices")
def list_permit_invoices(permit_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    permit = get_permit(permit_id)
    if role == "RenterOrgRep" and uid != permit["renter_org_id"]:
        raise errors.forbidden()
    rows = [i for i in db.invoices.values() if i["permit_id"] == permit_id]
    for param in ("invoice_kind", "invoice_status"):
        v = request.args.get(param)
        if v:
            rows = [i for i in rows if i.get(param) == v]
    rows.sort(key=lambda i: i["created_at"])
    return response.paginate([invoice_out(i) for i in rows])


# ---------------------------------------------------------------------------
# Damage assessments
# ---------------------------------------------------------------------------

def assessment_out(a):
    return {k: a.get(k) for k in (
        "id", "created_at", "updated_at", "version", "permit_id",
        "facility_id", "recorded_by_user_id", "line_items",
        "total_claimed_cents", "adjudicated_amount_cents", "assessment_status")}


@bp.post("/district/permits/<permit_id>/damage_assessments")
def create_assessment(permit_id):
    uid, role = require_roles("SiteCoordinator")
    permit = get_permit(permit_id)
    body = body_json()
    items = body.get("line_items")
    if items is None:
        raise errors.invalid_request("line_items is required")
    if not isinstance(items, list):
        raise errors.invalid_request("line_items must be an array")
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("description"), str):
            raise errors.invalid_request(
                "each line item needs a description string")
        cost = it.get("repair_cost_cents")
        if not isinstance(cost, int) or isinstance(cost, bool):
            raise errors.invalid_request(
                "each line item needs an integer repair_cost_cents")
    if permit["lifecycle_status"] != "COMPLETED":
        raise errors.invalid_state(
            "Damage intake requires a COMPLETED permit")
    if len(items) == 0 or any(it["repair_cost_cents"] <= 0 for it in items):
        raise errors.empty_damage_claim()
    total = sum(it["repair_cost_cents"] for it in items)
    rec = init_common()
    rec.update({
        "permit_id": permit["id"],
        "facility_id": permit["facility_id"],
        "recorded_by_user_id": uid,
        "line_items": [{"description": it["description"],
                        "repair_cost_cents": it["repair_cost_cents"]}
                       for it in items],
        "total_claimed_cents": total,
        "adjudicated_amount_cents": None,
        "assessment_status": "OPEN",
    })
    db.damage_assessments[rec["id"]] = rec
    # Intake freezes the deposit release.
    if permit["financial_status"] in ("SECURED", "INVOICED"):
        permit["financial_status"] = "FORFEIT_PENDING"
        touch(permit)
    return response.success(assessment_out(rec), 201)


@bp.get("/district/damage_assessments")
def list_assessments():
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator")
    rows = list(db.damage_assessments.values())
    for param in ("permit_id", "facility_id", "assessment_status"):
        v = request.args.get(param)
        if v:
            rows = [a for a in rows if (a.get(param) or "") == v]
    rows.sort(key=lambda a: a["created_at"])
    return response.paginate([assessment_out(a) for a in rows])


@bp.get("/district/damage_assessments/<assessment_id>")
def get_assessment_ep(assessment_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    a = get_assessment(assessment_id)
    if role == "RenterOrgRep":
        permit = db.permits.get(a["permit_id"])
        if permit is None or uid != permit["renter_org_id"]:
            raise errors.forbidden()
    return response.success(assessment_out(a))


@bp.get("/district/permits/<permit_id>/damage_assessments")
def list_permit_assessments(permit_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    permit = get_permit(permit_id)
    if role == "RenterOrgRep" and uid != permit["renter_org_id"]:
        raise errors.forbidden()
    status = request.args.get("assessment_status")
    rows = [a for a in db.damage_assessments.values()
            if a["permit_id"] == permit_id]
    if status:
        rows = [a for a in rows if a["assessment_status"] == status]
    rows.sort(key=lambda a: a["created_at"])
    return response.paginate([assessment_out(a) for a in rows])


@bp.post("/district/damage_assessments/<assessment_id>/adjudicate")
def adjudicate(assessment_id):
    uid, role = require_roles("FacilitiesDirector")
    a = get_assessment(assessment_id)
    body = body_json()
    amount = req_int(body, "adjudicated_amount_cents")
    if amount < 0:
        raise errors.invalid_request("adjudicated_amount_cents must be >= 0")
    if uid == a["recorded_by_user_id"]:
        raise errors.segregation()
    if a["assessment_status"] != "OPEN":
        raise errors.invalid_state("Only OPEN assessments can be adjudicated")
    if amount > a["total_claimed_cents"]:
        raise errors.adjudication_exceeds()
    a["adjudicated_amount_cents"] = amount
    a["assessment_status"] = "ADJUDICATED"
    a["_adjudicated_at"] = now_iso()
    touch(a)
    return response.success(assessment_out(a))


@bp.post("/district/damage_assessments/<assessment_id>/accept")
def accept_assessment(assessment_id):
    uid, role = require_roles("RenterOrgRep")
    a = get_assessment(assessment_id)
    permit = db.permits.get(a["permit_id"])
    if permit is None or uid != permit["renter_org_id"]:
        raise errors.forbidden()
    if a["assessment_status"] != "ADJUDICATED":
        raise errors.invalid_state("Only ADJUDICATED assessments can be accepted")
    a["assessment_status"] = "FINAL"
    touch(a)
    services.finalize_assessment(a)
    return response.success(assessment_out(a))


@bp.post("/district/damage_assessments/<assessment_id>/appeal")
def appeal_assessment(assessment_id):
    uid, role = require_roles("RenterOrgRep")
    a = get_assessment(assessment_id)
    permit = db.permits.get(a["permit_id"])
    if permit is None or uid != permit["renter_org_id"]:
        raise errors.forbidden()
    body = body_json()
    req_string(body, "appeal_reason")
    if a["assessment_status"] != "ADJUDICATED":
        raise errors.invalid_state("Only ADJUDICATED assessments can be appealed")
    adjudicated_at = util.parse_iso(a["_adjudicated_at"]) if a.get("_adjudicated_at") \
        else util.parse_iso(a["updated_at"])
    if util.clock_now() > adjudicated_at + timedelta(days=14):
        raise errors.appeal_window_elapsed()
    a["assessment_status"] = "APPEALED"
    touch(a)
    return response.success(assessment_out(a))


@bp.post("/district/damage_assessments/<assessment_id>/resolve_appeal")
def resolve_appeal(assessment_id):
    uid, role = require_roles("FacilitiesDirector")
    a = get_assessment(assessment_id)
    body = body_json()
    final_amount = req_int(body, "final_amount_cents")
    if final_amount < 0:
        raise errors.invalid_request("final_amount_cents must be >= 0")
    if uid == a["recorded_by_user_id"]:
        raise errors.segregation()
    if a["assessment_status"] != "APPEALED":
        raise errors.invalid_state("Only APPEALED assessments can be resolved")
    if final_amount > a["total_claimed_cents"]:
        raise errors.adjudication_exceeds()
    a["adjudicated_amount_cents"] = final_amount
    a["assessment_status"] = "FINAL"
    touch(a)
    services.finalize_assessment(a)
    return response.success(assessment_out(a))


# ---------------------------------------------------------------------------
# Seasonal permits
# ---------------------------------------------------------------------------

def series_out(s):
    return {k: s.get(k) for k in (
        "id", "created_at", "updated_at", "version", "renter_org_id",
        "facility_id", "series_name", "recurrence_rule", "season_start",
        "season_end", "renewed_from_id", "seniority_key", "series_status")}


@bp.post("/district/seasonal_permits")
def create_series():
    uid, role = get_auth()
    if role not in ("RenterOrgRep", "FacilitiesDirector"):
        raise errors.forbidden()
    body = body_json()
    renter_org_id = req_string(body, "renter_org_id")
    facility_id = req_string(body, "facility_id")
    series_name = req_string(body, "series_name")
    recurrence_rule = req_string(body, "recurrence_rule")
    season_start = req_datetime(body, "season_start")
    season_end = req_datetime(body, "season_end")
    renewed_from_id = opt_string(body, "renewed_from_id")
    expected_series_version = body.get("expected_series_version")
    if role == "RenterOrgRep" and uid != renter_org_id:
        raise errors.forbidden()
    renter = get_renter(renter_org_id)
    fac = get_facility(facility_id)
    site = site_of_facility(fac)
    if util.parse_recurrence(recurrence_rule) is None:
        raise errors.invalid_request(
            "recurrence_rule must look like 'WEEKLY:SAT:18:00-21:00'")
    if season_end < season_start:
        raise errors.invalid_time_window("season_end must be >= season_start")
    if season_end - season_start > timedelta(days=120):
        raise errors.invalid_time_window("season span must be <= 120 days")
    if site is None or site["site_status"] != "ACTIVE":
        raise errors.site_closed()
    if fac["facility_status"] != "AVAILABLE":
        raise errors.facility_not_available()
    if renter["org_standing"] != "GOOD_STANDING":
        raise errors.renter_not_good_standing()

    # Renewal: OCC on the prior series first (§2.8's canonical stale case is a
    # second renewal after another writer renewed the same series), then the
    # renewal-linkage rule (same renter, renewable status, not already renewed).
    prior = None
    if renewed_from_id is not None:
        prior = db.seasonal_permits.get(renewed_from_id)
        if prior is None:
            raise errors.renewal_not_renewable()
        if not isinstance(expected_series_version, int) or \
                isinstance(expected_series_version, bool):
            raise errors.invalid_request(
                "expected_series_version is required when renewed_from_id is set")
        if expected_series_version != prior["version"]:
            raise errors.stale_version(
                "expected_series_version does not match the prior series' version")
        if prior["renter_org_id"] != renter_org_id or \
                prior["series_status"] not in ("COMPLETED", "ACTIVE") or \
                any(s.get("renewed_from_id") == renewed_from_id
                    for s in db.seasonal_permits.values()):
            raise errors.renewal_not_renewable()

    rec = init_common()
    rec.update({
        "renter_org_id": renter_org_id,
        "facility_id": facility_id,
        "series_name": series_name,
        "recurrence_rule": recurrence_rule.strip(),
        "season_start": util.iso_z(season_start),
        "season_end": util.iso_z(season_end),
        "renewed_from_id": renewed_from_id,
        "seniority_key": prior["seniority_key"] if prior else rec["created_at"],
        "series_status": "PENDING_GENERATION",
    })
    db.seasonal_permits[rec["id"]] = rec
    if prior is not None:
        touch(prior)  # renewal increments the renewed-from series version

    approved, failed = services.expand_series(rec)
    if approved > 0 and failed > 0:
        rec["series_status"] = "PARTIALLY_BLOCKED"
    elif approved > 0:
        rec["series_status"] = "ACTIVE"
    touch(rec)
    return response.success(series_out(rec), 201)


@bp.get("/district/seasonal_permits/<series_id>")
def get_series_ep(series_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    s = get_series(series_id)
    if role == "RenterOrgRep" and uid != s["renter_org_id"]:
        raise errors.forbidden()
    return response.success(series_out(s))


@bp.get("/district/seasonal_permits")
def list_series():
    require_roles("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator")
    rows = list(db.seasonal_permits.values())
    for param in ("renter_org_id", "series_status", "facility_id",
                  "renewed_from_id"):
        v = request.args.get(param)
        if v:
            rows = [s for s in rows if (s.get(param) or "") == v]
    rows.sort(key=lambda s: s["created_at"])
    return response.paginate([series_out(s) for s in rows])


@bp.get("/district/renters/<org_id>/seasonal_permits")
def list_org_series(org_id):
    uid, role = get_auth()
    if role not in ("FacilitiesDirector", "DistrictAdmin", "SiteCoordinator",
                    "RenterOrgRep"):
        raise errors.forbidden()
    if role == "RenterOrgRep" and uid != org_id:
        raise errors.forbidden()
    get_renter(org_id)
    status = request.args.get("series_status")
    rows = [s for s in db.seasonal_permits.values() if s["renter_org_id"] == org_id]
    if status:
        rows = [s for s in rows if s["series_status"] == status]
    rows.sort(key=lambda s: s["created_at"])
    return response.paginate([series_out(s) for s in rows])


@bp.post("/district/seasonal_permits/<series_id>/cancel")
def cancel_series(series_id):
    uid, role = get_auth()
    if role not in ("RenterOrgRep", "FacilitiesDirector"):
        raise errors.forbidden()
    s = get_series(series_id)
    if role == "RenterOrgRep" and uid != s["renter_org_id"]:
        raise errors.forbidden()
    body = body_json()
    req_string(body, "reason")
    if s["series_status"] not in ("PENDING_GENERATION", "ACTIVE",
                                  "PARTIALLY_BLOCKED"):
        raise errors.invalid_state("Series is not cancellable")
    s["series_status"] = "CANCELLED"
    touch(s)
    now = util.clock_now()
    for p in list(db.permits.values()):
        if p.get("seasonal_permit_id") != series_id:
            continue
        if p["lifecycle_status"] == "ISSUED" and \
                util.parse_iso(p["occupancy_start"]) > now:
            p["lifecycle_status"] = "CANCELLED"
            cancel_permit_record(p, "ADMINISTRATIVE")
    return response.success(series_out(s))
