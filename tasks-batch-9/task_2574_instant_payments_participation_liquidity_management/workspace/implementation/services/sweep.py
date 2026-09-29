"""The network housekeeping sweep: the only time-driven state advancer."""

from db import bump, db, now, sorted_rows
from timeutils import plus_minutes
from services import liquidity, lookup
from services.constants import (
    ACK_SLA_MINUTES,
    QUEUE_TTL_MINUTES,
    RFP_EXPIRABLE_STATUSES,
)


def run():
    clock = now()
    expired_rfp_count = 0
    expired_return_request_count = 0
    expired_transfer_count = 0
    escalated_alert_count = 0

    for rfp in sorted_rows("request_for_payments"):
        if rfp["status"] in RFP_EXPIRABLE_STATUSES and clock >= rfp["expiry_at"]:
            rfp["status"] = "EXPIRED"
            bump(rfp)
            expired_rfp_count += 1

    for request in sorted_rows("return_requests"):
        if request["status"] == "REQUESTED" and clock >= request["response_deadline_at"]:
            request["status"] = "EXPIRED"
            bump(request)
            transfer = db.credit_transfers.get(request["credit_transfer_id"])
            if transfer is not None:
                transfer["exception_status"] = "RETURN_EXPIRED"
                bump(transfer)
            expired_return_request_count += 1

    touched_participants = []
    for transfer in sorted_rows("credit_transfers"):
        if transfer["clearing_status"] != "QUEUED_THROTTLED":
            continue
        if transfer["queued_at"] is None:
            continue
        if plus_minutes(transfer["queued_at"], QUEUE_TTL_MINUTES) <= clock:
            transfer["clearing_status"] = "EXPIRED"
            bump(transfer)
            expired_transfer_count += 1
            if transfer["originator_participant_id"] not in touched_participants:
                touched_participants.append(transfer["originator_participant_id"])

    for alert in sorted_rows("liquidity_alerts"):
        if alert["status"] == "OPEN" and plus_minutes(alert["created_at"], ACK_SLA_MINUTES) <= clock:
            alert["status"] = "ESCALATED"
            alert["escalated_at"] = clock
            bump(alert)
            escalated_alert_count += 1

    # Expiring a queued transfer changes the reservation set, so every account
    # the sweep touched has its balance, availability and posture recomputed.
    for participant_id in touched_participants:
        participant = db.participants.get(participant_id)
        if participant is None:
            continue
        account = lookup.account_of_participant(participant_id)
        if account is not None:
            liquidity.recompute_band(account)
        liquidity.rederive_posture(participant)

    return {
        "expired_rfp_count": expired_rfp_count,
        "expired_return_request_count": expired_return_request_count,
        "expired_transfer_count": expired_transfer_count,
        "escalated_alert_count": escalated_alert_count,
    }
