"""The validation ladder: which of several simultaneous defects is reported, and the guards that
refuse a write outright while leaving every counter where it stood."""

from test_helpers import (
    ActionType,
    AdmissionPath,
    ApiErrorId,
    NON_EXISTENT_UUID,
    RunVariant,
    TEST_DEFAULTS,
    TransferType,
    assert_compliance_breakdown,
    assert_fields_equal,
    assert_posture,
    assert_reconciliation,
    assert_tally,
    award_championship_event,
    cast_action_ballot,
    cast_action_ballots,
    close_action_voting,
    compute_run,
    create_conference,
    create_petitioned_member,
    create_protected_rivalry,
    create_revenue_pool,
    create_venue,
    draft_audit_report,
    execute_membership_action,
    host_championship_event,
    make_action_ballot_payload,
    make_auditor_headers,
    make_championship_event_payload,
    make_commissioner_headers,
    make_compliance_officer_headers,
    make_conference_payload,
    make_entry_fee_payment_payload,
    make_event_settlement_payload,
    make_finance_officer_headers,
    make_member_payload,
    make_member_representative_headers,
    make_member_update_payload,
    make_membership_action_payload,
    make_platform_admin_headers,
    make_protected_rivalry_payload,
    make_reserve_transfer_payload,
    make_schedule_game_payload,
    make_schedule_coordinator_headers,
    make_treasurer_headers,
    make_venue_payload,
    make_withdrawal_notice_payload,
    open_action_voting,
    post_run,
    propose_membership_action,
    read_conference,
    read_member,
    read_membership_action,
    read_revenue_pool,
    read_run_lines,
    set_logical_clock,
    setup_admit_action_in_voting,
    setup_approved_bowl_appearance,
    setup_charter_roster,
    setup_closed_media_pool,
    setup_computed_fy2026_final_run,
    setup_operating_conference,
    setup_operating_conference_with_reserve,
    setup_unit_based_pool,
    validate_error,
    validate_paginated,
    validate_success,
)


def _total(response):
    return validate_paginated(response)[1]["total_count"]


def _read_event(api, event_id):
    return validate_success(
        api.get_championship_event(event_id, headers=make_schedule_coordinator_headers())
    )


def _read_report(api, report_id):
    return validate_success(api.get_audit_report(report_id, headers=make_auditor_headers()))


def _reconciliation(api, run_id):
    return validate_success(
        api.get_run_reconciliation(run_id, headers=make_auditor_headers())
    )


