"""Outing endpoints: creation, reads, and the two lifecycle dimensions."""

from flask import Blueprint

import calc
import derive
import enums
import serial
import store
import validate
from auth import (BENEFICIARY, CHARITY_TREASURER, COURSE_OPERATIONS,
                  PARTICIPANT, SPONSORSHIP_MANAGER, TOURNAMENT_DIRECTOR, auth)
from envelope import created, ok, paginate
from errors import fail
from lookup import outing as get_outing
from store import touch

bp = Blueprint("outings", __name__)

READ_ROLES = (TOURNAMENT_DIRECTOR, SPONSORSHIP_MANAGER, CHARITY_TREASURER,
              COURSE_OPERATIONS, BENEFICIARY)

CREATE_FIELDS = ("name", "beneficiary_name", "format", "start_format",
                 "scheduled_date", "wave_a_start", "wave_a_end",
                 "field_capacity_teams", "prize_pool_cents", "rain_date",
                 "wave_b_start", "wave_b_end")

ZERO_ROLLUP_FIELDS = (
    "confirmed_player_slots", "checked_in_player_count",
    "waitlisted_registration_count", "reserved_asset_slot_count",
    "gross_revenue_cents", "refunded_cents", "course_charge_cents",
    "fnb_shortfall_cents", "insurance_cost_cents", "prize_cost_cents",
    "fulfillment_credit_cents", "direct_costs_cents",
    "net_proceeds_before_fee_cents", "admin_fee_cents", "net_proceeds_cents",
    "unclaimed_prize_cents", "receipted_deductible_total_cents",
    "beneficiary_remittance_cents", "reopen_count",
)


@bp.post("/outing-ops/outings")
def create_outing():
    auth((TOURNAMENT_DIRECTOR,))
    body = validate.body()
    validate.only_fields(body, CREATE_FIELDS)
    fields = {
        "name": validate.req_str(body, "name"),
        "beneficiary_name": validate.req_str(body, "beneficiary_name"),
        "format": validate.req_enum(body, "format", enums.OUTING_FORMAT),
        "start_format": validate.req_enum(body, "start_format", enums.START_FORMAT),
        "scheduled_date": validate.req_ts(body, "scheduled_date"),
        "wave_a_start": validate.req_ts(body, "wave_a_start"),
        "wave_a_end": validate.req_ts(body, "wave_a_end"),
        "field_capacity_teams": validate.req_int(body, "field_capacity_teams", minimum=1),
        "prize_pool_cents": validate.req_money(body, "prize_pool_cents"),
        "rain_date": validate.opt_ts(body, "rain_date"),
        "wave_b_start": validate.opt_ts(body, "wave_b_start"),
        "wave_b_end": validate.opt_ts(body, "wave_b_end"),
        "play_status": "DRAFT",
        "finance_status": "COLLECTING",
        "postponed_from_date": None,
        "proceeds_variant": "PROVISIONAL",
        "remittance_reference": None,
        "admin_fee_pct": 0,
    }
    for name in ZERO_ROLLUP_FIELDS:
        fields[name] = 0
    row = store.new_row("Outing", fields)
    return created(serial.dump(row))


@bp.get("/outing-ops/outings/<row_id>")
def read_outing(row_id):
    auth(READ_ROLES)
    row = get_outing(row_id)
    return ok(serial.dump(row))


@bp.get("/outing-ops/outings")
def list_outings():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    play_status = validate.q_enum("play_status", enums.PLAY_STATUS)
    finance_status = validate.q_enum("finance_status", enums.FINANCE_STATUS)
    rows = store.sorted_rows(list(store.outings.values()))
    if play_status is not None:
        rows = [r for r in rows if r["play_status"] == play_status]
    if finance_status is not None:
        rows = [r for r in rows if r["finance_status"] == finance_status]
    return paginate(rows, limit, offset, serial.dump)


