"""Requests that break two rules at once, and the code that must come back.

Each scenario is built so a second, lower-priority rule is genuinely violated too;
a companion test proves that by provoking the lower rule on its own.
"""

from typing import Any, Dict

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_funding_source_conservation,
    assert_member_organization,
    assert_pledge_capacity_identity,
    assert_skill_fit_report,
    assert_version_unchanged,
    create_funding_source,
    decide,
    funding_commitment_payload,
    make_member_org_delegate_headers,
    presentation_version,
    read_funding_source,
    read_member_org,
    read_presentation,
    record_assistance,
    request_disbursement,
    setup_awarded_case,
    setup_deliberating_presentation,
    setup_permitted_project_with_group,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["volunteer_coordinator_headers"]
ADMIN = TEST_USERS["ltrg_admin_headers"]

TWO_ORGS = [
    {"org_name": "Lakeside Presbyterian", "annual_pledge_cap_cents": 5_000_000},
    {"org_name": "Eastgate Rotary", "annual_pledge_cap_cents": 800_000},
]


def _pledge_request(presentation_id: str, member_org_id: str, cents: int, purpose_code: str):
    """Send a pledge as the delegate of `member_org_id` against a freshly read version."""
    payload = funding_commitment_payload(
        presentation_id,
        member_org_id,
        cents,
        presentation_version(presentation_id),
        purpose_code=purpose_code,
    )
    return api_client.create_funding_commitment(
        payload, make_member_org_delegate_headers(member_org_id)
    )


def _setup_two_org_table(award: bool) -> Dict[str, Any]:
    """A 6000000 case before two seated organizations, optionally already awarded.

    The larger organization pledges 2000000; no unrestricted money exists, so the
    award authorizes no bridge and closes the pledge window at 2000000.
    """
    scenario = setup_deliberating_presentation(
        damage=[("STRUCTURE", 6_000_000)],
        orgs=TWO_ORGS,
        quorum_min_member_orgs=2,
    )
    scenario["commitment"] = validate_success(
        _pledge_request(
            scenario["presentation"]["id"],
            scenario["member_orgs"][0]["id"],
            2_000_000,
            "STRUCTURE_REPAIR",
        ),
        201,
    )
    if award:
        scenario["decision"] = decide(scenario["presentation"]["id"], "AWARD", "Partial award")
    scenario["presentation"] = read_presentation(scenario["presentation"]["id"])
    return scenario


def test_a_closed_pledge_window_is_reported_ahead_of_the_pledge_cap(api):
    """PRD §3.4: "The presentation's `status` must be `DELIBERATING`, or
    `ERR_PRESENTATION_NOT_ACCEPTING_PLEDGES` results."

    Design: Difficulty/priority_pair_validation_conflict/presentation_closed_to_pledges_beats_pledge_cap_exceeded
    """
    scenario = _setup_two_org_table(award=True)
    before = scenario["presentation"]
    assert before["status"] == "AWARDED"
    small_org = scenario["member_orgs"][1]

    response = _pledge_request(
        before["id"], small_org["id"], 900_000, "STRUCTURE_REPAIR"
    )

    # 900000 also exceeds this organization's 800000 remaining capacity, and the
    # version read above is already stale, but the closed window is reported.
    validate_error(response, ApiErrorId.ERR_PRESENTATION_NOT_ACCEPTING_PLEDGES.value, 409)
    org = read_member_org(small_org["id"])
    assert_member_organization(org)
    assert org["committed_cents"] == 0
    assert org["remaining_pledge_capacity_cents"] == 800_000
    assert org["status"] == "ACTIVE"
    assert_pledge_capacity_identity(org)
    after = read_presentation(before["id"])
    assert after["status"] == "AWARDED"
    assert after["pledged_total_cents"] == 2_000_000
    assert after["awarded_cents"] == 2_000_000
    assert_version_unchanged(before, after)


