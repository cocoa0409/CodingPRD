"""Apportioned registration: distance schedules, fee apportionment, credential
issuance, mid-year fleet supplements, credential distribution, audit selection
and the retention-review cascade."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import serializers as S
from common import (
    ALL_ROLES,
    API_PREFIX,
    DB,
    LIGHT,
    VERSIONED,
    ZERO,
    D,
    authenticate,
    bad_request,
    carrier_scope_guard,
    collection,
    fail,
    find_or_404,
    fmt_instant,
    miles,
    money,
    need_date,
    need_enum,
    need_int,
    need_num,
    need_str,
    new_row,
    ok,
    parse_date,
    percent,
    q_int,
    q_str,
    ratio,
    raw_body,
    reject_unknown,
    touch,
    whole,
)
from routes_ref import get_carrier_or_404, get_vehicle_or_404
from routes_returns import _void_active_lines, _write_lines, rescore_not_selected

bp = Blueprint("registration", __name__)


def get_application_or_404(application_id):
    return find_or_404(DB.registration_applications, application_id,
                       "ERR_REGISTRATION_APPLICATION_NOT_FOUND")


def get_change_or_404(change_id):
    return find_or_404(DB.fleet_change_requests, change_id,
                       "ERR_FLEET_CHANGE_REQUEST_NOT_FOUND")


def get_credential_or_404(credential_id):
    return find_or_404(DB.credentials, credential_id, "ERR_CREDENTIAL_NOT_FOUND")


def get_selection_or_404(selection_id):
    return find_or_404(DB.audit_selections, selection_id,
                       "ERR_AUDIT_SELECTION_NOT_FOUND")


def get_driver_or_404(driver_id):
    return find_or_404(DB.drivers, driver_id, "ERR_DRIVER_NOT_FOUND")


def sync_credential_status(vehicle):
    """PRD §2.10 — Vehicle.credential_status is derived, never written by a
    client. Recomputes it in place and reports whether it actually moved, so a
    caller that is already mutating the row versions the row exactly once."""
    if vehicle is None:
        return False
    derived = calc.derive_credential_status(vehicle["id"])
    if vehicle["credential_status"] != derived:
        vehicle["credential_status"] = derived
        return True
    return False


def rederive_credential_status(vehicle):
    if sync_credential_status(vehicle):
        touch(vehicle)


def void_vehicle_credentials(vehicle, target_status, reason_code,
                             touch_vehicle=True):
    for credential in calc.vehicle_credentials(vehicle["id"]):
        if credential["credential_status"] not in ("ISSUED", "DISTRIBUTED"):
            continue
        credential["credential_status"] = target_status
        credential["voided_reason_code"] = reason_code
        touch(credential)
    changed = sync_credential_status(vehicle)
    if changed and touch_vehicle:
        touch(vehicle)
    return changed


# --------------------------------------------------------------------------
# Registration applications
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/registration-applications")
def create_registration_application():
    authenticate(["TaxPreparer"])
    body = raw_body()
    reject_unknown(body, {
        "carrier_id", "registration_year", "weight_group_code", "distance_basis",
    })

    # Step 4 — body foreign keys.
    if isinstance(body.get("carrier_id"), str):
        get_carrier_or_404(body["carrier_id"])

    # Step 5 — request shape.
    need_str(body, "carrier_id")
    registration_year = need_int(body, "registration_year", minimum=1)
    weight_group_code = need_str(body, "weight_group_code")
    distance_basis = need_enum(body, "distance_basis",
                               ("ACTUAL_DISTANCE_BASIS", "ESTIMATED_DISTANCE_BASIS"))
    carrier = get_carrier_or_404(body["carrier_id"])

    # Step 19 — one live application per carrier and year. A corrected
    # application does not block its replacement.
    for existing in DB.registration_applications.values():
        if existing["carrier_id"] != carrier["id"]:
            continue
        if existing["registration_year"] != registration_year:
            continue
        if existing["application_status"] == "RETURNED_FOR_CORRECTION":
            continue
        raise fail("ERR_DUPLICATE_APPLICATION_YEAR",
                   "The carrier already holds a live application for %s."
                   % registration_year)

    row = new_row(VERSIONED)
    row.update({
        "carrier_id": carrier["id"],
        "registration_year": registration_year,
        "weight_group_code": weight_group_code,
        "distance_basis": distance_basis,
        "application_status": "DRAFT",
        "prepared_by_user_id": g.user_id,
        "reviewed_by_user_id": None,
        "apportioned_vehicle_count": calc.apportioned_vehicle_count(
            carrier["id"], registration_year
        ),
        "fleet_total_distance_miles": miles(ZERO),
        "base_fee_total": money(ZERO),
        "total_apportioned_fee": money(ZERO),
        "apportion_frozen_at": None,
    })
    DB.registration_applications[row["id"]] = row
    return ok(S.registration_application_out(row), 201)


@bp.get(API_PREFIX + "/registration-applications/<row_id>")
def get_registration_application(row_id):
    authenticate(ALL_ROLES)
    return ok(S.registration_application_out(get_application_or_404(row_id)))


@bp.get(API_PREFIX + "/registration-applications")
def list_registration_applications():
    authenticate(ALL_ROLES)
    filters = {
        "carrier_id": q_str("carrier_id"),
        "registration_year": q_int("registration_year"),
        "application_status": q_str("application_status"),
        "distance_basis": q_str("distance_basis"),
    }
    return collection(DB.registration_applications.values(), filters,
                      ["registration_year"], S.registration_application_out)


# --------------------------------------------------------------------------
# Distance schedule
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/registration-applications/<row_id>/distance-schedule")
def add_distance_schedule_line(row_id):
    authenticate(["TaxPreparer"])
    application = get_application_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"jurisdiction_code", "reported_distance_miles"})

    # Step 5 — request shape.
    code = need_str(body, "jurisdiction_code")
    reported = need_num(body, "reported_distance_miles", minimum=0)

    # Step 6 — jurisdiction declaration.
    if calc.jurisdiction_by_code(code) is None:
        raise fail("ERR_JURISDICTION_NOT_DECLARED",
                   "Jurisdiction %s is not declared." % code)

    # Step 9 — state.
    if application["application_status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "Schedule lines cannot be added while the application is %s."
                   % application["application_status"])

    # Step 20 — at most one ACTIVE line per jurisdiction. A VOIDED line from an
    # earlier correction round does not block a fresh one.
    for line in calc.schedule_lines(application["id"], "ACTIVE"):
        if line["jurisdiction_code"] == code:
            raise fail("ERR_DUPLICATE_JURISDICTION_LINE",
                       "An active line for %s already exists on this application."
                       % code)

    row = new_row(LIGHT)
    row.update({
        "registration_application_id": application["id"],
        "jurisdiction_code": code,
        "reported_distance_miles": miles(reported),
        "effective_distance_miles": miles(ZERO),
        "apportion_percent": percent(ZERO),
        "jurisdiction_fee_amount": money(ZERO),
        "line_status": "ACTIVE",
    })
    DB.schedule_lines[row["id"]] = row
    return ok(S.schedule_line_out(row), 201)


@bp.get(API_PREFIX + "/registration-applications/<row_id>/distance-schedule")
def list_distance_schedule(row_id):
    authenticate(ALL_ROLES)
    application = get_application_or_404(row_id)
    rows = [
        l for l in DB.schedule_lines.values()
        if l["registration_application_id"] == application["id"]
    ]
    filters = {
        "jurisdiction_code": q_str("jurisdiction_code"),
        "line_status": q_str("line_status"),
    }
    return collection(rows, filters, ["jurisdiction_code"], S.schedule_line_out)


# --------------------------------------------------------------------------
# Submission
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/registration-applications/<row_id>/submit")
def submit_registration_application(row_id):
    authenticate(["TaxPreparer"])
    application = get_application_or_404(row_id)
    body = raw_body()
    reject_unknown(body, set())

    carrier = DB.carriers.get(application["carrier_id"])

    # Step 9 — the transition must exist, and the three substantive
    # preconditions of the submission are themselves state complaints.
    if application["application_status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "An application in %s cannot be submitted."
                   % application["application_status"])
    lines = calc.schedule_lines(application["id"], "ACTIVE")
    if not lines:
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "The application has no active distance schedule line.")
    base_code = carrier["base_jurisdiction_code"] if carrier else None
    if not any(l["jurisdiction_code"] == base_code for l in lines):
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "The schedule must report distance in the base jurisdiction %s."
                   % base_code)
    count = calc.apportioned_vehicle_count(
        application["carrier_id"], application["registration_year"]
    )
    if count < 1:
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "The carrier has no apportionable unit for %s."
                   % application["registration_year"])

    # Step 11 — IRP account liveness.
    if carrier is None or carrier["irp_account_status"] != "ACTIVE":
        raise fail("ERR_CARRIER_IRP_INACTIVE",
                   "The carrier's IRP account is not active.")

    application["apportioned_vehicle_count"] = count
    application["application_status"] = "SUBMITTED"
    touch(application)
    return ok(S.registration_application_out(application))


# --------------------------------------------------------------------------
# Review: invoicing and correction
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/registration-applications/<row_id>/review")
def review_registration_application(row_id):
    authenticate(["ComplianceOfficer"])
    application = get_application_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"decision", "review_note"})
    decision = need_enum(body, "decision", ("INVOICE", "RETURN_FOR_CORRECTION"))
    need_str(body, "review_note", required=False)

    # Step 9 — state.
    if application["application_status"] != "SUBMITTED":
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "An application in %s cannot be reviewed."
                   % application["application_status"])

    # Step 18 — segregation of duties.
    if (application["prepared_by_user_id"] is not None
            and application["prepared_by_user_id"] == g.user_id):
        raise fail("ERR_SEGREGATION_OF_DUTIES",
                   "The preparer of this application may not review it.")

    if decision == "RETURN_FOR_CORRECTION":
        for line in calc.schedule_lines(application["id"], "ACTIVE"):
            line["line_status"] = "VOIDED"
        application["fleet_total_distance_miles"] = miles(ZERO)
        application["base_fee_total"] = money(ZERO)
        application["total_apportioned_fee"] = money(ZERO)
        application["apportion_frozen_at"] = None
        application["application_status"] = "RETURNED_FOR_CORRECTION"
        application["reviewed_by_user_id"] = g.user_id
        touch(application)
        return ok(S.registration_application_out(application))

    # Step 27 — the fee chart must price every active line.
    lines = calc.schedule_lines(application["id"], "ACTIVE")
    for line in lines:
        if calc.weight_group_fee(line["jurisdiction_code"],
                                 application["weight_group_code"]) is None:
            raise fail("ERR_WEIGHT_GROUP_FEE_MISSING",
                       "No fee cell for (%s, %s)."
                       % (line["jurisdiction_code"], application["weight_group_code"]))

    calc.apportion_application(application)
    application["apportion_frozen_at"] = fmt_instant(DB.clock.now())
    application["application_status"] = "INVOICED"
    application["reviewed_by_user_id"] = g.user_id
    touch(application)

    # Cascade — every pending unit of the year joins the fleet.
    activated_on = DB.clock.today().isoformat()
    for vehicle in calc.carrier_vehicles(application["carrier_id"],
                                         application["registration_year"]):
        if vehicle["vehicle_status"] != "PENDING":
            continue
        vehicle["vehicle_status"] = "ACTIVE"
        vehicle["activated_on_date"] = activated_on
        touch(vehicle)
    return ok(S.registration_application_out(application))


# --------------------------------------------------------------------------
# Credential issuance
# --------------------------------------------------------------------------

CREDENTIAL_TYPES = ("DECAL_SET", "CAB_CARD", "IFTA_LICENSE_COPY")


@bp.post(API_PREFIX + "/registration-applications/<row_id>/issue-credentials")
def issue_credentials(row_id):
    authenticate(["ComplianceOfficer"])
    application = get_application_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"valid_from_date", "valid_to_date"})
    valid_from = need_date(body, "valid_from_date", required=False)
    valid_to = need_date(body, "valid_to_date", required=False)

    carrier = DB.carriers.get(application["carrier_id"])

    # Step 9 — state.
    if application["application_status"] != "INVOICED":
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "Credentials cannot be issued while the application is %s."
                   % application["application_status"])

    # Step 10 — a suspended licensee gets no new paper.
    if carrier is None or carrier["ifta_license_status"] != "ACTIVE":
        raise fail("ERR_CARRIER_LICENSE_INACTIVE",
                   "The carrier's IFTA licence is not active.")

    fleet = [
        v for v in calc.carrier_vehicles(application["carrier_id"],
                                         application["registration_year"])
        if v["vehicle_status"] == "ACTIVE"
    ]
    if not fleet:
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "The carrier has no active unit to print credentials for.")

    if valid_from is None:
        valid_from = DB.clock.today().isoformat()
    if valid_to is None:
        valid_to = calc.december_31(application["registration_year"])

    for vehicle in fleet:
        for credential_type in CREDENTIAL_TYPES:
            row = new_row(VERSIONED)
            row.update({
                "vehicle_id": vehicle["id"],
                "registration_application_id": application["id"],
                "distributed_to_driver_id": None,
                "credential_type": credential_type,
                "registration_year": application["registration_year"],
                "valid_from_date": valid_from,
                "valid_to_date": valid_to,
                "credential_status": "ISSUED",
                "distributed_at": None,
                "voided_reason_code": None,
            })
            DB.credentials[row["id"]] = row
        rederive_credential_status(vehicle)

    application["application_status"] = "ISSUED"
    touch(application)
    return ok(S.registration_application_out(application))


# --------------------------------------------------------------------------
# Mid-year fleet supplements
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/fleet-change-requests")
def create_fleet_change_request():
    authenticate(["CarrierAdmin", "TaxPreparer"])
    body = raw_body()
    reject_unknown(body, {
        "registration_application_id", "vehicle_id", "change_type",
        "effective_date", "replaced_vehicle_id",
        "expected_registration_application_version",
    })

    # Step 4 — body foreign keys, in the pinned body-field order.
    if isinstance(body.get("vehicle_id"), str):
        get_vehicle_or_404(body["vehicle_id"])
    if isinstance(body.get("replaced_vehicle_id"), str):
        get_vehicle_or_404(body["replaced_vehicle_id"])
    if isinstance(body.get("registration_application_id"), str):
        get_application_or_404(body["registration_application_id"])

    # Step 5 — request shape.
    need_str(body, "registration_application_id")
    need_str(body, "vehicle_id")
    change_type = need_enum(body, "change_type", ("ADDITION", "DELETION", "TRANSFER"))
    effective_date = need_date(body, "effective_date")
    replaced_vehicle_id = need_str(body, "replaced_vehicle_id", required=False)
    if change_type == "TRANSFER" and replaced_vehicle_id is None:
        raise bad_request("Field 'replaced_vehicle_id' is required for a TRANSFER.")
    if change_type != "TRANSFER" and replaced_vehicle_id is not None:
        raise bad_request(
            "Field 'replaced_vehicle_id' must be null for a %s." % change_type
        )
    expected = need_int(body, "expected_registration_application_version")

    application = get_application_or_404(body["registration_application_id"])
    vehicle = get_vehicle_or_404(body["vehicle_id"])
    if replaced_vehicle_id is not None:
        get_vehicle_or_404(replaced_vehicle_id)

    # Step 7 — carrier scope, against the parent application's carrier.
    carrier_scope_guard(application["carrier_id"])

    # Step 8 — optimistic concurrency on the fee basis.
    if application["version"] != expected:
        raise fail("ERR_STALE_APPLICATION_VERSION",
                   "The application has moved on since it was read.")

    row = new_row(VERSIONED)
    row.update({
        "registration_application_id": application["id"],
        "vehicle_id": vehicle["id"],
        "replaced_vehicle_id": replaced_vehicle_id,
        "change_type": change_type,
        "effective_date": effective_date,
        "prorate_months": 0,
        "fee_delta": money(ZERO),
        "change_status": "REQUESTED",
        "requested_by_user_id": g.user_id,
        "decided_by_user_id": None,
        "reversal_reason_code": None,
    })
    DB.fleet_change_requests[row["id"]] = row
    touch(application)
    return ok(S.fleet_change_request_out(row), 201)


@bp.get(API_PREFIX + "/fleet-change-requests/<row_id>")
def get_fleet_change_request(row_id):
    authenticate(ALL_ROLES)
    return ok(S.fleet_change_request_out(get_change_or_404(row_id)))


@bp.get(API_PREFIX + "/fleet-change-requests")
def list_fleet_change_requests():
    authenticate(ALL_ROLES)
    filters = {
        "registration_application_id": q_str("registration_application_id"),
        "vehicle_id": q_str("vehicle_id"),
        "replaced_vehicle_id": q_str("replaced_vehicle_id"),
        "change_type": q_str("change_type"),
        "change_status": q_str("change_status"),
    }
    return collection(DB.fleet_change_requests.values(), filters,
                      ["effective_date"], S.fleet_change_request_out)


# --------------------------------------------------------------------------
# Deciding a supplement
# --------------------------------------------------------------------------


def _restate_application(application, count_delta):
    application["apportioned_vehicle_count"] = (
        application["apportioned_vehicle_count"] + count_delta
    )
    calc.refresh_total_apportioned_fee(application)
    touch(application)


@bp.post(API_PREFIX + "/fleet-change-requests/<row_id>/decide")
def decide_fleet_change_request(row_id):
    authenticate(["ComplianceOfficer"])
    change = get_change_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"decision", "decision_note"})
    decision = need_enum(body, "decision", ("APPROVE", "REJECT"))
    need_str(body, "decision_note", required=False)

    application = DB.registration_applications.get(
        change["registration_application_id"]
    )
    carrier = DB.carriers.get(application["carrier_id"]) if application else None
    vehicle = DB.vehicles.get(change["vehicle_id"])
    outgoing = DB.vehicles.get(change["replaced_vehicle_id"]) \
        if change["replaced_vehicle_id"] else None

    # Step 9 — state.
    if change["change_status"] != "REQUESTED":
        raise fail("ERR_CHANGE_REQUEST_NOT_PENDING",
                   "A request in %s cannot be decided." % change["change_status"])

    if decision == "REJECT":
        change["change_status"] = "REJECTED"
        change["decided_by_user_id"] = g.user_id
        touch(change)
        if application is not None:
            touch(application)
        return ok(S.fleet_change_request_out(change))

    if application is None or application["application_status"] not in ("INVOICED", "ISSUED"):
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "A supplement can only be priced against frozen percentages.")

    # Step 11 — IRP account liveness.
    if carrier is None or carrier["irp_account_status"] != "ACTIVE":
        raise fail("ERR_CARRIER_IRP_INACTIVE",
                   "The carrier's IRP account is not active.")

    # Step 12 — the units must be in the states the change type requires.
    change_type = change["change_type"]
    if change_type in ("ADDITION", "TRANSFER"):
        if vehicle is None or vehicle["vehicle_status"] != "PENDING":
            raise fail("ERR_VEHICLE_STATE_INCOMPATIBLE",
                       "The incoming unit must be PENDING for a %s." % change_type)
    if change_type == "DELETION":
        if vehicle is None or vehicle["vehicle_status"] != "ACTIVE":
            raise fail("ERR_VEHICLE_STATE_INCOMPATIBLE",
                       "The unit must be ACTIVE for a DELETION.")
    if change_type == "TRANSFER":
        if outgoing is None or outgoing["vehicle_status"] != "ACTIVE":
            raise fail("ERR_VEHICLE_STATE_INCOMPATIBLE",
                       "The outgoing unit must be ACTIVE for a TRANSFER.")

    # Step 23 — the change must land inside the registration year.
    effective = parse_date(change["effective_date"])
    if effective is None or effective.year != application["registration_year"]:
        raise fail("ERR_EFFECTIVE_DATE_OUT_OF_YEAR",
                   "%s is outside registration year %s."
                   % (change["effective_date"], application["registration_year"]))

    prorate_months, fee_delta = calc.fleet_change_fee_delta(
        application, change_type, change["effective_date"]
    )
    change["prorate_months"] = prorate_months
    change["fee_delta"] = fee_delta
    change["change_status"] = "APPROVED"
    change["decided_by_user_id"] = g.user_id
    touch(change)

    if change_type == "ADDITION":
        _restate_application(application, 1)
        vehicle["vehicle_status"] = "ACTIVE"
        vehicle["activated_on_date"] = change["effective_date"]
        touch(vehicle)
    elif change_type == "DELETION":
        _restate_application(application, -1)
        vehicle["vehicle_status"] = "DELETED"
        void_vehicle_credentials(vehicle, "VOIDED", "FLEET_DELETION",
                                 touch_vehicle=False)
        touch(vehicle)
    else:
        _restate_application(application, 0)
        vehicle["vehicle_status"] = "ACTIVE"
        vehicle["activated_on_date"] = change["effective_date"]
        vehicle["replaced_vehicle_id"] = outgoing["id"]
        touch(vehicle)
        outgoing["vehicle_status"] = "TRANSFERRED"
        void_vehicle_credentials(outgoing, "REPLACED", "TRANSFER_REPLACEMENT",
                                 touch_vehicle=False)
        touch(outgoing)
    return ok(S.fleet_change_request_out(change))


# --------------------------------------------------------------------------
# Reversing a supplement
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/fleet-change-requests/<row_id>/reverse")
def reverse_fleet_change_request(row_id):
    authenticate(["ComplianceOfficer"])
    change = get_change_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"reversal_reason_code"})
    reason = need_enum(body, "reversal_reason_code",
                       ("CLERICAL_ERROR", "VEHICLE_NOT_DELIVERED",
                        "JURISDICTION_REJECTION"))

    application = DB.registration_applications.get(
        change["registration_application_id"]
    )
    vehicle = DB.vehicles.get(change["vehicle_id"])

    # Step 9 — state.
    if change["change_status"] != "APPROVED":
        raise fail("ERR_CHANGE_REQUEST_NOT_PENDING",
                   "A request in %s cannot be reversed." % change["change_status"])
    if application is None or application["application_status"] not in ("INVOICED", "ISSUED"):
        raise fail("ERR_INVALID_APPLICATION_STATE",
                   "The parent application is no longer open to supplements.")

    # Step 13 — an approved transfer is terminal on the outgoing unit.
    if change["change_type"] == "TRANSFER":
        raise fail("ERR_TRANSFER_NOT_REVERSIBLE",
                   "An approved transfer cannot be reversed.")

    change["change_status"] = "REVERSED"
    change["reversal_reason_code"] = reason
    change["decided_by_user_id"] = g.user_id
    touch(change)

    # The fee total is recomputed from the whole remaining APPROVED set, so it
    # returns to exactly its pre-approval value; fee_delta stays as audit trail.
    if change["change_type"] == "ADDITION":
        _restate_application(application, -1)
        if vehicle is not None:
            vehicle["vehicle_status"] = "PENDING"
            vehicle["activated_on_date"] = None
            touch(vehicle)
    else:
        _restate_application(application, 1)
        if vehicle is not None:
            vehicle["vehicle_status"] = "ACTIVE"
            touch(vehicle)
    return ok(S.fleet_change_request_out(change))


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------


@bp.get(API_PREFIX + "/credentials/<row_id>")
def get_credential(row_id):
    authenticate(ALL_ROLES)
    return ok(S.credential_out(get_credential_or_404(row_id)))


@bp.get(API_PREFIX + "/credentials")
def list_credentials():
    authenticate(ALL_ROLES)
    filters = {
        "vehicle_id": q_str("vehicle_id"),
        "registration_application_id": q_str("registration_application_id"),
        "distributed_to_driver_id": q_str("distributed_to_driver_id"),
        "credential_type": q_str("credential_type"),
        "credential_status": q_str("credential_status"),
        "registration_year": q_int("registration_year"),
    }
    return collection(DB.credentials.values(), filters, [], S.credential_out)


@bp.post(API_PREFIX + "/credentials/<row_id>/distribute")
def distribute_credential(row_id):
    authenticate(["CarrierAdmin", "ComplianceOfficer"])
    credential = get_credential_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"distributed_to_driver_id"})

    # Step 4 — body foreign keys.
    if isinstance(body.get("distributed_to_driver_id"), str):
        get_driver_or_404(body["distributed_to_driver_id"])

    # Step 5 — request shape.
    need_str(body, "distributed_to_driver_id")
    driver = get_driver_or_404(body["distributed_to_driver_id"])

    vehicle = DB.vehicles.get(credential["vehicle_id"])

    # Step 7 — carrier scope, through the credential's vehicle.
    carrier_scope_guard(vehicle["carrier_id"] if vehicle else None)

    # Step 9 — state.
    if credential["credential_status"] != "ISSUED":
        raise fail("ERR_CREDENTIAL_NOT_ISSUED",
                   "A credential in %s cannot be handed over."
                   % credential["credential_status"])

    # Step 21 — the driver must belong to the unit's carrier and be live.
    if vehicle is None or driver["carrier_id"] != vehicle["carrier_id"]:
        raise fail("ERR_DRIVER_CARRIER_MISMATCH",
                   "The driver does not belong to the unit's carrier.")
    if driver["driver_status"] != "ACTIVE":
        raise fail("ERR_DRIVER_CARRIER_MISMATCH",
                   "The driver is not active.")

    # Step 25 — buffered, closed-interval handover geometry.
    new_from = parse_date(credential["valid_from_date"])
    new_to = parse_date(credential["valid_to_date"])
    if new_from is not None and new_to is not None:
        clash = calc.credential_window_conflict(
            driver["id"], credential["credential_type"], new_from, new_to,
            exclude_credential_id=credential["id"],
        )
        if clash is not None:
            raise fail("ERR_DRIVER_CREDENTIAL_WINDOW_CONFLICT",
                       "The driver already holds a %s covering %s to %s."
                       % (credential["credential_type"], clash["valid_from_date"],
                          clash["valid_to_date"]))

    credential["credential_status"] = "DISTRIBUTED"
    credential["distributed_to_driver_id"] = driver["id"]
    credential["distributed_at"] = fmt_instant(DB.clock.now())
    touch(credential)
    rederive_credential_status(vehicle)
    return ok(S.credential_out(credential))


# --------------------------------------------------------------------------
# Audit selection
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/audit-selections")
def create_audit_selection():
    authenticate(["ComplianceOfficer"])
    body = raw_body()
    reject_unknown(body, {
        "carrier_id", "selection_year", "selection_quarter",
        "late_filing_count", "retention_deficiency_count",
    })

    # Step 4 — body foreign keys.
    if isinstance(body.get("carrier_id"), str):
        get_carrier_or_404(body["carrier_id"])

    # Step 5 — request shape.
    need_str(body, "carrier_id")
    selection_year = need_int(body, "selection_year", minimum=1)
    selection_quarter = need_int(body, "selection_quarter", choices=(1, 2, 3, 4))
    late_filing_count = need_int(body, "late_filing_count", required=False,
                                 default=0, minimum=0)
    retention_deficiency_count = need_int(body, "retention_deficiency_count",
                                          required=False, default=0, minimum=0)
    carrier = get_carrier_or_404(body["carrier_id"])

    # Step 19 — one scoring per carrier and period.
    for existing in DB.audit_selections.values():
        if (existing["carrier_id"] == carrier["id"]
                and existing["selection_year"] == selection_year
                and existing["selection_quarter"] == selection_quarter):
            raise fail("ERR_DUPLICATE_AUDIT_PERIOD",
                       "The carrier is already scored for %s Q%s."
                       % (selection_year, selection_quarter))

    risk_score = calc.audit_risk_score(carrier, late_filing_count,
                                       retention_deficiency_count)
    selected = risk_score >= calc.AUDIT_SELECTION_THRESHOLD

    row = new_row(VERSIONED)
    row.update({
        "carrier_id": carrier["id"],
        "selection_year": selection_year,
        "selection_quarter": selection_quarter,
        "late_filing_count": late_filing_count,
        "retention_deficiency_count": retention_deficiency_count,
        "risk_score": risk_score,
        "post_review_risk_score": None,
        "expected_records_count": None,
        "records_missing_count": None,
        "retention_deficiency_ratio": None,
        "selection_status": "SELECTED" if selected else "NOT_SELECTED",
        "reviewed_by_user_id": None,
    })
    DB.audit_selections[row["id"]] = row

    if selected:
        carrier["audit_flag"] = True
        touch(carrier)
    return ok(S.audit_selection_out(row), 201)


# --------------------------------------------------------------------------
# Retention review — the deepest cascade in the system
# --------------------------------------------------------------------------


def _resettle_on_audit_basis(ret, carrier):
    """First cascade hop — the filed quarter is recomputed with reconstructed
    legs uplifted, and the difference is recorded as the assessment."""
    filed_total = ret["total_amount_due"]
    settlement = calc.settle_quarter(
        carrier["id"], ret["filing_year"], ret["filing_quarter"], "AUDIT_BASIS"
    )
    _void_active_lines(ret["id"])
    _write_lines(ret["id"], settlement["lines"])
    ret["settlement_basis"] = "AUDIT_BASIS"
    ret["total_fleet_miles"] = settlement["total_fleet_miles"]
    ret["total_tax_paid_gallons"] = settlement["total_tax_paid_gallons"]
    ret["fleet_mpg"] = settlement["fleet_mpg"]
    ret["reconstructed_mileage_ratio"] = settlement["reconstructed_mileage_ratio"]
    ret["total_net_tax_due"] = settlement["total_net_tax_due"]
    ret["reconstruction_penalty_amount"] = settlement["reconstruction_penalty_amount"]
    ret["total_amount_due"] = settlement["total_amount_due"]
    ret["audit_assessment_delta"] = money(
        settlement["total_amount_due"] - filed_total
    )
    ret["return_status"] = "AUDIT_ADJUSTED"
    touch(ret)


def _void_ifta_license_copies(carrier):
    affected = []
    for credential in DB.credentials.values():
        if credential["credential_type"] != "IFTA_LICENSE_COPY":
            continue
        if credential["credential_status"] not in ("ISSUED", "DISTRIBUTED"):
            continue
        vehicle = DB.vehicles.get(credential["vehicle_id"])
        if vehicle is None or vehicle["carrier_id"] != carrier["id"]:
            continue
        credential["credential_status"] = "VOIDED"
        credential["voided_reason_code"] = "LICENSE_SUSPENSION"
        touch(credential)
        if vehicle["id"] not in [v["id"] for v in affected]:
            affected.append(vehicle)
    for vehicle in affected:
        rederive_credential_status(vehicle)


def _deactivate_drivers(carrier):
    """Final hop — an IRP suspension takes the carrier's drivers off the road."""
    for driver in DB.drivers.values():
        if driver["carrier_id"] != carrier["id"]:
            continue
        if driver["driver_status"] != "ACTIVE":
            continue
        driver["driver_status"] = "INACTIVE"
        touch(driver)


