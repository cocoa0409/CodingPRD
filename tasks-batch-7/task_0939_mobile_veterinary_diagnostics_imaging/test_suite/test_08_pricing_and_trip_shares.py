"""How a study is priced: the trip-fee split, the administrative fee and cancellations."""
from test_helpers import (
    TEST_USERS,
    expected_admin_fee_cents,
    expected_trip_share_allocation,
    make_clinic_user_headers,
    new_specialist,
    open_invoice,
    post_study,
    qc_study,
    read_and_finalize,
    set_clock,
    setup_mobile_scene,
    setup_telerad_scene,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# --------------------------------------------------------------------------
# The trip-fee floor plus remainder — difficulty instance
# --------------------------------------------------------------------------
def _three_acquired_studies_at_one_stop(api):
    set_clock("2026-05-04T08:00:00Z")
    return setup_mobile_scene(
        clinic_name="Riverbend Vet", address_zone="Z3", contract_kind="PER_STUDY_LIST",
        unit_name="Van 3", equipment_serial="US-3", technician_name="Ana Ruiz",
        body_regions=("ABDOMEN", "THORAX", "PELVIS"), acquire=True, image_count=6,
        # Distinct creation instants so "earliest-created" is unambiguous.
        study_clock_instants=("2026-05-04T08:00:00Z", "2026-05-04T08:01:00Z",
                              "2026-05-04T08:02:00Z"),
    )


def test_the_trip_fee_is_floored_then_the_leftover_cents_go_to_the_earliest_members(api):
    """PRD §3.9: "Otherwise let the set's size be the divisor: the base share is the
    stop's `trip_fee_cents` divided by that size and rounded **down** to a whole cent,
    and the leftover — the trip fee less the base share multiplied by the size — is
    handed out one extra cent at a time to the earliest-created members. Concretely, a
    stop with three billable studies allocates 4167, 4167 and 4166 cents, never 4167
    three times; the rounding order is pinned this way precisely so that the
    allocation sums to exactly the stop's single 12500-cent trip fee and the
    invoice-money invariant holds."
    PRD §3.3: "is stamped with a `trip_fee_cents` of 12500 — one trip fee per stop, no
    matter how much work happens there"

    Derivation: 12500 // 3 = 4166 with a leftover of 12500 - 3 x 4166 = 2, so the two
    earliest-created studies each get one extra cent: 4167, 4167, 4166 — summing to
    exactly 12500.

    Design: Difficulty/combinatorial_formula/trip_fee_floor_plus_remainder_across_three_studies
    """
    scene = _three_acquired_studies_at_one_stop(api)
    first, second, third = scene["studies"]

    prices = [
        validate_success(api.get_study_pricing(study["id"], BILLING))
        for study in (first, second, third)
    ]

    assert prices[0]["billable_studies_at_stop"] == 3
    assert [price["trip_share_cents"] for price in prices] == expected_trip_share_allocation(12500, 3)
    assert [price["trip_share_cents"] for price in prices] == [4167, 4167, 4166]
    assert sum(price["trip_share_cents"] for price in prices) == 12500


def test_the_one_cent_share_difference_carries_through_to_the_totals(api):
    """PRD §3.9: "Compute `admin_fee_cents`, strictly **after** the trip share is
    allocated: 3 percent of the sum of `base_price_cents`, `trip_share_cents` and
    `stat_surcharge_cents`, rounded half up. That is **one** rounding applied to the
    study's subtotal, not a sum of separately rounded per-component fees."
    PRD §3.9: "`total_price_cents` is the plain sum of `base_price_cents`,
    `trip_share_cents`, `stat_surcharge_cents` and `admin_fee_cents`."

    Derivation: under a per-study-list contract each ultrasound study prices at 26000.
    For the two studies holding 4167 the subtotal is 30167 and 3 percent of that is
    905.01, rounding half up to 905, so the total is 26000 + 4167 + 905 = 31072.  For
    the third, holding 4166, the subtotal is 30166 and 3 percent is 904.98, rounding
    to 905, so the total is 26000 + 4166 + 905 = 31071.

    Design: Difficulty/combinatorial_formula/trip_fee_floor_plus_remainder_across_three_studies
    """
    scene = _three_acquired_studies_at_one_stop(api)
    first, second, third = scene["studies"]

    prices = [
        validate_success(api.get_study_pricing(study["id"], BILLING))
        for study in (first, second, third)
    ]

    assert prices[0]["total_price_cents"] == 31072
    assert prices[1]["total_price_cents"] == 31072
    assert prices[2]["total_price_cents"] == 31071
    assert prices[2]["admin_fee_cents"] == 905
    assert prices[2]["admin_fee_cents"] == expected_admin_fee_cents(26000, 4166, 0)
    assert validate_success(api.get_equipment(scene["equipment"]["id"], ADMIN))["usage_count_since_qc"] == 3


# --------------------------------------------------------------------------
# The administrative fee is computed after the STAT surcharge — difficulty instance
# --------------------------------------------------------------------------
def _sole_acquired_study_at_its_stop(api):
    set_clock("2026-05-04T09:00:00Z")
    return setup_mobile_scene(
        clinic_name="Hillcrest Vet", address_zone="Z5", contract_kind="PER_STUDY_LIST",
        unit_name="Van H", equipment_serial="US-H", technician_name="Lee Park",
        acquire=True, image_count=9,
    )


def test_a_routine_sole_occupant_carries_the_whole_trip_fee_and_a_three_percent_fee(api):
    """PRD §3.9: "Compute `trip_share_cents`. A telerad study's share is structurally 0
    — there is no route stop, no van and no trip to allocate. For a mobile study, form
    the stop's **billable set**: every study whose appointment is bound to that route
    stop, whose `workflow_status` is one of `ACQUIRED`, `ASSIGNED`, `READ_IN_PROGRESS`,
    `PRELIM_REPORTED` or `FINALIZED`, and whose `billing_status` is not
    `NON_BILLABLE`, sorted by `created_at` ascending."
    PRD §3.9: "Compute `stat_surcharge_cents`: 4500 cents when the study's current
    `priority` is `STAT` — whether natively or by upgrade — and 0 otherwise."

    Derivation: the sole billable study at the stop takes the whole 12500 trip fee on
    top of its 26000 list base; 3 percent of 38500 is exactly 1155, so the total is
    26000 + 12500 + 0 + 1155 = 39655.

    Design: Difficulty/combinatorial_formula/admin_fee_evaluated_after_stat_surcharge_not_before
    """
    scene = _sole_acquired_study_at_its_stop(api)
    study = scene["studies"][0]

    price = validate_success(api.get_study_pricing(study["id"], BILLING))

    assert price["stat_surcharge_cents"] == 0
    assert price["trip_share_cents"] == 12500
    assert price["base_price_cents"] == 26000
    assert price["admin_fee_cents"] == 1155
    assert price["total_price_cents"] == 39655


def test_escalation_lifts_the_administrative_fee_because_it_is_taken_after_the_surcharge(api):
    """PRD §3.9: "**How a study is priced.** Six figures make up a study's price and
    their evaluation order is **pinned**, because the dependency looks circular: the
    administrative fee depends on the trip share, the trip share depends on which
    studies at the stop are billable, and billability depends on whether a study was
    cancelled — which is itself priced off the list table rather than off the
    contract's block rate."
    PRD §3.9: "Compute `admin_fee_cents`, strictly **after** the trip share is
    allocated: 3 percent of the sum of `base_price_cents`, `trip_share_cents` and
    `stat_surcharge_cents`, rounded half up."

    Derivation: escalation adds a 4500-cent surcharge, so the subtotal moves from
    38500 to 43000 and the administrative fee from 1155 to 3 percent of 43000 = 1290;
    the total moves 39655 to 26000 + 12500 + 4500 + 1290 = 44290.  Taking the fee
    before the surcharge would have left it at 1155 and the total at 44155.

    Design: Difficulty/combinatorial_formula/admin_fee_evaluated_after_stat_surcharge_not_before
    """
    scene = _sole_acquired_study_at_its_stop(api)
    study = scene["studies"][0]
    before = validate_success(api.get_study_pricing(study["id"], BILLING))
    assert before["admin_fee_cents"] == 1155
    assert before["total_price_cents"] == 39655

    escalated = validate_success(
        api.escalate_stat(study["id"], make_clinic_user_headers(scene["clinic"]["id"]))
    )
    after = validate_success(api.get_study_pricing(study["id"], BILLING))

    assert escalated["priority"] == "STAT"
    assert escalated["priority_source"] == "UPGRADED"
    assert after["stat_surcharge_cents"] == 4500
    assert after["admin_fee_cents"] == 1290
    assert after["admin_fee_cents"] == expected_admin_fee_cents(26000, 12500, 4500)
    assert after["total_price_cents"] == 44290


# --------------------------------------------------------------------------
# Block rate then list price on byte-identical studies — difficulty instance
# --------------------------------------------------------------------------
def _two_finalized_ultrasound_studies_on_a_single_unit_block(api):
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Northside Vet", address_zone="Z1", contract_kind="PREPAID_BLOCK",
        block_purchased_studies=1, unit_name="Van 1", equipment_serial="US-1",
        technician_name="Tam Ito", body_regions=("ABDOMEN", "THORAX"),
        acquire=True, qc_result="ACCEPTED", image_count=10,
    )
    specialist = new_specialist("Dr Reed", ("ULTRASOUND",), ("CANINE",), stat_eligible=True)
    for study in scene["studies"]:
        read_and_finalize(study["id"], specialist["id"], findings="no abnormality detected")
    scene["invoice"] = open_invoice(scene["clinic"]["id"])
    return scene


