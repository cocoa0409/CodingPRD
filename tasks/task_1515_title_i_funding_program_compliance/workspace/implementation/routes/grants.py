"""DistrictGrant endpoints: lifecycle, rankings lock, finalization, close-out,
and the carryover-waiver dimension."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from services import calc, serializers, workflows

bp = Blueprint("grants", __name__)

FPD = {"FederalProgramsDirector"}
ALL_ROLES = middleware.ROLES

POVERTY_MEASURES = {"CENSUS_SAIPE", "FREE_REDUCED_LUNCH", "MEDICAID_DIRECT_CERT", "COMPOSITE"}
EQUITABLE_METHODS = {"CONSULTATION_AGREED", "VERIFIED_COUNT"}


def get_grant_or_404(grant_id):
    grant = db.grants.get(grant_id)
    if grant is None:
        errors.fail(errors.ERR_NOT_FOUND, "Grant %s does not exist." % grant_id)
    return grant


@bp.post("/grants")
def create_grant():
    _uid, role = middleware.current_user()
    middleware.require_role(role, FPD)
    data = V.json_body()
    # Tier 4: schema
    V.check_unknown(data, {
        "fiscal_year", "total_allocation_cents", "carryover_in_cents",
        "admin_reserve_cents", "poverty_measure", "equitable_count_method",
    })
    fiscal_year = V.req_int(data, "fiscal_year")
    total = V.req_int(data, "total_allocation_cents")
    carryover_in = V.opt_int(data, "carryover_in_cents", 0)
    admin_reserve = V.opt_int(data, "admin_reserve_cents", 0)
    measure = V.req_enum(data, "poverty_measure", POVERTY_MEASURES)
    method = V.opt_enum(data, "equitable_count_method", EQUITABLE_METHODS, "CONSULTATION_AGREED")
    if fiscal_year < 2020 or fiscal_year > 2100:
        errors.fail(errors.ERR_INVALID_REQUEST, "fiscal_year must be between 2020 and 2100.")
    if total <= 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "total_allocation_cents must be > 0.")
    if carryover_in < 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "carryover_in_cents must be >= 0.")
    if admin_reserve < 0 or admin_reserve > total + carryover_in:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "admin_reserve_cents must be >= 0 and <= total_allocation_cents + carryover_in_cents.",
        )
    # Tier 4.5: structural conflict
    for g in db.grants.values():
        if g["fiscal_year"] == fiscal_year:
            errors.fail(
                errors.ERR_DUPLICATE_FISCAL_YEAR,
                "A grant already exists for fiscal year %s." % fiscal_year,
            )
    grant = db.init_common({
        "fiscal_year": fiscal_year,
        "total_allocation_cents": total,
        "carryover_in_cents": carryover_in,
        "admin_reserve_cents": admin_reserve,
        "poverty_measure": measure,
        "equitable_count_method": method,
        "status": "SETUP",
        "carryover_waiver_status": "NONE",
        "carryover_waiver_justification": None,
        "carryover_waiver_decided_at": None,
        "net_allocable_cents": total + carryover_in - admin_reserve,
        "ranking_version": 0,
        "liquidated_cents": 0,
        "pending_cents": 0,
        "final_carryover_cents": None,
        "final_carryover_pct_bp": None,
        "monitoring_clearance": "NOT_MONITORED",
    })
    db.grants[grant["id"]] = grant
    return response.success_object(serializers.grant_view(grant), 201)


@bp.get("/grants")
def list_grants():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    fiscal_year = V.query_int("fiscal_year")
    status = V.query_filter("status")
    page, limit, offset, total = V.sorted_page(
        list(db.grants.values()),
        [("fiscal_year", fiscal_year), ("status", status)],
    )
    return response.success_list(
        [serializers.grant_view(g) for g in page], limit, offset, total
    )


@bp.get("/grants/<grant_id>")
def get_grant(grant_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(serializers.grant_view(get_grant_or_404(grant_id)))


@bp.post("/grants/<grant_id>/lock-rankings")
def lock_rankings(grant_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, FPD)
    grant = get_grant_or_404(grant_id)
    data = V.json_body()
    V.check_unknown(data, set())
    # Tier 5: state gates
    if grant["status"] != "SETUP":
        errors.fail(errors.ERR_GRANT_INVALID_STATE, "lock-rankings requires status SETUP.")
    certified = [
        s for s in workflows.grant_snapshots(grant["id"]) if s["status"] == "CERTIFIED"
    ]
    if not certified:
        errors.fail(
            errors.ERR_NO_CERTIFIED_SNAPSHOT,
            "lock-rankings requires a CERTIFIED poverty snapshot.",
        )
    workflows.create_allocations_from_snapshot(grant, certified[0])
    grant["status"] = "RANKING_LOCKED"
    grant["ranking_version"] += 1
    db.touch(grant)
    return response.success_object(serializers.grant_view(grant))


@bp.post("/grants/<grant_id>/finalize-allocations")
def finalize_allocations(grant_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, FPD)
    grant = get_grant_or_404(grant_id)
    data = V.json_body()
    V.check_unknown(data, {"serve_below_threshold_school_ids"})
    elected_ids = V.opt_array(data, "serve_below_threshold_school_ids", []) or []
    for sid in elected_ids:
        if not isinstance(sid, str):
            errors.fail(
                errors.ERR_INVALID_REQUEST,
                "serve_below_threshold_school_ids must contain school id strings.",
            )
    # Tier 3: elected ids are FK references to schools.
    for sid in elected_ids:
        if sid not in db.schools:
            errors.fail(errors.ERR_NOT_FOUND, "School %s does not exist." % sid)
    # Tier 5: state gate
    if grant["status"] != "RANKING_LOCKED":
        errors.fail(
            errors.ERR_GRANT_INVALID_STATE,
            "finalize-allocations requires status RANKING_LOCKED.",
        )
    # Tier 9: consultation completeness gate under CONSULTATION_AGREED.
    if grant["equitable_count_method"] == "CONSULTATION_AGREED":
        signed = {
            c["private_school_id"]
            for c in db.consultations.values()
            if c["grant_id"] == grant["id"] and c["status"] == "AFFIRMATION_SIGNED"
        }
        for ps in db.private_schools.values():
            if ps["nonprofit_verified"] and ps["id"] not in signed:
                errors.fail(
                    errors.ERR_CONSULTATION_INCOMPLETE,
                    "Verified private school %s lacks an AFFIRMATION_SIGNED consultation."
                    % ps["id"],
                )
    allocs = workflows.grant_allocations(grant["id"])
    by_school = {a["school_id"]: a for a in allocs}
    for sid in elected_ids:
        alloc = by_school.get(sid)
        if alloc is None:
            errors.fail(
                errors.ERR_NOT_FOUND,
                "School %s has no allocation in grant %s." % (sid, grant["id"]),
            )
        if alloc["eligibility_flag"] == "BELOW_THRESHOLD":
            alloc["serve_elected"] = True
    workflows.finalize_allocations(grant)
    grant["status"] = "ALLOCATED"
    db.touch(grant)
    return response.success_object(serializers.grant_view(grant))


@bp.post("/grants/<grant_id>/close-out")
def close_out(grant_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, FPD)
    grant = get_grant_or_404(grant_id)
    data = V.json_body()
    V.check_unknown(data, set())
    if grant["status"] != "ALLOCATED":
        errors.fail(errors.ERR_GRANT_INVALID_STATE, "close-out requires status ALLOCATED.")
    # Tier 8: open-findings block.
    visit_ids = {v["id"] for v in workflows.grant_visits(grant["id"])}
    if any(
        f["status"] in calc.NON_TERMINAL_FINDING_STATUSES
        for f in db.findings.values()
        if f["visit_id"] in visit_ids
    ):
        errors.fail(
            errors.ERR_OPEN_FINDINGS_BLOCK_CLOSEOUT,
            "Close-out blocked by non-terminal monitoring findings.",
        )
    # Tier 11: fiscal gates, in PRD 3.10 order.
    if any(
        e["status"] == "PENDING_REVIEW" for e in workflows.grant_expenditures(grant["id"])
    ):
        errors.fail(
            errors.ERR_UNRESOLVED_EXPENDITURES,
            "Close-out blocked by PENDING_REVIEW expenditures.",
        )
    if any(
        a["status"] in ("DRAFT", "SUBMITTED")
        for a in db.amendments.values()
        if a["grant_id"] == grant["id"]
    ):
        errors.fail(
            errors.ERR_UNRESOLVED_AMENDMENTS,
            "Close-out blocked by DRAFT/SUBMITTED amendments.",
        )
    final_cents, final_pct = calc.final_carryover(grant)
    if final_pct > calc.CARRYOVER_LIMIT_BP and grant["carryover_waiver_status"] != "GRANTED":
        errors.fail(
            errors.ERR_CARRYOVER_LIMIT_EXCEEDED,
            "Final carryover exceeds 1500 bp without a GRANTED waiver.",
        )
    grant["final_carryover_cents"] = final_cents
    grant["final_carryover_pct_bp"] = final_pct
    grant["status"] = "CLOSED_OUT"
    db.touch(grant)
    return response.success_object(serializers.grant_view(grant))


@bp.post("/grants/<grant_id>/request-carryover-waiver")
def request_carryover_waiver(grant_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, FPD)
    grant = get_grant_or_404(grant_id)
    data = V.json_body()
    V.check_unknown(data, {"justification"})
    justification = V.req_str(data, "justification")
    # Tier 5: state gates on both dimensions.
    if grant["status"] != "ALLOCATED":
        errors.fail(
            errors.ERR_GRANT_INVALID_STATE,
            "A waiver may only be requested while the grant is ALLOCATED.",
        )
    if grant["carryover_waiver_status"] not in ("NONE", "DENIED"):
        errors.fail(
            errors.ERR_WAIVER_INVALID_STATE,
            "carryover_waiver_status must be NONE or DENIED to request a waiver.",
        )
    # Tier 11: fiscal waiver conditions.
    _cents, prov_pct = calc.provisional_carryover(grant)
    if prov_pct <= calc.CARRYOVER_LIMIT_BP:
        errors.fail(
            errors.ERR_CARRYOVER_WITHIN_LIMIT,
            "Provisional carryover is within the 15% limit; nothing to waive.",
        )
    fy = grant["fiscal_year"]
    for other in db.grants.values():
        if (
            other["id"] != grant["id"]
            and other["carryover_waiver_status"] == "GRANTED"
            and other["fiscal_year"] in (fy - 3, fy - 2, fy - 1)
        ):
            errors.fail(
                errors.ERR_CARRYOVER_WAIVER_WITHIN_3_YEARS,
                "A GRANTED waiver exists in one of the three prior fiscal years.",
            )
    grant["carryover_waiver_status"] = "REQUESTED"
    grant["carryover_waiver_justification"] = justification
    grant["carryover_waiver_decided_at"] = None
    db.touch(grant)
    return response.success_object(serializers.grant_view(grant))


@bp.post("/grants/<grant_id>/decide-carryover-waiver")
def decide_carryover_waiver(grant_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"SEAMonitor"})
    grant = get_grant_or_404(grant_id)
    data = V.json_body()
    V.check_unknown(data, {"decision", "decision_note"})
    decision = V.req_enum(data, "decision", {"GRANT", "DENY"})
    V.opt_str(data, "decision_note")
    if grant["carryover_waiver_status"] != "REQUESTED":
        errors.fail(
            errors.ERR_WAIVER_INVALID_STATE,
            "Only a REQUESTED waiver may be decided.",
        )
    grant["carryover_waiver_status"] = "GRANTED" if decision == "GRANT" else "DENIED"
    grant["carryover_waiver_decided_at"] = db.now_ts()
    db.touch(grant)
    return response.success_object(serializers.grant_view(grant))