@bp.get("/outing-ops/outings/<row_id>/proceeds-report")
def proceeds_report(row_id):
    auth((CHARITY_TREASURER, TOURNAMENT_DIRECTOR, BENEFICIARY))
    row = get_outing(row_id)
    return ok(serial.proceeds_report(row))


@bp.get("/outing-ops/outings/<row_id>/pairing-sheet")
def pairing_sheet(row_id):
    auth((TOURNAMENT_DIRECTOR, COURSE_OPERATIONS, PARTICIPANT))
    limit, offset = validate.page_params()
    wave = validate.q_enum("wave", enums.WAVE)
    row = get_outing(row_id)
    teams = derive.teams_of(row["id"])
    if wave is not None:
        teams = [t for t in teams if t["wave"] == wave]
    teams.sort(key=lambda t: (
        t["wave"] is None, t["wave"] or "",
        t["starting_hole"] is None, t["starting_hole"] or 0,
        t["tee_time"] is None, t["tee_time"] or "",
        t["created_at"], t["_seq"],
    ))
    return paginate(teams, limit, offset, serial.dump)


# --------------------------------------------------------------------------
# The play dimension (PRD 3.1)
# --------------------------------------------------------------------------
GROSS_FIELDS = ("gross_score", "gross_back_9", "gross_back_6", "gross_back_3",
                "gross_hole_18")
PLACEMENT_FIELDS = ("wave", "starting_hole", "tee_time", "cart_number",
                    "slot_occupancy_start", "slot_occupancy_end")


@bp.post("/outing-ops/outings/<row_id>/play-transition")
def play_transition(row_id):
    auth((TOURNAMENT_DIRECTOR,))
    body = validate.body()
    validate.only_fields(body, ("action", "rain_date"))
    action = validate.req_enum(body, "action", enums.PLAY_ACTIONS)
    rain_date = validate.opt_ts(body, "rain_date")
    outing = get_outing(row_id)
    if action == "OPEN_REGISTRATION":
        _open_registration(outing)
    elif action == "LOCK_FIELD":
        _lock_field(outing)
    elif action == "START_PLAY":
        _start_play(outing)
    elif action == "FINALIZE_SCORING":
        _finalize_scoring(outing)
    elif action == "POSTPONE":
        _postpone(outing, rain_date)
    elif action == "RESUME":
        _resume(outing)
    else:
        _cancel_outing(outing)
    touch(outing)
    return ok(serial.dump(outing))


def _open_registration(outing):
    status = outing["play_status"]
    if status == "DRAFT":
        contract = derive.contract_of(outing["id"])
        if contract is None or contract["status"] not in ("SIGNED", "AMENDED"):
            fail("ERR_CONTRACT_NOT_SIGNED",
                 "The outing has no signed course contract.")
        if not derive.tiers_of(outing["id"]):
            fail("ERR_NO_PACKAGE_TIER", "The outing has no package tier.")
        outing["play_status"] = "OPEN"
        return
    if status == "FIELD_LOCKED":
        if outing["reopen_count"] >= calc.MAX_FIELD_REOPENS:
            fail("ERR_MAX_REOPENS_EXCEEDED",
                 "The field has already been reopened twice.")
        outing["play_status"] = "OPEN"
        outing["reopen_count"] = outing["reopen_count"] + 1
        contract = derive.contract_of(outing["id"])
        for player in derive.players_of_outing(outing["id"]):
            if player["effective_handicap_index"] is not None:
                player["effective_handicap_index"] = None
                touch(player)
            derive.rederive_player_handicap(player, contract, use_effective=False)
        for team in derive.teams_of(outing["id"]):
            derive.rederive_team_handicap(team, "PROVISIONAL")
        return
    fail("ERR_INVALID_STATE_TRANSITION",
         "OPEN_REGISTRATION is not an edge out of %s." % status)


