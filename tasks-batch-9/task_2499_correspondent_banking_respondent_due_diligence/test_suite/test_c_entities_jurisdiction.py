"""Corner queue - section entities, JurisdictionProfile and RespondentBank surface."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    is_iso8601_timestamp,
    is_valid_uuid,
    new_jurisdiction,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, COMMITTEE, OFFICER, RM


def test_create_jurisdiction_profile_returns_201_with_computed_risk_points(api):
    """A jurisdiction with a clean sanctions, FATF and secrecy posture scores on the Basel
    term alone, so 4.00 * 2.0 is the whole of `jurisdiction_risk_points`.

    Design: Corner/entities/create_jurisdiction_profile_returns_201_with_computed_risk_points
    """
    created = validate_success(
        api.create_jurisdiction_profile(
            {
                "jurisdiction_code": "DE",
                "name": "Germany",
                "basel_aml_index": 4.0,
                "corridor_risk_weight": 1.0,
                "sanctions_status": "PERMITTED",
                "fatf_listing": "NONE",
                "secrecy_flag": False,
                "max_permitted_risk_rating": "HIGH",
            },
            ADMIN,
        ),
        expected_status=201,
    )

    assert created["jurisdiction_risk_points"] == 8.00
    assert created["version"] == 1
    assert is_valid_uuid(created["id"])
    assert is_iso8601_timestamp(created["created_at"])


def test_create_jurisdiction_profile_omitted_optionals_take_declared_defaults(api):
    """Every optional flag has a declared default, so a body carrying only the four
    required fields still yields a fully populated row scoring 5.0 * 2.0.

    Design: Corner/entities/create_jurisdiction_profile_omitted_optionals_take_declared_defaults
    """
    created = validate_success(
        api.create_jurisdiction_profile(
            {
                "jurisdiction_code": "FR",
                "name": "France",
                "basel_aml_index": 5.0,
                "corridor_risk_weight": 1.2,
            },
            OFFICER,
        ),
        expected_status=201,
    )

    assert created["sanctions_status"] == "PERMITTED"
    assert created["fatf_listing"] == "NONE"
    assert created["secrecy_flag"] is False
    assert created["nested_correspondent_prohibited"] is False
    assert created["max_permitted_risk_rating"] == "HIGH"
    assert created["jurisdiction_risk_points"] == 10.00


def test_create_jurisdiction_profile_missing_corridor_risk_weight_rejected(api):
    """`corridor_risk_weight` carries no default, so its absence is a body defect at
    priority 5 and no row is written.

    Design: Corner/entities/create_jurisdiction_profile_missing_corridor_risk_weight_rejected
    """
    response = api.create_jurisdiction_profile(
        {"jurisdiction_code": "IT", "name": "Italy", "basel_aml_index": 4.5}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST_BODY)

    _rows, meta = validate_paginated(api.list_jurisdiction_profiles(ADMIN))
    assert meta["total_count"] == 0


def test_create_jurisdiction_profile_basel_index_above_ten_rejected(api):
    """10.01 sits one hundredth above the inclusive ceiling of the declared domain, so the
    range check at priority 7 answers rather than any enum or body check.

    Design: Corner/entities/create_jurisdiction_profile_basel_index_above_ten_rejected
    """
    response = api.create_jurisdiction_profile(
        {
            "jurisdiction_code": "PA",
            "name": "Panama",
            "basel_aml_index": 10.01,
            "corridor_risk_weight": 2.0,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_FIELD_OUT_OF_RANGE)


def test_create_jurisdiction_profile_unknown_sanctions_status_rejected(api):
    """An out-of-set enum member is refused at priority 6 with the enum error, which sits
    above the numeric-domain check that a range violation would earn.

    Design: Corner/entities/create_jurisdiction_profile_unknown_sanctions_status_rejected
    """
    response = api.create_jurisdiction_profile(
        {
            "jurisdiction_code": "IR",
            "name": "Iran",
            "basel_aml_index": 8.0,
            "corridor_risk_weight": 2.5,
            "sanctions_status": "EMBARGOED",
        },
        OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM_VALUE)


def test_get_jurisdiction_profile_by_id_returns_stored_row(api):
    """The single-row read is addressed by UUID even though the entity has a natural key,
    and it echoes the stored inputs alongside the derived points.

    Design: Corner/entities/get_jurisdiction_profile_by_id_returns_stored_row
    """
    created = new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )

    fetched = validate_success(api.get_jurisdiction_profile(created["id"], ANALYST))

    assert fetched["id"] == created["id"]
    assert fetched["jurisdiction_code"] == "DE"
    assert fetched["name"] == "Germany"
    assert fetched["basel_aml_index"] == 4.00
    assert fetched["corridor_risk_weight"] == 1.00
    assert fetched["jurisdiction_risk_points"] == 8.00


def test_get_jurisdiction_profile_unknown_id_returns_not_found(api):
    """A well-formed UUID belonging to no row is a path-resolution failure at priority 4,
    reported with the entity's own not-found id.

    Design: Corner/entities/get_jurisdiction_profile_unknown_id_returns_not_found
    """
    new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )

    response = api.get_jurisdiction_profile(NON_EXISTENT_UUID, ANALYST)
    validate_error(response, ApiErrorId.ERR_JURISDICTION_PROFILE_NOT_FOUND)


def test_list_jurisdiction_profiles_pagination_envelope_and_ordering(api):
    """`total_count` counts the rows matching the filters before the window is applied, so
    a two-row window over three rows reports 3 with `has_more` true, in creation order.

    Design: Corner/entities/list_jurisdiction_profiles_pagination_envelope_and_ordering
    """
    de = new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )
    fr = new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    new_jurisdiction(
        jurisdiction_code="US", name="United States", basel_aml_index=3.0,
        corridor_risk_weight=0.8,
    )

    rows, meta = validate_paginated(
        api.list_jurisdiction_profiles(RM, params={"limit": 2, "offset": 0})
    )

    assert [row["id"] for row in rows] == [de["id"], fr["id"]]
    assert [row["jurisdiction_code"] for row in rows] == ["DE", "FR"]
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_list_jurisdiction_profiles_filter_by_sanctions_status_singleton(api):
    """The `sanctions_status` filter narrows the collection before the window, so one
    RESTRICTED row out of three answers with total_count 1 and no further pages.

    Design: Corner/entities/list_jurisdiction_profiles_filter_by_sanctions_status_singleton
    """
    new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )
    tr = new_jurisdiction(
        jurisdiction_code="TR", name="Turkiye", basel_aml_index=6.0, corridor_risk_weight=1.5,
        sanctions_status="RESTRICTED",
    )
    new_jurisdiction(
        jurisdiction_code="KP", name="Korea DPR", basel_aml_index=9.0,
        corridor_risk_weight=2.5, sanctions_status="COMPREHENSIVELY_SANCTIONED",
    )

    rows, meta = validate_paginated(
        api.list_jurisdiction_profiles(ANALYST, params={"sanctions_status": "RESTRICTED"})
    )

    assert [row["id"] for row in rows] == [tr["id"]]
    assert rows[0]["jurisdiction_code"] == "TR"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_list_jurisdiction_profiles_empty_collection_returns_zero_total(api):
    """An empty collection is a successful read, not a not-found: 200 with an empty array,
    a zero total and no further pages.

    Design: Corner/entities/list_jurisdiction_profiles_empty_collection_returns_zero_total
    """
    rows, meta = validate_paginated(api.list_jurisdiction_profiles(COMMITTEE))

    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
