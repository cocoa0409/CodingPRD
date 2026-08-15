"""Case-level derived state: certified intervals, avoidable-day attribution,
escalation tiers, lazy materialization of EXPIRED / CLOSED_NO_APPEAL."""
import db
from services.calculations import tier_of
from services.clock import logical_now, parse_iso


# ---------------------------------------------------------------------------
# Certified intervals
# ---------------------------------------------------------------------------

def certified_intervals(case_id):
    """Yield dicts {start, end, level_of_care, source} for every granted interval
    on the case, in creation order of the granting resource."""
    intervals = []
    # AuthorizationRequest approvals
    for ar in db.authorization_requests.values():
        if ar["case_id"] != case_id:
            continue
        if ar.get("certified_day_start") is not None and ar.get("certified_day_end") is not None:
            if ar["status"] == "APPROVED":
                intervals.append({
                    "start": ar["certified_day_start"],
                    "end": ar["certified_day_end"],
                    "level_of_care": ar["_interval_level"],
                    "source": ("auth", ar["id"], ar["created_at"]),
                })
    # ConcurrentReview approvals
    for cr in db.concurrent_reviews.values():
        auth = db.authorization_requests.get(cr["authorization_request_id"])
        if not auth or auth["case_id"] != case_id:
            continue
        if cr.get("certified_day_start") is not None and cr.get("certified_day_end") is not None:
            if cr["status"] in ("APPROVED", "PARTIALLY_APPROVED"):
                intervals.append({
                    "start": cr["certified_day_start"],
                    "end": cr["certified_day_end"],
                    "level_of_care": auth["_interval_level"],
                    "source": ("cr", cr["id"], cr["created_at"]),
                })
    intervals.sort(key=lambda i: i["source"][2])
    return intervals


def recompute_certified_counts(case):
    """Recompute certified_day_count / certified_inpatient_day_count /
    certified_observation_day_count from current intervals. Caller touches case."""
    intervals = certified_intervals(case["id"])
    total = 0
    inp = 0
    obs = 0
    for iv in intervals:
        length = iv["end"] - iv["start"]
        total += length
        if iv["level_of_care"] == "INPATIENT":
            inp += length
        else:
            obs += length
    case["certified_day_count"] = total
    case["certified_inpatient_day_count"] = inp
    case["certified_observation_day_count"] = obs


def intervals_overlap(case_id, start, end):
    """Half-open [start, end) overlap check; adjacency (start == existing end) allowed."""
    for iv in certified_intervals(case_id):
        if start < iv["end"] and end > iv["start"]:
            return True
    return False


def case_frontier_end(case_id):
    """Highest existing certified end on the case (1 when none — certified
    intervals live on a 1-based hospital-day index per PRD §2.9, so the
    frontier of an empty case is the first hospital day, day 1)."""
    intervals = certified_intervals(case_id)
    if not intervals:
        return 1
    return max(iv["end"] for iv in intervals)


# ---------------------------------------------------------------------------
# Avoidable-day attribution
# ---------------------------------------------------------------------------

def recompute_attribution(case, day_date):
    """Re-run attribution for one (case, day_date) group per the payer's method.
    Only records with status != OVERTURNED participate."""
    payer = db.payers[case["payer_id"]]
    group = [
        a for a in db.avoidable_days.values()
        if a["case_id"] == case["id"] and a["day_date"] == day_date and a["status"] != "OVERTURNED"
    ]
    if not group:
        return
    if payer["avoidable_attribution_method"] == "FIRST_CAUSE":
        owner = min(group, key=lambda a: (a["created_at"], a["barrier_code"]))
    else:  # DOMINANT_CAUSE
        owner = min(group, key=lambda a: (-a["barrier_weight"], a["created_at"], a["barrier_code"]))
    for a in group:
        a["is_attributed"] = (a["id"] == owner["id"])


