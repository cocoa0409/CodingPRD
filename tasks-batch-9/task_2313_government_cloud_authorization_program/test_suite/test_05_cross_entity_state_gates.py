"""Writes whose admissibility depends on the state of a neighbouring entity.

This file covers the three places where the program refuses a write not because
the target row is in the wrong state but because some other row is: an
authorization package waiting on its backing assessment engagement to deliver
its report, a finding's verification closure waiting on the deviation request
hanging off it to be decided, and a control implementation whose inheritance
pointer must name an offering that is already authorized. Each rule is exercised
across the moment the blocking entity moves, so the identical call is first
refused and then accepted.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Shared preconditions
# ---------------------------------------------------------------------------


def _engagement_in_testing_with_a_draft_package(client):
    """An AGENCY_SPONSORED offering in assessment: engagement in ``TESTING``
    with one 8.00 hour slot scheduled against its 200 hour pool, and a package
    sitting in ``DRAFT`` against the live offering version, with the clock at
    the authorization instant."""
    env = fx.seed_reference_data(client, clock=fx.SETUP_CLOCK)
    env = fx.seed_path_selected_offering(
        client, env, authorization_path="AGENCY_SPONSORED"
    )
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env, contracted_hours=200.00, labor_cost_usd=120000.00)
    env = fx.seed_test_slot(client, env, hours=8.00, family_code="AC")
    fx.set_clock(client, fx.AUTHORIZATION_CLOCK)
    env["clock_set_to"] = fx.AUTHORIZATION_CLOCK
    env = fx.seed_package(client, env)
    return env


def _finding_awaiting_verification_under_an_agency_deviation(client):
    """A MODERATE finding detected 2026-02-01, driven to
    ``AWAITING_VERIFICATION``, carrying a ``RISK_ADJUSTMENT`` deviation request
    routed into the agency queue."""
    env = fx.seed_reference_data(client, clock=fx.SETUP_CLOCK)
    env = fx.seed_path_selected_offering(
        client, env, authorization_path="AGENCY_SPONSORED"
    )
    env = fx.seed_engagement(client, env, submit_plan=False)
    env = fx.seed_poam_item(
        client, env, severity="MODERATE", detected_at=fx.SETUP_CLOCK, control_id="AC-2"
    )
    fx.drive_remediation(client, env, env["poam_id"], ["START", "SUBMIT_EVIDENCE"])
    env = fx.seed_deviation(
        client,
        env,
        env["poam_id"],
        kind="RISK_ADJUSTMENT",
        review_queue="AGENCY",
    )
    return env


def _authorized_offering_beside_a_draft_and_an_inheritance_target(client):
    """One lead holding three offerings: ``GovCloud Compute`` AUTHORIZED at
    2026-03-30, ``GovCloud Analytics`` still in DRAFT, and ``GovCloud Storage``
    as the offering that wants to inherit a control."""
    env = fx.seed_authorized_offering(client)
    env = fx.seed_draft_offering(client, env, name="GovCloud Analytics", key="offering_c")
    env = fx.seed_draft_offering(client, env, name="GovCloud Storage", key="offering_b")
    return env


def _inheriting_payload(env, source_key):
    """The one control-implementation payload both inheritance calls send,
    differing only in which offering the control is inherited from."""
    return f.build_control_implementation_payload(
        env["offering_b_id"],
        control_id="AC-17",
        family_code="AC",
        implementation_status="IMPLEMENTED",
        crm_documented=True,
        inherited_from_offering_id=env[f"{source_key}_id"],
    )


# ---------------------------------------------------------------------------
# The package gate on its backing engagement
# ---------------------------------------------------------------------------


def test_package_submit_is_refused_while_its_backing_engagement_is_still_testing(client):
    """A package cannot be submitted while the engagement backing it is still testing.

    PRD: "It is performed by the offering's owning compliance lead on a package in `DRAFT` or `REVISION_REQUESTED`, and it enforces, in the order given by §2.7: the backing engagement must be in `REPORT_DELIVERED`, else `ERR_ENGAGEMENT_REPORT_NOT_DELIVERED`; customer-responsibility-matrix coverage computed as in §3.4 must be at least 90.00 percent, else `ERR_CRM_COVERAGE_INSUFFICIENT`; the submission-variant residual risk score must be strictly below 50.00, else `ERR_RESIDUAL_RISK_TOO_HIGH`; no finding of the offering may be `HIGH` severity, not `CLOSED`, and already at or past its deadline as of the submission instant, else `ERR_OVERDUE_HIGH_FINDINGS`; and the engagement's `total_cost_usd` must not exceed the offering's `assessment_budget_usd`, else `ERR_ASSESSMENT_BUDGET_EXCEEDED`."

    Design: Difficulty/cross_entity_state_dependency/package_submit_waits_for_the_engagement_to_reach_report_delivered
    """
    env = _engagement_in_testing_with_a_draft_package(client)

    assert fx.read_engagement(client, env["engagement_id"])["status"] == "TESTING"
    assert fx.read_package(client, env["package_id"])["status"] == "DRAFT"

    response = client.submit_package(env["package_id"], env["lead_headers"])
    validate_error(response, err.ERR_ENGAGEMENT_REPORT_NOT_DELIVERED, 409)

    package = fx.read_package(client, env["package_id"])
    assert package["status"] == "DRAFT"
    a.assert_integer(package["submission_round"], 0, "submission_round")
    assert package["submitted_at"] is None
    assert fx.read_offering(client, env["offering_id"])["status"] == "IN_ASSESSMENT"


def test_report_delivery_completes_the_scheduled_slot_without_returning_its_hours(client):
    """Delivering the report moves the engagement on and completes its scheduled slot.

    PRD: "On success the engagement moves `TESTING → REPORT_DELIVERED`; one plan-of-action item is opened per findings element with `source` `ASSESSMENT`, its `anchor_at` set to its `detected_at` and its deadline computed as described in §3.6; `findings_reported_count` is set to the number of items created; and every slot of the engagement still in `SCHEDULED` moves `SCHEDULED → COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/package_submit_waits_for_the_engagement_to_reach_report_delivered
    """
    env = _engagement_in_testing_with_a_draft_package(client)

    env = fx.seed_report_delivered(client, env, findings=[], ensure_slot=False)

    engagement = fx.read_engagement(client, env["engagement_id"])
    assert engagement["status"] == "REPORT_DELIVERED"
    a.assert_integer(engagement["findings_reported_count"], 0, "findings_reported_count")

    slots = fx.list_test_slots(client, env["engagement_id"])
    slot = next(row for row in slots if row["id"] == env["slot_id"])
    assert slot["status"] == "COMPLETED"

    a.assert_money(engagement["allocated_hours"], 8.00, "allocated_hours")
    a.assert_money(engagement["unallocated_hours"], 192.00, "unallocated_hours")
    assert float(engagement["unallocated_hours"]) != 200.00
    a.assert_hour_conservation(engagement)


def test_package_submit_stamps_the_clock_once_the_engagement_report_is_delivered(client):
    """The identical submit call is accepted after the engagement delivers its report.

    PRD: "`submitted_at` is set to the logical clock and `submission_round` increments by one."

    Design: Difficulty/cross_entity_state_dependency/package_submit_waits_for_the_engagement_to_reach_report_delivered
    """
    env = _engagement_in_testing_with_a_draft_package(client)

    refused = client.submit_package(env["package_id"], env["lead_headers"])
    validate_error(refused, err.ERR_ENGAGEMENT_REPORT_NOT_DELIVERED, 409)

    env = fx.seed_report_delivered(client, env, findings=[], ensure_slot=False)

    accepted = client.submit_package(env["package_id"], env["lead_headers"])
    package = validate_success(accepted, 200)

    assert package["status"] == "SUBMITTED"
    a.assert_integer(package["submission_round"], 1, "submission_round")
    a.assert_instant(package["submitted_at"], fx.AUTHORIZATION_CLOCK, "submitted_at")
    assert fx.read_offering(client, env["offering_id"])["status"] == "PACKAGE_SUBMITTED"


def test_package_submission_freezes_coverage_risk_and_open_findings(client):
    """Submission freezes the three decision figures onto the package.

    PRD: "Three figures are frozen onto the package at that instant and never move again: `crm_coverage_pct` from the coverage computation, `residual_risk_score_at_submission` from the submission variant of the risk score, and `open_findings_at_submission` as the count of the offering's findings whose `remediation_status` is not `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/package_submit_waits_for_the_engagement_to_reach_report_delivered
    """
    env = _engagement_in_testing_with_a_draft_package(client)
    env = fx.seed_report_delivered(client, env, findings=[], ensure_slot=False)

    package = validate_success(
        client.submit_package(env["package_id"], env["lead_headers"]), 200
    )

    a.assert_money(package["crm_coverage_pct"], 100.00, "crm_coverage_pct")
    a.assert_money(
        package["residual_risk_score_at_submission"],
        0.00,
        "residual_risk_score_at_submission",
    )
    a.assert_integer(
        package["open_findings_at_submission"], 0, "open_findings_at_submission"
    )


# ---------------------------------------------------------------------------
# The verification-closure gate on the finding's deviation request
# ---------------------------------------------------------------------------


def test_verify_close_is_refused_while_the_agency_deviation_is_undecided(client):
    """A finding cannot be verified closed while a deviation on it sits in agency review.

    PRD: "`VERIFY_CLOSE` moves `AWAITING_VERIFICATION → CLOSED`, sets `closure_reason` to `REMEDIATED`, and recomputes the authorization's `open_findings_count`, `closed_findings_count` and `residual_risk_score`; it is refused with `ERR_DEVIATION_PENDING_ON_ITEM` while any deviation on the item is still in `SUBMITTED`, `BOARD_REVIEW` or `AGENCY_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/verify_close_waits_for_the_pending_deviation_to_be_decided
    """
    env = _finding_awaiting_verification_under_an_agency_deviation(client)

    assert fx.read_deviation(client, env["deviation_id"])["status"] == "AGENCY_REVIEW"
    item = fx.read_poam_item(client, env["poam_id"])
    assert item["remediation_status"] == "AWAITING_VERIFICATION"
    assert item["risk_disposition"] == "DEVIATION_REQUESTED"

    response = client.advance_remediation(
        env["poam_id"],
        f.build_remediation_payload("VERIFY_CLOSE"),
        env["assessor_headers"],
    )
    validate_error(response, err.ERR_DEVIATION_PENDING_ON_ITEM, 409)

    item = fx.read_poam_item(client, env["poam_id"])
    assert item["remediation_status"] == "AWAITING_VERIFICATION"
    assert item["closure_reason"] is None


def test_denying_the_deviation_clears_the_risk_disposition_without_moving_the_deadline(
    client,
):
    """Denying the deviation returns the finding's risk dimension to no disposition.

    PRD: "Denying a request from either queue returns the finding's `risk_disposition` to `NONE`, resets its `granted_extension_days` to 0, recomputes its `deadline_at` without any extension, and recomputes the authorization's `residual_risk_score`."

    Design: Difficulty/cross_entity_state_dependency/verify_close_waits_for_the_pending_deviation_to_be_decided
    """
    env = _finding_awaiting_verification_under_an_agency_deviation(client)

    deviation = fx.decide_deviation(
        client, env, env["deviation_id"], decision="DENY", headers=env["agency_headers"]
    )
    assert deviation["status"] == "DENIED"
    assert deviation["decided_by_user_id"] == env["agency_id"]

    item = fx.read_poam_item(client, env["poam_id"])
    assert item["risk_disposition"] == "NONE"
    assert item["risk_disposition"] != "RISK_ACCEPTED"
    a.assert_integer(item["granted_extension_days"], 0, "granted_extension_days")
    a.assert_instant(
        item["deadline_at"],
        a.expected_deadline(fx.SETUP_CLOCK, "MODERATE"),
        "deadline_at",
    )
    assert item["remediation_status"] == "AWAITING_VERIFICATION"


def test_verify_close_closes_the_finding_once_the_deviation_is_denied(client):
    """The identical verification closure is accepted once no deviation is pending.

    PRD: "`VERIFY_CLOSE` moves `AWAITING_VERIFICATION → CLOSED`, sets `closure_reason` to `REMEDIATED`, and recomputes the authorization's `open_findings_count`, `closed_findings_count` and `residual_risk_score`; it is refused with `ERR_DEVIATION_PENDING_ON_ITEM` while any deviation on the item is still in `SUBMITTED`, `BOARD_REVIEW` or `AGENCY_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/verify_close_waits_for_the_pending_deviation_to_be_decided
    """
    env = _finding_awaiting_verification_under_an_agency_deviation(client)

    refused = client.advance_remediation(
        env["poam_id"],
        f.build_remediation_payload("VERIFY_CLOSE"),
        env["assessor_headers"],
    )
    validate_error(refused, err.ERR_DEVIATION_PENDING_ON_ITEM, 409)

    fx.decide_deviation(
        client, env, env["deviation_id"], decision="DENY", headers=env["agency_headers"]
    )

    accepted = client.advance_remediation(
        env["poam_id"],
        f.build_remediation_payload("VERIFY_CLOSE"),
        env["assessor_headers"],
    )
    item = validate_success(accepted, 200)

    assert item["remediation_status"] == "CLOSED"
    assert item["closure_reason"] == "REMEDIATED"
    assert item["closure_reason"] != "FALSE_POSITIVE"
    a.assert_integer(item["reopen_count"], 0, "reopen_count")


# ---------------------------------------------------------------------------
# The inheritance gate on the source offering
# ---------------------------------------------------------------------------


def test_inherited_control_is_refused_when_its_source_offering_is_still_draft(client):
    """A control may not be inherited from an offering that is not yet authorized.

    PRD: "Inheritance is only legal from an offering whose `status` is `AUTHORIZED`; pointing at an offering in any other status is refused with `ERR_INHERITED_OFFERING_NOT_AUTHORIZED`, both when the implementation row is created and when it is later updated."

    Design: Difficulty/cross_entity_state_dependency/inherited_control_requires_its_source_offering_to_be_authorized
    """
    env = _authorized_offering_beside_a_draft_and_an_inheritance_target(client)

    assert fx.read_offering(client, env["offering_c_id"])["status"] == "DRAFT"
    assert fx.read_offering(client, env["offering_id"])["status"] == "AUTHORIZED"

    response = client.create_control_implementation(
        _inheriting_payload(env, "offering_c"), env["lead_headers"]
    )
    validate_error(response, err.ERR_INHERITED_OFFERING_NOT_AUTHORIZED, 409)

    rows, meta = validate_paginated(
        client.list_control_implementations(
            env["lead_headers"], {"offering_id": env["offering_b_id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_inherited_control_is_accepted_from_an_authorized_source_offering(client):
    """The same payload is accepted once its inheritance pointer names the authorized offering.

    PRD: "Supplying `inherited_from_offering_id` names the already-authorized offering the control is inherited from; leaving it null (the default) marks the control as directly implemented."

    Design: Difficulty/cross_entity_state_dependency/inherited_control_requires_its_source_offering_to_be_authorized
    """
    env = _authorized_offering_beside_a_draft_and_an_inheritance_target(client)

    refused = client.create_control_implementation(
        _inheriting_payload(env, "offering_c"), env["lead_headers"]
    )
    validate_error(refused, err.ERR_INHERITED_OFFERING_NOT_AUTHORIZED, 409)

    accepted = client.create_control_implementation(
        _inheriting_payload(env, "offering"), env["lead_headers"]
    )
    row = validate_success(accepted, 201)

    assert row["inherited_from_offering_id"] == env["offering_id"]
    assert row["inherited_from_offering_id"] != env["offering_c_id"]
    assert row["offering_id"] == env["offering_b_id"]
    assert row["control_id"] == "AC-17"


def test_authorized_source_offering_lists_the_single_control_inheriting_from_it(client):
    """The inheritance filter returns exactly the one control drawn from the authorized offering.

    PRD: "Implementations are listed with filters on `offering_id`, `inherited_from_offering_id`, `family_code`, `implementation_status` and `crm_documented`."

    Design: Difficulty/cross_entity_state_dependency/inherited_control_requires_its_source_offering_to_be_authorized
    """
    env = _authorized_offering_beside_a_draft_and_an_inheritance_target(client)

    row = validate_success(
        client.create_control_implementation(
            _inheriting_payload(env, "offering"), env["lead_headers"]
        ),
        201,
    )

    rows, meta = validate_paginated(
        client.list_control_implementations(
            env["lead_headers"], {"inherited_from_offering_id": env["offering_id"]}
        )
    )
    assert a.ids_of(rows) == [row["id"]]
    assert meta["total_count"] == 1
