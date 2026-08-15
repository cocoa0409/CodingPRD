"""Privilege delineation: evaluation gating, tiered scoring, and OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_delineation,
    assert_delineation,
    create_criteria,
    create_delineation_payload,
    create_draft_application,
    create_member_record,
    create_submitted_application,
    refresh_application,
    refresh_delineation,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]

CARD_CATH = {
    "specialty_code": "CARD",
    "privilege_line": "CARD-CATH",
    "min_training_months": 24,
    "min_case_volume_24mo": 50,
    "required_board_cert": True,
    "fppe_case_count": 5,
    "volume_tier_table": [
        {"tier_name": "BASIC", "min_cases": 50, "score_multiplier": 0.10},
        {"tier_name": "ADVANCED", "min_cases": 200, "score_multiplier": 0.25},
        {"tier_name": "EXPERT", "min_cases": 500, "score_multiplier": 0.40},
    ],
}

BOARD_CERT_CRED = {
    "credential_kind": "BOARD_CERT",
    "credential_number": "BC-1",
    "issued_on": "2026-01-01T00:00:00Z",
    "expires_on": "2027-08-01T00:00:00Z",
}


def _card_workspace(name, npdb, training_months, cases_24mo,
                    criteria_overrides=None):
    """Member with a CURRENT board-cert credential and a SUBMITTED application
    carrying one CARD-CATH delineation with the given attested numbers."""
    overrides = dict(CARD_CATH)
    if criteria_overrides:
        overrides.update(criteria_overrides)
    return create_submitted_application(
        name, npdb,
        criteria_overrides=overrides,
        credentials=[dict(BOARD_CERT_CRED)],
        delineation_overrides={
            "privilege_line": "CARD-CATH",
            "documented_training_months": training_months,
            "documented_cases_24mo": cases_24mo,
        })


class TestDelineationEvaluationGating:
    def test_delineation_evaluation_blocked_while_application_in_draft(self, api):
        """PRD §3.3: "Evaluation by a coordinator requires the delineation to
        still be in `REQUESTED` (`ERR_DELINEATION_NOT_EVALUABLE`) and the parent
        application to be in `SUBMITTED`, `PSV_IN_PROGRESS`, or `PSV_COMPLETE`
        (`ERR_APPLICATION_NOT_IN_REVIEW`) — evaluation after committee advancement
        is too late."

        Design: Difficulty/cross_entity_state_dependency/delineation_evaluation_gated_by_application_state
        """
        create_criteria()
        member = create_member_record("Dr. G", "NPDB-G1", "EMED")
        application = create_draft_application(member)
        delineation = add_delineation(application["id"])

        resp = api.evaluate_delineation(delineation["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_IN_REVIEW, 409)
        assert refresh_delineation(
            delineation["id"])["delineation_status"] == "REQUESTED"
        assert refresh_application(
            application["id"])["application_status"] == "DRAFT"

    def test_delineation_evaluation_allowed_once_application_submitted(self, api):
        """PRD §3.3: "Evaluation by a coordinator requires the delineation to
        still be in `REQUESTED` (`ERR_DELINEATION_NOT_EVALUABLE`) and the parent
        application to be in `SUBMITTED`, `PSV_IN_PROGRESS`, or `PSV_COMPLETE`
        (`ERR_APPLICATION_NOT_IN_REVIEW`) — evaluation after committee advancement
        is too late."

        The same call that failed against a DRAFT application succeeds once the
        application is SUBMITTED.

        Design: Difficulty/cross_entity_state_dependency/delineation_evaluation_gated_by_application_state
        """
        ws = create_submitted_application("Dr. G2", "NPDB-G2")
        delineation = validate_success(
            api.evaluate_delineation(ws["delineation"]["id"], COORD))
        assert_delineation(delineation)
        assert delineation["delineation_status"] == "CRITERIA_MET"
        # 24 training months vs 12 required, 100 cases, single BASIC tier at 10:
        # base 0.10 * 100 = 10.00, training bonus min(24-12, 24) * 0.5 = 6.00.
        assert delineation["satisfaction_tier"] == "BASIC"
        assert delineation["satisfaction_score"] == 16.00


class TestDelineationScoring:
    def test_delineation_tiered_scoring_met_with_advanced_tier(self, api):
        """PRD §3.3: "The criteria's `volume_tier_table` is walked in ascending
        `min_cases` order, and the selected tier is the last tier whose
        `min_cases` is at most the documented case volume."
        PRD §3.3: "The selected tier's `score_multiplier` is multiplied by the
        documented case volume capped at one thousand cases — volumes above the
        cap contribute no further base score."
        PRD §3.3: "The excess of `documented_training_months` over
        `min_training_months`, capped above at twenty-four months and never
        allowed below zero, is multiplied by one-half point per excess month."

        250 cases selects ADVANCED (last tier with min_cases <= 250);
        base = 0.25 * 250 = 62.50; bonus = min(30-24, 24) * 0.5 = 3.00;
        score = 65.50.

        Design: Difficulty/combinatorial_formula/delineation_tiered_scoring_with_nested_minmax
        """
        ws = _card_workspace("Dr. C", "NPDB-C", 30, 250)
        delineation = validate_success(
            api.evaluate_delineation(ws["delineation"]["id"], COORD))
        assert delineation["delineation_status"] == "CRITERIA_MET"
        assert delineation["satisfaction_tier"] == "ADVANCED"
        assert delineation["satisfaction_score"] == 65.50

    def test_delineation_volume_below_minimum_pins_unmet(self, api):
        """PRD §3.3: "**Volume gate.** The applicant's `documented_cases_24mo`
        must be at least the criteria's `min_case_volume_24mo`."
        PRD §3.3: "The delineation lands in `CRITERIA_MET` only when the
        mandatory gate passes, the volume gate passes, and the selected tier is
        not `UNMET`; otherwise it lands in `CRITERIA_UNMET`, with
        `satisfaction_tier` pinned to `UNMET` whenever any mandatory criterion
        fails."

        49 < 50 documented cases fails the volume gate despite identical
        training and a current board certification.

        Design: Difficulty/combinatorial_formula/delineation_tiered_scoring_with_nested_minmax
        """
        ws = _card_workspace("Dr. D", "NPDB-D", 30, 49)
        delineation = validate_success(
            api.evaluate_delineation(ws["delineation"]["id"], COORD))
        assert delineation["delineation_status"] == "CRITERIA_UNMET"
        assert delineation["satisfaction_tier"] == "UNMET"

    def test_delineation_tier_unmet_when_below_first_tier(self, api):
        """PRD §3.3: "When the volume falls below even the first tier's
        `min_cases`, no tier qualifies and the tier is `UNMET`."

        Design: Corner/calculations/delineation_tier_unmet_when_below_first_tier
        """
        ws = _card_workspace(
            "Dr. LowVol", "NPDB-LV", 36, 10,
            criteria_overrides={
                "volume_tier_table": [
                    {"tier_name": "BASIC", "min_cases": 50,
                     "score_multiplier": 0.10},
                    {"tier_name": "ADVANCED", "min_cases": 200,
                     "score_multiplier": 0.25},
                ],
            })
        delineation = validate_success(
            api.evaluate_delineation(ws["delineation"]["id"], COORD))
        assert delineation["delineation_status"] == "CRITERIA_UNMET"
        assert delineation["satisfaction_tier"] == "UNMET"


class TestDelineationOcc:
    def test_occ_delineation_create_stale_application_version(self, api):
        """PRD §2.7: "If the application's version has advanced since the client
        last read it — the application may have been advanced to committee review
        or withdrawn by another writer — the delineation creation is rejected
        with `ERR_STALE_VERSION` (HTTP 412) rather than attaching a new
        delineation to a stale snapshot."
        PRD §3.3: "creating a delineation increments the parent application's
        `version` by one."

        Design: Corner/cross_cutting_layers/occ_delineation_create_stale_application_version
        """
        create_criteria(specialty_code="CARD", privilege_line="CARD-CATH",
                        min_training_months=24, min_case_volume_24mo=50,
                        required_board_cert=False, fppe_case_count=5,
                        volume_tier_table=[
                            {"tier_name": "BASIC", "min_cases": 50,
                             "score_multiplier": 0.10}])
        create_criteria(specialty_code="CARD", privilege_line="CARD-ECHO",
                        min_training_months=12, min_case_volume_24mo=20,
                        required_board_cert=False, fppe_case_count=3,
                        volume_tier_table=[
                            {"tier_name": "BASIC", "min_cases": 20,
                             "score_multiplier": 0.10}])
        member = create_member_record("Dr. OCC2", "NPDB-OCC2", "CARD")
        application = create_draft_application(member)
        v0 = application["version"]

        validate_success(
            api.create_delineation(
                create_delineation_payload(application["id"], v0,
                                           privilege_line="CARD-CATH",
                                           documented_training_months=30,
                                           documented_cases_24mo=100),
                COORD), 201)

        stale = api.create_delineation(
            create_delineation_payload(application["id"], v0,
                                       privilege_line="CARD-ECHO",
                                       documented_training_months=20,
                                       documented_cases_24mo=60),
            COORD)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        v1 = refresh_application(application["id"])["version"]
        validate_success(
            api.create_delineation(
                create_delineation_payload(application["id"], v1,
                                           privilege_line="CARD-ECHO",
                                           documented_training_months=20,
                                           documented_cases_24mo=60),
                COORD), 201)

        delineations, meta = validate_paginated(
            api.list_delineations(COORD,
                                  params={"application_id": application["id"]}))
        assert len(delineations) == 2, (
            "Only the two version-current delineation creates may persist")
