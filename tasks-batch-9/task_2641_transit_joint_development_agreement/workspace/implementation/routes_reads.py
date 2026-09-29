"""The 25 read endpoints. All seven roles may call every read endpoint."""

from flask import Blueprint, g

import authz
import common
import enums
import envelope
import shape
import store
from errors import fail

bp = Blueprint("reads", __name__)


def _read_auth():
    return authz.authorize(*authz.ALL_ROLES)


# -------------------------------------------------------------------- sites ---
@bp.get("/jda/sites")
def list_sites():
    _read_auth()
    limit, offset = shape.paging()
    status = shape.query_enum("status", enums.SITE_STATUS)
    tier = shape.query_enum("tier", enums.READINESS_TIER)
    funding = shape.query_enum("acquisition_funding_source", enums.FUNDING_SOURCE)
    records = store.all_of("site")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if tier is not None:
        records = [r for r in records if r["readiness_tier"] == tier]
    if funding is not None:
        records = [r for r in records if r["acquisition_funding_source"] == funding]
    records = sorted(records, key=lambda r: (r["site_code"], r["_seq"]))
    return common.respond_list(records, limit, offset)


@bp.get("/jda/sites/<site_id>")
def get_site(site_id):
    _read_auth()
    return envelope.ok(common.public(store.require("site", site_id)))


