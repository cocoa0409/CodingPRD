"""Inclusive edges: the volume tier, the scored-contract denominator, the attrition floor."""

from test_helpers import (
    ApiClient,
    QualificationStatus,
    ShowStatus,
    SpaceContractStatus,
    factories as f,
    fixtures as fx,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

Q1000 = f.booth_payload("Q1000", 20, 50, location_class="CORNER",
                        premium_zone="MAIN_AISLE", max_height_ft=16)
R999 = f.booth_payload("R999", 27, 37, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)


def _tier_edge_env(client: ApiClient) -> dict:
    """One 1000 sqft booth and one 999 sqft booth, one exhibitor for each."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [Q1000, R999])
    env["big_buyer"] = fx.exhibitor(client, "Nordic Furnishings",
                                    consecutive_years=6)
    env["small_buyer"] = fx.exhibitor(client, "Harbor Ceramics",
                                      consecutive_years=2)
    return env


def test_exactly_one_thousand_square_feet_earns_the_five_percent_tier(
    client: ApiClient,
):
    """
    The volume tier read at its inclusive lower edge.

    "From that total the system selects a `volume_tier_pct`, and the thresholds are
    inclusive at the bottom: 12 percent at 4000 square feet or more, 8 percent at
    2000 or more, 5 percent at 1000 or more, and 0 percent below 1000. Exactly 1000
    square feet therefore earns 5 percent, which is why a well-advised exhibitor
    buys the thousandth foot."

    Design: Difficulty/boundary_precision_check/volume_tier_at_exactly_1000_sqft_undercuts_999_sqft
    """
    env = _tier_edge_env(client)
    booth = env["booth_by_number"]["Q1000"]
    assert booth["area_sqft"] == 1000

    contract = fx.offered_contract(
        client, env["show"]["id"], env["big_buyer"]["id"], 1000,
        [booth["id"]], premium_placement_requested=True,
    )
    assert contract["offered_net_sqft"] == 1000
    assert contract["volume_tier_pct"] == 5
    assert contract["space_fee_cents"] == 3696165
    assert contract["min_deposit_cents"] == 924041


def test_nine_hundred_and_ninety_nine_square_feet_costs_more_than_a_thousand(
    client: ApiClient,
):
    """
    One square foot below the edge earns nothing, so the smaller booth is dearer.

    "Because the volume tier is a step function of the summed area rather than of
    any individual line, the same one thousand square feet can legitimately cost
    less than nine hundred and ninety-nine."  "That exact gross line, carrying full
    precision, is then reduced by the total discount — multiplied by one hundred
    less the total discount percentage, divided by one hundred — and the *result of
    that reduction* is rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/volume_tier_at_exactly_1000_sqft_undercuts_999_sqft
    """
    env = _tier_edge_env(client)
    big = fx.offered_contract(
        client, env["show"]["id"], env["big_buyer"]["id"], 1000,
        [env["booth_by_number"]["Q1000"]["id"]], premium_placement_requested=True,
    )
    small_booth = env["booth_by_number"]["R999"]
    assert small_booth["area_sqft"] == 999

    small = fx.offered_contract(
        client, env["show"]["id"], env["small_buyer"]["id"], 999,
        [small_booth["id"]], premium_placement_requested=True,
    )
    assert small["volume_tier_pct"] == 0
    assert small["space_fee_cents"] == 3886809
    assert small["min_deposit_cents"] == 971702
    assert small["space_fee_cents"] > big["space_fee_cents"]


SCAN_CLOCK = "2027-03-05T10:00:00Z"
LEAD_BOOTHS = [
    f.booth_payload("A100", 20, 20, location_class="CORNER",
                    premium_zone="MAIN_AISLE", max_height_ft=16),
    f.inline_booth_payload("B200", 20, 20),
    f.inline_booth_payload("C300", 10, 20),
    f.inline_booth_payload("SPARE9", 20, 20),
]
REGISTRATIONS = [
    dict(category="BUYER", company_name="Delta Retail Group",
         job_title="VP Procurement", purchasing_authority="DECISION_MAKER",
         annual_spend_band="OVER_1M", email="r1@delta.example"),
    dict(category="BUYER", company_name="Sunset Analytics", job_title="Analyst",
         purchasing_authority="RECOMMENDER", annual_spend_band="K50_250K",
         email="r2@sunset.example"),
    dict(category="VIP_BUYER", company_name="Northline Stores",
         job_title="Head of Category", purchasing_authority="DECISION_MAKER",
         annual_spend_band="K250K_1M", email="r3@northline.example"),
    dict(category="BUYER", company_name="Tiny Corner Shop", job_title="Intern",
         purchasing_authority="NONE", annual_spend_band="UNDER_50K",
         email="r4@tiny.example"),
    dict(category="PRESS", company_name="Trade Weekly", job_title="Reporter",
         purchasing_authority="NONE", annual_spend_band="UNDER_50K",
         email="r5@tradeweekly.example"),
]


def _lead_report_env(client: ApiClient) -> dict:
    """
    Three signed contracts, five badges, and scans arranged so that one contract
    scanned four badges, one scanned a single unqualified badge, and one scanned
    nothing at all.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, LEAD_BOOTHS,
                            vc_overrides={"committed_net_sqft_per_year": 900})
    show_id = env["show"]["id"]
    booths = env["booth_by_number"]

    plan = [
        ("Nordic Furnishings", 6, "A100", 400),
        ("Harbor Ceramics", 2, "B200", 400),
        ("Alder Textiles", 1, "C300", 200),
    ]
    env["contracts"] = []
    for legal_name, years, booth_number, sqft in plan:
        exhibitor = fx.exhibitor(client, legal_name, consecutive_years=years)
        env["contracts"].append(
            fx.signed_contract(client, show_id, exhibitor["id"], sqft,
                               [booths[booth_number]["id"]])
        )

    fx.transition(client, show_id, ShowStatus.SELLING)
    env["registrations"] = [
        fx.registration(client, show_id, fx.REGISTRANT_HEADERS, **payload)
        for payload in REGISTRATIONS
    ]
    fx.transition(client, show_id, ShowStatus.ON_SITE)
    fx.set_clock(client, SCAN_CLOCK)

    r1, r2, r3, _r4, r5 = env["registrations"]
    busy, quiet = env["contracts"][0], env["contracts"][1]
    for registration, minute in ((r1, "05"), (r3, "10"), (r5, "15"), (r2, "20")):
        fx.lead_scan(client, busy["id"], registration["id"],
                     f"2027-03-05T10:{minute}:00Z")
    fx.lead_scan(client, quiet["id"], r2["id"], "2027-03-05T11:00:00Z")

    env["show"] = fx.transition(client, show_id, ShowStatus.CLOSED)
    return env


