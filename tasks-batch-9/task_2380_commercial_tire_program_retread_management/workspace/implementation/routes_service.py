"""RoadServiceCall, ScrapManifest and CrossLocationInvoice."""

from flask import Blueprint, g

import calc
import common
import derive
import errors
import serialize
import validate as v
from auth import endpoint, fleet_scope, is_fleet_manager, scope_filter_value
from db import db, insert, ordered, touch
from errors import fail
from response import created, ok
from util import utc_date

bp = Blueprint("service", __name__)


# ================================================================ RoadServiceCall

def _call_agreement(call):
    """The ACTIVE agreement covering the UTC date of reported_at, if any."""
    return derive.active_agreement_on(
        call["fleet_account_id"], utc_date(call["reported_at_dt"])
    )


def _technician_scope(call):
    """Validation step 5 — only the assigned technician may arrive or complete."""
    if call["technician_id"] != g.user_id:
        fail(errors.ERR_TECHNICIAN_SCOPE_VIOLATION)


def _release_technician(call):
    if call["technician_id"] is None:
        return
    tech = db.technicians.get(call["technician_id"])
    if tech is not None and tech["status"] == "ON_CALL":
        tech["status"] = "AVAILABLE"
        touch(tech)


@bp.post("/road-service-calls")
@endpoint("DispatchCoordinator", "FleetManager")
def create_call():
    payload = v.body()
    if is_fleet_manager():
        claimed = payload.get("fleet_account_id")
        if isinstance(claimed, str) and claimed != g.user_id:
            fail(errors.ERR_FLEET_SCOPE_VIOLATION)
    fleet_account_id = v.s_str(payload, "fleet_account_id")
    vehicle_id = v.s_str(payload, "vehicle_id")
    service_location_id = v.s_str(payload, "service_location_id")
    priority = v.s_enum(payload, "priority", ("NORMAL", "EMERGENCY"))
    complaint = v.s_str(payload, "complaint")
    reported_raw, reported_dt = v.s_datetime(payload, "reported_at")

    fleet_row = common.fleet(fleet_account_id)
    vehicle_row = common.vehicle(vehicle_id)
    common.location(service_location_id)
    fleet_scope(fleet_row["id"])

    if vehicle_row["fleet_account_id"] != fleet_row["id"]:
        fail(errors.ERR_FLEET_MISMATCH)
    if fleet_row["status"] != "ACTIVE":
        fail(errors.ERR_FLEET_SUSPENDED)

    row = insert(
        db.road_service_calls,
        {
            "fleet_account_id": fleet_row["id"],
            "vehicle_id": vehicle_row["id"],
            "service_location_id": service_location_id,
            "technician_id": None,
            "priority": priority,
            "complaint": complaint,
            "reported_at": reported_raw,
            "reported_at_dt": reported_dt,
            "dispatched_at": None,
            "dispatched_at_dt": None,
            "arrived_at": None,
            "arrived_at_dt": None,
            "closed_at": None,
            "closed_at_dt": None,
            "dispatch_miles": None,
            "labor_hours": None,
            "dispatch_status": "OPEN",
            "billing_status": "UNBILLED",
            "committed_response_minutes": None,
            "actual_response_minutes": None,
            "sla_met": None,
            "gross_cents": None,
            "sla_credit_cents": 0,
            "invoice_total_cents": None,
            "cancel_reason": None,
            "cross_location_invoice_id": None,
        },
    )
    common.sync_vehicle_status(vehicle_row)
    return created(serialize.road_service_call(row))


