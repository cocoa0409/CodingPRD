"""Validation rules and their fixed precedence across the program API.

This file covers the refusal side of the contract: which reason is reported when
several checks fail at once on one request, the per-offering uniqueness of
control identifiers and category codes, the customer-responsibility-matrix text
coupling, the inclusive detection-instant boundary, the sponsorship capacity
ceiling, the reuse-grant gate on a package read, and the two-step categorization
cascade that reaches the baseline lookup only once a final impact level exists.
Every refusal is also checked for inertness: no row written, no counter moved.
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
    ERR_BASELINE_NOT_AVAILABLE,
    ERR_CRM_TEXT_REQUIRED,
    ERR_DETECTION_DATE_IN_FUTURE,
    ERR_DUPLICATE_CONTROL_IMPLEMENTATION,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_ENGAGEMENT_OFFERING_MISMATCH,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_NO_CONFIRMED_DATA_CATEGORY,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OFFERING_NOT_FOUND,
    ERR_PACKAGE_ACCESS_DENIED,
    ERR_SPONSORSHIP_CAPACITY_EXCEEDED,
    ERR_STALE_OFFERING_VERSION,
    ERR_UNAUTHENTICATED,
    VALIDATION_TIER,
)
from test_helpers.factories import OMIT
from test_helpers.test_users import (
    CSP_LEAD_2,
    NO_AUTH_HEADERS,
    make_assessor_headers,
    make_board_headers,
    make_csp_lead_headers,
)

# ---------------------------------------------------------------------------
# Shared state builders
# ---------------------------------------------------------------------------


def _categorized_offering(client):
    """Reference data plus one offering in CATEGORIZED owned by csp-lead-1."""
    env = fx.seed_reference_data(client)
    return fx.seed_categorized_offering(client, env)


def _implementation_count(client, headers, **params):
    """``total_count`` of the control-implementation list read."""
    _, meta = validate_paginated(client.list_control_implementations(headers, params or None))
    return meta["total_count"]


# ---------------------------------------------------------------------------
# Duplicate control identifiers and category codes are scoped to one offering
# ---------------------------------------------------------------------------


def test_a_repeated_control_id_is_refused_on_its_own_offering_but_accepted_on_another(client):
    """A control_id already recorded on an offering may still be recorded on a second offering.

    PRD: "A duplicate `control_id` on the same offering is refused with `ERR_DUPLICATE_CONTROL_IMPLEMENTATION`."

    Design: Corner/validations/a_repeated_control_id_or_category_code_inside_one_offering_is_a_duplicate
    """
    env = _categorized_offering(client)
    env = fx.seed_control_implementations(client, env, (("AC-2", "AC"),))
    env = fx.seed_categorized_offering(
        client, env, offering_key="offering_2", name="GovCloud Object Store"
    )

    duplicate = client.create_control_implementation(
        f.build_control_implementation_payload(env["offering_id"], control_id="AC-2"),
        env["lead_headers"],
    )
    validate_error(duplicate, ERR_DUPLICATE_CONTROL_IMPLEMENTATION, 409)
    assert (
        _implementation_count(client, env["lead_headers"], offering_id=env["offering_id"])
        == 1
    ), "the refused duplicate must not leave a second AC-2 row on the offering"

    accepted = client.create_control_implementation(
        f.build_control_implementation_payload(env["offering_2_id"], control_id="AC-2"),
        env["lead_headers"],
    )
    row = validate_success(accepted, 201)
    assert row["control_id"] == "AC-2"
    assert row["offering_id"] == env["offering_2_id"]
    assert (
        _implementation_count(
            client, env["lead_headers"], offering_id=env["offering_2_id"]
        )
        == 1
    )


def test_a_repeated_category_code_is_refused_on_its_own_offering_but_accepted_on_another(client):
    """A category_code already declared on an offering may still be declared on a second offering.

    PRD: "A second category re-using an existing `category_code` on the same offering is refused with `ERR_DUPLICATE_CONTROL_IMPLEMENTATION`."

    Design: Corner/validations/a_repeated_control_id_or_category_code_inside_one_offering_is_a_duplicate
    """
    env = _categorized_offering(client)
    env = fx.seed_draft_offering(
        client, env, name="GovCloud Object Store", key="offering_2"
    )

    accepted = client.create_data_category(
        env["offering_2_id"],
        f.build_data_category_payload(
            category_code="PII",
            confidentiality_impact="LOW",
            integrity_impact="LOW",
            availability_impact="LOW",
        ),
        env["lead_headers"],
    )
    category = validate_success(accepted, 201)
    assert category["status"] == "DECLARED"
    second_offering = fx.read_offering(client, env["offering_2_id"])
    assert second_offering["preliminary_impact_level"] == "LOW"
    version_before = second_offering["version"]

    duplicate = client.create_data_category(
        env["offering_2_id"],
        f.build_data_category_payload(
            category_code="PII",
            confidentiality_impact="LOW",
            integrity_impact="LOW",
            availability_impact="LOW",
        ),
        env["lead_headers"],
    )
    validate_error(duplicate, ERR_DUPLICATE_CONTROL_IMPLEMENTATION, 409)

    _, meta = validate_paginated(
        client.list_data_categories(env["offering_2_id"], env["lead_headers"])
    )
    assert meta["total_count"] == 1, "the refused duplicate must not write a second row"
    after = fx.read_offering(client, env["offering_2_id"])
    assert after["version"] == version_before, (
        "a refused duplicate category must not recompute the preliminary impact level"
    )
    assert after["preliminary_impact_level"] == "LOW"


# ---------------------------------------------------------------------------
# The fiscal gate is satisfied at equality
# ---------------------------------------------------------------------------


def _boundary_budget_package(client):
    """A submittable package whose engagement cost lands exactly on the budget."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env, assessment_budget_usd=127200.00)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env, contracted_hours=200.00, labor_cost_usd=120000.00)
    env = fx.seed_report_delivered(client, env, report_at=fx.AUTHORIZATION_CLOCK)
    return fx.seed_package(client, env)


