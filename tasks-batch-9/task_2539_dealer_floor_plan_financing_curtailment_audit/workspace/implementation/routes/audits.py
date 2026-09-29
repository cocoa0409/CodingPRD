"""Physical inventory audits, the observation log, the out-of-trust cascade and
the incident read surface (PRD 3.6)."""

from flask import Blueprint

import db
import lookup
import middleware
import response
import validate
from errors import ApiError
from services import calc, ledger, serial, spec

bp = Blueprint("audits", __name__)

READ_ROLES = middleware.ALL_ROLES

INCIDENT_READ_ROLES = (
    middleware.CREDIT_OFFICER,
    middleware.CREDIT_RISK_MANAGER,
    middleware.AUDIT_MANAGER,
    middleware.DEALER_PRINCIPAL,
    middleware.SYSTEM_OPERATOR,
)


def _windows_intersect(start_a, end_a, start_b, end_b):
    """Closed intervals: touching endpoints collide."""
    return start_a <= end_b and start_b <= end_a


@bp.route("/floorplan/audits", methods=["POST"])
def schedule_audit():
    middleware.require(middleware.AUDIT_MANAGER)
    data = validate.body()
    dealer_id = validate.req_ref(data, "dealer_id")
    middleware.guard_dealer_id(dealer_id)
    dealer = lookup.dealer(dealer_id)
    audit_type = validate.req_enum(data, "audit_type", spec.AUDIT_TYPES)
    window_start = validate.req_instant(data, "window_start_date")
    window_end = validate.req_instant(data, "window_end_date")

    start_day = db.day_of(window_start)
    end_day = db.day_of(window_end)

    if audit_type == "ANNOUNCED":
        if (start_day - db.day_of(db.now())).days < spec.ANNOUNCED_NOTICE_DAYS:
            raise ApiError("ERR_AUDIT_NOTICE_TOO_SHORT")
    else:
        reconciled = [
            a
            for a in db.rows("audits")
            if a["dealer_id"] == dealer["id"] and a["status"] in spec.RECONCILED_AUDIT_STATUSES
        ]
        if reconciled:
            latest = max(reconciled, key=lambda a: (a["window_end_date"], a["_seq"]))
            latest_end = db.day_of(db.parse_instant(latest["window_end_date"]))
            if (start_day - latest_end).days < spec.UNANNOUNCED_MIN_GAP_DAYS:
                raise ApiError("ERR_AUDIT_GAP_TOO_SHORT")

    if end_day < start_day:
        raise ApiError("ERR_UNANNOUNCED_WINDOW_INVALID")
    if audit_type == "UNANNOUNCED" and (end_day - start_day).days > spec.UNANNOUNCED_MAX_SPAN_DAYS:
        raise ApiError("ERR_UNANNOUNCED_WINDOW_INVALID")

    for other in db.rows("audits"):
        if other["dealer_id"] != dealer["id"]:
            continue
        if other["status"] not in spec.BLOCKING_AUDIT_STATUSES:
            continue
        if _windows_intersect(
            start_day,
            end_day,
            db.day_of(db.parse_instant(other["window_start_date"])),
            db.day_of(db.parse_instant(other["window_end_date"])),
        ):
            raise ApiError("ERR_AUDIT_WINDOW_OVERLAP")

    record = db.insert(
        "audits",
        {
            "dealer_id": dealer["id"],
            "audit_type": audit_type,
            "status": "SCHEDULED",
            "window_start_date": db.fmt_instant(window_start),
            "window_end_date": db.fmt_instant(window_end),
            "started_at": None,
            "reconciled_at": None,
            "units_in_scope_count": 0,
            "units_verified_count": 0,
            "units_exception_count": 0,
            "units_unobserved_count": 0,
            "sot_exposure_cents": 0,
            "observer_user_ids": [],
            "reconciled_by_user_id": None,
            "abort_reason_code": None,
            "_scope_unit_ids": [],
        },
    )
    return response.created(serial.audit(record))


