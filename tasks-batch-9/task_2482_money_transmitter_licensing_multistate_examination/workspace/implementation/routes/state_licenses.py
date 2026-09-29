"""State licences: bonds, obligations, renewals and surrender (§3.4, §3.5)."""

from flask import Blueprint

import calculations as calc
from db import days, now, serialize, set_dt, set_input_dt, touch
from db import db
from errors import ApiError
from middleware import authorize, regulator_matches, require_scope
from response import ok
from routes.common import filter_rows, get_jurisdiction, get_licensee, get_license, paginate
from services import engine
from validators import get_body, pagination, q_enum, q_str, v_dt, v_enum, v_int, v_str

bp = Blueprint("state_licenses", __name__)

LICENSE_STATUSES = (
    "PENDING_BOND",
    "ACTIVE",
    "SUSPENDED",
    "SURRENDER_REQUESTED",
    "SURRENDERED",
    "REVOKED",
)
REPORTING_STATUSES = ("CURRENT", "DELINQUENT", "DEFICIENT_FILING")
TERMINAL_LICENSE_STATUSES = ("SURRENDERED", "REVOKED")
CALL_REPORT_STATUSES = ("FILED", "LATE", "FILED_DEFICIENT")


def _require_status(license_row, allowed):
    if license_row["license_status"] not in allowed:
        raise ApiError(
            "ERR_LICENSE_NOT_ACTIVE",
            "Licence %s is %s; the operation requires one of %s"
            % (license_row["id"], license_row["license_status"], ", ".join(allowed)),
        )


def _require_not_terminal(license_row):
    if license_row["license_status"] in TERMINAL_LICENSE_STATUSES:
        raise ApiError(
            "ERR_LICENSE_TERMINAL",
            "Licence %s is %s and accepts no further mutation"
            % (license_row["id"], license_row["license_status"]),
        )


@bp.get("/state-licenses/<license_id>")
def get_one(license_id):
    authorize(
        "LicensingManager", "ComplianceOfficer", "ChiefComplianceOfficer", "StateRegulator"
    )
    return ok(serialize(get_license(license_id)))


@bp.get("/state-licenses")
def list_all():
    authorize(
        "LicensingManager", "ComplianceOfficer", "ChiefComplianceOfficer", "StateRegulator"
    )
    limit, offset = pagination()
    filters = {
        "licensee_id": q_str("licensee_id"),
        "jurisdiction_id": q_str("jurisdiction_id"),
        "application_id": q_str("application_id"),
        "license_status": q_enum("license_status", LICENSE_STATUSES),
        "reporting_status": q_enum("reporting_status", REPORTING_STATUSES),
    }
    return paginate(filter_rows(db.state_licenses.values(), filters), limit, offset)


@bp.post("/state-licenses/<license_id>/bond")
def post_bond(license_id):
    authorize("LicensingManager")
    body = get_body()
    amount_cents = v_int(body, "amount_cents", minimum=0)
    bond_issuer = v_str(body, "bond_issuer")
    v_dt(body, "effective_date", required=True)

    license_row = get_license(license_id)
    licensee = get_licensee(license_row["licensee_id"])

    _require_status(license_row, ("PENDING_BOND",))
    if amount_cents < license_row["bond_requirement_cents"]:
        raise ApiError(
            "ERR_BOND_INSUFFICIENT",
            "The posted bond is below the requirement of %d cents"
            % license_row["bond_requirement_cents"],
        )

    license_row["bond_posted_cents"] = amount_cents
    license_row["bond_status"] = "POSTED"
    license_row["bond_issuer"] = bond_issuer
    license_row["license_status"] = "ACTIVE"
    set_dt(license_row, "authorized_at", now())
    touch(license_row)

    licensee["active_license_count"] += 1
    old_posture = engine.recompute_coverage(licensee)
    touch(licensee)
    engine.propagate_posture(licensee, old_posture)
    engine.refresh_gate(license_row, licensee)
    return ok(serialize(license_row))


@bp.post("/state-licenses/<license_id>/bond-cancellation-notice")
def bond_cancellation_notice(license_id):
    authorize("LicensingManager")
    body = get_body()
    raw_date, parsed_date = v_dt(body, "bond_cancellation_effective_date", required=True)

    license_row = get_license(license_id)
    licensee = get_licensee(license_row["licensee_id"])

    if license_row["license_status"] != "ACTIVE" or license_row["bond_status"] != "POSTED":
        raise ApiError(
            "ERR_LICENSE_NOT_ACTIVE",
            "A cancellation notice requires an ACTIVE licence with a POSTED bond",
        )
    if parsed_date < now() + days(30):
        raise ApiError(
            "ERR_BOND_NOTICE_TOO_SHORT",
            "The cancellation effective date must be at least thirty days out",
        )

    license_row["bond_status"] = "CANCELLATION_NOTICED"
    set_input_dt(license_row, "bond_cancellation_effective_date", raw_date, parsed_date)
    engine.suspend_license_cascade(license_row, licensee)
    return ok(serialize(license_row))


