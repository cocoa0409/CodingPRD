"""Business logic: calculations (SCAFFOLD table 1.3), calendar rules (PRD
§2.7), duplicate guard, leg bubble-up, logical-clock sweep, and the accept /
completion / cancellation cascades (PRD §3.4, §3.8, §3.9).
"""

from datetime import timedelta

from httpkit import api_err
from store import clock, db, mutate, new_record, next_seq
from util import date_obj, dec, fmt_ts, new_uuid, round_cents

# Constants (SCAFFOLD calculations / state machines)
DAYS_PER_WEEK = 7
EXTRA_DAY_DIVISOR = 6
APA_TIER_THRESHOLD_CENTS = 2_000_000
APA_PCT_BELOW_THRESHOLD = 0.30
APA_PCT_AT_OR_ABOVE_THRESHOLD = 0.25
SIGNING_SHARE_PCT = dec("0.50")
OFFER_VALID_DAYS = 7
MAX_NEGOTIATION_ROUNDS = 4
TURNAROUND_BUFFER_DAYS = 1
PENALTY_COMMISSION_PCT = dec("0.20")
COMMISSION_TIER1_MAX_CENTS = 999_999
COMMISSION_TIER2_MAX_CENTS = 4_999_999

RESUME_RANK = {"NONE": 0, "COASTAL": 1, "OFFSHORE": 2, "OCEAN": 3}
LIVE_REQUEST_STATES = {"DRAFT", "SUBMITTED", "OFFERED", "COUNTERED"}
LIVE_AGREEMENT_STATES = {"PENDING_SIGNATURES", "SIGNED", "IN_PREP", "UNDERWAY"}

_BUCKET_FIELD = {
    "CHARTER_FEE": "held_charter_fee_cents",
    "APA": "held_apa_cents",
    "DEPOSIT": "held_deposit_cents",
    "GRATUITY": "held_gratuity_cents",
}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def escrow_of(agreement_id):
    for e in db["escrow_accounts"].values():
        if e["charter_agreement_id"] == agreement_id:
            return e
    return None


def charter_block_of(agreement_id):
    for b in db["availability_blocks"].values():
        if b.get("charter_agreement_id") == agreement_id:
            return b
    return None


def expenses_of(agreement_id):
    return [
        e for e in db["expenses"].values()
        if e["charter_agreement_id"] == agreement_id
    ]


def legs_of(agreement_id):
    legs = [
        l for l in db["itinerary_legs"].values()
        if l["charter_agreement_id"] == agreement_id
    ]
    return sorted(legs, key=lambda l: l["seq_no"])


def permits_of(leg_id):
    return [
        p for p in db["port_permits"].values()
        if p["itinerary_leg_id"] == leg_id
    ]


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD table 1.3)
# ---------------------------------------------------------------------------

def charter_fee_quote(yacht, start_date, end_date):
    """PRO_RATA: round_half_up(weekly * days / 7). WEEKLY_PLUS_DAILY: full
    weeks at the weekly rate + remaining days at round_half_up(weekly / 6)."""
    days = (date_obj(end_date) - date_obj(start_date)).days
    weekly = yacht["weekly_base_rate_cents"]
    if yacht["pricing_mode"] == "PRO_RATA":
        return round_cents(dec(weekly) * dec(days) / dec(DAYS_PER_WEEK))
    weeks, rem = divmod(days, DAYS_PER_WEEK)
    extra_day_rate = round_cents(dec(weekly) / dec(EXTRA_DAY_DIVISOR))
    return weeks * weekly + rem * extra_day_rate


def apa_pct_default(quoted_fee_cents):
    """Tiered APA default; fee == threshold lands in the 0.25 tier."""
    if quoted_fee_cents < APA_TIER_THRESHOLD_CENTS:
        return APA_PCT_BELOW_THRESHOLD
    return APA_PCT_AT_OR_ABOVE_THRESHOLD


def apa_amount_cents(charter_fee_cents, apa_pct):
    return round_cents(dec(charter_fee_cents) * dec(apa_pct))


def signing_charter_part(charter_fee_cents):
    """Half the fee, rounded half-up; the odd cent lands here."""
    return round_cents(dec(charter_fee_cents) * SIGNING_SHARE_PCT)


