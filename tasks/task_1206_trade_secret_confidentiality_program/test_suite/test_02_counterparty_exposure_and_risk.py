"""Counterparty exposure indexes and risk tiering (PRD §2.8)."""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_obligation_payload,
    create_registered_asset,
    add_verified_measure,
    create_employee_record,
    create_approved_disclosure,
    create_under_review_disclosure,
    make_employee_headers,
    make_counterparty_rep_headers,
    make_obligations_overdue,
    escalate_obligations,
    SHA256_A,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
SEC = TEST_USERS["security_officer_headers"]


def _setup_counterparty_with_history(api):
    """Counterparty with ACTIVE NDA; one obligation escalated at 2026-05-20;
    one disclosure executed at 2026-06-01."""
    cp = create_counterparty(legal_name="Acme Parts Ltd", counterparty_type="VENDOR")
    nda = create_active_nda(
        cp["id"], template_version="t1", governing_law="DE",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2026-12-31T00:00:00Z",
        survival_months=12, classification_ceiling="RESTRICTED",
    )
    resp = api.create_obligation(
        create_obligation_payload(nda["id"], obligation_type="NON_USE",
                                  due_at="2026-05-10T00:00:00Z"), IP
    )
    ob_id = validate_success(resp, expected_status=201)["id"]
    api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, IP)
    api.run_sweep(IP)
    validate_success(api.transition_obligation(ob_id, {"to_status": "ESCALATED"}, IP))

    asset = create_registered_asset(
        title="Sensor calibration table", description="lookup tables",
        classification="CONFIDENTIAL", owner_department="ENG",
        exposure_estimate_cents=100000,
    )
    add_verified_measure(asset["id"], "TECHNICAL", title="Encryption at rest",
                         evidence_uri="s3://ev/enc.pdf")
    add_verified_measure(asset["id"], "CONTRACTUAL", title="Confidentiality clauses",
                         evidence_uri="s3://ev/cl.pdf")
    emp = create_employee_record(
        full_name="Dana Engineer", email="dana@x.com", department="ENG",
        role_title="Engineer", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    # final risk = 30 * 1.0 (LOW) - 10 = 20 < 80, so no endorsement needed
    disc = create_approved_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="Joint eval", marking_protocol="STAMPED_CONFIDENTIAL",
        planned_disclosure_date="2026-06-15T00:00:00Z",
    )
    api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, IP)
    validate_success(api.transition_disclosure(
        disc["id"],
        {"to_status": "EXECUTED", "marking_evidence_uri": "s3://ev/marked.pdf",
         "marking_sha256": SHA256_A},
        IP,
    ))
    return cp


class TestCounterpartyExposureTrailingVsLifetime:
    def test_trailing_window_excludes_old_events(self, api):
        """PRD §2.8: "The trailing variant, `exposure_index_trailing`, is the sum
        of those in-window points, capped at 100."
        PRD §2.8: "The window is the closed interval from 365 days before the
        current clock through the current clock, inclusive at both ends — an
        event exactly 365 days old still counts."

        Design: Difficulty/dual_variant_calc/counterparty_exposure_trailing_vs_lifetime
        """
        cp = _setup_counterparty_with_history(api)
        api.set_clock({"to_iso8601": "2027-07-01T00:00:00Z"}, IP)
        data = validate_success(api.get_counterparty(cp["id"], IP))
        assert data["exposure_index_trailing"] == 0, \
            f"both events older than 365 days; escalated obligation is not OVERDUE-now; got {data['exposure_index_trailing']}"

    def test_lifetime_counts_all_events_and_tier_follows_trailing(self, api):
        """PRD §2.8: "The lifetime variant, `exposure_index_lifetime`, applies
        the same point values with no time window at all: every escalated
        obligation and every executed disclosure counts regardless of age."
        PRD §2.8: "The `risk_tier` derives from the trailing variant alone:
        `LOW` below 30 points, `MEDIUM` from 30 up to but not including 60, and
        `HIGH` at 60 or more."

        Design: Difficulty/dual_variant_calc/counterparty_exposure_trailing_vs_lifetime
        """
        cp = _setup_counterparty_with_history(api)
        api.set_clock({"to_iso8601": "2027-07-01T00:00:00Z"}, IP)
        data = validate_success(api.get_counterparty(cp["id"], IP))
        assert data["exposure_index_lifetime"] == 30, \
            f"expected 25 escalated + 5 executed = 30, got {data['exposure_index_lifetime']}"
        assert data["risk_tier"] == "LOW", "trailing 0 < 30 must be LOW"


class TestRiskTierBoundary:
    def test_trailing_exactly_30_is_medium(self, api):
        """PRD §2.8: "The `risk_tier` derives from the trailing variant alone:
        `LOW` below 30 points, `MEDIUM` from 30 up to but not including 60, and
        `HIGH` at 60 or more — so an index of exactly 30 is `MEDIUM` and exactly
        60 is `HIGH`."
        PRD §2.8: "each obligation currently `OVERDUE` contributes 10 points,
        counted at the present moment with no window applied."

        Design: Corner/calculations/risk_tier_boundary_exactly_30_is_medium
        """
        cp = create_counterparty(legal_name="Sigma Freight", counterparty_type="VENDOR")
        nda = create_active_nda(
            cp["id"], template_version="t16", governing_law="UT",
            effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
            survival_months=3, classification_ceiling="INTERNAL",
        )
        for otype in ["NON_DISCLOSURE", "NON_USE", "AUDIT_RIGHT"]:
            api.create_obligation(
                create_obligation_payload(nda["id"], obligation_type=otype,
                                          due_at="2026-05-10T00:00:00Z"), IP
            )
        api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, IP)
        validate_success(api.run_sweep(IP))
        data = validate_success(api.get_counterparty(cp["id"], IP))
        assert data["exposure_index_trailing"] == 30, \
            f"3 x 10 OVERDUE-now = 30, got {data['exposure_index_trailing']}"
        assert data["risk_tier"] == "MEDIUM", "exactly 30 must be MEDIUM (boundary inclusive)"
