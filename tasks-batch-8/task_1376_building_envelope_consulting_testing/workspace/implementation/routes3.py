"""API routes — part 3: remediation plans, warranty claims, litigation holds,
maintenance visits, invoices, and flat single-resource/child-list routes."""
from datetime import timedelta
from decimal import Decimal

from flask import request

from db import STORE, clock_now
from errors import (
    ERR_ANOMALY_NOT_VERIFIED,
    ERR_CLAIM_NOT_ACTIONABLE,
    ERR_ENGAGEMENT_FROZEN,
    ERR_ESCALATION_WINDOW_NOT_ELAPSED,
    ERR_FEE_CAP_EXCEEDED,
    ERR_HOLD_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_DRAFT,
    ERR_INVOICE_NOT_ISSUED,
    ERR_NOT_FOUND,
    ERR_OUTSIDE_VISIT_WINDOW,
    ERR_PLAN_NOT_ACTIONABLE,
    ERR_STALE_ENGAGEMENT_VERSION,
    ERR_SUPERSEDES_NOT_ISSUED,
    ERR_VISIT_NOT_SCHEDULED,
    ERR_WINDOW_OVERLAP,
    raise_err,
)
from middleware import ANY_ROLE, auth, require_role
from response import ok
from routes import (
    bp,
    get_child,
    get_engagement,
    list_response,
    require_in_progress,
    require_not_frozen,
    require_posture_open,
)
from services import (
    REMEDIATION_RECOVERY,
    apply_fee_delta,
    apply_risk_delta,
    bump_engagement_version,
    fee_headroom_cents,
    fiscal_gate,
    invoice_totals,
    new_audit,
    new_common,
    remediation_actual,
    remediation_estimate,
    response_due_at,
    ser_anomaly,
    ser_assembly,
    ser_chamber_slot,
    ser_design_review,
    ser_field_test,
    ser_invoice,
    ser_litigation_hold,
    ser_maintenance_visit,
    ser_mock_up,
    ser_remediation_plan,
    ser_survey,
    ser_warranty_claim,
    touch,
    touch_engagement,
    warranty_recovery_share,
)
from validators import (
    get_body,
    opt_int,
    opt_num,
    opt_str,
    parse_date,
    req_int,
    req_list,
    req_num,
    req_str,
)


def _expected_version(body):
    return req_int(body, "expected_engagement_version")


def _check_occ(eng, expected):
    """Tier 13: optimistic concurrency on the two remediation-plan writes."""
    if expected != eng["version"]:
        raise_err(
            ERR_STALE_ENGAGEMENT_VERSION,
            "expected_engagement_version does not match the engagement's current version",
        )


