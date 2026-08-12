"""TenantChallenge endpoints."""

from flask import Blueprint

from db import db, new_resource, touch
from errors import err
from response import success_object
from services.core import (
    recompute_billing_posture, recompute_recovery_ytd,
)
from services.validate import (
    body, req_int, req_enum, req_string, opt_string, filter_arg_str,
)
from routes.helpers import (
    get_lease_or_404, get_child_or_404, list_response,
)

bp = Blueprint("challenges", __name__)

REASON_CODES = {
    "GROSS_UP_DISPUTE", "PRO_RATA_DISPUTE", "AUDIT_FINDING",
    "MATH_ERROR", "POOL_MISCLASS",
}
OUTCOMES = {"ACCEPTED", "REJECTED"}


@bp.post("/lease-admin/leases/<lease_id>/tenant-challenges")
def create_challenge(lease_id):
    lease = get_lease_or_404(lease_id)
    data = body()
    reconciliation_id = req_string(data, "reconciliation_id")
    recovery_billing_id = opt_string(data, "recovery_billing_id")
    reason_code = req_enum(data, "reason_code", REASON_CODES)
    claimed_overbilling_cents = req_int(data, "claimed_overbilling_cents",
                                        min_v=1)
    # Referential integrity (pipeline step 8).
    recon = db["reconciliations"].get(reconciliation_id)
    if recon is None or recon["lease_id"] != lease_id:
        err("ERR_REFERENTIAL_INTEGRITY",
            "reconciliation_id must reference a Reconciliation on this lease")
    billing = None
    if recovery_billing_id is not None:
        billing = db["recovery_billings"].get(recovery_billing_id)
        if billing is None or billing["lease_id"] != lease_id:
            err("ERR_REFERENTIAL_INTEGRITY",
                "recovery_billing_id must reference a RecoveryBilling on this lease")
        if billing["status"] != "ISSUED":
            err("ERR_REFERENTIAL_INTEGRITY",
                "recovery_billing_id must reference a billing in ISSUED status")

    cid, common = new_resource()
    challenge = {
        **common,
        "lease_id": lease_id,
        "reconciliation_id": reconciliation_id,
        "recovery_billing_id": recovery_billing_id,
        "reason_code": reason_code,
        "claimed_overbilling_cents": claimed_overbilling_cents,
        "status": "OPEN",
        "round_index": 0,
        "resolution_delta_cents": None,
    }
    db["tenant_challenges"][cid] = challenge
    # Neighborhood reconfiguration: APPROVED reconciliation -> CHALLENGED;
    # linked ISSUED billing -> DISPUTED; posture recomputes up the tree.
    if recon["status"] == "APPROVED":
        recon["status"] = "CHALLENGED"
        touch(recon)
    if billing is not None:
        billing["status"] = "DISPUTED"
        touch(billing)
    recompute_billing_posture(lease)
    return success_object(challenge, status=201)


@bp.get("/lease-admin/leases/<lease_id>/tenant-challenges")
def list_lease_challenges(lease_id):
    get_lease_or_404(lease_id)
    return list_response(
        [c for c in db["tenant_challenges"].values()
         if c["lease_id"] == lease_id],
        filters=[
            (filter_arg_str("status"), lambda r, v: r["status"] == v),
        ])


@bp.get("/lease-admin/tenant-challenges/<challenge_id>")
def get_challenge(challenge_id):
    return success_object(
        get_child_or_404("tenant_challenges", challenge_id, "TenantChallenge"))


@bp.get("/lease-admin/tenant-challenges")
def list_challenges_filtered():
    return list_response(db["tenant_challenges"].values(), filters=[
        (filter_arg_str("lease_id"), lambda r, v: r["lease_id"] == v),
        (filter_arg_str("reconciliation_id"),
         lambda r, v: r["reconciliation_id"] == v),
        (filter_arg_str("recovery_billing_id"),
         lambda r, v: r["recovery_billing_id"] == v),
        (filter_arg_str("status"), lambda r, v: r["status"] == v),
    ])


@bp.post("/lease-admin/tenant-challenges/<challenge_id>/start-review")
def start_review_challenge(challenge_id):
    ch = get_child_or_404("tenant_challenges", challenge_id, "TenantChallenge")
    if ch["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Start-review requires status == OPEN")
    ch["status"] = "UNDER_REVIEW"
    touch(ch)
    return success_object(ch)


