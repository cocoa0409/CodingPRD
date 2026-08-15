"""Delivery-contract fulfillment, over-delivery tolerance, amendment and
cancellation guards, and optimistic concurrency (PRD §2.8, §3.2, §3.4)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    assert_cwt,
    ApiErrorId,
    TEST_USERS,
    create_open_season,
    create_grower,
    create_contract,
    create_contract_lot,
    grade_lot,
    get_contract,
    get_lot,
    create_contract_payload,
)

MERCH = TEST_USERS["merchandiser_headers"]
SCALE = TEST_USERS["scale_operator_headers"]
LAB = TEST_USERS["quality_lab_tech_headers"]


def _contract_scenario(contracted_cwt=400.00, base_price=1500):
    season = create_open_season()
    grower = create_grower(season["id"])
    contract = create_contract(season["id"], grower["id"],
                               contracted_cwt=contracted_cwt,
                               base_price_cents_per_cwt=base_price)
    return season, grower, contract


# ---------------------------------------------------------------------------
# Boundary: fulfillment ratio landing exactly on 100%
# ---------------------------------------------------------------------------

def _filled_to_exactly_400():
    """Contract 400.00; lot 1 graded dry 338.24; lot 2 booked, not yet graded."""
    season, grower, contract = _contract_scenario()
    lot1 = create_contract_lot(season["id"], grower["id"], contract["id"],
                               gross_weight_lbs=48300, tare_weight_lbs=12000,
                               moisture_pct_handheld=18.0)
    grade_lot(lot1["id"], moisture_pct_official=18.5, foreign_matter_pct=0.4,
              damage_pct=0.4, broken_pct=2.0)
    mid = get_contract(contract["id"])
    lot2 = create_contract_lot(season["id"], grower["id"], contract["id"],
                               gross_weight_lbs=18176, tare_weight_lbs=12000,
                               scheduled_date="2026-08-11",
                               moisture_pct_handheld=13.0)
    return season, grower, contract, mid, lot2


def test_contract_exactly_fulfilled_at_100_percent(api):
    """PRD §3.2: "reaching or exceeding the contracted volume — an exact
    one-hundred-percent fill counts as fulfilled — moves it to `FULFILLED`, from
    `OPEN` or `PARTIALLY_FULFILLED` alike."
    PRD §3.2: "Each time a linked lot is graded, `fulfilled_cwt` is recomputed
    as the total dry weight of the contract's lots standing in `GRADED`,
    `BINNED`, or `SETTLED`"

    Design: Difficulty/boundary_precision_check/contract_exactly_fulfilled_at_100_percent
    """
    _, _, contract, mid, lot2 = _filled_to_exactly_400()
    assert mid["status"] == "PARTIALLY_FULFILLED"
    assert_cwt(mid["fulfilled_cwt"], 338.24, "fulfilled_cwt after first grading")

    graded2 = grade_lot(lot2["id"], moisture_pct_official=13.0)
    assert_cwt(graded2["dry_weight_cwt"], 61.76, "second lot dry weight")

    final = get_contract(contract["id"])
    assert_cwt(final["fulfilled_cwt"], 400.00, "fulfilled_cwt at exactly 100%")
    assert final["status"] == "FULFILLED"


def test_fulfilled_contract_refuses_further_bookings(api, scale_operator_headers):
    """PRD §3.3: "The named contract must stand in `OPEN` or
    `PARTIALLY_FULFILLED`; booking against a cancelled, fulfilled, or defaulted
    contract is refused with `ERR_CONTRACT_NOT_OPEN`."

    Design: Difficulty/boundary_precision_check/contract_exactly_fulfilled_at_100_percent
    """
    season, grower, contract, _, lot2 = _filled_to_exactly_400()
    grade_lot(lot2["id"], moisture_pct_official=13.0)  # -> FULFILLED at 400.00

    fresh = get_contract(contract["id"])
    resp = api.create_lot(
        {
            "season_id": season["id"],
            "grower_id": grower["id"],
            "variety": "LONG_GRAIN",
            "source": "CONTRACT",
            "contract_id": contract["id"],
            "expected_contract_version": fresh["version"],
            "gross_weight_lbs": 13000,
            "tare_weight_lbs": 12000,
            "scheduled_date": "2026-08-12",
            "moisture_pct_handheld": 13.0,
        },
        scale_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_OPEN)


# ---------------------------------------------------------------------------
# Corner: over-delivery tolerance, strict comparison
# ---------------------------------------------------------------------------

def test_overdelivery_tolerance_strict_comparison(api, quality_lab_tech_headers):
    """PRD §3.4: "if the contract's fulfilled volume before this grading plus
    the lot's new dry weight is strictly greater than one hundred and five
    percent of the contracted volume — the tolerance figure itself rounded
    half-up to 2 decimal places — the grading is refused for the whole lot with
    `ERR_OVERDELIVERY_BEYOND_TOLERANCE`."

    Design: Corner/calculations/overdelivery_tolerance_strict_comparison
    """
    season = create_open_season()
    grower = create_grower(season["id"])
    contract_x = create_contract(season["id"], grower["id"], contracted_cwt=100.00)
    contract_y = create_contract(season["id"], grower["id"], contracted_cwt=100.00)
    lot_x = create_contract_lot(season["id"], grower["id"], contract_x["id"],
                                gross_weight_lbs=22500, tare_weight_lbs=12000,
                                scheduled_date="2026-08-10")
    lot_y = create_contract_lot(season["id"], grower["id"], contract_y["id"],
                                gross_weight_lbs=22501, tare_weight_lbs=12000,
                                scheduled_date="2026-08-11")

    # Exactly 105.00 of 100.00 cwt: strict > not triggered, grading accepted.
    grade_payload = {
        "moisture_pct_official": 13.0, "foreign_matter_pct": 0.2,
        "damage_pct": 0.2, "broken_pct": 0.6,
    }
    gx = validate_success(
        api.grade_lot(lot_x["id"], grade_payload, quality_lab_tech_headers)
    )
    assert_cwt(gx["dry_weight_cwt"], 105.00, "lot X dry weight")
    assert gx["status"] == "GRADED"
    assert get_contract(contract_x["id"])["status"] == "FULFILLED"

    # 105.01 > 105.00: refused, and the lot is not partially graded.
    resp = api.grade_lot(lot_y["id"], grade_payload, quality_lab_tech_headers)
    validate_error(resp, ApiErrorId.ERR_OVERDELIVERY_BEYOND_TOLERANCE)
    assert get_contract(contract_y["id"])["status"] == "OPEN"
    assert get_lot(lot_y["id"])["status"] == "WEIGHED"


# ---------------------------------------------------------------------------
# Corner: rejecting a graded lot removes it from fulfillment
# ---------------------------------------------------------------------------

def test_fulfillment_excludes_rejected_lots(api, quality_lab_tech_headers):
    """PRD §3.4: "one rejected from `GRADED` has its dry weight removed from the
    contract's fulfilled tally, and the contract's status is re-derived from
    what remains, which may drop it from `FULFILLED` or `PARTIALLY_FULFILLED`
    back toward `OPEN`."

    Design: Corner/calculations/fulfillment_excludes_rejected_lots
    """
    season, grower, contract = _contract_scenario()
    lot = create_contract_lot(season["id"], grower["id"], contract["id"],
                              gross_weight_lbs=48300, tare_weight_lbs=12000,
                              moisture_pct_handheld=18.0)
    grade_lot(lot["id"], moisture_pct_official=18.5, foreign_matter_pct=0.4,
              damage_pct=0.4, broken_pct=2.0)
    mid = get_contract(contract["id"])
    assert mid["status"] == "PARTIALLY_FULFILLED"
    assert_cwt(mid["fulfilled_cwt"], 338.24, "fulfilled before rejection")

    validate_success(
        api.reject_lot(lot["id"], {"reject_reason": "weeviled load"},
                       quality_lab_tech_headers)
    )
    end = get_contract(contract["id"])
    assert end["status"] == "OPEN"
    assert_cwt(end["fulfilled_cwt"], 0, "REJECTED lots leave the input set")


# ---------------------------------------------------------------------------
# Corner: optimistic concurrency on contract delivery and amendment
# ---------------------------------------------------------------------------

def test_occ_contract_delivery_stale_version(api, scale_operator_headers):
    """PRD §2.8: "Creating a contract-sourced paddy lot requires the request to
    carry `expected_contract_version`, the contract `version` the client last
    observed. If the contract's version has since advanced — because another
    delivery was booked, another lot was graded against it, or the contract was
    amended — the create is rejected with `ERR_STALE_CONTRACT_VERSION`
    (HTTP 412), and the client must re-read the contract and retry."

    Design: Corner/cross_cutting_layers/occ_contract_delivery_stale_version
    """
    season, grower, contract = _contract_scenario()
    stale_version = contract["version"]  # 1

    first = validate_success(
        api.create_lot(
            {
                "season_id": season["id"], "grower_id": grower["id"],
                "variety": "LONG_GRAIN", "source": "CONTRACT",
                "contract_id": contract["id"],
                "expected_contract_version": stale_version,
                "gross_weight_lbs": 22000, "tare_weight_lbs": 12000,
                "scheduled_date": "2026-08-10", "moisture_pct_handheld": 13.0,
            },
            scale_operator_headers,
        ),
        expected_status=201,
    )
    assert first["status"] == "WEIGHED"

    # The first booking advanced the contract version; replaying v1 is stale.
    resp = api.create_lot(
        {
            "season_id": season["id"], "grower_id": grower["id"],
            "variety": "LONG_GRAIN", "source": "CONTRACT",
            "contract_id": contract["id"],
            "expected_contract_version": stale_version,
            "gross_weight_lbs": 22000, "tare_weight_lbs": 12000,
            "scheduled_date": "2026-08-11", "moisture_pct_handheld": 13.0,
        },
        scale_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION)

    fresh_version = get_contract(contract["id"])["version"]
    assert fresh_version == stale_version + 1
    retry = validate_success(
        api.create_lot(
            {
                "season_id": season["id"], "grower_id": grower["id"],
                "variety": "LONG_GRAIN", "source": "CONTRACT",
                "contract_id": contract["id"],
                "expected_contract_version": fresh_version,
                "gross_weight_lbs": 22000, "tare_weight_lbs": 12000,
                "scheduled_date": "2026-08-11", "moisture_pct_handheld": 13.0,
            },
            scale_operator_headers,
        ),
        expected_status=201,
    )
    assert retry["status"] == "WEIGHED"


def test_occ_contract_amend_stale_version(api, merchandiser_headers,
                                          scale_operator_headers):
    """PRD §2.8: "Amending a contract's price or volume likewise requires
    `expected_contract_version`. A mismatch with the contract's current
    `version` is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412); both
    amendments may be individually legitimate, but the second must re-read the
    contract first."
    PRD §3.2: "a successful amendment increments the contract's `version`."

    Design: Corner/cross_cutting_layers/occ_contract_amend_stale_version
    """
    season, grower, contract = _contract_scenario()
    create_contract_lot(season["id"], grower["id"], contract["id"])  # version -> 2

    resp = api.amend_contract(
        contract["id"],
        {"expected_contract_version": contract["version"],
         "base_price_cents_per_cwt": 1550},
        merchandiser_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION)

    fresh_version = get_contract(contract["id"])["version"]
    amended = validate_success(
        api.amend_contract(
            contract["id"],
            {"expected_contract_version": fresh_version,
             "base_price_cents_per_cwt": 1550},
            merchandiser_headers,
        )
    )
    assert amended["base_price_cents_per_cwt"] == 1550
    assert amended["version"] == fresh_version + 1


def test_contract_amend_blocked_after_fulfillment(api, merchandiser_headers):
    """PRD §3.2: "Amending `contracted_cwt`, `base_price_cents_per_cwt`, or
    `grade_adjustments` is permitted only while the contract's fulfilled volume
    is still zero — otherwise `ERR_CONTRACT_HAS_DELIVERIES`"
    PRD §3.2: "Cancelling a contract requires it to stand in `OPEN` or
    `PARTIALLY_FULFILLED` — any other status yields `ERR_CONTRACT_NOT_OPEN` —
    and likewise requires zero fulfilled volume, since settled grain cannot be
    un-delivered; a fulfilled-tainted cancel attempt meets
    `ERR_CONTRACT_HAS_DELIVERIES`."

    Design: Corner/cross_cutting_layers/contract_amend_blocked_after_fulfillment
    """
    season, grower, contract = _contract_scenario()
    lot = create_contract_lot(season["id"], grower["id"], contract["id"])
    grade_lot(lot["id"])  # dry 100.00 -> fulfilled_cwt 100.00

    current = get_contract(contract["id"])
    assert_cwt(current["fulfilled_cwt"], 100.00, "fulfilled after grading")

    resp = api.amend_contract(
        contract["id"],
        {"expected_contract_version": current["version"],
         "base_price_cents_per_cwt": 1550},
        merchandiser_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_HAS_DELIVERIES)

    resp = api.cancel_contract(contract["id"], merchandiser_headers)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_HAS_DELIVERIES)


def test_contract_create_missing_required_field(api, merchandiser_headers):
    """PRD §2.7: "Required fields are present, types and enum values are valid,
    `tare_weight_lbs` is less than `gross_weight_lbs`, a packaging run's
    `ends_at` is later than its `starts_at`, a contract-sourced lot carries its
    `contract_id` and `expected_contract_version` and matches the contract's
    grower and variety, a spot lot carries `spot_price_cents_per_cwt`, and a
    fumigation record's `started_at` is not in the future relative to the season
    clock (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/contract_create_missing_required_field
    """
    season, grower, _ = _contract_scenario()
    payload = create_contract_payload(season["id"], grower["id"])
    del payload["contracted_cwt"]
    resp = api.create_contract(payload, merchandiser_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
