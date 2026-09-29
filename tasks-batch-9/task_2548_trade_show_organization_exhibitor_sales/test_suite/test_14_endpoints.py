"""
Three endpoints whose whole behaviour lives in the relationships they rewrite:
the all-or-nothing combine, the lead scan that links two sides of one edition,
and the rebook that carries a streak into next year.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BoothStatus,
    QualificationStatus,
    ShowStatus,
    SpaceContractStatus,
    assert_lead_scan,
    factories as f,
    fixtures as fx,
    make_floor_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)
D010 = f.inline_booth_payload("D010", 10, 10)
F100 = f.booth_payload("F100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)

FLOOR = make_floor_manager_headers("u_fm_1")

SHOW_2028 = {
    "edition_year": 2028,
    "move_in_start": "2028-03-01",
    "event_start": "2028-03-05",
    "event_end": "2028-03-07",
    "move_out_end": "2028-03-09",
    "base_rate_cents_per_sqft": 3400,
}


def test_a_combine_set_that_names_its_own_survivor_is_refused_wholesale(
    client: ApiClient,
):
    """
    The illegal set takes its legal sibling down with it; the retried pair moves
    three hundred square feet into the survivor and creates none.

    "a set that names a booth of another show or lists the survivor as its own
    child is refused with `ERR_INVALID_COMBINE_SET`"  "On success each child moves
    `AVAILABLE → MERGED` with its `combined_parent_booth_id` pointing at the
    survivor, and each child's `area_sqft` is added to the survivor's `area_sqft`."
    "As §2.9 states, a combine leaves `sellable_booth_sqft` unchanged — area is
    conserved, never created."

    Design: Corner/endpoints/combine_is_all_or_nothing_and_conserves_floor_area
    """
    fx.set_clock(client, CLOCK)
    env = fx.show_with_booths(client, [A100, C050, D010])
    show_id = env["show"]["id"]
    booths = env["booth_by_number"]
    survivor_id = booths["A100"]["id"]
    c050_id = booths["C050"]["id"]
    d010_id = booths["D010"]["id"]
    assert env["show"]["sellable_booth_sqft"] == 700

    pinned_version = fx.show_version(client, show_id)
    validate_error(
        client.combine_booths(
            survivor_id, f.combine_payload(pinned_version, [survivor_id, c050_id]),
            FLOOR,
        ),
        ApiErrorId.INVALID_COMBINE_SET,
        422,
    )

    assert fx.read_booth(client, survivor_id)["area_sqft"] == 400
    untouched = fx.read_booth(client, c050_id)
    assert untouched["status"] == BoothStatus.AVAILABLE
    assert untouched["combined_parent_booth_id"] is None
    assert fx.show_version(client, show_id) == pinned_version

    survivor = validate_success(
        client.combine_booths(
            survivor_id, f.combine_payload(pinned_version, [c050_id, d010_id]),
            FLOOR,
        )
    )
    assert survivor["area_sqft"] == 700
    assert survivor["status"] == BoothStatus.AVAILABLE

    for child_id in (c050_id, d010_id):
        child = fx.read_booth(client, child_id)
        assert child["status"] == BoothStatus.MERGED
        assert child["combined_parent_booth_id"] == survivor_id

    show = fx.read_show(client, show_id)
    assert show["sellable_booth_sqft"] == 700
    assert show["available_net_sqft"] == 700

    rows, meta = validate_paginated(
        client.list_booths(fx.DIRECTOR_HEADERS,
                           {"show_id": show_id,
                            "combined_parent_booth_id": survivor_id})
    )
    assert meta["total_count"] == 2
    assert sorted(row["booth_number"] for row in rows) == ["C050", "D010"]


ON_SITE_CLOCK = "2027-03-05T10:00:00Z"
UNKNOWN_REGISTRATION_ID = "00000000-0000-4000-8000-0000000000ff"


def _on_site_edition_with_badges(client: ApiClient) -> dict:
    """
    An `ON_SITE` 2027 edition carrying a signed hold and two qualified badges,
    beside a `SELLING` 2028 edition carrying a badge of its own.
    """
    fx.set_clock(client, CLOCK)
    this_year = fx.published_show(client, [A100])
    show_id = this_year["show"]["id"]
    next_year = fx.published_show(client, [F100],
                                  venue_contract=this_year["venue_contract"],
                                  **SHOW_2028)
    fx.transition(client, next_year["show"]["id"], ShowStatus.SELLING)

    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    contract = fx.signed_contract(client, show_id, nordic["id"], 400,
                                  [this_year["booth_by_number"]["A100"]["id"]],
                                  389070, premium_placement_requested=True)
    assert contract["status"] == SpaceContractStatus.SIGNED
    fx.transition(client, show_id, ShowStatus.SELLING)

    r1 = fx.registration(client, show_id, fx.REGISTRANT_HEADERS,
                         company_name="Delta Retail Group",
                         job_title="VP Procurement", email="r1@delta.example")
    r3 = fx.registration(client, show_id, fx.REGISTRANT_HEADERS,
                         company_name="Northway Wholesale",
                         job_title="Director of Buying",
                         email="r3@northway.example")
    r2 = fx.registration(client, next_year["show"]["id"], fx.REGISTRANT_HEADERS,
                         company_name="Foreign Edition Buyer", job_title="Owner",
                         email="r2@foreign.example")
    for badge in (r1, r2, r3):
        assert badge["qualification_status"] == QualificationStatus.QUALIFIED
        assert badge["lead_scan_count"] == 0

    fx.transition(client, show_id, ShowStatus.ON_SITE)
    fx.set_clock(client, ON_SITE_CLOCK)
    return {"show_id": show_id, "other_show_id": next_year["show"]["id"],
            "exhibitor": nordic, "contract": contract,
            "headers": fx.make_exhibitor_headers(nordic["id"]),
            "r1": r1, "r2": r2, "r3": r3}


def test_the_badge_scan_counts_once_and_the_replay_is_refused(client: ApiClient):
    """
    One scan links contract to badge and bumps the attendance counter; the second
    scan of the same pairing is refused and the counter does not move.

    "no scan may already exist pairing this same contract with this same
    registration, or the request is refused with `ERR_DUPLICATE_LEAD_SCAN`"  "A
    successful scan increments the registration's `lead_scan_count` and its
    `version`."  "Scans are listable both from the exhibitor's side, per contract,
    and from the attendee's side, per registration."

    Design: Corner/endpoints/a_lead_scan_links_a_contract_to_a_registration_of_the_same_show
    """
    env = _on_site_edition_with_badges(client)
    contract_id = env["contract"]["id"]
    r1 = env["r1"]

    scan = validate_success(
        client.create_lead_scan(
            contract_id, f.lead_scan_payload(r1["id"], "2027-03-05T10:05:00Z"),
            env["headers"],
        ),
        201,
    )
    assert_lead_scan(scan)
    assert scan["space_contract_id"] == contract_id
    assert scan["registration_id"] == r1["id"]

    scanned = validate_success(client.get_registration(r1["id"], fx.DIRECTOR_HEADERS))
    assert scanned["lead_scan_count"] == 1
    assert scanned["version"] == r1["version"] + 1

    validate_error(
        client.create_lead_scan(
            contract_id, f.lead_scan_payload(r1["id"], "2027-03-05T14:00:00Z"),
            env["headers"],
        ),
        ApiErrorId.DUPLICATE_LEAD_SCAN,
        409,
    )
    assert (
        validate_success(
            client.get_registration(r1["id"], fx.DIRECTOR_HEADERS)
        )["lead_scan_count"] == 1
    )

    per_contract, contract_meta = validate_paginated(
        client.list_contract_lead_scans(contract_id, env["headers"])
    )
    assert contract_meta["total_count"] == 1
    assert per_contract[0]["id"] == scan["id"]

    per_badge, badge_meta = validate_paginated(
        client.list_registration_lead_scans(r1["id"], fx.DIRECTOR_HEADERS)
    )
    assert badge_meta["total_count"] == 1
    assert per_badge[0]["id"] == scan["id"]


def test_a_foreign_badge_an_unknown_badge_and_a_late_scan_are_each_refused(
    client: ApiClient,
):
    """
    Three ways for the link to fail, each with its own error, and no counter moves.

    "its `show_id` must be the same show as the contract's, or the request is
    refused with `ERR_REGISTRATION_SHOW_MISMATCH`"  "registration
    (`ERR_REGISTRATION_NOT_FOUND`)"  "the date of `scanned_at` must fall inside the
    closed interval from the show's `move_in_start` through its `move_out_end`, or
    the request is refused with `ERR_LEAD_SCAN_OUTSIDE_SHOW_WINDOW`"

    Design: Corner/endpoints/a_lead_scan_links_a_contract_to_a_registration_of_the_same_show
    """
    env = _on_site_edition_with_badges(client)
    contract_id = env["contract"]["id"]
    headers = env["headers"]

    validate_error(
        client.create_lead_scan(
            contract_id,
            f.lead_scan_payload(env["r2"]["id"], "2027-03-05T10:10:00Z"),
            headers,
        ),
        ApiErrorId.REGISTRATION_SHOW_MISMATCH,
        422,
    )
    validate_error(
        client.create_lead_scan(
            contract_id,
            f.lead_scan_payload(UNKNOWN_REGISTRATION_ID, "2027-03-05T10:15:00Z"),
            headers,
        ),
        ApiErrorId.REGISTRATION_NOT_FOUND,
        404,
    )
    validate_error(
        client.create_lead_scan(
            contract_id,
            f.lead_scan_payload(env["r3"]["id"], "2027-03-15T10:00:00Z"),
            headers,
        ),
        ApiErrorId.LEAD_SCAN_OUTSIDE_SHOW_WINDOW,
        422,
    )

    for badge_id in (env["r2"]["id"], env["r3"]["id"]):
        row = validate_success(client.get_registration(badge_id, fx.DIRECTOR_HEADERS))
        assert row["lead_scan_count"] == 0

    rows, meta = validate_paginated(
        client.list_contract_lead_scans(contract_id, headers)
    )
    assert meta["total_count"] == 0
    assert rows == []


G100 = f.booth_payload("G100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
SUMMER_2027 = {
    "name": "National Buyers Expo Summer",
    "edition_year": 2027,
    "move_in_start": "2027-06-01",
    "event_start": "2027-06-05",
    "event_end": "2027-06-07",
    "move_out_end": "2027-06-09",
}
POST_SHOW_CLOCK = "2027-03-10T00:00:00Z"


def test_rebooking_a_closed_out_hold_carries_the_streak_and_the_bonus_forward(
    client: ApiClient,
):
    """
    A target edition that is not strictly later is refused; the 2028 edition takes
    the rebook and the exhibitor's streak and bonus follow it.

    "Naming the source show itself, an edition under a different venue agreement,
    an edition whose `edition_year` is not strictly later, or an edition that is no
    longer open for sale all fail with `ERR_REBOOK_TARGET_INVALID`."  "A successful
    rebook creates a fresh space contract in `OFFERED` on the target edition with
    `rebooked_from_space_contract_id` set to the source contract, moves the chosen
    target-edition booths `AVAILABLE → HELD`"  "the new contract earns the
    five-point rebook bonus inside its point contribution, which flows straight
    into the exhibitor's provisional standing, and the exhibitor's
    `consecutive_years` is incremented by one"

    Design: Corner/endpoints/rebooking_is_allowed_only_from_a_closed_out_contract_into_a_later_edition
    """
    fx.set_clock(client, CLOCK)
    this_year = fx.published_show(client, [A100])
    agreement = this_year["venue_contract"]
    show_id = this_year["show"]["id"]
    next_year = fx.published_show(client, [F100], venue_contract=agreement,
                                  **SHOW_2028)
    other_show_id = next_year["show"]["id"]
    f100_id = next_year["booth_by_number"]["F100"]["id"]
    same_year = fx.published_show(client, [G100], venue_contract=agreement,
                                  **SUMMER_2027)

    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    source = fx.signed_contract(client, show_id, nordic["id"], 400,
                                [this_year["booth_by_number"]["A100"]["id"]],
                                389070, premium_placement_requested=True)

    fx.transition(client, show_id, ShowStatus.SELLING)
    fx.transition(client, show_id, ShowStatus.ON_SITE)
    fx.transition(client, show_id, ShowStatus.CLOSED)
    fx.set_clock(client, POST_SHOW_CLOCK)

    closed_out = fx.read_contract(client, source["id"])
    assert closed_out["status"] == SpaceContractStatus.CLOSED_OUT
    assert closed_out["assigned_net_sqft"] == 400

    validate_error(
        client.rebook(
            source["id"],
            f.rebook_payload(same_year["show"]["id"],
                             fx.show_version(client, same_year["show"]["id"]), 400,
                             premium_placement_requested=True),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.REBOOK_TARGET_INVALID,
        422,
    )
    _, refused_meta = validate_paginated(
        client.list_space_contracts(fx.DIRECTOR_HEADERS,
                                    {"show_id": same_year["show"]["id"]})
    )
    assert refused_meta["total_count"] == 0

    pinned_version = fx.show_version(client, other_show_id)
    rebooked = validate_success(
        client.rebook(
            source["id"],
            f.rebook_payload(other_show_id, pinned_version, 400,
                             premium_placement_requested=True,
                             booth_ids=[f100_id]),
            fx.SALES_REP_HEADERS,
        ),
        201,
    )
    assert rebooked["show_id"] == other_show_id
    assert rebooked["status"] == SpaceContractStatus.OFFERED
    assert rebooked["rebooked_from_space_contract_id"] == source["id"]

    f100 = fx.read_booth(client, f100_id)
    assert f100["status"] == BoothStatus.HELD
    assert f100["space_contract_id"] == rebooked["id"]
    target_show = fx.read_show(client, other_show_id)
    assert target_show["held_net_sqft"] == 400
    assert target_show["version"] > pinned_version

    row = fx.read_exhibitor(client, nordic["id"])
    assert row["consecutive_years"] == 7
    assert row["provisional_priority_points"] == 13
    assert row["certified_priority_points"] == 8

    rows, meta = validate_paginated(
        client.list_space_contracts(
            fx.DIRECTOR_HEADERS,
            {"rebooked_from_space_contract_id": source["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == rebooked["id"]