def test_three_defects_at_once_report_the_earliest_rung_of_the_ladder(api):
    """PRD §2.8: "The service evaluates checks in a fixed order, and the first failure
    determines the response."
    PRD §2.8: "The full ladder is: authentication (`ERR_UNAUTHENTICATED`), role authorisation
    (`ERR_UNAUTHORIZED`), member ownership for a `MemberRepresentative`
    (`ERR_NOT_MEMBER_OWNER`), conference existence (`ERR_CONFERENCE_NOT_INITIALIZED`, or
    `ERR_CONFERENCE_ALREADY_EXISTS` on initialisation), path-identifier resolution (the 404
    family), request-shape validation (`ERR_INVALID_REQUEST`), pagination bounds
    (`ERR_INVALID_PAGINATION`), body foreign-key resolution (the 404 family again),
    institution-code uniqueness (`ERR_DUPLICATE_INSTITUTION_CODE`), member-pair distinctness
    (`ERR_MEMBER_PAIR_INVALID`), rivalry uniqueness (`ERR_DUPLICATE_RIVALRY`), the
    optimistic-concurrency version checks (the 412 family), the charter-window check
    (`ERR_CHARTER_WINDOW_CLOSED`), the per-entity status checks (`ERR_POOL_STATE_INVALID`,
    `ERR_RUN_STATE_INVALID`, `ERR_APPEARANCE_STATE_INVALID`, `ERR_ACTION_STATE_INVALID`,
    `ERR_PROPOSAL_STATE_INVALID`, `ERR_GAME_STATE_INVALID`, `ERR_EVENT_STATE_INVALID`,
    `ERR_REPORT_STATE_INVALID`, `ERR_MEMBER_STATE_INVALID`, in that relative order), the
    amendment budget (`ERR_AMEND_LIMIT_REACHED`), segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), the already-distributed guard on voiding an appearance
    (`ERR_UNITS_ALREADY_DISTRIBUTED`), the temporal checks
    (`ERR_MEMBER_REST_BUFFER_VIOLATION`, then `ERR_VENUE_CAPACITY_EXCEEDED`, then
    `ERR_INVALID_EFFECTIVE_YEAR`), the remaining shape constraints
    (`ERR_VENUE_NOT_HOME_VENUE`, then `ERR_INVALID_EVENT_WINDOW`, then
    `ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE`, then `ERR_DUPLICATE_BALLOT`), the referential
    preconditions (`ERR_NO_APPROVED_BUDGET`, then `ERR_BOWL_REVIEW_PENDING`, then
    `ERR_AUDIT_REPORT_NOT_ISSUED`, then `ERR_HOST_COMPLIANCE_INSUFFICIENT`, then
    `ERR_POOL_CLOSED_TO_REVENUE`, then `ERR_RECONCILIATION_IMBALANCE`), and finally the
    fiscal checks (`ERR_RESERVE_POSTURE_FROZEN`, then `ERR_AUDITED_EXPENSE_MISSING`, then
    `ERR_EMPTY_ALLOCATION_BASIS`, then `ERR_ENTRY_FEE_OUTSTANDING`, then
    `ERR_ENTRY_FEE_OVERPAYMENT`, then `ERR_RESERVE_INSUFFICIENT`)."
    PRD §2.8: "Request-shape validation is uniform across the API and raises
    `ERR_INVALID_REQUEST` (HTTP 400): every required field must be present, every enumerated
    value must be one the specification declares, every amount field named in cents and every
    count must be a non-negative integer, and every instant must parse as an ISO 8601 UTC
    timestamp."
    PRD §2.8: "Identifiers carried in a request body are resolved the same way and produce the
    same codes; body-level resolution covers member creation, revenue-pool creation,
    membership-action creation, budget-proposal creation, protected-rivalry creation,
    schedule-game creation, championship-event creation, audit-report creation, both
    ballot-casting operations, and member profile amendment, and the codes it can raise there
    are `ERR_VENUE_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_REVENUE_POOL_NOT_FOUND`,
    `ERR_DISTRIBUTION_RUN_NOT_FOUND` and `ERR_PROTECTED_RIVALRY_NOT_FOUND`."
    PRD §3.1: "The institution code must be 2 to 8 uppercase characters and must be unique
    across the conference; a collision with an existing member's code is refused with
    `ERR_DUPLICATE_INSTITUTION_CODE`."

    Design: Corner/validations/corner_priority_ordering_shape_then_body_fk_then_uniqueness
    """
    ctx = setup_charter_roster(api, member_keys=("north",))
    conference_id = ctx["conference_id"]
    headers = make_commissioner_headers()

    bad_enum = api.create_member(
        make_member_payload(
            conference_id,
            NON_EXISTENT_UUID,
            name="Defect Pileup College",
            institution_code="DPC",
            admission_path="INVITED",
            grant_of_rights_through_fiscal_year=2032,
        ),
        headers=headers,
    )
    bad_venue = api.create_member(
        make_member_payload(
            conference_id,
            NON_EXISTENT_UUID,
            name="Defect Pileup College",
            institution_code="DPC",
            grant_of_rights_through_fiscal_year=2032,
        ),
        headers=headers,
    )
    bad_venue_and_code = api.create_member(
        make_member_payload(
            conference_id,
            NON_EXISTENT_UUID,
            name="Defect Pileup College",
            institution_code="NOR",
            grant_of_rights_through_fiscal_year=2032,
        ),
        headers=headers,
    )
    duplicate_code = api.create_member(
        make_member_payload(
            conference_id,
            ctx["venue_north"]["id"],
            name="Defect Pileup College",
            institution_code="NOR",
            grant_of_rights_through_fiscal_year=2032,
        ),
        headers=headers,
    )

    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    validate_error(bad_venue, ApiErrorId.ERR_VENUE_NOT_FOUND.value, 404)
    # Body-FK resolution outranks uniqueness, so adding a duplicate code changes nothing.
    validate_error(bad_venue_and_code, ApiErrorId.ERR_VENUE_NOT_FOUND.value, 404)
    validate_error(
        duplicate_code, ApiErrorId.ERR_DUPLICATE_INSTITUTION_CODE.value, 409
    )
    assert _total(api.list_members(headers=headers)) == 1, "no refusal persisted a member"


def test_self_references_are_refused_and_the_rivalry_pair_is_compared_unordered(api):
    """PRD §3.4: "A game between a member and itself is refused first with
    `ERR_MEMBER_PAIR_INVALID`."
    PRD §3.4: "The two parties must be different institutions, and an attempt to protect a
    rivalry between a member and itself is refused with `ERR_MEMBER_PAIR_INVALID`."
    PRD §3.4: "The pair is treated as unordered: if any protected rivalry already links the
    same two institutions in this conference — whether it is still `ACTIVE` or has already gone
    `LAPSED` — the request is refused with `ERR_DUPLICATE_RIVALRY`, so the same fixture cannot
    be protected twice under two labels."
    PRD §3.1: "A member in `DEPARTED` or `ADMISSION_DENIED` may not be amended at all, which
    surfaces as `ERR_MEMBER_STATE_INVALID`, and a travel-partner value equal to the member's
    own identifier is refused with `ERR_MEMBER_PAIR_INVALID`."

    Design: Corner/validations/corner_paired_member_references_and_duplicate_rivalry_rejected
    """
    ctx = setup_charter_roster(api)
    ids = ctx["member_ids"]
    east = read_member(api, ids["east"])

    mirror_game = api.create_schedule_game(
        make_schedule_game_payload(
            ctx["conference_id"],
            ids["north"],
            ids["north"],
            ctx["venue_north"]["id"],
            "2026-09-05T19:00:00Z",
        ),
        headers=make_schedule_coordinator_headers(),
    )
    mirror_rivalry = api.create_protected_rivalry(
        make_protected_rivalry_payload(
            ctx["conference_id"], ids["north"], ids["north"], label="Mirror Match"
        ),
        headers=make_schedule_coordinator_headers(),
    )
    self_partner = api.update_member(
        ids["east"],
        make_member_update_payload(east["version"], travel_partner_member_id=ids["east"]),
        headers=make_commissioner_headers(),
    )
    rivalry = create_protected_rivalry(
        api, ctx["conference_id"], ids["north"], ids["south"], label="Prairie Rivalry"
    )
    reversed_rivalry = api.create_protected_rivalry(
        make_protected_rivalry_payload(
            ctx["conference_id"],
            ids["south"],
            ids["north"],
            label="Prairie Rivalry Reversed",
        ),
        headers=make_schedule_coordinator_headers(),
    )

    validate_error(mirror_game, ApiErrorId.ERR_MEMBER_PAIR_INVALID.value, 422)
    validate_error(mirror_rivalry, ApiErrorId.ERR_MEMBER_PAIR_INVALID.value, 422)
    validate_error(self_partner, ApiErrorId.ERR_MEMBER_PAIR_INVALID.value, 422)
    assert read_member(api, ids["east"])["version"] == east["version"]
    assert rivalry["status"] == "ACTIVE"
    # A (member_a_id, member_b_id) unique index would let the reversed pair through.
    validate_error(reversed_rivalry, ApiErrorId.ERR_DUPLICATE_RIVALRY.value, 409)
    assert (
        _total(api.list_protected_rivalries(headers=make_schedule_coordinator_headers()))
        == 1
    )
    assert (
        _total(api.list_schedule_games(headers=make_schedule_coordinator_headers())) == 0
    )


