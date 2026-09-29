"""Layered setup builders.

The harness restarts the server before every test, so each test starts against an empty
database and has to build every row it needs through the API. Almost every workflow in
this domain shares one spine — pin the clock, onboard an applicant, open a facility,
register a bank and a beneficiary, draft a credit with its documentary requirements,
submit it, approve it with a second pair of eyes, issue it, then present, examine, claim
and settle. These builders express that spine one tier at a time so a test can enter it
at whatever depth it needs and override exactly the inputs under examination.

Every builder drives the public API with `get_success_data`, never a direct database
write, and threads identities correctly: the entity-backed roles (`ApplicantUser`,
`BeneficiaryUser`, `CorrespondentBank`) always act under headers built from the id of the
row they represent.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    COMPLIANCE_OFFICER_1,
    COMPLIANCE_OFFICER_2,
    CREDIT_OFFICER_1,
    CREDIT_OFFICER_2,
    DOCUMENT_EXAMINER_1,
    SYSTEM_OPERATOR_1,
    TRADE_FINANCE_OFFICER_1,
    TRADE_FINANCE_OFFICER_2,
    compliance_officer_headers,
    credit_officer_headers,
    document_examiner_headers,
    make_applicant_user_headers,
    make_beneficiary_user_headers,
    make_correspondent_bank_headers,
    system_operator_headers,
    trade_finance_officer_headers,
)

# A Monday, chosen so banking-day walks are easy to follow by hand.
DEFAULT_CLOCK = "2026-08-10T09:00:00Z"


# ----------------------------------------------------------------------
# Tier 0 — clock and sweep
# ----------------------------------------------------------------------
def set_clock(instant: str, user_id: str = SYSTEM_OPERATOR_1) -> Dict[str, Any]:
    """Move the deterministic logical clock. Only a SystemOperator may do this."""
    return get_success_data(
        api_client.set_clock(f.clock_payload(instant), system_operator_headers(user_id))
    )


def pin_default_clock() -> str:
    set_clock(DEFAULT_CLOCK)
    return DEFAULT_CLOCK


def run_sweep(dry_run: Optional[bool] = None, user_id: str = SYSTEM_OPERATOR_1) -> Dict[str, Any]:
    payload: Dict[str, Any] = {} if dry_run is None else {"dry_run": dry_run}
    return get_success_data(
        api_client.run_expiry_sweep(payload, system_operator_headers(user_id))
    )


# ----------------------------------------------------------------------
# Tier 1 — counterparties
# ----------------------------------------------------------------------
def create_applicant(user_id: str = CREDIT_OFFICER_1, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_applicant(
            f.applicant_payload(**overrides), credit_officer_headers(user_id)
        )
    )


def create_facility(
    applicant_id: str, user_id: str = CREDIT_OFFICER_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_facility(
            applicant_id, f.facility_payload(**overrides), credit_officer_headers(user_id)
        )
    )


def create_bank(user_id: str = CREDIT_OFFICER_1, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_bank(f.bank_payload(**overrides), credit_officer_headers(user_id))
    )


def create_beneficiary(
    nominated_bank_id: str, user_id: str = TRADE_FINANCE_OFFICER_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_beneficiary(
            f.beneficiary_payload(nominated_bank_id, **overrides),
            trade_finance_officer_headers(user_id),
        )
    )


def post_collateral(
    facility_id: str,
    amount_cents: int,
    expected_facility_version: int,
    user_id: str = CREDIT_OFFICER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_collateral_posting(
            facility_id,
            f.collateral_posting_payload(amount_cents, expected_facility_version, **overrides),
            credit_officer_headers(user_id),
        )
    )


def change_facility_status(
    facility_id: str, action: str, user_id: str = CREDIT_OFFICER_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_facility_status_change(
            facility_id,
            f.facility_status_change_payload(action, **overrides),
            credit_officer_headers(user_id),
        )
    )


@dataclass
class Parties:
    """The four counterparties every credit needs, plus their acting headers."""

    applicant: Dict[str, Any]
    facility: Dict[str, Any]
    advising_bank: Dict[str, Any]
    beneficiary: Dict[str, Any]

    @property
    def applicant_id(self) -> str:
        return self.applicant["id"]

    @property
    def facility_id(self) -> str:
        return self.facility["id"]

    @property
    def advising_bank_id(self) -> str:
        return self.advising_bank["id"]

    @property
    def beneficiary_id(self) -> str:
        return self.beneficiary["id"]

    @property
    def nominated_bank_id(self) -> str:
        return self.beneficiary["nominated_bank_id"]

    @property
    def applicant_headers(self) -> Dict[str, str]:
        return make_applicant_user_headers(self.applicant_id)

    @property
    def beneficiary_headers(self) -> Dict[str, str]:
        return make_beneficiary_user_headers(self.beneficiary_id)

    @property
    def advising_bank_headers(self) -> Dict[str, str]:
        return make_correspondent_bank_headers(self.advising_bank_id)

    @property
    def nominated_bank_headers(self) -> Dict[str, str]:
        return make_correspondent_bank_headers(self.nominated_bank_id)

    def refresh_facility(self) -> Dict[str, Any]:
        self.facility = get_success_data(
            api_client.get_facility(self.facility_id, credit_officer_headers())
        )
        return self.facility

    def refresh_applicant(self) -> Dict[str, Any]:
        self.applicant = get_success_data(
            api_client.get_applicant(self.applicant_id, credit_officer_headers())
        )
        return self.applicant

    def refresh_advising_bank(self) -> Dict[str, Any]:
        self.advising_bank = get_success_data(
            api_client.get_bank(self.advising_bank_id, credit_officer_headers())
        )
        return self.advising_bank


def setup_parties(
    applicant: Optional[Dict[str, Any]] = None,
    facility: Optional[Dict[str, Any]] = None,
    bank: Optional[Dict[str, Any]] = None,
    beneficiary: Optional[Dict[str, Any]] = None,
) -> Parties:
    """Onboard applicant, facility, advising bank and beneficiary in one call.

    Each argument is a dict of field overrides for that row. The beneficiary's
    `nominated_bank_id` defaults to the advising bank, which makes that one bank an
    acceptable presenting bank as well.
    """
    applicant_row = create_applicant(**(applicant or {}))
    facility_row = create_facility(applicant_row["id"], **(facility or {}))
    bank_row = create_bank(**(bank or {}))
    beneficiary_overrides = dict(beneficiary or {})
    nominated_bank_id = beneficiary_overrides.pop("nominated_bank_id", bank_row["id"])
    beneficiary_row = create_beneficiary(nominated_bank_id, **beneficiary_overrides)
    return Parties(
        applicant=applicant_row,
        facility=facility_row,
        advising_bank=bank_row,
        beneficiary=beneficiary_row,
    )


# ----------------------------------------------------------------------
# Tier 2 — the documentary credit
# ----------------------------------------------------------------------
@dataclass
class CreditContext:
    """A credit plus the parties it names, so tests can keep re-reading both."""

    parties: Parties
    credit: Dict[str, Any]
    requirements: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def credit_id(self) -> str:
        return self.credit["id"]

    @property
    def version(self) -> int:
        return self.credit["version"]

    def refresh(self) -> Dict[str, Any]:
        self.credit = get_success_data(
            api_client.get_credit(self.credit_id, trade_finance_officer_headers())
        )
        return self.credit

    def refresh_facility(self) -> Dict[str, Any]:
        return self.parties.refresh_facility()


def default_requirement_payloads() -> List[Dict[str, Any]]:
    """A mandatory commercial invoice plus a transport document.

    Submission for approval demands at least one mandatory `COMMERCIAL_INVOICE`
    requirement and at least one transport requirement, and an `FOB` credit must not
    carry an `INSURANCE_CERTIFICATE` requirement, so this pair is the minimum legal set
    for the default draft.
    """
    return [f.invoice_requirement_payload(), f.transport_requirement_payload()]


def add_requirement(
    credit_id: str, payload: Dict[str, Any], user_id: str = TRADE_FINANCE_OFFICER_1
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_documentary_requirement(
            credit_id, payload, trade_finance_officer_headers(user_id)
        )
    )


def draft_credit(
    parties: Parties,
    requirements: Optional[Sequence[Dict[str, Any]]] = None,
    user_id: str = TRADE_FINANCE_OFFICER_1,
    **overrides: Any,
) -> CreditContext:
    """Draft a credit on the given parties and attach its documentary requirements.

    Callers may override any of the four party ids (for example to draft on a second
    facility of the same applicant); anything not overridden comes from `parties`.
    """
    applicant_id = overrides.pop("applicant_id", parties.applicant_id)
    beneficiary_id = overrides.pop("beneficiary_id", parties.beneficiary_id)
    facility_id = overrides.pop("facility_id", parties.facility_id)
    advising_bank_id = overrides.pop("advising_bank_id", parties.advising_bank_id)
    credit = get_success_data(
        api_client.create_credit(
            f.credit_payload(
                applicant_id,
                beneficiary_id,
                facility_id,
                advising_bank_id,
                **overrides,
            ),
            trade_finance_officer_headers(user_id),
        )
    )
    payloads = default_requirement_payloads() if requirements is None else list(requirements)
    rows = [add_requirement(credit["id"], p, user_id) for p in payloads]
    ctx = CreditContext(parties=parties, credit=credit, requirements=rows)
    ctx.refresh()
    return ctx


def submit_credit_for_approval(
    credit_id: str, user_id: str = TRADE_FINANCE_OFFICER_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_credit_for_approval(
            credit_id,
            f.submit_for_approval_payload(**overrides),
            trade_finance_officer_headers(user_id),
        )
    )


def approve_credit(
    credit_id: str, user_id: str = CREDIT_OFFICER_2, **overrides: Any
) -> Dict[str, Any]:
    """Approve a pending credit.

    The acting identifier must differ from the credit's `drafted_by_user_id`, so the
    default approver is a credit officer distinct from the drafting officer.
    """
    return get_success_data(
        api_client.approve_credit(
            credit_id, f.approve_payload(**overrides), credit_officer_headers(user_id)
        )
    )


def issue_credit(
    credit_id: str, user_id: str = TRADE_FINANCE_OFFICER_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.issue_credit(
            credit_id, f.issue_payload(**overrides), trade_finance_officer_headers(user_id)
        )
    )


def approved_credit(
    parties: Optional[Parties] = None,
    requirements: Optional[Sequence[Dict[str, Any]]] = None,
    **overrides: Any,
) -> CreditContext:
    """Draft a credit and carry it as far as `APPROVED`."""
    ctx = draft_credit(parties or setup_parties(), requirements, **overrides)
    submit_credit_for_approval(ctx.credit_id)
    approve_credit(ctx.credit_id)
    ctx.refresh()
    return ctx


def issued_credit(
    parties: Optional[Parties] = None,
    requirements: Optional[Sequence[Dict[str, Any]]] = None,
    **overrides: Any,
) -> CreditContext:
    """Draft, submit, approve and issue a credit; the facility is committed at issuance."""
    ctx = approved_credit(parties, requirements, **overrides)
    issue_credit(ctx.credit_id)
    ctx.refresh()
    ctx.parties.refresh_facility()
    return ctx


def cancel_credit(
    credit_id: str, user_id: str = TRADE_FINANCE_OFFICER_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.cancel_credit(
            credit_id, f.cancel_payload(**overrides), trade_finance_officer_headers(user_id)
        )
    )


def list_credit_allocation_rows(credit_id: str, **params: Any) -> List[Dict[str, Any]]:
    """Allocation rows raised by one credit, in `created_at` ascending order."""
    return get_success_data(
        api_client.list_credit_allocations(
            credit_id, trade_finance_officer_headers(), params or None
        )
    )


def list_facility_allocation_rows(facility_id: str, **params: Any) -> List[Dict[str, Any]]:
    """Allocation rows sitting on one facility, in `created_at` ascending order."""
    return get_success_data(
        api_client.list_facility_allocations(
            facility_id, credit_officer_headers(), params or None
        )
    )


def list_credit_screening_rows(credit_id: str, **params: Any) -> List[Dict[str, Any]]:
    """Screening checks attached to one credit, in `created_at` ascending order."""
    return get_success_data(
        api_client.list_credit_screening_checks(
            credit_id, compliance_officer_headers(), params or None
        )
    )


# ----------------------------------------------------------------------
# Tier 3 — confirmation
# ----------------------------------------------------------------------
def request_confirmation(
    credit_id: str,
    confirming_bank_id: Optional[str] = None,
    user_id: str = TRADE_FINANCE_OFFICER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    """Ask a correspondent bank to add its confirmation.

    Omitting `confirming_bank_id` hands the choice to the selector policy.
    """
    return get_success_data(
        api_client.create_confirmation_request(
            credit_id,
            f.confirmation_request_payload(confirming_bank_id, **overrides),
            trade_finance_officer_headers(user_id),
        )
    )


def respond_to_confirmation(
    credit_id: str, confirming_bank_id: str, decision: str = "CONFIRM", **overrides: Any
) -> Dict[str, Any]:
    """The nominated confirming bank answers; it acts under its own bank id."""
    return get_success_data(
        api_client.create_confirmation_response(
            credit_id,
            f.confirmation_response_payload(decision=decision, **overrides),
            make_correspondent_bank_headers(confirming_bank_id),
        )
    )


def confirmed_credit(
    ctx: CreditContext, confirming_bank_id: Optional[str] = None
) -> Tuple[CreditContext, str]:
    """Drive an issued credit all the way to `CONFIRMED`, returning the confirming bank."""
    request = request_confirmation(ctx.credit_id, confirming_bank_id)
    bank_id = request["confirming_bank_id"]
    respond_to_confirmation(ctx.credit_id, bank_id, "CONFIRM")
    ctx.refresh()
    return ctx, bank_id


# ----------------------------------------------------------------------
# Tier 3 — amendments
# ----------------------------------------------------------------------
def draft_amendment(
    ctx: CreditContext,
    change_set: Dict[str, Any],
    expected_credit_version: Optional[int] = None,
    user_id: str = TRADE_FINANCE_OFFICER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft an amendment under optimistic concurrency control on the credit."""
    if expected_credit_version is None:
        expected_credit_version = ctx.refresh()["version"]
    return get_success_data(
        api_client.create_amendment(
            ctx.credit_id,
            f.amendment_payload(change_set, expected_credit_version, **overrides),
            trade_finance_officer_headers(user_id),
        )
    )


