"""Store-aware derivations and cascades (PRD sections 2.8, 2.10, 3.x).

Every derived value is kept continuously correct: whenever an input moves, the
owning row is recomputed in the same request and everything downstream of it
follows until the chain closes.  Each row a cascade touches has its version
bumped exactly once for the request (store.touch is idempotent per request).
"""

import calc
import store
from store import touch

REVENUE_STATES = ("CONFIRMED", "AMENDED", "CHECKED_IN")
RESERVED_STATES = ("RESERVED",)
COMMITTED_STATES = ("COMMITTED", "ARTWORK_APPROVED", "INSTALLED")
FULFILLED_STATES = ("VERIFIED", "WAIVED")
OCCUPYING_STATES = RESERVED_STATES + COMMITTED_STATES + FULFILLED_STATES
REVENUE_ALLOCATION_STATES = COMMITTED_STATES + FULFILLED_STATES
NON_TERMINAL_ALLOCATION_STATES = RESERVED_STATES + COMMITTED_STATES
INSURED_STATES = ("BOUND", "CLAIM_PAID", "CLAIM_DENIED", "EXPIRED")


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def rows_where(collection, **filters):
    out = []
    for row in collection.values():
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return store.sorted_rows(out)


def contract_of(outing_id):
    for row in store.contracts.values():
        if row["outing_id"] == outing_id:
            return row
    return None


def tiers_of(outing_id):
    return rows_where(store.package_tiers, outing_id=outing_id)


def regs_of(outing_id):
    return rows_where(store.registrations, outing_id=outing_id)


def teams_of(outing_id):
    return rows_where(store.teams, outing_id=outing_id)


def assets_of(outing_id):
    return rows_where(store.sponsorship_assets, outing_id=outing_id)


def contests_of(outing_id):
    return rows_where(store.contests, outing_id=outing_id)


def items_of(outing_id):
    return rows_where(store.fundraising_items, outing_id=outing_id)


def receipts_of(outing_id):
    return rows_where(store.receipts, outing_id=outing_id)


def players_of_registration(registration_id):
    return rows_where(store.players, registration_id=registration_id)


def players_of_team(team_id):
    return rows_where(store.players, team_id=team_id)


def allocs_of_registration(registration_id):
    return rows_where(store.sponsor_allocations, registration_id=registration_id)


def allocs_of_asset(asset_id):
    return rows_where(store.sponsor_allocations, sponsorship_asset_id=asset_id)


def players_of_outing(outing_id):
    reg_ids = set(r["id"] for r in regs_of(outing_id))
    return store.sorted_rows(
        [p for p in store.players.values() if p["registration_id"] in reg_ids]
    )


def allocs_of_outing(outing_id):
    reg_ids = set(r["id"] for r in regs_of(outing_id))
    return store.sorted_rows(
        [a for a in store.sponsor_allocations.values()
         if a["registration_id"] in reg_ids]
    )


def outing_of_registration(reg):
    return store.outings.get(reg["outing_id"])


def registration_of_player(player):
    return store.registrations.get(player["registration_id"])


def outing_of_player(player):
    reg = registration_of_player(player)
    return None if reg is None else store.outings.get(reg["outing_id"])


def tier_of(reg):
    return store.package_tiers.get(reg["package_tier_id"])


def is_revenue(reg):
    return reg is not None and reg["status"] in REVENUE_STATES


# --------------------------------------------------------------------------
# Handicaps (PRD 3.3)
# --------------------------------------------------------------------------
def player_course_handicap(player, contract, use_effective):
    """Convert the index in use into a course handicap, or None when unusable."""
    if contract is None:
        return None
    index = (player.get("effective_handicap_index") if use_effective
             else player.get("handicap_index_at_confirm"))
    if index is None:
        return None
    return calc.course_handicap(index, contract["slope_rating"],
                               contract["course_rating"], contract["par"])


