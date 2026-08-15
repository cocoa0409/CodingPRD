"""Business logic: derived fields, selector, commission waterfall, clock sweep."""
from datetime import timedelta

import store
from util import iso, rhu, month_key, new_id, DAY

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVENT_POINTS = {
    "EMAIL_OPEN": 5,
    "LINK_CLICK": 10,
    "CALL_ANSWERED": 20,
    "FORM_SUBMIT": 25,
    "REPLIED": 30,
    "SHOWING_ATTENDED": 40,
}

DEFAULT_TIER_WEIGHT_BPS = {"BRONZE": 10000, "SILVER": 11000, "GOLD": 12500, "PLATINUM": 15000}

WARM_THRESHOLD = 40
HOT_THRESHOLD = 75
DECAY_STEP1_DAYS = 30
DECAY_STEP2_DAYS = 60

HOT_BOOST_MIN_CONVERSIONS = 5
HOT_BOOST_MULTIPLIER = 2

PLATINUM_MIN_CONVERSIONS = 8
PLATINUM_MAX_RESPONSE_SECONDS = 300
GOLD_MIN_CONVERSIONS = 4
GOLD_MAX_RESPONSE_SECONDS = 900
SILVER_MIN_CONVERSIONS = 1

HOUSE_BPS = 3000
VOLUME_TIER_THRESHOLD_CENTS = 10000000
VOLUME_PREMIUM_BPS = 500

EST_COMMISSION_BPS = 300
TEMP_PROBABILITY_BPS = {"COLD": 500, "WARM": 2000, "HOT": 4500}

ACTIVE_LEAD_STATUSES = {"OFFERED", "CLAIMED", "WORKING", "UNDER_CONTRACT"}
OPEN_PIPELINE_STATUSES = {"OFFERED", "CLAIMED", "WORKING", "UNDER_CONTRACT"}


# ---------------------------------------------------------------------------
# Derived agent fields (reconciled on read from underlying data)
# ---------------------------------------------------------------------------

def _window_start(days=90):
    return store.now() - timedelta(days=days)


def derived_active_lead_count(agent_id):
    return sum(1 for l in store.leads.values()
               if l["assigned_agent_id"] == agent_id and l["status"] in ACTIVE_LEAD_STATUSES)


def derived_offered(agent_id):
    ws = _window_start()
    return sum(1 for a in store.assignments.values()
               if a["agent_id"] == agent_id and ws <= a["offered_at"] <= store.now())


def derived_claimed(agent_id):
    ws = _window_start()
    return sum(1 for a in store.assignments.values()
               if a["agent_id"] == agent_id and a.get("_claimed_at") is not None
               and ws <= a["_claimed_at"] <= store.now())


def derived_conversions(agent_id):
    ws = _window_start()
    return sum(1 for d in store.deals.values()
               if d["agent_id"] == agent_id and d["status"] in ("APPROVED", "PAID_OUT")
               and d.get("approved_at") is not None and ws <= d["approved_at"] <= store.now())


def derived_avg_response(agent_id):
    """Integer mean (round half up) of response gaps in the trailing 90d, else None."""
    ws = _window_start()
    gaps = []
    for a in store.assignments.values():
        if a["agent_id"] != agent_id:
            continue
        ra = a.get("responded_at")
        if ra is None or not (ws <= ra <= store.now()):
            continue
        lead = store.leads.get(a["lead_id"])
        if lead is None:
            continue
        gaps.append((ra - lead["created_at"]).total_seconds())
    if not gaps:
        return None
    return rhu(int(round(sum(gaps) * 1_000_000)), len(gaps) * 1_000_000)


def agent_conversions(agent):
    return derived_conversions(agent["id"]) + agent["stat_adj"]["conversions"]


def agent_claimed(agent):
    return derived_claimed(agent["id"]) + agent["stat_adj"]["claimed"]


def agent_offered(agent):
    return derived_offered(agent["id"]) + agent["stat_adj"]["offered"]


def agent_avg_response(agent):
    real = derived_avg_response(agent["id"])
    if real is not None:
        return real
    return agent.get("imported_avg_response")


def agent_tier(agent):
    c = agent_conversions(agent)
    r = agent_avg_response(agent)
    if c >= PLATINUM_MIN_CONVERSIONS and r is not None and r <= PLATINUM_MAX_RESPONSE_SECONDS:
        return "PLATINUM"
    if c >= GOLD_MIN_CONVERSIONS and r is not None and r <= GOLD_MAX_RESPONSE_SECONDS:
        return "GOLD"
    if c >= SILVER_MIN_CONVERSIONS:
        return "SILVER"
    return "BRONZE"


# ---------------------------------------------------------------------------
# Engagement score / temperature
# ---------------------------------------------------------------------------

def event_effective_points(ev, now=None):
    now = now or store.now()
    age_days = int((now - ev["occurred_at"]).total_seconds() // 86400)
    if age_days < DECAY_STEP1_DAYS:
        return ev["points"]
    if age_days < DECAY_STEP2_DAYS:
        return ev["points"] // 2
    return 0


def lead_score(lead_id, now=None):
    return sum(event_effective_points(e, now) for e in store.events.values()
               if e["lead_id"] == lead_id)


def temperature_for_score(score):
    if score >= HOT_THRESHOLD:
        return "HOT"
    if score >= WARM_THRESHOLD:
        return "WARM"
    return "COLD"


def cascade_temperature_exits(lead, new_temp):
    """Exit ENROLLED/PAUSED enrollments whose campaign target != new temperature."""
    for e in store.enrollments.values():
        if e["lead_id"] != lead["id"] or e["status"] not in ("ENROLLED", "PAUSED"):
            continue
        camp = store.campaigns.get(e["campaign_id"])
        if camp is None or camp["temperature_target"] == new_temp:
            continue
        e["status"] = "EXITED"
        e["exit_reason"] = "TEMPERATURE_SHIFT"
        store.touch(e)


def refresh_lead_temperature(lead):
    """Recompute score/temperature; cascade enrollment exits on a temperature change."""
    score = lead_score(lead["id"])
    new_temp = temperature_for_score(score)
    if new_temp != lead["temperature"]:
        lead["temperature"] = new_temp
        store.touch(lead)
        cascade_temperature_exits(lead, new_temp)
    return score


# ---------------------------------------------------------------------------
# Policies / effective windows
# ---------------------------------------------------------------------------

def active_policy(team_id):
    for p in store.policies.values():
        if p["team_id"] == team_id and p["status"] == "ACTIVE":
            return p
    return None


def effective_claim_window(team, policy):
    if policy is not None and policy.get("claim_window_seconds") is not None:
        return policy["claim_window_seconds"]
    return team["claim_window_seconds"]


def effective_speed_window(team, policy):
    if policy is not None and policy.get("speed_to_lead_window_seconds") is not None:
        return policy["speed_to_lead_window_seconds"]
    return team["speed_to_lead_window_seconds"]


# ---------------------------------------------------------------------------
# Agent selector
# ---------------------------------------------------------------------------

def _on_time_off(agent_id, now):
    for t in store.timeoffs.values():
        if t["agent_id"] == agent_id and t["starts_at"] <= now <= t["ends_at"]:
            return True
    return False


def _rr_key(agent):
    last = agent.get("last_assigned_at")
    return (0 if last is None else 1,
            last if last is not None else agent["created_at"],
            agent["created_at"], agent["_seq"])


def select_agent(lead, team, policy, excluded_ids):
    """Return (agent, effective_mode) or (None, effective_mode) when pool empty."""
    now = store.now()
    source = store.sources.get(lead["source_id"])
    overrides = policy.get("source_mode_overrides") or {}
    mode = overrides.get(source["type"], policy["mode"]) if source else policy["mode"]

    eligible = []
    for a in store.agents.values():
        if a["team_id"] != team["id"]:
            continue
        if a["status"] != "ACTIVE":
            continue
        if derived_active_lead_count(a["id"]) >= a["max_active_leads"]:
            continue
        if _on_time_off(a["id"], now):
            continue
        if a["id"] in excluded_ids:
            continue
        eligible.append(a)

    if not eligible:
        return None, mode

    if mode == "ROUND_ROBIN":
        eligible.sort(key=_rr_key)
        return eligible[0], mode

    # PERFORMANCE_WEIGHTED
    weights = dict(DEFAULT_TIER_WEIGHT_BPS)
    weights.update(policy.get("tier_weight_bps") or {})
    scored = []
    for a in eligible:
        remaining = a["max_active_leads"] - derived_active_lead_count(a["id"])
        score = weights.get(agent_tier(a), 10000) * remaining
        if lead["temperature"] == "HOT" and agent_conversions(a) >= HOT_BOOST_MIN_CONVERSIONS:
            score = score * HOT_BOOST_MULTIPLIER
        scored.append((a, score))
    scored.sort(key=lambda t: (-t[1],) + _rr_key(t[0]))
    return scored[0][0], mode


def create_assignment(lead, team, policy, agent, mode, supersedes=None):
    """Create the OFFERED assignment and flip the lead. Returns the assignment."""
    now = store.now()
    claim_win = effective_claim_window(team, policy)
    speed_win = effective_speed_window(team, policy)
    asg = {
        "id": new_id(),
        "lead_id": lead["id"],
        "agent_id": agent["id"],
        "policy_id": policy["id"],
        "supersedes_assignment_id": supersedes,
        "rotation_seq": store.next_rotation(team["id"]),
        "policy_mode_snapshot": mode,
        "offered_at": now,
        "claim_deadline_at": now + timedelta(seconds=claim_win),
        "responded_at": None,
        "status": "OFFERED",
        "outcome_reason": None,
        "_claimed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.assignments[asg["id"]] = asg

    lead["status"] = "OFFERED"
    lead["assigned_agent_id"] = agent["id"]
    lead["current_assignment_id"] = asg["id"]
    lead["claim_deadline_at"] = asg["claim_deadline_at"]
    if lead["speed_deadline_at"] is None:
        lead["speed_deadline_at"] = lead["created_at"] + timedelta(seconds=speed_win)
    store.touch(lead)

    agent["last_assigned_at"] = now
    store.touch(agent)
    return asg


def route_lead(lead, excluded_ids=(), supersedes=None, explicit_agent=None):
    """Run the selector and create an OFFERED assignment.

    Returns (assignment, None) on success, (None, 'no_policy') when the team has
    no ACTIVE policy, (None, 'empty_pool') when no agent is eligible.
    """
    team = store.teams.get(lead["team_id"])
    policy = active_policy(lead["team_id"])
    if policy is None:
        return None, "no_policy"
    if explicit_agent is not None:
        agent = explicit_agent
        source = store.sources.get(lead["source_id"])
        overrides = policy.get("source_mode_overrides") or {}
        mode = overrides.get(source["type"], policy["mode"]) if source else policy["mode"]
    else:
        agent, mode = select_agent(lead, team, policy, set(excluded_ids))
        if agent is None:
            return None, "empty_pool"
    return create_assignment(lead, team, policy, agent, mode, supersedes=supersedes), None


# ---------------------------------------------------------------------------
# Pause / offboard cascades
# ---------------------------------------------------------------------------

def _expire_assignment_for_cascade(asg, reason, sweep_ctx=None):
    asg["status"] = "EXPIRED"
    asg["outcome_reason"] = reason
    store.touch(asg)
    if sweep_ctx is not None:
        sweep_ctx["expired_assignment_count"] += 1
    lead = store.leads.get(asg["lead_id"])
    if lead is not None and lead["current_assignment_id"] == asg["id"]:
        lead["status"] = "NEW"
        lead["assigned_agent_id"] = None
        lead["current_assignment_id"] = None
        lead["claim_deadline_at"] = None
        store.touch(lead)
    return lead


def pause_agent_cascade(agent, sweep_ctx=None):
    """ACTIVE -> PAUSED: expire OFFERED assignments (AUTO_PAUSE, no miss increment)
    and re-route affected leads with this agent excluded."""
    agent["status"] = "PAUSED"
    store.touch(agent)
    offered = [a for a in store.assignments.values()
               if a["agent_id"] == agent["id"] and a["status"] == "OFFERED"]
    offered.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for asg in offered:
        lead = _expire_assignment_for_cascade(asg, "AUTO_PAUSE", sweep_ctx)
        if lead is not None:
            route_lead(lead, excluded_ids={agent["id"]}, supersedes=asg["id"])


def offboard_agent_cascade(agent):
    """ACTIVE/PAUSED -> OFFBOARDING -> OFFBOARDED: release the whole pipeline and
    re-route returned leads with the departing agent excluded."""
    agent["status"] = "OFFBOARDING"
    store.touch(agent)

    offered = [a for a in store.assignments.values()
               if a["agent_id"] == agent["id"] and a["status"] == "OFFERED"]
    offered.sort(key=lambda a: (a["created_at"], a["_seq"]))
    rerouted = []
    for asg in offered:
        lead = _expire_assignment_for_cascade(asg, "OFFBOARD")
        if lead is not None:
            rerouted.append((lead, asg["id"]))

    held = [l for l in store.leads.values()
            if l["assigned_agent_id"] == agent["id"]
            and l["status"] in ("CLAIMED", "WORKING", "UNDER_CONTRACT")]
    held.sort(key=lambda l: (l["created_at"], l["_seq"]))
    for lead in held:
        cur = store.assignments.get(lead["current_assignment_id"] or "")
        if cur is not None and cur["status"] in ("OFFERED", "CLAIMED"):
            cur["status"] = "RELEASED"
            cur["outcome_reason"] = "OFFBOARD"
            store.touch(cur)
            supersedes = cur["id"]
        else:
            supersedes = None
        lead["status"] = "NEW"
        lead["assigned_agent_id"] = None
        lead["current_assignment_id"] = None
        lead["claim_deadline_at"] = None
        store.touch(lead)
        rerouted.append((lead, supersedes))

    for lead, supersedes in rerouted:
        route_lead(lead, excluded_ids={agent["id"]}, supersedes=supersedes)

    if derived_active_lead_count(agent["id"]) == 0:
        agent["status"] = "OFFBOARDED"
        store.touch(agent)


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------

def run_sweep():
    """Pinned ordering: expired OFFERED assignments (claim_deadline_at ASC,
    created_at ASC) with inline auto-pause cascades; then agreement expiries;
    then nurture step advancement; then decay-driven temperature refresh."""
    now = store.now()
    ctx = {"expired_assignment_count": 0, "auto_paused_agent_count": 0,
           "expired_agreement_count": 0, "advanced_enrollment_count": 0}

    due = [a for a in store.assignments.values()
           if a["status"] == "OFFERED" and a["claim_deadline_at"] < now]
    due.sort(key=lambda a: (a["claim_deadline_at"], a["created_at"], a["_seq"]))
    for asg in due:
        if asg["status"] != "OFFERED":
            continue  # already cascade-expired inside this sweep
        agent = store.agents.get(asg["agent_id"])
        lead = _expire_assignment_for_cascade(asg, "DEADLINE", ctx)
        if agent is not None:
            agent["consecutive_missed_claims"] = agent.get("consecutive_missed_claims", 0) + 1
            store.touch(agent)
            if agent["consecutive_missed_claims"] >= 3 and agent["status"] == "ACTIVE":
                ctx["auto_paused_agent_count"] += 1
                pause_agent_cascade(agent, sweep_ctx=ctx)
        if lead is not None:
            route_lead(lead,
                       excluded_ids={agent["id"]} if agent is not None else set(),
                       supersedes=asg["id"])

    for ag in store.agreements.values():
        if ag["status"] == "ACTIVE" and ag["effective_until"] is not None \
                and now >= ag["effective_until"]:
            ag["status"] = "EXPIRED"
            store.touch(ag)
            ctx["expired_agreement_count"] += 1

    due_enrollments = [e for e in store.enrollments.values()
                       if e["status"] == "ENROLLED" and e["next_send_at"] is not None
                       and e["next_send_at"] <= now]
    due_enrollments.sort(key=lambda e: (e["next_send_at"], e["created_at"], e["_seq"]))
    for e in due_enrollments:
        camp = store.campaigns.get(e["campaign_id"])
        if camp is None:
            continue
        steps = camp["steps"]
        advanced = False
        while e["status"] == "ENROLLED" and e["next_send_at"] is not None \
                and e["next_send_at"] <= now:
            e["current_step_index"] += 1
            if e["current_step_index"] >= len(steps):
                e["status"] = "COMPLETED"
                e["next_send_at"] = None
            else:
                e["next_send_at"] = e["created_at"] + timedelta(
                    days=steps[e["current_step_index"]]["offset_days"])
            advanced = True
        if advanced:
            store.touch(e)
            ctx["advanced_enrollment_count"] += 1

    for lead in store.leads.values():
        refresh_lead_temperature(lead)

    return ctx


# ---------------------------------------------------------------------------
# Commission waterfall (pinned rounding order: basis -> fee -> house -> pool -> A -> B)
# ---------------------------------------------------------------------------

def partner_ytd_volume(partner_id, exclude_deal_id):
    """Calendar-year approved volume for the partner, excluding the current deal."""
    now = store.now()
    total = 0
    for d in store.deals.values():
        if d.get("referral_partner_id") != partner_id or d["id"] == exclude_deal_id:
            continue
        if d["status"] not in ("APPROVED", "PAID_OUT") or d.get("approved_at") is None:
            continue
        if d["approved_at"].year == now.year:
            total += d["split_basis_cents"]
    return total


def covering_agreement(team_id, closing_agent_id, at):
    """Earliest-created ACTIVE agreement covering the closing agent at instant `at`."""
    matches = []
    for ag in store.agreements.values():
        if ag["team_id"] != team_id or ag["status"] != "ACTIVE":
            continue
        if closing_agent_id not in (ag["agent_a_id"], ag["agent_b_id"]):
            continue
        if ag["effective_from"] <= at and \
                (ag["effective_until"] is None or at < ag["effective_until"]):
            matches.append(ag)
    if not matches:
        return None
    matches.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return matches[0]


def compute_waterfall(deal, basis, at):
    partner = None
    if deal.get("referral_partner_id"):
        partner = store.partners.get(deal["referral_partner_id"])
    fee_bps = 0
    if partner is not None:
        ytd = partner_ytd_volume(partner["id"], deal["id"])
        fee_bps = partner["fee_bps"] + (VOLUME_PREMIUM_BPS if ytd >= VOLUME_TIER_THRESHOLD_CENTS else 0)
    referral_fee = rhu(basis * fee_bps, 10000) if partner is not None else 0
    house_share = rhu((basis - referral_fee) * HOUSE_BPS, 10000)
    pool = basis - referral_fee - house_share

    agr = covering_agreement(deal["team_id"], deal["agent_id"], at)
    if agr is not None:
        a_amt = rhu(pool * agr["a_share_bps"], 10000)
        b_amt = pool - a_amt
        shares = [{"agent_id": agr["agent_a_id"], "amount_cents": a_amt},
                  {"agent_id": agr["agent_b_id"], "amount_cents": b_amt}]
        agr_id = agr["id"]
    else:
        shares = [{"agent_id": deal["agent_id"], "amount_cents": pool}]
        agr_id = None
    return fee_bps, referral_fee, house_share, pool, shares, agr_id


def apply_waterfall(deal, basis, at, snapshot_agreement):
    fee_bps, fee, house, pool, shares, agr_id = compute_waterfall(deal, basis, at)
    deal["split_basis_cents"] = basis
    deal["effective_fee_bps"] = fee_bps
    deal["referral_fee_cents"] = fee
    deal["house_share_cents"] = house
    deal["agent_pool_cents"] = pool
    deal["agent_shares"] = shares
    if snapshot_agreement:
        deal["split_agreement_id"] = agr_id
