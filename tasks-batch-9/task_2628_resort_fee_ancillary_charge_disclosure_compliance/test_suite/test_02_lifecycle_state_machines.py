"""Lifecycle edges: what each transition requires, stamps, refuses and repeats."""
from test_helpers import (
    ApiErrorId,
    ARRIVAL_DATE,
    CLOCK_START,
    CLOCK_START_TIMESTAMP,
    DEPARTURE_DATE,
    FOLIO_CHARGES_SUBTOTAL_CENTS,
    FOLIO_DESTINATION_AMOUNT_CENTS,
    FOLIO_TAX_TOTAL_CENTS,
    FOLIO_TOTAL_CENTS,
    FOLIO_WIFI_AMOUNT_CENTS,
    OCCUPANCY_TAX_RATE_BPS,
    PUBLISHED_RESORT_PER_NIGHT_CENTS,
    SINGLE_FEE_INCLUSIONS,
    USER_COMPLIANCE_OFFICER,
    USER_COMPLIANCE_OFFICER_2,
    USER_REVENUE_MANAGER,
    add_fee,
    add_inquiry,
    assert_booking_mirrors_folio,
    assert_folio_ledger_conservation,
    assert_folio_sequence_integrity,
    assert_stamped_at_clock,
    create_fee_program_payload,
    create_resort_fee_payload,
    find_line_by_sequence,
    move_clock_to,
    read_booking,
    read_clock,
    read_disclosure_summary,
    read_fee_program,
    read_folio,
    read_folio_lines,
    read_profile,
    read_property,
    setup_configuration,
    setup_confirmed_booking,
    setup_draft_program,
    setup_granted_opt_out,
    setup_investigated_complaint,
    setup_itemized_folio,
    setup_program_under_review,
    setup_requested_opt_out_on_posted_folio,
    setup_substantiated_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    AGENT,
    COMPLIANCE,
    COMPLIANCE_2,
    LIAISON,
    LIAISON_2,
    REVENUE,
)

CREDITED_TAX_TOTAL_CENTS = 17202
CREDITED_TOTAL_CENTS = 148372
REBILLED_CHARGES_SUBTOTAL_CENTS = 143130
REFUNDED_TOTAL_CENTS = 152552
REPOST_INSTANT = "2026-09-15T00:00:00Z"
SINGLE_FEE_PROGRAM = {
    "fee_payloads": [create_resort_fee_payload()],
    "inclusion_spec": SINGLE_FEE_INCLUSIONS,
    "taxability_spec": {"RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS)},
}
OPTIONAL_SPA_FEE = {
    "code": "SPA_CREDIT",
    "label": "Spa Credit",
    "classification": "OPTIONAL",
    "basis": "PER_STAY",
    "amount_cents": 5000,
    "disclosure_text": "An optional spa credit may be added to this stay on request.",
}


def test_a_new_inventory_lands_in_draft_with_every_attestation_field_null(api):
    """The author is recorded at once; the attesting fields wait for publication.

    PRD 3.2: "The new row lands in `DRAFT` status, which is one of `DRAFT`,
    `UNDER_REVIEW`, `PUBLISHED` and `SUPERSEDED`. Its `authored_by_user_id` is
    stamped from the acting `X-User-ID` and is the anchor for the
    segregation-of-duties check that fires later at attestation;
    `attested_by_user_id`, `attestation_note` and `published_at` are all null
    until then."

    Design: Corner/state_machines/fee_program_starts_in_draft_with_null_attestation_fields
    """
    env = setup_configuration(taxability_spec={})

    created = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                env["property"]["id"], env["property"]["version"]
            ),
            REVENUE,
        ),
        201,
    )

    assert created["status"] == "DRAFT"
    assert created["authored_by_user_id"] == USER_REVENUE_MANAGER
    assert created["attested_by_user_id"] is None
    assert created["attestation_note"] is None
    assert created["published_at"] is None
    assert created["supersedes_program_id"] is None
    assert created["version"] == 1
    assert created["created_at"] == CLOCK_START_TIMESTAMP

    assert read_property(env["property"]["id"])["published_fee_program_count"] == 0


