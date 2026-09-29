"""Authorization: the positive half of the role matrix walked end to end, the
two denial rungs, the actor-identity separation on a league filing, and the
club-scoped operator identity.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_USER_ID,
    FARM_DIRECTOR_HEADERS,
    FARM_DIRECTOR_USER_ID,
    INTERNATIONAL_SCOUT_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_integer,
    assert_money,
    assert_status,
    factories,
    fixtures,
    make_affiliate_operator_headers,
    make_compliance_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_all_five_roles_carry_out_the_operations_the_contract_reserves_to_them(api: ApiClient):
    """One ordering exercises every role's own act with no refusal anywhere.

    PRD 2.1 fixes what each identity means: "When `X-User-Role` is
    `AffiliateOperator`, `X-User-ID` is the `id` of the acting `Affiliate`;
    ownership checks on any resource that references an `Affiliate` compare the
    resource's affiliate foreign-key field to `X-User-ID`."  The acts themselves
    are distributed by PRD 3.2 — "Submission is the club's act." and
    "Certification is compliance's act." — by PRD 3.5, which reserves the medical
    verdict ("Disposition of a clearance belongs exclusively to a
    `MedicalDirector`."), and by PRD 2.12, which splits the signing flow: "the
    `InternationalScout` role may submit a signing but only a `ComplianceOfficer`
    may approve one."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z", COMPLIANCE_OFFICER_HEADERS)

    academy = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Matrix Academy",
        level="DOMINICAN_ACADEMY",
        market_city="Boca Chica",
        meal_stipend_cents_per_day=2500,
    )
    club = fixtures.create_affiliate(
        api,
        FARM_DIRECTOR_HEADERS,
        name="Matrix Club",
        level="SINGLE_A",
        market_city="Clearwater",
        meal_stipend_cents_per_day=2600,
    )
    operator_headers = make_affiliate_operator_headers(club["id"])

    agreement = fixtures.create_agreement(
        api,
        club["id"],
        operator_headers,
        facility_standard_tier="TIER_2",
        club_reimbursement_cap_cents=900000,
        minimum_active_players=0,
    )
    submitted = fixtures.submit_agreement(api, agreement["id"], club["id"])
    assert_status(submitted, "SUBMITTED", "AffiliationAgreement")
    assert submitted["submitted_by_user_id"] == club["id"], (
        f"submission records the operator's identity, got {submitted['submitted_by_user_id']!r}"
    )
    activated = fixtures.activate_agreement(api, agreement["id"])
    assert_status(activated, "ACTIVE", "AffiliationAgreement")

    review = fixtures.file_facility_review(api, club["id"], "CLUBHOUSE", "2026-04-01", 92)
    assert_status(review, "CLOSED", "FacilityStandardReview")

    member = fixtures.create_staff_member(
        api,
        full_name="Matrix Coach",
        discipline="PITCHING",
        curriculum_version_certified="2026.1",
        certification_expires_on="2027-01-31",
    )
    assert member["id"], "a FarmDirector registers staff members"

    player = fixtures.create_player(
        api,
        FARM_DIRECTOR_HEADERS,
        full_name="Matrix Domestic",
        origin="DOMESTIC_DRAFT",
        signed_date="2025-06-10",
    )
    requested = fixtures.request_clearance(
        api, player["id"], "LEVEL_ASSIGNMENT", MEDICAL_DIRECTOR_HEADERS
    )
    issued = fixtures.dispose_clearance(
        api,
        requested["id"],
        "ISSUE",
        cleared_workload_ceiling_index=25.00,
        expires_on="2026-12-31",
    )
    assert_status(issued, "ISSUED", "MedicalClearance")
    assert issued["issued_by_user_id"] == "u-med-1", (
        f"the issuing director is recorded, got {issued['issued_by_user_id']!r}"
    )

    assignment = fixtures.create_assignment(
        api,
        player["id"],
        club["id"],
        assignment_type="LEVEL",
        movement_reason="INITIAL",
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    active = fixtures.dispose_assignment(api, assignment["id"], "ACTIVATE")
    assert_status(active, "ACTIVE", "PlayerAssignment")
    assert active["initiated_by_user_id"] == FARM_DIRECTOR_USER_ID, (
        f"the initiating director is recorded, got {active['initiated_by_user_id']!r}"
    )

    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=5000000)
    signing_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Matrix International",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    signing = fixtures.create_signing(
        api, pool["id"], signing_player["id"], academy["id"], bonus_cents=400000
    )
    assert_status(signing, "SUBMITTED", "InternationalSigning")
    assert_money(signing["bonus_cents"], 400000, "bonus_cents")


