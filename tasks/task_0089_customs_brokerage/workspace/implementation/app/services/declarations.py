"""Declaration service: CRUD + state transitions."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from ..audit import emit_audit
from ..auth import current_actor
from ..calculations import (
    compute_declared_value_review,
    to_float2,
)
from ..clock import now_dt, now_iso_ms, parse_iso
from ..constants import (
    CORE_DOC_TYPES,
    JURISDICTIONS,
    TRADE_AGREEMENTS,
    declared_to_settlement_rate,
)
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .validation import (
    ensure_currency,
    ensure_country,
    ensure_enum,
    ensure_hs_code,
    ensure_non_negative_number,
    ensure_string,
    occ_check,
)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def _unique_shipment_reference(
    agreement_id: str, shipment_reference: str, exclude_id: Optional[str] = None
) -> None:
    """Unique per agreement_id among non-WITHDRAWN."""
    store = get_store()
    for d in store.declarations.values():
        if d.get("agreement_id") != agreement_id:
            continue
        if d.get("status") == "WITHDRAWN":
            continue
        if exclude_id and d.get("id") == exclude_id:
            continue
        if d.get("shipment_reference") == shipment_reference:
            raise ApiError(
                "ERR_INVALID_INPUT",
                f"shipment_reference {shipment_reference!r} already used within this agreement.",
            )


def create_declaration(body: dict[str, Any]) -> dict[str, Any]:
    agreement_id = ensure_string(body.get("agreement_id"), "agreement_id", 1, 200)
    store = get_store()
    agreement = store.agreements.get(agreement_id)
    if not agreement:
        raise ApiError("ERR_NOT_FOUND", f"Agreement {agreement_id!r} not found.")

    jurisdiction_code = ensure_enum(
        body.get("jurisdiction_code"), "jurisdiction_code", JURISDICTIONS
    )
    shipment_reference = ensure_string(
        body.get("shipment_reference"), "shipment_reference", 1, 60
    )
    hs_code = ensure_hs_code(body.get("hs_code"))
    country_of_origin = ensure_country(body.get("country_of_origin"), "country_of_origin")
    trade_agreement_code = body.get("trade_agreement_code")
    if trade_agreement_code is None:
        trade_agreement_code = "NONE"
    else:
        trade_agreement_code = ensure_enum(
            trade_agreement_code, "trade_agreement_code", TRADE_AGREEMENTS
        )
    if "declared_value_amount" not in body:
        raise ApiError("ERR_INVALID_INPUT", "declared_value_amount is required.")
    declared_value_amount = ensure_non_negative_number(
        body["declared_value_amount"], "declared_value_amount"
    )
    declared_currency = ensure_currency(body.get("declared_currency"), "declared_currency")

    # State checks (business_temporal / business_referential)
    if agreement.get("status") != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE.")
    vf = parse_iso(agreement["valid_from"])
    vu = parse_iso(agreement["valid_until"])
    now = now_dt()
    if not (vf <= now < vu):
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "Outside agreement validity window.")
    if "DECLARATION" not in (agreement.get("scope_of_service") or []):
        raise ApiError(
            "ERR_SERVICE_OUT_OF_SCOPE",
            "DECLARATION service not in agreement.scope_of_service.",
        )

    _unique_shipment_reference(agreement_id, shipment_reference)

    record = common_fields_create()
    record.update(
        {
            "agreement_id": agreement_id,
            "jurisdiction_code": jurisdiction_code,
            "shipment_reference": shipment_reference,
            "hs_code": hs_code,
            "country_of_origin": country_of_origin,
            "trade_agreement_code": trade_agreement_code,
            "declared_value_amount": float(declared_value_amount),
            "declared_currency": declared_currency,
            "fx_rate_to_settlement": None,
            "declared_value_review_status": "PENDING",
            "form_payload": None,
            "status": "DRAFT",
            "rejection_reason_code": None,
            "amendment_count": 0,
            "pinned_agreement_version": None,
        }
    )
    # Run declared-value review (uses fx 1.0 if not pinned)
    record["declared_value_review_status"] = compute_declared_value_review(record)

    store.declarations[record["id"]] = record
    return record


def get_declaration(declaration_id: str) -> dict[str, Any]:
    d = get_store().declarations.get(declaration_id)
    if not d:
        raise ApiError("ERR_NOT_FOUND", f"Declaration {declaration_id!r} not found.")
    return d


def list_declarations(
    status: Optional[str],
    agreement_id: Optional[str],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    items = list(get_store().declarations.values())
    if status is not None:
        items = [d for d in items if d.get("status") == status]
    if agreement_id is not None:
        items = [d for d in items if d.get("agreement_id") == agreement_id]
    # ClientUser scoping
    user_id, role = current_actor()
    if role == "ClientUser":
        # restrict to declarations whose parent agreement belongs to this client
        store = get_store()
        items = [
            d
            for d in items
            if store.agreements.get(d.get("agreement_id"), {}).get("client_id") == user_id
        ]
    items.sort(key=lambda d: d.get("created_at") or "")
    return items


def update_declaration(declaration_id: str, body: dict[str, Any]) -> dict[str, Any]:
    declaration = get_declaration(declaration_id)
    occ_check(declaration, body.get("version"))
    if declaration.get("status") not in {"DRAFT", "DOCS_PENDING", "AMENDING"}:
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Declaration in state {declaration['status']!r}; cannot patch.",
        )

    changed_value = False
    if "declared_value_amount" in body:
        v = ensure_non_negative_number(body["declared_value_amount"], "declared_value_amount")
        declaration["declared_value_amount"] = float(v)
        changed_value = True
    if "hs_code" in body:
        declaration["hs_code"] = ensure_hs_code(body["hs_code"])
        changed_value = True  # hs_code feeds review heuristic
    if "country_of_origin" in body:
        declaration["country_of_origin"] = ensure_country(
            body["country_of_origin"], "country_of_origin"
        )
    if "trade_agreement_code" in body:
        declaration["trade_agreement_code"] = ensure_enum(
            body["trade_agreement_code"], "trade_agreement_code", TRADE_AGREEMENTS
        )

    if changed_value:
        declaration["declared_value_review_status"] = compute_declared_value_review(declaration)

    bump_version(declaration)
    return declaration


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------
def request_documents(declaration_id: str, body: dict[str, Any]) -> dict[str, Any]:
    declaration = get_declaration(declaration_id)
    occ_check(declaration, body.get("version"))
    if declaration.get("status") != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Declaration in {declaration['status']!r}; expected DRAFT.",
        )
    # Preconditions: required fields populated
    for f in ("hs_code", "country_of_origin", "declared_value_amount", "declared_currency"):
        if declaration.get(f) in (None, ""):
            raise ApiError("ERR_INVALID_INPUT", f"{f} must be populated before request-documents.")

    store = get_store()
    agreement = store.agreements.get(declaration["agreement_id"])
    if not agreement or agreement.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Parent agreement is not ACTIVE.")
    if "DECLARATION" not in (agreement.get("scope_of_service") or []):
        raise ApiError(
            "ERR_SERVICE_OUT_OF_SCOPE",
            "DECLARATION service not in agreement.scope_of_service.",
        )

    prev_status = declaration["status"]
    declaration["status"] = "DOCS_PENDING"
    bump_version(declaration)

    # Side effect: create stub ShipmentDocuments for missing core docs
    present_types = {
        doc["doc_type"]
        for doc in store.documents.values()
        if doc.get("declaration_id") == declaration_id
    }
    user_id, role = current_actor()
    for core_type in CORE_DOC_TYPES:
        if core_type not in present_types:
            stub = common_fields_create()
            stub.update(
                {
                    "declaration_id": declaration_id,
                    "doc_type": core_type,
                    "storage_uri": "",
                    "declared_total_value": None,
                    "declared_total_currency": None,
                    "authenticity_score": None,
                    "authenticity_status": "UNSCREENED",
                    "follow_up_requested_at": now_iso_ms(),
                }
            )
            store.documents[stub["id"]] = stub

    emit_audit(
        "DECLARATION",
        declaration_id,
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": prev_status, "to": "DOCS_PENDING"},
    )
    return declaration


def _validate_pre_validate_preconditions(declaration: dict[str, Any]) -> None:
    """Run priority-ordered checks for pre-validation per scaffold §1.4.

    Order: authenticity_flagged (72) -> license (73) -> dangerous-goods (74)
           -> doc_complete (90) -> doc_consistency (91) -> declared_value (92, via review)
    """
    store = get_store()
    declaration_id = declaration["id"]
    docs = [
        d
        for d in store.documents.values()
        if d.get("declaration_id") == declaration_id
    ]

    # Priority 72: ERR_DOC_AUTHENTICITY_FLAGGED
    if any(d.get("authenticity_status") == "FLAGGED" for d in docs):
        raise ApiError(
            "ERR_DOC_AUTHENTICITY_FLAGGED",
            "One or more documents have authenticity_status=FLAGGED.",
        )

    hs_code = declaration.get("hs_code") or ""
    juris = declaration.get("jurisdiction_code")

    # Priority 73: ERR_DOC_MISSING_LICENSE
    needs_license = hs_code.startswith("28") or hs_code.startswith("29") or (
        juris == "CN" and hs_code.startswith("29")
    )
    if needs_license:
        if not any(d.get("doc_type") == "IMPORT_LICENSE" for d in docs):
            raise ApiError(
                "ERR_DOC_MISSING_LICENSE",
                "Restricted-HS declaration requires IMPORT_LICENSE doc.",
            )

    # Priority 74: ERR_DOC_MISSING_DG
    needs_dg = (
        hs_code.startswith("2208")
        or hs_code.startswith("2402")
        or hs_code.startswith("2710")
    )
    if needs_dg:
        if not any(d.get("doc_type") == "DANGEROUS_GOODS_DECL" for d in docs):
            raise ApiError(
                "ERR_DOC_MISSING_DG",
                "Dangerous-goods HS prefix requires DANGEROUS_GOODS_DECL doc.",
            )

    # Priority 90: ERR_DOC_INCOMPLETE — all four core docs must exist
    # A "stub" document with empty storage_uri (created via request-documents) does NOT count
    # as the operator having attached the doc — it represents a follow-up request.
    present_core = {
        d.get("doc_type")
        for d in docs
        if d.get("doc_type") in CORE_DOC_TYPES and d.get("storage_uri")
    }
    if present_core != CORE_DOC_TYPES:
        raise ApiError("ERR_DOC_INCOMPLETE", "Missing one or more core documents.")

    # Priority 91: ERR_DOC_INCONSISTENT — invoice/packing_list consistency
    invoices = [d for d in docs if d.get("doc_type") == "COMMERCIAL_INVOICE"]
    packings = [d for d in docs if d.get("doc_type") == "PACKING_LIST"]
    if invoices and packings:
        # Take the one with declared_total_value populated for each type
        inv = next(
            (d for d in invoices if d.get("declared_total_value") is not None),
            None,
        )
        pak = next(
            (d for d in packings if d.get("declared_total_value") is not None),
            None,
        )
        if (
            inv is not None
            and pak is not None
            and inv.get("declared_total_currency") == pak.get("declared_total_currency")
        ):
            inv_v = Decimal(str(inv["declared_total_value"]))
            pak_v = Decimal(str(pak["declared_total_value"]))
            larger = max(inv_v, pak_v)
            if larger > 0:
                diff = abs(inv_v - pak_v)
                if diff > larger * Decimal("0.005"):
                    raise ApiError(
                        "ERR_DOC_INCONSISTENT",
                        "Invoice vs packing-list totals differ by more than 0.5%.",
                    )

    # Declared-value review must NOT be FLAGGED at pre-validate either
    if declaration.get("declared_value_review_status") == "FLAGGED":
        raise ApiError(
            "ERR_DECLARED_VALUE_FLAGGED",
            "declared_value_review_status is FLAGGED.",
        )


def _generate_form_payload(declaration: dict[str, Any]) -> dict[str, Any]:
    """Build a jurisdiction-specific form payload."""
    juris = declaration["jurisdiction_code"]
    return {
        "template": f"FORM_{juris}",
        "jurisdiction_code": juris,
        "hs_code": declaration.get("hs_code"),
        "country_of_origin": declaration.get("country_of_origin"),
        "trade_agreement_code": declaration.get("trade_agreement_code"),
        "declared_value_amount": float(declaration.get("declared_value_amount") or 0),
        "declared_currency": declaration.get("declared_currency"),
        "shipment_reference": declaration.get("shipment_reference"),
    }


def pre_validate(declaration_id: str, body: dict[str, Any]) -> dict[str, Any]:
    declaration = get_declaration(declaration_id)
    occ_check(declaration, body.get("version"))

    if declaration.get("status") not in {"DOCS_PENDING", "AMENDING"}:
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Declaration in {declaration['status']!r}; expected DOCS_PENDING or AMENDING.",
        )

    # business_safety checks (priority 72-74) first, then completeness/consistency,
    # then declared-value flag check
    _validate_pre_validate_preconditions(declaration)

    # Side effects
    store = get_store()
    agreement = store.agreements.get(declaration["agreement_id"])
    if not agreement:
        raise ApiError("ERR_NOT_FOUND", "Parent agreement not found.")
    client = store.clients.get(agreement.get("client_id"))
    if not client:
        raise ApiError("ERR_NOT_FOUND", "Parent client not found.")

    settlement_currency = client["default_settlement_currency"]
    fx = declared_to_settlement_rate(declaration["declared_currency"], settlement_currency)
    declaration["fx_rate_to_settlement"] = float(fx)

    # PRD §3.3: declared-value review runs only on CREATE and on PATCH of
    # declared_value_amount. Pre-validate does NOT re-run it; it only checks
    # the existing declared_value_review_status (handled higher up).
    declaration["form_payload"] = _generate_form_payload(declaration)
    declaration["pinned_agreement_version"] = int(agreement.get("version", 0))

    prev_status = declaration["status"]
    declaration["status"] = "PRE_VALIDATED"
    bump_version(declaration)

    user_id, role = current_actor()
    # Record actor for SoD
    store.preval_actor[declaration_id] = user_id

    emit_audit(
        "DECLARATION",
        declaration_id,
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": prev_status, "to": "PRE_VALIDATED"},
    )
    emit_audit(
        "DECLARATION",
        declaration_id,
        "FIELD_CHANGE",
        role,
        user_id,
        {
            "field": "form_payload",
            "old": None,
            "new": declaration["form_payload"],
        },
    )
    emit_audit(
        "DECLARATION",
        declaration_id,
        "FIELD_CHANGE",
        role,
        user_id,
        {
            "field": "fx_rate_to_settlement",
            "old": None,
            "new": declaration["fx_rate_to_settlement"],
        },
    )
    return declaration


def file_declaration(declaration_id: str, body: dict[str, Any]) -> dict[str, Any]:
    declaration = get_declaration(declaration_id)
    occ_check(declaration, body.get("version"))

    store = get_store()

    # PRD §2.11 names ERR_FILING_ALREADY_EXISTS as the file-race loser
    # outcome; surface it ahead of the generic state precondition so a
    # second filing on the already-FILED declaration produces the
    # PRD-specified error rather than ERR_INVALID_STATE.
    existing = _active_filing(declaration_id)
    if existing is not None:
        raise ApiError(
            "ERR_FILING_ALREADY_EXISTS",
            "An active Filing already exists for this declaration.",
        )

    if declaration.get("status") != "PRE_VALIDATED":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Declaration in {declaration['status']!r}; expected PRE_VALIDATED.",
        )

    user_id, role = current_actor()

    # Priority 70: SoD — FilingOfficer != DocReviewer
    preval_actor_id = store.preval_actor.get(declaration_id)
    if preval_actor_id and preval_actor_id == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "FilingOfficer must differ from the DocReviewer who pre-validated.",
        )

    # Priority 92: ERR_DECLARED_VALUE_FLAGGED
    if declaration.get("declared_value_review_status") == "FLAGGED":
        raise ApiError(
            "ERR_DECLARED_VALUE_FLAGGED",
            "declared_value_review_status is FLAGGED.",
        )

    # Priority 130: ERR_AGREEMENT_VERSION_DRIFT
    agreement = store.agreements.get(declaration["agreement_id"])
    if not agreement:
        raise ApiError("ERR_NOT_FOUND", "Parent agreement not found.")
    if declaration.get("pinned_agreement_version") != agreement.get("version"):
        raise ApiError(
            "ERR_AGREEMENT_VERSION_DRIFT",
            "Agreement version has drifted since pre-validation; re-pre-validate.",
        )

    prev_status = declaration["status"]
    declaration["status"] = "FILED"
    bump_version(declaration)

    # Create Filing
    import uuid as _uuid

    filing = common_fields_create()
    filing.update(
        {
            "declaration_id": declaration_id,
            "single_window_ref": str(_uuid.uuid4()),
            "submitted_at": now_iso_ms(),
            "response_type": "AWAITING",
            "response_received_at": None,
            "query_due_at": None,
            "query_response_at": None,
            "manifest_match_status": "UNMATCHED",
            "is_amendment": int(declaration.get("amendment_count", 0) or 0) > 0,
        }
    )
    store.filings[filing["id"]] = filing
    store.file_actor[declaration_id] = user_id

    emit_audit(
        "DECLARATION",
        declaration_id,
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": prev_status, "to": "FILED"},
    )
    if filing["is_amendment"]:
        emit_audit(
            "DECLARATION",
            declaration_id,
            "AMENDMENT_FILED",
            role,
            user_id,
            {"amendment_count": declaration.get("amendment_count", 0)},
        )
    return declaration


def _active_filing(declaration_id: str) -> Optional[dict[str, Any]]:
    """Return the most recent non-terminal Filing for this declaration, if any."""
    store = get_store()
    candidates = [
        f
        for f in store.filings.values()
        if f.get("declaration_id") == declaration_id
        and f.get("response_type") not in {"RELEASE", "REJECT"}
    ]
    if not candidates:
        return None
    # Latest by submitted_at
    candidates.sort(key=lambda f: f.get("submitted_at") or "")
    return candidates[-1]


def respond_query(declaration_id: str, body: dict[str, Any]) -> dict[str, Any]:
    declaration = get_declaration(declaration_id)
    occ_check(declaration, body.get("version"))
    if declaration.get("status") != "QUERIED":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Declaration in {declaration['status']!r}; expected QUERIED.",
        )
    response_note = body.get("response_note")
    if not isinstance(response_note, str) or not response_note:
        raise ApiError("ERR_INVALID_INPUT", "response_note is required.")

    filing = _active_filing(declaration_id)
    if filing is None or filing.get("response_type") != "QUERY":
        raise ApiError("ERR_INVALID_STATE", "No active QUERY filing.")

    due = parse_iso(filing["query_due_at"]) if filing.get("query_due_at") else None
    if due is None or now_dt() >= due:
        raise ApiError("ERR_QUERY_DEADLINE_PASSED", "Query deadline has passed.")

    prev_status = declaration["status"]
    declaration["status"] = "FILED"
    bump_version(declaration)

    filing["query_response_at"] = now_iso_ms()
    filing["response_type"] = "AWAITING"
    bump_version(filing)

    user_id, role = current_actor()
    emit_audit(
        "DECLARATION",
        declaration_id,
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": prev_status, "to": "FILED"},
    )
    return declaration


def amend_declaration(declaration_id: str, body: dict[str, Any]) -> dict[str, Any]:
    declaration = get_declaration(declaration_id)
    occ_check(declaration, body.get("version"))
    if declaration.get("status") != "REJECTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Declaration in {declaration['status']!r}; expected REJECTED.",
        )
    if declaration.get("rejection_reason_code") == "INSPECTION_FAILED":
        raise ApiError(
            "ERR_INSPECTION_REJECTION_NOT_AMENDABLE",
            "INSPECTION_FAILED rejections must be withdrawn, not amended.",
        )
    if int(declaration.get("amendment_count", 0) or 0) >= 3:
        raise ApiError("ERR_AMENDMENT_CAP_REACHED", "Amendment cap of 3 reached.")
    # Must have RejectionRecord
    store = get_store()
    rej_exists = any(
        r.get("declaration_id") == declaration_id for r in store.rejection_records.values()
    )
    if not rej_exists:
        raise ApiError("ERR_INVALID_STATE", "No RejectionRecord for this declaration.")

    prev_status = declaration["status"]
    declaration["status"] = "AMENDING"
    declaration["amendment_count"] = int(declaration.get("amendment_count", 0) or 0) + 1
    declaration["rejection_reason_code"] = None
    declaration["pinned_agreement_version"] = None
    bump_version(declaration)

    user_id, role = current_actor()
    emit_audit(
        "DECLARATION",
        declaration_id,
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": prev_status, "to": "AMENDING"},
    )
    emit_audit(
        "DECLARATION",
        declaration_id,
        "FIELD_CHANGE",
        role,
        user_id,
        {
            "field": "amendment_count",
            "old": declaration["amendment_count"] - 1,
            "new": declaration["amendment_count"],
        },
    )
    return declaration


def withdraw_declaration(declaration_id: str, body: dict[str, Any]) -> dict[str, Any]:
    declaration = get_declaration(declaration_id)
    occ_check(declaration, body.get("version"))

    if declaration.get("status") not in {"DRAFT", "REJECTED"}:
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Declaration in {declaration['status']!r}; cannot withdraw.",
        )

    store = get_store()
    # Priority 41: ERR_SETTLEMENT_HAS_ADVANCE
    for s in store.settlements.values():
        if s.get("declaration_id") != declaration_id:
            continue
        if s.get("status") in {"ADVANCED", "REIMBURSED"}:
            raise ApiError(
                "ERR_SETTLEMENT_HAS_ADVANCE",
                "Cannot withdraw: settlement has been advanced or reimbursed.",
            )

    if declaration["status"] == "DRAFT":
        # No Filing should exist
        if any(f.get("declaration_id") == declaration_id for f in store.filings.values()):
            raise ApiError("ERR_INVALID_STATE", "Cannot withdraw DRAFT with existing Filing.")
    if declaration["status"] == "REJECTED":
        if not any(
            r.get("declaration_id") == declaration_id for r in store.rejection_records.values()
        ):
            raise ApiError("ERR_INVALID_STATE", "Withdraw requires existing RejectionRecord.")

    prev_status = declaration["status"]
    declaration["status"] = "WITHDRAWN"
    bump_version(declaration)

    user_id, role = current_actor()
    # Cascade: void PROVISIONAL/FINAL settlement (not ADVANCED/REIMBURSED)
    for s in store.settlements.values():
        if s.get("declaration_id") != declaration_id:
            continue
        if s.get("status") in {"PROVISIONAL", "FINAL"}:
            prev = s["status"]
            s["status"] = "VOIDED"
            bump_version(s)
            emit_audit(
                "SETTLEMENT",
                s["id"],
                "STATE_TRANSITION",
                role,
                user_id,
                {"from": prev, "to": "VOIDED"},
            )

    emit_audit(
        "DECLARATION",
        declaration_id,
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": prev_status, "to": "WITHDRAWN"},
    )

    # Emit logistics RETURN_SHIPMENT_DISPATCHED event
    from ..store import common_fields_append_only

    ev = common_fields_append_only()
    ev.update(
        {
            "source_system": "LOGISTICS",
            "event_type": "RETURN_SHIPMENT_DISPATCHED",
            "target_entity_type": "DECLARATION",
            "target_entity_id": declaration_id,
            "payload": {"shipment_reference": declaration.get("shipment_reference")},
            "processed_at": now_iso_ms(),
        }
    )
    store.external_events[ev["id"]] = ev

    return declaration
