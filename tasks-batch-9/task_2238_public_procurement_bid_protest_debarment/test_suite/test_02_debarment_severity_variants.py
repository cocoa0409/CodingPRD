"""The severity of one debarment proceeding, scored twice by two different rules.

The notice of proposed debarment scores the adequate-evidence figure that
justifies an interim suspension; the merits decision re-scores the very same
factor codes under the preponderance rule, which credits the respondent's
mitigation and therefore lands on a shorter period.
"""
from datetime import datetime
from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions
from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import DEBARMENT_AUTHORITY_HEADERS

NOTICE_UTC = "2026-08-01T00:00:00Z"
RESPONSE_UTC = "2026-08-02T00:00:00Z"
DECISION_UTC = "2026-08-20T00:00:00Z"

# FRAUD 40 + SAFETY_VIOLATION 15.
AGGRAVATING_TOTAL = 55.00
# SELF_DISCLOSURE 15 + COOPERATION 8, under the cap of half of 55.00.
MITIGATING_CREDIT = 23.00
INTERIM_SEVERITY = 55.00
FINAL_SEVERITY = 32.00
PERIOD_MONTHS = 12
DEBARMENT_END_UTC = "2027-08-20T00:00:00Z"
EARLIEST_PETITION_UTC = "2027-02-20T00:00:00Z"


