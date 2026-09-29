"""Endorsements, endorsement financing, restructuring and chargebacks."""

from flask import Blueprint, g, request

from calc import (cut_schedule, price_agreement, redistribute_tail,
                  unearned_finance_charge_rebate)
from core import (body, clock, db, fail, new_record, ok, ok_list, opt_int,
                  opt_str, ordered, paginate, parse_date, req_date, req_enum,
                  req_int, touch, endpoint)
from gates import (require_agent_active, require_down_payment,
                   require_first_due_window, require_licensed,
                   require_policy_status, require_stage, require_status,
                   require_term_within_maximum)
from model import (endorsements_of_policy, get_agent, get_agreement,
                   get_chargeback, get_endorsement, get_policy,
                   installments_of_agreement, late_fees_of_agreement,
                   notices_of_agreement, outstanding_chargeback_cents,
                   policies_of_agreement, rule_of_agreement, ser_agreement,
                   ser_chargeback, ser_endorsement)

bp = Blueprint("endorsements", __name__)

ENDORSEMENT_TYPES = ("ADDITIONAL_PREMIUM", "RETURN_PREMIUM")


@bp.route("/policies/<policy_id>/endorsements", methods=["POST"])
@endpoint(("ProducerAgent", "FinanceAnalyst"))
def file_endorsement(policy_id):
    policy = get_policy(policy_id)
    agreement = get_agreement(policy["agreement_id"])
    if g.role == "ProducerAgent" and agreement["producer_agent_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "caller does not own this policy")
    data = body()
    kind = req_enum(data, "endorsement_type", ENDORSEMENT_TYPES)
    amount = req_int(data, "amount_cents", 1)
    effective = req_date(data, "effective_date")
    require_policy_status(policy, ("PENDING_VERIFICATION", "VERIFIED"))
    if policy["verified_effective_date"] is not None:
        floor = parse_date(policy["verified_effective_date"],
                           "verified_effective_date")
        if effective < floor:
            fail("ERR_INVALID_REQUEST",
                 "effective_date must fall on or after the policy's "
                 "verified_effective_date")
    signed = amount if kind == "ADDITIONAL_PREMIUM" else -amount
    rec = new_record(
        "endorsements",
        policy_id=policy["id"],
        endorsement_type=kind,
        amount_cents=amount,
        effective_date=effective.isoformat(),
        status="PENDING",
        signed_amount_cents=signed,
        financed_at=None,
    )
    return ok(ser_endorsement(rec), 201)


@bp.route("/policies/<policy_id>/endorsements", methods=["GET"])
@endpoint(("FinanceAnalyst", "ComplianceOfficer", "ProducerAgent", "Insurer"))
def list_endorsements(policy_id):
    policy = get_policy(policy_id)
    rows = endorsements_of_policy(policy["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, page = paginate(rows, ser_endorsement)
    return ok_list(items, page)


@bp.route("/endorsements/<endorsement_id>/decline", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def decline_endorsement(endorsement_id):
    rec = get_endorsement(endorsement_id)
    data = body()
    opt_str(data, "reason")
    if rec["status"] != "PENDING":
        fail("ERR_ENDORSEMENT_STATE_INVALID",
             "an endorsement in %s status may not be declined" % rec["status"])
    rec["status"] = "DECLINED"
    touch(rec)
    return ok(ser_endorsement(rec))


@bp.route("/agreements/<agreement_id>/endorsement-financings", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def finance_endorsements(agreement_id):
    from model import endorsed_premium_cents
    agreement = get_agreement(agreement_id)
    rule = rule_of_agreement(agreement)
    data = body()
    expected = req_int(data, "expected_agreement_version", 1)
    if expected != agreement["version"]:
        fail("ERR_STALE_AGREEMENT_VERSION",
             "expected_agreement_version %s does not match the stored version %s"
             % (expected, agreement["version"]))
    require_status(agreement, ("ACTIVE",))
    require_stage(agreement, ("CURRENT",))
    qualifying = []
    for policy in policies_of_agreement(agreement["id"]):
        if policy["status"] != "VERIFIED":
            continue
        pending = [e for e in endorsements_of_policy(policy["id"])
                   if e["status"] == "PENDING"]
        if pending:
            qualifying.append((policy, pending))
    if not qualifying:
        fail("ERR_NO_PENDING_ENDORSEMENTS",
             "no pending endorsement exists on a verified policy of this note")
    old_financed = agreement["amount_financed_cents"]
    old_charge = agreement["finance_charge_cents"]
    stamp = clock.now_iso()
    for policy, pending in qualifying:
        for rec in pending:
            rec["status"] = "FINANCED"
            rec["financed_at"] = stamp
            touch(rec)
        policy["financed_premium_cents"] = (policy["verified_premium_cents"]
                                            + endorsed_premium_cents(policy["id"]))
        touch(policy)
    price_agreement(agreement, rule, "FINAL")
    redistribute_tail(agreement)
    agreement["principal_balance_cents"] += (agreement["amount_financed_cents"]
                                             - old_financed)
    agreement["unpaid_finance_charge_cents"] += (agreement["finance_charge_cents"]
                                                 - old_charge)
    touch(agreement)
    return ok(ser_agreement(agreement))


@bp.route("/agreements/<agreement_id>/restructure", methods=["POST"])
@endpoint(("FinanceAnalyst",))
def restructure(agreement_id):
    predecessor = get_agreement(agreement_id)
    rule = rule_of_agreement(predecessor)
    agent = get_agent(predecessor["producer_agent_id"])
    data = body()
    additional_down = req_int(data, "additional_down_payment_cents", 0)
    count = req_int(data, "installment_count", 2)
    first_due = req_date(data, "first_installment_due_date")
    require_status(predecessor, ("ACTIVE",))
    require_licensed(rule)
    require_agent_active(agent)
    require_term_within_maximum(count, rule)
    require_down_payment(additional_down, 0, rule)
    require_first_due_window(first_due)
    verified = [p for p in policies_of_agreement(predecessor["id"])
                if p["status"] == "VERIFIED"]
    if (predecessor["delinquency_stage"] not in ("CURRENT", "LATE", "NOIC_ISSUED")
            or not verified
            or predecessor["principal_balance_cents"] <= 0):
        fail("ERR_RESTRUCTURE_NOT_ELIGIBLE",
             "this note is not eligible for restructuring")

    rebate = unearned_finance_charge_rebate(predecessor, rule)
    predecessor["unpaid_finance_charge_cents"] -= rebate
    rows = installments_of_agreement(predecessor["id"])
    past_due_remainder = sum(r["amount_cents"] - r["paid_cents"] for r in rows
                             if r["status"] == "PAST_DUE")
    reversed_fees = 0
    carried = (predecessor["principal_balance_cents"]
               + predecessor["unpaid_finance_charge_cents"]
               + past_due_remainder
               + predecessor["late_fee_balance_cents"]
               - predecessor["unapplied_credit_cents"]
               - additional_down)
    for row in rows:
        if row["status"] in ("SCHEDULED", "PAST_DUE"):
            row["status"] = "VOIDED"
            touch(row)
    for fee in late_fees_of_agreement(predecessor["id"]):
        if fee["status"] == "OUTSTANDING":
            fee["status"] = "REVERSED"
            reversed_fees += fee["amount_cents"]
            touch(fee)
    for notice in notices_of_agreement(predecessor["id"]):
        if notice["status"] == "ISSUED":
            notice["status"] = "SUPERSEDED"
            touch(notice)
    predecessor["status"] = "RESTRUCTURED"
    predecessor["principal_balance_cents"] = 0
    predecessor["unpaid_finance_charge_cents"] = 0
    predecessor["late_fee_balance_cents"] = 0
    predecessor["delinquency_stage"] = "CURRENT"
    touch(predecessor)

    from routes_agreements import blank_agreement_fields
    fields = blank_agreement_fields()
    fields.update(
        insured_id=predecessor["insured_id"],
        producer_agent_id=predecessor["producer_agent_id"],
        state_rule_id=predecessor["state_rule_id"],
        originated_by_user_id=g.user_id,
        restructured_from_agreement_id=predecessor["id"],
        down_payment_cents=0,
        service_fee_cents=0,
        installment_count=count,
        first_installment_due_date=first_due.isoformat(),
        carried_over_balance_cents=carried,
    )
    successor = new_record("agreements", **fields)
    for policy in policies_of_agreement(predecessor["id"]):
        if policy["status"] == "CANCELLED":
            continue
        policy["agreement_id"] = successor["id"]
        policy["carried_over"] = True
        touch(policy)
    price_agreement(successor, rule, "FINAL")
    cut_schedule(successor, rule, first_due)
    successor["principal_balance_cents"] = successor["amount_financed_cents"]
    successor["unpaid_finance_charge_cents"] = successor["finance_charge_cents"]
    successor["activated_at"] = clock.now_iso()
    successor["status"] = "ACTIVE"
    successor["delinquency_stage"] = "CURRENT"
    return ok(ser_agreement(successor), 201)


# ---------------------------------------------------------------------------
# Agent chargebacks
# ---------------------------------------------------------------------------

@bp.route("/agent-chargebacks", methods=["GET"])
@endpoint(("ComplianceOfficer", "FinanceAnalyst", "ProducerAgent"))
def list_chargebacks():
    rows = ordered(list(db.chargebacks.values()))
    args = request.args
    for key in ("producer_agent_id", "agreement_id", "status"):
        value = args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, page = paginate(rows, ser_chargeback)
    return ok_list(items, page)


@bp.route("/agent-chargebacks/<chargeback_id>", methods=["GET"])
@endpoint(("ComplianceOfficer", "FinanceAnalyst", "ProducerAgent"))
def read_chargeback(chargeback_id):
    return ok(ser_chargeback(get_chargeback(chargeback_id)))


@bp.route("/agent-chargebacks/<chargeback_id>/offset", methods=["POST"])
@endpoint(("ComplianceOfficer",))
def offset_chargeback(chargeback_id):
    record = get_chargeback(chargeback_id)
    agent = get_agent(record["producer_agent_id"])
    data = body()
    amount = req_int(data, "offset_amount_cents", 1)
    expected = req_int(data, "expected_chargeback_version", 1)
    if expected != record["version"]:
        fail("ERR_STALE_CHARGEBACK_VERSION",
             "expected_chargeback_version %s does not match the stored version %s"
             % (expected, record["version"]))
    if record["status"] not in ("PENDING", "PARTIALLY_OFFSET"):
        fail("ERR_CHARGEBACK_STATE_INVALID",
             "a chargeback in %s status accepts no further offset" % record["status"])
    remainder = record["amount_cents"] - record["offset_applied_cents"]
    if amount > remainder or amount > agent["chargeback_reserve_balance_cents"]:
        fail("ERR_OFFSET_EXCEEDS_RESERVE",
             "the offset exceeds the unsettled remainder or the agency reserve")
    record["offset_applied_cents"] += amount
    agent["chargeback_reserve_balance_cents"] -= amount
    if record["offset_applied_cents"] >= record["amount_cents"]:
        record["status"] = "OFFSET"
    else:
        record["status"] = "PARTIALLY_OFFSET"
    touch(record)
    exposure = outstanding_chargeback_cents(agent["id"])
    if (exposure < agent["chargeback_liability_cap_cents"]
            and agent["status"] == "SUSPENDED_FOR_CHARGEBACKS"):
        agent["status"] = "ACTIVE"
        touch(agent)
    return ok(ser_chargeback(record))
