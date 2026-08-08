"""Application creation gates, the screening loop, and match gating."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_applicant_headers,
    setup_scenario, new_applicant, new_application, screen_application,
)


def test_application_term_too_short(api):
    """PRD §3.3: "the proposed term must be at least the listing's `min_term_months`
    (else `ERR_TERM_TOO_SHORT`, 409)."

    Design: Corner/validations/application_term_too_short
    """
    ctx = setup_scenario(api, stage="listing_open", listing_overrides={"min_term_months": 3})
    resp = api.create_application(
        {"listing_id": ctx["listing"]["id"], "applicant_id": ctx["applicant"]["id"],
         "proposed_move_in_date": "2026-06-01", "proposed_move_out_date": "2026-06-20"},
        make_applicant_headers(ctx["applicant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TERM_TOO_SHORT.value)


def test_match_fails_when_screening_result_fail(api):
    """PRD §3.3: "its `screening_result` must be `PASS` (else `ERR_SCREENING_NOT_PASSED`)".

    Design: Corner/validations/match_fail_screening_rejected
    """
    ctx = setup_scenario(api, stage="listing_open",
                         listing_overrides={"screening_policy": "STRICT"},
                         applicant_overrides={"annual_income_cents": 5000000, "credit_score": 640})
    application = new_application(api, ctx["listing"], ctx["applicant"],
                                 proposed_move_in_date="2026-06-01", proposed_move_out_date="2026-08-31")
    report = screen_application(api, application, credit_score=640)
    assert report["qualification_result"] == "FAIL", "STRICT screen of income 5000000 must FAIL"
    resp = api.match_application(application["id"], TEST_USERS["compliance_headers"])
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_PASSED.value)


class TestScreeningRevisionCycle:
    """Difficulty: non_linear_state_machine — the SCREENING <-> INFO_REQUESTED cycle
    is revisitable, unlike a linear pipeline."""

    def _setup_info_requested(self, api):
        ctx = setup_scenario(api, stage="listing_open")
        application = new_application(api, ctx["listing"], ctx["applicant"])
        validate_success(api.start_screening(application["id"], TEST_USERS["compliance_headers"]))
        validate_success(api.request_info(application["id"], TEST_USERS["compliance_headers"]))
        return ctx, application

    def test_resubmit_info_returns_to_screening(self, api):
        """PRD §3.3: "the `Applicant` then resubmits, returning the application from
        `INFO_REQUESTED` to `SCREENING` (else `ERR_APPLICATION_NOT_INFO_REQUESTED`)".

        Design: Difficulty/non_linear_state_machine/application_screening_revision_cycle
        """
        ctx, application = self._setup_info_requested(api)
        resp = api.resubmit_info(application["id"], make_applicant_headers(ctx["applicant"]["id"]))
        data = validate_success(resp)
        assert data["status"] == "SCREENING", f"resubmit-info must return to SCREENING, got {data['status']}"

    def test_second_request_info_reenters_info_requested(self, api):
        """PRD §3.3: "This `SCREENING` ⇄ `INFO_REQUESTED` cycle may repeat any number
        of rounds."

        Design: Difficulty/non_linear_state_machine/application_screening_revision_cycle
        """
        ctx, application = self._setup_info_requested(api)
        validate_success(api.resubmit_info(application["id"], make_applicant_headers(ctx["applicant"]["id"])))
        resp = api.request_info(application["id"], TEST_USERS["compliance_headers"])
        data = validate_success(resp)
        assert data["status"] == "INFO_REQUESTED", (
            f"second request-info must re-enter INFO_REQUESTED, got {data['status']}")


class TestAvailabilityWindowBoundary:
    """Difficulty: boundary_precision_check — the availability window is inclusive of
    available_to (closed on the move-out boundary)."""

    def test_move_out_equal_available_to_accepted(self, api):
        """PRD §3.3: "the proposed occupancy must fall entirely within the listing's
        inclusive `available_from`-to-`available_to` window (else
        `ERR_OUTSIDE_AVAILABILITY_WINDOW`, 422)".

        Design: Difficulty/boundary_precision_check/availability_window_inclusive_move_out_boundary
        """
        ctx = setup_scenario(api, stage="listing_open",
                            listing_overrides={"available_from": "2026-06-01",
                                               "available_to": "2026-08-31", "min_term_months": 1})
        resp = api.create_application(
            {"listing_id": ctx["listing"]["id"], "applicant_id": ctx["applicant"]["id"],
             "proposed_move_in_date": "2026-06-01", "proposed_move_out_date": "2026-08-31"},
            make_applicant_headers(ctx["applicant"]["id"]))
        data = validate_success(resp, 201)
        assert data["status"] == "SUBMITTED", "move-out on the inclusive boundary must be accepted"

    def test_move_out_past_available_to_rejected(self, api):
        """PRD §3.3: "the proposed occupancy must fall entirely within the listing's
        inclusive `available_from`-to-`available_to` window (else
        `ERR_OUTSIDE_AVAILABILITY_WINDOW`, 422)".

        Design: Difficulty/boundary_precision_check/availability_window_inclusive_move_out_boundary
        """
        ctx = setup_scenario(api, stage="listing_open",
                            listing_overrides={"available_from": "2026-06-01",
                                               "available_to": "2026-08-31", "min_term_months": 1})
        applicant2 = new_applicant(api, name="AP2", email="ap2@x.com")
        resp = api.create_application(
            {"listing_id": ctx["listing"]["id"], "applicant_id": applicant2["id"],
             "proposed_move_in_date": "2026-06-01", "proposed_move_out_date": "2026-09-01"},
            make_applicant_headers(applicant2["id"]))
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_AVAILABILITY_WINDOW.value)


class TestDuplicateApplicationPrecedesWindow:
    """Difficulty: priority_pair_validation_conflict — a duplicate application (referential,
    §2.9 step 6) is reported ahead of an out-of-window date (temporal, §2.9 step 9)."""

    def test_duplicate_with_out_of_window_dates_reports_duplicate(self, api):
        """PRD §2.9: "6. **Cross-entity referential preconditions** — such as a lease
        being VERIFIED, a settlement being FUNDED, or the absence of a duplicate
        application (409)."
        PRD §3.3: "the applicant must not already hold a non-terminal application on the
        same listing (else `ERR_DUPLICATE_APPLICATION`)".

        Design: Difficulty/priority_pair_validation_conflict/apply_referential_precedes_temporal
        """
        ctx = setup_scenario(api, stage="listing_open",
                            listing_overrides={"available_from": "2026-06-01",
                                               "available_to": "2026-08-31", "min_term_months": 1})
        # First (valid, in-window) application.
        new_application(api, ctx["listing"], ctx["applicant"],
                        proposed_move_in_date="2026-06-10", proposed_move_out_date="2026-08-15")
        # Second application by the same applicant AND out-of-window dates: both checks would fail.
        resp = api.create_application(
            {"listing_id": ctx["listing"]["id"], "applicant_id": ctx["applicant"]["id"],
             "proposed_move_in_date": "2026-06-10", "proposed_move_out_date": "2026-12-31"},
            make_applicant_headers(ctx["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION.value)

    def test_duplicate_in_window_still_rejected(self, api):
        """PRD §3.3: "the applicant must not already hold a non-terminal application on
        the same listing (else `ERR_DUPLICATE_APPLICATION`)".

        Design: Difficulty/priority_pair_validation_conflict/apply_referential_precedes_temporal
        """
        ctx = setup_scenario(api, stage="listing_open",
                            listing_overrides={"available_from": "2026-06-01",
                                               "available_to": "2026-08-31", "min_term_months": 1})
        new_application(api, ctx["listing"], ctx["applicant"],
                        proposed_move_in_date="2026-06-10", proposed_move_out_date="2026-08-15")
        resp = api.create_application(
            {"listing_id": ctx["listing"]["id"], "applicant_id": ctx["applicant"]["id"],
             "proposed_move_in_date": "2026-06-10", "proposed_move_out_date": "2026-08-15"},
            make_applicant_headers(ctx["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION.value)
