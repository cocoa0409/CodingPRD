"""State machines across the licensing estate.

Every row in this system moves along a declared set of edges: an application from
`DRAFT` through review to issuance, a licence through bonding, suspension and the
terminal `SURRENDERED`, a coverage test from `DRAFT` to the terminal `CERTIFIED`,
a delegate authorization to the terminal `TERMINATED`, an examination through the
strict fieldwork-to-closure chain and an information request to the terminal
`ACCEPTED`. These tests exercise the initial states, the undeclared transitions
and the terminal lockdowns, and each one reads the row back afterwards to prove
that a refused transition moved nothing.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APPLICATION_INVALID_STATE,
    ERR_AUTHORIZATION_INVALID_STATE,
    ERR_EXAM_INVALID_STATE,
    ERR_INFO_REQUEST_INVALID_STATE,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_LICENSE_TERMINAL,
    ERR_TEST_INVALID_STATE,
)
from test_helpers.test_users import CHIEF_HEADERS, MANAGER_HEADERS, make_state_regulator_headers

# The logical clock's process-start instant, without its trailing designator, so
# that a stamp can be compared regardless of how many fractional digits it shows.
CLOCK_START = C.SEED_CLOCK.rstrip("Z")


# ===========================================================================
# Instance: a fresh application is DRAFT and pins nothing until submission
# ===========================================================================


def test_new_application_is_draft_and_pins_requirements_only_on_submit(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """A created application is DRAFT with no stamps; submit pins bond and net worth.

    PRD 3.3: "The row starts in `DRAFT`; the remaining statuses are `SUBMITTED`, `UNDER_REVIEW`, `DEFICIENT`, `APPROVED`, `DENIED` and `WITHDRAWN`, of which the last three are terminal."
    PRD 3.3: "Submission is the moment the arithmetic gets pinned."
    PRD 3.3: "On success the application moves `DRAFT → SUBMITTED`, `submitted_at` is stamped from the logical clock, `required_net_worth_cents` is pinned as a copy of the jurisdiction's `min_net_worth_cents`, and `required_bond_cents` is pinned to the surety bond figure computed as described in §3.4, using the jurisdiction configuration, the submitted `projected_annual_volume_cents`, the declared `license_class`, and a delegate count of zero — an applicant has no active delegates yet by definition."
    PRD 3.4: "A volume of at most one billion cents — that is, ten million dollars — is tier one at a tier bond of two and a half million cents; a volume above one billion cents but at most ten billion cents is tier two at ten million cents; a volume above ten billion cents is tier three at twenty-five million cents."
    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 3.4: "Step three multiplies that figure by the class multiplier for the `license_class` and divides by 10000, rounding down: `MONEY_TRANSMISSION` carries a multiplier of 10000 basis points and therefore leaves the figure unchanged, `PAYMENT_INSTRUMENTS` carries 12000 basis points, and `VIRTUAL_CURRENCY` carries 15000 basis points."
    PRD 3.4: "Step four takes the lesser of that result and the jurisdiction's `bond_cap_cents`."
    PRD 2.4: "The server holds a **logical clock** that starts at `2026-08-01T00:00:00Z` when the process starts and never advances on its own."
    PRD 3.3: "Approval stamps `decision_at` and mints a licence."

    Design: Corner/state_machines/new_license_application_starts_in_draft_with_zero_requirements
    """
    draft = validate_success(
        api.create_application(
            F.application_payload(
                licensee["id"],
                ca_jurisdiction["id"],
                projected_annual_volume_cents=250_000_000,
            ),
            MANAGER_HEADERS,
        ),
        201,
    )

    assert draft["status"] == "DRAFT"
    # Nothing is stamped and no decision is taken before submission.
    assert draft.get("submitted_at") is None
    assert draft.get("decision_at") is None
    assert draft.get("denial_reason") is None

    # No licence exists yet: only an approval mints one.
    licenses, meta = validate_paginated(
        api.list_state_licenses(MANAGER_HEADERS, params={"application_id": draft["id"]})
    )
    assert meta["total_count"] == 0
    assert licenses == []

    submitted = validate_success(api.submit_application(draft["id"], MANAGER_HEADERS))

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"].startswith(CLOCK_START)
    # required_net_worth_cents is a copy of CA's min_net_worth_cents.
    assert submitted["required_net_worth_cents"] == 50_000_000
    # Bond: volume 250,000,000 <= 1,000,000,000 -> tier bond 2,500,000;
    # max(base 5,000,000, 2,500,000 + 0 * 100,000) = 5,000,000;
    # 5,000,000 * 10000 / 10000 = 5,000,000; min(5,000,000, cap 40,000,000) = 5,000,000.
    assert submitted["required_bond_cents"] == 5_000_000


# ===========================================================================
# Instance: submit is admissible only from DRAFT
# ===========================================================================


def test_replaying_submit_on_a_submitted_application_rejects(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """A second submit on a SUBMITTED application is refused and re-stamps nothing.

    PRD 3.3: "The application must be in `DRAFT`; a submit from any other status is rejected with `ERR_APPLICATION_INVALID_STATE`."
    PRD 3.3: "There must be no other application for the same licensee and the same jurisdiction whose `status` is `SUBMITTED`, `UNDER_REVIEW`, `DEFICIENT` or `APPROVED`; a second live filing is rejected with `ERR_DUPLICATE_LICENSE_APPLICATION`."
    PRD 2.7: "When several rules could reject the same request, the system evaluates them in a fixed order and returns the error of the first rule that fails."
    PRD 3.3: "On success the application moves `DRAFT → SUBMITTED`, `submitted_at` is stamped from the logical clock, `required_net_worth_cents` is pinned as a copy of the jurisdiction's `min_net_worth_cents`, and `required_bond_cents` is pinned to the surety bond figure computed as described in §3.4, using the jurisdiction configuration, the submitted `projected_annual_volume_cents`, the declared `license_class`, and a delegate count of zero — an applicant has no active delegates yet by definition."

    Design: Corner/state_machines/resubmitting_an_application_twice_rejects_with_application_invalid_state
    """
    application = fx.create_application(
        api,
        licensee["id"],
        ca_jurisdiction["id"],
        projected_annual_volume_cents=250_000_000,
    )
    first = fx.submit_application(api, application["id"])
    assert first["status"] == "SUBMITTED"

    # The state rung of the §2.7 ladder is reached before the uniqueness rung, so
    # the replay reports the invalid state and not a duplicate live filing.
    validate_error(
        api.submit_application(application["id"], MANAGER_HEADERS),
        ERR_APPLICATION_INVALID_STATE,
    )

    after = validate_success(api.get_application(application["id"], MANAGER_HEADERS))
    assert after["status"] == "SUBMITTED"
    assert after["submitted_at"] == first["submitted_at"]
    assert after["submitted_at"].startswith(CLOCK_START)
    assert after["required_bond_cents"] == 5_000_000  # unchanged by the refused replay


# ===========================================================================
# Instance: WITHDRAW is declared only on the DEFICIENT edge
# ===========================================================================


def test_withdraw_from_under_review_rejects_and_leaves_the_application_under_review(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """WITHDRAW aimed at an UNDER_REVIEW application is refused as an invalid state.

    PRD 3.3: "A `DEFICIENT` application may instead be closed out: the regulator records the applicant's withdrawal with the action `WITHDRAW`, moving `DEFICIENT → WITHDRAWN`, clearing `deficiency_deadline_at` and stamping `decision_at`, and no licence is minted."
    PRD 2.7: "**Entity state admissibility**, in this order: application status (`ERR_APPLICATION_INVALID_STATE`), licence authorisation status (`ERR_LICENSE_NOT_ACTIVE`), licence terminality (`ERR_LICENSE_TERMINAL`), coverage-test status (`ERR_TEST_INVALID_STATE`), authorization status (`ERR_AUTHORIZATION_INVALID_STATE`), examination status (`ERR_EXAM_INVALID_STATE`), information-request status (`ERR_INFO_REQUEST_INVALID_STATE`), enforcement status (`ERR_ENFORCEMENT_INVALID_STATE`), control-person status (`ERR_CONTROL_PERSON_INVALID_STATE`)."
    PRD 3.3: "The action `START_REVIEW` moves `SUBMITTED → UNDER_REVIEW` and refreshes `updated_at`."

    Design: Corner/state_machines/withdraw_from_under_review_rejects_with_application_invalid_state
    """
    application = fx.create_application(
        api,
        licensee["id"],
        ca_jurisdiction["id"],
        projected_annual_volume_cents=250_000_000,
    )
    fx.submit_application(api, application["id"])
    under_review = fx.review_application(
        api, application["id"], ca_jurisdiction["id"], "START_REVIEW"
    )
    assert under_review["status"] == "UNDER_REVIEW"

    validate_error(
        api.review_application(
            application["id"],
            F.review_action_payload("WITHDRAW", note="Applicant asked to withdraw."),
            make_state_regulator_headers(ca_jurisdiction["id"]),
        ),
        ERR_APPLICATION_INVALID_STATE,
    )

    after = validate_success(api.get_application(application["id"], MANAGER_HEADERS))
    assert after["status"] == "UNDER_REVIEW"
    assert after.get("decision_at") is None  # nothing was decided
    assert after.get("deficiency_deadline_at") is None  # no deficiency round was opened


# ===========================================================================
# Instance: bond posting is admissible only from PENDING_BOND
# ===========================================================================


def test_second_bond_posting_on_an_active_licence_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Posting a second bond on an ACTIVE licence is refused and overwrites nothing.

    PRD 3.4: "Posting is admissible only from `PENDING_BOND`; from any other authorisation status the request is rejected with `ERR_LICENSE_NOT_ACTIVE`."
    PRD 3.4: "On success the licence moves `PENDING_BOND → ACTIVE`: `bond_posted_cents` records the face amount, `bond_status` becomes `POSTED`, the `bond_issuer` is stored, `authorized_at` is stamped from the logical clock, the licensee's `active_license_count` is increased by one, and — because the licence has just joined the obligation aggregate set — the licensee's `aggregate_outstanding_obligations_cents` is recomputed."
    PRD 3.4: "The posted amount must be at least the licence's current `bond_requirement_cents`; a smaller bond is rejected with `ERR_BOND_INSUFFICIENT` (HTTP 422)."
    PRD 2.4: "Almost every resource additionally carries an `updated_at` — refreshed on every mutation, in the same format — and a `version`, an integer that starts at 1 on creation and increments by one on every mutation of that row."

    Design: Corner/state_machines/second_bond_posting_rejects_with_license_not_active
    """
    before = fx.get_license(api, active_license.license_id)
    assert before["license_status"] == "ACTIVE"
    # The fixture posts exactly the requirement pinned at submission: volume
    # 500,000,000 -> tier bond 2,500,000; max(base 5,000,000, 2,500,000) = 5,000,000.
    assert before["bond_posted_cents"] == 5_000_000

    validate_error(
        api.post_bond(
            active_license.license_id,
            F.bond_payload(9_000_000, bond_issuer="Second Surety"),
            MANAGER_HEADERS,
        ),
        ERR_LICENSE_NOT_ACTIVE,
    )

    after = fx.get_license(api, active_license.license_id)
    assert after["license_status"] == "ACTIVE"
    assert after["bond_status"] == "POSTED"
    assert after["bond_posted_cents"] == 5_000_000
    assert after["bond_issuer"] == C.SEED_BOND_ISSUER
    assert after["version"] == before["version"]  # a refused post bumps nothing

    licensee_row = fx.get_licensee(api, active_license.licensee_id)
    assert licensee_row["active_license_count"] == 1  # one bonding, counted once


