"""Package review rounds and the two status dimensions of a plan-of-action item.

These tests exercise the loops the program's state machines are built around: the
submit / review / revision-request cycle that turns into an outright rejection on
its third pass and voids the backing engagement, and the two orthogonal
dimensions a finding carries — the remediation dimension the operating parties
advance, the risk dimension the review queues decide, the reopen leg out of
closure, and the single false-positive edge that crosses from one dimension into
the other.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    BOARD_1,
    BOARD_2,
    make_board_headers,
    make_csp_lead_headers,
)

# ---------------------------------------------------------------------------
# Shared preludes
# ---------------------------------------------------------------------------


def _engagement_with_two_completed_slots(client):
    """An offering whose engagement delivered its report with two COMPLETED slots.

    The two slots draw 8.00 and 12.00 hours from a 200.00 hour pool, so the
    engagement sits at 20.00 allocated and 180.00 unallocated hours, and report
    delivery moved both slots ``SCHEDULED -> COMPLETED``.
    """
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_test_slot(
        client,
        env,
        start_at="2026-03-02T09:00:00Z",
        end_at="2026-03-02T17:00:00Z",
        hours=8.00,
        family_code="AC",
        key="slot_a",
    )
    env = fx.seed_test_slot(
        client,
        env,
        start_at="2026-03-03T00:00:00Z",
        end_at="2026-03-03T12:00:00Z",
        hours=12.00,
        family_code="SC",
        key="slot_b",
    )
    env = fx.seed_report_delivered(client, env, report_at=fx.AUTHORIZATION_CLOCK)
    return env


def _package_under_review_at_round(client, env, rounds):
    """Drive one package through ``rounds`` submissions, leaving it UNDER_REVIEW.

    Each pass submits the package and takes it into review; every pass but the
    last is then sent back with a revision note, which is the loop back into
    resubmission.
    """
    env = fx.seed_package(client, env)
    for index in range(rounds):
        env = fx.submit_package(client, env)
        env = fx.review_package(client, env, reviewer=BOARD_1)
        if index < rounds - 1:
            env = fx.request_revision(
                client,
                env,
                revision_note=f"Round {index + 1}: expand the CRM narrative.",
                reviewer=BOARD_1,
            )
    return env


def _request_revision(client, package_id, note):
    """Raise a revision request on a package under review."""
    return validate_success(
        client.request_package_revision(
            package_id, f.build_revision_request_payload(note), make_board_headers(BOARD_1)
        ),
        200,
    )


def _path_selected_offering_with_engagement(client):
    """A PATH_SELECTED, agency-sponsored offering with an engagement in place."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env, submit_plan=False, approve_plan=False)
    return env


def _finding_awaiting_verification_with_routed_deviation(client):
    """A HIGH finding awaiting verification with a 30-day request in the board queue.

    The finding was detected at 2026-02-01T00:00:00Z, so its unextended deadline
    is 2026-03-03T00:00:00Z, and its remediation dimension has already been
    driven ``OPEN -> IN_REMEDIATION -> AWAITING_VERIFICATION``.
    """
    env = _path_selected_offering_with_engagement(client)
    env = fx.seed_poam_item(
        client, env, severity="HIGH", detected_at=fx.SETUP_CLOCK, key="finding"
    )
    a.assert_instant(
        env["poam_items"]["finding"]["deadline_at"],
        "2026-03-03T00:00:00Z",
        "deadline_at at creation",
    )
    fx.drive_remediation(
        client, env, env["finding_id"], ["START", "SUBMIT_EVIDENCE"]
    )
    env = fx.seed_deviation(
        client,
        env,
        env["finding_id"],
        kind="OPERATIONAL_REQUIREMENT",
        requested_extension_days=30,
        review_queue="BOARD",
        router=BOARD_1,
    )
    return env


