"""Composite setup helpers — multi-step preambles tests can reuse.

PRD §2.12 clock semantics: POST /customs/_clock/advance moves the
logical clock; POST /customs/_events/emit drives external-event-triggered
transitions. These fixtures use the SystemAdmin headers for those calls.

IDENTITY THREADING — PRD §2.1: ClientUser is entity-backed
("X-User-ID is the id of the acting ClientCompany"). Ownership-gated
ClientUser calls — POST /customs/agreements/{id}/sign,
POST /customs/declarations/{id}/documents (as the consignor),
POST /customs/inspection-cases/{id}/provide-sample, and the
GET reads on owned clients/declarations/settlements — MUST use
make_client_user_headers(client_company["id"]). Falling back to the
shared TEST_USERS["client_user_headers"] constant binds X-User-ID to
an id that does not equal any real ClientCompany.id; ownership-checks
would then reject every request regardless of the implementation.

PRD §2.9 segregation-of-duties: pre-validate / file MUST use distinct
opaque DocReviewer / FilingOfficer ids; file / advance MUST use
distinct FilingOfficer / SettlementOfficer ids. Fixtures pin distinct
defaults so consumers don't have to remember.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    action_with_version_payload,
    advance_settlement_payload,
    attach_document_payload,
    clock_advance_payload,
    create_agreement_payload,
    create_client_payload,
    create_declaration_payload,
    create_inspection_case_payload,
    emit_bank_debit_payload,
    emit_customs_response_payload,
    emit_manifest_dropped_payload,
    iso_utc,
    random_legal_name,
    random_shipment_reference,
    random_tax_id,
    record_outcome_payload,
    request_signature_payload,
    respond_query_payload,
    sign_agreement_payload,
    terminate_agreement_payload,
)
from .test_users import (
    BROKER_OPS_ID,
    DECLARATION_OFFICER_ID,
    DOC_REVIEWER_ID,
    FILING_OFFICER_ID,
    INSPECTION_OFFICER_ID,
    SETTLEMENT_OFFICER_ID,
    SYSTEM_ADMIN_ID,
    TEST_USERS,
    make_broker_ops_headers,
    make_client_user_headers,
    make_declaration_officer_headers,
    make_doc_reviewer_headers,
    make_filing_officer_headers,
    make_inspection_officer_headers,
    make_settlement_officer_headers,
    make_system_admin_headers,
)


# Logical-clock anchor (PRD §2.12). All fixtures reset to this before
# running so time-gated tests have a known origin.
TEST_EPOCH = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
DEFAULT_VALID_FROM = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
DEFAULT_VALID_UNTIL = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Header helpers
# ---------------------------------------------------------------------------
def _broker() -> Dict[str, str]:
    return TEST_USERS["broker_ops_headers"]


def _dec_officer() -> Dict[str, str]:
    return TEST_USERS["declaration_officer_headers"]


def _doc_reviewer() -> Dict[str, str]:
    return TEST_USERS["doc_reviewer_headers"]


def _filing_officer() -> Dict[str, str]:
    return TEST_USERS["filing_officer_headers"]


def _settle_officer() -> Dict[str, str]:
    return TEST_USERS["settlement_officer_headers"]


def _insp_officer() -> Dict[str, str]:
    return TEST_USERS["inspection_officer_headers"]


def _sysadmin() -> Dict[str, str]:
    return TEST_USERS["system_admin_headers"]


def _data(resp) -> Dict[str, Any]:
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock control (PRD §2.12)
# ---------------------------------------------------------------------------
def advance_clock_to(target: datetime) -> str:
    iso = iso_utc(target)
    _data(api_client.clock_advance(clock_advance_payload(iso), _sysadmin()))
    return iso


def reset_clock_to_epoch() -> str:
    return advance_clock_to(TEST_EPOCH)


# ---------------------------------------------------------------------------
# Tier 1 — primitives
# ---------------------------------------------------------------------------
def create_client(default_settlement_currency: str = "CNY",
                  country_code: str = "CN",
                  **overrides: Any) -> Dict[str, Any]:
    """Create a ClientCompany (PRD §3.1). The created entity's id is the
    value a ClientUser must pass as X-User-ID for ownership-gated calls
    (see PRD §2.1 / make_client_user_headers)."""
    payload = create_client_payload(
        default_settlement_currency=default_settlement_currency,
        country_code=country_code,
        **overrides,
    )
    return _data(api_client.create_client(payload, _broker()))


def create_agreement(
    client_id: str,
    *,
    scope_of_service: Optional[List[str]] = None,
    fee_schedule: Optional[Dict[str, float]] = None,
    agreement_currency: str = "USD",
    valid_from: Optional[datetime] = None,
    valid_until: Optional[datetime] = None,
    late_interest_daily_rate_bps: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create an agreement in DRAFT (PRD §3.1)."""
    vf = valid_from or DEFAULT_VALID_FROM
    vu = valid_until or DEFAULT_VALID_UNTIL
    payload = create_agreement_payload(
        client_id=client_id,
        scope_of_service=scope_of_service,
        fee_schedule=fee_schedule,
        agreement_currency=agreement_currency,
        valid_from=iso_utc(vf),
        valid_until=iso_utc(vu),
        late_interest_daily_rate_bps=late_interest_daily_rate_bps,
        **overrides,
    )
    return _data(api_client.create_agreement(payload, _broker()))


