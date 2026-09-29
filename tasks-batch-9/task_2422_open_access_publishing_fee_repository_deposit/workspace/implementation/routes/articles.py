"""Articles, eligibility checks, publication and the determination ledger."""
from flask import Blueprint

import constants as C
import schemas
from auth import ALL_ROLES, endpoint, require_owner
from db import db, new_row, set_fields
from errors import ApiError
from response import object_response
from routes.helpers import paged
from services import compliance
from services.determination import append_determination
from util import parse_iso_date
from validation import (
    filter_enum,
    get_body,
    invalid,
    opt_enum,
    opt_int,
    req_date,
    req_str,
    resolve,
    resolve_body_fk,
    resolve_filter,
)

bp = Blueprint("articles", __name__)


def _publisher_of_article(article):
    journal = db.journals[article["journal_id"]]
    return db.publishers[journal["publisher_id"]]


def _require_publisher_not_blocked(article):
    if _publisher_of_article(article)["screening_status"] == "BLOCKED":
        raise ApiError("ERR_PUBLISHER_BLOCKED", 422)


def _require_grant_active(article):
    grant_id = article.get("grant_id")
    if not grant_id:
        return
    grant = db.grants.get(grant_id)
    if grant is None or grant["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE", 409)


# ---------------------------------------------------------------- Articles

@bp.post("/articles")
@endpoint(["CorrespondingAuthor", "ScholCommLibrarian"])
def create_article():
    body = get_body()
    journal = resolve_body_fk(body, "journal_id", "journal")
    author = resolve_body_fk(body, "corresponding_author_id", "author")
    grant = resolve_body_fk(body, "grant_id", "grant")

    if author is not None:
        require_owner(author["id"])

    if journal is None:
        invalid("journal_id is required")
    if author is None:
        invalid("corresponding_author_id is required")
    manuscript_title = req_str(body, "manuscript_title")
    accepted_on_raw, accepted_on = req_date(body, "accepted_on")
    apc_list_cents = opt_int(body, "apc_list_cents", minimum=0)

    if grant is not None:
        if grant["status"] != "ACTIVE":
            raise ApiError("ERR_GRANT_NOT_ACTIVE", 409)
        award_from = parse_iso_date(grant["award_from"])
        award_until = parse_iso_date(grant["award_until"])
        if accepted_on < award_from or accepted_on > award_until:
            raise ApiError("ERR_GRANT_NOT_ACTIVE", 409)

    appointment_from = parse_iso_date(author["appointment_from"])
    appointment_until = parse_iso_date(author["appointment_until"])
    if accepted_on < appointment_from or accepted_on > appointment_until:
        raise ApiError("ERR_APPOINTMENT_WINDOW_EXPIRED", 422)

    row = new_row(
        journal_id=journal["id"],
        corresponding_author_id=author["id"],
        grant_id=grant["id"] if grant else None,
        manuscript_title=manuscript_title,
        accepted_on=accepted_on_raw,
        publication_date=None,
        apc_list_cents=apc_list_cents,
        doi=None,
        funding_status="DRAFT",
        compliance_status="PENDING_DEPOSIT",
        eligibility_route=None,
        covered_amount_cents=0,
        author_share_cents=0,
        determination_count=0,
        deposit_deadline_on=None,
        embargo_until=None,
        latest_deposit_ordinal=0,
    )
    row.update(compliance.initial_compliance(row))
    db.articles[row["id"]] = row
    if grant is not None:
        compliance.recompute_grant(grant["id"])
    return object_response(schemas.serialize(row, schemas.ARTICLE), 201)


@bp.get("/articles")
@endpoint(ALL_ROLES)
def list_articles():
    journal_id = resolve_filter("journal", "journal_id")
    author_id = resolve_filter("author", "corresponding_author_id")
    grant_id = resolve_filter("grant", "grant_id")
    funding_status = filter_enum("funding_status", C.FUNDING_STATUSES)
    compliance_status = filter_enum("compliance_status", C.COMPLIANCE_STATUSES)
    rows = list(db.articles.values())
    if journal_id:
        rows = [a for a in rows if a["journal_id"] == journal_id]
    if author_id:
        rows = [a for a in rows if a["corresponding_author_id"] == author_id]
    if grant_id:
        rows = [a for a in rows if a.get("grant_id") == grant_id]
    if funding_status:
        rows = [a for a in rows if a["funding_status"] == funding_status]
    if compliance_status:
        rows = [a for a in rows if a["compliance_status"] == compliance_status]
    return paged(rows, schemas.ARTICLE)


@bp.get("/articles/<article_id>")
@endpoint(ALL_ROLES)
def get_article(article_id):
    row = resolve("article", article_id)
    return object_response(schemas.serialize(row, schemas.ARTICLE))


@bp.post("/articles/<article_id>/eligibility-checks")
@endpoint(["ScholCommLibrarian", "CorrespondingAuthor"])
def create_eligibility_check(article_id):
    article = resolve("article", article_id)
    require_owner(article["corresponding_author_id"])
    body = get_body()
    basis = opt_enum(body, "basis", C.DETERMINATION_BASES, default="PROVISIONAL")
    _require_publisher_not_blocked(article)
    _require_grant_active(article)
    row = append_determination(article, basis)
    return object_response(schemas.serialize(row, schemas.DETERMINATION), 201)


@bp.post("/articles/<article_id>/publication")
@endpoint(["ScholCommLibrarian"])
def publish_article(article_id):
    article = resolve("article", article_id)
    body = get_body()
    publication_date_raw, _ = req_date(body, "publication_date")
    if article.get("publication_date") is not None:
        raise ApiError("ERR_ARTICLE_ALREADY_PUBLISHED", 409)

    journal = db.journals[article["journal_id"]]
    publisher = db.publishers[journal["publisher_id"]]
    doi = "%s%s.%d" % (
        C.DOI_PREFIX,
        publisher["publisher_code"],
        db.next_publication_sequence(),
    )

    # the FINAL determination and the embargo both read the new publication date
    article["publication_date"] = publication_date_raw
    _, embargo_until = compliance.deadline_and_embargo(article)

    append_determination(
        article,
        "FINAL",
        extra_article_changes={
            "publication_date": publication_date_raw,
            "doi": doi,
            "embargo_until": embargo_until,
        },
    )
    return object_response(schemas.serialize(article, schemas.ARTICLE))


# ------------------------------------------------------ Determination ledger

@bp.get("/eligibility-determinations")
@endpoint(["AgreementAdmin", "ScholCommLibrarian", "FundManager", "CorrespondingAuthor"])
def list_determinations():
    article_id = resolve_filter("article", "article_id")
    agreement_id = resolve_filter("agreement", "agreement_id")
    coverage_id = resolve_filter("coverage", "coverage_id")
    basis = filter_enum("basis", C.DETERMINATION_BASES)
    rows = list(db.determinations.values())
    if article_id:
        rows = [d for d in rows if d["article_id"] == article_id]
    if agreement_id:
        rows = [d for d in rows if d.get("agreement_id") == agreement_id]
    if coverage_id:
        rows = [d for d in rows if d.get("coverage_id") == coverage_id]
    if basis:
        rows = [d for d in rows if d["basis"] == basis]
    return paged(rows, schemas.DETERMINATION)


@bp.get("/eligibility-determinations/<determination_id>")
@endpoint(["AgreementAdmin", "ScholCommLibrarian", "FundManager", "CorrespondingAuthor"])
def get_determination(determination_id):
    row = resolve("determination", determination_id)
    return object_response(schemas.serialize(row, schemas.DETERMINATION))