@bp.post("/road-service-calls/<call_id>/dispatch")
@endpoint("DispatchCoordinator")
def dispatch_call(call_id):
    row = common.road_service_call(call_id)
    payload = v.body()
    dispatched_raw, dispatched_dt = v.s_datetime(payload, "dispatched_at")
    dispatch_miles = v.s_int(payload, "dispatch_miles", minimum=0, maximum=2000)
    technician_id = v.s_str(payload, "technician_id", required=False)
    tech = common.technician(technician_id) if technician_id is not None else None

    if row["dispatch_status"] != "OPEN":
        fail(errors.ERR_CALL_INVALID_STATE)
    if tech is not None and tech["service_location_id"] != row["service_location_id"]:
        fail(errors.ERR_TECHNICIAN_LOCATION_MISMATCH)
    if dispatched_dt < row["reported_at_dt"]:
        fail(errors.ERR_INVALID_TIMELINE)
    if tech is not None:
        if tech["status"] != "AVAILABLE":
            fail(errors.ERR_TECHNICIAN_UNAVAILABLE)
    else:
        tech = calc.select_technician(row)
        if tech is None:
            fail(errors.ERR_NO_TECHNICIAN_AVAILABLE)

    row["technician_id"] = tech["id"]
    row["dispatched_at"] = dispatched_raw
    row["dispatched_at_dt"] = dispatched_dt
    row["dispatch_miles"] = dispatch_miles
    row["dispatch_status"] = "DISPATCHED"
    touch(row)
    tech["status"] = "ON_CALL"
    touch(tech)
    vehicle_row = db.vehicles.get(row["vehicle_id"])
    if vehicle_row is not None:
        common.sync_vehicle_status(vehicle_row)
    return ok(serialize.road_service_call(row))


@bp.post("/road-service-calls/<call_id>/arrive")
@endpoint("TireTechnician")
def arrive_call(call_id):
    row = common.road_service_call(call_id)
    _technician_scope(row)
    payload = v.body()
    arrived_raw, arrived_dt = v.s_datetime(payload, "arrived_at")
    if row["dispatch_status"] != "DISPATCHED":
        fail(errors.ERR_CALL_INVALID_STATE)
    if arrived_dt < row["dispatched_at_dt"]:
        fail(errors.ERR_INVALID_TIMELINE)

    row["arrived_at"] = arrived_raw
    row["arrived_at_dt"] = arrived_dt
    row["dispatch_status"] = "ON_SITE"
    location_row = db.service_locations.get(row["service_location_id"])
    committed, actual, sla_met = calc.response_metrics(
        row, location_row, _call_agreement(row)
    )
    row["committed_response_minutes"] = committed
    row["actual_response_minutes"] = actual
    row["sla_met"] = sla_met
    touch(row)
    return ok(serialize.road_service_call(row))


