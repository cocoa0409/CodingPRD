"""Evidence strength: the pinned per-link rounding order, the two variants that read
different numbers off identical links, the cardinality boundaries that guard a lock,
the mass that must survive an add-then-delete, and which guard wins on a purged
artifact borrowed from another study."""

import pytest

from test_helpers import (
    RESEARCHER_HEADERS,
    RESEARCH_LEAD_HEADERS,
    ApiErrorId,
    approve_guide,
    assert_evidence_link,
    assert_finding,
    assert_research_artifact,
    assert_theme,
    close_fielding,
    complete_session,
    create_decision,
    create_evidence_link_payload,
    create_finding,
    create_study,
    create_theme,
    field_study,
    grant_consent,
    invite,
    link_evidence,
    read_artifact,
    read_finding,
    read_theme,
    register_artifact,
    revoke_consent,
    schedule,
    screen,
    set_clock,
    setup_approved_request,
    setup_completed_sessions,
    setup_draft_finding_with_links,
    setup_pool_with_participants,
    setup_study_in_analysis,
    validate_error,
    validate_paginated,
    validate_success,
    write_guide,
)

CLOCK_START = "2026-08-01T00:00:00Z"
SESSION_START = "2026-08-05T14:00:00Z"
SESSION_END = "2026-08-05T15:00:00Z"


def _diary_finding_with_three_observed_links(api):
    """A DIARY_STUDY in analysis carrying one DRAFT finding with three
    OBSERVED_BEHAVIOR links, one per participant's recording."""
    set_clock(CLOCK_START, api)
    return setup_draft_finding_with_links(
        api,
        weight_classes=("OBSERVED_BEHAVIOR", "OBSERVED_BEHAVIOR", "OBSERVED_BEHAVIOR"),
        severity="HIGH",
        method="DIARY_STUDY",
        participant_count=3,
        target_participant_count=3,
        artifact_type="RECORDING",
    )


