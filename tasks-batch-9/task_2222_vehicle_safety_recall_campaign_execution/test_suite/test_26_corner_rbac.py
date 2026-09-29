"""
Access control: the operations desk's exclusive fleet and parts actions, a role
refused a remedy release it has a valid body for, the missing identity header, the
dealer acting for a sibling dealership, and the self-filed defect notice.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    CampaignStatus,
    ClaimStatus,
    RegionCode,
    RemedyStatus,
    Role,
    factories as f,
    fixtures as fx,
    make_dealer_service_manager_headers,
    make_headers,
    read_list,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    CLAIMS_AUDITOR,
    COMPLIANCE_OFFICER_1,
    OPERATIONS_MANAGER,
    SAFETY_ENGINEER_1,
    SAFETY_ENGINEER_1_ID,
    headers_without_user_id,
)

TWO_NE_BUILDS = [
    {
        "vin": "1HGCM82633A004352",
        "production_date": "2024-03-15",
        "suspect_part_number": 1500,
        "owner_name": "Ann Vega",
    },
    {
        "vin": "1HGCM82633A004353",
        "production_date": "2024-03-16",
        "suspect_part_number": 1501,
        "owner_name": "Ben Ito",
    },
]


def test_operations_manager_owns_fleet_ingest_dealer_enrollment_and_allocation(api):
    """
    Ingesting a build record, enrolling a dealer and allocating kits are all accepted
    from the operations desk; the very same allocation body, sent by the engineer who
    registered the remedy part, is refused on authorization — so defining a remedy and
    distributing it are separate capabilities.

    PRD §2.1: "A request whose role is recognised but is not listed as authorised for
    the targeted operation in §4 is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD §2.7: "1. **Authentication**, then **authorization** — `ERR_UNAUTHENTICATED`,
    then `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/recall_operations_manager_performs_its_exclusive_fleet_and_parts_operations
    """
    state = fx.filed_campaign(
        api,
        campaign={"campaign_number": "26V-337"},
        vehicles=TWO_NE_BUILDS,
    )
    campaign_id = state["campaign_id"]
    part = fx.add_remedy_part(
        api, campaign_id, part_number="P-88337", total_procured_qty=100
    )

    validate_success(
        api.create_vehicle(
            f.vehicle_payload(
                vin="1HGCM82633A004354",
                production_date="2024-03-17",
                suspect_part_number=1502,
                owner_name="Cara Lu",
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    dealer = validate_success(
        api.create_dealer(
            f.dealer_payload(
                dealer_code="D-NE-01",
                name="Vega Motors",
                region_code=RegionCode.NE,
                labor_rate_per_hour=138.74,
                monthly_repair_capacity=40,
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    allocation = validate_success(
        api.create_parts_allocation(
            f.parts_allocation_payload(
                part["id"], dealer["id"], part["version"], requested_qty=2
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert allocation["allocated_qty"] == 2
    assert allocation["status"] == AllocationStatus.ALLOCATED

    refused = api.create_parts_allocation(
        f.parts_allocation_payload(
            part["id"], dealer["id"], part["version"], requested_qty=1
        ),
        SAFETY_ENGINEER_1,
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED, 403)

    read_list(
        api.list_parts_allocations(OPERATIONS_MANAGER, {"campaign_id": campaign_id}),
        expected_total=1,
    )


def test_claims_auditor_cannot_release_a_remedy(api):
    """
    The auditor supplies a real labor operation and the campaign version token read
    moments earlier, so the body would pass every later check; authorization runs first
    and the remedy dimension never moves.

    PRD §2.1: "A request whose role is recognised but is not listed as authorised for
    the targeted operation in §4 is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD §2.7: "1. **Authentication**, then **authorization** — `ERR_UNAUTHENTICATED`,
    then `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/claims_auditor_cannot_release_a_remedy
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-338"})
    campaign_id = state["campaign_id"]
    labor_operation = fx.add_labor_operation(
        api,
        campaign_id,
        labor_op_code="R338-01",
        flat_hours=1.10,
        effective_from="2026-08-01",
        effective_to="2027-12-31",
    )
    version_before = fx.campaign_version(api, campaign_id, CLAIMS_AUDITOR)

    response = api.release_remedy(
        campaign_id,
        f.remedy_release_payload(
            labor_operation["id"],
            version_before,
            remedy_description="Auditor attempting to ship a remedy",
        ),
        CLAIMS_AUDITOR,
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED, 403)

    campaign = fx.read_campaign(api, campaign_id)
    assert campaign["remedy_status"] == RemedyStatus.REMEDY_UNDER_DEVELOPMENT
    assert campaign["remedy_released_at"] is None
    assert campaign["version"] == version_before


