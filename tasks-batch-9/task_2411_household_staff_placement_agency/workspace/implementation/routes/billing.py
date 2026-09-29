"""Milestone billing, claim adjudication and the payroll handoff (PRD 3.7, 3.8)."""

from flask import Blueprint, request

import db
from db import (
    CLAIM_ACTIONS,
    EIN_STATUSES,
    NET_TERMS_DAYS,
    TERMINAL_CLAIM,
    TERMINAL_HANDOFF,
    TERMINAL_MILESTONE,
    serialize,
    store,
    touch,
)
from errors import fail
from middleware import (
    AGENCY_PRINCIPAL,
    BILLING_ADMINISTRATOR,
    CLIENT,
    COMPLIANCE_OFFICER,
    PLACEMENT_CONSULTANT,
    authenticate,
)
from response import object_response
from services import calc, domain
from timeutil import add_days, format_date, parse_date
from validation import body_of, check_enum, check_int, require_present, require_string

bp = Blueprint("billing", __name__)

INVOICEABLE_MILESTONE_STATUSES = ("INVOICED", "OVERDUE")


def _placement_of(row):
    return domain.resolve("placements", row["placement_id"])


def _client_of(placement):
    return domain.resolve("clients", placement["client_id"])


# ---------------------------------------------------------------------------
# Fee milestones
# ---------------------------------------------------------------------------
@bp.get("/fee-milestones/<milestone_id>")
def get_fee_milestone(milestone_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, BILLING_ADMINISTRATOR,
        COMPLIANCE_OFFICER, CLIENT,
    })
    row = domain.resolve("fee_milestones", milestone_id)
    return object_response(serialize(row))


@bp.post("/fee-milestones/<milestone_id>/invoice")
def invoice_milestone(milestone_id):
    user_id, _role = authenticate({BILLING_ADMINISTRATOR})
    body = body_of(request)
    require_string(body, "note", 0, 100000, required=False)

    milestone = domain.resolve("fee_milestones", milestone_id)
    domain.guard_terminal(milestone["invoice_status"], TERMINAL_MILESTONE)
    if milestone["invoice_status"] != "PENDING":
        fail("ERR_INVALID_STATE_TRANSITION")

    placement = _placement_of(milestone)
    if milestone["milestone_type"] == "ENGAGEMENT":
        admissible = ("PENDING_ACCEPTANCE", "ACTIVE")
    else:
        admissible = ("ACTIVE",)
    if placement["placement_status"] not in admissible:
        fail("ERR_PLACEMENT_NOT_ACTIVE")

    if milestone["milestone_type"] == "START_DATE":
        # Cross-arm gate: the compliance desk blocks the billing desk.
        attested = any(
            h["status"] == "ATTESTED" for h in domain.handoffs_of(placement["id"])
        )
        if not attested:
            fail("ERR_PAYROLL_HANDOFF_NOT_ATTESTED")

    client = _client_of(placement)
    invoiced_on = store.today()

    milestone["invoice_status"] = "INVOICED"
    milestone["invoiced_on"] = format_date(invoiced_on)
    milestone["due_date"] = format_date(add_days(invoiced_on, NET_TERMS_DAYS))
    milestone["invoiced_by_user_id"] = user_id
    touch(milestone)

    domain.append_ledger_entry(
        client,
        "FEE_INVOICED",
        milestone["amount_cents"],
        "Invoice for %s milestone" % milestone["milestone_type"],
        related_ref_type="FEE_MILESTONE",
        related_ref_id=milestone["id"],
    )
    domain.recompute_client_balance(client)
    domain.recompute_billing_status(placement)

    return object_response(serialize(milestone))


@bp.post("/fee-milestones/<milestone_id>/record-payment")
def record_milestone_payment(milestone_id):
    authenticate({BILLING_ADMINISTRATOR})
    body = body_of(request)

    require_present(body, "paid_amount_cents", "payment_reference")
    payment_reference = require_string(body, "payment_reference", 0, 100000)
    paid_amount_cents = check_int(body, "paid_amount_cents", minimum=0)

    milestone = domain.resolve("fee_milestones", milestone_id)
    domain.guard_terminal(milestone["invoice_status"], TERMINAL_MILESTONE)
    if milestone["invoice_status"] not in INVOICEABLE_MILESTONE_STATUSES:
        fail("ERR_MILESTONE_NOT_INVOICED")

    # There are no partial payments: a household settles in full or not at all.
    if paid_amount_cents != milestone["amount_cents"]:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH")

    placement = _placement_of(milestone)
    client = _client_of(placement)

    milestone["invoice_status"] = "PAID"
    milestone["paid_on"] = format_date(store.today())
    milestone["payment_reference"] = payment_reference
    touch(milestone)

    domain.append_ledger_entry(
        client,
        "FEE_PAYMENT",
        -milestone["amount_cents"],
        "Payment of %s milestone" % milestone["milestone_type"],
        related_ref_type="FEE_MILESTONE",
        related_ref_id=milestone["id"],
    )
    domain.recompute_client_balance(client)
    domain.recompute_billing_status(placement)

    return object_response(serialize(milestone))


