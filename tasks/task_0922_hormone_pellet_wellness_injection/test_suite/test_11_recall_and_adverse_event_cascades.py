"""The five-hop recall cascade, the severe-adverse-event cascade, and review."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adverse_events,
    assert_adverse_event,
    assert_lot_buckets,
    assert_same_instant,
    attach_consent_to,
    book_procedure,
    file_adverse_event,
    make_physician_headers,
    new_patient,
    new_physician,
    new_standing_order,
    open_supply_for,
    patient_notifications,
    perform_for,
    publish_protocol,
    read_adverse_event,
    read_consent,
    read_lot,
    read_patient,
    read_procedure,
    read_standing_order,
    recall_impact,
    recall_lot,
    receive_and_release_lot,
    record_consult,
    review_adverse_event,
    run_allocation_for,
    set_clock,
    setup_injection_visit,
    setup_pellet_procedure,
    sign_consent,
    validate_error,
    validate_success,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]


def _three_procedures_drawing_on_one_lot(api):
    """One consumed-and-completed procedure, one still-reserved procedure, and one
    consumed-then-voided procedure, all drawing on the same 200 mg lot."""
    physician = new_physician(api)
    patients = [
        new_patient(api, "Pat Eleven", "p11@example.com", date_of_birth="1980-01-11"),
        new_patient(api, "Pat Twelve", "p12@example.com", date_of_birth="1980-01-12"),
        new_patient(api, "Pat Thirteen", "p13@example.com", date_of_birth="1980-01-13"),
    ]
    publish_protocol(api, physician["id"], "TESTOSTERONE", "T pellet protocol v1")
    consents = [sign_consent(api, p["id"], "TESTOSTERONE", 1, 2000) for p in patients]
    consults = [
        record_consult(api, patients[0]["id"], physician["id"], prescribed_dose_mg=1150),
        record_consult(api, patients[1]["id"], physician["id"], prescribed_dose_mg=1150),
        record_consult(api, patients[2]["id"], physician["id"], prescribed_dose_mg=1000),
    ]
    order = new_standing_order(api, physician["id"])
    large_lot = receive_and_release_lot(api, "T200-A", strength_mg=200, qty_received=20)
    small_lot = receive_and_release_lot(api, "T100-B", strength_mg=100, qty_received=20)

    starts = ["2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z", "2026-05-10T13:00:00Z"]
    procedures = [
        book_procedure(
            api, patients[i]["id"], physician["id"], consults[i]["id"], order["id"],
            room_code="RM1", scheduled_start=starts[i],
        )
        for i in range(3)
    ]
    for procedure, consent in zip(procedures, consents):
        attach_consent_to(api, procedure["id"], consent["id"])
        run_allocation_for(api, procedure["id"])

    open_supply_for(api, procedures[0]["id"], physician["id"])
    open_supply_for(api, procedures[2]["id"], physician["id"])
    set_clock(api, "2026-05-10T09:00:00Z")
    perform_for(api, procedures[0]["id"], patients[0]["id"], physician["id"])
    perform_for(api, procedures[2]["id"], patients[2]["id"], physician["id"])
    validate_success(
        api.void_procedure(
            procedures[2]["id"], {"reason": "Wrong patient charted"},
            make_physician_headers(physician["id"]),
        ),
        200,
    )

    return {
        "physician": physician,
        "patients": patients,
        "procedures": procedures,
        "large_lot": large_lot,
        "small_lot": small_lot,
    }


def test_recall_projection_counts_are_deliberately_over_inclusive(api):
    """PRD §3.8: "Under `PROJECTION`, available at any time, the report is a deliberately
    over-inclusive worst-case planning number: `released_allocation_count` is the count of
    this lot's allocations in `RESERVED` or `OPENED`; `flagged_allocation_count` is the count
    in `CONSUMED`; `affected_procedure_count` is the number of distinct procedures owning those
    consumed allocations **with no procedure-status filter at all**; `held_procedure_count` is
    the number of distinct procedures owning reserved or opened allocations of this lot whose
    `status` is `SCHEDULED`, `CONSENTED` or `SUPPLY_OPENED`; `notification_count` equals
    `affected_procedure_count`; and `surveillance_event_count` equals
    `affected_procedure_count` when the optional `assume_severity` parameter is `CLASS_I` and
    is 0 otherwise."

    Design: Difficulty/transitive_cascade/lot_recall_five_hop_cascade_with_excluded_legs
    """
    ctx = _three_procedures_drawing_on_one_lot(api)

    projection = recall_impact(
        api, ctx["large_lot"]["id"], "PROJECTION", assume_severity="CLASS_I"
    )

    assert projection["lot_id"] == ctx["large_lot"]["id"]
    assert projection["variant"] == "PROJECTION"
    assert projection["released_allocation_count"] == 1
    assert projection["flagged_allocation_count"] == 2
    assert projection["affected_procedure_count"] == 2, (
        "The projection counts the voided procedure the cascade will skip"
    )
    assert projection["held_procedure_count"] == 1
    assert projection["notification_count"] == 2
    assert projection["surveillance_event_count"] == 2


def test_recall_cascade_moves_allocations_procedures_and_lot_buckets(api):
    """PRD §3.8: "Hop two chases the allocations: every allocation of this lot in `RESERVED`
    or in `OPENED` moves to `RECALL_RELEASED`, with its quantity moved from `qty_reserved`
    into `qty_returned`; every allocation in `CONSUMED` moves to `RECALL_FLAGGED` with **no**
    bucket movement at all, because those pellets are inside a patient; and allocations already
    in `RELEASED`, `WASTED` or `RECALL_RELEASED` are left untouched."
    PRD §3.8: "Hop three-a runs on the procedures' recall axis: every procedure whose `status`
    is `COMPLETED` and which owns an allocation just flagged moves `NONE → RECALL_AFFECTED`,
    incrementing its `version`; procedures in `VOIDED` or `CANCELLED` are explicitly skipped,
    and allocations that had already been released before the recall produce nothing. Hop
    three-b runs on the procedures' primary axis: every procedure in `SCHEDULED`, `CONSENTED`
    or `SUPPLY_OPENED` owning an allocation just moved to `RECALL_RELEASED` is frozen into
    `SUPPLY_HOLD` with `hold_reason` `LOT_RECALL`."
    PRD §3.8: "Hop one moves `sterility_status` to the terminal `RECALLED`, increases
    `qty_returned` by whatever `qty_on_hand` held and then sets `qty_on_hand` to 0, and
    records `recall_severity`, `recall_reason` and `recalled_at` from the logical clock."

    Design: Difficulty/transitive_cascade/lot_recall_five_hop_cascade_with_excluded_legs
    """
    ctx = _three_procedures_drawing_on_one_lot(api)

    recall_lot(api, ctx["large_lot"]["id"], "CLASS_I", "Endotoxin excursion")

    large = read_lot(api, ctx["large_lot"]["id"])
    assert large["sterility_status"] == "RECALLED"
    assert_lot_buckets(large, on_hand=0, reserved=0, consumed=10, wasted=0, returned=10)

    small = read_lot(api, ctx["small_lot"]["id"])
    assert_lot_buckets(small, on_hand=18, reserved=0, consumed=2, wasted=0, returned=0)

    completed, reserved_only, voided = (
        read_procedure(api, p["id"]) for p in ctx["procedures"]
    )
    assert completed["status"] == "COMPLETED"
    assert completed["recall_status"] == "NOTIFIED"
    assert reserved_only["status"] == "SUPPLY_HOLD"
    assert reserved_only["hold_reason"] == "LOT_RECALL"
    assert reserved_only["recall_status"] == "NONE"
    assert voided["status"] == "VOIDED"
    assert voided["recall_status"] == "NONE", (
        "Hop three-a explicitly skips procedures in VOIDED"
    )

    holds = [read_patient(api, p["id"])["clinical_hold"] for p in ctx["patients"]]
    assert holds == [True, False, False]
    assert read_patient(api, ctx["patients"][0]["id"])["eligibility_status"] == "CLINICAL_HOLD"


def test_recall_actual_counts_report_what_the_cascade_really_wrote(api):
    """PRD §3.8: "Under `ACTUAL`, meaningful once the lot has actually been recalled, the same
    six response fields are filled from what the cascade really wrote: allocations now in
    `RECALL_RELEASED`, allocations now in `RECALL_FLAGGED`, procedures with `recall_status` of
    `NOTIFIED` owning an allocation of this lot, procedures in `SUPPLY_HOLD` with
    `hold_reason` `LOT_RECALL` owning an allocation of this lot, notifications carrying this
    `lot_id`, and adverse events carrying this `lot_id` whose `source` is
    `RECALL_SURVEILLANCE`."
    PRD §3.8: "Hop five runs **only** for a `CLASS_I` recall: for each such notification the
    server mints an `AdverseEvent` with `severity` `SURVEILLANCE`, `source`
    `RECALL_SURVEILLANCE`, `status` `OPEN` and `reported_by_provider_id` set to the affected
    procedure's `provider_id`, and sets that patient's `clinical_hold` to true."

    Design: Difficulty/transitive_cascade/lot_recall_five_hop_cascade_with_excluded_legs
    """
    ctx = _three_procedures_drawing_on_one_lot(api)

    recall_lot(api, ctx["large_lot"]["id"], "CLASS_I", "Endotoxin excursion")
    actual = recall_impact(api, ctx["large_lot"]["id"], "ACTUAL")

    assert actual["variant"] == "ACTUAL"
    assert actual["released_allocation_count"] == 1
    assert actual["flagged_allocation_count"] == 2
    assert actual["affected_procedure_count"] == 1
    assert actual["held_procedure_count"] == 1
    assert actual["notification_count"] == 1
    assert actual["surveillance_event_count"] == 1

    notes = patient_notifications(api, params={"lot_id": ctx["large_lot"]["id"]})
    assert len(notes) == 1
    assert notes[0]["patient_id"] == ctx["patients"][0]["id"]
    assert notes[0]["notification_type"] == "RECALL"
    assert notes[0]["severity_class"] == "CLASS_I"
    assert notes[0]["procedure_id"] == ctx["procedures"][0]["id"]

    surveillance = adverse_events(api, {"source": "RECALL_SURVEILLANCE"})
    assert len(surveillance) == 1
    assert surveillance[0]["severity"] == "SURVEILLANCE"
    assert surveillance[0]["status"] == "OPEN"
    assert surveillance[0]["patient_id"] == ctx["patients"][0]["id"]
    assert_adverse_event(surveillance[0])


def _completed_procedure_then_class_two_recall(api):
    ctx = setup_pellet_procedure(
        api, target_status="COMPLETED", prescribed_dose_mg=1000,
        patient_name="Pat Ten", patient_email="p10@example.com",
        room_code="RM8", scheduled_start="2026-05-10T09:00:00Z",
        perform_at="2026-05-10T09:00:00Z",
        lot_specs=[{"lot_code": "T200-A", "strength_mg": 200, "qty_received": 10}],
    )
    recall_lot(
        api, ctx["lots"]["T200-A"]["id"], "CLASS_II", "Sterility excursion at the fill line"
    )
    return ctx


def test_recall_notifies_the_completed_procedure_on_its_own_axis(api):
    """PRD §3.8: "Hop four notifies. Each recall-affected procedure mints a
    `PatientNotification` whose `notification_type` is `RECALL`, whose `severity_class`
    carries the lot's `recall_severity` through, and whose `patient_id`, `procedure_id` and
    `lot_id` are all set; its `status` starts `PENDING`, its `due_at` is 7 days after the
    moment of creation, `acknowledged_at` is null, and the patient's `open_notification_count`
    rises by 1. The procedure then moves `RECALL_AFFECTED → NOTIFIED`, which is terminal on
    that axis."
    PRD §3.8: "Hop five runs **only** for a `CLASS_I` recall: for each such notification the
    server mints an `AdverseEvent` with `severity` `SURVEILLANCE`, `source`
    `RECALL_SURVEILLANCE`, `status` `OPEN` and `reported_by_provider_id` set to the affected
    procedure's `provider_id`, and sets that patient's `clinical_hold` to true. A `CLASS_II`
    recall notifies without holding anybody."

    Design: Difficulty/non_linear_state_machine/procedure_status_and_recall_status_are_independent_axes
    """
    ctx = _completed_procedure_then_class_two_recall(api)

    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "COMPLETED"
    assert procedure["recall_status"] == "NOTIFIED"

    notes = patient_notifications(api, ctx["patient_id"])
    assert len(notes) == 1
    assert notes[0]["notification_type"] == "RECALL"
    assert notes[0]["severity_class"] == "CLASS_II"
    assert notes[0]["status"] == "PENDING"
    assert notes[0]["acknowledged_at"] is None
    assert_same_instant(notes[0]["due_at"], "2026-05-17T09:00:00Z", "due_at")

    patient = read_patient(api, ctx["patient_id"])
    assert patient["clinical_hold"] is False
    assert patient["open_notification_count"] == 1


def test_voiding_leaves_the_recall_axis_pinned_at_notified(api):
    """PRD §3.8: "Two independent axes on the same procedure row make this workable: the
    primary `status` axis and the `recall_status` axis run entirely independently, so the same
    row can read `COMPLETED` with `NONE`, `COMPLETED` with `RECALL_AFFECTED`, or `COMPLETED`
    with `NOTIFIED`, and status transitions never touch the recall axis."
    PRD §3.6: "The procedure's `delivered_total_mg` is reset to 0; the patient's
    `cumulative_mg_testosterone` or `cumulative_mg_estradiol` is reduced by the pre-void
    delivered figure; and `last_insertion_at` together with `last_insertion_hormone_type` are
    recomputed from whatever completed procedures remain, falling back to null when none do.
    Allocation rows stay `CONSUMED` and every lot bucket is left exactly as it was, because
    the pellets are physically inside the patient and no accounting entry brings them back."

    Design: Difficulty/non_linear_state_machine/procedure_status_and_recall_status_are_independent_axes
    """
    ctx = _completed_procedure_then_class_two_recall(api)

    voided = validate_success(
        api.void_procedure(
            ctx["procedure_id"], {"reason": "Billing correction after recall"},
            make_physician_headers(ctx["physician_id"]),
        ),
        200,
    )

    assert voided["status"] == "VOIDED"
    assert voided["recall_status"] == "NOTIFIED", (
        "The recall axis is not a function of the lifecycle axis"
    )
    assert voided["delivered_total_mg"] == 0

    patient = read_patient(api, ctx["patient_id"])
    assert patient["cumulative_mg_testosterone"] == 0
    assert patient["last_insertion_at"] is None
    assert patient["clinical_hold"] is False

    assert_lot_buckets(
        read_lot(api, ctx["lots"]["T200-A"]["id"]),
        on_hand=0, reserved=0, consumed=5, wasted=0, returned=5,
    )


def _two_consented_procedures_under_one_order(api):
    """Two patients, each with a CONSENTED procedure allocated under the same order."""
    physician = new_physician(api)
    first = new_patient(api, "Pat Fourteen", "p14@example.com", date_of_birth="1981-02-14")
    second = new_patient(api, "Pat Fifteen", "p15@example.com", date_of_birth="1981-02-15")
    publish_protocol(api, physician["id"], "TESTOSTERONE", "T pellet protocol v1")
    first_consent = sign_consent(api, first["id"], "TESTOSTERONE", 1, 2000)
    second_consent = sign_consent(api, second["id"], "TESTOSTERONE", 1, 2000)
    first_consult = record_consult(api, first["id"], physician["id"], prescribed_dose_mg=1150)
    second_consult = record_consult(api, second["id"], physician["id"], prescribed_dose_mg=1150)
    order = new_standing_order(api, physician["id"])
    large_lot = receive_and_release_lot(api, "T200-A", strength_mg=200, qty_received=20)
    small_lot = receive_and_release_lot(api, "T100-B", strength_mg=100, qty_received=20)

    first_procedure = book_procedure(
        api, first["id"], physician["id"], first_consult["id"], order["id"],
        room_code="RM1", scheduled_start="2026-05-14T09:00:00Z",
    )
    second_procedure = book_procedure(
        api, second["id"], physician["id"], second_consult["id"], order["id"],
        room_code="RM1", scheduled_start="2026-05-14T11:00:00Z",
    )
    for procedure, consent in (
        (first_procedure, first_consent), (second_procedure, second_consent)
    ):
        attach_consent_to(api, procedure["id"], consent["id"])
        run_allocation_for(api, procedure["id"])

    set_clock(api, "2026-05-02T00:00:00Z")
    return {
        "physician": physician,
        "patients": [first, second],
        "consents": [first_consent, second_consent],
        "procedures": [first_procedure, second_procedure],
        "order": order,
        "large_lot": large_lot,
        "small_lot": small_lot,
    }


def test_severe_event_suspends_the_order_and_freezes_every_procedure_under_it(api):
    """PRD §3.8: "`SEVERE` fires a four-hop cascade and also increments the patient's
    `version`. Hop one sets `review_due_at` to 24 hours after filing, sets the patient's
    `clinical_hold` to true with `eligibility_status` recomputed, supersedes **every** `ACTIVE`
    consent belonging to that patient regardless of hormone type, and, when a `lot_id` was
    named and that lot is `RELEASED`, moves the lot back `RELEASED → QUARANTINED` so it stops
    being an allocation candidate — existing reserved and opened allocations against it are
    left untouched. Hop two suspends the referenced standing order. Hop three freezes every
    procedure booked under that order whose `status` is `SCHEDULED`, `CONSENTED` or
    `SUPPLY_OPENED` into `SUPPLY_HOLD` with `hold_reason` `STANDING_ORDER_SUSPENDED` —
    including procedures belonging to patients who have nothing whatever to do with the event."
    PRD §3.8: "Suspension is never a client action — it is hop two of the severe-adverse-event
    cascade, moving the order `ACTIVE → SUSPENDED` with `suspended_reason` set to
    `SEVERE_ADVERSE_EVENT`."

    Design: Difficulty/transitive_cascade/severe_adverse_event_four_hop_cascade_reaches_other_patients
    """
    ctx = _two_consented_procedures_under_one_order(api)

    event = file_adverse_event(
        api, ctx["patients"][0]["id"], ctx["physician"]["id"], severity="SEVERE",
        narrative="Post-insertion site infection with systemic signs",
        onset_at="2026-05-01T18:00:00Z", standing_order_id=ctx["order"]["id"],
    )

    assert event["status"] == "OPEN"
    assert_same_instant(event["review_due_at"], "2026-05-03T00:00:00Z", "review_due_at")

    order = read_standing_order(api, ctx["order"]["id"])
    assert order["status"] == "SUSPENDED"
    assert order["suspended_reason"] == "SEVERE_ADVERSE_EVENT"

    for procedure in ctx["procedures"]:
        frozen = read_procedure(api, procedure["id"])
        assert frozen["status"] == "SUPPLY_HOLD"
        assert frozen["hold_reason"] == "STANDING_ORDER_SUSPENDED"


def test_severe_event_releases_an_unrelated_patients_reserved_pellets(api):
    """PRD §3.8: "Hop four releases those procedures' pellets: every allocation of theirs in
    `RESERVED` or `OPENED` moves to `RELEASED` with its quantity returned from `qty_reserved`
    to `qty_on_hand`, which changes which lot the next unrelated patient's plan will draw from."
    PRD §3.2: "Three distinct events supersede a consent: a newer consent for the same patient
    and hormone, the protocol-publication cascade described above, and the filing of a severe
    adverse event, which supersedes every `ACTIVE` consent belonging to the affected patient
    regardless of hormone type."

    Design: Difficulty/transitive_cascade/severe_adverse_event_four_hop_cascade_reaches_other_patients
    """
    ctx = _two_consented_procedures_under_one_order(api)

    file_adverse_event(
        api, ctx["patients"][0]["id"], ctx["physician"]["id"], severity="SEVERE",
        narrative="Post-insertion site infection with systemic signs",
        onset_at="2026-05-01T18:00:00Z", standing_order_id=ctx["order"]["id"],
    )

    assert_lot_buckets(
        read_lot(api, ctx["large_lot"]["id"]),
        on_hand=20, reserved=0, consumed=0, wasted=0, returned=0,
    )
    assert_lot_buckets(
        read_lot(api, ctx["small_lot"]["id"]),
        on_hand=20, reserved=0, consumed=0, wasted=0, returned=0,
    )

    assert read_consent(api, ctx["consents"][0]["id"])["status"] == "SUPERSEDED"
    assert read_consent(api, ctx["consents"][1]["id"])["status"] == "ACTIVE", (
        "Only the affected patient's consents are superseded"
    )
    assert read_patient(api, ctx["patients"][0]["id"])["clinical_hold"] is True
    assert read_patient(api, ctx["patients"][1]["id"])["clinical_hold"] is False


def _visit_blocked_by_a_severe_event(api):
    ctx = setup_injection_visit(
        api, injection_type="GLUTATHIONE", room_code="RM17",
        scheduled_start="2026-05-18T09:00:00Z",
        patient_name="Pat TwentyFour", patient_email="p24@example.com",
    )
    ctx["event"] = file_adverse_event(
        api, ctx["patient_id"], ctx["physician_id"], severity="SEVERE",
        narrative="Anaphylactoid reaction to a prior injection",
        onset_at="2026-05-01T06:00:00Z",
    )
    set_clock(api, "2026-05-18T09:00:00Z")
    return ctx


def test_injection_administration_is_refused_while_the_clinical_hold_is_true(api):
    """PRD §3.7: "Administering the injection moves it `SCHEDULED → ADMINISTERED` and is done
    by a `NurseInjector` under the delegation gate or by a `Physician` on their own licence.
    The patient's `clinical_hold` must be false and no panel of theirs may sit in
    `CRITICAL_FLAGGED`; a financial hold, by contrast, does **not** block administration."
    PRD §2.9: "**Rung 14** — `clinical_hold` is false on the patient, on
    `POST /clinic/procedures`, `POST /clinic/procedures/{id}/perform` and
    `POST /clinic/injection-visits/{id}/administer`. Otherwise `ERR_PATIENT_CLINICAL_HOLD`
    (409)."

    Design: Difficulty/cross_entity_state_dependency/injection_administer_blocked_by_patient_clinical_hold
    """
    ctx = _visit_blocked_by_a_severe_event(api)

    response = api.administer_injection_visit(
        ctx["visit_id"], make_physician_headers(ctx["physician_id"])
    )
    validate_error(response, ApiErrorId.ERR_PATIENT_CLINICAL_HOLD.value)
    assert response.status_code == 409

    patient = read_patient(api, ctx["patient_id"])
    assert patient["clinical_hold"] is True
    assert patient["eligibility_status"] == "CLINICAL_HOLD"

    visit = validate_success(api.get_injection_visit(ctx["visit_id"], FRONT_DESK), 200)
    assert visit["status"] == "SCHEDULED"
    assert visit["charge_cents"] == 0


def test_severe_event_naming_no_standing_order_leaves_the_order_active(api):
    """PRD §3.8: "Up to four optional references pin the event to what is implicated: a
    `procedure_id`, an `injection_visit_id`, a `lot_id` and a `standing_order_id`, in any
    combination including none."
    PRD §3.8: "Hop two suspends the referenced standing order. Hop three freezes every
    procedure booked under that order whose `status` is `SCHEDULED`, `CONSENTED` or
    `SUPPLY_OPENED` into `SUPPLY_HOLD` with `hold_reason` `STANDING_ORDER_SUSPENDED` —
    including procedures belonging to patients who have nothing whatever to do with the event."
    PRD §3.1: "`clinical_hold` is set true by three things: filing an adverse event with
    severity `SEVERE`, the surveillance hop of a class-one lot recall, and an explicit
    eligibility-hold action carrying `hold_kind` of `CLINICAL` with `hold_action` of `SET`."

    Design: Difficulty/cross_entity_state_dependency/injection_administer_blocked_by_patient_clinical_hold
    """
    ctx = _visit_blocked_by_a_severe_event(api)

    order = read_standing_order(api, ctx["standing_order_id"])
    assert order["status"] == "ACTIVE", "No standing order was referenced, so hop two hit nothing"
    assert order["suspended_reason"] is None

    event = read_adverse_event(api, ctx["event"]["id"])
    assert event["severity"] == "SEVERE"
    assert event["status"] == "OPEN"
    assert event["source"] == "CLINICAL_REPORT"


def test_reinstating_an_active_standing_order_reports_invalid_state(api):
    """PRD §3.8: "Reinstatement, available only to the authoring physician (the acting
    `X-User-ID` must equal the order's `physician_id`), moves it `SUSPENDED → ACTIVE`, but only
    when **every** adverse event referencing that order has reached `CLOSED`; it clears
    `suspended_reason` back to null and releases every procedure the suspension held."
    PRD §2.9: "**Rung 10** — the target row is in a state from which the requested transition
    is declared on the relevant axis, on every action endpoint. Otherwise `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/reinstate_an_active_standing_order_returns_invalid_state
    """
    physician = new_physician(api)
    order = new_standing_order(api, physician["id"])

    response = api.reinstate_standing_order(
        order["id"], make_physician_headers(physician["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409

    after = read_standing_order(api, order["id"])
    assert after["status"] == "ACTIVE"
    assert after["suspended_reason"] is None


def test_closing_an_escalated_event_demands_a_third_physician(api):
    """PRD §3.8: "From `ESCALATED` the event converges over the leg `ESCALATED → CLOSED`, and
    here the segregation rule tightens: the closing physician's `X-User-ID` must differ from
    `reported_by_provider_id` **and** from the `reviewed_by_provider_id` written by the
    escalating review, so three distinct people are required to close an escalated event —
    reporter, escalating reviewer, closing reviewer. The closing review overwrites
    `reviewed_by_provider_id` with the closing physician."
    PRD §3.8: "`MILD` logs and nothing more: `review_due_at` stays null and no hold is placed."

    Design: Corner/state_machines/adverse_event_escalated_then_closed_requires_a_third_physician
    """
    reporter = new_physician(api)
    escalator = new_physician(api, "Dr Ben Sato", "1000000002")
    closer = new_physician(api, "Dr Cara Diaz", "1000000004")
    patient = new_patient(api, "Corner Eleven", "c11@example.com")
    event = file_adverse_event(
        api, patient["id"], reporter["id"], severity="MILD",
        narrative="Transient soreness at the insertion site", onset_at="2026-05-01T06:00:00Z",
    )

    escalated = review_adverse_event(
        api, event["id"], escalator["id"], "ESCALATED", "Wants a second opinion"
    )
    assert escalated["status"] == "ESCALATED"
    assert escalated["reviewed_by_provider_id"] == escalator["id"]

    refused = api.review_adverse_event(
        event["id"],
        {"disposition": "CLOSED", "disposition_note": "Closing my own escalation"},
        make_physician_headers(escalator["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert refused.status_code == 403

    closed = review_adverse_event(
        api, event["id"], closer["id"], "CLOSED", "Independent review complete"
    )
    assert closed["status"] == "CLOSED"
    assert closed["reviewed_by_provider_id"] == closer["id"]
    assert closed["review_due_at"] is None
    assert read_patient(api, patient["id"])["clinical_hold"] is False


def test_reporter_cannot_review_their_own_adverse_event(api):
    """PRD §3.8: "Review is a `Physician`-only action carrying a `disposition` of `CLOSED` or
    `ESCALATED` and a `disposition_note`. Segregation of duties is absolute: the acting
    `X-User-ID` must differ from `reported_by_provider_id`, and a violation answers
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "`MODERATE` sets `review_due_at` to 14 days after the moment of filing — note
    that the deadline is anchored on the filing instant, not on `onset_at` — places no hold,
    and increments the patient's `version` by 1."

    Design: Corner/state_machines/reporter_cannot_review_their_own_adverse_event
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner Twelve", "c12@example.com")
    event = file_adverse_event(
        api, patient["id"], physician["id"], severity="MODERATE",
        narrative="Persistent erythema", onset_at="2026-05-01T06:00:00Z",
    )

    response = api.review_adverse_event(
        event["id"], {"disposition": "CLOSED", "disposition_note": "Self review"},
        make_physician_headers(physician["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert response.status_code == 403

    after = read_adverse_event(api, event["id"])
    assert after["status"] == "OPEN"
    assert after["reviewed_by_provider_id"] is None
    assert_same_instant(after["review_due_at"], "2026-05-15T00:00:00Z", "review_due_at")
    assert read_patient(api, patient["id"])["clinical_hold"] is False


def test_revoking_a_standing_order_leaves_its_scheduled_procedures_untouched(api):
    """PRD §3.8: "Revocation and suspension differ in a way that matters operationally:
    revocation is **forward-looking only**, so already-scheduled procedures are *not* frozen
    and simply lose their delegated cover for future administrations, whereas suspension
    freezes them."
    PRD §3.8: "Revocation, again restricted to the authoring physician, may be applied with an
    optional `reason` over either of two legs, `ACTIVE → REVOKED` or `SUSPENDED → REVOKED`,
    reaching the terminal `REVOKED`."

    Design: Corner/state_machines/standing_order_revoke_leaves_scheduled_procedures_untouched
    """
    ctx = setup_pellet_procedure(
        api, target_status="CONSENTED", prescribed_dose_mg=1000,
        patient_name="Corner Thirteen", patient_email="c13@example.com",
        room_code="RM34", scheduled_start="2026-06-12T09:00:00Z",
        lot_specs=[{"lot_code": "T200-A", "strength_mg": 200, "qty_received": 10}],
    )

    revoked = validate_success(
        api.revoke_standing_order(
            ctx["standing_order_id"], {"reason": "Retired"},
            make_physician_headers(ctx["physician_id"]),
        ),
        200,
    )
    assert revoked["status"] == "REVOKED"

    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "CONSENTED", "Revocation freezes nothing"
    assert procedure["hold_reason"] is None

    assert_lot_buckets(
        read_lot(api, ctx["lots"]["T200-A"]["id"]),
        on_hand=5, reserved=5, consumed=0, wasted=0, returned=0,
    )
