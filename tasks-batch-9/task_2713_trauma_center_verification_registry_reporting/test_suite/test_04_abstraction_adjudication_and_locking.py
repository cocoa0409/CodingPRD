"""Two independent dimensions on one case, and the gate the lock reads across entities.

A registry case tracks its abstraction and its triage adjudication separately: neither
transition may disturb the other, and the lock is only legal once the child abstraction
has been accepted by a second person.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    AbstractionStatus,
    DesignationLevel,
    InclusionReason,
    InclusionStatus,
    TierCode,
    TriageReviewStatus,
    ValidationStatus,
    assert_instant,
    fixtures as fx,
    make_trauma_program_manager_headers,
)


def _case_with_submitted_abstraction(api: ApiClient):
    """A case whose abstraction is filed but not yet adjudicated."""
    fx.anchor_clock(api)
    center, tier = fx.center_with_tier(
        api,
        name="Harbor Point Trauma",
        state_code="WA",
        designation_level=DesignationLevel.LEVEL_I,
        tier_code=TierCode.TIER_1_FULL,
    )
    case, abstraction = fx.case_abstracted(
        api,
        center["id"],
        tier["id"],
        mrn="MRN-P1",
        arrival_at="2026-07-25T08:00:00Z",
        injury_severity_score=22,
        los_hours=80.00,
        iss_abstracted=22,
        gcs_arrival=11,
        mechanism_code="MVC",
        ed_departure_at="2026-07-25T10:30:00Z",
    )
    return center, case, abstraction


def _granite_ridge_case_with_submitted_abstraction(api: ApiClient):
    """A second center's case, filed and awaiting validation before it can be locked."""
    fx.anchor_clock(api)
    center, tier = fx.center_with_tier(
        api,
        name="Granite Ridge Trauma",
        state_code="NH",
        designation_level=DesignationLevel.LEVEL_II,
        tier_code=TierCode.TIER_1_FULL,
    )
    case, abstraction = fx.case_abstracted(
        api,
        center["id"],
        tier["id"],
        mrn="MRN-G1",
        arrival_at="2026-07-20T04:00:00Z",
        injury_severity_score=26,
        los_hours=96.00,
        iss_abstracted=26,
        gcs_arrival=9,
        mechanism_code="FALL",
        ed_departure_at="2026-07-20T07:00:00Z",
    )
    return center, case, abstraction


class TestIndependentCaseDimensions:
    """The abstraction ladder and the triage adjudication do not interleave."""

    def test_the_triage_adjudication_leaves_the_abstraction_state_untouched(
        self, api: ApiClient
    ) -> None:
        """A case sitting at ABSTRACTED stays there while its triage is decided.

        Design: Difficulty/non_linear_state_machine/registry_case_abstraction_and_triage_dimensions_advance_independently
        """
        _, case, abstraction = _case_with_submitted_abstraction(api)
        assert case["abstraction_status"] == AbstractionStatus.ABSTRACTED
        assert case["triage_review_status"] == TriageReviewStatus.UNREVIEWED

        after_triage = fx.triage_review(api, case, TriageReviewStatus.APPROPRIATE)
        assert after_triage["triage_review_status"] == TriageReviewStatus.APPROPRIATE
        assert after_triage["abstraction_status"] == AbstractionStatus.ABSTRACTED, (
            "the triage decision does not advance the abstraction dimension"
        )
        assert (
            fx.get_abstraction(api, case["id"], abstraction["id"])["validation_status"]
            == ValidationStatus.SUBMITTED
        )

    def test_validating_the_abstraction_preserves_the_triage_outcome(
        self, api: ApiClient
    ) -> None:
        """Validation moves only the abstraction dimension, and the lock stamps the case.

        Design: Difficulty/non_linear_state_machine/registry_case_abstraction_and_triage_dimensions_advance_independently
        """
        _, case, abstraction = _case_with_submitted_abstraction(api)
        fx.triage_review(api, case, TriageReviewStatus.APPROPRIATE)

        fx.validate_abstraction(api, abstraction)
        validated = fx.get_case(api, case["id"])
        assert validated["abstraction_status"] == AbstractionStatus.VALIDATED
        assert validated["triage_review_status"] == TriageReviewStatus.APPROPRIATE

        locked = fx.lock_case(api, case)
        assert locked["abstraction_status"] == AbstractionStatus.LOCKED
        assert locked["triage_review_status"] == TriageReviewStatus.APPROPRIATE
        assert_instant(locked["locked_at"], "2026-08-01T00:00:00Z", "locked_at")
        assert locked["effective_iss"] == 22


class TestLockRequiresValidatedAbstraction:
    """Locking a case reads the state of a different entity than the one being written."""

    def test_locking_is_refused_while_the_abstraction_is_only_submitted(
        self, api: ApiClient
    ) -> None:
        """The parent cannot be frozen while its child is still awaiting adjudication.

        Design: Difficulty/cross_entity_state_dependency/case_lock_requires_child_abstraction_in_validated_state
        """
        center, case, abstraction = _granite_ridge_case_with_submitted_abstraction(api)
        assert (
            fx.get_abstraction(api, case["id"], abstraction["id"])["validation_status"]
            == ValidationStatus.SUBMITTED
        )

        refused = api.lock_registry_case(
            case["id"], make_trauma_program_manager_headers(center["id"])
        )
        validate_error(refused, E.ABSTRACTION_NOT_VALIDATED, 409)

        untouched = fx.get_case(api, case["id"])
        assert untouched["abstraction_status"] == AbstractionStatus.ABSTRACTED
        assert untouched["locked_at"] is None

    def test_the_same_lock_request_succeeds_once_the_abstraction_is_validated(
        self, api: ApiClient
    ) -> None:
        """Nothing about the request changes; only the child's state does.

        Design: Difficulty/cross_entity_state_dependency/case_lock_requires_child_abstraction_in_validated_state
        """
        center, case, abstraction = _granite_ridge_case_with_submitted_abstraction(api)
        validate_error(
            api.lock_registry_case(
                case["id"], make_trauma_program_manager_headers(center["id"])
            ),
            E.ABSTRACTION_NOT_VALIDATED,
            409,
        )

        fx.validate_abstraction(api, abstraction)
        assert (
            fx.get_case(api, case["id"])["abstraction_status"]
            == AbstractionStatus.VALIDATED
        )

        accepted = api.lock_registry_case(
            case["id"], make_trauma_program_manager_headers(center["id"])
        )
        locked = validate_success(accepted, 200)
        assert locked["abstraction_status"] == AbstractionStatus.LOCKED
        assert_instant(locked["locked_at"], "2026-08-01T00:00:00Z", "locked_at")
        assert locked["effective_iss"] == 26
        assert locked["inclusion_status"] == InclusionStatus.INCLUDED
        assert locked["inclusion_reason"] == InclusionReason.MEETS_INCLUSION_CRITERIA