def _react_to_post_review_score(carrier, post_review_score, deficiency_ratio):
    """Second cascade hop — the two licence dimensions react independently."""
    if post_review_score < calc.LICENSE_SUSPENSION_THRESHOLD:
        return
    current = carrier["ifta_license_status"]
    revoke = False
    if current == "ACTIVE":
        revoke = deficiency_ratio == 1
        carrier["ifta_license_status"] = "REVOKED" if revoke else "SUSPENDED"
    elif current == "SUSPENDED":
        revoke = True
        carrier["ifta_license_status"] = "REVOKED"
    else:
        return
    carrier["suspension_count"] = carrier["suspension_count"] + 1
    _void_ifta_license_copies(carrier)
    irp_suspended = False
    if revoke and carrier["irp_account_status"] == "ACTIVE":
        carrier["irp_account_status"] = "SUSPENDED"
        irp_suspended = True
    touch(carrier)
    if irp_suspended:
        _deactivate_drivers(carrier)


@bp.post(API_PREFIX + "/audit-selections/<row_id>/retention-review")
def retention_review(row_id):
    authenticate(["ComplianceOfficer"])
    selection = get_selection_or_404(row_id)
    body = raw_body()
    reject_unknown(body, {"expected_records_count", "records_missing_count"})
    expected_records = need_int(body, "expected_records_count", minimum=1)
    records_missing = need_int(body, "records_missing_count", minimum=0,
                              maximum=expected_records)

    carrier = DB.carriers.get(selection["carrier_id"])

    # Step 9 — state.
    if selection["selection_status"] != "SELECTED":
        raise fail("ERR_AUDIT_SELECTION_NOT_SELECTED",
                   "A selection in %s cannot be retention-reviewed."
                   % selection["selection_status"])

    # Step 28 — there must be a filed basis to audit against.
    target = None
    for ret in DB.fuel_tax_returns.values():
        if ret["carrier_id"] != selection["carrier_id"]:
            continue
        if ret["filing_year"] != selection["selection_year"]:
            continue
        if ret["filing_quarter"] != selection["selection_quarter"]:
            continue
        if ret["return_status"] != "FILED":
            continue
        target = ret
        break
    if target is None:
        raise fail("ERR_NO_FILED_RETURN_FOR_PERIOD",
                   "No filed return covers %s Q%s."
                   % (selection["selection_year"], selection["selection_quarter"]))

    deficiency_ratio = ratio(D(records_missing) / D(expected_records))
    post_review_score = calc.post_review_score(selection["risk_score"],
                                               deficiency_ratio)

    selection["expected_records_count"] = expected_records
    selection["records_missing_count"] = records_missing
    selection["retention_deficiency_ratio"] = deficiency_ratio
    selection["post_review_risk_score"] = post_review_score
    selection["selection_status"] = "RETENTION_REVIEWED"
    selection["reviewed_by_user_id"] = g.user_id
    touch(selection)

    _resettle_on_audit_basis(target, carrier)
    _react_to_post_review_score(carrier, post_review_score, deficiency_ratio)
    return ok(S.audit_selection_out(selection))
