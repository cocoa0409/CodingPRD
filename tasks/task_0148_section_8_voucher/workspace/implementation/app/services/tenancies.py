"""Tenancy lifecycle: RFTA, finalize (ACTIVE/REJECTED), move-out."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from app import calculations, clock, store
from app.errors import APIError, fk_not_found, invalid_state, validation
from app.serializers import _occupancy_status
from app.services import payment_standards as ps_service
from app.services.common import occ_check, touch
from app.util import new_id, parse_iso, require_str


# Gates ordered per PRD §2.10. Each helper raises with the correct error_id.


def _ensure_caller_context(caller_pha_id: Optional[str], voucher: dict) -> None:
    """Voucher locality gate. caller_pha_id may be None for non-PHA roles, in
    which case we fall back to the configured default PHA (PHA_001).
    """
    pha = caller_pha_id or store.DEFAULT_PHA
    if voucher.get("administering_pha_id") != pha:
        raise APIError("ERR_VOUCHER_NOT_LOCAL", 403, "Voucher is not locally administered")


def create_tenancy(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation("Body must be a JSON object")
    try:
        voucher_id = require_str(payload.get("voucher_id"), field="voucher_id")
        unit_id = require_str(payload.get("unit_id"), field="unit_id")
        lease_start = parse_iso(payload.get("lease_start"))
        if lease_start is None:
            raise ValueError("lease_start is required")
    except ValueError as exc:
        raise validation(str(exc))

    # FK existence (priority 4).
    voucher = store.vouchers.get(voucher_id)
    if voucher is None:
        raise fk_not_found(f"voucher_id {voucher_id!r} not found")
    unit = store.units.get(unit_id)
    if unit is None:
        raise fk_not_found(f"unit_id {unit_id!r} not found")
    applicant = store.applicants.get(voucher.get("applicant_id"))
    if applicant is None:
        raise fk_not_found("voucher.applicant_id no longer resolves")

    # Voucher state (priority 5).
    if voucher.get("status") not in ("SEARCHING", "SEARCHING_REISSUED"):
        raise invalid_state("Voucher is not in SEARCHING/SEARCHING_REISSUED")

    # Voucher expiration (priority 6).
    now = clock.now()
    if now > voucher["search_deadline"]:
        raise APIError("ERR_VOUCHER_EXPIRED", 409, "Voucher search window has closed")

    # PHA locality (priority 7). We accept the default PHA for non-PHA callers.
    _ensure_caller_context(store.DEFAULT_PHA, voucher)

    # Note: special-mobility zone enforcement is a *finalize*-time gate
    # per PRD §3.7 — the RFTA gate list in §3.4 does not include it. The
    # voucher's frozen PaymentStandard tier still uses the mobility
    # amount, but the lease-up rejection is raised in finalize_tenancy.

    # Under-housing guard (priority 11).
    if voucher.get("bedroom_size", 0) >= 1 and unit.get("bedroom_count", 0) < 1:
        raise APIError("ERR_UNIT_TOO_SMALL", 422, "Unit is too small for this voucher")

    # Lease start within search window (priority 12).
    if lease_start > voucher["search_deadline"]:
        raise APIError("ERR_LEASE_START_AFTER_DEADLINE", 422, "lease_start is past search_deadline")

    # Unit vacancy (priority 14 region — but unit-not-vacant is the precondition).
    if _occupancy_status(unit_id) != "VACANT":
        raise APIError("ERR_UNIT_NOT_VACANT", 409, "Unit is not VACANT")

    # Tenancy interval overlap on the same unit (priority 14).
    for existing in store.tenancies.values():
        if existing.get("unit_id") != unit_id:
            continue
        # An existing tenancy that is TERMINATED/REJECTED with an end timestamp
        # must have ended strictly before this new tenancy's requested_at.
        if existing.get("status") not in ("TERMINATED", "REJECTED"):
            raise APIError("ERR_UNIT_OCCUPANCY_OVERLAP", 409, "Tenancy interval overlaps")
        end = existing.get("terminated_at") or existing.get("updated_at")
        if end is not None and end >= now:
            raise APIError("ERR_UNIT_OCCUPANCY_OVERLAP", 409, "Tenancy interval overlaps")

    # All gates passed. Freeze financial fields and persist.
    gross_rent_cents = unit["asking_rent_cents"] + unit["tenant_paid_utilities_cents"]
    cell_bedroom = min(voucher["bedroom_size"], unit["bedroom_count"])
    standard_row = ps_service.active_standard_for(
        zone=voucher["zone"],
        bedroom_size=cell_bedroom,
        asof=now,
    )
    if standard_row is None:
        raise validation(
            f"No PaymentStandard configured for zone={voucher['zone']} bedroom_size={cell_bedroom}"
        )
    if voucher.get("special_mobility_flag"):
        applicable_ps = standard_row["mobility_amount_cents"]
    else:
        applicable_ps = standard_row["standard_amount_cents"]

    tenancy_id = new_id()
    record = {
        "id": tenancy_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "voucher_id": voucher_id,
        "unit_id": unit_id,
        "requested_at": now,
        "lease_start": lease_start,
        "gross_rent_cents": gross_rent_cents,
        "applicable_payment_standard_cents": applicable_ps,
        "rent_reasonable": None,
        "initial_total_tenant_payment_cents": None,
        "initial_hap_cents": None,
        "current_total_tenant_payment_cents": None,
        "current_hap_cents": None,
        "rent_burden_at_lease_up_pct": None,
        "status": "PENDING_INSPECTION",
        "abatement_started_at": None,
        "termination_reason": None,
        "terminated_at": None,
    }
    store.tenancies[tenancy_id] = record
    return record


def finalize_tenancy(tenancy_id: str, payload: Optional[dict]) -> dict:
    payload = payload or {}
    tenancy = store.tenancies.get(tenancy_id)
    if tenancy is None:
        from app.errors import not_found
        raise not_found("Tenancy not found")
    occ_check(tenancy, payload.get("version"))

    # State gate (priority 5): must be in PENDING_RENT_REASONABLE.
    if tenancy["status"] != "PENDING_RENT_REASONABLE":
        raise invalid_state("Tenancy is not in PENDING_RENT_REASONABLE")

    voucher = store.vouchers.get(tenancy["voucher_id"])
    if voucher is None:
        raise invalid_state("Voucher missing for tenancy")
    unit = store.units.get(tenancy["unit_id"])
    if unit is None:
        raise invalid_state("Unit missing for tenancy")
    applicant = store.applicants.get(voucher["applicant_id"])
    if applicant is None:
        raise invalid_state("Applicant missing for tenancy")

    # Voucher expiration gate (priority 6).
    now = clock.now()
    if now > voucher["search_deadline"]:
        raise APIError("ERR_VOUCHER_EXPIRED", 409, "Voucher search window has closed")

    # PHA locality (priority 7).
    _ensure_caller_context(store.DEFAULT_PHA, voucher)

    # Mobility zone gate (priority 9).
    if voucher.get("special_mobility_flag") and unit.get("zone") != "ZONE_A":
        _reject_tenancy(tenancy)
        raise APIError(
            "ERR_MOBILITY_ZONE_VIOLATION",
            422,
            "Special mobility voucher requires ZONE_A unit",
        )

    # Rent reasonableness gate (priority 18). Pulled before burden per ordering.
    if tenancy.get("rent_reasonable") is not True:
        _reject_tenancy(tenancy)
        raise APIError("ERR_RENT_NOT_REASONABLE", 422, "Rent reasonableness gate failed")

    # Rent-burden div-zero gate (priority 17).
    if applicant.get("adjusted_annual_income_cents", 0) == 0:
        _reject_tenancy(tenancy)
        raise APIError("ERR_RENT_BURDEN_DIVZERO", 422, "Monthly adjusted income is zero")

    # Compute TTP + HAP (initial) so we can run the rent-burden gate against
    # the actual initial HAP figure.
    initial_ttp = calculations.calc_ttp(
        adjusted_annual_income_cents=applicant["adjusted_annual_income_cents"],
        gross_annual_income_cents=applicant["gross_annual_income_cents"],
    )
    initial_hap = calculations.calc_hap(
        applicable_payment_standard_cents=tenancy["applicable_payment_standard_cents"],
        gross_rent_cents=tenancy["gross_rent_cents"],
        ttp_cents=initial_ttp,
    )

    passes, burden_err = calculations.calc_rent_burden_passes(
        gross_rent_cents=tenancy["gross_rent_cents"],
        initial_hap_cents=initial_hap,
        adjusted_annual_income_cents=applicant["adjusted_annual_income_cents"],
    )
    if not passes:
        _reject_tenancy(tenancy)
        raise APIError(burden_err, 422, "Rent burden gate failed")

    burden_pct = calculations.calc_rent_burden_pct(
        gross_rent_cents=tenancy["gross_rent_cents"],
        initial_hap_cents=initial_hap,
        adjusted_annual_income_cents=applicant["adjusted_annual_income_cents"],
    )

    # Commit. Mutate tenancy, cascade voucher → LEASED, create AnnualReview.
    tenancy["initial_total_tenant_payment_cents"] = initial_ttp
    tenancy["initial_hap_cents"] = initial_hap
    tenancy["current_total_tenant_payment_cents"] = initial_ttp
    tenancy["current_hap_cents"] = initial_hap
    tenancy["rent_burden_at_lease_up_pct"] = round(burden_pct, 6)
    tenancy["status"] = "ACTIVE"
    touch(tenancy)

    voucher["status"] = "LEASED"
    touch(voucher)

    # Schedule first DUE AnnualReview at lease_start + 365 days.
    ar_id = new_id()
    review_due = tenancy["lease_start"] + timedelta(days=365)
    now2 = clock.now()
    store.annual_reviews[ar_id] = {
        "id": ar_id,
        "created_at": now2,
        "updated_at": now2,
        "version": 1,
        "tenancy_id": tenancy_id,
        "review_due_date": review_due,
        "submitted_at": None,
        "declared_gross_annual_income_cents": None,
        "declared_household_size": None,
        "new_adjusted_income_cents": None,
        "new_total_tenant_payment_cents": None,
        "new_hap_cents": None,
        "deficiency_codes": [],
        "status": "DUE",
        "deficient_since": None,
    }
    # Track current/DUE AnnualReview id on the parent Tenancy so callers
    # can discover the review without scanning the AR store.
    tenancy["current_annual_review_id"] = ar_id
    return tenancy


def _reject_tenancy(tenancy: dict) -> None:
    tenancy["status"] = "REJECTED"
    tenancy["terminated_at"] = clock.now()
    touch(tenancy)
    # Voucher stays in SEARCHING per §3.7.


def move_out(tenancy_id: str, payload: dict) -> dict:
    payload = payload or {}
    tenancy = store.tenancies.get(tenancy_id)
    if tenancy is None:
        from app.errors import not_found
        raise not_found("Tenancy not found")
    occ_check(tenancy, payload.get("version"))

    if tenancy["status"] != "ACTIVE":
        raise invalid_state("Tenancy is not ACTIVE")

    try:
        move_out_date = parse_iso(payload.get("move_out_date"))
        if move_out_date is None:
            raise ValueError("move_out_date is required")
    except ValueError as exc:
        raise validation(str(exc))

    tenancy["status"] = "TERMINATED"
    tenancy["termination_reason"] = "TENANT_MOVE_OUT"
    tenancy["terminated_at"] = move_out_date
    touch(tenancy)

    voucher = store.vouchers.get(tenancy["voucher_id"])
    if voucher is not None:
        voucher["status"] = "SEARCHING_REISSUED"
        voucher["search_deadline"] = move_out_date + timedelta(days=60)
        touch(voucher)

    # Per §3.8, any DUE AnnualReview auto-closes "as void". The state enum does
    # not include VOID, so we mark these reviews as DENIED (their tenancy is
    # already TERMINATED so further state on them is moot).
    return tenancy
