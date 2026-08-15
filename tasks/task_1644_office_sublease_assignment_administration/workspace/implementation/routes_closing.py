"""SubleaseAgreement, RecognitionAgreement, Settlement, RestorationObligation,
and Clock endpoints."""
from flask import Blueprint

import db
from db import store, new_id, touch, new_common, iso_logical, parse_iso
from errors import ApiError
from response import ok, created, paginate
from middleware import get_context, require_roles, ALL_ROLES, ADMIN_READ
from validation import parse_body, require_path_entity
from domain import (
    compute_settlement_fields, get_settlement_measurement,
    get_recognition_agreement as domain_get_ra,
    get_sublease_agreement as domain_get_sa,
    evaluate_deemed_approvals, decrement_lease_open_count,
)

bp = Blueprint("closing", __name__)


# ---------------------------------------------------------------------------
# SubleaseAgreement — read
# ---------------------------------------------------------------------------

@bp.get("/sublease-admin/sublease-agreements/<sa_id>")
def get_sublease_agreement(sa_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    return ok(require_path_entity(store.sublease_agreements, sa_id))


@bp.get("/sublease-admin/sublease-agreements")
def list_sublease_agreements():
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    rows = list(store.sublease_agreements.values())
    for f in ("transfer_request_id", "status", "demised_area_id"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# SubleaseAgreement — terminate
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/sublease-agreements/<sa_id>/terminate")
def terminate_sublease_agreement(sa_id):
    uid, role, _ = get_context()
    require_roles(["Tenant"])
    sa = require_path_entity(store.sublease_agreements, sa_id)
    transfer = store.transfer_requests.get(sa["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")
    lease = store.leases[transfer["lease_id"]]

    # State: must be EXECUTED or RECOGNIZED
    if sa["status"] not in ("EXECUTED", "RECOGNIZED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Terminate requires the instrument to be EXECUTED or RECOGNIZED")

    # Identity: caller must be the lease's tenant
    if uid != lease["tenant_party_id"]:
        raise ApiError("ERR_DUTY_SEGREGATION", 403,
                       "Only the lease's tenant of record may terminate the instrument")

    sa["status"] = "TERMINATED"
    touch(sa)
    return ok(sa)


# ---------------------------------------------------------------------------
# RecognitionAgreement — read
# ---------------------------------------------------------------------------

@bp.get("/sublease-admin/recognition-agreements/<ra_id>")
def get_recognition_agreement_by_id(ra_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.recognition_agreements, ra_id))


@bp.get("/sublease-admin/recognition-agreements")
def list_recognition_agreements():
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    rows = list(store.recognition_agreements.values())
    for f in ("transfer_request_id", "sublease_agreement_id", "status"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# RecognitionAgreement — sign
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/recognition-agreements/<ra_id>/sign")
def sign_recognition_agreement(ra_id):
    uid, role, _ = get_context()
    require_roles(["Landlord", "Subtenant", "Assignee"])
    body = parse_body({
        "signatory": ("enum", True, ["LANDLORD", "COUNTERPARTY"]),
    }, allow_empty=False)

    ra = require_path_entity(store.recognition_agreements, ra_id)
    transfer = store.transfer_requests.get(ra["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")
    lease = store.leases[transfer["lease_id"]]

    # State: must be DRAFTED or PARTIALLY_SIGNED
    if ra["status"] not in ("DRAFTED", "PARTIALLY_SIGNED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Sign requires the agreement to be DRAFTED or PARTIALLY_SIGNED")

    signatory = body["signatory"]
    now = db.LOGICAL_CLOCK

    # Identity check per signatory
    if signatory == "LANDLORD":
        if uid != lease["landlord_party_id"]:
            raise ApiError("ERR_SIGNATORY_MISMATCH", 403,
                           "Signatory LANDLORD requires the lease's landlord party id")
        if ra.get("landlord_signed_at") is not None:
            raise ApiError("ERR_SIGNATORY_MISMATCH", 403,
                           "Landlord has already signed")
        ra["landlord_signed_at"] = iso_logical(now)
    else:  # COUNTERPARTY
        if uid != transfer["counterparty_id"]:
            raise ApiError("ERR_SIGNATORY_MISMATCH", 403,
                           "Signatory COUNTERPARTY requires the transfer's counterparty id")
        if ra.get("counterparty_signed_at") is not None:
            raise ApiError("ERR_SIGNATORY_MISMATCH", 403,
                           "Counterparty has already signed")
        ra["counterparty_signed_at"] = iso_logical(now)

    # Determine new status
    if ra.get("landlord_signed_at") is not None and ra.get("counterparty_signed_at") is not None:
        ra["status"] = "FULLY_EXECUTED"
    else:
        ra["status"] = "PARTIALLY_SIGNED"
    touch(ra)

    # Cascade on full execution
    if ra["status"] == "FULLY_EXECUTED":
        # Hop 1: Transfer DOCUMENTED -> EFFECTIVE
        if transfer["status"] == "DOCUMENTED":
            transfer["status"] = "EFFECTIVE"
            transfer["effective_at"] = iso_logical(now)
            touch(transfer)
            decrement_lease_open_count(lease)
        # Hop 2: SubleaseAgreement EXECUTED -> RECOGNIZED (SUBLEASE only)
        sa = domain_get_sa(transfer["id"])
        if sa is not None and sa["status"] == "EXECUTED":
            sa["status"] = "RECOGNIZED"
            touch(sa)

    return ok(ra)


# ---------------------------------------------------------------------------
# Settlement — create
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/settlements")
def create_settlement():
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    body = parse_body({
        "lease_id": ("string", True, None),
        "transfer_request_id": ("string", True, None),
        "period_start": ("string", True, None),
        "period_end": ("string", True, None),
        "subrent_collected_cents": ("integer", True, None),
    }, allow_empty=False)

    # FK referential integrity (priority 4)
    lease = store.leases.get(body["lease_id"])
    if lease is None:
        raise ApiError("ERR_FK_MISMATCH", 422, "Referenced lease does not exist")
    transfer = store.transfer_requests.get(body["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_FK_MISMATCH", 422, "Referenced transfer does not exist")
    if transfer["lease_id"] != body["lease_id"]:
        raise ApiError("ERR_FK_MISMATCH", 422,
                       "Transfer does not belong to the referenced lease")

    # State (priority 5): transfer must be in CONSENT_GRANTED, DOCUMENTED, or EFFECTIVE
    if transfer["status"] not in ("CONSENT_GRANTED", "DEEMED_APPROVED", "DOCUMENTED", "EFFECTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Settlement creation requires transfer in CONSENT_GRANTED, DOCUMENTED, or EFFECTIVE")

    # If instrument exists, it must not be TERMINATED
    sa = domain_get_sa(transfer["id"])
    if sa is not None and sa["status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No settlements against a transfer with a TERMINATED instrument")

    # Temporal window (priority 7): period_end strictly after period_start
    period_start = parse_iso(body["period_start"])
    period_end = parse_iso(body["period_end"])
    if period_end <= period_start:
        raise ApiError("ERR_TEMPORAL_WINDOW", 422,
                       "period_end must be strictly after period_start")

    # Fiscal coherence (priority 10)
    if body["subrent_collected_cents"] < 0:
        raise ApiError("ERR_FISCAL_INCOHERENT", 422,
                       "subrent_collected_cents must be >= 0")

    # Compute derived fields
    measurement = get_settlement_measurement(transfer)
    if measurement is None:
        raise ApiError("ERR_PACKAGE_INCOMPLETE", 422,
                       "No certified measurement available for settlement math")

    fields = compute_settlement_fields(
        lease, measurement["rentable_sf"], measurement["is_partial_floor"],
        period_start, period_end, body["subrent_collected_cents"],
    )

    settlement = {
        "id": new_id(),
        "lease_id": body["lease_id"],
        "transfer_request_id": body["transfer_request_id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "subrent_collected_cents": body["subrent_collected_cents"],
        "passthrough_rent_cents": fields["passthrough_rent_cents"],
        "net_profit_cents": fields["net_profit_cents"],
        "landlord_share_cents": fields["landlord_share_cents"],
        "tenant_share_cents": fields["tenant_share_cents"],
        "status": "DRAFT",
        "finalized_at": None,
    }
    new_common(settlement)
    store.settlements[settlement["id"]] = settlement
    return created(settlement)


# ---------------------------------------------------------------------------
# Settlement — read
# ---------------------------------------------------------------------------

def _recompute_if_draft_settlement(settlement):
    """Return a copy with recomputed derived fields if DRAFT; otherwise as-is."""
    if settlement["status"] != "DRAFT":
        return settlement
    transfer = store.transfer_requests.get(settlement["transfer_request_id"])
    if transfer is None:
        return settlement
    lease = store.leases.get(settlement["lease_id"])
    if lease is None:
        return settlement
    measurement = get_settlement_measurement(transfer)
    if measurement is None:
        return settlement
    period_start = parse_iso(settlement["period_start"])
    period_end = parse_iso(settlement["period_end"])
    fields = compute_settlement_fields(
        lease, measurement["rentable_sf"], measurement["is_partial_floor"],
        period_start, period_end, settlement["subrent_collected_cents"],
    )
    result = dict(settlement)
    result.update(fields)
    return result


@bp.get("/sublease-admin/settlements/<settlement_id>")
def get_settlement(settlement_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    s = require_path_entity(store.settlements, settlement_id)
    return ok(_recompute_if_draft_settlement(s))


@bp.get("/sublease-admin/settlements")
def list_settlements():
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    rows = [_recompute_if_draft_settlement(s) for s in store.settlements.values()]
    for f in ("lease_id", "transfer_request_id", "status"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# Settlement — finalize
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/settlements/<settlement_id>/finalize")
def finalize_settlement(settlement_id):
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    settlement = require_path_entity(store.settlements, settlement_id)

    # State: settlement must be DRAFT
    if settlement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Finalize requires the settlement to be DRAFT")

    transfer = store.transfer_requests.get(settlement["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")
    lease = store.leases[settlement["lease_id"]]

    # Transfer must be EFFECTIVE
    if transfer["status"] != "EFFECTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Finalize requires the transfer to be EFFECTIVE")

    # Instrument must not be TERMINATED
    sa = domain_get_sa(transfer["id"])
    if sa is not None and sa["status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot finalize against a TERMINATED instrument")

    # Non-overlap with existing FINALIZED settlements for same transfer
    s_start = parse_iso(settlement["period_start"])
    s_end = parse_iso(settlement["period_end"])
    for other in store.settlements.values():
        if (other["id"] != settlement["id"]
                and other["transfer_request_id"] == settlement["transfer_request_id"]
                and other["status"] == "FINALIZED"):
            o_start = parse_iso(other["period_start"])
            o_end = parse_iso(other["period_end"])
            # Half-open overlap: [s_start, s_end) overlaps [o_start, o_end)
            if s_start < o_end and o_start < s_end:
                raise ApiError("ERR_DUPLICATE_ACTIVE", 409,
                               "Period overlaps an existing FINALIZED settlement")

    # Finalize: freeze fields, stamp, debit ledger
    now = db.LOGICAL_CLOCK
    settlement["status"] = "FINALIZED"
    settlement["finalized_at"] = iso_logical(now)
    touch(settlement)

    lease["cumulative_profit_share_cents"] = (
        lease.get("cumulative_profit_share_cents", 0) + settlement["landlord_share_cents"]
    )
    touch(lease)

    return ok(settlement)


# ---------------------------------------------------------------------------
# Settlement — void
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/settlements/<settlement_id>/void")
def void_settlement(settlement_id):
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    settlement = require_path_entity(store.settlements, settlement_id)

    if settlement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Void requires the settlement to be DRAFT")

    settlement["status"] = "VOID"
    touch(settlement)
    return ok(settlement)


# ---------------------------------------------------------------------------
# RestorationObligation — read
# ---------------------------------------------------------------------------

@bp.get("/sublease-admin/restoration-obligations/<ro_id>")
def get_restoration_obligation(ro_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    return ok(require_path_entity(store.restoration_obligations, ro_id))


# ---------------------------------------------------------------------------
# RestorationObligation — complete
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/restoration-obligations/<ro_id>/complete")
def complete_restoration_obligation(ro_id):
    uid, role, _ = get_context()
    require_roles(["Landlord"])
    ro = require_path_entity(store.restoration_obligations, ro_id)
    transfer = store.transfer_requests.get(ro["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")
    lease = store.leases[transfer["lease_id"]]

    # State: must be OPEN or ESCROW_POSTED
    if ro["status"] not in ("OPEN", "ESCROW_POSTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Complete requires the obligation to be OPEN or ESCROW_POSTED")

    # Identity: caller must be the lease's landlord
    if uid != lease["landlord_party_id"]:
        raise ApiError("ERR_DUTY_SEGREGATION", 403,
                       "Only the lease's landlord of record may complete restoration")

    # Gate for OPEN: responsible_party == TENANT or escrow == 0
    if ro["status"] == "OPEN":
        if ro["responsible_party"] != "TENANT" and ro.get("escrow_amount_cents", 0) > 0:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "OPEN obligation requires responsible_party TENANT or zero escrow")

    now = db.LOGICAL_CLOCK
    ro["status"] = "COMPLETED"
    ro["completed_at"] = iso_logical(now)
    touch(ro)
    return ok(ro)


# ---------------------------------------------------------------------------
# RestorationObligation — waive
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/restoration-obligations/<ro_id>/waive")
def waive_restoration_obligation(ro_id):
    uid, role, _ = get_context()
    require_roles(["Landlord"])
    ro = require_path_entity(store.restoration_obligations, ro_id)
    transfer = store.transfer_requests.get(ro["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")
    lease = store.leases[transfer["lease_id"]]

    # State: must be OPEN or ESCROW_POSTED
    if ro["status"] not in ("OPEN", "ESCROW_POSTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Waive requires the obligation to be OPEN or ESCROW_POSTED")

    # Identity: caller must be the lease's landlord
    if uid != lease["landlord_party_id"]:
        raise ApiError("ERR_DUTY_SEGREGATION", 403,
                       "Only the lease's landlord of record may waive restoration")

    ro["status"] = "WAIVED"
    touch(ro)
    return ok(ro)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/_clock/set_current_utc")
def set_clock():
    uid, role, _ = get_context()
    require_roles(["AssetManager"])
    body = parse_body({
        "to_iso8601": ("string", True, None),
    }, allow_empty=False)

    raw = body["to_iso8601"]
    parsed = raw
    if parsed.endswith("Z"):
        parsed = parsed[:-1] + "+00:00"
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(parsed)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    db.LOGICAL_CLOCK = dt.astimezone(timezone.utc)

    advanced = evaluate_deemed_approvals()

    return ok({
        "current_utc": iso_logical(db.LOGICAL_CLOCK),
        "advanced_transitions": advanced,
    })