class TestFindingStrengthProvisionalVersusCorroborated:
    def test_a_draft_finding_scores_its_three_links_under_the_provisional_variant(self, api):
        """Three OBSERVED_BEHAVIOR links on a diary study each contribute 0.94, and the
        draft finding divides that raw total of 2.82 by 4.00.

        PRD 3.7: "Every evidence link of the finding whose `is_admissible` is true gets a
        `contribution`: multiply the weight of its `weight_class` — 1.00 for
        `DIRECT_QUOTE`, 0.85 for `OBSERVED_BEHAVIOR`, 0.50 for `SELF_REPORT` — by the
        multiplier of the study's `method` — 1.20 for `USABILITY_TEST`, 1.10 for
        `DIARY_STUDY`, 1.00 for `INTERVIEW`, 0.70 for `SURVEY` — and round the product
        half-up to two decimal places."

        PRD 3.7: "While the finding is `DRAFT` the **provisional** variant applies: divide
        the raw total by 4.00, hold the quotient at a ceiling of 1.00, and round half-up to
        two decimals."

        Design: Difficulty/dual_variant_calc/finding_strength_provisional_vs_corroborated
        """
        ctx = _diary_finding_with_three_observed_links(api)
        finding = read_finding(ctx["finding"]["id"], api)
        assert_finding(finding)

        assert finding["status"] == "DRAFT", (
            f"Expected DRAFT, got {finding['status']} before the evidence set is locked"
        )
        assert finding["strength_variant"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {finding['strength_variant']} on a draft finding"
        )
        assert finding["evidence_strength"] == pytest.approx(0.71, abs=0.01), (
            f"Expected 0.71 from 2.82 over 4.00, got {finding['evidence_strength']}"
        )
        assert finding["admissible_link_count"] == 3, (
            f"Expected 3 admissible links, got {finding['admissible_link_count']}"
        )
        assert finding["distinct_participant_count"] == 3, (
            f"Expected 3 distinct participants, got {finding['distinct_participant_count']}"
        )

        rows, _meta = validate_paginated(
            api.list_finding_evidence_links(finding["id"], RESEARCHER_HEADERS)
        )
        assert len(rows) == 3, f"Expected 3 evidence links, got {len(rows)}"
        for row in rows:
            assert_evidence_link(row)
            assert row["contribution"] == pytest.approx(0.94, abs=0.01), (
                f"Expected each OBSERVED_BEHAVIOR contribution to be 0.94, got {row['contribution']}"
            )

    def test_locking_reads_the_same_links_under_the_corroborated_variant(self, api):
        """Locking changes the number without touching a single link: the same 2.82 of
        evidence mass scores 0.56 once the divisor tightens to 3.00 and breadth applies.

        PRD 3.7: "Once the finding is `EVIDENCE_LOCKED`, `PUBLISHED` or `RETRACTED` the
        **corroborated** variant applies, and it is computed in three steps: divide the raw
        total by the tighter 3.00, hold it at a ceiling of 1.00 and round to **four**
        decimal places to obtain a density; divide `distinct_participant_count` by 5, hold
        that at a ceiling of 1.00 and round half-up to two decimals to obtain a
        corroboration factor; then multiply density by corroboration factor and round
        half-up to two decimals."

        PRD 3.7: "On success `strength_variant` is set to `CORROBORATED` and
        `evidence_strength` is recomputed under that variant, which typically moves the
        number: the same links that scored provisionally against a divisor of 4.00 now
        score against 3.00 and are then scaled by participant breadth."

        Design: Difficulty/dual_variant_calc/finding_strength_provisional_vs_corroborated
        """
        ctx = _diary_finding_with_three_observed_links(api)
        finding_id = ctx["finding"]["id"]
        provisional = read_finding(finding_id, api)
        assert provisional["evidence_strength"] == pytest.approx(0.71, abs=0.01), (
            f"Expected 0.71 before the lock, got {provisional['evidence_strength']}"
        )

        locked = validate_success(api.lock_finding(finding_id, RESEARCHER_HEADERS))
        assert_finding(locked)
        assert locked["status"] == "EVIDENCE_LOCKED", (
            f"Expected EVIDENCE_LOCKED, got {locked['status']}"
        )
        assert locked["strength_variant"] == "CORROBORATED", (
            f"Expected CORROBORATED, got {locked['strength_variant']} after locking"
        )
        assert locked["evidence_strength"] == pytest.approx(0.56, abs=0.01), (
            f"Expected 0.56 from density 0.9400 times factor 0.60, got {locked['evidence_strength']}"
        )
        assert locked["evidence_strength"] != pytest.approx(0.71, abs=0.001), (
            "Expected the two variants to disagree on identical link data, "
            f"but the locked finding still reads {locked['evidence_strength']}"
        )

        assert locked["admissible_link_count"] == 3, (
            f"Expected the link set to be untouched at 3, got {locked['admissible_link_count']}"
        )
        assert locked["distinct_participant_count"] == 3, (
            f"Expected 3 distinct participants after locking, got {locked['distinct_participant_count']}"
        )
        rows, _meta = validate_paginated(
            api.list_finding_evidence_links(finding_id, RESEARCHER_HEADERS)
        )
        assert len(rows) == 3, f"Expected the same 3 evidence links after locking, got {len(rows)}"
        for row in rows:
            assert row["contribution"] == pytest.approx(0.94, abs=0.01), (
                f"Expected each contribution to still be 0.94 after locking, got {row['contribution']}"
            )
            assert row["is_admissible"] is True, (
                f"Expected every link to stay admissible after locking, got {row['is_admissible']}"
            )


def _one_participant_three_artifacts_two_links(api):
    """A DIARY_STUDY with a single completed session carrying three artifacts, and a
    DRAFT finding already citing two of them as OBSERVED_BEHAVIOR."""
    set_clock(CLOCK_START, api)
    ctx = setup_completed_sessions(
        api,
        method="DIARY_STUDY",
        participant_count=1,
        target_participant_count=1,
        artifact_type="RECORDING",
        retention_days=90,
    )
    recruitment_id = ctx["recruitments"][0]["id"]
    ctx["artifacts"].append(
        register_artifact(recruitment_id, api, artifact_type="TRANSCRIPT")
    )
    ctx["artifacts"].append(
        register_artifact(recruitment_id, api, artifact_type="PII_NOTE", contains_pii=True)
    )
    ctx["theme"] = create_theme(api)
    ctx["finding"] = create_finding(
        ctx["study"]["id"], ctx["theme"]["id"], api, severity="HIGH"
    )
    ctx["links"] = [
        link_evidence(
            ctx["finding"]["id"],
            ctx["artifacts"][index]["id"],
            api,
            weight_class="OBSERVED_BEHAVIOR",
        )
        for index in (0, 1)
    ]
    ctx["finding"] = read_finding(ctx["finding"]["id"], api)
    return ctx


