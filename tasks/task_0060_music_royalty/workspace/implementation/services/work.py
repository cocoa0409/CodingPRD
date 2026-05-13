"""Work service: registration, lifecycle transitions, dispute_posture cascade."""

from decimal import Decimal

from db import store
from errors import raise_err
from clock import clock
from middleware import current_role, current_user_id
from util import (
    get_str, get_enum, get_int, get_number,
    ISRC_RE, ISWC_RE, URL_RE,
)

RIGHTS_TYPES = {"COMPOSITION", "LYRICS", "RECORDING", "PERFORMANCE"}
COCREATOR_ROLES = {"COMPOSER", "LYRICIST", "PRODUCER", "PERFORMER"}
WORK_STATUSES = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "WITHDRAWN"}


def serialize(w: dict) -> dict:
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
        "owner_rights_holder_id": w.get("owner_rights_holder_id"),
        "title": w["title"],
        "duration_seconds": w["duration_seconds"],
        "isrc": w.get("isrc"),
        "iswc": w.get("iswc"),
        "rights_type": w["rights_type"],
        "co_creators": w.get("co_creators", []),
        "original_proof_url": w.get("original_proof_url"),
        "registration_status": w["registration_status"],
        "dispute_posture": w["dispute_posture"],
        "reject_reason": w.get("reject_reason"),
        "reviewer_id": w.get("reviewer_id"),
    }


def _validate_cocreators(cc, require_sum_100=False):
    if not isinstance(cc, list):
        raise_err("ERR_VALIDATION", "co_creators must be an array")
    if not (1 <= len(cc) <= 16):
        raise_err("ERR_VALIDATION", "co_creators length 1..16")
    total = Decimal("0")
    for item in cc:
        if not isinstance(item, dict):
            raise_err("ERR_VALIDATION", "co_creator must be object")
        full_name = item.get("full_name")
        role = item.get("role")
        pct = item.get("contribution_percent")
        if not isinstance(full_name, str) or not full_name:
            raise_err("ERR_VALIDATION", "co_creator.full_name required")
        if role not in COCREATOR_ROLES:
            raise_err("ERR_VALIDATION", "co_creator.role invalid")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            raise_err("ERR_VALIDATION", "co_creator.contribution_percent must be numeric")
        total += Decimal(str(pct))
    if require_sum_100 and total != Decimal("100"):
        raise_err("ERR_COCREATOR_SUM_INVALID", "co_creators contribution sum != 100")
    return total


def create_work(body: dict) -> dict:
    title = get_str(body, "title", min_len=1, max_len=200)
    duration_seconds = get_int(body, "duration_seconds", lo=1, hi=7200)
    rights_type = get_enum(body, "rights_type", RIGHTS_TYPES)

    isrc = body.get("isrc")
    iswc = body.get("iswc")
    if isrc is not None:
        if not isinstance(isrc, str) or not ISRC_RE.match(isrc):
            raise_err("ERR_VALIDATION", "isrc must be exactly 12 alphanumeric chars")
    if iswc is not None:
        if not isinstance(iswc, str) or not ISWC_RE.match(iswc):
            raise_err("ERR_VALIDATION", "iswc must match T followed by 10 digits")

    co_creators = body.get("co_creators")
    if co_creators is None:
        raise_err("ERR_VALIDATION", "co_creators required")
    _validate_cocreators(co_creators, require_sum_100=False)

    original_proof_url = get_str(body, "original_proof_url", min_len=1, max_len=2048)
    if not URL_RE.match(original_proof_url):
        raise_err("ERR_VALIDATION", "original_proof_url must be http/https URL")

    with store.lock:
        # Uniqueness check on isrc / iswc among existing Works
        if isrc:
            for w in store.works.values():
                if w.get("isrc") == isrc:
                    raise_err("ERR_DUPLICATE_IDENTIFIER", "Duplicate isrc")
        if iswc:
            for w in store.works.values():
                if w.get("iswc") == iswc:
                    raise_err("ERR_DUPLICATE_IDENTIFIER", "Duplicate iswc")

        row = store.common_fields()
        row.update({
            "owner_rights_holder_id": current_user_id(),
            "title": title,
            "duration_seconds": duration_seconds,
            "isrc": isrc,
            "iswc": iswc,
            "rights_type": rights_type,
            "co_creators": co_creators,
            "original_proof_url": original_proof_url,
            "registration_status": "DRAFT",
            "dispute_posture": "CLEAR",
            "reject_reason": None,
            "reviewer_id": None,
        })
        store.works[row["id"]] = row
    return serialize(row)


