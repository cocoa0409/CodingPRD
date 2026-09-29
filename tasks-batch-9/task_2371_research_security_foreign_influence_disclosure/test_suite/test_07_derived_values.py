"""Derived-value corners: risk points, reconciliation input sets, completeness
scoring, capacity projection, travel device tiers, incident severity bands and the
effective-designation walk.

Every test builds its own data from scratch. The harness restarts the server before
each test, so the database is empty and the logical clock sits at its mandatory
startup default of 2026-08-01T00:00:00Z; the clock is still pinned explicitly
wherever an assertion depends on a clock-derived instant.
"""

import pytest

from test_helpers import (
    RSO,
    RSO_USER_ID,
    add_disclosure_item,
    add_personnel,
    begin_review,
    certify_disclosure,
    create_access_grant_payload,
    create_disclosure,
    create_disclosure_item_payload,
    create_foreign_organization_payload,
    create_incident,
    create_investigator,
    create_organization,
    create_project,
    create_support_statement,
    create_travel_registration_payload,
    investigate_incident,
    make_investigator_headers,
    read_access_grant,
    read_disclosure,
    read_investigator,
    read_organization,
    read_project,
    return_for_revision,
    set_clock,
    set_grant_status,
    setup_active_access_grant,
    submit_disclosure,
    validate_success,
)


def test_paid_surcharge_lands_after_the_designation_multiplier(api):
    """PRD §3.3: "Multiply that base by the counterparty's exposure multiplier, read
    from the referenced organization's `effective_designation`: 1.0 for `NONE`, 1.5
    for `UNVERIFIED_END_USER`, 2.0 for `ENTITY_LIST`, 2.5 for `FOREIGN_MILITARY`,
    and 3.0 for both `MALIGN_TALENT_PROGRAM` and `SDN`. If the relationship is
    compensated — `is_paid` true — add a flat surcharge of 5 after the
    multiplication. Round the result half up to a whole number; that whole number is
    the item's contribution."

    Design: Corner/calculations/risk_score_adds_paid_surcharge_after_the_designation_multiplier
    """
    set_clock()
    org_unverified = create_organization(
        legal_name="Unverified Trading Co",
        country_code="SG",
        org_type="COMPANY",
        own_designation="UNVERIFIED_END_USER",
        designated_on="2025-03-01T00:00:00Z",
    )
    org_plain = create_organization(
        legal_name="Plain Partner College",
        country_code="KR",
        org_type="UNIVERSITY",
        own_designation="NONE",
    )
    investigator = create_investigator(
        full_name="Viktor Adler", home_department="Mathematics"
    )
    disclosure = create_disclosure(investigator["id"])

    # 12 * 1.5 = 18, then the flat paid surcharge of 5 on top of the product.
    paid_appointment = add_disclosure_item(
        disclosure["id"],
        org_unverified["id"],
        investigator_id=investigator["id"],
        item_type="FOREIGN_APPOINTMENT",
        start_date="2025-04-01T00:00:00Z",
        annual_effort_hours=0,
        is_paid=True,
        compensation_usd_cents=1_200_000,
    )
    unpaid_scholar = add_disclosure_item(
        disclosure["id"],
        org_plain["id"],
        investigator_id=investigator["id"],
        item_type="VISITING_SCHOLAR",
        start_date="2025-05-01T00:00:00Z",
        annual_effort_hours=0,
        is_paid=False,
    )
    submit_disclosure(disclosure["id"], investigator["id"])

    assert paid_appointment["item_risk_points"] == 23
    assert unpaid_scholar["item_risk_points"] == 10

    verified_first = validate_success(
        api.set_disclosure_item_status(
            paid_appointment["id"], {"to_status": "VERIFIED"}, RSO
        )
    )
    assert verified_first["status"] == "VERIFIED"
    after_first = read_investigator(investigator["id"])
    assert after_first["risk_score"] == 23
    assert after_first["disclosure_posture"] == "CLEAR"

    validate_success(
        api.set_disclosure_item_status(
            unpaid_scholar["id"], {"to_status": "VERIFIED"}, RSO
        )
    )
    after_second = read_investigator(investigator["id"])
    assert after_second["risk_score"] == 33
    assert after_second["disclosure_posture"] == "REVIEW_REQUIRED"
    assert after_second["outside_effort_pct"] == pytest.approx(0.00, abs=0.01)