# ===========================================================================
# Instance: SURRENDERED is terminal for a licence
# ===========================================================================


def test_call_report_against_a_surrendered_licence_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A surrendered licence accepts no further filing and keeps its volume at zero.

    PRD 2.8: "Only `license_status` reaching `SURRENDERED` or `REVOKED` stops filings altogether, and any attempt to mutate such a licence — including filing a call report against it, running any licence-level operation on it, or issuing a new enforcement action against it — is rejected with `ERR_LICENSE_TERMINAL`."
    PRD 3.5: "Filing is impossible against a `SURRENDERED` or `REVOKED` licence, which reports `ERR_LICENSE_TERMINAL`."
    PRD 3.4: "A `decision` of `APPROVED`, with an optional `rationale`, moves `SURRENDER_REQUESTED → SURRENDERED`, which is terminal, sets `bond_status` to `CANCELLED`, drives every non-`TERMINATED` `DelegateAuthorization` of the licence to `TERMINATED`, decrements the licensee's `active_license_count`, and — because the licence has left the aggregate set — recomputes the licensee's `aggregate_outstanding_obligations_cents`, `coverage_ratio_bps` and `coverage_posture`."
    PRD 3.5: "Regardless of status, every filing adds its `transmission_volume_cents` to the licence's `annual_volume_cents` and recomputes `bond_requirement_cents`, since the volume tier may have moved."

    Design: Corner/state_machines/call_report_on_surrendered_license_rejects_with_license_terminal
    """
    bonded = fx.get_license(api, active_license.license_id)
    assert bonded["outstanding_obligations_cents"] == 0

    validate_success(
        api.request_surrender(
            active_license.license_id,
            F.surrender_request_payload(
                bonded["version"],
                effective_date="2026-09-30T00:00:00Z",
                wind_down_narrative="All obligations settled; no delegates.",
            ),
            MANAGER_HEADERS,
        )
    )
    surrendered = validate_success(
        api.decide_surrender(
            active_license.license_id,
            F.surrender_decision_payload("APPROVED", rationale="Wind-down plan accepted."),
            make_state_regulator_headers(active_license.jurisdiction_id),
        )
    )
    assert surrendered["license_status"] == "SURRENDERED"
    assert surrendered["bond_status"] == "CANCELLED"

    licensee_after_surrender = fx.get_licensee(api, active_license.licensee_id)
    # One licence bonded (+1) then surrendered from ACTIVE (-1) = 0.
    assert licensee_after_surrender["active_license_count"] == 0

    validate_error(
        api.file_call_report(
            F.call_report_payload(active_license.license_id, "2026Q2", 40_000_000, 700),
            MANAGER_HEADERS,
        ),
        ERR_LICENSE_TERMINAL,
    )

    reports, meta = validate_paginated(
        api.list_license_call_reports(active_license.license_id, MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0
    assert reports == []

    after = fx.get_license(api, active_license.license_id)
    assert after["license_status"] == "SURRENDERED"
    assert after["annual_volume_cents"] == 0  # the refused filing added nothing


# ===========================================================================
# Instance: certification is admissible only from PREPARED
# ===========================================================================


def test_certifying_a_draft_coverage_test_rejects(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """Certifying a test that was never prepared is refused and stamps nothing.

    PRD 3.7: "An operation on a test in the wrong status — preparing anything that is not `DRAFT`, certifying anything that is not `PREPARED`, or touching a `SUPERSEDED` or `CERTIFIED` row — is rejected with `ERR_TEST_INVALID_STATE`."
    PRD 3.7: "The row starts in `DRAFT`; the other statuses are `PREPARED`, and the terminal `CERTIFIED` and `SUPERSEDED`."
    PRD 3.7: "It is admissible only from `PREPARED`; the certifying `X-User-ID` must differ from `prepared_by_user_id` per §2.10; and it must arrive on or before forty-five days after `coverage_period_end` — the boundary is inclusive, and a late certification is rejected with `ERR_CERTIFICATION_WINDOW_CLOSED`."
    PRD 3.7: "First, the test moves `PREPARED → CERTIFIED`, `certified_at` is stamped from the logical clock, `certified_by_user_id` records the acting identity, and the licensee's `consecutive_failed_test_count` either increases by one — when the test's `result` is `SHORTFALL` — or resets to zero when it is `PASS`; `coverage_posture` is then recomputed, and because two consecutive certified shortfalls set the count to 2, the second one alone forces the posture to `FROZEN` no matter how good the ratio looks."
    PRD 3.7: "`obligations_cents` snapshots the licensee's `aggregate_outstanding_obligations_cents`; `investment_value_cents` snapshots the permissible investment value computed under this row's own `method`; `coverage_ratio_bps` is that value multiplied by 10000 divided by `obligations_cents` and rounded down, or exactly 10000 when `obligations_cents` is zero; `shortfall_cents` is `obligations_cents` minus `investment_value_cents`, or zero when that difference would be negative — never a negative number; and `result` becomes `PASS` when `coverage_ratio_bps` is at least 10000 and `SHORTFALL` otherwise, having been null until preparation."
    PRD 3.1: "A freshly created licensee starts with `version` at 1, `coverage_posture` at `COMPLIANT`, `coverage_ratio_bps` at 10000 — vacuously perfect, since there are no obligations yet — `control_chain_status` at `VERIFIED`, and every counter at zero: `aggregate_outstanding_obligations_cents`, `eligible_investment_value_cents`, `book_investment_value_cents`, `consecutive_failed_test_count` and `active_license_count`."

    Design: Corner/state_machines/certifying_a_draft_test_rejects_with_test_invalid_state
    """
    fx.record_holding(
        api, licensee["id"], "CASH", "First Republic Trust", 4_000_000, 4_000_000
    )
    test = fx.open_investment_test(api, licensee["id"], "ELIGIBLE_MARKET")
    assert test["status"] == "DRAFT"

    validate_error(
        api.certify_investment_test(
            test["id"],
            CHIEF_HEADERS,
            F.certify_payload(attestation_note="Certified without preparation."),
        ),
        ERR_TEST_INVALID_STATE,
    )

    after = validate_success(api.get_investment_test(test["id"], CHIEF_HEADERS))
    assert after["status"] == "DRAFT"
    assert after.get("certified_by_user_id") is None
    assert after.get("certified_at") is None
    assert after.get("result") is None

    licensee_after = fx.get_licensee(api, licensee["id"])
    assert licensee_after["consecutive_failed_test_count"] == 0  # no certification landed
    assert licensee_after["coverage_posture"] == "COMPLIANT"


# ===========================================================================
# Instance: TERMINATED is terminal for a delegate authorization
# ===========================================================================


def test_activating_a_terminated_authorization_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A terminated authorization cannot be activated even with a passing score.

    PRD 3.6: "It is admissible from `PENDING_OVERSIGHT` or from `SUSPENDED_BY_POSTURE`, and from nothing else — an attempt from `ACTIVE`, `SUSPENDED` or `TERMINATED` is rejected with `ERR_AUTHORIZATION_INVALID_STATE`."
    PRD 3.6: "Termination is the compensating action and is admissible from every non-`TERMINATED` status."
    PRD 3.6: "If it had only been `PENDING_OVERSIGHT`, no counter moves, because the row was never counted."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."
    PRD 3.6: "The remaining statuses are `ACTIVE`, `SUSPENDED_BY_POSTURE`, `SUSPENDED` and the terminal `TERMINATED`; `activated_at` and `oversight_score_at_activation` both start null."
    PRD 3.6: "On success, and identically for both admissible source statuses, the authorization moves to `ACTIVE`, `activated_at` is stamped from the logical clock, and `oversight_score_at_activation` pins the delegate's `oversight_score` as it stood at that instant."
    PRD 3.6: "The first successful activation moves the delegate `ONBOARDING → ACTIVE`; an activation out of `SUSPENDED_BY_POSTURE` for a delegate that had been parked moves it `SUSPENDED → ACTIVE` and clears `oversight_hold` to false."
    PRD 3.6: "The row starts in `ONBOARDING`, the other statuses being `ACTIVE`, `SUSPENDED` and the terminal `TERMINATED`."
    PRD 3.6: "The resulting `oversight_score` is the training score weighted at 4000 basis points, plus the anti-money-laundering test score weighted at 3500 basis points, plus the recordkeeping score weighted at 2500 basis points, that sum divided by 10000 and rounded down to a whole number."

    Design: Corner/state_machines/activating_a_terminated_authorization_rejects
    """
    delegate = fx.create_delegate(api, active_license.licensee_id)
    scored = fx.review_delegate(
        api, delegate["id"], training_score=90, aml_test_score=90, recordkeeping_score=70
    )
    # floor((90*4000 + 90*3500 + 70*2500) / 10000) = floor(850000 / 10000) = 85.
    assert scored["oversight_score"] == 85

    authorization = fx.create_authorization(
        api,
        delegate["id"],
        active_license.license_id,
        "2026-09-01T00:00:00Z",
        "2027-08-31T00:00:00Z",
    )
    assert authorization["status"] == "PENDING_OVERSIGHT"
    terminated = fx.terminate_authorization(api, authorization["id"])
    assert terminated["status"] == "TERMINATED"

    validate_error(
        api.activate_authorization(authorization["id"], MANAGER_HEADERS),
        ERR_AUTHORIZATION_INVALID_STATE,
    )

    after = validate_success(
        api.get_delegate_authorization(authorization["id"], MANAGER_HEADERS)
    )
    assert after["status"] == "TERMINATED"
    assert after.get("activated_at") is None
    assert after.get("oversight_score_at_activation") is None

    delegate_after = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert delegate_after["status"] == "ONBOARDING"  # never activated, never terminated
    assert delegate_after["oversight_score"] == 85
    assert delegate_after["authorized_state_count"] == 0

    license_after = fx.get_license(api, active_license.license_id)
    assert license_after["active_delegate_count"] == 0
    # No delegate ever counted, so the requirement is still the application figure.
    assert license_after["bond_requirement_cents"] == 5_000_000


