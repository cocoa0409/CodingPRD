"""Coverage instruments (bond / insurance) and qualifier designations."""

from flask import Blueprint

import calc
from core import (
    clock_date,
    created,
    db,
    err,
    fmt_date,
    get_body,
    new_row,
    ok,
    qfilter,
    render_list,
    require_auth,
    setf,
    touch,
    v_date,
    v_enum,
    v_id,
    v_int,
    v_money,
    v_num,
    v_str,
)
import domain
from domain import D, find, must, rows

bp = Blueprint("coverage", __name__)

COVERAGE_TYPES = ["BOND", "GENERAL_LIABILITY", "WORKERS_COMP"]
RELATIONSHIP_TYPES = ["RESPONSIBLE_MANAGING_OFFICER", "RESPONSIBLE_MANAGING_EMPLOYEE"]


# ------------------------------------------------------- coverage records ----
@bp.route("/licensing/coverage-records", methods=["POST"])
def create_coverage():
    require_auth(["LicensingAnalyst", "Licensee"])
    body = get_body()
    license_id = v_id(body, "license_id")
    coverage_type = v_enum(body, "coverage_type", COVERAGE_TYPES)
    carrier_name = v_str(body, "carrier_name")
    policy_number = v_str(body, "policy_number")
    amount_cents = v_money(body, "amount_cents")
    effective_date = v_date(body, "effective_date")
    expiration_date = v_date(body, "expiration_date")
    if expiration_date <= effective_date:
        err("ERR_INVALID_REQUEST", "expiration_date must be strictly after effective_date")

    lic = must("licenses", license_id)
    if lic["status"] == "REVOKED":
        err("ERR_LICENSE_STATE_INVALID", "a REVOKED licence accepts no coverage filing")

    row = new_row()
    row.update({
        "license_id": lic["id"],
        "coverage_type": coverage_type,
        "carrier_name": carrier_name,
        "policy_number": policy_number,
        "amount_cents": amount_cents,
        "effective_date": fmt_date(effective_date),
        "expiration_date": fmt_date(expiration_date),
        "status": "PENDING_VERIFICATION",
        "verified_on": None,
        "cancellation_date": None,
        "rejection_reason": None,
    })
    db.coverage_records[row["id"]] = row
    return created(domain.ser_coverage(row))


@bp.route("/licensing/coverage-records/<rid>", methods=["GET"])
def get_coverage(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "Licensee"])
    return ok(domain.ser_coverage(must("coverage_records", rid)))


@bp.route("/licensing/coverage-records", methods=["GET"])
def list_coverage():
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "Licensee"])
    items = rows("coverage_records")
    for field in ("license_id", "coverage_type", "status"):
        items = qfilter(items, field)
    return render_list(items, domain.ser_coverage)


@bp.route("/licensing/coverage-records/<rid>/verification", methods=["POST"])
def verify_coverage(rid):
    require_auth(["LicensingAnalyst"])
    body = get_body()
    outcome = v_enum(body, "outcome", ["VERIFY", "REJECT"])
    rejection_reason = v_str(body, "rejection_reason", required=False)

    record = must("coverage_records", rid)
    if record["status"] != "PENDING_VERIFICATION":
        err("ERR_COVERAGE_STATE_INVALID",
            "only a PENDING_VERIFICATION record may be verified or rejected")

    lic = find("licenses", record["license_id"])

    if outcome == "REJECT":
        setf(record, "status", "REJECTED")
        setf(record, "rejection_reason", rejection_reason)
        touch(record)
        if lic is not None:
            domain.recompute_posture(lic)
        return ok(domain.ser_coverage(record))

    start = D(record["effective_date"])
    end = D(record["expiration_date"])
    for other in domain.coverage_records_for(record["license_id"]):
        if other["id"] == record["id"] or other["status"] != "VERIFIED":
            continue
        if other["coverage_type"] != record["coverage_type"]:
            continue
        if D(other["effective_date"]) < end and start < D(other["expiration_date"]):
            err("ERR_COVERAGE_PERIOD_OVERLAP",
                "another VERIFIED record of this coverage_type overlaps the period")

    if record["coverage_type"] == "BOND":
        classification = find("trade_classifications", lic["classification_id"])
        if record["amount_cents"] < classification["required_bond_amount_cents"]:
            err("ERR_BOND_AMOUNT_INSUFFICIENT",
                "the bond face amount is below the classification's requirement")

    setf(record, "status", "VERIFIED")
    setf(record, "verified_on", fmt_date(clock_date()))
    touch(record)
    if lic is not None:
        domain.recompute_posture(lic)
    return ok(domain.ser_coverage(record))


@bp.route("/licensing/coverage-records/<rid>/cancel", methods=["POST"])
def cancel_coverage(rid):
    require_auth(["LicensingAnalyst"])
    body = get_body()
    cancellation_date = v_date(body, "cancellation_date")

    record = must("coverage_records", rid)
    if cancellation_date < D(record["effective_date"]):
        err("ERR_INVALID_REQUEST",
            "cancellation_date must be on or after the record's effective_date")
    if record["status"] != "VERIFIED":
        err("ERR_COVERAGE_STATE_INVALID", "only a VERIFIED record may be cancelled")

    # hop 1 -- truncate the period and close the record
    setf(record, "cancellation_date", fmt_date(cancellation_date))
    setf(record, "expiration_date", fmt_date(cancellation_date))
    setf(record, "status", "CANCELLED")
    touch(record)

    lic = find("licenses", record["license_id"])
    if lic is not None:
        # hops 2-4 -- posture, licence suspension, designation cascade
        if (record["coverage_type"] == "BOND"
                and not domain.has_live_coverage(lic["id"], "BOND")
                and lic["status"] == "ACTIVE"):
            domain.suspend_license(lic, "BOND_LAPSE", None)
        domain.recompute_posture(lic)

    return ok(domain.ser_coverage(record))