def test_strict_agency_reconciliation_counts_only_same_agency_personnel(api):
    """PRD §3.5: "Under `STRICT_AGENCY` — the view a single sponsor takes of its own
    current-and-pending page — the institutional truth counts only those personnel
    rows of this investigator whose `status` is `ACTIVE` **and** whose project's
    `agency_code` equals the statement's `agency_code`; it draws disclosure items
    from exactly one source, the single newest disclosure of this investigator whose
    review status is `CERTIFIED`, selected by the latest `submitted_at` and breaking
    ties by the latest `created_at`; it counts only items whose `item_type` is
    `FOREIGN_APPOINTMENT`; and it never converts outside hours into person-months,
    so the outside contribution is 0.00."

    Design: Corner/calculations/support_reconciliation_strict_agency_filters_personnel_by_agency
    """
    set_clock()
    investigator = create_investigator(
        full_name="Wanda Bryce", home_department="Biology"
    )
    organization = create_organization(
        legal_name="Overseas Lab Partner",
        country_code="JP",
        org_type="INSTITUTE",
        own_designation="NONE",
    )
    nsf_project = create_project(
        title="NSF Genomics Award",
        agency_code="NSF",
        sensitivity_level="STANDARD",
        award_amount_cents=20_000_000,
    )
    nih_project = create_project(
        title="NIH Proteomics Award",
        agency_code="NIH",
        sensitivity_level="STANDARD",
        award_amount_cents=35_000_000,
    )
    add_personnel(
        nsf_project["id"],
        investigator["id"],
        role_on_project="PI",
        committed_person_months=2.00,
    )
    add_personnel(
        nih_project["id"],
        investigator["id"],
        role_on_project="CO_PI",
        committed_person_months=3.00,
    )

    disclosure = create_disclosure(investigator["id"])
    add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="FOREIGN_APPOINTMENT",
        start_date="2025-01-15T00:00:00Z",
        annual_effort_hours=0,
        is_paid=False,
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    begin_review(disclosure["id"])
    certify_disclosure(disclosure["id"])

    statement = create_support_statement(
        investigator["id"],
        nsf_project["id"],
        agency_code="NSF",
        document_type="CURRENT_AND_PENDING",
        declared_person_months=2.00,
        declared_appointment_count=1,
        declared_support_count=0,
    )

    # The 3.00 person-month NIH commitment is invisible to an NSF statement.
    reconciled = validate_success(
        api.reconcile_support_statement(
            statement["id"], {"variant": "STRICT_AGENCY"}, RSO
        )
    )
    assert reconciled["applied_variant"] == "STRICT_AGENCY"
    assert reconciled["institutional_person_months"] == pytest.approx(2.00, abs=0.01)
    assert reconciled["variance_person_months"] == pytest.approx(0.00, abs=0.01)
    assert reconciled["omission_count"] == 0
    assert reconciled["verdict"] == "CONSISTENT"
    assert reconciled["status"] == "RECONCILED"

    after = read_investigator(investigator["id"])
    assert after["material_discrepancy_count"] == 0
    assert after["risk_score"] == 12
    assert after["disclosure_posture"] == "CLEAR"
    # 2.00 / 12 rounds to 16.67 and 3.00 / 12 to 25.00, summed after rounding.
    assert after["committed_effort_pct"] == pytest.approx(41.67, abs=0.01)
    assert "SUPPORT_INCONSISTENT" not in read_project(nsf_project["id"])[
        "activation_blockers"
    ]


