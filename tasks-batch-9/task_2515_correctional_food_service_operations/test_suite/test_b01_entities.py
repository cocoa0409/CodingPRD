"""Entity shape, defaults, computed fields, immutability and graph edges.

These cases pin what a row looks like the instant it is written: which fields the
client supplies, which the server derives, which stay null until a later step, and
which entities carry no mutable audit stamps at all.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


def test_a_new_contract_lands_in_draft_with_every_ledger_figure_at_zero(
    api: ApiClient,
) -> None:
    """The nine commercial inputs are echoed back, the fourteen derived ledger
    figures are all zero and the damages algorithm is not yet chosen.

    The PRD states: "A new contract lands in `status` `DRAFT`. Its liquidated-damages
    ledger starts empty in the strictest sense: `total_trays_served`,
    `meal_days_served`, `missed_meal_total`, `substitution_total`,
    `grievance_sla_breach_count`, `raw_liquidated_damages_cents`,
    `substitution_surcharge_cents`, `liquidated_damages_cents`,
    `gross_food_cost_cents`, `cost_recovery_credit_cents` and
    `net_liquidated_damages_cents` all read 0, while `substitution_rate_pct`,
    `cost_cents_per_meal_day_actual` and `performance_score` all read 0.00. The chosen
    damages algorithm, `ld_variant`, is null until the first reconciliation pins it,
    and both `reconciled_at` and `closed_at` are null." Per §2.4 `version` "begins at 1
    when the row is created".

    Design: Corner/entities/corner_service_contract_create_returns_declared_defaults
    """
    fixtures.set_clock(api)

    response = api.create_service_contract(
        factories.service_contract_payload(contract_code="CFS-2515-E01"),
        users.CONTRACT_ADMIN,
    )
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    contract = validate_success(response, 201)
    assertions.assert_service_contract(contract)
    assertions.assert_contract_ledger_zeroed(contract)
    assert is_valid_uuid(contract["id"])
    assert contract["status"] == "DRAFT"
    assert contract["ld_variant"] is None
    assert contract["contract_code"] == "CFS-2515-E01"
    assert contract["vendor_name"] == "Aramark Correctional Services"
    assert contract["contracted_kcal_per_meal_day"] == 2800
    assert contract["contracted_sodium_mg_cap_per_meal_day"] == 2400
    assert contract["cost_ceiling_cents_per_meal_day"] == 320
    assert contract["ld_cents_per_missed_meal"] == 750
    assert contract["ld_monthly_cap_cents"] == 5000000
    assert contract["reconciled_at"] is None
    assert contract["closed_at"] is None
    assert contract["version"] == 1


def test_a_facility_read_returns_the_stored_row_and_never_bumps_its_version(
    api: ApiClient,
) -> None:
    """A read echoes the registration inputs, exposes the sharps counters and the
    derived posture, and leaves the row untouched.

    The PRD states: "A newly registered facility is `OPEN` for business:
    `kitchen_posture` reads `OPEN`, `sharps_on_board_count` is initialised to the same
    value as `sharps_authorized_count`". It also states that "A facility read returns
    its sharps counters and its derived posture", while §2.4 makes `version` "an
    integer that begins at 1 when the row is created and is incremented by exactly 1
    on every mutation of that row", so a read moves nothing. The `ComplianceAuditor`
    "may call every read endpoint in the domain".

    Design: Corner/entities/corner_facility_get_returns_stored_row
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-E02")
    created = fixtures.create_facility(
        api,
        contract["id"],
        facility_code="FAC-E02",
        name="West Unit Kitchen",
        sharps_authorized_count=9,
        satellite_site_count=3,
        blast_chiller_capacity=4,
    )

    read = validate_success(api.get_facility(created["id"], users.AUDITOR))
    assertions.assert_facility(read)
    assert read["facility_code"] == "FAC-E02"
    assert read["version"] == created["version"]
    assert read["kitchen_posture"] == "OPEN"
    assert read["sharps_authorized_count"] == 9
    assert read["sharps_on_board_count"] == 9
    assert read["sharps_issued_count"] == 0
    assert read["sharps_unaccounted_count"] == 0
    assert read["satellite_site_count"] == 3
    assert read["blast_chiller_capacity"] == 4
    assert read["contract_id"] == contract["id"]


