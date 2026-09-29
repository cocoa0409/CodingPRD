"""Investment policy statements and the asset-class slot skeleton."""
from decimal import Decimal
from flask import Blueprint

import calc
from core import (D, as_dec, as_enum, as_int, as_str, authenticate, body, clock,
                  fail, new_row, ok, ok_list, opt_field, paginate, parse_date,
                  public, q_int, q_str, req_field, store, touch)
from helpers import (filter_rows, get_row, require_posture, resolve_body_refs)

bp = Blueprint("menu", __name__)


def _posture(plan):
    calc.recompute_posture(plan)
    touch(plan)


def _require_adopted_ips(plan):
    ips = calc.adopted_ips(plan["id"])
    if ips is None:
        fail("ERR_NO_ADOPTED_IPS", "the plan has no ADOPTED investment policy statement")
    return ips


def _parse_weights(payload, required=True):
    weights = payload.get("weights")
    if weights is None:
        if required:
            fail("ERR_INVALID_REQUEST", "weights is required")
        return None
    if not isinstance(weights, dict):
        fail("ERR_INVALID_REQUEST", "weights must be an object")
    out = {}
    total = Decimal("0.00")
    for key in calc.WEIGHT_KEYS:
        if key not in weights or weights[key] is None:
            fail("ERR_INVALID_REQUEST", "weights.%s is required" % key)
        value = as_dec(weights[key], "weights.%s" % key, 2, "0.00", "1.00")
        out[key] = value
        total += value
    for key in weights:
        if key not in calc.WEIGHT_KEYS:
            fail("ERR_INVALID_REQUEST", "weights.%s is not a recognised weight" % key)
    if total != Decimal("1.00"):
        fail("ERR_IPS_WEIGHTS_INVALID", "the five weights must sum to exactly 1.00")
    return out


# --------------------------------------------------------------------------- #
# Investment policy statements
# --------------------------------------------------------------------------- #

@bp.route("/governance/investment-policy-statements", methods=["POST"])
def create_ips():
    authenticate(("InvestmentConsultant", "PlanSponsorAdmin"))
    payload = body()
    refs = resolve_body_refs(payload, {"!plan_id": "plans"})
    plan = refs.get("plan_id")
    version_label = as_str(req_field(payload, "version_label"), "version_label", 1, 60)
    effective_date = payload.get("effective_date")
    if effective_date is not None:
        parse_date(as_str(effective_date, "effective_date"), "effective_date")
    scoring_variant = as_enum(req_field(payload, "scoring_variant"),
                              "scoring_variant", calc.SCORING_VARIANTS)
    watch_max = as_dec(opt_field(payload, "watch_trigger_score_max", "40.00"),
                       "watch_trigger_score_max", 2, "0.00", "100.00")
    remediation_max = as_dec(
        opt_field(payload, "remediation_trigger_score_max", "25.00"),
        "remediation_trigger_score_max", 2, "0.00", "100.00")
    cure_margin = as_dec(opt_field(payload, "cure_margin_points", "10.00"),
                         "cure_margin_points", 2, "0.00", "100.00")
    peer_multiple = as_dec(opt_field(payload, "expense_peer_multiple", "1.25"),
                           "expense_peer_multiple", 4, "0.0000", "10.0000")
    min_track = as_int(opt_field(payload, "min_track_record_quarters", 12),
                       "min_track_record_quarters", 0)
    drift_floor = as_dec(opt_field(payload, "style_drift_r2_floor", "0.8000"),
                         "style_drift_r2_floor", 4, "0.0000", "1.0000")
    grace = as_int(opt_field(payload, "watch_grace_quarters", 2),
                   "watch_grace_quarters", 1, 8)
    weights = _parse_weights(payload)
    benchmark_map = payload.get("benchmark_map")
    if benchmark_map is None:
        benchmark_map = {}
    if not isinstance(benchmark_map, dict):
        fail("ERR_INVALID_REQUEST", "benchmark_map must be an object")
    if remediation_max >= watch_max:
        fail("ERR_INVALID_REQUEST",
             "remediation_trigger_score_max must be below watch_trigger_score_max")

    for row in calc.plan_ips(plan["id"]):
        if row["version_label"] == version_label:
            fail("ERR_DUPLICATE_RESOURCE", "version_label already exists on this plan")

    ips = new_row({
        "plan_id": plan["id"],
        "approving_motion_id": None,
        "version_label": version_label,
        "effective_date": effective_date,
        "status": "DRAFT",
        "scoring_variant": scoring_variant,
        "watch_trigger_score_max": watch_max,
        "remediation_trigger_score_max": remediation_max,
        "cure_margin_points": cure_margin,
        "expense_peer_multiple": peer_multiple,
        "min_track_record_quarters": min_track,
        "style_drift_r2_floor": drift_floor,
        "watch_grace_quarters": grace,
        "weights": weights,
        "benchmark_map": benchmark_map,
        "adopted_quarter_index": None,
        "superseded_quarter_index": None,
    })
    store.ips[ips["id"]] = ips
    return ok(public(ips), 201)


