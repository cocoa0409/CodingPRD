"""Season lifecycle guards, list pagination envelope, and read-after-write
consistency (PRD §2.3, §2.4, §2.5, §3.1)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    assert_cwt,
    assert_bin_capacity_invariant,
    ApiErrorId,
    TEST_USERS,
    create_season,
    create_open_season,
    close_intake,
    create_grower,
    create_contract,
    create_bin,
    create_spot_lot,
    create_contract_lot,
    grade_lot,
    store_lot,
    create_draft_settlement,
    issue_provisional,
    begin_settlement_review,
    approve_settlement,
    pay_settlement,
    create_byproduct_order,
    setup_binned_contract_lots,
    settlement_reaching,
    get_contract,
    get_bin,
    create_season_payload,
)

ADMIN = TEST_USERS["mill_admin_headers"]
MERCH = TEST_USERS["merchandiser_headers"]
SCALE = TEST_USERS["scale_operator_headers"]


def test_season_create_ignores_client_clock(api):
    """PRD §2.4: "The clock starts at exactly `2026-08-01T00:00:00Z` when the
    season is created, advances only when a `MillAdmin` sets it to a supplied
    `to_iso8601` instant, and never falls back to wall-clock time."
    PRD §2.5: "starts at 1 when the resource is created and increments by one on
    every mutation".

    Design: Corner/entities/season_create_client_clock_input_ignored
    """
    payload = create_season_payload(current_clock_iso="2030-01-01T00:00:00Z")
    data = validate_success(api.create_season(payload, ADMIN), expected_status=201)

    assert data["current_clock_iso"].replace(".000Z", "Z") == "2026-08-01T00:00:00Z", (
        f"client-supplied clock must be ignored; got {data['current_clock_iso']!r}"
    )
    assert data["status"] == "SETUP"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]), "season id must be a bare UUID"


def test_grower_list_pagination_envelope(api, merchandiser_headers):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return."

    Design: Corner/entities/grower_list_pagination_envelope
    """
    season = create_season()
    create_grower(season["id"], farm_code="FARM-001", legal_name="Delta Farms")
    create_grower(season["id"], farm_code="FARM-002", legal_name="Bayou Grain")

    page1, meta1 = validate_paginated(
        api.list_growers(merchandiser_headers,
                         params={"season_id": season["id"], "limit": 1, "offset": 0})
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_growers(merchandiser_headers,
                         params={"season_id": season["id"], "limit": 1, "offset": 1})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert {page1[0]["farm_code"], page2[0]["farm_code"]} == {"FARM-001", "FARM-002"}


def test_season_review_reopen_and_open_guards(api, mill_admin_headers):
    """PRD §3.1: "Beginning settlement review (`INTAKE_CLOSED` →
    `SETTLEMENT_REVIEW`) is blocked with `ERR_UNRESOLVED_INTAKE_WORK` while any
    lot in the season still stands in `WEIGHED` or `GRADED`, while any drying
    run remains `PLANNED`, or while any mill run is `IN_PROCESS`."
    PRD §3.1: "invoking any season lifecycle action from a state that does not
    offer it is rejected with `ERR_INVALID_SEASON_STATE` (HTTP 409)."

    Design: Corner/state_machines/season_reopen_and_review_guards
    """
    season = create_open_season(name="S1")
    grower = create_grower(season["id"])
    lot = create_spot_lot(season["id"], grower["id"])
    grade_lot(lot["id"])  # stands GRADED, never stored
    close_intake(season["id"])

    resp = api.begin_settlement_review(season["id"], mill_admin_headers)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_INTAKE_WORK)

    reopened = validate_success(api.reopen_intake(season["id"], mill_admin_headers))
    assert reopened["status"] == "INTAKE_OPEN", (
        "reopen must be allowed while no settlement has advanced past draft"
    )

    resp = api.open_intake(season["id"], mill_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_SEASON_STATE)


def test_season_reopen_blocked_by_issued_settlement(api, mill_admin_headers):
    """PRD §3.1: "if any settlement stands in `PROVISIONAL_ISSUED`, `APPROVED`,
    or `PAID`, the reopen is refused with `ERR_SEASON_REOPEN_BLOCKED`."

    Design: Corner/state_machines/season_reopen_blocked_by_issued_settlement
    """
    season = create_open_season(name="S2")
    grower = create_grower(season["id"])
    bin_ = create_bin(season["id"])
    lot = create_spot_lot(season["id"], grower["id"])
    grade_lot(lot["id"])
    store_lot(lot["id"], bin_["id"])
    close_intake(season["id"])
    settlement = create_draft_settlement(season["id"], grower["id"])
    issue_provisional(settlement["id"])

    resp = api.reopen_intake(season["id"], mill_admin_headers)
    validate_error(resp, ApiErrorId.ERR_SEASON_REOPEN_BLOCKED)


