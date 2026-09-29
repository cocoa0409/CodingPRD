"""The lease lifecycle: drafting, amendment, withdrawal, fair-market-value
review, execution, commencement, termination and after-hours access
(PRD Sections 3.3, 3.4 and 3.5)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import enums
import serializers as ser
import validators as v
from db import by_creation, clock_date, db, stamp_new, touch
from errors import ApiError, bad_request
from lookups import get_building, get_lease, get_suite, get_tenant, paged
from middleware import acting_user_id, endpoint, is_portal_user, require_tenant_scope
from response import object_response
from services import calc, cascades
from services.compliance import open_fmv_deviation_case

bp = Blueprint("leases", __name__)

MATERIAL_FIELDS = ("base_rent_psf_annual", "term_start", "term_end", "exclusive_use_specialty")
REVISION_ROUND_CAP = 2


# ----------------------------------------------------------------- guards


def _frozen_guard(building):
    """Ladder rung 16 — a freeze halts every leasing-lifecycle write."""
    if building["tenant_mix_posture"] == "FROZEN":
        raise ApiError(
            "ERR_BUILDING_MIX_FROZEN",
            "Building '%s' has a FROZEN tenant mix posture." % building["id"],
        )


def _lease_state_guard(lease, allowed):
    """Ladder rung 13."""
    if lease["status"] not in allowed:
        raise ApiError(
            "ERR_INVALID_LEASE_STATE",
            "Lease '%s' is in status %s; expected one of %s."
            % (lease["id"], lease["status"], ", ".join(allowed)),
        )


def _open_lease_guard(lease):
    """Rung 13 for the 'any status other than TERMINATED or WITHDRAWN' family."""
    if lease["status"] in calc.CLOSED_LEASE_STATUSES:
        raise ApiError(
            "ERR_INVALID_LEASE_STATE",
            "Lease '%s' has reached %s." % (lease["id"], lease["status"]),
        )


def _master_type_guard(lease_type, master):
    """Ladder rung 26 at draft and at review submission: a SUBLEASE must name a
    master whose own lease_type is MASTER."""
    if lease_type != "SUBLEASE":
        return
    if master is None or master["lease_type"] != "MASTER":
        raise ApiError(
            "ERR_MASTER_LEASE_NOT_ACTIVE",
            "A SUBLEASE must name a master lease whose lease_type is MASTER.",
        )


def _min_term_guard(term_start, term_end):
    """Ladder rung 30."""
    months = calc.term_months(term_start, term_end)
    if months < calc.MIN_TERM_MONTHS:
        raise ApiError(
            "ERR_MIN_TERM_NOT_MET",
            "Derived term_months is %d; the minimum term is %d months."
            % (months, calc.MIN_TERM_MONTHS),
        )
    return months


def _sublease_term_guard(lease_type, master, term_start, term_end):
    """Ladder rung 31 — the sublease term must sit inside the master's term."""
    if lease_type != "SUBLEASE" or master is None:
        return
    if term_start < master["term_start"] or term_end > master["term_end"]:
        raise ApiError(
            "ERR_SUBLEASE_TERM_EXCEEDS_MASTER",
            "The sublease term must lie within master lease '%s'." % master["id"],
        )


def _exclusive_use_conflict(lease, tenant):
    """Ladder rung 23 — one-directional: an incumbent's exclusive blocks an
    entrant of that specialty, never the reverse."""
    for other in by_creation(list(db.leases.values())):
        if other["id"] == lease["id"]:
            continue
        if other["building_id"] != lease["building_id"]:
            continue
        if other["status"] not in calc.OCCUPYING_LEASE_STATUSES:
            continue
        if other["exclusive_use_specialty"] == tenant["primary_specialty"]:
            raise ApiError(
                "ERR_EXCLUSIVE_USE_CONFLICT",
                "Lease '%s' holds an exclusive over %s in this building."
                % (other["id"], tenant["primary_specialty"]),
            )