def test_asking_for_review_changes_the_status_and_closes_the_edit_window(api):
    """Review refreshes the two counts and freezes the fee inventory.

    PRD 3.2: "Submitting the inventory for review moves it from `DRAFT` to
    `UNDER_REVIEW` and may be done by a `RevenueManager` or a
    `ComplianceOfficer`. It requires the program to be in `DRAFT`, the property to
    be `ACTIVE`, and the program to hold at least one fee of any classification
    ... The transition refreshes `fee_count` and `mandatory_fee_count` from the
    program's current fee rows and increments the program's `version`." PRD 3.2
    also pins where fees may be added: "Fees are appended to a draft program one
    at a time."

    Design: Corner/state_machines/fee_program_submit_review_moves_draft_to_under_review
    """
    env = setup_draft_program(**SINGLE_FEE_PROGRAM)
    before = read_fee_program(env["program"]["id"])

    reviewed = validate_success(
        api.submit_fee_program_for_review(env["program"]["id"], REVENUE)
    )

    assert reviewed["id"] == env["program"]["id"]
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["fee_count"] == 1
    assert reviewed["mandatory_fee_count"] == 1
    assert reviewed["published_at"] is None
    assert reviewed["attested_by_user_id"] is None
    assert reviewed["total_mandatory_fee_cents_per_night"] == 0
    assert float(reviewed["inclusion_coverage_ratio"]) == 0.0
    assert reviewed["version"] > before["version"]
    assert reviewed["updated_at"] == CLOCK_START_TIMESTAMP

    validate_error(
        api.create_fee(env["program"]["id"], OPTIONAL_SPA_FEE, REVENUE),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )


def test_an_empty_inventory_cannot_be_sent_to_review(api):
    """The status is legal, so the refusal names the emptiness and not the state.

    PRD 3.2: "It requires the program to be in `DRAFT`, the property to be
    `ACTIVE`, and the program to hold at least one fee of any classification; an
    empty program is rejected with `ERR_FEE_PROGRAM_EMPTY` (HTTP 409)."

    Design: Corner/state_machines/submit_review_on_a_program_with_no_fees_is_rejected
    """
    env = setup_configuration(taxability_spec={})
    program = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                env["property"]["id"], env["property"]["version"]
            ),
            REVENUE,
        ),
        201,
    )
    assert program["fee_count"] == 0

    error = validate_error(
        api.submit_fee_program_for_review(program["id"], REVENUE),
        ApiErrorId.ERR_FEE_PROGRAM_EMPTY,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE

    unchanged = read_fee_program(program["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == program["version"]

    # Any classification satisfies the precondition, not only a mandatory one.
    add_fee(program["id"], OPTIONAL_SPA_FEE)
    reviewed = validate_success(api.submit_fee_program_for_review(program["id"], REVENUE))
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["fee_count"] == 1
    assert reviewed["mandatory_fee_count"] == 0


def test_attestation_stamps_four_fields_and_computes_the_heavy_rollups(api):
    """Publication is the one moment the reference burden and coverage are computed.

    PRD 3.2: "On success the program moves `UNDER_REVIEW → PUBLISHED`, its
    `attested_by_user_id` is set from the acting `X-User-ID` and its
    `published_at` is set to the current logical clock. This is also the single
    moment at which the two heavier rollups leave their defaults ...
    `total_mandatory_fee_cents_per_night` becomes a reference per-night mandatory
    burden, computed against the *property's* `base_room_rate_cents` rather than
    any booking's rate ... every other fee contributes its unrounded per-night
    value rounded half up to whole cents". PRD 2.9: "Every field it reports must
    equal the denormalised counterpart stored on the property row."

    Design: Corner/state_machines/publish_stamps_attestation_and_computes_publication_rollups
    """
    env = setup_program_under_review(**SINGLE_FEE_PROGRAM)
    note = "Inclusion analysis reviewed; pool access valued at 1500 cents."
    property_before = read_property(env["property"]["id"])

    published = validate_success(
        api.publish_fee_program(env["program"]["id"], note, COMPLIANCE)
    )

    assert published["status"] == "PUBLISHED"
    assert published["attested_by_user_id"] == USER_COMPLIANCE_OFFICER
    assert published["attestation_note"] == note
    assert_stamped_at_clock(published["published_at"], CLOCK_START, "published_at")
    assert published["fee_count"] == 1
    assert published["mandatory_fee_count"] == 1
    # 29900 * 750 / 10000 is 2242.5 per night, carried half up.
    assert published["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_RESORT_PER_NIGHT_CENTS
    )
    assert float(published["inclusion_coverage_ratio"]) == 1.0

    property_after = read_property(env["property"]["id"])
    assert property_after["published_fee_program_count"] == 1
    assert property_after["version"] > property_before["version"]

    summary = read_disclosure_summary(env["property"]["id"])
    assert summary["published_fee_program_count"] == 1
    assert summary["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_RESORT_PER_NIGHT_CENTS
    )


def test_publication_cannot_skip_the_review_step_even_when_it_would_pass(api):
    """Every business check would pass; the source status alone refuses the call.

    PRD 3.2: "only then is the program's status examined, and a program not in
    `UNDER_REVIEW` fails with `ERR_INVALID_STATE`". PRD 3.2 on the lawful order:
    "Submitting the inventory for review moves it from `DRAFT` to
    `UNDER_REVIEW`".

    Design: Corner/state_machines/publish_directly_from_draft_is_rejected_as_invalid_state
    """
    env = setup_draft_program(**SINGLE_FEE_PROGRAM)
    note = "Attesting an inventory that never went to review."

    validate_error(
        api.publish_fee_program(env["program"]["id"], note, COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )

    refused = read_fee_program(env["program"]["id"])
    assert refused["status"] == "DRAFT"
    assert refused["published_at"] is None
    assert refused["attested_by_user_id"] is None
    assert refused["attestation_note"] is None
    assert refused["total_mandatory_fee_cents_per_night"] == 0
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 0

    # The review step was the only thing missing; nothing else had to change.
    validate_success(api.submit_fee_program_for_review(env["program"]["id"], REVENUE))
    published = validate_success(
        api.publish_fee_program(env["program"]["id"], note, COMPLIANCE)
    )
    assert published["status"] == "PUBLISHED"
    assert published["attested_by_user_id"] == USER_COMPLIANCE_OFFICER

    # No transition returns a published inventory to review.
    validate_error(
        api.submit_fee_program_for_review(env["program"]["id"], REVENUE),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )


def test_check_in_before_the_arrival_instant_leaves_no_orphan_folio(api):
    """The refused transition suppresses its folio side effect entirely.

    PRD 3.4: "Check-in is a `GuestServicesAgent` action and advances
    `stay_status` from `CONFIRMED` to `IN_HOUSE`. It requires the logical clock
    to be at or after the booking's `arrival_date`, with equality permitted; an
    early attempt is rejected with `ERR_ARRIVAL_NOT_REACHED` (HTTP 409).
    Check-in creates exactly one folio for the booking, in `OPEN` status with
    `line_count` 0 and every monetary aggregate at 0, and increments the
    booking's `version`."

    Design: Corner/state_machines/check_in_before_arrival_date_is_rejected_and_creates_no_folio
    """
    env = setup_confirmed_booking()
    booking_before = env["booking"]

    assert booking_before["stay_status"] == "CONFIRMED"
    assert_stamped_at_clock(booking_before["arrival_date"], ARRIVAL_DATE, "arrival_date")
    assert_stamped_at_clock(read_clock(), CLOCK_START, "current_utc")

    validate_error(
        api.check_in_booking(booking_before["id"], AGENT),
        ApiErrorId.ERR_ARRIVAL_NOT_REACHED,
        409,
    )

    refused = read_booking(booking_before["id"])
    assert refused["stay_status"] == "CONFIRMED"
    assert refused["version"] == booking_before["version"]
    folios, meta = validate_paginated(api.list_booking_folios(booking_before["id"], AGENT))
    assert folios == []
    assert meta["total_count"] == 0

    # Equality is permitted, so the arrival instant itself admits the check-in.
    move_clock_to(ARRIVAL_DATE)
    checked_in = validate_success(api.check_in_booking(booking_before["id"], AGENT))
    assert checked_in["stay_status"] == "IN_HOUSE"
    assert checked_in["version"] > booking_before["version"]

    folios, meta = validate_paginated(api.list_booking_folios(booking_before["id"], AGENT))
    assert meta["total_count"] == 1
    folio = folios[0]
    assert folio["status"] == "OPEN"
    assert folio["line_count"] == 0
    assert folio["itemization_complete"] is False
    assert folio["charges_subtotal_cents"] == 0
    assert folio["credits_total_cents"] == 0
    assert folio["tax_total_cents"] == 0
    assert folio["folio_total_cents"] == 0
    assert folio["posted_at"] is None


def test_an_accepted_docket_has_no_outgoing_edge_at_all(api):
    """Every one of the docket's five actions is refused from ACCEPTED.

    PRD 3.8: "Statuses are `RECEIVED`, `RESPONSE_DRAFTED`, `RESPONSE_SUBMITTED`,
    `REMEDIATION_REQUIRED`, `REMEDIATION_SUBMITTED`, `ACCEPTED` and `WITHDRAWN`,
    with `ACCEPTED` and `WITHDRAWN` terminal, and the machine is cyclic through
    the remediation rounds." PRD 3.8 on the compensating action: "it is reachable
    from `RECEIVED`, from `RESPONSE_DRAFTED`, from `RESPONSE_SUBMITTED` and from
    `REMEDIATION_REQUIRED`; `WITHDRAWN` is **not** reachable from
    `REMEDIATION_SUBMITTED` and not from `ACCEPTED`."

    Design: Corner/state_machines/accepted_inquiry_is_terminal_and_rejects_further_transitions
    """
    env = setup_configuration()
    inquiry = add_inquiry(env)
    validate_success(
        api.draft_inquiry_response(
            inquiry["id"], "The operator's account of its disclosure practice.", LIAISON
        )
    )
    validate_success(api.submit_inquiry_response(inquiry["id"], LIAISON_2))
    validate_success(
        api.require_inquiry_remediation(
            inquiry["id"], "Repair every in-scope booking path.", ADMIN
        )
    )
    validate_success(
        api.submit_inquiry_remediation(
            inquiry["id"], "There were no in-scope paths to repair.", LIAISON
        )
    )
    accepted = validate_success(api.accept_inquiry(inquiry["id"], ADMIN))

    assert accepted["status"] == "ACCEPTED"
    assert accepted["flagged_profile_ids"] == []
    assert accepted["remediation_round"] == 1
    property_before = read_property(env["property"]["id"])
    assert property_before["open_disclosure_obligation_count"] == 0

    validate_error(
        api.withdraw_inquiry(
            inquiry["id"], "Attempting to withdraw an accepted docket.", ADMIN
        ),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.reject_inquiry_remediation(inquiry["id"], "Reopening the docket.", ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.submit_inquiry_remediation(inquiry["id"], "A further repair.", LIAISON),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.require_inquiry_remediation(inquiry["id"], "A further order.", ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.submit_inquiry_response(inquiry["id"], LIAISON_2),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.draft_inquiry_response(inquiry["id"], "A later account.", LIAISON),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )

    locked = validate_success(api.get_regulator_inquiry(inquiry["id"], ADMIN))
    assert locked["status"] == "ACCEPTED"
    assert locked["withdrawal_reason"] is None
    assert locked["rejection_reason"] is None
    property_after = read_property(env["property"]["id"])
    assert property_after["open_disclosure_obligation_count"] == 0
    assert property_after["version"] == property_before["version"]


def test_a_repeated_action_call_is_a_conflict_and_not_a_second_success(api):
    """The from-state no longer holds, so the second call bumps nothing at all.

    PRD 2.6: "Target-state admissibility for the requested transition, including
    terminal-state lockdown — `ERR_INVALID_STATE` (HTTP 409)." PRD 3.2: "It
    requires the program to be in `DRAFT`, the property to be `ACTIVE`, and the
    program to hold at least one fee of any classification".

    Design: Corner/state_machines/repeating_submit_review_on_the_same_program_is_rejected
    """
    env = setup_program_under_review(**SINGLE_FEE_PROGRAM)
    first = env["program"]
    assert first["status"] == "UNDER_REVIEW"

    validate_error(
        api.submit_fee_program_for_review(first["id"], REVENUE),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )

    unchanged = read_fee_program(first["id"])
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["version"] == first["version"]
    assert unchanged["updated_at"] == first["updated_at"]

    # The same non-idempotence holds along the deploy, confirm and itemise edges.
    # A jurisdiction `code` is globally unique, so the second configuration this
    # test builds registers its own authority rather than repeating the first's.
    env = setup_itemized_folio(
        env=None,
        jurisdiction_overrides={
            "code": "US-NV-WASHOE",
            "name": "Washoe County, Nevada",
        },
        **SINGLE_FEE_PROGRAM,
    )
    validate_error(
        api.deploy_profile(env["profile"]["id"], COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.confirm_booking(env["booking"]["id"], AGENT),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.itemize_folio(env["folio"]["id"], AGENT),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )


def test_closing_the_folio_expires_an_undecided_opt_out_without_moving_money(api):
    """Expiry is a stamp only: no credit line, no aggregate touched, EXPIRED final.

    PRD 3.5: "Closing expires every opt-out request on the booking that is still
    `REQUESTED`, stamping each one's `decided_at` with the logical clock, and
    increments the folio's `version`." PRD 3.6: "Expiry is not a caller action at
    all: closing the booking's folio moves every still-`REQUESTED` request to
    `EXPIRED`, stamping `decided_at` with the logical clock and incrementing each
    `version`."

    Design: Corner/state_machines/folio_close_expires_a_still_pending_opt_out_request
    """
    env = setup_requested_opt_out_on_posted_folio()
    opt_out_before = env["opt_out"]
    folio_before = read_folio(env["folio"]["id"])

    assert opt_out_before["status"] == "REQUESTED"
    assert opt_out_before["decided_at"] is None
    assert opt_out_before["credit_cents"] == 0
    assert opt_out_before["credit_line_sequence_no"] is None
    assert folio_before["status"] == "POSTED"
    assert folio_before["line_count"] == 4
    assert folio_before["folio_total_cents"] == FOLIO_TOTAL_CENTS

    closed = validate_success(api.close_folio(env["folio"]["id"], AGENT))

    assert closed["status"] == "CLOSED"
    assert closed["line_count"] == 4
    assert closed["charges_subtotal_cents"] == FOLIO_CHARGES_SUBTOTAL_CENTS
    assert closed["credits_total_cents"] == 0
    assert closed["tax_total_cents"] == FOLIO_TAX_TOTAL_CENTS
    assert closed["folio_total_cents"] == FOLIO_TOTAL_CENTS

    expired = validate_success(api.get_opt_out_request(opt_out_before["id"], AGENT))
    assert expired["status"] == "EXPIRED"
    assert_stamped_at_clock(expired["decided_at"], DEPARTURE_DATE, "decided_at")
    assert expired["credit_cents"] == 0
    assert expired["tax_credit_cents"] == 0
    assert expired["credit_line_sequence_no"] is None
    assert expired["denial_reason_code"] is None
    assert expired["version"] > opt_out_before["version"]

    lines = read_folio_lines(env["folio"]["id"])
    assert len(lines) == 4
    assert [line["line_type"] for line in lines] == [
        "ROOM",
        "MANDATORY_FEE",
        "MANDATORY_FEE",
        "MANDATORY_FEE",
    ]
    assert_folio_ledger_conservation(closed, lines)
    assert_folio_sequence_integrity(closed, lines)
    assert read_booking(env["booking"]["id"])["guest_out_of_pocket_cents"] == (
        FOLIO_TOTAL_CENTS
    )

    # EXPIRED is terminal, so the guest's request can no longer be granted.
    validate_error(
        api.grant_opt_out_request(opt_out_before["id"], AGENT),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )


def test_dismissal_clears_the_booking_and_touches_nothing_else(api):
    """UNSUBSTANTIATED restores standing without rescoring or moving one cent.

    PRD 3.7: "Dismissal moves the complaint to `UNSUBSTANTIATED` and its
    side-effect set is **deliberately disjoint** from substantiation's. It
    records the mandatory `dismissal_reason_code`, forces
    `refund_entitlement_cents` to 0 and leaves `refund_variant` null, moves the
    booking's `disclosure_status` to `DISCLOSED` when it is `PENDING_AUDIT` or
    `DISPUTED` ... It does **not** touch the path's
    `confirmed_undisclosed_count`, does **not** rescore the path, and therefore
    causes no posture change and no flagging."

    Design: Corner/state_machines/complaint_dismissal_side_effects_are_disjoint_from_substantiation
    """
    env = setup_investigated_complaint()
    profile_before = read_profile(env["profile"]["id"])
    assert profile_before["disclosure_score"] == 100
    assert profile_before["confirmed_undisclosed_count"] == 0
    assert read_booking(env["booking"]["id"])["disclosure_status"] == "PENDING_AUDIT"

    dismissed = validate_success(
        api.dismiss_complaint(
            env["complaint"]["id"], "DISCLOSURE_EVIDENCED", COMPLIANCE_2
        )
    )

    assert dismissed["status"] == "UNSUBSTANTIATED"
    assert dismissed["adjudicated_by_user_id"] == USER_COMPLIANCE_OFFICER_2
    assert dismissed["dismissal_reason_code"] == "DISCLOSURE_EVIDENCED"
    assert dismissed["refund_entitlement_cents"] == 0
    assert dismissed["refund_variant"] is None
    # PRD 3.7: "a system `refunded_amount_cents` defaulting to 0".
    assert dismissed["refunded_amount_cents"] == 0

    assert read_booking(env["booking"]["id"])["disclosure_status"] == "DISCLOSED"

    profile_after = read_profile(env["profile"]["id"])
    assert profile_after["confirmed_undisclosed_count"] == 0
    assert profile_after["disclosure_score"] == 100
    assert profile_after["status"] == "DEPLOYED"
    assert profile_after["version"] == profile_before["version"]

    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 100
    assert prop["disclosure_posture"] == "COMPLIANT"
    assert prop["open_disclosure_obligation_count"] == 0
    assert prop["aggregate_disclosure_gap_cents"] == 0

    folio = read_folio(env["folio"]["id"])
    assert folio["status"] == "POSTED"
    assert folio["line_count"] == 4
    assert folio["credits_total_cents"] == 0
    assert folio["folio_total_cents"] == FOLIO_TOTAL_CENTS

    # REFUNDED is reachable only from SUBSTANTIATED.
    validate_error(
        api.refund_complaint(env["complaint"]["id"], 1, AGENT),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )


def test_paying_a_substantiated_complaint_appends_a_credit_and_cures_the_stay(api):
    """Five lines, both money mirrors re-derived, and the channel's record kept.

    PRD 3.7: "It appends one `COMPLAINT_REFUND` line with `amount_cents` equal to
    `refund_amount_cents` carried **positive** under the credit sign convention,
    `tax_cents` of 0 and `taxability_determination` `EXEMPT` ... It records
    `refunded_amount_cents`, moves the folio `POSTED → ADJUSTED` ... re-derives
    the folio subtotals and the booking's `folio_total_cents` and
    `guest_out_of_pocket_cents`, moves the booking's `disclosure_status` from
    `UNDISCLOSED_CONFIRMED` to `CURED` ... while **leaving the path's
    `confirmed_undisclosed_count` intact**."

    Design: Corner/state_machines/complaint_refund_syncs_the_folio_ledger_and_the_booking_aggregates
    """
    env = setup_substantiated_complaint()
    complaint = env["complaint"]

    assert complaint["status"] == "SUBSTANTIATED"
    assert complaint["refund_variant"] == "FULL_FEE_REFUND"
    assert complaint["disputed_amount_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert complaint["disclosed_amount_cents"] == 0
    assert complaint["refund_entitlement_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert read_booking(env["booking"]["id"])["disclosure_status"] == (
        "UNDISCLOSED_CONFIRMED"
    )

    refunded = validate_success(
        api.refund_complaint(complaint["id"], FOLIO_WIFI_AMOUNT_CENTS, AGENT)
    )

    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded_amount_cents"] == FOLIO_WIFI_AMOUNT_CENTS

    lines = read_folio_lines(env["folio"]["id"])
    assert len(lines) == 5
    charged = find_line_by_sequence(lines, 4)
    assert charged["line_type"] == "MANDATORY_FEE"
    assert charged["fee_code"] == "WIFI_PREMIUM"
    assert charged["amount_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert charged["tax_cents"] == 0
    credit = find_line_by_sequence(lines, 5)
    assert credit["line_type"] == "COMPLAINT_REFUND"
    assert credit["amount_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert credit["tax_cents"] == 0
    assert credit["taxability_determination"] == "EXEMPT"

    folio = read_folio(env["folio"]["id"])
    assert folio["status"] == "ADJUSTED"
    assert folio["line_count"] == 5
    assert folio["charges_subtotal_cents"] == FOLIO_CHARGES_SUBTOTAL_CENTS
    assert folio["credits_total_cents"] == FOLIO_WIFI_AMOUNT_CENTS
    assert folio["tax_total_cents"] == FOLIO_TAX_TOTAL_CENTS
    assert folio["folio_total_cents"] == REFUNDED_TOTAL_CENTS
    assert_folio_ledger_conservation(folio, lines)
    assert_folio_sequence_integrity(folio, lines)

    booking = read_booking(env["booking"]["id"])
    assert booking["folio_total_cents"] == REFUNDED_TOTAL_CENTS
    assert booking["guest_out_of_pocket_cents"] == REFUNDED_TOTAL_CENTS
    assert booking["disclosure_status"] == "CURED"
    assert_booking_mirrors_folio(booking, folio)

    profile = read_profile(env["profile"]["id"])
    assert profile["confirmed_undisclosed_count"] == 1
    assert profile["disclosure_score"] == 95
    assert read_property(env["property"]["id"])["open_disclosure_obligation_count"] == 0


def test_an_adjusted_folio_must_be_reposted_before_it_can_ever_be_closed(api):
    """POSTED is re-entered, the aggregates hold, and the close edge needs it.

    PRD 3.5: "From `ADJUSTED` it requires the folio to be `ADJUSTED`, the booking
    to be `CHECKED_OUT`, and **no** opt-out request on the booking to still be in
    `REQUESTED` ... Either edge sets `posted_at` to the logical clock and
    increments the folio's `version`." PRD 3.5 on the close edge: "**There is no
    edge from `ADJUSTED` to `CLOSED`**: an adjusted folio must be re-posted
    first, so an unposted adjustment can never be locked away."

    Design: Corner/state_machines/folio_reposts_after_an_adjustment_closing_the_itemize_post_adjust_cycle
    """
    env = setup_granted_opt_out()
    adjusted = read_folio(env["folio"]["id"])

    assert adjusted["status"] == "ADJUSTED"
    assert adjusted["line_count"] == 5
    assert adjusted["charges_subtotal_cents"] == FOLIO_CHARGES_SUBTOTAL_CENTS
    assert adjusted["credits_total_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert adjusted["tax_total_cents"] == CREDITED_TAX_TOTAL_CENTS
    assert adjusted["folio_total_cents"] == CREDITED_TOTAL_CENTS
    assert_stamped_at_clock(adjusted["posted_at"], DEPARTURE_DATE, "posted_at")

    validate_error(
        api.close_folio(adjusted["id"], AGENT), ApiErrorId.ERR_INVALID_STATE, 409
    )

    # "A folio already in `ADJUSTED` stays there when a further compensating line
    # lands", and revocation itself requires that adjustable state, so the mirror
    # rebill lands before the folio is taken back to POSTED.
    validate_success(api.revoke_opt_out_request(env["opt_out"]["id"], AGENT))
    readjusted = read_folio(adjusted["id"])
    assert readjusted["status"] == "ADJUSTED"
    assert readjusted["line_count"] == 6
    assert readjusted["folio_total_cents"] == FOLIO_TOTAL_CENTS

    # The close edge is still refused: only POSTED admits it.
    validate_error(
        api.close_folio(adjusted["id"], AGENT), ApiErrorId.ERR_INVALID_STATE, 409
    )

    move_clock_to(REPOST_INSTANT)
    reposted = validate_success(api.post_folio(adjusted["id"], AGENT))

    assert reposted["status"] == "POSTED"
    assert reposted["version"] == readjusted["version"] + 1
    assert_stamped_at_clock(reposted["posted_at"], REPOST_INSTANT, "posted_at")
    assert reposted["line_count"] == 6
    assert reposted["charges_subtotal_cents"] == REBILLED_CHARGES_SUBTOTAL_CENTS
    assert reposted["credits_total_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert reposted["tax_total_cents"] == FOLIO_TAX_TOTAL_CENTS
    assert reposted["folio_total_cents"] == FOLIO_TOTAL_CENTS

    closed = validate_success(api.close_folio(adjusted["id"], AGENT))
    assert closed["status"] == "CLOSED"
    assert closed["line_count"] == 6
