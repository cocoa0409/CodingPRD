"""Domain logic: state machines, calculations, cascades, clock advancement.

All temporal behavior is driven by each cooperative's logical clock
(`current_utc`), never by wall-clock time.
"""
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, new_id, next_seq
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_CROSS_ENTITY_VIOLATION,
    ERR_FISCAL_THRESHOLD_VIOLATION,
    ERR_ALTERATION_SAFETY_VIOLATION,
)
from util import START_UTC

# Domain constants (PRD §3 / scaffold §1.3)
BOARD_SEATS = 5
VOTES_REQUIRED = 3                      # majority of the 5-seat board
DTI_MAX_BPS = 2800                      # 28%
MORTGAGE_RATE_ASSUMPTION_BPS = 700      # 7% APR assumption
MONTHS_LIQUIDITY_REQUIRED = 12
SUBLET_FEE_RATE_BPS = 1500              # 15%
FINANCING_CAP_BPS = 8000                # 80% max financing
SECONDS_PER_DAY = 86400
ALTERATION_MIN_INSURANCE_CENTS = 100000000  # $1M
ALTERATION_MIN_DEPOSIT_CENTS = 500000       # $5k
NO_SHOW_AFTER_SECONDS = 86400
MEETING_AUTO_ADJOURN_SECONDS = 86400

CURE_DAYS = {"LATE_NOTICE": 30, "DEMAND_LETTER": 15, "TERMINATION_NOTICE": 10}
NEXT_TIER = {"LATE_NOTICE": "DEMAND_LETTER", "DEMAND_LETTER": "TERMINATION_NOTICE"}

POLICY_FIELDS = (
    "flip_tax_policy", "flip_tax_percent_bps", "flip_tax_per_share_cents",
    "sublet_policy_years_max", "sublet_policy_gap_years",
    "arrears_late_fee_flat_cents", "arrears_interest_rate_bps",
    "arrears_grace_days", "arrears_termination_threshold_cents",
    "annual_meeting_quorum_percent_bps",
)

SUBJECT_STORES = {
    "PurchaseApplication": "purchase_applications",
    "ChargeSchedule": "charge_schedules",
    "SubletAgreement": "sublet_agreements",
    "AlterationAgreement": "alteration_agreements",
    "Shareholder": "shareholders",
    "Cooperative": "cooperatives",
}

APP_IN_FLIGHT = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "INTERVIEW_SCHEDULED", "APPROVED")
APP_TERMINAL = ("REJECTED", "WITHDRAWN", "TRANSFERRED")


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def rhu(numerator, denominator=1):
    """Round half-up of numerator/denominator to integer cents/shares."""
    d = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def ser(entity):
    """Serialize an entity dict: drop internal `_`-keys, format datetimes."""
    from util import fmt_iso
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_iso(v)
        else:
            out[k] = v
    return out


def make(kind, coop, **fields):
    """Create and register an entity with common fields (PRD §2.4)."""
    now = coop["current_utc"] if coop is not None else START_UTC
    e = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    STORE[kind][e["id"]] = e
    return e


def touch(e, coop):
    """Every mutation of an entity increments its version and refreshes updated_at."""
    e["version"] += 1
    if coop is not None:
        e["updated_at"] = coop["current_utc"]


def bump_coop(coop):
    """Aggregate-wide mutation counter (PRD §2.7)."""
    coop["version"] += 1
    coop["updated_at"] = coop["current_utc"]


def get_coop(cid):
    c = STORE["cooperatives"].get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "Cooperative %s not found" % cid, 404)
    return c


def get_scoped(kind, eid, cid, label):
    e = STORE[kind].get(eid)
    if e is None or e.get("cooperative_id") != cid:
        raise ApiError(ERR_NOT_FOUND, "%s %s not found" % (label, eid), 404)
    return e


def all_of(kind, cid=None):
    items = list(STORE[kind].values())
    if cid is not None:
        items = [e for e in items if e.get("cooperative_id") == cid]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return items


def windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Shareholder derived fields (PRD §3.1 / §3.4)
# ---------------------------------------------------------------------------

def owned_unit_ids(coop, sh_id):
    return {
        e["unit_id"]
        for e in STORE["share_ledger_entries"].values()
        if e["cooperative_id"] == coop["id"]
        and e["shareholder_id"] == sh_id
        and e["entry_status"] == "ACTIVE"
    }


def recompute_shareholder(coop, sh):
    """Recompute arrears_balance_cents and standing after any charge/payment write.

    PENDING charges are not yet issued and do not count toward arrears (PAID
    and WAIVED charges carry outstanding_cents of zero anyway).
    """
    cid = coop["id"]
    units = owned_unit_ids(coop, sh["id"])
    bal = sum(
        c["outstanding_cents"]
        for c in STORE["maintenance_charges"].values()
        if c["cooperative_id"] == cid
        and c["unit_id"] in units
        and c["charge_status"] != "PENDING"
    )
    changed = False
    if sh["arrears_balance_cents"] != bal:
        sh["arrears_balance_cents"] = bal
        changed = True
    if sh["standing"] != "TERMINATED":
        new_st = sh["standing"]
        if bal == 0:
            has_term_notice = any(
                a for a in STORE["arrears_actions"].values()
                if a["cooperative_id"] == cid
                and a["shareholder_id"] == sh["id"]
                and a["action_type"] == "TERMINATION_NOTICE"
                and a["action_status"] == "ISSUED"
            )
            new_st = "DELINQUENT" if has_term_notice else "GOOD_STANDING"
        else:
            if sh["standing"] == "GOOD_STANDING":
                past_due = any(
                    c for c in STORE["maintenance_charges"].values()
                    if c["cooperative_id"] == cid
                    and c["unit_id"] in units
                    and c["charge_status"] == "PAST_DUE"
                )
                if past_due:
                    new_st = "DELINQUENT"
            # DELINQUENT persists while balance > 0
        if new_st != sh["standing"]:
            sh["standing"] = new_st
            changed = True
    if changed:
        touch(sh, coop)


def cure_actions_if_zero(coop, sh, now):
    """ISSUED actions cure automatically when arrears hit zero before the deadline."""
    if sh["arrears_balance_cents"] != 0:
        return
    for a in STORE["arrears_actions"].values():
        if (
            a["cooperative_id"] == coop["id"]
            and a["shareholder_id"] == sh["id"]
            and a["action_status"] == "ISSUED"
            and now <= a["cure_deadline"]
        ):
            a["action_status"] = "CURED"
            touch(a, coop)


def recompute_all(coop):
    now = coop["current_utc"]
    for sh in all_of("shareholders", coop["id"]):
        recompute_shareholder(coop, sh)
        cure_actions_if_zero(coop, sh, now)


# ---------------------------------------------------------------------------
# Maintenance charges: issuance, past-due, interest (PRD §3.3 / §3.4)
# ---------------------------------------------------------------------------

def month_start_of(billing_month):
    y, m = billing_month.split("-")
    return datetime(int(y), int(m), 1, tzinfo=timezone.utc)


def grace_end(coop, ch):
    return ch["due_date"] + timedelta(days=coop["arrears_grace_days"])


def recompute_outstanding(ch):
    ch["outstanding_cents"] = max(
        0, ch["base_amount_cents"] + ch["late_fee_cents"] + ch["interest_cents"] - ch["paid_cents"]
    )


