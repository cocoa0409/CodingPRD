"""The insertion itself: rounding order, the facility-fee waiver, and breakage."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_lot_buckets,
    assert_same_instant,
    attach_consent_to,
    book_procedure,
    make_physician_headers,
    new_membership,
    new_patient,
    new_physician,
    new_standing_order,
    open_supply_for,
    patient_version,
    perform_for,
    procedure_allocations,
    publish_protocol,
    read_lot,
    read_patient,
    read_procedure,
    receive_and_release_lot,
    record_consult,
    record_lab_panel,
    run_allocation_for,
    set_clock,
    setup_pellet_procedure,
    setup_redose_ready,
    sign_consent,
    validate_error,
    validate_success,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
PERFORM_AT = "2026-05-20T10:00:00Z"


def test_pellet_lines_are_rounded_per_line_before_they_are_summed(api):
    """PRD §3.5: "Each line's cents figure is the line's pellet count multiplied by that
    strength in milligrams multiplied by the hormone's price per milligram — 21.5 cents per
    milligram for testosterone, 176.25 cents per milligram for estradiol — with the result
    rounded half up to whole cents **per line**. The pellet subtotal is the sum of the rounded
    lines, and the procedure subtotal is a fixed insertion base fee of 25000 cents plus that
    pellet subtotal."
    PRD §3.5: "Rounding order here is load-bearing and must not be rearranged: an estradiol
    procedure that consumed three 25 mg pellets and one 10 mg pellet produces a first line of
    13218.75 cents rounding to 13219 and a second line of 1762.5 cents rounding to 1763,
    summing to 14982 — whereas summing the raw products first and rounding once would give
    14981, which is wrong."

    Design: Difficulty/combinatorial_formula/pellet_charge_round_per_line_then_sum_mode_b
    """
    ctx = setup_pellet_procedure(
        api, target_status="COMPLETED", hormone_type="ESTRADIOL",
        prescribed_dose_mg=80, consented_max_dose_mg=150,
        patient_name="Pat Five", patient_email="p5@example.com", sex_at_birth="FEMALE",
        room_code="RM3", scheduled_start=PERFORM_AT, perform_at=PERFORM_AT,
        lot_specs=[
            {"lot_code": "E25-A", "strength_mg": 25, "qty_received": 10},
            {"lot_code": "E10-A", "strength_mg": 10, "qty_received": 10},
        ],
    )

    procedure = ctx["procedure"]
    assert procedure["pellets_inserted"] == 4
    assert procedure["delivered_total_mg"] == 85
    assert procedure["charge_cents"] == 47482


def test_estradiol_eighty_five_milligram_insertion_charges_47482_not_47481(api):
    """PRD §3.5: "Rounding order here is load-bearing and must not be rearranged: an estradiol
    procedure that consumed three 25 mg pellets and one 10 mg pellet produces a first line of
    13218.75 cents rounding to 13219 and a second line of 1762.5 cents rounding to 1763,
    summing to 14982 — whereas summing the raw products first and rounding once would give
    14981, which is wrong."
    PRD §3.5: "`delivered_total_mg` is recomputed as the sum, over this procedure's allocation
    rows whose status is exactly `CONSUMED`, of `quantity` multiplied by `strength_mg` — rows
    in `OPENED`, `WASTED`, `RELEASED`, `RECALL_RELEASED` or `RECALL_FLAGGED` contribute
    nothing."

    Design: Difficulty/combinatorial_formula/pellet_charge_round_per_line_then_sum_mode_b
    """
    ctx = setup_pellet_procedure(
        api, target_status="COMPLETED", hormone_type="ESTRADIOL",
        prescribed_dose_mg=80, consented_max_dose_mg=150,
        patient_name="Pat Five", patient_email="p5@example.com", sex_at_birth="FEMALE",
        room_code="RM3", scheduled_start=PERFORM_AT, perform_at=PERFORM_AT,
        lot_specs=[
            {"lot_code": "E25-A", "strength_mg": 25, "qty_received": 10},
            {"lot_code": "E10-A", "strength_mg": 10, "qty_received": 10},
        ],
    )

    assert ctx["procedure"]["charge_cents"] != 47481, (
        "Summing the raw products before rounding once would give 47481"
    )
    assert ctx["procedure"]["charge_cents"] == 47482

    rows = procedure_allocations(api, ctx["procedure_id"])
    assert {row["status"] for row in rows} == {"CONSUMED"}
    assert sum(row["quantity"] * row["strength_mg"] for row in rows) == 85

    assert_lot_buckets(
        read_lot(api, ctx["lots"]["E25-A"]["id"]),
        on_hand=7, reserved=0, consumed=3, wasted=0, returned=0,
    )
    assert_lot_buckets(
        read_lot(api, ctx["lots"]["E10-A"]["id"]),
        on_hand=9, reserved=0, consumed=1, wasted=0, returned=0,
    )


def test_non_member_estradiol_100mg_insertion_wins_the_waiver_on_the_boundary(api):
    """PRD §3.5: "Fifth, decide the facility fee: it is zero when the **discounted** subtotal
    is greater than or equal to 42625 cents, and 7500 cents otherwise. Sixth, `charge_cents`
    is the discounted subtotal plus the facility fee."
    PRD §3.5: "An estradiol procedure delivering 100 mg has a subtotal of exactly 42625 cents;
    with no membership the waiver is granted precisely on the boundary and the total is 42625,
    while a `PLUS` member's ten-percent discount of 4262.5 rounds to 4263, drops the
    discounted subtotal to 38362, loses the waiver, and totals 45862."

    Design: Difficulty/combinatorial_formula/facility_fee_waiver_reads_post_discount_subtotal_mode_c
    """
    ctx = setup_pellet_procedure(
        api, target_status="COMPLETED", hormone_type="ESTRADIOL",
        prescribed_dose_mg=100, consented_max_dose_mg=150,
        patient_name="Pat Six", patient_email="p6@example.com", sex_at_birth="FEMALE",
        room_code="RM4", scheduled_start=PERFORM_AT, perform_at=PERFORM_AT,
        lot_specs=[{"lot_code": "E25-A", "strength_mg": 25, "qty_received": 20}],
    )

    assert ctx["procedure"]["delivered_total_mg"] == 100
    assert ctx["procedure"]["charge_cents"] == 42625


def test_plus_member_discount_costs_the_waiver_and_raises_the_total(api):
    """PRD §3.5: "**Stage two, the discount and the facility fee**, evaluated in exactly this
    order. First take the procedure subtotal from stage one. Second, determine the discount
    rate: it is the membership's `discount_pct` when the procedure names a `membership_id` and
    that membership's `status` is `ACTIVE` at the moment of insertion, and zero otherwise.
    Third, compute the discount amount as the subtotal multiplied by that rate, rounded half
    up to whole cents — this is the only rounding step in stage two. Fourth, subtract the
    discount amount from the subtotal to get the discounted subtotal. Fifth, decide the
    facility fee: it is zero when the **discounted** subtotal is greater than or equal to
    42625 cents, and 7500 cents otherwise. Sixth, `charge_cents` is the discounted subtotal
    plus the facility fee."
    PRD §3.5: "It also produces a consequence the implementation must reproduce rather than
    smooth over: a discount can cost a patient the waiver and leave them paying more overall."

    Design: Difficulty/combinatorial_formula/facility_fee_waiver_reads_post_discount_subtotal_mode_c
    """
    first_physician = new_physician(api)
    second_physician = new_physician(api, "Dr Ben Sato", "1000000002")
    plain = new_patient(api, "Pat Six", "p6@example.com", sex_at_birth="FEMALE")
    member = new_patient(api, "Pat Seven", "p7@example.com", sex_at_birth="FEMALE",
                         date_of_birth="1971-05-05")
    membership = new_membership(api, member["id"], "PLUS")

    publish_protocol(api, first_physician["id"], "ESTRADIOL", "E2 pellet protocol v1")
    plain_consent = sign_consent(api, plain["id"], "ESTRADIOL", 1, 150)
    member_consent = sign_consent(api, member["id"], "ESTRADIOL", 1, 150)
    plain_consult = record_consult(
        api, plain["id"], first_physician["id"], "ESTRADIOL",
        prescribed_dose_mg=100, indication="Vasomotor",
    )
    member_consult = record_consult(
        api, member["id"], first_physician["id"], "ESTRADIOL",
        prescribed_dose_mg=100, indication="Vasomotor",
    )
    order = new_standing_order(api, first_physician["id"])
    receive_and_release_lot(
        api, "E25-A", hormone_type="ESTRADIOL", strength_mg=25, qty_received=20
    )

    plain_procedure = book_procedure(
        api, plain["id"], first_physician["id"], plain_consult["id"], order["id"],
        room_code="RM4", scheduled_start=PERFORM_AT,
    )
    member_procedure = book_procedure(
        api, member["id"], second_physician["id"], member_consult["id"], order["id"],
        room_code="RM5", scheduled_start=PERFORM_AT, membership_id=membership["id"],
    )
    for procedure, consent in (
        (plain_procedure, plain_consent), (member_procedure, member_consent)
    ):
        attach_consent_to(api, procedure["id"], consent["id"])
        run_allocation_for(api, procedure["id"])
    open_supply_for(api, plain_procedure["id"], first_physician["id"])
    open_supply_for(api, member_procedure["id"], second_physician["id"])

    set_clock(api, PERFORM_AT)
    plain_done = perform_for(api, plain_procedure["id"], plain["id"], first_physician["id"])
    member_done = perform_for(api, member_procedure["id"], member["id"], second_physician["id"])

    assert plain_done["delivered_total_mg"] == 100
    assert plain_done["charge_cents"] == 42625
    assert member_done["delivered_total_mg"] == 100
    assert member_done["charge_cents"] == 45862
    assert member_done["charge_cents"] > plain_done["charge_cents"], (
        "The ten-percent discount loses the waiver and the member pays more"
    )


def test_partial_wastage_splits_the_row_and_lowers_the_delivered_total(api):
    """PRD §3.5: "Wastage is taken from the **highest** `allocation_rank` downward. Because
    ranks were assigned in earliest-expiry order, walking downward means the earliest-expiring
    lot is consumed and the breakage lands on the latest-expiring lot. Rows are walked from
    the top rank toward rank 1, taking pellets as waste until the requested `pellets_wasted`
    is satisfied; every remaining pellet moves to `CONSUMED`. When the wastage boundary falls
    part-way through a row, that row is **split**: the original row keeps its `id`, keeps its
    `allocation_rank`, and takes the consumed remainder as its `quantity` with status
    `CONSUMED`, while a new allocation row is created against the same `procedure_id`, the
    same `lot_id`, the same `strength_mg` and the same `allocation_rank`, carrying the wasted
    quantity with status `WASTED`."
    PRD §3.5: "For every lot touched, `qty_reserved` decreases by that lot's opened quantity
    while `qty_consumed` rises by its consumed share and `qty_wasted` by its wasted share, so
    the pellet conservation identity survives the split intact."

    Design: Corner/calculations/partial_wastage_splits_the_allocation_row_and_lowers_delivered_mg
    """
    ctx = setup_pellet_procedure(
        api, target_status="COMPLETED", prescribed_dose_mg=1150,
        patient_name="Corner Twenty", patient_email="c20@example.com",
        room_code="RM45", scheduled_start="2026-05-10T09:00:00Z",
        perform_at="2026-05-10T09:00:00Z", pellets_wasted=1,
    )

    procedure = ctx["procedure"]
    assert procedure["pellets_allocated"] == 7
    assert procedure["pellets_inserted"] == 6
    assert procedure["pellets_wasted"] == 1
    assert procedure["delivered_total_mg"] == 1100
    assert procedure["charge_cents"] == 48650
    assert read_patient(api, ctx["patient_id"])["cumulative_mg_testosterone"] == 1100

    assert_lot_buckets(
        read_lot(api, ctx["lots"]["T200-A"]["id"]),
        on_hand=15, reserved=0, consumed=5, wasted=0, returned=0,
    )
    assert_lot_buckets(
        read_lot(api, ctx["lots"]["T100-B"]["id"]),
        on_hand=18, reserved=0, consumed=1, wasted=1, returned=0,
    )

    rows = procedure_allocations(api, ctx["procedure_id"])
    assert len(rows) == 3, f"The straddled row splits into two, giving three rows: {rows}"
    shapes = sorted(
        (row["status"], row["quantity"], row["allocation_rank"]) for row in rows
    )
    assert shapes == [("CONSUMED", 1, 2), ("CONSUMED", 5, 1), ("WASTED", 1, 2)]


def test_critical_lab_blocks_the_insertion_and_the_safety_ceiling_blocks_it_again(api):
    """PRD §2.9: "**Rung 15** — the patient holds no `LabPanel` in status `CRITICAL_FLAGGED`,
    on `POST /clinic/procedures/{id}/perform` and `POST /clinic/injection-visits/{id}/administer`.
    Acknowledging the panel clears the block; recording a newer panel does not, because
    critically flagged panels are never superseded. Otherwise
    `ERR_CRITICAL_LAB_UNACKNOWLEDGED` (409)."
    PRD §2.9: "**Rung 18** — the patient's most recent non-superseded `HEMATOCRIT` panel has a
    `value` no greater than 52.0 percent, on `POST /clinic/procedures` and
    `POST /clinic/procedures/{id}/perform`. A patient with no hematocrit panel at all passes
    this rung. Otherwise `ERR_SAFETY_CEILING_EXCEEDED` (422)."
    PRD §3.3: "Acknowledgement moves the panel `CRITICAL_FLAGGED → ACKNOWLEDGED`, writes the
    acting physician's identity into `acknowledged_by_provider_id`, and increments the panel's
    `version` by 1."

    Design: Corner/validations/critical_lab_blocks_perform_then_safety_ceiling_blocks_it_again
    """
    ctx = setup_pellet_procedure(
        api, target_status="SUPPLY_OPENED", prescribed_dose_mg=1000,
        patient_name="Corner TwentySeven", patient_email="c27@example.com",
        room_code="RM51", scheduled_start="2026-05-10T09:00:00Z",
        lot_specs=[{"lot_code": "T200-A", "strength_mg": 200, "qty_received": 10}],
    )
    set_clock(api, "2026-05-10T09:00:00Z")
    panel = record_lab_panel(
        api, ctx["patient_id"], ctx["physician_id"], analyte="HEMATOCRIT",
        value=55.0, drawn_at="2026-05-10T08:00:00Z",
    )
    assert panel["critical_flag"] is True
    assert panel["lab_reference_band"] == "ABOVE_REF"
    assert panel["clinic_optimal_band"] == "ABOVE_OPTIMAL"

    observed_version = patient_version(api, ctx["patient_id"])
    physician_headers = make_physician_headers(ctx["physician_id"])

    blocked = api.perform_procedure(
        ctx["procedure_id"],
        {"expected_patient_version": observed_version, "pellets_wasted": 0},
        physician_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_CRITICAL_LAB_UNACKNOWLEDGED.value)
    assert blocked.status_code == 409

    acknowledged = validate_success(
        api.acknowledge_critical_lab(
            panel["id"], {"note": "Phlebotomy repeat ordered"}, physician_headers
        ),
        200,
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_provider_id"] == ctx["physician_id"]

    still_blocked = api.perform_procedure(
        ctx["procedure_id"],
        {"expected_patient_version": observed_version, "pellets_wasted": 0},
        physician_headers,
    )
    validate_error(still_blocked, ApiErrorId.ERR_SAFETY_CEILING_EXCEEDED.value)
    assert still_blocked.status_code == 422

    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "SUPPLY_OPENED"
    assert procedure["delivered_total_mg"] == 0


def test_therapy_status_reports_every_redose_factor_flag(api):
    """PRD §3.4: "The response reports `patient_id` and `hormone_type` as asked, then
    `rolling_mg_completed_only` and `rolling_mg_including_scheduled` side by side with the
    applicable `rolling_mg_cap`, the `anchor_performed_at` instant the re-dose factors are
    measured from, the five booleans `f1_interval_ok`, `f2_trough_ok`, `f3_freshness_ok`,
    `f4_symptom_ok` and `f5_band_ok`, the conjunction of all five as `redose_eligible`, and
    the patient's current `clinical_hold`, `financial_hold` and `eligibility_status`."
    PRD §3.4: "A patient is eligible for a re-dose only when all five factors hold at once."

    Design: Corner/endpoints/therapy_status_reports_every_redose_factor_flag
    """
    ctx = setup_redose_ready(
        api, anchor_performed_at="2026-05-10T09:00:00Z",
        trough_drawn_at="2026-07-25T09:00:00Z", follow_up_symptom_score=55,
        room_code="RM58", now="2026-07-25T09:00:00Z", patient_email="c36@example.com",
    )

    status = validate_success(
        api.get_therapy_status(
            ctx["patient_id"], FRONT_DESK,
            {
                "hormone_type": "TESTOSTERONE",
                "consult_id": ctx["follow_up_consult"]["id"],
                "lab_panel_id": ctx["trough_panel"]["id"],
                "scheduled_start": "2026-08-05T09:00:00Z",
            },
        ),
        200,
    )

    assert_same_instant(
        status["anchor_performed_at"], "2026-05-10T09:00:00Z", "anchor_performed_at"
    )
    assert status["f1_interval_ok"] is True
    assert status["f2_trough_ok"] is True
    assert status["f3_freshness_ok"] is True
    assert status["f4_symptom_ok"] is True
    assert status["f5_band_ok"] is True
    assert status["redose_eligible"] is True
    assert status["eligibility_status"] == "CLEAR"
    assert status["clinical_hold"] is False
    assert status["financial_hold"] is False
    assert status["rolling_mg_completed_only"] == 1000
