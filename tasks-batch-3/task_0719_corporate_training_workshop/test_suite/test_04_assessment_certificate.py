"""Assessment grading (percent/outcome) and certificate issuance/revocation."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_assessment, assert_certificate,
    setup_running_cohort_one_attendee, setup_open_cohort,
    register_and_confirm, lock_cohort, set_clock, make_facilitator_headers,
    TEST_USERS,
)

DESIGNER = TEST_USERS["program_designer_headers"]
COORD = TEST_USERS["scheduling_coordinator_headers"]


class TestAssessment:
    def test_pass_threshold_inclusive_boundary(self, api):
        """PRD §3.8: "The `outcome` is `PASS` when `percent_score` is at least the cohort's
        program version `pass_threshold_pct` — the comparison is boundary-inclusive, so a
        percentage exactly equal to the threshold passes — and `FAIL` otherwise."

        Design: Difficulty/boundary_precision_check/assessment_pass_threshold_inclusive_boundary
        """
        ctx = setup_running_cohort_one_attendee(pass_threshold_pct=70)
        data = validate_success(
            api.create_assessment(ctx["registration"]["id"], {"raw_score": 7, "max_score": 10},
                                  ctx["fac_headers"]),
            expected_status=201,
        )
        assert_assessment(data)
        assert data["percent_score"] == pytest.approx(70.00, abs=0.001)
        assert data["outcome"] == "PASS"

    def test_just_below_threshold_fails(self, api):
        """PRD §3.8: "The `outcome` is `PASS` when `percent_score` is at least the cohort's
        program version `pass_threshold_pct` — the comparison is boundary-inclusive, so a
        percentage exactly equal to the threshold passes — and `FAIL` otherwise."

        Design: Difficulty/boundary_precision_check/assessment_pass_threshold_inclusive_boundary
        """
        ctx = setup_running_cohort_one_attendee(pass_threshold_pct=70)
        data = validate_success(
            api.create_assessment(ctx["registration"]["id"], {"raw_score": 69, "max_score": 100},
                                  ctx["fac_headers"]),
            expected_status=201,
        )
        assert data["percent_score"] == pytest.approx(69.00, abs=0.001)
        assert data["outcome"] == "FAIL"

    def test_rounding_half_up_two_decimals(self, api):
        """PRD §3.8: "The system computes `percent_score` as 100 multiplied by `raw_score`,
        divided by `max_score`, rounded half up to two decimal places."

        Design: Corner/calculations/assessment_rounding_half_up_two_decimals
        """
        ctx = setup_running_cohort_one_attendee(pass_threshold_pct=70)
        data = validate_success(
            api.create_assessment(ctx["registration"]["id"], {"raw_score": 2, "max_score": 3},
                                  ctx["fac_headers"]),
            expected_status=201,
        )
        assert data["percent_score"] == pytest.approx(66.67, abs=0.001)
        assert data["outcome"] == "FAIL"

    def test_computed_fields_ignore_client_input(self, api):
        """PRD §3.8: "The grade supplies a `raw_score` (the points scored, at least 0) and a
        `max_score` (the maximum possible points, at least 1). The system computes `percent_score`
        as 100 multiplied by `raw_score`, divided by `max_score`, rounded half up to two decimal
        places."

        Design: Corner/entities/assessment_computed_fields_ignore_client_input
        """
        ctx = setup_running_cohort_one_attendee(pass_threshold_pct=70)
        data = validate_success(
            api.create_assessment(ctx["registration"]["id"], {"raw_score": 90, "max_score": 100},
                                  ctx["fac_headers"]),
            expected_status=201,
        )
        assert data["percent_score"] == pytest.approx(90.00, abs=0.001)
        assert data["outcome"] == "PASS"


class TestCertificate:
    def _attended_pass_cert(self, api, ceu_credits=8, pass_threshold_pct=50):
        ctx = setup_running_cohort_one_attendee(ceu_credits=ceu_credits,
                                                pass_threshold_pct=pass_threshold_pct)
        asm = validate_success(
            api.create_assessment(ctx["registration"]["id"], {"raw_score": 9, "max_score": 10},
                                  ctx["fac_headers"]),
            expected_status=201,
        )
        cert = validate_success(
            api.issue_certificate(ctx["registration"]["id"], {"assessment_id": asm["id"]}, DESIGNER),
            expected_status=201,
        )
        return ctx, asm, cert

    def test_revoke_still_valid_rejected(self, api):
        """PRD §3.8: "Manual revocation is permitted only when the certificate is no longer backed
        by a clean record — that is, when the linked registration is not `ATTENDED` or the linked
        assessment has been `VOIDED`. If the registration is still `ATTENDED` and the assessment
        has not been voided, the certificate is still valid and revocation is rejected with
        `ERR_CERTIFICATE_STILL_VALID`."

        Design: Corner/endpoints/revoke_certificate_still_valid_rejected
        """
        _, _, cert = self._attended_pass_cert(api)
        resp = api.revoke_certificate(cert["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_STILL_VALID.value)

    def test_void_assessment_then_revoke_succeeds(self, api):
        """PRD §3.8: "Manual revocation is permitted only when the certificate is no longer backed
        by a clean record — that is, when the linked registration is not `ATTENDED` or the linked
        assessment has been `VOIDED`." PRD §3.8: "Revoking a certificate is performed by a
        `ProgramDesigner` and moves it from `ISSUED` to `REVOKED`".

        Design: Corner/endpoints/void_assessment_then_revoke_certificate_succeeds
        """
        _, asm, cert = self._attended_pass_cert(api)
        validate_success(api.void_assessment(asm["id"], DESIGNER))
        data = validate_success(api.revoke_certificate(cert["id"], DESIGNER))
        assert data["status"] == "REVOKED"

    def test_certificate_not_eligible_no_show(self, api):
        """PRD §3.8: "Issuance is permitted only when the registration is `ATTENDED` and the
        referenced assessment's outcome is `PASS`; otherwise it is rejected with
        `ERR_NOT_ELIGIBLE_FOR_CERTIFICATE`."

        Design: Corner/validations/certificate_not_eligible_no_show
        """
        # RUNNING cohort, graded PASS, but learner never marked attended -> NO_SHOW on deliver.
        ctx = setup_open_cohort(
            delivery_mode="ONSITE", category="TECHNICAL",
            cohort_overrides={"starts_at": "2026-07-21T09:00:00Z", "ends_at": "2026-07-21T13:00:00Z",
                              "enroll_deadline": "2026-07-20T00:00:00Z"},
            version_overrides={"per_seat_cents": 10000, "min_seats": 1, "pass_threshold_pct": 50},
        )
        coh_id = ctx["cohort"]["id"]
        reg = register_and_confirm(coh_id, "ne@example.com")
        lock_cohort(coh_id)
        set_clock("2026-07-21T09:00:00Z")
        api.start_cohort(coh_id, COORD)
        fac_headers = make_facilitator_headers(ctx["facilitator"]["id"])
        asm = validate_success(
            api.create_assessment(reg["id"], {"raw_score": 9, "max_score": 10}, fac_headers),
            expected_status=201,
        )
        set_clock("2026-07-21T13:00:00Z")
        api.deliver_cohort(coh_id, COORD)  # reg never marked -> NO_SHOW
        assert validate_success(api.get_registration(reg["id"], COORD))["status"] == "NO_SHOW"
        resp = api.issue_certificate(reg["id"], {"assessment_id": asm["id"]}, DESIGNER)
        validate_error(resp, ApiErrorId.ERR_NOT_ELIGIBLE_FOR_CERTIFICATE.value)
