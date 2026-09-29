"""Guards shared across endpoints plus every cascade and multi-row operation."""

from decimal import Decimal

import calc
import constants as K
import derive
import versioning
from db import db, sort_key
from errors import ApiError
from timeutil import add_days, add_hours, add_minutes, whole_minutes_between


# --------------------------------------------------------------------------
# lookups (rules 4 and 5)
# --------------------------------------------------------------------------
def path_lookup(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "Resource %s does not exist." % rid)
    return rec


def fk_lookup(store, rid, label):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(
            "ERR_REFERENCED_ENTITY_NOT_FOUND",
            "Referenced %s %s does not exist." % (label, rid),
        )
    return rec


# --------------------------------------------------------------------------
# ownership, phase, posture (rules 6, 7, 8)
# --------------------------------------------------------------------------
def own_club(role, user_id, club_id):
    if role in ("ClubGM", "ClubMedicalDirector") and user_id != club_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting club does not own this resource.")


def own_prospect(role, user_id, prospect_id):
    if role == "ProspectAgent" and user_id != prospect_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "Acting agent does not represent this prospect."
        )


def require_phase(cycle, allowed):
    if cycle["status"] not in allowed:
        raise ApiError(
            "ERR_CYCLE_PHASE_INVALID",
            "Cycle phase %s does not permit this operation." % cycle["status"],
        )


def require_unfrozen(cycle):
    if derive.cycle_posture(cycle) == "FROZEN":
        raise ApiError("ERR_CYCLE_FROZEN", "The draft cycle is frozen.")


def invalid_transition(detail="The requested transition is not legal."):
    return ApiError("ERR_INVALID_STATE_TRANSITION", detail)


def require_same_cycle(cycle_id, other_cycle_id):
    if cycle_id != other_cycle_id:
        raise ApiError(
            "ERR_CROSS_CYCLE_REFERENCE",
            "Referenced resource belongs to a different draft cycle.",
        )


# --------------------------------------------------------------------------
# cascades
# --------------------------------------------------------------------------
def cancel_scheduled_bookings(prospect_id):
    for booking in derive.prospect_bookings(prospect_id):
        if booking["status"] == "SCHEDULED":
            booking["status"] = "CANCELLED"


def prospect_contracts(prospect_id):
    return [c for c in db.player_contracts.values() if c["prospect_id"] == prospect_id]


def lapse_offered_contracts(prospect):
    """PRD 3.8: a lapse returns signing_status to UNSIGNED unless the prospect
    already holds a SIGNED contract."""
    contracts = prospect_contracts(prospect["id"])
    lapsed_any = False
    for contract in contracts:
        if contract["status"] == "OFFERED":
            contract["status"] = "LAPSED"
            lapsed_any = True
    if lapsed_any:
        if not any(c["status"] == "SIGNED" for c in contracts):
            prospect["signing_status"] = "UNSIGNED"
    return lapsed_any


def revoke_consent(prospect):
    prospect["consent_status"] = "REVOKED"
    evaluations = derive.prospect_evaluations(prospect["id"])
    touched = []
    for evaluation in evaluations:
        affected = False
        for share in derive.evaluation_shares(evaluation["id"]):
            if share["status"] == "GRANTED":
                share["status"] = "REVOKED"
                affected = True
        if affected:
            touched.append(evaluation)
    for evaluation in touched:
        if derive.active_share_count(evaluation["id"]) == 0:
            evaluation["disclosure_state"] = "SEALED"
    if evaluations and all(e["disclosure_state"] == "SEALED" for e in evaluations):
        prospect["medical_clearance_status"] = "UNVERIFIED"
        lapse_offered_contracts(prospect)
    prospect["consent_scope"] = None
    prospect["consent_expires_at"] = None


def share_expiry_sweep():
    """PRD 2.5: each clock advance expires GRANTED shares at or past expires_at."""
    for share in db.medical_record_shares.values():
        if share["status"] != "GRANTED":
            continue
        expires = share["expires_at"]
        if expires is not None and expires <= db.now:
            share["status"] = "EXPIRED"