def test_submission_is_accepted_when_the_engagement_cost_exactly_equals_the_budget(client):
    """A total assessment cost landing exactly on the approved budget clears the fiscal gate.

    PRD: "The engagement's total cost fits the offering's approved assessment budget — `ERR_ASSESSMENT_BUDGET_EXCEEDED` (422)."

    Design: Corner/validations/submission_passes_when_the_engagement_cost_exactly_equals_the_budget
    """
    env = _boundary_budget_package(client)

    engagement = fx.read_engagement(client, env["engagement_id"])
    offering = fx.read_offering(client, env["offering_id"])
    a.assert_money(engagement["total_cost_usd"], 127200.00, "total_cost_usd")
    a.assert_money(offering["assessment_budget_usd"], 127200.00, "assessment_budget_usd")
    a.assert_money(
        engagement["total_cost_usd"],
        offering["assessment_budget_usd"],
        "total_cost_usd against assessment_budget_usd",
    )

    response = client.submit_package(env["package_id"], env["lead_headers"])
    package = validate_success(response, 200)
    assert package["status"] == "SUBMITTED"
    a.assert_integer(package["submission_round"], 1, "submission_round")
    a.assert_instant(package["submitted_at"], fx.AUTHORIZATION_CLOCK, "submitted_at")


def test_the_boundary_submission_freezes_full_coverage_and_a_zero_residual_risk(client):
    """The accepted boundary submission freezes coverage, risk and finding counts on the package.

    PRD: "Three figures are frozen onto the package at that instant and never move again: `crm_coverage_pct` from the coverage computation, `residual_risk_score_at_submission` from the submission variant of the risk score, and `open_findings_at_submission` as the count of the offering's findings whose `remediation_status` is not `CLOSED`."

    Design: Corner/validations/submission_passes_when_the_engagement_cost_exactly_equals_the_budget
    """
    env = _boundary_budget_package(client)

    package = validate_success(
        client.submit_package(env["package_id"], env["lead_headers"]), 200
    )
    a.assert_money(
        package["crm_coverage_pct"],
        a.expected_overall_coverage(((2, 2), (1, 1))),
        "crm_coverage_pct",
    )
    a.assert_money(
        package["residual_risk_score_at_submission"],
        0.00,
        "residual_risk_score_at_submission",
    )
    a.assert_integer(
        package["open_findings_at_submission"], 0, "open_findings_at_submission"
    )
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "PACKAGE_SUBMITTED"


# ---------------------------------------------------------------------------
# Header, body and ownership gates peel off in priority order
# ---------------------------------------------------------------------------


def test_absent_headers_outrank_the_malformed_body_and_the_unknown_offering(client):
    """A request with no identity headers is refused for authentication, not for its other defects.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the four roles the program recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/validations/the_header_body_and_ownership_gates_peel_off_in_priority_order
    """
    env = _categorized_offering(client)
    assert VALIDATION_TIER[ERR_UNAUTHENTICATED] < VALIDATION_TIER[ERR_INVALID_REQUEST]

    response = client.create_control_implementation(
        f.build_control_implementation_payload(
            NON_EXISTENT_UUID, control_id=OMIT, crm_documented=False
        ),
        NO_AUTH_HEADERS,
    )
    validate_error(response, ERR_UNAUTHENTICATED, 401)
    assert _implementation_count(client, env["lead_headers"]) == 0


def test_the_role_gate_outranks_the_malformed_body_on_a_control_implementation(client):
    """An assessor recording a control implementation is refused for role, not for body shape.

    PRD: "When the acting role is not listed as authorized for the endpoint being called (see §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/validations/the_header_body_and_ownership_gates_peel_off_in_priority_order
    """
    env = _categorized_offering(client)
    assert VALIDATION_TIER[ERR_FORBIDDEN_ROLE] < VALIDATION_TIER[ERR_INVALID_REQUEST]

    response = client.create_control_implementation(
        f.build_control_implementation_payload(
            NON_EXISTENT_UUID, control_id=OMIT, crm_documented=False
        ),
        make_assessor_headers(),
    )
    validate_error(response, ERR_FORBIDDEN_ROLE, 403)
    assert _implementation_count(client, env["lead_headers"]) == 0


def test_the_body_shape_gate_outranks_the_unresolvable_offering_reference(client):
    """A missing control_id is reported before the unresolvable offering reference is looked up.

    PRD: "Request shape: required fields present, enum members legal, numbers positive where the field demands it, arrays non-empty and duplicate-free (with the single exception of the assessment report's `findings` array, which may legally be empty), `period_month` well formed, pagination inside its bounds — `ERR_INVALID_REQUEST`."

    Design: Corner/validations/the_header_body_and_ownership_gates_peel_off_in_priority_order
    """
    env = _categorized_offering(client)
    # Tier 5 is the request-shape gate; the body foreign key is only resolved at tier 7.
    assert VALIDATION_TIER[ERR_INVALID_REQUEST] == 5

    response = client.create_control_implementation(
        f.build_control_implementation_payload(
            NON_EXISTENT_UUID, control_id=OMIT, crm_documented=False
        ),
        env["lead_headers"],
    )
    validate_error(response, ERR_INVALID_REQUEST, 400)
    assert _implementation_count(client, env["lead_headers"]) == 0