def _lock_field(outing):
    if outing["play_status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION",
             "LOCK_FIELD is not an edge out of %s." % outing["play_status"])
    teams = derive.teams_of(outing["id"])
    if not teams:
        fail("ERR_TEAM_INCOMPLETE", "The outing has no team.")
    for team in teams:
        if team["player_count"] != 4:
            fail("ERR_TEAM_INCOMPLETE",
                 "Team %s does not hold four players." % team["id"])
    outing["play_status"] = "FIELD_LOCKED"
    contract = derive.contract_of(outing["id"])
    for player in derive.players_of_outing(outing["id"]):
        reg = derive.registration_of_player(player)
        if not derive.is_revenue(reg):
            continue
        player["effective_handicap_index"] = calc.sandbag_capped_index(
            player["handicap_index"], player["handicap_index_at_confirm"])
        player["course_handicap"] = derive.player_course_handicap(
            player, contract, True)
        touch(player)
    for team in teams:
        derive.rederive_team_handicap(team, "LOCKED")


def _start_play(outing):
    if outing["play_status"] != "FIELD_LOCKED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "START_PLAY is not an edge out of %s." % outing["play_status"])
    for team in derive.teams_of(outing["id"]):
        if team["tee_assignment_count"] < 1 or team["starting_hole"] is None:
            fail("ERR_MISSING_TEE_ASSIGNMENT",
                 "Team %s has no tee assignment." % team["id"])
    outing["play_status"] = "IN_PLAY"


def _finalize_scoring(outing):
    if outing["play_status"] != "IN_PLAY":
        fail("ERR_INVALID_STATE_TRANSITION",
             "FINALIZE_SCORING is not an edge out of %s." % outing["play_status"])
    teams = derive.teams_of(outing["id"])
    for team in teams:
        for name in GROSS_FIELDS:
            if team[name] is None:
                fail("ERR_MISSING_SCORES",
                     "Team %s has not posted a complete card." % team["id"])
    payouts = 0
    for contest in derive.contests_of(outing["id"]):
        if contest["status"] == "OPEN":
            fail("ERR_MISSING_SCORES",
                 "Contest %s is still open." % contest["id"])
        payouts += contest["contest_payout_cents"]
    if (outing["prize_pool_cents"] + payouts
            > outing["gross_revenue_cents"] - outing["refunded_cents"]):
        fail("ERR_PRIZE_POOL_UNFUNDED",
             "The prize pool and contest payouts exceed net collections.")
    outing["play_status"] = "SCORED"
    derive.rank_and_distribute(outing)
    derive.run_rollup(outing)


