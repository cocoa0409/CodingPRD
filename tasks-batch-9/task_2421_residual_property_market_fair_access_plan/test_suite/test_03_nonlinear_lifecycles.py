"""Lifecycles that revisit states, branch three ways, or move one dimension only.

An application can re-enter a state it has already occupied, a policy carries two
dimensions that advance independently on the same record, and a single completion
endpoint forks into three terminal inspection results with three different
cascades behind them.
"""

from typing import List

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_field_equals,
    assert_field_null,
    assert_instant_equals,
)
from test_helpers.constants import (
    APP_STATUS_APPROVED_TO_BIND,
    APP_STATUS_DECLINED,
    APP_STATUS_IMPROVEMENTS_REQUIRED,
    APP_STATUS_INSPECTION_PENDING,
    COVERAGE_STATUS_IN_FORCE,
    DECLINE_REASON_INSPECTION_FAILED,
    DEPOP_STATUS_NOT_OFFERED,
    DEPOP_STATUS_OFFER_OUTSTANDING,
    INSPECTION_RESULT_FAIL,
    INSPECTION_RESULT_PASS,
    INSPECTION_RESULT_PASS_WITH_CONDITIONS,
    OFFER_STATUS_OUTSTANDING,
    OFFER_STATUS_WITHDRAWN,
    REQUIREMENT_CODE_DEFENSIBLE_SPACE,
    REQUIREMENT_CODE_ELECTRICAL,
    SEVERITY_MINOR,
)
from test_helpers.fixtures import (
    ApplicationChain,
    Foundations,
    build_in_force_policy,
    build_inspection_pending_application,
    complete_inspection,
    create_offer,
    order_inspection,
    read_inspection,
    read_member,
    read_offer,
    read_requirements,
)
from test_helpers.test_users import (
    make_member_insurer_headers,
    second_inspector_headers,
)

BOUND_ANNUAL_PREMIUM_CENTS = 577_125
BIND_DEADLINE_AT = "2026-10-01T00:00:00Z"


def _application_with_one_open_requirement(
    foundations: Foundations,
) -> ApplicationChain:
    """Completed once with conditions, so the application sits in remediation."""
    chain = build_inspection_pending_application(foundations.client, foundations)
    complete_inspection(
        chain,
        observed_condition_score=72,
        result=INSPECTION_RESULT_PASS_WITH_CONDITIONS,
        requirements=[f.requirement_spec()],
    )
    chain.refresh_application()
    return chain


def _three_applications_awaiting_inspection(
    foundations: Foundations,
) -> List[ApplicationChain]:
    """Three independent risks parked in INSPECTION_PENDING with an order placed."""
    chains = []
    for index, address in enumerate(("1 Shore Rd", "2 Shore Rd", "3 Shore Rd")):
        chains.append(
            build_inspection_pending_application(
                foundations.client,
                foundations,
                applicant_overrides={
                    "full_name": f"Owner {index}",
                    "email": f"owner{index}@example.com",
                },
                property_overrides={
                    "address_line": address,
                    "roof_age_years": 12 + index * 2,
                },
            )
        )
    return chains


# ---------------------------------------------------------------------------
# Re-entering a previously occupied application state
# ---------------------------------------------------------------------------


def test_reinspection_returns_the_application_to_improvements_required(
    roomy_foundations: Foundations,
) -> None:
    """A second conditional completion re-enters IMPROVEMENTS_REQUIRED.

    PRD: "Ordering a **re-inspection** from `IMPROVEMENTS_REQUIRED` additionally moves the application `IMPROVEMENTS_REQUIRED → INSPECTION_PENDING` and increments its `version` by one; requirements raised by the earlier inspection are not disturbed and keep their own status."

    PRD: "Because the reverse move exists too, `IMPROVEMENTS_REQUIRED → INSPECTION_PENDING → IMPROVEMENTS_REQUIRED` is a genuine cycle that may repeat as often as the risk demands."

    Design: Difficulty/non_linear_state_machine/application_reinspection_cycle_returns_to_improvements_required
    """
    chain = _application_with_one_open_requirement(roomy_foundations)
    first_inspection_id = chain.inspection_id
    assert_field_equals(chain.application, "status", APP_STATUS_IMPROVEMENTS_REQUIRED)

    order_inspection(chain)
    assert_field_equals(
        chain.refresh_application(), "status", APP_STATUS_INSPECTION_PENDING
    )
    complete_inspection(
        chain,
        observed_condition_score=80,
        result=INSPECTION_RESULT_PASS_WITH_CONDITIONS,
        requirements=[
            f.requirement_spec(REQUIREMENT_CODE_DEFENSIBLE_SPACE, SEVERITY_MINOR)
        ],
        headers=second_inspector_headers(),
    )

    assert_field_equals(
        chain.refresh_application(), "status", APP_STATUS_IMPROVEMENTS_REQUIRED
    )
    first = read_inspection(roomy_foundations.client, first_inspection_id)
    assert_field_equals(first, "result", INSPECTION_RESULT_PASS_WITH_CONDITIONS)
    assert_field_equals(first, "open_requirement_count", 1)


