"""State reporting rules (closed-interval overlap) and state obligation
evaluation (CFSF forward / direct file / not required)."""
import pytest

from test_helpers import (
    ADMIN,
    IRS,
    SPEC,
    ApiErrorId,
    assert_state_obligation,
    create_matched_vendor,
    create_payment,
    create_state_rule,
    create_state_rule_payload,
    create_tax_year,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStateRuleOverlap:
    def test_state_rule_closed_interval_touching(self, api):
        """PRD §3.1: "Two rules for the same `state_code` may not overlap: creation
        is rejected with `ERR_STATE_RULE_OVERLAP` whenever an existing rule for that
        state has its `effective_from` at or before the new rule's `effective_to` and
        the new rule's `effective_from` is at or before the existing rule's
        `effective_to` — because the intervals are closed, rules whose endpoints
        merely touch do overlap and are rejected."

        Design: Difficulty/resource_temporal_overlap/state_rule_closed_interval_touching
        """
        create_state_rule(
            state_code="CA", participates_in_cfsf=True, direct_reporting_threshold_cents=0,
            effective_from="2025-01-01T00:00:00Z", effective_to="2025-12-31T00:00:00Z",
        )

        # Touching endpoints DO overlap under closed-interval semantics.
        touching = api.create_state_rule(
            create_state_rule_payload(
                state_code="CA", participates_in_cfsf=False,
                direct_reporting_threshold_cents=50000,
                effective_from="2025-12-31T00:00:00Z",
                effective_to="2026-12-31T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(touching, ApiErrorId.ERR_STATE_RULE_OVERLAP, 409)

        # A truly disjoint window is accepted.
        disjoint = api.create_state_rule(
            create_state_rule_payload(
                state_code="CA", participates_in_cfsf=False,
                direct_reporting_threshold_cents=50000,
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-12-31T00:00:00Z",
            ),
            ADMIN,
        )
        validate_success(disjoint, 201)

    def test_state_rule_overlap_is_per_state_and_inverted_interval_rejected(self, api):
        """PRD §3.1: "Two rules for the same `state_code` may not overlap..."
        PRD §3.1: "A rule whose `effective_to` precedes its `effective_from` is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Difficulty/resource_temporal_overlap/state_rule_closed_interval_touching
        """
        create_state_rule(
            state_code="CA", participates_in_cfsf=True, direct_reporting_threshold_cents=0,
            effective_from="2025-01-01T00:00:00Z", effective_to="2025-12-31T00:00:00Z",
        )

        # The same window for a DIFFERENT state does not overlap.
        other_state = api.create_state_rule(
            create_state_rule_payload(
                state_code="TX", participates_in_cfsf=False,
                direct_reporting_threshold_cents=50000,
                effective_from="2025-01-01T00:00:00Z",
                effective_to="2025-12-31T00:00:00Z",
            ),
            ADMIN,
        )
        validate_success(other_state, 201)

        # effective_to before effective_from is structurally invalid.
        inverted = api.create_state_rule(
            create_state_rule_payload(
                state_code="NY", participates_in_cfsf=False,
                direct_reporting_threshold_cents=50000,
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2025-01-01T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(inverted, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestStateObligationEvaluation:
    def test_state_channel_cfsf_direct_not_required(self, api):
        """PRD §3.9: "Its `required_channel` is `CFSF_FORWARD` when the rule's
        `participates_in_cfsf` is true; otherwise `DIRECT_FILE` when
        `reportable_amount_cents` is at least the rule's
        `direct_reporting_threshold_cents`; otherwise `NOT_REQUIRED`."
        PRD §3.9: "The obligation's status mirrors the channel: `CFSF_FORWARD` and
        `DIRECT_FILE` rows start `PENDING`, while a `NOT_REQUIRED` channel yields a
        `NOT_REQUIRED` status immediately."
        PRD §3.9: "The obligation's `reportable_amount_cents` is the sum of
        `amount_cents` over the vendor's `POSTED` in-year reportable payments across
        all boxes, NEC and MISC alike."

        Design: Corner/calculations/c_state_channel_cfsf_direct_not_required
        """
        create_tax_year()
        # All three rules cover the default logical clock (2026-08-01).
        create_state_rule(state_code="CA", participates_in_cfsf=True,
                          direct_reporting_threshold_cents=0,
                          effective_from="2020-01-01T00:00:00Z",
                          effective_to="2030-12-31T00:00:00Z")
        create_state_rule(state_code="TX", participates_in_cfsf=False,
                          direct_reporting_threshold_cents=50000,
                          effective_from="2020-01-01T00:00:00Z",
                          effective_to="2030-12-31T00:00:00Z")
        create_state_rule(state_code="NY", participates_in_cfsf=False,
                          direct_reporting_threshold_cents=200000,
                          effective_from="2020-01-01T00:00:00Z",
                          effective_to="2030-12-31T00:00:00Z")

        ca_vendor, _ = create_matched_vendor(
            legal_name="CA V", tin="111222333",
            address_line1="1 Q", address_city="Los Angeles",
            address_state="CA", address_postal="90001",
        )
        create_payment(ca_vendor["id"], amount_cents=70000, payment_date="2025-06-01T00:00:00Z")
        tx_vendor, _ = create_matched_vendor(
            legal_name="TX V", tin="444555666",
            address_line1="2 Q", address_city="Austin",
            address_state="TX", address_postal="78701",
        )
        create_payment(tx_vendor["id"], amount_cents=70000, payment_date="2025-06-01T00:00:00Z")
        ny_vendor, _ = create_matched_vendor(
            legal_name="NY V", tin="777888999",
            address_line1="3 Q", address_city="Albany",
            address_state="NY", address_postal="12201",
        )
        create_payment(ny_vendor["id"], amount_cents=70000, payment_date="2025-06-01T00:00:00Z")

        result = validate_success(
            api.evaluate_state_obligations({"tax_year": 2025}, SPEC), 200
        )
        assert result["evaluated_count"] == 3
        assert len(result["created_obligation_ids"]) == 3

        ca_rows, ca_meta = validate_paginated(
            api.list_state_obligations(SPEC, params={"vendor_id": ca_vendor["id"], "tax_year": 2025})
        )
        assert ca_meta["total_count"] == 1
        assert_state_obligation(ca_rows[0])
        assert ca_rows[0]["required_channel"] == "CFSF_FORWARD"
        assert ca_rows[0]["status"] == "PENDING"
        assert ca_rows[0]["reportable_amount_cents"] == 70000

        tx_rows, tx_meta = validate_paginated(
            api.list_state_obligations(SPEC, params={"vendor_id": tx_vendor["id"], "tax_year": 2025})
        )
        assert tx_meta["total_count"] == 1
        # 70000 >= 50000: the inclusive direct-file threshold.
        assert tx_rows[0]["required_channel"] == "DIRECT_FILE"
        assert tx_rows[0]["status"] == "PENDING"
        assert tx_rows[0]["reportable_amount_cents"] == 70000

        ny_rows, ny_meta = validate_paginated(
            api.list_state_obligations(SPEC, params={"vendor_id": ny_vendor["id"], "tax_year": 2025})
        )
        assert ny_meta["total_count"] == 1
        # 70000 < 200000: below the direct-file threshold.
        assert ny_rows[0]["required_channel"] == "NOT_REQUIRED"
        assert ny_rows[0]["status"] == "NOT_REQUIRED"
        assert ny_rows[0]["reportable_amount_cents"] == 70000