def test_the_diet_order_listing_reports_total_count_and_has_more_across_pages(
    api: ApiClient,
) -> None:
    """Three adjacent orders on one inmate page two at a time, with the totals
    describing the whole filtered set rather than the page.

    The PRD states: "The `meta` block of a list response carries `limit` and `offset`
    echoing the effective values used, `total_count` giving the number of rows
    matching the filters before pagination is applied, and `has_more` set true when
    rows remain beyond the current page." It also states that "Results are ordered by
    `created_at` ascending on every list endpoint unless that endpoint's own
    description says otherwise, and this ordering is stable across pages."

    Design: Corner/entities/corner_diet_order_list_paginates_with_total_count_and_has_more
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-E03"},
        facility_overrides={"facility_code": "FAC-E03"},
    )
    inmate = fixtures.create_inmate(
        api,
        ctx["facility"]["id"],
        booking_number="BK-0003",
        religious_affiliation="JEWISH",
    )
    windows = (
        ("2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z"),
        ("2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z"),
        ("2026-08-20T00:00:00Z", "2026-08-30T00:00:00Z"),
    )
    created_ids = []
    for effective_from, effective_to in windows:
        current = validate_success(api.get_inmate(inmate["id"], users.DIETITIAN))
        order = validate_success(
            api.create_diet_order(
                factories.religious_diet_order_payload(
                    current["id"],
                    current["version"],
                    diet_code="KOSHER",
                    effective_from=effective_from,
                    effective_to=effective_to,
                ),
                users.DIETITIAN,
            ),
            201,
        )
        created_ids.append(order["id"])

    page_one_response = api.list_diet_orders(
        users.AUDITOR, {"inmate_id": inmate["id"], "limit": 2, "offset": 0}
    )
    assert page_one_response.json()["response_type"] == "array"
    page_one, meta_one = validate_paginated(page_one_response)
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert len(page_one) == 2

    page_two, meta_two = validate_paginated(
        api.list_diet_orders(
            users.AUDITOR, {"inmate_id": inmate["id"], "limit": 2, "offset": 2}
        )
    )
    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert len(page_two) == 1

    paged_ids = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(paged_ids)) == 3
    assert set(paged_ids) == set(created_ids)
    for row in page_one + page_two:
        assert row["inmate_id"] == inmate["id"]
        assert row["order_type"] == "RELIGIOUS"
        assert row["status"] == "PENDING_VERIFICATION"


def test_an_unknown_facility_id_reports_the_facility_specific_not_found_code(
    api: ApiClient,
) -> None:
    """A well-formed but unknown path id is a 404 naming the missing entity, not an
    empty success body.

    The PRD states: "Every resource named by a path segment exists, validated strictly
    left to right so that the outermost segment's 404 is reported first. The specific
    code names the entity that was missing: `ERR_SERVICE_CONTRACT_NOT_FOUND`,
    `ERR_FACILITY_NOT_FOUND`, ...". The error envelope carries "`error_id`" and
    "`message`", where "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/entities/corner_get_facility_unknown_id_returns_not_found
    """
    fixtures.set_clock(api)

    response = api.get_facility(NON_EXISTENT_UUID, users.AUDITOR)
    validate_error(response, ApiErrorId.ERR_FACILITY_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"] != ""


def test_omitting_sharps_authorized_count_is_rejected_as_an_invalid_request(
    api: ApiClient,
) -> None:
    """The knife inventory size carries no default, so leaving it out is a shape
    failure and no facility row appears.

    The PRD states: "On every write endpoint, every field the endpoint declares as
    required is present and carries the declared JSON type, else
    `ERR_INVALID_REQUEST`." Registration requires "the size of the knife inventory in
    `sharps_authorized_count`", while only `satellite_site_count` and
    `blast_chiller_capacity` are described as "Two operational parameters are
    optional."

    Design: Corner/entities/corner_facility_create_missing_sharps_authorized_count_rejected
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-E05")

    validate_error(
        api.create_facility(
            factories.facility_payload(
                contract["id"],
                facility_code="FAC-E05",
                name="North Unit Kitchen",
                sharps_authorized_count=factories.OMIT,
            ),
            users.CONTRACT_ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _, meta = validate_paginated(
        api.list_facilities(users.AUDITOR, {"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 0


def test_facility_creation_applies_the_satellite_and_chiller_defaults(
    api: ApiClient,
) -> None:
    """Both optional parameters fall back to their declared values, and the shadow
    board starts full rather than empty.

    The PRD states: "`satellite_site_count`, the number of satellite feeding sites fed
    from this kitchen, defaults to 0 and must be at least 0" and "`blast_chiller_
    capacity`, the number of cook-chill batches whose buffered occupancy intervals may
    overlap, defaults to 2 and must be at least 1." It continues: "`sharps_on_board_
    count` is initialised to the same value as `sharps_authorized_count` — every
    authorised tool is presumed on the board — and every other derived field starts at
    its zero ... `corrective_action_required` reads false, and `last_sharps_audit_at`
    is null because the board has never been counted."

    Design: Corner/entities/corner_facility_create_applies_satellite_and_chiller_defaults
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-E06")

    facility = validate_success(
        api.create_facility(
            {
                "contract_id": contract["id"],
                "facility_code": "FAC-E06",
                "name": "Annex Kitchen",
                "sharps_authorized_count": 7,
            },
            users.CONTRACT_ADMIN,
        ),
        201,
    )

    assertions.assert_facility(facility)
    assert facility["satellite_site_count"] == 0
    assert facility["blast_chiller_capacity"] == 2
    assert facility["sharps_on_board_count"] == 7
    assert facility["sharps_authorized_count"] == 7
    assertions.assert_sharps_conservation(facility)
    assert facility["corrective_action_required"] is False
    assert facility["kitchen_posture"] == "OPEN"
    assert facility["last_sharps_audit_at"] is None
    assert facility["sharps_audit_shortfall"] == 0
    assert facility["open_sharps_discrepancy_count"] == 0
    assert facility["open_contraband_incident_count"] == 0
    assert facility["active_special_diet_count"] == 0


def test_population_count_total_is_the_plain_sum_of_its_four_segments(
    api: ApiClient,
) -> None:
    """The head total is derived, not supplied, and the row is stamped from the
    logical clock with the submitting officer.

    The PRD states: "The system computes `total_population` as the plain sum of the
    four segments, stamps `count_at` from the logical clock — the instant that drives
    forecast staleness downstream — and records `submitted_by_user_id`. A population
    count is an immutable ledger row: it has no `updated_at` and no `version`, and no
    operation ever changes one."

    Design: Corner/entities/corner_population_count_total_is_computed_from_four_segments
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        clock="2026-08-01T06:30:00Z",
        contract_overrides={"contract_code": "CFS-2515-E07"},
        facility_overrides={"facility_code": "FAC-E07"},
    )

    count = validate_success(
        api.create_population_count(
            factories.population_count_payload(
                ctx["facility"]["id"],
                general_population=41,
                segregation_population=7,
                satellite_population=5,
                medical_population=3,
                source="EMERGENCY_COUNT",
            ),
            users.OFFICER,
        ),
        201,
    )

    assertions.assert_population_count(count)
    assert count["total_population"] == 56
    assertions.assert_instant(count["count_at"], "2026-08-01T06:30:00Z")
    assert count["submitted_by_user_id"] == users.user_id_of(users.OFFICER)
    assert count["source"] == "EMERGENCY_COUNT"
    assert "version" not in count
    assert "updated_at" not in count


def test_a_new_menu_cycle_generates_its_system_fields_and_leaves_approvals_null(
    api: ApiClient,
) -> None:
    """Only the facility, code and length are supplied; everything else is stamped or
    deliberately absent until the cycle is signed.

    The PRD states: "The cycle opens in `status` `DRAFT` with `item_count` at 0 and all
    four attested figures — `approved_kcal_per_meal_day`,
    `approved_protein_grams_per_meal_day`, `approved_sodium_mg_per_meal_day` and
    `approved_cost_cents_per_meal_day` — null, because nothing has been attested yet.
    `nutrition_signed_by_user_id`, `activated_by_user_id` and `activated_at` are
    likewise null." Per §2.4 every resource carries "an `id`, which is a server-minted
    UUID with no type prefix of any kind", with `version` beginning at 1.

    Design: Corner/entities/corner_menu_cycle_system_fields_generated_on_create
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-E08"},
        facility_overrides={"facility_code": "FAC-E08"},
    )

    cycle = validate_success(
        api.create_menu_cycle(
            factories.menu_cycle_payload(
                ctx["facility"]["id"], cycle_code="CYC-E08", cycle_length_days=3
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )

    assertions.assert_menu_cycle(cycle)
    assertions.assert_menu_cycle_draft_defaults(cycle)
    assert is_valid_uuid(cycle["id"])
    assert cycle["version"] == 1
    assert cycle["cycle_length_days"] == 3
    assert cycle["cycle_code"] == "CYC-E08"


def test_an_unknown_housing_unit_is_rejected_as_an_invalid_enum_value(
    api: ApiClient,
) -> None:
    """A feeding-location class outside the declared four is refused and no inmate is
    booked.

    The PRD states that the booking payload names "a `housing_unit` of `GENERAL`,
    `SEGREGATION`, `SATELLITE` or `MEDICAL` — the feeding-location class that decides
    which forecast bucket this head lands in", and that in the ladder "On every write
    endpoint, every enum-typed field carries a value inside its declared domain, else
    `ERR_INVALID_ENUM_VALUE`."

    Design: Corner/entities/corner_inmate_create_invalid_housing_unit_enum_rejected
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-E09"},
        facility_overrides={"facility_code": "FAC-E09"},
    )

    validate_error(
        api.create_inmate(
            factories.inmate_payload(
                ctx["facility"]["id"],
                booking_number="BK-0009",
                housing_unit="INFIRMARY",
            ),
            users.OFFICER,
        ),
        ApiErrorId.ERR_INVALID_ENUM_VALUE.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_inmates(users.AUDITOR, {"facility_id": ctx["facility"]["id"]})
    )
    assert meta["total_count"] == 0


def test_registering_a_facility_under_an_unknown_contract_reports_not_found(
    api: ApiClient,
) -> None:
    """The parent reference is resolved before anything is written, so no orphan
    facility can appear.

    The PRD states: "Every reference supplied in a request body names an existing row,
    validated in the order the endpoint declares its input fields, and reported with
    the same per-entity 404 code as step 8", where that code list includes
    "`ERR_SERVICE_CONTRACT_NOT_FOUND`". The ladder's "first failure aborts the request
    with no partial writes."

    Design: Corner/entities/corner_facility_create_with_unknown_contract_id_returns_not_found
    """
    fixtures.set_clock(api)

    validate_error(
        api.create_facility(
            factories.facility_payload(
                NON_EXISTENT_UUID,
                facility_code="FAC-E11",
                name="Orphan Kitchen",
                sharps_authorized_count=12,
            ),
            users.CONTRACT_ADMIN,
        ),
        ApiErrorId.ERR_SERVICE_CONTRACT_NOT_FOUND.value,
        404,
    )

    _, meta = validate_paginated(api.list_facilities(users.AUDITOR))
    assert meta["total_count"] == 0