def test_the_two_denial_rungs_refuse_at_the_endpoint_and_at_the_action(api: ApiClient):
    """A role off the endpoint list and a role off the action list share one code.

    PRD 2.6 separates the two checks: "The acting role appears on the target
    endpoint, otherwise `ERR_ROLE_NOT_PERMITTED` (403)." and, four rungs later, "On
    every disposition endpoint, the requested `action` is one the acting role may
    request, otherwise `ERR_ROLE_NOT_PERMITTED` (403)."  The second rung is what
    stops an officer from submitting on the club's behalf, since PRD 3.2 assigns
    that act elsewhere: "Submission is the club's act."

    Design: Corner/rbac/roles_are_refused_on_operations_they_do_not_own
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z", COMPLIANCE_OFFICER_HEADERS)
    club = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Denied Club",
        level="SINGLE_A",
        market_city="Dunedin",
        meal_stipend_cents_per_day=2600,
    )
    operator_headers = make_affiliate_operator_headers(club["id"])
    agreement = fixtures.create_agreement(
        api,
        club["id"],
        COMPLIANCE_OFFICER_HEADERS,
        facility_standard_tier="TIER_2",
        club_reimbursement_cap_cents=900000,
        minimum_active_players=0,
    )
    player = fixtures.create_player(
        api,
        FARM_DIRECTOR_HEADERS,
        full_name="Denied Player",
        origin="DOMESTIC_DRAFT",
        signed_date="2025-06-10",
    )
    clearance = fixtures.request_clearance(api, player["id"], "LEVEL_ASSIGNMENT")

    # Rung 3: the role does not appear on the endpoint at all.
    validate_error(
        api.dispose_medical_clearance(
            clearance["id"],
            factories.disposition_payload(
                "ISSUE", cleared_workload_ceiling_index=25.00, expires_on="2026-12-31"
            ),
            FARM_DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.create_signing_pool(
            factories.signing_pool_payload(season_year=2026, base_pool_cents=5000000),
            MEDICAL_DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.create_staff_member(
            factories.staff_member_payload(
                full_name="Unauthorized Coach",
                discipline="PITCHING",
                curriculum_version_certified="2026.1",
                certification_expires_on="2027-01-31",
            ),
            INTERNATIONAL_SCOUT_HEADERS,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    # Rung 5: the role is on the endpoint, but not for this action.
    validate_error(
        api.dispose_agreement(
            agreement["id"],
            factories.disposition_payload("SUBMIT"),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.dispose_agreement(
            agreement["id"], factories.disposition_payload("ACTIVATE"), operator_headers
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    assert_status(
        fixtures.read_agreement(api, club["id"], agreement["id"]), "DRAFT", "AffiliationAgreement"
    )
    assert_integer(
        fixtures.read_agreement(api, club["id"], agreement["id"])["version"],
        1,
        "AffiliationAgreement.version",
    )

    submitted = fixtures.submit_agreement(api, agreement["id"], club["id"])
    assert_status(submitted, "SUBMITTED", "AffiliationAgreement")
    assert_integer(submitted["version"], 2, "AffiliationAgreement.version")


def test_the_operator_that_initiated_the_movement_cannot_certify_its_filing(api: ApiClient):
    """The refusal keys on X-User-ID, so the same role passes under another identity.

    PRD 2.6: "On a transaction-report `FILE` action, `X-User-ID` differs from the
    report's `initiated_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD 2.12 explains why the comparison is stable: "The `X-User-ID` of the
    `FarmDirector` that created an assignment is stored on the assignment as
    `initiated_by_user_id` and copied verbatim onto every transaction report that
    assignment produces."  PRD 2.12 also fixes which copy is read: "The comparison
    is on the report's copy, so it survives even if the assignment is later touched
    by someone else."  The deadline the
    filing is judged against comes from PRD 3.8: "A report's `filing_deadline` is
    two days after the producing assignment's `effective_date`."

    Design: Corner/rbac/the_initiating_director_may_not_certify_its_own_transaction_filing
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate_with_active_player(
        api,
        affiliate_overrides={
            "name": "Duties Club",
            "level": "SINGLE_A",
            "market_city": "Lakeland",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
        player_overrides={
            "full_name": "Duties Player",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )

    reports = fixtures.reports_for(api, club["assignment_id"])
    assert len(reports) == 1, f"activation files exactly one report, got {reports}"
    report = reports[0]
    assert report["transaction_type"] == "OPTIONAL_ASSIGNMENT", (
        f"an INITIAL activation files an OPTIONAL_ASSIGNMENT, got {report['transaction_type']!r}"
    )
    assert_status(report, "PENDING", "TransactionReport")
    assert report["initiated_by_user_id"] == FARM_DIRECTOR_USER_ID, (
        f"the report copies the initiating identity, got {report['initiated_by_user_id']!r}"
    )
    assert report["filing_deadline"] == "2026-04-03", (
        f"the deadline is two days after the effective date, got {report['filing_deadline']!r}"
    )

    collision = api.dispose_transaction_report(
        report["id"],
        factories.disposition_payload("FILE"),
        make_compliance_officer_headers(FARM_DIRECTOR_USER_ID),
    )
    validate_error(collision, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    unchanged = fixtures.reports_for(api, club["assignment_id"])[0]
    assert_status(unchanged, "PENDING", "TransactionReport")
    assert unchanged["certified_by_user_id"] is None, (
        f"a refused filing certifies nobody, got {unchanged['certified_by_user_id']!r}"
    )

    filed = fixtures.dispose_report(api, report["id"], "FILE")
    assert_status(filed, "FILED", "TransactionReport")
    assert filed["certified_by_user_id"] == COMPLIANCE_OFFICER_USER_ID, (
        f"filing records the certifying identity, got {filed['certified_by_user_id']!r}"
    )
    assert filed["is_late"] is False, (
        f"a filing inside the window is not late, got {filed!r}"
    )
    assert_money(filed["late_fee_cents"], 0, "late_fee_cents")


def test_an_operator_reaches_only_the_club_whose_id_it_carries(api: ApiClient):
    """Three cross-club attempts are refused; the same calls pass for the owner.

    PRD 2.6: "For an `AffiliateOperator`, `X-User-ID` equals the `Affiliate` id the
    target resource belongs to — the affiliate itself, or the `affiliate_id` on the
    agreement, the inspection or the allocation being touched — otherwise
    `ERR_AFFILIATE_SCOPE_VIOLATION` (403). This scope check guards four operations:
    drafting an agreement under an affiliate, filing an inspection under an
    affiliate, disposing of an agreement, and disposing of a facility inspection."
    When no resource exists to scope against, the ladder falls through to the path
    rung, which PRD 2.6 defines as "the not-found error for the leftmost unresolved
    segment (404)".

    Design: Corner/rbac/an_operator_cannot_reach_another_clubs_agreement
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z", COMPLIANCE_OFFICER_HEADERS)
    club_a = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Scope Club A",
        level="SINGLE_A",
        market_city="Bradenton",
        meal_stipend_cents_per_day=2600,
    )
    club_b = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Scope Club B",
        level="HIGH_A",
        market_city="Tampa",
        meal_stipend_cents_per_day=2800,
    )
    agreement = fixtures.create_agreement(
        api,
        club_a["id"],
        COMPLIANCE_OFFICER_HEADERS,
        facility_standard_tier="TIER_2",
        club_reimbursement_cap_cents=900000,
        minimum_active_players=0,
    )
    review = fixtures.file_facility_review(api, club_a["id"], "LIGHTING", "2026-04-01", 75)

    intruder = make_affiliate_operator_headers(club_b["id"])
    validate_error(
        api.dispose_agreement(
            agreement["id"], factories.disposition_payload("SUBMIT"), intruder
        ),
        ApiErrorId.ERR_AFFILIATE_SCOPE_VIOLATION.value,
        403,
    )
    validate_error(
        api.dispose_facility_review(
            review["id"],
            factories.disposition_payload(
                "SUBMIT_REMEDIATION", remediation_note="not our rig"
            ),
            intruder,
        ),
        ApiErrorId.ERR_AFFILIATE_SCOPE_VIOLATION.value,
        403,
    )
    validate_error(
        api.create_agreement(
            club_a["id"],
            factories.agreement_payload(
                term_start_date="2027-01-01",
                term_end_date="2027-12-31",
                facility_standard_tier="TIER_2",
                club_reimbursement_cap_cents=900000,
                minimum_active_players=0,
            ),
            intruder,
        ),
        ApiErrorId.ERR_AFFILIATE_SCOPE_VIOLATION.value,
        403,
    )
    _, meta = validate_paginated(api.list_agreements(club_a["id"], COMPLIANCE_OFFICER_HEADERS))
    assert_integer(meta["total_count"], 1, "agreement total_count")

    validate_error(
        api.dispose_agreement(
            "00000000-0000-4000-8000-000000000000",
            factories.disposition_payload("SUBMIT"),
            intruder,
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
        404,
    )

    owner = make_affiliate_operator_headers(club_a["id"])
    submitted = validate_success(
        api.dispose_agreement(
            agreement["id"], factories.disposition_payload("SUBMIT"), owner
        ),
        200,
    )
    assert_status(submitted, "SUBMITTED", "AffiliationAgreement")
    remediated = validate_success(
        api.dispose_facility_review(
            review["id"],
            factories.disposition_payload(
                "SUBMIT_REMEDIATION", remediation_note="rig replaced"
            ),
            owner,
        ),
        200,
    )
    assert_status(remediated, "REMEDIATION_SUBMITTED", "FacilityStandardReview")