def standard_commission_total(charter_fee_cents):
    if charter_fee_cents <= COMMISSION_TIER1_MAX_CENTS:
        rate = dec("0.15")
    elif charter_fee_cents <= COMMISSION_TIER2_MAX_CENTS:
        rate = dec("0.18")
    else:
        rate = dec("0.20")
    return round_cents(dec(charter_fee_cents) * rate)


def penalty_commission_total(retained_cents):
    return round_cents(dec(retained_cents) * PENALTY_COMMISSION_PCT)


def commission_shares(commission_total_cents, retail_pct_bps):
    """Pinned rounding order: total rounded first, retail share rounded,
    central share is the residual (never independently rounded)."""
    retail = round_cents(dec(commission_total_cents) * dec(retail_pct_bps) / dec(10000))
    return retail, commission_total_cents - retail


def cancellation_penalty(charter_fee_cents, days_before_start):
    """Tier boundaries use >=: 60 lands in 0.30, 59 in 0.50."""
    if days_before_start >= 90:
        tier = dec("0.10")
    elif days_before_start >= 60:
        tier = dec("0.30")
    elif days_before_start >= 30:
        tier = dec("0.50")
    else:
        tier = dec("1.00")
    return round_cents(dec(charter_fee_cents) * tier)


def gratuity_minimum(quoted_fee_cents):
    return round_cents(dec("0.10") * dec(quoted_fee_cents))


# ---------------------------------------------------------------------------
# Calendar rules (PRD §2.7): half-open overlap first, then 0-day adjacency
# ---------------------------------------------------------------------------

def calendar_check(yacht_id, start_date, end_date):
    blocks = [
        b for b in db["availability_blocks"].values()
        if b["yacht_id"] == yacht_id and b["status"] == "ACTIVE"
    ]
    for b in blocks:
        if start_date < b["end_date"] and b["start_date"] < end_date:
            raise api_err(
                "ERR_AVAILABILITY_CONFLICT",
                "Requested interval overlaps an ACTIVE availability block",
            )
    for b in blocks:
        if end_date == b["start_date"] or b["end_date"] == start_date:
            raise api_err(
                "ERR_TURNAROUND_BUFFER_VIOLATION",
                "Requested interval abuts an ACTIVE block with a zero-day gap",
            )


def duplicate_request_check(client_id, yacht_id, start_date, end_date, exclude_id=None):
    for r in db["charter_requests"].values():
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if (
            r["client_id"] == client_id
            and r["yacht_id"] == yacht_id
            and r["status"] in LIVE_REQUEST_STATES
            and start_date < r["end_date"]
            and r["start_date"] < end_date
        ):
            raise api_err(
                "ERR_DUPLICATE_ACTIVE_REQUEST",
                "A live request for this client and yacht overlaps the window",
            )


# ---------------------------------------------------------------------------
# Itinerary leg roll-up + clock sweep
# ---------------------------------------------------------------------------

def reevaluate_leg(leg):
    """PERMITTED iff >= 1 GRANTED permit and zero REQUESTED permits."""
    perms = permits_of(leg["id"])
    granted = any(p["status"] == "GRANTED" for p in perms)
    requested = any(p["status"] == "REQUESTED" for p in perms)
    new_status = "PERMITTED" if (granted and not requested) else "PLANNED"
    if new_status != leg["status"]:
        leg["status"] = new_status
        mutate(leg)


def clock_sweep():
    """On clock set: GRANTED permits whose valid_until date is earlier than
    the new clock date become EXPIRED; each affected leg re-evaluates."""
    today = clock.now().date().isoformat()
    affected_leg_ids = []
    for p in db["port_permits"].values():
        if p["status"] == "GRANTED" and p["valid_until"] < today:
            p["status"] = "EXPIRED"
            mutate(p)
            if p["itinerary_leg_id"] not in affected_leg_ids:
                affected_leg_ids.append(p["itinerary_leg_id"])
    for leg_id in affected_leg_ids:
        reevaluate_leg(db["itinerary_legs"][leg_id])


# ---------------------------------------------------------------------------
# Escrow movement posting (ledger; amounts always positive)
# ---------------------------------------------------------------------------

