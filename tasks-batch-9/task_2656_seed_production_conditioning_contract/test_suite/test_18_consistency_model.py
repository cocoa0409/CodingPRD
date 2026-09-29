"""Every hop of a cascade is already visible in the write's own response and the next read."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    assert_certification_tag,
    assert_tag_serial_format,
    assert_tagged_bag_count_matches_issued_tags,
    create_certification_tag_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_certification_agency_headers,
    make_conditioning_manager_headers,
    make_settlement_accountant_headers,
    passed_lot_state,
    validate_success,
)


class TestTagIssuanceCascadeIsVisibleImmediately:
    def test_the_write_response_and_the_very_next_reads_already_carry_every_hop(self, api):
        """One tag POST, and both the lot and the contract are current on the first read.

        PRD: "Several operations in this system propagate through more than one hop, and consistency
        is immediate: by the time a request returns, every hop of its cascade has been applied and
        every affected resource's `version` has moved."

        PRD: "When an operation on one resource mutates a second resource as a side effect, the
        second resource's `version` increments and its `updated_at` refreshes just as if it had been
        written directly."

        PRD: "Issuing a tag mints a deterministic `tag_serial` of the form
        `TAG-{season_year}-{6-digit issuance sequence}` — the lot's season year followed by a
        six-digit, zero-padded issuance sequence number — stamps `issued_at` with the current logical
        clock instant, and puts the tag in `ISSUED` status with `void_reason` null."

        PRD: "The tag's `bag_count` is added to the lot's `tagged_bag_count`, and the lot's
        certification status advances `PASSED → TAGGED`."

        PRD: "The lot's `final_clean_units` is added to the originating contract's
        `certified_units_total` and the contract's `version` increments by 1."

        PRD: "The lot's `version` increments by 1."

        Design: Corner/consistency_model/immediate_consistency_derived_fields_visible_in_same_response
        """
        state = passed_lot_state(api)
        lot_before = state["seed_lot"]
        contract_before = state["contract"]
        assert lot_before["certification_status"] == "PASSED"
        assert contract_before["certified_units_total"] == pytest.approx(0.0, abs=0.01)

        tag = validate_success(
            api.create_certification_tag(
                create_certification_tag_payload(lot_before["id"], state["sample"]["id"]),
                make_certification_agency_headers(),
            ),
            201,
        )
        assert_certification_tag(tag)
        assert tag["status"] == "ISSUED"
        assert tag["void_reason"] is None
        assert is_valid_uuid(tag["id"])
        assert_tag_serial_format(tag["tag_serial"], TEST_DEFAULTS["SEASON_YEAR"])
        assert is_iso8601_timestamp(tag["issued_at"])
        assert tag["bag_count"] == TEST_DEFAULTS["TAG_BAG_COUNT"]

        lot_after = get_success_data(
            api.get_seed_lot(lot_before["id"], make_conditioning_manager_headers())
        )
        assert lot_after["tagged_bag_count"] == TEST_DEFAULTS["TAG_BAG_COUNT"]
        assert lot_after["certification_status"] == "TAGGED"
        assert lot_after["version"] == lot_before["version"] + 1
        assert lot_after["updated_at"] != lot_before["updated_at"]
        assert_tagged_bag_count_matches_issued_tags(lot_after, [tag])

        contract_after = get_success_data(
            api.get_production_contract(contract_before["id"], make_settlement_accountant_headers())
        )
        assert contract_after["certified_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )
        assert contract_after["version"] == contract_before["version"] + 1
        assert lot_after["final_clean_units"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )
