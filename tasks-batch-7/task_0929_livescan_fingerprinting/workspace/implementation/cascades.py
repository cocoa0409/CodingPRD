"""The two deep cascades and the reprint authorization."""

import billing
import cardsvc
import constants as C
import derive
from store import db
from timeutil import add_days


# ---------------------------------------------------------------- purge grant

def sync_subscription_counters(subscription):
    bound = [n for n in db.notifications.values() if n["subscription_id"] == subscription["id"]]
    received = len(bound)
    routed = sum(1 for n in bound if n["status"] in ("ROUTED", "ACKNOWLEDGED"))
    voided = sum(1 for n in bound if n["status"] == "VOIDED")
    changed = (
        subscription["notifications_received_count"] != received
        or subscription["notifications_routed_count"] != routed
        or subscription["notifications_voided_count"] != voided
    )
    subscription["notifications_received_count"] = received
    subscription["notifications_routed_count"] = routed
    subscription["notifications_voided_count"] = voided
    return changed


def grant_purge(submission, actor_user_id):
    # hop 1
    submission["retention_status"] = "PURGED"
    submission["purge_decided_by_user_id"] = actor_user_id
    db.touch(submission)

    # hop 2
    voided_response_ids = []
    for response in db.chr_responses.values():
        if response["submission_id"] != submission["id"]:
            continue
        if response["routing_status"] not in ("RECEIVED", "ROUTED"):
            continue
        response["routing_status"] = "VOIDED"
        response["record_detail"] = None
        db.touch(response)
        voided_response_ids.append(response["id"])

    # hop 3
    for subscription in db.subscriptions.values():
        if subscription["submission_id"] != submission["id"]:
            continue
        if derive.subscription_status(subscription) not in ("ACTIVE", "RENEWAL_DUE"):
            continue
        subscription["status"] = "TERMINATED"
        # hop 4
        for notification in db.notifications.values():
            if notification["subscription_id"] != subscription["id"]:
                continue
            if notification["status"] != "ROUTED":
                continue
            notification["status"] = "VOIDED"
            db.touch(notification)
        sync_subscription_counters(subscription)
        db.touch(subscription)

    # hop 5
    for determination in db.determinations.values():
        if determination["basis_response_id"] not in voided_response_ids:
            continue
        if determination["status"] not in ("ISSUED", "CHALLENGED", "REAFFIRMED", "AMENDED"):
            continue
        previous = determination["status"]
        determination["status"] = "VACATED"
        if previous == "ISSUED":
            determination["outcome"] = None
        if previous == "CHALLENGED":
            determination["challenge_filed_at"] = None
        db.touch(determination)

    # hop 6
    ori = db.oris[submission["ori_id"]]
    if submission["tcn_suffix"] == 0:
        ori["tcn_released_count"] += len(submission["destinations"])
        db.touch(ori)
    card = db.cards.get(submission["card_id"])
    if card is not None:
        card["status"] = "SUPERSEDED"
        card["taint_reason"] = "PURGED_RECORD"
        db.touch(card)
        site = db.sites.get(card["site_id"])
        if site is not None:
            cardsvc.recompute_site_billable(site)


# ---------------------------------------------------------- calibration audit