def test_the_two_singleton_guards_are_mirror_images_of_one_another(api):
    """PRD §2.4: "The service holds exactly one conference office record, and it must exist
    before anything else can be written."
    PRD §2.4: "Initialising it is a `PlatformAdmin` capability, and a second attempt to
    initialise while a conference record already exists is rejected with
    `ERR_CONFERENCE_ALREADY_EXISTS` (HTTP 409)."
    PRD §2.4: "Conversely, every write in the system other than conference initialisation
    itself and the logical-clock capability is rejected with `ERR_CONFERENCE_NOT_INITIALIZED`
    (HTTP 409) while no conference exists; read endpoints report the same code for the same
    reason."
    PRD §2.4: "The server never reads the host wall clock: instead it reads a logical clock,
    which a `PlatformAdmin` may set to an explicit instant supplied as `to_iso8601`, and the
    capability returns the newly established instant as `current_utc`."

    Design: Corner/validations/corner_conference_singleton_and_initialization_guards_rejected
    """
    # The clock is deliberately outside the guard, which is what lets a fixture pin
    # time before the conference exists at all.
    set_logical_clock(api)

    premature_venue = api.create_venue(
        make_venue_payload(name="Premature Pavilion", city="Nowhere", seating_capacity=20000),
        headers=make_platform_admin_headers(),
    )
    conference = create_conference(api)
    second_conference = api.create_conference(
        make_conference_payload(name="Rival Conference Office"),
        headers=make_platform_admin_headers(),
    )
    venue = create_venue(api)

    validate_error(
        premature_venue, ApiErrorId.ERR_CONFERENCE_NOT_INITIALIZED.value, 409
    )
    assert conference["version"] == 1
    validate_error(
        second_conference, ApiErrorId.ERR_CONFERENCE_ALREADY_EXISTS.value, 409
    )
    assert read_conference(api)["name"] == TEST_DEFAULTS["CONFERENCE_NAME"]
    assert venue["name"] == "Northfield Dome", "the same write succeeds once initialised"


def test_the_charter_window_shuts_the_instant_the_conference_starts_operating(api):
    """PRD §3.1: "Because the charter window closes when the conference graduates to
    `OPERATING`, a charter creation attempted after the first budget has been approved is
    refused with `ERR_CHARTER_WINDOW_CLOSED`."
    PRD §3.3: "Graduating to `OPERATING` is one-way and it is what closes the charter-seating
    window described in §3.1."
    PRD §3.1: "`PETITIONED` is the other path: the institution is created in status
    `PETITIONED` with `distribution_phase_bps` of 0, `voting_weight_bps` of 0, `phase_year` of
    0 and `entry_fee_paid_cents` of 0."

    Design: Corner/validations/corner_charter_admission_after_operating_rejected
    """
    ctx = setup_operating_conference(api)
    assert read_conference(api)["governance_status"] == "OPERATING"

    late_charter = api.create_member(
        make_member_payload(
            ctx["conference_id"],
            ctx["venue_east"]["id"],
            name="Latecomer University",
            institution_code="LAT",
            admission_path=AdmissionPath.CHARTER.value,
            grant_of_rights_through_fiscal_year=2034,
        ),
        headers=make_commissioner_headers(),
    )
    validate_error(late_charter, ApiErrorId.ERR_CHARTER_WINDOW_CLOSED.value, 409)
    assert _total(api.list_members(headers=make_commissioner_headers())) == 4

    # The identical payload on the petition path is accepted, and the refused attempt
    # persisted nothing, so reusing institution_code LAT does not trip uniqueness.
    petitioner = validate_success(
        api.create_member(
            make_member_payload(
                ctx["conference_id"],
                ctx["venue_east"]["id"],
                name="Latecomer University",
                institution_code="LAT",
                admission_path=AdmissionPath.PETITIONED.value,
                grant_of_rights_through_fiscal_year=2034,
            ),
            headers=make_commissioner_headers(),
        ),
        201,
    )
    assert_fields_equal(
        petitioner,
        status="PETITIONED",
        distribution_phase_bps=0,
        voting_weight_bps=0,
        phase_year=0,
        entry_fee_paid_cents=0,
    )


