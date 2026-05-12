"""State transition orchestration: evidence anchoring, batch confirmations,
expiry sweeps, certificate cascades."""
import secrets
import string
from decimal import Decimal

from flask import g

import db
from clock import iso, now, parse_iso, add_seconds
from errors import err
from services import audit
from services.calculations import (
    CHAIN_CONFIRMATION_THRESHOLD,
    batch_fee_final,
    preservation_fee_final,
)
from services.lookup import (
    batch_members,
    certificate_for_evidence,
    latest_on_chain_tx_for_batch,
    latest_on_chain_tx_for_evidence,
    notarization_for_evidence,
)


_ALPHANUM_UPPER = string.ascii_uppercase + string.digits


def _new_tx_hash() -> str:
    return "0x" + "".join(secrets.choice("0123456789abcdef") for _ in range(64))


def _new_seal_id() -> str:
    return "SEAL_" + "".join(secrets.choice(_ALPHANUM_UPPER) for _ in range(16))


def new_verification_code() -> str:
    return "".join(secrets.choice(_ALPHANUM_UPPER) for _ in range(12))


def create_on_chain_tx(*, evidence_id=None, batch_id=None, chain_id: str,
                      anchored_hash: str, attempt_index: int) -> dict:
    tx = {
        "evidence_id": evidence_id,
        "batch_id": batch_id,
        "chain_id": chain_id,
        "anchored_hash": anchored_hash,
        "tx_hash": _new_tx_hash(),
        "block_height": None,
        "confirmations": 0,
        "status": "SUBMITTED",
        "attempt_index": attempt_index,
    }
    db.stamp_create(tx, common_fields=True)
    db.on_chain_txs[tx["id"]] = tx
    return tx


def _bump_customer(customer: dict) -> None:
    db.stamp_update(customer)


def _bump_fee_account(fa: dict) -> None:
    # FeeAccount has only id + created_at per PRD §2.4 — no version / updated_at.
    pass


# ------------------- Evidence: PENDING -> SUBMITTING -------------------

def evidence_submit(evidence: dict) -> None:
    """Implements PENDING -> SUBMITTING for a single evidence."""
    customer = db.customers[evidence["customer_id"]]

    if customer.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Customer is not ACTIVE")
    if evidence["status"] != "PENDING":
        raise err("ERR_INVALID_STATE",
                  f"Evidence is in {evidence['status']}, expected PENDING")
    if evidence.get("batch_id") is not None:
        raise err("ERR_INVALID_STATE",
                  "Evidence belongs to a batch; use batch submit")

    # Forward-looking quote
    from services.calculations import preservation_fee_quote
    quote = preservation_fee_quote(evidence)
    if customer.get("wallet_balance_cents", 0) < quote:
        raise err("ERR_INSUFFICIENT_BALANCE",
                  "Wallet balance insufficient for preservation fee quote")

    # Cascade
    evidence["status"] = "SUBMITTING"
    evidence["submission_attempts"] = evidence.get("submission_attempts", 0) + 1
    db.stamp_update(evidence)

    tx = create_on_chain_tx(
        evidence_id=evidence["id"],
        batch_id=None,
        chain_id=evidence["chain_id"],
        anchored_hash=evidence["file_hash"],
        attempt_index=evidence["submission_attempts"],
    )

    audit.append(
        event_type="EVIDENCE_SUBMITTED",
        target_entity="Evidence",
        target_id=evidence["id"],
        detail={"tx_id": tx["id"], "attempt_index": tx["attempt_index"]},
    )


# ------------------- Evidence: FAILED -> SUBMITTING -------------------

