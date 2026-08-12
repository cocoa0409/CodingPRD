"""The deep cascades: equipment quarantine, the STAT stop bump, and what they conserve."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accepted_referral_with_appointment,
    acquire_study,
    add_stop,
    assert_block_conservation,
    assert_invoice_total_matches_active_lines,
    assert_same_instant,
    block_purchase,
    finalize_invoice,
    make_field_tech_headers,
    new_calibrated_equipment,
    new_clinic,
    new_mobile_unit,
    new_route,
    new_specialist,
    new_study,
    new_technician,
    open_invoice,
    offer_read,
    post_study,
    qc_study,
    read_and_finalize,
    record_qc_check,
    route_version,
    set_clock,
    setup_mobile_scene,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# --------------------------------------------------------------------------
# The seven-hop equipment-quarantine cascade — difficulty instance
# --------------------------------------------------------------------------
def _one_posted_study_and_one_offered_study_on_the_same_unit(api):
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Cascade Vet", address_zone="Z8", contract_kind="PREPAID_BLOCK",
        block_purchased_studies=2, unit_name="Van Q", equipment_serial="US-Q",
        technician_name="Quinn Ade", body_regions=("ABDOMEN", "THORAX"),
        acquire=True, qc_result="ACCEPTED", image_count=10,
    )
    specialist = new_specialist("Dr Osei", ("ULTRASOUND",), ("CANINE",), stat_eligible=True)
    posted_study, offered_study = scene["studies"]
    assignment_posted, report = read_and_finalize(posted_study["id"], specialist["id"],
                                                  findings="hepatic nodule")
    assignment_offered = offer_read(offered_study["id"], specialist["id"])
    invoice = open_invoice(scene["clinic"]["id"])
    posted = post_study(invoice["id"], posted_study["id"])
    scene.update({
        "specialist": specialist, "report": report, "invoice": invoice,
        "assignment_posted": assignment_posted, "assignment_offered": assignment_offered,
        "total_before_fail": posted["total_cents"],
    })
    return scene


def test_a_failing_check_condemns_every_study_the_unit_acquired_since_its_last_pass(api):
    """PRD §3.6: "A `FAIL` quarantines the unit and reaches backwards. The **blast
    radius** is computed first. Take the cutoff to be the unit's `last_passing_qc_at`,
    or, when that is null because the unit has never passed a check, the unit's own
    `created_at`."
    PRD §3.6: "**Hop 2**, caused by hop 1. Every study in the blast radius moves its
    `qc_status` to `REPEAT_REQUIRED` and its `workflow_status` to `REPEAT_PENDING`. On
    the quality axis this is a genuine re-entry edge: a study already sitting at
    `ACCEPTED` is retroactively demoted `ACCEPTED → REPEAT_REQUIRED`, which is what
    makes that axis non-linear."
    PRD §3.6: "**Hop 2b**, caused by hop 2. Every report on those studies whose
    `status` is `PUBLISHED` moves `PUBLISHED → RETRACTED` with `retract_reason` set to
    the literal string `EQUIPMENT_QUARANTINE`."
    PRD §3.6: "**Hop 3**, caused by hop 2. Every read assignment on those studies
    whose `status` is `OFFERED` or `ACCEPTED` moves to `REVOKED`."
    PRD §3.6: "**Hop 7**, caused by hop 2. One notification of kind
    `STUDY_REPEAT_REQUIRED` is appended per affected study, addressed to that study's
    clinic."

    Design: Difficulty/transitive_cascade/qc_fail_quarantine_six_hop_cascade_to_contract_balance
    """
    scene = _one_posted_study_and_one_offered_study_on_the_same_unit(api)
    posted_study, offered_study = scene["studies"]

    check = record_qc_check(scene["equipment"]["id"], scene["technician"]["id"], "FAIL",
                            note="phantom resolution out of tolerance")

    assert check["affected_study_count"] == 2
    assert validate_success(api.get_equipment(scene["equipment"]["id"], ADMIN))["calibration_status"] == "QUARANTINED"
    for study_id in (posted_study["id"], offered_study["id"]):
        state = validate_success(api.get_study(study_id, SCHED))
        assert state["workflow_status"] == "REPEAT_PENDING"
        assert state["qc_status"] == "REPEAT_REQUIRED"
    assert validate_success(api.get_report(scene["report"]["id"], SCHED))["status"] == "RETRACTED"
    assert validate_success(api.get_read_assignment(scene["assignment_offered"]["id"], SCHED))["status"] == "REVOKED"
    assert validate_success(api.get_read_assignment(scene["assignment_posted"]["id"], SCHED))["status"] == "COMPLETED"
    assert validate_success(api.get_specialist(scene["specialist"]["id"], SCHED))["open_read_count"] == 0
    rows, _meta = validate_paginated(
        api.list_notifications(SCHED, params={"clinic_id": scene["clinic"]["id"],
                                              "kind": "STUDY_REPEAT_REQUIRED"})
    )
    assert len(rows) == 2


def test_the_quarantine_cascade_reverses_the_charges_and_refunds_the_block_unit(api):
    """PRD §3.6: "**Hop 4b**, caused by hop 2. Every `ACTIVE` charge line on those
    studies whose invoice is `OPEN` moves to `REVERSED` with `reversal_reason` set to
    `EQUIPMENT_QUARANTINE`, and each such study moves its billing axis `POSTED →
    REVERSED`."
    PRD §3.6: "**Hop 5**, caused by hop 4b. Every invoice thereby touched recomputes
    `total_cents` and `posted_study_count`."
    PRD §3.6: "**Hop 6**, caused by hop 4b. For each reversed study that had drawn a
    block unit, a block ledger entry with `delta_studies` of positive 1 and `reason`
    of `REFUND_QC` is appended, and its contract's `block_consumed_studies` decreases
    while its `block_remaining_studies` increases by the same amount."

    Derivation: the posted study drew the block, so it priced at the 20000 block rate
    with a 6250 trip share and 3 percent of 26250 = 787.5 rounding to 788 — an invoice
    total of 27038 before the failure.  Reversing all three lines empties the invoice.

    Design: Difficulty/transitive_cascade/qc_fail_quarantine_six_hop_cascade_to_contract_balance
    """
    scene = _one_posted_study_and_one_offered_study_on_the_same_unit(api)
    assert scene["total_before_fail"] == 27038

    record_qc_check(scene["equipment"]["id"], scene["technician"]["id"], "FAIL",
                    note="phantom resolution out of tolerance")

    assert validate_success(api.get_study(scene["studies"][0]["id"], SCHED))["billing_status"] == "REVERSED"
    lines, _m1 = validate_paginated(
        api.list_charge_lines(BILLING, params={"invoice_id": scene["invoice"]["id"]})
    )
    assert len(lines) == 3
    assert all(line["status"] == "REVERSED" for line in lines)
    invoice = validate_success(api.get_invoice(scene["invoice"]["id"], BILLING))
    assert invoice["total_cents"] == 0
    assert_invoice_total_matches_active_lines(invoice, lines)
    contract = validate_success(api.get_contract(scene["contract"]["id"], BILLING))
    assert contract["block_consumed_studies"] == 0
    assert contract["block_remaining_studies"] == 2
    assert_block_conservation(contract)
    entries, _m2 = validate_paginated(
        api.list_block_ledger_entries(BILLING, params={"contract_id": scene["contract"]["id"]})
    )
    assert len(entries) == 2
    assert sum(entry["delta_studies"] for entry in entries) == 0


# --------------------------------------------------------------------------
# The STAT stop bump — difficulty instance
# --------------------------------------------------------------------------
def _full_route_whose_last_routine_stop_carries_an_ordered_study(api):
    set_clock("2026-05-04T08:00:00Z")
    clinics = [new_clinic(f"Clinic C{n}", "Z9") for n in range(1, 4)]
    emergency_clinic = new_clinic("Clinic C4 Emergency", "Z9")
    unit = new_mobile_unit("Van Bump")
    technician = new_technician("Rae Solis", ["ULTRASOUND"])
    route = new_route(unit["id"], technician["id"])
    stops = [
        add_stop(route["id"], clinic["id"], planned_arrival_minute=arrival,
                 service_minutes=20, drive_minutes_from_prev=5)
        for clinic, arrival in zip(clinics, (500, 540, 580))
    ]
    _referral, appointment = accepted_referral_with_appointment(
        clinics[2]["id"], route_stop_id=stops[2]["id"], patient_name="Pippin",
        study_kind="MOBILE", requested_modality="ULTRASOUND",
        clinical_history="routine screening",
    )
    study = new_study(appointment["id"], clinics[2]["id"])
    return clinics, emergency_clinic, route, stops, appointment, study


def test_a_stat_insertion_sacrifices_the_latest_planned_routine_stop(api):
    """PRD §3.3: "**Victim selection** considers only stops on this route whose
    `status` is `PLANNED` and whose `stop_priority` is `ROUTINE`; stops that are
    `EN_ROUTE`, `ARRIVED`, `SERVICED`, `BUMPED` or `CANCELLED` are never victims, and
    neither is another STAT stop. Among the eligible stops the one with the **latest**
    `planned_arrival_minute` is sacrificed first — the last routine visit of the day
    is the cheapest to lose — with ties broken by the earlier `created_at`.
    Identifiers are never part of the ordering."
    PRD §3.3: "**First**, a STAT stop's service time is forced to 30 minutes,
    overriding whatever the payload asked for — the stop's persisted `service_minutes`
    reads 30 — and that override is applied before rung 40 and every later rung runs"
    PRD §3.3: "**Hop 1** stamps the victim's `bumped_by_stop_id` with the id of the
    newly inserted STAT stop and writes the literal string `BUMPED_BY_STAT_INSERTION`
    into its `cancel_reason`."

    Derivation: the van carries the default ceiling of 3 stops, so the fourth
    insertion breaches the count test; because the newcomer is STAT the server bumps
    the latest PLANNED routine stop — the one arriving at minute 580 — and the route
    settles back at 3 counted stops occupying (5+20) + (5+20) + (5+30) = 85 minutes.

    Design: Difficulty/transitive_cascade/stat_stop_insertion_bumps_routine_stop_five_hop_cascade
    """
    _clinics, emergency_clinic, route, stops, _appointment, _study = (
        _full_route_whose_last_routine_stop_carries_an_ordered_study(api)
    )

    stat_stop = validate_success(
        api.add_route_stop(
            route["id"],
            {
                "clinic_id": emergency_clinic["id"],
                "planned_arrival_minute": 620,
                "service_minutes": 30,
                "drive_minutes_from_prev": 5,
                "stop_priority": "STAT",
                "expected_route_version": route_version(route["id"]),
            },
            SCHED,
        ),
        expected_status=201,
    )

    assert stat_stop["service_minutes"] == 30
    victim = validate_success(api.get_route_stop(stops[2]["id"], SCHED))
    assert victim["status"] == "BUMPED"
    assert victim["bumped_by_stop_id"] == stat_stop["id"]
    assert validate_success(api.get_route_stop(stops[0]["id"], SCHED))["status"] == "PLANNED"
    assert validate_success(api.get_route_stop(stops[1]["id"], SCHED))["status"] == "PLANNED"
    route_after = validate_success(api.get_route(route["id"], SCHED))
    assert route_after["stop_count"] == 3
    assert route_after["planned_occupied_minutes"] == 85


def test_the_bump_cancels_the_appointment_and_costs_the_clinic_nothing(api):
    """PRD §3.3: "**Hop 2**, caused by hop 1, moves every appointment bound to that
    stop whose `status` is `SCHEDULED` or `IN_PROGRESS` to `CANCELLED_BY_PROVIDER`,
    stamping `cancelled_at` with the logical clock."
    PRD §3.3: "**Hop 3**, caused by hop 2, moves every study under those appointments
    whose `workflow_status` is `ORDERED` to `NOT_PERFORMED`, writes the literal string
    `STOP_BUMPED` into its `cancel_reason`, sets its `cancellation_fee_cents` to 0 and
    its `billing_status` to `NON_BILLABLE`. Provider-caused cancellation costs the
    clinic nothing, regardless of how little lead time was left."
    PRD §3.3: "**Hop 6**, caused by hop 2, appends one notification of kind
    `APPOINTMENT_CANCELLED` per cancelled appointment plus one notification of kind
    `STOP_BUMPED` for the stop's clinic."

    Design: Difficulty/transitive_cascade/stat_stop_insertion_bumps_routine_stop_five_hop_cascade
    """
    clinics, emergency_clinic, route, _stops, appointment, study = (
        _full_route_whose_last_routine_stop_carries_an_ordered_study(api)
    )

    validate_success(
        api.add_route_stop(
            route["id"],
            {
                "clinic_id": emergency_clinic["id"],
                "planned_arrival_minute": 620,
                "service_minutes": 30,
                "drive_minutes_from_prev": 5,
                "stop_priority": "STAT",
                "expected_route_version": route_version(route["id"]),
            },
            SCHED,
        ),
        expected_status=201,
    )

    cancelled_appointment = validate_success(api.get_appointment(appointment["id"], SCHED))
    assert cancelled_appointment["status"] == "CANCELLED_BY_PROVIDER"
    assert cancelled_appointment["ordered_studies_count"] == 1
    assert cancelled_appointment["not_performed_studies_count"] == 1
    dropped = validate_success(api.get_study(study["id"], SCHED))
    assert dropped["workflow_status"] == "NOT_PERFORMED"
    assert dropped["cancellation_fee_cents"] == 0
    assert dropped["billing_status"] == "NON_BILLABLE"
    rows, _meta = validate_paginated(
        api.list_notifications(SCHED, params={"clinic_id": clinics[2]["id"]})
    )
    kinds = sorted(row["kind"] for row in rows)
    assert kinds == ["APPOINTMENT_CANCELLED", "STOP_BUMPED"]


# --------------------------------------------------------------------------
# Block conservation across a draw, a top-up and a refund — difficulty instance
# --------------------------------------------------------------------------
def _posted_study_on_a_single_unit_block(api):
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Blockbuy Vet", address_zone="Z18", contract_kind="PREPAID_BLOCK",
        block_purchased_studies=1, unit_name="Van BB", equipment_serial="US-BB",
        technician_name="Ada Kim", acquire=True, qc_result="ACCEPTED", image_count=11,
    )
    specialist = new_specialist("Dr Amari", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    study = scene["studies"][0]
    read_and_finalize(study["id"], specialist["id"], findings="gastric foreign body")
    invoice = open_invoice(scene["clinic"]["id"])
    post_study(invoice["id"], study["id"])
    scene["invoice"] = invoice
    return scene


def test_the_block_partition_holds_across_a_draw_a_top_up_and_a_refund(api):
    """PRD §2.10: "**Block conservation.** A contract's `block_purchased_studies`
    equals its `block_consumed_studies` plus its `block_remaining_studies`; and
    `block_consumed_studies` equals the negation of the sum of `delta_studies` over
    every block ledger entry whose `contract_id` is that contract."
    PRD §3.1: "Topping up a block adds a supplied `additional_studies` count to both
    `block_purchased_studies` and `block_remaining_studies`, and is subject to the
    concurrency rule of §2.7 and to rung 16's requirement that the clinic have exactly
    one contract computing to `ACTIVE`."

    Derivation: after the draw the contract reads purchased 1, consumed 1, remaining
    0; the top-up of 2 makes it 3, 1 and 2; the quarantine refund makes it 3, 0 and 3.
    The partition holds at all three observation points.

    Design: Difficulty/compensating_invariant/block_ledger_draw_and_qc_refund_conserve_purchased_studies
    """
    scene = _posted_study_on_a_single_unit_block(api)
    contract_id = scene["contract"]["id"]

    after_draw = validate_success(api.get_contract(contract_id, BILLING))
    assert (after_draw["block_purchased_studies"], after_draw["block_consumed_studies"],
            after_draw["block_remaining_studies"]) == (1, 1, 0)
    assert_block_conservation(after_draw)

    after_top_up = block_purchase(contract_id, 2, expected_contract_version=after_draw["version"])
    assert (after_top_up["block_purchased_studies"], after_top_up["block_consumed_studies"],
            after_top_up["block_remaining_studies"]) == (3, 1, 2)
    assert_block_conservation(after_top_up)

    record_qc_check(scene["equipment"]["id"], scene["technician"]["id"], "FAIL",
                    note="transducer element dropout")

    after_refund = validate_success(api.get_contract(contract_id, BILLING))
    assert (after_refund["block_purchased_studies"], after_refund["block_consumed_studies"],
            after_refund["block_remaining_studies"]) == (3, 0, 3)
    assert_block_conservation(after_refund)


def test_the_block_ledger_records_the_draw_and_the_quality_refund(api):
    """PRD §3.9: "the server appends a block ledger entry naming the `contract_id` and
    the `study_id`, with `delta_studies` of negative 1, a `reason` of `DRAW`, and a
    `balance_after_studies` equal to the contract's remaining balance less one."
    PRD §3.9: "Block ledger entries are append-only historical facts carrying only an
    `id` and a `created_at` — no `updated_at`, no `version` — and the contract's two
    derived counters are always re-derivable by replaying that ledger in `created_at`
    ascending order."
    PRD §3.9: "when a `DRAW` entry exists for that study a matching block ledger entry
    with `delta_studies` of positive 1 and `reason` of `REFUND_QC` is appended,
    restoring the contract's balance."

    Derivation: the draw lands while the balance is 1, so its balance_after_studies is
    0; the refund lands after the top-up has raised the remaining balance to 2, so its
    balance_after_studies is 3.

    Design: Difficulty/compensating_invariant/block_ledger_draw_and_qc_refund_conserve_purchased_studies
    """
    scene = _posted_study_on_a_single_unit_block(api)
    contract_id = scene["contract"]["id"]
    block_purchase(contract_id, 2)
    record_qc_check(scene["equipment"]["id"], scene["technician"]["id"], "FAIL",
                    note="transducer element dropout")

    entries, _meta = validate_paginated(
        api.list_block_ledger_entries(BILLING, params={"contract_id": contract_id})
    )

    assert len(entries) == 2
    draw = next(entry for entry in entries if entry["reason"] == "DRAW")
    refund = next(entry for entry in entries if entry["reason"] == "REFUND_QC")
    assert draw["delta_studies"] == -1
    assert draw["reason"] == "DRAW"
    assert draw["balance_after_studies"] == 0
    assert refund["delta_studies"] == 1
    assert refund["reason"] == "REFUND_QC"
    assert refund["balance_after_studies"] == 3
    assert validate_success(api.get_study(scene["studies"][0]["id"], SCHED))["billing_status"] == "REVERSED"


# --------------------------------------------------------------------------
# Money conservation while one study leaves and the survivor is re-priced
# --------------------------------------------------------------------------
def _two_posted_studies_acquired_on_two_different_units(api):
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Ledger Vet", address_zone="Z20", contract_kind="PER_STUDY_LIST",
        unit_name="Van M", equipment_serial="US-MA", technician_name="Rui Alves",
        body_regions=("ABDOMEN", "THORAX"), acquire=False,
    )
    second_equipment = new_calibrated_equipment(scene["unit"]["id"], "ULTRASOUND", "US-MB")
    specialist = new_specialist("Dr Haddad", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    condemned, survivor = scene["studies"]
    acquire_study(condemned["id"], scene["equipment"]["id"], scene["technician"]["id"], image_count=9)
    acquire_study(survivor["id"], second_equipment["id"], scene["technician"]["id"], image_count=9)
    qc_study(condemned["id"], scene["technician"]["id"], "ACCEPTED")
    qc_study(survivor["id"], scene["technician"]["id"], "ACCEPTED")
    read_and_finalize(condemned["id"], specialist["id"], findings="splenic mass")
    read_and_finalize(survivor["id"], specialist["id"], findings="no thoracic metastasis")
    invoice = open_invoice(scene["clinic"]["id"])
    post_study(invoice["id"], condemned["id"])
    posted = post_study(invoice["id"], survivor["id"])
    scene.update({"second_equipment": second_equipment, "invoice": invoice,
                  "total_before": posted["total_cents"]})
    return scene


def test_the_invoice_total_always_equals_the_sum_of_its_active_lines(api):
    """PRD §2.10: "**Invoice money.** An invoice's `total_cents` equals the sum of
    `amount_cents` over the charge lines whose `invoice_id` is that invoice and whose
    `status` is `ACTIVE`. A `REVERSED` line keeps its `amount_cents` value for audit
    but is excluded from the sum."
    PRD §3.9: "While the invoice is `OPEN` it is re-derived on every read as the plain
    sum of `amount_cents` over that invoice's `ACTIVE` lines, so a cascade reversal
    changes it immediately; it is a sum of already-rounded line amounts and never a
    re-rounding of an unrounded aggregate."

    Derivation: two billable studies at one stop each carry 26000 base plus a 6250
    trip share, and 3 percent of 32250 is 967.5 rounding half up to 968, so each
    totals 33218 and the invoice totals 66436.  Quarantining the unit that acquired
    only the first study reverses its three lines and re-prices the survivor's trip
    share to the whole 12500, whose subtotal 38500 carries an administrative fee of
    exactly 1155 — so the invoice falls to 39655 even though the survivor got dearer.

    Design: Difficulty/compensating_invariant/charge_line_reversal_and_trip_reallocation_conserve_invoice_total
    """
    scene = _two_posted_studies_acquired_on_two_different_units(api)
    assert scene["total_before"] == 66436

    check = record_qc_check(scene["equipment"]["id"], scene["technician"]["id"], "FAIL",
                            note="probe fault on unit A only")

    assert check["affected_study_count"] == 1
    invoice = validate_success(api.get_invoice(scene["invoice"]["id"], BILLING))
    assert invoice["total_cents"] == 39655
    lines, _meta = validate_paginated(
        api.list_charge_lines(BILLING, params={"invoice_id": scene["invoice"]["id"]})
    )
    assert_invoice_total_matches_active_lines(invoice, lines)
    active = [line for line in lines if line["status"] == "ACTIVE"]
    reversed_lines = [line for line in lines if line["status"] == "REVERSED"]
    assert len(active) == 3
    assert len(reversed_lines) == 3
    assert sum(line["amount_cents"] for line in active) == 39655


def test_the_surviving_study_is_re_priced_upwards_while_its_sibling_is_reversed(api):
    """PRD §3.6: "**Hop 4c**, caused by hop 2. The condemned studies leave their stops'
    billable sets, so the trip-fee share is re-allocated across every surviving
    billable sibling at those stops, and each sibling's `ACTIVE` `TRIP_FEE_SHARE` and
    `ADMIN_FEE` charge lines are re-priced in place. The survivors get **more**
    expensive."
    PRD §2.11: "Any implementation that caches a derived value at write time and
    serves the cached copy later will diverge — most visibly on a study's
    `trip_share_cents`, which changes when a *sibling* study at the same stop leaves
    the billable set, an event that touches no field of the study whose price moves."

    Derivation: alone in the billable set the survivor takes the entire 12500 trip
    fee; 3 percent of 26000 + 12500 = 38500 is exactly 1155, so its total rises from
    33218 to 39655.

    Design: Difficulty/compensating_invariant/charge_line_reversal_and_trip_reallocation_conserve_invoice_total
    """
    scene = _two_posted_studies_acquired_on_two_different_units(api)
    condemned, survivor = scene["studies"]

    record_qc_check(scene["equipment"]["id"], scene["technician"]["id"], "FAIL",
                    note="probe fault on unit A only")

    condemned_state = validate_success(api.get_study(condemned["id"], SCHED))
    assert condemned_state["workflow_status"] == "REPEAT_PENDING"
    assert condemned_state["billing_status"] == "REVERSED"
    survivor_state = validate_success(api.get_study(survivor["id"], SCHED))
    assert survivor_state["workflow_status"] == "FINALIZED"
    assert survivor_state["billing_status"] == "POSTED"
    price = validate_success(api.get_study_pricing(survivor["id"], BILLING))
    assert price["trip_share_cents"] == 12500
    assert price["admin_fee_cents"] == 1155
    assert price["total_price_cents"] == 39655
    assert validate_success(api.get_equipment(scene["second_equipment"]["id"], ADMIN))["calibration_status"] == "VALID"


# --------------------------------------------------------------------------
# The finalized-invoice freeze beats the safety recall
# --------------------------------------------------------------------------
def test_a_finalized_invoice_refuses_the_failing_check_outright(api):
    """PRD §2.9: "This bites hardest on cascades: recording an equipment QC check whose
    `result` is `FAIL` is **rejected outright** with `ERR_INVOICE_FINALIZED` when any
    study inside its retroactive blast radius still carries `ACTIVE` charge lines on a
    finalized invoice. A billing freeze therefore blocks a safety action, the freeze
    is absolute, and there is no override path."
    PRD §3.9: "Finalizing the invoice moves it `OPEN → FINALIZED`, snapshots the live
    total into `finalized_total_cents`, stamps `finalized_at`, and thereafter
    `total_cents` simply returns that frozen snapshot."
    PRD §3.6: "Before anything is written, gate G1 is consulted: if any study inside
    the blast radius still carries `ACTIVE` charge lines on an invoice whose `status`
    is `FINALIZED`, the entire failing check is **rejected outright** with
    `ERR_INVOICE_FINALIZED`."

    Derivation: the sole billable study at its stop prices at 26000 + 12500 +
    round_half_up(0.03 x 38500 = 1155) = 39655, which is the total frozen at
    finalization.

    Design: Corner/endpoints/finalizing_an_invoice_freezes_its_total_against_a_later_quarantine
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Freeze Vet", address_zone="E3", contract_kind="PER_STUDY_LIST",
        unit_name="Van FZ", equipment_serial="US-FZ", technician_name="T Freeze",
        acquire=True, qc_result="ACCEPTED", image_count=8,
    )
    specialist = new_specialist("Dr Freeze", ("ULTRASOUND",), ("CANINE",), stat_eligible=False)
    study = scene["studies"][0]
    read_and_finalize(study["id"], specialist["id"], findings="normal")
    invoice = open_invoice(scene["clinic"]["id"])
    posted = post_study(invoice["id"], study["id"])
    assert posted["total_cents"] == 39655
    frozen = finalize_invoice(invoice["id"])
    assert frozen["finalized_total_cents"] == 39655
    assert_same_instant(frozen["finalized_at"], "2026-05-04T08:00:00Z")

    response = api.create_qc_check(
        {
            "equipment_id": scene["equipment"]["id"],
            "performed_by_technician_id": scene["technician"]["id"],
            "result": "FAIL",
            "note": "post-hoc fault",
        },
        make_field_tech_headers(scene["technician"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVOICE_FINALIZED.value)
    invoice_after = validate_success(api.get_invoice(invoice["id"], BILLING))
    assert invoice_after["total_cents"] == 39655
    assert invoice_after["status"] == "FINALIZED"
    equipment_after = validate_success(api.get_equipment(scene["equipment"]["id"], ADMIN))
    assert equipment_after["calibration_status"] == "VALID"
    assert equipment_after["quarantined_at"] is None
    study_after = validate_success(api.get_study(study["id"], SCHED))
    assert study_after["workflow_status"] == "FINALIZED"
    assert study_after["qc_status"] == "ACCEPTED"
    checks, _meta = validate_paginated(
        api.list_qc_checks(SCHED, params={"equipment_id": scene["equipment"]["id"]})
    )
    assert checks == []
