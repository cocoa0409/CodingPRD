"""Creation shapes: declared defaults, derived initial values, request-shape
refusals and the reference checks that guard a new row."""
from test_helpers import (
    ADMIN,
    ANALYST,
    NON_EXISTENT_UUID,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    assert_banner_defaults,
    assert_created_shape,
    assert_household_aggregates_zeroed,
    assert_instant_equals,
    assert_ledger_entry_shape,
    assert_pagination_meta,
    factories,
    fixtures,
    is_valid_uuid,
    make_pump_terminal_headers,
    make_store_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

FULLY_OVERRIDDEN = {
    "base_points_per_dollar": 2,
    "gift_card_multiplier": 6,
    "pharmacy_multiplier": 3,
    "pharmacy_points_per_script": 75,
    "max_stacked_multiplier": 12,
    "max_stack_count": 3,
    "points_per_discount_block": 200,
    "cents_off_per_block": 15,
    "max_cents_off_per_gallon": 150,
    "owned_max_gallons_per_redemption": 20,
    "min_points_per_redemption": 200,
    "rollover_cap_points": 1000,
    "max_transfers_per_cycle": 5,
    "expiry_basis": "CYCLE_SCOPED",
    "fraud_scoring_mode": "TRAILING_WEIGHTED",
    "freeze_threshold_score": 90,
}


def test_a_banner_registered_with_only_its_code_and_name_carries_every_default():
    """Every omitted configuration knob comes back at its declared default, and
    the banner is immediately usable.

    PRD: "A `ProgramAdmin` bootstraps a program by registering a banner with its
    `banner_code`, its `name` and whichever of the configuration knobs from §2.4
    it wishes to override; the banner comes into being in `ACTIVE` status with
    every omitted knob sitting at its declared default."

    PRD: "Every remaining banner field is a configuration knob supplied at
    registration, and every one of them is optional with a declared default."

    Design: Corner/entities/banner_creation_stamps_every_declared_default_and_starts_active
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")

    banner = validate_success(
        api_client.create_banner(
            {"banner_code": "CORE", "name": "Corner Banner"}, ADMIN
        ),
        201,
    )

    assert_banner_defaults(banner)
    assert banner["status"] == "ACTIVE"
    assert_created_shape(banner)


def test_a_fully_configured_banner_returns_every_supplied_parameter_unchanged():
    """No default silently overwrites a supplied value, including the two
    behaviour-selecting enums.

    PRD: "Three banner fields select behaviour rather than set a number, and they
    are the reason two banners are not interchangeable."

    PRD: "`expiry_basis` is either `LOT_FIFO` (the default) or `CYCLE_SCOPED`, and
    it decides which lot-consumption ordering the month-end sweep replays — see
    §3.8, where the two orderings are spelled out and produce genuinely different
    balances from an identical ledger."

    Design: Corner/entities/banner_get_round_trips_every_overridden_program_parameter
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    created = fixtures.create_banner(
        banner_code="FULL", name="Fully Configured Banner", **FULLY_OVERRIDDEN
    )

    fetched = validate_success(api_client.get_banner(created["id"], ANALYST))

    for field, supplied in FULLY_OVERRIDDEN.items():
        assert fetched[field] == supplied, f"{field} did not round-trip"
    assert fetched["banner_code"] == "FULL"
    assert fetched["status"] == "ACTIVE"


def test_the_site_list_pages_and_narrows_to_one_site_type():
    """`total_count` always counts the filtered set rather than the page.

    PRD: "`limit` sets the maximum number of rows returned; it defaults to 10, its
    minimum accepted value is 1 and its maximum accepted value is 100."

    PRD: "Both appear in the `meta` object of the response envelope alongside
    `total_count` (the number of rows matching the filters before pagination) and
    `has_more` (true when rows remain beyond this page)."

    Design: Corner/entities/sites_list_paginates_and_filters_by_banner_and_site_type
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    fixtures.create_grocery_site(banner["id"], "G-100")
    fixtures.create_owned_fuel_center(banner["id"], "F-100")
    partner = fixtures.create_partner_station(
        banner["id"], site_number="P-100", partner_code="PTR100"
    )

    first_page, first_meta = validate_paginated(
        api_client.list_sites(ANALYST, {"banner_id": banner["id"], "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert_pagination_meta(first_meta, total_count=3, limit=2, offset=0, has_more=True)

    second_page, second_meta = validate_paginated(
        api_client.list_sites(ANALYST, {"banner_id": banner["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert_pagination_meta(second_meta, total_count=3, limit=2, offset=2, has_more=False)

    partners, partner_meta = validate_paginated(
        api_client.list_sites(
            ANALYST, {"banner_id": banner["id"], "site_type": "PARTNER_STATION"}
        )
    )
    assert partner_meta["total_count"] == 1
    assert partners[0]["id"] == partner["id"]


def test_the_pump_resolves_a_keyed_alternate_id_through_the_member_list():
    """A keyed number that nobody holds is an empty page, not a not-found.

    PRD: "A pump session begins with an alternate-ID lookup — the member list is
    filterable by `alt_id` precisely so an unattended terminal can resolve a keyed
    number to a member — and continues with an authorization request naming the
    `member_id`, the `site_id`, the `alt_id_presented` at the keypad, the
    `points_committed` the customer offers, and the `expected_member_version`
    guard from §2.9."

    Design: Corner/entities/members_list_by_alt_id_supports_alternate_id_lookup_at_the_pump
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    fuel = fixtures.create_owned_fuel_center(banner["id"], "F-100")
    first = fixtures.create_member(
        banner["id"], alt_id="6660000001", card_number="4100000000000001"
    )
    fixtures.create_member(
        banner["id"], alt_id="6660000002", card_number="4100000000000002"
    )
    pump = make_pump_terminal_headers(fuel["id"])

    found, found_meta = validate_paginated(
        api_client.list_members(pump, {"banner_id": banner["id"], "alt_id": "6660000001"})
    )
    assert found_meta["total_count"] == 1
    assert found[0]["id"] == first["id"]

    missing, missing_meta = validate_paginated(
        api_client.list_members(pump, {"banner_id": banner["id"], "alt_id": "9999999999"})
    )
    assert missing == []
    assert missing_meta["total_count"] == 0
    assert missing_meta["has_more"] is False


def test_an_unused_member_identifier_in_the_path_is_a_not_found():
    """Existence is checked after authorisation, so even the program admin sees
    the 404.

    PRD: "Every identifier embedded in the request path resolves, validated
    strictly left to right, so the leftmost unresolvable identifier determines the
    error."

    Design: Corner/entities/member_get_with_unknown_id_returns_member_not_found
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    member = fixtures.create_member(banner["id"], alt_id="6660000001")

    validate_error(
        api_client.get_member(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_MEMBER_NOT_FOUND.value,
    )

    assert fixtures.get_member(member["id"])["alt_id"] == "6660000001"


def test_enrolling_a_member_without_a_card_number_is_refused():
    """`card_number` has no default, so an otherwise complete enrolment is a
    request-shape failure and nothing is written.

    PRD: "A member is enrolled against a `banner_id` with an `alt_id` — ten to
    twelve digits, the alternate identifier the shopper will key at the pump,
    unique among that banner's members — a `card_number` of eight to nineteen
    digits also unique within the banner, and a `full_name` of one to one hundred
    and twenty characters."

    PRD: "Every required input field present; every enum value a declared member;
    every integer field an integer; `amount_cents`, `quantity`, `points_committed`
    and `severity_weight` all zero or greater; `gallons_dispensed` carrying at most
    three decimals; every timestamp parsing as ISO 8601 UTC; `lines` a non-empty
    array; `period_start` no later than `period_end`; `starts_at` strictly before
    `ends_at`; and `cycle_month` matching the four-digit-year-dash-two-digit-month
    form."

    Design: Corner/entities/member_creation_missing_card_number_returns_invalid_request
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")

    validate_error(
        api_client.create_member(
            {
                "banner_id": banner["id"],
                "alt_id": "6660000003",
                "full_name": "Missing Card",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _rows, meta = validate_paginated(
        api_client.list_members(ADMIN, {"banner_id": banner["id"]})
    )
    assert meta["total_count"] == 0


def test_a_site_type_outside_the_declared_trio_is_refused():
    """`FUEL_CENTER` is not one of the three site types and is not coerced into
    one.

    PRD: "The three site types are `GROCERY`, `OWNED_FUEL_CENTER` and
    `PARTNER_STATION`."

    Design: Corner/entities/site_creation_rejects_a_site_type_outside_the_declared_enum
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")

    validate_error(
        api_client.create_site(
            {
                "banner_id": banner["id"],
                "site_number": "X-100",
                "site_type": "FUEL_CENTER",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _rows, meta = validate_paginated(
        api_client.list_sites(ADMIN, {"banner_id": banner["id"]})
    )
    assert meta["total_count"] == 0


def test_a_basket_with_no_lines_at_all_is_refused_at_the_shape_gate():
    """An empty `lines` array is malformed rather than a zero-point basket.

    PRD: "A `StoreOperator` records a basket by naming a `member_id`, a `site_id`,
    a `transacted_at` instant, and a `lines` array of one to twenty elements."

    Design: Corner/entities/purchase_transaction_rejects_an_empty_lines_array
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(alt_id="6660000001")
    grocery_id = program["grocery"]["id"]

    validate_error(
        api_client.create_purchase_transaction(
            factories.purchase_transaction_payload(
                program["member"]["id"],
                grocery_id,
                "2026-08-01T00:00:00Z",
                lines=[],
            ),
            make_store_operator_headers(grocery_id),
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _rows, meta = validate_paginated(
        api_client.list_purchase_transactions(
            ADMIN, {"member_id": program["member"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_recording_a_basket_derives_its_subtotal_and_leaves_the_points_alone():
    """The subtotal is computed from the submitted lines while every accrual
    figure stays at its unposted value.

    PRD: "Recording immediately computes `subtotal_cents` as the sum of
    `amount_cents` across **every** submitted line, including lines in categories
    that will earn nothing."

    PRD: "It writes no ledger row, leaves `gross_points_awarded` at zero, leaves
    `line_points_breakdown` empty, and leaves `posted_at` and `voided_at` null."

    PRD: "Every resource carries an `id`: a server-minted UUID with no type
    prefix. Clients never supply it."

    Design: Corner/entities/purchase_transaction_system_and_computed_fields_ignore_client_input
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(alt_id="6660000001")
    grocery_id = program["grocery"]["id"]

    basket = validate_success(
        api_client.create_purchase_transaction(
            factories.purchase_transaction_payload(
                program["member"]["id"],
                grocery_id,
                "2026-08-01T00:00:00Z",
                [factories.purchase_line("GROCERY", 30000, 1)],
            ),
            make_store_operator_headers(grocery_id),
        ),
        201,
    )

    assert basket["subtotal_cents"] == 30000
    assert basket["gross_points_awarded"] == 0
    assert basket["line_points_breakdown"] == []
    assert basket["posted_at"] is None
    assert basket["voided_at"] is None
    assert basket["posting_status"] == "RECORDED"
    assert basket["accrual_status"] == "NOT_ACCRUED"
    assert is_valid_uuid(basket["id"])
    assert_created_shape(basket)
    assert fixtures.get_member(program["member"]["id"])["available_points"] == 0


def test_an_accrual_ledger_row_carries_no_version_and_no_updated_at():
    """The row exposes its origin pair and its lot expiry but none of the audit
    fields a mutable resource carries.

    PRD: "`PointLedgerEntry` is the exception. Ledger rows are immutable by
    construction, so they carry only `id` and `created_at`: both `updated_at` and
    `version` are absent from a ledger entry entirely."

    PRD: "When `gross_points_awarded` is greater than zero it appends exactly one
    `ACCRUAL` ledger row whose `points_delta` equals `gross_points_awarded`, whose
    `point_cycle_id` is the open cycle, whose `lot_expires_at` is the **next**
    cycle's `closes_at`, whose `source_kind` is `PURCHASE_TRANSACTION` and whose
    `source_ref_id` is this transaction's identifier; when `gross_points_awarded`
    is exactly zero, no ledger row is written at all."

    Design: Corner/entities/point_ledger_entry_is_immutable_and_carries_no_version_field
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(alt_id="6660000001")
    grocery_id = program["grocery"]["id"]
    basket = fixtures.record_basket(
        program["member"]["id"],
        grocery_id,
        [factories.purchase_line("GROCERY", 30000, 1)],
        "2026-08-01T00:00:00Z",
    )
    fixtures.post_basket(basket["id"], grocery_id)

    rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ANALYST, {"member_id": program["member"]["id"], "entry_type": "ACCRUAL"}
        )
    )

    assert meta["total_count"] == 1
    row = rows[0]
    assert row["points_delta"] == 300
    assert row["entry_type"] == "ACCRUAL"
    assert row["source_kind"] == "PURCHASE_TRANSACTION"
    assert row["source_ref_id"] == basket["id"]
    assert row["point_cycle_id"] == program["cycles"]["2026-08"]["id"]
    assert_instant_equals(row["lot_expires_at"], "2026-09-30T23:59:59.999Z")
    assert_ledger_entry_shape(row)


def test_a_linkage_proposal_resolves_its_household_and_its_member_first():
    """Both body references are existence-checked, and neither failed attempt
    leaves a linkage behind.

    PRD: "Every identifier in the request body resolves, validated in the order
    the fields are listed for that endpoint, drawing on the same 404 family."

    Design: Corner/entities/household_link_creation_requires_both_referenced_parents_to_exist
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    member = fixtures.create_member(banner["id"], alt_id="6660000001")
    household = fixtures.create_household(banner["id"], "HH-CORE-1")

    validate_error(
        api_client.create_household_link(
            factories.household_link_payload(NON_EXISTENT_UUID, member["id"]), ANALYST
        ),
        ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND.value,
    )
    validate_error(
        api_client.create_household_link(
            factories.household_link_payload(household["id"], NON_EXISTENT_UUID), ANALYST
        ),
        ApiErrorId.ERR_MEMBER_NOT_FOUND.value,
    )

    _rows, meta = validate_paginated(
        api_client.list_household_links(ADMIN, {"household_id": household["id"]})
    )
    assert meta["total_count"] == 0
    assert fixtures.get_household(household["id"])["linked_member_count"] == 0


def test_a_new_household_starts_active_with_every_aggregate_initialised():
    """The derived figures are readable from the first moment rather than absent
    until a linkage arrives.

    PRD: "It starts `ACTIVE` with `fraud_score` zero, `linked_member_count` zero,
    `frozen_reason` null, `frozen_at` null and `version` 1."

    Design: Corner/entities/household_creation_zeroes_every_derived_aggregate_and_starts_active
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")

    household = validate_success(
        api_client.create_household(
            factories.household_payload(banner["id"], "HH-CORE-2"), ANALYST
        ),
        201,
    )

    assert household["status"] == "ACTIVE"
    assert household["frozen_reason"] is None
    assert household["frozen_at"] is None
    assert_household_aggregates_zeroed(household)
    assert_created_shape(household)


def test_a_new_point_cycle_is_open_with_its_close_metrics_at_zero():
    """The sweep totals sit at zero and `closed_at` is null until the close runs.

    PRD: "A newly defined cycle is `OPEN` with `expired_points_total`,
    `rolled_over_points_total` and `swept_member_count` all zero and `closed_at`
    null."

    Design: Corner/entities/point_cycle_creation_starts_open_with_zeroed_close_metrics
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")

    cycle = validate_success(
        api_client.create_point_cycle(
            factories.point_cycle_payload(banner["id"], "2026-11"), SUPERVISOR
        ),
        201,
    )

    assert cycle["status"] == "OPEN"
    assert cycle["closed_at"] is None
    assert cycle["expired_points_total"] == 0
    assert cycle["rolled_over_points_total"] == 0
    assert cycle["swept_member_count"] == 0
    assert cycle["cycle_month"] == "2026-11"
    assert_instant_equals(cycle["opens_at"], "2026-11-01T00:00:00Z")
    assert_instant_equals(cycle["closes_at"], "2026-11-30T23:59:59.999Z")


def test_a_promotion_whose_window_is_empty_is_refused_as_malformed():
    """A start equal to its end is a shape failure, not the window-conflict
    rule.

    PRD: "Each is scheduled against a `banner_id` with a `promo_code` of three to
    twenty-four characters unique within that banner, an integer `multiplier`
    between 2 and 10, an `applies_to_categories` array holding one to six distinct
    members of the six purchase categories, a `starts_at`, an `ends_at` strictly
    later than `starts_at`, and a `stack_priority` between 0 and 1000."

    Design: Corner/entities/promo_event_creation_rejects_a_window_whose_start_is_not_before_its_end
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")

    error = validate_error(
        api_client.create_promo_event(
            factories.promo_event_payload(
                banner["id"],
                promo_code="P_EMPTY",
                starts_at="2026-08-10T00:00:00Z",
                ends_at="2026-08-10T00:00:00Z",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value

    _rows, meta = validate_paginated(
        api_client.list_banner_promo_events(banner["id"], ADMIN)
    )
    assert meta["total_count"] == 0


def test_a_fraud_signal_may_not_carry_a_negative_weight():
    """A negative weight cannot be used to drive a household's score downwards.

    PRD: "A signal is raised against a `household_id` with a `signal_type` of
    `ALT_ID_SHARING`, `RAPID_TRANSFER`, `CROSS_BANNER_VELOCITY`, `OVERDRAWN_AUTH`
    or `GEO_IMPOSSIBLE`, and a `severity_weight` between 1 and 100."

    Design: Corner/entities/fraud_signal_creation_rejects_a_negative_severity_weight
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    household = fixtures.create_household(banner["id"], "HH-CORE-1")

    validate_error(
        api_client.create_fraud_signal(
            factories.fraud_signal_payload(
                household["id"], "ALT_ID_SHARING", severity_weight=-10
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _rows, meta = validate_paginated(
        api_client.list_household_fraud_signals(household["id"], ADMIN)
    )
    assert meta["total_count"] == 0

    household = fixtures.get_household(household["id"])
    assert household["fraud_score"] == 0
    assert household["status"] == "ACTIVE"


def test_a_member_may_be_linked_to_a_household_of_another_banner():
    """Activation publishes the member into the household's cross-banner set
    without re-parenting the member.

    PRD: "It is created in `PENDING` status with `activated_at` and `revoked_at`
    both null, and with `is_cross_banner` computed as true exactly when the
    member's banner differs from the household's banner."

    PRD: "Either way, activation sets `status` to `ACTIVE` and stamps
    `activated_at` with the logical clock — overwriting the previous activation
    instant on a re-activation rather than preserving it — and then performs the
    coverage propagation of §2.11: `linked_member_count`,
    `aggregate_available_points` and `cross_banner_member_ids` are recomputed on
    the household and its `version` increments by one."

    Design: Corner/entities/cross_aggregate_link_associates_a_member_with_another_banners_household
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    home = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    away = fixtures.create_banner(banner_code="ALT2", name="Alternate Banner Two")
    member = fixtures.create_member(home["id"], alt_id="6660000001")
    household = fixtures.create_household(away["id"], "HH-ALT2-1")
    link = validate_success(
        api_client.create_household_link(
            factories.household_link_payload(household["id"], member["id"], "SECONDARY"),
            ANALYST,
        ),
        201,
    )
    assert link["is_cross_banner"] is True
    assert link["status"] == "PENDING"

    activated = fixtures.activate_link(link["id"])

    assert activated["status"] == "ACTIVE"
    read = fixtures.get_household(household["id"])
    assert read["linked_member_count"] == 1
    assert read["cross_banner_member_ids"] == [member["id"]]
    assert fixtures.get_member(member["id"])["banner_id"] == home["id"]
