"""The reference book on its plainest path: what a create returns when the caller
supplies only the mandatory fields, what a read gives back, and what a filtered page
reports about the rows it did not return."""
from test_helpers import (
    CLERK,
    LAB_TECH,
    MANAGER,
    create_grape_contract_payload,
    create_grower,
    create_quality_spec,
    create_quality_spec_payload,
    is_valid_uuid,
    move_clock,
    single_installment_plan,
    validate_paginated,
    validate_success,
)

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"
CLOCK_MOVED_ON_TO = "2026-08-02T00:00:00Z"

PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
FILTERED_REGION = "NAPA-NORTH"
OTHER_REGION = "SONOMA-COAST"


def _stamped_at(value: str) -> bool:
    """The audit stamp records the logical clock's instant; the PRD fixes the instant,
    not the number of fractional digits the serialisation carries."""
    return isinstance(value, str) and value.startswith("2026-08-01T00:00:00")


# --- Registering a producer -------------------------------------------------------


def test_registering_a_producer_returns_the_row_in_the_success_envelope(api):
    """The create answers 201 with the standard envelope around the new row, and every
    supplied field is echoed verbatim.

    PRD: "The `data` field contains the resource object or an array of resource objects.
    For 2xx responses with no data, it contains an empty object. Unless otherwise noted,
    operations that create or modify a resource will return the created or updated
    resource object in the data field."

    Design: Corner/entities/grower_creation_returns_201_with_success_envelope_and_defaults
    """
    move_clock(CLOCK_PINNED_AT)

    response = api.create_grower(dict(PRODUCER), MANAGER)
    grower = validate_success(response, 201)

    body = response.json()
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert grower["name"] == "Ridgeline Vineyards"
    assert grower["license_number"] == "PL-44821"
    assert grower["region_code"] == "NAPA-NORTH"


def test_a_producer_registered_without_a_status_starts_active(api):
    """`status` was not supplied, and the row comes back `ACTIVE` rather than null.

    PRD: "An optional `status` may be supplied at registration and defaults to `ACTIVE`;
    the only other permitted value is `SUSPENDED`."

    Design: Corner/entities/grower_creation_returns_201_with_success_envelope_and_defaults
    """
    move_clock(CLOCK_PINNED_AT)

    grower = validate_success(api.create_grower(dict(PRODUCER), MANAGER), 201)
    assert grower["status"] == "ACTIVE"


def test_registration_seeds_the_standing_counters_at_zero_and_the_scores_at_full(api):
    """Derived standing is initialised, not left null: four counters and the lien balance
    at 0, both reliability scores at 100.0.

    PRD: "Registration also initialises the producer's derived standing:
    `rejected_load_count_vintage`, `expired_pick_call_count_vintage`,
    `no_show_appointment_count_vintage` and `prior_vintage_penalty_units` all start at 0,
    `outstanding_lien_balance_cents` starts at 0, and both `reliability_score_vintage` and
    `reliability_score_lifetime` start at 100.0."

    Design: Corner/entities/grower_creation_returns_201_with_success_envelope_and_defaults
    """
    move_clock(CLOCK_PINNED_AT)

    grower = validate_success(api.create_grower(dict(PRODUCER), MANAGER), 201)
    assert grower["rejected_load_count_vintage"] == 0
    assert grower["expired_pick_call_count_vintage"] == 0
    assert grower["no_show_appointment_count_vintage"] == 0
    assert grower["prior_vintage_penalty_units"] == 0
    assert grower["outstanding_lien_balance_cents"] == 0
    assert float(grower["reliability_score_vintage"]) == 100.0
    assert float(grower["reliability_score_lifetime"]) == 100.0


def test_a_new_row_carries_a_minted_identifier_and_its_first_version(api):
    """The id is a server-minted UUID and the audit trail opens at version 1, with both
    stamps taken from the logical clock.

    PRD: "Almost every resource additionally carries `updated_at` — an ISO 8601 UTC
    timestamp, same format, refreshed on every mutation — and `version`, an integer that
    starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/grower_creation_returns_201_with_success_envelope_and_defaults
    """
    move_clock(CLOCK_PINNED_AT)

    grower = validate_success(api.create_grower(dict(PRODUCER), MANAGER), 201)
    assert is_valid_uuid(grower["id"])
    assert grower["version"] == 1
    assert _stamped_at(grower["created_at"])
    assert grower["updated_at"] == grower["created_at"]


# --- Drafting a contract on the house standard ------------------------------------


def _bare_contract_payload() -> dict:
    """A contract body carrying nothing but the mandatory commercial terms."""
    grower = create_grower(**PRODUCER)
    spec = create_quality_spec()
    return create_grape_contract_payload(
        grower["id"],
        spec["id"],
        contract_code="GC-DEFAULTS",
        contract_basis="TONNAGE",
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2026,
        committed_tons=40.000,
        installment_plan=single_installment_plan(),
    )


