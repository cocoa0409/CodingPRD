"""Origination, verification, activation, voiding and payoff quotes."""

from flask import Blueprint, g, request

from calc import (cut_schedule, payoff_figures, price_agreement)
from core import (body, clock, db, fail, new_record, ok, ok_list, opt_bool,
                  opt_int, opt_str, paginate, parse_date, req_date, req_enum,
                  req_int, req_str, touch, endpoint)
from gates import (require_agent_active, require_down_payment,
                   require_first_due_window, require_licensed,
                   require_policy_status, require_service_fee_within_cap,
                   require_status, require_term_within_maximum,
                   service_fee_ceiling, PREMIUM_VARIANCE_TOLERANCE_BPS)
from model import (get_agent, get_agreement, get_insured, get_insurer,
                   get_policy, get_state_rule, installments_of_agreement,
                   policies_of_agreement, rule_of_agreement, ser_agreement,
                   ser_installment, ser_policy, ser_verification,
                   verifications_of_policy)

bp = Blueprint("agreements", __name__)

MAX_POLICY_TERM_DAYS = 730
AGREEMENT_STATUSES = ("DRAFT", "PENDING_VERIFICATION", "ACTIVE", "PAID_IN_FULL",
                      "RESTRUCTURED", "CANCELLED_DEFICIENT", "CLOSED_ZERO", "VOID")
DELINQUENCY_STAGES = ("CURRENT", "LATE", "NOIC_ISSUED",
                      "CANCELLATION_REQUESTED", "CANCELLED")


def _require_fk(data, key):
    if key not in data or data[key] is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a string identifier" % key)
    return value