def test_the_first_study_prices_at_the_block_rate_while_a_unit_remains(api):
    """PRD §3.9: "Otherwise, when the contract's `kind` is `PREPAID_BLOCK` **and** its
    `block_remaining_studies` is greater than 0, `price_basis` is `BLOCK_RATE` and the
    base price is the block rate for the study's modality: 14000 cents for
    radiography, 20000 for ultrasound, 42000 for CT, 27000 for echo."
    PRD §3.1: "A prepaid-block contract tracks `block_purchased_studies` — optionally
    seeded at creation and 0 for a per-study-list contract — alongside two derived
    counters, `block_consumed_studies` and `block_remaining_studies`, with the
    remaining balance initialised at creation to the purchased figure."

    Derivation: with one unit still in the block the ultrasound study prices at the
    block rate 20000; sharing the 12500 trip fee two ways gives 6250, and 3 percent of
    26250 is 787.5, rounding half up to 788, so the total is 27038.

    Design: Difficulty/dual_variant_calc/block_rate_draw_then_list_price_overage_on_identical_studies
    """
    scene = _two_finalized_ultrasound_studies_on_a_single_unit_block(api)
    first_study = scene["studies"][0]

    price = validate_success(api.get_study_pricing(first_study["id"], BILLING))

    assert price["price_basis"] == "BLOCK_RATE"
    assert price["base_price_cents"] == 20000
    assert price["trip_share_cents"] == 6250
    assert price["admin_fee_cents"] == 788
    assert price["total_price_cents"] == 27038