def share_expiry_instant(share):
    """PRD 3.4 medical_share_access_window: the earliest of three caps."""
    evaluation = db.medical_evaluations.get(share["medical_evaluation_id"])
    booking = db.combine_bookings.get(evaluation["combine_booking_id"])
    prospect = db.prospects.get(booking["prospect_id"])
    cycle = db.draft_cycles.get(prospect["draft_cycle_id"])
    candidates = [
        add_days(cycle["combine_week_end_at"], K.MEDICAL_SHARE_TTL_DAYS),
        add_days(cycle["draft_start_at"], K.MEDICAL_SHARE_DRAFT_GRACE_DAYS),
    ]
    if prospect["consent_expires_at"] is not None:
        candidates.append(prospect["consent_expires_at"])
    return min(candidates)


def share_prospect(share):
    evaluation = db.medical_evaluations.get(share["medical_evaluation_id"])
    booking = db.combine_bookings.get(evaluation["combine_booking_id"])
    return db.prospects.get(booking["prospect_id"])


# --------------------------------------------------------------------------
# selection clock
# --------------------------------------------------------------------------
def lowest_pending(cycle_id):
    picks = [p for p in derive.cycle_picks(cycle_id) if p["status"] == "PENDING"]
    if not picks:
        return None
    return sorted(picks, key=lambda p: p["overall_number"])[0]


def put_on_clock(cycle, pick, started_at):
    pick["status"] = "ON_CLOCK"
    pick["on_clock_started_at"] = started_at
    minutes = calc.clock_minutes(
        pick["round_number"], cycle["compressed_final_day"], pick["timeouts_used"]
    )
    pick["deadline_at"] = add_minutes(started_at, minutes)


def leave_clock(pick):
    """A pick leaving ON_CLOCK keeps its clock stamps.

    PRD 3.7 reads the *expired* pick's ``deadline_at`` after that pick has
    already moved to PASSED ("with ``on_clock_started_at`` set to the expired
    pick's ``deadline_at``"), so the stamp survives the transition; nothing in
    the PRD clears it.
    """
    return None


def advance_after_use(cycle, started_at):
    nxt = lowest_pending(cycle["id"])
    if nxt is not None:
        put_on_clock(cycle, nxt, started_at)
    return nxt


def clock_advance(cycle):
    expired_pick_id = None
    passed_count = 0
    lapsed_count = 0

    current = derive.on_clock_pick(cycle["id"])
    if current is None:
        current = advance_after_use(cycle, db.now)
    else:
        while current is not None and db.now >= current["deadline_at"]:
            boundary = current["deadline_at"]
            current["status"] = "PASSED"
            current["pass_reason"] = "EXPIRED"
            leave_clock(current)
            passed_count += 1
            if expired_pick_id is None:
                expired_pick_id = current["id"]
            nxt = lowest_pending(cycle["id"])
            if nxt is None:
                current = None
                break
            put_on_clock(cycle, nxt, boundary)
            current = nxt

    picks = derive.cycle_picks(cycle["id"])
    if picks and not any(p["status"] in ("PENDING", "ON_CLOCK") for p in picks):
        cycle["status"] = "DRAFT_COMPLETE"
        for pick in picks:
            if pick["status"] == "PASSED":
                pick["status"] = "LAPSED"
                lapsed_count += 1

    return {
        "expired_pick_id": expired_pick_id,
        "on_clock_pick_id": current["id"] if current is not None else None,
        "passed_count": passed_count,
        "lapsed_count": lapsed_count,
    }


# --------------------------------------------------------------------------
# forfeits and capital cascades
# --------------------------------------------------------------------------
def void_trades_for_suspension(cycle_id, club_id):
    for trade in db.pick_trades.values():
        if trade["draft_cycle_id"] != cycle_id:
            continue
        if club_id not in (trade["proposing_club_id"], trade["receiving_club_id"]):
            continue
        if trade["status"] in ("PROPOSED", "COUNTERED"):
            trade["status"] = "VOIDED_BY_CAPITAL"
            if trade["conditional_status"] == "OPEN":
                trade["conditional_status"] = "VOID"


def forfeit_pick(cycle, pick):
    pick["status"] = "FORFEITED"
    pick["chart_value_points"] = Decimal("0.0")
    leave_clock(pick)
    original = db.clubs.get(pick["original_club_id"])
    if original is not None:
        rounds = list(original["forfeited_round_numbers"])
        rounds.append(pick["round_number"])
        original["forfeited_round_numbers"] = rounds
    owner = db.clubs.get(pick["owning_club_id"])
    if owner is not None and derive.club_tier(owner) == "SUSPENDED":
        void_trades_for_suspension(cycle["id"], owner["id"])


