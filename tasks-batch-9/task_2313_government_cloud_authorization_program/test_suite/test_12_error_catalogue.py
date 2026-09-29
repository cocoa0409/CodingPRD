"""Error catalogue coverage for the program API.

These tests pin the refusals that are easy to collapse into one another: the
thirteen entity-specific 404 codes, the three-package row cap, the three
"wrong offering" mismatches, the monitoring-period duplicate and scan-window
gates, the escalation gate that closes reuse and monitoring writes, and the
finite reuse seat pool. Each one checks the exact error identifier and HTTP
status the contract names, and that a refused request leaves the state it
touched alone.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AUTHORIZATION_NOT_ACTIVE,
    ERR_BASELINE_NOT_FOUND,
    ERR_CHANGE_REQUEST_NOT_FOUND,
    ERR_CONTROL_IMPLEMENTATION_NOT_FOUND,
    ERR_DATA_CATEGORY_NOT_FOUND,
    ERR_DEVIATION_NOT_FOUND,
    ERR_DUPLICATE_MONITORING_PERIOD,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_INCOMPLETE_SCAN_SET,
    ERR_MONITORING_PERIOD_NOT_FOUND,
    ERR_PACKAGE_NOT_FOUND,
    ERR_POAM_OFFERING_MISMATCH,
    ERR_REUSE_GRANT_NOT_FOUND,
    ERR_REUSE_SEATS_EXHAUSTED,
    ERR_REVISION_LIMIT_EXCEEDED,
    ERR_SCAN_WINDOW_NOT_OPEN,
    ERR_SPONSOR_AGENCY_MISMATCH,
    ERR_SUPERSEDED_ITEM_MISMATCH,
)
from test_helpers.test_users import (
    ASSESSOR_HEADERS,
    BOARD_HEADERS,
    CSP_LEAD_HEADERS,
)

# ---------------------------------------------------------------------------
# Unknown identifiers against an empty database
# ---------------------------------------------------------------------------

#: One probe per entity whose identifier can sit in a request path, each issued
#: by a role the endpoint authorizes so the refusal can only come from the
#: unresolvable identifier.
_PATH_ID_PROBES = [
    pytest.param(
        lambda client: client.confirm_data_category(
            NON_EXISTENT_UUID, f.build_category_decision_payload("CONFIRM"), BOARD_HEADERS
        ),
        ERR_DATA_CATEGORY_NOT_FOUND,
        id="data_category",
    ),
    pytest.param(
        lambda client: client.get_control_implementation(
            NON_EXISTENT_UUID, CSP_LEAD_HEADERS
        ),
        ERR_CONTROL_IMPLEMENTATION_NOT_FOUND,
        id="control_implementation",
    ),
    pytest.param(
        lambda client: client.get_engagement(NON_EXISTENT_UUID, ASSESSOR_HEADERS),
        ERR_ENGAGEMENT_NOT_FOUND,
        id="assessment_engagement",
    ),
    pytest.param(
        lambda client: client.get_package(NON_EXISTENT_UUID, CSP_LEAD_HEADERS),
        ERR_PACKAGE_NOT_FOUND,
        id="authorization_package",
    ),
    pytest.param(
        lambda client: client.get_deviation_request(NON_EXISTENT_UUID, CSP_LEAD_HEADERS),
        ERR_DEVIATION_NOT_FOUND,
        id="deviation_request",
    ),
    pytest.param(
        lambda client: client.get_monitoring_period(NON_EXISTENT_UUID, BOARD_HEADERS),
        ERR_MONITORING_PERIOD_NOT_FOUND,
        id="monitoring_period",
    ),
    pytest.param(
        lambda client: client.get_change_request(NON_EXISTENT_UUID, ASSESSOR_HEADERS),
        ERR_CHANGE_REQUEST_NOT_FOUND,
        id="significant_change_request",
    ),
    pytest.param(
        lambda client: client.get_reuse_grant(NON_EXISTENT_UUID, BOARD_HEADERS),
        ERR_REUSE_GRANT_NOT_FOUND,
        id="reuse_grant",
    ),
]


@pytest.mark.parametrize("probe, expected_error_id", _PATH_ID_PROBES)
def test_unknown_path_identifier_reports_the_code_of_the_entity_it_addresses(
    client, probe, expected_error_id
):
    """Each unresolvable path identifier reports its own entity's 404 code.

    PRD: "Every identifier in the request path exists, resolved left to right — the corresponding 404."

    Design: Corner/errors/each_entity_reports_its_own_code_when_the_path_id_is_unknown
    """
    validate_error(probe(client), expected_error_id, 404)


def test_unknown_baseline_filter_on_the_offering_list_is_a_404_not_an_empty_page(client):
    """Listing offerings by an unknown baseline_id fails with the baseline 404.

    PRD: "Filtering offerings by a `baseline_id` that names no baseline fails with `ERR_BASELINE_NOT_FOUND`, and filtering by a `sponsor_agency_id` that names no agency fails with `ERR_AGENCY_NOT_FOUND`."

    Design: Corner/errors/each_entity_reports_its_own_code_when_the_path_id_is_unknown
    """
    response = client.list_offerings(CSP_LEAD_HEADERS, {"baseline_id": NON_EXISTENT_UUID})

    validate_error(response, ERR_BASELINE_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error", (
        "an unresolvable foreign-key filter must not return an offering page"
    )


def test_a_refused_lookup_carries_the_error_envelope(client):
    """A 404 body is the error envelope: response_type error and a two-key meta.

    PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/each_entity_reports_its_own_code_when_the_path_id_is_unknown
    """
    response = client.get_package(NON_EXISTENT_UUID, CSP_LEAD_HEADERS)
    validate_error(response, ERR_PACKAGE_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta carries unexpected keys: {sorted(body['meta'])}"
    )
    assert set(body["data"]) == {"error_id", "message"}, (
        f"error data carries unexpected keys: {sorted(body['data'])}"
    )
    assert body["data"]["message"], "the error envelope must carry a message"


# ---------------------------------------------------------------------------
# The three-package row cap
# ---------------------------------------------------------------------------


def _offering_with_one_package(client):
    """An offering whose report is delivered and which holds one DRAFT package."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_report_delivered(client, env, report_at=fx.AUTHORIZATION_CLOCK)
    env = fx.seed_package(client, env)
    return env


