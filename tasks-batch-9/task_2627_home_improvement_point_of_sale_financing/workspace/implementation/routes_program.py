"""Logical clock, ops sweep, program reference data and merchant records."""
from flask import Blueprint

import calc
import ops
import serialize as ser
import validate as v
from errors import fail
from response import created, listing, ok
from store import db
from util import fmt_dt

bp = Blueprint("program", __name__)


# =============================================================================
# Logical clock (PRD 2.5)
# =============================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    ctx = v.authorize(("ProgramAdmin", "ServicingAgent"))
    body = v.read_body(ctx)
    supplied = v.req_instant(body, "current_utc")
    previous = db.clock
    if supplied < previous:
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "The logical clock may only move forward or stay put.")
    db.clock = supplied
    return ok({"current_utc": fmt_dt(db.clock), "previous_utc": fmt_dt(previous)})


@bp.post("/servicing/expiration-sweeps")
def expiration_sweep():
    ctx = v.authorize(("ServicingAgent", "ProgramAdmin"))
    v.read_body(ctx)
    return ok(ops.run_expiration_sweep())


# =============================================================================
# Trade rules (PRD 3.1)
# =============================================================================
@bp.post("/trade-rules")
def create_trade_rule():
    ctx = v.authorize(("ProgramAdmin",))
    body = v.read_body(ctx)
    trade_type = v.req_enum(body, "trade_type", v.TRADE_TYPES)
    max_ticket = v.req_money(body, "max_ticket_cents")
    holdback_bps = v.req_money(body, "holdback_pct_bps")
    precompletion_bps = v.req_money(body, "max_precompletion_release_bps")
    velocity_cap = v.req_money(body, "velocity_cap_cents")
    requires_cert = v.req_bool(body, "requires_completion_certificate")
    min_months = v.req_int(body, "min_license_months", minimum=0)
    if calc.trade_rule_for(trade_type) is not None:
        fail("ERR_DUPLICATE_TRADE_RULE",
             "A trade rule already exists for %s." % trade_type)
    rec = db.new_record()
    rec.update({
        "trade_type": trade_type,
        "max_ticket_cents": max_ticket,
        "holdback_pct_bps": holdback_bps,
        "max_precompletion_release_bps": precompletion_bps,
        "velocity_cap_cents": velocity_cap,
        "requires_completion_certificate": requires_cert,
        "min_license_months": min_months,
    })
    db.trade_rules[rec["id"]] = rec
    return created(ser.trade_rule(rec))