def get_work(work_id: str) -> dict:
    with store.lock:
        w = store.works.get(work_id)
        if not w:
            raise_err("ERR_NOT_FOUND", "Work not found")
        return serialize(w)


def list_works(args):
    from util import parse_pagination
    limit, offset = parse_pagination(args)
    rs = args.get("registration_status")
    dp = args.get("dispute_posture")
    rt = args.get("rights_type")
    with store.lock:
        rows = list(store.works.values())
    if rs:
        rows = [r for r in rows if r["registration_status"] == rs]
    if dp:
        rows = [r for r in rows if r["dispute_posture"] == dp]
    if rt:
        rows = [r for r in rows if r["rights_type"] == rt]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serialize(r) for r in page], total, limit, offset


def _occ_check(row: dict, body):
    if isinstance(body, dict) and "version" in body and body["version"] is not None:
        if body["version"] != row["version"]:
            raise_err("ERR_VERSION_CONFLICT", "Version conflict")


def _check_state(w, expected):
    if w["registration_status"] != expected:
        raise_err("ERR_INVALID_STATE", f"Work not in {expected}")


def _owner_check(w):
    if current_role() == "RightsHolder":
        if w.get("owner_rights_holder_id") != current_user_id():
            raise_err("ERR_FORBIDDEN", "Not owner")


def submit_work(work_id: str, body) -> dict:
    with store.lock:
        w = store.works.get(work_id)
        if not w:
            raise_err("ERR_NOT_FOUND", "Work not found")
        _owner_check(w)
        _check_state(w, "DRAFT")
        # Recheck preconditions
        rt = w["rights_type"]
        if rt in {"RECORDING", "PERFORMANCE"} and not w.get("isrc"):
            raise_err("ERR_VALIDATION", "isrc required for RECORDING/PERFORMANCE")
        if rt in {"COMPOSITION", "LYRICS"} and not w.get("iswc"):
            raise_err("ERR_VALIDATION", "iswc required for COMPOSITION/LYRICS")
        # Required metadata already present at creation.
        # Co-creator sum check.
        _validate_cocreators(w.get("co_creators", []), require_sum_100=True)
        if not w.get("original_proof_url"):
            raise_err("ERR_VALIDATION", "original_proof_url required")
        _occ_check(w, body)
        w["registration_status"] = "SUBMITTED"
        store.touch(w)
        return serialize(w)


def take_review(work_id: str, body) -> dict:
    with store.lock:
        w = store.works.get(work_id)
        if not w:
            raise_err("ERR_NOT_FOUND", "Work not found")
        _check_state(w, "SUBMITTED")
        _occ_check(w, body)
        w["registration_status"] = "UNDER_REVIEW"
        w["reviewer_id"] = current_user_id()
        store.touch(w)
        return serialize(w)


def approve_work(work_id: str, body) -> dict:
    from decimal import Decimal
    with store.lock:
        w = store.works.get(work_id)
        if not w:
            raise_err("ERR_NOT_FOUND", "Work not found")
        _check_state(w, "UNDER_REVIEW")
        # Validate at least one ACTIVE share, sum == 100
        active_shares = [s for s in store.rights_shares.values()
                         if s["work_id"] == work_id and s["share_status"] == "ACTIVE"]
        if not active_shares:
            raise_err("ERR_SHARE_SUM_INVALID", "No active shares")
        total = sum((Decimal(str(s["share_percent"])) for s in active_shares), Decimal("0"))
        if total != Decimal("100"):
            raise_err("ERR_SHARE_SUM_INVALID", "Share percent sum != 100")
        _occ_check(w, body)
        w["registration_status"] = "APPROVED"
        w["dispute_posture"] = "CLEAR"
        store.touch(w)
        return serialize(w)