def _create_package_at_current_version(client, env):
    """Create one more package, re-arming the offering version each time."""
    return client.create_package(
        f.build_package_payload(
            env["offering_id"],
            env["engagement_id"],
            fx.offering_version(client, env["offering_id"]),
        ),
        env["lead_headers"],
    )


def test_a_second_package_supersedes_the_offerings_first_draft(client):
    """Creating a second package drives the first one to SUPERSEDED.

    PRD: "Any earlier package of the same offering sitting in `DRAFT` or `REVISION_REQUESTED` is superseded in the same request: it moves to status `SUPERSEDED`, the offering's `open_package_count` decrements by one and its `superseded_package_count` increments by one."

    Design: Corner/errors/a_fourth_package_row_on_one_offering_is_refused_whatever_its_state
    """
    env = _offering_with_one_package(client)
    first_package_id = env["package_id"]

    second = validate_success(_create_package_at_current_version(client, env), 201)

    assert fx.read_package(client, first_package_id)["status"] == "SUPERSEDED"
    assert second["status"] == "DRAFT"
    assert second["id"] != first_package_id


def test_three_package_rows_leave_one_open_and_two_superseded(client):
    """After three creates the open counter reads 1 and the superseded counter 2.

    PRD: "An offering's `open_package_count` counts its authorization packages in `status` `DRAFT`, `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED`; its `superseded_package_count` counts its packages in `status` `SUPERSEDED`; its `included_service_count` counts the services inside the authorization boundary."

    Design: Corner/errors/a_fourth_package_row_on_one_offering_is_refused_whatever_its_state
    """
    env = _offering_with_one_package(client)
    second = validate_success(_create_package_at_current_version(client, env), 201)
    third = validate_success(_create_package_at_current_version(client, env), 201)

    assert fx.read_package(client, second["id"])["status"] == "SUPERSEDED"
    assert third["status"] == "DRAFT"

    offering = fx.read_offering(client, env["offering_id"])
    a.assert_integer(offering["open_package_count"], 1, "open_package_count")
    a.assert_integer(offering["superseded_package_count"], 2, "superseded_package_count")


def test_a_fourth_package_row_on_one_offering_is_refused(client):
    """The fourth package create on one offering hits the three-row cap.

    PRD: "Revision capacity is capped by construction: an offering may hold at most three package rows in total, so a fourth creation is refused with `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Corner/errors/a_fourth_package_row_on_one_offering_is_refused_whatever_its_state
    """
    env = _offering_with_one_package(client)
    validate_success(_create_package_at_current_version(client, env), 201)
    validate_success(_create_package_at_current_version(client, env), 201)

    validate_error(
        _create_package_at_current_version(client, env), ERR_REVISION_LIMIT_EXCEEDED, 409
    )


def test_the_refused_fourth_package_leaves_exactly_three_rows_and_the_offering_version(
    client,
):
    """The refused fourth create writes nothing: three rows, offering version unmoved.

    PRD: "Creation also increments the offering's `open_package_count` and the offering's `version` by one."

    Design: Corner/errors/a_fourth_package_row_on_one_offering_is_refused_whatever_its_state
    """
    env = _offering_with_one_package(client)
    validate_success(_create_package_at_current_version(client, env), 201)
    validate_success(_create_package_at_current_version(client, env), 201)
    version_before = fx.offering_version(client, env["offering_id"])

    validate_error(
        _create_package_at_current_version(client, env), ERR_REVISION_LIMIT_EXCEEDED, 409
    )

    rows, meta = validate_paginated(
        client.list_packages(CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]})
    )
    assert meta["total_count"] == 3, (
        f"expected exactly three package rows, got {meta['total_count']}"
    )
    a.assert_integer(
        fx.read_offering(client, env["offering_id"])["version"],
        version_before,
        "offering version after the refused create",
    )
    assert len(rows) == 3