def evidence_resubmit(evidence: dict) -> None:
    customer = db.customers[evidence["customer_id"]]

    if evidence["status"] != "FAILED":
        raise err("ERR_INVALID_STATE",
                  f"Evidence is in {evidence['status']}, expected FAILED")
    if evidence.get("submission_attempts", 0) >= 3:
        raise err("ERR_RESUBMIT_LIMIT_EXCEEDED",
                  "Resubmission attempts may not exceed 3")

    from services.calculations import preservation_fee_quote
    quote = preservation_fee_quote(evidence)
    if customer.get("wallet_balance_cents", 0) < quote:
        raise err("ERR_INSUFFICIENT_BALANCE",
                  "Wallet balance insufficient for preservation fee quote")

    evidence["status"] = "SUBMITTING"
    evidence["submission_attempts"] = evidence.get("submission_attempts", 0) + 1
    db.stamp_update(evidence)

    tx = create_on_chain_tx(
        evidence_id=evidence["id"],
        batch_id=None,
        chain_id=evidence["chain_id"],
        anchored_hash=evidence["file_hash"],
        attempt_index=evidence["submission_attempts"],
    )

    audit.append(
        event_type="EVIDENCE_RESUBMITTED",
        target_entity="Evidence",
        target_id=evidence["id"],
        detail={"tx_id": tx["id"], "attempt_index": tx["attempt_index"]},
    )


# ------------------- Evidence: SUBMITTING -> CONFIRMED -------------------

def _confirm_single_evidence(evidence: dict) -> None:
    """Cascade from a CONFIRMED single-evidence OnChainTx."""
    if evidence["status"] != "SUBMITTING":
        return  # nothing to do
    if notarization_for_evidence(evidence["id"]) is None:
        raise err("ERR_TIMESTAMP_REQUIRED",
                  "Evidence has no TimestampNotarization at chain confirmation")

    customer = db.customers[evidence["customer_id"]]
    fee = preservation_fee_final(evidence)

    # Balance is checked at submit; PRD says the would-be result must not drive
    # the wallet below zero. Re-check to honor concurrency rule.
    if customer.get("wallet_balance_cents", 0) < fee:
        raise err("ERR_INSUFFICIENT_BALANCE",
                  "Wallet balance insufficient to debit preservation fee")

    confirmed_at = now()
    evidence["status"] = "CONFIRMED"
    evidence["confirmed_at"] = iso(confirmed_at)
    evidence["expires_at"] = iso(
        add_seconds(confirmed_at, evidence["storage_period_days"] * 86400)
    )
    evidence["per_evidence_fee_cents"] = fee
    db.stamp_update(evidence)

    customer["wallet_balance_cents"] -= fee
    _bump_customer(customer)

    fa = db.fee_accounts[customer["id"]]
    fa["lifetime_deduction_cents"] += fee
    _bump_fee_account(fa)

    audit.append(
        event_type="EVIDENCE_CONFIRMED",
        target_entity="Evidence",
        target_id=evidence["id"],
        detail={"fee_cents": fee, "confirmed_at": evidence["confirmed_at"]},
        actor_role="system", actor_id=None,
    )
    audit.append(
        event_type="FEE_DEBITED",
        target_entity="Evidence",
        target_id=evidence["id"],
        detail={"amount_cents": fee, "wallet_balance_cents": customer["wallet_balance_cents"]},
        actor_role="system", actor_id=None,
    )


def _fail_single_evidence(evidence: dict) -> None:
    if evidence["status"] != "SUBMITTING":
        return
    evidence["status"] = "FAILED"
    db.stamp_update(evidence)
    audit.append(
        event_type="EVIDENCE_FAILED",
        target_entity="Evidence",
        target_id=evidence["id"],
        detail={},
        actor_role="system", actor_id=None,
    )


# ------------------- Batch: PENDING -> SUBMITTING -------------------