@bp.patch("/state-licenses/<license_id>/obligations")
def adjust_obligations(license_id):
    authorize("LicensingManager")
    body = get_body()
    delta = v_int(body, "delta_cents", minimum=None)
    v_str(body, "memo")

    license_row = get_license(license_id)
    licensee = get_licensee(license_row["licensee_id"])

    _require_not_terminal(license_row)
    balance = license_row["outstanding_obligations_cents"] + delta
    if balance < 0:
        raise ApiError(
            "ERR_NEGATIVE_OBLIGATIONS",
            "The adjustment would drive outstanding obligations below zero",
        )

    license_row["outstanding_obligations_cents"] = balance
    touch(license_row)
    old_posture = engine.recompute_coverage(licensee)
    touch(licensee)
    engine.propagate_posture(licensee, old_posture)
    return ok(serialize(license_row))


@bp.post("/state-licenses/<license_id>/renewals")
def renew(license_id):
    authorize("LicensingManager")
    body = get_body()
    renewal_year = v_int(body, "renewal_year", minimum=0)
    payment = v_int(body, "payment_amount_cents", minimum=0)

    license_row = get_license(license_id)
    licensee = get_licensee(license_row["licensee_id"])
    jurisdiction = get_jurisdiction(license_row["jurisdiction_id"])

    _require_status(license_row, ("ACTIVE",))
    if licensee["control_chain_status"] == "BLOCKED":
        raise ApiError("ERR_CONTROL_CHAIN_BLOCKED", "The licensee's control chain is blocked")
    if license_row["reporting_status"] != "CURRENT":
        raise ApiError(
            "ERR_REPORTING_NOT_CURRENT",
            "Licence %s has reporting_status %s" % (license_id, license_row["reporting_status"]),
        )
    if licensee["reported_tangible_net_worth_cents"] < jurisdiction["min_net_worth_cents"]:
        raise ApiError(
            "ERR_NET_WORTH_INSUFFICIENT",
            "Reported tangible net worth is below the jurisdiction minimum",
        )
    total = calc.renewal_fee_assessment(jurisdiction, license_row["active_delegate_count"])
    if payment != total:
        raise ApiError(
            "ERR_RENEWAL_FEE_MISMATCH",
            "The renewal fee for this licence is %d cents" % total,
        )

    license_row["renewal_status"] = "RENEWED"
    license_row["renewal_year"] = renewal_year
    license_row["renewal_total_fee_cents"] = total
    touch(license_row)
    return ok(serialize(license_row))


@bp.post("/state-licenses/<license_id>/surrender-requests")
def surrender_request(license_id):
    authorize("LicensingManager")
    body = get_body()
    v_dt(body, "effective_date", required=True)
    v_str(body, "wind_down_narrative")
    expected_version = v_int(body, "expected_state_license_version", minimum=0)

    license_row = get_license(license_id)
    licensee = get_licensee(license_row["licensee_id"])

    if expected_version != license_row["version"]:
        raise ApiError(
            "ERR_STALE_LICENSE_VERSION",
            "Licence %s is at version %d" % (license_id, license_row["version"]),
        )
    _require_status(license_row, ("ACTIVE", "SUSPENDED"))
    if any(
        a["status"] == "ACTIVE" for a in engine.authorizations_of_license(license_id)
    ):
        raise ApiError(
            "ERR_ACTIVE_DELEGATES_REMAIN",
            "The licence still has ACTIVE delegate authorizations",
        )
    if license_row["outstanding_obligations_cents"] != 0:
        raise ApiError(
            "ERR_OUTSTANDING_OBLIGATIONS_REMAIN",
            "The licence still owes outstanding transmission obligations",
        )

    was_active = license_row["license_status"] == "ACTIVE"
    license_row["license_status"] = "SURRENDER_REQUESTED"
    touch(license_row)
    engine.set_gate(license_row, "BLOCKED")
    if was_active:
        licensee["active_license_count"] = max(0, licensee["active_license_count"] - 1)
        touch(licensee)
    return ok(serialize(license_row))


@bp.post("/state-licenses/<license_id>/surrender-decisions")
def surrender_decision(license_id):
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    decision = v_enum(body, "decision", ("APPROVED", "DENIED"))
    v_str(body, "rationale", required=False, allow_empty=True, default=None)

    license_row = get_license(license_id)
    licensee = get_licensee(license_row["licensee_id"])
    require_scope(
        regulator_matches(user_id, license_row["jurisdiction_id"]),
        user_id,
        "licence %s" % license_id,
    )
    _require_status(license_row, ("SURRENDER_REQUESTED",))

    if decision == "APPROVED":
        engine.surrender_license_cascade(license_row, licensee)
    else:
        license_row["license_status"] = "ACTIVE"
        touch(license_row)
        licensee["active_license_count"] += 1
        touch(licensee)
        engine.refresh_gate(license_row, licensee)
    return ok(serialize(license_row))


@bp.get("/state-licenses/<license_id>/call-reports")
def list_call_reports(license_id):
    authorize("LicensingManager", "StateRegulator")
    limit, offset = pagination()
    status = q_enum("status", CALL_REPORT_STATUSES)
    get_license(license_id)
    rows = filter_rows(engine.call_reports_of(license_id), {"status": status})
    return paginate(rows, limit, offset)
