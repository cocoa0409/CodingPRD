"""What the API says when the caller names something, or someone, it may not."""
from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    NON_EXISTENT_UUID,
    USER_COMPLIANCE_OFFICER,
    USER_REGULATORY_LIAISON,
    USER_REGULATORY_LIAISON_2,
    add_booking,
    add_channel,
    assert_stamped_at_clock,
    create_fee_inclusion_payload,
    create_fee_program_payload,
    create_jurisdiction_payload,
    create_profile_payload,
    create_property_payload,
    create_resort_fee_payload,
    make_channel_operator_headers,
    make_guest_headers,
    read_profile,
    read_property,
    setup_configuration,
    setup_confirmed_booking,
    setup_deployed_profile,
    setup_drafted_inquiry,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, AGENT, COMPLIANCE, LIAISON, LIAISON_2, REVENUE

MALFORMED_FEE = dict(create_resort_fee_payload(), classification="COMPULSORY")


def test_a_missing_path_identifier_is_named_by_the_entity_it_addressed(api):
    """Fourteen tables, fourteen codes, one status, and no generic not-found.

    PRD 2.6: "Identifiers embedded in a URL are resolved strictly left to right,
    and the leftmost missing segment determines the response. Adding a fee under
    a fee-program identifier that does not exist returns
    `ERR_FEE_PROGRAM_NOT_FOUND` (HTTP 404) and the request body is never
    inspected at all. The full set of not-found codes is
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_TAXABILITY_RULE_NOT_FOUND`,
    `ERR_PROPERTY_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`,
    `ERR_FEE_PROGRAM_NOT_FOUND`, `ERR_FEE_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BOOKING_NOT_FOUND`, `ERR_FOLIO_NOT_FOUND`, `ERR_FOLIO_LINE_NOT_FOUND`,
    `ERR_OPT_OUT_REQUEST_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_INQUIRY_NOT_FOUND` and `ERR_REVENUE_MODEL_NOT_FOUND`, each at HTTP 404."

    Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found
    """
    response = api.get_jurisdiction(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(response, ApiErrorId.ERR_JURISDICTION_NOT_FOUND, 404)
    assert error["message"]
    assert response.json()["meta"]["api_request_id"].startswith("req_")

    probes = [
        (api.get_taxability_rule(NON_EXISTENT_UUID, ADMIN),
         ApiErrorId.ERR_TAXABILITY_RULE_NOT_FOUND),
        (api.get_property(NON_EXISTENT_UUID, ADMIN),
         ApiErrorId.ERR_PROPERTY_NOT_FOUND),
        (api.get_channel(NON_EXISTENT_UUID, ADMIN),
         ApiErrorId.ERR_CHANNEL_NOT_FOUND),
        (api.get_fee_program(NON_EXISTENT_UUID, REVENUE),
         ApiErrorId.ERR_FEE_PROGRAM_NOT_FOUND),
        (api.get_fee(NON_EXISTENT_UUID, REVENUE), ApiErrorId.ERR_FEE_NOT_FOUND),
        (api.get_channel_disclosure_profile(NON_EXISTENT_UUID, REVENUE),
         ApiErrorId.ERR_PROFILE_NOT_FOUND),
        (api.get_booking(NON_EXISTENT_UUID, AGENT),
         ApiErrorId.ERR_BOOKING_NOT_FOUND),
        (api.get_folio(NON_EXISTENT_UUID, AGENT), ApiErrorId.ERR_FOLIO_NOT_FOUND),
        (api.get_folio_line(NON_EXISTENT_UUID, AGENT),
         ApiErrorId.ERR_FOLIO_LINE_NOT_FOUND),
        (api.get_opt_out_request(NON_EXISTENT_UUID, AGENT),
         ApiErrorId.ERR_OPT_OUT_REQUEST_NOT_FOUND),
        (api.get_guest_complaint(NON_EXISTENT_UUID, AGENT),
         ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        (api.get_regulator_inquiry(NON_EXISTENT_UUID, LIAISON),
         ApiErrorId.ERR_INQUIRY_NOT_FOUND),
        (api.get_revenue_impact_model(NON_EXISTENT_UUID, REVENUE),
         ApiErrorId.ERR_REVENUE_MODEL_NOT_FOUND),
    ]
    seen = {ApiErrorId.ERR_JURISDICTION_NOT_FOUND}
    for probed, expected in probes:
        validate_error(probed, expected, 404)
        seen.add(expected)
    assert len(seen) == 14

    # The path is resolved before the body is parsed, so rank 6 beats rank 7.
    validate_error(
        api.create_fee(NON_EXISTENT_UUID, MALFORMED_FEE, REVENUE),
        ApiErrorId.ERR_FEE_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_fee_inclusion(
            NON_EXISTENT_UUID,
            create_fee_inclusion_payload(service_code="POOL_ACCESS"),
            REVENUE,
        ),
        ApiErrorId.ERR_FEE_NOT_FOUND,
        404,
    )
    # A nested collection under a missing parent is a 404, not an empty page.
    validate_error(
        api.list_fee_inclusions(NON_EXISTENT_UUID, REVENUE),
        ApiErrorId.ERR_FEE_NOT_FOUND,
        404,
    )

    _rows, meta = validate_paginated(api.list_jurisdictions(ADMIN))
    assert meta["total_count"] == 0


def test_an_unknown_body_reference_is_a_not_found_before_any_other_reason(api):
    """The 404 answers where a stale token or an ownership rule looks likelier.

    PRD 2.6: "8. Existence of every identifier supplied in the request body —
    `jurisdiction_id`, `property_id`, `channel_id`, `fee_program_id`,
    `supersedes_program_id`, `channel_disclosure_profile_id`, `fee_id` and
    `folio_line_id` — checked in the order the endpoint declares its input
    fields, again yielding the matching not-found code. This rank guards the
    creation of taxability rules, properties, fee programs, disclosure profiles,
    bookings, opt-out requests, guest complaints, regulator inquiries and revenue
    impact models."

    Design: Corner/errors/unknown_body_references_return_not_found_before_state_checks
    """
    env = setup_configuration(taxability_spec={})
    live_version = read_property(env["property"]["id"])["version"]

    response = api.create_fee_program(
        create_fee_program_payload(NON_EXISTENT_UUID, live_version), REVENUE
    )
    error = validate_error(response, ApiErrorId.ERR_PROPERTY_NOT_FOUND, 404)
    # No token can match a row that does not exist, yet rank 8 still answers.
    assert error["error_id"] != ApiErrorId.ERR_STALE_PROPERTY_VERSION
    # A well-formed uuid that resolves to nothing is not a shape violation.
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST

    validate_error(
        api.create_taxability_rule(
            {
                "jurisdiction_id": NON_EXISTENT_UUID,
                "fee_code": "RESORT",
                "taxability": "TAXABLE",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_JURISDICTION_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_property(create_property_payload(NON_EXISTENT_UUID), ADMIN),
        ApiErrorId.ERR_JURISDICTION_NOT_FOUND,
        404,
    )

    channel = env["channel"]
    operator = make_channel_operator_headers(channel["id"])
    validate_error(
        api.create_channel_disclosure_profile(
            create_profile_payload(
                env["property"]["id"], channel["id"], NON_EXISTENT_UUID, 1
            ),
            operator,
        ),
        ApiErrorId.ERR_FEE_PROGRAM_NOT_FOUND,
        404,
    )
    # With the channel_id itself unknown, ownership at rank 4 answers first.
    validate_error(
        api.create_channel_disclosure_profile(
            create_profile_payload(
                env["property"]["id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID, 1
            ),
            operator,
        ),
        ApiErrorId.ERR_CHANNEL_OWNERSHIP_REQUIRED,
        403,
    )

    _rows, meta = validate_paginated(api.list_fee_programs(REVENUE))
    assert meta["total_count"] == 0
    _rules, rule_meta = validate_paginated(api.list_taxability_rules(ADMIN))
    assert rule_meta["total_count"] == 0
    _props, property_meta = validate_paginated(api.list_properties(ADMIN))
    assert property_meta["total_count"] == 1
    assert read_property(env["property"]["id"])["version"] == live_version


NO_HEADERS = {}
ROLE_ONLY = {"X-User-Role": "PlatformAdmin"}
ID_ONLY = {"X-User-ID": "u-admin-1"}
EMPTY_ID = {"X-User-Role": "PlatformAdmin", "X-User-ID": ""}
UNKNOWN_ROLE = {"X-User-Role": "Concierge", "X-User-ID": "u-concierge-1"}


def test_both_identity_headers_are_required_before_anything_else_is_looked_at(api):
    """401 even for an id that does not exist, and the clock read alone is exempt.

    PRD 1.6: "Every request other than the logical-clock read carries two headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the
    role that principal is acting in. If either header is absent or empty, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If `X-User-Role`
    carries a string that is not one of the seven role names defined below, the
    rejection is `ERR_UNKNOWN_ROLE` (HTTP 401) ... The single exception to all
    three rules is the logical-clock read (`GET /_clock`), which is deliberately
    unauthenticated so that a test harness can establish the current instant
    before assuming any identity."

    Design: Corner/errors/requests_missing_the_auth_headers_are_unauthenticated
    """
    env = setup_configuration(taxability_spec={})
    known_property = env["property"]["id"]

    for headers in (NO_HEADERS, ROLE_ONLY, ID_ONLY, EMPTY_ID):
        validate_error(
            api.get_property(known_property, headers),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
    # A recognised shape with an unrecognised role is the sibling 401.
    validate_error(
        api.get_property(known_property, UNKNOWN_ROLE),
        ApiErrorId.ERR_UNKNOWN_ROLE,
        401,
    )

    # Rank 1 answers before the path is resolved at rank 6.
    validate_error(
        api.get_property(NON_EXISTENT_UUID, NO_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.get_jurisdiction(NON_EXISTENT_UUID, UNKNOWN_ROLE),
        ApiErrorId.ERR_UNKNOWN_ROLE,
        401,
    )

    # An unauthenticated write is refused before it can persist anything.
    validate_error(
        api.create_jurisdiction(
            create_jurisdiction_payload(code="US-CA-SANDIEGO", name="San Diego County"),
            NO_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    _rows, meta = validate_paginated(api.list_jurisdictions(ADMIN))
    assert meta["total_count"] == 1

    clock = validate_success(api.get_clock())
    assert_stamped_at_clock(clock["current_utc"], CLOCK_START, "current_utc")


CAPABLE_GDS = {
    "name": "WorldGDS Terminal",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}


def test_a_channel_may_not_touch_the_booking_path_of_another_channel(api):
    """Ownership answers ahead of the state rule, and role ahead of ownership.

    PRD 1.7: "a `ChannelOperator` whose `X-User-ID` is not an existing `Channel`
    identifier, or which addresses a disclosure profile or booking whose
    `channel_id` differs from `X-User-ID`, is rejected with
    `ERR_CHANNEL_OWNERSHIP_REQUIRED` (HTTP 403). That check guards exactly six
    operations: creating a channel disclosure profile, deploying one,
    remediating one, creating a booking, reading a single disclosure profile,
    and reading a single booking."

    Design: Corner/errors/a_channel_operator_reaching_into_another_channel_is_forbidden
    """
    env = setup_deployed_profile()
    profile_id = env["profile"]["id"]
    owner = make_channel_operator_headers(env["channel"]["id"])
    intruder = make_channel_operator_headers(
        add_channel(env, "gds_channel", **CAPABLE_GDS)["id"]
    )
    stranger = make_channel_operator_headers(NON_EXISTENT_UUID)

    response = api.deploy_profile(profile_id, intruder)
    error = validate_error(response, ApiErrorId.ERR_CHANNEL_OWNERSHIP_REQUIRED, 403)
    # The path is already DEPLOYED, yet rank 4 answers before rank 12.
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE

    # The rule covers the single read as well as the write.
    validate_error(
        api.get_channel_disclosure_profile(profile_id, intruder),
        ApiErrorId.ERR_CHANNEL_OWNERSHIP_REQUIRED,
        403,
    )
    validate_error(
        api.get_channel_disclosure_profile(profile_id, stranger),
        ApiErrorId.ERR_CHANNEL_OWNERSHIP_REQUIRED,
        403,
    )
    mine = validate_success(api.get_channel_disclosure_profile(profile_id, owner))
    assert mine["id"] == profile_id
    assert mine["status"] == "DEPLOYED"

    # Role authorisation at rank 3 is a separate gate that fires even earlier.
    validate_error(
        api.deploy_profile(profile_id, AGENT), ApiErrorId.ERR_FORBIDDEN_ROLE, 403
    )
    validate_error(
        api.audit_profile(profile_id, owner), ApiErrorId.ERR_FORBIDDEN_ROLE, 403
    )

    after = read_profile(profile_id)
    assert after["status"] == "DEPLOYED"
    assert after["version"] == env["profile"]["version"]


def test_a_guest_authenticates_as_a_booking_and_may_read_only_that_one(api):
    """The neighbour's reservation is closed to them, and so is its opt-out route.

    PRD 1.7: "A `Guest` whose `X-User-ID` is not an existing `Booking`
    identifier, or which addresses a booking, folio, folio line, opt-out request
    or complaint that does not resolve to that same booking, is rejected with
    `ERR_BOOKING_OWNERSHIP_REQUIRED` (HTTP 403). That check guards exactly nine
    operations: reading a single booking, listing the folios of a booking,
    reading a single folio, reading a single folio line, listing folio lines,
    creating an opt-out request under a booking, creating a guest complaint under
    a booking, reading a single opt-out request, and reading a single complaint."

    Design: Corner/errors/a_guest_reading_another_guests_booking_is_forbidden
    """
    env = setup_confirmed_booking()
    mine = env["booking"]["id"]
    neighbour = add_booking(env)["id"]
    validate_success(api.confirm_booking(neighbour, AGENT))
    avoidable_fee = env["fees"]["DESTINATION"]["id"]

    validate_error(
        api.get_booking(mine, make_guest_headers(neighbour)),
        ApiErrorId.ERR_BOOKING_OWNERSHIP_REQUIRED,
        403,
    )
    # Only which booking authenticated differs between these two reads.
    read_back = validate_success(api.get_booking(mine, make_guest_headers(mine)))
    assert read_back["id"] == mine

    # Rank 5 outranks every opt-out eligibility rule from rank 24 downwards.
    denied = api.create_opt_out_request(
        mine, avoidable_fee, make_guest_headers(neighbour)
    )
    error = validate_error(denied, ApiErrorId.ERR_BOOKING_OWNERSHIP_REQUIRED, 403)
    assert error["error_id"] != ApiErrorId.ERR_FEE_NOT_ON_BOOKING_PROGRAM
    assert error["error_id"] != ApiErrorId.ERR_FEE_NOT_AVOIDABLE

    validate_error(
        api.list_booking_folios(mine, make_guest_headers(neighbour)),
        ApiErrorId.ERR_BOOKING_OWNERSHIP_REQUIRED,
        403,
    )
    # An identity that names no booking at all fails the same way.
    validate_error(
        api.get_booking(mine, make_guest_headers(NON_EXISTENT_UUID)),
        ApiErrorId.ERR_BOOKING_OWNERSHIP_REQUIRED,
        403,
    )

    # The channel that sold the stay is a separate, independent ownership gate.
    as_channel = validate_success(
        api.get_booking(mine, make_channel_operator_headers(env["channel"]["id"]))
    )
    assert as_channel["id"] == mine

    _rows, meta = validate_paginated(
        api.list_opt_out_requests(AGENT, {"booking_id": mine, "limit": 100})
    )
    assert meta["total_count"] == 0


SUCCESSOR_WINDOW = {
    "version_label": "FY27-Q1",
    "effective_from": "2026-12-01T00:00:00Z",
    "effective_to": "2027-03-01T00:00:00Z",
}


def test_the_hand_that_drafted_a_response_may_not_be_the_hand_that_submits_it(api):
    """The role is identical on both calls; only the acting identity decides.

    PRD 3.8: "It requires the submitting identity to differ from
    `drafted_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`, and it requires
    the logical clock still to be at or before `response_due_at`, on pain of
    `ERR_RESPONSE_WINDOW_EXPIRED`. It records `submitted_by_user_id`, recomputes
    `exposure_cents` and increments the docket's `version`." PRD 1.7: "Those four
    operations — publish, substantiate, dismiss, submit-response — are the
    complete set guarded by this rule."

    Design: Corner/errors/submitting_a_response_you_drafted_yourself_is_rejected
    """
    env = setup_drafted_inquiry()
    docket = env["inquiry"]
    assert docket["status"] == "RESPONSE_DRAFTED"
    assert docket["drafted_by_user_id"] == USER_REGULATORY_LIAISON
    before = read_property(env["property"]["id"])
    assert before["open_disclosure_obligation_count"] == 1

    response = api.submit_inquiry_response(docket["id"], LIAISON)
    error = validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    # The role is the endpoint's only role and the deadline is months away.
    assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE
    assert error["error_id"] != ApiErrorId.ERR_RESPONSE_WINDOW_EXPIRED

    still_drafted = validate_success(api.get_regulator_inquiry(docket["id"], LIAISON))
    assert still_drafted["status"] == "RESPONSE_DRAFTED"
    assert still_drafted["drafted_by_user_id"] == USER_REGULATORY_LIAISON
    assert still_drafted["submitted_by_user_id"] is None
    assert still_drafted["version"] == docket["version"]

    submitted = validate_success(api.submit_inquiry_response(docket["id"], LIAISON_2))
    assert submitted["status"] == "RESPONSE_SUBMITTED"
    assert submitted["submitted_by_user_id"] == USER_REGULATORY_LIAISON_2
    assert submitted["drafted_by_user_id"] == USER_REGULATORY_LIAISON

    # The sibling clause on attestation is keyed the same way, and outranks state.
    self_authored = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                env["property"]["id"],
                read_property(env["property"]["id"])["version"],
                **SUCCESSOR_WINDOW,
            ),
            COMPLIANCE,
        ),
        201,
    )
    assert self_authored["authored_by_user_id"] == USER_COMPLIANCE_OFFICER
    assert self_authored["status"] == "DRAFT"
    attested = api.publish_fee_program(
        self_authored["id"], "Attesting a program I wrote myself.", COMPLIANCE
    )
    attempt = validate_error(attested, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    assert attempt["error_id"] != ApiErrorId.ERR_INVALID_STATE

    after = read_property(env["property"]["id"])
    assert after["open_disclosure_obligation_count"] == 1
    assert after["published_fee_program_count"] == 1
