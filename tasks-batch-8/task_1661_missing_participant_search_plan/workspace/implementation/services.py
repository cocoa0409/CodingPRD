"""Domain services: serializers (computed fields derived on read), the case
ledger, the locate/restoration cascade, the stale-check sweep, and shared
lookups. All rules trace to PRD section 3 and SCAFFOLD sections 1.2-1.3."""

from datetime import timedelta

import db
from util import days_between, rhu

# ---------------------------------------------------------------------------
# Domain constants (SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------

WITHHOLDING_RATE_NUM = 20
WITHHOLDING_RATE_DEN = 100
WITHHOLDING_FLOOR_CENTS = 20000
CASHOUT_LIMIT_CENTS = 100000
FORCED_ROLLOVER_LIMIT_CENTS = 500000
ADJUSTMENT_RATE_NUM = 45
ADJUSTMENT_RATE_DEN = 1000
ADJUSTMENT_YEAR_DAYS = 365
STALE_CHECK_DAYS = 90
CERTIFIED_MAIL_BUFFER_DAYS = 15
DEFAULT_TREATMENT_LAG_DAYS = 30
NOIT_MIN_DAYS = 60
NOIT_MAX_DAYS = 90
INTERESTED_PARTY_MIN_DAYS = 10
INTERESTED_PARTY_MAX_DAYS = 24
BLACKOUT_ADVISORY_MIN_DAYS = 30
BLACKOUT_ADVISORY_MAX_DAYS = 60

RESOLVED_DISTRIBUTION_STATES = {
    "PAID_OUT",
    "AUTO_ROLLED_OVER",
    "PBGC_TRANSFERRED",
    "FORFEITED",
}

SEARCH_STEP_STATES = [
    "STEP1_COMMERCIAL_LOCATOR",
    "STEP2_PUBLIC_RECORDS",
    "STEP3_CREDIT_BUREAU",
    "STEP4_CERTIFIED_MAIL",
]

STEP_METHOD = {
    "STEP1_COMMERCIAL_LOCATOR": "COMMERCIAL_LOCATOR",
    "STEP2_PUBLIC_RECORDS": "PUBLIC_RECORDS",
    "STEP3_CREDIT_BUREAU": "CREDIT_BUREAU",
    "STEP4_CERTIFIED_MAIL": "CERTIFIED_MAIL",
}

ROLLOVER_METHODS = {
    "DIRECT_ROLLOVER_IRA",
    "DIRECT_ROLLOVER_QUALIFIED_PLAN",
    "AUTO_ROLLOVER_IRA",
}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def case_participants(case_id):
    return [
        p for p in db.all_of("participants")
        if p["termination_case_id"] == case_id
    ]


def case_blackouts(case_id):
    return [
        b for b in db.all_of("blackouts")
        if b["termination_case_id"] == case_id
    ]


def case_notices(case_id):
    return [
        n for n in db.all_of("notices")
        if n["termination_case_id"] == case_id
    ]


def case_blackout_active(case_id):
    return any(b["status"] == "ACTIVE" for b in case_blackouts(case_id))


def live_notice(case_id, notice_type):
    """The non-superseded notice of the given type on the case, if any."""
    live = [
        n for n in case_notices(case_id)
        if n["notice_type"] == notice_type and n["superseded_by_id"] is None
    ]
    return live[-1] if live else None


def participant_search_case(participant_id):
    """At most one MissingSearchCase ever exists per participant."""
    cases = [
        sc for sc in db.all_of("search_cases")
        if sc["participant_id"] == participant_id
    ]
    return cases[-1] if cases else None


def participant_transfers(participant_id):
    return [
        t for t in db.all_of("transfers")
        if t["participant_id"] == participant_id
    ]


def participant_forfeitures(participant_id):
    return [
        f for f in db.all_of("forfeitures")
        if f["participant_id"] == participant_id
    ]


def participant_payouts(participant_id):
    return [
        p for p in db.all_of("payouts")
        if p["participant_id"] == participant_id
    ]