def test_the_unresolvable_offering_reference_outranks_the_ownership_gate(client):
    """A well-formed body naming no existing offering is refused as a missing offering.

    PRD: "Every foreign key in the request body resolves, in the endpoint's declared field order, as do the two foreign-key filters of the offering list read — the corresponding 404."

    Design: Corner/validations/the_header_body_and_ownership_gates_peel_off_in_priority_order
    """
    env = _categorized_offering(client)
    # The body foreign key is resolved at tier 7, before the ownership check at tier 8.
    assert VALIDATION_TIER[ERR_NOT_RESOURCE_OWNER] == 8

    response = client.create_control_implementation(
        f.build_control_implementation_payload(
            NON_EXISTENT_UUID, control_id="AC-2", crm_documented=False
        ),
        env["lead_headers"],
    )
    validate_error(response, ERR_OFFERING_NOT_FOUND, 404)
    assert _implementation_count(client, env["lead_headers"]) == 0


def test_a_lead_who_does_not_own_the_offering_cannot_record_its_control(client):
    """A compliance lead other than the offering's owner is refused as a non-owner.

    PRD: "Any ownership failure of the three kinds above — a lead who is not the offering owner, an assessor who is not the engagement's assessor, or an agency official who is not the grant's agency — is rejected with `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/validations/the_header_body_and_ownership_gates_peel_off_in_priority_order
    """
    env = _categorized_offering(client)

    response = client.create_control_implementation(
        f.build_control_implementation_payload(
            env["offering_id"], control_id="AC-2", crm_documented=False
        ),
        make_csp_lead_headers(CSP_LEAD_2),
    )
    validate_error(response, ERR_NOT_RESOURCE_OWNER, 403)
    assert _implementation_count(client, env["lead_headers"]) == 0


def test_the_owner_records_the_only_control_row_that_survives_the_gate_ladder(client):
    """The offering's owner records an undocumented matrix entry with no customer text.

    PRD: "`crm_documented` is a boolean defaulting to false that asserts the matrix entry for this control has been written, and `customer_responsibility_text` holds the matrix prose, defaulting to null."

    Design: Corner/validations/the_header_body_and_ownership_gates_peel_off_in_priority_order
    """
    env = _categorized_offering(client)
    malformed_unknown = f.build_control_implementation_payload(
        NON_EXISTENT_UUID, control_id=OMIT, crm_documented=False
    )
    wellformed_unknown = f.build_control_implementation_payload(
        NON_EXISTENT_UUID, control_id="AC-2", crm_documented=False
    )
    wellformed_real = f.build_control_implementation_payload(
        env["offering_id"], control_id="AC-2", crm_documented=False
    )

    ladder = (
        (NO_AUTH_HEADERS, malformed_unknown, ERR_UNAUTHENTICATED, 401),
        (make_assessor_headers(), malformed_unknown, ERR_FORBIDDEN_ROLE, 403),
        (env["lead_headers"], malformed_unknown, ERR_INVALID_REQUEST, 400),
        (env["lead_headers"], wellformed_unknown, ERR_OFFERING_NOT_FOUND, 404),
        (
            make_csp_lead_headers(CSP_LEAD_2),
            wellformed_real,
            ERR_NOT_RESOURCE_OWNER,
            403,
        ),
    )
    for headers, payload, error_id, status in ladder:
        validate_error(
            client.create_control_implementation(payload, headers), error_id, status
        )

    accepted = client.create_control_implementation(
        f.build_control_implementation_payload(
            env["offering_id"], control_id="AC-2", crm_documented=False
        ),
        env["lead_headers"],
    )
    row = validate_success(accepted, 201)
    assert row["crm_documented"] is False
    assert row["customer_responsibility_text"] is None
    assert _implementation_count(client, env["lead_headers"]) == 1, (
        "none of the five refusals may have written a row"
    )


# ---------------------------------------------------------------------------
# The optimistic version gate sits between the foreign key and the parent check
# ---------------------------------------------------------------------------