def test_an_effective_year_equal_to_the_current_year_is_refused_on_both_endpoints(api):
    """PRD §3.2: "The effective year must be strictly later than the conference's
    `current_fiscal_year`; an equal or earlier year is refused with
    `ERR_INVALID_EFFECTIVE_YEAR` (HTTP 422)."
    PRD §3.8: "The effective year must be strictly greater than the conference's
    `current_fiscal_year`, and a notice filed for the current year or an earlier one is refused
    with `ERR_INVALID_EFFECTIVE_YEAR` (HTTP 422)."
    PRD §3.2: "A new action is created in `PROPOSED` with `amend_count` of 0,
    `quorum_weight_bps` of 6000, `proposed_by_user_id` taken from the acting `X-User-ID`, and
    `version` 1."
    PRD §3.8: "Filing sets the member's `status` to `WITHDRAWAL_NOTICED`, stamps
    `withdrawal_notice_at` from the logical clock, drops its `voting_weight_bps` to 0 so it can
    no longer influence any ballot, switches its postseason-unit valuation to the
    `CURRENT_YEAR_ONLY` variant of §3.6, and advances the member's `version` by 1."

    Design: Corner/validations/corner_effective_fiscal_year_must_exceed_current_rejected
    """
    ctx = setup_operating_conference(api)
    petitioner = create_petitioned_member(api, ctx)
    assert read_conference(api)["current_fiscal_year"] == 2027

    same_year_admit = api.create_membership_action(
        make_membership_action_payload(
            ctx["conference_id"],
            petitioner["id"],
            action_type=ActionType.ADMIT.value,
            effective_fiscal_year=2027,
            rationale="same-year admission",
        ),
        headers=make_commissioner_headers(),
    )
    same_year_notice = api.file_withdrawal_notice(
        ctx["member_ids"]["north"],
        make_withdrawal_notice_payload(2027, reason="same-year exit"),
        headers=make_commissioner_headers(),
    )

    validate_error(same_year_admit, ApiErrorId.ERR_INVALID_EFFECTIVE_YEAR.value, 422)
    assert _total(api.list_membership_actions(headers=make_commissioner_headers())) == 0
    validate_error(same_year_notice, ApiErrorId.ERR_INVALID_EFFECTIVE_YEAR.value, 422)
    assert_fields_equal(
        read_member(api, ctx["member_ids"]["north"]),
        status="FULL_SHARE",
        voting_weight_bps=10000,
    )

    # One year later on the identical payloads and both are accepted.
    action = propose_membership_action(
        api,
        ctx["conference_id"],
        petitioner["id"],
        action_type=ActionType.ADMIT.value,
        effective_fiscal_year=2028,
    )
    notice = validate_success(
        api.file_withdrawal_notice(
            ctx["member_ids"]["north"],
            make_withdrawal_notice_payload(2028, reason="orderly exit"),
            headers=make_commissioner_headers(),
        )
    )

    assert_fields_equal(action, status="PROPOSED", amend_count=0, version=1)
    assert_fields_equal(
        notice,
        status="WITHDRAWAL_NOTICED",
        withdrawal_effective_fiscal_year=2028,
        voting_weight_bps=0,
    )


def test_a_weightless_voter_and_a_second_ballot_are_both_turned_away(api):
    """PRD §3.2: "Ballots are only accepted while the action is `VOTING`
    (`ERR_ACTION_STATE_INVALID` otherwise), the voting member must carry a positive
    `voting_weight_bps` (`ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE` otherwise), and a member that
    already holds a `CAST` ballot on the same question is refused with
    `ERR_DUPLICATE_BALLOT`."
    PRD §3.1: "A petitioner is an applicant, not a member — it earns nothing and votes on
    nothing until the membership admits it."
    PRD §3.2: "The eligible weight, `eligible_weight_bps`, is the sum of `voting_weight_bps`
    across the conference's members whose weight is positive, snapshotted at the moment voting
    closes — so a member that filed a withdrawal notice mid-vote drops out of both the
    numerator and the denominator."
    PRD §3.2: "Quorum is tested without division: `quorum_met` is true when `cast_weight_bps`
    multiplied by 10000 is greater than or equal to `eligible_weight_bps` multiplied by the
    quorum threshold of 6000 basis points."
    PRD §3.2: "The two branches differ in their consequences: an approval leaves the subject
    member untouched and merely unlocks execution, while a rejection of an `ADMIT` also drives
    the subject institution `PETITIONED` → `ADMISSION_DENIED` with `voting_weight_bps` set to 0
    and its `version` advanced."

    Design: Corner/validations/corner_ineligible_and_duplicate_ballots_rejected
    """
    ctx = setup_admit_action_in_voting(api)
    action_id = ctx["action_id"]
    central_id = ctx["member_ids"]["central"]
    north_id = ctx["member_ids"]["north"]
    cast_action_ballot(api, action_id, north_id)
    version = read_membership_action(api, action_id)["version"]

    self_interested = api.cast_action_ballot(
        action_id,
        make_action_ballot_payload(central_id, version),
        headers=make_member_representative_headers(central_id),
    )
    second_ballot = api.cast_action_ballot(
        action_id,
        make_action_ballot_payload(north_id, version, "AGAINST"),
        headers=make_member_representative_headers(north_id),
    )

    # Eligibility is read from the live weight, not from membership existence.
    validate_error(
        self_interested, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE.value, 409
    )
    validate_error(second_ballot, ApiErrorId.ERR_DUPLICATE_BALLOT.value, 409)
    ballots, meta = validate_paginated(
        api.list_action_ballots(action_id, headers=make_commissioner_headers())
    )
    assert meta["total_count"] == 1
    assert_fields_equal(ballots[0], member_id=north_id, choice="FOR", status="CAST")
    assert read_membership_action(api, action_id)["version"] == version

    # Neither refusal changed the tally: one full-share ballot out of four eligible.
    closed = close_action_voting(api, action_id)
    assert_tally(closed, 40000, 10000, 10000, 0, False, 10000, status="REJECTED")
    assert_fields_equal(
        read_member(api, central_id), status="ADMISSION_DENIED", voting_weight_bps=0
    )


