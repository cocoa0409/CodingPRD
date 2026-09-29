"""The two test-driving utilities: the logical clock and the epoch runner."""

from flask import Blueprint

import validators as v
from db import store
from middleware import authenticate, body
from response import iso_ms, ok
from services.core import (dump, find, fk, ordered, pdate,
                           recompute_issuer_aggregate, recompute_window,
                           release_seats, revert_tier_after_lapse, touch)

bp = Blueprint("ops", __name__)

CLOCK_ROLES = ("ProgramAdmin", "RevenueAccountant", "FraudAnalyst",
               "PartnerManager", "ContractsOfficer")


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(CLOCK_ROLES)
    data = body()
    instant = v.req_dt(data, "to_iso8601")
    store.clock = instant
    return ok({"current_utc": iso_ms(store.clock)})


@bp.post("/_ops/run-epoch")
def run_epoch():
    authenticate(("ProgramAdmin",))
    data = body()
    program = fk(store.programs, data, "program_id", "ERR_PROGRAM_NOT_FOUND", required=True)
    program_id = program["id"]
    clock = store.clock

    member_ids = set(m["id"] for m in store.members.values()
                     if m["program_id"] == program_id)

    counts = {
        "holds_expired": 0,
        "campaigns_launched": 0,
        "campaigns_ended": 0,
        "status_matches_lapsed": 0,
        "notices_advanced": 0,
        "agreements_expired": 0,
        "windows_recomputed": 0,
    }

    # 1. Award booking holds lapse and release their seats.
    for booking in ordered(store.bookings):
        if booking["member_id"] not in member_ids or booking["status"] != "HELD":
            continue
        if booking["hold_expires_at"] <= clock:
            booking["status"] = "EXPIRED"
            touch(booking)
            release_seats(booking)
            counts["holds_expired"] += 1

    # 2. Promotion campaigns launch, then end.
    for campaign in ordered(store.campaigns):
        if campaign["program_id"] != program_id:
            continue
        if campaign["status"] == "SCHEDULED" and campaign["window_start"] <= clock:
            campaign["status"] = "LIVE"
            touch(campaign)
            counts["campaigns_launched"] += 1
        if campaign["status"] == "LIVE" and campaign["window_end"] <= clock:
            campaign["status"] = "ENDED"
            touch(campaign)
            counts["campaigns_ended"] += 1

    # 3. Status-match trials lapse.
    for member in ordered(store.members):
        if member["program_id"] != program_id:
            continue
        if (member["status_match_state"] == "TRIAL"
                and member["status_match_expires_at"] is not None
                and member["status_match_expires_at"] <= clock):
            member["status_match_state"] = "LAPSED"
            revert_tier_after_lapse(member)
            touch(member)
            counts["status_matches_lapsed"] += 1

    # 4. Programme change notices advance.
    for notice in ordered(store.notices):
        if notice["program_id"] != program_id:
            continue
        grandfather = notice["grandfather_until"]
        if notice["status"] == "ANNOUNCED" and clock >= notice["effective_at"]:
            if grandfather is not None and grandfather > clock:
                notice["status"] = "IN_GRANDFATHER"
            else:
                notice["status"] = "EFFECTIVE"
            touch(notice)
            counts["notices_advanced"] += 1
        elif notice["status"] == "IN_GRANDFATHER":
            if grandfather is not None and grandfather <= clock:
                notice["status"] = "EFFECTIVE"
                touch(notice)
                counts["notices_advanced"] += 1

    # 5. Agreement terms expire, recomputing the issuer aggregate.
    issuer_ids = set(i["id"] for i in store.issuers.values()
                     if i["program_id"] == program_id)
    for agreement in ordered(store.agreements):
        if agreement["issuer_id"] not in issuer_ids or agreement["status"] != "ACTIVE":
            continue
        if pdate(agreement["term_end_date"]) < clock.date():
            agreement["status"] = "EXPIRED"
            touch(agreement)
            recompute_issuer_aggregate(store.issuers[agreement["issuer_id"]])
            counts["agreements_expired"] += 1

    # 6. Every award window re-postures.
    for window in ordered(store.windows):
        if window["program_id"] != program_id:
            continue
        if recompute_window(window):
            touch(window)
        counts["windows_recomputed"] += 1

    payload = {"epoch_at": iso_ms(clock)}
    payload.update(counts)
    return ok(payload)