def run_calibration_audit(device, corrected_instant):
    # hop 1
    device["last_calibrated_at"] = corrected_instant
    device["calibration_expires_at"] = add_days(corrected_instant, C.DEVICE_CALIBRATION_VALID_DAYS)
    device["calibration_status"] = "QUARANTINED"
    new_expiry = device["calibration_expires_at"]

    # hop 2
    revoked = []
    for assignment in db.device_assignments.values():
        if assignment["device_id"] != device["id"]:
            continue
        derived = derive.assignment_status(assignment)
        if derived not in ("SCHEDULED", "ACTIVE"):
            continue
        assignment["_revoked_from"] = derived
        assignment["status"] = "REVOKED_TAINTED"
        revoked.append(assignment)

    # hop 3
    candidates = [
        card
        for card in db.cards.values()
        if card["device_id"] == device["id"]
        and card["first_capture_at"] is not None
        and card["first_capture_at"] > new_expiry
        and card["status"] in (
            "OPEN", "CAPTURING", "READY_FOR_SUBMISSION", "SUBMITTED", "CLOSED", "REJECTED_CLOSED"
        )
    ]
    candidates.sort(key=lambda c: (c["first_capture_at"], c["created_at"]))
    tainted_cards = []
    for card in candidates:
        card["status"] = "SUPERSEDED"
        card["taint_reason"] = "CALIBRATION_LAPSE"
        db.touch(card)
        tainted_cards.append(card)

    tainted_card_ids = {c["id"] for c in tainted_cards}
    tainted_submissions = [
        s for s in db.submissions.values() if s["card_id"] in tainted_card_ids
    ]
    tainted_submission_ids = {s["id"] for s in tainted_submissions}

    # hop 4
    for response in db.chr_responses.values():
        if response["submission_id"] not in tainted_submission_ids:
            continue
        if response["routing_status"] not in ("RECEIVED", "ROUTED"):
            continue
        response["routing_status"] = "SUPERSEDED"
        db.touch(response)

    # hop 5
    touched_invoices = set()
    for assessment in db.assessments.values():
        if assessment["submission_id"] not in tainted_submission_ids:
            continue
        if assessment["assessment_kind"] not in ("SUBMISSION", "REPRINT"):
            continue
        if assessment["status"] not in ("ASSESSED", "INVOICED"):
            continue
        invoice_id = assessment["invoice_id"]
        assessment["status"] = "CREDITED"
        assessment["credited_cents"] = assessment["total_cents"]
        db.touch(assessment)
        if invoice_id is not None:
            touched_invoices.add(invoice_id)
    for invoice_id in touched_invoices:
        invoice = db.invoices.get(invoice_id)
        if invoice is None:
            continue
        before = (invoice["subtotal_cents"], invoice["total_cents"])
        billing.recompute_invoice_totals(invoice)
        if (invoice["subtotal_cents"], invoice["total_cents"]) != before:
            db.touch(invoice)
        agency = db.agencies.get(invoice["agency_id"])
        if agency is not None:
            billing.recompute_agency_posture(agency)

    # hop 6
    affected_site_ids = {c["site_id"] for c in tainted_cards}
    for site_id in affected_site_ids:
        site = db.sites.get(site_id)
        if site is not None:
            cardsvc.recompute_site_billable(site)
    for assignment in revoked:
        revoked_from = assignment.pop("_revoked_from", "SCHEDULED")
        if revoked_from == "ACTIVE":
            assignment["tainted_print_count"] = sum(
                1
                for c in tainted_cards
                if c["device_id"] == assignment["device_id"]
                and c["site_id"] == assignment["site_id"]
            )
        else:
            assignment["tainted_print_count"] = 0
        db.touch(assignment)
    device["tainted_card_count"] = len(tainted_cards)
    db.touch(device)
    return tainted_cards


# ------------------------------------------------------- reprint authorization

def reprint_is_free(submission):
    technical = (
        submission["state_status"] == "REJECTED_TECHNICAL"
        or submission["fbi_status"] == "REJECTED_TECHNICAL"
    )
    if not technical:
        return False
    if submission["state_status"] == "REJECTED_TECHNICAL":
        anchor = submission["state_resulted_at"]
    else:
        anchor = submission["fbi_resulted_at"]
    if anchor is None:
        return False
    inside = db.now() <= add_days(anchor, C.FREE_REPRINT_WINDOW_DAYS)
    return bool(inside and submission["free_reprint_count"] < C.FREE_REPRINT_MAX_PER_SUBMISSION)


def authorize_reprint(submission, device, actor_user_id):
    free = reprint_is_free(submission)
    appointment = db.appointments[db.cards[submission["card_id"]]["appointment_id"]]
    site = db.sites[appointment["site_id"]]

    replacement = cardsvc.open_card(
        appointment,
        device,
        site,
        actor_user_id,
        reprint_of_submission_id=submission["id"],
        free_reprint_granted=free,
    )

    submission["reprint_count"] += 1
    if free:
        submission["free_reprint_count"] += 1
    db.touch(submission)

    original_card = db.cards.get(submission["card_id"])
    if original_card is not None:
        if original_card["status"] == "SUBMITTED":
            original_card["status"] = "REJECTED_CLOSED"
        original_card["superseded_by_card_id"] = replacement["id"]
        db.touch(original_card)

    for response in db.chr_responses.values():
        if response["submission_id"] != submission["id"]:
            continue
        if response["routing_status"] != "ROUTED":
            continue
        response["routing_status"] = "SUPERSEDED"
        db.touch(response)

    return replacement
