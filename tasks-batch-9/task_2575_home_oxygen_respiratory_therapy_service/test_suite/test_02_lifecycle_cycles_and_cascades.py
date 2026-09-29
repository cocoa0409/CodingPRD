"""Non-linear lifecycle cycles and transitive cascades.

Two families of behaviour are exercised here:

* the certificate-of-medical-necessity correction cycle, which re-enters states it
  has already left and closes only when the revision ceiling is reached, and the
  rental contract's two parallel state dimensions, which move independently of one
  another; and
* the two deepest cascades in the system — a failed in-home safety assessment
  propagating from stop to contract to placements to fleet units, and a Class I
  recall propagating from notice to fleet units to placements to contracts.

Every test builds its own state from scratch against an empty database with the
logical clock at its startup default.
"""

from test_helpers import (
    BILLING_SPECIALIST,
    BRANCH_MANAGER,
    COMPLIANCE_AUDITOR,
    INTAKE_COORDINATOR,
    RESPIRATORY_THERAPIST,
    ApiErrorId,
    api_client,
    apply_cmn_corrections,
    complete_setup_payload,
    create_recall_notice_payload,
    create_route_stop_payload,
    make_delivery_route,
    placement_for_role,
    post_billing_month_payload,
    read_cmn,
    read_contract,
    read_equipment_unit,
    read_patient,
    read_placement,
    read_recall_notice,
    read_route,
    read_route_stop,
    return_cmn_for_correction,
    setup_cap_reached_contract,
    setup_contract_in_service,
    setup_dispatched_setup_stop,
    setup_drafted_cmn,
    sign_cmn,
    submit_cmn,
    validate_error,
    validate_success,
)

# ─── Local composition over the shared fixtures ───────


def _drafted_cmn_scoring_full_marks() -> dict:
    """A certificate whose six documentation components sum to 100.00: a Group I
    study inside its validity window, 24 documented hours a day, all three
    narrative elements, portable prescribed for an ambulatory patient and a
    lifetime length of need."""
    return setup_drafted_cmn(
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={"portable_prescribed": True},
    )


def _run_three_revision_rounds(cmn_id: str) -> None:
    """Drive the correction cycle through its three permitted rounds, leaving the
    certificate in SUBMITTED at revision round 3.

    Round one returns from SUBMITTED, round two from PHYSICIAN_SIGNED and round
    three from SUBMITTED again; each return is followed by a correction that
    carries the certificate back to DRAFT and a fresh submission.
    """
    submit_cmn(cmn_id)
    return_cmn_for_correction(cmn_id, "Round 1: liter flow not documented against the study.")
    apply_cmn_corrections(cmn_id, narrative_element_count=2)
    submit_cmn(cmn_id)
    sign_cmn(cmn_id)
    return_cmn_for_correction(cmn_id, "Round 2: narrative regressed; signature discarded.")
    apply_cmn_corrections(cmn_id, narrative_element_count=3)
    submit_cmn(cmn_id)
    return_cmn_for_correction(cmn_id, "Round 3: hours per day still unsupported.")
    apply_cmn_corrections(cmn_id, hours_per_day=24)
    submit_cmn(cmn_id)


# ─── The certificate correction cycle ─────────────────