def test_the_optional_commercial_terms_take_the_house_defaults(api):
    """None of the ten optional terms was supplied, and every one of them comes back at
    its documented value — a silently missing default would zero a whole price component.

    PRD: "`spot_price_pct`, the percentage of the base price paid on over-delivery tonnage
    under an `ACCEPT_AT_SPOT` policy, defaults to 70.0 and must be greater than 0 and at
    most 100. `over_delivery_tolerance_pct`, the percentage by which the soft cap may be
    exceeded before fruit is refused outright, defaults to 10.0 and lies between 0 and 100
    inclusive. `settlement_basis` selects which final-settlement algorithm runs at close
    and defaults to `LOAD_BY_LOAD`, the alternative being `WEIGHTED_BLEND`.
    `provisional_payment_pct`, the share of each settlement line advanced provisionally at
    grading time, defaults to 60.0 and must be greater than 0 and at most 100."

    Design: Corner/entities/grape_contract_optional_fields_take_declared_defaults
    """
    move_clock(CLOCK_PINNED_AT)

    contract = validate_success(api.create_grape_contract(_bare_contract_payload(), MANAGER), 201)
    assert float(contract["spot_price_pct"]) == 70.0
    assert float(contract["over_delivery_tolerance_pct"]) == 10.0
    assert contract["settlement_basis"] == "LOAD_BY_LOAD"
    assert float(contract["provisional_payment_pct"]) == 60.0
    assert float(contract["lien_holdback_pct"]) == 5.0


def test_the_optional_notice_and_renewal_terms_take_the_house_defaults(api):
    """The scheduling and renewal knobs default too, and the two hour figures are whole
    hours rather than instants.

    PRD: "`min_pick_notice_hours` defaults to 48 whole hours and may not be negative;
    `pick_call_ack_window_hours`, the time the producer has to acknowledge a call, defaults
    to 24 whole hours and must be positive. `evergreen_flag` defaults to false; when true,
    the term rolls forward automatically once the renewal window closes without an explicit
    renewal or termination notice, and `evergreen_term_years` — defaulting to 1 and
    constrained to the range 1 through 5 — is how many years each roll adds.
    `termination_notice_days` defaults to 90"

    Design: Corner/entities/grape_contract_optional_fields_take_declared_defaults
    """
    move_clock(CLOCK_PINNED_AT)

    contract = validate_success(api.create_grape_contract(_bare_contract_payload(), MANAGER), 201)
    assert contract["min_pick_notice_hours"] == 48
    assert contract["pick_call_ack_window_hours"] == 24
    assert contract["evergreen_flag"] is False
    assert contract["evergreen_term_years"] == 1
    assert contract["termination_notice_days"] == 90


def test_a_freshly_drafted_contract_has_both_dimensions_at_their_opening_states(api):
    """Two independent dimensions, both at their opening value, with the negotiation
    counter and the tonnage posture alongside them.

    PRD: "A freshly drafted contract sits in `lifecycle_status` `DRAFT` with
    `renewal_status` `NOT_DUE`, `offer_round` 0 and `tonnage_status` `OPEN`."

    Design: Corner/entities/grape_contract_optional_fields_take_declared_defaults
    """
    move_clock(CLOCK_PINNED_AT)

    contract = validate_success(api.create_grape_contract(_bare_contract_payload(), MANAGER), 201)
    assert contract["lifecycle_status"] == "DRAFT"
    assert contract["renewal_status"] == "NOT_DUE"
    assert contract["offer_round"] == 0
    assert contract["tonnage_status"] == "OPEN"


def test_the_caps_and_the_renewal_window_are_not_derived_until_acceptance(api):
    """Everything the harvest needs is still null on a draft, because acceptance — not
    creation — is what derives it; the declared tonnage field is stored as given.

    PRD: "Acceptance is the pivot of the whole system. It is a `Grower` action on the
    contract's own producer, it drives `OFFERED → ACTIVE`, it takes no request body"

    Design: Corner/entities/grape_contract_optional_fields_take_declared_defaults
    """
    move_clock(CLOCK_PINNED_AT)

    contract = validate_success(api.create_grape_contract(_bare_contract_payload(), MANAGER), 201)
    assert contract["contract_cap_tons"] is None
    assert contract["hard_cap_tons"] is None
    assert contract["cap_scope"] is None
    assert contract["renewal_window_opens_at"] is None
    assert contract["renewal_window_closes_at"] is None
    assert contract["contracted_yield_tons_per_acre"] is None
    assert float(contract["committed_tons"]) == 40.000


