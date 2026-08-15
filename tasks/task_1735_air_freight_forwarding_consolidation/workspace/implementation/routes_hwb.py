"""House waybill issuance, screening lifecycle, measurement, and FK reverse
lookups (PRD §3.3, §3.6)."""
from decimal import Decimal

from flask import Blueprint, g, request

import services as svc
from db import store
from errors import (
    ApiError,
    ERR_DUPLICATE_WAYBILL_NUMBER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SHIPPER_NOT_KNOWN,
)
from middleware import (
    ALL_ROLES,
    get_body,
    opt_bool,
    opt_num,
    pagination_params,
    req_int,
    req_nonempty_str,
    req_num,
    require_roles,
)
from response import ok, ok_list

bp = Blueprint("house_waybills", __name__)


@bp.post("/house-waybills")
@require_roles("ForwarderOps")
def create_hwb():
    body = get_body()
    # Existence (priority 3): body shipper reference resolves.
    if isinstance(body.get("shipper_id"), str):
        svc.get_shipper(body["shipper_id"])
    shipper_id = req_nonempty_str(body, "shipper_id")
    hwb_number = req_nonempty_str(body, "hwb_number")
    origin_code = req_nonempty_str(body, "origin_code")
    destination_code = req_nonempty_str(body, "destination_code")
    pieces = req_int(body, "pieces", minimum=1)
    gross_weight_kg = req_num(body, "gross_weight_kg", exclusive_minimum=0)
    declared_volume_m3 = req_num(body, "declared_volume_m3", exclusive_minimum=0)
    dg_flag = opt_bool(body, "dg_flag", default=False)
    declared_value_amount = opt_num(body, "declared_value_amount", default=Decimal(0), minimum=0)
    declared_value_surcharge_paid = opt_bool(body, "declared_value_surcharge_paid", default=False)
    # Structural uniqueness guard (priority 8).
    if hwb_number in store.hwb_by_number:
        raise ApiError(
            ERR_DUPLICATE_WAYBILL_NUMBER,
            f"House waybill number '{hwb_number}' already exists.",
            409,
        )
    h = svc.fresh_rec(
        shipper_id=shipper_id,
        mawb_id=None,
        hwb_number=hwb_number,
        origin_code=origin_code,
        destination_code=destination_code,
        pieces=pieces,
        gross_weight_kg=gross_weight_kg,
        declared_volume_m3=declared_volume_m3,
        measured_volume_m3=None,
        effective_volume_m3=declared_volume_m3,
        chargeable_weight_kg=Decimal(0),
        weight_basis="UNRATED",
        dg_flag=dg_flag,
        declared_value_amount=declared_value_amount,
        declared_value_surcharge_paid=declared_value_surcharge_paid,
        freight_amount=Decimal(0),
        fuel_surcharge_amount=Decimal(0),
        security_fee_amount=Decimal(0),
        spot_surcharge_amount=Decimal(0),
        spot_surcharge_applied=False,
        total_charge_amount=Decimal(0),
        rate_agreement_id=None,
        submitted_by_user_id=None,
        delivered_at_utc=None,
        status="DRAFT",
    )
    store.hwbs[h.id] = h
    store.hwb_by_number[hwb_number] = h
    return ok(svc.hwb_json(h), 201)


@bp.get("/house-waybills")
@require_roles(*ALL_ROLES)
def list_hwbs():
    limit, offset = pagination_params()
    items = list(store.hwbs.values())
    shipper_id = request.args.get("shipper_id")
    mawb_id = request.args.get("mawb_id")
    status = request.args.get("status")
    rate_agreement_id = request.args.get("rate_agreement_id")
    if shipper_id is not None:
        items = [h for h in items if h.shipper_id == shipper_id]
    if mawb_id is not None:
        items = [h for h in items if h.mawb_id == mawb_id]
    if status is not None:
        items = [h for h in items if h.status == status]
    if rate_agreement_id is not None:
        items = [h for h in items if h.rate_agreement_id == rate_agreement_id]
    items = svc.sorted_by_created(items)
    page, total = svc.paginate(items, limit, offset)
    return ok_list([svc.hwb_json(h) for h in page], total, limit, offset)


@bp.get("/house-waybills/<hid>")
@require_roles(*ALL_ROLES)
def get_hwb(hid):
    return ok(svc.hwb_json(svc.get_hwb(hid)), 200)


