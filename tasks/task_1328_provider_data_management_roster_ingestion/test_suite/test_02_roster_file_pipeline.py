"""Roster file pipeline: state guards on commit, branching reject paths, supersede
preconditions, segregation of duties, and immediate read-after-write (PRD §3.2, §3.4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    commit_file,
    create_source,
    drive_file_to_state,
    make_intake_operator_headers,
    register_file,
    set_clock,
    setup_committed_empty_file,
    setup_validated_empty_file,
    validate_error,
    validate_success,
)


class TestCommitStateGuard:
    def test_commit_from_received_rejected(self, api, intake_operator_2_headers):
        """PRD §3.4: "Its checks are evaluated in a fixed order. The file must stand in
        `VALIDATED`, or the call fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/roster_file_commit_from_received_invalid
        """
        set_clock()
        source = create_source(source_code="S1", precedence_rank=1)
        f = register_file(source["id"], external_file_ref="s1f", checksum="s1c")
        res = api.commit_roster_file(
            f["id"],
            {"expected_roster_file_version": f["version"]},
            intake_operator_2_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_roster_file(f["id"], intake_operator_2_headers))
        assert after["status"] == "RECEIVED", (
            f"File must remain RECEIVED after a rejected commit, got {after['status']}"
        )


class TestBranchingRejectPaths:
    def test_reject_from_received(self, api, intake_operator_headers):
        """PRD §3.2: "A file that will never be committed can be rejected outright by the
        intake operator from any pre-commit state, landing in the terminal `REJECTED`
        state. The cascade depends on where the file stood: from `RECEIVED` there are no
        rows to touch"

        Design: Difficulty/non_linear_state_machine/roster_file_branching_reject_paths
        """
        set_clock()
        source = create_source(source_code="SRC_B1", precedence_rank=1)
        f = register_file(source["id"], external_file_ref="f1", checksum="c001")
        res = api.reject_roster_file(f["id"], intake_operator_headers)
        rejected = validate_success(res)
        assert rejected["status"] == "REJECTED"
        after = validate_success(api.get_roster_file(f["id"], intake_operator_headers))
        assert after["status"] == "REJECTED"

    def test_reject_from_normalized(self, api, intake_operator_headers):
        """PRD §3.2: "A file that will never be committed can be rejected outright by the
        intake operator from any pre-commit state, landing in the terminal `REJECTED`
        state." and "from `NORMALIZED`, every remaining non-terminal row transitions to
        `REJECTED`".

        Design: Difficulty/non_linear_state_machine/roster_file_branching_reject_paths
        """
        set_clock()
        source = create_source(source_code="SRC_B2", precedence_rank=1)
        f = register_file(
            source["id"], external_file_ref="f2", declared_row_count=0, checksum="c002"
        )
        drive_file_to_state(f["id"], "NORMALIZED")
        res = api.reject_roster_file(f["id"], intake_operator_headers)
        rejected = validate_success(res)
        assert rejected["status"] == "REJECTED"
        after = validate_success(api.get_roster_file(f["id"], intake_operator_headers))
        assert after["status"] == "REJECTED"
        assert after["rejected_row_count"] == after["parsed_row_count"] == 0


class TestSupersedePrecondition:
    def test_supersede_without_replacement_rejected(self, api, data_steward_headers):
        """PRD §3.4: "The precondition is that a replacement file for the same
        `roster_source_id` exists in `VALIDATED` or `COMMITTED` state — otherwise the
        call is rejected with `ERR_NO_REPLACEMENT_FILE` (HTTP 409)."

        Design: Corner/state_machines/roster_file_supersede_requires_replacement
        """
        set_clock()
        _, committed = setup_committed_empty_file(
            source_overrides={"source_code": "S6", "precedence_rank": 1}
        )
        res = api.supersede_roster_file(committed["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_NO_REPLACEMENT_FILE)


class TestSegregationOfDutiesOnCommit:
    def test_commit_by_registering_user_rejected(self, api):
        """PRD §2.8: "the operator who registers a roster file may not be the one who
        commits it: registration records the registrant's opaque user id, and a commit
        attempt carrying the same id is rejected with `ERR_SOD_SAME_USER` (HTTP 403)."

        Design: Corner/rbac/sod_commit_by_registering_user_blocked
        """
        set_clock()
        _, f = setup_validated_empty_file(
            source_overrides={"source_code": "RB4", "precedence_rank": 1},
            file_overrides={"external_file_ref": "rb4f", "checksum": "rb4c"},
            registrant_user_id="op_intake_1",
        )
        res = api.commit_roster_file(
            f["id"],
            {"expected_roster_file_version": f["version"]},
            make_intake_operator_headers("op_intake_1"),
        )
        validate_error(res, ApiErrorId.ERR_SOD_SAME_USER)

    def test_sod_fires_before_stale_version(self, api):
        """PRD §2.6: "After state legality come the segregation-of-duties checks of
        §2.8, then the optimistic-concurrency checks of §2.7, and then the endpoint's
        remaining business rules, each family of which declares its own internal order
        in §3 — for example, on file commit the duty check surfaces before the
        stale-version check, which in turn surfaces before the unresolved-row-conflict
        check."

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_stale_version_on_commit
        """
        set_clock()
        _, f = setup_validated_empty_file(
            source_overrides={"source_code": "SRC_P", "precedence_rank": 1},
            file_overrides={"external_file_ref": "pf1", "checksum": "p001"},
            registrant_user_id="op_intake_1",
        )
        # Same user as registrant AND a deliberately stale version: SoD must win.
        res = api.commit_roster_file(
            f["id"],
            {"expected_roster_file_version": f["version"] + 1000},
            make_intake_operator_headers("op_intake_1"),
        )
        validate_error(res, ApiErrorId.ERR_SOD_SAME_USER)

    def test_file_stays_validated_after_sod_rejection(self, api, intake_operator_headers):
        """PRD §3.4: "The committing operator's opaque user id must differ from the
        registrant's, per §2.8, or the call fails with `ERR_SOD_SAME_USER`." A rejected
        commit performs no transition, so the file remains in `VALIDATED`.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_stale_version_on_commit
        """
        set_clock()
        _, f = setup_validated_empty_file(
            source_overrides={"source_code": "SRC_P2", "precedence_rank": 1},
            file_overrides={"external_file_ref": "pf2", "checksum": "p002"},
            registrant_user_id="op_intake_1",
        )
        validate_error(
            api.commit_roster_file(
                f["id"],
                {"expected_roster_file_version": f["version"] + 1000},
                make_intake_operator_headers("op_intake_1"),
            ),
            ApiErrorId.ERR_SOD_SAME_USER,
        )
        after = validate_success(api.get_roster_file(f["id"], intake_operator_headers))
        assert after["status"] == "VALIDATED", (
            f"File must remain VALIDATED after a rejected commit, got {after['status']}"
        )


class TestCommitImmediateConsistency:
    def test_commit_response_carries_final_state(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."
        PRD §3.4: "The file itself settles its final `committed_row_count` — the number
        of rows whose identity resolution ended `MATCHED` or `NEW_PROVIDER` — alongside
        its final `rejected_row_count`, increments its own `version` by one, and rests
        in the terminal `COMMITTED` state."

        Design: Corner/consistency_model/commit_effects_visible_in_same_response
        """
        set_clock()
        _, f = setup_validated_empty_file(
            source_overrides={"source_code": "CM1", "precedence_rank": 1},
            file_overrides={"external_file_ref": "cm1f", "checksum": "cm1c"},
        )
        committed = commit_file(f["id"], committer_user_id="op_intake_2")
        assert committed["status"] == "COMMITTED", (
            f"Commit response must carry status COMMITTED, got {committed['status']}"
        )
        assert committed["committed_row_count"] == 0, (
            "A zero-row file commits with committed_row_count 0, "
            f"got {committed['committed_row_count']}"
        )


class TestNestedRetrieval:
    def test_rows_of_unknown_file_not_found(self, api, intake_operator_headers):
        """PRD §2.9: "Path identifiers are validated in sequential left-to-right order:
        the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first
        `id` in the path that does not correspond to an existing resource, or that
        exists but does not belong to the named parent chain."

        Design: Corner/entities/roster_row_wrong_parent_returns_not_found
        """
        set_clock()
        source = create_source(source_code="E6", precedence_rank=1)
        register_file(source["id"], external_file_ref="e6a", checksum="e6a")
        res = api.list_file_roster_rows(NON_EXISTENT_UUID, intake_operator_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)