# --------------------------------------------------------------------------
# trade valuation
# --------------------------------------------------------------------------
def _picks(ids):
    return [db.draft_picks[i] for i in ids if i in db.draft_picks]


def trade_valuation(offered_ids, requested_ids):
    incoming = Decimal("0.0")
    outgoing = Decimal("0.0")
    for pick in _picks(requested_ids):
        incoming += calc.dec(pick["chart_value_points"])
    for pick in _picks(offered_ids):
        outgoing += calc.dec(pick["chart_value_points"])
    balance, ratio = calc.chart_balance(incoming, outgoing)

    surplus_in = Decimal("0.0")
    surplus_out = Decimal("0.0")
    for pick in _picks(requested_ids):
        surplus_in += calc.pick_surplus_points(
            pick["round_number"], pick["slot_total_value_cents"] or 0
        )
    for pick in _picks(offered_ids):
        surplus_out += calc.pick_surplus_points(
            pick["round_number"], pick["slot_total_value_cents"] or 0
        )
    return balance, ratio, calc.q1(surplus_in - surplus_out)


def apply_valuation(trade):
    balance, ratio, surplus = trade_valuation(
        trade["offered_pick_ids"], trade["requested_pick_ids"]
    )
    trade["chart_balance_points"] = balance
    trade["imbalance_ratio"] = ratio
    trade["surplus_balance_points"] = surplus


def check_pick_package(trade_cycle_id, offered_ids, requested_ids, owner_a, owner_b):
    """Rule 23."""
    for ids, owner in ((offered_ids, owner_a), (requested_ids, owner_b)):
        for pick_id in ids:
            pick = db.draft_picks.get(pick_id)
            if (
                pick is None
                or pick["owning_club_id"] != owner
                or pick["status"] != "PENDING"
            ):
                raise ApiError(
                    "ERR_PICK_NOT_OWNED_BY_CLUB",
                    "Pick %s is not a PENDING pick of the declaring club." % pick_id,
                )


# --------------------------------------------------------------------------
# lottery
# --------------------------------------------------------------------------
def run_lottery(cycle, sequence):
    registered = derive.registered_clubs(cycle["id"])
    non_playoff = [c for c in registered if not c["playoff_qualified"]]
    playoff = [c for c in registered if c["playoff_qualified"]]

    non_playoff.sort(
        key=lambda c: (
            calc.dec(c["prior_season_win_pct"]),
            calc.dec(c["strength_of_schedule"]),
            c["head_to_head_rank"],
            c["created_at"],
            c["_seq"],
        )
    )

    # Step 2 -- contiguous combination blocks.
    cursor = 1
    blocks = []
    for club in non_playoff:
        count = int(club["lottery_combinations"] or 0)
        blocks.append((cursor, cursor + count - 1, club))
        cursor += count
    total_combinations = cursor - 1

    slot_count = min(K.LOTTERY_SLOT_CAP, len(non_playoff))

    # Rule 26 -- every drawn value in range, and enough distinct clubs.
    for value in sequence:
        if value < 1 or value > total_combinations:
            raise ApiError(
                "ERR_LOTTERY_SEQUENCE_INVALID",
                "Drawn combination %s is outside 1..%s." % (value, total_combinations),
            )
    distinct = []
    for value in sequence:
        owner = None
        for low, high, club in blocks:
            if low <= value <= high:
                owner = club
                break
        if owner is not None and owner["id"] not in distinct:
            distinct.append(owner["id"])
    if len(distinct) < slot_count:
        raise ApiError(
            "ERR_LOTTERY_SEQUENCE_INVALID",
            "The drawn sequence names fewer distinct clubs than there are slots.",
        )

    # Step 1 -- ranks.
    for club in registered:
        club["pre_lottery_rank"] = 0
    for index, club in enumerate(non_playoff):
        club["pre_lottery_rank"] = index + 1

    # Step 3 -- slots.
    slots = []
    slot_ids = set()
    for value in sequence:
        if len(slots) == slot_count:
            break
        owner = None
        for low, high, club in blocks:
            if low <= value <= high:
                owner = club
                break
        if owner is None or owner["id"] in slot_ids:
            continue
        slots.append(owner)
        slot_ids.add(owner["id"])

    # Step 4 -- final order.
    order = list(slots)
    placed = set(slot_ids)
    for club in non_playoff:
        if club["id"] not in placed:
            order.append(club)
            placed.add(club["id"])
    playoff.sort(
        key=lambda c: (
            c["playoff_exit_round"],
            calc.dec(c["prior_season_win_pct"]),
            calc.dec(c["strength_of_schedule"]),
            c["created_at"],
            c["_seq"],
        )
    )
    order.extend(playoff)

    for club in db.clubs.values():
        if club["draft_cycle_id"] == cycle["id"] and club["registration_status"] != "REGISTERED":
            club["draft_order_index"] = 0
            club["pre_lottery_rank"] = 0
    for index, club in enumerate(order):
        club["draft_order_index"] = index + 1

    cycle["lottery_completed"] = True
    cycle["lottery_slot_club_ids"] = [c["id"] for c in slots]


