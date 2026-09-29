"""Sign-off consequences: the out-of-trust cascade, the abort compensation and forbearance duties."""
from test_helpers import (
    AM,
    CO,
    CRM,
    ApiErrorId,
    api_client,
    assert_audit_scope_identity,
    assert_credit_line_capacity_identity,
    assert_out_of_trust_incident,
    assert_unit_audit_observation,
    abort_audit,
    aging_exception_decision_payload,
    assert_aging_exception_request,
    file_aging_exception,
    floor_unit,
    list_unit_obligations,
    make_credit_risk_manager_headers,
    move_title_custody,
    read_credit_line,
    read_dealer,
    read_unit,
    reconcile_audit,
    record_observation,
    register_unit,
    request_advance,
    run_curtailment,
    schedule_audit,
    set_clock,
    setup_active_line,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
)


def _missing_unit_ready_for_sign_off():
    """A 20,000,000 cent unit read as MISSING, plus an unrelated advance still REQUESTED."""
    ctx = setup_active_line(
        dealer_overrides={"legal_name": "Cascade Cascade Motors LLC", "state_code": "WA"}
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    unit_a = floor_unit(
        dealer_id,
        line_id,
        "CASCUNITA0000010",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=20000000,
        document_reference="MSO-0009A",
        disbursement_reference="WIRE-0009A",
        invoice_amount_cents=20000000,
        odometer_miles=8,
    )
    unit_b = register_unit(
        dealer_id,
        line_id,
        "CASCUNITB0000010",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
        odometer_miles=10,
    )
    move_title_custody(unit_b["id"], "LENDER_HELD", "MSO-0009B")
    advance_b = request_advance(unit_b["id"], ctx["dealer_headers"], 3000000, "INV-0009B")
    audit = schedule_audit(dealer_id, "2026-08-10", "2026-08-12")
    set_clock("2026-08-10T00:00:00Z")
    started = start_audit(audit["id"])
    assert started["units_in_scope_count"] == 1
    observation = record_observation(
        audit["id"], unit_a["unit"]["id"], "MISSING", False
    )
    assert observation["classification"] == "SOLD_OUT_OF_TRUST"
    assert observation["is_out_of_trust"] is True
    return {
        "dealer_id": dealer_id,
        "line_id": line_id,
        "unit_a": unit_a["unit"],
        "unit_b": unit_b,
        "advance_b": advance_b,
        "audit_id": audit["id"],
        "observation": observation,
    }


def test_signing_off_a_missing_unit_opens_an_incident_and_moves_the_unit():
    """The first two hops: an OPEN incident at live exposure and the unit out of trust.

    PRD: "For every observation of this audit whose `is_out_of_trust` is true, in `created_at` ascending order, an `OutOfTrustIncident` is created in `OPEN` carrying `dealer_id`, `unit_id`, `audit_id` and `observation_id`, with `exposure_cents` set to that unit's live `outstanding_principal_cents`, `cure_deadline_at` set to `reconciled_at` plus 10 days, `cured_at`, `charged_off_at` and `resolution_reason_code` null, and `version` 1."

    Design: Difficulty/transitive_cascade/audit_reconcile_cascades_five_hops_from_observation_to_voided_advance
    """
    ctx = _missing_unit_ready_for_sign_off()
    reconcile_audit(ctx["audit_id"], notes="Unit A absent, no payoff on file")

    incidents, meta = validate_paginated(
        api_client.list_out_of_trust_incidents(
            CRM, params={"unit_id": ctx["unit_a"]["id"], "status": "OPEN"}
        )
    )
    assert meta["total_count"] == 1
    incident = incidents[0]
    assert_out_of_trust_incident(incident)
    assert incident["status"] == "OPEN"
    assert incident["dealer_id"] == ctx["dealer_id"]
    assert incident["unit_id"] == ctx["unit_a"]["id"]
    assert incident["audit_id"] == ctx["audit_id"]
    assert incident["observation_id"] == ctx["observation"]["id"]
    assert incident["exposure_cents"] == 20000000
    assert str(incident["cure_deadline_at"]).startswith("2026-08-20T00:00:00")
    assert incident["cured_at"] is None
    assert incident["charged_off_at"] is None
    assert incident["resolution_reason_code"] is None
    assert incident["version"] == 1

    unit_a = read_unit(ctx["unit_a"]["id"])
    assert unit_a["funding_status"] == "SOT_OPEN"
    assert unit_a["eligibility_status"] == "INELIGIBLE_SOLD_OUT_OF_TRUST"
    assert unit_a["ineligibility_reason_code"] == "SOLD_OUT_OF_TRUST"
    assert unit_a["outstanding_principal_cents"] == 20000000


def test_the_exposure_threshold_suspends_the_facility_and_voids_an_unrelated_request():
    """Hops three to five reach an advance the observation never named.

    PRD: "When the dealership's `open_sot_exposure_cents` reaches or exceeds 10,000,000 cents (one hundred thousand dollars), the credit line moves `ACTIVE → SUSPENDED` with `suspension_reason_code` `SOT_EXPOSURE_THRESHOLD`. That suspension in turn voids every advance on the line still in `REQUESTED` (with `reason_code` `LINE_SUSPENDED`, processed in `created_at` ascending order, each voided advance returning its unit `PENDING_FUNDING → REGISTERED`) and moves the dealership `ACTIVE → SUSPENDED`."

    Design: Difficulty/transitive_cascade/audit_reconcile_cascades_five_hops_from_observation_to_voided_advance
    """
    ctx = _missing_unit_ready_for_sign_off()
    reconcile_audit(ctx["audit_id"], notes="Unit A absent, no payoff on file")

    dealer = read_dealer(ctx["dealer_id"])
    assert dealer["open_sot_incident_count"] == 1
    assert dealer["open_sot_exposure_cents"] == 20000000
    assert dealer["risk_score"] == 85
    assert dealer["risk_rating"] == "B"
    assert dealer["audit_frequency_days"] == 90
    assert str(dealer["next_audit_due_at"]).startswith("2026-11-08T00:00:00")
    assert dealer["status"] == "SUSPENDED"
    assert dealer["audit_in_progress"] is False

    line = read_credit_line(ctx["line_id"])
    assert line["status"] == "SUSPENDED"
    assert line["suspension_reason_code"] == "SOT_EXPOSURE_THRESHOLD"
    assert line["outstanding_principal_cents"] == 20000000
    assert line["eligible_collateral_cents"] == 0
    assert line["borrowing_base_deficiency_cents"] == 20000000
    assert line["available_credit_cents"] == 480000000
    assert_credit_line_capacity_identity(line)

    voided = validate_success(api_client.get_funding_advance(ctx["advance_b"]["id"], CO))
    assert voided["status"] == "VOIDED"
    assert voided["reason_code"] == "LINE_SUSPENDED"
    assert read_unit(ctx["unit_b"]["id"])["funding_status"] == "REGISTERED"


def test_the_audit_row_records_the_exception_outcome_at_the_live_exposure():
    """The audit lands in RECONCILED_EXCEPTIONS with the exposure read at sign-off time.

    PRD: "On the exceptions branch, `sot_exposure_cents` is the sum, taken over this audit's observations whose `is_out_of_trust` is true in `created_at` ascending order, of each such observation's unit's `outstanding_principal_cents` **read live at reconcile time** — not the `unit_outstanding_principal_cents_at_observation` snapshot stored on the row."

    Design: Difficulty/transitive_cascade/audit_reconcile_cascades_five_hops_from_observation_to_voided_advance
    """
    ctx = _missing_unit_ready_for_sign_off()
    signed = reconcile_audit(ctx["audit_id"], notes="Unit A absent, no payoff on file")

    assert signed["status"] == "RECONCILED_EXCEPTIONS"
    assert signed["sot_exposure_cents"] == 20000000
    assert signed["units_in_scope_count"] == 1
    assert signed["units_verified_count"] == 0
    assert signed["units_exception_count"] == 1
    assert signed["units_unobserved_count"] == 0
    assert signed["reconciled_by_user_id"] == AM["X-User-ID"]
    assert str(signed["reconciled_at"]).startswith("2026-08-10T00:00:00")
    assert_audit_scope_identity(signed)
    assert ctx["observation"]["unit_outstanding_principal_cents_at_observation"] == 20000000


def _three_floored_units_two_read():
    """Three floored units, an open count and two readings: one VERIFIED, one exception."""
    ctx = setup_active_line(
        dealer_overrides={"legal_name": "Compensating Count Motors LLC", "state_code": "OR"}
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    units = []
    for index, vin_seed in enumerate(
        ("ROLLUNITA0000010", "ROLLUNITB0000010", "ROLLUNITC0000010")
    ):
        units.append(
            floor_unit(
                dealer_id,
                line_id,
                vin_seed,
                dealer_headers=ctx["dealer_headers"],
                requested_amount_cents=3000000,
                document_reference="MSO-0020-%d" % index,
                disbursement_reference="WIRE-0020-%d" % index,
                invoice_amount_cents=3000000,
                odometer_miles=2 + index,
            )["unit"]
        )
    audit = schedule_audit(dealer_id, "2026-08-10", "2026-08-12")
    set_clock("2026-08-10T00:00:00Z")
    started = start_audit(audit["id"])
    reading_a = record_observation(
        audit["id"], units[0]["id"], "PRESENT", True, odometer_miles=2
    )
    reading_b = record_observation(
        audit["id"], units[1]["id"], "PRESENT_DAMAGED", True, odometer_miles=3
    )
    return {
        "dealer_id": dealer_id,
        "line_id": line_id,
        "units": units,
        "audit_id": audit["id"],
        "started": started,
        "reading_a": reading_a,
        "reading_b": reading_b,
    }


def test_aborting_rolls_the_three_observation_counters_back_to_the_frozen_scope():
    """The scope identity reads 3 == 0 + 0 + 3 before the readings and again after the abort.

    PRD: "It is the compensating action for the observation transitions, so the three observation counters are restored to the configuration they had before the first reading — `units_verified_count` and `units_exception_count` return to 0 and `units_unobserved_count` returns to `units_in_scope_count` — which keeps the count-conservation identity of §2.12 reading identically before and after."

    Design: Difficulty/compensating_invariant/audit_scope_count_identity_survives_an_abort_that_rolls_the_counters_back
    """
    ctx = _three_floored_units_two_read()
    frozen = ctx["started"]
    assert frozen["units_in_scope_count"] == 3
    assert frozen["units_verified_count"] == 0
    assert frozen["units_exception_count"] == 0
    assert frozen["units_unobserved_count"] == 3
    assert_audit_scope_identity(frozen)

    assert ctx["reading_a"]["classification"] == "VERIFIED"
    assert ctx["reading_a"]["is_out_of_trust"] is False
    assert ctx["reading_b"]["classification"] == "DAMAGE_EXCEPTION"
    assert ctx["reading_b"]["is_out_of_trust"] is False

    mid_count = validate_success(api_client.get_audit(ctx["audit_id"], AM))
    assert mid_count["units_verified_count"] == 1
    assert mid_count["units_exception_count"] == 1
    assert mid_count["units_unobserved_count"] == 1
    assert_audit_scope_identity(mid_count)

    aborted = abort_audit(ctx["audit_id"], "AUDITOR_REASSIGNED")
    assert aborted["status"] == "ABORTED"
    assert aborted["abort_reason_code"] == "AUDITOR_REASSIGNED"
    assert aborted["units_in_scope_count"] == 3
    assert aborted["units_verified_count"] == 0
    assert aborted["units_exception_count"] == 0
    assert aborted["units_unobserved_count"] == 3
    assert aborted["sot_exposure_cents"] == 0
    assert_audit_scope_identity(aborted)


def test_the_abandoned_count_leaves_the_readings_readable_and_everything_else_untouched():
    """No incident, no eligibility change, no cadence advance, and both rows still listed.

    PRD: "Aborting draws no conclusions whatsoever: no incident is created, no unit's `eligibility_status` or `funding_status` changes, and `sot_exposure_cents` is left at 0."

    PRD: "The dealership's `audit_in_progress` returns to false, its `next_audit_due_at` is **not** advanced (an abandoned count does not satisfy the cadence), and the audit's window is freed so a replacement can be scheduled over it."

    Design: Difficulty/compensating_invariant/audit_scope_count_identity_survives_an_abort_that_rolls_the_counters_back
    """
    ctx = _three_floored_units_two_read()
    abort_audit(ctx["audit_id"], "AUDITOR_REASSIGNED")

    rows, meta = validate_paginated(
        api_client.list_audit_observations(ctx["audit_id"], AM)
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [
        ctx["reading_a"]["id"],
        ctx["reading_b"]["id"],
    ]
    for row in rows:
        assert_unit_audit_observation(row)

    per_unit, per_unit_meta = validate_paginated(
        api_client.list_unit_audit_observations(ctx["units"][1]["id"], AM)
    )
    assert per_unit_meta["total_count"] == 1
    assert per_unit[0]["id"] == ctx["reading_b"]["id"]
    assert per_unit[0]["classification"] == "DAMAGE_EXCEPTION"

    damaged = read_unit(ctx["units"][1]["id"])
    assert damaged["eligibility_status"] == "ELIGIBLE"
    assert damaged["funding_status"] == "FLOORED"

    incidents, incident_meta = validate_paginated(
        api_client.list_out_of_trust_incidents(CRM, params={"dealer_id": ctx["dealer_id"]})
    )
    assert incident_meta["total_count"] == 0
    assert incidents == []

    dealer = read_dealer(ctx["dealer_id"])
    assert dealer["open_sot_incident_count"] == 0
    assert dealer["audit_in_progress"] is False
    assert str(dealer["next_audit_due_at"]).startswith("2027-01-28T00:00:00")

    line = read_credit_line(ctx["line_id"])
    assert line["outstanding_principal_cents"] == 9000000
    assert line["available_credit_cents"] == 491000000
    assert_credit_line_capacity_identity(line)


def _pending_exception_on_an_out_of_trust_unit():
    """A PENDING forbearance request on a DUE obligation of a unit already out of trust."""
    ctx = setup_active_line(
        dealer_overrides={"legal_name": "Sagebrush Duties Motors LLC", "state_code": "UT"}
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    unit = floor_unit(
        dealer_id,
        line_id,
        "SAGEUNIT00000010",
        dealer_headers=ctx["dealer_headers"],
        requested_amount_cents=3000000,
        document_reference="MSO-0012",
        disbursement_reference="WIRE-0012",
        invoice_amount_cents=3000000,
        odometer_miles=9,
    )["unit"]
    set_clock("2026-10-30T00:00:00Z")
    run_curtailment(dealer_id=dealer_id, as_of_date="2026-10-30")
    obligation = list_unit_obligations(unit["id"], status="DUE")[0]
    assert obligation["required_principal_cents"] == 300000
    request = file_aging_exception(
        obligation["id"],
        ctx["dealer_headers"],
        requested_extension_days=30,
        justification_code="RETAIL_DEAL_PENDING",
    )
    assert request["status"] == "PENDING"
    audit = schedule_audit(dealer_id, "2026-11-10", "2026-11-12")
    set_clock("2026-11-10T00:00:00Z")
    start_audit(audit["id"])
    record_observation(audit["id"], unit["id"], "MISSING", False)
    reconcile_audit(
        audit["id"], notes="Unit gone, dealer claims wholesale with no paperwork"
    )
    return {
        "dealer_id": dealer_id,
        "line_id": line_id,
        "unit": unit,
        "obligation": obligation,
        "request": request,
    }


def _approval_payload():
    """The one decision payload both duty checks are exercised with."""
    return aging_exception_decision_payload(
        "APPROVE", "RELIEF_GRANTED", decided_extension_days=30
    )


def test_the_funder_of_a_unit_cannot_approve_forbearance_on_it():
    """The duty-separation refusal wins over the live out-of-trust condition.

    PRD: "Because the duty separation is checked before the out-of-trust condition, an operator attempting to self-approve relief on an out-of-trust unit sees the separation error, not the out-of-trust one."

    Design: Difficulty/priority_pair_validation_conflict/exception_approver_sod_safety_error_beats_open_out_of_trust_referential_error
    """
    ctx = _pending_exception_on_an_out_of_trust_unit()
    unit = read_unit(ctx["unit"]["id"])
    assert unit["funded_by_user_id"] == CO["X-User-ID"]
    assert unit["funding_status"] == "SOT_OPEN"
    incidents, meta = validate_paginated(
        api_client.list_out_of_trust_incidents(
            CRM, params={"unit_id": ctx["unit"]["id"], "status": "OPEN"}
        )
    )
    assert meta["total_count"] == 1
    assert incidents[0]["exposure_cents"] == 3000000
    dealer = read_dealer(ctx["dealer_id"])
    assert dealer["status"] == "ACTIVE"
    assert dealer["open_sot_exposure_cents"] == 3000000
    assert read_credit_line(ctx["line_id"])["status"] == "ACTIVE"

    validate_error(
        api_client.decide_aging_exception(
            ctx["request"]["id"],
            _approval_payload(),
            make_credit_risk_manager_headers(CO["X-User-ID"]),
        ),
        ApiErrorId.ERR_SOD_EXCEPTION_APPROVER,
        403,
    )


def test_a_clean_approver_still_cannot_grant_relief_on_a_unit_out_of_trust():
    """Swapping only the acting identity exposes the referential refusal underneath.

    PRD: "And last, the unit must have no out-of-trust incident in `OPEN`: a unit already sold out of trust does not get more time, and the refusal is `ERR_UNIT_HAS_OPEN_SOT`."

    Design: Difficulty/priority_pair_validation_conflict/exception_approver_sod_safety_error_beats_open_out_of_trust_referential_error
    """
    ctx = _pending_exception_on_an_out_of_trust_unit()
    validate_error(
        api_client.decide_aging_exception(
            ctx["request"]["id"],
            _approval_payload(),
            make_credit_risk_manager_headers(CO["X-User-ID"]),
        ),
        ApiErrorId.ERR_SOD_EXCEPTION_APPROVER,
        403,
    )
    validate_error(
        api_client.decide_aging_exception(ctx["request"]["id"], _approval_payload(), CRM),
        ApiErrorId.ERR_UNIT_HAS_OPEN_SOT,
        409,
    )

    requests, meta = validate_paginated(
        api_client.list_aging_exceptions(ctx["obligation"]["id"], CRM)
    )
    assert meta["total_count"] == 1
    still_pending = requests[0]
    assert_aging_exception_request(still_pending)
    assert still_pending["status"] == "PENDING"
    assert still_pending["decided_extension_days"] is None
    assert still_pending["decided_by_user_id"] is None
    assert still_pending["decided_at"] is None
    assert still_pending["replacement_obligation_id"] is None

    obligation = validate_success(
        api_client.get_curtailment_obligation(ctx["obligation"]["id"], CO)
    )
    assert obligation["status"] == "DUE"
    assert obligation["extension_days_applied"] == 0

    unit = read_unit(ctx["unit"]["id"])
    assert unit["curtailment_extension_days_total"] == 0
    assert unit["aging_exception_count"] == 0
