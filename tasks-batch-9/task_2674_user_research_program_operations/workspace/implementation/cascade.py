"""The five-hop evidence-withdrawal cascade and the retention sweep (PRD 3.6).

Every hop is mandatory and the whole chain runs to completion inside the
request that triggered it: there is no deferred processing anywhere.
"""
from clock import clock
from decimal import Decimal as D

import calc
from calc import (
    ARTIFACT_SCOPE,
    LOCK_MIN_CONFIDENCE,
    MIN_DISTINCT_PARTICIPANTS,
    MIN_PUBLISH_STRENGTH,
    recompute_decision_confidence,
    recompute_finding,
    recompute_participant,
    recompute_pool,
    refresh_theme_weights,
    set_field,
)
from store import db


class Tally:
    """Counters for the retention sweep answer, de-duplicated by row id."""

    def __init__(self):
        self.expired_consents = set()
        self.purged_artifacts = set()
        self.inadmissible_links = set()
        self.retracted_findings = set()
        self.overdue_follow_ups = set()
        self.unlocked_decisions = set()

    def as_response(self):
        return {
            "expired_consent_count": len(self.expired_consents),
            "purged_artifact_count": len(self.purged_artifacts),
            "inadmissible_link_count": len(self.inadmissible_links),
            "retracted_finding_count": len(self.retracted_findings),
            "overdue_follow_up_count": len(self.overdue_follow_ups),
            "unlocked_decision_count": len(self.unlocked_decisions),
        }


def consent_artifacts(consent):
    """Artifacts of the consent record's own participant-and-study whose type
    maps to a scope the record granted and which are still RETAINED."""
    out = []
    for artifact in db.artifacts.values():
        if artifact["lifecycle_state"] != "RETAINED":
            continue
        recruitment = db.recruitments.get(artifact["recruitment_id"])
        if recruitment is None:
            continue
        if recruitment["participant_id"] != consent["participant_id"]:
            continue
        if recruitment["study_id"] != consent["study_id"]:
            continue
        if ARTIFACT_SCOPE[artifact["artifact_type"]] not in consent["scopes"]:
            continue
        out.append(artifact)
    return out


def purge_artifacts(artifacts, reason, tally):
    """Hop 1: RETAINED -> PURGED."""
    purged = []
    stamp = clock.now()
    for artifact in artifacts:
        if artifact["lifecycle_state"] != "RETAINED":
            continue
        set_field(artifact, "lifecycle_state", "PURGED")
        set_field(artifact, "purged_at", stamp)
        set_field(artifact, "purge_reason", reason)
        tally.purged_artifacts.add(artifact["id"])
        purged.append(artifact)
    return purged


def cascade_from_purged(purged, tally):
    """Hops 2 through 5."""
    if not purged:
        return
    purged_ids = {a["id"] for a in purged}

    # Hop 2 - evidence links citing a purged artifact go inadmissible.
    touched_findings = {}
    for link in db.links.values():
        if link["artifact_id"] not in purged_ids:
            continue
        if not link["is_admissible"]:
            continue
        set_field(link, "is_admissible", False)
        set_field(link, "inadmissible_reason", "ARTIFACT_PURGED")
        tally.inadmissible_links.add(link["id"])
        finding = db.findings.get(link["finding_id"])
        if finding is not None:
            touched_findings[finding["id"]] = finding

    # Hop 3 - findings re-score under their own current variant and may retract.
    changed = []
    for finding in touched_findings.values():
        before_status = finding["status"]
        before_strength = finding["evidence_strength"]
        recompute_finding(finding)
        if (
            finding["status"] == "PUBLISHED"
            and (
                D(finding["evidence_strength"]) < MIN_PUBLISH_STRENGTH
                or finding["distinct_participant_count"] < MIN_DISTINCT_PARTICIPANTS
            )
        ):
            set_field(finding, "status", "RETRACTED")
            set_field(finding, "retraction_reason", "EVIDENCE_WITHDRAWN")
            tally.retracted_findings.add(finding["id"])
        if finding["status"] != before_status or finding["evidence_strength"] != before_strength:
            changed.append(finding)

    if not changed:
        return

    # Hop 4 - themes re-weigh, children before parents and then up the chain.
    for theme_id in {f["theme_id"] for f in changed}:
        refresh_theme_weights(db.themes.get(theme_id))

    # Hop 5 - decisions reachable through an ACCEPTED readout may unlock.
    study_ids = {f["study_id"] for f in changed}
    decisions = {}
    for readout in db.readouts.values():
        if readout["status"] != "ACCEPTED":
            continue
        if readout["study_id"] not in study_ids:
            continue
        decision = db.decisions.get(readout["roadmap_decision_id"])
        if decision is not None:
            decisions[decision["id"]] = decision
    for decision in decisions.values():
        value = recompute_decision_confidence(decision)
        if decision["status"] == "LOCKED" and value < LOCK_MIN_CONFIDENCE:
            set_field(decision, "status", "OPEN")
            set_field(decision, "locked_at", None)
            tally.unlocked_decisions.add(decision["id"])


def run_consent_cascade(consent, reason, tally=None):
    """Both endings of a consent record run the same cascade."""
    tally = tally or Tally()
    purged = purge_artifacts(consent_artifacts(consent), reason, tally)
    cascade_from_purged(purged, tally)
    return tally


def retention_sweep():
    """The platform's only clock-driven actor: it applies exactly what is due at
    the clock's present value."""
    tally = Tally()
    now = clock.now()

    # Consent records whose retention horizon has been reached expire.
    for consent in calc.by_created(list(db.consents.values())):
        if consent["status"] != "GRANTED":
            continue
        if consent["retention_until"] is not None and consent["retention_until"] <= now:
            set_field(consent, "status", "EXPIRED")
            tally.expired_consents.add(consent["id"])
            run_consent_cascade(consent, "RETENTION_EXPIRED", tally)

    # Artifacts purge in their own right once their retention horizon is due.
    due = []
    for artifact in calc.by_created(list(db.artifacts.values())):
        if artifact["lifecycle_state"] != "RETAINED":
            continue
        if artifact["retention_until"] is not None and artifact["retention_until"] <= now:
            due.append(artifact)
    if due:
        purged = purge_artifacts(due, "RETENTION_EXPIRED", tally)
        cascade_from_purged(purged, tally)

    # Follow-ups fall overdue once their due date is strictly earlier than now.
    for followup in calc.by_created(list(db.followups.values())):
        if followup["status"] != "OPEN":
            continue
        if followup["due_date"] is not None and followup["due_date"] < now:
            set_field(followup, "status", "OVERDUE")
            tally.overdue_follow_ups.add(followup["id"])

    # Contact posture is re-derived so a COOLDOWN participant whose window has
    # rolled past returns to ELIGIBLE.
    for participant in calc.by_created(list(db.participants.values())):
        recompute_participant(participant)
    for pool in calc.by_created(list(db.pools.values())):
        recompute_pool(pool)

    return tally.as_response()