def _radius_conflict(lease, tenant):
    """Ladder rung 24 — a radius_restriction_miles of 0 disables the
    restriction on the lease that declares it."""
    for other in by_creation(list(db.leases.values())):
        if other["id"] == lease["id"]:
            continue
        if other["building_id"] != lease["building_id"]:
            continue
        if other["status"] not in calc.OCCUPYING_LEASE_STATUSES:
            continue
        miles = other["radius_restriction_miles"]
        if miles is None or miles <= 0:
            continue
        if db.tenants[other["tenant_id"]]["primary_specialty"] == tenant["primary_specialty"]:
            raise ApiError(
                "ERR_RADIUS_RESTRICTION_CONFLICT",
                "Lease '%s' carries a radius restriction over %s in this building."
                % (other["id"], tenant["primary_specialty"]),
            )


def _qualifying_appraisal_guard(lease, tenant):
    """Ladder rung 40 — only physician-owned tenants need a live opinion."""
    if not tenant["is_physician_owned"]:
        return None
    controlling = calc.controlling_appraisal(lease["id"])
    if controlling is None:
        raise ApiError(
            "ERR_NO_QUALIFYING_APPRAISAL",
            "Lease '%s' has no QUALIFIED appraisal that is still valid at the clock date."
            % lease["id"],
        )
    return controlling


def _occ_check(expected, lease):
    """Ladder rung 10. The field itself is parsed during the rung-3 pass so that
    a malformed version still outranks a missing lease."""
    if expected != lease["version"]:
        raise ApiError(
            "ERR_STALE_LEASE_VERSION",
            "expected_lease_version %d does not match the lease's current version %d."
            % (expected, lease["version"]),
        )


# ------------------------------------------------------------ draft + read


@bp.post("/leases")
@endpoint("LeasingAgent")
def create_lease():
    body = v.json_body()
    building_id = v.get_string(body, "building_id")
    suite_id = v.get_string(body, "suite_id")
    tenant_id = v.get_string(body, "tenant_id")
    lease_type = v.get_enum(body, "lease_type", enums.LEASE_TYPES)
    master_lease_id = v.get_string(body, "master_lease_id", required=False)
    term_start = v.get_date(body, "term_start")
    term_end = v.get_date(body, "term_end")
    if term_end <= term_start:
        raise bad_request("Field 'term_end' must be strictly later than 'term_start'.")
    base_rent_psf = v.get_money(body, "base_rent_psf_annual", allow_zero=False)
    exclusive = v.get_enum(body, "exclusive_use_specialty", enums.SPECIALTIES, required=False)
    radius = v.get_money(body, "radius_restriction_miles", required=False, default=Decimal("0.00"))
    if lease_type != "SUBLEASE" and master_lease_id is not None:
        raise bad_request(
            "Field 'master_lease_id' must be null for a %s lease." % lease_type
        )

    building = get_building(building_id)
    suite = get_suite(suite_id, building)
    tenant = get_tenant(tenant_id)
    master = get_lease(master_lease_id) if master_lease_id is not None else None

    _frozen_guard(building)
    _master_type_guard(lease_type, master)
    months = _min_term_guard(term_start, term_end)
    _sublease_term_guard(lease_type, master, term_start, term_end)

    row = {
        "building_id": building["id"],
        "suite_id": suite["id"],
        "tenant_id": tenant["id"],
        "lease_type": lease_type,
        "master_lease_id": master["id"] if master is not None else None,
        "status": "DRAFT",
        "term_start": term_start,
        "term_end": term_end,
        "term_months": months,
        "base_rent_psf_annual": base_rent_psf,
        "provisional_base_rent_annual": None,
        "certified_base_rent_annual": None,
        "effective_base_rent_annual": None,
        "fmv_certification_status": "NOT_STARTED",
        "certified_fmv_floor_psf": None,
        "certified_fmv_ceiling_psf": None,
        "fmv_variance_annual": None,
        "fmv_variance_pct": None,
        "fmv_submitted_by_user_id": None,
        "exclusive_use_specialty": exclusive,
        "radius_restriction_miles": radius,
        "signed_lease_on_file": False,
        "master_lease_consent_on_file": False,
        "space_sharing_schedule_on_file": False,
        "after_hours_authorized": False,
        "rent_concession_locked": False,
        "holdover_premium_applied": False,
        "revision_round": 0,
        "termination_reason": None,
        "terminated_on": None,
    }
    calc.recompute_provisional_rent(row)
    calc.apply_rent_variant(row)
    stamp_new(row)
    db.leases[row["id"]] = row
    return object_response(ser.lease_out(row), 201)