# ===========================================================================
# Instance: the examination chain admits no shortcut
# ===========================================================================


def test_exam_jumping_from_scheduled_to_report_issued_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """REPORT_ISSUED requested straight out of SCHEDULED is refused and stores no findings.

    PRD 3.8: "The lead supplies a `to_status`, and a transition that is not a declared edge is rejected with `ERR_EXAM_INVALID_STATE`."
    PRD 3.8: "On success the exam starts in `SCHEDULED` and `participating_state_count` is set to the distinct count of participating jurisdictions including the lead."
    PRD 3.8: "The remaining statuses are `FIELDWORK`, `REPORT_DRAFT`, `REPORT_ISSUED` and the terminal `CLOSED`; `open_request_count` and `findings_count` both start at zero."
    PRD 3.8: "`REPORT_DRAFT → REPORT_ISSUED` carries a `findings_count`, which is stored, and here the examination reaches out into the estate: when `findings_count` is 3 or more, every `StateLicense` of the examined licensee whose `jurisdiction_id` appears in `participating_jurisdiction_ids` has `exam_findings_open` set to true and `expansion_gate` set to `BLOCKED`, and every `DelegateAuthorization` of those licences whose `status` is `PENDING_OVERSIGHT` moves to `SUSPENDED_BY_POSTURE`; when `findings_count` is 2 or fewer, no licence is touched at all."
    PRD 2.8: "It is `OPEN` exactly when all five of the following hold: `license_status` is `ACTIVE`, `bond_status` is `POSTED`, `reporting_status` is `CURRENT`, `exam_findings_open` is false, and the owning licensee's `coverage_posture` is either `COMPLIANT` or `WATCH`."

    Design: Corner/state_machines/exam_jumping_from_scheduled_to_report_issued_rejects
    """
    exam = fx.schedule_exam(
        api,
        active_license.licensee_id,
        active_license.jurisdiction_id,
        "2026-09-01T00:00:00Z",
        "2026-09-15T00:00:00Z",
    )
    assert exam["status"] == "SCHEDULED"

    validate_error(
        api.change_exam_status(
            exam["id"],
            F.exam_status_payload("REPORT_ISSUED", findings_count=4),
            make_state_regulator_headers(active_license.jurisdiction_id),
        ),
        ERR_EXAM_INVALID_STATE,
    )

    after = validate_success(
        api.get_exam(exam["id"], make_state_regulator_headers(active_license.jurisdiction_id))
    )
    assert after["status"] == "SCHEDULED"
    assert after["findings_count"] == 0  # the refused edge stored nothing
    assert after["participating_state_count"] == 1  # CA is both lead and sole participant
    assert after["open_request_count"] == 0

    license_after = fx.get_license(api, active_license.license_id)
    assert license_after["exam_findings_open"] is False
    assert license_after["expansion_gate"] == "OPEN"


