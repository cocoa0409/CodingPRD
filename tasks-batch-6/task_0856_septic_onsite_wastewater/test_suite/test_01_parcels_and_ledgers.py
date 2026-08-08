"""The parcel register: hydraulic allowance, fee ledger, listings and the dossier."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_compliance_dossier,
    assert_parcel,
    condemn_parcel_well,
    create_parcel,
    create_parcel_payload,
    create_well,
    create_draft_site_evaluation,
    make_applicant_headers,
    refresh_parcel,
    unique_apn,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_parcel_creation_initialises_every_derived_field(api, records_clerk_headers):
    """PRD §3.1: "On success the register copies the creating caller's `X-User-ID`
    into `owner_user_id`, sets all four fee-ledger counters to zero, sets `risk_tier`
    to `LOW` and `transfer_hold` to false, and derives the parcel's hydraulic
    allowance."
    PRD §2.4: "`version` is an integer that starts at 1 when the record is created
    and increments by exactly 1 on every mutation of that record, including mutations
    that arrive as the cascade of an operation performed on some other record."

    Design: Corner/entities/corner_parcel_creation_returns_201_with_all_derived_fields_initialised
    """
    owner = make_applicant_headers("u-app-9")
    payload = create_parcel_payload(
        apn=unique_apn("0856-E1"),
        county_code="OR",
        site_address="20 First Street",
        lot_size_sqft=30000,
        water_source="PUBLIC_WATER",
    )
    parcel = validate_success(api.create_parcel(payload, owner), 201)

    assert_parcel(parcel)
    assert parcel["owner_user_id"] == "u-app-9"
    assert parcel["max_design_flow_gpd"] == 1500
    assert parcel["permitted_design_flow_gpd"] == 0
    assert parcel["fees_assessed_cents"] == 0
    assert parcel["fees_paid_cents"] == 0
    assert parcel["fees_credited_cents"] == 0
    assert parcel["fee_balance_cents"] == 0
    assert parcel["open_repair_order_count"] == 0
    assert parcel["water_quality_flag"] is False
    assert parcel["transfer_hold"] is False
    assert parcel["risk_tier"] == "LOW"
    assert parcel["version"] == 1


def test_max_design_flow_discards_the_fractional_part_below_the_cap(api, applicant_headers):
    """PRD §3.1: "It is derived from lot area alone: divide `lot_size_sqft` by 20
    square feet per gallon per day, discard the fractional part, and then cap the
    result at 1500 gallons per day."

    Design: Corner/entities/corner_parcel_max_design_flow_uses_floor_division_below_the_cap
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-E2"),
        county_code="WA",
        site_address="21 Odd Acre",
        lot_size_sqft=12345,
    )
    assert parcel["max_design_flow_gpd"] == 617, (
        "12345 / 20 is 617.25, which must be floored to 617 rather than rounded"
    )


