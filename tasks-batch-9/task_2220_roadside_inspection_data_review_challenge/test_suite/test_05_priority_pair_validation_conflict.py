"""Requests that break two rules at once, where only the higher-priority rejection may
be reported.
"""

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    BasicCategory,
    ChallengeStatus,
    ChallengeType,
    EvidenceType,
    UnitType,
    fixtures as fx,
    get_success_data,
    make_carrier_analyst_headers,
    validate_error,
)

LATE_CLOCK = "2028-08-01T00:00:00Z"


def _carrier_with_code_and_threshold(api, **carrier_overrides) -> Dict[str, Any]:
    carrier = fx.create_carrier(api, **carrier_overrides)
    segment = carrier["carrier_segment"]
    measures = (1.0, 2.0, 4.0) if segment == "SMALL" else (0.5, 1.0, 2.0)
    code = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment=segment,
        measure_at_p50=measures[0],
        measure_at_p65=measures[1],
        measure_at_p80=measures[2],
    )
    return {"carrier": carrier, "code": code}


def _withdrawn_challenge_on_an_expired_report(api) -> Dict[str, Any]:
    """A challenge withdrawn straight out of DRAFT, on a report whose 730-day filing
    window has since closed."""
    fx.set_clock(api)
    base = _carrier_with_code_and_threshold(api)
    carrier_id = base["carrier"]["id"]
    report, rows = fx.build_scored_report(
        api,
        carrier_id,
        [{"violation_code_id": base["code"]["id"], "unit_type": UnitType.VEHICLE}],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    challenge = fx.create_draft_challenge(
        api,
        carrier_id,
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="Narrative does not support the violation.",
        target_violation_id=rows[0]["id"],
    )
    fx.add_evidence(
        api, carrier_id, challenge["id"], evidence_type=EvidenceType.ELD_RECORD
    )
    get_success_data(
        api.withdraw_challenge(
            challenge["id"],
            make_carrier_analyst_headers(carrier_id),
            {"withdraw_note": "Filed in error; withdrawing before submission."},
        )
    )
    fx.set_clock(api, LATE_CLOCK)
    return {
        "carrier": base["carrier"],
        "report": report,
        "violation": rows[0],
        "challenge": challenge,
    }


class TestStateBeatsFilingWindow:
    def test_withdrawn_status_is_reported_and_not_the_closed_window(self, api):
        """PRD 2.8: "**State admissibility.** The target record is in a state that
        permits the requested transition, else one of `ERR_INVALID_REPORT_STATE`,
        `ERR_INVALID_CHALLENGE_STATE`, `ERR_INVALID_ADJUDICATION_STATE`,
        `ERR_ALREADY_APPLIED_TO_RECORD`, `ERR_ADJUDICATION_SUPERSEDED`,
        `ERR_INVALID_COACHING_STATE`, `ERR_INVALID_CAP_STATE`,
        `ERR_INVALID_CAP_ITEM_STATE` or `ERR_VIOLATION_NOT_ACTIVE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_filing_window_on_withdrawn_challenge_submit
        """
        scenario = _withdrawn_challenge_on_an_expired_report(api)
        carrier_id = scenario["carrier"]["id"]

        response = api.submit_challenge(
            scenario["challenge"]["id"], make_carrier_analyst_headers(carrier_id)
        )
        payload = validate_error(response, ApiErrorId.INVALID_CHALLENGE_STATE, 409)
        assert payload["error_id"] != ApiErrorId.CHALLENGE_FILING_WINDOW_CLOSED

    def test_the_rejected_submit_consumed_nothing(self, api):
        """PRD 3.6: "On creation the system copies the report's `attributed_carrier_id`
        onto the challenge as its own `carrier_id`, sets `status` to `DRAFT`, sets
        `info_request_count` to 0 and `evidence_count` to 0, and consumes no quota
        whatsoever — drafting is free."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_filing_window_on_withdrawn_challenge_submit
        """
        scenario = _withdrawn_challenge_on_an_expired_report(api)
        carrier_id = scenario["carrier"]["id"]
        api.submit_challenge(
            scenario["challenge"]["id"], make_carrier_analyst_headers(carrier_id)
        )

        challenge = get_success_data(
            api.get_data_challenge(scenario["challenge"]["id"], fx.REVIEWER)
        )
        assert challenge["status"] == ChallengeStatus.WITHDRAWN
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 0
        assert fx.read_violation(api, scenario["violation"]["id"])["under_challenge"] is False


def _quota_spent_and_window_closed(api) -> Dict[str, Any]:
    """A SMALL carrier that has already spent its single challenge, holding a second
    DRAFT challenge on a report that is now 762 days old."""
    fx.set_clock(api)
    base = _carrier_with_code_and_threshold(
        api,
        dot_number="1000003",
        legal_name="Ridge Runner Trucking",
        average_power_units=10,
        annual_vmt=800000,
    )
    carrier_id = base["carrier"]["id"]
    report, rows = fx.build_scored_report(
        api,
        carrier_id,
        [
            {"violation_code_id": base["code"]["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": base["code"]["id"], "unit_type": UnitType.VEHICLE},
        ],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    first = fx.build_submitted_challenge(
        api,
        carrier_id,
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="First entry is unsupported.",
        target_violation_id=rows[0]["id"],
    )
    second = fx.create_draft_challenge(
        api,
        carrier_id,
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="Second entry is unsupported.",
        target_violation_id=rows[1]["id"],
    )
    fx.add_evidence(api, carrier_id, second["id"], evidence_type=EvidenceType.ELD_RECORD)
    fx.set_clock(api, LATE_CLOCK)
    return {
        "carrier": base["carrier"],
        "report": report,
        "violations": rows,
        "first": first,
        "second": second,
    }


class TestFilingWindowBeatsQuota:
    def test_closed_window_is_reported_and_not_the_exhausted_quota(self, api):
        """PRD 3.6: "The filing window must be open: the number of whole days between
        the report's `inspection_start` and the current logical clock must be no more
        than 730 — two years of contestability, matching the scoring lookback — and a
        later submission is rejected with `ERR_CHALLENGE_FILING_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/filing_window_beats_quota_on_expired_report_submit
        """
        scenario = _quota_spent_and_window_closed(api)
        carrier_id = scenario["carrier"]["id"]

        response = api.submit_challenge(
            scenario["second"]["id"], make_carrier_analyst_headers(carrier_id)
        )
        payload = validate_error(
            response, ApiErrorId.CHALLENGE_FILING_WINDOW_CLOSED, 422
        )
        assert payload["error_id"] != ApiErrorId.CHALLENGE_QUOTA_EXCEEDED

    def test_the_quota_ledger_is_genuinely_exhausted_and_unchanged(self, api):
        """PRD 2.8: "**Challenge quota**, `ERR_CHALLENGE_QUOTA_EXCEEDED` (409), on
        challenge submission."

        Design: Difficulty/priority_pair_validation_conflict/filing_window_beats_quota_on_expired_report_submit
        """
        scenario = _quota_spent_and_window_closed(api)
        carrier_id = scenario["carrier"]["id"]
        api.submit_challenge(
            scenario["second"]["id"], make_carrier_analyst_headers(carrier_id)
        )

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["challenge_quota_limit"] == 1
        assert carrier["challenge_quota_used"] == 1

        second = get_success_data(
            api.get_data_challenge(scenario["second"]["id"], fx.REVIEWER)
        )
        assert second["status"] == ChallengeStatus.DRAFT
        first = get_success_data(
            api.get_data_challenge(scenario["first"]["id"], fx.REVIEWER)
        )
        assert first["status"] == ChallengeStatus.SUBMITTED
        assert (
            fx.read_violation(api, scenario["violations"][1]["id"])["under_challenge"]
            is False
        )


def _foreign_analyst_and_withdrawn_challenge(api) -> Dict[str, Any]:
    """A withdrawn challenge owned by one carrier, plus a second carrier whose analyst
    will address it."""
    fx.set_clock(api)
    base = _carrier_with_code_and_threshold(api)
    owner_id = base["carrier"]["id"]
    outsider = fx.create_carrier(
        api,
        dot_number="1000002",
        legal_name="Maple Leaf Transport",
        average_power_units=25,
        annual_vmt=2000000,
    )
    report, rows = fx.build_scored_report(
        api,
        owner_id,
        [{"violation_code_id": base["code"]["id"], "unit_type": UnitType.VEHICLE}],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    challenge = fx.create_draft_challenge(
        api,
        owner_id,
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="Narrative does not support the violation.",
        target_violation_id=rows[0]["id"],
    )
    fx.add_evidence(api, owner_id, challenge["id"], evidence_type=EvidenceType.ELD_RECORD)
    get_success_data(
        api.withdraw_challenge(
            challenge["id"],
            make_carrier_analyst_headers(owner_id),
            {"withdraw_note": "Withdrawn before submission."},
        )
    )
    return {
        "owner": base["carrier"],
        "outsider": outsider,
        "challenge": challenge,
        "violation": rows[0],
    }


class TestCarrierScopeBeatsState:
    def test_scope_violation_is_reported_and_not_the_invalid_state(self, api):
        """PRD 2.8: "**Carrier scope.** For a `CarrierAnalyst` or
        `CarrierSafetyManager`, `X-User-ID` matches the carrier owning the addressed
        resource, else `ERR_CARRIER_SCOPE_VIOLATION` (403)."

        Design: Difficulty/priority_pair_validation_conflict/carrier_scope_beats_state_on_foreign_challenge_submit
        """
        scenario = _foreign_analyst_and_withdrawn_challenge(api)

        response = api.submit_challenge(
            scenario["challenge"]["id"],
            make_carrier_analyst_headers(scenario["outsider"]["id"]),
        )
        payload = validate_error(response, ApiErrorId.CARRIER_SCOPE_VIOLATION, 403)
        assert payload["error_id"] != ApiErrorId.INVALID_CHALLENGE_STATE

    def test_neither_carrier_ledger_moved(self, api):
        """PRD 2.8: "When a single request violates more than one rule, the response
        reports the violation that comes first in the following precedence order."

        Design: Difficulty/priority_pair_validation_conflict/carrier_scope_beats_state_on_foreign_challenge_submit
        """
        scenario = _foreign_analyst_and_withdrawn_challenge(api)
        api.submit_challenge(
            scenario["challenge"]["id"],
            make_carrier_analyst_headers(scenario["outsider"]["id"]),
        )

        challenge = get_success_data(
            api.get_data_challenge(scenario["challenge"]["id"], fx.REVIEWER)
        )
        assert challenge["status"] == ChallengeStatus.WITHDRAWN
        assert challenge["carrier_id"] == scenario["owner"]["id"]
        assert fx.read_carrier(api, scenario["owner"]["id"])["challenge_quota_used"] == 0
        assert fx.read_carrier(api, scenario["outsider"]["id"])["challenge_quota_used"] == 0
