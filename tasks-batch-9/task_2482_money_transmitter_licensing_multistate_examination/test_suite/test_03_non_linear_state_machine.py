"""Non-linear state machines: the deficiency loop and the two licence dimensions.

Two families of behaviour are exercised here. First, the application deficiency
cycle, where the identical ``ISSUE_DEFICIENCY`` review action takes one edge
three times and a different edge the fourth time because the loop counter
survives every resubmission. Second, the two status dimensions of a state
licence, where the authorisation dimension and the reporting-calendar dimension
advance independently and neither can be derived from the other.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import MANAGER_HEADERS

# The logical clock starts at 2026-08-01T00:00:00Z and is never moved in this
# file, so every armed deficiency deadline is that instant plus 30 days.
DEFICIENCY_DEADLINE = "2026-08-31T00:00:00"

# Volume declared on the application and on every resubmission of it.
APPLIED_VOLUME_CENTS = 250_000_000

# A cancellation notice must be at least thirty days out; sixty days from the
# seed clock is 2026-09-30T00:00:00Z.
BOND_CANCELLATION_DATE = C.iso_add_days(C.SEED_CLOCK, 60)


def _instant(value):
    # Reduce an ISO 8601 UTC stamp to second precision for comparison.
    assert value is not None, "expected a timestamp, got null"
    return value[:19]


def _application_under_review(api, licensee_id, jurisdiction_id):
    # Open an application, submit it, and have the regulator of record start review.
    application = fx.create_application(
        api,
        licensee_id,
        jurisdiction_id,
        projected_annual_volume_cents=APPLIED_VOLUME_CENTS,
    )
    fx.submit_application(api, application["id"])
    return fx.review_application(
        api, application["id"], jurisdiction_id, "START_REVIEW"
    )


def _issue_deficiency(api, application_id, jurisdiction_id, note):
    # One ISSUE_DEFICIENCY review action from the regulator of record.
    return fx.review_application(
        api, application_id, jurisdiction_id, "ISSUE_DEFICIENCY", note=note
    )


def _resubmit(api, application_id, projected_annual_volume_cents=APPLIED_VOLUME_CENTS):
    # Close the correspondence loop from the licensee side.
    return validate_success(
        api.resubmit_application(
            application_id,
            F.resubmit_payload(
                projected_annual_volume_cents,
                remediation_note="Deficiency items addressed.",
            ),
            MANAGER_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# The deficiency loop and its fourth-round denial
# ---------------------------------------------------------------------------


def test_three_deficiency_rounds_all_take_the_loop_edge_to_deficient(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """Rounds one, two and three all move UNDER_REVIEW to DEFICIENT and re-arm the deadline.

    PRD 3.3: "The action `ISSUE_DEFICIENCY`, taken while the application is `UNDER_REVIEW`, increments `deficiency_round_count` and has two outcomes that depend entirely on how many rounds have already been spent."
    PRD 3.3: "While `deficiency_round_count` is below 3, the application moves `UNDER_REVIEW → DEFICIENT` and `deficiency_deadline_at` is set to the current logical clock plus thirty days."
    PRD 3.3: "`deficiency_round_count` is deliberately **not** reset: it is the loop counter that eventually forces the automatic denial, and an application may therefore bounce between `UNDER_REVIEW` and `DEFICIENT` at most three times."
    PRD 2.4: "The server holds a **logical clock** that starts at `2026-08-01T00:00:00Z` when the process starts and never advances on its own."

    Design: Difficulty/non_linear_state_machine/application_deficiency_loop_auto_denies_on_fourth_round
    """
    application = _application_under_review(
        api, licensee["id"], ca_jurisdiction["id"]
    )
    assert application["status"] == "UNDER_REVIEW"
    assert application["deficiency_round_count"] == 0

    round_one = _issue_deficiency(
        api,
        application["id"],
        ca_jurisdiction["id"],
        "Round 1: net worth statement unsigned.",
    )
    assert round_one["status"] == "DEFICIENT"
    assert round_one["deficiency_round_count"] == 1
    # 2026-08-01T00:00:00Z + 30 days.
    assert _instant(round_one["deficiency_deadline_at"]) == DEFICIENCY_DEADLINE

    _resubmit(api, application["id"])
    round_two = _issue_deficiency(
        api,
        application["id"],
        ca_jurisdiction["id"],
        "Round 2: delegate list incomplete.",
    )
    assert round_two["status"] == "DEFICIENT"
    assert round_two["deficiency_round_count"] == 2
    assert _instant(round_two["deficiency_deadline_at"]) == DEFICIENCY_DEADLINE

    _resubmit(api, application["id"])
    round_three = _issue_deficiency(
        api,
        application["id"],
        ca_jurisdiction["id"],
        "Round 3: AML program stale.",
    )
    assert round_three["status"] == "DEFICIENT"
    assert round_three["deficiency_round_count"] == 3
    assert _instant(round_three["deficiency_deadline_at"]) == DEFICIENCY_DEADLINE
    assert round_three["denial_reason"] is None

    fetched = get_success_data(
        api.get_application(application["id"], MANAGER_HEADERS)
    )
    assert fetched["status"] == "DEFICIENT"
    assert fetched["deficiency_round_count"] == 3


def test_fourth_deficiency_round_denies_the_application_instead_of_looping(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """The same review action becomes a denial once three rounds have been spent, and mints no licence.

    PRD 3.3: "But when `deficiency_round_count` already stands at exactly 3, the same action is a denial rather than a fourth round: the application moves `UNDER_REVIEW → DENIED`, `denial_reason` is recorded as `EXCESSIVE_DEFICIENCY_ROUNDS`, `decision_at` is stamped from the clock, and `deficiency_deadline_at` is cleared to null."
    PRD 3.3: "The two edges are siblings out of the same state and the round counter alone distinguishes them."
    PRD 3.3: "Approval stamps `decision_at` and mints a licence."
    PRD 2.3: "The licence register filters on `licensee_id`, `jurisdiction_id`, `application_id`, `license_status` and `reporting_status` — and the `application_id` filter is the only way to discover the licence that an approval minted, since approval returns the application rather than the new licence."

    Design: Difficulty/non_linear_state_machine/application_deficiency_loop_auto_denies_on_fourth_round
    """
    application = _application_under_review(
        api, licensee["id"], ca_jurisdiction["id"]
    )

    for round_number, note in (
        (1, "Round 1: net worth statement unsigned."),
        (2, "Round 2: delegate list incomplete."),
        (3, "Round 3: AML program stale."),
    ):
        deficient = _issue_deficiency(
            api, application["id"], ca_jurisdiction["id"], note
        )
        assert deficient["status"] == "DEFICIENT"
        assert deficient["deficiency_round_count"] == round_number
        _resubmit(api, application["id"])

    denied = _issue_deficiency(
        api,
        application["id"],
        ca_jurisdiction["id"],
        "Round 4: still non-responsive.",
    )
    assert denied["status"] == "DENIED"
    # Three loop rounds already spent, and the fourth action still increments.
    assert denied["deficiency_round_count"] == 4
    assert denied["denial_reason"] == "EXCESSIVE_DEFICIENCY_ROUNDS"
    assert denied["deficiency_deadline_at"] is None
    assert _instant(denied["decision_at"]) == "2026-08-01T00:00:00"

    fetched = get_success_data(
        api.get_application(application["id"], MANAGER_HEADERS)
    )
    assert fetched["status"] == "DENIED"
    assert fetched["deficiency_round_count"] == 4
    assert fetched["denial_reason"] == "EXCESSIVE_DEFICIENCY_ROUNDS"

    licences, meta = validate_paginated(
        api.list_state_licenses(
            MANAGER_HEADERS, params={"application_id": application["id"]}
        )
    )
    assert licences == []
    assert meta["total_count"] == 0


def test_resubmission_clears_the_deadline_repins_the_bond_and_keeps_the_counter(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """The loop's return edge clears the deadline and recomputes the bond while the counter survives.

    PRD 3.3: "On success the application moves `DEFICIENT → UNDER_REVIEW`, `deficiency_deadline_at` is cleared to null, and `required_bond_cents` is recomputed from the newly supplied projected volume."
    PRD 3.3: "`deficiency_round_count` is deliberately **not** reset: it is the loop counter that eventually forces the automatic denial, and an application may therefore bounce between `UNDER_REVIEW` and `DEFICIENT` at most three times."
    PRD 3.4: "A volume of at most one billion cents — that is, ten million dollars — is tier one at a tier bond of two and a half million cents; a volume above one billion cents but at most ten billion cents is tier two at ten million cents; a volume above ten billion cents is tier three at twenty-five million cents."
    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."

    Design: Difficulty/non_linear_state_machine/application_deficiency_loop_auto_denies_on_fourth_round
    """
    application = _application_under_review(
        api, licensee["id"], ca_jurisdiction["id"]
    )
    # Tier one on 250,000,000 gives 2,500,000; the CA base bond floor of
    # 5,000,000 is greater, and MONEY_TRANSMISSION leaves it unchanged.
    assert application["required_bond_cents"] == 5_000_000

    deficient = _issue_deficiency(
        api,
        application["id"],
        ca_jurisdiction["id"],
        "Round 1: net worth statement unsigned.",
    )
    assert deficient["status"] == "DEFICIENT"
    assert deficient["deficiency_round_count"] == 1

    resubmitted = _resubmit(
        api, application["id"], projected_annual_volume_cents=2_000_000_000
    )
    assert resubmitted["status"] == "UNDER_REVIEW"
    assert resubmitted["deficiency_deadline_at"] is None
    assert resubmitted["deficiency_round_count"] == 1
    # 2,000,000,000 is above one billion, so tier two of 10,000,000 now beats
    # the 5,000,000 base floor and stays under the 40,000,000 cap.
    assert resubmitted["required_bond_cents"] == 10_000_000

    second_round = _issue_deficiency(
        api,
        application["id"],
        ca_jurisdiction["id"],
        "Round 2: delegate list incomplete.",
    )
    assert second_round["status"] == "DEFICIENT"
    assert second_round["deficiency_round_count"] == 2
    assert _instant(second_round["deficiency_deadline_at"]) == DEFICIENCY_DEADLINE


# ---------------------------------------------------------------------------
# The two independent dimensions of a state licence
# ---------------------------------------------------------------------------


def test_late_call_report_moves_only_the_reporting_dimension(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A late 2026Q1 filing turns reporting_status DELINQUENT while license_status stays ACTIVE.

    PRD 3.5: "From the label the server derives `period_end`, at midnight UTC on the last day of the labelled period in the labelled year: the 31st of March for Q1, the 30th of June for Q2, the 30th of September for Q3, and the 31st of December for both Q4 and a full fiscal year."
    PRD 3.5: "`due_at` is then `period_end` plus forty-five days, again at midnight UTC."
    PRD 3.5: "The report's `status` follows a strictly ordered two-test rule: the report is `LATE` if the logical clock is strictly past `due_at`; otherwise it is `FILED_DEFICIENT` if `transaction_count` is exactly zero while `transmission_volume_cents` is greater than zero; otherwise it is `FILED`."
    PRD 3.5: "A `LATE` report moves `reporting_status` from `CURRENT` to `DELINQUENT`."
    PRD 3.5: "Any `reporting_status` other than `CURRENT` forces `expansion_gate` to `BLOCKED`."
    PRD 2.8: "A suspended licence still files call reports and its `reporting_status` still moves; a licence whose `reporting_status` is `DELINQUENT` is still authorised to transmit."

    Design: Difficulty/non_linear_state_machine/license_authorisation_and_reporting_dimensions_advance_independently
    """
    before = fx.get_license(api, active_license.license_id)
    assert before["license_status"] == "ACTIVE"
    assert before["reporting_status"] == "CURRENT"
    assert before["expansion_gate"] == "OPEN"

    report = fx.file_call_report(
        api, active_license.license_id, "2026Q1", 40_000_000, 900
    )
    # Q1 2026 ends 2026-03-31; plus 45 days is 2026-05-15, already past the
    # 2026-08-01 clock, so the filing is LATE.
    assert _instant(report["period_end"]) == "2026-03-31T00:00:00"
    assert _instant(report["due_at"]) == "2026-05-15T00:00:00"
    assert report["status"] == "LATE"

    licence = fx.get_license(api, active_license.license_id)
    assert licence["reporting_status"] == "DELINQUENT"
    assert licence["license_status"] == "ACTIVE"
    assert licence["bond_status"] == "POSTED"
    assert licence["expansion_gate"] == "BLOCKED"
    assert licence["annual_volume_cents"] == 40_000_000


