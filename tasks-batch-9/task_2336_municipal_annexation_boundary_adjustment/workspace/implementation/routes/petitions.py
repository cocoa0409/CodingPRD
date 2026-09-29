"""Petition circulation, owner consents and sufficiency certification (PRD §3.3)."""

from flask import Blueprint

import validate as v
from auth import ANY_ROLE, check_municipality_scope, check_owner_scope, prelude
from clockutil import add_days
from db import base_record, db, touch
from errors import ApiError
from response import object_response, paginate
from services import calc, domain

bp = Blueprint("petitions", __name__)

PETITION_METHODS = ("PETITION_100", "PETITION_MAJORITY")
CONSENT_ROLES = ("PropertyOwner", "CityClerk")


# ---------------------------------------------------------------------------
# Petitions
# ---------------------------------------------------------------------------

@bp.post("/petitions")
def create_petition():
    user_id, role = prelude(("MunicipalPlanner",))
    body = v.get_body()

    soft_case = domain.soft("cases", body.get("annexation_case_id"))
    check_municipality_scope(role, user_id, domain.municipality_id_of_case(soft_case))

    case_id = v.id_field(body, "annexation_case_id")
    case = domain.body_ref("cases", case_id)

    petition_type = v.enum_field(body, "petition_type", ("OWNER_100", "OWNER_MAJORITY"))
    circulation_days = v.int_field(
        body, "circulation_days", required=False, default=180, minimum=1, maximum=365
    )

    domain.assert_case_not_terminal(case)

    if case["status"] not in ("TERRITORY_CERTIFIED", "PETITION_CIRCULATING"):
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "A petition may only circulate on a certified or re-circulating case.",
        )
    if case["method"] not in PETITION_METHODS:
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "The case's method does not use the petition limb.",
        )
    for other in domain.rows("petitions"):
        if other["annexation_case_id"] == case["id"] and other["sufficiency_status"] in (
            "CIRCULATING",
            "SUFFICIENT",
        ):
            raise ApiError(
                "ERR_PETITION_ALREADY_CIRCULATING",
                "The case already has a live petition.",
            )

    started_at = db.now()
    record = base_record()
    record.update(
        {
            "annexation_case_id": case["id"],
            "petition_type": petition_type,
            "circulation_days": circulation_days,
            "circulation_started_at": started_at,
            "circulation_deadline_at": add_days(started_at, circulation_days),
            "sufficiency_status": "CIRCULATING",
            "qualified_signature_assessed_value_cents": 0,
            "qualified_signature_owner_count": 0,
            "signature_value_pct": calc.pct2(0),
            "signature_owner_pct": calc.pct2(0),
        }
    )
    db.petitions[record["id"]] = record

    case["status"] = "PETITION_CIRCULATING"
    touch(case)
    return object_response(record, 201)


@bp.get("/petitions/<petition_id>")
def read_petition(petition_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("petitions", petition_id))


@bp.get("/petitions")
def list_petitions():
    prelude(ANY_ROLE)
    return paginate(domain.rows("petitions"), ("annexation_case_id", "sufficiency_status"))


@bp.post("/petitions/<petition_id>/certify-sufficiency")
def certify_sufficiency(petition_id):
    user_id, role = prelude(("CityClerk",))
    soft_petition = domain.soft("petitions", petition_id)
    check_municipality_scope(
        role,
        user_id,
        domain.municipality_id_of_case(domain.case_of_petition(soft_petition)),
    )
    petition = domain.path_record("petitions", petition_id)
    case = domain.case_of_petition(petition)
    domain.assert_case_not_terminal(case)

    if petition["sufficiency_status"] == "EXPIRED":
        raise ApiError("ERR_PETITION_EXPIRED", "An expired petition can never be certified again.")
    if petition["sufficiency_status"] not in ("CIRCULATING", "INSUFFICIENT"):
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "Only a circulating or insufficient petition may be certified.",
        )

    statute = domain.statute_of_case(case)

    if db.now() > petition["circulation_deadline_at"]:
        # The circulation window lapsed: the petition expires and the case does not move.
        petition["sufficiency_status"] = "EXPIRED"
        touch(petition)
        touch(case)
        return object_response(petition)

    result = domain.evaluate_petition(petition, case, statute)
    if not result["met"]:
        raise ApiError(
            "ERR_PETITION_INSUFFICIENT",
            "The petition does not meet the statutory signature threshold.",
        )

    domain.stamp_petition_aggregates(petition, case, statute)
    petition["sufficiency_status"] = "SUFFICIENT"
    touch(petition)
    case["status"] = "SUFFICIENCY_REVIEW"
    touch(case)
    return object_response(petition)


# ---------------------------------------------------------------------------
# Parcel owner consents
# ---------------------------------------------------------------------------

