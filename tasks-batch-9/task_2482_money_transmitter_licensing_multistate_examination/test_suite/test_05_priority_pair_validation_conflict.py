"""Error precedence when two rules reject the same coverage certification.

A chief compliance officer who prepared a permissible-investment test and then
certifies it himself after the forty-five day window has closed breaches two
rules at once: the segregation of duties of PRD 2.10, which the ladder of PRD 2.7
evaluates at business-safety step 8, and the certification window of PRD 3.7,
which the same ladder evaluates at temporal-window step 10. Only one error may
come back, and it must be the safety one.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CERTIFICATION_WINDOW_CLOSED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.test_users import (
    CHIEF_HEADERS,
    SECOND_CHIEF_HEADERS,
    USER_CHIEF_COMPLIANCE_OFFICER,
)

# The closed coverage period every test below files on. Its certification
# deadline is 2026-06-30 plus forty-five days, i.e. 2026-08-14T00:00:00Z.
PERIOD_START = "2026-04-01T00:00:00Z"
PERIOD_END = "2026-06-30T00:00:00Z"
CERTIFICATION_DEADLINE = "2026-08-14T00:00:00Z"
LATE_CLOCK = "2026-09-01T00:00:00Z"


def _prepared_test_with_a_closed_window(
    api: MoneyTransmitterApiClient, licensee_id: str
) -> dict:
    """Open a test, prepare it as the chief officer, then close its window.

    The prepare step runs under ``CHIEF_HEADERS`` so that
    ``prepared_by_user_id`` records that identity, and the clock is then pushed
    well past the certification deadline of the period.
    """
    test = fx.open_investment_test(
        api,
        licensee_id,
        "ELIGIBLE_MARKET",
        coverage_period_start=PERIOD_START,
        coverage_period_end=PERIOD_END,
    )
    prepared = fx.prepare_investment_test(api, test["id"], CHIEF_HEADERS)
    assert prepared["status"] == "PREPARED"
    assert prepared["prepared_by_user_id"] == USER_CHIEF_COMPLIANCE_OFFICER
    fx.set_clock(api, LATE_CLOCK)
    return prepared


def test_self_certification_after_the_window_closes_reports_segregation_of_duties(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The preparer certifying late gets the safety error, not the window error.

    PRD 2.7: "When several rules could reject the same request, the system evaluates them in a fixed order and returns the error of the first rule that fails."
    PRD 2.7: "8. **Business safety**, in this order: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), background-check completeness (`ERR_BACKGROUND_CHECK_INCOMPLETE`), control-chain block (`ERR_CONTROL_CHAIN_BLOCKED`), frozen coverage posture (`ERR_POSTURE_FROZEN`), expansion gate (`ERR_EXPANSION_GATE_BLOCKED`), oversight score (`ERR_OVERSIGHT_SCORE_INSUFFICIENT`), remediation plan presence (`ERR_REMEDIATION_PLAN_REQUIRED`)."
    PRD 2.7: "10. **Temporal windows**, in this order: examination window conflict (`ERR_EXAM_WINDOW_CONFLICT`), delegate period overlap (`ERR_DELEGATE_PERIOD_OVERLAP`), certification window (`ERR_CERTIFICATION_WINDOW_CLOSED`), information-request response window (`ERR_RESPONSE_WINDOW_CLOSED`), deficiency deadline (`ERR_DEFICIENCY_DEADLINE_PASSED`), enforcement response window (`ERR_ENFORCEMENT_RESPONSE_WINDOW_CLOSED`), remediation deadline (`ERR_REMEDIATION_DEADLINE_PASSED`), bond cancellation notice period (`ERR_BOND_NOTICE_TOO_SHORT`)."
    PRD 2.10: "The certifying identity must differ from the preparing identity; a certification attempt whose `X-User-ID` equals the recorded `prepared_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD 3.7: "It is admissible only from `PREPARED`; the certifying `X-User-ID` must differ from `prepared_by_user_id` per §2.10; and it must arrive on or before forty-five days after `coverage_period_end` — the boundary is inclusive, and a late certification is rejected with `ERR_CERTIFICATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/certify_by_preparer_after_window_close_rejects_with_segregation_error
    """
    prepared = _prepared_test_with_a_closed_window(api, licensee["id"])

    # Read the row back so both losing and winning conditions are on the record:
    # the preparer is the identity that is about to certify, and the window that
    # PRD 3.7 measures from coverage_period_end has already run out.
    row = validate_success(api.get_investment_test(prepared["id"], CHIEF_HEADERS))
    assert row["status"] == "PREPARED"
    assert row["prepared_by_user_id"] == USER_CHIEF_COMPLIANCE_OFFICER
    assert row["coverage_period_end"] == PERIOD_END
    # 2026-06-30 plus the forty-five day window is 2026-08-14; the clock is at
    # 2026-09-01, eighteen days beyond it.
    assert C.iso_add_days(PERIOD_END, C.CERTIFICATION_WINDOW_DAYS) == CERTIFICATION_DEADLINE
    assert LATE_CLOCK > CERTIFICATION_DEADLINE

    response = api.certify_investment_test(
        prepared["id"], CHIEF_HEADERS, F.certify_payload()
    )

    # Step 8 outranks step 10, so exactly one error comes back and it is the
    # segregation breach.
    error = validate_error(response, ERR_SEGREGATION_OF_DUTIES, 409)
    assert error["error_id"] != ERR_CERTIFICATION_WINDOW_CLOSED


