"""ImplementationWave and RenewalPolicy routes, including the atomic wave
release (assignment + re-rate + book balancing) and disruption analysis.
"""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import balance_wave, rerate_policy, round4, wave_gap_ok
from envelope import list_response, serialize, success, to_jsonable
from errors import (
    err,
    ERR_CAP_ABOVE_REGULATORY_MAX,
    ERR_EFFECTIVE_DATE_NOT_REACHED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOTICE_DEADLINE_PASSED,
    ERR_PROFILE_INACTIVE,
    ERR_WAVE_GAP_VIOLATION,
    ERR_WAVE_WINDOW_INVALID,
)
from fields import IMPLEMENTATION_WAVE, RENEWAL_POLICY
from store import db, now, touch
from timeutil import end_of_day_utc, parse_date
from validate import (
    apply_filters, get_json_body, paginate, v_date, v_nonneg_number,
    v_pos_int, v_pos_number, v_state_code, v_string, validate_body,
)
from workflows import (
    base_entity,
    cancel_wave,
    create_calendar_entry,
    entry_mark_met,
    find_entries,
    get_or_404,
    reverse_wave,
)

bp = Blueprint("waves", __name__)


# --- waves ------------------------------------------------------------------------

@bp.route("/waves", methods=["POST"])
def create_wave():
    authenticate({"ImplementationLead"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "filing_id": (True, v_string),
        "wave_start_date": (True, v_date),
        "wave_end_date": (True, v_date),
        "cap_pct": (True, v_nonneg_number),
    })
    with db.lock:
        filing = get_or_404(db.rate_filings, data["filing_id"])
        if filing["status"] not in ("APPROVED", "DEEMED_APPROVED", "EFFECTIVE"):
            raise err(ERR_INVALID_STATE)
        profile = db.state_profiles.get(filing["profile_id"])
        if profile is None or profile["status"] != "ACTIVE":
            raise err(ERR_PROFILE_INACTIVE)
        start = parse_date(data["wave_start_date"])
        end = parse_date(data["wave_end_date"])
        if end < start:
            raise err(ERR_WAVE_WINDOW_INVALID)
        existing = [
            (parse_date(w["wave_start_date"]), parse_date(w["wave_end_date"]))
            for w in db.implementation_waves.values()
            if w["product_id"] == filing["product_id"]
            and w["state_code"] == filing["state_code"]
            and w["status"] in ("SCHEDULED", "RELEASED", "COMPLETED")
        ]
        if not wave_gap_ok(existing, start, end):
            raise err(ERR_WAVE_GAP_VIOLATION)
        if data["cap_pct"] > profile["max_single_change_pct"]:
            raise err(ERR_CAP_ABOVE_REGULATORY_MAX)
        wave = base_entity()
        wave.update({
            "filing_id": filing["id"],
            "product_id": filing["product_id"],
            "state_code": filing["state_code"],
            "wave_start_date": data["wave_start_date"],
            "wave_end_date": data["wave_end_date"],
            "cap_pct": data["cap_pct"],
            "approved_change_pct": filing["proposed_change_pct"],
            "balance_factor": None,
            "target_book_delta_cents": None,
            "final_book_delta_cents": None,
            "rated_policy_count": 0,
            "excluded_late_notice_count": 0,
            "status": "SCHEDULED",
        })
        db.implementation_waves[wave["id"]] = wave
        create_calendar_entry(
            "WAVE_WINDOW",
            end_of_day_utc(end),
            wave_id=wave["id"],
        )
    return success(serialize(wave, IMPLEMENTATION_WAVE), code=201)


@bp.route("/waves/<waveId>", methods=["GET"])
def get_wave(waveId):
    authenticate(ALL_ROLES)
    wave = get_or_404(db.implementation_waves, waveId)
    return success(serialize(wave, IMPLEMENTATION_WAVE), code=200)


@bp.route("/waves", methods=["GET"])
def list_waves():
    authenticate(ALL_ROLES)
    filters = {
        "filing_id": request.args.get("filing_id"),
        "product_id": request.args.get("product_id"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.implementation_waves.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(w, IMPLEMENTATION_WAVE) for w in page], total, limit, offset)