def search_case_attempts(search_case_id):
    return [
        a for a in db.all_of("attempts")
        if a["search_case_id"] == search_case_id
    ]


# ---------------------------------------------------------------------------
# Computed money fields
# ---------------------------------------------------------------------------

def vested_balance(participant):
    """round_half_up(account_balance_cents * vested_pct / 100)."""
    return rhu(
        participant["account_balance_cents"] * participant["vested_pct"], 100
    )


def net_distributable(participant):
    return vested_balance(participant) - participant["_expense_share_cents"]


def _case_transfer_rows(case_id):
    pids = {p["id"] for p in case_participants(case_id)}
    return [t for t in db.all_of("transfers") if t["participant_id"] in pids]


def _case_forfeiture_rows(case_id):
    pids = {p["id"] for p in case_participants(case_id)}
    return [f for f in db.all_of("forfeitures") if f["participant_id"] in pids]


def _case_payout_rows(case_id):
    pids = {p["id"] for p in case_participants(case_id)}
    return [p for p in db.all_of("payouts") if p["participant_id"] in pids]


def sponsor_contribution_cents(case):
    """Sponsor-funded injections: PBGC make-whole excesses plus
    EARNINGS_ADJUSTED restoration earnings parts."""
    total = 0
    for t in _case_transfer_rows(case["id"]):
        if t["status"] == "ACCEPTED":
            total += t["_excess_cents"]
    for f in _case_forfeiture_rows(case["id"]):
        if f["status"] == "RESTORED":
            total += f["restoration_amount_cents"] - f["forfeited_amount_cents"]
    return total


def case_ledger(case):
    """Derived ledger fields for a TerminationCase (all computed on read)."""
    sponsor = sponsor_contribution_cents(case)
    total_assets = case["_base_assets_cents"] + sponsor
    paid = sum(
        p["gross_cents"] for p in _case_payout_rows(case["id"])
        if p["status"] == "CLEARED"
    )
    pbgc = sum(
        t["amount_cents"] for t in _case_transfer_rows(case["id"])
        if t["status"] == "ACCEPTED"
    )
    forfeited = sum(
        f["forfeited_amount_cents"] for f in _case_forfeiture_rows(case["id"])
        if f["status"] == "RECORDED"
    )
    expense = sum(
        x["total_expense_cents"] for x in db.all_of("expenses")
        if x["termination_case_id"] == case["id"]
    )
    remaining = total_assets - paid - pbgc - forfeited - expense
    return {
        "sponsor_contribution_cents": sponsor,
        "total_plan_assets_cents": total_assets,
        "paid_out_cents": paid,
        "pbgc_transferred_cents": pbgc,
        "forfeited_cents": forfeited,
        "expense_paid_cents": expense,
        "remaining_undistributed_cents": remaining,
    }


def default_treatment_date(case):
    """Live DISTRIBUTION notice's action_effective_date + 30 days; null until
    a DISTRIBUTION notice is issued; recomputed on supersede."""
    notice = live_notice(case["id"], "DISTRIBUTION")
    if notice is None:
        return None
    return notice["action_effective_date"] + timedelta(
        days=DEFAULT_TREATMENT_LAG_DAYS
    )


# ---------------------------------------------------------------------------
# Serializers (datetime fields rendered with three fractional digits)
# ---------------------------------------------------------------------------

