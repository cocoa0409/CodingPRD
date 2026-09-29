"""Authentication ordering, role boundaries, optimistic concurrency and the
immediate-consistency guarantee of the inclusionary-zoning compliance API.

Every test builds its own preconditions from declared endpoints against an empty
database, using the shared composite helpers in ``test_helpers.fixtures``.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_fund_inflow_composed,
    assert_fund_money_conserved,
    assert_unit_dimensions,
    assert_waterfall_conserved,
    date_plus_days,
    factories,
    fixtures,
    make_resident_headers,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE,
    CANONICAL_FEE_DUE_DAYS,
    CLOCK_STARTUP_DEFAULT,
    MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
)

# A twenty-unit R-2 development owes exactly two whole affordable units and no
# residual fraction: 20 * 1000 bps = 20000 bps of obligation.
PROJECT_R2_20 = {
    "name": "Header Hollow",
    "zoning_district": "R-2",
    "total_units": 20,
    "approval_date": "2026-01-15",
}

# The canonical FULL assessment of that obligation, priced by the four ordered
# steps of the fee pipeline: base 48000000, surcharge 1680000 (under the
# 5000000 cap), pre-discount 49680000, 150 bps discount 745200.
FULL_ASSESSMENT_CENTS = 48934800
FULL_UNIT_EQUIVALENT_BPS = 20000


def _error_envelope(response, error_id: str) -> dict:
    """Validate the standard error envelope and its request-scoped metadata."""
    data = validate_error(response, error_id)
    meta = response.json()["meta"]
    assert "api_request_id" in meta, meta
    assert "api_request_timestamp" in meta, meta
    return data


def _project_at_twenty_units(headers=None, **overrides) -> dict:
    payload = dict(PROJECT_R2_20)
    payload.update(overrides)
    return fixtures.register_project(headers=headers or fixtures.DEV, **payload)


def _fee_ready_project(**overrides) -> dict:
    """A twenty-unit R-2 project that has elected the in-lieu fee path."""
    project = _project_at_twenty_units(**overrides)
    fixtures.screen_project(project["id"])
    return fixtures.elect_path(project["id"], "IN_LIEU_FEE")


def _occupied_ownership_scenario(project_overrides=None) -> dict:
    """A restriction-recorded OWNERSHIP unit occupied by a certified household."""
    ctx = fixtures.restricted_ownership_unit(
        original_purchase_price_cents=32500000,
        project_overrides=project_overrides,
    )
    ctx["seller"] = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    ctx["seller_certification"] = fixtures.certify_income(
        ctx["seller"]["id"], ctx["unit"]["id"], contract_rent_cents=0
    )
    ctx["unit"] = fixtures.live_unit(ctx["unit"]["id"])
    ctx["project"] = fixtures.live_project(ctx["project"]["id"])
    return ctx


# =============================================================================
# Authentication outranks every later check
# =============================================================================
def test_missing_auth_headers_outrank_the_request_body(api, program_admin, no_auth_headers):
    """A request carrying neither identity header is refused before its body is read.

    PRD: "If either header is absent or present but empty, the request is refused with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

    Design: Corner/errors/missing_and_unknown_auth_header_errors_outrank_every_later_check
    """
    fixtures.bootstrap_program()
    _project_at_twenty_units()

    ghost = dict(PROJECT_R2_20)
    ghost["name"] = "Ghost"
    response = api.create_project(ghost, headers=no_auth_headers)
    _error_envelope(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    projects, meta = validate_paginated(api.list_projects(headers=program_admin))
    assert meta["total_count"] == 1, meta
    assert [p["name"] for p in projects if p["name"] == "Ghost"] == [], projects


def test_empty_user_id_is_missing_auth_and_existence_is_never_leaked(
    api, empty_user_id_headers, no_auth_headers
):
    """A blank X-User-ID is unauthenticated, and an unauthenticated probe never yields 404.

    PRD: "If either header is absent or present but empty, the request is refused with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

    Design: Corner/errors/missing_and_unknown_auth_header_errors_outrank_every_later_check
    """
    fixtures.bootstrap_program()
    project = _project_at_twenty_units()

    # A valid role name does not rescue a blank identity.
    _error_envelope(
        api.get_project(project["id"], headers=empty_user_id_headers),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
    )

    # The path-identifier check sits far below the header check, so a header-less
    # read of an id that resolves to nothing is still a 401 and not a 404.
    _error_envelope(
        api.get_project(NON_EXISTENT_UUID, headers=no_auth_headers),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
    )


def test_unknown_role_outranks_authorization_and_payload_shape(
    api, compliance_officer, unknown_role_headers
):
    """An undeclared role name is a 401 before any role list or payload check runs.

    PRD: "If `X-User-Role` carries a value outside the five recognised roles, the request is refused with `ERR_UNKNOWN_ROLE` (HTTP 401)."

    Design: Corner/errors/missing_and_unknown_auth_header_errors_outrank_every_later_check
    """
    fixtures.bootstrap_program()
    project = _project_at_twenty_units()

    # The fund summary admits only ProgramAdministrator and FundAuditor, yet the
    # refusal is the 401 and not the 403: the role must first BE a declared role.
    _error_envelope(
        api.get_trust_fund_summary(headers=unknown_role_headers),
        ApiErrorId.ERR_UNKNOWN_ROLE.value,
    )

    # The clock admits all five declared roles and is still refused.
    _error_envelope(
        api.set_clock("2026-09-01T00:00:00Z", headers=unknown_role_headers),
        ApiErrorId.ERR_UNKNOWN_ROLE.value,
    )

    # A structurally invalid ordinance body does not surface ERR_INVALID_REQUEST
    # ahead of the header check.
    _error_envelope(
        api.create_ordinance({"code": ""}, headers=unknown_role_headers),
        ApiErrorId.ERR_UNKNOWN_ROLE.value,
    )

    # The rejected clock call had no effect: screening still stamps the startup instant.
    screened = validate_success(api.screen_project(project["id"], headers=compliance_officer))
    assert same_instant(screened["screened_at"], CLOCK_STARTUP_DEFAULT), screened["screened_at"]


# =============================================================================
# The fund auditor is read-only, and the fund reads are exclusive
# =============================================================================
def test_the_fund_auditor_holds_no_write_capability(api, fund_auditor, program_admin):
    """Every write endpoint the auditor can name refuses it, and nothing moves.

    PRD: "A `FundAuditor` is the external funder's auditor: this role reads the trust-fund ledger, the draw register, and the program-compliance reports, and holds no write capability whatsoever — every write endpoint refuses a `FundAuditor` with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/the_fund_auditor_is_a_read_only_role_and_the_fund_reads_are_exclusive
    """
    ctx = fixtures.funded_trust_fund(project_overrides=dict(PROJECT_R2_20))
    project_id = ctx["project"]["id"]
    fee_id = ctx["fee"]["id"]
    assert ctx["fee"]["assessed_amount_cents"] == FULL_ASSESSMENT_CENTS, ctx["fee"]
    before = fixtures.live_project(project_id, headers=program_admin)

    _error_envelope(
        api.create_project(dict(PROJECT_R2_20), headers=fund_auditor),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    _error_envelope(
        api.screen_project(project_id, headers=fund_auditor),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    _error_envelope(
        api.pay_in_lieu_fee(fee_id, 1, headers=fund_auditor),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    _error_envelope(
        api.create_disbursement(
            factories.create_disbursement_payload(fee_id, 100000), headers=fund_auditor
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    # The draw register itself is readable, and it is empty: no draw was booked.
    draws, draw_meta = validate_paginated(api.list_disbursements(headers=fund_auditor))
    assert draw_meta["total_count"] == 0, draw_meta
    assert draws == [], draws

    after = fixtures.live_project(project_id, headers=program_admin)
    assert after["version"] == before["version"], (before["version"], after["version"])
    assert after["state"] == "PATH_ELECTED", after["state"]
    _, project_meta = validate_paginated(api.list_projects(headers=program_admin))
    assert project_meta["total_count"] == 1, project_meta


def test_the_fund_ledger_reads_are_exclusive_to_the_administrator_and_the_auditor(
    api, developer, fund_auditor
):
    """A developer cannot read the fund at all, while the auditor reads it in full.

    PRD: "Only once both headers are well formed does the system consider whether the role is permitted to perform the requested operation; a well-formed request from a role that the endpoint does not list is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/the_fund_auditor_is_a_read_only_role_and_the_fund_reads_are_exclusive
    """
    ctx = fixtures.funded_trust_fund(project_overrides=dict(PROJECT_R2_20))

    _error_envelope(
        api.get_trust_fund_summary(headers=developer), ApiErrorId.ERR_UNAUTHORIZED.value
    )

    summary = validate_success(api.get_trust_fund_summary(headers=fund_auditor))
    assert summary["total_paid_fees_cents"] == FULL_ASSESSMENT_CENTS, summary
    assert summary["total_recapture_cents"] == 0, summary
    assert summary["total_inflow_cents"] == FULL_ASSESSMENT_CENTS, summary
    assert summary["encumbered_cents"] == 0, summary
    assert summary["disbursed_cents"] == 0, summary
    assert summary["unencumbered_balance_cents"] == FULL_ASSESSMENT_CENTS, summary
    assert_fund_inflow_composed(summary)
    assert_fund_money_conserved(summary)

    fee = validate_success(api.get_in_lieu_fee(ctx["fee"]["id"], headers=fund_auditor))
    assert fee["state"] == "PAID", fee["state"]
    assert fee["paid_amount_cents"] == FULL_ASSESSMENT_CENTS, fee


# =============================================================================
# Ownership scoping: a rival developer and a non-occupant resident
# =============================================================================
def test_a_rival_developer_is_refused_on_another_developers_project(
    api, rival_developer, developer
):
    """Ownership is compared against the stored developer_user_id, ahead of state rules.

    PRD: "The server records it as `developer_user_id` on a `Project` at registration time and thereafter compares it to that stored value: every `Developer` write against a project, one of its restricted units, one of its marketing plans, one of its in-lieu assessments, or one of its monitoring reviews is refused with `ERR_NOT_RESOURCE_OWNER` unless `X-User-ID` equals the owning project's `developer_user_id`."

    Design: Corner/rbac/ownership_scoping_refuses_a_rival_developer_and_a_non_occupant_resident
    """
    ctx = _occupied_ownership_scenario()
    project_id = ctx["project"]["id"]
    before = ctx["project"]

    _error_envelope(
        api.patch_project(project_id, {"name": "Seized Row"}, headers=rival_developer),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )

    # The project has long since left SCREENED_SUBJECT, so a state refusal is
    # also available here; ownership is checked first and wins.
    _error_envelope(
        api.elect_path(project_id, "IN_LIEU_FEE", headers=rival_developer),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )

    _error_envelope(
        api.create_unit(
            factories.create_unit_payload(
                project_id,
                ctx["agreement"]["id"],
                unit_number="NO-999",
                tenure="OWNERSHIP",
            ),
            headers=rival_developer,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )

    # Reads are not ownership-scoped: the rival sees the project unchanged.
    seen = validate_success(api.get_project(project_id, headers=rival_developer))
    assert seen["state"] == "MONITORING", seen["state"]
    assert seen["compliance_path"] == "ONSITE", seen["compliance_path"]
    assert seen["total_units"] == fixtures.ONE_UNIT_PROJECT["total_units"], seen["total_units"]
    assert seen["version"] == before["version"], (before["version"], seen["version"])
    _, unit_meta = validate_paginated(api.list_units(project_id=project_id, headers=developer))
    assert unit_meta["total_count"] == 1, unit_meta


def test_a_body_foreign_key_is_resolved_before_the_ownership_check(api, rival_developer):
    """Naming a project that does not exist yields the not-found code, not the owner code.

    PRD: "A body-supplied `project_id`, `agreement_id`, `marketing_plan_id`, `lottery_event_id`, `household_id`, `unit_id`, `prior_transaction_id`, `source_fee_id`, `buyer_household_id`, or `certification_id` that names no existing row yields the corresponding not-found code from the same catalogue."

    Design: Corner/rbac/ownership_scoping_refuses_a_rival_developer_and_a_non_occupant_resident
    """
    ctx = _occupied_ownership_scenario()

    _error_envelope(
        api.create_unit(
            factories.create_unit_payload(
                NON_EXISTENT_UUID, ctx["agreement"]["id"], unit_number="NO-998"
            ),
            headers=rival_developer,
        ),
        ApiErrorId.ERR_PROJECT_NOT_FOUND.value,
    )


def test_only_the_occupant_household_may_submit_a_resale(api, compliance_officer):
    """A resident who occupies nothing is refused the very payload the occupant may send.

    PRD: "Applying on behalf of a different household, or submitting a resale of a unit whose `occupant_household_id` is not `X-User-ID`, is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/ownership_scoping_refuses_a_rival_developer_and_a_non_occupant_resident
    """
    ctx = _occupied_ownership_scenario()
    unit = ctx["unit"]
    outsider = fixtures.register_household(
        applicant_name="Ines Okonkwo", household_size=2, gross_annual_income_cents=5000000
    )
    payload = factories.create_resale_payload(
        unit["id"],
        unit["version"],
        proposed_price_cents=32000000,
        appraised_value_cents=41000000,
        broker_fee_cents=1000000,
    )

    _error_envelope(
        api.create_resale(payload, headers=make_resident_headers(outsider["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    _, refused_meta = validate_paginated(
        api.list_resales(unit_id=unit["id"], headers=compliance_officer)
    )
    assert refused_meta["total_count"] == 0, refused_meta

    # The identical payload from the true occupant is accepted.
    accepted = validate_success(
        api.create_resale(payload, headers=make_resident_headers(ctx["seller"]["id"])), 201
    )
    assert accepted["state"] == "SUBMITTED", accepted["state"]
    assert accepted["seller_household_id"] == ctx["seller"]["id"], accepted


# =============================================================================
# Four eyes: the officer who opened a step may not close it
# =============================================================================
def test_the_issuing_officer_may_not_clear_the_cure_they_opened(
    api, compliance_officer, second_compliance_officer, program_admin
):
    """A cure clears only for a second officer; the first is refused on identity.

    PRD: "The officer whose `X-User-ID` was captured as `issued_by_user_id` when a monitoring review was created may not clear that review's cure."

    Design: Corner/rbac/four_eyes_blocks_the_same_officer_from_closing_a_step_that_they_opened
    """
    ctx = fixtures.review_with_submitted_cure(
        165000, MAX_ALLOWED_RENT_2BR_AT_5000_BPS, officer_headers=compliance_officer
    )
    review = ctx["monitoring_review"]
    assert review["state"] == "CURE_SUBMITTED", review["state"]
    assert review["issued_by_user_id"] == compliance_officer["X-User-ID"], review
    assert_unit_dimensions(ctx["unit"], compliance_status="CURE_PENDING")

    _error_envelope(
        api.clear_cure(review["id"], headers=compliance_officer),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    held = validate_success(api.get_monitoring_review(review["id"], headers=program_admin))
    assert held["state"] == "CURE_SUBMITTED", held["state"]
    assert held["cleared_by_user_id"] is None, held
    assert held["cure_deadline"] == review["cure_deadline"], (review, held)
    assert held["version"] == review["version"], (review["version"], held["version"])
    assert_unit_dimensions(
        fixtures.live_unit(ctx["unit"]["id"]), compliance_status="CURE_PENDING"
    )

    # The rule keys on the recorded identifier, not the role: the same role in a
    # second pair of hands is exactly who is expected to close the step.
    cleared = validate_success(api.clear_cure(review["id"], headers=second_compliance_officer))
    assert cleared["state"] == "CURED", cleared["state"]
    assert cleared["cleared_by_user_id"] == second_compliance_officer["X-User-ID"], cleared
    assert cleared["version"] == review["version"] + 1, cleared["version"]
    assert_unit_dimensions(
        fixtures.live_unit(ctx["unit"]["id"]), compliance_status="COMPLIANT"
    )


def test_the_price_approving_officer_may_not_certify_the_buyer(
    api, compliance_officer, second_compliance_officer, program_admin
):
    """Buyer certification is refused to the officer who approved the price.

    PRD: "The officer whose `X-User-ID` was captured as `price_approved_by_user_id` when a resale price was approved may not certify that transaction's buyer."

    Design: Corner/rbac/four_eyes_blocks_the_same_officer_from_closing_a_step_that_they_opened
    """
    ctx = fixtures.rofr_waived_resale(30000000, approver_headers=compliance_officer)
    resale = ctx["resale"]
    assert resale["state"] == "ROFR_WAIVED", resale["state"]
    assert resale["price_approved_by_user_id"] == compliance_officer["X-User-ID"], resale

    buyer = fixtures.register_household(applicant_name="Bo Ferreira")
    buyer_certification = fixtures.certify_income(
        buyer["id"], ctx["unit"]["id"], contract_rent_cents=0
    )

    _error_envelope(
        api.certify_buyer(
            resale["id"], buyer["id"], buyer_certification["id"], headers=compliance_officer
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    held = validate_success(api.get_resale(resale["id"], headers=program_admin))
    assert held["state"] == "ROFR_WAIVED", held["state"]
    assert held["buyer_household_id"] is None, held
    assert held["buyer_certification_id"] is None, held

    certified = validate_success(
        api.certify_buyer(
            resale["id"],
            buyer["id"],
            buyer_certification["id"],
            headers=second_compliance_officer,
        )
    )
    assert certified["state"] == "BUYER_CERTIFIED", certified["state"]
    assert certified["buyer_household_id"] == buyer["id"], certified
    assert certified["buyer_certification_id"] == buyer_certification["id"], certified


def test_the_review_state_gate_outranks_the_four_eyes_check(api, compliance_officer):
    """With no cure yet submitted, the issuing officer meets the state refusal first.

    PRD: "The monitoring review's `state` permits the operation — cure submission only from `FINDING_ISSUED` or `ESCALATED`, cure clearing and escalation only from `CURE_SUBMITTED` — else `ERR_REVIEW_STATE_INVALID`."

    Design: Corner/rbac/four_eyes_blocks_the_same_officer_from_closing_a_step_that_they_opened
    """
    ctx = fixtures.review_with_finding(165000, officer_headers=compliance_officer)
    review = ctx["monitoring_review"]
    assert review["state"] == "FINDING_ISSUED", review["state"]
    assert review["issued_by_user_id"] == compliance_officer["X-User-ID"], review

    _error_envelope(
        api.clear_cure(review["id"], headers=compliance_officer),
        ApiErrorId.ERR_REVIEW_STATE_INVALID.value,
    )


# =============================================================================
# Shared operations accept either authorised role interchangeably
# =============================================================================
def test_screening_is_shared_by_the_officer_and_the_administrator(
    api, compliance_officer, program_admin, developer, rival_developer
):
    """Two identical projects screened by the two authorised roles derive identically.

    PRD: "**Screening** is performed by a `HousingComplianceOfficer` or a `ProgramAdministrator` and is permitted only while the project is `DRAFT`."

    Design: Corner/rbac/shared_operations_accept_either_authorised_role_interchangeably
    """
    fixtures.bootstrap_program()
    first = _project_at_twenty_units(headers=developer, name="Shared Alpha")
    second = _project_at_twenty_units(headers=rival_developer, name="Shared Beta")

    by_officer = validate_success(api.screen_project(first["id"], headers=compliance_officer))
    by_admin = validate_success(api.screen_project(second["id"], headers=program_admin))

    for screened in (by_officer, by_admin):
        assert screened["state"] == "SCREENED_SUBJECT", screened["state"]
        assert screened["applicability"] == "SUBJECT", screened["applicability"]
        assert screened["required_affordable_units"] == 2, screened
        assert screened["fractional_obligation_bps"] == 0, screened
        assert screened["total_obligation_bps"] == FULL_UNIT_EQUIVALENT_BPS, screened
        assert screened["screen_count"] == 1, screened


def test_household_registration_is_shared_by_the_officer_and_the_administrator(
    api, program_admin, compliance_officer
):
    """Either authorised role may register a household, and both see both rows.

    PRD: "**Households** are registered by a `ProgramAdministrator` or a `HousingComplianceOfficer` with an `applicant_name` of 1 to 120 characters, a `household_size` from 1 through 5 which drives every income-limit lookup, and a self-reported `gross_annual_income_cents` of at least 0."

    Design: Corner/rbac/shared_operations_accept_either_authorised_role_interchangeably
    """
    fixtures.bootstrap_program()

    by_admin = validate_success(
        api.create_household(
            factories.create_household_payload(applicant_name="Ada Nakamura"),
            headers=program_admin,
        ),
        201,
    )
    by_officer = validate_success(
        api.create_household(
            factories.create_household_payload(applicant_name="Nia Bello"),
            headers=compliance_officer,
        ),
        201,
    )
    assert by_admin["state"] == "REGISTERED", by_admin["state"]
    assert by_officer["state"] == "REGISTERED", by_officer["state"]

    # Registration is not scoped to the registering role: each sees the other's row.
    seen_by_officer, officer_meta = validate_paginated(
        api.list_households(headers=compliance_officer)
    )
    seen_by_admin, admin_meta = validate_paginated(api.list_households(headers=program_admin))
    assert officer_meta["total_count"] == 2, officer_meta
    assert admin_meta["total_count"] == 2, admin_meta
    assert {h["id"] for h in seen_by_officer} == {by_admin["id"], by_officer["id"]}
    assert {h["id"] for h in seen_by_admin} == {by_admin["id"], by_officer["id"]}


def test_fee_assessment_is_shared_by_the_officer_and_the_administrator(
    api, program_admin, compliance_officer, developer, rival_developer
):
    """The same obligation prices identically whichever authorised role assesses it.

    PRD: "Assessment is available to a `ProgramAdministrator` or a `HousingComplianceOfficer` and takes three inputs: the `project_id` of the development, the `basis` on which the assessment is drawn, and the `expected_project_version` optimistic-concurrency token described in §2.8."

    Design: Corner/rbac/shared_operations_accept_either_authorised_role_interchangeably
    """
    fixtures.bootstrap_program()
    first = _project_at_twenty_units(headers=developer, name="Shared Alpha")
    second = _project_at_twenty_units(headers=rival_developer, name="Shared Beta")
    fixtures.screen_project(first["id"])
    fixtures.screen_project(second["id"])
    fixtures.elect_path(first["id"], "IN_LIEU_FEE", headers=developer)
    fixtures.elect_path(second["id"], "IN_LIEU_FEE", headers=rival_developer)

    by_admin = fixtures.assess_fee(first["id"], headers=program_admin)
    by_officer = fixtures.assess_fee(second["id"], headers=compliance_officer)

    expected_due_date = date_plus_days(CLOCK_STARTUP_DEFAULT[:10], CANONICAL_FEE_DUE_DAYS)
    for fee in (by_admin, by_officer):
        assert fee["state"] == "ASSESSED", fee["state"]
        assert fee["unit_equivalent_bps"] == FULL_UNIT_EQUIVALENT_BPS, fee
        assert fee["assessed_amount_cents"] == FULL_ASSESSMENT_CENTS, fee
        assert fee["due_date"] == expected_due_date, fee["due_date"]


def test_the_clock_is_shared_by_every_declared_role(api, fund_auditor, program_admin):
    """A resident and an auditor may each advance the shared logical clock.

    PRD: "Any of the five roles may advance the clock by supplying a `current_utc` instant to the clock-setting capability described in §4."

    Design: Corner/rbac/shared_operations_accept_either_authorised_role_interchangeably
    """
    fixtures.bootstrap_program()
    household = fixtures.register_household()

    by_resident = validate_success(
        api.set_clock("2026-08-02T00:00:00Z", headers=make_resident_headers(household["id"]))
    )
    assert same_instant(by_resident["current_utc"], "2026-08-02T00:00:00Z"), by_resident

    by_auditor = validate_success(
        api.set_clock("2026-08-03T00:00:00Z", headers=fund_auditor)
    )
    assert same_instant(by_auditor["current_utc"], "2026-08-03T00:00:00Z"), by_auditor
    for result in (by_resident, by_auditor):
        assert result["certifications_expired"] == 0, result
        assert result["fees_marked_delinquent"] == 0, result
        assert result["rofr_windows_auto_waived"] == 0, result


def test_sharing_stops_at_the_two_named_roles(api, developer, program_admin, compliance_officer):
    """A role outside an endpoint's list is refused, and its attempt changes nothing.

    PRD: "Only once both headers are well formed does the system consider whether the role is permitted to perform the requested operation; a well-formed request from a role that the endpoint does not list is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/shared_operations_accept_either_authorised_role_interchangeably
    """
    fixtures.bootstrap_program()
    project = _project_at_twenty_units()
    screened = fixtures.screen_project(project["id"])
    assert screened["screen_count"] == 1, screened
    household = fixtures.register_household()

    _error_envelope(
        api.create_household(
            factories.create_household_payload(applicant_name="Nia Bello"), headers=developer
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    _error_envelope(
        api.screen_project(project["id"], headers=make_resident_headers(household["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    _, household_meta = validate_paginated(api.list_households(headers=compliance_officer))
    assert household_meta["total_count"] == 1, household_meta
    still = validate_success(api.get_project(project["id"], headers=program_admin))
    assert still["screen_count"] == 1, still
    assert still["state"] == "SCREENED_SUBJECT", still["state"]
    assert still["version"] == screened["version"], (screened["version"], still["version"])


# =============================================================================
# A stale project view is refused before the project state is considered
# =============================================================================
def test_a_second_assessment_on_a_stale_project_version_writes_nothing(api, program_admin):
    """Replaying the version that the first assessment consumed is a 412 that writes nothing.

    PRD: "If that value does not equal the project's current `version`, the assessment is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/a_stale_project_view_is_refused_before_the_project_state_is_even_considered
    """
    fixtures.bootstrap_program()
    project = _fee_ready_project()
    stale_version = project["version"]

    first = validate_success(
        api.create_in_lieu_fee(
            factories.create_in_lieu_fee_payload(project["id"], stale_version, basis="FULL"),
            headers=program_admin,
        ),
        201,
    )
    assert first["assessed_amount_cents"] == FULL_ASSESSMENT_CENTS, first
    assert first["unit_equivalent_bps"] == FULL_UNIT_EQUIVALENT_BPS, first
    assert first["superseded_by_fee_id"] is None, first

    # Booking the assessment advanced the very version the caller quoted.
    advanced = fixtures.live_project(project["id"])
    assert advanced["version"] > stale_version, (stale_version, advanced["version"])

    _error_envelope(
        api.create_in_lieu_fee(
            factories.create_in_lieu_fee_payload(project["id"], stale_version, basis="FULL"),
            headers=program_admin,
        ),
        ApiErrorId.ERR_STALE_PROJECT_VERSION.value,
    )

    fees, fee_meta = validate_paginated(
        api.list_in_lieu_fees(project_id=project["id"], headers=program_admin)
    )
    assert fee_meta["total_count"] == 1, fee_meta
    assert [f["id"] for f in fees] == [first["id"]], fees
    held = validate_success(api.get_in_lieu_fee(first["id"], headers=program_admin))
    assert held["state"] == "ASSESSED", held["state"]
    assert held["superseded_by_fee_id"] is None, held
    assert held["version"] == first["version"], (first["version"], held["version"])
    unchanged = fixtures.live_project(project["id"])
    assert unchanged["version"] == advanced["version"], (advanced, unchanged)


def test_a_refreshed_project_version_lets_the_retry_supersede_the_open_assessment(
    api, program_admin
):
    """Re-reading the project makes the retry succeed and supersede the first assessment.

    PRD: "Booking a new assessment also supersedes whatever the project had open: any other assessment of the same project in `ASSESSED`, `PARTIALLY_PAID` or `DELINQUENT` transitions to `SUPERSEDED` — `ASSESSED → SUPERSEDED` and `DELINQUENT → SUPERSEDED` alike — with its `superseded_by_fee_id` pointing at the new assessment and its own `version` incremented, and the project's `fee_covered_equivalents_bps` and `compliance_posture` are recomputed."

    Design: Corner/cross_cutting_complexity_layers/a_stale_project_view_is_refused_before_the_project_state_is_even_considered
    """
    # Fifteen R-4 units owe 22500 bps: two whole units and a 2500 bps residual,
    # so a fractional assessment can be booked first and a full one after it.
    fixtures.bootstrap_program()
    project = fixtures.register_project(
        name="Fraction Court",
        zoning_district="R-4",
        total_units=15,
        approval_date="2026-01-15",
    )
    screened = fixtures.screen_project(project["id"])
    assert screened["required_affordable_units"] == 2, screened
    assert screened["fractional_obligation_bps"] == 2500, screened
    assert screened["total_obligation_bps"] == 22500, screened
    project = fixtures.elect_path(project["id"], "IN_LIEU_FEE")
    stale_version = project["version"]

    first = validate_success(
        api.create_in_lieu_fee(
            factories.create_in_lieu_fee_payload(
                project["id"], stale_version, basis="FRACTIONAL"
            ),
            headers=program_admin,
        ),
        201,
    )
    assert first["state"] == "ASSESSED", first["state"]
    assert first["unit_equivalent_bps"] == 2500, first
    assert first["superseded_by_fee_id"] is None, first

    # Booking the fractional assessment consumed the version the caller held.
    _error_envelope(
        api.create_in_lieu_fee(
            factories.create_in_lieu_fee_payload(project["id"], stale_version, basis="FULL"),
            headers=program_admin,
        ),
        ApiErrorId.ERR_STALE_PROJECT_VERSION.value,
    )

    fresh_version = fixtures.live_project(project["id"])["version"]
    second = validate_success(
        api.create_in_lieu_fee(
            factories.create_in_lieu_fee_payload(project["id"], fresh_version, basis="FULL"),
            headers=program_admin,
        ),
        201,
    )
    assert second["id"] != first["id"], second
    assert second["state"] == "ASSESSED", second["state"]
    assert second["unit_equivalent_bps"] == FULL_UNIT_EQUIVALENT_BPS, second
    assert second["assessed_amount_cents"] == FULL_ASSESSMENT_CENTS, second
    assert second["superseded_by_fee_id"] is None, second

    superseded = validate_success(api.get_in_lieu_fee(first["id"], headers=program_admin))
    assert superseded["state"] == "SUPERSEDED", superseded["state"]
    assert superseded["superseded_by_fee_id"] == second["id"], superseded
    assert superseded["version"] == first["version"] + 1, superseded["version"]

    _, fee_meta = validate_paginated(
        api.list_in_lieu_fees(project_id=project["id"], headers=program_admin)
    )
    assert fee_meta["total_count"] == 2, fee_meta


def test_the_stale_project_version_check_outranks_the_project_state_gate(
    api, program_admin, rival_developer
):
    """A DRAFT project quoted at a stale version answers 412 ahead of every lower rule.

    PRD: "Both guards are evaluated early — ahead of every state and business rule, as §2.9 sets out — so any request that intends to exercise a lower-priority rule on either of these two endpoints must still supply a currently-correct expected version."

    Design: Corner/cross_cutting_complexity_layers/a_stale_project_view_is_refused_before_the_project_state_is_even_considered
    """
    fixtures.bootstrap_program()
    project = _project_at_twenty_units(headers=rival_developer, name="Draft Beta")
    stale_version = project["version"]
    assert project["state"] == "DRAFT", project["state"]

    patched = validate_success(
        api.patch_project(project["id"], {"name": "Draft Beta Revised"}, headers=rival_developer)
    )
    assert patched["version"] == stale_version + 1, patched["version"]
    assert patched["state"] == "DRAFT", patched["state"]

    # An unscreened project owes nothing any basis can price, yet the refusal is
    # the 412: the concurrency guard is evaluated before that rule can speak.
    _error_envelope(
        api.create_in_lieu_fee(
            factories.create_in_lieu_fee_payload(project["id"], stale_version, basis="FULL"),
            headers=program_admin,
        ),
        ApiErrorId.ERR_STALE_PROJECT_VERSION.value,
    )

    still = fixtures.live_project(project["id"], headers=rival_developer)
    assert still["state"] == "DRAFT", still["state"]
    assert still["compliance_path"] is None, still
    assert still["version"] == patched["version"], (patched["version"], still["version"])
    _, fee_meta = validate_paginated(
        api.list_in_lieu_fees(project_id=project["id"], headers=program_admin)
    )
    assert fee_meta["total_count"] == 0, fee_meta


# =============================================================================
# A stale unit view is refused before the enforcement safety check
# =============================================================================
def test_a_second_resale_submission_on_a_stale_unit_version_writes_nothing(
    api, compliance_officer
):
    """The version the first submission consumed no longer buys a second submission.

    PRD: "If that value does not equal the unit's current `version`, the submission is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_stale_unit_view_is_refused_before_the_enforcement_safety_check
    """
    ctx = _occupied_ownership_scenario()
    unit_id = ctx["unit"]["id"]
    stale_version = ctx["unit"]["version"]
    seller = make_resident_headers(ctx["seller"]["id"])

    first = validate_success(
        api.create_resale(
            factories.create_resale_payload(
                unit_id,
                stale_version,
                proposed_price_cents=32000000,
                appraised_value_cents=41000000,
                broker_fee_cents=1000000,
            ),
            headers=seller,
        ),
        201,
    )
    assert first["state"] == "SUBMITTED", first["state"]

    advanced = fixtures.live_unit(unit_id)
    assert advanced["version"] > stale_version, (stale_version, advanced["version"])

    _error_envelope(
        api.create_resale(
            factories.create_resale_payload(
                unit_id,
                stale_version,
                proposed_price_cents=31000000,
                appraised_value_cents=41000000,
                broker_fee_cents=1000000,
            ),
            headers=seller,
        ),
        ApiErrorId.ERR_STALE_UNIT_VERSION.value,
    )

    resales, resale_meta = validate_paginated(
        api.list_resales(unit_id=unit_id, headers=compliance_officer)
    )
    assert resale_meta["total_count"] == 1, resale_meta
    assert [r["id"] for r in resales] == [first["id"]], resales
    held = validate_success(api.get_resale(first["id"], headers=compliance_officer))
    assert held["state"] == "SUBMITTED", held["state"]
    assert held["version"] == first["version"], (first["version"], held["version"])
    assert fixtures.live_unit(unit_id)["version"] == advanced["version"]


def test_a_refreshed_unit_version_lets_the_retry_supersede_the_open_submission(
    api, compliance_officer
):
    """Re-reading the unit makes the retry succeed and supersede the open submission.

    PRD: "Submission also copies `seller_household_id` from the unit's `occupant_household_id`, sets `state` to `SUBMITTED`, moves any other `SUBMITTED` resale of the same unit `SUBMITTED → SUPERSEDED`, and increments the unit's `version` by one — which is why a second submission must supply a freshly read `expected_unit_version`."

    Design: Corner/cross_cutting_complexity_layers/a_stale_unit_view_is_refused_before_the_enforcement_safety_check
    """
    ctx = _occupied_ownership_scenario()
    unit_id = ctx["unit"]["id"]
    seller = make_resident_headers(ctx["seller"]["id"])

    first = validate_success(
        api.create_resale(
            factories.create_resale_payload(
                unit_id, ctx["unit"]["version"], proposed_price_cents=32000000
            ),
            headers=seller,
        ),
        201,
    )
    assert first["seller_household_id"] == ctx["seller"]["id"], first

    refreshed = fixtures.live_unit(unit_id)
    second = validate_success(
        api.create_resale(
            factories.create_resale_payload(
                unit_id, refreshed["version"], proposed_price_cents=31000000
            ),
            headers=seller,
        ),
        201,
    )
    assert second["id"] != first["id"], second
    assert second["state"] == "SUBMITTED", second["state"]
    assert second["seller_household_id"] == ctx["seller"]["id"], second

    superseded = validate_success(api.get_resale(first["id"], headers=compliance_officer))
    assert superseded["state"] == "SUPERSEDED", superseded["state"]
    assert fixtures.live_unit(unit_id)["version"] > refreshed["version"]
    _, resale_meta = validate_paginated(
        api.list_resales(unit_id=unit_id, headers=compliance_officer)
    )
    assert resale_meta["total_count"] == 2, resale_meta


def test_the_stale_unit_version_check_outranks_the_enforcement_guard(
    api, compliance_officer, second_compliance_officer, developer, program_admin
):
    """An out-of-compliance unit quoted at a pre-cascade version answers 412, then 422.

    PRD: "Both guards are evaluated early — ahead of every state and business rule, as §2.9 sets out — so any request that intends to exercise a lower-priority rule on either of these two endpoints must still supply a currently-correct expected version."

    Design: Corner/cross_cutting_complexity_layers/a_stale_unit_view_is_refused_before_the_enforcement_safety_check
    """
    ctx = _occupied_ownership_scenario()
    unit_id = ctx["unit"]["id"]
    pre_cascade_version = ctx["unit"]["version"]
    seller = make_resident_headers(ctx["seller"]["id"])

    fixtures.set_clock("2027-03-01T00:00:00Z")
    review = validate_success(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                unit_id,
                review_year=2027,
                reported_rent_cents=0,
                reported_income_cents=6000000,
                occupancy_verified=False,
            ),
            headers=compliance_officer,
        ),
        201,
    )
    assert review["state"] == "FINDING_ISSUED", review["state"]
    assert review["finding_types"] == ["OCCUPANCY_UNVERIFIED"], review["finding_types"]

    cured = validate_success(api.submit_cure(review["id"], 0, headers=developer))
    assert cured["state"] == "CURE_SUBMITTED", cured["state"]
    escalated = validate_success(
        api.escalate_review(review["id"], headers=second_compliance_officer)
    )
    assert escalated["state"] == "ESCALATED", escalated["state"]
    assert_unit_dimensions(
        fixtures.live_unit(unit_id), compliance_status="OUT_OF_COMPLIANCE"
    )
    assert (
        fixtures.live_project(ctx["project"]["id"], headers=program_admin)["compliance_posture"]
        == "UNDER_ENFORCEMENT"
    )

    # The enforcement bar is a lower-priority rule than the concurrency guard.
    _error_envelope(
        api.create_resale(
            factories.create_resale_payload(
                unit_id, pre_cascade_version, proposed_price_cents=32000000
            ),
            headers=seller,
        ),
        ApiErrorId.ERR_STALE_UNIT_VERSION.value,
    )

    current_version = fixtures.live_unit(unit_id)["version"]
    assert current_version > pre_cascade_version, (pre_cascade_version, current_version)
    _error_envelope(
        api.create_resale(
            factories.create_resale_payload(
                unit_id, current_version, proposed_price_cents=32000000
            ),
            headers=seller,
        ),
        ApiErrorId.ERR_UNIT_OUT_OF_COMPLIANCE.value,
    )
    _, resale_meta = validate_paginated(
        api.list_resales(unit_id=unit_id, headers=compliance_officer)
    )
    assert resale_meta["total_count"] == 0, resale_meta


# =============================================================================
# Every cascade limb is readable in the request that caused it
# =============================================================================
def _resale_ready_to_close(api) -> dict:
    """A BUYER_CERTIFIED resale on a twenty-unit project, one step from closing."""
    ctx = _occupied_ownership_scenario(project_overrides=dict(PROJECT_R2_20))
    unit = ctx["unit"]
    resale = validate_success(
        api.create_resale(
            factories.create_resale_payload(
                unit["id"],
                unit["version"],
                proposed_price_cents=32000000,
                appraised_value_cents=41000000,
                broker_fee_cents=1000000,
            ),
            headers=make_resident_headers(ctx["seller"]["id"]),
        ),
        201,
    )
    resale = validate_success(api.approve_resale_price(resale["id"], headers=fixtures.HCO))
    resale = validate_success(api.rofr_decision(resale["id"], "WAIVE", headers=fixtures.PA))
    ctx["buyer"] = fixtures.register_household(
        applicant_name="Bo Ferreira", household_size=2, gross_annual_income_cents=5000000
    )
    ctx["buyer_certification"] = fixtures.certify_income(
        ctx["buyer"]["id"],
        unit["id"],
        certified_income_cents=5000000,
        contract_rent_cents=0,
    )
    ctx["resale"] = validate_success(
        api.certify_buyer(
            resale["id"],
            ctx["buyer"]["id"],
            ctx["buyer_certification"]["id"],
            headers=fixtures.HCO2,
        )
    )
    ctx["unit"] = fixtures.live_unit(unit["id"])
    return ctx


def test_the_close_response_already_carries_the_whole_waterfall(
    api, second_compliance_officer
):
    """Closing returns every derived money figure in the same response.

    PRD: "Start from `net_proceeds_cents`, the `proposed_price_cents` minus the `broker_fee_cents`, and pour that figure through four buckets in order, each bucket taking what it can from what is left."

    Design: Corner/consistency_model/every_cascade_limb_is_readable_in_the_same_request_that_caused_it
    """
    ctx = _resale_ready_to_close(api)
    assert ctx["resale"]["state"] == "BUYER_CERTIFIED", ctx["resale"]["state"]

    closed = validate_success(
        api.close_resale(ctx["resale"]["id"], headers=second_compliance_officer)
    )
    assert closed["state"] == "CLOSED", closed["state"]
    assert same_instant(closed["closed_at"], CLOCK_STARTUP_DEFAULT), closed["closed_at"]
    assert closed["net_proceeds_cents"] == 31000000, closed
    assert closed["seller_equity_cents"] == 31000000, closed
    assert closed["seller_improvement_credit_cents"] == 0, closed
    assert closed["seller_appreciation_share_cents"] == 0, closed
    assert closed["city_recapture_cents"] == 0, closed
    assert (
        closed["seller_equity_cents"]
        + closed["seller_improvement_credit_cents"]
        + closed["seller_appreciation_share_cents"]
        + closed["city_recapture_cents"]
        == closed["net_proceeds_cents"]
    ), closed
    assert_waterfall_conserved(closed)


def test_the_unit_and_certification_cascades_are_visible_on_the_next_read(
    api, second_compliance_officer, program_admin
):
    """The unit's new basis, new occupant and retired certification are readable at once.

    PRD: "Because the transaction closed, the unit's price basis is reset: `original_purchase_price_cents` becomes the `proposed_price_cents` and `ami_income_at_purchase_cents` is re-captured from the active schedule's median for `bedrooms` plus one, so the next resale is indexed from the new basis."

    Design: Corner/consistency_model/every_cascade_limb_is_readable_in_the_same_request_that_caused_it
    """
    ctx = _resale_ready_to_close(api)
    validate_success(api.close_resale(ctx["resale"]["id"], headers=second_compliance_officer))

    unit = validate_success(api.get_unit(ctx["unit"]["id"], headers=program_admin))
    assert unit["occupant_household_id"] == ctx["buyer"]["id"], unit
    assert_unit_dimensions(unit, occupancy_status="OCCUPIED", compliance_status="COMPLIANT")
    assert unit["original_purchase_price_cents"] == 32000000, unit
    assert (
        unit["ami_income_at_purchase_cents"] == AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["3"]
    ), unit

    seller_certification = validate_success(
        api.get_certification(ctx["seller_certification"]["id"], headers=program_admin)
    )
    assert seller_certification["state"] == "SUPERSEDED", seller_certification["state"]
    buyer_certification = validate_success(
        api.get_certification(ctx["buyer_certification"]["id"], headers=program_admin)
    )
    assert buyer_certification["state"] == "CERTIFIED", buyer_certification["state"]


def test_the_fund_ledger_reflects_the_close_on_the_next_read(
    api, second_compliance_officer, program_admin
):
    """A close that recaptured nothing leaves the computed fund reading zero everywhere.

    PRD: "`total_recapture_cents` is the sum of `city_recapture_cents` across resale transactions in `state` `CLOSED` only."

    Design: Corner/consistency_model/every_cascade_limb_is_readable_in_the_same_request_that_caused_it
    """
    ctx = _resale_ready_to_close(api)
    closed = validate_success(
        api.close_resale(ctx["resale"]["id"], headers=second_compliance_officer)
    )
    assert closed["city_recapture_cents"] == 0, closed

    summary = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert summary["total_recapture_cents"] == 0, summary
    assert summary["total_paid_fees_cents"] == 0, summary
    assert summary["total_inflow_cents"] == 0, summary
    assert summary["unencumbered_balance_cents"] == 0, summary
    assert_fund_inflow_composed(summary)
    assert_fund_money_conserved(summary)


def test_the_occupancy_report_and_every_repeat_read_agree_immediately(
    api, second_compliance_officer, fund_auditor, program_admin
):
    """The occupancy ratio already credits the new occupant, and re-reads are identical.

    PRD: "On the `OCCUPANCY` basis the ratio is 10000 multiplied by `occupied_equivalents_bps`, divided by `total_obligation_bps`, rounded half up."

    Design: Corner/consistency_model/every_cascade_limb_is_readable_in_the_same_request_that_caused_it
    """
    ctx = _resale_ready_to_close(api)
    closed = validate_success(
        api.close_resale(ctx["resale"]["id"], headers=second_compliance_officer)
    )

    report = validate_success(
        api.get_funder_report(ctx["project"]["id"], "OCCUPANCY", headers=fund_auditor)
    )
    assert report["total_obligation_bps"] == FULL_UNIT_EQUIVALENT_BPS, report
    assert report["occupied_equivalents_bps"] == 10000, report
    assert report["compliance_ratio_bps"] == 5000, report
    assert report["open_findings_count"] == 0, report

    # Reading is not a mutation, so the same rows re-read by another role are identical.
    first_transaction = validate_success(api.get_resale(closed["id"], headers=program_admin))
    second_transaction = validate_success(api.get_resale(closed["id"], headers=fund_auditor))
    assert first_transaction == second_transaction, (first_transaction, second_transaction)
    assert first_transaction["version"] == closed["version"], (closed, first_transaction)

    first_unit = validate_success(api.get_unit(ctx["unit"]["id"], headers=program_admin))
    second_unit = validate_success(api.get_unit(ctx["unit"]["id"], headers=fund_auditor))
    assert first_unit == second_unit, (first_unit, second_unit)

    repeat_report = validate_success(
        api.get_funder_report(ctx["project"]["id"], "OCCUPANCY", headers=program_admin)
    )
    assert repeat_report == report, (report, repeat_report)
