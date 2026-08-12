"""Invoices, charge lines, the block ledger, notifications and the logical
clock (PRD 3.9, 2.5)."""

from flask import Blueprint

from core import clock, db, envelope, gates
from core.auth import READ_ROLES, authenticate, authorize
from core.errors import ApiError
from core.validate import body, fail, req_id, req_int, req_str
from routes.common import apply_filters, fk, listing, need, one
from services import derive, pricing

bp = Blueprint("billing", __name__)


# ==========================================================================
# Invoice
# ==========================================================================

@bp.post("/invoices")
def create_invoice():
    authenticate()
    authorize("BillingAdmin")
    data = body()
    clinic = fk(data, "clinic_id", "clinics", "ERR_CLINIC_NOT_FOUND")
    req_id(data, "clinic_id")
    period_start = req_str(data, "period_start")
    period_end = req_str(data, "period_end")
    if clock.parse_date(period_start) is None:
        fail("Field 'period_start' must be a YYYY-MM-DD calendar date.")
    if clock.parse_date(period_end) is None:
        fail("Field 'period_end' must be a YYYY-MM-DD calendar date.")
    if clock.parse_date(period_end) < clock.parse_date(period_start):
        fail("period_end must not precede period_start.")

    rec = db.new_record()
    rec.update(
        {
            "clinic_id": clinic["id"],
            "period_start": period_start,
            "period_end": period_end,
            "status": "OPEN",
            "finalized_total_cents": None,
            "finalized_at": None,
        }
    )
    db.insert("invoices", rec)
    return one("invoices", rec, 201)


