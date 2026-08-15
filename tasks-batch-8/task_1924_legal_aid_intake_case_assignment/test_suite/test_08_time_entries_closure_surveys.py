"""Timekeeping ownership, closure ownership, satisfaction survey lifecycle,
and the survey response shape (auxiliary resource: no version/updated_at)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_venue_rule,
    create_intake_specialist,
    create_supervisor,
    create_attorney,
    create_client,
    create_openable_application,
    open_case_from_application,
    make_supervising_attorney_headers,
    make_staff_attorney_headers,
    make_intake_specialist_headers,
)


class TestTimeEntryOwnership:
    def test_time_entry_ownership_bundle(self, api):
        """PRD §3.8: "Logging is permitted to `StaffAttorney`, `Paralegal`,
        and `SupervisingAttorney` roles, but ownership binds tighter than
        role: the actor must be the case's assigned attorney or its assigned
        paralegal, and anyone else is rejected with `ERR_TIME_ENTRY_FORBIDDEN`
        (HTTP 403) before anything else about the entry is considered."
        PRD §3.8: "the entry's `staff_id` is set from the actor's `X-User-ID`
        and its `case_id` from the case it was logged against."

        Design: Corner/validations/time_entry_ownership_bundle
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        att_a = create_attorney(full_name="Att A", practice_areas=["CONSUMER_DEBT"])
        att_b = create_attorney(full_name="Att B", practice_areas=["CONSUMER_DEBT"])
        client = create_client(intake["id"], full_name="Cli TE")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"])
        validate_success(api.assign_case(
            case["id"], {"attorney_id": att_a["id"],
                         "expected_case_version": case["version"]},
            make_supervising_attorney_headers(sup["id"])))

        bad = api.create_time_entry(
            case["id"], {"hours": 1.50, "activity_code": "RESEARCH",
                         "work_date": "2026-08-05"},
            make_staff_attorney_headers(att_b["id"]))
        validate_error(bad, ApiErrorId.ERR_TIME_ENTRY_FORBIDDEN)

        good = api.create_time_entry(
            case["id"], {"hours": 1.50, "activity_code": "RESEARCH",
                         "work_date": "2026-08-05"},
            make_staff_attorney_headers(att_a["id"]))
        entry = validate_success(good, expected_status=201)
        assert entry["staff_id"] == att_a["id"]

        entries, meta = validate_paginated(api.list_time_entries(
            make_supervising_attorney_headers(sup["id"]), params={"case_id": case["id"]}))
        assert meta["total_count"] == 1


class TestCloseOwnership:
    def test_close_ownership_bundle(self, api):
        """PRD §3.8: "A `StaffAttorney` may close only their own case — the
        case's `assigned_attorney_id` must equal their `X-User-ID`, else
        `ERR_CASE_NOT_ASSIGNED_TO_YOU` (HTTP 403) — while a
        `SupervisingAttorney` may close any case."

        Design: Corner/validations/close_ownership_bundle
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        att_a = create_attorney(full_name="Att A", practice_areas=["CONSUMER_DEBT"])
        att_b = create_attorney(full_name="Att B", practice_areas=["CONSUMER_DEBT"])
        client = create_client(intake["id"], full_name="Cli CO")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"])
        validate_success(api.assign_case(
            case["id"], {"attorney_id": att_a["id"],
                         "expected_case_version": case["version"]},
            make_supervising_attorney_headers(sup["id"])))

        bad = api.close_case(case["id"], {"outcome_code": "ADVICE_GIVEN"},
                             make_staff_attorney_headers(att_b["id"]))
        validate_error(bad, ApiErrorId.ERR_CASE_NOT_ASSIGNED_TO_YOU)
        still = validate_success(api.get_case(
            case["id"], make_supervising_attorney_headers(sup["id"])))
        assert still["status"] == "OPEN"

        good = api.close_case(case["id"], {"outcome_code": "ADVICE_GIVEN",
                                           "closure_reason": "done"},
                              make_staff_attorney_headers(att_a["id"]))
        assert validate_success(good)["status"] == "CLOSED"


class TestSurveyLifecycle:
    def test_survey_lifecycle_bundle(self, api):
        """PRD §3.8: "An `IntakeSpecialist` may record a `SatisfactionSurvey`
        only against a `CLOSED` case, else `ERR_CASE_NOT_CLOSED` (HTTP 409),
        and at most one survey may exist per case — a second attempt is
        rejected with `ERR_DUPLICATE_SURVEY` (HTTP 409). The survey carries a
        `score` as an integer from 1 to 5 inclusive, a `would_recommend`
        boolean, and optional `comments` defaulting to empty; surveys are
        immutable once recorded, and a case's survey list therefore returns
        zero or one record."
        PRD §2.7: "Request shape: missing required fields, unknown fields,
        bad enum values, or range violations — a satisfaction `score` outside
        1–5, `hours` outside 0.25–24.00, an end date not after its start date,
        a `household_size` below 1, negative cent amounts — produce
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/survey_lifecycle_bundle
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        headers_in = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli S")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"])

        r1 = api.create_survey(case["id"], {"score": 5, "would_recommend": True}, headers_in)
        validate_error(r1, ApiErrorId.ERR_CASE_NOT_CLOSED)
        validate_success(api.close_case(case["id"], {"outcome_code": "ADVICE_GIVEN"},
                                        make_supervising_attorney_headers(sup["id"])))
        r2 = api.create_survey(case["id"], {"score": 6, "would_recommend": True}, headers_in)
        validate_error(r2, ApiErrorId.ERR_INVALID_REQUEST)
        ok = api.create_survey(case["id"], {"score": 5, "would_recommend": True}, headers_in)
        validate_success(ok, expected_status=201)
        r3 = api.create_survey(case["id"], {"score": 4, "would_recommend": False}, headers_in)
        validate_error(r3, ApiErrorId.ERR_DUPLICATE_SURVEY)

    def test_survey_response_has_no_version_field(self, api):
        """PRD §2.5: "Five auxiliary resources — `VenueRule`, `TimeEntry`,
        `SatisfactionSurvey`, `UnmetNeedRecord`, and `WaitlistEntry` — carry
        only `id` and `created_at`; both `updated_at` and `version` are
        absent from them."
        PRD §3.8: "surveys are immutable once recorded, and a case's survey
        list therefore returns zero or one record."

        Design: Corner/entities/survey_response_has_no_version_field
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        headers_in = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli Surv")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"])
        validate_success(api.close_case(
            case["id"], {"outcome_code": "ADVICE_GIVEN",
                         "closure_reason": "advice complete"},
            make_supervising_attorney_headers(sup["id"])))
        resp = api.create_survey(case["id"], {"score": 5, "would_recommend": True,
                                              "comments": "great"}, headers_in)
        data = validate_success(resp, expected_status=201)
        assert "id" in data and "created_at" in data
        assert "version" not in data, "auxiliary resource must not expose version"
        assert "updated_at" not in data, "auxiliary resource must not expose updated_at"
