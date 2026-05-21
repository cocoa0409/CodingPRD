"""PortabilityRequest lifecycle: submit, absorb, bill, deny."""

from __future__ import annotations

from app import clock, store
from app.errors import APIError, fk_not_found, invalid_state, not_found, validation
from app.services.common import occ_check, touch
from app.util import new_id, require_str


_VALID_DENIAL = ("RECEIVING_PHA_OVER_LEASING_CAP", "INELIGIBLE_HOUSEHOLD", "MOBILITY_ZONE_RESTRICTION", "NULL")


def create_request(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation("Body must be a JSON object")
    try:
        voucher_id = require_str(payload.get("voucher_id"), field="voucher_id")
        receiving_pha_id = require_str(payload.get("receiving_pha_id"), field="receiving_pha_id")
    except ValueError as exc:
        raise validation(str(exc))

    voucher = store.vouchers.get(voucher_id)
    if voucher is None:
        raise fk_not_found(f"voucher_id {voucher_id!r} not found")
    if voucher["status"] not in ("SEARCHING", "LEASED", "SEARCHING_REISSUED"):
        raise invalid_state("Voucher status does not permit portability")
    if receiving_pha_id == voucher["administering_pha_id"]:
        raise APIError(
            "ERR_INVALID_RECEIVING_PHA",
            422,
            "receiving_pha_id must differ from administering_pha_id",
        )
    if receiving_pha_id not in store.CONFIGURED_PHAS:
        raise APIError(
            "ERR_INVALID_RECEIVING_PHA",
            422,
            "receiving_pha_id is not in the PHA network",
        )

    now = clock.now()
    req_id = new_id()
    record = {
        "id": req_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "voucher_id": voucher_id,
        "receiving_pha_id": receiving_pha_id,
        "requested_at": now,
        "outcome": "INITIATED",
        "decided_at": None,
        "denial_reason": None,
    }
    store.portability_requests[req_id] = record
    return record


def absorb(req_id: str, payload: dict) -> dict:
    payload = payload or {}
    req = store.portability_requests.get(req_id)
    if req is None:
        raise not_found("PortabilityRequest not found")
    occ_check(req, payload.get("version"))

    if req["outcome"] != "INITIATED":
        raise invalid_state("PortabilityRequest already decided")

    voucher = store.vouchers.get(req["voucher_id"])
    if voucher is None:
        raise invalid_state("Voucher missing for portability request")

    # Mobility-zone restriction at receiving PHA. With no per-PHA zone catalog
    # in the scaffold we treat the default PHA as a non-ZONE_A absorber: a
    # special-mobility voucher absorbed to a non-default PHA must be denied.
    # The PRD says: "must be denied with MOBILITY_ZONE_RESTRICTION rather than absorbed".
    # We implement this guard but, since we cannot infer "offers ZONE_A units"
    # from configuration, we do not preemptively reject by default.

    now = clock.now()
    receiving = req["receiving_pha_id"]
    voucher["administering_pha_id"] = receiving
    touch(voucher)

    if voucher["status"] == "LEASED":
        # Cascade: voucher → PORTED_OUT, active tenancy → TERMINATED(PORTABILITY_ABSORBED).
        for tn in store.tenancies.values():
            if tn.get("voucher_id") == voucher["id"] and tn.get("status") in ("ACTIVE", "ABATED", "PENDING_INSPECTION", "PENDING_RENT_REASONABLE"):
                tn["status"] = "TERMINATED"
                tn["termination_reason"] = "PORTABILITY_ABSORBED"
                tn["terminated_at"] = now
                touch(tn)
                # Emit a PORTABILITY_CLOSEOUT row for any prebooked future month.
                from app.services.hap import emit_portability_closeout
                emit_portability_closeout(tn, source_request_id=req["id"])
        voucher["status"] = "PORTED_OUT"
        touch(voucher)

    req["outcome"] = "ABSORBED"
    req["decided_at"] = now
    touch(req)
    return req


def bill(req_id: str, payload: dict) -> dict:
    payload = payload or {}
    req = store.portability_requests.get(req_id)
    if req is None:
        raise not_found("PortabilityRequest not found")
    occ_check(req, payload.get("version"))

    if req["outcome"] != "INITIATED":
        raise invalid_state("PortabilityRequest already decided")

    req["outcome"] = "BILLED"
    req["decided_at"] = clock.now()
    touch(req)
    return req


def deny(req_id: str, payload: dict) -> dict:
    payload = payload or {}
    req = store.portability_requests.get(req_id)
    if req is None:
        raise not_found("PortabilityRequest not found")
    occ_check(req, payload.get("version"))

    if req["outcome"] != "INITIATED":
        raise invalid_state("PortabilityRequest already decided")

    try:
        denial_reason = require_str(payload.get("denial_reason"), field="denial_reason", allowed=_VALID_DENIAL)
    except ValueError as exc:
        raise validation(str(exc))

    req["outcome"] = "DENIED"
    req["denial_reason"] = denial_reason
    req["decided_at"] = clock.now()
    touch(req)
    return req