def test_the_entry_fee_must_be_settled_exactly_before_the_seat_is_taken(api):
    """PRD §3.1: "A `Treasurer`, or the institution's own `MemberRepresentative`, records a
    payment as an `amount_cents` figure with an optional `reference` string, and the amount is
    added to the member's `entry_fee_paid_cents`."
    PRD §3.1: "Overpayment is refused rather than absorbed: if the existing
    `entry_fee_paid_cents` plus the new `amount_cents` would exceed the assessed
    `entry_fee_cents`, the payment fails with `ERR_ENTRY_FEE_OVERPAYMENT` (HTTP 422), so the
    sum of instalments can equal the assessment exactly but never surpass it."
    PRD §3.2: "For an `ADMIT`, the subject member moves `PETITIONED` → `ADMITTED_PHASING` with
    `phase_year` set to 1, the phase multiplier re-derived from that (2500 basis points under
    the default three-year ladder), `voting_weight_bps` set equal to `distribution_phase_bps`,
    and the action's `entry_fee_cents` copied onto the member as its assessment; an execution
    attempted while the institution still owes an assessed entry fee is refused with
    `ERR_ENTRY_FEE_OUTSTANDING`."
    PRD §3.2: "Execution sets the action to `EXECUTED` and advances its `version`."

    Design: Corner/validations/corner_entry_fee_outstanding_then_overpayment_rejected
    """
    ctx = setup_operating_conference(api)
    petitioner = create_petitioned_member(api, ctx, entry_fee_cents=5_000_000)
    action = propose_membership_action(
        api,
        ctx["conference_id"],
        petitioner["id"],
        action_type=ActionType.ADMIT.value,
        effective_fiscal_year=2028,
        entry_fee_cents=5_000_000,
    )
    open_action_voting(api, action["id"])
    cast_action_ballots(
        api,
        action["id"],
        [
            (ctx["member_ids"][key], "FOR")
            for key in ("north", "south", "east", "west")
        ],
    )
    approved = close_action_voting(api, action["id"])
    assert_tally(approved, 40000, 40000, 40000, 0, True, 10000, status="APPROVED")

    part_paid = validate_success(
        api.create_entry_fee_payment(
            petitioner["id"],
            make_entry_fee_payment_payload(3_000_000),
            headers=make_treasurer_headers(),
        )
    )
    early_execute = api.execute_membership_action(
        action["id"], headers=make_commissioner_headers()
    )
    one_cent_over = api.create_entry_fee_payment(
        petitioner["id"],
        make_entry_fee_payment_payload(2_000_001, reference="wire-2-too-big"),
        headers=make_treasurer_headers(),
    )

    assert part_paid["entry_fee_paid_cents"] == 3_000_000
    validate_error(early_execute, ApiErrorId.ERR_ENTRY_FEE_OUTSTANDING.value, 402)
    assert read_membership_action(api, action["id"])["status"] == "APPROVED"
    validate_error(one_cent_over, ApiErrorId.ERR_ENTRY_FEE_OVERPAYMENT.value, 422)
    assert read_member(api, petitioner["id"])["entry_fee_paid_cents"] == 3_000_000

    # Only the exact remainder unlocks the seating.
    settled = validate_success(
        api.create_entry_fee_payment(
            petitioner["id"],
            make_entry_fee_payment_payload(2_000_000, reference="wire-3"),
            headers=make_treasurer_headers(),
        )
    )
    executed = execute_membership_action(api, action["id"])

    assert settled["entry_fee_paid_cents"] == 5_000_000
    assert executed["status"] == "EXECUTED"
    assert_fields_equal(
        read_member(api, petitioner["id"]),
        status="ADMITTED_PHASING",
        phase_year=1,
        distribution_phase_bps=2500,
        voting_weight_bps=2500,
    )