def test_second_inspection_starts_fresh_and_records_its_own_inspector(
    roomy_foundations: Foundations,
) -> None:
    """Two inspections coexist; the second carries the second inspector's id.

    PRD: "When `X-User-Role` is `Inspector`, it is recorded as `inspector_user_id` on the inspection that inspector completed."

    PRD: "`PENDING → PASS_WITH_CONDITIONS` is available when the request supplies at least one requirement. It creates one improvement requirement per supplied entry, each in `status` `OPEN` with `due_at` set to forty-five days after the inspection's `completed_at`; it writes the inspection's `open_requirement_count` to the number of requirements created and its `cleared_major_count` to 0; and it cascades the application `INSPECTION_PENDING → IMPROVEMENTS_REQUIRED`, on which branch `approved_to_bind_at` and `bind_deadline_at` both remain null."

    Design: Difficulty/non_linear_state_machine/application_reinspection_cycle_returns_to_improvements_required
    """
    chain = _application_with_one_open_requirement(roomy_foundations)

    order_inspection(chain)
    second = complete_inspection(
        chain,
        observed_condition_score=80,
        result=INSPECTION_RESULT_PASS_WITH_CONDITIONS,
        requirements=[
            f.requirement_spec(REQUIREMENT_CODE_DEFENSIBLE_SPACE, SEVERITY_MINOR)
        ],
        headers=second_inspector_headers(),
    )

    assert_field_equals(second, "result", INSPECTION_RESULT_PASS_WITH_CONDITIONS)
    assert_field_equals(second, "open_requirement_count", 1)
    assert_field_equals(second, "inspector_user_id", "insp-2")

    listing = roomy_foundations.client.list_application_inspections(
        chain.application_id, chain.producer_headers, {"limit": 100}
    )
    inspections, _meta = validate_paginated(listing)
    assert_count(inspections, 2, "inspections on the application")
    assert_field_null(chain.refresh_application(), "approved_to_bind_at")


# ---------------------------------------------------------------------------
# Two independent dimensions on the same policy record
# ---------------------------------------------------------------------------


def test_depopulation_dimension_cycles_while_coverage_stays_in_force(
    roomy_foundations: Foundations,
) -> None:
    """Offer, withdrawal and re-offer move only the depopulation dimension.

    PRD: "Withdrawal moves the offer `OUTSTANDING → WITHDRAWN`, increments its `version`, and resets the policy's `depopulation_status` from `OFFER_OUTSTANDING` back to `NOT_OFFERED` with the policy's `version` incremented by one — which makes the policy offerable again by any `ACTIVE` member, so the depopulation dimension is genuinely cyclic."

    PRD: "The coverage dimension is completely untouched by this move — `depopulation_status` and `coverage_status` are independent dimensions carried on the same policy record."

    Design: Difficulty/non_linear_state_machine/policy_depopulation_dimension_cycles_while_coverage_stays_in_force
    """
    client = roomy_foundations.client
    chain = build_in_force_policy(client, roomy_foundations)
    first_carrier = roomy_foundations.members[0]["id"]
    second_carrier = roomy_foundations.members[1]["id"]

    first_offer = create_offer(chain, member_index=0)
    assert_field_equals(
        chain.refresh_policy(), "depopulation_status", DEPOP_STATUS_OFFER_OUTSTANDING
    )

    withdrawal = client.withdraw_takeout_offer(
        first_offer["id"],
        f.withdrawal_payload(),
        make_member_insurer_headers(first_carrier),
    )
    assert withdrawal.status_code == 200, withdrawal.text
    assert_field_equals(
        chain.refresh_policy(), "depopulation_status", DEPOP_STATUS_NOT_OFFERED
    )

    second_offer = create_offer(
        chain, member_index=1, offered_premium_cents=640_000,
        election_deadline_at="2026-11-15T00:00:00Z",
    )

    policy = chain.refresh_policy()
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_IN_FORCE)
    assert_field_equals(policy, "depopulation_status", DEPOP_STATUS_OFFER_OUTSTANDING)
    assert_cents(
        policy["annual_premium_cents"],
        BOUND_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )
    assert_field_equals(
        read_offer(client, second_offer["id"]), "status", OFFER_STATUS_OUTSTANDING
    )
    assert second_carrier != first_carrier


