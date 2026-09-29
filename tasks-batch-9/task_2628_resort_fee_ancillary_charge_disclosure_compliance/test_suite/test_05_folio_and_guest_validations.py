"""Rules guarding who may book, who may opt out, who may complain, and when."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_INCLUSIONS,
    CANONICAL_TAXABILITY,
    CLOCK_START,
    DESTINATION_OPT_OUT_WINDOW_HOURS,
    FOLIO_DESTINATION_AMOUNT_CENTS,
    FOLIO_DESTINATION_TAX_CENTS,
    FOLIO_RESORT_AMOUNT_CENTS,
    FOLIO_ROOM_AMOUNT_CENTS,
    FOLIO_ROOM_TAX_CENTS,
    FOLIO_TOTAL_CENTS,
    OCCUPANCY_TAX_RATE_BPS,
    PUBLISHED_DESTINATION_PER_NIGHT_CENTS,
    PUBLISHED_RESORT_PER_NIGHT_CENTS,
    QUOTED_TOTAL_CENTS,
    add_booking,
    add_channel,
    add_draft_profile,
    add_fee,
    add_inquiry,
    add_opt_out_request,
    advance_to_posted_folio,
    assert_stamped_at_clock,
    create_booking_payload,
    create_destination_fee_payload,
    create_fee_program_payload,
    create_guest_complaint_payload,
    create_regulator_inquiry_payload,
    create_remediation_payload,
    create_resort_fee_payload,
    create_wifi_fee_payload,
    deploy_profile,
    find_line_by_sequence,
    make_guest_headers,
    move_clock_to,
    read_booking,
    read_fee_program,
    read_folio,
    read_folio_lines,
    read_profile,
    read_property,
    remediate_profile,
    setup_checked_out_booking,
    setup_configuration,
    setup_confirmed_booking,
    setup_draft_profile,
    setup_granted_opt_out,
    setup_in_house_booking,
    setup_itemized_folio,
    setup_posted_folio,
    setup_received_inquiry,
    setup_requested_opt_out,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AGENT, COMPLIANCE, LIAISON, LIAISON_2, REVENUE

UNDER_FLOOR_PROFILE = {
    "first_quote_shows_total": True,
    "itemized_at_first_quote": False,
    "disclosure_placement": "CHECKOUT",
}
CAPABLE_GDS = {
    "name": "WorldGDS Terminal",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}
CREDITED_FOLIO_TOTAL_CENTS = 148372
NOTICE_HOURS_AT_CLOCK_START = 960
WINDOW_OPEN_INSTANT = "2026-09-08T00:00:00Z"
WINDOW_CLOSED_INSTANT = "2026-09-08T00:59:59Z"
WINDOW_CLOSED_LATER_INSTANT = "2026-09-08T01:00:00Z"
SPA_FEE = {
    "code": "SPA_ACCESS",
    "label": "Spa Day Pass",
    "classification": "OPTIONAL",
    "basis": "PER_STAY",
    "amount_cents": 5000,
    "avoidable": True,
    "opt_out_window_hours": 24,
    "disclosure_text": "An optional spa day pass may be added to this stay.",
}
SUCCESSOR_WINDOW = {
    "version_label": "FY27-Q1",
    "effective_from": "2026-12-01T00:00:00Z",
    "effective_to": "2027-03-01T00:00:00Z",
}
FOREIGN_SPA_FEE = {
    "code": "SPA_ACCESS",
    "label": "Spa Day Pass",
    "classification": "MANDATORY",
    "basis": "PER_STAY",
    "amount_cents": 5000,
    "disclosure_text": "A mandatory spa access fee applies under the new inventory.",
}
RESPONSE_DUE_AT = "2026-10-01T00:00:00Z"
ONE_SECOND_PAST_DUE = "2026-10-01T00:00:01Z"
ZERO_PRICED_PARKING_FEE = {
    "code": "PARKING",
    "label": "Self-Parking",
    "classification": "MANDATORY",
    "basis": "PER_NIGHT",
    "amount_cents": 0,
    "avoidable": True,
    "opt_out_window_hours": DESTINATION_OPT_OUT_WINDOW_HOURS,
    "disclosure_text": "Self-parking is included at no charge for this stay.",
}
PARKING_INCLUSION = {
    "service_code": "PARKING_PASS",
    "service_label": "Self-parking pass",
    "retail_value_cents": 800,
    "units": 1,
}
# Room 119600 plus a 2243-per-night resort fee, a 1495-per-night destination fee
# and a parking fee that expands to nothing at all.
PARKING_QUOTED_FEE_CENTS = 14952
PARKING_QUOTED_TOTAL_CENTS = 152555
PARKING_FOLIO_CHARGES_CENTS = 134550
PARKING_FOLIO_TAX_TOTAL_CENTS = 18002
PARKING_FOLIO_TOTAL_CENTS = 152552


def test_a_credit_cannot_land_on_a_folio_that_has_not_yet_posted(api):
    """The fee line the credit wants is present; the folio's own status refuses it.

    PRD 3.6: "Granting is a `GuestServicesAgent` action from `REQUESTED` to
    `GRANTED`. The folio must be in `POSTED` or `ADJUSTED` so that the reversal
    has something to reverse — an `OPEN`, `ITEMIZED` or `CLOSED` folio cannot
    absorb a compensating line and the attempt is rejected with
    `ERR_FOLIO_NOT_ADJUSTABLE` (HTTP 409) — and the folio must carry a
    `MANDATORY_FEE` line for the request's `fee_id` with no un-rebilled credit
    already standing against it, the absence being rejected with
    `ERR_FEE_LINE_NOT_ON_FOLIO` (HTTP 422)."

    Design: Corner/validations/opt_out_grant_against_an_itemized_folio_is_rejected
    """
    env = setup_requested_opt_out()
    setup_in_house_booking(env=env)
    setup_itemized_folio(env=env)

    lines = read_folio_lines(env["folio"]["id"])
    billed = find_line_by_sequence(lines, 3)
    assert billed["line_type"] == "MANDATORY_FEE"
    assert billed["fee_id"] == env["fees"]["DESTINATION"]["id"]
    assert billed["amount_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS

    error = validate_error(
        api.grant_opt_out_request(env["opt_out"]["id"], AGENT),
        ApiErrorId.ERR_FOLIO_NOT_ADJUSTABLE,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_FEE_LINE_NOT_ON_FOLIO

    request = validate_success(api.get_opt_out_request(env["opt_out"]["id"], AGENT))
    assert request["status"] == "REQUESTED"
    assert request["credit_cents"] == 0
    assert request["tax_credit_cents"] == 0
    assert request["credit_line_sequence_no"] is None

    folio = read_folio(env["folio"]["id"])
    assert folio["status"] == "ITEMIZED"
    assert folio["line_count"] == 4
    assert folio["credits_total_cents"] == 0
    assert folio["folio_total_cents"] == FOLIO_TOTAL_CENTS

    # The identical grant is admitted the moment the ledger reaches POSTED.
    setup_checked_out_booking(env=env)
    setup_posted_folio(env=env)
    granted = validate_success(api.grant_opt_out_request(env["opt_out"]["id"], AGENT))
    assert granted["status"] == "GRANTED"
    assert granted["credit_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert granted["tax_credit_cents"] == FOLIO_DESTINATION_TAX_CENTS
    assert granted["credit_line_sequence_no"] == 5
    assert read_folio(env["folio"]["id"])["status"] == "ADJUSTED"

    # Re-posting leaves the compensating window: revocation now sees POSTED.
    reposted = validate_success(api.post_folio(env["folio"]["id"], AGENT))
    assert reposted["status"] == "POSTED"
    assert reposted["folio_total_cents"] == CREDITED_FOLIO_TOTAL_CENTS
    validate_error(
        api.revoke_opt_out_request(env["opt_out"]["id"], AGENT),
        ApiErrorId.ERR_FOLIO_NOT_ADJUSTABLE,
        409,
    )


def test_only_a_live_path_may_take_a_booking_whatever_it_scores(api):
    """A flawless DRAFT path is unbookable; a repaired one is bookable again.

    PRD 3.4: "Only a live path can take a booking: the referenced profile must be
    in `DEPLOYED` or `REMEDIATED` status, and a `DRAFT`, `FLAGGED` or `RETIRED`
    path is rejected with `ERR_PROFILE_NOT_BOOKABLE` (HTTP 409). On success the
    profile's `fee_program_id` is **pinned** onto the booking as a system-written
    field."

    Design: Corner/validations/booking_against_a_draft_profile_is_rejected
    """
    env = setup_draft_profile()
    draft = env["profile"]
    assert draft["status"] == "DRAFT"
    assert draft["disclosure_score"] == 100

    def book(profile, channel):
        return api.create_booking(
            create_booking_payload(
                env["property"]["id"], channel["id"], profile["id"]
            ),
            AGENT,
        )

    validate_error(
        book(draft, env["channel"]), ApiErrorId.ERR_PROFILE_NOT_BOOKABLE, 409
    )
    _rows, meta = validate_paginated(
        api.list_bookings(AGENT, {"property_id": env["property"]["id"], "limit": 100})
    )
    assert meta["total_count"] == 0

    env["profile"] = deploy_profile(env)
    sold = validate_success(book(env["profile"], env["channel"]), 201)
    assert sold["quoted_total_cents"] == QUOTED_TOTAL_CENTS
    assert sold["fee_program_id"] == env["program"]["id"]

    # A path pulled out of service for a repair is unbookable in the same way.
    terminal = add_channel(env, "gds_channel", **CAPABLE_GDS)
    weak = deploy_profile(
        env, profile=add_draft_profile(env, channel=terminal, **UNDER_FLOOR_PROFILE)
    )
    assert weak["disclosure_score"] == 58
    flagged = validate_success(api.audit_profile(weak["id"], COMPLIANCE))
    assert flagged["status"] == "FLAGGED"
    validate_error(book(flagged, terminal), ApiErrorId.ERR_PROFILE_NOT_BOOKABLE, 409)

    repaired = remediate_profile(
        env, create_remediation_payload(), profile=flagged, headers=REVENUE
    )
    assert repaired["status"] == "REMEDIATED"
    resold = validate_success(book(repaired, terminal), 201)
    assert resold["quoted_total_cents"] == QUOTED_TOTAL_CENTS
    assert read_profile(weak["id"])["status"] == "REMEDIATED"


def test_an_opt_out_must_name_a_fee_of_the_pinned_inventory(api):
    """Membership answers at rank 24 while the same fee's rank-31 flaw waits.

    PRD 3.6: "Four business rules gate creation, and they fire in the global
    precedence order. The `fee_id` must belong to the booking's pinned
    `fee_program_id`, and a fee drawn from any other program is rejected with
    `ERR_FEE_NOT_ON_BOOKING_PROGRAM` (HTTP 422) ... The fee must have `avoidable`
    true **and** classification `MANDATORY` or `CONDITIONAL`, since a
    non-avoidable fee cannot be opted out of at all, and a violation is rejected
    with `ERR_FEE_NOT_AVOIDABLE` (HTTP 422)."

    Design: Corner/validations/opt_out_naming_a_fee_from_another_program_is_rejected
    """
    env = setup_confirmed_booking()
    booking = env["booking"]
    guest = make_guest_headers(booking["id"])
    prop = read_property(env["property"]["id"])
    successor = validate_success(
        api.create_fee_program(
            create_fee_program_payload(prop["id"], prop["version"], **SUCCESSOR_WINDOW),
            REVENUE,
        ),
        201,
    )
    foreign = add_fee(successor["id"], FOREIGN_SPA_FEE)

    assert booking["fee_program_id"] == env["program"]["id"]
    assert foreign["avoidable"] is False
    pinned_fees, _pinned_meta = validate_paginated(
        api.list_fees(REVENUE, {"fee_program_id": env["program"]["id"], "limit": 100})
    )
    assert foreign["id"] not in [fee["id"] for fee in pinned_fees]

    error = validate_error(
        api.create_opt_out_request(booking["id"], foreign["id"], guest),
        ApiErrorId.ERR_FEE_NOT_ON_BOOKING_PROGRAM,
        422,
    )
    assert error["error_id"] != ApiErrorId.ERR_FEE_NOT_AVOIDABLE

    _rows, meta = validate_paginated(
        api.list_opt_out_requests(AGENT, {"booking_id": booking["id"], "limit": 100})
    )
    assert meta["total_count"] == 0

    # The outranked rule is armed: the pinned program's own resort fee proves it.
    validate_error(
        api.create_opt_out_request(
            booking["id"], env["fees"]["RESORT"]["id"], guest
        ),
        ApiErrorId.ERR_FEE_NOT_AVOIDABLE,
        422,
    )

    accepted = validate_success(
        api.create_opt_out_request(
            booking["id"], env["fees"]["DESTINATION"]["id"], guest
        ),
        201,
    )
    assert accepted["status"] == "REQUESTED"
    assert accepted["requested_hours_before_arrival"] == NOTICE_HOURS_AT_CLOCK_START


def _stranger_folio_lines(api, env):
    """Itemise a second stay on the same path and return its ledger lines."""
    stranger = add_booking(env)
    validate_success(api.confirm_booking(stranger["id"], AGENT))
    validate_success(api.check_in_booking(stranger["id"], AGENT))
    folios = validate_success(api.list_booking_folios(stranger["id"], AGENT))
    other_folio = folios[0] if isinstance(folios, list) else folios["items"][0]
    validate_success(api.itemize_folio(other_folio["id"], AGENT))
    return read_folio_lines(other_folio["id"])


def test_a_complaint_may_only_name_a_fee_line_of_its_own_stay(api):
    """Room revenue, a credit, and a stranger's fee line all fail as one rule.

    PRD 3.7: "It is created under the booking by the owning `Guest` or by a
    `GuestServicesAgent`, and carries the `folio_line_id` of the specific
    disputed line, a `complaint_reason` from `NOT_DISCLOSED`,
    `MISSTATED_AMOUNT`, `MANDATORY_NOT_AVOIDABLE` and `TOTAL_NOT_SHOWN`, and a
    `narrative` of 8 to 1000 characters giving the guest's account of what was
    and was not shown. The line must belong to a folio of the addressed booking
    **and** have `line_type` `MANDATORY_FEE` or `OPTIONAL_FEE`; a room line, a
    credit line, or a line from someone else's folio is rejected with
    `ERR_FOLIO_LINE_NOT_ON_BOOKING` (HTTP 422)."

    Design: Corner/validations/complaint_naming_a_room_line_is_rejected
    """
    env = setup_granted_opt_out()
    env["folio"] = validate_success(api.post_folio(env["folio"]["id"], AGENT))
    booking = env["booking"]
    guest = make_guest_headers(booking["id"])
    lines = read_folio_lines(env["folio"]["id"])

    room = find_line_by_sequence(lines, 1)
    assert room["line_type"] == "ROOM"
    assert room["amount_cents"] == FOLIO_ROOM_AMOUNT_CENTS
    assert room["tax_cents"] == FOLIO_ROOM_TAX_CENTS
    credit = find_line_by_sequence(lines, 5)
    assert credit["line_type"] == "FEE_CREDIT"

    def complain(folio_line_id):
        return api.create_guest_complaint(
            booking["id"],
            create_guest_complaint_payload(
                folio_line_id,
                complaint_reason="MISSTATED_AMOUNT",
                narrative="The room rate itself was misquoted to me at booking.",
            ),
            guest,
        )

    validate_error(
        complain(room["id"]), ApiErrorId.ERR_FOLIO_LINE_NOT_ON_BOOKING, 422
    )
    validate_error(
        complain(credit["id"]), ApiErrorId.ERR_FOLIO_LINE_NOT_ON_BOOKING, 422
    )

    stranger_lines = _stranger_folio_lines(api, env)
    stranger_fee = find_line_by_sequence(stranger_lines, 2)
    assert stranger_fee["line_type"] == "MANDATORY_FEE"
    validate_error(
        complain(stranger_fee["id"]), ApiErrorId.ERR_FOLIO_LINE_NOT_ON_BOOKING, 422
    )

    _rows, meta = validate_paginated(
        api.list_guest_complaints(AGENT, {"booking_id": booking["id"], "limit": 100})
    )
    assert meta["total_count"] == 0

    own_fee = find_line_by_sequence(lines, 2)
    assert own_fee["amount_cents"] == FOLIO_RESORT_AMOUNT_CENTS
    filed = validate_success(complain(own_fee["id"]), 201)
    assert filed["status"] == "SUBMITTED"
    assert filed["disputed_amount_cents"] == 0
    _rows, meta = validate_paginated(
        api.list_guest_complaints(AGENT, {"booking_id": booking["id"], "limit": 100})
    )
    assert meta["total_count"] == 1


def test_the_notice_window_is_measured_in_floored_whole_hours(api):
    """Exactly 48 hours of notice is admitted; one minute less is not.

    PRD 3.6: "Finally the request must land early enough: the floored
    `requested_hours_before_arrival` must be at least the fee's
    `opt_out_window_hours`, and the comparison is **inclusive**, so a request
    arriving at exactly `opt_out_window_hours` before arrival is accepted while
    one arriving an hour later is rejected with `ERR_OPT_OUT_WINDOW_CLOSED`
    (HTTP 422)." PRD 3.6 on the figure itself:
    "`requested_hours_before_arrival` is the whole hours between the logical
    clock and the booking's `arrival_date`, **floored**".

    Design: Corner/validations/opt_out_requested_inside_the_notice_window_is_rejected
    """
    env = setup_confirmed_booking()
    early = env["booking"]
    late = add_booking(env)
    validate_success(api.confirm_booking(late["id"], AGENT))
    destination = env["fees"]["DESTINATION"]
    assert destination["avoidable"] is True
    assert destination["opt_out_window_hours"] == DESTINATION_OPT_OUT_WINDOW_HOURS

    move_clock_to(WINDOW_OPEN_INSTANT)
    on_the_boundary = validate_success(
        api.create_opt_out_request(
            early["id"], destination["id"], make_guest_headers(early["id"])
        ),
        201,
    )
    assert on_the_boundary["status"] == "REQUESTED"
    assert on_the_boundary["requested_hours_before_arrival"] == (
        DESTINATION_OPT_OUT_WINDOW_HOURS
    )

    # One second inside the window floors to 47 whole hours, never up to 48.
    move_clock_to(WINDOW_CLOSED_INSTANT)
    validate_error(
        api.create_opt_out_request(
            late["id"], destination["id"], make_guest_headers(late["id"])
        ),
        ApiErrorId.ERR_OPT_OUT_WINDOW_CLOSED,
        422,
    )
    move_clock_to(WINDOW_CLOSED_LATER_INSTANT)
    validate_error(
        api.create_opt_out_request(
            late["id"], destination["id"], make_guest_headers(late["id"])
        ),
        ApiErrorId.ERR_OPT_OUT_WINDOW_CLOSED,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_opt_out_requests(AGENT, {"booking_id": late["id"], "limit": 100})
    )
    assert meta["total_count"] == 0
    _rows, meta = validate_paginated(
        api.list_opt_out_requests(AGENT, {"booking_id": early["id"], "limit": 100})
    )
    assert meta["total_count"] == 1


def test_uniqueness_of_an_opt_out_is_scoped_to_the_live_statuses(api):
    """A denial frees the slot; a grant occupies it and outranks the shut window.

    PRD 3.6: "No other request for the same booking and fee pair may be in
    `REQUESTED` or `GRANTED`, a live duplicate being rejected with
    `ERR_DUPLICATE_OPT_OUT` (HTTP 409); a previously `DENIED`, `EXPIRED` or
    `REVOKED` request does not block a fresh one." PRD 3.6 on the freeing edge:
    "Denial is a `GuestServicesAgent` action from `REQUESTED` to `DENIED`,
    carrying a `denial_reason_code` of `NOT_AVOIDABLE`,
    `SERVICE_ALREADY_CONSUMED` or `POLICY_EXCEPTION_DENIED`. It sets that code
    and `decided_at`, appends no folio line, changes no money aggregate".

    Design: Corner/validations/a_second_pending_opt_out_for_the_same_fee_is_rejected
    """
    env = setup_requested_opt_out()
    booking = env["booking"]
    guest = make_guest_headers(booking["id"])
    destination = env["fees"]["DESTINATION"]

    def ask():
        return api.create_opt_out_request(booking["id"], destination["id"], guest)

    validate_error(ask(), ApiErrorId.ERR_DUPLICATE_OPT_OUT, 409)
    _rows, meta = validate_paginated(
        api.list_opt_out_requests(AGENT, {"booking_id": booking["id"], "limit": 100})
    )
    assert meta["total_count"] == 1
    assert validate_success(
        api.get_opt_out_request(env["opt_out"]["id"], AGENT)
    )["status"] == "REQUESTED"

    denied = validate_success(
        api.deny_opt_out_request(
            env["opt_out"]["id"], "SERVICE_ALREADY_CONSUMED", AGENT
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_reason_code"] == "SERVICE_ALREADY_CONSUMED"
    assert_stamped_at_clock(denied["decided_at"], CLOCK_START, "decided_at")
    assert denied["credit_cents"] == 0

    replacement = validate_success(ask(), 201)
    assert replacement["status"] == "REQUESTED"
    validate_error(ask(), ApiErrorId.ERR_DUPLICATE_OPT_OUT, 409)

    advance_to_posted_folio(env)
    granted = validate_success(api.grant_opt_out_request(replacement["id"], AGENT))
    assert granted["status"] == "GRANTED"
    assert granted["credit_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS

    # The clock is now past arrival, yet rank 30 answers before rank 32.
    error = validate_error(ask(), ApiErrorId.ERR_DUPLICATE_OPT_OUT, 409)
    assert error["error_id"] != ApiErrorId.ERR_OPT_OUT_WINDOW_CLOSED
    _rows, meta = validate_paginated(
        api.list_opt_out_requests(AGENT, {"booking_id": booking["id"], "limit": 100})
    )
    assert meta["total_count"] == 2


def test_avoidability_is_a_property_of_the_fee_and_of_its_classification(api):
    """A non-avoidable fee and an avoidable optional one share one refusal.

    PRD 3.6: "The fee must have `avoidable` true **and** classification
    `MANDATORY` or `CONDITIONAL`, since a non-avoidable fee cannot be opted out
    of at all, and a violation is rejected with `ERR_FEE_NOT_AVOIDABLE` (HTTP
    422)." PRD 3.2: "The boolean `avoidable` defaults to false and states whether
    a guest may decline the fee through an opt-out request. When `avoidable` is
    true, `opt_out_window_hours` is required ... When `avoidable` is false,
    `opt_out_window_hours` must be null".

    Design: Corner/validations/opt_out_on_a_non_avoidable_fee_is_rejected
    """
    env = setup_confirmed_booking(
        fee_payloads=[
            create_resort_fee_payload(),
            create_destination_fee_payload(),
            create_wifi_fee_payload(),
            SPA_FEE,
        ],
        taxability_spec={**CANONICAL_TAXABILITY, "SPA_ACCESS": ("EXEMPT", None)},
    )
    booking = env["booking"]
    guest = make_guest_headers(booking["id"])

    resort = validate_success(api.get_fee(env["fees"]["RESORT"]["id"], REVENUE))
    assert resort["avoidable"] is False
    assert resort["opt_out_window_hours"] is None

    validate_error(
        api.create_opt_out_request(booking["id"], resort["id"], guest),
        ApiErrorId.ERR_FEE_NOT_AVOIDABLE,
        422,
    )

    # An OPTIONAL fee is outside the admitted classifications even when avoidable.
    spa = validate_success(api.get_fee(env["fees"]["SPA_ACCESS"]["id"], REVENUE))
    assert spa["classification"] == "OPTIONAL"
    assert spa["avoidable"] is True
    validate_error(
        api.create_opt_out_request(booking["id"], spa["id"], guest),
        ApiErrorId.ERR_FEE_NOT_AVOIDABLE,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_opt_out_requests(AGENT, {"booking_id": booking["id"], "limit": 100})
    )
    assert meta["total_count"] == 0

    # The two mandatory fees differ only in avoidability and its window.
    accepted = validate_success(
        api.create_opt_out_request(
            booking["id"], env["fees"]["DESTINATION"]["id"], guest
        ),
        201,
    )
    assert accepted["status"] == "REQUESTED"
    assert accepted["requested_hours_before_arrival"] == NOTICE_HOURS_AT_CLOCK_START


def test_a_lapsed_docket_can_no_longer_be_answered_on_either_edge(api):
    """The deadline instant itself answers; one second later neither edge does.

    PRD 3.8: "Drafting is a `RegulatoryLiaison` action from `RECEIVED` to
    `RESPONSE_DRAFTED`, carrying the `response_summary` text. It requires the
    logical clock to be at or before `response_due_at`, a lapsed docket being
    rejected with `ERR_RESPONSE_WINDOW_EXPIRED` (HTTP 409) on the reasoning that
    a lapsed docket must be escalated by the regulator, not answered late."
    PRD 3.8 on the sibling edge: "It requires the submitting identity to differ
    from `drafted_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`, and it
    requires the logical clock still to be at or before `response_due_at`, on
    pain of `ERR_RESPONSE_WINDOW_EXPIRED`."

    Design: Corner/validations/drafting_an_inquiry_response_after_the_due_date_is_rejected
    """
    env = setup_received_inquiry()
    answered = env["inquiry"]
    lapsed = add_inquiry(env, docket_number="NV-2026-0092")
    assert answered["response_due_at"].startswith("2026-10-01T00:00:00")
    assert lapsed["status"] == "RECEIVED"

    move_clock_to(RESPONSE_DUE_AT)
    drafted = validate_success(
        api.draft_inquiry_response(
            answered["id"], "Every booking path has been audited.", LIAISON
        )
    )
    assert drafted["status"] == "RESPONSE_DRAFTED"

    move_clock_to(ONE_SECOND_PAST_DUE)
    validate_error(
        api.draft_inquiry_response(
            lapsed["id"], "Booking paths audited and corrected.", LIAISON
        ),
        ApiErrorId.ERR_RESPONSE_WINDOW_EXPIRED,
        409,
    )
    still_received = validate_success(api.get_regulator_inquiry(lapsed["id"], LIAISON))
    assert still_received["status"] == "RECEIVED"
    assert still_received["response_summary"] is None
    assert still_received["drafted_by_user_id"] is None

    validate_error(
        api.submit_inquiry_response(answered["id"], LIAISON_2),
        ApiErrorId.ERR_RESPONSE_WINDOW_EXPIRED,
        409,
    )
    unsubmitted = validate_success(api.get_regulator_inquiry(answered["id"], LIAISON))
    assert unsubmitted["status"] == "RESPONSE_DRAFTED"
    assert unsubmitted["submitted_by_user_id"] is None

    # Neither docket can be answered, so both remain open obligations.
    assert read_property(env["property"]["id"])["open_disclosure_obligation_count"] == 2


def test_a_docket_must_name_a_real_and_non_empty_channel_scope(api):
    """Emptiness and an unknown family share one code; a repeat is a shape error.

    PRD 3.8: "`channel_scope` is a non-empty array of `channel_type` literals
    with no duplicates; an empty array, or one containing any value that is not a
    `channel_type` member, is rejected with `ERR_INQUIRY_SCOPE_EMPTY` (HTTP 422).
    Only profiles on channels whose `channel_type` appears in that array are ever
    touched by this docket's directives." PRD 2.6 places the duplicate clause one
    ladder above: rank 7 checks "that `channel_scope` and `roll_in_fee_codes` are
    duplicate-free arrays of strings".

    Design: Corner/validations/inquiry_with_an_empty_channel_scope_is_rejected
    """
    env = setup_configuration()

    def file_docket(**overrides):
        return api.create_regulator_inquiry(
            create_regulator_inquiry_payload(
                env["jurisdiction"]["id"], env["property"]["id"], **overrides
            ),
            LIAISON,
        )

    validate_error(
        file_docket(channel_scope=[]), ApiErrorId.ERR_INQUIRY_SCOPE_EMPTY, 422
    )
    validate_error(
        file_docket(channel_scope=["KIOSK"]),
        ApiErrorId.ERR_INQUIRY_SCOPE_EMPTY,
        422,
    )
    validate_error(
        file_docket(channel_scope=["OTA", "OTA"]), ApiErrorId.ERR_INVALID_REQUEST, 422
    )

    _rows, meta = validate_paginated(
        api.list_regulator_inquiries(
            LIAISON, {"property_id": env["property"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0
    assert read_property(env["property"]["id"])["open_disclosure_obligation_count"] == 0

    filed = validate_success(file_docket(channel_scope=["OTA", "GDS"]), 201)
    assert filed["status"] == "RECEIVED"
    assert filed["channel_scope"] == ["OTA", "GDS"]
    assert filed["exposure_cents"] == 0
    assert filed["flagged_profile_ids"] == []
    assert read_property(env["property"]["id"])["open_disclosure_obligation_count"] == 1


def test_a_zero_priced_avoidable_fee_leaves_the_grant_nothing_to_credit(api):
    """The opt-out is lawful at every eligibility rule and still cannot be paid.

    PRD 3.6: "the folio must carry a `MANDATORY_FEE` line for the request's
    `fee_id` with no un-rebilled credit already standing against it, the absence
    being rejected with `ERR_FEE_LINE_NOT_ON_FOLIO` (HTTP 422). That absence is
    genuinely reachable: a `MANDATORY` avoidable fee whose stay amount computes
    to 0 cents is a legitimate opt-out target under the fee-membership and
    avoidability rules, yet itemisation wrote no line for it, so there is nothing
    to credit." PRD 3.5: "A mandatory fee that computes to 0 cents for this stay
    is still disclosed in the program but produces **no** folio line at all."

    Design: Corner/validations/opt_out_grant_for_a_zero_amount_fee_finds_no_line_to_credit
    """
    env = setup_confirmed_booking(
        fee_payloads=[
            create_resort_fee_payload(),
            create_destination_fee_payload(),
            ZERO_PRICED_PARKING_FEE,
        ],
        inclusion_spec={
            "RESORT": CANONICAL_INCLUSIONS["RESORT"],
            "DESTINATION": CANONICAL_INCLUSIONS["DESTINATION"],
            "PARKING": PARKING_INCLUSION,
        },
        taxability_spec={
            "RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS),
            "DESTINATION": ("TAXABLE_IF_MANDATORY", OCCUPANCY_TAX_RATE_BPS),
            "PARKING": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS),
        },
    )
    program = read_fee_program(env["program"]["id"])
    assert program["mandatory_fee_count"] == 3
    assert program["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_RESORT_PER_NIGHT_CENTS + PUBLISHED_DESTINATION_PER_NIGHT_CENTS
    )
    assert env["booking"]["quoted_mandatory_fee_cents"] == PARKING_QUOTED_FEE_CENTS
    assert env["booking"]["quoted_total_cents"] == PARKING_QUOTED_TOTAL_CENTS

    parking_request = add_opt_out_request(env, "PARKING")
    assert parking_request["status"] == "REQUESTED"
    assert parking_request["requested_hours_before_arrival"] == (
        NOTICE_HOURS_AT_CLOCK_START
    )
    destination_request = add_opt_out_request(env, "DESTINATION")

    advance_to_posted_folio(env)
    folio = read_folio(env["folio"]["id"])
    lines = read_folio_lines(folio["id"])
    assert folio["status"] == "POSTED"
    assert folio["line_count"] == 3
    assert [line["sequence_no"] for line in lines] == [1, 2, 3]
    assert env["fees"]["PARKING"]["id"] not in [line["fee_id"] for line in lines]
    assert folio["charges_subtotal_cents"] == PARKING_FOLIO_CHARGES_CENTS
    assert folio["credits_total_cents"] == 0
    assert folio["tax_total_cents"] == PARKING_FOLIO_TAX_TOTAL_CENTS
    assert folio["folio_total_cents"] == PARKING_FOLIO_TOTAL_CENTS
    assert read_booking(env["booking"]["id"])["quote_folio_variance_cents"] == -3

    error = validate_error(
        api.grant_opt_out_request(parking_request["id"], AGENT),
        ApiErrorId.ERR_FEE_LINE_NOT_ON_FOLIO,
        422,
    )
    assert error["error_id"] != ApiErrorId.ERR_FOLIO_NOT_ADJUSTABLE

    unpaid = validate_success(api.get_opt_out_request(parking_request["id"], AGENT))
    assert unpaid["status"] == "REQUESTED"
    assert unpaid["credit_cents"] == 0
    assert unpaid["credit_line_sequence_no"] is None
    assert read_folio(folio["id"])["line_count"] == 3

    # The same grant on a fee that did bill a line credits it in full.
    paid = validate_success(api.grant_opt_out_request(destination_request["id"], AGENT))
    assert paid["status"] == "GRANTED"
    assert paid["credit_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert paid["credit_line_sequence_no"] == 4
    adjusted = read_folio(folio["id"])
    assert adjusted["status"] == "ADJUSTED"
    assert adjusted["line_count"] == 4
    assert find_line_by_sequence(read_folio_lines(folio["id"]), 4)["line_type"] == (
        "FEE_CREDIT"
    )
