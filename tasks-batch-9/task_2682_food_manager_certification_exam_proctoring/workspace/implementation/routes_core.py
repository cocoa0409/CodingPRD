"""Jurisdictions, training providers, exam forms, testing sites, clock hook."""
from flask import Blueprint

import authz
import cascade
import validation as V
from authz import require, find, deny_scope
from envelope import ok
from errors import ApiError
from helpers import paged, scoped_filter, match
from store import store

core_bp = Blueprint("core", __name__)


# --- jurisdictions ---------------------------------------------------------

@core_bp.post("/jurisdictions")
def create_jurisdiction():
    require(authz.PLATFORM_ADMIN)
    body = V.get_body()
    name = V.req_str(body, "name", 1, 120)
    code = V.req_str(body, "jurisdiction_code", 2, 16)
    bodies = V.req_enum_subset(body, "accepted_accreditation_bodies",
                               V.ACCREDITATION_BODIES)
    languages = V.req_enum_subset(body, "accepted_languages", V.LANGUAGES)
    accepts_remote = V.opt_bool(body, "accepts_remote_proctoring", True)
    override = V.opt_int(body, "min_passing_score_override", 0, 100, None)
    requires_local = V.opt_bool(body, "requires_local_registration", True)
    deadline_days = V.opt_int(body, "posting_deadline_days", 1, 365, 30)
    cycle_months = V.opt_int(body, "recert_cycle_months", 12, 120, 60)
    surcharge = V.opt_decimal(body, "exam_fee_surcharge_pct", 0.0, 0.25, 3, None)
    if surcharge is None:
        surcharge = V.Decimal("0.0")
    for existing in store.jurisdictions.values():
        if existing["jurisdiction_code"] == code:
            raise ApiError("ERR_INVALID_REQUEST",
                           "jurisdiction_code must be unique")
    row = store.base()
    row.update({
        "name": name,
        "jurisdiction_code": code,
        "accepted_accreditation_bodies": bodies,
        "accepted_languages": languages,
        "accepts_remote_proctoring": accepts_remote,
        "min_passing_score_override": override,
        "requires_local_registration": requires_local,
        "posting_deadline_days": deadline_days,
        "recert_cycle_months": cycle_months,
        "exam_fee_surcharge_pct": surcharge,
    })
    store.jurisdictions[row["id"]] = row
    return ok(row, 201)


@core_bp.get("/jurisdictions/<jurisdiction_id>")
def read_jurisdiction(jurisdiction_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.HEALTH_OFFICER,
                            authz.PROVIDER_ADMIN)
    row = find("jurisdiction", jurisdiction_id)
    if role == authz.HEALTH_OFFICER and row["id"] != user_id:
        deny_scope()
    return ok(row)


# --- training providers ----------------------------------------------------

@core_bp.post("/training-providers")
def create_provider():
    require(authz.PLATFORM_ADMIN)
    body = V.get_body()
    legal_name = V.req_str(body, "legal_name", 1, 160)
    jurisdiction_id = V.req_id(body, "jurisdiction_id")
    contact_email = V.req_str(body, "contact_email", 1)
    if "@" not in contact_email:
        raise ApiError("ERR_INVALID_REQUEST", "contact_email must contain @")
    find("jurisdiction", jurisdiction_id)
    row = store.base()
    row.update({
        "legal_name": legal_name,
        "jurisdiction_id": jurisdiction_id,
        "contact_email": contact_email,
        "lifetime_credited_cents": 0,
        "lifetime_charged_cents": 0,
        "credit_balance_cents": 0,
    })
    store.providers[row["id"]] = row
    return ok(row, 201)