@bp.get("/leases/<lease_id>")
@endpoint()
def read_lease(lease_id):
    lease = get_lease(lease_id)
    require_tenant_scope(lease["tenant_id"])
    return object_response(ser.lease_out(lease))


@bp.get("/leases")
@endpoint()
def list_leases():
    limit, offset = v.pagination()
    building_id = v.query_string("building_id")
    suite_id = v.query_string("suite_id")
    tenant_id = v.query_string("tenant_id")
    master_lease_id = v.query_string("master_lease_id")
    status = v.query_enum("status", enums.LEASE_STATUSES)
    lease_type = v.query_enum("lease_type", enums.LEASE_TYPES)

    rows = by_creation(list(db.leases.values()))
    if is_portal_user():
        rows = [l for l in rows if l["tenant_id"] == acting_user_id()]
    if building_id is not None:
        rows = [l for l in rows if l["building_id"] == building_id]
    if suite_id is not None:
        rows = [l for l in rows if l["suite_id"] == suite_id]
    if tenant_id is not None:
        rows = [l for l in rows if l["tenant_id"] == tenant_id]
    if master_lease_id is not None:
        rows = [l for l in rows if l["master_lease_id"] == master_lease_id]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    if lease_type is not None:
        rows = [l for l in rows if l["lease_type"] == lease_type]
    return paged(rows, ser.lease_out, limit, offset)


# --------------------------------------------------------------- amendment