# --------------------------------------------------------------------------
# draft order finalize
# --------------------------------------------------------------------------
def _mint_pick(cycle, club, round_number, pick_in_round, compensatory, sequence):
    forfeited = round_number in (club["forfeited_round_numbers"] or [])
    slot = calc.slotted_contract_value(round_number, pick_in_round, "DRAFTED")
    fields = {
        "draft_cycle_id": cycle["id"],
        "owning_club_id": club["id"],
        "original_club_id": club["id"],
        "round_number": round_number,
        "pick_in_round": pick_in_round,
        "overall_number": 0,
        "is_compensatory": compensatory,
        "compensatory_sequence": sequence,
        "status": "FORFEITED" if (forfeited and not compensatory) else "PENDING",
        "chart_value_points": (
            Decimal("0.0")
            if (forfeited and not compensatory)
            else calc.chart_value_points(round_number, pick_in_round)
        ),
        "slot_total_value_cents": slot["total_value_cents"],
        "slot_signing_bonus_cents": slot["signing_bonus_cents"],
        "slot_first_year_cap_charge_cents": slot["first_year_cap_charge_cents"],
        "slot_total_cap_commitment_cents": slot["total_cap_commitment_cents"],
        "on_clock_started_at": None,
        "deadline_at": None,
        "timeouts_used": 0,
        "out_of_order_authorized": False,
        "selected_prospect_id": None,
        "selection_source": None,
        "pass_reason": None,
    }
    return db.insert(db.draft_picks, "DraftPick", fields)


def _award_pass(cycle, club_count):
    """PRD 3.5: one league-wide ordering, per-club net entitlement and caps."""
    claims = [
        c
        for c in db.compensatory_claims.values()
        if c["draft_cycle_id"] == cycle["id"] and c["status"] == "VERIFIED"
    ]
    net_by_club = {}
    for club in derive.cycle_clubs(cycle["id"]):
        departures = [
            c
            for c in claims
            if c["club_id"] == club["id"]
            and c["claim_type"] == "DEPARTURE"
            and c["qualifies"]
        ]
        arrivals = [
            c
            for c in claims
            if c["club_id"] == club["id"]
            and c["claim_type"] == "ARRIVAL"
            and c["qualifies"]
        ]
        net_by_club[club["id"]] = max(0, len(departures) - len(arrivals))

    candidates = [
        c for c in claims if c["claim_type"] == "DEPARTURE" and c["qualifies"]
    ]
    candidates.sort(key=lambda c: (-calc.dec(c["claim_score"]), c["created_at"], c["_seq"]))

    league_awarded = 0
    per_club = {}
    round_sequence = {}
    awarded = []
    for claim in candidates:
        if league_awarded >= K.COMP_LEAGUE_MAX_AWARDS:
            break
        club_id = claim["club_id"]
        used = per_club.get(club_id, 0)
        allowance = min(net_by_club.get(club_id, 0), K.COMP_MAX_AWARDS_PER_CLUB)
        if used >= allowance:
            continue
        awarded_round = calc.comp_awarded_round(claim["claim_score"])
        sequence = round_sequence.get(awarded_round, 0) + 1
        round_sequence[awarded_round] = sequence
        claim["status"] = "AWARDED"
        claim["awarded_round"] = awarded_round
        claim["awarded_sequence"] = sequence
        per_club[club_id] = used + 1
        league_awarded += 1
        awarded.append(claim)

    for claim in claims:
        if claim["status"] == "VERIFIED":
            claim["status"] = "REJECTED_CAP"
            claim["awarded_round"] = 0
            claim["awarded_sequence"] = 0

    comp_picks = []
    for claim in awarded:
        club = db.clubs.get(claim["club_id"])
        if club is None:
            continue
        pick = _mint_pick(
            cycle,
            club,
            claim["awarded_round"],
            club_count + claim["awarded_sequence"],
            True,
            claim["awarded_sequence"],
        )
        comp_picks.append(pick)
    return comp_picks


