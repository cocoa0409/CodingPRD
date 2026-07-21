"""Lookups, ownership checks and derived-counter re-derivation."""
import config
import db
from db import store
from errors import raise_error
from services import calc

OPEN_REGISTRATION_STATUSES = ("RESERVED", "CONFIRMED", "CHECKED_IN")
MEMBER_STATUSES = ("PENDING", "ACTIVE")
RESERVING_PAYOUT_STATUSES = ("REQUESTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "APPROVED")


# ------------------------------------------------------------------ lookups
def _find(collection, rec_id, error_id):
    if not isinstance(rec_id, str):
        raise_error(error_id)
    rec = collection.get(rec_id)
    if rec is None:
        raise_error(error_id)
    return rec


def get_organization(rec_id):
    return _find(store.organizations, rec_id, "ERR_ORGANIZATION_NOT_FOUND")


def get_campaign(rec_id):
    return _find(store.campaigns, rec_id, "ERR_CAMPAIGN_NOT_FOUND")


def get_event(rec_id):
    return _find(store.events, rec_id, "ERR_EVENT_NOT_FOUND")


def get_team(rec_id):
    return _find(store.teams, rec_id, "ERR_TEAM_NOT_FOUND")


def get_participant(rec_id):
    return _find(store.participants, rec_id, "ERR_PARTICIPANT_NOT_FOUND")


def get_registration(rec_id):
    return _find(store.registrations, rec_id, "ERR_REGISTRATION_NOT_FOUND")


def get_donor(rec_id):
    return _find(store.donors, rec_id, "ERR_DONOR_NOT_FOUND")


def get_donation(rec_id):
    return _find(store.donations, rec_id, "ERR_DONATION_NOT_FOUND")


def get_match_pool(rec_id):
    return _find(store.match_pools, rec_id, "ERR_MATCH_POOL_NOT_FOUND")


def get_tier(rec_id):
    return _find(store.incentive_tiers, rec_id, "ERR_TIER_NOT_FOUND")


def get_award(rec_id):
    return _find(store.incentive_awards, rec_id, "ERR_AWARD_NOT_FOUND")


def get_receipt(rec_id):
    return _find(store.receipts, rec_id, "ERR_RECEIPT_NOT_FOUND")


def get_payout(rec_id):
    return _find(store.payouts, rec_id, "ERR_PAYOUT_NOT_FOUND")


# ---------------------------------------------------------------- ownership
def require_manager_owns_campaign(user_id, campaign):
    """PRD 2.1: a manager may only act on campaigns of its own organization."""
    if campaign["organization_id"] != user_id:
        raise_error("ERR_UNAUTHORIZED")


def require_manager_owns_organization(user_id, organization):
    if organization["id"] != user_id:
        raise_error("ERR_UNAUTHORIZED")


def require_participant_is(user_id, participant):
    if participant["id"] != user_id:
        raise_error("ERR_UNAUTHORIZED")


def require_donor_is(user_id, donor_id):
    if donor_id != user_id:
        raise_error("ERR_UNAUTHORIZED")


def require_actor_owns_campaign(user_id, role, campaign):
    if role == config.ROLE_CAMPAIGN_MANAGER:
        require_manager_owns_campaign(user_id, campaign)


# ------------------------------------------------------------- child scans
def campaign_donations(campaign_id):
    return [d for d in store.donations.values() if d["campaign_id"] == campaign_id]


def campaign_events(campaign_id):
    return [e for e in store.events.values() if e["campaign_id"] == campaign_id]


def campaign_pools(campaign_id):
    return [p for p in store.match_pools.values() if p["campaign_id"] == campaign_id]


def campaign_participants(campaign_id):
    return [p for p in store.participants.values() if p["campaign_id"] == campaign_id]


def campaign_teams(campaign_id):
    return [t for t in store.teams.values() if t["campaign_id"] == campaign_id]


def campaign_tiers(campaign_id):
    return [t for t in store.incentive_tiers.values() if t["campaign_id"] == campaign_id]


def campaign_payouts(campaign_id):
    return [p for p in store.payouts.values() if p["campaign_id"] == campaign_id]


def campaign_receipts(campaign_id):
    return [r for r in store.receipts.values() if r["campaign_id"] == campaign_id]


def event_registrations(event_id):
    return [r for r in store.registrations.values() if r["event_id"] == event_id]


def participant_registrations(participant_id):
    return [
        r for r in store.registrations.values() if r["participant_id"] == participant_id
    ]


def participant_awards(participant_id):
    return [
        a
        for a in store.incentive_awards.values()
        if a["participant_id"] == participant_id
    ]


def receipt_of_donation(donation_id):
    for r in store.receipts.values():
        if r["donation_id"] == donation_id:
            return r
    return None


def campaign_of_event(event):
    return store.campaigns.get(event["campaign_id"])


def campaign_of_participant(participant):
    return store.campaigns.get(participant["campaign_id"])


def campaign_of_registration(registration):
    participant = store.participants.get(registration["participant_id"])
    if participant is None:
        return None
    return campaign_of_participant(participant)


# ----------------------------------------------------- match pool selection
def select_pool(campaign_id, amount_cents):
    """PRD 3.5 candidate filter and ranking; returns the winning pool or None."""
    now = db.now()
    candidates = []
    for pool in campaign_pools(campaign_id):
        if pool["status"] != "ACTIVE":
            continue
        starts_at = db.dt_of(pool["starts_at"])
        ends_at = db.dt_of(pool["ends_at"])
        if not (starts_at <= now < ends_at):
            continue
        if pool["remaining_cents"] <= 0:
            continue
        if amount_cents < pool["min_donation_cents"]:
            continue
        candidates.append(pool)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["ends_at"], p["created_at"], p["_seq"]))
    return candidates[0]


