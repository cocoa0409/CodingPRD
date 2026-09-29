"""
The validation ladder read one rung at a time: six independent rules each firing
their own error, the ladder's own priority order, and the aggregate rules that
only a collection can break.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BoothStatus,
    DealStatus,
    FloorPosture,
    LocationClass,
    PremiumZone,
    PriorityTier,
    ShowStatus,
    SpaceContractStatus,
    VenueContractStatus,
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

FLOOR = make_floor_manager_headers("u_fm_1")

HALL_B_RATES = {
    "hall_code": "HALL_B",
    "hall_gross_sqft": 120000,
    "max_booth_height_ft": 16,
    "committed_net_sqft_per_year": 600,
    "attrition_allowance_pct": 10,
    "advance_order_discount_pct": 15,
    "labor_rate_cents_per_hour": 9000,
    "electrical_rate_cents_per_amp": 4000,
    "material_handling_rate_cents_per_cwt": 8000,
}


def _read_venue_contract(client: ApiClient, vc_id: str) -> dict:
    return validate_success(client.get_venue_contract(vc_id, fx.DIRECTOR_HEADERS))


def _two_agreements(client: ApiClient) -> dict:
    """One countersigned HALL_A agreement, one HALL_B agreement left in DRAFT."""
    fx.set_clock(client, CLOCK)
    executed = fx.executed_venue_contract(client)
    draft = fx.draft_venue_contract(client, **HALL_B_RATES)
    assert executed["status"] == VenueContractStatus.EXECUTED
    assert draft["status"] == VenueContractStatus.DRAFT
    return {"executed": executed, "draft": draft}


def test_three_rules_of_the_design_phase_each_report_their_own_error(
    client: ApiClient,
):
    """
    An uncountersigned agreement, a booth taller than the rigging and a repeated
    booth number: three unrelated rules, three distinct error ids.

    "No show may be created under an agreement that is not `EXECUTED`; an attempt
    reports `ERR_VENUE_CONTRACT_NOT_EXECUTED`."  "each booth declares its own
    `max_height_ft`, the tallest structure permitted inside it, which must be at
    least one foot and may not exceed the hall's `max_booth_height_ft`; a booth
    that reaches above the rigging is refused with `ERR_BOOTH_HEIGHT_LIMIT`."
    "Each booth carries a `booth_number` ... which must be unique among the
    booths of the same show; a collision is `ERR_DUPLICATE_BOOTH_NUMBER`."

    Design: Corner/validations/six_independent_validation_rules_each_return_their_own_error
    """
    agreements = _two_agreements(client)
    env = fx.show_with_booths(client, [A100, C050],
                              venue_contract=agreements["executed"])
    show_id = env["show"]["id"]

    validate_error(
        client.create_show(
            f.show_payload(agreements["draft"]["id"], name="Hall B Expo",
                           edition_year=2028, move_in_start="2028-03-01",
                           event_start="2028-03-05", event_end="2028-03-07",
                           move_out_end="2028-03-09", gross_sqft=50000,
                           base_rate_cents_per_sqft=3000,
                           selection_desk_capacity=1),
            fx.DIRECTOR_HEADERS,
        ),
        ApiErrorId.VENUE_CONTRACT_NOT_EXECUTED,
        409,
    )
    assert _read_venue_contract(client, agreements["draft"]["id"])["show_count"] == 0

    validate_error(
        client.create_booth(
            show_id,
            f.booth_payload("H900", 20, 20, location_class=LocationClass.ISLAND,
                            premium_zone=PremiumZone.NONE, max_height_ft=24),
            FLOOR,
        ),
        ApiErrorId.BOOTH_HEIGHT_LIMIT,
        422,
    )

    validate_error(
        client.create_booth(show_id, f.inline_booth_payload("A100", 10, 10), FLOOR),
        ApiErrorId.DUPLICATE_BOOTH_NUMBER,
        409,
    )

    rows, meta = validate_paginated(
        client.list_booths(fx.DIRECTOR_HEADERS, {"show_id": show_id})
    )
    assert meta["total_count"] == 2
    assert sorted(row["booth_number"] for row in rows) == ["A100", "C050"]

    original = env["booth_by_number"]["A100"]
    reread = fx.read_booth(client, original["id"])
    assert reread["area_sqft"] == 400
    assert reread["max_height_ft"] == 16
    assert reread["version"] == original["version"]


def test_three_rules_of_the_selling_phase_each_report_their_own_error(
    client: ApiClient,
):
    """
    A second live contract for the same exhibitor, out-of-order dates and an
    edition past the end of the term — and the agreement still counts one show.

    "the exhibitor must not already hold another contract on this show in
    `OFFERED`, `COUNTERED` or `SIGNED` status"  "duplicate active contract
    (`ERR_DUPLICATE_ACTIVE_CONTRACT`)"  "The four dates must be non-decreasing —
    `move_in_start` on or before `event_start`, `event_start` on or before
    `event_end`, `event_end` on or before `move_out_end`, all read as UTC dates —
    or the request fails with `ERR_INVALID_SHOW_WINDOW`."  "the calendar year of
    `move_in_start` and the calendar year of `move_out_end` must both lie between
    `contract_year_start` and `contract_year_start` plus `contract_year_count`
    minus one inclusive"

    Design: Corner/validations/six_independent_validation_rules_each_return_their_own_error
    """
    agreements = _two_agreements(client)
    agreement_id = agreements["executed"]["id"]
    env = fx.published_show(client, [A100, C050],
                            venue_contract=agreements["executed"])
    show_id = env["show"]["id"]
    booths = env["booth_by_number"]

    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    held = fx.offered_contract(client, show_id, nordic["id"], 400,
                               [booths["A100"]["id"]],
                               premium_placement_requested=True)
    assert held["status"] == SpaceContractStatus.OFFERED

    validate_error(
        client.create_space_contract(
            f.space_contract_payload(show_id, nordic["id"],
                                     fx.show_version(client, show_id), 200,
                                     booth_ids=[booths["C050"]["id"]]),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.DUPLICATE_ACTIVE_CONTRACT,
        409,
    )
    c050 = fx.read_booth(client, booths["C050"]["id"])
    assert c050["status"] == BoothStatus.AVAILABLE
    assert c050["space_contract_id"] is None

    validate_error(
        client.create_show(
            f.show_payload(agreement_id, name="Reversed Window Expo",
                           edition_year=2027, move_in_start="2027-04-01",
                           event_start="2027-04-05", event_end="2027-04-03",
                           move_out_end="2027-04-09", gross_sqft=40000,
                           base_rate_cents_per_sqft=3000,
                           selection_desk_capacity=1),
            fx.DIRECTOR_HEADERS,
        ),
        ApiErrorId.INVALID_SHOW_WINDOW,
        422,
    )

    validate_error(
        client.create_show(
            f.show_payload(agreement_id, name="Out Of Term Expo",
                           edition_year=2030, move_in_start="2030-03-01",
                           event_start="2030-03-05", event_end="2030-03-07",
                           move_out_end="2030-03-09", gross_sqft=40000,
                           base_rate_cents_per_sqft=3000,
                           selection_desk_capacity=1),
            fx.DIRECTOR_HEADERS,
        ),
        ApiErrorId.SHOW_OUTSIDE_CONTRACT_TERM,
        422,
    )

    assert _read_venue_contract(client, agreement_id)["show_count"] == 1
    rows, meta = validate_paginated(
        client.list_space_contracts(fx.DIRECTOR_HEADERS, {"show_id": show_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == held["id"]


def test_a_deposit_one_cent_short_is_refused_and_the_exact_minimum_signs(
    client: ApiClient,
):
    """
    389069 cents is refused, 389070 signs: the comparison is inclusive at its bound.

    "the tendered deposit must be at least `min_deposit_cents`, or the request is
    refused with `ERR_DEPOSIT_BELOW_MINIMUM`"  "A successful signature moves the
    contract `OFFERED → SIGNED`"  "`deposit_paid_cents` and `signed_at` are
    written, the latter from the logical clock."  "`points_awarded` is written as
    that assigned footage divided by one hundred with the remainder discarded,
    multiplied by two"

    Design: Corner/validations/a_deposit_exactly_at_the_minimum_is_accepted
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    booth_id = env["booth_by_number"]["A100"]["id"]

    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    contract = fx.offered_contract(client, show_id, nordic["id"], 400, [booth_id],
                                   premium_placement_requested=True)
    assert contract["space_fee_cents"] == 1556280
    assert contract["min_deposit_cents"] == 389070
    assert contract["status"] == SpaceContractStatus.OFFERED

    pinned_version = fx.show_version(client, show_id)
    exhibitor_headers = fx.make_exhibitor_headers(nordic["id"])

    validate_error(
        client.sign_space_contract(
            contract["id"], f.sign_payload(pinned_version, 389069), exhibitor_headers
        ),
        ApiErrorId.DEPOSIT_BELOW_MINIMUM,
        422,
    )
    assert (
        fx.read_contract(client, contract["id"])["status"]
        == SpaceContractStatus.OFFERED
    )
    assert fx.read_booth(client, booth_id)["status"] == BoothStatus.HELD
    assert fx.show_version(client, show_id) == pinned_version

    signed = validate_success(
        client.sign_space_contract(
            contract["id"], f.sign_payload(pinned_version, 389070), exhibitor_headers
        )
    )
    assert signed["status"] == SpaceContractStatus.SIGNED
    assert signed["deposit_paid_cents"] == 389070
    assert signed["signed_at"] is not None
    assert signed["signed_at"].startswith("2026-08-15T00:00:00")

    assert fx.read_booth(client, booth_id)["status"] == BoothStatus.ASSIGNED
    show = fx.read_show(client, show_id)
    assert show["assigned_net_sqft"] == 400
    assert show["held_net_sqft"] == 0

    row = fx.read_exhibitor(client, nordic["id"])
    assert row["space_points_provisional"] == 8
    assert row["priority_tier"] == PriorityTier.BRONZE