class TestEvidenceStrengthRoundsPerLinkThenSums:
    def test_each_link_stores_its_own_rounded_contribution(self, api):
        """0.85 times 1.10 is 0.935, and every link stores that product already rounded to
        0.94 rather than carrying an unrounded figure into the total.

        PRD 3.7: "Every evidence link of the finding whose `is_admissible` is true gets a
        `contribution`: multiply the weight of its `weight_class` — 1.00 for
        `DIRECT_QUOTE`, 0.85 for `OBSERVED_BEHAVIOR`, 0.50 for `SELF_REPORT` — by the
        multiplier of the study's `method` — 1.20 for `USABILITY_TEST`, 1.10 for
        `DIARY_STUDY`, 1.00 for `INTERVIEW`, 0.70 for `SURVEY` — and round the product
        half-up to two decimal places."

        PRD 2.8: "Unless a specific rule says otherwise, every derived decimal quantity in
        this system is rounded to **2 decimal places using round-half-up** — that is, a
        value exactly at the midpoint rounds away from zero, so a raw 0.125 stored at two
        decimals becomes 0.13."

        Design: Difficulty/combinatorial_formula/evidence_strength_rounds_per_link_then_sums
        """
        ctx = _one_participant_three_artifacts_two_links(api)

        for link in ctx["links"]:
            assert_evidence_link(link)
            assert link["contribution"] == pytest.approx(0.94, abs=0.01), (
                f"Expected 0.935 rounded half-up to 0.94, got {link['contribution']}"
            )

        finding = ctx["finding"]
        assert finding["evidence_strength"] == pytest.approx(0.47, abs=0.01), (
            f"Expected 0.47 from two rounded 0.94 terms over 4.00, got {finding['evidence_strength']}"
        )
        assert finding["admissible_link_count"] == 2, (
            f"Expected 2 admissible links before the third is added, got {finding['admissible_link_count']}"
        )
        assert finding["distinct_participant_count"] == 1, (
            f"Expected 1 distinct participant, got {finding['distinct_participant_count']}"
        )

    def test_the_third_link_lands_on_the_sum_of_rounded_terms_not_the_rounded_sum(self, api):
        """Three links of 0.94 total 2.82 and score 0.71; summing the unrounded 0.935
        products first would total 2.805 and score 0.70, which is explicitly not the rule.

        PRD 3.7: "**The rounding order here is pinned and it matters**: each link's
        `contribution` is rounded to two decimals *first*, and the raw total is the sum of
        those already-rounded terms. Summing the unrounded products and rounding at the end
        is explicitly not the rule."

        PRD 3.7: "While the finding is `DRAFT` the **provisional** variant applies: divide
        the raw total by 4.00, hold the quotient at a ceiling of 1.00, and round half-up to
        two decimals."

        Design: Difficulty/combinatorial_formula/evidence_strength_rounds_per_link_then_sums
        """
        ctx = _one_participant_three_artifacts_two_links(api)
        finding_id = ctx["finding"]["id"]
        assert ctx["finding"]["evidence_strength"] == pytest.approx(0.47, abs=0.01), (
            f"Expected 0.47 with two links, got {ctx['finding']['evidence_strength']}"
        )

        third = validate_success(
            api.create_evidence_link(
                finding_id,
                create_evidence_link_payload(
                    ctx["artifacts"][2]["id"], weight_class="OBSERVED_BEHAVIOR"
                ),
                RESEARCHER_HEADERS,
            ),
            expected_status=201,
        )
        assert third["contribution"] == pytest.approx(0.94, abs=0.01), (
            f"Expected the third contribution to be 0.94, got {third['contribution']}"
        )

        finding = read_finding(finding_id, api)
        assert finding["evidence_strength"] == pytest.approx(0.71, abs=0.01), (
            f"Expected 2.82 over 4.00 to give 0.71, got {finding['evidence_strength']}"
        )
        assert finding["evidence_strength"] != pytest.approx(0.70, abs=0.001), (
            "Expected the sum of already-rounded contributions, but "
            f"{finding['evidence_strength']} is what summing the unrounded 0.935 products would give"
        )
        assert finding["admissible_link_count"] == 3, (
            f"Expected 3 admissible links, got {finding['admissible_link_count']}"
        )
        assert finding["distinct_participant_count"] == 1, (
            f"Expected 1 distinct participant behind all three artifacts, got {finding['distinct_participant_count']}"
        )


def _interview_study_in_analysis_with_two_bare_findings(api):
    """An INTERVIEW study in analysis with one recording per participant and two DRAFT
    findings that carry no evidence links at all."""
    set_clock(CLOCK_START, api)
    ctx = setup_study_in_analysis(
        api,
        method="INTERVIEW",
        participant_count=3,
        target_participant_count=3,
        artifact_type="RECORDING",
    )
    ctx["theme"] = create_theme(api)
    ctx["finding_a"] = create_finding(
        ctx["study"]["id"], ctx["theme"]["id"], api, severity="MEDIUM"
    )
    ctx["finding_b"] = create_finding(
        ctx["study"]["id"], ctx["theme"]["id"], api, severity="MEDIUM"
    )
    return ctx


