"""Letters of intent, exclusivity windows and the negotiation cycle — PRD 3.3."""

from flask import Blueprint

import calc
import enums
import services
from auth import authenticate
from clock import CLOCK, add_days, date_at_midnight, fmt_date, fmt_ts, parse_date, parse_ts
from db import LETTERS, RESTRUCTURINGS, create_row, touch
from errors import fail
from response import ok_row
from validate import (bad, body_object, opt_str, req_date, req_enum, req_id,
                      req_int, req_str)

bp = Blueprint("letters", __name__)


def _seat_split_in_range(split, combined_board_seats):
    return 1 <= split <= combined_board_seats - 1


def _window_of(letter):
    return (parse_date(letter["exclusivity_start_date"]),
            parse_date(letter["exclusivity_end_date"]))


@bp.post("/letters-of-intent")
def issue_letter():
    actor = authenticate(["StrategyOfficer"])
    body = body_object()
    restructuring_id = req_id(body, "restructuring_id")
    expected_version = req_int(body, "expected_restructuring_version")
    proposed_structure_type = req_enum(body, "proposed_structure_type",
                                      enums.STRUCTURE_TYPES)
    combined_board_seats = req_int(body, "combined_board_seats", minimum=3, maximum=51)
    split = req_int(body, "board_seat_split_initiator")
    exclusivity_days = req_int(body, "exclusivity_days", minimum=1, maximum=365)
    start_date = req_date(body, "exclusivity_start_date")
    # The start date may be later than the clock's calendar date but never earlier.
    if start_date < CLOCK.today():
        bad("exclusivity_start_date may not fall earlier than the current logical date.")

    deal = services.find_deal(restructuring_id)
    # Ladder rule 13: issuance checks two-party membership.
    services.require_party(actor, deal)
    # Ladder rule 15.
    if expected_version != deal["version"]:
        fail("ERR_STALE_RESTRUCTURING_VERSION",
             "expected_restructuring_version does not match the deal's current version.")
    # Ladder rule 16.
    if deal["status"] not in ("RATIONALE_BUILT", "LOI_NEGOTIATION"):
        fail("ERR_INVALID_DEAL_STATE",
             "A letter of intent cannot be issued while the deal is %s." % deal["status"])

    end_date = add_days(start_date, exclusivity_days - 1)
    init, tgt = services.parties(deal)
    pair = frozenset((init, tgt))

    # Ladder rule 40: inclusive-window overlap against another deal's ACTIVE window.
    for letter in LETTERS.values():
        if letter["restructuring_id"] == deal["id"]:
            continue
        if letter["exclusivity_status"] != "ACTIVE":
            continue
        other = RESTRUCTURINGS.get(letter["restructuring_id"])
        if other is None:
            continue
        if not ({other["initiator_org_id"], other["target_org_id"]} & {init, tgt}):
            continue
        o_start, o_end = _window_of(letter)
        if o_start is None or o_end is None:
            continue
        if start_date <= o_end and o_start <= end_date:
            fail("ERR_EXCLUSIVITY_CONFLICT",
                 "The requested exclusivity window overlaps an active window of "
                 "another deal involving one of these parties.")

    # Ladder rule 41: cooling-off after the most recent released or expired window.
    candidates = []
    for letter in LETTERS.values():
        if letter["exclusivity_status"] not in ("RELEASED", "EXPIRED"):
            continue
        other = RESTRUCTURINGS.get(letter["restructuring_id"])
        if other is None:
            continue
        if not ({other["initiator_org_id"], other["target_org_id"]} & {init, tgt}):
            continue
        candidates.append((letter, other))
    if candidates:
        latest, latest_deal = max(
            candidates,
            key=lambda item: (item[0]["exclusivity_end_date"], item[0]["_seq"]),
        )
        latest_pair = frozenset((latest_deal["initiator_org_id"],
                                 latest_deal["target_org_id"]))
        if latest_pair != pair:
            previous_end = parse_date(latest["exclusivity_end_date"])
            if previous_end is not None:
                earliest = add_days(previous_end, calc.EXCLUSIVITY_COOLING_OFF_DAYS)
                if start_date <= earliest:
                    fail("ERR_EXCLUSIVITY_COOLING_OFF",
                         "The cooling-off period after the previous counterparty's "
                         "window has not elapsed.")

    # Ladder rule 45.
    if not _seat_split_in_range(split, combined_board_seats):
        fail("ERR_SEAT_SPLIT_OUT_OF_RANGE",
             "board_seat_split_initiator must leave both parties represented.")

    row = create_row("LetterOfIntent", {
        "restructuring_id": deal["id"],
        "round_no": deal["round_no"],
        "proposed_structure_type": proposed_structure_type,
        "combined_board_seats": combined_board_seats,
        "board_seat_split_initiator": split,
        "exclusivity_days": exclusivity_days,
        "exclusivity_start_date": fmt_date(start_date),
        "exclusivity_end_date": fmt_date(end_date),
        "exclusivity_status": "ACTIVE",
        "expires_at": fmt_ts(date_at_midnight(end_date)),
        "status": "ISSUED",
        "countered_by_party": None,
        "counter_round_count": 0,
        "executed_at": None,
        "withdrawal_reason": None,
    })

    # Any letter of a LOWER round_no still negotiating is superseded.
    for letter in services.deal_letters(deal["id"]):
        if letter["id"] == row["id"]:
            continue
        if letter["round_no"] < row["round_no"] and letter["status"] in ("ISSUED", "COUNTERED"):
            letter["status"] = "SUPERSEDED"
            letter["exclusivity_status"] = "RELEASED"
            touch(letter)

    if deal["status"] == "RATIONALE_BUILT":
        deal["status"] = "LOI_NEGOTIATION"
    # The deal's version rises by exactly one for the request either way.
    touch(deal)
    return ok_row(row, 201)


