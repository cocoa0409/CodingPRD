"""Payments, late fees, the servicing pass, statutory notices and the
power of attorney."""

from flask import Blueprint, g, request

from calc import (OVERPAYMENT_TOLERANCE_CENTS, allocate_payment, late_fee_amount,
                  payoff_figures, reverse_payment, settle_note,
                  unearned_finance_charge_rebate, unearned_premium_estimate)
from core import (add_days, body, clock, db, fail, new_record, ok, ok_list,
                  opt_str, ordered, paginate, parse_date, req_date, req_enum,
                  req_int, req_str, touch, endpoint)
from gates import (complete_if_paid_in_full, cure_delinquency, has_outstanding_fee,
                   has_past_due, require_stage, require_status)
from model import (get_agent, get_agreement, get_late_fee, get_payment,
                   installments_of_agreement, late_fees_of_agreement,
                   notices_of_agreement, policies_of_agreement,
                   rule_of_agreement, ser_late_fee, ser_notice, ser_payment)

bp = Blueprint("servicing", __name__)

PAYMENT_METHODS = ("ACH", "CHECK", "CARD")
REVERSAL_REASONS = ("NSF", "BANK_ERROR")


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@bp.route("/agreements/<agreement_id>/payments", methods=["POST"])
@endpoint(("FinanceAnalyst", "Insured"))
def post_payment(agreement_id):
    agreement = get_agreement(agreement_id)
    if g.role == "Insured" and agreement["insured_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "caller does not own this agreement")
    rule = rule_of_agreement(agreement)
    data = body()
    amount = req_int(data, "amount_cents", 1)
    received = req_date(data, "received_date")
    method = req_enum(data, "method", PAYMENT_METHODS)
    if received > clock.date():
        fail("ERR_INVALID_REQUEST", "received_date may not be later than the clock date")
    require_status(agreement, ("ACTIVE",))
    quote = payoff_figures(agreement, rule)
    if amount > quote["net_payoff_cents"] + OVERPAYMENT_TOLERANCE_CENTS:
        fail("ERR_PAYMENT_EXCEEDS_PAYOFF",
             "tendered amount exceeds the net payoff by more than %s cents"
             % OVERPAYMENT_TOLERANCE_CENTS)
    payment = new_record(
        "payments",
        agreement_id=agreement["id"],
        amount_cents=amount,
        received_date=received.isoformat(),
        method=method,
        status="POSTED",
        applied_late_fee_cents=0,
        applied_finance_charge_cents=0,
        applied_principal_cents=0,
        applied_unapplied_cents=0,
        rebate_applied_cents=0,
        allocation_variant=None,
        reversal_reason=None,
        reversed_at=None,
    )
    allocate_payment(agreement, rule, payment)
    cure_delinquency(agreement)
    complete_if_paid_in_full(agreement, payment)
    touch(agreement)
    return ok(ser_payment(payment), 201)


@bp.route("/agreements/<agreement_id>/payments", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insured"))
def list_payments(agreement_id):
    agreement = get_agreement(agreement_id)
    from model import payments_of_agreement
    rows = payments_of_agreement(agreement["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, page = paginate(rows, ser_payment)
    return ok_list(items, page)


@bp.route("/payments/<payment_id>/reverse", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def reverse(payment_id):
    payment = get_payment(payment_id)
    agreement = get_agreement(payment["agreement_id"])
    data = body()
    reason = req_enum(data, "reversal_reason", REVERSAL_REASONS)
    require_status(agreement, ("ACTIVE", "PAID_IN_FULL"))
    if payment["status"] != "POSTED":
        fail("ERR_PAYMENT_ALREADY_REVERSED", "this payment is already reversed")
    payment["status"] = "REVERSED"
    payment["reversal_reason"] = reason
    payment["reversed_at"] = clock.now_iso()
    reverse_payment(agreement, payment)
    if agreement["status"] == "PAID_IN_FULL":
        agreement["status"] = "ACTIVE"
    if agreement["status"] == "ACTIVE":
        if has_past_due(agreement["id"]) or agreement["late_fee_balance_cents"] > 0:
            if agreement["delinquency_stage"] == "CURRENT":
                agreement["delinquency_stage"] = "LATE"
    touch(payment)
    touch(agreement)
    return ok(ser_payment(payment))


# ---------------------------------------------------------------------------
# Late fees and the servicing pass
# ---------------------------------------------------------------------------

@bp.route("/agreements/<agreement_id>/late-fees", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insured"))
def list_late_fees(agreement_id):
    agreement = get_agreement(agreement_id)
    rows = late_fees_of_agreement(agreement["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, page = paginate(rows, ser_late_fee)
    return ok_list(items, page)


@bp.route("/late-fees/<fee_id>/waive", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def waive_late_fee(fee_id):
    fee = get_late_fee(fee_id)
    agreement = get_agreement(fee["agreement_id"])
    data = body()
    req_str(data, "justification")
    if fee["status"] != "OUTSTANDING":
        fail("ERR_LATE_FEE_NOT_OUTSTANDING",
             "a late fee in %s status may not be waived" % fee["status"])
    fee["status"] = "WAIVED"
    fee["waived_by_user_id"] = g.user_id
    agreement["late_fee_balance_cents"] -= fee["amount_cents"]
    touch(fee)
    cure_delinquency(agreement)
    touch(agreement)
    return ok(ser_late_fee(fee))


@bp.route("/servicing-runs", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def servicing_run():
    today = clock.date()
    past_due_marked = 0
    late_fees_assessed = 0
    advanced = 0
    for agreement in ordered(list(db.agreements.values())):
        if agreement["status"] != "ACTIVE":
            continue
        if agreement["delinquency_stage"] not in ("CURRENT", "LATE", "NOIC_ISSUED"):
            continue
        rule = rule_of_agreement(agreement)
        newly_past_due = False
        for row in installments_of_agreement(agreement["id"]):
            if row["status"] in ("PAID", "VOIDED"):
                continue
            due = parse_date(row["due_date"], "due_date")
            if (row["status"] == "SCHEDULED" and due < today
                    and row["paid_cents"] < row["amount_cents"]):
                row["status"] = "PAST_DUE"
                touch(row)
                past_due_marked += 1
                newly_past_due = True
            if row["status"] != "PAST_DUE":
                continue
            if today <= add_days(due, rule["grace_period_days"]):
                continue
            if agreement["late_fee_count"] >= rule["max_late_fees_per_agreement"]:
                continue
            blocked = False
            for fee in late_fees_of_agreement(agreement["id"]):
                if (fee["installment_number"] == row["installment_number"]
                        and fee["status"] != "REVERSED"):
                    blocked = True
                    break
            if blocked:
                continue
            amount = late_fee_amount(row, rule)
            new_record(
                "late_fees",
                agreement_id=agreement["id"],
                installment_number=row["installment_number"],
                assessed_date=today.isoformat(),
                amount_cents=amount,
                status="OUTSTANDING",
                waived_by_user_id=None,
            )
            agreement["late_fee_count"] += 1
            agreement["late_fee_balance_cents"] += amount
            late_fees_assessed += 1
            touch(agreement)
        if newly_past_due and agreement["delinquency_stage"] == "CURRENT":
            agreement["delinquency_stage"] = "LATE"
            advanced += 1
            touch(agreement)
    return ok({
        "past_due_marked": past_due_marked,
        "late_fees_assessed": late_fees_assessed,
        "agreements_advanced_to_late": advanced,
    })


# ---------------------------------------------------------------------------
# Notice of intent to cancel
# ---------------------------------------------------------------------------

@bp.route("/agreements/<agreement_id>/cancellation-notices", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def issue_notice(agreement_id):
    agreement = get_agreement(agreement_id)
    rule = rule_of_agreement(agreement)
    require_status(agreement, ("ACTIVE",))
    require_stage(agreement, ("LATE", "NOIC_ISSUED"))
    if not has_outstanding_fee(agreement["id"]):
        fail("ERR_DELINQUENCY_STATE_INVALID",
             "no outstanding late fee justifies a notice of intent to cancel")
    notices = notices_of_agreement(agreement["id"])
    for notice in notices:
        if notice["status"] == "ISSUED":
            fail("ERR_NOTICE_WINDOW_OPEN",
                 "a notice of intent to cancel is already open on this note")
    cured = [n for n in notices if n["status"] == "CURED" and n["cured_date"]]
    if cured:
        latest = cured[-1]
        blackout_end = add_days(parse_date(latest["cured_date"], "cured_date"),
                                rule["noic_notice_days"])
        if blackout_end >= clock.date():
            fail("ERR_NOTICE_BLACKOUT_ACTIVE",
                 "the post-cure blackout window is still running")
    today = clock.date()
    notice_days = rule["noic_notice_days"]
    past_due_amount = sum(r["amount_cents"] - r["paid_cents"]
                          for r in installments_of_agreement(agreement["id"])
                          if r["status"] == "PAST_DUE")
    past_due_amount += agreement["late_fee_balance_cents"]
    rec = new_record(
        "notices",
        agreement_id=agreement["id"],
        issued_date=today.isoformat(),
        issued_by_user_id=g.user_id,
        notice_days=notice_days,
        effective_cancel_date=add_days(today, notice_days).isoformat(),
        past_due_amount_cents=past_due_amount,
        status="ISSUED",
        cured_date=None,
        executed_date=None,
    )
    agreement["delinquency_stage"] = "NOIC_ISSUED"
    touch(agreement)
    return ok(ser_notice(rec), 201)


@bp.route("/agreements/<agreement_id>/cancellation-notices", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insured"))
def list_notices(agreement_id):
    agreement = get_agreement(agreement_id)
    rows = notices_of_agreement(agreement["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, page = paginate(rows, ser_notice)
    return ok_list(items, page)


@bp.route("/agreements/<agreement_id>/cancellation-executions", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def execute_cancellation(agreement_id):
    agreement = get_agreement(agreement_id)
    rule = rule_of_agreement(agreement)
    notices = notices_of_agreement(agreement["id"])
    issued = [n for n in notices if n["status"] == "ISSUED"]
    candidate = issued[-1] if issued else (notices[-1] if notices else None)
    if candidate is not None and candidate["status"] == "ISSUED":
        if g.user_id == candidate["issued_by_user_id"]:
            fail("ERR_SOD_NOTICE_ISSUER_CANNOT_EXECUTE",
                 "the analyst who issued the notice may not execute it")
    require_status(agreement, ("ACTIVE",))
    require_stage(agreement, ("NOIC_ISSUED",))
    if candidate is None or candidate["status"] != "ISSUED":
        fail("ERR_NOTICE_STATE_INVALID",
             "no notice of intent to cancel is available for execution")
    cancel_date = parse_date(candidate["effective_cancel_date"],
                             "effective_cancel_date")
    if clock.date() < cancel_date:
        fail("ERR_NOTICE_PERIOD_NOT_ELAPSED",
             "the statutory notice period has not elapsed")
    verified = [p for p in policies_of_agreement(agreement["id"])
                if p["status"] == "VERIFIED"]
    if not verified:
        fail("ERR_POLICY_NOT_VERIFIED", "no verified policy remains to cancel")
    today = clock.date()
    candidate["status"] = "EXECUTED"
    candidate["executed_date"] = today.isoformat()
    touch(candidate)
    estimated_total = 0
    requests_created = 0
    for policy in verified:
        earned, estimate = unearned_premium_estimate(policy, rule, cancel_date)
        policy["status"] = "CANCELLED"
        policy["cancellation_effective_date"] = cancel_date.isoformat()
        policy["earned_days"] = earned
        policy["unearned_premium_estimate_cents"] = estimate
        touch(policy)
        new_record(
            "cancel_requests",
            agreement_id=agreement["id"],
            policy_id=policy["id"],
            requested_date=today.isoformat(),
            cancellation_effective_date=cancel_date.isoformat(),
            requested_by_user_id=g.user_id,
            computed_unearned_premium_cents=estimate,
            estimate_method=rule["unearned_premium_method"],
            carrier_returned_cents=None,
            variance_cents=None,
            status="REQUESTED",
        )
        estimated_total += estimate
        requests_created += 1
    rebate = unearned_finance_charge_rebate(agreement, rule)
    agreement["unpaid_finance_charge_cents"] -= rebate
    agreement.setdefault("_rebates_granted", 0)
    agreement["_rebates_granted"] += rebate
    for row in installments_of_agreement(agreement["id"]):
        if row["status"] == "SCHEDULED" and row["paid_cents"] == 0:
            row["status"] = "VOIDED"
            touch(row)
    agreement["delinquency_stage"] = "CANCELLATION_REQUESTED"
    touch(agreement)
    return ok({
        "requests_created": requests_created,
        "estimated_unearned_premium_cents": estimated_total,
        "rebate_applied_cents": rebate,
        "gross_balance_cents": (agreement["principal_balance_cents"]
                                + agreement["unpaid_finance_charge_cents"]),
    })


# ---------------------------------------------------------------------------
# Carrier cancellation requests and the deficiency cascade
# ---------------------------------------------------------------------------

@bp.route("/carrier-cancellation-requests", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insurer"))
def list_cancel_requests():
    from model import get_policy, ser_cancel_request
    args = request.args
    agreement_id = args.get("agreement_id")
    policy_id = args.get("policy_id")
    if agreement_id is not None and policy_id is not None:
        policy = get_policy(policy_id)
        if policy["agreement_id"] != agreement_id:
            fail("ERR_POLICY_AGREEMENT_MISMATCH",
                 "policy %s does not belong to agreement %s"
                 % (policy_id, agreement_id))
    rows = ordered(list(db.cancel_requests.values()))
    for key in ("agreement_id", "policy_id", "status"):
        value = args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, page = paginate(rows, ser_cancel_request)
    return ok_list(items, page)


@bp.route("/carrier-cancellation-requests/<request_id>", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "Insurer"))
def read_cancel_request(request_id):
    from model import get_cancel_request, ser_cancel_request
    return ok(ser_cancel_request(get_cancel_request(request_id)))


@bp.route("/carrier-cancellation-requests/<request_id>/return-posting",
          methods=["POST"])
@endpoint(("Insurer",))
def post_return(request_id):
    from model import (cancel_requests_of_agreement, get_cancel_request,
                       get_policy, ser_cancel_request)
    record = get_cancel_request(request_id)
    policy = get_policy(record["policy_id"])
    agreement = get_agreement(record["agreement_id"])
    data = body()
    named_agreement = None
    if data.get("agreement_id") is not None:
        named_agreement = get_agreement(data["agreement_id"])
    if policy["insurer_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "caller does not own this policy")
    returned = req_int(data, "carrier_returned_cents", 0)
    req_date(data, "posted_date")
    if record["status"] != "REQUESTED":
        fail("ERR_CANCEL_REQUEST_STATE_INVALID",
             "a request in %s status accepts no return" % record["status"])
    if named_agreement is not None and named_agreement["id"] != policy["agreement_id"]:
        fail("ERR_POLICY_AGREEMENT_MISMATCH",
             "policy %s does not belong to agreement %s"
             % (policy["id"], named_agreement["id"]))
    record["variance_cents"] = returned - record["computed_unearned_premium_cents"]
    record["carrier_returned_cents"] = returned
    if returned > 0:
        record["status"] = "RETURN_POSTED"
        policy["unearned_premium_returned_cents"] = returned
        touch(policy)
        agreement["unearned_premium_received_cents"] += returned
        credit = returned
        take = min(credit, agreement["principal_balance_cents"])
        agreement["principal_balance_cents"] -= take
        credit -= take
        take = min(credit, agreement["unpaid_finance_charge_cents"])
        agreement["unpaid_finance_charge_cents"] -= take
        credit -= take
        take = min(credit, agreement["late_fee_balance_cents"])
        agreement["late_fee_balance_cents"] -= take
        credit -= take
        if credit > 0:
            agreement["unapplied_credit_cents"] += credit
        touch(agreement)
    else:
        record["status"] = "CLOSED_NO_RETURN"
    touch(record)
    siblings = cancel_requests_of_agreement(agreement["id"])
    if all(r["status"] in ("RETURN_POSTED", "CLOSED_NO_RETURN") for r in siblings):
        if agreement["status"] == "ACTIVE":
            agent = get_agent(agreement["producer_agent_id"])
            settle_note(agreement, rule_of_agreement(agreement), agent)
    return ok(ser_cancel_request(record))