def post_movement(escrow, movement_type, bucket, amount_cents, memo):
    if amount_cents <= 0:
        return None
    mv = {
        "id": new_uuid(),
        "created_at": clock.now(),
        "_seq": next_seq(),
        "escrow_account_id": escrow["id"],
        "movement_type": movement_type,
        "bucket": bucket,
        "amount_cents": amount_cents,
        "memo": memo,
    }
    db["escrow_movements"][mv["id"]] = mv
    field = _BUCKET_FIELD[bucket]
    if movement_type == "CLIENT_FUND":
        escrow[field] += amount_cents
        escrow["total_funded_cents"] += amount_cents
    else:
        escrow[field] -= amount_cents
        escrow["total_released_cents"] += amount_cents
    escrow["updated_at"] = clock.now()
    return mv


def write_statement(agreement_id, basis, basis_amount, total, retail, central):
    st = {
        "id": new_uuid(),
        "created_at": clock.now(),
        "_seq": next_seq(),
        "charter_agreement_id": agreement_id,
        "basis": basis,
        "basis_amount_cents": basis_amount,
        "commission_total_cents": total,
        "retail_share_cents": retail,
        "central_share_cents": central,
    }
    db["commission_statements"][st["id"]] = st
    return st


# ---------------------------------------------------------------------------
# Accept cascade (PRD §3.4): agreement + escrow + CHARTER block
# ---------------------------------------------------------------------------

def accept_cascade(req):
    yacht = db["yachts"][req["yacht_id"]]
    fee = req["quoted_charter_fee_cents"]
    pct = req["apa_pct"]
    gratuity = req["gratuity_pledged_cents"]
    bps = req["retail_pct_bps"]

    # Funding schedule, pinned evaluation order (escrow_funding_schedule)
    apa_amt = apa_amount_cents(fee, pct)
    sp = signing_charter_part(fee)
    signing_due = sp + yacht["security_deposit_cents"]
    final_due = (fee - sp) + apa_amt + gratuity

    agr = new_record()
    agr.update({
        "charter_request_id": req["id"],
        "client_id": req["client_id"],
        "yacht_id": req["yacht_id"],
        "operator_id": yacht["operator_id"],
        "retail_broker_id": req["retail_broker_id"],
        "central_agent_id": yacht["listing_central_agent_id"],
        "start_date": req["start_date"],
        "end_date": req["end_date"],
        "charter_fee_cents": fee,
        "apa_pct": pct,
        "apa_amount_cents": apa_amt,
        "security_deposit_cents": yacht["security_deposit_cents"],
        "gratuity_pledged_cents": gratuity,
        "retail_pct_bps": bps,
        "pricing_mode": yacht["pricing_mode"],
        "signing_due_cents": signing_due,
        "final_due_cents": final_due,
        "client_signed_at": None,
        "central_agent_signed_at": None,
        "days_before_start": None,
        "cancellation_penalty_cents": None,
        "status": "PENDING_SIGNATURES",
        "funds_status": "UNFUNDED",
    })
    db["charter_agreements"][agr["id"]] = agr

    esc = new_record()
    esc.update({
        "charter_agreement_id": agr["id"],
        "held_charter_fee_cents": 0,
        "held_apa_cents": 0,
        "held_deposit_cents": 0,
        "held_gratuity_cents": 0,
        "total_funded_cents": 0,
        "total_released_cents": 0,
        "status": "OPEN",
    })
    db["escrow_accounts"][esc["id"]] = esc

    blk = new_record()
    blk.update({
        "yacht_id": yacht["id"],
        "charter_agreement_id": agr["id"],
        "block_type": "CHARTER",
        "start_date": req["start_date"],
        "end_date": req["end_date"],
        "status": "ACTIVE",
    })
    db["availability_blocks"][blk["id"]] = blk
    mutate(yacht)  # calendar changed

    req["status"] = "ACCEPTED"
    mutate(req)
    return agr


# ---------------------------------------------------------------------------
# Completion cascade (PRD §3.8)
# ---------------------------------------------------------------------------

