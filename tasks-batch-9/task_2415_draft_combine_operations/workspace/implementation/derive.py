"""Derived aggregates (PRD 2.11 "upward recomputation"). Everything here is
computed on read, so a change to an input row is reflected immediately."""

from decimal import Decimal

import calc
import constants as K
from db import db


# --------------------------------------------------------------------------
# DraftCycle
# --------------------------------------------------------------------------
def cycle_posture(cycle):
    status = cycle["status"]
    if status in K.FROZEN_STATUSES:
        return "FROZEN"
    if status in K.RESTRICTED_STATUSES:
        return "RESTRICTED"
    return "OPEN"


def cycle_clubs(cycle_id):
    return [c for c in db.clubs.values() if c["draft_cycle_id"] == cycle_id]


def registered_clubs(cycle_id):
    return [
        c
        for c in db.clubs.values()
        if c["draft_cycle_id"] == cycle_id and c["registration_status"] == "REGISTERED"
    ]


def club_count(cycle_id):
    return len(registered_clubs(cycle_id))


def cycle_prospects(cycle_id):
    return [p for p in db.prospects.values() if p["draft_cycle_id"] == cycle_id]


def cycle_picks(cycle_id):
    return [p for p in db.draft_picks.values() if p["draft_cycle_id"] == cycle_id]


def pick_inventory(cycle_id):
    picks = [p for p in cycle_picks(cycle_id) if p["status"] != "FORFEITED"]
    total = Decimal("0.0")
    for pick in picks:
        total += calc.dec(pick["chart_value_points"])
    return len(picks), calc.q1(total)


def current_overall_number(cycle_id):
    for pick in cycle_picks(cycle_id):
        if pick["status"] == "ON_CLOCK":
            return pick["overall_number"]
    return 0


def on_clock_pick(cycle_id):
    for pick in cycle_picks(cycle_id):
        if pick["status"] == "ON_CLOCK":
            return pick
    return None


# --------------------------------------------------------------------------
# Club
# --------------------------------------------------------------------------
def club_contracts(club_id):
    return [c for c in db.player_contracts.values() if c["club_id"] == club_id]


def rookie_pool_remaining(club):
    charged = 0
    for contract in club_contracts(club["id"]):
        if contract["status"] == "SIGNED":
            charged += contract["first_year_cap_charge_cents"]
    return club["rookie_pool_total_cents"] - charged


def draft_capital_points(club):
    total = Decimal("0.0")
    for pick in db.draft_picks.values():
        if pick["owning_club_id"] == club["id"] and pick["status"] in (
            "PENDING",
            "ON_CLOCK",
        ):
            total += calc.dec(pick["chart_value_points"])
    return calc.q1(total)


def club_tier(club):
    return calc.trade_authorization_tier(draft_capital_points(club))


def udfa_pool_remaining(club):
    remaining = int(club["udfa_pool_total_cents"])
    contracts = [
        c
        for c in club_contracts(club["id"])
        if c["origin"] == "UDFA" and c["status"] in ("OFFERED", "SIGNED")
    ]
    for contract in sorted(contracts, key=lambda r: (r["created_at"], r["_seq"])):
        remaining -= int(contract["signing_bonus_cents"])
    return remaining


def lapsed_slot_charge_total(club_id):
    total = 0
    for pick in db.draft_picks.values():
        if pick["owning_club_id"] == club_id and pick["status"] == "LAPSED":
            total += int(pick["slot_first_year_cap_charge_cents"] or 0)
    return total


# --------------------------------------------------------------------------
# MedicalEvaluation / MedicalRecordShare
# --------------------------------------------------------------------------
def evaluation_shares(evaluation_id):
    return [
        s
        for s in db.medical_record_shares.values()
        if s["medical_evaluation_id"] == evaluation_id
    ]


def active_share_count(evaluation_id):
    return len([s for s in evaluation_shares(evaluation_id) if s["status"] == "GRANTED"])


def effective_access(share):
    if share["status"] == "GRANTED" and share["expires_at"] is not None:
        if db.now < share["expires_at"]:
            return share["scope"]
    return "NONE"


def prospect_evaluations(prospect_id):
    return [
        e for e in db.medical_evaluations.values() if e["prospect_id"] == prospect_id
    ]


# --------------------------------------------------------------------------
# Bookings
# --------------------------------------------------------------------------
def prospect_bookings(prospect_id):
    return [b for b in db.combine_bookings.values() if b["prospect_id"] == prospect_id]


def evaluation_prospect(evaluation):
    return db.prospects.get(evaluation["prospect_id"])


def prospect_cycle(prospect):
    return db.draft_cycles.get(prospect["draft_cycle_id"])


def club_cycle(club):
    return db.draft_cycles.get(club["draft_cycle_id"])
