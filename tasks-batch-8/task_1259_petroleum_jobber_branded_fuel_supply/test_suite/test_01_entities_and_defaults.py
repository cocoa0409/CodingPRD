"""Entity creation defaults, shape validation, and not-found behavior (PRD §2.9, §3.1)."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_dealer_station_payload,
    create_inventory_reconciliation_payload,
    create_loss_event_payload,
    create_meter_reading_payload,
    create_product_payload,
    create_storage_tank_payload,
    create_supply_agreement_payload,
    create_tax_remittance_payload,
)

ADMIN = TEST_USERS["admin_headers"]
PRICING = TEST_USERS["pricing_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
TAX = TEST_USERS["tax_headers"]


def test_station_create_defaults_and_initial_state(api):
    """PRD §3.1: "Two optional fields carry defaults: `local_option_tc_per_gal`
    defaults to 0, and `credit_terms_days` defaults to 10 and must be at least
    1. A new station begins with `operating_status` of `ONBOARDING`,
    `credit_status` of `GOOD_STANDING`, `compliance_status` of `COMPLIANT`,
    and zero exposure."

    Design: Corner/entities/station_create_defaults_and_initial_state
    """
    station = validate_success(api.create_dealer_station(
        create_dealer_station_payload(
            station_name="S-Def",
            state_code="TX",
            home_terminal_code="TX-NORTH",
            state_excise_tc_per_gal=200,
            credit_limit_cents=500000,
        ),
        ADMIN,
    ), 201)
    assert station["local_option_tc_per_gal"] == 0
    assert station["credit_terms_days"] == 10
    assert station["current_exposure_cents"] == 0
    assert station["operating_status"] == "ONBOARDING"
    assert station["credit_status"] == "GOOD_STANDING"
    assert station["compliance_status"] == "COMPLIANT"
    assert station["version"] == 1
    assert isinstance(station["id"], str) and station["id"]
    assert "created_at" in station and "updated_at" in station


def test_station_create_missing_required_returns_invalid_request(api):
    """PRD §2.9 step 3: "All required fields are present, no unknown fields
    appear, types are valid, enum members are valid, `window_start` is strictly
    before `window_end`, `term_end_date` is strictly after `term_start_date`,
    `period_end` is on or after `period_start`, and audit `score` lies between
    0 and 100 inclusive — otherwise `ERR_VALIDATION_FAILED` (HTTP 400)."

    Design: Corner/entities/station_create_missing_required_returns_invalid_request
    """
    resp = api.create_dealer_station(
        {
            "station_name": "S-Bad",
            "state_code": "TX",
            "home_terminal_code": "TX-NORTH",
            "state_excise_tc_per_gal": 200,
            # credit_limit_cents omitted
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


def test_product_create_extra_field_rejected(api):
    """PRD §2.9 step 3: "All required fields are present, no unknown fields
    appear, types are valid, enum members are valid, `window_start` is strictly
    before `window_end`, `term_end_date` is strictly after `term_start_date`,
    `period_end` is on or after `period_start`, and audit `score` lies between
    0 and 100 inclusive — otherwise `ERR_VALIDATION_FAILED` (HTTP 400)."

    Design: Corner/entities/product_create_extra_field_rejected
    """
    resp = api.create_product(
        {
            "product_code": "REGULAR_87",
            "display_name": "Regular 87",
            "category": "GASOLINE",
            "federal_excise_tc_per_gal": 184,
            "temp_coeff": 0.00065,
            "sponsor": "acme",  # unknown key
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


def test_dealer_station_not_found_returns_404(api):
    """PRD §2.9 step 4: "Path identifiers are checked left to right, then body
    foreign keys (`station_id`, `tank_id`, `truck_id`, `product_id`,
    `invoice_id`). Each missing resource yields its resource-specific 404:
    `ERR_PRODUCT_NOT_FOUND`, `ERR_DEALER_STATION_NOT_FOUND`, ..."

    Design: Corner/entities/dealer_station_not_found_returns_404
    """
    resp = api.get_dealer_station(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEALER_STATION_NOT_FOUND)


def test_agreement_invalid_enum_rejected(api):
    """PRD §2.9 step 3: "All required fields are present, no unknown fields
    appear, types are valid, enum members are valid, ... otherwise
    `ERR_VALIDATION_FAILED` (HTTP 400)."

    Design: Corner/entities/agreement_invalid_enum_rejected
    """
    station = get_success_data(api.create_dealer_station(
        create_dealer_station_payload(
            station_name="S-Enum",
            state_code="TX",
            home_terminal_code="TX-NORTH",
            state_excise_tc_per_gal=200,
            credit_limit_cents=500000,
        ),
        ADMIN,
    ))
    resp = api.create_supply_agreement(
        create_supply_agreement_payload(
            station_id=station["id"],
            committed_gallons=1000,
            imaging_allowance_cents=1000,
            margin_tc_per_gal=10,
            shortfall_penalty_tc_per_gal=10,
            buyout_method="WEEKLY",  # not a declared enum member
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


def test_product_duplicate_code_rejected(api):
    """PRD §3.1: "A `JobberAdmin` registers each product with a unique
    `product_code` (such as `REGULAR_87`; attempting to reuse a code is
    rejected with `ERR_VALIDATION_FAILED`)..."

    Design: Corner/entities/product_duplicate_code_rejected
    """
    validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    resp = api.create_product(
        create_product_payload(display_name="Duplicate"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


def test_tank_safe_fill_default_applied(api):
    """PRD §3.7: "A tank is commissioned by a `JobberAdmin` with its
    `station_id`, `product_id`, `capacity_gallons` (greater than zero), and
    `opening_physical_gallons` (at least zero), which seeds both physical and
    book inventory; the optional `safe_fill_pct` defaults to 0.95 and must be
    greater than 0 and at most 1."

    Design: Corner/entities/tank_safe_fill_default_applied
    """
    station = get_success_data(api.create_dealer_station(
        create_dealer_station_payload(station_name="S-Tk", credit_limit_cents=500000),
        ADMIN,
    ))
    product = get_success_data(api.create_product(create_product_payload(), ADMIN))
    tank = validate_success(api.create_storage_tank(
        create_storage_tank_payload(
            station_id=station["id"],
            product_id=product["id"],
            capacity_gallons=20000,
            opening_physical_gallons=1000,
        ),
        ADMIN,
    ), 201)
    assert tank["safe_fill_pct"] == 0.95
    assert tank["physical_gallons"] == 1000
    assert tank["book_inventory_gallons"] == 1000


def test_meter_reading_immutable_no_version_field(api):
    """PRD §2.7: "Two resource types are deliberately leaner: meter readings
    and brand compliance audits carry only `id` and `created_at`. Neither has
    `updated_at` nor `version`, and neither participates in optimistic
    concurrency control."
    PRD §3.7: "Each reading's `metered_gallons` is the totalizer minus the
    chronological predecessor's totalizer for the same tank — readings are
    ordered by `reading_at` ascending with `created_at` ascending breaking
    ties — and zero for the tank's first reading."

    Design: Corner/entities/meter_reading_immutable_no_version_field
    """
    from test_helpers import (
        create_storage_tank_payload,
        make_dealer_operator_headers,
    )
    station = get_success_data(api.create_dealer_station(
        create_dealer_station_payload(station_name="S-Mr", credit_limit_cents=500000),
        ADMIN,
    ))
    product = get_success_data(api.create_product(create_product_payload(), ADMIN))
    tank = get_success_data(api.create_storage_tank(
        create_storage_tank_payload(
            station_id=station["id"],
            product_id=product["id"],
            capacity_gallons=20000,
            opening_physical_gallons=0,
        ),
        ADMIN,
    ))
    reading = validate_success(api.create_meter_reading(
        create_meter_reading_payload(
            tank_id=tank["id"],
            reading_at="2026-05-01T08:00:00Z",
            totalizer_gallons=5000,
        ),
        make_dealer_operator_headers(station["id"]),
    ), 201)
    assert "id" in reading and "created_at" in reading
    assert "version" not in reading, "MeterReading must not carry version"
    assert "updated_at" not in reading, "MeterReading must not carry updated_at"
    assert reading["metered_gallons"] == 0


def test_audit_result_computed_boundary(api):
    """PRD §3.4: "The audit's `result` is computed, not supplied: `PASS` when
    the score is at least 70, `FAIL` otherwise."
    PRD §3.4: "A `PASS` recorded while the station is in `CURE_PERIOD` restores
    it to `COMPLIANT` and clears `cure_started_at` to null."

    Design: Corner/entities/audit_result_computed_boundary
    """
    from test_helpers import (
        create_brand_compliance_audit_payload,
    )
    station = get_success_data(api.create_dealer_station(
        create_dealer_station_payload(station_name="S-Aud", credit_limit_cents=500000),
        ADMIN,
    ))
    get_success_data(api.activate_dealer_station(station["id"], ADMIN))
    audit = validate_success(api.create_brand_compliance_audit(
        create_brand_compliance_audit_payload(
            station_id=station["id"], audit_date="2026-05-10", score=70
        ),
        INSPECTOR,
    ), 201)
    assert audit["result"] == "PASS", "score 70 is the inclusive PASS boundary"
    station_now = get_success_data(api.get_dealer_station(station["id"], ADMIN))
    assert station_now["compliance_status"] == "COMPLIANT"