def rederive_player_handicap(player, contract=None, use_effective=None):
    """Recompute course_handicap for a revenue-recognized player."""
    reg = registration_of_player(player)
    if not is_revenue(reg):
        return
    if contract is None:
        contract = contract_of(reg["outing_id"])
    if use_effective is None:
        use_effective = player.get("effective_handicap_index") is not None
    value = player_course_handicap(player, contract, use_effective)
    player["course_handicap"] = value
    touch(player)


def snapshot_registration_players(reg, contract=None):
    """On confirmation: snapshot the index, then derive the course handicap."""
    if contract is None:
        contract = contract_of(reg["outing_id"])
    for player in players_of_registration(reg["id"]):
        player["handicap_index_at_confirm"] = player["handicap_index"]
        player["course_handicap"] = player_course_handicap(player, contract, False)
        touch(player)


def rederive_team_handicap(team, variant=None):
    """Recompute team_playing_handicap under the given (or current) variant."""
    outing = store.outings.get(team["outing_id"])
    if variant is None:
        variant = team.get("handicap_variant") or "PROVISIONAL"
    team["handicap_variant"] = variant
    members = [p for p in players_of_team(team["id"])
               if is_revenue(registration_of_player(p))]
    members.sort(key=lambda p: (
        p["course_handicap"] if p["course_handicap"] is not None else 0,
        p["created_at"], p["_seq"],
    ))
    handicaps = [p["course_handicap"] for p in members]
    fmt = outing["format"] if outing else "SCRAMBLE"
    team["team_playing_handicap"] = calc.team_playing_handicap(handicaps, fmt)
    touch(team)
    rederive_team_net(team)


def rederive_team_net(team):
    """Recompute the five net metrics when a gross card has been posted."""
    if team.get("gross_score") is None:
        return
    metrics = calc.net_metrics(
        team.get("team_playing_handicap") or 0,
        team["gross_score"], team["gross_back_9"], team["gross_back_6"],
        team["gross_back_3"], team["gross_hole_18"],
    )
    team.update(metrics)
    touch(team)


def rederive_team_player_count(team):
    team["player_count"] = len(players_of_team(team["id"]))
    touch(team)
    rederive_team_handicap(team)


def rating_cascade(outing):
    """Contract rating change: players -> teams -> net metrics (PRD 2.8)."""
    contract = contract_of(outing["id"])
    for player in players_of_outing(outing["id"]):
        rederive_player_handicap(player, contract)
    for team in teams_of(outing["id"]):
        rederive_team_handicap(team)


# --------------------------------------------------------------------------
# Sponsorship inventory conservation (PRD 2.10)
# --------------------------------------------------------------------------
def asset_occupancy(asset):
    reserved = committed = fulfilled = 0
    for alloc in allocs_of_asset(asset["id"]):
        status = alloc["status"]
        if status in RESERVED_STATES:
            reserved += 1
        elif status in COMMITTED_STATES:
            committed += 1
        elif status in FULFILLED_STATES:
            fulfilled += 1
    return reserved, committed, fulfilled


def asset_posture(asset, reserved, committed, fulfilled):
    if asset["status"] == "WITHDRAWN":
        return "WITHDRAWN"
    if reserved + committed + fulfilled == 0:
        return "AVAILABLE"
    if committed > 0:
        return "COMMITTED"
    if reserved > 0:
        return "RESERVED"
    return "FULFILLED"


def rederive_asset(asset):
    reserved, committed, fulfilled = asset_occupancy(asset)
    asset["reserved_count"] = reserved
    asset["committed_count"] = committed
    asset["fulfilled_count"] = fulfilled
    asset["status"] = asset_posture(asset, reserved, committed, fulfilled)
    if asset["status"] == "WITHDRAWN":
        asset["remaining_capacity"] = 0
    else:
        asset["remaining_capacity"] = asset["capacity"] - (reserved + committed + fulfilled)
    touch(asset)


