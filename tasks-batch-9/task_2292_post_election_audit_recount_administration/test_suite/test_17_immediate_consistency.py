"""Immediate consistency: the writing response already carries every recomputed roll-up."""

import pytest

from test_helpers import (
    api_client,
    assertions,
    constants,
    fixtures,
    make_tally_team_lead_headers,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]

CANVASS_DAY = constants.TEST_DEFAULTS["CLOCK_CANVASS_DAY"]


class TestDerivedValuesAreVisibleImmediately:
    """One submit, and the ledger, the measure, the status and the flag have all moved."""

    def test_the_submit_response_carries_the_recomputed_figures_with_no_further_read(self):
        """PRD §2.8: "Every derived value in this service is recomputed inside the request that
        invalidated it. There is no read-time reconciliation, no deferred job, and no endpoint
        whose sole purpose is to repair a roll-up. When a request causes a cascade, every entity
        the cascade touches has its `updated_at` refreshed and its `version` incremented by 1".
        PRD §1: "If a hand tally is submitted and its arithmetic disagrees with the machine, the
        finding, the round's ledger, the audit's status and the election's risk flag all move
        before the response is written." §3.5: "`relative_taint` is `net_error_votes` multiplied
        by the contest's `margin_votes`, divided by twice the drawn batch's `ballot_count`,
        rounded half up to four decimal places."

        Design: Corner/consistency_model/every_derived_value_is_visible_in_the_writing_response
        """
        scenario = fixtures.setup_draft_tally(
            counted_votes={"ALVAREZ": 522, "BRENNAN": 478}
        )
        team_id = scenario["team"]["id"]
        tally_id = scenario["manual_tally"]["id"]
        assert scenario["manual_tally"]["status"] == "DRAFT"
        assert scenario["manual_tally"]["version"] == 1

        written = validate_success(
            api_client.submit_manual_tally(
                tally_id, make_tally_team_lead_headers(team_id)
            )
        )

        assertions.assert_manual_tally(written)
        assert written["status"] == "SUBMITTED"
        assert written["machine_margin_votes"] == 50
        assert written["manual_margin_votes"] == 44
        assert written["net_error_votes"] == 6
        assert written["relative_taint"] == pytest.approx(0.9000, abs=0.00005)
        assertions.assert_four_decimal_places(written["relative_taint"], "relative_taint")
        assert written["version"] == 2
        assertions.assert_same_instant(written["submitted_at"], CANVASS_DAY, "submitted_at")

        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["round_measure"] == pytest.approx(0.0060, abs=0.00005)
        assert audit_round["counted_ballots"] == 1000
        assert audit_round["cumulative_net_error_votes"] == 6
        assert audit_round["discrepancy_count"] == 1
        assert audit_round["status"] == "REVIEW_REQUIRED"
        audit = fixtures.read_audit(scenario["audit"]["id"])
        assert audit["discrepancy_measure"] == pytest.approx(0.0060, abs=0.00005)
        assert audit["status"] == "DISCREPANCY_REVIEW"
        election = fixtures.read_election(scenario["election"]["id"])
        assert election["certification_risk_flag"] is True
        findings, meta = validate_paginated(
            api_client.list_discrepancies(
                AUDIT_MANAGER, params={"manual_tally_id": tally_id, "limit": 10}
            )
        )
        assert meta["total_count"] == 1
        finding = findings[0]
        assertions.assert_discrepancy(finding)
        assert finding["magnitude_votes"] == 6
        assert finding["discrepancy_type"] == "OVERSTATEMENT"
        assert finding["status"] == "OPEN"
        drawn = fixtures.read_audit_batch(scenario["target_audit_batch"]["id"])
        assert drawn["tally_status"] == "COUNTED"
