"""Specification workflow: review cycle, temporal guards, supersede cascade, OCC."""

from test_helpers import (
    AUTHOR_1,
    AUTHOR_2,
    QM_1,
    ApiErrorId,
    add_parameter,
    approve_spec,
    create_draft_spec,
    create_draft_spec_with_parameters,
    create_ingredient_entity,
    create_provisional_source,
    create_spec_payload,
    create_supplier_entity,
    fresh_ingredient,
    fresh_ingredient_version,
    make_quality_manager_headers,
    make_spec_author_headers,
    make_spec_effective,
    setup_dual_sourced_ingredient,
    submit_spec,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSpecReviewCycle:
    def test_spec_revision_cycle_full_loop(self, api):
        """PRD §3.2: "Reject moves the spec to `REJECTED`. Revise moves a `REJECTED`
        spec back to `DRAFT` so the author can edit parameters and resubmit; both
        reject and revise carry the same state and segregation guards."

        Design: Difficulty/non_linear_state_machine/spec_review_reject_revision_cycle
        """
        ingredient = create_ingredient_entity("ENZ-CYC")
        spec = create_draft_spec_with_parameters(
            ingredient["id"],
            parameters=[{
                "parameter_name": "activity", "criticality": "CRITICAL", "uom": "u_g",
                "target_value": 100, "min_value": 90, "max_value": 110,
            }],
        )
        submitted = submit_spec(ingredient["id"], spec["id"])
        assert submitted["status"] == "PENDING_REVIEW"

        rejected = validate_success(
            api.reject_spec(ingredient["id"], spec["id"], make_quality_manager_headers(QM_1))
        )
        assert rejected["status"] == "REJECTED"

        # Cycle back: REJECTED -> DRAFT re-opens parameter editing.
        revised = validate_success(
            api.revise_spec(ingredient["id"], spec["id"], make_spec_author_headers(AUTHOR_1))
        )
        assert revised["status"] == "DRAFT", "revision loop must return the spec to DRAFT"

        # Parameter add succeeds again in the second DRAFT pass.
        add_parameter(
            ingredient["id"], spec["id"],
            parameter_name="moisture", criticality="MINOR", uom="percent",
            target_value=5, min_value=0, max_value=10,
        )
        resubmitted = submit_spec(ingredient["id"], spec["id"])
        assert resubmitted["status"] == "PENDING_REVIEW"
        approved = approve_spec(ingredient["id"], spec["id"])
        assert approved["status"] == "APPROVED"

    def test_spec_revise_rejected_by_non_author(self, api):
        """PRD §2.11: "Only the spec's author (the `SpecAuthor` whose `X-User-ID`
        matches the spec's `author_user_id`) may submit that spec for review or
        revise it after a rejection."

        Design: Difficulty/non_linear_state_machine/spec_review_reject_revision_cycle
        """
        ingredient = create_ingredient_entity("ENZ-CYC2")
        spec = create_draft_spec_with_parameters(ingredient["id"])
        submit_spec(ingredient["id"], spec["id"])
        validate_success(api.reject_spec(ingredient["id"], spec["id"], make_quality_manager_headers(QM_1)))

        resp = api.revise_spec(ingredient["id"], spec["id"], make_spec_author_headers(AUTHOR_2))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestSpecApproveAndEffectivityGuards:
    def test_make_effective_before_effective_date_blocked(self, api):
        """PRD §3.2: "It is rejected with `ERR_INVALID_STATE` if the spec is not
        `APPROVED`, with `ERR_SPEC_NOT_YET_EFFECTIVE` if the logical clock is before
        the spec's `effective_date`, and with `ERR_SUPERSEDES_NOT_EFFECTIVE` if the
        spec carries a non-null `supersedes_spec_id` whose referenced spec is not
        currently `EFFECTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_spec_approve_and_effective
        """
        ingredient = create_ingredient_entity("FLV-1")
        spec = create_draft_spec_with_parameters(
            ingredient["id"],
            parameters=[{
                "parameter_name": "aroma", "criticality": "MINOR", "uom": "score",
                "target_value": 8, "min_value": 6, "max_value": 10,
            }],
            effective_date="2026-09-01T00:00:00Z",  # after the default clock 2026-08-01
        )
        submit_spec(ingredient["id"], spec["id"])
        # Approve by a QualityManager who is not the author succeeds: the
        # segregation guard and the temporal guard live on different endpoints.
        approved = approve_spec(ingredient["id"], spec["id"], qm_id=QM_1)
        assert approved["status"] == "APPROVED"

        resp = api.make_spec_effective(ingredient["id"], spec["id"], make_quality_manager_headers(QM_1))
        validate_error(resp, ApiErrorId.ERR_SPEC_NOT_YET_EFFECTIVE)

    def test_author_cannot_approve_own_spec(self, api):
        """PRD §2.11: "The `QualityManager` approving or rejecting a spec must not
        be the spec's author." PRD §2.12: the segregation check sits before the
        temporal guards in the validation order ("then segregation-of-duties; then
        temporal guards").

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_spec_approve_and_effective
        """
        ingredient = create_ingredient_entity("FLV-2")
        spec = create_draft_spec_with_parameters(
            ingredient["id"],
            effective_date="2026-09-01T00:00:00Z",
        )
        submit_spec(ingredient["id"], spec["id"])

        # Same operator id as the author, presented with the QualityManager role.
        resp = api.approve_spec(ingredient["id"], spec["id"], make_quality_manager_headers(AUTHOR_1))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestSpecSupersedeCascade:
    def _setup_supersede(self):
        """Dual-sourced ingredient on spec v1; spec v2 approved, ready to make effective."""
        ctx = setup_dual_sourced_ingredient("DUAL-1")
        ingredient = ctx["ingredient"]
        spec1 = ctx["spec"]
        spec2 = create_draft_spec_with_parameters(
            ingredient["id"],
            parameters=[{
                "parameter_name": "moisture", "criticality": "MINOR", "uom": "percent",
                "target_value": 4, "min_value": 0, "max_value": 8,
            }],
            label="v2",
            effective_date="2026-07-15T00:00:00Z",
            version_note="tightened moisture band",
            supersedes_spec_id=spec1["id"],
        )
        submit_spec(ingredient["id"], spec2["id"])
        approve_spec(ingredient["id"], spec2["id"])
        ctx["spec2"] = spec2
        return ctx

    def test_spec_supersede_suspends_stale_pinned_sources(self, api, procurement_manager_headers):
        """PRD §3.2: "On success, several side effects fire: the referenced prior
        spec transitions from `EFFECTIVE` to `SUPERSEDED`; the ingredient's
        `active_spec_id` is updated to the newly effective spec; every approved
        source of the ingredient whose `pinned_spec_id` matches the superseded spec
        and whose status is `ACTIVE` transitions to `SUSPENDED` with
        `suspension_reason` set to `MANUAL` (the stale-pin sweep); and the
        ingredient's `current_dual_source_breach` is recomputed."

        Design: Difficulty/transitive_cascade/spec_supersede_cascade_depth3
        """
        ctx = self._setup_supersede()
        ingredient = ctx["ingredient"]
        spec1, spec2 = ctx["spec"], ctx["spec2"]

        make_spec_effective(ingredient["id"], spec2["id"])

        spec1_after = validate_success(
            api.get_spec(ingredient["id"], spec1["id"], procurement_manager_headers)
        )
        assert spec1_after["status"] == "SUPERSEDED"

        ing_after = fresh_ingredient(ingredient["id"])
        assert ing_after["active_spec_id"] == spec2["id"]

        sources, _meta = validate_paginated(
            api.list_approved_sources(ingredient["id"], procurement_manager_headers)
        )
        assert len(sources) == 2
        for row in sources:
            assert row["status"] == "SUSPENDED", f"stale-pin sweep must suspend {row['id']}"
            assert row["suspension_reason"] == "MANUAL"

    def test_spec_supersede_sets_dual_source_breach(self, api, procurement_manager_headers):
        """PRD §3.10: "For an ingredient, count the approved sources that are in
        `ACTIVE` status and pinned to the ingredient's `active_spec_id`. When
        `requires_dual_source` is true and that count is less than two,
        `current_dual_source_breach` is set to true; when the count is exactly two
        or more, the breach is cleared."

        Design: Difficulty/transitive_cascade/spec_supersede_cascade_depth3
        """
        ctx = self._setup_supersede()
        ingredient = ctx["ingredient"]
        assert ctx["ingredient"]["current_dual_source_breach"] is False, (
            "two ACTIVE sources on the EFFECTIVE spec: breach starts false"
        )

        make_spec_effective(ingredient["id"], ctx["spec2"]["id"])

        ing_after = fresh_ingredient(ingredient["id"])
        assert ing_after["current_dual_source_breach"] is True, (
            "after the stale-pin sweep, zero ACTIVE sources remain on the EFFECTIVE spec"
        )


class TestSpecTransitionsAndGuards:
    def test_spec_submit_from_pending_review_rejected_invalid_state(self, api):
        """PRD §3.2: "The submit is rejected with `ERR_INVALID_STATE` if the spec
        is not `DRAFT`, with `ERR_NO_SPEC_PARAMETERS` if the spec has zero
        parameters, with `ERR_INVALID_REQUEST` if `version_note` is shorter than
        ten characters, and with `ERR_SEGREGATION_OF_DUTIES` if the acting
        `SpecAuthor` is not the spec's recorded author."

        Design: Corner/state_machines/spec_submit_from_pending_review_rejected_invalid_state
        """
        ingredient = create_ingredient_entity("ENZ-IV")
        spec = create_draft_spec_with_parameters(ingredient["id"])
        submit_spec(ingredient["id"], spec["id"])

        resp = api.submit_spec(ingredient["id"], spec["id"], make_spec_author_headers(AUTHOR_1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_retired_spec_terminal_lockdown(self, api):
        """PRD §3.2: "The submit is rejected with `ERR_INVALID_STATE` if the spec
        is not `DRAFT`" and approve "is rejected with `ERR_INVALID_STATE` if the
        spec is not in review" — a RETIRED spec is neither DRAFT nor in review.

        Design: Corner/state_machines/retired_spec_terminal_lockdown
        """
        ingredient = create_ingredient_entity("ENZ-RET")
        spec = create_draft_spec_with_parameters(ingredient["id"])
        retired = validate_success(
            api.retire_spec(ingredient["id"], spec["id"], make_quality_manager_headers(QM_1))
        )
        assert retired["status"] == "RETIRED"

        resp_submit = api.submit_spec(ingredient["id"], spec["id"], make_spec_author_headers(AUTHOR_1))
        validate_error(resp_submit, ApiErrorId.ERR_INVALID_STATE)
        resp_approve = api.approve_spec(ingredient["id"], spec["id"], make_quality_manager_headers(QM_1))
        validate_error(resp_approve, ApiErrorId.ERR_INVALID_STATE)
        resp_retire = api.retire_spec(ingredient["id"], spec["id"], make_quality_manager_headers(QM_1))
        validate_error(resp_retire, ApiErrorId.ERR_INVALID_STATE)

    def test_spec_submit_without_parameters_blocked(self, api):
        """PRD §3.2: "The submit is rejected with `ERR_INVALID_STATE` if the spec
        is not `DRAFT`, with `ERR_NO_SPEC_PARAMETERS` if the spec has zero
        parameters, ..."

        Design: Corner/validations/spec_submit_without_parameters_blocked
        """
        ingredient = create_ingredient_entity("ENZ-NP")
        spec = create_draft_spec(ingredient["id"])  # zero parameters
        resp = api.submit_spec(ingredient["id"], spec["id"], make_spec_author_headers(AUTHOR_1))
        validate_error(resp, ApiErrorId.ERR_NO_SPEC_PARAMETERS)

    def test_make_effective_with_supersedes_not_effective_blocked(self, api):
        """PRD §3.2: "It is rejected with `ERR_INVALID_STATE` if the spec is not
        `APPROVED`, with `ERR_SPEC_NOT_YET_EFFECTIVE` if the logical clock is before
        the spec's `effective_date`, and with `ERR_SUPERSEDES_NOT_EFFECTIVE` if the
        spec carries a non-null `supersedes_spec_id` whose referenced spec is not
        currently `EFFECTIVE`."

        Design: Corner/validations/make_effective_with_supersedes_not_effective_blocked
        """
        ingredient = create_ingredient_entity("ENZ-SNE")
        spec1 = create_draft_spec(ingredient["id"], label="v1")  # stays DRAFT
        spec2 = create_draft_spec_with_parameters(
            ingredient["id"], label="v2",
            effective_date="2026-07-15T00:00:00Z",
            version_note="supersede draft attempt",
            supersedes_spec_id=spec1["id"],
        )
        submit_spec(ingredient["id"], spec2["id"])
        approve_spec(ingredient["id"], spec2["id"])

        resp = api.make_spec_effective(ingredient["id"], spec2["id"], make_quality_manager_headers(QM_1))
        validate_error(resp, ApiErrorId.ERR_SUPERSEDES_NOT_EFFECTIVE)

    def test_segregation_author_cannot_approve_own_spec(self, api):
        """PRD §2.11: "The `QualityManager` approving or rejecting a spec must not
        be the spec's author." — rejection carries `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403) even though the role itself is permitted.

        Design: Corner/state_machines/segregation_author_cannot_approve_own_spec
        """
        ingredient = create_ingredient_entity("ENZ-SOD")
        spec = create_draft_spec_with_parameters(ingredient["id"])
        submit_spec(ingredient["id"], spec["id"])

        resp = api.approve_spec(ingredient["id"], spec["id"], make_quality_manager_headers(AUTHOR_1))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_rbac_regulatory_cannot_approve_spec(self, api, regulatory_affairs_headers):
        """PRD §2.1: "a role that is not permitted for the endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §2.12: "then forbidden role; then path
        resource existence" — the role check precedes state and segregation checks.
        PRD §4 restricts spec approve to QualityManager.

        Design: Corner/roles/rbac_regulatory_cannot_approve_spec
        """
        ingredient = create_ingredient_entity("RBAC-2")
        spec = create_draft_spec_with_parameters(ingredient["id"])
        submit_spec(ingredient["id"], spec["id"])

        resp = api.approve_spec(ingredient["id"], spec["id"], regulatory_affairs_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_retire_spec_in_use_blocked(self, api):
        """PRD §3.2: "Retire moves a `DRAFT` or `REJECTED` spec to `RETIRED` and is
        rejected with `ERR_SPEC_IN_USE` if any approved source still references the
        spec in `PROVISIONAL` or `ACTIVE` status."

        Design: Corner/errors/retire_spec_in_use_blocked
        """
        ingredient = create_ingredient_entity("ENZ-SIU")
        spec = create_draft_spec(ingredient["id"], label="v1")
        supplier = create_supplier_entity("SUP-SIU")
        create_provisional_source(ingredient["id"], supplier["id"], spec["id"])

        resp = api.retire_spec(ingredient["id"], spec["id"], make_quality_manager_headers(QM_1))
        validate_error(resp, ApiErrorId.ERR_SPEC_IN_USE)

    def test_occ_stale_version_on_spec_create(self, api, spec_author_headers, procurement_manager_headers):
        """PRD §2.7: "The client must supply the parent's last-observed `version` in
        a required request field; if it does not match the parent's current
        `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)." and
        "Creating a new spec version under an ingredient requires
        `expected_ingredient_version`."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_spec_create
        """
        ingredient = create_ingredient_entity("OCC-1")
        stale_version = ingredient["version"]  # captured before the first spec write
        spec1 = create_draft_spec(ingredient["id"], label="v1")  # bumps ingredient version

        resp = api.create_spec(
            ingredient["id"],
            create_spec_payload(
                stale_version,
                spec_version_label="v2",
                version_note="stale version attempt",
                supersedes_spec_id=spec1["id"],
            ),
            spec_author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        retry = api.create_spec(
            ingredient["id"],
            create_spec_payload(
                fresh_ingredient_version(ingredient["id"]),
                spec_version_label="v2",
                version_note="fresh version attempt",
                supersedes_spec_id=spec1["id"],
            ),
            spec_author_headers,
        )
        assert retry.status_code == 201, f"retry with the fresh version must succeed: {retry.text[:300]}"