# ------------------------------------------------- qualifier designations ----
def live_designations_covering(qi_id, on_date):
    count = 0
    for a in rows("qualifier_assignments"):
        if a["qualifying_individual_id"] != qi_id or a["status"] != "ACTIVE":
            continue
        if D(a["effective_from"]) > on_date:
            continue
        eff_to = a.get("effective_to")
        if eff_to is not None and D(eff_to) < on_date:
            continue
        count += 1
    return count


@bp.route("/licensing/qualifier-assignments", methods=["POST"])
def create_assignment():
    require_auth(["LicensingAnalyst"])
    body = get_body()
    license_id = v_id(body, "license_id")
    qualifying_individual_id = v_id(body, "qualifying_individual_id")
    relationship_type = v_enum(body, "relationship_type", RELATIONSHIP_TYPES)
    effective_from = v_date(body, "effective_from")
    expected_license_version = v_int(body, "expected_license_version")
    ownership_pct = v_num(body, "ownership_pct", required=False, default=0,
                          minv=0, maxv=100)
    effective_to = v_date(body, "effective_to", required=False)
    if effective_to is not None and effective_to < effective_from:
        err("ERR_INVALID_REQUEST", "effective_to must be on or after effective_from")

    lic = must("licenses", license_id)
    qi = must("qualifying_individuals", qualifying_individual_id)

    if expected_license_version != lic["version"]:
        err("ERR_STALE_LICENSE_VERSION", "the presented licence version is stale")

    if lic["status"] == "REVOKED":
        err("ERR_LICENSE_STATE_INVALID", "a REVOKED licence accepts no designation")

    if live_designations_covering(qi["id"], effective_from) >= \
            calc.MAX_CONCURRENT_QUALIFICATIONS:
        err("ERR_QUALIFIER_CAPACITY_EXCEEDED",
            "this person already holds the maximum concurrent designations")

    if (relationship_type == "RESPONSIBLE_MANAGING_OFFICER"
            and ownership_pct < calc.RMO_MIN_OWNERSHIP_PCT):
        err("ERR_OWNERSHIP_PCT_INSUFFICIENT",
            "a responsible managing officer must own at least %d percent"
            % calc.RMO_MIN_OWNERSHIP_PCT)

    if effective_from < D(lic["issued_on"]):
        err("ERR_ASSIGNMENT_EFFECTIVE_DATE_INVALID",
            "effective_from precedes the licence's issued_on")
    if effective_to is not None and effective_to > D(lic["expires_on"]):
        err("ERR_ASSIGNMENT_EFFECTIVE_DATE_INVALID",
            "effective_to falls after the licence's expires_on")

    today = fmt_date(clock_date())

    row = new_row()
    row.update({
        "license_id": lic["id"],
        "qualifying_individual_id": qi["id"],
        "relationship_type": relationship_type,
        "ownership_pct": ownership_pct,
        "effective_from": fmt_date(effective_from),
        "effective_to": fmt_date(effective_to) if effective_to is not None else None,
        "status": "ACTIVE",
        "withdrawn_on": None,
    })
    db.qualifier_assignments[row["id"]] = row

    # supersede any live designation of the same relationship type
    for other in domain.license_assignments(lic["id"]):
        if other["id"] == row["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if other["relationship_type"] != relationship_type:
            continue
        setf(other, "status", "WITHDRAWN")
        setf(other, "withdrawn_on", today)
        setf(other, "effective_to", today)
        touch(other)
        touch(find("qualifying_individuals", other["qualifying_individual_id"]))

    setf(lic, "qualifying_individual_id", qi["id"])
    touch(qi)
    domain.recompute_posture(lic)
    touch(lic)
    return created(domain.ser_assignment(row))


@bp.route("/licensing/qualifier-assignments/<rid>", methods=["GET"])
def get_assignment(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "Licensee"])
    return ok(domain.ser_assignment(must("qualifier_assignments", rid)))


@bp.route("/licensing/qualifier-assignments", methods=["GET"])
def list_assignments():
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "Licensee"])
    items = rows("qualifier_assignments")
    for field in ("license_id", "qualifying_individual_id", "status"):
        items = qfilter(items, field)
    return render_list(items, domain.ser_assignment)


@bp.route("/licensing/qualifier-assignments/<rid>/withdraw", methods=["POST"])
def withdraw_assignment(rid):
    require_auth(["LicensingAnalyst"])
    body = get_body()
    withdrawn_on = v_date(body, "withdrawn_on")

    assignment = must("qualifier_assignments", rid)
    if withdrawn_on < D(assignment["effective_from"]):
        err("ERR_INVALID_REQUEST",
            "withdrawn_on must be on or after the designation's effective_from")
    if assignment["status"] != "ACTIVE":
        err("ERR_ASSIGNMENT_STATE_INVALID", "only an ACTIVE designation may be withdrawn")

    stamp = fmt_date(withdrawn_on)
    setf(assignment, "status", "WITHDRAWN")
    setf(assignment, "withdrawn_on", stamp)
    setf(assignment, "effective_to", stamp)
    touch(assignment)
    touch(find("qualifying_individuals", assignment["qualifying_individual_id"]))

    lic = find("licenses", assignment["license_id"])
    if lic is not None:
        if lic.get("qualifying_individual_id") == assignment["qualifying_individual_id"]:
            setf(lic, "qualifying_individual_id", None)
            domain.recompute_posture(lic)
    return ok(domain.ser_assignment(assignment))