def _open_finding_with_false_positive_in_the_agency_queue(client):
    """An OPEN MODERATE finding with a false-positive request in the agency queue."""
    env = _path_selected_offering_with_engagement(client)
    env = fx.seed_poam_item(
        client, env, severity="MODERATE", detected_at=fx.SETUP_CLOCK, key="finding"
    )
    env = fx.seed_deviation(
        client,
        env,
        env["finding_id"],
        kind="FALSE_POSITIVE",
        review_queue="AGENCY",
        router=BOARD_1,
    )
    return env


def _authorized_offering_with_a_closed_finding(client):
    """A live authorization whose single MODERATE finding has been verified closed.

    The finding was detected at the authorization instant 2026-03-30T00:00:00Z,
    giving a 90-day deadline of 2026-06-28T00:00:00Z, and was driven
    ``START -> SUBMIT_EVIDENCE -> VERIFY_CLOSE``.
    """
    env = fx.seed_authorized_offering(client)
    env = fx.seed_poam_item(
        client,
        env,
        severity="MODERATE",
        detected_at=fx.AUTHORIZATION_CLOCK,
        key="finding",
    )
    a.assert_instant(
        env["poam_items"]["finding"]["deadline_at"],
        "2026-06-28T00:00:00Z",
        "deadline_at at creation",
    )
    fx.drive_remediation(
        client, env, env["finding_id"], ["START", "SUBMIT_EVIDENCE", "VERIFY_CLOSE"]
    )
    return env


# ---------------------------------------------------------------------------
# The three-round package review loop
# ---------------------------------------------------------------------------


def test_third_revision_request_rejects_the_package_instead_of_returning_it(client):
    """A revision request raised at submission round 3 rejects the package outright.

    PRD: "When `submission_round` has reached 3 the same act instead moves the package `UNDER_REVIEW → REJECTED`, still writing `revision_note`, decrements the offering's `open_package_count` by one, and cascades: the backing assessment engagement is driven to `VOIDED`, which in turn cancels every one of that engagement's `SCHEDULED` slots and returns their hours to `unallocated_hours`."

    Design: Difficulty/non_linear_state_machine/package_review_cycle_ends_in_rejection_on_the_third_revision_request
    """
    env = _engagement_with_two_completed_slots(client)
    env = _package_under_review_at_round(client, env, 3)
    assert env["package"]["status"] == "UNDER_REVIEW"
    a.assert_integer(env["package"]["submission_round"], 3, "submission_round")

    package = _request_revision(
        client, env["package_id"], "Round 3: unresolved architectural gap."
    )

    assert package["status"] == "REJECTED"
    assert package["status"] != "REVISION_REQUESTED"
    a.assert_integer(package["submission_round"], 3, "submission_round")
    assert package["revision_note"] == "Round 3: unresolved architectural gap."

    stored = fx.read_package(client, env["package_id"])
    assert stored["status"] == "REJECTED"
    assert stored["revision_note"] == "Round 3: unresolved architectural gap."


def test_first_revision_request_returns_the_package_for_another_submission(client):
    """Below round 3 the same act only sends the package back, leaving the engagement alive.

    PRD: "From `UNDER_REVIEW` the reviewer may send the package back with a `revision_note`: when `submission_round` is below 3 the package moves `UNDER_REVIEW → REVISION_REQUESTED` and the note is written, which is the cycle back into resubmission."

    Design: Difficulty/non_linear_state_machine/package_review_cycle_ends_in_rejection_on_the_third_revision_request
    """
    env = _engagement_with_two_completed_slots(client)
    env = _package_under_review_at_round(client, env, 1)

    package = _request_revision(
        client, env["package_id"], "Round 1: expand the CRM narrative."
    )

    assert package["status"] == "REVISION_REQUESTED"
    assert package["status"] != "REJECTED"
    a.assert_integer(package["submission_round"], 1, "submission_round")
    assert package["revision_note"] == "Round 1: expand the CRM narrative."

    engagement = fx.read_engagement(client, env["engagement_id"])
    assert engagement["status"] == "REPORT_DELIVERED"
    assert engagement["status"] != "VOIDED"

    offering = fx.read_offering(client, env["offering_id"])
    a.assert_integer(offering["open_package_count"], 1, "open_package_count")


