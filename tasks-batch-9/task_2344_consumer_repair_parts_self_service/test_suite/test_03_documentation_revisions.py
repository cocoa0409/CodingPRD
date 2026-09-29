"""Documentation under revision control: the rejection cycle, the publication
cascade into compliance, and the parent-model support gate on approval.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    DOCS,
    SAFETY,
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_error,
)


def _read_revision(revision_id):
    return get_success_data(api_client.get_manual_revision(revision_id, ADMIN))


def _read_obligation(obligation_id):
    return get_success_data(api_client.get_compliance_obligation(obligation_id, ADMIN))


# --------------------------------------------------------------------------- #
# A guide that is rejected twice before it is approved
# --------------------------------------------------------------------------- #
def _draft_guide_awaiting_review():
    """A model with one published part and a draft guide covering that part."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-5000",
        product_family="CRX",
        market_release_date="2025-02-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-BEZEL", list_price_cents=2500)
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2025-03-01T00:00:00Z", install_minutes=25
    )
    fixtures.publish_part(part["id"])
    revision = fixtures.create_draft_revision(
        model["id"],
        DOCS,
        doc_type="DISASSEMBLY_GUIDE",
        covered_part_skus=["SKU-BEZEL"],
        safety_warning_count=3,
    )
    return {"model": model, "part": part, "revision": revision}


def test_rejection_loop_returns_the_guide_to_draft_and_counts_the_cycle():
    """PRD §3.4: "The revision-control cycle is `DRAFT` to `IN_REVIEW`, then either
    `IN_REVIEW` back to `DRAFT` on rejection or `IN_REVIEW` to `APPROVED`, then
    `APPROVED` to `PUBLISHED`, and finally `PUBLISHED` to the terminal
    `SUPERSEDED`."
    PRD §3.4: "A rejection returns the revision from `IN_REVIEW` to `DRAFT`,
    increments `rejection_cycle_count` by one, and stores both
    `reviewed_by_user_id` and the note; it too requires `rejection_cycle_count` to
    be below three beforehand, otherwise `ERR_REVISION_CYCLE_CAP_REACHED`."

    Design: Difficulty/non_linear_state_machine/manual_revision_review_cycle_loops_twice_then_publishes
    """
    bundle = _draft_guide_awaiting_review()
    revision_id = bundle["revision"]["id"]

    fixtures.submit_revision(revision_id, DOCS)
    first = fixtures.review_revision(
        revision_id, "REJECT", SAFETY, review_note="step 4 photo missing"
    )
    assert first["status"] == "DRAFT", (
        f"the first rejection must return the revision to DRAFT, got {first['status']}"
    )
    assert first["rejection_cycle_count"] == 1, first["rejection_cycle_count"]

    fixtures.submit_revision(revision_id, DOCS)
    second = fixtures.review_revision(
        revision_id, "REJECT", SAFETY, review_note="torque values still wrong"
    )
    assert second["status"] == "DRAFT", (
        f"the second rejection must return the revision to DRAFT, got {second['status']}"
    )
    assert second["rejection_cycle_count"] == 2, (
        f"Expected two traversals of the rejection loop, got "
        f"{second['rejection_cycle_count']}"
    )
    assert second["revision_number"] == 1, (
        "the cycle runs on one row, so the revision number never advances, got "
        f"{second['revision_number']}"
    )