def test_all_three_package_rows_still_carry_submission_round_zero(client):
    """The row cap bites even though no package was ever submitted.

    PRD: "On success the package opens in status `DRAFT` with `submission_round` 0, `submitted_at`, `crm_coverage_pct`, `residual_risk_score_at_submission`, `open_findings_at_submission`, `reviewed_by_user_id`, `revision_note` and `letter_reference` all null, and with `authorization_path` copied from the offering — that copy is what later decides who may issue the decision."

    Design: Corner/errors/a_fourth_package_row_on_one_offering_is_refused_whatever_its_state
    """
    env = _offering_with_one_package(client)
    validate_success(_create_package_at_current_version(client, env), 201)
    validate_success(_create_package_at_current_version(client, env), 201)

    validate_error(
        _create_package_at_current_version(client, env), ERR_REVISION_LIMIT_EXCEEDED, 409
    )

    rows, _ = validate_paginated(
        client.list_packages(CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]})
    )
    for row in rows:
        a.assert_integer(row["submission_round"], 0, f"package {row['id']} submission_round")
        assert row["submitted_at"] is None


# ---------------------------------------------------------------------------
# Cross-offering references and foreign agency officials
# ---------------------------------------------------------------------------

_OFFERING_B_CATEGORIES = (
    {
        "category_code": "PHI",
        "confidentiality_impact": "MODERATE",
        "integrity_impact": "LOW",
        "availability_impact": "LOW",
        "confirm": True,
    },
)


def _two_offerings_and_a_foreign_agency(client):
    """Offering A sponsored by DOT with a submitted plan, offering B with a finding.

    An EPA agency exists and sponsors nothing, so its official has no
    relationship with either offering.
    """
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env, approve_plan=False)
    env = fx.add_agency(
        client,
        env,
        name="Environmental Protection Agency",
        agency_code="EPA",
        key="epa",
    )
    env = fx.seed_categorized_offering(
        client,
        env,
        categories=_OFFERING_B_CATEGORIES,
        offering_key="offering_b",
        name="GovCloud Storage",
    )
    env = fx.seed_poam_item(
        client,
        env,
        offering_key="offering_b",
        control_id="AC-2",
        severity="HIGH",
        key="poam_b",
    )
    return env


def test_a_foreign_agency_official_may_not_approve_the_sponsored_assessment_plan(client):
    """An EPA official approving DOT's sponsored plan is a sponsor mismatch.

    PRD: "On the `AGENCY_SPONSORED` path the acting party must be an `AgencyAuthorizingOfficial` whose `X-User-ID` equals the offering's `sponsor_agency_id`, and any other agency official is refused with `ERR_SPONSOR_AGENCY_MISMATCH`; on the `PROGRAM_BOARD` path the acting party must be a `ProgramBoardReviewer`, and anyone else is refused with `ERR_WRONG_REVIEW_QUEUE`."

    Design: Corner/errors/cross_offering_references_and_foreign_officials_are_each_refused_with_their_own_code
    """
    env = _two_offerings_and_a_foreign_agency(client)

    response = client.decide_plan(
        env["engagement_id"], f.build_plan_decision_payload("APPROVE"), env["epa_headers"]
    )

    validate_error(response, ERR_SPONSOR_AGENCY_MISMATCH, 403)
    assert fx.read_engagement(client, env["engagement_id"])["status"] == "PLAN_SUBMITTED"


def test_the_sponsoring_official_approves_the_plan_and_the_offering_enters_assessment(
    client,
):
    """The DOT official's approval moves the engagement and bubbles up the offering.

    PRD: "An `APPROVE` moves the engagement `PLAN_SUBMITTED → PLAN_APPROVED` and, as a bubble-up, drives the offering `PATH_SELECTED → IN_ASSESSMENT` and increments the offering's `version` by one; the offering must be in `PATH_SELECTED` and the engagement must belong to it."

    Design: Corner/errors/cross_offering_references_and_foreign_officials_are_each_refused_with_their_own_code
    """
    env = _two_offerings_and_a_foreign_agency(client)

    engagement = validate_success(
        client.decide_plan(
            env["engagement_id"],
            f.build_plan_decision_payload("APPROVE"),
            env["agency_headers"],
        ),
        200,
    )

    assert engagement["status"] == "PLAN_APPROVED"
    assert fx.read_offering(client, env["offering_id"])["status"] == "IN_ASSESSMENT"