@bp.patch("/leases/<lease_id>")
@endpoint("LeasingAgent")
def amend_lease(lease_id):
    body = v.json_body()
    expected = v.get_int(body, "expected_lease_version", minimum=0)
    new_rent = v.get_money(body, "base_rent_psf_annual", required=False, allow_zero=False)
    new_start = v.get_date(body, "term_start", required=False)
    new_end = v.get_date(body, "term_end", required=False)
    exclusive_given = "exclusive_use_specialty" in body
    new_exclusive = v.get_enum(
        body, "exclusive_use_specialty", enums.SPECIALTIES, required=False
    )
    radius_given = "radius_restriction_miles" in body
    new_radius = v.get_money(body, "radius_restriction_miles", required=False)

    lease = get_lease(lease_id)
    _occ_check(expected, lease)
    _lease_state_guard(lease, ("DRAFT", "FMV_CERTIFIED"))

    term_start = new_start if new_start is not None else lease["term_start"]
    term_end = new_end if new_end is not None else lease["term_end"]
    if term_end <= term_start:
        raise bad_request("Field 'term_end' must be strictly later than 'term_start'.")

    building = db.buildings[lease["building_id"]]
    _frozen_guard(building)

    material = (
        new_rent is not None
        or new_start is not None
        or new_end is not None
        or exclusive_given
    )
    # Rung 17 bites only where the amendment would actually advance the counter,
    # which is the FMV_CERTIFIED -> DRAFT material edge (PRD Section 3.3).
    if material and lease["status"] == "FMV_CERTIFIED" and lease["revision_round"] > 1:
        raise ApiError(
            "ERR_REVISION_LIMIT_EXCEEDED",
            "Lease '%s' has already used revision round %d of a cap of %d."
            % (lease["id"], lease["revision_round"], REVISION_ROUND_CAP),
        )

    if (
        lease["rent_concession_locked"]
        and new_rent is not None
        and new_rent < lease["base_rent_psf_annual"]
    ):
        raise ApiError(
            "ERR_RENT_CONCESSION_LOCKED",
            "Lease '%s' has rent_concession_locked set; base_rent_psf_annual may not be lowered."
            % lease["id"],
        )

    if new_start is not None or new_end is not None:
        _min_term_guard(term_start, term_end)
        master = db.leases.get(lease["master_lease_id"]) if lease["master_lease_id"] else None
        _sublease_term_guard(lease["lease_type"], master, term_start, term_end)

    # --- apply ------------------------------------------------------------
    term_or_rent_changed = (
        new_rent is not None or new_start is not None or new_end is not None
    )
    if new_rent is not None:
        lease["base_rent_psf_annual"] = new_rent
    if new_start is not None:
        lease["term_start"] = new_start
    if new_end is not None:
        lease["term_end"] = new_end
    if new_start is not None or new_end is not None:
        lease["term_months"] = calc.term_months(lease["term_start"], lease["term_end"])
    if exclusive_given:
        lease["exclusive_use_specialty"] = new_exclusive
    if radius_given:
        lease["radius_restriction_miles"] = new_radius

    if material and lease["status"] == "FMV_CERTIFIED":
        lease["status"] = "DRAFT"
        lease["fmv_certification_status"] = "STALE"
        lease["certified_fmv_floor_psf"] = None
        lease["certified_fmv_ceiling_psf"] = None
        lease["certified_base_rent_annual"] = None
        lease["fmv_variance_annual"] = None
        lease["fmv_variance_pct"] = None
        for appraisal in calc.appraisals_of_lease(lease["id"]):
            if appraisal["is_controlling"]:
                appraisal["is_controlling"] = False
                touch(appraisal)
        lease["revision_round"] += 1
        calc.recompute_provisional_rent(lease)
        calc.apply_rent_variant(lease)
    elif term_or_rent_changed:
        # PRD Section 3.3: term_months and the provisional rent are re-derived.
        calc.recompute_provisional_rent(lease)
        calc.apply_rent_variant(lease)

    touch(lease)
    return object_response(ser.lease_out(lease))


@bp.delete("/leases/<lease_id>")
@endpoint("LeasingAgent")
def withdraw_lease(lease_id):
    lease = get_lease(lease_id)
    _lease_state_guard(lease, ("DRAFT",))
    for project in calc.projects_of_lease(lease["id"]):
        if project["status"] != "CANCELLED":
            raise ApiError(
                "ERR_TI_PROJECT_NOT_COMPLETE",
                "Tenant-improvement project '%s' survives in status %s."
                % (project["id"], project["status"]),
            )

    for appraisal in calc.appraisals_of_lease(lease["id"]):
        if appraisal["status"] in ("SUBMITTED", "QUALIFIED"):
            appraisal["status"] = "DISQUALIFIED"
            appraisal["decision_reason"] = "lease withdrawn"
            touch(appraisal)
    lease["status"] = "WITHDRAWN"
    touch(lease)
    return object_response(ser.lease_out(lease))


# ------------------------------------------------- review and certification


@bp.post("/leases/<lease_id>/submit-fmv-review")
@endpoint("LeasingAgent")
def submit_fmv_review(lease_id):
    body = v.json_body()
    v.get_string(body, "submission_note", required=False, allow_empty=True)

    lease = get_lease(lease_id)
    _lease_state_guard(lease, ("DRAFT",))
    building = db.buildings[lease["building_id"]]
    _frozen_guard(building)
    master = db.leases.get(lease["master_lease_id"]) if lease["master_lease_id"] else None
    _master_type_guard(lease["lease_type"], master)
    _min_term_guard(lease["term_start"], lease["term_end"])
    _sublease_term_guard(lease["lease_type"], master, lease["term_start"], lease["term_end"])
    tenant = db.tenants[lease["tenant_id"]]
    _qualifying_appraisal_guard(lease, tenant)

    lease["status"] = "PENDING_FMV_REVIEW"
    lease["fmv_certification_status"] = "PENDING"
    lease["fmv_submitted_by_user_id"] = acting_user_id()
    # The provisional figure is frozen here at the rate card as it stands, and
    # is deliberately not recomputed at certification (PRD Section 3.4).
    calc.recompute_provisional_rent(lease)
    calc.apply_rent_variant(lease)
    touch(lease)
    return object_response(ser.lease_out(lease))