def test_third_review_approves_and_publication_makes_the_guide_current():
    """PRD §3.4: "An approval moves `IN_REVIEW` to `APPROVED` and stores
    `reviewed_by_user_id`, and carries three guards of its own: the caller's
    `X-User-ID` must differ from `authored_by_user_id`, or the decision is refused
    with `ERR_SELF_REVIEW_FORBIDDEN`; the parent model's `support_state` must not be
    `SUPPORT_ENDED`, or the approval is refused with
    `ERR_INVALID_STATE_TRANSITION`; and for a `DISASSEMBLY_GUIDE` the
    `coverage_gap_sku_count` must be exactly zero, or the approval is refused with
    `ERR_REVISION_COVERAGE_GAP`, because a guide that omits a published, in-window
    part of the model is not a complete guide."
    PRD §3.4: "The same pass refreshes `published_disassembly_revision_number` from
    that guide's `revision_number`, and `published_safety_sheet_revision_number`
    from the revision number of the model's published `SAFETY_SHEET`, using null
    where no such revision exists."

    Design: Difficulty/non_linear_state_machine/manual_revision_review_cycle_loops_twice_then_publishes
    """
    bundle = _draft_guide_awaiting_review()
    revision_id = bundle["revision"]["id"]

    for note in ("step 4 photo missing", "torque values still wrong"):
        fixtures.submit_revision(revision_id, DOCS)
        fixtures.review_revision(revision_id, "REJECT", SAFETY, review_note=note)

    fixtures.submit_revision(revision_id, DOCS)
    fixtures.review_revision(revision_id, "APPROVE", SAFETY, review_note="third pass accepted")
    revision = fixtures.publish_revision(revision_id, SAFETY)

    assert revision["status"] == "PUBLISHED", revision["status"]
    assert revision["rejection_cycle_count"] == 2, (
        f"publication does not reset the cycle counter, got "
        f"{revision['rejection_cycle_count']}"
    )
    assert revision["revision_number"] == 1, revision["revision_number"]
    assert revision["coverage_gap_sku_count"] == 0, (
        f"the guide covers the only published in-window part, got "
        f"{revision['coverage_gap_sku_count']}"
    )
    assert revision["reviewed_by_user_id"] == "user_safety_001", (
        f"Expected the reviewer identity to be stored, got "
        f"{revision['reviewed_by_user_id']}"
    )

    model = fixtures.read_model(bundle["model"]["id"])
    assert model["published_disassembly_revision_number"] == 1, (
        f"Expected revision 1 to become the model's current guide, got "
        f"{model['published_disassembly_revision_number']}"
    )
    assert model["documentation_posture"] == "CURRENT", model["documentation_posture"]