def finalize_order(cycle):
    registered = derive.registered_clubs(cycle["id"])
    ordered = sorted(
        registered, key=lambda c: (c["draft_order_index"], c["created_at"], c["_seq"])
    )
    club_count = len(ordered)
    rounds_count = cycle["rounds_count"]

    regular = []
    for round_number in range(1, rounds_count + 1):
        for club in ordered:
            regular.append(
                _mint_pick(
                    cycle, club, round_number, club["draft_order_index"], False, 0
                )
            )

    comp_picks = _award_pass(cycle, club_count)

    # Overall numbers: regular picks of each round, then that round's
    # compensatory picks at the tail.
    overall = 0
    all_rounds = sorted(
        set([p["round_number"] for p in regular] + [p["round_number"] for p in comp_picks])
    )
    for round_number in all_rounds:
        for pick in sorted(
            [p for p in regular if p["round_number"] == round_number],
            key=lambda p: p["pick_in_round"],
        ):
            overall += 1
            pick["overall_number"] = overall
        for pick in sorted(
            [p for p in comp_picks if p["round_number"] == round_number],
            key=lambda p: p["compensatory_sequence"],
        ):
            overall += 1
            pick["overall_number"] = overall

    cycle["order_finalized_at"] = db.now
    cycle["udfa_window_close_at"] = add_hours(cycle["draft_start_at"], K.UDFA_WINDOW_HOURS)
    cycle["status"] = "ORDER_FINAL"

    first = None
    for pick in regular + comp_picks:
        if pick["overall_number"] == 1:
            first = pick
            break
    return {
        "created_pick_count": len(regular),
        "compensatory_pick_count": len(comp_picks),
        "first_overall_pick_id": first["id"] if first is not None else None,
    }


# --------------------------------------------------------------------------
# phase transitions
# --------------------------------------------------------------------------
CYCLE_TRANSITIONS = {
    ("SETUP", "DECLARATION_OPEN"),
    ("DECLARATION_OPEN", "COMBINE_WEEK"),
    ("COMBINE_WEEK", "ORDER_PENDING"),
    ("ORDER_FINAL", "DRAFT_LIVE"),
    ("DRAFT_LIVE", "DRAFT_SUSPENDED"),
    ("DRAFT_SUSPENDED", "DRAFT_LIVE"),
    ("DRAFT_COMPLETE", "UDFA_WINDOW"),
    ("UDFA_WINDOW", "CLOSED"),
}