def batch_submit(batch: dict) -> None:
    customer = db.customers[batch["customer_id"]]
    if customer.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Customer is not ACTIVE")
    if batch["status"] != "PENDING":
        raise err("ERR_INVALID_STATE",
                  f"Batch is in {batch['status']}, expected PENDING")

    members = batch_members(batch["id"])
    if len(members) != batch["evidence_count"]:
        raise err("ERR_INVALID_STATE", "Batch member set has changed")
    for m in members:
        if m["status"] != "PENDING" or m.get("batch_id") != batch["id"]:
            raise err("ERR_INVALID_STATE",
                      f"Member evidence {m['id']} is not PENDING in this batch")

    quote = batch_fee_final(members)
    if customer.get("wallet_balance_cents", 0) < quote:
        raise err("ERR_INSUFFICIENT_BALANCE",
                  "Wallet balance insufficient for batch fee quote")

    # Recompute Merkle root over members in submission order (matches creation).
    from services.merkle import merkle_root
    leaves = [m["file_hash"] for m in members]
    batch["merkle_root"] = merkle_root(leaves)
    batch["status"] = "SUBMITTING"
    batch["submission_attempts"] = batch.get("submission_attempts", 0) + 1
    db.stamp_update(batch)

    for m in members:
        m["status"] = "SUBMITTING"
        db.stamp_update(m)

    tx = create_on_chain_tx(
        evidence_id=None,
        batch_id=batch["id"],
        chain_id=batch["chain_id"],
        anchored_hash=batch["merkle_root"],
        attempt_index=batch["submission_attempts"],
    )

    # PRD §2.9: cascade audit entries are appended for the cascaded
    # events as well as the primary one. PRD §2.12 enumerates
    # `OnChainTx` as a valid target_entity for audit rows. The
    # OnChainTx creation here is the cascaded side-effect of the
    # primary batch state transition, so we record it under the
    # nearest matching event_type from the §2.12 enumeration:
    # EVIDENCE_SUBMITTED (the "submission" event family). The detail
    # snapshot carries batch_id so PRD-style audit consumers can
    # correlate the chain tx back to its parent batch.
    audit.append(
        event_type="EVIDENCE_SUBMITTED",
        target_entity="OnChainTx",
        target_id=tx["id"],
        detail={
            "batch_id": batch["id"],
            "attempt_index": tx["attempt_index"],
            "anchored_hash": tx["anchored_hash"],
        },
    )


# ------------------- Batch: SUBMITTING -> CONFIRMED -------------------

def _confirm_batch(batch: dict) -> None:
    if batch["status"] != "SUBMITTING":
        return
    members = batch_members(batch["id"])
    for m in members:
        if notarization_for_evidence(m["id"]) is None:
            raise err("ERR_TIMESTAMP_REQUIRED",
                      f"Member evidence {m['id']} has no TimestampNotarization")

    customer = db.customers[batch["customer_id"]]
    fee = batch_fee_final(members)

    if customer.get("wallet_balance_cents", 0) < fee:
        raise err("ERR_INSUFFICIENT_BALANCE",
                  "Wallet balance insufficient to debit batch fee")

    confirmed_at = now()
    confirmed_iso = iso(confirmed_at)

    for m in members:
        m["status"] = "CONFIRMED"
        m["confirmed_at"] = confirmed_iso
        m["expires_at"] = iso(
            add_seconds(confirmed_at, m["storage_period_days"] * 86400)
        )
        # per-member fee column stays null (this is the batch path)
        db.stamp_update(m)

    batch["status"] = "CONFIRMED"
    batch["total_fee_cents"] = fee
    db.stamp_update(batch)
    batch["_confirmed_at"] = batch["updated_at"]

    customer["wallet_balance_cents"] -= fee
    _bump_customer(customer)
    fa = db.fee_accounts[customer["id"]]
    fa["lifetime_deduction_cents"] += fee

    audit.append(
        event_type="BATCH_CONFIRMED",
        target_entity="Batch",
        target_id=batch["id"],
        detail={"fee_cents": fee, "members": len(members)},
        actor_role="system", actor_id=None,
    )
    audit.append(
        event_type="FEE_DEBITED",
        target_entity="Batch",
        target_id=batch["id"],
        detail={"amount_cents": fee, "wallet_balance_cents": customer["wallet_balance_cents"]},
        actor_role="system", actor_id=None,
    )


def _fail_batch(batch: dict) -> None:
    if batch["status"] != "SUBMITTING":
        return
    members = batch_members(batch["id"])
    for m in members:
        m["status"] = "FAILED"
        db.stamp_update(m)
    batch["status"] = "FAILED"
    db.stamp_update(batch)