def _report(client: ApiClient, show_id: str) -> dict:
    return validate_success(client.get_post_show_report(show_id, fx.DIRECTOR_HEADERS))


def test_a_contract_with_no_scans_reports_a_line_but_no_percentage(
    client: ApiClient,
):
    """
    Three lines, one of them scoreless: the scored set has only two members.

    "A signed exhibitor who scanned nothing still appears in `exhibitor_lines`, with
    `lead_count` and `exhibitor_lead_quality_pct` both zero, but is excluded from the
    index's denominator, because including it would drag every diligent exhibitor's
    number toward zero."

    Design: Difficulty/boundary_precision_check/zero_scan_contract_leaves_the_lead_quality_denominator_at_one_scan
    """
    env = _lead_report_env(client)
    report = _report(client, env["show"]["id"])

    lines = report["exhibitor_lines"]
    assert len(lines) == 3
    assert lines[0]["lead_count"] == 4
    assert lines[0]["qualified_lead_count"] == 3
    assert lines[0]["exhibitor_lead_quality_pct"] == 75
    assert lines[1]["lead_count"] == 1
    assert lines[1]["qualified_lead_count"] == 0
    assert lines[1]["exhibitor_lead_quality_pct"] == 0
    assert lines[2]["lead_count"] == 0
    assert lines[2]["exhibitor_lead_quality_pct"] == 0

    assert report["total_lead_scans"] == 5
    assert report["scored_contract_count"] == 2


def test_the_index_averages_the_two_scored_contracts_and_rounds_half_up(
    client: ApiClient,
):
    """
    Thirty-seven and a half percent, rounded once at the end of the second pass.

    "The index is zero when that set is empty, and otherwise the sum of the
    already-rounded `exhibitor_lead_quality_pct` values over the scored contracts,
    divided by `scored_contract_count`, and that mean rounded half up."  "The
    `attendance_quality_index` is zero when nobody attended, and otherwise one
    hundred times `qualified_attended` divided by `attended_registrations`, rounded
    half up to an integer percent."

    Design: Difficulty/boundary_precision_check/zero_scan_contract_leaves_the_lead_quality_denominator_at_one_scan
    """
    env = _lead_report_env(client)
    scores = [
        (85, QualificationStatus.QUALIFIED),
        (40, QualificationStatus.WAITLISTED),
        (86, QualificationStatus.QUALIFIED),
        (5, QualificationStatus.REJECTED),
        (0, QualificationStatus.QUALIFIED),
    ]
    for registration, (score, status) in zip(env["registrations"], scores):
        row = fx.get_success_data(
            client.get_registration(registration["id"], fx.DIRECTOR_HEADERS)
        )
        assert row["qualification_score"] == score
        assert row["qualification_status"] == status

    report = _report(client, env["show"]["id"])
    assert report["total_registrations"] == 5
    assert report["qualified_registrations"] == 3
    assert report["attended_registrations"] == 4
    assert report["qualified_attended"] == 3
    assert report["attendance_quality_index"] == 75
    assert report["show_lead_quality_index"] == 38
    assert report["attrition_shortfall_sqft"] == 0
    assert report["attrition_settlement_cents"] == 0