def apply_phase(cycle, target):
    current = cycle["status"]
    if (current, target) not in CYCLE_TRANSITIONS:
        raise invalid_transition(
            "Cycle cannot move from %s to %s." % (current, target)
        )

    if target == "DECLARATION_OPEN":
        if derive.club_count(cycle["id"]) < 2:
            raise invalid_transition("At least two registered clubs are required.")
    elif target == "COMBINE_WEEK":
        declared = [
            p
            for p in derive.cycle_prospects(cycle["id"])
            if p["declaration_status"] == "DECLARED"
        ]
        if not declared:
            raise invalid_transition("No prospect has declared yet.")
    elif target == "ORDER_PENDING":
        for booking in db.combine_bookings.values():
            prospect = db.prospects.get(booking["prospect_id"])
            if prospect is None or prospect["draft_cycle_id"] != cycle["id"]:
                continue
            if booking["status"] in K.BOOKING_ACTIVE_STATUSES:
                raise invalid_transition("A combine booking is still open.")
    elif target == "DRAFT_LIVE" and current == "ORDER_FINAL":
        if db.now < cycle["draft_start_at"]:
            raise invalid_transition("The draft start instant has not been reached.")
    elif target == "CLOSED":
        close_at = cycle["udfa_window_close_at"]
        if close_at is None or db.now < close_at:
            raise invalid_transition("The undrafted window has not closed yet.")

    cycle["status"] = target

    if target == "UDFA_WINDOW":
        for club in derive.registered_clubs(cycle["id"]):
            club["udfa_pool_total_cents"] = calc.udfa_pool_total(
                derive.rookie_pool_remaining(club),
                derive.lapsed_slot_charge_total(club["id"]),
            )
    elif target == "CLOSED":
        club_ids = set(c["id"] for c in derive.cycle_clubs(cycle["id"]))
        touched = set()
        for contract in db.player_contracts.values():
            if contract["club_id"] in club_ids and contract["status"] == "OFFERED":
                contract["status"] = "LAPSED"
                touched.add(contract["prospect_id"])
        for prospect_id in touched:
            prospect = db.prospects.get(prospect_id)
            if prospect is None:
                continue
            if not any(
                c["status"] == "SIGNED" for c in prospect_contracts(prospect_id)
            ):
                prospect["signing_status"] = "UNSIGNED"
    return cycle


# --------------------------------------------------------------------------
# booking conflict detection (rules 32, 33, 34)
# --------------------------------------------------------------------------
def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def check_station_conflict(station, starts_at, ends_at):
    buffer_minutes = int(station["turnaround_buffer_minutes"] or 0)
    low = add_minutes(starts_at, -buffer_minutes)
    high = add_minutes(ends_at, buffer_minutes)
    for booking in db.combine_bookings.values():
        if booking["medical_station_id"] != station["id"]:
            continue
        if booking["status"] not in K.BOOKING_ACTIVE_STATUSES:
            continue
        if _overlaps(low, high, booking["starts_at"], booking["ends_at"]):
            raise ApiError(
                "ERR_STATION_SLOT_CONFLICT",
                "The medical station is not free for that interval.",
            )


def check_room_capacity(room, starts_at, ends_at):
    overlapping = 0
    for booking in db.combine_bookings.values():
        if booking["interview_room_id"] != room["id"]:
            continue
        if booking["status"] not in K.BOOKING_ACTIVE_STATUSES:
            continue
        if _overlaps(starts_at, ends_at, booking["starts_at"], booking["ends_at"]):
            overlapping += 1
    if overlapping >= int(room["concurrent_capacity"]):
        raise ApiError(
            "ERR_ROOM_CAPACITY_EXCEEDED",
            "The interview room is at capacity for that interval.",
        )


def check_itinerary(prospect_id, starts_at, ends_at):
    low = add_minutes(starts_at, -K.PROSPECT_TRAVEL_GAP_MINUTES)
    high = add_minutes(ends_at, K.PROSPECT_TRAVEL_GAP_MINUTES)
    for booking in derive.prospect_bookings(prospect_id):
        if booking["status"] not in K.BOOKING_ACTIVE_STATUSES:
            continue
        if _overlaps(low, high, booking["starts_at"], booking["ends_at"]):
            raise ApiError(
                "ERR_PROSPECT_ITINERARY_CONFLICT",
                "The prospect cannot reach that slot in time.",
            )


def duration_minutes(starts_at, ends_at):
    return whole_minutes_between(starts_at, ends_at)


# --------------------------------------------------------------------------
# sorting helpers for list endpoints
# --------------------------------------------------------------------------
def by_created(records):
    return sorted(records, key=sort_key)


def by_club_order(records):
    return sorted(records, key=lambda c: (c["draft_order_index"], c["created_at"], c["_seq"]))


def by_starts_at(records):
    return sorted(records, key=lambda b: (b["starts_at"], b["created_at"], b["_seq"]))


def by_overall(records):
    return sorted(records, key=lambda p: (p["overall_number"], p["created_at"], p["_seq"]))


def by_claim_score(records):
    return sorted(
        records, key=lambda c: (-calc.dec(c["claim_score"]), c["created_at"], c["_seq"])
    )
