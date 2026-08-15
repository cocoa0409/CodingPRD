"""Optimistic concurrency, version incrementing, supersede cascade,
substantiation pinning, immediate consistency (PRD §2.4, §2.7, §2.8, §3.3)."""
from test_helpers import (
    ApiErrorId,
    batch_payload,
    create_brand_owner,
    create_complaint,
    create_formula,
    create_ingredient,
    create_production_batch,
    formula_payload,
    get_batch,
    get_brand,
    get_formula,
    get_registration,
    make_regulatory_affairs_headers,
    post_nutrient_profile,
    setup_batch_in_state,
    setup_locked_formula,
    setup_registration,
    setup_substantiated_formula,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_occ_batch_create_stale_formula_version(api, production_planner_headers):
    """PRD §2.7: "Creating a production batch against a formula requires a
    non-optional `expected_formula_version` field in the request body, carrying
    the formula `version` the client last read."
    PRD §2.7: "In both cases, if the supplied value does not match the formula's
    current `version` — because another writer has substantiated, locked, revised,
    withdrawn, or otherwise advanced the formula since the client last read it —
    the request is rejected with `ERR_STALE_FORMULA_VERSION` (HTTP 412)."
    PRD §3.5: "Creating a batch itself advances the formula's `version` by one, so
    a second planner working from a stale formula view is caught by the
    concurrency check on their own create."

    Design: Corner/cross_cutting_complexity_layers/occ_batch_create_stale_formula_version
    """
    ctx = setup_locked_formula()
    observed_version = get_formula(ctx["formula"]["id"])["version"]

    first = validate_success(
        api.create_batch(
            ctx["formula"]["id"],
            batch_payload(observed_version, planned_kg=100.0, line_id="LINE-O2",
                          scheduled_start="2026-09-02T08:00:00Z"),
            production_planner_headers,
        ),
        expected_status=201,
    )
    assert first["status"] == "SCHEDULED"
    assert get_formula(ctx["formula"]["id"])["version"] == observed_version + 1

    stale = api.create_batch(
        ctx["formula"]["id"],
        batch_payload(observed_version, planned_kg=100.0, line_id="LINE-O3",
                      scheduled_start="2026-09-02T08:00:00Z"),
        production_planner_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_FORMULA_VERSION.value)

    batches, meta = validate_paginated(
        api.list_formula_batches(ctx["formula"]["id"], production_planner_headers)
    )
    assert len(batches) == 1
    assert meta["total_count"] == 1


def test_occ_registration_approve_stale_formula_version(api, state_regulator_headers,
                                                        production_planner_headers):
    """PRD §2.7: "Approving a state registration likewise requires a non-optional
    `expected_formula_version`. In both cases, if the supplied value does not
    match the formula's current `version` — because another writer has
    substantiated, locked, revised, withdrawn, or otherwise advanced the formula
    since the client last read it — the request is rejected with
    `ERR_STALE_FORMULA_VERSION` (HTTP 412)."
    PRD §3.5: "Creating a batch itself advances the formula's `version` by one"

    Design: Corner/cross_cutting_complexity_layers/occ_registration_approve_stale_formula_version
    """
    ctx = setup_registration(target_state="UNDER_REVIEW", state_code="AZ", locked=True)
    observed_version = get_formula(ctx["formula"]["id"])["version"]

    # A batch create advances the formula version, making the observed one stale.
    validate_success(
        api.create_batch(
            ctx["formula"]["id"],
            batch_payload(observed_version, planned_kg=100.0, line_id="LINE-O4",
                          scheduled_start="2026-09-03T08:00:00Z"),
            production_planner_headers,
        ),
        expected_status=201,
    )

    resp = api.approve_registration(
        ctx["registration"]["id"], {"expected_formula_version": observed_version},
        state_regulator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_FORMULA_VERSION.value)
    assert get_registration(ctx["registration"]["id"])["status"] == "UNDER_REVIEW"


def test_entity_version_increments_on_each_mutation(
    api, platform_admin_headers, formulation_scientist_headers
):
    """PRD §2.4: "`version` (integer): a system-managed counter that starts at 1
    and increments by exactly one on every mutation of the resource — including
    explicit state transitions, automatic cascades originating elsewhere, and
    recomputation of derived fields."
    PRD §3.3: "Adding a line mutates the formula and increments its `version`."
    PRD §2.4: "`updated_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, refreshed on every mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/entity_version_increments_on_each_mutation
    """
    brand = create_brand_owner()
    ingredient = create_ingredient()

    created = validate_success(
        api.create_formula(brand["id"], formula_payload(), formulation_scientist_headers),
        expected_status=201,
    )
    assert created["version"] == 1
    stamps = [created["updated_at"]]

    # Advance the logical clock between mutations so the refreshed updated_at is
    # observable as a strictly moving value under the platform's logical clock.
    validate_success(
        api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, platform_admin_headers)
    )
    validate_success(
        api.add_formula_ingredient(
            created["id"], {"ingredient_id": ingredient["id"], "inclusion_pct": 100.0},
            formulation_scientist_headers,
        ),
        expected_status=201,
    )
    after_line = get_formula(created["id"])
    assert after_line["version"] == 2
    stamps.append(after_line["updated_at"])

    validate_success(
        api.set_clock({"to_iso8601": "2026-08-03T00:00:00Z"}, platform_admin_headers)
    )
    submitted = validate_success(
        api.submit_nutrient_review(created["id"], formulation_scientist_headers)
    )
    assert submitted["version"] == 3
    stamps.append(submitted["updated_at"])

    assert stamps[1] > stamps[0], "updated_at must refresh on the line-add mutation"
    assert stamps[2] > stamps[1], "updated_at must refresh on the submit mutation"