# ===========================================================================
# Instance: the two child-derived gates on the examination chain
# ===========================================================================


def test_report_draft_with_an_open_information_request_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """An exam with one OPEN request cannot leave FIELDWORK for REPORT_DRAFT.

    PRD 3.8: "`FIELDWORK → REPORT_DRAFT` is gated on the record requests being finished: `open_request_count` must be exactly zero, meaning no `InformationRequest` of the exam remains in `OPEN`, `OVERDUE` or `RESPONDED`."
    PRD 3.8: "The row starts in `OPEN` — the other statuses being `RESPONDED`, `OVERDUE` and the terminal `ACCEPTED` — with `reopen_count` and `submitted_item_count` at zero and `responded_at` null."
    PRD 3.8: "Because `open_request_count` is by definition the number of the exam's requests sitting in `OPEN`, `OVERDUE` or `RESPONDED`, opening a request raises it by one."
    PRD 3.8: "Its `due_at` is the current logical clock plus the requesting jurisdiction's `response_window_days`, expressed as that many exact twenty-four-hour periods."
    PRD 3.8: "The lead supplies a `to_status`, and a transition that is not a declared edge is rejected with `ERR_EXAM_INVALID_STATE`."

    Design: Corner/state_machines/closing_an_exam_with_an_open_information_request_rejects
    """
    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        active_license.jurisdiction_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
    )
    assert exam["status"] == "FIELDWORK"

    request = fx.open_information_request(
        api,
        exam["id"],
        active_license.jurisdiction_id,
        subject="Delegate settlement ledgers",
        requested_item_count=3,
    )
    assert request["status"] == "OPEN"
    # Clock 2026-08-01 plus CA's response_window_days of 15 exact 24-hour periods.
    assert request["due_at"].startswith("2026-08-16T00:00:00")

    regulator = make_state_regulator_headers(active_license.jurisdiction_id)
    with_open_request = validate_success(api.get_exam(exam["id"], regulator))
    assert with_open_request["open_request_count"] == 1  # one OPEN request

    validate_error(
        api.change_exam_status(exam["id"], F.exam_status_payload("REPORT_DRAFT"), regulator),
        ERR_EXAM_INVALID_STATE,
    )

    after = validate_success(api.get_exam(exam["id"], regulator))
    assert after["status"] == "FIELDWORK"
    assert after["open_request_count"] == 1
    assert after["findings_count"] == 0


