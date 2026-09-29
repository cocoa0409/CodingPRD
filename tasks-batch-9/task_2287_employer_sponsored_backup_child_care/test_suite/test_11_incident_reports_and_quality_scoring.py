"""Incident review, the substantiate/dismiss fork and the two quality-score variants."""

from typing import Any, Dict

import pytest
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_incident_report,
    dismiss_incident,
    file_incident,
    incident_report_payload,
    make_network_admin_headers,
    read_provider,
    review_incident,
    set_clock,
    setup_confirmed_reservation,
    setup_credentialed_provider,
    substantiate_incident,
    substantiated_incident,
    validate_error,
    validate_paginated,
    validate_success,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]
CARE_COORDINATOR = TEST_USERS["care_coordinator"]


class TestRollingVersusLifetimeQualityScore:
    """Three substantiated reports of ageing severities, scored two ways."""

    @staticmethod
    def _three_substantiated_reports(api) -> Dict[str, Any]:
        """SEVERE at 2026-08-01, MODERATE at 2026-09-20, MINOR at 2026-10-25."""
        bundle = setup_credentialed_provider(
            api,
            provider_name="Bright Start Center",
            owner_user_id="u_pm_2",
            market_code="MKT-BOS",
            postal_code="02111",
            daily_capacity_slots=6,
        )
        provider_id = bundle["provider"]["id"]

        severe = substantiated_incident(
            api,
            provider_id,
            "SEVERE",
            filer_user_id="u_cc_1",
            resolution_reason_code="COACHING_ISSUED",
            category="SUPERVISION",
            narrative="Unattended child in the toddler room for 8 minutes.",
        )

        set_clock(api, "2026-09-20T00:00:00Z")
        moderate = substantiated_incident(
            api,
            provider_id,
            "MODERATE",
            filer_user_id="u_cc_1",
            resolution_reason_code="FACILITY_REPAIRED",
            category="FACILITY",
            narrative="Playground gate latch found unsecured at drop-off.",
        )

        set_clock(api, "2026-10-25T00:00:00Z")
        minor = substantiated_incident(
            api,
            provider_id,
            "MINOR",
            filer_user_id="u_cc_1",
            resolution_reason_code="PAPERWORK_CORRECTED",
            category="DOCUMENTATION",
            narrative="Sign-out sheet missing a guardian signature.",
        )

        return {
            "provider_id": provider_id,
            "severe": severe,
            "moderate": moderate,
            "minor": minor,
        }

    def test_identical_rows_yield_88_80_rolling_and_54_00_lifetime(self, api):
        """One decayed set of deductions, two totals that disagree by 34.80.

        PRD 3.8: "The rolling result is written to `quality_score` and is the only
        variant the matching ranker reads; the undecayed result is written to
        `lifetime_quality_score` and is the value the reinstatement floor and the
        renewal-risk analytics read."

        Design: Difficulty/dual_variant_calc/provider_rolling_quality_88_80_vs_lifetime_54_00
        """
        world = self._three_substantiated_reports(api)
        set_clock(api, "2026-11-01T00:00:00Z")

        provider = read_provider(api, world["provider_id"])
        assert provider["quality_score"] == pytest.approx(88.80, abs=0.0001)
        assert provider["lifetime_quality_score"] == pytest.approx(54.00, abs=0.0001)
        assert provider["quality_score"] != provider["lifetime_quality_score"]
        assert provider["substantiated_incident_count"] == 3
        assert provider["completed_reservation_count"] == 0
        assert provider["network_status"] == "CREDENTIALED"

        severe = validate_success(api.get_incident_report(world["severe"]["id"], NETWORK_ADMIN))
        assert_incident_report(severe)
        assert severe["incident_status"] == "SUBSTANTIATED"
        assert severe["qa_action"] == "NONE"
        assert severe["resolution_reason_code"] == "COACHING_ISSUED"

    def test_a_92_day_old_severe_report_deducts_nothing_rolling_and_thirty_lifetime(self, api):
        """Past ninety days the rolling variant forgets what the lifetime variant keeps.

        PRD 3.8: "For the rolling variant, the decay factor is 1.00 for an age of 30
        days or fewer, 0.60 for an age above 30 but at most 60 days, 0.30 for an age
        above 60 but at most 90 days, and 0.00 beyond 90 days, so an incident older
        than a quarter stops counting."

        PRD 3.8: "For the lifetime variant the decay factor is always 1.00 — age is
        ignored entirely and every substantiated incident deducts at full weight
        forever."

        Design: Difficulty/dual_variant_calc/provider_rolling_quality_88_80_vs_lifetime_54_00
        """
        bundle = setup_credentialed_provider(
            api,
            provider_name="Single Severe Center",
            owner_user_id="u_pm_3",
            market_code="MKT-BOS",
            postal_code="02112",
            daily_capacity_slots=6,
        )
        provider_id = bundle["provider"]["id"]
        assert bundle["provider"]["quality_score"] == pytest.approx(100.00, abs=0.0001)

        substantiated_incident(
            api,
            provider_id,
            "SEVERE",
            filer_user_id="u_cc_1",
            resolution_reason_code="COACHING_ISSUED",
        )
        set_clock(api, "2026-11-01T00:00:00Z")

        provider = read_provider(api, provider_id)
        assert provider["quality_score"] == pytest.approx(100.00, abs=0.0001)
        assert provider["lifetime_quality_score"] == pytest.approx(70.00, abs=0.0001)
        assert provider["substantiated_incident_count"] == 1

    def test_advancing_the_clock_recomputes_the_rolling_score_only(self, api):
        """79.80 becomes 88.80 as the SEVERE row ages out; 54.00 never moves.

        PRD 3.8: "Both are recomputed when a report is substantiated, when a provider
        passes credential review, on every network-posture movement, when a reservation
        completes, and whenever the logical clock is advanced."

        Design: Difficulty/dual_variant_calc/provider_rolling_quality_88_80_vs_lifetime_54_00
        """
        world = self._three_substantiated_reports(api)

        at_third_substantiation = read_provider(api, world["provider_id"])
        assert at_third_substantiation["quality_score"] == pytest.approx(79.80, abs=0.0001)
        assert at_third_substantiation["lifetime_quality_score"] == pytest.approx(
            54.00, abs=0.0001
        )

        set_clock(api, "2026-11-01T00:00:00Z")

        aged = read_provider(api, world["provider_id"])
        assert aged["quality_score"] == pytest.approx(88.80, abs=0.0001)
        assert aged["quality_score"] > at_third_substantiation["quality_score"]
        assert aged["lifetime_quality_score"] == pytest.approx(54.00, abs=0.0001)
        assert aged["substantiated_incident_count"] == 3