def request_signature(agreement: Dict[str, Any]) -> Dict[str, Any]:
    """DRAFT → AWAITING_SIGNATURE (PRD §3.2)."""
    return _data(api_client.request_signature(
        agreement["id"],
        request_signature_payload(version=agreement["version"]),
        _broker(),
    ))


def sign_agreement(agreement: Dict[str, Any], client_id: str) -> Dict[str, Any]:
    """AWAITING_SIGNATURE → ACTIVE (PRD §3.2). client_id is the
    ClientCompany.id; PRD §2.1 entity-backed identity rule applies."""
    return _data(api_client.sign_agreement(
        agreement["id"],
        sign_agreement_payload(
            signature_token=agreement["signature_token"],
            version=agreement["version"],
        ),
        make_client_user_headers(client_id),
    ))


def activate_agreement(client_id: str,
                       *,
                       scope_of_service: Optional[List[str]] = None,
                       fee_schedule: Optional[Dict[str, float]] = None,
                       agreement_currency: str = "USD",
                       valid_from: Optional[datetime] = None,
                       valid_until: Optional[datetime] = None,
                       late_interest_daily_rate_bps: int = 100,
                       **overrides: Any) -> Dict[str, Any]:
    """Walk DRAFT → AWAITING_SIGNATURE → ACTIVE in one call."""
    agreement = create_agreement(
        client_id,
        scope_of_service=scope_of_service,
        fee_schedule=fee_schedule,
        agreement_currency=agreement_currency,
        valid_from=valid_from,
        valid_until=valid_until,
        late_interest_daily_rate_bps=late_interest_daily_rate_bps,
        **overrides,
    )
    agreement = request_signature(agreement)
    return sign_agreement(agreement, client_id)