def complete_cascade(agr):
    esc = escrow_of(agr["id"])
    expenses = expenses_of(agr["id"])

    # Hop 1: funds FULLY_FUNDED -> SETTLING; lock unresolved expenses
    agr["funds_status"] = "SETTLING"
    for e in expenses:
        if e["status"] in ("PENDING", "DISPUTED"):
            e["status"] = "REJECTED"
            mutate(e)

    apa_actual = sum(
        e["amount_cents"] for e in expenses
        if e["bucket"] == "APA" and e["status"] == "APPROVED"
    )
    approved_damage = sum(
        e["amount_cents"] for e in expenses
        if e["bucket"] == "DAMAGE_CLAIM" and e["status"] == "APPROVED"
    )

    fee = agr["charter_fee_cents"]
    commission_total = standard_commission_total(fee)
    retail_share, central_share = commission_shares(
        commission_total, agr["retail_pct_bps"]
    )

    held_fee = esc["held_charter_fee_cents"]
    held_apa = esc["held_apa_cents"]
    held_dep = esc["held_deposit_cents"]
    held_grat = esc["held_gratuity_cents"]
    operator_damage = min(approved_damage, held_dep)

    # Hop 2: settlement movements; escrow OPEN -> SETTLING
    esc["status"] = "SETTLING"
    post_movement(esc, "RELEASE_TO_OPERATOR", "APA", apa_actual,
                  "Settlement: approved APA spend released to operator")
    post_movement(esc, "REFUND_TO_CLIENT", "APA", held_apa - apa_actual,
                  "Settlement: unspent APA refunded to client")
    post_movement(esc, "RELEASE_TO_OPERATOR", "GRATUITY", held_grat,
                  "Settlement: crew gratuity released to operator")
    post_movement(esc, "RELEASE_TO_OPERATOR", "DEPOSIT", operator_damage,
                  "Settlement: approved damage claims released to operator")
    post_movement(esc, "REFUND_TO_CLIENT", "DEPOSIT", held_dep - operator_damage,
                  "Settlement: deposit remainder refunded to client")
    post_movement(esc, "RELEASE_TO_OPERATOR", "CHARTER_FEE", fee - commission_total,
                  "Settlement: charter fee less commission released to operator")
    post_movement(esc, "RELEASE_TO_RETAIL_BROKER", "CHARTER_FEE", retail_share,
                  "Settlement: retail broker commission share")
    post_movement(esc, "RELEASE_TO_CENTRAL_AGENT", "CHARTER_FEE", central_share,
                  "Settlement: central agent commission share")

    # Hop 3: commission statement + escrow SETTLING -> CLOSED (buckets zeroed)
    write_statement(agr["id"], "CHARTER_FEE", fee, commission_total,
                    retail_share, central_share)
    esc["status"] = "CLOSED"
    esc["held_charter_fee_cents"] = 0
    esc["held_apa_cents"] = 0
    esc["held_deposit_cents"] = 0
    esc["held_gratuity_cents"] = 0
    mutate(esc)

    # Hop 4: funds SETTLING -> SETTLED
    agr["funds_status"] = "SETTLED"
    agr["status"] = "COMPLETED"
    mutate(agr)


# ---------------------------------------------------------------------------
# Cancellation cascade (PRD §3.9)
# ---------------------------------------------------------------------------