def _instant(value: Any) -> datetime:
    """Parse an ISO 8601 UTC instant so two renderings of the same instant
    compare equal at millisecond precision."""
    assert isinstance(value, str), "expected an ISO 8601 instant, got {!r}".format(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _build_contested_proceeding_at_hearing_held() -> Dict[str, Any]:
    """One eligible vendor with no strikes, a notice of proposed debarment
    carrying an interim suspension on two aggravating factors and no mitigation,
    a written response merging two mitigating factors, and the contested hearing
    held, with the clock standing at the decision instant."""
    fx.reset_clock()

    vendor = fx.create_vendor(
        legal_name="Cortland Structural Inc",
        tax_id="100000002",
        contact_email="v2@example.gov",
    )
    vendor_id = vendor["id"]
    assert vendor["eligibility_status"] == "ELIGIBLE"
    assert vendor["debarment_strike_count"] == 0

    notice = fx.open_proceeding(
        vendor_id,
        cause_code="FRAUD",
        aggravating_factor_codes=["FRAUD", "SAFETY_VIOLATION"],
        mitigating_factor_codes=[],
        interim_suspension=True,
    )
    proceeding_id = notice["id"]

    fx.set_clock(RESPONSE_UTC)
    fx.file_debarment_response(
        proceeding_id,
        vendor_id,
        response_narrative=(
            "self-reported the invoice error and cooperated with the audit"
        ),
        mitigating_factor_codes=["SELF_DISCLOSURE", "COOPERATION"],
    )
    fx.hold_debarment_hearing(
        proceeding_id,
        hearing_summary="respondent appeared and was heard on the merits",
    )
    fx.set_clock(DECISION_UTC)

    return {
        "vendor_id": vendor_id,
        "proceeding_id": proceeding_id,
        "notice": notice,
    }


def _decide_debarred(proceeding_id: str) -> Dict[str, Any]:
    """Issue the merits decision and return the updated proceeding."""
    response = api_client.decide_debarment(
        proceeding_id,
        fac.debarment_decision_payload(
            outcome="DEBARRED",
            rationale=(
                "cause established by a preponderance; mitigation credited to "
                "the statutory cap"
            ),
        ),
        DEBARMENT_AUTHORITY_HEADERS,
    )
    return validate_success(response)


@pytest.fixture
def contested_state() -> Dict[str, Any]:
    return _build_contested_proceeding_at_hearing_held()


class TestDebarmentSeverityVariants:
    """The interim-suspension scoring of the notice against the final-debarment
    scoring of the merits decision, on one and the same proceeding row."""

    def test_interim_basis_at_notice_then_final_basis_at_decision(self, contested_state):
        """Under the **interim-suspension variant**, which reflects the adequate-evidence standard applicable at notice time, mitigation is ignored entirely and prior strikes do not escalate: `mitigating_credit_points` is 0 and `severity_score` is the aggravating total, capped at 100.

        A raw mitigation total is formed as the sum of the weights of the distinct members of `mitigating_factor_codes` — `SELF_DISCLOSURE` credits 15 points, `RESTITUTION_PAID` 12, `COMPLIANCE_PROGRAM` 10 and `COOPERATION` 8 — and `mitigating_credit_points` is the lesser of that raw total and half of the aggravating total, so mitigation can never erase more than 50 percent of the aggravation.

        Design: Difficulty/dual_variant_calc/debarment_severity_interim_versus_final_variant_divergence
        """
        notice = contested_state["notice"]
        assertions.assert_two_decimal_score(notice["severity_score"], "severity_score")
        assert notice["severity_score"] == pytest.approx(INTERIM_SEVERITY, abs=0.01)
        assert notice["mitigating_credit_points"] == pytest.approx(0, abs=0.01)
        assert notice["aggravating_total_points"] == pytest.approx(
            AGGRAVATING_TOTAL, abs=0.01
        )
        assert notice["status"] == "NOTICE_ISSUED"
        assert notice["interim_status"] == "INTERIM_SUSPENDED"

        decided = _decide_debarred(contested_state["proceeding_id"])
        assertions.assert_two_decimal_score(decided["severity_score"], "severity_score")

        # The two mitigating codes total 23.00 raw, which is under the cap of
        # half of 55.00, so the whole raw total is credited.
        assert decided["mitigating_credit_points"] == pytest.approx(
            MITIGATING_CREDIT, abs=0.01
        )
        assert decided["severity_score"] == pytest.approx(FINAL_SEVERITY, abs=0.01)
        assert decided["aggravating_total_points"] == pytest.approx(
            AGGRAVATING_TOTAL, abs=0.01
        )

        # The same factor codes, scored twice: the gap is exactly the credit.
        assert notice["severity_score"] - decided["severity_score"] == pytest.approx(
            MITIGATING_CREDIT, abs=0.01
        )
        assert decided["status"] == "DEBARRED"

    def test_final_severity_reads_off_the_twelve_month_tier(self, contested_state):
        """**The period** is read off a tier table from the final severity: 60 months at a severity of 80 or more, 36 months at 60 or more, 24 months at 40 or more, and 12 months at 20 or more.

        Design: Difficulty/dual_variant_calc/debarment_severity_interim_versus_final_variant_divergence
        """
        assert contested_state["notice"]["debarment_period_months"] == 0

        decided = _decide_debarred(contested_state["proceeding_id"])

        # A final severity of 32.00 sits in the 20-tier, not the 40-tier the
        # interim figure of 55.00 would have reached.
        assert decided["debarment_period_months"] == PERIOD_MONTHS
        assert decided["debarment_period_months"] not in (24, 36, 60)

    def test_the_period_fixes_the_debarment_window_and_the_petition_ripeness(
        self, contested_state
    ):
        """When a debarment is decided, the respondent's `reinstatement_earliest_petition_utc` is stamped as the proceeding's `debarment_start_utc` plus a number of calendar months equal to half the `debarment_period_months`, rounded up to a whole month.

        The same convention gives `debarment_end_utc` as the start instant plus the full `debarment_period_months`.

        Design: Difficulty/dual_variant_calc/debarment_severity_interim_versus_final_variant_divergence
        """
        decided = _decide_debarred(contested_state["proceeding_id"])

        assert _instant(decided["debarment_start_utc"]) == _instant(DECISION_UTC)
        assert _instant(decided["debarment_end_utc"]) == _instant(DEBARMENT_END_UTC)
        assert _instant(decided["decided_at_utc"]) == _instant(DECISION_UTC)

        vendor = fx.read_vendor(contested_state["vendor_id"])
        assert _instant(vendor["reinstatement_earliest_petition_utc"]) == _instant(
            EARLIEST_PETITION_UTC
        )

    def test_the_interim_strike_converts_rather_than_adding_a_second_one(
        self, contested_state
    ):
        """The strike bookkeeping differs by the vendor's prior posture, and the difference is deliberate: a vendor moving `SUSPENDED → DEBARRED` was already carrying this proceeding's strike, so `interim_status` moves `INTERIM_SUSPENDED → INTERIM_LIFTED` while `strikes_applied` stays 1 and `debarment_strike_count` is unchanged; a vendor moving `ELIGIBLE → DEBARRED` with no interim suspension in force has this proceeding's `strikes_applied` move from 0 to 1, so `debarment_strike_count` increases by 1.

        Design: Difficulty/dual_variant_calc/debarment_severity_interim_versus_final_variant_divergence
        """
        vendor_id = contested_state["vendor_id"]

        assert contested_state["notice"]["strikes_applied"] == 1
        before = fx.read_vendor(vendor_id)
        assert before["eligibility_status"] == "SUSPENDED"
        assert before["debarment_strike_count"] == 1

        decided = _decide_debarred(contested_state["proceeding_id"])
        assert decided["strikes_applied"] == 1
        assert decided["interim_status"] == "INTERIM_LIFTED"

        after = fx.read_vendor(vendor_id)
        assert after["eligibility_status"] == "DEBARRED"
        assert after["debarment_strike_count"] == 1
        assert after["active_debarment_id"] == contested_state["proceeding_id"]