@bp.route("/governance/investment-policy-statements", methods=["GET"])
def list_ips():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    rows = filter_rows(list(store.ips.values()),
                       [(q_str("plan_id"), "plan_id"),
                        (q_str("approving_motion_id"), "approving_motion_id"),
                        (q_str("status"), "status"),
                        (q_str("version_label"), "version_label"),
                        (q_str("scoring_variant"), "scoring_variant")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/investment-policy-statements/<ips_id>", methods=["GET"])
def get_ips(ips_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "PlanAuditor"))
    return ok(public(get_row("ips", ips_id, "ipsId")))


@bp.route("/governance/investment-policy-statements/<ips_id>/adopt", methods=["POST"])
def adopt_ips(ips_id):
    authenticate(("CommitteeChair",))
    ips = get_row("ips", ips_id, "ipsId")
    payload = body()
    plan = store.plans.get(ips["plan_id"])
    refs = resolve_body_refs(payload, {"!approving_motion_id": "motions"},
                             extra_rows={"_ips": ("ips", ips)})
    motion = refs.get("approving_motion_id")

    if plan["charter_status"] != "ADOPTED":
        fail("ERR_CHARTER_NOT_ADOPTED", "the committee charter is not adopted")
    if ips["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "only a DRAFT statement may be adopted")
    if motion["subject_type"] != "IPS_ADOPTION" or motion["subject_id"] != ips["id"]:
        fail("ERR_MOTION_SUBJECT_MISMATCH",
             "the motion's subject is not this policy statement")
    if motion["status"] != "CARRIED":
        fail("ERR_MOTION_NOT_CARRIED", "the referenced motion did not carry")
    calc.require_minutes_approved(motion)
    total = Decimal("0.00")
    for key in calc.WEIGHT_KEYS:
        total += D(ips["weights"][key])
    if total != Decimal("1.00"):
        fail("ERR_IPS_WEIGHTS_INVALID", "the five weights must sum to exactly 1.00")
    if D(ips["remediation_trigger_score_max"]) >= D(ips["watch_trigger_score_max"]):
        fail("ERR_INVALID_REQUEST",
             "remediation_trigger_score_max must be below watch_trigger_score_max")

    fqi = plan["fiscal_quarter_index"]
    for other in calc.sort_created(calc.plan_ips(plan["id"])):
        if other["id"] == ips["id"]:
            continue
        if other["status"] == "ADOPTED":
            other["status"] = "SUPERSEDED"
            other["superseded_quarter_index"] = fqi
            touch(other)
        elif other["status"] == "DRAFT":
            other["status"] = "RETIRED"
            touch(other)
    ips["status"] = "ADOPTED"
    ips["adopted_quarter_index"] = fqi
    ips["approving_motion_id"] = motion["id"]
    touch(ips)
    _posture(plan)
    return ok(public(ips))


# --------------------------------------------------------------------------- #
# Asset-class slots
# --------------------------------------------------------------------------- #

@bp.route("/governance/asset-class-slots", methods=["POST"])
def create_slot():
    authenticate(("InvestmentConsultant", "PlanSponsorAdmin"))
    payload = body()
    refs = resolve_body_refs(payload, {"!plan_id": "plans", "ips_id": "ips"})
    plan = refs.get("plan_id")
    asset_class = as_enum(req_field(payload, "asset_class_code"),
                          "asset_class_code", calc.ASSET_CLASSES)
    designation = as_enum(req_field(payload, "designation"), "designation",
                          calc.DESIGNATIONS)
    slot_index = as_int(req_field(payload, "slot_index"), "slot_index", 1)
    adopted = _require_adopted_ips(plan)
    ips = refs.get("ips_id") or adopted

    for slot in calc.plan_slots(plan["id"]):
        if slot["status"] == "RETIRED":
            continue
        if slot["asset_class_code"] == asset_class:
            fail("ERR_DUPLICATE_RESOURCE",
                 "the asset class already has a slot on this plan")
        if designation == "QDIA" and slot["designation"] == "QDIA":
            fail("ERR_DUPLICATE_RESOURCE", "the plan already has a QDIA slot")
    for slot in calc.plan_slots(plan["id"]):
        if slot["slot_index"] == slot_index:
            fail("ERR_DUPLICATE_RESOURCE", "slot_index already exists on this plan")

    slot = new_row({
        "plan_id": plan["id"],
        "ips_id": ips["id"],
        "asset_class_code": asset_class,
        "designation": designation,
        "current_fund_id": None,
        "status": "EMPTY",
        "at_risk_since_quarter_index": None,
        "status_before_last_review": None,
        "slot_index": slot_index,
    })
    store.slots[slot["id"]] = slot
    return ok(public(slot), 201)


@bp.route("/governance/asset-class-slots", methods=["GET"])
def list_slots():
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "Recordkeeper", "PlanAuditor"))
    rows = filter_rows(list(store.slots.values()),
                       [(q_str("plan_id"), "plan_id"),
                        (q_str("ips_id"), "ips_id"),
                        (q_str("current_fund_id"), "current_fund_id"),
                        (q_str("designation"), "designation"),
                        (q_str("status"), "status"),
                        (q_str("asset_class_code"), "asset_class_code"),
                        (q_int("slot_index"), "slot_index")])
    data, limit, offset, total = paginate(rows, secondary=lambda r: r["slot_index"])
    return ok_list(data, limit, offset, total)


