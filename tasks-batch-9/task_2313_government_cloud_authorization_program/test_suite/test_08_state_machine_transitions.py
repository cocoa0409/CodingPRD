"""State-machine behaviour of the program API.

These tests exercise the transition tables themselves: the state a freshly
created row opens in, the legal legs of the assessment-plan revision loop, the
change-request decision fork, the reuse-grant incremental-review self-loop, and
the two ways a wrong from-state is reported — ``ERR_INVALID_STATE`` for most
operations and ``ERR_ALREADY_TERMINAL`` for the five operations PRD 2.7 lists at
tier 12.
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
from test_helpers.test_users import (
    BOARD_2,
    BOARD_HEADERS,
    CSP_LEAD_1,
    CSP_LEAD_HEADERS,
    make_board_headers,
)

#: The clock the whole file works at unless a test moves it on.
SETUP_CLOCK = fx.SETUP_CLOCK
AUTHORIZATION_CLOCK = fx.AUTHORIZATION_CLOCK


def _category_row(client, offering_id, category_code):
    """The offering's data category carrying ``category_code``, read back live."""
    rows, _meta = validate_paginated(
        client.list_data_categories(offering_id, CSP_LEAD_HEADERS)
    )
    matches = [row for row in rows if row["category_code"] == category_code]
    assert matches, f"no data category {category_code} on offering {offering_id}"
    return matches[0]


# ---------------------------------------------------------------------------
# Initial states
# ---------------------------------------------------------------------------


def test_a_new_engagement_opens_in_draft_with_an_empty_hour_ledger(client):
    """A newly created assessment engagement opens in DRAFT with a zeroed ledger.

    PRD: "The engagement opens in status `DRAFT` with `plan_revision_round` and `findings_reported_count` at 0, `planned_test_start` and `planned_test_end` null, `allocated_hours` at 0 and `unallocated_hours` equal to `contracted_hours`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_categorized_offering(client, env)

    engagement = validate_success(
        client.create_engagement(
            f.build_engagement_payload(
                env["offering_id"], contracted_hours=200.00, labor_cost_usd=120000.00
            ),
            env["lead_headers"],
        ),
        201,
    )

    assert engagement["status"] == "DRAFT"
    a.assert_integer(engagement["plan_revision_round"], 0, "plan_revision_round")
    a.assert_integer(engagement["findings_reported_count"], 0, "findings_reported_count")
    assert engagement["planned_test_start"] is None
    assert engagement["planned_test_end"] is None
    a.assert_money(engagement["allocated_hours"], 0.00, "allocated_hours")
    a.assert_money(engagement["unallocated_hours"], 200.00, "unallocated_hours")
    a.assert_hour_conservation(engagement)
    # The MODERATE offering pays the 0.06 surcharge tier on labor alone and no
    # hour overage, because 200 contracted hours sit inside the 900 allowance.
    a.assert_engagement_costs(engagement, 120000.00, 200.00, "MODERATE")
    a.assert_money(engagement["program_surcharge_usd"], 7200.00, "program_surcharge_usd")
    a.assert_money(engagement["total_cost_usd"], 127200.00, "total_cost_usd")


def test_a_fresh_offering_opens_in_draft_with_no_impact_levels_or_baseline(client):
    """A newly registered offering opens in DRAFT with every derived field null.

    PRD: "A fresh offering has `authorization_path`, `sponsor_agency_id`, `baseline_id`, `preliminary_impact_level` and `final_impact_level` all null, `boundary_version` at 1, and `included_service_count`, `open_package_count` and `superseded_package_count` all at 0."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    fx.seed_reference_data(client, clock=SETUP_CLOCK)

    offering = validate_success(
        client.create_offering(
            f.build_offering_payload(name="GovCloud Object Store"), CSP_LEAD_HEADERS
        ),
        201,
    )

    assert offering["status"] == "DRAFT"
    assert offering["owner_user_id"] == CSP_LEAD_1
    assert offering["authorization_path"] is None
    assert offering["sponsor_agency_id"] is None
    assert offering["baseline_id"] is None
    assert offering["preliminary_impact_level"] is None
    assert offering["final_impact_level"] is None
    a.assert_integer(offering["boundary_version"], 1, "boundary_version")
    a.assert_integer(offering["included_service_count"], 0, "included_service_count")
    a.assert_integer(offering["open_package_count"], 0, "open_package_count")
    a.assert_integer(offering["superseded_package_count"], 0, "superseded_package_count")
    a.assert_integer(offering["version"], 1, "version")
    a.assert_audit_triplet(offering, "offering")