@bp.post("/fee-milestones/<milestone_id>/reverse")
def reverse_milestone(milestone_id):
    authenticate({BILLING_ADMINISTRATOR})
    body = body_of(request)
    require_string(body, "reason", 0, 100000, required=False)

    milestone = domain.resolve("fee_milestones", milestone_id)
    domain.guard_terminal(milestone["invoice_status"], TERMINAL_MILESTONE)
    if milestone["invoice_status"] not in INVOICEABLE_MILESTONE_STATUSES:
        fail("ERR_MILESTONE_NOT_INVOICED")

    placement = _placement_of(milestone)
    client = _client_of(placement)

    milestone["invoice_status"] = "REVERSED"
    touch(milestone)

    # FEE_INVOICED and FEE_REVERSAL carry identical magnitudes with opposite
    # signs, so the receivable returns to its exact pre-invoice value.
    domain.append_ledger_entry(
        client,
        "FEE_REVERSAL",
        -milestone["amount_cents"],
        "Reversal of %s milestone" % milestone["milestone_type"],
        related_ref_type="FEE_MILESTONE",
        related_ref_id=milestone["id"],
    )
    domain.recompute_client_balance(client)
    domain.recompute_billing_status(placement)

    return object_response(serialize(milestone))


# ---------------------------------------------------------------------------
# Replacement claims
# ---------------------------------------------------------------------------
@bp.get("/replacement-claims/<claim_id>")
def get_replacement_claim(claim_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, BILLING_ADMINISTRATOR,
        COMPLIANCE_OFFICER, CLIENT,
    })
    row = domain.resolve("replacement_claims", claim_id)
    return object_response(serialize(row))


def _void_pending_milestones(placement):
    for milestone in db.sort_by_sequence(domain.milestones_of(placement["id"])):
        if milestone["invoice_status"] == "PENDING":
            milestone["invoice_status"] = "VOIDED"
            touch(milestone)


