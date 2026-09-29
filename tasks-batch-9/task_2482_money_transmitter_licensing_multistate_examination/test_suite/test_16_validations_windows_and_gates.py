"""Temporal windows, conditional gates and the ladder that orders them.

Every deadline in the Money Transmitter Licensing API is measured against the
server's logical clock, and each one has an inclusive last instant: the response
window of an information request, the deficiency deadline of an application, the
twenty-day enforcement response window, the remediation deadline of a consent
order and the thirty-day forward notice a surety cancellation must give. The
tests below pin both sides of each of those boundaries, prove that a refused
write moves nothing at all, and check the two gates that guard a renewal and an
application submission from the reporting calendar and the control chain.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BOND_NOTICE_TOO_SHORT,
    ERR_CONTROL_CHAIN_BLOCKED,
    ERR_DEFICIENCY_DEADLINE_PASSED,
    ERR_ENFORCEMENT_RESPONSE_WINDOW_CLOSED,
    ERR_REMEDIATION_DEADLINE_PASSED,
    ERR_REMEDIATION_PLAN_REQUIRED,
    ERR_REPORTING_NOT_CURRENT,
    ERR_RESPONSE_INCOMPLETE,
    ERR_RESPONSE_WINDOW_CLOSED,
)
from test_helpers.test_users import MANAGER_HEADERS


def _instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to whole seconds for comparison."""
    return value.replace("Z", "").split(".")[0]


# ---------------------------------------------------------------------------
# Instance: closed_response_window_outranks_the_completeness_check
# ---------------------------------------------------------------------------

# California's response_window_days is 15, so a request opened at the seed clock
# of 2026-08-01 is due at 2026-08-16 inclusive.
REQUEST_DUE_AT = "2026-08-16T00:00:00"
ONE_DAY_PAST_DUE_AT = "2026-08-17T00:00:00Z"


def _exam_with_one_open_request(
    api: MoneyTransmitterApiClient, scenario: fx.Scenario
) -> tuple:
    """A CA-led examination in FIELDWORK holding one OPEN request for 3 items."""
    exam = fx.setup_exam_in_fieldwork(api, scenario.licensee_id, scenario.jurisdiction_id)
    request = fx.open_information_request(
        api, exam["id"], scenario.jurisdiction_id, requested_item_count=3
    )
    assert request["status"] == "OPEN"
    # 2026-08-01 plus California's fifteen-day window lands on 2026-08-16.
    assert _instant(request["due_at"]) == REQUEST_DUE_AT
    return exam, request