def test_a_declared_category_opens_declared_and_lifts_only_the_preliminary_level(client):
    """A declared data category opens DECLARED and lifts only the preliminary level.

    PRD: "The server attaches `offering_id` from the creation path, sets the category's `status` to `DECLARED`, and leaves `confirmed_by_user_id` null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_draft_offering(client, env, name="GovCloud Object Store")

    category = validate_success(
        client.create_data_category(
            env["offering_id"],
            f.build_data_category_payload(
                category_code="PII",
                confidentiality_impact="MODERATE",
                integrity_impact="MODERATE",
                availability_impact="LOW",
            ),
            env["lead_headers"],
        ),
        201,
    )

    assert category["status"] == "DECLARED"
    assert category["offering_id"] == env["offering_id"]
    assert category["confirmed_by_user_id"] is None

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "DRAFT"
    assert offering["preliminary_impact_level"] == "MODERATE"
    assert offering["final_impact_level"] is None
    assert offering["baseline_id"] is None
    # create 1 + the preliminary high-water-mark refresh the declaration forces 2.
    a.assert_integer(offering["version"], 2, "offering version")


def test_a_new_finding_initialises_both_of_its_status_dimensions(client):
    """A newly filed finding initialises its remediation and risk dimensions apart.

    PRD: "Every new item opens with `remediation_status` `OPEN`, `risk_disposition` `NONE`, `closure_reason` null, `granted_extension_days` 0 and `reopen_count` 0."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_draft_offering(client, env, name="GovCloud Object Store")

    item = validate_success(
        client.create_poam_item(
            f.build_poam_item_payload(
                env["offering_id"],
                control_id="AC-2",
                severity="MODERATE",
                detected_at=SETUP_CLOCK,
                source="SELF_IDENTIFIED",
            ),
            env["lead_headers"],
        ),
        201,
    )

    assert item["remediation_status"] == "OPEN"
    assert item["risk_disposition"] == "NONE"
    assert item["closure_reason"] is None
    a.assert_integer(item["granted_extension_days"], 0, "granted_extension_days")
    a.assert_integer(item["reopen_count"], 0, "reopen_count")
    a.assert_instant(item["anchor_at"], SETUP_CLOCK, "anchor_at")
    a.assert_instant(
        item["deadline_at"],
        a.expected_deadline(SETUP_CLOCK, "MODERATE"),
        "deadline_at",
    )
    a.assert_instant(item["deadline_at"], "2026-05-02T00:00:00Z", "deadline_at")


# ---------------------------------------------------------------------------
# The assessment-plan revision loop
# ---------------------------------------------------------------------------


def test_plan_rejection_returns_the_engagement_to_draft_and_clears_the_window(client):
    """Rejecting the assessment plan walks the engagement back to DRAFT.

    PRD: "A `REJECT` is the revision loop: the engagement returns `PLAN_SUBMITTED → DRAFT`, `plan_revision_round` increments by one, and both `planned_test_start` and `planned_test_end` are cleared so the assessor must restate the window."

    Design: Corner/state_machines/plan_rejection_walks_the_engagement_back_to_draft_and_clears_the_window
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env, approve_plan=False)
    assert env["engagement"]["status"] == "PLAN_SUBMITTED"

    engagement = validate_success(
        client.decide_plan(
            env["engagement_id"],
            f.build_plan_decision_payload("REJECT"),
            env["agency_headers"],
        ),
        200,
    )

    assert engagement["status"] == "DRAFT"
    a.assert_integer(engagement["plan_revision_round"], 1, "plan_revision_round")
    assert engagement["planned_test_start"] is None
    assert engagement["planned_test_end"] is None

    # The rejection is a loop on the engagement alone: the offering does not
    # bubble up and its version does not move.
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "PATH_SELECTED"
    # create 1 + category 2 + confirm 3 + determination 4 + path selection 5.
    a.assert_integer(offering["version"], 5, "offering version")

    agency = fx.read_agency(client, env["agency_id"])
    a.assert_integer(agency["sponsored_offering_count"], 1, "sponsored_offering_count")
    a.assert_integer(agency["version"], 2, "agency version")


def test_the_second_plan_restates_the_window_without_a_further_revision_round(client):
    """After a rejection the assessor may restate a different testing window.

    PRD: "It writes both instants and moves the engagement `DRAFT → PLAN_SUBMITTED`."

    Design: Corner/state_machines/plan_rejection_walks_the_engagement_back_to_draft_and_clears_the_window
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env, approve_plan=False)
    validate_success(
        client.decide_plan(
            env["engagement_id"],
            f.build_plan_decision_payload("REJECT"),
            env["agency_headers"],
        ),
        200,
    )

    engagement = validate_success(
        client.submit_plan(
            env["engagement_id"],
            f.build_plan_payload("2026-03-05T00:00:00Z", "2026-03-25T00:00:00Z"),
            env["assessor_headers"],
        ),
        200,
    )

    assert engagement["status"] == "PLAN_SUBMITTED"
    a.assert_instant(
        engagement["planned_test_start"], "2026-03-05T00:00:00Z", "planned_test_start"
    )
    a.assert_instant(
        engagement["planned_test_end"], "2026-03-25T00:00:00Z", "planned_test_end"
    )
    # Restating the window is not itself a revision: the round stays at 1.
    a.assert_integer(engagement["plan_revision_round"], 1, "plan_revision_round")

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "PATH_SELECTED"
    a.assert_integer(offering["version"], 5, "offering version")


