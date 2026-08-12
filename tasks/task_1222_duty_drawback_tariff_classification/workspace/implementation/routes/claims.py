"""Drawback claim endpoints: lifecycle, lines, filing, review, payment (PRD §3.4-§3.5)."""
from flask import Blueprint, request

from calc import (
    RETENTION_YEARS,
    TERMINAL_CLAIM_STATUSES,
    active_lines_of_claim,
    claim_period_overlaps,
    compute_line_amount,
    entry_hts_code,
    line_raw_refund,
    mint_entity,
    recompute_claim_estimate,
    recompute_client_aggregates,
    recompute_entry,
    recompute_entry_quantities,
    recompute_export,
    recompute_filing_deadline,
    tiered_fee_cents,
    touch,
    void_all_active_lines,
    void_line_with_cascade,
)
from db import STORE, logical_now
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_APPROVED_EXCEEDS_CLAIMED,
    ERR_CLAIM_PERIOD_OVERLAP,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_CROSS_CLIENT_REFERENCE,
    ERR_DEFICIENCY_LIMIT_REACHED,
    ERR_EXPORT_VALUE_POOL_EXCEEDED,
    ERR_FILING_DEADLINE_PASSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_WINDOW,
    ERR_MATCH_INCOMPATIBLE,
    ERR_MATCH_QUANTITY_EXCEEDED,
    ERR_NOT_FOUND,
    ERR_PAID_AMOUNT_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import (
    authenticate,
    get_body,
    opt_dt,
    opt_int,
    req_dt,
    req_enum,
    req_int,
    req_str,
    require_client_scope,
    require_role,
)
from response import paginate, success_object
from serializers import serialize, sorted_by_creation
from util import add_years, fmt_dt

bp = Blueprint("claims", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}
CLAIM_TYPES = {"DIRECT_IDENTIFICATION", "SUBSTITUTION"}
MATCH_METHOD_BY_TYPE = {"DIRECT_IDENTIFICATION": "DIRECT", "SUBSTITUTION": "SUBSTITUTION"}
RETENTION_DOC_TYPES = ("ENTRY_DOCS", "EXPORT_PROOF", "MATCHING_WORKSHEET")


def get_claim_or_404(claim_id):
    claim = STORE["claims"].get(claim_id)
    if claim is None:
        raise_err(ERR_NOT_FOUND, f"Claim {claim_id} not found")
    return claim


def _claim_transition_guard(claim):
    if claim["status"] in TERMINAL_CLAIM_STATUSES:
        raise_err(ERR_ALREADY_TERMINAL, f"Claim is {claim['status']} (terminal)")


# ---------------------------------------------------------------------------
# Claim CRUD
# ---------------------------------------------------------------------------

@bp.route("/customs/claims", methods=["POST"])
def create_claim():
    user_id, role = authenticate()
    require_role(role, {"Analyst"})
    body = get_body()
    client_id = req_str(body, "client_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")

    client = STORE["clients"].get(client_id)
    if client is None:
        raise_err(ERR_NOT_FOUND, f"Client {client_id} not found")
    if client["engagement_status"] != "ACTIVE":
        raise_err(ERR_CLIENT_NOT_ACTIVE, "Client engagement is not ACTIVE")
    if period_end < period_start:
        raise_err(ERR_INVALID_WINDOW, "period_end must be on or after period_start")
    if claim_period_overlaps(client_id, claim_type, period_start, period_end):
        raise_err(
            ERR_CLAIM_PERIOD_OVERLAP,
            "Period overlaps another same-type, non-terminal claim of this client",
        )

    claim = mint_entity()
    claim.update({
        "client_id": client_id,
        "claim_type": claim_type,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "prepared_by_user_id": user_id,
        "filed_by_user_id": None,
        "filed_at": None,
        "deficiency_count": 0,
        "estimate_cents": 0,
        "claimed_duty_cents": None,
        "approved_duty_cents": None,
        "paid_duty_cents": None,
        "paid_at": None,
        "filing_deadline": None,
    })
    STORE["claims"][claim["id"]] = claim
    return success_object(serialize(claim), 201)


@bp.route("/customs/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    claim = get_claim_or_404(claim_id)
    require_client_scope(user_id, role, claim["client_id"])
    return success_object(serialize(claim))


@bp.route("/customs/claims", methods=["GET"])
def list_claims():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["claims"].values())
    if role == "ClientContact":
        items = [c for c in items if c["client_id"] == user_id]
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [c for c in items if c["client_id"] == client_id]
    claim_type = request.args.get("claim_type")
    if claim_type is not None:
        items = [c for c in items if c["claim_type"] == claim_type]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([serialize(c) for c in items])


