"""BMP credits and their inspections: provisional vs inspected scoring, the
PASS self-loop, the FAIL revocation cascade, the active-credit precondition,
coverage-window overlap, range validation, and double-completion."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_bmp_credit_payload, create_inspection_payload, complete_inspection_payload,
    create_active_parcel, setup_parcel_with_credit, setup_scheduled_inspection,
)

ASSESSOR = TEST_USERS["assessor_headers"]
CREDIT_INSPECTOR = TEST_USERS["credit_inspector_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]


def test_credit_provisional_pct_before_inspection(api):
    """PRD §3.4: "Its provisional `credit_pct` is derived from the self-reported
    score: the score is divided by 100 to yield a fraction, that fraction is
    multiplied by the credit scale of 0.60, and the result is capped at the
    maximum credit of 0.50 — that is, the provisional credit fraction is the
    smaller of 0.50 and six-tenths of the score expressed as a fraction of 100."

    Design: Difficulty/dual_variant_calc/credit_provisional_vs_inspected_diverge_on_bmpcredit
    """
    base = setup_parcel_with_credit(api, measured_sqft=18000, self_reported_score=90)
    credit = validate_success(api.get_bmp_credit(base["credit"]["id"], ASSESSOR))
    assert credit["credit_pct"] == 0.50


def test_credit_inspected_pct_diverges_after_pass(api):
    """PRD §3.4: "On a `PASS`, the credit stays `ACTIVE` but is re-scored: its
    `inspected_score` is set to the observed score, and its `credit_pct` is
    recomputed from the inspected score by the same formula used at creation —
    the inspected score divided by 100, multiplied by the credit scale of 0.60,
    capped at the maximum credit of 0.50 — after which the parcel's
    `current_fee_cents` is recomputed and the parcel's `version` is incremented
    by one."

    Design: Difficulty/dual_variant_calc/credit_provisional_vs_inspected_diverge_on_bmpcredit
    """
    base = setup_scheduled_inspection(api, measured_sqft=18000, self_reported_score=90)
    validate_success(
        api.complete_inspection(base["inspection"]["id"],
                                complete_inspection_payload(result="PASS",
                                                            observed_score=70),
                                CREDIT_INSPECTOR))
    credit = validate_success(api.get_bmp_credit(base["credit"]["id"], ASSESSOR))
    assert credit["inspected_score"] == 70
    assert credit["credit_pct"] == 0.42


def test_reinspection_pass_keeps_credit_active_rescored(api):
    """PRD §3.4: "On a `PASS`, the credit stays `ACTIVE` but is re-scored: its
    `inspected_score` is set to the observed score, and its `credit_pct` is
    recomputed from the inspected score by the same formula used at creation."

    Design: Difficulty/non_linear_state_machine/bmpcredit_reinspection_active_self_loop
    """
    base = setup_scheduled_inspection(api, measured_sqft=18000, self_reported_score=90,
                                      bmp_type="GREEN_ROOF")
    validate_success(
        api.complete_inspection(base["inspection"]["id"],
                                complete_inspection_payload(result="PASS",
                                                            observed_score=70),
                                CREDIT_INSPECTOR))
    credit = validate_success(api.get_bmp_credit(base["credit"]["id"], ASSESSOR))
    assert credit["status"] == "ACTIVE"
    assert credit["credit_pct"] == 0.42


def test_reinspection_pass_low_score_stays_active(api):
    """PRD §3.4: "On a `PASS`, the credit stays `ACTIVE` but is re-scored: its
    `inspected_score` is set to the observed score, and its `credit_pct` is
    recomputed from the inspected score by the same formula used at creation —
    the inspected score divided by 100, multiplied by the credit scale of 0.60,
    capped at the maximum credit of 0.50."

    Design: Difficulty/non_linear_state_machine/bmpcredit_reinspection_active_self_loop
    """
    # observed 50 -> 50/100*0.60 = 0.30 (below the 0.50 cap); credit stays ACTIVE.
    base = setup_scheduled_inspection(api, measured_sqft=18000, self_reported_score=90,
                                      bmp_type="GREEN_ROOF")
    validate_success(
        api.complete_inspection(base["inspection"]["id"],
                                complete_inspection_payload(result="PASS",
                                                            observed_score=50),
                                CREDIT_INSPECTOR))
    credit = validate_success(api.get_bmp_credit(base["credit"]["id"], ASSESSOR))
    assert credit["status"] == "ACTIVE"
    assert credit["credit_pct"] == 0.30


def test_credit_fail_revokes_and_recomputes_parcel(api):
    """PRD §3.4: "On a `FAIL`, the credit transitions from `ACTIVE` to `REVOKED`:
    its `inspected_score` is set to the observed score, its `credit_pct` is set
    to 0, the parcel's `current_fee_cents` is recomputed with the credit removed,
    and the parcel's `version` is incremented by one."
    PRD §3.4: "Completing the inspection sets its `status` to `COMPLETED` and
    stores the `result` and `observed_score`."

    Design: Difficulty/transitive_cascade/credit_fail_revokes_and_recomputes_parcel_depth3
    """
    base = setup_scheduled_inspection(api, measured_sqft=18000, self_reported_score=90,
                                      bmp_type="DETENTION_POND")
    parcel = validate_success(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    assert parcel["current_fee_cents"] == 10500
    insp = validate_success(
        api.complete_inspection(base["inspection"]["id"],
                                complete_inspection_payload(result="FAIL",
                                                            observed_score=10),
                                CREDIT_INSPECTOR))
    assert insp["status"] == "COMPLETED"
    credit = validate_success(api.get_bmp_credit(base["credit"]["id"], ASSESSOR))
    assert credit["status"] == "REVOKED"
    assert credit["credit_pct"] == 0
    parcel = validate_success(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    assert parcel["current_fee_cents"] == 21000


def test_credit_fail_recomputes_parcel_eru3(api):
    """PRD §3.4: "On a `FAIL`, the credit transitions from `ACTIVE` to `REVOKED`:
    its `inspected_score` is set to the observed score, its `credit_pct` is set
    to 0, the parcel's `current_fee_cents` is recomputed with the credit removed,
    and the parcel's `version` is incremented by one."

    Design: Difficulty/transitive_cascade/credit_fail_revokes_and_recomputes_parcel_depth3
    """
    # ERU 3.0: base 11000, credit 0.50 -> current_fee 11000-5500 = 5500;
    # after FAIL the credit is removed -> current_fee 11000. The per-bill fixed
    # administrative charge is not part of the parcel-level current_fee_cents.
    base = setup_scheduled_inspection(api, measured_sqft=9000, self_reported_score=90,
                                      bmp_type="DETENTION_POND")
    parcel = validate_success(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    assert parcel["current_fee_cents"] == 5500
    validate_success(
        api.complete_inspection(base["inspection"]["id"],
                                complete_inspection_payload(result="FAIL",
                                                            observed_score=10),
                                CREDIT_INSPECTOR))
    credit = validate_success(api.get_bmp_credit(base["credit"]["id"], ASSESSOR))
    assert credit["status"] == "REVOKED"
    parcel = validate_success(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    assert parcel["current_fee_cents"] == 11000


def test_inspection_complete_on_expired_credit_rejected(api):
    """PRD §3.4: "The credit being inspected must itself be `ACTIVE` — a
    `REVOKED` or `EXPIRED` credit cannot be inspected, and an attempt to complete
    against such a credit is rejected with `ERR_INVALID_STATE`."
    PRD §3.8: "Any `ACTIVE` credit that has reached its `next_inspection_due`
    transitions from `ACTIVE` to `EXPIRED`, its `credit_pct` is set to 0."

    Design: Difficulty/cross_entity_state_dependency/inspection_complete_requires_active_credit
    """
    base = setup_scheduled_inspection(api, measured_sqft=18000, self_reported_score=80,
                                      bmp_type="CISTERN",
                                      effective_date="2026-01-01T00:00:00Z",
                                      expiry_date="2028-01-01T00:00:00Z")
    # next_inspection_due = effective + 365 days = 2027-01-01; advance past it.
    validate_success(api.set_clock("2027-01-02T00:00:00Z", CREDIT_INSPECTOR))
    validate_success(api.run_billing_cycle(BILLING_CLERK))
    credit = validate_success(api.get_bmp_credit(base["credit"]["id"], ASSESSOR))
    assert credit["status"] == "EXPIRED"
    resp = api.complete_inspection(
        base["inspection"]["id"],
        complete_inspection_payload(result="PASS", observed_score=90), CREDIT_INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    insp = validate_success(api.get_inspection(base["inspection"]["id"], CREDIT_INSPECTOR))
    assert insp["status"] == "SCHEDULED"


def test_inspection_complete_on_revoked_credit_rejected(api):
    """PRD §3.4: "The credit being inspected must itself be `ACTIVE` — a
    `REVOKED` or `EXPIRED` credit cannot be inspected, and an attempt to complete
    against such a credit is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/inspection_complete_requires_active_credit
    """
    base = setup_scheduled_inspection(api, measured_sqft=18000, self_reported_score=80,
                                      bmp_type="CISTERN")
    # Revoke the credit via a FAIL on the first inspection.
    validate_success(
        api.complete_inspection(base["inspection"]["id"],
                                complete_inspection_payload(result="FAIL",
                                                            observed_score=10),
                                CREDIT_INSPECTOR))
    credit = validate_success(api.get_bmp_credit(base["credit"]["id"], ASSESSOR))
    assert credit["status"] == "REVOKED"
    # A second inspection against the now-REVOKED credit cannot be completed.
    insp2 = validate_success(
        api.create_inspection(create_inspection_payload(base["credit"]["id"],
                                                        scheduled_date="2026-03-01T00:00:00Z"),
                              CREDIT_INSPECTOR),
        expected_status=201)
    resp = api.complete_inspection(
        insp2["id"], complete_inspection_payload(result="PASS", observed_score=90),
        CREDIT_INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_credit_window_half_open_overlap_rejected(api):
    """PRD §3.4: "A new credit window may not overlap the window of an existing
    `ACTIVE` credit of the same `bmp_type` on the same parcel; because the window
    is half-open, two windows that merely touch at an endpoint do not conflict,
    but any genuine overlap is rejected with `ERR_CREDIT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/credit_window_half_open_overlap_rejected
    """
    base = setup_parcel_with_credit(api, measured_sqft=18000, self_reported_score=80,
                                    bmp_type="RAIN_GARDEN",
                                    effective_date="2026-01-01T00:00:00Z",
                                    expiry_date="2026-07-01T00:00:00Z")
    resp = api.create_bmp_credit(
        create_bmp_credit_payload(base["parcel"]["id"], bmp_type="RAIN_GARDEN",
                                  self_reported_score=70,
                                  effective_date="2026-06-01T00:00:00Z",
                                  expiry_date="2026-12-01T00:00:00Z"), ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_CREDIT_WINDOW_OVERLAP.value)


def test_credit_window_touching_endpoint_allowed(api):
    """PRD §3.4: "The credit's coverage window runs from `effective_date`
    inclusive to `expiry_date` exclusive — the half-open interval that starts on
    the effective date and ends the instant before the expiry date."
    PRD §3.4: "because the window is half-open, two windows that merely touch at
    an endpoint do not conflict, but any genuine overlap is rejected with
    `ERR_CREDIT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/credit_window_half_open_overlap_rejected
    """
    # New window starts exactly at the prior window's exclusive expiry -> allowed.
    base = setup_parcel_with_credit(api, measured_sqft=18000, self_reported_score=80,
                                    bmp_type="RAIN_GARDEN",
                                    effective_date="2026-01-01T00:00:00Z",
                                    expiry_date="2026-07-01T00:00:00Z")
    credit2 = validate_success(
        api.create_bmp_credit(
            create_bmp_credit_payload(base["parcel"]["id"], bmp_type="RAIN_GARDEN",
                                      self_reported_score=70,
                                      effective_date="2026-07-01T00:00:00Z",
                                      expiry_date="2026-12-01T00:00:00Z"), ASSESSOR),
        expected_status=201)
    assert credit2["status"] == "ACTIVE"


def test_credit_score_out_of_range_rejected(api):
    """PRD §3.4: "The `self_reported_score` is the owner's own performance rating
    and must lie between 0 and 100 inclusive; a score outside that range is
    rejected with `ERR_OUT_OF_RANGE`."

    Design: Corner/validations/credit_score_out_of_range_rejected
    """
    base = create_active_parcel(api, measured_sqft=9000, land_use="COMMERCIAL")
    resp = api.create_bmp_credit(
        create_bmp_credit_payload(base["parcel"]["id"], bmp_type="RAIN_GARDEN",
                                  self_reported_score=150), ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_OUT_OF_RANGE.value)


def test_inspection_double_complete_rejected(api):
    """PRD §3.4: "Completing an inspection is only valid while it is still
    `SCHEDULED`; completing one that is already `COMPLETED` is rejected with
    `ERR_INSPECTION_ALREADY_COMPLETED`."

    Design: Corner/cross_cutting_complexity_layers/inspection_double_complete_rejected
    """
    base = setup_scheduled_inspection(api, measured_sqft=9000, self_reported_score=80,
                                      bmp_type="CISTERN")
    validate_success(
        api.complete_inspection(base["inspection"]["id"],
                                complete_inspection_payload(result="PASS",
                                                            observed_score=80),
                                CREDIT_INSPECTOR))
    resp = api.complete_inspection(
        base["inspection"]["id"],
        complete_inspection_payload(result="PASS", observed_score=80), CREDIT_INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_ALREADY_COMPLETED.value)