@bp.route("/floorplan/audits/<audit_id>/start", methods=["POST"])
def start_audit(audit_id):
    middleware.require(middleware.FIELD_AUDITOR)
    audit = lookup.audit(audit_id)
    dealer = db.get("dealers", audit["dealer_id"])
    if audit["status"] != "SCHEDULED":
        raise ApiError("ERR_AUDIT_NOT_IN_PROGRESS")
    if dealer["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_DEALER_NOT_ACTIVE")
    today = db.day_of(db.now())
    if not (
        db.day_of(db.parse_instant(audit["window_start_date"]))
        <= today
        <= db.day_of(db.parse_instant(audit["window_end_date"]))
    ):
        raise ApiError("ERR_AUDIT_WINDOW_NOT_OPEN")
    if dealer["audit_in_progress"]:
        raise ApiError("ERR_AUDIT_NOT_IN_PROGRESS", "The dealership already has a count in flight.")

    scope = [
        u
        for u in ledger.dealer_units(dealer["id"])
        if u["funding_status"] in spec.COLLATERAL_FUNDING_STATUSES
    ]
    audit["status"] = "IN_PROGRESS"
    audit["_scope_unit_ids"] = [u["id"] for u in scope]
    audit["units_in_scope_count"] = len(scope)
    audit["units_unobserved_count"] = len(scope)
    audit["units_verified_count"] = 0
    audit["units_exception_count"] = 0
    audit["started_at"] = db.now_str()
    db.touch(audit)
    dealer["audit_in_progress"] = True
    db.touch(dealer)
    return response.ok(serial.audit(audit))


@bp.route("/floorplan/audits/<audit_id>/observations", methods=["POST"])
def record_observation(audit_id):
    user_id, _role = middleware.require(middleware.FIELD_AUDITOR)
    audit = lookup.audit(audit_id)
    data = validate.body()
    unit = lookup.unit(validate.req_ref(data, "unit_id"))
    observed_condition = validate.req_enum(data, "observed_condition", spec.OBSERVED_CONDITIONS)
    title_verified = validate.req_bool(data, "title_verified")
    odometer = validate.opt_int(data, "odometer_miles", minimum=0)
    sale_reference = validate.opt_str(data, "sale_contract_reference")

    if audit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_AUDIT_NOT_IN_PROGRESS")
    if unit["funding_status"] not in spec.COLLATERAL_FUNDING_STATUSES:
        raise ApiError("ERR_UNIT_NOT_FLOORED")
    for existing in db.rows("observations"):
        if existing["audit_id"] == audit["id"] and existing["unit_id"] == unit["id"]:
            raise ApiError("ERR_DUPLICATE_OBSERVATION")
    if unit["dealer_id"] != audit["dealer_id"] or unit["id"] not in audit["_scope_unit_ids"]:
        raise ApiError("ERR_UNIT_NOT_IN_AUDIT_SCOPE")

    snapshot = int(unit["outstanding_principal_cents"])
    classification, out_of_trust = calc.classify_observation(
        observed_condition, title_verified, snapshot
    )
    record = db.insert(
        "observations",
        {
            "audit_id": audit["id"],
            "unit_id": unit["id"],
            "observed_condition": observed_condition,
            "title_verified": title_verified,
            "odometer_miles": odometer,
            "sale_contract_reference": sale_reference,
            "classification": classification,
            "is_out_of_trust": out_of_trust,
            "observed_by_user_id": user_id,
            "unit_outstanding_principal_cents_at_observation": snapshot,
        },
        versioned=False,
    )
    if user_id not in audit["observer_user_ids"]:
        audit["observer_user_ids"].append(user_id)
    if classification == "VERIFIED":
        audit["units_verified_count"] = int(audit["units_verified_count"]) + 1
    else:
        audit["units_exception_count"] = int(audit["units_exception_count"]) + 1
    audit["units_unobserved_count"] = int(audit["units_unobserved_count"]) - 1
    db.touch(audit)
    return response.created(serial.observation(record))


