"""Stored-row contracts: echoed fields, defaults, computed money, immutability."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

STARTUP_CLOCK = const.CLOCK_STARTUP_DEFAULT
ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]

FULLY_OVERRIDDEN_INSTALLATION = {
    "name": "Norfolk Naval Station Family Housing",
    "branch": "NAVY",
    "mha_code": "VA-NRF",
    "bill_of_rights_version": "2026.1",
    "turn_buffer_days": 7,
    "offer_response_hours": 48,
    "decline_limit": 3,
    "decline_penalty_days": 20,
    "incentive_base_pct": 0.04,
}


def _empty_database_at_startup(api):
    """Nothing but the logical clock, parked at its startup reading."""
    fx.set_clock(api, STARTUP_CLOCK)


def _bare_installation(api):
    """One installation carrying every declared policy default."""
    fx.set_clock(api, STARTUP_CLOCK)
    return fx.create_installation(api)


def test_installation_creation_echoes_every_supplied_override(api):
    """All five policy knobs are stored as given and the counters start empty.

    PRD: "At registration, `total_unit_count`, `available_unit_count`, `assigned_unit_count`, `occupied_unit_count`, `offline_unit_count`, `hazard_hold_unit_count` and `pending_application_count` all initialise to 0, `offer_run_epoch` initialises to 0, and `last_offer_run_at` initialises to null."

    Design: Corner/entities/installation_creation_with_all_overrides_returns_declared_fields
    """
    _empty_database_at_startup(api)

    response = api.create_installation(
        f.create_installation_payload(**FULLY_OVERRIDDEN_INSTALLATION), ADMIN
    )

    created = validate_success(response, 201)
    asserts.assert_envelope_meta(response.json())
    asserts.assert_installation(created)
    for field, value in FULLY_OVERRIDDEN_INSTALLATION.items():
        assert created[field] == value, field
    for counter in (
        "total_unit_count",
        "available_unit_count",
        "assigned_unit_count",
        "occupied_unit_count",
        "offline_unit_count",
        "hazard_hold_unit_count",
        "pending_application_count",
        "offer_run_epoch",
    ):
        assert created[counter] == 0, counter
    assert created["last_offer_run_at"] is None
    assert created["version"] == 1
    asserts.assert_instant_equals(created["created_at"], STARTUP_CLOCK)
    asserts.assert_instant_equals(created["updated_at"], STARTUP_CLOCK)
    reread = fx.read_installation(api, created["id"])
    assert reread == created


HISTORIC_ACCESSIBLE_UNIT = {
    "unit_code": "B-200",
    "bedroom_count": 3,
    "unit_type": "SFH",
    "designated_rank_category": "SENIOR_ENLISTED",
    "historic_flag": True,
    "accessibility_features": ["ROLL_IN_SHOWER", "ZERO_STEP_ENTRY"],
}


def test_housing_unit_read_returns_the_stored_row_and_moves_two_counters(api):
    """The read reproduces the array field and the two nulls a new unit carries.

    PRD: "A newly created unit enters inventory with `status` `AVAILABLE`, a null `hazard_hold_reason` and a null `last_lease_end_date`, and the creation raises the installation's `total_unit_count` by one and `available_unit_count` by one, preserving the counter invariant of §2.8."

    Design: Corner/entities/housing_unit_retrieval_returns_the_stored_row
    """
    installation = _bare_installation(api)
    created = fx.create_housing_unit(
        api, installation["id"], **HISTORIC_ACCESSIBLE_UNIT
    )

    unit = validate_success(api.get_housing_unit(created["id"], TECH))

    asserts.assert_housing_unit(unit)
    assert unit["installation_id"] == installation["id"]
    for field, value in HISTORIC_ACCESSIBLE_UNIT.items():
        assert unit[field] == value, field
    assert unit["status"] == "AVAILABLE"
    assert unit["hazard_hold_reason"] is None
    assert unit["last_lease_end_date"] is None
    assert unit["version"] == 1
    parent = fx.read_installation(api, installation["id"])
    assert parent["total_unit_count"] == 1
    assert parent["available_unit_count"] == 1
    asserts.assert_installation_counter_conservation(parent)


FIVE_UNIT_INVENTORY = (
    {"unit_code": "A-101"},
    {"unit_code": "A-102"},
    {"unit_code": "A-103"},
    {
        "unit_code": "B-200",
        "bedroom_count": 3,
        "unit_type": "SFH",
        "designated_rank_category": "SENIOR_ENLISTED",
    },
    {"unit_code": "C-300", "unit_type": "APARTMENT"},
)


def test_housing_unit_listing_pages_and_filters_independently(api):
    """The window moves without changing the count, and the filters disagree.

    PRD: "The `meta` block of every list response carries `limit`, `offset`, `total_count` and `has_more`; `total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/housing_unit_listing_paginates_and_filters_independently
    """
    state = fx.setup_multi_unit_installation(api, FIVE_UNIT_INVENTORY)
    inst_id = state["installation"]["id"]
    offline = state["units"][2]
    validate_success(
        api.set_housing_unit_status(
            offline["id"], f.housing_unit_status_payload("OFFLINE_MAINTENANCE"), MANAGER
        )
    )

    first_page, first_meta = validate_paginated(
        api.list_housing_units(
            MANAGER, params={"installation_id": inst_id, "limit": 2, "offset": 0}
        )
    )
    last_page, last_meta = validate_paginated(
        api.list_housing_units(
            MANAGER, params={"installation_id": inst_id, "limit": 2, "offset": 4}
        )
    )

    assert first_meta["total_count"] == 5
    assert first_meta["has_more"] is True
    assert len(first_page) == 2
    assert first_page[0]["unit_code"] == "A-101"
    asserts.assert_created_at_ascending(first_page)
    assert last_meta["total_count"] == 5
    assert last_meta["has_more"] is False
    assert len(last_page) == 1
    assert last_page[0]["unit_code"] == "C-300"

    available, available_meta = validate_paginated(
        api.list_housing_units(
            MANAGER, params={"installation_id": inst_id, "status": "AVAILABLE"}
        )
    )
    assert available_meta["total_count"] == 4
    assert "A-103" not in [row["unit_code"] for row in available]

    townhomes, townhome_meta = validate_paginated(
        api.list_housing_units(
            MANAGER,
            params={
                "installation_id": inst_id,
                "bedroom_count": 2,
                "unit_type": "TOWNHOME",
            },
        )
    )
    assert townhome_meta["total_count"] == 3
    assert "A-103" in [row["unit_code"] for row in townhomes]


ROUTINE_RESPONSE_DUE_AT = "2026-08-06T00:00:00Z"
ROUTINE_COMPLETION_DUE_AT = "2026-08-31T00:00:00Z"


def test_every_omitted_optional_field_takes_its_declared_default(api):
    """Four creates supply only mandatory input and inherit five, two, one, one.

    PRD: "The optional `historic_flag` defaults to false and, when true, adds a rent premium before the statutory BAH cap is applied. The optional `accessibility_features` array defaults to empty and holds zero or more of the codes `ROLL_IN_SHOWER`, `ZERO_STEP_ENTRY` and `WIDENED_DOORWAYS`."

    Design: Corner/entities/omitted_optional_fields_fall_back_to_declared_defaults
    """
    _empty_database_at_startup(api)

    installation = validate_success(
        api.create_installation(f.create_installation_payload(), ADMIN), 201
    )
    assert installation["turn_buffer_days"] == const.DEFAULT_TURN_BUFFER_DAYS
    assert installation["offer_response_hours"] == const.DEFAULT_OFFER_RESPONSE_HOURS
    assert installation["decline_limit"] == const.DEFAULT_DECLINE_LIMIT
    assert installation["decline_penalty_days"] == const.DEFAULT_DECLINE_PENALTY_DAYS
    assert installation["incentive_base_pct"] == const.DEFAULT_INCENTIVE_BASE_PCT

    unit_payload = f.create_housing_unit_payload(installation["id"])
    unit_payload.pop("historic_flag")
    unit = validate_success(api.create_housing_unit(unit_payload, ADMIN), 201)
    assert unit["historic_flag"] is False
    assert unit["accessibility_features"] == []
    assert unit["status"] == "AVAILABLE"

    sponsor = fx.create_service_member(api)
    dependent = validate_success(
        api.create_dependent(
            f.create_dependent_payload(sponsor["id"], relationship="SPOUSE",
                                       date_of_birth="1992-03-04",
                                       gender="FEMALE"),
            ADMIN,
        ),
        201,
    )
    assert dependent["is_full_time_custody"] is True
    assert validate_success(api.get_service_member(sponsor["id"], MANAGER))[
        "dependent_count"
    ] == 1

    order = validate_success(
        api.create_work_order(f.create_work_order_payload(unit["id"]), MANAGER), 201
    )
    assert order["habitability_impact"] is False
    assert order["priority_class"] == "ROUTINE"
    asserts.assert_instant_equals(order["response_due_at"], ROUTINE_RESPONSE_DUE_AT)
    asserts.assert_instant_equals(order["completion_due_at"], ROUTINE_COMPLETION_DUE_AT)
    assert order["lease_id"] is None
    assert order["parent_work_order_id"] is None
    assert order["inspection_deficiency_code"] is None
    assert order["status"] == "SUBMITTED"
    assert order["escalation_level"] == 0
    assert order["reopen_count"] == 0
    assert order["sla_breached"] is False
    assert order["first_response_at"] is None


SECOND_INSTALLATION_NAME = "Fort Hood Historic District"


def test_the_system_fields_are_minted_by_the_server_from_the_logical_clock(api):
    """Two creates at one clock reading share their stamps but not their ids.

    PRD: "Every persisted resource carries an `id` that is a server-minted UUID string with no type prefix and no embedded meaning; clients never supply it."

    Design: Corner/entities/installation_system_fields_are_server_minted_from_the_logical_clock
    """
    _empty_database_at_startup(api)

    first = validate_success(
        api.create_installation(f.create_installation_payload(), ADMIN), 201
    )
    second = validate_success(
        api.create_installation(
            f.create_installation_payload(name=SECOND_INSTALLATION_NAME), ADMIN
        ),
        201,
    )

    assert is_valid_uuid(first["id"])
    assert is_valid_uuid(second["id"])
    assert first["id"] != second["id"]
    asserts.assert_instant_equals(first["created_at"], STARTUP_CLOCK)
    asserts.assert_instant_equals(first["updated_at"], STARTUP_CLOCK)
    # The clock never moved, so the second row carries the same instant.
    asserts.assert_instant_equals(second["created_at"], STARTUP_CLOCK)
    assert second["created_at"] == first["created_at"]
    assert first["version"] == 1
    assert second["version"] == 1
    assert first["offer_run_epoch"] == 0
    assert first["last_offer_run_at"] is None


def test_the_lease_money_and_link_fields_are_computed_not_supplied(api):
    """Four input fields in, four money figures and a sponsor link out.

    PRD: "The lease's money fields are then set from the BAH table under the provisional variant described next, and `early_termination_fee_cents`, `settlement_total_cents`, `allotment_balance_cents` and `abatement_total_cents` all initialise to 0 while `bill_of_rights_version_ack`, `bill_of_rights_ack_at`, `termination_reason`, `termination_notice_date` and `termination_effective_date` all initialise to null."

    Design: Corner/entities/lease_money_and_link_fields_are_computed_not_supplied
    """
    state = fx.setup_accepted_application(api)
    payload = f.create_lease_payload(
        state["application"]["id"], state["unit"]["id"]
    )
    assert set(payload) == {
        "application_id",
        "housing_unit_id",
        "start_date",
        "term_months",
    }

    lease = validate_success(api.create_lease(payload, MANAGER), 201)

    asserts.assert_lease(lease)
    assert lease["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert lease["utility_allowance_cents"] == const.BASE_UTILITY_ALLOWANCE_CENTS
    assert lease["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    assert lease["daily_rent_cents"] == const.BASE_DAILY_RENT_CENTS
    assert lease["rent_basis"] == "OFFER_PROVISIONAL"
    assert lease["rent_effective_year"] == 2026
    # Copied off the application, not named in the request body.
    assert lease["service_member_id"] == state["sponsor"]["id"]
    assert lease["occupancy_status"] == "PENDING_MOVE_IN"
    assert lease["allotment_status"] == "NOT_STARTED"
    for money_field in (
        "early_termination_fee_cents",
        "settlement_total_cents",
        "allotment_balance_cents",
        "abatement_total_cents",
    ):
        assert lease[money_field] == 0, money_field
    for null_field in (
        "bill_of_rights_version_ack",
        "bill_of_rights_ack_at",
        "termination_reason",
        "termination_notice_date",
        "termination_effective_date",
    ):
        assert lease[null_field] is None, null_field
    assert fx.read_application(api, state["application"]["id"])["status"] == "HOUSED"
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "ASSIGNED"


OUT_OF_RANGE_BEDROOM_COUNT = 6
UNDECLARED_UNIT_TYPE = "CONDO"
UNDECLARED_ACCESSIBILITY_FEATURE = ["ELEVATOR"]


def test_out_of_range_and_unknown_enum_unit_values_are_invalid_request(api):
    """Six bedrooms, a condo and an elevator each fail the shape rung.

    PRD: "Before any lookup, the request body and query string are checked for structural validity: every required field present, every enum-typed value a declared member of its enumeration, every integer-typed value an actual integer, monetary fields non-negative integers unless this document explicitly declares them signed, every ISO date and datetime parseable, and `limit` within 1 through 100 with `offset` at least 0."

    Design: Corner/entities/housing_unit_out_of_range_and_unknown_enum_values_are_invalid_request
    """
    installation = _bare_installation(api)
    inst_id = installation["id"]

    validate_error(
        api.create_housing_unit(
            f.create_housing_unit_payload(
                inst_id,
                unit_code="A-101",
                bedroom_count=OUT_OF_RANGE_BEDROOM_COUNT,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_housing_unit(
            f.create_housing_unit_payload(
                inst_id, unit_code="A-102", unit_type=UNDECLARED_UNIT_TYPE
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_housing_unit(
            f.create_housing_unit_payload(
                inst_id,
                unit_code="A-103",
                accessibility_features=UNDECLARED_ACCESSIBILITY_FEATURE,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    parent = fx.read_installation(api, inst_id)
    assert parent["total_unit_count"] == 0
    assert parent["available_unit_count"] == 0
    _, meta = validate_paginated(
        api.list_housing_units(MANAGER, params={"installation_id": inst_id})
    )
    assert meta["total_count"] == 0


SEPTEMBER = "2026-09"


def test_the_two_immutable_row_types_carry_no_version_and_no_updated_at(api):
    """A rate row and a ledger row are append-only records, not editable ones.

    PRD: "Two entities are deliberate exceptions because they are immutable once written: a `BahRate` row and an `AllotmentTransaction` row carry only `id` and `created_at`."

    Design: Corner/entities/immutable_rows_carry_no_version_and_have_no_update_endpoint
    """
    state = fx.setup_charged_lease(api, period_month=SEPTEMBER)

    rates, rate_meta = validate_paginated(
        api.list_installation_bah_rates(
            state["installation"]["id"],
            ADMIN,
            params={
                "pay_grade": "E5",
                "with_dependents": True,
                "effective_year": 2026,
            },
        )
    )
    ledger, ledger_meta = validate_paginated(
        api.list_lease_allotment_transactions(
            state["lease"]["id"], MANAGER, params={"period_month": SEPTEMBER}
        )
    )

    assert rate_meta["total_count"] == 1
    assert rates[0]["monthly_rate_cents"] == const.TEST_DEFAULTS["E5_MONTHLY_RATE_CENTS"]
    asserts.assert_immutable_row_fields(rates[0], "BahRate")

    assert ledger_meta["total_count"] == 1
    assert ledger[0]["type"] == "CHARGE"
    assert ledger[0]["amount_cents"] == const.BASE_NET_RENT_CENTS
    assert ledger[0]["running_balance_cents"] == const.BASE_NET_RENT_CENTS
    asserts.assert_immutable_row_fields(ledger[0], "AllotmentTransaction")

    # No declared endpoint addresses either row by id, so neither can be
    # mutated after it is written.
    for path in (
        f"/bah-rates/{rates[0]['id']}",
        f"/allotment-transactions/{ledger[0]['id']}",
    ):
        rejected = api.raw_post(path, {"monthly_rate_cents": 1}, ADMIN)
        assert rejected.status_code >= 400, path


UNKNOWN_SPONSOR_ID = NON_EXISTENT_UUID
UNKNOWN_INSTALLATION_ID = "22222222-2222-4222-8222-222222222222"


def test_child_rows_naming_unknown_parents_take_the_parent_s_own_not_found(api):
    """The dependent blames the sponsor rung, the application the installation one.

    PRD: "Rung 7 requires the addressed `ServiceMember` to exist and covers sponsor reads, the sponsor's dependent listing, orders recording, and any body carrying `service_member_id`; failure is `ERR_SERVICE_MEMBER_NOT_FOUND` (404)."

    Design: Corner/entities/dependent_and_application_with_unknown_parent_ids_return_not_found
    """
    _bare_installation(api)
    sponsor = fx.create_service_member(api)

    validate_error(
        api.create_dependent(
            f.create_dependent_payload(
                UNKNOWN_SPONSOR_ID,
                relationship="SPOUSE",
                date_of_birth="1992-03-04",
                gender="FEMALE",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_SERVICE_MEMBER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_waitlist_application(
            f.create_waitlist_application_payload(
                UNKNOWN_INSTALLATION_ID, sponsor["id"]
            ),
            fx.make_service_member_headers(sponsor["id"]),
        ),
        ApiErrorId.ERR_INSTALLATION_NOT_FOUND,
        404,
    )

    _, dependent_meta = validate_paginated(
        api.list_service_member_dependents(sponsor["id"], MANAGER)
    )
    assert dependent_meta["total_count"] == 0
    _, application_meta = validate_paginated(
        api.list_waitlist_applications(
            MANAGER, params={"service_member_id": sponsor["id"]}
        )
    )
    assert application_meta["total_count"] == 0


TWO_BARE_UNITS = (
    {"unit_code": "A-101"},
    {"unit_code": "A-102"},
)
FOLLOW_ON_DESCRIPTION = "Follow-on paint work"


def test_a_parent_work_order_on_another_unit_is_rejected_after_the_existence_check(api):
    """The unknown parent is a 404 first; the wrong-unit parent is a 422 after.

    PRD: "Rung 33 requires a supplied `parent_work_order_id` or `source_work_order_id` to belong to the same housing unit as the row being created; it guards work-order submission and hazard-case reporting, failing with `ERR_WORK_ORDER_UNIT_MISMATCH` (422)."

    Design: Corner/entities/work_order_parent_on_a_different_unit_is_rejected_after_the_existence_check
    """
    state = fx.setup_multi_unit_installation(
        api, TWO_BARE_UNITS, clock=STARTUP_CLOCK
    )
    first_unit, second_unit = state["units"]
    parent = fx.submit_work_order(api, first_unit["id"])

    validate_error(
        api.create_work_order(
            f.create_work_order_payload(
                second_unit["id"],
                parent_work_order_id=parent["id"],
                description=FOLLOW_ON_DESCRIPTION,
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_WORK_ORDER_UNIT_MISMATCH,
        422,
    )
    # Priority 11 pre-empts priority 33: an unresolvable parent is a 404.
    validate_error(
        api.create_work_order(
            f.create_work_order_payload(
                first_unit["id"],
                parent_work_order_id=NON_EXISTENT_UUID,
                description=FOLLOW_ON_DESCRIPTION,
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_WORK_ORDER_NOT_FOUND,
        404,
    )

    _, second_unit_meta = validate_paginated(
        api.list_work_orders(MANAGER, params={"housing_unit_id": second_unit["id"]})
    )
    assert second_unit_meta["total_count"] == 0
    _, child_meta = validate_paginated(
        api.list_work_orders(MANAGER, params={"parent_work_order_id": parent["id"]})
    )
    assert child_meta["total_count"] == 0


def test_every_omitted_mandatory_input_field_is_an_invalid_request(api):
    """A pay grade, a rank category and a utility allowance cannot be left out.

    PRD: "**Rung 4 — request shape.** Before any lookup, the request body and query string are checked for structural validity: every required field present, every enum-typed value a declared member of its enumeration, every integer-typed value an actual integer, monetary fields non-negative integers unless this document explicitly declares them signed, every ISO date and datetime parseable, and `limit` within 1 through 100 with `offset` at least 0. A violation is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/missing_required_input_fields_return_invalid_request
    """
    installation = _bare_installation(api)

    sponsor_payload = f.create_service_member_payload()
    sponsor_payload.pop("pay_grade")
    validate_error(
        api.create_service_member(sponsor_payload, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    unit_payload = f.create_housing_unit_payload(installation["id"])
    unit_payload.pop("designated_rank_category")
    unit_payload.pop("historic_flag")
    validate_error(
        api.create_housing_unit(unit_payload, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    rate_payload = f.create_bah_rate_payload(installation["id"])
    rate_payload.pop("utility_allowance_cents")
    validate_error(
        api.create_bah_rate(rate_payload, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    assert fx.read_installation(api, installation["id"])["total_unit_count"] == 0