def test_rejection_at_the_revision_limit_voids_the_engagement_and_spares_its_completed_slots(
    client,
):
    """The void cascade cancels only SCHEDULED slots, so the hour ledger does not move.

    PRD: "An engagement in `PLAN_APPROVED`, `TESTING` or `REPORT_DELIVERED` moves to `VOIDED` when the package it backs is rejected after exhausting the revision limit, and in all three cases the void cancels every slot of the engagement still in `SCHEDULED` and returns their hours to `unallocated_hours`."

    Design: Difficulty/non_linear_state_machine/package_review_cycle_ends_in_rejection_on_the_third_revision_request
    """
    env = _engagement_with_two_completed_slots(client)
    env = _package_under_review_at_round(client, env, 3)

    _request_revision(
        client, env["package_id"], "Round 3: unresolved architectural gap."
    )

    engagement = fx.read_engagement(client, env["engagement_id"])
    assert engagement["status"] == "VOIDED"

    slots = {row["id"]: row for row in fx.list_test_slots(client, env["engagement_id"])}
    assert slots[env["slot_a_id"]]["status"] == "COMPLETED"
    assert slots[env["slot_b_id"]]["status"] == "COMPLETED"
    assert slots[env["slot_a_id"]]["status"] != "CANCELLED"
    assert slots[env["slot_b_id"]]["status"] != "CANCELLED"

    a.assert_money(engagement["allocated_hours"], 20.00, "allocated_hours")
    a.assert_money(engagement["unallocated_hours"], 180.00, "unallocated_hours")
    a.assert_hour_conservation(engagement)


def test_rejected_package_leaves_the_offering_with_no_open_package(client):
    """A package rejected at the revision limit no longer counts as an open package.

    PRD: "An offering's `open_package_count` counts its authorization packages in `status` `DRAFT`, `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED`; its `superseded_package_count` counts its packages in `status` `SUPERSEDED`; its `included_service_count` counts the services inside the authorization boundary."

    Design: Difficulty/non_linear_state_machine/package_review_cycle_ends_in_rejection_on_the_third_revision_request
    """
    env = _engagement_with_two_completed_slots(client)
    env = _package_under_review_at_round(client, env, 3)
    before = fx.read_offering(client, env["offering_id"])
    a.assert_integer(before["open_package_count"], 1, "open_package_count before")

    _request_revision(
        client, env["package_id"], "Round 3: unresolved architectural gap."
    )

    offering = fx.read_offering(client, env["offering_id"])
    a.assert_integer(offering["open_package_count"], 0, "open_package_count")
    a.assert_integer(offering["superseded_package_count"], 0, "superseded_package_count")

    authorizations = get_success_data(
        client.list_authorizations(
            make_csp_lead_headers(), {"package_id": env["package_id"]}
        ),
        200,
    )
    assert authorizations == []


# ---------------------------------------------------------------------------
# The two dimensions of a finding: extension granted beside awaiting verification
# ---------------------------------------------------------------------------