@bp.route("/customs/claims/<claim_id>", methods=["PUT"])
def update_claim(claim_id):
    _, role = authenticate()
    require_role(role, {"Analyst"})
    claim = get_claim_or_404(claim_id)
    body = get_body()
    if "expected_claim_version" not in body or body["expected_claim_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_claim_version")
    expected = body["expected_claim_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_claim_version must be an integer")
    new_start = opt_dt(body, "period_start")
    new_end = opt_dt(body, "period_end")
    new_type = None
    if "claim_type" in body and body["claim_type"] is not None:
        new_type = req_enum(body, "claim_type", CLAIM_TYPES)

    if expected != claim["version"]:
        raise_err(ERR_STALE_VERSION, "expected_claim_version does not match current version")
    _claim_transition_guard(claim)
    if claim["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"Only DRAFT claims may be updated (got {claim['status']})")

    start = new_start if new_start is not None else claim["period_start"]
    end = new_end if new_end is not None else claim["period_end"]
    ctype = new_type if new_type is not None else claim["claim_type"]
    if end < start:
        raise_err(ERR_INVALID_WINDOW, "period_end must be on or after period_start")
    if claim_period_overlaps(claim["client_id"], ctype, start, end, exclude_id=claim["id"]):
        raise_err(
            ERR_CLAIM_PERIOD_OVERLAP,
            "Period overlaps another same-type, non-terminal claim of this client",
        )

    claim["period_start"] = start
    claim["period_end"] = end
    claim["claim_type"] = ctype
    touch(claim)
    return success_object(serialize(claim))


# ---------------------------------------------------------------------------
# Claim lines
# ---------------------------------------------------------------------------

@bp.route("/customs/claims/<claim_id>/lines", methods=["POST"])
def add_claim_line(claim_id):
    _, role = authenticate()
    require_role(role, {"Analyst"})
    claim = get_claim_or_404(claim_id)
    body = get_body()
    import_entry_id = req_str(body, "import_entry_id")
    export_shipment_id = req_str(body, "export_shipment_id")
    matched_quantity = req_int(body, "matched_quantity", minimum=1)

    entry = STORE["import_entries"].get(import_entry_id)
    if entry is None:
        raise_err(ERR_NOT_FOUND, f"Import entry {import_entry_id} not found")
    export = STORE["export_shipments"].get(export_shipment_id)
    if export is None:
        raise_err(ERR_NOT_FOUND, f"Export shipment {export_shipment_id} not found")

    _claim_transition_guard(claim)
    if claim["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"Lines may only be added to DRAFT claims (got {claim['status']})")

    if entry["client_id"] != claim["client_id"] or export["client_id"] != claim["client_id"]:
        raise_err(ERR_CROSS_CLIENT_REFERENCE, "Entry and export must belong to the claim's client")

    if claim["claim_type"] == "DIRECT_IDENTIFICATION":
        if export["hts_code"] != entry_hts_code(entry):
            raise_err(
                ERR_MATCH_INCOMPATIBLE,
                "DIRECT_IDENTIFICATION requires export.hts_code == entry.hts_code",
            )

    entry_remaining = entry["line_quantity"] - entry["matched_quantity"]
    export_remaining = export["quantity"] - export["matched_quantity"]
    if matched_quantity > min(entry_remaining, export_remaining):
        raise_err(
            ERR_MATCH_QUANTITY_EXCEEDED,
            "matched_quantity exceeds remaining units on entry or export",
        )

    raw = line_raw_refund(entry, export, matched_quantity, claim["claim_type"])
    if claim["claim_type"] == "SUBSTITUTION":
        if raw > export["value_pool_remaining_cents"]:
            raise_err(
                ERR_EXPORT_VALUE_POOL_EXCEEDED,
                "Substitution refund exceeds the export's remaining FOB value pool",
            )
    amount = compute_line_amount(entry, export, matched_quantity, claim["claim_type"])

    line = mint_entity()
    line.update({
        "claim_id": claim["id"],
        "import_entry_id": import_entry_id,
        "export_shipment_id": export_shipment_id,
        "matched_quantity": matched_quantity,
        "match_method": MATCH_METHOD_BY_TYPE[claim["claim_type"]],
        "drawback_amount_cents": amount,
        "status": "ACTIVE",
    })
    STORE["claim_lines"][line["id"]] = line

    recompute_entry(entry)
    recompute_entry_quantities(entry)
    touch(entry)
    recompute_export(export)
    touch(export)
    recompute_claim_estimate(claim)
    recompute_filing_deadline(claim)
    touch(claim)
    return success_object(serialize(line), 201)


@bp.route("/customs/claims/<claim_id>/lines/<line_id>", methods=["DELETE"])
def void_claim_line(claim_id, line_id):
    _, role = authenticate()
    require_role(role, {"Analyst"})
    claim = get_claim_or_404(claim_id)
    line = STORE["claim_lines"].get(line_id)
    if line is None or line["claim_id"] != claim_id:
        raise_err(ERR_NOT_FOUND, f"Claim line {line_id} not found on claim {claim_id}")

    _claim_transition_guard(claim)
    if claim["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"Lines may only be voided on DRAFT claims (got {claim['status']})")
    if line["status"] == "VOID":
        raise_err(ERR_ALREADY_TERMINAL, "Claim line is VOID (terminal)")

    void_line_with_cascade(line)
    return success_object(serialize(line))


@bp.route("/customs/claim-lines/<line_id>", methods=["GET"])
def get_claim_line(line_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    line = STORE["claim_lines"].get(line_id)
    if line is None:
        raise_err(ERR_NOT_FOUND, f"Claim line {line_id} not found")
    claim = STORE["claims"].get(line["claim_id"])
    require_client_scope(user_id, role, claim["client_id"] if claim else None)
    return success_object(serialize(line))


@bp.route("/customs/claim-lines", methods=["GET"])
def list_claim_lines():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["claim_lines"].values())
    if role == "ClientContact":
        items = [
            l for l in items
            if STORE["claims"].get(l["claim_id"], {}).get("client_id") == user_id
        ]
    claim_id = request.args.get("claim_id")
    if claim_id is not None:
        items = [l for l in items if l["claim_id"] == claim_id]
    import_entry_id = request.args.get("import_entry_id")
    if import_entry_id is not None:
        items = [l for l in items if l["import_entry_id"] == import_entry_id]
    export_shipment_id = request.args.get("export_shipment_id")
    if export_shipment_id is not None:
        items = [l for l in items if l["export_shipment_id"] == export_shipment_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return paginate([serialize(l) for l in items])


# ---------------------------------------------------------------------------
# Claim lifecycle transitions
# ---------------------------------------------------------------------------

@bp.route("/customs/claims/<claim_id>/file", methods=["POST"])
def file_claim(claim_id):
    user_id, role = authenticate()
    require_role(role, {"LicensedBroker"})
    claim = get_claim_or_404(claim_id)
    get_body()  # tolerate stray payloads

    _claim_transition_guard(claim)
    if claim["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"Only DRAFT claims may be filed (got {claim['status']})")
    lines = active_lines_of_claim(claim_id)
    if not lines:
        raise_err(ERR_INVALID_REQUEST, "Claim must have at least one ACTIVE line")
    if user_id == claim["prepared_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Filer must differ from the preparer")
    client = STORE["clients"][claim["client_id"]]
    if client["engagement_status"] != "ACTIVE":
        raise_err(ERR_CLIENT_NOT_ACTIVE, "Client engagement is not ACTIVE")
    deadline = claim["filing_deadline"]
    if deadline is not None and logical_now() > deadline:
        raise_err(
            ERR_FILING_DEADLINE_PASSED,
            f"Logical clock is past filing_deadline ({fmt_dt(deadline)})",
        )

    now = logical_now()
    claim["status"] = "FILED"
    claim["filed_at"] = now
    claim["filed_by_user_id"] = user_id
    # FINAL variant: frozen as the sum of the per-line rounded amounts.
    claim["claimed_duty_cents"] = sum(l["drawback_amount_cents"] for l in lines)
    touch(claim)

    # Evidentiary package: three compliance records, retained indefinitely for now.
    for doc_type in RETENTION_DOC_TYPES:
        record = mint_entity()
        record.update({
            "claim_id": claim["id"],
            "doc_type": doc_type,
            "retention_until": None,
            "status": "RETAINED",
        })
        STORE["compliance_records"][record["id"]] = record

    return success_object(serialize(claim))


@bp.route("/customs/claims/<claim_id>/review", methods=["POST"])
def review_claim(claim_id):
    _, role = authenticate()
    require_role(role, {"LicensedBroker"})
    claim = get_claim_or_404(claim_id)
    body = get_body()
    outcome = req_enum(body, "outcome", {"APPROVED", "DENIED", "DEFICIENCY"})
    approved_duty_cents = None
    if outcome == "APPROVED":
        if body.get("approved_duty_cents") is None:
            raise_err(ERR_INVALID_REQUEST, "outcome=APPROVED requires approved_duty_cents")
        approved_duty_cents = req_int(body, "approved_duty_cents", minimum=0)

    _claim_transition_guard(claim)
    if claim["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, f"Review is only valid from FILED (got {claim['status']})")

    if outcome == "APPROVED":
        if approved_duty_cents > claim["claimed_duty_cents"]:
            raise_err(
                ERR_APPROVED_EXCEEDS_CLAIMED,
                "approved_duty_cents exceeds claimed_duty_cents",
            )
        claim["status"] = "APPROVED"
        claim["approved_duty_cents"] = approved_duty_cents
        touch(claim)
        # Claim enters the APPROVED accrual set.
        recompute_client_aggregates(STORE["clients"][claim["client_id"]])
    elif outcome == "DENIED":
        claim["status"] = "DENIED"
        void_all_active_lines(claim)
        touch(claim)
        recompute_client_aggregates(STORE["clients"][claim["client_id"]])
    else:  # DEFICIENCY
        if claim["deficiency_count"] >= 2:
            raise_err(ERR_DEFICIENCY_LIMIT_REACHED, "Deficiency cycle limit (2) reached")
        claim["deficiency_count"] += 1
        claim["status"] = "DEFICIENCY_ISSUED"
        touch(claim)
    return success_object(serialize(claim))


@bp.route("/customs/claims/<claim_id>/deficiency-response", methods=["POST"])
def deficiency_response(claim_id):
    user_id, role = authenticate()
    require_role(role, {"Analyst", "LicensedBroker", "ClientContact"})
    claim = get_claim_or_404(claim_id)
    get_body()
    require_client_scope(user_id, role, claim["client_id"])
    _claim_transition_guard(claim)
    if claim["status"] != "DEFICIENCY_ISSUED":
        raise_err(
            ERR_INVALID_STATE,
            f"Deficiency response is only valid from DEFICIENCY_ISSUED (got {claim['status']})",
        )
    claim["status"] = "FILED"
    touch(claim)
    return success_object(serialize(claim))


@bp.route("/customs/claims/<claim_id>/record-payment", methods=["POST"])
def record_payment(claim_id):
    _, role = authenticate()
    require_role(role, {"FirmAdmin"})
    claim = get_claim_or_404(claim_id)
    body = get_body()
    paid_duty_cents = req_int(body, "paid_duty_cents", minimum=0)

    _claim_transition_guard(claim)
    if claim["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, f"Payment requires APPROVED (got {claim['status']})")
    if paid_duty_cents != claim["approved_duty_cents"]:
        raise_err(ERR_PAID_AMOUNT_MISMATCH, "paid_duty_cents must equal approved_duty_cents")

    now = logical_now()
    claim["status"] = "PAID"
    claim["paid_duty_cents"] = paid_duty_cents
    claim["paid_at"] = now
    touch(claim)

    # Paid cascade link 1: invoice auto-created in ISSUED (SETTLED tiered fee).
    client = STORE["clients"][claim["client_id"]]
    invoice = mint_entity()
    invoice.update({
        "claim_id": claim["id"],
        "client_id": claim["client_id"],
        "recovered_duty_cents": paid_duty_cents,
        "fee_bps_snapshot": client["contingency_fee_bps"],
        "fee_cents": tiered_fee_cents(paid_duty_cents, client["contingency_fee_bps"]),
        "amount_paid_cents": 0,
        "status": "ISSUED",
    })
    invoice["balance_cents"] = invoice["fee_cents"] - invoice["amount_paid_cents"]
    STORE["invoices"][invoice["id"]] = invoice

    # Paid cascade link 2: client aggregates move.
    recompute_client_aggregates(client)

    # Paid cascade link 3: retention clock starts on the three records.
    retention_until = add_years(now, RETENTION_YEARS)
    for record in STORE["compliance_records"].values():
        if record["claim_id"] == claim["id"]:
            record["retention_until"] = retention_until
            touch(record)

    return success_object(serialize(claim))


@bp.route("/customs/claims/<claim_id>/cancel", methods=["POST"])
def cancel_claim(claim_id):
    _, role = authenticate()
    require_role(role, {"Analyst"})
    claim = get_claim_or_404(claim_id)
    get_body()
    _claim_transition_guard(claim)
    if claim["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"Only DRAFT claims may be cancelled (got {claim['status']})")
    claim["status"] = "CANCELLED"
    void_all_active_lines(claim)
    touch(claim)
    recompute_client_aggregates(STORE["clients"][claim["client_id"]])
    return success_object(serialize(claim))
