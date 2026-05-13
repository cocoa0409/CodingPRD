"""Dispute service: open, evidence, status transitions, resolve, withdraw."""

from db import store
from errors import raise_err
from middleware import current_role, current_user_id
from clock import clock
from util import get_str, get_enum
from services.work import recompute_dispute_posture

DISPUTE_KINDS = {"SHARE_RATIO", "OWNERSHIP", "ORIGINALITY", "AGENCY_AUTHORITY"}
OPEN_STATUSES = {"OPEN", "UNDER_INVESTIGATION", "MEDIATION", "ARBITRATION"}


def serialize(d: dict) -> dict:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "work_id": d["work_id"],
        "claimant_rights_holder_id": d["claimant_rights_holder_id"],
        "dispute_kind": d["dispute_kind"],
        "claim_summary": d["claim_summary"],
        "status": d["status"],
        "evidence_items": d.get("evidence_items", []),
        "arbitration_decision": d.get("arbitration_decision"),
        "arbitrator_id": d.get("arbitrator_id"),
    }


def _occ_check(d, body):
    if isinstance(body, dict) and body.get("version") is not None:
        if body["version"] != d["version"]:
            raise_err("ERR_VERSION_CONFLICT", "Version conflict")


def open_dispute(body: dict) -> dict:
    work_id = get_str(body, "work_id")
    dispute_kind = get_enum(body, "dispute_kind", DISPUTE_KINDS)
    claim_summary = get_str(body, "claim_summary", min_len=1, max_len=2000)
    with store.lock:
        w = store.works.get(work_id)
        if not w:
            raise_err("ERR_NOT_FOUND", "Work not found")
        claimant = current_user_id()
        # claimant must exist as a RightsHolder.
        if claimant not in store.rights_holders:
            raise_err("ERR_NOT_FOUND", "Claimant RightsHolder not found")
        row = store.common_fields()
        row.update({
            "work_id": work_id,
            "claimant_rights_holder_id": claimant,
            "dispute_kind": dispute_kind,
            "claim_summary": claim_summary,
            "status": "OPEN",
            "evidence_items": [],
            "arbitration_decision": None,
            "arbitrator_id": None,
        })
        store.disputes[row["id"]] = row
        # Recompute work's dispute_posture (will flip to FROZEN and cascade Distributions).
        recompute_dispute_posture(work_id)
        return serialize(row)


def submit_evidence(dispute_id: str, body) -> dict:
    url = get_str(body, "url", min_len=1, max_len=2048)
    with store.lock:
        d = store.disputes.get(dispute_id)
        if not d:
            raise_err("ERR_NOT_FOUND", "Dispute not found")
        if d["status"] not in OPEN_STATUSES:
            raise_err("ERR_INVALID_STATE", "Dispute not open for evidence")
        _occ_check(d, body)
        d.setdefault("evidence_items", []).append({
            "submitter_role": current_role(),
            "submitter_id": current_user_id(),
            "url": url,
            "submitted_at": store.now_iso(),
        })
        store.touch(d)
        return serialize(d)


def _transition(dispute_id, body, expected_from, new_status, extra_check=None):
    with store.lock:
        d = store.disputes.get(dispute_id)
        if not d:
            raise_err("ERR_NOT_FOUND", "Dispute not found")
        if d["status"] != expected_from:
            raise_err("ERR_INVALID_STATE", f"Dispute not in {expected_from}")
        if extra_check:
            extra_check(d)
        _occ_check(d, body)
        d["status"] = new_status
        store.touch(d)
        return serialize(d)


def start_investigation(dispute_id, body):
    return _transition(dispute_id, body, "OPEN", "UNDER_INVESTIGATION")


def advance_to_mediation(dispute_id, body):
    def check(d):
        if len(d.get("evidence_items", [])) < 2:
            raise_err("ERR_INVALID_STATE", "Need at least 2 evidence items")
    return _transition(dispute_id, body, "UNDER_INVESTIGATION", "MEDIATION", extra_check=check)


def reopen_investigation(dispute_id, body):
    return _transition(dispute_id, body, "MEDIATION", "UNDER_INVESTIGATION")


def advance_to_arbitration(dispute_id, body):
    return _transition(dispute_id, body, "MEDIATION", "ARBITRATION")


