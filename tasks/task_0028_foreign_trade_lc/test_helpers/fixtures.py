"""Composite setup helpers for multi-step preconditions.

Walking the PRD's lifecycle from DRAFT to SETTLED requires registering
parties, drafting the LC, submitting, issuing, advising, optionally
confirming, attaching documents, starting examination, primary review,
cross-check, finalize, and finally settling. This module captures the
common multi-call sequences once.

Identity threading (PRD §2.1):

PRD §2.1 explicitly says that for the six entity_backed roles
(Applicant, Beneficiary, IssuingBank, AdvisingBank, ConfirmingBank,
NegotiatingBank) the X-User-ID header is the actual entity id, and
ownership is enforced by comparing X-User-ID to the resource's
applicant_id / beneficiary_id / *_bank_id field. Therefore every helper
that creates an entity records the id and uses make_<role>_headers(id)
on subsequent ownership-gated calls — never the shared TEST_USERS
constant.

For Operator and Auditor PRD §2.1 says the X-User-ID is opaque, so the
shared make_operator_headers helper is canonical. The reviewer
segregation rule (PRD §3.5: 'the secondary must differ from the
primary') still requires distinct operator ids, which is why
make_operator_headers accepts an explicit id.

Setup calls use get_success_data (lenient) so failed pre-conditions
surface as 'Setup failed' messages rather than confusing assertion
mismatches in the assert phase.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    advance_clock_payload,
    advise_payload,
    applicant_decision_payload,
    attach_document_payload,
    bill_of_lading_payload,
    cancel_lc_payload,
    certificate_of_origin_payload,
    commercial_invoice_payload,
    compensate_payload,
    consent_payload,
    create_amendment_payload,
    create_applicant_payload,
    create_bank_payload,
    create_beneficiary_payload,
    create_external_event_payload,
    create_lc_payload,
    create_presentation_payload,
    create_settlement_payload,
    cross_check_payload,
    discrepancy_item,
    dispute_claim_payload,
    primary_review_payload,
    refuse_payload,
    start_examination_payload,
    unique_swift_bic,
)
from .test_users import (
    TEST_USERS,
    make_advising_bank_headers,
    make_applicant_headers,
    make_beneficiary_headers,
    make_confirming_bank_headers,
    make_issuing_bank_headers,
    make_negotiating_bank_headers,
    make_operator_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4 — ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


def add_seconds(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def now_iso() -> str:
    return iso_z(datetime.now(timezone.utc))


# ===========================================================================
# Clock helpers (PRD §3.10 — Operator advances clock)
# ===========================================================================
OPERATOR_HEADERS = TEST_USERS["operator_headers"]


def get_clock() -> Dict[str, Any]:
    res = api_client.get_clock(OPERATOR_HEADERS)
    return get_success_data(res)


def advance_clock_seconds(seconds: int) -> Dict[str, Any]:
    """POST /_clock/advance with Operator headers (PRD §3.10)."""
    res = api_client.advance_clock(
        advance_clock_payload(seconds=seconds), OPERATOR_HEADERS
    )
    return get_success_data(res)


def advance_clock_days(days: int) -> Dict[str, Any]:
    return advance_clock_seconds(days * 86_400)


def advance_clock_banking_days(banking_days: int,
                               start_clock: Optional[str] = None) -> Dict[str, Any]:
    """Advance the server clock by `banking_days` Mon-Fri days (PRD §2.8).

    PRD §2.8: '"Banking days" in this system count Monday through Friday
    strictly greater than the start date and stop counting on Saturday
    and Sunday'. Implementation: advance one calendar day at a time and
    count the days that fall on weekdays.
    """
    if start_clock is None:
        start_clock = get_clock()["now"]
    cur = parse_iso(start_clock)
    counted = 0
    last = None
    while counted < banking_days:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:
            counted += 1
        last = advance_clock_seconds(86_400)
    return last or get_clock()


# ===========================================================================
# Reference-data fixtures (PRD §3.1)
# ===========================================================================
def create_bank(*, bank_role: str = "ISSUING",
                swift_bic: Optional[str] = None,
                **overrides: Any) -> Dict[str, Any]:
    """Operator creates a Bank with the given role (PRD §3.1).

    Returns the Bank dict whose ``id`` is the value tests must use as
    X-User-ID for that bank role on subsequent ownership-gated calls.
    """
    res = api_client.create_bank(
        create_bank_payload(
            bank_role=bank_role,
            swift_bic=swift_bic or unique_swift_bic(),
            **overrides,
        ),
        OPERATOR_HEADERS,
    )
    return get_success_data(res)


def create_applicant(**overrides: Any) -> Dict[str, Any]:
    """Operator registers an Applicant (PRD §3.1)."""
    res = api_client.create_applicant(
        create_applicant_payload(**overrides), OPERATOR_HEADERS
    )
    return get_success_data(res)


def create_beneficiary(**overrides: Any) -> Dict[str, Any]:
    """Operator registers a Beneficiary (PRD §3.1)."""
    res = api_client.create_beneficiary(
        create_beneficiary_payload(**overrides), OPERATOR_HEADERS
    )
    return get_success_data(res)


# ===========================================================================
# Party bundle — the common cast for an LC
# ===========================================================================
def setup_party_bundle(*, with_confirming: bool = False,
                       with_negotiating: bool = False) -> Dict[str, Any]:
    """Register Applicant + Beneficiary + IssuingBank + AdvisingBank
    (and optionally ConfirmingBank, NegotiatingBank) in one call.

    Returns a dict with all entities. Tests use the entity ids both for
    the LC payload and to mint per-role headers.
    """
    applicant = create_applicant()
    beneficiary = create_beneficiary()
    issuing_bank = create_bank(bank_role="ISSUING")
    advising_bank = create_bank(bank_role="ADVISING")
    bundle = {
        "applicant": applicant,
        "beneficiary": beneficiary,
        "issuing_bank": issuing_bank,
        "advising_bank": advising_bank,
        "applicant_headers": make_applicant_headers(applicant["id"]),
        "beneficiary_headers": make_beneficiary_headers(beneficiary["id"]),
        "issuing_bank_headers": make_issuing_bank_headers(issuing_bank["id"]),
        "advising_bank_headers": make_advising_bank_headers(advising_bank["id"]),
    }
    if with_confirming:
        confirming_bank = create_bank(bank_role="CONFIRMING")
        bundle["confirming_bank"] = confirming_bank
        bundle["confirming_bank_headers"] = make_confirming_bank_headers(
            confirming_bank["id"]
        )
    if with_negotiating:
        negotiating_bank = create_bank(bank_role="NEGOTIATING")
        bundle["negotiating_bank"] = negotiating_bank
        bundle["negotiating_bank_headers"] = make_negotiating_bank_headers(
            negotiating_bank["id"]
        )
    return bundle


# ===========================================================================
# Tier 1: LC drafting + lifecycle progression (PRD §3.2 / §3.3)
# ===========================================================================
def _default_dates(*, expiry_days_ahead: int = 90,
                   shipment_days_ahead: int = 30) -> Tuple[str, str]:
    """Return (latest_shipment_date, expiry_date) using current clock."""
    now = parse_iso(get_clock()["now"])
    lsd = iso_z(now + timedelta(days=shipment_days_ahead))
    exp = iso_z(now + timedelta(days=expiry_days_ahead))
    return lsd, exp


def create_lc_draft(
    *,
    bundle: Optional[Dict[str, Any]] = None,
    lc_type: str = "SIGHT",
    amount_minor_units: int = 100_000,
    tolerance_pct: int = 0,
    confirmation_required: bool = False,
    usance_tenor_days: Optional[int] = None,
    latest_shipment_date: Optional[str] = None,
    expiry_date: Optional[str] = None,
    presentation_period_days: Optional[int] = None,
    discrepancy_fee_minor_units: Optional[int] = None,
    required_documents: Optional[List[str]] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Draft an LC. Returns (lc_dict, party_bundle).

    PRD §3.2: 'A corporate buyer acting as Applicant initiates the
    workflow by drafting an LC.' The payload names the parties and the
    financial / shipping terms.
    """
    if bundle is None:
        bundle = setup_party_bundle(
            with_confirming=confirmation_required,
            with_negotiating=False,
        )
    if latest_shipment_date is None or expiry_date is None:
        lsd_default, exp_default = _default_dates()
        latest_shipment_date = latest_shipment_date or lsd_default
        expiry_date = expiry_date or exp_default

    payload = create_lc_payload(
        applicant_id=bundle["applicant"]["id"],
        beneficiary_id=bundle["beneficiary"]["id"],
        issuing_bank_id=bundle["issuing_bank"]["id"],
        advising_bank_id=bundle["advising_bank"]["id"],
        confirming_bank_id=bundle.get("confirming_bank", {}).get("id")
            if confirmation_required else None,
        lc_type=lc_type,
        amount_minor_units=amount_minor_units,
        tolerance_pct=tolerance_pct,
        latest_shipment_date=latest_shipment_date,
        expiry_date=expiry_date,
        confirmation_required=confirmation_required,
        usance_tenor_days=usance_tenor_days,
        presentation_period_days=presentation_period_days,
        discrepancy_fee_minor_units=discrepancy_fee_minor_units,
        required_documents=required_documents,
        **overrides,
    )
    res = api_client.create_lc(payload, bundle["applicant_headers"])
    lc = get_success_data(res)
    return lc, bundle