def test_board_extension_approval_rewrites_the_finding_deadline(client):
    """Approving a 30-day operational-requirement request re-dates the finding's deadline.

    PRD: "Approving an `OPERATIONAL_REQUIREMENT` request in the board queue sets the request's `granted_extension_days` to the `requested_extension_days` figure, copies that figure onto the finding's own `granted_extension_days`, recomputes the finding's `deadline_at` from its anchor with the extension included, moves the finding's `risk_disposition` `DEVIATION_REQUESTED → EXTENSION_GRANTED`, and recomputes the authorization's `residual_risk_score`."

    Design: Difficulty/non_linear_state_machine/poam_remediation_and_risk_disposition_dimensions_advance_independently
    """
    env = _finding_awaiting_verification_with_routed_deviation(client)

    deviation = validate_success(
        client.decide_deviation(
            env["deviation_id"],
            f.build_deviation_decision_payload("APPROVE"),
            make_board_headers(BOARD_2),
        ),
        200,
    )

    assert deviation["status"] == "APPROVED"
    assert deviation["decided_by_user_id"] == BOARD_2
    a.assert_integer(
        deviation["granted_extension_days"], 30, "deviation granted_extension_days"
    )

    item = fx.read_poam_item(client, env["finding_id"])
    assert item["risk_disposition"] == "EXTENSION_GRANTED"
    a.assert_integer(item["granted_extension_days"], 30, "granted_extension_days")
    a.assert_instant(item["deadline_at"], "2026-04-02T00:00:00Z", "deadline_at")
    assert not a.instants_equal(item["deadline_at"], "2026-03-03T00:00:00Z")


def test_extension_approval_leaves_the_remediation_dimension_awaiting_verification(
    client,
):
    """The risk-dimension approval does not touch the finding's remediation dimension.

    PRD: "Two resource types carry two orthogonal state dimensions on a single row, and a transition in one dimension never implies a transition in the other unless §3 explicitly says so."

    Design: Difficulty/non_linear_state_machine/poam_remediation_and_risk_disposition_dimensions_advance_independently
    """
    env = _finding_awaiting_verification_with_routed_deviation(client)
    before = fx.read_poam_item(client, env["finding_id"])
    assert before["remediation_status"] == "AWAITING_VERIFICATION"

    fx.decide_deviation(
        client, env, env["deviation_id"], decision="APPROVE", decider=BOARD_2
    )

    item = fx.read_poam_item(client, env["finding_id"])
    assert item["risk_disposition"] == "EXTENSION_GRANTED"
    assert item["remediation_status"] == "AWAITING_VERIFICATION"
    assert item["remediation_status"] != "CLOSED"
    assert item["closure_reason"] is None
    a.assert_integer(item["reopen_count"], 0, "reopen_count")


def test_verification_closure_keeps_the_granted_extension_disposition(client):
    """Closing the remediation dimension leaves the granted extension disposition standing.

    PRD: "`VERIFY_CLOSE` moves `AWAITING_VERIFICATION → CLOSED`, sets `closure_reason` to `REMEDIATED`, and recomputes the authorization's `open_findings_count`, `closed_findings_count` and `residual_risk_score`; it is refused with `ERR_DEVIATION_PENDING_ON_ITEM` while any deviation on the item is still in `SUBMITTED`, `BOARD_REVIEW` or `AGENCY_REVIEW`."

    Design: Difficulty/non_linear_state_machine/poam_remediation_and_risk_disposition_dimensions_advance_independently
    """
    env = _finding_awaiting_verification_with_routed_deviation(client)
    fx.decide_deviation(
        client, env, env["deviation_id"], decision="APPROVE", decider=BOARD_2
    )

    item = validate_success(
        client.advance_remediation(
            env["finding_id"],
            f.build_remediation_payload("VERIFY_CLOSE"),
            env["assessor_headers"],
        ),
        200,
    )

    assert item["remediation_status"] == "CLOSED"
    assert item["closure_reason"] == "REMEDIATED"
    assert item["risk_disposition"] == "EXTENSION_GRANTED"
    assert item["risk_disposition"] != "NONE"
    a.assert_integer(item["reopen_count"], 0, "reopen_count")
    a.assert_instant(item["deadline_at"], "2026-04-02T00:00:00Z", "deadline_at")


# ---------------------------------------------------------------------------
# The reopen leg out of closure
# ---------------------------------------------------------------------------