def resolve_dispute(dispute_id, body):
    if not isinstance(body, dict):
        raise_err("ERR_RESOLUTION_INVALID", "Body required")
    outcome = body.get("outcome")
    arbitration_decision = body.get("arbitration_decision")
    if outcome not in ("UPHELD", "DISMISSED"):
        raise_err("ERR_RESOLUTION_INVALID", "outcome must be UPHELD or DISMISSED")
    if not isinstance(arbitration_decision, str) or not arbitration_decision:
        raise_err("ERR_RESOLUTION_INVALID", "arbitration_decision required")
    with store.lock:
        d = store.disputes.get(dispute_id)
        if not d:
            raise_err("ERR_NOT_FOUND", "Dispute not found")
        if d["status"] != "ARBITRATION":
            raise_err("ERR_INVALID_STATE", "Dispute must be ARBITRATION to resolve")
        _occ_check(d, body)
        new_status = "RESOLVED_UPHELD" if outcome == "UPHELD" else "RESOLVED_DISMISSED"
        d["status"] = new_status
        d["arbitration_decision"] = arbitration_decision
        d["arbitrator_id"] = current_user_id()
        store.touch(d)

        # SHARE_RATIO upheld with new_share_percentages: update shares + audit.
        new_pcts = body.get("new_share_percentages")
        if outcome == "UPHELD" and d["dispute_kind"] == "SHARE_RATIO" and new_pcts and isinstance(new_pcts, list):
            from services.rights_share import _write_audit_row
            for item in new_pcts:
                if not isinstance(item, dict):
                    continue
                sid = item.get("rights_share_id")
                pct = item.get("share_percent")
                if not sid or pct is None:
                    continue
                s = store.rights_shares.get(sid)
                if not s:
                    continue
                before = {
                    "share_percent": float(s["share_percent"]),
                    "share_status": s["share_status"],
                    "agency_binding_id": s.get("agency_binding_id"),
                }
                s["share_percent"] = float(pct)
                store.touch(s)
                after = {
                    "share_percent": float(s["share_percent"]),
                    "share_status": s["share_status"],
                    "agency_binding_id": s.get("agency_binding_id"),
                }
                _write_audit_row(sid, "PERCENT_UPDATED", before, after)

        # Recompute work's dispute_posture, possibly unfreeze distributions.
        recompute_dispute_posture(d["work_id"])
        return serialize(d)


def withdraw_dispute(dispute_id, body):
    with store.lock:
        d = store.disputes.get(dispute_id)
        if not d:
            raise_err("ERR_NOT_FOUND", "Dispute not found")
        if d["status"] != "OPEN":
            raise_err("ERR_INVALID_STATE", "Dispute must be OPEN to withdraw")
        if d["claimant_rights_holder_id"] != current_user_id():
            raise_err("ERR_FORBIDDEN", "Only claimant may withdraw")
        _occ_check(d, body)
        d["status"] = "WITHDRAWN"
        store.touch(d)
        recompute_dispute_posture(d["work_id"])
        return serialize(d)


def compute_exposure_score(holder_id: str, mode: str):
    """Forward_looking variant: score = 0.6 * open_disputes + 0.4 * ceil(ratio * 100)
       ratio = frozen_distribution_cents / max(1, total_lifetime_paid_cents).
       Then round_half_up to integer.
       chronological variant: replay disputes by created_at, decay by 0.9 per dispute.
    """
    from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
    with store.lock:
        if holder_id not in store.rights_holders:
            raise_err("ERR_NOT_FOUND", "RightsHolder not found")

        # Open disputes touching this holder.
        # Either claimant_rights_holder_id == holder OR any RightsShare on disputed work belongs to holder.
        shares_by_work = {}
        for s in store.rights_shares.values():
            shares_by_work.setdefault(s["work_id"], []).append(s)

        open_disputes = []
        all_disputes = []
        for d in store.disputes.values():
            touches = False
            if d["claimant_rights_holder_id"] == holder_id:
                touches = True
            else:
                for sh in shares_by_work.get(d["work_id"], []):
                    if sh["rights_holder_id"] == holder_id:
                        touches = True
                        break
            if touches:
                all_disputes.append(d)
                if d["status"] in OPEN_STATUSES:
                    open_disputes.append(d)

        frozen_cents = sum(
            dist["gross_amount_cents"]
            for dist in store.distributions.values()
            if dist["rights_holder_id"] == holder_id and dist["status"] == "FROZEN"
        )
        lifetime_paid = max(1, store.holder_lifetime_paid_cents.get(holder_id, 0))

        if mode == "chronological":
            # Replay disputes in created_at order, decaying by 0.9 per subsequent dispute.
            all_disputes.sort(key=lambda d: d["created_at"])
            score = Decimal("0")
            decay = Decimal("0.9")
            n = len(all_disputes)
            for i, _ in enumerate(all_disputes):
                # Position from oldest: contribution is decayed deeper for older ones.
                # Contribution of dispute i = decay**(n-1-i)
                power = n - 1 - i
                contribution = decay ** power
                score += contribution
            score_int = int(score.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return {"score": score_int, "mode": "chronological"}
        else:
            ratio = Decimal(frozen_cents) / Decimal(lifetime_paid)
            ceil_val = (ratio * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_CEILING)
            score_raw = Decimal("0.6") * Decimal(len(open_disputes)) + Decimal("0.4") * ceil_val
            score_int = int(score_raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return {"score": score_int, "mode": "forward_looking"}
