"""Installment agreement endpoints (§3.4)."""
from __future__ import annotations

from typing import List

from flask import Blueprint, request

from app.auth import enforce_taxpayer_ownership, require_roles
from app.envelope import success, success_list
from app.errors import (
    ERR_DDIA_REQUIRED,
    ERR_INELIGIBLE_AGREEMENT_TYPE,
    ERR_INVALID_STATE,
    ERR_LIABILITY_LOCKED,
    ERR_LIABILITY_NOT_ELIGIBLE,
    ERR_LIABILITY_NOT_OWNED,
    ERR_NOT_FOUND,
    ERR_OVERPAYMENT,
    ERR_VALIDATION,
    raise_error,
)
from app.services.calculations import project_payoff
from app.services.common import bump_version, check_version, init_common_fields
from app.services.csed import close_events_of_kind
from app.services.liabilities import (
    get_liabilities,
    recompute_balance,
    set_status,
    sum_balances,
)
from app.services.liens import release_check
from app.services.payment_allocation import allocate, settle_to_paid_if_zero
from app.services.taxpayers import refresh_taxpayer_aggregates
from app.store import STORE, new_id
from app.timeutil import add_days, fmt, now_iso, parse_iso
from app.util import (
    get_json_body,
    get_pagination,
    optional_version,
    paginate,
    require_enum,
    require_fields,
    require_int,
    require_list,
    require_str,
)


bp = Blueprint("installment_agreements", __name__, url_prefix="/collections/installment-agreements")


PAYMENT_METHODS = ("CHECK", "DDIA", "PAYROLL_DEDUCTION")
IA_STATUSES = ("PENDING", "ACTIVE", "DEFAULTED", "TERMINATED", "COMPLETED")
AGGREGATE_DDIA_THRESHOLD = 2_500_000  # $25,000
LONG_TERM_DEBT_CAP = 5_000_000        # $50,000
SHORT_TERM_DAYS = 180


def _serialize(ia: dict) -> dict:
    return {
        "id": ia["id"],
        "taxpayer_id": ia["taxpayer_id"],
        "liability_ids": list(ia["liability_ids"]),
        "agreement_type": ia["agreement_type"],
        "proposed_monthly_payment_cents": ia["proposed_monthly_payment_cents"],
        "payment_method": ia["payment_method"],
        "ddia_bank_account_last4": ia.get("ddia_bank_account_last4"),
        "next_due_date": ia.get("next_due_date"),
        "planned_payoff_date": ia.get("planned_payoff_date"),
        "missed_payment_count": ia.get("missed_payment_count", 0),
        "status": ia["status"],
        "activation_date": ia.get("activation_date"),
        "activated_by_officer_id": ia.get("activated_by_officer_id"),
        "created_at": ia["created_at"],
        "updated_at": ia["updated_at"],
        "version": ia["version"],
    }


def _classify_type(aggregate_debt: int, proposed_monthly: int, csed_min_iso: str,
                   activation_iso: str, mdi: int) -> str:
    """Classify into SHORT_TERM, LONG_TERM, or PPIA. Raises ERR_INELIGIBLE_AGREEMENT_TYPE if none fit."""
    # SHORT_TERM: 4 months of payment >= total debt AND projected payoff within 180 days
    if proposed_monthly * 4 >= aggregate_debt:
        # Verify spread within 180 days: months_needed * 30 days <= 180
        months_needed = (aggregate_debt + proposed_monthly - 1) // max(1, proposed_monthly)
        if months_needed * 30 <= SHORT_TERM_DAYS:
            return "SHORT_TERM"

    # Project payoff for LONG_TERM vs PPIA check
    csed_min_dt = parse_iso(csed_min_iso)
    activation_dt = parse_iso(activation_iso)

    if aggregate_debt <= LONG_TERM_DEBT_CAP:
        # Tentatively LONG_TERM if projected payoff <= csed_min
        proj = project_payoff(
            initial_balance_cents=aggregate_debt,
            monthly_payment_cents=proposed_monthly,
            activation_iso=activation_iso,
            csed_effective_min_iso=csed_min_iso,
            agreement_type="LONG_TERM",
        )
        proj_dt = parse_iso(proj)
        if proj_dt <= csed_min_dt:
            return "LONG_TERM"

    # PPIA: requires payoff > csed_min AND mdi >= proposed_monthly
    if mdi >= proposed_monthly:
        proj = project_payoff(
            initial_balance_cents=aggregate_debt,
            monthly_payment_cents=proposed_monthly,
            activation_iso=activation_iso,
            csed_effective_min_iso=csed_min_iso,
            agreement_type="PPIA",
        )
        proj_dt = parse_iso(proj)
        if proj_dt > csed_min_dt or proj_dt == csed_min_dt:  # PPIA's hallmark is statute-capped
            # Verify it's actually PPIA-shaped: balance would not be cleared in time
            return "PPIA"

    raise_error(ERR_INELIGIBLE_AGREEMENT_TYPE, "Proposal does not satisfy SHORT_TERM, LONG_TERM, or PPIA gates.")


