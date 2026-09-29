"""State machines that revisit states, fork on a computed value, or run in parallel."""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    CASE_MANAGER_ALT,
    CASE_MANAGER_ONE,
    CASE_MANAGER_TWO,
    PROVIDER_ADMIN,
    admit_eligible_panelists,
    api_client,
    assert_appointment,
    clear_compliance,
    cure_deficiency,
    deficiency_notice_payload,
    file_court_challenge,
    fund_case_to_assessment,
    issue_deficiency_notice,
    nominate_seat,
    precedent_entry_of,
    publish_decision,
    publish_payload,
    read_appointment,
    read_case,
    read_complainant,
    read_decision,
    read_domain,
    read_panelist,
    resolve_court_challenge,
    screen_seat,
    set_clock,
    setup_filed_case,
    setup_issued_single_member_decision,
    setup_responded_case,
    validate_error,
    validate_paginated,
    waive_seat,
    waiver_payload,
)

LOOP_DOCKET = {
    "iana_id": "IANA-7007",
    "domain_name": "loopcase.example",
    "legal_name": "Loop BV",
    "country_code": "FR",
}
FORK_DOCKET = {
    "iana_id": "IANA-8008",
    "domain_name": "threeway.example",
    "legal_name": "Fork SA",
    "country_code": "FR",
}
TWO_DIM_DOCKET = {
    "iana_id": "IANA-9009",
    "domain_name": "twodim.example",
    "legal_name": "Two Dim Oy",
    "country_code": "FR",
}


