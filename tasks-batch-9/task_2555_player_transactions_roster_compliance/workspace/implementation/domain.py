"""Domain helpers: lookups, player service time, cap recomputation, compliance."""
import calc
from errors import fail
from store import UTC, base_record, db, fmt_ms, fmt_ts, hours, days, touch, values

ROSTERED_DESIGNATIONS = ("ACTIVE", "RESERVE", "INJURED_RESERVE", "PRACTICE_SQUAD")
ALL_DESIGNATIONS = ROSTERED_DESIGNATIONS + ("UNROSTERED", "WAIVED_PENDING")

DESIGNATION_BUCKET = {
    "ACTIVE": "accrued_active_days",
    "RESERVE": "accrued_reserve_days",
    "INJURED_RESERVE": "accrued_ir_days",
    "PRACTICE_SQUAD": "accrued_practice_days",
}
DESIGNATION_COUNT = {
    "ACTIVE": "active_roster_count",
    "RESERVE": "reserve_roster_count",
    "INJURED_RESERVE": "injured_reserve_count",
    "PRACTICE_SQUAD": "practice_squad_count",
}
DESIGNATION_LIMIT = {
    "ACTIVE": "active_roster_limit",
    "RESERVE": "reserve_roster_limit",
    "INJURED_RESERVE": "injured_reserve_limit",
    "PRACTICE_SQUAD": "practice_squad_limit",
}

PROVISIONAL_CONTRACT_STATUSES = ("PENDING_APPROVAL", "ACTIVE")
PROVISIONAL_BONUS_TYPES = ("ROSTER_BONUS", "PERFORMANCE_LTBE")
FINAL_BONUS_TYPES = ("ROSTER_BONUS", "PERFORMANCE_LTBE", "PERFORMANCE_NLTBE")

FROZEN_STATUSES = ("NON_COMPLIANT", "TRANSACTION_FROZEN")
OPEN_DESIGNATION_STATUSES = (
    "PENDING_PAPERWORK", "PAPERWORK_FILED", "ACTIVE", "RETURN_WINDOW_OPEN",
)


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def _get(collection, key, error_id):
    record = collection.get(key) if isinstance(key, str) else None
    if record is None:
        fail(error_id, "resource not found")
    return record


def get_team(team_id):
    return _get(db.teams, team_id, "ERR_TEAM_NOT_FOUND")


def get_player(player_id):
    return _get(db.players, player_id, "ERR_PLAYER_NOT_FOUND")


