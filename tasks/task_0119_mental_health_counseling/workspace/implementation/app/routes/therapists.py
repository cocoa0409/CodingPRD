"""Therapist resource routes."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from flask import Blueprint, request

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_invalid_amount,
    err_no_active_license,
    err_not_found,
    err_supervision_incomplete,
    err_therapist_not_active,
    err_validation,
    err_invalid_state,
)
from ..helpers import (
    assert_bool,
    assert_enum,
    assert_integer,
    assert_string,
    new_uuid,
    occ_check,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.calculations import (
    REQUIRED_HOURS_FOR_LICENSURE,
    licensure_exam_eligible,
    to_decimal,
)
from ..services.cascades import (
    bump,
    hold_future_scheduled_for_therapist,
    unhold_appointments_for_therapist_license_gap,
)
from ..services.serialize import serialize_therapist
from ..store import store

bp = Blueprint("therapists", __name__, url_prefix="/practice/therapists")

SUPERVISION_TRACKS = ["PRE_LICENSED", "LICENSED"]
CREDENTIAL_STATUSES = ["PROVISIONAL", "ACTIVE", "SUSPENDED", "DEACTIVATED"]


# ---------------- Create ------------------------------------------------------

@bp.post("")
@require_roles("PracticeAdmin")
def create_therapist(**_):
    body = require_json_object()
    full_name = assert_string(body.get("full_name"), "full_name")
    npi = assert_string(body.get("npi"), "npi", pattern=r"^[0-9]{10}$")
    supervision_track = assert_enum(body.get("supervision_track"), "supervision_track", SUPERVISION_TRACKS)
    psypact_enrolled = assert_bool(body.get("psypact_enrolled"), "psypact_enrolled", required=False)
    if psypact_enrolled is None:
        psypact_enrolled = False

    # Fiscal validation precedes generic schema-type? Actually scaffold §1.4 priority 20 says
    # ERR_INVALID_AMOUNT precedes ERR_VALIDATION (priority 22). The integer assertion above
    # treats missing/typed-wrong as ERR_VALIDATION, then we check negativity as ERR_INVALID_AMOUNT.
    rack_91 = body.get("pricing_rack_90791_cents")
    rack_34 = body.get("pricing_rack_90834_cents")
    # presence/type → ERR_VALIDATION
    if rack_91 is None:
        raise err_validation("pricing_rack_90791_cents is required")
    if rack_34 is None:
        raise err_validation("pricing_rack_90834_cents is required")
    if isinstance(rack_91, bool) or not isinstance(rack_91, int):
        raise err_validation("pricing_rack_90791_cents must be an integer")
    if isinstance(rack_34, bool) or not isinstance(rack_34, int):
        raise err_validation("pricing_rack_90834_cents must be an integer")
    # value check → ERR_INVALID_AMOUNT (422)
    if rack_91 < 0 or rack_34 < 0:
        raise err_invalid_amount("rack rates must be >= 0")

    s = store()
    with s.lock:
        # NPI uniqueness within the practice.
        for t in s.therapists.values():
            if t["npi"] == npi:
                raise err_validation("npi must be unique within the practice")

        tid = new_uuid()
        ts = now()
        row: dict[str, Any] = {
            "id": tid,
            "full_name": full_name,
            "npi": npi,
            "credential_status": "PROVISIONAL",
            "supervision_track": supervision_track,
            "supervision_hours_accrued": Decimal("0.00"),
            "licensure_exam_eligible": False,
            "psypact_enrolled": bool(psypact_enrolled),
            "pricing_rack_90791_cents": rack_91,
            "pricing_rack_90834_cents": rack_34,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.therapists[tid] = row
        return created(serialize_therapist(row))


# ---------------- Read --------------------------------------------------------

@bp.get("/<tid>")
@require_roles("PracticeAdmin", "Therapist", "Supervisor", "BillingClerk")
def get_therapist(tid: str, **_):
    s = store()
    row = s.therapists.get(tid)
    if row is None:
        raise err_not_found("Therapist not found")
    return ok(serialize_therapist(row))


# ---------------- List --------------------------------------------------------

@bp.get("")
@require_roles("PracticeAdmin", "BillingClerk")
def list_therapists(**_):
    limit, offset = parse_pagination()
    cred = request.args.get("credential_status")
    if cred is not None and cred not in CREDENTIAL_STATUSES:
        raise err_validation("credential_status filter invalid")
    track = request.args.get("supervision_track")
    if track is not None and track not in SUPERVISION_TRACKS:
        raise err_validation("supervision_track filter invalid")

    s = store()
    rows = [r for r in s.therapists.values()
            if (cred is None or r["credential_status"] == cred)
            and (track is None or r["supervision_track"] == track)]
    rows.sort(key=lambda r: r["created_at"])
    return listing([serialize_therapist(r) for r in paginate(rows, limit, offset)],
                   total_count=len(rows), limit=limit, offset=offset)


# ---------------- PATCH -------------------------------------------------------

@bp.patch("/<tid>")
@require_roles("PracticeAdmin")
def update_therapist(tid: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        row = s.therapists.get(tid)
        if row is None:
            raise err_not_found("Therapist not found")

        occ_check(body.get("version"), row["version"])

        # Validate rack rates if supplied (ERR_INVALID_AMOUNT preempts ERR_VALIDATION).
        if "pricing_rack_90791_cents" in body:
            v = body["pricing_rack_90791_cents"]
            if isinstance(v, bool) or not isinstance(v, int):
                raise err_validation("pricing_rack_90791_cents must be an integer")
            if v < 0:
                raise err_invalid_amount("pricing_rack_90791_cents must be >= 0")
            row["pricing_rack_90791_cents"] = v
        if "pricing_rack_90834_cents" in body:
            v = body["pricing_rack_90834_cents"]
            if isinstance(v, bool) or not isinstance(v, int):
                raise err_validation("pricing_rack_90834_cents must be an integer")
            if v < 0:
                raise err_invalid_amount("pricing_rack_90834_cents must be >= 0")
            row["pricing_rack_90834_cents"] = v
        if "psypact_enrolled" in body:
            v = body["psypact_enrolled"]
            if not isinstance(v, bool):
                raise err_validation("psypact_enrolled must be a boolean")
            row["psypact_enrolled"] = v

        bump(row)
        return ok(serialize_therapist(row))


# ---------------- State-machine transitions ----------------------------------

def _has_active_assignment(s, tid: str) -> bool:
    return any(
        a["therapist_id"] == tid and a["status"] == "ACTIVE"
        for a in s.supervision_assignments.values()
    )


def _has_active_license(s, tid: str) -> bool:
    return any(
        l["therapist_id"] == tid and l["status"] == "ACTIVE"
        for l in s.state_licenses.values()
    )


def _activate_common(row: dict[str, Any], s):
    """Shared activation logic. Returns the mutated row."""
    # Therapist must not already be DEACTIVATED (terminal).
    cur = row["credential_status"]
    if cur not in {"PROVISIONAL", "SUSPENDED"}:
        raise err_invalid_state(f"Therapist in state {cur} cannot be activated")

    # Active-license requirement.
    if not _has_active_license(s, row["id"]):
        raise err_no_active_license()
    # PRE_LICENSED requires supervision_hours >= 3000 AND active assignment.
    if row["supervision_track"] == "PRE_LICENSED":
        accrued = to_decimal(row["supervision_hours_accrued"])
        if accrued < REQUIRED_HOURS_FOR_LICENSURE or not _has_active_assignment(s, row["id"]):
            raise err_supervision_incomplete()

    row["credential_status"] = "ACTIVE"
    row["licensure_exam_eligible"] = licensure_exam_eligible(
        row["supervision_hours_accrued"], "ACTIVE"
    )
    bump(row)
    # Reactivation cascade: unhold appointments held due to LICENSE_GAP for this therapist.
    unhold_appointments_for_therapist_license_gap(s, row["id"])
    return row


@bp.post("/<tid>/activate")
@require_roles("PracticeAdmin")
def activate_therapist(tid: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        row = s.therapists.get(tid)
        if row is None:
            raise err_not_found("Therapist not found")
        occ_check(body.get("version"), row["version"])
        _activate_common(row, s)
        return ok(serialize_therapist(row))


@bp.post("/<tid>/reinstate")
@require_roles("PracticeAdmin")
def reinstate_therapist(tid: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        row = s.therapists.get(tid)
        if row is None:
            raise err_not_found("Therapist not found")
        occ_check(body.get("version"), row["version"])
        # Reinstate is specifically SUSPENDED→ACTIVE (the activate alias).
        if row["credential_status"] != "SUSPENDED":
            raise err_invalid_state("Only SUSPENDED therapists may be reinstated")
        if not _has_active_license(s, row["id"]):
            raise err_no_active_license()
        # PRE_LICENSED requirement applies on activate; reinstate carries the same constraints
        # since it transitions into ACTIVE. PRD §3.2 keeps the precondition list shorter for
        # reinstate (only ACTIVE-license requirement), so we do not impose supervision here.
        row["credential_status"] = "ACTIVE"
        row["licensure_exam_eligible"] = licensure_exam_eligible(
            row["supervision_hours_accrued"], "ACTIVE"
        )
        bump(row)
        unhold_appointments_for_therapist_license_gap(s, row["id"])
        return ok(serialize_therapist(row))


@bp.post("/<tid>/suspend")
@require_roles("PracticeAdmin")
def suspend_therapist(tid: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        row = s.therapists.get(tid)
        if row is None:
            raise err_not_found("Therapist not found")
        occ_check(body.get("version"), row["version"])
        if row["credential_status"] != "ACTIVE":
            raise err_invalid_state("Only ACTIVE therapists may be suspended")
        row["credential_status"] = "SUSPENDED"
        row["licensure_exam_eligible"] = licensure_exam_eligible(
            row["supervision_hours_accrued"], "SUSPENDED"
        )
        bump(row)
        # Cascade: future SCHEDULED appointments → HELD/LICENSE_GAP.
        hold_future_scheduled_for_therapist(s, row["id"], "LICENSE_GAP")
        return ok(serialize_therapist(row))


@bp.post("/<tid>/deactivate")
@require_roles("PracticeAdmin")
def deactivate_therapist(tid: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        row = s.therapists.get(tid)
        if row is None:
            raise err_not_found("Therapist not found")
        occ_check(body.get("version"), row["version"])
        if row["credential_status"] not in {"ACTIVE", "SUSPENDED"}:
            raise err_invalid_state("Therapist cannot be deactivated from this state")
        # No SCHEDULED/HELD/CHECKED_IN appointments may exist.
        blocking_states = {"SCHEDULED", "HELD", "CHECKED_IN"}
        for appt in s.appointments.values():
            if appt["therapist_id"] == tid and appt["status"] in blocking_states:
                raise err_invalid_state(
                    "Cannot deactivate: therapist has open appointments (SCHEDULED/HELD/CHECKED_IN)"
                )
        row["credential_status"] = "DEACTIVATED"
        row["licensure_exam_eligible"] = licensure_exam_eligible(
            row["supervision_hours_accrued"], "DEACTIVATED"
        )
        bump(row)
        return ok(serialize_therapist(row))
