"""QR code minting and consumer trace."""

import secrets

from flask import g

from common import (
    get_json_body,
    require_field,
    sort_by_created_at,
    stamp_create_immutable,
)
from db import db
from errors import (
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_QR_ALREADY_BOUND,
    ERR_QR_REVOKED,
    ERR_QR_TOKEN_INVALID,
    raise_error,
)
from services.audit import record_audit
from services.harvest import get_harvest_or_404
from services.planting_batch import _serialize as serialize_batch


def _serialize_qr(q: dict, include_token: bool = False) -> dict:
    out = {
        "id": q["id"],
        "created_at": q["created_at"],
        "planting_batch_id": q["planting_batch_id"],
        "harvest_record_id": q["harvest_record_id"],
        "qr_code_value": q["qr_code_value"],
        "scan_count": q["scan_count"],
        "revoked": q["revoked"],
    }
    if include_token:
        out["anti_counterfeit_token"] = q["anti_counterfeit_token"]
    return out


def mint_qr(harvest_id):
    with db.lock:
        hr = get_harvest_or_404(harvest_id)
        batch = db.planting_batches.get(hr["planting_batch_id"])
        if batch is None:
            raise_error(ERR_NOT_FOUND, "parent batch missing")
        if batch["grower_id"] != g.user_id:
            raise_error(ERR_FORBIDDEN, "grower can only mint QR for own batch")
        # Uniqueness: one QR per harvest_record
        if harvest_id in db.qr_by_harvest:
            raise_error(ERR_QR_ALREADY_BOUND, "QR already bound to this harvest record")

        qr_value = secrets.token_hex(16)  # 32 hex chars
        # Ensure uniqueness across qr_by_value (collision should be astronomically unlikely)
        while qr_value in db.qr_by_value:
            qr_value = secrets.token_hex(16)
        token = secrets.token_urlsafe(32)
        qr = {
            "id": db.new_id(),
            "planting_batch_id": batch["id"],
            "harvest_record_id": harvest_id,
            "qr_code_value": qr_value,
            "anti_counterfeit_token": token,
            "scan_count": 0,
            "revoked": False,
        }
        stamp_create_immutable(qr)
        db.qr_codes[qr["id"]] = qr
        db.qr_by_value[qr_value] = qr["id"]
        db.qr_by_harvest[harvest_id] = qr["id"]
        record_audit(
            "QRCode", qr["id"], "CREATE", "MINTED",
            before_state=None,
            change_summary={"harvest_record_id": harvest_id},
        )
    return _serialize_qr(qr, include_token=True)


def trace_qr(qr_value, args):
    """Consumer trace endpoint. Token is supplied as query param or body."""
    body = get_json_body()
    token = body.get("anti_counterfeit_token") or args.get("anti_counterfeit_token")
    if not token:
        from errors import ERR_VALIDATION
        raise_error(ERR_VALIDATION, "anti_counterfeit_token required")

    with db.lock:
        qr_id = db.qr_by_value.get(qr_value)
        if qr_id is None:
            raise_error(ERR_NOT_FOUND, "QR code not found")
        qr = db.qr_codes[qr_id]
        if qr["revoked"]:
            raise_error(ERR_QR_REVOKED, "QR code is revoked")
        if token != qr["anti_counterfeit_token"]:
            raise_error(ERR_QR_TOKEN_INVALID, "anti_counterfeit_token does not match")

        # Increment scan_count on every successful response.
        qr["scan_count"] += 1

        batch = db.planting_batches.get(qr["planting_batch_id"])
        if batch is None:
            raise_error(ERR_NOT_FOUND, "parent batch missing")

        # planting block — batch + agro applications sorted by application_date ASC
        from services.agro_app import _serialize as ser_agro
        from services.harvest import _serialize as ser_hr
        from services.inspection import _serialize as ser_insp
        from services.logistics import _serialize as ser_leg

        applications = [
            a for a in db.agrochemical_applications.values()
            if a["planting_batch_id"] == batch["id"]
        ]
        applications.sort(key=lambda x: (x["application_date"], x["created_at"]))
        planting_block = serialize_batch(batch)
        planting_block["agrochemical_applications"] = [ser_agro(a) for a in applications]

        harvest_record = db.harvest_records.get(qr["harvest_record_id"])

        # Inspection: latest ISSUED report for batch (issued_at DESC, id ASC tie-break)
        issued_reports = [
            r for r in db.inspection_reports.values()
            if r["planting_batch_id"] == batch["id"] and r["status"] == "ISSUED"
        ]
        issued_reports.sort(key=lambda r: (r["issued_at"] or "", r["id"]))
        # latest by issued_at DESC means we sort ascending and take the last;
        # tie-break: id ASC means among same issued_at, smallest id first → take last.
        # Use proper sort: primary issued_at DESC, secondary id ASC
        if issued_reports:
            issued_reports.sort(key=lambda r: r["id"])  # secondary ASC
            issued_reports.sort(key=lambda r: (r["issued_at"] or ""), reverse=True)  # primary DESC stable
            inspection = ser_insp(issued_reports[0])
        else:
            inspection = None

        # Logistics: legs sorted by leg_index ASC
        legs = [l for l in db.logistics_legs.values()
                if l["planting_batch_id"] == batch["id"]]
        legs.sort(key=lambda l: l["leg_index"])

        return {
            "qr": _serialize_qr(qr, include_token=False),
            "planting": planting_block,
            "harvest": ser_hr(harvest_record) if harvest_record else None,
            "inspection": inspection,
            "logistics": [ser_leg(l) for l in legs],
        }


def revoke_qrs_for_batch(batch_id, value=True):
    """Set revoked=value on every QR for the batch."""
    for qr in db.qr_codes.values():
        if qr["planting_batch_id"] == batch_id:
            qr["revoked"] = bool(value)


def get_qr_or_404(qr_value):
    qr_id = db.qr_by_value.get(qr_value)
    if qr_id is None:
        raise_error(ERR_NOT_FOUND, "QR code not found")
    return db.qr_codes[qr_id]