def get_contract(contract_id):
    return _get(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")


def get_allocation(allocation_id):
    return _get(db.bonus_allocations, allocation_id, "ERR_BONUS_ALLOCATION_NOT_FOUND")


def get_transaction(transaction_id):
    return _get(db.transactions, transaction_id, "ERR_TRANSACTION_NOT_FOUND")


def get_waiver_request(waiver_request_id):
    return _get(db.waiver_requests, waiver_request_id, "ERR_WAIVER_REQUEST_NOT_FOUND")


def get_waiver_claim(claim_id):
    return _get(db.waiver_claims, claim_id, "ERR_WAIVER_CLAIM_NOT_FOUND")


def get_trade(trade_id):
    return _get(db.trades, trade_id, "ERR_TRADE_NOT_FOUND")


def get_tender(tender_id):
    return _get(db.qualifying_offers, tender_id, "ERR_TENDER_NOT_FOUND")


def get_designation(designation_id):
    return _get(db.injury_designations, designation_id, "ERR_INJURY_DESIGNATION_NOT_FOUND")


def get_exam(exam_id):
    return _get(db.physical_exams, exam_id, "ERR_PHYSICAL_EXAM_NOT_FOUND")


def require_window():
    """Validation rule 22: the four gated operations need the daily window."""
    if not calc.in_window(db.clock):
        fail("ERR_OUTSIDE_PROCESSING_WINDOW", "outside the daily processing window")


def require_not_frozen(team):
    """Validation rule 15."""
    if team["compliance_status"] in FROZEN_STATUSES:
        fail("ERR_TEAM_TRANSACTIONS_FROZEN", "club transactions are frozen")


def require_occ(supplied, record, error_id):
    if supplied != record["version"]:
        fail(error_id, "stale version")


# --------------------------------------------------------------------------
# Player service time (PRD 3.2)
# --------------------------------------------------------------------------
def pension_credit_days(player):
    return (
        player["accrued_active_days"]
        + player["accrued_reserve_days"]
        + player["accrued_ir_days"]
    )


def roster_service_days(player):
    return (
        player["accrued_active_days"]
        + player["accrued_reserve_days"]
        + player["accrued_ir_days"] // 2
    )


def service_years(player):
    return calc.service_years_from_days(pension_credit_days(player))


def contract_rights_class(player):
    return calc.rights_class(service_years(player))


def practice_squad_eligible(player):
    return (
        roster_service_days(player) <= calc.PRACTICE_SQUAD_MAX_ROSTER_SERVICE_DAYS
        and player["practice_squad_seasons_used"] < calc.PRACTICE_SQUAD_MAX_SEASONS
    )


def waiver_revocability_class(instant=None):
    moment = instant if instant is not None else db.clock
    if moment < calc.WAIVER_IRREVOCABLE_CUTOFF:
        return "REVOCABLE"
    return "IRREVOCABLE"


def accrue_outgoing(player):
    """Add whole elapsed days to the outgoing bucket, then reset the baseline."""
    bucket = DESIGNATION_BUCKET.get(player["roster_designation"])
    if bucket:
        earned = calc.elapsed_days(player["designation_effective_at"], db.clock)
        player[bucket] = player[bucket] + earned
    player["designation_effective_at"] = db.clock


_UNSET = object()


def set_designation(player, designation, team_id=_UNSET):
    accrue_outgoing(player)
    player["roster_designation"] = designation
    if team_id is not _UNSET:
        player["current_team_id"] = team_id
    if designation == "UNROSTERED":
        player["current_team_id"] = None
    touch(player)


def player_active_contract(player):
    for contract in values(db.contracts, lambda c: c["player_id"] == player["id"]):
        if contract["status"] == "ACTIVE":
            return contract
    return None


def last_physical_passed_at(player):
    best = None
    for exam in values(db.physical_exams, lambda e: e["player_id"] == player["id"]):
        if exam["status"] == "PASSED" and exam["performed_at"] is not None:
            if best is None or exam["performed_at"] > best:
                best = exam["performed_at"]
    return best


def citable_physical(player_id, transaction_id=None):
    """A PASSED exam whose expires_at is strictly later than the clock."""
    for exam in values(db.physical_exams, lambda e: e["player_id"] == player_id):
        if exam["status"] != "PASSED":
            continue
        if exam["expires_at"] is None or exam["expires_at"] <= db.clock:
            continue
        if transaction_id is not None and exam["transaction_id"] not in (None, transaction_id):
            continue
        return exam
    return None


# --------------------------------------------------------------------------
# Contract economics (PRD 3.4)
# --------------------------------------------------------------------------
def recompute_contract_charge(contract):
    share = calc.current_season_share(
        contract["years"],
        contract["start_season_year"],
        contract["annual_proration_cents"],
        contract["final_season_proration_cents"],
    )
    contract["current_season_cap_charge_cents"] = contract["base_salary_cents"] + share
    contract["total_value_cents"] = (
        contract["base_salary_cents"] * contract["years"] + contract["signing_bonus_cents"]
    )


def apply_proration(contract):
    span, annual, final = calc.proration(
        contract["signing_bonus_cents"], contract["years"]
    )
    contract["proration_years"] = span
    contract["annual_proration_cents"] = annual
    contract["final_season_proration_cents"] = final
    recompute_contract_charge(contract)


def new_allocation(contract, bonus_type, season_year, amount_cents):
    record = base_record()
    record.update({
        "contract_id": contract["id"],
        "bonus_type": bonus_type,
        "season_year": season_year,
        "amount_cents": amount_cents,
        "allocation_status": "SCHEDULED",
        "counts_against_provisional": bonus_type in PROVISIONAL_BONUS_TYPES,
        "earned_at": None,
    })
    db.bonus_allocations[record["id"]] = record
    return record


def materialise_allocations(contract, ltbe_cents, nltbe_cents):
    span = contract["proration_years"]
    for index in range(span):
        amount = contract["annual_proration_cents"]
        if index == span - 1:
            amount = contract["final_season_proration_cents"]
        new_allocation(
            contract, "SIGNING_PRORATION", contract["start_season_year"] + index, amount
        )
    if ltbe_cents and ltbe_cents > 0:
        new_allocation(
            contract, "PERFORMANCE_LTBE", contract["start_season_year"], ltbe_cents
        )
    if nltbe_cents and nltbe_cents > 0:
        new_allocation(
            contract, "PERFORMANCE_NLTBE", contract["start_season_year"], nltbe_cents
        )


def contract_allocations(contract_id):
    return values(db.bonus_allocations, lambda a: a["contract_id"] == contract_id)


def terminate_contract(contract, reason):
    """The single termination cascade shared by all three routes."""
    contract["status"] = "TERMINATED"
    contract["termination_reason"] = reason
    current, following = calc.dead_money_split(
        contract["signing_bonus_cents"],
        contract["annual_proration_cents"],
        contract["start_season_year"],
        db.clock,
    )
    if reason == "RELEASE_CLEARED" and contract["base_guaranteed"]:
        current = current + contract["base_salary_cents"]
    contract["dead_money_current_season_cents"] = current
    contract["dead_money_next_season_cents"] = following
    for allocation in contract_allocations(contract["id"]):
        if allocation["allocation_status"] != "SCHEDULED":
            continue
        if allocation["bonus_type"] == "SIGNING_PRORATION":
            if allocation["season_year"] >= calc.CURRENT_SEASON_YEAR:
                allocation["allocation_status"] = "ACCELERATED"
                touch(allocation)
        else:
            allocation["allocation_status"] = "FORFEITED"
            touch(allocation)
    touch(contract)


def void_contract(contract):
    contract["status"] = "VOIDED"
    touch(contract)


# --------------------------------------------------------------------------
# Club roster counts, cap totals and compliance posture (PRD 3.1 / 3.9)
# --------------------------------------------------------------------------
def team_players(team_id):
    return values(db.players, lambda p: p["current_team_id"] == team_id)


def team_contracts(team_id):
    return values(db.contracts, lambda c: c["team_id"] == team_id)


def recompute_counts(team):
    fresh = dict((field, 0) for field in DESIGNATION_COUNT.values())
    for player in team_players(team["id"]):
        field = DESIGNATION_COUNT.get(player["roster_designation"])
        if field:
            fresh[field] = fresh[field] + 1
    team.update(fresh)


def team_dead_money(team_id):
    total = 0
    for contract in db.contracts.values():
        if contract["team_id"] == team_id and contract["status"] == "TERMINATED":
            total += contract["dead_money_current_season_cents"]
    for wire in db.waiver_requests.values():
        if wire["from_team_id"] == team_id and wire["status"] == "CLAIMED":
            total += wire["releasing_team_dead_money_cents"]
    return total


def recompute_cap(team):
    provisional = 0
    final = 0
    for contract in team_contracts(team["id"]):
        allocations = contract_allocations(contract["id"])
        if contract["status"] in PROVISIONAL_CONTRACT_STATUSES:
            provisional += contract["current_season_cap_charge_cents"]
            for allocation in allocations:
                if (
                    allocation["counts_against_provisional"]
                    and allocation["season_year"] == calc.CURRENT_SEASON_YEAR
                    and allocation["allocation_status"] in ("SCHEDULED", "EARNED")
                ):
                    provisional += allocation["amount_cents"]
        if contract["status"] == "ACTIVE":
            final += contract["current_season_cap_charge_cents"]
            for allocation in allocations:
                if (
                    allocation["bonus_type"] in FINAL_BONUS_TYPES
                    and allocation["season_year"] == calc.CURRENT_SEASON_YEAR
                    and allocation["allocation_status"] == "EARNED"
                ):
                    final += allocation["amount_cents"]
    dead_money = team_dead_money(team["id"])
    team["dead_money_cents"] = dead_money
    team["provisional_cap_committed_cents"] = provisional + dead_money
    team["final_cap_committed_cents"] = final + dead_money
    team["cap_space_cents"] = (
        team["salary_cap_limit_cents"] - team["provisional_cap_committed_cents"]
    )


def recompute_medical_reviews(team):
    count = 0
    for trade in db.trades.values():
        if trade["status"] != "MEDICAL_REVIEW":
            continue
        if team["id"] in (trade["initiating_team_id"], trade["counterparty_team_id"]):
            count += 1
    team["open_medical_review_count"] = count


def violation_codes(team):
    codes = []
    if team["active_roster_count"] > team["active_roster_limit"]:
        codes.append("ACTIVE_ROSTER_OVER_LIMIT")
    if team["reserve_roster_count"] > team["reserve_roster_limit"]:
        codes.append("RESERVE_OVER_LIMIT")
    if team["injured_reserve_count"] > team["injured_reserve_limit"]:
        codes.append("IR_OVER_LIMIT")
    if team["practice_squad_count"] > team["practice_squad_limit"]:
        codes.append("PRACTICE_SQUAD_OVER_LIMIT")
    if team["provisional_cap_committed_cents"] > team["salary_cap_limit_cents"]:
        codes.append("CAP_OVER_LIMIT")
    for player in team_players(team["id"]):
        if player["roster_designation"] == "PRACTICE_SQUAD" and not practice_squad_eligible(player):
            codes.append("INELIGIBLE_PRACTICE_SQUAD_PLAYER")
            break
    for designation in values(db.injury_designations, lambda d: d["team_id"] == team["id"]):
        if designation["status"] != "PENDING_PAPERWORK":
            continue
        due = designation["created_at"] + hours(calc.PAPERWORK_GRACE_HOURS)
        if db.clock >= due:
            codes.append("UNFILED_INJURY_PAPERWORK")
            break
    return codes


def apply_event_posture(team):
    """Event mode: the only ladder edge it may take is COMPLIANT -> GRACE."""
    codes = violation_codes(team)
    if codes and team["compliance_status"] == "COMPLIANT":
        team["compliance_status"] = "GRACE"
        team["grace_expires_at"] = db.clock + hours(calc.GRACE_PERIOD_HOURS)
        team["consecutive_noncompliant_checks"] = 1
    return codes


def recompute_team(team, event=False):
    recompute_counts(team)
    recompute_cap(team)
    recompute_medical_reviews(team)
    if event:
        apply_event_posture(team)
    return team


def projected_counts(team, moves):
    """moves is a list of (outgoing_designation, incoming_designation) pairs."""
    recompute_counts(team)
    projected = dict((key, team[field]) for key, field in DESIGNATION_COUNT.items())
    for outgoing, incoming in moves:
        if outgoing in projected:
            projected[outgoing] = projected[outgoing] - 1
        if incoming in projected:
            projected[incoming] = projected[incoming] + 1
    return projected


def require_projected_quotas(team, moves):
    """Validation rule 36: every one of the four quotas must still be satisfied."""
    projected = projected_counts(team, moves)
    for designation, count in projected.items():
        if count > team[DESIGNATION_LIMIT[designation]]:
            fail("ERR_ROSTER_LIMIT_EXCEEDED", "%s quota exceeded" % designation)


def require_room_for(team, designation):
    recompute_counts(team)
    if team[DESIGNATION_COUNT[designation]] >= team[DESIGNATION_LIMIT[designation]]:
        fail("ERR_ROSTER_LIMIT_EXCEEDED", "%s quota exceeded" % designation)


# --------------------------------------------------------------------------
# Trade helpers (PRD 3.7)
# --------------------------------------------------------------------------
def trade_assets(trade_id):
    return values(db.trade_assets, lambda a: a["trade_id"] == trade_id)


def proposed_assets(trade_id):
    return [a for a in trade_assets(trade_id) if a["status"] == "PROPOSED"]


def recompute_trade_deltas(trade):
    incoming_initiator = 0
    incoming_counterparty = 0
    for asset in proposed_assets(trade["id"]):
        amount = asset["cap_charge_snapshot_cents"] or 0
        if asset["direction"] == "TO_INITIATOR":
            incoming_initiator += amount
        else:
            incoming_counterparty += amount
    trade["cap_delta_initiating_cents"] = incoming_initiator - incoming_counterparty
    trade["cap_delta_counterparty_cents"] = incoming_counterparty - incoming_initiator


def trade_clubs(trade):
    return (
        db.teams.get(trade["initiating_team_id"]),
        db.teams.get(trade["counterparty_team_id"]),
    )


def void_trade(trade, reason):
    was_medical_review = trade["status"] == "MEDICAL_REVIEW"
    trade["status"] = "VOIDED"
    trade["void_reason"] = reason
    for asset in trade_assets(trade["id"]):
        if asset["status"] == "PROPOSED":
            asset["status"] = "RETURNED"
            touch(asset)
    recompute_trade_deltas(trade)
    touch(trade)
    if was_medical_review:
        for club in trade_clubs(trade):
            if club is not None:
                recompute_team(club)
    return trade
