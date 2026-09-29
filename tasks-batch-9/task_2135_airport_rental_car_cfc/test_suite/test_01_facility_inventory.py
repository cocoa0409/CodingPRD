"""Standing up the ConRAC inventory: facilities, brands and counter space."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    ApiErrorId,
    UNKNOWN_UUID,
    UNKNOWN_UUIDS,
    assert_facility,
    assert_counter_space,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_facility_registration_initialises_trust_and_covenant(api):
    """PRD §3.1: "On registration all seven trust buckets and `trust_lifetime_received_cents`
    start at 0, `funded_obligation_count` starts at 0, `overflow_stalls_allocated` starts at 0
    and `overflow_stalls_available` therefore equals `overflow_lot_stalls`,
    `bond_coverage_status` is computed as described in §2.8, and `current_utc` reports the
    logical clock."
    PRD §2.8: "Note the consequence at registration time: a facility whose
    `ds_reserve_requirement_cents` is greater than zero begins life `DEFICIENT`, while a
    facility that requires no debt-service reserve at all begins `SATISFIED`."
    PRD §2.11: "It keeps a logical clock, exposed on every facility as `current_utc`, which
    reads exactly `2026-08-01T00:00:00Z` until an administrator moves it and never falls back
    to real time."

    Design: Corner/entities/facility_creation_initialises_every_trust_bucket_and_covenant_posture
    """
    payload = f.facility_payload(
        code="DEN",
        name="DEN ConRAC",
        cfc_rate_per_transaction_day_cents=500,
        ds_reserve_requirement_cents=5_000_000,
        om_reserve_requirement_cents=1_000_000,
        capital_fund_cap_cents=50_000_000,
        overflow_lot_stalls=100,
        overflow_daily_surcharge_cents=400,
        remittance_grace_days=20,
    )
    facility = validate_success(api.create_facility(payload, ADMIN), 201)

    assert_facility(facility)
    for bucket in (
        "trust_lifetime_received_cents",
        "trust_debt_service_reserve_cents",
        "trust_debt_service_funded_cents",
        "trust_om_reserve_cents",
        "trust_capital_fund_cents",
        "trust_unallocated_cents",
        "trust_encumbered_cents",
        "trust_disbursed_cents",
    ):
        assert facility[bucket] == 0, f"{bucket} must start at 0, got {facility[bucket]}"
    assert facility["bond_coverage_status"] == "DEFICIENT", (
        "a facility requiring 5,000,000 cents of debt-service reserve begins DEFICIENT"
    )
    assert facility["overflow_stalls_allocated"] == 0
    assert facility["overflow_stalls_available"] == 100
    assert facility["funded_obligation_count"] == 0
    assert facility["version"] == 1
    assert facility["current_utc"] == "2026-08-01T00:00:00Z", (
        f"the logical clock must read 2026-08-01T00:00:00Z, got {facility['current_utc']}"
    )


def test_facility_optional_fields_default_to_zero_and_twenty(api):
    """PRD §3.1: "`overflow_daily_surcharge_cents`, the per-stall per-day surcharge billed for
    overflow-lot stalls, defaults to 0 when omitted."
    PRD §3.1: "`remittance_grace_days`, the number of days after a reporting period's last
    calendar day before an unpaid Customer Facility Charge remittance falls delinquent,
    defaults to 20 when omitted — the float an operator is given to move the cash it has
    already collected from travellers."
    PRD §2.8: "Note the consequence at registration time: a facility whose
    `ds_reserve_requirement_cents` is greater than zero begins life `DEFICIENT`, while a
    facility that requires no debt-service reserve at all begins `SATISFIED`."

    Design: Corner/entities/facility_optional_fields_take_declared_defaults_when_omitted
    """
    payload = {
        "code": "PHX",
        "name": "PHX ConRAC",
        "cfc_rate_per_transaction_day_cents": 600,
        "ds_reserve_requirement_cents": 0,
        "om_reserve_requirement_cents": 0,
        "capital_fund_cap_cents": 1_000_000,
        "overflow_lot_stalls": 10,
    }
    facility = validate_success(api.create_facility(payload, ADMIN), 201)

    assert facility["overflow_daily_surcharge_cents"] == 0, (
        "an omitted overflow_daily_surcharge_cents must default to 0, not null"
    )
    assert facility["remittance_grace_days"] == 20, (
        "an omitted remittance_grace_days must default to 20, not null"
    )
    assert facility["bond_coverage_status"] == "SATISFIED", (
        "a facility requiring no debt-service reserve begins SATISFIED"
    )


def test_get_facility_with_unknown_id_returns_facility_not_found(api):
    """PRD §2.5: "Path parameters are nevertheless validated left to right, and a path
    parameter that names no existing row rejects the request before any body field is
    examined, with the not-found code belonging to that resource type: `facility_id` yields
    `ERR_FACILITY_NOT_FOUND`"

    Design: Corner/entities/get_facility_with_unknown_id_returns_not_found
    """
    response = api.get_facility(UNKNOWN_UUID, ADMIN)

    validate_error(response, ApiErrorId.ERR_FACILITY_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_concessionaire_without_brand_code_is_rejected(api):
    """PRD §3.1: "A brand row carries `facility_id`, its registered `legal_name`, a
    `brand_code` of two to eight uppercase characters, and a `contact_email` for billing
    correspondence."
    PRD §2.6: "Request shape: every required input field is present, every value has the
    declared type, every enum-typed value is a legal member of its enumeration, every integer
    satisfies its declared range, every date parses as `YYYY-MM-DD`, and pagination stays
    within its bounds; otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_concessionaire_missing_brand_code_returns_invalid_request
    """
    facility = fx.create_facility(api)

    response = api.create_concessionaire(
        {
            "facility_id": facility["id"],
            "legal_name": "Avex Rent A Car",
            "contact_email": "ops@avex.example",
        },
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _rows, meta = validate_paginated(
        api.list_concessionaires(ADMIN, params={"facility_id": facility["id"]})
    )
    assert meta["total_count"] == 0, "the rejected create must leave no concessionaire behind"


def test_duplicate_brand_code_at_one_facility_is_rejected(api):
    """PRD §3.1: "Two brands at the same facility may not share a `brand_code`; an attempt to
    reuse one is rejected with `ERR_DUPLICATE_BRAND_CODE`."

    Design: Corner/validations/duplicate_brand_code_within_a_facility_is_rejected
    """
    facility = fx.create_facility(api)
    fx.create_concessionaire(
        api, facility["id"], legal_name="Avex Rent A Car", brand_code="AVX"
    )

    response = api.create_concessionaire(
        f.concessionaire_payload(
            facility["id"],
            legal_name="Avex Holdings",
            brand_code="AVX",
            contact_email="a2@x.example",
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_BRAND_CODE.value, 409)
    _rows, meta = validate_paginated(
        api.list_concessionaires(ADMIN, params={"facility_id": facility["id"]})
    )
    assert meta["total_count"] == 1, "the facility must still hold exactly one brand"


def test_concessionaire_list_pages_with_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` object of a list response carries `limit` and `offset` as they
    were resolved for the request, `total_count` as the number of rows matching the filters
    before the page window is applied, and `has_more` as a boolean that is true when rows
    remain beyond the current window."

    Design: Corner/entities/concessionaire_list_paginates_with_total_count_and_has_more
    """
    facility = fx.create_facility(api)
    brand_a = fx.create_concessionaire(
        api, facility["id"], legal_name="Avex Rent A Car", brand_code="AVX",
        contact_email="a@x.example",
    )
    brand_b = fx.create_concessionaire(
        api, facility["id"], legal_name="Budline Auto Rental", brand_code="BUD",
        contact_email="b@x.example",
    )
    brand_c = fx.create_concessionaire(
        api, facility["id"], legal_name="Cruzo Cars", brand_code="CRZ",
        contact_email="c@x.example",
    )

    first_page, first_meta = validate_paginated(
        api.list_concessionaires(
            ADMIN, params={"facility_id": facility["id"], "limit": 2, "offset": 0}
        )
    )
    second_page, second_meta = validate_paginated(
        api.list_concessionaires(
            ADMIN, params={"facility_id": facility["id"], "limit": 2, "offset": 2}
        )
    )

    assert len(first_page) == 2, f"limit 2 must return 2 rows, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(second_page) == 1, f"the tail page must hold 1 row, got {len(second_page)}"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    seen = {row["id"] for row in first_page} | {row["id"] for row in second_page}
    assert seen == {brand_a["id"], brand_b["id"], brand_c["id"]}