# ---------------------------------------------------------------------------
# Tier 2 — composite client + agreement scaffolding
# ---------------------------------------------------------------------------
def setup_active_agreement(
    *,
    default_settlement_currency: str = "CNY",
    country_code: str = "CN",
    agreement_currency: str = "USD",
    scope_of_service: Optional[List[str]] = None,
    fee_schedule: Optional[Dict[str, float]] = None,
    valid_from: Optional[datetime] = None,
    valid_until: Optional[datetime] = None,
    late_interest_daily_rate_bps: int = 100,
    client_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """ClientCompany + ACTIVE CommissionAgreement.

    Returns (client, agreement). client["id"] is the ClientCompany.id
    that a ClientUser MUST pass as X-User-ID for any ownership-gated
    call (PRD §2.1)."""
    client = create_client(
        default_settlement_currency=default_settlement_currency,
        country_code=country_code,
        **(client_overrides or {}),
    )
    agreement = activate_agreement(
        client["id"],
        scope_of_service=scope_of_service,
        fee_schedule=fee_schedule,
        agreement_currency=agreement_currency,
        valid_from=valid_from,
        valid_until=valid_until,
        late_interest_daily_rate_bps=late_interest_daily_rate_bps,
    )
    return client, agreement


# ---------------------------------------------------------------------------
# Declaration primitives
# ---------------------------------------------------------------------------
def create_declaration(
    agreement_id: str,
    *,
    jurisdiction_code: str = "CN",
    hs_code: str = "85171200",
    country_of_origin: str = "JP",
    trade_agreement_code: Optional[str] = "NONE",
    declared_value_amount: float = 1000.00,
    declared_currency: str = "USD",
    shipment_reference: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_declaration_payload(
        agreement_id=agreement_id,
        jurisdiction_code=jurisdiction_code,
        shipment_reference=shipment_reference or random_shipment_reference(),
        hs_code=hs_code,
        country_of_origin=country_of_origin,
        trade_agreement_code=trade_agreement_code,
        declared_value_amount=declared_value_amount,
        declared_currency=declared_currency,
        **overrides,
    )
    return _data(api_client.create_declaration(payload, _dec_officer()))


def request_documents(declaration: Dict[str, Any]) -> Dict[str, Any]:
    """DRAFT → DOCS_PENDING (PRD §3.4)."""
    return _data(api_client.request_documents(
        declaration["id"],
        action_with_version_payload(version=declaration["version"]),
        _dec_officer(),
    ))


def attach_document(
    declaration_id: str,
    *,
    doc_type: str,
    storage_uri: Optional[str] = None,
    declared_total_value: Optional[float] = None,
    declared_total_currency: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach a ShipmentDocument (PRD §3.4). Acted as DeclarationOfficer
    (the role shares the endpoint with ClientUser).

    The default URI uses an all-lowercase-letters scheme so PRD §3.4's
    authenticity signal 3 ("one or more lowercase scheme letters followed
    by ``://`` and at least one character") scores 1.0 — avoiding spurious
    FLAGGED defaults from schemes like ``s3`` that contain a digit.
    """
    payload = attach_document_payload(
        doc_type=doc_type,
        storage_uri=storage_uri or f"https://docs/{doc_type.lower()}-{random_tax_id('FILE')}.pdf",
        declared_total_value=declared_total_value,
        declared_total_currency=declared_total_currency,
    )
    return _data(api_client.attach_document(declaration_id, payload, _dec_officer()))


def attach_core_docs(
    declaration_id: str,
    *,
    invoice_total: float = 1000.00,
    invoice_currency: str = "USD",
    packing_list_total: Optional[float] = None,
    packing_list_currency: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Attach the four core documents (PRD §3.4 / §3.5).

    Sets invoice/packing-list totals so the cross-document consistency
    check (V-DOC-CONSISTENCY) and authenticity total-match signal both
    PASS by default. Pass overrides to break a specific check.

    PRD §3.4: the provisional authenticity screen runs only against
    siblings that exist at insert time; a later sibling does not retroact.
    To force a fresh score against the full sibling set, this helper
    re-runs the DocReviewer ``/screen`` capability on COMMERCIAL_INVOICE
    once PACKING_LIST is in place. Without this step the invoice would
    remain FLAGGED (no partner at insert) and pre-validate would be
    blocked by ERR_DOC_AUTHENTICITY_FLAGGED.

    Returns {'COMMERCIAL_INVOICE': doc, 'PACKING_LIST': doc, ...}.
    """
    if packing_list_total is None:
        packing_list_total = invoice_total
    if packing_list_currency is None:
        packing_list_currency = invoice_currency

    docs: Dict[str, Any] = {}
    docs["COMMERCIAL_INVOICE"] = attach_document(
        declaration_id, doc_type="COMMERCIAL_INVOICE",
        declared_total_value=invoice_total,
        declared_total_currency=invoice_currency,
    )
    docs["PACKING_LIST"] = attach_document(
        declaration_id, doc_type="PACKING_LIST",
        declared_total_value=packing_list_total,
        declared_total_currency=packing_list_currency,
    )
    docs["BILL_OF_LADING"] = attach_document(
        declaration_id, doc_type="BILL_OF_LADING",
    )
    docs["CONTRACT"] = attach_document(
        declaration_id, doc_type="CONTRACT",
    )
    # PRD §3.4: re-screen the invoice so its score is recomputed against
    # the now-present PACKING_LIST sibling. The DocReviewer screen
    # capability returns the refreshed doc.
    invoice = docs["COMMERCIAL_INVOICE"]
    docs["COMMERCIAL_INVOICE"] = _data(api_client.screen_document(
        invoice["id"],
        action_with_version_payload(version=invoice["version"]),
        _doc_reviewer(),
    ))
    return docs


def pre_validate_declaration(
    declaration: Dict[str, Any],
    *,
    reviewer_id: str = DOC_REVIEWER_ID,
) -> Dict[str, Any]:
    """DOCS_PENDING (or AMENDING) → PRE_VALIDATED (PRD §3.5).
    reviewer_id is the opaque DocReviewer X-User-ID — keep it DISTINCT
    from the filing_officer_id used at file time (PRD §2.9 SoD)."""
    return _data(api_client.pre_validate_declaration(
        declaration["id"],
        action_with_version_payload(version=declaration["version"]),
        make_doc_reviewer_headers(reviewer_id),
    ))


def file_declaration(
    declaration: Dict[str, Any],
    *,
    filer_id: str = FILING_OFFICER_ID,
) -> Dict[str, Any]:
    """PRE_VALIDATED → FILED (PRD §3.6). filer_id is the opaque
    FilingOfficer X-User-ID — keep it DISTINCT from the DocReviewer
    id used at pre-validate (PRD §2.9 SoD-1) and from the
    SettlementOfficer id used at advance (PRD §2.9 SoD-2)."""
    return _data(api_client.file_declaration(
        declaration["id"],
        action_with_version_payload(version=declaration["version"]),
        make_filing_officer_headers(filer_id),
    ))


def get_filing_for_declaration(declaration_id: str) -> Optional[Dict[str, Any]]:
    """Look up the Filing row created by file_declaration().

    The PRD doesn't expose a /filings list, but the Filing id is
    needed for emit-event and inspection-case wiring. The Declaration
    GET response carries the latest snapshot — implementations are
    expected to expose Filing identifiers transitively via the
    declaration. This helper walks declaration['id'] → reads the
    declaration → returns the filing dict if present.
    """
    dec = _data(api_client.get_declaration(declaration_id, _broker()))
    # PRD does not pin the shape of the nested filing reference. We
    # tolerate two common forms: a top-level 'filing' dict, or a
    # 'filing_id' string sibling. Callers that need the full Filing
    # row directly should pass the id along from the cascade.
    f = dec.get("filing") if isinstance(dec, dict) else None
    if isinstance(f, dict) and "id" in f:
        return f
    return None


def emit_manifest_match(filing_id: str, *, shipment_reference: str, hs_code: str) -> None:
    """Logistics MANIFEST_DROPPED with payload matching declaration (PRD §3.6)."""
    payload = emit_manifest_dropped_payload(
        filing_id=filing_id,
        shipment_reference=shipment_reference,
        hs_code=hs_code,
    )
    _data(api_client.emit_event(payload, _sysadmin()))


def emit_customs_response(filing_id: str,
                          response_type: str,
                          reason_code: Optional[str] = None) -> None:
    """SINGLE_WINDOW CUSTOMS_RESPONSE event (PRD §3.6)."""
    payload = emit_customs_response_payload(
        filing_id=filing_id,
        response_type=response_type,
        reason_code=reason_code,
    )
    _data(api_client.emit_event(payload, _sysadmin()))


# ---------------------------------------------------------------------------
# Tier 3 — composite walkers (PRD §3.3 — §3.6)
# ---------------------------------------------------------------------------
def setup_declaration_in_docs_pending(
    *,
    agreement: Optional[Dict[str, Any]] = None,
    client: Optional[Dict[str, Any]] = None,
    jurisdiction_code: str = "CN",
    hs_code: str = "85171200",
    country_of_origin: str = "JP",
    trade_agreement_code: Optional[str] = "NONE",
    declared_value_amount: float = 1000.00,
    declared_currency: str = "USD",
    fee_schedule: Optional[Dict[str, float]] = None,
    agreement_currency: str = "USD",
    default_settlement_currency: str = "CNY",
) -> Dict[str, Any]:
    """Active agreement + declaration in DOCS_PENDING.

    Returns {client, agreement, declaration}."""
    if agreement is None:
        client, agreement = setup_active_agreement(
            agreement_currency=agreement_currency,
            fee_schedule=fee_schedule,
            default_settlement_currency=default_settlement_currency,
        )
    declaration = create_declaration(
        agreement["id"],
        jurisdiction_code=jurisdiction_code,
        hs_code=hs_code,
        country_of_origin=country_of_origin,
        trade_agreement_code=trade_agreement_code,
        declared_value_amount=declared_value_amount,
        declared_currency=declared_currency,
    )
    declaration = request_documents(declaration)
    return {
        "client": client,
        "agreement": agreement,
        "declaration": declaration,
    }


def setup_declaration_in_pre_validated(
    *,
    reviewer_id: str = DOC_REVIEWER_ID,
    invoice_total: float = 1000.00,
    invoice_currency: str = "USD",
    extra_docs: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Declaration walked to PRE_VALIDATED. All four core docs attached
    with matching invoice/packing-list totals.

    extra_docs: list of {'doc_type', 'storage_uri', 'declared_total_value',
    'declared_total_currency'} entries appended before pre-validate (e.g.,
    IMPORT_LICENSE or DANGEROUS_GOODS_DECL).
    """
    ctx = setup_declaration_in_docs_pending(**kwargs)
    docs = attach_core_docs(
        ctx["declaration"]["id"],
        invoice_total=invoice_total,
        invoice_currency=invoice_currency,
    )
    if extra_docs:
        for d in extra_docs:
            docs[d["doc_type"]] = attach_document(
                ctx["declaration"]["id"], **{k: v for k, v in d.items() if k != "doc_type"},
                doc_type=d["doc_type"],
            )
    # Refresh declaration before pre-validate (the version may have moved).
    ctx["declaration"] = _data(api_client.get_declaration(
        ctx["declaration"]["id"], _dec_officer(),
    ))
    ctx["declaration"] = pre_validate_declaration(
        ctx["declaration"], reviewer_id=reviewer_id,
    )
    ctx["documents"] = docs
    ctx["reviewer_id"] = reviewer_id
    return ctx


def setup_declaration_in_filed(
    *,
    reviewer_id: str = DOC_REVIEWER_ID,
    filer_id: str = FILING_OFFICER_ID,
    match_manifest: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Declaration walked to FILED.

    If match_manifest=True, immediately emit a LOGISTICS MANIFEST_DROPPED
    matching the declaration so a subsequent RELEASE response is not
    blocked by V-FIL-MANIFEST. If the cascade returns the Filing in the
    response payload of the file action, the test can grab it from
    ctx['filing']; otherwise this helper inspects the declaration to
    discover the filing.
    """
    ctx = setup_declaration_in_pre_validated(reviewer_id=reviewer_id, **kwargs)
    filed = file_declaration(ctx["declaration"], filer_id=filer_id)
    ctx["declaration"] = filed
    # Try to discover the Filing row.
    filing = filed.get("filing") if isinstance(filed, dict) else None
    if not (isinstance(filing, dict) and "id" in filing):
        filing = get_filing_for_declaration(filed["id"])
    ctx["filing"] = filing
    ctx["filer_id"] = filer_id

    if match_manifest and isinstance(filing, dict) and "id" in filing:
        emit_manifest_match(
            filing["id"],
            shipment_reference=filed["shipment_reference"],
            hs_code=filed["hs_code"],
        )
    return ctx


def setup_declaration_released_via_emit(
    *,
    reviewer_id: str = DOC_REVIEWER_ID,
    filer_id: str = FILING_OFFICER_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Declaration walked to RELEASED via SINGLE_WINDOW CUSTOMS_RESPONSE=RELEASE.
    Settlement is auto-created in FINAL status (PRD §3.6, §3.8).

    Returns ctx augmented with: declaration (RELEASED), settlement (FINAL).
    """
    ctx = setup_declaration_in_filed(
        reviewer_id=reviewer_id, filer_id=filer_id,
        match_manifest=True, **kwargs,
    )
    filing = ctx.get("filing")
    if isinstance(filing, dict) and "id" in filing:
        emit_customs_response(filing["id"], response_type="RELEASE")
    # Refresh declaration; locate the cascaded Settlement.
    ctx["declaration"] = _data(api_client.get_declaration(
        ctx["declaration"]["id"], _broker(),
    ))
    settlement = locate_settlement_for_declaration(ctx["declaration"]["id"])
    ctx["settlement"] = settlement
    return ctx


def locate_settlement_for_declaration(declaration_id: str) -> Optional[Dict[str, Any]]:
    """Find the Settlement row associated with a declaration via list filter."""
    resp = api_client.list_settlements(
        _broker(), params={"declaration_id": declaration_id, "limit": 100},
    )
    body = _data(resp)
    if isinstance(body, list):
        rows = body
    elif isinstance(body, dict):
        rows = body.get("items") or body.get("data") or []
        if not rows and "settlements" in body:
            rows = body["settlements"]
        # Some implementations wrap pagination differently; final fallback:
        if not isinstance(rows, list):
            rows = []
    else:
        rows = []
    if not rows:
        return None
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 4 — query / inspection / amendment / withdrawal walkers
# ---------------------------------------------------------------------------
def setup_declaration_in_queried(*, match_manifest: bool = True,
                                 **kwargs: Any) -> Dict[str, Any]:
    """Declaration walked to QUERIED via CUSTOMS_RESPONSE=QUERY.

    Default match_manifest=True so callers exercising the
    RELEASE-event-vs-respond-query race (PRD §2.11) start with
    manifest_match_status=MATCHED before the QUERY response moves the
    filing's response_type to QUERY. Pass match_manifest=False to keep
    the manifest UNMATCHED if your scenario needs that.
    """
    ctx = setup_declaration_in_filed(match_manifest=match_manifest, **kwargs)
    filing = ctx.get("filing")
    if isinstance(filing, dict) and "id" in filing:
        emit_customs_response(filing["id"], response_type="QUERY")
    ctx["declaration"] = _data(api_client.get_declaration(
        ctx["declaration"]["id"], _broker(),
    ))
    # Re-fetch filing so query_due_at is visible.
    ctx["filing"] = get_filing_for_declaration(ctx["declaration"]["id"]) or ctx.get("filing")
    return ctx


def setup_declaration_in_rejected_via_emit(
    *,
    reason_code: str = "HS_MISMATCH",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Declaration walked to REJECTED via CUSTOMS_RESPONSE=REJECT.
    A RejectionRecord is also archived (PRD §3.6)."""
    ctx = setup_declaration_in_filed(match_manifest=False, **kwargs)
    filing = ctx.get("filing")
    if isinstance(filing, dict) and "id" in filing:
        emit_customs_response(
            filing["id"], response_type="REJECT", reason_code=reason_code,
        )
    ctx["declaration"] = _data(api_client.get_declaration(
        ctx["declaration"]["id"], _broker(),
    ))
    return ctx


def setup_declaration_in_amending(*, reason_code: str = "HS_MISMATCH",
                                  **kwargs: Any) -> Dict[str, Any]:
    """Declaration walked REJECTED → AMENDING (PRD §3.11)."""
    ctx = setup_declaration_in_rejected_via_emit(reason_code=reason_code, **kwargs)
    declaration = ctx["declaration"]
    amended = _data(api_client.amend_declaration(
        declaration["id"],
        action_with_version_payload(version=declaration["version"]),
        _dec_officer(),
    ))
    ctx["declaration"] = amended
    return ctx


def setup_inspection_case(
    *,
    sample_required: bool = False,
    scheduled_at: Optional[datetime] = None,
    warehouse_code: str = "BOND-001",
    reviewer_id: str = DOC_REVIEWER_ID,
    filer_id: str = FILING_OFFICER_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Declaration walked to INSPECTING + InspectionCase created (PRD §3.7)."""
    ctx = setup_declaration_in_filed(
        reviewer_id=reviewer_id, filer_id=filer_id,
        match_manifest=False, **kwargs,
    )
    filing = ctx.get("filing")
    if isinstance(filing, dict) and "id" in filing:
        emit_customs_response(filing["id"], response_type="INSPECT")
    ctx["declaration"] = _data(api_client.get_declaration(
        ctx["declaration"]["id"], _broker(),
    ))
    sched = scheduled_at or (TEST_EPOCH + timedelta(hours=1))
    case = _data(api_client.create_inspection_case(
        create_inspection_case_payload(
            filing_id=filing["id"] if isinstance(filing, dict) else "",
            warehouse_code=warehouse_code,
            scheduled_at=iso_utc(sched),
            sample_required=sample_required,
        ),
        _insp_officer(),
    ))
    ctx["inspection_case"] = case
    ctx["scheduled_at"] = sched
    return ctx


def record_inspection_outcome(
    case: Dict[str, Any],
    outcome: str,
    *,
    penalty_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """Record inspection outcome PENDING → RELEASE | DETENTION | PENALTY."""
    payload = record_outcome_payload(
        outcome=outcome,
        penalty_amount=penalty_amount,
        version=case["version"],
    )
    return _data(api_client.record_inspection_outcome(
        case["id"], payload, _insp_officer(),
    ))


# ---------------------------------------------------------------------------
# Tier 5 — settlement walkers (PRD §3.10)
# ---------------------------------------------------------------------------
def advance_settlement(
    settlement: Dict[str, Any],
    *,
    officer_id: str = SETTLEMENT_OFFICER_ID,
) -> Dict[str, Any]:
    """FINAL → ADVANCED. PRD §2.9 SoD-2: officer_id MUST differ from the
    FilingOfficer who filed the underlying declaration. SETTLEMENT_OFFICER_ID
    defaults differ from FILING_OFFICER_ID so the SoD pair does not
    self-collide in fixtures."""
    return _data(api_client.advance_settlement(
        settlement["id"],
        advance_settlement_payload(version=settlement["version"]),
        make_settlement_officer_headers(officer_id),
    ))


def setup_settlement_in_advanced(
    *,
    officer_id: str = SETTLEMENT_OFFICER_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Declaration → RELEASED → Settlement ADVANCED (PRD §3.10)."""
    ctx = setup_declaration_released_via_emit(**kwargs)
    settlement = ctx.get("settlement")
    if settlement is None:
        raise RuntimeError("Settlement was not created by RELEASE cascade")
    ctx["settlement"] = advance_settlement(settlement, officer_id=officer_id)
    return ctx


def emit_bank_debit(settlement_id: str, amount: float) -> None:
    """BANK BANK_DEBIT_CONFIRMED event drives ADVANCED → REIMBURSED (PRD §3.10)."""
    payload = emit_bank_debit_payload(settlement_id=settlement_id, amount=amount)
    _data(api_client.emit_event(payload, _sysadmin()))


# ---------------------------------------------------------------------------
# Tier 6 — withdrawal (PRD §3.11)
# ---------------------------------------------------------------------------
def withdraw_declaration(declaration: Dict[str, Any]) -> Dict[str, Any]:
    return _data(api_client.withdraw_declaration(
        declaration["id"],
        action_with_version_payload(version=declaration["version"]),
        _broker(),
    ))


# ---------------------------------------------------------------------------
# Tier 7 — difficulty-design composite scenarios
# ---------------------------------------------------------------------------
def setup_two_declarations_for_tariff_variants() -> Dict[str, Any]:
    """For difficulty rule_id=dual_variant_calc /
    tariff_general_vs_preferential_on_settlement.

    DEC-G (general tariff, trade_agreement_code=NONE) and
    DEC-P (preferential tariff, trade_agreement_code=RCEP, JP origin
    eligible under RCEP for CN jurisdiction).
    Both: jurisdiction=CN, hs_code starts 8517, declared_value=2000.00 USD.
    Both driven to RELEASED.
    """
    client, agreement = setup_active_agreement(
        default_settlement_currency="CNY",
        agreement_currency="USD",
        scope_of_service=["DECLARATION", "INSPECTION", "TARIFF_ADVANCE",
                          "AMENDMENT", "RETURN_SHIP"],
        fee_schedule={
            "DECLARATION": 100,
            "INSPECTION": 50,
            "TARIFF_ADVANCE": 80,
            "AMENDMENT": 30,
            "RETURN_SHIP": 200,
        },
        late_interest_daily_rate_bps=100,
    )

    ctx_g = setup_declaration_released_via_emit(
        agreement=agreement, client=client,
        jurisdiction_code="CN", hs_code="85171200",
        country_of_origin="JP", trade_agreement_code="NONE",
        declared_value_amount=1000.00, declared_currency="USD",
        reviewer_id=DOC_REVIEWER_ID, filer_id=FILING_OFFICER_ID,
    )
    ctx_p = setup_declaration_released_via_emit(
        agreement=agreement, client=client,
        jurisdiction_code="CN", hs_code="85171200",
        country_of_origin="JP", trade_agreement_code="RCEP",
        declared_value_amount=1000.00, declared_currency="USD",
        reviewer_id=DOC_REVIEWER_ID + "-p", filer_id=FILING_OFFICER_ID + "-p",
    )
    return {
        "client": client,
        "agreement": agreement,
        "general": ctx_g,
        "preferential": ctx_p,
    }


def setup_settlement_for_late_interest_freeze() -> Dict[str, Any]:
    """For difficulty rule_id=dual_variant_calc /
    late_interest_ongoing_vs_finalized_on_settlement_ledger.

    Drive a declaration to RELEASED, advance the settlement at TEST_EPOCH
    so reimbursement_due_at = TEST_EPOCH + 7d. Returns the ADVANCED
    settlement + client + agreement.
    """
    reset_clock_to_epoch()
    ctx = setup_settlement_in_advanced(
        default_settlement_currency="CNY",
        agreement_currency="USD",
        jurisdiction_code="CN", hs_code="85171200",
        country_of_origin="JP", trade_agreement_code="NONE",
        declared_value_amount=1000.00, declared_currency="USD",
        fee_schedule={
            "DECLARATION": 100,
            "INSPECTION": 50,
            "TARIFF_ADVANCE": 80,
            "AMENDMENT": 30,
            "RETURN_SHIP": 200,
        },
    )
    return ctx


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------
__all__ = [
    # constants
    "TEST_EPOCH",
    "DEFAULT_VALID_FROM",
    "DEFAULT_VALID_UNTIL",
    # clock
    "advance_clock_to",
    "reset_clock_to_epoch",
    # tier 1
    "create_client",
    "create_agreement",
    "request_signature",
    "sign_agreement",
    "activate_agreement",
    # tier 2
    "setup_active_agreement",
    "create_declaration",
    "request_documents",
    "attach_document",
    "attach_core_docs",
    "pre_validate_declaration",
    "file_declaration",
    "get_filing_for_declaration",
    "emit_manifest_match",
    "emit_customs_response",
    # tier 3
    "setup_declaration_in_docs_pending",
    "setup_declaration_in_pre_validated",
    "setup_declaration_in_filed",
    "setup_declaration_released_via_emit",
    "locate_settlement_for_declaration",
    # tier 4
    "setup_declaration_in_queried",
    "setup_declaration_in_rejected_via_emit",
    "setup_declaration_in_amending",
    "setup_inspection_case",
    "record_inspection_outcome",
    # tier 5
    "advance_settlement",
    "setup_settlement_in_advanced",
    "emit_bank_debit",
    # tier 6
    "withdraw_declaration",
    # tier 7 — difficulty-design composites
    "setup_two_declarations_for_tariff_variants",
    "setup_settlement_for_late_interest_freeze",
]