def test_reopening_a_closed_finding_returns_it_to_remediation_and_clears_the_closure_reason(
    client,
):
    """CLOSED is not terminal: a reopened finding goes back into remediation.

    PRD: "`REOPEN` has two legs and each increments `reopen_count` by one: from `AWAITING_VERIFICATION` it returns the item to `IN_REMEDIATION` with no other effect, and from `CLOSED` — legal only when `closure_reason` is `REMEDIATED` — it returns the item to `IN_REMEDIATION`, clears `closure_reason`, and recomputes the authorization's `open_findings_count`, `closed_findings_count` and `residual_risk_score` so the open/closed partition of §2.11 stays exact."

    Design: Difficulty/non_linear_state_machine/poam_reopen_from_closed_restores_the_open_counters_and_the_risk_score
    """
    env = _authorized_offering_with_a_closed_finding(client)
    before = fx.read_poam_item(client, env["finding_id"])
    assert before["remediation_status"] == "CLOSED"
    assert before["closure_reason"] == "REMEDIATED"
    a.assert_integer(before["reopen_count"], 0, "reopen_count before")

    item = validate_success(
        client.advance_remediation(
            env["finding_id"],
            f.build_remediation_payload("REOPEN"),
            env["assessor_headers"],
        ),
        200,
    )

    assert item["remediation_status"] == "IN_REMEDIATION"
    assert item["remediation_status"] != "CLOSED"
    assert item["closure_reason"] is None
    a.assert_integer(item["reopen_count"], 1, "reopen_count")
    a.assert_instant(item["deadline_at"], "2026-06-28T00:00:00Z", "deadline_at")


def test_reopen_moves_one_finding_from_the_closed_side_back_to_the_open_side(client):
    """The reopen shifts the authorization's finding counters without changing the total.

    PRD: "Reopening a closed finding moves one unit from the closed side to the open side, and the residual risk score is recomputed in the same request."

    Design: Difficulty/non_linear_state_machine/poam_reopen_from_closed_restores_the_open_counters_and_the_risk_score
    """
    env = _authorized_offering_with_a_closed_finding(client)
    before = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(before["open_findings_count"], 0, "open_findings_count before")
    a.assert_integer(before["closed_findings_count"], 1, "closed_findings_count before")

    fx.drive_remediation(client, env, env["finding_id"], ["REOPEN"])

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["open_findings_count"], 1, "open_findings_count")
    a.assert_integer(authorization["closed_findings_count"], 0, "closed_findings_count")
    a.assert_integer(authorization["total_findings_count"], 1, "total_findings_count")
    a.assert_finding_partition(authorization)


def test_reopened_finding_re_enters_the_residual_risk_population(client):
    """A reopened MODERATE finding scores 4.00 again, where the closed finding scored nothing.

    PRD: "The included population is the offering's findings whose `remediation_status` is `OPEN`, `IN_REMEDIATION` or `AWAITING_VERIFICATION`; a `CLOSED` finding never contributes regardless of its `closure_reason`."

    Design: Difficulty/non_linear_state_machine/poam_reopen_from_closed_restores_the_open_counters_and_the_risk_score
    """
    env = _authorized_offering_with_a_closed_finding(client)
    before = fx.read_authorization(client, env["authorization_id"])
    a.assert_money(before["residual_risk_score"], 0.00, "residual_risk_score before")
    assert before["poam_risk_tier"] == "NONE"

    fx.drive_remediation(client, env, env["finding_id"], ["REOPEN"])

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_money(authorization["residual_risk_score"], 4.00, "residual_risk_score")
    assert authorization["poam_risk_tier"] == "LOW"
    a.assert_risk_tier_matches_score(authorization)

    summary = fx.read_risk_summary(client, env["authorization_id"])
    a.assert_money(summary["residual_risk_score"], 4.00, "live residual_risk_score")
    a.assert_money(
        summary["stored_residual_risk_score"], 4.00, "stored_residual_risk_score"
    )
    a.assert_integer(summary["open_findings_count"], 1, "open_findings_count")
    assert summary["poam_risk_tier"] == "LOW"


