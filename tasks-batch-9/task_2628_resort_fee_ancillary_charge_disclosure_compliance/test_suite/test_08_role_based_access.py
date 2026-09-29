"""Who may act: exclusive duties, shared duties, peer isolation and duty splits."""
from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    FOLIO_WIFI_AMOUNT_CENTS,
    FOLIO_WIFI_TAX_CENTS,
    FULL_INCLUSION_COVERAGE_RATIO,
    NON_EXISTENT_UUID,
    PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT,
    USER_COMPLIANCE_OFFICER,
    USER_COMPLIANCE_OFFICER_2,
    USER_GUEST_SERVICES_AGENT,
    USER_REVENUE_MANAGER,
    add_channel,
    add_complaint,
    assert_stamped_at_clock,
    create_booking_payload,
    create_fee_inclusion_payload,
    create_fee_program_payload,
    create_resort_fee_payload,
    create_revenue_impact_model_payload,
    make_channel_operator_headers,
    make_guest_headers,
    read_booking,
    read_clock,
    read_fee_program,
    read_profile,
    read_property,
    setup_configuration,
    setup_deployed_profile,
    setup_investigated_complaint,
    setup_program_under_review,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, AGENT, COMPLIANCE, COMPLIANCE_2, LIAISON, REVENUE

ATTESTATION = "Attesting the season's fee inventory."


