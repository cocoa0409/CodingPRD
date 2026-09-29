"""Rules guarding the inventory, its taxability coverage, its paths and its models."""
from test_helpers import (
    ApiErrorId,
    BASE_ROOM_RATE_CENTS,
    CANONICAL_INCLUSIONS,
    OCCUPANCY_TAX_RATE_BPS,
    PUBLISHED_RESORT_PER_NIGHT_CENTS,
    PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT,
    SINGLE_FEE_INCLUSIONS,
    add_channel,
    add_draft_profile,
    add_fee,
    add_inclusion,
    add_second_jurisdiction,
    add_second_property,
    create_fee_program_payload,
    create_fee_inclusion_payload,
    create_profile_payload,
    create_property,
    create_remediation_payload,
    create_resort_fee_payload,
    create_revenue_impact_model_payload,
    create_taxability_rule,
    deploy_profile,
    move_clock_to,
    read_fee_program,
    read_profile,
    read_property,
    remediate_profile,
    setup_configuration,
    setup_deployed_profile,
    setup_program_under_review,
    setup_published_program,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COMPLIANCE, LIAISON, REVENUE

VOICE_CHANNEL = {
    "name": "Reservations Voice Desk",
    "channel_type": "VOICE",
    "supports_total_price_display": False,
    "supports_itemization": False,
}
TOTAL_ONLY_CHANNEL = {
    "name": "Voicebook Reservations",
    "channel_type": "VOICE",
    "supports_total_price_display": True,
    "supports_itemization": False,
}
CAPABLE_GDS = {
    "name": "WorldGDS Terminal",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}
CONFIRMATION_ONLY_PROFILE = {
    "first_quote_shows_total": True,
    "itemized_at_first_quote": False,
    "disclosure_placement": "CONFIRMATION_ONLY",
}
NO_TOTAL_PROFILE = {
    "first_quote_shows_total": False,
    "itemized_at_first_quote": True,
    "disclosure_placement": "RATE_DETAILS",
}
TWO_RULE_SPEC = {
    "RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS),
    "DESTINATION": ("TAXABLE_IF_MANDATORY", OCCUPANCY_TAX_RATE_BPS),
}
OPTIONAL_SPA_FEE = {
    "code": "SPA_LUX",
    "label": "Luxury Spa Package",
    "classification": "OPTIONAL",
    "basis": "PER_STAY",
    "amount_cents": 5000,
    "disclosure_text": "An optional luxury spa package may be added to this stay.",
}


def test_a_path_cannot_be_opened_against_an_unpublished_inventory(api):
    """The payload is well formed and its token current, so only the status refuses.

    PRD 3.3: "The referenced fee program must be in `PUBLISHED` status, and a
    draft, under-review or superseded program is rejected with
    `ERR_FEE_PROGRAM_NOT_PUBLISHED` (HTTP 409). The create also carries the
    `expected_fee_program_version` concurrency token of §2.7." PRD 3.9 repeats the
    same gate: "The referenced program must be `PUBLISHED`, an unpublished
    program being rejected with `ERR_FEE_PROGRAM_NOT_PUBLISHED` (HTTP 409)."

    Design: Corner/validations/disclosure_profile_on_an_unpublished_program_is_rejected
    """
    env = setup_program_under_review()
    under_review = read_fee_program(env["program"]["id"])
    assert under_review["status"] == "UNDER_REVIEW"

    payload = create_profile_payload(
        env["property"]["id"],
        env["channel"]["id"],
        under_review["id"],
        under_review["version"],
    )
    validate_error(
        api.create_channel_disclosure_profile(payload, REVENUE),
        ApiErrorId.ERR_FEE_PROGRAM_NOT_PUBLISHED,
        409,
    )

    profiles, meta = validate_paginated(
        api.list_channel_disclosure_profiles(
            REVENUE, {"property_id": env["property"]["id"], "limit": 100}
        )
    )
    assert profiles == []
    assert meta["total_count"] == 0

    validate_error(
        api.create_revenue_impact_model(
            create_revenue_impact_model_payload(
                env["property"]["id"],
                under_review["id"],
                scenario="STATUS_QUO",
                roll_in_fee_codes=[],
            ),
            REVENUE,
        ),
        ApiErrorId.ERR_FEE_PROGRAM_NOT_PUBLISHED,
        409,
    )

    validate_success(
        api.publish_fee_program(
            under_review["id"], "Attested against the county mandate.", COMPLIANCE
        )
    )
    published = read_fee_program(under_review["id"])
    payload["expected_fee_program_version"] = published["version"]
    created = validate_success(
        api.create_channel_disclosure_profile(payload, REVENUE), 201
    )
    assert created["status"] == "DRAFT"


def test_a_repair_that_only_clears_the_flag_floor_cannot_be_signed_off(api):
    """Sixty-five leaves the flag threshold behind but misses the sign-off bar.

    PRD 3.3: "Confirmation is a `ComplianceOfficer` action and moves a profile
    `REMEDIATED → DEPLOYED`, closing the cycle
    `DEPLOYED → FLAGGED → REMEDIATED → DEPLOYED`. It requires the profile's
    recomputed `disclosure_score` to be at or above 80: exactly 80 passes, 79 does
    not and is rejected with `ERR_REMEDIATION_SCORE_INSUFFICIENT` (HTTP 409),
    leaving the operator to remediate again — which is why a path may accumulate
    several remediation rounds."

    Design: Corner/validations/confirm_remediation_below_the_confirm_threshold_is_rejected
    """
    env = setup_deployed_profile(profile_overrides=CONFIRMATION_ONLY_PROFILE)
    assert env["profile"]["disclosure_score"] == 53

    flagged = validate_success(api.audit_profile(env["profile"]["id"], COMPLIANCE))
    assert flagged["status"] == "FLAGGED"
    assert flagged["disclosure_score"] == 53

    partly_repaired = remediate_profile(
        env,
        create_remediation_payload(
            itemized_at_first_quote=False, disclosure_placement="RATE_DETAILS"
        ),
    )
    assert partly_repaired["status"] == "REMEDIATED"

    weak = read_profile(env["profile"]["id"])
    assert weak["disclosure_score"] == 65

    validate_error(
        api.confirm_remediation(weak["id"], COMPLIANCE),
        ApiErrorId.ERR_REMEDIATION_SCORE_INSUFFICIENT,
        409,
    )

    still_remediated = read_profile(weak["id"])
    assert still_remediated["status"] == "REMEDIATED"
    assert still_remediated["remediation_round"] == 1
    # REMEDIATED has no outgoing remediate edge, so the repair had to be right.
    validate_error(
        api.remediate_profile(weak["id"], create_remediation_payload(), REVENUE),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )

    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 65
    assert prop["disclosure_posture"] == "AT_RISK"

    # A full repair on a second path clears the same bar it just missed.
    gds = add_channel(env, "gds_channel", **CAPABLE_GDS)
    sibling = deploy_profile(
        env,
        profile=add_draft_profile(env, channel=gds, **CONFIRMATION_ONLY_PROFILE),
    )
    validate_success(api.audit_profile(sibling["id"], COMPLIANCE))
    repaired = remediate_profile(
        env, create_remediation_payload(), profile=sibling, headers=REVENUE
    )
    assert repaired["disclosure_score"] == 100
    signed_off = validate_success(api.confirm_remediation(sibling["id"], COMPLIANCE))
    assert signed_off["status"] == "DEPLOYED"


def test_a_jurisdictions_total_mandate_blocks_deployment_but_not_drafting(api):
    """The same silent path is legal in DRAFT and unshippable under the mandate.

    PRD 3.3: "Where the property's jurisdiction has `first_quote_total_required`
    true, the profile must have `first_quote_shows_total` true; a profile that
    hides the total is rejected with `ERR_TOTAL_PRICE_DISPLAY_REQUIRED` (HTTP
    422). A profile may perfectly legitimately be *drafted* with
    `first_quote_shows_total` false, but in such a jurisdiction it can never reach
    `DEPLOYED` or `REMEDIATED`."

    Design: Corner/validations/deploying_a_profile_without_total_price_display_is_rejected
    """
    env = setup_published_program()
    assert env["jurisdiction"]["first_quote_total_required"] is True

    drafted = add_draft_profile(env, **NO_TOTAL_PROFILE)
    assert drafted["status"] == "DRAFT"
    assert drafted["disclosure_score"] == 50

    validate_error(
        api.deploy_profile(drafted["id"], COMPLIANCE),
        ApiErrorId.ERR_TOTAL_PRICE_DISPLAY_REQUIRED,
        422,
    )

    refused = read_profile(drafted["id"])
    assert refused["status"] == "DRAFT"
    assert read_property(env["property"]["id"])["min_channel_disclosure_score"] is None

    # The flag decides, not the profile: the same switches ship where it is false.
    permissive = setup_published_program(
        jurisdiction_overrides={
            "code": "US-AZ-MARICOPA",
            "name": "Maricopa County, Arizona",
            "first_quote_total_required": False,
        }
    )
    elsewhere = add_draft_profile(permissive, **NO_TOTAL_PROFILE)
    deployed = validate_success(api.deploy_profile(elsewhere["id"], COMPLIANCE))
    assert deployed["status"] == "DEPLOYED"
    assert deployed["disclosure_score"] == 50


def test_a_path_may_not_claim_a_capability_its_channel_lacks(api):
    """Claiming itemisation on a voice desk is refused; admitting nothing is not.

    PRD 3.3: "A profile may not claim a behaviour its channel cannot perform:
    claiming `first_quote_shows_total` true on a channel whose
    `supports_total_price_display` is false, or `itemized_at_first_quote` true on
    a channel whose `supports_itemization` is false, is rejected with
    `ERR_CHANNEL_CAPABILITY_MISMATCH` (HTTP 422) at creation and again at
    remediation."

    Design: Corner/validations/profile_claiming_itemization_on_an_incapable_channel_is_rejected
    """
    env = setup_published_program()
    voice = add_channel(env, "voice_channel", **VOICE_CHANNEL)
    program = read_fee_program(env["program"]["id"])

    def voice_payload(**switches):
        return create_profile_payload(
            env["property"]["id"],
            voice["id"],
            program["id"],
            read_fee_program(program["id"])["version"],
            **switches,
        )

    validate_error(
        api.create_channel_disclosure_profile(
            voice_payload(
                first_quote_shows_total=False,
                itemized_at_first_quote=True,
                disclosure_placement="ABSENT",
            ),
            REVENUE,
        ),
        ApiErrorId.ERR_CHANNEL_CAPABILITY_MISMATCH,
        422,
    )
    validate_error(
        api.create_channel_disclosure_profile(
            voice_payload(
                first_quote_shows_total=True,
                itemized_at_first_quote=False,
                disclosure_placement="ABSENT",
            ),
            REVENUE,
        ),
        ApiErrorId.ERR_CHANNEL_CAPABILITY_MISMATCH,
        422,
    )

    profiles, meta = validate_paginated(
        api.list_channel_disclosure_profiles(
            REVENUE, {"channel_id": voice["id"], "limit": 100}
        )
    )
    assert profiles == []
    assert meta["total_count"] == 0

    # The honest path is accepted and merely scores nothing after the penalty.
    honest = validate_success(
        api.create_channel_disclosure_profile(
            voice_payload(
                first_quote_shows_total=False,
                itemized_at_first_quote=False,
                disclosure_placement="ABSENT",
            ),
            REVENUE,
        ),
        201,
    )
    assert honest["status"] == "DRAFT"
    assert honest["disclosure_score"] == 0

    # Remediation re-evaluates the same clauses against the new switches.
    half_capable = setup_deployed_profile(
        jurisdiction_overrides={
            "code": "US-AZ-MARICOPA",
            "name": "Maricopa County, Arizona",
            "first_quote_total_required": False,
            "itemization_required_on_folio": False,
        },
        channel_overrides=TOTAL_ONLY_CHANNEL,
        profile_overrides=CONFIRMATION_ONLY_PROFILE,
    )
    assert half_capable["channel"]["supports_itemization"] is False
    assert half_capable["profile"]["disclosure_score"] == 53
    validate_success(api.audit_profile(half_capable["profile"]["id"], COMPLIANCE))
    assert read_profile(half_capable["profile"]["id"])["status"] == "FLAGGED"

    response = api.remediate_profile(
        half_capable["profile"]["id"], create_remediation_payload(), REVENUE
    )
    validate_error(response, ApiErrorId.ERR_CHANNEL_CAPABILITY_MISMATCH, 422)
    assert read_profile(half_capable["profile"]["id"])["status"] == "FLAGGED"


def test_publication_needs_a_taxability_rule_for_every_mandatory_code(api):
    """Two of three codes covered is not coverage; the property's county decides.

    PRD 3.2: "a taxability rule must exist for the pair of the property's
    `jurisdiction_id` and the fee's `code` for every `MANDATORY` fee of the
    program, failing with `ERR_TAXABILITY_RULE_MISSING`." PRD 3.1: "Taxability is
    decided per fee code, per jurisdiction, and never globally."

    Design: Corner/validations/publishing_with_a_missing_taxability_rule_is_rejected
    """
    env = setup_program_under_review(taxability_spec=TWO_RULE_SPEC)
    note = "Attempting to publish with an incomplete rule set."

    validate_error(
        api.publish_fee_program(env["program"]["id"], note, COMPLIANCE),
        ApiErrorId.ERR_TAXABILITY_RULE_MISSING,
        422,
    )

    refused = read_fee_program(env["program"]["id"])
    assert refused["status"] == "UNDER_REVIEW"
    assert refused["published_at"] is None
    assert refused["total_mandatory_fee_cents_per_night"] == 0
    assert env["jurisdiction"]["mandatory_fee_ban"] is False

    # A rule for the same code in another county does not close the gap.
    elsewhere = add_second_jurisdiction(env)
    create_taxability_rule(elsewhere["id"], "WIFI_PREMIUM", "EXEMPT", None)
    validate_error(
        api.publish_fee_program(env["program"]["id"], note, COMPLIANCE),
        ApiErrorId.ERR_TAXABILITY_RULE_MISSING,
        422,
    )

    create_taxability_rule(env["jurisdiction"]["id"], "WIFI_PREMIUM", "EXEMPT", None)
    published = validate_success(
        api.publish_fee_program(env["program"]["id"], note, COMPLIANCE)
    )
    assert published["status"] == "PUBLISHED"
    assert published["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT
    )


def test_a_fee_code_is_unique_only_inside_its_own_inventory(api):
    """RESORT collides in one program and is free in the next; so is an inclusion.

    PRD 3.2: "Each fee carries a `code` of 1 to 32 characters composed of
    uppercase letters, digits and underscores, unique within its own program — a
    repeat is rejected with `ERR_DUPLICATE_FEE_CODE`". PRD 3.2 on the child rows:
    "a `service_code` of 1 to 32 characters, unique per fee, with a repeat
    rejected as `ERR_DUPLICATE_INCLUSION_CODE`".

    Design: Corner/validations/duplicate_fee_code_within_one_program_is_rejected
    """
    env = setup_configuration(taxability_spec={})
    first = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                env["property"]["id"], env["property"]["version"]
            ),
            REVENUE,
        ),
        201,
    )
    resort = add_fee(first["id"], create_resort_fee_payload())
    add_inclusion(resort["id"], CANONICAL_INCLUSIONS["RESORT"])
    second = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                env["property"]["id"],
                read_property(env["property"]["id"])["version"],
                version_label="FY27-Q1",
                effective_from="2026-12-01T00:00:00Z",
                effective_to="2027-03-01T00:00:00Z",
            ),
            REVENUE,
        ),
        201,
    )
    recycled = {
        "code": "RESORT",
        "label": "Resort Fee v2",
        "classification": "OPTIONAL",
        "basis": "PER_NIGHT",
        "amount_cents": 800,
        "disclosure_text": "A second fee reusing the RESORT code entirely.",
    }

    validate_error(
        api.create_fee(first["id"], recycled, REVENUE),
        ApiErrorId.ERR_DUPLICATE_FEE_CODE,
        409,
    )
    fees, meta = validate_paginated(
        api.list_fees(REVENUE, {"fee_program_id": first["id"], "limit": 100})
    )
    assert meta["total_count"] == 1
    assert [fee["code"] for fee in fees] == ["RESORT"]

    # One parent over, the same literal string is legal again.
    twin = validate_success(api.create_fee(second["id"], recycled, REVENUE), 201)
    assert twin["code"] == "RESORT"
    assert twin["classification"] == "OPTIONAL"

    validate_error(
        api.create_fee_inclusion(
            resort["id"], create_fee_inclusion_payload(service_code="POOL_ACCESS"), REVENUE
        ),
        ApiErrorId.ERR_DUPLICATE_INCLUSION_CODE,
        409,
    )
    assert validate_success(api.get_fee(resort["id"], REVENUE))["inclusion_count"] == 1

    reused = validate_success(
        api.create_fee_inclusion(
            twin["id"], create_fee_inclusion_payload(service_code="POOL_ACCESS"), REVENUE
        ),
        201,
    )
    assert reused["service_code"] == "POOL_ACCESS"