def test_bond_cancellation_moves_only_the_authorisation_dimension(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A bond cancellation notice suspends the licence and leaves reporting_status DELINQUENT.

    PRD 3.4: "The licensee files the notice with a `bond_cancellation_effective_date`, which must be at least thirty days after the current logical clock; a shorter notice is rejected with `ERR_BOND_NOTICE_TOO_SHORT` (HTTP 422)."
    PRD 3.4: "On acceptance, `bond_status` becomes `CANCELLATION_NOTICED`, the effective date is stored, and the licence moves `ACTIVE → SUSPENDED`, triggering the licence-suspension cascade of §2.9 in full."
    PRD 2.8: "A `StateLicense` carries two status fields that move independently and must never be conflated."
    PRD 2.8: "`reporting_status` is the reporting-calendar dimension and takes the values `CURRENT`, `DELINQUENT` and `DEFICIENT_FILING`; it starts at `CURRENT` and has no terminal value."

    Design: Difficulty/non_linear_state_machine/license_authorisation_and_reporting_dimensions_advance_independently
    """
    late_report = fx.file_call_report(
        api, active_license.license_id, "2026Q1", 40_000_000, 900
    )
    assert late_report["status"] == "LATE"
    delinquent = fx.get_license(api, active_license.license_id)
    assert delinquent["license_status"] == "ACTIVE"
    assert delinquent["reporting_status"] == "DELINQUENT"

    # 2026-09-30 is 60 days after the 2026-08-01 clock, so the 30-day notice
    # period is satisfied.
    suspended = validate_success(
        api.file_bond_cancellation_notice(
            active_license.license_id,
            F.bond_cancellation_payload(BOND_CANCELLATION_DATE),
            MANAGER_HEADERS,
        )
    )
    assert suspended["license_status"] == "SUSPENDED"
    assert suspended["bond_status"] == "CANCELLATION_NOTICED"

    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "SUSPENDED"
    assert licence["reporting_status"] == "DELINQUENT"
    assert licence["bond_status"] == "CANCELLATION_NOTICED"
    assert licence["expansion_gate"] == "BLOCKED"
    assert _instant(licence["bond_cancellation_effective_date"]) == "2026-09-30T00:00:00"


def test_timely_later_filing_restores_reporting_status_on_a_suspended_licence(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A timely 2026Q2 filing returns reporting_status to CURRENT while license_status stays SUSPENDED.

    PRD 3.5: "Recovery from `DELINQUENT` back to `CURRENT` is stricter: the new report must be filed on or before the `due_at` of its own, later, period, and no other call report of the licence may still be `LATE` for a period label greater than the one being filed; when both hold, the new report is `FILED` and `reporting_status` returns to `CURRENT`."
    PRD 3.5: "The filing then drives the reporting dimension of the licence, entirely independently of its authorisation status — a `SUSPENDED` licence still files and still flips this dimension."
    PRD 3.5: "Regardless of status, every filing adds its `transmission_volume_cents` to the licence's `annual_volume_cents` and recomputes `bond_requirement_cents`, since the volume tier may have moved."
    PRD 2.8: "It is `OPEN` exactly when all five of the following hold: `license_status` is `ACTIVE`, `bond_status` is `POSTED`, `reporting_status` is `CURRENT`, `exam_findings_open` is false, and the owning licensee's `coverage_posture` is either `COMPLIANT` or `WATCH`."

    Design: Difficulty/non_linear_state_machine/license_authorisation_and_reporting_dimensions_advance_independently
    """
    fx.file_call_report(api, active_license.license_id, "2026Q1", 40_000_000, 900)
    validate_success(
        api.file_bond_cancellation_notice(
            active_license.license_id,
            F.bond_cancellation_payload(BOND_CANCELLATION_DATE),
            MANAGER_HEADERS,
        )
    )
    parked = fx.get_license(api, active_license.license_id)
    assert parked["license_status"] == "SUSPENDED"
    assert parked["reporting_status"] == "DELINQUENT"

    second_report = fx.file_call_report(
        api, active_license.license_id, "2026Q2", 60_000_000, 1_100
    )
    # Q2 2026 ends 2026-06-30; plus 45 days is 2026-08-14, still ahead of the
    # 2026-08-01 clock, and the transaction count is above zero.
    assert _instant(second_report["period_end"]) == "2026-06-30T00:00:00"
    assert _instant(second_report["due_at"]) == "2026-08-14T00:00:00"
    assert second_report["status"] == "FILED"

    licence = fx.get_license(api, active_license.license_id)
    assert licence["reporting_status"] == "CURRENT"
    assert licence["license_status"] == "SUSPENDED"
    assert licence["bond_status"] == "CANCELLATION_NOTICED"
    # 40,000,000 from 2026Q1 plus 60,000,000 from 2026Q2.
    assert licence["annual_volume_cents"] == 100_000_000
    # 100,000,000 is tier one at 2,500,000; with zero active delegates the CA
    # base floor of 5,000,000 still wins and the 40,000,000 cap does not bite.
    assert licence["bond_requirement_cents"] == 5_000_000
    # The authorisation dimension alone keeps the gate shut.
    assert licence["expansion_gate"] == "BLOCKED"

    reports, meta = validate_paginated(
        api.list_license_call_reports(active_license.license_id, MANAGER_HEADERS)
    )
    assert meta["total_count"] == 2
    assert [row["status"] for row in reports] == ["LATE", "FILED"]
