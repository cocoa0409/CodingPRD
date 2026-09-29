"""Statutory regime, licences, counterparties and the logical clock."""

import re
from datetime import datetime, timezone

from flask import Blueprint, g, request

from core import (body, clock, db, fail, fmt_dt, new_record, ok, ok_list,
                  opt_bool, opt_enum, opt_int, opt_str, paginate, req_date,
                  req_enum, req_int, req_state_code, req_str, touch, endpoint)
from model import (get_license, get_state_rule, get_agent, licenses_of_rule,
                   ser_agent, ser_insured, ser_insurer, ser_license,
                   ser_state_rule)

bp = Blueprint("admin", __name__)

FINANCE_CHARGE_METHODS = ("ADD_ON", "SIMPLE_INTEREST")
UNEARNED_METHODS = ("PRO_RATA", "SHORT_RATE")
REBATE_METHODS = ("RULE_OF_78", "ACTUARIAL")
CHARGEBACK_BASES = ("COMMISSION_CAPPED", "RESERVE_CAPPED")


@bp.route("/state-rate-rules", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def create_state_rule():
    data = body()
    state_code = req_state_code(data, "state_code")
    method = req_enum(data, "finance_charge_method", FINANCE_CHARGE_METHODS)
    max_rate = req_int(data, "max_annual_rate_bps", 1, 3000)
    max_fee = req_int(data, "max_service_fee_cents", 0)
    min_down = req_int(data, "min_down_payment_bps", 0, 10000)
    max_term = req_int(data, "max_term_months", 2, 36)
    late_bps = req_int(data, "late_fee_bps", 0, 2000)
    late_min = req_int(data, "late_fee_min_cents", 0)
    late_max = req_int(data, "late_fee_max_cents", 0)
    if late_max < late_min:
        fail("ERR_INVALID_REQUEST",
             "late_fee_max_cents may not be smaller than late_fee_min_cents")
    grace = req_int(data, "grace_period_days", 0, 30)
    notice_days = req_int(data, "noic_notice_days", 5, 30)
    unearned = req_enum(data, "unearned_premium_method", UNEARNED_METHODS)
    penalty = req_int(data, "short_rate_penalty_bps", 0, 5000)
    rebate = req_enum(data, "rebate_method", REBATE_METHODS)
    max_fees = req_int(data, "max_late_fees_per_agreement", 1, 12)
    license_required = opt_bool(data, "license_required", True)
    for existing in db.state_rules.values():
        if existing["state_code"] == state_code:
            fail("ERR_DUPLICATE_STATE_RULE",
                 "a rate regime for state %s already exists" % state_code)
    rec = new_record(
        "state_rules",
        state_code=state_code,
        finance_charge_method=method,
        max_annual_rate_bps=max_rate,
        max_service_fee_cents=max_fee,
        min_down_payment_bps=min_down,
        max_term_months=max_term,
        late_fee_bps=late_bps,
        late_fee_min_cents=late_min,
        late_fee_max_cents=late_max,
        grace_period_days=grace,
        noic_notice_days=notice_days,
        unearned_premium_method=unearned,
        short_rate_penalty_bps=penalty,
        rebate_method=rebate,
        max_late_fees_per_agreement=max_fees,
        license_required=license_required,
    )
    return ok(ser_state_rule(rec), 201)


@bp.route("/state-rate-rules/<rule_id>", methods=["GET"])
@endpoint(("ComplianceOfficer", "FinanceAnalyst"))
def read_state_rule(rule_id):
    return ok(ser_state_rule(get_state_rule(rule_id)))


@bp.route("/state-rate-rules/<rule_id>/licenses", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def create_license(rule_id):
    rule = get_state_rule(rule_id)
    data = body()
    number = req_str(data, "license_number")
    effective = req_date(data, "effective_date")
    expiration = req_date(data, "expiration_date")
    if expiration <= effective:
        fail("ERR_INVALID_REQUEST",
             "expiration_date must be strictly after effective_date")
    for existing in licenses_of_rule(rule["id"]):
        if existing["license_number"] == number:
            fail("ERR_INVALID_REQUEST",
                 "license_number %s already exists for this state regime" % number)
    rec = new_record(
        "licenses",
        state_rule_id=rule["id"],
        license_number=number,
        status="ACTIVE",
        effective_date=effective.isoformat(),
        expiration_date=expiration.isoformat(),
    )
    return ok(ser_license(rec), 201)


@bp.route("/state-rate-rules/<rule_id>/licenses", methods=["GET"])
@endpoint(("ComplianceOfficer", "FinanceAnalyst"))
def list_licenses(rule_id):
    rule = get_state_rule(rule_id)
    rows = licenses_of_rule(rule["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, page = paginate(rows, ser_license)
    return ok_list(items, page)


@bp.route("/licenses/<license_id>/suspend", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def suspend_license(license_id):
    lic = get_license(license_id)
    if lic["status"] != "ACTIVE":
        fail("ERR_INVALID_REQUEST", "license is already SUSPENDED")
    lic["status"] = "SUSPENDED"
    touch(lic)
    return ok(ser_license(lic))


@bp.route("/insureds", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def create_insured():
    data = body()
    legal_name = req_str(data, "legal_name")
    state_code = req_state_code(data, "mailing_state_code")
    email = req_str(data, "email")
    if "@" not in email:
        fail("ERR_INVALID_REQUEST", "email must contain an at-sign")
    rec = new_record("insureds", legal_name=legal_name,
                     mailing_state_code=state_code, email=email)
    return ok(ser_insured(rec), 201)


@bp.route("/agents", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def create_agent():
    data = body()
    agency_name = req_str(data, "agency_name")
    state_code = req_state_code(data, "state_code")
    commission = req_int(data, "agent_commission_bps", 0, 3000)
    basis = req_enum(data, "chargeback_basis", CHARGEBACK_BASES)
    cap = req_int(data, "chargeback_liability_cap_cents", 0)
    reserve = req_int(data, "initial_reserve_balance_cents", 0)
    rec = new_record(
        "agents",
        agency_name=agency_name,
        state_code=state_code,
        agent_commission_bps=commission,
        chargeback_basis=basis,
        chargeback_liability_cap_cents=cap,
        chargeback_reserve_balance_cents=reserve,
        status="ACTIVE",
    )
    return ok(ser_agent(rec), 201)


@bp.route("/agents/<agent_id>", methods=["GET"])
@endpoint(("ComplianceOfficer", "FinanceAnalyst", "ProducerAgent"))
def read_agent(agent_id):
    return ok(ser_agent(get_agent(agent_id)))


@bp.route("/agents/<agent_id>/suspend", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def suspend_agent(agent_id):
    agent = get_agent(agent_id)
    data = body()
    opt_str(data, "reason")
    if agent["status"] != "ACTIVE":
        fail("ERR_INVALID_REQUEST",
             "producing agency is already %s" % agent["status"])
    agent["status"] = "SUSPENDED_BY_COMPLIANCE"
    touch(agent)
    return ok(ser_agent(agent))


@bp.route("/insurers", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def create_insurer():
    data = body()
    carrier_name = req_str(data, "carrier_name")
    naic_code = req_str(data, "naic_code")
    status = opt_enum(data, "status", ("ACTIVE", "INACTIVE"), "ACTIVE")
    for existing in db.insurers.values():
        if existing["naic_code"] == naic_code:
            fail("ERR_INVALID_REQUEST",
                 "naic_code %s is already registered" % naic_code)
    rec = new_record("insurers", carrier_name=carrier_name,
                     naic_code=naic_code, status=status)
    return ok(ser_insurer(rec), 201)


ISO_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$")


def parse_instant(value):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")
    match = ISO_INSTANT_RE.match(value.strip())
    if not match:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")
    year, month, day, hour, minute = (int(match.group(i)) for i in range(1, 6))
    second = int(match.group(6) or 0)
    fraction = match.group(7) or ""
    micro = int((fraction + "000000")[:6]) if fraction else 0
    offset = match.group(8)
    tzinfo = timezone.utc
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        from datetime import timedelta
        tzinfo = timezone(sign * timedelta(hours=int(digits[:2]),
                                          minutes=int(digits[2:4])))
    try:
        return datetime(year, month, day, hour, minute, second, micro,
                        tzinfo=tzinfo).astimezone(timezone.utc)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "to_iso8601 is not a valid instant")


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(("ComplianceOfficer", "FinanceAnalyst"))
def set_clock():
    data = body()
    if "to_iso8601" not in data or data["to_iso8601"] is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 is required")
    target = parse_instant(data["to_iso8601"])
    if target < clock.now():
        fail("ERR_CLOCK_REWIND", "the logical clock may not move backwards")
    clock.value = target
    return ok({"current_utc": fmt_dt(target)})