def _postpone(outing, rain_date):
    if outing["play_status"] not in ("OPEN", "FIELD_LOCKED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "POSTPONE is not an edge out of %s." % outing["play_status"])
    contract = derive.contract_of(outing["id"])
    terms = contract["rain_date_terms"] if contract is not None else "NONE"
    candidate = rain_date if rain_date is not None else outing["rain_date"]
    if candidate is None or terms not in ("FULL_CREDIT", "PARTIAL_CREDIT"):
        fail("ERR_NO_RAIN_DATE_TERMS",
             "The outing carries no rain date under crediting terms.")
    base = outing["course_charge_cents"]
    outing["postponed_from_date"] = outing["scheduled_date"]
    outing["scheduled_date"] = candidate
    outing["rain_date"] = None
    outing["play_status"] = "POSTPONED"
    if terms == "FULL_CREDIT":
        credit = base
    else:
        credit = calc.pct_of(contract["rain_date_credit_pct"], base)
    contract["rain_credit_cents"] = credit
    contract["amendment_count"] = contract["amendment_count"] + 1
    contract["status"] = "AMENDED"
    touch(contract)
    for team in derive.teams_of(outing["id"]):
        for name in PLACEMENT_FIELDS:
            team[name] = None
        touch(team)
    derive.run_rollup(outing)


def _resume(outing):
    if outing["play_status"] != "POSTPONED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "RESUME is not an edge out of %s." % outing["play_status"])
    outing["play_status"] = "OPEN"


def _cancel_outing(outing):
    status = outing["play_status"]
    if status not in ("DRAFT", "OPEN", "POSTPONED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "CANCEL_OUTING is not an edge out of %s." % status)
    if outing["finance_status"] != "COLLECTING":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The finance dimension has left COLLECTING.")
    outing["play_status"] = "CANCELLED"
    if status == "OPEN":
        for reg in derive.regs_of(outing["id"]):
            if reg["status"] in ("PENDING_PAYMENT", "WAITLISTED"):
                reg["status"] = "CANCELLED"
                touch(reg)


# --------------------------------------------------------------------------
# The finance dimension (PRD 3.9)
# --------------------------------------------------------------------------
@bp.post("/outing-ops/outings/<row_id>/finance-transition")
def finance_transition(row_id):
    auth((CHARITY_TREASURER,))
    body = validate.body()
    validate.only_fields(body, ("action", "expected_outing_version",
                                "remittance_cents", "remittance_reference"))
    action = validate.req_enum(body, "action", enums.FINANCE_ACTIONS)
    expected = validate.req_int(body, "expected_outing_version")
    if action == "REMIT":
        remittance = validate.req_money(body, "remittance_cents")
        reference = validate.req_str(body, "remittance_reference")
    else:
        remittance = None
        reference = None
    outing = get_outing(row_id)

    # tier 8 - the state precondition, ahead of the version guard (PRD 2.6)
    if action == "RECONCILE":
        if outing["finance_status"] != "COLLECTING":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "RECONCILE is not an edge out of %s." % outing["finance_status"])
        if outing["play_status"] != "SCORED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The play dimension has not reached SCORED.")
    elif action == "REOPEN":
        if outing["finance_status"] != "RECONCILED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "REOPEN is not an edge out of %s." % outing["finance_status"])
    else:
        if outing["finance_status"] != "RECONCILED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "REMIT is not an edge out of %s." % outing["finance_status"])

    # tier 11 - optimistic concurrency
    if expected != outing["version"]:
        fail("ERR_STALE_OUTING_VERSION",
             "The outing has moved to version %d." % outing["version"])

    if action == "RECONCILE":
        outing["finance_status"] = "RECONCILED"
        derive.run_rollup(outing, "FINAL")
    elif action == "REOPEN":
        outing["finance_status"] = "COLLECTING"
        derive.run_rollup(outing, "PROVISIONAL")
    else:
        _remit(outing, remittance, reference)
    touch(outing)
    return ok(serial.dump(outing))


def _remit(outing, remittance, reference):
    outing_id = outing["id"]
    for reg in derive.regs_of(outing_id):
        if reg["status"] in derive.REVENUE_STATES and not reg["receipt_issued"]:
            fail("ERR_UNRECEIPTED_ITEMS_REMAIN",
                 "Registration %s carries no receipt." % reg["id"])
    for item in derive.items_of(outing_id):
        if item["status"] == "PAID":
            fail("ERR_UNRECEIPTED_ITEMS_REMAIN",
                 "Fundraising item %s carries no receipt." % item["id"])
    if outing["net_proceeds_cents"] <= 0:
        fail("ERR_NEGATIVE_NET_PROCEEDS",
             "Net proceeds are not strictly positive.")
    if remittance != outing["net_proceeds_cents"]:
        fail("ERR_REMITTANCE_AMOUNT_MISMATCH",
             "The remittance must equal net proceeds of %d cents."
             % outing["net_proceeds_cents"])
    outing["finance_status"] = "DISBURSED"
    outing["beneficiary_remittance_cents"] = outing["net_proceeds_cents"]
    outing["remittance_reference"] = reference
    contract = derive.contract_of(outing_id)
    if contract is not None and contract["status"] in ("SIGNED", "AMENDED"):
        contract["status"] = "SETTLED"
        contract["settled_charge_cents"] = (outing["course_charge_cents"]
                                           + outing["fnb_shortfall_cents"]
                                           - contract["rain_credit_cents"])
        touch(contract)