# --------------------------------------------------------------------------- #
# A replacement guide published over a stale one
# --------------------------------------------------------------------------- #
def _stale_model_with_approved_replacement_guide():
    """A model whose published guide misses a newly published part, plus the fix.

    Publishing SKU-CELL-2 after revision 1 went out leaves a coverage gap, which
    drags the model's documentation posture to STALE and its obligation to AT_RISK.
    Revision 2 covers both SKUs and is approved but not yet published.
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-8000",
        product_family="CRX",
        market_release_date="2025-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part_1 = fixtures.create_part(sku="SKU-CELL-1", list_price_cents=4000)
    fixtures.create_compatibility(
        part_1["id"], model["id"], effective_from="2025-02-01T00:00:00Z", install_minutes=30
    )
    fixtures.publish_part(part_1["id"])
    revision_1 = fixtures.publish_disassembly_guide(
        model["id"], ["SKU-CELL-1"], safety_warning_count=2
    )
    obligation = fixtures.create_obligation(model["id"], "US-CA", COMPLIANCE)

    part_2 = fixtures.create_part(sku="SKU-CELL-2", list_price_cents=4200)
    fixtures.create_compatibility(
        part_2["id"], model["id"], effective_from="2025-02-01T00:00:00Z", install_minutes=30
    )
    fixtures.publish_part(part_2["id"])

    revision_2 = fixtures.create_draft_revision(
        model["id"],
        DOCS,
        doc_type="DISASSEMBLY_GUIDE",
        covered_part_skus=["SKU-CELL-1", "SKU-CELL-2"],
        safety_warning_count=4,
    )
    fixtures.submit_revision(revision_2["id"], DOCS)
    fixtures.review_revision(
        revision_2["id"], "APPROVE", SAFETY, review_note="R2 closes the coverage gap"
    )
    return {
        "model": model,
        "obligation": obligation,
        "revision_1": revision_1,
        "revision_2": revision_2,
    }


def test_publishing_a_replacement_guide_supersedes_the_previous_revision():
    """PRD §3.4: "The first hop sets the revision's `status` to `PUBLISHED` and
    stamps `published_at` and `effective_from`."
    PRD §3.4: "The second hop, caused by the first, moves the previously published
    revision of the same model and document type — if there was one — to the
    terminal `SUPERSEDED`; that row is then frozen, and orders that pinned it keep
    their pinned revision number unchanged."

    Design: Difficulty/transitive_cascade/guide_publication_cascades_through_supersession_posture_and_obligation_recovery
    """
    bundle = _stale_model_with_approved_replacement_guide()
    revision_2 = fixtures.publish_revision(bundle["revision_2"]["id"], SAFETY)

    assert revision_2["status"] == "PUBLISHED", revision_2["status"]
    assert revision_2["revision_number"] == 2, (
        f"Expected the second guide for this model and doc type, got "
        f"{revision_2['revision_number']}"
    )
    assert revision_2["published_at"] is not None, "publication stamps published_at"
    assert revision_2["effective_from"] is not None, "publication stamps effective_from"

    revision_1 = _read_revision(bundle["revision_1"]["id"])
    assert revision_1["status"] == "SUPERSEDED", (
        f"the previously published guide must be superseded, got {revision_1['status']}"
    )


def test_publishing_a_replacement_guide_restores_the_documentation_posture():
    """PRD §3.4: "The gap is the required SKUs that do not appear in the published
    guide's `covered_part_skus`, and the size of that gap is written to the guide's
    `coverage_gap_sku_count`. When the gap is non-empty the posture is `STALE`."
    PRD §3.4: "The third hop, caused by the change of which revision is current,
    refreshes the parent model's `published_disassembly_revision_number` and
    `published_safety_sheet_revision_number` and re-derives its
    `documentation_posture`."

    Design: Difficulty/transitive_cascade/guide_publication_cascades_through_supersession_posture_and_obligation_recovery
    """
    bundle = _stale_model_with_approved_replacement_guide()

    before = fixtures.read_model(bundle["model"]["id"])
    assert before["documentation_posture"] == "STALE", (
        "publishing a second part leaves the current guide with a gap, got "
        f"{before['documentation_posture']}"
    )
    assert before["published_disassembly_revision_number"] == 1, (
        before["published_disassembly_revision_number"]
    )

    revision_2 = fixtures.publish_revision(bundle["revision_2"]["id"], SAFETY)
    assert revision_2["coverage_gap_sku_count"] == 0, (
        f"the replacement guide covers both published parts, got "
        f"{revision_2['coverage_gap_sku_count']}"
    )

    after = fixtures.read_model(bundle["model"]["id"])
    assert after["published_disassembly_revision_number"] == 2, (
        f"Expected the model to point at revision 2, got "
        f"{after['published_disassembly_revision_number']}"
    )
    assert after["documentation_posture"] == "CURRENT", (
        f"an empty gap restores the posture to CURRENT, got "
        f"{after['documentation_posture']}"
    )


def test_publishing_a_replacement_guide_recovers_the_obligation_and_the_posture():
    """PRD §3.4: "The fourth hop, caused by the third, re-evaluates every compliance
    obligation of that model and then recomputes the model's `compliance_posture`
    from the new obligation statuses."
    PRD §3.2: "Fourth: when `deadline_basis` is `END_OF_PRODUCTION` and the logical
    clock has reached or passed the point ninety days before `parts_available_until`,
    or when the model's `documentation_posture` is `STALE`, the status is `AT_RISK`."
    PRD §3.2: "Alongside the posture, `open_obligation_count` is set to the number
    of the model's obligations whose status is `OPEN`, `AT_RISK`, or `ATTESTED`."

    Design: Difficulty/transitive_cascade/guide_publication_cascades_through_supersession_posture_and_obligation_recovery
    """
    bundle = _stale_model_with_approved_replacement_guide()

    obligation_before = _read_obligation(bundle["obligation"]["id"])
    assert obligation_before["status"] == "AT_RISK", (
        f"a STALE documentation posture puts the obligation AT_RISK, got "
        f"{obligation_before['status']}"
    )
    model_before = fixtures.read_model(bundle["model"]["id"])
    assert model_before["compliance_posture"] == "WATCH", (
        f"an AT_RISK obligation raises the model to WATCH, got "
        f"{model_before['compliance_posture']}"
    )

    fixtures.publish_revision(bundle["revision_2"]["id"], SAFETY)

    obligation = _read_obligation(bundle["obligation"]["id"])
    assert obligation["status"] == "OPEN", (
        f"the recovered posture drops the obligation back to OPEN, got "
        f"{obligation['status']}"
    )
    assert obligation["breach_count"] == 0, (
        "no evaluation ever landed on a breached value, got "
        f"{obligation['breach_count']}"
    )

    model = fixtures.read_model(bundle["model"]["id"])
    assert model["compliance_posture"] == "OPEN", (
        f"with no AT_RISK sibling the model returns to OPEN, got "
        f"{model['compliance_posture']}"
    )
    assert model["open_obligation_count"] == 1, (
        f"the single OPEN obligation is counted, got {model['open_obligation_count']}"
    )


# --------------------------------------------------------------------------- #
# A guide left in review while its model was retired
# --------------------------------------------------------------------------- #
def _revision_in_review_on_a_retired_model():
    """An IN_REVIEW guide whose model has been walked all the way to SUPPORT_ENDED."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-9400",
        product_family="CRX",
        market_release_date="2020-01-01T00:00:00Z",
        repairability_tier="TIER_B_GUIDED",
    )
    revision = fixtures.create_draft_revision(
        model["id"],
        DOCS,
        doc_type="DISASSEMBLY_GUIDE",
        covered_part_skus=["SKU-LATER-1"],
        safety_warning_count=2,
    )
    fixtures.submit_revision(revision["id"], DOCS)
    fixtures.end_production(model["id"], "2024-06-01T00:00:00Z")
    fixtures.end_support(model["id"], "2026-07-01T00:00:00Z")
    return {"model": model, "revision": revision}


