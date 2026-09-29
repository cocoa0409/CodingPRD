"""Domain services: maintained counters, cascades and the safe-harbour posture.

Every secondary effect here is mandatory rather than best-effort (PRD 2.11).
"""
from datetime import datetime, timedelta, timezone

import calc
from calc import D, rhu
from errors import fail
import store
from store import create, create_immutable, db, update

# --------------------------------------------------------------------------
# policy configuration
# --------------------------------------------------------------------------
POLICY_DEFAULTS = {
    "strike_expiry_days": 365,
    "decay_step_days": 90,
    "limitation_threshold_points": 20,
    "termination_threshold_points": 40,
    "appeal_window_days": 14,
    "counter_notice_window_days": 30,
    "dispute_window_days": 30,
}

EPOCH_FLOOR = datetime(1970, 1, 1, tzinfo=timezone.utc)

CLAIM_TERMINAL = ("RESTORED", "UPHELD", "WITHDRAWN")
COUNTER_TERMINAL = ("RESTORED", "BLOCKED_BY_SUIT", "SUPERSEDED", "REJECTED")
INTERVAL_STATUSES = (
    "DISABLED",
    "COUNTER_NOTICED",
    "RESTORATION_SCHEDULED",
    "UPHELD",
    "RESTORED",
)
PENALTY_STATUSES = (
    "DISABLED",
    "COUNTER_NOTICED",
    "RESTORATION_SCHEDULED",
    "RESTORED",
    "UPHELD",
)
AUTO_OPEN_CLAIM_STATUSES = (
    "DISABLED",
    "COUNTER_NOTICED",
    "RESTORATION_SCHEDULED",
    "UPHELD",
)


def published_policy(provider_id):
    if provider_id is None:
        return None
    for policy in db.policies.values():
        if policy["provider_id"] == provider_id and policy["status"] == "PUBLISHED":
            return policy
    return None


def any_published_policy():
    for policy in db.policies.values():
        if policy["status"] == "PUBLISHED":
            return policy
    return None


def policy_cfg(provider_id):
    policy = published_policy(provider_id)
    if policy is None:
        policy = any_published_policy() if provider_id is None else None
    if policy is None:
        return dict(POLICY_DEFAULTS)
    return dict((key, policy[key]) for key in POLICY_DEFAULTS)


# --------------------------------------------------------------------------
# graph navigation
# --------------------------------------------------------------------------
def account_of_item(item):
    if item is None:
        return None
    return db.accounts.get(item["account_id"])


def item_of_claim(claim):
    return db.content_items.get(claim["content_item_id"])


def account_of_claim(claim):
    return account_of_item(item_of_claim(claim))


def provider_id_of_account(account):
    return None if account is None else account["provider_id"]


def claims_of_notice(notice):
    return [c for c in db.claims.values() if c["notice_id"] == notice["id"]]


def counters_of_claim(claim):
    return [c for c in db.counter_notices.values() if c["claim_id"] == claim["id"]]


def governing_counter(claim):
    """The claim's most recent counter-notice that has not been discarded."""
    live = [
        c
        for c in counters_of_claim(claim)
        if c["status"] not in ("SUPERSEDED", "REJECTED")
    ]
    if not live:
        return None
    live.sort(key=lambda record: record["created_at"])
    return live[-1]


def provider_of_notice(notice):
    """A notice has no provider FK; resolve it through the material it names."""
    for claim in claims_of_notice(notice):
        account = account_of_claim(claim)
        if account is not None:
            provider = db.providers.get(account["provider_id"])
            if provider is not None:
                return provider
    for url in notice.get("claimed_urls") or []:
        for item in db.content_items.values():
            if item["content_url"] == url:
                account = account_of_item(item)
                if account is not None:
                    provider = db.providers.get(account["provider_id"])
                    if provider is not None:
                        return provider
    if len(db.providers) == 1:
        return list(db.providers.values())[0]
    return None


