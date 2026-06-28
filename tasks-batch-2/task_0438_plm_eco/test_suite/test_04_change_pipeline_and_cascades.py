"""Engineering change pipeline: quorum, segregation of duties, the release
cascade, exclusive occupancy, temporal overlap, and compensating reverts.

Covers the deep difficulty instances around the ECO lifecycle (PRD 3.5-3.7),
deviations (3.10) and serialized-unit conformance (3.11).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    validate_paginated, ApiErrorId,
    TEST_USERS, make_change_admin_headers, make_approver_headers,
    factories, get_success_data, fixtures,
)

DESIGNER = TEST_USERS["designer_headers"]
SUPPLIER_MGR = TEST_USERS["supplier_manager_headers"]
QUALITY = TEST_USERS["quality_engineer_headers"]
VIEWER = TEST_USERS["viewer_headers"]
CA = "ca1"
CHANGE_ADMIN = make_change_admin_headers(CA)
AP1 = make_approver_headers("ap1")
AP2 = make_approver_headers("ap2")


# ===========================================================================
# non_linear_state_machine
# ===========================================================================
class TestEcoRecallCycle:
    def _build_in_approval_with_one_approval(self):
        """ECO IN_APPROVAL, required_approvals=2, one task already APPROVED."""
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=100)
        get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
        eco, task_ids = fixtures.create_in_approval_eco(
            part["id"], rev["id"], effectivity_date="2026-02-01T00:00:00Z",
            required_approvals=2, assignees=["ap1", "ap2"])
        get_success_data(api_client.approve_task(task_ids[0], AP1))
        return eco, task_ids

    def test_recall_returns_to_draft_and_resets_count(self, api):
        """PRD 3.5: "An `IN_APPROVAL` order may be recalled by the `ChangeAdmin` back
        to `DRAFT`; recall resets every approval task's `decision` to `PENDING`, clears
        each `decided_by_user_id`, and sets `approval_count` back to 0, making the order
        machine cyclic."

        Design: Difficulty/non_linear_state_machine/eco_in_approval_recall_cycle
        """
        eco, _task_ids = self._build_in_approval_with_one_approval()
        recalled = validate_success(api.recall_change_order(eco["id"], CHANGE_ADMIN))
        assert recalled["status"] == "DRAFT", recalled
        assert recalled["approval_count"] == 0, recalled

    def test_recall_resets_approval_task_to_pending(self, api):
        """PRD 3.5: "recall resets every approval task's `decision` to `PENDING`,
        clears each `decided_by_user_id`, and sets `approval_count` back to 0, making
        the order machine cyclic."

        Design: Difficulty/non_linear_state_machine/eco_in_approval_recall_cycle
        """
        eco, task_ids = self._build_in_approval_with_one_approval()
        validate_success(api.recall_change_order(eco["id"], CHANGE_ADMIN))
        task = validate_success(api.get_approval_task(task_ids[0], AP1))
        assert task["decision"] == "PENDING", task
        assert task["decided_by_user_id"] is None, task


class TestSerializedUnitParallelDimensions:
    def _built_conforming_unit(self):
        part, rev, _leaf = fixtures.create_released_make_part()
        return fixtures.create_built_unit(rev["id"])

    def test_flag_nonconforming_leaves_build_status_untouched(self, api):
        """PRD 3.11: "A serialized unit tracks a single physical article through two
        independent state dimensions."
        PRD 3.11: "A `QualityEngineer` may manually flag a conforming unit, moving it
        `CONFORMING → NONCONFORMING`".

        Design: Difficulty/non_linear_state_machine/serialized_unit_parallel_dimensions
        """
        unit = self._built_conforming_unit()
        assert unit["build_status"] == "BUILT"
        flagged = validate_success(api.flag_unit_nonconforming(unit["id"], QUALITY))
        assert flagged["build_status"] == "BUILT", flagged
        assert flagged["conformance_status"] == "NONCONFORMING", flagged

    def test_conformance_flips_independently_of_build(self, api):
        """PRD 3.11: "The two dimensions evolve independently on the same row".
        PRD 3.11: "A new unit starts with `build_status` `PLANNED` and
        `conformance_status` `CONFORMING`."

        Design: Difficulty/non_linear_state_machine/serialized_unit_parallel_dimensions
        """
        unit = self._built_conforming_unit()
        # build advanced to BUILT, conformance still at its starting CONFORMING.
        assert unit["conformance_status"] == "CONFORMING"
        flagged = validate_success(api.flag_unit_nonconforming(unit["id"], QUALITY))
        # build dimension is unaffected by the conformance flip.
        assert flagged["build_status"] == "BUILT", flagged


# ===========================================================================
# transitive_cascade
# ===========================================================================
class TestReleaseCascadeDepth3:
    def _build(self):
        """Part D rev A RELEASED with a BUILT CONFORMING unit pinned to it; rev B
        IN_REVIEW attached to a 2nd APPROVED ECO whose effectivity has passed."""
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        d = fixtures.create_part("MAKE", base_cost_cents=100)
        # rev A -> released
        da = fixtures.create_revision(d["id"])
        fixtures.add_bom_line(da["id"], leaf["id"], 1)
        get_success_data(api_client.submit_revision_review(da["id"], DESIGNER))
        fixtures.release_revision(d["id"], da["id"])
        # unit pinned to rev A, built + conforming
        unit = fixtures.create_built_unit(da["id"])
        # rev B branched from released A, IN_REVIEW, attached to 2nd APPROVED ECO
        db = fixtures.create_revision(d["id"])
        fixtures.add_bom_line(db["id"], leaf["id"], 2)
        get_success_data(api_client.submit_revision_review(db["id"], DESIGNER))
        eco2, _t = fixtures.create_approved_eco(
            d["id"], db["id"], effectivity_date="2026-01-04T00:00:00Z")
        fixtures.set_clock("2026-01-05T00:00:00Z")
        return d, da, db, unit, eco2

    def test_make_effective_releases_new_and_obsoletes_prior(self, api):
        """PRD 3.7: "First, each affected revision transitions `IN_REVIEW → RELEASED`."
        PRD 3.7: "Second, if a different prior revision of the same part was already
        `RELEASED`, that prior revision is driven `RELEASED → OBSOLETE`."

        Design: Difficulty/transitive_cascade/eco_effective_release_obsolete_nonconforming_depth3
        """
        d, da, db, _unit, eco2 = self._build()
        validate_success(api.make_change_order_effective(eco2["id"], CHANGE_ADMIN))
        assert validate_success(api.get_revision(db["id"], DESIGNER))["lifecycle_state"] == "RELEASED"
        assert validate_success(api.get_revision(da["id"], DESIGNER))["lifecycle_state"] == "OBSOLETE"

    def test_obsoleted_revision_unit_becomes_nonconforming(self, api):
        """PRD 3.7: "Third, for each serialized unit pinned to that now-obsoleted
        revision whose `conformance_status` is `CONFORMING` and that is not covered by a
        granted deviation, the unit's `conformance_status` becomes `NONCONFORMING`."

        Design: Difficulty/transitive_cascade/eco_effective_release_obsolete_nonconforming_depth3
        """
        d, da, db, unit, eco2 = self._build()
        validate_success(api.make_change_order_effective(eco2["id"], CHANGE_ADMIN))
        u = validate_success(api.get_serialized_unit(unit["id"], QUALITY))
        assert u["conformance_status"] == "NONCONFORMING", u


class TestPcnAcceptSpawnsEcr:
    def _assessed_pcn_on_buy(self):
        sup = fixtures.create_supplier()
        part = fixtures.create_buy_part(base_cost_cents=400, supplier_id=sup["id"])
        return fixtures.create_assessed_pcn(sup["id"], part["id"]), part

    def test_accept_sets_spawned_ecr_id(self, api):
        """PRD 3.8: "Second, the notice's `spawned_ecr_id` is set to the id of that
        newly created request, closing the loop between the supplier notice and the
        engineering change pipeline."

        Design: Difficulty/transitive_cascade/pcn_accept_spawns_ecr_depth2
        """
        pcn, _part = self._assessed_pcn_on_buy()
        accepted = validate_success(api.accept_pcn(pcn["id"], SUPPLIER_MGR))
        assert accepted["status"] == "ACCEPTED", accepted
        assert accepted["spawned_ecr_id"] is not None, accepted

    def test_accept_creates_supplier_change_ecr_in_draft(self, api):
        """PRD 3.8: "First, the system creates a new change request in `DRAFT` whose
        `affected_part_id` matches the notice's affected part, whose `reason_code` is
        `SUPPLIER_CHANGE`, and whose `source_pcn_id` points back at this notice."

        Design: Difficulty/transitive_cascade/pcn_accept_spawns_ecr_depth2
        """
        pcn, part = self._assessed_pcn_on_buy()
        accepted = validate_success(api.accept_pcn(pcn["id"], SUPPLIER_MGR))
        rows, _meta = validate_paginated(
            api.list_change_requests(VIEWER, params={"source_pcn_id": pcn["id"]}))
        assert len(rows) == 1, rows
        ecr = rows[0]
        assert ecr["reason_code"] == "SUPPLIER_CHANGE", ecr
        assert ecr["status"] == "DRAFT", ecr
        assert ecr["affected_part_id"] == part["id"], ecr
        assert ecr["id"] == accepted["spawned_ecr_id"], ecr


# ===========================================================================
# priority_pair_validation_conflict
# ===========================================================================
class TestValidationPriorityConflicts:
    def test_make_effective_on_in_approval_eco_rejected(self, api):
        """PRD 3.7: "Once an order is `APPROVED`, a `ChangeAdmin` makes it effective,
        but only when the logical clock has reached or passed the order's
        `effectivity_date`; an attempt before that instant is rejected with
        `ERR_NOT_YET_EFFECTIVE`."
        PRD 3.7: "when that governing order is in `APPROVED` status at make-effective
        time (otherwise `ERR_ECO_NOT_APPROVED`)."

        The PRD does not commit in prose to which of the ECO-state gate (the order is
        not `APPROVED`) or the `ERR_ECO_NOT_APPROVED` precondition pre-empts the other,
        so either rejection is PRD-faithful (error-precedence silence pattern).

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_make_effective
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=100)
        get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
        eco, _task_ids = fixtures.create_in_approval_eco(
            part["id"], rev["id"], required_approvals=2, assignees=["ap1", "ap2"])
        fixtures.set_clock("2026-01-03T00:00:00Z")
        # ECO is IN_APPROVAL (0 approvals), not APPROVED -> make-effective not permitted.
        resp = api.make_change_order_effective(eco["id"], CHANGE_ADMIN)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ECO_NOT_APPROVED])

    def test_make_effective_succeeds_once_eco_is_approved(self, api):
        """PRD 3.7: "Once an order is `APPROVED`, a `ChangeAdmin` makes it effective,
        but only when the logical clock has reached or passed the order's
        `effectivity_date`; an attempt before that instant is rejected with
        `ERR_NOT_YET_EFFECTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_make_effective
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=100)
        get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
        # Same ECO path but driven all the way to APPROVED: the state gate now passes.
        eco, _t = fixtures.create_approved_eco(part["id"], rev["id"])
        fixtures.set_clock("2026-01-03T00:00:00Z")
        effective = validate_success(api.make_change_order_effective(eco["id"], CHANGE_ADMIN))
        assert effective["status"] == "EFFECTIVE", effective

    def test_self_approve_on_draft_eco_returns_invalid_state(self, api):
        """PRD 3.6: "In both cases three preconditions are enforced, evaluated in order:
        the parent order must be in `IN_APPROVAL` (otherwise `ERR_INVALID_STATE`); the
        acting `X-User-ID` must equal the task's `assignee_user_id` (otherwise
        `ERR_NOT_TASK_ASSIGNEE`); and the acting `X-User-ID` must not equal the parent
        order's `created_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), so the
        person who created the order can never approve or reject its tasks."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_approve_self
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=100)
        get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
        # DRAFT ECO (not submitted) with one task assigned to the creator ca1.
        eco, task_ids = fixtures.create_draft_eco(
            part["id"], rev["id"], effectivity_date="2026-02-01T00:00:00Z",
            required_approvals=1, assignees=["ca1"])
        # Creator ca1 attempts to approve own task while ECO still DRAFT.
        resp = api.approve_task(task_ids[0], make_approver_headers("ca1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_self_approve_on_in_approval_eco_returns_segregation(self, api):
        """PRD 3.6: "the acting `X-User-ID` must not equal the parent order's
        `created_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), so the person who
        created the order can never approve or reject its tasks."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_approve_self
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=100)
        get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
        # Once the ECO is IN_APPROVAL the state check passes, so the lower-priority
        # segregation-of-duties check is what rejects the creator approving their task.
        eco, task_ids = fixtures.create_in_approval_eco(
            part["id"], rev["id"], effectivity_date="2026-02-01T00:00:00Z",
            required_approvals=1, assignees=["ca1"])
        resp = api.approve_task(task_ids[0], make_approver_headers("ca1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


# ===========================================================================
# boundary_precision_check
# ===========================================================================
class TestQuorumBoundary:
    def _build(self):
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=100)
        get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
        eco, task_ids = fixtures.create_in_approval_eco(
            part["id"], rev["id"], effectivity_date="2026-02-01T00:00:00Z",
            required_approvals=2, assignees=["ap1", "ap2"])
        return eco, task_ids

    def test_one_approval_below_quorum_stays_in_approval(self, api):
        """PRD 3.6: "the order is considered approved once `approval_count` reaches or
        exceeds `required_approvals` — the boundary is inclusive, meeting the threshold
        suffices, it need not be exceeded."

        Design: Difficulty/boundary_precision_check/quorum_inclusive_lower_bound
        """
        eco, task_ids = self._build()
        validate_success(api.approve_task(task_ids[0], AP1))
        mid = validate_success(api.get_change_order(eco["id"], CHANGE_ADMIN))
        assert mid["status"] == "IN_APPROVAL", mid
        assert mid["approval_count"] == 1, mid

    def test_reaching_quorum_approves_order(self, api):
        """PRD 3.6: "When that quorum is met the order cascades `IN_APPROVAL →
        APPROVED`, and as part of that transition every affected item is pinned: each
        item's `pinned` flag is set true and the child revision ids of its
        `part_revision_id` are frozen, so the released configuration is locked at the
        moment of approval and cannot drift afterward."

        Design: Difficulty/boundary_precision_check/quorum_inclusive_lower_bound
        """
        eco, task_ids = self._build()
        validate_success(api.approve_task(task_ids[0], AP1))
        validate_success(api.approve_task(task_ids[1], AP2))
        fin = validate_success(api.get_change_order(eco["id"], CHANGE_ADMIN))
        assert fin["status"] == "APPROVED", fin
        assert fin["approval_count"] == 2, fin


class TestDeviationEmptyCandidateSet:
    def test_grant_with_no_nonconforming_units_covers_zero(self, api):
        """PRD 3.10: "if there are no candidates the selection is empty and
        `covered_unit_count` remains 0."

        Design: Difficulty/boundary_precision_check/deviation_coverage_empty_candidate_set
        """
        part = fixtures.create_part("MAKE", base_cost_cents=100)
        dev = fixtures.create_submitted_deviation(
            part["id"], "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z",
            defect_code="COSMETIC", max_units=5)
        granted = validate_success(api.grant_deviation(dev["id"], QUALITY))
        assert granted["covered_unit_count"] == 0, granted

    def test_grant_with_empty_candidate_set_still_transitions(self, api):
        """PRD 3.10: "Granting a deviation moves it `SUBMITTED → GRANTED` and waives
        units."

        Design: Difficulty/boundary_precision_check/deviation_coverage_empty_candidate_set
        """
        part = fixtures.create_part("MAKE", base_cost_cents=100)
        dev = fixtures.create_submitted_deviation(
            part["id"], "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z",
            defect_code="COSMETIC", max_units=5)
        granted = validate_success(api.grant_deviation(dev["id"], QUALITY))
        assert granted["status"] == "GRANTED", granted


# ===========================================================================
# cross_entity_state_dependency
# ===========================================================================
class TestRevisionReleaseRequiresApprovedEco:
    def test_make_effective_releases_revision_and_sets_released_pointer(self, api):
        """PRD 3.7: "Making the order effective transitions it `APPROVED → EFFECTIVE`
        and fires the central release cascade for each affected item's
        `part_revision_id`."
        PRD 3.7: "On release, the part's `released_revision_id` is set to this revision
        and the part's `revision_count` is recomputed."

        Design: Difficulty/cross_entity_state_dependency/revision_release_requires_approved_eco
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=100)
        get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
        eco, _t = fixtures.create_approved_eco(part["id"], rev["id"])
        fixtures.set_clock("2026-01-03T00:00:00Z")
        validate_success(api.make_change_order_effective(eco["id"], CHANGE_ADMIN))
        r = validate_success(api.get_revision(rev["id"], DESIGNER))
        assert r["lifecycle_state"] == "RELEASED", r
        p = validate_success(api.get_part(part["id"], DESIGNER))
        assert p["released_revision_id"] == rev["id"], p

    def test_revision_reaches_released_only_via_eco_effectivity(self, api):
        """PRD 3.2: "A revision reaches `RELEASED` only as a system cascade driven by a
        change order becoming effective (detailed in Section 3.5), never by a direct
        client call, and from `RELEASED` it is driven to `OBSOLETE` only as a system
        cascade when a newer revision of the same part is released."

        Design: Difficulty/cross_entity_state_dependency/revision_release_requires_approved_eco
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=100)
        get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
        # IN_REVIEW with an APPROVED governing ECO; before make-effective it is NOT released.
        eco, _t = fixtures.create_approved_eco(part["id"], rev["id"])
        pre = validate_success(api.get_revision(rev["id"], DESIGNER))
        assert pre["lifecycle_state"] == "IN_REVIEW", pre
        fixtures.set_clock("2026-01-03T00:00:00Z")
        validate_success(api.make_change_order_effective(eco["id"], CHANGE_ADMIN))
        post = validate_success(api.get_revision(rev["id"], DESIGNER))
        assert post["lifecycle_state"] == "RELEASED", post


class TestUnitBuildRequiresReleasedRevision:
    def test_build_on_working_revision_rejected(self, api):
        """PRD 3.11: "A `QualityEngineer` marks a planned unit built, but only when the
        pinned `part_revision_id` revision is in `RELEASED` state; building against a
        non-released revision is rejected with `ERR_REVISION_NOT_RELEASED`."

        Design: Difficulty/cross_entity_state_dependency/serialized_unit_build_requires_released_revision
        """
        part = fixtures.create_part("MAKE", base_cost_cents=100)
        rev = fixtures.create_revision(part["id"])  # WORKING, never released
        unit = get_success_data(api.create_serialized_unit(
            factories.create_serialized_unit_payload(rev["id"]), QUALITY))
        resp = api.build_serialized_unit(unit["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_REVISION_NOT_RELEASED)

    def test_build_on_released_revision_succeeds(self, api):
        """PRD 3.11: "A `QualityEngineer` marks a planned unit built, but only when the
        pinned `part_revision_id` revision is in `RELEASED` state".
        PRD 3.11: "The unit then advances `PLANNED → BUILT`."

        Design: Difficulty/cross_entity_state_dependency/serialized_unit_build_requires_released_revision
        """
        _part, rev, _leaf = fixtures.create_released_make_part()
        unit = get_success_data(api.create_serialized_unit(
            factories.create_serialized_unit_payload(rev["id"]), QUALITY))
        built = validate_success(api.build_serialized_unit(unit["id"], QUALITY))
        assert built["build_status"] == "BUILT", built


# ===========================================================================
# resource_temporal_overlap
# ===========================================================================
class TestDeviationWindowOverlap:
    def test_touching_windows_collide_on_shared_boundary(self, api):
        """PRD 3.10: "A grant is blocked if any other granted deviation for the same
        `part_id` and the same `defect_code` has a window that overlaps this one,
        treating both endpoints of the `effective_from`-to-`effective_to` window as
        inclusive; an overlap is rejected with `ERR_DEVIATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/deviation_inclusive_window_overlap
        """
        part = fixtures.create_part("MAKE", base_cost_cents=100)
        fixtures.create_granted_deviation(
            part["id"], "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z",
            defect_code="DIMENSIONAL", max_units=5)
        dev2 = fixtures.create_submitted_deviation(
            part["id"], "2026-06-30T00:00:00Z", "2026-12-31T00:00:00Z",
            defect_code="DIMENSIONAL", max_units=5)
        resp = api.grant_deviation(dev2["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_DEVIATION_WINDOW_OVERLAP)

    def test_overlap_check_is_scoped_to_same_defect_code(self, api):
        """PRD 3.10: "A grant is blocked if any other granted deviation for the same
        `part_id` and the same `defect_code` has a window that overlaps this one,
        treating both endpoints of the `effective_from`-to-`effective_to` window as
        inclusive; an overlap is rejected with `ERR_DEVIATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/deviation_inclusive_window_overlap
        """
        part = fixtures.create_part("MAKE", base_cost_cents=100)
        fixtures.create_granted_deviation(
            part["id"], "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z",
            defect_code="DIMENSIONAL", max_units=5)
        # Same overlapping window but a DIFFERENT defect_code -> no collision.
        dev2 = fixtures.create_submitted_deviation(
            part["id"], "2026-06-30T00:00:00Z", "2026-12-31T00:00:00Z",
            defect_code="COSMETIC", max_units=5)
        granted = validate_success(api.grant_deviation(dev2["id"], QUALITY))
        assert granted["status"] == "GRANTED", granted


class TestRevisionExclusiveOccupancy:
    def _build(self):
        """A WORKING revision attached to one DRAFT ECO; a second DRAFT ECO ready."""
        part = fixtures.create_part("PHANTOM")
        rev = fixtures.create_revision(part["id"])
        # eco1 attaches the revision
        ecr1 = fixtures.create_approved_ecr(part["id"])
        eco1 = get_success_data(api_client.create_change_order(
            factories.create_change_order_payload(
                ecr1["id"], "2026-03-01T00:00:00Z", required_approvals=1), CHANGE_ADMIN))
        get_success_data(api_client.add_affected_item(
            eco1["id"], factories.create_affected_item_payload(rev["id"]), CHANGE_ADMIN))
        # eco2 from a different approved ECR
        ecr2 = fixtures.create_approved_ecr(part["id"], reason_code="COST_REDUCTION")
        eco2 = get_success_data(api_client.create_change_order(
            factories.create_change_order_payload(
                ecr2["id"], "2026-04-01T00:00:00Z", required_approvals=1), CHANGE_ADMIN))
        return rev, eco1, eco2

    def test_second_attach_of_governed_revision_rejected(self, api):
        """PRD 3.5: "A revision may be governed by at most one non-terminal order at a
        time; attaching a revision whose `governing_change_order_id` already points to a
        non-terminal order is rejected with `ERR_REVISION_ALREADY_GOVERNED`."

        Design: Difficulty/resource_temporal_overlap/revision_exclusive_occupancy_by_eco
        """
        rev, _eco1, eco2 = self._build()
        resp = api.add_affected_item(
            eco2["id"], factories.create_affected_item_payload(rev["id"]), CHANGE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_REVISION_ALREADY_GOVERNED)

    def test_first_attach_sets_governing_change_order(self, api):
        """PRD 3.5: "Attaching an item sets that revision's `governing_change_order_id`
        to this order."

        Design: Difficulty/resource_temporal_overlap/revision_exclusive_occupancy_by_eco
        """
        rev, eco1, _eco2 = self._build()
        r = validate_success(api.get_revision(rev["id"], DESIGNER))
        assert r["governing_change_order_id"] == eco1["id"], r


# ===========================================================================
# compensating_invariant
# ===========================================================================
class TestEcoCancelConservesReleasedCount:
    def _build_in_approval(self):
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=100)
        get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
        eco, _task_ids = fixtures.create_in_approval_eco(
            part["id"], rev["id"], effectivity_date="2026-02-01T00:00:00Z",
            required_approvals=1, assignees=["ap1"])
        return part, rev, eco

    def test_cancel_detaches_affected_item_without_release(self, api):
        """PRD 3.7: "Cancellation detaches every affected item by clearing each linked
        revision's `governing_change_order_id`, so those revisions are free to be
        governed by a future order; when cancelling from `IN_APPROVAL`, the detach
        additionally sets each affected item's `pinned` back to false."

        Design: Difficulty/compensating_invariant/eco_cancel_conserves_released_count
        """
        part, rev, eco = self._build_in_approval()
        cancelled = validate_success(api.cancel_change_order(eco["id"], CHANGE_ADMIN))
        assert cancelled["status"] == "CANCELLED", cancelled
        r = validate_success(api.get_revision(rev["id"], DESIGNER))
        assert r["governing_change_order_id"] is None, r
        assert r["lifecycle_state"] == "IN_REVIEW", r

    def test_cancel_conserves_released_revision_count(self, api):
        """PRD 3.7: "This compensating detach conserves the count of released revisions
        — cancelling an order never leaves a phantom governance link behind."

        Design: Difficulty/compensating_invariant/eco_cancel_conserves_released_count
        """
        part, _rev, eco = self._build_in_approval()
        validate_success(api.cancel_change_order(eco["id"], CHANGE_ADMIN))
        p = validate_success(api.get_part(part["id"], DESIGNER))
        assert p["released_revision_id"] is None, p


class TestDeviationGrantExpireConservesConforming:
    def _build(self):
        """A part with one BUILT unit flagged NONCONFORMING and a SUBMITTED deviation
        whose window has already passed so it can be expired after grant."""
        part, rev, _leaf = fixtures.create_released_make_part()
        unit = fixtures.create_nonconforming_unit(rev["id"])
        dev = fixtures.create_submitted_deviation(
            part["id"], "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
            defect_code="FUNCTIONAL", max_units=3)
        return part, unit, dev

    def test_grant_waives_unit_and_counts_coverage(self, api):
        """PRD 3.10: "For each taken unit, the unit's `deviation_id` is set to this
        deviation, its `conformance_status` becomes `WAIVED`, and the deviation's
        `covered_unit_count` is incremented accordingly."

        Design: Difficulty/compensating_invariant/deviation_grant_expire_conserves_conforming_count
        """
        part, unit, dev = self._build()
        granted = validate_success(api.grant_deviation(dev["id"], QUALITY))
        assert granted["covered_unit_count"] == 1, granted
        u = validate_success(api.get_serialized_unit(unit["id"], QUALITY))
        assert u["conformance_status"] == "WAIVED", u

    def test_expire_reverts_unit_and_zeroes_coverage(self, api):
        """PRD 3.10: "for each serialized unit whose `deviation_id` equals this
        deviation and whose `conformance_status` is `WAIVED`, the unit's
        `conformance_status` returns to `NONCONFORMING`, its `deviation_id` is cleared,
        and the deviation's `covered_unit_count` is decremented."

        Design: Difficulty/compensating_invariant/deviation_grant_expire_conserves_conforming_count
        """
        part, unit, dev = self._build()
        validate_success(api.grant_deviation(dev["id"], QUALITY))
        # clock is at 2026-01-03 (set by create_released_make_part); window ended 2026-01-02.
        validate_success(api.expire_deviation(dev["id"], QUALITY))
        u = validate_success(api.get_serialized_unit(unit["id"], QUALITY))
        assert u["conformance_status"] == "NONCONFORMING", u
        assert u["deviation_id"] is None, u
        final_dev = validate_success(api.get_deviation(dev["id"], QUALITY))
        assert final_dev["covered_unit_count"] == 0, final_dev
