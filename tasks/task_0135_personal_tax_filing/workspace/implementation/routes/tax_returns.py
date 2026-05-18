"""TaxReturn routes (PRD §3.1, §3.5, §3.8, §3.10)."""
from __future__ import annotations

from flask import Blueprint, g, request

from config import (
    ACCOUNT_ACTIVE,
    DEDUCTION_METHODS,
    EFILING_PENDING,
    ELIG_PENDING,
    FILING_STATUSES,
    RETURN_STATUS_DRAFT,
    RETURN_STATUS_FILED,
    RETURN_STATUS_READY_TO_FILE,
    RETURN_STATUS_REJECTED,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
    TAX_YEAR_MAX,
    TAX_YEAR_MIN,
)
from db import store
from errors import (
    err_duplicate_return,
    err_invalid_input,
    err_invalid_state,
    err_qualifying_children_exceed,
    err_taxpayer_locked,
)
from middleware import require_auth
from response import list_success, success
from services import engine
from services.audit import append_audit
from utils import iso_now, new_submission_id, new_uuid

from routes._helpers import (
    check_version,
    enforce_return_owner,
    enforce_taxpayer_self,
    get_json,
    get_return_or_404,
    get_taxpayer_or_404,
    parse_pagination,
    parse_version,
    sort_by_created_at,
)


bp = Blueprint("tax_returns", __name__)


def _serialize_return(r: dict) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "taxpayer_id": r["taxpayer_id"],
        "tax_year": r["tax_year"],
        "filing_status": r["filing_status"],
        "dependents_count": r["dependents_count"],
        "qualifying_children_under_17": r["qualifying_children_under_17"],
        "status": r["status"],
        "deduction_method": r["deduction_method"],
        "total_income_cents": r["total_income_cents"],
        "agi_cents": r["agi_cents"],
        "taxable_income_cents": r["taxable_income_cents"],
        "regular_tax_cents": r["regular_tax_cents"],
        "amt_cents": r["amt_cents"],
        "total_credits_cents": r["total_credits_cents"],
        "total_withholding_cents": r["total_withholding_cents"],
        "estimated_payments_applied_cents": r["estimated_payments_applied_cents"],
        "balance_due_or_refund_cents": r["balance_due_or_refund_cents"],
        "filed_at": r.get("filed_at"),
        "accepted_at": r.get("accepted_at"),
    }


def _serialize_efiling(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "tax_return_id": e["tax_return_id"],
        "submission_id": e["submission_id"],
        "outcome": e["outcome"],
        "rejection_code": e.get("rejection_code"),
        "rejection_message": e.get("rejection_message"),
        "filed_at": e.get("filed_at"),
        "processed_at": e.get("processed_at"),
    }


def _validate_basics_for_create(body: dict):
    """Validate POST /tax-returns body inputs (priority 21 = ERR_INVALID_INPUT)."""
    taxpayer_id = body.get("taxpayer_id")
    tax_year = body.get("tax_year")
    filing_status = body.get("filing_status")
    if not isinstance(taxpayer_id, str) or not taxpayer_id.strip():
        raise err_invalid_input("taxpayer_id is required")
    if isinstance(tax_year, bool) or not isinstance(tax_year, int):
        raise err_invalid_input("tax_year must be an integer 2020..2025")
    if tax_year < TAX_YEAR_MIN or tax_year > TAX_YEAR_MAX:
        raise err_invalid_input("tax_year must be in the inclusive range 2020..2025")
    if filing_status not in FILING_STATUSES:
        raise err_invalid_input("filing_status must be a valid enum value")


# ── POST /tax-returns ───────────────────────────────────────────────────