def provider_of_counter(counter):
    account = db.accounts.get(counter["account_id"])
    if account is None:
        return None
    return db.providers.get(account["provider_id"])


def accounts_of_provider(provider):
    return [a for a in db.accounts.values() if a["provider_id"] == provider["id"]]


# --------------------------------------------------------------------------
# compliance gates (ladder rungs 7 to 10)
# --------------------------------------------------------------------------
def require_registered_agent(provider):
    if provider is not None:
        satisfied = bool(provider["designated_agent_registered"])
    else:
        satisfied = any(p["designated_agent_registered"] for p in db.providers.values())
    if not satisfied:
        fail(
            "ERR_DESIGNATED_AGENT_NOT_REGISTERED",
            "The provider holds no designated agent in REGISTERED.",
        )


def require_published_policy(provider):
    if provider is not None:
        satisfied = published_policy(provider["id"]) is not None
    else:
        satisfied = any_published_policy() is not None
    if not satisfied:
        fail(
            "ERR_REPEAT_INFRINGER_POLICY_NOT_PUBLISHED",
            "The provider holds no repeat infringer policy in PUBLISHED.",
        )


def require_safe_harbor_eligible(provider):
    if provider is not None:
        satisfied = provider["safe_harbor_status"] == "ELIGIBLE"
    else:
        satisfied = any(
            p["safe_harbor_status"] == "ELIGIBLE" for p in db.providers.values()
        )
    if not satisfied:
        fail("ERR_SAFE_HARBOR_NOT_ELIGIBLE", "The provider's safe harbor status is not ELIGIBLE.")


# --------------------------------------------------------------------------
# provider posture
# --------------------------------------------------------------------------
POSTURE_TRANSITIONS = {
    "publish_contact": {("FORFEITED", "ELIGIBLE")},
    "agent_register": {("FORFEITED", "ELIGIBLE")},
    "policy_publish": {("FORFEITED", "ELIGIBLE"), ("FORFEITED", "AT_RISK")},
    "agent_lapse": {("ELIGIBLE", "FORFEITED"), ("AT_RISK", "FORFEITED")},
    "audit": {
        ("FORFEITED", "ELIGIBLE"),
        ("FORFEITED", "AT_RISK"),
        ("ELIGIBLE", "AT_RISK"),
        ("AT_RISK", "ELIGIBLE"),
        ("ELIGIBLE", "FORFEITED"),
        ("AT_RISK", "FORFEITED"),
    },
}


def refresh_provider_flags(provider):
    registered = any(
        a["provider_id"] == provider["id"] and a["registration_status"] == "REGISTERED"
        for a in db.agents.values()
    )
    published = sum(
        1
        for p in db.policies.values()
        if p["provider_id"] == provider["id"] and p["status"] == "PUBLISHED"
    )
    update(
        provider,
        designated_agent_registered=registered,
        repeat_infringer_policy_published=(published == 1),
    )


def hard_gate(provider):
    if not provider["designated_agent_registered"]:
        return "AGENT_NOT_REGISTERED"
    if not provider["repeat_infringer_policy_published"]:
        return "POLICY_NOT_PUBLISHED"
    if provider["public_contact_published_at"] is None:
        return "CONTACT_NOT_PUBLISHED"
    return None


def measure_provider(provider):
    """The four raw measurements the compliance score reads."""
    latencies = []
    for notice in db.notices.values():
        if notice["status"] not in ("PROCESSED", "CLOSED"):
            continue
        if notice["processed_at"] is None:
            continue
        owner = provider_of_notice(notice)
        if owner is None or owner["id"] != provider["id"]:
            continue
        latencies.append(calc.whole_hours_decimal(notice["created_at"], notice["processed_at"]))
    median = calc.median_response_hours(latencies)

    overdue = 0
    for counter in db.counter_notices.values():
        if counter["status"] not in ("FORWARDED", "RESTORATION_SCHEDULED"):
            continue
        deadline = counter["restoration_deadline_at"]
        if deadline is None or deadline > db.clock:
            continue
        owner = provider_of_counter(counter)
        if owner is None or owner["id"] != provider["id"]:
            continue
        overdue += 1

    cfg = policy_cfg(provider["id"])
    threshold = D(cfg["termination_threshold_points"])
    compliant = True
    for account in accounts_of_provider(provider):
        if D(account["strike_points"]) < threshold:
            continue
        addressed = any(
            case["account_id"] == account["id"] and case["status"] in ("OPEN", "EXECUTED")
            for case in db.termination_cases.values()
        )
        if not addressed:
            compliant = False
            break

    contact_published = provider["public_contact_published_at"] is not None
    return median, overdue, compliant, contact_published


