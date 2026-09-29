"""Check-in, the four-rung screening ladder at the scale, business referral and
the two quota ledgers."""

from test_helpers import (
    EXPLOSIVE,
    SOLVENT,
    TECH,
    ApiErrorId,
    assert_dropoff_line,
    assert_kg,
    create_category,
    create_dropoff_line_payload,
    read_appointment,
    read_dropoff_line,
    read_event,
    read_program,
    read_resident,
    record_line,
    setup_canon,
    validate_error,
    validate_success,
)


def test_checking_a_vehicle_in_twice_is_refused(api):
    """PRD §3.7: "Checking a vehicle in moves `CONFIRMED → CHECKED_IN`, requires
    that the event is `IN_PROGRESS` and its containment axis reads `COMPLIANT` or
    `REMEDIATED`, and stamps `check_in_utc` with the current logical-clock instant."
    PRD §2.5: "The requested action is a declared transition out of the target row's
    current state on the relevant axis — otherwise `ERR_INVALID_STATE_TRANSITION`
    (HTTP 409)."

    Design: Corner/state_machines/check_in_twice_returns_invalid_state
    """
    ctx = setup_canon(17, appointment={"declared_total_kg": 11.0})
    assert ctx["appointment"]["status"] == "CHECKED_IN"
    assert ctx["appointment"]["check_in_utc"] == "2026-09-12T09:00:00.000Z"

    response = api.appointment_transition(
        ctx["appointment_id"], {"action": "CHECK_IN"}, TECH
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    after = read_appointment(ctx["appointment_id"])
    assert after["status"] == "CHECKED_IN"
    assert after["check_in_utc"] == "2026-09-12T09:00:00.000Z"


def test_prohibited_material_is_recorded_as_a_rejected_line_not_an_error(api):
    """PRD §3.7: "Rung one asks whether the material is prohibited outright: if the
    named category's `acceptance_policy` is `REJECTED_ALWAYS`, the `disposition` is
    `REJECTED_PROHIBITED` and the `rejection_reason_code` is `PROHIBITED_MATERIAL`."
    PRD §3.7: "A rejected line is still a real, recorded line: the request succeeds
    with HTTP 201 and returns the resolved `disposition`, because rejected material
    was physically weighed at the gate and must be counted in the event's
    `rejected_tonnage_kg`."

    Design: Corner/calculations/prohibited_material_line_is_recorded_as_rejected_not_errored
    """
    ctx = setup_canon(18, appointment={"declared_total_kg": 10.0})
    explosives = create_category(ctx["program_id"], EXPLOSIVE)

    response = api.create_dropoff_line(
        create_dropoff_line_payload(
            ctx["appointment_id"], explosives["id"], 0.4, declared_kg=0.5
        ),
        TECH,
    )
    line = validate_success(response, 201)

    assert_dropoff_line(line)
    assert line["disposition"] == "REJECTED_PROHIBITED"
    assert line["rejection_reason_code"] == "PROHIBITED_MATERIAL"
    assert line["estimated_disposal_cost_cents"] == 0
    assert read_dropoff_line(line["id"])["container_id"] is None

    event = read_event(ctx["event_id"])
    assert_kg(event["rejected_tonnage_kg"], 0.4, "rejected_tonnage_kg")
    assert_kg(event["accepted_tonnage_kg"], 0.0, "accepted_tonnage_kg")
    assert_kg(
        read_resident(ctx["resident_id"])["annual_quantity_settled_kg"],
        0.0,
        "annual_quantity_settled_kg",
    )


def test_annual_ceiling_is_reported_ahead_of_the_event_ceiling(api):
    """PRD §3.7: "Rung two asks whether the resident has exhausted their year. The
    system totals the `net_weight_kg` of every previously accepted line for the
    **same** material category belonging to any appointment of the **same** resident,
    across every event of the program, excluding the line now being recorded; if that
    running total plus the new `net_weight_kg` is strictly greater than the category's
    `max_kg_per_resident_per_year`, the `disposition` is
    `REJECTED_OVER_ANNUAL_LIMIT` and the `rejection_reason_code` is `ANNUAL_LIMIT`."
    PRD §3.7: "And the annual rung sits above the event rung on purpose: a line that
    breaches both ceilings at once reports `REJECTED_OVER_ANNUAL_LIMIT`, never
    `REJECTED_OVER_EVENT_LIMIT`."

    Design: Corner/calculations/annual_limit_rung_precedes_event_limit_rung
    """
    ctx = setup_canon(
        18,
        category=dict(SOLVENT, max_kg_per_resident_per_year=30.0),
        appointment={"declared_total_kg": 35.0},
    )

    first = record_line(ctx["appointment_id"], ctx["category_id"], 20.0)
    assert first["disposition"] == "ACCEPTED"
    assert first["estimated_disposal_cost_cents"] == 6200

    response = api.create_dropoff_line(
        create_dropoff_line_payload(ctx["appointment_id"], ctx["category_id"], 12.0), TECH
    )
    second = validate_success(response, 201)

    assert second["disposition"] == "REJECTED_OVER_ANNUAL_LIMIT", (
        "20.0 + 12.0 breaches the 30.0 annual ceiling before the 25.0 event ceiling"
    )
    assert second["rejection_reason_code"] == "ANNUAL_LIMIT"
    assert second["estimated_disposal_cost_cents"] == 0

    assert_kg(read_appointment(ctx["appointment_id"])["settled_kg"], 20.0, "settled_kg")
    assert_kg(
        read_resident(ctx["resident_id"])["annual_quantity_settled_kg"],
        20.0,
        "annual_quantity_settled_kg",
    )
    assert_kg(read_event(ctx["event_id"])["rejected_tonnage_kg"], 12.0, "rejected_tonnage_kg")


def test_cumulative_mass_landing_exactly_on_the_event_ceiling_is_accepted(api):
    """PRD §3.7: "Rung three asks the same question about the day. The system totals
    the `net_weight_kg` of every previously accepted line for the same material
    category belonging to the **same appointment**, excluding the line being recorded;
    if that total plus the new `net_weight_kg` is strictly greater than the category's
    `max_kg_per_resident_per_event`, the `disposition` is `REJECTED_OVER_EVENT_LIMIT`
    and the `rejection_reason_code` is `EVENT_LIMIT`."
    PRD §3.7: "Both limit comparisons breach only on a **strict** excess, so a
    cumulative total that lands exactly on a ceiling is accepted, not rejected."

    Design: Difficulty/boundary_precision_check/per_event_quantity_limit_strict_greater_than_boundary
    """
    ctx = setup_canon(18, category=SOLVENT, appointment={"declared_total_kg": 30.0})

    response = api.create_dropoff_line(
        create_dropoff_line_payload(
            ctx["appointment_id"], ctx["category_id"], 25.0, declared_kg=25.0
        ),
        TECH,
    )
    line = validate_success(response, 201)

    assert line["disposition"] == "ACCEPTED", "25.000 is not strictly greater than 25.0"
    assert line["rejection_reason_code"] is None
    assert line["estimated_disposal_cost_cents"] == 7750


def test_one_gram_past_the_event_ceiling_is_rejected_over_the_event_limit(api):
    """PRD §3.7: "Rung three asks the same question about the day. The system totals
    the `net_weight_kg` of every previously accepted line for the same material
    category belonging to the **same appointment**, excluding the line being recorded;
    if that total plus the new `net_weight_kg` is strictly greater than the category's
    `max_kg_per_resident_per_event`, the `disposition` is `REJECTED_OVER_EVENT_LIMIT`
    and the `rejection_reason_code` is `EVENT_LIMIT`."
    PRD §3.7: "A line's `estimated_disposal_cost_cents` is its `net_weight_kg`
    multiplied by the category's `disposal_rate_cents_per_kg`, rounded half up to
    whole cents, when the disposition is `ACCEPTED`, and zero in every other case."

    Design: Difficulty/boundary_precision_check/per_event_quantity_limit_strict_greater_than_boundary
    """
    ctx = setup_canon(18, category=SOLVENT, appointment={"declared_total_kg": 30.0})
    record_line(ctx["appointment_id"], ctx["category_id"], 25.0, declared_kg=25.0)

    response = api.create_dropoff_line(
        create_dropoff_line_payload(
            ctx["appointment_id"], ctx["category_id"], 0.001, declared_kg=0.001
        ),
        TECH,
    )
    over = validate_success(response, 201)

    assert over["disposition"] == "REJECTED_OVER_EVENT_LIMIT", "25.000 + 0.001 > 25.0"
    assert over["rejection_reason_code"] == "EVENT_LIMIT"
    assert over["estimated_disposal_cost_cents"] == 0

    assert_kg(read_appointment(ctx["appointment_id"])["settled_kg"], 25.0, "settled_kg")
    event = read_event(ctx["event_id"])
    assert_kg(event["accepted_tonnage_kg"], 25.0, "accepted_tonnage_kg")
    assert_kg(event["rejected_tonnage_kg"], 0.001, "rejected_tonnage_kg")
    assert_kg(
        read_resident(ctx["resident_id"])["annual_quantity_settled_kg"],
        25.0,
        "annual_quantity_settled_kg",
    )


def test_declared_and_weighed_ledgers_disagree_while_the_visit_is_open(api):
    """PRD §3.5: "`annual_quantity_reserved_kg` is the **declared** ledger: it is
    the sum of `declared_total_kg` across the resident's appointments whose status is
    `CONFIRMED`, `CHECKED_IN` or `UNLOADING`, rounded half up to three decimal
    places."
    PRD §3.5: "`annual_quantity_settled_kg` is the **weighed** ledger: it is the sum
    of `net_weight_kg` across every dropoff line belonging to any of the resident's
    appointments whose `disposition` resolved to `ACCEPTED`, rounded half up to three
    decimal places."

    Design: Difficulty/dual_variant_calc/resident_reserved_versus_settled_quota_divergence
    """
    ctx = setup_canon(21)

    resident = read_resident(ctx["resident_id"])
    assert_kg(resident["annual_quantity_reserved_kg"], 18.5, "annual_quantity_reserved_kg")
    assert_kg(resident["annual_quantity_settled_kg"], 4.5, "annual_quantity_settled_kg")
    assert resident["annual_quantity_reserved_kg"] != resident["annual_quantity_settled_kg"], (
        "The declared ledger holds the whole promise; the weighed ledger holds the scale"
    )


def test_completing_the_visit_empties_the_declared_ledger_only(api):
    """PRD §3.7: "On completion `unload_complete_utc` is stamped with the current
    logical-clock instant, `reserved_kg` falls to zero, the resident's
    `annual_quantity_reserved_kg` falls by `declared_total_kg` while their
    `annual_quantity_settled_kg` and `completed_visit_count` are recomputed, the
    event's `reserved_slot_count` falls by one while its `participant_count` — the
    number of that event's appointments sitting in `COMPLETED` — rises by one and its
    `accepted_tonnage_kg` and `rejected_tonnage_kg` are recomputed, and the program's
    `participant_count_ytd` is recomputed."
    PRD §3.5: "A resident who declared 18.5 kg and had 4.5 kg accepted therefore
    reserved 18.5 and settled 4.5, and completing the appointment moves mass out of the
    reserved ledger without moving the same quantity into the settled one."

    Design: Difficulty/dual_variant_calc/resident_reserved_versus_settled_quota_divergence
    """
    ctx = setup_canon(21)

    completed = validate_success(
        api.appointment_transition(
            ctx["appointment_id"], {"action": "COMPLETE_UNLOAD"}, TECH
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert_kg(completed["settled_kg"], 4.5, "settled_kg")
    assert_kg(completed["reserved_kg"], 0.0, "reserved_kg")

    resident = read_resident(ctx["resident_id"])
    assert_kg(resident["annual_quantity_reserved_kg"], 0.0, "annual_quantity_reserved_kg")
    assert_kg(resident["annual_quantity_settled_kg"], 4.5, "annual_quantity_settled_kg")
    assert resident["completed_visit_count"] == 1
    assert read_program(ctx["program_id"])["participant_count_ytd"] == 1


def test_referring_a_business_generator_rewrites_every_line_it_had_taken(api):
    """PRD §3.7: "The appointment's status becomes `REFERRED_OUT`, the supplied
    `referral_program_code` is recorded, and a `referral_packet_code` is minted
    deterministically by joining three parts with hyphens: the
    `referral_program_code`, then the event's `event_date`, then the appointment's
    `queue_seq` — so a referral to `CESQG-DROPOFF` at an event dated 2026-09-12 for
    the seventh booking of that event reads `CESQG-DROPOFF-2026-09-12-7`."
    PRD §3.7: "Every dropoff line of that appointment has its `disposition` rewritten
    to `REFERRED_BUSINESS`, its `rejection_reason_code` set to `BUSINESS_GENERATOR`,
    and its `estimated_disposal_cost_cents` set to zero — and because those lines have
    left `ACCEPTED`, the resident's `annual_quantity_settled_kg` and the event's
    `accepted_tonnage_kg` and `rejected_tonnage_kg` are all recomputed."
    PRD §3.7: "The one thing referral never does is raise `participant_count`: a
    visitor sent to another program is not a participant of this one, and the
    distinction propagates all the way into the cost-per-participant figure of §3.9."

    Design: Corner/state_machines/refer_business_rewrites_lines_and_mints_referral_packet
    """
    ctx = setup_canon(
        20, line_weights=(1.5, 2.5), appointment={"declared_total_kg": 12.0}
    )
    assert ctx["appointment"]["queue_seq"] == 1
    assert ctx["lines"][0]["estimated_disposal_cost_cents"] == 233
    assert ctx["lines"][1]["estimated_disposal_cost_cents"] == 388

    referred = validate_success(
        api.appointment_transition(
            ctx["appointment_id"],
            {"action": "REFER_BUSINESS", "referral_program_code": "CESQG-DROPOFF"},
            TECH,
        ),
        200,
    )
    assert referred["status"] == "REFERRED_OUT"
    assert referred["referral_packet_code"] == "CESQG-DROPOFF-2026-09-12-1"
    assert_kg(referred["reserved_kg"], 0.0, "reserved_kg")
    assert_kg(referred["settled_kg"], 0.0, "settled_kg")

    for line_id in ctx["line_ids"]:
        line = read_dropoff_line(line_id)
        assert line["disposition"] == "REFERRED_BUSINESS"
        assert line["rejection_reason_code"] == "BUSINESS_GENERATOR"
        assert line["estimated_disposal_cost_cents"] == 0

    event = read_event(ctx["event_id"])
    assert event["participant_count"] == 0
    assert_kg(event["accepted_tonnage_kg"], 0.0, "accepted_tonnage_kg")
    assert_kg(event["rejected_tonnage_kg"], 4.0, "rejected_tonnage_kg")
    assert event["reserved_slot_count"] == 0

    resident = read_resident(ctx["resident_id"])
    assert_kg(resident["annual_quantity_reserved_kg"], 0.0, "annual_quantity_reserved_kg")
    assert_kg(resident["annual_quantity_settled_kg"], 0.0, "annual_quantity_settled_kg")
    assert read_program(ctx["program_id"])["participant_count_ytd"] == 0