class TestDeficiencyCorrectionLoop:
    def test_the_notice_and_cure_loop_returns_the_case_to_the_state_it_started_from(self):
        """PRD §3.4: "The notice is created in `status` `OPEN`, stamps `issued_at`
        from the logical clock, records the issuing case manager in
        `issued_by_user_id`, sets `round_number` to the case's
        `deficiency_round_count` plus one — never exceeding 2 — and sets
        `correction_deadline_at` to `issued_at` plus `correction_days` days."
        PRD §3.4: "The notice becomes `CURED` with `cured_at` stamped from the
        clock, and the case returns from `DEFICIENT` to `FILED`."

        Design: Difficulty/non_linear_state_machine/case_deficiency_correction_cycle_runs_twice_then_hits_the_round_limit
        """
        bundle = setup_filed_case(**LOOP_DOCKET)
        case_id = bundle["case"]["id"]
        complainant_id = bundle["complainant"]["id"]

        first = issue_deficiency_notice(
            case_id, deficiency_codes=["MUTUAL_JURISDICTION_ABSENT"], correction_days=5
        )
        assert first["status"] == "OPEN"
        assert first["round_number"] == 1
        assert first["issued_at"] == "2026-08-01T00:00:00.000Z"
        assert first["issued_by_user_id"] == CASE_MANAGER_ONE
        assert first["correction_deadline_at"] == "2026-08-06T00:00:00.000Z"
        deficient = read_case(case_id)
        assert deficient["status"] == "DEFICIENT"
        assert deficient["deficiency_round_count"] == 1
        assert deficient["last_deficiency_issuer_user_id"] == CASE_MANAGER_ONE

        cured = cure_deficiency(
            case_id, first["id"], complainant_id,
            notes="Mutual jurisdiction consent appended.",
        )
        assert cured["status"] == "CURED"
        assert cured["cured_at"] == "2026-08-01T00:00:00.000Z"
        assert read_case(case_id)["status"] == "FILED"

        second = issue_deficiency_notice(
            case_id, CASE_MANAGER_ALT,
            deficiency_codes=["ILLEGIBLE_EVIDENCE_ANNEX", "MISSING_SIGNATURE"],
            correction_days=5,
        )
        assert second["round_number"] == 2
        assert second["issued_by_user_id"] == CASE_MANAGER_TWO
        after_second = read_case(case_id)
        assert after_second["status"] == "DEFICIENT"
        assert after_second["deficiency_round_count"] == 2
        assert after_second["last_deficiency_issuer_user_id"] == CASE_MANAGER_TWO
        cured_again = cure_deficiency(
            case_id, second["id"], complainant_id,
            notes="Legible annex and signature page filed.",
        )
        assert cured_again["status"] == "CURED"
        assert read_case(case_id)["status"] == "FILED"

    def test_a_third_notice_from_the_same_filed_state_hits_the_round_ceiling(self):
        """PRD §3.4: "The case's `deficiency_round_count` must be below the ceiling
        of 2 rounds; a third notice is refused with
        `ERR_DEFICIENCY_ROUND_LIMIT`."
        PRD §3.4: "A successful clearance records the clearing officer on the case
        as `compliance_cleared_by_user_id`, moves the case from `FILED` to
        `VERIFICATION_PENDING`, and cascades into the registrar: a verification
        request row is created for the case in `status` `REQUESTED`, with
        `requested_at` at the current logical-clock instant and `due_at` that many
        hours later, where the number of hours is the sponsoring registrar's own
        `verification_response_hours`."

        Design: Difficulty/non_linear_state_machine/case_deficiency_correction_cycle_runs_twice_then_hits_the_round_limit
        """
        bundle = setup_filed_case(**LOOP_DOCKET)
        case_id = bundle["case"]["id"]
        complainant_id = bundle["complainant"]["id"]
        first = issue_deficiency_notice(case_id, deficiency_codes=["MUTUAL_JURISDICTION_ABSENT"])
        cure_deficiency(case_id, first["id"], complainant_id)
        second = issue_deficiency_notice(case_id, CASE_MANAGER_ALT, deficiency_codes=["MISSING_SIGNATURE"])
        cure_deficiency(case_id, second["id"], complainant_id)

        refused = api_client.create_deficiency_notice(
            case_id, deficiency_notice_payload(deficiency_codes=["MISSING_SIGNATURE"]), CASE_MANAGER
        )
        validate_error(refused, ApiErrorId.ERR_DEFICIENCY_ROUND_LIMIT.value, 409)
        unchanged = read_case(case_id)
        assert unchanged["deficiency_round_count"] == 2
        assert unchanged["status"] == "FILED"
        assert unchanged["last_deficiency_issuer_user_id"] == CASE_MANAGER_TWO
        rows, meta = validate_paginated(
            api_client.list_deficiency_notices(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2
        assert [row["round_number"] for row in rows] == [1, 2]

        cleared = clear_compliance(case_id, reviewer_notes="Both deficiency rounds cured.")
        assert cleared["status"] == "VERIFICATION_PENDING"
        assert cleared["compliance_cleared_by_user_id"] == CASE_MANAGER_ONE


class TestScreeningForksThreeWays:
    def _three_nominated_seats(self):
        bundle = setup_responded_case(requests_three_member_panel=True, **FORK_DOCKET)
        fund_case_to_assessment(bundle["case"]["id"])
        panelists = admit_eligible_panelists(3)
        seats = ["PRESIDING", "CO_PANELIST_1", "CO_PANELIST_2"]
        nominators = ["PROVIDER", "COMPLAINANT", "RESPONDENT"]
        appointments = [
            nominate_seat(bundle["case"]["id"], seat, panelist["id"], nominated_by=nominated_by)
            for seat, panelist, nominated_by in zip(seats, panelists, nominators)
        ]
        assert [a["status"] for a in appointments] == ["NOMINATED", "NOMINATED", "NOMINATED"]
        bundle["panelists"] = panelists
        bundle["appointments"] = appointments
        return bundle

    def test_one_screening_endpoint_lands_three_nominated_rows_in_three_states(self):
        """PRD §3.6: "A score at or above the disqualification threshold of 60
        sends the seat straight to `CONFLICTED`, taking no load and requiring no
        further step — exactly 60.00 disqualifies."
        PRD §3.6: "A score at or above the waiver threshold of 30 but below 60
        sends the seat to `WAIVER_PENDING`, again taking no load, and the seat
        waits on the parties' consent — exactly 30.00 requires a waiver."

        Design: Difficulty/non_linear_state_machine/appointment_screening_forks_three_ways_out_of_one_nominated_state
        """
        bundle = self._three_nominated_seats()
        clean, waivable, conflicted = bundle["appointments"]
        pan_clean, pan_waivable, pan_conflicted = bundle["panelists"]

        screened_clean = screen_seat(clean["id"], pan_clean["id"])
        assert_appointment(screened_clean)
        assert float(screened_clean["conflict_score"]) == 0.00
        assert screened_clean["status"] == "ACCEPTED"
        assert screened_clean["accepted_at"] == "2026-08-01T00:00:00.000Z"
        assert screened_clean["decision_due_at"] == "2026-08-15T00:00:00.000Z"
        assert screened_clean["conflict_factors"] == []

        screened_waivable = screen_seat(
            waivable["id"], pan_waivable["id"], disclosed_same_firm=True
        )
        assert float(screened_waivable["conflict_score"]) == 35.00
        assert screened_waivable["status"] == "WAIVER_PENDING"
        assert screened_waivable["accepted_at"] is None
        assert screened_waivable["conflict_factors"] == ["SAME_FIRM"]

        screened_conflicted = screen_seat(
            conflicted["id"], pan_conflicted["id"],
            disclosed_financial_interest=True, months_since_last_contact=6,
        )
        assert float(screened_conflicted["conflict_score"]) == 60.00
        assert screened_conflicted["status"] == "CONFLICTED"
        assert screened_conflicted["accepted_at"] is None
        assert screened_conflicted["conflict_factors"] == ["FINANCIAL_INTEREST"]

        assert read_panelist(pan_clean["id"])["active_case_load"] == 1
        assert read_panelist(pan_waivable["id"])["active_case_load"] == 0
        assert read_panelist(pan_conflicted["id"])["active_case_load"] == 0
        assert read_case(bundle["case"]["id"])["status"] == "PANEL_APPOINTMENT", (
            "one accepted seat out of three required does not constitute the panel"
        )

    def test_only_the_waiver_pending_fork_can_be_consented_out_of(self):
        """PRD §3.6: "The seat must be in `WAIVER_PENDING`, and its
        `conflict_score` must be below 60, or the request is refused with
        `ERR_CONFLICT_NOT_WAIVABLE`."
        PRD §3.6: "Both consents are stored on the seat, the engagement-window and
        capacity checks are re-run exactly as they are on direct acceptance, and
        the seat moves from `WAIVER_PENDING` to `ACCEPTED` with `accepted_at`,
        `decision_due_at` and the load increment."

        Design: Difficulty/non_linear_state_machine/appointment_screening_forks_three_ways_out_of_one_nominated_state
        """
        bundle = self._three_nominated_seats()
        clean, waivable, conflicted = bundle["appointments"]
        pan_clean, pan_waivable, pan_conflicted = bundle["panelists"]
        screen_seat(clean["id"], pan_clean["id"])
        screen_seat(waivable["id"], pan_waivable["id"], disclosed_same_firm=True)
        screen_seat(
            conflicted["id"], pan_conflicted["id"],
            disclosed_financial_interest=True, months_since_last_contact=6,
        )

        refused = api_client.record_waiver(
            conflicted["id"], waiver_payload(waiver_respondent=False), CASE_MANAGER
        )
        validate_error(refused, ApiErrorId.ERR_CONFLICT_NOT_WAIVABLE.value, 409)
        assert read_appointment(conflicted["id"])["status"] == "CONFLICTED"

        waived = waive_seat(waivable["id"])
        assert waived["status"] == "ACCEPTED"
        assert waived["accepted_at"] == "2026-08-01T00:00:00.000Z"
        assert read_panelist(pan_waivable["id"])["active_case_load"] == 1
        assert read_case(bundle["case"]["id"])["status"] == "PANEL_APPOINTMENT", (
            "two of the three required seats are accepted, so the panel is still short"
        )


class TestIndependentDecisionDimensions:
    def test_publication_advances_its_own_dimension_and_leaves_the_status_alone(self):
        """PRD §3.9: "A redaction level of `NONE` drives `publication_status` to
        `PUBLISHED`; either `PARTY_NAMES` or `FULL` drives it to `REDACTED`."
        PRD §3.9: "Exactly one precedent entry exists per decision, created with
        `published_at` stamped from the clock, the supplied `redaction_level` and
        `precedent_tags`, `superseded` false, and `citable` true unless the
        redaction level was `FULL`."

        Design: Difficulty/non_linear_state_machine/decision_status_and_publication_dimensions_advance_independently
        """
        bundle = setup_issued_single_member_decision(vote="TRANSFER", **TWO_DIM_DOCKET)
        decision_id = bundle["decision"]["id"]
        entry = publish_decision(
            decision_id, "PARTY_NAMES",
            precedent_tags=["identical_mark", "ppc_parking"],
            digest_text="Transfer ordered; party names withheld at the respondent's request.",
        )
        decision = read_decision(decision_id)
        assert decision["publication_status"] == "REDACTED"
        assert decision["status"] == "ISSUED", (
            "publication does not move the enforcement dimension"
        )
        assert entry["published_at"] == "2026-08-01T00:00:00.000Z"
        assert entry["redaction_level"] == "PARTY_NAMES"
        assert entry["precedent_tags"] == ["identical_mark", "ppc_parking"]
        assert entry["superseded"] is False
        assert entry["citable"] is True
        assert entry["citation_count"] == 0
        assert float(entry["precedent_weight"]) == 0.00

        again = api_client.publish_decision(
            decision_id, publish_payload("NONE"), PROVIDER_ADMIN
        )
        validate_error(again, ApiErrorId.ERR_ALREADY_PUBLISHED.value, 409)
        assert read_decision(decision_id)["publication_status"] == "REDACTED"

    def test_a_sustained_challenge_voids_the_status_while_the_entry_stays_published(self):
        """PRD §3.8: "If the voided decision had already been published, its
        precedent entry's `superseded` becomes true while its
        `publication_status` is left exactly as it was — publication is never
        rolled back, only marked as superseded."
        PRD §3.9: "Entries whose decision was voided are excluded from the search
        unless `include_superseded` is true, and entries published under a `FULL`
        redaction are never citable and never listed at all, regardless of any
        filter."

        Design: Difficulty/non_linear_state_machine/decision_status_and_publication_dimensions_advance_independently
        """
        bundle = setup_issued_single_member_decision(vote="TRANSFER", **TWO_DIM_DOCKET)
        decision_id = bundle["decision"]["id"]
        publish_decision(
            decision_id, "PARTY_NAMES", precedent_tags=["identical_mark", "ppc_parking"]
        )

        set_clock("2026-08-05T00:00:00Z")
        challenge = file_court_challenge(bundle, "RESPONDENT")
        assert challenge["status"] == "FILED"
        assert challenge["filed_at"] == "2026-08-05T00:00:00.000Z"
        stayed = read_decision(decision_id)
        assert stayed["status"] == "STAYED"
        assert stayed["publication_status"] == "REDACTED"
        assert read_case(bundle["case"]["id"])["status"] == "STAYED"

        set_clock("2026-08-10T00:00:00Z")
        resolve_court_challenge(
            challenge["id"], "SUSTAINED",
            resolution_note="The district court set the panel decision aside.",
        )
        voided = read_decision(decision_id)
        assert voided["status"] == "VOIDED"
        assert voided["voided_at"] == "2026-08-10T00:00:00.000Z"
        assert voided["publication_status"] == "REDACTED", (
            "the publication dimension is untouched by the status dimension"
        )
        entry = precedent_entry_of(decision_id)
        assert entry["superseded"] is True
        assert entry["citable"] is False
        assert entry["redaction_level"] == "PARTY_NAMES"

        case = read_case(bundle["case"]["id"])
        assert case["status"] == "TERMINATED_COURT"
        assert case["closed_at"] == "2026-08-10T00:00:00.000Z"
        assert case["refiling_bar_until"] == "2026-09-09T00:00:00.000Z"
        assert read_domain(bundle["domain"]["id"])["lock_status"] == "UNLOCKED"
        assert read_appointment(bundle["appointments"][0]["id"])["status"] == "DISCHARGED"
        assert read_panelist(bundle["panelists"][0]["id"])["active_case_load"] == 0
        assert read_complainant(bundle["complainant"]["id"])["open_case_count"] == 0

        default_rows, default_meta = validate_paginated(
            api_client.search_precedents(CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert all(row["decision_id"] != decision_id for row in default_rows)
        assert default_meta["total_count"] == 0
        included_rows, included_meta = validate_paginated(
            api_client.search_precedents(
                CASE_MANAGER, params={"include_superseded": True, "limit": 10, "offset": 0}
            )
        )
        assert included_meta["total_count"] == 1
        assert included_rows[0]["decision_id"] == decision_id
