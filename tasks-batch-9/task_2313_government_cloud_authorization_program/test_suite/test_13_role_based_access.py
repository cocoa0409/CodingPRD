"""Role-based access control across the four operating parties.

This file exercises the authorization matrix of the program API: the writes each
role owns exclusively, the handful of operations two roles co-own, and the two
places where a single role is held apart from itself by identity — the board
member who routes a deviation may not decide it, and the board member who
reviews a package may not authorize it. It also pins the precedence of the role
gate against the state, path-resolution and sponsorship checks that sit behind
it.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as tu
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_STATE,
    ERR_REUSE_GRANT_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_WRONG_REVIEW_QUEUE,
)
from test_helpers.assertions import assert_instant, assert_money
from test_helpers.constants import expected_letter_reference


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------


def _headers_for(env, role_key):
    """The request headers of one of the four roles, given a built ``env``."""
    return {
        "CspComplianceLead": tu.CSP_LEAD_HEADERS,
        "ThirdPartyAssessor": tu.ASSESSOR_HEADERS,
        "ProgramBoardReviewer": tu.BOARD_HEADERS,
        "AgencyAuthorizingOfficial": env["agency_headers"],
    }[role_key]


ALL_FOUR_ROLES = (
    "CspComplianceLead",
    "ThirdPartyAssessor",
    "ProgramBoardReviewer",
    "AgencyAuthorizingOfficial",
)


def _categorized_offering(client):
    """A CATEGORIZED offering with one CONFIRMED MODERATE category and nothing else."""
    env = fx.seed_reference_data(client)
    return fx.seed_categorized_offering(client, env)


def _offering_in_assessment(client):
    """An IN_ASSESSMENT offering sponsored by DOT whose engagement is PLAN_APPROVED."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(
        client, env, authorization_path="AGENCY_SPONSORED"
    )
    env = fx.seed_control_implementations(client, env)
    return fx.seed_engagement(client, env)