def rederive_reserved_asset_slots(outing):
    total = 0
    for asset in assets_of(outing["id"]):
        total += (asset["reserved_count"] + asset["committed_count"]
                  + asset["fulfilled_count"])
    outing["reserved_asset_slot_count"] = total
    touch(outing)


# --------------------------------------------------------------------------
# Registration / tier derived figures
# --------------------------------------------------------------------------
def rederive_tier_sold_count(tier):
    if tier is None:
        return
    count = 0
    for reg in regs_of(tier["outing_id"]):
        if reg["package_tier_id"] == tier["id"] and reg["status"] in REVENUE_STATES:
            count += 1
    tier["sold_count"] = count
    touch(tier)


def rederive_entitled_balance(reg):
    tier = tier_of(reg)
    if tier is None or reg["status"] not in REVENUE_STATES:
        reg["entitled_asset_balance"] = 0
        touch(reg)
        return
    used = 0
    for alloc in allocs_of_registration(reg["id"]):
        if alloc["source"] == "PACKAGE_ENTITLEMENT" and alloc["status"] != "RELEASED":
            used += 1
    balance = tier["entitled_asset_count"] - used
    reg["entitled_asset_balance"] = balance if balance > 0 else 0
    touch(reg)


def rederive_registration_fulfillment_credit(reg):
    total = 0
    for alloc in allocs_of_registration(reg["id"]):
        if alloc["status"] == "WAIVED":
            total += alloc["fulfillment_credit_cents"]
    reg["fulfillment_credit_cents"] = total
    touch(reg)


def rederive_outing_counters(outing):
    outing_id = outing["id"]
    confirmed_slots = 0
    waitlisted = 0
    for reg in regs_of(outing_id):
        if reg["status"] in REVENUE_STATES:
            confirmed_slots += reg["player_count"]
        elif reg["status"] == "WAITLISTED":
            waitlisted += 1
    checked_in = 0
    for player in players_of_outing(outing_id):
        if player["checked_in"]:
            checked_in += 1
    outing["confirmed_player_slots"] = confirmed_slots
    outing["waitlisted_registration_count"] = waitlisted
    outing["checked_in_player_count"] = checked_in
    total = 0
    for asset in assets_of(outing_id):
        total += (asset["reserved_count"] + asset["committed_count"]
                  + asset["fulfilled_count"])
    outing["reserved_asset_slot_count"] = total
    credit = 0
    for alloc in allocs_of_outing(outing_id):
        if alloc["status"] == "WAIVED":
            credit += alloc["fulfillment_credit_cents"]
    outing["fulfillment_credit_cents"] = credit
    touch(outing)


def rederive_receipted_total(outing):
    total = 0
    for receipt in receipts_of(outing["id"]):
        total += receipt["deductible_amount_cents"]
    outing["receipted_deductible_total_cents"] = total
    touch(outing)


# --------------------------------------------------------------------------
# The net-proceeds rollup (PRD 3.9)
# --------------------------------------------------------------------------
def _contract_terms(outing):
    contract = contract_of(outing["id"])
    if contract is None:
        return {
            "rate_per_player_cents": 0,
            "guaranteed_player_count": 0,
            "fnb_minimum_cents": 0,
            "fnb_per_player_cents": 0,
            "rain_credit_cents": 0,
        }
    return contract


