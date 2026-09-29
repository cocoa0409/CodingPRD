"""Entity record and field contracts for the residual earthquake program.

The program keeps fourteen kinds of record, and this module holds the reading of
each record as a record: the fields an enrollment, a registration, a dwelling
description, a funding cycle, a quote and an immutable assessment ledger line
carry back to the caller, the values the server itself mints rather than accepts
from the body, the defaults that stand in for omitted optional inputs, the
domain each enum and each amount is confined to, the not-found code that belongs
to each resource kind, the foreign keys that must resolve to a real row before
any business rule runs, and the pagination block that a filtered collection read
reports around its page of rows.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLAIM_ADJUSTER_ALT_HEADERS,
    CLAIM_ADJUSTER_HEADERS,
    GRANT_REVIEWER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
)
from test_helpers.test_users import make_insurer_headers, make_policyholder_headers


def _same_instant(actual, expected_zulu):
    """True when a returned instant names the expected moment.

    The program writes instants as ISO 8601 UTC, and a whole-second moment may be
    carried with or without its three fractional digits; both spell the same
    reading of the logical clock.
    """
    assert isinstance(actual, str), f"expected an instant string, got {actual!r}"
    stem = expected_zulu[:-1]
    return actual in (expected_zulu, f"{stem}.000Z")


def test_01_enrolling_an_insurer_returns_every_declared_field_at_its_opening_value(api):
    """PRD §4: "Endpoints that bring a new resource into existence answer with HTTP 201 and the created resource in `data`; endpoints that read, that modify an existing resource, or that drive a state transition answer with HTTP 200 and the affected resource in `data`."

    PRD §2.4: "Every resource carries an `id` that the server mints as a UUID with no type prefix — clients never supply or predict it."

    PRD §2.4: "Thirteen of the fourteen resource kinds — `Policyholder`, `ParticipatingInsurer`, `Dwelling`, `MandatoryOffer`, `Policy`, `GrantCycle`, `RetrofitGrant`, `Contractor`, `RetrofitProject`, `Inspection`, `CatastropheEvent`, `ReinsuranceLayer` and `Claim` — additionally carry `updated_at`, in the same format, and `version`, an integer that starts at 1 when the row is created and increases by exactly one on every mutation of that row."

    PRD §3.1: "A freshly enrolled insurer starts with `status` set to `ACTIVE` and `compliance_status` set to `COMPLIANT`, and with all five of its running counters at zero: `offers_recorded_count`, `undocumented_decline_count`, `last_take_up_rate_bp`, `assessment_balance_cents` and `policies_bound_count`."

    Design: Corner/entities/create_participating_insurer_returns_envelope_and_all_declared_fields
    """
    response = api.create_insurer(
        factories.create_insurer_payload(
            name="Cascade Mutual", naic_code="20001", market_share_pct=12.5
        ),
        PROGRAM_ADMIN_HEADERS,
    )
    insurer = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single enrollment is one resource, not a collection: {body['response_type']}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {body['meta']['api_request_id']}"
    )

    assertions.assert_insurer_shape(insurer)
    assert is_valid_uuid(insurer["id"]), f"insurer id is not a bare UUID: {insurer['id']}"
    assert insurer["version"] == 1, f"a newly enrolled row opens at version 1: {insurer['version']}"

    assert insurer["name"] == "Cascade Mutual"
    assert insurer["naic_code"] == "20001"
    assert insurer["market_share_pct"] == 12.5
    assert insurer["status"] == "ACTIVE", f"participation opens ACTIVE: {insurer['status']}"
    assert insurer["compliance_status"] == "COMPLIANT", (
        f"the offer-duty posture opens COMPLIANT: {insurer['compliance_status']}"
    )
    for counter in (
        "offers_recorded_count",
        "undocumented_decline_count",
        "last_take_up_rate_bp",
        "assessment_balance_cents",
        "policies_bound_count",
    ):
        assert insurer[counter] == 0, f"{counter} must open at zero, got {insurer[counter]}"


def test_02_reading_a_funding_cycle_echoes_the_pool_ledger_with_its_uncommitted_residual(api):
    """PRD §3.5: "A new cycle opens with `status` `OPEN`, `reserved_cents` and `disbursed_cents` at zero, `uncommitted_cents` equal to `total_pool_cents`, and `version` at 1."

    PRD §3.5: "Three figures keep the pool honest, and the third is the residual of the first two: `reserved_cents` is the sum of the awards on this cycle's grants currently in `FUNDS_RESERVED`, `disbursed_cents` is the sum of the awards on its grants in `VERIFIED_COMPLETE`, and `uncommitted_cents` is `total_pool_cents` less `reserved_cents` less `disbursed_cents`."

    Design: Corner/entities/retrieve_grant_cycle_returns_the_stored_row_with_derived_uncommitted
    """
    created = fixtures.create_grant_cycle(
        api,
        program_track="BRACE_AND_BOLT",
        label="2026 Retrieval Cycle",
        opens_at="2026-07-01T00:00:00Z",
        closes_at="2026-12-31T00:00:00Z",
        total_pool_cents=4000000,
    )

    cycle = validate_success(api.get_grant_cycle(created["id"], GRANT_REVIEWER_HEADERS))
    assertions.assert_grant_cycle_shape(cycle)

    assert cycle["id"] == created["id"]
    assert cycle["program_track"] == "BRACE_AND_BOLT"
    assert cycle["label"] == "2026 Retrieval Cycle"
    assert _same_instant(cycle["opens_at"], "2026-07-01T00:00:00Z"), (
        f"the stored application window opening was not echoed: {cycle['opens_at']}"
    )
    assert _same_instant(cycle["closes_at"], "2026-12-31T00:00:00Z"), (
        f"the stored application window closing was not echoed: {cycle['closes_at']}"
    )
    assert cycle["total_pool_cents"] == 4000000
    assert cycle["reserved_cents"] == 0
    assert cycle["disbursed_cents"] == 0
    assert cycle["uncommitted_cents"] == 4000000, (
        "an untouched cycle's uncommitted figure is its whole pool, not null: "
        f"{cycle['uncommitted_cents']}"
    )
    assert cycle["status"] == "OPEN"
    assert cycle["version"] == 1
    assertions.assert_grant_pool_conserved(cycle)


def test_03_listing_dwellings_reports_the_unpaginated_count_and_the_remaining_page_flag(api):
    """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before pagination and `has_more` is true exactly when rows remain beyond the current page."

    PRD §2.3: "`offset` defaults to 0 and counts rows to skip from the beginning of the result set."

    Design: Corner/entities/list_dwellings_is_paginated_with_total_count_and_has_more
    """
    holder = fixtures.create_policyholder(api)
    dwelling_ids = {
        fixtures.create_dwelling(api, holder["id"], street_address=f"{n} Mesa Road")["id"]
        for n in (1, 2, 3)
    }
    assert len(dwelling_ids) == 3, "the three dwellings must be three distinct rows"

    first_response = api.list_dwellings(
        {"policyholder_id": holder["id"], "limit": 2, "offset": 0}, PROGRAM_ADMIN_HEADERS
    )
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array", (
        "a collection read answers with an array envelope"
    )
    assert len(first_rows) == 2, f"limit 2 must return exactly two rows, got {len(first_rows)}"
    assert first_meta["total_count"] == 3, (
        f"total_count counts every matching row, not the page: {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, "a third row remains beyond the first page"
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_rows, second_meta = validate_paginated(
        api.list_dwellings(
            {"policyholder_id": holder["id"], "limit": 2, "offset": 2}, PROGRAM_ADMIN_HEADERS
        )
    )
    assert len(second_rows) == 1, f"one row is left after skipping two, got {len(second_rows)}"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False, "nothing remains beyond the last page"
    assert second_meta["offset"] == 2

    walked = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(set(walked)) == 3, f"the offset walk saw a row twice: {walked}"
    assert set(walked) == dwelling_ids, "the walk returned rows other than the three created"
    for row in first_rows + second_rows:
        assertions.assert_dwelling_shape(row)
        assert row["policyholder_id"] == holder["id"]


def test_04_reading_an_unknown_dwelling_answers_with_the_dwelling_not_found_code(api):
    """PRD §2.4: "Because the topology is flat, most paths carry a single identifier, and a request naming a row that does not exist is rejected with the 404 belonging to that resource kind — `ERR_POLICYHOLDER_NOT_FOUND`, `ERR_INSURER_NOT_FOUND`, `ERR_DWELLING_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_GRANT_CYCLE_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_LAYER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or `ERR_ALLOCATION_NOT_FOUND`, each with HTTP status 404."

    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/retrieve_unknown_dwelling_returns_dwelling_not_found
    """
    response = api.get_dwelling(constants.NON_EXISTENT_ID, PROGRAM_ADMIN_HEADERS)

    error = validate_error(response, ApiErrorId.DWELLING_NOT_FOUND)
    assert response.json()["response_type"] == "error", (
        "a missing row is an error envelope, not a success envelope carrying null"
    )
    assert error["message"].strip(), "the error must explain itself"


def test_05_a_dwelling_missing_any_required_hazard_input_is_refused_and_not_persisted(api):
    """PRD §3.2: "Creating one requires the owner through `policyholder_id`, the `street_address` of the insured structure, the `county_hazard_tier` of its county — `TIER_1`, `TIER_2` or `TIER_3`, in ascending seismicity — the site's `soil_class` from the geotechnical screen, which is `ROCK`, `STIFF`, `SOFT` or `LIQUEFACTION`, the `structure_type`, which is `WOOD_FRAME_SLAB`, `WOOD_FRAME_CRIPPLE_WALL`, `MASONRY_URM` or `MOBILE_HOME`, the `year_built` of original construction, and `dwelling_limit_cents`, the Coverage A dwelling limit that is the exposure base for both rating and the deductible."

    PRD §2.8: "Rung 10: every required body field must be present and not null, otherwise `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/dwelling_create_missing_required_inputs_is_rejected
    """
    holder = fixtures.create_policyholder(api)

    for omitted in ("dwelling_limit_cents", "street_address", "county_hazard_tier"):
        payload = factories.create_dwelling_payload(holder["id"], street_address="9 Absent Way")
        payload.pop(omitted)
        validate_error(
            api.create_dwelling(payload, PROGRAM_ADMIN_HEADERS),
            ApiErrorId.INVALID_REQUEST,
        )

    rows, meta = validate_paginated(
        api.list_dwellings({"policyholder_id": holder["id"]}, PROGRAM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"a refused creation must persist no partial dwelling, found {meta['total_count']}"
    )
    assert rows == [], f"a refused creation must persist no partial dwelling: {rows}"


def test_06_omitted_optional_registration_inputs_open_at_their_declared_defaults(api):
    """PRD §3.1: "A policyholder record carries the owner-occupant's `full_name`, an `email` that must be unique across the registry and is the address the program's public-education outreach targets, the five-character `county_code` of the mailing address, and an optional `outreach_campaign_code` that defaults to the string `NONE` and exists so that the program can report take-up by campaign."

    PRD §3.1: "Registry `status` starts at `ACTIVE` and may also be `INACTIVE`."

    PRD §3.2: "A new dwelling opens with `retrofit_status` at `NONE`, `verified_retrofit_scope` at `NONE` and `grant_lifetime_count` at zero."

    Design: Corner/entities/defaults_applied_when_optional_inputs_are_omitted
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)

    holder_payload = factories.create_policyholder_payload(
        full_name="Ines Kaur", county_code="06029"
    )
    holder_payload.pop("outreach_campaign_code")
    holder = validate_success(
        api.create_policyholder(holder_payload, PROGRAM_ADMIN_HEADERS), 201
    )
    assertions.assert_policyholder_shape(holder)
    assert holder["outreach_campaign_code"] == "NONE", (
        "an untagged registration carries the literal string NONE, not null or empty: "
        f"{holder['outreach_campaign_code']!r}"
    )
    assert holder["status"] == "ACTIVE", f"the registry opens ACTIVE: {holder['status']}"

    dwelling = validate_success(
        api.create_dwelling(
            factories.create_dwelling_payload(
                holder["id"],
                street_address="4 Default Lane",
                county_hazard_tier="TIER_3",
                soil_class="SOFT",
                year_built=1998,
                dwelling_limit_cents=15000000,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )
    assertions.assert_dwelling_shape(dwelling)
    assert dwelling["retrofit_status"] == "NONE", (
        f"a new dwelling has no retrofit posture yet: {dwelling['retrofit_status']}"
    )
    assert dwelling["verified_retrofit_scope"] == "NONE", (
        f"no scope is claimed on a new dwelling: {dwelling['verified_retrofit_scope']}"
    )
    assert dwelling["grant_lifetime_count"] == 0, (
        f"a new dwelling has never drawn on the pool: {dwelling['grant_lifetime_count']}"
    )


def test_07_an_untagged_mandatory_offer_opens_pending_on_a_sixty_day_window(api):
    """PRD §3.1: "Recording an offer requires the payload to name the discharging insurer through `insurer_id`, the recipient through `policyholder_id` and the covered structure through `dwelling_id`, and it may carry a `campaign_code` attributing the offer to a public-education campaign, which defaults to `NONE`."

    PRD §3.1: "The recorded offer opens in `PENDING` with `offer_round` set to 1, `offered_at` set to the current logical clock and `expires_at` set to sixty days after `offered_at`; `responded_at` stays null while the offer is unanswered, and the insurer's `offers_recorded_count` rises by one."

    Design: Corner/entities/defaults_applied_when_optional_inputs_are_omitted
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    insurer = fixtures.create_insurer(api, name="Default Valley Insurance", naic_code="20002")
    holder = fixtures.create_policyholder(api)
    dwelling = fixtures.create_dwelling(api, holder["id"])

    offer = validate_success(
        api.create_mandatory_offer(
            {
                "insurer_id": insurer["id"],
                "policyholder_id": holder["id"],
                "dwelling_id": dwelling["id"],
            },
            make_insurer_headers(insurer["id"]),
        ),
        201,
    )
    assertions.assert_mandatory_offer_shape(offer)

    assert offer["campaign_code"] == "NONE", (
        f"an unattributed offer carries the literal string NONE: {offer['campaign_code']!r}"
    )
    assert offer["offer_round"] == 1, f"the first round is round one: {offer['offer_round']}"
    assert offer["status"] == "PENDING", f"a fresh offer awaits an answer: {offer['status']}"
    assert offer["responded_at"] is None, (
        f"an unanswered offer has no response instant: {offer['responded_at']!r}"
    )
    assert _same_instant(offer["offered_at"], "2026-08-01T00:00:00Z"), (
        f"offered_at is the logical clock reading: {offer['offered_at']}"
    )
    assert _same_instant(offer["expires_at"], "2026-09-30T00:00:00Z"), (
        "the acceptance window runs sixty days from the offer: "
        f"{offer['expires_at']}"
    )


def test_08_a_quote_computes_its_own_premium_and_ignores_pricing_fields_in_the_body(api):
    """PRD §3.3: "Multiply the base rate per thousand by the exposure units and then by all six factors, in that order, keeping exact decimal arithmetic throughout."

    PRD §3.3: "The result is written to `base_premium_cents`, and `rating_variant` records which of the two variants produced it, taking the value `QUOTE_TIME` or `RENEWAL_TIME`."

    PRD §3.3: "Finally, `annual_premium_cents` — the amount actually billed — is `base_premium_cents` less whatever `mitigation_discount_cents` currently stands at, which at quote time is zero."

    PRD §3.3: "The quote copies the dwelling's owner into the policy's own `policyholder_id` so that ownership checks on the policy need no join, and it pins `rated_dwelling_limit_cents` from the dwelling's live `dwelling_limit_cents`."

    PRD §3.3: "The quote opens with `lifecycle_status` at `QUOTED`, `mitigation_status` at `UNMITIGATED`, `term_number` at 1, `mitigation_discount_cents` and `prorated_credit_cents` at zero, and both `effective_at` and `expires_at` null, since nothing is in force yet."

    PRD §3.3: "`quote_expires_at` is set to thirty days after the row's `created_at`."

    Design: Corner/entities/policy_computed_pricing_fields_are_derived_and_client_values_input_ignored
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = fixtures.setup_accepted_offer(
        api,
        dwelling_overrides={
            "street_address": "6 Ignore Court",
            "county_hazard_tier": "TIER_2",
            "soil_class": "STIFF",
            "structure_type": "WOOD_FRAME_SLAB",
            "year_built": 1990,
            "dwelling_limit_cents": 20000000,
        },
    )
    insurer_headers = make_insurer_headers(ctx["insurer"]["id"])

    payload = factories.create_policy_payload(
        ctx["dwelling"]["id"],
        ctx["insurer"]["id"],
        ctx["offer"]["id"],
        deductible_pct=10,
        contents_sublimit_cents=4000000,
        loss_of_use_sublimit_cents=1000000,
        base_premium_cents=1,
        annual_premium_cents=1,
        rating_variant="RENEWAL_TIME",
        mitigation_discount_cents=999,
    )
    policy = validate_success(api.create_policy(payload, insurer_headers), 201)
    assertions.assert_policy_shape(policy)

    # 320 cents per thousand for TIER_2, 200 exposure units, every factor neutral.
    assert policy["base_premium_cents"] == 64000, (
        f"the hazard rate must be computed, not read from the body: {policy['base_premium_cents']}"
    )
    assert policy["annual_premium_cents"] == 64000, (
        f"the billed premium is the base premium at quote time: {policy['annual_premium_cents']}"
    )
    assert policy["rating_variant"] == "QUOTE_TIME", (
        f"a quote rates under the quote-time variant: {policy['rating_variant']}"
    )
    assert policy["mitigation_discount_cents"] == 0, (
        f"a quote carries no discount: {policy['mitigation_discount_cents']}"
    )
    assert policy["prorated_credit_cents"] == 0
    assertions.assert_premium_ledger_consistent(policy)

    assert policy["policyholder_id"] == ctx["policyholder"]["id"], (
        "the owner is copied from the rated dwelling: "
        f"{policy['policyholder_id']} != {ctx['policyholder']['id']}"
    )
    assert policy["rated_dwelling_limit_cents"] == 20000000, (
        "the term snapshot is pinned from the dwelling's live limit: "
        f"{policy['rated_dwelling_limit_cents']}"
    )
    assert policy["lifecycle_status"] == "QUOTED"
    assert policy["mitigation_status"] == "UNMITIGATED"
    assert policy["term_number"] == 1
    assert policy["effective_at"] is None, f"nothing is in force yet: {policy['effective_at']!r}"
    assert policy["expires_at"] is None, f"nothing is in force yet: {policy['expires_at']!r}"
    assert _same_instant(policy["quote_expires_at"], "2026-08-31T00:00:00Z"), (
        f"the quote stands for thirty days: {policy['quote_expires_at']}"
    )


def test_09_dwelling_identity_and_retrofit_posture_are_server_minted_not_client_supplied(api):
    """PRD §2.4: "Every resource carries an `id` that the server mints as a UUID with no type prefix — clients never supply or predict it."

    PRD §2.4: "Thirteen of the fourteen resource kinds — `Policyholder`, `ParticipatingInsurer`, `Dwelling`, `MandatoryOffer`, `Policy`, `GrantCycle`, `RetrofitGrant`, `Contractor`, `RetrofitProject`, `Inspection`, `CatastropheEvent`, `ReinsuranceLayer` and `Claim` — additionally carry `updated_at`, in the same format, and `version`, an integer that starts at 1 when the row is created and increases by exactly one on every mutation of that row."

    PRD §3.2: "A new dwelling opens with `retrofit_status` at `NONE`, `verified_retrofit_scope` at `NONE` and `grant_lifetime_count` at zero."

    PRD §3.2: "There are exactly two ways to leave `NONE`."

    Design: Corner/entities/dwelling_system_fields_are_server_minted_and_client_values_input_ignored
    """
    holder = fixtures.create_policyholder(api)
    spoofed_id = "11111111-1111-4111-8111-111111111111"

    dwelling = validate_success(
        api.create_dwelling(
            factories.create_dwelling_payload(
                holder["id"],
                street_address="7 Spoof Street",
                structure_type="WOOD_FRAME_CRIPPLE_WALL",
                year_built=1970,
                id=spoofed_id,
                version=42,
                retrofit_status="VERIFIED",
                verified_retrofit_scope="CRIPPLE_WALL_BRACING",
                grant_lifetime_count=7,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )
    assertions.assert_dwelling_shape(dwelling)

    assert dwelling["id"] != spoofed_id, "the client must not be able to choose the identifier"
    assert is_valid_uuid(dwelling["id"]), f"the minted id is not a bare UUID: {dwelling['id']}"
    assert dwelling["version"] == 1, f"a new row opens at version 1, not 42: {dwelling['version']}"
    assert dwelling["retrofit_status"] == "NONE", (
        "a retrofit posture cannot be asserted in the create body: "
        f"{dwelling['retrofit_status']}"
    )
    assert dwelling["verified_retrofit_scope"] == "NONE", (
        f"no scope is verified on a new dwelling: {dwelling['verified_retrofit_scope']}"
    )
    assert dwelling["grant_lifetime_count"] == 0, (
        f"a new dwelling has drawn on no cycle: {dwelling['grant_lifetime_count']}"
    )
    assert is_iso8601_timestamp(dwelling["created_at"]), (
        f"created_at must be a server-minted UTC instant: {dwelling['created_at']}"
    )
    assert is_iso8601_timestamp(dwelling["updated_at"]), (
        f"updated_at must be a server-minted UTC instant: {dwelling['updated_at']}"
    )


def test_10_an_unknown_soil_class_outranks_an_out_of_range_vintage_or_coverage_limit(api):
    """PRD §2.8: "Every check in the system therefore occupies a fixed rung on one ordered ladder, and **the rung with the lowest number wins**: the server evaluates the rungs in ascending numeric order and returns the first violation it finds, without evaluating any later rung."

    PRD §2.8: "Rung 11: every enum-typed field must carry a value from its declared domain, otherwise `ERR_INVALID_ENUM_VALUE` (422)."

    PRD §2.8: "Rung 12: numeric domains must hold, otherwise `ERR_INVALID_AMOUNT` (422) — every field whose name ends in `_cents` must be zero or greater, `dwelling_limit_cents` must be at least 5,000,000 and at most 300,000,000 cents, `total_pool_cents` must be at least 100,000 cents, `project_cost_estimate_cents` must be strictly greater than zero, a payment's `amount_cents` must be strictly greater than zero, `market_share_pct` must be between 0 and 100 inclusive with at most two decimal places, `magnitude` must be between 4.0 and 9.5 inclusive with one decimal place, `ceded_pct` must be strictly greater than 0 and at most 1 with at most two decimal places, `layer_index` must be at least 1, and `year_built` must be between 1850 and 2026 inclusive; this rung guards dwelling creation, insurer enrollment, funding-cycle creation, catastrophe-event creation, reinsurance-layer creation, grant submission, first notice of loss and payment recording."

    Design: Corner/entities/out_of_domain_dwelling_and_policy_field_values_are_rejected
    """
    holder = fixtures.create_policyholder(api)

    validate_error(
        api.create_dwelling(
            factories.create_dwelling_payload(
                holder["id"], street_address="10 Domain Drive", soil_class="SANDY"
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INVALID_ENUM_VALUE,
    )

    validate_error(
        api.create_dwelling(
            factories.create_dwelling_payload(
                holder["id"], street_address="12 Domain Drive", year_built=1700
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INVALID_AMOUNT,
    )

    validate_error(
        api.create_dwelling(
            factories.create_dwelling_payload(
                holder["id"], street_address="14 Domain Drive", dwelling_limit_cents=1000000
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INVALID_AMOUNT,
    )

    _, meta = validate_paginated(
        api.list_dwellings({"policyholder_id": holder["id"]}, PROGRAM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"no out-of-domain dwelling may be persisted, found {meta['total_count']}"
    )


def test_11_a_deductible_outside_the_five_permitted_steps_is_refused_as_an_enum_defect(api):
    """PRD §3.3: "The payload names the rated structure through `dwelling_id`, the quoting carrier through `insurer_id`, and the accepted offer that authorises the sale through `accepted_offer_id`; it selects the household's `deductible_pct`, which must be one of 5, 10, 15, 20 or 25 percent of the dwelling limit; and it sets the two coverage sublimits, `contents_sublimit_cents` for Coverage C and `loss_of_use_sublimit_cents` for Coverage D."

    PRD §2.8: "Rung 11: every enum-typed field must carry a value from its declared domain, otherwise `ERR_INVALID_ENUM_VALUE` (422)."

    Design: Corner/entities/out_of_domain_dwelling_and_policy_field_values_are_rejected
    """
    ctx = fixtures.setup_accepted_offer(api)

    validate_error(
        api.create_policy(
            factories.create_policy_payload(
                ctx["dwelling"]["id"],
                ctx["insurer"]["id"],
                ctx["offer"]["id"],
                deductible_pct=12,
                contents_sublimit_cents=4000000,
                loss_of_use_sublimit_cents=1000000,
            ),
            make_insurer_headers(ctx["insurer"]["id"]),
        ),
        ApiErrorId.INVALID_ENUM_VALUE,
    )

    _, meta = validate_paginated(
        api.list_policies({"dwelling_id": ctx["dwelling"]["id"]}, PROGRAM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"a refused quote leaves no policy row behind, found {meta['total_count']}"
    )


def test_12_a_dwelling_naming_an_unknown_owner_is_refused_with_the_policyholder_code(api):
    """PRD §2.4: "The same catalogue governs identifiers supplied in a request body: `insurer_id`, `policyholder_id`, `dwelling_id`, `policy_id`, `accepted_offer_id`, `grant_cycle_id`, `grant_id`, `contractor_id`, `project_id` and `event_id` must each resolve to an existing row of their kind, and the failure carries that kind's not-found code."

    PRD §2.8: "Rung 5: every foreign-key identifier in the request body must resolve to an existing row — `insurer_id`, `policyholder_id`, `dwelling_id`, `policy_id`, `accepted_offer_id`, `grant_cycle_id`, `grant_id`, `contractor_id`, `project_id` and `event_id` — otherwise that kind's not-found code (404); this applies to every creating and linking operation."

    Design: Corner/entities/dwelling_requires_an_existing_policyholder_parent_not_found
    """
    validate_error(
        api.create_dwelling(
            factories.create_dwelling_payload(
                constants.NON_EXISTENT_ID,
                street_address="16 Orphan Row",
                county_hazard_tier="TIER_1",
                soil_class="ROCK",
                year_built=2005,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.POLICYHOLDER_NOT_FOUND,
    )


def test_13_an_accepted_offer_on_another_dwelling_cannot_authorise_this_quote(api):
    """PRD §2.8: "Rung 45: `accepted_offer_id` must name a `MandatoryOffer` whose `status` is `ACCEPTED` and whose `insurer_id` and `dwelling_id` both match the policy's, checked at quote time, again at bind and again at every renewal, otherwise `ERR_MANDATORY_OFFER_NOT_ACCEPTED` (409)."

    PRD §3.3: "A quote cannot be produced through a `SANCTIONED` or `WITHDRAWN` insurer, the offer named in `accepted_offer_id` must be in `ACCEPTED` with its own `insurer_id` and `dwelling_id` matching the policy's, and at most one policy per dwelling may sit in `ACTIVE` or `QUOTED` — a second live quote on the same structure collides with `ERR_DUPLICATE_ACTIVE_POLICY`."

    Design: Corner/entities/cross_reference_integrity_quote_rejects_an_offer_for_another_dwelling
    """
    insurer = fixtures.create_insurer(api, name="Crosswire Insurance", naic_code="20005")
    holder = fixtures.create_policyholder(api)
    dwelling_a = fixtures.create_dwelling(api, holder["id"], street_address="18 Crosswire Way")
    dwelling_b = fixtures.create_dwelling(api, holder["id"], street_address="20 Crosswire Way")

    offer_b = validate_success(
        api.create_mandatory_offer(
            factories.create_mandatory_offer_payload(
                insurer["id"], holder["id"], dwelling_b["id"]
            ),
            make_insurer_headers(insurer["id"]),
        ),
        201,
    )
    accepted_b = validate_success(
        api.respond_to_offer(
            offer_b["id"],
            factories.respond_to_offer_payload("ACCEPT"),
            make_policyholder_headers(holder["id"]),
        )
    )
    assert accepted_b["status"] == "ACCEPTED", "the setup offer must be accepted"

    validate_error(
        api.create_policy(
            factories.create_policy_payload(
                dwelling_a["id"], insurer["id"], offer_b["id"]
            ),
            make_insurer_headers(insurer["id"]),
        ),
        ApiErrorId.MANDATORY_OFFER_NOT_ACCEPTED,
    )

    policy = validate_success(
        api.create_policy(
            factories.create_policy_payload(
                dwelling_b["id"], insurer["id"], offer_b["id"]
            ),
            make_insurer_headers(insurer["id"]),
        ),
        201,
    )
    assert policy["lifecycle_status"] == "QUOTED", (
        f"the matching pair must quote cleanly: {policy['lifecycle_status']}"
    )
    assert policy["dwelling_id"] == dwelling_b["id"]
    assert policy["accepted_offer_id"] == offer_b["id"]


def test_14_a_levied_assessment_allocation_is_an_immutable_ledger_line(api):
    """PRD §2.4: "An allocation is an immutable ledger line struck at the moment an assessment is levied and never touched again, so it carries only `id` and `created_at`: it has no `updated_at` and no `version` field at all, and neither field appears in its representation."

    PRD §2.11: "Two collections are read-only in practice: assessment allocations exist solely as the output of a levy and can never be created, modified or deleted directly, and they are the only record of how a shortfall was spread."

    PRD §3.7: "`ceded_total_cents` is the sum of the `ceded_cents` of the participating layers, and `uncovered_cents` is the gross less `retained_cents` less `ceded_total_cents`, floored at zero — it is a residual and is never independently rounded."

    PRD §3.8: "`admin_loading_cents` is the shortfall multiplied by that rate, rounded half up to whole cents, and `assessment_total_cents` is the shortfall plus the loading."

    PRD §3.8: "One allocation row is created per assessable insurer, recording `event_id`, `insurer_id`, the insurer's `market_share_pct` at levy time as `market_share_pct_snapshot`, its `allocation_rank`, its `assessed_cents` and the boolean `absorbs_remainder`."

    PRD §3.8: "For the last rank, `assessed_cents` is `assessment_total_cents` less the sum of all the earlier ranks' `assessed_cents`, and `absorbs_remainder` is true — so the allocations sum to `assessment_total_cents` exactly, to the cent, with the rounding drift of every earlier rank absorbed by the last."

    PRD §3.8: "Each assessed insurer's `assessment_balance_cents` rises by its own `assessed_cents`, and the event's `version` rises by one."

    Design: Corner/entities/assessment_allocation_is_immutable_with_no_version_and_no_write_endpoint
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(
        api, name="Sole Assessable Insurance", naic_code="20006", market_share_pct=40.0
    )
    parties = fixtures.setup_parties(
        api,
        insurer=insurer,
        dwelling_overrides={
            "street_address": "22 Vineyard Rise",
            "county_hazard_tier": "TIER_1",
            "soil_class": "ROCK",
            "structure_type": "WOOD_FRAME_SLAB",
            "year_built": 2004,
            "dwelling_limit_cents": 300000000,
        },
    )
    ctx = fixtures.setup_bound_policy(
        api,
        parties=parties,
        deductible_pct=5,
        contents_sublimit_cents=1000000,
        loss_of_use_sublimit_cents=500000,
    )

    fixtures.create_reinsurance_layer(
        api,
        treaty_year=2026,
        layer_index=1,
        attachment_point_cents=100000000,
        limit_cents=50000000,
        ceded_pct=0.90,
    )
    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    event = fixtures.create_catastrophe_event(
        api,
        event_code="EQ-2026-IMMUTABLE",
        magnitude=7.0,
        occurred_at="2026-09-05T00:00:00Z",
        retention_cents=100000000,
    )
    declared = validate_success(api.declare_event(event["id"], None, PROGRAM_ADMIN_HEADERS))

    claim = validate_success(
        api.create_claim(
            factories.create_claim_payload(
                ctx["policy"]["id"],
                event["id"],
                declared["version"],
                structural_damage_cents=250000000,
                cosmetic_damage_cents=0,
                contents_damage_cents=0,
                loss_of_use_cents=0,
            ),
            CLAIM_ADJUSTER_HEADERS,
        ),
        201,
    )
    validate_success(api.adjust_claim_provisional(claim["id"], None, CLAIM_ADJUSTER_HEADERS))
    finalized = validate_success(
        api.finalize_claim_adjustment(claim["id"], None, CLAIM_ADJUSTER_ALT_HEADERS)
    )
    # 300,000,000 snapshot at a 5 per cent deductible leaves 235,000,000 payable.
    assert finalized["final_payable_cents"] == 235000000, (
        f"the final settlement must be 235,000,000: {finalized['final_payable_cents']}"
    )

    levied = validate_success(api.levy_assessment(event["id"], None, PROGRAM_ADMIN_HEADERS))
    assertions.assert_catastrophe_event_shape(levied)
    assert levied["status"] == "ASSESSMENT_LEVIED", (
        f"the levy moves the event on: {levied['status']}"
    )
    assert levied["retained_cents"] == 100000000
    assert levied["ceded_total_cents"] == 45000000
    assert levied["uncovered_cents"] == 90000000, (
        "the shortfall is the gross less retention less cession: "
        f"{levied['uncovered_cents']}"
    )
    assertions.assert_event_loss_conserved(levied)
    assert levied["assessment_shortfall_cents"] == 90000000, (
        f"the bare shortfall is pinned at levy time: {levied['assessment_shortfall_cents']}"
    )
    assert levied["admin_loading_cents"] == 1800000, (
        "a shortfall below 10,000,000,000 cents carries a two per cent loading: "
        f"{levied['admin_loading_cents']}"
    )
    assert levied["assessment_total_cents"] == 91800000, (
        f"the levied total is shortfall plus loading: {levied['assessment_total_cents']}"
    )

    rows, meta = validate_paginated(
        api.list_assessment_allocations({"event_id": event["id"]}, PROGRAM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"one allocation per assessable insurer, and there is one: {meta['total_count']}"
    )
    allocation = rows[0]
    assertions.assert_assessment_allocation_shape(allocation)
    assert allocation["event_id"] == event["id"]
    assert allocation["insurer_id"] == insurer["id"]
    assert allocation["market_share_pct_snapshot"] == 40.0, (
        f"the share is snapshotted at levy time: {allocation['market_share_pct_snapshot']}"
    )
    assert allocation["assessed_cents"] == 91800000, (
        "the sole assessable carrier absorbs the whole levied total: "
        f"{allocation['assessed_cents']}"
    )
    assert allocation["allocation_rank"] == 1
    assert allocation["absorbs_remainder"] is True, (
        "the last rank absorbs the remainder so the parts sum exactly"
    )
    assertions.assert_assessment_allocations_sum(rows, 91800000)

    read_back = validate_success(
        api.get_assessment_allocation(allocation["id"], make_insurer_headers(insurer["id"]))
    )
    assertions.assert_assessment_allocation_shape(read_back)
    assert read_back["assessed_cents"] == 91800000
    assert "updated_at" not in read_back, (
        "a ledger line that is never touched again carries no modification instant"
    )
    assert "version" not in read_back, (
        "a ledger line that is never touched again carries no version counter"
    )

    assessed_insurer = validate_success(api.get_insurer(insurer["id"], PROGRAM_ADMIN_HEADERS))
    assertions.assert_insurer_assessment_balance(assessed_insurer, 91800000)
