"""Tenant registry, crew roster and the logical clock."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import derive
import response
import serialize
import store
import validators as V
from errors import fail
from store import S, insert, now, touch

bp = Blueprint("admin", __name__)

CLIENT_FIELDS = [
    ("legal_name", "string", True),
    ("industry_code", "string", True),
    ("grading_policy", "string", False),
    ("max_trir", "number", False),
    ("max_dart_rate", "number", False),
    ("max_emr", "number", False),
    ("max_citation_points", "integer", False),
    ("weight_trir", "number", False),
    ("weight_dart", "number", False),
    ("weight_emr", "number", False),
    ("weight_citation", "number", False),
    ("conditional_band_pct", "number", False),
    ("requalification_interval_months", "integer", False),
    ("audit_sample_rate_pct", "number", False),
    ("cascade_depth_limit", "integer", False),
    ("required_coverage_types", "array", False),
]


@bp.route("/clients", methods=["POST"])
def create_client():
    auth.authenticate([auth.ROLE_NETWORK_ADMIN])
    body = V.parse_body(CLIENT_FIELDS)

    legal_name = V.check_str_len("legal_name", body["legal_name"], 1, 200)
    industry_code = body["industry_code"]
    if len(industry_code) != 6 or not industry_code.isdigit():
        fail("ERR_INVALID_FIELD_VALUE", "industry_code must be exactly six digits.")
    grading_policy = "BALANCED"
    if body["grading_policy"] is not None:
        grading_policy = V.check_enum("grading_policy", body["grading_policy"], calc.GRADING_POLICIES)

    def number(name, default, lo=None, hi=None, lo_strict=False):
        if body[name] is None:
            return Decimal(default)
        return V.check_num_range(name, body[name], lo=lo, hi=hi, lo_strict=lo_strict)

    max_trir = number("max_trir", "3.00", lo=0, lo_strict=True)
    max_dart_rate = number("max_dart_rate", "1.50", lo=0, lo_strict=True)
    max_emr = number("max_emr", "1.00", lo=0, lo_strict=True)
    if body["max_citation_points"] is None:
        max_citation_points = 6
    else:
        max_citation_points = V.check_int_range(
            "max_citation_points", body["max_citation_points"], lo=0
        )
    weight_trir = number("weight_trir", "0.40", lo=0, hi=1, lo_strict=True)
    weight_dart = number("weight_dart", "0.25", lo=0, hi=1, lo_strict=True)
    weight_emr = number("weight_emr", "0.25", lo=0, hi=1, lo_strict=True)
    weight_citation = number("weight_citation", "0.10", lo=0, hi=1, lo_strict=True)
    if (weight_trir + weight_dart + weight_emr + weight_citation) != Decimal("1.00"):
        fail("ERR_INVALID_FIELD_VALUE", "The four metric weights must sum to exactly 1.00.")

    conditional_band_pct = number("conditional_band_pct", "20", lo=0, hi=100)
    if body["requalification_interval_months"] is None:
        interval = 12
    else:
        interval = V.check_int_range(
            "requalification_interval_months", body["requalification_interval_months"], lo=1, hi=36
        )
    audit_sample_rate_pct = number("audit_sample_rate_pct", "25", lo=0, hi=100)
    if body["cascade_depth_limit"] is None:
        cascade_depth_limit = 2
    else:
        cascade_depth_limit = V.check_int_range(
            "cascade_depth_limit", body["cascade_depth_limit"], lo=1, hi=5
        )
    if body["required_coverage_types"] is None:
        required_coverage_types = ["GL", "WC"]
    else:
        required_coverage_types = V.check_subset(
            "required_coverage_types", body["required_coverage_types"], calc.COVERAGE_TYPES
        )

    for existing in S.clients.values():
        if existing["legal_name"] == legal_name:
            fail("ERR_INVALID_FIELD_VALUE", "legal_name is already registered.")

    row = store.base_row()
    row.update(
        {
            "legal_name": legal_name,
            "industry_code": industry_code,
            "grading_policy": grading_policy,
            "max_trir": max_trir,
            "max_dart_rate": max_dart_rate,
            "max_emr": max_emr,
            "max_citation_points": max_citation_points,
            "weight_trir": weight_trir,
            "weight_dart": weight_dart,
            "weight_emr": weight_emr,
            "weight_citation": weight_citation,
            "conditional_band_pct": conditional_band_pct,
            "requalification_interval_months": interval,
            "audit_sample_rate_pct": audit_sample_rate_pct,
            "cascade_depth_limit": cascade_depth_limit,
            "required_coverage_types": required_coverage_types,
        }
    )
    insert(S.clients, row)
    return response.created(serialize.client(row))


@bp.route("/clients/<client_id>/sites", methods=["POST"])
def create_site(client_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    body = V.parse_body(
        [
            ("client_id", "string", False),
            ("site_code", "string", True),
            ("required_hazard_classes", "array", True),
            ("min_grade", "string", False),
        ]
    )
    site_code = V.check_str_len("site_code", body["site_code"], 1, 40)
    hazard_classes = V.check_subset(
        "required_hazard_classes", body["required_hazard_classes"], calc.HAZARD_CLASSES
    )
    min_grade = "C"
    if body["min_grade"] is not None:
        min_grade = V.check_enum("min_grade", body["min_grade"], calc.SITE_MIN_GRADES)

    client_row = V.get_client(client_id)
    auth.check_owner(role, user_id, client_id=client_row["id"])

    for existing in derive.sites_of(client_row["id"]):
        if existing["site_code"] == site_code:
            fail("ERR_INVALID_FIELD_VALUE", "site_code is already used by this client.")

    row = store.base_row()
    row.update(
        {
            "client_id": client_row["id"],
            "site_code": site_code,
            "required_hazard_classes": hazard_classes,
            "min_grade": min_grade,
            "granted_worker_count": 0,
            "access_gate_status": "OPEN",
        }
    )
    insert(S.sites, row)
    return response.created(serialize.site(row))


@bp.route("/contractors", methods=["POST"])
def create_contractor():
    auth.authenticate([auth.ROLE_NETWORK_ADMIN])
    body = V.parse_body(
        [
            ("legal_name", "string", True),
            ("scope_of_work", "array", True),
            ("hazard_profile", "array", True),
            ("employee_count", "integer", True),
        ]
    )
    legal_name = V.check_str_len("legal_name", body["legal_name"], 1, 200)
    scope_of_work = V.check_subset("scope_of_work", body["scope_of_work"], calc.TRADE_CODES)
    hazard_profile = V.check_subset("hazard_profile", body["hazard_profile"], calc.HAZARD_CLASSES)
    employee_count = V.check_int_range("employee_count", body["employee_count"], lo=1)

    for existing in S.contractors.values():
        if existing["legal_name"] == legal_name:
            fail("ERR_INVALID_FIELD_VALUE", "legal_name is already registered.")

    row = store.base_row()
    row.update(
        {
            "legal_name": legal_name,
            "scope_of_work": scope_of_work,
            "hazard_profile": hazard_profile,
            "employee_count": employee_count,
            "status": "ACTIVE",
            "base_hazard_tier": calc.base_hazard_tier(hazard_profile),
            "incident_review_flag": False,
            "open_severe_incident_count": 0,
            "open_deficiency_count": 0,
            "verified_coverage_types": [],
        }
    )
    insert(S.contractors, row)
    return response.created(serialize.contractor(row))


@bp.route("/contractors/<contractor_id>", methods=["PATCH"])
def patch_contractor(contractor_id):
    auth.authenticate([auth.ROLE_NETWORK_ADMIN])
    body = V.parse_body(
        [
            ("scope_of_work", "array", False),
            ("hazard_profile", "array", False),
            ("employee_count", "integer", False),
            ("status", "string", False),
        ]
    )
    scope_of_work = None
    if body["scope_of_work"] is not None:
        scope_of_work = V.check_subset("scope_of_work", body["scope_of_work"], calc.TRADE_CODES)
    hazard_profile = None
    if body["hazard_profile"] is not None:
        hazard_profile = V.check_subset(
            "hazard_profile", body["hazard_profile"], calc.HAZARD_CLASSES
        )
    employee_count = None
    if body["employee_count"] is not None:
        employee_count = V.check_int_range("employee_count", body["employee_count"], lo=1)
    new_status = None
    if body["status"] is not None:
        new_status = V.check_enum("status", body["status"], calc.CONTRACTOR_STATUSES)

    row = V.get_contractor(contractor_id)

    if hazard_profile is not None:
        needed = set()
        for grant in S.site_access_grants.values():
            if grant["status"] != "GRANTED":
                continue
            preq = S.prequalifications.get(grant["prequalification_id"])
            if preq is None or preq["contractor_id"] != row["id"]:
                continue
            site = S.sites.get(grant["site_id"])
            if site is not None:
                needed.update(site["required_hazard_classes"])
        if not needed.issubset(set(hazard_profile)):
            fail(
                "ERR_HAZARD_PROFILE_MISMATCH",
                "hazard_profile may not drop a class required by a site holding a granted badge.",
            )
        row["hazard_profile"] = hazard_profile
        row["base_hazard_tier"] = calc.base_hazard_tier(hazard_profile)
    if scope_of_work is not None:
        row["scope_of_work"] = scope_of_work
    if employee_count is not None:
        row["employee_count"] = employee_count
    if new_status is not None:
        row["status"] = new_status
    touch(row)
    return response.ok(serialize.contractor(row))


@bp.route("/contractors/<contractor_id>/workers", methods=["POST"])
def create_worker(contractor_id):
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(
        [
            ("contractor_id", "string", False),
            ("full_name", "string", True),
            ("employee_ref", "string", True),
            ("trade_code", "string", True),
        ]
    )
    full_name = V.check_str_len("full_name", body["full_name"], 1, 120)
    employee_ref = V.check_str_len("employee_ref", body["employee_ref"], 1, 40)
    trade_code = V.check_enum("trade_code", body["trade_code"], calc.TRADE_CODES)

    contractor_row = V.get_contractor(contractor_id)
    auth.check_owner(role, user_id, contractor_id=contractor_row["id"])

    for existing in derive.workers_of(contractor_row["id"]):
        if existing["employee_ref"] == employee_ref:
            fail("ERR_INVALID_FIELD_VALUE", "employee_ref is already used by this contractor.")

    row = store.base_row(versioned=False)
    row.update(
        {
            "contractor_id": contractor_row["id"],
            "full_name": full_name,
            "employee_ref": employee_ref,
            "trade_code": trade_code,
        }
    )
    insert(S.workers, row)
    return response.created(serialize.worker(row))


@bp.route("/workers/<worker_id>/qualifications", methods=["POST"])
def create_qualification(worker_id):
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(
        [
            ("worker_id", "string", False),
            ("qualification_code", "string", True),
            ("issued_date", "string", True),
            ("expiration_date", "string", True),
            ("training_provider", "string", True),
            ("evidence_ref", "string", True),
        ]
    )
    qualification_code = V.check_enum(
        "qualification_code", body["qualification_code"], calc.QUALIFICATION_CODES
    )
    issued_date = V.parse_instant("issued_date", body["issued_date"])
    expiration_date = V.parse_instant("expiration_date", body["expiration_date"])
    training_provider = V.check_str_len("training_provider", body["training_provider"], 1, 120)
    evidence_ref = V.check_str_len("evidence_ref", body["evidence_ref"], 1, 120)
    if issued_date > now():
        fail("ERR_INVALID_FIELD_VALUE", "issued_date must be at or before the logical clock.")
    if expiration_date <= issued_date:
        fail("ERR_INVALID_FIELD_VALUE", "expiration_date must be strictly after issued_date.")

    worker_row = V.get_worker(worker_id)
    auth.check_owner(role, user_id, contractor_id=worker_row["contractor_id"])

    row = store.base_row(versioned=False)
    row.update(
        {
            "worker_id": worker_row["id"],
            "qualification_code": qualification_code,
            "issued_date": issued_date,
            "expiration_date": expiration_date,
            "training_provider": training_provider,
            "evidence_ref": evidence_ref,
        }
    )
    insert(S.worker_qualifications, row)
    return response.created(serialize.worker_qualification(row))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth.authenticate([auth.ROLE_NETWORK_ADMIN])
    body = V.parse_body([("current_utc", "string", True)])
    current_utc = V.parse_instant("current_utc", body["current_utc"])
    previous = S.clock
    S.clock = current_utc
    return response.ok(
        {
            "current_utc": store.fmt_dt(current_utc),
            "previous_utc": store.fmt_dt(previous),
        }
    )