def run_rollup(outing, variant=None):
    """Recompute the whole finance rollup in full — never incrementally patched."""
    if variant is None:
        variant = outing.get("proceeds_variant") or "PROVISIONAL"
    outing["proceeds_variant"] = variant
    rederive_outing_counters(outing)
    rederive_receipted_total(outing)
    terms = _contract_terms(outing)
    outing_id = outing["id"]

    # step 1 - gross revenue
    gross = 0
    for reg in regs_of(outing_id):
        if reg["status"] in REVENUE_STATES:
            gross += reg["amount_paid_cents"]
    for alloc in allocs_of_outing(outing_id):
        if alloc["status"] in REVENUE_ALLOCATION_STATES:
            gross += alloc["upsell_price_cents"]
    for item in items_of(outing_id):
        if item["status"] in ("PAID", "RECEIPTED"):
            gross += item["collected_cents"]

    # step 2 - refunds, over every registration whatever its status
    refunded = 0
    for reg in regs_of(outing_id):
        refunded += reg["amount_refunded_cents"]

    # steps 3 and 4 - the course charge and the food and beverage minimum
    if variant == "FINAL":
        billable = outing["checked_in_player_count"]
    else:
        billable = outing["confirmed_player_slots"]
    guaranteed = terms["guaranteed_player_count"]
    course_charge = max(billable, guaranteed) * terms["rate_per_player_cents"]
    fnb_actual = billable * terms["fnb_per_player_cents"]
    fnb_shortfall = terms["fnb_minimum_cents"] - fnb_actual
    if fnb_shortfall < 0:
        fnb_shortfall = 0

    # step 5 - prize and insurance costs
    insurance_cost = 0
    contest_payouts = 0
    for contest in contests_of(outing_id):
        if contest["insurance_status"] in INSURED_STATES:
            insurance_cost += contest["insurance_premium_cents"]
        contest_payouts += contest["contest_payout_cents"]
    if variant == "FINAL":
        awarded = 0
        for team in teams_of(outing_id):
            awarded += team["prize_award_cents"]
        prize_cost = awarded + contest_payouts
    else:
        prize_cost = outing["prize_pool_cents"] + contest_payouts

    # step 6 - direct costs
    direct_costs = (course_charge + fnb_shortfall + insurance_cost + prize_cost
                    - terms["rain_credit_cents"])
    if variant == "FINAL":
        direct_costs += outing["fulfillment_credit_cents"]

    # step 7 - the administrative fee, in the pinned order
    net_before_fee = gross - refunded - direct_costs
    fee_pct = calc.admin_fee_pct(net_before_fee)
    fee = calc.pct_of(fee_pct, gross) if fee_pct else 0

    outing["gross_revenue_cents"] = gross
    outing["refunded_cents"] = refunded
    outing["course_charge_cents"] = course_charge
    outing["fnb_shortfall_cents"] = fnb_shortfall
    outing["insurance_cost_cents"] = insurance_cost
    outing["prize_cost_cents"] = prize_cost
    outing["direct_costs_cents"] = direct_costs
    outing["net_proceeds_before_fee_cents"] = net_before_fee
    outing["admin_fee_pct"] = fee_pct
    outing["admin_fee_cents"] = fee
    outing["net_proceeds_cents"] = net_before_fee - fee
    touch(outing)


# --------------------------------------------------------------------------
# Ranking and prize distribution (PRD 3.8)
# --------------------------------------------------------------------------
def rank_and_distribute(outing):
    teams = teams_of(outing["id"])
    for team in teams:
        rederive_team_net(team)
    ordered = sorted(teams, key=lambda t: (
        t["net_score"], t["net_back_9"], t["net_back_6"], t["net_back_3"],
        t["net_hole_18"], t["team_playing_handicap"], t["created_at"], t["_seq"],
    ))
    for index, team in enumerate(ordered):
        team["rank_position"] = index + 1
        touch(team)
    eligible = []
    for team in ordered:
        professional = False
        for player in players_of_team(team["id"]):
            if player["amateur_status"] == "PROFESSIONAL":
                professional = True
                break
        team["prize_eligible"] = not professional
        team["prize_award_cents"] = 0
        touch(team)
        if not professional:
            eligible.append(team)
    awards = calc.prize_awards(outing["prize_pool_cents"], len(eligible))
    for team, award in zip(eligible, awards):
        team["prize_award_cents"] = award
        touch(team)
    total_awarded = 0
    for team in teams:
        total_awarded += team["prize_award_cents"]
    outing["unclaimed_prize_cents"] = outing["prize_pool_cents"] - total_awarded
    touch(outing)