def test_three_uniqueness_scopes_are_exercised_from_one_estate(api):
    """A global code, a per-jurisdiction rule pair, a per-jurisdiction docket.

    PRD 3.1: "it must be between 3 and 32 characters long, composed only of
    uppercase letters, digits and hyphens, and globally unique; a second
    jurisdiction offered the same `code` is rejected with
    `ERR_DUPLICATE_JURISDICTION_CODE`." PRD 3.1: "the pair of jurisdiction and fee
    code is unique across the whole rule set — a duplicate is rejected with
    `ERR_DUPLICATE_TAXABILITY_RULE`." PRD 3.8: "The pair of `jurisdiction_id` and
    `docket_number` is unique, a collision being rejected with
    `ERR_DUPLICATE_DOCKET_NUMBER` (HTTP 409)."

    Design: Corner/validations/duplicate_jurisdiction_code_is_rejected
    """
    env = setup_configuration(
        taxability_spec={"RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS)}
    )
    arizona = add_second_jurisdiction(env)
    env["property_2"] = add_second_property(env, "property_2")
    env["property_az"] = create_property(
        arizona["id"], name="Desert Bloom Suites", brand_code="DBS"
    )
    validate_success(
        api.create_regulator_inquiry(
            {
                "jurisdiction_id": env["jurisdiction"]["id"],
                "property_id": env["property"]["id"],
                "docket_number": "NV-2026-0091",
                "channel_scope": ["OTA"],
                "response_due_at": "2026-10-01T00:00:00Z",
            },
            LIAISON,
        ),
        201,
    )

    validate_error(
        api.create_jurisdiction(
            {
                "code": "US-NV-CLARK",
                "name": "Clark County Nevada (duplicate)",
                "occupancy_tax_rate_bps": 1400,
                "first_quote_total_required": False,
                "itemization_required_on_folio": False,
                "mandatory_fee_ban": True,
                "opt_out_mandate": False,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_JURISDICTION_CODE,
        409,
    )
    _rows, meta = validate_paginated(api.list_jurisdictions(ADMIN, {"limit": 100}))
    assert meta["total_count"] == 2
    incumbent = validate_success(
        api.get_jurisdiction(env["jurisdiction"]["id"], ADMIN)
    )
    assert incumbent["occupancy_tax_rate_bps"] == OCCUPANCY_TAX_RATE_BPS
    assert incumbent["mandatory_fee_ban"] is False

    validate_error(
        api.create_taxability_rule(
            {
                "jurisdiction_id": env["jurisdiction"]["id"],
                "fee_code": "RESORT",
                "taxability": "EXEMPT",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_TAXABILITY_RULE,
        409,
    )
    twin_rule = create_taxability_rule(arizona["id"], "RESORT", "EXEMPT", None)
    assert twin_rule["fee_code"] == "RESORT"
    assert twin_rule["taxability"] == "EXEMPT"

    validate_error(
        api.create_regulator_inquiry(
            {
                "jurisdiction_id": env["jurisdiction"]["id"],
                "property_id": env["property_2"]["id"],
                "docket_number": "NV-2026-0091",
                "channel_scope": ["GDS"],
                "response_due_at": "2026-10-01T00:00:00Z",
            },
            LIAISON,
        ),
        ApiErrorId.ERR_DUPLICATE_DOCKET_NUMBER,
        409,
    )
    elsewhere = validate_success(
        api.create_regulator_inquiry(
            {
                "jurisdiction_id": arizona["id"],
                "property_id": env["property_az"]["id"],
                "docket_number": "NV-2026-0091",
                "channel_scope": ["OTA"],
                "response_due_at": "2026-10-01T00:00:00Z",
            },
            LIAISON,
        ),
        201,
    )
    assert elsewhere["docket_number"] == "NV-2026-0091"
    assert elsewhere["status"] == "RECEIVED"


def test_attestation_is_refused_once_the_clock_crosses_the_windows_start(api):
    """The same inventory was legal to draft and becomes unpublishable by time.

    PRD 3.2: "and `effective_from` must be at or after the current logical clock,
    since a program cannot be published into the past, failing with
    `ERR_EFFECTIVE_FROM_IN_PAST`." PRD 2.8: "At startup the clock reads exactly
    `2026-08-01T00:00:00Z` ... A `PlatformAdmin` moves it by supplying a
    `to_iso8601` instant, which may be earlier or later than the current
    reading."

    Design: Corner/validations/publishing_a_program_whose_window_has_already_started_is_rejected
    """
    env = setup_program_under_review()
    note = "Late attestation attempt."
    assert env["program"]["effective_from"].startswith("2026-09-01")

    move_clock_to("2026-09-02T00:00:00Z")
    validate_error(
        api.publish_fee_program(env["program"]["id"], note, COMPLIANCE),
        ApiErrorId.ERR_EFFECTIVE_FROM_IN_PAST,
        422,
    )
    refused = read_fee_program(env["program"]["id"])
    assert refused["status"] == "UNDER_REVIEW"
    assert refused["published_at"] is None
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 0

    # One second past the boundary is still the past.
    move_clock_to("2026-09-01T00:00:01Z")
    validate_error(
        api.publish_fee_program(env["program"]["id"], note, COMPLIANCE),
        ApiErrorId.ERR_EFFECTIVE_FROM_IN_PAST,
        422,
    )

    # Equality is admitted: at or after the clock is the rule.
    move_clock_to("2026-09-01T00:00:00Z")
    published = validate_success(
        api.publish_fee_program(env["program"]["id"], note, COMPLIANCE)
    )
    assert published["status"] == "PUBLISHED"
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 1


def test_a_model_may_only_roll_in_mandatory_codes_of_its_own_program(api):
    """The optional code answers with rank 33 even though rank 34 also fails.

    PRD 3.9: "Every code in `roll_in_fee_codes` must name a fee of that program
    whose classification is `MANDATORY`, with no duplicates; `OPTIONAL` and
    `CONDITIONAL` fees never enter the model and may not appear in the array, a
    violation being rejected with `ERR_ROLL_IN_FEE_NOT_MANDATORY` (HTTP 422)."
    PRD 2.6 ranks that rule at "33. Roll-in code that is not a mandatory fee —
    `ERR_ROLL_IN_FEE_NOT_MANDATORY`." above "34. Roll-in set inconsistent with
    the declared scenario — `ERR_ROLL_IN_SCENARIO_MISMATCH`."

    Design: Corner/validations/roll_in_model_naming_an_optional_fee_is_rejected
    """
    env = setup_published_program(
        fee_payloads=[create_resort_fee_payload(), OPTIONAL_SPA_FEE],
        inclusion_spec=SINGLE_FEE_INCLUSIONS,
        taxability_spec={"RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS)},
    )
    assert env["program"]["fee_count"] == 2
    assert env["program"]["mandatory_fee_count"] == 1

    def model(**overrides):
        return create_revenue_impact_model_payload(
            env["property"]["id"], env["program"]["id"], **overrides
        )

    error = validate_error(
        api.create_revenue_impact_model(
            model(scenario="PARTIAL_ROLL_IN", roll_in_fee_codes=["SPA_LUX"]), REVENUE
        ),
        ApiErrorId.ERR_ROLL_IN_FEE_NOT_MANDATORY,
        422,
    )
    assert error["error_id"] != ApiErrorId.ERR_ROLL_IN_SCENARIO_MISMATCH

    _rows, meta = validate_paginated(
        api.list_revenue_impact_models(
            REVENUE, {"fee_program_id": env["program"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0

    # A code naming no fee of this program fails the same rule.
    validate_error(
        api.create_revenue_impact_model(
            model(scenario="PARTIAL_ROLL_IN", roll_in_fee_codes=["DESTINATION"]),
            REVENUE,
        ),
        ApiErrorId.ERR_ROLL_IN_FEE_NOT_MANDATORY,
        422,
    )

    # With one mandatory code there is no legal proper non-empty subset at all.
    validate_error(
        api.create_revenue_impact_model(
            model(scenario="PARTIAL_ROLL_IN", roll_in_fee_codes=["RESORT"]), REVENUE
        ),
        ApiErrorId.ERR_ROLL_IN_SCENARIO_MISMATCH,
        422,
    )

    full = validate_success(
        api.create_revenue_impact_model(
            model(scenario="FULL_ROLL_IN", roll_in_fee_codes=["RESORT"]), REVENUE
        ),
        201,
    )
    assert full["baseline_adr_cents"] == BASE_ROOM_RATE_CENTS
    assert full["scenario"] == "FULL_ROLL_IN"


def test_the_code_list_must_agree_exactly_with_the_declared_scenario(api):
    """The same three codes are lawful under one scenario and unlawful under two.

    PRD 3.9: "The array must then agree with the declared `scenario`:
    `STATUS_QUO` requires it to be empty, `FULL_ROLL_IN` requires it to name
    **every** mandatory code of the program, and `PARTIAL_ROLL_IN` requires a
    non-empty **proper** subset. A non-empty array under `STATUS_QUO`, an
    incomplete array under `FULL_ROLL_IN`, or an empty or complete array under
    `PARTIAL_ROLL_IN` is rejected with `ERR_ROLL_IN_SCENARIO_MISMATCH` (HTTP
    422)."

    Design: Corner/validations/roll_in_codes_that_contradict_the_declared_scenario_are_rejected
    """
    env = setup_published_program()
    every_code = ["RESORT", "DESTINATION", "WIFI_PREMIUM"]
    assert env["program"]["mandatory_fee_count"] == 3

    def model(**overrides):
        return create_revenue_impact_model_payload(
            env["property"]["id"], env["program"]["id"], **overrides
        )

    for scenario, codes in (
        ("STATUS_QUO", ["RESORT"]),
        ("FULL_ROLL_IN", ["RESORT", "DESTINATION"]),
        ("PARTIAL_ROLL_IN", []),
        ("PARTIAL_ROLL_IN", every_code),
    ):
        validate_error(
            api.create_revenue_impact_model(
                model(scenario=scenario, roll_in_fee_codes=codes), REVENUE
            ),
            ApiErrorId.ERR_ROLL_IN_SCENARIO_MISMATCH,
            422,
        )

    status_quo = validate_success(
        api.create_revenue_impact_model(
            model(scenario="STATUS_QUO", roll_in_fee_codes=[]), REVENUE
        ),
        201,
    )
    assert status_quo["scenario"] == "STATUS_QUO"
    assert status_quo["baseline_adr_cents"] == BASE_ROOM_RATE_CENTS
    assert status_quo["modeled_adr_cents"] == status_quo["baseline_adr_cents"]

    full = validate_success(
        api.create_revenue_impact_model(
            model(scenario="FULL_ROLL_IN", roll_in_fee_codes=every_code), REVENUE
        ),
        201,
    )
    assert full["modeled_adr_cents"] == (
        BASE_ROOM_RATE_CENTS + PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT
    )

    partial = validate_success(
        api.create_revenue_impact_model(
            model(scenario="PARTIAL_ROLL_IN", roll_in_fee_codes=["RESORT"]), REVENUE
        ),
        201,
    )
    assert partial["modeled_adr_cents"] == (
        BASE_ROOM_RATE_CENTS + PUBLISHED_RESORT_PER_NIGHT_CENTS
    )
