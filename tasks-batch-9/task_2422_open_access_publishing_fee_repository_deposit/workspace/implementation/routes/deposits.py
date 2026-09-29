"""Repository deposits, submission and curation decisions."""
from flask import Blueprint

import constants as C
import schemas
from auth import endpoint, require_owner
from clock import clock
from db import db, new_row, set_fields, sort_rows
from errors import ApiError
from response import object_response
from routes.helpers import paged
from services import compliance, funding
from validation import (
    filter_enum,
    get_body,
    invalid,
    opt_str,
    req_enum,
    req_int,
    req_str,
    resolve,
    resolve_body_fk,
    resolve_filter,
)

bp = Blueprint("deposits", __name__)

OPEN_DEPOSIT_STATUSES = ("DRAFT", "SUBMITTED")

LICENSE_ALLOWED = {
    "ANY": C.DEPOSIT_LICENSES,
    "CC_BY": ("CC_BY",),
    "CC_BY_OR_NC": ("CC_BY", "CC_BY_NC"),
}


def _license_requirement(article):
    grant = compliance.grant_of(article)
    funder = compliance.funder_of_grant(grant)
    if funder is None:
        return "ANY"
    return funder["license_required"]


@bp.post("/repository-deposits")
@endpoint(["CorrespondingAuthor"])
def create_deposit():
    body = get_body()
    article = resolve_body_fk(body, "article_id", "article")
    if article is not None:
        require_owner(article["corresponding_author_id"])
    if article is None:
        invalid("article_id is required")
    version_label = req_enum(body, "version_label", C.DEPOSIT_VERSION_LABELS)
    file_checksum = req_str(body, "file_checksum", pattern=C.CHECKSUM_PATTERN)
    license_value = req_enum(body, "license", C.DEPOSIT_LICENSES)
    expected_article_version = req_int(body, "expected_article_version", minimum=0)

    if expected_article_version != article["version"]:
        raise ApiError("ERR_STALE_PARENT_VERSION", 412)

    requirement = _license_requirement(article)
    if license_value not in LICENSE_ALLOWED[requirement]:
        raise ApiError("ERR_LICENSE_NOT_PERMITTED", 422)

    for other in db.deposits.values():
        if other["article_id"] == article["id"] and other["status"] in OPEN_DEPOSIT_STATUSES:
            raise ApiError("ERR_DEPOSIT_VERSION_CONFLICT", 409)

    ordinal = article["latest_deposit_ordinal"] + 1
    row = new_row(
        article_id=article["id"],
        version_label=version_label,
        version_ordinal=ordinal,
        file_checksum=file_checksum,
        license=license_value,
        status="DRAFT",
        persistent_identifier=None,
        returned_count=0,
        curation_note=None,
        submitted_at=None,
        ingested_at=None,
        embargo_until=None,
    )
    db.deposits[row["id"]] = row
    set_fields(article, _force=True, latest_deposit_ordinal=ordinal)
    return object_response(schemas.serialize(row, schemas.DEPOSIT), 201)


@bp.get("/articles/<article_id>/deposits")
@endpoint(["ScholCommLibrarian", "RepositoryCurator", "CorrespondingAuthor", "FundManager"])
def list_article_deposits(article_id):
    resolve("article", article_id)
    filter_article = resolve_filter("article", "article_id")
    status = filter_enum("status", C.DEPOSIT_STATUSES)
    rows = [d for d in db.deposits.values() if d["article_id"] == article_id]
    if filter_article:
        rows = [d for d in rows if d["article_id"] == filter_article]
    if status:
        rows = [d for d in rows if d["status"] == status]
    return paged(rows, schemas.DEPOSIT)


@bp.get("/repository-deposits/<deposit_id>")
@endpoint(["ScholCommLibrarian", "RepositoryCurator", "CorrespondingAuthor", "FundManager"])
def get_deposit(deposit_id):
    row = resolve("deposit", deposit_id)
    return object_response(schemas.serialize(row, schemas.DEPOSIT))


@bp.post("/repository-deposits/<deposit_id>/submission")
@endpoint(["CorrespondingAuthor"])
def submit_deposit(deposit_id):
    deposit = resolve("deposit", deposit_id)
    article = db.articles[deposit["article_id"]]
    require_owner(article["corresponding_author_id"])
    if deposit["status"] != "DRAFT":
        raise ApiError("ERR_DEPOSIT_INVALID_STATE", 409)
    set_fields(deposit, status="SUBMITTED", submitted_at=clock.now_iso())
    return object_response(schemas.serialize(deposit, schemas.DEPOSIT))


@bp.post("/repository-deposits/<deposit_id>/curation-decision")
@endpoint(["RepositoryCurator"])
def curate_deposit(deposit_id):
    deposit = resolve("deposit", deposit_id)
    body = get_body()
    decision = req_enum(body, "decision", C.CURATION_DECISIONS)
    curation_note = opt_str(body, "curation_note")
    if deposit["status"] != "SUBMITTED":
        raise ApiError("ERR_DEPOSIT_INVALID_STATE", 409)

    article = db.articles[deposit["article_id"]]
    author = db.authors[article["corresponding_author_id"]]

    if decision == "RETURN":
        set_fields(
            deposit,
            _force=True,
            status="DRAFT",
            returned_count=deposit["returned_count"] + 1,
            curation_note=curation_note,
        )
        return object_response(schemas.serialize(deposit, schemas.DEPOSIT))

    if not author.get("orcid"):
        raise ApiError("ERR_ORCID_REQUIRED", 422)

    handle = "%s%06d" % (C.HANDLE_PREFIX, db.next_ingest_sequence())

    for other in sort_rows(list(db.deposits.values())):
        if other["id"] == deposit["id"]:
            continue
        if other["article_id"] != article["id"]:
            continue
        if other["status"] == "INGESTED":
            set_fields(other, status="SUPERSEDED")

    verdict = compliance.compliance_at_ingest(article)
    ordinal = max(
        [d["version_ordinal"] for d in db.deposits.values() if d["article_id"] == article["id"]]
        or [0]
    )
    set_fields(article, _force=True, latest_deposit_ordinal=ordinal, **verdict)

    set_fields(
        deposit,
        _force=True,
        status="INGESTED",
        ingested_at=clock.now_iso(),
        persistent_identifier=handle,
        curation_note=curation_note,
        embargo_until=article["embargo_until"],
    )

    compliance.recompute_grant(article.get("grant_id"))
    funding.recompute_author_outputs(author["id"])
    return object_response(schemas.serialize(deposit, schemas.DEPOSIT))
