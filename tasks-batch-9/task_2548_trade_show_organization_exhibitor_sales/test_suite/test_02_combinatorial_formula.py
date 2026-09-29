"""Multiplicative pricing grids, the bundle tier's input, and two-pass rounding."""

import pytest

from test_helpers import (
    ApiClient,
    BoothStatus,
    DealStatus,
    QualificationStatus,
    ShowStatus,
    SpaceContractStatus,
    factories as f,
    fixtures as fx,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
B200 = f.booth_payload("B200", 30, 20, location_class="ISLAND",
                       premium_zone="ENTRANCE", max_height_ft=20)
C050 = f.inline_booth_payload("C050", 10, 20)


def _priced_floor(client: ApiClient) -> dict:
    """A published edition with three booths and two exhibitors, nothing sold."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, B200, C050])
    env["nordic"] = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    env["harbor"] = fx.exhibitor(client, "Harbor Ceramics", consecutive_years=2)
    return env


def test_thousand_sqft_contract_prices_both_lines_at_the_volume_tier(
    client: ApiClient,
):
    """
    A 400 sqft CORNER/MAIN_AISLE booth and a 600 sqft ISLAND/ENTRANCE booth sold
    together, so the contract-wide total selects the five percent tier.

    "A booth's exact gross line is its `area_sqft` multiplied by the show's
    `base_rate_cents_per_sqft`, multiplied by a location multiplier — 1.00 for
    `INLINE`, 1.10 for `CORNER`, 1.20 for `PENINSULA`, 1.30 for `ISLAND` — and
    multiplied by a zone multiplier: 1.00 for `NONE`, 1.08 for `MAIN_AISLE`, 1.15
    for `ENTRANCE`, and 1.05 for `FOOD_COURT`."  "The contract's
    `min_deposit_cents` is then 25 percent of `space_fee_cents`, rounded half up."

    Design: Difficulty/combinatorial_formula/booth_space_fee_three_input_multiplicative_grid_with_volume_tier
    """
    env = _priced_floor(client)
    booths = env["booth_by_number"]

    contract = fx.offered_contract(
        client, env["show"]["id"], env["nordic"]["id"], 1000,
        [booths["A100"]["id"], booths["B200"]["id"]],
        premium_placement_requested=True,
    )

    assert contract["offered_net_sqft"] == 1000
    assert contract["volume_tier_pct"] == pytest.approx(5, abs=0.01)
    assert contract["space_fee_cents"] == 4269257
    # "Step four selects `bundle_discount_pct` from that **pre-discount** subtotal:
    # ... two and a half percent when it is at least two million cents": the
    # 4,269,257-cent subtotal clears the two-million band even with no sponsorship
    # attached, so the invoice sits 106,731 cents below the space fee.
    assert contract["sponsorship_attached_cents"] == 0
    assert contract["bundle_discount_pct"] == pytest.approx(2.5, abs=0.01)
    assert contract["bundle_discount_cents"] == 106731
    assert contract["invoice_total_cents"] == 4162526
    assert contract["min_deposit_cents"] == 1067314


def test_two_hundred_sqft_contract_falls_below_every_volume_tier(client: ApiClient):
    """
    A 200 sqft INLINE/NONE booth sold on its own, where both multipliers are 1.00
    and the volume tier is zero.

    "From that total the system selects a `volume_tier_pct`, and the thresholds are
    inclusive at the bottom: 12 percent at 4000 square feet or more, 8 percent at
    2000 or more, 5 percent at 1000 or more, and 0 percent below 1000."

    Design: Difficulty/combinatorial_formula/booth_space_fee_three_input_multiplicative_grid_with_volume_tier
    """
    env = _priced_floor(client)
    booths = env["booth_by_number"]
    show_id = env["show"]["id"]

    fx.offered_contract(
        client, show_id, env["nordic"]["id"], 1000,
        [booths["A100"]["id"], booths["B200"]["id"]],
        premium_placement_requested=True,
    )
    small = fx.offered_contract(
        client, show_id, env["harbor"]["id"], 200, [booths["C050"]["id"]],
        premium_placement_requested=False,
    )

    assert small["offered_net_sqft"] == 200
    assert small["volume_tier_pct"] == pytest.approx(0, abs=0.01)
    assert small["space_fee_cents"] == 655000
    assert small["min_deposit_cents"] == 163750

    for number in ("A100", "B200", "C050"):
        assert (
            fx.read_booth(client, booths[number]["id"])["status"] == BoothStatus.HELD
        )
    assert fx.read_show(client, show_id)["held_net_sqft"] == 1200


def _bundle_setup(client: ApiClient) -> dict:
    """One offered 400 sqft contract plus a proposed sponsorship on the same show."""
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)
    show_id = env["show"]["id"]
    booth = validate_success(
        client.create_booth(show_id, A100, fx.FLOOR_MANAGER_HEADERS), 201
    )
    package = fx.sponsorship_package(
        client, show_id, package_code="ENTRY_ARCH", list_price_cents=500000,
        price_floor_cents=400000, inventory_total=2,
        exclusivity_category="OUTDOOR_FURNITURE",
        obligation_codes=["LOGO_ON_ENTRY_ARCH", "BAG_INSERT"],
        priority_point_value=12,
    )
    env["show"] = validate_success(
        client.publish_floor_plan(show_id, fx.DIRECTOR_HEADERS)
    )
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    contract = fx.offered_contract(
        client, show_id, exhibitor["id"], 400, [booth["id"]],
        premium_placement_requested=True,
    )
    deal = fx.proposed_deal(client, package["id"], exhibitor["id"], 463720)
    env.update({"booth": booth, "package": package, "exhibitor": exhibitor,
                "contract": contract, "deal": deal})
    return env


def test_bundle_tier_is_selected_from_the_pre_discount_subtotal(client: ApiClient):
    """
    A 1,556,280 cent space fee plus 463,720 cents of signed sponsorship makes a
    2,020,000 cent subtotal, which is what earns the two-and-a-half percent tier.

    "Step four selects `bundle_discount_pct` from that **pre-discount** subtotal: 4
    percent when the subtotal is at least five million cents (fifty thousand
    dollars), two and a half percent when it is at least two million cents (twenty
    thousand dollars), and 0 percent below that."  "`invoice_total_cents` may
    legitimately end up below the threshold that earned the discount, and
    re-selecting the tier from `invoice_total_cents` is wrong."

    Design: Difficulty/combinatorial_formula/invoice_bundle_tier_reads_the_pre_discount_subtotal
    """
    env = _bundle_setup(client)

    validate_success(
        client.sign_sponsorship_deal(
            env["deal"]["id"], fx.make_director_headers("u_dir_1")
        )
    )

    contract = fx.read_contract(client, env["contract"]["id"])
    assert contract["space_fee_cents"] == 1556280
    assert contract["sponsorship_attached_cents"] == 463720
    assert contract["bundle_discount_pct"] == pytest.approx(2.5, abs=0.01)
    assert contract["bundle_discount_cents"] == 50500
    assert contract["invoice_total_cents"] == 1969500


def test_the_bundle_reprice_leaves_the_contract_offered_and_the_deposit_on_the_fee(
    client: ApiClient,
):
    """
    Signing the sponsorship reprices the invoice without moving the contract's own
    status, and the minimum deposit still tracks the space fee alone.

    "Every recomputation of the space fee reprices the invoice, and so does the
    signing or cancellation of any sponsorship deal for the same exhibitor on the
    same show."  "the obligations are materialised: one fulfillment obligation is
    created per entry of the package's `obligation_codes`"

    Design: Difficulty/combinatorial_formula/invoice_bundle_tier_reads_the_pre_discount_subtotal
    """
    env = _bundle_setup(client)

    deal = validate_success(
        client.sign_sponsorship_deal(
            env["deal"]["id"], fx.make_director_headers("u_dir_1")
        )
    )
    assert deal["deal_status"] == DealStatus.SIGNED
    assert deal["obligation_count"] == 2

    contract = fx.read_contract(client, env["contract"]["id"])
    assert contract["status"] == SpaceContractStatus.OFFERED
    assert contract["min_deposit_cents"] == 389070


def _report_setup(client: ApiClient) -> dict:
    """
    Three 200 sqft contracts on one edition, three scored registrations, two scans
    on the first contract, one on the second and none on the third, then a close.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(
        client,
        [f.inline_booth_payload("P100", 10, 20),
         f.inline_booth_payload("P200", 10, 20),
         f.inline_booth_payload("P300", 10, 20)],
        vc_overrides={"committed_net_sqft_per_year": 600,
                      "attrition_allowance_pct": 0},
    )
    show_id = env["show"]["id"]
    booths = env["booth_by_number"]
    names = [("Nordic Furnishings", 6, "P100"), ("Harbor Ceramics", 2, "P200"),
             ("Summit Textiles", 1, "P300")]
    contracts = []
    for legal_name, years, booth_number in names:
        exhibitor = fx.exhibitor(client, legal_name, consecutive_years=years)
        offered = fx.offered_contract(
            client, show_id, exhibitor["id"], 200, [booths[booth_number]["id"]],
            premium_placement_requested=False,
        )
        contracts.append(fx.sign_contract(client, offered, 200000))

    registrations = [
        fx.registration(
            client, show_id, fx.REGISTRANT_HEADERS, category="BUYER",
            company_name="Alpine Retail Group", job_title="Director of Purchasing",
            purchasing_authority="DECISION_MAKER", annual_spend_band="OVER_1M",
            email="r1@alpine.example",
        ),
        fx.registration(
            client, show_id, fx.REGISTRANT_HEADERS, category="BUYER",
            company_name="Coastal Gift Shop", job_title="Intern",
            purchasing_authority="NONE", annual_spend_band="UNDER_50K",
            email="r2@coastal.example",
        ),
        fx.registration(
            client, show_id, fx.REGISTRANT_HEADERS, category="VIP_BUYER",
            company_name="Metro Home Stores", job_title="Senior Buyer",
            purchasing_authority="RECOMMENDER", annual_spend_band="K250K_1M",
            email="r3@metro.example",
        ),
    ]

    fx.transition(client, show_id, ShowStatus.SELLING)
    fx.transition(client, show_id, ShowStatus.ON_SITE)
    fx.set_clock(client, "2027-03-05T10:00:00Z")
    fx.lead_scan(client, contracts[0]["id"], registrations[0]["id"],
                 "2027-03-05T10:05:00Z")
    fx.lead_scan(client, contracts[0]["id"], registrations[1]["id"],
                 "2027-03-05T10:06:00Z")
    fx.lead_scan(client, contracts[1]["id"], registrations[2]["id"],
                 "2027-03-05T10:07:00Z")
    env["show"] = fx.transition(client, show_id, ShowStatus.CLOSED)
    env["contracts"] = contracts
    env["registrations"] = registrations
    return env


def test_lead_quality_index_averages_the_already_rounded_contract_percentages(
    client: ApiClient,
):
    """
    Two scored contracts at 50 and 100 percent average to 75; pooling the same
    three scans would report 67.

    "The index is zero when that set is empty, and otherwise the sum of the
    already-rounded `exhibitor_lead_quality_pct` values over the scored contracts,
    divided by `scored_contract_count`, and that mean rounded half up. Each
    contract's percentage is rounded first and the mean is taken of the rounded
    percentages: pooling every scan in the show and dividing total qualified scans
    by total scans yields a different number and is wrong."

    Design: Difficulty/combinatorial_formula/post_show_lead_quality_rounds_per_contract_then_averages
    """
    env = _report_setup(client)

    report = validate_success(
        client.get_post_show_report(env["show"]["id"], fx.DIRECTOR_HEADERS)
    )
    assert report["total_lead_scans"] == 3
    assert report["scored_contract_count"] == 2
    assert report["show_lead_quality_index"] == 75

    lines = report["exhibitor_lines"]
    assert len(lines) == 3
    assert lines[0]["lead_count"] == 2
    assert lines[0]["exhibitor_lead_quality_pct"] == 50
    assert lines[1]["lead_count"] == 1
    assert lines[1]["exhibitor_lead_quality_pct"] == 100


def test_the_report_scores_attendance_and_excludes_the_unscanned_contract(
    client: ApiClient,
):
    """
    The attendance side of the same report, and the signed contract that scanned
    nothing.

    "The `attendance_quality_index` is zero when nobody attended, and otherwise one
    hundred times `qualified_attended` divided by `attended_registrations`, rounded
    half up to an integer percent."  "A signed exhibitor who scanned nothing still
    appears in `exhibitor_lines`, with `lead_count` and
    `exhibitor_lead_quality_pct` both zero, but is excluded from the index's
    denominator".

    Design: Difficulty/combinatorial_formula/post_show_lead_quality_rounds_per_contract_then_averages
    """
    env = _report_setup(client)
    r1, r2, r3 = env["registrations"]
    assert r1["qualification_score"] == 85
    assert r1["qualification_status"] == QualificationStatus.QUALIFIED
    assert r2["qualification_score"] == 5
    assert r2["qualification_status"] == QualificationStatus.REJECTED
    assert r3["qualification_score"] == 69
    assert r3["qualification_status"] == QualificationStatus.QUALIFIED

    report = validate_success(
        client.get_post_show_report(env["show"]["id"], fx.DIRECTOR_HEADERS)
    )
    assert report["total_registrations"] == 3
    assert report["qualified_registrations"] == 2
    assert report["attended_registrations"] == 3
    assert report["qualified_attended"] == 2
    assert report["attendance_quality_index"] == 67
    assert report["exhibitor_lines"][2]["lead_count"] == 0
    assert report["exhibitor_lines"][2]["exhibitor_lead_quality_pct"] == 0
    assert report["attrition_shortfall_sqft"] == 0
    assert report["attrition_settlement_cents"] == 0
