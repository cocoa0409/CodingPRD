"""Difficulty Rule 6 — boundary_precision_check.

(A) ClosingDisclosure 72-hour boundary: at exactly 72h acknowledge SUCCEEDS;
    at 72h - 1 second it FAILS with ERR_CD_THREE_DAY_NOT_ELAPSED.
(B) Reissue material-change at 12 bps SUCCEEDS; at 11 bps FAILS with
    ERR_CD_REISSUE_NOT_MATERIAL.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_delivered_cd,
    advance_clock,
    reissue_closing_disclosure_payload,
    api_client,
)


class TestClosingDisclosure72HourAcknowledgeBoundary:
    """The wait is closed on the boundary: clock >= earliest_consummation_at
    is permitted; strictly less is rejected.
    """

    def test_acknowledge_one_second_before_boundary_rejected(self, api):
        """PRD §3.4: "Acknowledgement is the buyer's confirmation that the disclosure has been read."
        PRD §3.4: "It is gated on time: the current UTC clock must be at or after ``earliest_consummation_at``. Acknowledging on the 72-hour mark itself is allowed; strictly earlier is rejected with ``ERR_CD_THREE_DAY_NOT_ELAPSED`` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/cd_three_day_72h_exact_boundary
        """
        scenario = setup_delivered_cd(initial_iso8601="2026-06-01T00:00:00Z")
        # Clock is at 2026-06-01T00:00:00Z, earliest_consummation_at = +72h.
        # Advance 259199s = 72h - 1s.
        advance_clock(259199, scenario["actors"]["co"])
        res = api.acknowledge_closing_disclosure(
            scenario["cd_id"], scenario["actors"]["eo"]
        )
        validate_error(res, "ERR_CD_THREE_DAY_NOT_ELAPSED", expected_status=409)

    def test_acknowledge_exactly_at_boundary_succeeds(self, api):
        """PRD §3.4: "It is gated on time: the current UTC clock must be at or after ``earliest_consummation_at``. Acknowledging on the 72-hour mark itself is allowed; strictly earlier is rejected with ``ERR_CD_THREE_DAY_NOT_ELAPSED`` (HTTP 409). Acknowledgement stamps ``acknowledged_at`` to the current UTC clock."

        Design: Difficulty/boundary_precision_check/cd_three_day_72h_exact_boundary
        """
        scenario = setup_delivered_cd(initial_iso8601="2026-06-01T00:00:00Z")
        advance_clock(259200, scenario["actors"]["co"])  # +72h exactly
        res = api.acknowledge_closing_disclosure(
            scenario["cd_id"], scenario["actors"]["eo"]
        )
        cd = validate_success(res, expected_status=200)
        assert cd["status"] == "ACKNOWLEDGED", \
            f"acknowledge at exactly 72h must succeed, got {cd['status']}"
        assert cd["acknowledged_at"].startswith("2026-06-04T00:00:00"), \
            f"acknowledged_at must stamp the 72h instant (2026-06-04T00:00:00Z), got {cd['acknowledged_at']}"


class TestClosingDisclosureReissueMaterialChangeAprBoundary:
    """The reissue material-change predicate uses '>=' on the absolute APR
    delta: 12 bps is material, 11 bps is not.
    """

    def test_reissue_at_11_bps_delta_rejected_not_material(self, api):
        """PRD §3.4: "The reissue is rejected with ``ERR_CD_REISSUE_NOT_MATERIAL`` unless the change is material under the following rule, evaluated against the current stored CD: the absolute difference between the request's ``cd_apr_bps`` and the current ``cd_apr_bps`` is at least 12 basis points (so an absolute delta of 12 bps is material; an absolute delta of 11 bps is not), or the request's ``cd_product_type`` differs from the current value, or ``cd_prepayment_penalty`` changes specifically from ``false`` to ``true``."

        Design: Difficulty/boundary_precision_check/cd_reissue_material_change_12bps_boundary
        """
        scenario = setup_delivered_cd(initial_iso8601="2026-06-01T00:00:00Z", cd_apr_bps=600)
        res = api.reissue_closing_disclosure(
            scenario["cd_id"],
            reissue_closing_disclosure_payload(cd_apr_bps=611),
            scenario["actors"]["eo"],
        )
        validate_error(res, "ERR_CD_REISSUE_NOT_MATERIAL", expected_status=422)

    def test_reissue_at_exactly_12_bps_delta_succeeds(self, api):
        """PRD §3.4: "The reissue is rejected with ``ERR_CD_REISSUE_NOT_MATERIAL`` unless the change is material under the following rule, evaluated against the current stored CD: the absolute difference between the request's ``cd_apr_bps`` and the current ``cd_apr_bps`` is at least 12 basis points (so an absolute delta of 12 bps is material; an absolute delta of 11 bps is not), or the request's ``cd_product_type`` differs from the current value, or ``cd_prepayment_penalty`` changes specifically from ``false`` to ``true``."
        PRD §3.4: "When the change is material, the supplied fields are written, the disclosure advances from ``DELIVERED`` to ``REISSUED``, ``issued_at`` is re-stamped to the current UTC clock, and ``earliest_consummation_at`` is recomputed as the new ``issued_at`` plus 72 hours — restarting the three-day clock from scratch."

        Design: Difficulty/boundary_precision_check/cd_reissue_material_change_12bps_boundary
        """
        scenario = setup_delivered_cd(initial_iso8601="2026-06-01T00:00:00Z", cd_apr_bps=600)
        res = api.reissue_closing_disclosure(
            scenario["cd_id"],
            reissue_closing_disclosure_payload(cd_apr_bps=612),
            scenario["actors"]["eo"],
        )
        cd = validate_success(res, expected_status=200)
        assert cd["status"] == "REISSUED", \
            f"delta of exactly 12 bps is material → REISSUED expected, got {cd['status']}"
        assert cd["cd_apr_bps"] == 612, \
            f"cd_apr_bps must be rewritten to 612, got {cd['cd_apr_bps']}"
