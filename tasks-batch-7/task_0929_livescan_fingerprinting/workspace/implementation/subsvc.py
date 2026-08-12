"""Transmission, transaction control numbers and destination results."""

import constants as C
import derive
from store import db
from timeutil import add_days


def _root_sequence(ori):
    return sum(
        1
        for s in db.submissions.values()
        if s["ori_id"] == ori["id"] and s["tcn_suffix"] == 0
    ) + 1


def _mint_root(ori):
    return "%s-%06d" % (ori["ori_code"], _root_sequence(ori))


def allocate_tcn(ori, card, destinations):
    """Returns (tcn_root, tcn_suffix, consumed, original_submission_id,
    reprint_sequence)."""
    reprint_of = card["reprint_of_submission_id"]
    if reprint_of is None:
        return _mint_root(ori), 0, len(destinations), None, 0

    source = db.submissions[reprint_of]
    head = source
    if source["original_submission_id"] is not None:
        head = db.submissions.get(source["original_submission_id"], source)

    next_suffix = head["reprint_count"]
    inside_window = (
        head["transmitted_at"] is not None
        and db.now() <= add_days(head["transmitted_at"], C.TCN_PRESERVATION_WINDOW_DAYS)
    )
    if inside_window and next_suffix <= C.TCN_SUFFIX_MAX:
        return head["tcn_root"], next_suffix, 0, head["id"], next_suffix
    return _mint_root(ori), 0, len(destinations), head["id"], next_suffix


def render_tcn(root, suffix):
    if suffix == 0:
        return root
    return "%s-%d" % (root, suffix)


def create_submission(card, ori, retention_requested):
    destinations = ["STATE", "FBI"] if ori["destination_requirement"] == "STATE_AND_FBI" else ["STATE"]
    root, suffix, consumed, original_id, sequence = allocate_tcn(ori, card, destinations)

    submission = db.create(
        "submissions",
        {
            "card_id": card["id"],
            "ori_id": ori["id"],
            "original_submission_id": original_id,
            "reprint_sequence": sequence,
            "transmitted_at": db.now(),
            "destinations": destinations,
            "state_status": "PENDING",
            "fbi_status": "PENDING" if "FBI" in destinations else "NOT_REQUIRED",
            "composite_disposition": "INCOMPLETE",
            "retention_requested": bool(retention_requested),
            "retention_status": "GRANTED" if retention_requested else "NOT_REQUESTED",
            "tcn_root": root,
            "tcn_suffix": suffix,
            "tcn_full": render_tcn(root, suffix),
            "state_resulted_at": None,
            "fbi_resulted_at": None,
            "reprint_count": 0,
            "free_reprint_count": 0,
            "purge_requested_at": None,
            "purge_requested_by_user_id": None,
            "purge_decided_by_user_id": None,
        },
    )
    if consumed:
        ori["tcn_consumed_count"] += consumed
        db.touch(ori)
    return submission


def fitness_code(record_count, disqualifying_offense_count):
    if disqualifying_offense_count >= 1:
        return "INELIGIBLE"
    if record_count >= 1:
        return "ELIGIBLE_WITH_NOTICE"
    return "ELIGIBLE"


def create_and_route_response(submission, destination, record_count,
                              disqualifying_offense_count, record_detail):
    response = db.create(
        "chr_responses",
        {
            "submission_id": submission["id"],
            "destination": destination,
            "record_count": record_count,
            "disqualifying_offense_count": disqualifying_offense_count,
            "record_detail": record_detail,
            "fitness_code": fitness_code(record_count, disqualifying_offense_count),
            "routing_status": "RECEIVED",
            "routed_at": None,
            "routed_recipient_roles": None,
        },
    )
    if submission["retention_status"] != "PURGED":
        response["routing_status"] = "ROUTED"
        response["routed_at"] = db.now()
        response["routed_recipient_roles"] = ["AgencyAdjudicator", "Applicant"]
    return response


def sync_composite(submission):
    submission["composite_disposition"] = derive.composite_disposition(submission)
    return submission["composite_disposition"]


def close_card_when_complete(submission):
    """Once composite_disposition becomes CLEARED or HIT the card behind the
    submission moves SUBMITTED -> CLOSED."""
    disposition = sync_composite(submission)
    if disposition not in ("CLEARED", "HIT"):
        return
    card = db.cards.get(submission["card_id"])
    if card is not None and card["status"] == "SUBMITTED":
        card["status"] = "CLOSED"
        db.touch(card)