@bp.post("/parcel-owner-consents")
def create_consent():
    user_id, role = prelude(CONSENT_ROLES)
    body = v.get_body()

    soft_petition = domain.soft("petitions", body.get("petition_id"))
    check_municipality_scope(
        role,
        user_id,
        domain.municipality_id_of_case(domain.case_of_petition(soft_petition)),
    )
    raw_owner = body.get("property_owner_id")
    if isinstance(raw_owner, str):
        check_owner_scope(role, user_id, raw_owner)

    petition_id = v.id_field(body, "petition_id")
    petition = domain.body_ref("petitions", petition_id)
    parcel_id = v.id_field(body, "parcel_id")
    parcel = domain.body_ref("parcels", parcel_id)
    owner_id = v.id_field(body, "property_owner_id")
    domain.body_ref("property_owners", owner_id)

    share = v.num_field(
        body, "ownership_share_pct", exclusive_minimum=0, maximum=100, places=2
    )

    case = domain.case_of_petition(petition)
    domain.assert_case_not_terminal(case)

    if petition["sufficiency_status"] == "EXPIRED":
        raise ApiError("ERR_PETITION_EXPIRED", "The petition has expired.")

    now = db.now()
    if now < petition["circulation_started_at"] or now > petition["circulation_deadline_at"]:
        raise ApiError(
            "ERR_PETITION_WINDOW_CLOSED",
            "The logical clock lies outside the petition's circulation window.",
        )

    if case is None or parcel["annexation_case_id"] != case["id"]:
        raise ApiError(
            "ERR_PARCEL_CASE_MISMATCH",
            "The parcel does not belong to the petition's annexation case.",
        )

    siblings = [
        c
        for c in domain.rows("consents")
        if c["petition_id"] == petition["id"]
        and c["parcel_id"] == parcel["id"]
        and c["consent_status"] == "SIGNED"
    ]
    for existing in siblings:
        if existing["property_owner_id"] == owner_id:
            raise ApiError(
                "ERR_CONSENT_DUPLICATE",
                "This owner has already signed for this parcel on this petition.",
            )

    total_share = sum((calc.D(c["ownership_share_pct"]) for c in siblings), calc.ZERO) + share
    if total_share > calc.HUNDRED:
        raise ApiError(
            "ERR_CONSENT_OWNERSHIP_SHARE_INVALID",
            "Signed ownership shares for this parcel would exceed 100 percent.",
        )

    record = base_record()
    record.update(
        {
            "petition_id": petition["id"],
            "parcel_id": parcel["id"],
            "property_owner_id": owner_id,
            "ownership_share_pct": share,
            "consent_status": "SIGNED",
            "signed_at": now,
            "withdrawn_at": None,
            "qualified_value_cents": calc.share_value_cents(parcel["assessed_value_cents"], share),
        }
    )
    db.consents[record["id"]] = record

    domain.stamp_petition_aggregates(petition, case, domain.statute_of_case(case))
    touch(petition)
    return object_response(record, 201)


@bp.get("/parcel-owner-consents/<consent_id>")
def read_consent(consent_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("consents", consent_id))


@bp.get("/parcel-owner-consents")
def list_consents():
    prelude(ANY_ROLE)
    return paginate(
        domain.rows("consents"),
        ("petition_id", "parcel_id", "property_owner_id", "consent_status"),
    )


@bp.post("/parcel-owner-consents/<consent_id>/withdraw")
def withdraw_consent(consent_id):
    user_id, role = prelude(CONSENT_ROLES)
    soft_consent = domain.soft("consents", consent_id)
    check_municipality_scope(
        role, user_id, domain.municipality_id_of_case(domain.case_of_consent(soft_consent))
    )
    if soft_consent is not None:
        check_owner_scope(role, user_id, soft_consent.get("property_owner_id"))
    consent = domain.path_record("consents", consent_id)

    case = domain.case_of_consent(consent)
    domain.assert_case_not_terminal(case)

    if consent["consent_status"] != "SIGNED":
        raise ApiError("ERR_CONSENT_ALREADY_WITHDRAWN", "The consent is already withdrawn.")

    consent["consent_status"] = "WITHDRAWN"
    consent["withdrawn_at"] = db.now()
    consent["qualified_value_cents"] = 0
    touch(consent)

    petition = domain.soft("petitions", consent["petition_id"])
    if petition is not None and case is not None:
        was_sufficient = petition["sufficiency_status"] == "SUFFICIENT"
        result = domain.stamp_petition_aggregates(petition, case, domain.statute_of_case(case))
        if was_sufficient and not result["met"]:
            petition["sufficiency_status"] = "INSUFFICIENT"
            domain.supersession_cascade(case)
            touch(case)
        touch(petition)
    return object_response(consent)
