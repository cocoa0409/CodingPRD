"""Accession + DeedOfGift routes (PRD §3.1)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_ACCESSION_NOT_ACCESSIONED,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from util import (
    get_json_body, as_str, as_int, as_bool, parse_date_field, parse_iso8601_opt,
    paginate, parse_pagination, public_view,
)

bp = Blueprint("accessions", __name__)


def serialize_accession(a: dict) -> dict:
    return public_view(a)


def serialize_deed(d: dict) -> dict:
    return public_view(d)


def _get_accession(aid: str) -> dict:
    a = db.accessions.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Accession not found: {aid}")
    return a


def _get_deed(did: str) -> dict:
    d = db.deeds.get(did)
    if d is None:
        raise_err(ERR_NOT_FOUND, f"DeedOfGift not found: {did}")
    return d


# ---------------------------------------------------------------------------
# Accessions
# ---------------------------------------------------------------------------

@bp.route("/accessions", methods=["POST"])
@require_roles("Registrar")
def create_accession(_user_id: str, _role: str):
    body = get_json_body()
    donor_name = as_str(body, "donor_name", required=True)
    donor_contact = as_str(body, "donor_contact", required=True)
    accession_date = as_str(body, "accession_date", required=True)
    parse_date_field(accession_date, "accession_date")
    lot_value = as_int(body, "lot_appraised_value_cents", required=True, minimum=0)

    year = db.get_now().year
    seq = db.accession_year_counters.get(year, 0) + 1
    db.accession_year_counters[year] = seq
    accession_number = f"{year:04d}-{seq:03d}"

    accession = {
        **db.make_common_fields(),
        "donor_name": donor_name,
        "donor_contact": donor_contact,
        "accession_date": accession_date,
        "lot_appraised_value_cents": lot_value,
        "accession_number": accession_number,
        "status": "DRAFT",
        "current_deed_id": None,
    }
    db.accessions[accession["id"]] = accession
    return success_object(serialize_accession(accession), 201)


@bp.route("/accessions", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_accessions(_user_id: str, _role: str):
    status = request.args.get("status")
    items = list(db.accessions.values())
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_accession(a) for a in page], limit, offset, total)


@bp.route("/accessions/<aid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_accession(aid: str, _user_id: str, _role: str):
    return success_object(serialize_accession(_get_accession(aid)))


@bp.route("/accessions/<aid>/submit", methods=["POST"])
@require_roles("Registrar")
def submit_accession(aid: str, _user_id: str, _role: str):
    a = _get_accession(aid)
    if a["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT accession may be submitted")
    a["status"] = "PENDING_DEED"
    db.touch(a)
    return success_object(serialize_accession(a))


@bp.route("/accessions/<aid>/amend", methods=["POST"])
@require_roles("Registrar")
def amend_accession(aid: str, _user_id: str, _role: str):
    a = _get_accession(aid)
    if a["status"] != "ACCESSIONED":
        raise_err(ERR_INVALID_STATE, "Only an ACCESSIONED accession may be amended")
    a["status"] = "AMENDMENT_PENDING"
    db.touch(a)
    return success_object(serialize_accession(a))


@bp.route("/accessions/<aid>/withdraw", methods=["POST"])
@require_roles("Registrar")
def withdraw_accession(aid: str, _user_id: str, _role: str):
    a = _get_accession(aid)
    if a["status"] not in ("DRAFT", "PENDING_DEED"):
        raise_err(ERR_INVALID_STATE, "Only DRAFT or PENDING_DEED accessions may be withdrawn")
    a["status"] = "WITHDRAWN"
    db.touch(a)
    for d in db.deeds.values():
        if d["accession_id"] == aid and d["status"] == "DRAFT":
            d["status"] = "VOIDED"
            db.touch(d)
    return success_object(serialize_accession(a))


# ---------------------------------------------------------------------------
# Deeds of gift
# ---------------------------------------------------------------------------

@bp.route("/accessions/<aid>/deeds", methods=["POST"])
@require_roles("Registrar")
def create_deed(aid: str, _user_id: str, _role: str):
    body = get_json_body()
    reproduction_restricted = as_bool(body, "reproduction_restricted", required=False, default=False)
    publication_license_required = as_bool(body, "publication_license_required", required=False, default=False)
    embargo_raw = body.get("embargo_until")
    embargo_dt = parse_iso8601_opt(body, "embargo_until")
    required_citation_text = body.get("required_citation_text")
    if required_citation_text is not None and not isinstance(required_citation_text, str):
        raise_err(ERR_INVALID_REQUEST, "Field 'required_citation_text' must be a string")

    a = _get_accession(aid)  # path id (priority 4)

    if a["status"] not in ("PENDING_DEED", "AMENDMENT_PENDING", "ACCESSIONED"):
        raise_err(
            ERR_INVALID_STATE,
            "Deeds may be drafted only while the accession is PENDING_DEED, "
            "AMENDMENT_PENDING, or ACCESSIONED",
        )

    deed_version = sum(1 for d in db.deeds.values() if d["accession_id"] == aid) + 1
    deed = {
        **db.make_common_fields(),
        "accession_id": aid,
        "deed_version": deed_version,
        "reproduction_restricted": reproduction_restricted,
        "publication_license_required": publication_license_required,
        "embargo_until": embargo_raw,
        "required_citation_text": required_citation_text,
        "status": "DRAFT",
        "_embargo_dt": embargo_dt,
    }
    db.deeds[deed["id"]] = deed
    return success_object(serialize_deed(deed), 201)


@bp.route("/accessions/<aid>/deeds", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_deeds(aid: str, _user_id: str, _role: str):
    parse_pagination()  # priority 3 precedes path-id existence (priority 4)
    _get_accession(aid)
    items = [d for d in db.deeds.values() if d["accession_id"] == aid]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_deed(d) for d in page], limit, offset, total)


@bp.route("/deeds/<did>/execute", methods=["POST"])
@require_roles("Registrar")
def execute_deed(did: str, _user_id: str, _role: str):
    body = get_json_body()
    expected_version = as_int(body, "expected_accession_version", required=True)

    deed = _get_deed(did)  # priority 4

    # priority 5: deed state
    if deed["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT deed may be executed")

    accession = db.accessions.get(deed["accession_id"])
    if accession is None:
        raise_err(ERR_NOT_FOUND, f"Accession not found: {deed['accession_id']}")

    # priority 6: OCC on the accession version
    if expected_version != accession["version"]:
        raise_err(ERR_STALE_VERSION, "expected_accession_version does not match the accession's current version")

    # priority 7: accession state gate
    if accession["status"] not in ("PENDING_DEED", "AMENDMENT_PENDING", "ACCESSIONED"):
        raise_err(
            ERR_ACCESSION_NOT_ACCESSIONED,
            "The deed's accession must be PENDING_DEED, AMENDMENT_PENDING, or ACCESSIONED",
        )

    # supersede the previously EXECUTED deed (if any)
    for d in db.deeds.values():
        if d["accession_id"] == accession["id"] and d["status"] == "EXECUTED":
            d["status"] = "SUPERSEDED"
            db.touch(d)

    deed["status"] = "EXECUTED"
    db.touch(deed)
    accession["status"] = "ACCESSIONED"
    accession["current_deed_id"] = deed["id"]
    db.touch(accession)
    return success_object(serialize_deed(deed))


@bp.route("/deeds/<did>/void", methods=["POST"])
@require_roles("Registrar")
def void_deed(did: str, _user_id: str, _role: str):
    deed = _get_deed(did)
    if deed["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT deed may be voided")
    deed["status"] = "VOIDED"
    db.touch(deed)
    return success_object(serialize_deed(deed))