def cancel_cascade(agr):
    req = db["charter_requests"][agr["charter_request_id"]]
    yacht = db["yachts"][agr["yacht_id"]]
    esc = escrow_of(agr["id"])

    # Hop 1: penalty computation + funds -> REFUNDING
    days_before_start = (
        date_obj(agr["start_date"]) - clock.now().date()
    ).days
    penalty = cancellation_penalty(agr["charter_fee_cents"], days_before_start)
    agr["days_before_start"] = days_before_start
    agr["cancellation_penalty_cents"] = penalty
    agr["funds_status"] = "REFUNDING"

    held_fee = esc["held_charter_fee_cents"]
    held_apa = esc["held_apa_cents"]
    held_dep = esc["held_deposit_cents"]
    held_grat = esc["held_gratuity_cents"]
    retained = min(penalty, held_fee)

    approved_damage = sum(
        e["amount_cents"] for e in expenses_of(agr["id"])
        if e["bucket"] == "DAMAGE_CLAIM" and e["status"] == "APPROVED"
    )
    operator_damage = min(approved_damage, held_dep)

    # Hop 2: refund / release movements; escrow OPEN -> SETTLING
    esc["status"] = "SETTLING"
    post_movement(esc, "REFUND_TO_CLIENT", "CHARTER_FEE", held_fee - retained,
                  "Cancellation: charter fee less retained penalty refunded")
    post_movement(esc, "REFUND_TO_CLIENT", "APA", held_apa,
                  "Cancellation: held APA refunded to client")
    post_movement(esc, "REFUND_TO_CLIENT", "GRATUITY", held_grat,
                  "Cancellation: held gratuity refunded to client")
    post_movement(esc, "RELEASE_TO_OPERATOR", "DEPOSIT", operator_damage,
                  "Cancellation: approved damage claims released to operator")
    post_movement(esc, "REFUND_TO_CLIENT", "DEPOSIT", held_dep - operator_damage,
                  "Cancellation: deposit remainder refunded to client")

    pen_comm = retail_share = central_share = 0
    if retained > 0:
        pen_comm = penalty_commission_total(retained)
        retail_share, central_share = commission_shares(
            pen_comm, agr["retail_pct_bps"]
        )
        post_movement(esc, "RELEASE_TO_OPERATOR", "CHARTER_FEE",
                      retained - pen_comm,
                      "Cancellation: retained penalty less commission to operator")
        post_movement(esc, "RELEASE_TO_RETAIL_BROKER", "CHARTER_FEE", retail_share,
                      "Cancellation: penalty commission, retail share")
        post_movement(esc, "RELEASE_TO_CENTRAL_AGENT", "CHARTER_FEE", central_share,
                      "Cancellation: penalty commission, central share")

    # Hop 3: statement iff retained > 0; escrow SETTLING -> CLOSED
    if retained > 0:
        write_statement(agr["id"], "CANCELLATION_PENALTY", retained,
                        pen_comm, retail_share, central_share)
    esc["status"] = "CLOSED"
    esc["held_charter_fee_cents"] = 0
    esc["held_apa_cents"] = 0
    esc["held_deposit_cents"] = 0
    esc["held_gratuity_cents"] = 0
    mutate(esc)

    # Hop 4: funds REFUNDING -> REFUNDED
    agr["funds_status"] = "REFUNDED"

    # Hop 5: escrow closure releases the CHARTER block; yacht version bumps
    blk = charter_block_of(agr["id"])
    if blk is not None and blk["status"] == "ACTIVE":
        blk["status"] = "RELEASED"
        mutate(blk)
        mutate(yacht)

    # Hop 6: block release cancels the source request
    if req["status"] == "ACCEPTED":
        req["status"] = "CANCELLED"
        mutate(req)

    agr["status"] = "CANCELLED"
    mutate(agr)


# ---------------------------------------------------------------------------
# Void (PRD §3.4): unsigned agreement torn up
# ---------------------------------------------------------------------------

def void_agreement(agr):
    req = db["charter_requests"][agr["charter_request_id"]]
    yacht = db["yachts"][agr["yacht_id"]]
    agr["status"] = "VOIDED"
    blk = charter_block_of(agr["id"])
    if blk is not None and blk["status"] == "ACTIVE":
        blk["status"] = "RELEASED"
        mutate(blk)
        mutate(yacht)
    if req["status"] == "ACCEPTED":
        req["status"] = "CANCELLED"
        mutate(req)
    mutate(agr)


# ---------------------------------------------------------------------------
# Offer term resolution (PRD §3.3)
# ---------------------------------------------------------------------------

def resolve_offer_terms(yacht, req, fee_override, apa_override,
                        gratuity_override, bps_override):
    fee = fee_override if fee_override is not None else charter_fee_quote(
        yacht, req["start_date"], req["end_date"]
    )
    pct = apa_override if apa_override is not None else apa_pct_default(fee)
    gratuity = gratuity_override if gratuity_override is not None else 0
    bps = bps_override if bps_override is not None else 0
    if yacht["charter_type"] == "CREWED" and gratuity < gratuity_minimum(fee):
        raise api_err(
            "ERR_GRATUITY_BELOW_MINIMUM",
            "CREWED offers require gratuity >= 10% of the quoted charter fee",
        )
    return fee, float(pct), gratuity, bps


def offer_expiry():
    return fmt_ts(clock.now() + timedelta(days=OFFER_VALID_DAYS))