@bp.post("/leases/<lease_id>/compliance-decisions")
@endpoint("ComplianceOfficer")
def lease_compliance_decision(lease_id):
    body = v.json_body()
    action = v.get_enum(body, "action", enums.LEASE_DECISION_ACTIONS)
    v.get_string(body, "decision_note")

    lease = get_lease(lease_id)
    if action == "RETURN_FOR_REVISION":
        _lease_state_guard(lease, ("PENDING_FMV_REVIEW",))
        if lease["revision_round"] > 1:
            raise ApiError(
                "ERR_REVISION_LIMIT_EXCEEDED",
                "Lease '%s' has already used revision round %d of a cap of %d."
                % (lease["id"], lease["revision_round"], REVISION_ROUND_CAP),
            )
        lease["status"] = "DRAFT"
        lease["revision_round"] += 1
        lease["fmv_certification_status"] = "NOT_STARTED"
        lease["fmv_submitted_by_user_id"] = None
        touch(lease)
        return object_response(ser.lease_out(lease))

    # REINSTATE — the compensating action for the hop-3/hop-4 suspension.
    _lease_state_guard(lease, ("SUSPENDED_MIX_REVIEW",))
    building = db.buildings[lease["building_id"]]
    if building["tenant_mix_posture"] in ("RESTRICTED", "FROZEN"):
        raise ApiError(
            "ERR_BUILDING_MIX_RESTRICTED",
            "Building '%s' still reads %s." % (building["id"], building["tenant_mix_posture"]),
        )
    lease["status"] = "DRAFT"
    for project in calc.projects_of_lease(lease["id"]):
        if project["status"] == "ON_HOLD":
            project["status"] = project["on_hold_from_status"]
            project["on_hold_from_status"] = None
            touch(project)
    # revision_round is deliberately left untouched: a suspension was never the
    # agent's fault (PRD Section 3.5).
    touch(lease)
    return object_response(ser.lease_out(lease))


@bp.post("/leases/<lease_id>/certify-fmv")
@endpoint("ComplianceOfficer")
def certify_fmv(lease_id):
    body = v.json_body()
    v.get_string(body, "certification_note", required=False, allow_empty=True)

    lease = get_lease(lease_id)
    _lease_state_guard(lease, ("PENDING_FMV_REVIEW",))
    building = db.buildings[lease["building_id"]]
    _frozen_guard(building)
    if acting_user_id() == lease["fmv_submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who submitted lease '%s' for review may not certify it." % lease["id"],
        )
    tenant = db.tenants[lease["tenant_id"]]
    suite = db.suites[lease["suite_id"]]
    _qualifying_appraisal_guard(lease, tenant)
    floor_psf, ceiling_psf, controlling = calc.fmv_band(lease, tenant, building, suite)

    # The ceiling is tested before the floor (PRD Section 3.4).
    if lease["base_rent_psf_annual"] > ceiling_psf:
        raise ApiError(
            "ERR_RENT_ABOVE_FMV_CEILING",
            "base_rent_psf_annual %s exceeds the admissible ceiling of %s."
            % (lease["base_rent_psf_annual"], ceiling_psf),
        )
    if lease["base_rent_psf_annual"] < floor_psf:
        raise ApiError(
            "ERR_RENT_BELOW_FMV_FLOOR",
            "base_rent_psf_annual %s falls below the admissible floor of %s."
            % (lease["base_rent_psf_annual"], floor_psf),
        )

    lease["status"] = "FMV_CERTIFIED"
    lease["certified_fmv_floor_psf"] = floor_psf
    lease["certified_fmv_ceiling_psf"] = ceiling_psf
    for appraisal in calc.appraisals_of_lease(lease["id"]):
        should_control = controlling is not None and appraisal["id"] == controlling["id"]
        if appraisal["is_controlling"] != should_control:
            appraisal["is_controlling"] = should_control
            touch(appraisal)
    lease["fmv_certification_status"] = "CERTIFIED"
    calc.apply_rent_variant(lease)
    touch(lease)

    if abs(lease["fmv_variance_pct"]) > calc.FMV_DEVIATION_THRESHOLD_PCT:
        open_fmv_deviation_case(
            lease,
            basis="Certified rent deviates from the published rate card by %s on lease %s."
            % (lease["fmv_variance_pct"], lease["id"]),
        )
        calc.recompute_tenant_risk(tenant)
    return object_response(ser.lease_out(lease))