@bp.post("/house-waybills/<hid>/submit")
@require_roles("ForwarderOps")
def submit_hwb(hid):
    h = svc.get_hwb(hid)
    if h.status != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE,
            f"House waybill status is {h.status}; submit requires DRAFT.",
            409,
        )
    # Dangerous-goods gate (priority 6): shipper must be KNOWN at submit.
    shipper = svc.get_shipper(h.shipper_id)
    if h.dg_flag and shipper.known_shipper_status != "KNOWN":
        raise ApiError(
            ERR_SHIPPER_NOT_KNOWN,
            "Dangerous-goods waybill requires the shipper to be KNOWN at submit.",
            403,
        )
    h.status = "SCREENING"
    h.submitted_by_user_id = g.user_id
    svc.touch(h)
    # Auto-create required records: SECURITY first, then DANGEROUS_GOODS iff
    # dg_flag; fresh_rec mints strictly increasing created_at within a submit.
    sec = svc.fresh_rec(
        hwb_id=h.id,
        screening_type="SECURITY",
        result="PENDING",
        rejection_reason=None,
        resolved_by_user_id=None,
    )
    store.screenings[sec.id] = sec
    if h.dg_flag:
        dg = svc.fresh_rec(
            hwb_id=h.id,
            screening_type="DANGEROUS_GOODS",
            result="PENDING",
            rejection_reason=None,
            resolved_by_user_id=None,
        )
        store.screenings[dg.id] = dg
    return ok(svc.hwb_json(h), 200)


@bp.post("/house-waybills/<hid>/recall")
@require_roles("ForwarderOps")
def recall_hwb(hid):
    h = svc.get_hwb(hid)
    if h.status not in ("SCREENING", "SCREENING_REJECTED"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"House waybill status is {h.status}; recall requires SCREENING or SCREENING_REJECTED.",
            409,
        )
    # Records are retained for audit; clearance is judged on the latest per type.
    h.status = "DRAFT"
    svc.touch(h)
    return ok(svc.hwb_json(h), 200)


@bp.post("/house-waybills/<hid>/cancel")
@require_roles("ForwarderOps")
def cancel_hwb(hid):
    h = svc.get_hwb(hid)
    if h.status not in ("DRAFT", "SCREENING", "SCREENING_REJECTED", "CLEARED"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"House waybill status is {h.status}; it cannot be cancelled.",
            409,
        )
    h.status = "CANCELLED"
    svc.touch(h)
    return ok(svc.hwb_json(h), 200)


@bp.post("/house-waybills/<hid>/measure")
@require_roles("ForwarderOps")
def measure_hwb(hid):
    h = svc.get_hwb(hid)
    if h.status != "CONSOLIDATED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"House waybill status is {h.status}; measurement requires CONSOLIDATED.",
            409,
        )
    body = get_body()
    measured = req_num(body, "measured_volume_m3", exclusive_minimum=0)
    h.measured_volume_m3 = measured
    # effective volume reads the measured value once set (PRD §3.6).
    h.effective_volume_m3 = measured
    svc.touch(h)
    return ok(svc.hwb_json(h), 200)


@bp.get("/house-waybills/<hid>/screening-records")
@require_roles(*ALL_ROLES)
def list_screening_records(hid):
    svc.get_hwb(hid)
    limit, offset = pagination_params()
    items = svc.sorted_by_created(
        [r for r in store.screenings.values() if r.hwb_id == hid]
    )
    page, total = svc.paginate(items, limit, offset)
    return ok_list([svc.screening_json(r) for r in page], total, limit, offset)


@bp.get("/house-waybills/<hid>/customs-entries")
@require_roles(*ALL_ROLES)
def list_customs_entries(hid):
    svc.get_hwb(hid)
    limit, offset = pagination_params()
    items = svc.sorted_by_created(
        [c for c in store.customs_entries.values() if c.hwb_id == hid]
    )
    page, total = svc.paginate(items, limit, offset)
    return ok_list([svc.customs_entry_json(c) for c in page], total, limit, offset)


@bp.get("/house-waybills/<hid>/claims")
@require_roles(*ALL_ROLES)
def list_hwb_claims(hid):
    svc.get_hwb(hid)
    limit, offset = pagination_params()
    items = svc.sorted_by_created(
        [c for c in store.claims.values() if c.hwb_id == hid]
    )
    page, total = svc.paginate(items, limit, offset)
    return ok_list([svc.claim_json(c) for c in page], total, limit, offset)