def score_provider(provider):
    median, overdue, compliant, contact_published = measure_provider(provider)
    response = calc.response_component(median)
    restoration = calc.restoration_component(overdue)
    termination = rhu(D(calc.TERMINATION_WEIGHT if compliant else 0), 2)
    contact = rhu(D(calc.CONTACT_WEIGHT if contact_published else 0), 2)
    score = int(rhu(response + restoration + termination + contact, 0))
    return {
        "median_response_hours": median,
        "overdue_restoration_count": overdue,
        "termination_compliance": compliant,
        "contact_published": contact_published,
        "response_component": response,
        "restoration_component": restoration,
        "termination_component": termination,
        "contact_component": contact,
        "compliance_score": score,
    }


def recompute_posture(provider, trigger):
    """Recompute score and posture; the posture only moves on declared transitions."""
    refresh_provider_flags(provider)
    gate = hard_gate(provider)
    measured = score_provider(provider)
    if gate is not None:
        measured["response_component"] = rhu(D(0), 2)
        measured["restoration_component"] = rhu(D(0), 2)
        measured["termination_component"] = rhu(D(0), 2)
        measured["contact_component"] = rhu(D(0), 2)
        measured["compliance_score"] = 0
        resulting = "FORFEITED"
    else:
        resulting = calc.posture_for_score(measured["compliance_score"])
    measured["gate_failure_reason"] = gate
    measured["resulting_status"] = resulting

    fields = {"safe_harbor_score": measured["compliance_score"]}
    current = provider["safe_harbor_status"]
    if (current, resulting) in POSTURE_TRANSITIONS.get(trigger, set()):
        fields["safe_harbor_status"] = resulting
    update(provider, **fields)
    return measured


# --------------------------------------------------------------------------
# strike accounting
# --------------------------------------------------------------------------
def account_strikes(account, statuses=("ACTIVE", "DECAYED")):
    return [
        s
        for s in db.strikes.values()
        if s["account_id"] == account["id"] and s["status"] in statuses
    ]


def computed_points(account, cfg=None):
    cfg = cfg or policy_cfg(account["provider_id"])
    return calc.total_strike_points(
        account_strikes(account), db.clock, cfg["decay_step_days"]
    )


def open_termination_case(account, points):
    for case in db.termination_cases.values():
        if case["account_id"] == account["id"] and case["status"] in ("OPEN", "EXECUTED"):
            return None
    return create(
        db.termination_cases,
        {
            "account_id": account["id"],
            "trigger_points": calc.num(points),
            "status": "OPEN",
            "opened_by_user_id": None,
            "executed_by_user_id": None,
            "decided_by_user_id": None,
            "executed_at": None,
            "appeal_deadline_at": None,
            "appeal_filed_at": None,
            "decision": None,
        },
    )


def recompute_account(account):
    """Recompute strike_points, follow standing and open a case when warranted."""
    cfg = policy_cfg(account["provider_id"])
    points = computed_points(account, cfg)
    update(account, strike_points=calc.num(points))

    limitation = D(cfg["limitation_threshold_points"])
    termination = D(cfg["termination_threshold_points"])
    if account["standing"] == "ACTIVE" and points >= limitation:
        update(account, standing="LIMITED", upload_restricted=True)
    elif account["standing"] == "LIMITED" and points < limitation:
        update(account, standing="ACTIVE", upload_restricted=False)

    if points >= termination and account["standing"] != "TERMINATED":
        open_termination_case(account, points)
    return points