@bp.route("/floorplan/audits/<audit_id>/observations", methods=["GET"])
def list_audit_observations(audit_id):
    middleware.require(*READ_ROLES)
    audit = lookup.audit(audit_id)
    middleware.guard_owned(audit)
    classification = response.filter_value("classification", spec.CLASSIFICATIONS)
    is_out_of_trust = response.filter_bool("is_out_of_trust")
    unit_id = response.filter_value("unit_id")
    records = response.apply_filters(
        [o for o in db.rows("observations") if o["audit_id"] == audit["id"]],
        [
            ("classification", classification),
            ("is_out_of_trust", is_out_of_trust),
            ("unit_id", unit_id),
        ],
    )
    return response.paginate(records, serial.observation)


@bp.route("/floorplan/audits/<audit_id>/reconcile", methods=["POST"])
def reconcile_audit(audit_id):
    user_id, _role = middleware.require(middleware.AUDIT_MANAGER)
    audit = lookup.audit(audit_id)
    data = validate.body()
    validate.opt_str(data, "notes", min_len=0)
    dealer = db.get("dealers", audit["dealer_id"])

    if audit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_AUDIT_NOT_IN_PROGRESS")
    observed = int(audit["units_verified_count"]) + int(audit["units_exception_count"])
    if int(audit["units_in_scope_count"]) > 0 and observed == 0:
        raise ApiError("ERR_AUDIT_NO_OBSERVATIONS")
    if user_id in audit["observer_user_ids"]:
        raise ApiError("ERR_SOD_AUDIT_RECONCILER")

    observations = [o for o in db.rows("observations") if o["audit_id"] == audit["id"]]
    clean = int(audit["units_exception_count"]) == 0
    audit["status"] = "RECONCILED_CLEAN" if clean else "RECONCILED_EXCEPTIONS"
    audit["reconciled_at"] = db.now_str()
    audit["reconciled_by_user_id"] = user_id

    if clean:
        audit["sot_exposure_cents"] = 0
        db.touch(audit)
    else:
        out_of_trust = [o for o in observations if o["is_out_of_trust"]]
        exposure = 0
        for observation in out_of_trust:
            unit = db.get("inventory_units", observation["unit_id"])
            exposure += int(unit["outstanding_principal_cents"])
        audit["sot_exposure_cents"] = exposure
        db.touch(audit)

        lines = set()
        for observation in out_of_trust:
            unit = db.get("inventory_units", observation["unit_id"])
            db.insert(
                "incidents",
                {
                    "dealer_id": audit["dealer_id"],
                    "unit_id": unit["id"],
                    "audit_id": audit["id"],
                    "observation_id": observation["id"],
                    "status": "OPEN",
                    "exposure_cents": int(unit["outstanding_principal_cents"]),
                    "cure_deadline_at": db.fmt_instant(
                        db.add_days(db.parse_instant(audit["reconciled_at"]), spec.SOT_CURE_DEADLINE_DAYS)
                    ),
                    "cured_at": None,
                    "charged_off_at": None,
                    "resolution_reason_code": None,
                },
            )
            eligibility, reason = calc.SOT_ELIGIBILITY_BY_CLASSIFICATION[
                observation["classification"]
            ]
            unit["funding_status"] = "SOT_OPEN"
            unit["eligibility_status"] = eligibility
            unit["ineligibility_reason_code"] = reason
            db.touch(unit)
            lines.add(unit["credit_line_id"])

        for observation in observations:
            if observation["is_out_of_trust"] or observation["classification"] == "VERIFIED":
                continue
            unit = db.get("inventory_units", observation["unit_id"])
            eligibility, reason = calc.SOT_ELIGIBILITY_BY_CLASSIFICATION[
                observation["classification"]
            ]
            unit["eligibility_status"] = eligibility
            unit["ineligibility_reason_code"] = reason
            db.touch(unit)
            lines.add(unit["credit_line_id"])

        for line_id in lines:
            line = db.get("credit_lines", line_id)
            if line is not None:
                ledger.recompute_availability(line)
                db.touch(line)
        ledger.recompute_dealer_counters(dealer)
        if int(dealer["open_sot_exposure_cents"]) >= spec.SOT_EXPOSURE_SUSPENSION_CENTS:
            ledger.suspend_line(
                ledger.dealer_line(dealer["id"]), dealer, "SOT_EXPOSURE_THRESHOLD"
            )

    dealer["audit_in_progress"] = False
    ledger.recompute_dealer_counters(dealer)
    ledger.recompute_risk(dealer)
    dealer["next_audit_due_at"] = db.fmt_instant(
        db.add_days(
            db.parse_instant(audit["reconciled_at"]), int(dealer["audit_frequency_days"])
        )
    )
    db.touch(dealer)
    return response.ok(serial.audit(audit))