@bp.post("/road-service-calls/<call_id>/complete")
@endpoint("TireTechnician")
def complete_call(call_id):
    row = common.road_service_call(call_id)
    _technician_scope(row)
    payload = v.body()
    closed_raw, closed_dt = v.s_datetime(payload, "closed_at")
    labor_hours = v.s_quarter_hours(payload, "labor_hours")
    replaced_asset_id = v.s_str(payload, "replaced_tire_asset_id", required=False)
    replacement_casing_id = v.s_str(payload, "replacement_casing_id", required=False)
    replacement_brand = v.s_str(payload, "replacement_brand", required=False)
    replacement_cost_basis_cents = v.s_int(
        payload, "replacement_cost_basis_cents", required=False, minimum=0
    )
    replaced_asset = common.tire_asset(replaced_asset_id) if replaced_asset_id else None
    replacement_casing = common.casing(replacement_casing_id) if replacement_casing_id else None

    if row["dispatch_status"] != "ON_SITE":
        fail(errors.ERR_CALL_INVALID_STATE)
    if replaced_asset is not None:
        if replaced_asset["status"] not in ("MOUNTED", "PULL_FLAGGED"):
            fail(errors.ERR_TIRE_ASSET_INVALID_STATE)
        if replaced_asset["vehicle_id"] != row["vehicle_id"]:
            fail(errors.ERR_TIRE_ASSET_INVALID_STATE)
        if replaced_asset["fleet_account_id"] != row["fleet_account_id"]:
            fail(errors.ERR_FLEET_MISMATCH)
    if replacement_casing is not None and (
        replacement_casing["fleet_account_id"] != row["fleet_account_id"]
    ):
        fail(errors.ERR_FLEET_MISMATCH)
    if closed_dt < row["arrived_at_dt"]:
        fail(errors.ERR_INVALID_TIMELINE)

    policy = None
    if replaced_asset is not None and replacement_casing is not None:
        policy = derive.find_policy(row["fleet_account_id"], replaced_asset["position"])
        if policy is None:
            fail(errors.ERR_TIRE_POLICY_MISSING)

    row["closed_at"] = closed_raw
    row["closed_at_dt"] = closed_dt
    row["labor_hours"] = labor_hours
    row["dispatch_status"] = "COMPLETED"
    gross_cents, sla_credit_cents, invoice_total_cents = calc.call_pricing(
        row, _call_agreement(row)
    )
    row["gross_cents"] = gross_cents
    row["sla_credit_cents"] = sla_credit_cents
    row["invoice_total_cents"] = invoice_total_cents
    touch(row)

    _release_technician(row)
    vehicle_row = db.vehicles.get(row["vehicle_id"])

    if replaced_asset is not None:
        # hop 1
        replaced_asset["status"] = "PULLED"
        replaced_asset["pull_reason"] = "ROAD_SERVICE_REPLACEMENT"
        touch(replaced_asset)
        if replacement_casing is not None:
            new_asset = insert(
                db.tire_assets,
                {
                    "fleet_account_id": row["fleet_account_id"],
                    "casing_id": replacement_casing["id"],
                    "brand": replacement_brand,
                    "cost_basis_cents": replacement_cost_basis_cents,
                    "vehicle_id": row["vehicle_id"],
                    "position": replaced_asset["position"],
                    "status": "MOUNTED",
                    "mounted_at": closed_raw,
                    "mounted_at_dt": closed_dt,
                    "odometer_at_mount": (
                        vehicle_row["current_odometer_miles"] if vehicle_row else None
                    ),
                    "tread_depth_at_mount_32nds": policy["new_tire_tread_depth_32nds"],
                    "replaced_tire_asset_id": replaced_asset["id"],
                    "pull_reason": None,
                },
            )
            if replacement_casing["status"] == "RETREADED":
                replacement_casing["status"] = "ON_WHEEL"
                replacement_casing["collected_at_location_id"] = None
                touch(replacement_casing)
        # hop 2 (and hop 3, which is a recomputed aggregate)
        pulled_casing = db.casings.get(replaced_asset["casing_id"])
        if pulled_casing is not None and pulled_casing["status"] == "ON_WHEEL":
            pulled_casing["status"] = "COLLECTED"
            pulled_casing["collected_at_location_id"] = row["service_location_id"]
            touch(pulled_casing)

    if vehicle_row is not None:
        common.sync_vehicle_status(vehicle_row)
    return ok(serialize.road_service_call(row))


@bp.post("/road-service-calls/<call_id>/cancel")
@endpoint("DispatchCoordinator")
def cancel_call(call_id):
    row = common.road_service_call(call_id)
    payload = v.body()
    cancel_reason = v.s_str(payload, "cancel_reason")
    if row["dispatch_status"] not in ("OPEN", "DISPATCHED"):
        fail(errors.ERR_CALL_INVALID_STATE)
    row["dispatch_status"] = "CANCELLED"
    row["cancel_reason"] = cancel_reason
    row["billing_status"] = "NON_BILLABLE"
    touch(row)
    _release_technician(row)
    vehicle_row = db.vehicles.get(row["vehicle_id"])
    if vehicle_row is not None:
        common.sync_vehicle_status(vehicle_row)
    return ok(serialize.road_service_call(row))


_CALL_READERS = (
    "DealerAdmin",
    "DispatchCoordinator",
    "TireTechnician",
    "FleetManager",
    "BillingClerk",
)


@bp.get("/road-service-calls/<call_id>")
@endpoint(*_CALL_READERS)
def get_call(call_id):
    row = common.road_service_call(call_id)
    fleet_scope(row["fleet_account_id"])
    return ok(serialize.road_service_call(row))


