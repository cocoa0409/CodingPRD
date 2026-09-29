"""State machines: declared initial states, out-of-order triggers, terminal replays and forks."""

from test_helpers import api_client, validate_error, validate_paginated, validate_success
from test_helpers.constants import MISSING_UUID
from test_helpers.factories import (
    acknowledgement_payload,
    create_compliance_case_payload,
    create_division_payload,
    create_results_payload,
    placing_row,
)
from test_helpers.fixtures import (
    activate_coverage_shift,
    build_active_coverage,
    build_approved_show,
    build_confirmed_entry,
    build_entry,
    build_field,
    build_judge_and_steward,
    build_point_submission,
    build_show_with_class_list,
    build_steward,
    card_judge_and_steward,
    card_official,
    class_version,
    create_coverage_shift,
    create_horse,
    create_official,
    create_rider,
    create_ring,
    create_show,
    decide_license,
    get_class,
    get_class_entry,
    get_entry,
    get_ring,
    get_show,
    get_slot,
    open_class,
    open_compliance_case,
    record_finding,
    record_footing_maintenance,
    set_clock,
    start_slot,
    submit_license,
    book_slot,
)
from test_helpers.test_users import TEST_USERS, make_exhibitor_headers, make_judge_headers

SECRETARY = TEST_USERS["show_secretary_headers"]
OFFICER = TEST_USERS["federation_officer_headers"]
RING_MASTER = TEST_USERS["ring_master_headers"]
GROUNDS = TEST_USERS["grounds_manager_headers"]

TWO_JUMPER_CLASSES = [
    {"class_number": 101, "name": "Open Jumper 1.20m", "jump_height_cm": 120, "class_share_bp": 1669},
    {"class_number": 102, "name": "Open Jumper 1.10m", "jump_height_cm": 110, "class_share_bp": 1000},
]

COMPETITION_DAY_CLOCK = "2026-09-10T13:30:00Z"


def _card(class_id, judge_id, placings, actual_minutes):
    return api_client.record_class_results(
        class_id,
        create_results_payload(placings, actual_minutes),
        make_judge_headers(judge_id),
    )


def _two_started_slots_with_and_without_a_field():
    """Class 101 running with two confirmed starters; class 102 running with nothing in it."""
    ctx = build_approved_show(class_specs=TWO_JUMPER_CLASSES, ring_specs=[{}])
    class_101, class_102 = ctx["class_ids"]
    ctx["field"] = build_field(ctx["show_id"], [class_101], 2)
    ctx["class_entry_ids"] = [row["class_entry_id"] for row in ctx["field"]]
    ctx.update(build_judge_and_steward())

    ctx["slot_p"] = book_slot(ctx["ring_id"], class_101, "2026-09-10T14:00:00Z")
    ctx["slot_q"] = book_slot(ctx["ring_id"], class_102, "2026-09-10T15:00:00Z")
    card_judge_and_steward(ctx["slot_p"]["id"], ctx["judge_id"], ctx["steward_id"])
    card_judge_and_steward(ctx["slot_q"]["id"], ctx["judge_id"], ctx["steward_id"])

    ctx["coverage_shift"] = build_active_coverage(ctx["show_id"])
    start_slot(ctx["slot_p"]["id"])
    start_slot(ctx["slot_q"]["id"])
    ctx["class_101"], ctx["class_102"] = class_101, class_102
    return ctx


def _empty_class_booked_and_chaired():
    """One 14:00-14:20 occupancy on Ring A with a judge and a steward carded onto it."""
    ctx = build_approved_show(ring_specs=[{}])
    ctx.update(build_judge_and_steward())
    ctx["slot"] = book_slot(ctx["ring_id"], ctx["class_id"], "2026-09-10T14:00:00Z")
    ctx["slot_id"] = ctx["slot"]["id"]
    ctx["assignments"] = card_judge_and_steward(
        ctx["slot_id"], ctx["judge_id"], ctx["steward_id"]
    )
    return ctx