class TestFindingLockOnEmptyAndMinimumEvidenceSets:
    def test_locking_a_finding_with_an_empty_admissible_set_is_refused(self, api):
        """Zero admissible links is the empty end of the cardinality boundary, and the lock
        is refused there without moving the finding out of DRAFT.

        PRD 3.7: "It must carry at least one admissible link, else
        `ERR_NO_ADMISSIBLE_EVIDENCE`."

        PRD 3.7: "The finding opens in `status` `DRAFT` with `strength_variant`
        `PROVISIONAL`, `evidence_strength` 0.00, `admissible_link_count` and
        `distinct_participant_count` at 0, `retraction_reason` and `published_at` null, and
        `authored_by_user_id` set to the creating operator's `X-User-ID`."

        Design: Difficulty/boundary_precision_check/finding_lock_on_empty_and_minimum_evidence_sets
        """
        ctx = _interview_study_in_analysis_with_two_bare_findings(api)
        finding_id = ctx["finding_a"]["id"]

        assert ctx["finding_a"]["admissible_link_count"] == 0, (
            f"Expected 0 admissible links on a fresh finding, got {ctx['finding_a']['admissible_link_count']}"
        )
        assert ctx["finding_a"]["evidence_strength"] == pytest.approx(0.00, abs=0.01), (
            f"Expected 0.00 on a fresh finding, got {ctx['finding_a']['evidence_strength']}"
        )

        refused = api.lock_finding(finding_id, RESEARCHER_HEADERS)
        validate_error(refused, ApiErrorId.NO_ADMISSIBLE_EVIDENCE.value)

        untouched = read_finding(finding_id, api)
        assert untouched["status"] == "DRAFT", (
            f"Expected DRAFT, got {untouched['status']} after a lock refused for an empty evidence set"
        )
        assert untouched["strength_variant"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {untouched['strength_variant']} after a refused lock"
        )

    def test_the_lock_opens_only_at_exactly_three_distinct_participants(self, api):
        """One and two distinct participants are both short of the corroboration floor; the
        third participant is the first cardinality the lock accepts.

        PRD 3.7: "And its `distinct_participant_count` must be **at least 3**, else
        `ERR_INSUFFICIENT_CORROBORATION` — three separate people, not three excerpts from
        one."

        PRD 3.7: "Once the finding is `EVIDENCE_LOCKED`, `PUBLISHED` or `RETRACTED` the
        **corroborated** variant applies, and it is computed in three steps: divide the raw
        total by the tighter 3.00, hold it at a ceiling of 1.00 and round to **four**
        decimal places to obtain a density; divide `distinct_participant_count` by 5, hold
        that at a ceiling of 1.00 and round half-up to two decimals to obtain a
        corroboration factor; then multiply density by corroboration factor and round
        half-up to two decimals."

        Design: Difficulty/boundary_precision_check/finding_lock_on_empty_and_minimum_evidence_sets
        """
        ctx = _interview_study_in_analysis_with_two_bare_findings(api)
        finding_id = ctx["finding_b"]["id"]

        link_evidence(finding_id, ctx["artifacts"][0]["id"], api, weight_class="DIRECT_QUOTE")
        one_participant = read_finding(finding_id, api)
        assert one_participant["distinct_participant_count"] == 1, (
            f"Expected 1 distinct participant, got {one_participant['distinct_participant_count']}"
        )
        validate_error(
            api.lock_finding(finding_id, RESEARCHER_HEADERS),
            ApiErrorId.INSUFFICIENT_CORROBORATION.value,
        )

        link_evidence(finding_id, ctx["artifacts"][1]["id"], api, weight_class="DIRECT_QUOTE")
        two_participants = read_finding(finding_id, api)
        assert two_participants["distinct_participant_count"] == 2, (
            f"Expected 2 distinct participants, got {two_participants['distinct_participant_count']}"
        )
        validate_error(
            api.lock_finding(finding_id, RESEARCHER_HEADERS),
            ApiErrorId.INSUFFICIENT_CORROBORATION.value,
        )
        assert read_finding(finding_id, api)["status"] == "DRAFT", (
            "Expected the finding to still be DRAFT after two refused locks"
        )

        link_evidence(finding_id, ctx["artifacts"][2]["id"], api, weight_class="DIRECT_QUOTE")
        three_participants = read_finding(finding_id, api)
        assert three_participants["distinct_participant_count"] == 3, (
            f"Expected 3 distinct participants, got {three_participants['distinct_participant_count']}"
        )
        assert three_participants["strength_variant"] == "PROVISIONAL", (
            f"Expected PROVISIONAL before the lock, got {three_participants['strength_variant']}"
        )
        assert three_participants["evidence_strength"] == pytest.approx(0.75, abs=0.01), (
            f"Expected 3.00 over 4.00 to give 0.75 before the lock, got {three_participants['evidence_strength']}"
        )

        locked = validate_success(api.lock_finding(finding_id, RESEARCHER_HEADERS))
        assert locked["status"] == "EVIDENCE_LOCKED", (
            f"Expected EVIDENCE_LOCKED at exactly three distinct participants, got {locked['status']}"
        )
        assert locked["strength_variant"] == "CORROBORATED", (
            f"Expected CORROBORATED, got {locked['strength_variant']}"
        )
        assert locked["evidence_strength"] == pytest.approx(0.60, abs=0.01), (
            f"Expected density 1.0000 times factor 0.60 to give 0.60, got {locked['evidence_strength']}"
        )
        assert locked["admissible_link_count"] == 3, (
            f"Expected 3 admissible links, got {locked['admissible_link_count']}"
        )