@bp.get("/road-service-calls")
@endpoint(*_CALL_READERS)
def list_calls():
    fleet_account_id = scope_filter_value(v.q_str("fleet_account_id"))
    rows = common.filtered(
        db.road_service_calls,
        [
            ("fleet_account_id", fleet_account_id),
            ("vehicle_id", v.q_str("vehicle_id")),
            ("service_location_id", v.q_str("service_location_id")),
            ("technician_id", v.q_str("technician_id")),
            ("cross_location_invoice_id", v.q_str("cross_location_invoice_id")),
            ("dispatch_status", v.q_enum("dispatch_status", derive.DISPATCH_STATUSES)),
            ("billing_status", v.q_enum("billing_status", derive.BILLING_STATUSES)),
            ("priority", v.q_enum("priority", ("NORMAL", "EMERGENCY"))),
        ],
    )
    return common.page(rows, serialize.road_service_call)


# ================================================================ ScrapManifest

@bp.post("/service-locations/<location_id>/scrap-manifests")
@endpoint("ComplianceOfficer")
def create_manifest(location_id):
    location_row = common.location(location_id)
    payload = v.body()
    hauler_permit_number = v.s_str(payload, "hauler_permit_number")
    hauler_capacity_lbs = v.s_int(payload, "hauler_capacity_lbs", minimum=1, maximum=40000)
    row = insert(
        db.scrap_manifests,
        {
            "service_location_id": location_row["id"],
            "hauler_permit_number": hauler_permit_number,
            "hauler_capacity_lbs": hauler_capacity_lbs,
            "manifest_number": db.next_manifest_number(),
            "status": "DRAFT",
            "signed_by_user_id": None,
            "signed_at": None,
            "signed_at_dt": None,
            "transported_at": None,
            "transported_at_dt": None,
            "hauler_vehicle_id": None,
            "certified_by_user_id": None,
            "certified_at": None,
            "certified_at_dt": None,
            "destruction_facility_code": None,
            "void_reason": None,
        },
    )
    return created(serialize.scrap_manifest(row))


@bp.post("/scrap-manifests/<manifest_id>/lines")
@endpoint("ComplianceOfficer")
def add_manifest_line(manifest_id):
    row = common.scrap_manifest(manifest_id)
    payload = v.body()
    casing_id = v.s_str(payload, "casing_id")
    casing_row = common.casing(casing_id)

    if row["status"] != "DRAFT":
        fail(errors.ERR_MANIFEST_INVALID_STATE)
    if casing_row["status"] != "REJECTED":
        fail(errors.ERR_CASING_NOT_SCRAP_ELIGIBLE)
    if casing_row["scrap_manifest_id"] is not None:
        fail(errors.ERR_CASING_ALREADY_ON_MANIFEST)
    _, total_weight = derive.manifest_totals(row["id"])
    if total_weight + casing_row["scrap_weight_lbs"] > row["hauler_capacity_lbs"]:
        fail(errors.ERR_MANIFEST_CAPACITY_EXCEEDED)

    casing_row["scrap_manifest_id"] = row["id"]
    touch(casing_row)
    touch(row)
    return ok(serialize.scrap_manifest(row))


@bp.post("/scrap-manifests/<manifest_id>/sign")
@endpoint("ComplianceOfficer")
def sign_manifest(manifest_id):
    row = common.scrap_manifest(manifest_id)
    payload = v.body()
    signed_raw, signed_dt = v.s_datetime(payload, "signed_at")

    if row["status"] != "DRAFT":
        fail(errors.ERR_MANIFEST_INVALID_STATE)

    location_row = db.service_locations.get(row["service_location_id"])
    if location_row is not None and location_row["scrap_permit_expires_on_d"] < db.clock_date():
        fail(errors.ERR_SCRAP_PERMIT_EXPIRED)

    casings = derive.manifest_casings(row["id"])
    for casing_row in casings:
        if casing_row["inspected_by_user_id"] == g.user_id:
            fail(errors.ERR_SOD_INSPECTOR_CANNOT_SIGN)
    for casing_row in casings:
        if casing_row["status"] != "REJECTED":
            fail(errors.ERR_CASING_NOT_SCRAP_ELIGIBLE)
    if len(casings) < 1:
        fail(errors.ERR_MANIFEST_EMPTY)

    row["status"] = "SIGNED"
    row["signed_by_user_id"] = g.user_id
    row["signed_at"] = signed_raw
    row["signed_at_dt"] = signed_dt
    touch(row)
    return ok(serialize.scrap_manifest(row))