def test_the_second_identical_study_falls_back_to_list_once_the_block_is_empty(api):
    """PRD §3.9: "Otherwise — a per-study-list contract, or a prepaid-block contract
    with nothing left in the block — `price_basis` is `LIST_PRICE` and the base price
    is the list rate for the modality: 18000, 26000, 52000 and 34000 cents
    respectively. The boundary is exact: with one study left in the block the next
    study prices at the block rate, and the study after it, with the block at zero,
    prices at list."
    PRD §3.9: "An ordinary posting creates up to four charge lines against the study,
    each carrying an `invoice_id`, a `study_id`, a `kind`, an `amount_cents` and a
    `status` that begins at `ACTIVE` with a null `reversal_reason`: one line of kind
    `STUDY_READ` for the base price; one of kind `TRIP_FEE_SHARE` when the study's
    `trip_share_cents` is greater than 0; one of kind `STAT_SURCHARGE` when the
    study's `priority` is `STAT`; and one of kind `ADMIN_FEE`."
    PRD §2.10: "An invoice's `total_cents` equals the sum of `amount_cents` over the
    charge lines whose `invoice_id` is that invoice and whose `status` is `ACTIVE`."

    Derivation: the first posting draws the last block unit, so the second study finds
    the block at zero and prices at list 26000; its trip share is still 6250 and 3
    percent of 32250 is 967.5, rounding half up to 968, for a total of 33218.  The
    invoice therefore totals 27038 + 33218 = 60256.

    Design: Difficulty/dual_variant_calc/block_rate_draw_then_list_price_overage_on_identical_studies
    """
    scene = _two_finalized_ultrasound_studies_on_a_single_unit_block(api)
    first_study, second_study = scene["studies"]
    invoice = scene["invoice"]

    post_study(invoice["id"], first_study["id"])
    post_study(invoice["id"], second_study["id"])

    first_lines, _m1 = validate_paginated(
        api.list_charge_lines(BILLING, params={"study_id": first_study["id"]})
    )
    second_lines, _m2 = validate_paginated(
        api.list_charge_lines(BILLING, params={"study_id": second_study["id"]})
    )
    by_kind_first = {line["kind"]: line["amount_cents"] for line in first_lines}
    by_kind_second = {line["kind"]: line["amount_cents"] for line in second_lines}

    assert by_kind_first["STUDY_READ"] == 20000
    assert by_kind_first["TRIP_FEE_SHARE"] == 6250
    assert by_kind_first["ADMIN_FEE"] == 788
    assert by_kind_second["STUDY_READ"] == 26000
    assert by_kind_second["TRIP_FEE_SHARE"] == 6250
    assert by_kind_second["ADMIN_FEE"] == 968
    assert validate_success(api.get_invoice(invoice["id"], BILLING))["total_cents"] == 60256