def _diary_finding_with_mixed_weight_links(api):
    """A DIARY_STUDY in analysis where participant 1 carries two artifacts and
    participants 2 and 3 one each, with a DRAFT finding citing one artifact per
    participant at three different weight classes."""
    set_clock(CLOCK_START, api)
    ctx = setup_completed_sessions(
        api,
        method="DIARY_STUDY",
        participant_count=3,
        target_participant_count=3,
        artifact_type="RECORDING",
    )
    ctx["extra_artifact"] = register_artifact(
        ctx["recruitments"][0]["id"], api, artifact_type="TRANSCRIPT"
    )
    ctx["study"] = close_fielding(ctx["study"]["id"], api)
    ctx["theme"] = create_theme(api)
    ctx["finding"] = create_finding(
        ctx["study"]["id"], ctx["theme"]["id"], api, severity="HIGH"
    )
    ctx["links"] = [
        link_evidence(
            ctx["finding"]["id"], ctx["artifacts"][0]["id"], api,
            weight_class="OBSERVED_BEHAVIOR",
        ),
        link_evidence(
            ctx["finding"]["id"], ctx["artifacts"][1]["id"], api,
            weight_class="SELF_REPORT",
        ),
        link_evidence(
            ctx["finding"]["id"], ctx["artifacts"][2]["id"], api,
            weight_class="DIRECT_QUOTE",
        ),
    ]
    ctx["finding"] = read_finding(ctx["finding"]["id"], api)
    return ctx


