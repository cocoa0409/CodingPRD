"""Daily gate admission pricing: season-pass coverage, age tiers (PRD §3.2)."""
from test_helpers import (
    api_client, validate_success, ApiErrorId, TEST_USERS,
    assert_admission,
    create_pass_holder_payload,
    make_facility, make_season, make_pass_holder, make_season_pass,
    make_admission, set_clock,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]

SEASON_PRICES = dict(
    resident_pass_price_cents=15000,
    non_resident_pass_price_cents=25000,
    resident_daily_price_cents=800,
    non_resident_daily_price_cents=1200,
)


def _setup_two_holders(clock="2026-07-10T14:00:00Z"):
    facility = make_facility(max_bather_capacity=200, lap_lane_count=6)
    season = make_season(facility["id"], **SEASON_PRICES)
    p = make_pass_holder(
        full_name="Pat Resident", date_of_birth="1990-01-15T00:00:00Z",
        residency_status="RESIDENT",
    )
    q = make_pass_holder(
        full_name="Quinn NoPass", date_of_birth="1990-01-15T00:00:00Z",
        residency_status="RESIDENT",
    )
    season_pass = make_season_pass(p["id"], season["id"])
    set_clock(clock)
    return facility, season, p, q, season_pass


def test_pass_admission_charged_zero_vs_gate_price(api):
    """PRD §3.2: "A valid pass covers the day in full, so `charge_cents` is 0
    and no pricing math runs."
    PRD §3.2: "The base is `resident_daily_price_cents` for a `RESIDENT`
    holder or `non_resident_daily_price_cents` for a `NON_RESIDENT` holder."

    Design: Difficulty/dual_variant_calc/daily_admission_with_pass_vs_gate_price
    """
    facility, season, p, q, season_pass = _setup_two_holders()
    adm_p = validate_success(
        api.create_admission(
            {
                "facility_id": facility["id"],
                "pass_holder_id": p["id"],
                "season_pass_id": season_pass["id"],
                "admission_date": "2026-07-10T00:00:00Z",
            },
            GATE,
        ),
        expected_status=201,
    )
    adm_q = validate_success(
        api.create_admission(
            {
                "facility_id": facility["id"],
                "pass_holder_id": q["id"],
                "admission_date": "2026-07-10T00:00:00Z",
            },
            GATE,
        ),
        expected_status=201,
    )
    assert_admission(adm_p)
    assert_admission(adm_q)
    assert adm_p["charge_cents"] == 0, (
        f"Season-pass admission must be free, got {adm_p['charge_cents']}"
    )
    assert adm_q["charge_cents"] == 800, (
        f"Adult RESIDENT gate price must be the 800c base, "
        f"got {adm_q['charge_cents']}"
    )
    assert adm_p["charge_cents"] != adm_q["charge_cents"]


def test_gate_price_variant_applies_residency_base(api):
    """PRD §3.2: "When no pass is supplied, `charge_cents` is computed from
    the season's daily price book and the holder's profile. The base is
    `resident_daily_price_cents` for a `RESIDENT` holder or
    `non_resident_daily_price_cents` for a `NON_RESIDENT` holder."
    PRD §3.2: "`ADULT` patrons pay the base unchanged."

    Design: Difficulty/dual_variant_calc/daily_admission_with_pass_vs_gate_price
    """
    facility = make_facility(max_bather_capacity=200, lap_lane_count=6)
    make_season(facility["id"], **SEASON_PRICES)
    nonresident = make_pass_holder(
        date_of_birth="1990-01-15T00:00:00Z", residency_status="NON_RESIDENT"
    )
    set_clock("2026-07-10T14:00:00Z")
    adm = validate_success(
        api.create_admission(
            {
                "facility_id": facility["id"],
                "pass_holder_id": nonresident["id"],
                "admission_date": "2026-07-10T00:00:00Z",
            },
            GATE,
        ),
        expected_status=201,
    )
    assert_admission(adm)
    assert adm["charge_cents"] == 1200, (
        f"Adult NON_RESIDENT gate price must be the 1200c base, "
        f"got {adm['charge_cents']}"
    )


def test_daily_price_senior_tier(api):
    """PRD §3.2: "`CHILD` patrons pay 60 percent of the base, `SENIOR` patrons
    pay 75 percent, and `ADULT` patrons pay the base unchanged. The final
    amount is rounded up to the next whole cent."
    PRD §3.2: "under 18 is `CHILD`, 18 through 61 is `ADULT`, and 62 or older
    is `SENIOR`."

    Design: Corner/calculations/daily_price_senior_tier
    """
    facility = make_facility()
    make_season(facility["id"], **SEASON_PRICES)
    senior = make_pass_holder(
        full_name="Sr", date_of_birth="1960-01-01T00:00:00Z",
        residency_status="RESIDENT",
    )
    set_clock("2026-07-01T10:00:00Z")
    adm = validate_success(
        api.create_admission(
            {
                "facility_id": facility["id"],
                "pass_holder_id": senior["id"],
                "admission_date": "2026-07-01T00:00:00Z",
            },
            GATE,
        ),
        expected_status=201,
    )
    assert_admission(adm)
    # ceil(800 * 0.75) = 600
    assert adm["charge_cents"] == 600, (
        f"SENIOR RESIDENT price must be ceil(800*0.75)=600, "
        f"got {adm['charge_cents']}"
    )


def test_daily_price_child_nonresident(api):
    """PRD §3.2: "`CHILD` patrons pay 60 percent of the base, `SENIOR` patrons
    pay 75 percent, and `ADULT` patrons pay the base unchanged. The final
    amount is rounded up to the next whole cent."
    PRD §3.2: "The base is `resident_daily_price_cents` for a `RESIDENT`
    holder or `non_resident_daily_price_cents` for a `NON_RESIDENT` holder."

    Design: Corner/calculations/daily_price_child_nonresident
    """
    facility = make_facility()
    make_season(facility["id"], **SEASON_PRICES)
    child = make_pass_holder(
        full_name="Kid", date_of_birth="2016-01-01T00:00:00Z",
        residency_status="NON_RESIDENT",
    )
    set_clock("2026-07-01T10:00:00Z")
    adm = validate_success(
        api.create_admission(
            {
                "facility_id": facility["id"],
                "pass_holder_id": child["id"],
                "admission_date": "2026-07-01T00:00:00Z",
            },
            GATE,
        ),
        expected_status=201,
    )
    assert_admission(adm)
    # ceil(1200 * 0.60) = 720
    assert adm["charge_cents"] == 720, (
        f"CHILD NON_RESIDENT price must be ceil(1200*0.60)=720, "
        f"got {adm['charge_cents']}"
    )
