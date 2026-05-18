"""Trust engine — state-machine transitions, cascades, balance bookkeeping.

This module knows the entity dictionaries' shape and is the only place
that mutates them. Routes call into it under a single global lock so
the concurrency rules in scaffold §1.2.1 hold.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from db import store
from errors import (
    err_beneficiary_terminated,
    err_grantor_status_incompatible,
    err_has_approved_distributions,
    err_has_pending_distributions,
    err_has_undistributed_assets,
    err_insufficient_income,
    err_insufficient_income_for_tax,
    err_insufficient_principal,
    err_invalid_state,
    err_irrevocable_cannot_revoke,
    err_k1_stale_reference,
    err_newer_year_closed,
    err_no_beneficiary,
    err_no_open_tax_year,
    err_no_primary_trustee,
    err_nonzero_balance,
    err_segregation,
    err_tax_year_closed,
    err_tax_year_closing_in_progress,
    err_tax_year_not_closed,
    err_tax_year_not_ended,
    err_tax_year_not_open,
    err_trust_not_active,
)
from services.calculations import (
    compute_dni,
    compute_gst_classification,
    compute_gst_tax_amount,
    compute_k1_shares,
    compute_trust_income_tax,
    compute_trust_taxable_income,
    determine_is_skip_person,
)
from utils import money, new_uuid, to_decimal


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Mutation helpers — touch updated_at + version on every successful change ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def _now() -> datetime:
    return store.now()


def _touch(entity: dict) -> None:
    """Bump version and updated_at (PRD §2.4 / §2.9 cascade semantics)."""
    entity["updated_at"] = _now()
    entity["version"] = int(entity.get("version", 0)) + 1


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Trust CRUD + activation/revocation/termination                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def validate_grantor_status_combination(trust_type: str, grantor_tax_status: str, has_grantor_powers: bool):
    """Scaffold §1.4 priority 14 / PRD §3.1: GRANTOR forbidden when
    IRREVOCABLE AND has_grantor_powers=false.
    """
    if (
        grantor_tax_status == "GRANTOR"
        and trust_type == "IRREVOCABLE"
        and not has_grantor_powers
    ):
        raise err_grantor_status_incompatible()


def create_trust(
    *,
    name: str,
    trust_type: str,
    grantor_tax_status: str,
    has_grantor_powers: bool,
    situs_state: str,
    inception_date: datetime,
    grantor_user_id: str,
) -> dict:
    validate_grantor_status_combination(trust_type, grantor_tax_status, has_grantor_powers)
    now = _now()
    tid = new_uuid()
    trust = {
        "id": tid,
        "name": name,
        "trust_type": trust_type,
        "grantor_tax_status": grantor_tax_status,
        "has_grantor_powers": has_grantor_powers,
        "grantor_user_id": grantor_user_id,
        "situs_state": situs_state,
        "inception_date": inception_date,
        "status": "DRAFT",
        "principal_balance": Decimal("0.00"),
        "income_balance": Decimal("0.00"),
        "gst_exemption_used": Decimal("0.00"),
        "current_tax_year_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.trusts[tid] = trust
    return trust


def patch_trust(trust: dict, body: dict) -> dict:
    """Update mutable fields. trust_type / grantor_tax_status / has_grantor_powers
    are only mutable while DRAFT; situs_state and name are mutable any time.
    Optimistic concurrency on `version` happens at the caller layer.
    """
    # Capture intended new combination for the compatibility check.
    new_trust_type = trust["trust_type"]
    new_status_field = trust["grantor_tax_status"]
    new_powers = trust["has_grantor_powers"]

    if "trust_type" in body and body["trust_type"] is not None:
        if trust["status"] != "DRAFT":
            raise err_irrevocable_cannot_revoke("trust_type immutable after ACTIVE.")
        new_trust_type = body["trust_type"]
        trust["trust_type"] = new_trust_type
    if "grantor_tax_status" in body and body["grantor_tax_status"] is not None:
        if trust["status"] != "DRAFT":
            raise err_irrevocable_cannot_revoke("grantor_tax_status immutable after ACTIVE.")
        new_status_field = body["grantor_tax_status"]
        trust["grantor_tax_status"] = new_status_field
    if "has_grantor_powers" in body and body["has_grantor_powers"] is not None:
        if trust["status"] != "DRAFT":
            raise err_irrevocable_cannot_revoke("has_grantor_powers immutable after ACTIVE.")
        new_powers = bool(body["has_grantor_powers"])
        trust["has_grantor_powers"] = new_powers
    if "name" in body and body["name"] is not None:
        trust["name"] = body["name"]
    if "situs_state" in body and body["situs_state"] is not None:
        trust["situs_state"] = body["situs_state"]

    validate_grantor_status_combination(new_trust_type, new_status_field, new_powers)
    _touch(trust)
    return trust


def activate_trust(trust: dict) -> dict:
    if trust["status"] != "DRAFT":
        raise err_invalid_state("Trust not in DRAFT.")
    # Activation preconditions in scaffold-pinned order.
    primary_trustees = [
        t for t in store.trustees.values()
        if t["trust_id"] == trust["id"] and t["status"] == "ACTIVE" and t["is_primary"]
    ]
    if len(primary_trustees) != 1:
        raise err_no_primary_trustee()
    active_benes = [
        b for b in store.beneficiaries.values()
        if b["trust_id"] == trust["id"] and b["status"] == "ACTIVE"
    ]
    if len(active_benes) < 1:
        raise err_no_beneficiary()
    inception_year = trust["inception_date"].year
    matching_ty = next(
        (
            ty for ty in store.tax_years.values()
            if ty["trust_id"] == trust["id"]
            and ty["calendar_year"] == inception_year
            and ty["status"] == "OPEN"
        ),
        None,
    )
    if matching_ty is None:
        raise err_no_open_tax_year()

    # Transition + recompute balances from Assets.
    trust["status"] = "ACTIVE"
    _recompute_trust_balances(trust)
    _touch(trust)
    return trust


def revoke_trust(trust: dict) -> dict:
    if trust["status"] != "ACTIVE":
        raise err_invalid_state("Trust must be ACTIVE to revoke.")
    if trust["trust_type"] != "REVOCABLE":
        raise err_irrevocable_cannot_revoke()
    # No APPROVED distributions.
    has_approved = any(
        d for d in store.distributions.values()
        if d["trust_id"] == trust["id"] and d["status"] == "APPROVED"
    )
    if has_approved:
        raise err_has_approved_distributions()
    # No TaxYear in CLOSING.
    closing_ty = any(
        ty for ty in store.tax_years.values()
        if ty["trust_id"] == trust["id"] and ty["status"] == "CLOSING"
    )
    if closing_ty:
        raise err_tax_year_closing_in_progress()

    trust["status"] = "REVOKED"
    # Cascade: all ACTIVE beneficiaries → TERMINATED; all FUNDED assets → DISTRIBUTED.
    for b in list(store.beneficiaries.values()):
        if b["trust_id"] == trust["id"] and b["status"] == "ACTIVE":
            b["status"] = "TERMINATED"
            _touch(b)
    for a in list(store.assets.values()):
        if a["trust_id"] == trust["id"] and a["status"] == "FUNDED":
            a["status"] = "DISTRIBUTED"
            _touch(a)
    # Final true-up: principal and income balances zeroed (returned to grantor).
    trust["principal_balance"] = Decimal("0.00")
    trust["income_balance"] = Decimal("0.00")
    _touch(trust)
    return trust


def terminate_trust(trust: dict) -> dict:
    if trust["status"] != "ACTIVE":
        raise err_invalid_state("Trust must be ACTIVE to terminate.")
    # No undistributed assets.
    has_funded = any(
        a for a in store.assets.values()
        if a["trust_id"] == trust["id"] and a["status"] == "FUNDED"
    )
    if has_funded:
        raise err_has_undistributed_assets()
    # Zero balances.
    if to_decimal(trust["principal_balance"]) != 0 or to_decimal(trust["income_balance"]) != 0:
        raise err_nonzero_balance()
    # current_tax_year_id must be CLOSED or AMENDED.
    cur_ty_id = trust.get("current_tax_year_id")
    cur_ty = store.tax_years.get(cur_ty_id) if cur_ty_id else None
    if cur_ty is None or cur_ty["status"] not in ("CLOSED", "AMENDED"):
        raise err_tax_year_not_closed()

    trust["status"] = "TERMINATED"
    for b in list(store.beneficiaries.values()):
        if b["trust_id"] == trust["id"] and b["status"] == "ACTIVE":
            b["status"] = "TERMINATED"
            _touch(b)
    _touch(trust)
    return trust


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Trustee, Beneficiary, Asset                                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def add_trustee(trust: dict, *, user_id: str, full_name: str, is_primary: bool) -> dict:
    now = _now()
    tid = new_uuid()
    trustee = {
        "id": tid,
        "trust_id": trust["id"],
        "user_id": user_id,
        "full_name": full_name,
        "is_primary": bool(is_primary),
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.trustees[tid] = trustee
    # Cascade: if is_primary=true and another ACTIVE primary exists, demote it.
    if is_primary:
        for other in store.trustees.values():
            if (
                other["id"] != tid
                and other["trust_id"] == trust["id"]
                and other["status"] == "ACTIVE"
                and other["is_primary"]
            ):
                other["is_primary"] = False
                _touch(other)
    _touch(trust)  # cascade depth-2 on trust
    return trustee


def add_beneficiary(
    trust: dict,
    *,
    full_name: str,
    relation_class: str,
    beneficiary_class: str,
    distribution_tier: str,
    birth_date: datetime,
) -> dict:
    now = _now()
    bid = new_uuid()
    b = {
        "id": bid,
        "trust_id": trust["id"],
        "full_name": full_name,
        "relation_class": relation_class,
        "is_skip_person": False,  # filled below
        "beneficiary_class": beneficiary_class,
        "distribution_tier": distribution_tier,
        "status": "ACTIVE",
        "birth_date": birth_date,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    b["is_skip_person"] = determine_is_skip_person(b, trust)
    store.beneficiaries[bid] = b
    _touch(trust)
    return b


def terminate_beneficiary(trust: dict, beneficiary: dict) -> dict:
    if beneficiary["status"] != "ACTIVE":
        raise err_invalid_state("Beneficiary not ACTIVE.")
    if trust["status"] != "ACTIVE":
        raise err_trust_not_active()
    # No PROPOSED/APPROVED distributions referencing this beneficiary.
    pending = any(
        d for d in store.distributions.values()
        if d["beneficiary_id"] == beneficiary["id"]
        and d["status"] in ("PROPOSED", "APPROVED")
    )
    if pending:
        raise err_has_pending_distributions()
    beneficiary["status"] = "TERMINATED"
    _touch(beneficiary)
    return beneficiary


def add_asset(
    trust: dict,
    *,
    description: str,
    asset_class: str,
    book_value,
    classification: str,
) -> dict:
    now = _now()
    aid = new_uuid()
    asset = {
        "id": aid,
        "trust_id": trust["id"],
        "description": description,
        "asset_class": asset_class,
        "book_value": money(book_value),
        "classification": classification,
        "status": "FUNDED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.assets[aid] = asset
    # Cascade: bump the trust balance directly. Activation also recomputes
    # from assets, but for ACTIVE trusts a new asset adds to the appropriate
    # bucket immediately.
    _recompute_trust_balances(trust)
    _touch(trust)
    return asset


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Tax Year lifecycle                                                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def open_tax_year(trust: dict, *, calendar_year: int) -> dict:
    """Idempotent on (trust_id, calendar_year): return existing if present."""
    # Idempotency check.
    existing = next(
        (
            ty for ty in store.tax_years.values()
            if ty["trust_id"] == trust["id"] and ty["calendar_year"] == calendar_year
        ),
        None,
    )
    if existing is not None:
        return existing

    start = datetime(calendar_year, 1, 1, tzinfo=timezone.utc)
    # End of year: Dec 31 23:59:59.999999 — but for date-window comparisons
    # we treat the year as inclusive of Dec 31 (and exclusive of next Jan 1).
    end = datetime(calendar_year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    now = _now()
    tid = new_uuid()
    ty = {
        "id": tid,
        "trust_id": trust["id"],
        "calendar_year": calendar_year,
        "start_date": start,
        "end_date": end,
        "status": "OPEN",
        "dni": Decimal("0.00"),
        "trust_taxable_income": Decimal("0.00"),
        "trust_income_tax": Decimal("0.00"),
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.tax_years[tid] = ty
    # If this is the trust's first tax year, point current_tax_year_id at it.
    if trust.get("current_tax_year_id") is None:
        trust["current_tax_year_id"] = tid
        _touch(trust)
    return ty


def find_tax_year_for_date(trust_id: str, dt: datetime, allow_closing: bool = False):
    """Return the TaxYear whose calendar year contains dt, scoped to trust_id."""
    year = dt.year
    ty = next(
        (
            t for t in store.tax_years.values()
            if t["trust_id"] == trust_id and t["calendar_year"] == year
        ),
        None,
    )
    if ty is None:
        return None
    if allow_closing:
        if ty["status"] in ("OPEN", "CLOSING"):
            return ty
    else:
        if ty["status"] == "OPEN":
            return ty
    return None


def begin_close_tax_year(trust: dict, ty: dict) -> dict:
    if ty["status"] != "OPEN":
        raise err_invalid_state("TaxYear not OPEN.")
    # Clock-based: end_date must be reached.
    now = store.now()
    if now < ty["end_date"]:
        raise err_tax_year_not_ended()
    # No APPROVED distributions in this tax_year_id.
    has_approved = any(
        d for d in store.distributions.values()
        if d["tax_year_id"] == ty["id"] and d["status"] == "APPROVED"
    )
    if has_approved:
        raise err_has_approved_distributions()
    # Transition.
    ty["status"] = "CLOSING"
    # Side effect: auto-reject any PROPOSED distributions.
    for d in list(store.distributions.values()):
        if d["tax_year_id"] == ty["id"] and d["status"] == "PROPOSED":
            d["status"] = "REJECTED"
            _touch(d)
    # Recompute DNI + refresh DRAFT K-1s.
    _refresh_tax_year_dni(trust, ty)
    _refresh_draft_k1s(trust, ty)
    _touch(ty)
    return ty


def finalize_tax_year(trust: dict, ty: dict) -> dict:
    if ty["status"] not in ("CLOSING", "AMENDED"):
        raise err_invalid_state("TaxYear not in CLOSING or AMENDED.")
    is_amendment = ty["status"] == "AMENDED"

    # Ensure DRAFT K-1 records exist for every ACTIVE-at-year-end Beneficiary.
    _ensure_draft_k1s_present(trust, ty)

    # Compute trust_taxable_income + trust_income_tax.
    executed_income_sum = sum(
        (
            to_decimal(d["amount_income"])
            for d in store.distributions.values()
            if d["status"] == "EXECUTED" and d["tax_year_id"] == ty["id"]
        ),
        Decimal("0"),
    )
    new_taxable = compute_trust_taxable_income(trust, ty["dni"], executed_income_sum)
    new_tax = compute_trust_income_tax(new_taxable)

    if is_amendment:
        # Verify version-pinning on every DRAFT K-1 before committing.
        for k in store.k1s.values():
            if k["tax_year_id"] == ty["id"] and k["status"] == "DRAFT":
                live_sum = _sum_distribution_versions_for_beneficiary(ty, k["beneficiary_id"])
                pinned = k.get("snapshot_distribution_version_sum")
                if pinned is not None and pinned != live_sum:
                    raise err_k1_stale_reference()
        # Delta-based tax adjustment.
        old_tax = to_decimal(ty["trust_income_tax"])
        delta = new_tax - old_tax
        new_income_balance = to_decimal(trust["income_balance"]) - delta
        if new_income_balance < 0:
            raise err_insufficient_income_for_tax()
        trust["income_balance"] = money(new_income_balance)
    else:
        # Standard finalize: debit income_balance by new_tax.
        if to_decimal(trust["income_balance"]) < new_tax:
            raise err_insufficient_income_for_tax()
        trust["income_balance"] = money(to_decimal(trust["income_balance"]) - new_tax)

    ty["trust_taxable_income"] = new_taxable
    ty["trust_income_tax"] = new_tax
    ty["status"] = "CLOSED"
    ty["closed_at"] = store.now()

    # Issue K-1s: DRAFT → ISSUED, pin snapshot_distribution_version_sum.
    issued_at = store.now()
    for k in store.k1s.values():
        if k["tax_year_id"] == ty["id"] and k["status"] == "DRAFT":
            k["status"] = "ISSUED"
            k["snapshot_distribution_version_sum"] = _sum_distribution_versions_for_beneficiary(
                ty, k["beneficiary_id"]
            )
            k["issued_at"] = issued_at
            _touch(k)

    # Advance Trust.current_tax_year_id to the next year's OPEN TaxYear if it exists.
    next_year = ty["calendar_year"] + 1
    next_ty = next(
        (
            t for t in store.tax_years.values()
            if t["trust_id"] == trust["id"] and t["calendar_year"] == next_year
        ),
        None,
    )
    if next_ty is not None:
        trust["current_tax_year_id"] = next_ty["id"]

    _touch(ty)
    _touch(trust)
    return ty


def amend_tax_year(trust: dict, ty: dict) -> dict:
    if ty["status"] != "CLOSED":
        raise err_invalid_state("TaxYear must be CLOSED to amend.")
    # No newer year already CLOSED.
    has_newer_closed = any(
        t for t in store.tax_years.values()
        if t["trust_id"] == trust["id"]
        and t["calendar_year"] > ty["calendar_year"]
        and t["status"] == "CLOSED"
    )
    if has_newer_closed:
        raise err_newer_year_closed()
    # Existing ISSUED K-1s → SUPERSEDED.
    for k in list(store.k1s.values()):
        if k["tax_year_id"] == ty["id"] and k["status"] == "ISSUED":
            k["status"] = "SUPERSEDED"
            _touch(k)
    ty["status"] = "AMENDED"
    # Refresh draft K-1s (create fresh DRAFT for each ACTIVE-at-year-end beneficiary).
    _refresh_tax_year_dni(trust, ty)
    _refresh_draft_k1s(trust, ty, recreate=True)
    _touch(ty)
    return ty


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Transaction                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def create_transaction(
    trust: dict,
    *,
    txn_type: str,
    amount,
    transaction_date: datetime,
    principal_or_income: str,
    description: str,
) -> dict:
    # Find a TaxYear in OPEN or CLOSING that contains transaction_date.
    ty = find_tax_year_for_date(trust["id"], transaction_date, allow_closing=True)
    if ty is None:
        raise err_tax_year_closed()

    now = _now()
    txid = new_uuid()
    tx = {
        "id": txid,
        "trust_id": trust["id"],
        "tax_year_id": ty["id"],
        "txn_type": txn_type,
        "amount": money(amount),
        "transaction_date": transaction_date,
        "principal_or_income": principal_or_income,
        "description": description,
        "created_at": now,
    }
    store.transactions[txid] = tx

    # Recompute balances and, if the TaxYear is CLOSING, refresh DNI + K-1s.
    _recompute_trust_balances(trust)
    _touch(trust)
    if ty["status"] == "CLOSING":
        _refresh_tax_year_dni(trust, ty)
        _refresh_draft_k1s(trust, ty)
        _touch(ty)
    return tx


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Distribution lifecycle                                                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def propose_distribution(
    trust: dict,
    *,
    beneficiary_id: str,
    scheduled_date: datetime,
    amount_principal,
    amount_income,
    distribution_type: str,
    proposed_by_user_id: str,
) -> dict:
    # scheduled_date must fall inside an OPEN TaxYear (priority 10).
    ty = find_tax_year_for_date(trust["id"], scheduled_date, allow_closing=False)
    if ty is None:
        raise err_tax_year_closed()

    bene = store.beneficiaries.get(beneficiary_id)
    # (Existence already validated at the route layer.)

    now = _now()
    did = new_uuid()
    # Preview GST classification (informational on PROPOSED).
    preview_d = {
        "amount_principal": money(amount_principal),
        "amount_income": money(amount_income),
    }
    gst_taxable, _exempt_applied, _taxable_portion = compute_gst_classification(
        trust, preview_d, bene
    )
    gst_tax_amount = Decimal("0.00")

    d = {
        "id": did,
        "trust_id": trust["id"],
        "beneficiary_id": beneficiary_id,
        "tax_year_id": ty["id"],
        "scheduled_date": scheduled_date,
        "amount_principal": money(amount_principal),
        "amount_income": money(amount_income),
        "distribution_type": distribution_type,
        "status": "PROPOSED",
        "proposed_by_user_id": proposed_by_user_id,
        "approved_by_user_id": None,
        "gst_taxable": gst_taxable,
        "gst_tax_amount": gst_tax_amount,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.distributions[did] = d
    return d


def approve_distribution(trust: dict, d: dict, approver_user_id: str) -> dict:
    if d["status"] != "PROPOSED":
        raise err_invalid_state("Distribution not in PROPOSED.")
    if trust["status"] != "ACTIVE":
        raise err_trust_not_active()
    bene = store.beneficiaries.get(d["beneficiary_id"])
    if bene is None or bene["status"] != "ACTIVE":
        raise err_beneficiary_terminated()
    ty = store.tax_years.get(d["tax_year_id"])
    if ty is None or ty["status"] != "OPEN":
        raise err_tax_year_not_open()
    # Segregation: approver != proposer.
    if approver_user_id == d["proposed_by_user_id"]:
        raise err_segregation("Approver must differ from proposer.")
    # Fiscal sufficiency at approve-time.
    if to_decimal(d["amount_principal"]) > to_decimal(trust["principal_balance"]):
        raise err_insufficient_principal()
    if to_decimal(d["amount_income"]) > to_decimal(trust["income_balance"]):
        raise err_insufficient_income()

    # Pin gst_taxable + gst_tax_amount.
    gst_taxable, _ea, taxable_portion = compute_gst_classification(trust, d, bene)
    d["gst_taxable"] = gst_taxable
    d["gst_tax_amount"] = compute_gst_tax_amount(taxable_portion) if gst_taxable else Decimal("0.00")
    d["status"] = "APPROVED"
    d["approved_by_user_id"] = approver_user_id
    _touch(d)
    return d


def execute_distribution(trust: dict, d: dict) -> dict:
    if d["status"] != "APPROVED":
        raise err_invalid_state("Distribution not in APPROVED.")
    bene = store.beneficiaries.get(d["beneficiary_id"])
    if bene is None or bene["status"] != "ACTIVE":
        raise err_beneficiary_terminated()
    # Re-check fiscal sufficiency (balances may have moved).
    if to_decimal(d["amount_principal"]) > to_decimal(trust["principal_balance"]):
        raise err_insufficient_principal()
    if to_decimal(d["amount_income"]) > to_decimal(trust["income_balance"]):
        raise err_insufficient_income()

    # Compute exemption_applied + final tax via the pinned order.
    gst_taxable, exemption_applied, taxable_portion = compute_gst_classification(
        trust, d, bene
    )
    if gst_taxable:
        gst_tax = compute_gst_tax_amount(taxable_portion)
    else:
        gst_tax = Decimal("0.00")
    # Apply state + side effects atomically.
    d["status"] = "EXECUTED"
    d["gst_taxable"] = gst_taxable
    d["gst_tax_amount"] = gst_tax
    # Trust mutations.
    trust["principal_balance"] = money(
        to_decimal(trust["principal_balance"]) - to_decimal(d["amount_principal"])
    )
    trust["income_balance"] = money(
        to_decimal(trust["income_balance"]) - to_decimal(d["amount_income"])
    )
    trust["gst_exemption_used"] = money(
        to_decimal(trust["gst_exemption_used"]) + exemption_applied
    )
    if gst_taxable:
        trust["income_balance"] = money(
            to_decimal(trust["income_balance"]) - gst_tax
        )
    _touch(trust)
    _touch(d)

    # Cascade: refresh the DRAFT K-1 for this beneficiary in this TaxYear,
    # and refresh the year's DNI accrual.
    ty = store.tax_years.get(d["tax_year_id"])
    if ty is not None:
        _refresh_tax_year_dni(trust, ty)
        _refresh_draft_k1s(trust, ty)
        _touch(ty)
    return d


def reject_distribution(trust: dict, d: dict, rejecter_user_id: str) -> dict:
    if d["status"] == "PROPOSED":
        # Trust must be ACTIVE or REVOKED.
        if trust["status"] not in ("ACTIVE", "REVOKED"):
            raise err_invalid_state("Trust must be ACTIVE or REVOKED for rejection.")
        d["status"] = "REJECTED"
        _touch(d)
        return d
    if d["status"] == "APPROVED":
        # Segregation: rejecter must differ from approver.
        if d.get("approved_by_user_id") == rejecter_user_id:
            raise err_segregation("Rejecter must differ from approver.")
        d["status"] = "REJECTED"
        _touch(d)
        return d
    raise err_invalid_state("Distribution not in PROPOSED or APPROVED.")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ Internal cascade helpers                                                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def _recompute_trust_balances(trust: dict) -> None:
    """Recompute principal_balance and income_balance from the source-of-truth
    aggregates (PRD §3.9). Called after asset/transaction/distribution/finalize.
    """
    principal = Decimal("0")
    income = Decimal("0")
    # Asset book values (FUNDED only).
    for a in store.assets.values():
        if a["trust_id"] != trust["id"]:
            continue
        if a["status"] != "FUNDED":
            continue
        if a["classification"] == "PRINCIPAL":
            principal += to_decimal(a["book_value"])
        elif a["classification"] == "INCOME":
            income += to_decimal(a["book_value"])
    # Transactions (income +, expense -).
    for tx in store.transactions.values():
        if tx["trust_id"] != trust["id"]:
            continue
        amt = to_decimal(tx["amount"])
        if tx["principal_or_income"] == "PRINCIPAL":
            if tx["txn_type"].startswith("INCOME_"):
                principal += amt
            else:
                principal -= amt
        else:  # INCOME
            if tx["txn_type"].startswith("INCOME_"):
                income += amt
            else:
                income -= amt
    # Executed Distributions.
    for d in store.distributions.values():
        if d["trust_id"] != trust["id"]:
            continue
        if d["status"] != "EXECUTED":
            continue
        principal -= to_decimal(d["amount_principal"])
        income -= to_decimal(d["amount_income"])
        if d["gst_taxable"]:
            income -= to_decimal(d["gst_tax_amount"])
    # CLOSED/AMENDED TaxYears' trust_income_tax (also debited at finalize).
    for ty in store.tax_years.values():
        if ty["trust_id"] != trust["id"]:
            continue
        if ty["status"] in ("CLOSED", "AMENDED"):
            income -= to_decimal(ty["trust_income_tax"])
    trust["principal_balance"] = money(principal)
    trust["income_balance"] = money(income)


def _transactions_in_tax_year(trust: dict, ty: dict):
    return [
        tx for tx in store.transactions.values()
        if tx["trust_id"] == trust["id"]
        and ty["start_date"] <= tx["transaction_date"] <= ty["end_date"]
    ]


def _refresh_tax_year_dni(trust: dict, ty: dict) -> None:
    """Recompute and pin ty['dni'] from the in-year transaction set."""
    if trust["status"] not in ("ACTIVE", "REVOKED", "TERMINATED"):
        return
    txns = _transactions_in_tax_year(trust, ty)
    dni, _buckets = compute_dni(txns)
    ty["dni"] = dni


def _refresh_draft_k1s(trust: dict, ty: dict, recreate: bool = False) -> None:
    """Recompute or create the DRAFT K-1 set for the TaxYear's shares.

    `recreate=True` deletes any existing DRAFT K-1s for this tax year first
    (used on AMEND, where a fresh DRAFT set must be created).
    """
    # Compute character buckets fresh for this refresh.
    txns = _transactions_in_tax_year(trust, ty)
    dni, buckets = compute_dni(txns)
    ty["dni"] = dni

    # Active-at-year-end beneficiaries.
    # We approximate "ACTIVE-at-year-end" as currently ACTIVE OR TERMINATED.
    benes = [
        b for b in store.beneficiaries.values()
        if b["trust_id"] == trust["id"]
    ]

    # Drop existing DRAFT K-1s if recreating.
    if recreate:
        to_delete = [
            k_id for k_id, k in store.k1s.items()
            if k["tax_year_id"] == ty["id"] and k["status"] == "DRAFT"
        ]
        for k_id in to_delete:
            del store.k1s[k_id]

    # Ensure each beneficiary has a DRAFT K-1 row.
    draft_by_bene = {
        k["beneficiary_id"]: k
        for k in store.k1s.values()
        if k["tax_year_id"] == ty["id"] and k["status"] == "DRAFT"
    }
    now = _now()
    for b in benes:
        if b["id"] not in draft_by_bene:
            kid = new_uuid()
            k = {
                "id": kid,
                "tax_year_id": ty["id"],
                "trust_id": trust["id"],
                "beneficiary_id": b["id"],
                "ordinary_income_share": Decimal("0.00"),
                "interest_income_share": Decimal("0.00"),
                "dividend_income_share": Decimal("0.00"),
                "capital_gain_share": Decimal("0.00"),
                "total_distributed": Decimal("0.00"),
                "status": "DRAFT",
                "snapshot_distribution_version_sum": None,
                "issued_at": None,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            store.k1s[kid] = k
            draft_by_bene[b["id"]] = k

    # Per-beneficiary aggregates for the waterfall.
    executed_by_bene = {}
    largest_dist_type = {}
    total_distributed_by_bene = {}
    for d in store.distributions.values():
        if d["tax_year_id"] != ty["id"] or d["status"] != "EXECUTED":
            continue
        bid = d["beneficiary_id"]
        executed_by_bene[bid] = executed_by_bene.get(bid, Decimal("0")) + to_decimal(d["amount_income"])
        total_distributed_by_bene[bid] = total_distributed_by_bene.get(bid, Decimal("0")) + (
            to_decimal(d["amount_principal"]) + to_decimal(d["amount_income"])
        )
        # Track which distribution is largest (by total) for the
        # capital-gain-share gating rule.
        cur = largest_dist_type.get(bid)
        total = to_decimal(d["amount_principal"]) + to_decimal(d["amount_income"])
        if cur is None or total > cur[1]:
            largest_dist_type[bid] = (d["distribution_type"], total)
    # Reduce largest_dist_type to {bid: distribution_type}.
    largest_dist_type = {bid: v[0] for bid, v in largest_dist_type.items()}

    bene_with_tier = [(b["id"], b["distribution_tier"]) for b in benes]
    shares = compute_k1_shares(
        dni, buckets, bene_with_tier, executed_by_bene, largest_dist_type
    )
    for b in benes:
        k = draft_by_bene[b["id"]]
        s = shares.get(b["id"], {})
        k["ordinary_income_share"] = s.get("ordinary_income_share", Decimal("0.00"))
        k["interest_income_share"] = s.get("interest_income_share", Decimal("0.00"))
        k["dividend_income_share"] = s.get("dividend_income_share", Decimal("0.00"))
        k["capital_gain_share"] = s.get("capital_gain_share", Decimal("0.00"))
        k["total_distributed"] = money(total_distributed_by_bene.get(b["id"], Decimal("0")))
        _touch(k)


def _ensure_draft_k1s_present(trust: dict, ty: dict) -> None:
    """Make sure each ACTIVE-at-year-end beneficiary has a DRAFT K-1 row.

    Called at finalize time so begin-close → finalize without intermediate
    transactions still emits one K-1 per beneficiary.
    """
    _refresh_draft_k1s(trust, ty)


def _sum_distribution_versions_for_beneficiary(ty: dict, beneficiary_id: str) -> int:
    """Sum of Distribution.version across EXECUTED distributions to a
    beneficiary in this tax year. Used for K-1 snapshot pinning.
    """
    total = 0
    for d in store.distributions.values():
        if (
            d["tax_year_id"] == ty["id"]
            and d["beneficiary_id"] == beneficiary_id
            and d["status"] == "EXECUTED"
        ):
            total += int(d.get("version", 0))
    return total
