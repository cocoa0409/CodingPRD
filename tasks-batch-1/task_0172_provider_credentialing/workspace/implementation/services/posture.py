"""Posture recomputation orchestration and credentialing-lapse cascade."""
from db import store
from services.calc import (
    compute_posture,
    compute_readiness_score,
    compute_sanction_score,
)
from services.model import touch


def recompute_provider(provider, recompute_readiness=True):
    """Recompute sanction_score, credentialing_status, and (optionally)
    readiness_score on a provider. If credentialing_status leaves CLEARED,
    cascade-terminate the provider's ACTIVE payer enrollments. Bumps the
    provider's version/updated_at since derived fields are a mutation.

    Returns the new credentialing_status.
    """
    prev_status = provider["credentialing_status"]

    new_sanction = compute_sanction_score(provider)
    provider["sanction_score"] = new_sanction

    new_status = compute_posture(provider)
    provider["credentialing_status"] = new_status

    if recompute_readiness:
        provider["readiness_score"] = compute_readiness_score(provider)

    touch(provider)

    # Cascade: provider leaves CLEARED -> auto-terminate ACTIVE enrollments.
    if prev_status == "CLEARED" and new_status != "CLEARED":
        _auto_terminate_enrollments(provider)

    return new_status


def _auto_terminate_enrollments(provider):
    for enr in store.payer_enrollments.values():
        if enr["provider_id"] != provider["id"]:
            continue
        if enr["status"] == "ACTIVE":
            enr["status"] = "TERMINATED"
            enr["termination_reason"] = "CREDENTIALING_LAPSED"
            touch(enr)