def test_returned_certificate_climbs_back_to_draft_with_a_recomputed_score():
    """A certificate returned for correction re-enters DRAFT once intake applies the corrections, with the documentation score recomputed over the edited values.

    PRD: "Applying corrections then closes the cycle: an `IntakeCoordinator` may revise `prescribed_lpm`, `hours_per_day`, `portable_prescribed`, `length_of_need_months` and `narrative_element_count` on a certificate in `RETURNED_FOR_CORRECTION`, which advances it `RETURNED_FOR_CORRECTION → DRAFT`, recomputes the documentation score over the edited values, clears `submitted_by_user_id` back to null, mirrors `DRAFT` onto the patient when this is the newest certificate, and increments the certificate's `version` by 1."

    Design: Difficulty/non_linear_state_machine/cmn_revision_cycle_returns_to_draft_and_caps_at_three_rounds
    """
    scenario = _drafted_cmn_scoring_full_marks()
    cmn_id = scenario["cmn"]["id"]
    patient_id = scenario["patient"]["id"]

    assert scenario["cmn"]["status"] == "DRAFT"
    assert scenario["cmn"]["revision_round"] == 0
    assert round(float(scenario["cmn"]["documentation_score"]), 2) == 100.00

    submit_cmn(cmn_id)
    returned = validate_success(
        api_client.return_cmn_for_correction(
            cmn_id,
            {"correction_notes": "Round 1: liter flow not documented against the study."},
            COMPLIANCE_AUDITOR,
        )
    )
    assert returned["status"] == "RETURNED_FOR_CORRECTION"
    assert returned["revision_round"] == 1
    assert read_patient(patient_id)["current_cmn_status"] == "RETURNED_FOR_CORRECTION"

    corrected = validate_success(
        api_client.update_cmn(cmn_id, {"narrative_element_count": 2}, INTAKE_COORDINATOR)
    )
    assert corrected["status"] == "DRAFT", "the cycle closes back onto an already-visited state"
    assert corrected["submitted_by_user_id"] is None
    assert corrected["revision_round"] == 1, "applying corrections never touches the revision round"
    # 30 group + 20 currency + 15 usage + 13.333... narrative + 10 portable + 5 duration
    assert round(float(corrected["documentation_score"]), 2) == 93.33
    assert read_patient(patient_id)["current_cmn_status"] == "DRAFT"


def test_return_from_physician_signed_discards_the_signature():
    """Returning a signed certificate for correction on the second round discards the physician signature outright.

    PRD: "Both branches behave identically and both are equally binding: `revision_round` increments by 1, the supplied notes are stored in `correction_notes`, **both `signed_by_user_id` and `physician_signature_date` are cleared to null** — the physician signature is discarded and must be obtained again even on the branch where a signature existed — the patient's mirror becomes `RETURNED_FOR_CORRECTION` when this is the newest certificate, and the certificate's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/cmn_revision_cycle_returns_to_draft_and_caps_at_three_rounds
    """
    scenario = _drafted_cmn_scoring_full_marks()
    cmn_id = scenario["cmn"]["id"]
    patient_id = scenario["patient"]["id"]

    # Round one: return from SUBMITTED, correct, and submit the certificate again.
    submit_cmn(cmn_id)
    return_cmn_for_correction(cmn_id, "Round 1: liter flow not documented against the study.")
    apply_cmn_corrections(cmn_id, narrative_element_count=2)
    submit_cmn(cmn_id)
    signed = sign_cmn(cmn_id)
    assert signed["status"] == "PHYSICIAN_SIGNED"
    assert signed["signed_by_user_id"] == "u-phys-1"
    assert signed["physician_signature_date"] == "2026-08-01"

    # Round two returns the certificate from the PHYSICIAN_SIGNED branch instead.
    returned = validate_success(
        api_client.return_cmn_for_correction(
            cmn_id,
            {"correction_notes": "Round 2: narrative regressed; signature discarded."},
            COMPLIANCE_AUDITOR,
        )
    )
    assert returned["status"] == "RETURNED_FOR_CORRECTION"
    assert returned["revision_round"] == 2
    assert returned["signed_by_user_id"] is None
    assert returned["physician_signature_date"] is None
    assert returned["correction_notes"] == "Round 2: narrative regressed; signature discarded."
    assert read_patient(patient_id)["current_cmn_status"] == "RETURNED_FOR_CORRECTION"

    # The cycle closes onto DRAFT for the second time, at full marks again.
    corrected = apply_cmn_corrections(cmn_id, narrative_element_count=3)
    assert corrected["status"] == "DRAFT"
    assert round(float(corrected["documentation_score"]), 2) == 100.00