# ------------------- OnChainTx confirmation / failure -------------------

def chain_confirm(tx: dict, block_height: int, confirmations: int) -> None:
    threshold = CHAIN_CONFIRMATION_THRESHOLD[tx["chain_id"]]
    # Update height/confirmations regardless; flip status only at threshold
    tx["block_height"] = block_height
    tx["confirmations"] = confirmations

    if confirmations < threshold:
        # Stays in SUBMITTED; no cascade
        db.stamp_update(tx)
        return

    if tx["status"] in {"CONFIRMED", "FAILED"}:
        # Terminal already
        db.stamp_update(tx)
        return

    tx["status"] = "CONFIRMED"
    db.stamp_update(tx)

    # Cascade upstream
    if tx.get("evidence_id"):
        ev = db.evidences[tx["evidence_id"]]
        # Validate this is the latest attempt
        latest = latest_on_chain_tx_for_evidence(ev["id"])
        if latest and latest["id"] == tx["id"]:
            _confirm_single_evidence(ev)
    elif tx.get("batch_id"):
        b = db.batches[tx["batch_id"]]
        latest = latest_on_chain_tx_for_batch(b["id"])
        if latest and latest["id"] == tx["id"]:
            _confirm_batch(b)


def chain_fail(tx: dict, reason: str) -> None:
    if tx["status"] in {"CONFIRMED", "FAILED"}:
        return
    tx["status"] = "FAILED"
    db.stamp_update(tx)
    if tx.get("evidence_id"):
        ev = db.evidences[tx["evidence_id"]]
        latest = latest_on_chain_tx_for_evidence(ev["id"])
        if latest and latest["id"] == tx["id"]:
            _fail_single_evidence(ev)
    elif tx.get("batch_id"):
        b = db.batches[tx["batch_id"]]
        latest = latest_on_chain_tx_for_batch(b["id"])
        if latest and latest["id"] == tx["id"]:
            _fail_batch(b)


# ------------------- Expiry sweep -------------------

def expiry_sweep() -> dict:
    """Flip CONFIRMED -> EXPIRED for all eligible evidences."""
    current = now()
    swept = []
    cert_revoked = []
    pkg_rejected = []

    # snapshot list to avoid mutation while iterating
    candidates = [e for e in db.evidences.values()
                  if e["status"] == "CONFIRMED" and e.get("expires_at")]

    for ev in candidates:
        try:
            exp_dt = parse_iso(ev["expires_at"])
        except Exception:
            continue
        if exp_dt > current:
            continue
        ev["status"] = "EXPIRED"
        db.stamp_update(ev)
        swept.append(ev["id"])

        # Cascade Certificate -> REVOKED (if ISSUED), but PRD §3.6:
        # "A Certificate whose linked evidence is referenced by a
        # SEALED but not-yet-DELIVERED JudicialPackage is
        # intentionally not auto-cascaded by sweeps — the judicial
        # channel is responsible for that decision."
        cert = certificate_for_evidence(ev["id"])
        has_sealed_pkg = any(
            pkg["evidence_id"] == ev["id"] and pkg["status"] == "SEALED"
            for pkg in db.judicial_packages.values()
        )
        if cert is not None and cert["status"] == "ISSUED" and not has_sealed_pkg:
            cert["status"] = "REVOKED"
            db.stamp_update(cert)
            cert_revoked.append(cert["id"])

        # Cascade DRAFT JudicialPackage -> REJECTED
        for pkg in list(db.judicial_packages.values()):
            if pkg["evidence_id"] == ev["id"] and pkg["status"] == "DRAFT":
                pkg["status"] = "REJECTED"
                db.stamp_update(pkg)
                pkg_rejected.append(pkg["id"])

    return {
        "swept_evidence_ids": swept,
        "revoked_certificate_ids": cert_revoked,
        "rejected_judicial_package_ids": pkg_rejected,
    }


# ------------------- Recharge: PENDING -> COMPLETED / FAILED -------------------