def test_withdrawal_grants_no_depopulation_credit_to_either_carrier(
    roomy_foundations: Foundations,
) -> None:
    """A withdrawn offer leaves both carriers' credit counters at zero.

    PRD: "The offering carrier may instead withdraw an outstanding offer, supplying a `reason` that is stored as `withdrawal_reason`; the withdrawing operator's `X-User-ID` must equal the offer's `member_insurer_id`."

    PRD: "On the next hop the offering carrier's `takeout_credit_count` rises by the granted credit units and the carrier's `version` increments by one — this is how a carrier earns the depopulation credits it can later offset against an assessment."

    Design: Difficulty/non_linear_state_machine/policy_depopulation_dimension_cycles_while_coverage_stays_in_force
    """
    client = roomy_foundations.client
    chain = build_in_force_policy(client, roomy_foundations)
    first_carrier = roomy_foundations.members[0]["id"]

    first_offer = create_offer(chain, member_index=0)
    withdrawal = client.withdraw_takeout_offer(
        first_offer["id"],
        f.withdrawal_payload(),
        make_member_insurer_headers(first_carrier),
    )
    assert withdrawal.status_code == 200, withdrawal.text
    create_offer(
        chain, member_index=1, offered_premium_cents=640_000,
        election_deadline_at="2026-11-15T00:00:00Z",
    )

    withdrawn = read_offer(client, first_offer["id"])
    assert_field_equals(withdrawn, "status", OFFER_STATUS_WITHDRAWN)
    assert_field_equals(withdrawn, "withdrawal_reason", "capacity pulled")
    assert_field_equals(withdrawn, "credit_units_granted", 0)
    assert_field_equals(read_member(client, first_carrier), "takeout_credit_count", 0)
    assert_field_equals(
        read_member(client, roomy_foundations.members[1]["id"]),
        "takeout_credit_count",
        0,
    )


# ---------------------------------------------------------------------------
# One endpoint, three terminal results, three cascades
# ---------------------------------------------------------------------------


def test_pass_completion_cascades_to_approved_to_bind_with_a_thirty_day_window(
    roomy_foundations: Foundations,
) -> None:
    """A clean pass authorises binding for exactly thirty days.

    PRD: "`PENDING → PASS` is available when the request supplies no requirements. It cascades the application `INSPECTION_PENDING → APPROVED_TO_BIND`, writing `approved_to_bind_at` to the current logical clock and `bind_deadline_at` to thirty days after that instant."

    Design: Difficulty/non_linear_state_machine/inspection_three_way_fork_drives_three_different_application_states
    """
    passing, _conditional, _failing = _three_applications_awaiting_inspection(
        roomy_foundations
    )

    inspection = complete_inspection(
        passing, observed_condition_score=90, result=INSPECTION_RESULT_PASS
    )

    assert_field_equals(inspection, "result", INSPECTION_RESULT_PASS)
    application = passing.refresh_application()
    assert_field_equals(application, "status", APP_STATUS_APPROVED_TO_BIND)
    assert_instant_equals(
        application["bind_deadline_at"], BIND_DEADLINE_AT, "bind_deadline_at"
    )


def test_conditional_completion_cascades_to_improvements_required(
    roomy_foundations: Foundations,
) -> None:
    """The same endpoint with one requirement routes the risk into remediation.

    PRD: "`PASS`, `PASS_WITH_CONDITIONS` and `FAIL` are all terminal results for an inspection."

    PRD: "`open_requirement_count` is the number of child requirements whose `status` is `OPEN` **or** `EVIDENCE_SUBMITTED` — submitting evidence does not reduce it, because unverified evidence is not remediation."

    Design: Difficulty/non_linear_state_machine/inspection_three_way_fork_drives_three_different_application_states
    """
    _passing, conditional, _failing = _three_applications_awaiting_inspection(
        roomy_foundations
    )

    inspection = complete_inspection(
        conditional,
        observed_condition_score=68,
        result=INSPECTION_RESULT_PASS_WITH_CONDITIONS,
        requirements=[f.requirement_spec(REQUIREMENT_CODE_ELECTRICAL, SEVERITY_MINOR)],
    )

    assert_field_equals(inspection, "result", INSPECTION_RESULT_PASS_WITH_CONDITIONS)
    assert_field_equals(inspection, "open_requirement_count", 1)
    assert_field_equals(
        conditional.refresh_application(), "status", APP_STATUS_IMPROVEMENTS_REQUIRED
    )


def test_failing_completion_cascades_to_a_declined_application(
    roomy_foundations: Foundations,
) -> None:
    """A failure terminates the application with the fixed decline reason.

    PRD: "`PENDING → FAIL` creates **no** improvement requirements even if the request supplies some, and cascades the application `INSPECTION_PENDING → DECLINED`, writing `decline_reason` to the literal string `INSPECTION_FAILED`."

    Design: Difficulty/non_linear_state_machine/inspection_three_way_fork_drives_three_different_application_states
    """
    _passing, _conditional, failing = _three_applications_awaiting_inspection(
        roomy_foundations
    )

    inspection = complete_inspection(
        failing, observed_condition_score=30, result=INSPECTION_RESULT_FAIL
    )

    assert_field_equals(inspection, "result", INSPECTION_RESULT_FAIL)
    application = failing.refresh_application()
    assert_field_equals(application, "status", APP_STATUS_DECLINED)
    assert_field_equals(
        application, "decline_reason", DECLINE_REASON_INSPECTION_FAILED
    )
    assert_count(
        read_requirements(roomy_foundations.client, failing.inspection_id),
        0,
        "requirements created on a failure",
    )