def test_fourth_return_for_correction_is_refused_at_the_revision_ceiling():
    """The correction cycle closes for good once the revision round reaches three, so a fourth return is refused even though the certificate is legally SUBMITTED.

    PRD: "Return-for-correction is refused with `ERR_REVISION_LIMIT_REACHED` once `revision_round` has already reached the ceiling of 3, so the field ranges from 0 through 3."

    Design: Difficulty/non_linear_state_machine/cmn_revision_cycle_returns_to_draft_and_caps_at_three_rounds
    """
    scenario = _drafted_cmn_scoring_full_marks()
    cmn_id = scenario["cmn"]["id"]

    _run_three_revision_rounds(cmn_id)

    exhausted = read_cmn(cmn_id)
    assert exhausted["status"] == "SUBMITTED"
    assert exhausted["revision_round"] == 3, "neither correction nor submission touches the round"

    response = api_client.return_cmn_for_correction(
        cmn_id,
        {"correction_notes": "Round 4 attempt: must be refused."},
        COMPLIANCE_AUDITOR,
    )
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)

    unchanged = read_cmn(cmn_id)
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["revision_round"] == 3


def test_certificate_stuck_at_submitted_cannot_be_voided():
    """A certificate that has exhausted its revision rounds while sitting in SUBMITTED cannot be voided, because voiding is reachable only from DRAFT, RETURNED_FOR_CORRECTION or ACTIVE.

    PRD: "Voiding is the auditor's escape hatch, and it is reachable from exactly three states: `ACTIVE`, `DRAFT` and `RETURNED_FOR_CORRECTION`."

    Design: Difficulty/non_linear_state_machine/cmn_revision_cycle_returns_to_draft_and_caps_at_three_rounds
    """
    scenario = _drafted_cmn_scoring_full_marks()
    cmn_id = scenario["cmn"]["id"]
    patient_id = scenario["patient"]["id"]

    _run_three_revision_rounds(cmn_id)
    assert read_cmn(cmn_id)["status"] == "SUBMITTED"

    response = api_client.void_cmn(
        cmn_id,
        {"void_reason": "Exhausted certificate should be retired."},
        COMPLIANCE_AUDITOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert read_cmn(cmn_id)["status"] == "SUBMITTED"
    assert read_patient(patient_id)["current_cmn_status"] == "SUBMITTED"


# ─── The contract's two parallel state dimensions ─────


def test_capped_contract_still_holds_equipment_on_the_service_dimension():
    """A rental contract that has reached its capped-rental ceiling on the billing dimension still sits IN_SERVICE on the service dimension.

    PRD: "A contract may legitimately sit at `CAP_REACHED` on the billing dimension while sitting at `IN_SERVICE` on the service dimension, or at `ACCRUING` while `PICKUP_SCHEDULED`."

    Design: Difficulty/non_linear_state_machine/contract_parallel_billing_and_service_dimensions_evolve_independently
    """
    scenario = setup_cap_reached_contract(cap_month_limit=1, service_month="2026-08")
    contract = read_contract(scenario["contract"]["id"])

    assert contract["billing_status"] == "CAP_REACHED"
    assert contract["service_status"] == "IN_SERVICE"
    assert contract["suspension_reason"] == "NONE"
    # One stationary concentrator in the primary role on a competitive-bid contract.
    assert contract["monthly_allowable_cents"] == 5590
    assert contract["lifetime_paid_cents"] == 5590
    assert contract["posted_month_count"] == 1


def test_scheduling_a_pickup_moves_only_the_service_dimension():
    """Scheduling a pickup stop drives the contract's service dimension to PICKUP_SCHEDULED while the billing dimension stays exactly where it was.

    PRD: "Scheduling a `PICKUP` stop is more than paperwork — it moves the contract's service dimension `IN_SERVICE → PICKUP_SCHEDULED` and increments the contract's `version` by 1, in addition to creating the stop in `PLANNED` and incrementing the route's `version`."

    Design: Difficulty/non_linear_state_machine/contract_parallel_billing_and_service_dimensions_evolve_independently
    """
    scenario = setup_cap_reached_contract(cap_month_limit=1, service_month="2026-08")
    contract_id = scenario["contract"]["id"]
    placement_id = placement_for_role(contract_id, "PRIMARY_STATIONARY")["id"]
    before = read_contract(contract_id)
    assert before["billing_status"] == "CAP_REACHED"
    assert before["service_status"] == "IN_SERVICE"

    pickup_route = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-15",
        shift_start_utc="2026-08-15T12:00:00Z",
        shift_end_utc="2026-08-15T22:00:00Z",
    )
    stop = validate_success(
        api_client.create_route_stop(
            create_route_stop_payload(
                pickup_route["id"],
                contract_id,
                stop_type="PICKUP",
                window_start_utc="2026-08-15T13:00:00Z",
                window_end_utc="2026-08-15T14:00:00Z",
                service_minutes=45,
                cylinders_requested=0,
            ),
            BRANCH_MANAGER,
        ),
        201,
    )
    assert stop["status"] == "PLANNED"

    after = read_contract(contract_id)
    assert after["service_status"] == "PICKUP_SCHEDULED"
    assert after["billing_status"] == "CAP_REACHED", "the billing dimension is untouched"
    assert after["suspension_reason"] == "NONE"
    assert after["monthly_allowable_cents"] == 5590
    assert after["lifetime_paid_cents"] == 5590
    assert read_placement(placement_id)["status"] == "PLACED", (
        "scheduling a pickup never touches the placement"
    )