def test_approval_is_refused_once_the_parent_model_support_has_ended():
    """PRD §3.1: "Ending support stores `support_end_date`, closes every obligation
    still in `OPEN`, `AT_RISK`, or `ATTESTED` whose mandated parts deadline already
    lies in the past, expires every eligibility assessment of the model that was
    still `VALID`, and blocks any further manual-revision approval for that model
    from then on."
    PRD §3.4: "An approval moves `IN_REVIEW` to `APPROVED` and stores
    `reviewed_by_user_id`, and carries three guards of its own: the caller's
    `X-User-ID` must differ from `authored_by_user_id`, or the decision is refused
    with `ERR_SELF_REVIEW_FORBIDDEN`; the parent model's `support_state` must not be
    `SUPPORT_ENDED`, or the approval is refused with
    `ERR_INVALID_STATE_TRANSITION`; and for a `DISASSEMBLY_GUIDE` the
    `coverage_gap_sku_count` must be exactly zero, or the approval is refused with
    `ERR_REVISION_COVERAGE_GAP`, because a guide that omits a published, in-window
    part of the model is not a complete guide."

    Design: Difficulty/cross_entity_state_dependency/guide_approval_blocked_once_parent_model_support_has_ended
    """
    bundle = _revision_in_review_on_a_retired_model()

    model = fixtures.read_model(bundle["model"]["id"])
    assert model["support_state"] == "SUPPORT_ENDED", (
        f"Expected the model to be retired before the trigger, got "
        f"{model['support_state']}"
    )

    response = api_client.review_manual_revision(
        bundle["revision"]["id"],
        factories.review_decision_payload(
            "APPROVE", review_note="content is fine but the model is retired"
        ),
        SAFETY,
    )
    validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)


def test_refused_approval_leaves_the_guide_in_review_with_no_reviewer():
    """PRD §3.4: "Submitting a revision for review advances `DRAFT` to `IN_REVIEW`."
    PRD §3.4: "Submission recomputes `coverage_gap_sku_count` against the model's
    parts that are `PUBLISHED` and hold an in-window compatibility row."

    Design: Difficulty/cross_entity_state_dependency/guide_approval_blocked_once_parent_model_support_has_ended
    """
    bundle = _revision_in_review_on_a_retired_model()

    api_client.review_manual_revision(
        bundle["revision"]["id"],
        factories.review_decision_payload(
            "APPROVE", review_note="content is fine but the model is retired"
        ),
        SAFETY,
    )

    revision = _read_revision(bundle["revision"]["id"])
    assert revision["status"] == "IN_REVIEW", (
        f"the refused decision must not move the revision, got {revision['status']}"
    )
    assert revision["reviewed_by_user_id"] is None, (
        f"a refused approval stores no reviewer, got {revision['reviewed_by_user_id']}"
    )
    assert revision["coverage_gap_sku_count"] == 0, (
        "no part is published for this model, so the refusal is not a coverage gap; "
        f"got {revision['coverage_gap_sku_count']}"
    )
