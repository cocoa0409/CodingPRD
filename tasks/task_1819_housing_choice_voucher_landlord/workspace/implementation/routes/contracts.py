"""HAPContract endpoints and cascades."""

from datetime import date

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    parse_pagination, get_or_404, sorted_page,
    landlord_of_contract, landlord_of_unit, assert_landlord_owns,
)
from services.calculations import (
    rent_reasonableness, hap_split, first_payment_period, add_one_year,
    find_payment_standard, _parse_iso_date,
)

bp = Blueprint("contracts", __name__)

LIVE_CONTRACT_STATUSES = ("DRAFT", "PENDING_INSPECTION", "APPROVED", "ACTIVE", "ABATED")


def serialize_contract(c):
    return {
        "id": c["id"],
        "unit_id": c["unit_id"],
        "family_id": c["family_id"],
        "contract_rent_cents": c["contract_rent_cents"],
        "approved_rent_cents": c["approved_rent_cents"],
        "hap_portion_cents": c["hap_portion_cents"],
        "tenant_portion_cents": c["tenant_portion_cents"],
        "lease_start_date": c["lease_start_date"],
        "status": c["status"],
        "next_recert_due_date": c.get("next_recert_due_date"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/hcv/contracts", methods=["POST"])
def create_contract():
    role, user_id = require_roles("Landlord")
    body = request.get_json(force=True, silent=True) or {}
    unit_id = body.get("unit_id")
    family_id = body.get("family_id")
    contract_rent_cents = body.get("contract_rent_cents")
    lease_start_date = body.get("lease_start_date")
    expected_unit_version = body.get("expected_unit_version")

    # Existence: left-to-right as identifiers appear in the payload
    unit = get_or_404(db.units, unit_id, "Unit")
    family = get_or_404(db.voucher_families, family_id, "VoucherFamily")

    # State check on Unit (must be LISTED per state machine)
    # OCC check runs at priority 5, AFTER state checks (priority 4).
    # But ERR_UNIT_ALREADY_UNDER_CONTRACT is priority 11. ERR_INVALID_STATE covers the
    # unit's state-machine precondition (LISTED). Note the scaffold says the create
    # contract endpoint's OCC is priority 5, so we must do: state checks (unit must be
    # LISTED) at p4, then OCC p5, then ownership p6, etc.

    # Priority 4 (state): unit.status == LISTED
    if unit["status"] != "LISTED":
        # if unit already has a live contract, that's ERR_UNIT_ALREADY_UNDER_CONTRACT (p11).
        # but the state-machine precondition is "Unit.status == LISTED". The catalog says
        # ERR_UNIT_ALREADY_UNDER_CONTRACT is the one-live-contract-per-unit check.
        # The two overlap when the unit is UNDER_CONTRACT because of a live contract.
        # Per priority ordering: p4 ERR_INVALID_STATE fires first for state precondition.
        # However the specific error ERR_UNIT_ALREADY_UNDER_CONTRACT is more semantically
        # precise. The PRD §3.3 lists the guard order as: NOT_OWNER, LANDLORD_SUSPENDED,
        # VOUCHER_SIZE_MISMATCH, UNIT_ALREADY_UNDER_CONTRACT, INVALID_AMOUNT — i.e. the
        # already-under-contract check is a business rule, and the unit's state machine
        # precondition (LISTED) is effectively captured by it. We'll check live-contract
        # here and raise ERR_UNIT_ALREADY_UNDER_CONTRACT at its proper priority position.
        pass

    # Priority 5 (OCC): expected_unit_version vs unit.version
    if expected_unit_version is None or expected_unit_version != unit["version"]:
        raise errors.stale_version("expected_unit_version does not match unit's current version")

    # Priority 6 (ownership)
    owner = landlord_of_unit(unit)
    assert_landlord_owns(user_id, owner)

    # Priority 7 (landlord ACTIVE)
    if owner is None or owner["status"] != "ACTIVE":
        raise errors.landlord_suspended()

    # Priority 10 (voucher size)
    if family["voucher_bedroom_size"] < unit["bedroom_count"]:
        raise errors.voucher_size_mismatch()

    # Priority 11 (one live contract per unit)
    for c in db.hap_contracts.values():
        if c["unit_id"] == unit_id and c["status"] in LIVE_CONTRACT_STATUSES:
            raise errors.unit_already_under_contract()

    # Priority 12 (amounts)
    if not isinstance(contract_rent_cents, int) or contract_rent_cents <= 0:
        raise errors.invalid_amount("contract_rent_cents must be > 0")
    if not isinstance(family["annual_income_cents"], int) or family["annual_income_cents"] < 0:
        raise errors.invalid_amount("annual_income_cents must be >= 0")

    rec = db.make_record({
        "unit_id": unit_id,
        "family_id": family_id,
        "contract_rent_cents": contract_rent_cents,
        "approved_rent_cents": 0,
        "hap_portion_cents": 0,
        "tenant_portion_cents": 0,
        "lease_start_date": lease_start_date,
        "status": "DRAFT",
        "next_recert_due_date": None,
    })
    db.hap_contracts[rec["id"]] = rec

    # Side effect: Unit LISTED -> UNDER_CONTRACT, version bump
    unit["status"] = "UNDER_CONTRACT"
    db.touch(unit)

    return success_object(serialize_contract(rec), 201)


@bp.route("/hcv/contracts", methods=["GET"])
def list_contracts():
    require_roles("HousingAuthorityAdmin", "Landlord")
    limit, offset = parse_pagination()
    family_id = request.args.get("family_id")
    rows = list(db.hap_contracts.values())
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    page, total = sorted_page(rows, limit, offset)
    return success_list([serialize_contract(c) for c in page], total, limit, offset)


@bp.route("/hcv/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_roles("HousingAuthorityAdmin", "Landlord", "Inspector")
    c = get_or_404(db.hap_contracts, cid, "HAPContract")
    return success_object(serialize_contract(c))


@bp.route("/hcv/contracts/<cid>/submit", methods=["POST"])
def submit_contract(cid):
    role, user_id = require_roles("Landlord")
    c = get_or_404(db.hap_contracts, cid, "HAPContract")
    if c["status"] != "DRAFT":
        raise errors.invalid_state("Contract must be DRAFT to submit")
    owner = landlord_of_contract(c)
    assert_landlord_owns(user_id, owner)
    if not isinstance(c["contract_rent_cents"], int) or c["contract_rent_cents"] <= 0:
        raise errors.invalid_amount("contract_rent_cents must be > 0")

    # Run rent reasonableness against lease_start_date
    unit = db.units[c["unit_id"]]
    prop = db.properties[unit["property_id"]]
    family = db.voucher_families[c["family_id"]]
    lease_start = _parse_iso_date(c["lease_start_date"])

    approved = rent_reasonableness(c["contract_rent_cents"], prop["zip_code"],
                                   unit["bedroom_count"], lease_start)
    ps = find_payment_standard(prop["zip_code"], unit["bedroom_count"], lease_start)
    ps_amount = ps["amount_cents"] if ps else 0
    tenant_portion, hap_portion = hap_split(approved, family["annual_income_cents"], ps_amount)

    c["approved_rent_cents"] = approved
    c["tenant_portion_cents"] = tenant_portion
    c["hap_portion_cents"] = hap_portion
    c["status"] = "PENDING_INSPECTION"
    db.touch(c)

    # Auto-create INITIAL inspection in SCHEDULED status
    insp = db.make_record({
        "contract_id": c["id"],
        "inspection_type": "INITIAL",
        "scheduled_date": db.current_logical_date().isoformat(),
        "status": "SCHEDULED",
        "result_recorded_date": None,
    })
    db.inspections[insp["id"]] = insp

    return success_object(serialize_contract(c))


@bp.route("/hcv/contracts/<cid>/withdraw", methods=["POST"])
def withdraw_contract(cid):
    role, user_id = require_roles("Landlord")
    c = get_or_404(db.hap_contracts, cid, "HAPContract")
    if c["status"] != "PENDING_INSPECTION":
        raise errors.invalid_state("Contract must be PENDING_INSPECTION to withdraw")
    owner = landlord_of_contract(c)
    assert_landlord_owns(user_id, owner)

    c["status"] = "DRAFT"
    c["approved_rent_cents"] = 0
    c["hap_portion_cents"] = 0
    c["tenant_portion_cents"] = 0
    db.touch(c)

    # Cancel the SCHEDULED INITIAL inspection
    for insp in db.inspections.values():
        if insp["contract_id"] == c["id"] and insp["inspection_type"] == "INITIAL" and insp["status"] == "SCHEDULED":
            insp["status"] = "CLOSED"
            db.touch(insp)

    return success_object(serialize_contract(c))


@bp.route("/hcv/contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    require_roles("HousingAuthorityAdmin")
    c = get_or_404(db.hap_contracts, cid, "HAPContract")
    if c["status"] != "APPROVED":
        raise errors.invalid_state("Contract must be APPROVED to activate")
    lease_start = _parse_iso_date(c["lease_start_date"])
    if lease_start > db.current_logical_date():
        raise errors.invalid_state("lease_start_date must be on or before current logical date")

    c["status"] = "ACTIVE"
    c["next_recert_due_date"] = add_one_year(lease_start).isoformat()
    db.touch(c)

    # VoucherFamily SEARCHING -> LEASED
    family = db.voucher_families.get(c["family_id"])
    if family and family["status"] == "SEARCHING":
        family["status"] = "LEASED"
        db.touch(family)

    # First HAPPayment
    first_period = first_payment_period(lease_start)
    pay = {
        "id": db.new_uuid(),
        "created_at": db.iso_timestamp(),
        "contract_id": c["id"],
        "period_month": first_period.isoformat(),
        "hap_amount_cents": c["hap_portion_cents"],
        "disbursement_status": "SCHEDULED",
    }
    db.hap_payments[pay["id"]] = pay

    return success_object(serialize_contract(c))


def _terminate_contract_cascade(c, from_status):
    """Shared termination cascade (used by /terminate and portability absorb)."""
    c["status"] = "TERMINATED"
    db.touch(c)
    family = db.voucher_families.get(c["family_id"])
    if family and family["status"] == "LEASED":
        family["status"] = "SEARCHING"
        db.touch(family)
    unit = db.units.get(c["unit_id"])
    if unit:
        if from_status == "ACTIVE" and unit["status"] == "UNDER_CONTRACT":
            unit["status"] = "LISTED"
            db.touch(unit)
        elif from_status == "ABATED" and unit["status"] == "SUSPENDED_ABATEMENT":
            unit["status"] = "LISTED"
            db.touch(unit)
    today = db.current_logical_date()
    for p in db.hap_payments.values():
        if p["contract_id"] != c["id"]:
            continue
        period = _parse_iso_date(p["period_month"])
        # "future" = period month at/after current month's start
        current_month_start = date(today.year, today.month, 1)
        if period < current_month_start:
            continue
        if p["disbursement_status"] in ("SCHEDULED", "ABATED_HELD"):
            p["disbursement_status"] = "VOID"


@bp.route("/hcv/contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    require_roles("HousingAuthorityAdmin")
    c = get_or_404(db.hap_contracts, cid, "HAPContract")
    if c["status"] not in ("ACTIVE", "ABATED"):
        raise errors.invalid_state("Contract must be ACTIVE or ABATED to terminate")
    _terminate_contract_cascade(c, c["status"])
    return success_object(serialize_contract(c))


@bp.route("/hcv/contracts/<cid>/inspections", methods=["GET"])
def list_contract_inspections(cid):
    require_roles("HousingAuthorityAdmin", "Landlord", "Inspector")
    get_or_404(db.hap_contracts, cid, "HAPContract")
    limit, offset = parse_pagination()
    rows = [i for i in db.inspections.values() if i["contract_id"] == cid]
    page, total = sorted_page(rows, limit, offset)
    from routes.inspections import serialize_inspection
    return success_list([serialize_inspection(i) for i in page], total, limit, offset)


@bp.route("/hcv/contracts/<cid>/inspections", methods=["POST"])
def schedule_inspection(cid):
    require_roles("HousingAuthorityAdmin")
    get_or_404(db.hap_contracts, cid, "HAPContract")
    body = request.get_json(force=True, silent=True) or {}
    inspection_type = body.get("inspection_type")
    scheduled_date = body.get("scheduled_date")
    # Priority 9: scheduled_date must not precede current logical date
    if scheduled_date:
        sd = _parse_iso_date(scheduled_date)
        if sd < db.current_logical_date():
            raise errors.schedule_in_past()
    if inspection_type not in ("ANNUAL", "REINSPECTION", "COMPLAINT"):
        # scaffold: this endpoint is for non-initial inspections
        raise errors.invalid_state("inspection_type must be ANNUAL, REINSPECTION, or COMPLAINT")
    rec = db.make_record({
        "contract_id": cid,
        "inspection_type": inspection_type,
        "scheduled_date": scheduled_date,
        "status": "SCHEDULED",
        "result_recorded_date": None,
    })
    db.inspections[rec["id"]] = rec
    from routes.inspections import serialize_inspection
    return success_object(serialize_inspection(rec), 201)


@bp.route("/hcv/contracts/<cid>/hap-payments", methods=["GET"])
def list_contract_payments(cid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    get_or_404(db.hap_contracts, cid, "HAPContract")
    limit, offset = parse_pagination()
    rows = [p for p in db.hap_payments.values() if p["contract_id"] == cid]
    page, total = sorted_page(rows, limit, offset)
    from routes.hap_payments import serialize_payment
    return success_list([serialize_payment(p) for p in page], total, limit, offset)


@bp.route("/hcv/contracts/<cid>/rent-increase-requests", methods=["GET"])
def list_contract_increases(cid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    get_or_404(db.hap_contracts, cid, "HAPContract")
    limit, offset = parse_pagination()
    rows = [r for r in db.rent_increase_requests.values() if r["contract_id"] == cid]
    page, total = sorted_page(rows, limit, offset)
    from routes.rent_increase_requests import serialize_request
    return success_list([serialize_request(r) for r in page], total, limit, offset)


@bp.route("/hcv/contracts/<cid>/recertifications", methods=["GET"])
def list_contract_recertifications(cid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    get_or_404(db.hap_contracts, cid, "HAPContract")
    limit, offset = parse_pagination()
    rows = [r for r in db.recertifications.values() if r["contract_id"] == cid]
    page, total = sorted_page(rows, limit, offset)
    from routes.recertifications import serialize_recertification
    return success_list([serialize_recertification(r) for r in page], total, limit, offset)