def test_cancelling_the_pickup_returns_the_service_dimension_to_in_service():
    """Cancelling the only planned pickup stop reverts the contract's service dimension to IN_SERVICE, leaving the capped billing dimension exactly as it was.

    PRD: "When the cancelled stop was a `PICKUP` and no other `PLANNED` pickup stop remains for its contract, the cancellation also reverts the contract's service dimension `PICKUP_SCHEDULED → IN_SERVICE` and increments the contract's `version` by 1 — the pickup scheduling step is fully undone."

    Design: Difficulty/non_linear_state_machine/contract_parallel_billing_and_service_dimensions_evolve_independently
    """
    scenario = setup_cap_reached_contract(cap_month_limit=1, service_month="2026-08")
    contract_id = scenario["contract"]["id"]
    setup_route_id = scenario["route"]["id"]
    placement_id = placement_for_role(contract_id, "PRIMARY_STATIONARY")["id"]

    pickup_route = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-15",
        shift_start_utc="2026-08-15T12:00:00Z",
        shift_end_utc="2026-08-15T22:00:00Z",
    )
    stop = validate_success(
        api_client.create_route_stop(
            create_route_stop_payload(
                pickup_route["id"],
                contract_id,
                stop_type="PICKUP",
                window_start_utc="2026-08-15T13:00:00Z",
                window_end_utc="2026-08-15T14:00:00Z",
                service_minutes=45,
                cylinders_requested=0,
            ),
            BRANCH_MANAGER,
        ),
        201,
    )
    assert read_contract(contract_id)["service_status"] == "PICKUP_SCHEDULED"

    cancelled = validate_success(api_client.cancel_route_stop(stop["id"], BRANCH_MANAGER))
    assert cancelled["status"] == "CANCELLED"

    contract = read_contract(contract_id)
    assert contract["service_status"] == "IN_SERVICE", "the service dimension round trip is closed"
    assert contract["billing_status"] == "CAP_REACHED", "no billing side effect fired"
    assert contract["suspension_reason"] == "NONE"
    assert contract["monthly_allowable_cents"] == 5590
    assert contract["lifetime_paid_cents"] == 5590
    assert read_placement(placement_id)["status"] == "PLACED"
    # The setup route bubbled up to COMPLETED; the pickup route never left PLANNING.
    assert read_route(setup_route_id)["status"] == "COMPLETED"
    assert read_route(pickup_route["id"])["status"] == "PLANNING"


# ─── Hop one: the failed in-home safety assessment ────


def _dispatched_setup_with_two_reserved_roles() -> dict:
    """A contract in PENDING_SETUP holding a reserved stationary concentrator and a
    reserved portable concentrator, with its SETUP_DELIVERY stop planned on a
    dispatched route."""
    return setup_dispatched_setup_stop(
        roles=["PRIMARY_STATIONARY", "PORTABLE"],
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={"portable_prescribed": True},
        stop_overrides={"cylinders_requested": 2},
    )