def test_parcel_read_echoes_the_registered_particulars(api, applicant_headers, records_clerk_headers):
    """PRD §3.1: "An `Applicant` opens one by supplying its assessor parcel number as
    `apn`, the two-letter `county_code` of the county it sits in, its street address
    as `site_address`, its lot area in square feet as `lot_size_sqft`, and the potable
    water source serving it as `water_source`, which is either `PUBLIC_WATER` or
    `PRIVATE_WELL`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/corner_parcel_retrieval_returns_the_stored_entity
    """
    apn = unique_apn("0856-E3")
    created = create_parcel(
        api,
        headers=applicant_headers,
        apn=apn,
        county_code="OR",
        site_address="22 Echo Way",
        lot_size_sqft=20000,
        water_source="PRIVATE_WELL",
    )

    response = api.get_parcel(created["id"], records_clerk_headers)
    parcel = validate_success(response, 200)
    body = response.json()

    assert parcel["apn"] == apn
    assert parcel["county_code"] == "OR"
    assert parcel["site_address"] == "22 Echo Way"
    assert parcel["lot_size_sqft"] == 20000
    assert parcel["water_source"] == "PRIVATE_WELL"
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_parcel_listing_reports_total_count_and_has_more(api, applicant_headers, records_clerk_headers):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as
    actually applied, `total_count` giving the number of records matching the filters
    before pagination, and `has_more`, which is true exactly when records remain
    beyond the current page."

    Design: Corner/entities/corner_parcel_list_paginates_with_total_count_and_has_more
    """
    for address in ("23 A Street", "24 B Street", "25 C Street"):
        create_parcel(
            api,
            headers=applicant_headers,
            apn=unique_apn("0856-E4"),
            county_code="OR",
            site_address=address,
            lot_size_sqft=20000,
        )

    first_page = api.list_parcels(
        records_clerk_headers, params={"county_code": "OR", "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2, f"limit 2 must return two rows, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert first_page.json()["response_type"] == "array"

    second_page = api.list_parcels(
        records_clerk_headers, params={"county_code": "OR", "limit": 2, "offset": 2}
    )
    rows, meta = validate_paginated(second_page)
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_unknown_parcel_id_is_reported_as_missing(api, records_clerk_headers):
    """PRD §2.6: "Every resource named by a path segment must exist, and path segments
    are resolved strictly left to right, so a request against a well nested under a
    non-existent parcel reports the parcel as missing rather than the well."

    Design: Corner/entities/corner_get_parcel_with_unknown_uuid_returns_not_found
    """
    response = api.get_parcel(NON_EXISTENT_UUID, records_clerk_headers)
    validate_error(response, ApiErrorId.ERR_PARCEL_NOT_FOUND.value, 404)


def test_parcel_registration_without_lot_size_is_malformed(api, applicant_headers, records_clerk_headers):
    """PRD §2.6: "The payload must be well formed: required fields present, enumerated
    fields naming a declared member, numbers inside their declared bounds,
    `scheduled_end` strictly after `scheduled_start`, `valid_until` strictly after
    `valid_from`, and pagination parameters inside their declared range."

    Design: Corner/entities/corner_create_parcel_missing_required_lot_size_returns_invalid_request
    """
    response = api.create_parcel(
        {
            "apn": unique_apn("0856-E5"),
            "county_code": "OR",
            "site_address": "26 Incomplete Court",
            "water_source": "PUBLIC_WATER",
        },
        applicant_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(api.list_parcels(records_clerk_headers))
    assert meta["total_count"] == 0, "a malformed registration must create no parcel"


def test_duplicate_apn_is_refused_only_within_the_same_county(api, applicant_headers):
    """PRD §3.1: "The pair of `apn` and `county_code` is the parcel's legal identity
    and no two parcels may share it; a second registration of the same pair is refused
    with `ERR_DUPLICATE_APN`."

    Design: Corner/entities/corner_duplicate_apn_within_same_county_is_rejected
    """
    apn = unique_apn("0856-E8")
    create_parcel(
        api,
        headers=applicant_headers,
        apn=apn,
        county_code="OR",
        site_address="29 Twin Trail",
        lot_size_sqft=20000,
    )

    clash = api.create_parcel(
        create_parcel_payload(
            apn=apn, county_code="OR", site_address="30 Twin Trail", lot_size_sqft=20000
        ),
        applicant_headers,
    )
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_APN.value, 409)

    other_county = validate_success(
        api.create_parcel(
            create_parcel_payload(
                apn=apn,
                county_code="WA",
                site_address="31 Twin Trail",
                lot_size_sqft=20000,
            ),
            applicant_headers,
        ),
        201,
    )
    assert other_county["county_code"] == "WA"


def test_pagination_parameters_outside_their_range_are_refused(api, applicant_headers, records_clerk_headers):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`,
    is a malformed request and is refused with `ERR_INVALID_REQUEST` (HTTP 400) rather
    than being silently clamped."

    Design: Corner/validations/corner_pagination_limit_above_maximum_returns_invalid_request
    """
    create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-V3"),
        site_address="56 Page Place",
        lot_size_sqft=20000,
    )

    validate_error(
        api.list_parcels(records_clerk_headers, params={"limit": 101, "offset": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.list_parcels(records_clerk_headers, params={"limit": 1, "offset": -1}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )


def test_parcel_version_advances_by_one_per_fee_payment(api, applicant_headers):
    """PRD §3.1: "Recording one is a parcel-scoped write available to the `Applicant`
    who owns the parcel and to any `RecordsClerk`; it carries a single `amount_cents`
    figure, adds that figure to `fees_paid_cents`, re-derives `fee_balance_cents`,
    increments the parcel's `version` by 1, and answers with the refreshed parcel."
    PRD §3.1: "It may legitimately be negative when a parcel has overpaid."

    Design: Corner/cross_cutting_layers/corner_entity_version_increments_on_every_mutation
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-L3"),
        site_address="78 Increment Isle",
    )
    assert parcel["version"] == 1
    created_at = parcel["created_at"]

    after_first = validate_success(
        api.record_fee_payment(parcel["id"], {"amount_cents": 1000}, applicant_headers), 200
    )
    after_second = validate_success(
        api.record_fee_payment(parcel["id"], {"amount_cents": 2000}, applicant_headers), 200
    )

    assert after_first["version"] == 2, f"expected version 2, got {after_first['version']}"
    assert after_second["version"] == 3, f"expected version 3, got {after_second['version']}"
    assert after_second["fees_paid_cents"] == 3000
    assert after_second["fee_balance_cents"] == -3000
    assert after_second["created_at"] == created_at, "created_at must not move"


def test_applicant_may_not_pay_fees_on_a_parcel_they_do_not_own(api):
    """PRD §2.1: "An `Applicant` acting on a parcel-scoped resource — recording a fee
    payment against a parcel's ledger, or opening a transfer-certificate request —
    must be the parcel's owner; if `X-User-ID` differs from the parcel's
    `owner_user_id`, the request is refused with `ERR_NOT_PARCEL_OWNER` (HTTP 403)."

    Design: Corner/rbac/corner_applicant_cannot_pay_fees_on_another_owners_parcel
    """
    owner = make_applicant_headers("u-app-9")
    stranger = make_applicant_headers("u-app-8")
    parcel = create_parcel(
        api, headers=owner, apn=unique_apn("0856-R3"), site_address="74 Owner Oval"
    )

    refused = api.record_fee_payment(parcel["id"], {"amount_cents": 5000}, stranger)
    validate_error(refused, ApiErrorId.ERR_NOT_PARCEL_OWNER.value, 403)

    accepted = validate_success(
        api.record_fee_payment(parcel["id"], {"amount_cents": 5000}, owner), 200
    )
    assert accepted["fees_paid_cents"] == 5000
    assert accepted["fee_balance_cents"] == -5000
    assert accepted["owner_user_id"] == "u-app-9"


def test_compliance_dossier_is_computed_on_read(api, applicant_headers, records_clerk_headers):
    """PRD §3.1: "It is a computed object, not a stored one, and reports eleven fields:
    `parcel_id`, `risk_tier`, `transfer_hold`, `fee_balance_cents`,
    `permitted_design_flow_gpd`, `max_design_flow_gpd`, `open_repair_order_count` and
    `water_quality_flag` are copied straight off the parcel; `well_count` is the number
    of wells recorded on it; `active_operating_permit_count` is the number of operating
    permits on it whose `status` is `ACTIVE`; and `latest_certificate_grade` is the
    `certificate_grade` of the parcel's transfer inspection with the greatest
    `certified_at`, or null when the parcel has no certified inspection at all."

    Design: Corner/endpoints/corner_parcel_compliance_dossier_is_a_computed_read
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-EP1"),
        site_address="68 Dossier Drive",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers)
    condemn_parcel_well(api, well["id"])

    response = api.get_compliance_dossier(parcel["id"], records_clerk_headers)
    dossier = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assert_compliance_dossier(dossier)

    assert dossier["parcel_id"] == parcel["id"]
    assert dossier["risk_tier"] == "ELEVATED"
    assert dossier["transfer_hold"] is True
    assert dossier["water_quality_flag"] is True
    assert dossier["well_count"] == 1
    assert dossier["active_operating_permit_count"] == 0
    assert dossier["fee_balance_cents"] == 0
    assert dossier["permitted_design_flow_gpd"] == 0
    assert dossier["max_design_flow_gpd"] == 1500
    assert dossier["open_repair_order_count"] == 0
    assert dossier["latest_certificate_grade"] is None


def test_parcel_child_listings_never_leak_a_sibling_parcels_rows(api, applicant_headers, records_clerk_headers):
    """PRD §3.1: "Narrower listings exist for reaching a parcel's children: its wells,
    optionally narrowed by `well_type`, and its site evaluations, optionally narrowed
    by `status`; both are available to `Applicant`, `DesignProfessional`,
    `EnvironmentalHealthSpecialist`, `HealthOfficer` and `RecordsClerk`."

    Design: Corner/endpoints/corner_child_list_endpoints_filter_strictly_by_foreign_key
    """
    left = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-EP3A"),
        site_address="70 Left Lane",
        water_source="PRIVATE_WELL",
    )
    left_well = create_well(api, left["id"], headers=applicant_headers)
    left_eval = create_draft_site_evaluation(api, left["id"])

    right = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-EP3B"),
        site_address="71 Right Road",
        water_source="PRIVATE_WELL",
    )
    right_well = create_well(
        api,
        right["id"],
        headers=applicant_headers,
        well_type="IRRIGATION",
        location_x_ft=5,
        location_y_ft=5,
        depth_ft=60,
    )
    right_eval = create_draft_site_evaluation(
        api,
        right["id"],
        evaluated_on="2026-04-16T00:00:00Z",
        soil_group="SANDY",
        depth_to_limiting_layer_in=60,
    )

    wells, wells_meta = validate_paginated(
        api.list_parcel_wells(left["id"], records_clerk_headers)
    )
    assert wells_meta["total_count"] == 1
    assert [row["id"] for row in wells] == [left_well["id"]]
    assert right_well["id"] not in [row["id"] for row in wells]

    evaluations, eval_meta = validate_paginated(
        api.list_parcel_site_evaluations(right["id"], records_clerk_headers)
    )
    assert eval_meta["total_count"] == 1
    assert [row["id"] for row in evaluations] == [right_eval["id"]]
    assert left_eval["id"] not in [row["id"] for row in evaluations]


def test_parcel_stays_consistent_after_reading_it_back(api, applicant_headers):
    """PRD §3.1: "The outstanding `fee_balance_cents` is then the assessed total less
    the paid total less the credited total."

    Design: Corner/cross_cutting_layers/corner_entity_version_increments_on_every_mutation
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-L3B"),
        site_address="78 Increment Isle",
    )
    validate_success(
        api.record_fee_payment(parcel["id"], {"amount_cents": 4200}, applicant_headers), 200
    )

    reread = refresh_parcel(api, parcel["id"], applicant_headers)
    assert reread["version"] == 2
    assert reread["fees_paid_cents"] == 4200
    assert reread["fee_balance_cents"] == -4200
    assert_parcel(reread)