def test_a_supersedes_pointer_at_another_offerings_finding_is_refused(client):
    """A finding on offering A may not supersede a finding of offering B.

    PRD: "Supplying `supersedes_item_id` names the finding this item replaces; it must belong to the same offering, and a cross-offering pointer is refused with `ERR_SUPERSEDED_ITEM_MISMATCH`, while a pointer at a finding that is already `CLOSED` is refused with `ERR_ALREADY_TERMINAL`."

    Design: Corner/errors/cross_offering_references_and_foreign_officials_are_each_refused_with_their_own_code
    """
    env = _two_offerings_and_a_foreign_agency(client)

    response = client.create_poam_item(
        f.build_poam_item_payload(
            env["offering_id"],
            control_id="AC-3",
            severity="HIGH",
            detected_at=fx.SETUP_CLOCK,
            supersedes_item_id=env["poam_b_id"],
        ),
        env["lead_headers"],
    )

    validate_error(response, ERR_SUPERSEDED_ITEM_MISMATCH, 409)

    superseded_target = fx.read_poam_item(client, env["poam_b_id"])
    assert superseded_target["remediation_status"] == "OPEN"
    assert superseded_target["closure_reason"] is None
    assert fx.list_poam_items(client, offering_id=env["offering_id"]) == [], (
        "the refused create must not write a finding on offering A"
    )
    assert len(fx.list_poam_items(client, offering_id=env["offering_b_id"])) == 1


def test_a_foreign_official_deciding_an_agency_queue_deviation_reports_the_finding_mismatch(
    client,
):
    """The tier-33 entitlement check outranks the tier-34 sponsor comparison.

    PRD: "An `AGENCY_REVIEW` request may only be decided by an `AgencyAuthorizingOfficial` whose `X-User-ID` equals the offering's `sponsor_agency_id`; a foreign agency official is refused with `ERR_POAM_OFFERING_MISMATCH` at tier 33 of §2.7, before the sponsor comparison at tier 34 is ever reached."

    Design: Corner/errors/cross_offering_references_and_foreign_officials_are_each_refused_with_their_own_code
    """
    env = _two_offerings_and_a_foreign_agency(client)
    env = fx.seed_poam_item(
        client, env, control_id="AC-3", severity="HIGH", key="poam_a"
    )
    env = fx.seed_deviation(
        client,
        env,
        env["poam_a_id"],
        kind="RISK_ADJUSTMENT",
        review_queue="AGENCY",
    )

    response = client.decide_deviation(
        env["deviation_id"],
        f.build_deviation_decision_payload("APPROVE"),
        env["epa_headers"],
    )

    validate_error(response, ERR_POAM_OFFERING_MISMATCH, 409)
    assert fx.read_deviation(client, env["deviation_id"])["status"] == "AGENCY_REVIEW"


def test_the_sponsoring_official_approves_the_risk_adjustment_on_its_own_offering(client):
    """The DOT official's approval accepts the risk on offering A's finding.

    PRD: "Approving a `RISK_ADJUSTMENT` request in the agency queue leaves `granted_extension_days` at 0, moves the finding's `risk_disposition` `DEVIATION_REQUESTED → RISK_ACCEPTED`, and recomputes the authorization's `risk_accepted_findings_count` and `residual_risk_score`, where the accepted finding now contributes at half weight."

    Design: Corner/errors/cross_offering_references_and_foreign_officials_are_each_refused_with_their_own_code
    """
    env = _two_offerings_and_a_foreign_agency(client)
    env = fx.seed_poam_item(
        client, env, control_id="AC-3", severity="HIGH", key="poam_a"
    )
    env = fx.seed_deviation(
        client,
        env,
        env["poam_a_id"],
        kind="RISK_ADJUSTMENT",
        review_queue="AGENCY",
    )

    deviation = validate_success(
        client.decide_deviation(
            env["deviation_id"],
            f.build_deviation_decision_payload("APPROVE"),
            env["agency_headers"],
        ),
        200,
    )

    assert deviation["status"] == "APPROVED"
    assert fx.read_poam_item(client, env["poam_a_id"])["risk_disposition"] == "RISK_ACCEPTED"


# ---------------------------------------------------------------------------
# Monitoring periods: duplicate month and the scan window
# ---------------------------------------------------------------------------


def test_reopening_the_month_the_authorization_already_opened_is_refused(client):
    """The month the authorization decision opened cannot be opened again.

    PRD: "That value must be unique for the authorization, so a duplicate month is refused with `ERR_DUPLICATE_MONITORING_PERIOD`, and a month string that does not match the form is refused with `ERR_INVALID_REQUEST`."

    Design: Corner/errors/monitoring_periods_refuse_a_repeated_month_and_a_scan_that_arrives_before_the_window_opens
    """
    env = fx.seed_authorized_offering(client)
    assert fx.read_monitoring_period(client, env["period_id"])["period_month"] == "2026-03"

    response = client.create_monitoring_period(
        env["authorization_id"],
        f.build_monitoring_period_payload("2026-03"),
        env["lead_headers"],
    )

    validate_error(response, ERR_DUPLICATE_MONITORING_PERIOD, 409)
    assert len(fx.list_monitoring_periods(client, env["authorization_id"])) == 1