def test_plan_approval_bubbles_the_offering_up_to_in_assessment(client):
    """Approving the resubmitted plan drives the offering into IN_ASSESSMENT.

    PRD: "An `APPROVE` moves the engagement `PLAN_SUBMITTED → PLAN_APPROVED` and, as a bubble-up, drives the offering `PATH_SELECTED → IN_ASSESSMENT` and increments the offering's `version` by one; the offering must be in `PATH_SELECTED` and the engagement must belong to it."

    Design: Corner/state_machines/plan_rejection_walks_the_engagement_back_to_draft_and_clears_the_window
    """
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env, approve_plan=False)
    validate_success(
        client.decide_plan(
            env["engagement_id"],
            f.build_plan_decision_payload("REJECT"),
            env["agency_headers"],
        ),
        200,
    )
    validate_success(
        client.submit_plan(
            env["engagement_id"],
            f.build_plan_payload("2026-03-05T00:00:00Z", "2026-03-25T00:00:00Z"),
            env["assessor_headers"],
        ),
        200,
    )

    engagement = validate_success(
        client.decide_plan(
            env["engagement_id"],
            f.build_plan_decision_payload("APPROVE"),
            env["agency_headers"],
        ),
        200,
    )

    assert engagement["status"] == "PLAN_APPROVED"
    a.assert_money(engagement["allocated_hours"], 0.00, "allocated_hours")
    a.assert_integer(engagement["plan_revision_round"], 1, "plan_revision_round")

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "IN_ASSESSMENT"
    # The plan loop added nothing; only the approval bubble-up moves 5 -> 6.
    a.assert_integer(offering["version"], 6, "offering version")


# ---------------------------------------------------------------------------
# Review-side triggers on a package that has not been submitted
# ---------------------------------------------------------------------------


def _draft_package_env(client):
    """A package in DRAFT behind a REPORT_DELIVERED engagement with no findings."""
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_report_delivered(client, env, report_at=AUTHORIZATION_CLOCK)
    env = fx.seed_package(client, env)
    assert env["package"]["status"] == "DRAFT"
    return env


def test_taking_a_draft_package_into_review_is_refused_as_invalid_state(client):
    """A package that has not been submitted cannot be taken into program review.

    PRD: "A `ProgramBoardReviewer` first takes a `SUBMITTED` package into review, moving it `SUBMITTED → UNDER_REVIEW` and stamping `reviewed_by_user_id` from their own `X-User-ID`."

    Design: Corner/state_machines/package_review_and_decision_before_submission_are_invalid_state
    """
    env = _draft_package_env(client)

    validate_error(
        client.review_package(env["package_id"], BOARD_HEADERS),
        err.ERR_INVALID_STATE,
        409,
    )

    package = fx.read_package(client, env["package_id"])
    assert package["status"] == "DRAFT"
    a.assert_integer(package["submission_round"], 0, "submission_round")
    assert package["submitted_at"] is None
    assert package["reviewed_by_user_id"] is None
    assert package["letter_reference"] is None


def test_requesting_revision_on_a_draft_package_is_refused_as_invalid_state(client):
    """A revision request is only legal from UNDER_REVIEW, never from DRAFT.

    PRD: "From `UNDER_REVIEW` the reviewer may send the package back with a `revision_note`: when `submission_round` is below 3 the package moves `UNDER_REVIEW → REVISION_REQUESTED` and the note is written, which is the cycle back into resubmission."

    Design: Corner/state_machines/package_review_and_decision_before_submission_are_invalid_state
    """
    env = _draft_package_env(client)

    validate_error(
        client.request_package_revision(
            env["package_id"], f.build_revision_request_payload("Too early."), BOARD_HEADERS
        ),
        err.ERR_INVALID_STATE,
        409,
    )

    package = fx.read_package(client, env["package_id"])
    assert package["status"] == "DRAFT"
    assert package["revision_note"] is None
    a.assert_integer(package["submission_round"], 0, "submission_round")

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "IN_ASSESSMENT"
    a.assert_integer(offering["open_package_count"], 1, "open_package_count")


def test_deciding_a_draft_package_is_refused_and_mints_no_authorization(client):
    """The authorization decision is refused on a DRAFT package and creates nothing.

    PRD: "The package must be `UNDER_REVIEW`."

    Design: Corner/state_machines/package_review_and_decision_before_submission_are_invalid_state
    """
    env = _draft_package_env(client)

    validate_error(
        client.decide_package(
            env["package_id"],
            f.build_package_decision_payload("AUTHORIZE"),
            env["agency_headers"],
        ),
        err.ERR_INVALID_STATE,
        409,
    )

    package = fx.read_package(client, env["package_id"])
    assert package["status"] == "DRAFT"
    assert package["letter_reference"] is None

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "IN_ASSESSMENT"

    _rows, meta = validate_paginated(
        client.list_authorizations(CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]})
    )
    a.assert_integer(meta["total_count"], 0, "authorizations total_count")