def _strip(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def public_case(case):
    ps = case_participants(case["id"])
    total = len(ps)
    resolved = sum(
        1 for p in ps if p["distribution_status"] in RESOLVED_DISTRIBUTION_STATES
    )
    missing = sum(1 for p in ps if p["locate_status"] == "MISSING")
    out = _strip(case)
    out["proposed_termination_date"] = db.fmt_ts(case["proposed_termination_date"])
    out["created_at"] = db.fmt_ts(case["created_at"])
    out["updated_at"] = db.fmt_ts(case["updated_at"])
    out["total_participant_count"] = total
    out["resolved_participant_count"] = resolved
    out["missing_participant_count"] = missing
    out["all_participants_resolved"] = total > 0 and resolved == total
    out["blackout_active"] = case_blackout_active(case["id"])
    dtd = default_treatment_date(case)
    out["default_treatment_date"] = db.fmt_ts(dtd) if dtd is not None else None
    out.update(case_ledger(case))
    return out


def public_participant(p):
    out = _strip(p)
    for f in ("flagged_at", "declared_missing_at", "located_at",
              "created_at", "updated_at"):
        out[f] = db.fmt_ts(p[f]) if p[f] is not None else None
    out["created_at"] = db.fmt_ts(p["created_at"])
    out["updated_at"] = db.fmt_ts(p["updated_at"])
    out["vested_balance_cents"] = vested_balance(p)
    out["termination_expense_share_cents"] = p["_expense_share_cents"]
    out["net_distributable_cents"] = net_distributable(p)
    out["restoration_credit_cents"] = p["_restoration_credit_cents"]
    return out


def public_search_case(sc):
    out = _strip(sc)
    for f in ("opened_at", "resolved_at", "exhausted_at",
              "created_at", "updated_at"):
        out[f] = db.fmt_ts(sc[f]) if sc[f] is not None else None
    out["created_at"] = db.fmt_ts(sc["created_at"])
    out["updated_at"] = db.fmt_ts(sc["updated_at"])
    out["attempt_count"] = len(search_case_attempts(sc["id"]))
    return out


def public_attempt(a):
    out = _strip(a)
    out["attempted_at"] = db.fmt_ts(a["attempted_at"])
    out["created_at"] = db.fmt_ts(a["created_at"])
    return out


def public_notice(n):
    out = _strip(n)
    for f in ("issued_at", "action_effective_date", "created_at", "updated_at"):
        out[f] = db.fmt_ts(n[f]) if n[f] is not None else None
    return out


def public_blackout(b):
    out = _strip(b)
    for f in ("start_at", "end_at", "activated_at", "completed_at",
              "created_at", "updated_at"):
        out[f] = db.fmt_ts(b[f]) if b[f] is not None else None
    return out


def public_election(e):
    out = _strip(e)
    out["created_at"] = db.fmt_ts(e["created_at"])
    out["updated_at"] = db.fmt_ts(e["updated_at"])
    return out


def public_payout(pay):
    out = _strip(pay)
    for f in ("issued_at", "cleared_at", "stale_marked_at",
              "created_at", "updated_at"):
        out[f] = db.fmt_ts(pay[f]) if pay[f] is not None else None
    out["created_at"] = db.fmt_ts(pay["created_at"])
    out["updated_at"] = db.fmt_ts(pay["updated_at"])
    return out


def public_transfer(t):
    out = _strip(t)
    for f in ("submitted_at", "confirmed_at", "created_at", "updated_at"):
        out[f] = db.fmt_ts(t[f]) if t[f] is not None else None
    return out


def public_forfeiture(f):
    out = _strip(f)
    for f_ in ("restored_at", "created_at", "updated_at"):
        out[f_] = db.fmt_ts(f[f_]) if f[f_] is not None else None
    return out


def public_dlr(d):
    out = _strip(d)
    for f in ("intended_filing_date", "filed_at", "created_at", "updated_at"):
        out[f] = db.fmt_ts(d[f]) if d[f] is not None else None
    return out


def public_log(entry):
    out = _strip(entry)
    out["created_at"] = db.fmt_ts(entry["created_at"])
    return out


def public_expense(x):
    out = _strip(x)
    out["created_at"] = db.fmt_ts(x["created_at"])
    out["updated_at"] = db.fmt_ts(x["updated_at"])
    return out


# ---------------------------------------------------------------------------
# Payout creation (net_payout_withholding, SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------

def compute_withholding(method, gross_cents):
    if method == "LUMP_SUM_CHECK" and gross_cents >= WITHHOLDING_FLOOR_CENTS:
        return rhu(gross_cents * WITHHOLDING_RATE_NUM, WITHHOLDING_RATE_DEN)
    return 0


def create_payout(participant, source, method, election_id):
    """gross = net_distributable + restoration_credit at creation; creating
    the payout consumes the credit (resets it to 0)."""
    gross = net_distributable(participant) + participant["_restoration_credit_cents"]
    participant["_restoration_credit_cents"] = 0
    withholding = compute_withholding(method, gross)
    blackout = case_blackout_active(participant["termination_case_id"])
    issued = not blackout
    return db.new_entity("payouts", {
        "participant_id": participant["id"],
        "distribution_election_id": election_id,
        "source": source,
        "method": method,
        "gross_cents": gross,
        "withholding_cents": withholding,
        "net_cents": gross - withholding,
        "status": "PREPARED" if blackout else "ISSUED",
        "issued_at": db.now() if issued else None,
        "cleared_at": None,
        "stale_marked_at": None,
    })


# ---------------------------------------------------------------------------
# The locate cascade (PRD section 3.3/3.4, four hops)
# ---------------------------------------------------------------------------

def locate_participant(participant):
    """MISSING -> LOCATED; resolves the open search case; when the participant
    is FORFEITED, fires the restoration cascade (hops 2-4)."""
    ts = db.now()
    participant["locate_status"] = "LOCATED"
    participant["located_at"] = ts
    db.touch(participant)

    sc = (
        db.get("search_cases", participant["active_search_case_id"])
        if participant["active_search_case_id"]
        else None
    )
    if sc is not None and sc["status"] in SEARCH_STEP_STATES:
        sc["status"] = "RESOLVED"
        sc["resolved_at"] = ts
        db.touch(sc)
        participant["active_search_case_id"] = None

    if participant["distribution_status"] == "FORFEITED":
        # Hop 2: FORFEITED -> RESTORED.
        participant["distribution_status"] = "RESTORED"
        db.touch(participant)
        # Hop 3: the RECORDED forfeiture -> RESTORED with computed amount.
        recorded = [
            f for f in participant_forfeitures(participant["id"])
            if f["status"] == "RECORDED"
        ]
        if recorded:
            forfeiture = recorded[-1]
            case = db.get("cases", participant["termination_case_id"])
            elapsed_days = max(
                0, days_between(forfeiture["created_at"], ts)
            )
            earnings = 0
            if case["restoration_policy"] == "EARNINGS_ADJUSTED":
                earnings = rhu(
                    forfeiture["forfeited_amount_cents"]
                    * ADJUSTMENT_RATE_NUM
                    * elapsed_days,
                    ADJUSTMENT_RATE_DEN * ADJUSTMENT_YEAR_DAYS,
                )
            forfeiture["restoration_amount_cents"] = (
                forfeiture["forfeited_amount_cents"] + earnings
            )
            forfeiture["restored_at"] = ts
            forfeiture["status"] = "RESTORED"
            db.touch(forfeiture)
            # Hop 4: ledger repair is derived on read; the earnings part is
            # sponsor-funded and waits in restoration_credit_cents for the
            # participant's next payout.
            if earnings > 0:
                participant["_restoration_credit_cents"] += earnings
    return participant


# ---------------------------------------------------------------------------
# Stale-check sweep (PRD section 3.6; runs after every clock set)
# ---------------------------------------------------------------------------

def stale_check_sweep():
    now = db.now()
    candidates = [
        pay for pay in db.all_of("payouts")
        if pay["status"] == "ISSUED" and pay["method"] == "LUMP_SUM_CHECK"
    ]
    candidates.sort(key=lambda pay: (pay["issued_at"], pay["_seq"]))
    for pay in candidates:
        if now >= pay["issued_at"] + timedelta(days=STALE_CHECK_DAYS):
            pay["status"] = "STALE_UNCASHED"
            pay["stale_marked_at"] = now
            db.touch(pay)
            participant = db.get("participants", pay["participant_id"])
            if participant is not None and participant["locate_status"] == "UNVERIFIED":
                participant["locate_status"] = "FLAGGED_UNCASHED"
                participant["flagged_at"] = now
                db.touch(participant)