def accrue_strike(account, claim, holder, reason):
    cfg = policy_cfg(account["provider_id"])
    weight = calc.TIER_WEIGHTS.get(holder["program_tier"], 1.0)
    base = calc.num(rhu(D(calc.STRIKE_BASE_POINTS) * D(weight), 2))
    strike = create(
        db.strikes,
        {
            "account_id": account["id"],
            "claim_id": claim["id"],
            "weight": weight,
            "base_points": base,
            "effective_points": base,
            "reason": reason,
            "status": "ACTIVE",
            "accrued_at": db.clock,
            "expires_at": db.clock + timedelta(days=cfg["strike_expiry_days"]),
        },
    )
    recompute_account(account)
    return strike


def void_strikes_of_claim(claim):
    voided = False
    for strike in db.strikes.values():
        if strike["claim_id"] == claim["id"] and strike["status"] in ("ACTIVE", "DECAYED"):
            update(strike, status="VOIDED", effective_points=0)
            voided = True
    return voided


# --------------------------------------------------------------------------
# claim cascades
# --------------------------------------------------------------------------
def maybe_close_notice(notice):
    if notice is None or notice["status"] != "PROCESSED":
        return
    if notice["matched_claim_count"] < 1:
        return
    children = claims_of_notice(notice)
    if not children:
        return
    if all(claim["status"] in CLAIM_TERMINAL for claim in children):
        update(notice, status="CLOSED")


def withdraw_claim(claim):
    """DISABLED/COUNTER_NOTICED -> WITHDRAWN, compensating every side effect."""
    update(claim, status="WITHDRAWN")
    item = item_of_claim(claim)
    account = account_of_item(item)
    if item is not None and item["availability_status"] != "PURGED":
        update(
            item,
            availability_status="RESTORED",
            dispute_status="RESOLVED",
            restored_at=db.clock,
        )
        if account is not None:
            update(account, available_content_count=account["available_content_count"] + 1)
    for counter in counters_of_claim(claim):
        if counter["status"] not in COUNTER_TERMINAL:
            update(counter, status="SUPERSEDED")
    void_strikes_of_claim(claim)
    if account is not None:
        recompute_account(account)
    maybe_close_notice(db.notices.get(claim["notice_id"]))


def disable_item_for_claim(item, account, holder, claim):
    """The cascade a new claim runs on hosted material and its owner."""
    update(item, availability_status="DISABLED", disabled_at=db.clock)
    if account is not None:
        update(
            account,
            available_content_count=max(0, account["available_content_count"] - 1),
            notified_count=account["notified_count"] + 1,
        )
    update(item, dispute_status="UNDER_NOTICE")
    if account is not None:
        accrue_strike(account, claim, holder, "NOTICE_PROCESSED")


# --------------------------------------------------------------------------
# rights-holder abuse pressure
# --------------------------------------------------------------------------
def auto_open_misrepresentation_case(holder):
    eligible = [
        c
        for c in db.claims.values()
        if c["rights_holder_id"] == holder["id"] and c["status"] in AUTO_OPEN_CLAIM_STATUSES
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda record: (record["disabled_at"] or EPOCH_FLOOR, record["created_at"]),
        reverse=True,
    )
    claim = eligible[0]
    for case in db.misrep_cases.values():
        if (
            case["rights_holder_id"] == holder["id"]
            and case["claim_id"] == claim["id"]
            and case["status"] == "OPEN"
        ):
            return None
    return create(
        db.misrep_cases,
        {
            "rights_holder_id": holder["id"],
            "claim_id": claim["id"],
            "allegation": "SYSTEM_ABUSE_SCORE_THRESHOLD",
            "opened_by_user_id": None,
            "substantiated_by_user_id": None,
            "status": "OPEN",
            "affected_claim_count": 0,
            "disabled_day_count": 0,
            "base_penalty_cents": 0,
            "surcharge_cents": 0,
            "total_penalty_cents": 0,
            "substantiated_at": None,
        },
    )


