"""Requests that break two rules at once, where only the higher rank may answer."""
from test_helpers import (
    ApiErrorId,
    OCCUPANCY_TAX_RATE_BPS,
    add_fee,
    add_second_jurisdiction,
    add_second_property,
    create_fee_program_payload,
    create_property,
    create_resort_fee_payload,
    create_taxability_rule,
    read_fee_program,
    read_property,
    setup_configuration,
    setup_program_under_review,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COMPLIANCE, REVENUE

SUSPENDED_PROPERTY = {
    "name": "Shuttered Sands Inn",
    "brand_code": "SSI",
    "base_room_rate_cents": 19900,
    "status": "SUSPENDED",
}


def _stale_token_estate(api):
    """A live property bumped to version 2 beside a suspended one at version 1."""
    env = setup_configuration(taxability_spec={})
    live = env["property"]
    validate_success(
        api.create_fee_program(
            create_fee_program_payload(live["id"], live["version"]), REVENUE
        ),
        201,
    )
    env["live_version"] = read_property(live["id"])["version"]
    env["suspended"] = add_second_property(
        env, "suspended", **SUSPENDED_PROPERTY
    )
    return env


def test_a_stale_token_answers_before_the_suspended_property_is_noticed(api):
    """The 412 wins even though loading the property would reveal a 409 first.

    PRD 2.6: "Validation precedence across the whole API is global and total:
    when one request violates several rules, the response carries the error of
    the highest-precedence violated rule and no lower-precedence check is
    evaluated at all." The ladder puts "10. Stale `Property` version on
    fee-program creation — `ERR_STALE_PROPERTY_VERSION`." above "16. Property
    operating status — `ERR_PROPERTY_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/stale_property_version_outranks_property_not_active_on_program_create
    """
    env = _stale_token_estate(api)
    suspended = env["suspended"]

    assert env["live_version"] == 2
    assert suspended["version"] == 1
    assert suspended["status"] == "SUSPENDED"

    response = api.create_fee_program(
        create_fee_program_payload(suspended["id"], env["live_version"]), REVENUE
    )

    validate_error(response, ApiErrorId.ERR_STALE_PROPERTY_VERSION, 412)
    assert response.status_code != 409

    unchanged = read_property(suspended["id"])
    assert unchanged["version"] == 1
    assert unchanged["published_fee_program_count"] == 0


def test_the_suspension_rule_is_armed_and_answers_once_the_token_is_correct(api):
    """With a fresh token the same call falls through to the 409, proving both.

    PRD 3.2: "The create also carries the `expected_property_version`
    concurrency token described in §2.7, and requires the property to be
    `ACTIVE` — a program cannot be opened against a `SUSPENDED` property, which
    is rejected with `ERR_PROPERTY_NOT_ACTIVE`." PRD 2.7: "If that value does
    not equal the property's current `version`, the create is rejected with
    `ERR_STALE_PROPERTY_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/stale_property_version_outranks_property_not_active_on_program_create
    """
    env = _stale_token_estate(api)
    suspended = env["suspended"]

    validate_error(
        api.create_fee_program(
            create_fee_program_payload(suspended["id"], env["live_version"]), REVENUE
        ),
        ApiErrorId.ERR_STALE_PROPERTY_VERSION,
        412,
    )
    validate_error(
        api.create_fee_program(
            create_fee_program_payload(suspended["id"], suspended["version"]), REVENUE
        ),
        ApiErrorId.ERR_PROPERTY_NOT_ACTIVE,
        409,
    )

    programs, _meta = validate_paginated(
        api.list_fee_programs(REVENUE, {"property_id": suspended["id"], "limit": 100})
    )
    assert programs == []
    assert read_property(suspended["id"])["version"] == 1


BAN_JURISDICTION = {"jurisdiction_overrides": {"mandatory_fee_ban": True}}
UNCOVERED_PROGRAM = {
    "taxability_spec": {"RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS)},
    "fee_payloads": [create_resort_fee_payload()],
    "inclusion_spec": {},
}
FREE_PROPERTY = {
    "name": "Desert Bloom Suites",
    "brand_code": "DBS",
    "base_room_rate_cents": 24900,
}


def _banned_and_free_programs(api):
    """Two uncovered UNDER_REVIEW programs, one under a ban and one not."""
    env = setup_program_under_review(**BAN_JURISDICTION, **UNCOVERED_PROGRAM)
    free_jurisdiction = add_second_jurisdiction(env, mandatory_fee_ban=False)
    create_taxability_rule(free_jurisdiction["id"], "RESORT", "TAXABLE", 1250)
    env["property_free"] = create_property(free_jurisdiction["id"], **FREE_PROPERTY)
    free_program = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                env["property_free"]["id"], env["property_free"]["version"]
            ),
            REVENUE,
        ),
        201,
    )
    add_fee(free_program["id"], create_resort_fee_payload())
    env["program_free"] = validate_success(
        api.submit_fee_program_for_review(free_program["id"], REVENUE)
    )
    return env


