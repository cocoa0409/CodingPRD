"""The daily compliance sweep (PRD 3.9)."""
from flask import Blueprint

import calc
import domain
import shape
import views
from auth import LEAGUE_OFFICER, endpoint
from envelope import single
from store import base_record, db, hours, touch, values

bp = Blueprint("compliance", __name__)


def _recompute(team_ids):
    for team_id in team_ids:
        club = db.teams.get(team_id)
        if club is not None:
            domain.recompute_team(club)


def _step_one_void_stale_drafts(affected):
    """Void every DRAFT filing whose filing_deadline_at the clock has passed."""
    for filing in values(db.transactions, lambda t: t["status"] == "DRAFT"):
        deadline = filing["filing_deadline_at"]
        if deadline is None or db.clock <= deadline:
            continue
        filing["status"] = "VOIDED"
        touch(filing)
        if filing["transaction_type"] == "SIGNING" and filing["contract_id"]:
            contract = db.contracts.get(filing["contract_id"])
            if contract is not None and contract["status"] == "PENDING_APPROVAL":
                domain.void_contract(contract)
        affected.add(filing["team_id"])


def _step_two_lapse_decisions(affected):
    """Lapse expired tenders, then expired contract options."""
    for tender in values(db.qualifying_offers, lambda t: t["status"] == "ISSUED"):
        if tender["deadline_at"] is None or db.clock <= tender["deadline_at"]:
            continue
        tender["status"] = "LAPSED"
        touch(tender)
        affected.add(tender["team_id"])
    for contract in values(db.contracts, lambda c: c["option_status"] == "PENDING"):
        deadline = contract["option_deadline_at"]
        if deadline is None or db.clock <= deadline:
            continue
        contract["option_status"] = "LAPSED"
        if contract["status"] == "ACTIVE":
            domain.terminate_contract(contract, "OPTION_LAPSED")
            player = db.players.get(contract["player_id"])
            if player is not None:
                domain.set_designation(player, "UNROSTERED", team_id=None)
        else:
            touch(contract)
        affected.add(contract["team_id"])


def _step_three_void_medical_reviews(affected):
    """Void every MEDICAL_REVIEW trade whose medical_review_deadline_at has passed."""
    for trade in values(db.trades, lambda t: t["status"] == "MEDICAL_REVIEW"):
        deadline = trade["medical_review_deadline_at"]
        if deadline is None or db.clock <= deadline:
            continue
        domain.void_trade(trade, "MEDICAL_WINDOW_EXPIRED")
        affected.add(trade["initiating_team_id"])
        affected.add(trade["counterparty_team_id"])


def _expire_designation(designation):
    designation["status"] = "EXPIRED"
    designation["closed_at"] = db.clock
    designation["ir_service_credit_days"] = calc.elapsed_days(
        designation["activated_at"], designation["closed_at"]
    )
    touch(designation)


def _step_four_return_windows(affected):
    """Open the return window on the clock, or shut the door on it."""
    for designation in values(
        db.injury_designations,
        lambda d: d["status"] in ("ACTIVE", "RETURN_WINDOW_OPEN"),
    ):
        opens = designation["return_window_opens_at"]
        closes = designation["return_window_closes_at"]
        if closes is not None and db.clock > closes:
            _expire_designation(designation)
            affected.add(designation["team_id"])
            continue
        if designation["status"] != "ACTIVE":
            continue
        if opens is not None and db.clock >= opens:
            designation["status"] = "RETURN_WINDOW_OPEN"
            touch(designation)


def _step_five_expire_physicals(affected):
    """A physical stops being citable the instant expires_at arrives."""
    for exam in values(db.physical_exams, lambda e: e["status"] == "PASSED"):
        if exam["expires_at"] is None or db.clock < exam["expires_at"]:
            continue
        exam["status"] = "EXPIRED"
        touch(exam)


def _clock_driven_steps():
    affected = set()
    _step_one_void_stale_drafts(affected)
    _step_two_lapse_decisions(affected)
    _step_three_void_medical_reviews(affected)
    _step_four_return_windows(affected)
    _step_five_expire_physicals(affected)
    _recompute(affected)


def _walk_ladder(team, codes):
    """The sweep-mode posture ladder of PRD 3.9. Returns the record's `result`."""
    if not codes:
        team["compliance_status"] = "COMPLIANT"
        team["grace_expires_at"] = None
        team["consecutive_noncompliant_checks"] = 0
        return "COMPLIANT"
    posture = team["compliance_status"]
    if posture == "COMPLIANT":
        team["compliance_status"] = "GRACE"
        team["grace_expires_at"] = db.clock + hours(calc.GRACE_PERIOD_HOURS)
        team["consecutive_noncompliant_checks"] = 1
        return "GRACE"
    if posture == "GRACE":
        expiry = team["grace_expires_at"]
        if expiry is not None and db.clock < expiry:
            return "GRACE"
        team["compliance_status"] = "NON_COMPLIANT"
        team["grace_expires_at"] = None
        team["consecutive_noncompliant_checks"] = 2
        return "NON_COMPLIANT"
    counter = team["consecutive_noncompliant_checks"] + 1
    team["consecutive_noncompliant_checks"] = counter
    if posture == "NON_COMPLIANT" and counter >= calc.FREEZE_AFTER_CONSECUTIVE_CHECKS:
        team["compliance_status"] = "TRANSACTION_FROZEN"
    return "NON_COMPLIANT"


@bp.route("/compliance-checks/run", methods=["POST"])
@endpoint(LEAGUE_OFFICER)
def run_sweep(actor):
    body = shape.body()
    team_id = shape.req_ref(body, "team_id")
    team = domain.get_team(team_id)
    _clock_driven_steps()
    domain.recompute_team(team)
    codes = domain.violation_codes(team)
    checked_at = db.clock
    result = _walk_ladder(team, codes)
    record = base_record()
    record.update({
        "team_id": team["id"],
        "checked_at": checked_at,
        "active_roster_count": team["active_roster_count"],
        "reserve_roster_count": team["reserve_roster_count"],
        "injured_reserve_count": team["injured_reserve_count"],
        "practice_squad_count": team["practice_squad_count"],
        "final_cap_committed_cents": team["final_cap_committed_cents"],
        "cap_space_cents": (
            team["salary_cap_limit_cents"] - team["final_cap_committed_cents"]
        ),
        "violation_codes": codes,
        "result": result,
        "grace_expires_at": team["grace_expires_at"] if result == "GRACE" else None,
        "resulting_compliance_status": team["compliance_status"],
    })
    db.compliance_checks[record["id"]] = record
    touch(team)
    return single(views.compliance_check(record), 201)