def _csed_min_iso(liabs) -> str:
    return min(l["csed_effective_date"] for l in liabs)


# ---------------------------------------------------------------------------
# POST /collections/installment-agreements  — DRAFT/PENDING creation
# ---------------------------------------------------------------------------

@bp.route("", methods=["POST"])
@require_roles("Taxpayer", "IRSOfficer")
def create_agreement(identity):
    body = get_json_body()
    require_fields(body, ["taxpayer_id", "liability_ids", "proposed_monthly_payment_cents", "payment_method"])
    taxpayer_id = require_str(body, "taxpayer_id")
    liab_ids = require_list(body, "liability_ids", min_len=1)
    if any(not isinstance(x, str) for x in liab_ids):
        raise_error(ERR_VALIDATION, "liability_ids must be an array of strings.")
    proposed_monthly = require_int(body, "proposed_monthly_payment_cents", minimum=1)
    method = require_enum(body, "payment_method", PAYMENT_METHODS)
    last4 = body.get("ddia_bank_account_last4")
    if method == "DDIA":
        if not (isinstance(last4, str) and last4.isdigit() and len(last4) == 4):
            raise_error(ERR_VALIDATION, "ddia_bank_account_last4 must be 4 digits when payment_method is DDIA.")
    else:
        last4 = None

    with STORE.lock:
        tp = STORE.taxpayers.get(taxpayer_id)
        if tp is None:
            raise_error(ERR_NOT_FOUND, f"Taxpayer {taxpayer_id!r} not found.")
        enforce_taxpayer_ownership(identity, taxpayer_id)

        # Existence + ownership of liabilities
        liabs = []
        for lid in liab_ids:
            l = STORE.tax_liabilities.get(lid)
            if l is None or l["taxpayer_id"] != taxpayer_id:
                raise_error(ERR_LIABILITY_NOT_OWNED, f"Liability {lid!r} not owned by taxpayer.")
            liabs.append(l)

        # Liability status eligibility (priority 7)
        for l in liabs:
            if l["status"] not in ("OPEN", "IN_AGREEMENT"):
                raise_error(ERR_LIABILITY_NOT_ELIGIBLE,
                            f"Liability {l['id']!r} is in status {l['status']} and ineligible.")

        aggregate_debt = sum(l["current_balance_cents"] for l in liabs)

        # DDIA threshold (priority 13)
        if aggregate_debt > AGGREGATE_DDIA_THRESHOLD and method != "DDIA":
            raise_error(ERR_DDIA_REQUIRED,
                        "Aggregate debt > $25,000 requires payment_method == DDIA.")

        # Classify agreement type (priorities 14-16)
        activation_iso = now_iso()
        csed_min_iso = _csed_min_iso(liabs)
        agreement_type = _classify_type(
            aggregate_debt, proposed_monthly, csed_min_iso, activation_iso,
            tp["monthly_disposable_income_cents"],
        )

        ia = {
            "id": new_id(),
            "taxpayer_id": taxpayer_id,
            "liability_ids": list(liab_ids),
            "agreement_type": agreement_type,
            "proposed_monthly_payment_cents": proposed_monthly,
            "payment_method": method,
            "ddia_bank_account_last4": last4,
            "next_due_date": None,
            "planned_payoff_date": None,
            "missed_payment_count": 0,
            "status": "PENDING",
            "activation_date": None,
            "activated_by_officer_id": None,
        }
        init_common_fields(ia)
        STORE.installment_agreements[ia["id"]] = ia

    return success(_serialize(ia), status=201)


# ---------------------------------------------------------------------------
# GET /collections/installment-agreements/{id}
# ---------------------------------------------------------------------------