def test_the_reserve_may_be_emptied_exactly_but_never_overdrawn(api):
    """PRD §3.3: "A withdrawal larger than the current `reserve_balance_cents` is refused with
    `ERR_RESERVE_INSUFFICIENT` (HTTP 422); the reserve may be emptied exactly but never
    overdrawn."
    PRD §3.3: "Every accepted transfer re-runs the posture derivation of §2.10, rewriting
    `reserve_posture` and `funded_ratio_bps`, and advances the conference's `version` by 1 —
    which is precisely why the next transfer needs a fresh read."
    PRD §2.10: "The funded ratio, `funded_ratio_bps`, is 10000 when the target is 0; otherwise
    it is `reserve_balance_cents` multiplied by 10000 and divided by `reserve_target_cents`,
    rounded down to a whole basis point."
    PRD §2.10: "The posture, `reserve_posture`, is one of `OPEN`, `RESERVE_RESTRICTED` or
    `FROZEN`, and is derived by comparing the balance against the target without dividing: when
    the target is 0 the posture is `OPEN`; otherwise, if the balance multiplied by 10000 is
    less than the target multiplied by 2500 basis points the posture is `FROZEN`; otherwise, if
    the balance multiplied by 10000 is less than the target multiplied by 6000 basis points the
    posture is `RESERVE_RESTRICTED`; otherwise the posture is `OPEN`."

    Design: Corner/validations/corner_reserve_withdrawal_exceeding_balance_rejected
    """
    setup_operating_conference_with_reserve(api)
    before = read_conference(api)
    assert before["reserve_target_cents"] == 18_000_000
    assert before["reserve_balance_cents"] == 12_000_000
    assert_posture(before, "OPEN", 6666)

    one_cent_over = api.create_reserve_transfer(
        make_reserve_transfer_payload(
            12_000_001,
            before["version"],
            transfer_type=TransferType.WITHDRAWAL.value,
            memo="one cent too many",
        ),
        headers=make_treasurer_headers(),
    )

    validate_error(one_cent_over, ApiErrorId.ERR_RESERVE_INSUFFICIENT.value, 422)
    unchanged = read_conference(api)
    assert_fields_equal(
        unchanged, reserve_balance_cents=12_000_000, version=before["version"]
    )
    assert_posture(unchanged, "OPEN", 6666)

    # The refusal moved no version, so the successful call reuses the same expectation.
    drained = validate_success(
        api.create_reserve_transfer(
            make_reserve_transfer_payload(
                12_000_000,
                before["version"],
                transfer_type=TransferType.WITHDRAWAL.value,
                memo="full drawdown",
            ),
            headers=make_treasurer_headers(),
        )
    )

    assert_fields_equal(
        drained, reserve_balance_cents=0, version=before["version"] + 1
    )
    assert_posture(drained, "FROZEN", 0)


def test_a_void_is_refused_once_a_unit_has_been_paid_on_a_posted_run(api):
    """PRD §3.6: "That compensation is only safe while the money has not yet gone out, so
    voiding an approved appearance is refused with `ERR_UNITS_ALREADY_DISTRIBUTED` when any of
    its postseason units is referenced by a distribution line whose parent run is `POSTED`."
    PRD §3.7: "Under `UNIT_BASED` it is 10000 multiplied by the member's count of postseason
    units in status `VALIDATED` whose `fiscal_year` equals the pool's `fiscal_year` — so a
    member with no validated units for that year has a raw weight of exactly 0."
    PRD §3.7: "A member whose `weight_bps` lands on exactly 0 — a fully phased-in school in a
    unit-based pool with no validated units, or a first-year school whose raw weight is small
    enough that the phase fraction floors it away — receives no distribution line at all, and
    therefore is never charged the governance service fee either."
    PRD §3.7: "The `reserve_draw_cents` is the smaller of `net_pool_cents` multiplied by the
    sweep rate divided by 10000 and rounded up to the next whole cent, and that shortfall — so
    a fully funded reserve draws nothing at all no matter what the rate says."
    PRD §3.7: "Posting sets the run `POSTED`, stamps `posted_at` from the logical clock and
    `posted_by_user_id` from the acting user, increases the conference's
    `reserve_balance_cents` by the run's `reserve_draw_cents` and re-derives `reserve_posture`
    and `funded_ratio_bps` from the new balance, increases `escrow_balance_cents` by the sum of
    the lines' `withheld_cents`, increases `governance_fee_revenue_cents` by the sum of the
    lines' `governance_fee_cents`, advances each affected member's `exit_settlement_paid_cents`
    by that member's line's `gor_offset_cents` where it is positive, and — only when the run's
    `variant` is `FINAL_AUDITED` and the pool's `pool_type` is `MEDIA_RIGHTS` — writes each
    line's `gross_share_cents` into that member's `last_full_annual_distribution_cents`, which
    is the figure every future exit settlement is assessed against."

    Design: Corner/validations/corner_void_after_units_distributed_rejected
    """
    ctx = setup_operating_conference_with_reserve(api)
    appearance = setup_approved_bowl_appearance(api, ctx["member_ids"]["north"])
    assert appearance["residual_to_pool_cents"] == 4_800_000
    pool = setup_unit_based_pool(api, ctx)
    run = compute_run(
        api,
        pool["id"],
        RunVariant.PROVISIONAL.value,
        expected_pool_version=pool["version"],
        memo="unit distribution",
    )
    posted = post_run(api, run["id"])

    voided = api.void_bowl_appearance(
        appearance["id"],
        {"reason": "expense documentation withdrawn"},
        headers=make_compliance_officer_headers(),
    )

    validate_error(voided, ApiErrorId.ERR_UNITS_ALREADY_DISTRIBUTED.value, 409)
    assert_fields_equal(
        posted,
        status="POSTED",
        total_weight_bps=20000,
        reserve_draw_cents=5_000_000,
        distributable_cents=95_000_000,
    )
    lines = read_run_lines(api, run["id"])
    assert len(lines) == 1, "the three zero-unit members receive no line at all"
    assert_fields_equal(
        lines[0],
        member_id=ctx["member_ids"]["north"],
        weight_bps=20000,
        gross_share_cents=95_000_000,
        withheld_cents=9_500_000,
        governance_fee_cents=1_250_000,
        net_payable_cents=84_250_000,
    )
    units, meta = validate_paginated(
        api.list_appearance_postseason_units(
            appearance["id"], headers=make_compliance_officer_headers()
        )
    )
    assert meta["total_count"] == 2
    for unit in units:
        assert unit["status"] == "VALIDATED"
    # The refused void disturbed none of the counters the post moved.
    assert_fields_equal(
        read_conference(api),
        validated_postseason_unit_count=2,
        escrow_balance_cents=14_300_000,
        reserve_balance_cents=17_000_000,
    )