def test_a_later_month_opens_while_the_current_month_is_still_open(client):
    """A different month is accepted and derives its window from the month alone.

    PRD: "The server derives three instants from the month: `window_start` is the first instant of that month inclusive, `window_end` is the first instant of the following month exclusive, and `scan_due_at` is five days after `window_end`."

    Design: Corner/errors/monitoring_periods_refuse_a_repeated_month_and_a_scan_that_arrives_before_the_window_opens
    """
    env = fx.seed_authorized_offering(client)

    period = validate_success(
        client.create_monitoring_period(
            env["authorization_id"],
            f.build_monitoring_period_payload("2026-05"),
            env["lead_headers"],
        ),
        201,
    )

    a.assert_monitoring_window(period, "2026-05")
    a.assert_instant(period["window_start"], "2026-05-01T00:00:00Z", "window_start")
    a.assert_instant(period["window_end"], "2026-06-01T00:00:00Z", "window_end")
    a.assert_instant(period["scan_due_at"], "2026-06-06T00:00:00Z", "scan_due_at")
    assert period["status"] == "OPEN"

    _, meta = validate_paginated(
        client.list_monitoring_periods(
            env["authorization_id"], BOARD_HEADERS, {"status": "OPEN"}
        )
    )
    assert meta["total_count"] == 2, (
        f"two months may be open at once, got {meta['total_count']} open periods"
    )


def _authorization_with_a_future_period(client):
    """A live authorization at 2026-03-30 holding an extra, not-yet-begun period."""
    env = fx.seed_authorized_offering(client)
    return fx.open_monitoring_period(client, env, "2026-05", key="may_period")


def test_a_complete_scan_set_before_the_window_opens_is_refused(client):
    """Scans for a month that has not begun are refused on the window gate.

    PRD: "A submission before the period has begun — the logical clock earlier than `window_start` — is refused with `ERR_SCAN_WINDOW_NOT_OPEN`."

    Design: Corner/errors/monitoring_periods_refuse_a_repeated_month_and_a_scan_that_arrives_before_the_window_opens
    """
    env = _authorization_with_a_future_period(client)

    response = client.create_scan_submission(
        env["may_period_id"],
        f.build_scan_submission_payload(["INFRASTRUCTURE", "WEB_APP", "DATABASE"]),
        env["lead_headers"],
    )

    validate_error(response, ERR_SCAN_WINDOW_NOT_OPEN, 422)


def test_an_incomplete_scan_set_outranks_the_unopened_window(client):
    """A missing mandatory scan type is reported ahead of the window gate.

    PRD: "Three of those four are mandatory in every submission: a `scan_types` array that omits `INFRASTRUCTURE`, `WEB_APP` or `DATABASE` is refused with `ERR_INCOMPLETE_SCAN_SET`, while `CONTAINER` is optional."

    Design: Corner/errors/monitoring_periods_refuse_a_repeated_month_and_a_scan_that_arrives_before_the_window_opens
    """
    env = _authorization_with_a_future_period(client)

    response = client.create_scan_submission(
        env["may_period_id"],
        f.build_scan_submission_payload(["INFRASTRUCTURE", "WEB_APP"]),
        env["lead_headers"],
    )

    validate_error(response, ERR_INCOMPLETE_SCAN_SET, 422)


def test_refused_scan_submissions_leave_the_period_counters_untouched(client):
    """Neither refused submission writes a row or moves a period counter.

    PRD: "The period opens in status `OPEN` with `accepted_submission_count`, `late_submission_count` and `rejected_submission_count` at 0, `covered_scan_types` an empty array, and `closed_at` null."

    Design: Corner/errors/monitoring_periods_refuse_a_repeated_month_and_a_scan_that_arrives_before_the_window_opens
    """
    env = _authorization_with_a_future_period(client)

    validate_error(
        client.create_scan_submission(
            env["may_period_id"],
            f.build_scan_submission_payload(["INFRASTRUCTURE", "WEB_APP", "DATABASE"]),
            env["lead_headers"],
        ),
        ERR_SCAN_WINDOW_NOT_OPEN,
        422,
    )
    validate_error(
        client.create_scan_submission(
            env["may_period_id"],
            f.build_scan_submission_payload(["INFRASTRUCTURE", "WEB_APP"]),
            env["lead_headers"],
        ),
        ERR_INCOMPLETE_SCAN_SET,
        422,
    )

    period = fx.read_monitoring_period(client, env["may_period_id"])
    a.assert_integer(period["accepted_submission_count"], 0, "accepted_submission_count")
    a.assert_integer(period["late_submission_count"], 0, "late_submission_count")
    a.assert_integer(period["rejected_submission_count"], 0, "rejected_submission_count")
    assert period["covered_scan_types"] == []
    a.assert_integer(period["version"], 1, "monitoring period version")


# ---------------------------------------------------------------------------
# Escalation closes reuse and monitoring writes
# ---------------------------------------------------------------------------


