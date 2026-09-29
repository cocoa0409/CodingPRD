"""Server-owned record fields: draft defaults, derived concept scores, append-only
ballots and the prerequisite graph."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_concept_test,
    assert_deliverable,
    assert_formulation,
    assert_gate_vote,
    assert_label_approval,
    assert_project,
    cast_vote,
    create_formulation,
    deliverable_payload,
    intake_project,
    is_iso8601_timestamp,
    label_approval_payload,
    make_functional_reviewer_headers,
    make_gate_chair_headers,
    make_innovation_lead_headers,
    open_gate_review,
    read_formulation,
    register_stage_gate,
    schedule_gate_review,
    screen_project,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SNACK_IDEA = {
    "name": "Toffee Crunch Bites",
    "brand": "GrainWell",
    "category": "SNACK",
    "project_type": "LINE_EXTENSION",
    "strategic_fit_score": 8,
    "consumer_need_score": 7,
    "target_gross_margin_pct": 36,
    "category_attractiveness_score": 7,
    "development_budget_cap_usd": 500000.00,
}

CONCEPT_STUDIES = [
    {"test_type": "MONADIC", "sample_size": 400, "purchase_intent_top2_pct": 62.00,
     "uniqueness_pct": 48.00, "fielded_at": "2026-07-05T00:00:00Z", "expected": 56.40},
    {"test_type": "SEQUENTIAL_MONADIC", "sample_size": 250, "purchase_intent_top2_pct": 42.00,
     "uniqueness_pct": 35.00, "fielded_at": "2026-07-12T00:00:00Z", "expected": 37.24},
    {"test_type": "IN_HOME_USE", "sample_size": 90, "purchase_intent_top2_pct": 70.00,
     "uniqueness_pct": 55.00, "fielded_at": "2026-07-19T00:00:00Z", "expected": 54.40},
]


def _snack_project_with_draft_formulation():
    """A snack idea and its first formulation revision, both untouched."""
    set_clock("2026-08-01T00:00:00Z")
    project = intake_project(owner_user_id="lead-d1", **dict(SNACK_IDEA))
    formulation = create_formulation(
        project["id"], spec_summary="Toffee inclusion at 12 percent",
        allergen_regime="NONE", target_shelf_life_days=180, unit_cost_usd=3.2000,
    )
    return project, formulation


def _three_concept_studies(api):
    """One snack idea carrying three studies fielded a week apart."""
    set_clock("2026-08-01T00:00:00Z")
    project = intake_project(owner_user_id="lead-k1", **dict(SNACK_IDEA))
    created = []
    for study in CONCEPT_STUDIES:
        payload = {key: value for key, value in study.items() if key != "expected"}
        created.append(
            validate_success(
                api.create_concept_test(
                    project["id"], payload, make_innovation_lead_headers("lead-k1")
                ),
                201,
            )
        )
    return project, created


def _prerequisite_chain(api):
    """Three hand-added checklist items on one snack idea, the third already linked."""
    set_clock("2026-08-01T00:00:00Z")
    gate2 = register_stage_gate(
        gate_number=2, category="SNACK", stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=[],
    )
    project = intake_project(owner_user_id="lead-g1", **dict(SNACK_IDEA))
    lead = make_innovation_lead_headers("lead-g1")
    first = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate2["id"], deliverable_type="MANUFACTURING_READINESS",
                                owner_function="OPERATIONS"),
            lead,
        ),
        201,
    )
    second = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate2["id"], deliverable_type="DISTRIBUTION_READINESS",
                                owner_function="OPERATIONS"),
            lead,
        ),
        201,
    )
    third = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate2["id"], deliverable_type="SALES_SELL_IN_PLAN",
                                owner_function="SALES",
                                prerequisite_deliverable_id=second["id"]),
            lead,
        ),
        201,
    )
    return project, gate2, first, second, third


def test_a_fresh_label_draft_carries_an_empty_unsupported_claim_list(api):
    """Drafting pack artwork answers 201 with `unsupported_claims` as an empty array, no
    decider, and the formulation still at its first draft revision.

    PRD: "A new draft starts in `DRAFT` with an empty `unsupported_claims` array and
    `decided_by_user_id` null."
    PRD: "`revision` is assigned by the server as a 1-based ordinal within the project, so
    the first revision is 1. A new revision starts in `DRAFT` with `best_pilot_yield_pct`
    `0.00`."

    Design: Corner/entities/entity_label_approval_defaults_unsupported_claims_to_empty_array
    """
    project, formulation = _snack_project_with_draft_formulation()

    label = validate_success(
        api.create_label_approval(
            project["id"],
            label_approval_payload(formulation["id"], label_version="v1",
                                   claims=["No artificial colors"]),
            make_innovation_lead_headers("lead-d1"),
        ),
        201,
    )

    assert_label_approval(label)
    assert label["status"] == "DRAFT"
    assert label["unsupported_claims"] == [], (
        f"an undecided draft flags nothing, got {label['unsupported_claims']!r}"
    )
    assert label["decided_by_user_id"] is None
    assert label["formulation_id"] == formulation["id"]
    assert label["version"] == 1

    stored_formulation = read_formulation(formulation["id"])
    assert_formulation(stored_formulation)
    assert stored_formulation["revision"] == 1
    assert stored_formulation["status"] == "DRAFT"
    assert stored_formulation["best_pilot_yield_pct"] == pytest.approx(0.00, abs=0.01)


def test_each_concept_study_scores_through_its_own_confidence_band(api):
    """Three studies keep three distinct scores because the respondent count picks the
    multiplier the client never sends.

    PRD: "Purchase intent is weighted 0.60 and uniqueness 0.40; their weighted sum is then
    multiplied by a confidence multiplier chosen from the respondent count — `1.00` when
    `sample_size` is at least 300, `0.95` when `sample_size` is at least 100 but below 300,
    and `0.85` when `sample_size` is below 100 — and the product is rounded half up to two
    decimal places to give `concept_score`."

    Design: Corner/entities/entity_concept_test_computed_score_and_authoritative_flag
    """
    project, created = _three_concept_studies(api)

    for study, row in zip(CONCEPT_STUDIES, created):
        assert_concept_test(row)
        assert row["concept_score"] == pytest.approx(study["expected"], abs=0.01), (
            f"sample_size {study['sample_size']} must score {study['expected']}, "
            f"got {row['concept_score']}"
        )

    scores = [row["concept_score"] for row in created]
    assert len(set(scores)) == 3, "three different input sets keep three different scores"
    assert scores[2] < scores[0], (
        "the highest raw score sits on the lowest confidence band, so the band is not cosmetic"
    )
    _, meta = validate_paginated(
        api.list_concept_tests(project["id"], make_innovation_lead_headers("lead-k1"))
    )
    assert meta["total_count"] == 3, "all three studies are stored, not just the winner"


def test_only_the_latest_fielded_study_stays_authoritative(api):
    """Recording a newer study clears the flag on the two it displaces.

    PRD: "The `is_authoritative` flag is true for exactly one row per project: the study
    with the greatest `fielded_at`, and where several share that instant, the earliest
    created among them."
    PRD: "Recording a newer study therefore clears `is_authoritative` on the studies it
    displaces."

    Design: Corner/entities/entity_concept_test_computed_score_and_authoritative_flag
    """
    project, created = _three_concept_studies(api)

    rows, meta = validate_paginated(
        api.list_concept_tests(project["id"], make_innovation_lead_headers("lead-k1"))
    )

    assert meta["total_count"] == 3
    by_id = {row["id"]: row for row in rows}
    latest = by_id[created[2]["id"]]
    assert latest["is_authoritative"] is True, "the greatest fielded_at holds the flag"
    assert by_id[created[0]["id"]]["is_authoritative"] is False
    assert by_id[created[1]["id"]]["is_authoritative"] is False
    assert sum(1 for row in rows if row["is_authoritative"]) == 1, (
        "exactly one row per project is authoritative"
    )
    assert latest["concept_score"] == pytest.approx(54.40, abs=0.01), (
        "the authoritative row is the newest, not the best scoring one"
    )


def test_screening_bumps_the_version_without_disturbing_the_owner(api):
    """A chair's screen call is an accepted write: `version` goes to 2 while
    `owner_user_id` and `created_at` stay as the creating lead left them.

    PRD: "Alongside `id`, every entity in this system also carries `created_at`,
    `updated_at` and `version`: `created_at` and `updated_at` are ISO 8601 UTC timestamps
    with three fractional digits, and `version` is an integer that starts at 1 on insert and
    increments by one on every accepted write to that row."
    PRD: "The acting user's opaque identifier is captured as `owner_user_id`, which is what
    later bars that same person from voting at the project's gates."

    Design: Corner/entities/entity_project_system_fields_refresh_on_mutation
    """
    set_clock("2026-08-01T00:00:00Z")
    register_stage_gate(
        gate_number=2, category="SNACK", stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=[],
    )
    intaken = intake_project(owner_user_id="lead-s1", **dict(SNACK_IDEA))
    assert intaken["version"] == 1

    screened = validate_success(
        api.screen_project(
            intaken["id"], {"screening_notes": "Approved into stage 2."},
            make_gate_chair_headers("chair-s1"),
        )
    )

    assert_project(screened)
    assert screened["version"] == 2, "one accepted write moves the row from 1 to 2"
    assert screened["owner_user_id"] == "lead-s1", (
        "the chair's call does not reassign ownership"
    )
    assert screened["created_at"] == intaken["created_at"], "insert time is never rewritten"
    assert is_iso8601_timestamp(screened["updated_at"])
    assert screened["screening_score"] == pytest.approx(79.00, abs=0.01)
    assert screened["screening_decision"] == "PASSED"
    assert screened["dev_status"] == "SCREENED", (
        "a server-owned field the client never sent"
    )


def test_a_second_ballot_appends_a_row_and_leaves_the_first_untouched(api):
    """Casting a second seat's ballot adds a row rather than amending the first, and no
    ballot carries a version or an update stamp.

    PRD: "There is exactly one exception — `GateVote` is immutable once cast and therefore
    carries only `id` and `created_at`; it has neither `updated_at` nor `version`."
    PRD: "A `FunctionalReviewer` or `RegulatoryApprover` casts one ballot per
    cross-functional seat, supplying the `function`, the `vote` and an optional `rationale`;
    the ballot is stored against the review's `gate_review_id` with the acting identifier as
    `voter_user_id`, and the review's `vote_count` increments."

    Design: Corner/entities/entity_gate_vote_is_append_only_with_no_version_field
    """
    set_clock("2026-08-01T00:00:00Z")
    gate2 = register_stage_gate(
        gate_number=2, category="SNACK", stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=[], quorum_size=2,
        veto_functions=[],
    )
    project = intake_project(owner_user_id="lead-v1", **dict(SNACK_IDEA))
    screen_project(project["id"], chair_user_id="chair-v1", screening_notes="Into stage 2.")
    review = schedule_gate_review(project["id"], gate2["id"], chair_user_id="chair-v1",
                                  scheduled_at="2026-08-05T09:00:00Z")
    open_gate_review(review["id"], chair_user_id="chair-v1")
    first_ballot = cast_vote(review["id"], function="OPERATIONS", vote="APPROVE",
                            voter_user_id="rev-ops-v",
                            rationale="Line capacity confirmed.")

    second_ballot = validate_success(
        api.cast_gate_vote(
            review["id"],
            {"function": "MARKETING", "vote": "APPROVE_WITH_CONDITIONS",
             "rationale": "Copy pending."},
            make_functional_reviewer_headers("rev-mkt-v"),
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_gate_votes(review["id"], make_gate_chair_headers("chair-v1"))
    )
    assert meta["total_count"] == 2, "the second ballot appended instead of overwriting"
    by_function = {row["function"]: row for row in rows}
    operations = by_function["OPERATIONS"]
    assert operations["id"] == first_ballot["id"]
    assert operations["vote"] == "APPROVE"
    assert operations["voter_user_id"] == "rev-ops-v"
    assert operations["rationale"] == "Line capacity confirmed."
    assert operations["created_at"] == first_ballot["created_at"]
    assert by_function["MARKETING"]["id"] == second_ballot["id"]
    for row in rows:
        assert_gate_vote(row)
        assert "version" not in row, "a ballot has no version to increment"
        assert "updated_at" not in row, "a ballot is never updated"

    stored_review = validate_success(
        api.get_gate_review(review["id"], make_gate_chair_headers("chair-v1"))
    )
    assert stored_review["vote_count"] == 2
    assert stored_review["status"] == "IN_SESSION"


def test_a_checklist_item_under_an_unknown_project_reports_the_path_parent(
        api, gate_chair_headers, portfolio_admin_headers):
    """The nested create resolves the path project before the body's gate, so an unknown
    project is the project family's 404 even though the gate exists.

    PRD: "**Path existence** — every identifier in the URL resolves to a stored row,
    resolved outer to inner, so a nested path with two unknown identifiers reports the outer
    resource first."
    PRD: "**Body foreign-key existence** — every identifier supplied in the body resolves,
    checked left to right in the order the fields are declared for that operation. Answers
    the matching 404 code. This band applies to gate-review scheduling, checklist creation
    and prerequisite setting, pilot-run booking, label drafting, trade-presentation booking
    and the launch date lock."

    Design: Corner/entities/entity_deliverable_requires_existing_parent_project_not_found
    """
    gate2 = register_stage_gate(
        gate_number=2, category="SNACK", stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=[],
    )

    error = validate_error(
        api.create_deliverable(
            NON_EXISTENT_UUID,
            deliverable_payload(gate2["id"], deliverable_type="MANUFACTURING_READINESS",
                                owner_function="OPERATIONS"),
            gate_chair_headers,
        ),
        ApiErrorId.ERR_PROJECT_NOT_FOUND,
    )

    assert error["error_id"] != ApiErrorId.ERR_STAGE_GATE_NOT_FOUND.value, (
        "the body's gate reference does resolve, so the path parent is the failure"
    )
    _, meta = validate_paginated(api.list_deliverables(portfolio_admin_headers))
    assert meta["total_count"] == 0, "no checklist item was stored"


def test_a_prerequisite_edge_can_be_pointed_at_a_new_item_after_creation(api,
                                                                        gate_chair_headers):
    """Linking an existing item to a new prerequisite answers 200, stores the edge, and
    leaves every item's status alone.

    PRD: "An item's `prerequisite_deliverable_id` points at another item that must be
    settled first, and the edge may be set at creation or afterwards by an
    `InnovationLead` or `GateChair` pointing the item at a new prerequisite."
    PRD: "Each item starts in `PENDING` with `evidence_url`, `submitted_by_user_id` and
    `decided_by_user_id` all null, `due_at` null unless supplied,
    `prerequisite_deliverable_id` null unless supplied, and `submission_count` 0."

    Design: Corner/entities/entity_deliverable_prerequisite_graph_is_reverse_queryable
    """
    project, _, first, second, third = _prerequisite_chain(api)

    linked = validate_success(
        api.set_deliverable_prerequisite(
            second["id"], {"prerequisite_deliverable_id": first["id"]}, gate_chair_headers
        )
    )

    assert_deliverable(linked)
    assert linked["id"] == second["id"]
    assert linked["prerequisite_deliverable_id"] == first["id"]
    rows, meta = validate_paginated(
        api.list_deliverables(gate_chair_headers, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 3
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["prerequisite_deliverable_id"] is None, (
        "the chain has a root with no prerequisite of its own"
    )
    assert by_id[third["id"]]["prerequisite_deliverable_id"] == second["id"]
    assert all(row["status"] == "PENDING" for row in rows), (
        "linking is not a transition, so nothing left PENDING"
    )
    assert all(row["submission_count"] == 0 for row in rows)


def test_the_prerequisite_chain_is_walkable_from_each_root_to_its_dependent(
        api, gate_chair_headers):
    """Filtering the checklist by `prerequisite_deliverable_id` returns exactly the one
    dependent item at each hop of the two-hop chain.

    PRD: "List endpoints also accept optional equality filters drawn from the listed
    entity's own fields."
    PRD: "**Prerequisites form a directed acyclic graph within a project.**"

    Design: Corner/entities/entity_deliverable_prerequisite_graph_is_reverse_queryable
    """
    _, _, first, second, third = _prerequisite_chain(api)
    validate_success(
        api.set_deliverable_prerequisite(
            second["id"], {"prerequisite_deliverable_id": first["id"]}, gate_chair_headers
        )
    )

    first_hop, first_meta = validate_paginated(
        api.list_deliverables(
            gate_chair_headers, params={"prerequisite_deliverable_id": first["id"]}
        )
    )
    second_hop, second_meta = validate_paginated(
        api.list_deliverables(
            gate_chair_headers, params={"prerequisite_deliverable_id": second["id"]}
        )
    )

    assert first_meta["total_count"] == 1
    assert [row["id"] for row in first_hop] == [second["id"]], (
        "the first hop reaches exactly the item that depends on the root"
    )
    assert second_meta["total_count"] == 1
    assert [row["id"] for row in second_hop] == [third["id"]], (
        "the second hop reaches exactly the item that depends on the middle"
    )
    empty, empty_meta = validate_paginated(
        api.list_deliverables(
            gate_chair_headers, params={"prerequisite_deliverable_id": third["id"]}
        )
    )
    assert empty_meta["total_count"] == 0 and empty == [], (
        "the leaf of the chain has no dependents"
    )