def test_formula_supersede_cascades_registrations_and_batches(
    api, formulation_scientist_headers, production_planner_headers
):
    """PRD §3.3: "A creation request may carry a `parent_formula_id` referencing
    an earlier formula; when that parent is `LOCKED`, creating the revision
    supersedes it — the parent moves from `LOCKED` to `SUPERSEDED`, and the
    cascade fires: every state registration of the parent sitting in `SUBMITTED`
    or `UNDER_REVIEW` moves to `REVOKED`, and every production batch of the parent
    sitting in `SCHEDULED` or `RELEASED_FOR_PRODUCTION` moves to `REJECTED`."
    PRD §3.3: "A formula starts in `DRAFT` with `revision_number` 1"

    Design: Corner/cross_cutting_complexity_layers/formula_supersede_cascades_registrations_and_batches
    """
    ctx = setup_locked_formula()
    parent = ctx["formula"]
    ra = make_regulatory_affairs_headers(ctx["brand"]["id"])
    registration = validate_success(
        api.create_state_registration(
            parent["id"],
            {"state_code": "WA", "label_revision_ref": 1, "tonnage_tier": 3.0},
            ra,
        ),
        expected_status=201,
    )
    batch = create_production_batch(parent["id"], planned_kg=900.0, line_id="LINE-U1",
                                    scheduled_start="2026-09-04T08:00:00Z")
    assert registration["status"] == "SUBMITTED"
    assert batch["status"] == "SCHEDULED"

    child = validate_success(
        api.create_formula(
            ctx["brand"]["id"],
            formula_payload(parent_formula_id=parent["id"]),
            formulation_scientist_headers,
        ),
        expected_status=201,
    )
    assert child["status"] == "DRAFT"
    assert child["revision_number"] == 1
    assert child["parent_formula_id"] == parent["id"]

    assert get_formula(parent["id"])["status"] == "SUPERSEDED"
    assert get_registration(registration["id"])["status"] == "REVOKED"
    assert get_batch(batch["id"])["status"] == "REJECTED"


def test_substantiation_pins_locked_profile_version(
    api, qa_approver_headers, formulation_scientist_headers
):
    """PRD §3.3: "Successful substantiation pins `substantiation_locked_version`
    to the current `version` of the linked substantiation object — the nutrient
    profile or the feeding-trial protocol, according to basis — freezing the
    evidentiary baseline at approval time."
    PRD §3.3: "A formula carries at most one current profile per basis: posting a
    new profile for a basis the formula already has replaces the earlier one as
    current"
    PRD §3.3: "If a nutrient profile already exists for the formula at submission
    time, its metabolizable energy is recomputed as part of the transition" — and
    PRD §2.4 advances the profile's `version` on that recomputation, so the pin
    is read back from the profile's current version, not the creation snapshot.

    Design: Corner/cross_cutting_complexity_layers/substantiation_pins_locked_profile_version
    """
    ctx = setup_substantiated_formula()
    profiles, _meta = validate_paginated(
        api.list_nutrient_profiles(ctx["formula"]["id"], formulation_scientist_headers)
    )
    assert len(profiles) == 1
    pinned_version = profiles[0]["version"]
    assert ctx["formula"]["status"] == "SUBSTANTIATED"
    assert ctx["formula"]["substantiation_locked_version"] == pinned_version

    # Replacing the profile afterwards must not move the frozen pin.
    post_nutrient_profile(ctx["formula"]["id"], crude_protein_min_pct=27.0)
    formula_after = get_formula(ctx["formula"]["id"])
    assert formula_after["substantiation_locked_version"] == pinned_version
    assert formula_after["status"] == "SUBSTANTIATED"


def test_immediate_visibility_of_action_side_effects(
    api, line_operator_headers, quality_analyst_headers
):
    """PRD §2.8: "These rollups are part of the mutation that triggered them,
    never deferred."
    PRD §3.5: "Completion stores `actual_kg`, computes the batch's
    `yield_variance_pct` (the yield rule itself, including the override
    governance, is specified in §3.6), and increments the parent formula's
    `total_batch_count` by one."
    PRD §3.8: "Triage computes the final `triage_score`, recomputes the brand's
    `complaint_score`, and then branches"

    Design: Corner/consistency_model/immediate_visibility_of_action_side_effects
    """
    ctx = setup_batch_in_state("IN_PROCESS", planned_kg=800.0, line_id="LINE-I1")
    case = create_complaint(
        ctx["brand"]["id"], ctx["formula"]["id"],
        severity="SERIOUS", category="ILLNESS", adverse_event_flag=False,
    )

    completed = validate_success(
        api.complete_batch(ctx["batch"]["id"], {"actual_kg": 800.0}, line_operator_headers)
    )
    assert completed["status"] == "COMPLETED"
    assert completed["yield_variance_pct"] == 0.0

    triaged = validate_success(
        api.triage_complaint(case["id"], {"confirm_adverse_event_flag": True},
                             quality_analyst_headers)
    )
    assert triaged["triage_score"] == 45.0
    assert triaged["status"] == "TRIAGED"

    # One TRIAGED case at half weight: (45 * 0.5) / 0.5 == 45.0, visible at once.
    assert get_brand(ctx["brand"]["id"])["complaint_score"] == 45.0