def _board_path_package_under_review(client):
    """A PROGRAM_BOARD package taken into review by board-1, with no sponsor agency."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(
        client, env, authorization_path="PROGRAM_BOARD"
    )
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_report_delivered(client, env, report_at=fx.AUTHORIZATION_CLOCK)
    env = fx.seed_package(client, env)
    env = fx.submit_package(client, env)
    return fx.review_package(client, env, reviewer=tu.BOARD_1)


# ===========================================================================
# The provider's exclusive writes
# ===========================================================================

#: The provider-only writes of PRD 4, each probed from a role that owns a
#: neighbouring part of the same workflow.
_CSP_EXCLUSIVE_PROBES = (
    (
        "create_offering_as_board",
        lambda client, env: client.create_offering(
            f.build_offering_payload(
                name="Rogue Service",
                service_model="SAAS",
                assessment_budget_usd=100000.00,
            ),
            tu.BOARD_HEADERS,
        ),
    ),
    (
        "declare_data_category_as_agency_official",
        lambda client, env: client.create_data_category(
            env["offering_id"],
            f.build_data_category_payload(
                category_code="PHI",
                confidentiality_impact="LOW",
                integrity_impact="LOW",
                availability_impact="LOW",
            ),
            env["agency_headers"],
        ),
    ),
    (
        "select_path_as_board",
        lambda client, env: client.select_path(
            env["offering_id"],
            f.build_path_selection_payload(authorization_path="PROGRAM_BOARD"),
            tu.BOARD_HEADERS,
        ),
    ),
    (
        "record_control_implementation_as_assessor",
        lambda client, env: client.create_control_implementation(
            f.build_control_implementation_payload(
                env["offering_id"],
                control_id="AC-2",
                family_code="AC",
                crm_documented=False,
            ),
            tu.ASSESSOR_HEADERS,
        ),
    ),
    (
        "create_engagement_as_board",
        lambda client, env: client.create_engagement(
            f.build_engagement_payload(env["offering_id"]), tu.BOARD_HEADERS
        ),
    ),
    (
        "file_finding_as_assessor",
        lambda client, env: client.create_poam_item(
            f.build_poam_item_payload(
                env["offering_id"], severity="LOW", detected_at=fx.SETUP_CLOCK
            ),
            tu.ASSESSOR_HEADERS,
        ),
    ),
    (
        "file_change_request_as_agency_official",
        lambda client, env: client.create_change_request(
            f.build_change_request_payload(
                env["offering_id"],
                "2026-04-01T00:00:00Z",
                "2026-04-15T00:00:00Z",
                change_kind="BOUNDARY_CHANGE",
            ),
            env["agency_headers"],
        ),
    ),
)


@pytest.mark.parametrize(
    "probe_name, probe",
    _CSP_EXCLUSIVE_PROBES,
    ids=[name for name, _ in _CSP_EXCLUSIVE_PROBES],
)
def test_provider_exclusive_writes_are_refused_to_the_other_three_roles(
    client, probe_name, probe
):
    """Each provider-only write is a flat 403 when any other role attempts it.

    PRD: "When the acting role is not listed as authorized for the endpoint being called (see §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/every_csp_exclusive_write_is_closed_to_the_other_three_roles
    """
    env = _categorized_offering(client)

    validate_error(probe(client, env), ERR_FORBIDDEN_ROLE, 403)

    # The refusal left the hub row alone: the offering still sits at the version
    # its create, category declaration, confirmation and determination produced.
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["version"] == 4, (
        f"{probe_name} must not touch the offering, "
        f"expected version 4, got {offering['version']}"
    )
    assert offering["status"] == "CATEGORIZED"

    # No second offering row was minted by the refused create.
    _, meta = validate_paginated(client.list_offerings(tu.BOARD_HEADERS))
    assert meta["total_count"] == 1


def test_the_provider_role_gate_is_reported_before_the_offering_state_gate(client):
    """A foreign role earns 403 on a write the offering's own state would also refuse.

    PRD: "Checks are therefore evaluated in one fixed global order, and the first failing check determines the response."

    Design: Corner/rbac/every_csp_exclusive_write_is_closed_to_the_other_three_roles
    """
    env = _categorized_offering(client)
    category_payload = f.build_data_category_payload(
        category_code="PHI",
        confidentiality_impact="LOW",
        integrity_impact="LOW",
        availability_impact="LOW",
    )
    change_payload = f.build_change_request_payload(
        env["offering_id"],
        "2026-04-01T00:00:00Z",
        "2026-04-15T00:00:00Z",
        change_kind="BOUNDARY_CHANGE",
    )

    # An agency official is stopped at the role tier, never reaching the state tier.
    validate_error(
        client.create_data_category(
            env["offering_id"], category_payload, env["agency_headers"]
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        client.create_change_request(change_payload, env["agency_headers"]),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # The owning provider passes the role tier and is then refused by the state
    # tier on the very same two calls, which is what proves the ordering.
    validate_error(
        client.create_data_category(
            env["offering_id"], category_payload, env["lead_headers"]
        ),
        ERR_INVALID_STATE,
        409,
    )
    validate_error(
        client.create_change_request(change_payload, env["lead_headers"]),
        ERR_INVALID_STATE,
        409,
    )


def test_the_owning_provider_records_the_control_implementation_and_the_finding(client):
    """The two writes refused to the assessor are accepted from the compliance lead.

    PRD: "Against the bound baseline, the compliance lead records one **control implementation** per control."

    Design: Corner/rbac/every_csp_exclusive_write_is_closed_to_the_other_three_roles
    """
    env = _categorized_offering(client)

    implementation = validate_success(
        client.create_control_implementation(
            f.build_control_implementation_payload(
                env["offering_id"], control_id="AC-2", family_code="AC"
            ),
            env["lead_headers"],
        ),
        201,
    )
    assert implementation["control_id"] == "AC-2"

    finding = validate_success(
        client.create_poam_item(
            f.build_poam_item_payload(
                env["offering_id"], severity="LOW", detected_at=fx.SETUP_CLOCK
            ),
            env["lead_headers"],
        ),
        201,
    )
    assert finding["remediation_status"] == "OPEN"

    # Neither accepted write is one of the offering-version-bumping operations.
    assert fx.read_offering(client, env["offering_id"])["version"] == 4


# ===========================================================================
# The board's, assessor's and agency's exclusive writes
# ===========================================================================

#: Every remaining exclusive operation, probed from a role that owns a
#: neighbouring part of the same workflow.
_NON_PROVIDER_EXCLUSIVE_PROBES = (
    (
        "register_agency_as_provider",
        lambda client, env: client.create_agency(
            f.build_agency_payload(
                name="Small Business Administration", agency_code="SBA"
            ),
            tu.CSP_LEAD_HEADERS,
        ),
    ),
    (
        "publish_baseline_as_agency_official",
        lambda client, env: client.create_control_baseline(
            f.build_baseline_payload(
                impact_level="HIGH", families=[f.build_family("AC", 4, 1)]
            ),
            env["agency_headers"],
        ),
    ),
    (
        "determine_impact_as_provider",
        lambda client, env: client.determine_impact(
            env["offering_id"], {}, tu.CSP_LEAD_HEADERS
        ),
    ),
    (
        "set_clock_as_provider",
        lambda client, env: client.set_clock(
            f.build_clock_payload("2026-03-01T00:00:00Z"), tu.CSP_LEAD_HEADERS
        ),
    ),
    (
        "schedule_test_slot_as_provider",
        lambda client, env: client.create_test_slot(
            f.build_test_slot_payload(env["engagement_id"]), tu.CSP_LEAD_HEADERS
        ),
    ),
    (
        "submit_assessment_plan_as_provider",
        lambda client, env: client.submit_plan(
            env["engagement_id"], f.build_plan_payload(), tu.CSP_LEAD_HEADERS
        ),
    ),
    (
        "deliver_assessment_report_as_board",
        lambda client, env: client.deliver_report(
            env["engagement_id"], f.build_report_payload([]), tu.BOARD_HEADERS
        ),
    ),
    (
        "record_incremental_review_as_board",
        lambda client, env: client.record_incremental_review(
            NON_EXISTENT_UUID,
            f.build_incremental_review_payload("ACCEPT", 0),
            tu.BOARD_HEADERS,
        ),
    ),
)


@pytest.mark.parametrize(
    "probe_name, probe",
    _NON_PROVIDER_EXCLUSIVE_PROBES,
    ids=[name for name, _ in _NON_PROVIDER_EXCLUSIVE_PROBES],
)
def test_board_assessor_and_agency_exclusive_writes_are_closed_to_each_other(
    client, probe_name, probe
):
    """No role stands in for another: every remaining exclusive write is a flat 403.

    PRD: "When the acting role is not listed as authorized for the endpoint being called (see §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/the_board_assessor_and_agency_exclusive_writes_are_closed_to_each_other
    """
    env = _offering_in_assessment(client)

    validate_error(probe(client, env), ERR_FORBIDDEN_ROLE, 403)


def test_the_refused_writes_leave_the_clock_and_the_plan_round_untouched(client):
    """A refused clock move and a refused plan submission change no server state.

    PRD: "A `ProgramBoardReviewer` may move the clock by supplying a `to_iso8601` instant; the response reports the new setting as `current_utc`."

    Design: Corner/rbac/the_board_assessor_and_agency_exclusive_writes_are_closed_to_each_other
    """
    env = _offering_in_assessment(client)

    validate_error(
        client.set_clock(
            f.build_clock_payload("2026-03-01T00:00:00Z"), tu.CSP_LEAD_HEADERS
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        client.submit_plan(
            env["engagement_id"], f.build_plan_payload(), tu.CSP_LEAD_HEADERS
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # The logical clock is observable through any computed read's evaluated_at.
    coverage = validate_success(
        client.get_crm_coverage(env["offering_id"], tu.BOARD_HEADERS), 200
    )
    assert_instant(coverage["evaluated_at"], fx.SETUP_CLOCK, "evaluated_at")

    engagement = fx.read_engagement(client, env["engagement_id"])
    assert engagement["plan_revision_round"] == 0
    assert engagement["status"] == "PLAN_APPROVED"


def test_the_role_gate_precedes_the_path_lookup_on_an_unknown_reuse_grant(client):
    """A board reviewer reaching into the agency's reuse endpoint is refused by role, not by 404.

    PRD: "Checks are therefore evaluated in one fixed global order, and the first failing check determines the response."

    Design: Corner/rbac/the_board_assessor_and_agency_exclusive_writes_are_closed_to_each_other
    """
    env = _offering_in_assessment(client)
    payload = f.build_incremental_review_payload("ACCEPT", 0)

    # The role tier fires even though the path identifier names no row at all.
    validate_error(
        client.record_incremental_review(NON_EXISTENT_UUID, payload, tu.BOARD_HEADERS),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # The role that owns the endpoint gets as far as resolving the path.
    validate_error(
        client.record_incremental_review(
            NON_EXISTENT_UUID, payload, env["agency_headers"]
        ),
        ERR_REUSE_GRANT_NOT_FOUND,
        404,
    )


def test_the_owning_roles_register_the_agency_and_schedule_the_test_slot(client):
    """The two writes refused to their neighbours are accepted from their owners.

    PRD: "The first slot of an engagement also moves it `PLAN_APPROVED → TESTING`; every slot creation increments the engagement's `version` by one."

    Design: Corner/rbac/the_board_assessor_and_agency_exclusive_writes_are_closed_to_each_other
    """
    env = _offering_in_assessment(client)

    agency = validate_success(
        client.create_agency(
            f.build_agency_payload(
                name="Small Business Administration", agency_code="SBA"
            ),
            tu.BOARD_HEADERS,
        ),
        201,
    )
    assert agency["agency_code"] == "SBA"

    slot = validate_success(
        client.create_test_slot(
            f.build_test_slot_payload(env["engagement_id"]), env["assessor_headers"]
        ),
        201,
    )
    assert slot["status"] == "SCHEDULED"

    engagement = fx.read_engagement(client, env["engagement_id"])
    assert_money(engagement["allocated_hours"], 8.00, "allocated_hours")
    assert_money(engagement["unallocated_hours"], 192.00, "unallocated_hours")
    assert engagement["status"] == "TESTING"


# ===========================================================================
# The co-owned monitoring operations
# ===========================================================================


def _authorized_offering_with_scanned_first_period(client):
    """A live authorization whose 2026-03 period has its three mandatory scans in."""
    env = fx.seed_authorized_offering(client)
    fx.submit_scans(client, env, env["period_id"])
    return env


def test_closing_a_monitoring_period_accepts_the_board_or_the_agency_but_not_the_provider(
    client,
):
    """Opening a period and closing one are different privileges, and the provider holds only the first.

    PRD: "Closing a period is a government act performed by a `ProgramBoardReviewer` or an `AgencyAuthorizingOfficial`."

    Design: Corner/rbac/the_monitoring_shared_operations_accept_either_of_their_two_owning_roles
    """
    env = _authorized_offering_with_scanned_first_period(client)
    fx.set_clock(client, "2026-04-01T00:00:00Z")

    # The provider who submitted the scans may not sign the month off.
    validate_error(
        client.close_monitoring_period(env["period_id"], tu.CSP_LEAD_HEADERS),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    assert fx.read_monitoring_period(client, env["period_id"])["status"] == "OPEN"

    # The sponsoring agency's official closes 2026-03 compliant.
    march = validate_success(
        client.close_monitoring_period(env["period_id"], env["agency_headers"]), 200
    )
    assert march["status"] == "CLOSED_COMPLIANT"

    # The board closes the auto-created 2026-04 the same way.
    periods = fx.list_monitoring_periods(client, env["authorization_id"])
    april = periods[1]
    assert april["period_month"] == "2026-04"
    fx.set_clock(client, "2026-05-01T00:00:00Z")
    fx.submit_scans(client, env, april["id"])
    closed_april = validate_success(
        client.close_monitoring_period(april["id"], tu.BOARD_HEADERS), 200
    )
    assert closed_april["status"] == "CLOSED_COMPLIANT"

    authorization = fx.read_authorization(client, env["authorization_id"])
    assert authorization["consecutive_deficient_periods"] == 0
    assert authorization["monitoring_posture"] == "ACTIVE"


def test_opening_a_monitoring_period_accepts_either_the_provider_or_the_board(client):
    """The period-opening endpoint is co-owned by the compliance lead and the program board.

    PRD: "Opening a period may be done by a `CspComplianceLead` or a `ProgramBoardReviewer`, and requires the authorization to be in `authorization_status` `AUTHORIZED` with a `monitoring_posture` other than `ESCALATED`, else `ERR_AUTHORIZATION_NOT_ACTIVE`."

    Design: Corner/rbac/the_monitoring_shared_operations_accept_either_of_their_two_owning_roles
    """
    env = fx.seed_authorized_offering(client)

    by_provider = validate_success(
        client.create_monitoring_period(
            env["authorization_id"],
            f.build_monitoring_period_payload("2026-05"),
            env["lead_headers"],
        ),
        201,
    )
    assert by_provider["period_month"] == "2026-05"
    assert by_provider["status"] == "OPEN"

    by_board = validate_success(
        client.create_monitoring_period(
            env["authorization_id"],
            f.build_monitoring_period_payload("2026-06"),
            tu.BOARD_HEADERS,
        ),
        201,
    )
    assert by_board["period_month"] == "2026-06"

    # The role that may open a period still may not close one.
    validate_error(
        client.close_monitoring_period(env["period_id"], tu.CSP_LEAD_HEADERS),
        ERR_FORBIDDEN_ROLE,
        403,
    )


def test_a_compliant_close_auto_creates_the_next_month_and_skips_an_existing_one(client):
    """The close creates 2026-04 but declines to duplicate the already-opened 2026-05.

    PRD: "And the next month's monitoring period is auto-created by the close whenever the authorization's `authorization_status` after the close is `AUTHORIZED` or `SUSPENDED` — that creation is skipped when a period for that `period_month` already exists for the authorization, and no further period is auto-created once the authorization has reached `REVOKED` or `EXPIRED`."

    Design: Corner/rbac/the_monitoring_shared_operations_accept_either_of_their_two_owning_roles
    """
    env = _authorized_offering_with_scanned_first_period(client)
    fx.set_clock(client, "2026-04-01T00:00:00Z")
    validate_success(
        client.close_monitoring_period(env["period_id"], env["agency_headers"]), 200
    )

    periods = fx.list_monitoring_periods(client, env["authorization_id"])
    assert [row["period_month"] for row in periods] == ["2026-03", "2026-04"]
    assert periods[1]["status"] == "OPEN"

    # 2026-05 is opened by hand before 2026-04 is closed, so the close finds it
    # already present and creates nothing.
    may = validate_success(
        client.create_monitoring_period(
            env["authorization_id"],
            f.build_monitoring_period_payload("2026-05"),
            tu.BOARD_HEADERS,
        ),
        201,
    )
    fx.set_clock(client, "2026-05-01T00:00:00Z")
    fx.submit_scans(client, env, periods[1]["id"])
    validate_success(
        client.close_monitoring_period(periods[1]["id"], tu.BOARD_HEADERS), 200
    )

    _, meta = validate_paginated(
        client.list_monitoring_periods(env["authorization_id"], tu.BOARD_HEADERS)
    )
    assert meta["total_count"] == 3
    assert fx.read_monitoring_period(client, may["id"])["status"] == "OPEN"


@pytest.mark.parametrize("role", ALL_FOUR_ROLES)
def test_the_monitoring_read_surfaces_stay_open_to_all_four_roles(client, role):
    """Every monitoring read is legible to the provider, assessor, board and agency alike.

    PRD: "All read endpoints in §4 are open to all four roles, with the single exception described at the end of this subsection."

    Design: Corner/rbac/the_monitoring_shared_operations_accept_either_of_their_two_owning_roles
    """
    env = _authorized_offering_with_scanned_first_period(client)
    headers = _headers_for(env, role)

    authorization = validate_success(
        client.get_authorization(env["authorization_id"], headers), 200
    )
    assert authorization["id"] == env["authorization_id"]
    assert authorization["authorization_status"] == "AUTHORIZED"

    periods, _ = validate_paginated(
        client.list_monitoring_periods(env["authorization_id"], headers)
    )
    assert [row["id"] for row in periods] == [env["period_id"]]

    period = validate_success(
        client.get_monitoring_period(env["period_id"], headers), 200
    )
    assert period["period_month"] == "2026-03"

    submissions, _ = validate_paginated(
        client.list_scan_submissions(env["period_id"], headers)
    )
    assert len(submissions) == 1


# ===========================================================================
# The co-owned categorization decision
# ===========================================================================


def _draft_offering_with_two_declared_categories(client):
    """A DRAFT offering at version 3 with DECLARED PII (M/M/L) and PHI (H/M/L)."""
    env = fx.seed_reference_data(client)
    fx.create_baseline(
        client,
        impact_level="HIGH",
        families=[f.build_family("AC", 4, 1), f.build_family("SC", 2, 2)],
    )
    env = fx.seed_draft_offering(client, env)
    return fx.declare_categories(
        client,
        env,
        [
            {
                "category_code": "PII",
                "confidentiality_impact": "MODERATE",
                "integrity_impact": "MODERATE",
                "availability_impact": "LOW",
            },
            {
                "category_code": "PHI",
                "confidentiality_impact": "HIGH",
                "integrity_impact": "MODERATE",
                "availability_impact": "LOW",
            },
        ],
    )


def _category_by_code(client, offering_id, category_code):
    """One of the offering's declared categories, looked up by its code."""
    rows, _ = validate_paginated(
        client.list_data_categories(offering_id, tu.BOARD_HEADERS)
    )
    matches = [row for row in rows if row["category_code"] == category_code]
    assert len(matches) == 1, f"expected one {category_code} category, got {matches}"
    return matches[0]


