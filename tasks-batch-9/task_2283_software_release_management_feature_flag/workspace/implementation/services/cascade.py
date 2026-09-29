"""Cascades, derived-field recomputation and counter reconciliation.

PRD 2.10: cascades are ordered, every touched resource is a real mutation, and
release ledgers are reconciled by compensation rather than recomputation.
"""

import db
from db import store, upd, now
from services import calc


# ---------------------------------------------------------------------------
# derived-field refreshers
# ---------------------------------------------------------------------------
def refresh_projected(release):
    upd(release, readiness_score_projected=calc.readiness_projected(release))


def refresh_rollback_plan_confirmed(release):
    upd(release, rollback_plan_confirmed=calc.rollback_plan_confirmed(release))


def refresh_evidence_packet_required(release):
    upd(release, evidence_packet_required=calc.evidence_packet_required(release))


def refresh_verified_change_count(release):
    upd(release, verified_change_count=calc.verified_change_count(release))


def last_deployment_end_value(env):
    live = [
        d
        for d in db.deployments_of_environment(env["id"])
        if d["delivery_state"] not in ("ABORTED", "ROLLED_BACK")
    ]
    newest = db.latest(live)
    return newest["window_end_at"] if newest else None


def refresh_last_deployment_end(env):
    upd(env, last_deployment_end_at=last_deployment_end_value(env))


def refresh_packet(packet):
    release = store.releases.get(packet["release_id"])
    if release is None:
        return
    computed = calc.evidence_completeness(release, packet["waivers"])
    packet["_satisfied"] = computed["_satisfied"]
    upd(
        packet,
        base_index=computed["base_index"],
        waiver_credit_points=computed["waiver_credit_points"],
        completeness_index=computed["completeness_index"],
        missing_items=computed["missing_items"],
        waiver_count=computed["waiver_count"],
    )


def refresh_draft_packets(release):
    for packet in db.packets_of_release(release["id"]):
        if packet["state"] == "DRAFT":
            refresh_packet(packet)


def train_of(release):
    return store.release_trains.get(release["release_train_id"])


# ---------------------------------------------------------------------------
# release ledger compensation
# ---------------------------------------------------------------------------
def credit_approval(release, change):
    """Change entered APPROVED: raise the ledgers."""
    upd(
        release,
        committed_change_count=release["committed_change_count"] + 1,
        risk_budget_consumed_points=release["risk_budget_consumed_points"]
        + (change["risk_score_final"] or 0),
    )


def debit_approval(release, change):
    """Change left APPROVED: give the ledger contribution back."""
    upd(
        release,
        committed_change_count=release["committed_change_count"] - 1,
        risk_budget_consumed_points=release["risk_budget_consumed_points"]
        - (change["risk_score_final"] or 0),
    )


# ---------------------------------------------------------------------------
# dependency-driven blocking / unblocking
# ---------------------------------------------------------------------------
def block_approved_dependents(change, touched_releases):
    """Every APPROVED change that directly depends on `change` becomes
    BLOCKED_BY_DEPENDENCY, each applying its own counter decrements."""
    for edge in db.deps_to(change["id"]):
        dependent = store.change_requests.get(edge["from_change_id"])
        if dependent is None or dependent["state"] != "APPROVED":
            continue
        upd(dependent, state="BLOCKED_BY_DEPENDENCY")
        release = store.releases.get(dependent["release_id"])
        if release is not None:
            debit_approval(release, dependent)
            touched_releases.add(release["id"])


def unblock_dependents_after_merge(release):
    """A prerequisite reached MERGED: dependents whose full prerequisite set is
    now MERGED or DEPLOYED return to APPROVED."""
    for candidate in db.changes_of_release(release["id"]):
        if candidate["state"] != "BLOCKED_BY_DEPENDENCY":
            continue
        edges = db.deps_from(candidate["id"])
        if not edges:
            continue
        ready = True
        for edge in edges:
            prereq = store.change_requests.get(edge["to_change_id"])
            if prereq is None or prereq["state"] not in ("MERGED", "DEPLOYED"):
                ready = False
                break
        if ready:
            upd(candidate, state="APPROVED")
            credit_approval(release, candidate)


# ---------------------------------------------------------------------------
# ReleaseTrain freeze / unfreeze (PRD 3.1)
# ---------------------------------------------------------------------------
DEFERRABLE_STATES = ("DRAFT", "RISK_CLASSIFIED", "CAB_REVIEW")