@bp.post("/scrap-manifests/<manifest_id>/transport")
@endpoint("ComplianceOfficer")
def transport_manifest(manifest_id):
    row = common.scrap_manifest(manifest_id)
    payload = v.body()
    transported_raw, transported_dt = v.s_datetime(payload, "transported_at")
    hauler_vehicle_id = v.s_str(payload, "hauler_vehicle_id")
    if row["status"] != "SIGNED":
        fail(errors.ERR_MANIFEST_INVALID_STATE)
    if transported_dt < row["signed_at_dt"]:
        fail(errors.ERR_INVALID_TIMELINE)
    row["status"] = "TRANSPORTED"
    row["transported_at"] = transported_raw
    row["transported_at_dt"] = transported_dt
    row["hauler_vehicle_id"] = hauler_vehicle_id
    touch(row)
    return ok(serialize.scrap_manifest(row))


@bp.post("/scrap-manifests/<manifest_id>/certify-destruction")
@endpoint("ComplianceOfficer")
def certify_manifest(manifest_id):
    row = common.scrap_manifest(manifest_id)
    payload = v.body()
    certified_raw, certified_dt = v.s_datetime(payload, "certified_at")
    destruction_facility_code = v.s_str(payload, "destruction_facility_code")

    if row["status"] != "TRANSPORTED":
        fail(errors.ERR_MANIFEST_INVALID_STATE)
    if row["signed_by_user_id"] == g.user_id:
        fail(errors.ERR_SOD_SIGNER_CANNOT_CERTIFY)
    if certified_dt < row["transported_at_dt"]:
        fail(errors.ERR_INVALID_TIMELINE)

    casings = ordered(derive.manifest_casings(row["id"]))
    expiries = []
    per_fleet = {}
    for casing_row in casings:
        credit = derive.casing_provisional_credit_cents(casing_row["id"])
        if credit != 0:
            expiries.append((casing_row, -credit))
            per_fleet[casing_row["fleet_account_id"]] = (
                per_fleet.get(casing_row["fleet_account_id"], 0) - credit
            )
    for fleet_account_id, delta in per_fleet.items():
        if derive.fleet_balance_cents(fleet_account_id) + delta < 0:
            fail(errors.ERR_CREDIT_BALANCE_NEGATIVE)

    # hop 1
    row["status"] = "CERTIFIED_DESTROYED"
    row["certified_by_user_id"] = g.user_id
    row["certified_at"] = certified_raw
    row["certified_at_dt"] = certified_dt
    row["destruction_facility_code"] = destruction_facility_code
    touch(row)

    # hop 2
    for casing_row in casings:
        if casing_row["status"] == "REJECTED":
            casing_row["status"] = "SCRAPPED"
            touch(casing_row)
        for asset in derive.casing_assets(casing_row["id"]):
            if asset["status"] == "PULLED":
                asset["status"] = "SCRAPPED"
                touch(asset)

    # hop 3
    for casing_row, amount in expiries:
        fleet_row = db.fleet_accounts.get(casing_row["fleet_account_id"])
        if fleet_row is None:
            continue
        common.post_entry(
            fleet_row,
            "EXPIRY",
            amount,
            "SCRAP_MANIFEST",
            row["id"],
            "Provisional casing credit expired on certified destruction",
            casing_id=casing_row["id"],
        )

    # hop 4
    for fleet_account_id in per_fleet:
        fleet_row = db.fleet_accounts.get(fleet_account_id)
        if fleet_row is not None:
            touch(fleet_row)
    return ok(serialize.scrap_manifest(row))