@bp.post("/tax-returns")
@require_auth([ROLE_TAXPAYER])
def create_return():
    body = get_json()

    with store.lock:
        # Priority 3 (Taxpayer existence): only after auth+role pass.
        taxpayer_id = body.get("taxpayer_id")
        if isinstance(taxpayer_id, str) and taxpayer_id.strip():
            tp = get_taxpayer_or_404(taxpayer_id)
            # Ownership: a Taxpayer can only create their own return.
            enforce_taxpayer_self(tp)
        else:
            # Defer to ERR_INVALID_INPUT below.
            tp = None

        # Priority 6 (taxpayer locked) — only meaningful if taxpayer found.
        if tp is not None and tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()

        # Validation priority 13: qualifying_children <= dependents.
        dependents_count = body.get("dependents_count", 0)
        qualifying = body.get("qualifying_children_under_17", 0)
        if isinstance(dependents_count, bool) or not isinstance(dependents_count, int) or dependents_count < 0:
            raise err_invalid_input("dependents_count must be a non-negative integer")
        if isinstance(qualifying, bool) or not isinstance(qualifying, int) or qualifying < 0:
            raise err_invalid_input("qualifying_children_under_17 must be a non-negative integer")
        if qualifying > dependents_count:
            raise err_qualifying_children_exceed()

        # Priority 19: duplicate non-DRAFT return for same (taxpayer_id, tax_year).
        # Run only if all earlier-priority validations pass.
        # ERR_INVALID_INPUT is priority 21, but we need taxpayer/year/status
        # validated before duplicate check. Order: input validation first.
        _validate_basics_for_create(body)

        # Now check duplicate.
        for r in store.tax_returns.values():
            if (
                r["taxpayer_id"] == taxpayer_id
                and r["tax_year"] == body["tax_year"]
                and r["status"] != RETURN_STATUS_DRAFT
            ):
                raise err_duplicate_return()

        deduction_method = body.get("deduction_method", "STANDARD")
        if deduction_method not in DEDUCTION_METHODS:
            raise err_invalid_input("deduction_method must be STANDARD or ITEMIZED")

        r = {
            "id": new_uuid(),
            "taxpayer_id": taxpayer_id,
            "tax_year": body["tax_year"],
            "filing_status": body["filing_status"],
            "dependents_count": dependents_count,
            "qualifying_children_under_17": qualifying,
            "status": RETURN_STATUS_DRAFT,
            "deduction_method": deduction_method,
            "total_income_cents": 0,
            "agi_cents": 0,
            "taxable_income_cents": 0,
            "regular_tax_cents": 0,
            "amt_cents": 0,
            "total_credits_cents": 0,
            "total_withholding_cents": 0,
            "estimated_payments_applied_cents": 0,
            "balance_due_or_refund_cents": 0,
            "filed_at": None,
            "accepted_at": None,
        }
        engine.stamp_create(r)
        store.tax_returns[r["id"]] = r

    return success(_serialize_return(r), 201)


# ── GET /tax-returns ────────────────────────────────────────────────────


