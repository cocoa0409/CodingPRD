"""Every read endpoint.  All six roles may call all of them (PRD 2.1)."""

from flask import Blueprint

import constants as K
import derive
import serialize
import shape
import store
from authz import require
from routes import common

bp = Blueprint("reads", __name__)


@bp.get("/sites")
def list_sites():
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    listing_status = shape.enum_filter("listing_status", K.LISTING_STATUSES)
    epa_region = shape.int_filter("epa_region")
    cost_posture = shape.enum_filter("cost_posture", K.COST_POSTURES)
    rows = list(store.sites.values())
    if listing_status is not None:
        rows = [r for r in rows if r["listing_status"] == listing_status]
    if epa_region is not None:
        rows = [r for r in rows if r["epa_region"] == epa_region]
    if cost_posture is not None:
        rows = [r for r in rows if r["cost_posture"] == cost_posture]
    # created_at DESCENDING, then name ASCENDING as the tie-break (PRD 2.3).
    rows.sort(key=lambda r: (r["name"], -r["seq"]))
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return common.paged(rows, serialize.site, limit, offset)


@bp.get("/sites/<site_id>")
def read_site(site_id):
    require(*K.ALL_ROLES)
    site = common.get_site(site_id)
    return common.respond_raw(serialize.site(site))


@bp.get("/sites/<site_id>/cost-ledger")
def read_cost_ledger(site_id):
    require(*K.ALL_ROLES)
    site = common.get_site(site_id)
    view = derive.cost_ledger_view(site)
    from numeric import as_json_number

    payload = {}
    for key, value in view.items():
        if key.endswith("_pct"):
            payload[key] = as_json_number(value)
        else:
            payload[key] = value
    return common.respond_raw(payload)