def issue_amendment(
    amendment_id: str, user_id: str = TRADE_FINANCE_OFFICER_2, **overrides: Any
) -> Dict[str, Any]:
    """Issue an amendment.

    The acting identifier must differ from the amendment's own `drafted_by_user_id`, so
    the default issuer is a trade finance officer distinct from the drafting officer.
    """
    return get_success_data(
        api_client.issue_amendment(
            amendment_id,
            f.amendment_issue_payload(**overrides),
            trade_finance_officer_headers(user_id),
        )
    )


def consent_to_amendment(
    amendment_id: str, beneficiary_id: str, decision: str, **overrides: Any
) -> Dict[str, Any]:
    """The beneficiary answers a consent-bearing amendment under its own id."""
    return get_success_data(
        api_client.consent_amendment(
            amendment_id,
            f.consent_payload(decision, **overrides),
            make_beneficiary_user_headers(beneficiary_id),
        )
    )


def list_amendment_rows(credit_id: str, **params: Any) -> List[Dict[str, Any]]:
    """Amendments of one credit, in `seq` ascending order."""
    return get_success_data(
        api_client.list_credit_amendments(
            credit_id, trade_finance_officer_headers(), params or None
        )
    )


# ----------------------------------------------------------------------
# Tier 4 — presentation of documents
# ----------------------------------------------------------------------
@dataclass
class PresentationContext:
    """A presentation file plus the credit and bank it belongs to."""

    credit_ctx: CreditContext
    presentation: Dict[str, Any]
    presenting_bank_id: str
    documents: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def presentation_id(self) -> str:
        return self.presentation["id"]

    @property
    def credit_id(self) -> str:
        return self.credit_ctx.credit_id

    @property
    def parties(self) -> Parties:
        return self.credit_ctx.parties

    @property
    def bank_headers(self) -> Dict[str, str]:
        return make_correspondent_bank_headers(self.presenting_bank_id)

    def refresh(self) -> Dict[str, Any]:
        self.presentation = get_success_data(
            api_client.get_presentation(self.presentation_id, document_examiner_headers())
        )
        return self.presentation

    def refresh_credit(self) -> Dict[str, Any]:
        return self.credit_ctx.refresh()


