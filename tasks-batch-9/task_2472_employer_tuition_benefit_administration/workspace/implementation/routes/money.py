"""Invoices, reimbursement claims, repayment obligations and the tax ledger."""

from decimal import Decimal

import domain
import serialize
from auth import employee_scope, employer_scope, endpoint
from errors import ApiError, fail
from store import db, new_record, touch
from validate import (
    body,
    enum_field,
    int_field,
    nullable_text,
    pagination,
    query_enum,
    query_int,
    query_str,
    string_field,
)

from .common import filter_eq, object_response, paged
from .enrollments import own_enrollment

ENTRY_TYPES = ["BENEFIT", "REVERSAL", "TRUE_UP"]
CLAIM_DECISIONS = ["APPROVE", "REJECT"]


def register(app):
    # ------------------------------------------------------------------ invoices
    @app.post("/tuition-invoices/<invoice_id>/approve-payment")
    @endpoint(["BenefitAdministrator"])
    def approve_invoice(invoice_id):
        invoice = domain.must(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
        enrollment = db.enrollments[invoice["enrollment_id"]]
        own_enrollment(enrollment)
        if enrollment["academic_status"] not in domain.OPEN_ACADEMIC_STATES:
            fail(
                "ERR_ENROLLMENT_INVALID_ACADEMIC_STATE",
                "enrollment is %s" % enrollment["academic_status"],
            )
        if invoice["status"] != "ISSUED":
            fail("ERR_INVOICE_INVALID_STATE", "invoice is %s, not ISSUED" % invoice["status"])
        invoice["status"] = "APPROVED_FOR_PAYMENT"
        touch(invoice)
        return object_response(serialize.invoice(invoice))

    @app.post("/tuition-invoices/<invoice_id>/pay")
    @endpoint(["PlatformAdmin"])
    def pay_invoice(invoice_id):
        invoice = domain.must(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
        enrollment = db.enrollments[invoice["enrollment_id"]]
        employee = db.employees[enrollment["employee_id"]]
        if enrollment["academic_status"] == "WITHDRAWN":
            fail("ERR_ENROLLMENT_INVALID_ACADEMIC_STATE", "the enrollment is WITHDRAWN")
        if enrollment["funding_status"] != "BILLED":
            fail(
                "ERR_ENROLLMENT_INVALID_FUNDING_STATE",
                "funding is %s, not BILLED" % enrollment["funding_status"],
            )
        if invoice["status"] != "APPROVED_FOR_PAYMENT":
            fail(
                "ERR_INVOICE_INVALID_STATE",
                "invoice is %s, not APPROVED_FOR_PAYMENT" % invoice["status"],
            )

        invoice["status"] = "PAID"
        invoice["paid_on"] = domain.clock_date().isoformat()
        touch(invoice)
        domain.settle_direct_bill(invoice, enrollment, employee)
        domain.refresh_and_touch(employee)
        return object_response(serialize.invoice(invoice))

    # -------------------------------------------------------------------- claims
    @app.post("/enrollments/<enrollment_id>/reimbursement-claims")
    @endpoint(["Employee"])
    def file_claim(enrollment_id):
        data = body()
        amount_requested_cents = int_field(data, "amount_requested_cents", minimum=1)
        receipt_reference = string_field(data, "receipt_reference", max_len=64)

        enrollment = domain.must(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
        own_enrollment(enrollment)

        if enrollment["academic_status"] != "PASSED":
            fail(
                "ERR_ENROLLMENT_INVALID_ACADEMIC_STATE",
                "enrollment is %s, not PASSED" % enrollment["academic_status"],
            )
        # rule 24 only bites on a reimbursement enrollment; direct bill falls to rule 31
        if (
            enrollment["funding_model"] == "REIMBURSEMENT"
            and enrollment["funding_status"] != "RESERVED"
        ):
            fail(
                "ERR_ENROLLMENT_INVALID_FUNDING_STATE",
                "funding is %s, not RESERVED" % enrollment["funding_status"],
            )

        policy = db.policies[enrollment["policy_id"]]
        outcome = domain.latest_outcome(enrollment_id)
        floor = Decimal(str(policy["min_passing_grade_points"]))
        if (
            outcome is None
            or outcome["completion_status"] != "PASSED"
            or outcome["grade_points"] is None
            or Decimal(str(outcome["grade_points"])) < floor
        ):
            fail("ERR_ACADEMIC_PROGRESS_NOT_MET", "the latest outcome does not clear the floor")

        if enrollment["funding_model"] != "REIMBURSEMENT":
            fail("ERR_REIMBURSEMENT_NOT_ALLOWED", "this enrollment is billed directly")

        row = new_record(
            {
                "enrollment_id": enrollment["id"],
                "amount_requested_cents": amount_requested_cents,
                "receipt_reference": receipt_reference,
                "status": "SUBMITTED",
                "approved_amount_cents": 0,
                "platform_admin_fee_cents": 0,
                "decision_note": None,
            }
        )
        db.claims[row["id"]] = row
        return object_response(serialize.claim(row), 201)

    @app.post("/reimbursement-claims/<claim_id>/decide")
    @endpoint(["BenefitAdministrator"])
    def decide_claim(claim_id):
        data = body()
        decision = enum_field(data, "decision", CLAIM_DECISIONS)
        decision_note = nullable_text(data, "decision_note", 2000)

        claim = domain.must(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
        enrollment = db.enrollments[claim["enrollment_id"]]
        employee = own_enrollment(enrollment)

        if decision == "APPROVE" and enrollment["funding_status"] != "RESERVED":
            fail(
                "ERR_ENROLLMENT_INVALID_FUNDING_STATE",
                "funding is %s, not RESERVED" % enrollment["funding_status"],
            )
        if claim["status"] != "SUBMITTED":
            fail("ERR_CLAIM_INVALID_STATE", "claim is %s, not SUBMITTED" % claim["status"])

        if decision == "REJECT":
            claim["status"] = "REJECTED"
            claim["decision_note"] = decision_note
            touch(claim)
            enrollment["funding_status"] = "RELEASED"
            touch(enrollment)
            domain.refresh_and_touch(employee)
            return object_response(serialize.claim(claim))

        # --- APPROVE: the six pinned settlement steps ------------------------
        policy = db.policies[enrollment["policy_id"]]
        outcome = domain.latest_outcome(enrollment["id"])
        cap_available = employee["cap_available_cents"]
        ceiling = enrollment["employer_reserved_cents"] + cap_available

        eligible_final = domain.reimbursement_final(enrollment, policy, outcome, cap_available)
        approved = min(claim["amount_requested_cents"], eligible_final, ceiling)
        fee_basis = domain.employer_total_disbursed(employee["employer_id"])
        fee_pct = domain.admin_fee_pct(fee_basis)
        fee = domain.round_half_up(Decimal(approved) * fee_pct)

        claim["status"] = "APPROVED"
        claim["approved_amount_cents"] = approved
        claim["platform_admin_fee_cents"] = fee
        claim["decision_note"] = decision_note
        touch(claim)

        enrollment["funding_status"] = "SETTLED"
        enrollment["employer_settled_cents"] = approved
        enrollment["employer_disbursed_cents"] = approved
        touch(enrollment)

        domain.append_benefit_entry(employee, enrollment, approved)
        domain.refresh_and_touch(employee)
        return object_response(serialize.claim(claim))

    # --------------------------------------------------------------- obligations
    def _own_obligation(obligation):
        enrollment = db.enrollments[obligation["enrollment_id"]]
        return own_enrollment(enrollment)

    @app.post("/repayment-obligations/<obligation_id>/payments")
    @endpoint(["Employee"])
    def repay(obligation_id):
        data = body()
        amount_cents = int_field(data, "amount_cents", minimum=1)
        obligation = domain.must(db.obligations, obligation_id, "ERR_OBLIGATION_NOT_FOUND")
        employee = _own_obligation(obligation)
        if obligation["status"] not in domain.OPEN_OBLIGATION_STATES:
            fail(
                "ERR_OBLIGATION_INVALID_STATE",
                "obligation is %s" % obligation["status"],
            )
        if amount_cents > obligation["balance_cents"]:
            fail("ERR_REPAYMENT_EXCEEDS_BALANCE", "the payment exceeds the outstanding balance")

        obligation["paid_cents"] += amount_cents
        obligation["balance_cents"] = (
            obligation["principal_cents"] - obligation["paid_cents"] - obligation["waived_cents"]
        )
        obligation["status"] = "SETTLED" if obligation["balance_cents"] == 0 else "PARTIALLY_PAID"
        touch(obligation)
        domain.refresh_and_touch(employee)
        return object_response(serialize.obligation(obligation))

    @app.post("/repayment-obligations/<obligation_id>/waive")
    @endpoint(["BenefitAdministrator"])
    def waive(obligation_id):
        obligation = domain.must(db.obligations, obligation_id, "ERR_OBLIGATION_NOT_FOUND")
        employee = _own_obligation(obligation)
        if obligation["status"] not in domain.OPEN_OBLIGATION_STATES:
            fail("ERR_OBLIGATION_INVALID_STATE", "obligation is %s" % obligation["status"])
        obligation["waived_cents"] = obligation["balance_cents"]
        obligation["balance_cents"] = 0
        obligation["status"] = "WAIVED"
        touch(obligation)
        domain.refresh_and_touch(employee)
        return object_response(serialize.obligation(obligation))

    # ---------------------------------------------------------------- tax ledger
    @app.get("/tax-ledger-entries")
    @endpoint(["BenefitAdministrator", "PlatformAdmin"])
    def list_tax_entries():
        limit, offset = pagination()
        entry_type = query_enum("entry_type", ENTRY_TYPES)
        tax_year = query_int("tax_year", None)
        rows = list(db.tax_entries.values())
        rows = filter_eq(rows, "employee_id", query_str("employee_id"))
        rows = filter_eq(rows, "enrollment_id", query_str("enrollment_id"))
        rows = filter_eq(rows, "entry_type", entry_type)
        if tax_year is not None:
            rows = [r for r in rows if r["tax_year"] == tax_year]
        return paged(rows, serialize.tax_entry, limit, offset)

    @app.get("/tax-ledger-entries/<entry_id>")
    @endpoint(["BenefitAdministrator", "PlatformAdmin"])
    def read_tax_entry(entry_id):
        entry = db.tax_entries.get(entry_id)
        if entry is None:
            raise ApiError("ERR_NOT_FOUND", 404, "no tax ledger entry with id %s" % entry_id)
        employee = db.employees[entry["employee_id"]]
        employer_scope(employee["employer_id"])
        employee_scope(employee["id"])
        return object_response(serialize.tax_entry(entry))