UNKNOWN_SHOW_ID = "00000000-0000-4000-8000-0000000000cc"
UNKNOWN_EXHIBITOR_ID = "00000000-0000-4000-8000-0000000000dd"


def test_a_bad_enum_outranks_the_unknown_show_that_would_have_hosted_it(
    client: ApiClient,
):
    """
    An undeclared `location_class` under a show that does not exist answers on
    shape, not on existence.

    "every enumerated field must hold a declared value"  "Failures here are
    `ERR_VALIDATION` (HTTP 422). These are structural, single-field checks that
    consult no stored data, which is why they outrank even existence."

    Design: Corner/validations/structural_and_existence_checks_run_in_priority_order
    """
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)
    other_show_id = env["show"]["id"]
    pinned_version = fx.show_version(client, other_show_id)

    validate_error(
        client.create_booth(
            UNKNOWN_SHOW_ID,
            f.booth_payload("A100", 20, 20, location_class="ROUND",
                            premium_zone=PremiumZone.NONE, max_height_ft=12),
            FLOOR,
        ),
        ApiErrorId.VALIDATION,
        422,
    )

    rows, meta = validate_paginated(
        client.list_booths(fx.DIRECTOR_HEADERS, {"show_id": other_show_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert fx.show_version(client, other_show_id) == pinned_version


def test_the_missing_show_answers_before_the_missing_exhibitor_and_before_the_version(
    client: ApiClient,
):
    """
    A contract naming an unknown show, an unknown exhibitor and another show's
    version reports only the first of the three failures.

    "**Existence**, path resources before body references, in this order: venue
    contract (`ERR_VENUE_CONTRACT_NOT_FOUND`), show (`ERR_SHOW_NOT_FOUND`),
    exhibitor (`ERR_EXHIBITOR_NOT_FOUND`)"  "Concurrency control sits deliberately
    *after* existence and per-row state — a stale version on a non-existent or
    wrongly-stated row still reports the sharper error"

    Design: Corner/validations/structural_and_existence_checks_run_in_priority_order
    """
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)
    other_show_id = env["show"]["id"]
    pinned_version = fx.show_version(client, other_show_id)

    validate_error(
        client.create_space_contract(
            f.space_contract_payload(UNKNOWN_SHOW_ID, UNKNOWN_EXHIBITOR_ID,
                                     pinned_version, 400),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.SHOW_NOT_FOUND,
        404,
    )

    rows, meta = validate_paginated(
        client.list_space_contracts(fx.DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert fx.show_version(client, other_show_id) == pinned_version


def test_a_booth_that_breaks_no_rule_of_its_own_still_overcommits_the_floor(
    client: ApiClient,
):
    """
    On a 600 sqft floor already holding 400, a second legal 400 sqft booth is
    refused and a 200 sqft booth lands exactly on the bound.

    "the summed `area_sqft` of the show's booths whose status is anything other
    than `MERGED` may never exceed the show's sellable area — the value derived
    from `gross_sqft` and `aisle_ratio_pct` described below, evaluated on demand
    even before publication has written it into `net_sellable_sqft`. A booth that
    would push the collection past that ceiling is refused with
    `ERR_FLOOR_INVENTORY_OVERCOMMITTED`."  "the system writes `net_sellable_sqft`
    as the show's `gross_sqft` multiplied by one hundred less its
    `aisle_ratio_pct`, divided by one hundred, with any fractional square foot
    discarded downward."

    Design: Corner/validations/individually_legal_booths_can_overcommit_the_floor_collectively
    """
    fx.set_clock(client, CLOCK)
    env = fx.show_with_booths(client, [A100], name="Boutique Sourcing Summit",
                              gross_sqft=1000, aisle_ratio_pct=40)
    show_id = env["show"]["id"]
    assert env["booth_by_number"]["A100"]["area_sqft"] == 400

    validate_error(
        client.create_booth(
            show_id,
            f.inline_booth_payload("B200", 20, 20, max_height_ft=16),
            FLOOR,
        ),
        ApiErrorId.FLOOR_INVENTORY_OVERCOMMITTED,
        422,
    )
    rows, meta = validate_paginated(
        client.list_booths(fx.DIRECTOR_HEADERS, {"show_id": show_id})
    )
    assert meta["total_count"] == 1
    assert [row["booth_number"] for row in rows] == ["A100"]

    accepted = validate_success(
        client.create_booth(show_id, f.inline_booth_payload("C050", 10, 20), FLOOR),
        201,
    )
    assert accepted["area_sqft"] == 200
    assert accepted["status"] == BoothStatus.AVAILABLE

    published = validate_success(client.publish_floor_plan(show_id, fx.DIRECTOR_HEADERS))
    assert published["status"] == ShowStatus.SPACE_SELECTION
    assert published["net_sellable_sqft"] == 600
    assert published["sellable_booth_sqft"] == 600
    assert published["available_net_sqft"] == 600
    assert published["floor_posture"] == FloorPosture.OPEN


def _package_by_code(client: ApiClient, show_id: str) -> dict:
    rows, _ = validate_paginated(
        client.list_sponsorship_packages(show_id, fx.DIRECTOR_HEADERS)
    )
    return {row["package_code"]: row for row in rows}


def test_the_category_lock_binds_only_the_packages_that_name_a_category(
    client: ApiClient,
):
    """
    A rival is locked out of the sibling COOKWARE package, walks into the
    uncategorised one, and the incumbent may take the sibling itself.

    "Where the package names a real `exclusivity_category`, no *other* package of
    the same show sharing that category may already carry a deal in `PROPOSED` or
    `SIGNED` status for a **different** exhibitor; a conflict is
    `ERR_EXCLUSIVITY_CATEGORY_TAKEN`, and note that the conflict lives on a sibling
    package, not on the package being sold."  "An optional `exclusivity_category`,
    drawn from the same character set and defaulting to the literal `NONE`, names a
    market category the package locks up — the literal `NONE` means the package is
    non-exclusive."

    Design: Corner/validations/exclusivity_is_enforced_only_for_packages_that_declare_a_category
    """
    fx.set_clock(client, CLOCK)
    env = fx.planning_show(client)
    show_id = env["show"]["id"]

    cook_a = fx.sponsorship_package(
        client, show_id, package_code="PKG_COOK_A", list_price_cents=4000000,
        price_floor_cents=3200000, inventory_total=2,
        exclusivity_category="COOKWARE", obligation_codes=["LOGO_PLACEMENT"],
        priority_point_value=40,
    )
    cook_b = fx.sponsorship_package(
        client, show_id, package_code="PKG_COOK_B", list_price_cents=4000000,
        price_floor_cents=3200000, inventory_total=2,
        exclusivity_category="COOKWARE", obligation_codes=["STAGE_BANNER"],
        priority_point_value=40,
    )
    open_pkg = fx.sponsorship_package(
        client, show_id, package_code="PKG_OPEN", list_price_cents=4000000,
        price_floor_cents=3200000, inventory_total=2,
        obligation_codes=["LANYARD_PRINT"], priority_point_value=30,
    )
    assert open_pkg["exclusivity_category"] == "NONE"

    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    basalt = fx.exhibitor(client, "Basalt Cookware",
                          contact_email="space@basalt.example",
                          consecutive_years=4, headers=fx.SALES_REP_HEADERS)

    incumbent = fx.proposed_deal(client, cook_a["id"], nordic["id"], 4000000,
                                 headers=fx.SALES_REP_HEADERS)
    assert incumbent["deal_status"] == DealStatus.PROPOSED

    validate_error(
        client.create_sponsorship_deal(
            cook_b["id"], f.sponsorship_deal_payload(basalt["id"], 4000000),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.EXCLUSIVITY_CATEGORY_TAKEN,
        409,
    )
    assert _package_by_code(client, show_id)["PKG_COOK_B"]["inventory_committed"] == 0

    uncategorised = validate_success(
        client.create_sponsorship_deal(
            open_pkg["id"], f.sponsorship_deal_payload(basalt["id"], 4000000),
            fx.SALES_REP_HEADERS,
        ),
        201,
    )
    assert uncategorised["deal_status"] == DealStatus.PROPOSED
    assert uncategorised["exhibitor_id"] == basalt["id"]

    sibling = validate_success(
        client.create_sponsorship_deal(
            cook_b["id"], f.sponsorship_deal_payload(nordic["id"], 4000000),
            fx.SALES_REP_HEADERS,
        ),
        201,
    )
    assert sibling["deal_status"] == DealStatus.PROPOSED
    assert sibling["exhibitor_id"] == nordic["id"]

    assert fx.read_deal(client, incumbent["id"])["deal_status"] == DealStatus.PROPOSED
    after = _package_by_code(client, show_id)["PKG_COOK_B"]
    assert after["inventory_committed"] == 1
    assert after["inventory_available"] == 1


F100 = f.booth_payload("F100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
UNKNOWN_BOOTH_ID = "00000000-0000-4000-8000-0000000000ee"


def test_an_unknown_booth_id_answers_before_the_wrong_editions_booth_does(
    client: ApiClient,
):
    """
    Two editions of the same event: a booth id belonging to nothing is a 404,
    while a real booth of the 2028 edition is a 422 on the 2027 edition.

    "**Existence**, path resources before body references"  "Body references are
    checked here too: `venue_contract_id` on show creation, `show_id` and
    `exhibitor_id` on contract creation, `exhibitor_id` on appointment booking and
    on deal proposal, every element of `booth_ids`"  "When `booth_ids` is supplied,
    those booths are taken as named — each must exist, must belong to the target
    show, must not be `MERGED`, and must be `AVAILABLE` ... failing with
    `ERR_BOOTH_NOT_FOUND`, `ERR_BOOTH_NOT_IN_SHOW`, `ERR_BOOTH_MERGED` and
    `ERR_BOOTH_NOT_AVAILABLE` respectively."

    Design: Corner/validations/booth_existence_is_resolved_before_booth_ownership
    """
    fx.set_clock(client, CLOCK)
    this_year = fx.published_show(client, [A100, C050])
    show_id = this_year["show"]["id"]
    next_year = fx.published_show(
        client, [F100], venue_contract=this_year["venue_contract"],
        edition_year=2028, move_in_start="2028-03-01", event_start="2028-03-05",
        event_end="2028-03-07", move_out_end="2028-03-09",
        base_rate_cents_per_sqft=3400,
    )
    other_show_id = next_year["show"]["id"]
    f100_id = next_year["booth_by_number"]["F100"]["id"]

    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example",
                         consecutive_years=1, headers=fx.SALES_REP_HEADERS)
    pinned_version = fx.show_version(client, show_id)

    validate_error(
        client.create_space_contract(
            f.space_contract_payload(show_id, alder["id"], pinned_version, 400,
                                     booth_ids=[UNKNOWN_BOOTH_ID]),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.BOOTH_NOT_FOUND,
        404,
    )

    validate_error(
        client.create_space_contract(
            f.space_contract_payload(show_id, alder["id"], pinned_version, 400,
                                     booth_ids=[f100_id]),
            fx.SALES_REP_HEADERS,
        ),
        ApiErrorId.BOOTH_NOT_IN_SHOW,
        422,
    )

    f100 = fx.read_booth(client, f100_id)
    assert f100["status"] == BoothStatus.AVAILABLE
    assert f100["space_contract_id"] is None
    assert fx.read_show(client, other_show_id)["held_net_sqft"] == 0

    assert fx.show_version(client, show_id) == pinned_version
    a100 = fx.read_booth(client, this_year["booth_by_number"]["A100"]["id"])
    assert a100["status"] == BoothStatus.AVAILABLE
    assert a100["space_contract_id"] is None

    rows, meta = validate_paginated(
        client.list_space_contracts(fx.DIRECTOR_HEADERS,
                                    {"exhibitor_id": alder["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
