"""Agreement formation, contract lifecycle, advances, true-up and territory grants."""

import re
from datetime import timedelta

from flask import Blueprint

import constants as K
import db
import middleware as mw
import response
import serializers
import validate as V
from db import S, apply_changes, touch
from errors import ApiError
from middleware import (ROLE_AUDITOR, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_LICENSEE,
                        ROLE_MANAGER, guard, paginate, pagination)
from services import calc, domain

bp = Blueprint("agreements", __name__)

TERRITORY_RE = re.compile(r"^[A-Z]{2,6}$")

READ_ROLES = [ROLE_MANAGER, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR, ROLE_LICENSEE]


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


def find_agreement(agreement_id):
    row = S.agreements.get(agreement_id)
    if row is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    return row


def _find_grant(grant_id):
    row = S.grants.get(grant_id)
    if row is None:
        raise ApiError("ERR_GRANT_NOT_FOUND")
    return row


def advance_floor_cents(category, minimum_guarantee_cents):
    return calc.apply_rate_floor(minimum_guarantee_cents, category["advance_floor_bps_of_mg"])


def _check_commercial_terms(category, exclusivity_mode, mg_cents, advance_cents):
    if exclusivity_mode != "NON_EXCLUSIVE" and not category["exclusivity_allowed"]:
        raise ApiError("ERR_EXCLUSIVITY_NOT_PERMITTED")
    if mg_cents < category["minimum_guarantee_floor_cents"]:
        raise ApiError("ERR_MG_BELOW_FLOOR")
    if advance_cents < advance_floor_cents(category, mg_cents):
        raise ApiError("ERR_ADVANCE_BELOW_FLOOR")


# --------------------------------------------------------------------------- #
# creation, reads and amendment                                               #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/agreements")
def create_agreement():
    ctx = guard([ROLE_MANAGER])
    body = ctx.body

    licensee_id = body.get("licensee_id")
    if licensee_id is not None and licensee_id not in S.licensees:
        raise ApiError("ERR_LICENSEE_NOT_FOUND")
    category_id = body.get("category_id")
    if category_id is not None and category_id not in S.categories:
        raise ApiError("ERR_CATEGORY_NOT_FOUND")

    licensee_id = V.req_string(body, "licensee_id")
    category_id = V.req_string(body, "category_id")
    exclusivity_mode = V.req_enum(body, "exclusivity_mode", K.EXCLUSIVITY_MODES)
    mg_cents = V.req_cents(body, "minimum_guarantee_cents")
    advance_cents = V.req_cents(body, "required_advance_cents")
    term_start = V.req_date(body, "term_start_date")
    term_end = V.req_date(body, "term_end_date")
    central = V.opt_bool(body, "central_licensing_flag")

    if term_end <= term_start:
        _bad("term_end_date must be strictly later than term_start_date.")
    start_quarter = db.quarter_of_date(term_start)
    end_quarter = db.quarter_of_date(term_end)
    span = db.elapsed_quarters(start_quarter, end_quarter) + 1
    if span < 1 or span > 20:
        _bad("The term must span between 1 and 20 whole quarters.")

    licensee = S.licensees[licensee_id]
    category = S.categories[category_id]
    if licensee["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSEE_NOT_ACTIVE")
    _check_commercial_terms(category, exclusivity_mode, mg_cents, advance_cents)

    requested_from = term_start
    requested_to = term_end + timedelta(days=1)
    for other in domain.agreements_of(licensee_id):
        if other["category_id"] != category_id:
            continue
        if other["contract_status"] in ("EXPIRED", "TERMINATED"):
            continue
        other_from = db.parse_date(other["term_start_date"])
        other_to = db.parse_date(other["term_end_date"]) + timedelta(days=1)
        if requested_from < other_to and other_from < requested_to:
            raise ApiError("ERR_DUPLICATE_AGREEMENT")

    if central is None:
        central = category["central_licensing_default"]

    row = db.base_row()
    row.update({
        "licensee_id": licensee_id,
        "category_id": category_id,
        "exclusivity_mode": exclusivity_mode,
        "minimum_guarantee_cents": mg_cents,
        "required_advance_cents": advance_cents,
        "advance_paid_cents": 0,
        "unrecouped_advance_cents": 0,
        "recouped_advance_cents": 0,
        "term_start_date": body["term_start_date"],
        "term_end_date": body["term_end_date"],
        "central_licensing_flag": central,
        "contract_status": "DRAFT",
        "compliance_posture": "CLEAR",
        "posture_as_of_quarter": None,
        "cumulative_royalty_cents": 0,
        "contract_year_start_quarter": start_quarter,
        "mg_accrued_shortfall_cents": 0,
        "mg_final_shortfall_cents": None,
        "approved_sku_count": 0,
        "authorized_channel_count": 0,
        "distribution_ready": False,
        "countersigned_by": None,
        "suspension_reason": None,
        "termination_reason": None,
    })
    S.agreements[row["id"]] = row
    domain.refresh_agreement_count(licensee)
    return response.created(serializers.dump("LicenseAgreement", row))