def test_the_same_pledge_breaks_the_cap_while_the_window_is_still_open(api):
    """PRD §3.4: "And `pledged_cents` may not exceed the organization's
    `remaining_pledge_capacity_cents`, or `ERR_PLEDGE_CAP_EXCEEDED` results."

    Design: Difficulty/priority_pair_validation_conflict/presentation_closed_to_pledges_beats_pledge_cap_exceeded
    """
    scenario = _setup_two_org_table(award=False)
    assert scenario["presentation"]["status"] == "DELIBERATING"
    small_org = scenario["member_orgs"][1]

    response = _pledge_request(
        scenario["presentation"]["id"], small_org["id"], 900_000, "STRUCTURE_REPAIR"
    )

    validate_error(response, ApiErrorId.ERR_PLEDGE_CAP_EXCEEDED.value, 422)
    org = read_member_org(small_org["id"])
    assert org["committed_cents"] == 0
    assert org["remaining_pledge_capacity_cents"] == 800_000
    assert org["status"] == "ACTIVE"


def _setup_contents_case_with_thin_grant(late_assistance: bool) -> Dict[str, Any]:
    """A cleared 500000 contents payment against a grant holding only 100000.

    The bucket need is 1000000 and 400000 of documented assistance is already on the
    file, so the request clears duplication of benefits at creation. When
    `late_assistance` is set, a further 300000 is documented afterwards, which is
    exactly what the re-run at approval catches.
    """
    scenario = setup_awarded_case(
        damage=[("CONTENTS", 1_000_000)],
        assistance=[
            {
                "source_type": "INSURANCE_SETTLEMENT",
                "purpose_code": "CONTENTS_REPLACEMENT",
                "awarded_cents": 400_000,
                "received_on": "2026-07-10",
                "documentation_status": "DOCUMENTED",
            }
        ],
        orgs=[{"org_name": "Southgate Community Chest", "annual_pledge_cap_cents": 1_000_000}],
        pledges=[(0, 600_000, "CONTENTS_REPLACEMENT")],
    )
    scenario["source"] = create_funding_source(
        label="Contents grant remainder",
        source_type="FOUNDATION_GRANT",
        restriction_code="CONTENTS_ONLY",
        total_cents=100_000,
        admin_retention_allowed=False,
    )
    scenario["requested"] = request_disbursement(
        scenario["case"]["id"],
        "CONTENTS_REPLACEMENT",
        500_000,
        payee_name="Valley Furniture Co",
        commitment_id=scenario["commitments"][0]["id"],
    )
    if late_assistance:
        record_assistance(
            scenario["case"]["id"],
            source_type="STATE_PROGRAM",
            purpose_code="CONTENTS_REPLACEMENT",
            awarded_cents=300_000,
            received_on="2026-08-20",
            documentation_status="DOCUMENTED",
        )
    return scenario


def test_the_duplication_re_run_is_reported_ahead_of_the_funding_shortfall(api):
    """PRD §3.6: "The duplication-of-benefits check is re-run from scratch and must
    still yield exposure of 0, or `ERR_DUPLICATION_OF_BENEFITS` results — a record
    documented since the request was created can flag a row that cleared earlier."

    Design: Difficulty/priority_pair_validation_conflict/duplication_of_benefits_beats_insufficient_restricted_funds
    """
    scenario = _setup_contents_case_with_thin_grant(late_assistance=True)
    assert scenario["requested"]["status"] == "DOB_CLEARED"

    response = api.approve_disbursement(
        scenario["requested"]["id"], {"approval_note": "Approve contents payment"}, ADMIN
    )

    # The 100000 grant also cannot cover 500000 of net, but exposure is checked first.
    validate_error(response, ApiErrorId.ERR_DUPLICATION_OF_BENEFITS.value, 422)


def test_nothing_is_written_when_the_duplication_re_run_refuses_the_approval(api):
    """PRD §3.6: "The flagged branch's distinguishing property is what it does *not*
    do: no funding source field is touched, the case's `total_committed_cents` is
    unchanged, and the request cannot be approved until the finding is resolved or the
    request is voided."

    Design: Difficulty/priority_pair_validation_conflict/duplication_of_benefits_beats_insufficient_restricted_funds
    """
    scenario = _setup_contents_case_with_thin_grant(late_assistance=True)

    validate_error(
        api.approve_disbursement(
            scenario["requested"]["id"], {"approval_note": "Approve contents payment"}, ADMIN
        ),
        ApiErrorId.ERR_DUPLICATION_OF_BENEFITS.value,
        422,
    )

    row = validate_success(
        api.get_disbursement(
            scenario["requested"]["id"], TEST_USERS["disbursement_officer_headers"]
        )
    )
    assert row["status"] == "DOB_CLEARED"
    assert row["allocation_lines"] == []
    source = read_funding_source(scenario["source"]["id"])
    assert source["committed_cents"] == 0
    assert source["available_cents"] == 100_000
    assert source["status"] == "OPEN"
    assert_funding_source_conservation(source)