def recompute_abuse_score(holder):
    score = calc.abuse_score(
        holder["withdrawn_count"],
        holder["rejected_count"],
        holder["misrepresentation_count"],
        holder["notices_processed"],
    )
    update(holder, abuse_score=calc.num(score))
    if score >= calc.AUTO_OPEN_FLOOR:
        auto_open_misrepresentation_case(holder)
    return score


def quarantine_reference_files(holder):
    """Suspension cascade: ACTIVE files are quarantined and their claims withdrawn."""
    for reference in list(db.reference_files.values()):
        if reference["rights_holder_id"] != holder["id"] or reference["status"] != "ACTIVE":
            continue
        update(reference, status="QUARANTINED")
        for claim in list(db.claims.values()):
            if claim["reference_file_id"] != reference["id"]:
                continue
            if claim["status"] in ("DISABLED", "COUNTER_NOTICED"):
                withdraw_claim(claim)


def suspend_holder(holder):
    update(holder, enrollment_status="SUSPENDED")
    quarantine_reference_files(holder)


# --------------------------------------------------------------------------
# the logical clock
# --------------------------------------------------------------------------
def advance_clock(moment):
    db.clock = moment

    for strike in list(db.strikes.values()):
        if strike["status"] not in ("ACTIVE", "DECAYED"):
            continue
        account = db.accounts.get(strike["account_id"])
        cfg = policy_cfg(account["provider_id"]) if account else dict(POLICY_DEFAULTS)
        if strike["expires_at"] is not None and db.clock >= strike["expires_at"]:
            update(strike, status="EXPIRED", effective_points=0)
            continue
        age = calc.whole_days(strike["accrued_at"], db.clock)
        points = calc.num(calc.strike_points(strike["weight"], age, cfg["decay_step_days"]))
        status = "DECAYED" if age >= cfg["decay_step_days"] else strike["status"]
        update(strike, status=status, effective_points=points)

    for account in list(db.accounts.values()):
        recompute_account(account)

    for counter in list(db.counter_notices.values()):
        if counter["status"] != "FORWARDED":
            continue
        earliest = counter["restoration_earliest_at"]
        if earliest is not None and db.clock >= earliest:
            update(counter, status="RESTORATION_SCHEDULED")

    for case in list(db.termination_cases.values()):
        if case["status"] != "EXECUTED":
            continue
        deadline = case["appeal_deadline_at"]
        if deadline is not None and db.clock > deadline and case["appeal_filed_at"] is None:
            update(case, status="CLOSED")


# --------------------------------------------------------------------------
# safe-harbour audit record
# --------------------------------------------------------------------------
def run_audit(provider):
    # Recompute every account's decayed total before the repeat-infringer measure.
    for account in accounts_of_provider(provider):
        recompute_account(account)

    measured = recompute_posture(provider, "audit")
    audit = create_immutable(
        db.audits,
        {
            "provider_id": provider["id"],
            "median_response_hours": calc.num(measured["median_response_hours"]),
            "overdue_restoration_count": measured["overdue_restoration_count"],
            "termination_compliance": measured["termination_compliance"],
            "contact_published": measured["contact_published"],
            "response_component": calc.num(measured["response_component"]),
            "restoration_component": calc.num(measured["restoration_component"]),
            "termination_component": calc.num(measured["termination_component"]),
            "contact_component": calc.num(measured["contact_component"]),
            "compliance_score": measured["compliance_score"],
            "resulting_status": measured["resulting_status"],
            "gate_failure_reason": measured["gate_failure_reason"],
        },
    )
    # The audit writes its verdict onto the provider unconditionally.
    update(
        provider,
        safe_harbor_status=measured["resulting_status"],
        safe_harbor_score=measured["compliance_score"],
        last_audit_at=audit["created_at"],
    )
    return audit
