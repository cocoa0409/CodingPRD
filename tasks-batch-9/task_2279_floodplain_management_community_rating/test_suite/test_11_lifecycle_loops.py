"""Bounded review loops, the certificate amend loop and the compensating appeal.

Every scenario is built from scratch through PRD-declared endpoints only.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    amend_certificate,
    file_certificate,
    make_administrator_headers,
    make_appeals_board_headers,
    read_certificate,
    read_permit,
    read_structure,
    review_certificate,
    review_permit,
    setup_appealed_case,
    setup_issued_permit,
    setup_structure,
    start_permit,
    submit_permit,
    validate_error,
    validate_success,
)

ADMIN_FPA_01 = make_administrator_headers("fpa-01")
APPEALS_ABM_01 = make_appeals_board_headers("abm-01")

COMMUNITY_1_5_FT = {"freeboard_ft": 1.5, "cumulative_period_years": 10}
PANEL_AE_12 = {"flood_zone": "AE", "base_flood_elevation_ft": 12.0}


# --------------------------------------------------------------------------
# Private composites
# --------------------------------------------------------------------------

def _setup_submitted_permit():
    """A permit sitting in review for the first time, at `revision_round` 0."""
    scenario = setup_structure(
        community_overrides=COMMUNITY_1_5_FT,
        panel_overrides=PANEL_AE_12,
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "construction_year": 2005,
            "market_value_usd": 250_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    permit = start_permit(
        scenario["property"]["id"],
        scenario["structure"]["id"],
        scenario["owner_headers"],
        project_type="NEW_CONSTRUCTION",
        declared_project_cost_usd=90_000.00,
        proposed_lowest_floor_elevation_ft=20.0,
    )
    scenario["permit"] = submit_permit(permit["id"], scenario["owner_headers"])
    return scenario


def _setup_permit_at_the_revision_ceiling():
    """A permit driven through all three admitted revision rounds, back in review."""
    scenario = _setup_submitted_permit()
    permit_id = scenario["permit"]["id"]
    for round_note in ("Round 1 corrections", "Round 2 corrections", "Round 3 corrections"):
        review_permit(permit_id, "REQUEST_REVISION", review_note=round_note)
        submit_permit(permit_id, scenario["owner_headers"])
    scenario["permit"] = read_permit(permit_id)
    return scenario


def _setup_deficient_ngvd29_certificate():
    """An issued permit requiring 13.5 ft, with an NGVD29 certificate already found
    deficient for a negative freeboard margin."""
    scenario = setup_issued_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 180_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides=COMMUNITY_1_5_FT,
        panel_overrides=PANEL_AE_12,
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "construction_year": 2024,
            "market_value_usd": 275_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    certificate = file_certificate(
        scenario["permit"]["id"],
        scenario["structure"]["id"],
        scenario["owner_headers"],
        certificate_type="FINISHED_CONSTRUCTION",
        datum="NGVD29",
        measured_lowest_floor_ft=13.6,
        measured_bfe_ft=12.0,
        surveyor_license_no="TX-RPLS-4471",
    )
    scenario["certificate"] = review_certificate(
        certificate["id"],
        "DEFICIENT",
        deficiency_codes=["DATUM_MISMATCH", "SECTION_C_INCOMPLETE"],
    )
    return scenario


def _setup_sustained_ready_case():
    """A SUBSTANTIAL determination on a 200000.00 structure, already appealed by the
    owner and awaiting the board's decision."""
    return setup_appealed_case(
        records=[
            {"record_type": "IMPROVEMENT", "event_date": "2026-05-01T00:00:00Z",
             "cost_usd": 120_000.00},
        ],
        method="CUMULATIVE",
        determiner_headers=ADMIN_FPA_01,
        community_overrides=COMMUNITY_1_5_FT,
        panel_overrides=PANEL_AE_12,
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "construction_year": 1975,
            "market_value_usd": 200_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )


# ==========================================================================
# The permit revision loop
# ==========================================================================

