"""IntakeApplication workflows: initial state, documentation loop, decision
gating, rescreen OCC, withdrawal side effects, venue errors, and the
client-patch waitlist cascade."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_venue_rule,
    create_intake_specialist,
    create_client,
    create_application,
    create_eligible_application,
    screen_application,
    decide_application,
    make_intake_specialist_headers,
)


class TestInitialState:
    def test_application_created_in_initial_state_submitted(self, api):
        """PRD §3.2: "A new application starts in `SUBMITTED` with `version` 1,
        and the application register supports filtering by `client_id`,
        `status`, `case_type`, and `incident_county`."

        Design: Corner/state_machines/application_created_in_initial_state_submitted
        """
        intake = create_intake_specialist()
        client = create_client(intake["id"], full_name="Cli Init")
        resp = api.create_application(
            {"client_id": client["id"], "case_type": "EVICTION_DEFENSE",
             "opposing_party_name": "Landlord", "incident_county": "CountyA"},
            make_intake_specialist_headers(intake["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SUBMITTED"
        assert data["version"] == 1
        # computed screening fields not yet populated
        assert data.get("priority_score") is None
        assert data.get("gross_poverty_percentage") is None
        assert data.get("eligibility_determination") is None
        assert data.get("venue") is None


class TestDocumentationLoop:
    def test_intake_application_documentation_loop_cycle(self, api):
        """PRD §3.2: "From `SUBMITTED`, the application can be moved to
        `DOCS_REQUESTED` — the request may carry an optional `request_note` —
        and submitting documents returns it to `SUBMITTED` for a fresh screen;
        the loop may repeat as needed. A `SUBMITTED` application is the only
        one that can be screened."

        Design: Difficulty/non_linear_state_machine/intake_application_documentation_loop_cycle
        """
        create_venue_rule()
        intake = create_intake_specialist()
        headers = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli Loop")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord LLC")

        s1 = validate_success(api.request_documents(app["id"], {"request_note": "pay stubs"}, headers))
        assert s1["status"] == "DOCS_REQUESTED"
        s2 = validate_success(api.submit_documents(app["id"], headers))
        assert s2["status"] == "SUBMITTED"
        s3 = validate_success(api.screen_application(app["id"], headers))
        assert s3["status"] == "SCREENED"
        # loop returns to a workable state: 1,000,000 / 1,506,000 * 100 = 66.40
        assert s3["gross_poverty_percentage"] == pytest.approx(66.40, abs=0.001)

    def test_documentation_loop_may_repeat(self, api):
        """PRD §3.2: "From `SUBMITTED`, the application can be moved to
        `DOCS_REQUESTED` — the request may carry an optional `request_note` —
        and submitting documents returns it to `SUBMITTED` for a fresh screen;
        the loop may repeat as needed."

        Design: Difficulty/non_linear_state_machine/intake_application_documentation_loop_cycle
        """
        create_venue_rule()
        intake = create_intake_specialist()
        headers = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli Loop2")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord LLC")
        for _ in range(2):
            s1 = validate_success(api.request_documents(app["id"], {}, headers))
            assert s1["status"] == "DOCS_REQUESTED"
            s2 = validate_success(api.submit_documents(app["id"], headers))
            assert s2["status"] == "SUBMITTED"
        s3 = validate_success(api.screen_application(app["id"], headers))
        assert s3["status"] == "SCREENED"


class TestDecideEligibility:
    def test_decide_before_screen_rejected(self, api):
        """PRD §3.2: "`OPENED` and `WITHDRAWN` are terminal, and any attempted
        transition from a state that is not a from-state of the requested
        action is rejected with `ERR_INVALID_APPLICATION_STATE` (HTTP 409)."

        Design: Corner/state_machines/decide_before_screen_rejected
        """
        intake = create_intake_specialist()
        client = create_client(intake["id"], full_name="Cli Early")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord")
        headers = make_intake_specialist_headers(intake["id"])
        resp = api.decide_eligibility(app["id"], {"determination": "ELIGIBLE"}, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)
        after = validate_success(api.get_application(app["id"], headers))
        assert after["status"] == "SUBMITTED"

    def test_determination_mismatch_rejected(self, api):
        """PRD §3.2: "The submitted value must equal the computed
        `eligibility_determination`; a contradiction is rejected with
        `ERR_DETERMINATION_MISMATCH` (HTTP 409)."

        Design: Corner/validations/determination_mismatch_rejected
        """
        create_venue_rule()
        intake = create_intake_specialist()
        client = create_client(intake["id"], full_name="Cli MM")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord")
        headers = make_intake_specialist_headers(intake["id"])
        screen_application(app["id"], intake["id"])  # computed ELIGIBLE (66.40 <= 125.00)
        resp = api.decide_eligibility(app["id"], {"determination": "INELIGIBLE"}, headers)
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_MISMATCH)
        after = validate_success(api.get_application(app["id"], headers))
        assert after["status"] == "SCREENED"


class TestRescreen:
    def test_rescreen_from_eligible_returns_submitted(self, api):
        """PRD §3.2: "A successful rescreen increments the application's
        `version` by one; on the `ELIGIBLE` branch the previously computed
        screen fields — `venue`, both percentages, `priority_score`, and
        `eligibility_determination` — are retained until a subsequent screen
        overwrites them, and the same version-incrementing reset applies on
        the `INELIGIBLE` branch."

        Design: Corner/state_machines/rescreen_from_eligible_returns_submitted
        """
        create_venue_rule()
        intake = create_intake_specialist()
        headers = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli Re")
        app = create_eligible_application(intake["id"], client["id"],
                                          case_type="EVICTION_DEFENSE")
        resp = api.rescreen_application(
            app["id"], {"expected_application_version": app["version"]}, headers
        )
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED"
        assert data["version"] == app["version"] + 1

    def test_occ_stale_version_on_rescreen(self, api):
        """PRD §2.8: "Rescreening an application requires the request to carry
        `expected_application_version`, the client's last observed `version`
        of that application, for the same reason: rescreening legitimately
        supersedes a prior screening outcome, and a stale
        `expected_application_version` is what condemns a request that has not
        observed the latest one. A mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_rescreen
        """
        create_venue_rule()
        intake = create_intake_specialist()
        headers = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli OCC2")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord")
        screened = screen_application(app["id"], intake["id"])
        app_v2 = screened["version"]
        decided = decide_application(app["id"], "ELIGIBLE", intake["id"])
        app_v3 = decided["version"]

        stale = api.rescreen_application(
            app["id"], {"expected_application_version": app_v2}, headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        still = validate_success(api.get_application(app["id"], headers))
        assert still["status"] == "ELIGIBLE"

        ok = api.rescreen_application(
            app["id"], {"expected_application_version": app_v3}, headers
        )
        assert validate_success(ok)["status"] == "SUBMITTED"


class TestWithdrawalUnmetNeed:
    def _make_ineligible_app(self, api):
        create_venue_rule()
        intake = create_intake_specialist()
        client = create_client(intake["id"], full_name="Cli Rich",
                               annual_gross_income_cents=2_000_000,
                               annual_countable_income_cents=1_900_000)
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Landlord")
        screen_application(app["id"], intake["id"])
        decide_application(app["id"], "INELIGIBLE", intake["id"])
        return intake, app

    def test_withdraw_from_ineligible_adds_no_extra_unmet_record(self, api):
        """PRD §3.2: "withdrawal from `INELIGIBLE` creates no record, because
        the unmet need was already recorded at the decision; withdrawal from
        `WAITLISTED` deletes the application's waitlist entry and creates the
        `CLIENT_WITHDRAWN` record."

        Design: Corner/state_machines/withdraw_from_ineligible_adds_no_extra_unmet_record
        """
        intake, app = self._make_ineligible_app(api)
        headers = make_intake_specialist_headers(intake["id"])
        resp = api.withdraw_application(app["id"], {"withdrawal_reason": "client left"}, headers)
        assert validate_success(resp)["status"] == "WITHDRAWN"
        recs, meta = validate_paginated(
            api.list_unmet_need_records(headers, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 1
        assert recs[0]["reason_code"] == "OVER_INCOME"

    def test_withdraw_from_eligible_creates_client_withdrawn_record(self, api):
        """PRD §3.2: "Withdrawal from `SUBMITTED`, `DOCS_REQUESTED`, `SCREENED`,
        or `ELIGIBLE` creates an `UnmetNeedRecord` with `reason_code`
        `CLIENT_WITHDRAWN`; withdrawal from `INELIGIBLE` creates no record,
        because the unmet need was already recorded at the decision; withdrawal
        from `WAITLISTED` deletes the application's waitlist entry and creates
        the `CLIENT_WITHDRAWN` record."

        Design: Corner/state_machines/withdraw_from_ineligible_adds_no_extra_unmet_record
        """
        create_venue_rule()
        intake = create_intake_specialist()
        headers = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli WD")
        app = create_eligible_application(intake["id"], client["id"],
                                          case_type="EVICTION_DEFENSE")
        resp = api.withdraw_application(app["id"], {}, headers)
        assert validate_success(resp)["status"] == "WITHDRAWN"
        recs, meta = validate_paginated(
            api.list_unmet_need_records(headers, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 1
        assert recs[0]["reason_code"] == "CLIENT_WITHDRAWN"


class TestVenueRuleGate:
    def test_screen_without_venue_rule_rejected(self, api):
        """PRD §3.2: "When an intake specialist screens a `SUBMITTED`
        application, the system first looks for a venue rule covering the pair
        of `incident_county` and `case_type`; if no such rule exists, the
        screen fails with `ERR_VENUE_UNDETERMINED` (HTTP 422)."

        Design: Corner/validations/screen_without_venue_rule_rejected
        """
        intake = create_intake_specialist(practice_areas=["EXPUNGEMENT"])
        client = create_client(intake["id"], full_name="Cli NoRule")
        app = create_application(intake["id"], client["id"], case_type="EXPUNGEMENT",
                                 opposing_party_name="State")
        headers = make_intake_specialist_headers(intake["id"])
        resp = api.screen_application(app["id"], headers)
        validate_error(resp, ApiErrorId.ERR_VENUE_UNDETERMINED)
        after = validate_success(api.get_application(app["id"], headers))
        assert after["status"] == "SUBMITTED"


class TestClientPatchCascade:
    def test_client_financial_patch_depth2_waitlist_cascade(self, api):
        """PRD §3.1: "Changing any financial field, however — `household_size`,
        `annual_gross_income_cents`, `annual_countable_income_cents`,
        `receives_means_tested_benefits`, or `residence_county` — invalidates
        every pending determination for that client: each of the client's
        applications sitting in `SCREENED`, `ELIGIBLE`, or `INELIGIBLE` returns
        to `SUBMITTED` for a fresh screen, and an application sitting in
        `WAITLISTED` returns to `SUBMITTED` with its waitlist entry deleted,
        since an entry may exist only for a waitlisted application."

        Design: Difficulty/transitive_cascade/client_financial_patch_depth2_waitlist_cascade
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        headers = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli WL")
        app = create_eligible_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector Inc")
        wl = api.enqueue_waitlist(app["id"], headers)
        assert validate_success(wl)["status"] == "WAITLISTED"

        api.update_client(client["id"], {"annual_gross_income_cents": 1_200_000}, headers)
        after = validate_success(api.get_application(app["id"], headers))
        assert after["status"] == "SUBMITTED"
        entries, meta = validate_paginated(
            api.list_waitlist_entries(headers, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 0

    def test_client_financial_patch_returns_screened_app_to_submitted(self, api):
        """PRD §3.1: "Changing any financial field, however — `household_size`,
        `annual_gross_income_cents`, `annual_countable_income_cents`,
        `receives_means_tested_benefits`, or `residence_county` — invalidates
        every pending determination for that client: each of the client's
        applications sitting in `SCREENED`, `ELIGIBLE`, or `INELIGIBLE` returns
        to `SUBMITTED` for a fresh screen, and an application sitting in
        `WAITLISTED` returns to `SUBMITTED` with its waitlist entry deleted,
        since an entry may exist only for a waitlisted application."

        Design: Difficulty/transitive_cascade/client_financial_patch_depth2_waitlist_cascade
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        headers = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli Re2")
        app = create_application(intake["id"], client["id"], case_type="CONSUMER_DEBT",
                                 opposing_party_name="Collector")
        screen_application(app["id"], intake["id"])
        api.update_client(client["id"], {"household_size": 3}, headers)
        after = validate_success(api.get_application(app["id"], headers))
        assert after["status"] == "SUBMITTED"