@bp.route("/floorplan/audits/<audit_id>/abort", methods=["POST"])
def abort_audit(audit_id):
    middleware.require(middleware.AUDIT_MANAGER)
    audit = lookup.audit(audit_id)
    data = validate.body()
    abort_reason = validate.req_enum(data, "abort_reason_code", spec.ABORT_REASONS)
    if audit["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_AUDIT_NOT_IN_PROGRESS")
    audit["status"] = "ABORTED"
    audit["abort_reason_code"] = abort_reason
    audit["units_verified_count"] = 0
    audit["units_exception_count"] = 0
    audit["units_unobserved_count"] = int(audit["units_in_scope_count"])
    audit["sot_exposure_cents"] = 0
    db.touch(audit)
    dealer = db.get("dealers", audit["dealer_id"])
    dealer["audit_in_progress"] = False
    db.touch(dealer)
    return response.ok(serial.audit(audit))


@bp.route("/floorplan/audits/<audit_id>", methods=["GET"])
def read_audit(audit_id):
    middleware.require(*READ_ROLES)
    audit = lookup.audit(audit_id)
    middleware.guard_owned(audit)
    return response.ok(serial.audit(audit))


@bp.route("/floorplan/audits", methods=["GET"])
def list_audits():
    middleware.require(*READ_ROLES)
    dealer_id = response.filter_value("dealer_id")
    if dealer_id is not None:
        middleware.guard_dealer_id(dealer_id)
    status = response.filter_value("status", spec.AUDIT_STATUSES)
    audit_type = response.filter_value("audit_type", spec.AUDIT_TYPES)
    records = response.apply_filters(
        db.rows("audits"),
        [("dealer_id", dealer_id), ("status", status), ("audit_type", audit_type)],
    )
    scope = middleware.scope_dealer_id()
    if scope is not None:
        records = [a for a in records if a["dealer_id"] == scope]
    return response.paginate(records, serial.audit)


@bp.route("/floorplan/out-of-trust-incidents/<incident_id>", methods=["GET"])
def read_incident(incident_id):
    middleware.require(*INCIDENT_READ_ROLES)
    incident = lookup.incident(incident_id)
    middleware.guard_owned(incident)
    return response.ok(serial.incident(incident))


@bp.route("/floorplan/out-of-trust-incidents", methods=["GET"])
def list_incidents():
    middleware.require(*INCIDENT_READ_ROLES)
    dealer_id = response.filter_value("dealer_id")
    if dealer_id is not None:
        middleware.guard_dealer_id(dealer_id)
    unit_id = response.filter_value("unit_id")
    audit_id = response.filter_value("audit_id")
    observation_id = response.filter_value("observation_id")
    status = response.filter_value("status", spec.INCIDENT_STATUSES)
    records = response.apply_filters(
        db.rows("incidents"),
        [
            ("dealer_id", dealer_id),
            ("unit_id", unit_id),
            ("audit_id", audit_id),
            ("observation_id", observation_id),
            ("status", status),
        ],
    )
    scope = middleware.scope_dealer_id()
    if scope is not None:
        records = [i for i in records if i["dealer_id"] == scope]
    return response.paginate(records, serial.incident)