class TestFindingEvidenceMassIsConservedAcrossAddAndDelete:
    def test_the_three_starting_links_store_their_rounded_contributions(self, api):
        """The baseline mass is the sum of three already-rounded terms, 0.94 plus 0.55 plus
        1.10, and 2.59 over 4.00 rounds half-up to 0.65.

        PRD 3.7: "**The rounding order here is pinned and it matters**: each link's
        `contribution` is rounded to two decimals *first*, and the raw total is the sum of
        those already-rounded terms. Summing the unrounded products and rounding at the end
        is explicitly not the rule."

        PRD 3.7: "Alongside the total, `admissible_link_count` is the number of admissible
        links, and `distinct_participant_count` is the number of distinct participants
        reached by walking each admissible link to its artifact, the artifact to its
        recruitment, and the recruitment to its participant."

        Design: Difficulty/compensating_invariant/finding_evidence_mass_conserved_across_link_add_and_delete
        """
        ctx = _diary_finding_with_mixed_weight_links(api)
        observed, self_report, direct_quote = ctx["links"]

        assert observed["contribution"] == pytest.approx(0.94, abs=0.01), (
            f"Expected 0.85 times 1.10 rounded to 0.94, got {observed['contribution']}"
        )
        assert self_report["contribution"] == pytest.approx(0.55, abs=0.01), (
            f"Expected 0.50 times 1.10 rounded to 0.55, got {self_report['contribution']}"
        )
        assert direct_quote["contribution"] == pytest.approx(1.10, abs=0.01), (
            f"Expected 1.00 times 1.10 rounded to 1.10, got {direct_quote['contribution']}"
        )

        finding = ctx["finding"]
        assert finding["evidence_strength"] == pytest.approx(0.65, abs=0.01), (
            f"Expected 2.59 over 4.00 to give 0.6475 rounded to 0.65, got {finding['evidence_strength']}"
        )
        assert finding["admissible_link_count"] == 3, (
            f"Expected 3 admissible links, got {finding['admissible_link_count']}"
        )
        assert finding["distinct_participant_count"] == 3, (
            f"Expected 3 distinct participants, got {finding['distinct_participant_count']}"
        )

    def test_deleting_the_added_link_restores_the_exact_earlier_strength(self, api):
        """Adding a fourth link on participant 1's second artifact lifts the strength to
        0.88, and deleting it recomputes back to exactly 0.65 rather than subtracting the
        departing link's rounded contribution from 0.88.

        PRD 3.7: "Removing a link is permitted only while the finding is `DRAFT` — on an
        `EVIDENCE_LOCKED`, `PUBLISHED` or `RETRACTED` finding it is refused with
        `ERR_INVALID_STATE` — and it reverses the link's effect exactly, recomputing
        `admissible_link_count`, `distinct_participant_count` and `evidence_strength` back
        to precisely the values they held before that link was added. Removal answers with
        204 and no body."

        Design: Difficulty/compensating_invariant/finding_evidence_mass_conserved_across_link_add_and_delete
        """
        ctx = _diary_finding_with_mixed_weight_links(api)
        finding_id = ctx["finding"]["id"]
        before = read_finding(finding_id, api)
        assert before["evidence_strength"] == pytest.approx(0.65, abs=0.01), (
            f"Expected 0.65 before the add, got {before['evidence_strength']}"
        )

        fourth = validate_success(
            api.create_evidence_link(
                finding_id,
                create_evidence_link_payload(
                    ctx["extra_artifact"]["id"], weight_class="OBSERVED_BEHAVIOR"
                ),
                RESEARCHER_HEADERS,
            ),
            expected_status=201,
        )
        assert fourth["contribution"] == pytest.approx(0.94, abs=0.01), (
            f"Expected the fourth contribution to be 0.94, got {fourth['contribution']}"
        )

        enlarged = read_finding(finding_id, api)
        assert enlarged["evidence_strength"] == pytest.approx(0.88, abs=0.01), (
            f"Expected mass 3.53 over 4.00 to give 0.88, got {enlarged['evidence_strength']}"
        )
        assert enlarged["admissible_link_count"] == 4, (
            f"Expected 4 admissible links, got {enlarged['admissible_link_count']}"
        )
        assert enlarged["distinct_participant_count"] == 3, (
            "Expected the breadth to stay at 3 because the new artifact belongs to a "
            f"participant already counted, got {enlarged['distinct_participant_count']}"
        )

        removal = api.delete_evidence_link(fourth["id"], RESEARCHER_HEADERS)
        assert removal.status_code == 204, (
            f"Expected 204 on removal, got {removal.status_code} with body {removal.text!r}"
        )
        assert not removal.content, (
            f"Expected an empty body on removal, got {removal.text!r}"
        )

        restored = read_finding(finding_id, api)
        assert restored["evidence_strength"] == pytest.approx(0.65, abs=0.01), (
            "Expected the strength recomputed from the surviving links back to 0.65, got "
            f"{restored['evidence_strength']}"
        )
        assert restored["evidence_strength"] != pytest.approx(0.64, abs=0.001), (
            "Expected a recomputation, but 0.88 minus the departing link's 0.24 share of "
            f"the quotient is what {restored['evidence_strength']} would mean"
        )
        assert restored["admissible_link_count"] == 3, (
            f"Expected 3 admissible links after removal, got {restored['admissible_link_count']}"
        )
        assert restored["distinct_participant_count"] == 3, (
            f"Expected 3 distinct participants after removal, got {restored['distinct_participant_count']}"
        )

        rows, _meta = validate_paginated(
            api.list_finding_evidence_links(finding_id, RESEARCHER_HEADERS)
        )
        assert len(rows) == 3, f"Expected exactly 3 surviving links, got {len(rows)}"
        orphaned, _meta = validate_paginated(
            api.list_artifact_evidence_links(ctx["extra_artifact"]["id"], RESEARCHER_HEADERS)
        )
        assert orphaned == [], (
            f"Expected no links left citing the removed artifact, got {orphaned}"
        )

    def test_the_restored_mass_propagates_through_the_lock_and_the_theme_rollup(self, api):
        """Because the surviving mass is exactly 2.59 again, the corroborated variant reads
        0.52 and the published finding rolls 0.78 of weight up onto its theme.

        PRD 3.7: "Once the finding is `EVIDENCE_LOCKED`, `PUBLISHED` or `RETRACTED` the
        **corroborated** variant applies, and it is computed in three steps: divide the raw
        total by the tighter 3.00, hold it at a ceiling of 1.00 and round to **four**
        decimal places to obtain a density; divide `distinct_participant_count` by 5, hold
        that at a ceiling of 1.00 and round half-up to two decimals to obtain a
        corroboration factor; then multiply density by corroboration factor and round
        half-up to two decimals."

        PRD 3.7: "A theme's `own_evidence_weight` is the sum, over every `PUBLISHED`
        finding whose `theme_id` is that theme, of the finding's `evidence_strength`
        multiplied by its severity multiplier — 1.50 for `HIGH`, 1.00 for `MEDIUM`, 0.60 for
        `LOW` — with each per-finding term rounded half-up to two decimals before it enters
        the sum."

        PRD 3.7: "The theme's `evidence_weight` is then its own weight plus the
        `evidence_weight` of every theme whose `parent_theme_id` names it, the total again
        rounded half-up to two decimals."

        PRD 3.7: "A theme whose `evidence_weight` is **at least 1.20** is `ESTABLISHED`;
        below that it is `EMERGING`, and the two transitions between those postures are pure
        consequences of the rollup, never a command."

        Design: Difficulty/compensating_invariant/finding_evidence_mass_conserved_across_link_add_and_delete
        """
        ctx = _diary_finding_with_mixed_weight_links(api)
        finding_id = ctx["finding"]["id"]

        fourth = link_evidence(
            finding_id, ctx["extra_artifact"]["id"], api, weight_class="OBSERVED_BEHAVIOR"
        )
        removal = api.delete_evidence_link(fourth["id"], RESEARCHER_HEADERS)
        assert removal.status_code == 204, (
            f"Expected 204 on removal, got {removal.status_code}"
        )

        locked = validate_success(api.lock_finding(finding_id, RESEARCHER_HEADERS))
        assert locked["strength_variant"] == "CORROBORATED", (
            f"Expected CORROBORATED, got {locked['strength_variant']}"
        )
        assert locked["evidence_strength"] == pytest.approx(0.52, abs=0.01), (
            "Expected density 0.8633 times factor 0.60 to give 0.52, got "
            f"{locked['evidence_strength']}"
        )

        published = validate_success(api.publish_finding(finding_id, RESEARCH_LEAD_HEADERS))
        assert published["status"] == "PUBLISHED", (
            f"Expected PUBLISHED, got {published['status']}"
        )
        assert published["evidence_strength"] == pytest.approx(0.52, abs=0.01), (
            f"Expected the published strength to stay 0.52, got {published['evidence_strength']}"
        )

        theme = read_theme(ctx["theme"]["id"], api)
        assert_theme(theme)
        assert theme["own_evidence_weight"] == pytest.approx(0.78, abs=0.01), (
            f"Expected 0.52 times the HIGH multiplier 1.50 to give 0.78, got {theme['own_evidence_weight']}"
        )
        assert theme["evidence_weight"] == pytest.approx(0.78, abs=0.01), (
            f"Expected a childless theme's rolled-up weight to equal 0.78, got {theme['evidence_weight']}"
        )
        assert theme["status"] == "EMERGING", (
            f"Expected EMERGING below the 1.20 bar, got {theme['status']}"
        )