def test_the_same_review_succeeds_once_the_package_is_submitted(client):
    """The review that was refused from DRAFT succeeds once the package is SUBMITTED.

    PRD: "A `ProgramBoardReviewer` first takes a `SUBMITTED` package into review, moving it `SUBMITTED → UNDER_REVIEW` and stamping `reviewed_by_user_id` from their own `X-User-ID`."

    Design: Corner/state_machines/package_review_and_decision_before_submission_are_invalid_state
    """
    env = _draft_package_env(client)
    validate_error(
        client.review_package(env["package_id"], BOARD_HEADERS),
        err.ERR_INVALID_STATE,
        409,
    )

    submitted = validate_success(
        client.submit_package(env["package_id"], env["lead_headers"]), 200
    )
    assert submitted["status"] == "SUBMITTED"
    a.assert_integer(submitted["submission_round"], 1, "submission_round")
    a.assert_instant(submitted["submitted_at"], AUTHORIZATION_CLOCK, "submitted_at")
    a.assert_money(submitted["crm_coverage_pct"], 100.00, "crm_coverage_pct")
    a.assert_money(
        submitted["residual_risk_score_at_submission"],
        0.00,
        "residual_risk_score_at_submission",
    )
    a.assert_integer(
        submitted["open_findings_at_submission"], 0, "open_findings_at_submission"
    )

    reviewed = validate_success(
        client.review_package(env["package_id"], BOARD_HEADERS), 200
    )
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["reviewed_by_user_id"] == "board-1"


# ---------------------------------------------------------------------------
# A revoked reuse grant is sealed
# ---------------------------------------------------------------------------


def _revoked_grant_env(client):
    """A live authorization whose EPA reuse grant has already been revoked."""
    env = fx.seed_authorized_offering(client)
    env = fx.add_agency(
        client,
        env,
        name="Environmental Protection Agency",
        agency_code="EPA",
        key="epa",
    )
    env = fx.seed_reuse_grant(
        client,
        env,
        agency_id=env["epa_id"],
        agency_headers=env["epa_headers"],
        advance_to="PACKAGE_ACCESS_GRANTED",
    )
    env["grant"] = validate_success(
        client.revoke_reuse_grant(
            env["grant_id"], f.build_revoke_payload("AGENCY_REQUEST"), env["epa_headers"]
        ),
        200,
    )
    assert env["grant"]["access_state"] == "REVOKED"
    return env


def test_revoking_an_already_revoked_grant_reports_already_terminal(client):
    """A second revocation of the same reuse grant is refused as already terminal.

    PRD: "A grant may be revoked at any point before it is already revoked, by either the grant's own agency official or a `ProgramBoardReviewer`; a grant already in `REVOKED` is refused with `ERR_ALREADY_TERMINAL`, and an agency official acting on a grant that is not their agency's is refused with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/state_machines/a_revoked_reuse_grant_refuses_every_further_transition
    """
    env = _revoked_grant_env(client)

    validate_error(
        client.revoke_reuse_grant(
            env["grant_id"],
            f.build_revoke_payload("POSTURE_ESCALATION"),
            env["epa_headers"],
        ),
        err.ERR_ALREADY_TERMINAL,
        409,
    )

    grant = fx.read_reuse_grant(client, env["grant_id"])
    assert grant["access_state"] == "REVOKED"
    # The refused second revoke wrote nothing: the original reason stands.
    assert grant["revoked_reason"] == "AGENCY_REQUEST"
    assert grant["revoked_reason"] != "POSTURE_ESCALATION"
    assert grant["reuse_accepted_at"] is None
    a.assert_integer(grant["notice_count"], 0, "notice_count")

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 0, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 5, "reuse_seats_available")
    a.assert_seat_conservation(authorization)

    agency = fx.read_agency(client, env["epa_id"])
    a.assert_integer(agency["reuse_grant_count"], 0, "reuse_grant_count")
    a.assert_integer(agency["open_notice_count"], 0, "open_notice_count")