def test_the_jurisdictional_ban_answers_before_the_missing_inclusion(api):
    """Two 422s are violated at once and only the rank-19 identifier is returned.

    PRD 3.2: "if the property's jurisdiction has `mandatory_fee_ban` true and
    the program holds at least one `MANDATORY` fee, the attempt fails with
    `ERR_MANDATORY_FEE_BANNED_IN_JURISDICTION` (HTTP 422); every `MANDATORY` fee
    in the program must carry at least one inclusion whose
    `included_value_cents` is greater than 0, because a mandatory fee must buy
    the guest something, failing with `ERR_MANDATORY_FEE_WITHOUT_INCLUSION`."
    PRD 2.6 ranks the first at "19. Jurisdictional mandatory-fee ban" and the
    second at "22. Mandatory fee without a value-bearing inclusion".

    Design: Difficulty/priority_pair_validation_conflict/mandatory_fee_ban_outranks_missing_inclusion_on_publish
    """
    env = _banned_and_free_programs(api)
    banned = read_fee_program(env["program"]["id"])

    assert env["jurisdiction"]["mandatory_fee_ban"] is True
    assert banned["status"] == "UNDER_REVIEW"
    assert banned["mandatory_fee_count"] == 1
    assert float(banned["inclusion_coverage_ratio"]) == 0.0
    inclusions, _meta = validate_paginated(
        api.list_fee_inclusions(env["fees"]["RESORT"]["id"], REVENUE, {"limit": 100})
    )
    assert inclusions == []

    response = api.publish_fee_program(
        banned["id"], "Publishing a mandatory fee where mandatory fees are banned.",
        COMPLIANCE,
    )

    error = validate_error(
        response, ApiErrorId.ERR_MANDATORY_FEE_BANNED_IN_JURISDICTION, 422
    )
    assert error["error_id"] != ApiErrorId.ERR_MANDATORY_FEE_WITHOUT_INCLUSION

    assert read_fee_program(banned["id"])["status"] == "UNDER_REVIEW"
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 0


def test_the_missing_inclusion_rule_bites_where_no_ban_outranks_it(api):
    """The same uncovered program under a permissive county returns the rank-22 code.

    PRD 3.1: "When `mandatory_fee_ban` is true, no fee program carrying any fee
    classified `MANDATORY` may be published for a property in that jurisdiction
    at all; this flag is optional on input and defaults to false." PRD 3.2 pins
    the check the ban would otherwise mask:
    "every `MANDATORY` fee in the program must carry at least one inclusion
    whose `included_value_cents` is greater than 0 ... failing with
    `ERR_MANDATORY_FEE_WITHOUT_INCLUSION`."

    Design: Difficulty/priority_pair_validation_conflict/mandatory_fee_ban_outranks_missing_inclusion_on_publish
    """
    env = _banned_and_free_programs(api)
    free_program = env["program_free"]

    assert env["jurisdiction_2"]["mandatory_fee_ban"] is False
    assert free_program["status"] == "UNDER_REVIEW"
    assert free_program["mandatory_fee_count"] == 1

    validate_error(
        api.publish_fee_program(
            free_program["id"],
            "Publishing an uncovered mandatory fee in a county with no ban.",
            COMPLIANCE,
        ),
        ApiErrorId.ERR_MANDATORY_FEE_WITHOUT_INCLUSION,
        422,
    )

    assert read_fee_program(free_program["id"])["status"] == "UNDER_REVIEW"
    assert read_property(env["property_free"]["id"])["published_fee_program_count"] == 0