def test_the_certification_window_really_had_closed_for_a_second_chief_officer(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """With the segregation breach removed, the same clock closes the window.

    PRD 2.10: "`prepared_by_user_id` records the `X-User-ID` of whoever ran the prepare step; `certified_by_user_id` records the `X-User-ID` of whoever certified."
    PRD 2.10: "Because only a `ChiefComplianceOfficer` may certify, and both a `ComplianceOfficer` and a `ChiefComplianceOfficer` may prepare, the practical effect is that a chief compliance officer who prepared a test must hand certification to a colleague."
    PRD 3.7: "It is admissible only from `PREPARED`; the certifying `X-User-ID` must differ from `prepared_by_user_id` per §2.10; and it must arrive on or before forty-five days after `coverage_period_end` — the boundary is inclusive, and a late certification is rejected with `ERR_CERTIFICATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/certify_by_preparer_after_window_close_rejects_with_segregation_error
    """
    prepared = _prepared_test_with_a_closed_window(api, licensee["id"])

    # A different chief compliance officer satisfies segregation of duties, so
    # the only rule left to fail on this certify call is the temporal one.
    response = api.certify_investment_test(
        prepared["id"], SECOND_CHIEF_HEADERS, F.certify_payload()
    )

    error = validate_error(response, ERR_CERTIFICATION_WINDOW_CLOSED, 409)
    assert error["error_id"] != ERR_SEGREGATION_OF_DUTIES

    row = validate_success(api.get_investment_test(prepared["id"], CHIEF_HEADERS))
    assert row["status"] == "PREPARED"
    assert row["certified_by_user_id"] is None


def test_the_rejected_self_certification_leaves_the_test_and_the_licensee_untouched(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A rejected certification certifies nothing and moves no failure counter.

    PRD 2.10: "The certifying identity must differ from the preparing identity; a certification attempt whose `X-User-ID` equals the recorded `prepared_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD 3.7: "First, the test moves `PREPARED → CERTIFIED`, `certified_at` is stamped from the logical clock, `certified_by_user_id` records the acting identity, and the licensee's `consecutive_failed_test_count` either increases by one — when the test's `result` is `SHORTFALL` — or resets to zero when it is `PASS`; `coverage_posture` is then recomputed, and because two consecutive certified shortfalls set the count to 2, the second one alone forces the posture to `FROZEN` no matter how good the ratio looks."
    PRD 3.7: "Certification bumps `Licensee.version`."

    Design: Difficulty/priority_pair_validation_conflict/certify_by_preparer_after_window_close_rejects_with_segregation_error
    """
    prepared = _prepared_test_with_a_closed_window(api, licensee["id"])
    before = fx.get_licensee(api, licensee["id"])

    response = api.certify_investment_test(
        prepared["id"], CHIEF_HEADERS, F.certify_payload()
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 409)

    row = validate_success(api.get_investment_test(prepared["id"], CHIEF_HEADERS))
    assert row["status"] == "PREPARED"
    assert row["certified_by_user_id"] is None
    assert row["certified_at"] is None
    # The prepared verdict itself is untouched: no obligations and no holdings
    # means a vacuously perfect ratio of 10000 basis points and a PASS.
    assert row["obligations_cents"] == 0
    assert row["coverage_ratio_bps"] == 10000
    assert row["result"] == "PASS"

    after = fx.get_licensee(api, licensee["id"])
    assert after["consecutive_failed_test_count"] == 0
    assert after["version"] == before["version"]
    assert after["coverage_posture"] == "COMPLIANT"