def test_incremental_review_on_a_revoked_grant_is_refused_as_invalid_state(client):
    """An incremental review on a revoked grant reports a wrong from-state.

    PRD: "An `ACCEPT` decision is legal from `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW` or `NOTICE_ISSUED`, requires the supplied `findings_count` to be no more than 5 — more than that is refused with `ERR_INCREMENTAL_FINDINGS_EXCEED_TOLERANCE` — and requires the authorization to still be in `authorization_status` `AUTHORIZED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`."

    Design: Corner/state_machines/a_revoked_reuse_grant_refuses_every_further_transition
    """
    env = _revoked_grant_env(client)

    validate_error(
        client.record_incremental_review(
            env["grant_id"],
            f.build_incremental_review_payload("ACCEPT", 0),
            env["epa_headers"],
        ),
        err.ERR_INVALID_STATE,
        409,
    )

    grant = fx.read_reuse_grant(client, env["grant_id"])
    assert grant["access_state"] == "REVOKED"
    assert grant["reuse_accepted_at"] is None
    a.assert_integer(
        grant["incremental_review_findings_count"],
        0,
        "incremental_review_findings_count",
    )


def test_granting_package_access_on_a_revoked_grant_is_refused_as_invalid_state(client):
    """Package access cannot be granted on a revoked reuse grant.

    PRD: "The offering's owning compliance lead grants package access, moving the grant `REQUESTED → PACKAGE_ACCESS_GRANTED`, which is what makes the authorization package readable to the grantee agency under the access rule of §2.1; the acting `X-User-ID` must equal the offering's `owner_user_id`."

    Design: Corner/state_machines/a_revoked_reuse_grant_refuses_every_further_transition
    """
    env = _revoked_grant_env(client)

    validate_error(
        client.grant_package_access(env["grant_id"], env["lead_headers"]),
        err.ERR_INVALID_STATE,
        409,
    )

    grant = fx.read_reuse_grant(client, env["grant_id"])
    assert grant["access_state"] == "REVOKED"
    assert grant["revoked_reason"] == "AGENCY_REQUEST"

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 0, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 5, "reuse_seats_available")


# ---------------------------------------------------------------------------
# Categorization review is not idempotent
# ---------------------------------------------------------------------------


def _confirmed_category_env(client):
    """A DRAFT offering holding one CONFIRMED PII category, confirmed by board-1."""
    env = fx.seed_reference_data(client, clock=SETUP_CLOCK)
    env = fx.seed_draft_offering(client, env)
    env = fx.declare_categories(client, env)
    env["category_id"] = env["data_categories"]["PII"]["id"]
    assert env["data_categories"]["PII"]["status"] == "CONFIRMED"
    return env


def test_replaying_confirm_on_a_confirmed_category_is_refused_as_invalid_state(client):
    """Confirming an already CONFIRMED data category is refused, and rewrites nothing.

    PRD: "Both legs require the category to still be `DECLARED` and the parent offering to still be in `DRAFT`, both write `confirmed_by_user_id` from the reviewer's `X-User-ID`, and both recompute the offering's `preliminary_impact_level` and increment the offering's `version` by one."

    Design: Corner/state_machines/confirming_a_data_category_twice_is_an_invalid_state
    """
    env = _confirmed_category_env(client)

    validate_error(
        client.confirm_data_category(
            env["category_id"],
            f.build_category_decision_payload("CONFIRM"),
            make_board_headers(BOARD_2),
        ),
        err.ERR_INVALID_STATE,
        409,
    )

    category = _category_row(client, env["offering_id"], "PII")
    assert category["status"] == "CONFIRMED"
    # The reviewer identity of the original confirmation is not overwritten.
    assert category["confirmed_by_user_id"] == "board-1"
    assert category["confirmed_by_user_id"] != BOARD_2

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "DRAFT"
    assert offering["preliminary_impact_level"] == "MODERATE"
    assert offering["final_impact_level"] is None
    # create 1 + category 2 + confirm 3; the refused replay recomputes nothing.
    a.assert_integer(offering["version"], 3, "offering version")


def test_withdrawing_an_already_confirmed_category_is_refused_as_invalid_state(client):
    """WITHDRAW is legal only from DECLARED, so it is refused after a confirmation.

    PRD: "Both legs require the category to still be `DECLARED` and the parent offering to still be in `DRAFT`, both write `confirmed_by_user_id` from the reviewer's `X-User-ID`, and both recompute the offering's `preliminary_impact_level` and increment the offering's `version` by one."

    Design: Corner/state_machines/confirming_a_data_category_twice_is_an_invalid_state
    """
    env = _confirmed_category_env(client)

    validate_error(
        client.confirm_data_category(
            env["category_id"],
            f.build_category_decision_payload("WITHDRAW"),
            env["agency_headers"],
        ),
        err.ERR_INVALID_STATE,
        409,
    )

    category = _category_row(client, env["offering_id"], "PII")
    assert category["status"] == "CONFIRMED"
    assert category["confirmed_by_user_id"] == "board-1"
    assert category["confirmed_by_user_id"] != env["agency_id"]

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "DRAFT"
    assert offering["preliminary_impact_level"] == "MODERATE"
    a.assert_integer(offering["version"], 3, "offering version")


# ---------------------------------------------------------------------------
# Monitoring-period closure is gated on the window end
# ---------------------------------------------------------------------------