def own_agreement(agreement):
    if g.role == "Insured" and agreement["insured_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "caller does not own this agreement")
    if g.role == "ProducerAgent" and agreement["producer_agent_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "caller does not own this agreement")


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------

def blank_agreement_fields():
    return dict(
        restructured_from_agreement_id=None,
        status="DRAFT",
        delinquency_stage="CURRENT",
        rate_exception_approved=False,
        rate_exception_approved_by_user_id=None,
        approved_service_fee_cap_cents=None,
        approved_annual_rate_bps=None,
        total_premium_cents=0,
        amount_financed_cents=0,
        effective_annual_rate_bps=0,
        finance_charge_cents=0,
        total_of_payments_cents=0,
        quote_basis=None,
        principal_balance_cents=0,
        unpaid_finance_charge_cents=0,
        late_fee_balance_cents=0,
        late_fee_count=0,
        unapplied_credit_cents=0,
        unearned_premium_received_cents=0,
        deficiency_balance_cents=0,
        refund_due_cents=0,
        agent_chargeback_cents=0,
        carried_over_balance_cents=0,
        activated_at=None,
    )


@bp.route("/agreements", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def create_agreement():
    data = body()
    insured = get_insured(_require_fk(data, "insured_id"))
    agent = get_agent(_require_fk(data, "producer_agent_id"))
    rule = get_state_rule(_require_fk(data, "state_rule_id"))
    down_payment = req_int(data, "down_payment_cents", 0)
    service_fee = req_int(data, "service_fee_cents", 0)
    count = req_int(data, "installment_count", 2)
    first_due = req_date(data, "first_installment_due_date")
    require_licensed(rule)
    require_agent_active(agent)
    require_term_within_maximum(count, rule)
    if service_fee > rule["max_service_fee_cents"]:
        fail("ERR_SERVICE_FEE_ABOVE_CAP",
             "service_fee_cents %s exceeds max_service_fee_cents %s"
             % (service_fee, rule["max_service_fee_cents"]))
    require_first_due_window(first_due)
    fields = blank_agreement_fields()
    fields.update(
        insured_id=insured["id"],
        producer_agent_id=agent["id"],
        state_rule_id=rule["id"],
        originated_by_user_id=g.user_id,
        down_payment_cents=down_payment,
        service_fee_cents=service_fee,
        installment_count=count,
        first_installment_due_date=first_due.isoformat(),
    )
    rec = new_record("agreements", **fields)
    return ok(ser_agreement(rec), 201)


@bp.route("/agreements/<agreement_id>", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insured", "ProducerAgent"))
def read_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    own_agreement(agreement)
    return ok(ser_agreement(agreement))


@bp.route("/agreements", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer"))
def list_agreements():
    from core import ordered
    rows = ordered(list(db.agreements.values()))
    args = request.args
    for key in ("insured_id", "producer_agent_id", "state_rule_id",
                "restructured_from_agreement_id", "status", "delinquency_stage"):
        value = args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, page = paginate(rows, ser_agreement)
    return ok_list(items, page)


# ---------------------------------------------------------------------------
# Financed policies
# ---------------------------------------------------------------------------

@bp.route("/agreements/<agreement_id>/policies", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def attach_policy(agreement_id):
    agreement = get_agreement(agreement_id)
    data = body()
    insurer = get_insurer(_require_fk(data, "insurer_id"))
    policy_number = req_str(data, "policy_number")
    gross = req_int(data, "gross_premium_cents", 1)
    effective = req_date(data, "effective_date")
    expiration = req_date(data, "expiration_date")
    min_earned = opt_int(data, "min_earned_days", 0, 0)
    fully_earned = opt_bool(data, "fully_earned", False)
    require_status(agreement, ("DRAFT",))
    term_days = (expiration - effective).days
    if term_days <= 0 or term_days > MAX_POLICY_TERM_DAYS or min_earned > term_days:
        fail("ERR_INVALID_POLICY_TERM", "the policy term is not well formed")
    for other in db.policies.values():
        if other["status"] == "CANCELLED":
            continue
        if other["insurer_id"] != insurer["id"]:
            continue
        if other["policy_number"] != policy_number:
            continue
        other_start = parse_date(other["effective_date"], "effective_date")
        other_end = parse_date(other["expiration_date"], "expiration_date")
        if effective < other_end and other_start < expiration:
            fail("ERR_POLICY_TERM_OVERLAP",
                 "policy %s for this carrier already covers an overlapping term"
                 % policy_number)
    rec = new_record(
        "policies",
        agreement_id=agreement["id"],
        insurer_id=insurer["id"],
        policy_number=policy_number,
        gross_premium_cents=gross,
        effective_date=effective.isoformat(),
        expiration_date=expiration.isoformat(),
        min_earned_days=min_earned,
        fully_earned=fully_earned,
        carried_over=False,
        status="PENDING_VERIFICATION",
        verified_premium_cents=None,
        verified_effective_date=None,
        dispute_reason=None,
        financed_premium_cents=gross,
        cancellation_effective_date=None,
        earned_days=None,
        unearned_premium_estimate_cents=None,
        unearned_premium_returned_cents=0,
    )
    touch(agreement)
    return ok(ser_policy(rec), 201)


@bp.route("/policies/<policy_id>", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insurer", "ProducerAgent"))
def read_policy(policy_id):
    return ok(ser_policy(get_policy(policy_id)))


@bp.route("/policies", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insurer"))
def list_policies():
    from core import ordered
    rows = ordered(list(db.policies.values()))
    args = request.args
    for key in ("agreement_id", "insurer_id", "status"):
        value = args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, page = paginate(rows, ser_policy)
    return ok_list(items, page)


# ---------------------------------------------------------------------------
# Two-party verification
# ---------------------------------------------------------------------------

DECISIONS = ("CONFIRMED", "CORRECTED", "REJECTED")


def live_verifications(policy_id):
    return [v for v in verifications_of_policy(policy_id) if not v["superseded"]]


def _evaluate_pair(policy, agreement, rule):
    live = live_verifications(policy["id"])
    parties = set(v["party"] for v in live)
    if not {"INSURER", "PRODUCER_AGENT"}.issubset(parties):
        return
    insurer_rec = [v for v in live if v["party"] == "INSURER"][0]
    agent_rec = [v for v in live if v["party"] == "PRODUCER_AGENT"][0]
    rejected = any(v["decision"] == "REJECTED" for v in (insurer_rec, agent_rec))
    if not rejected:
        premiums_match = (insurer_rec["effective_premium_cents"]
                          == agent_rec["effective_premium_cents"])
        dates_match = (insurer_rec["effective_date_asserted"]
                       == agent_rec["effective_date_asserted"])
    else:
        premiums_match = dates_match = False
    if not rejected and premiums_match and dates_match:
        policy["status"] = "VERIFIED"
        policy["verified_premium_cents"] = insurer_rec["effective_premium_cents"]
        policy["verified_effective_date"] = insurer_rec["effective_date_asserted"]
        policy["dispute_reason"] = None
        from model import endorsed_premium_cents
        policy["financed_premium_cents"] = (policy["verified_premium_cents"]
                                            + endorsed_premium_cents(policy["id"]))
        touch(policy)
        return
    policy["status"] = "DISPUTED"
    if rejected:
        policy["dispute_reason"] = "PARTY_REJECTED"
    elif not premiums_match:
        policy["dispute_reason"] = "PREMIUM_MISMATCH"
    else:
        policy["dispute_reason"] = "EFFECTIVE_DATE_MISMATCH"
    policy["verified_premium_cents"] = None
    policy["verified_effective_date"] = None
    touch(policy)
    if agreement["status"] == "PENDING_VERIFICATION":
        agreement["status"] = "DRAFT"
        agreement["total_premium_cents"] = 0
        agreement["amount_financed_cents"] = 0
        agreement["effective_annual_rate_bps"] = 0
        agreement["finance_charge_cents"] = 0
        agreement["total_of_payments_cents"] = 0
        agreement["quote_basis"] = None
        touch(agreement)


@bp.route("/policies/<policy_id>/verifications", methods=["POST"])
@endpoint(("Insurer", "ProducerAgent"))
def file_verification(policy_id):
    policy = get_policy(policy_id)
    agreement = get_agreement(policy["agreement_id"])
    data = body()
    named_agreement = None
    if data.get("agreement_id") is not None:
        named_agreement = get_agreement(data["agreement_id"])
    if g.role == "Insurer":
        party = "INSURER"
        if policy["insurer_id"] != g.user_id:
            fail("ERR_VERIFIER_NOT_AUTHORIZED",
                 "caller has no standing to attest on this policy")
    else:
        party = "PRODUCER_AGENT"
        if agreement["producer_agent_id"] != g.user_id:
            fail("ERR_VERIFIER_NOT_AUTHORIZED",
                 "caller has no standing to attest on this policy")
    decision = req_enum(data, "decision", DECISIONS)
    note = opt_str(data, "note")
    corrected_premium = None
    corrected_date = None
    if decision == "CORRECTED":
        corrected_premium = req_int(data, "corrected_premium_cents", 1)
        corrected_date = req_date(data, "corrected_effective_date")
    else:
        if data.get("corrected_premium_cents") is not None:
            fail("ERR_INVALID_REQUEST",
                 "corrected_premium_cents is only permitted on a CORRECTED filing")
        if data.get("corrected_effective_date") is not None:
            fail("ERR_INVALID_REQUEST",
                 "corrected_effective_date is only permitted on a CORRECTED filing")
    require_policy_status(policy, ("PENDING_VERIFICATION",))
    if named_agreement is not None and named_agreement["id"] != policy["agreement_id"]:
        fail("ERR_POLICY_AGREEMENT_MISMATCH",
             "policy %s does not belong to agreement %s"
             % (policy["id"], named_agreement["id"]))
    for existing in live_verifications(policy["id"]):
        if existing["party"] == party:
            fail("ERR_VERIFICATION_ALREADY_RECORDED",
                 "this party already holds a live attestation on the policy")
    if decision == "CORRECTED":
        quoted = policy["gross_premium_cents"]
        if abs(corrected_premium - quoted) * 10000 > quoted * PREMIUM_VARIANCE_TOLERANCE_BPS:
            fail("ERR_PREMIUM_VARIANCE_EXCEEDED",
                 "corrected premium departs from the quote by more than %s bps"
                 % PREMIUM_VARIANCE_TOLERANCE_BPS)
    if decision == "CONFIRMED":
        effective_premium = policy["gross_premium_cents"]
        effective_date = policy["effective_date"]
    elif decision == "CORRECTED":
        effective_premium = corrected_premium
        effective_date = corrected_date.isoformat()
    else:
        effective_premium = None
        effective_date = None
    rec = new_record(
        "verifications",
        versioned=False,
        policy_id=policy["id"],
        party=party,
        party_user_id=g.user_id,
        decision=decision,
        corrected_premium_cents=corrected_premium,
        corrected_effective_date=(corrected_date.isoformat()
                                  if corrected_date else None),
        effective_premium_cents=effective_premium,
        effective_date_asserted=effective_date,
        note=note,
        superseded=False,
    )
    _evaluate_pair(policy, agreement, rule_of_agreement(agreement))
    return ok(ser_verification(rec), 201)


@bp.route("/policies/<policy_id>/verifications", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insurer", "ProducerAgent"))
def list_verifications(policy_id):
    policy = get_policy(policy_id)
    rows = verifications_of_policy(policy["id"])
    party = request.args.get("party")
    if party is not None:
        rows = [r for r in rows if r["party"] == party]
    items, page = paginate(rows, ser_verification)
    return ok_list(items, page)


@bp.route("/policies/<policy_id>/reopen-verification", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def reopen_verification(policy_id):
    policy = get_policy(policy_id)
    agreement = get_agreement(policy["agreement_id"])
    require_policy_status(policy, ("DISPUTED",))
    require_status(agreement, ("DRAFT", "PENDING_VERIFICATION"))
    for existing in verifications_of_policy(policy["id"]):
        existing["superseded"] = True
    policy["dispute_reason"] = None
    policy["status"] = "PENDING_VERIFICATION"
    touch(policy)
    return ok(ser_policy(policy))


# ---------------------------------------------------------------------------
# Submission, activation, voiding
# ---------------------------------------------------------------------------

def active_policies(agreement_id):
    return [p for p in policies_of_agreement(agreement_id)
            if p["status"] != "CANCELLED"]


@bp.route("/agreements/<agreement_id>/submit", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def submit_agreement(agreement_id):
    from calc import premium_basis
    agreement = get_agreement(agreement_id)
    rule = rule_of_agreement(agreement)
    agent = get_agent(agreement["producer_agent_id"])
    require_status(agreement, ("DRAFT",))
    for policy in active_policies(agreement["id"]):
        require_policy_status(policy, ("PENDING_VERIFICATION",))
    require_licensed(rule)
    require_agent_active(agent)
    count = agreement["installment_count"]
    if count < 2 or count > rule["max_term_months"]:
        fail("ERR_TERM_EXCEEDS_STATE_MAXIMUM",
             "installment_count %s is outside the statutory term range" % count)
    basis = premium_basis(agreement, "PROVISIONAL")
    require_down_payment(agreement["down_payment_cents"], basis, rule)
    require_service_fee_within_cap(agreement, rule)
    if not active_policies(agreement["id"]):
        fail("ERR_NO_FINANCED_POLICIES",
             "at least one policy must be financed before submission")
    require_first_due_window(
        parse_date(agreement["first_installment_due_date"],
                   "first_installment_due_date"))
    price_agreement(agreement, rule, "PROVISIONAL")
    agreement["status"] = "PENDING_VERIFICATION"
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.route("/agreements/<agreement_id>/activate", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def activate_agreement(agreement_id):
    from calc import premium_basis
    from model import policy_count, verified_policy_count
    agreement = get_agreement(agreement_id)
    rule = rule_of_agreement(agreement)
    require_status(agreement, ("PENDING_VERIFICATION",))
    require_licensed(rule)
    basis = premium_basis(agreement, "FINAL")
    require_down_payment(agreement["down_payment_cents"], basis, rule)
    require_service_fee_within_cap(agreement, rule)
    total = policy_count(agreement["id"])
    verified = verified_policy_count(agreement["id"])
    if total < 1 or verified != total:
        fail("ERR_POLICY_NOT_VERIFIED",
             "every attached policy must be verified before activation")
    price_agreement(agreement, rule, "FINAL")
    cut_schedule(agreement, rule,
                 parse_date(agreement["first_installment_due_date"],
                            "first_installment_due_date"))
    agreement["principal_balance_cents"] = agreement["amount_financed_cents"]
    agreement["unpaid_finance_charge_cents"] = agreement["finance_charge_cents"]
    agreement["activated_at"] = clock.now_iso()
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.route("/agreements/<agreement_id>/void", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def void_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    data = body()
    opt_str(data, "reason")
    require_status(agreement, ("DRAFT", "PENDING_VERIFICATION"))
    for payment in db.payments.values():
        if payment["agreement_id"] == agreement["id"]:
            fail("ERR_AGREEMENT_STATE_INVALID",
                 "a note carrying payments may not be voided")
    agreement["status"] = "VOID"
    for policy in policies_of_agreement(agreement["id"]):
        if policy["status"] != "CANCELLED":
            policy["status"] = "CANCELLED"
            policy["cancellation_effective_date"] = None
            touch(policy)
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.route("/agreements/<agreement_id>/installments", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insured"))
def list_installments(agreement_id):
    agreement = get_agreement(agreement_id)
    rows = installments_of_agreement(agreement["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, page = paginate(rows, ser_installment)
    return ok_list(items, page)


# ---------------------------------------------------------------------------
# Priced exceptions and payoff quotes
# ---------------------------------------------------------------------------

@bp.route("/agreements/<agreement_id>/rate-exception-approvals", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def approve_rate_exception(agreement_id):
    agreement = get_agreement(agreement_id)
    rule = rule_of_agreement(agreement)
    data = body()
    req_str(data, "justification")
    override_fee = opt_int(data, "override_service_fee_cents", None, 0)
    override_rate = opt_int(data, "override_annual_rate_bps", None, 0)
    if g.user_id == agreement["originated_by_user_id"]:
        fail("ERR_SOD_ORIGINATOR_CANNOT_APPROVE",
             "the originating analyst may not approve a priced exception")
    require_status(agreement, ("DRAFT", "PENDING_VERIFICATION"))
    if override_fee is not None and agreement["service_fee_cents"] > override_fee:
        fail("ERR_SERVICE_FEE_ABOVE_CAP",
             "service_fee_cents %s exceeds the approved cap %s"
             % (agreement["service_fee_cents"], override_fee))
    if override_rate is not None and override_rate > rule["max_annual_rate_bps"]:
        fail("ERR_RATE_ABOVE_STATE_MAXIMUM",
             "override_annual_rate_bps %s exceeds max_annual_rate_bps %s"
             % (override_rate, rule["max_annual_rate_bps"]))
    agreement["rate_exception_approved"] = True
    agreement["rate_exception_approved_by_user_id"] = g.user_id
    if override_fee is not None:
        agreement["approved_service_fee_cap_cents"] = override_fee
    if override_rate is not None:
        agreement["approved_annual_rate_bps"] = override_rate
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.route("/agreements/<agreement_id>/payoff-quote", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insured"))
def payoff_quote(agreement_id):
    agreement = get_agreement(agreement_id)
    rule = rule_of_agreement(agreement)
    raw = request.args.get("as_of_date")
    if raw is not None and raw != "":
        as_of = parse_date(raw, "as_of_date")
    else:
        as_of = clock.date()
    figures = payoff_figures(agreement, rule)
    payload = {"as_of_date": as_of.isoformat()}
    payload.update(figures)
    return ok(payload)