# --- Writing the grading rulebook from its five mandatory thresholds --------------


def test_the_optional_grading_thresholds_take_their_declared_defaults(api):
    """A specification authored from the five mandatory thresholds still exposes the whole
    reference grading curve, because every price adjustment reads these defaults.

    PRD: "`min_brix_pick_call`, the minimum sampled sugar that lets a pick call be issued,
    defaults to 21.0; `brix_step`, the sugar increment that constitutes one bonus or penalty
    step, defaults to 0.5; `brix_bonus_pct_per_step` defaults to 1.5 and
    `brix_penalty_pct_per_step` to 2.0 percentage points"

    Design: Corner/entities/quality_spec_grading_defaults_applied_when_only_required_fields_supplied
    """
    move_clock(CLOCK_PINNED_AT)

    spec = validate_success(
        api.create_quality_spec(create_quality_spec_payload(spec_code="CAB-BARE-2026"), LAB_TECH),
        201,
    )
    assert float(spec["min_brix_pick_call"]) == 21.0
    assert float(spec["brix_step"]) == 0.5
    assert float(spec["brix_bonus_pct_per_step"]) == 1.5
    assert float(spec["brix_penalty_pct_per_step"]) == 2.0


def test_the_acid_rot_and_mog_bands_and_the_two_ceilings_all_default(api):
    """The three non-sugar components and the clamp that bounds their sum are all present
    without being asked for; a missing one would silently disable a whole penalty.

    PRD: "the titratable-acidity band runs from `ta_min_gl`, defaulting to 5.5 grams per
    litre, to `ta_max_gl`, defaulting to 9.0 and required to be strictly greater than
    `ta_min_gl`, with `acid_out_of_spec_penalty_pct` defaulting to a flat 3.0 percentage
    points outside that band; `rot_free_pct`, the rot percentage tolerated at no cost,
    defaults to 2.0 and `rot_penalty_pct_per_point` to 1.5 percentage points per whole point
    above it; `mog_max_pct`, the tolerated material-other-than-grapes percentage, defaults to
    1.0 with a flat `mog_penalty_pct` of 2.5 percentage points beyond it; and the two
    ceilings, `max_total_bonus_pct` defaulting to 8.0 and `max_total_penalty_pct` defaulting
    to 20.0, bound the combined adjustment."

    Design: Corner/entities/quality_spec_grading_defaults_applied_when_only_required_fields_supplied
    """
    move_clock(CLOCK_PINNED_AT)

    spec = validate_success(
        api.create_quality_spec(create_quality_spec_payload(spec_code="CAB-BARE-2026"), LAB_TECH),
        201,
    )
    assert float(spec["ta_min_gl"]) == 5.5
    assert float(spec["ta_max_gl"]) == 9.0
    assert float(spec["acid_out_of_spec_penalty_pct"]) == 3.0
    assert float(spec["rot_free_pct"]) == 2.0
    assert float(spec["rot_penalty_pct_per_point"]) == 1.5
    assert float(spec["mog_max_pct"]) == 1.0
    assert float(spec["mog_penalty_pct"]) == 2.5
    assert float(spec["max_total_bonus_pct"]) == 8.0
    assert float(spec["max_total_penalty_pct"]) == 20.0


def test_the_five_mandatory_thresholds_are_stored_exactly_as_supplied(api):
    """Defaulting the rest does not disturb the five values the lab did supply.

    PRD: "Five values are mandatory: a `spec_code` of 3 to 32 characters unique across
    specifications, `min_brix_accept` (the minimum graded sugar at receipt, below which the
    load is rejected on quality), `brix_bonus_start` (which must be strictly greater than
    `min_brix_accept`), `brix_penalty_start` (which must be at least `min_brix_accept` and at
    most `brix_bonus_start`), and `rot_rejection_pct` (which must be strictly greater than
    `rot_free_pct`)."

    Design: Corner/entities/quality_spec_grading_defaults_applied_when_only_required_fields_supplied
    """
    move_clock(CLOCK_PINNED_AT)

    spec = validate_success(
        api.create_quality_spec(create_quality_spec_payload(spec_code="CAB-BARE-2026"), LAB_TECH),
        201,
    )
    assert spec["spec_code"] == "CAB-BARE-2026"
    assert float(spec["min_brix_accept"]) == 20.0
    assert float(spec["brix_bonus_start"]) == 24.0
    assert float(spec["brix_penalty_start"]) == 22.0
    assert float(spec["rot_rejection_pct"]) == 8.0
    assert spec["version"] == 1


# --- Reading a row back ------------------------------------------------------------