def test_pagination_limit_above_one_hundred_is_rejected(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, may not be smaller than 1, and may not
    be larger than 100. `offset` defaults to 0 and may not be negative. A `limit` outside the
    1-to-100 range, or a negative `offset`, is a malformed request and is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/pagination_limit_above_maximum_returns_invalid_request
    """
    facility = fx.create_facility(api)

    response = api.list_concessionaires(
        ADMIN, params={"facility_id": facility["id"], "limit": 101, "offset": 0}
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_counter_space_read_echoes_stored_inventory_fields(api):
    """PRD §3.1: "Each space carries `facility_id`, a `terminal_code` naming the terminal or
    level it sits on, a `space_label` that must be unique within the facility, and a
    `space_class` of either `COUNTER` for rental counters or `READY_RETURN` for ready and
    return stalls."
    PRD §3.1: "A new space begins unoccupied, with `active_assignment_id` null and
    `assignment_count` of 0; the latter counts the assignments on that space whose status is
    either `ALLOCATED` or `ACTIVE`."

    Design: Corner/entities/counter_space_retrieval_returns_exactly_what_was_stored
    """
    facility = fx.create_facility(api)
    created = fx.create_counter_space(
        api, facility["id"], terminal_code="GT", space_label="RR-14",
        space_class="READY_RETURN",
    )

    space = validate_success(api.get_counter_space(created["id"], AUDITOR))

    assert_counter_space(space)
    assert space["terminal_code"] == "GT"
    assert space["space_label"] == "RR-14"
    assert space["space_class"] == "READY_RETURN"
    assert space["active_assignment_id"] is None, "a new space is unoccupied"
    assert space["assignment_count"] == 0
    assert space["facility_id"] == facility["id"]


def test_duplicate_space_label_at_one_facility_is_rejected(api):
    """PRD §3.1: "A repeated `space_label` at the same facility is rejected with
    `ERR_DUPLICATE_SPACE_LABEL`."

    Design: Corner/validations/duplicate_counter_space_label_is_rejected
    """
    facility = fx.create_facility(api)
    fx.create_counter_space(
        api, facility["id"], terminal_code="T1", space_label="T1-A02", space_class="COUNTER"
    )

    response = api.create_counter_space(
        f.counter_space_payload(
            facility["id"], terminal_code="GT", space_label="T1-A02",
            space_class="READY_RETURN",
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_SPACE_LABEL.value, 409)
    _rows, meta = validate_paginated(
        api.list_counter_spaces(ADMIN, params={"facility_id": facility["id"]})
    )
    assert meta["total_count"] == 1, "the facility must still hold exactly one space"


def test_unknown_ids_on_read_endpoints_return_their_own_codes(api):
    """PRD §2.5: "`agreement_id` yields `ERR_AGREEMENT_NOT_FOUND`, `counter_space_id` yields
    `ERR_COUNTER_SPACE_NOT_FOUND`, `counter_assignment_id` yields
    `ERR_COUNTER_ASSIGNMENT_NOT_FOUND`, `zone_id` yields `ERR_ZONE_NOT_FOUND`,
    `fleet_allocation_id` yields `ERR_FLEET_ALLOCATION_NOT_FOUND`, `report_id` yields
    `ERR_REPORT_NOT_FOUND`, `remittance_id` yields `ERR_REMITTANCE_NOT_FOUND`,
    `obligation_id` yields `ERR_OBLIGATION_NOT_FOUND`, `shuttle_period_id` yields
    `ERR_SHUTTLE_PERIOD_NOT_FOUND`, `shuttle_allocation_id` yields
    `ERR_SHUTTLE_ALLOCATION_NOT_FOUND`, `project_id` yields `ERR_PROJECT_NOT_FOUND`,
    `disbursement_id` yields `ERR_DISBURSEMENT_NOT_FOUND`, and `settlement_id` yields
    `ERR_SETTLEMENT_NOT_FOUND`. All of these carry HTTP 404."

    Design: Corner/errors/unknown_ids_on_read_endpoints_return_their_own_not_found_codes
    """
    probes = [
        (api.get_agreement, UNKNOWN_UUIDS[0], ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value),
        (api.get_counter_space, UNKNOWN_UUIDS[1], ApiErrorId.ERR_COUNTER_SPACE_NOT_FOUND.value),
        (
            api.get_counter_assignment,
            UNKNOWN_UUIDS[2],
            ApiErrorId.ERR_COUNTER_ASSIGNMENT_NOT_FOUND.value,
        ),
        (api.get_fleet_zone, UNKNOWN_UUIDS[3], ApiErrorId.ERR_ZONE_NOT_FOUND.value),
        (
            api.get_fleet_allocation,
            UNKNOWN_UUIDS[4],
            ApiErrorId.ERR_FLEET_ALLOCATION_NOT_FOUND.value,
        ),
        (api.get_remittance, UNKNOWN_UUIDS[5], ApiErrorId.ERR_REMITTANCE_NOT_FOUND.value),
        (api.get_obligation, UNKNOWN_UUIDS[6], ApiErrorId.ERR_OBLIGATION_NOT_FOUND.value),
        (
            api.get_shuttle_period,
            UNKNOWN_UUIDS[7],
            ApiErrorId.ERR_SHUTTLE_PERIOD_NOT_FOUND.value,
        ),
        (
            api.get_shuttle_allocation,
            UNKNOWN_UUIDS[8],
            ApiErrorId.ERR_SHUTTLE_ALLOCATION_NOT_FOUND.value,
        ),
        (api.get_disbursement, UNKNOWN_UUIDS[9], ApiErrorId.ERR_DISBURSEMENT_NOT_FOUND.value),
        (api.get_settlement, UNKNOWN_UUIDS[10], ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value),
    ]

    seen = []
    for getter, unknown_id, expected_error in probes:
        response = getter(unknown_id, ADMIN)
        assert response.status_code == 404, (
            f"{expected_error} must carry HTTP 404, got {response.status_code}"
        )
        error = validate_error(response, expected_error, 404)
        seen.append(error["error_id"])

    assert len(set(seen)) == 11, (
        f"the eleven reads must surface eleven distinct error identifiers, got {sorted(set(seen))}"
    )
