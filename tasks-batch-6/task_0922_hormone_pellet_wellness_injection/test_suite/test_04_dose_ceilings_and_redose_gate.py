"""Rolling exposure, the per-procedure ceiling and the five re-dose factors."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    book_procedure,
    make_physician_headers,
    new_patient,
    new_physician,
    new_standing_order,
    read_patient,
    record_consult,
    record_lab_panel,
    setup_pellet_procedure,
    setup_redose_ready,
    validate_error,
    validate_paginated,
    validate_success,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]

ANCHOR_AT = "2026-05-10T09:00:00Z"
TROUGH_AT = "2026-07-25T09:00:00Z"


def test_therapy_status_reports_both_rolling_variants_side_by_side(api):
    """PRD §3.4: "At booking, the system computes the patient's **including-scheduled**
    exposure for that hormone: the sum of `delivered_total_mg` over the patient's procedures
    of that hormone whose `status` is `COMPLETED` and whose `performed_at` falls within the
    window running from 365 days before now up to now, both ends inclusive, **plus** the sum
    of `planned_total_mg` over the patient's procedures of that hormone whose `status` is
    `SCHEDULED`, `CONSENTED` or `SUPPLY_OPENED` and whose `scheduled_start` falls strictly
    after now and no later than 365 days after now."
    PRD §3.4: "At insertion time the same cap is re-tested against a **completed-only**
    exposure, which drops the forward-looking half entirely and counts only milligrams
    actually in bodies."
    PRD §3.4: "The response reports `patient_id` and `hormone_type` as asked, then
    `rolling_mg_completed_only` and `rolling_mg_including_scheduled` side by side with the
    applicable `rolling_mg_cap`, the `anchor_performed_at` instant the re-dose factors are
    measured from, the five booleans `f1_interval_ok`, `f2_trough_ok`, `f3_freshness_ok`,
    `f4_symptom_ok` and `f5_band_ok`, the conjunction of all five as `redose_eligible`, and
    the patient's current `clinical_hold`, `financial_hold` and `eligibility_status`."

    Design: Difficulty/dual_variant_calc/rolling_mg_forward_vs_completed_on_patient
    """
    ctx = setup_redose_ready(
        api, anchor_performed_at=ANCHOR_AT, anchor_dose_mg=1150,
        trough_drawn_at=TROUGH_AT, follow_up_dose_mg=1150, now=TROUGH_AT,
    )
    book_procedure(
        api, ctx["patient_id"], ctx["physician_id"], ctx["follow_up_consult"]["id"],
        ctx["standing_order_id"], procedure_type="REDOSE", room_code="RM1",
        scheduled_start="2026-08-05T09:00:00Z", lab_panel_id=ctx["trough_panel"]["id"],
    )

    status = validate_success(
        api.get_therapy_status(
            ctx["patient_id"], make_physician_headers(ctx["physician_id"]),
            {"hormone_type": "TESTOSTERONE"},
        ),
        200,
    )

    assert status["rolling_mg_completed_only"] == 1200
    assert status["rolling_mg_including_scheduled"] == 2400, (
        "The forward variant also counts the procedure that is merely booked"
    )
    assert status["rolling_mg_cap"] == 4800
    assert status["patient_id"] == ctx["patient_id"]
    assert status["hormone_type"] == "TESTOSTERONE"


def test_forward_rolling_variant_counts_the_merely_scheduled_procedure(api):
    """PRD §3.4: "The two variants deliberately return different numbers for the same patient
    at the same instant, and the including-scheduled variant can refuse a booking that the
    completed-only variant would happily allow."
    PRD §3.5: "`delivered_total_mg` is recomputed as the sum, over this procedure's allocation
    rows whose status is exactly `CONSUMED`, of `quantity` multiplied by `strength_mg` — rows
    in `OPENED`, `WASTED`, `RELEASED`, `RECALL_RELEASED` or `RECALL_FLAGGED` contribute nothing."

    Design: Difficulty/dual_variant_calc/rolling_mg_forward_vs_completed_on_patient
    """
    ctx = setup_redose_ready(
        api, anchor_performed_at=ANCHOR_AT, anchor_dose_mg=1150,
        trough_drawn_at=TROUGH_AT, follow_up_dose_mg=1150, now=TROUGH_AT,
    )
    booked = book_procedure(
        api, ctx["patient_id"], ctx["physician_id"], ctx["follow_up_consult"]["id"],
        ctx["standing_order_id"], procedure_type="REDOSE", room_code="RM1",
        scheduled_start="2026-08-05T09:00:00Z", lab_panel_id=ctx["trough_panel"]["id"],
    )

    assert ctx["procedure"]["delivered_total_mg"] == 1200
    assert booked["planned_total_mg"] == 1200
    assert booked["status"] == "SCHEDULED"

    status = validate_success(
        api.get_therapy_status(
            ctx["patient_id"], make_physician_headers(ctx["physician_id"]),
            {"hormone_type": "TESTOSTERONE"},
        ),
        200,
    )
    assert (
        status["rolling_mg_including_scheduled"] - status["rolling_mg_completed_only"]
        == booked["planned_total_mg"]
    ), "The forward half is exactly the booked procedure's planned total"


def test_lab_exactly_forty_five_days_old_falls_through_to_the_symptom_factor(api):
    """PRD §2.9: "**Rung 21** — re-dose factor three, laboratory freshness: no more than 45
    days separate the supporting panel's `drawn_at` from now. Applies to
    `POST /clinic/procedures` when `procedure_type` is `REDOSE`. A panel exactly 45 days old
    still supports the decision; 46 days fails and forces a re-draw. Otherwise `ERR_LAB_STALE`
    (422)."
    PRD §2.9: "**Rung 25** — re-dose factor four, symptom burden: the consult's
    `symptom_score` is at least 40. Equality passes. Applies to `POST /clinic/procedures` when
    `procedure_type` is `REDOSE`. Otherwise `ERR_SYMPTOM_SCORE_BELOW_THRESHOLD` (422)."

    Design: Difficulty/priority_pair_validation_conflict/lab_staleness_pre_empts_symptom_score_on_redose
    """
    ctx = setup_redose_ready(
        api, anchor_performed_at=ANCHOR_AT, trough_drawn_at=TROUGH_AT,
        follow_up_symptom_score=30, room_code="RM11", now="2026-09-08T09:00:00Z",
    )

    response = api.create_procedure(
        {
            "patient_id": ctx["patient_id"],
            "provider_id": ctx["physician_id"],
            "consult_id": ctx["follow_up_consult"]["id"],
            "standing_order_id": ctx["standing_order_id"],
            "procedure_type": "REDOSE",
            "room_code": "RM11",
            "scheduled_start": "2026-09-15T09:00:00Z",
            "lab_panel_id": ctx["trough_panel"]["id"],
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_SYMPTOM_SCORE_BELOW_THRESHOLD.value)
    assert response.status_code == 422


def test_lab_forty_six_days_old_reports_lab_stale_ahead_of_the_symptom_factor(api):
    """PRD §2.9: "First, the five re-dose factors are evaluated in the fixed order 21, 22, 23,
    24, 25 — freshness, then trough window, then interval, then band, then symptom score — so
    a request failing several of them hears exactly the lowest-numbered one."
    PRD §2.9: "**Rung 21** — re-dose factor three, laboratory freshness: no more than 45 days
    separate the supporting panel's `drawn_at` from now. Applies to `POST /clinic/procedures`
    when `procedure_type` is `REDOSE`. A panel exactly 45 days old still supports the
    decision; 46 days fails and forces a re-draw. Otherwise `ERR_LAB_STALE` (422)."

    Design: Difficulty/priority_pair_validation_conflict/lab_staleness_pre_empts_symptom_score_on_redose
    """
    ctx = setup_redose_ready(
        api, anchor_performed_at=ANCHOR_AT, trough_drawn_at=TROUGH_AT,
        follow_up_symptom_score=30, room_code="RM11", now="2026-09-09T09:00:00Z",
    )

    response = api.create_procedure(
        {
            "patient_id": ctx["patient_id"],
            "provider_id": ctx["physician_id"],
            "consult_id": ctx["follow_up_consult"]["id"],
            "standing_order_id": ctx["standing_order_id"],
            "procedure_type": "REDOSE",
            "room_code": "RM11",
            "scheduled_start": "2026-09-15T09:00:00Z",
            "lab_panel_id": ctx["trough_panel"]["id"],
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_LAB_STALE.value)
    assert response.status_code == 422

    rows, meta = validate_paginated(
        api.list_procedures(FRONT_DESK, {"consult_id": ctx["follow_up_consult"]["id"]})
    )
    assert meta["total_count"] == 0, "A rejected re-dose booking must not be persisted"


def test_redose_supported_by_a_lab_exactly_forty_five_days_old_is_created(api):
    """PRD §3.4: "Factor three, checked first, is freshness: no more than 45 days may separate
    the panel's `drawn_at` from now, so a panel exactly 45 days old still supports the
    decision while one 46 days old is rejected with `ERR_LAB_STALE`."
    PRD §4: "Requests that bring a new resource into existence answer with HTTP 201 and the
    created resource in `data`; requests that modify, transition or settle an existing
    resource answer with HTTP 200 and the updated resource in `data`; computed reads and list
    reads answer with HTTP 200."

    Design: Difficulty/boundary_precision_check/redose_lab_exactly_forty_five_days_old_still_supports
    """
    ctx = setup_redose_ready(
        api, anchor_performed_at=ANCHOR_AT, trough_drawn_at=TROUGH_AT,
        follow_up_symptom_score=55, room_code="RM12", now="2026-09-08T09:00:00Z",
    )

    response = api.create_procedure(
        {
            "patient_id": ctx["patient_id"],
            "provider_id": ctx["physician_id"],
            "consult_id": ctx["follow_up_consult"]["id"],
            "standing_order_id": ctx["standing_order_id"],
            "procedure_type": "REDOSE",
            "room_code": "RM12",
            "scheduled_start": "2026-09-15T09:00:00Z",
            "lab_panel_id": ctx["trough_panel"]["id"],
        },
        FRONT_DESK,
    )
    booked = validate_success(response, 201)
    assert booked["status"] == "SCHEDULED"
    assert booked["procedure_type"] == "REDOSE"


def test_redose_booking_copies_the_plan_and_leaves_the_cumulative_untouched(api):
    """PRD §3.4: "On success the server copies `hormone_type`, `planned_pellet_count` and
    `planned_total_mg` from the referenced consult onto the procedure, sets `scheduled_end` to
    45 minutes after `scheduled_start`, sets `status` to `SCHEDULED` and `recall_status` to
    `NONE`, and initialises `pellets_allocated`, `pellets_opened`, `pellets_inserted`,
    `pellets_wasted`, `delivered_total_mg`, `charge_cents` and `cancel_fee_cents` all to 0,
    with `consent_record_id`, `cancel_tier`, `performed_at` and `hold_reason` all null."
    PRD §3.5: "the patient's `cumulative_mg_testosterone` or `cumulative_mg_estradiol` rises
    by the delivered total, `last_insertion_at` and `last_insertion_hormone_type` are updated
    to this procedure's values, and both the patient's `version` and the procedure's `version`
    increment by 1."

    Design: Difficulty/boundary_precision_check/redose_lab_exactly_forty_five_days_old_still_supports
    """
    ctx = setup_redose_ready(
        api, anchor_performed_at=ANCHOR_AT, trough_drawn_at=TROUGH_AT,
        follow_up_symptom_score=55, room_code="RM12", now="2026-09-08T09:00:00Z",
    )

    booked = book_procedure(
        api, ctx["patient_id"], ctx["physician_id"], ctx["follow_up_consult"]["id"],
        ctx["standing_order_id"], procedure_type="REDOSE", room_code="RM12",
        scheduled_start="2026-09-15T09:00:00Z", lab_panel_id=ctx["trough_panel"]["id"],
    )

    assert booked["planned_total_mg"] == 1000
    assert booked["hormone_type"] == "TESTOSTERONE"
    assert booked["recall_status"] == "NONE"
    assert booked["pellets_allocated"] == 0
    assert booked["consent_record_id"] is None
    assert booked["performed_at"] is None
    assert_same_instant(booked["scheduled_end"], "2026-09-15T09:45:00Z", "scheduled_end")

    patient = read_patient(api, ctx["patient_id"])
    assert patient["cumulative_mg_testosterone"] == 1000, (
        "Only the completed anchor counts; a booking commits no milligrams"
    )


def test_estradiol_plan_above_the_per_procedure_cap_is_rejected(api):
    """PRD §2.9: "**Rung 19** — `planned_total_mg` is no greater than 2000 mg for a
    testosterone procedure or 150 mg for an estradiol procedure, on `POST /clinic/procedures`.
    Equality passes. Otherwise `ERR_DOSE_CAP_EXCEEDED` (422)."
    PRD §3.4: "The first is per-procedure: `planned_total_mg` may not exceed 2000 mg for a
    testosterone procedure or 150 mg for an estradiol one, with equality passing, and a
    violation answers `ERR_DOSE_CAP_EXCEEDED`."

    Design: Corner/validations/estradiol_dose_above_per_procedure_cap_is_rejected
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner TwentyFour", "c24@example.com", sex_at_birth="FEMALE")
    consult = record_consult(
        api, patient["id"], physician["id"], "ESTRADIOL",
        prescribed_dose_mg=200, indication="Vasomotor",
    )
    order = new_standing_order(
        api, physician["id"], scope_hormone_types=["ESTRADIOL"], max_dose_mg=300
    )

    assert consult["planned_large_count"] == 8
    assert consult["planned_small_count"] == 0
    assert consult["planned_total_mg"] == 200

    response = api.create_procedure(
        {
            "patient_id": patient["id"],
            "provider_id": physician["id"],
            "consult_id": consult["id"],
            "standing_order_id": order["id"],
            "procedure_type": "INITIAL",
            "room_code": "RM48",
            "scheduled_start": "2026-06-15T09:00:00Z",
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_DOSE_CAP_EXCEEDED.value)
    assert response.status_code == 422


def test_rolling_cap_equality_passes_and_ten_more_milligrams_rejects(api):
    """PRD §2.9: "**Rung 20** — the rolling 365-day exposure plus the milligrams this request
    would commit is no greater than 4800 mg for testosterone or 400 mg for estradiol, on
    `POST /clinic/procedures` and `POST /clinic/procedures/{id}/perform`. Equality passes in
    both cases. Otherwise `ERR_ROLLING_MG_CAP_EXCEEDED` (422)."
    PRD §3.4: "That figure plus the milligrams this booking would commit must not exceed
    4800 mg for testosterone or 400 mg for estradiol; equality passes, and a violation answers
    `ERR_ROLLING_MG_CAP_EXCEEDED`."

    Design: Corner/calculations/rolling_mg_cap_equality_passes_and_ten_more_milligrams_rejects
    """
    ctx = setup_pellet_procedure(
        api, target_status="COMPLETED", hormone_type="ESTRADIOL",
        prescribed_dose_mg=150, consented_max_dose_mg=150,
        patient_name="Corner TwentyThree", patient_email="c23@example.com",
        sex_at_birth="FEMALE", room_code="RM47",
        scheduled_start="2026-05-10T09:00:00Z", perform_at="2026-05-10T09:00:00Z",
        lot_specs=[{"lot_code": "E25-A", "strength_mg": 25, "qty_received": 30}],
    )
    assert read_patient(api, ctx["patient_id"])["cumulative_mg_estradiol"] == 150

    def e2_consult(dose):
        return record_consult(
            api, ctx["patient_id"], ctx["physician_id"], "ESTRADIOL",
            prescribed_dose_mg=dose, indication="Vasomotor",
        )["id"]

    book_procedure(
        api, ctx["patient_id"], ctx["physician_id"], e2_consult(150),
        ctx["standing_order_id"], room_code="RM47", scheduled_start="2026-06-01T09:00:00Z",
    )

    on_the_nose = validate_success(
        api.create_procedure(
            {
                "patient_id": ctx["patient_id"],
                "provider_id": ctx["physician_id"],
                "consult_id": e2_consult(100),
                "standing_order_id": ctx["standing_order_id"],
                "procedure_type": "INITIAL",
                "room_code": "RM47",
                "scheduled_start": "2026-06-10T09:00:00Z",
            },
            FRONT_DESK,
        ),
        201,
    )
    assert on_the_nose["planned_total_mg"] == 100
    assert on_the_nose["status"] == "SCHEDULED"

    over = api.create_procedure(
        {
            "patient_id": ctx["patient_id"],
            "provider_id": ctx["physician_id"],
            "consult_id": e2_consult(10),
            "standing_order_id": ctx["standing_order_id"],
            "procedure_type": "INITIAL",
            "room_code": "RM47",
            "scheduled_start": "2026-06-20T09:00:00Z",
        },
        FRONT_DESK,
    )
    validate_error(over, ApiErrorId.ERR_ROLLING_MG_CAP_EXCEEDED.value)
    assert over.status_code == 422


def test_trough_drawn_before_the_window_opens_is_rejected(api):
    """PRD §2.9: "**Rung 22** — re-dose factor two, the trough window: the supporting panel's
    `is_trough_draw` is true and the days between the anchoring insertion and the panel's
    `drawn_at` fall inside the hormone's trough window with both bounds inclusive — 70 through
    98 days for testosterone, 56 through 84 days for estradiol. Applies to
    `POST /clinic/procedures` when `procedure_type` is `REDOSE`. Otherwise
    `ERR_TROUGH_WINDOW_VIOLATION` (422)."

    Design: Corner/validations/trough_panel_drawn_before_the_window_opens_is_rejected
    """
    ctx = setup_redose_ready(
        api, anchor_performed_at=ANCHOR_AT, trough_drawn_at="2026-06-19T09:00:00Z",
        follow_up_symptom_score=55, room_code="RM52", now="2026-06-19T09:00:00Z",
        patient_email="c28@example.com",
    )

    response = api.create_procedure(
        {
            "patient_id": ctx["patient_id"],
            "provider_id": ctx["physician_id"],
            "consult_id": ctx["follow_up_consult"]["id"],
            "standing_order_id": ctx["standing_order_id"],
            "procedure_type": "REDOSE",
            "room_code": "RM52",
            "scheduled_start": "2026-08-05T09:00:00Z",
            "lab_panel_id": ctx["trough_panel"]["id"],
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_TROUGH_WINDOW_VIOLATION.value)
    assert response.status_code == 422

    rows, meta = validate_paginated(
        api.list_procedures(FRONT_DESK, {"consult_id": ctx["follow_up_consult"]["id"]})
    )
    assert meta["total_count"] == 0


def test_redose_with_no_prior_insertion_reports_interval_not_met(api):
    """PRD §2.9: "Second, when the patient has no completed procedure of the relevant hormone
    at all, there is no anchoring insertion for rungs 21 and 22 to measure against; in that
    case rungs 21 and 22 are skipped and the request lands on rung 23, which is what makes
    rung 23's no-prior-insertion condition reachable."
    PRD §2.9: "**Rung 23** — re-dose factor one, the minimum interval: at least 84 days for
    testosterone, or at least 70 days for estradiol, separate the anchoring insertion from the
    requested `scheduled_start`. Equality passes. A patient with no completed procedure of that
    hormone at all also fails here. Applies to `POST /clinic/procedures` when `procedure_type`
    is `REDOSE`. Otherwise `ERR_REDOSE_INTERVAL_NOT_MET` (422)."

    Design: Corner/validations/redose_with_no_prior_insertion_reports_interval_not_met
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner TwentyNine", "c29@example.com")
    consult = record_consult(api, patient["id"], physician["id"], prescribed_dose_mg=1000)
    order = new_standing_order(api, physician["id"])
    panel = record_lab_panel(
        api, patient["id"], physician["id"], analyte="TOTAL_TESTOSTERONE",
        value=400, drawn_at="2026-05-01T00:00:00Z", is_trough_draw=True,
    )

    response = api.create_procedure(
        {
            "patient_id": patient["id"],
            "provider_id": physician["id"],
            "consult_id": consult["id"],
            "standing_order_id": order["id"],
            "procedure_type": "REDOSE",
            "room_code": "RM53",
            "scheduled_start": "2026-06-18T09:00:00Z",
            "lab_panel_id": panel["id"],
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_REDOSE_INTERVAL_NOT_MET.value)
    assert response.status_code == 422

    assert read_patient(api, patient["id"])["last_insertion_at"] is None
