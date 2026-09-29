"""Evidence packet indices: satisfied weights, waiver credit and the cap tier."""

import pytest

from test_helpers import (
    ApiErrorId,
    EvidenceItem,
    PacketState,
    assert_evidence_index,
    assert_missing_items,
    expected_completeness_index,
    expected_waiver_cap,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    scenario_draft_packet_on_open_release,
    waive_item,
)
from test_helpers.test_users import COMPLIANCE_OFFICER


class TestWaiverCapTierFromBaseIndex:
    """"The tier is keyed on ``base_index`` and **not** on the running total"."""

    def test_base_index_sums_the_satisfied_weights_excluding_waivers(self, api):
        """"**Step one** computes ``base_index`` as the sum of the weights of the
        satisfied items, **excluding waivers entirely**".

        Design: Difficulty/combinatorial_formula/evidence_completeness_waiver_cap_tier_selected_from_base_index
        """
        built = scenario_draft_packet_on_open_release(api)

        packet = built["packet"]

        assert_evidence_index(
            packet, base_index=75, waiver_credit_points=0, completeness_index=75
        )
        assert packet["waiver_count"] == 0
        assert packet["state"] == PacketState.DRAFT
        assert expected_waiver_cap(75) == 10

    def test_first_waiver_earns_half_of_that_item_s_weight(self, api):
        """"sum, over every entry in ``waivers``, half of that item's weight; round the
        sum half up to two decimal places".

        Design: Difficulty/combinatorial_formula/evidence_completeness_waiver_cap_tier_selected_from_base_index
        """
        built = scenario_draft_packet_on_open_release(api)

        after_first = waive_item(
            api, built["packet"]["id"], EvidenceItem.CANARY_PASS
        )

        assert_evidence_index(
            after_first,
            base_index=75,
            waiver_credit_points=7.5,
            completeness_index=82.5,
        )
        assert after_first["completeness_index"] == pytest.approx(
            expected_completeness_index(75, [EvidenceItem.CANARY_PASS]), abs=0.01
        )

    def test_second_waiver_is_clamped_by_the_cap_selected_from_the_base_index(self, api):
        """"take the smaller of that raw credit and the cap" -- re-selecting the tier
        after adding credit "is the wrong reading and produces a larger index".

        Design: Difficulty/combinatorial_formula/evidence_completeness_waiver_cap_tier_selected_from_base_index
        """
        built = scenario_draft_packet_on_open_release(api)
        waive_item(api, built["packet"]["id"], EvidenceItem.CANARY_PASS)

        after_second = waive_item(
            api, built["packet"]["id"], EvidenceItem.RELEASE_NOTES
        )

        assert_evidence_index(
            after_second,
            base_index=75,
            waiver_credit_points=10,
            completeness_index=85.0,
        )
        assert after_second["completeness_index"] != pytest.approx(87.5, abs=0.001)

    def test_both_waivers_are_recorded_and_nothing_remains_missing(self, api):
        """"``missing_items`` lists the item codes that are neither satisfied nor
        waived, and ``waiver_count`` is the number of entries in ``waivers``".

        Design: Difficulty/combinatorial_formula/evidence_completeness_waiver_cap_tier_selected_from_base_index
        """
        built = scenario_draft_packet_on_open_release(api)
        waive_item(api, built["packet"]["id"], EvidenceItem.CANARY_PASS)

        after_second = waive_item(
            api, built["packet"]["id"], EvidenceItem.RELEASE_NOTES
        )

        assert after_second["waiver_count"] == 2
        assert_missing_items(after_second, [])
        waived_codes = [entry["item_code"] for entry in after_second["waivers"]]
        assert sorted(waived_codes) == sorted(
            [EvidenceItem.CANARY_PASS, EvidenceItem.RELEASE_NOTES]
        )

    def test_sealing_below_ninety_is_refused_and_the_packet_stays_draft(self, api):
        """"its ``completeness_index`` must be at least 90, or sealing is refused with
        ``ERR_EVIDENCE_INCOMPLETE``".

        Design: Difficulty/combinatorial_formula/evidence_completeness_waiver_cap_tier_selected_from_base_index
        """
        built = scenario_draft_packet_on_open_release(api)
        waive_item(api, built["packet"]["id"], EvidenceItem.CANARY_PASS)
        waive_item(api, built["packet"]["id"], EvidenceItem.RELEASE_NOTES)

        response = api.seal_evidence_packet(
            built["packet"]["id"], {}, COMPLIANCE_OFFICER
        )

        validate_error(response, ApiErrorId.ERR_EVIDENCE_INCOMPLETE.value, 422)
        packets, _ = validate_paginated(
            api.list_evidence_packets(built["release"]["id"], COMPLIANCE_OFFICER)
        )
        assert packets[0]["state"] == PacketState.DRAFT
