"""Fan-out cascades shared by participant suspension paths (PRD 3.11)."""
from db import commit, snapshot
from services import repo
from services.counters import recompute_active_subscription_count
from services.scorecard import apply_to_participant

PARTICIPANT_SUSPENSION_CASCADE = "PARTICIPANT_SUSPENSION_CASCADE"
PARTICIPANT_TERMINATED = "PARTICIPANT_TERMINATED"
AUTOMATIC_SANCTION_THRESHOLD = "AUTOMATIC_SANCTION_THRESHOLD"
SUPERSEDED_BY_GENERATION = "SUPERSEDED_BY_GENERATION"

SUSPENDABLE_FEED_STATES = ("PROVISIONING", "MONITORED", "DEGRADED")
LIVE_SUBSCRIPTION_STATES = ("PENDING_ACTIVATION", "ACTIVE")


def suspend_feeds(participant):
    """Every live feed of the participant moves to SUSPENDED, created_at ASC."""
    for feed in repo.participant_feeds(participant["id"]):
        if feed["status"] not in SUSPENDABLE_FEED_STATES:
            continue
        before = snapshot(feed)
        feed["status"] = "SUSPENDED"
        feed["status_reason"] = PARTICIPANT_SUSPENSION_CASCADE
        commit(feed, before)


def restore_feeds(participant):
    """Only the feeds suspended by the participant cascade come back."""
    for feed in repo.participant_feeds(participant["id"]):
        if feed["status"] != "SUSPENDED":
            continue
        if feed["status_reason"] != PARTICIPANT_SUSPENSION_CASCADE:
            continue
        before = snapshot(feed)
        feed["status"] = "MONITORED"
        feed["status_reason"] = None
        commit(feed, before)


def suspend_subscriptions(participant):
    for subscription in repo.participant_subscriptions(participant["id"]):
        if subscription["status"] not in LIVE_SUBSCRIPTION_STATES:
            continue
        before = snapshot(subscription)
        subscription["status"] = "SUSPENDED"
        commit(subscription, before)
    recompute_active_subscription_count(participant)


def reactivate_subscriptions(participant):
    for subscription in repo.participant_subscriptions(participant["id"]):
        if subscription["status"] != "SUSPENDED":
            continue
        before = snapshot(subscription)
        subscription["status"] = "ACTIVE"
        commit(subscription, before)
    recompute_active_subscription_count(participant)


def terminate_subscriptions(participant, reason=PARTICIPANT_TERMINATED):
    for subscription in repo.participant_subscriptions(participant["id"]):
        if subscription["status"] == "TERMINATED":
            continue
        before = snapshot(subscription)
        subscription["status"] = "TERMINATED"
        subscription["termination_reason"] = reason
        commit(subscription, before)
    recompute_active_subscription_count(participant)


def withdraw_records_and_recount(participant):
    """Participant termination withdraws every contributed record from the index."""
    from services.clusters import recount_and_touch

    touched = []
    for record in repo.where("patient_records", participant_id=participant["id"]):
        if record["match_state"] == "WITHDRAWN_FROM_INDEX":
            continue
        before = snapshot(record)
        record["match_state"] = "WITHDRAWN_FROM_INDEX"
        commit(record, before)
        if record["cluster_id"] and record["cluster_id"] not in touched:
            touched.append(record["cluster_id"])
    for cluster_id in touched:
        cluster = repo.get("clusters", cluster_id)
        if cluster is not None:
            recount_and_touch(cluster)


def suspend_participant(participant, reason):
    """Shared body of the manual SUSPEND and the automatic sanction suspension."""
    participant["onboarding_status"] = "SUSPENDED"
    participant["suspension_reason"] = reason
    suspend_feeds(participant)
    apply_to_participant(participant)
    suspend_subscriptions(participant)