def test_campaign_creation_without_the_user_id_header_is_rejected(api):
    """
    The role header alone is not enough: a request declaring an authorised role but
    omitting its identity fails on authentication, ahead of the authorization check
    that would otherwise have let that very role through, and nothing is written.

    PRD §2.1: "A request missing either header, or presenting an `X-User-Role` that is
    not one of the five recognised role names, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    PRD §2.7: "1. **Authentication**, then **authorization** — `ERR_UNAUTHENTICATED`,
    then `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/campaign_creation_without_the_user_id_header_is_rejected
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    response = api.create_campaign(
        f.campaign_payload(campaign_number="26V-339", risk_severity=None),
        headers_without_user_id(Role.SAFETY_ENGINEER),
    )
    validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)

    read_list(api.list_campaigns(SAFETY_ENGINEER_1), expected_total=0)


def test_dealer_service_manager_cannot_claim_on_behalf_of_another_dealer(api):
    """
    The caller holds the right role but the wrong identity: the body names the
    dealership that actually holds the kit while the identity header names its
    neighbour, and the scope check refuses it — the identical body sent under the
    holding dealer's own identity is accepted.

    PRD §2.1: "Concretely, a `DealerServiceManager` submitting a repair claim or
    booking an appointment must supply a `dealer_id` equal to its own `X-User-ID`, and
    when the affected-vehicle row is already scheduled, the row's existing `dealer_id`
    must also equal `X-User-ID`; a mismatch is rejected with
    `ERR_DEALER_SCOPE_VIOLATION` (HTTP 403)."

    PRD §2.7: "6. **Dealer scoping**, then **segregation of duties** —
    `ERR_DEALER_SCOPE_VIOLATION`, then `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/dealer_service_manager_cannot_claim_on_behalf_of_another_dealer
    """
    state = fx.campaign_with_remedy(
        api,
        campaign={"campaign_number": "26V-340"},
        labor_operation={"labor_op_code": "R340-01"},
        remedy_part={"part_number": "P-88340", "total_procured_qty": 100},
    )
    campaign_id = state["campaign_id"]
    holder_of_nothing = fx.create_dealer(api)
    holder_of_the_kit = fx.create_dealer(
        api, dealer_code="D-NE-02", name="Harbor Motors", labor_rate_per_hour=141.00
    )
    fx.allocate_parts(
        api,
        campaign_id,
        state["part_number"],
        state["remedy_part_id"],
        holder_of_the_kit["id"],
        requested_qty=1,
    )
    row = fx.find_affected_vehicle(api, campaign_id, state["vehicle_id"])

    claim_body = f.repair_claim_payload(
        row["id"],
        holder_of_the_kit["id"],
        state["labor_operation_id"],
        repair_date="2026-08-03",
        claimed_labor_hours=1.10,
        parts_used_qty=1,
    )
    response = api.create_repair_claim(
        claim_body, make_dealer_service_manager_headers(holder_of_nothing["id"])
    )
    validate_error(response, ApiErrorId.DEALER_SCOPE_VIOLATION, 403)

    read_list(
        api.list_repair_claims(CLAIMS_AUDITOR, {"campaign_id": campaign_id}),
        expected_total=0,
    )

    accepted = validate_success(
        api.create_repair_claim(
            claim_body, make_dealer_service_manager_headers(holder_of_the_kit["id"])
        ),
        201,
    )
    assert accepted["dealer_id"] == holder_of_the_kit["id"]
    assert accepted["status"] == ClaimStatus.SUBMITTED


def test_defect_notice_filed_by_the_determining_user_is_rejected(api):
    """
    The filer carries the compliance role, so authorization passes; what fails is the
    identity comparison against the operator who determined the defect. A different
    compliance officer then files the same report successfully and on time.

    PRD §2.6: "Filing the Part 573 defect notice requires an `X-User-ID` different from
    the campaign's `determined_by_user_id`."

    PRD §3.3: "It is refused from any other `campaign_status` with
    `ERR_INVALID_CAMPAIGN_STATE`, refused with `ERR_SEGREGATION_OF_DUTIES` when the
    caller's `X-User-ID` equals the campaign's `determined_by_user_id`, and refused
    with `ERR_FILING_PERIOD_DUPLICATE` when a defect notice already exists for the
    campaign."

    Design: Corner/rbac/defect_notice_filed_by_the_determining_user_is_rejected
    """
    state = fx.determined_campaign(api, campaign_number="26V-341")
    campaign_id = state["campaign_id"]
    assert state["campaign"]["determined_by_user_id"] == SAFETY_ENGINEER_1_ID

    response = api.create_filing(
        campaign_id,
        f.defect_notice_payload(narrative="Self-filed defect information report"),
        make_headers(SAFETY_ENGINEER_1_ID, Role.COMPLIANCE_OFFICER),
    )
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

    refused_state = fx.read_campaign(api, campaign_id)
    assert refused_state["campaign_status"] == CampaignStatus.DEFECT_DETERMINED
    assert refused_state["filed_at"] is None
    assert refused_state["days_late"] == 0

    validate_success(
        api.create_filing(
            campaign_id,
            f.defect_notice_payload(
                narrative="Part 573 defect information report for 26V-341"
            ),
            COMPLIANCE_OFFICER_1,
        ),
        201,
    )

    filed = fx.read_campaign(api, campaign_id)
    assert filed["campaign_status"] == CampaignStatus.FILED
    assert filed["late_filing_flag"] is False
    assert filed["days_late"] == 0