ATTRITION_TERMS = {"committed_net_sqft_per_year": 1647, "attrition_allowance_pct": 15}
P1000 = f.inline_booth_payload("P1000", 20, 50)
P400 = f.inline_booth_payload("P400", 20, 20)
Q999 = f.inline_booth_payload("Q999", 27, 37)
Q400 = f.inline_booth_payload("Q400", 20, 20)


def _attrition_env(client: ApiClient) -> dict:
    """
    Two editions of one agreement closing against a forgiven floor of 1400 square
    feet: the first assigns exactly 1400, the second one foot less.
    """
    fx.set_clock(client, CLOCK)
    on_the_floor = fx.published_show(
        client, [P1000, P400], vc_overrides=ATTRITION_TERMS,
        name="National Buyers Expo 2027",
    )
    one_short = fx.published_show(
        client, [Q999, Q400], venue_contract=on_the_floor["venue_contract"],
        name="National Buyers Expo 2028", edition_year=2028,
        move_in_start="2028-03-01", event_start="2028-03-05",
        event_end="2028-03-07", move_out_end="2028-03-09",
    )
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)

    for env, sqft, numbers in ((on_the_floor, 1400, ("P1000", "P400")),
                               (one_short, 1399, ("Q999", "Q400"))):
        env["contract"] = fx.signed_contract(
            client, env["show"]["id"], exhibitor["id"], sqft,
            [env["booth_by_number"][n]["id"] for n in numbers],
        )
        fx.transition(client, env["show"]["id"], ShowStatus.SELLING)
        fx.transition(client, env["show"]["id"], ShowStatus.ON_SITE)
        env["show"] = fx.transition(client, env["show"]["id"], ShowStatus.CLOSED)

    return {"on_the_floor": on_the_floor, "one_short": one_short,
            "exhibitor": exhibitor}


def test_meeting_the_forgiven_floor_exactly_settles_at_nothing(client: ApiClient):
    """
    Actual performance of 1400 against a forgiven floor of 1400.

    "The forgiven allowance is that commitment multiplied by
    `attrition_allowance_pct` divided by one hundred, floored to whole square feet —
    floored, which favours the venue by shrinking the forgiveness."  "The floor is
    inclusive: actual performance exactly equal to the forgiven floor owes nothing at
    all, while one square foot below it owes a full 1800 cents."

    Design: Difficulty/boundary_precision_check/attrition_floor_is_inclusive_to_the_last_square_foot
    """
    env = _attrition_env(client)["on_the_floor"]
    contract = fx.read_contract(client, env["contract"]["id"])
    assert contract["assigned_net_sqft"] == 1400
    assert contract["space_fee_cents"] == 4355750
    assert contract["min_deposit_cents"] == 1088938
    assert contract["status"] == SpaceContractStatus.CLOSED_OUT

    show = fx.read_show(client, env["show"]["id"])
    assert show["status"] == ShowStatus.CLOSED
    assert show["attrition_shortfall_sqft"] == 0
    assert show["attrition_settlement_cents"] == 0


def test_one_square_foot_short_of_the_floor_settles_at_eighteen_hundred(
    client: ApiClient,
):
    """
    The same agreement's next edition, one square foot below the same floor.

    "The `attrition_shortfall_sqft` is the forgiven floor minus actual performance,
    or zero when actual performance meets or exceeds it. The `attrition_settlement_cents`
    is that shortfall multiplied by eighteen dollars — 1800 cents — per square foot."

    Design: Difficulty/boundary_precision_check/attrition_floor_is_inclusive_to_the_last_square_foot
    """
    env = _attrition_env(client)["one_short"]
    contract = fx.read_contract(client, env["contract"]["id"])
    assert contract["assigned_net_sqft"] == 1399
    assert contract["space_fee_cents"] == 4352639
    assert contract["min_deposit_cents"] == 1088160
    assert contract["status"] == SpaceContractStatus.CLOSED_OUT

    show = fx.read_show(client, env["show"]["id"])
    assert show["status"] == ShowStatus.CLOSED
    assert show["attrition_shortfall_sqft"] == 1
    assert show["attrition_settlement_cents"] == 1800