def test_the_provider_may_not_confirm_the_categories_it_declared(client):
    """The declarer is not the confirmer: the compliance lead is refused at the role tier.

    PRD: "A `ProgramBoardReviewer` or an `AgencyAuthorizingOfficial` reviews a `DECLARED` category with a `decision` of either `CONFIRM`, which moves it `DECLARED → CONFIRMED`, or `WITHDRAW`, which moves it `DECLARED → WITHDRAWN`."

    Design: Corner/rbac/data_category_confirmation_accepts_either_the_board_or_an_agency_official
    """
    env = _draft_offering_with_two_declared_categories(client)
    pii_id = env["data_categories"]["PII"]["id"]

    validate_error(
        client.confirm_data_category(
            pii_id, f.build_category_decision_payload("CONFIRM"), env["lead_headers"]
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    # The refused confirmation wrote nothing on either category.
    for code in ("PII", "PHI"):
        row = _category_by_code(client, env["offering_id"], code)
        assert row["status"] == "DECLARED"
        assert row["confirmed_by_user_id"] is None
    assert fx.read_offering(client, env["offering_id"])["version"] == 3


def test_a_non_sponsoring_agency_official_may_confirm_and_the_board_may_withdraw(client):
    """The categorization gate is co-owned before any sponsorship exists.

    PRD: "Both legs require the category to still be `DECLARED` and the parent offering to still be in `DRAFT`, both write `confirmed_by_user_id` from the reviewer's `X-User-ID`, and both recompute the offering's `preliminary_impact_level` and increment the offering's `version` by one."

    Design: Corner/rbac/data_category_confirmation_accepts_either_the_board_or_an_agency_official
    """
    env = _draft_offering_with_two_declared_categories(client)

    # DOT sponsors nothing at all, so this cannot be a sponsorship check.
    assert env["agency"]["sponsored_offering_count"] == 0
    confirmed = validate_success(
        client.confirm_data_category(
            env["data_categories"]["PII"]["id"],
            f.build_category_decision_payload("CONFIRM"),
            env["agency_headers"],
        ),
        200,
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_by_user_id"] == env["agency_id"]

    withdrawn = validate_success(
        client.confirm_data_category(
            env["data_categories"]["PHI"]["id"],
            f.build_category_decision_payload("WITHDRAW"),
            tu.BOARD_HEADERS,
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["confirmed_by_user_id"] == tu.BOARD_1


def test_both_categorization_decisions_move_the_parent_offering_version(client):
    """Each confirmation and each withdrawal increments the offering's version by one.

    PRD: "The offering is the hub: confirming or withdrawing a data category, determining the impact level, selecting the path, approving an assessment plan, submitting a package, deciding a package, filing a change request and deciding a change request each increment the offering's `version` by one in addition to whatever they write on their own resource."

    Design: Corner/rbac/data_category_confirmation_accepts_either_the_board_or_an_agency_official
    """
    env = _draft_offering_with_two_declared_categories(client)
    assert fx.read_offering(client, env["offering_id"])["version"] == 3

    validate_success(
        client.confirm_data_category(
            env["data_categories"]["PII"]["id"],
            f.build_category_decision_payload("CONFIRM"),
            env["agency_headers"],
        ),
        200,
    )
    assert fx.read_offering(client, env["offering_id"])["version"] == 4

    validate_success(
        client.confirm_data_category(
            env["data_categories"]["PHI"]["id"],
            f.build_category_decision_payload("WITHDRAW"),
            tu.BOARD_HEADERS,
        ),
        200,
    )
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["version"] == 5
    assert offering["version"] != 3


def test_the_withdrawn_high_category_leaves_the_final_impact_level_at_moderate(client):
    """A withdrawal by the board takes the HIGH claim out of every later computation.

    PRD: "`WITHDRAWN` is terminal for a category, and a withdrawn category is invisible to every impact computation thereafter."

    Design: Corner/rbac/data_category_confirmation_accepts_either_the_board_or_an_agency_official
    """
    env = _draft_offering_with_two_declared_categories(client)
    validate_success(
        client.confirm_data_category(
            env["data_categories"]["PII"]["id"],
            f.build_category_decision_payload("CONFIRM"),
            env["agency_headers"],
        ),
        200,
    )
    validate_success(
        client.confirm_data_category(
            env["data_categories"]["PHI"]["id"],
            f.build_category_decision_payload("WITHDRAW"),
            tu.BOARD_HEADERS,
        ),
        200,
    )

    determined = validate_success(
        client.determine_impact(env["offering_id"], {}, tu.BOARD_HEADERS), 200
    )
    assert determined["final_impact_level"] == "MODERATE"
    assert determined["final_impact_level"] != "HIGH"
    assert determined["status"] == "CATEGORIZED"
    assert determined["baseline_id"] == env["baseline_id"]


# ===========================================================================
# Segregation of duties on a deviation request
# ===========================================================================


def _deviation_awaiting_routing(client):
    """A CATEGORIZED offering with one OPEN MODERATE finding under an unrouted deviation."""
    env = fx.seed_reference_data(client)
    env = fx.seed_categorized_offering(client, env)
    env = fx.seed_poam_item(
        client, env, severity="MODERATE", detected_at=fx.SETUP_CLOCK, control_id="AC-2"
    )
    return fx.seed_deviation(
        client,
        env,
        env["poam_id"],
        kind="OPERATIONAL_REQUIREMENT",
        requested_extension_days=45,
    )


def test_an_operational_requirement_deviation_may_not_be_routed_to_the_agency_queue(
    client,
):
    """The queue must be legal for the request's kind, and the agency queue is not.

    PRD: "A `RISK_ADJUSTMENT` may not go to the board queue and an `OPERATIONAL_REQUIREMENT` may not go to the agency queue; the agency queue additionally requires the finding's offering to be on the `AGENCY_SPONSORED` path with a sponsor agency present."

    Design: Corner/rbac/the_board_member_who_routes_a_deviation_may_not_be_the_one_who_decides_it
    """
    env = _deviation_awaiting_routing(client)

    validate_error(
        client.route_deviation(
            env["deviation_id"], f.build_route_payload("AGENCY"), tu.BOARD_HEADERS
        ),
        ERR_WRONG_REVIEW_QUEUE,
        403,
    )
    refused = fx.read_deviation(client, env["deviation_id"])
    assert refused["status"] == "SUBMITTED"
    assert refused["review_queue"] is None
    assert refused["routed_by_user_id"] is None

    routed = validate_success(
        client.route_deviation(
            env["deviation_id"], f.build_route_payload("BOARD"), tu.BOARD_HEADERS
        ),
        200,
    )
    assert routed["status"] == "BOARD_REVIEW"
    assert routed["review_queue"] == "BOARD"
    assert routed["routed_by_user_id"] == tu.BOARD_1


def test_a_board_queue_deviation_decision_is_closed_to_the_agency_official(client):
    """The BOARD queue belongs to a program board reviewer, not to an agency official.

    PRD: "A deviation routed to the board queue may only be decided by a `ProgramBoardReviewer`; a deviation routed to the agency queue may only be decided by an `AgencyAuthorizingOfficial`; and on the `PROGRAM_BOARD` authorization path, package decisions and significant-change decisions belong to a `ProgramBoardReviewer` while on the `AGENCY_SPONSORED` path they belong to the sponsoring agency's official."

    Design: Corner/rbac/the_board_member_who_routes_a_deviation_may_not_be_the_one_who_decides_it
    """
    env = _deviation_awaiting_routing(client)
    validate_success(
        client.route_deviation(
            env["deviation_id"], f.build_route_payload("BOARD"), tu.BOARD_HEADERS
        ),
        200,
    )

    validate_error(
        client.decide_deviation(
            env["deviation_id"],
            f.build_deviation_decision_payload("APPROVE"),
            env["agency_headers"],
        ),
        ERR_WRONG_REVIEW_QUEUE,
        403,
    )
    still_open = fx.read_deviation(client, env["deviation_id"])
    assert still_open["status"] == "BOARD_REVIEW"
    assert still_open["decided_by_user_id"] is None


def test_the_board_member_who_routed_the_deviation_may_not_decide_it(client):
    """Segregation of duties is an identity comparison, not a role comparison.

    PRD: "The board member who routes a deviation request into a review queue may not be the board member who decides it: on a deviation decision the acting `X-User-ID` must differ from the request's recorded `routed_by_user_id`, and an equal value is refused with `ERR_SEGREGATION_OF_DUTIES` (409)."

    Design: Corner/rbac/the_board_member_who_routes_a_deviation_may_not_be_the_one_who_decides_it
    """
    env = _deviation_awaiting_routing(client)
    validate_success(
        client.route_deviation(
            env["deviation_id"], f.build_route_payload("BOARD"), tu.BOARD_HEADERS
        ),
        200,
    )

    validate_error(
        client.decide_deviation(
            env["deviation_id"],
            f.build_deviation_decision_payload("APPROVE"),
            tu.BOARD_HEADERS,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    refused = fx.read_deviation(client, env["deviation_id"])
    assert refused["status"] == "BOARD_REVIEW"
    assert refused["decided_by_user_id"] is None
    assert refused["granted_extension_days"] == 0

    # The finding keeps its unextended MODERATE deadline: 2026-02-01 plus 90 days.
    finding = fx.read_poam_item(client, env["poam_id"])
    assert finding["risk_disposition"] == "DEVIATION_REQUESTED"
    assert_instant(finding["deadline_at"], "2026-05-02T00:00:00Z", "deadline_at")


def test_the_second_board_member_approves_the_extension_and_moves_the_deadline(client):
    """board-2 carries the same role as board-1 and may decide what board-1 routed.

    PRD: "Approving an `OPERATIONAL_REQUIREMENT` request in the board queue sets the request's `granted_extension_days` to the `requested_extension_days` figure, copies that figure onto the finding's own `granted_extension_days`, recomputes the finding's `deadline_at` from its anchor with the extension included, moves the finding's `risk_disposition` `DEVIATION_REQUESTED → EXTENSION_GRANTED`, and recomputes the authorization's `residual_risk_score`."

    Design: Corner/rbac/the_board_member_who_routes_a_deviation_may_not_be_the_one_who_decides_it
    """
    env = _deviation_awaiting_routing(client)
    validate_success(
        client.route_deviation(
            env["deviation_id"], f.build_route_payload("BOARD"), tu.BOARD_HEADERS
        ),
        200,
    )

    decided = validate_success(
        client.decide_deviation(
            env["deviation_id"],
            f.build_deviation_decision_payload("APPROVE"),
            tu.BOARD_2_HEADERS,
        ),
        200,
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == tu.BOARD_2
    assert decided["granted_extension_days"] == 45

    finding = fx.read_poam_item(client, env["poam_id"])
    assert finding["risk_disposition"] == "EXTENSION_GRANTED"
    assert finding["granted_extension_days"] == 45
    assert_instant(finding["deadline_at"], "2026-06-16T00:00:00Z", "deadline_at")


# ===========================================================================
# Segregation of duties on an authorization package
# ===========================================================================


def test_program_review_stamps_the_reviewing_board_member(client):
    """Submission and completeness review are two acts by two different parties.

    PRD: "A `ProgramBoardReviewer` first takes a `SUBMITTED` package into review, moving it `SUBMITTED → UNDER_REVIEW` and stamping `reviewed_by_user_id` from their own `X-User-ID`."

    Design: Corner/rbac/the_board_member_who_reviews_a_package_may_not_be_the_one_who_authorizes_it
    """
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(
        client, env, authorization_path="PROGRAM_BOARD"
    )
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_report_delivered(client, env, report_at=fx.AUTHORIZATION_CLOCK)
    env = fx.seed_package(client, env)

    submitted = validate_success(
        client.submit_package(env["package_id"], env["lead_headers"]), 200
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_round"] == 1

    reviewed = validate_success(
        client.review_package(env["package_id"], tu.BOARD_HEADERS), 200
    )
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["reviewed_by_user_id"] == tu.BOARD_1


def test_a_program_board_package_decision_is_closed_to_an_agency_official(client):
    """A PROGRAM_BOARD package has no sponsor to check, so the queue tier refuses first.

    PRD: "On the `PROGRAM_BOARD` path it belongs to a `ProgramBoardReviewer`, anyone else being refused with `ERR_WRONG_REVIEW_QUEUE`, and that reviewer's `X-User-ID` must differ from the package's `reviewed_by_user_id`, an equal value being refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_board_member_who_reviews_a_package_may_not_be_the_one_who_authorizes_it
    """
    env = _board_path_package_under_review(client)
    assert fx.read_offering(client, env["offering_id"])["sponsor_agency_id"] is None

    validate_error(
        client.decide_package(
            env["package_id"],
            f.build_package_decision_payload(
                "AUTHORIZE", risk_acceptance_note="Board accepts the residual risk."
            ),
            env["agency_headers"],
        ),
        ERR_WRONG_REVIEW_QUEUE,
        403,
    )

    package = fx.read_package(client, env["package_id"])
    assert package["status"] == "UNDER_REVIEW"
    assert package["letter_reference"] is None
    _, meta = validate_paginated(
        client.list_authorizations(tu.BOARD_HEADERS, {"package_id": env["package_id"]})
    )
    assert meta["total_count"] == 0


def test_the_board_reviewer_may_not_issue_the_authorization_decision(client):
    """The identity split is the only thing between one person and a self-authorized package.

    PRD: "Likewise, the board member who performs the completeness review of an authorization package may not issue the program-board authorization decision for it: on a `PROGRAM_BOARD` package decision the acting `X-User-ID` must differ from the package's recorded `reviewed_by_user_id`, and an equal value is refused with the same error."

    Design: Corner/rbac/the_board_member_who_reviews_a_package_may_not_be_the_one_who_authorizes_it
    """
    env = _board_path_package_under_review(client)

    validate_error(
        client.decide_package(
            env["package_id"],
            f.build_package_decision_payload(
                "AUTHORIZE", risk_acceptance_note="Board accepts the residual risk."
            ),
            tu.BOARD_HEADERS,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        409,
    )

    package = fx.read_package(client, env["package_id"])
    assert package["status"] == "UNDER_REVIEW"
    assert package["status"] != "AUTHORIZED"
    assert package["letter_reference"] is None
    assert fx.read_offering(client, env["offering_id"])["status"] == "PACKAGE_SUBMITTED"
    _, meta = validate_paginated(
        client.list_authorizations(tu.BOARD_HEADERS, {"package_id": env["package_id"]})
    )
    assert meta["total_count"] == 0


def test_a_second_board_member_authorizes_the_package_and_mints_the_board_letter(client):
    """board-2 issues the decision board-1 could not, and the letter names the board.

    PRD: "An `AUTHORIZE` decision moves the package `UNDER_REVIEW → AUTHORIZED` and mints its `letter_reference`, formatted as `AUTH-LTR-` followed by the package's `submission_round` and then by the sponsoring agency's `agency_code` on the sponsored path or the literal `BOARD` on the program-board path."

    Design: Corner/rbac/the_board_member_who_reviews_a_package_may_not_be_the_one_who_authorizes_it
    """
    env = _board_path_package_under_review(client)

    decided = validate_success(
        client.decide_package(
            env["package_id"],
            f.build_package_decision_payload(
                "AUTHORIZE", risk_acceptance_note="Board accepts the residual risk."
            ),
            tu.BOARD_2_HEADERS,
        ),
        200,
    )
    assert decided["status"] == "AUTHORIZED"
    assert decided["letter_reference"] == expected_letter_reference(1)


def test_the_authorization_cascade_runs_exactly_once_after_the_two_refusals(client):
    """The refused decisions mint nothing, and board-2's decision fires each link once.

    PRD: "Where §3 describes a chain — a package decision creating an authorization, that authorization creating the first monitoring period; a deficient period close incrementing a run counter, that counter moving the monitoring posture, that posture issuing reuse notices, those notices incrementing an agency counter — every link fires within the one request, not lazily and not on a subsequent read."

    Design: Corner/rbac/the_board_member_who_reviews_a_package_may_not_be_the_one_who_authorizes_it
    """
    env = _board_path_package_under_review(client)
    decision_payload = f.build_package_decision_payload(
        "AUTHORIZE", risk_acceptance_note="Board accepts the residual risk."
    )

    validate_error(
        client.decide_package(
            env["package_id"], decision_payload, env["agency_headers"]
        ),
        ERR_WRONG_REVIEW_QUEUE,
        403,
    )
    validate_error(
        client.decide_package(env["package_id"], decision_payload, tu.BOARD_HEADERS),
        ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    validate_success(
        client.decide_package(env["package_id"], decision_payload, tu.BOARD_2_HEADERS),
        200,
    )

    authorizations, meta = validate_paginated(
        client.list_authorizations(tu.BOARD_HEADERS, {"package_id": env["package_id"]})
    )
    assert meta["total_count"] == 1
    authorization = authorizations[0]
    assert authorization["authorization_status"] == "AUTHORIZED"
    assert authorization["monitoring_posture"] == "ACTIVE"
    assert fx.read_offering(client, env["offering_id"])["status"] == "AUTHORIZED"

    periods, period_meta = validate_paginated(
        client.list_monitoring_periods(authorization["id"], tu.BOARD_HEADERS)
    )
    assert period_meta["total_count"] == 1
    assert periods[0]["period_month"] == "2026-03"
    assert periods[0]["status"] == "OPEN"