@bp.get("/invoices/<invoice_id>")
def get_invoice(invoice_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("invoices", need("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND"))


@bp.get("/invoices")
def list_invoices():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("invoices")
    rows = apply_filters(rows, {"clinic_id": "clinic_id", "status": "status"})
    return listing("invoices", rows)


def _charge_line(invoice, study, kind, amount):
    rec = db.new_record()
    rec.update(
        {
            "invoice_id": invoice["id"],
            "study_id": study["id"],
            "kind": kind,
            "amount_cents": amount,
            "status": "ACTIVE",
            "reversal_reason": None,
        }
    )
    return db.insert("charge_lines", rec)


@bp.post("/invoices/<invoice_id>/post-study")
def post_study(invoice_id):
    authenticate()
    authorize("BillingAdmin")
    invoice = need("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    data = body()
    study = fk(data, "study_id", "studies", "ERR_STUDY_NOT_FOUND")
    req_id(data, "study_id")
    expected = req_int(data, "expected_invoice_version")
    # rung 7
    if expected != invoice["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # rung 8 (G1)
    gates.g1_invoice_not_finalized(invoice)
    # rung 16 — exactly one ACTIVE contract for the study's clinic
    clinic_id = derive.clinic_id_of_study(study)
    actives = derive.active_contracts_for_clinic(clinic_id)
    if len(actives) != 1:
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    contract = actives[0]

    fee_only = (
        study["workflow_status"] != "FINALIZED"
        and study.get("cancellation_fee_cents", 0) > 0
    )
    # rung 47
    if clinic_id != invoice["clinic_id"]:
        raise ApiError("ERR_CLINIC_MISMATCH")
    billable_instant = study["updated_at"] if fee_only else study.get("acquired_at")
    if billable_instant is None:
        raise ApiError("ERR_STUDY_OUTSIDE_INVOICE_PERIOD")
    billable_date = clock.date_utc(billable_instant)
    if not (
        clock.parse_date(invoice["period_start"])
        <= billable_date
        <= clock.parse_date(invoice["period_end"])
    ):
        raise ApiError("ERR_STUDY_OUTSIDE_INVOICE_PERIOD")
    # rung 48
    if study["workflow_status"] != "FINALIZED" and not fee_only:
        raise ApiError("ERR_STUDY_NOT_FINALIZED")
    # rung 49
    if study["billing_status"] == "NON_BILLABLE":
        raise ApiError("ERR_STUDY_NON_BILLABLE")
    # rung 50
    if study["billing_status"] == "POSTED":
        raise ApiError("ERR_STUDY_ALREADY_POSTED")

    if fee_only:
        _charge_line(
            invoice, study, "CANCELLATION_FEE", study["cancellation_fee_cents"]
        )
    else:
        # Re-derive from scratch on every posting (a re-post after a cascade
        # reversal must see the refunded block balance), then pin what was
        # actually billed.
        study["_billed_price_basis"] = None
        study["_billed_base_price_cents"] = 0
        parts = pricing.decomposition(study, contract, resolved=True)
        study["_billed_price_basis"] = parts["price_basis"]
        study["_billed_base_price_cents"] = parts["base_price_cents"]
        _charge_line(invoice, study, "STUDY_READ", parts["base_price_cents"])
        if parts["trip_share_cents"] > 0:
            _charge_line(
                invoice, study, "TRIP_FEE_SHARE", parts["trip_share_cents"]
            )
        if study["priority"] == "STAT":
            _charge_line(
                invoice, study, "STAT_SURCHARGE", parts["stat_surcharge_cents"]
            )
        _charge_line(invoice, study, "ADMIN_FEE", parts["admin_fee_cents"])
        # The block is drawn AFTER the study has been priced off it.
        if (
            contract["kind"] == "PREPAID_BLOCK"
            and derive.contract_remaining(contract) > 0
            and study["billing_status"] != "NON_BILLABLE"
        ):
            entry = db.new_record(with_version=False)
            entry.update(
                {
                    "contract_id": contract["id"],
                    "study_id": study["id"],
                    "delta_studies": -1,
                    "reason": "DRAW",
                    "balance_after_studies": derive.contract_remaining(contract) - 1,
                }
            )
            db.insert("block_ledger_entries", entry)
            db.touch(contract)

    study["billing_status"] = "POSTED"
    db.touch(study)
    db.touch(invoice)
    stop = derive.stop_of_study(study)
    if stop is not None:
        pricing.reprice_stop_siblings(stop)
    return one("invoices", invoice)


@bp.post("/invoices/<invoice_id>/finalize")
def finalize_invoice(invoice_id):
    authenticate()
    authorize("BillingAdmin")
    invoice = need("invoices", invoice_id, "ERR_INVOICE_NOT_FOUND")
    # rung 8 (G1)
    gates.g1_invoice_not_finalized(invoice)
    invoice["finalized_total_cents"] = derive.invoice_total_cents(invoice)
    invoice["finalized_at"] = clock.now()
    invoice["status"] = "FINALIZED"
    db.touch(invoice)
    return one("invoices", invoice)


# ==========================================================================
# ChargeLine
# ==========================================================================

@bp.get("/charge-lines/<charge_line_id>")
def get_charge_line(charge_line_id):
    authenticate()
    authorize(*READ_ROLES)
    return one(
        "charge_lines", need("charge_lines", charge_line_id, "ERR_RECORD_NOT_FOUND")
    )


@bp.get("/charge-lines")
def list_charge_lines():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("charge_lines")
    rows = apply_filters(
        rows,
        {
            "invoice_id": "invoice_id",
            "study_id": "study_id",
            "kind": "kind",
            "status": "status",
        },
    )
    return listing("charge_lines", rows)


# ==========================================================================
# BlockLedgerEntry
# ==========================================================================

@bp.get("/block-ledger-entries/<entry_id>")
def get_block_entry(entry_id):
    authenticate()
    authorize(*READ_ROLES)
    return one(
        "block_ledger_entries",
        need("block_ledger_entries", entry_id, "ERR_RECORD_NOT_FOUND"),
    )


@bp.get("/block-ledger-entries")
def list_block_entries():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("block_ledger_entries")
    rows = apply_filters(rows, {"contract_id": "contract_id", "study_id": "study_id"})
    return listing("block_ledger_entries", rows)


# ==========================================================================
# Notification
# ==========================================================================

@bp.get("/notifications/<notification_id>")
def get_notification(notification_id):
    authenticate()
    authorize(*READ_ROLES)
    return one(
        "notifications", need("notifications", notification_id, "ERR_RECORD_NOT_FOUND")
    )


@bp.get("/notifications")
def list_notifications():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("notifications")
    rows = apply_filters(
        rows, {"clinic_id": "clinic_id", "study_id": "study_id", "kind": "kind"}
    )
    return listing("notifications", rows)


# ==========================================================================
# The logical clock
# ==========================================================================

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate()
    authorize("PlatformAdmin")
    data = body()
    raw = req_str(data, "to_iso8601")
    parsed = clock.parse_instant(raw)
    if parsed is None:
        fail("Field 'to_iso8601' must be an ISO 8601 instant.")
    clock.set_now(parsed)
    # Case (ii) of the timestamp policy: a caller-supplied instant is parsed and
    # consistently RE-RENDERED through the single renderer.
    return envelope.object_response({"current_utc": clock.render(clock.now())})
