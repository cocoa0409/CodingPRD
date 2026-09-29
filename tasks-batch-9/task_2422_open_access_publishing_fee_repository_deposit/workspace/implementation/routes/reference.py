"""Publishers, journals, agreements, coverages, authors, funders, grants, funds."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import schemas
from auth import ALL_ROLES, endpoint
from clock import clock
from db import db, new_ledger_row, new_row, set_fields
from errors import ApiError
from response import object_response
from routes.helpers import paged
from services.determination import recompute_publisher_agreement_count
from services.screening import run_screening
from util import parse_iso_date
from validation import (
    filter_enum,
    get_body,
    invalid,
    opt_int,
    opt_str,
    present,
    req_bool,
    req_date,
    req_enum,
    req_enum_list,
    req_fraction,
    req_int,
    req_number,
    req_str,
    resolve,
    resolve_body_fk,
    resolve_filter,
)

bp = Blueprint("reference", __name__)


def _duplicate(condition, error_id):
    if condition:
        raise ApiError(error_id, 409)


# ------------------------------------------------------------- Publishers

@bp.post("/publishers")
@endpoint(["AgreementAdmin"])
def create_publisher():
    body = get_body()
    name = req_str(body, "name", min_len=1, max_len=200)
    publisher_code = req_str(
        body, "publisher_code", min_len=2, max_len=16, pattern=C.PUBLISHER_CODE_PATTERN
    )
    country_code = req_str(
        body, "country_code", min_len=2, max_len=2, pattern=C.COUNTRY_CODE_PATTERN
    )
    _duplicate(
        any(p["publisher_code"] == publisher_code for p in db.publishers.values()),
        "ERR_DUPLICATE_CODE",
    )
    row = new_row(
        name=name,
        publisher_code=publisher_code,
        country_code=country_code,
        screening_status="UNSCREENED",
        predatory_score=None,
        doaj_indexed=None,
        cope_member=None,
        editorial_board_verified=None,
        retraction_rate_per_1000=None,
        peer_review_days_median=None,
        apc_transparency_score=None,
        author_guidance=None,
        last_screened_at=None,
        active_agreement_count=0,
    )
    db.publishers[row["id"]] = row
    return object_response(schemas.serialize(row, schemas.PUBLISHER), 201)


@bp.get("/publishers/<publisher_id>")
@endpoint(ALL_ROLES)
def get_publisher(publisher_id):
    row = resolve("publisher", publisher_id)
    return object_response(schemas.serialize(row, schemas.PUBLISHER))


@bp.post("/publishers/<publisher_id>/screening-runs")
@endpoint(["ScholCommLibrarian"])
def create_screening_run(publisher_id):
    publisher = resolve("publisher", publisher_id)
    body = get_body()
    signals = {
        "doaj_indexed": req_bool(body, "doaj_indexed"),
        "cope_member": req_bool(body, "cope_member"),
        "editorial_board_verified": req_bool(body, "editorial_board_verified"),
        "retraction_rate_per_1000": req_number(body, "retraction_rate_per_1000", minimum=0),
        "peer_review_days_median": req_int(body, "peer_review_days_median", minimum=0),
        "apc_transparency_score": req_int(
            body, "apc_transparency_score", minimum=0, maximum=100
        ),
    }
    run_screening(publisher, signals)
    return object_response(schemas.serialize(publisher, schemas.PUBLISHER))


@bp.get("/publishers/<publisher_id>/journals")
@endpoint(ALL_ROLES)
def list_publisher_journals(publisher_id):
    resolve("publisher", publisher_id)
    filter_publisher = resolve_filter("publisher", "publisher_id")
    oa_model = filter_enum("oa_model", C.OA_MODELS)
    rows = [j for j in db.journals.values() if j["publisher_id"] == publisher_id]
    if filter_publisher:
        rows = [j for j in rows if j["publisher_id"] == filter_publisher]
    if oa_model:
        rows = [j for j in rows if j["oa_model"] == oa_model]
    return paged(rows, schemas.JOURNAL)


@bp.get("/publishers/<publisher_id>/transformative-agreements")
@endpoint(["AgreementAdmin", "ScholCommLibrarian", "FundManager"])
def list_publisher_agreements(publisher_id):
    resolve("publisher", publisher_id)
    filter_publisher = resolve_filter("publisher", "publisher_id")
    status = filter_enum("status", C.AGREEMENT_STATUSES)
    rows = [a for a in db.agreements.values() if a["publisher_id"] == publisher_id]
    if filter_publisher:
        rows = [a for a in rows if a["publisher_id"] == filter_publisher]
    if status:
        rows = [a for a in rows if a["status"] == status]
    return paged(rows, schemas.AGREEMENT)


# ---------------------------------------------------------------- Journals

@bp.post("/journals")
@endpoint(["AgreementAdmin"])
def create_journal():
    body = get_body()
    publisher = resolve_body_fk(body, "publisher_id", "publisher")
    if publisher is None:
        invalid("publisher_id is required")
    issn = req_str(body, "issn", pattern=C.ISSN_PATTERN)
    title = req_str(body, "title")
    oa_model = req_enum(body, "oa_model", C.OA_MODELS)
    list_apc_cents = req_int(body, "list_apc_cents", minimum=0)
    required_embargo_months = opt_int(
        body,
        "required_embargo_months",
        default=C.DEFAULT_REQUIRED_EMBARGO_MONTHS,
        minimum=0,
        maximum=48,
    )
    _duplicate(any(j["issn"] == issn for j in db.journals.values()), "ERR_DUPLICATE_ISSN")
    row = new_row(
        publisher_id=publisher["id"],
        issn=issn,
        title=title,
        oa_model=oa_model,
        list_apc_cents=list_apc_cents,
        required_embargo_months=required_embargo_months,
    )
    db.journals[row["id"]] = row
    return object_response(schemas.serialize(row, schemas.JOURNAL), 201)


@bp.get("/journals/<journal_id>")
@endpoint(ALL_ROLES)
def get_journal(journal_id):
    row = resolve("journal", journal_id)
    return object_response(schemas.serialize(row, schemas.JOURNAL))


@bp.get("/journals/<journal_id>/coverages")
@endpoint(["AgreementAdmin", "ScholCommLibrarian", "FundManager"])
def list_journal_coverages(journal_id):
    resolve("journal", journal_id)
    filter_journal = resolve_filter("journal", "journal_id")
    rows = [c for c in db.coverages.values() if c["journal_id"] == journal_id]
    if filter_journal:
        rows = [c for c in rows if c["journal_id"] == filter_journal]
    return paged(rows, schemas.COVERAGE)


# ------------------------------------------------ Transformative agreements

@bp.post("/transformative-agreements")
@endpoint(["AgreementAdmin"])
def create_agreement():
    body = get_body()
    publisher = resolve_body_fk(body, "publisher_id", "publisher")
    if publisher is None:
        invalid("publisher_id is required")
    agreement_code = req_str(body, "agreement_code")
    effective_from_raw, effective_from = req_date(body, "effective_from")
    effective_until_raw, effective_until = req_date(body, "effective_until")
    if effective_until <= effective_from:
        invalid("effective_until must be strictly after effective_from")
    article_quota = req_int(body, "article_quota", minimum=1)
    discount_pct = req_fraction(body, "discount_pct", 0, "0.95", max_decimals=4)
    covered_oa_models = req_enum_list(
        body, "covered_oa_models", C.AGREEMENT_COVERED_OA_MODELS
    )
    expected_publisher_version = req_int(body, "expected_publisher_version", minimum=0)

    if expected_publisher_version != publisher["version"]:
        raise ApiError("ERR_STALE_PARENT_VERSION", 412)

    for other in db.agreements.values():
        if other["publisher_id"] != publisher["id"]:
            continue
        if other["status"] not in ("DRAFT", "ACTIVE", "EXHAUSTED"):
            continue
        other_from = parse_iso_date(other["effective_from"])
        other_until = parse_iso_date(other["effective_until"])
        if effective_from < other_until and other_from < effective_until:
            raise ApiError("ERR_AGREEMENT_WINDOW_OVERLAP", 409)

    _duplicate(
        any(a["agreement_code"] == agreement_code for a in db.agreements.values()),
        "ERR_DUPLICATE_AGREEMENT_CODE",
    )

    row = new_row(
        publisher_id=publisher["id"],
        agreement_code=agreement_code,
        effective_from=effective_from_raw,
        effective_until=effective_until_raw,
        article_quota=article_quota,
        articles_used=0,
        discount_pct=discount_pct,
        covered_oa_models=list(covered_oa_models),
        status="DRAFT",
        activated_at=None,
    )
    db.agreements[row["id"]] = row
    set_fields(publisher, _force=True)
    return object_response(schemas.serialize(row, schemas.AGREEMENT), 201)


@bp.get("/transformative-agreements/<agreement_id>")
@endpoint(["AgreementAdmin", "ScholCommLibrarian", "FundManager"])
def get_agreement(agreement_id):
    row = resolve("agreement", agreement_id)
    return object_response(schemas.serialize(row, schemas.AGREEMENT))


@bp.post("/transformative-agreements/<agreement_id>/activation")
@endpoint(["AgreementAdmin"])
def activate_agreement(agreement_id):
    agreement = resolve("agreement", agreement_id)
    has_coverage = any(
        c["agreement_id"] == agreement_id for c in db.coverages.values()
    )
    if agreement["status"] != "DRAFT" or not has_coverage:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVATABLE", 409)
    set_fields(agreement, status="ACTIVE", activated_at=clock.now_iso())
    recompute_publisher_agreement_count(agreement["publisher_id"])
    return object_response(schemas.serialize(agreement, schemas.AGREEMENT))


@bp.post("/transformative-agreements/<agreement_id>/coverages")
@endpoint(["AgreementAdmin"])
def create_coverage(agreement_id):
    agreement = resolve("agreement", agreement_id)
    body = get_body()
    journal = resolve_body_fk(body, "journal_id", "journal")
    if journal is None:
        invalid("journal_id is required")
    coverage_type = req_enum(body, "coverage_type", C.COVERAGE_TYPES)
    if coverage_type == "CAPPED_APC":
        capped_amount_cents = req_int(body, "capped_amount_cents", minimum=1)
    else:
        if present(body, "capped_amount_cents"):
            invalid("capped_amount_cents is only permitted for CAPPED_APC coverage")
        capped_amount_cents = None
    covered_from_raw, covered_from = req_date(body, "covered_from")
    covered_until_raw, covered_until = req_date(body, "covered_until")
    if covered_until < covered_from:
        invalid("covered_until may not precede covered_from")
    if covered_from < parse_iso_date(agreement["effective_from"]):
        invalid("covered_from must lie inside the agreement window")
    if covered_until >= parse_iso_date(agreement["effective_until"]):
        invalid("covered_until must lie inside the agreement window")

    if journal["publisher_id"] != agreement["publisher_id"]:
        raise ApiError("ERR_COVERAGE_JOURNAL_PUBLISHER_MISMATCH", 422)

    for other in db.coverages.values():
        if other["journal_id"] != journal["id"]:
            continue
        other_from = parse_iso_date(other["covered_from"])
        other_until = parse_iso_date(other["covered_until"])
        gap = C.COVERAGE_GAP_DAYS
        if (
            covered_from <= other_until + timedelta(days=gap)
            and covered_until >= other_from - timedelta(days=gap)
        ):
            raise ApiError("ERR_COVERAGE_WINDOW_CONFLICT", 409)

    row = new_ledger_row(
        agreement_id=agreement["id"],
        journal_id=journal["id"],
        coverage_type=coverage_type,
        capped_amount_cents=capped_amount_cents,
        covered_from=covered_from_raw,
        covered_until=covered_until_raw,
    )
    db.coverages[row["id"]] = row
    return object_response(schemas.serialize(row, schemas.COVERAGE), 201)


@bp.get("/transformative-agreements/<agreement_id>/coverages")
@endpoint(["AgreementAdmin", "ScholCommLibrarian", "FundManager"])
def list_agreement_coverages(agreement_id):
    resolve("agreement", agreement_id)
    filter_agreement = resolve_filter("agreement", "agreement_id")
    rows = [c for c in db.coverages.values() if c["agreement_id"] == agreement_id]
    if filter_agreement:
        rows = [c for c in rows if c["agreement_id"] == filter_agreement]
    return paged(rows, schemas.COVERAGE)


# ----------------------------------------------------------------- Authors

@bp.post("/authors")
@endpoint(["AgreementAdmin"])
def create_author():
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    orcid = opt_str(body, "orcid", pattern=C.ORCID_PATTERN)
    department_code = req_str(body, "department_code")
    affiliation_status = req_enum(body, "affiliation_status", C.AFFILIATION_STATUSES)
    appointment_from_raw, _ = req_date(body, "appointment_from")
    appointment_until_raw, _ = req_date(body, "appointment_until")
    annual_cap_cents = opt_int(
        body, "annual_cap_cents", default=C.DEFAULT_ANNUAL_CAP_CENTS, minimum=0
    )
    if orcid is not None:
        _duplicate(
            any(a["orcid"] == orcid for a in db.authors.values()),
            "ERR_DUPLICATE_ORCID",
        )
    row = new_row(
        full_name=full_name,
        email=email,
        orcid=orcid,
        department_code=department_code,
        affiliation_status=affiliation_status,
        appointment_from=appointment_from_raw,
        appointment_until=appointment_until_raw,
        annual_cap_cents=annual_cap_cents,
        apc_committed_cents=0,
        apc_disbursed_cents=0,
        linked_output_count=0,
    )
    db.authors[row["id"]] = row
    return object_response(schemas.serialize(row, schemas.AUTHOR), 201)


@bp.get("/authors/<author_id>")
@endpoint(ALL_ROLES)
def get_author(author_id):
    row = resolve("author", author_id)
    return object_response(schemas.serialize(row, schemas.AUTHOR))


@bp.get("/authors/<author_id>/grants")
@endpoint(["AgreementAdmin", "ScholCommLibrarian", "FundManager", "CorrespondingAuthor"])
def list_author_grants(author_id):
    resolve("author", author_id)
    filter_author = resolve_filter("author", "pi_author_id")
    status = filter_enum("status", C.GRANT_STATUSES)
    rows = [gr for gr in db.grants.values() if gr["pi_author_id"] == author_id]
    if filter_author:
        rows = [gr for gr in rows if gr["pi_author_id"] == filter_author]
    if status:
        rows = [gr for gr in rows if gr["status"] == status]
    return paged(rows, schemas.GRANT)


# ----------------------------------------------------------------- Funders

@bp.post("/funders")
@endpoint(["AgreementAdmin"])
def create_funder():
    body = get_body()
    name = req_str(body, "name")
    funder_code = req_str(body, "funder_code")
    mandate_type = req_enum(body, "mandate_type", C.MANDATE_TYPES)
    max_embargo_months = req_int(body, "max_embargo_months", minimum=0, maximum=24)
    deposit_deadline_days = req_int(body, "deposit_deadline_days", minimum=1, maximum=365)
    license_required = req_enum(body, "license_required", C.LICENSE_REQUIREMENTS)
    apc_allowable = req_bool(body, "apc_allowable")
    _duplicate(
        any(f["funder_code"] == funder_code for f in db.funders.values()),
        "ERR_DUPLICATE_CODE",
    )
    row = new_row(
        name=name,
        funder_code=funder_code,
        mandate_type=mandate_type,
        max_embargo_months=max_embargo_months,
        deposit_deadline_days=deposit_deadline_days,
        license_required=license_required,
        apc_allowable=apc_allowable,
    )
    db.funders[row["id"]] = row
    return object_response(schemas.serialize(row, schemas.FUNDER), 201)


@bp.get("/funders/<funder_id>")
@endpoint(ALL_ROLES)
def get_funder(funder_id):
    row = resolve("funder", funder_id)
    return object_response(schemas.serialize(row, schemas.FUNDER))


@bp.get("/funders/<funder_id>/grants")
@endpoint(["AgreementAdmin", "ScholCommLibrarian", "FundManager"])
def list_funder_grants(funder_id):
    resolve("funder", funder_id)
    filter_funder = resolve_filter("funder", "funder_id")
    status = filter_enum("status", C.GRANT_STATUSES)
    rows = [gr for gr in db.grants.values() if gr["funder_id"] == funder_id]
    if filter_funder:
        rows = [gr for gr in rows if gr["funder_id"] == filter_funder]
    if status:
        rows = [gr for gr in rows if gr["status"] == status]
    return paged(rows, schemas.GRANT)


# ------------------------------------------------------------------ Grants

@bp.post("/grants")
@endpoint(["AgreementAdmin"])
def create_grant():
    body = get_body()
    funder = resolve_body_fk(body, "funder_id", "funder")
    pi_author = resolve_body_fk(body, "pi_author_id", "author")
    if funder is None:
        invalid("funder_id is required")
    if pi_author is None:
        invalid("pi_author_id is required")
    grant_number = req_str(body, "grant_number")
    award_from_raw, award_from = req_date(body, "award_from")
    award_until_raw, award_until = req_date(body, "award_until")
    apc_budget_cents = req_int(body, "apc_budget_cents", minimum=0)
    _duplicate(
        any(gr["grant_number"] == grant_number for gr in db.grants.values()),
        "ERR_DUPLICATE_CODE",
    )
    row = new_row(
        funder_id=funder["id"],
        pi_author_id=pi_author["id"],
        grant_number=grant_number,
        award_from=award_from_raw,
        award_until=award_until_raw,
        apc_budget_cents=apc_budget_cents,
        status="ACTIVE",
        output_count=0,
        compliant_output_count=0,
        mandate_status="IN_PROGRESS",
    )
    db.grants[row["id"]] = row
    return object_response(schemas.serialize(row, schemas.GRANT), 201)


@bp.get("/grants/<grant_id>")
@endpoint(["AgreementAdmin", "ScholCommLibrarian", "FundManager", "CorrespondingAuthor"])
def get_grant(grant_id):
    row = resolve("grant", grant_id)
    return object_response(schemas.serialize(row, schemas.GRANT))


# --------------------------------------------------------------- APC funds

@bp.post("/apc-funds")
@endpoint(["FundManager"])
def create_fund():
    body = get_body()
    fund_code = req_str(body, "fund_code")
    fiscal_year = req_int(body, "fiscal_year", minimum=2020, maximum=2100)
    period_from_raw, _ = req_date(body, "period_from")
    period_to_raw, _ = req_date(body, "period_to")
    total_budget_cents = req_int(body, "total_budget_cents", minimum=1)
    priority_rank = req_int(body, "priority_rank", minimum=1)
    eligible_affiliation_statuses = req_enum_list(
        body, "eligible_affiliation_statuses", C.AFFILIATION_STATUSES
    )
    per_article_cap_cents = req_int(body, "per_article_cap_cents", minimum=1)

    _duplicate(
        any(
            f["fiscal_year"] == fiscal_year and f["priority_rank"] == priority_rank
            for f in db.funds.values()
        ),
        "ERR_DUPLICATE_FUND_PRIORITY",
    )
    _duplicate(
        any(f["fund_code"] == fund_code for f in db.funds.values()),
        "ERR_DUPLICATE_CODE",
    )

    row = new_row(
        fund_code=fund_code,
        fiscal_year=fiscal_year,
        period_from=period_from_raw,
        period_to=period_to_raw,
        total_budget_cents=total_budget_cents,
        committed_cents=0,
        spent_cents=0,
        available_cents=total_budget_cents,
        priority_rank=priority_rank,
        eligible_affiliation_statuses=list(eligible_affiliation_statuses),
        per_article_cap_cents=per_article_cap_cents,
        status="OPEN",
        freeze_reason=None,
    )
    db.funds[row["id"]] = row
    return object_response(schemas.serialize(row, schemas.FUND), 201)


@bp.get("/apc-funds/<fund_id>")
@endpoint(["FundManager", "ScholCommLibrarian"])
def get_fund(fund_id):
    row = resolve("fund", fund_id)
    return object_response(schemas.serialize(row, schemas.FUND))


@bp.post("/apc-funds/<fund_id>/freeze")
@endpoint(["FundManager"])
def freeze_fund(fund_id):
    fund = resolve("fund", fund_id)
    body = get_body()
    reason = req_str(body, "reason")
    if fund["status"] != "OPEN":
        raise ApiError("ERR_FUND_FROZEN", 409)
    set_fields(fund, status="FROZEN", freeze_reason=reason)
    return object_response(schemas.serialize(fund, schemas.FUND))


@bp.get("/apc-funds/<fund_id>/allocations")
@endpoint(["FundManager", "ScholCommLibrarian"])
def list_fund_allocations(fund_id):
    resolve("fund", fund_id)
    filter_fund = resolve_filter("fund", "fund_id")
    status = filter_enum("status", C.ALLOCATION_STATUSES)
    rows = [a for a in db.allocations.values() if a["fund_id"] == fund_id]
    if filter_fund:
        rows = [a for a in rows if a["fund_id"] == filter_fund]
    if status:
        rows = [a for a in rows if a["status"] == status]
    return paged(rows, schemas.ALLOCATION)