@bp.post("/leases/<lease_id>/compliance-attestations")
@endpoint("LeasingAgent")
def file_attestation(lease_id):
    body = v.json_body()
    attestation_type = v.get_enum(body, "attestation_type", enums.ATTESTATION_TYPES)
    on_file = v.get_bool(body, "on_file")
    v.get_string(body, "document_reference")

    lease = get_lease(lease_id)
    _open_lease_guard(lease)

    target = {
        "SIGNED_LEASE": "signed_lease_on_file",
        "MASTER_LEASE_CONSENT": "master_lease_consent_on_file",
        "SPACE_SHARING_SCHEDULE": "space_sharing_schedule_on_file",
    }[attestation_type]
    lease[target] = on_file

    touch(lease)
    return object_response(ser.lease_out(lease))


# ------------------------------------------------------ occupancy lifecycle


@bp.post("/leases/<lease_id>/execute")
@endpoint("LeasingAgent")
def execute_lease(lease_id):
    body = v.json_body()
    v.get_string(body, "execution_note", required=False, allow_empty=True)

    lease = get_lease(lease_id)
    _lease_state_guard(lease, ("FMV_CERTIFIED",))
    building = db.buildings[lease["building_id"]]
    suite = db.suites[lease["suite_id"]]
    tenant = db.tenants[lease["tenant_id"]]
    _frozen_guard(building)
    _exclusive_use_conflict(lease, tenant)
    _radius_conflict(lease, tenant)
    if (
        tenant["affiliation"] in calc.ANCHOR_AFFILIATIONS
        and building["tenant_mix_posture"] == "RESTRICTED"
    ):
        raise ApiError(
            "ERR_BUILDING_MIX_RESTRICTED",
            "Building '%s' is RESTRICTED and the tenant is health-system affiliated."
            % building["id"],
        )
    master = db.leases.get(lease["master_lease_id"]) if lease["master_lease_id"] else None
    _master_type_guard(lease["lease_type"], master)
    if lease["lease_type"] == "SUBLEASE" and master["status"] != "ACTIVE":
        raise ApiError(
            "ERR_MASTER_LEASE_NOT_ACTIVE",
            "Master lease '%s' is in status %s; ACTIVE is required at execution."
            % (master["id"], master["status"]),
        )
    if lease["lease_type"] == "SUBLEASE" and not lease["master_lease_consent_on_file"]:
        raise ApiError(
            "ERR_MASTER_LEASE_CONSENT_MISSING",
            "Lease '%s' has no master-lease consent on file." % lease["id"],
        )
    if not lease["signed_lease_on_file"]:
        raise ApiError(
            "ERR_SIGNED_LEASE_NOT_ON_FILE",
            "Lease '%s' has no signed lease on file." % lease["id"],
        )
    conflict = calc.find_suite_term_conflict(lease)
    if conflict is not None:
        raise ApiError(
            "ERR_SUITE_TERM_CONFLICT",
            "Lease '%s' already holds suite '%s' over an overlapping buffered term."
            % (conflict["id"], suite["id"]),
        )
    if suite["occupancy_status"] != "VACANT" or calc.suite_occupied_by_other(
        suite["id"], lease["id"]
    ):
        raise ApiError(
            "ERR_SUITE_NOT_AVAILABLE",
            "Suite '%s' is not available (occupancy_status %s)."
            % (suite["id"], suite["occupancy_status"]),
        )

    lease["status"] = "EXECUTED"
    suite["occupancy_status"] = "RESERVED"
    touch(suite)
    calc.recompute_building_mix(building)
    touch(building)
    touch(lease)
    return object_response(ser.lease_out(lease))


