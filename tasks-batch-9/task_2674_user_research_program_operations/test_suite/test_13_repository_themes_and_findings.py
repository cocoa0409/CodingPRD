"""Insight-repository corners: the theme tree, the evidence junction, the weight
rollup, the duplicate-label guard, the publish strength gate and the theme index
round trip."""

import pytest

from test_helpers import (
    RESEARCH_LEAD_HEADERS,
    RESEARCH_OPS_ADMIN_HEADERS,
    RESEARCHER_HEADERS,
    assert_ordered_desc_then_created_at,
    assert_theme,
    create_evidence_link_payload,
    create_finding,
    create_participant_pool_payload,
    create_theme,
    create_theme_payload,
    link_evidence,
    lock_finding,
    read_finding,
    read_theme,
    set_clock,
    setup_completed_sessions,
    setup_locked_finding,
    setup_study_in_analysis,
    setup_theme_chain,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# The theme tree is capped at three levels
# ===========================================================================
def test_theme_depth_runs_one_two_three_down_the_parent_chain(api):
    """A root theme is depth 1 and every nested theme is its parent's depth plus one.

    PRD 3.7: "A theme with no parent is a root and its `depth` is 1; a nested
    theme's `depth` is its parent's `depth` plus 1."

    PRD 3.7: "A new theme opens `EMERGING` with `own_evidence_weight` and
    `evidence_weight` both 0.00 and `reuse_count` at 0."

    Design: Corner/entities/theme_hierarchy_depth_is_capped_at_three
    """
    chain = setup_theme_chain(api, depth=3)

    for level, theme in enumerate(chain, start=1):
        assert_theme(theme)
        assert theme["depth"] == level, (
            f"Expected depth {level} at level {level} of the parent chain, "
            f"got {theme['depth']}"
        )
        assert theme["status"] == "EMERGING", (
            f"Expected a fresh theme to open EMERGING, got {theme['status']}"
        )
        assert float(theme["own_evidence_weight"]) == pytest.approx(0.00, abs=0.01), (
            f"Expected own_evidence_weight 0.00 on a fresh theme, "
            f"got {theme['own_evidence_weight']}"
        )
        assert float(theme["evidence_weight"]) == pytest.approx(0.00, abs=0.01), (
            f"Expected evidence_weight 0.00 on a fresh theme, "
            f"got {theme['evidence_weight']}"
        )
        assert theme["reuse_count"] == 0, (
            f"Expected reuse_count 0 on a fresh theme, got {theme['reuse_count']}"
        )

    assert chain[0].get("parent_theme_id") is None, (
        f"Expected the root theme to carry a null parent_theme_id, "
        f"got {chain[0].get('parent_theme_id')!r}"
    )
    assert chain[1]["parent_theme_id"] == chain[0]["id"], (
        "Expected the second-level theme to name the root as its parent"
    )
    assert chain[2]["parent_theme_id"] == chain[1]["id"], (
        "Expected the third-level theme to name the second level as its parent"
    )


def test_nesting_under_a_third_level_theme_is_refused(api):
    """A fourth level would push `depth` above 3, which the repository refuses.

    PRD 3.7: "**The tree is capped at three levels**: nesting that would give the
    new theme a `depth` above 3 is refused with `ERR_THEME_DEPTH_EXCEEDED`, so a
    theme may be created under a root or under a second-level theme but never
    under a third-level one."

    Design: Corner/entities/theme_hierarchy_depth_is_capped_at_three
    """
    chain = setup_theme_chain(api, depth=3)
    third_level_id = chain[2]["id"]

    refused = api.create_theme(
        create_theme_payload(
            label="Onboarding / invites / roles / naming",
            parent_theme_id=third_level_id,
        ),
        RESEARCHER_HEADERS,
    )
    validate_error(refused, "ERR_THEME_DEPTH_EXCEEDED")

    children = api.list_themes(
        RESEARCHER_HEADERS, {"parent_theme_id": third_level_id}
    )
    rows, meta = validate_paginated(children)
    assert meta["total_count"] == 0, (
        f"Expected no theme to have been persisted under the third level, "
        f"got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected an empty child list, got {len(rows)} rows"


# ===========================================================================
# One artifact backs two findings: the evidence-link junction
# ===========================================================================
def test_one_artifact_backs_two_findings_and_is_navigable_from_both_ends(api):
    """Two findings cite the same artifact and each end lists the rows that reach it.

    PRD 3.7: "Evidence links are what connect a claim to the sessions that
    support it."

    PRD 2.7: "When a nested creation carries the parent's identifier in the path,
    the stored foreign-key field on the new row is taken from that path segment
    and not from the body: a participant's `pool_id`, a recruitment's `study_id`,
    an artifact's `recruitment_id`, an evidence link's `finding_id` and a
    follow-up's `readout_id` are all filled in this way."

    PRD 3.6: "Consent records may be read individually or listed with optional
    `participant_id`, `study_id` and `status` filters; a recruitment's artifacts
    may be listed with optional `artifact_type` and `lifecycle_state` filters; an
    artifact may be read on its own, exposing its retention horizon and lifecycle
    state; and the evidence links citing one artifact may be listed with an
    optional `is_admissible` filter."

    Design: Corner/entities/evidence_link_junction_connects_two_findings_to_one_artifact
    """
    ctx = setup_completed_sessions(
        api, participant_count=1, artifact_type="RECORDING", contains_pii=True
    )
    artifact_id = ctx["artifacts"][0]["id"]
    theme = create_theme(api, label="Invite expectations")
    first = create_finding(
        ctx["study"]["id"],
        theme["id"],
        api,
        statement="Admins expect invites to explain roles",
        severity="MEDIUM",
    )
    second = create_finding(
        ctx["study"]["id"],
        theme["id"],
        api,
        statement="Admins expect a resend control on invites",
        severity="LOW",
    )

    first_link = validate_success(
        api.create_evidence_link(
            first["id"],
            create_evidence_link_payload(
                artifact_id, weight_class="DIRECT_QUOTE", excerpt_ref="00:06:10"
            ),
            RESEARCHER_HEADERS,
        ),
        201,
    )
    second_link = validate_success(
        api.create_evidence_link(
            second["id"],
            create_evidence_link_payload(
                artifact_id, weight_class="SELF_REPORT", excerpt_ref="00:22:40"
            ),
            RESEARCHER_HEADERS,
        ),
        201,
    )

    assert first_link["finding_id"] == first["id"], (
        "Expected the first link's finding_id to come from the path segment"
    )
    assert second_link["finding_id"] == second["id"], (
        "Expected the second link's finding_id to come from the path segment"
    )
    assert first_link["artifact_id"] == artifact_id, (
        "Expected the first link to cite the one registered artifact"
    )
    assert second_link["artifact_id"] == artifact_id, (
        "Expected the second link to cite the very same artifact"
    )

    from_artifact = api.list_artifact_evidence_links(artifact_id, RESEARCHER_HEADERS)
    artifact_rows, artifact_meta = validate_paginated(from_artifact)
    assert artifact_meta["total_count"] == 2, (
        f"Expected the artifact to list both citing links, "
        f"got total_count {artifact_meta['total_count']}"
    )
    assert {row["finding_id"] for row in artifact_rows} == {
        first["id"],
        second["id"],
    }, "Expected one row per citing finding when navigating from the artifact"

    for finding_id in (first["id"], second["id"]):
        from_finding = api.list_finding_evidence_links(finding_id, RESEARCHER_HEADERS)
        finding_rows, finding_meta = validate_paginated(from_finding)
        assert finding_meta["total_count"] == 1, (
            f"Expected finding {finding_id} to hold exactly one link, "
            f"got total_count {finding_meta['total_count']}"
        )
        assert finding_rows[0]["artifact_id"] == artifact_id, (
            "Expected the finding's single link to point back at the artifact"
        )


def test_two_links_on_one_artifact_score_by_their_own_weight_classes(api):
    """The junction's two rows contribute independently to their own findings.

    PRD 3.7: "Every evidence link of the finding whose `is_admissible` is true
    gets a `contribution`: multiply the weight of its `weight_class` — 1.00 for
    `DIRECT_QUOTE`, 0.85 for `OBSERVED_BEHAVIOR`, 0.50 for `SELF_REPORT` — by the
    multiplier of the study's `method` — 1.20 for `USABILITY_TEST`, 1.10 for
    `DIARY_STUDY`, 1.00 for `INTERVIEW`, 0.70 for `SURVEY` — and round the product
    half-up to two decimal places."

    PRD 3.7: "While the finding is `DRAFT` the **provisional** variant applies:
    divide the raw total by 4.00, hold the quotient at a ceiling of 1.00, and
    round half-up to two decimals."

    PRD 3.7: "Alongside the total, `admissible_link_count` is the number of
    admissible links, and `distinct_participant_count` is the number of distinct
    participants reached by walking each admissible link to its artifact, the
    artifact to its recruitment, and the recruitment to its participant."

    Design: Corner/entities/evidence_link_junction_connects_two_findings_to_one_artifact
    """
    ctx = setup_completed_sessions(
        api, participant_count=1, artifact_type="RECORDING", contains_pii=True
    )
    artifact_id = ctx["artifacts"][0]["id"]
    theme = create_theme(api, label="Invite expectations")
    first = create_finding(ctx["study"]["id"], theme["id"], api, severity="MEDIUM")
    second = create_finding(ctx["study"]["id"], theme["id"], api, severity="LOW")

    first_link = link_evidence(
        first["id"], artifact_id, api, weight_class="DIRECT_QUOTE"
    )
    second_link = link_evidence(
        second["id"], artifact_id, api, weight_class="SELF_REPORT"
    )

    assert float(first_link["contribution"]) == pytest.approx(1.00, abs=0.01), (
        f"Expected DIRECT_QUOTE 1.00 times the INTERVIEW multiplier 1.00, "
        f"got {first_link['contribution']}"
    )
    assert float(second_link["contribution"]) == pytest.approx(0.50, abs=0.01), (
        f"Expected SELF_REPORT 0.50 times the INTERVIEW multiplier 1.00, "
        f"got {second_link['contribution']}"
    )
    assert first_link["is_admissible"] is True, (
        "Expected a fresh evidence link to open admissible"
    )
    assert second_link["is_admissible"] is True, (
        "Expected a fresh evidence link to open admissible"
    )

    first_read = read_finding(first["id"], api)
    second_read = read_finding(second["id"], api)

    assert first_read["strength_variant"] == "PROVISIONAL", (
        f"Expected a DRAFT finding to score provisionally, "
        f"got {first_read['strength_variant']}"
    )
    assert float(first_read["evidence_strength"]) == pytest.approx(0.25, abs=0.01), (
        f"Expected a raw total of 1.00 over the 4.00 provisional divisor, "
        f"got {first_read['evidence_strength']}"
    )
    assert float(second_read["evidence_strength"]) == pytest.approx(0.13, abs=0.01), (
        f"Expected a raw total of 0.50 over the 4.00 provisional divisor rounded "
        f"half-up, got {second_read['evidence_strength']}"
    )
    for finding in (first_read, second_read):
        assert finding["distinct_participant_count"] == 1, (
            f"Expected one distinct participant behind the shared artifact, "
            f"got {finding['distinct_participant_count']}"
        )
        assert finding["admissible_link_count"] == 1, (
            f"Expected exactly one admissible link per finding, "
            f"got {finding['admissible_link_count']}"
        )


# ===========================================================================
# Published weight climbs from the child theme to its parent
# ===========================================================================
def test_publishing_a_child_finding_lifts_the_parent_evidence_weight(api):
    """The parent's own weight stays 0.00 while its rolled-up weight follows the child.

    PRD 3.7: "A theme's `own_evidence_weight` is the sum, over every `PUBLISHED`
    finding whose `theme_id` is that theme, of the finding's `evidence_strength`
    multiplied by its severity multiplier — 1.50 for `HIGH`, 1.00 for `MEDIUM`,
    0.60 for `LOW` — with each per-finding term rounded half-up to two decimals
    before it enters the sum."

    PRD 3.7: "The theme's `evidence_weight` is then its own weight plus the
    `evidence_weight` of every theme whose `parent_theme_id` names it, the total
    again rounded half-up to two decimals."

    PRD 3.7: "Findings in `DRAFT`, `EVIDENCE_LOCKED` or `RETRACTED` contribute
    exactly 0.00."

    Design: Corner/calculations/theme_weight_rolls_up_from_child_to_parent
    """
    ctx = setup_study_in_analysis(
        api, participant_count=3, artifact_type="RECORDING", contains_pii=True
    )
    study_id = ctx["study"]["id"]
    artifact_ids = [artifact["id"] for artifact in ctx["artifacts"]]

    parent = create_theme(api, label="Onboarding")
    child = create_theme(api, label="Onboarding / invites", parent_theme_id=parent["id"])
    assert parent["depth"] == 1, f"Expected the root at depth 1, got {parent['depth']}"
    assert child["depth"] == 2, f"Expected the nested theme at depth 2, got {child['depth']}"

    findings = []
    for statement in (
        "Admins cannot tell which invite failed",
        "Admins resend invites blindly",
    ):
        finding = create_finding(
            study_id, child["id"], api, statement=statement, severity="HIGH"
        )
        for artifact_id in artifact_ids:
            link_evidence(finding["id"], artifact_id, api, weight_class="DIRECT_QUOTE")
        locked = lock_finding(finding["id"], api)
        assert float(locked["evidence_strength"]) == pytest.approx(0.60, abs=0.01), (
            f"Expected a corroborated strength of 0.60 from three direct quotes "
            f"across three participants, got {locked['evidence_strength']}"
        )
        findings.append(locked)

    while_locked_child = read_theme(child["id"], api)
    assert float(while_locked_child["own_evidence_weight"]) == pytest.approx(
        0.00, abs=0.01
    ), (
        f"Expected locked-but-unpublished findings to contribute 0.00, "
        f"got {while_locked_child['own_evidence_weight']}"
    )

    validate_success(api.publish_finding(findings[0]["id"], RESEARCH_LEAD_HEADERS), 200)

    child_after_one = read_theme(child["id"], api)
    parent_after_one = read_theme(parent["id"], api)
    assert float(child_after_one["own_evidence_weight"]) == pytest.approx(
        0.90, abs=0.01
    ), (
        f"Expected 0.60 strength times the HIGH multiplier 1.50, "
        f"got {child_after_one['own_evidence_weight']}"
    )
    assert float(child_after_one["evidence_weight"]) == pytest.approx(0.90, abs=0.01), (
        f"Expected a childless theme's rolled-up weight to equal its own weight, "
        f"got {child_after_one['evidence_weight']}"
    )
    assert float(parent_after_one["own_evidence_weight"]) == pytest.approx(
        0.00, abs=0.01
    ), (
        f"Expected the parent to hold no findings of its own, "
        f"got {parent_after_one['own_evidence_weight']}"
    )
    assert float(parent_after_one["evidence_weight"]) == pytest.approx(0.90, abs=0.01), (
        f"Expected the parent to absorb the child's 0.90, "
        f"got {parent_after_one['evidence_weight']}"
    )

    validate_success(api.publish_finding(findings[1]["id"], RESEARCH_LEAD_HEADERS), 200)

    child_after_two = read_theme(child["id"], api)
    parent_after_two = read_theme(parent["id"], api)
    assert float(child_after_two["own_evidence_weight"]) == pytest.approx(
        1.80, abs=0.01
    ), (
        f"Expected two 0.90 terms in the child's own sum, "
        f"got {child_after_two['own_evidence_weight']}"
    )
    assert float(child_after_two["evidence_weight"]) == pytest.approx(1.80, abs=0.01), (
        f"Expected the child's rolled-up weight to be 1.80, "
        f"got {child_after_two['evidence_weight']}"
    )
    assert float(parent_after_two["own_evidence_weight"]) == pytest.approx(
        0.00, abs=0.01
    ), (
        f"Expected the parent's own weight to stay 0.00, "
        f"got {parent_after_two['own_evidence_weight']}"
    )
    assert float(parent_after_two["evidence_weight"]) == pytest.approx(1.80, abs=0.01), (
        f"Expected the parent to absorb 1.80 from its single child, "
        f"got {parent_after_two['evidence_weight']}"
    )


def test_the_established_posture_follows_the_rolled_up_weight_on_both_levels(api):
    """Crossing 1.20 flips both the child and its parent to `ESTABLISHED` at once.

    PRD 3.7: "A theme whose `evidence_weight` is **at least 1.20** is
    `ESTABLISHED`; below that it is `EMERGING`, and the two transitions between
    those postures are pure consequences of the rollup, never a command."

    PRD 3.7: "Evaluation order is pinned: children are evaluated before parents in
    a post-order walk of the tree, and then the affected theme's ancestors are
    refreshed from that theme upward to the root one level at a time."

    Design: Corner/calculations/theme_weight_rolls_up_from_child_to_parent
    """
    ctx = setup_study_in_analysis(
        api, participant_count=3, artifact_type="RECORDING", contains_pii=True
    )
    study_id = ctx["study"]["id"]
    artifact_ids = [artifact["id"] for artifact in ctx["artifacts"]]

    parent = create_theme(api, label="Onboarding")
    child = create_theme(api, label="Onboarding / invites", parent_theme_id=parent["id"])

    locked_ids = []
    for statement in (
        "Admins cannot tell which invite failed",
        "Admins resend invites blindly",
    ):
        finding = create_finding(
            study_id, child["id"], api, statement=statement, severity="HIGH"
        )
        for artifact_id in artifact_ids:
            link_evidence(finding["id"], artifact_id, api, weight_class="DIRECT_QUOTE")
        lock_finding(finding["id"], api)
        locked_ids.append(finding["id"])

    validate_success(api.publish_finding(locked_ids[0], RESEARCH_LEAD_HEADERS), 200)
    assert read_theme(child["id"], api)["status"] == "EMERGING", (
        "Expected a rolled-up weight of 0.90 to stay below the 1.20 threshold"
    )
    assert read_theme(parent["id"], api)["status"] == "EMERGING", (
        "Expected the parent at 0.90 to stay EMERGING as well"
    )

    validate_success(api.publish_finding(locked_ids[1], RESEARCH_LEAD_HEADERS), 200)
    child_final = read_theme(child["id"], api)
    parent_final = read_theme(parent["id"], api)
    assert child_final["status"] == "ESTABLISHED", (
        f"Expected the child at 1.80 to be ESTABLISHED, got {child_final['status']}"
    )
    assert parent_final["status"] == "ESTABLISHED", (
        f"Expected the parent at 1.80 to be ESTABLISHED, got {parent_final['status']}"
    )
    assert child_final["reuse_count"] == 0, (
        f"Expected publishing to leave reuse_count alone, "
        f"got {child_final['reuse_count']}"
    )
    assert parent_final["reuse_count"] == 0, (
        f"Expected publishing to leave the parent's reuse_count alone, "
        f"got {parent_final['reuse_count']}"
    )


# ===========================================================================
# Labels and pool names are unique namespaces
# ===========================================================================
def test_a_repeated_theme_label_is_refused_at_any_depth(api):
    """A theme `label` is unique across the whole repository, not per parent.

    PRD 3.7: "A `Researcher` or `ResearchLead` creates one with a `label` that must
    be non-empty and unique across every theme in the repository — a collision is
    refused with `ERR_DUPLICATE_LABEL` — and optionally a `parent_theme_id` naming
    the theme it nests under."

    Design: Corner/validations/duplicate_theme_label_and_duplicate_pool_name_are_rejected
    """
    root = create_theme(api, label="Onboarding")

    flat_repeat = api.create_theme(
        create_theme_payload(label="Onboarding"), RESEARCHER_HEADERS
    )
    validate_error(flat_repeat, "ERR_DUPLICATE_LABEL")

    nested_repeat = api.create_theme(
        create_theme_payload(label="Onboarding", parent_theme_id=root["id"]),
        RESEARCHER_HEADERS,
    )
    validate_error(nested_repeat, "ERR_DUPLICATE_LABEL")

    distinct_nested = validate_success(
        api.create_theme(
            create_theme_payload(
                label="Onboarding / invites", parent_theme_id=root["id"]
            ),
            RESEARCHER_HEADERS,
        ),
        201,
    )
    assert distinct_nested["depth"] == 2, (
        f"Expected a distinct label to nest at depth 2, got {distinct_nested['depth']}"
    )

    rows, meta = validate_paginated(api.list_themes(RESEARCHER_HEADERS))
    assert meta["total_count"] == 2, (
        f"Expected only the two accepted themes to exist, "
        f"got total_count {meta['total_count']}"
    )
    assert {row["label"] for row in rows} == {"Onboarding", "Onboarding / invites"}, (
        "Expected exactly the two accepted labels in the repository"
    )


def test_a_repeated_pool_name_is_refused(api):
    """A pool `name` is unique across all pools and reuses the same error.

    PRD 3.2: "A `ResearchOpsAdmin` creates one with a `name` that must be non-empty
    and unique across all pools — a collision is refused with
    `ERR_DUPLICATE_LABEL` — a `pool_type` of `CUSTOMER_LIST`, `EXTERNAL_PANEL` or
    `INTERNAL_DOGFOOD`, a `contact_cap_per_window` of at least 1, a
    `contact_window_days` of at least 1, and an `incentive_budget_cents` of zero or
    more."

    Design: Corner/validations/duplicate_theme_label_and_duplicate_pool_name_are_rejected
    """
    first = validate_success(
        api.create_participant_pool(
            create_participant_pool_payload(name="Power user panel"),
            RESEARCH_OPS_ADMIN_HEADERS,
        ),
        201,
    )
    assert first["name"] == "Power user panel", (
        f"Expected the pool to store the supplied name, got {first['name']!r}"
    )

    repeat = api.create_participant_pool(
        create_participant_pool_payload(
            name="Power user panel", pool_type="EXTERNAL_PANEL"
        ),
        RESEARCH_OPS_ADMIN_HEADERS,
    )
    validate_error(repeat, "ERR_DUPLICATE_LABEL")

    accepted = validate_success(
        api.create_participant_pool(
            create_participant_pool_payload(name="Power user panel EU"),
            RESEARCH_OPS_ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["name"] == "Power user panel EU", (
        f"Expected a distinct name to be accepted, got {accepted['name']!r}"
    )


# ===========================================================================
# The publish gate on evidence strength
# ===========================================================================
def test_publishing_a_finding_below_the_strength_floor_is_refused(api):
    """Three self-reported excerpts score 0.30, which misses the 0.45 publish floor.

    PRD 3.7: "The finding's `evidence_strength` must be **at least 0.45**, else
    `ERR_EVIDENCE_TOO_WEAK`."

    PRD 3.7: "Once the finding is `EVIDENCE_LOCKED`, `PUBLISHED` or `RETRACTED` the
    **corroborated** variant applies, and it is computed in three steps: divide the
    raw total by the tighter 3.00, hold it at a ceiling of 1.00 and round to
    **four** decimal places to obtain a density; divide `distinct_participant_count`
    by 5, hold that at a ceiling of 1.00 and round half-up to two decimals to
    obtain a corroboration factor; then multiply density by corroboration factor
    and round half-up to two decimals."

    Design: Corner/validations/publishing_a_weak_finding_is_rejected
    """
    ctx = setup_locked_finding(
        api, weight_classes=("SELF_REPORT", "SELF_REPORT", "SELF_REPORT")
    )
    finding = ctx["finding"]
    assert float(finding["evidence_strength"]) == pytest.approx(0.30, abs=0.01), (
        f"Expected a raw total of 1.50 to give 0.5000 density times 0.60 "
        f"corroboration, got {finding['evidence_strength']}"
    )

    refused = api.publish_finding(finding["id"], RESEARCH_LEAD_HEADERS)
    validate_error(refused, "ERR_EVIDENCE_TOO_WEAK")


def test_a_refused_publication_leaves_the_finding_and_its_theme_untouched(api):
    """The rejected publish stores nothing: no `published_at`, no theme weight.

    PRD 3.7: "On success `published_at` is set to the current logical clock instant
    and the theme weights are recomputed for the finding's theme and every ancestor
    of it."

    PRD 3.7: "Findings in `DRAFT`, `EVIDENCE_LOCKED` or `RETRACTED` contribute
    exactly 0.00."

    Design: Corner/validations/publishing_a_weak_finding_is_rejected
    """
    ctx = setup_locked_finding(
        api, weight_classes=("SELF_REPORT", "SELF_REPORT", "SELF_REPORT")
    )
    before = ctx["finding"]

    validate_error(
        api.publish_finding(before["id"], RESEARCH_LEAD_HEADERS),
        "ERR_EVIDENCE_TOO_WEAK",
    )

    after = read_finding(before["id"], api)
    assert after["status"] == "EVIDENCE_LOCKED", (
        f"Expected the finding to stay EVIDENCE_LOCKED, got {after['status']}"
    )
    assert after["strength_variant"] == "CORROBORATED", (
        f"Expected the corroborated variant to remain in force, "
        f"got {after['strength_variant']}"
    )
    assert float(after["evidence_strength"]) == pytest.approx(0.30, abs=0.01), (
        f"Expected the strength to stay 0.30, got {after['evidence_strength']}"
    )
    assert after["admissible_link_count"] == 3, (
        f"Expected all three links to remain admissible, "
        f"got {after['admissible_link_count']}"
    )
    assert after["distinct_participant_count"] == 3, (
        f"Expected three distinct participants to remain, "
        f"got {after['distinct_participant_count']}"
    )
    assert after["published_at"] is None, (
        f"Expected published_at to stay null after a refused publication, "
        f"got {after['published_at']!r}"
    )
    assert after["version"] == before["version"], (
        f"Expected the refused publication to leave version at "
        f"{before['version']}, got {after['version']}"
    )

    theme = read_theme(ctx["theme"]["id"], api)
    assert float(theme["own_evidence_weight"]) == pytest.approx(0.00, abs=0.01), (
        f"Expected the theme to carry no weight from an unpublished finding, "
        f"got {theme['own_evidence_weight']}"
    )
    assert float(theme["evidence_weight"]) == pytest.approx(0.00, abs=0.01), (
        f"Expected the theme's rolled-up weight to stay 0.00, "
        f"got {theme['evidence_weight']}"
    )
    assert theme["status"] == "EMERGING", (
        f"Expected the theme to stay EMERGING, got {theme['status']}"
    )


# ===========================================================================
# The theme index: create, read, page and filter
# ===========================================================================
def _three_themes_at_distinct_instants(api):
    """Create three themes an hour apart so `created_at` is a strict tiebreak."""
    set_clock("2026-08-01T00:00:00Z", api)
    first = create_theme(api, label="Navigation friction")
    set_clock("2026-08-01T01:00:00Z", api)
    second = create_theme(
        api, label="Navigation friction / search", parent_theme_id=first["id"]
    )
    set_clock("2026-08-01T02:00:00Z", api)
    third = create_theme(api, label="Checkout drop-off")
    return first, second, third


def test_a_created_theme_reads_back_with_its_rolled_up_weight_and_reuse_count(api):
    """The read echoes exactly what creation stored, including the empty rollup.

    PRD 3.7: "A theme read returns its rolled-up weight and reuse count."

    PRD 3.7: "A new theme opens `EMERGING` with `own_evidence_weight` and
    `evidence_weight` both 0.00 and `reuse_count` at 0."

    PRD 2.4: "`version` is an integer that starts at 1 when the resource is created
    and increments by exactly 1 on every mutation."

    Design: Corner/endpoints/theme_create_read_and_list_round_trip
    """
    parent = create_theme(api, label="Navigation friction")
    created = validate_success(
        api.create_theme(
            create_theme_payload(
                label="Navigation friction / search", parent_theme_id=parent["id"]
            ),
            RESEARCHER_HEADERS,
        ),
        201,
    )

    read_back = validate_success(api.get_theme(created["id"], RESEARCHER_HEADERS), 200)
    assert_theme(read_back)
    assert read_back["id"] == created["id"], (
        "Expected the read to return the very row that creation answered with"
    )
    assert read_back["label"] == "Navigation friction / search", (
        f"Expected the stored label to survive the round trip, "
        f"got {read_back['label']!r}"
    )
    assert read_back["parent_theme_id"] == parent["id"], (
        "Expected the read to echo the parent named at creation"
    )
    assert read_back["depth"] == 2, (
        f"Expected a nested theme at depth 2, got {read_back['depth']}"
    )
    assert read_back["status"] == "EMERGING", (
        f"Expected a fresh theme to read as EMERGING, got {read_back['status']}"
    )
    assert float(read_back["own_evidence_weight"]) == pytest.approx(0.00, abs=0.01), (
        f"Expected own_evidence_weight 0.00, got {read_back['own_evidence_weight']}"
    )
    assert float(read_back["evidence_weight"]) == pytest.approx(0.00, abs=0.01), (
        f"Expected evidence_weight 0.00, got {read_back['evidence_weight']}"
    )
    assert read_back["reuse_count"] == 0, (
        f"Expected reuse_count 0, got {read_back['reuse_count']}"
    )
    assert read_back["version"] == 1, (
        f"Expected a freshly created theme at version 1, got {read_back['version']}"
    )


def test_the_theme_index_pages_in_weight_then_created_at_order(api):
    """Three equally weighted themes page out oldest-first across two windows.

    PRD 2.3: "the repository theme index is ordered by `evidence_weight`
    descending, then `created_at` ascending"

    PRD 2.3: "List responses carry `response_type` of `"array"` and populate four
    pagination fields in `meta`: `limit` (the effective page size actually applied),
    `offset` (the effective starting index), `total_count` (the number of rows
    matching the filters before the page window is applied) and `has_more` (true
    when rows remain beyond the current window)."

    Design: Corner/endpoints/theme_create_read_and_list_round_trip
    """
    first, second, third = _three_themes_at_distinct_instants(api)

    page_one = api.list_themes(RESEARCHER_HEADERS, {"limit": 2, "offset": 0})
    rows_one, meta_one = validate_paginated(page_one)
    assert meta_one["limit"] == 2, f"Expected the applied limit 2, got {meta_one['limit']}"
    assert meta_one["offset"] == 0, (
        f"Expected the applied offset 0, got {meta_one['offset']}"
    )
    assert meta_one["total_count"] == 3, (
        f"Expected all three themes counted before the window, "
        f"got {meta_one['total_count']}"
    )
    assert meta_one["has_more"] is True, (
        "Expected has_more true while a third row waits beyond the window"
    )
    assert [row["id"] for row in rows_one] == [first["id"], second["id"]], (
        "Expected the two oldest themes first when every weight ties at 0.00"
    )
    assert_ordered_desc_then_created_at(rows_one, "evidence_weight")

    page_two = api.list_themes(RESEARCHER_HEADERS, {"limit": 2, "offset": 2})
    rows_two, meta_two = validate_paginated(page_two)
    assert meta_two["offset"] == 2, (
        f"Expected the applied offset 2, got {meta_two['offset']}"
    )
    assert meta_two["total_count"] == 3, (
        f"Expected the same unwindowed count of 3, got {meta_two['total_count']}"
    )
    assert meta_two["has_more"] is False, (
        "Expected has_more false on the final window"
    )
    assert [row["id"] for row in rows_two] == [third["id"]], (
        "Expected the newest theme alone on the second page"
    )


def test_theme_index_filters_narrow_additively(api):
    """`parent_theme_id`, `label_contains` and `status` each cut the result set.

    PRD 3.7: "The theme index lists themes ordered by `evidence_weight` descending
    then `created_at` ascending, with optional `parent_theme_id`, `status` and
    `label_contains` filters, the last matching themes whose `label` contains the
    supplied substring."

    PRD 2.3: "Filters on list endpoints are additive: supplying several narrows the
    result set, and pagination is applied after filtering."

    Design: Corner/endpoints/theme_create_read_and_list_round_trip
    """
    first, second, third = _three_themes_at_distinct_instants(api)

    children = api.list_themes(RESEARCHER_HEADERS, {"parent_theme_id": first["id"]})
    child_rows, child_meta = validate_paginated(children)
    assert child_meta["total_count"] == 1, (
        f"Expected exactly one child of the root theme, "
        f"got {child_meta['total_count']}"
    )
    assert child_rows[0]["id"] == second["id"], (
        "Expected the parent filter to return the nested theme"
    )

    by_substring = api.list_themes(RESEARCHER_HEADERS, {"label_contains": "Navigation"})
    substring_rows, substring_meta = validate_paginated(by_substring)
    assert substring_meta["total_count"] == 2, (
        f"Expected the two Navigation themes, got {substring_meta['total_count']}"
    )
    assert {row["id"] for row in substring_rows} == {first["id"], second["id"]}, (
        "Expected the substring filter to skip the checkout theme"
    )

    combined = api.list_themes(
        RESEARCHER_HEADERS, {"label_contains": "Navigation", "status": "EMERGING"}
    )
    combined_rows, combined_meta = validate_paginated(combined)
    assert combined_meta["total_count"] == 2, (
        f"Expected the additive filters to still match the two Navigation themes, "
        f"got {combined_meta['total_count']}"
    )
    assert [row["id"] for row in combined_rows] == [first["id"], second["id"]], (
        "Expected the additive filters to preserve the contractual ordering"
    )

    unmatched = api.list_themes(
        RESEARCHER_HEADERS, {"label_contains": "Checkout", "status": "ESTABLISHED"}
    )
    unmatched_rows, unmatched_meta = validate_paginated(unmatched)
    assert unmatched_meta["total_count"] == 0, (
        f"Expected no weightless theme to be ESTABLISHED, "
        f"got {unmatched_meta['total_count']}"
    )
    assert unmatched_rows == [], (
        f"Expected an empty page, got {len(unmatched_rows)} rows"
    )
    assert third["status"] == "EMERGING", (
        f"Expected the checkout theme itself to be EMERGING, got {third['status']}"
    )