def _march_period_env(client):
    """A live authorization whose auto-created 2026-03 period holds a full scan set."""
    env = fx.seed_authorized_offering(client)
    assert env["period"]["period_month"] == "2026-03"
    env["submission"] = fx.submit_scans(client, env, env["period_id"])
    return env


def test_closing_a_period_before_its_window_end_is_refused(client):
    """A period close before the clock reaches window_end is refused, full scans or not.

    PRD: "The period must still be `OPEN`, else `ERR_ALREADY_TERMINAL`, and the logical clock must be at or after `window_end`, else `ERR_PERIOD_NOT_ENDED`."

    Design: Corner/state_machines/a_monitoring_period_close_before_its_window_end_is_refused
    """
    env = _march_period_env(client)

    submission = env["submission"]
    assert submission["status"] == "ACCEPTED"
    a.assert_integer(submission["days_late"], 0, "days_late")
    a.assert_instant(submission["submitted_at"], AUTHORIZATION_CLOCK, "submitted_at")
    assert submission["submitted_by_user_id"] == CSP_LEAD_1

    period = fx.read_monitoring_period(client, env["period_id"])
    a.assert_monitoring_window(period, "2026-03")
    a.assert_integer(period["accepted_submission_count"], 1, "accepted_submission_count")
    assert period["covered_scan_types"] == ["DATABASE", "INFRASTRUCTURE", "WEB_APP"]

    validate_error(
        client.close_monitoring_period(env["period_id"], BOARD_HEADERS),
        err.ERR_PERIOD_NOT_ENDED,
        409,
    )

    period = fx.read_monitoring_period(client, env["period_id"])
    assert period["status"] == "OPEN"
    assert period["closed_at"] is None


def test_the_same_close_lands_compliant_once_the_clock_reaches_the_window_end(client):
    """Once the clock reaches window_end the same close lands CLOSED_COMPLIANT.

    PRD: "When all three hold the period closes `OPEN → CLOSED_COMPLIANT`; when any one of them fails it closes `OPEN → CLOSED_DEFICIENT`."

    Design: Corner/state_machines/a_monitoring_period_close_before_its_window_end_is_refused
    """
    env = _march_period_env(client)
    validate_error(
        client.close_monitoring_period(env["period_id"], BOARD_HEADERS),
        err.ERR_PERIOD_NOT_ENDED,
        409,
    )

    fx.set_clock(client, "2026-04-01T00:00:00Z")
    period = validate_success(
        client.close_monitoring_period(env["period_id"], BOARD_HEADERS), 200
    )

    assert period["status"] == "CLOSED_COMPLIANT"
    assert period["status"] != "CLOSED_DEFICIENT"
    a.assert_instant(period["closed_at"], "2026-04-01T00:00:00Z", "closed_at")

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        authorization["consecutive_deficient_periods"],
        0,
        "consecutive_deficient_periods",
    )
    assert authorization["monitoring_posture"] == "ACTIVE"
    assert authorization["authorization_status"] == "AUTHORIZED"


def test_a_compliant_close_auto_opens_the_next_month_period(client):
    """The compliant close auto-creates the next month's period with its own window.

    PRD: "And the next month's monitoring period is auto-created by the close whenever the authorization's `authorization_status` after the close is `AUTHORIZED` or `SUSPENDED` — that creation is skipped when a period for that `period_month` already exists for the authorization, and no further period is auto-created once the authorization has reached `REVOKED` or `EXPIRED`."

    Design: Corner/state_machines/a_monitoring_period_close_before_its_window_end_is_refused
    """
    env = _march_period_env(client)
    fx.set_clock(client, "2026-04-01T00:00:00Z")
    validate_success(
        client.close_monitoring_period(env["period_id"], BOARD_HEADERS), 200
    )

    rows, meta = validate_paginated(
        client.list_monitoring_periods(env["authorization_id"], CSP_LEAD_HEADERS)
    )
    a.assert_integer(meta["total_count"], 2, "monitoring periods total_count")

    open_periods = [row for row in rows if row["status"] == "OPEN"]
    assert len(open_periods) == 1
    april = open_periods[0]
    a.assert_monitoring_window(april, "2026-04")
    a.assert_instant(april["window_start"], "2026-04-01T00:00:00Z", "window_start")
    a.assert_instant(april["window_end"], "2026-05-01T00:00:00Z", "window_end")
    a.assert_instant(april["scan_due_at"], "2026-05-06T00:00:00Z", "scan_due_at")
    assert april["covered_scan_types"] == []
    assert april["closed_at"] is None
    a.assert_integer(april["accepted_submission_count"], 0, "accepted_submission_count")


# ---------------------------------------------------------------------------
# The incremental-review self-loop
# ---------------------------------------------------------------------------


