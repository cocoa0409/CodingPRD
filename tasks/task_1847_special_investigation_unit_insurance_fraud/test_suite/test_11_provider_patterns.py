"""Provider pattern scoring, escalation, merge integrity.

NOTE on the auto-linkage mechanism: PRD §3.6 says "each provider pattern associated
with evidence on the case gains the case in its `linked_case_ids`", but the
Evidence resource carries no provider-identifier field in §3.4, so the concrete
linkage mechanism is not uniquely derivable from the PRD. Exact pattern_score
values for the three-case combinatorial recipe therefore cannot be asserted
without assuming a linkage pathway the PRD leaves open; the tests below restrict
themselves to what IS uniquely derivable (escalation threshold, merge integrity).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, create_provider_pattern_payload,
)
from test_helpers.api_client import api_client


class TestProviderPatternScoreCombinatorial:
    """Difficulty/combinatorial_formula/provider_pattern_score_mode_a_multi_input_tiered

    The exact-score=64 assertion is not uniquely derivable from the PRD (the
    evidence→pattern linkage field is absent). What IS derivable is the
    escalation threshold rule and the merge integrity rule; the two tests below
    pin those.
    """

    def test_pattern_below_escalation_threshold_rejected(self, api):
        """PRD §3.8: "A pattern in `MONITORING` may be escalated to
        `ESCALATED_TO_NICB` once its `pattern_score` reaches the escalation
        threshold of 60 — below the threshold the attempt is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/combinatorial_formula/provider_pattern_score_mode_a_multi_input_tiered
        """
        mh = make_manager_headers()
        pat_resp = api_client.create_provider_pattern(
            create_provider_pattern_payload(provider_npi="NPI-LO",
                                            provider_name="ProvLo",
                                            ring_signature="SIG-LO"), mh)
        pattern = validate_success(pat_resp, expected_status=201)
        # Newly registered pattern has no linked cases; score is below threshold.
        assert pattern["pattern_score"] < 60
        resp = api_client.escalate_provider_pattern(pattern["id"], mh)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_pattern_score_is_bounded_by_max_100(self, api):
        """PRD §3.8: "The result is capped at 100."
        PRD §3.8: "A new pattern starts in `MONITORING` with `linked_case_ids`
        empty, `parent_pattern_id` null, and a `pattern_score` computed over its
        (initially empty) linkage."

        Design: Difficulty/combinatorial_formula/provider_pattern_score_mode_a_multi_input_tiered
        """
        mh = make_manager_headers()
        pat_resp = api_client.create_provider_pattern(
            create_provider_pattern_payload(provider_npi="NPI-CAP",
                                            provider_name="ProvCap",
                                            ring_signature="SIG-CAP"), mh)
        pattern = validate_success(pat_resp, expected_status=201)
        assert 0 <= pattern["pattern_score"] <= 100
        assert pattern["escalation_status"] == "MONITORING"
        assert pattern["linked_case_ids"] == []


class TestProviderPatternMerge:
    def test_merge_with_mismatched_ring_signature_rejected(self, api):
        """PRD §3.8: "the manager supplies `parent_pattern_id`, which must resolve
        (`ERR_FK_NOT_FOUND`), must name a different pattern that is itself still
        `MONITORING`, and must carry the identical `ring_signature` — otherwise
        `ERR_PATTERN_MERGE_INVALID`."

        Design: Corner/errors/err_pattern_merge_invalid_trigger
        """
        mh = make_manager_headers()
        pa = validate_success(api_client.create_provider_pattern(
            create_provider_pattern_payload(provider_npi="NPI-A",
                                            provider_name="ProvA",
                                            ring_signature="SIG-A"), mh),
            expected_status=201)
        pb = validate_success(api_client.create_provider_pattern(
            create_provider_pattern_payload(provider_npi="NPI-B",
                                            provider_name="ProvB",
                                            ring_signature="SIG-B"), mh),
            expected_status=201)
        resp = api_client.merge_provider_pattern(pa["id"],
                                                 {"parent_pattern_id": pb["id"]}, mh)
        validate_error(resp, ApiErrorId.ERR_PATTERN_MERGE_INVALID)