@core_bp.get("/training-providers/<provider_id>")
def read_provider(provider_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    row = find("provider", provider_id)
    if role == authz.PROVIDER_ADMIN and row["id"] != user_id:
        deny_scope()
    return ok(row)


@core_bp.get("/training-providers")
def list_providers():
    require(authz.PLATFORM_ADMIN)
    jurisdiction_id = V.query_id("jurisdiction_id")
    rows = [r for r in store.providers.values()
            if match(r, "jurisdiction_id", jurisdiction_id)]
    return paged(rows)


@core_bp.post("/training-providers/<provider_id>/credit-adjustments")
def create_credit_adjustment(provider_id):
    require(authz.PLATFORM_ADMIN)
    provider = find("provider", provider_id)
    body = V.get_body()
    amount = V.req_int(body, "amount_cents", 0, None)
    V.req_str(body, "memo", 1)
    cascade.credit_provider(provider, amount)
    return ok(provider)


# --- exam forms ------------------------------------------------------------

@core_bp.post("/exam-forms")
def create_exam_form():
    require(authz.PLATFORM_ADMIN)
    body = V.get_body()
    form_code = V.req_str(body, "form_code", 1)
    version_label = V.req_str(body, "version_label", 1)
    language = V.req_enum(body, "language", V.LANGUAGES)
    accreditation_body = V.req_enum(body, "accreditation_body",
                                    V.ACCREDITATION_BODIES)
    scored_item_count = V.req_int(body, "scored_item_count", 10, 200)
    national_cut_score = V.req_int(body, "national_cut_score", 0, 100)
    base_minutes = V.req_int(body, "base_minutes", 30, 240)
    pretest_item_count = V.opt_int(body, "pretest_item_count", 0, 40, 0)
    translated_extra = V.opt_int(body, "translated_extra_minutes", 0, 60, 0)
    for existing in store.exam_forms.values():
        if existing["form_code"] == form_code \
                and existing["version_label"] == version_label \
                and existing["language"] == language:
            raise ApiError("ERR_INVALID_REQUEST",
                           "form_code, version_label and language must be unique")
    row = store.base()
    row.update({
        "form_code": form_code,
        "version_label": version_label,
        "language": language,
        "accreditation_body": accreditation_body,
        "scored_item_count": scored_item_count,
        "pretest_item_count": pretest_item_count,
        "national_cut_score": national_cut_score,
        "base_minutes": base_minutes,
        "translated_extra_minutes": translated_extra,
        "status": "ACTIVE",
    })
    store.exam_forms[row["id"]] = row
    return ok(row, 201)


@core_bp.get("/exam-forms/<form_id>")
def read_exam_form(form_id):
    require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN, authz.PROCTOR)
    return ok(find("exam_form", form_id))


@core_bp.get("/exam-forms")
def list_exam_forms():
    require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    language = V.query_enum("language", V.LANGUAGES)
    accreditation_body = V.query_enum("accreditation_body",
                                      V.ACCREDITATION_BODIES)
    status = V.query_enum("status", V.EXAM_FORM_STATUS)
    rows = [r for r in store.exam_forms.values()
            if match(r, "language", language)
            and match(r, "accreditation_body", accreditation_body)
            and match(r, "status", status)]
    return paged(rows)


@core_bp.post("/exam-forms/<form_id>/retire")
def retire_exam_form(form_id):
    require(authz.PLATFORM_ADMIN)
    form = find("exam_form", form_id)
    if form["status"] != "ACTIVE":
        raise ApiError("ERR_EXAM_FORM_RETIRED", "the exam form is already retired")
    form["status"] = "RETIRED"
    store.touch(form)
    return ok(form)


# --- testing sites ---------------------------------------------------------

@core_bp.post("/testing-sites")
def create_testing_site():
    require(authz.PLATFORM_ADMIN)
    body = V.get_body()
    name = V.req_str(body, "name", 1)
    jurisdiction_id = V.req_id(body, "jurisdiction_id")
    seat_count = V.req_int(body, "seat_count", 1, 50)
    address_line = V.req_str(body, "address_line", 1)
    languages = V.req_enum_subset(body, "languages_supported", V.LANGUAGES)
    find("jurisdiction", jurisdiction_id)
    row = store.base()
    row.update({
        "name": name,
        "jurisdiction_id": jurisdiction_id,
        "seat_count": seat_count,
        "address_line": address_line,
        "languages_supported": languages,
        "reserved_seat_minutes": 0,
    })
    store.testing_sites[row["id"]] = row
    return ok(row, 201)


@core_bp.get("/testing-sites/<site_id>")
def read_testing_site(site_id):
    require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    return ok(find("testing_site", site_id))


@core_bp.get("/testing-sites")
def list_testing_sites():
    require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    jurisdiction_id = V.query_id("jurisdiction_id")
    rows = [r for r in store.testing_sites.values()
            if match(r, "jurisdiction_id", jurisdiction_id)]
    return paged(rows)


# --- logical clock test hook ----------------------------------------------

@core_bp.post("/_clock/set_current_utc")
def set_clock():
    require(authz.PLATFORM_ADMIN)
    body = V.get_body()
    moment = V.req_datetime(body, "to_iso8601")
    store.clock = moment
    return ok({"current_utc": moment})