class TestPermitRevisionLoop:

    def test_three_revision_rounds_are_admitted(self, api):
        """PRD §3.4: "On a resubmission out of `REVISION_REQUIRED`, `revision_round`
        first increases by one, and all three snapshots are refreshed from current
        community and panel state before the requirement is recomputed."
        PRD §2.5: "A permit may re-enter review only while its `revision_round` is
        strictly less than 3; a remediation order may be extended only while its
        `extension_count` is strictly less than 2."

        Design: Difficulty/non_linear_state_machine/permit_revision_loop_blocks_fourth_revision_round
        """
        scenario = _setup_submitted_permit()
        permit_id = scenario["permit"]["id"]
        assert scenario["permit"]["revision_round"] == 0

        for expected_round in (1, 2, 3):
            permit = validate_success(
                api.review_permit(
                    permit_id,
                    {"decision": "REQUEST_REVISION",
                     "review_note": "Round %d corrections" % expected_round},
                    ADMIN_FPA_01,
                ),
                200,
            )
            assert permit["status"] == "REVISION_REQUIRED"

            permit = validate_success(
                api.submit_permit(permit_id, scenario["owner_headers"]), 200
            )
            assert permit["status"] == "UNDER_REVIEW"
            assert permit["revision_round"] == expected_round

    def test_fourth_revision_request_is_rejected_at_the_ceiling(self, api):
        """PRD §3.4: "`REQUEST_REVISION` moves the permit to `REVISION_REQUIRED` and is
        itself subject to the revision ceiling, so a request that would exceed three
        rounds is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."
        PRD §3.4: "Resubmission is permitted only while `revision_round` is strictly less
        than 3; a fourth round is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/permit_revision_loop_blocks_fourth_revision_round
        """
        scenario = _setup_permit_at_the_revision_ceiling()
        permit_id = scenario["permit"]["id"]

        validate_error(
            api.review_permit(
                permit_id,
                {"decision": "REQUEST_REVISION", "review_note": "Round 4 corrections"},
                ADMIN_FPA_01,
            ),
            ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED,
        )

        permit = read_permit(permit_id)
        assert permit["status"] == "UNDER_REVIEW"
        assert permit["revision_round"] == 3


# ==========================================================================
# The certificate deficiency / amendment loop
# ==========================================================================

class TestCertificateAmendLoop:

    def test_deficient_decision_records_codes_and_the_negative_margin(self, api):
        """PRD §3.5: "The datum offset is added to `measured_lowest_floor_ft` first — the
        offset is 0.0 feet for `NAVD88` and negative 0.85 feet for `NGVD29` — and that sum
        is rounded half-up to one decimal place to yield `normalized_lowest_floor_ft`."
        PRD §3.5: "The permit's current `required_lowest_floor_elevation_ft` is then
        subtracted from that already-rounded normalized value, and the difference is
        rounded half-up to one decimal place again to yield `freeboard_margin_ft`."
        PRD §3.5: "A `DEFICIENT` decision moves the certificate to `DEFICIENT` and records
        the supplied `deficiency_codes` verbatim."
        PRD §3.5: "The amendment replaces those four values, returns the certificate to
        `SUBMITTED`, resets `deficiency_codes` to the empty list, and recomputes
        `normalized_lowest_floor_ft` and `freeboard_margin_ft`."

        Design: Difficulty/non_linear_state_machine/certificate_deficiency_amend_loop_then_accepted_at_zero_margin
        """
        scenario = _setup_deficient_ngvd29_certificate()
        certificate = scenario["certificate"]

        assert certificate["status"] == "DEFICIENT"
        assert certificate["deficiency_codes"] == ["DATUM_MISMATCH", "SECTION_C_INCOMPLETE"]
        assert float(certificate["normalized_lowest_floor_ft"]) == pytest.approx(
            12.8, abs=0.01
        )
        assert float(certificate["freeboard_margin_ft"]) == pytest.approx(-0.7, abs=0.01)

        amended = validate_success(
            api.amend_certificate(
                certificate["id"],
                {
                    "datum": "NAVD88",
                    "measured_lowest_floor_ft": 13.5,
                    "measured_bfe_ft": 12.0,
                    "surveyor_license_no": "TX-RPLS-4471",
                },
                scenario["owner_headers"],
            ),
            200,
        )

        assert amended["status"] == "SUBMITTED"
        assert amended["deficiency_codes"] == []
        assert float(amended["normalized_lowest_floor_ft"]) == pytest.approx(13.5, abs=0.01)
        assert float(amended["freeboard_margin_ft"]) == pytest.approx(0.0, abs=0.01)

    def test_amended_certificate_is_accepted_at_exactly_zero_margin(self, api):
        """PRD §3.5: "Acceptance additionally requires that the certificate's
        `structure_id` still equals its permit's `structure_id` and that
        `freeboard_margin_ft` be at least 0.0 feet; a negative margin is rejected with
        `ERR_ELEVATION_BELOW_REQUIRED`."
        PRD §2.6: "All threshold comparisons in this domain are inclusive on the passing
        side unless stated otherwise: a ratio that lands exactly on 50 percent is
        substantial, a coverage figure that lands exactly on 75 percent earns partial
        credit, and a freeboard margin of exactly 0.0 feet is acceptable."
        PRD §3.5: "And when the accepted certificate's `certificate_type` is
        `FINISHED_CONSTRUCTION`, the structure's `lowest_floor_elevation_ft` is set to the
        certificate's `normalized_lowest_floor_ft` and the structure's
        `compliance_status` becomes `COMPLIANT` — unless the structure carries a violation
        whose `status` is `OPEN`, `ORDER_ISSUED`, or `ESCALATED`, in which case the
        elevation is recorded but the compliance status is left where enforcement put it."

        Design: Difficulty/non_linear_state_machine/certificate_deficiency_amend_loop_then_accepted_at_zero_margin
        """
        scenario = _setup_deficient_ngvd29_certificate()
        certificate_id = scenario["certificate"]["id"]
        amend_certificate(
            certificate_id,
            scenario["owner_headers"],
            datum="NAVD88",
            measured_lowest_floor_ft=13.5,
            measured_bfe_ft=12.0,
            surveyor_license_no="TX-RPLS-4471",
        )

        accepted = validate_success(
            api.review_certificate(certificate_id, {"decision": "ACCEPT"}, ADMIN_FPA_01),
            200,
        )

        assert accepted["status"] == "ACCEPTED"
        assert accepted["datum"] == "NAVD88"
        assert float(accepted["normalized_lowest_floor_ft"]) == pytest.approx(13.5, abs=0.01)
        assert float(accepted["freeboard_margin_ft"]) == pytest.approx(0.0, abs=0.01)
        assert accepted["deficiency_codes"] == []

        structure = read_structure(scenario["structure"]["id"])
        assert float(structure["lowest_floor_elevation_ft"]) == pytest.approx(13.5, abs=0.01)
        assert structure["compliance_status"] == "COMPLIANT"

        assert read_certificate(certificate_id)["status"] == "ACCEPTED"


