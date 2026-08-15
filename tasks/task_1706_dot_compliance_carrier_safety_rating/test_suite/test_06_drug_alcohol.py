"""Drug and alcohol program: collection intake, lab reporting, MRO
verification, segregation of duties, and post-accident windows."""
from test_helpers import (
    ApiErrorId,
    assert_drug_test,
    create_document_payload,
    create_period_payload,
    create_test_payload,
    get_test,
    make_carrier,
    make_carrier_with_driver,
    make_category,
    make_driver,
    make_drug_test,
    make_inspection,
    make_mro_headers,
    make_violation,
    report_lab,
    setup_post_accident_case,
    validate_error,
    validate_success,
)


class TestCreateTimeStates:
    def test_initial_states_on_create(self, api, manager_headers):
        """PRD §3.3: "Each new violation starts in `ACTIVE` status."
        PRD §3.6: "A new record starts in `COLLECTED` with `lab_result`
        `PENDING` and `mro_verdict` `NONE`".
        PRD §3.10: "A new document is `RETAINED`."
        PRD §3.6: "A `SafetyManager` opens an annual **random testing period**
        with `carrier_id`, the `program_year`, and the `avg_driver_count` of the
        random pool" — and only "a period in `OPEN` may be closed", so a fresh
        period is `OPEN`.

        Design: Corner/state_machines/initial_states_on_create
        """
        carrier = make_carrier(dot_number="DOT-2112")
        category = make_category(category_code="UNSAFE_DRIVING", display_name="UD")
        driver = make_driver(carrier["id"], cdl_number="CDL-2112")
        inspection = make_inspection(
            carrier["id"], driver["id"], report_number="R-2112",
            inspection_level=3, state_code="KS",
        )

        violation = make_violation(
            inspection["id"], category["id"], violation_code="392.2", severity_weight=2
        )
        assert violation["status"] == "ACTIVE"

        test = make_drug_test(
            driver["id"], test_type="PRE_EMPLOYMENT", substance="DRUG"
        )
        assert_drug_test(test)
        assert test["status"] == "COLLECTED"
        assert test["lab_result"] == "PENDING"
        assert test["mro_verdict"] == "NONE"

        document = validate_success(
            api.create_document(
                create_document_payload(
                    carrier["id"], document_type="TRAINING_CERTIFICATE",
                    filed_at="2026-01-01T00:00:00Z",
                ),
                manager_headers,
            ),
            201,
        )
        assert document["status"] == "RETAINED"

        period = validate_success(
            api.create_period(
                create_period_payload(carrier["id"], program_year=2026, avg_driver_count=4),
                manager_headers,
            ),
            201,
        )
        assert period["status"] == "OPEN"


class TestLabReportingAndVerification:
    def test_report_result_twice_rejected(self, api, manager_headers):
        """PRD §3.6: "The laboratory report, recorded by a `SafetyManager`
        through a `lab_result` payload, moves a `COLLECTED` test to
        `LAB_REPORTED` when the payload is `NEGATIVE`, `POSITIVE`, or `REFUSAL`,
        or to terminal `CANCELLED` when the payload is `CANCELLED_BY_LAB`; a
        test in any other state is rejected with `ERR_TEST_NOT_COLLECTED`."

        Design: Corner/state_machines/test_report_result_twice_rejected
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2107"}
        )
        test = make_drug_test(
            driver["id"], test_type="RANDOM", substance="ALCOHOL"
        )

        first = validate_success(
            api.report_lab_result(test["id"], {"lab_result": "NEGATIVE"}, manager_headers),
            200,
        )
        assert first["status"] == "LAB_REPORTED"
        assert first["lab_result"] == "NEGATIVE"

        second = api.report_lab_result(
            test["id"], {"lab_result": "POSITIVE"}, manager_headers
        )
        validate_error(second, ApiErrorId.ERR_TEST_NOT_COLLECTED)
        assert get_test(test["id"])["lab_result"] == "NEGATIVE"

    def test_verify_before_lab_result_rejected(self, api, mro_headers):
        """PRD §3.6: "Verification belongs exclusively to the
        `MedicalReviewOfficer`, who submits a `verdict` on a `LAB_REPORTED` test
        (`ERR_TEST_NOT_LAB_REPORTED` from any other state)."

        Design: Corner/validations/verify_before_lab_result_rejected
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2326"}
        )
        test = make_drug_test(driver["id"], test_type="RANDOM", substance="DRUG")
        assert test["status"] == "COLLECTED"

        resp = api.verify_test(test["id"], {"verdict": "VERIFIED_NEGATIVE"}, mro_headers)
        validate_error(resp, ApiErrorId.ERR_TEST_NOT_LAB_REPORTED)

    def test_sod_mro_verifier_is_recorder(self, api):
        """PRD §2.10: "The `MedicalReviewOfficer` who verifies a drug or alcohol
        test must not be the operator who recorded the collection: when the
        verifier's `X-User-ID` equals the test's `recorded_by_user_id`,
        verification is rejected with `ERR_SOD_VERIFIER_IS_RECORDER` (HTTP
        409)."

        Design: Corner/validations/sod_mro_verifier_is_recorder
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2307"}
        )
        test = make_drug_test(driver["id"], test_type="RANDOM", substance="DRUG")
        report_lab(test["id"], "NEGATIVE")

        # Role is correct (MedicalReviewOfficer) but the user id equals the
        # recorder's — the SoD rule compares X-User-ID values.
        resp = api.verify_test(
            test["id"], {"verdict": "VERIFIED_NEGATIVE"}, make_mro_headers("sm-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VERIFIER_IS_RECORDER)

        after = get_test(test["id"])
        assert after["status"] == "LAB_REPORTED"
        assert after["mro_verdict"] == "NONE"

    def test_verdict_result_mismatch_rejected(self, api):
        """PRD §3.6: "The verdict must be consistent with the laboratory result
        — `NEGATIVE` maps to `VERIFIED_NEGATIVE`, `POSITIVE` to
        `VERIFIED_POSITIVE`, and `REFUSAL` to `VERIFIED_REFUSAL` — and any other
        pairing is rejected with `ERR_VERDICT_RESULT_MISMATCH`."

        Design: Corner/validations/verdict_result_mismatch_rejected
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2309"}
        )
        test = make_drug_test(driver["id"], test_type="RANDOM", substance="DRUG")
        report_lab(test["id"], "NEGATIVE")

        resp = api.verify_test(
            test["id"], {"verdict": "VERIFIED_POSITIVE"}, make_mro_headers("mro-1")
        )
        validate_error(resp, ApiErrorId.ERR_VERDICT_RESULT_MISMATCH)
        assert get_test(test["id"])["status"] == "LAB_REPORTED"