def train_freeze(train):
    touched = set()
    # Hop 1: the train itself.
    upd(train, phase="FROZEN", frozen_at=now())

    # Hop 2: OPEN releases become FROZEN.
    frozen_releases = []
    for release in db.by_creation(db.releases_of_train(train["id"])):
        if release["phase"] == "OPEN":
            upd(release, phase="FROZEN")
            frozen_releases.append(release)
            touched.add(release["id"])

    # Hop 3: in-flight changes on those releases become DEFERRED.
    deferred = []
    for release in frozen_releases:
        for change in db.by_creation(db.changes_of_release(release["id"])):
            if change["state"] in DEFERRABLE_STATES:
                upd(change, state="DEFERRED")
                deferred.append(change)

    # Hop 4: APPROVED dependents of the deferred changes become blocked.
    # Hop 5: those dependents give back their ledger contributions.
    for change in deferred:
        block_approved_dependents(change, touched)

    # Finally: readiness recomputed on every release touched above.
    for release_id in touched:
        release = store.releases.get(release_id)
        if release is not None:
            refresh_projected(release)


def train_unfreeze(train):
    touched = set()
    upd(train, phase="ACTIVE")  # frozen_at retained as the historical record

    reopened = []
    for release in db.by_creation(db.releases_of_train(train["id"])):
        if release["phase"] == "FROZEN" and release["cut_at"] > now():
            upd(release, phase="OPEN")
            reopened.append(release)
            touched.add(release["id"])

    # DEFERRED changes return first, so the blocked check below sees them
    # already restored.
    for release in reopened:
        for change in db.by_creation(db.changes_of_release(release["id"])):
            if change["state"] == "DEFERRED":
                upd(change, state="RISK_CLASSIFIED")

    for release in reopened:
        for change in db.by_creation(db.changes_of_release(release["id"])):
            if change["state"] != "BLOCKED_BY_DEPENDENCY":
                continue
            abandoned = False
            for edge in db.deps_from(change["id"]):
                prereq = store.change_requests.get(edge["to_change_id"])
                if prereq is None or prereq["state"] in ("DEFERRED", "WITHDRAWN", "REJECTED"):
                    abandoned = True
                    break
            if not abandoned:
                upd(change, state="APPROVED")
                credit_approval(release, change)

    for release_id in touched:
        release = store.releases.get(release_id)
        if release is not None:
            refresh_projected(release)


# ---------------------------------------------------------------------------
# flag pause / step teardown
# ---------------------------------------------------------------------------
def system_pause_flag(flag):
    """ACTIVE_ROLLING_OUT -> PAUSED forced by a system event."""
    if flag["state"] != "ACTIVE_ROLLING_OUT":
        return False
    upd(flag, state="PAUSED", kill_switch_engaged=True)
    return True


def teardown_flag_steps(flag):
    """PLANNED steps are voided; SOAKING steps are aborted with the flag's
    exposure restored verbatim."""
    voided = 0
    aborted = 0
    for step in db.by_creation(db.steps_of_flag(flag["id"])):
        if step["state"] == "PLANNED":
            upd(step, state="VOIDED")
            voided += 1
        elif step["state"] == "SOAKING":
            upd(step, state="ABORTED")
            upd(flag, current_exposure_pct=step["previous_exposure_pct"])
            aborted += 1
    return voided, aborted


def flags_of_release(release):
    """Distinct flags reachable through change-to-flag links from the release's
    change requests, in creation order."""
    seen = []
    seen_ids = set()
    for change in db.by_creation(db.changes_of_release(release["id"])):
        for link in db.by_creation(db.links_of_change(change["id"])):
            if link["feature_flag_id"] in seen_ids:
                continue
            flag = store.feature_flags.get(link["feature_flag_id"])
            if flag is None:
                continue
            seen_ids.add(flag["id"])
            seen.append(flag)
    return seen


def releases_linked_to_flag(flag):
    release_ids = []
    for link in db.links_of_flag(flag["id"]):
        change = store.change_requests.get(link["change_request_id"])
        if change is None:
            continue
        if change["release_id"] not in release_ids:
            release_ids.append(change["release_id"])
    return [store.releases.get(rid) for rid in release_ids if store.releases.get(rid)]