def _fail_the_in_home_assessment(stop_id: str) -> dict:
    """Close the setup stop reporting a smoker in the home, which fails the
    assessment and fires the cascade."""
    return validate_success(
        api_client.complete_setup(
            stop_id,
            complete_setup_payload(smoking_in_home=True),
            RESPIRATORY_THERAPIST,
        )
    )


def test_smoking_in_the_home_fails_the_setup_stop_assessment():
    """A setup stop closed with a smoker in the home records a failing safety result, which is the first hop of the setup-failure cascade.

    PRD: "`safety_result` is `FAIL` exactly when smoking was found in the home, and `PASS` otherwise; it only ever remains at `NOT_ASSESSED` on a setup stop that has not yet been completed."

    Design: Difficulty/transitive_cascade/setup_safety_failure_four_hop_cascade
    """
    scenario = _dispatched_setup_with_two_reserved_roles()
    stop_id = scenario["stop"]["id"]
    assert scenario["stop"]["safety_result"] == "NOT_ASSESSED"

    closed = _fail_the_in_home_assessment(stop_id)

    assert closed["status"] == "COMPLETED"
    assert closed["safety_result"] == "FAIL"
    assert closed["completed_by_user_id"] == "u-rt-1"
    assert closed["completed_at"].startswith("2026-08-01T00:00:00")
    # Smoking found, electrical inspection passed, teach-back a perfect 5.
    assert closed["safety_findings_count"] == 1
    assert closed["smoking_in_home"] is True
    # The route's only stop is now terminal, so the route bubbles up to COMPLETED.
    assert read_route(scenario["route"]["id"])["status"] == "COMPLETED"


def test_failing_safety_result_fails_the_contract_on_both_dimensions():
    """Because the stop recorded a failing safety result, the contract's service dimension fails and its billing dimension is suspended with the setup-failure reason.

    PRD: "Hop two, *because* hop one recorded a failing safety result, moves the contract's service dimension `PENDING_SETUP → SETUP_FAILED` and — branching off the same hop — moves the contract's billing dimension to `SUSPENDED` with `suspension_reason` set to `SETUP_FAILED`."

    Design: Difficulty/transitive_cascade/setup_safety_failure_four_hop_cascade
    """
    scenario = _dispatched_setup_with_two_reserved_roles()
    assert scenario["contract"]["service_status"] == "PENDING_SETUP"
    assert scenario["contract"]["billing_status"] == "ACCRUING"

    _fail_the_in_home_assessment(scenario["stop"]["id"])

    contract = read_contract(scenario["contract"]["id"])
    assert contract["service_status"] == "SETUP_FAILED"
    assert contract["billing_status"] == "SUSPENDED"
    assert contract["suspension_reason"] == "SETUP_FAILED"
    assert contract["first_service_month"] is None, "service never began"
    assert contract["monthly_allowable_cents"] == 0


def test_failed_contract_removes_its_reserved_placements():
    """Because the contract failed its setup, every placement it holds in RESERVED is removed with the setup-failure removal reason.

    PRD: "Hop three, *because* hop two moved the contract to `SETUP_FAILED`, moves every placement on the contract that is `RESERVED` to `REMOVED` with `removal_reason` set to `SETUP_FAILED` and `removed_at` set to the logical clock."

    Design: Difficulty/transitive_cascade/setup_safety_failure_four_hop_cascade
    """
    scenario = _dispatched_setup_with_two_reserved_roles()
    contract_id = scenario["contract"]["id"]
    primary_id = placement_for_role(contract_id, "PRIMARY_STATIONARY")["id"]
    portable_id = placement_for_role(contract_id, "PORTABLE")["id"]
    assert read_placement(primary_id)["status"] == "RESERVED"
    assert read_placement(portable_id)["status"] == "RESERVED"

    _fail_the_in_home_assessment(scenario["stop"]["id"])

    for placement_id in (primary_id, portable_id):
        placement = read_placement(placement_id)
        assert placement["status"] == "REMOVED"
        assert placement["removal_reason"] == "SETUP_FAILED"
        assert placement["removed_at"].startswith("2026-08-01T00:00:00")
        assert placement["placed_at"] is None, "the equipment never reached the home"