def _access_granted_grant_env(client):
    """A live authorization whose EPA grant sits in PACKAGE_ACCESS_GRANTED."""
    env = fx.seed_authorized_offering(client)
    env = fx.add_agency(
        client,
        env,
        name="Environmental Protection Agency",
        agency_code="EPA",
        key="epa",
    )
    env = fx.seed_reuse_grant(
        client,
        env,
        agency_id=env["epa_id"],
        agency_headers=env["epa_headers"],
        advance_to="PACKAGE_ACCESS_GRANTED",
    )
    assert env["grant"]["access_state"] == "PACKAGE_ACCESS_GRANTED"
    return env


def test_repeated_more_info_overwrites_the_incremental_review_findings_count(client):
    """A second MORE_INFO self-loops and overwrites the findings count rather than adding.

    PRD: "A `MORE_INFO` decision writes `incremental_review_findings_count` and moves the grant `PACKAGE_ACCESS_GRANTED → INCREMENTAL_REVIEW`; repeated from `INCREMENTAL_REVIEW` it is a self-loop that overwrites `incremental_review_findings_count` and leaves the state where it is, so the review may iterate as often as the agency needs."

    Design: Corner/state_machines/the_incremental_review_self_loop_overwrites_the_findings_count
    """
    env = _access_granted_grant_env(client)

    first = validate_success(
        client.record_incremental_review(
            env["grant_id"],
            f.build_incremental_review_payload("MORE_INFO", 2),
            env["epa_headers"],
        ),
        200,
    )
    assert first["access_state"] == "INCREMENTAL_REVIEW"
    a.assert_integer(
        first["incremental_review_findings_count"],
        2,
        "incremental_review_findings_count",
    )

    second = validate_success(
        client.record_incremental_review(
            env["grant_id"],
            f.build_incremental_review_payload("MORE_INFO", 4),
            env["epa_headers"],
        ),
        200,
    )
    assert second["access_state"] == "INCREMENTAL_REVIEW"
    a.assert_integer(
        second["incremental_review_findings_count"],
        4,
        "incremental_review_findings_count",
    )
    assert second["incremental_review_findings_count"] != 6
    assert second["reuse_accepted_at"] is None


def test_accepting_above_the_findings_tolerance_leaves_the_grant_in_review(client):
    """An acceptance carrying six findings exceeds the tolerance and changes nothing.

    PRD: "An `ACCEPT` decision is legal from `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW` or `NOTICE_ISSUED`, requires the supplied `findings_count` to be no more than 5 — more than that is refused with `ERR_INCREMENTAL_FINDINGS_EXCEED_TOLERANCE` — and requires the authorization to still be in `authorization_status` `AUTHORIZED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`."

    Design: Corner/state_machines/the_incremental_review_self_loop_overwrites_the_findings_count
    """
    env = _access_granted_grant_env(client)
    validate_success(
        client.record_incremental_review(
            env["grant_id"],
            f.build_incremental_review_payload("MORE_INFO", 4),
            env["epa_headers"],
        ),
        200,
    )

    validate_error(
        client.record_incremental_review(
            env["grant_id"],
            f.build_incremental_review_payload("ACCEPT", 6),
            env["epa_headers"],
        ),
        err.ERR_INCREMENTAL_FINDINGS_EXCEED_TOLERANCE,
        422,
    )

    grant = fx.read_reuse_grant(client, env["grant_id"])
    assert grant["access_state"] == "INCREMENTAL_REVIEW"
    a.assert_integer(
        grant["incremental_review_findings_count"],
        4,
        "incremental_review_findings_count",
    )
    assert grant["reuse_accepted_at"] is None


def test_accepting_at_exactly_the_findings_tolerance_moves_the_grant_to_reuse_accepted(
    client,
):
    """An acceptance carrying exactly five findings passes and stamps reuse_accepted_at.

    PRD: "It writes `incremental_review_findings_count` and `reuse_accepted_at` from the logical clock and moves the grant to `REUSE_ACCEPTED`; when the previous state was `NOTICE_ISSUED`, accepting also decrements the grantee agency's `open_notice_count` by one, which is the loop back out of a monitoring notice into good standing."

    Design: Corner/state_machines/the_incremental_review_self_loop_overwrites_the_findings_count
    """
    env = _access_granted_grant_env(client)
    validate_success(
        client.record_incremental_review(
            env["grant_id"],
            f.build_incremental_review_payload("MORE_INFO", 4),
            env["epa_headers"],
        ),
        200,
    )

    grant = validate_success(
        client.record_incremental_review(
            env["grant_id"],
            f.build_incremental_review_payload("ACCEPT", 5),
            env["epa_headers"],
        ),
        200,
    )

    assert grant["access_state"] == "REUSE_ACCEPTED"
    a.assert_integer(
        grant["incremental_review_findings_count"],
        5,
        "incremental_review_findings_count",
    )
    a.assert_instant(grant["reuse_accepted_at"], AUTHORIZATION_CLOCK, "reuse_accepted_at")

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 1, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 4, "reuse_seats_available")
    a.assert_seat_conservation(authorization)

    agency = fx.read_agency(client, env["epa_id"])
    a.assert_integer(agency["reuse_grant_count"], 1, "reuse_grant_count")
    a.assert_integer(agency["open_notice_count"], 0, "open_notice_count")