def _artifact_of_another_study(api, revoke):
    """Two studies on one decision sharing one pool and one participant. Study A is never
    fielded and holds a bare DRAFT finding; study B holds the participant's completed
    session and its single RECORDING artifact, optionally purged by revoking consent."""
    set_clock(CLOCK_START, api)
    decision = create_decision(api)
    intake_a = setup_approved_request(api, method="INTERVIEW", decision=decision)
    intake_b = setup_approved_request(api, method="INTERVIEW", decision=decision)
    panel = setup_pool_with_participants(api, participant_count=1)
    participant_id = panel["participants"][0]["id"]

    study_a = create_study(
        intake_a["request"]["id"], panel["pool"]["id"], api,
        method="INTERVIEW", target_participant_count=1,
    )
    study_b = create_study(
        intake_b["request"]["id"], panel["pool"]["id"], api,
        method="INTERVIEW", target_participant_count=1,
    )
    write_guide(study_b["id"], api)
    approve_guide(study_b["id"], api)
    study_b = field_study(study_b["id"], api)

    consent = grant_consent(
        participant_id, study_b["id"], api, scopes=["RECORDING"], retention_days=90
    )
    recruitment = screen(invite(study_b["id"], participant_id, api)["id"], api)
    recruitment = schedule(recruitment["id"], SESSION_START, SESSION_END, api)
    recruitment = complete_session(recruitment["id"], api)
    artifact = register_artifact(recruitment["id"], api, artifact_type="RECORDING")

    if revoke:
        revoke_consent(consent["id"], api)

    theme = create_theme(api)
    finding = create_finding(study_a["id"], theme["id"], api, severity="MEDIUM")
    return {
        "study_a": study_a,
        "study_b": study_b,
        "artifact": read_artifact(artifact["id"], api),
        "finding": finding,
        "theme": theme,
        "consent": consent,
    }