class TestIncidentResolutionFork:
    """Two identical MODERATE reports resolved down opposite branches."""

    @staticmethod
    def _two_reviewed_reports(api) -> Dict[str, Any]:
        bundle = setup_credentialed_provider(
            api,
            provider_name="Forkview Center",
            owner_user_id="u_pm_f",
            market_code="MKT-BOS",
            postal_code="02117",
            daily_capacity_slots=5,
        )
        provider_id = bundle["provider"]["id"]
        assert bundle["provider"]["network_status"] == "CREDENTIALED"
        assert bundle["provider"]["quality_score"] == pytest.approx(100.00, abs=0.0001)
        assert bundle["provider"]["substantiated_incident_count"] == 0

        first = file_incident(
            api,
            provider_id,
            "MODERATE",
            category="SUPERVISION",
            narrative="Ratio breach during nap transition.",
        )
        second = file_incident(
            api,
            provider_id,
            "MODERATE",
            category="MEDICAL",
            narrative="Medication log entry disputed by the family.",
        )
        review_incident(api, first["id"], CARE_COORDINATOR)
        review_incident(api, second["id"], CARE_COORDINATOR)

        return {"provider_id": provider_id, "first": first, "second": second}

    def test_substantiation_deducts_twelve_and_demotes_to_probation(self, api):
        """The substantiate branch moves score, count and network posture together.

        PRD 3.8: "It records both, then recomputes the provider's
        `substantiated_incident_count` and both quality-score variants."

        PRD 3.3: "it records `last_status_reason_code` from the supplied reason code
        (or from `INCIDENT_SUBSTANTIATED` when it is driven by a substantiated
        incident), causes every later ranking evaluation to multiply this provider's
        score by one half"

        Design: Difficulty/non_linear_state_machine/incident_fork_substantiate_probation_versus_dismiss_no_op
        """
        world = self._two_reviewed_reports(api)

        resolved = substantiate_incident(
            api,
            world["first"]["id"],
            "PROBATION",
            resolution_reason_code="RATIO_BREACH_CONFIRMED",
        )
        assert resolved["incident_status"] == "SUBSTANTIATED"
        assert resolved["qa_action"] == "PROBATION"
        assert resolved["resolution_reason_code"] == "RATIO_BREACH_CONFIRMED"

        provider = read_provider(api, world["provider_id"])
        assert provider["quality_score"] == pytest.approx(88.00, abs=0.0001)
        assert provider["lifetime_quality_score"] == pytest.approx(88.00, abs=0.0001)
        assert provider["network_status"] == "PROBATION"
        assert provider["substantiated_incident_count"] == 1
        assert provider["last_status_reason_code"] == "INCIDENT_SUBSTANTIATED"

    def test_dismissal_of_the_sibling_report_changes_nothing_at_all(self, api):
        """The dismiss branch is a scoring no-op even on an identical MODERATE row.

        PRD 3.8: "It records that reason code, leaves `qa_action` at `NONE`, leaves
        `network_status` entirely unchanged, and leaves `substantiated_incident_count`,
        `quality_score` and `lifetime_quality_score` unchanged: a dismissed report
        never deducts, ever."

        Design: Difficulty/non_linear_state_machine/incident_fork_substantiate_probation_versus_dismiss_no_op
        """
        world = self._two_reviewed_reports(api)
        substantiate_incident(
            api,
            world["first"]["id"],
            "PROBATION",
            resolution_reason_code="RATIO_BREACH_CONFIRMED",
        )

        dismissed = dismiss_incident(
            api,
            world["second"]["id"],
            resolution_reason_code="UNSUBSTANTIATED_AFTER_INTERVIEW",
        )
        assert dismissed["incident_status"] == "DISMISSED"
        assert dismissed["qa_action"] == "NONE"
        assert dismissed["resolution_reason_code"] == "UNSUBSTANTIATED_AFTER_INTERVIEW"

        provider = read_provider(api, world["provider_id"])
        assert provider["quality_score"] == pytest.approx(88.00, abs=0.0001)
        assert provider["lifetime_quality_score"] == pytest.approx(88.00, abs=0.0001)
        assert provider["network_status"] == "PROBATION"
        assert provider["substantiated_incident_count"] == 1


