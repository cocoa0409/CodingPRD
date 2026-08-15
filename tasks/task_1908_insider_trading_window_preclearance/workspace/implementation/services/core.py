"""Core domain services: entity helpers, computed flags, screens, cascades,
matching pass, severity scoring, merge rule, and the compliance sweep."""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE
from errors import err, not_found, ERR_NOT_FOUND
from util import fmt_ts, dec, rhu2, TWO_DP

# --- Constants (scaffold calculations) ---
APPROVAL_TTL_HOURS = 48
EXCEPTION_DECISION_WINDOW_DAYS = 5
COOLING_OFF_STANDARD_DAYS = 30
COOLING_OFF_EXECUTIVE_DAYS = 90
EARNINGS_BUFFER_DAYS = 2
CURRENCY_WINDOW_DAYS = 365
QUORUM = 2
BASE_POINTS = {"BLACKOUT_TRADE": 40, "NO_PRECLEARANCE": 25, "RESTRICTED_LIST": 50,
               "PLAN_VIOLATION": 30, "OTHER": 15}
REPEAT_BONUS = 15
VALUE_BAND_HIGH = 100000
VALUE_BAND_MID = 25000
SCORE_CAP = 100
EXECUTIVE_DESIGNATIONS = {"SECTION_16_OFFICER", "DIRECTOR"}
OPEN_CASE_STATES = {"OPENED", "UNDER_INVESTIGATION", "ESCALATED", "SUBSTANTIATED", "SANCTION_RECORDED"}

DESIGNATIONS = {"SECTION_16_OFFICER", "DIRECTOR", "EMPLOYEE", "CONSULTANT"}
DEAL_TYPES = {"MERGER", "ACQUISITION", "DIVESTITURE", "FINANCING", "RESTRUCTURING"}
TRADE_SIDES = {"BUY", "SELL"}
WINDOW_KINDS = {"QUARTERLY", "EVENT_DRIVEN"}
FISCAL_QUARTERS = {"Q1", "Q2", "Q3", "Q4"}
VIOLATION_TYPES = {"BLACKOUT_TRADE", "NO_PRECLEARANCE", "RESTRICTED_LIST", "PLAN_VIOLATION", "OTHER"}
ATTESTATION_KINDS = {"POLICY_ACK", "ANNUAL_TRAINING"}


# ---------------------------------------------------------------------------
# Base entity helpers
# ---------------------------------------------------------------------------

def new_entity():
    eid = str(uuid.uuid4())
    now = fmt_ts(STORE.clock)
    return {"id": eid, "created_at": now, "updated_at": now, "version": 1,
            "_seq": STORE.next_seq(), "_created_dt": STORE.clock}


def touch(e):
    e["updated_at"] = fmt_ts(STORE.clock)
    e["version"] = e.get("version", 1) + 1