# ==========================================================================
# The compensating appeal branch
# ==========================================================================

class TestAppealSustainBranch:

    def test_sustained_appeal_flips_the_outcome_and_records_the_board(self, api):
        """PRD §3.7: "`SUSTAIN` moves the case to the terminal `APPEAL_SUSTAINED`, records
        `appeal_decided_by_user_id`, flips `outcome` to `NOT_SUBSTANTIAL`, reverts the
        structure's `substantial_status` to `NONE`, and recomputes
        `required_lowest_floor_elevation_ft` for every permit of that structure whose
        `status` is `UNDER_REVIEW`, `REVISION_REQUIRED`, or `APPROVED` — it fully
        compensates the determination."
        PRD §3.7: "Determination stamps `determined_by_user_id` with the acting
        administrator's identifier, `determined_at` with the current logical clock, and
        `appeal_deadline_at` with 30 days after `determined_at`."

        Design: Difficulty/non_linear_state_machine/appeal_sustain_branch_compensates_substantial_improvement
        """
        scenario = _setup_sustained_ready_case()

        case = validate_success(
            api.decide_appeal(
                scenario["case"]["id"],
                {"decision": "SUSTAIN",
                 "decision_note": "Revised cost documentation accepted"},
                APPEALS_ABM_01,
            ),
            200,
        )

        assert case["status"] == "APPEAL_SUSTAINED"
        assert case["outcome"] == "NOT_SUBSTANTIAL"
        assert case["appeal_decided_by_user_id"] == "abm-01"
        assert case["determined_by_user_id"] == "fpa-01"

    def test_sustained_appeal_reverts_the_structure_but_keeps_the_ledger(self, api):
        """PRD §3.7: "`SUSTAIN` moves the case to the terminal `APPEAL_SUSTAINED`, records
        `appeal_decided_by_user_id`, flips `outcome` to `NOT_SUBSTANTIAL`, reverts the
        structure's `substantial_status` to `NONE`, and recomputes
        `required_lowest_floor_elevation_ft` for every permit of that structure whose
        `status` is `UNDER_REVIEW`, `REVISION_REQUIRED`, or `APPROVED` — it fully
        compensates the determination."
        PRD §3.6: "`cumulative_improvement_pct` is that windowed sum divided by the
        denominator, multiplied by 100, rounded half-up to two decimals;
        `single_event_improvement_pct` is the anchor's own `cost_usd` divided by the same
        denominator, multiplied by 100, rounded half-up to two decimals."

        Design: Difficulty/non_linear_state_machine/appeal_sustain_branch_compensates_substantial_improvement
        """
        scenario = _setup_sustained_ready_case()

        case = validate_success(
            api.decide_appeal(
                scenario["case"]["id"],
                {"decision": "SUSTAIN",
                 "decision_note": "Revised cost documentation accepted"},
                APPEALS_ABM_01,
            ),
            200,
        )

        assert float(case["computed_ratio_pct"]) == pytest.approx(60.00, abs=0.01)

        structure = read_structure(scenario["structure"]["id"])
        assert structure["substantial_status"] == "NONE"
        assert float(structure["cumulative_improvement_pct"]) == pytest.approx(
            60.00, abs=0.01
        )