def test_the_award_reads_the_hosts_live_score_rather_than_a_stored_one(api):
    """PRD §3.5: "Then the host must be scheduling in good faith: its
    `schedule_compliance_score` must be at least 90, and a host below that minimum is refused
    with `ERR_HOST_COMPLIANCE_INSUFFICIENT` (HTTP 422)."
    PRD §3.5: "A successful award creates the event in `SCHEDULED` and snapshots the host's
    score at that moment as `host_compliance_score_at_award`."
    PRD §3.4: "The first is 15 points for each **unmet protected rivalry** involving the
    member, where a rivalry counts as unmet if it is `LAPSED`, or if it is `ACTIVE` but the
    number of games referencing it in the current fiscal year with status `SCHEDULED` or
    `PLAYED` is fewer than its `required_annual_meetings`."
    PRD §3.5: "Because both windows are half-open, a requested window that begins exactly at
    another event's `window_end` does not intersect it and is therefore permitted."

    Design: Corner/validations/corner_host_compliance_below_minimum_rejected
    """
    ctx = setup_charter_roster(api)
    ids = ctx["member_ids"]
    pool = create_revenue_pool(api, ctx["conference_id"])
    create_protected_rivalry(
        api, ctx["conference_id"], ids["north"], ids["south"], label="Prairie Rivalry"
    )
    north_compliance = validate_success(
        api.get_schedule_compliance(
            ids["north"], headers=make_schedule_coordinator_headers()
        )
    )
    assert_compliance_breakdown(
        north_compliance,
        unmet_rivalry_count=1,
        travel_partner_gap_count=0,
        home_game_count=0,
        away_game_count=0,
        schedule_compliance_score=85,
    )

    refused = api.create_championship_event(
        make_championship_event_payload(
            ctx["conference_id"],
            ctx["venue_east"]["id"],
            ids["north"],
            pool["id"],
            "2027-03-01T00:00:00Z",
            "2027-03-05T00:00:00Z",
            sport="WRESTLING",
        ),
        headers=make_schedule_coordinator_headers(),
    )
    validate_error(refused, ApiErrorId.ERR_HOST_COMPLIANCE_INSUFFICIENT.value, 422)
    assert (
        _total(api.list_championship_events(headers=make_schedule_coordinator_headers()))
        == 0
    )

    # East is untouched by the rivalry, so the identical window is awarded to it.
    awarded = award_championship_event(
        api,
        ctx["conference_id"],
        ctx["venue_east"]["id"],
        ids["east"],
        pool["id"],
        "2027-03-01T00:00:00Z",
        "2027-03-05T00:00:00Z",
        sport="WRESTLING",
    )
    assert_fields_equal(
        awarded, status="SCHEDULED", host_compliance_score_at_award=100
    )