class TestPostAccidentTesting:
    def test_post_accident_requires_accident_link(self, api, manager_headers):
        """PRD §3.6: "A `POST_ACCIDENT` test must carry the `accident_id` of the
        crash that prompted it, and an `accident_id` supplied on any other test
        type is likewise invalid — both directions surface as
        `ERR_MISSING_ACCIDENT_LINK`."

        Design: Corner/validations/post_accident_requires_accident_link
        """
        carrier, driver, accident = setup_post_accident_case()

        missing = api.create_test(
            create_test_payload(
                driver["id"], test_type="POST_ACCIDENT", substance="DRUG",
                collected_at="2026-07-02T00:00:00Z",
            ),
            manager_headers,
        )
        validate_error(missing, ApiErrorId.ERR_MISSING_ACCIDENT_LINK)

        stray = api.create_test(
            create_test_payload(
                driver["id"], test_type="RANDOM", substance="DRUG",
                collected_at="2026-07-02T00:00:00Z", accident_id=accident["id"],
            ),
            manager_headers,
        )
        validate_error(stray, ApiErrorId.ERR_MISSING_ACCIDENT_LINK)

    def test_post_accident_window_alcohol_boundary(self, api, manager_headers):
        """PRD §3.6: "A post-accident collection must fall within the federal
        testing window measured from the accident's `occurred_at`: no more than
        8 hours after the accident for an `ALCOHOL` test and no more than 32
        hours for a `DRUG` test, with a later collection rejected as
        `ERR_POST_ACCIDENT_WINDOW_MISSED`".

        Design: Corner/validations/post_accident_window_alcohol_boundary
        """
        carrier, driver, accident = setup_post_accident_case()

        # Exactly 8 hours after the accident: "no more than 8 hours" includes
        # the boundary instant.
        on_boundary = api.create_test(
            create_test_payload(
                driver["id"], test_type="POST_ACCIDENT", substance="ALCOHOL",
                collected_at="2026-07-01T08:00:00Z", accident_id=accident["id"],
            ),
            manager_headers,
        )
        assert validate_success(on_boundary, 201)["status"] == "COLLECTED"

        past_boundary = api.create_test(
            create_test_payload(
                driver["id"], test_type="POST_ACCIDENT", substance="ALCOHOL",
                collected_at="2026-07-01T08:00:01Z", accident_id=accident["id"],
            ),
            manager_headers,
        )
        validate_error(past_boundary, ApiErrorId.ERR_POST_ACCIDENT_WINDOW_MISSED)

    def test_conflict_state_beats_temporal_post_accident(self, api, manager_headers):
        """PRD §2.6: "Every request is validated against the following stages,
        evaluated in the order given; a request that fails several checks
        receives the error from the earliest failing stage." — state eligibility
        (stage 5) precedes temporal gates (stage 8), so the state error wins.
        PRD §3.6: "Most test types require the driver to be `ACTIVE`
        (`ERR_DRIVER_NOT_ACTIVE`)".

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_beats_temporal_post_accident
        """
        carrier, driver, accident = setup_post_accident_case()
        validate_success(api.terminate_driver(driver["id"], manager_headers), 200)

        # 60 hours after the accident also blows the 32-hour DRUG window, but
        # the state violation is the earlier stage and must be reported.
        resp = api.create_test(
            create_test_payload(
                driver["id"], test_type="POST_ACCIDENT", substance="DRUG",
                collected_at="2026-07-03T12:00:00Z", accident_id=accident["id"],
            ),
            manager_headers,
        )
        error = validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ACTIVE)
        assert error["error_id"] != ApiErrorId.ERR_POST_ACCIDENT_WINDOW_MISSED

    def test_post_accident_window_drug_32h_isolated(self, api, manager_headers):
        """PRD §3.6: "no more than 8 hours after the accident for an `ALCOHOL`
        test and no more than 32 hours for a `DRUG` test, with a later
        collection rejected as `ERR_POST_ACCIDENT_WINDOW_MISSED`" — exercised in
        isolation on an ACTIVE driver (no competing state violation).

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_beats_temporal_post_accident
        """
        carrier, driver, accident = setup_post_accident_case()

        in_window = api.create_test(
            create_test_payload(
                driver["id"], test_type="POST_ACCIDENT", substance="DRUG",
                collected_at="2026-07-02T08:00:00Z", accident_id=accident["id"],
            ),
            manager_headers,
        )
        validate_success(in_window, 201)

        past_window = api.create_test(
            create_test_payload(
                driver["id"], test_type="POST_ACCIDENT", substance="DRUG",
                collected_at="2026-07-03T12:00:00Z", accident_id=accident["id"],
            ),
            manager_headers,
        )
        validate_error(past_window, ApiErrorId.ERR_POST_ACCIDENT_WINDOW_MISSED)