def _authorized_with_two_more_agencies(client):
    """A live authorization at 2026-03-30 plus an EPA and an HHS agency."""
    env = fx.seed_authorized_offering(client)
    env = fx.add_agency(
        client,
        env,
        name="Environmental Protection Agency",
        agency_code="EPA",
        key="epa",
    )
    env = fx.add_agency(
        client, env, name="Health and Human Services", agency_code="HHS", key="hhs"
    )
    return env


def _period_id_for_month(client, authorization_id, period_month):
    """The id of the authorization's period covering ``period_month``."""
    for row in fx.list_monitoring_periods(client, authorization_id):
        if row["period_month"] == period_month:
            return row["id"]
    raise AssertionError(f"no monitoring period exists for {period_month}")


def _at_risk_env(client):
    """One deficient close behind it: posture AT_RISK, authorization still AUTHORIZED."""
    env = _authorized_with_two_more_agencies(client)
    fx.set_clock(client, "2026-04-01T00:00:00Z")
    fx.close_period(client, env, env["period_id"])
    env["april_period_id"] = _period_id_for_month(
        client, env["authorization_id"], "2026-04"
    )
    return env


def _escalated_env(client):
    """Two consecutive deficient closes: posture ESCALATED, authorization SUSPENDED.

    The EPA grant is taken while the posture is only AT_RISK and carried to
    ``PACKAGE_ACCESS_GRANTED``, so the second close moves it to
    ``NOTICE_ISSUED`` — a state an incremental-review acceptance is legal from.
    """
    env = _at_risk_env(client)
    env = fx.seed_reuse_grant(
        client,
        env,
        agency_id=env["epa_id"],
        agency_headers=env["epa_headers"],
        advance_to="PACKAGE_ACCESS_GRANTED",
        key="epa_grant",
    )
    fx.set_clock(client, "2026-05-01T00:00:00Z")
    fx.close_period(client, env, env["april_period_id"])
    return env


def test_the_first_deficient_close_moves_the_posture_and_leaves_the_authorization_active(
    client,
):
    """One deficient month reaches AT_RISK without touching authorization_status.

    PRD: "At a run of 1 the `monitoring_posture` moves `ACTIVE → AT_RISK`, and every reuse grant of the authorization in `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW` or `REUSE_ACCEPTED` is moved to `NOTICE_ISSUED`, each such grant incrementing its own `notice_count` by one and the grantee agency's `open_notice_count` by one."

    Design: Corner/errors/an_escalated_authorization_stops_accepting_reuse_and_monitoring_writes
    """
    env = _authorized_with_two_more_agencies(client)
    fx.set_clock(client, "2026-04-01T00:00:00Z")

    period = validate_success(
        client.close_monitoring_period(env["period_id"], BOARD_HEADERS), 200
    )

    assert period["status"] == "CLOSED_DEFICIENT"
    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        authorization["consecutive_deficient_periods"], 1, "consecutive_deficient_periods"
    )
    assert authorization["monitoring_posture"] == "AT_RISK"
    assert authorization["authorization_status"] == "AUTHORIZED"

    periods = fx.list_monitoring_periods(client, env["authorization_id"])
    by_month = {row["period_month"]: row for row in periods}
    assert sorted(by_month) == ["2026-03", "2026-04"], (
        f"the close must auto-create the next month, found {sorted(by_month)}"
    )
    assert by_month["2026-04"]["status"] == "OPEN"


def test_a_reuse_grant_is_accepted_while_the_posture_is_only_at_risk(client):
    """AT_RISK is not a blocking posture, so reuse still succeeds after one lapse.

    PRD: "The authorization must be in `authorization_status` `AUTHORIZED` with a `monitoring_posture` other than `ESCALATED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`."

    Design: Corner/errors/an_escalated_authorization_stops_accepting_reuse_and_monitoring_writes
    """
    env = _at_risk_env(client)
    assert (
        fx.read_authorization(client, env["authorization_id"])["monitoring_posture"]
        == "AT_RISK"
    )

    grant = validate_success(
        client.create_reuse_grant(
            f.build_reuse_grant_payload(
                env["authorization_id"],
                env["epa_id"],
                fx.authorization_version(client, env["authorization_id"]),
            ),
            env["epa_headers"],
        ),
        201,
    )

    assert grant["access_state"] == "REQUESTED"
    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 1, "reuse_seats_granted")
    a.assert_seat_conservation(authorization)


def test_the_second_deficient_close_escalates_the_posture_and_suspends_the_offering(
    client,
):
    """A second consecutive deficient month escalates and suspends.

    PRD: "At a run of exactly 2 the `authorization_status` moves `AUTHORIZED → SUSPENDED` and the `monitoring_posture` is set to `ESCALATED`, and the offering is driven `AUTHORIZED → SUSPENDED` with its `version` incremented by one; a posture already at `AT_RISK` moving on a run of 2 or more likewise lands at `ESCALATED` and issues notices to the same three access states."

    Design: Corner/errors/an_escalated_authorization_stops_accepting_reuse_and_monitoring_writes
    """
    env = _at_risk_env(client)
    fx.set_clock(client, "2026-05-01T00:00:00Z")

    period = validate_success(
        client.close_monitoring_period(env["april_period_id"], BOARD_HEADERS), 200
    )

    assert period["status"] == "CLOSED_DEFICIENT"
    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        authorization["consecutive_deficient_periods"], 2, "consecutive_deficient_periods"
    )
    assert authorization["monitoring_posture"] == "ESCALATED"
    assert authorization["authorization_status"] == "SUSPENDED"
    assert fx.read_offering(client, env["offering_id"])["status"] == "SUSPENDED"