@bp.get("/jda/sites/<site_id>/assessments")
def list_site_assessments(site_id):
    _read_auth()
    limit, offset = shape.paging()
    status = shape.query_enum("status", enums.ASSESSMENT_STATUS)
    store.require("site", site_id)
    records = common.assessments_of(site_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    # newest first, with id ascending as the tie-break
    records = sorted(records, key=lambda r: r["id"])
    records = sorted(records, key=lambda r: r["created_at"], reverse=True)
    return common.respond_list(records, limit, offset)


@bp.get("/jda/sites/<site_id>/solicitations")
def list_site_solicitations(site_id):
    _read_auth()
    limit, offset = shape.paging()
    status = shape.query_enum("status", enums.SOLICITATION_STATUS)
    store.require("site", site_id)
    records = common.solicitations_of(site_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return common.respond_list(common.created_asc(records), limit, offset)


@bp.get("/jda/sites/<site_id>/valuations")
def list_site_valuations(site_id):
    _read_auth()
    limit, offset = shape.paging()
    status = shape.query_enum("status", enums.VALUATION_STATUS)
    store.require("site", site_id)
    records = common.valuations_of(site_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return common.respond_list(common.created_asc(records), limit, offset)


@bp.get("/jda/sites/<site_id>/shared-facilities")
def list_site_facilities(site_id):
    _read_auth()
    limit, offset = shape.paging()
    store.require("site", site_id)
    records = common.facilities_of(site_id)
    return common.respond_list(common.created_asc(records), limit, offset)


# ---------------------------------------------------- solicitations, developers ---
@bp.get("/jda/solicitations/<solicitation_id>")
def get_solicitation(solicitation_id):
    _read_auth()
    return envelope.ok(common.public(store.require("solicitation", solicitation_id)))


@bp.get("/jda/developers/<developer_id>")
def get_developer(developer_id):
    _read_auth()
    return envelope.ok(common.public(store.require("developer", developer_id)))


# ---------------------------------------------------------------- proposals ---
@bp.get("/jda/proposals/<proposal_id>")
def get_proposal(proposal_id):
    _read_auth()
    proposal = store.require("proposal", proposal_id)
    if g.role == "Developer" and proposal["developer_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This proposal belongs to another developer")
    return envelope.ok(common.public(proposal))


@bp.get("/jda/proposals")
def list_proposals():
    _read_auth()
    limit, offset = shape.paging()
    solicitation_id = shape.query_str("solicitation_id")
    developer_id = shape.query_str("developer_id")
    status = shape.query_enum("status", enums.PROPOSAL_STATUS)
    records = store.all_of("proposal")
    if solicitation_id is not None:
        records = [r for r in records if r["solicitation_id"] == solicitation_id]
    if developer_id is not None:
        records = [r for r in records if r["developer_id"] == developer_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    # rank ASC (unranked proposals last), created_at ASC as the tie-break
    records = sorted(records,
                     key=lambda r: ((0, r["rank"]) if r["rank"] is not None else (1, 0),
                                    r["created_at"], r["_seq"]))
    return common.respond_list(records, limit, offset)


# -------------------------------------------------------- negotiation periods ---
@bp.get("/jda/negotiation-periods/<period_id>")
def get_period(period_id):
    _read_auth()
    return envelope.ok(common.public(store.require("negotiation_period", period_id)))


@bp.get("/jda/negotiation-periods")
def list_periods():
    _read_auth()
    limit, offset = shape.paging()
    site_id = shape.query_str("site_id")
    proposal_id = shape.query_str("proposal_id")
    status = shape.query_enum("status", enums.PERIOD_STATUS)
    records = store.all_of("negotiation_period")
    if site_id is not None:
        records = [r for r in records if r["site_id"] == site_id]
    if proposal_id is not None:
        records = [r for r in records if r["proposal_id"] == proposal_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sorted(records, key=lambda r: (r["start_date"], r["created_at"], r["_seq"]))
    return common.respond_list(records, limit, offset)


# ---------------------------------------------------- valuations, assessments ---
@bp.get("/jda/valuations/<valuation_id>")
def get_valuation(valuation_id):
    _read_auth()
    return envelope.ok(common.public(store.require("valuation", valuation_id)))


@bp.get("/jda/assessments/<assessment_id>")
def get_assessment(assessment_id):
    _read_auth()
    return envelope.ok(common.public(store.require("assessment", assessment_id)))


# --------------------------------------------------------------- agreements ---
@bp.get("/jda/agreements/<agreement_id>")
def get_agreement(agreement_id):
    _read_auth()
    return envelope.ok(common.public(store.require("agreement", agreement_id)))


@bp.get("/jda/agreements")
def list_agreements():
    _read_auth()
    limit, offset = shape.paging()
    site_id = shape.query_str("site_id")
    developer_id = shape.query_str("developer_id")
    proposal_id = shape.query_str("proposal_id")
    valuation_id = shape.query_str("valuation_id")
    negotiation_status = shape.query_enum("negotiation_status", enums.NEGOTIATION_STATUS)
    federal_status = shape.query_enum("federal_approval_status", enums.FEDERAL_APPROVAL_STATUS)
    records = store.all_of("agreement")
    if site_id is not None:
        records = [r for r in records if r["site_id"] == site_id]
    if developer_id is not None:
        records = [r for r in records if r["developer_id"] == developer_id]
    if proposal_id is not None:
        records = [r for r in records if r["proposal_id"] == proposal_id]
    if valuation_id is not None:
        records = [r for r in records if r["valuation_id"] == valuation_id]
    if negotiation_status is not None:
        records = [r for r in records if r["negotiation_status"] == negotiation_status]
    if federal_status is not None:
        records = [r for r in records if r["federal_approval_status"] == federal_status]
    return common.respond_list(common.created_asc(records), limit, offset)


@bp.get("/jda/agreements/<agreement_id>/disposition-requests")
def list_agreement_dispositions(agreement_id):
    _read_auth()
    limit, offset = shape.paging()
    store.require("agreement", agreement_id)
    records = common.dispositions_of(agreement_id)
    return common.respond_list(common.created_asc(records), limit, offset)


@bp.get("/jda/agreements/<agreement_id>/facility-replacements")
def list_agreement_replacements(agreement_id):
    _read_auth()
    limit, offset = shape.paging()
    status = shape.query_enum("status", enums.REPLACEMENT_STATUS)
    store.require("agreement", agreement_id)
    records = common.replacements_of(agreement_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return common.respond_list(common.created_asc(records), limit, offset)


@bp.get("/jda/agreements/<agreement_id>/maintenance-charges")
def list_agreement_charges(agreement_id):
    _read_auth()
    limit, offset = shape.paging()
    store.require("agreement", agreement_id)
    records = [c for c in store.all_of("maintenance_charge") if c["jda_id"] == agreement_id]
    return common.respond_list(common.created_asc(records), limit, offset)


# -------------------------------------------- dispositions, replacements, ops ---
@bp.get("/jda/disposition-requests/<request_id>")
def get_disposition(request_id):
    _read_auth()
    return envelope.ok(common.public(store.require("disposition_request", request_id)))


@bp.get("/jda/facility-replacements/<replacement_id>")
def get_replacement(replacement_id):
    _read_auth()
    return envelope.ok(common.public(store.require("facility_replacement", replacement_id)))


@bp.get("/jda/shared-facilities/<facility_id>")
def get_facility(facility_id):
    _read_auth()
    return envelope.ok(common.public(store.require("shared_facility", facility_id)))


@bp.get("/jda/shared-facilities/<facility_id>/maintenance-charges")
def list_facility_charges(facility_id):
    _read_auth()
    limit, offset = shape.paging()
    store.require("shared_facility", facility_id)
    records = [c for c in store.all_of("maintenance_charge")
               if c["shared_facility_id"] == facility_id]
    return common.respond_list(common.created_asc(records), limit, offset)


@bp.get("/jda/staging-windows/<window_id>")
def get_window(window_id):
    _read_auth()
    return envelope.ok(common.public(store.require("staging_window", window_id)))


@bp.get("/jda/staging-windows")
def list_windows():
    _read_auth()
    limit, offset = shape.paging()
    jda_id = shape.query_str("jda_id")
    facility_id = shape.query_str("shared_facility_id")
    status = shape.query_enum("status", enums.WINDOW_STATUS)
    records = store.all_of("staging_window")
    if jda_id is not None:
        records = [r for r in records if r["jda_id"] == jda_id]
    if facility_id is not None:
        records = [r for r in records if r["shared_facility_id"] == facility_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sorted(records, key=lambda r: (r["start_at"], r["created_at"], r["_seq"]))
    return common.respond_list(records, limit, offset)
