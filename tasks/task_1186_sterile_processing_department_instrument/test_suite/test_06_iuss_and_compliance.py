"""Immediate-use steam sterilization exceptions: the rolling-window
supervisor gate, the dual-rate compliance summary, and the IUSS lifecycle.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_supervisor_headers,
    make_technician_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]
AUDIT = TEST_USERS["quality_auditor_headers"]


class TestIussRateBoundary:
    """The prospective-count >= 4 supervisor gate (two tests, one design
    instance)."""

    def _log_three_then_fourth_as_technician(self, api, s):
        h = make_technician_headers(s.tech_a["id"])
        for tray in s.trays[:3]:
            resp = api.create_iuss_exception(
                f.create_iuss_payload(tray["id"], s.cu["id"]), h
            )
            validate_success(resp, 201)
        return api.create_iuss_exception(
            f.create_iuss_payload(s.trays[3]["id"], s.cu["id"]), h
        )

    def test_third_event_allowed_fourth_technician_rejected(self, api):
        """PRD §3.6: "count the exceptions with `logged_at` inside the
        trailing 168 hours — the window start is exclusive, the current
        instant inclusive — and add the prospective event; if that prospective
        count reaches 4, the caller must be a `SpdSupervisor`, else
        `ERR_IUSS_RATE_EXCEEDED` (403). A technician may therefore log the
        first, second, and third events inside a window; the fourth belongs to
        the supervisor alone."

        Design: Difficulty/boundary_precision_check/iuss_third_event_allowed_fourth_requires_supervisor
        """
        s = fx.setup_iuss_boundary_scenario(api)
        fourth = self._log_three_then_fourth_as_technician(api, s)
        validate_error(fourth, ApiErrorId.ERR_IUSS_RATE_EXCEEDED)
        tray = validate_success(api.get_tray(s.trays[3]["id"], ADMIN))
        assert tray["status"] == "DECONTAMINATED", (
            "the rejected fourth attempt left the tray untouched"
        )

    def test_fourth_event_succeeds_for_supervisor(self, api):
        """PRD §3.6: "if that prospective count reaches 4, the caller must be
        a `SpdSupervisor`, else `ERR_IUSS_RATE_EXCEEDED` (403). A technician
        may therefore log the first, second, and third events inside a window;
        the fourth belongs to the supervisor alone."

        Design: Difficulty/boundary_precision_check/iuss_third_event_allowed_fourth_requires_supervisor
        """
        s = fx.setup_iuss_boundary_scenario(api)
        fourth = self._log_three_then_fourth_as_technician(api, s)
        validate_error(fourth, ApiErrorId.ERR_IUSS_RATE_EXCEEDED)

        sup = api.create_iuss_exception(
            f.create_iuss_payload(
                s.trays[3]["id"], s.cu["id"],
                justification="Emergency turnover; supervisor authorized flash",
            ),
            make_supervisor_headers(s.tech_s["id"]),
        )
        validate_success(sup, 201)
        tray = validate_success(api.get_tray(s.trays[3]["id"], ADMIN))
        assert tray["status"] == "IN_USE", (
            "the gate is role-based: the supervisor's identical 4th event lands"
        )


class TestIussRateVariants:
    """Identical numerator, two denominator variants (two tests, one design
    instance)."""

    def test_window_counts(self, api):
        """PRD §3.8: "The summary reports `iuss_count_7d` — exceptions with
        `logged_at` in the trailing 168 hours, window start exclusive and the
        current instant inclusive; `completed_cases_30d` — cases `COMPLETED`
        with `completed_at` in the trailing 720 hours on the same window
        semantics; `scheduled_cases_30d` — cases whose `scheduled_start_at`
        falls in the trailing 720 hours, regardless of status".

        Design: Difficulty/dual_variant_calc/iuss_rate_per_completed_vs_per_scheduled
        """
        fx.setup_iuss_rate_scenario(api)
        data = validate_success(api.get_compliance_summary(ADMIN))
        assert data["iuss_count_7d"] == 2
        assert data["completed_cases_30d"] == 2
        assert data["scheduled_cases_30d"] == 5, (
            "the CANCELLED case still counts toward the scheduled denominator"
        )
        assert data["loads_recalled_30d"] == 0
        assert data["trays_quarantined_count"] == 0

    def test_rate_variants_diverge_on_denominator(self, api):
        """PRD §3.8: "two rate variants to 4 decimal places, round half up:
        `iuss_rate_per_completed` divides `iuss_count_7d` by the larger of
        `completed_cases_30d` and 1, while `iuss_rate_per_scheduled` divides
        it by the larger of `scheduled_cases_30d` and 1 — the scheduled
        denominator is never the smaller one, so identical numerators yield a
        smaller-or-equal scheduled rate."

        Design: Difficulty/dual_variant_calc/iuss_rate_per_completed_vs_per_scheduled
        """
        fx.setup_iuss_rate_scenario(api)
        data = validate_success(api.get_compliance_summary(ADMIN))
        assert float(data["iuss_rate_per_completed"]) == pytest.approx(1.0), (
            "2 / max(2, 1)"
        )
        assert float(data["iuss_rate_per_scheduled"]) == pytest.approx(0.4), (
            "2 / max(5, 1) — same numerator, different denominator variant"
        )


def test_iuss_double_review_rejected(api):
    """PRD §3.6: "A `QualityAuditor` reviews a `DOCUMENTED` exception — a
    second review draws `ERR_IUSS_ALREADY_REVIEWED` — moving it to `REVIEWED`
    and recording an optional `review_note`."

    Design: Corner/state_machines/iuss_double_review_rejected
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    ur = fx.create_decontaminated_tray(api, tpl["id"], tech["id"], label="UR")
    cr = fx.create_case(api, case_number="C-R", surgeon="Dr R",
                        scheduled_start_at="2026-05-02T09:00:00Z",
                        scheduled_end_at="2026-05-02T10:00:00Z", priority="URGENT")
    iuss = validate_success(
        api.create_iuss_exception(
            f.create_iuss_payload(ur["id"], cr["id"]),
            make_technician_headers(tech["id"]),
        ),
        201,
    )
    r1 = validate_success(
        api.review_iuss_exception(iuss["id"], {"review_note": "Reviewed; coaching scheduled"}, AUDIT)
    )
    assert r1["status"] == "REVIEWED"
    e2 = api.review_iuss_exception(iuss["id"], {"review_note": "Second review attempt"}, AUDIT)
    validate_error(e2, ApiErrorId.ERR_IUSS_ALREADY_REVIEWED)