# ---------------------------------------------------------------------------
# RemediationPlan
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/remediation-plans", methods=["POST"], strict_slashes=False)
def create_remediation_plan(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    anomaly_ids = req_list(body, "anomaly_ids")
    for aid in anomaly_ids:
        if not isinstance(aid, str):
            raise_err(ERR_INVALID_REQUEST, "anomaly_ids must be an array of strings")
    spec_sections = req_list(body, "spec_sections")
    for sec in spec_sections:
        if not isinstance(sec, str):
            raise_err(ERR_INVALID_REQUEST, "spec_sections must be an array of strings")
    supersedes_plan_id = opt_str(body, "supersedes_plan_id")
    expected = _expected_version(body)
    require_in_progress(eng)
    anomalies_by_id = {}
    for aid in anomaly_ids:
        anomalies_by_id[aid] = get_child("anomalies", aid, eng["id"], "Anomaly")
    target = None
    if supersedes_plan_id is not None:
        candidate = STORE["remediation_plans"].get(supersedes_plan_id)
        if (
            candidate is None
            or candidate["engagement_id"] != eng["id"]
            or candidate["plan_status"] != "ISSUED"
        ):
            raise_err(
                ERR_SUPERSEDES_NOT_ISSUED,
                "supersedes_plan_id must reference an ISSUED plan of this engagement",
            )
        target = candidate
    _check_occ(eng, expected)
    plan = new_common()
    plan.update(
        {
            "engagement_id": eng["id"],
            "anomaly_ids": list(anomaly_ids),
            "spec_sections": list(spec_sections),
            "estimated_cost_cents": None,
            "actual_cost_cents": None,
            "plan_status": "DRAFT",
            "supersedes_plan_id": supersedes_plan_id,
        }
    )
    STORE["remediation_plans"][plan["id"]] = plan
    if target is not None:
        # Supersede: flip ISSUED -> SUPERSEDED and reverse provisional recognition.
        target["plan_status"] = "SUPERSEDED"
        touch(target)
        apply_fee_delta(eng, -target["estimated_cost_cents"], "remediation_supersede")
    bump_engagement_version(eng)
    return ok(ser_remediation_plan(plan), status=201)


@bp.route("/engagements/<engagement_id>/remediation-plans", methods=["GET"], strict_slashes=False)
def list_remediation_plans(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return list_response(
        [
            p
            for p in STORE["remediation_plans"].values()
            if p["engagement_id"] == eng["id"]
        ],
        ser_remediation_plan,
    )


@bp.route("/engagements/<engagement_id>/remediation-plans/<plan_id>", methods=["GET"], strict_slashes=False)
def get_remediation_plan_route(engagement_id, plan_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(
        ser_remediation_plan(
            get_child("remediation_plans", plan_id, eng["id"], "RemediationPlan")
        )
    )


@bp.route(
    "/engagements/<engagement_id>/remediation-plans/<plan_id>/issue",
    methods=["POST"],
    strict_slashes=False,
)
def issue_remediation_plan(engagement_id, plan_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    plan = get_child("remediation_plans", plan_id, eng["id"], "RemediationPlan")
    body = get_body()
    expected = _expected_version(body)
    require_in_progress(eng)
    require_posture_open(eng)
    if plan["plan_status"] != "DRAFT":
        raise_err(ERR_PLAN_NOT_ACTIONABLE, "issue requires plan_status DRAFT")
    anomalies_by_id = {
        aid: get_child("anomalies", aid, eng["id"], "Anomaly")
        for aid in plan["anomaly_ids"]
    }
    if any(a["status"] != "VERIFIED" for a in anomalies_by_id.values()):
        raise_err(
            ERR_ANOMALY_NOT_VERIFIED,
            "Every anomaly named in anomaly_ids must be VERIFIED at issuance",
        )
    estimate = remediation_estimate(plan, anomalies_by_id)
    fiscal_gate(eng, estimate)
    _check_occ(eng, expected)
    plan["plan_status"] = "ISSUED"
    plan["estimated_cost_cents"] = estimate
    touch(plan)
    apply_fee_delta(eng, estimate, "remediation_estimate")
    bump_engagement_version(eng)
    return ok(ser_remediation_plan(plan))


@bp.route(
    "/engagements/<engagement_id>/remediation-plans/<plan_id>/complete",
    methods=["POST"],
    strict_slashes=False,
)
def complete_remediation_plan(engagement_id, plan_id):
    _, role = auth()
    require_role(role, {"Principal"})
    eng = get_engagement(engagement_id)
    plan = get_child("remediation_plans", plan_id, eng["id"], "RemediationPlan")
    require_in_progress(eng)
    require_not_frozen(eng)
    if plan["plan_status"] != "ISSUED":
        raise_err(ERR_PLAN_NOT_ACTIONABLE, "complete requires plan_status ISSUED")
    anomalies_by_id = {
        aid: get_child("anomalies", aid, eng["id"], "Anomaly")
        for aid in plan["anomaly_ids"]
    }
    actual = remediation_actual(plan, anomalies_by_id)
    delta = actual - plan["estimated_cost_cents"]
    fiscal_gate(eng, delta)
    plan["plan_status"] = "COMPLETED"
    plan["actual_cost_cents"] = actual
    touch(plan)
    apply_fee_delta(eng, delta, "remediation_completion_delta")
    # Cascade: covered anomalies VERIFIED -> REMEDIATED, +10 risk each, per-anomaly.
    for aid in plan["anomaly_ids"]:
        anomaly = anomalies_by_id[aid]
        if anomaly["status"] == "VERIFIED":
            anomaly["status"] = "REMEDIATED"
            touch(anomaly)
            apply_risk_delta(eng, REMEDIATION_RECOVERY)
    return ok(ser_remediation_plan(plan))


@bp.route(
    "/engagements/<engagement_id>/remediation-plans/<plan_id>/withdraw",
    methods=["POST"],
    strict_slashes=False,
)
def withdraw_remediation_plan(engagement_id, plan_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    plan = get_child("remediation_plans", plan_id, eng["id"], "RemediationPlan")
    require_in_progress(eng)
    if plan["plan_status"] != "DRAFT":
        raise_err(ERR_PLAN_NOT_ACTIONABLE, "withdraw requires plan_status DRAFT")
    plan["plan_status"] = "WITHDRAWN"
    touch(plan)
    return ok(ser_remediation_plan(plan))


# ---------------------------------------------------------------------------
# WarrantyClaim
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/warranty-claims", methods=["POST"], strict_slashes=False)
def create_warranty_claim(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    anomaly_id = req_str(body, "anomaly_id")
    manufacturer_name = req_str(body, "manufacturer_name")
    claimed = req_int(body, "claimed_amount_cents", lo=1)
    require_in_progress(eng)
    anomaly = get_child("anomalies", anomaly_id, eng["id"], "Anomaly")
    if anomaly["status"] != "VERIFIED":
        raise_err(
            ERR_ANOMALY_NOT_VERIFIED,
            "Warranty claim requires the referenced anomaly to be VERIFIED",
        )
    filed = clock_now()
    c = new_common()
    c.update(
        {
            "engagement_id": eng["id"],
            "anomaly_id": anomaly_id,
            "manufacturer_name": manufacturer_name,
            "claimed_amount_cents": claimed,
            "recovered_amount_cents": 0,
            "_filed_at": filed,
            "_response_due_at": response_due_at(filed),
            "claim_status": "FILED",
        }
    )
    STORE["warranty_claims"][c["id"]] = c
    return ok(ser_warranty_claim(c), status=201)


@bp.route("/engagements/<engagement_id>/warranty-claims", methods=["GET"], strict_slashes=False)
def list_warranty_claims(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    items = [
        c for c in STORE["warranty_claims"].values() if c["engagement_id"] == eng["id"]
    ]
    anomaly_id = request.args.get("anomaly_id")
    if anomaly_id is not None:
        items = [c for c in items if c["anomaly_id"] == anomaly_id]
    return list_response(items, ser_warranty_claim)


@bp.route("/engagements/<engagement_id>/warranty-claims/<claim_id>", methods=["GET"], strict_slashes=False)
def get_warranty_claim_route(engagement_id, claim_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(
        ser_warranty_claim(
            get_child("warranty_claims", claim_id, eng["id"], "WarrantyClaim")
        )
    )


def _claim_transition(engagement_id, claim_id, allowed_roles):
    uid, role = auth()
    require_role(role, allowed_roles)
    eng = get_engagement(engagement_id)
    claim = get_child("warranty_claims", claim_id, eng["id"], "WarrantyClaim")
    require_in_progress(eng)
    return uid, eng, claim


@bp.route(
    "/engagements/<engagement_id>/warranty-claims/<claim_id>/manufacturer-acknowledge",
    methods=["POST"],
    strict_slashes=False,
)
def claim_manufacturer_acknowledge(engagement_id, claim_id):
    _, eng, claim = _claim_transition(engagement_id, claim_id, {"ManufacturerRep"})
    if claim["claim_status"] != "FILED":
        raise_err(ERR_CLAIM_NOT_ACTIONABLE, "acknowledge requires FILED")
    claim["claim_status"] = "UNDER_MANUFACTURER_REVIEW"
    touch(claim)
    return ok(ser_warranty_claim(claim))


@bp.route(
    "/engagements/<engagement_id>/warranty-claims/<claim_id>/manufacturer-decide",
    methods=["POST"],
    strict_slashes=False,
)
def claim_manufacturer_decide(engagement_id, claim_id):
    _, eng, claim = _claim_transition(engagement_id, claim_id, {"ManufacturerRep"})
    body = get_body()
    decision = body.get("decision")
    if decision is None or not isinstance(decision, str):
        raise_err(ERR_INVALID_REQUEST, "Field 'decision' is required")
    if decision not in ("ACCEPTED", "DENIED"):
        raise_err(
            ERR_CLAIM_NOT_ACTIONABLE, "decision must be either ACCEPTED or DENIED"
        )
    if claim["claim_status"] not in ("UNDER_MANUFACTURER_REVIEW", "ESCALATED"):
        raise_err(
            ERR_CLAIM_NOT_ACTIONABLE,
            "decide requires UNDER_MANUFACTURER_REVIEW or ESCALATED",
        )
    claim["claim_status"] = decision
    touch(claim)
    return ok(ser_warranty_claim(claim))


@bp.route(
    "/engagements/<engagement_id>/warranty-claims/<claim_id>/escalate",
    methods=["POST"],
    strict_slashes=False,
)
def claim_escalate(engagement_id, claim_id):
    _, eng, claim = _claim_transition(engagement_id, claim_id, {"Consultant"})
    if claim["claim_status"] != "DENIED":
        raise_err(ERR_CLAIM_NOT_ACTIONABLE, "escalate requires DENIED")
    if clock_now() < claim["_response_due_at"]:
        raise_err(
            ERR_ESCALATION_WINDOW_NOT_ELAPSED,
            "escalate requires the logical clock to have reached response_due_at",
        )
    claim["claim_status"] = "ESCALATED"
    touch(claim)
    return ok(ser_warranty_claim(claim))


@bp.route(
    "/engagements/<engagement_id>/warranty-claims/<claim_id>/resolve",
    methods=["POST"],
    strict_slashes=False,
)
def claim_resolve(engagement_id, claim_id):
    _, eng, claim = _claim_transition(engagement_id, claim_id, {"Consultant"})
    if claim["claim_status"] != "ACCEPTED":
        raise_err(ERR_CLAIM_NOT_ACTIONABLE, "resolve requires ACCEPTED")
    recovered = warranty_recovery_share(claim)
    claim["claim_status"] = "RESOLVED"
    claim["recovered_amount_cents"] = recovered
    touch(claim)
    # Recovery offsets recognized fees; provisional accumulator floored at 0.
    apply_fee_delta(eng, -recovered, "warranty_recovery")
    return ok(ser_warranty_claim(claim))


# ---------------------------------------------------------------------------
# LitigationHold
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/litigation-holds", methods=["POST"], strict_slashes=False)
def create_litigation_hold(engagement_id):
    _, role = auth()
    require_role(role, {"Principal"})
    eng = get_engagement(engagement_id)
    body = get_body()
    matter_reference = req_str(body, "matter_reference")
    require_in_progress(eng)
    hold = new_audit()
    hold.update(
        {
            "engagement_id": eng["id"],
            "matter_reference": matter_reference,
            "hold_status": "ACTIVE",
        }
    )
    STORE["litigation_holds"][hold["id"]] = hold
    eng["litigation_hold_active"] = True
    bump_engagement_version(eng)
    return ok(ser_litigation_hold(hold), status=201)


@bp.route("/engagements/<engagement_id>/litigation-holds", methods=["GET"], strict_slashes=False)
def list_litigation_holds(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return list_response(
        [
            h
            for h in STORE["litigation_holds"].values()
            if h["engagement_id"] == eng["id"]
        ],
        ser_litigation_hold,
    )


@bp.route("/engagements/<engagement_id>/litigation-holds/<hold_id>", methods=["GET"], strict_slashes=False)
def get_litigation_hold_route(engagement_id, hold_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(
        ser_litigation_hold(
            get_child("litigation_holds", hold_id, eng["id"], "LitigationHold")
        )
    )


@bp.route(
    "/engagements/<engagement_id>/litigation-holds/<hold_id>/release",
    methods=["POST"],
    strict_slashes=False,
)
def release_litigation_hold(engagement_id, hold_id):
    _, role = auth()
    require_role(role, {"Principal"})
    eng = get_engagement(engagement_id)
    hold = get_child("litigation_holds", hold_id, eng["id"], "LitigationHold")
    require_in_progress(eng)
    if hold["hold_status"] != "ACTIVE":
        raise_err(ERR_HOLD_NOT_ACTIVE, "release requires hold_status ACTIVE")
    hold["hold_status"] = "RELEASED"
    eng["litigation_hold_active"] = any(
        h["engagement_id"] == eng["id"] and h["hold_status"] == "ACTIVE"
        for h in STORE["litigation_holds"].values()
    )
    bump_engagement_version(eng)
    return ok(ser_litigation_hold(hold))


# ---------------------------------------------------------------------------
# MaintenanceVisit
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/maintenance-visits", methods=["POST"], strict_slashes=False)
def create_maintenance_visit(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    visit_label = req_str(body, "visit_label")
    start_s = req_str(body, "window_start_date")
    end_s = req_str(body, "window_end_date")
    start_d = parse_date(start_s, "window_start_date")
    end_d = parse_date(end_s, "window_end_date")
    if end_d < start_d:
        raise_err(
            ERR_INVALID_REQUEST,
            "window_end_date must not be earlier than window_start_date",
        )
    buffer_days = opt_int(body, "buffer_days", default=0, lo=0)
    require_in_progress(eng)
    # Closed window expanded by buffer_days on both sides vs other SCHEDULED
    # visits' closed windows; touching endpoints DO conflict.
    exp_start = start_d - timedelta(days=buffer_days)
    exp_end = end_d + timedelta(days=buffer_days)
    for v in STORE["maintenance_visits"].values():
        if (
            v["engagement_id"] == eng["id"]
            and v["visit_status"] == "SCHEDULED"
            and exp_start <= v["_window_end"]
            and v["_window_start"] <= exp_end
        ):
            raise_err(
                ERR_WINDOW_OVERLAP,
                "Visit window (buffer-expanded) overlaps another SCHEDULED visit",
            )
    v = new_common()
    v.update(
        {
            "engagement_id": eng["id"],
            "visit_label": visit_label,
            "window_start_date": start_s,
            "window_end_date": end_s,
            "_window_start": start_d,
            "_window_end": end_d,
            "buffer_days": buffer_days,
            "visit_status": "SCHEDULED",
        }
    )
    STORE["maintenance_visits"][v["id"]] = v
    return ok(ser_maintenance_visit(v), status=201)


@bp.route("/engagements/<engagement_id>/maintenance-visits", methods=["GET"], strict_slashes=False)
def list_maintenance_visits(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return list_response(
        [
            v
            for v in STORE["maintenance_visits"].values()
            if v["engagement_id"] == eng["id"]
        ],
        ser_maintenance_visit,
    )


@bp.route("/engagements/<engagement_id>/maintenance-visits/<visit_id>", methods=["GET"], strict_slashes=False)
def get_maintenance_visit_route(engagement_id, visit_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(
        ser_maintenance_visit(
            get_child("maintenance_visits", visit_id, eng["id"], "MaintenanceVisit")
        )
    )


@bp.route(
    "/engagements/<engagement_id>/maintenance-visits/<visit_id>/complete",
    methods=["POST"],
    strict_slashes=False,
)
def complete_maintenance_visit(engagement_id, visit_id):
    _, role = auth()
    require_role(role, {"FieldTechnician"})
    eng = get_engagement(engagement_id)
    v = get_child("maintenance_visits", visit_id, eng["id"], "MaintenanceVisit")
    require_in_progress(eng)
    if v["visit_status"] != "SCHEDULED":
        raise_err(ERR_VISIT_NOT_SCHEDULED, "complete requires visit_status SCHEDULED")
    today = clock_now().date()
    if not (v["_window_start"] <= today <= v["_window_end"]):
        raise_err(
            ERR_OUTSIDE_VISIT_WINDOW,
            "Logical clock date is outside the visit's closed window",
        )
    v["visit_status"] = "COMPLETED"
    touch(v)
    return ok(ser_maintenance_visit(v))


@bp.route(
    "/engagements/<engagement_id>/maintenance-visits/<visit_id>/cancel",
    methods=["POST"],
    strict_slashes=False,
)
def cancel_maintenance_visit(engagement_id, visit_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    v = get_child("maintenance_visits", visit_id, eng["id"], "MaintenanceVisit")
    require_in_progress(eng)
    if v["visit_status"] != "SCHEDULED":
        raise_err(ERR_VISIT_NOT_SCHEDULED, "cancel requires visit_status SCHEDULED")
    v["visit_status"] = "CANCELLED"
    touch(v)
    return ok(ser_maintenance_visit(v))


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/invoices", methods=["POST"], strict_slashes=False)
def create_invoice(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    labor_hours = req_num(body, "labor_hours", lo=Decimal(0))
    expense_cents = req_int(body, "expense_cents", lo=0)
    discount = opt_num(body, "discount_pct", default=Decimal(0), lo=Decimal(0), hi=Decimal(100))
    require_in_progress(eng)
    subtotal, total = invoice_totals(eng, labor_hours, expense_cents, discount)
    inv = new_audit()
    inv.update(
        {
            "engagement_id": eng["id"],
            "labor_hours": labor_hours,
            "expense_cents": expense_cents,
            "discount_pct": discount,
            "subtotal_cents": subtotal,
            "total_cents": total,
            "invoice_status": "DRAFT",
        }
    )
    STORE["invoices"][inv["id"]] = inv
    return ok(ser_invoice(inv), status=201)


@bp.route("/engagements/<engagement_id>/invoices", methods=["GET"], strict_slashes=False)
def list_invoices(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return list_response(
        [i for i in STORE["invoices"].values() if i["engagement_id"] == eng["id"]],
        ser_invoice,
    )


@bp.route("/engagements/<engagement_id>/invoices/<invoice_id>", methods=["GET"], strict_slashes=False)
def get_invoice_route(engagement_id, invoice_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return ok(ser_invoice(get_child("invoices", invoice_id, eng["id"], "Invoice")))


@bp.route(
    "/engagements/<engagement_id>/invoices/<invoice_id>/issue",
    methods=["POST"],
    strict_slashes=False,
)
def issue_invoice(engagement_id, invoice_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    inv = get_child("invoices", invoice_id, eng["id"], "Invoice")
    require_in_progress(eng)
    require_not_frozen(eng)
    if inv["invoice_status"] != "DRAFT":
        raise_err(ERR_INVOICE_NOT_DRAFT, "issue requires invoice_status DRAFT")
    if fee_headroom_cents(eng) < inv["total_cents"]:
        raise_err(
            ERR_FEE_CAP_EXCEEDED,
            "fee_headroom_cents must be at least the invoice total_cents",
        )
    inv["invoice_status"] = "ISSUED"
    touch_engagement(eng)
    return ok(ser_invoice(inv))


@bp.route(
    "/engagements/<engagement_id>/invoices/<invoice_id>/mark-paid",
    methods=["POST"],
    strict_slashes=False,
)
def mark_invoice_paid(engagement_id, invoice_id):
    _, role = auth()
    require_role(role, {"Principal"})
    eng = get_engagement(engagement_id)
    inv = get_child("invoices", invoice_id, eng["id"], "Invoice")
    require_in_progress(eng)
    if inv["invoice_status"] != "ISSUED":
        raise_err(ERR_INVOICE_NOT_ISSUED, "mark-paid requires invoice_status ISSUED")
    inv["invoice_status"] = "PAID"
    touch_engagement(eng)
    return ok(ser_invoice(inv))


@bp.route(
    "/engagements/<engagement_id>/invoices/<invoice_id>/void",
    methods=["POST"],
    strict_slashes=False,
)
def void_invoice(engagement_id, invoice_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    inv = get_child("invoices", invoice_id, eng["id"], "Invoice")
    require_in_progress(eng)
    if inv["invoice_status"] != "DRAFT":
        raise_err(ERR_INVOICE_NOT_DRAFT, "void requires invoice_status DRAFT")
    inv["invoice_status"] = "VOID"
    touch_engagement(eng)
    return ok(ser_invoice(inv))


# ---------------------------------------------------------------------------
# Flat single-resource GETs and reverse-reachability list routes
# ---------------------------------------------------------------------------
def _flat_get(collection, entity_id, serializer, what):
    _, role = auth()
    require_role(role, ANY_ROLE)
    entity = STORE[collection].get(entity_id)
    if entity is None:
        raise_err(ERR_NOT_FOUND, f"{what} not found")
    return ok(serializer(entity))


def _flat_children(collection, entity_id, children_coll, fk, serializer, what):
    _, role = auth()
    require_role(role, ANY_ROLE)
    entity = STORE[collection].get(entity_id)
    if entity is None:
        raise_err(ERR_NOT_FOUND, f"{what} not found")
    return list_response(
        [c for c in STORE[children_coll].values() if c.get(fk) == entity_id],
        serializer,
    )


@bp.route("/assemblies/<entity_id>", methods=["GET"], strict_slashes=False)
def flat_get_assembly(entity_id):
    return _flat_get("assemblies", entity_id, ser_assembly, "Assembly")


@bp.route("/assemblies/<entity_id>/design-reviews", methods=["GET"], strict_slashes=False)
def flat_assembly_design_reviews(entity_id):
    return _flat_children(
        "assemblies", entity_id, "design_reviews", "assembly_id", ser_design_review, "Assembly"
    )


@bp.route("/assemblies/<entity_id>/mock-ups", methods=["GET"], strict_slashes=False)
def flat_assembly_mock_ups(entity_id):
    return _flat_children(
        "assemblies", entity_id, "mock_ups", "assembly_id", ser_mock_up, "Assembly"
    )


@bp.route("/assemblies/<entity_id>/field-tests", methods=["GET"], strict_slashes=False)
def flat_assembly_field_tests(entity_id):
    return _flat_children(
        "assemblies", entity_id, "field_tests", "assembly_id", ser_field_test, "Assembly"
    )


@bp.route("/assemblies/<entity_id>/surveys", methods=["GET"], strict_slashes=False)
def flat_assembly_surveys(entity_id):
    return _flat_children(
        "assemblies", entity_id, "surveys", "assembly_id", ser_survey, "Assembly"
    )


@bp.route("/chamber-slots/<entity_id>", methods=["GET"], strict_slashes=False)
def flat_get_chamber_slot(entity_id):
    return _flat_get("chamber_slots", entity_id, ser_chamber_slot, "ChamberSlot")


@bp.route("/chamber-slots/<entity_id>/mock-ups", methods=["GET"], strict_slashes=False)
def flat_chamber_slot_mock_ups(entity_id):
    return _flat_children(
        "chamber_slots", entity_id, "mock_ups", "chamber_slot_id", ser_mock_up, "ChamberSlot"
    )


@bp.route("/field-tests/<entity_id>", methods=["GET"], strict_slashes=False)
def flat_get_field_test(entity_id):
    return _flat_get("field_tests", entity_id, ser_field_test, "FieldTest")


@bp.route("/field-tests/<entity_id>/anomalies", methods=["GET"], strict_slashes=False)
def flat_field_test_anomalies(entity_id):
    return _flat_children(
        "field_tests", entity_id, "anomalies", "field_test_id", ser_anomaly, "FieldTest"
    )


@bp.route("/surveys/<entity_id>", methods=["GET"], strict_slashes=False)
def flat_get_survey(entity_id):
    return _flat_get("surveys", entity_id, ser_survey, "Survey")


@bp.route("/surveys/<entity_id>/anomalies", methods=["GET"], strict_slashes=False)
def flat_survey_anomalies(entity_id):
    return _flat_children(
        "surveys", entity_id, "anomalies", "survey_id", ser_anomaly, "Survey"
    )


@bp.route("/anomalies/<entity_id>", methods=["GET"], strict_slashes=False)
def flat_get_anomaly(entity_id):
    return _flat_get("anomalies", entity_id, ser_anomaly, "Anomaly")


@bp.route("/anomalies/<entity_id>/warranty-claims", methods=["GET"], strict_slashes=False)
def flat_anomaly_warranty_claims(entity_id):
    return _flat_children(
        "anomalies", entity_id, "warranty_claims", "anomaly_id", ser_warranty_claim, "Anomaly"
    )


@bp.route("/remediation-plans/<entity_id>", methods=["GET"], strict_slashes=False)
def flat_get_remediation_plan(entity_id):
    return _flat_get("remediation_plans", entity_id, ser_remediation_plan, "RemediationPlan")


@bp.route("/remediation-plans", methods=["GET"], strict_slashes=False)
def flat_list_remediation_plans():
    _, role = auth()
    require_role(role, ANY_ROLE)
    items = list(STORE["remediation_plans"].values())
    supersedes_plan_id = request.args.get("supersedes_plan_id")
    if supersedes_plan_id is not None:
        items = [p for p in items if p["supersedes_plan_id"] == supersedes_plan_id]
    return list_response(items, ser_remediation_plan)
