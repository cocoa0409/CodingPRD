"""Role authorization tests.

The §4 table is the licence: each write endpoint names the roles that may call
it, `GET` endpoints are open to all four roles, the `PropertyOwner` is scoped to
its own parcel, and the appeal decision additionally enforces segregation of
duties against the determining administrator.
"""
import pytest

from test_helpers import (
    ADMINISTRATOR,
    APPEALS_BOARD,
    COORDINATOR,
    ApiErrorId,
    add_property,
    draft_standard,
    file_certificate_payload,
    file_panel,
    improvement_record_payload,
    make_appeals_board_headers,
    make_property_owner_headers,
    parse_instant,
    read_community,
    read_permit,
    read_standard,
    read_structure,
    register_community,
    setup_appealed_case,
    setup_issued_permit,
    setup_ledger,
    setup_permit_under_review,
    setup_structure,
    start_permit,
    submit_standard,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Roles the §4 table does not license for the write
# --------------------------------------------------------------------------

def test_appeals_board_member_cannot_open_a_determination_case(api):
    """PRD §2.1: "If the headers are well formed but the named role is not
    authorized for the endpoint being called, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §4: "| `POST` | `/floodplain/determination-cases` | Open a substantial
    improvement or substantial damage determination case; supersedes any prior
    open or determined case for the structure | `FloodplainAdministrator` |"

    Design: Corner/RBAC/roles/appeals_board_member_cannot_open_a_determination_case_unauthorized
    """
    scenario = setup_ledger(
        [{"record_type": "IMPROVEMENT", "event_date": "2026-06-01T00:00:00Z",
          "cost_usd": 105_000.00}],
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    structure_id = scenario["structure"]["id"]
    structure_version = read_structure(structure_id)["version"]
    cases_before, meta_before = validate_paginated(
        api.list_determination_cases(ADMINISTRATOR, params={"structure_id": structure_id})
    )

    response = api.open_determination_case(
        {
            "structure_id": structure_id,
            "method": "CUMULATIVE",
            "expected_structure_version": structure_version,
        },
        APPEALS_BOARD,
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    cases_after, meta_after = validate_paginated(
        api.list_determination_cases(ADMINISTRATOR, params={"structure_id": structure_id})
    )
    assert meta_after["total_count"] == meta_before["total_count"]
    assert [case["id"] for case in cases_after] == [case["id"] for case in cases_before]
    structure = read_structure(structure_id)
    assert structure["version"] == structure_version
    assert structure["substantial_status"] == "NONE"


def test_administrator_cannot_activate_a_firm_panel(api):
    """PRD §2.1: "If the headers are well formed but the named role is not
    authorized for the endpoint being called, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §4: "| `POST` | `/floodplain/firm-panels/{panelId}/activate` | Make a
    filed panel the governing map; runs the map-revision cascade |
    `StateNfipCoordinator` |"

    Design: Corner/RBAC/roles/administrator_cannot_activate_a_firm_panel_unauthorized
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    panel = file_panel(
        community["id"], panel_number="48001C0100", suffix="H", flood_zone="AE",
        base_flood_elevation_ft=12.0, effective_date="2020-01-01T00:00:00Z",
    )

    response = api.activate_firm_panel(panel["id"], ADMINISTRATOR)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    unchanged = validate_success(api.get_firm_panel(panel["id"], COORDINATOR), 200)
    assert unchanged["status"] == "PENDING_REVISION"
    assert unchanged["activated_at"] is None
    assert unchanged["version"] == 1


def test_coordinator_cannot_review_a_permit(api):
    """PRD §2.1: "If the headers are well formed but the named role is not
    authorized for the endpoint being called, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §4: "| `POST` | `/floodplain/permits/{permitId}/review` | Record the
    floodplain administrator's review decision | `FloodplainAdministrator` |"

    Design: Corner/RBAC/roles/coordinator_cannot_review_a_permit_unauthorized
    """
    scenario = setup_permit_under_review(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
    )
    permit_id = scenario["permit"]["id"]

    response = api.review_permit(permit_id, {"decision": "APPROVE"}, COORDINATOR)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    unchanged = read_permit(permit_id)
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["revision_round"] == 0
    assert unchanged["issued_at"] is None


def test_property_owner_cannot_file_an_improvement_record(api):
    """PRD §2.1: "If the headers are well formed but the named role is not
    authorized for the endpoint being called, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §4: "| `POST` | `/floodplain/improvement-records` | Append an improvement
    or damage record, or a reversal of one, to a structure's cumulative ledger |
    `FloodplainAdministrator` |"

    Design: Corner/RBAC/roles/property_owner_cannot_file_an_improvement_record_unauthorized
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    structure_id = scenario["structure"]["id"]

    response = api.append_improvement_record(
        improvement_record_payload(
            structure_id, record_type="IMPROVEMENT",
            event_date="2026-06-01T00:00:00Z", cost_usd=40_000.00,
        ),
        scenario["owner_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    rows, meta = validate_paginated(
        api.list_improvement_records(ADMINISTRATOR, params={"structure_id": structure_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    structure = read_structure(structure_id)
    assert structure["anchor_record_id"] is None
    assert float(structure["cumulative_counted_cost_usd"]) == pytest.approx(0.00, abs=0.01)
    assert float(structure["cumulative_improvement_pct"]) == pytest.approx(0.00, abs=0.01)


# --------------------------------------------------------------------------
# PropertyOwner scoping
# --------------------------------------------------------------------------

def test_other_parcels_owner_cannot_file_a_certificate(api):
    """PRD §2.1: "Concretely, a permit is owned by the owner whose identifier
    equals the permit's `property_id`; an elevation certificate is owned by the
    owner whose identifier equals the `property_id` of the permit the certificate
    was filed against; a determination case is owned by the owner whose
    identifier equals the `property_id` of the case's structure."

    PRD §2.1: "When a `PropertyOwner` acts on a resource that does not belong to
    it, the rejection is `ERR_NOT_PROPERTY_OWNER` (HTTP 403)."

    Design: Corner/RBAC/roles/other_parcels_owner_cannot_file_a_certificate_unauthorized
    """
    scenario = setup_issued_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
    )
    permit_id = scenario["permit"]["id"]
    other_property = add_property(
        scenario["community"]["id"], scenario["panel"]["id"], owner_name="Second Owner"
    )
    other_owner_headers = make_property_owner_headers(other_property["id"])

    response = api.file_certificate(
        file_certificate_payload(
            permit_id, scenario["structure"]["id"],
            certificate_type="FINISHED_CONSTRUCTION", datum="NAVD88",
            measured_lowest_floor_ft=20.0, measured_bfe_ft=12.0,
            surveyor_license_no="TX-12345",
        ),
        other_owner_headers,
    )

    validate_error(response, ApiErrorId.ERR_NOT_PROPERTY_OWNER)

    rows, meta = validate_paginated(
        api.list_certificates(ADMINISTRATOR, params={"permit_id": permit_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_structure(scenario["structure"]["id"])["lowest_floor_elevation_ft"] is None
    assert read_permit(permit_id)["status"] == "ISSUED"


# --------------------------------------------------------------------------
# Segregation of duties
# --------------------------------------------------------------------------

def test_the_determining_administrator_cannot_decide_the_appeal(api):
    """PRD §3.7: "Segregation of duties is absolute: the deciding identifier must
    differ from the `determined_by_user_id` recorded on the case, and a
    self-decision is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    PRD §3.7: "`SUSTAIN` moves the case to the terminal `APPEAL_SUSTAINED`,
    records `appeal_decided_by_user_id`, flips `outcome` to `NOT_SUBSTANTIAL`,
    reverts the structure's `substantial_status` to `NONE`, and recomputes
    `required_lowest_floor_elevation_ft` for every permit of that structure whose
    `status` is `UNDER_REVIEW`, `REVISION_REQUIRED`, or `APPROVED` — it fully
    compensates the determination."

    Design: Corner/RBAC/roles/the_determining_administrator_cannot_decide_the_appeal_unauthorized
    """
    scenario = setup_appealed_case(
        records=[{"record_type": "IMPROVEMENT", "event_date": "2026-06-01T00:00:00Z",
                  "cost_usd": 105_000.00}],
        method="CUMULATIVE",
        determiner_headers=ADMINISTRATOR,
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    case_id = scenario["case"]["id"]
    structure_id = scenario["structure"]["id"]

    response = api.decide_appeal(
        case_id, {"decision": "SUSTAIN"}, make_appeals_board_headers("fpa-01")
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    unchanged = validate_success(api.get_determination_case(case_id, ADMINISTRATOR), 200)
    assert unchanged["status"] == "APPEALED"
    assert unchanged["determined_by_user_id"] == "fpa-01"
    assert unchanged["appeal_decided_by_user_id"] is None
    assert unchanged["outcome"] == "SUBSTANTIAL"
    assert read_structure(structure_id)["substantial_status"] == "SUBSTANTIAL_IMPROVEMENT"

    decided = validate_success(
        api.decide_appeal(
            case_id, {"decision": "SUSTAIN"}, make_appeals_board_headers("abm-02")
        ),
        200,
    )
    assert decided["status"] == "APPEAL_SUSTAINED"
    assert decided["appeal_decided_by_user_id"] == "abm-02"
    assert decided["outcome"] == "NOT_SUBSTANTIAL"
    assert read_structure(structure_id)["substantial_status"] == "NONE"


# --------------------------------------------------------------------------
# Shared authority
# --------------------------------------------------------------------------

def test_all_four_roles_share_the_permit_read(api):
    """PRD §2.1: "Every endpoint listed in §4 is readable by all four roles when
    it is a `GET`; write authority is narrower and is stated per endpoint in that
    table."

    PRD §4: "| `GET` | `/floodplain/permits/{permitId}` | Read a permit |
    `StateNfipCoordinator`, `FloodplainAdministrator`, `AppealsBoardMember`,
    `PropertyOwner` |"

    Design: Corner/RBAC/roles/all_four_roles_share_the_permit_read
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
    )
    permit = start_permit(
        scenario["property"]["id"], scenario["structure"]["id"], scenario["owner_headers"],
        project_type="NEW_CONSTRUCTION", declared_project_cost_usd=20_000.00,
        proposed_lowest_floor_elevation_ft=20.0,
    )
    other_property = add_property(
        scenario["community"]["id"], scenario["panel"]["id"], owner_name="Second Owner"
    )
    reader_headers = [
        COORDINATOR,
        ADMINISTRATOR,
        APPEALS_BOARD,
        make_property_owner_headers(other_property["id"]),
    ]

    for headers in reader_headers:
        data = validate_success(api.get_permit(permit["id"], headers), 200)
        assert data["id"] == permit["id"]
        assert data["status"] == "DRAFT"
        assert data["revision_round"] == 0
        assert data["version"] == 1


def test_both_write_roles_share_the_clock_endpoint(api):
    """PRD §2.5: "A test-driving capability lets a `StateNfipCoordinator` or a
    `FloodplainAdministrator` move the clock forward by supplying the target
    instant as `to_iso8601`; the response reports the new `current_utc` and the
    `previous_utc` it replaced."

    PRD §4: "| `POST` | `/floodplain/_clock/set_current_utc` | Set the server's
    logical UTC clock to a supplied instant at or after the current one |
    `StateNfipCoordinator`, `FloodplainAdministrator` |"

    Design: Corner/RBAC/roles/both_write_roles_share_the_clock_endpoint
    """
    validate_success(api.set_clock("2026-09-01T00:00:00Z", COORDINATOR), 200)

    administrator_clock = validate_success(
        api.set_clock("2026-10-01T00:00:00Z", ADMINISTRATOR), 200
    )
    assert parse_instant(administrator_clock["previous_utc"]) == parse_instant(
        "2026-09-01T00:00:00Z"
    )
    assert parse_instant(administrator_clock["current_utc"]) == parse_instant(
        "2026-10-01T00:00:00Z"
    )

    validate_error(
        api.set_clock("2026-11-01T00:00:00Z", APPEALS_BOARD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )

    re_read = validate_success(api.set_clock("2026-10-01T00:00:00Z", ADMINISTRATOR), 200)
    assert parse_instant(re_read["previous_utc"]) == parse_instant("2026-10-01T00:00:00Z")


def test_coordinator_verifies_what_the_administrator_submits(api):
    """PRD §3.9: "Verification belongs to the `StateNfipCoordinator`, never to the
    administrator who submitted, and carries a `decision` of `VERIFY` or `REJECT`
    with an optional `rejection_reason`; it is admitted only from `SUBMITTED`,
    else `ERR_STANDARD_NOT_SUBMITTED`."

    PRD §4: "| `POST` | `/floodplain/higher-standards/{standardId}/verify` | State
    coordinator verifies or rejects the documentation | `StateNfipCoordinator` |"

    Design: Corner/RBAC/roles/coordinator_verifies_what_the_administrator_submits
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    standard = draft_standard(
        community["id"], activity_code="A430_FREEBOARD",
        documentation_cycle_year=2026, claimed_points=100,
    )
    submit_standard(standard["id"])

    validate_error(
        api.verify_higher_standard(standard["id"], {"decision": "VERIFY"}, ADMINISTRATOR),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    assert read_standard(standard["id"])["documentation_status"] == "SUBMITTED"

    verified = validate_success(
        api.verify_higher_standard(standard["id"], {"decision": "VERIFY"}, COORDINATOR), 200
    )
    assert verified["documentation_status"] == "VERIFIED"
    assert verified["verified_points"] == 100
    assert read_community(community["id"])["crs_credit_points_verified"] == 100