class TestIncidentReviewTransition:
    def test_taking_a_severe_report_under_review_deducts_nothing(self, api):
        """UNDER_REVIEW records the reviewer and leaves both scores at 100.

        PRD 3.8: "Taking a report under review is done by a `care_coordinator` or a
        `network_admin` and requires the subject provider not to be `DEPROVISIONED`
        (`ERR_PROVIDER_NOT_IN_NETWORK`); it records `reviewed_by` from `X-User-ID` and
        moves no score."

        PRD 3.8: "Deductions accumulate over this provider's reports whose
        `incident_status` is `SUBSTANTIATED` — reports that are `OPEN`, `UNDER_REVIEW`
        or `DISMISSED` contribute nothing at all."

        Design: Corner/state_machines/corner_incident_report_open_to_under_review_transition
        """
        bundle = setup_credentialed_provider(
            api,
            provider_name="Review Path Center",
            owner_user_id="u_pm_rv",
            market_code="MKT-MCI",
            postal_code="64106",
            daily_capacity_slots=4,
        )
        provider_id = bundle["provider"]["id"]
        assert bundle["provider"]["network_status"] == "CREDENTIALED"
        assert bundle["provider"]["quality_score"] == pytest.approx(100.00, abs=0.0001)

        filed = file_incident(
            api,
            provider_id,
            "SEVERE",
            category="SUPERVISION",
            narrative="A child was briefly unaccounted for during outdoor play.",
        )
        assert filed["incident_status"] == "OPEN"

        reviewed = review_incident(api, filed["id"], NETWORK_ADMIN)
        assert_incident_report(reviewed)
        assert reviewed["incident_status"] == "UNDER_REVIEW"
        assert reviewed["reviewed_by"] == "u_na_1"
        assert reviewed["resolution_reason_code"] is None
        assert reviewed["qa_action"] == "NONE"
        assert reviewed["severity"] == "SEVERE"

        provider = read_provider(api, provider_id)
        assert provider["network_status"] == "CREDENTIALED"
        assert provider["quality_score"] == pytest.approx(100.00, abs=0.0001)
        assert provider["lifetime_quality_score"] == pytest.approx(100.00, abs=0.0001)
        assert provider["substantiated_incident_count"] == 0