def recharge_complete(recharge: dict) -> None:
    if recharge["status"] != "PENDING":
        raise err("ERR_INVALID_STATE",
                  f"Recharge is in {recharge['status']}, expected PENDING")
    customer = db.customers[recharge["customer_id"]]
    recharge["status"] = "COMPLETED"
    db.stamp_update(recharge) if "version" in recharge else None
    customer["wallet_balance_cents"] += recharge["amount_cents"]
    _bump_customer(customer)
    fa = db.fee_accounts[customer["id"]]
    fa["lifetime_recharge_cents"] += recharge["amount_cents"]
    audit.append(
        event_type="RECHARGE_COMPLETED",
        target_entity="Recharge",
        target_id=recharge["id"],
        detail={"amount_cents": recharge["amount_cents"]},
        actor_role="system", actor_id=None,
    )


def recharge_fail(recharge: dict) -> None:
    if recharge["status"] != "PENDING":
        raise err("ERR_INVALID_STATE",
                  f"Recharge is in {recharge['status']}, expected PENDING")
    recharge["status"] = "FAILED"


# ------------------- Judicial seal / deliver -------------------

def judicial_seal(pkg: dict) -> None:
    if pkg["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE",
                  f"JudicialPackage is in {pkg['status']}, expected DRAFT")

    evidence = db.evidences[pkg["evidence_id"]]
    if evidence["status"] != "CONFIRMED":
        raise err("ERR_EVIDENCE_NOT_CONFIRMED",
                  "Linked Evidence is not in CONFIRMED state")

    cert = certificate_for_evidence(evidence["id"])
    if cert is None or cert["status"] != "ISSUED":
        raise err("ERR_CERTIFICATE_REQUIRED",
                  "Linked Certificate is missing or not ISSUED")

    if notarization_for_evidence(evidence["id"]) is None:
        raise err("ERR_TIMESTAMP_REQUIRED",
                  "Linked TimestampNotarization is required")

    customer = db.customers[evidence["customer_id"]]
    from services.calculations import judicial_surcharge_quote
    quote = judicial_surcharge_quote(pkg["include_original_data"], pkg["authority_code"])
    if customer.get("wallet_balance_cents", 0) < quote:
        raise err("ERR_INSUFFICIENT_BALANCE",
                  "Wallet balance insufficient for judicial surcharge")

    pkg["status"] = "SEALED"
    pkg["official_seal_id"] = _new_seal_id()
    pkg["surcharge_cents"] = quote
    db.stamp_update(pkg)
    # Stash the seal timestamp for later billing-period invoice lookups.
    pkg["_sealed_at"] = pkg["updated_at"]

    customer["wallet_balance_cents"] -= quote
    _bump_customer(customer)
    fa = db.fee_accounts[customer["id"]]
    fa["lifetime_deduction_cents"] += quote

    audit.append(
        event_type="JUDICIAL_SEALED",
        target_entity="JudicialPackage",
        target_id=pkg["id"],
        detail={"surcharge_cents": quote, "seal_id": pkg["official_seal_id"]},
    )
    audit.append(
        event_type="FEE_DEBITED",
        target_entity="JudicialPackage",
        target_id=pkg["id"],
        detail={"amount_cents": quote, "wallet_balance_cents": customer["wallet_balance_cents"]},
    )


def judicial_deliver(pkg: dict, *, system_actor: bool = False) -> None:
    if pkg["status"] != "SEALED":
        raise err("ERR_INVALID_STATE",
                  f"JudicialPackage is in {pkg['status']}, expected SEALED")
    pkg["status"] = "DELIVERED"
    pkg["delivered_at"] = iso(now())
    db.stamp_update(pkg)
    audit.append(
        event_type="JUDICIAL_DELIVERED",
        target_entity="JudicialPackage",
        target_id=pkg["id"],
        detail={"delivered_at": pkg["delivered_at"]},
        actor_role=("system" if system_actor else None),
        actor_id=(None if system_actor else None),
    )
