"""Role authorization, ownership scope, authentication and segregation of duties."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    COACH_A_HEADERS,
    COACH_A_USER_ID,
    COACH_B_HEADERS,
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    NO_AUTH_HEADERS,
    ApiErrorId,
    active_provider,
    apply_provider,
    assert_no_error_envelope,
    claim_line,
    contract_version,
    create_claim,
    create_contract,
    create_enrollment,
    create_enrollment_payload,
    create_license_verification_payload,
    create_provider_payload,
    create_substitute,
    create_visit_payload,
    issue_agreement,
    make_provider_headers,
    make_substitute_headers,
    open_review,
    request_coverage,
    submit_cap,
    submit_claim,
    verify_license,
)

# Local setup builders


def _enrolling_home(**apply_overrides):
    """An ACTIVE home entitled to enrollment support."""
    overrides = {"capacity_slots": 6}
    overrides.update(apply_overrides)
    return active_provider(
        apply_overrides=overrides,
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
    )


def _pool_home():
    """An ACTIVE STANDARD-tier home entitled to the substitute pool."""
    return active_provider(
        apply_overrides={"county_tier": "STANDARD", "capacity_slots": 6},
        agreement_overrides={"shared_services": ["SUBSTITUTE_POOL"]},
    )


# Every role's own authority


def test_each_of_the_six_roles_performs_an_operation_only_it_may_perform(api):
    """One representative operation per role succeeds, so no role gate is over-tight.

    The unauthenticated application, the licensing verification, the membership execution, the
    advance payment, the coaching booking and the coverage acceptance are each reserved to a
    different role, and each is answered successfully when called by that role. No call in the
    chain returns an error envelope.

    PRD: "The acting role appears in the endpoint's authorized-role list. `ERR_FORBIDDEN_ROLE`,
    HTTP 403. Applies to every endpoint."

    PRD: "Execution is the moment the provider becomes a member, and it is the provider — not
    staff — who performs it."

    Design: Corner/RBAC/every_role_can_perform_one_of_its_own_exclusive_operations
    """
    applied = validate_success(
        api.apply_provider(
            create_provider_payload(
                legal_name="Alvarez Family Child Care",
                county_tier="STANDARD",
                license_number="FCC-1001",
                license_expires_on="2027-06-30T00:00:00Z",
                capacity_slots=6,
            ),
            NO_AUTH_HEADERS,
        ),
        201,
    )
    assert applied["membership_status"] == "APPLICANT"
    provider_id = applied["id"]

    verified = validate_success(
        api.verify_license(
            provider_id,
            create_license_verification_payload(
                license_number="FCC-1001", license_expires_on="2027-06-30T00:00:00Z"
            ),
            NETWORK_ADMIN_HEADERS,
        )
    )
    assert verified["membership_status"] == "PENDING_AGREEMENT"

    agreement = issue_agreement(
        provider_id,
        verified["version"],
        shared_services=["ENROLLMENT", "BILLING", "FOOD_PROGRAM", "SUBSTITUTE_POOL"],
    )
    executed = validate_success(
        api.execute_agreement(agreement["id"], None, make_provider_headers(provider_id))
    )
    assert executed["status"] == "EXECUTED"

    contract = create_contract(
        provider_id,
        daily_rate_cents=4500,
        contracted_slots=4,
        authorized_amount_cents=5000000,
        period_start_on="2026-08-01T00:00:00Z",
    )
    enrollment = create_enrollment(
        provider_id,
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )
    claim = create_claim(
        contract["id"],
        provider_id,
        "2026-08",
        [claim_line(enrollment["id"], 20, 0)],
        contract_version(contract["id"]),
    )
    submit_claim(claim["id"], provider_id)
    substitute = create_substitute(
        full_name="Ada Nkemelu",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2500,
        service_county_tiers=["STANDARD"],
    )
    assignment = request_coverage(
        provider_id,
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        reason="ILLNESS",
        min_credential_level="NONE",
    )

    advanced = validate_success(api.advance_claim(claim["id"], None, FISCAL_OFFICER_HEADERS))
    assert advanced["status"] == "ADVANCE_PAID"

    visit = validate_success(
        api.create_visit(
            create_visit_payload(provider_id, "2026-08-10T00:00:00Z", focus_area="CURRICULUM"),
            COACH_A_HEADERS,
        ),
        201,
    )
    assert visit["status"] == "SCHEDULED"

    accepted = validate_success(
        api.accept_assignment(
            assignment["id"], None, make_substitute_headers(substitute["id"])
        )
    )
    assert accepted["staffing_status"] == "CONFIRMED"

    for row in (applied, verified, executed, advanced, visit, accepted):
        assert_no_error_envelope(row)


# Cross-role denial


def test_the_fiscal_office_may_not_sign_a_membership_agreement_for_a_home(api):
    """Signing is the provider's own act, so another staff role is refused outright.

    The role gate sits above every piece of agreement logic, so the call never reaches the
    state machine: the offer is still outstanding and the home is still waiting to become a
    member.

    PRD: "The acting role appears in the endpoint's authorized-role list. `ERR_FORBIDDEN_ROLE`,
    HTTP 403. Applies to every endpoint."

    PRD: "Execution is the moment the provider becomes a member, and it is the provider — not
    staff — who performs it."

    Design: Corner/RBAC/fiscal_officer_cannot_execute_a_membership_agreement_forbidden_role
    """
    provider = apply_provider(legal_name="Alvarez Family Child Care")
    verified = verify_license(provider["id"])
    agreement = issue_agreement(
        provider["id"], verified["version"], shared_services=["ENROLLMENT"]
    )
    assert agreement["status"] == "SENT"

    validate_error(
        api.execute_agreement(agreement["id"], None, FISCAL_OFFICER_HEADERS),
        ApiErrorId.FORBIDDEN_ROLE.value,
        403,
    )

    stored = validate_success(api.get_agreement(agreement["id"], NETWORK_ADMIN_HEADERS))
    assert stored["status"] == "SENT"
    stored_provider = validate_success(
        api.get_provider(provider["id"], NETWORK_ADMIN_HEADERS)
    )
    assert stored_provider["membership_status"] == "PENDING_AGREEMENT"


def test_an_unauthenticated_caller_is_told_to_authenticate_rather_than_forbidden(api):
    """With no role header at all the answer is 401, not the 403 a wrong role would earn.

    Only the application endpoint is exempt from the header checks, so an enrollment request
    carrying no identity fails the very first check in the ladder. Because that check runs
    above the role gate, the caller learns they are unauthenticated rather than unauthorized,
    and nothing is stored.

    PRD: "`X-User-Role` present and equal to one of the six declared roles.
    `ERR_UNAUTHENTICATED`, HTTP 401. Applies to every endpoint except
    `POST /fccn/providers/apply`."

    Design: Corner/RBAC/anonymous_cannot_create_an_enrollment_and_is_unauthenticated
    """
    ctx = _enrolling_home()

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(
                ctx["provider_id"],
                child_ref="CH-1",
                family_name="Alvarez",
                days_per_week=5,
                private_monthly_tuition_cents=90000,
                subsidy_certified=False,
            ),
            NO_AUTH_HEADERS,
        ),
        ApiErrorId.UNAUTHENTICATED.value,
        401,
    )

    _, meta = validate_paginated(
        api.list_enrollments({"provider_id": ctx["provider_id"]}, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


# Ownership scope between peers


def test_one_home_may_not_read_another_homes_family(api):
    """The same endpoint and the same role are separated only by the acting identity.

    The owning home reads its own enrollment without difficulty. The second home, holding the
    identical role, is refused on ownership scope. The refusal is a 403 rather than a 404
    because the row plainly exists — it is simply none of that home's business.

    PRD: "A `Provider` actor may only address resources whose `provider_id` equals
    `X-User-ID`, whether directly or through the `contract_id` chain to
    `SubsidyContract.provider_id`; a `Substitute` actor may only address
    `SubstituteAssignment` rows whose `substitute_id` equals `X-User-ID`."

    Design: Corner/RBAC/provider_cannot_read_another_providers_enrollment_scope_violation
    """
    owner = _enrolling_home()
    stranger = _enrolling_home(
        legal_name="Brody Family Child Care", license_number="FCC-1002"
    )
    assert stranger["provider_id"] != owner["provider_id"]

    enrollment = create_enrollment(
        owner["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=90000,
        subsidy_certified=False,
    )

    own_read = validate_success(api.get_enrollment(enrollment["id"], owner["headers"]))
    assert own_read["child_ref"] == "CH-1"

    denied = api.get_enrollment(enrollment["id"], stranger["headers"])
    validate_error(denied, ApiErrorId.PROVIDER_SCOPE_VIOLATION.value, 403)
    assert denied.status_code != 404


def test_one_pool_member_may_not_accept_work_offered_to_another(api):
    """The offer belongs to the member it was made to, and only they can answer it.

    The cheaper member wins the selection, so the work is offered to them. The other member,
    holding the same role, is refused on ownership scope and the offer is left untouched. The
    member who actually holds it then accepts without difficulty.

    PRD: "Accepting requires the assignment's `staffing_status` to be `OFFERED`, requires the
    acting substitute to be the one named on `substitute_id`, and re-checks that their
    `pool_status` is `AVAILABLE` and their `clearance_expires_on` still falls on or after the
    assignment's `end_at`; it moves the assignment `OFFERED → CONFIRMED` and leaves
    `billing_status` untouched."

    Design: Corner/RBAC/substitute_cannot_accept_another_substitutes_assignment_scope_violation
    """
    ctx = _pool_home()
    offered = create_substitute(
        full_name="Offered Olive",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2000,
        service_county_tiers=["STANDARD"],
    )["id"]
    other = create_substitute(
        full_name="Other Otto",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=3000,
        service_county_tiers=["STANDARD"],
    )["id"]

    assignment = request_coverage(
        ctx["provider_id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        reason="ILLNESS",
        min_credential_level="NONE",
    )
    assert assignment["substitute_id"] == offered

    validate_error(
        api.accept_assignment(assignment["id"], None, make_substitute_headers(other)),
        ApiErrorId.SUBSTITUTE_SCOPE_VIOLATION.value,
        403,
    )
    untouched = validate_success(api.get_assignment(assignment["id"], NETWORK_ADMIN_HEADERS))
    assert untouched["staffing_status"] == "OFFERED"

    accepted = validate_success(
        api.accept_assignment(assignment["id"], None, make_substitute_headers(offered))
    )
    assert accepted["staffing_status"] == "CONFIRMED"


# Segregation of duties


def test_the_coach_who_opened_a_finding_may_not_be_the_one_who_signs_it_off(api):
    """Two coaches, one endpoint, and the outcome turns on which of them is acting.

    The review records the operator who opened it, and the closing check compares the acting
    operator against that record. The opener's own attempt is refused and leaves the review
    exactly where it was; the second coach's identical call closes it as compliant.

    PRD: "Closing requires the review to be `CAP_SUBMITTED` and requires the acting operator's
    identifier to differ from `opened_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES`
    otherwise."

    Design: Corner/RBAC/same_coach_cannot_close_a_review_they_opened_segregation_of_duties
    """
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
    )
    review = open_review(
        ctx["provider_id"], ["SUP-2"], "2026-09-15T00:00:00Z", headers=COACH_A_HEADERS
    )
    assert review["opened_by_user_id"] == COACH_A_USER_ID
    submitted = submit_cap(
        review["id"], ctx["provider_id"], "Storage rack anchored and staff retrained"
    )
    assert submitted["status"] == "CAP_SUBMITTED"

    validate_error(
        api.close_review(review["id"], None, COACH_A_HEADERS),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )
    untouched = validate_success(api.get_review(review["id"], NETWORK_ADMIN_HEADERS))
    assert untouched["status"] == "CAP_SUBMITTED"
    assert untouched["closed_by_user_id"] is None

    closed = validate_success(api.close_review(review["id"], None, COACH_B_HEADERS))
    assert closed["status"] == "CLOSED_COMPLIANT"