@bp.route("/<ia_id>", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer", "Taxpayer")
def get_agreement(identity, ia_id):
    with STORE.lock:
        ia = STORE.installment_agreements.get(ia_id)
        if ia is None:
            raise_error(ERR_NOT_FOUND, f"InstallmentAgreement {ia_id!r} not found.")
        enforce_taxpayer_ownership(identity, ia["taxpayer_id"])
        return success(_serialize(ia))


# ---------------------------------------------------------------------------
# POST /collections/installment-agreements/{id}/activate
# ---------------------------------------------------------------------------

@bp.route("/<ia_id>/activate", methods=["POST"])
@require_roles("IRSOfficer")
def activate_agreement(identity, ia_id):
    body = get_json_body()
    with STORE.lock:
        ia = STORE.installment_agreements.get(ia_id)
        if ia is None:
            raise_error(ERR_NOT_FOUND, f"InstallmentAgreement {ia_id!r} not found.")
        if ia["status"] != "PENDING":
            raise_error(ERR_INVALID_STATE, f"Agreement is in status {ia['status']}, cannot activate.")
        check_version(ia, optional_version(body))

        liabs = get_liabilities(ia["liability_ids"])

        # Liability eligibility re-check
        for l in liabs:
            if l["status"] not in ("OPEN", "IN_AGREEMENT"):
                raise_error(ERR_LIABILITY_NOT_ELIGIBLE,
                            f"Liability {l['id']!r} is in status {l['status']} and ineligible.")

        # Cross-workflow lock: any liability held by an UNDER_REVIEW OIC
        for oic in STORE.offers.values():
            if oic["status"] == "UNDER_REVIEW" and any(lid in oic["liability_ids"] for lid in ia["liability_ids"]):
                raise_error(ERR_LIABILITY_LOCKED,
                            "Liability is locked by an UNDER_REVIEW Offer in Compromise.")

        tp = STORE.taxpayers[ia["taxpayer_id"]]
        aggregate_debt = sum(l["current_balance_cents"] for l in liabs)

        if aggregate_debt > AGGREGATE_DDIA_THRESHOLD and ia["payment_method"] != "DDIA":
            raise_error(ERR_DDIA_REQUIRED,
                        "Aggregate debt > $25,000 requires payment_method == DDIA.")

        # Re-classify type
        activation_iso = now_iso()
        csed_min_iso = _csed_min_iso(liabs)
        agreement_type = _classify_type(
            aggregate_debt, ia["proposed_monthly_payment_cents"], csed_min_iso,
            activation_iso, tp["monthly_disposable_income_cents"],
        )
        ia["agreement_type"] = agreement_type

        # Activate
        ia["status"] = "ACTIVE"
        ia["activation_date"] = activation_iso
        ia["activated_by_officer_id"] = identity.user_id
        # next_due_date: activation + 30 days
        ia["next_due_date"] = fmt(add_days(parse_iso(activation_iso), 30))
        # planned_payoff_date
        ia["planned_payoff_date"] = project_payoff(
            initial_balance_cents=aggregate_debt,
            monthly_payment_cents=ia["proposed_monthly_payment_cents"],
            activation_iso=activation_iso,
            csed_effective_min_iso=csed_min_iso,
            agreement_type=agreement_type,
        )
        bump_version(ia)

        # Transition covered liabilities to IN_AGREEMENT
        for l in liabs:
            set_status(l, "IN_AGREEMENT")
            # Close any open INSTALLMENT_PENDING tolling event
            close_events_of_kind(l["id"], "INSTALLMENT_PENDING")

        refresh_taxpayer_aggregates(ia["taxpayer_id"])
        return success(_serialize(ia))


# ---------------------------------------------------------------------------
# POST /collections/installment-agreements/{id}/record-payment
# ---------------------------------------------------------------------------

@bp.route("/<ia_id>/record-payment", methods=["POST"])
@require_roles("IRSOfficer")
def record_payment(identity, ia_id):
    body = get_json_body()
    require_fields(body, ["amount_cents", "received_at"])
    amount = require_int(body, "amount_cents", minimum=1)
    received_at = require_str(body, "received_at")
    try:
        parse_iso(received_at)
    except ValueError:
        raise_error(ERR_VALIDATION, "received_at must be ISO 8601 UTC.")

    with STORE.lock:
        ia = STORE.installment_agreements.get(ia_id)
        if ia is None:
            raise_error(ERR_NOT_FOUND, f"InstallmentAgreement {ia_id!r} not found.")
        if ia["status"] != "ACTIVE":
            raise_error(ERR_INVALID_STATE, f"Agreement is in status {ia['status']}, cannot record payment.")

        liabs = get_liabilities(ia["liability_ids"])

        # CSED expiration check (priority 10)
        from app.timeutil import CLOCK
        now_dt = CLOCK.now()
        for l in liabs:
            eff = parse_iso(l["csed_effective_date"])
            if eff <= now_dt:
                from app.errors import ERR_CSED_EXPIRED
                raise_error(ERR_CSED_EXPIRED, f"Liability {l['id']!r} has expired.")

        # Overpayment check (priority 20): amount > sum of balances
        total_balance = sum(l["current_balance_cents"] for l in liabs)
        if amount > total_balance:
            raise_error(ERR_OVERPAYMENT, "Payment amount exceeds remaining balance across covered liabilities.")

        # Allocate
        rows, remaining = allocate(amount, ia["liability_ids"])
        # remaining should be 0 since amount <= total_balance, but defensive:
        if remaining > 0:
            raise_error(ERR_OVERPAYMENT, "Payment surplus after allocation.")

        payment = {
            "id": new_id(),
            "agreement_id": ia_id,
            "taxpayer_id": ia["taxpayer_id"],
            "amount_cents": amount,
            "received_at": received_at,
            "payment_kind": "INSTALLMENT",
            "allocation": rows,
            "oic_id": None,
        }
        init_common_fields(payment, with_version=False)
        STORE.payments[payment["id"]] = payment

        # next_due_date += 30 days; reset missed_payment_count
        ia["next_due_date"] = fmt(add_days(parse_iso(ia["next_due_date"]), 30))
        ia["missed_payment_count"] = 0
        bump_version(ia)

        # Settle to PAID for liabilities now at zero balance
        newly_paid = settle_to_paid_if_zero(ia["liability_ids"])

        # Cascade COMPLETED if all covered now have balance 0
        if all(STORE.tax_liabilities[lid]["current_balance_cents"] == 0 for lid in ia["liability_ids"]):
            ia["status"] = "COMPLETED"
            bump_version(ia)
            release_check(dominant_cause="PAID_IN_FULL")

        refresh_taxpayer_aggregates(ia["taxpayer_id"])
        return success(_serialize_payment(payment), status=201)


def _serialize_payment(p: dict) -> dict:
    return {
        "id": p["id"],
        "agreement_id": p.get("agreement_id"),
        "taxpayer_id": p["taxpayer_id"],
        "amount_cents": p["amount_cents"],
        "received_at": p["received_at"],
        "payment_kind": p["payment_kind"],
        "allocation": list(p["allocation"]),
        "oic_id": p.get("oic_id"),
        "created_at": p["created_at"],
    }


# ---------------------------------------------------------------------------
# POST /collections/installment-agreements/{id}/terminate
# ---------------------------------------------------------------------------

@bp.route("/<ia_id>/terminate", methods=["POST"])
@require_roles("IRSOfficer")
def terminate_agreement(identity, ia_id):
    body = get_json_body()
    with STORE.lock:
        ia = STORE.installment_agreements.get(ia_id)
        if ia is None:
            raise_error(ERR_NOT_FOUND, f"InstallmentAgreement {ia_id!r} not found.")
        if ia["status"] != "DEFAULTED":
            raise_error(ERR_INVALID_STATE, f"Agreement is in status {ia['status']}, cannot terminate.")
        check_version(ia, optional_version(body))

        # Block terminate if a PENDING reconsideration exists
        for r in STORE.reconsiderations.values():
            if r["agreement_id"] == ia_id and r["status"] == "PENDING":
                raise_error(ERR_INVALID_STATE, "Cannot terminate: PENDING reconsideration exists.")

        ia["status"] = "TERMINATED"
        bump_version(ia)

        # Revert covered liabilities
        for lid in ia["liability_ids"]:
            liab = STORE.tax_liabilities.get(lid)
            if liab is None:
                continue
            if liab["current_balance_cents"] == 0:
                set_status(liab, "PAID")
            elif liab["status"] == "IN_AGREEMENT":
                set_status(liab, "OPEN")

        refresh_taxpayer_aggregates(ia["taxpayer_id"])
        return success(_serialize(ia))


# ---------------------------------------------------------------------------
# GET /collections/installment-agreements
# ---------------------------------------------------------------------------

@bp.route("", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer", "Taxpayer")
def list_agreements(identity):
    limit, offset = get_pagination()
    taxpayer_filter = request.args.get("taxpayer_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in IA_STATUSES:
        raise_error(ERR_VALIDATION, "Invalid status filter.")

    with STORE.lock:
        items = list(STORE.installment_agreements.values())
        if identity.role == "Taxpayer":
            items = [ia for ia in items if ia["taxpayer_id"] == identity.user_id]
        if taxpayer_filter:
            items = [ia for ia in items if ia["taxpayer_id"] == taxpayer_filter]
        if status_filter:
            items = [ia for ia in items if ia["status"] == status_filter]
        items.sort(key=lambda ia: ia["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([_serialize(ia) for ia in page], limit, offset, total)