def test_closing_an_exam_over_an_unresolved_enforcement_action_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A REPORT_ISSUED exam cannot close while the action it produced is still ISSUED.

    PRD 3.8: "`REPORT_ISSUED → CLOSED` is compound: beyond the status and lead checks, no `EnforcementAction` whose `originating_exam_id` names this exam may still be in `ISSUED`, `CONTESTED` or `CONSENT_ORDER`."
    PRD 3.8: "An examination cannot be closed over an unresolved enforcement matter it produced, and the attempt is rejected with `ERR_EXAM_INVALID_STATE`."
    PRD 3.9: "The action starts in `ISSUED` and `issued_at` is stamped from the logical clock, which starts a twenty-day response window."
    PRD 3.9: "Until every action originating from an examination has reached `RESOLVED` or `REVOCATION`, that examination cannot be closed."
    PRD 3.8: "`REPORT_DRAFT → REPORT_ISSUED` carries a `findings_count`, which is stored, and here the examination reaches out into the estate: when `findings_count` is 3 or more, every `StateLicense` of the examined licensee whose `jurisdiction_id` appears in `participating_jurisdiction_ids` has `exam_findings_open` set to true and `expansion_gate` set to `BLOCKED`, and every `DelegateAuthorization` of those licences whose `status` is `PENDING_OVERSIGHT` moves to `SUSPENDED_BY_POSTURE`; when `findings_count` is 2 or fewer, no licence is touched at all."

    Design: Corner/state_machines/closing_an_exam_with_an_open_information_request_rejects
    """
    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        active_license.jurisdiction_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
    )
    fx.change_exam_status(api, exam["id"], active_license.jurisdiction_id, "REPORT_DRAFT")
    issued = fx.change_exam_status(
        api, exam["id"], active_license.jurisdiction_id, "REPORT_ISSUED", findings_count=1
    )
    assert issued["status"] == "REPORT_ISSUED"
    assert issued["findings_count"] == 1
    assert issued["open_request_count"] == 0  # the REPORT_DRAFT gate was satisfied

    action = fx.issue_enforcement_action(
        api,
        active_license.license_id,
        active_license.jurisdiction_id,
        originating_exam_id=exam["id"],
    )
    assert action["status"] == "ISSUED"

    regulator = make_state_regulator_headers(active_license.jurisdiction_id)
    validate_error(
        api.change_exam_status(exam["id"], F.exam_status_payload("CLOSED"), regulator),
        ERR_EXAM_INVALID_STATE,
    )

    after = validate_success(api.get_exam(exam["id"], regulator))
    assert after["status"] == "REPORT_ISSUED"
    assert after["findings_count"] == 1

    action_after = validate_success(api.get_enforcement_action(action["id"], regulator))
    assert action_after["status"] == "ISSUED"

    license_after = fx.get_license(api, active_license.license_id)
    # findings_count 1 is below the 3-finding threshold, so no licence was touched.
    assert license_after["exam_findings_open"] is False


# ===========================================================================
# Instance: ACCEPTED is terminal for an information request
# ===========================================================================


def test_disposing_an_accepted_information_request_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A second disposition on an ACCEPTED request is refused and reopens nothing.

    PRD 3.8: "The row starts in `OPEN` — the other statuses being `RESPONDED`, `OVERDUE` and the terminal `ACCEPTED` — with `reopen_count` and `submitted_item_count` at zero and `responded_at` null."
    PRD 3.8: "A `decision` of `ACCEPTED`, admissible from `RESPONDED`, moves the request to the terminal `ACCEPTED` and takes it out of the open set, lowering `open_request_count` by one."
    PRD 3.8: "A `decision` of `REJECTED` from `RESPONDED` sends the request back to `OPEN`: `reopen_count` increases by one, `submitted_item_count` is reset to zero, and `due_at` is re-armed to the current logical clock plus five days — a deliberately short second clock, and notably not the jurisdiction's own `response_window_days`."
    PRD 3.8: "A `decision` of `REJECTED` taken while the request is still `OPEN` and the logical clock has already passed `due_at` moves it `OPEN → OVERDUE`; this is the only way a request becomes overdue, since moving the clock alone never flips a status."
    PRD 2.7: "**Entity state admissibility**, in this order: application status (`ERR_APPLICATION_INVALID_STATE`), licence authorisation status (`ERR_LICENSE_NOT_ACTIVE`), licence terminality (`ERR_LICENSE_TERMINAL`), coverage-test status (`ERR_TEST_INVALID_STATE`), authorization status (`ERR_AUTHORIZATION_INVALID_STATE`), examination status (`ERR_EXAM_INVALID_STATE`), information-request status (`ERR_INFO_REQUEST_INVALID_STATE`), enforcement status (`ERR_ENFORCEMENT_INVALID_STATE`), control-person status (`ERR_CONTROL_PERSON_INVALID_STATE`)."
    PRD 3.8: "On success the request moves to `RESPONDED`, `submitted_item_count` is stored and `responded_at` is stamped."

    Design: Corner/state_machines/disposing_an_accepted_information_request_rejects
    """
    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        active_license.jurisdiction_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
    )
    request = fx.open_information_request(
        api,
        exam["id"],
        active_license.jurisdiction_id,
        subject="Delegate settlement ledgers",
        requested_item_count=3,
    )
    responded = fx.respond_to_information_request(
        api, request["id"], 3, narrative="Three ledgers attached."
    )
    assert responded["status"] == "RESPONDED"
    accepted = fx.disposition_information_request(
        api, request["id"], active_license.jurisdiction_id, "ACCEPTED", rationale="Complete."
    )
    assert accepted["status"] == "ACCEPTED"

    regulator = make_state_regulator_headers(active_license.jurisdiction_id)
    validate_error(
        api.disposition_information_request(
            request["id"],
            F.disposition_payload("REJECTED", rationale="Changed our mind."),
            regulator,
        ),
        ERR_INFO_REQUEST_INVALID_STATE,
    )

    after = validate_success(api.get_information_request(request["id"], regulator))
    assert after["status"] == "ACCEPTED"
    assert after["reopen_count"] == 0  # the refused rejection re-armed nothing
    assert after["submitted_item_count"] == 3

    exam_after = validate_success(api.get_exam(exam["id"], regulator))
    # One request opened (+1) then accepted (-1) = 0, not decremented twice.
    assert exam_after["open_request_count"] == 0