def open_presentation(
    credit_ctx: CreditContext,
    presenting_bank_id: Optional[str] = None,
    **overrides: Any,
) -> PresentationContext:
    """Open a presentation file. The acting bank id must equal `presenting_bank_id`."""
    bank_id = presenting_bank_id or credit_ctx.parties.nominated_bank_id
    row = get_success_data(
        api_client.create_presentation(
            f.presentation_payload(credit_ctx.credit_id, bank_id, **overrides),
            make_correspondent_bank_headers(bank_id),
        )
    )
    return PresentationContext(
        credit_ctx=credit_ctx, presentation=row, presenting_bank_id=bank_id
    )


def add_document(pctx: PresentationContext, payload: Dict[str, Any]) -> Dict[str, Any]:
    row = get_success_data(
        api_client.create_presented_document(
            pctx.presentation_id, payload, pctx.bank_headers
        )
    )
    pctx.documents.append(row)
    return row


def add_invoice(
    pctx: PresentationContext, invoice_amount_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return add_document(pctx, f.invoice_document_payload(invoice_amount_cents, **overrides))


def add_transport_document(pctx: PresentationContext, **overrides: Any) -> Dict[str, Any]:
    return add_document(pctx, f.transport_document_payload(**overrides))


def submit_presentation(pctx: PresentationContext, **overrides: Any) -> Dict[str, Any]:
    """Declare the file complete: freeze the drawn amount and start the examination clock."""
    row = get_success_data(
        api_client.submit_presentation(
            pctx.presentation_id,
            f.submit_presentation_payload(**overrides),
            pctx.bank_headers,
        )
    )
    pctx.presentation = row
    return row


def submitted_presentation(
    credit_ctx: CreditContext,
    invoice_amounts: Sequence[int] = (2000000,),
    presenting_bank_id: Optional[str] = None,
    invoice_overrides: Optional[Dict[str, Any]] = None,
    transport_overrides: Optional[Dict[str, Any]] = None,
    **presentation_overrides: Any,
) -> PresentationContext:
    """Open a file, tender one invoice per amount plus a transport document, and submit.

    The default answer set satisfies the credit's mandatory commercial invoice and
    transport requirements, so submission is admitted.
    """
    pctx = open_presentation(credit_ctx, presenting_bank_id, **presentation_overrides)
    for amount in invoice_amounts:
        add_invoice(pctx, amount, **(invoice_overrides or {}))
    add_transport_document(pctx, **(transport_overrides or {}))
    submit_presentation(pctx)
    pctx.refresh()
    return pctx


# ----------------------------------------------------------------------
# Tier 5 — examination, waivers, refusal
# ----------------------------------------------------------------------
def raise_discrepancy(
    pctx: PresentationContext,
    code: str,
    severity: str = "MATERIAL",
    user_id: str = DOCUMENT_EXAMINER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_discrepancy(
            pctx.presentation_id,
            f.discrepancy_payload(code, severity, **overrides),
            document_examiner_headers(user_id),
        )
    )


def conclude_examination(
    pctx: PresentationContext, user_id: str = DOCUMENT_EXAMINER_1, **overrides: Any
) -> Dict[str, Any]:
    row = get_success_data(
        api_client.conclude_examination(
            pctx.presentation_id,
            f.conclude_examination_payload(**overrides),
            document_examiner_headers(user_id),
        )
    )
    pctx.presentation = row
    return row


def complying_presentation(
    credit_ctx: CreditContext,
    invoice_amounts: Sequence[int] = (2000000,),
    **kwargs: Any,
) -> PresentationContext:
    """A submitted file with no discrepancies, concluded `COMPLYING` and ready to claim."""
    pctx = submitted_presentation(credit_ctx, invoice_amounts, **kwargs)
    conclude_examination(pctx)
    pctx.refresh()
    return pctx


def discrepant_presentation(
    credit_ctx: CreditContext,
    code: str = "GOODS_DESCRIPTION_MISMATCH",
    severity: str = "MATERIAL",
    invoice_amounts: Sequence[int] = (2000000,),
    **kwargs: Any,
) -> PresentationContext:
    """A submitted file carrying one discrepancy, concluded `DISCREPANT`."""
    pctx = submitted_presentation(credit_ctx, invoice_amounts, **kwargs)
    raise_discrepancy(pctx, code, severity)
    conclude_examination(pctx)
    pctx.refresh()
    return pctx


def request_waiver(
    pctx: PresentationContext,
    discrepancy_codes: Sequence[str],
    user_id: str = DOCUMENT_EXAMINER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_waiver_request(
            pctx.presentation_id,
            f.waiver_request_payload(list(discrepancy_codes), **overrides),
            document_examiner_headers(user_id),
        )
    )


def respond_to_waiver(
    waiver_request_id: str, applicant_id: str, decision: str, **overrides: Any
) -> Dict[str, Any]:
    """The applicant answers under its own id — it is an entity-backed principal."""
    return get_success_data(
        api_client.respond_to_waiver_request(
            waiver_request_id,
            f.waiver_response_payload(decision, **overrides),
            make_applicant_user_headers(applicant_id),
        )
    )


def refuse_presentation(
    pctx: PresentationContext,
    disposal_instruction: str = "RETURN_TO_PRESENTER",
    user_id: str = DOCUMENT_EXAMINER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    row = get_success_data(
        api_client.refuse_presentation(
            pctx.presentation_id,
            f.refusal_payload(disposal_instruction, **overrides),
            document_examiner_headers(user_id),
        )
    )
    pctx.presentation = row
    return row


def list_discrepancy_rows(presentation_id: str, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_discrepancies(
            presentation_id, document_examiner_headers(), params or None
        )
    )


def list_waiver_request_rows(presentation_id: str, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_waiver_requests(
            presentation_id, document_examiner_headers(), params or None
        )
    )


def list_presented_document_rows(presentation_id: str, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_presented_documents(
            presentation_id, document_examiner_headers(), params or None
        )
    )


# ----------------------------------------------------------------------
# Tier 5 — screening
# ----------------------------------------------------------------------
def rescreen_presentation(
    pctx: PresentationContext,
    scope: str = "PRESENTED_DOCUMENTS",
    user_id: str = COMPLIANCE_OFFICER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_presentation_screening(
            pctx.presentation_id,
            f.screening_payload(scope, **overrides),
            compliance_officer_headers(user_id),
        )
    )


def review_screening(
    screening_check_id: str,
    decision: str,
    user_id: str = COMPLIANCE_OFFICER_2,
    **overrides: Any,
) -> Dict[str, Any]:
    """Adjudicate a screening hit.

    The reviewer's identifier must differ from the check's `screened_by_user_id`, so the
    default reviewer is a compliance officer distinct from the screening one.
    """
    return get_success_data(
        api_client.review_screening_check(
            screening_check_id,
            f.screening_review_payload(decision, **overrides),
            compliance_officer_headers(user_id),
        )
    )


def list_presentation_screening_rows(presentation_id: str, **params: Any) -> List[Dict[str, Any]]:
    """Screening checks over one presentation's documents, oldest first."""
    return get_success_data(
        api_client.list_presentation_screenings(
            presentation_id, compliance_officer_headers(), params or None
        )
    )


def newest_presentation_screening(presentation_id: str) -> Dict[str, Any]:
    rows = list_presentation_screening_rows(presentation_id)
    assert rows, f"presentation {presentation_id} carries no screening check"
    return rows[-1]


# ----------------------------------------------------------------------
# Tier 6 — settlement
# ----------------------------------------------------------------------
def lodge_claim(
    pctx: PresentationContext,
    claim_type: str,
    claimed_amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """The presenting bank lodges a claim under its own bank id."""
    return get_success_data(
        api_client.create_settlement_claim(
            pctx.presentation_id,
            f.settlement_claim_payload(claim_type, claimed_amount_cents, **overrides),
            pctx.bank_headers,
        )
    )


def settle_claim(
    claim_id: str, user_id: str = TRADE_FINANCE_OFFICER_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.settle_claim(
            claim_id, f.settle_payload(**overrides), trade_finance_officer_headers(user_id)
        )
    )


def list_claim_rows(presentation_id: str, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_settlement_claims(
            presentation_id, trade_finance_officer_headers(), params or None
        )
    )


def settled_claim(
    pctx: PresentationContext, claim_type: str, claimed_amount_cents: int
) -> Dict[str, Any]:
    """Lodge and settle a claim in one step, returning the settled claim row."""
    claim = lodge_claim(pctx, claim_type, claimed_amount_cents)
    return settle_claim(claim["id"])


# ----------------------------------------------------------------------
# Pytest fixtures — thin wrappers over the builders above
# ----------------------------------------------------------------------
@pytest.fixture
def clock() -> str:
    """Pin the logical clock to the shared reference Monday."""
    return pin_default_clock()


@pytest.fixture
def parties(clock: str) -> Parties:
    return setup_parties()


@pytest.fixture
def drafted_credit(parties: Parties) -> CreditContext:
    return draft_credit(parties)


@pytest.fixture
def credit_awaiting_issue(parties: Parties) -> CreditContext:
    return approved_credit(parties)


@pytest.fixture
def standard_credit(parties: Parties) -> CreditContext:
    """The reference issued credit: USD 10,000,000 at sight on a 50,000,000 facility."""
    return issued_credit(parties)