def test_removed_placements_quarantine_their_units_for_safety():
    """Because those placements were removed, every fleet unit they referenced enters quarantine with the safety reason rather than returning to the branch pool.

    PRD: "Hop four, *because* hop three removed those placements, moves every fleet unit they referenced from `RESERVED` to `IN_QUARANTINE` with `quarantine_reason` set to `SAFETY` — the equipment came back off a truck from an unsafe home and does not go straight back into the pool."

    Design: Difficulty/transitive_cascade/setup_safety_failure_four_hop_cascade
    """
    scenario = _dispatched_setup_with_two_reserved_roles()
    stationary_id = scenario["stationary_unit"]["id"]
    portable_id = scenario["portable_unit"]["id"]
    assert read_equipment_unit(stationary_id)["status"] == "RESERVED"
    assert read_equipment_unit(portable_id)["status"] == "RESERVED"

    _fail_the_in_home_assessment(scenario["stop"]["id"])

    for unit_id in (stationary_id, portable_id):
        unit = read_equipment_unit(unit_id)
        assert unit["status"] == "IN_QUARANTINE", "the unit is not returned to stock"
        assert unit["quarantine_reason"] == "SAFETY"


def test_failed_setup_recomputes_the_risk_score_under_the_initial_assessment_variant():
    """The failed in-home assessment recomputes the patient's oxygen-safety risk score as the weighted average of the five factors, which dilutes the single catastrophic smoking factor.

    PRD: "The **initial-assessment variant** is a weighted average of those five factors: the smoking factor at weight 0.30, the electrical factor at 0.15, the teach-back factor at 0.15, the flow factor at 0.30 and the incident factor at 0.10."

    Design: Difficulty/transitive_cascade/setup_safety_failure_four_hop_cascade
    """
    scenario = _dispatched_setup_with_two_reserved_roles()
    patient_id = scenario["patient"]["id"]
    assert round(float(read_patient(patient_id)["oxygen_safety_risk_score"]), 2) == 0.00

    _fail_the_in_home_assessment(scenario["stop"]["id"])

    patient = read_patient(patient_id)
    # Smoking 100, electrical 0, teach-back 0, flow 20 for 3.0 lpm, incident 0:
    # 100 * 0.30 + 0 * 0.15 + 0 * 0.15 + 20 * 0.30 + 0 * 0.10 = 36.00
    assert round(float(patient["oxygen_safety_risk_score"]), 2) == 36.00
    assert patient["risk_variant_applied"] == "INITIAL_ASSESSMENT"
    assert patient["compliance_hold"] is False


def test_setup_failure_suspension_blocks_a_posted_rental_month():
    """The billing suspension the setup failure cascaded onto the contract is real: the contract can no longer accept a posted rental month.

    PRD: "It must be exactly `ACCRUING`: a contract sitting in `SUSPENDED` or `CAP_REACHED` cannot accept another month, and the attempt is refused with `ERR_CONTRACT_BILLING_SUSPENDED`."

    Design: Difficulty/transitive_cascade/setup_safety_failure_four_hop_cascade
    """
    scenario = _dispatched_setup_with_two_reserved_roles()
    contract_id = scenario["contract"]["id"]

    _fail_the_in_home_assessment(scenario["stop"]["id"])
    assert read_contract(contract_id)["billing_status"] == "SUSPENDED"

    response = api_client.post_billing_month(
        contract_id, post_billing_month_payload("2026-08"), BILLING_SPECIALIST
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_BILLING_SUSPENDED.value)

    contract = read_contract(contract_id)
    assert contract["billing_status"] == "SUSPENDED"
    assert contract["posted_months"] == []
    assert contract["lifetime_paid_cents"] == 0


# ─── The Class I recall cascade ────────────────────────