@bp.post("/scrap-manifests/<manifest_id>/void")
@endpoint("ComplianceOfficer")
def void_manifest(manifest_id):
    row = common.scrap_manifest(manifest_id)
    payload = v.body()
    void_reason = v.s_str(payload, "void_reason")
    if row["status"] not in ("DRAFT", "SIGNED"):
        fail(errors.ERR_MANIFEST_INVALID_STATE)
    was_signed = row["status"] == "SIGNED"
    for casing_row in derive.manifest_casings(row["id"]):
        casing_row["scrap_manifest_id"] = None
        touch(casing_row)
    row["status"] = "VOIDED"
    row["void_reason"] = void_reason
    if was_signed:
        row["signed_by_user_id"] = None
        row["signed_at"] = None
        row["signed_at_dt"] = None
    touch(row)
    return ok(serialize.scrap_manifest(row))


@bp.get("/scrap-manifests/<manifest_id>")
@endpoint("DealerAdmin", "ComplianceOfficer")
def get_manifest(manifest_id):
    return ok(serialize.scrap_manifest(common.scrap_manifest(manifest_id)))


@bp.get("/scrap-manifests")
@endpoint("DealerAdmin", "ComplianceOfficer")
def list_manifests():
    rows = common.filtered(
        db.scrap_manifests,
        [
            ("service_location_id", v.q_str("service_location_id")),
            ("status", v.q_enum("status", derive.MANIFEST_STATUSES)),
            ("hauler_permit_number", v.q_str("hauler_permit_number")),
        ],
    )
    return common.page(rows, serialize.scrap_manifest)


# ================================================================ CrossLocationInvoice

@bp.post("/cross-location-invoices")
@endpoint("BillingClerk")
def create_invoice():
    payload = v.body()
    fleet_account_id = v.s_str(payload, "fleet_account_id")
    start_raw, start_date = v.s_date(payload, "billing_period_start")
    end_raw, end_date = v.s_date(payload, "billing_period_end")
    expected_version = v.s_int(payload, "expected_fleet_account_version")
    fleet_row = common.fleet(fleet_account_id)

    if expected_version != fleet_row["version"]:
        fail(errors.ERR_STALE_FLEET_VERSION)
    if end_date < start_date or (end_date - start_date).days + 1 > 92:
        fail(errors.ERR_INVALID_BILLING_PERIOD)

    agreement = derive.active_agreement_on(fleet_row["id"], start_date)
    if agreement is None:
        fail(errors.ERR_NO_ACTIVE_AGREEMENT)

    lines = calc.billable_lines(fleet_row["id"], start_date, end_date)
    if not lines:
        fail(errors.ERR_NO_BILLABLE_LINES)

    money = calc.rollup(lines, agreement, derive.fleet_balance_cents(fleet_row["id"]))
    row = insert(
        db.cross_location_invoices,
        {
            "fleet_account_id": fleet_row["id"],
            "national_agreement_id": agreement["id"],
            "billing_period_start": start_raw,
            "billing_period_start_d": start_date,
            "billing_period_end": end_raw,
            "billing_period_end_d": end_date,
            "status": "OPEN",
            "subtotal_cents": money["subtotal_cents"],
            "discount_cents": money["discount_cents"],
            "net_before_credit_cents": money["net_before_credit_cents"],
            "credit_applied_cents": money["credit_applied_cents"],
            "total_cents": money["total_cents"],
            "paid_amount_cents": None,
            "dispute_reason": None,
        },
    )
    for call in lines:
        call["billing_status"] = "INVOICED"
        call["cross_location_invoice_id"] = row["id"]
        touch(call)
    touch(fleet_row)
    return created(serialize.cross_location_invoice(row))