def test_nine_machines_each_report_the_initial_state_their_own_rule_declares():
    """Nine of this system's state machines are created in one pass and every one of them lands on
    the value its own creation rule declares: a fresh show is DRAFT, a fresh ring AVAILABLE, an
    untouched class PLANNED, an entry RECEIVED on the paperwork side and UNBILLED on the money side
    at once, a class entry ENTERED with nothing scored yet, a case OPEN with no finding, a coverage
    window SCHEDULED before its provider arrives, a booked occupancy SCHEDULED, and a carded chair
    ACTIVE.

    PRD §3.1: "At creation the show's `license_status` is `DRAFT`, `revision_count` is 0, `allocated_prize_cents` is 0, `unallocated_prize_cents` equals `prize_money_pool_cents`, `reserved_stall_count` is 0, `available_stall_count` equals `stall_capacity`, `division_share_bp_total` is 0 and `welfare_strike_count` is 0."
    PRD §3.3: "A new ring has `status` of `AVAILABLE`, `scheduled_minutes_total` of 0 and `slot_count` of 0, and its creation increments the parent show's `version`."
    PRD §3.5: "A new entry has `verification_status` of `RECEIVED`, `settlement_status` of `UNBILLED`, `assigned_stall_count` of 0, all five settlement figures — `class_fee_cents_total`, `stall_fee_cents`, `preliminary_subtotal_cents`, `office_fee_cents` and `total_due_cents` — at 0, and `refunded_cents` at 0."
    PRD §3.5: "Its `placing` and `round_seconds` are null, and `prize_cents`, `points_national` and `points_regional` are all 0."
    PRD §3.9: "A new case has `status` of `OPEN` and `finding` of null."
    PRD §3.3: "A new window has `status` of `SCHEDULED`."
    PRD §3.6: "Booking writes an occupancy — a ring slot — whose `slot_type` is `CLASS`, whose `class_id` names the booked class, and whose `status` is `SCHEDULED`."
    PRD §3.6: "A new assignment has `status` of `ACTIVE`, and the official's `assigned_minutes` is increased by the whole minutes from the occupancy's `warmup_start_utc` to its `end_utc`; the official's `version` increments."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    ctx = build_approved_show(class_specs=TWO_JUMPER_CLASSES, open_classes=False)
    class_101, class_102 = ctx["class_ids"]
    assert open_class(class_101)["status"] == "OPEN"

    untouched = get_class(class_102)
    assert untouched["status"] == "PLANNED"
    assert untouched["entry_count"] == 0
    assert untouched["point_eligible"] is False
    assert untouched["actual_minutes"] is None

    second_show = create_show(name="Winter Classic", federation_show_id="FED-2435")
    assert second_show["license_status"] == "DRAFT"
    assert second_show["revision_count"] == 0
    assert second_show["welfare_strike_count"] == 0
    assert second_show["version"] == 1

    ring = create_ring(ctx["show_id"], name="Ring B")
    assert ring["status"] == "AVAILABLE"
    assert ring["scheduled_minutes_total"] == 0
    assert ring["slot_count"] == 0

    rider = create_rider()
    horse = create_horse()
    row = build_entry(
        ctx["show_id"], rider["id"], horse["id"], [class_101], requested_stall_count=2
    )
    entry = row["entry"]
    assert entry["verification_status"] == "RECEIVED"
    assert entry["settlement_status"] == "UNBILLED"
    assert entry["assigned_stall_count"] == 0
    assert entry["requested_stall_count"] == 2
    assert entry["total_due_cents"] == 0
    assert entry["refunded_cents"] == 0

    class_entry = get_class_entry(row["class_entry_id"])
    assert class_entry["status"] == "ENTERED"
    assert class_entry["placing"] is None
    assert class_entry["round_seconds"] is None
    assert class_entry["prize_cents"] == 0
    assert class_entry["points_national"] == 0
    assert class_entry["points_regional"] == 0

    steward = build_steward()
    case = open_compliance_case(
        row["entry_id"],
        steward["steward_id"],
        case_type="WELFARE_CITATION",
        welfare_rule_code="GR-1305",
    )
    assert case["status"] == "OPEN"
    assert case["finding"] is None
    assert case["welfare_rule_code"] == "GR-1305"

    shift = create_coverage_shift(ctx["show_id"])
    assert shift["status"] == "SCHEDULED"
    assert shift["coverage_type"] == "VETERINARIAN"

    slot = book_slot(ring["id"], class_101, "2026-09-10T14:00:00Z")
    assert slot["status"] == "SCHEDULED"
    assert slot["slot_type"] == "CLASS"
    assert slot["class_id"] == class_101

    judge = create_official(license_roles=["JUDGE"], licensed_disciplines=["JUMPER"])
    assignment = card_official(judge["id"], slot["id"], "JUDGE")
    assert assignment["status"] == "ACTIVE"
    assert assignment["official_role"] == "JUDGE"


def test_each_dimension_refuses_the_step_it_is_not_standing_in_front_of():
    """The paperwork and money dimensions each police their own predecessor: acceptance is refused
    while the entry is only RECEIVED and payment while it is only UNBILLED, each with its own code.
    Driven in order the pair advances one step at a time — and a replay of any step that has
    already landed is refused, including the paid entry whose second payment finds the money
    dimension no longer INVOICED. Only when both dimensions have landed does the class entry
    confirm.

    PRD §3.5: "An entry may be invoiced while still `RECEIVED`, and it may be verified while still `UNBILLED`."
    PRD §3.5: "Only an entry in `RECEIVED` may be verified; otherwise `ERR_ENTRY_NOT_RECEIVED`."
    PRD §3.5: "Only an entry in `VERIFIED` may be accepted; otherwise `ERR_ENTRY_NOT_VERIFIED`."
    PRD §3.5: "Freezing the invoice moves `UNBILLED → INVOICED` and writes all five settlement figures; a second attempt is refused with `ERR_ENTRY_ALREADY_INVOICED`, and an attempt on a withdrawn entry is refused with `ERR_ENTRY_ALREADY_TERMINAL`."
    PRD §3.5: "An entry not in `INVOICED` is refused with `ERR_ENTRY_NOT_INVOICED`, and an `amount_cents` that is not exactly equal to `total_due_cents` — short or over — is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD §3.5: "A class entry starts life `ENTERED` and only reaches `CONFIRMED` when *both* entry dimensions have landed: `verification_status` of `ACCEPTED` and `settlement_status` of `PAID`."

    Design: Corner/state_machines/entry_dimension_triggers_out_of_order_rejected
    """
    ctx = build_approved_show()
    rider = create_rider()
    horse = create_horse()
    row = build_entry(ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]])
    entry_id = row["entry_id"]
    exhibitor = make_exhibitor_headers(rider["id"])

    validate_error(
        api_client.accept_entry(entry_id, SECRETARY), "ERR_ENTRY_NOT_VERIFIED", 409
    )
    validate_error(
        api_client.pay_entry(entry_id, {"amount_cents": 30000}, exhibitor),
        "ERR_ENTRY_NOT_INVOICED",
        409,
    )

    verified = validate_success(api_client.verify_entry(entry_id, SECRETARY))
    assert verified["verification_status"] == "VERIFIED"
    assert verified["settlement_status"] == "UNBILLED"
    validate_error(
        api_client.verify_entry(entry_id, SECRETARY), "ERR_ENTRY_NOT_RECEIVED", 409
    )

    invoiced = validate_success(api_client.invoice_entry(entry_id, SECRETARY))
    assert invoiced["settlement_status"] == "INVOICED"
    assert invoiced["verification_status"] == "VERIFIED"
    assert invoiced["class_fee_cents_total"] == 25000
    assert invoiced["stall_fee_cents"] == 0
    assert invoiced["preliminary_subtotal_cents"] == 25000
    assert invoiced["office_fee_cents"] == 5000
    assert invoiced["total_due_cents"] == 30000
    validate_error(
        api_client.invoice_entry(entry_id, SECRETARY), "ERR_ENTRY_ALREADY_INVOICED", 409
    )

    accepted = validate_success(api_client.accept_entry(entry_id, SECRETARY))
    assert accepted["verification_status"] == "ACCEPTED"
    assert get_class_entry(row["class_entry_id"])["status"] == "ENTERED"

    paid = validate_success(
        api_client.pay_entry(entry_id, {"amount_cents": 30000}, exhibitor)
    )
    assert paid["settlement_status"] == "PAID"
    assert get_class_entry(row["class_entry_id"])["status"] == "CONFIRMED"

    validate_error(
        api_client.pay_entry(entry_id, {"amount_cents": 30000}, exhibitor),
        "ERR_ENTRY_NOT_INVOICED",
        409,
    )

    final = get_entry(entry_id)
    assert final["verification_status"] == "ACCEPTED"
    assert final["settlement_status"] == "PAID"


def test_neither_terminal_licence_state_can_be_resubmitted_or_decided_a_second_time():
    """Approval and denial are both ends of the licence cycle, and both close the same two doors:
    a fresh submission is refused as not-DRAFT and a fresh decision as not-SUBMITTED. The denied
    show is additionally locked for structure — a late division is refused — and its prize list has
    already been closed out by the denial, so its class is VOIDED and its division CLOSED. Opening
    that voided class reports the class's own state rather than the licence, because a resource's
    own state precondition is evaluated before the licence gate.

    PRD §3.1: "`APPROVED` and `DENIED` are terminal licence states."
    PRD §3.1: "`license_status` moves `DRAFT → SUBMITTED` when the secretary submits the prize list to the federation, and submission is only accepted from `DRAFT` or from `RETURNED_FOR_CORRECTION`; attempting it from `SUBMITTED`, `APPROVED` or `DENIED` yields `ERR_SHOW_LICENSE_NOT_DRAFT`."
    PRD §3.1: "All three require the show to be in `SUBMITTED`; from any other licence state the decision is refused with `ERR_SHOW_LICENSE_NOT_SUBMITTED`."
    PRD §3.1: "Denial — whether explicit or escalated — closes the prize list: every `CompetitionDivision` of the show whose `status` is `ACTIVE` becomes `CLOSED`, and every class beneath those divisions whose `status` is `PLANNED` becomes `VOIDED`."
    PRD §3.1: "Divisions and classes may only be created while the show's `license_status` is `DRAFT` or `RETURNED_FOR_CORRECTION`; once the licence is `SUBMITTED`, `APPROVED` or `DENIED`, a creation attempt is refused with `ERR_SHOW_LICENSE_LOCKED`."
    PRD §3.2: "Only a class in `PLANNED` may be opened — otherwise `ERR_CLASS_NOT_PLANNED` — the owning show's licence must be `APPROVED`, and the owning division's `status` must be `ACTIVE`."
    PRD §2.12: "The target resource's own state precondition — the 409 state codes."

    Design: Corner/state_machines/approved_and_denied_licenses_are_terminal
    """
    approved_ctx = build_approved_show(open_classes=False)
    denied_ctx = build_show_with_class_list(
        show_overrides={"name": "Winter Classic", "federation_show_id": "FED-2435"},
        class_specs=[
            {
                "class_number": 201,
                "name": "Junior Jumper 1.00m",
                "jump_height_cm": 100,
                "class_share_bp": 1000,
            }
        ],
    )
    submit_license(denied_ctx["show_id"])
    denied = decide_license(
        denied_ctx["show_id"], "DENY", correction_note="Veterinary plan not filed."
    )
    assert denied["license_status"] == "DENIED"

    for show_id in (approved_ctx["show_id"], denied_ctx["show_id"]):
        validate_error(
            api_client.submit_show_license(show_id, SECRETARY),
            "ERR_SHOW_LICENSE_NOT_DRAFT",
            409,
        )
        validate_error(
            api_client.decide_show_license(show_id, {"decision": "APPROVE"}, OFFICER),
            "ERR_SHOW_LICENSE_NOT_SUBMITTED",
            409,
        )

    validate_error(
        api_client.create_division(
            denied_ctx["show_id"], create_division_payload(name="Late Hunter"), SECRETARY
        ),
        "ERR_SHOW_LICENSE_LOCKED",
        409,
    )
    validate_error(
        api_client.open_class(denied_ctx["class_id"], SECRETARY),
        "ERR_CLASS_NOT_PLANNED",
        409,
    )

    still_approved = get_show(approved_ctx["show_id"])
    assert still_approved["license_status"] == "APPROVED"
    assert still_approved["revision_count"] == 0

    assert get_class(denied_ctx["class_id"])["status"] == "VOIDED"
    rows, meta = validate_paginated(
        api_client.list_show_divisions(denied_ctx["show_id"], SECRETARY)
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "CLOSED"


def test_a_replayed_check_in_and_a_replayed_adjudication_change_nothing():
    """Two independent machines have each fired once — a coverage window checked in, a drug test
    dismissed — and each refuses to fire again with its own code. The refusal is total: the
    dismissed case keeps the version it had when it was dismissed, so the rejected attempts wrote
    nothing at all, and the POSITIVE verdict that would have suspended the horse and disqualified
    its ride is refused on the same terminal-state grounds rather than being applied.

    PRD §3.3: "Activation is only permitted from `SCHEDULED`; a second activation is refused with `ERR_COVERAGE_SHIFT_NOT_SCHEDULED`."
    PRD §3.9: "Only a case in `OPEN` may be adjudicated; otherwise `ERR_CASE_ALREADY_ADJUDICATED`."
    PRD §3.9: "`SUBSTANTIATED` and `DISMISSED` are terminal case states."
    PRD §3.9: "A `NEGATIVE` finding moves the case `OPEN → DISMISSED`, records `finding` as `NEGATIVE`, and does nothing else beyond incrementing the case's `version`."
    PRD §3.4: "The only other eligibility value is `SUSPENDED`, reached only by a substantiated positive compliance finding."

    Design: Corner/state_machines/replayed_final_triggers_rejected_without_side_effects
    """
    ctx = build_approved_show()
    rider = create_rider()
    horse = create_horse()
    row = build_confirmed_entry(
        ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]]
    )
    steward = build_steward()
    case = open_compliance_case(
        row["entry_id"], steward["steward_id"], case_type="DRUG_TEST", sample_code="S-4477"
    )
    shift = create_coverage_shift(ctx["show_id"])

    set_clock(COMPETITION_DAY_CLOCK)
    assert activate_coverage_shift(shift["id"])["status"] == "ACTIVE"

    dismissed = record_finding(case["id"], "NEGATIVE")
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["finding"] == "NEGATIVE"
    settled_version = dismissed["version"]

    validate_error(
        api_client.activate_coverage_shift(shift["id"], GROUNDS),
        "ERR_COVERAGE_SHIFT_NOT_SCHEDULED",
        409,
    )
    validate_error(
        api_client.record_case_finding(case["id"], {"finding": "NEGATIVE"}, OFFICER),
        "ERR_CASE_ALREADY_ADJUDICATED",
        409,
    )
    validate_error(
        api_client.record_case_finding(case["id"], {"finding": "POSITIVE"}, OFFICER),
        "ERR_CASE_ALREADY_ADJUDICATED",
        409,
    )

    replayed_case = validate_success(api_client.get_compliance_case(case["id"], SECRETARY))
    assert replayed_case["status"] == "DISMISSED"
    assert replayed_case["finding"] == "NEGATIVE"
    assert replayed_case["version"] == settled_version

    shifts, _meta = validate_paginated(
        api_client.list_show_coverage_shifts(ctx["show_id"], SECRETARY)
    )
    assert [s["status"] for s in shifts if s["id"] == shift["id"]] == ["ACTIVE"]

    assert validate_success(api_client.get_horse(horse["id"], OFFICER))["eligibility_status"] == "ELIGIBLE"
    assert get_class_entry(row["class_entry_id"])["status"] == "CONFIRMED"
    assert get_show(ctx["show_id"])["welfare_strike_count"] == 0


def test_the_judges_card_has_four_independent_gates_each_with_its_own_answer():
    """A gap in the placings and a row placed twice are both malformed cards; an unknown class
    entry is a resolution failure long before the placings are inspected; and a class with an empty
    field cannot be carded at all, so the empty card is refused as having nothing to judge rather
    than accepted as a blank result. The well-formed card then lands, completing both starters and
    closing only its own occupancy — the second ring booking is still RUNNING — and the card cannot
    be replayed against a class that has left IN_PROGRESS.

    PRD §3.7: "A `Judge` records results for a class in `IN_PROGRESS`; any other class status is `ERR_CLASS_NOT_IN_PROGRESS`."
    PRD §3.7: "The class's `entry_count` must be at least 1; a class with nothing in it is `ERR_NO_ENTRIES_TO_JUDGE`."
    PRD §3.7: "And the placings themselves must be well-formed: the positions supplied must be distinct integers forming a contiguous run starting at 1, the number of positions may not exceed the smaller of 5 and the count of this class's class entries whose `status` is `CONFIRMED`, and every class entry named in the card must belong to this class and be `CONFIRMED`."
    PRD §2.8: "The same catalogue serves references supplied inside a request body rather than in the path."
    PRD §3.7: "The class moves `IN_PROGRESS → JUDGED` with `actual_minutes` written from the card and `placed_count` recomputed as the number of its class entries that have a non-null `placing` and a `status` of `COMPLETED`."
    PRD §3.7: "The class's `RUNNING` occupancy moves `RUNNING → COMPLETED`, and the ring's `scheduled_minutes_total` is recomputed."

    Design: Corner/state_machines/results_card_preconditions_and_placings_rejected
    """
    ctx = _two_started_slots_with_and_without_a_field()
    first, second = ctx["class_entry_ids"]
    judge_id = ctx["judge_id"]

    assert ctx["slot_p"]["duration_minutes"] == 25
    assert ctx["slot_q"]["duration_minutes"] == 20

    validate_error(
        _card(
            ctx["class_101"],
            judge_id,
            [placing_row(first, 1, 62.5), placing_row(second, 3, 64.0)],
            24,
        ),
        "ERR_INVALID_PLACINGS",
        422,
    )
    validate_error(
        _card(
            ctx["class_101"],
            judge_id,
            [placing_row(first, 1, 62.5), placing_row(first, 2, 62.5)],
            24,
        ),
        "ERR_INVALID_PLACINGS",
        422,
    )
    validate_error(
        _card(
            ctx["class_101"],
            judge_id,
            [placing_row(first, 1, 62.5), placing_row(MISSING_UUID, 2, 64.0)],
            24,
        ),
        "ERR_CLASS_ENTRY_NOT_FOUND",
        404,
    )
    validate_error(
        _card(ctx["class_102"], judge_id, [], 20), "ERR_NO_ENTRIES_TO_JUDGE", 409
    )

    judged = validate_success(
        _card(
            ctx["class_101"],
            judge_id,
            [placing_row(first, 1, 62.5), placing_row(second, 2, 64.0)],
            24,
        )
    )
    assert judged["status"] == "JUDGED"
    assert judged["placed_count"] == 2
    assert judged["actual_minutes"] == 24

    winner = get_class_entry(first)
    runner_up = get_class_entry(second)
    assert winner["status"] == "COMPLETED"
    assert winner["placing"] == 1
    assert winner["prize_cents"] == 0
    assert runner_up["status"] == "COMPLETED"
    assert runner_up["placing"] == 2
    assert runner_up["prize_cents"] == 0

    assert get_slot(ctx["slot_p"]["id"])["status"] == "COMPLETED"
    assert get_slot(ctx["slot_q"]["id"])["status"] == "RUNNING"

    validate_error(
        _card(
            ctx["class_101"],
            judge_id,
            [placing_row(first, 1, 62.5), placing_row(second, 2, 64.0)],
            24,
        ),
        "ERR_CLASS_NOT_IN_PROGRESS",
        409,
    )
    assert get_class(ctx["class_101"])["placed_count"] == 2

    ring = get_ring(ctx["ring_id"])
    assert ring["slot_count"] == 2
    assert ring["scheduled_minutes_total"] == 45


def test_a_dismissal_fires_no_consequence_and_a_warning_belongs_to_the_other_case_type():
    """Opening a drug test without its barcode is a shape violation and leaves no case behind. The
    case that is properly opened then meets a verdict-typed refusal — a warning is a welfare
    verdict and is not applicable to a drug test — and the case survives that refusal still OPEN.
    The NEGATIVE verdict that follows dismisses it and fires nothing else: the horse stays
    eligible, its ride stays confirmed, and the show's strike counter never moves.

    PRD §3.9: "A drug test carries the laboratory barcode in `sample_code` and must not carry a `welfare_rule_code`; a welfare citation carries the federation rule cited in `welfare_rule_code` and must not carry a `sample_code`."
    PRD §3.9: "Supplying the wrong one, or omitting the required one, is `ERR_INVALID_REQUEST`."
    PRD §3.9: "A `WARNING` finding moves the case `OPEN → SUBSTANTIATED`, records `finding` as `WARNING`, and is only permitted when the case's `case_type` is `WELFARE_CITATION`; a warning on a drug test is refused with `ERR_FINDING_NOT_APPLICABLE`."
    PRD §3.9: "A `NEGATIVE` finding moves the case `OPEN → DISMISSED`, records `finding` as `NEGATIVE`, and does nothing else beyond incrementing the case's `version`."
    PRD §3.4: "The only other eligibility value is `SUSPENDED`, reached only by a substantiated positive compliance finding."

    Design: Corner/state_machines/negative_finding_dismisses_case_without_side_effects
    """
    ctx = build_approved_show()
    rider = create_rider()
    horse = create_horse()
    row = build_confirmed_entry(
        ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]]
    )
    steward = build_steward()

    validate_error(
        api_client.create_compliance_case(
            row["entry_id"],
            {"opened_by_official_id": steward["steward_id"], "case_type": "DRUG_TEST"},
            steward["steward_headers"],
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    _rows, empty_meta = validate_paginated(
        api_client.list_compliance_cases(SECRETARY, params={"entry_id": row["entry_id"]})
    )
    assert empty_meta["total_count"] == 0

    case = validate_success(
        api_client.create_compliance_case(
            row["entry_id"],
            create_compliance_case_payload(
                steward["steward_id"], "DRUG_TEST", sample_code="S-4477"
            ),
            steward["steward_headers"],
        ),
        201,
    )
    assert case["status"] == "OPEN"
    assert case["finding"] is None
    assert case["sample_code"] == "S-4477"

    validate_error(
        api_client.record_case_finding(case["id"], {"finding": "WARNING"}, OFFICER),
        "ERR_FINDING_NOT_APPLICABLE",
        422,
    )
    assert validate_success(api_client.get_compliance_case(case["id"], SECRETARY))["status"] == "OPEN"

    dismissed = validate_success(
        api_client.record_case_finding(case["id"], {"finding": "NEGATIVE"}, OFFICER)
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["finding"] == "NEGATIVE"

    assert validate_success(api_client.get_horse(horse["id"], OFFICER))["eligibility_status"] == "ELIGIBLE"
    assert get_class_entry(row["class_entry_id"])["status"] == "CONFIRMED"
    assert get_show(ctx["show_id"])["welfare_strike_count"] == 0

    _cases, meta = validate_paginated(
        api_client.list_compliance_cases(SECRETARY, params={"entry_id": row["entry_id"]})
    )
    assert meta["total_count"] == 1


def test_a_pass_landing_exactly_on_sixty_adds_a_hold_without_unwinding_anything():
    """Sixty is not below sixty, so the hold branch is not taken: the ring stays AVAILABLE, the
    booked class keeps its occupancy and its two chairs keep their fifty minutes each. What the
    pass does do is add its own maintenance occupancy — a class-less 60-minute window that sorts
    second behind the 14:00 class — and rewrite the surface score. Because this branch does check
    for collisions, a hold requested inside the class window is refused, and a hold requested
    beyond the show's last day is refused on containment; neither refusal touches the surface score
    or the occupancy count.

    PRD §3.3: "What differs is the posture the ring lands in, and the threshold is a footing score of 60."
    PRD §3.3: "A pass that leaves the surface at 60 or above from an `AVAILABLE` ring leaves the ring `AVAILABLE` — a same-state transition — and the requested hold window is checked against the ring's existing occupancies under the overlap geometry of §3.5; a collision is `ERR_RING_SLOT_OVERLAP`."
    PRD §3.3: "The hold window must lie inside the show's competition window; a window not fully contained between `start_utc` and `end_utc` of the show is refused with `ERR_SLOT_OUTSIDE_SHOW_WINDOW`."
    PRD §3.6: "Maintenance occupancies synthesised by footing work carry `slot_type` of `MAINTENANCE`, a null `class_id`, and a `duration_minutes` equal to the requested hold length; a class occupancy always has a non-null `class_id`."
    PRD §3.3: "Every footing pass, whatever the resulting score, does three things: it synthesises a maintenance occupancy on the ring for the requested window with the requested length, it rewrites `footing_condition_score` to `new_footing_condition_score`, and it recomputes the ring's `scheduled_minutes_total`, `slot_count` and the `order_index` of every occupancy on the ring, incrementing the ring's `version`."

    Design: Corner/state_machines/footing_pass_at_threshold_leaves_schedule_intact
    """
    ctx = _empty_class_booked_and_chaired()
    assert ctx["slot"]["duration_minutes"] == 20
    assert ctx["slot"]["end_utc"] == "2026-09-10T14:20:00Z"

    at_threshold = record_footing_maintenance(
        ctx["ring_id"],
        start_utc="2026-09-10T18:00:00Z",
        duration_minutes=60,
        new_footing_condition_score=60,
    )
    assert at_threshold["status"] == "AVAILABLE"
    assert at_threshold["footing_condition_score"] == 60

    assert get_slot(ctx["slot_id"])["status"] == "SCHEDULED"
    assert get_class(ctx["class_id"])["status"] == "SCHEDULED"

    for key in ("judge_assignment", "steward_assignment"):
        assignment = validate_success(
            api_client.get_official_assignment(ctx["assignments"][key]["id"], SECRETARY)
        )
        assert assignment["status"] == "ACTIVE"
    assert validate_success(api_client.get_official(ctx["judge_id"], SECRETARY))["assigned_minutes"] == 50
    assert validate_success(api_client.get_official(ctx["steward_id"], SECRETARY))["assigned_minutes"] == 50

    holds, holds_meta = validate_paginated(
        api_client.list_ring_slots(
            RING_MASTER, params={"ring_id": ctx["ring_id"], "slot_type": "MAINTENANCE"}
        )
    )
    assert holds_meta["total_count"] == 1
    assert holds[0]["duration_minutes"] == 60
    assert holds[0]["start_utc"] == "2026-09-10T18:00:00Z"
    assert holds[0]["class_id"] is None
    assert holds[0]["order_index"] == 2

    ring = get_ring(ctx["ring_id"])
    assert ring["slot_count"] == 2
    assert ring["scheduled_minutes_total"] == 80

    validate_error(
        api_client.record_footing_maintenance(
            ctx["ring_id"],
            {
                "start_utc": "2026-09-10T14:05:00Z",
                "duration_minutes": 30,
                "new_footing_condition_score": 70,
            },
            GROUNDS,
        ),
        "ERR_RING_SLOT_OVERLAP",
        409,
    )
    validate_error(
        api_client.record_footing_maintenance(
            ctx["ring_id"],
            {
                "start_utc": "2026-09-14T09:00:00Z",
                "duration_minutes": 30,
                "new_footing_condition_score": 70,
            },
            GROUNDS,
        ),
        "ERR_SLOT_OUTSIDE_SHOW_WINDOW",
        409,
    )

    unchanged = get_ring(ctx["ring_id"])
    assert unchanged["footing_condition_score"] == 60
    assert unchanged["slot_count"] == 2


def test_the_regional_leg_credits_alone_and_the_national_leg_joins_the_fork_at_recorded():
    """The regional acknowledgement credits 8, 5 and 3 to the three ribbons and 16 to the
    submission, while every national figure — the submission's total, its reference and each row's
    points — stays exactly where the raising left it. The rider's own standings read agrees: eight
    regional points and no scoring class nationally. The national leg then lands with the same side
    effects it would have had first, joining the fork at RECORDED with 20.0 national points on a
    three-starter multiplier of 1.0, and a third acknowledgement finds the submission finalised.

    PRD §3.8: "The two legs are independent forks that join at `RECORDED`."
    PRD §3.8: "From `PREPARED`, a national acceptance moves the submission `PREPARED → NATIONAL_ACCEPTED` and a regional acceptance moves it `PREPARED → REGIONAL_ACCEPTED`."
    PRD §3.8: "From `NATIONAL_ACCEPTED`, a regional acceptance moves it `NATIONAL_ACCEPTED → RECORDED`; from `REGIONAL_ACCEPTED`, a national acceptance moves it `REGIONAL_ACCEPTED → RECORDED`."
    PRD §3.8: "An accepted **regional** leg writes `points_regional` on the same population, sets the submission's `regional_points_total` to the sum of those values, stores the supplied `body_reference` as `regional_body_reference`, and adds each placed class entry's `points_regional` to its rider's `regional_points_total`."
    PRD §3.8: "That whole table is then scaled by a multiplier chosen from the class's `confirmed_entry_count`: when it is at least 25 the multiplier is 2.0; otherwise when it is at least 10 the multiplier is 1.5; otherwise when it is at least 3 the multiplier is 1.0; and below 3 the multiplier is 0.0."
    PRD §3.8: "Any acknowledgement attempted against a submission already `RECORDED`, `REJECTED` or `RETRACTED` is refused with `ERR_SUBMISSION_ALREADY_FINALIZED`."

    Design: Corner/state_machines/point_submission_legs_fork_and_join_at_recorded
    """
    ctx = build_point_submission(entry_count=3, actual_minutes=25)
    submission_id = ctx["submission_id"]
    first, second, third = ctx["class_entry_ids"]
    rider_id = ctx["field"][0]["rider_id"]

    regional = validate_success(
        api_client.acknowledge_point_submission(
            submission_id,
            acknowledgement_payload("REGIONAL", "ACCEPTED", "REG-SE-0091"),
            OFFICER,
        )
    )
    assert regional["status"] == "REGIONAL_ACCEPTED"
    assert regional["regional_body_reference"] == "REG-SE-0091"
    assert regional["regional_points_total"] == 16
    assert regional["national_points_total"] == 0
    assert regional["national_body_reference"] is None

    assert [get_class_entry(ce)["points_regional"] for ce in (first, second, third)] == [8, 5, 3]
    assert [get_class_entry(ce)["points_national"] for ce in (first, second, third)] == [0, 0, 0]

    standings = validate_success(
        api_client.get_rider_standings(rider_id, SECRETARY, params={"show_id": ctx["show_id"]})
    )
    assert standings["regional_points_total"] == 8
    assert standings["national_points_total"] == 0
    assert standings["national_class_count"] == 0
    assert standings["regional_capped"] is False

    recorded = validate_success(
        api_client.acknowledge_point_submission(
            submission_id,
            acknowledgement_payload("NATIONAL", "ACCEPTED", "NAT-2026-00417"),
            OFFICER,
        )
    )
    assert recorded["status"] == "RECORDED"
    assert recorded["national_points_total"] == 20.0
    assert recorded["regional_points_total"] == 16
    assert recorded["national_body_reference"] == "NAT-2026-00417"

    assert [get_class_entry(ce)["points_national"] for ce in (first, second, third)] == [10.0, 6.0, 4.0]
    assert get_class(ctx["class_id"])["status"] == "POINTS_SUBMITTED"

    validate_error(
        api_client.acknowledge_point_submission(
            submission_id,
            acknowledgement_payload("NATIONAL", "ACCEPTED", "NAT-2026-00418"),
            OFFICER,
        ),
        "ERR_SUBMISSION_ALREADY_FINALIZED",
        409,
    )

    final = validate_success(
        api_client.get_rider_standings(rider_id, SECRETARY, params={"show_id": ctx["show_id"]})
    )
    assert final["national_points_total"] == 10.0
    assert final["regional_points_total"] == 8


def test_a_rejection_on_the_second_leg_unwinds_the_credit_the_first_leg_gave():
    """The rejection arrives on the national leg but has to compensate the regional one: the 16
    points already credited come off the submission, off all three rows and off the rider's own
    total. The class falls back to RESULTS_POSTED, which is what lets a corrected submission be
    raised against it, and the class's version advances exactly once for the rejection. The purse
    is untouched throughout — posting wrote 33793 cents and the standings workflow never had any
    business with it.

    PRD §3.8: "A `REJECTED` outcome may arrive while the submission is `PREPARED`, `NATIONAL_ACCEPTED` or `REGIONAL_ACCEPTED`, and it moves the submission to `REJECTED` from any of the three."
    PRD §3.8: "It compensates whatever had already been credited: for each leg already accepted, the credited `points_national` or `points_regional` figures are subtracted from the corresponding rider totals and those class-entry fields are reset to 0."
    PRD §3.8: "The submission's own `national_points_total` and `regional_points_total` both become 0."
    PRD §3.8: "The class then reverts `POINTS_SUBMITTED → RESULTS_POSTED`, which is what allows a corrected submission to be raised against it."
    PRD §3.8: "The submission's and the class's `version` both increment."

    Design: Corner/state_machines/point_submission_rejection_reverses_credited_leg
    """
    ctx = build_point_submission(entry_count=3, actual_minutes=25)
    submission_id = ctx["submission_id"]
    first, second, third = ctx["class_entry_ids"]
    rider_id = ctx["field"][0]["rider_id"]

    credited = validate_success(
        api_client.acknowledge_point_submission(
            submission_id,
            acknowledgement_payload("REGIONAL", "ACCEPTED", "REG-SE-0091"),
            OFFICER,
        )
    )
    assert credited["regional_points_total"] == 16
    version_before_rejection = class_version(ctx["class_id"])

    rejected = validate_success(
        api_client.acknowledge_point_submission(
            submission_id, acknowledgement_payload("NATIONAL", "REJECTED"), OFFICER
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["regional_points_total"] == 0
    assert rejected["national_points_total"] == 0

    assert [get_class_entry(ce)["points_regional"] for ce in (first, second, third)] == [0, 0, 0]
    assert [get_class_entry(ce)["points_national"] for ce in (first, second, third)] == [0, 0, 0]

    standings = validate_success(
        api_client.get_rider_standings(rider_id, SECRETARY, params={"show_id": ctx["show_id"]})
    )
    assert standings["regional_points_total"] == 0
    assert standings["national_points_total"] == 0
    assert standings["national_class_count"] == 0
    assert standings["regional_capped"] is False

    reverted = get_class(ctx["class_id"])
    assert reverted["status"] == "RESULTS_POSTED"
    assert reverted["version"] == version_before_rejection + 1
    assert reverted["awarded_prize_cents"] == 33793
    assert [get_class_entry(ce)["prize_cents"] for ce in (first, second, third)] == [16688, 10430, 6675]
    assert get_show(ctx["show_id"])["allocated_prize_cents"] == 33793

    corrected = validate_success(
        api_client.create_point_submission(
            ctx["class_id"], {"expected_class_version": reverted["version"]}, SECRETARY
        ),
        201,
    )
    assert corrected["status"] == "PREPARED"

    _rows, meta = validate_paginated(
        api_client.list_class_point_submissions(ctx["class_id"], SECRETARY)
    )
    assert meta["total_count"] == 2