def _in_service_contract_with_two_placed_units() -> dict:
    """A contract IN_SERVICE after a passing setup, holding a placed stationary
    concentrator and a placed portable concentrator on two distinct model codes."""
    return setup_contract_in_service(
        roles=["PRIMARY_STATIONARY", "PORTABLE"],
        patient_overrides={"mobility_profile": "ACTIVE_AMBULATORY"},
        cmn_overrides={"portable_prescribed": True},
        stop_overrides={"cylinders_requested": 2},
    )


def _publish_class_i_recall(model_code: str) -> dict:
    """Publish a Class I manufacturer recall against one model code."""
    return validate_success(
        api_client.create_recall_notice(
            create_recall_notice_payload(model_code, "CLASS_I"), COMPLIANCE_AUDITOR
        ),
        201,
    )


def test_class_i_recall_notice_falls_due_five_days_after_issue():
    """A Class I recall notice opens against the model code with a remediation deadline five whole days after the issue instant.

    PRD: "The notice opens in `OPEN` with `issued_at` stamped from the logical clock, and its `remediation_deadline_utc` is `issued_at` advanced by whole days according to severity: 5 days for `CLASS_I`, 30 days for `CLASS_II` and 90 days for `CLASS_III`."

    Design: Difficulty/transitive_cascade/recall_class_i_four_hop_cascade
    """
    scenario = _in_service_contract_with_two_placed_units()

    notice = _publish_class_i_recall(scenario["stationary_unit"]["model_code"])

    assert notice["status"] == "OPEN"
    assert notice["severity"] == "CLASS_I"
    assert notice["model_code"] == scenario["stationary_unit"]["model_code"]
    assert notice["issued_at"].startswith("2026-08-01T00:00:00")
    assert notice["remediation_deadline_utc"].startswith("2026-08-06T00:00:00")


def test_class_i_recall_freezes_its_exposure_snapshots_at_issue_time():
    """The notice's unit counts are taken over the units matching its model code before the cascade moves anything, so only the recalled model is counted.

    PRD: "`affected_unit_count` counts the fleet units whose `model_code` matches the notice and whose status is `IN_STOCK`, `RESERVED`, `DEPLOYED` or `IN_QUARANTINE`; `RETIRED` units are excluded."

    Design: Difficulty/transitive_cascade/recall_class_i_four_hop_cascade
    """
    scenario = _in_service_contract_with_two_placed_units()

    notice = _publish_class_i_recall(scenario["stationary_unit"]["model_code"])

    # Exactly one unit carries the recalled model code; the portable concentrator
    # sits on a different one and is invisible to the notice.
    assert notice["affected_unit_count"] == 1
    assert notice["auto_quarantined_unit_count"] == 1
    assert notice["remediated_unit_count"] == 0

    reread = read_recall_notice(notice["id"])
    assert reread["affected_unit_count"] == 1, "the snapshot is never recomputed"
    assert reread["auto_quarantined_unit_count"] == 1
    assert reread["remediated_unit_count"] == 0


def test_class_i_recall_quarantines_only_the_matching_model_code():
    """Publishing a Class I notice pulls every non-retired unit sharing the recalled model code into quarantine and leaves every other unit alone.

    PRD: "Hop one moves every non-retired fleet unit whose `model_code` matches the notice from `IN_STOCK`, `RESERVED` or `DEPLOYED` into `IN_QUARANTINE` with `quarantine_reason` set to `RECALL`; units already `IN_QUARANTINE` stay there."

    Design: Difficulty/transitive_cascade/recall_class_i_four_hop_cascade
    """
    scenario = _in_service_contract_with_two_placed_units()
    stationary_id = scenario["stationary_unit"]["id"]
    portable_id = scenario["portable_unit"]["id"]
    assert read_equipment_unit(stationary_id)["status"] == "DEPLOYED"
    assert read_equipment_unit(portable_id)["status"] == "DEPLOYED"

    _publish_class_i_recall(scenario["stationary_unit"]["model_code"])

    recalled = read_equipment_unit(stationary_id)
    assert recalled["status"] == "IN_QUARANTINE"
    assert recalled["quarantine_reason"] == "RECALL"

    untouched = read_equipment_unit(portable_id)
    assert untouched["status"] == "DEPLOYED", "a different model code is not exposed"
    assert untouched["quarantine_reason"] == "NONE"


