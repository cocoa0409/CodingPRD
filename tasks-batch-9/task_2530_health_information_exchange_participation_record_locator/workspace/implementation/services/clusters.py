"""Identity cluster membership recount, merge and unmerge cascades (PRD 3.3-3.5)."""
from db import by_created, commit, db, parse_iso, snapshot, touch
from services import repo
from services.counters import recompute_active_subscription_count

LIVE_SUBSCRIPTION_STATES = ("PENDING_ACTIVATION", "ACTIVE")
DUPLICATE_TERMINATION_REASON = "DUPLICATE_AFTER_CLUSTER_MERGE"


def rank(row):
    return (row["created_at"], row["_seq"])


def recount(cluster):
    """Recompute every derived counter of a cluster from scratch."""
    cluster_id = cluster["id"]
    members = repo.cluster_members(cluster_id)
    cluster["member_record_count"] = len(members)
    cluster["participant_count"] = len({m["participant_id"] for m in members})
    if members:
        ordered = sorted(
            members,
            key=lambda r: (-int(r["completeness_score"] or 0), r["created_at"], r["_seq"]),
        )
        cluster["primary_record_id"] = ordered[0]["id"]
    else:
        cluster["primary_record_id"] = None
    member_ids = {m["id"] for m in members}
    pending = 0
    for link in db.match_links.values():
        if link["status"] != "PENDING_REVIEW":
            continue
        if link["left_record_id"] in member_ids or link["right_record_id"] in member_ids:
            pending += 1
    cluster["pending_review_link_count"] = pending
    active = 0
    for directive in db.directives.values():
        if directive["cluster_id"] == cluster_id and directive["status"] == "ACTIVE":
            active += 1
    cluster["active_directive_count"] = active
    return cluster


def _repoint_directives(winner, loser):
    moved = repo.where("directives", cluster_id=loser["id"])
    for directive in moved:
        before = snapshot(directive)
        directive["cluster_id"] = winner["id"]
        commit(directive, before)
    groups = {}
    for directive in repo.where("directives", cluster_id=winner["id"], status="ACTIVE"):
        key = (
            directive["directive_type"],
            directive["scope"],
            directive["scoped_participant_id"],
        )
        groups.setdefault(key, []).append(directive)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows = sorted(
            rows,
            key=lambda r: (parse_iso(r["effective_from"]), r["created_at"], r["_seq"]),
        )
        survivor = rows[-1]
        for older in rows[:-1]:
            before = snapshot(older)
            older["status"] = "SUPERSEDED"
            commit(older, before)
        before = snapshot(survivor)
        survivor["supersedes_directive_id"] = rows[-2]["id"]
        commit(survivor, before)


def _repoint_subscriptions(winner, loser):
    moved = [
        s
        for s in repo.where("subscriptions", cluster_id=loser["id"])
        if s["subscription_scope"] == "CLUSTER"
    ]
    for subscription in moved:
        before = snapshot(subscription)
        subscription["cluster_id"] = winner["id"]
        commit(subscription, before)
    incumbents = [
        s
        for s in repo.where("subscriptions", cluster_id=winner["id"])
        if s["subscription_scope"] == "CLUSTER"
    ]
    affected = set()
    for subscription in moved:
        for other in incumbents:
            if other["id"] == subscription["id"]:
                continue
            if (
                other["subscriber_participant_id"]
                != subscription["subscriber_participant_id"]
            ):
                continue
            if subscription["status"] not in LIVE_SUBSCRIPTION_STATES:
                continue
            if other["status"] not in LIVE_SUBSCRIPTION_STATES:
                continue
            if not (set(other["event_types"] or []) & set(subscription["event_types"] or [])):
                continue
            later = other if rank(other) > rank(subscription) else subscription
            before = snapshot(later)
            later["status"] = "TERMINATED"
            later["termination_reason"] = DUPLICATE_TERMINATION_REASON
            commit(later, before)
            affected.add(later["subscriber_participant_id"])
    for participant_id in affected:
        participant = repo.participant(participant_id)
        if participant is None:
            continue
        before = snapshot(participant)
        recompute_active_subscription_count(participant)
        commit(participant, before)


def merge_for_link(link, cluster_left, cluster_right):
    """Merge the two clusters a link spans.  Earlier created_at wins."""
    if cluster_left["id"] == cluster_right["id"]:
        winner, loser = cluster_left, None
    else:
        pair = sorted([cluster_left, cluster_right], key=rank)
        winner, loser = pair[0], pair[1]

    if loser is not None:
        for record in repo.cluster_records(loser["id"]):
            before = snapshot(record)
            record["prior_cluster_id"] = loser["id"]
            record["cluster_id"] = winner["id"]
            commit(record, before)
        loser["status"] = "MERGED_AWAY"
        loser["merged_into_cluster_id"] = winner["id"]

    link["cluster_id"] = winner["id"]
    link["merged_away_cluster_id"] = loser["id"] if loser is not None else None

    if loser is not None:
        _repoint_directives(winner, loser)
        _repoint_subscriptions(winner, loser)

    # Winner first, loser second (PRD 2.10).
    recount(winner)
    touch(winner)
    if loser is not None:
        recount(loser)
        touch(loser)
    return winner, loser


def unmerge_for_link(link):
    """Compensating restoration performed by an unlink (PRD 3.5)."""
    winner = repo.get("clusters", link["cluster_id"])
    restored = repo.get("clusters", link["merged_away_cluster_id"])

    if restored is not None:
        restored["status"] = "ACTIVE"
        restored["merged_into_cluster_id"] = None
        for record in by_created(
            [
                r
                for r in db.patient_records.values()
                if r["prior_cluster_id"] == restored["id"]
            ]
        ):
            before = snapshot(record)
            record["cluster_id"] = record["prior_cluster_id"]
            record["prior_cluster_id"] = None
            commit(record, before)

    link["cluster_id"] = None
    link["merged_away_cluster_id"] = None

    if winner is not None:
        recount(winner)
        touch(winner)
    if restored is not None and (winner is None or restored["id"] != winner["id"]):
        recount(restored)
        touch(restored)
    return winner, restored


def recount_and_touch(cluster):
    before = snapshot(cluster)
    recount(cluster)
    commit(cluster, before)


def recount_and_bump(cluster):
    recount(cluster)
    touch(cluster)