def submit_lc(lc_id: str, applicant_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.submit_lc(lc_id, applicant_headers)
    return get_success_data(res)


def issue_lc(lc_id: str, issuing_bank_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.issue_lc(lc_id, issuing_bank_headers)
    return get_success_data(res)


def advise_lc(lc_id: str, advising_bank_headers: Dict[str, str],
              *, downstream_advising_bank_bic: Optional[str] = None) -> Dict[str, Any]:
    res = api_client.advise_lc(
        lc_id, advising_bank_headers,
        advise_payload(downstream_advising_bank_bic=downstream_advising_bank_bic),
    )
    return get_success_data(res)


def confirm_lc(lc_id: str, confirming_bank_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.confirm_lc(lc_id, confirming_bank_headers)
    return get_success_data(res)


def get_lc(lc_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_lc(lc_id, headers or OPERATOR_HEADERS)
    return get_success_data(res)


def setup_active_lc(
    *,
    lc_type: str = "SIGHT",
    amount_minor_units: int = 100_000,
    tolerance_pct: int = 0,
    confirmation_required: bool = False,
    usance_tenor_days: Optional[int] = None,
    latest_shipment_date: Optional[str] = None,
    expiry_date: Optional[str] = None,
    presentation_period_days: Optional[int] = None,
    discrepancy_fee_minor_units: Optional[int] = None,
    bundle: Optional[Dict[str, Any]] = None,
    required_documents: Optional[List[str]] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Walk DRAFT → UNDER_REVIEW → ISSUED → ADVISED → ACTIVE (PRD §3.2 / §3.3).

    Returns (active_lc, bundle). When confirmation_required=True the LC
    only reaches ACTIVE after the ConfirmingBank confirms.
    """
    if usance_tenor_days is None and lc_type == "USANCE":
        usance_tenor_days = 60
    lc, bundle = create_lc_draft(
        bundle=bundle,
        lc_type=lc_type,
        amount_minor_units=amount_minor_units,
        tolerance_pct=tolerance_pct,
        confirmation_required=confirmation_required,
        usance_tenor_days=usance_tenor_days,
        latest_shipment_date=latest_shipment_date,
        expiry_date=expiry_date,
        presentation_period_days=presentation_period_days,
        discrepancy_fee_minor_units=discrepancy_fee_minor_units,
        required_documents=required_documents,
        **overrides,
    )
    submit_lc(lc["id"], bundle["applicant_headers"])
    issue_lc(lc["id"], bundle["issuing_bank_headers"])
    advise_lc(lc["id"], bundle["advising_bank_headers"])
    if confirmation_required:
        confirm_lc(lc["id"], bundle["confirming_bank_headers"])
    return get_lc(lc["id"], bundle["applicant_headers"]), bundle


# ===========================================================================
# Tier 2: Presentation + documents + examination (PRD §3.5 / §3.6)
# ===========================================================================
def create_presentation(
    *,
    lc_id: str,
    beneficiary_headers: Dict[str, str],
    drawing_amount_minor_units: int,
    shipment_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Beneficiary submits a presentation (PRD §3.5)."""
    if shipment_date is None:
        shipment_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
    res = api_client.create_presentation(
        lc_id,
        create_presentation_payload(
            shipment_date=shipment_date,
            drawing_amount_minor_units=drawing_amount_minor_units,
        ),
        beneficiary_headers,
    )
    return get_success_data(res)


def attach_commercial_invoice(presentation_id: str,
                              beneficiary_headers: Dict[str, str],
                              *, stated_amount_minor_units: int,
                              currency: str = "USD",
                              country_of_origin: str = "CN",
                              **overrides: Any) -> Dict[str, Any]:
    res = api_client.attach_document(
        presentation_id,
        commercial_invoice_payload(
            stated_amount_minor_units=stated_amount_minor_units,
            currency=currency,
            country_of_origin=country_of_origin,
            **overrides,
        ),
        beneficiary_headers,
    )
    return get_success_data(res)


def attach_bill_of_lading(presentation_id: str,
                          beneficiary_headers: Dict[str, str],
                          *, shipped_on_board_date: str,
                          currency: str = "USD",
                          **overrides: Any) -> Dict[str, Any]:
    res = api_client.attach_document(
        presentation_id,
        bill_of_lading_payload(
            shipped_on_board_date=shipped_on_board_date,
            currency=currency,
            **overrides,
        ),
        beneficiary_headers,
    )
    return get_success_data(res)


def attach_certificate_of_origin(presentation_id: str,
                                 beneficiary_headers: Dict[str, str],
                                 *, country_of_origin: str = "CN",
                                 currency: str = "USD",
                                 **overrides: Any) -> Dict[str, Any]:
    res = api_client.attach_document(
        presentation_id,
        certificate_of_origin_payload(
            country_of_origin=country_of_origin,
            currency=currency,
            **overrides,
        ),
        beneficiary_headers,
    )
    return get_success_data(res)


def setup_presentation_with_clean_documents(
    *,
    lc: Dict[str, Any],
    bundle: Dict[str, Any],
    drawing_amount_minor_units: Optional[int] = None,
    country_of_origin: str = "CN",
    include_certificate_of_origin: bool = False,
    shipped_on_board_date: Optional[str] = None,
    shipment_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit a Presentation and attach a CLEAN-eligible document set.

    Default: COMMERCIAL_INVOICE matching LC.amount + BILL_OF_LADING with a
    valid shipped_on_board_date. PRD §3.6 I1..I7 must all hold.
    """
    if drawing_amount_minor_units is None:
        drawing_amount_minor_units = lc["amount_minor_units"]
    if shipment_date is None:
        shipment_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
    if shipped_on_board_date is None:
        shipped_on_board_date = shipment_date

    presentation = create_presentation(
        lc_id=lc["id"],
        beneficiary_headers=bundle["beneficiary_headers"],
        drawing_amount_minor_units=drawing_amount_minor_units,
        shipment_date=shipment_date,
    )
    attach_commercial_invoice(
        presentation["id"], bundle["beneficiary_headers"],
        stated_amount_minor_units=drawing_amount_minor_units,
        currency=lc["currency"],
        country_of_origin=country_of_origin,
    )
    attach_bill_of_lading(
        presentation["id"], bundle["beneficiary_headers"],
        shipped_on_board_date=shipped_on_board_date,
        currency=lc["currency"],
    )
    if include_certificate_of_origin:
        attach_certificate_of_origin(
            presentation["id"], bundle["beneficiary_headers"],
            country_of_origin=country_of_origin,
            currency=lc["currency"],
        )
    return presentation


def get_presentation(presentation_id: str,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_presentation(
        presentation_id, headers or OPERATOR_HEADERS,
    )
    return get_success_data(res)


# Reviewer ids — PRD §3.5 requires distinct primary/secondary.
DEFAULT_PRIMARY_REVIEWER_ID = "op-primary-001"
DEFAULT_SECONDARY_REVIEWER_ID = "op-secondary-001"


def start_examination(
    presentation_id: str,
    issuing_bank_headers: Dict[str, str],
    *,
    primary_reviewer_id: str = DEFAULT_PRIMARY_REVIEWER_ID,
    secondary_reviewer_id: str = DEFAULT_SECONDARY_REVIEWER_ID,
) -> Dict[str, Any]:
    """IssuingBank starts examination, naming both reviewers (PRD §3.5)."""
    res = api_client.start_examination(
        presentation_id,
        start_examination_payload(
            primary_reviewer_id=primary_reviewer_id,
            secondary_reviewer_id=secondary_reviewer_id,
        ),
        issuing_bank_headers,
    )
    return get_success_data(res)


def primary_review_clean(examination_id: str,
                         primary_reviewer_id: str = DEFAULT_PRIMARY_REVIEWER_ID
                         ) -> Dict[str, Any]:
    res = api_client.primary_review(
        examination_id,
        primary_review_payload(primary_outcome="CLEAN"),
        make_operator_headers(primary_reviewer_id),
    )
    return get_success_data(res)


def primary_review_discrepant(examination_id: str,
                              discrepancies: List[Dict[str, Any]],
                              primary_reviewer_id: str = DEFAULT_PRIMARY_REVIEWER_ID,
                              ) -> Dict[str, Any]:
    res = api_client.primary_review(
        examination_id,
        primary_review_payload(
            primary_outcome="DISCREPANT", discrepancies=discrepancies,
        ),
        make_operator_headers(primary_reviewer_id),
    )
    return get_success_data(res)


def cross_check_clean(examination_id: str,
                      secondary_reviewer_id: str = DEFAULT_SECONDARY_REVIEWER_ID,
                      ) -> Dict[str, Any]:
    res = api_client.cross_check(
        examination_id,
        cross_check_payload(secondary_outcome="CLEAN"),
        make_operator_headers(secondary_reviewer_id),
    )
    return get_success_data(res)


def cross_check_discrepant(examination_id: str,
                           discrepancies: List[Dict[str, Any]],
                           secondary_reviewer_id: str = DEFAULT_SECONDARY_REVIEWER_ID,
                           ) -> Dict[str, Any]:
    res = api_client.cross_check(
        examination_id,
        cross_check_payload(
            secondary_outcome="DISCREPANT", discrepancies=discrepancies,
        ),
        make_operator_headers(secondary_reviewer_id),
    )
    return get_success_data(res)


def finalize_examination(examination_id: str,
                         issuing_bank_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.finalize_examination(examination_id, issuing_bank_headers)
    return get_success_data(res)


def reset_examination(examination_id: str,
                      issuing_bank_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.reset_examination(examination_id, issuing_bank_headers)
    return get_success_data(res)


# ===========================================================================
# Tier 3: Walk Presentation through to EXAMINED_CLEAN / EXAMINED_DISCREPANT
# ===========================================================================
def setup_examined_clean_presentation(
    *,
    lc: Optional[Dict[str, Any]] = None,
    bundle: Optional[Dict[str, Any]] = None,
    drawing_amount_minor_units: Optional[int] = None,
    confirmation_required: bool = False,
    lc_type: str = "SIGHT",
    usance_tenor_days: Optional[int] = None,
    amount_minor_units: int = 100_000,
    tolerance_pct: int = 0,
    expiry_date: Optional[str] = None,
    latest_shipment_date: Optional[str] = None,
    discrepancy_fee_minor_units: Optional[int] = None,
    include_certificate_of_origin: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk through to Presentation.status=EXAMINED_CLEAN.

    Returns (lc, bundle, presentation, examination_report).
    """
    if lc is None:
        # When the caller asks for a CERTIFICATE_OF_ORIGIN attachment, the
        # LC's required_documents list must include it (PRD §3.5: a
        # document is rejected with ERR_DOCUMENT_NOT_REQUIRED_OR_DUPLICATE
        # when its document_type does not appear in required_documents).
        required_documents = (
            ["COMMERCIAL_INVOICE", "BILL_OF_LADING", "CERTIFICATE_OF_ORIGIN"]
            if include_certificate_of_origin
            else None
        )
        lc, bundle = setup_active_lc(
            lc_type=lc_type,
            usance_tenor_days=usance_tenor_days,
            amount_minor_units=amount_minor_units,
            tolerance_pct=tolerance_pct,
            confirmation_required=confirmation_required,
            expiry_date=expiry_date,
            latest_shipment_date=latest_shipment_date,
            discrepancy_fee_minor_units=discrepancy_fee_minor_units,
            required_documents=required_documents,
        )
    assert bundle is not None, "Setup failed: bundle required when lc supplied"

    presentation = setup_presentation_with_clean_documents(
        lc=lc, bundle=bundle,
        drawing_amount_minor_units=drawing_amount_minor_units,
        include_certificate_of_origin=include_certificate_of_origin,
    )
    examination = start_examination(
        presentation["id"], bundle["issuing_bank_headers"],
    )
    primary_review_clean(examination["id"])
    cross_check_clean(examination["id"])
    finalize_examination(examination["id"], bundle["issuing_bank_headers"])
    presentation = get_presentation(presentation["id"], bundle["beneficiary_headers"])
    return lc, bundle, presentation, examination


def setup_examined_discrepant_presentation(
    *,
    lc: Optional[Dict[str, Any]] = None,
    bundle: Optional[Dict[str, Any]] = None,
    drawing_amount_minor_units: Optional[int] = None,
    discrepancy_codes: Optional[List[str]] = None,
    amount_minor_units: int = 100_000,
    tolerance_pct: int = 0,
    discrepancy_fee_minor_units: Optional[int] = None,
    expiry_date: Optional[str] = None,
    latest_shipment_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk to Presentation.status=EXAMINED_DISCREPANT (with both reviewers
    flagging the same discrepancy code so the report finalises DISCREPANT).
    """
    if discrepancy_codes is None:
        discrepancy_codes = ["MISSING_DOCUMENT"]
    if lc is None:
        lc, bundle = setup_active_lc(
            amount_minor_units=amount_minor_units,
            tolerance_pct=tolerance_pct,
            expiry_date=expiry_date,
            latest_shipment_date=latest_shipment_date,
            discrepancy_fee_minor_units=discrepancy_fee_minor_units,
        )
    assert bundle is not None
    presentation = setup_presentation_with_clean_documents(
        lc=lc, bundle=bundle,
        drawing_amount_minor_units=drawing_amount_minor_units,
    )
    examination = start_examination(
        presentation["id"], bundle["issuing_bank_headers"],
    )
    items = [discrepancy_item(discrepancy_code=c) for c in discrepancy_codes]
    primary_review_discrepant(examination["id"], items)
    cross_check_discrepant(examination["id"], items)
    finalize_examination(examination["id"], bundle["issuing_bank_headers"])
    presentation = get_presentation(presentation["id"], bundle["beneficiary_headers"])
    return lc, bundle, presentation, examination


# ===========================================================================
# Tier 4: Discrepancy / refusal / settlement variants (PRD §3.7 / §3.8)
# ===========================================================================
def applicant_decision_accept(presentation_id: str,
                              applicant_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.applicant_decision(
        presentation_id, applicant_decision_payload(decision="ACCEPTED"),
        applicant_headers,
    )
    return get_success_data(res)


def applicant_decision_reject(presentation_id: str,
                              applicant_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.applicant_decision(
        presentation_id, applicant_decision_payload(decision="REJECTED"),
        applicant_headers,
    )
    return get_success_data(res)


def refuse_presentation(presentation_id: str,
                        issuing_bank_headers: Dict[str, str],
                        *, refusal_reason: str = "documents discrepant"
                        ) -> Dict[str, Any]:
    res = api_client.refuse_presentation(
        presentation_id, refuse_payload(refusal_reason=refusal_reason),
        issuing_bank_headers,
    )
    return get_success_data(res)


def applicant_override(presentation_id: str,
                       applicant_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.applicant_override(presentation_id, applicant_headers)
    return get_success_data(res)


# ----- Settlement helpers ----------------------------------------------
def create_sight_settlement(presentation_id: str,
                            issuing_bank_headers: Dict[str, str],
                            ) -> Dict[str, Any]:
    res = api_client.create_settlement(
        presentation_id, create_settlement_payload(), issuing_bank_headers,
    )
    return get_success_data(res)


def create_negotiation_settlement(presentation_id: str,
                                  negotiating_bank_headers: Dict[str, str],
                                  ) -> Dict[str, Any]:
    """Create a settlement with settlement_type_override=NEGOTIATION
    (PRD §3.8 — only legal override; restricted to NegotiatingBank flows).
    """
    res = api_client.create_settlement(
        presentation_id,
        create_settlement_payload(settlement_type_override="NEGOTIATION"),
        negotiating_bank_headers,
    )
    return get_success_data(res)


def execute_sight(settlement_id: str,
                  issuing_bank_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.execute_sight(settlement_id, issuing_bank_headers)
    return get_success_data(res)


def record_acceptance(settlement_id: str,
                      issuing_bank_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.record_acceptance(settlement_id, issuing_bank_headers)
    return get_success_data(res)


def negotiation_advance(settlement_id: str,
                        negotiating_bank_headers: Dict[str, str]
                        ) -> Dict[str, Any]:
    res = api_client.negotiation_advance(settlement_id, negotiating_bank_headers)
    return get_success_data(res)


def compensate_settlement(settlement_id: str,
                          issuing_bank_headers: Dict[str, str],
                          *, reason: str = "reimbursement-disputed",
                          ) -> Dict[str, Any]:
    res = api_client.compensate_settlement(
        settlement_id, compensate_payload(reason=reason),
        issuing_bank_headers,
    )
    return get_success_data(res)


# ----- Reimbursement helpers ------------------------------------------
def honor_claim(claim_id: str,
                issuing_bank_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.honor_claim(claim_id, issuing_bank_headers)
    return get_success_data(res)


def dispute_claim(claim_id: str,
                  issuing_bank_headers: Dict[str, str],
                  *, reason: str = "discrepancy") -> Dict[str, Any]:
    res = api_client.dispute_claim(
        claim_id, dispute_claim_payload(reason=reason),
        issuing_bank_headers,
    )
    return get_success_data(res)


def extinguish_claim(claim_id: str,
                     negotiating_bank_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.extinguish_claim(claim_id, negotiating_bank_headers)
    return get_success_data(res)


# ===========================================================================
# Tier 5: Full-lifecycle composite shortcuts
# ===========================================================================
def setup_paid_sight_settlement(
    *, amount_minor_units: int = 100_000,
    drawing_amount_minor_units: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk an LC to PaymentSettlement.status=PAID via the SIGHT path.

    Returns (lc_after, bundle, presentation_after, settlement_after).
    """
    lc, bundle, presentation, _examination = setup_examined_clean_presentation(
        amount_minor_units=amount_minor_units,
        drawing_amount_minor_units=drawing_amount_minor_units,
    )
    settlement = create_sight_settlement(
        presentation["id"], bundle["issuing_bank_headers"],
    )
    settlement = execute_sight(
        settlement["id"], bundle["issuing_bank_headers"],
    )
    lc_after = get_lc(lc["id"], bundle["applicant_headers"])
    presentation_after = get_presentation(
        presentation["id"], bundle["beneficiary_headers"],
    )
    return lc_after, bundle, presentation_after, settlement


def setup_negotiation_paid_settlement(
    *,
    amount_minor_units: int = 200_000,
    drawing_amount_minor_units: int = 80_000,
    discrepancy_fee_minor_units: int = 7_500,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk an LC to PaymentSettlement.status=PAID via the NEGOTIATION path,
    auto-creating the ReimbursementClaim (PRD §3.8 / §3.9).

    Returns (lc_after, bundle, presentation, settlement_after, claim).
    """
    bundle = setup_party_bundle(with_negotiating=True)
    lc, _ = setup_active_lc(
        bundle=bundle,
        lc_type="SIGHT",
        amount_minor_units=amount_minor_units,
        discrepancy_fee_minor_units=discrepancy_fee_minor_units,
    )
    _, _, presentation, _ = setup_examined_clean_presentation(
        lc=lc, bundle=bundle,
        drawing_amount_minor_units=drawing_amount_minor_units,
    )
    settlement = api_client.create_settlement(
        presentation["id"],
        create_settlement_payload(settlement_type_override="NEGOTIATION"),
        bundle["negotiating_bank_headers"],
    )
    settlement = get_success_data(settlement)
    settlement = negotiation_advance(
        settlement["id"], bundle["negotiating_bank_headers"],
    )
    # ReimbursementClaim is auto-created with payment_settlement_id == S.id.
    # Fetch it via the get-settlement response if implementations expose
    # a claim_id field, otherwise discover it through a list. Per PRD §3.9
    # the claim is reachable directly via /reimbursement-claims/{claim_id}
    # but the only doc-level handle is on the settlement; we'll search by
    # iterating the audit log.
    claim_id = _find_reimbursement_claim_id_for_settlement(
        lc_id=lc["id"], settlement_id=settlement["id"],
        operator_or_issuing_headers=bundle["issuing_bank_headers"],
    )
    if claim_id is None:
        # Some implementations expose the claim id directly on the
        # settlement payload; check that as a secondary lookup.
        claim_id = settlement.get("reimbursement_claim_id")
    claim = None
    if claim_id is not None:
        claim_res = api_client.get_reimbursement_claim(
            claim_id, bundle["issuing_bank_headers"],
        )
        claim = get_success_data(claim_res)
    lc_after = get_lc(lc["id"], bundle["applicant_headers"])
    return lc_after, bundle, presentation, settlement, claim


def _find_reimbursement_claim_id_for_settlement(
    *, lc_id: str, settlement_id: str,
    operator_or_issuing_headers: Dict[str, str],
) -> Optional[str]:
    """Best-effort lookup of the auto-created ReimbursementClaim's id.

    PRD §3.10 §2.10: the audit log records every state change including
    the auto-creation of the claim. If the implementation surfaces it on
    the settlement payload directly we read that; otherwise we scan the
    LC's audit log for a REIMBURSEMENT subject row.
    """
    # Paginate through the audit log (PRD §2.10) — a negotiation-advance
    # follow-on cascade entry can land well beyond the default page size.
    offset = 0
    page_size = 100
    while True:
        res = api_client.list_audit_log(
            lc_id, operator_or_issuing_headers,
            params={"limit": page_size, "offset": offset},
        )
        payload = get_success_data(res)
        entries = payload if isinstance(payload, list) else payload.get("entries", payload)
        if isinstance(entries, dict):
            entries = []
        if not entries:
            return None
        for e in entries:
            if e.get("subject_type") == "REIMBURSEMENT":
                return e.get("subject_id")
        if len(entries) < page_size:
            return None
        offset += page_size


def setup_disputed_reimbursement_chain(
    *,
    amount_minor_units: int = 200_000,
    drawing_amount_minor_units: int = 80_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Run the negotiation-paid setup, then dispute the claim — yields
    the cascade ReimbursementClaim.SUBMITTED→DISPUTED → settlement
    PAID→COMPENSATED → LC.drawn_amount decremented (PRD §3.9 / §3.8).

    Returns (lc_after, bundle, presentation_after, settlement_after, claim_after).
    """
    lc, bundle, presentation, settlement, claim = setup_negotiation_paid_settlement(
        amount_minor_units=amount_minor_units,
        drawing_amount_minor_units=drawing_amount_minor_units,
    )
    assert claim is not None and claim.get("id"), (
        "Setup failed: ReimbursementClaim id not found after negotiation-advance"
    )
    claim_after = dispute_claim(claim["id"], bundle["issuing_bank_headers"])
    settlement_after = api_client.get_settlement(
        settlement["id"], bundle["issuing_bank_headers"],
    )
    settlement_after = get_success_data(settlement_after)
    presentation_after = get_presentation(
        presentation["id"], bundle["beneficiary_headers"],
    )
    lc_after = get_lc(lc["id"], bundle["applicant_headers"])
    return lc_after, bundle, presentation_after, settlement_after, claim_after


# ===========================================================================
# Tier 6: Pending amendment shortcut (PRD §3.4)
# ===========================================================================
def initiate_amendment(lc_id: str,
                       issuing_bank_headers: Dict[str, str],
                       *, changes: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.create_amendment(
        lc_id, create_amendment_payload(changes=changes),
        issuing_bank_headers,
    )
    return get_success_data(res)


def applicant_consent_amendment(lc_id: str, amendment_id: str,
                                applicant_headers: Dict[str, str],
                                *, decision: str) -> Dict[str, Any]:
    res = api_client.applicant_consent(
        lc_id, amendment_id, consent_payload(decision=decision),
        applicant_headers,
    )
    return get_success_data(res)


def beneficiary_consent_amendment(lc_id: str, amendment_id: str,
                                  beneficiary_headers: Dict[str, str],
                                  *, decision: str) -> Dict[str, Any]:
    res = api_client.beneficiary_consent(
        lc_id, amendment_id, consent_payload(decision=decision),
        beneficiary_headers,
    )
    return get_success_data(res)


def confirming_bank_consent_amendment(lc_id: str, amendment_id: str,
                                      confirming_bank_headers: Dict[str, str],
                                      *, decision: str) -> Dict[str, Any]:
    res = api_client.confirming_bank_consent(
        lc_id, amendment_id, consent_payload(decision=decision),
        confirming_bank_headers,
    )
    return get_success_data(res)


def withdraw_amendment(lc_id: str, amendment_id: str,
                       issuing_bank_headers: Dict[str, str]) -> Dict[str, Any]:
    res = api_client.withdraw_amendment(
        lc_id, amendment_id, issuing_bank_headers,
    )
    return get_success_data(res)


def setup_pending_amendment(
    *,
    amount_minor_units: int = 100_000,
    changes: Optional[Dict[str, Any]] = None,
    confirmation_required: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build an ACTIVE LC with a PENDING amendment.

    Returns (lc, bundle, amendment).
    """
    lc, bundle = setup_active_lc(
        amount_minor_units=amount_minor_units,
        confirmation_required=confirmation_required,
    )
    if changes is None:
        changes = {"amount_minor_units": amount_minor_units + 50_000}
    amendment = initiate_amendment(
        lc["id"], bundle["issuing_bank_headers"], changes=changes,
    )
    return lc, bundle, amendment


__all__ = [
    # time helpers
    "iso_z", "parse_iso", "add_days", "add_seconds", "now_iso",
    # clock
    "OPERATOR_HEADERS", "get_clock", "advance_clock_seconds",
    "advance_clock_days", "advance_clock_banking_days",
    # reference data
    "create_bank", "create_applicant", "create_beneficiary",
    "setup_party_bundle",
    # LC lifecycle
    "create_lc_draft", "submit_lc", "issue_lc", "advise_lc",
    "confirm_lc", "get_lc", "setup_active_lc",
    # presentation / documents
    "create_presentation", "attach_commercial_invoice",
    "attach_bill_of_lading", "attach_certificate_of_origin",
    "setup_presentation_with_clean_documents", "get_presentation",
    # examination
    "DEFAULT_PRIMARY_REVIEWER_ID", "DEFAULT_SECONDARY_REVIEWER_ID",
    "start_examination",
    "primary_review_clean", "primary_review_discrepant",
    "cross_check_clean", "cross_check_discrepant",
    "finalize_examination", "reset_examination",
    # composite progressions
    "setup_examined_clean_presentation",
    "setup_examined_discrepant_presentation",
    # discrepancy / refusal
    "applicant_decision_accept", "applicant_decision_reject",
    "refuse_presentation", "applicant_override",
    # settlement
    "create_sight_settlement", "create_negotiation_settlement",
    "execute_sight", "record_acceptance", "negotiation_advance",
    "compensate_settlement",
    # reimbursement
    "honor_claim", "dispute_claim", "extinguish_claim",
    # full lifecycle shortcuts
    "setup_paid_sight_settlement", "setup_negotiation_paid_settlement",
    "setup_disputed_reimbursement_chain",
    # amendment
    "initiate_amendment", "applicant_consent_amendment",
    "beneficiary_consent_amendment", "confirming_bank_consent_amendment",
    "withdraw_amendment", "setup_pending_amendment",
]