@bp.get("/trade-rules")
def list_trade_rules():
    v.authorize(("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                 "ServicingAgent", "Merchant"))
    limit, offset = v.pagination()
    trade_type = v.filter_arg("trade_type")
    rows = [r for r in db.ordered(db.trade_rules)
            if trade_type is None or r["trade_type"] == trade_type]
    page = v.paginate(rows, limit, offset)
    return listing([ser.trade_rule(r) for r in page], limit, offset, len(rows))


# =============================================================================
# Promotion plans (PRD 3.1)
# =============================================================================
@bp.post("/promotion-plans")
def create_promotion_plan():
    ctx = v.authorize(("ProgramAdmin",))
    body = v.read_body(ctx)
    code = v.req_str(body, "code")
    promotion_type = v.req_enum(body, "promotion_type", v.PROMOTION_TYPES)
    term_months = v.req_int(body, "promo_term_months", minimum=0)
    deferred_apr = v.req_money(body, "deferred_apr_bps")
    post_promo_apr = v.req_money(body, "post_promo_apr_bps")
    discount_bps = v.req_money(body, "merchant_discount_bps")
    min_ticket = v.req_money(body, "min_ticket_cents")
    max_ticket = v.req_money(body, "max_ticket_cents")
    template_version = v.req_str(body, "disclosure_template_version")
    allowed = v.req_enum_array(body, "allowed_trade_types", v.TRADE_TYPES)
    for plan in db.ordered(db.promotion_plans):
        if plan["code"] == code:
            fail("ERR_DUPLICATE_PROMOTION_CODE",
                 "Promotion code %s already exists." % code)
    rec = db.new_record()
    rec.update({
        "code": code,
        "promotion_type": promotion_type,
        "promo_term_months": term_months,
        "deferred_apr_bps": deferred_apr,
        "post_promo_apr_bps": post_promo_apr,
        "merchant_discount_bps": discount_bps,
        "min_ticket_cents": min_ticket,
        "max_ticket_cents": max_ticket,
        "disclosure_template_version": template_version,
        "allowed_trade_types": allowed,
    })
    db.promotion_plans[rec["id"]] = rec
    return created(ser.promotion_plan(rec))


@bp.get("/promotion-plans")
def list_promotion_plans():
    v.authorize(("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                 "ServicingAgent", "Merchant"))
    limit, offset = v.pagination()
    code = v.filter_arg("code")
    promotion_type = v.filter_arg("promotion_type")
    rows = []
    for plan in db.ordered(db.promotion_plans):
        if code is not None and plan["code"] != code:
            continue
        if promotion_type is not None and plan["promotion_type"] != promotion_type:
            continue
        rows.append(plan)
    page = v.paginate(rows, limit, offset)
    return listing([ser.promotion_plan(r) for r in page], limit, offset, len(rows))


# =============================================================================
# Merchants (PRD 3.2)
# =============================================================================
@bp.post("/merchants")
def create_merchant():
    ctx = v.authorize(("ProgramAdmin",))
    body = v.read_body(ctx)
    legal_name = v.req_str(body, "legal_name")
    trade_type = v.req_enum(body, "trade_type", v.TRADE_TYPES)
    state_code = v.req_str(body, "state_code")
    contact_email = v.req_str(body, "contact_email")
    rec = db.new_record()
    rec.update({
        "legal_name": legal_name,
        "trade_type": trade_type,
        "state_code": state_code,
        "contact_email": contact_email,
        "enrollment_status": "DRAFT",
        "attestation_ref": None,
        "approved_by_user_id": None,
        "approved_on": None,
        "suspension_reason_code": None,
        "termination_reason_code": None,
        "holdback_reserve_cents": 0,
        "holdback_target_cents": 0,
        "settlement_offset_receivable_cents": 0,
        "program_write_off_cents": 0,
    })
    db.merchants[rec["id"]] = rec
    return created(ser.merchant(rec))


MERCHANT_READ_ROLES = ("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                       "ServicingAgent", "Merchant")


@bp.get("/merchants/<merchant_id>")
def read_merchant(merchant_id):
    ctx = v.authorize(MERCHANT_READ_ROLES)
    merchant = v.get_merchant(merchant_id)
    v.resolve_identity(ctx, MERCHANT_READ_ROLES)
    v.merchant_scope(ctx, merchant_id)
    return ok(ser.merchant(merchant))


@bp.get("/merchants")
def list_merchants():
    v.authorize(("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                 "ServicingAgent"))
    limit, offset = v.pagination()
    enrollment_status = v.filter_arg("enrollment_status")
    trade_type = v.filter_arg("trade_type")
    risk_tier = v.filter_arg("risk_tier")
    grade = v.filter_arg("portfolio_grade")
    recommended = v.bool_filter_arg("termination_recommended")
    rows = []
    for merchant in db.ordered(db.merchants):
        if enrollment_status is not None and merchant["enrollment_status"] != enrollment_status:
            continue
        if trade_type is not None and merchant["trade_type"] != trade_type:
            continue
        if risk_tier is not None and calc.merchant_risk_tier(merchant["id"]) != risk_tier:
            continue
        if grade is not None and calc.merchant_grade(merchant["id"]) != grade:
            continue
        if recommended is not None and calc.termination_recommended(merchant["id"]) != recommended:
            continue
        rows.append(merchant)
    page = v.paginate(rows, limit, offset)
    return listing([ser.merchant(r) for r in page], limit, offset, len(rows))


# =============================================================================
# Merchant licences (PRD 3.2)
# =============================================================================
@bp.post("/merchants/<merchant_id>/licenses")
def file_license(merchant_id):
    roles = ("Merchant", "ProgramAdmin")
    ctx = v.authorize(roles)
    body = v.read_body(ctx)
    trade_type = v.req_enum(body, "trade_type", v.TRADE_TYPES)
    license_number = v.req_str(body, "license_number")
    state_code = v.req_str(body, "state_code")
    effective_from = v.req_date(body, "effective_from")
    expires_on = v.req_date(body, "expires_on")
    # Band 4 — half-open coverage, so equal dates describe an empty interval.
    if effective_from >= expires_on:
        fail("ERR_INVALID_DATE_RANGE",
             "effective_from must be strictly earlier than expires_on.")
    merchant = v.get_merchant(merchant_id)
    v.resolve_identity(ctx, roles)
    v.merchant_scope(ctx, merchant_id)
    # Band 35 — overlap among UNVERIFIED / VERIFIED licences of the same
    # merchant, trade and state. Touching intervals do not conflict.
    new_from = calc.parse_date(effective_from)
    new_to = calc.parse_date(expires_on)
    for other in db.ordered(db.licenses):
        if other["merchant_id"] != merchant_id:
            continue
        if other["verification_status"] not in ("UNVERIFIED", "VERIFIED"):
            continue
        if other["trade_type"] != trade_type or other["state_code"] != state_code:
            continue
        other_from = calc.parse_date(other["effective_from"])
        other_to = calc.parse_date(other["expires_on"])
        if new_from < other_to and other_from < new_to:
            fail("ERR_LICENSE_COVERAGE_OVERLAP",
                 "Coverage overlaps licence %s." % other["id"])
    rec = db.new_record()
    rec.update({
        "merchant_id": merchant["id"],
        "trade_type": trade_type,
        "license_number": license_number,
        "state_code": state_code,
        "effective_from": effective_from,
        "expires_on": expires_on,
        "verification_status": "UNVERIFIED",
        "verified_by_user_id": None,
        "verification_note": None,
        "verified_on": None,
    })
    db.licenses[rec["id"]] = rec
    return created(ser.merchant_license(rec))


@bp.get("/merchants/<merchant_id>/licenses")
def list_licenses(merchant_id):
    ctx = v.authorize(MERCHANT_READ_ROLES)
    v.get_merchant(merchant_id)
    v.resolve_identity(ctx, MERCHANT_READ_ROLES)
    v.merchant_scope(ctx, merchant_id)
    limit, offset = v.pagination()
    status = v.filter_arg("verification_status")
    trade_type = v.filter_arg("trade_type")
    rows = []
    for lic in db.ordered(db.licenses):
        if lic["merchant_id"] != merchant_id:
            continue
        if status is not None and lic["verification_status"] != status:
            continue
        if trade_type is not None and lic["trade_type"] != trade_type:
            continue
        rows.append(lic)
    page = v.paginate(rows, limit, offset)
    return listing([ser.merchant_license(r) for r in page], limit, offset, len(rows))


@bp.post("/merchants/<merchant_id>/licenses/<license_id>/verification")
def verify_license(merchant_id, license_id):
    ctx = v.authorize(("ProgramUnderwriter",))
    body = v.read_body(ctx)
    outcome = v.req_enum(body, "outcome", ("VERIFIED", "REJECTED"))
    note = v.opt_str(body, "verification_note")
    merchant = v.get_merchant(merchant_id)
    lic = v.get_license(merchant_id, license_id)
    # Band 15 — the licence must still be undecided.
    if lic["verification_status"] != "UNVERIFIED":
        fail("ERR_LICENSE_ALREADY_DECIDED",
             "Licence %s has already been decided." % license_id)
    # UNVERIFIED -> VERIFIED additionally requires a non-terminated merchant.
    if outcome == "VERIFIED" and merchant["enrollment_status"] == "TERMINATED":
        fail("ERR_INVALID_MERCHANT_STATE",
             "A terminated merchant's licence may not be verified.")
    lic["verification_status"] = outcome
    lic["verified_by_user_id"] = ctx.user_id
    lic["verification_note"] = note
    lic["verified_on"] = db.now()
    ops.bump(lic)
    return ok(ser.merchant_license(lic))


# =============================================================================
# Enrollment review (PRD 3.2)
# =============================================================================
@bp.post("/merchants/<merchant_id>/enrollment-submission")
def submit_enrollment(merchant_id):
    roles = ("Merchant", "ProgramAdmin")
    ctx = v.authorize(roles)
    body = v.read_body(ctx)
    attestation_ref = v.req_str(body, "attestation_ref")
    merchant = v.get_merchant(merchant_id)
    v.resolve_identity(ctx, roles)
    v.merchant_scope(ctx, merchant_id)
    # Band 14 — submission only from DRAFT or DOCS_REQUIRED.
    if merchant["enrollment_status"] not in ("DRAFT", "DOCS_REQUIRED"):
        fail("ERR_INVALID_MERCHANT_STATE",
             "A merchant in %s may not be submitted for review."
             % merchant["enrollment_status"])
    filed = [lic for lic in db.ordered(db.licenses)
             if lic["merchant_id"] == merchant_id
             and lic["verification_status"] in ("UNVERIFIED", "VERIFIED")]
    if not filed:
        fail("ERR_LICENSE_NOT_VERIFIED",
             "At least one unverified or verified licence must be on file.")
    merchant["attestation_ref"] = attestation_ref
    merchant["enrollment_status"] = "PENDING_REVIEW"
    ops.bump(merchant)
    return ok(ser.merchant(merchant))


@bp.post("/merchants/<merchant_id>/enrollment-decision")
def decide_enrollment(merchant_id):
    ctx = v.authorize(("ProgramUnderwriter",))
    body = v.read_body(ctx)
    decision = v.req_enum(body, "decision", ("APPROVE", "DECLINE", "REQUEST_DOCS"))
    note = v.opt_str(body, "decision_note")
    merchant = v.get_merchant(merchant_id)
    # Band 6 — the governing trade rule must exist before a trade-specific
    # program rule (the licence seasoning gate) is applied.
    rule = v.get_trade_rule(merchant["trade_type"]) if decision == "APPROVE" else None
    # Band 14 — a decision is only admissible from PENDING_REVIEW.
    if merchant["enrollment_status"] != "PENDING_REVIEW":
        fail("ERR_INVALID_MERCHANT_STATE",
             "A merchant in %s carries no pending review."
             % merchant["enrollment_status"])
    if decision == "APPROVE":
        today = db.today()
        covering = [lic for lic in db.ordered(db.licenses)
                    if lic["merchant_id"] == merchant_id
                    and lic["verification_status"] == "VERIFIED"
                    and lic["trade_type"] == merchant["trade_type"]
                    and lic["state_code"] == merchant["state_code"]
                    and calc.license_covers(lic, today)]
        # Band 24
        if not covering:
            fail("ERR_LICENSE_NOT_VERIFIED",
                 "No verified licence covers this merchant's trade and state.")
        # Band 25
        seasoned = [lic for lic in covering
                    if calc.months_of_coverage_left(lic, today)
                    >= rule["min_license_months"]]
        if not seasoned:
            fail("ERR_LICENSE_COVERAGE_INSUFFICIENT",
                 "The covering licence has less than %d whole months left."
                 % rule["min_license_months"])
        merchant["enrollment_status"] = "APPROVED"
        merchant["approved_by_user_id"] = ctx.user_id
        merchant["approved_on"] = db.now()
    elif decision == "DECLINE":
        merchant["enrollment_status"] = "DECLINED"
    else:
        merchant["enrollment_status"] = "DOCS_REQUIRED"
    merchant["_decision_note"] = note
    ops.bump(merchant)
    return ok(ser.merchant(merchant))


@bp.post("/merchants/<merchant_id>/program-action")
def program_action(merchant_id):
    ctx = v.authorize(("ProgramAdmin",))
    body = v.read_body(ctx)
    action = v.req_enum(body, "action", ("SUSPEND", "REINSTATE", "TERMINATE"))
    reason_code = v.opt_str(body, "reason_code")
    merchant = v.get_merchant(merchant_id)
    status = merchant["enrollment_status"]
    # Band 14 — posture admission.
    if action == "SUSPEND" and status != "APPROVED":
        fail("ERR_INVALID_MERCHANT_STATE",
             "Only an approved merchant may be suspended.")
    if action == "REINSTATE" and status != "SUSPENDED":
        fail("ERR_INVALID_MERCHANT_STATE",
             "Only a suspended merchant may be reinstated.")
    if action == "TERMINATE" and status not in ("APPROVED", "SUSPENDED"):
        fail("ERR_INVALID_MERCHANT_STATE",
             "Only an approved or suspended merchant may be terminated.")
    if action == "SUSPEND":
        ops.suspend_merchant(merchant, reason_code or "ANALYST_ACTION")
    elif action == "REINSTATE":
        if calc.reserve_coverage_bps(merchant) < calc.RESERVE_SUSPENSION_BPS:
            fail("ERR_INVALID_MERCHANT_STATE",
                 "Reserve coverage is below five thousand basis points.")
        if any(a["status"] == "OPEN" for a in calc.merchant_alerts(merchant_id)):
            fail("ERR_INVALID_MERCHANT_STATE",
                 "An open fraud alert blocks reinstatement.")
        merchant["enrollment_status"] = "APPROVED"
        merchant["suspension_reason_code"] = None
        ops.bump(merchant)
        ops.cascade_reinstate(merchant)
    else:
        if not calc.termination_recommended(merchant_id):
            fail("ERR_INVALID_MERCHANT_STATE",
                 "Termination is not recommended for this merchant.")
        merchant["enrollment_status"] = "TERMINATED"
        merchant["termination_reason_code"] = reason_code
        ops.bump(merchant)
        ops.cascade_terminate(merchant)
    return ok(ser.merchant(merchant))


# =============================================================================
# Promotion enrollments (PRD 3.3)
# =============================================================================
@bp.post("/merchants/<merchant_id>/promotion-enrollments")
def create_enrollment(merchant_id):
    ctx = v.authorize(("ProgramUnderwriter", "ProgramAdmin"))
    body = v.read_body(ctx)
    plan_id = v.req_str(body, "promotion_plan_id")
    window_start = v.req_date(body, "window_start_date")
    window_end = v.req_date(body, "window_end_date")
    negotiated = v.opt_money(body, "negotiated_discount_bps")
    # Band 4 — the window is closed, so equal dates are a legal one-day window.
    if window_start > window_end:
        fail("ERR_INVALID_DATE_RANGE",
             "window_start_date must not be later than window_end_date.")
    merchant = v.get_merchant(merchant_id)
    plan = v.get_plan(plan_id)
    # Band 14 — funding-side writes require an approved merchant.
    if merchant["enrollment_status"] != "APPROVED":
        fail("ERR_INVALID_MERCHANT_STATE",
             "Only an approved merchant may be enrolled in a promotion.")
    # Band 30
    if merchant["trade_type"] not in plan["allowed_trade_types"]:
        fail("ERR_TRADE_NOT_ELIGIBLE",
             "Trade %s is not eligible for plan %s."
             % (merchant["trade_type"], plan["code"]))
    # Band 36 — closed windows conflict even when they merely touch.
    new_start = calc.parse_date(window_start)
    new_end = calc.parse_date(window_end)
    for other in db.ordered(db.enrollments):
        if other["merchant_id"] != merchant_id:
            continue
        if other["promotion_plan_id"] != plan_id:
            continue
        if other["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        other_start = calc.parse_date(other["window_start_date"])
        other_end = calc.parse_date(other["window_end_date"])
        if new_start <= other_end and other_start <= new_end:
            fail("ERR_ENROLLMENT_WINDOW_OVERLAP",
                 "The window overlaps enrollment %s." % other["id"])
    # Band 43
    approved_on = merchant["approved_on"]
    if approved_on is not None and new_start < approved_on.date():
        fail("ERR_ENROLLMENT_WINDOW_BEFORE_APPROVAL",
             "The window may not begin before the merchant was approved.")
    rec = db.new_record()
    rec.update({
        "merchant_id": merchant["id"],
        "promotion_plan_id": plan_id,
        "window_start_date": window_start,
        "window_end_date": window_end,
        "negotiated_discount_bps": negotiated,
        "status": "ACTIVE",
    })
    db.enrollments[rec["id"]] = rec
    return created(ser.enrollment(rec))


def _enrollment_rows(merchant_id=None):
    plan_id = v.filter_arg("promotion_plan_id")
    status = v.filter_arg("status")
    scoped_merchant = v.filter_arg("merchant_id")
    rows = []
    for rec in db.ordered(db.enrollments):
        if merchant_id is not None and rec["merchant_id"] != merchant_id:
            continue
        if scoped_merchant is not None and rec["merchant_id"] != scoped_merchant:
            continue
        if plan_id is not None and rec["promotion_plan_id"] != plan_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        rows.append(rec)
    return rows


@bp.get("/merchants/<merchant_id>/promotion-enrollments")
def list_merchant_enrollments(merchant_id):
    ctx = v.authorize(MERCHANT_READ_ROLES)
    v.get_merchant(merchant_id)
    v.resolve_identity(ctx, MERCHANT_READ_ROLES)
    v.merchant_scope(ctx, merchant_id)
    limit, offset = v.pagination()
    rows = _enrollment_rows(merchant_id)
    page = v.paginate(rows, limit, offset)
    return listing([ser.enrollment(r) for r in page], limit, offset, len(rows))


@bp.get("/promotion-enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    ctx = v.authorize(MERCHANT_READ_ROLES)
    rec = v.get_enrollment(enrollment_id)
    v.resolve_identity(ctx, MERCHANT_READ_ROLES)
    v.merchant_scope(ctx, rec["merchant_id"])
    return ok(ser.enrollment(rec))


@bp.get("/promotion-enrollments")
def list_enrollments():
    v.authorize(("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                 "ServicingAgent"))
    limit, offset = v.pagination()
    rows = _enrollment_rows()
    page = v.paginate(rows, limit, offset)
    return listing([ser.enrollment(r) for r in page], limit, offset, len(rows))


# =============================================================================
# Holdback reserve adjustments (PRD 3.8)
# =============================================================================
@bp.post("/merchants/<merchant_id>/holdback-adjustments")
def adjust_holdback(merchant_id):
    ctx = v.authorize(("ServicingAgent",))
    body = v.read_body(ctx)
    adjustment_type = v.req_enum(body, "adjustment_type", ("DEPOSIT", "RELEASE"))
    amount = v.req_money(body, "amount_cents")
    v.opt_str(body, "reason_code")
    expected = v.req_int(body, "expected_merchant_version")
    merchant = v.get_merchant(merchant_id)
    # Band 12 — optimistic concurrency on the merchant record.
    if expected != merchant["version"]:
        fail("ERR_STALE_MERCHANT_VERSION",
             "The merchant record has moved on since it was read.")
    # Band 52
    if adjustment_type == "RELEASE" and amount > merchant["holdback_reserve_cents"]:
        fail("ERR_RESERVE_RELEASE_EXCEEDS_BALANCE",
             "A release may not exceed the reserve balance.")
    if adjustment_type == "DEPOSIT":
        merchant["holdback_reserve_cents"] += amount
    else:
        merchant["holdback_reserve_cents"] -= amount
    ops.bump(merchant)
    return ok(ser.merchant(merchant))


# =============================================================================
# Fraud alerts and investigation (PRD 3.11)
# =============================================================================
ALERT_TYPES = ("PHANTOM_PROJECT", "PRE_COMPLETION_FULL_DRAW", "VELOCITY_SPIKE",
               "DUPLICATE_CONSUMER")


@bp.post("/merchants/<merchant_id>/fraud-alerts")
def raise_alert(merchant_id):
    ctx = v.authorize(("RiskAnalyst",))
    body = v.read_body(ctx)
    alert_type = v.req_enum(body, "alert_type", ALERT_TYPES)
    severity = v.req_int(body, "severity_weight", minimum=1, maximum=100)
    evidence_ref = v.opt_str(body, "evidence_ref")
    merchant = v.get_merchant(merchant_id)
    rec = db.new_record()
    rec.update({
        "merchant_id": merchant["id"],
        "alert_type": alert_type,
        "severity_weight": severity,
        "source": "ANALYST",
        "status": "OPEN",
        "evidence_ref": evidence_ref,
        "opened_on": calc.fmt_date(db.today()),
        "investigated_by_user_id": None,
        "investigation_note": None,
    })
    db.alerts[rec["id"]] = rec
    # Creation recomputes the merchant's fraud figures and bumps its version.
    ops.bump(merchant)
    return created(ser.fraud_alert(rec))


@bp.get("/merchants/<merchant_id>/fraud-alerts")
def list_alerts(merchant_id):
    v.authorize(("ProgramAdmin", "ProgramUnderwriter", "RiskAnalyst",
                 "ServicingAgent"))
    v.get_merchant(merchant_id)
    limit, offset = v.pagination()
    status = v.filter_arg("status")
    alert_type = v.filter_arg("alert_type")
    source = v.filter_arg("source")
    rows = []
    for rec in calc.merchant_alerts(merchant_id):
        if status is not None and rec["status"] != status:
            continue
        if alert_type is not None and rec["alert_type"] != alert_type:
            continue
        if source is not None and rec["source"] != source:
            continue
        rows.append(rec)
    page = v.paginate(rows, limit, offset)
    return listing([ser.fraud_alert(r) for r in page], limit, offset, len(rows))


@bp.post("/merchants/<merchant_id>/fraud-alerts/<alert_id>/investigation")
def investigate_alert(merchant_id, alert_id):
    ctx = v.authorize(("RiskAnalyst",))
    body = v.read_body(ctx)
    outcome = v.req_enum(body, "outcome", ("CONFIRMED", "CLEARED"))
    note = v.opt_str(body, "investigation_note")
    merchant = v.get_merchant(merchant_id)
    alert = v.get_alert(merchant_id, alert_id)
    # Band 10 — the closing analyst may not be the approving underwriter.
    if (merchant["approved_by_user_id"] is not None
            and ctx.user_id == merchant["approved_by_user_id"]):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The approving operator may not close this merchant's alerts.")
    # Band 22
    if alert["status"] != "OPEN":
        fail("ERR_INVALID_ALERT_STATE", "Alert %s is no longer open." % alert_id)
    alert["status"] = outcome
    alert["investigated_by_user_id"] = ctx.user_id
    alert["investigation_note"] = note
    ops.bump(alert)
    ops.bump(merchant)
    if outcome == "CONFIRMED":
        if (calc.phantom_risk_score(merchant_id) >= calc.FRAUD_SUSPENSION_SCORE
                and merchant["enrollment_status"] == "APPROVED"):
            ops.suspend_merchant(merchant, "FRAUD_CONFIRMED")
    else:
        calc.recompute_holdback_target(merchant)
    return ok(ser.fraud_alert(alert))