def test_reading_a_producer_back_is_not_a_mutation(api):
    """The clock has moved on a whole day, yet the read returns the row exactly as the
    create left it — a GET neither refreshes `updated_at` nor bumps `version`.

    PRD: "Recomputation counts as mutation. When a load is graded and the cascade recomputes
    a contract's delivered tonnage, that contract's `updated_at` is refreshed and its
    `version` increments, exactly as if a client had written to it directly."

    Design: Corner/entities/grower_retrieval_by_id_returns_the_stored_row
    """
    move_clock(CLOCK_PINNED_AT)
    created = create_grower(**PRODUCER)
    move_clock(CLOCK_MOVED_ON_TO)

    response = api.get_grower(created["id"], CLERK)
    grower = validate_success(response, 200)

    assert response.json()["response_type"] == "object"
    assert grower["id"] == created["id"]
    assert grower["license_number"] == "PL-44821"
    assert grower["version"] == 1
    assert grower["updated_at"] == created["updated_at"]
    assert _stamped_at(grower["updated_at"])
    assert float(grower["reliability_score_lifetime"]) == 100.0


# --- Listing: the filter decides the cardinality the envelope reports -------------


def _three_producers_two_of_them_in_one_region() -> dict:
    """Two producers in the filtered region and one outside it."""
    move_clock(CLOCK_PINNED_AT)
    return {
        "a": create_grower(name="Ridgeline Vineyards", license_number="PL-44821", region_code=FILTERED_REGION),
        "b": create_grower(name="Stonegate Ranch", license_number="PL-44822", region_code=FILTERED_REGION),
        "c": create_grower(name="Coastal Rows", license_number="PL-44823", region_code=OTHER_REGION),
    }


def test_a_filtered_page_reports_the_filtered_count_not_the_table_count(api):
    """Three rows exist but only two match the region, so `total_count` is 2 — and with a
    page of one, rows remain beyond it.

    PRD: "Every list response repeats `limit` and `offset` in the `meta` object alongside
    `total_count` — the number of rows matching the filter before pagination is applied — and
    `has_more`, which is true exactly when rows remain beyond the current page."

    Design: Corner/entities/grower_listing_returns_pagination_envelope_with_total_count_and_has_more
    """
    producers = _three_producers_two_of_them_in_one_region()

    response = api.list_growers(MANAGER, params={"region_code": FILTERED_REGION, "limit": 1, "offset": 0})
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert rows[0]["id"] != producers["c"]["id"]


def test_the_last_page_of_a_filtered_listing_reports_nothing_beyond_it(api):
    """Skipping the first of the two matching rows lands on the last page, where the same
    `total_count` now comes with `has_more` false.

    PRD: "`offset` is the number of rows to skip before the page begins; it defaults to 0 and
    may not be negative."

    Design: Corner/entities/grower_listing_returns_pagination_envelope_with_total_count_and_has_more
    """
    producers = _three_producers_two_of_them_in_one_region()

    first, _ = validate_paginated(
        api.list_growers(MANAGER, params={"region_code": FILTERED_REGION, "limit": 1, "offset": 0})
    )
    second, meta = validate_paginated(
        api.list_growers(MANAGER, params={"region_code": FILTERED_REGION, "limit": 1, "offset": 1})
    )

    assert len(second) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["offset"] == 1
    assert second[0]["id"] != first[0]["id"]
    assert {first[0]["id"], second[0]["id"]} == {producers["a"]["id"], producers["b"]["id"]}


def test_the_row_outside_the_filter_appears_on_neither_page(api):
    """The producer in the other region is excluded from every page of the filtered read,
    which is what makes the count of 2 meaningful.

    PRD: "Producers can be browsed as a collection with the optional filters `region_code`
    and `status`, and a single producer read returns both reliability scores and the
    outstanding lien balance."

    Design: Corner/entities/grower_listing_returns_pagination_envelope_with_total_count_and_has_more
    """
    producers = _three_producers_two_of_them_in_one_region()

    seen = []
    for offset in (0, 1):
        rows, _ = validate_paginated(
            api.list_growers(MANAGER, params={"region_code": FILTERED_REGION, "limit": 1, "offset": offset})
        )
        seen.extend(row["id"] for row in rows)

    assert producers["c"]["id"] not in seen
    assert all(row_id in seen for row_id in (producers["a"]["id"], producers["b"]["id"]))


def test_a_listing_with_no_pagination_params_takes_the_declared_defaults(api):
    """No filter and no pagination: the whole table comes back on one page of the default
    size, with nothing beyond it.

    PRD: "`limit` caps the number of rows returned; it defaults to 10 when omitted, may not
    be smaller than 1, and may not be larger than 100."

    Design: Corner/entities/grower_listing_returns_pagination_envelope_with_total_count_and_has_more
    """
    _three_producers_two_of_them_in_one_region()

    rows, meta = validate_paginated(api.list_growers(MANAGER))

    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
