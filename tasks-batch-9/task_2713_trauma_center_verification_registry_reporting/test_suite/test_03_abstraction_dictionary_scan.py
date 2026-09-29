"""The dictionary scan, its escalating band multiplier, and the resubmission token.

The band multiplier applied to an abstraction is read from the compliance score as it
stands before that abstraction's own penalty is applied, so three identically wrong
abstractions cost 6.00, 9.00 and 12.00 points in that order.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    AbstractionStatus,
    BAND_MULTIPLIER_HIGH,
    BAND_MULTIPLIER_LOW,
    BAND_MULTIPLIER_MID,
    DictionaryFieldName,
    DesignationLevel,
    RuleSeverity,
    SUPERSEDED_BY_RESUBMISSION,
    TierCode,
    ValidationStatus,
    assert_abstraction_record,
    assert_decimal,
    factories as f,
    fixtures as fx,
    make_registry_abstractor_headers,
)


def _four_rule_dictionary(api: ApiClient) -> None:
    """Two major range rules and two minor rules, weighing six points in total."""
    fx.create_rule(
        api,
        f.range_rule_payload(
            field_name=DictionaryFieldName.GCS_ARRIVAL,
            min_value=3,
            max_value=15,
            severity=RuleSeverity.MAJOR,
        ),
    )
    fx.create_rule(
        api,
        f.range_rule_payload(
            field_name=DictionaryFieldName.ISS_ABSTRACTED,
            min_value=0,
            max_value=75,
            severity=RuleSeverity.MAJOR,
        ),
    )
    fx.create_rule(
        api,
        f.conformance_rule_payload(
            field_name=DictionaryFieldName.MECHANISM_CODE,
            allowed_codes=["MVC", "FALL", "GSW"],
            severity=RuleSeverity.MINOR,
        ),
    )
    fx.create_rule(
        api,
        f.required_rule_payload(
            field_name=DictionaryFieldName.ED_DEPARTURE_AT,
            severity=RuleSeverity.MINOR,
        ),
    )


def _three_identically_wrong_abstractions(
    api: ApiClient,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """One center whose three abstractions each break all four rules."""
    fx.anchor_clock(api)
    _four_rule_dictionary(api)
    center, tier = fx.center_with_tier(
        api,
        name="Summit Ridge Trauma",
        state_code="CO",
        designation_level=DesignationLevel.LEVEL_I,
        tier_code=TierCode.TIER_1_FULL,
    )
    records = []
    for mrn in ("MRN-D1", "MRN-D2", "MRN-D3"):
        case = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn=mrn,
            arrival_at="2026-07-24T08:00:00Z",
            injury_severity_score=18,
            los_hours=72.00,
        )
        records.append(
            fx.submit_abstraction(
                api,
                case,
                iss_abstracted=90,
                gcs_arrival=20,
                mechanism_code="TRAIN",
                ed_departure_at=None,
            )
        )
    return center, records


class TestBandMultiplierReadsPrePenaltyScore:
    """Each scan is charged at the band the score occupied before it was charged."""

    def test_the_three_scans_are_charged_at_escalating_band_multipliers(
        self, api: ApiClient
    ) -> None:
        """The same four errors cost 6.00, then 9.00, then 12.00 points.

        Design: Difficulty/combinatorial_formula/dictionary_band_multiplier_reads_prepenalty_compliance_score
        """
        _, records = _three_identically_wrong_abstractions(api)

        expected = [
            (BAND_MULTIPLIER_HIGH, 6.00),
            (BAND_MULTIPLIER_MID, 9.00),
            (BAND_MULTIPLIER_LOW, 12.00),
        ]
        for record, (multiplier, penalty) in zip(records, expected):
            assert_abstraction_record(record)
            assert record["dictionary_error_count"] == 4, (
                "all four declared rules are broken by every abstraction"
            )
            assert record["band_multiplier_used"] == multiplier
            assert_decimal(record["applied_penalty_points"], penalty, "applied_penalty_points")

    def test_the_center_compliance_score_lands_on_seventy_three(
        self, api: ApiClient
    ) -> None:
        """100.00 less 6.00, 9.00 and 12.00 is 73.00, not the flat 82.00.

        Design: Difficulty/combinatorial_formula/dictionary_band_multiplier_reads_prepenalty_compliance_score
        """
        center, _ = _three_identically_wrong_abstractions(api)

        assert_decimal(
            fx.get_center(api, center["id"])["registry_compliance_score"],
            73.00,
            "registry_compliance_score",
        )


class TestAbstractionResubmissionToken:
    """A resubmission must carry the case version the earlier submission produced."""

    def test_a_stale_case_version_is_refused_and_the_fresh_one_supersedes(
        self, api: ApiClient
    ) -> None:
        """Replaying the opening version fails; the current version supersedes the first record.

        Design: Corner/complexity_layers/stale_case_version_rejects_the_resubmitted_abstraction
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Grindstone Trauma",
            state_code="MO",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        case = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-GS1",
            arrival_at="2026-07-25T13:00:00Z",
            injury_severity_score=24,
            los_hours=58.00,
        )
        opening_version = case["version"]
        first = fx.submit_abstraction(
            api,
            case,
            iss_abstracted=24,
            gcs_arrival=8,
            mechanism_code="MVC",
            ed_departure_at="2026-07-25T16:00:00Z",
            expected_case_version=opening_version,
        )

        refused = api.create_abstraction(
            case["id"],
            f.abstraction_payload(
                expected_case_version=opening_version,
                iss_abstracted=25,
                gcs_arrival=8,
                mechanism_code="MVC",
                ed_departure_at="2026-07-25T16:00:00Z",
            ),
            make_registry_abstractor_headers(),
        )
        validate_error(refused, E.STALE_CASE_VERSION, 412)
        assert (
            fx.get_abstraction(api, case["id"], first["id"])["validation_status"]
            == ValidationStatus.SUBMITTED
        )

        current_version = fx.get_case(api, case["id"])["version"]
        assert current_version > opening_version

        second = fx.submit_abstraction(
            api,
            case,
            iss_abstracted=25,
            gcs_arrival=8,
            mechanism_code="MVC",
            ed_departure_at="2026-07-25T16:00:00Z",
            expected_case_version=current_version,
        )
        assert second["validation_status"] == ValidationStatus.SUBMITTED

        superseded = fx.get_abstraction(api, case["id"], first["id"])
        assert superseded["validation_status"] == ValidationStatus.REJECTED
        assert superseded["rejection_reason"] == SUPERSEDED_BY_RESUBMISSION

        after_case = fx.get_case(api, case["id"])
        assert after_case["abstraction_status"] == AbstractionStatus.ABSTRACTED
        assert after_case["version"] > current_version