def accrue_interest(coop, ch, now):
    """Simple daily interest on outstanding principal (base + late_fee - paid).

    days = ceil(seconds past grace / 86400): a charge crossing the grace
    boundary by one second accrues one day on that first tick; exactly at the
    grace boundary nothing accrues. Interest never compounds onto interest.
    """
    if ch["charge_status"] != "PAST_DUE":
        return
    ge = grace_end(coop, ch)
    if now <= ge:
        return
    days = math.ceil((now - ge).total_seconds() / SECONDS_PER_DAY)
    accrued = ch.get("_interest_days", 0)
    if days <= accrued:
        return
    principal = ch["base_amount_cents"] + ch["late_fee_cents"] - ch["paid_cents"]
    per_day = rhu(
        Decimal(principal) * Decimal(coop["arrears_interest_rate_bps"]),
        Decimal(365 * 10000),
    )
    ch["interest_cents"] += per_day * (days - accrued)
    ch["_interest_days"] = days
    recompute_outstanding(ch)
    touch(ch, coop)


def enter_past_due(coop, ch, now):
    ch["charge_status"] = "PAST_DUE"
    if ch["late_fee_cents"] == 0:
        # Exactly one flat late fee, applied once on entering PAST_DUE.
        ch["late_fee_cents"] = coop["arrears_late_fee_flat_cents"]
    ch["_interest_days"] = 0
    recompute_outstanding(ch)
    touch(ch, coop)
    accrue_interest(coop, ch, now)


def evaluate_charge(coop, ch, now):
    """Advance a charge through its time-driven states against `now`."""
    if ch["charge_status"] == "PENDING":
        ms = month_start_of(ch["billing_month"])
        if now >= ms:
            ch["charge_status"] = "ISSUED"
            ch["due_date"] = ms
            touch(ch, coop)
    if ch["charge_status"] in ("ISSUED", "PARTIALLY_PAID"):
        if ch["outstanding_cents"] > 0 and now > grace_end(coop, ch):
            enter_past_due(coop, ch, now)
        elif ch["outstanding_cents"] == 0:
            ch["charge_status"] = "PAID"
            touch(ch, coop)
    if ch["charge_status"] == "PAST_DUE":
        accrue_interest(coop, ch, now)


# ---------------------------------------------------------------------------
# Charge schedule approval cascade (PRD §3.3)
# ---------------------------------------------------------------------------