def test_a_late_and_short_response_reports_the_closed_window_not_the_shortfall(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """One day past due_at with one of three items, the temporal rule wins.

    PRD 2.7: "When several rules could reject the same request, the system evaluates them in a fixed order and returns the error of the first rule that fails."
    PRD 2.7: "10. **Temporal windows**, in this order: examination window conflict (`ERR_EXAM_WINDOW_CONFLICT`), delegate period overlap (`ERR_DELEGATE_PERIOD_OVERLAP`), certification window (`ERR_CERTIFICATION_WINDOW_CLOSED`), information-request response window (`ERR_RESPONSE_WINDOW_CLOSED`), deficiency deadline (`ERR_DEFICIENCY_DEADLINE_PASSED`), enforcement response window (`ERR_ENFORCEMENT_RESPONSE_WINDOW_CLOSED`), remediation deadline (`ERR_REMEDIATION_DEADLINE_PASSED`), bond cancellation notice period (`ERR_BOND_NOTICE_TOO_SHORT`)."
    PRD 2.7: "11. **Uniqueness and structural constraints**, in this order: duplicate live application (`ERR_DUPLICATE_LICENSE_APPLICATION`), duplicate `ein` (`ERR_DUPLICATE_EIN`), duplicate `state_code` (`ERR_DUPLICATE_STATE_CODE`), duplicate or mis-formed `period_label` (`ERR_DUPLICATE_CALL_REPORT`), incomplete information-request response (`ERR_RESPONSE_INCOMPLETE`), active delegates remaining at surrender (`ERR_ACTIVE_DELEGATES_REMAIN`), control-chain cycle or excessive depth (`ERR_CONTROL_CHAIN_CYCLE`), reporting status not current at renewal (`ERR_REPORTING_NOT_CURRENT`)."
    PRD 3.8: "The row starts in `OPEN` — the other statuses being `RESPONDED`, `OVERDUE` and the terminal `ACCEPTED` — with `reopen_count` and `submitted_item_count` at zero and `responded_at` null."
    PRD 3.8: "Its `due_at` is the current logical clock plus the requesting jurisdiction's `response_window_days`, expressed as that many exact twenty-four-hour periods."
    PRD 3.8: "Because `open_request_count` is by definition the number of the exam's requests sitting in `OPEN`, `OVERDUE` or `RESPONDED`, opening a request raises it by one."
    PRD 3.8: "The exam must be in `FIELDWORK`, or the response is rejected with `ERR_EXAM_INVALID_STATE`; the request must be in `OPEN` or `OVERDUE`, or the response is rejected with `ERR_INFO_REQUEST_INVALID_STATE`; the logical clock must be on or before `due_at`, the boundary being inclusive, or the response is rejected with `ERR_RESPONSE_WINDOW_CLOSED`; and `submitted_item_count` must be at least `requested_item_count`, or the response is rejected with `ERR_RESPONSE_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/closed_response_window_outranks_the_completeness_check
    """
    exam, request = _exam_with_one_open_request(api, active_license)
    fx.set_clock(api, ONE_DAY_PAST_DUE_AT)

    # One item against three requested breaches the step-11 completeness rule and
    # the clock breaches the step-10 window rule at the same time.
    response = api.respond_to_information_request(
        request["id"], F.information_response_payload(1), MANAGER_HEADERS
    )

    error = validate_error(response, ERR_RESPONSE_WINDOW_CLOSED, 409)
    assert error["error_id"] != ERR_RESPONSE_INCOMPLETE

    row = validate_success(api.get_information_request(request["id"], MANAGER_HEADERS))
    assert row["status"] == "OPEN"
    assert row["submitted_item_count"] == 0
    assert row["responded_at"] is None
    assert row["requested_item_count"] == 3
    assert _instant(row["due_at"]) == REQUEST_DUE_AT
    assert row["version"] == request["version"]

    exam_row = validate_success(api.get_exam(exam["id"], MANAGER_HEADERS))
    # The single opened request is still the only open matter of the exam.
    assert exam_row["open_request_count"] == 1


def test_at_the_inclusive_due_at_only_the_completeness_rule_can_still_fail(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """On due_at itself the window is open: three items land, one does not.

    PRD 2.4: "Every deadline, window and `*_at` stamp in the specification reads that clock — response windows, certification windows, deficiency deadlines, bond-cancellation notice periods, call-report lateness and enforcement response windows are all evaluated against it."
    PRD 3.8: "The row starts in `OPEN` — the other statuses being `RESPONDED`, `OVERDUE` and the terminal `ACCEPTED` — with `reopen_count` and `submitted_item_count` at zero and `responded_at` null."
    PRD 3.8: "The exam must be in `FIELDWORK`, or the response is rejected with `ERR_EXAM_INVALID_STATE`; the request must be in `OPEN` or `OVERDUE`, or the response is rejected with `ERR_INFO_REQUEST_INVALID_STATE`; the logical clock must be on or before `due_at`, the boundary being inclusive, or the response is rejected with `ERR_RESPONSE_WINDOW_CLOSED`; and `submitted_item_count` must be at least `requested_item_count`, or the response is rejected with `ERR_RESPONSE_INCOMPLETE` (HTTP 422)."
    PRD 3.8: "A partial delivery is not a response."
    PRD 3.8: "On success the request moves to `RESPONDED`, `submitted_item_count` is stored and `responded_at` is stamped."

    Design: Corner/validations/closed_response_window_outranks_the_completeness_check
    """
    exam, request = _exam_with_one_open_request(api, active_license)
    # The last instant the inclusive window admits, one day earlier than the
    # rejection above.
    fx.set_clock(api, REQUEST_DUE_AT + "Z")

    short = api.respond_to_information_request(
        request["id"], F.information_response_payload(1), MANAGER_HEADERS
    )
    error = validate_error(short, ERR_RESPONSE_INCOMPLETE, 422)
    assert error["error_id"] != ERR_RESPONSE_WINDOW_CLOSED

    held = validate_success(api.get_information_request(request["id"], MANAGER_HEADERS))
    assert held["status"] == "OPEN"
    assert held["submitted_item_count"] == 0
    assert held["responded_at"] is None
    assert held["version"] == request["version"]

    # A complete delivery at the very same instant is admitted, which is what
    # makes the inclusive boundary observable.
    accepted = validate_success(
        api.respond_to_information_request(
            request["id"], F.information_response_payload(3), MANAGER_HEADERS
        )
    )
    assert accepted["status"] == "RESPONDED"
    assert accepted["submitted_item_count"] == 3
    assert _instant(accepted["responded_at"]) == REQUEST_DUE_AT


# ---------------------------------------------------------------------------
# Instance: resubmit_after_the_deficiency_deadline_rejects
# ---------------------------------------------------------------------------

# ISSUE_DEFICIENCY at the seed clock of 2026-08-01 plus thirty days.
DEFICIENCY_DEADLINE = "2026-08-31T00:00:00"
ONE_DAY_PAST_DEFICIENCY_DEADLINE = "2026-09-01T00:00:00Z"


def _deficient_application(
    api: MoneyTransmitterApiClient, licensee_id: str, jurisdiction_id: str
) -> dict:
    """Drive one application to DEFICIENT on its first round at the seed clock."""
    application = fx.create_application(api, licensee_id, jurisdiction_id)
    fx.submit_application(api, application["id"])
    fx.review_application(api, application["id"], jurisdiction_id, "START_REVIEW")
    deficient = fx.review_application(
        api,
        application["id"],
        jurisdiction_id,
        "ISSUE_DEFICIENCY",
        note="Missing AML programme.",
    )
    assert deficient["status"] == "DEFICIENT"
    assert deficient["deficiency_round_count"] == 1
    # 2026-08-01 plus thirty days is 2026-08-31.
    assert _instant(deficient["deficiency_deadline_at"]) == DEFICIENCY_DEADLINE
    return deficient


def test_resubmitting_one_day_after_the_deficiency_deadline_is_refused(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """A day past the deadline the deficient application is not revived.

    PRD 3.3: "While `deficiency_round_count` is below 3, the application moves `UNDER_REVIEW → DEFICIENT` and `deficiency_deadline_at` is set to the current logical clock plus thirty days."
    PRD 3.3: "The resubmission must arrive on or before `deficiency_deadline_at` — the boundary is inclusive, and a resubmission after the deadline is rejected with `ERR_DEFICIENCY_DEADLINE_PASSED`."
    PRD 3.3: "`deficiency_round_count` is deliberately **not** reset: it is the loop counter that eventually forces the automatic denial, and an application may therefore bounce between `UNDER_REVIEW` and `DEFICIENT` at most three times."

    Design: Corner/validations/resubmit_after_the_deficiency_deadline_rejects
    """
    deficient = _deficient_application(api, licensee["id"], ca_jurisdiction["id"])
    fx.set_clock(api, ONE_DAY_PAST_DEFICIENCY_DEADLINE)

    response = api.resubmit_application(
        deficient["id"],
        F.resubmit_payload(500_000_000, remediation_note="AML programme attached."),
        MANAGER_HEADERS,
    )

    validate_error(response, ERR_DEFICIENCY_DEADLINE_PASSED, 409)

    row = validate_success(api.get_application(deficient["id"], MANAGER_HEADERS))
    assert row["status"] == "DEFICIENT"
    assert row["deficiency_round_count"] == 1
    assert _instant(row["deficiency_deadline_at"]) == DEFICIENCY_DEADLINE
    assert row["version"] == deficient["version"]


def test_resubmitting_on_the_deficiency_deadline_itself_reopens_the_review(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """The boundary is inclusive, so the deadline instant is still admissible.

    PRD 3.3: "A `LicensingManager` resubmits a `DEFICIENT` application with a fresh `projected_annual_volume_cents` and an optional `remediation_note`."
    PRD 3.3: "The resubmission must arrive on or before `deficiency_deadline_at` — the boundary is inclusive, and a resubmission after the deadline is rejected with `ERR_DEFICIENCY_DEADLINE_PASSED`."
    PRD 3.3: "On success the application moves `DEFICIENT → UNDER_REVIEW`, `deficiency_deadline_at` is cleared to null, and `required_bond_cents` is recomputed from the newly supplied projected volume."

    Design: Corner/validations/resubmit_after_the_deficiency_deadline_rejects
    """
    deficient = _deficient_application(api, licensee["id"], ca_jurisdiction["id"])
    # Exactly the deadline instant, one day earlier than the rejection above.
    fx.set_clock(api, DEFICIENCY_DEADLINE + "Z")

    row = validate_success(
        api.resubmit_application(
            deficient["id"],
            F.resubmit_payload(500_000_000, remediation_note="AML programme attached."),
            MANAGER_HEADERS,
        )
    )

    assert row["status"] == "UNDER_REVIEW"
    assert row["deficiency_deadline_at"] is None
    # The loop counter survives the resubmission it admits.
    assert row["deficiency_round_count"] == 1


# ---------------------------------------------------------------------------
# Instance: enforcement_response_after_twenty_days_rejects
# ---------------------------------------------------------------------------

# issued_at at the seed clock of 2026-08-01 plus twenty days.
ENFORCEMENT_WINDOW_LAST_INSTANT = "2026-08-21T00:00:00"
ONE_DAY_PAST_ENFORCEMENT_WINDOW = "2026-08-22T00:00:00Z"


def test_answering_an_enforcement_action_after_twenty_days_is_refused(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A day past the window the consent order never settles anything.

    PRD 3.9: "The action starts in `ISSUED` and `issued_at` is stamped from the logical clock, which starts a twenty-day response window."
    PRD 3.9: "Either branch requires the action to be in `ISSUED` — a response to anything else is rejected with `ERR_ENFORCEMENT_INVALID_STATE` — and requires the logical clock to be on or before `issued_at` plus twenty days, a late response being rejected with `ERR_ENFORCEMENT_RESPONSE_WINDOW_CLOSED`."
    PRD 3.9: "Settling also costs the licence its authorisation: the target `StateLicense` moves `ACTIVE → SUSPENDED`, `expansion_gate` becomes `BLOCKED`, the licensee's `active_license_count` drops by one, every `ACTIVE` `DelegateAuthorization` of the licence moves to `SUSPENDED` with `active_delegate_count` reset to zero and `bond_requirement_cents` recomputed with no delegates, and each affected `Delegate` has `authorized_state_count` reduced by one and moves to `SUSPENDED` when that count reaches zero."

    Design: Corner/validations/enforcement_response_after_twenty_days_rejects
    """
    action = fx.issue_enforcement_action(
        api,
        active_license.license_id,
        active_license.jurisdiction_id,
        basis="DELINQUENT_REPORTING",
        penalty_cents=2_500_000,
    )
    assert action["status"] == "ISSUED"
    assert _instant(action["issued_at"]) == "2026-08-01T00:00:00"
    licence_before = fx.get_license(api, active_license.license_id)
    fx.set_clock(api, ONE_DAY_PAST_ENFORCEMENT_WINDOW)

    response = api.respond_to_enforcement_action(
        action["id"],
        F.enforcement_response_payload(
            "CONSENT_ORDER",
            remediation_plan_narrative="Backfill all delinquent call reports.",
        ),
        MANAGER_HEADERS,
    )

    validate_error(response, ERR_ENFORCEMENT_RESPONSE_WINDOW_CLOSED, 409)

    row = validate_success(api.get_enforcement_action(action["id"], MANAGER_HEADERS))
    assert row["status"] == "ISSUED"
    assert row["response_at"] is None
    assert row["remediation_plan_narrative"] is None
    assert row["version"] == action["version"]

    # The settlement's suspension cascade never ran.
    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "ACTIVE"
    assert licence["expansion_gate"] == "OPEN"
    assert licence["version"] == licence_before["version"]
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1


def test_answering_on_the_twentieth_day_still_settles_and_suspends(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """issued_at plus exactly twenty days is inside the window.

    PRD 3.9: "Either branch requires the action to be in `ISSUED` — a response to anything else is rejected with `ERR_ENFORCEMENT_INVALID_STATE` — and requires the logical clock to be on or before `issued_at` plus twenty days, a late response being rejected with `ERR_ENFORCEMENT_RESPONSE_WINDOW_CLOSED`."
    PRD 3.9: "A `response` of `CONSENT_ORDER` settles: the action moves `ISSUED → CONSENT_ORDER`, `response_at` is stamped, and the supplied `remediation_plan_narrative` is stored."
    PRD 3.9: "Settling also costs the licence its authorisation: the target `StateLicense` moves `ACTIVE → SUSPENDED`, `expansion_gate` becomes `BLOCKED`, the licensee's `active_license_count` drops by one, every `ACTIVE` `DelegateAuthorization` of the licence moves to `SUSPENDED` with `active_delegate_count` reset to zero and `bond_requirement_cents` recomputed with no delegates, and each affected `Delegate` has `authorized_state_count` reduced by one and moves to `SUSPENDED` when that count reaches zero."

    Design: Corner/validations/enforcement_response_after_twenty_days_rejects
    """
    action = fx.issue_enforcement_action(
        api,
        active_license.license_id,
        active_license.jurisdiction_id,
        basis="DELINQUENT_REPORTING",
        penalty_cents=2_500_000,
    )
    # 2026-08-01 plus twenty days is 2026-08-21, the last admissible instant.
    fx.set_clock(api, ENFORCEMENT_WINDOW_LAST_INSTANT + "Z")

    row = validate_success(
        api.respond_to_enforcement_action(
            action["id"],
            F.enforcement_response_payload(
                "CONSENT_ORDER",
                remediation_plan_narrative="Backfill all delinquent call reports.",
            ),
            MANAGER_HEADERS,
        )
    )

    assert row["status"] == "CONSENT_ORDER"
    assert _instant(row["response_at"]) == ENFORCEMENT_WINDOW_LAST_INSTANT
    assert row["remediation_plan_narrative"] == "Backfill all delinquent call reports."

    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "SUSPENDED"
    assert licence["expansion_gate"] == "BLOCKED"
    # The one authorised licence of the licensee has left the active count.
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 0


# ---------------------------------------------------------------------------
# Instance: remediation_resolution_after_the_deadline_rejects
# ---------------------------------------------------------------------------

REMEDIATION_DEADLINE = "2026-08-10T00:00:00"
ONE_DAY_PAST_REMEDIATION_DEADLINE = "2026-08-11T00:00:00Z"


def _consent_order_under_a_short_deadline(
    api: MoneyTransmitterApiClient, scenario: fx.Scenario
) -> dict:
    """An action answered with a consent order whose remediation runs to 10 Aug."""
    action = fx.issue_enforcement_action(
        api,
        scenario.license_id,
        scenario.jurisdiction_id,
        basis="PERMISSIBLE_INVESTMENT_SHORTFALL",
        penalty_cents=1_500_000,
        remediation_deadline_at=REMEDIATION_DEADLINE + "Z",
    )
    settled = fx.respond_to_enforcement_action(
        api,
        action["id"],
        "CONSENT_ORDER",
        remediation_plan_narrative="Top up permissible investments within 7 days.",
    )
    assert settled["status"] == "CONSENT_ORDER"
    assert _instant(settled["remediation_deadline_at"]) == REMEDIATION_DEADLINE
    return settled


def test_resolving_a_consent_order_after_its_remediation_deadline_is_refused(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A day late the licence stays suspended and the action stays open.

    PRD 3.9: "An `outcome` of `RESOLVED` is admissible from either `CONSENT_ORDER` or `CONTESTED`; out of `CONSENT_ORDER` it additionally requires the logical clock to be on or before `remediation_deadline_at`, and a late resolution is rejected with `ERR_REMEDIATION_DEADLINE_PASSED`."
    PRD 3.9: "Out of `CONSENT_ORDER` with `remediation_accepted` true, the action moves to the terminal `RESOLVED`, `resolved_at` is stamped, `remediation_accepted` is recorded as true, and the compensating licence transition runs: the `SUSPENDED` licence returns to `ACTIVE` — which requires its `bond_status` still to be `POSTED` — the licensee's `active_license_count` rises by one, `exam_findings_open` is cleared to false, and `expansion_gate` is re-derived, becoming `OPEN` when the licensee's `coverage_posture` is `COMPLIANT` or `WATCH` and `exam_findings_open` is false."

    Design: Corner/validations/remediation_resolution_after_the_deadline_rejects
    """
    settled = _consent_order_under_a_short_deadline(api, active_license)
    fx.set_clock(api, ONE_DAY_PAST_REMEDIATION_DEADLINE)

    response = api.resolve_enforcement_action(
        settled["id"],
        F.enforcement_resolution_payload("RESOLVED", remediation_accepted=True),
        active_license.regulator_headers,
    )

    validate_error(response, ERR_REMEDIATION_DEADLINE_PASSED, 409)

    row = validate_success(api.get_enforcement_action(settled["id"], MANAGER_HEADERS))
    assert row["status"] == "CONSENT_ORDER"
    assert row["resolved_at"] is None
    assert row["version"] == settled["version"]

    # The compensating licence transition never ran.
    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "SUSPENDED"
    assert licence["expansion_gate"] == "BLOCKED"
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 0


def test_resolving_a_consent_order_on_its_remediation_deadline_restores_the_licence(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The deadline instant itself still admits the accepted remediation.

    PRD 3.9: "An `outcome` of `RESOLVED` is admissible from either `CONSENT_ORDER` or `CONTESTED`; out of `CONSENT_ORDER` it additionally requires the logical clock to be on or before `remediation_deadline_at`, and a late resolution is rejected with `ERR_REMEDIATION_DEADLINE_PASSED`."
    PRD 3.9: "Out of `CONSENT_ORDER` with `remediation_accepted` true, the action moves to the terminal `RESOLVED`, `resolved_at` is stamped, `remediation_accepted` is recorded as true, and the compensating licence transition runs: the `SUSPENDED` licence returns to `ACTIVE` — which requires its `bond_status` still to be `POSTED` — the licensee's `active_license_count` rises by one, `exam_findings_open` is cleared to false, and `expansion_gate` is re-derived, becoming `OPEN` when the licensee's `coverage_posture` is `COMPLIANT` or `WATCH` and `exam_findings_open` is false."

    Design: Corner/validations/remediation_resolution_after_the_deadline_rejects
    """
    settled = _consent_order_under_a_short_deadline(api, active_license)
    # Exactly the remediation deadline, one day earlier than the rejection above.
    fx.set_clock(api, REMEDIATION_DEADLINE + "Z")

    row = validate_success(
        api.resolve_enforcement_action(
            settled["id"],
            F.enforcement_resolution_payload("RESOLVED", remediation_accepted=True),
            active_license.regulator_headers,
        )
    )

    assert row["status"] == "RESOLVED"
    assert _instant(row["resolved_at"]) == REMEDIATION_DEADLINE
    assert row["remediation_accepted"] is True

    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "ACTIVE"
    assert licence["bond_status"] == "POSTED"
    assert licence["exam_findings_open"] is False
    assert licence["expansion_gate"] == "OPEN"
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1


# ---------------------------------------------------------------------------
# Instance: bond_cancellation_notice_shorter_than_thirty_days_rejects
# ---------------------------------------------------------------------------

# Measured forward from the seed clock of 2026-08-01.
NOTICE_TWENTY_NINE_DAYS = "2026-08-30T00:00:00Z"
NOTICE_THIRTY_DAYS = "2026-08-31T00:00:00"
NOTICE_NINETEEN_DAYS = "2026-08-20T00:00:00Z"


def test_a_cancellation_notice_of_fewer_than_thirty_days_leaves_the_licence_alone(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Twenty-nine days of notice is refused and suspends nothing.

    PRD 2.4: "Day arithmetic on the clock adds exact multiples of twenty-four hours, and all instants are millisecond-exact ISO 8601 UTC."
    PRD 3.4: "The licensee files the notice with a `bond_cancellation_effective_date`, which must be at least thirty days after the current logical clock; a shorter notice is rejected with `ERR_BOND_NOTICE_TOO_SHORT` (HTTP 422)."
    PRD 3.4: "On acceptance, `bond_status` becomes `CANCELLATION_NOTICED`, the effective date is stored, and the licence moves `ACTIVE → SUSPENDED`, triggering the licence-suspension cascade of §2.9 in full."

    Design: Corner/validations/bond_cancellation_notice_shorter_than_thirty_days_rejects
    """
    before = fx.get_license(api, active_license.license_id)
    assert before["license_status"] == "ACTIVE"
    assert before["bond_status"] == "POSTED"

    # One day short of the statutory notice period: 2026-08-01 plus 29 days.
    near_miss = api.file_bond_cancellation_notice(
        active_license.license_id,
        F.bond_cancellation_payload(NOTICE_TWENTY_NINE_DAYS),
        MANAGER_HEADERS,
    )
    validate_error(near_miss, ERR_BOND_NOTICE_TOO_SHORT, 422)

    # And a notice only nineteen days out fails on the same rule.
    far_miss = api.file_bond_cancellation_notice(
        active_license.license_id,
        F.bond_cancellation_payload(NOTICE_NINETEEN_DAYS),
        MANAGER_HEADERS,
    )
    validate_error(far_miss, ERR_BOND_NOTICE_TOO_SHORT, 422)

    row = fx.get_license(api, active_license.license_id)
    assert row["license_status"] == "ACTIVE"
    assert row["bond_status"] == "POSTED"
    assert row["expansion_gate"] == "OPEN"
    assert row["bond_cancellation_effective_date"] is None
    assert row["version"] == before["version"]
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1


def test_a_cancellation_notice_of_exactly_thirty_days_suspends_the_licence(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Thirty days is "at least thirty", so the notice is admissible.

    PRD 3.4: "The licensee files the notice with a `bond_cancellation_effective_date`, which must be at least thirty days after the current logical clock; a shorter notice is rejected with `ERR_BOND_NOTICE_TOO_SHORT` (HTTP 422)."
    PRD 3.4: "The notice is admissible only while the licence is `ACTIVE` with `bond_status` `POSTED`."
    PRD 3.4: "On acceptance, `bond_status` becomes `CANCELLATION_NOTICED`, the effective date is stored, and the licence moves `ACTIVE → SUSPENDED`, triggering the licence-suspension cascade of §2.9 in full."

    Design: Corner/validations/bond_cancellation_notice_shorter_than_thirty_days_rejects
    """
    # 2026-08-01 plus exactly thirty days is 2026-08-31.
    assert C.iso_add_days(C.SEED_CLOCK, C.BOND_NOTICE_MIN_DAYS) == NOTICE_THIRTY_DAYS + "Z"

    row = validate_success(
        api.file_bond_cancellation_notice(
            active_license.license_id,
            F.bond_cancellation_payload(NOTICE_THIRTY_DAYS + "Z"),
            MANAGER_HEADERS,
        )
    )

    assert row["bond_status"] == "CANCELLATION_NOTICED"
    assert _instant(row["bond_cancellation_effective_date"]) == NOTICE_THIRTY_DAYS
    assert row["license_status"] == "SUSPENDED"
    assert row["expansion_gate"] == "BLOCKED"
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 0


# ---------------------------------------------------------------------------
# Instance: consent_order_without_a_plan_rejects_with_plan_required
# ---------------------------------------------------------------------------


def test_a_consent_order_with_no_remediation_plan_is_refused(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The settlement branch cannot be taken without the narrative.

    PRD 3.9: "A `response` of `CONSENT_ORDER` settles: the action moves `ISSUED → CONSENT_ORDER`, `response_at` is stamped, and the supplied `remediation_plan_narrative` is stored."
    PRD 3.9: "That narrative is mandatory on this branch — a consent order response with the field absent or empty is rejected with `ERR_REMEDIATION_PLAN_REQUIRED` (HTTP 422)."
    PRD 3.9: "Settling also costs the licence its authorisation: the target `StateLicense` moves `ACTIVE → SUSPENDED`, `expansion_gate` becomes `BLOCKED`, the licensee's `active_license_count` drops by one, every `ACTIVE` `DelegateAuthorization` of the licence moves to `SUSPENDED` with `active_delegate_count` reset to zero and `bond_requirement_cents` recomputed with no delegates, and each affected `Delegate` has `authorized_state_count` reduced by one and moves to `SUSPENDED` when that count reaches zero."

    Design: Corner/validations/consent_order_without_a_plan_rejects_with_plan_required
    """
    action = fx.issue_enforcement_action(
        api,
        active_license.license_id,
        active_license.jurisdiction_id,
        basis="DELINQUENT_REPORTING",
        penalty_cents=2_500_000,
    )
    licence_before = fx.get_license(api, active_license.license_id)

    # Passing Ellipsis removes the key from the body entirely.
    response = api.respond_to_enforcement_action(
        action["id"],
        F.enforcement_response_payload("CONSENT_ORDER", remediation_plan_narrative=...),
        MANAGER_HEADERS,
    )

    validate_error(response, ERR_REMEDIATION_PLAN_REQUIRED, 422)

    row = validate_success(api.get_enforcement_action(action["id"], MANAGER_HEADERS))
    assert row["status"] == "ISSUED"
    assert row["response_at"] is None
    assert row["remediation_plan_narrative"] is None
    assert row["version"] == action["version"]

    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "ACTIVE"
    assert licence["expansion_gate"] == "OPEN"
    assert licence["version"] == licence_before["version"]
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1


def test_an_empty_plan_is_refused_while_the_contest_branch_needs_no_plan_at_all(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """An empty narrative fails the same rule the contest branch never meets.

    PRD 3.9: "That narrative is mandatory on this branch — a consent order response with the field absent or empty is rejected with `ERR_REMEDIATION_PLAN_REQUIRED` (HTTP 422)."
    PRD 3.9: "A `response` of `CONTEST` litigates instead: the action moves `ISSUED → CONTESTED` and `response_at` is stamped, and that is the entire effect."
    PRD 3.9: "The licence is **not** suspended, no delegate authorization is touched, `expansion_gate` is unchanged, `active_license_count` is unchanged, and the licence's `version` is not bumped."

    Design: Corner/validations/consent_order_without_a_plan_rejects_with_plan_required
    """
    action = fx.issue_enforcement_action(
        api,
        active_license.license_id,
        active_license.jurisdiction_id,
        basis="DELINQUENT_REPORTING",
        penalty_cents=2_500_000,
    )
    licence_before = fx.get_license(api, active_license.license_id)

    empty = api.respond_to_enforcement_action(
        action["id"],
        F.enforcement_response_payload("CONSENT_ORDER", remediation_plan_narrative=""),
        MANAGER_HEADERS,
    )
    validate_error(empty, ERR_REMEDIATION_PLAN_REQUIRED, 422)

    held = validate_success(api.get_enforcement_action(action["id"], MANAGER_HEADERS))
    assert held["status"] == "ISSUED"
    assert held["response_at"] is None
    assert held["version"] == action["version"]

    # The same body without a narrative on the litigating branch is admitted:
    # the field is conditionally required, not required outright.
    contested = validate_success(
        api.respond_to_enforcement_action(
            action["id"], F.enforcement_response_payload("CONTEST"), MANAGER_HEADERS
        )
    )
    assert contested["status"] == "CONTESTED"
    assert contested["remediation_plan_narrative"] is None

    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "ACTIVE"
    assert licence["expansion_gate"] == "OPEN"
    assert licence["version"] == licence_before["version"]
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1


# ---------------------------------------------------------------------------
# Instance: renewal_while_reporting_is_delinquent_rejects
# ---------------------------------------------------------------------------

# California's renewal_fee_cents is 500000 and the licence has no active
# delegate, so the subtotal is 500000 + 0 * 25000 = 500000; that subtotal
# exceeds 250000, so the tier rate is 200 bps; the assessment is
# round-half-up(500000 * 200 / 10000) = 10000; the total is 510000.
CA_RENEWAL_TOTAL_CENTS = 510_000


def _license_delinquent_on_a_late_first_quarter(
    api: MoneyTransmitterApiClient, scenario: fx.Scenario
) -> dict:
    """File 2026Q1 well past its due date so the reporting dimension flips."""
    report = fx.file_call_report(api, scenario.license_id, "2026Q1", 20_000_000, 400)
    # 2026Q1 ends 2026-03-31 and is due forty-five days later, on 2026-05-15;
    # the seed clock of 2026-08-01 is strictly past that.
    assert _instant(report["period_end"]) == "2026-03-31T00:00:00"
    assert _instant(report["due_at"]) == "2026-05-15T00:00:00"
    assert report["status"] == "LATE"
    return report


def test_a_delinquent_reporting_dimension_refuses_an_exactly_correct_renewal_payment(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The licence is still ACTIVE, yet the reporting gate blocks the renewal.

    PRD 2.8: "A suspended licence still files call reports and its `reporting_status` still moves; a licence whose `reporting_status` is `DELINQUENT` is still authorised to transmit."
    PRD 3.5: "`due_at` is then `period_end` plus forty-five days, again at midnight UTC."
    PRD 3.5: "The report's `status` follows a strictly ordered two-test rule: the report is `LATE` if the logical clock is strictly past `due_at`; otherwise it is `FILED_DEFICIENT` if `transaction_count` is exactly zero while `transmission_volume_cents` is greater than zero; otherwise it is `FILED`."
    PRD 3.5: "A `LATE` report moves `reporting_status` from `CURRENT` to `DELINQUENT`."
    PRD 3.5: "Any `reporting_status` other than `CURRENT` forces `expansion_gate` to `BLOCKED`."
    PRD 3.5: "Three gates guard it: the licensee's `control_chain_status` must not be `BLOCKED` (`ERR_CONTROL_CHAIN_BLOCKED`); the licence's `reporting_status` must be exactly `CURRENT`, so a `DELINQUENT` or `DEFICIENT_FILING` licence cannot renew (`ERR_REPORTING_NOT_CURRENT`); and the licensee's `reported_tangible_net_worth_cents` must be at least the jurisdiction's `min_net_worth_cents` (`ERR_NET_WORTH_INSUFFICIENT`)."

    Design: Corner/validations/renewal_while_reporting_is_delinquent_rejects
    """
    _license_delinquent_on_a_late_first_quarter(api, active_license)

    before = fx.get_license(api, active_license.license_id)
    assert before["reporting_status"] == "DELINQUENT"
    assert before["license_status"] == "ACTIVE"
    assert before["expansion_gate"] == "BLOCKED"
    assert before["renewal_status"] == "NOT_RENEWED"

    response = api.renew_license(
        active_license.license_id,
        F.renewal_payload(2027, CA_RENEWAL_TOTAL_CENTS),
        MANAGER_HEADERS,
    )

    validate_error(response, ERR_REPORTING_NOT_CURRENT, 409)

    row = fx.get_license(api, active_license.license_id)
    assert row["renewal_status"] == "NOT_RENEWED"
    assert row["reporting_status"] == "DELINQUENT"
    assert row["license_status"] == "ACTIVE"
    assert row["version"] == before["version"]


def test_recovering_the_reporting_dimension_lets_the_same_payment_renew(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """With reporting back at CURRENT the identical fee is accepted.

    PRD 3.5: "Recovery from `DELINQUENT` back to `CURRENT` is stricter: the new report must be filed on or before the `due_at` of its own, later, period, and no other call report of the licence may still be `LATE` for a period label greater than the one being filed; when both hold, the new report is `FILED` and `reporting_status` returns to `CURRENT`."
    PRD 3.5: "First the subtotal: the jurisdiction's `renewal_fee_cents` plus the licence's current `active_delegate_count` multiplied by twenty-five thousand cents — two hundred and fifty dollars per active delegate."
    PRD 3.5: "Second, a tier rate is selected **from that pre-assessment subtotal and never from the final total**: 500 basis points when the subtotal is at most one hundred thousand cents, 350 basis points when the subtotal is above one hundred thousand cents but at most two hundred and fifty thousand cents, and 200 basis points when the subtotal exceeds two hundred and fifty thousand cents."
    PRD 3.5: "Third, the assessment is the subtotal multiplied by the tier rate divided by 10000, rounded half up to whole cents."
    PRD 3.5: "Fourth, the total is the subtotal plus that assessment."
    PRD 3.5: "On a match, `renewal_status` moves from `NOT_RENEWED` to `RENEWED`, `renewal_year` records the year renewed, `renewal_total_fee_cents` records the computed total, and the licence's `version` is bumped."

    Design: Corner/validations/renewal_while_reporting_is_delinquent_rejects
    """
    _license_delinquent_on_a_late_first_quarter(api, active_license)

    # 2026Q2 ends 2026-06-30 and is due 2026-08-14, so a filing at the seed
    # clock of 2026-08-01 is on time, and no later period is still LATE.
    recovery = fx.file_call_report(api, active_license.license_id, "2026Q2", 20_000_000, 400)
    assert _instant(recovery["due_at"]) == "2026-08-14T00:00:00"
    assert recovery["status"] == "FILED"

    recovered = fx.get_license(api, active_license.license_id)
    assert recovered["reporting_status"] == "CURRENT"
    assert recovered["active_delegate_count"] == 0

    row = validate_success(
        api.renew_license(
            active_license.license_id,
            F.renewal_payload(2027, CA_RENEWAL_TOTAL_CENTS),
            MANAGER_HEADERS,
        )
    )

    assert row["renewal_status"] == "RENEWED"
    assert row["renewal_year"] == 2027
    # 500000 subtotal at 200 bps assesses 10000, for a total of 510000 cents.
    assert row["renewal_total_fee_cents"] == CA_RENEWAL_TOTAL_CENTS


# ---------------------------------------------------------------------------
# Instance: blocked_control_chain_stops_a_later_application_submit
# ---------------------------------------------------------------------------


def _licensee_with_a_live_application_and_one_control_holder(
    api: MoneyTransmitterApiClient, licensee_id: str, ca_id: str
) -> dict:
    """A submitted CA filing puts CA in scope, then a 5000 bps holder is added."""
    ca_application = fx.create_application(api, licensee_id, ca_id)
    submitted = fx.submit_application(api, ca_application["id"])
    assert submitted["status"] == "SUBMITTED"
    holder = fx.create_control_person(
        api,
        licensee_id,
        full_name="Dana Whitfield",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=5000,
    )
    # 5000 attributed basis points clears the 2500 control threshold, so the
    # holder is a control person and owes a background check.
    assert holder["attributed_ownership_bps"] == 5000
    assert holder["control_determination"] == "CONTROL"
    assert holder["background_check_status"] == "PENDING"
    return holder


def test_a_blocked_control_chain_stops_a_submit_in_an_unrelated_state(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """One adverse holder blocks the chain, and the chain blocks a Texas filing.

    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "`background_check_status` is set to `PENDING` for a control person and to `NOT_REQUIRED` otherwise; its full value set is `NOT_REQUIRED`, `PENDING`, `CLEARED` and `ADVERSE`, and it defaults to `NOT_REQUIRED`."
    PRD 3.2: "An `outcome` of `ADVERSE` accompanied by `disqualifying_finding` true sets `background_check_status` to `ADVERSE`, sets the row's `disqualifying_finding` to true, and drives the holder from `PROPOSED` straight to the terminal `REMOVED`; the licensee's `control_chain_status` is then forced to `BLOCKED`, and every child holder whose `parent_control_person_id` names the removed row has both `effective_ownership_bps` and `attributed_ownership_bps` recomputed to zero and is itself set to `REMOVED`."
    PRD 3.2: "A `BLOCKED` chain stops three things dead — application submission, application approval and licence renewal — each with `ERR_CONTROL_CHAIN_BLOCKED` (HTTP 409)."
    PRD 3.3: "The licensee's `coverage_posture` must not be `FROZEN`, or the submission is rejected with `ERR_POSTURE_FROZEN`, and its `control_chain_status` must not be `BLOCKED`."

    Design: Corner/validations/blocked_control_chain_stops_a_later_application_submit
    """
    texas = fx.create_jurisdiction(api, C.TX_CONFIG)
    holder = _licensee_with_a_live_application_and_one_control_holder(
        api, licensee["id"], ca_jurisdiction["id"]
    )

    adjudicated = fx.adjudicate_adverse(api, holder["id"], ca_jurisdiction["id"])
    assert adjudicated["background_check_status"] == "ADVERSE"
    assert adjudicated["disqualifying_finding"] is True
    assert fx.get_licensee(api, licensee["id"])["control_chain_status"] == "BLOCKED"

    texas_application = fx.create_application(api, licensee["id"], texas["id"])
    assert texas_application["status"] == "DRAFT"

    response = api.submit_application(texas_application["id"], MANAGER_HEADERS)

    validate_error(response, ERR_CONTROL_CHAIN_BLOCKED, 409)

    row = validate_success(api.get_application(texas_application["id"], MANAGER_HEADERS))
    assert row["status"] == "DRAFT"
    assert row["submitted_at"] is None
    assert row["version"] == texas_application["version"]


def test_a_cleared_holder_leaves_the_chain_verified_and_the_submit_admissible(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """The same filing goes through once the same holder is cleared instead.

    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "`background_check_status` is set to `PENDING` for a control person and to `NOT_REQUIRED` otherwise; its full value set is `NOT_REQUIRED`, `PENDING`, `CLEARED` and `ADVERSE`, and it defaults to `NOT_REQUIRED`."
    PRD 3.2: "An `outcome` of `CLEARED` sets `background_check_status` to `CLEARED`."
    PRD 3.2: "It is recomputed on every control-person creation, every background-check adjudication and every change-of-control decision, by this precedence: `BLOCKED` if any such holder has `background_check_status` of `ADVERSE` or `change_of_control_status` of `DENIED`; otherwise `PENDING_CHECKS` if any such holder has `background_check_status` of `PENDING` or `change_of_control_status` of `PENDING_APPROVAL`; otherwise `VERIFIED`."
    PRD 3.2: "A `BLOCKED` chain stops three things dead — application submission, application approval and licence renewal — each with `ERR_CONTROL_CHAIN_BLOCKED` (HTTP 409)."
    PRD 3.3: "On success the application moves `DRAFT → SUBMITTED`, `submitted_at` is stamped from the logical clock, `required_net_worth_cents` is pinned as a copy of the jurisdiction's `min_net_worth_cents`, and `required_bond_cents` is pinned to the surety bond figure computed as described in §3.4, using the jurisdiction configuration, the submitted `projected_annual_volume_cents`, the declared `license_class`, and a delegate count of zero — an applicant has no active delegates yet by definition."

    Design: Corner/validations/blocked_control_chain_stops_a_later_application_submit
    """
    texas = fx.create_jurisdiction(api, C.TX_CONFIG)
    holder = _licensee_with_a_live_application_and_one_control_holder(
        api, licensee["id"], ca_jurisdiction["id"]
    )

    cleared = fx.clear_background_check(api, holder["id"], ca_jurisdiction["id"])
    assert cleared["background_check_status"] == "CLEARED"
    assert fx.get_licensee(api, licensee["id"])["control_chain_status"] == "VERIFIED"

    texas_application = fx.create_application(api, licensee["id"], texas["id"])
    row = validate_success(api.submit_application(texas_application["id"], MANAGER_HEADERS))

    assert row["status"] == "SUBMITTED"
    assert _instant(row["submitted_at"]) == "2026-08-01T00:00:00"
    # Texas pins its own net-worth floor of 100000000 cents onto the filing.
    assert row["required_net_worth_cents"] == 100_000_000