def test_no_role_inherits_another_roles_exclusive_operation(api):
    """The platform's own admin is refused the attestation just as flatly as a guest.

    PRD 3.2: "Attestation is the compliance event, and it is reserved to a
    `ComplianceOfficer` alone." PRD 1.6: "If the role is recognised but is not
    among the roles authorised for the addressed endpoint in the §4 table, the
    rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD 3.2 on the untouched
    rollups: "All four rollup fields start at their defaults: `fee_count` 0,
    `mandatory_fee_count` 0, `total_mandatory_fee_cents_per_night` 0 and
    `inclusion_coverage_ratio` 0.0000."

    Design: Corner/rbac/exclusive_operations_are_forbidden_to_every_other_role
    """
    env = setup_program_under_review()
    program_id = env["program"]["id"]
    assert env["program"]["authored_by_user_id"] == USER_REVENUE_MANAGER

    # The author's own role is refused at rank 3, before duty separation at 9.
    author = api.publish_fee_program(program_id, ATTESTATION, REVENUE)
    error = validate_error(author, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES

    for outsider in (
        ADMIN,
        LIAISON,
        AGENT,
        make_channel_operator_headers(env["channel"]["id"]),
        make_guest_headers(NON_EXISTENT_UUID),
    ):
        validate_error(
            api.publish_fee_program(program_id, ATTESTATION, outsider),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )

    unattested = read_fee_program(program_id)
    assert unattested["status"] == "UNDER_REVIEW"
    assert unattested["published_at"] is None
    assert unattested["attested_by_user_id"] is None
    assert unattested["total_mandatory_fee_cents_per_night"] == 0
    assert float(unattested["inclusion_coverage_ratio"]) == 0.0

    published = validate_success(
        api.publish_fee_program(program_id, ATTESTATION, COMPLIANCE)
    )
    assert published["status"] == "PUBLISHED"
    assert published["attested_by_user_id"] == USER_COMPLIANCE_OFFICER
    assert published["attestation_note"] == ATTESTATION
    assert published["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT
    )
    assert float(published["inclusion_coverage_ratio"]) == FULL_INCLUSION_COVERAGE_RATIO

    # Every other exclusive duty refuses its neighbours the same way, and the
    # role gate answers before the addressed identifier is ever resolved.
    validate_error(
        api.set_clock("2026-08-02T00:00:00Z", COMPLIANCE),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.audit_profile(NON_EXISTENT_UUID, REVENUE),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.check_in_booking(NON_EXISTENT_UUID, COMPLIANCE),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.grant_opt_out_request(
            NON_EXISTENT_UUID, make_channel_operator_headers(env["channel"]["id"])
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.draft_inquiry_response(NON_EXISTENT_UUID, "A response.", COMPLIANCE),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    # The operator's liaison answers a docket but never grants it for the regulator.
    validate_error(
        api.accept_inquiry(NON_EXISTENT_UUID, LIAISON),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    assert_stamped_at_clock(read_clock(), CLOCK_START, "current_utc")


SUCCESSOR_WINDOW = {
    "version_label": "FY27-Q1",
    "effective_from": "2026-12-01T00:00:00Z",
    "effective_to": "2027-03-01T00:00:00Z",
}
VOLATILE_FEE_FIELDS = {"id", "created_at", "updated_at", "fee_program_id"}


def test_a_shared_operation_records_the_same_row_whichever_role_calls_it(api):
    """The fee inventory records no actor, so authorship cannot move with the caller.

    PRD 1.5: "A `RevenueManager` authors fee programs, adds fees and inclusion
    analysis to them, submits them for review ... A `ComplianceOfficer` is the
    attesting authority ... and it is also permitted to author programs and add
    fees — which is precisely what makes the segregation-of-duties check on
    publication reachable." PRD 3.2: "Its `authored_by_user_id` is stamped from
    the acting `X-User-ID` and is the anchor for the segregation-of-duties check
    that fires later at attestation".

    Design: Corner/rbac/shared_operations_accept_either_declared_role_identically
    """
    env = setup_configuration()
    property_id = env["property"]["id"]
    authored = validate_success(
        api.create_fee_program(
            create_fee_program_payload(property_id, env["property"]["version"]), REVENUE
        ),
        201,
    )
    assert authored["authored_by_user_id"] == USER_REVENUE_MANAGER

    officer_fee = validate_success(
        api.create_fee(authored["id"], create_resort_fee_payload(), COMPLIANCE_2), 201
    )
    assert officer_fee["code"] == "RESORT"
    assert officer_fee["classification"] == "MANDATORY"
    assert officer_fee["basis"] == "PERCENT_OF_ROOM"
    assert officer_fee["percent_bps"] == 750
    assert officer_fee["amount_cents"] is None
    assert officer_fee["avoidable"] is False
    # A fee carries no actor field at all, so nothing records who added it.
    assert [key for key in officer_fee if key.endswith("_by_user_id")] == []

    carrying = read_fee_program(authored["id"])
    assert carrying["fee_count"] == 1
    assert carrying["mandatory_fee_count"] == 1
    assert carrying["total_mandatory_fee_cents_per_night"] == 0
    assert float(carrying["inclusion_coverage_ratio"]) == 0.0
    # Authorship stays with the manager who opened the program.
    assert carrying["authored_by_user_id"] == USER_REVENUE_MANAGER
    assert carrying["status"] == "DRAFT"

    # The same create issued by the other permitted role yields the same row.
    twin_program = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                property_id,
                read_property(property_id)["version"],
                **SUCCESSOR_WINDOW,
            ),
            COMPLIANCE,
        ),
        201,
    )
    manager_fee = validate_success(
        api.create_fee(twin_program["id"], create_resort_fee_payload(), REVENUE), 201
    )
    assert {
        key: value
        for key, value in manager_fee.items()
        if key not in VOLATILE_FEE_FIELDS
    } == {
        key: value
        for key, value in officer_fee.items()
        if key not in VOLATILE_FEE_FIELDS
    }
    assert twin_program["authored_by_user_id"] == USER_COMPLIANCE_OFFICER

    # Every remaining configuration step is shared with the same two roles.
    validate_success(
        api.create_fee_inclusion(
            officer_fee["id"], create_fee_inclusion_payload(), COMPLIANCE_2
        ),
        201,
    )
    reviewed = validate_success(
        api.submit_fee_program_for_review(authored["id"], COMPLIANCE_2)
    )
    assert reviewed["status"] == "UNDER_REVIEW"

    # Declaring taxability is likewise shared, and records no author either.
    by_admin = validate_success(
        api.create_taxability_rule(
            {
                "jurisdiction_id": env["jurisdiction"]["id"],
                "fee_code": "PARKING",
                "taxability": "TAXABLE",
            },
            ADMIN,
        ),
        201,
    )
    by_officer = validate_success(
        api.create_taxability_rule(
            {
                "jurisdiction_id": env["jurisdiction"]["id"],
                "fee_code": "SPA_ACCESS",
                "taxability": "EXEMPT",
            },
            COMPLIANCE,
        ),
        201,
    )
    assert set(by_admin) == set(by_officer)
    assert [key for key in by_officer if key.endswith("_by_user_id")] == []

    # The shared list is exactly two roles wide.
    validate_error(
        api.create_fee(twin_program["id"], create_resort_fee_payload(code="POOL"), AGENT),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    _rows, meta = validate_paginated(
        api.list_fees(REVENUE, {"fee_program_id": twin_program["id"], "limit": 100})
    )
    assert meta["total_count"] == 1


CAPABLE_GDS = {
    "name": "WorldGDS Terminal",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}


def test_one_channel_may_not_quote_a_stay_on_another_channels_path(api):
    """Isolation follows the addressed path, not the channel named in the body.

    PRD 1.7: "When `X-User-Role` is `ChannelOperator`, `X-User-ID` is the `id` of
    the acting `Channel`; ownership checks on any resource that references a
    `Channel` compare the resource's `channel_id` field to `X-User-ID`." PRD 3.4:
    "The payload names the `property_id` booked, the `channel_id` the quote was
    shown on, and the `channel_disclosure_profile_id` of the booking path that
    produced the first quote; the `channel_id` supplied must be the profile's
    own channel, and a mismatch is a malformed quote request rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/rbac/peer_channel_operators_cannot_touch_each_others_resources
    """
    env = setup_deployed_profile()
    property_id = env["property"]["id"]
    selling_channel = env["channel"]["id"]
    path_id = env["profile"]["id"]
    rival = add_channel(env, "gds_channel", **CAPABLE_GDS)
    rival_operator = make_channel_operator_headers(rival["id"])
    selling_operator = make_channel_operator_headers(selling_channel)

    validate_error(
        api.create_booking(
            create_booking_payload(property_id, selling_channel, path_id),
            rival_operator,
        ),
        ApiErrorId.ERR_CHANNEL_OWNERSHIP_REQUIRED,
        403,
    )
    # Naming its own channel clears the ownership rank — the booking's own
    # `channel_id` now equals `X-User-ID` — so the shape rank answers instead:
    # "the `channel_id` supplied must be the profile's own channel, and a
    # mismatch is a malformed quote request rejected with `ERR_INVALID_REQUEST`".
    validate_error(
        api.create_booking(
            create_booking_payload(property_id, rival["id"], path_id), rival_operator
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        422,
    )
    _rows, meta = validate_paginated(api.list_bookings(REVENUE, {"limit": 100}))
    assert meta["total_count"] == 0

    quoted = validate_success(
        api.create_booking(
            create_booking_payload(property_id, selling_channel, path_id),
            selling_operator,
        ),
        201,
    )
    assert quoted["channel_id"] == selling_channel
    assert quoted["channel_disclosure_profile_id"] == path_id

    # Guest is absent from the path endpoint's role list, so rank 3 answers.
    guest = make_guest_headers(quoted["id"])
    validate_error(
        api.get_channel_disclosure_profile(path_id, guest),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    # The same guest may read the fee inventory that priced its own stay.
    priced_fee = env["fees"]["RESORT"]["id"]
    assert validate_success(api.get_fee(priced_fee, guest))["id"] == priced_fee
    inclusions, _inclusion_meta = validate_paginated(
        api.list_fee_inclusions(priced_fee, guest, {"limit": 100})
    )
    assert len(inclusions) == 1

    # Roll-in modelling belongs to neither entity-backed identity.
    for outsider in (guest, rival_operator):
        validate_error(
            api.create_revenue_impact_model(
                create_revenue_impact_model_payload(property_id, env["program"]["id"]),
                outsider,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )


def test_the_officer_who_opened_an_investigation_may_not_adjudicate_it(api):
    """One duty split spanning two role lists, keyed on the recorded identity.

    PRD 3.7: "Both branches leave `UNDER_INVESTIGATION`, both are
    `ComplianceOfficer` actions, both require the adjudicating identity to differ
    from `investigated_by_user_id` on pain of `ERR_SEGREGATION_OF_DUTIES`, and
    both set `adjudicated_by_user_id`." PRD 3.7 on the variant: "Under
    `FULL_FEE_REFUND`, selected when `complaint_reason` is `NOT_DISCLOSED`,
    `TOTAL_NOT_SHOWN` or `MANDATORY_NOT_AVOIDABLE` ... `refund_entitlement_cents`
    is the line's `amount_cents` plus the line's `tax_cents`".

    Design: Corner/rbac/substantiating_a_complaint_you_investigated_yourself_is_rejected
    """
    env = setup_investigated_complaint()
    complaint_id = env["complaint"]["id"]
    assert env["complaint"]["status"] == "UNDER_INVESTIGATION"
    assert env["complaint"]["investigated_by_user_id"] == USER_COMPLIANCE_OFFICER

    validate_error(
        api.substantiate_complaint(complaint_id, COMPLIANCE),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    # Both adjudication verbs are covered by the one rule.
    validate_error(
        api.dismiss_complaint(complaint_id, "DISCLOSURE_EVIDENCED", COMPLIANCE),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    held = validate_success(api.get_guest_complaint(complaint_id, COMPLIANCE))
    assert held["status"] == "UNDER_INVESTIGATION"
    assert held["investigated_by_user_id"] == USER_COMPLIANCE_OFFICER
    assert held["adjudicated_by_user_id"] is None
    assert held["refund_variant"] is None
    assert held["refund_entitlement_cents"] == 0
    # None of the four cascade levels fired.
    assert read_booking(env["booking"]["id"])["disclosure_status"] == "PENDING_AUDIT"
    unrescored = read_profile(env["profile"]["id"])
    assert unrescored["confirmed_undisclosed_count"] == 0
    assert unrescored["disclosure_score"] == 100

    upheld = validate_success(api.substantiate_complaint(complaint_id, COMPLIANCE_2))
    assert upheld["status"] == "SUBSTANTIATED"
    assert upheld["adjudicated_by_user_id"] == USER_COMPLIANCE_OFFICER_2
    assert upheld["refund_variant"] == "FULL_FEE_REFUND"
    assert upheld["disputed_amount_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert upheld["refund_entitlement_cents"] == (
        FOLIO_WIFI_AMOUNT_CENTS + FOLIO_WIFI_TAX_CENTS
    )
    assert read_booking(env["booking"]["id"])["disclosure_status"] == (
        "UNDISCLOSED_CONFIRMED"
    )
    rescored = read_profile(env["profile"]["id"])
    assert rescored["confirmed_undisclosed_count"] == 1
    assert rescored["disclosure_score"] == 95
    assert rescored["status"] == "DEPLOYED"

    # The rule reads the recorded identity, never the investigator's role: with
    # the front desk investigating, the first officer may adjudicate after all.
    front_desk_case = add_complaint(env, fee_code="RESORT")
    validate_success(api.investigate_complaint(front_desk_case["id"], AGENT))
    adjudicated = validate_success(
        api.dismiss_complaint(front_desk_case["id"], "DISCLOSURE_EVIDENCED", COMPLIANCE)
    )
    assert adjudicated["status"] == "UNSUBSTANTIATED"
    assert adjudicated["adjudicated_by_user_id"] == USER_COMPLIANCE_OFFICER
    assert adjudicated["investigated_by_user_id"] == USER_GUEST_SERVICES_AGENT
