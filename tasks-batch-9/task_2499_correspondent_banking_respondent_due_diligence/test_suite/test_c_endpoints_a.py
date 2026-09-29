"""Corner queue - section endpoints, part A: reference CRUD, patching and paging."""
from test_helpers import (
    assert_instant_equals,
    licensed_respondent,
    new_jurisdiction,
    new_respondent,
    set_clock,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, OFFICER, RM
from test_helpers.test_users import RM_ID_2


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_jurisdiction_profile_create_read_patch_round_trip(api):
    """The reference entity has no state machine, so the whole contract is the round trip: the
    declared defaults, the echo, and a partial update that leaves the untouched fields alone.

    Design: Corner/endpoints/jurisdiction_profile_create_read_patch_round_trip
    """
    created = validate_success(
        api.create_jurisdiction_profile(
            {"jurisdiction_code": "DE", "name": "Germany", "basel_aml_index": 4.0,
             "corridor_risk_weight": 1.0},
            ADMIN,
        ),
        expected_status=201,
    )

    read = validate_success(api.get_jurisdiction_profile(created["id"], ANALYST))
    assert read["jurisdiction_code"] == "DE"
    assert read["name"] == "Germany"
    assert read["basel_aml_index"] == 4.00
    assert read["corridor_risk_weight"] == 1.00
    assert read["sanctions_status"] == "PERMITTED"
    assert read["fatf_listing"] == "NONE"
    assert read["secrecy_flag"] is False
    assert read["nested_correspondent_prohibited"] is False
    assert read["max_permitted_risk_rating"] == "HIGH"

    patched = validate_success(
        api.amend_jurisdiction_profile(
            created["id"], {"sanctions_status": "RESTRICTED"}, OFFICER
        )
    )
    assert patched["sanctions_status"] == "RESTRICTED"
    assert patched["basel_aml_index"] == 4.00
    assert patched["corridor_risk_weight"] == 1.00
    assert patched["version"] == read["version"] + 1


def test_respondent_patch_updates_only_the_supplied_fields(api):
    """The two commercial fields in the body move while every due-diligence dimension holds
    still, and the row's version and update stamp both advance exactly once.

    Design: Corner/endpoints/respondent_patch_updates_only_the_supplied_fields
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    version_before = respondent["version"]
    set_clock("2026-08-05T00:00:00Z")

    patched = validate_success(
        api.amend_respondent(
            respondent["id"],
            {"legal_name": "Nordbank Aktiengesellschaft",
             "relationship_manager_user_id": RM_ID_2},
            RM,
        )
    )

    assert patched["legal_name"] == "Nordbank Aktiengesellschaft"
    assert patched["relationship_manager_user_id"] == RM_ID_2
    assert patched["expected_monthly_volume_usd"] == 500000.00
    assert patched["expected_monthly_count"] == 100
    assert patched["dd_state"] == "DD_IN_PROGRESS"
    assert patched["payment_posture"] == "BLOCKED"
    assert patched["license_status"] == "ACTIVE"
    assert patched["version"] == version_before + 1
    assert_instant_equals(patched["updated_at"], "2026-08-05T00:00:00Z")


def _five_respondents():
    _de()
    return [
        new_respondent(
            "DE", legal_name=f"Bank {n}", swift_bic=f"BANK{n}DEF",
            expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        )
        for n in range(1, 6)
    ]


def test_respondent_list_pagination_walks_created_at_ascending(api):
    """Paging through the default creation order proves the window moves while the total stays
    put, and an offset past the end is an empty page rather than an error.

    Design: Corner/endpoints/respondent_list_pagination_walks_created_at_ascending
    """
    created = _five_respondents()

    rows, meta = validate_paginated(
        api.list_respondents(ANALYST, params={"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in rows] == [created[2]["id"], created[3]["id"]]
    assert meta["total_count"] == 5
    assert meta["has_more"] is True
    assert meta["api_request_id"]
    assert meta["api_request_timestamp"]

    last_rows, last_meta = validate_paginated(
        api.list_respondents(ANALYST, params={"limit": 2, "offset": 4})
    )
    assert [row["id"] for row in last_rows] == [created[4]["id"]]
    assert last_meta["total_count"] == 5
    assert last_meta["has_more"] is False

    empty_rows, empty_meta = validate_paginated(
        api.list_respondents(ANALYST, params={"limit": 2, "offset": 99})
    )
    assert empty_rows == []
    assert empty_meta["total_count"] == 5
    assert empty_meta["has_more"] is False


def test_respondent_list_filters_combine_conjunctively(api):
    """Two filters that each match a different superset must intersect rather than union, and
    the reported total has to describe the filtered set.

    Design: Corner/endpoints/respondent_list_filters_combine_conjunctively
    """
    _de()
    new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    active_de = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    prospect_de = new_respondent(
        "DE", legal_name="Sudbank AG", swift_bic="SUEDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    licensed_respondent(
        "FR", legal_name="Banque de Paris", swift_bic="BDPAFRPP",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )

    rows, meta = validate_paginated(
        api.list_respondents(
            ANALYST, params={"dd_state": "DD_IN_PROGRESS", "home_jurisdiction_code": "DE"}
        )
    )
    assert [row["id"] for row in rows] == [active_de["id"]]
    assert meta["total_count"] == 1
    assert prospect_de["id"] not in [row["id"] for row in rows]

    _blocked, blocked_meta = validate_paginated(
        api.list_respondents(ANALYST, params={"payment_posture": "BLOCKED"})
    )
    assert blocked_meta["total_count"] == 3