@bp.post("/letters-of-intent/<letter_id>/counter")
def counter_letter(letter_id):
    actor = authenticate(["StrategyOfficer"])
    body = body_object()
    req_str(body, "counter_note", min_len=1)

    letter = services.find_letter(letter_id)
    deal = services.find_deal(letter["restructuring_id"])
    # Ladder rule 13: countering belongs to the target organization.
    services.require_specific_party(actor, deal["target_org_id"])
    # Ladder rule 17.
    if letter["status"] != "ISSUED" or letter["exclusivity_status"] != "ACTIVE":
        fail("ERR_INVALID_LETTER_STATE",
             "Only an ISSUED letter inside an ACTIVE window can be countered.")

    letter["status"] = "COUNTERED"
    letter["countered_by_party"] = "TARGET"
    letter["counter_round_count"] += 1
    touch(letter)
    return ok_row(letter)


@bp.post("/letters-of-intent/<letter_id>/revise")
def revise_letter(letter_id):
    actor = authenticate(["StrategyOfficer"])
    body = body_object()
    split = req_int(body, "board_seat_split_initiator")

    letter = services.find_letter(letter_id)
    deal = services.find_deal(letter["restructuring_id"])
    # Ladder rule 13: revision belongs to the initiator organization.
    services.require_specific_party(actor, deal["initiator_org_id"])
    # Ladder rule 17.
    if letter["status"] != "COUNTERED" or letter["exclusivity_status"] != "ACTIVE":
        fail("ERR_INVALID_LETTER_STATE",
             "Only a COUNTERED letter inside an ACTIVE window can be revised.")
    # Ladder rule 45.
    if not _seat_split_in_range(split, letter["combined_board_seats"]):
        fail("ERR_SEAT_SPLIT_OUT_OF_RANGE",
             "board_seat_split_initiator must leave both parties represented.")

    letter["board_seat_split_initiator"] = split
    letter["status"] = "ISSUED"
    touch(letter)
    return ok_row(letter)


@bp.post("/letters-of-intent/<letter_id>/execute")
def execute_letter(letter_id):
    actor = authenticate(["StrategyOfficer"])
    body = body_object()
    opt_str(body, "executed_note", min_len=1)

    letter = services.find_letter(letter_id)
    deal = services.find_deal(letter["restructuring_id"])
    # Ladder rule 13: execution is the target's countersignature.
    services.require_specific_party(actor, deal["target_org_id"])
    # Ladder rule 17, including the expiry instant.
    if letter["status"] != "ISSUED" or letter["exclusivity_status"] != "ACTIVE":
        fail("ERR_INVALID_LETTER_STATE",
             "Only an ISSUED letter inside an ACTIVE window can be executed.")
    expires = parse_ts(letter["expires_at"])
    if expires is not None and CLOCK.now() >= expires:
        fail("ERR_INVALID_LETTER_STATE",
             "The letter's exclusivity window has already expired.")

    letter["status"] = "EXECUTED"
    letter["executed_at"] = CLOCK.now_iso()
    touch(letter)

    if deal["status"] == "LOI_NEGOTIATION":
        deal["status"] = "DILIGENCE"
        deal["combined_board_seats"] = letter["combined_board_seats"]
        deal["reserved_seat_pool"] = letter["combined_board_seats"]
        touch(deal)
    return ok_row(letter)


@bp.post("/letters-of-intent/<letter_id>/withdraw")
def withdraw_letter(letter_id):
    actor = authenticate(["StrategyOfficer"])
    body = body_object()
    reason = req_str(body, "withdrawal_reason", min_len=1)

    letter = services.find_letter(letter_id)
    deal = services.find_deal(letter["restructuring_id"])
    # Ladder rule 13: withdrawal belongs to the initiator organization.
    services.require_specific_party(actor, deal["initiator_org_id"])
    # Ladder rule 17.
    if letter["status"] not in ("ISSUED", "COUNTERED"):
        fail("ERR_INVALID_LETTER_STATE",
             "Only an ISSUED or COUNTERED letter can be withdrawn.")

    letter["status"] = "WITHDRAWN"
    letter["exclusivity_status"] = "RELEASED"
    letter["withdrawal_reason"] = reason
    touch(letter)
    return ok_row(letter)
