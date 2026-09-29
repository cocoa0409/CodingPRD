"""One request breaking two rules at once, six rungs of the ladder apart.

PRD §2.11: "Validations are evaluated in one strict ascending priority order across
the whole service. The first violated rule wins, its error is returned, and no later
rule is evaluated — so a request that breaks three rules at once produces exactly
one, fully determined error code."
"""
import pytest
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    create_hcu_study_payload,
    create_transfer_application_payload,
    create_water_right_payload,
    decide_payload,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    ANALYST,
    DECIDER,
    activate_right,
    add_injury_analysis,
    add_use_record,
    create_water_right,
    read_application,
    read_right,
    right_version,
    set_clock,
    setup_certified_right,
    setup_documented_right,
    setup_draft_application,
    submit_application,
)

CLOCK = "2026-03-01T00:00:00Z"


def _activated_second_right(claimant_id, right_number="WR-2198-002"):
    right = create_water_right(claimant_id, right_number=right_number)
    add_use_record(
        right["id"],
        2025,
        reported_diversion_af=300.000,
        irrigated_acres=100.00,
        verification_source="METER",
    )
    return activate_right(right["id"])


class TestAuthorizationRunsBeforeThePathIsResolved:
    """PRD §2.1 — the role gate cannot be used to probe the catalogue.

    A study may only be run by an analyst, and the adjudicator asks for one on a
    right that does not exist. Two rules are broken; only the earlier one speaks.
    """

    def test_the_wrong_role_on_a_missing_right_is_a_role_failure(self):
        """PRD §2.1: "If the headers are well formed but the named role is not
        authorized for the endpoint being called, the rejection is
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403). These two checks are the first and
        second things this service ever evaluates, in that order."

        PRD §3.3: "A study declares a `method` of either `DIVERSION_BASED` or
        `CIR_BASED`" and only the analyst may run one — PRD §3.3: "only a
        `WaterRightsAnalyst` may run one — it is the single operation the basin
        adjudicator is barred from despite otherwise sharing every
        right-documentation capability." Because authorization precedes
        path-parameter existence on the ladder of PRD §2.11, the 404 never surfaces.

        Design: Corner/validations/val_priority_role_check_precedes_path_existence
        """
        set_clock(CLOCK)

        response = api_client.create_hcu_study(
            NON_EXISTENT_UUID, create_hcu_study_payload(2023, 2025), ADJUDICATOR
        )

        validate_error(
            response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )


class TestExistenceRunsBeforeTheBodyIsParsed:
    """PRD §2.11 — a bad route cannot be masked by a bad body.

    The path names a right that does not exist and the body is invalid twice over:
    the `method` is outside the enum and the study period runs backwards.
    """

    def test_an_unresolvable_path_outranks_a_doubly_malformed_body(self):
        """PRD §2.6: "Path parameters are resolved strictly left to right, and the
        error returned belongs to the leftmost segment that fails to resolve. A
        request naming a right that does not exist fails with
        `ERR_WATER_RIGHT_NOT_FOUND` (HTTP 404) before anything nested beneath that
        right is examined."

        PRD §2.11 puts "path-parameter existence" above "request-body
        well-formedness (`ERR_INVALID_REQUEST`)" in the one strict ascending order,
        so neither the bogus method nor the inverted window is ever reported.

        Design: Corner/validations/val_priority_path_existence_precedes_request_shape
        """
        set_clock(CLOCK)

        response = api_client.create_hcu_study(
            NON_EXISTENT_UUID,
            create_hcu_study_payload(2025, 2023, method="GUESSWORK"),
            ANALYST,
        )

        validate_error(
            response, ApiErrorId.ERR_WATER_RIGHT_NOT_FOUND.value, expected_status=404
        )


class TestForeignKeysAreResolvedBeforeUniquenessIsTested:
    """PRD §2.11 — a body naming an unknown claimant and a taken right number.

    Both violations live in the same body. The referential one is earlier on the
    ladder, so the duplicate right number is never reached.
    """

    def test_an_unknown_claimant_outranks_a_duplicate_right_number(self):
        """PRD §2.11: "The ladder from the top is: header presence and role
        membership (`ERR_UNAUTHENTICATED`, then `ERR_ROLE_NOT_PERMITTED`);
        path-parameter existence, then nested-parent ownership of a sub-resource
        identifier; claimant ownership of the target resource
        (`ERR_NOT_RESOURCE_OWNER`); request-body well-formedness
        (`ERR_INVALID_REQUEST`); body foreign-key existence; then the
        domain-specific referential, uniqueness, concurrency, state, safety,
        temporal, constraint and fiscal families in that sequence."

        Body foreign-key existence sits above the uniqueness family, so the answer
        is `ERR_CLAIMANT_NOT_FOUND` and no second right is written.

        Design: Corner/validations/val_priority_body_foreign_key_precedes_uniqueness
        """
        bundle = setup_documented_right(CLOCK)
        taken_number = bundle["right"]["right_number"]

        response = api_client.create_water_right(
            create_water_right_payload(NON_EXISTENT_UUID, right_number=taken_number),
            ANALYST,
        )

        validate_error(
            response, ApiErrorId.ERR_CLAIMANT_NOT_FOUND.value, expected_status=404
        )
        rights, meta = validate_paginated(api_client.list_water_rights(ANALYST))
        assert meta["total_count"] == 1
        assert [right["id"] for right in rights] == [bundle["right"]["id"]]


