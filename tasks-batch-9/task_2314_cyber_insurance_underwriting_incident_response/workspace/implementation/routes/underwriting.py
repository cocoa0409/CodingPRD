"""Insured accounts, applications, attestations, scanning, quoting and binding."""

from decimal import Decimal

from flask import Blueprint, g, request

import calc
import errors
import validate
from cascades import refresh_attested, set_application_status
from calc import dec
from db import iso3, new_row, now_iso, plus_days, round2, sorted_by_created, store, touch
from errors import ApiError, bad_request
from middleware import (CLAIMS_ADJUSTER, INSURED, PORTFOLIO_ACTUARY, UNDERWRITER,
                        endpoint, find_account, find_application, find_attestation,
                        find_scan, guard_account_filter, is_insured, owner_of_application,
                        scope_guard, scoped_filter)
from response import created, listing, ok
from routes.common import apply_eq, filter_value

bp = Blueprint("underwriting", __name__, url_prefix="/cyber")


# --------------------------------------------------------------------------
# insured accounts
# --------------------------------------------------------------------------

@bp.route("/insured-accounts", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def register_account():
    payload = validate.body()
    row = new_row({
        "legal_name": validate.req_str(payload, "legal_name", 1, 200),
        "industry_code": validate.req_enum(payload, "industry_code", calc.INDUSTRY_CODES),
        "annual_revenue_usd": round2(validate.req_num(
            payload, "annual_revenue_usd", minimum=0, exclusive_min=True, money=True)),
        "record_count": validate.req_int(payload, "record_count", 0, None),
        "primary_dependency_key": validate.opt_enum(
            payload, "primary_dependency_key", calc.DEPENDENCY_KEYS, default="NONE"),
        "open_remediation_count": 0,
    })
    store.insured_accounts[row["id"]] = row
    return created(row)


@bp.route("/insured-accounts/<insured_account_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def read_account(insured_account_id):
    account = find_account(insured_account_id)
    scope_guard(account["id"])
    return ok(account)


@bp.route("/insured-accounts", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY])
def list_accounts():
    rows = list(store.insured_accounts.values())
    rows = apply_eq(rows, "industry_code", filter_value("industry_code", calc.INDUSTRY_CODES))
    rows = apply_eq(rows, "primary_dependency_key",
                    filter_value("primary_dependency_key", calc.DEPENDENCY_KEYS))
    return listing(sorted_by_created(rows))


# --------------------------------------------------------------------------
# applications
# --------------------------------------------------------------------------

@bp.route("/applications", methods=["POST"])
@endpoint(roles=[UNDERWRITER, INSURED])
def create_application():
    payload = validate.body()
    supplied = payload.get("insured_account_id")
    if is_insured() and isinstance(supplied, str) and supplied != g.user_id:
        raise ApiError(errors.ERR_ACCOUNT_SCOPE_VIOLATION, 403,
                       "an Insured may only open applications on its own account")
    account_id = validate.req_str(payload, "insured_account_id")
    account = find_account(account_id)
    scope_guard(account["id"])

    aggregate = validate.req_num(payload, "requested_aggregate_limit_usd",
                                 minimum=calc.MIN_AGGREGATE_LIMIT_USD, money=True)
    retention = validate.req_num(payload, "requested_retention_usd",
                                 minimum=0, maximum=aggregate, money=True)
    definition = validate.req_enum(payload, "dependent_bi_definition",
                                   calc.DEPENDENT_BI_DEFINITIONS)
    if aggregate % calc.LIMIT_INCREMENT_USD != 0:
        raise ApiError(errors.ERR_INVALID_LIMIT_INCREMENT, 422,
                       "requested_aggregate_limit_usd must be a whole multiple of 250000")

    row = new_row({
        "insured_account_id": account["id"],
        "requested_aggregate_limit_usd": round2(aggregate),
        "requested_retention_usd": round2(retention),
        "dependent_bi_definition": definition,
        "status": "DRAFT",
        "attested_control_score": None,
        "verified_control_score": None,
        "mandatory_gap_count": 0,
        "mandatory_gap_control_keys": [],
        "indicative_premium_usd": None,
        "premium_usd": None,
        "quoted_by_user_id": None,
        "quote_expires_at": None,
        "declined_reason": None,
    })
    store.applications[row["id"]] = row
    row["attested_control_score"] = refresh_attested(row)
    return created(row)


@bp.route("/applications/<application_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def read_application(application_id):
    application = find_application(application_id)
    scope_guard(owner_of_application(application))
    return ok(application)


@bp.route("/applications", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY, INSURED])
def list_applications():
    guard_account_filter("insured_account_id")
    rows = list(store.applications.values())
    rows = apply_eq(rows, "insured_account_id", filter_value("insured_account_id"))
    rows = apply_eq(rows, "status", filter_value("status", calc.APPLICATION_STATES))
    rows = scoped_filter(rows, owner_of_application)
    return listing(sorted_by_created(rows))


# --------------------------------------------------------------------------
# control attestations
# --------------------------------------------------------------------------

@bp.route("/applications/<application_id>/control-attestations", methods=["POST"])
@endpoint(roles=[UNDERWRITER, INSURED])
def create_attestation(application_id):
    application = find_application(application_id)
    scope_guard(owner_of_application(application))
    payload = validate.body()
    control_key = validate.req_enum(payload, "control_key", calc.CONTROL_KEYS)
    attested_level = validate.req_enum(payload, "attested_level", calc.LEVELS)
    if control_key not in calc.catalog_by_key():
        raise bad_request("control_key %s is not present in the control catalog" % control_key)
    if application["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_APPLICATION_STATE, 409,
                       "attestations may only be written against a DRAFT application")
    for existing in calc.attestations_of(application["id"]):
        if existing["control_key"] == control_key:
            raise ApiError(errors.ERR_DUPLICATE_ATTESTATION, 422,
                           "an attestation for %s already exists" % control_key)
    row = new_row({
        "application_id": application["id"],
        "control_key": control_key,
        "attested_level": attested_level,
        "verified_level": None,
    })
    store.control_attestations[row["id"]] = row
    refresh_attested(application)
    touch(application)
    return created(row)


@bp.route("/applications/<application_id>/control-attestations", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def list_application_attestations(application_id):
    application = find_application(application_id)
    scope_guard(owner_of_application(application))
    rows = calc.attestations_of(application["id"])
    rows.sort(key=lambda row: (row["control_key"], row["created_at"], row["_seq"]))
    return listing(rows)


@bp.route("/control-attestations/<attestation_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def read_attestation(attestation_id):
    attestation = find_attestation(attestation_id)
    application = store.applications.get(attestation["application_id"])
    scope_guard(owner_of_application(application) if application else None)
    return ok(attestation)


@bp.route("/control-attestations", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY])
def list_attestations():
    rows = list(store.control_attestations.values())
    rows = apply_eq(rows, "application_id", filter_value("application_id"))
    rows = apply_eq(rows, "control_key", filter_value("control_key", calc.CONTROL_KEYS))
    return listing(sorted_by_created(rows))


@bp.route("/applications/<application_id>/control-posture", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY, INSURED])
def read_control_posture(application_id):
    application = find_application(application_id)
    scope_guard(owner_of_application(application))
    attested_score, _ = calc.control_posture_score(application, "attested")
    verified_score, gaps = calc.control_posture_score(application, "verified")
    completed = calc.latest_completed_scan(application["id"])
    newest = calc.latest_scan(application["id"])
    scan_ok = newest is not None and newest["status"] == "COMPLETED"
    if completed is None:
        verified_score = None
    quotable = bool(scan_ok and not gaps and verified_score is not None
                    and dec(verified_score) >= calc.MIN_SCORE_FOR_COVERAGE)
    return ok({
        "attested_score": attested_score,
        "verified_score": verified_score,
        "mandatory_gap_count": len(gaps),
        "mandatory_gap_control_keys": gaps,
        "min_score_for_coverage": calc.MIN_SCORE_FOR_COVERAGE,
        "quotable": quotable,
    })


# --------------------------------------------------------------------------
# submit / resubmit
# --------------------------------------------------------------------------

def _mandatory_attestation_guard(application):
    attested = set(row["control_key"] for row in calc.attestations_of(application["id"]))
    for key in calc.mandatory_catalog_keys():
        if key not in attested:
            raise ApiError(errors.ERR_MANDATORY_ATTESTATION_MISSING, 422,
                           "no attestation exists for mandatory control %s" % key)


@bp.route("/applications/<application_id>/submit", methods=["POST"])
@endpoint(roles=[UNDERWRITER, INSURED])
def submit_application(application_id):
    application = find_application(application_id)
    scope_guard(owner_of_application(application))
    if application["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_APPLICATION_STATE, 409,
                       "only a DRAFT application may be submitted")
    _mandatory_attestation_guard(application)
    account = store.insured_accounts[application["insured_account_id"]]
    score = refresh_attested(application)
    application["indicative_premium_usd"] = calc.premium_quote(account, application, score)
    set_application_status(application, "SUBMITTED")
    return ok(application)


@bp.route("/applications/<application_id>/resubmit-controls", methods=["POST"])
@endpoint(roles=[UNDERWRITER, INSURED])
def resubmit_controls(application_id):
    application = find_application(application_id)
    scope_guard(owner_of_application(application))
    payload = validate.body()
    entries = validate.req_object_array(payload, "attestations", non_empty=True)
    revisions = []
    for entry in entries:
        control_key = validate.req_enum(entry, "control_key", calc.CONTROL_KEYS)
        attested_level = validate.req_enum(entry, "attested_level", calc.LEVELS)
        revisions.append((control_key, attested_level))
    if application["status"] != "REMEDIATION_REQUIRED":
        raise ApiError(errors.ERR_INVALID_APPLICATION_STATE, 409,
                       "only an application in REMEDIATION_REQUIRED may resubmit controls")
    gap_keys = list(application["mandatory_gap_control_keys"] or [])
    for control_key, _level in revisions:
        if control_key not in gap_keys:
            raise bad_request("%s is not among mandatory_gap_control_keys" % control_key)
    _mandatory_attestation_guard(application)

    existing = dict((row["control_key"], row) for row in calc.attestations_of(application["id"]))
    for control_key, level in revisions:
        row = existing.get(control_key)
        if row is None:
            row = new_row({
                "application_id": application["id"],
                "control_key": control_key,
                "attested_level": level,
                "verified_level": None,
            })
            store.control_attestations[row["id"]] = row
            existing[control_key] = row
        else:
            if row["attested_level"] != level:
                row["attested_level"] = level
                touch(row)
    for row in calc.attestations_of(application["id"]):
        if row["verified_level"] is not None:
            row["verified_level"] = None
            touch(row)

    application["verified_control_score"] = None
    application["mandatory_gap_count"] = 0
    application["mandatory_gap_control_keys"] = []
    account = store.insured_accounts[application["insured_account_id"]]
    score = refresh_attested(application)
    application["indicative_premium_usd"] = calc.premium_quote(account, application, score)
    set_application_status(application, "SUBMITTED")
    return ok(application)


# --------------------------------------------------------------------------
# external scans
# --------------------------------------------------------------------------

@bp.route("/applications/<application_id>/external-scans", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def order_scan(application_id):
    application = find_application(application_id)
    payload = validate.body()
    vendor_name = validate.req_str(payload, "scan_vendor_name", 1, 120)
    scan_score = validate.opt_num(payload, "scan_score", minimum=0, maximum=100)
    if application["status"] not in ("SUBMITTED", "UNDERWRITING", "REMEDIATION_REQUIRED"):
        raise ApiError(errors.ERR_INVALID_APPLICATION_STATE, 409,
                       "a scan may only be ordered on an application under underwriting")
    row = new_row({
        "application_id": application["id"],
        "scan_vendor_name": vendor_name,
        "status": "PENDING",
        "scan_score": scan_score,
        "findings": [],
        "critical_finding_count": 0,
        "completed_at": None,
    })
    store.external_scans[row["id"]] = row
    return created(row)


@bp.route("/applications/<application_id>/external-scans", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY, INSURED])
def list_application_scans(application_id):
    application = find_application(application_id)
    scope_guard(owner_of_application(application))
    rows = calc.scans_of(application["id"])
    rows = apply_eq(rows, "status", filter_value("status", calc.SCAN_STATES))
    return listing(sorted_by_created(rows))


@bp.route("/external-scans/<scan_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY, INSURED])
def read_scan(scan_id):
    scan = find_scan(scan_id)
    application = store.applications.get(scan["application_id"])
    scope_guard(owner_of_application(application) if application else None)
    return ok(scan)


@bp.route("/external-scans", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY])
def list_scans():
    rows = list(store.external_scans.values())
    rows = apply_eq(rows, "application_id", filter_value("application_id"))
    rows = apply_eq(rows, "status", filter_value("status", calc.SCAN_STATES))
    return listing(sorted_by_created(rows))


@bp.route("/external-scans/<scan_id>/complete", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def complete_scan(scan_id):
    scan = find_scan(scan_id)
    payload = validate.body()
    outcome = validate.req_enum(payload, "outcome", ("COMPLETED", "FAILED"))
    scan_score = validate.opt_num(payload, "scan_score", minimum=0, maximum=100)
    findings = []
    seen_keys = set()
    catalog = calc.catalog_by_key()
    if validate.present(payload, "findings"):
        entries = validate.req_object_array(payload, "findings", non_empty=False)
        for entry in entries:
            control_key = validate.req_enum(entry, "control_key", calc.CONTROL_KEYS)
            severity = validate.req_enum(entry, "severity", calc.SEVERITIES)
            observed_level = validate.req_enum(entry, "observed_level", calc.LEVELS)
            if control_key not in catalog:
                raise bad_request("finding control_key %s is not in the control catalog"
                                  % control_key)
            if control_key in seen_keys:
                raise bad_request("at most one findings entry per control_key is allowed")
            seen_keys.add(control_key)
            findings.append({"control_key": control_key, "severity": severity,
                             "observed_level": observed_level})
    if scan["status"] != "PENDING":
        raise ApiError(errors.ERR_INVALID_SCAN_STATE, 409,
                       "only a PENDING scan may return a result")

    application = store.applications.get(scan["application_id"])
    if scan_score is not None:
        scan["scan_score"] = scan_score
    scan["completed_at"] = now_iso()

    if outcome == "FAILED":
        scan["status"] = "FAILED"
        touch(scan)
        return ok(scan)

    # hop 1
    scan["status"] = "COMPLETED"
    scan["findings"] = findings
    scan["critical_finding_count"] = len([f for f in findings if f["severity"] == "CRITICAL"])
    touch(scan)

    # hop 2 -- rewrite every attestation's verified_level
    observed = {}
    for finding in findings:
        key = finding["control_key"]
        level = finding["observed_level"]
        if key not in observed or calc.LEVEL_ORDER[level] < calc.LEVEL_ORDER[observed[key]]:
            observed[key] = level
    for attestation in calc.sorted_by_created(calc.attestations_of(application["id"])):
        seen = observed.get(attestation["control_key"], "FULL")
        attested = attestation["attested_level"]
        lower = seen if calc.LEVEL_ORDER[seen] < calc.LEVEL_ORDER[attested] else attested
        attestation["verified_level"] = lower
        touch(attestation)

    # hop 3
    score, gaps = calc.control_posture_score(application, "verified")
    application["verified_control_score"] = score
    application["mandatory_gap_count"] = len(gaps)
    application["mandatory_gap_control_keys"] = gaps
    if gaps:
        # hop 3b + hop 4
        application["premium_usd"] = None
        set_application_status(application, "REMEDIATION_REQUIRED")
    else:
        set_application_status(application, "UNDERWRITING")
    return ok(scan)


# --------------------------------------------------------------------------
# quote / decline / bind
# --------------------------------------------------------------------------

def _occ_guard(payload, field, row, error_id):
    expected = validate.req_int(payload, field, None, None)
    if expected != row["version"]:
        raise ApiError(error_id, 412, "%s does not match the current version" % field)


@bp.route("/applications/<application_id>/quote", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def quote_application(application_id):
    application = find_application(application_id)
    payload = validate.body()
    _occ_guard(payload, "expected_application_version", application,
               errors.ERR_STALE_APPLICATION_VERSION)
    if application["status"] not in ("UNDERWRITING", "QUOTED"):
        raise ApiError(errors.ERR_INVALID_APPLICATION_STATE, 409,
                       "only an application in UNDERWRITING or QUOTED may be quoted")

    newest = calc.latest_scan(application["id"])
    if newest is None or newest["status"] != "COMPLETED":
        raise ApiError(errors.ERR_SCAN_NOT_COMPLETED, 422,
                       "the application's latest external scan is not COMPLETED")
    score, gaps = calc.control_posture_score(application, "verified")
    if gaps:
        # PRD §3.5 gate 2: the recomputation only blocks the quote; the stored
        # mandatory_gap_count still reads whatever the scan cascade left there.
        raise ApiError(errors.ERR_MANDATORY_CONTROL_GAP, 422,
                       "mandatory control gaps remain: %s" % ", ".join(gaps))
    if dec(score) < calc.MIN_SCORE_FOR_COVERAGE:
        raise ApiError(errors.ERR_CONTROL_SCORE_BELOW_MINIMUM, 422,
                       "verified control score is below the minimum for coverage")

    account = store.insured_accounts[application["insured_account_id"]]
    application["verified_control_score"] = score
    application["mandatory_gap_count"] = 0
    application["mandatory_gap_control_keys"] = []
    application["premium_usd"] = calc.premium_quote(account, application, score)
    application["quoted_by_user_id"] = g.user_id
    expires = plus_days(store.clock, calc.QUOTE_VALID_DAYS)
    application["quote_expires_at"] = iso3(expires)
    application["_quote_expires_at"] = expires
    application["status"] = "QUOTED"
    touch(application)
    return ok(application)


@bp.route("/applications/<application_id>/decline", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def decline_application(application_id):
    application = find_application(application_id)
    payload = validate.body()
    reason = validate.req_str(payload, "declined_reason", 1, None)
    if application["status"] not in ("UNDERWRITING", "REMEDIATION_REQUIRED", "QUOTED"):
        raise ApiError(errors.ERR_INVALID_APPLICATION_STATE, 409,
                       "this application may not be declined from %s" % application["status"])
    application["declined_reason"] = reason
    application["premium_usd"] = None
    set_application_status(application, "DECLINED")
    return ok(application)


def _validate_tower(payload, aggregate_limit):
    entries = validate.req_object_array(payload, "coverage_sections", non_empty=True)
    parsed = []
    for entry in entries:
        section_key = validate.req_enum(entry, "section_key", calc.SECTION_KEYS)
        sublimit = validate.req_num(entry, "sublimit_usd", minimum=0, exclusive_min=True,
                                    money=True)
        erosion_priority = validate.req_int(entry, "erosion_priority", 1, 99)
        coinsurance = validate.opt_num(entry, "coinsurance_pct", minimum=0,
                                       maximum=Decimal("0.50"), default=round2(0))
        if section_key in calc.INTERRUPTION_SECTION_KEYS:
            waiting = validate.req_num(entry, "waiting_period_hours", minimum=0,
                                       maximum=168, exclusive_min=True)
        else:
            if validate.present(entry, "waiting_period_hours"):
                raise bad_request("waiting_period_hours must be null for %s" % section_key)
            waiting = None
        parsed.append({
            "section_key": section_key,
            "sublimit_usd": round2(sublimit),
            "erosion_priority": erosion_priority,
            "coinsurance_pct": coinsurance,
            "waiting_period_hours": waiting,
        })
    return parsed


@bp.route("/applications/<application_id>/bind", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def bind_application(application_id):
    application = find_application(application_id)
    if application["quoted_by_user_id"] is not None \
            and g.user_id == application["quoted_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "the underwriter who quoted this risk may not bind it")
    payload = validate.body()
    period_start_raw, period_start = validate.req_dt(payload, "period_start")
    period_end_raw, period_end = validate.req_dt(payload, "period_end")
    if not period_start < period_end:
        raise bad_request("period_end must be strictly after period_start")
    baseline = validate.req_enum(payload, "bi_baseline_method", calc.BASELINE_METHODS)
    named_dependencies = validate.opt_array(payload, "named_dependency_keys",
                                            calc.NAMED_DEPENDENCY_KEYS, default=[])
    sections = _validate_tower(payload, application["requested_aggregate_limit_usd"])
    _occ_guard(payload, "expected_application_version", application,
               errors.ERR_STALE_APPLICATION_VERSION)

    if application["status"] != "QUOTED":
        raise ApiError(errors.ERR_INVALID_APPLICATION_STATE, 409,
                       "only a QUOTED application may be bound")
    if application["mandatory_gap_count"]:
        raise ApiError(errors.ERR_MANDATORY_CONTROL_GAP, 422,
                       "mandatory control gaps remain on this application")
    expires_at = application.get("_quote_expires_at")
    if expires_at is None or store.clock >= expires_at:
        raise ApiError(errors.ERR_QUOTE_EXPIRED, 422, "the quote has expired")

    aggregate = dec(application["requested_aggregate_limit_usd"])
    for existing in calc.policies_of_account(application["insured_account_id"]):
        if existing["lifecycle_status"] != "INFORCE":
            continue
        if period_start < existing["_period_end"] and existing["_period_start"] < period_end:
            raise ApiError(errors.ERR_POLICY_PERIOD_OVERLAP, 422,
                           "an in-force policy already covers part of this period")

    keys = [entry["section_key"] for entry in sections]
    priorities = [entry["erosion_priority"] for entry in sections]
    if "FIRST_PARTY_RESPONSE" not in keys:
        raise ApiError(errors.ERR_INVALID_TOWER_STRUCTURE, 422,
                       "the tower must include a FIRST_PARTY_RESPONSE section")
    if len(set(keys)) != len(keys):
        raise ApiError(errors.ERR_INVALID_TOWER_STRUCTURE, 422,
                       "section_key must be unique within the policy")
    if len(set(priorities)) != len(priorities):
        raise ApiError(errors.ERR_INVALID_TOWER_STRUCTURE, 422,
                       "erosion_priority must be unique within the policy")

    interruption_total = sum((entry["sublimit_usd"] for entry in sections
                              if entry["section_key"] in calc.INTERRUPTION_SECTION_KEYS),
                             Decimal("0"))
    for entry in sections:
        if entry["sublimit_usd"] > aggregate:
            raise ApiError(errors.ERR_SUBLIMIT_EXCEEDS_AGGREGATE, 422,
                           "a section sublimit exceeds the policy aggregate")
    if interruption_total > aggregate:
        raise ApiError(errors.ERR_SUBLIMIT_EXCEEDS_AGGREGATE, 422,
                       "the interruption sublimits exceed the policy aggregate")

    policy = new_row({
        "application_id": application["id"],
        "insured_account_id": application["insured_account_id"],
        "aggregate_limit_usd": round2(aggregate),
        "aggregate_limit_remaining_usd": round2(aggregate),
        "retention_usd": round2(dec(application["requested_retention_usd"])),
        "premium_usd": application["premium_usd"],
        "period_start": period_start_raw,
        "period_end": period_end_raw,
        "bi_baseline_method": baseline,
        "dependent_bi_definition": application["dependent_bi_definition"],
        "named_dependency_keys": named_dependencies,
        "warranty_control_keys": calc.mandatory_catalog_keys(),
        "lapsed_warranty_control_keys": [],
        "warranty_status": "COMPLIANT",
        "lifecycle_status": "INFORCE",
        "limit_status": "INTACT",
        "aggregation_flagged": False,
        "cancelled_at": None,
        "cancellation_reason": None,
        "_period_start": period_start,
        "_period_end": period_end,
    })
    store.policies[policy["id"]] = policy
    for entry in sections:
        section = new_row({
            "policy_id": policy["id"],
            "section_key": entry["section_key"],
            "sublimit_usd": entry["sublimit_usd"],
            "sublimit_remaining_usd": entry["sublimit_usd"],
            "waiting_period_hours": entry["waiting_period_hours"],
            "coinsurance_pct": entry["coinsurance_pct"],
            "erosion_priority": entry["erosion_priority"],
        })
        store.coverage_sections[section["id"]] = section

    application["status"] = "BOUND"
    touch(application)
    return created(policy)