def serialize(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def sort_created(items):
    return sorted(items, key=lambda e: (e["_created_dt"], e["_seq"]))


def get_or_404(table, rid, what):
    e = STORE.__dict__[table].get(rid)
    if e is None:
        raise not_found(what)
    return e


# ---------------------------------------------------------------------------
# CoveredPerson computed flags (PRD section 3.1)
# ---------------------------------------------------------------------------

def compute_flags(person):
    now = STORE.clock
    since = now - timedelta(days=CURRENCY_WINDOW_DAYS)
    ack = False
    training_done = False
    training_overdue = False
    for a in STORE.attestations.values():
        if a["covered_person_id"] != person["id"]:
            continue
        if a["kind"] == "POLICY_ACK" and a["status"] == "COMPLETED" \
                and a["_completed_dt"] is not None and since <= a["_completed_dt"] <= now:
            ack = True
        if a["kind"] == "ANNUAL_TRAINING":
            if a["status"] == "COMPLETED" and a["_completed_dt"] is not None \
                    and since <= a["_completed_dt"] <= now:
                training_done = True
            if a["status"] == "OVERDUE":
                training_overdue = True
    hold = any(c["covered_person_id"] == person["id"] and c["status"] in OPEN_CASE_STATES
               for c in STORE.violation_cases.values())
    return ack, (training_done and not training_overdue), hold


def apply_flags(person, force_touch=False):
    """Store freshly computed flags; bump version when they change (a server
    mutation) or when force_touch is set (attestation completion)."""
    ack, training, hold = compute_flags(person)
    changed = (person["policy_ack_current"] != ack
               or person["training_current"] != training
               or person["compliance_hold"] != hold)
    person["policy_ack_current"] = ack
    person["training_current"] = training
    person["compliance_hold"] = hold
    if changed or force_touch:
        touch(person)


def serialize_person(p):
    d = serialize(p)
    ack, training, hold = compute_flags(p)
    d["policy_ack_current"] = ack
    d["training_current"] = training
    d["compliance_hold"] = hold
    return d


# ---------------------------------------------------------------------------
# Screens shared by preclearance submission / decision / void / matching
# ---------------------------------------------------------------------------

def window_applies(window, ticker):
    return window["kind"] == "QUARTERLY" or window["security_ticker"] == ticker


def window_covers(window, instant):
    return window["_start_dt"] <= instant < window["_end_dt"]


def ticker_restricted(ticker):
    return any(e["status"] == "ACTIVE" and e["security_ticker"] == ticker
               for e in STORE.restricted_entries.values())


def exception_bypass(request_dict):
    """True iff the request cites an APPROVED exception for the same ticker
    covering at least the request's quantity."""
    eid = request_dict.get("exception_id")
    if not eid:
        return False
    ex = STORE.exception_requests.get(eid)
    if ex is None or ex["status"] != "APPROVED":
        return False
    if ex["security_ticker"] != request_dict["security_ticker"]:
        return False
    return dec(ex["quantity"]) >= dec(request_dict["quantity"])


def blackout_blocked(ticker, proposed_dt):
    """Provisional blackout verdict against the calendar as it stands now."""
    for w in STORE.blackout_windows.values():
        if w["status"] in ("SCHEDULED", "ACTIVE") and window_applies(w, ticker) \
                and window_covers(w, proposed_dt):
            return True
    return False


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def auto_deny_pending(ticker):
    """Deal activation / manual restricted entry: pending requests on the
    ticker in SUBMITTED or UNDER_REVIEW are denied RESTRICTED_LIST."""
    for r in sort_created(STORE.preclearance_requests.values()):
        if r["security_ticker"] == ticker and r["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            r["status"] = "DENIED"
            r["denial_reason"] = "RESTRICTED_LIST"
            touch(r)


def merge_event_window(candidate):
    """Blackout interval merge for a newly created EVENT_DRIVEN window.

    Survivors: existing SCHEDULED/ACTIVE EVENT_DRIVEN windows on the same
    ticker whose intervals overlap or touch (gap == 0) the candidate. The
    survivor with the earliest start_at (tie: created_at ASC) absorbs: it
    takes the min start and max end across itself, the candidate, and every
    other touching survivor; other survivors and the candidate become MERGED
    into it. No survivors -> candidate stays SCHEDULED.
    """
    ticker = candidate["security_ticker"]
    c_start, c_end = candidate["_start_dt"], candidate["_end_dt"]
    survivors = [w for w in STORE.blackout_windows.values()
                 if w["id"] != candidate["id"]
                 and w["kind"] == "EVENT_DRIVEN"
                 and w["security_ticker"] == ticker
                 and w["status"] in ("SCHEDULED", "ACTIVE")
                 and c_start <= w["_end_dt"] and c_end >= w["_start_dt"]]
    if not survivors:
        return
    survivors.sort(key=lambda w: (w["_start_dt"], w["_created_dt"], w["_seq"]))
    primary = survivors[0]
    new_start = min([c_start] + [w["_start_dt"] for w in survivors])
    new_end = max([c_end] + [w["_end_dt"] for w in survivors])
    primary["_start_dt"] = new_start
    primary["start_at"] = fmt_ts(new_start)
    primary["_end_dt"] = new_end
    primary["end_at"] = fmt_ts(new_end)
    touch(primary)
    for w in survivors[1:]:
        w["status"] = "MERGED"
        w["merged_into_id"] = primary["id"]
        touch(w)
    candidate["status"] = "MERGED"
    candidate["merged_into_id"] = primary["id"]


def create_event_window(ticker, start_dt, end_dt, deal_id=None):
    w = new_entity()
    w.update({
        "kind": "EVENT_DRIVEN",
        "fiscal_year": None,
        "fiscal_quarter": None,
        "security_ticker": ticker,
        "deal_id": deal_id,
        "start_at": fmt_ts(start_dt),
        "end_at": fmt_ts(end_dt),
        "status": "SCHEDULED",
        "merged_into_id": None,
        "applicability_note": f"EVENT_DRIVEN window applies to {ticker} only",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    STORE.blackout_windows[w["id"]] = w
    merge_event_window(w)
    return w


def void_cascade(window):
    """BlackoutWindow SCHEDULED -> ACTIVE cascade (final validity verdict):
    void APPROVED requests covered by this window when the window was created
    after the request's decision and no exception bypass protects them."""
    voided = 0
    for r in sort_created(STORE.preclearance_requests.values()):
        if r["status"] != "APPROVED":
            continue
        if not window_applies(window, r["security_ticker"]):
            continue
        if not window_covers(window, r["_proposed_dt"]):
            continue
        if not (window["_created_dt"] > r["_decided_dt"]):
            continue
        if exception_bypass(r):
            continue
        r["status"] = "VOIDED"
        for c in sort_created(STORE.trade_confirmations.values()):
            if c["match_preclearance_id"] == r["id"] and c["status"] == "MATCHED_PRECLEARANCE":
                c["status"] = "RECEIVED"
                c["match_preclearance_id"] = None
                touch(c)
        r["matched_quantity"] = 0
        r["remaining_quantity"] = r["quantity"]
        touch(r)
        voided += 1
    return voided


# ---------------------------------------------------------------------------
# Trade confirmation matching pass (PRD section 3.7)
# ---------------------------------------------------------------------------

def matching_pass(conf):
    """Run the preclearance lane, then the plan lane, else flag + auto-open a
    violation case + recompute the compliance hold. Mutates in place."""
    # --- Lane 1: preclearance ---
    cands = []
    for r in STORE.preclearance_requests.values():
        if r["status"] != "APPROVED":
            continue
        if r["covered_person_id"] != conf["covered_person_id"]:
            continue
        if r["security_ticker"] != conf["security_ticker"] or r["trade_side"] != conf["trade_side"]:
            continue
        if not (r["_decided_dt"] <= conf["_trade_date_dt"] <= r["_approval_valid_until_dt"]):
            continue
        if dec(r["remaining_quantity"]) < dec(conf["quantity"]):
            continue
        cands.append(r)
    if cands:
        cands.sort(key=lambda r: (r["_decided_dt"], r["_created_dt"], r["_seq"]))
        r = cands[0]
        applied = dec(min(dec(conf["quantity"]), dec(r["remaining_quantity"]))).quantize(
            TWO_DP, rounding=ROUND_HALF_UP)
        r["matched_quantity"] = float((dec(r["matched_quantity"]) + applied).quantize(
            TWO_DP, rounding=ROUND_HALF_UP))
        r["remaining_quantity"] = float((dec(r["remaining_quantity"]) - applied).quantize(
            TWO_DP, rounding=ROUND_HALF_UP))
        conf["status"] = "MATCHED_PRECLEARANCE"
        conf["match_preclearance_id"] = r["id"]
        if dec(r["remaining_quantity"]) == 0:
            r["status"] = "CLOSED"
        touch(r)
        return

    # --- Lane 2: 10b5-1 plan ---
    plans = [p for p in STORE.tenb5_plans.values()
             if p["status"] == "ACTIVE"
             and p["covered_person_id"] == conf["covered_person_id"]
             and p["security_ticker"] == conf["security_ticker"]
             and conf["_trade_date_dt"] >= p["_cooling_off_end_dt"]
             and conf["_trade_date_dt"] >= p["_first_trade_dt"]]
    if plans:
        plans.sort(key=lambda p: (p["_approved_at_dt"], p["_created_dt"], p["_seq"]))
        conf["status"] = "MATCHED_PLAN"
        conf["match_plan_id"] = plans[0]["id"]
        return

    # --- Lane 3: flag ---
    if any(w["status"] == "ACTIVE" and window_applies(w, conf["security_ticker"])
           and window_covers(w, conf["_trade_date_dt"]) for w in STORE.blackout_windows.values()):
        reason = "BLACKOUT_TRADE"
    elif ticker_restricted(conf["security_ticker"]):
        reason = "RESTRICTED_LIST"
    else:
        reason = "NO_PRECLEARANCE"
    conf["status"] = "FLAGGED"
    conf["flagged_reason"] = reason
    # Auto-open a violation case unless an open case already references this
    # confirmation (in sweep re-match the duplicate attempt is skipped, not
    # raised; the 409 applies to the manual endpoint).
    if not any(c["trade_confirmation_id"] == conf["id"] and c["status"] != "CLOSED"
               for c in STORE.violation_cases.values()):
        case = new_entity()
        case.update({
            "covered_person_id": conf["covered_person_id"],
            "trade_confirmation_id": conf["id"],
            "violation_type": reason,
            "source": "AUTO_FLAG",
            "status": "OPENED",
            "severity_score": None,
            "sanction": None,
            "sanction_recorded_at": None,
            "note": None,
            "_sanction_recorded_dt": None,
        })
        STORE.violation_cases[case["id"]] = case
    person = STORE.covered_persons.get(conf["covered_person_id"])
    if person is not None:
        apply_flags(person)


# ---------------------------------------------------------------------------
# Severity scoring (PRD section 3.8)
# ---------------------------------------------------------------------------

def compute_severity(case):
    base = BASE_POINTS[case["violation_type"]]
    repeat_count = sum(
        1 for c in STORE.violation_cases.values()
        if c["id"] != case["id"]
        and c["covered_person_id"] == case["covered_person_id"]
        and c["status"] in ("SANCTION_RECORDED", "CLOSED")
        and c["sanction"] is not None)
    value_bonus = 0
    tcid = case.get("trade_confirmation_id")
    if tcid:
        conf = STORE.trade_confirmations.get(tcid)
        if conf is not None:
            tv = dec(conf["trade_value"])
            if tv >= dec(VALUE_BAND_HIGH):
                value_bonus = 20
            elif tv >= dec(VALUE_BAND_MID):
                value_bonus = 10
    person = STORE.covered_persons.get(case["covered_person_id"])
    designation_bonus = 10 if person is not None and person["designation"] in EXECUTIVE_DESIGNATIONS else 0
    return min(SCORE_CAP, base + REPEAT_BONUS * repeat_count + value_bonus + designation_bonus)


def sanction_for_score(score):
    if score >= 75:
        return "TERMINATION_REFERRAL"
    if score >= 50:
        return "SUSPENSION_90D"
    if score >= 25:
        return "SUSPENSION_30D"
    return "WARNING"