@bp.route("/waves/<waveId>/release", methods=["POST"])
def release_wave(waveId):
    authenticate({"ImplementationLead"})
    with db.lock:
        wave = get_or_404(db.implementation_waves, waveId)
        if wave["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE)
        filing = db.rate_filings.get(wave["filing_id"])
        if filing is None or filing["status"] != "EFFECTIVE":
            raise err(ERR_INVALID_STATE)
        profile = db.state_profiles.get(filing["profile_id"])
        release_date = now().date()
        start = parse_date(wave["wave_start_date"])
        end = parse_date(wave["wave_end_date"])
        # claim scope: PENDING policies of the same product+state whose renewal
        # falls within the inclusive window, in creation order
        in_scope = sorted(
            (
                p
                for p in db.renewal_policies.values()
                if p["status"] == "PENDING"
                and p["product_id"] == wave["product_id"]
                and p["state_code"] == wave["state_code"]
                and wave["wave_start_date"] <= p["renewal_effective_date"] <= wave["wave_end_date"]
            ),
            key=lambda p: (p["created_at"], p["_seq"]),
        )
        rated = []
        excluded = 0
        for p in in_scope:
            notice_due = parse_date(p["renewal_effective_date"]) - timedelta(
                days=profile["renewal_notice_days"]
            )
            if release_date > notice_due:
                # timely notice impossible by construction: leave out
                p["exclusion_reason"] = "LATE_NOTICE_BY_CONSTRUCTION"
                touch(p)
                excluded += 1
                continue
            p["baseline_premium_cents"] = p["current_premium_cents"]
            raw_change_pct, raw_new, was_capped, capped = rerate_policy(
                wave["approved_change_pct"], wave["cap_pct"],
                p["class_rel_factor"], p["current_premium_cents"],
            )
            p["raw_change_pct"] = raw_change_pct
            p["raw_new_premium_cents"] = raw_new
            p["was_capped"] = was_capped
            p["notice_due_date"] = notice_due.isoformat()
            p["wave_id"] = wave["id"]
            p["exclusion_reason"] = None
            p["status"] = "RATED"
            p["_approved_change_pct"] = wave["approved_change_pct"]
            touch(p)
            create_calendar_entry(
                "RENEWAL_NOTICE_DUE",
                end_of_day_utc(notice_due),
                wave_id=wave["id"],
                policy_id=p["id"],
            )
            rated.append((p, capped))
        balance_factor, target, final_delta = balance_wave(rated)
        wave["balance_factor"] = balance_factor
        wave["target_book_delta_cents"] = target
        wave["final_book_delta_cents"] = final_delta
        wave["rated_policy_count"] = len(rated)
        wave["excluded_late_notice_count"] = excluded
        wave["status"] = "RELEASED"
        touch(wave)
        for p, _ in rated:
            p.pop("_approved_change_pct", None)
    return success(serialize(wave, IMPLEMENTATION_WAVE), code=200)


@bp.route("/waves/<waveId>/reverse", methods=["POST"])
def reverse_wave_route(waveId):
    authenticate({"ImplementationLead"})
    with db.lock:
        wave = get_or_404(db.implementation_waves, waveId)
        if wave["status"] != "RELEASED":
            raise err(ERR_INVALID_STATE)
        reverse_wave(wave)
    return success(serialize(wave, IMPLEMENTATION_WAVE), code=200)


@bp.route("/waves/<waveId>/cancel", methods=["POST"])
def cancel_wave_route(waveId):
    authenticate({"ImplementationLead"})
    with db.lock:
        wave = get_or_404(db.implementation_waves, waveId)
        if wave["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE)
        cancel_wave(wave)
    return success(serialize(wave, IMPLEMENTATION_WAVE), code=200)


@bp.route("/waves/<waveId>/disruption-analysis", methods=["GET"])
def disruption_analysis(waveId):
    authenticate(ALL_ROLES)
    wave = get_or_404(db.implementation_waves, waveId)
    policies = [
        p
        for p in db.renewal_policies.values()
        if p["wave_id"] == wave["id"] and p["status"] in ("RATED", "NOTICE_SENT", "COMPLETED")
    ]
    if policies:
        total = len(policies)
        capped_count = sum(1 for p in policies if p["was_capped"])
        raw_pcts = [p["raw_change_pct"] for p in policies]
        sum_baseline = sum(p["baseline_premium_cents"] for p in policies)
        raw_delta = sum(p["raw_new_premium_cents"] - p["baseline_premium_cents"] for p in policies)
        final_delta = sum(p["final_premium_cents"] - p["baseline_premium_cents"] for p in policies)
        data = {
            "total_policies": total,
            "capped_policy_count": capped_count,
            "max_raw_change_pct": max(raw_pcts),
            "min_raw_change_pct": min(raw_pcts),
            "book_avg_raw_change_pct": round4(Decimal(raw_delta) / Decimal(sum_baseline)),
            "book_avg_final_change_pct": round4(Decimal(final_delta) / Decimal(sum_baseline)),
            "balance_factor": wave["balance_factor"],
            "target_book_delta_cents": wave["target_book_delta_cents"],
            "final_book_delta_cents": wave["final_book_delta_cents"],
        }
    else:
        data = {
            "total_policies": 0,
            "capped_policy_count": 0,
            "max_raw_change_pct": None,
            "min_raw_change_pct": None,
            "book_avg_raw_change_pct": None,
            "book_avg_final_change_pct": None,
            "balance_factor": wave["balance_factor"],
            "target_book_delta_cents": wave["target_book_delta_cents"],
            "final_book_delta_cents": wave["final_book_delta_cents"],
        }
    return success({k: to_jsonable(v) for k, v in data.items()}, code=200)


# --- renewal policies ---------------------------------------------------------------

@bp.route("/policies", methods=["POST"])
def create_policy():
    authenticate({"ImplementationLead"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "product_id": (True, v_string),
        "state_code": (True, v_state_code),
        "policy_number": (True, v_string),
        "current_premium_cents": (True, v_pos_int),
        "class_rel_factor": (True, v_pos_number),
        "renewal_effective_date": (True, v_date),
    })
    with db.lock:
        get_or_404(db.products, data["product_id"])
        # policy_number is unique within (product_id, state_code)
        for p in db.renewal_policies.values():
            if (
                p["product_id"] == data["product_id"]
                and p["state_code"] == data["state_code"]
                and p["policy_number"] == data["policy_number"]
            ):
                raise err(ERR_INVALID_REQUEST)
        policy = base_entity()
        policy.update({
            "product_id": data["product_id"],
            "wave_id": None,
            "state_code": data["state_code"],
            "policy_number": data["policy_number"],
            "current_premium_cents": data["current_premium_cents"],
            "class_rel_factor": data["class_rel_factor"],
            "renewal_effective_date": data["renewal_effective_date"],
            "baseline_premium_cents": None,
            "raw_change_pct": None,
            "raw_new_premium_cents": None,
            "was_capped": None,
            "final_premium_cents": None,
            "notice_due_date": None,
            "notice_sent_at": None,
            "status": "PENDING",
            "exclusion_reason": None,
        })
        db.renewal_policies[policy["id"]] = policy
    return success(serialize(policy, RENEWAL_POLICY), code=201)


@bp.route("/policies/<policyId>", methods=["GET"])
def get_policy(policyId):
    authenticate(ALL_ROLES)
    policy = get_or_404(db.renewal_policies, policyId)
    return success(serialize(policy, RENEWAL_POLICY), code=200)


@bp.route("/policies", methods=["GET"])
def list_policies():
    authenticate(ALL_ROLES)
    filters = {
        "product_id": request.args.get("product_id"),
        "wave_id": request.args.get("wave_id"),
        "state_code": request.args.get("state_code"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.renewal_policies.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(p, RENEWAL_POLICY) for p in page], total, limit, offset)


@bp.route("/policies/<policyId>/send-notice", methods=["POST"])
def send_notice(policyId):
    authenticate({"ImplementationLead"})
    with db.lock:
        policy = get_or_404(db.renewal_policies, policyId)
        if policy["status"] != "RATED":
            raise err(ERR_INVALID_STATE)
        if now().date() > parse_date(policy["notice_due_date"]):
            raise err(ERR_NOTICE_DEADLINE_PASSED)
        policy["status"] = "NOTICE_SENT"
        policy["notice_sent_at"] = now()
        touch(policy)
        for e in find_entries("RENEWAL_NOTICE_DUE", policy_id=policy["id"], status="PENDING"):
            entry_mark_met(e)
    return success(serialize(policy, RENEWAL_POLICY), code=200)


@bp.route("/policies/<policyId>/complete-renewal", methods=["POST"])
def complete_renewal(policyId):
    authenticate({"ImplementationLead"})
    with db.lock:
        policy = get_or_404(db.renewal_policies, policyId)
        if policy["status"] != "NOTICE_SENT":
            raise err(ERR_INVALID_STATE)
        if now().date() < parse_date(policy["renewal_effective_date"]):
            raise err(ERR_EFFECTIVE_DATE_NOT_REACHED)
        policy["status"] = "COMPLETED"
        policy["current_premium_cents"] = policy["final_premium_cents"]
        touch(policy)
    return success(serialize(policy, RENEWAL_POLICY), code=200)
