"""Distribution rule versions and their HYBRID weight constraints (PRD
§3.7, §2.10 priority 17)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA,
    assert_distribution_rule_version,
    create_distribution_rule_payload,
    validate_error,
    validate_success,
)


class TestRuleCreation:

    def test_create_per_play_rule(self, api):
        """PRD §3.7: 'Each version is identified by a unique 1-to-32-
        character version_tag... a distribution_mode of PER_PLAY,
        PER_DURATION, or HYBRID, a per_play_weight between 0.00 and
        1.00 (required when the mode is PER_PLAY or HYBRID)...'

        Claim: POST /royalty/distribution-rules in PER_PLAY mode → 201
        with version_tag set and distribution_mode=PER_PLAY.
        """
        resp = api.create_distribution_rule(
            create_distribution_rule_payload(distribution_mode="PER_PLAY"),
            PA,
        )
        data = validate_success(resp, 201)
        assert_distribution_rule_version(data)
        assert data["distribution_mode"] == "PER_PLAY"

    def test_rule_version_is_append_only_shape(self, api):
        """PRD §3.7: 'DistributionRuleVersion rows carry only id and
        created_at — they are versioned by version_tag and immutable
        once published.'

        Claim: rule version response shape carries id + created_at; no
        updated_at; no version.
        """
        resp = api.create_distribution_rule(
            create_distribution_rule_payload(distribution_mode="PER_PLAY"),
            PA,
        )
        data = validate_success(resp, 201)
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" not in data or data.get("updated_at") is None
        assert "version" not in data or data.get("version") is None


class TestHybridWeights:

    def test_hybrid_weights_summing_correctly_succeeds(self, api):
        """PRD §3.7: 'When the mode is HYBRID, the sum of
        per_play_weight and per_duration_weight must equal exactly
        1.00.'

        Claim: HYBRID mode with weights summing to 1.00 → 201.
        """
        resp = api.create_distribution_rule(
            create_distribution_rule_payload(
                distribution_mode="HYBRID",
                per_play_weight=0.40,
                per_duration_weight=0.60,
            ),
            PA,
        )
        data = validate_success(resp, 201)
        assert data["distribution_mode"] == "HYBRID"

    def test_hybrid_weights_not_summing_rejected(self, api):
        """PRD §3.7 / §2.10 priority 17: 'When creating a
        DistributionRuleVersion with distribution_mode of HYBRID, the
        sum of per_play_weight and per_duration_weight must equal
        exactly 1.00; otherwise ERR_RULE_WEIGHTS_INVALID (422).'

        Claim: HYBRID with sum != 1.00 → ERR_RULE_WEIGHTS_INVALID (422).
        """
        resp = api.create_distribution_rule(
            create_distribution_rule_payload(
                distribution_mode="HYBRID",
                per_play_weight=0.30,
                per_duration_weight=0.30,
            ),
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_RULE_WEIGHTS_INVALID.value, 422)
