"""Creation postures, stored-row reads and omitted-optional defaults."""

from datetime import datetime

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ADMIN_HQ_HEADERS,
    STAFF_OPS_HEADERS,
    assert_cents,
    assert_common_fields,
    assert_decimal2,
    make_club_headers,
    make_manufacturer_headers,
)
from test_helpers.factories import (
    club_payload,
    demo_event_payload,
    demonstrator_payload,
    equipment_unit_payload,
    manufacturer_payload,
    non_food_product_payload,
)
from test_helpers.types import (
    AccountStatus,
    BookingAction,
    ClubStatus,
    ClubTier,
    DayPart,
    EmploymentStatus,
    EquipmentType,
    ProductCategory,
    ProgramTier,
    SanitationStatus,
)


def _instant(value):
    """Parse an ISO-8601 UTC instant, tolerating the optional fractional part."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_manufacturer_registration_returns_the_declared_opening_posture(api):
    """PRD §3.1: "A newly registered vendor starts with `account_status` set to `ACTIVE`, and both ledger mirrors — `outstanding_balance_cents` and `credit_note_balance_cents` — at zero."

    Design: Corner/entities/manufacturer_creation_returns_201_with_every_declared_field
    """
    payload = manufacturer_payload(
        legal_name="Bellhaven Foods Inc",
        billing_email="ap@bellhaven.example",
        program_tier=ProgramTier.PLATINUM,
        credit_limit_cents=900_000,
        credit_terms_days=60,
    )

    response = api.create_manufacturer(payload, ADMIN_HQ_HEADERS)

    vendor = validate_success(response, 201)
    assert vendor["legal_name"] == "Bellhaven Foods Inc"
    assert vendor["billing_email"] == "ap@bellhaven.example"
    assert vendor["program_tier"] == ProgramTier.PLATINUM
    assert_cents(vendor["credit_limit_cents"], 900_000, "credit_limit_cents")
    assert vendor["credit_terms_days"] == 60
    assert vendor["account_status"] == AccountStatus.ACTIVE
    assert_cents(vendor["outstanding_balance_cents"], 0, "outstanding_balance_cents")
    assert_cents(vendor["credit_note_balance_cents"], 0, "credit_note_balance_cents")
    assert_common_fields(vendor)
    assert vendor["version"] == 1

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_club_read_back_returns_the_stored_row_with_its_opening_status(api):
    """PRD §3.1: "A new club opens with `club_status` set to `OPEN`."

    PRD §2.4: "`version` (integer): a monotonically increasing counter that begins at 1 on creation and increments by exactly 1 on every mutation of the row, including server-initiated recomputation of derived fields."

    Design: Corner/entities/club_retrieval_by_id_returns_the_stored_row_unchanged
    """
    created = validate_success(
        api.create_club(
            club_payload(
                club_number="C6001",
                name="Bellhaven Club 6001",
                region_code="SW",
                club_tier=ClubTier.SATELLITE,
                daily_event_capacity=2,
                food_station_count=0,
                health_permit_expires_on="2027-03-31",
            ),
            ADMIN_HQ_HEADERS,
        ),
        201,
    )

    read_back = validate_success(
        api.get_club(created["id"], make_club_headers(created["id"]))
    )

    assert read_back["club_status"] == ClubStatus.OPEN
    assert read_back["version"] == created["version"] == 1
    assert read_back["id"] == created["id"]
    assert read_back["created_at"] == created["created_at"]
    assert read_back["club_number"] == "C6001"
    assert read_back["name"] == "Bellhaven Club 6001"
    assert read_back["region_code"] == "SW"
    assert read_back["club_tier"] == ClubTier.SATELLITE
    assert read_back["daily_event_capacity"] == 2
    assert read_back["food_station_count"] == 0
    assert read_back["health_permit_expires_on"] == "2027-03-31"


def test_omitted_optional_inputs_take_their_declared_defaults(api):
    """PRD §3.2: "`attribution_window_days`, from 3 through 28 inclusive, sets the length of the final sales-lift attribution window and defaults to 14 when omitted."

    PRD §3.2: "`addon_services` is an array of billable extras drawn from `EXTRA_TABLE`, `VIDEO_LOOP`, `ALLERGEN_SIGNAGE`, `PREMIUM_PLACEMENT` and `BILINGUAL_DEMONSTRATOR`, with no duplicates and no more than five members; it defaults to an empty array."

    PRD §3.4: "Adding a demonstrator captures a `home_club_id` naming the club the worker is rostered to, a `full_name`, an `hourly_rate_cents` of at least 1 that will price the invoice's staffing lines, and an optional `max_weekly_events` from 1 through 14 that defaults to 5."

    PRD §3.4: "A new worker starts with `employment_status` set to `ACTIVE`, both reliability variants — `reliability_score_rolling_90` and `reliability_score_program_to_date` — at 100.00, and `no_show_strike_count` and `completed_event_count` both at zero."

    Design: Corner/entities/demo_event_omitted_optionals_take_declared_defaults
    """
    vendor = validate_success(
        api.create_manufacturer(
            manufacturer_payload(legal_name="Dunmere Household"), ADMIN_HQ_HEADERS
        ),
        201,
    )
    club = validate_success(
        api.create_club(
            club_payload(club_number="C6003", daily_event_capacity=3, food_station_count=1),
            ADMIN_HQ_HEADERS,
        ),
        201,
    )

    product_payload = non_food_product_payload(
        vendor["id"],
        sku="DH-MAT-003",
        name="Anti-Fatigue Mat",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=2400,
        samples_per_case=2,
        weekly_sample_case_pool=12,
    )
    product_payload.pop("emergency_reserve_cases", None)
    product = validate_success(
        api.create_product(product_payload, make_manufacturer_headers(vendor["id"])),
        201,
    )
    assert product["emergency_reserve_cases"] == 0

    event_payload = demo_event_payload(
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    event_payload.pop("addon_services", None)
    event = validate_success(
        api.create_demo_event(event_payload, make_manufacturer_headers(vendor["id"])),
        201,
    )
    assert event["attribution_window_days"] == 14
    assert event["addon_services"] == []
    assert event["allocated_sample_cases"] == 0

    worker_payload = demonstrator_payload(club["id"], full_name="Nils Aberg", hourly_rate_cents=2000)
    worker_payload.pop("max_weekly_events", None)
    worker = validate_success(
        api.create_demonstrator(worker_payload, STAFF_OPS_HEADERS), 201
    )
    assert worker["max_weekly_events"] == 5
    assert worker["employment_status"] == EmploymentStatus.ACTIVE
    assert_decimal2(worker["reliability_score_rolling_90"], 100.00, "rolling_90")
    assert_decimal2(
        worker["reliability_score_program_to_date"], 100.00, "program_to_date"
    )
    assert worker["no_show_strike_count"] == 0
    assert worker["completed_event_count"] == 0


def test_equipment_food_cert_flag_is_derived_from_the_unit_type_alone(api):
    """PRD §3.5: "From the type the server derives `requires_food_cert`, which reads true for a `CONVECTION_OVEN`, an `INDUCTION_COOKTOP` or a `REFRIGERATED_CART` and false for a `DISPLAY_TABLE` or a `TV_CART`; a client-supplied value for that field is ignored."

    PRD §3.5: "A new unit is registered with `sanitation_status` set to `SANITIZED` and `last_sanitized_at` unset."

    Design: Corner/entities/equipment_unit_requires_food_cert_is_computed_from_equipment_type
    """
    club = validate_success(
        api.create_club(
            club_payload(club_number="C6004", daily_event_capacity=3, food_station_count=2),
            ADMIN_HQ_HEADERS,
        ),
        201,
    )
    club_headers = make_club_headers(club["id"])

    oven = validate_success(
        api.create_equipment_unit(
            equipment_unit_payload(
                club["id"],
                asset_tag="EQ-6004-OVEN",
                equipment_type=EquipmentType.CONVECTION_OVEN,
            ),
            club_headers,
        ),
        201,
    )
    tv_cart = validate_success(
        api.create_equipment_unit(
            equipment_unit_payload(
                club["id"],
                asset_tag="EQ-6004-TV",
                equipment_type=EquipmentType.TV_CART,
            ),
            club_headers,
        ),
        201,
    )

    assert oven["requires_food_cert"] is True
    assert tv_cart["requires_food_cert"] is False
    assert oven["sanitation_status"] == SanitationStatus.SANITIZED
    assert tv_cart["sanitation_status"] == SanitationStatus.SANITIZED
    assert oven["last_sanitized_at"] is None
    assert tv_cart["last_sanitized_at"] is None


def test_submission_stamp_is_written_only_by_its_own_transition(api):
    """PRD §3.2: "And the booking opens in a known posture: `booking_status` `DRAFT`, `staffing_status` `UNSTAFFED`, `settlement_status` `UNBILLED`, and `allocated_sample_cases`, `pool_cases_used` and `reserve_cases_used` all zero, with `submitted_at`, `approved_at` and `cancellation_reason` all unset, `required_support_count` zero and `no_show_recovery_open` false."

    PRD §3.2: "On success the submission stamps `submitted_at` with the logical clock's current instant and increments the event's `version` by 1."

    PRD §2.5: "A `MORNING` demo runs from 09:00Z to 13:00Z, a `MIDDAY` demo from 12:00Z to 16:00Z, and an `AFTERNOON` demo from 15:00Z to 19:00Z, all on the event's `event_date`."

    Design: Corner/entities/demo_event_system_stamps_start_null_and_are_set_only_by_transitions
    """
    vendor = validate_success(
        api.create_manufacturer(
            manufacturer_payload(legal_name="Faircot Supply"), ADMIN_HQ_HEADERS
        ),
        201,
    )
    club = validate_success(
        api.create_club(club_payload(club_number="C6005"), ADMIN_HQ_HEADERS), 201
    )
    vendor_headers = make_manufacturer_headers(vendor["id"])
    product = validate_success(
        api.create_product(
            non_food_product_payload(
                vendor["id"],
                sku="FS-BIN-005",
                name="Utility Bin",
                unit_cost_cents=1200,
                samples_per_case=2,
                weekly_sample_case_pool=12,
            ),
            vendor_headers,
        ),
        201,
    )
    event = validate_success(
        api.create_demo_event(
            demo_event_payload(
                vendor["id"],
                club["id"],
                product["id"],
                event_date="2026-09-14",
                day_part=DayPart.MIDDAY,
                requested_sample_cases=2,
            ),
            vendor_headers,
        ),
        201,
    )

    assert event["submitted_at"] is None
    assert event["approved_at"] is None
    assert event["version"] == 1
    assert _instant(event["event_window_start_utc"]) == _instant("2026-09-14T12:00:00Z")
    assert _instant(event["event_window_end_utc"]) == _instant("2026-09-14T16:00:00Z")

    submitted = validate_success(
        api.demo_event_transition(
            event["id"], {"action": BookingAction.SUBMIT}, vendor_headers
        )
    )

    assert submitted["submitted_at"] is not None
    assert submitted["approved_at"] is None
    assert submitted["version"] == 2