def test_a_settlement_into_a_closed_pool_leaks_not_one_cent(api):
    """PRD §3.5: "Settlement is only accepted while the linked pool can still absorb restated
    revenue, meaning its status is `DRAFT`, `OPEN` or `BOOKS_CLOSED`; against a `CLOSED` pool
    the settlement is refused with `ERR_POOL_CLOSED_TO_REVENUE`."
    PRD §3.7: "Closing a `BOOKS_CLOSED` pool permanently sets it `CLOSED`, and requires that at
    least one run on the pool has reached `POSTED`."
    PRD §3.5: "Confirming that an event was hosted moves it from either `SCHEDULED` or
    `HOST_AT_RISK` into `HOSTED`, and confirmation is deliberately permitted from the at-risk
    state so that a lapse in the host's scheduling compliance does not strand an event that has
    already been played."
    PRD §3.5: "The `participant_pool_cents` is added to the linked revenue pool's
    `gross_revenue_cents`."

    Design: Corner/validations/corner_settling_into_a_closed_pool_rejected
    """
    ctx = setup_closed_media_pool(api)
    pool = read_revenue_pool(api, ctx["pool_2026_id"])
    assert pool["status"] == "CLOSED"
    event = award_championship_event(
        api,
        ctx["conference_id"],
        ctx["venue_east"]["id"],
        ctx["member_ids"]["south"],
        pool["id"],
        "2027-03-01T00:00:00Z",
        "2027-03-05T00:00:00Z",
        sport="WRESTLING",
        fiscal_year=2026,
    )
    hosted = host_championship_event(api, event["id"])

    refused = api.settle_championship_event(
        event["id"],
        make_event_settlement_payload(48_000_000, 12_000_000, 21_000_000),
        headers=make_finance_officer_headers(),
    )

    validate_error(refused, ApiErrorId.ERR_POOL_CLOSED_TO_REVENUE.value, 409)
    # Half-settled is not a state the machine has: the event stays exactly HOSTED.
    assert_fields_equal(
        _read_event(api, event["id"]), status="HOSTED", version=hosted["version"]
    )
    assert_fields_equal(
        read_revenue_pool(api, pool["id"]),
        status="CLOSED",
        gross_revenue_cents=600_000_000,
        version=pool["version"],
    )


def test_the_conservation_identity_is_re_evaluated_at_issue_time(api):
    """PRD §3.9: "The report is created in `DRAFT` with `reconciliation_delta_cents` 0, and
    reports can be listed and filtered by `conference_id`, `distribution_run_id`,
    `fiscal_year` and `status`, or read individually."
    PRD §3.9: "The identity considers only the run's lines still in status `ACTIVE`, enumerated
    in the members' `created_at` ascending order; voided lines are excluded entirely, which is
    why a run whose lines have all been voided reconciles to its whole `net_pool_cents`."
    PRD §3.9: "Summing those active lines gives `total_net_payable_cents`,
    `total_withheld_cents`, `total_governance_fee_cents` and `total_gor_offset_cents`, and the
    `reconciliation_delta_cents` is the run's `net_pool_cents` minus the sum of its
    `reserve_draw_cents` and those four totals."
    PRD §3.9: "Issuing is refused with `ERR_RECONCILIATION_IMBALANCE` (HTTP 422) when the delta
    is anything other than 0, is refused with `ERR_REPORT_STATE_INVALID` unless the report is
    in `DRAFT`, and is refused with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID`
    equals the attested run's `computed_by_user_id` — an auditor may not attest a run they
    computed themselves."
    PRD §3.7: "A successful computation creates the run in `COMPUTED` with one `ACTIVE` line
    per line member, records the acting user as `computed_by_user_id`, writes `net_pool_cents`,
    `reserve_draw_cents`, `distributable_cents` and `total_weight_bps`, sets any earlier run on
    the same pool that is still `COMPUTED` to `SUPERSEDED` with `superseded_by_run_id` pointing
    at the new run and every one of that older run's `ACTIVE` lines moved to `VOIDED`, and
    advances the pool's `version` by 1."

    Design: Corner/validations/corner_reconciliation_imbalance_blocks_issue
    """
    ctx = setup_operating_conference_with_reserve(api)
    attested = setup_computed_fy2026_final_run(api, ctx)
    report = draft_audit_report(
        api, ctx["conference_id"], attested["id"], fiscal_year=2026
    )
    assert_fields_equal(report, status="DRAFT", reconciliation_delta_cents=0)
    replacement = compute_run(
        api,
        ctx["pool_2026_id"],
        RunVariant.FINAL_AUDITED.value,
        expected_pool_version=read_revenue_pool(api, ctx["pool_2026_id"])["version"],
        memo="recomputed settlement",
    )

    issued = api.issue_audit_report(report["id"], headers=make_auditor_headers())

    validate_error(issued, ApiErrorId.ERR_RECONCILIATION_IMBALANCE.value, 422)
    assert_fields_equal(
        _read_report(api, report["id"]), status="DRAFT", issued_by_user_id=None
    )
    superseded = validate_success(
        api.get_distribution_run(attested["id"], headers=make_finance_officer_headers())
    )
    assert_fields_equal(
        superseded, status="SUPERSEDED", superseded_by_run_id=replacement["id"]
    )
    for line in read_run_lines(api, attested["id"]):
        assert line["status"] == "VOIDED"
    # With every line voided the attested run reconciles to its whole net pool
    # less the sweep, which is the imbalance the issue refused.
    assert_reconciliation(
        _reconciliation(api, attested["id"]),
        net_pool_cents=596_000_000,
        reserve_draw_cents=6_000_000,
        total_net_payable_cents=0,
        total_withheld_cents=0,
        total_governance_fee_cents=0,
        total_gor_offset_cents=0,
        reconciliation_delta_cents=590_000_000,
    )
    # The imbalance is a property of the attested run, not of the pool.
    assert (
        _reconciliation(api, replacement["id"])["reconciliation_delta_cents"] == 0
    )
