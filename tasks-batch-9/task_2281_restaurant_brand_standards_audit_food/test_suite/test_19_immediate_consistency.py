"""The widest write in the system settles every cascade before its response returns."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    FIRST_VISIT_END,
    SCORE_SHEET_ONE_CRITICAL,
    api_client,
    assert_instant,
    finalize_visit,
    setup_submitted_visit,
    validate_paginated,
    validate_success,
)


class TestFinalizeConsistency:
    def test_the_finalize_response_already_carries_every_cascaded_value(self):
        """Follow-up reads add no information, and repeating them changes nothing.

        PRD: "Because these cascades are immediate and synchronous, a read taken after any
        triggering write already reflects the complete cascade. There is no eventual-consistency
        window and no deferred job."

        Design: Corner/consistency_model/every_cascaded_field_is_readable_in_the_response_that_caused_it
        """
        program = setup_submitted_visit(sheet=SCORE_SHEET_ONE_CRITICAL)
        location_id = program["location"]["id"]
        brand_id = program["brand"]["id"]

        finalized = finalize_visit(program, program["visit"]["id"], at=FIRST_VISIT_END)
        assert finalized["status"] == "FINALIZED"
        assert finalized["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert finalized["composite_variant"] == "FINAL"
        assert finalized["grade"] == "PASS"
        assert_instant(finalized["finalized_at"], FIRST_VISIT_END, "finalized_at")

        location = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert location["standing_score"] == pytest.approx(90.70, abs=0.01), \
            "the location already agrees with the visit that caused it"
        assert location["latest_grade"] == "PASS"
        assert location["open_corrective_action_count"] == 3

        rows, meta = validate_paginated(
            api_client.list_corrective_actions(
                ADMIN_HEADERS, params={"location_id": location_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3, "all three remediations exist by the first read"
        assert rows[0]["status"] == "ASSIGNED"

        auditor = validate_success(
            api_client.get_auditor(program["auditor"]["id"], ADMIN_HEADERS)
        )
        assert auditor["finalized_visit_count"] == 1

        risk = validate_success(api_client.get_brand_risk_index(brand_id, ADMIN_HEADERS))
        assert risk["brand_risk_index"] == pytest.approx(11.58, abs=0.01)
        assert risk["rated_location_count"] == 1, \
            "the auditor counter and the brand aggregate settled in the same instant"

        location_again = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert location_again["standing_score"] == pytest.approx(
            location["standing_score"], abs=0.01
        )
        assert location_again["open_corrective_action_count"] == \
            location["open_corrective_action_count"]
        assert location_again["latest_grade"] == location["latest_grade"]

        risk_again = validate_success(api_client.get_brand_risk_index(brand_id, ADMIN_HEADERS))
        assert risk_again["brand_risk_index"] == pytest.approx(
            risk["brand_risk_index"], abs=0.01
        ), "repeating a read never advances the state"
        assert risk_again["rated_location_count"] == risk["rated_location_count"]