def recompute_open_counts_and_escalation(case):
    """Recompute open_avoidable_day_count, escalation_tier; create/upgrade
    EscalationCase when raw tier thresholds are crossed. Does NOT touch case."""
    open_dates = {
        a["day_date"]
        for a in db.avoidable_days.values()
        if a["case_id"] == case["id"] and a["status"] == "OPEN"
    }
    raw_count = len(open_dates)
    case["open_avoidable_day_count"] = raw_count
    raw_tier = tier_of(raw_count)
    case["escalation_tier"] = raw_tier

    active = next(
        (e for e in db.escalation_cases.values()
         if e["case_id"] == case["id"] and e["status"] in ("OPEN", "ACKNOWLEDGED")),
        None,
    )
    if raw_tier >= 1 and active is None:
        from services.common import init_common
        esc = {
            **init_common(),
            "case_id": case["id"],
            "tier": raw_tier,
            "trigger_open_day_count": raw_count,
            "director_credit_days": 0,
            "effective_tier": raw_tier,
            "status": "OPEN",
            "resolution_note": None,
        }
        db.escalation_cases[esc["id"]] = esc
    elif active is not None and raw_tier > active["tier"]:
        active["tier"] = raw_tier
        _recompute_effective_tier(active, raw_count)


def _recompute_effective_tier(esc, raw_count):
    net = max(0, raw_count - esc["director_credit_days"])
    esc["effective_tier"] = tier_of(net)


def refresh_escalation_effective(case):
    """Recompute effective_tier of any active escalation from the current raw count."""
    active = next(
        (e for e in db.escalation_cases.values()
         if e["case_id"] == case["id"] and e["status"] in ("OPEN", "ACKNOWLEDGED")),
        None,
    )
    if active is not None:
        _recompute_effective_tier(active, case["open_avoidable_day_count"])


# ---------------------------------------------------------------------------
# Lazy materialization
# ---------------------------------------------------------------------------

def maybe_expire_conference(conf):
    """Materialize EXPIRED when now > window_deadline_at and status SCHEDULED."""
    if conf["status"] != "SCHEDULED":
        return False
    if logical_now() > parse_iso(conf["window_deadline_at"]):
        conf["status"] = "EXPIRED"
        from services.common import touch
        touch(conf)
        # linked DenialCase P2P_SCHEDULED -> OPEN (deadline unchanged)
        denial = _denial_for_auth(conf["authorization_request_id"])
        if denial is not None and denial["status"] == "P2P_SCHEDULED":
            denial["status"] = "OPEN"
            touch(denial)
        auth = db.authorization_requests[conf["authorization_request_id"]]
        case = db.utilization_cases[auth["case_id"]]
        from services.common import append_audit
        append_audit(case["id"], "P2P_EXPIRED", "system", "system",
                     f"Conference {conf['id']} expired after window deadline")
        return True
    return False


def maybe_close_denial(denial):
    """Materialize CLOSED_NO_APPEAL when now > appeal_deadline_at and status OPEN."""
    if denial["status"] != "OPEN":
        return False
    if logical_now() > parse_iso(denial["appeal_deadline_at"]):
        denial["status"] = "CLOSED_NO_APPEAL"
        from services.common import touch
        touch(denial)
        from services.common import append_audit
        append_audit(denial["case_id"], "DENIAL_CLOSED_NO_APPEAL", "system", "system",
                     f"Denial {denial['id']} closed: appeal deadline passed")
        return True
    return False


def _denial_for_auth(auth_request_id):
    for d in db.denial_cases.values():
        if d["authorization_request_id"] == auth_request_id:
            return d
    return None


def denial_is_final(denial):
    """True when denial is OPEN and no linked PeerToPeerConference is SCHEDULED."""
    if denial["status"] != "OPEN":
        return False
    for conf in db.peer_to_peer_conferences.values():
        if conf["authorization_request_id"] == denial["authorization_request_id"]:
            maybe_expire_conference(conf)
            if conf["status"] == "SCHEDULED":
                return False
    return True