def test_the_thin_grant_alone_cannot_cover_the_request(api):
    """PRD §3.6: "If any remaining net is left once the ordered pool is exhausted, the
    approval fails with `ERR_INSUFFICIENT_RESTRICTED_FUNDS` and nothing is written."

    Design: Difficulty/priority_pair_validation_conflict/duplication_of_benefits_beats_insufficient_restricted_funds
    """
    scenario = _setup_contents_case_with_thin_grant(late_assistance=False)

    response = api.approve_disbursement(
        scenario["requested"]["id"], {"approval_note": "Approve contents payment"}, ADMIN
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_RESTRICTED_FUNDS.value, 422)
    source = read_funding_source(scenario["source"]["id"])
    assert source["committed_cents"] == 0
    assert source["available_cents"] == 100_000


def _setup_undersized_crew_for_a_weighted_phase() -> Dict[str, Any]:
    """A permitted phase needing 1350 weighted hours and a crew of only four."""
    scenario = setup_permitted_project_with_group(
        project_overrides={
            "required_trade_hours": {"FRAMING": 300, "ROOFING": 150, "GENERAL_LABOR": 300},
            "estimated_material_cents": 900_000,
            "critical_trades": ["FRAMING"],
        },
        group_overrides={
            "group_name": "Maple Street Small Team",
            "home_organization": "Maple Street Church",
            "member_count": 4,
            "skill_profile": {"FRAMING": 1, "ROOFING": 1, "GENERAL_LABOR": 4},
            "requires_housing": False,
        },
        permit_number="PB-3314",
    )
    return scenario


def test_date_ordering_is_reported_ahead_of_the_skill_fit_floor(api):
    """PRD §3.8: "First, the dates must be sane: `departure_date` must fall on or after
    `arrival_date`, and `arrival_date` must fall on or after the logical clock's current
    date; a violation is refused with `ERR_INVALID_DATE_RANGE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_date_range_beats_skill_fit_below_minimum
    """
    scenario = _setup_undersized_crew_for_a_weighted_phase()

    response = api.create_volunteer_deployment(
        {
            "group_id": scenario["group"]["id"],
            "project_id": scenario["project"]["id"],
            "arrival_date": "2026-09-20",
            "departure_date": "2026-09-16",
        },
        COORDINATOR,
    )

    # The crew would also fail the 6000 basis-point floor for this window.
    validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)
    bookings, meta = validate_paginated(
        api.list_volunteer_deployments(COORDINATOR, params={"group_id": scenario["group"]["id"]})
    )
    assert meta["total_count"] == 0
    assert bookings == []


def test_the_reordered_window_really_does_fall_below_the_skill_fit_floor(api):
    """PRD §3.8: "The server computes `skill_fit_score_bps` in the `COVERAGE_WEIGHTED`
    variant and stores it on the deployment, and refuses the booking with
    `ERR_SKILL_FIT_BELOW_MINIMUM` when the score is below 6000 basis points."

    Design: Difficulty/priority_pair_validation_conflict/invalid_date_range_beats_skill_fit_below_minimum
    """
    scenario = _setup_undersized_crew_for_a_weighted_phase()

    probe = validate_success(
        api.get_skill_fit(
            scenario["project"]["id"],
            COORDINATOR,
            params={
                "group_id": scenario["group"]["id"],
                "variant": "COVERAGE_WEIGHTED",
                "arrival_date": "2026-09-16",
                "departure_date": "2026-09-20",
            },
        )
    )
    assert_skill_fit_report(probe)
    # 3*30 + 30 + 120 covered against a weighted requirement of 1350.
    assert probe["weighted_covered"] == 240
    assert probe["weighted_required"] == 1350
    assert probe["score_bps"] == 1778
    assert probe["meets_minimum"] is False

    response = api.create_volunteer_deployment(
        {
            "group_id": scenario["group"]["id"],
            "project_id": scenario["project"]["id"],
            "arrival_date": "2026-09-16",
            "departure_date": "2026-09-20",
        },
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_SKILL_FIT_BELOW_MINIMUM.value, 422)