@bp.route("/governance/asset-class-slots/<slot_id>", methods=["GET"])
def get_slot(slot_id):
    authenticate(("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
                  "InvestmentConsultant", "Recordkeeper", "PlanAuditor"))
    return ok(public(get_row("slots", slot_id, "slotId")))


@bp.route("/governance/asset-class-slots/<slot_id>/seat-fund", methods=["POST"])
def seat_fund(slot_id):
    authenticate(("InvestmentConsultant",))
    slot = get_row("slots", slot_id, "slotId")
    payload = body()
    refs = resolve_body_refs(payload, {"!fund_id": "funds", "motion_id": "motions"},
                             extra_rows={"_slot": ("slots", slot)})
    fund = refs.get("fund_id")
    plan = store.plans.get(slot["plan_id"])

    if slot["status"] != "EMPTY":
        fail("ERR_INVALID_STATE_TRANSITION", "the slot is not EMPTY")
    if fund["menu_status"] != "CANDIDATE":
        fail("ERR_FUND_NOT_CANDIDATE", "the fund is not a CANDIDATE")
    require_posture(plan, slot)
    adopted = _require_adopted_ips(plan)
    calc.require_ips_eligible(fund, adopted)
    if fund["asset_class_code"] != slot["asset_class_code"]:
        fail("ERR_ASSET_CLASS_MISMATCH",
             "the fund's asset class does not match the slot")
    if slot["ips_id"] != adopted["id"]:
        fail("ERR_IPS_VERSION_STALE",
             "the slot is pinned to a superseded policy statement")
    if plan["available_menu_slots"] < 1:
        fail("ERR_MENU_CAPACITY_EXHAUSTED", "no available menu slot remains")
    if slot["designation"] == "QDIA":
        if not fund.get("is_target_date_suite"):
            fail("ERR_QDIA_REQUIRES_TARGET_DATE_SUITE",
                 "a QDIA slot accepts only a target-date suite")
        carried = False
        for motion in calc.plan_motions(plan["id"]):
            if motion["subject_type"] == "TARGET_DATE_SELECTION" and \
                    motion["subject_id"] == fund["id"] and \
                    motion["status"] == "CARRIED":
                carried = True
                break
        if not carried:
            fail("ERR_QDIA_REQUIRES_TARGET_DATE_SUITE",
                 "a carried TARGET_DATE_SELECTION motion must name this fund")

    slot["current_fund_id"] = fund["id"]
    slot["status"] = "ACTIVE"
    touch(slot)
    fund["menu_status"] = "ACTIVE"
    fund["credit_accrual_status"] = "ACCRUING"
    fund["qdia_flag"] = slot["designation"] == "QDIA"
    touch(fund)
    _posture(plan)
    return ok(public(slot))


@bp.route("/governance/asset-class-slots/<slot_id>/retire", methods=["POST"])
def retire_slot(slot_id):
    authenticate(("PlanSponsorAdmin",))
    slot = get_row("slots", slot_id, "slotId")
    payload = body()
    reason = payload.get("reason")
    if reason is not None:
        reason = as_str(reason, "reason", 1)
    plan = store.plans.get(slot["plan_id"])

    if slot["status"] not in ("EMPTY", "ACTIVE", "AT_RISK"):
        fail("ERR_INVALID_STATE_TRANSITION", "the slot cannot be retired now")
    if slot["designation"] == "QDIA":
        fail("ERR_QDIA_SLOT_REQUIRED", "a QDIA slot may never be retired")
    if slot["status"] in ("ACTIVE", "AT_RISK"):
        for proposal in calc.plan_proposals(plan["id"]):
            if proposal["slot_id"] == slot["id"] and \
                    proposal["status"] in calc.NON_TERMINAL_PROPOSAL_STATES:
                fail("ERR_SLOT_HAS_OPEN_PROPOSAL",
                     "a non-terminal replacement proposal exists on this slot")

    seated = store.funds.get(slot.get("current_fund_id"))
    if seated is not None and seated["menu_status"] == "ACTIVE":
        seated["menu_status"] = "PENDING_REMOVAL"
        touch(seated)
    slot["status"] = "RETIRED"
    if reason is not None:
        slot["retire_reason"] = reason
    touch(slot)
    _posture(plan)
    return ok(public(slot))