def test_late_item_count_counts_only_items_added_after_a_revision_round(api):
    """PRD §3.3: "`late_item_count` is the number of items that were created while
    the disclosure's `revision_round` was already at least 1 — a relationship
    surfaced only after the office pushed back."

    Design: Corner/calculations/completeness_counts_only_items_created_after_a_revision_round
    """
    set_clock()
    organization = create_organization(
        legal_name="Modest Institute",
        country_code="DE",
        org_type="INSTITUTE",
        own_designation="NONE",
    )
    investigator = create_investigator(
        full_name="Xenia Corbin",
        appointment_type="RESEARCH_STAFF",
        home_department="Public Health",
    )
    disclosure = create_disclosure(investigator["id"])
    add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="OUTSIDE_SUPPORT",
        start_date="2025-02-01T00:00:00Z",
        annual_effort_hours=0,
        is_paid=False,
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    begin_review(disclosure["id"])
    returned = return_for_revision(disclosure["id"])

    # The item that predates the return is not late: raw 100 - 6 = 94 stays in tier A.
    assert returned["revision_round"] == 1
    assert returned["late_item_count"] == 0
    assert returned["completeness_score"] == 94
    assert returned["completeness_tier"] == "A"

    owner_headers = make_investigator_headers(investigator["id"])
    for start_date, value_cents in (
        ("2025-03-01T00:00:00Z", 400_000),
        ("2025-04-01T00:00:00Z", 250_000),
    ):
        validate_success(
            api.create_disclosure_item(
                disclosure["id"],
                create_disclosure_item_payload(
                    organization["id"],
                    item_type="IN_KIND_RESOURCE",
                    start_date=start_date,
                    in_kind_value_cents=value_cents,
                    is_paid=False,
                ),
                owner_headers,
            ),
            expected_status=201,
        )
    resubmitted = validate_success(
        api.submit_disclosure(disclosure["id"], owner_headers)
    )

    assert resubmitted["item_count"] == 3
    assert resubmitted["late_item_count"] == 2
    assert resubmitted["undisclosed_item_count"] == 0
    # Raw 100 - 16 - 6 = 78 selects tier B, whose 5-point penalty gives 73.
    assert resubmitted["completeness_score"] == 73
    assert resubmitted["completeness_tier"] == "B"
    assert resubmitted["review_status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert read_disclosure(disclosure["id"])["completeness_score"] == 73


def test_capacity_projection_ignores_a_revoked_grant_on_the_same_window(api):
    """PRD §3.7: "The projection considers the other grants on the same project whose
    `status` is `REQUESTED`, `ACTIVE` or `SUSPENDED` — `REVOKED` grants never occupy
    capacity — and among those, only the ones whose window genuinely overlaps the
    candidate's, meaning the other grant's `valid_from` falls strictly before the
    candidate's `valid_until` and the candidate's `valid_from` falls strictly before
    the other grant's `valid_until`."

    Design: Corner/calculations/area_capacity_projection_ignores_revoked_grants
    """
    set_clock()
    project, investigator, first_grant = setup_active_access_grant(
        controlled_area_capacity=1,
        valid_from="2026-09-01T00:00:00Z",
        valid_until="2026-12-01T00:00:00Z",
        title="Single Badge Facility",
        agency_code="DOE",
        sensitivity_level="CONTROLLED",
        award_amount_cents=45_000_000,
    )
    first_grant = set_grant_status(first_grant["id"], "REVOKED")
    assert first_grant["status"] == "REVOKED"
    assert first_grant["status_reason"] == "OFFICER_ACTION"

    project_now = read_project(project["id"])
    second_grant = validate_success(
        api.create_access_grant(
            create_access_grant_payload(
                project["id"],
                investigator["id"],
                project_now["version"],
                valid_from="2026-09-01T00:00:00Z",
                valid_until="2026-12-01T00:00:00Z",
            ),
            RSO,
        ),
        expected_status=201,
    )
    # The revoked grant occupies nothing, so the sweep still reports a peak of 1.
    assert second_grant["peak_concurrency_at_request"] == 1

    activated = validate_success(
        api.set_access_grant_status(
            second_grant["id"], {"to_status": "ACTIVE"}, RSO
        )
    )
    assert activated["status"] == "ACTIVE"
    assert activated["status_reason"] == "NONE"
    assert read_access_grant(first_grant["id"])["status"] == "REVOKED"

    after = read_project(project["id"])
    assert after["active_grant_count"] == 1
    assert after["controlled_area_posture"] == "RESTRICTED"


def test_device_tier_none_needs_both_no_device_and_zero_flags(api):
    """PRD §3.7: "The `device_requirement_tier` is then read off the flag count in
    this exact order, with the no-device short-circuit evaluated first: if
    `carries_institutional_device` is false **and** the flag count is exactly 0, the
    tier is `NONE`; otherwise if the flag count is 1 or fewer, the tier is
    `STANDARD`; otherwise if the flag count is 3 or fewer, the tier is
    `LOANER_REQUIRED`; otherwise, at 4 flags, the tier is `LOANER_PLUS_ESCORT`."

    Design: Corner/calculations/travel_tier_none_requires_both_zero_flags_and_no_device
    """
    set_clock()
    investigator = create_investigator(
        full_name="Zoe Farrow",
        appointment_type="POSTDOC",
        home_department="Astronomy",
    )
    owner_headers = make_investigator_headers(investigator["id"])

    # CN raises the destination flag, so declining the device cannot reach NONE.
    high_risk_trip = validate_success(
        api.create_travel_registration(
            create_travel_registration_payload(
                investigator["id"],
                destination_country_code="CN",
                depart_on="2026-10-01T00:00:00Z",
                return_on="2026-10-08T00:00:00Z",
                purpose="CONFERENCE",
                carries_institutional_device=False,
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    plain_trip = validate_success(
        api.create_travel_registration(
            create_travel_registration_payload(
                investigator["id"],
                destination_country_code="KR",
                depart_on="2026-11-01T00:00:00Z",
                return_on="2026-11-08T00:00:00Z",
                purpose="CONFERENCE",
                carries_institutional_device=False,
            ),
            owner_headers,
        ),
        expected_status=201,
    )

    assert high_risk_trip["risk_flag_count"] == 1
    assert high_risk_trip["device_requirement_tier"] == "STANDARD"
    assert high_risk_trip["briefing_required"] is False

    assert plain_trip["risk_flag_count"] == 0
    assert plain_trip["device_requirement_tier"] == "NONE"
    assert plain_trip["briefing_required"] is False

    for trip in (high_risk_trip, plain_trip):
        assert trip["status"] == "DRAFT"
        assert trip["device_decision_recorded_at"] is None


def test_unverified_end_user_host_raises_no_device_flag(api):
    """PRD §3.7: "A second is raised if a `host_organization_id` is present and that
    organization's `effective_designation` has a strictness rank of at least 2 — that
    is, `ENTITY_LIST` or anything stricter."

    Design: Corner/calculations/travel_host_strictness_floor_excludes_unverified_end_user
    """
    set_clock()
    investigator = create_investigator(
        full_name="Aaron Guttmann", home_department="Political Science"
    )
    org_unverified = create_organization(
        legal_name="Grey Market Instruments",
        country_code="AE",
        org_type="COMPANY",
        own_designation="UNVERIFIED_END_USER",
        designated_on="2025-02-01T00:00:00Z",
    )
    org_military = create_organization(
        legal_name="Defence Academy Bureau",
        country_code="AE",
        org_type="GOVERNMENT_AGENCY",
        own_designation="FOREIGN_MILITARY",
        designated_on="2025-02-01T00:00:00Z",
    )
    owner_headers = make_investigator_headers(investigator["id"])

    unverified_host_trip = validate_success(
        api.create_travel_registration(
            create_travel_registration_payload(
                investigator["id"],
                destination_country_code="AE",
                depart_on="2026-10-01T00:00:00Z",
                return_on="2026-10-05T00:00:00Z",
                purpose="COLLABORATION",
                host_organization_id=org_unverified["id"],
                carries_institutional_device=True,
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    military_host_trip = validate_success(
        api.create_travel_registration(
            create_travel_registration_payload(
                investigator["id"],
                destination_country_code="AE",
                depart_on="2026-11-01T00:00:00Z",
                return_on="2026-11-05T00:00:00Z",
                purpose="COLLABORATION",
                host_organization_id=org_military["id"],
                carries_institutional_device=True,
            ),
            owner_headers,
        ),
        expected_status=201,
    )

    # Strictness rank 1 sits below the floor; rank 3 clears it.
    assert unverified_host_trip["risk_flag_count"] == 0
    assert unverified_host_trip["device_requirement_tier"] == "STANDARD"
    assert unverified_host_trip["briefing_required"] is False

    assert military_host_trip["risk_flag_count"] == 1
    assert military_host_trip["device_requirement_tier"] == "STANDARD"
    assert military_host_trip["briefing_required"] is False


def test_low_severity_band_earns_a_sixty_day_notification_window(api):
    """PRD §3.8: "The total is stored as `severity_points`, and `severity` is banded
    off it with inclusive floors: below 20 is `LOW`, below 40 is `MODERATE`, below 60
    is `HIGH`, and 60 or above is `CRITICAL`. The floors bite exactly where they are
    written — an `UNREPORTED_TRAVEL` incident on an active, `RESTRICTED` project
    scores 15 plus 15 plus 10 for exactly 40 points and is therefore `HIGH`, while
    one point less would be `MODERATE`. Finally `notification_due_on` is set to
    `substantiated_at` plus the window the band earns: 60 days for `LOW`, 30 for
    `MODERATE`, 10 for `HIGH` and 5 for `CRITICAL`."

    Design: Corner/calculations/incident_low_band_uses_the_sixty_day_notification_window
    """
    set_clock()
    investigator = create_investigator(
        full_name="Bea Halloran", home_department="Anthropology"
    )
    incident = create_incident(
        investigator["id"],
        incident_type="UNREPORTED_TRAVEL",
        discovered_on="2026-07-28T00:00:00Z",
        summary="Undeclared conference trip surfaced in an expense report.",
    )
    investigate_incident(incident["id"], lead_investigator_user_id=RSO_USER_ID)

    substantiated = validate_success(
        api.set_incident_status(
            incident["id"], {"to_status": "SUBSTANTIATED"}, RSO
        )
    )
    # No project link, so neither award surcharge applies and no priors exist.
    assert substantiated["severity_points"] == 15
    assert substantiated["severity"] == "LOW"
    assert substantiated["substantiated_at"].startswith("2026-08-01T00:00:00")
    assert substantiated["notification_due_on"].startswith("2026-09-30T00:00:00")
    assert substantiated["notified_late"] is False
    assert substantiated["finding"] == "SUBSTANTIATED"
    assert substantiated["lead_investigator_user_id"] == RSO_USER_ID

    after = read_investigator(investigator["id"])
    assert after["substantiated_incident_count"] == 1
    assert after["risk_score"] == 5
    assert after["disclosure_posture"] == "RESTRICTED"


def test_effective_designation_keeps_the_strictest_chain_member(api):
    """PRD §2.10: "An organization's `effective_designation` is the strictest
    designation found on the chain of control rooted at that organization, and
    `effective_designation_depth` is the number of ownership hops between the
    organization and the chain member that supplied it."

    Design: Corner/calculations/effective_designation_takes_the_strictest_ancestor_not_the_nearest
    """
    set_clock()
    apex = create_organization(
        legal_name="Sanctioned Apex Group",
        country_code="RU",
        org_type="COMPANY",
        own_designation="SDN",
        designated_on="2024-11-01T00:00:00Z",
    )
    middle = create_organization(
        legal_name="Middle Tier Holdings",
        country_code="RU",
        org_type="COMPANY",
        own_designation="ENTITY_LIST",
        designated_on="2025-01-01T00:00:00Z",
        parent_organization_id=apex["id"],
        parent_ownership_pct=100.00,
    )

    leaf = validate_success(
        api.create_foreign_organization(
            create_foreign_organization_payload(
                legal_name="Leaf Research Unit",
                country_code="RU",
                org_type="INSTITUTE",
                own_designation="NONE",
                parent_organization_id=middle["id"],
                parent_ownership_pct=75.00,
            ),
            RSO,
        ),
        expected_status=201,
    )

    # ENTITY_LIST at hop 1 does not stop the walk: SDN at hop 2 is stricter.
    assert leaf["own_designation"] == "NONE"
    assert leaf["effective_designation"] == "SDN"
    assert leaf["effective_designation_depth"] == 2

    middle_now = read_organization(middle["id"])
    assert middle_now["effective_designation"] == "SDN"
    assert middle_now["effective_designation_depth"] == 1

    apex_now = read_organization(apex["id"])
    assert apex_now["effective_designation"] == "SDN"
    assert apex_now["effective_designation_depth"] == 0


def test_designation_tie_keeps_the_nearer_hop_depth(api):
    """PRD §2.10: "If the parent's `own_designation` is **strictly** stricter than the
    best designation recorded so far, adopt it along with the current hop count as
    the new best; a parent that merely ties the incumbent does not displace it, so
    ties always keep the nearer hop."

    Design: Corner/calculations/designation_tie_keeps_the_nearer_ancestor_depth
    """
    set_clock()
    grandparent = create_organization(
        legal_name="Listed Grandparent Works",
        country_code="CN",
        org_type="COMPANY",
        own_designation="ENTITY_LIST",
        designated_on="2024-09-01T00:00:00Z",
    )
    parent = create_organization(
        legal_name="Listed Parent Works",
        country_code="CN",
        org_type="COMPANY",
        own_designation="ENTITY_LIST",
        designated_on="2024-10-01T00:00:00Z",
        parent_organization_id=grandparent["id"],
        parent_ownership_pct=100.00,
    )

    child = validate_success(
        api.create_foreign_organization(
            create_foreign_organization_payload(
                legal_name="Undesignated Child Works",
                country_code="CN",
                org_type="COMPANY",
                own_designation="NONE",
                parent_organization_id=parent["id"],
                parent_ownership_pct=50.00,
            ),
            RSO,
        ),
        expected_status=201,
    )

    # The grandparent merely ties the parent, so depth stays at the nearer hop.
    assert child["effective_designation"] == "ENTITY_LIST"
    assert child["effective_designation_depth"] == 1

    parent_now = read_organization(parent["id"])
    assert parent_now["effective_designation"] == "ENTITY_LIST"
    assert parent_now["effective_designation_depth"] == 0