@bp.post("/lease-admin/tenant-challenges/<challenge_id>/reopen")
def reopen_challenge(challenge_id):
    ch = get_child_or_404("tenant_challenges", challenge_id, "TenantChallenge")
    if ch["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "Reopen requires status == UNDER_REVIEW")
    if ch["round_index"] >= 3:
        err("ERR_MAX_ROUNDS_REACHED",
            "The maximum number of negotiation rounds has been reached")
    ch["round_index"] += 1
    ch["status"] = "OPEN"
    touch(ch)
    return success_object(ch)


@bp.post("/lease-admin/tenant-challenges/<challenge_id>/resolve")
def resolve_challenge(challenge_id):
    ch = get_child_or_404("tenant_challenges", challenge_id, "TenantChallenge")
    data = body()
    outcome = req_enum(data, "outcome", OUTCOMES)
    resolution_delta_cents = req_int(data, "resolution_delta_cents")
    if ch["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "Resolve requires status == UNDER_REVIEW")
    # Sign rules: accepted requires delta <= 0; rejected requires delta == 0.
    if outcome == "ACCEPTED" and resolution_delta_cents > 0:
        err("ERR_INVALID_RESOLUTION_SIGN",
            "An accepted resolution requires a delta of zero or less")
    if outcome == "REJECTED" and resolution_delta_cents != 0:
        err("ERR_INVALID_RESOLUTION_SIGN",
            "A rejected resolution requires a delta of exactly zero")
    recon = db["reconciliations"].get(ch["reconciliation_id"])
    if outcome == "ACCEPTED" and recon is not None and \
       recon.get("true_up_cents") is not None:
        if abs(resolution_delta_cents) > abs(recon["true_up_cents"]):
            err("ERR_RESOLUTION_EXCEEDS_TRUE_UP",
                "The resolution magnitude exceeds the reconciliation true-up")

    ch["resolution_delta_cents"] = resolution_delta_cents
    ch["status"] = "RESOLVED_ACCEPTED" if outcome == "ACCEPTED" \
        else "RESOLVED_REJECTED"
    touch(ch)

    lease = db["leases"][ch["lease_id"]]
    if outcome == "ACCEPTED" and recon is not None:
        recon["true_up_cents"] = (recon["true_up_cents"] or 0) + \
            resolution_delta_cents
        touch(recon)
        recompute_recovery_ytd(lease)
        lease["cached_recovery_ytd_cents"] += resolution_delta_cents
        touch(lease)
    # Release any linked DISPUTED billing back to ISSUED.
    _release_billing(ch)
    recompute_billing_posture(lease)
    return success_object(ch)


@bp.post("/lease-admin/tenant-challenges/<challenge_id>/escalate")
def escalate_challenge(challenge_id):
    ch = get_child_or_404("tenant_challenges", challenge_id, "TenantChallenge")
    if ch["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "Escalate requires status == UNDER_REVIEW")
    ch["status"] = "ESCALATED"
    touch(ch)
    return success_object(ch)


@bp.post("/lease-admin/tenant-challenges/<challenge_id>/withdraw")
def withdraw_challenge(challenge_id):
    ch = get_child_or_404("tenant_challenges", challenge_id, "TenantChallenge")
    if ch["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Withdraw requires status == OPEN")
    ch["status"] = "WITHDRAWN"
    touch(ch)
    _release_billing(ch)
    # Reconciliation CHALLENGED -> APPROVED when no other open challenges.
    recon = db["reconciliations"].get(ch["reconciliation_id"])
    if recon is not None and recon["status"] == "CHALLENGED":
        others_open = any(
            c for c in db["tenant_challenges"].values()
            if c["reconciliation_id"] == recon["id"] and c["id"] != ch["id"]
            and c["status"] in ("OPEN", "UNDER_REVIEW", "ESCALATED"))
        if not others_open:
            recon["status"] = "APPROVED"
            touch(recon)
    lease = db["leases"][ch["lease_id"]]
    recompute_billing_posture(lease)
    return success_object(ch)


def _release_billing(ch):
    """Return the challenge's linked DISPUTED billing to ISSUED."""
    bid = ch.get("recovery_billing_id")
    if bid:
        b = db["recovery_billings"].get(bid)
        if b is not None and b["status"] == "DISPUTED":
            b["status"] = "ISSUED"
            touch(b)