# ------------------------------------------------------------- re-derivation
def refresh_pool(pool):
    allocated = 0
    for d in store.donations.values():
        if d.get("match_pool_id") == pool["id"] and d["match_status"] == "MATCHED":
            allocated += d["matched_amount_cents"]
    pool["allocated_cents"] = allocated
    remaining = pool["pool_amount_cents"] - allocated
    pool["remaining_cents"] = remaining if remaining > 0 else 0
    if pool["status"] != "CLOSED":
        pool["status"] = "EXHAUSTED" if pool["remaining_cents"] == 0 else "ACTIVE"
    return pool


def participant_credited_cents(participant_id):
    total = 0
    for d in store.donations.values():
        if (
            d["designation_type"] == "PARTICIPANT"
            and d["designation_id"] == participant_id
            and d["payment_status"] == "SETTLED"
        ):
            total += d["amount_cents"] + d["matched_amount_cents"]
    return total


def participant_projected_cents(participant_id):
    total = 0
    for d in store.donations.values():
        if (
            d["designation_type"] != "PARTICIPANT"
            or d["designation_id"] != participant_id
        ):
            continue
        if d["payment_status"] == "SETTLED":
            total += d["amount_cents"] + d["matched_amount_cents"]
        elif d["payment_status"] == "PENDING":
            pool = select_pool(d["campaign_id"], d["amount_cents"])
            projected = calc.match_amount(d["amount_cents"], pool) if pool else 0
            total += d["amount_cents"] + projected
    return total


def refresh_participant(participant):
    participant["credited_cents"] = participant_credited_cents(participant["id"])
    participant["projected_cents"] = participant_projected_cents(participant["id"])
    participant["recruit_count"] = len(
        [
            p
            for p in store.participants.values()
            if p["recruited_by_participant_id"] == participant["id"]
            and p["status"] in MEMBER_STATUSES
        ]
    )
    campaign = campaign_of_participant(participant)
    minimum = campaign["fundraising_minimum_cents"] if campaign else 0
    participant["minimum_met"] = participant["credited_cents"] >= minimum
    return participant


def team_credited_cents(team_id):
    total = 0
    for p in store.participants.values():
        if p["team_id"] == team_id:
            total += participant_credited_cents(p["id"])
    for d in store.donations.values():
        if (
            d["designation_type"] == "TEAM"
            and d["designation_id"] == team_id
            and d["payment_status"] == "SETTLED"
        ):
            total += d["amount_cents"] + d["matched_amount_cents"]
    return total


def refresh_team(team):
    team["credited_cents"] = team_credited_cents(team["id"])
    team["member_count"] = len(
        [
            p
            for p in store.participants.values()
            if p["team_id"] == team["id"] and p["status"] in MEMBER_STATUSES
        ]
    )
    return team


def refresh_event(event):
    count = len(
        [
            r
            for r in event_registrations(event["id"])
            if r["status"] in OPEN_REGISTRATION_STATUSES
        ]
    )
    event["registered_count"] = count
    if event["status"] != "CLOSED":
        event["status"] = "FULL" if count >= event["capacity"] else "OPEN"
    return event


def refresh_campaign(campaign):
    cid = campaign["id"]
    raised = 0
    lifetime_net = 0
    donors = set()
    for d in campaign_donations(cid):
        if d["payment_status"] == "SETTLED":
            raised += d["amount_cents"] + d["matched_amount_cents"]
            lifetime_net += d["net_cents"] + d["matched_amount_cents"]
            donors.add(d["donor_id"])
    reserved = 0
    paid_out = 0
    for p in campaign_payouts(cid):
        if p["status"] in RESERVING_PAYOUT_STATUSES:
            reserved += p["amount_cents"]
        elif p["status"] == "RELEASED":
            paid_out += p["amount_cents"]
    campaign["raised_credited_cents"] = raised
    campaign["lifetime_net_cents"] = lifetime_net
    campaign["reserved_payout_cents"] = reserved
    campaign["paid_out_cents"] = paid_out
    campaign["available_balance_cents"] = lifetime_net - reserved - paid_out
    campaign["donor_count"] = len(donors)
    return campaign


def available_balance(campaign):
    return refresh_campaign(campaign)["available_balance_cents"]


# ------------------------------------------------------------- serializers
def ser_organization(rec):
    return db.serialize(rec)


def ser_campaign(rec):
    return db.serialize(refresh_campaign(rec))


def ser_event(rec):
    return db.serialize(refresh_event(rec))


def ser_team(rec):
    return db.serialize(refresh_team(rec))


def ser_participant(rec):
    return db.serialize(refresh_participant(rec))


def ser_registration(rec):
    return db.serialize(rec)


def ser_donor(rec):
    return db.serialize(rec)


def ser_donation(rec):
    return db.serialize(rec)


def ser_match_pool(rec):
    return db.serialize(refresh_pool(rec))


def ser_tier(rec):
    return db.serialize(rec)


def ser_award(rec):
    return db.serialize(rec)


def ser_receipt(rec):
    return db.serialize(rec)


def ser_payout(rec):
    return db.serialize(rec)