def test_season_settle_guards_and_contract_default(api, mill_admin_headers, merchandiser_headers):
    """PRD §3.1: "Final settlement of the season (`SETTLEMENT_REVIEW` →
    `SETTLED`) is permitted only when every settlement in the season stands in
    `PAID` — otherwise `ERR_UNPAID_SETTLEMENTS_EXIST` — and when no byproduct
    sale order remains `OPEN` or `RESERVED` — otherwise
    `ERR_OPEN_BYPRODUCT_ORDERS`."
    PRD §3.1: "Settling the season carries a consequential cascade: every
    delivery contract still `OPEN` or `PARTIALLY_FULFILLED` whose fulfilled
    volume falls short of its contracted volume is automatically moved to
    `DEFAULTED`."

    Design: Corner/state_machines/season_settle_guards_and_contract_default
    """
    adjustments = {"US_NO_1": 0, "US_NO_2": -25, "US_NO_3": -60,
                   "US_NO_4": -110, "US_NO_5": -175, "SAMPLE": -300}
    scenario = setup_binned_contract_lots(
        [{"gross": 48300, "tare": 12000, "handheld": 18.0, "official": 18.5,
          "fm": 0.4, "dmg": 0.4, "brk": 2.0}],
        contracted_cwt=400.00, base_price_cents_per_cwt=1500,
        grade_adjustments=adjustments, farm_code="FARM-001",
        legal_name="Delta Farms",
    )
    season_id = scenario["season"]["id"]
    # Settlement approved but unpaid; no byproduct orders yet.
    settlement = settlement_reaching(scenario, "approved")

    resp = api.settle_season(season_id, mill_admin_headers)
    validate_error(resp, ApiErrorId.ERR_UNPAID_SETTLEMENTS_EXIST)

    pay_settlement(settlement["id"])
    order = create_byproduct_order(season_id, product="HULL", quantity_cwt=1.00,
                                   price_cents_per_cwt=200, buyer_name="BeddingCo")
    resp = api.settle_season(season_id, mill_admin_headers)
    validate_error(resp, ApiErrorId.ERR_OPEN_BYPRODUCT_ORDERS)

    validate_success(api.cancel_byproduct_order(order["id"], merchandiser_headers))
    settled = validate_success(api.settle_season(season_id, mill_admin_headers))
    assert settled["status"] == "SETTLED"

    contract = get_contract(scenario["contract"]["id"])
    assert contract["status"] == "DEFAULTED", (
        f"under-delivered contract (338.24 of 400.00) must be DEFAULTED, "
        f"got {contract['status']}"
    )


def test_immediate_consistency_after_write(api, scale_operator_headers):
    """PRD §2.5: "Cascaded mutations — a bin touched by a drying run, a grower
    touched by a settlement payment, a contract touched by a lot grading — each
    independently refresh `updated_at` and increment `version` on the affected
    resource, and every such cascade is visible in the same response that
    triggered it."
    PRD §3.3: "From the two scale weights the system derives the net wet weight:
    the difference between gross and tare in pounds, divided by one hundred to
    express it in hundredweight, rounded half-up to 2 decimal places and stored
    as `net_wet_cwt`."

    Design: Corner/consistency/immediate_consistency_after_write
    """
    season = create_open_season()
    grower = create_grower(season["id"])
    contract = create_contract(season["id"], grower["id"], contracted_cwt=400.00,
                               base_price_cents_per_cwt=1500)
    bin_ = create_bin(season["id"])

    lot = validate_success(
        api.create_lot(
            {
                "season_id": season["id"],
                "grower_id": grower["id"],
                "variety": "LONG_GRAIN",
                "source": "CONTRACT",
                "contract_id": contract["id"],
                "expected_contract_version": contract["version"],
                "gross_weight_lbs": 48300,
                "tare_weight_lbs": 12000,
                "scheduled_date": "2026-08-10",
                "moisture_pct_handheld": 18.0,
            },
            scale_operator_headers,
        ),
        expected_status=201,
    )
    assert_cwt(lot["net_wet_cwt"], 363.00, "net_wet_cwt in create response")
    assert_cwt(lot["provisional_dry_weight_cwt"], 340.32,
               "provisional_dry_weight_cwt in create response")

    grade_lot(lot["id"], moisture_pct_official=13.0)
    contract_after = get_contract(contract["id"])
    assert_cwt(contract_after["fulfilled_cwt"], 363.00, "fulfilled_cwt right after grade")
    assert contract_after["status"] == "PARTIALLY_FULFILLED"

    store_lot(lot["id"], bin_["id"])
    bin_after = get_bin(bin_["id"])
    assert_cwt(bin_after["stock_cwt"], 363.00, "stock_cwt right after store")
    assert_bin_capacity_invariant(bin_after)
