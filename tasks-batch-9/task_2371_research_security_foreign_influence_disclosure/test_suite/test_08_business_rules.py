"""Business-rule corners: uniqueness, rejection ordering, window sanity, effort
ceilings and the cross-aggregate gates that guard clearance and certification.

Every test builds its own world from scratch. The harness restarts the server
before each test, so the database is empty and the logical clock sits at its
mandatory startup default of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    CRO,
    CRO_USER_ID,
    NON_EXISTENT_UUID,
    RSO,
    RSO_USER_ID,
    ApiErrorId,
    acknowledge_plan,
    add_disclosure_item,
    add_personnel,
    assert_version_unchanged,
    begin_review,
    certify_disclosure,
    create_access_grant_payload,
    create_disclosure,
    create_disclosure_payload,
    create_investigator,
    create_investigator_payload,
    create_organization,
    create_project,
    create_subaward,
    issue_plan,
    read_disclosure,
    read_disclosure_item,
    read_investigator,
    read_project,
    require_plan,
    screen_subaward,
    set_clock,
    set_item_status,
    setup_disclosure_under_review,
    setup_project_with_active_pi,
    submit_disclosure,
    validate_error,
    validate_paginated,
    validate_success,
)

CYCLE = "2026-ANNUAL"


# --------------------------------------------------------------------------- #
# Local setup helpers
# --------------------------------------------------------------------------- #

def _setup_capped_plan_investigator(plan_effort_cap_pct: int) -> tuple:
    """An investigator on full institutional base effort whose disclosure carries a
    live, acknowledged management plan capping total_commitment_pct.

    The plan requirement is warranted by a `TALENT_PROGRAM` item in `DECLARED`
    status, and the plan expires well after the logical clock so it is in force.

    Returns (investigator_id, disclosure).
    """
    investigator = create_investigator(full_name="Farid Lund")
    organization = create_organization(
        legal_name="Talent Scheme Bureau",
        country_code="CN",
        org_type="TALENT_PROGRAM",
        own_designation="NONE",
    )
    disclosure = create_disclosure(investigator["id"])
    add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="TALENT_PROGRAM",
        start_date="2025-06-01T00:00:00Z",
        annual_effort_hours=0,
        is_paid=False,
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    begin_review(disclosure["id"])
    require_plan(disclosure["id"])
    issue_plan(
        disclosure["id"],
        plan_effort_cap_pct=plan_effort_cap_pct,
        plan_required_actions=["REDUCE_OUTSIDE_EFFORT", "QUARTERLY_ATTESTATION"],
        plan_effective_from="2026-08-01T00:00:00Z",
        plan_expires_on="2027-08-01T00:00:00Z",
    )
    acknowledge_plan(disclosure["id"], investigator["id"])
    return investigator["id"], read_disclosure(disclosure["id"])


# --------------------------------------------------------------------------- #
# Uniqueness
# --------------------------------------------------------------------------- #

def test_second_investigator_with_an_email_already_on_file_is_refused(api):
    """PRD §3.1: "The `email` is the institution's unique handle for the person;
    registering a second investigator with an `email` already on file is refused
    with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/validations/duplicate_investigator_email_rejected
    """
    set_clock()
    create_investigator(full_name="Carla Imani", email="carla.imani@uni.edu")

    # Otherwise valid body, so the uniqueness check is what fails, not the shape check.
    response = api.create_investigator(
        create_investigator_payload(
            full_name="Carla Imani (visiting)",
            email="carla.imani@uni.edu",
            appointment_type="RESEARCH_STAFF",
            home_department="Law",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_EMAIL.value, expected_status=409)

    _rows, meta = validate_paginated(api.list_investigators(ADMIN))
    assert meta["total_count"] == 1, "the refused registration must not have persisted"


def test_new_cycle_disclosure_supersedes_the_live_record_but_a_certified_one_blocks_it(api):
    """PRD §3.3: "Only one live disclosure may exist per investigator and
    `cycle_label`. If a `CERTIFIED` or `REJECTED` disclosure already exists for that
    pair, the create is refused with `ERR_DUPLICATE_DISCLOSURE_CYCLE`. Otherwise any
    prior disclosure for the same pair whose review status is `DRAFT`, `SUBMITTED`,
    `UNDER_REVIEW` or `RETURNED_FOR_REVISION` transitions to `SUPERSEDED` as a side
    effect of the create, its `plan_status` left exactly as it was, and the
    superseded record stops counting toward any project's `activation_blockers`; the
    investigator's `risk_score` is then recomputed and their `disclosure_posture`
    after it."

    Design: Corner/validations/duplicate_cycle_blocks_a_draft_but_supersedes_a_submitted_disclosure
    """
    set_clock()
    investigator = create_investigator(
        full_name="Dmitri Jalen", email="dmitri.jalen@uni.edu"
    )
    first = create_disclosure(investigator["id"], cycle_label=CYCLE)

    # A DRAFT incumbent is a supersede-able source state, so the create succeeds.
    second = create_disclosure(investigator["id"], cycle_label=CYCLE)
    superseded_first = read_disclosure(first["id"])
    assert superseded_first["review_status"] == "SUPERSEDED"
    assert superseded_first["plan_status"] == "NOT_REQUIRED", (
        "supersession leaves plan_status exactly as it was"
    )
    assert second["review_status"] == "DRAFT"
    assert second["revision_round"] == 0

    # A SUBMITTED incumbent is supersede-able too.
    submit_disclosure(second["id"], investigator["id"])
    third = create_disclosure(investigator["id"], cycle_label=CYCLE)
    assert read_disclosure(second["id"])["review_status"] == "SUPERSEDED"
    assert third["review_status"] == "DRAFT"

    # Once the cycle carries a CERTIFIED record, uniqueness bites.
    submit_disclosure(third["id"], investigator["id"])
    begin_review(third["id"])
    certified = certify_disclosure(third["id"])
    assert certified["review_status"] == "CERTIFIED"

    current = read_investigator(investigator["id"])
    response = api.create_disclosure(
        create_disclosure_payload(
            investigator["id"], current["version"], cycle_label=CYCLE
        ),
        RSO,
    )
    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_DISCLOSURE_CYCLE.value, expected_status=409
    )

    _rows, meta = validate_paginated(
        api.list_disclosures(ADMIN, params={"investigator_id": investigator["id"]})
    )
    assert meta["total_count"] == 3, "the refused create must not have persisted"


# --------------------------------------------------------------------------- #
# Order of rejection
# --------------------------------------------------------------------------- #

def test_system_admin_security_status_write_on_a_missing_project_is_unauthorized(api):
    """PRD §2.8: "Because most write endpoints in this system are guarded by several
    independent checks at once, the **order** in which those checks run is part of
    the contract: a request that violates two rules must fail with the earlier rule's
    error, not the later one's. The evaluation order is the following twenty steps,
    and the first step that fails ends the request."

    Design: Corner/validations/security_status_write_by_system_admin_returns_403_before_404
    """
    set_clock()

    # Role admissibility (step 2) outranks path existence (step 4): the security
    # dimension belongs to the ResearchSecurityOfficer, so the 404 never leaks.
    response = api.set_security_status(
        NON_EXISTENT_UUID, {"to_status": "CLEARED"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_disclosure_create_without_the_acting_user_header_is_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity in which that user is
    acting. If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    Design: Corner/validations/disclosure_create_missing_x_user_id_returns_401_unauthenticated
    """
    set_clock()
    unrelated = create_investigator(
        full_name="Rhea Castellan",
        email="rhea.castellan@uni.edu",
        home_department="Philosophy",
    )

    headers_without_user_id = {
        "X-User-Role": "Investigator",
        "Content-Type": "application/json",
    }
    # The body is also malformed (no cycle_label) and names a missing investigator,
    # yet header presence is checked before any other processing.
    response = api.create_disclosure(
        {
            "investigator_id": NON_EXISTENT_UUID,
            "disclosure_type": "ANNUAL",
            "expected_investigator_version": unrelated["version"],
        },
        headers_without_user_id,
    )
    validate_error(
        response, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
    )


