"""CompensationDisclosure endpoints (PRD 3.7)."""

from flask import Blueprint

import calc
import clock
import db
import domain
import guards
import response

bp = Blueprint("disclosures", __name__)

READ_ROLES = ("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")


@bp.route("/compliance/compensation-disclosures", methods=["POST"])
def create_disclosure():
    guards.authorize("PlanSponsorAdmin", "ComplianceOfficer")
    body = guards.read_body()
    contract_id = guards.field(body, "contract_id", "string")
    direct = guards.field(body, "direct_comp_cents", "integer")
    indirect = guards.field(body, "indirect_comp_cents", "integer")
    benchmark = guards.field(body, "benchmark_median_cents", "integer")
    scope_score = guards.field(body, "services_scope_score", "integer")
    completeness = guards.field(body, "disclosure_completeness_score", "integer")
    contract = guards.fetch("contract", contract_id)
    plan_year = db.plan_year_of_contract(contract)
    guards.not_frozen(plan_year)
    # Ladder step 31 — only broker/consultant contracts carry a disclosure.
    guards.require(
        contract["compensation_disclosure_required"] is True,
        "ERR_DISCLOSURE_NOT_APPLICABLE",
        "Contract type %s does not require a compensation disclosure."
        % contract["contract_type"],
    )
    # Ladder step 32 — numeric domains of the scoring inputs.
    guards.require(
        benchmark >= 1
        and 1 <= scope_score <= 5
        and 1 <= completeness <= 5
        and direct >= 0
        and indirect >= 0,
        "ERR_INVALID_BENCHMARK",
        "benchmark_median_cents must be >= 1, the two scores must be in [1, 5] "
        "and the compensation amounts must be >= 0.",
    )
    record = db.common_fields()
    record.update({
        "contract_id": contract_id,
        "direct_comp_cents": direct,
        "indirect_comp_cents": indirect,
        "benchmark_median_cents": benchmark,
        "services_scope_score": scope_score,
        "disclosure_completeness_score": completeness,
        "status": "RECEIVED",
        "variant_applied": None,
        "component_price_score": None,
        "component_scope_score": None,
        "component_disclosure_score": None,
        "unreasonableness_score": None,
        "assessed_at": None,
        "assessed_by_user_id": None,
    })
    db.disclosures[record["id"]] = record
    return response.created_response(response.public(record))


@bp.route("/compliance/compensation-disclosures/<row_id>", methods=["GET"])
def get_disclosure(row_id):
    guards.authorize(*READ_ROLES)
    return response.object_response(
        response.public(guards.fetch("disclosure", row_id))
    )


@bp.route("/compliance/compensation-disclosures", methods=["GET"])
def list_disclosures():
    guards.authorize(*READ_ROLES)
    limit, offset = guards.pagination()
    guards.filter_fk("contract", "contract_id")
    rows = guards.apply_filters(db.ordered(db.disclosures), [
        ("contract_id", "contract_id", None),
        ("status", "status", None),
        ("variant_applied", "variant_applied", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route("/compliance/compensation-disclosures/<row_id>/assess", methods=["POST"])
def assess_disclosure(row_id):
    user_id, _role = guards.authorize("ComplianceOfficer")
    disclosure = guards.fetch("disclosure", row_id)
    body = guards.read_body()
    guards.field(body, "assessment_note", "string", required=False)
    contract = db.contracts.get(disclosure["contract_id"])
    plan_year = db.plan_year_of_disclosure(disclosure)
    guards.not_frozen(plan_year)
    guards.state_is(disclosure["status"], "RECEIVED")
    scored = calc.compensation_score(
        contract["contract_type"] if contract else "CONSULTANT", disclosure
    )
    with db.txn(disclosure):
        disclosure["variant_applied"] = scored["variant_applied"]
        disclosure["component_price_score"] = scored["component_price_score"]
        disclosure["component_scope_score"] = scored["component_scope_score"]
        disclosure["component_disclosure_score"] = scored["component_disclosure_score"]
        disclosure["unreasonableness_score"] = scored["unreasonableness_score"]
        disclosure["status"] = scored["status"]
        disclosure["assessed_at"] = clock.now_iso()
        disclosure["assessed_by_user_id"] = user_id
    # The REASONABLE branch touches no PlanYear field.
    if scored["status"] == "UNREASONABLE" and plan_year is not None:
        with db.txn(plan_year):
            domain.recompute_posture(plan_year)
    return response.object_response(response.public(disclosure))