@bp.post("/replacement-claims/<claim_id>/review")
def review_replacement_claim(claim_id):
    authenticate({AGENCY_PRINCIPAL})
    body = body_of(request)

    require_present(body, "action")
    decision_note = require_string(body, "decision_note", 0, 100000, required=False)
    action = check_enum(body, "action", CLAIM_ACTIONS)

    claim = domain.resolve("replacement_claims", claim_id)
    domain.guard_terminal(claim["status"], TERMINAL_CLAIM)

    required_state = "SUBMITTED" if action == "OPEN_REVIEW" else "UNDER_REVIEW"
    if claim["status"] != required_state:
        fail("ERR_CLAIM_NOT_UNDER_REVIEW")

    if action == "APPROVE_REPLACEMENT" and claim["requested_remedy"] != "REPLACEMENT":
        fail("ERR_REMEDY_MISMATCH")
    if action == "APPROVE_REFUND" and claim["requested_remedy"] != "REFUND":
        fail("ERR_REMEDY_MISMATCH")

    if action == "OPEN_REVIEW":
        claim["status"] = "UNDER_REVIEW"
        if decision_note is not None:
            claim["decision_note"] = decision_note
        touch(claim)
        return object_response(serialize(claim))

    if action == "REQUEST_INFO":
        claim["status"] = "INFO_REQUESTED"
        claim["info_request_round"] += 1
        if decision_note is not None:
            claim["decision_note"] = decision_note
        touch(claim)
        return object_response(serialize(claim))

    if action == "DENY":
        # A denial changes nothing but the claim and the right to re-file.
        claim["status"] = "DENIED"
        if decision_note is not None:
            claim["decision_note"] = decision_note
        touch(claim)
        return object_response(serialize(claim))

    placement = _placement_of(claim)
    client = _client_of(placement)
    candidate = store.candidates.get(placement["candidate_id"])
    requisition = store.requisitions.get(placement["requisition_id"])

    if action == "APPROVE_REPLACEMENT":
        claim["status"] = "APPROVED_REPLACEMENT"
        if decision_note is not None:
            claim["decision_note"] = decision_note
        touch(claim)

        # A fresh search rather than money: no ledger movement of any kind.
        placement["placement_status"] = "TERMINATED_REPLACED"
        touch(placement)
        _void_pending_milestones(placement)

        if requisition is not None and requisition["status"] == "PLACED":
            # The search reopens without consuming a scoping round.
            requisition["status"] = "SOURCING"
            touch(requisition)
    else:
        figures = calc.refund_proration(
            placement["fee_cents"],
            placement["guarantee_window_days"],
            parse_date(placement["start_date"]),
            parse_date(claim["separation_date"]),
        )
        claim["status"] = "APPROVED_REFUND"
        claim["elapsed_days"] = figures["elapsed_days"]
        claim["unused_days"] = figures["unused_days"]
        claim["gross_refund_cents"] = figures["gross_refund_cents"]
        claim["retained_admin_fee_cents"] = figures["admin_retained_cents"]
        claim["net_refund_cents"] = figures["net_refund_cents"]
        if decision_note is not None:
            claim["decision_note"] = decision_note
        touch(claim)

        placement["placement_status"] = "TERMINATED_REFUNDED"
        if placement["billing_status"] in ("PARTIALLY_BILLED", "FULLY_BILLED"):
            placement["billing_status"] = "REFUNDED"
        touch(placement)
        _void_pending_milestones(placement)

        domain.append_ledger_entry(
            client,
            "REFUND_ISSUED",
            -claim["net_refund_cents"],
            "Guarantee refund on claim %s" % claim["id"],
            related_ref_type="REPLACEMENT_CLAIM",
            related_ref_id=claim["id"],
        )
        domain.recompute_client_balance(client)

    if candidate is not None:
        domain.start_cooling_off(candidate)
    domain.recompute_client_derived(client)

    return object_response(serialize(claim))


@bp.post("/replacement-claims/<claim_id>/provide-info")
def provide_claim_info(claim_id):
    authenticate({CLIENT})
    body = body_of(request)

    info_note = require_string(body, "info_note", 0, 100000)

    claim = domain.resolve("replacement_claims", claim_id)
    domain.guard_terminal(claim["status"], TERMINAL_CLAIM)
    if claim["status"] != "INFO_REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION")

    claim["status"] = "UNDER_REVIEW"
    existing = claim.get("decision_note")
    claim["decision_note"] = info_note if not existing else "%s\n%s" % (existing, info_note)
    touch(claim)

    return object_response(serialize(claim))


# ---------------------------------------------------------------------------
# Payroll handoffs
# ---------------------------------------------------------------------------
@bp.get("/payroll-handoffs/<handoff_id>")
def get_payroll_handoff(handoff_id):
    authenticate({AGENCY_PRINCIPAL, BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER, CLIENT})
    row = domain.resolve("payroll_handoffs", handoff_id)
    return object_response(serialize(row))


@bp.post("/payroll-handoffs/<handoff_id>/update-ein")
def update_handoff_ein(handoff_id):
    authenticate({COMPLIANCE_OFFICER})
    body = body_of(request)

    require_present(body, "ein_status")
    # The status is advanced, so only APPLIED and ISSUED may be supplied.
    ein_status = check_enum(body, "ein_status", [s for s in EIN_STATUSES if s != "NOT_APPLIED"])

    handoff = domain.resolve("payroll_handoffs", handoff_id)
    domain.guard_terminal(handoff["status"], TERMINAL_HANDOFF)

    handoff["ein_status"] = ein_status
    touch(handoff)
    return object_response(serialize(handoff))


@bp.post("/payroll-handoffs/<handoff_id>/attest")
def attest_handoff(handoff_id):
    authenticate({CLIENT, COMPLIANCE_OFFICER})
    body = body_of(request)

    attested_by_name = require_string(body, "attested_by_name", 0, 100000)

    handoff = domain.resolve("payroll_handoffs", handoff_id)
    domain.guard_terminal(handoff["status"], TERMINAL_HANDOFF)
    if handoff["ein_status"] != "ISSUED":
        fail("ERR_EIN_NOT_ISSUED")

    handoff["status"] = "ATTESTED"
    handoff["attested_by_name"] = attested_by_name
    handoff["attested_at"] = store.now_str()
    touch(handoff)
    return object_response(serialize(handoff))