def test_iuss_tray_eligibility_and_terminal_case_gates(api):
    """PRD §3.6: "a `justification` of at least 20 characters (shorter draws
    `ERR_JUSTIFICATION_TOO_SHORT`). The tray must be `DECONTAMINATED` or
    `ASSEMBLED` (else `ERR_IUSS_TRAY_NOT_ELIGIBLE`)". "Referencing a case
    already `COMPLETED` or `CANCELLED` is rejected with
    `ERR_CASE_TERMINAL_FOR_IUSS`." PRD §2.6: request-shape screening (step 4)
    precedes state-machine preconditions (step 6).

    Each gate is exercised in isolation so no two checks fail on the same
    call.

    Design: Corner/state_machines/iuss_tray_eligibility_and_terminal_case_gates
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    uf = fx.create_tray(api, tpl["id"], tech["id"], label="UF")  # AWAITING_DECONTAMINATION
    ud = fx.create_decontaminated_tray(api, tpl["id"], tech["id"], label="UD")
    cg = fx.create_case(api, case_number="C-G", surgeon="Dr G",
                        scheduled_start_at="2026-05-02T09:00:00Z",
                        scheduled_end_at="2026-05-02T10:00:00Z", priority="ELECTIVE")
    validate_success(api.cancel_case(cg["id"], TEST_USERS["or_scheduler_headers"]))
    c_ok = fx.create_case(api, case_number="C-OK", surgeon="Dr K",
                          scheduled_start_at="2026-05-03T09:00:00Z",
                          scheduled_end_at="2026-05-03T10:00:00Z", priority="ELECTIVE")
    h = make_technician_headers(tech["id"])

    # Shape gate (PRD §2.6 step 4) fires before any state gate.
    e1 = api.create_iuss_exception(
        f.create_iuss_payload(uf["id"], cg["id"], justification="short"), h
    )
    validate_error(e1, ApiErrorId.ERR_JUSTIFICATION_TOO_SHORT)

    # Tray gate in isolation: the case is live, only the tray is ineligible.
    e2 = api.create_iuss_exception(f.create_iuss_payload(uf["id"], c_ok["id"]), h)
    validate_error(e2, ApiErrorId.ERR_IUSS_TRAY_NOT_ELIGIBLE)

    # Case gate in isolation: the tray is eligible, only the case is terminal.
    e3 = api.create_iuss_exception(f.create_iuss_payload(ud["id"], cg["id"]), h)
    validate_error(e3, ApiErrorId.ERR_CASE_TERMINAL_FOR_IUSS)
