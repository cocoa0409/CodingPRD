"""PickupAuthorization service."""
from datetime import datetime, timedelta, timezone
from clock import now
from db import store, GLOBAL_LOCK
from errors import E, raise_error
from services.common import stamp_create


def _parse_iso(s):
    if isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        raise_error(E.VALIDATION, "expires_at must be ISO 8601 string")
    try:
        # Accept trailing Z
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise_error(E.VALIDATION, "expires_at not valid ISO 8601")


def create_authorization(parcel_id: str, body: dict):
    from services.parcel import get_parcel
    parcel = get_parcel(parcel_id, allow_not_found=False)
    delegate_name = body.get("delegate_name")
    delegate_id_number = body.get("delegate_id_number")
    delegate_phone = body.get("delegate_phone")
    expires_at = body.get("expires_at")
    if not delegate_name or not delegate_id_number or not delegate_phone or not expires_at:
        raise_error(E.VALIDATION, "delegate_* and expires_at required")
    expires_dt = _parse_iso(expires_at)

    with GLOBAL_LOCK:
        t = now()
        if expires_dt <= t:
            raise_error(E.AUTHORIZATION_EXPIRY_INVALID, "expires_at must be > now")
        if parcel.get("free_storage_deadline") is None:
            # No deadline yet → can't compute upper bound; use a generous fallback:
            # but per PRD, this is only invoked when parcel is shelved-ish; reject as invalid.
            raise_error(E.AUTHORIZATION_EXPIRY_INVALID,
                        "Parcel has no free_storage_deadline")
        upper = parcel["free_storage_deadline"] + timedelta(days=7)
        if expires_dt > upper:
            raise_error(E.AUTHORIZATION_EXPIRY_INVALID,
                        "expires_at > free_storage_deadline + 7 days")

        row = stamp_create({
            "parcel_id": parcel_id,
            "delegate_name": delegate_name,
            "delegate_id_number": delegate_id_number,
            "delegate_phone": delegate_phone,
            "granted_at": t,
            "expires_at": expires_dt,
            "status": "ACTIVE",
        }, common_fields=False)
        store.pickup_auths[row["id"]] = row
        return row


def update_authorization(auth_id: str, body: dict):
    auth = store.pickup_auths.get(auth_id)
    if auth is None:
        raise_error(E.RESOURCE_NOT_FOUND, "Authorization not found")
    new_status = body.get("status")
    if new_status not in ("REVOKED",):
        raise_error(E.VALIDATION, "Only status=REVOKED supported")
    with GLOBAL_LOCK:
        if auth["status"] not in ("ACTIVE",):
            raise_error(E.INVALID_PARCEL_STATE, "Authorization is not active")
        auth["status"] = "REVOKED"
        return auth
