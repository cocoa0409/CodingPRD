"""
Six roles, six disjoint surfaces, and one identity comparison inside a single role.

The role check sits at priority 2 — above the shape check, above path existence, above the
concurrency check — so an impostor is turned away before the server ever looks at what it
asked for. Each of the four exclusive surfaces is probed from the roles most tempted to reach
into it, and each surface's own owner then makes the identical call successfully. The last
boundary is finer: two operators holding the same reviewer role are separated by the
identifier they act under.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    CLOCK_EPOCH,
    ERR_FORBIDDEN_ROLE,
    ERR_SEGREGATION_OF_DUTIES,
    LENDER,
    PROGRAM_ADMIN,
    REVIEWER_ALPHA,
    REVIEWER_BETA,
    acquisition_payload,
    add_assessment_phase,
    add_finding,
    assert_fields,
    assert_pagination_meta,
    assert_sweep_counters,
    assessment_phase_payload,
    continuing_obligation_payload,
    eligibility_decision_payload,
    enrollment_payload,
    funding_decision_payload,
    inquiry_completion_payload,
    issue_letter,
    laboratory_payload,
    lender_acceptance_payload,
    liability_protection_payload,
    make_consultant_headers,
    make_redeveloper_headers,
    monitoring_event_payload,
    nfa_letter_payload,
    party_payload,
    phase_review_payload,
    redeveloper_payload,
    run_sweep,
    set_clock,
    site_payload,
    stage_completion_review,
    stage_implementation,
    stage_protection,
    stage_registry,
    stage_site,
    submit_phase,
)

# ─── redeveloper_exclusive_operations_return_forbidden_role_for_other_roles ────────

IMPOSTOR_PARCEL = {
    "site_name": "Consultant-filed parcel",
    "county_code": "OH-035",
    "acreage": 2.0,
    "intended_reuse": "COMMERCIAL",
    "planned_acquisition_date": "2026-10-15",
}
PLATFORM_OPERATOR_STATEMENT = "Filed by the platform operator."


def test_the_owners_five_operations_are_refused_to_five_other_roles(api):
    """
    Consultant, lender, reviewer, administrator and carrier are all turned away.

    "If both headers are present but the supplied `X-User-Role` is not among the roles listed
    for the target endpoint in §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/redeveloper_exclusive_operations_return_forbidden_role_for_other_roles
    """
    world = stage_registry(api)

    validate_error(
        api.create_site(
            site_payload(world.redeveloper["id"], **IMPOSTOR_PARCEL),
            world.consult_headers,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_liability_protection(
            liability_protection_payload(NON_EXISTENT_UUID), LENDER
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.record_acquisition(
            NON_EXISTENT_UUID, acquisition_payload("2026-10-15"), REVIEWER_ALPHA
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_enrollment(
            enrollment_payload(
                NON_EXISTENT_UUID, applicant_statement=PLATFORM_OPERATOR_STATEMENT
            ),
            PROGRAM_ADMIN,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_nfa_letter(
            nfa_letter_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            world.insurer_headers,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    parcels, parcel_meta = validate_paginated(api.list_sites(REVIEWER_ALPHA))
    assert parcels == [], f"a refused create persisted a parcel: {parcels}"
    assert_pagination_meta(parcel_meta, expected_total=0)

    letters, letter_meta = validate_paginated(api.list_nfa_letters(REVIEWER_ALPHA))
    assert letters == [], f"a refused create persisted a letter: {letters}"
    assert_pagination_meta(letter_meta, expected_total=0)


def test_the_owning_redeveloper_files_the_identical_parcel(api):
    """
    The same body from the role that owns the operation is accepted.

    "The payload carries `owner_party_id` — which must resolve to a party whose `party_type` is
    `REDEVELOPER`, and which must equal the acting `X-User-ID`, since a redeveloper may only
    register sites it will own — plus `site_name` (1 to 160 characters), `county_code` (the
    regulator's county or district code for the parcel, 1 to 16 characters), `acreage` (strictly
    greater than zero, at most two decimal places), `intended_reuse`, and
    `planned_acquisition_date` as an ISO 8601 calendar date in `YYYY-MM-DD` form."

    Design: Corner/rbac/redeveloper_exclusive_operations_return_forbidden_role_for_other_roles
    """
    world = stage_registry(api)

    parcel = get_success_data(
        api.create_site(
            site_payload(world.redeveloper["id"], **IMPOSTOR_PARCEL),
            world.redev_headers,
        ),
        201,
    )
    assert_fields(
        parcel,
        owner_party_id=world.redeveloper["id"],
        site_name="Consultant-filed parcel",
        county_code="OH-035",
        intended_reuse="COMMERCIAL",
        planned_acquisition_date="2026-10-15",
    )


# ─── consultant_exclusive_operations_return_forbidden_role_for_other_roles ─────────

EDIT_TO_A_LATER_START = {"years_to_construction_start": 5}
IMPOSTOR_PERIOD_CODE = "X-2027-M01"


def test_assessment_and_remedy_authorship_is_refused_to_every_other_role(api):
    """
    Opening a phase, completing the inquiry, submitting, editing and scheduling are the
    consultant's alone.

    "**Role authorisation** — the acting `X-User-Role` appears in the endpoint's role list, else
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/consultant_exclusive_operations_return_forbidden_role_for_other_roles
    """
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    opened_version = world.protection["version"]

    validate_error(
        api.create_assessment_phase(
            assessment_phase_payload(world.site["id"], world.consultant["id"]),
            world.redev_headers,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.complete_inquiry(
            world.protection["id"],
            inquiry_completion_payload(NON_EXISTENT_UUID),
            world.redev_headers,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.submit_assessment_phase(NON_EXISTENT_UUID, REVIEWER_ALPHA),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.patch_plan(NON_EXISTENT_UUID, EDIT_TO_A_LATER_START, REVIEWER_ALPHA),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_monitoring_event(
            monitoring_event_payload(
                world.site["id"],
                world.laboratory["id"],
                NON_EXISTENT_UUID,
                monitoring_period_code=IMPOSTOR_PERIOD_CODE,
            ),
            LENDER,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    assert_fields(
        world.read_protection(), inquiry_state="AAI_PENDING", version=opened_version
    )

    phase = add_assessment_phase(world)
    add_finding(world, phase)
    assert_fields(submit_phase(world, phase), status="UNDER_REVIEW")

    phases, meta = validate_paginated(
        api.list_assessment_phases(world.consult_headers, site_id=world.site["id"])
    )
    assert len(phases) == 1, f"expected only the consultant's own phase, got {phases}"
    assert_pagination_meta(meta, expected_total=1)


# ─── insurer_exclusive_operations_return_forbidden_role_for_other_roles ────────────


def _quote_without_a_version(insurer_party_id, policy_reference):
    """A quote body that omits the OCC field entirely, to prove priority 2 runs first."""
    return {
        "remedial_action_plan_id": NON_EXISTENT_UUID,
        "insurer_party_id": insurer_party_id,
        "policy_reference": policy_reference,
        "term_years": 5,
    }


def test_quoting_and_binding_the_cost_cap_belong_to_the_carrier_alone(api):
    """
    Two malformed quotes and two binds are refused for the role, not for their contents.

    "Validations are evaluated in ascending priority order, and evaluation stops at the first
    violation: the first rule violated determines the response, and no later rule is even
    considered."

    Design: Corner/rbac/insurer_exclusive_operations_return_forbidden_role_for_other_roles
    """
    world = stage_registry(api)
    insurer_id = world.insurer["id"]

    validate_error(
        api.quote_policy(
            _quote_without_a_version(insurer_id, "CCP-X"), world.consult_headers
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.quote_policy(_quote_without_a_version(insurer_id, "CCP-Y"), REVIEWER_ALPHA),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.bind_policy(NON_EXISTENT_UUID, LENDER), ERR_FORBIDDEN_ROLE, 403
    )
    validate_error(
        api.bind_policy(NON_EXISTENT_UUID, world.redev_headers),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    policies, meta = validate_paginated(api.list_policies(world.insurer_headers))
    assert policies == [], f"a refused quote persisted a policy: {policies}"
    assert_pagination_meta(
        meta,
        expected_total=0,
        expected_limit=10,
        expected_offset=0,
        expected_has_more=False,
    )


# ─── reviewer_exclusive_operations_return_forbidden_role_for_other_roles ───────────

SWEEP_DATE = "2026-08-01"
SELF_IMPOSED_DESCRIPTION = "Self-imposed obligation."
SELF_APPROVED_NOTE = "Self-approved."
SELF_AWARDED_NOTE = "Self-awarded."


def test_every_adjudication_is_refused_to_the_parties_it_decides_upon(api):
    """
    Sweep, phase review, imposition, eligibility, approval, funding and issuance all refuse.

    "If both headers are present but the supplied `X-User-Role` is not among the roles listed
    for the target endpoint in §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/reviewer_exclusive_operations_return_forbidden_role_for_other_roles
    """
    world = stage_registry(api)

    validate_error(
        api.run_compliance_sweep(SWEEP_DATE, world.redev_headers),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.review_assessment_phase(
            NON_EXISTENT_UUID, phase_review_payload("APPROVE"), world.consult_headers
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.impose_continuing_obligation(
            NON_EXISTENT_UUID,
            continuing_obligation_payload(description=SELF_IMPOSED_DESCRIPTION),
            world.redev_headers,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.decide_eligibility(
            NON_EXISTENT_UUID,
            eligibility_decision_payload("ENROLL", decision_note=SELF_APPROVED_NOTE),
            world.redev_headers,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.approve_plan(NON_EXISTENT_UUID, world.consult_headers),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.decide_funding_award(
            NON_EXISTENT_UUID,
            funding_decision_payload("AWARD", decision_note=SELF_AWARDED_NOTE),
            world.redev_headers,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.issue_nfa_letter(NON_EXISTENT_UUID, LENDER), ERR_FORBIDDEN_ROLE, 403
    )


def test_the_agencys_own_sweep_over_an_empty_programme_returns_six_zeroes(api):
    """
    The role that owns the checkpoint runs it, and finds nothing to advance.

    "Its response echoes the `as_of_date` and carries six counters: `swept_obligation_count` for
    the duties examined and advanced, `at_risk_count` and `lapsed_count` for the two adverse
    landings, `stale_inquiry_count` for the inquiries expired, `forfeited_protection_count` for
    the defences lost, and `frozen_site_count` for the parcels frozen as a consequence."

    Design: Corner/rbac/reviewer_exclusive_operations_return_forbidden_role_for_other_roles
    """
    world = stage_registry(api)

    result = run_sweep(world, SWEEP_DATE)
    assert_fields(result, as_of_date=SWEEP_DATE)
    assert_sweep_counters(
        result,
        swept_obligation_count=0,
        at_risk_count=0,
        lapsed_count=0,
        stale_inquiry_count=0,
        forfeited_protection_count=0,
        frozen_site_count=0,
    )


# ─── lender_and_program_admin_boundaries_return_forbidden_role ─────────────────────

SELF_ACTING_USER_ID = "party-self"
SELF_REGISTERED_PARTY = {"legal_name": "Self-registered LLC", "party_type": "REDEVELOPER"}
SELF_REGISTERED_LAB = {
    "lab_name": "Consultant-registered Lab",
    "certification_code": "NELAP-OH-999",
    "concurrent_capacity": 5,
}


def test_acceptance_and_registration_are_refused_to_the_roles_they_serve(api):
    """
    The two smallest surfaces are exclusive too, and nothing they refuse persists.

    "**Role authorisation** — the acting `X-User-Role` appears in the endpoint's role list, else
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/lender_and_program_admin_boundaries_return_forbidden_role
    """
    set_clock(api, CLOCK_EPOCH)

    validate_error(
        api.accept_nfa_letter(
            NON_EXISTENT_UUID,
            lender_acceptance_payload("LOAN-SELF"),
            make_redeveloper_headers(SELF_ACTING_USER_ID),
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.accept_nfa_letter(
            NON_EXISTENT_UUID, lender_acceptance_payload("LOAN-AGENCY"), REVIEWER_ALPHA
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_party(
            party_payload(**SELF_REGISTERED_PARTY),
            make_redeveloper_headers(SELF_ACTING_USER_ID),
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_laboratory(
            laboratory_payload(**SELF_REGISTERED_LAB),
            make_consultant_headers(SELF_ACTING_USER_ID),
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    parties, party_meta = validate_paginated(api.list_parties(PROGRAM_ADMIN))
    assert parties == [], f"a refused registration persisted a party: {parties}"
    assert_pagination_meta(party_meta, expected_total=0)

    labs, lab_meta = validate_paginated(api.list_laboratories(PROGRAM_ADMIN))
    assert labs == [], f"a refused registration persisted a laboratory: {labs}"
    assert_pagination_meta(lab_meta, expected_total=0)


def test_the_administrator_keeps_both_registries_itself(api):
    """
    The identical registrations land when the administrator makes them.

    "`ProgramAdmin` maintains the party registry and the accredited laboratory list and
    otherwise only reads."

    Design: Corner/rbac/lender_and_program_admin_boundaries_return_forbidden_role
    """
    set_clock(api, CLOCK_EPOCH)

    party = get_success_data(api.create_party(redeveloper_payload(), PROGRAM_ADMIN), 201)
    assert_fields(party, party_type="REDEVELOPER")

    laboratory = get_success_data(
        api.create_laboratory(laboratory_payload(), PROGRAM_ADMIN), 201
    )
    assert_fields(laboratory, concurrent_capacity=10)

    _parties, party_meta = validate_paginated(api.list_parties(PROGRAM_ADMIN))
    assert_pagination_meta(party_meta, expected_total=1)

    _labs, lab_meta = validate_paginated(api.list_laboratories(PROGRAM_ADMIN))
    assert_pagination_meta(lab_meta, expected_total=1)


# ─── the_approving_reviewer_cannot_also_issue_the_closure_letter ───────────────────

ISSUANCE_DATE = "2027-06-01"


def test_the_reviewer_who_approved_the_remedy_cannot_issue_the_letter(api):
    """
    Same role, different identifier: priority 2 passes and priority 7 refuses.

    "The acting `X-User-ID` must differ from that plan's `approved_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_approving_reviewer_cannot_also_issue_the_closure_letter
    """
    world = stage_implementation(api)
    stage_completion_review(world)
    assert_fields(world.read_plan(), approved_by_user_id="reviewer-alpha")

    refused = api.issue_nfa_letter(world.letter["id"], REVIEWER_ALPHA)
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

    assert_fields(world.read_letter(), status="DRAFT", issued_on=None)
    assert_fields(world.read_enrollment(), status="COMPLETION_REVIEW")


def test_a_second_reviewer_issues_the_identical_request(api):
    """
    The letter issues the moment a different agency identifier signs it.

    "Issuance moves the letter `DRAFT → ISSUED`, sets `issued_on` from the logical clock's date,
    records `issued_by_user_id`, and stores `controls_certified_count` as the number of site
    controls on the parcel whose `status` is `OPERATING` at that instant."

    Design: Corner/rbac/the_approving_reviewer_cannot_also_issue_the_closure_letter
    """
    world = stage_implementation(api)
    stage_completion_review(world)

    issued = issue_letter(world, headers=REVIEWER_BETA)
    assert_fields(
        issued,
        status="ISSUED",
        issued_by_user_id="reviewer-beta",
        issued_on=ISSUANCE_DATE,
        controls_certified_count=1,
    )