# ---------------------------------------------------------------------------
# The one crossing: an approved false positive in the agency queue
# ---------------------------------------------------------------------------


def test_agency_false_positive_approval_closes_an_open_finding_as_false_positive(client):
    """An approved false positive closes the remediation dimension straight from OPEN.

    PRD: "Approving a `FALSE_POSITIVE` request — legal from either queue — leaves `granted_extension_days` at 0, moves the finding's `risk_disposition` `DEVIATION_REQUESTED → FALSE_POSITIVE_ACCEPTED`, and additionally drives the finding's `remediation_status` to `CLOSED` with `closure_reason` `FALSE_POSITIVE`."

    Design: Difficulty/non_linear_state_machine/false_positive_approval_in_the_agency_queue_closes_the_remediation_dimension_from_open
    """
    env = _open_finding_with_false_positive_in_the_agency_queue(client)
    before = fx.read_poam_item(client, env["finding_id"])
    assert before["remediation_status"] == "OPEN"
    assert before["risk_disposition"] == "DEVIATION_REQUESTED"

    validate_success(
        client.decide_deviation(
            env["deviation_id"],
            f.build_deviation_decision_payload("APPROVE"),
            env["agency_headers"],
        ),
        200,
    )

    item = fx.read_poam_item(client, env["finding_id"])
    assert item["risk_disposition"] == "FALSE_POSITIVE_ACCEPTED"
    assert item["remediation_status"] == "CLOSED"
    assert item["closure_reason"] == "FALSE_POSITIVE"
    assert item["closure_reason"] != "REMEDIATED"


def test_false_positive_approval_leaves_the_deadline_at_its_unextended_instant(client):
    """A false-positive approval grants no extension, so the deadline never moves.

    PRD: "At creation an item's `anchor_at` equals its `detected_at`, and its `deadline_at` is `anchor_at` advanced by the severity base allowance and then by `granted_extension_days` further days."

    Design: Difficulty/non_linear_state_machine/false_positive_approval_in_the_agency_queue_closes_the_remediation_dimension_from_open
    """
    env = _open_finding_with_false_positive_in_the_agency_queue(client)
    a.assert_instant(
        env["poam_items"]["finding"]["deadline_at"],
        "2026-05-02T00:00:00Z",
        "deadline_at at creation",
    )

    fx.decide_deviation(
        client, env, env["deviation_id"], decision="APPROVE", headers=env["agency_headers"]
    )

    item = fx.read_poam_item(client, env["finding_id"])
    a.assert_integer(item["granted_extension_days"], 0, "granted_extension_days")
    a.assert_instant(item["deadline_at"], "2026-05-02T00:00:00Z", "deadline_at")
    a.assert_integer(item["reopen_count"], 0, "reopen_count")


def test_agency_queue_decision_records_the_deciding_official_and_ends_the_request(client):
    """The sponsoring agency's official is stamped on the terminal deviation decision.

    PRD: "Deciding a routed request takes a `decision` of `APPROVE` or `DENY`, writes `decided_by_user_id`, and is terminal — `APPROVED` and `DENIED` both end the request's life."

    Design: Difficulty/non_linear_state_machine/false_positive_approval_in_the_agency_queue_closes_the_remediation_dimension_from_open
    """
    env = _open_finding_with_false_positive_in_the_agency_queue(client)

    deviation = validate_success(
        client.decide_deviation(
            env["deviation_id"],
            f.build_deviation_decision_payload("APPROVE"),
            env["agency_headers"],
        ),
        200,
    )

    assert deviation["status"] == "APPROVED"
    assert deviation["status"] != "AGENCY_REVIEW"
    assert deviation["review_queue"] == "AGENCY"
    assert deviation["decided_by_user_id"] == env["agency_id"]
    assert deviation["routed_by_user_id"] == BOARD_1
    a.assert_integer(
        deviation["granted_extension_days"], 0, "deviation granted_extension_days"
    )
