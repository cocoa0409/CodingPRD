"""Counters that are always recomputed from scratch (PRD 2.10)."""
from db import db

ISSUED_LIKE = ("ISSUED", "DELINQUENT")


def recompute_active_subscription_count(participant):
    count = 0
    for row in db.subscriptions.values():
        if (
            row["subscriber_participant_id"] == participant["id"]
            and row["status"] == "ACTIVE"
        ):
            count += 1
    participant["active_subscription_count"] = count
    return count


def recompute_outstanding_balance(participant):
    total = 0
    for row in db.invoices.values():
        if row["participant_id"] == participant["id"] and row["status"] in ISSUED_LIKE:
            total += int(row["total_cents"] or 0)
    participant["outstanding_balance_cents"] = total
    return total


def recompute_policy_directive_count(policy):
    count = 0
    for row in db.directives.values():
        if row["policy_id"] == policy["id"]:
            count += 1
    policy["directive_count"] = count
    return count


def recompute_passed_profiles(participant, profile):
    profiles = set(participant.get("passed_profiles") or [])
    profiles.add(profile)
    participant["passed_profiles"] = sorted(profiles)
    return participant["passed_profiles"]