def reject_work(work_id: str, body) -> dict:
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "reject_reason required")
    reject_reason = body.get("reject_reason")
    if not isinstance(reject_reason, str) or not (1 <= len(reject_reason) <= 500):
        raise_err("ERR_VALIDATION", "reject_reason 1..500 chars")
    with store.lock:
        w = store.works.get(work_id)
        if not w:
            raise_err("ERR_NOT_FOUND", "Work not found")
        _check_state(w, "UNDER_REVIEW")
        _occ_check(w, body)
        w["registration_status"] = "REJECTED"
        w["reject_reason"] = reject_reason
        store.touch(w)
        # Cascade: every ACTIVE RightsShare for this work → TERMINATED, plus audit
        from services.rights_share import _write_audit_row
        for s in list(store.rights_shares.values()):
            if s["work_id"] == work_id and s["share_status"] == "ACTIVE":
                before = {
                    "share_percent": float(s["share_percent"]),
                    "share_status": s["share_status"],
                    "agency_binding_id": s.get("agency_binding_id"),
                }
                s["share_status"] = "TERMINATED"
                store.touch(s)
                after = {
                    "share_percent": float(s["share_percent"]),
                    "share_status": s["share_status"],
                    "agency_binding_id": s.get("agency_binding_id"),
                }
                _write_audit_row(s["id"], "TERMINATED", before, after)
        return serialize(w)


def withdraw_work(work_id: str, body) -> dict:
    with store.lock:
        w = store.works.get(work_id)
        if not w:
            raise_err("ERR_NOT_FOUND", "Work not found")
        _owner_check(w)
        _check_state(w, "DRAFT")
        _occ_check(w, body)
        w["registration_status"] = "WITHDRAWN"
        store.touch(w)
        return serialize(w)


def return_to_draft(work_id: str, body) -> dict:
    with store.lock:
        w = store.works.get(work_id)
        if not w:
            raise_err("ERR_NOT_FOUND", "Work not found")
        _check_state(w, "SUBMITTED")
        _occ_check(w, body)
        w["registration_status"] = "DRAFT"
        store.touch(w)
        return serialize(w)


def recompute_dispute_posture(work_id: str):
    """Recompute Work.dispute_posture. Run after any Dispute open/resolve/withdraw.
    Returns the new posture. Caller holds store.lock."""
    w = store.works.get(work_id)
    if not w:
        return None
    OPEN_STATUSES = {"OPEN", "UNDER_INVESTIGATION", "MEDIATION", "ARBITRATION"}
    any_open = any(
        d["work_id"] == work_id and d["status"] in OPEN_STATUSES
        for d in store.disputes.values()
    )
    new_posture = "FROZEN" if any_open else "CLEAR"
    old_posture = w["dispute_posture"]
    if new_posture == old_posture:
        return new_posture
    w["dispute_posture"] = new_posture
    store.touch(w)
    # Cascade Distribution status updates
    if old_posture == "CLEAR" and new_posture == "FROZEN":
        # PENDING/RELEASED distributions on this work flip to FROZEN.
        for d in store.distributions.values():
            if d["work_id"] == work_id and d["status"] in ("PENDING", "RELEASED"):
                d["status"] = "FROZEN"
                store.touch(d)
    elif old_posture == "FROZEN" and new_posture == "CLEAR":
        for d in store.distributions.values():
            if d["work_id"] == work_id and d["status"] == "FROZEN":
                d["status"] = "RELEASED"
                store.touch(d)
    return new_posture