class TestEvidenceLinkSafetyPurgeOutranksReferentialMismatch:
    def test_a_purged_artifact_from_another_study_is_refused_for_the_purge(self, api):
        """The cited artifact is both purged and owned by a different study, and the
        privacy-safety guard is the one that answers.

        PRD 3.7: "Three conditions guard the write. The cited artifact's `lifecycle_state`
        must be `RETAINED`, else `ERR_ARTIFACT_PURGED`. The artifact must belong to the same
        study as the finding — resolved from the artifact's `recruitment_id` to that
        recruitment's `study_id`, compared against the finding's `study_id` — else
        `ERR_EVIDENCE_STUDY_MISMATCH`, which is how the platform stops evidence being
        borrowed across studies."

        PRD 3.6: "Its `purged_at` is set to the clock instant and its `purge_reason` is set
        to `CONSENT_REVOKED` on the revocation path or `RETENTION_EXPIRED` on the expiry
        path."

        Design: Difficulty/priority_pair_validation_conflict/evidence_link_safety_purge_outranks_referential_mismatch
        """
        ctx = _artifact_of_another_study(api, revoke=True)
        artifact = ctx["artifact"]
        assert_research_artifact(artifact)
        assert artifact["lifecycle_state"] == "PURGED", (
            f"Expected PURGED after the revocation, got {artifact['lifecycle_state']}"
        )
        assert artifact["purge_reason"] == "CONSENT_REVOKED", (
            f"Expected purge_reason CONSENT_REVOKED, got {artifact['purge_reason']}"
        )

        finding_id = ctx["finding"]["id"]
        refused = api.create_evidence_link(
            finding_id,
            create_evidence_link_payload(artifact["id"], weight_class="DIRECT_QUOTE"),
            RESEARCHER_HEADERS,
        )
        error = validate_error(refused, ApiErrorId.ARTIFACT_PURGED.value)
        assert error["error_id"] != ApiErrorId.EVIDENCE_STUDY_MISMATCH.value, (
            "Expected the purge guard to answer ahead of the referential guard, got "
            f"{error['error_id']} even though the artifact belongs to another study"
        )

        untouched = read_finding(finding_id, api)
        assert untouched["admissible_link_count"] == 0, (
            f"Expected 0 admissible links after the refusal, got {untouched['admissible_link_count']}"
        )
        assert untouched["evidence_strength"] == pytest.approx(0.00, abs=0.01), (
            f"Expected 0.00 after the refusal, got {untouched['evidence_strength']}"
        )
        rows, _meta = validate_paginated(
            api.list_finding_evidence_links(finding_id, RESEARCHER_HEADERS)
        )
        assert rows == [], f"Expected no evidence links on the finding, got {rows}"

    def test_a_retained_artifact_from_another_study_is_refused_for_the_mismatch(self, api):
        """With the same cross-study shape but a retained artifact, the referential guard is
        the one that answers, which is what makes the purge guard's precedence observable.

        PRD 3.7: "Three conditions guard the write. The cited artifact's `lifecycle_state`
        must be `RETAINED`, else `ERR_ARTIFACT_PURGED`. The artifact must belong to the same
        study as the finding — resolved from the artifact's `recruitment_id` to that
        recruitment's `study_id`, compared against the finding's `study_id` — else
        `ERR_EVIDENCE_STUDY_MISMATCH`, which is how the platform stops evidence being
        borrowed across studies."

        Design: Difficulty/priority_pair_validation_conflict/evidence_link_safety_purge_outranks_referential_mismatch
        """
        ctx = _artifact_of_another_study(api, revoke=False)
        artifact = ctx["artifact"]
        assert artifact["lifecycle_state"] == "RETAINED", (
            f"Expected RETAINED with consent still granted, got {artifact['lifecycle_state']}"
        )
        assert ctx["study_a"]["id"] != ctx["study_b"]["id"], (
            "Expected the finding and the artifact to sit on different studies"
        )

        finding_id = ctx["finding"]["id"]
        refused = api.create_evidence_link(
            finding_id,
            create_evidence_link_payload(artifact["id"], weight_class="DIRECT_QUOTE"),
            RESEARCHER_HEADERS,
        )
        validate_error(refused, ApiErrorId.EVIDENCE_STUDY_MISMATCH.value)

        untouched = read_finding(finding_id, api)
        assert untouched["admissible_link_count"] == 0, (
            f"Expected 0 admissible links after the refusal, got {untouched['admissible_link_count']}"
        )
        rows, _meta = validate_paginated(
            api.list_finding_evidence_links(finding_id, RESEARCHER_HEADERS)
        )
        assert rows == [], f"Expected no evidence links on the finding, got {rows}"