class TestCriticalDictionaryViolation:
    """A critical rule does not cost points: it refuses the abstraction outright."""

    def test_a_critical_range_breach_rejects_the_whole_abstraction(
        self, api: ApiClient
    ) -> None:
        """Nothing is stored, the case does not advance, and no penalty is charged.

        Design: Corner/validations/critical_dictionary_range_violation_rejects_the_abstraction
        """
        fx.anchor_clock(api)
        fx.create_rule(
            api,
            f.range_rule_payload(
                field_name=DictionaryFieldName.GCS_ARRIVAL,
                min_value=3,
                max_value=15,
                severity=RuleSeverity.CRITICAL,
            ),
        )
        center, tier = fx.center_with_tier(
            api,
            name="Ravenswood Trauma",
            state_code="IL",
            designation_level=DesignationLevel.LEVEL_I,
            tier_code=TierCode.TIER_1_FULL,
        )
        case = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-RN1",
            arrival_at="2026-07-27T18:00:00Z",
            injury_severity_score=29,
            los_hours=70.00,
        )
        opening_version = case["version"]

        refused = api.create_abstraction(
            case["id"],
            f.abstraction_payload(
                expected_case_version=opening_version,
                iss_abstracted=29,
                gcs_arrival=20,
                mechanism_code="MVC",
                ed_departure_at="2026-07-27T20:00:00Z",
            ),
            make_registry_abstractor_headers(),
        )
        validate_error(refused, E.DICTIONARY_CRITICAL_VIOLATION, 422)

        assert (
            get_success_data(
                api.list_abstractions(case["id"], make_registry_abstractor_headers())
            )
            == []
        ), "a refused abstraction leaves no record behind"

        untouched = fx.get_case(api, case["id"])
        assert untouched["abstraction_status"] == AbstractionStatus.PENDING
        assert untouched["version"] == opening_version

        assert_decimal(
            fx.get_center(api, center["id"])["registry_compliance_score"],
            100.00,
            "registry_compliance_score",
        )


class TestAbstractionWindow:
    """The sixty day abstraction window is measured from the case's arrival."""

    def test_an_abstraction_past_the_sixty_day_window_is_refused(
        self, api: ApiClient
    ) -> None:
        """A case opened in May cannot be abstracted in August, dictionary or no dictionary.

        Design: Corner/validations/abstraction_after_sixty_day_window_returns_window_closed
        """
        fx.anchor_clock(api, "2026-05-02T00:00:00Z")
        center, tier = fx.center_with_tier(
            api,
            name="Marbleton Trauma",
            state_code="MD",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        case = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-MB1",
            arrival_at="2026-05-01T08:00:00Z",
            injury_severity_score=23,
            los_hours=52.00,
        )
        opening_version = case["version"]

        fx.move_clock(api, "2026-08-01T00:00:00Z")

        refused = api.create_abstraction(
            case["id"],
            f.abstraction_payload(
                expected_case_version=opening_version,
                iss_abstracted=23,
                gcs_arrival=11,
                mechanism_code="FALL",
                ed_departure_at="2026-05-01T11:00:00Z",
            ),
            make_registry_abstractor_headers(),
        )
        validate_error(refused, E.ABSTRACTION_WINDOW_CLOSED, 422)

        untouched = fx.get_case(api, case["id"])
        assert untouched["abstraction_status"] == AbstractionStatus.PENDING
        assert untouched["version"] == opening_version, (
            "the concurrency token supplied was current, so the window is what refused"
        )
        assert (
            get_success_data(
                api.list_abstractions(case["id"], make_registry_abstractor_headers())
            )
            == []
        )
