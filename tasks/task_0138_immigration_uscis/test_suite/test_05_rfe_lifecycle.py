"""RFE lifecycle — PRD §3.5.

Coverage:
- Issuance requires no other OUTSTANDING RFE on the case
  (ERR_RFE_ALREADY_OUTSTANDING).
- RFE creation pins issued_at, computes deadline_at = issued_at +
  rfe_response_window_days * 86400 seconds, mirrors deadline_at onto
  Case.rfe_deadline, and transitions parent to RFE_ISSUED.
- Response in-window: status -> RESPONDED, response_received_at set,
  Case.rfe_deadline cleared, parent -> RFE_RESPONDED.
- Response strictly after deadline -> ERR_RFE_DEADLINE_PASSED.
- The exact instant equal to deadline_at is in-window (boundary).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_RFE_WINDOW_DAYS,
    SECONDS_PER_DAY,
    advance_clock_to,
    api_client,
    assert_rfe,
    issue_rfe,
    iso_utc,
    parse_iso,
    re_get_case,
    respond_rfe,
    server_now_dt,
    setup_biometrics_completed,
    setup_filed_case,
    setup_i130_in_rfe_issued,
    validate_error,
    validate_success,
)


class TestRFEIssuance:

    def test_issue_rfe_sets_deadline_and_mirrors_to_case(self, api):
        """PRD §3.5: "Its deadline_at is set to issued_at plus the
        matching CaseTypeConfig.rfe_response_window_days converted to
        seconds (each day is 86,400 seconds; the default window across
        all four form types is 87 days). The same instant is mirrored
        onto the parent case's rfe_deadline field".

        Claim: a freshly issued RFE has deadline_at == issued_at +
        window_days * 86400 seconds, and Case.rfe_deadline equals
        RFE.deadline_at.
        """
        bundle = setup_biometrics_completed(case_type="I-485")
        case = bundle["case"]
        rfe = issue_rfe(case)
        assert_rfe(rfe)
        assert rfe["status"] == "OUTSTANDING"
        issued = parse_iso(rfe["issued_at"])
        deadline = parse_iso(rfe["deadline_at"])
        delta_seconds = (deadline - issued).total_seconds()
        expected_seconds = DEFAULT_RFE_WINDOW_DAYS * SECONDS_PER_DAY
        assert delta_seconds == expected_seconds, (
            f"deadline_at - issued_at must equal "
            f"{DEFAULT_RFE_WINDOW_DAYS} days = {expected_seconds}s; "
            f"got {delta_seconds}s"
        )
        parent = re_get_case(case["id"])
        assert parent["status"] == "RFE_ISSUED"
        assert parent["rfe_deadline"] == rfe["deadline_at"], (
            f"Case.rfe_deadline must mirror RFE.deadline_at; got "
            f"case={parent['rfe_deadline']!r} rfe={rfe['deadline_at']!r}"
        )

    def test_double_issue_rejected(self, api):
        """PRD §3.5: "Issuing an RFE requires that no other RFE on the
        case currently sit in OUTSTANDING status; a second concurrent
        issue attempt is rejected with ERR_RFE_ALREADY_OUTSTANDING".

        Claim: a second /rfe while one is OUTSTANDING ->
        ERR_RFE_ALREADY_OUTSTANDING.
        """
        bundle = setup_biometrics_completed(case_type="I-485")
        case = bundle["case"]
        issue_rfe(case)
        resp = api_client.issue_rfe(
            case["id"],
            {"reason_code": "IDENTITY_DOC",
             "officer_notes": "Second attempt."},
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(
            resp, ApiErrorId.ERR_RFE_ALREADY_OUTSTANDING.value,
        )

    def test_invalid_reason_code_rejected(self, api):
        """PRD §3.5: "The officer supplies the reason_code (one of
        MISSING_DOC, IDENTITY_DOC, FINANCIAL_PROOF, MEDICAL_EXAM, or
        TRANSLATION)".

        Claim: an unknown reason_code -> ERR_VALIDATION.
        """
        bundle = setup_biometrics_completed(case_type="I-485")
        case = bundle["case"]
        resp = api_client.issue_rfe(
            case["id"],
            {"reason_code": "UNKNOWN", "officer_notes": "n"},
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Response
# ===========================================================================
class TestRFEResponse:

    def test_response_in_window_clears_deadline(self, api):
        """PRD §3.5: "Accepting a response sets the RFE's status to
        RESPONDED, pins response_received_at to the present instant,
        clears the case's rfe_deadline back to null, transitions the
        parent case from RFE_ISSUED to RFE_RESPONDED".

        Claim: respond before deadline_at -> RFE.status=RESPONDED,
        response_received_at non-null, Case.rfe_deadline cleared,
        parent Case.status=RFE_RESPONDED.
        """
        bundle = setup_biometrics_completed(case_type="I-485")
        case = bundle["case"]
        petitioner = bundle["petitioner"]
        rfe = issue_rfe(case)
        responded = respond_rfe(rfe, petitioner)
        assert responded["status"] == "RESPONDED"
        assert responded.get("response_received_at") is not None
        parent = re_get_case(case["id"])
        assert parent["status"] == "RFE_RESPONDED"
        assert parent.get("rfe_deadline") is None, (
            f"Case.rfe_deadline must be cleared after RFE response; "
            f"got {parent.get('rfe_deadline')!r}"
        )

    def test_response_strictly_after_deadline_rejected(self, api):
        """PRD §3.5: "A response received strictly after deadline_at is
        rejected with ERR_RFE_DEADLINE_PASSED."

        Claim: advancing the clock 1ms past deadline_at and then
        attempting respond -> ERR_RFE_DEADLINE_PASSED.
        """
        bundle = setup_biometrics_completed(case_type="I-485")
        case = bundle["case"]
        petitioner = bundle["petitioner"]
        rfe = issue_rfe(case)
        deadline = parse_iso(rfe["deadline_at"])
        # Advance 1 millisecond past deadline_at — strictly greater.
        advance_clock_to(iso_utc(deadline + timedelta(milliseconds=1)))
        resp = api_client.respond_rfe(
            rfe["id"],
            {"X-User-ID": petitioner["id"], "X-User-Role": "Petitioner",
             "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_RFE_DEADLINE_PASSED.value)

    def test_response_at_exact_deadline_in_window(self, api):
        """PRD §2.8 / §3.5: "The RFE response deadline is stored as an
        ISO 8601 timestamp to millisecond precision; comparisons
        against it use strict greater-than semantics, so the exact
        instant equal to deadline_at is still in-window and only a
        strictly later instant marks the RFE as past due."

        Claim: at now() == deadline_at exactly the response succeeds.
        """
        bundle = setup_biometrics_completed(case_type="I-485")
        case = bundle["case"]
        petitioner = bundle["petitioner"]
        rfe = issue_rfe(case)
        deadline = parse_iso(rfe["deadline_at"])
        # Advance exactly to deadline_at.
        advance_clock_to(iso_utc(deadline))
        resp = api_client.respond_rfe(
            rfe["id"],
            {"X-User-ID": petitioner["id"], "X-User-Role": "Petitioner",
             "Content-Type": "application/json"},
        )
        data = validate_success(resp)
        assert data["status"] == "RESPONDED"


# ===========================================================================
# RFE issuable from FILED when biometrics not required
# ===========================================================================
class TestRFEFromFiled:

    def test_i130_can_issue_rfe_from_filed(self, api):
        """PRD §3.5: "when biometrics is not required the RFE may
        issue directly from FILED (so the parent transitions are
        FILED → RFE_ISSUED)".

        Claim: an I-130 (requires_biometrics=false) in FILED can have
        an RFE issued and transitions FILED -> RFE_ISSUED.
        """
        bundle = setup_i130_in_rfe_issued()
        case = bundle["case"]
        assert case["status"] == "RFE_ISSUED"
        assert case.get("rfe_deadline") is not None