class TestIncidentReservationProviderMatch:
    def test_naming_another_providers_reservation_is_refused_and_not_persisted(self, api):
        """The same payload is rejected for the wrong provider and accepted for the right one.

        PRD 3.8: "When a reservation is named, its `matched_provider_id` must be the
        same provider the report is filed against, otherwise
        `ERR_INCIDENT_PROVIDER_MISMATCH`."

        PRD 3.8: "Filing alone moves no score: the provider's `quality_score`,
        `lifetime_quality_score` and `substantiated_incident_count` are all untouched."

        Design: Corner/endpoints/corner_incident_report_reservation_provider_mismatch_rejected
        """
        world = setup_confirmed_reservation(
            api,
            care_start_utc="2026-08-17T09:00:00Z",
            care_end_utc="2026-08-17T15:00:00Z",
            block_start_utc="2026-08-17T08:00:00Z",
            block_end_utc="2026-08-17T18:00:00Z",
            market_code="MKT-NSH",
            total_slots=4,
            provider_overrides={
                "provider_name": "Nashville Serving Center",
                "postal_code": "37203",
            },
        )
        serving_provider_id = world["provider"]["id"]
        reservation_id = world["reservation"]["id"]
        assert world["reservation"]["matched_provider_id"] == serving_provider_id

        other = setup_credentialed_provider(
            api,
            provider_name="Memphis Bystander Center",
            owner_user_id="u_pm_mem",
            market_code="MKT-MEM",
            postal_code="38103",
            daily_capacity_slots=4,
        )
        bystander_provider_id = other["provider"]["id"]

        mismatched = api.create_incident_report(
            incident_report_payload(
                bystander_provider_id,
                "MODERATE",
                reservation_id=reservation_id,
                narrative="Filed against the wrong provider on purpose.",
            ),
            CARE_COORDINATOR,
        )
        validate_error(mismatched, ApiErrorId.ERR_INCIDENT_PROVIDER_MISMATCH.value, 409)

        accepted = validate_success(
            api.create_incident_report(
                incident_report_payload(
                    serving_provider_id,
                    "MODERATE",
                    reservation_id=reservation_id,
                    narrative="Snack allergy protocol was not followed at pickup.",
                ),
                CARE_COORDINATOR,
            ),
            201,
        )
        assert accepted["provider_id"] == serving_provider_id
        assert accepted["reservation_id"] == reservation_id
        assert accepted["incident_status"] == "OPEN"

        rows, meta = validate_paginated(
            api.list_incident_reports(
                NETWORK_ADMIN,
                {"provider_id": bystander_provider_id, "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

        serving = read_provider(api, serving_provider_id)
        assert serving["quality_score"] == pytest.approx(100.00, abs=0.0001)
        assert serving["substantiated_incident_count"] == 0


class TestIncidentSegregationOfDuties:
    def test_the_filer_may_review_but_may_not_resolve_its_own_report(self, api):
        """The bar is on identity, not role, and it covers both resolution edges.

        PRD 3.8: "Resolving the report is reserved to a `network_admin`, and the
        `X-User-ID` doing so may not equal the `reported_by_user_id` that filed it
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/rbac/corner_filer_cannot_substantiate_or_dismiss_own_incident_report
        """
        bundle = setup_credentialed_provider(
            api,
            provider_name="Duty Split Center",
            owner_user_id="u_pm_ds",
            market_code="MKT-OKC",
            postal_code="73102",
            daily_capacity_slots=4,
        )
        provider_id = bundle["provider"]["id"]
        filer = make_network_admin_headers("u_na_9")

        filed = file_incident(
            api,
            provider_id,
            "MODERATE",
            filer_headers=filer,
            narrative="Ratio slipped during the afternoon transition.",
        )
        assert filed["reported_by_user_id"] == "u_na_9"

        reviewed = review_incident(api, filed["id"], filer)
        assert reviewed["incident_status"] == "UNDER_REVIEW"
        assert reviewed["reviewed_by"] == "u_na_9"

        own_substantiate = api.substantiate_incident_report(
            filed["id"],
            {"qa_action": "PROBATION", "resolution_reason_code": "CONFIRMED_FINDING"},
            filer,
        )
        validate_error(own_substantiate, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        own_dismiss = api.dismiss_incident_report(
            filed["id"], {"resolution_reason_code": "UNFOUNDED"}, filer
        )
        validate_error(own_dismiss, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        resolved = substantiate_incident(
            api,
            filed["id"],
            "PROBATION",
            headers=make_network_admin_headers("u_na_2"),
            resolution_reason_code="CONFIRMED_FINDING",
        )
        assert resolved["incident_status"] == "SUBSTANTIATED"
        assert resolved["qa_action"] == "PROBATION"

        provider = read_provider(api, provider_id)
        assert provider["network_status"] == "PROBATION"
        assert provider["lifetime_quality_score"] == pytest.approx(88.00, abs=0.0001)
        assert provider["substantiated_incident_count"] == 1