@bp.get("/licensing/agreements")
def list_agreements():
    ctx = guard(READ_ROLES)
    limit, offset = pagination()
    licensee_id = mw.filter_str("licensee_id")
    category_id = mw.filter_str("category_id")
    contract_status = mw.filter_enum("contract_status", K.CONTRACT_STATUSES)
    posture = mw.filter_enum("compliance_posture", K.POSTURES)
    central = mw.filter_bool("central_licensing_flag")

    rows = list(S.agreements.values())
    if ctx.role == ROLE_LICENSEE:
        rows = [r for r in rows if r["licensee_id"] == ctx.uid]
    if licensee_id is not None:
        rows = [r for r in rows if r["licensee_id"] == licensee_id]
    if category_id is not None:
        rows = [r for r in rows if r["category_id"] == category_id]
    if contract_status is not None:
        rows = [r for r in rows if r["contract_status"] == contract_status]
    if posture is not None:
        rows = [r for r in rows if r["compliance_posture"] == posture]
    if central is not None:
        rows = [r for r in rows if r["central_licensing_flag"] == central]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("LicenseAgreement", page),
                            limit, offset, total)


@bp.get("/licensing/agreements/<agreement_id>")
def get_agreement(agreement_id):
    ctx = guard(READ_ROLES)
    agreement = find_agreement(agreement_id)
    mw.scope_agreement(ctx, agreement)
    return response.ok(serializers.dump("LicenseAgreement", agreement))


