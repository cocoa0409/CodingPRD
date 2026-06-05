"""Lease routes (scaffold §1.5 — Leases block; PRD §3.4, §3.5, §3.8).

The lease aggregate carries the most complex behaviour in the system:

  * POST /leases enforces the priority-ordered validation ladder culminating
    in the OCC parent-version pin (PRD §2.6 / §2.7) and creates a RESERVED
    lease + a RESERVED slip, with the slip's version advancing.
  * POST /leases/{id}/check-in pins nightly_rate_cents and total_cost_cents
    via the seasonal/aggregation calculations (PRD §3.5) and cascades the
    slip into OCCUPIED.
  * POST /leases/{id}/check-out is the three-hop cascade in PRD §3.8 —
    lease ENDED, optional marina counter decrement, optional waitlist
    promotion and slip transition.
  * POST /leases/{id}/cancel is the lightweight RESERVED -> CANCELLED move.
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INSURANCE_INVALID,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LIVEABOARD_NOT_ALLOWED,
    ERR_SLIP_DATE_CONFLICT,
    ERR_SLIP_SIZE_MISMATCH,
    ERR_STALE_VERSION,
    ERR_VESSEL_TENANT_MISMATCH,
)
from middleware import current_user_id, get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.calculations import (
    MIN_INSURANCE_COVERAGE_CENTS,
    insurance_valid,
    lease_total_cost,
    seasonal_lease_pricing,
)
from services.cascades import promote_waitlist_head
from services.validation import (
    lookup_or_404,
    require_bool,
    require_date,
    require_fields,
    require_int,
)


bp = Blueprint("leases", __name__)


LEASE_STATUSES = {"RESERVED", "ACTIVE", "ENDED", "CANCELLED"}


@bp.post("/leases")
def create_lease():
    """Tenant reserves a slip.

    Validation priority order (PRD §2.7 / scaffold §1.4):
      1. auth (require_auth)
      2. existence (path FKs: marina/slip/tenant/vessel via lookup_or_404)
      3. state — Slip.status == AVAILABLE
      4. OCC — expected_slip_version == slip.version
      5. liveaboard policy (if is_liveaboard)
      6. slip size match (vessel <= slip)
      7. date-range overlap on existing RESERVED/ACTIVE leases
      8. start_date < end_date
      9. vessel.tenant_id == lease.tenant_id
    """
    require_auth(["Tenant"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "marina_id",
            "slip_id",
            "tenant_id",
            "vessel_id",
            "start_date",
            "end_date",
            "expected_slip_version",
        ],
    )
    marina = lookup_or_404(db.marinas, body["marina_id"], "Marina")
    slip = lookup_or_404(db.slips, body["slip_id"], "Slip")
    tenant = lookup_or_404(db.tenants, body["tenant_id"], "Tenant")
    vessel = lookup_or_404(db.vessels, body["vessel_id"], "Vessel")

    # body schema parsing — pure type checks belong to the lowest priority
    # bucket, but we need typed values to evaluate the higher-priority checks
    # that come next. Parse here without escalating beyond ERR_INVALID_REQUEST.
    start_date = require_date(body["start_date"], "start_date")
    end_date = require_date(body["end_date"], "end_date")
    expected_slip_version = require_int(
        body["expected_slip_version"], "expected_slip_version", min_value=1
    )
    is_liveaboard_raw = body.get("is_liveaboard", False)
    if is_liveaboard_raw is None:
        is_liveaboard_raw = False
    is_liveaboard = require_bool(is_liveaboard_raw, "is_liveaboard")

    # Cross-resource sanity: the slip must live in the marina referenced in
    # the body. This is an existence-layer check (the referenced (marina, slip)
    # pair has to resolve), so a mismatch surfaces as ERR_NOT_FOUND per
    # PRD §2.5.
    if slip.get("marina_id") != marina["id"]:
        from errors import ERR_NOT_FOUND
        raise APIError(ERR_NOT_FOUND, 404, "slip does not belong to marina")

    with db.mutation_lock:
        # Priority 4 (state): Slip.status == AVAILABLE.
        if slip.get("status") != "AVAILABLE":
            raise APIError(
                ERR_INVALID_STATE, 409, "Slip must be AVAILABLE to reserve"
            )

        # Priority 5 (OCC): expected_slip_version equals current Slip.version.
        if slip.get("version") != expected_slip_version:
            raise APIError(
                ERR_STALE_VERSION,
                412,
                "Slip.version has advanced past expected_slip_version",
            )

        # Priority 6 (insurance) does not apply at create — applies at
        # check-in only per PRD §3.5.

        # Priority 7 (liveaboard policy) — only if is_liveaboard true.
        if is_liveaboard:
            if not slip.get("liveaboard_allowed", False):
                raise APIError(
                    ERR_LIVEABOARD_NOT_ALLOWED,
                    422,
                    "Slip does not permit liveaboard",
                )
            if tenant.get("liveaboard_status") != "APPROVED":
                raise APIError(
                    ERR_LIVEABOARD_NOT_ALLOWED,
                    422,
                    "Tenant.liveaboard_status must be APPROVED",
                )

        # Priority 8 (slip size matching).
        if vessel.get("loa_ft", 0) > slip.get("length_ft", 0) or vessel.get(
            "beam_ft", 0
        ) > slip.get("beam_ft", 0):
            raise APIError(
                ERR_SLIP_SIZE_MISMATCH,
                422,
                "Vessel size exceeds slip dimensions",
            )

        # Priority 9 (date-range overlap on same slip, half-open interval).
        # Day-exact adjacency (next.start == prev.end) does NOT collide.
        for lease in db.leases.values():
            if lease.get("slip_id") != slip["id"]:
                continue
            if lease.get("status") not in ("RESERVED", "ACTIVE"):
                continue
            other_start = db.parse_iso_date(lease.get("start_date"))
            other_end = db.parse_iso_date(lease.get("end_date"))
            if other_start is None or other_end is None:
                continue
            # half-open [a, b) intersects [c, d) iff a < d AND c < b
            if start_date < other_end and other_start < end_date:
                raise APIError(
                    ERR_SLIP_DATE_CONFLICT,
                    409,
                    "Requested lease window overlaps an existing lease",
                )

        # Priority 10 (date-range sanity).
        if not (start_date < end_date):
            raise APIError(
                ERR_INVALID_DATE_RANGE,
                422,
                "start_date must be strictly before end_date",
            )

        # Priority 12 (vessel/tenant referential match).
        if vessel.get("tenant_id") != tenant["id"]:
            raise APIError(
                ERR_VESSEL_TENANT_MISMATCH,
                422,
                "Vessel.tenant_id does not match Lease.tenant_id",
            )

        # All gates passed — create lease in RESERVED, advance slip.
        lease = {
            "marina_id": marina["id"],
            "slip_id": slip["id"],
            "tenant_id": tenant["id"],
            "vessel_id": vessel["id"],
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "is_liveaboard": is_liveaboard,
            "nightly_rate_cents": 0,
            "total_cost_cents": 0,
            "status": "RESERVED",
            # The OCC field is part of the body schema but per scaffold the
            # server validates and discards rather than persisting it. We omit
            # it from the persisted record.
        }
        db.stamp_common(lease)
        db.leases[lease["id"]] = lease

        slip["status"] = "RESERVED"
        db.bump(slip)
        return ok_object(lease, 201)


@bp.get("/leases")
def list_leases():
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    limit, offset = paginate_params(request.args)
    items = list(db.leases.values())
    for key in ("tenant_id", "slip_id", "marina_id", "vessel_id", "status"):
        if key in request.args:
            val = request.args[key]
            items = [l for l in items if l.get(key) == val]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/leases/<lid>")
def get_lease(lid: str):
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    lease = lookup_or_404(db.leases, lid, "Lease")
    return ok_object(lease, 200)


@bp.post("/leases/<lid>/check-in")
def check_in_lease(lid: str):
    require_auth(["MarinaStaff", "HarborMaster"])()
    lease = lookup_or_404(db.leases, lid, "Lease")

    with db.mutation_lock:
        # State preconditions: slip RESERVED, lease RESERVED, current clock
        # date on or after start_date.
        slip = db.slips.get(lease.get("slip_id"))
        if slip is None or slip.get("status") != "RESERVED":
            raise APIError(
                ERR_INVALID_STATE, 409, "Slip must be RESERVED to check in"
            )
        if lease.get("status") != "RESERVED":
            raise APIError(
                ERR_INVALID_STATE, 409, "Lease must be RESERVED to check in"
            )
        today_utc = db.now_logical_date()
        start_date = db.parse_iso_date(lease.get("start_date"))
        if start_date is None or today_utc < start_date:
            raise APIError(
                ERR_INVALID_STATE,
                409,
                "Current clock date is before Lease.start_date",
            )

        # Insurance gate (priority 6).
        vessel = db.vessels.get(lease.get("vessel_id"))
        if vessel is None or not insurance_valid(vessel, today_utc):
            raise APIError(
                ERR_INSURANCE_INVALID,
                422,
                "Vessel insurance is not valid for check-in",
            )

        # Liveaboard policy (priority 7) — re-checked at check-in.
        tenant = db.tenants.get(lease.get("tenant_id"))
        if lease.get("is_liveaboard"):
            if not slip.get("liveaboard_allowed", False):
                raise APIError(
                    ERR_LIVEABOARD_NOT_ALLOWED,
                    422,
                    "Slip does not permit liveaboard",
                )
            if tenant is None or tenant.get("liveaboard_status") != "APPROVED":
                raise APIError(
                    ERR_LIVEABOARD_NOT_ALLOWED,
                    422,
                    "Tenant.liveaboard_status must be APPROVED",
                )

        # Size matching (priority 8) — re-checked at check-in.
        if vessel.get("loa_ft", 0) > slip.get("length_ft", 0) or vessel.get(
            "beam_ft", 0
        ) > slip.get("beam_ft", 0):
            raise APIError(
                ERR_SLIP_SIZE_MISMATCH,
                422,
                "Vessel size exceeds slip dimensions",
            )

        # Pin nightly_rate_cents per seasonal_lease_pricing.
        marina = db.marinas.get(lease.get("marina_id"))
        if marina is None:
            from errors import ERR_NOT_FOUND
            raise APIError(ERR_NOT_FOUND, 404, "Marina not found for lease")
        summer_start = db.parse_mmdd(marina.get("season_summer_start"))
        summer_end = db.parse_mmdd(marina.get("season_summer_end"))
        nightly = seasonal_lease_pricing(
            slip.get("base_daily_rate_cents", 0),
            bool(lease.get("is_liveaboard")),
            start_date,
            summer_start,
            summer_end,
        )
        end_date = db.parse_iso_date(lease.get("end_date"))
        nights = (end_date - start_date).days
        total = lease_total_cost(
            nights, nightly, bool(lease.get("is_liveaboard"))
        )

        lease["nightly_rate_cents"] = nightly
        lease["total_cost_cents"] = total
        lease["status"] = "ACTIVE"
        db.bump(lease)

        slip["status"] = "OCCUPIED"
        db.bump(slip)
        return ok_object(lease, 200)


@bp.post("/leases/<lid>/check-out")
def check_out_lease(lid: str):
    require_auth(["MarinaStaff", "HarborMaster"])()
    lease = lookup_or_404(db.leases, lid, "Lease")
    with db.mutation_lock:
        slip = db.slips.get(lease.get("slip_id"))
        if slip is None or slip.get("status") != "OCCUPIED":
            raise APIError(
                ERR_INVALID_STATE, 409, "Slip must be OCCUPIED to check out"
            )
        if lease.get("status") != "ACTIVE":
            raise APIError(
                ERR_INVALID_STATE, 409, "Lease must be ACTIVE to check out"
            )
        # Hop 1: lease ENDED.
        lease["status"] = "ENDED"
        db.bump(lease)
        # Hop 2: marina liveaboard counter decrement if applicable.
        if lease.get("is_liveaboard"):
            marina = db.marinas.get(lease.get("marina_id"))
            if marina is not None:
                marina["liveaboard_current_count"] = max(
                    0, marina.get("liveaboard_current_count", 0) - 1
                )
                db.bump(marina)
        # Hop 3: waitlist head promotion (or plain AVAILABLE if no head).
        promote_waitlist_head(slip)
        db.bump(slip)
        return ok_object(lease, 200)


@bp.post("/leases/<lid>/cancel")
def cancel_lease(lid: str):
    require_auth(["Tenant"])()
    lease = lookup_or_404(db.leases, lid, "Lease")
    with db.mutation_lock:
        slip = db.slips.get(lease.get("slip_id"))
        if slip is None or slip.get("status") != "RESERVED":
            raise APIError(
                ERR_INVALID_STATE, 409, "Slip must be RESERVED to cancel"
            )
        if lease.get("status") != "RESERVED":
            raise APIError(
                ERR_INVALID_STATE, 409, "Lease must be RESERVED to cancel"
            )
        lease["status"] = "CANCELLED"
        db.bump(lease)
        slip["status"] = "AVAILABLE"
        db.bump(slip)
        return ok_object(lease, 200)