def months_in_window(frm, to):
    """Month starts m with frm <= m < to."""
    cur = datetime(frm.year, frm.month, 1, tzinfo=timezone.utc)
    if cur < frm:
        if cur.month == 12:
            cur = datetime(cur.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            cur = datetime(cur.year, cur.month + 1, 1, tzinfo=timezone.utc)
    while cur < to:
        yield cur
        if cur.month == 12:
            cur = datetime(cur.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            cur = datetime(cur.year, cur.month + 1, 1, tzinfo=timezone.utc)


def compute_monthly_amounts(coop, sched):
    """maintenance_monthly_charge calculation with residual reconciliation."""
    units = all_of("units", coop["id"])
    if not units:
        return {}
    B = sched["annual_operating_budget_cents"]
    amounts = {}
    if sched["allocation_method"] == "PRO_RATA_SHARES":
        S = coop["total_shares"]
        for u in units:
            amounts[u["id"]] = rhu(Decimal(B) * u["shares_allocated"], Decimal(S * 12))
        # Largest unit absorbs the residual; tie-break earliest created_at.
        absorber = max(units, key=lambda u: (u["shares_allocated"], -u["_seq"]))
    else:  # EQUAL_SPLIT
        N = len(units)
        for u in units:
            amounts[u["id"]] = rhu(Decimal(B), Decimal(N * 12))
        absorber = min(units, key=lambda u: u["_seq"])
    residual = B - 12 * sum(amounts.values())
    amounts[absorber["id"]] += rhu(Decimal(residual), Decimal(12))
    return amounts


def generate_charges(coop, sched):
    amounts = compute_monthly_amounts(coop, sched)
    if not amounts:
        return
    now = coop["current_utc"]
    for ms in months_in_window(sched["effective_from"], sched["effective_to"]):
        bm = "%04d-%02d" % (ms.year, ms.month)
        for u in all_of("units", coop["id"]):
            ch = make(
                "maintenance_charges", coop,
                cooperative_id=coop["id"],
                unit_id=u["id"],
                schedule_id=sched["id"],
                billing_month=bm,
                due_date=ms,
                base_amount_cents=amounts[u["id"]],
                late_fee_cents=0,
                interest_cents=0,
                paid_cents=0,
                outstanding_cents=amounts[u["id"]],
                charge_status="PENDING",
                _interest_days=0,
            )
            evaluate_charge(coop, ch, now)


def approve_schedule(coop, sched, res):
    sched["schedule_status"] = "APPROVED"
    sched["approving_resolution_id"] = res["id"]
    touch(sched, coop)
    new_month = "%04d-%02d" % (sched["effective_from"].year, sched["effective_from"].month)
    # Replacement: overlapping APPROVED schedules are superseded; their
    # not-yet-due charges in PENDING/ISSUED/PARTIALLY_PAID are waived.
    for other in all_of("charge_schedules", coop["id"]):
        if other["id"] == sched["id"] or other["schedule_status"] != "APPROVED":
            continue
        if windows_overlap(
            other["effective_from"], other["effective_to"],
            sched["effective_from"], sched["effective_to"],
        ):
            other["schedule_status"] = "SUPERSEDED"
            touch(other, coop)
            for ch in all_of("maintenance_charges", coop["id"]):
                if (
                    ch["schedule_id"] == other["id"]
                    and ch["billing_month"] >= new_month
                    and ch["charge_status"] in ("PENDING", "ISSUED", "PARTIALLY_PAID")
                ):
                    ch["charge_status"] = "WAIVED"
                    ch["outstanding_cents"] = 0
                    touch(ch, coop)
    generate_charges(coop, sched)
    recompute_all(coop)
    bump_coop(coop)


# ---------------------------------------------------------------------------
# Flip tax (PRD §3.6)
# ---------------------------------------------------------------------------

def compute_flip_tax(coop, unit, app):
    if coop["flip_tax_policy"] == "GROSS_PERCENT":
        return rhu(Decimal(app["gross_sale_price_cents"]) * coop["flip_tax_percent_bps"], 10000)
    # PER_SHARE: unit allocation x per-share cents; independent of price.
    return unit["shares_allocated"] * coop["flip_tax_per_share_cents"]


# ---------------------------------------------------------------------------
# Buyer qualification (PRD §3.6, buyer_liquidity_requirement)
# ---------------------------------------------------------------------------

def current_base_maintenance(coop, unit_id):
    """base_amount_cents of the unit's charge for the current billing month, or 0."""
    now = coop["current_utc"]
    bm = "%04d-%02d" % (now.year, now.month)
    best = None
    for ch in STORE["maintenance_charges"].values():
        if (
            ch["cooperative_id"] == coop["id"]
            and ch["unit_id"] == unit_id
            and ch["billing_month"] == bm
            and ch["charge_status"] != "WAIVED"
        ):
            if best is None or ch["_seq"] > best["_seq"]:
                best = ch
    return best["base_amount_cents"] if best is not None else 0


def monthly_mortgage(app):
    return rhu(
        Decimal(app["gross_sale_price_cents"])
        * app["financing_percent_bps"]
        * MORTGAGE_RATE_ASSUMPTION_BPS,
        Decimal(10000 * 10000 * 12),
    )


def latest_interview(coop, app_id):
    ivs = [
        i for i in STORE["interviews"].values()
        if i["cooperative_id"] == coop["id"] and i["application_id"] == app_id
    ]
    ivs.sort(key=lambda i: i["_seq"])
    return ivs[-1] if ivs else None


# ---------------------------------------------------------------------------
# Resolutions (PRD §3.2)
# ---------------------------------------------------------------------------

def pre_pass_gates(coop, res):
    """Checks that must hold before a deciding vote may close a resolution PASSED."""
    kind = res["resolution_kind"]
    sid = res["subject_entity_id"]
    if kind == "APPROVE_PURCHASE":
        app = STORE["purchase_applications"].get(sid)
        if app is None or app.get("cooperative_id") != coop["id"]:
            raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Subject purchase application not found", 422)
        # PRD §3.6: "even a passed resolution does not approve an unqualified
        # buyer" — the application-state and interview-outcome qualifications
        # gate the cascade in apply_resolution_passed, not the vote. Only the
        # two fiscal thresholds reject the deciding vote (HTTP 422).
        if app["debt_to_income_bps"] > DTI_MAX_BPS:
            raise ApiError(
                ERR_FISCAL_THRESHOLD_VIOLATION,
                "Buyer debt-to-income exceeds 2800 bps",
                422,
            )
        required = MONTHS_LIQUIDITY_REQUIRED * (
            current_base_maintenance(coop, app["unit_id"]) + monthly_mortgage(app)
        )
        if app["post_closing_liquidity_cents"] < required:
            raise ApiError(
                ERR_FISCAL_THRESHOLD_VIOLATION,
                "Buyer post-closing liquidity below 12 months of carrying costs",
                422,
            )
    elif kind == "APPROVE_ALTERATION":
        a = STORE["alteration_agreements"].get(sid)
        if (
            a is not None
            and a.get("cooperative_id") == coop["id"]
            and a["alteration_status"] == "SUBMITTED"
            and a.get("involves_wet_over_dry")
        ):
            p = res.get("payload_json") or {}
            if p.get("wet_over_dry_ack") is not True:
                raise ApiError(
                    ERR_ALTERATION_SAFETY_VIOLATION,
                    "Wet-over-dry work requires explicit wet_over_dry_ack in the resolution payload",
                    422,
                )


def apply_resolution_passed(coop, res):
    """Downstream cascade fired when a resolution reaches PASSED."""
    kind = res["resolution_kind"]
    sid = res["subject_entity_id"]
    now = coop["current_utc"]
    if kind == "APPROVE_PURCHASE":
        app = STORE["purchase_applications"].get(sid)
        # PRD §3.6: approval moves the application from INTERVIEW_SCHEDULED to
        # APPROVED, and only when the interview is COMPLETED with a FAVORABLE
        # outcome; otherwise a passed resolution leaves the application as-is.
        if app is not None and app["application_status"] == "INTERVIEW_SCHEDULED":
            iv = latest_interview(coop, app["id"])
            if (
                iv is not None
                and iv["interview_status"] == "COMPLETED"
                and iv["interview_outcome"] == "FAVORABLE"
            ):
                app["application_status"] = "APPROVED"
                app["deciding_resolution_id"] = res["id"]
                touch(app, coop)
    elif kind == "REJECT_PURCHASE":
        app = STORE["purchase_applications"].get(sid)
        if app is not None and app["application_status"] in ("UNDER_REVIEW", "INTERVIEW_SCHEDULED"):
            app["application_status"] = "REJECTED"
            app["deciding_resolution_id"] = res["id"]
            touch(app, coop)
    elif kind == "APPROVE_SCHEDULE":
        sched = STORE["charge_schedules"].get(sid)
        if sched is not None and sched["schedule_status"] == "DRAFT":
            approve_schedule(coop, sched, res)
    elif kind == "APPROVE_REFINANCE":
        p = dict(res.get("payload_json") or {})
        rate_new = p.get("rate_bps_new", coop["underlying_mortgage_rate_bps"])
        principal_new = p.get(
            "principal_cents_new",
            p.get("underlying_mortgage_principal_cents", coop["underlying_mortgage_principal_cents"]),
        )
        new_payment = rhu(Decimal(principal_new) * Decimal(rate_new), 10000)
        cur_payment = rhu(
            Decimal(coop["underlying_mortgage_principal_cents"])
            * Decimal(coop["underlying_mortgage_rate_bps"]),
            10000,
        )
        p["annual_payment_cents_new"] = new_payment
        p["delta_vs_current_cents"] = new_payment - cur_payment
        res["payload_json"] = p
        coop["underlying_mortgage_rate_bps"] = rate_new
        coop["underlying_mortgage_principal_cents"] = principal_new
        bump_coop(coop)
    elif kind == "APPROVE_SUBLET":
        s = STORE["sublet_agreements"].get(sid)
        if s is not None and s["sublet_status"] == "SUBMITTED":
            s["sublet_status"] = "APPROVED"
            s["monthly_sublet_fee_cents"] = rhu(
                Decimal(current_base_maintenance(coop, s["unit_id"])) * SUBLET_FEE_RATE_BPS, 10000
            )
            touch(s, coop)
    elif kind == "APPROVE_ALTERATION":
        a = STORE["alteration_agreements"].get(sid)
        if a is not None and a["alteration_status"] == "SUBMITTED":
            a["alteration_status"] = "APPROVED"
            touch(a, coop)
    elif kind == "ISSUE_ARREARS_ACTION":
        actions = [
            a for a in all_of("arrears_actions", coop["id"])
            if a["shareholder_id"] == sid and a["action_status"] == "ISSUED"
        ]
        if actions:
            escalate_action(coop, actions[-1], now, manual=False)
    elif kind == "SET_POLICY":
        p = res.get("payload_json") or {}
        for f in POLICY_FIELDS:
            if f in p and p[f] is not None:
                coop[f] = p[f]
        # A superseded policy resolution stays in the ledger as history.
        bump_coop(coop)


# ---------------------------------------------------------------------------
# Arrears actions (PRD §3.4)
# ---------------------------------------------------------------------------

def spawn_action(coop, sh, action_type, now):
    return make(
        "arrears_actions", coop,
        cooperative_id=coop["id"],
        shareholder_id=sh["id"],
        action_type=action_type,
        action_status="ISSUED",
        issued_at=now,
        cure_deadline=now + timedelta(days=CURE_DAYS[action_type]),
        cure_amount_cents=sh["arrears_balance_cents"],
    )


def has_termination_resolution(coop, sh_id):
    return any(
        r for r in STORE["resolutions"].values()
        if r["cooperative_id"] == coop["id"]
        and r["resolution_kind"] == "ISSUE_ARREARS_ACTION"
        and r["resolution_status"] == "PASSED"
        and r["subject_entity_id"] == sh_id
    )


def terminate_shareholder(coop, sh, now):
    """Termination of the proprietary lease: wide cascade (PRD §3.4)."""
    sh["standing"] = "TERMINATED"
    touch(sh, coop)
    for e in STORE["share_ledger_entries"].values():
        if (
            e["cooperative_id"] == coop["id"]
            and e["shareholder_id"] == sh["id"]
            and e["entry_status"] == "ACTIVE"
        ):
            e["entry_status"] = "SUPERSEDED"
            touch(e, coop)
    for s in STORE["sublet_agreements"].values():
        if (
            s["cooperative_id"] == coop["id"]
            and s["shareholder_id"] == sh["id"]
            and s["sublet_status"] in ("APPROVED", "ACTIVE")
        ):
            s["sublet_status"] = "TERMINATED_EARLY"
            touch(s, coop)
            unit = STORE["units"].get(s["unit_id"])
            if unit is not None:
                unit["occupancy_status"] = "OWNER_OCCUPIED"
                unit["last_sublet_end_date"] = now
                touch(unit, coop)
    for a in STORE["alteration_agreements"].values():
        if (
            a["cooperative_id"] == coop["id"]
            and a["shareholder_id"] == sh["id"]
            and a["alteration_status"] in ("APPROVED", "IN_PROGRESS")
        ):
            a["alteration_status"] = "ABANDONED"
            touch(a, coop)
    for app in STORE["purchase_applications"].values():
        if (
            app["cooperative_id"] == coop["id"]
            and app["seller_shareholder_id"] == sh["id"]
            and app["application_status"] not in APP_TERMINAL
        ):
            app["application_status"] = "WITHDRAWN"
            touch(app, coop)
            iv = latest_interview(coop, app["id"])
            if iv is not None and iv["interview_status"] == "SCHEDULED":
                iv["interview_status"] = "CANCELLED"
                touch(iv, coop)


def escalate_action(coop, a, now, manual):
    """ISSUED -> ESCALATED with the next-tier spawn / termination cascade."""
    sh = STORE["shareholders"].get(a["shareholder_id"])
    if a["action_type"] == "TERMINATION_NOTICE":
        if not has_termination_resolution(coop, a["shareholder_id"]):
            if manual:
                raise ApiError(
                    ERR_CROSS_ENTITY_VIOLATION,
                    "Escalating a TERMINATION_NOTICE requires a PASSED ISSUE_ARREARS_ACTION resolution",
                    422,
                )
            return
        a["action_status"] = "ESCALATED"
        touch(a, coop)
        if sh is not None:
            terminate_shareholder(coop, sh, now)
    else:
        a["action_status"] = "ESCALATED"
        touch(a, coop)
        if sh is not None:
            spawn_action(coop, sh, NEXT_TIER[a["action_type"]], now)


# ---------------------------------------------------------------------------
# Sublets / alterations / meetings helpers
# ---------------------------------------------------------------------------

def complete_sublet(coop, s):
    s["sublet_status"] = "COMPLETED"
    touch(s, coop)
    unit = STORE["units"].get(s["unit_id"])
    if unit is not None:
        unit["occupancy_status"] = "OWNER_OCCUPIED"
        unit["last_sublet_end_date"] = s["sublet_end_date"]
        touch(unit, coop)


def adjourn_meeting(coop, m):
    m["meeting_status"] = "ADJOURNED_NO_QUORUM"
    m["preparation_state"] = "ADJOURNED"
    for b in STORE["ballots"].values():
        if b["meeting_id"] == m["id"] and b["ballot_status"] == "SUBMITTED":
            b["ballot_status"] = "INVALIDATED"
            touch(b, coop)
    m["shares_represented"] = 0
    m["quorum_state"] = "QUORUM_FAILED"
    touch(m, coop)


def quorum_threshold(coop):
    """Ceiling division: smallest whole share count meeting the quorum percent."""
    return (
        coop["total_shares"] * coop["annual_meeting_quorum_percent_bps"] + 9999
    ) // 10000


def recompute_meeting(coop, m):
    """Quorum is always recomputed from scratch over SUBMITTED ∪ COUNTED ballots."""
    m["shares_represented"] = sum(
        b["shares_voted"]
        for b in STORE["ballots"].values()
        if b["meeting_id"] == m["id"] and b["ballot_status"] in ("SUBMITTED", "COUNTED")
    )
    if m["shares_represented"] >= quorum_threshold(coop):
        q = "QUORUM_MET"
    elif m["meeting_status"] == "ADJOURNED_NO_QUORUM":
        q = "QUORUM_FAILED"
    else:
        q = "QUORUM_PENDING"
    if m["quorum_state"] != q:
        m["quorum_state"] = q
    touch(m, coop)


def run_election_tally(coop, m, open_seats):
    """Simplified cumulative voting (scaffold election_tally).

    Each candidate listed on a COUNTED ballot receives that ballot's full
    shares_voted. Rank by total DESC; tie-break by the cast order of each
    candidate's highest-share supporting ballot (earliest wins); final
    tie-break is the lexicographically smaller candidate user id.
    """
    counted = [
        b for b in STORE["ballots"].values()
        if b["meeting_id"] == m["id"] and b["ballot_status"] == "COUNTED"
    ]
    totals = {}
    top_ballot = {}  # candidate -> (shares, seq) of its highest-share ballot
    for b in counted:
        for c in b["candidate_user_ids"]:
            totals[c] = totals.get(c, 0) + b["shares_voted"]
            cand_key = (b["shares_voted"], -b["_seq"])
            if c not in top_ballot or cand_key > top_ballot[c]:
                top_ballot[c] = cand_key

    def sort_key(c):
        shares, neg_seq = top_ballot[c]
        return (-totals[c], -neg_seq, c)

    ranked = sorted(totals.keys(), key=sort_key)
    m["_elected"] = ranked[: max(0, open_seats)]
    return m["_elected"]


# ---------------------------------------------------------------------------
# Logical clock advancement (PRD §2.5): fires every scheduled transition.
# ---------------------------------------------------------------------------

def advance_clock(coop, to_dt):
    coop["current_utc"] = to_dt
    now = to_dt
    cid = coop["id"]

    # 1. Maintenance charges: issuance, past-due, interest accrual.
    for ch in all_of("maintenance_charges", cid):
        evaluate_charge(coop, ch, now)

    # 2. Derived shareholder balances / standing, and automatic cures.
    for sh in all_of("shareholders", cid):
        recompute_shareholder(coop, sh)
        cure_actions_if_zero(coop, sh, now)

    # 3. Sublet activation / completion.
    for s in all_of("sublet_agreements", cid):
        if s["sublet_status"] == "APPROVED" and s["sublet_start_date"] <= now:
            if now < s["sublet_end_date"]:
                s["sublet_status"] = "ACTIVE"
                touch(s, coop)
                unit = STORE["units"].get(s["unit_id"])
                if unit is not None:
                    unit["occupancy_status"] = "SUBLET"
                    touch(unit, coop)
            else:
                # Whole window elapsed within one clock jump.
                complete_sublet(coop, s)
        if s["sublet_status"] == "ACTIVE" and now >= s["sublet_end_date"]:
            complete_sublet(coop, s)

    # 4. Alterations: work window closing abandons unfinished jobs.
    for a in all_of("alteration_agreements", cid):
        if a["alteration_status"] in ("APPROVED", "IN_PROGRESS") and now >= a["work_window_end"]:
            a["alteration_status"] = "ABANDONED"
            touch(a, coop)

    # 5. Interview no-show after 24h.
    for iv in all_of("interviews", cid):
        if (
            iv["interview_status"] == "SCHEDULED"
            and now > iv["scheduled_at"] + timedelta(seconds=NO_SHOW_AFTER_SECONDS)
        ):
            iv["interview_status"] = "NO_SHOW"
            touch(iv, coop)
            app = STORE["purchase_applications"].get(iv["application_id"])
            if app is not None and app["application_status"] == "INTERVIEW_SCHEDULED":
                app["application_status"] = "UNDER_REVIEW"
                touch(app, coop)

    # 6. Meeting auto-adjournment after 24h with quorum pending.
    for m in all_of("meetings", cid):
        if (
            m["meeting_status"] in ("SCHEDULED", "IN_SESSION")
            and m["quorum_state"] == "QUORUM_PENDING"
            and now > m["scheduled_at"] + timedelta(seconds=MEETING_AUTO_ADJOURN_SECONDS)
        ):
            adjourn_meeting(coop, m)

    # 7. Arrears ladder: automatic escalation past the cure deadline.
    for a in all_of("arrears_actions", cid):
        if a["action_status"] != "ISSUED":
            continue
        sh = STORE["shareholders"].get(a["shareholder_id"])
        if sh is None:
            continue
        if sh["arrears_balance_cents"] == 0 and now <= a["cure_deadline"]:
            a["action_status"] = "CURED"
            touch(a, coop)
        elif now > a["cure_deadline"] and sh["arrears_balance_cents"] > 0:
            escalate_action(coop, a, now, manual=False)

    # 8. Every clock advancement increments the cooperative's version.
    bump_coop(coop)