@bp.patch("/licensing/agreements/<agreement_id>")
def patch_agreement(agreement_id):
    ctx = guard([ROLE_MANAGER])
    agreement = find_agreement(agreement_id)
    body = ctx.body

    changes = {}
    if V.present(body, "exclusivity_mode"):
        changes["exclusivity_mode"] = V.req_enum(body, "exclusivity_mode",
                                                 K.EXCLUSIVITY_MODES)
    if V.present(body, "minimum_guarantee_cents"):
        changes["minimum_guarantee_cents"] = V.req_cents(body, "minimum_guarantee_cents")
    if V.present(body, "required_advance_cents"):
        changes["required_advance_cents"] = V.req_cents(body, "required_advance_cents")
    if V.present(body, "term_end_date"):
        V.req_date(body, "term_end_date")
        changes["term_end_date"] = body["term_end_date"]
    if V.present(body, "central_licensing_flag"):
        changes["central_licensing_flag"] = V.req_bool(body, "central_licensing_flag")

    if agreement["contract_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    category = domain.category_of(agreement)
    _check_commercial_terms(
        category,
        changes.get("exclusivity_mode", agreement["exclusivity_mode"]),
        changes.get("minimum_guarantee_cents", agreement["minimum_guarantee_cents"]),
        changes.get("required_advance_cents", agreement["required_advance_cents"]),
    )

    agreement.update(changes)
    touch(agreement)
    return response.ok(serializers.dump("LicenseAgreement", agreement))


# --------------------------------------------------------------------------- #
# contract dimension                                                          #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/agreements/<agreement_id>/contract-status")
def contract_status(agreement_id):
    ctx = guard([ROLE_MANAGER, ROLE_COMPLIANCE])
    agreement = find_agreement(agreement_id)
    body = ctx.body
    action = V.req_enum(body, "action", ("SUBMIT_FOR_SIGNATURE", "ACTIVATE", "SUSPEND",
                                        "REINSTATE", "TERMINATE"))
    reason = V.opt_string(body, "reason")
    licensee = domain.licensee_of(agreement)
    category = domain.category_of(agreement)
    status = agreement["contract_status"]

    if action == "SUBMIT_FOR_SIGNATURE":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        if agreement["minimum_guarantee_cents"] < category["minimum_guarantee_floor_cents"]:
            raise ApiError("ERR_MG_BELOW_FLOOR")
        if agreement["advance_paid_cents"] < agreement["required_advance_cents"]:
            raise ApiError("ERR_INVALID_STATE",
                           "The contracted advance has not been fully paid.")
        if not any(g["status"] == "GRANTED" for g in domain.grants_of(agreement_id)):
            raise ApiError("ERR_INVALID_STATE",
                           "At least one granted territory grant is required.")
        agreement["contract_status"] = "PENDING_SIGNATURE"
        touch(agreement)

    elif action == "ACTIVATE":
        countersigned_by = V.req_string(body, "countersigned_by", 1)
        if status != "PENDING_SIGNATURE":
            raise ApiError("ERR_INVALID_STATE")
        if licensee["status"] != "ACTIVE":
            raise ApiError("ERR_LICENSEE_NOT_ACTIVE")
        agreement["contract_status"] = "ACTIVE"
        agreement["countersigned_by"] = countersigned_by
        touch(agreement)
        domain.refresh_agreement_count(licensee)

    elif action == "SUSPEND":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        agreement["contract_status"] = "SUSPENDED"
        agreement["suspension_reason"] = reason
        touch(agreement)
        for sub in domain.submissions_of(agreement_id):
            if sub["status"] in domain.HELD_SUBMISSION_STATES and not sub["review_hold"]:
                sub["review_hold"] = True
                touch(sub)
        domain.refresh_distribution_ready(agreement)

    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        if licensee["status"] != "ACTIVE":
            raise ApiError("ERR_LICENSEE_NOT_ACTIVE")
        agreement["contract_status"] = "ACTIVE"
        agreement["suspension_reason"] = None
        touch(agreement)
        hold = agreement["compliance_posture"] in ("PROBATION", "FROZEN")
        for sub in domain.submissions_of(agreement_id):
            if sub["review_hold"] != hold:
                sub["review_hold"] = hold
                touch(sub)
        domain.refresh_distribution_ready(agreement)

    else:
        if status not in ("DRAFT", "PENDING_SIGNATURE", "ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        agreement["contract_status"] = "TERMINATED"
        agreement["termination_reason"] = reason
        agreement["mg_final_shortfall_cents"] = domain.assess_final_shortfall(agreement)
        touch(agreement)
        for grant in domain.grants_of(agreement_id):
            if grant["status"] == "GRANTED":
                grant["status"] = "REVOKED"
                touch(grant)
        if status in ("ACTIVE", "SUSPENDED"):
            for sub in domain.submissions_of(agreement_id):
                if sub["status"] == "APPROVED":
                    domain.revoke_submission(sub, "COMPLIANCE_ORDER")
            domain.refresh_distribution_ready(agreement)
        domain.refresh_agreement_count(licensee)

    return response.ok(serializers.dump("LicenseAgreement", agreement))


@bp.post("/licensing/agreements/<agreement_id>/advance-payments")
def advance_payment(agreement_id):
    ctx = guard([ROLE_FINANCE, ROLE_LICENSEE])
    agreement = find_agreement(agreement_id)
    mw.scope_agreement(ctx, agreement)
    amount = V.req_cents(ctx.body, "amount_cents")

    if agreement["advance_paid_cents"] + amount > agreement["required_advance_cents"]:
        raise ApiError("ERR_ADVANCE_OVERPAYMENT")

    agreement["advance_paid_cents"] += amount
    agreement["unrecouped_advance_cents"] += amount
    touch(agreement)
    return response.ok(serializers.dump("LicenseAgreement", agreement))


@bp.post("/licensing/agreements/<agreement_id>/annual-true-up")
def annual_true_up(agreement_id):
    ctx = guard([ROLE_FINANCE, ROLE_AUDITOR])
    agreement = find_agreement(agreement_id)
    contract_year = V.req_int(ctx.body, "contract_year")
    if contract_year < 1:
        _bad("contract_year must be at least 1.")

    category = domain.category_of(agreement)
    first = db.quarter_shift(agreement["contract_year_start_quarter"],
                            4 * (contract_year - 1))
    quarters = [db.quarter_shift(first, offset) for offset in range(4)]

    included = [r for r in domain.reports_of(agreement_id)
                if r["period_quarter"] in quarters
                and r["status"] in ("ACCEPTED", "ADJUSTED", "CLOSED")]
    included.sort(key=lambda r: r["period_quarter"])

    cumulative = sum(r["net_regular_total_cents"] for r in included)
    marginal = calc.marginal_tier_total(category, cumulative)

    closeout_part = 0
    provisional = 0
    for report in included:
        for line in calc.ordered_lines(report["channel_lines"]):
            eligible = calc.closeout_eligible_for(line, category)
            closeout_part += calc.apply_rate_half_up(eligible, category["closeout_rate_bps"])
        adjusted = report.get("adjusted_royalty_due_cents")
        provisional += adjusted if adjusted is not None else report["royalty_due_cents"]

    true_up = marginal + closeout_part
    return response.ok({
        "agreement_id": agreement_id,
        "contract_year": contract_year,
        "included_report_count": len(included),
        "cumulative_net_regular_cents": cumulative,
        "true_up_royalty_cents": true_up,
        "provisional_total_cents": provisional,
        "delta_cents": true_up - provisional,
    })


# --------------------------------------------------------------------------- #
# territory grants                                                            #
# --------------------------------------------------------------------------- #

def _channels_intersect(left, right):
    if left == "ALL" or right == "ALL":
        return True
    return left == right


def _check_exclusivity(agreement, grant_id, territory_code, channel_class,
                       effective_from, effective_to, exclusivity_mode):
    if exclusivity_mode != "EXCLUSIVE":
        return
    for other in S.grants.values():
        if other["id"] == grant_id:
            continue
        if other["status"] != "GRANTED":
            continue
        if other["agreement_id"] == agreement["id"]:
            continue
        other_agreement = S.agreements.get(other["agreement_id"])
        if other_agreement is None or other_agreement["category_id"] != agreement["category_id"]:
            continue
        if other["territory_code"] != territory_code:
            continue
        if not _channels_intersect(channel_class, other["channel_class"]):
            continue
        other_from = db.parse_date(other["effective_from"])
        other_to = db.parse_date(other["effective_to"])
        if effective_from < other_to and other_from < effective_to:
            raise ApiError("ERR_TERRITORY_EXCLUSIVITY_CONFLICT")


@bp.post("/licensing/agreements/<agreement_id>/territory-grants")
def create_grant(agreement_id):
    ctx = guard([ROLE_MANAGER])
    agreement = find_agreement(agreement_id)
    body = ctx.body

    territory_code = V.req_string(body, "territory_code", 2, 6)
    if not TERRITORY_RE.match(territory_code):
        _bad("territory_code must be two to six uppercase letters.")
    channel_class = V.req_enum(body, "channel_class", K.GRANT_CHANNEL_CLASSES)
    effective_from = V.req_date(body, "effective_from")
    effective_to = V.req_date(body, "effective_to")

    if agreement["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_POSTURE_FROZEN")

    _check_exclusivity(agreement, None, territory_code, channel_class,
                       effective_from, effective_to, agreement["exclusivity_mode"])

    term_start = db.parse_date(agreement["term_start_date"])
    term_end = db.parse_date(agreement["term_end_date"])
    if effective_from >= effective_to:
        raise ApiError("ERR_GRANT_WINDOW_INVALID")
    if db.elapsed_quarters(db.quarter_of_date(term_start),
                          db.quarter_of_date(effective_from)) < 0:
        raise ApiError("ERR_GRANT_WINDOW_INVALID")
    if effective_to > term_end + timedelta(days=1):
        raise ApiError("ERR_GRANT_WINDOW_INVALID")

    row = db.base_row()
    row.update({
        "agreement_id": agreement_id,
        "territory_code": territory_code,
        "channel_class": channel_class,
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "status": "GRANTED",
        "exclusivity_mode_snapshot": agreement["exclusivity_mode"],
    })
    S.grants[row["id"]] = row
    return response.created(serializers.dump("TerritoryGrant", row))


@bp.get("/licensing/territory-grants")
def list_grants():
    ctx = guard(READ_ROLES)
    limit, offset = pagination()
    agreement_id = mw.filter_str("agreement_id")
    territory_code = mw.filter_str("territory_code")
    channel_class = mw.filter_enum("channel_class", K.GRANT_CHANNEL_CLASSES)
    status = mw.filter_enum("status", K.GRANT_STATUSES)

    rows = list(S.grants.values())
    if ctx.role == ROLE_LICENSEE:
        own = {a["id"] for a in domain.agreements_of(ctx.uid)}
        rows = [r for r in rows if r["agreement_id"] in own]
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if territory_code is not None:
        rows = [r for r in rows if r["territory_code"] == territory_code]
    if channel_class is not None:
        rows = [r for r in rows if r["channel_class"] == channel_class]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("TerritoryGrant", page),
                            limit, offset, total)


@bp.get("/licensing/territory-grants/<grant_id>")
def get_grant(grant_id):
    ctx = guard(READ_ROLES)
    grant = _find_grant(grant_id)
    mw.scope_agreement(ctx, S.agreements[grant["agreement_id"]])
    return response.ok(serializers.dump("TerritoryGrant", grant))


@bp.post("/licensing/territory-grants/<grant_id>/status")
def grant_status(grant_id):
    ctx = guard([ROLE_MANAGER])
    grant = _find_grant(grant_id)
    action = V.req_enum(ctx.body, "action", ("REVOKE", "REINSTATE"))
    V.opt_string(ctx.body, "reason")

    if action == "REVOKE":
        if grant["status"] != "GRANTED":
            raise ApiError("ERR_INVALID_STATE")
        grant["status"] = "REVOKED"
        touch(grant)
    else:
        if grant["status"] != "REVOKED":
            raise ApiError("ERR_INVALID_STATE")
        agreement = S.agreements[grant["agreement_id"]]
        _check_exclusivity(agreement, grant["id"], grant["territory_code"],
                           grant["channel_class"],
                           db.parse_date(grant["effective_from"]),
                           db.parse_date(grant["effective_to"]),
                           grant["exclusivity_mode_snapshot"])
        grant["status"] = "GRANTED"
        touch(grant)
    return response.ok(serializers.dump("TerritoryGrant", grant))
