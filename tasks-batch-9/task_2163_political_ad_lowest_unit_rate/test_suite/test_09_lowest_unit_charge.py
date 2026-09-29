"""Lowest-unit-charge determinations: the two variants, the window, and the reprice."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    air_spot,
    assert_luc_determination,
    assert_rebate_entry,
    charge_order,
    classify_candidate_advertiser,
    classify_issue_advertiser,
    create_determination,
    create_election,
    create_order,
    create_rate_class,
    create_station,
    hourly_spots,
    list_file_entries,
    list_rebates,
    luc_determination_payload,
    read_election,
    read_order,
    read_spot,
    read_station,
    set_clock,
    setup_candidate_order,
    submit_order,
    accept_order,
    add_spot,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER_BETA = TEST_USERS["officer_beta_headers"]

EARLY_NEWS = {
    "class_code": "RC-EN",
    "daypart": "EARLY_NEWS",
    "preemptible": True,
    "preemption_priority": 2,
    "posted_rate_cents": 100000,
}
MORNING = {
    "class_code": "RC-AM",
    "daypart": "MORNING",
    "preemptible": True,
    "preemption_priority": 3,
    "posted_rate_cents": 12345,
}


def _issue_order_with_spots(station, rate_class, election, advertiser, spots, charge):
    order = create_order(
        station["id"],
        advertiser["id"],
        rate_class["id"],
        payment_terms="PREPAY",
        sponsorship_disclosure_text="PAID FOR BY " + advertiser["legal_name"],
        election_id=election["id"],
    )
    rows = [add_spot(order["id"], advertiser["id"], **spot) for spot in spots]
    submit_order(order["id"], advertiser["id"])
    order = accept_order(order["id"])
    if charge is not None:
        order = charge_order(order["id"], advertiser["id"], charge)
    return order, rows


def _dual_variant_scenario():
    """Five never-aired discounted spots against one aired undiscounted spot."""
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WKPX-TV",
        licensee_name="Palmetto Broadcasting LLC",
        market_code="DMA-518",
        political_file_posting_deadline_hours=24,
        daily_political_seconds_cap=300,
        eo_parity_basis="SPOT_COUNT",
    )
    election = create_election(station["id"], election_type="PRIMARY", election_date="2026-09-15")
    rate_class = create_rate_class(station["id"], **EARLY_NEWS)

    empire = classify_issue_advertiser(
        station["id"], legal_name="Empire Growth Fund", election_id=election["id"]
    )
    coastal = classify_issue_advertiser(
        station["id"], legal_name="Coastal Water Alliance", election_id=election["id"]
    )

    empire_order, _empire_spots = _issue_order_with_spots(
        station,
        rate_class,
        election,
        empire,
        hourly_spots(5, air_date="2026-08-21", prefix="EN-A"),
        475000,
    )
    coastal_order, coastal_spots = _issue_order_with_spots(
        station,
        rate_class,
        election,
        coastal,
        hourly_spots(1, air_date="2026-08-10", prefix="EN-B"),
        100000,
    )

    set_clock("2026-08-10T12:00:00Z")
    air_spot(coastal_spots[0]["id"])

    return {
        "station": station,
        "election": election,
        "rate_class": rate_class,
        "empire_order": empire_order,
        "coastal_order": coastal_order,
        "coastal_spots": coastal_spots,
    }


def test_provisional_variant_counts_merely_scheduled_spots_on_accepted_orders(api):
    """PRD §3.7: "The `PROVISIONAL` variant admits spots that are `SCHEDULED` or
    `AIRED`, on orders that are `ACCEPTED`, `SUSPENDED`, `RUNNING` or `COMPLETED`."
    PRD §3.7: "If the candidate set is non-empty, `luc_cents` is the smallest
    `unit_equivalent_rate_cents` among the candidates, `basis` reads
    `LOWEST_QUALIFYING_SPOT`, and `qualifying_spot_count` is the size of the candidate
    set."

    Design: Difficulty/dual_variant_calc/luc_provisional_vs_final_diverge_on_same_rate_class
    """
    scenario = _dual_variant_scenario()

    provisional = create_determination(
        scenario["election"]["id"], scenario["rate_class"]["id"], "PROVISIONAL"
    )
    assert_luc_determination(provisional)

    assert provisional["luc_cents"] == 95000, (
        "the five discounted, never-aired spots drag the provisional figure down"
    )
    assert provisional["qualifying_spot_count"] == 6
    assert provisional["basis"] == "LOWEST_QUALIFYING_SPOT"
    assert provisional["repriced_spot_count"] == 0
    assert provisional["rebate_total_cents"] == 0
    assert read_order(scenario["empire_order"]["id"])["gross_charge_cents"] == 475000


def test_final_variant_counts_only_aired_spots_and_diverges_from_the_provisional(api):
    """PRD §3.7: "The `FINAL` variant is computed after the window has closed and admits
    only spots that actually reached `AIRED`, on orders that reached `RUNNING` or
    `COMPLETED`. The same data therefore yields a different figure, and the final figure
    is the one that carries retroactive force."
    PRD §3.7: "A `PROVISIONAL` determination stops there. Its `repriced_spot_count` and
    `rebate_total_cents` are always zero, because a provisional figure caps only the
    spots on the order that triggered it and never reaches back across the election."

    Design: Difficulty/dual_variant_calc/luc_provisional_vs_final_diverge_on_same_rate_class
    """
    scenario = _dual_variant_scenario()

    provisional = create_determination(
        scenario["election"]["id"], scenario["rate_class"]["id"], "PROVISIONAL"
    )
    final = create_determination(
        scenario["election"]["id"], scenario["rate_class"]["id"], "FINAL"
    )
    assert_luc_determination(final)

    assert final["luc_cents"] == 100000, "only the single aired spot qualifies"
    assert final["qualifying_spot_count"] == 1
    assert final["basis"] == "LOWEST_QUALIFYING_SPOT"
    assert final["repriced_spot_count"] == 0, "both buyers are issue advertisers"
    assert final["luc_cents"] != provisional["luc_cents"], (
        "the identical spot population yields different figures under the two variants"
    )


def test_window_membership_is_inclusive_of_the_window_start_date(api):
    """PRD §3.2: "Both endpoints are inclusive, and this matters in practice: a spot
    whose air date falls exactly on `window_start_date` is inside the window, while a
    spot one day earlier is outside it."
    PRD §3.7: "The `basis_spot_id` names the candidate attaining that minimum; when
    several candidates tie at the minimum, the winner is the one with the earliest
    `created_at`, and if that still ties, the earliest `air_date`, and if that still
    ties, the smallest `start_offset_seconds`."
    PRD §3.7: "The recorded determination copies the election's `station_id` and
    `election_id`, snapshots the election's `window_start_date` and `window_end_date` as
    they stood at computation time, stamps `computed_at` with the logical clock, and is
    created with `status` `ACTIVE`."

    Design: Corner/calculations/luc_includes_a_spot_airing_exactly_on_window_start_date_and_excludes_the_day_before
    """
    set_clock("2026-07-25T09:00:00Z")
    station = create_station(
        call_sign="WWIN-TV",
        licensee_name="Window Edge Media",
        market_code="DMA-114",
        political_file_posting_deadline_hours=24,
        daily_political_seconds_cap=300,
    )
    election = create_election(station["id"], election_type="PRIMARY", election_date="2026-09-15")
    assert election["window_start_date"] == "2026-08-01"

    rate_class = create_rate_class(station["id"], **EARLY_NEWS)
    advertiser = classify_issue_advertiser(
        station["id"], legal_name="Empire Growth Fund", election_id=election["id"]
    )

    _before_order, before_spots = _issue_order_with_spots(
        station,
        rate_class,
        election,
        advertiser,
        [
            {
                "air_date": "2026-07-31",
                "start_offset_seconds": 0,
                "duration_seconds": 30,
                "program_code": "EN-B",
            }
        ],
        None,
    )
    _edge_order, edge_spots = _issue_order_with_spots(
        station,
        rate_class,
        election,
        advertiser,
        [
            {
                "air_date": "2026-08-01",
                "start_offset_seconds": 0,
                "duration_seconds": 30,
                "program_code": "EN-E",
            }
        ],
        None,
    )

    determination = create_determination(election["id"], rate_class["id"], "PROVISIONAL")

    assert determination["qualifying_spot_count"] == 1
    assert determination["luc_cents"] == 100000
    assert determination["basis"] == "LOWEST_QUALIFYING_SPOT"
    assert determination["basis_spot_id"] == edge_spots[0]["id"]
    assert determination["basis_spot_id"] != before_spots[0]["id"]
    assert determination["window_start_date"] == "2026-08-01"
    assert determination["window_end_date"] == "2026-09-15"


def test_determination_falls_back_to_the_card_unit_rate_when_nothing_qualifies(api):
    """PRD §3.7: "If the candidate set comes out empty, the determination falls back to
    the rate card. Its `luc_cents` becomes the card unit rate for the class —
    `posted_rate_cents` multiplied by that class's daypart multiplier, rounded half up
    to whole cents — its `basis` reads `POSTED_RATE_FALLBACK`, its `basis_spot_id` is
    null, and its `qualifying_spot_count` is zero."
    PRD §3.3: "`MORNING` multiplies by 0.60, `DAYTIME` by 0.45, and `LATE_NIGHT` by
    0.35."

    Design: Corner/calculations/luc_falls_back_to_the_card_unit_rate_when_no_spot_qualifies
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WFBK-TV", licensee_name="Fallback Broadcasting", market_code="DMA-115"
    )
    election = create_election(station["id"], election_type="PRIMARY", election_date="2026-09-15")
    rate_class = create_rate_class(station["id"], **MORNING)

    response = api.create_luc_determination(
        election["id"],
        luc_determination_payload(rate_class["id"], "FINAL", election["version"]),
        OFFICER_BETA,
    )
    determination = validate_success(response, 201)
    assert_luc_determination(determination)

    assert determination["luc_cents"] == 7407, "12345 * 0.60 rounds half up to 7407"
    assert determination["basis"] == "POSTED_RATE_FALLBACK"
    assert determination["qualifying_spot_count"] == 0
    assert determination["basis_spot_id"] is None
    assert determination["repriced_spot_count"] == 0
    assert determination["rebate_total_cents"] == 0
    assert determination["status"] == "ACTIVE"


