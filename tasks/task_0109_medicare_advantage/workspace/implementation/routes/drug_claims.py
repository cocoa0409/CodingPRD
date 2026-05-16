"""Drug claim and ledger endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from flask import Blueprint, g, request

from auth import require_roles
from errors import err
from response import ok_object
from serializers import serialize_drug_claim, serialize_drug_phase_ledger
from services.donut_hole import phase_walk, replay_chronological
from store import store
from utils import (
    check_version,
    iso_string,
    parse_iso_datetime,
    require_enum,
    require_field,
    require_int,
    stamp_create,
    stamp_update,
)

bp = Blueprint("drug_claims", __name__)

TIERS = {"TIER_1", "TIER_2", "TIER_3", "TIER_4", "TIER_5"}


def _find_ledger_for_enrollment(eid: str) -> dict | None:
    for l in store.drug_phase_ledgers.values():
        if l["enrollment_id"] == eid:
            return l
    return None


@bp.route("/drug-claims", methods=["POST"])
@require_roles("BenefitsCounselor")
def submit_claim():
    body = request.get_json(silent=True) or {}
    bid = require_field(body, "beneficiary_id")
    eid = require_field(body, "enrollment_id")
    ndc = require_field(body, "ndc_code")
    tier = require_enum(require_field(body, "tier"), field="tier", allowed=TIERS)
    fill_dt = parse_iso_datetime(require_field(body, "fill_date"), field="fill_date")
    gross = require_int(require_field(body, "gross_cost_cents"), field="gross_cost_cents", minimum=1)

    beneficiary = store.beneficiaries.get(bid)
    enrollment = store.enrollments.get(eid)
    if beneficiary is None or enrollment is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced beneficiary or enrollment not found")
    if enrollment["beneficiary_id"] != bid:
        raise err("ERR_FK_NOT_FOUND", "Enrollment does not belong to beneficiary")
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")
    if enrollment["part_covered"] != "PART_D":
        raise err("ERR_NON_PART_D_CLAIM", "Claim must reference a Part D enrollment")

    plan = store.plans[enrollment["plan_id"]]
    end_of_year = datetime(plan["plan_year"], 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    coverage_end = enrollment["_termination_dt"] if enrollment["_termination_dt"] else end_of_year
    if fill_dt < enrollment["_effective_dt"] or fill_dt > coverage_end:
        raise err("ERR_FILL_DATE_OUT_OF_COVERAGE", "fill_date outside coverage window")

    if not isinstance(ndc, str) or not ndc:
        raise err("ERR_VALIDATION", "ndc_code required")

    cid = store.new_id()
    now_iso = store.now_iso()
    claim = {
        "id": cid,
        "beneficiary_id": bid,
        "enrollment_id": eid,
        "ndc_code": ndc,
        "tier": tier,
        "_fill_dt": fill_dt,
        "gross_cost_cents": gross,
        "status": "SUBMITTED",
        "phase_at_adjudication": None,
        "beneficiary_cost_cents": None,
        "plan_cost_cents": None,
        "_adjudicated_dt": None,
        "_submitter_user_id": g.user_id,
        "created_at": now_iso,
    }
    # DrugClaim does not carry version/updated_at per scaffold
    store.drug_claims[cid] = claim
    return ok_object(serialize_drug_claim(claim), status=201)


@bp.route("/drug-claims/<cid>/adjudicate", methods=["POST"])
@require_roles("PlanAdmin")
def adjudicate_claim(cid):
    claim = store.drug_claims.get(cid)
    if not claim:
        raise err("ERR_NOT_FOUND", "Drug claim not found")
    body = request.get_json(silent=True) or {}
    beneficiary = store.beneficiaries[claim["beneficiary_id"]]
    enrollment = store.enrollments[claim["enrollment_id"]]
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")
    if claim["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim must be SUBMITTED to adjudicate")
    if enrollment["part_covered"] != "PART_D":
        raise err("ERR_NON_PART_D_CLAIM", "Claim must reference a Part D enrollment")
    plan = store.plans[enrollment["plan_id"]]
    end_of_year = datetime(plan["plan_year"], 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    coverage_end = enrollment["_termination_dt"] if enrollment["_termination_dt"] else end_of_year
    if claim["_fill_dt"] < enrollment["_effective_dt"] or claim["_fill_dt"] > coverage_end:
        raise err("ERR_FILL_DATE_OUT_OF_COVERAGE", "fill_date outside coverage window")
    # SoD: submitter must not equal adjudicator
    if claim["_submitter_user_id"] == g.user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Same operator cannot submit and adjudicate")

    ledger = _find_ledger_for_enrollment(enrollment["id"])
    if ledger is None:
        raise err("ERR_INVALID_STATE", "No ledger exists for this enrollment")

    # OCC against ledger.version if "version" supplied in body
    if body and "version" in body and body["version"] is not None:
        v = body["version"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise err("ERR_VALIDATION", "version must be integer")
        if v != ledger["version"]:
            raise err("ERR_LEDGER_VERSION_STALE", "Ledger version stale")

    # Replay chronologically: every previously ADJUDICATED claim (oldest fill_date first,
    # tie-break by id ascending), then this claim. The pre-claim ledger snapshot for THIS
    # claim is the state after replaying claims whose (fill_date, id) sort earlier.
    adjudicated = [
        c for c in store.drug_claims.values()
        if c["enrollment_id"] == enrollment["id"] and c["status"] == "ADJUDICATED"
    ]

    # Determine sort key: (fill_date, id). The claim being adjudicated has not yet been
    # adjudicated — its (fill_date, id) determines where it slots.
    def sort_key(c):
        return (c["_fill_dt"], c["id"])

    # Pre-claim: replay all adjudicated claims whose sort_key < this claim's sort_key.
    earlier = [c for c in adjudicated if sort_key(c) < sort_key(claim)]
    later = [c for c in adjudicated if sort_key(c) > sort_key(claim)]
    earlier.sort(key=sort_key)
    later.sort(key=sort_key)

    pre_state = replay_chronological(earlier, plan)
    pre_ded = pre_state["ded_paid"]
    pre_spend = pre_state["spend"]
    pre_troop = pre_state["troop"]

    # Run THIS claim
    this_result = phase_walk(
        gross_cost_cents=claim["gross_cost_cents"],
        tier=claim["tier"],
        plan=plan,
        pre_ded_paid=pre_ded,
        pre_spend=pre_spend,
        pre_troop=pre_troop,
    )

    # Now replay the later (already-adjudicated) claims after THIS one to compute the
    # canonical final ledger state.
    post_ded = this_result["post_ded_paid"]
    post_spend = this_result["post_spend"]
    post_troop = this_result["post_troop"]
    for c in later:
        # The later claim was already adjudicated previously; we re-run it to get the
        # NEW correct beneficiary/plan costs after THIS claim was inserted in chronological
        # order. Per the PRD, the ledger state must equal the chronological sum of all
        # adjudicated contributions; we therefore overwrite the later claims' per-claim
        # contributions to maintain that invariant.
        r = phase_walk(
            gross_cost_cents=c["gross_cost_cents"],
            tier=c["tier"],
            plan=plan,
            pre_ded_paid=post_ded,
            pre_spend=post_spend,
            pre_troop=post_troop,
        )
        c["beneficiary_cost_cents"] = r["beneficiary_cost_cents"]
        c["plan_cost_cents"] = r["plan_cost_cents"]
        c["phase_at_adjudication"] = r["phase_at_adjudication"]
        post_ded = r["post_ded_paid"]
        post_spend = r["post_spend"]
        post_troop = r["post_troop"]

    # Determine next_phase from the final state (after this claim AND later claims)
    D = int(plan.get("annual_deductible_cents", 0) or 0)
    I = int(plan.get("initial_coverage_limit_cents", 0) or 0)
    C = int(plan.get("catastrophic_threshold_cents", 0) or 0)
    if post_ded < D:
        next_phase = "DEDUCTIBLE"
    elif post_spend < I:
        next_phase = "INITIAL_COVERAGE"
    elif post_troop < C:
        next_phase = "COVERAGE_GAP"
    else:
        next_phase = "CATASTROPHIC"

    now_iso = store.now_iso()
    # Write this claim's outputs
    claim["status"] = "ADJUDICATED"
    claim["phase_at_adjudication"] = this_result["phase_at_adjudication"]
    claim["beneficiary_cost_cents"] = this_result["beneficiary_cost_cents"]
    claim["plan_cost_cents"] = this_result["plan_cost_cents"]
    claim["_adjudicated_dt"] = store.clock

    # Update ledger counters to final state
    ledger["deductible_paid_cents"] = post_ded
    ledger["total_drug_spend_cents"] = post_spend
    ledger["troop_cents"] = post_troop
    ledger["current_phase"] = next_phase
    # last_adjudicated_claim_id is the claim adjudicated most recently in WALL-TIME (which
    # is this claim).
    ledger["last_adjudicated_claim_id"] = claim["id"]
    stamp_update(ledger, store_now_iso=now_iso)

    return ok_object(serialize_drug_claim(claim))


@bp.route("/drug-claims/<cid>/reverse", methods=["POST"])
@require_roles("PlanAdmin")
def reverse_claim(cid):
    claim = store.drug_claims.get(cid)
    if not claim:
        raise err("ERR_NOT_FOUND", "Drug claim not found")
    body = request.get_json(silent=True) or {}
    beneficiary = store.beneficiaries[claim["beneficiary_id"]]
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")
    if claim["status"] == "SUBMITTED":
        claim["status"] = "REVERSED"
        return ok_object(serialize_drug_claim(claim))
    if claim["status"] != "ADJUDICATED":
        raise err("ERR_INVALID_STATE", "Claim must be SUBMITTED or ADJUDICATED to reverse")

    enrollment = store.enrollments[claim["enrollment_id"]]
    plan = store.plans[enrollment["plan_id"]]
    ledger = _find_ledger_for_enrollment(enrollment["id"])
    if ledger is None:
        raise err("ERR_INVALID_STATE", "No ledger exists for this enrollment")

    # OCC against ledger.version
    if body and "version" in body and body["version"] is not None:
        v = body["version"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise err("ERR_VALIDATION", "version must be integer")
        if v != ledger["version"]:
            raise err("ERR_LEDGER_VERSION_STALE", "Ledger version stale")

    # Reverse must be of the most-recently adjudicated claim — checked against last_adjudicated_claim_id
    if ledger["last_adjudicated_claim_id"] != claim["id"]:
        raise err("ERR_REVERSE_BLOCKED_BY_LATER_CLAIM", "A later adjudicated claim exists")

    # Recompute ledger by replaying all remaining ADJUDICATED claims chronologically
    remaining = [
        c for c in store.drug_claims.values()
        if c["enrollment_id"] == enrollment["id"]
        and c["status"] == "ADJUDICATED"
        and c["id"] != claim["id"]
    ]
    remaining.sort(key=lambda c: (c["_fill_dt"], c["id"]))
    replay = replay_chronological(remaining, plan)

    # Update each remaining claim's per-claim contributions to match canonical replay
    # (in case earlier write-backs were optimistic and need refreshing).
    post_ded = 0
    post_spend = 0
    post_troop = 0
    for c, r in zip(remaining, replay["per_claim"]):
        c["beneficiary_cost_cents"] = r["beneficiary_cost_cents"]
        c["plan_cost_cents"] = r["plan_cost_cents"]
        c["phase_at_adjudication"] = r["phase_at_adjudication"]
        post_ded = r["post_ded_paid"]
        post_spend = r["post_spend"]
        post_troop = r["post_troop"]

    D = int(plan.get("annual_deductible_cents", 0) or 0)
    I = int(plan.get("initial_coverage_limit_cents", 0) or 0)
    C = int(plan.get("catastrophic_threshold_cents", 0) or 0)
    if post_ded < D:
        next_phase = "DEDUCTIBLE"
    elif post_spend < I:
        next_phase = "INITIAL_COVERAGE"
    elif post_troop < C:
        next_phase = "COVERAGE_GAP"
    else:
        next_phase = "CATASTROPHIC"

    now_iso = store.now_iso()
    ledger["deductible_paid_cents"] = post_ded
    ledger["total_drug_spend_cents"] = post_spend
    ledger["troop_cents"] = post_troop
    ledger["current_phase"] = next_phase
    if remaining:
        # Update last_adjudicated_claim_id to the chronological tail
        ledger["last_adjudicated_claim_id"] = remaining[-1]["id"]
    else:
        ledger["last_adjudicated_claim_id"] = None
    stamp_update(ledger, store_now_iso=now_iso)

    claim["status"] = "REVERSED"
    return ok_object(serialize_drug_claim(claim))


@bp.route("/drug-claims/<cid>", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def get_claim(cid):
    c = store.drug_claims.get(cid)
    if not c:
        raise err("ERR_NOT_FOUND", "Drug claim not found")
    if g.role == "Beneficiary" and c["beneficiary_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own claims")
    return ok_object(serialize_drug_claim(c))


# ---------- Ledger ----------

ledger_bp = Blueprint("ledger", __name__)


@ledger_bp.route("/beneficiaries/<bid>/drug-phase-ledger", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def get_ledger(bid):
    b = store.beneficiaries.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Beneficiary not found")
    if g.role == "Beneficiary" and bid != g.user_id:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own ledger")
    plan_year_q = request.args.get("plan_year")
    candidates = [l for l in store.drug_phase_ledgers.values() if l["beneficiary_id"] == bid]
    if plan_year_q is not None:
        try:
            py = int(plan_year_q)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "plan_year must be integer")
        candidates = [l for l in candidates if l["plan_year"] == py]
    if not candidates:
        raise err("ERR_NOT_FOUND", "No ledger for beneficiary")
    # Return latest plan_year (or only one)
    candidates.sort(key=lambda l: (l["plan_year"], l["created_at"]), reverse=True)
    return ok_object(serialize_drug_phase_ledger(candidates[0]))


@ledger_bp.route("/beneficiaries/<bid>/drug-cost-estimate", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary")
def forward_estimate(bid):
    b = store.beneficiaries.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Beneficiary not found")
    if g.role == "Beneficiary" and bid != g.user_id:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own estimate")
    raw_gross = request.args.get("gross_cost_cents")
    raw_tier = request.args.get("tier")
    if raw_gross is None or raw_tier is None:
        raise err("ERR_VALIDATION", "gross_cost_cents and tier query params required")
    try:
        gross = int(raw_gross)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "gross_cost_cents must be integer")
    if gross < 1:
        raise err("ERR_VALIDATION", "gross_cost_cents must be >= 1")
    if raw_tier not in TIERS:
        raise err("ERR_VALIDATION", f"tier must be one of {sorted(TIERS)}")

    # Find an ACTIVE PART_D enrollment for this beneficiary (latest)
    candidates = [
        e for e in store.enrollments.values()
        if e["beneficiary_id"] == bid and e["part_covered"] == "PART_D" and e["status"] == "ACTIVE"
    ]
    if not candidates:
        raise err("ERR_NOT_FOUND", "No active PART_D enrollment for beneficiary")
    candidates.sort(key=lambda e: e["_effective_dt"], reverse=True)
    enrollment = candidates[0]
    plan = store.plans[enrollment["plan_id"]]
    ledger = _find_ledger_for_enrollment(enrollment["id"])
    if ledger is None:
        raise err("ERR_NOT_FOUND", "Ledger missing for active enrollment")

    result = phase_walk(
        gross_cost_cents=gross,
        tier=raw_tier,
        plan=plan,
        pre_ded_paid=ledger["deductible_paid_cents"],
        pre_spend=ledger["total_drug_spend_cents"],
        pre_troop=ledger["troop_cents"],
    )
    return ok_object({
        "beneficiary_cost_cents": result["beneficiary_cost_cents"],
        "plan_cost_cents": result["plan_cost_cents"],
        "phase_at_adjudication": result["phase_at_adjudication"],
    })