@bp.get("/sites/<site_id>/prps")
def list_site_prps(site_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    status = shape.enum_filter("status", K.PRP_STATUSES)
    site = common.get_site(site_id)
    rows = derive.site_prps(site["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.paged(rows, serialize.prp, limit, offset)


@bp.get("/sites/<site_id>/ownership-periods")
def list_site_periods(site_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    site = common.get_site(site_id)
    rows = derive.site_periods(site["id"])
    rows.sort(key=lambda r: (r["start_date"], r["seq"]))
    return common.paged(rows, serialize.ownership_period, limit, offset)


@bp.get("/sites/<site_id>/waste-in-records")
def list_site_waste(site_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    status = shape.enum_filter("status", K.WASTE_STATUSES)
    site = common.get_site(site_id)
    rows = derive.site_waste(site["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.paged(rows, serialize.waste_in_record, limit, offset)


@bp.get("/sites/<site_id>/remedial-investigations")
def list_site_ris(site_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    status = shape.enum_filter("status", K.RI_STATUSES)
    site = common.get_site(site_id)
    rows = derive.site_investigations(site["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.paged(rows, serialize.remedial_investigation, limit, offset)


@bp.get("/sites/<site_id>/records-of-decision")
def list_site_rods(site_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    status = shape.enum_filter("status", K.ROD_STATUSES)
    site = common.get_site(site_id)
    rows = derive.site_rods(site["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.paged(rows, serialize.record_of_decision, limit, offset)


@bp.get("/sites/<site_id>/allocation-rounds")
def list_site_rounds(site_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    status = shape.enum_filter("status", K.ROUND_STATUSES)
    site = common.get_site(site_id)
    rows = derive.site_rounds(site["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.paged(rows, serialize.allocation_round, limit, offset)


@bp.get("/sites/<site_id>/consent-decrees")
def list_site_decrees(site_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    legal_status = shape.enum_filter("legal_status", K.LEGAL_STATUSES)
    site = common.get_site(site_id)
    rows = derive.site_decrees(site["id"])
    if legal_status is not None:
        rows = [r for r in rows if r["legal_status"] == legal_status]
    return common.paged(rows, serialize.consent_decree, limit, offset)


@bp.get("/sites/<site_id>/remediation-contracts")
def list_site_contracts(site_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    status = shape.enum_filter("status", K.CONTRACT_STATUSES)
    site = common.get_site(site_id)
    rows = derive.site_contracts(site["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.paged(rows, serialize.remediation_contract, limit, offset)


@bp.get("/prps/<prp_id>")
def read_prp(prp_id):
    require(*K.ALL_ROLES)
    prp = common.get_prp(prp_id)
    return common.respond_raw(serialize.prp(prp))


@bp.get("/prps/<prp_id>/ownership-periods")
def list_prp_periods(prp_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    prp = common.get_prp(prp_id)
    rows = derive.prp_periods(prp["id"])
    return common.paged(rows, serialize.ownership_period, limit, offset)


@bp.get("/prps/<prp_id>/waste-in-records")
def list_prp_waste(prp_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    status = shape.enum_filter("status", K.WASTE_STATUSES)
    prp = common.get_prp(prp_id)
    rows = derive.prp_waste(prp["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.paged(rows, serialize.waste_in_record, limit, offset)


@bp.get("/prps/<prp_id>/allocation-shares")
def list_prp_shares(prp_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    disposition = shape.enum_filter("disposition", K.DISPOSITIONS)
    prp = common.get_prp(prp_id)
    rows = derive.prp_shares(prp["id"])
    if disposition is not None:
        rows = [r for r in rows if r["disposition"] == disposition]
    return common.paged(rows, serialize.allocation_share, limit, offset)


@bp.get("/waste-in-records/<waste_id>")
def read_waste(waste_id):
    require(*K.ALL_ROLES)
    record = common.get_waste(waste_id)
    return common.respond_raw(serialize.waste_in_record(record))


@bp.get("/remedial-investigations/<ri_id>")
def read_ri(ri_id):
    require(*K.ALL_ROLES)
    ri = common.get_ri(ri_id)
    return common.respond_raw(serialize.remedial_investigation(ri))


@bp.get("/remedial-investigations/<ri_id>/samples")
def list_samples(ri_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    qa_status = shape.enum_filter("qa_status", K.QA_STATUSES)
    medium = shape.enum_filter("medium", K.EXPOSURE_MEDIA)
    ri = common.get_ri(ri_id)
    rows = derive.ri_samples(ri["id"])
    if qa_status is not None:
        rows = [r for r in rows if r["qa_status"] == qa_status]
    if medium is not None:
        rows = [r for r in rows if r["medium"] == medium]
    rows.sort(key=lambda r: (r["collected_at"], r["seq"]))
    return common.paged(rows, serialize.contaminant_sample, limit, offset)


@bp.get("/remedial-investigations/<ri_id>/remedy-alternatives")
def list_alternatives(ri_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    ri = common.get_ri(ri_id)
    rows = derive.ri_alternatives(ri["id"])
    return common.paged(rows, serialize.remedy_alternative, limit, offset)


@bp.get("/remedial-investigations/<ri_id>/records-of-decision")
def list_ri_rods(ri_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    ri = common.get_ri(ri_id)
    rows = derive._by_created(
        [
            r
            for r in store.records_of_decision.values()
            if r["remedial_investigation_id"] == ri["id"]
        ]
    )
    return common.paged(rows, serialize.record_of_decision, limit, offset)


@bp.get("/records-of-decision/<rod_id>")
def read_rod(rod_id):
    require(*K.ALL_ROLES)
    rod = common.get_rod(rod_id)
    return common.respond_raw(serialize.record_of_decision(rod))


@bp.get("/records-of-decision/<rod_id>/selected-remedy")
def read_selected_remedy(rod_id):
    """A zero-or-one element array: an unsigned document reports an empty array
    rather than an error."""
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    rod = common.get_rod(rod_id)
    rows = []
    if rod["selected_alternative_id"]:
        alternative = store.remedy_alternatives.get(rod["selected_alternative_id"])
        if alternative is not None:
            rows.append(alternative)
    return common.paged(rows, serialize.remedy_alternative, limit, offset)


@bp.get("/records-of-decision/<rod_id>/remediation-contracts")
def list_rod_contracts(rod_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    rod = common.get_rod(rod_id)
    rows = derive._by_created(
        [
            c
            for c in store.remediation_contracts.values()
            if c["record_of_decision_id"] == rod["id"]
        ]
    )
    return common.paged(rows, serialize.remediation_contract, limit, offset)


@bp.get("/allocation-rounds/<round_id>")
def read_round(round_id):
    require(*K.ALL_ROLES)
    round_ = common.get_round(round_id)
    return common.respond_raw(serialize.allocation_round(round_))


@bp.get("/allocation-rounds/<round_id>/shares")
def list_round_shares(round_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    disposition = shape.enum_filter("disposition", K.DISPOSITIONS)
    round_ = common.get_round(round_id)
    rows = derive.round_shares(round_["id"])
    if disposition is not None:
        rows = [r for r in rows if r["disposition"] == disposition]
    return common.paged(rows, serialize.allocation_share, limit, offset)


@bp.get("/consent-decrees/<decree_id>")
def read_decree(decree_id):
    require(*K.ALL_ROLES)
    decree = common.get_decree(decree_id)
    return common.respond_raw(serialize.consent_decree(decree))


@bp.get("/remediation-contracts/<contract_id>")
def read_contract(contract_id):
    require(*K.ALL_ROLES)
    contract = common.get_contract(contract_id)
    return common.respond_raw(serialize.remediation_contract(contract))


@bp.get("/remediation-contracts/<contract_id>/work-windows")
def list_windows(contract_id):
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    activity_type = shape.enum_filter("activity_type", K.ACTIVITY_TYPES)
    contract = common.get_contract(contract_id)
    rows = derive.contract_windows(contract["id"])
    if activity_type is not None:
        rows = [r for r in rows if r["activity_type"] == activity_type]
    rows.sort(key=lambda r: (r["start_at"], r["seq"]))
    return common.paged(rows, serialize.work_window, limit, offset)


@bp.get("/cost-recovery-actions")
def list_actions():
    """The one place where three foreign keys collapse into a single channel."""
    require(*K.ALL_ROLES)
    limit, offset = shape.pagination()
    site_id = shape.str_filter("site_id")
    respondent = shape.str_filter("respondent_prp_id")
    claimant = shape.str_filter("claimant_prp_id")
    action_type = shape.enum_filter("action_type", K.ACTION_TYPES)
    status = shape.enum_filter("status", K.ACTION_STATUSES)
    rows = derive._by_created(list(store.cost_recovery_actions.values()))
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if respondent is not None:
        rows = [r for r in rows if r["respondent_prp_id"] == respondent]
    if claimant is not None:
        rows = [r for r in rows if r["claimant_prp_id"] == claimant]
    if action_type is not None:
        rows = [r for r in rows if r["action_type"] == action_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.paged(rows, serialize.cost_recovery_action, limit, offset)


@bp.get("/cost-recovery-actions/<action_id>")
def read_action(action_id):
    require(*K.ALL_ROLES)
    action = common.get_action(action_id)
    return common.respond_raw(serialize.cost_recovery_action(action))