@bp.post("/cross-location-invoices/<invoice_id>/submit")
@endpoint("BillingClerk")
def submit_invoice(invoice_id):
    row = common.invoice(invoice_id)
    if row["status"] != "OPEN":
        fail(errors.ERR_INVOICE_INVALID_STATE)
    agreement = db.national_agreements.get(row["national_agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        fail(errors.ERR_INVOICE_NOT_BILLABLE)
    if row["total_cents"] <= 0:
        fail(errors.ERR_INVOICE_NOT_BILLABLE)

    fleet_row = db.fleet_accounts.get(row["fleet_account_id"])
    applied = row["credit_applied_cents"]
    if applied > 0 and derive.fleet_balance_cents(fleet_row["id"]) - applied < 0:
        fail(errors.ERR_CREDIT_BALANCE_NEGATIVE)

    row["status"] = "SUBMITTED"
    touch(row)
    if applied > 0:
        common.post_entry(
            fleet_row,
            "APPLICATION",
            -applied,
            "CROSS_LOCATION_INVOICE",
            row["id"],
            "Casing credit applied to cross-location invoice",
            casing_id=None,
        )
    touch(fleet_row)
    for call in ordered(derive.invoice_calls(row["id"])):
        if call["billing_status"] == "INVOICED":
            call["billing_status"] = "BILLED_TO_NATIONAL"
            touch(call)
    return ok(serialize.cross_location_invoice(row))


@bp.post("/cross-location-invoices/<invoice_id>/settle")
@endpoint("BillingClerk")
def settle_invoice(invoice_id):
    row = common.invoice(invoice_id)
    payload = v.body()
    paid_amount_cents = v.s_int(payload, "paid_amount_cents", minimum=0)
    if row["status"] != "SUBMITTED":
        fail(errors.ERR_INVOICE_INVALID_STATE)
    if paid_amount_cents != row["total_cents"]:
        fail(errors.ERR_PAYMENT_AMOUNT_MISMATCH)
    row["status"] = "PAID"
    row["paid_amount_cents"] = paid_amount_cents
    touch(row)
    for call in ordered(derive.invoice_calls(row["id"])):
        if call["billing_status"] == "BILLED_TO_NATIONAL":
            call["billing_status"] = "SETTLED"
            touch(call)
    return ok(serialize.cross_location_invoice(row))


@bp.post("/cross-location-invoices/<invoice_id>/dispute")
@endpoint("FleetManager", "BillingClerk")
def dispute_invoice(invoice_id):
    row = common.invoice(invoice_id)
    fleet_scope(row["fleet_account_id"])
    payload = v.body()
    dispute_reason = v.s_str(payload, "dispute_reason")
    if row["status"] != "SUBMITTED":
        fail(errors.ERR_INVOICE_INVALID_STATE)

    fleet_row = db.fleet_accounts.get(row["fleet_account_id"])
    applied = row["credit_applied_cents"]
    claimed = ordered(derive.invoice_calls(row["id"]))

    row["status"] = "DISPUTED"
    row["dispute_reason"] = dispute_reason
    if applied > 0:
        common.post_entry(
            fleet_row,
            "REVERSAL",
            applied,
            "CROSS_LOCATION_INVOICE",
            row["id"],
            "Casing credit returned on invoice dispute",
            casing_id=None,
        )
        row["credit_applied_cents"] = 0
        row["total_cents"] = row["net_before_credit_cents"]
    touch(row)
    if fleet_row is not None:
        touch(fleet_row)
    for call in claimed:
        if call["billing_status"] == "BILLED_TO_NATIONAL":
            call["billing_status"] = "UNBILLED"
            call["cross_location_invoice_id"] = None
            touch(call)
    return ok(serialize.cross_location_invoice(row))


@bp.get("/cross-location-invoices/<invoice_id>")
@endpoint("DealerAdmin", "BillingClerk", "FleetManager")
def get_invoice(invoice_id):
    row = common.invoice(invoice_id)
    fleet_scope(row["fleet_account_id"])
    return ok(serialize.cross_location_invoice(row))


@bp.get("/cross-location-invoices")
@endpoint("DealerAdmin", "BillingClerk", "FleetManager")
def list_invoices():
    fleet_account_id = scope_filter_value(v.q_str("fleet_account_id"))
    rows = common.filtered(
        db.cross_location_invoices,
        [
            ("fleet_account_id", fleet_account_id),
            ("national_agreement_id", v.q_str("national_agreement_id")),
            ("status", v.q_enum("status", derive.INVOICE_STATUSES)),
        ],
    )
    return common.page(rows, serialize.cross_location_invoice)
