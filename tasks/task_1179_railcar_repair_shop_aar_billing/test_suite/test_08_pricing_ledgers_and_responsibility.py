"""Estimate/final field families, party ledger posting, and responsibility."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    authorize_current_wo, build_work_order, make_car_owner_rep_headers,
    make_handling_line_rep_headers, scenario_completed_wo,
    scenario_submitted_brc, setup_shop_ctx, submit_current_wo,
    validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]


def test_estimate_fields_frozen_after_finalization():
    """PRD §2.7: "the line's `estimate_labor_cents` is the entry's
    `standard_labor_hours` multiplied by the entry's shop
    `labor_rate_cents_per_hour`, rounded half up to whole cents."
    PRD §2.7: "The line's `final_labor_cents` is its `actual_labor_hours`
    multiplied by that rate, rounded half up to whole cents".

    Design: Corner/calculations/estimate_fields_frozen_after_finalization
    """
    ctx = scenario_completed_wo(actual_hours=2.0)
    line = validate_success(api_client.get_repair_line(ctx["wo_lines"][0]["id"], ADMIN))
    assert line["status"] == "FINALIZED"
    assert line["estimate_labor_cents"] == 13500, "estimate keeps the 1.5 standard-hours basis"
    assert line["final_labor_cents"] == 18000, "final uses the 2.0 actual-hours basis"
    assert line["estimate_total_cents"] == 13500
    assert line["final_total_cents"] == 18000


def test_car_owner_credit_watch_status_flip():
    """PRD §2.10: "A CarOwner whose `outstanding_balance_cents` rises strictly
    above the shop's `owner_watch_threshold_cents` — defaulting to one million
    cents — flips to `CREDIT_WATCH`; at or below the threshold the owner is
    `ACTIVE`."
    PRD §2.10: "At acceptance — manual or deemed — the owner's balance
    increases by the card's `owner_total_cents` minus the owner-responsible
    share of accepted counter-bill credits".

    Design: Corner/calculations/car_owner_credit_watch_status_flip
    """
    ctx = scenario_submitted_brc(
        actual_hours=2.0, shop_overrides={"owner_watch_threshold_cents": 10000},
        part={"part_number": "H-100", "unit_price_cents": 4500, "on_hand_qty": 10,
              "reorder_threshold": 2})
    resp_brc = api_client.accept_billing_repair_card(
        ctx["brc"]["id"], make_car_owner_rep_headers(ctx["owner"]["id"]))
    validate_success(resp_brc)
    owner = validate_success(api_client.get_car_owner(ctx["owner"]["id"], ADMIN))
    assert owner["outstanding_balance_cents"] == 22500, (
        "final 18000 labor + 4500 part posts in full with no counters")
    assert owner["status"] == "CREDIT_WATCH", "22500 is strictly above the 10000 threshold"


def test_handling_damage_line_requires_handling_line_authorizer():
    """PRD §2.8: "**Rule 1** — if the defect's `cause_code` is
    `HANDLING_DAMAGE`, the line belongs to the handling line:
    `responsible_party` is `HANDLING_LINE` and `owner_pct` is 0."
    PRD §2.1: "when it is `HANDLING_LINE`, the caller must be a
    `HandlingLineRep` whose `X-User-ID` equals the car's `handling_line_id`."
    PRD §2.1: "Any failure of these checks is rejected with
    `ERR_RESPONSIBILITY_MISMATCH` (403)."

    Design: Corner/validations/handling_damage_line_requires_handling_line_authorizer
    """
    ctx = setup_shop_ctx()
    add_price_entry(ctx, job_code="J-STRUCT-STR", description="Straighten side sill",
                    labor_rate_cents_per_hour=10000, mobile_labor_rate_cents_per_hour=12000,
                    standard_labor_hours=3.0, mobile_trip_surcharge_cents=20000,
                    mobile_eligible=True)
    add_car_with_inspection(
        ctx, car_number="6001",
        defects=[{"aar_defect_code": "AAR-3300", "defect_group": "STRUCTURAL",
                  "cause_code": "HANDLING_DAMAGE", "severity": "MAJOR",
                  "location": "side sill"}])
    build_work_order(ctx, lines=[{"job_code": "J-STRUCT-STR"}])
    wo = submit_current_wo(ctx)

    line = validate_success(api_client.get_repair_line(ctx["wo_lines"][0]["id"], ADMIN))
    assert line["responsible_party"] == "HANDLING_LINE"
    assert line["owner_pct"] == 0

    resp = api_client.authorize_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]},
        make_car_owner_rep_headers(ctx["owner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_RESPONSIBILITY_MISMATCH, expected_status=403)

    authorized = validate_success(api_client.authorize_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]},
        make_handling_line_rep_headers(ctx["line"]["id"])))
    assert authorized["auth_status"] == "AUTHORIZED", (
        "the rejected attempt did not consume the OCC version; the line rep's "
        "authorize with the same captured version succeeds")