# ---------------------------------------------------------------------------
# The significant-change decision fork
# ---------------------------------------------------------------------------


def test_filing_a_change_request_moves_the_offering_into_change_under_review(client):
    """Filing a boundary change opens the request SUBMITTED and parks the offering.

    PRD: "Filing requires the offering to be in status `AUTHORIZED`, moves it `AUTHORIZED → CHANGE_UNDER_REVIEW`, increments its `version` by one, and opens the request in status `SUBMITTED` with `decided_by_user_id` null."

    Design: Corner/state_machines/a_denied_change_request_returns_the_offering_to_authorized_without_touching_the_boundary
    """
    env = fx.seed_authorized_offering(client)
    version_before = fx.offering_version(client, env["offering_id"])

    request = validate_success(
        client.create_change_request(
            f.build_change_request_payload(
                env["offering_id"],
                "2026-05-01T00:00:00Z",
                "2026-05-10T00:00:00Z",
                change_kind="BOUNDARY_CHANGE",
                description="Withdrawn boundary expansion.",
            ),
            env["lead_headers"],
        ),
        201,
    )

    assert request["status"] == "SUBMITTED"
    assert request["decided_by_user_id"] is None
    assert request["requires_reassessment"] is True

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "CHANGE_UNDER_REVIEW"
    a.assert_integer(offering["version"], version_before + 1, "offering version")
    a.assert_integer(offering["boundary_version"], 1, "boundary_version")
    a.assert_integer(offering["included_service_count"], 0, "included_service_count")


def test_a_denied_change_request_returns_the_offering_without_touching_the_boundary(
    client,
):
    """A denied change request returns the offering to AUTHORIZED and leaves the boundary.

    PRD: "A `DENY` leaves both `boundary_version` and `included_service_count` unchanged."

    Design: Corner/state_machines/a_denied_change_request_returns_the_offering_to_authorized_without_touching_the_boundary
    """
    env = fx.seed_authorized_offering(client)
    request = validate_success(
        client.create_change_request(
            f.build_change_request_payload(
                env["offering_id"],
                "2026-05-01T00:00:00Z",
                "2026-05-10T00:00:00Z",
                change_kind="BOUNDARY_CHANGE",
                description="Withdrawn boundary expansion.",
            ),
            env["lead_headers"],
        ),
        201,
    )

    decided = validate_success(
        client.decide_change_request(
            request["id"], f.build_change_decision_payload("DENY"), env["agency_headers"]
        ),
        200,
    )

    assert decided["status"] == "DENIED"
    assert decided["decided_by_user_id"] == env["agency_id"]

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "AUTHORIZED"
    a.assert_integer(offering["boundary_version"], 1, "boundary_version")
    a.assert_integer(offering["included_service_count"], 0, "included_service_count")


def test_an_approved_new_service_bumps_the_boundary_version_and_service_count(client):
    """An approved NEW_SERVICE change applies both boundary side effects.

    PRD: "An `APPROVE` of a `BOUNDARY_CHANGE` or a `NEW_SERVICE` increments the offering's `boundary_version` by one, and an `APPROVE` of a `NEW_SERVICE` additionally increases the offering's `included_service_count` by the request's `added_service_count`; an `APPROVE` of a `TECH_REFRESH` leaves both untouched."

    Design: Corner/state_machines/a_denied_change_request_returns_the_offering_to_authorized_without_touching_the_boundary
    """
    env = fx.seed_authorized_offering(client)
    request = validate_success(
        client.create_change_request(
            f.build_change_request_payload(
                env["offering_id"],
                "2026-06-01T00:00:00Z",
                "2026-06-10T00:00:00Z",
                change_kind="NEW_SERVICE",
                description="Add three managed data services.",
                added_service_count=3,
            ),
            env["lead_headers"],
        ),
        201,
    )
    # added_service_count 3 is at the reassessment threshold.
    assert request["requires_reassessment"] is True
    assert fx.read_offering(client, env["offering_id"])["status"] == "CHANGE_UNDER_REVIEW"

    decided = validate_success(
        client.decide_change_request(
            request["id"],
            f.build_change_decision_payload("APPROVE"),
            env["agency_headers"],
        ),
        200,
    )

    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == env["agency_id"]

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "AUTHORIZED"
    a.assert_integer(offering["boundary_version"], 2, "boundary_version")
    a.assert_integer(offering["included_service_count"], 3, "included_service_count")

    _rows, meta = validate_paginated(
        client.list_change_requests(
            CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]}
        )
    )
    a.assert_integer(meta["total_count"], 1, "change requests total_count")
