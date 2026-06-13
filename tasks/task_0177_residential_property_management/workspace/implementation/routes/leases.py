"""Lease routes (PRD §3.3, §3.4, §3.5).

create (original / renewal w/ OCC + overlap), get, list, sign (cascade),
offer-renewal (cyclic OCC toggle), expire (cascade), assess-late-fees (sweep).
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, optional_string, require_int, optional_int,
    require_number, optional_number, require_iso_date, parse_pagination,
    paginate, filter_param, parse_date,
)
from services import domain

bp = Blueprint("leases", __name__)


def _term_overlaps(a_start, a_end, b_start, b_end):
    """Half-open intervals [start, end). Overlap iff a_start < b_end and
    b_start < a_end. Adjacency (a_end == b_start) does not overlap."""
    return parse_date(a_start) < parse_date(b_end) and parse_date(b_start) < parse_date(a_end)


@bp.route("/leases", methods=["POST"])
def create_lease():
    require_role({"PropertyManager"})
    body = get_json_body()
    unit_id = require_string(body, "unit_id")
    start_date = require_iso_date(body, "start_date")
    end_date = require_iso_date(body, "end_date")
    monthly_rent = require_int(body, "monthly_rent_cents", minimum=1)
    rent_due_day = optional_int(body, "rent_due_day", 1, minimum=1, maximum=28)
    grace_period = optional_int(body, "grace_period_days", 5, minimum=0)
    late_fee_flat = optional_int(body, "late_fee_flat_cents", 0, minimum=0)
    late_fee_pct = optional_number(body, "late_fee_pct", 0, minimum=0, maximum=0.25)
    applicant_id = optional_string(body, "applicant_id")
    renewed_from = optional_string(body, "renewed_from_lease_id")
    expected_lease_version = optional_int(body, "expected_lease_version", None)

    # end_date strictly after start_date (priority 5 request-shape check).
    if parse_date(end_date) <= parse_date(start_date):
        raise err(errors.ERR_INVALID_REQUEST, "end_date must be after start_date")

    with db.LOCK:
        # FK resolution (priority 4): unit_id, applicant_id, renewed_from_lease_id.
        unit = db.units.get(unit_id)
        if unit is None:
            raise err(errors.ERR_FK_NOT_FOUND, "unit_id does not resolve")
        prior = None
        if renewed_from is not None:
            prior = db.leases.get(renewed_from)
            if prior is None:
                raise err(errors.ERR_FK_NOT_FOUND, "renewed_from_lease_id does not resolve")
        if applicant_id is not None:
            if applicant_id not in db.applicants:
                raise err(errors.ERR_FK_NOT_FOUND, "applicant_id does not resolve")

        is_renewal = renewed_from is not None

        # OCC check (priority 6) precedes overlap/availability state checks.
        if is_renewal:
            if expected_lease_version is None:
                raise err(errors.ERR_INVALID_REQUEST,
                          "expected_lease_version required for a renewal")
            if prior["version"] != expected_lease_version:
                raise err(errors.ERR_STALE_VERSION, "prior lease version is stale")

        # Lease-term overlap (priority 10.5): against ACTIVE/RENEWAL_OFFERED
        # leases on the unit, excluding the prior lease being renewed.
        for other in db.leases.values():
            if other["unit_id"] != unit_id:
                continue
            if other["status"] not in ("ACTIVE", "RENEWAL_OFFERED"):
                continue
            if prior is not None and other["id"] == prior["id"]:
                continue
            if _term_overlaps(start_date, end_date, other["start_date"], other["end_date"]):
                raise err(errors.ERR_LEASE_OVERLAP,
                          "lease term overlaps an existing lease on the unit")

        # Unit availability (priority 11): non-renewal lease needs VACANT_READY;
        # renewal whose renewed_from == unit.active_lease_id is exempt.
        if is_renewal and unit["active_lease_id"] == prior["id"]:
            pass  # renewal exemption
        else:
            if unit["occupancy_status"] != "VACANT_READY":
                raise err(errors.ERR_UNIT_NOT_AVAILABLE, "Unit is not VACANT_READY")

        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "unit_id": unit_id,
            "applicant_id": applicant_id,
            "tenant_id": None,
            "renewed_from_lease_id": renewed_from,
            "start_date": start_date,
            "end_date": end_date,
            "monthly_rent_cents": monthly_rent,
            "rent_due_day": rent_due_day,
            "grace_period_days": grace_period,
            "late_fee_flat_cents": late_fee_flat,
            "late_fee_pct": late_fee_pct,
            "status": "DRAFT",
            "balance_due_cents": 0,
            "superseded_by_lease_id": None,
        }
        db.leases[record["id"]] = record

        # Successful renewal create increments the prior lease's version so a
        # later stale renewal create is rejected (PRD §2.9).
        if is_renewal:
            db.touch(prior)

        return object_response(serialize(record), 201)


@bp.route("/leases/<id>", methods=["GET"])
def get_lease(id):
    require_role({"PropertyManager", "Owner", "Tenant"})
    with db.LOCK:
        record = db.leases.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Lease not found")
        return object_response(serialize(record), 200)


@bp.route("/leases", methods=["GET"])
def list_leases():
    require_role({"PropertyManager", "Owner"})
    unit_id = filter_param(request.args, "unit_id")
    applicant_id = filter_param(request.args, "applicant_id")
    renewed_from = filter_param(request.args, "renewed_from_lease_id")
    status = filter_param(request.args, "status")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.leases.values())
        if unit_id is not None:
            records = [r for r in records if r["unit_id"] == unit_id]
        if applicant_id is not None:
            records = [r for r in records if r.get("applicant_id") == applicant_id]
        if renewed_from is not None:
            records = [r for r in records if r.get("renewed_from_lease_id") == renewed_from]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/leases/<id>/sign", methods=["POST"])
def sign_lease(id):
    require_role({"PropertyManager"})
    with db.LOCK:
        lease = db.leases.get(id)
        if lease is None:
            raise err(errors.ERR_NOT_FOUND, "Lease not found")
        if lease["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Lease is not DRAFT")

        is_renewal = lease.get("renewed_from_lease_id") is not None
        prior = db.leases.get(lease["renewed_from_lease_id"]) if is_renewal else None
        unit = db.units.get(lease["unit_id"])

        # Applicant approval (original leases only) — ERR_APPLICANT_NOT_APPROVED.
        if not is_renewal:
            applicant = db.applicants.get(lease.get("applicant_id"))
            if applicant is None or applicant["status"] != "APPROVED":
                raise err(errors.ERR_APPLICANT_NOT_APPROVED,
                          "Source applicant is not APPROVED")

        # Unit availability with renewal exemption — ERR_UNIT_NOT_AVAILABLE.
        renewal_exempt = (is_renewal and prior is not None
                          and unit is not None
                          and unit["active_lease_id"] == prior["id"])
        if not renewal_exempt:
            if unit is None or unit["occupancy_status"] != "VACANT_READY":
                raise err(errors.ERR_UNIT_NOT_AVAILABLE, "Unit is not VACANT_READY")

        # SecurityDeposit in HELD must exist — ERR_DEPOSIT_REQUIRED.
        held_deposit = any(
            d["lease_id"] == lease["id"] and d["status"] == "HELD"
            for d in db.security_deposits.values()
        )
        if not held_deposit:
            raise err(errors.ERR_DEPOSIT_REQUIRED, "A HELD security deposit is required")

        # --- Cascade ---
        if not is_renewal:
            # hop 1: mint tenant from applicant.
            applicant = db.applicants.get(lease["applicant_id"])
            common = db.new_common()
            tenant = {
                **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
                "applicant_id": applicant["id"],
                "full_name": applicant["full_name"],
                "email": applicant["email"],
                "status": "CURRENT",
            }
            db.tenants[tenant["id"]] = tenant
            lease["tenant_id"] = tenant["id"]
            # hop 2: applicant -> LEASED.
            applicant["status"] = "LEASED"
            db.touch(applicant)
        else:
            # renewal: inherit prior lease's tenant.
            lease["tenant_id"] = prior["tenant_id"]

        lease["status"] = "ACTIVE"
        db.touch(lease)

        # hop 3: unit -> OCCUPIED, active_lease_id -> this lease.
        unit["occupancy_status"] = "OCCUPIED"
        unit["active_lease_id"] = lease["id"]
        db.touch(unit)

        # hop 4: renewal supersedes prior lease.
        if is_renewal:
            prior["status"] = "EXPIRED"
            prior["superseded_by_lease_id"] = lease["id"]
            db.touch(prior)

        return object_response(serialize(lease), 200)


@bp.route("/leases/<id>/offer-renewal", methods=["POST"])
def offer_renewal(id):
    require_role({"PropertyManager"})
    body = get_json_body()
    with db.LOCK:
        lease = db.leases.get(id)
        if lease is None:
            raise err(errors.ERR_NOT_FOUND, "Lease not found")
        expected = require_int(body, "expected_lease_version")
        # OCC (priority 6) precedes state-admissibility (priority 7).
        if lease["version"] != expected:
            raise err(errors.ERR_STALE_VERSION, "lease version is stale")
        if lease["status"] == "ACTIVE":
            lease["status"] = "RENEWAL_OFFERED"
        elif lease["status"] == "RENEWAL_OFFERED":
            lease["status"] = "ACTIVE"
        else:
            raise err(errors.ERR_INVALID_STATE,
                      "Lease is not ACTIVE or RENEWAL_OFFERED")
        db.touch(lease)
        return object_response(serialize(lease), 200)


@bp.route("/leases/<id>/expire", methods=["POST"])
def expire_lease(id):
    require_role({"PropertyManager"})
    body = get_json_body()
    as_of = require_iso_date(body, "as_of_date")
    with db.LOCK:
        lease = db.leases.get(id)
        if lease is None:
            raise err(errors.ERR_NOT_FOUND, "Lease not found")
        if lease["status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Lease is not ACTIVE")
        if parse_date(as_of) < parse_date(lease["end_date"]):
            raise err(errors.ERR_LEASE_NOT_ENDED, "Lease term has not ended")
        lease["status"] = "EXPIRED"
        db.touch(lease)
        # Cascade: unit -> VACANT_TURN, active_lease_id -> null; tenant -> FORMER.
        unit = db.units.get(lease["unit_id"])
        if unit is not None:
            unit["occupancy_status"] = "VACANT_TURN"
            unit["active_lease_id"] = None
            db.touch(unit)
        tenant = db.tenants.get(lease.get("tenant_id"))
        if tenant is not None and tenant["status"] != "FORMER":
            tenant["status"] = "FORMER"
            db.touch(tenant)
        return object_response(serialize(lease), 200)


@bp.route("/leases/<id>/assess-late-fees", methods=["POST"])
def assess_late_fees(id):
    require_role({"PropertyManager"})
    body = get_json_body()
    as_of = require_iso_date(body, "as_of_date")
    with db.LOCK:
        lease = db.leases.get(id)
        if lease is None:
            raise err(errors.ERR_NOT_FOUND, "Lease not found")
        domain.assess_late_fees(lease, as_of)
        return object_response(serialize(lease), 200)
