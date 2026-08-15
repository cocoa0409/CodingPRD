"""CAQH profile attestation."""
from datetime import timedelta

from flask import Blueprint, g

from db import store, touch
from errors import ApiError, ERR_PROFILE_OWNERSHIP_MISMATCH, not_found
from middleware import require_roles
from response import success_object
from serializers import pub
from services import ATTESTATION_CYCLE_DAYS
from util import fmt_ts

bp = Blueprint("caqh", __name__)


@bp.post("/api/caqh-profiles/<pid>/attest")
@require_roles("Provider")
def attest_caqh_profile(pid):
    prof = store.caqh_profiles.get(pid)
    if prof is None:
        raise not_found("CAQHProfile")
    # Actor scope: a Provider attests only their own profile.
    if g.user_id != prof["provider_id"]:
        raise ApiError(
            ERR_PROFILE_OWNERSHIP_MISMATCH,
            403,
            "A provider may only attest their own CAQH profile",
        )
    # Attestation is permitted from every status and resets the 120-day cycle.
    now = store.clock
    prof["status"] = "ATTESTED"
    prof["last_attested_at"] = fmt_ts(now)
    prof["due_at"] = fmt_ts(now + timedelta(days=ATTESTATION_CYCLE_DAYS))
    touch(prof)
    return success_object(pub(prof))