# --------------------------------------------------------------------------
# Removing work from a stop makes the surviving work more expensive
# --------------------------------------------------------------------------
def test_the_survivors_trip_share_rises_when_a_sibling_leaves_the_billable_set(api):
    """PRD §3.9: "The trip-fee split is where this system's pricing stops being
    monotone. Two billable studies at a stop each carry 6250 cents of trip share. Take
    one of them out of the billable set — the reachable way is an image-QC verdict of
    `REPEAT_REQUIRED`, which moves it to `REPEAT_PENDING` — and the survivor's share
    **rises** to 12500, carrying its administrative fee and its `total_price_cents` up
    with it."
    PRD §3.5: "A `REPEAT_REQUIRED` verdict moves the quality axis `PENDING_QC →
    REPEAT_REQUIRED`; a `NON_DIAGNOSTIC` verdict moves it `PENDING_QC →
    NON_DIAGNOSTIC`, which is terminal on that axis. Both of the latter two also move
    the workflow axis `ACQUIRED → REPEAT_PENDING`"

    Derivation: before the verdict each of the two billable studies carries 6250 and
    totals 26000 + 6250 + round_half_up(0.03 x 32250 = 967.5) = 33218.  After the
    verdict the survivor is alone in the set, so it carries the whole 12500 and totals
    26000 + 12500 + round_half_up(0.03 x 38500 = 1155) = 39655.

    Design: Corner/calculations/trip_share_rises_for_the_survivor_when_a_sibling_leaves_the_billable_set
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Monotone Vet", address_zone="ZM", contract_kind="PER_STUDY_LIST",
        unit_name="Van Mono", equipment_serial="US-MONO", technician_name="Noa Feld",
        body_regions=("ABDOMEN", "THORAX"), acquire=True, image_count=7,
    )
    survivor, leaver = scene["studies"]

    before = validate_success(api.get_study_pricing(survivor["id"], BILLING))
    assert before["billable_studies_at_stop"] == 2
    assert before["trip_share_cents"] == 6250
    assert before["total_price_cents"] == 33218

    qc_study(leaver["id"], scene["technician"]["id"], "REPEAT_REQUIRED")

    after = validate_success(api.get_study_pricing(survivor["id"], BILLING))
    assert after["billable_studies_at_stop"] == 1
    assert after["trip_share_cents"] == 12500
    assert after["admin_fee_cents"] == 1155
    assert after["total_price_cents"] == 39655

    departed = validate_success(api.get_study_pricing(leaver["id"], BILLING))
    assert departed["trip_share_cents"] == 0
    leaver_state = validate_success(api.get_study(leaver["id"], SCHED))
    assert leaver_state["workflow_status"] == "REPEAT_PENDING"
    assert leaver_state["qc_status"] == "REPEAT_REQUIRED"


def test_a_stop_whose_billable_set_empties_allocates_no_trip_fee_at_all(api):
    """PRD §3.9: "If that set is empty, no trip fee is billed at all and the share is
    0; if the study being priced is not itself in the set, its share is 0."
    PRD §3.5: "a `NON_DIAGNOSTIC` verdict moves it `PENDING_QC → NON_DIAGNOSTIC`,
    which is terminal on that axis. Both of the latter two also move the workflow axis
    `ACQUIRED → REPEAT_PENDING` and append a notification of kind
    `STUDY_REPEAT_REQUIRED` for the clinic, and both refresh the appointment's
    disposition counters."

    Design: Corner/calculations/stop_with_zero_billable_studies_allocates_no_trip_fee_at_all
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Empty Set Vet", address_zone="ZV", contract_kind="PER_STUDY_LIST",
        unit_name="Van V", equipment_serial="US-V", technician_name="Uma Vale",
        acquire=True, image_count=4,
    )
    study = scene["studies"][0]

    before = validate_success(api.get_study_pricing(study["id"], BILLING))
    assert before["billable_studies_at_stop"] == 1
    assert before["trip_share_cents"] == 12500

    qc_study(study["id"], scene["technician"]["id"], "NON_DIAGNOSTIC")

    after = validate_success(api.get_study_pricing(study["id"], BILLING))
    assert after["billable_studies_at_stop"] == 0
    assert after["trip_share_cents"] == 0
    state = validate_success(api.get_study(study["id"], SCHED))
    assert state["qc_status"] == "NON_DIAGNOSTIC"
    assert state["workflow_status"] == "REPEAT_PENDING"
    rows, _meta = validate_paginated(api.list_charge_lines(BILLING, params={"study_id": study["id"]}))
    assert rows == []