def test_a_further_reuse_grant_is_refused_once_the_posture_is_escalated(client):
    """A second agency's reuse request on an escalated authorization is a 409.

    PRD: "The authorization must be in `authorization_status` `AUTHORIZED` with a `monitoring_posture` other than `ESCALATED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`."

    Design: Corner/errors/an_escalated_authorization_stops_accepting_reuse_and_monitoring_writes
    """
    env = _escalated_env(client)
    current_version = fx.authorization_version(client, env["authorization_id"])

    response = client.create_reuse_grant(
        f.build_reuse_grant_payload(
            env["authorization_id"], env["hhs_id"], current_version
        ),
        env["hhs_headers"],
    )

    validate_error(response, ERR_AUTHORIZATION_NOT_ACTIVE, 409)
    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 1, "reuse_seats_granted")
    a.assert_integer(
        fx.read_agency(client, env["hhs_id"])["reuse_grant_count"],
        0,
        "HHS reuse_grant_count",
    )


def test_an_incremental_review_acceptance_is_refused_once_the_authorization_is_suspended(
    client,
):
    """The grantee agency cannot accept reuse while the authorization is suspended.

    PRD: "An `ACCEPT` decision is legal from `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW` or `NOTICE_ISSUED`, requires the supplied `findings_count` to be no more than 5 — more than that is refused with `ERR_INCREMENTAL_FINDINGS_EXCEED_TOLERANCE` — and requires the authorization to still be in `authorization_status` `AUTHORIZED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`."

    Design: Corner/errors/an_escalated_authorization_stops_accepting_reuse_and_monitoring_writes
    """
    env = _escalated_env(client)
    grant = fx.read_reuse_grant(client, env["epa_grant_id"])
    assert grant["access_state"] == "NOTICE_ISSUED", (
        "the escalating close issues a notice on the access-bearing grant, which is "
        "a state an acceptance is otherwise legal from"
    )

    response = client.record_incremental_review(
        env["epa_grant_id"],
        f.build_incremental_review_payload("ACCEPT", 0),
        env["epa_headers"],
    )

    validate_error(response, ERR_AUTHORIZATION_NOT_ACTIVE, 409)
    assert fx.read_reuse_grant(client, env["epa_grant_id"])["access_state"] == "NOTICE_ISSUED"
    assert fx.read_reuse_grant(client, env["epa_grant_id"])["reuse_accepted_at"] is None


def test_opening_a_further_monitoring_period_by_hand_is_refused_once_escalated(client):
    """A hand-opened month is refused even though the close auto-created one.

    PRD: "Opening a period may be done by a `CspComplianceLead` or a `ProgramBoardReviewer`, and requires the authorization to be in `authorization_status` `AUTHORIZED` with a `monitoring_posture` other than `ESCALATED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`."

    Design: Corner/errors/an_escalated_authorization_stops_accepting_reuse_and_monitoring_writes
    """
    env = _escalated_env(client)
    months = sorted(
        row["period_month"]
        for row in fx.list_monitoring_periods(client, env["authorization_id"])
    )
    assert months == ["2026-03", "2026-04", "2026-05"], (
        f"the suspending close auto-creates the next month, got {months}"
    )

    response = client.create_monitoring_period(
        env["authorization_id"],
        f.build_monitoring_period_payload("2026-06"),
        env["lead_headers"],
    )

    validate_error(response, ERR_AUTHORIZATION_NOT_ACTIVE, 409)
    assert len(fx.list_monitoring_periods(client, env["authorization_id"])) == 3


# ---------------------------------------------------------------------------
# The finite reuse seat pool
# ---------------------------------------------------------------------------

_REUSING_AGENCIES = (
    ("epa", "Environmental Protection Agency", "EPA"),
    ("hhs", "Health and Human Services", "HHS"),
    ("doe", "Department of Energy", "DOE"),
    ("va", "Veterans Affairs", "VA"),
    ("gsa", "General Services Administration", "GSA"),
    ("nasa", "Aeronautics and Space Administration", "NASA"),
)


def _authorization_with_four_seats_taken(client):
    """A live authorization whose first four reuse seats are already granted."""
    env = fx.seed_authorized_offering(client)
    for key, name, code in _REUSING_AGENCIES:
        env = fx.add_agency(client, env, name=name, agency_code=code, key=key)
    for key in ("epa", "hhs", "doe", "va"):
        env = fx.seed_reuse_grant(
            client,
            env,
            agency_id=env[f"{key}_id"],
            agency_headers=env[f"{key}_headers"],
            key=f"{key}_grant",
        )
    return env


