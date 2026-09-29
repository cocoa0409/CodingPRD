"""Federal grants, MOE assessment and the state match commitments."""

from flask import Blueprint

import auth
import db
import response
import util
from errors import fail
from services import calc
from services import constants as C
from services import core
from validators import (
    bad_amount,
    body_json,
    listing,
    peek_fk,
    query_enum,
    query_str,
    read_enum,
    read_id,
    read_instant,
    read_int,
    read_number,
    read_str,
)

bp = Blueprint("federal_grants", __name__)


@bp.post("/fiscal/federal-grants")
def create_grant():
    auth.authenticate((auth.BUDGET_ANALYST,))
    body = body_json()

    agency = peek_fk(body, "agency_id", core.get_agency)
    cycle = peek_fk(body, "budget_cycle_id", core.get_cycle)

    read_id(body, "agency_id")
    read_id(body, "budget_cycle_id")
    cfda_number = read_str(body, "cfda_number", min_len=1, max_len=16)
    award_cents = read_int(body, "award_cents")
    if award_cents <= 0:
        fail("ERR_INVALID_REQUEST", "award_cents must be greater than zero.")
    period_start = read_instant(body, "period_start")
    period_end = read_instant(body, "period_end")
    if period_end <= period_start:
        fail("ERR_INVALID_REQUEST", "period_end must be later than period_start.")
    moe_baseline_cents = read_int(body, "moe_baseline_cents")
    if moe_baseline_cents <= 0:
        fail("ERR_INVALID_REQUEST", "moe_baseline_cents must be greater than zero.")
    required_match_ratio = read_number(
        body, "required_match_ratio", required=False, default=0.25
    )
    if required_match_ratio < 0 or required_match_ratio > 3:
        fail("ERR_INVALID_REQUEST", "required_match_ratio must be between 0 and 3.")
    prior1 = read_int(body, "moe_prior_year1_spend_cents", required=False, default=0)
    prior2 = read_int(body, "moe_prior_year2_spend_cents", required=False, default=0)
    if prior1 < 0 or prior2 < 0:
        fail("ERR_INVALID_REQUEST", "MOE prior-year spend figures must be non-negative.")

    core.require_not_closed(cycle)

    row = db.new_row()
    row.update(
        {
            "agency_id": agency["id"],
            "budget_cycle_id": cycle["id"],
            "cfda_number": cfda_number,
            "award_cents": award_cents,
            "required_match_ratio": required_match_ratio,
            "period_start": body["period_start"],
            "period_end": body["period_end"],
            "required_state_match_cents": util.pct_of_cents(
                required_match_ratio, award_cents
            ),
            "committed_match_cents": 0,
            "match_status": "UNMET",
            "moe_baseline_cents": moe_baseline_cents,
            "moe_prior_year1_spend_cents": prior1,
            "moe_prior_year2_spend_cents": prior2,
            # PRD 3.8: at creation `committed_match_cents` and
            # `moe_current_spend_cents` are 0 -- charges posted before the grant
            # existed only reach the figure through an assessment or a later
            # posting/voiding cascade.
            "moe_current_spend_cents": 0,
            "moe_compliance_ratio": 0,
            "moe_assessed_basis": None,
            "moe_compliance_status": "NOT_ASSESSED",
            "_period_start": period_start,
            "_period_end": period_end,
        }
    )
    db.federal_grants[row["id"]] = row
    return response.created(db.serialize(row))


@bp.get("/fiscal/federal-grants/<grant_id>")
def read_grant(grant_id):
    auth.authenticate(auth.ANY_ROLE)
    row = core.get_grant(grant_id)
    return response.ok(db.serialize(row))


@bp.get("/fiscal/federal-grants")
def list_grants():
    auth.authenticate(auth.ANY_ROLE)
    agency_id = query_str("agency_id")
    cycle_id = query_str("budget_cycle_id")
    match_status = query_enum("match_status", C.MATCH_STATUSES)
    rows = []
    for row in db.federal_grants.values():
        if agency_id is not None and row["agency_id"] != agency_id:
            continue
        if cycle_id is not None and row["budget_cycle_id"] != cycle_id:
            continue
        if match_status is not None and row["match_status"] != match_status:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)


@bp.post("/fiscal/federal-grants/<grant_id>/moe-assessment")
def assess_moe(grant_id):
    auth.authenticate((auth.BUDGET_ANALYST,))
    row = core.get_grant(grant_id)
    body = body_json()
    basis = read_enum(body, "basis", C.MOE_BASES)

    cycle = core.get_cycle(row["budget_cycle_id"])
    core.require_not_closed(cycle)

    current_spend = core.moe_spend(row["agency_id"], row["budget_cycle_id"])
    result = calc.moe_assessment(row, basis, current_spend)
    changed = db.apply_changes(row, result)
    if not changed:
        db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/fiscal/match-commitments")
def create_commitment():
    actor = auth.authenticate((auth.AGENCY_BUDGET_OFFICER,))
    body = body_json()

    grant = peek_fk(body, "federal_grant_id", core.get_grant)
    appropriation = peek_fk(body, "appropriation_id", core.get_appropriation)
    if grant is not None:
        auth.require_agency_scope(actor, grant["agency_id"])
    if appropriation is not None:
        auth.require_agency_scope(actor, appropriation["agency_id"])

    read_id(body, "federal_grant_id")
    read_id(body, "appropriation_id")
    committed_match_cents = read_int(body, "committed_match_cents")
    if committed_match_cents <= 0:
        bad_amount("committed_match_cents must be greater than zero.")

    core.require_not_closed(core.get_cycle(appropriation["budget_cycle_id"]))

    if appropriation["authority_status"] != "ENACTED":
        fail("ERR_APPROPRIATION_NOT_ENACTED", "The appropriation is not ENACTED.")

    overlapping = core.overlapping_committed_total(appropriation["id"], grant)
    if overlapping + committed_match_cents > appropriation["available_authority_cents"]:
        fail(
            "ERR_MATCH_AGGREGATE_CAPACITY_EXCEEDED",
            "Overlapping pledges of %d plus %d exceed the available authority of %d."
            % (
                overlapping,
                committed_match_cents,
                appropriation["available_authority_cents"],
            ),
        )

    row = db.new_row()
    row.update(
        {
            "federal_grant_id": grant["id"],
            "appropriation_id": appropriation["id"],
            "committed_match_cents": committed_match_cents,
            "status": "COMMITTED",
        }
    )
    db.match_commitments[row["id"]] = row
    core.recompute_grants_and_agencies((grant["id"],))
    return response.created(db.serialize(row))


@bp.get("/fiscal/match-commitments/<commitment_id>")
def read_commitment(commitment_id):
    auth.authenticate(auth.ANY_ROLE)
    row = core.get_commitment(commitment_id)
    return response.ok(db.serialize(row))


@bp.get("/fiscal/match-commitments")
def list_commitments():
    auth.authenticate(auth.ANY_ROLE)
    grant_id = query_str("federal_grant_id")
    appropriation_id = query_str("appropriation_id")
    status = query_enum("status", C.COMMITMENT_STATUSES)
    rows = []
    for row in db.match_commitments.values():
        if grant_id is not None and row["federal_grant_id"] != grant_id:
            continue
        if appropriation_id is not None and row["appropriation_id"] != appropriation_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)