# --------------------------------------------------------------------------
# Waitlist promotion (PRD 3.2 step 7)
# --------------------------------------------------------------------------
def promote_from_waitlist(outing, freed_slots):
    """Promote at most one waitlisted registration; returns it or None."""
    if outing["play_status"] != "OPEN":
        return None
    candidates = []
    for reg in regs_of(outing["id"]):
        if reg["status"] == "WAITLISTED" and reg["player_count"] <= freed_slots:
            candidates.append(reg)
    if not candidates:
        return None

    def price_of(reg):
        tier = tier_of(reg)
        return tier["price_cents"] if tier else 0

    candidates.sort(key=lambda r: (-price_of(r), r["created_at"], r["_seq"]))
    winner = candidates[0]
    winner["status"] = "CONFIRMED"
    winner["confirmed_at"] = store.now_iso()
    touch(winner)
    snapshot_registration_players(winner)
    rederive_entitled_balance(winner)
    rederive_tier_sold_count(tier_of(winner))
    rederive_outing_counters(outing)
    return winner


# --------------------------------------------------------------------------
# Allocation release (PRD 3.4) — the compensating action
# --------------------------------------------------------------------------
def release_allocation(alloc):
    """Release one occupying allocation and settle the inventory chain."""
    alloc["status"] = "RELEASED"
    touch(alloc)
    asset = store.sponsorship_assets.get(alloc["sponsorship_asset_id"])
    if asset is not None:
        rederive_asset(asset)
    reg = store.registrations.get(alloc["registration_id"])
    if reg is not None:
        rederive_entitled_balance(reg)
        rederive_registration_fulfillment_credit(reg)


# --------------------------------------------------------------------------
# Receipts (PRD 3.7)
# --------------------------------------------------------------------------
def next_receipt_number(outing_id):
    return "GR-%04d" % (len(receipts_of(outing_id)) + 1,)


def reversal_of(receipt_id):
    for row in store.receipts.values():
        if row.get("reverses_receipt_id") == receipt_id:
            return row
    return None


def live_forward_receipt(outing_id, registration_id=None, fundraising_item_id=None):
    """The un-reversed forward receipt for a subject, if one exists."""
    for row in receipts_of(outing_id):
        if row["receipt_kind"] == "REVERSAL":
            continue
        if registration_id is not None and row.get("registration_id") != registration_id:
            continue
        if (fundraising_item_id is not None
                and row.get("fundraising_item_id") != fundraising_item_id):
            continue
        if reversal_of(row["id"]) is None:
            return row
    return None


def append_reversal(original, issued_by_user_id):
    """Append a REVERSAL row mirroring the original with every sign flipped."""
    outing_id = original["outing_id"]
    row = store.new_row("CharitableReceipt", {
        "outing_id": outing_id,
        "receipt_kind": "REVERSAL",
        "registration_id": None,
        "fundraising_item_id": None,
        "reverses_receipt_id": original["id"],
        "payment_cents": -original["payment_cents"],
        "gsv_cents": -original["gsv_cents"],
        "deductible_amount_cents": -original["deductible_amount_cents"],
        "receipt_number": next_receipt_number(outing_id),
        "issued_by_user_id": issued_by_user_id,
        "issued_at": store.now_iso(),
    }, common=False)
    if original.get("registration_id"):
        reg = store.registrations.get(original["registration_id"])
        if reg is not None:
            reg["receipt_issued"] = False
            touch(reg)
    if original.get("fundraising_item_id"):
        item = store.fundraising_items.get(original["fundraising_item_id"])
        if item is not None and item["status"] == "RECEIPTED":
            item["status"] = "PAID"
            touch(item)
    outing = store.outings.get(outing_id)
    if outing is not None:
        rederive_receipted_total(outing)
    return row