# ---------------------------------------------------------------------------
# Release rollback cascade (PRD 3.8 hops 2-4)
# ---------------------------------------------------------------------------
def release_rollback(release):
    if release["phase"] not in ("STABILIZING", "RELEASED"):
        return
    upd(release, phase="ROLLED_BACK", rolled_back_at=now())

    # Hop 3: pause the release's rolling-out guard flags.
    paused = []
    for flag in flags_of_release(release):
        if system_pause_flag(flag):
            paused.append(flag)

    # Hop 4: void / abort their ladders.
    for flag in paused:
        teardown_flag_steps(flag)

    # Alongside: DEPLOYED changes stay DEPLOYED but lose their verification.
    for change in db.by_creation(db.changes_of_release(release["id"])):
        if change["state"] == "DEPLOYED":
            upd(change, deployment_verified=False)
    refresh_verified_change_count(release)


def deployment_rollback(deployment):
    upd(deployment, delivery_state="ROLLED_BACK", rolled_back_at=now())
    env = store.environments.get(deployment["environment_id"])
    if env is not None:
        refresh_last_deployment_end(env)
    release = store.releases.get(deployment["release_id"])
    if release is not None:
        release_rollback(release)


# ---------------------------------------------------------------------------
# Canary abort cascade (PRD 3.7, four hops)
# ---------------------------------------------------------------------------
def deployment_abort(deployment):
    # Hop 1
    upd(deployment, delivery_state="ABORTED", verification_state="FAILING")
    env = store.environments.get(deployment["environment_id"])
    if env is not None:
        upd(env, active_deployment_count=max(0, env["active_deployment_count"] - 1))

    # Hop 2
    affected_flags = []
    for step in db.by_creation(db.steps_of_deployment(deployment["id"])):
        if step["state"] != "SOAKING":
            continue
        upd(step, state="ABORTED")
        flag = store.feature_flags.get(step["feature_flag_id"])
        if flag is None:
            continue
        upd(flag, current_exposure_pct=step["previous_exposure_pct"])
        if flag["id"] not in [f["id"] for f in affected_flags]:
            affected_flags.append(flag)

    # Hop 3
    paused = []
    for flag in affected_flags:
        if system_pause_flag(flag):
            paused.append(flag)

    # Hop 4
    touched_releases = []
    for flag in paused:
        for link in db.by_creation(db.links_of_flag(flag["id"])):
            change = store.change_requests.get(link["change_request_id"])
            if change is None or change["state"] != "DEPLOYED":
                continue
            upd(change, deployment_verified=False)
            if change["release_id"] not in touched_releases:
                touched_releases.append(change["release_id"])
    for release_id in touched_releases:
        release = store.releases.get(release_id)
        if release is not None:
            refresh_verified_change_count(release)


# ---------------------------------------------------------------------------
# Cleanup sweep (PRD 3.6)
# ---------------------------------------------------------------------------
def cleanup_sweep():
    stamp = now()
    evaluated = []
    newly_enforced = []
    affected = []

    for flag in db.by_creation(store.feature_flags.values()):
        if flag["state"] == "ARCHIVED":
            continue
        was_enforced = flag["cleanup_state"] == "ENFORCED"
        debt, cleanup = calc.flag_stale_debt(flag, stamp)
        changed = upd(
            flag, stale_debt_points=debt, cleanup_state=cleanup, last_sweep_at=stamp
        )
        evaluated.append(flag)
        if changed:
            affected.append(flag)
        if cleanup == "ENFORCED" and not was_enforced:
            newly_enforced.append(flag)

    paused_flag_count = 0
    voided_step_count = 0
    aborted_step_count = 0
    for flag in newly_enforced:
        if flag["state"] != "ACTIVE_ROLLING_OUT":
            continue
        upd(flag, state="PAUSED", kill_switch_engaged=True)
        paused_flag_count += 1
        voided, aborted = teardown_flag_steps(flag)
        voided_step_count += voided
        aborted_step_count += aborted
        if flag["id"] not in [f["id"] for f in affected]:
            affected.append(flag)

    # readiness recomputed on every release reachable from an affected flag
    release_ids = []
    for flag in affected:
        for release in releases_linked_to_flag(flag):
            if release["id"] not in release_ids:
                release_ids.append(release["id"])
    for release_id in release_ids:
        release = store.releases.get(release_id)
        if release is not None:
            refresh_projected(release)

    return {
        "evaluated_count": len(evaluated),
        "warning_count": len([f for f in evaluated if f["cleanup_state"] == "WARNING"]),
        "overdue_count": len([f for f in evaluated if f["cleanup_state"] == "OVERDUE"]),
        "enforced_count": len([f for f in evaluated if f["cleanup_state"] == "ENFORCED"]),
        "paused_flag_count": paused_flag_count,
        "voided_step_count": voided_step_count,
        "aborted_step_count": aborted_step_count,
    }
