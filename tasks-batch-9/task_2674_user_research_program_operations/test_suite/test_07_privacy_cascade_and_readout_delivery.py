"""Privacy cascade depth and the cross-entity gate on readout delivery.

Two behaviours live here.  The first is the five-hop evidence-withdrawal
cascade that a single consent revocation sets off: artifacts purge, the
evidence links citing them go inadmissible, the findings that lost those links
re-score and retract, the theme they roll into re-weighs, and the decision that
was locked on that evidence unlocks.  The second is the delivery guard that
reads the live publication state of the findings a readout cites rather than a
flag copied onto the readout when it was drafted.
"""

import pytest

from test_helpers import (
    PRIVACY_OFFICER_HEADERS,
    RESEARCH_LEAD_HEADERS,
    RESEARCHER_HEADERS,
    STAKEHOLDER_HEADERS,
    draft_readout,
    publish_finding,
    read_decision,
    read_finding,
    read_readout,
    read_study,
    read_theme,
    revoke_consent,
    setup_locked_decision_on_dual_findings,
    setup_locked_finding,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Shared preconditions
# ---------------------------------------------------------------------------
def _locked_decision_on_two_published_findings(api):
    """A DIARY_STUDY whose three RECORDING artifacts each back two published
    HIGH-severity findings, cited by one accepted readout, on a decision the
    stakeholder has locked.

    Every observable figure of that precondition follows from the PRD: each
    ``OBSERVED_BEHAVIOR`` link contributes 0.85 * 1.10 = 0.94, so three links
    give a raw total of 2.82; the corroborated variant turns that into a
    density of 0.9400 scaled by a corroboration factor of 0.60, giving each
    finding an ``evidence_strength`` of 0.56.  The theme sums two HIGH terms of
    0.84 to 1.68, and the readout's contribution is the 0.5600 mean of the two
    strengths times the DIARY_STUDY multiplier 1.10, i.e. 0.62.
    """
    return setup_locked_decision_on_dual_findings(
        api,
        method="DIARY_STUDY",
        weight_class="OBSERVED_BEHAVIOR",
        participant_count=3,
        severity="HIGH",
        artifact_type="RECORDING",
        contains_pii=True,
        consent_scopes=["RECORDING"],
        retention_days=120,
        pool_overrides={"incentive_budget_cents": 100000},
    )


def _links_citing(api, artifact_id):
    rows, _meta = validate_paginated(
        api.list_artifact_evidence_links(artifact_id, RESEARCHER_HEADERS)
    )
    return rows


# ===========================================================================
# The five-hop evidence-withdrawal cascade
# ===========================================================================
def test_revocation_purges_only_the_covered_artifact(api):
    """Revoking one participant's consent moves that session's artifact to PURGED
    and leaves the other two participants' artifacts alone.

    PRD 3.6: "A `PrivacyOfficer` — and only a `PrivacyOfficer` — may revoke a
    `GRANTED` record with a supplied `reason`, carrying it `GRANTED → REVOKED`,
    setting `revoked_at` to the clock instant and storing the `reason` as
    `revocation_reason`."

    PRD 3.6: "Every artifact whose `recruitment_id` resolves to a recruitment
    sharing the consent record's `participant_id` and `study_id`, whose
    `artifact_type` maps to a scope the consent record granted, and whose
    `lifecycle_state` is still `RETAINED`, moves `RETAINED → PURGED`. Its
    `purged_at` is set to the clock instant and its `purge_reason` is set to
    `CONSENT_REVOKED` on the revocation path or `RETENTION_EXPIRED` on the
    expiry path. Artifacts of a type the record did not cover are untouched, as
    are artifacts of other participants or other studies."

    Design: Difficulty/transitive_cascade/consent_revocation_five_hop_evidence_withdrawal
    """
    ctx = _locked_decision_on_two_published_findings(api)
    artifacts = ctx["artifacts"]
    assert len(artifacts) == 3, f"Expected three registered artifacts, got {len(artifacts)}"

    revoked = validate_success(
        api.revoke_consent_record(
            ctx["consents"][0]["id"],
            {"reason": "Participant withdrew consent by email"},
            PRIVACY_OFFICER_HEADERS,
        )
    )
    assert revoked["status"] == "REVOKED", (
        f"Expected the revoked consent record to read REVOKED, got {revoked['status']}"
    )
    assert revoked["revoked_at"] is not None, (
        "Expected revoked_at to be stamped from the logical clock on the revocation path"
    )
    assert revoked["revocation_reason"] == "Participant withdrew consent by email", (
        f"Expected the supplied reason to land in revocation_reason, "
        f"got {revoked['revocation_reason']!r}"
    )

    purged = validate_success(api.get_artifact(artifacts[0]["id"], RESEARCHER_HEADERS))
    assert purged["lifecycle_state"] == "PURGED", (
        f"Expected the revoking participant's RECORDING to be PURGED, "
        f"got {purged['lifecycle_state']}"
    )
    assert purged["purge_reason"] == "CONSENT_REVOKED", (
        f"Expected purge_reason CONSENT_REVOKED on the revocation path, "
        f"got {purged['purge_reason']!r}"
    )
    assert purged["purged_at"] is not None, (
        "Expected purged_at to be set to the clock instant when the artifact purged"
    )

    for index in (1, 2):
        untouched = validate_success(
            api.get_artifact(artifacts[index]["id"], RESEARCHER_HEADERS)
        )
        assert untouched["lifecycle_state"] == "RETAINED", (
            f"Expected artifact {index} of another participant to stay RETAINED, "
            f"got {untouched['lifecycle_state']}"
        )
        assert untouched["purge_reason"] is None, (
            f"Expected artifact {index} to keep a null purge_reason, "
            f"got {untouched['purge_reason']!r}"
        )


def test_purging_the_artifact_makes_every_link_citing_it_inadmissible(api):
    """The two evidence links that cited the purged artifact — one per finding —
    flip to inadmissible while the four links citing the surviving artifacts stay
    admissible.

    PRD 3.6: "For each artifact that just became `PURGED`, every evidence link
    citing it whose `is_admissible` is still true is flipped to false with
    `inadmissible_reason` set to `ARTIFACT_PURGED`. The link row is not deleted
    — it remains readable as a record of evidence that was once cited."

    Design: Difficulty/transitive_cascade/consent_revocation_five_hop_evidence_withdrawal
    """
    ctx = _locked_decision_on_two_published_findings(api)
    artifacts = ctx["artifacts"]

    before = _links_citing(api, artifacts[0]["id"])
    assert len(before) == 2, (
        f"Expected both findings to cite the first artifact, got {len(before)} links"
    )
    assert all(link["is_admissible"] for link in before), (
        "Expected every link to start admissible before the revocation"
    )

    revoke_consent(ctx["consents"][0]["id"], api)

    after = _links_citing(api, artifacts[0]["id"])
    assert len(after) == 2, (
        f"Expected the inadmissible link rows to survive the cascade, got {len(after)}"
    )
    for link in after:
        assert link["is_admissible"] is False, (
            f"Expected link {link['id']} citing the purged artifact to go inadmissible, "
            f"got is_admissible {link['is_admissible']}"
        )
        assert link["inadmissible_reason"] == "ARTIFACT_PURGED", (
            f"Expected inadmissible_reason ARTIFACT_PURGED, "
            f"got {link['inadmissible_reason']!r}"
        )

    for index in (1, 2):
        for link in _links_citing(api, artifacts[index]["id"]):
            assert link["is_admissible"] is True, (
                f"Expected links citing the retained artifact {index} to stay admissible, "
                f"got is_admissible {link['is_admissible']}"
            )
            assert link["inadmissible_reason"] is None, (
                f"Expected a null inadmissible_reason on the surviving link {link['id']}, "
                f"got {link['inadmissible_reason']!r}"
            )


def test_the_withdrawn_evidence_rescores_and_retracts_both_published_findings(api):
    """Two admissible links from two participants re-score each published finding
    from 0.56 to 0.25 under the corroborated variant, which retracts both.

    PRD 3.6: "Every finding that just lost an admissible link has its
    `admissible_link_count`, `distinct_participant_count` and
    `evidence_strength` recomputed under **its own current variant** — a draft
    finding is re-scored provisionally, a locked, published or retracted one
    under the corroborated variant. A finding whose `status` is `PUBLISHED` and
    whose recomputed `evidence_strength` has fallen **below 0.45**, *or* whose
    recomputed `distinct_participant_count` has fallen **below 3**, moves
    `PUBLISHED → RETRACTED` with `retraction_reason` set to
    `EVIDENCE_WITHDRAWN`."

    PRD 3.7: "Once the finding is `EVIDENCE_LOCKED`, `PUBLISHED` or `RETRACTED`
    the **corroborated** variant applies, and it is computed in three steps:
    divide the raw total by the tighter 3.00, hold it at a ceiling of 1.00 and
    round to **four** decimal places to obtain a density; divide
    `distinct_participant_count` by 5, hold that at a ceiling of 1.00 and round
    half-up to two decimals to obtain a corroboration factor; then multiply
    density by corroboration factor and round half-up to two decimals."

    Design: Difficulty/transitive_cascade/consent_revocation_five_hop_evidence_withdrawal
    """
    ctx = _locked_decision_on_two_published_findings(api)
    findings = ctx["findings"]
    assert len(findings) == 2, f"Expected two findings on the study, got {len(findings)}"

    for finding in findings:
        baseline = read_finding(finding["id"], api)
        assert baseline["status"] == "PUBLISHED", (
            f"Expected finding {finding['id']} to start PUBLISHED, got {baseline['status']}"
        )
        assert baseline["evidence_strength"] == pytest.approx(0.56, abs=0.01), (
            f"Expected a corroborated strength of 0.56 from three OBSERVED_BEHAVIOR links "
            f"on a DIARY_STUDY, got {baseline['evidence_strength']}"
        )

    revoke_consent(ctx["consents"][0]["id"], api)

    for finding in findings:
        rescored = read_finding(finding["id"], api)
        assert rescored["admissible_link_count"] == 2, (
            f"Expected two admissible links to survive, "
            f"got {rescored['admissible_link_count']}"
        )
        assert rescored["distinct_participant_count"] == 2, (
            f"Expected the purged artifact's participant to drop out of the count, "
            f"got {rescored['distinct_participant_count']}"
        )
        assert rescored["evidence_strength"] == pytest.approx(0.25, abs=0.01), (
            f"Expected 0.6267 density times a 0.40 corroboration factor to give 0.25, "
            f"got {rescored['evidence_strength']}"
        )
        assert rescored["status"] == "RETRACTED", (
            f"Expected the published finding to retract once its strength fell below "
            f"0.45 and its participant count below 3, got {rescored['status']}"
        )
        assert rescored["retraction_reason"] == "EVIDENCE_WITHDRAWN", (
            f"Expected retraction_reason EVIDENCE_WITHDRAWN, "
            f"got {rescored['retraction_reason']!r}"
        )


def test_the_retractions_empty_the_theme_and_drop_its_rolled_up_weight(api):
    """With both findings retracted the theme has no published finding left, so
    its own and rolled-up weights fall to 0.00 and it drops back to EMERGING.

    PRD 3.6: "Every theme referenced by a finding that just retracted is
    recomputed — its own weight first, then the rolled-up weight, then the same
    rollup applied up the `parent_theme_id` chain one level at a time to the
    root — which may move a theme `ESTABLISHED → EMERGING`."

    PRD 3.7: "A theme's `own_evidence_weight` is the sum, over every
    `PUBLISHED` finding whose `theme_id` is that theme, of the finding's
    `evidence_strength` multiplied by its severity multiplier — 1.50 for
    `HIGH`, 1.00 for `MEDIUM`, 0.60 for `LOW` — with each per-finding term
    rounded half-up to two decimals before it enters the sum. Findings in
    `DRAFT`, `EVIDENCE_LOCKED` or `RETRACTED` contribute exactly 0.00."

    PRD 3.7: "A theme whose `evidence_weight` is **at least 1.20** is
    `ESTABLISHED`; below that it is `EMERGING`, and the two transitions between
    those postures are pure consequences of the rollup, never a command."

    Design: Difficulty/transitive_cascade/consent_revocation_five_hop_evidence_withdrawal
    """
    ctx = _locked_decision_on_two_published_findings(api)

    baseline = read_theme(ctx["theme"]["id"], api)
    assert baseline["evidence_weight"] == pytest.approx(1.68, abs=0.01), (
        f"Expected two HIGH findings at 0.56 to roll up to 1.68, "
        f"got {baseline['evidence_weight']}"
    )
    assert baseline["status"] == "ESTABLISHED", (
        f"Expected 1.68 to clear the 1.20 bar and read ESTABLISHED, got {baseline['status']}"
    )

    revoke_consent(ctx["consents"][0]["id"], api)

    reweighed = read_theme(ctx["theme"]["id"], api)
    assert reweighed["own_evidence_weight"] == pytest.approx(0.00, abs=0.01), (
        f"Expected retracted findings to contribute exactly 0.00, "
        f"got {reweighed['own_evidence_weight']}"
    )
    assert reweighed["evidence_weight"] == pytest.approx(0.00, abs=0.01), (
        f"Expected the rolled-up weight of a childless theme to match its own weight, "
        f"got {reweighed['evidence_weight']}"
    )
    assert reweighed["status"] == "EMERGING", (
        f"Expected the theme to fall back to EMERGING below 1.20, got {reweighed['status']}"
    )


def test_the_recomputed_confidence_unlocks_the_decision_and_clears_locked_at(api):
    """The accepted readout's study has no published finding left, so the
    decision's confidence recomputes to 0.00, the lock is released and
    `locked_at` goes back to null.

    PRD 3.6: "Every roadmap decision reachable through an `ACCEPTED` readout of
    a study whose finding just retracted has its `evidence_confidence`
    recomputed. A decision whose `status` is `LOCKED` and whose recomputed
    confidence has fallen **below 0.60** moves `LOCKED → OPEN`, keeps the
    recomputed value in `evidence_confidence`, and has `locked_at` cleared back
    to null."

    PRD 3.8: "Collect the findings of that readout's study whose `status` is
    `PUBLISHED`; if there are none, the readout contributes exactly 0.00."

    Design: Difficulty/transitive_cascade/consent_revocation_five_hop_evidence_withdrawal
    """
    ctx = _locked_decision_on_two_published_findings(api)

    baseline = read_decision(ctx["decision"]["id"], api)
    assert baseline["status"] == "LOCKED", (
        f"Expected the decision to start LOCKED on the accepted evidence, "
        f"got {baseline['status']}"
    )
    assert baseline["evidence_confidence"] == pytest.approx(0.62, abs=0.01), (
        f"Expected a 0.5600 mean times the DIARY_STUDY multiplier 1.10 to give 0.62, "
        f"got {baseline['evidence_confidence']}"
    )
    assert baseline["locked_at"] is not None, (
        "Expected locked_at to be stamped while the decision is LOCKED"
    )

    revoke_consent(ctx["consents"][0]["id"], api)

    unlocked = read_decision(ctx["decision"]["id"], api)
    assert unlocked["evidence_confidence"] == pytest.approx(0.00, abs=0.01), (
        f"Expected a readout with no published findings to contribute 0.00, "
        f"got {unlocked['evidence_confidence']}"
    )
    assert unlocked["status"] == "OPEN", (
        f"Expected the decision to unlock once confidence fell below 0.60, "
        f"got {unlocked['status']}"
    )
    assert unlocked["locked_at"] is None, (
        f"Expected locked_at to be cleared back to null on the unlock, "
        f"got {unlocked['locked_at']!r}"
    )


def test_the_accepted_readout_keeps_its_recorded_before_and_after_confidences(api):
    """The unlock comes from the recomputed aggregate, not from rewriting the
    readout: it stays ACCEPTED with the two confidence figures it captured at
    acceptance.

    PRD 3.8: "On the `DELIVERED → ACCEPTED` transition the platform captures
    the decision's current `evidence_confidence` into the readout's
    `decision_confidence_before`, recomputes that decision's
    `evidence_confidence` from scratch, and stores the recomputed figure into
    the readout's `decision_confidence_after` as well as onto the decision
    itself."

    PRD 3.8: "Both outcomes require the readout to be `DELIVERED` and set
    `responded_at` to the clock instant, and both are terminal."

    Design: Difficulty/transitive_cascade/consent_revocation_five_hop_evidence_withdrawal
    """
    ctx = _locked_decision_on_two_published_findings(api)

    before_cascade = read_readout(ctx["readout"]["id"], api)
    assert before_cascade["status"] == "ACCEPTED", (
        f"Expected the readout to start ACCEPTED, got {before_cascade['status']}"
    )
    assert before_cascade["decision_confidence_before"] == pytest.approx(0.00, abs=0.01), (
        f"Expected the decision's confidence at acceptance time to be captured as 0.00, "
        f"got {before_cascade['decision_confidence_before']}"
    )
    assert before_cascade["decision_confidence_after"] == pytest.approx(0.62, abs=0.01), (
        f"Expected the recomputed 0.62 to be stored as decision_confidence_after, "
        f"got {before_cascade['decision_confidence_after']}"
    )

    revoke_consent(ctx["consents"][0]["id"], api)

    after_cascade = read_readout(ctx["readout"]["id"], api)
    assert after_cascade["status"] == "ACCEPTED", (
        f"Expected ACCEPTED to be terminal across the cascade, got {after_cascade['status']}"
    )
    assert after_cascade["decision_confidence_before"] == pytest.approx(0.00, abs=0.01), (
        f"Expected decision_confidence_before to survive the cascade unchanged, "
        f"got {after_cascade['decision_confidence_before']}"
    )
    assert after_cascade["decision_confidence_after"] == pytest.approx(0.62, abs=0.01), (
        f"Expected decision_confidence_after to survive the cascade unchanged, "
        f"got {after_cascade['decision_confidence_after']}"
    )
    assert after_cascade["responded_at"] == before_cascade["responded_at"], (
        f"Expected responded_at to stay at {before_cascade['responded_at']!r}, "
        f"got {after_cascade['responded_at']!r}"
    )


# ===========================================================================
# Delivery reads the live publication state of the findings it cites
# ===========================================================================
def _draft_readout_citing_a_locked_finding(api):
    """A study in analysis carrying one EVIDENCE_LOCKED finding with three
    DIRECT_QUOTE links, and a DRAFT readout that cites it."""
    ctx = setup_locked_finding(api)
    ctx["readout"] = draft_readout(
        ctx["study"]["id"], ctx["decision"]["id"], [ctx["finding"]["id"]], api
    )
    ctx["study"] = read_study(ctx["study"]["id"], api)
    return ctx


def test_delivery_is_refused_while_the_cited_finding_is_only_evidence_locked(api):
    """The write target is the readout but the gate is the cited finding's state:
    delivery is refused while that finding is still EVIDENCE_LOCKED.

    PRD 3.8: "And the citation set must still hold up: `cited_finding_ids` must
    be non-empty and **every** cited finding must be in `status` `PUBLISHED` at
    the moment of delivery, else `ERR_NO_PUBLISHED_FINDINGS` — a finding that
    was published when the draft was written and has since been retracted by a
    privacy cascade will block delivery."

    Design: Difficulty/cross_entity_state_dependency/readout_delivery_gated_on_cited_finding_publication
    """
    ctx = _draft_readout_citing_a_locked_finding(api)

    cited = read_finding(ctx["finding"]["id"], api)
    assert cited["status"] == "EVIDENCE_LOCKED", (
        f"Expected the cited finding to sit in EVIDENCE_LOCKED before publication, "
        f"got {cited['status']}"
    )

    validate_error(
        api.deliver_readout(ctx["readout"]["id"], RESEARCHER_HEADERS),
        "ERR_NO_PUBLISHED_FINDINGS",
    )

    refused = read_readout(ctx["readout"]["id"], api)
    assert refused["status"] == "DRAFT", (
        f"Expected the refused readout to stay DRAFT, got {refused['status']}"
    )
    assert refused["delivered_at"] is None, (
        f"Expected delivered_at to stay null after the refusal, "
        f"got {refused['delivered_at']!r}"
    )

    study = read_study(ctx["study"]["id"], api)
    assert study["execution_status"] == "ANALYSIS", (
        f"Expected the study to stay in ANALYSIS after the refused delivery, "
        f"got {study['execution_status']}"
    )


def test_publishing_the_cited_finding_opens_delivery_and_reports_the_study(api):
    """The same payload that was refused succeeds the moment a second operator
    publishes the cited finding, and the accepted delivery reports the study.

    PRD 3.7: "Publication is the `ResearchLead`'s or `ResearchOpsAdmin`'s act
    and it carries the finding `EVIDENCE_LOCKED → PUBLISHED`."

    PRD 3.8: "On success `delivered_at` is set to the current logical clock
    instant, the study moves `ANALYSIS → REPORTED` with its `version`
    incremented by 1, and the study's operations metrics are refreshed."

    Design: Difficulty/cross_entity_state_dependency/readout_delivery_gated_on_cited_finding_publication
    """
    ctx = _draft_readout_citing_a_locked_finding(api)

    validate_error(
        api.deliver_readout(ctx["readout"]["id"], RESEARCHER_HEADERS),
        "ERR_NO_PUBLISHED_FINDINGS",
    )

    published = validate_success(
        api.publish_finding(ctx["finding"]["id"], RESEARCH_LEAD_HEADERS)
    )
    assert published["status"] == "PUBLISHED", (
        f"Expected publication by an operator other than the author to succeed, "
        f"got {published['status']}"
    )

    delivered = validate_success(
        api.deliver_readout(ctx["readout"]["id"], RESEARCHER_HEADERS)
    )
    assert delivered["status"] == "DELIVERED", (
        f"Expected the second delivery attempt to carry the readout to DELIVERED, "
        f"got {delivered['status']}"
    )
    assert delivered["delivered_at"] is not None, (
        "Expected delivered_at to be set from the logical clock on a successful delivery"
    )

    study = read_study(ctx["study"]["id"], api)
    assert study["execution_status"] == "REPORTED", (
        f"Expected the delivery to carry the study ANALYSIS -> REPORTED, "
        f"got {study['execution_status']}"
    )


def test_delivering_the_readout_leaves_the_decision_confidence_at_zero(api):
    """A delivered but unanswered readout contributes nothing, so the decision's
    confidence is still 0.00 after delivery.

    PRD 3.8: "Readouts in `DRAFT`, `SUPERSEDED`, `DELIVERED` or `DEFERRED`
    contribute nothing at all."

    Design: Difficulty/cross_entity_state_dependency/readout_delivery_gated_on_cited_finding_publication
    """
    ctx = _draft_readout_citing_a_locked_finding(api)
    publish_finding(ctx["finding"]["id"], api)
    validate_success(api.deliver_readout(ctx["readout"]["id"], RESEARCHER_HEADERS))

    decision = validate_success(
        api.get_roadmap_decision(ctx["decision"]["id"], STAKEHOLDER_HEADERS)
    )
    assert decision["evidence_confidence"] == pytest.approx(0.00, abs=0.01), (
        f"Expected a delivered-but-unanswered readout to contribute nothing, "
        f"got evidence_confidence {decision['evidence_confidence']}"
    )
    assert decision["status"] == "OPEN", (
        f"Expected the decision to stay OPEN after a mere delivery, got {decision['status']}"
    )


def test_publishing_the_cited_finding_rolls_its_strength_into_the_theme(api):
    """Publication is what gives the finding weight: 0.60 at MEDIUM severity rolls
    into the theme, which stays EMERGING because 0.60 is short of 1.20.

    PRD 3.7: "On success `published_at` is set to the current logical clock
    instant and the theme weights are recomputed for the finding's theme and
    every ancestor of it."

    PRD 3.7: "A theme whose `evidence_weight` is **at least 1.20** is
    `ESTABLISHED`; below that it is `EMERGING`, and the two transitions between
    those postures are pure consequences of the rollup, never a command."

    Design: Difficulty/cross_entity_state_dependency/readout_delivery_gated_on_cited_finding_publication
    """
    ctx = _draft_readout_citing_a_locked_finding(api)

    theme_before = read_theme(ctx["theme"]["id"], api)
    assert theme_before["evidence_weight"] == pytest.approx(0.00, abs=0.01), (
        f"Expected an EVIDENCE_LOCKED finding to carry no theme weight, "
        f"got {theme_before['evidence_weight']}"
    )

    published = validate_success(
        api.publish_finding(ctx["finding"]["id"], RESEARCH_LEAD_HEADERS)
    )
    assert published["published_at"] is not None, (
        "Expected published_at to be stamped from the logical clock on publication"
    )
    assert published["evidence_strength"] == pytest.approx(0.60, abs=0.01), (
        f"Expected three DIRECT_QUOTE links on an INTERVIEW to give a corroborated "
        f"1.0000 density times a 0.60 corroboration factor, got "
        f"{published['evidence_strength']}"
    )

    theme_after = read_theme(ctx["theme"]["id"], api)
    assert theme_after["evidence_weight"] == pytest.approx(0.60, abs=0.01), (
        f"Expected 0.60 times the MEDIUM multiplier 1.00 to roll up as 0.60, "
        f"got {theme_after['evidence_weight']}"
    )
    assert theme_after["status"] == "EMERGING", (
        f"Expected 0.60 to stay below the 1.20 bar and read EMERGING, "
        f"got {theme_after['status']}"
    )