def _request_reuse(client, env, key):
    """One agency's reuse request, re-armed with the authorization's live version."""
    return client.create_reuse_grant(
        f.build_reuse_grant_payload(
            env["authorization_id"],
            env[f"{key}_id"],
            fx.authorization_version(client, env["authorization_id"]),
        ),
        env[f"{key}_headers"],
    )


def test_the_fifth_reuse_grant_consumes_the_last_seat(client):
    """The fifth distinct agency takes the last of the five seats.

    PRD: "Seats are finite — `reuse_seats_granted` counts the authorization's grants not in `REVOKED` and `reuse_seats_available` is `reuse_seats_total` less that count — and a request arriving when no seat is available is refused with `ERR_REUSE_SEATS_EXHAUSTED`."

    Design: Corner/errors/the_sixth_agency_finds_the_reuse_seat_pool_empty
    """
    env = _authorization_with_four_seats_taken(client)

    grant = validate_success(_request_reuse(client, env, "gsa"), 201)

    assert grant["access_state"] == "REQUESTED"
    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_total"], 5, "reuse_seats_total")
    a.assert_integer(authorization["reuse_seats_granted"], 5, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 0, "reuse_seats_available")
    a.assert_seat_conservation(authorization)


def test_the_sixth_agency_finds_the_reuse_seat_pool_empty(client):
    """The sixth agency is refused on the seat pool, not on the version check.

    PRD: "Seats are finite — `reuse_seats_granted` counts the authorization's grants not in `REVOKED` and `reuse_seats_available` is `reuse_seats_total` less that count — and a request arriving when no seat is available is refused with `ERR_REUSE_SEATS_EXHAUSTED`."

    Design: Corner/errors/the_sixth_agency_finds_the_reuse_seat_pool_empty
    """
    env = _authorization_with_four_seats_taken(client)
    validate_success(_request_reuse(client, env, "gsa"), 201)
    version_before = fx.authorization_version(client, env["authorization_id"])

    validate_error(
        _request_reuse(client, env, "nasa"), ERR_REUSE_SEATS_EXHAUSTED, 422
    )

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 5, "reuse_seats_granted")
    a.assert_integer(authorization["version"], version_before, "authorization version")
    a.assert_integer(
        fx.read_agency(client, env["nasa_id"])["reuse_grant_count"],
        0,
        "NASA reuse_grant_count",
    )
    a.assert_seat_conservation(authorization)


def test_revoking_a_grant_returns_its_seat_to_the_pool(client):
    """Revocation is compensating: one seat comes back to the ledger.

    PRD: "It returns the seat — the authorization's `reuse_seats_granted` decreases by one and `reuse_seats_available` increases by one — decrements the agency's `reuse_grant_count` by one, decrements that agency's `open_notice_count` by one when the grant was sitting in `NOTICE_ISSUED`, and increments the authorization's `version` by one."

    Design: Corner/errors/the_sixth_agency_finds_the_reuse_seat_pool_empty
    """
    env = _authorization_with_four_seats_taken(client)
    validate_success(_request_reuse(client, env, "gsa"), 201)

    grant = validate_success(
        client.revoke_reuse_grant(
            env["epa_grant_id"], f.build_revoke_payload("AGENCY_REQUEST"), env["epa_headers"]
        ),
        200,
    )

    assert grant["access_state"] == "REVOKED"
    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 4, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 1, "reuse_seats_available")
    a.assert_integer(
        fx.read_agency(client, env["epa_id"])["reuse_grant_count"],
        0,
        "EPA reuse_grant_count",
    )
    a.assert_seat_conservation(authorization)


def test_the_sixth_agency_succeeds_against_the_freed_seat(client):
    """The pool is a live ledger, so the freed seat is grantable again.

    PRD: "On success the grant opens with `access_state` `REQUESTED`, `incremental_review_findings_count` 0, `notice_count` 0, `reuse_accepted_at` null and `revoked_reason` null; the granting agency's `reuse_grant_count` increments by one and the authorization's `version` increments by one."

    Design: Corner/errors/the_sixth_agency_finds_the_reuse_seat_pool_empty
    """
    env = _authorization_with_four_seats_taken(client)
    validate_success(_request_reuse(client, env, "gsa"), 201)
    validate_error(_request_reuse(client, env, "nasa"), ERR_REUSE_SEATS_EXHAUSTED, 422)
    validate_success(
        client.revoke_reuse_grant(
            env["epa_grant_id"], f.build_revoke_payload("AGENCY_REQUEST"), env["epa_headers"]
        ),
        200,
    )

    grant = validate_success(_request_reuse(client, env, "nasa"), 201)

    assert grant["access_state"] == "REQUESTED"
    a.assert_integer(grant["notice_count"], 0, "notice_count")
    assert grant["reuse_accepted_at"] is None
    assert grant["revoked_reason"] is None
    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 5, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 0, "reuse_seats_available")
    a.assert_seat_conservation(authorization)