def _two_offerings_ready_for_a_package(client):
    """Offering 1 with a REPORT_DELIVERED engagement, offering 2 with a DRAFT one."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_report_delivered(client, env, report_at=fx.AUTHORIZATION_CLOCK)
    env = fx.seed_categorized_offering(
        client, env, offering_key="offering_2", name="GovCloud Object Store"
    )
    foreign = validate_success(
        client.create_engagement(
            f.build_engagement_payload(env["offering_2_id"]), env["lead_headers"]
        ),
        201,
    )
    env["foreign_engagement_id"] = foreign["id"]
    env["offering_version"] = fx.offering_version(client, env["offering_id"])
    return env


def _package_count(client, headers):
    _, meta = validate_paginated(client.list_packages(headers))
    return meta["total_count"]


def test_an_unresolvable_engagement_outranks_a_stale_expected_offering_version(client):
    """A package create naming no existing engagement is refused as a missing engagement.

    PRD: "Every foreign key in the request body resolves, in the endpoint's declared field order, as do the two foreign-key filters of the offering list read — the corresponding 404."

    Design: Corner/validations/the_optimistic_version_gate_outranks_the_engagement_ownership_gate
    """
    env = _two_offerings_ready_for_a_package(client)
    stale = env["offering_version"] - 1
    # The body foreign key is resolved at tier 7, ahead of the version gate at tier 10.
    assert VALIDATION_TIER[ERR_STALE_OFFERING_VERSION] == 10

    response = client.create_package(
        f.build_package_payload(env["offering_id"], NON_EXISTENT_UUID, stale),
        env["lead_headers"],
    )
    validate_error(response, ERR_ENGAGEMENT_NOT_FOUND, 404)
    assert _package_count(client, env["lead_headers"]) == 0
    assert (
        fx.offering_version(client, env["offering_id"]) == env["offering_version"]
    ), "a refused package create must not touch the offering"


def test_a_stale_expected_offering_version_outranks_the_engagement_parent_mismatch(client):
    """A stale expected version is reported even though the named engagement has another parent.

    PRD: "If that value does not equal the offering's current `version`, the create is rejected with `ERR_STALE_OFFERING_VERSION` (412)."

    Design: Corner/validations/the_optimistic_version_gate_outranks_the_engagement_ownership_gate
    """
    env = _two_offerings_ready_for_a_package(client)
    stale = env["offering_version"] - 1
    assert (
        VALIDATION_TIER[ERR_STALE_OFFERING_VERSION]
        < VALIDATION_TIER[ERR_ENGAGEMENT_OFFERING_MISMATCH]
    )

    response = client.create_package(
        f.build_package_payload(
            env["offering_id"], env["foreign_engagement_id"], stale
        ),
        env["lead_headers"],
    )
    validate_error(response, ERR_STALE_OFFERING_VERSION, 412)
    assert _package_count(client, env["lead_headers"]) == 0
    assert fx.offering_version(client, env["offering_id"]) == env["offering_version"]


def test_a_cross_parent_engagement_is_reported_once_the_version_matches(client):
    """With the version current, an engagement belonging to another offering is the reported defect.

    PRD: "The engagement must belong to the same offering, and a mismatch is refused with `ERR_ENGAGEMENT_OFFERING_MISMATCH`."

    Design: Corner/validations/the_optimistic_version_gate_outranks_the_engagement_ownership_gate
    """
    env = _two_offerings_ready_for_a_package(client)

    response = client.create_package(
        f.build_package_payload(
            env["offering_id"], env["foreign_engagement_id"], env["offering_version"]
        ),
        env["lead_headers"],
    )
    validate_error(response, ERR_ENGAGEMENT_OFFERING_MISMATCH, 409)
    assert _package_count(client, env["lead_headers"]) == 0
    assert fx.offering_version(client, env["offering_id"]) == env["offering_version"]
    foreign = fx.read_engagement(client, env["foreign_engagement_id"])
    assert foreign["status"] == "DRAFT", "the refused reference must not touch the engagement"


def test_the_offerings_own_engagement_at_the_current_version_opens_a_draft_package(client):
    """The offering's own engagement at the current version creates the package and bumps the offering.

    PRD: "Creation also increments the offering's `open_package_count` and the offering's `version` by one."

    Design: Corner/validations/the_optimistic_version_gate_outranks_the_engagement_ownership_gate
    """
    env = _two_offerings_ready_for_a_package(client)

    response = client.create_package(
        f.build_package_payload(
            env["offering_id"], env["engagement_id"], env["offering_version"]
        ),
        env["lead_headers"],
    )
    package = validate_success(response, 201)
    assert package["status"] == "DRAFT"
    a.assert_integer(package["submission_round"], 0, "submission_round")

    offering = fx.read_offering(client, env["offering_id"])
    a.assert_integer(offering["open_package_count"], 1, "open_package_count")
    a.assert_integer(
        offering["version"], env["offering_version"] + 1, "offering version"
    )
    assert _package_count(client, env["lead_headers"]) == 1


# ---------------------------------------------------------------------------
# The package read is gated on sponsorship or a live reuse grant
# ---------------------------------------------------------------------------


def _authorized_offering_with_a_second_agency(client):
    """A live authorization sponsored by DOT, plus an EPA agency holding no grant."""
    env = fx.seed_authorized_offering(client)
    return fx.add_agency(
        client,
        env,
        name="Environmental Protection Agency",
        agency_code="EPA",
        key="epa",
    )


def test_only_the_sponsoring_agency_official_reads_the_package_without_a_grant(client):
    """The sponsor's official reads the package while an unrelated agency's official is refused.

    PRD: "Second, reading an authorization package is the one read in the system that is not universally open: an `AgencyAuthorizingOfficial` may read a package only if that official's agency is the offering's sponsor, or if the official's agency holds a reuse grant on the resulting authorization whose `access_state` is one of `PACKAGE_ACCESS_GRANTED`, `INCREMENTAL_REVIEW`, `REUSE_ACCEPTED` or `NOTICE_ISSUED`."

    Design: Corner/validations/package_access_for_a_non_sponsor_official_depends_on_a_live_reuse_grant
    """
    env = _authorized_offering_with_a_second_agency(client)

    sponsor_read = client.get_package(env["package_id"], env["agency_headers"])
    package = validate_success(sponsor_read, 200)
    assert package["id"] == env["package_id"]

    foreign_read = client.get_package(env["package_id"], env["epa_headers"])
    validate_error(foreign_read, ERR_PACKAGE_ACCESS_DENIED, 403)


def test_a_grant_still_in_requested_does_not_open_the_package_read(client):
    """A reuse grant sitting in REQUESTED is outside the access-bearing states.

    PRD: "Otherwise the read is refused with `ERR_PACKAGE_ACCESS_DENIED` (403)."

    Design: Corner/validations/package_access_for_a_non_sponsor_official_depends_on_a_live_reuse_grant
    """
    env = _authorized_offering_with_a_second_agency(client)
    env = fx.seed_reuse_grant(
        client,
        env,
        agency_id=env["epa_id"],
        agency_headers=env["epa_headers"],
        advance_to="REQUESTED",
    )
    assert fx.read_reuse_grant(client, env["grant_id"])["access_state"] == "REQUESTED"

    response = client.get_package(env["package_id"], env["epa_headers"])
    validate_error(response, ERR_PACKAGE_ACCESS_DENIED, 403)


def test_granting_package_access_opens_the_read_for_the_grantee_agency(client):
    """Moving the grant to PACKAGE_ACCESS_GRANTED makes the package readable by the grantee.

    PRD: "The offering's owning compliance lead grants package access, moving the grant `REQUESTED → PACKAGE_ACCESS_GRANTED`, which is what makes the authorization package readable to the grantee agency under the access rule of §2.1; the acting `X-User-ID` must equal the offering's `owner_user_id`."

    Design: Corner/validations/package_access_for_a_non_sponsor_official_depends_on_a_live_reuse_grant
    """
    env = _authorized_offering_with_a_second_agency(client)
    env = fx.seed_reuse_grant(
        client,
        env,
        agency_id=env["epa_id"],
        agency_headers=env["epa_headers"],
        advance_to="PACKAGE_ACCESS_GRANTED",
    )
    assert (
        fx.read_reuse_grant(client, env["grant_id"])["access_state"]
        == "PACKAGE_ACCESS_GRANTED"
    )

    response = client.get_package(env["package_id"], env["epa_headers"])
    package = validate_success(response, 200)
    assert package["id"] == env["package_id"]


def test_revoking_the_grant_closes_the_package_read_and_returns_the_seat(client):
    """Revoking the grant refuses the grantee's read again and hands its reuse seat back.

    PRD: "It returns the seat — the authorization's `reuse_seats_granted` decreases by one and `reuse_seats_available` increases by one — decrements the agency's `reuse_grant_count` by one, decrements that agency's `open_notice_count` by one when the grant was sitting in `NOTICE_ISSUED`, and increments the authorization's `version` by one."

    Design: Corner/validations/package_access_for_a_non_sponsor_official_depends_on_a_live_reuse_grant
    """
    env = _authorized_offering_with_a_second_agency(client)
    env = fx.seed_reuse_grant(
        client,
        env,
        agency_id=env["epa_id"],
        agency_headers=env["epa_headers"],
        advance_to="PACKAGE_ACCESS_GRANTED",
    )

    revoked = validate_success(
        client.revoke_reuse_grant(
            env["grant_id"], f.build_revoke_payload("AGENCY_REQUEST"), env["epa_headers"]
        ),
        200,
    )
    assert revoked["access_state"] == "REVOKED"

    response = client.get_package(env["package_id"], env["epa_headers"])
    validate_error(response, ERR_PACKAGE_ACCESS_DENIED, 403)

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["reuse_seats_granted"], 0, "reuse_seats_granted")
    a.assert_integer(authorization["reuse_seats_available"], 5, "reuse_seats_available")
    a.assert_seat_conservation(authorization)


# ---------------------------------------------------------------------------
# The detection instant boundary is inclusive
# ---------------------------------------------------------------------------

_DETECTION_CLOCK = "2026-03-01T00:00:00Z"


def _offering_at_the_detection_clock(client):
    env = _categorized_offering(client)
    fx.set_clock(client, _DETECTION_CLOCK)
    env["clock_set_to"] = _DETECTION_CLOCK
    return env


def _poam_count(client, headers, offering_id):
    _, meta = validate_paginated(
        client.list_poam_items(headers, {"offering_id": offering_id})
    )
    return meta["total_count"]


def test_a_detection_one_second_after_the_clock_is_refused(client):
    """A finding detected one second past the logical clock is a future detection.

    PRD: "`detected_at` is not after the logical clock — `ERR_DETECTION_DATE_IN_FUTURE` (422), on finding creation and on report delivery."

    Design: Corner/validations/a_detection_instant_one_second_past_the_clock_is_refused
    """
    env = _offering_at_the_detection_clock(client)

    response = client.create_poam_item(
        f.build_poam_item_payload(
            env["offering_id"],
            control_id="AC-2",
            severity="HIGH",
            detected_at=a.shift_instant(_DETECTION_CLOCK, seconds=1),
        ),
        env["lead_headers"],
    )
    validate_error(response, ERR_DETECTION_DATE_IN_FUTURE, 422)
    assert _poam_count(client, env["lead_headers"], env["offering_id"]) == 0


def test_a_detection_at_the_clock_instant_is_accepted_and_anchors_on_itself(client):
    """A finding detected at exactly the clock instant is accepted and anchors on that instant.

    PRD: "A directly filed item names the `offering_id` carrying the finding, the `control_id` the finding was raised against, a `severity` of `HIGH`, `MODERATE` or `LOW`, and a `detected_at` instant that must not be after the logical clock."

    Design: Corner/validations/a_detection_instant_one_second_past_the_clock_is_refused
    """
    env = _offering_at_the_detection_clock(client)

    response = client.create_poam_item(
        f.build_poam_item_payload(
            env["offering_id"],
            control_id="AC-2",
            severity="HIGH",
            detected_at=_DETECTION_CLOCK,
        ),
        env["lead_headers"],
    )
    item = validate_success(response, 201)
    a.assert_instant(item["detected_at"], _DETECTION_CLOCK, "detected_at")
    a.assert_instant(item["anchor_at"], _DETECTION_CLOCK, "anchor_at")
    a.assert_instant(
        item["deadline_at"],
        a.expected_deadline(_DETECTION_CLOCK, "HIGH"),
        "deadline_at",
    )
    assert _poam_count(client, env["lead_headers"], env["offering_id"]) == 1


def test_a_past_detection_keeps_its_own_earlier_deadline(client):
    """A finding detected two weeks before the clock anchors on its detection, not on the clock.

    PRD: "At creation an item's `anchor_at` equals its `detected_at`, and its `deadline_at` is `anchor_at` advanced by the severity base allowance and then by `granted_extension_days` further days."

    Design: Corner/validations/a_detection_instant_one_second_past_the_clock_is_refused
    """
    env = _offering_at_the_detection_clock(client)
    detected_at = "2026-02-15T00:00:00Z"

    response = client.create_poam_item(
        f.build_poam_item_payload(
            env["offering_id"],
            control_id="AC-3",
            severity="HIGH",
            detected_at=detected_at,
        ),
        env["lead_headers"],
    )
    item = validate_success(response, 201)
    a.assert_instant(item["anchor_at"], detected_at, "anchor_at")
    a.assert_instant(
        item["deadline_at"], a.expected_deadline(detected_at, "HIGH"), "deadline_at"
    )
    a.assert_instant(item["deadline_at"], "2026-03-17T00:00:00Z", "deadline_at")
    assert not a.instants_equal(
        item["deadline_at"], a.expected_deadline(_DETECTION_CLOCK, "HIGH")
    ), "a past detection must not be re-anchored onto the clock"


# ---------------------------------------------------------------------------
# Sponsorship capacity is an aggregate ceiling
# ---------------------------------------------------------------------------


def _three_categorized_offerings_and_a_capacity_of_two(client):
    env = fx.seed_reference_data(client, sponsorship_capacity=2)
    env = fx.seed_categorized_offering(client, env)
    env = fx.seed_categorized_offering(
        client, env, offering_key="offering_2", name="GovCloud Object Store"
    )
    return fx.seed_categorized_offering(
        client, env, offering_key="offering_3", name="GovCloud Key Vault"
    )


def _select_agency_sponsorship(client, env, offering_key):
    return client.select_path(
        env[f"{offering_key}_id"],
        f.build_path_selection_payload("AGENCY_SPONSORED", env["agency_id"]),
        env["lead_headers"],
    )


def test_two_sponsorships_fill_a_capacity_of_two_one_at_a_time(client):
    """Each accepted sponsorship raises the agency's sponsored count and its version by one.

    PRD: "On success the server writes both `authorization_path` and `sponsor_agency_id` onto the offering, increments the sponsoring agency's `sponsored_offering_count` by one, and increments that agency's `version` by one."

    Design: Corner/validations/three_individually_legal_sponsorships_exceed_a_capacity_of_two
    """
    env = _three_categorized_offerings_and_a_capacity_of_two(client)

    first = validate_success(_select_agency_sponsorship(client, env, "offering"), 200)
    assert first["authorization_path"] == "AGENCY_SPONSORED"
    assert first["sponsor_agency_id"] == env["agency_id"]
    agency = fx.read_agency(client, env["agency_id"])
    a.assert_integer(agency["sponsored_offering_count"], 1, "sponsored_offering_count")
    a.assert_integer(agency["version"], 2, "agency version")

    validate_success(_select_agency_sponsorship(client, env, "offering_2"), 200)
    agency = fx.read_agency(client, env["agency_id"])
    a.assert_integer(agency["sponsored_offering_count"], 2, "sponsored_offering_count")
    a.assert_integer(agency["version"], 3, "agency version")


def test_a_third_sponsorship_is_refused_and_leaves_the_agency_counter_untouched(client):
    """A third sponsorship against a capacity of two is refused without moving the counter.

    PRD: "On the `AGENCY_SPONSORED` branch a `sponsor_agency_id` must be supplied, that agency's `status` must be `ACTIVE`, and its `sponsored_offering_count` must be strictly less than its `sponsorship_capacity`; an agency already sponsoring as many offerings as its capacity allows causes the selection to fail with `ERR_SPONSORSHIP_CAPACITY_EXCEEDED`."

    Design: Corner/validations/three_individually_legal_sponsorships_exceed_a_capacity_of_two
    """
    env = _three_categorized_offerings_and_a_capacity_of_two(client)
    validate_success(_select_agency_sponsorship(client, env, "offering"), 200)
    validate_success(_select_agency_sponsorship(client, env, "offering_2"), 200)

    response = _select_agency_sponsorship(client, env, "offering_3")
    validate_error(response, ERR_SPONSORSHIP_CAPACITY_EXCEEDED, 422)

    agency = fx.read_agency(client, env["agency_id"])
    a.assert_integer(agency["sponsored_offering_count"], 2, "sponsored_offering_count")
    a.assert_integer(agency["version"], 3, "agency version")
    third = fx.read_offering(client, env["offering_3_id"])
    assert third["status"] == "CATEGORIZED"
    assert third["authorization_path"] is None
    assert third["sponsor_agency_id"] is None


def test_the_program_board_fallback_succeeds_without_touching_the_agency(client):
    """The offering refused sponsorship may still select the program-board path.

    PRD: "In that case the server writes `authorization_path` as `PROGRAM_BOARD` and leaves `sponsor_agency_id` null, and no agency row is touched."

    Design: Corner/validations/three_individually_legal_sponsorships_exceed_a_capacity_of_two
    """
    env = _three_categorized_offerings_and_a_capacity_of_two(client)
    validate_success(_select_agency_sponsorship(client, env, "offering"), 200)
    validate_success(_select_agency_sponsorship(client, env, "offering_2"), 200)
    validate_error(
        _select_agency_sponsorship(client, env, "offering_3"),
        ERR_SPONSORSHIP_CAPACITY_EXCEEDED,
        422,
    )

    fallback = validate_success(
        client.select_path(
            env["offering_3_id"],
            f.build_path_selection_payload("PROGRAM_BOARD"),
            env["lead_headers"],
        ),
        200,
    )
    assert fallback["status"] == "PATH_SELECTED"
    assert fallback["authorization_path"] == "PROGRAM_BOARD"
    assert fallback["sponsor_agency_id"] is None

    agency = fx.read_agency(client, env["agency_id"])
    a.assert_integer(agency["sponsored_offering_count"], 2, "sponsored_offering_count")
    a.assert_integer(agency["version"], 3, "agency version")


# ---------------------------------------------------------------------------
# The customer-responsibility text is required only while the flag is set
# ---------------------------------------------------------------------------


def test_an_undocumented_matrix_entry_may_omit_the_customer_text(client):
    """With crm_documented false the customer responsibility text may be absent.

    PRD: "`crm_documented` is a boolean defaulting to false that asserts the matrix entry for this control has been written, and `customer_responsibility_text` holds the matrix prose, defaulting to null."

    Design: Corner/validations/the_crm_text_requirement_applies_only_while_the_documented_flag_is_set
    """
    env = _categorized_offering(client)

    response = client.create_control_implementation(
        f.build_control_implementation_payload(
            env["offering_id"], control_id="SC-7", family_code="SC", crm_documented=False
        ),
        env["lead_headers"],
    )
    row = validate_success(response, 201)
    assert row["crm_documented"] is False
    assert row["customer_responsibility_text"] is None


@pytest.mark.parametrize(
    "customer_responsibility_text", [OMIT, ""], ids=["absent", "empty_string"]
)
def test_the_documented_flag_without_customer_text_is_refused(
    client, customer_responsibility_text
):
    """Setting crm_documented true with no matrix prose — absent or empty — is refused.

    PRD: "The two are coupled: whenever `crm_documented` is true, `customer_responsibility_text` must be present and non-empty, and a violation is refused with `ERR_CRM_TEXT_REQUIRED` on both creation and update."

    Design: Corner/validations/the_crm_text_requirement_applies_only_while_the_documented_flag_is_set
    """
    env = _categorized_offering(client)

    response = client.create_control_implementation(
        f.build_control_implementation_payload(
            env["offering_id"],
            control_id="AC-2",
            crm_documented=True,
            customer_responsibility_text=customer_responsibility_text,
        ),
        env["lead_headers"],
    )
    validate_error(response, ERR_CRM_TEXT_REQUIRED, 422)
    assert _implementation_count(client, env["lead_headers"]) == 0


def test_the_documented_flag_with_customer_text_is_accepted(client):
    """With crm_documented true and prose supplied the implementation row is written.

    PRD: "The two are coupled: whenever `crm_documented` is true, `customer_responsibility_text` must be present and non-empty, and a violation is refused with `ERR_CRM_TEXT_REQUIRED` on both creation and update."

    Design: Corner/validations/the_crm_text_requirement_applies_only_while_the_documented_flag_is_set
    """
    env = _categorized_offering(client)

    response = client.create_control_implementation(
        f.build_control_implementation_payload(
            env["offering_id"], control_id="AC-2", crm_documented=True
        ),
        env["lead_headers"],
    )
    row = validate_success(response, 201)
    assert row["crm_documented"] is True
    assert row["customer_responsibility_text"] == f.DEFAULT_CRM_TEXT
    a.assert_integer(row["version"], 1, "control implementation version")


def test_patching_the_documented_flag_on_without_text_leaves_the_row_untouched(client):
    """Flipping crm_documented on without supplying prose is refused on update too.

    PRD: "The two are coupled: whenever `crm_documented` is true, `customer_responsibility_text` must be present and non-empty, and a violation is refused with `ERR_CRM_TEXT_REQUIRED` on both creation and update."

    Design: Corner/validations/the_crm_text_requirement_applies_only_while_the_documented_flag_is_set
    """
    env = _categorized_offering(client)
    undocumented = validate_success(
        client.create_control_implementation(
            f.build_control_implementation_payload(
                env["offering_id"],
                control_id="SC-7",
                family_code="SC",
                crm_documented=False,
            ),
            env["lead_headers"],
        ),
        201,
    )

    response = client.update_control_implementation(
        undocumented["id"], {"crm_documented": True}, env["lead_headers"]
    )
    validate_error(response, ERR_CRM_TEXT_REQUIRED, 422)

    unchanged = validate_success(
        client.get_control_implementation(undocumented["id"], env["lead_headers"]), 200
    )
    assert unchanged["crm_documented"] is False
    a.assert_integer(unchanged["version"], 1, "control implementation version")


def test_patching_the_documented_flag_off_is_accepted_and_retains_the_stored_text(client):
    """Turning crm_documented off is accepted and the stored prose is left behind.

    PRD: "Updating an implementation may revise `implementation_status`, `crm_documented`, `customer_responsibility_text` or `inherited_from_offering_id`, and increments the row's own `version` by one."

    Design: Corner/validations/the_crm_text_requirement_applies_only_while_the_documented_flag_is_set
    """
    env = _categorized_offering(client)
    documented = validate_success(
        client.create_control_implementation(
            f.build_control_implementation_payload(
                env["offering_id"], control_id="AC-2", crm_documented=True
            ),
            env["lead_headers"],
        ),
        201,
    )

    patched = validate_success(
        client.update_control_implementation(
            documented["id"], {"crm_documented": False}, env["lead_headers"]
        ),
        200,
    )
    assert patched["crm_documented"] is False
    assert patched["customer_responsibility_text"] == f.DEFAULT_CRM_TEXT
    a.assert_integer(patched["version"], 2, "control implementation version")


def test_coverage_falls_to_zero_once_no_row_is_both_documented_and_implemented(client):
    """An implemented control whose matrix entry is undocumented contributes no coverage.

    PRD: "For each remaining family, count the offering's control implementations whose `family_code` matches that family, whose `implementation_status` is either `IMPLEMENTED` or `PARTIALLY_IMPLEMENTED`, and whose `crm_documented` is true — implementations that are `PLANNED`, `ALTERNATIVE_IMPLEMENTATION` or `NOT_APPLICABLE` never count, and neither does an implementation whose matrix entry is undocumented."

    Design: Corner/validations/the_crm_text_requirement_applies_only_while_the_documented_flag_is_set
    """
    env = _categorized_offering(client)
    validate_success(
        client.create_control_implementation(
            f.build_control_implementation_payload(
                env["offering_id"],
                control_id="SC-7",
                family_code="SC",
                crm_documented=False,
            ),
            env["lead_headers"],
        ),
        201,
    )
    documented = validate_success(
        client.create_control_implementation(
            f.build_control_implementation_payload(
                env["offering_id"], control_id="AC-2", crm_documented=True
            ),
            env["lead_headers"],
        ),
        201,
    )
    validate_success(
        client.update_control_implementation(
            documented["id"], {"crm_documented": False}, env["lead_headers"]
        ),
        200,
    )

    coverage = validate_success(
        client.get_crm_coverage(env["offering_id"], env["lead_headers"]), 200
    )
    a.assert_money(coverage["overall_coverage_pct"], 0.00, "overall_coverage_pct")
    a.assert_integer(coverage["weight_total"], 3, "weight_total")


# ---------------------------------------------------------------------------
# The baseline lookup runs only once a final impact level exists
# ---------------------------------------------------------------------------

_HIGH_FAMILIES = [f.build_family("AC", 4, 1), f.build_family("SC", 2, 2)]


def _draft_offering_with_a_declared_high_category(client):
    """A DRAFT offering whose only category is declared, not confirmed, and rates HIGH."""
    env = fx.seed_reference_data(client)
    env = fx.seed_draft_offering(client, env)
    env["category"] = validate_success(
        client.create_data_category(
            env["offering_id"],
            f.build_data_category_payload(
                category_code="TELEMETRY",
                confidentiality_impact="LOW",
                integrity_impact="LOW",
                availability_impact="HIGH",
            ),
            env["lead_headers"],
        ),
        201,
    )
    return env


def test_impact_determination_without_a_confirmed_category_reports_the_confirmation_gate(client):
    """With every category merely declared, the determination fails on the confirmation gate.

    PRD: "If the offering has no confirmed category at all, the request fails with `ERR_NO_CONFIRMED_DATA_CATEGORY`."

    Design: Corner/validations/the_baseline_lookup_only_runs_once_the_final_level_has_been_decided
    """
    env = _draft_offering_with_a_declared_high_category(client)
    before = fx.read_offering(client, env["offering_id"])
    assert (
        VALIDATION_TIER[ERR_NO_CONFIRMED_DATA_CATEGORY]
        < VALIDATION_TIER[ERR_BASELINE_NOT_AVAILABLE]
    )

    response = client.determine_impact(env["offering_id"], {}, make_board_headers())
    validate_error(response, ERR_NO_CONFIRMED_DATA_CATEGORY, 422)

    after = fx.read_offering(client, env["offering_id"])
    assert after["status"] == "DRAFT"
    assert after["final_impact_level"] is None
    assert after["baseline_id"] is None
    a.assert_integer(after["version"], before["version"], "offering version")


def test_the_missing_high_baseline_surfaces_only_after_the_category_is_confirmed(client):
    """Once the HIGH category is confirmed the determination reaches the empty baseline set.

    PRD: "Candidates are the control baselines whose `impact_level` equals the determined final level and whose `retired` flag is false; if that candidate set is empty the request fails with `ERR_BASELINE_NOT_AVAILABLE`."

    Design: Corner/validations/the_baseline_lookup_only_runs_once_the_final_level_has_been_decided
    """
    env = _draft_offering_with_a_declared_high_category(client)
    board_headers = make_board_headers()

    confirmed = validate_success(
        client.confirm_data_category(
            env["category"]["id"], f.build_category_decision_payload("CONFIRM"), board_headers
        ),
        200,
    )
    assert confirmed["status"] == "CONFIRMED"
    after_confirm = fx.read_offering(client, env["offering_id"])
    assert after_confirm["preliminary_impact_level"] == "HIGH"

    response = client.determine_impact(env["offering_id"], {}, board_headers)
    validate_error(response, ERR_BASELINE_NOT_AVAILABLE, 422)

    after = fx.read_offering(client, env["offering_id"])
    assert after["status"] == "DRAFT"
    assert after["final_impact_level"] is None
    assert after["baseline_id"] is None
    a.assert_integer(after["version"], after_confirm["version"], "offering version")


def test_publishing_the_high_baseline_lets_the_same_determination_through(client):
    """With a HIGH baseline published the determination binds it and categorizes the offering.

    PRD: "On success the offering moves `DRAFT → CATEGORIZED`, `final_impact_level` and `baseline_id` are written, and the offering's `version` increments by one."

    Design: Corner/validations/the_baseline_lookup_only_runs_once_the_final_level_has_been_decided
    """
    env = _draft_offering_with_a_declared_high_category(client)
    board_headers = make_board_headers()
    validate_success(
        client.confirm_data_category(
            env["category"]["id"], f.build_category_decision_payload("CONFIRM"), board_headers
        ),
        200,
    )
    validate_error(
        client.determine_impact(env["offering_id"], {}, board_headers),
        ERR_BASELINE_NOT_AVAILABLE,
        422,
    )
    high_baseline = fx.create_baseline(
        client, impact_level="HIGH", families=_HIGH_FAMILIES
    )
    before = fx.read_offering(client, env["offering_id"])

    determined = validate_success(
        client.determine_impact(env["offering_id"], {}, board_headers), 200
    )
    assert determined["status"] == "CATEGORIZED"
    assert determined["final_impact_level"] == "HIGH"
    assert determined["baseline_id"] == high_baseline["id"]
    assert determined["baseline_id"] != env["baseline_id"], (
        "the MODERATE baseline must never be selected for a HIGH final level"
    )
    a.assert_integer(determined["version"], before["version"] + 1, "offering version")