def test_second_determination_supersedes_the_prior_active_row_for_that_variant(api):
    """PRD §3.7: "Creating a determination for an election, rate class and variant that
    already has an active determination moves that earlier one `ACTIVE → SUPERSEDED`;
    superseding is the only way a determination leaves `ACTIVE`, and it never edits the
    superseded figures."
    PRD §2.4: "Most resources additionally carry an `updated_at` timestamp in the same
    format and an integer `version` that starts at 1 on creation and increments by
    exactly 1 on every mutation of that resource; `updated_at` is refreshed to the
    logical clock on each such mutation."

    Design: Corner/endpoints/luc_determination_supersedes_the_prior_active_row_for_the_same_variant
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WSUP-TV", licensee_name="Supersede Broadcasting", market_code="DMA-136"
    )
    election = create_election(station["id"], election_type="PRIMARY", election_date="2026-09-15")
    assert election["version"] == 1, "version starts at 1 on creation"
    rate_class = create_rate_class(station["id"], **MORNING)

    first = create_determination(election["id"], rate_class["id"], "PROVISIONAL")
    second = create_determination(election["id"], rate_class["id"], "PROVISIONAL")

    assert validate_success(api.get_luc_determination(first["id"], ADMIN))["status"] == "SUPERSEDED"
    assert validate_success(api.get_luc_determination(second["id"], ADMIN))["status"] == "ACTIVE"
    assert second["luc_cents"] == 7407

    active, active_meta = validate_paginated(
        api.list_luc_determinations(
            ADMIN, params={"election_id": election["id"], "status": "ACTIVE"}
        )
    )
    assert active_meta["total_count"] == 1
    assert active[0]["id"] == second["id"]

    every, every_meta = validate_paginated(
        api.list_luc_determinations(ADMIN, params={"election_id": election["id"]})
    )
    assert every_meta["total_count"] == 2
    assert [row["id"] for row in every] == [first["id"], second["id"]]


def test_determination_carrying_a_stale_election_version_is_refused(api):
    """PRD §2.6: "Such a request must carry `expected_election_version`, a non-optional
    field holding the `version` of the target `Election` as the client last read it. If
    that value does not equal the election's current `version`, the request is rejected
    with `ERR_STALE_ELECTION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_election_version_rejects_the_luc_determination_create
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WOCC-TV", licensee_name="Occ Guard Broadcasting", market_code="DMA-143"
    )
    election = create_election(station["id"], election_type="PRIMARY", election_date="2026-09-15")
    rate_class = create_rate_class(station["id"], **MORNING)

    first = create_determination(election["id"], rate_class["id"], "PROVISIONAL")
    current_version = read_election(election["id"])["version"]

    validate_error(
        api.create_luc_determination(
            election["id"],
            luc_determination_payload(rate_class["id"], "FINAL", current_version + 999),
            OFFICER_BETA,
        ),
        ApiErrorId.ERR_STALE_ELECTION_VERSION,
    )

    assert validate_success(api.get_luc_determination(first["id"], ADMIN))["status"] == "ACTIVE"
    _rows, meta = validate_paginated(
        api.list_luc_determinations(ADMIN, params={"election_id": election["id"]})
    )
    assert meta["total_count"] == 1, "the refused create writes no determination row"


def _final_reprice_scenario():
    """A candidate spot charged above the final figure, alongside a cheaper aired flight."""
    built = setup_candidate_order(
        call_sign="WCAS-TV",
        market_code="DMA-507",
        station_overrides={
            "licensee_name": "Cascade Licensee LLC",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        rate_class_overrides=EARLY_NEWS,
        spots=hourly_spots(1, prefix="EN-C"),
        charge_amount_cents=100000,
    )
    station, election, rate_class = built["station"], built["election"], built["rate_class"]

    empire = classify_issue_advertiser(
        station["id"], legal_name="Empire Growth Fund", election_id=election["id"]
    )
    issue_order, issue_spots = _issue_order_with_spots(
        station,
        rate_class,
        election,
        empire,
        hourly_spots(5, air_date="2026-08-21", prefix="EN-I"),
        475000,
    )

    set_clock("2026-08-21T12:00:00Z")
    for spot in issue_spots:
        air_spot(spot["id"])

    built["issue_order"] = read_order(issue_order["id"])
    built["issue_spots"] = issue_spots
    return built


def test_final_determination_reprices_the_candidate_spot_and_writes_the_rebate(api):
    """PRD §3.7: "The first hop reprices the spot: its `charged_rate_cents` becomes the
    determination's `luc_cents` multiplied by the spot's `duration_seconds`, divided by
    thirty, rounded half up; its `unit_equivalent_rate_cents` becomes the
    determination's `luc_cents` exactly; its `luc_cap_cents` records that same figure;
    and `luc_capped` becomes true."
    PRD §3.7: "The third hop, caused by the second, compares `paid_cents` minus
    `refunded_cents` minus the new `net_due_cents` against the order's existing
    `rebate_total_cents`, and where the former exceeds the latter, writes one rebate
    ledger entry naming this order, naming this determination as its
    `luc_determination_id`, carrying `reason` `LUC_FINAL_REPRICE` and an `amount_cents`
    equal to the excess alone; it then refreshes the order's `rebate_total_cents` to the
    new figure and moves the settlement dimension `PAID → REFUND_DUE`, with an order
    already in `REFUND_DUE` staying there and accruing the entry."

    Design: Difficulty/transitive_cascade/final_determination_reprice_cascades_spot_order_rebate_file_entry
    """
    scenario = _final_reprice_scenario()
    candidate_order = scenario["order"]
    candidate_spot = scenario["spots"][0]

    determination = create_determination(
        scenario["election"]["id"], scenario["rate_class"]["id"], "FINAL"
    )
    assert determination["luc_cents"] == 95000
    assert determination["qualifying_spot_count"] == 5
    assert determination["repriced_spot_count"] == 1
    assert determination["rebate_total_cents"] == 5000

    repriced = read_spot(candidate_spot["id"])
    assert repriced["charged_rate_cents"] == 95000
    assert repriced["unit_equivalent_rate_cents"] == 95000
    assert repriced["luc_cap_cents"] == 95000
    assert repriced["luc_capped"] is True

    refreshed = read_order(candidate_order["id"])
    assert refreshed["gross_charge_cents"] == 95000
    assert refreshed["net_due_cents"] == 95000
    assert refreshed["payment_status"] == "REFUND_DUE"
    assert refreshed["rebate_total_cents"] == 5000

    entries = list_rebates(order_id=candidate_order["id"])
    assert len(entries) == 1
    assert_rebate_entry(entries[0])
    assert entries[0]["amount_cents"] == 5000
    assert entries[0]["reason"] == "LUC_FINAL_REPRICE"
    assert entries[0]["luc_determination_id"] == determination["id"]


def test_final_reprice_files_a_rate_adjustment_entry_and_lifts_the_pending_count(api):
    """PRD §3.7: "The fourth hop, caused by the third, files a public political file
    entry of `event_type` `RATE_ADJUSTMENT` against the order in `PENDING` posting state
    and increments the station's `pending_file_entry_count` by one."
    PRD §3.7: "Spots belonging to issue advertisers are never targets: the lowest unit
    charge is a candidate entitlement and nothing else."

    Design: Difficulty/transitive_cascade/final_determination_reprice_cascades_spot_order_rebate_file_entry
    """
    scenario = _final_reprice_scenario()
    candidate_order, station = scenario["order"], scenario["station"]
    issue_order = scenario["issue_order"]

    create_determination(scenario["election"]["id"], scenario["rate_class"]["id"], "FINAL")

    entries = list_file_entries(order_id=candidate_order["id"])
    assert [entry["event_type"] for entry in entries] == [
        "ORDER_ACCEPTED",
        "RATE_ADJUSTMENT",
    ]
    assert entries[1]["posting_status"] == "PENDING"

    assert read_station(station["id"])["pending_file_entry_count"] == 3

    untouched = read_order(issue_order["id"])
    assert untouched["gross_charge_cents"] == 475000, (
        "the issue advertiser's flight is never repriced"
    )
    assert untouched["payment_status"] == "PAID"