@bp.post("/leases/<lease_id>/commence")
@endpoint("PropertyManager")
def commence_lease(lease_id):
    body = v.json_body()
    v.get_string(body, "commencement_note", required=False, allow_empty=True)

    lease = get_lease(lease_id)
    _lease_state_guard(lease, ("EXECUTED",))
    building = db.buildings[lease["building_id"]]
    suite = db.suites[lease["suite_id"]]
    tenant = db.tenants[lease["tenant_id"]]
    _frozen_guard(building)
    if suite["suite_class"] == "IMAGING" and not suite["shielding_certified"]:
        raise ApiError(
            "ERR_SHIELDING_CERTIFICATION_MISSING",
            "Suite '%s' is an IMAGING suite without shielding certification." % suite["id"],
        )
    # Re-run rather than trust from execution time: a peer lease may have taken
    # its exclusive in the interval (PRD Section 3.5).
    _exclusive_use_conflict(lease, tenant)
    _radius_conflict(lease, tenant)
    if clock_date() < lease["term_start"]:
        raise ApiError(
            "ERR_TERM_NOT_YET_STARTED",
            "The clock date has not reached term_start %s." % lease["term_start"].isoformat(),
        )
    for project in calc.projects_of_lease(lease["id"]):
        if project["status"] in ("DESIGN", "IN_REVIEW", "PERMITTED", "CONSTRUCTION", "ON_HOLD"):
            raise ApiError(
                "ERR_TI_PROJECT_NOT_COMPLETE",
                "Tenant-improvement project '%s' is still in flight (%s)."
                % (project["id"], project["status"]),
            )

    lease["status"] = "ACTIVE"
    suite["occupancy_status"] = "OCCUPIED"
    touch(suite)
    calc.recompute_building_mix(building)
    touch(building)
    touch(lease)
    return object_response(ser.lease_out(lease))


@bp.post("/leases/<lease_id>/terminate")
@endpoint("PropertyManager")
def terminate(lease_id):
    body = v.json_body()
    reason = v.get_enum(body, "termination_reason", enums.TERMINATION_REASONS)
    note = v.get_string(body, "termination_note", required=False, allow_empty=True)

    lease = get_lease(lease_id)
    _lease_state_guard(lease, ("EXECUTED", "ACTIVE", "HOLDOVER"))
    if reason != "DEFAULT" and calc.lease_has_outstanding_rent(lease["id"]):
        raise ApiError(
            "ERR_OUTSTANDING_RENT_BALANCE",
            "Lease '%s' still carries an ISSUED or DELINQUENT invoice." % lease["id"],
        )

    # terminate_lease runs all four hops and advances the lease's own version.
    cascades.terminate_lease(lease, reason, note)
    return object_response(ser.lease_out(lease))


@bp.post("/leases/<lease_id>/after-hours-authorization")
@endpoint("PropertyManager")
def after_hours_authorization(lease_id):
    body = v.json_body()
    authorized = v.get_bool(body, "authorized")

    lease = get_lease(lease_id)
    _open_lease_guard(lease)
    tenant = db.tenants[lease["tenant_id"]]
    # Rung 21 bites on the grant: the cascade in Section 3.7 revokes access and
    # no cure restores it, so a manager may still revoke while on watch.
    if authorized and tenant["compliance_watch_status"] == "WATCH":
        raise ApiError(
            "ERR_TENANT_ON_COMPLIANCE_WATCH",
            "Tenant '%s' is on referral-compliance watch." % tenant["id"],
        )

    lease["after_hours_authorized"] = authorized
    touch(lease)
    return object_response(ser.lease_out(lease))