@bp.get("/tax-returns")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def list_returns():
    limit, offset = parse_pagination()
    f_taxpayer = request.args.get("taxpayer_id")
    f_year = request.args.get("tax_year")
    f_status = request.args.get("status")

    if f_year is not None:
        try:
            f_year_int = int(f_year)
        except (TypeError, ValueError):
            raise err_invalid_input("tax_year filter must be integer")
    else:
        f_year_int = None

    rows = list(store.tax_returns.values())
    if g.role == ROLE_TAXPAYER:
        rows = [r for r in rows if r["taxpayer_id"] == g.user_id]
    if f_taxpayer is not None:
        rows = [r for r in rows if r["taxpayer_id"] == f_taxpayer]
    if f_year_int is not None:
        rows = [r for r in rows if r["tax_year"] == f_year_int]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    rows = sort_by_created_at(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_success([_serialize_return(r) for r in page], limit, offset, total, 200)


# ── GET /tax-returns/{id} ───────────────────────────────────────────────


@bp.get("/tax-returns/<return_id>")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def get_return(return_id):
    r = get_return_or_404(return_id)
    enforce_return_owner(r)
    return success(_serialize_return(r), 200)


# ── PATCH /tax-returns/{id} ─────────────────────────────────────────────


@bp.patch("/tax-returns/<return_id>")
@require_auth([ROLE_TAXPAYER])
def patch_return(return_id):
    body = get_json()
    with store.lock:
        r = get_return_or_404(return_id)
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        # OCC
        expected = parse_version(body)
        # Patches only allowed when status is DRAFT or READY_TO_FILE (then revert).
        if r["status"] not in (RETURN_STATUS_DRAFT, RETURN_STATUS_READY_TO_FILE):
            raise err_invalid_state("TaxReturn must be in DRAFT or READY_TO_FILE to patch.")

        new_fs = body.get("filing_status", r["filing_status"])
        if new_fs not in FILING_STATUSES:
            raise err_invalid_input("filing_status must be a valid enum value")
        new_dep = body.get("dependents_count", r["dependents_count"])
        new_q = body.get("qualifying_children_under_17", r["qualifying_children_under_17"])
        if isinstance(new_dep, bool) or not isinstance(new_dep, int) or new_dep < 0:
            raise err_invalid_input("dependents_count must be a non-negative integer")
        if isinstance(new_q, bool) or not isinstance(new_q, int) or new_q < 0:
            raise err_invalid_input("qualifying_children_under_17 must be a non-negative integer")
        if new_q > new_dep:
            raise err_qualifying_children_exceed()
        new_dm = body.get("deduction_method", r["deduction_method"])
        if new_dm not in DEDUCTION_METHODS:
            raise err_invalid_input("deduction_method must be STANDARD or ITEMIZED")

        # Priority 20: OCC last.
        check_version(r, expected)

        r["filing_status"] = new_fs
        r["dependents_count"] = new_dep
        r["qualifying_children_under_17"] = new_q
        r["deduction_method"] = new_dm
        # Cascade: READY_TO_FILE → DRAFT and invalidate computed fields.
        engine.cascade_child_mutation(r)

    return success(_serialize_return(r), 200)


# ── POST /tax-returns/{id}/compute ──────────────────────────────────────


@bp.post("/tax-returns/<return_id>/compute")
@require_auth([ROLE_TAXPAYER])
def compute_return(return_id):
    body = get_json()
    expected = parse_version(body)
    with store.lock:
        r = get_return_or_404(return_id)
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if r["status"] != RETURN_STATUS_DRAFT:
            raise err_invalid_state("compute requires return.status == DRAFT")

        # Filing status is required (always set on creation but guard regardless).
        if r.get("filing_status") not in FILING_STATUSES:
            raise err_invalid_state("filing_status must be set on the return")

        # Preconditions on children (mirrors validations priorities 10-12).
        docs = [d for d in store.income_documents.values() if d["tax_return_id"] == return_id]
        schedules_a = [
            s for s in store.schedules.values()
            if s["tax_return_id"] == return_id and s["schedule_type"] == "A"
        ]
        # Re-check SALT cap on every Schedule A.
        for s in schedules_a:
            if (s.get("itemized_salt_cents", 0) or 0) > 1_000_000:
                # Already prevented at write time but defensive.
                from errors import err_salt_cap_exceeded
                raise err_salt_cap_exceeded()
        # Re-check 1099-DIV qualified <= ordinary.
        for d in docs:
            if d["doc_type"] == "1099_DIV":
                if (d.get("qualified_dividends_cents", 0) or 0) > (d.get("ordinary_dividends_cents", 0) or 0):
                    from errors import err_qualified_div_exceeds_ordinary
                    raise err_qualified_div_exceeds_ordinary()
        # At least one IncomeDocument attached, OR (deduction=STANDARD and zero income).
        if not docs and r["deduction_method"] != "STANDARD":
            raise err_invalid_state("Return must have at least one IncomeDocument or use STANDARD deduction")

        # Priority 20: OCC.
        check_version(r, expected)

        engine.run_compute_pipeline(r, tp)
        engine.stamp_update(r)

    return success(_serialize_return(r), 200)


# ── POST /tax-returns/{id}/efile ────────────────────────────────────────


@bp.post("/tax-returns/<return_id>/efile")
@require_auth([ROLE_TAXPAYER])
def efile_return(return_id):
    body = get_json()
    expected = parse_version(body)
    with store.lock:
        r = get_return_or_404(return_id)
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if r["status"] != RETURN_STATUS_READY_TO_FILE:
            raise err_invalid_state("efile requires return.status == READY_TO_FILE")

        # Every TaxCredit on the return must have been evaluated (not PENDING).
        pending_credits = [
            c for c in store.tax_credits.values()
            if c["tax_return_id"] == return_id and c["eligibility_status"] == ELIG_PENDING
        ]
        if pending_credits:
            raise err_invalid_state("All TaxCredits must be evaluated before e-filing")

        # OCC priority 20.
        check_version(r, expected)

        now_iso = iso_now(store.clock_now())
        efiling = {
            "id": new_uuid(),
            "tax_return_id": r["id"],
            "submission_id": new_submission_id(),
            "outcome": EFILING_PENDING,
            "rejection_code": None,
            "rejection_message": None,
            "filed_at": now_iso,
            "processed_at": None,
        }
        # EFiling has only created_at + id (no updated_at/version).
        efiling["created_at"] = iso_now(store.now())
        store.efilings[efiling["id"]] = efiling

        r["status"] = RETURN_STATUS_FILED
        r["filed_at"] = now_iso
        engine.stamp_update(r)

        append_audit(
            actor_role=g.role,
            actor_id=g.user_id,
            action="RETURN_FILED",
            target_entity="TaxReturn",
            target_id=r["id"],
            payload={"efiling_id": efiling["id"], "submission_id": efiling["submission_id"]},
        )

    return success(_serialize_efiling(efiling), 201)


# ── POST /tax-returns/{id}/unlock-for-correction ────────────────────────


@bp.post("/tax-returns/<return_id>/unlock-for-correction")
@require_auth([ROLE_TAXPAYER])
def unlock_for_correction(return_id):
    with store.lock:
        r = get_return_or_404(return_id)
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if r["status"] != RETURN_STATUS_REJECTED:
            raise err_invalid_state("unlock requires return.status == REJECTED")
        # Most recent EFiling for this return must have outcome == REJECTED.
        related = [e for e in store.efilings.values() if e["tax_return_id"] == r["id"]]
        if not related:
            raise err_invalid_state("No EFiling for this return")
        latest = max(related, key=lambda e: e["created_at"])
        if latest["outcome"] != "REJECTED":
            raise err_invalid_state("Most recent EFiling is not REJECTED")

        r["status"] = RETURN_STATUS_DRAFT
        engine.invalidate_computed_fields(r)
        engine.stamp_update(r)

        append_audit(
            actor_role=g.role,
            actor_id=g.user_id,
            action="RETURN_REOPENED",
            target_entity="TaxReturn",
            target_id=r["id"],
            payload={},
        )

    return success(_serialize_return(r), 200)


# ── GET /tax-returns/{id}/safe-harbor ───────────────────────────────────


@bp.get("/tax-returns/<return_id>/safe-harbor")
@require_auth([ROLE_TAXPAYER])
def safe_harbor(return_id):
    from services.calculations import calc_safe_harbor

    with store.lock:
        r = get_return_or_404(return_id)
        enforce_return_owner(r)

        current_tax = (r.get("regular_tax_cents", 0) or 0) + (r.get("amt_cents", 0) or 0)
        payments_made = (r.get("total_withholding_cents", 0) or 0) + (
            r.get("estimated_payments_applied_cents", 0) or 0
        )

        prior = engine.find_prior_year_return(r["taxpayer_id"], r["tax_year"])
        if prior is None:
            prior_total = None
        else:
            prior_total = (prior.get("regular_tax_cents", 0) or 0) + (
                prior.get("amt_cents", 0) or 0
            )

        result = calc_safe_harbor(current_tax, r.get("agi_cents", 0) or 0, payments_made, prior_total)

    return success(result, 200)