def test_recall_quarantine_pulls_the_matching_placement_out_of_service():
    """Because the recall quarantined the stationary unit, the placement holding it leaves PLACED for RECALLED_OUT_OF_SERVICE while the portable placement stands.

    PRD: "Hop three, *because* hop one quarantined those units, moves every placement in `PLACED` that references one of them from `PLACED → RECALLED_OUT_OF_SERVICE`, setting `removal_reason` to `RECALL` and `removed_at` to the logical clock."

    Design: Difficulty/transitive_cascade/recall_class_i_four_hop_cascade
    """
    scenario = _in_service_contract_with_two_placed_units()
    contract_id = scenario["contract"]["id"]
    stationary_placement_id = placement_for_role(contract_id, "PRIMARY_STATIONARY")["id"]
    portable_placement_id = placement_for_role(contract_id, "PORTABLE")["id"]

    _publish_class_i_recall(scenario["stationary_unit"]["model_code"])

    pulled = read_placement(stationary_placement_id)
    assert pulled["status"] == "RECALLED_OUT_OF_SERVICE"
    assert pulled["removal_reason"] == "RECALL"
    assert pulled["removed_at"].startswith("2026-08-01T00:00:00")

    kept = read_placement(portable_placement_id)
    assert kept["status"] == "PLACED", "the portable unit was never recalled"
    assert kept["removal_reason"] == "NONE"
    assert kept["removed_at"] is None


def test_recall_suspends_billing_and_reprices_the_remaining_equipment():
    """Because the recall took a placement out of service, the contract's billing dimension suspends for RECALL and its monthly allowable is repriced over the equipment still placed, leaving the service dimension untouched.

    PRD: "Hop four, *because* hop three took those placements out of service, moves the billing dimension of each affected contract to `SUSPENDED` with `suspension_reason` set to `RECALL`, and recomputes each such contract's `monthly_allowable_cents` over its remaining placed equipment."

    Design: Difficulty/transitive_cascade/recall_class_i_four_hop_cascade
    """
    scenario = _in_service_contract_with_two_placed_units()
    contract_id = scenario["contract"]["id"]
    # Stationary concentrator plus portable concentrator, priced together.
    assert scenario["contract"]["monthly_allowable_cents"] == 6913
    assert scenario["contract"]["billing_status"] == "ACCRUING"

    _publish_class_i_recall(scenario["stationary_unit"]["model_code"])

    contract = read_contract(contract_id)
    assert contract["billing_status"] == "SUSPENDED"
    assert contract["suspension_reason"] == "RECALL"
    # The service dimension is not part of this cascade.
    assert contract["service_status"] == "IN_SERVICE"
    # Only the portable concentrator is still placed, so only it is priced.
    assert contract["monthly_allowable_cents"] == 1323


def test_billing_cannot_resume_while_a_recalled_placement_remains():
    """A contract still holding a recalled placement is refused when it tries to resume billing, and stays suspended.

    PRD: "A contract may not resume billing while any of its placements still sits in `RECALLED_OUT_OF_SERVICE`; the attempt is refused with `ERR_CONTRACT_HAS_RECALLED_EQUIPMENT`, and the only way forward is to take the recalled placement out of the way and re-equip the patient."

    Design: Difficulty/transitive_cascade/recall_class_i_four_hop_cascade
    """
    scenario = _in_service_contract_with_two_placed_units()
    contract_id = scenario["contract"]["id"]
    _publish_class_i_recall(scenario["stationary_unit"]["model_code"])
    assert (
        placement_for_role(contract_id, "PRIMARY_STATIONARY")["status"]
        == "RECALLED_OUT_OF_SERVICE"
    )

    validate_error(
        api_client.resume_billing(contract_id, BILLING_SPECIALIST),
        ApiErrorId.ERR_CONTRACT_HAS_RECALLED_EQUIPMENT.value,
    )

    contract = read_contract(contract_id)
    assert contract["billing_status"] == "SUSPENDED"
    assert contract["suspension_reason"] == "RECALL"