def test_a_telerad_study_never_carries_a_trip_share(api):
    """PRD §3.9: "A telerad study's share is structurally 0 — there is no route stop,
    no van and no trip to allocate."
    PRD §3.5: "Upload moves the study `ORDERED → ACQUIRED`, stamps `acquired_at` and
    records `image_count`, and leaves `equipment_id` and `technician_id` null — this
    edge skips every route, van, equipment and technician hop in the system."

    Derivation: with no trip share the ultrasound base of 26000 is the whole subtotal,
    and 3 percent of 26000 is exactly 780, so the total is 26780.

    Design: Corner/calculations/telerad_study_never_carries_a_trip_share
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Pure Telerad Vet", address_zone="ZTR",
        contract_kind="PER_STUDY_LIST", qc_result=None, image_count=18,
    )
    study = scene["studies"][0]

    price = validate_success(api.get_study_pricing(study["id"], BILLING))

    assert price["trip_share_cents"] == 0
    assert price["base_price_cents"] == 26000
    assert price["admin_fee_cents"] == 780
    assert price["total_price_cents"] == 26780
    assert validate_success(api.get_appointment(scene["appointment"]["id"], SCHED))["route_stop_id"] is None
    state = validate_success(api.get_study(study["id"], SCHED))
    assert state["equipment_id"] is None
    assert state["technician_id"] is None


# --------------------------------------------------------------------------
# What a cancellation costs
# --------------------------------------------------------------------------
def _three_ordered_studies_at_a_published_friday_stop(api):
    set_clock("2026-05-06T09:00:00Z")
    return setup_mobile_scene(
        clinic_name="Leadtime Vet", address_zone="ZN", contract_kind="PER_STUDY_LIST",
        unit_name="Van N", technician_name="Val Ortiz", equipment_serial="US-N",
        service_date="2026-05-08", planned_arrival_minute=540,
        body_regions=("ABDOMEN", "THORAX", "PELVIS"),
        publish=True, dispatch=False, arrive=False,
    )


def test_the_cancellation_lead_time_tiers_are_free_half_and_full(api):
    """PRD §3.9: "Otherwise, take the stop's scheduled arrival instant to be midnight
    UTC on the route's `service_date` advanced by the stop's `planned_arrival_minute`,
    and take the **lead** to be the wall minutes from the logical clock's current
    value to that arrival instant."
    PRD §3.9: "Otherwise, when the lead is at least 1440 minutes — a full day — the
    fee is 0."
    PRD §3.9: "Otherwise, when the lead is at least 240 minutes, the fee is 50 percent
    of list, rounded half up."
    PRD §3.9: "Otherwise the fee is 100 percent of list."
    PRD §3.9: "Boundaries are inclusive on the at-least side: a lead of exactly 1440
    minutes is free, and a lead of 1439 minutes costs half."

    Derivation: the stop arrives at midnight UTC on 2026-05-08 plus 540 minutes, that
    is 2026-05-08T09:00:00Z.  Cancelling at 2026-05-07T09:00:00Z leaves a lead of
    exactly 1440 minutes, so the fee is 0.  One minute later the lead is 1439, so the
    fee is half of the 26000 ultrasound list price, that is 13000.  At
    2026-05-08T05:01:00Z the lead is 239 minutes, below the 240 tier, so the fee is
    the whole 26000.

    Design: Corner/calculations/cancellation_fee_lead_time_tiers_free_half_and_full
    """
    scene = _three_ordered_studies_at_a_published_friday_stop(api)
    clinic_headers = make_clinic_user_headers(scene["clinic"]["id"])
    free_study, half_study, full_study = scene["studies"]

    set_clock("2026-05-07T09:00:00Z")
    free_result = validate_success(
        api.cancel_study(free_study["id"], {"cancel_reason": "owner rescheduled early"}, clinic_headers)
    )
    set_clock("2026-05-07T09:01:00Z")
    half_result = validate_success(
        api.cancel_study(half_study["id"], {"cancel_reason": "owner rescheduled one minute late"},
                         clinic_headers)
    )
    set_clock("2026-05-08T05:01:00Z")
    full_result = validate_success(
        api.cancel_study(full_study["id"], {"cancel_reason": "same-morning cancellation"}, clinic_headers)
    )

    assert free_result["cancellation_fee_cents"] == 0
    assert half_result["cancellation_fee_cents"] == 13000
    assert full_result["cancellation_fee_cents"] == 26000


def test_a_zero_fee_cancellation_is_non_billable_while_a_positive_fee_stays_unbilled(api):
    """PRD §3.9: "The fee is computed by the rules above and stored on
    `cancellation_fee_cents`; the study moves `ORDERED → CANCELLED`; its
    `billing_status` is set to `NON_BILLABLE` when the computed fee is 0, and is
    **left at `UNBILLED` when the fee is positive**, so that the fee can later be
    posted as a cancellation charge line."
    PRD §3.4: "`cancelled_studies_count` counts those in `CANCELLED`."

    Design: Corner/calculations/cancellation_fee_lead_time_tiers_free_half_and_full
    """
    scene = _three_ordered_studies_at_a_published_friday_stop(api)
    clinic_headers = make_clinic_user_headers(scene["clinic"]["id"])
    free_study, half_study, full_study = scene["studies"]

    set_clock("2026-05-07T09:00:00Z")
    free_result = validate_success(
        api.cancel_study(free_study["id"], {"cancel_reason": "owner rescheduled early"}, clinic_headers)
    )
    set_clock("2026-05-07T09:01:00Z")
    half_result = validate_success(
        api.cancel_study(half_study["id"], {"cancel_reason": "owner rescheduled one minute late"},
                         clinic_headers)
    )
    set_clock("2026-05-08T05:01:00Z")
    full_result = validate_success(
        api.cancel_study(full_study["id"], {"cancel_reason": "same-morning cancellation"}, clinic_headers)
    )

    assert free_result["billing_status"] == "NON_BILLABLE"
    assert half_result["billing_status"] == "UNBILLED"
    assert full_result["billing_status"] == "UNBILLED"
    appointment = validate_success(api.get_appointment(scene["appointment"]["id"], SCHED))
    assert appointment["cancelled_studies_count"] == 3
    assert appointment["ordered_studies_count"] == 3


def test_a_cancellation_is_priced_off_the_list_table_even_under_a_prepaid_block(api):
    """PRD §3.9: "It is priced off the **list** table, always, never off a contract's
    block rate, because a cancelled study draws no block unit: radiography 18000
    cents, ultrasound 26000, CT 52000, echo 34000."
    PRD §3.9: "Posting is also where a prepaid block is drawn down."

    Derivation: the clinic holds a prepaid block with 2 units still available, yet the
    239-minute-lead cancellation of an ultrasound study is billed the 26000 list price
    rather than the 20000 block rate, and no block ledger entry is written.

    Design: Corner/calculations/cancellation_fee_uses_list_price_even_under_a_prepaid_block_contract
    """
    set_clock("2026-05-06T09:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Blocked Cancel Vet", address_zone="ZZ", contract_kind="PREPAID_BLOCK",
        block_purchased_studies=2, unit_name="Van Z", technician_name="Zed Rao",
        equipment_serial="US-Z", service_date="2026-05-08", planned_arrival_minute=540,
        publish=True, dispatch=False, arrive=False,
    )
    study = scene["studies"][0]

    set_clock("2026-05-08T05:01:00Z")
    cancelled = validate_success(
        api.cancel_study(study["id"], {"cancel_reason": "owner did not travel"},
                         make_clinic_user_headers(scene["clinic"]["id"]))
    )

    assert cancelled["cancellation_fee_cents"] == 26000
    contract = validate_success(api.get_contract(scene["contract"]["id"], BILLING))
    assert contract["block_remaining_studies"] == 2
    assert contract["block_consumed_studies"] == 0
    rows, _meta = validate_paginated(
        api.list_block_ledger_entries(BILLING, params={"contract_id": scene["contract"]["id"]})
    )
    assert rows == []