# --------------------------------------------------------------------------- #
# Interval sanity
# --------------------------------------------------------------------------- #

def test_zero_length_grant_window_is_refused(api):
    """PRD §3.7: "A request names the `project_id` whose controlled area is being
    entered, the `investigator_id`, a `valid_from` instant, a `valid_until` instant
    that must fall strictly after `valid_from` (else `ERR_INVALID_GRANT_WINDOW`, HTTP
    422), and the `expected_project_version` demanded by §2.7 — on success the
    project's `version` increments by one."

    Design: Corner/validations/grant_window_must_not_end_when_it_starts
    """
    set_clock()
    investigator = create_investigator(
        full_name="Elif Karsten", email="elif.karsten@uni.edu"
    )
    project = create_project(
        title="Zero Window Facility",
        agency_code="NIH",
        sensitivity_level="CONTROLLED",
        award_amount_cents=15_000_000,
        controlled_area_capacity=3,
    )
    before = read_project(project["id"])

    # Interval sanity sits behind the version guard, so the supplied version is current.
    response = api.create_access_grant(
        create_access_grant_payload(
            project["id"],
            investigator["id"],
            before["version"],
            valid_from="2026-09-01T00:00:00Z",
            valid_until="2026-09-01T00:00:00Z",
        ),
        RSO,
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_GRANT_WINDOW.value, expected_status=422
    )

    _rows, meta = validate_paginated(
        api.list_access_grants(RSO, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 0, "the refused grant must not have persisted"
    assert_version_unchanged(before, read_project(project["id"]), "project")


# --------------------------------------------------------------------------- #
# Effort ceiling
# --------------------------------------------------------------------------- #

def test_personnel_activation_respects_the_acknowledged_plan_effort_cap(api):
    """PRD §3.2: "And if the investigator holds a disclosure whose `plan_status` is
    `PLAN_ACKNOWLEDGED` and whose `plan_expires_on` is still ahead of the logical
    clock, their `total_commitment_pct` after this activation must be at most that
    plan's `plan_effort_cap_pct`, else `ERR_EFFORT_CAP_EXCEEDED`."

    Design: Corner/validations/personnel_activation_respects_the_acknowledged_plan_effort_cap
    """
    set_clock()
    investigator_id, disclosure = _setup_capped_plan_investigator(105)
    assert disclosure["plan_status"] == "PLAN_ACKNOWLEDGED"
    assert disclosure["plan_approver_user_id"] == CRO_USER_ID
    assert disclosure["reviewer_user_id"] == RSO_USER_ID
    assert read_investigator(investigator_id)["disclosure_posture"] == "CLEAR"

    project = create_project(
        title="Capped Effort Award", agency_code="NSF", award_amount_cents=25_000_000
    )
    big_row = add_personnel(
        project["id"],
        investigator_id,
        role_on_project="PI",
        committed_person_months=1.00,
        activate=False,
    )
    small_row = add_personnel(
        project["id"],
        investigator_id,
        role_on_project="CO_PI",
        committed_person_months=0.50,
        activate=False,
    )

    # 1.00 person-month lands total_commitment_pct at 108.33, above the 105 cap.
    refused = api.set_personnel_status(big_row["id"], {"to_status": "ACTIVE"}, ADMIN)
    validate_error(
        refused, ApiErrorId.ERR_EFFORT_CAP_EXCEEDED.value, expected_status=409
    )
    unchanged_row = validate_success(api.get_personnel(big_row["id"], ADMIN))
    assert unchanged_row["status"] == "PROPOSED"

    # 0.50 person-months lands at 104.17 and is admissible under the same cap.
    allowed = api.set_personnel_status(small_row["id"], {"to_status": "ACTIVE"}, ADMIN)
    assert validate_success(allowed, expected_status=200)["status"] == "ACTIVE"

    investigator = read_investigator(investigator_id)
    assert investigator["committed_effort_pct"] == pytest.approx(4.17, abs=0.01)
    assert investigator["total_commitment_pct"] == pytest.approx(104.17, abs=0.01)
    assert investigator["overcommitment_pct"] == pytest.approx(4.17, abs=0.01)


# --------------------------------------------------------------------------- #
# Cross-aggregate gates
# --------------------------------------------------------------------------- #

def test_pending_subaward_screening_blocks_initial_project_clearance(api):
    """PRD §3.6: "Initial clearance, `PENDING_CLEARANCE → CLEARED`, requires two
    things: no subaward on the project may be in `PENDING`, `FLAGGED` or `BLOCKED`,
    else `ERR_SUBAWARD_SCREENING_OPEN`; and no investigator holding an `ACTIVE`
    personnel row on the project may have a `disclosure_posture` of `SUSPENDED`, else
    `ERR_INVESTIGATOR_SUSPENDED`."

    Design: Corner/validations/pending_subaward_screening_blocks_project_clearance_until_screened
    """
    set_clock()
    project, _investigator, _personnel = setup_project_with_active_pi(
        investigator_overrides={
            "full_name": "Gwen Mbeki",
            "email": "gwen.mbeki@uni.edu",
        },
        title="Andes Climate Survey",
        agency_code="NSF",
        award_amount_cents=18_000_000,
    )
    organization = create_organization(
        legal_name="Southern Field Station",
        country_code="CL",
        org_type="INSTITUTE",
        own_designation="NONE",
    )
    subaward = create_subaward(
        project["id"],
        organization["id"],
        scope="Field sampling logistics",
        amount_cents=2_500_000,
    )
    assert subaward["status"] == "PENDING"

    refused = api.set_security_status(
        project["id"], {"to_status": "CLEARED"}, RSO
    )
    validate_error(
        refused, ApiErrorId.ERR_SUBAWARD_SCREENING_OPEN.value, expected_status=409
    )
    assert read_project(project["id"])["security_status"] == "PENDING_CLEARANCE"

    screened = screen_subaward(subaward["id"], "OWNERSHIP_TRANSITIVE")
    assert screened["status"] == "CLEARED"
    assert screened["applied_screening_variant"] == "OWNERSHIP_TRANSITIVE"
    assert screened["screening_designation"] == "NONE"
    assert screened["screening_match_depth"] == 0
    assert screened["screening_matched_organization_id"] == organization["id"]
    assert screened["screening_risk_points"] == 0

    cleared = validate_success(
        api.set_security_status(project["id"], {"to_status": "CLEARED"}, RSO),
        expected_status=200,
    )
    assert cleared["security_status"] == "CLEARED"
    assert cleared["security_status_reason"] == "OFFICER_ACTION"
    assert cleared["activation_blockers"] == ["DISCLOSURE_NOT_CERTIFIED"]
    assert cleared["controlled_area_posture"] == "LOCKED_DOWN"


def test_certification_waits_until_the_disputed_item_is_adjudicated(api):
    """PRD §3.4: "And no item may be in `DISPUTED`, else `ERR_DISPUTED_ITEMS_OPEN`."

    Design: Corner/validations/disclosure_certify_waits_until_the_disputed_item_is_resolved
    """
    set_clock()
    investigator = create_investigator(
        full_name="Hugo Nazari",
        email="hugo.nazari@uni.edu",
        home_department="Pharmacy",
    )
    organization = create_organization(
        legal_name="Coastal Research Trust",
        country_code="NZ",
        org_type="INSTITUTE",
        own_designation="NONE",
    )
    disclosure, items = setup_disclosure_under_review(
        investigator["id"],
        items=[
            {
                "item_type": "OUTSIDE_SUPPORT",
                "start_date": "2025-07-01T00:00:00Z",
                "annual_effort_hours": 0,
                "is_paid": False,
            }
        ],
        organization_id=organization["id"],
    )
    item = items[0]
    set_item_status(item["id"], "DISPUTED", headers=RSO)

    refused = api.review_disclosure(disclosure["id"], {"action": "CERTIFY"}, RSO)
    validate_error(
        refused, ApiErrorId.ERR_DISPUTED_ITEMS_OPEN.value, expected_status=409
    )
    still_open = read_disclosure(disclosure["id"])
    assert still_open["review_status"] == "UNDER_REVIEW"
    assert still_open["certified_at"] is None

    # The conflict reviewer resolves the dispute in the investigator's favour.
    set_item_status(item["id"], "VERIFIED", headers=CRO)
    assert read_disclosure_item(item["id"])["status"] == "VERIFIED"
    assert read_investigator(investigator["id"])["risk_score"] == 8

    certified = validate_success(
        api.review_disclosure(disclosure["id"], {"action": "CERTIFY"}, RSO),
        expected_status=200,
    )
    assert certified["review_status"] == "CERTIFIED"
    assert certified["certified_at"].startswith("2026-08-01T00:00:00")
    assert certified["completeness_score"] == 100
    assert certified["completeness_tier"] == "A"
    assert certified["item_count"] == 1