class TestScopeCoherenceRunsBeforeStudyOwnership:
    """PRD §3.4 — the two nearest business rules on the drafting endpoint.

    A `CHANGE_OF_USE` draft omits its mandatory `proposed_purpose_of_use` and, at
    the same time, cites a certified study belonging to a different right. One
    priority step separates the two failures.
    """

    def test_the_missing_scope_field_outranks_the_borrowed_study(self):
        """PRD §3.4: "Scope coherence is checked before the study-ownership check."

        PRD §3.4: "`proposed_purpose_of_use`, drawn from the same five-value set as a
        right's authorized purpose, must be present exactly when the type is
        `CHANGE_OF_USE` or `COMBINED`" and "Presence where absence is required is as
        much a failure as the reverse, and either direction is
        `ERR_APPLICATION_SCOPE_INCOMPLETE` (HTTP 422)." The borrowed study would
        otherwise be `ERR_STUDY_RIGHT_MISMATCH`, and no application row is written.

        Design: Corner/validations/val_priority_scope_completeness_precedes_study_ownership
        """
        bundle = setup_certified_right(
            CLOCK, use_years=(2025,), study_start_year=2025, study_end_year=2025
        )
        other_right = _activated_second_right(bundle["claimant"]["id"])
        payload = create_transfer_application_payload(
            other_right["id"], bundle["study"]["id"], 10.00
        )
        payload.pop("proposed_purpose_of_use")

        response = api_client.create_transfer_application(payload, ANALYST)

        validate_error(
            response,
            ApiErrorId.ERR_APPLICATION_SCOPE_INCOMPLETE.value,
            expected_status=422,
        )
        _, meta = validate_paginated(api_client.list_transfer_applications(ANALYST))
        assert meta["total_count"] == 0


class TestConcurrencyRunsBeforeLifecycleState:
    """PRD §2.11 — a lost update is reported as a lost update.

    The same submit call is replayed with the same `expected_water_right_version`.
    By then the application has left `DRAFT` and the right's version has moved, so
    two rules are broken at once.
    """

    def _submitted_once(self):
        bundle = setup_draft_application(100.00, CLOCK)
        add_injury_analysis(
            bundle["application"]["id"],
            "SEASONAL_AVERAGE",
            0.00,
            return_flow_credit_af=78.00,
        )
        bundle["stale_version"] = right_version(bundle["right"]["id"])
        bundle["application"] = submit_application(
            bundle["application"]["id"], bundle["right"]["id"]
        )
        return bundle

    def test_the_stale_right_version_outranks_the_illegal_transition(self):
        """PRD §2.11: "The concurrency checks sit above every state and business
        check, so a stale version declaration surfaces before the service considers
        whether the transition was even legal."

        PRD §3.4: "Five gates apply, and their relative order is fixed: the declared
        version must match the right's current `version`, or the submission is
        `ERR_STALE_RIGHT_VERSION` (HTTP 412); the application must be in `DRAFT` and
        the relied-upon study must be in `CERTIFIED`, since a `DRAFT` or `SUPERSEDED`
        study cannot support a submission and either failure is `ERR_INVALID_STATE`
        (HTTP 409)". The rejected replay must also move nothing at all.

        Design: Corner/validations/val_priority_stale_parent_version_precedes_state_check
        """
        bundle = self._submitted_once()
        right_after_first_submit = read_right(bundle["right"]["id"])

        response = api_client.submit_transfer_application(
            bundle["application"]["id"], bundle["stale_version"], ANALYST
        )

        validate_error(
            response, ApiErrorId.ERR_STALE_RIGHT_VERSION.value, expected_status=412
        )
        right = read_right(bundle["right"]["id"])
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["version"] == right_after_first_submit["version"]
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "SUBMITTED"
        assert application["escrowed_af"] == pytest.approx(100.00, abs=0.01)
        assert application["version"] == bundle["application"]["version"]


class TestLifecycleStateRunsBeforeTheEvidentiaryPrerequisite:
    """PRD §2.11 — a disposition attempted on a `DRAFT` application.

    The application is not merely in the wrong state; it also has no injury
    analysis whatsoever, which is the other thing a disposition needs.
    """

    def test_the_wrong_state_outranks_the_missing_injury_analysis(self):
        """PRD §2.11: "The ladder from the top is: header presence and role
        membership (`ERR_UNAUTHENTICATED`, then `ERR_ROLE_NOT_PERMITTED`);
        path-parameter existence, then nested-parent ownership of a sub-resource
        identifier; claimant ownership of the target resource
        (`ERR_NOT_RESOURCE_OWNER`); request-body well-formedness
        (`ERR_INVALID_REQUEST`); body foreign-key existence; then the
        domain-specific referential, uniqueness, concurrency, state, safety,
        temporal, constraint and fiscal families in that sequence."

        The state family precedes the constraint family, so a `DRAFT` application
        answers `ERR_INVALID_STATE` and never `ERR_INJURY_ANALYSIS_MISSING`, and
        nothing about the application or the right moves.

        Design: Corner/validations/val_priority_state_check_precedes_analysis_prerequisite
        """
        bundle = setup_draft_application(100.00, CLOCK)

        response = api_client.decide_transfer_application(
            bundle["application"]["id"],
            decide_payload("APPROVE", decision_note="Premature decision attempt."),
            DECIDER,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "DRAFT"
        assert application["decided_by_user_id"] is None
        assert application["version"] == bundle["application"]["version"]
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(195.00, abs=0.01)
