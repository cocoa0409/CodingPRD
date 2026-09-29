"""State-machine conformance for the Neonatal Network API.

Covers the initial state of every declared machine (PRD §3.2, §3.3, §3.4, §3.5,
§3.6, §3.7, §3.9); the designation review path through submission, verification,
certification, the conditional grant, the below-floor denial and the exhausted
submission rounds (PRD §3.2); the referral transition table with its
terminal-state lockdown, its rejected out-of-state triggers and its capability
guard (PRD §2.7, §2.10, §3.3, §3.4); the bed-ledger synchronisation at admission
(PRD §2.6, §2.8, §3.7); the capability cascade a credential revocation triggers
(PRD §3.8); the compensating transport abort (PRD §3.6); and the capacity
sweep's expiry-then-promotion ordering (PRD §2.5, §3.4).
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    make_unit_scoped_user_id,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Initial state of every declared machine
# ---------------------------------------------------------------------------


def test_designation_review_opens_in_draft_with_zero_scores(api, network):
    """PRD §3.2: "The review starts in `DRAFT` with `submission_round` at 0 and every score field at 0."

    Design: Corner/state_machines/initial_state_of_every_declared_machine
    """
    resp = api.create_designation_review(
        factories.designation_review_payload(
            network["unit_a_id"], requested_level="LEVEL_III", assigned_nurse_count=2
        ),
        network["dir_a"],
    )
    review = validate_success(resp, 201)
    assertions.assert_designation_review(review)
    assert review["status"] == "DRAFT"
    assert review["submission_round"] == 0
    for score_field in (
        "staffing_subscore",
        "equipment_subscore",
        "volume_subscore",
        "compliance_score",
    ):
        assertions.assert_close(review[score_field], 0)


def test_referral_opens_pending_before_anyone_decides_on_it(api, network):
    """PRD §3.3: "The new referral starts at status `PENDING` with `info_request_rounds` at 0 and `decision_reason`, `requested_items`, `source_admission_id`, `superseded_by_referral_id` and `reservation_id` all null."

    Design: Corner/state_machines/initial_state_of_every_declared_machine
    """
    resp = api.create_referral(
        factories.referral_payload(
            network["unit_b_id"], network["unit_a_id"], case_reference="CASE-N1"
        ),
        network["ref_b"],
    )
    referral = validate_success(resp, 201)
    assertions.assert_referral(referral)
    assert referral["status"] == "PENDING"
    assert referral["info_request_rounds"] == 0
    assert referral["decision_reason"] is None
    assert referral["requested_items"] is None
    assert referral["source_admission_id"] is None
    assert referral["superseded_by_referral_id"] is None
    assert referral["reservation_id"] is None


def test_bed_reservation_is_born_held(api, network):
    """PRD §3.4: "A permitted acceptance moves the referral `PENDING → ACCEPTED` and creates a bed reservation for it, carrying the receiving unit as `unit_id` and the referral as `referral_id`, starting at status `HELD`, taking its `bed_class` from the waterfall rule of §2.8, stamping `held_at` with the current clock instant, and computing `expires_at` from the referral's kind: an antenatal hold lasts 720 minutes — twelve hours — from `held_at`, because a mother in labour needs a bed that will still be there tomorrow morning, while every other kind of hold lasts 240 minutes, four hours."

    Design: Corner/state_machines/initial_state_of_every_declared_machine
    """
    referral = fixtures.create_referral(network, case_reference="CASE-N1")
    unit_version = fixtures.read_unit_version(network, headers=network["intake_a"])
    resp = api.accept_referral(
        referral["id"],
        factories.accept_referral_payload(unit_version),
        network["intake_a"],
    )
    accepted = validate_success(resp)
    assert accepted["status"] == "ACCEPTED"

    reservation = fixtures.read_reservation(network, accepted["reservation_id"])
    assertions.assert_bed_reservation(reservation)
    assert reservation["status"] == "HELD"
    assert reservation["released_reason"] is None
    assert reservation["unit_id"] == network["unit_a_id"]
    assert reservation["referral_id"] == referral["id"]


def test_transport_run_opens_activated_without_dispatching(api):
    """PRD §3.6: "The run's `receiving_unit_id` is copied from the reservation rather than supplied, and the run opens at status `ACTIVATED`."
    PRD §3.6: "Both start out null and false respectively on a newly activated run."

    Design: Corner/state_machines/initial_state_of_every_declared_machine
    """
    env = fixtures.setup_network(with_isolette=True)
    _referral, accepted = fixtures.hold_bed(env, case_reference="CASE-N1")

    resp = api.create_transport_run(
        factories.transport_run_payload(
            accepted["reservation_id"], env["assets"]["TRANSPORT_ISOLETTE"]["id"]
        ),
        env["coord"],
    )
    run = validate_success(resp, 201)
    assertions.assert_transport_run(run)
    assert run["status"] == "ACTIVATED"
    assert run["receiving_unit_id"] == env["unit_a_id"]
    assert run["stabilization_score"] is None
    assert run["stabilization_bundle_complete"] is False


def test_admission_opens_on_both_dimensions_at_once(api, network):
    """PRD §3.7: "It opens at `care_status` `ADMITTED` and `infection_status` `SURVEILLANCE_CLEAR`, with `patient_days`, `central_line_days`, `ventilator_days`, `developmental_round_count`, `kangaroo_care_sessions`, `family_presence_minutes`, `cluster_care_compliant_count`, `light_cycling_compliant_count`, `developmental_bundle_score` and `milk_administered_ml` all at zero, `high_risk_graduate` false, and `back_transfer_source_admission_id`, `back_transfer_attestation_note`, `infection_confirmed_at`, `discharged_at` and `discharge_disposition` all null."
    PRD §3.7: "Any value of one dimension may coexist with any value of the other, and a transition on one dimension never moves the other."

    Design: Corner/state_machines/initial_state_of_every_declared_machine
    """
    referral, _accepted = fixtures.hold_bed(network, case_reference="CASE-N2")

    resp = api.create_admission(
        factories.admission_payload(referral["id"]), network["intake_a"]
    )
    admission = validate_success(resp, 201)
    assertions.assert_admission(admission)
    assert admission["care_status"] == "ADMITTED"
    assert admission["infection_status"] == "SURVEILLANCE_CLEAR"
    assert admission["high_risk_graduate"] is False
    for counter in (
        "patient_days",
        "central_line_days",
        "ventilator_days",
        "developmental_round_count",
        "kangaroo_care_sessions",
        "family_presence_minutes",
        "cluster_care_compliant_count",
        "light_cycling_compliant_count",
    ):
        assert admission[counter] == 0
    assertions.assert_close(admission["developmental_bundle_score"], 0)
    assertions.assert_close(admission["milk_administered_ml"], 0)
    assert admission["infection_confirmed_at"] is None
    assert admission["discharged_at"] is None
    assert admission["discharge_disposition"] is None


def test_milk_batch_opens_received_with_the_whole_volume_remaining(api, network):
    """PRD §3.7: "The caller's `X-User-ID` is stored as `received_by_user_id`, the batch opens at status `RECEIVED` with `verified_by_user_id` null, and `expires_at` is derived from the donor type: 96 hours — four days — after `expressed_at` for `MOTHERS_OWN`, and 24 hours after `expressed_at` for `DONOR_PASTEURIZED`."
    PRD §3.7: "`administered_ml` is the sum of volumes administered less the sum of volumes reversed; `discarded_ml` is the sum of volumes discarded; and `remaining_ml` is `volume_ml` less `administered_ml` less `discarded_ml`, at one decimal place."

    Design: Corner/state_machines/initial_state_of_every_declared_machine
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")

    resp = api.create_milk_batch(
        factories.milk_batch_payload(
            admission["id"], donor_type="MOTHERS_OWN", volume_ml=120.0, label_code="LBL-1"
        ),
        network["nurse"],
    )
    batch = validate_success(resp, 201)
    assertions.assert_milk_batch(batch)
    assert batch["status"] == "RECEIVED"
    assert batch["verified_by_user_id"] is None
    assertions.assert_close(batch["administered_ml"], 0.0)
    assertions.assert_close(batch["discarded_ml"], 0.0)
    assertions.assert_close(batch["remaining_ml"], 120.0)


def test_surveillance_report_opens_in_draft(api, network):
    """PRD §3.9: "The report opens at status `DRAFT`, and reports may be listed filtered by `unit_id`, `status`, `network_benchmark_flag` and `variant_applied`."

    Design: Corner/state_machines/initial_state_of_every_declared_machine
    """
    resp = api.create_surveillance_report(
        factories.surveillance_report_payload(
            network["unit_a_id"], reported_patient_days=10, reported_central_line_days=0
        ),
        network["dir_a"],
    )
    report = validate_success(resp, 201)
    assertions.assert_surveillance_report(report)
    assert report["status"] == "DRAFT"


def test_surge_escalation_opens_requested_and_grants_no_beds(api, network):
    """PRD §3.5: "The request opens at status `REQUESTED` and grants nothing until the network authorizes it."
    PRD §2.8: "Its `escalation_bed_count` is the sum of `authorized_beds` over the unit's surge escalations in status `ACTIVE`."

    Design: Corner/state_machines/initial_state_of_every_declared_machine
    """
    resp = api.create_surge_escalation(
        factories.surge_escalation_payload(
            network["unit_a_id"],
            requested_beds=2,
            effective_from="2026-08-02T00:00:00Z",
            effective_to="2026-08-03T00:00:00Z",
        ),
        network["dir_a"],
    )
    escalation = validate_success(resp, 201)
    assertions.assert_surge_escalation(escalation)
    assert escalation["status"] == "REQUESTED"

    unit = fixtures.read_unit(network)
    assertions.assert_unit_counts(unit, escalation=0, available=4)


# ---------------------------------------------------------------------------
# Designation review: submit, verify, certify
# ---------------------------------------------------------------------------


def test_submission_freezes_the_fully_compliant_score(api):
    """PRD §3.2: "A permitted submission increments `submission_round` by one, stamps `assessment_at` with the current clock instant, records the caller's `X-User-ID` as `submitted_by_user_id`, and freezes `required_nurse_count`, `staffing_subscore`, `equipment_subscore`, `volume_subscore` and `compliance_score` onto the review as they stand at that instant."
    PRD §3.2: "`compliance_score` is then 0.45 of the staffing subscore plus 0.35 of the equipment subscore plus 0.20 of the volume subscore, rounded half up to two decimals."

    Design: Corner/state_machines/review_certifies_at_requested_level_and_designates_the_unit
    """
    env = fixtures.setup_network(with_unit_b=False)
    review = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)

    resp = api.submit_designation_review(
        review["id"], {"assigned_nurse_count": 2}, env["dir_a"]
    )
    submitted = validate_success(resp)
    assertions.assert_designation_review(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_round"] == 1
    assert submitted["assessment_at"].startswith("2026-08-01T00:00:00")
    assert submitted["submitted_by_user_id"] == make_unit_scoped_user_id(
        env["unit_a_id"], "dir-1"
    )
    assertions.assert_close(submitted["staffing_subscore"], 100.00)
    assertions.assert_close(submitted["equipment_subscore"], 100.00)
    assertions.assert_close(submitted["volume_subscore"], 80.00)
    assertions.assert_close(submitted["compliance_score"], 96.00)


def test_certification_designates_the_unit_at_the_requested_level(api):
    """PRD §3.2: "From `VERIFIED`, certification moves the review `VERIFIED → CERTIFIED` and records the caller as `certified_by_user_id`, which must differ from `verified_by_user_id`."
    PRD §3.2: "The unit's `designated_level` is then written to that `outcome_level`, and its `designation_status` becomes `DESIGNATED` when the outcome equals the requested level and `CONDITIONAL` when it is the rung below."

    Design: Corner/state_machines/review_certifies_at_requested_level_and_designates_the_unit
    """
    env = fixtures.setup_network(with_unit_b=False)
    review = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)
    fixtures.submit_review(env, review["id"], assigned_nurse_count=2)

    verified = validate_success(
        api.verify_designation_review(review["id"], {}, env["admin"])
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == "net-1"

    certified = validate_success(
        api.certify_designation_review(review["id"], {}, env["admin_2"])
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "net-2"
    assert certified["outcome_level"] == "LEVEL_III"

    unit = fixtures.read_unit(env)
    assert unit["designated_level"] == "LEVEL_III"
    assert unit["designation_status"] == "DESIGNATED"
    assert unit["capability_level"] == "LEVEL_III"
    assert unit["effective_level"] == "LEVEL_III"
    assertions.assert_effective_level_consistent(unit)


def test_revoked_credential_halves_the_staffing_subscore_but_clears_the_floor(api):
    """PRD §3.1: "Revoking a credential sets `revoked_at` to the current clock instant, which makes the derived `status` `REVOKED`, and then re-derives the unit's `capability_level`, `effective_level` and `staffing_compliant`; if `effective_level` drops as a result, the capability cascade of §3.8 runs."
    PRD §3.2: "`staffing_subscore` is 100 multiplied by the credential coverage and again by the ratio factor, rounded half up to two decimals."
    PRD §3.2: "Verification moves it `SUBMITTED → VERIFIED` and records the caller as `verified_by_user_id`; it requires that `compliance_score` be at or above the `conditional_floor_score` of the standard for `requested_level`, and again that the caller differ from `submitted_by_user_id`."

    Design: Corner/state_machines/conditional_pass_grants_one_level_below_the_request
    """
    env = fixtures.setup_network(with_unit_b=False)
    review = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)

    revoked = validate_success(
        api.revoke_staff_credential(env["credentials"]["NEO_BOARD"]["id"], {}, env["dir_a"])
    )
    assertions.assert_staff_credential(revoked)
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"].startswith("2026-08-01T00:00:00")

    submitted = validate_success(
        api.submit_designation_review(review["id"], {}, env["dir_a"])
    )
    assertions.assert_close(submitted["staffing_subscore"], 50.00)
    assertions.assert_close(submitted["equipment_subscore"], 100.00)
    assertions.assert_close(submitted["volume_subscore"], 80.00)
    assertions.assert_close(submitted["compliance_score"], 73.50)

    verified = validate_success(
        api.verify_designation_review(review["id"], {}, env["admin"])
    )
    assert verified["status"] == "VERIFIED"


def test_conditional_certification_demotes_the_unit_one_rung(api):
    """PRD §3.2: "`outcome_level` becomes `requested_level` when `compliance_score` is at or above the standard's `min_compliance_score`, and otherwise the level one rung below `requested_level`."
    PRD §3.2: "The unit's `designated_level` is then written to that `outcome_level`, and its `designation_status` becomes `DESIGNATED` when the outcome equals the requested level and `CONDITIONAL` when it is the rung below."
    PRD §2.7: "`effective_level` is the lower-ranking of `designated_level` and `capability_level`, and it — not the designated level — gates every referral acceptance."

    Design: Corner/state_machines/conditional_pass_grants_one_level_below_the_request
    """
    env = fixtures.setup_network(with_unit_b=False)
    review = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)
    fixtures.submit_review(env, review["id"])
    validate_success(api.revoke_staff_credential(
        env["credentials"]["NEO_BOARD"]["id"], {}, env["dir_a"]
    ))
    fixtures.return_review(env, review["id"], "Credential evidence incomplete")
    fixtures.submit_review(env, review["id"])
    fixtures.verify_review(env, review["id"])

    certified = validate_success(
        api.certify_designation_review(review["id"], {}, env["admin_2"])
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["outcome_level"] == "LEVEL_II"

    unit = fixtures.read_unit(env)
    assert unit["designation_status"] == "CONDITIONAL"
    assert unit["designated_level"] == "LEVEL_II"
    assert unit["capability_level"] == "LEVEL_II"
    assert unit["effective_level"] == "LEVEL_II"
    assertions.assert_effective_level_consistent(unit)


def test_certify_from_submitted_denies_a_score_below_the_floor(api):
    """PRD §3.2: "From `SUBMITTED`, the same certification call instead moves the review `SUBMITTED → DENIED` when `compliance_score` is strictly below the standard's `conditional_floor_score`: `denial_basis` becomes `SCORE_BELOW_FLOOR`, `outcome_level` stays null, and the caller must differ from `submitted_by_user_id`."
    PRD §3.2: "Verification moves it `SUBMITTED → VERIFIED` and records the caller as `verified_by_user_id`; it requires that `compliance_score` be at or above the `conditional_floor_score` of the standard for `requested_level`, and again that the caller differ from `submitted_by_user_id`."

    Design: Corner/state_machines/certify_from_submitted_denies_a_below_floor_score
    """
    env = fixtures.setup_network(with_unit_b=False, credentials=(), equipment=())
    review = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)
    submitted = fixtures.submit_review(env, review["id"])
    assertions.assert_close(submitted["staffing_subscore"], 0.00)
    assertions.assert_close(submitted["equipment_subscore"], 0.00)
    assertions.assert_close(submitted["volume_subscore"], 80.00)
    assertions.assert_close(submitted["compliance_score"], 16.00)

    denied = validate_success(
        api.certify_designation_review(review["id"], {}, env["admin"])
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_basis"] == "SCORE_BELOW_FLOOR"
    assert denied["outcome_level"] is None
    assert denied["verified_by_user_id"] is None
    assert denied["certified_by_user_id"] is None


def test_denied_review_refuses_verification_and_leaves_the_unit_provisional(api):
    """PRD §3.2: "`CERTIFIED` and `DENIED` are both terminal."
    PRD §2.10: "Own state: the entity's own status must permit the trigger, including terminal-state lockdown and rejection of a repeated trigger, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/certify_from_submitted_denies_a_below_floor_score
    """
    env = fixtures.setup_network(with_unit_b=False, credentials=(), equipment=())
    review = fixtures.open_review(env, requested_level="LEVEL_III", assigned_nurse_count=2)
    fixtures.submit_review(env, review["id"])
    validate_success(api.certify_designation_review(review["id"], {}, env["admin"]))

    resp = api.verify_designation_review(review["id"], {}, env["admin_2"])
    validate_error(resp, ApiErrorId.INVALID_STATE)

    unit = fixtures.read_unit(env)
    assert unit["designation_status"] == "PROVISIONAL"
    assert unit["designated_level"] == "LEVEL_III"


def test_third_submission_denies_the_review_and_suspends_the_unit(api, network):
    """PRD §3.2: "When a review sitting in `RETURNED` already has `submission_round` equal to 2, the call moves it `RETURNED → DENIED` instead of to `SUBMITTED`: `submission_round` is set to 3, `denial_basis` is set to `ROUNDS_EXHAUSTED`, `outcome_level` is left null, the unit's `designation_status` becomes `SUSPENDED`, and every referral whose `receiving_unit_id` is that unit and whose status is `PENDING`, `INFO_REQUESTED` or `DEFERRED` is moved to `DIVERTED` with `decision_reason` `CAPABILITY_LOST`."

    Design: Corner/state_machines/third_submit_denies_the_review_and_suspends_the_unit
    """
    queued = fixtures.create_referral(network, case_reference="CASE-N1")
    review = fixtures.open_review(
        network, requested_level="LEVEL_III", assigned_nurse_count=2
    )

    first = fixtures.submit_review(network, review["id"])
    assert first["status"] == "SUBMITTED"
    assert first["submission_round"] == 1
    returned = fixtures.return_review(
        network, review["id"], "Nurse roster attachment missing"
    )
    assert returned["status"] == "RETURNED"
    second = fixtures.submit_review(network, review["id"])
    assert second["status"] == "SUBMITTED"
    assert second["submission_round"] == 2
    returned_again = fixtures.return_review(
        network, review["id"], "Equipment service log still unsigned"
    )
    assert returned_again["status"] == "RETURNED"

    denied = validate_success(
        api.submit_designation_review(review["id"], {}, network["dir_a"])
    )
    assert denied["status"] == "DENIED"
    assert denied["submission_round"] == 3
    assert denied["denial_basis"] == "ROUNDS_EXHAUSTED"
    assert denied["outcome_level"] is None

    unit = fixtures.read_unit(network)
    assert unit["designation_status"] == "SUSPENDED"

    diverted = fixtures.read_referral(network, queued["id"])
    assert diverted["status"] == "DIVERTED"
    assert diverted["decision_reason"] == "CAPABILITY_LOST"


def test_suspended_unit_refuses_a_fresh_acceptance(api, network):
    """PRD §2.7: "A `SUSPENDED` unit may not accept referrals; the attempt is refused with `ERR_UNIT_SUSPENDED` (HTTP 422)."
    PRD §3.4: "The receiving unit's `designation_status` must not be `SUSPENDED`, or the acceptance is refused with `ERR_UNIT_SUSPENDED`."

    Design: Corner/state_machines/third_submit_denies_the_review_and_suspends_the_unit
    """
    review = fixtures.open_review(
        network, requested_level="LEVEL_III", assigned_nurse_count=2
    )
    fixtures.submit_review(network, review["id"])
    fixtures.return_review(network, review["id"], "Nurse roster attachment missing")
    fixtures.submit_review(network, review["id"])
    fixtures.return_review(network, review["id"], "Equipment service log still unsigned")
    validate_success(api.submit_designation_review(review["id"], {}, network["dir_a"]))

    referral = fixtures.create_referral(network, case_reference="CASE-N3")
    unit_version = fixtures.read_unit_version(network, headers=network["intake_a"])
    resp = api.accept_referral(
        referral["id"],
        factories.accept_referral_payload(unit_version),
        network["intake_a"],
    )
    validate_error(resp, ApiErrorId.UNIT_SUSPENDED)

    still_pending = fixtures.read_referral(network, referral["id"])
    assert still_pending["status"] == "PENDING"
    assert still_pending["reservation_id"] is None

    unit = fixtures.read_unit(network)
    assertions.assert_unit_counts(unit, held=0, occupied=0, available=4)


# ---------------------------------------------------------------------------
# Referral transition table: lockdown, repeated triggers, out-of-state triggers
# ---------------------------------------------------------------------------


def test_accepting_an_already_accepted_referral_is_refused(api, network):
    """PRD §3.4: "An `IntakeNeonatologist` acting for the receiving unit accepts a referral sitting in `PENDING`, quoting `expected_unit_version` as the only body field."
    PRD §2.10: "Own state: the entity's own status must permit the trigger, including terminal-state lockdown and rejection of a repeated trigger, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/terminal_lockdown_and_repeat_trigger_rejection
    """
    referral, accepted = fixtures.hold_bed(network, case_reference="CASE-N1")
    unit_version = fixtures.read_unit_version(network, headers=network["intake_a"])

    resp = api.accept_referral(
        referral["id"],
        factories.accept_referral_payload(unit_version),
        network["intake_a"],
    )
    validate_error(resp, ApiErrorId.INVALID_STATE)

    assert fixtures.read_referral(network, referral["id"])["status"] == "ACCEPTED"
    reservation = fixtures.read_reservation(network, accepted["reservation_id"])
    assert reservation["status"] == "HELD"
    assertions.assert_unit_counts(
        fixtures.read_unit(network), held=1, occupied=0, available=3
    )


def test_withdrawal_releases_the_hold_once_and_then_locks_the_referral(api, network):
    """PRD §3.3: "The referring side may withdraw, moving the referral to `WITHDRAWN` from `PENDING`, `INFO_REQUESTED`, `DEFERRED` or `ACCEPTED` with `decision_reason` `FAMILY_CHOICE`; if a `HELD` reservation exists it is moved to `RELEASED` with `released_reason` `REFERRAL_WITHDRAWN`, and the receiving unit's `version` advances by one in exactly that case."
    PRD §3.3: "`DECLINED`, `DIVERTED`, `WITHDRAWN`, `REVOKED`, `SUPERSEDED` and `COMPLETED` are all terminal statuses for a referral."

    Design: Corner/state_machines/terminal_lockdown_and_repeat_trigger_rejection
    """
    referral, accepted = fixtures.hold_bed(network, case_reference="CASE-N1")

    withdrawn = validate_success(
        api.withdraw_referral(referral["id"], {}, network["ref_b"])
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["decision_reason"] == "FAMILY_CHOICE"
    reservation = fixtures.read_reservation(network, accepted["reservation_id"])
    assert reservation["status"] == "RELEASED"
    assert reservation["released_reason"] == "REFERRAL_WITHDRAWN"

    repeat = api.withdraw_referral(referral["id"], {}, network["ref_b"])
    validate_error(repeat, ApiErrorId.INVALID_STATE)

    unit = fixtures.read_unit(network)
    assertions.assert_unit_counts(unit, held=0, occupied=0, available=4)


def test_pending_referral_rejects_provide_info_and_revoke_acceptance(api, network):
    """PRD §3.3: "The referring side answers by supplying any of `support_modality`, `birth_weight_grams`, `gestational_age_weeks`, `diagnoses` and `planned_surgery`, each optional, which moves the referral `INFO_REQUESTED → PENDING`, increments `info_request_rounds` by one, clears `requested_items` back to null, applies the supplied clinical values, and then recomputes `required_level`, `level_basis`, `maternal_transfer_preferred` and `triage_priority` from the revised inputs — so an answer can raise or lower the level the case demands."
    PRD §3.4: "It moves the referral `ACCEPTED → REVOKED`, requires `expected_unit_version`, and is refused with `ERR_DEPENDENT_STATE_INVALID` when any transport run against that referral's reservation is in `GROUND_ROLLING`, `AIR_LAUNCHED`, `ON_SCENE`, `STABILIZING` or `EN_ROUTE` — a crew already on the road cannot have its destination taken away."
    PRD §2.10: "Own state: the entity's own status must permit the trigger, including terminal-state lockdown and rejection of a repeated trigger, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/triggers_absent_from_the_transition_list_are_rejected
    """
    referral = fixtures.create_referral(network, case_reference="CASE-N1")

    provide = api.provide_referral_info(
        referral["id"],
        factories.provide_info_payload(support_modality="CPAP"),
        network["ref_b"],
    )
    validate_error(provide, ApiErrorId.INVALID_STATE)

    unit_version = fixtures.read_unit_version(network, headers=network["intake_a"])
    revoke = api.revoke_referral_acceptance(
        referral["id"],
        factories.accept_referral_payload(unit_version),
        network["intake_a"],
    )
    validate_error(revoke, ApiErrorId.INVALID_STATE)

    after = fixtures.read_referral(network, referral["id"])
    assert after["status"] == "PENDING"
    assert after["info_request_rounds"] == 0
    assert after["support_modality"] == "ROOM_AIR"


def test_draft_review_rejects_verification_and_return(api, network):
    """PRD §3.2: "Returning a submission moves it `SUBMITTED → RETURNED` and records the supplied `return_reason` free text; the caller's `X-User-ID` must differ from `submitted_by_user_id`."
    PRD §3.2: "Verification moves it `SUBMITTED → VERIFIED` and records the caller as `verified_by_user_id`; it requires that `compliance_score` be at or above the `conditional_floor_score` of the standard for `requested_level`, and again that the caller differ from `submitted_by_user_id`."

    Design: Corner/state_machines/triggers_absent_from_the_transition_list_are_rejected
    """
    review = fixtures.open_review(
        network, requested_level="LEVEL_III", assigned_nurse_count=2
    )

    verify = api.verify_designation_review(review["id"], {}, network["admin"])
    validate_error(verify, ApiErrorId.INVALID_STATE)

    returned = api.return_designation_review(
        review["id"], factories.review_return_payload("Too early"), network["admin"]
    )
    validate_error(returned, ApiErrorId.INVALID_STATE)

    after = validate_success(api.get_designation_review(review["id"], network["admin"]))
    assert after["status"] == "DRAFT"
    assert after["submission_round"] == 0


def test_acceptance_is_refused_when_the_receiving_unit_cannot_deliver_the_level(
    api, network
):
    """PRD §3.4: "The unit's `effective_level` must rank at or above the referral's `required_level`, or the acceptance is refused with `ERR_LEVEL_CAPABILITY_INSUFFICIENT` — note that this reads the *effective* level of §2.7, so a unit designated `LEVEL_III` whose ventilator is out of service cannot accept a `LEVEL_III` case."
    PRD §3.3: "An antenatal `LEVEL_III` case at 30.0 weeks and 1300 grams scores 78.75; an inbound `LEVEL_III` case at 29.0 weeks and 1200 grams scores 71.25, as does an inbound `LEVEL_III` case at 30.0 weeks and 1250 grams — ties are real and are broken by the rules in §3.4."
    PRD §3.4: "The referral's `reservation_id` is a read-only pointer, derived from the reservations that name the referral rather than stored as a foreign key: it names the referral's current `HELD` or `OCCUPIED` reservation, or the most recently released one when none is live, and stays null while the referral has never been accepted."

    Design: Corner/state_machines/accept_is_guarded_by_the_receiving_units_capability
    """
    referral = fixtures.create_referral(
        network,
        case_reference="CASE-G1",
        referring_unit_id=network["unit_a_id"],
        receiving_unit_id=network["unit_b_id"],
    )
    assert referral["required_level"] == "LEVEL_III"
    assertions.assert_close(referral["triage_priority"], 71.25)

    before = fixtures.read_unit(network, network["unit_b_id"])
    assert before["effective_level"] == "LEVEL_I"

    resp = api.accept_referral(
        referral["id"],
        factories.accept_referral_payload(before["version"]),
        network["intake_b"],
    )
    validate_error(resp, ApiErrorId.LEVEL_CAPABILITY_INSUFFICIENT)

    after_referral = fixtures.read_referral(network, referral["id"])
    assert after_referral["status"] == "PENDING"
    assert after_referral["reservation_id"] is None

    after = fixtures.read_unit(network, network["unit_b_id"])
    assert after["version"] == before["version"]
    assertions.assert_unit_counts(after, held=0, occupied=0, available=6)


# ---------------------------------------------------------------------------
# Capability cascade and ledger synchronisation
# ---------------------------------------------------------------------------


def test_credential_revocation_diverts_the_held_referral(api, network):
    """PRD §3.8: "Revoking a credential runs the same propagation: `capability_level`, `effective_level` and `staffing_compliant` are re-derived, and where `effective_level` drops, the same referral, reservation, transport and admission consequences follow."
    PRD §2.7: "A unit's `designation_status` is separate from its level and takes one of four values: `PROVISIONAL` on registration, `DESIGNATED` after a fully passing certification, `CONDITIONAL` after a certification that granted one level less than requested or after an equipment loss that broke the standard for the designated level, and `SUSPENDED` after a review exhausts its submission rounds."

    Design: Corner/state_machines/credential_revocation_cascades_down_to_referral_and_admission
    """
    referral, accepted = fixtures.hold_bed(network, case_reference="CASE-N1")

    validate_success(
        api.revoke_staff_credential(
            network["credentials"]["NEO_BOARD"]["id"], {}, network["dir_a"]
        )
    )

    unit = fixtures.read_unit(network)
    assert unit["capability_level"] == "LEVEL_II"
    assert unit["effective_level"] == "LEVEL_II"
    assert unit["staffing_compliant"] is False
    assert unit["designated_level"] == "LEVEL_III"
    assert unit["designation_status"] == "PROVISIONAL"

    diverted = fixtures.read_referral(network, referral["id"])
    assert diverted["status"] == "DIVERTED"
    assert diverted["decision_reason"] == "CAPABILITY_LOST"

    reservation = fixtures.read_reservation(network, accepted["reservation_id"])
    assert reservation["status"] == "RELEASED"
    assert reservation["released_reason"] == "CAPABILITY_LOST"


def test_credential_revocation_requires_back_transfer_but_spares_a_completed_referral(
    api, network
):
    """PRD §3.8: "When a unit loses capability and an admitted infant's `current_care_level` now outranks the unit's new `effective_level`, the admission is moved `ADMITTED → BACK_TRANSFER_REQUIRED` or `STABILIZED → BACK_TRANSFER_REQUIRED` by the cascade described below."
    PRD §3.8: "Revoking a credential runs the same propagation: `capability_level`, `effective_level` and `staffing_compliant` are re-derived, and where `effective_level` drops, the same referral, reservation, transport and admission consequences follow."

    Design: Corner/state_machines/credential_revocation_cascades_down_to_referral_and_admission
    """
    referral = fixtures.create_referral(network, case_reference="CASE-N2")
    fixtures.accept_referral(network, referral["id"])
    admission = fixtures.admit(network, referral["id"])

    validate_success(
        api.revoke_staff_credential(
            network["credentials"]["NEO_BOARD"]["id"], {}, network["dir_a"]
        )
    )

    after = fixtures.read_admission(network, admission["id"])
    assert after["care_status"] == "BACK_TRANSFER_REQUIRED"
    assert after["current_care_level"] == "LEVEL_III"

    assert fixtures.read_referral(network, referral["id"])["status"] == "COMPLETED"

    unit = fixtures.read_unit(network)
    assertions.assert_unit_counts(unit, held=0, occupied=1, available=3)


def test_admission_completes_the_referral_and_occupies_the_hold(api, network):
    """PRD §3.7: "The referral is moved `ACCEPTED → COMPLETED` and its `HELD` reservation to `OCCUPIED` with `released_reason` `ADMITTED`; the bed has not been freed, it has changed category, and the ledger invariant of §2.8 holds throughout."
    PRD §3.7: "The new admission takes its `unit_id` from the referral's `receiving_unit_id`, copies `gestational_age_weeks` and `birth_weight_grams` from the referral, initialises `current_weight_grams` to that birth weight and `support_modality` from the referral's, and sets `transport_run_id` to the run that brought the infant when an `ARRIVED` run exists for the reservation and null otherwise."

    Design: Corner/state_machines/admission_syncs_the_units_bed_ledger
    """
    referral, accepted = fixtures.hold_bed(network, case_reference="CASE-N1")

    resp = api.create_admission(
        factories.admission_payload(referral["id"]), network["intake_a"]
    )
    admission = validate_success(resp, 201)
    assertions.assert_admission(admission)
    assert admission["care_status"] == "ADMITTED"
    assert admission["unit_id"] == network["unit_a_id"]
    assert admission["referral_id"] == referral["id"]
    assert admission["version"] == 1
    assert admission["transport_run_id"] is None
    assert admission["current_weight_grams"] == 1200
    assert admission["current_care_level"] == "LEVEL_III"

    assert fixtures.read_referral(network, referral["id"])["status"] == "COMPLETED"

    reservation = fixtures.read_reservation(network, accepted["reservation_id"])
    assert reservation["status"] == "OCCUPIED"
    assert reservation["released_reason"] == "ADMITTED"


def test_admission_moves_a_bed_between_ledger_buckets(api, network):
    """PRD §2.8: "And `available_bed_count` is the base staffed bed target plus the escalation bed count, minus the occupied bed count, minus the held bed count."
    PRD §2.8: "The invariant that must hold after every single operation is that `staffed_bed_target` plus `escalation_bed_count` equals `occupied_bed_count` plus `held_bed_count` plus `available_bed_count`."
    PRD §2.6: "The operations that advance a unit's `version`, and therefore invalidate a quoted value, are: accepting a referral; revoking an acceptance; withdrawing a referral in the case where that withdrawal releases a held reservation; admitting an infant, both for the hold-to-occupied conversion and for the back-transfer cascade at the source unit; discharging an admission; authorizing a surge escalation; standing a surge escalation down; editing the unit's capacity profile; certifying a designation review; and the capacity sweep, once per unit it changes."

    Design: Corner/state_machines/admission_syncs_the_units_bed_ledger
    """
    referral, _accepted = fixtures.hold_bed(network, case_reference="CASE-N1")
    while_held = fixtures.read_unit(network)
    assertions.assert_unit_counts(while_held, held=1, occupied=0, available=3)

    validate_success(
        api.create_admission(
            factories.admission_payload(referral["id"]), network["intake_a"]
        ),
        201,
    )

    unit = fixtures.read_unit(network)
    assertions.assert_unit_counts(
        unit, held=0, occupied=1, available=3, posture="OPEN"
    )
    assert unit["version"] == 3


# ---------------------------------------------------------------------------
# Transport abort compensation and the capacity sweep
# ---------------------------------------------------------------------------


def test_transport_abort_returns_the_case_and_releases_the_hold(api):
    """PRD §3.6: "An abort releases the reservation to `RELEASED` with `released_reason` `TRANSPORT_ABORTED`, returns its referral `ACCEPTED → PENDING` with `decision_reason` `TRANSPORT_ABORTED` so the case can be placed again, and sets the isolette's `decontamination_ready_at` to the current clock instant advanced by `decontamination_minutes`."
    PRD §3.6: "Its `decontamination_minutes` is derived from the mode: 45 minutes for a `GROUND` run, and 90 minutes — an hour and a half — for both `ROTOR_WING` and `FIXED_WING`, because an aircraft cabin takes longer to turn round than an ambulance."

    Design: Corner/state_machines/transport_abort_compensates_without_promoting_the_queue
    """
    env = fixtures.setup_network(with_isolette=True)
    fixtures.patch_unit(env, staffed_bed_target=1)
    referral, accepted = fixtures.hold_bed(env, case_reference="CASE-N1")
    run = fixtures.create_run(env, accepted["reservation_id"], mode="GROUND")

    resp = api.abort_transport_run(
        run["id"], factories.abort_payload("CREW_UNAVAILABLE"), env["coord"]
    )
    aborted = validate_success(resp)
    assert aborted["status"] == "ABORTED"
    assert aborted["abort_reason"] == "CREW_UNAVAILABLE"

    reservation = fixtures.read_reservation(env, accepted["reservation_id"])
    assert reservation["status"] == "RELEASED"
    assert reservation["released_reason"] == "TRANSPORT_ABORTED"

    returned = fixtures.read_referral(env, referral["id"])
    assert returned["status"] == "PENDING"
    assert returned["decision_reason"] == "TRANSPORT_ABORTED"

    isolette = validate_success(
        api.get_equipment_asset(env["assets"]["TRANSPORT_ISOLETTE"]["id"], env["admin"])
    )
    assert isolette["decontamination_ready_at"].startswith("2026-08-01T00:45:00")


def test_transport_abort_does_not_promote_the_deferral_queue(api):
    """PRD §3.4: "It deliberately does **not** fire from a transport abort or from a revocation of acceptance."
    PRD §3.4: "Deferral moves a referral `PENDING → DEFERRED`, is permitted only when the unit's `available_bed_count` is at or below zero, records `decision_reason` `NO_BED`, and causes the unit's `deferral_queue_depth` to be re-derived."

    Design: Corner/state_machines/transport_abort_compensates_without_promoting_the_queue
    """
    env = fixtures.setup_network(with_isolette=True)
    fixtures.patch_unit(env, staffed_bed_target=1)
    _referral, accepted = fixtures.hold_bed(env, case_reference="CASE-N1")
    queued = fixtures.create_referral(env, case_reference="CASE-N2")
    deferred = validate_success(
        api.defer_referral(queued["id"], {}, env["intake_a"])
    )
    assert deferred["status"] == "DEFERRED"
    assert deferred["decision_reason"] == "NO_BED"
    run = fixtures.create_run(env, accepted["reservation_id"], mode="GROUND")

    validate_success(
        api.abort_transport_run(
            run["id"], factories.abort_payload("CREW_UNAVAILABLE"), env["coord"]
        )
    )

    still_deferred = fixtures.read_referral(env, queued["id"])
    assert still_deferred["status"] == "DEFERRED"
    assert still_deferred["decision_reason"] == "NO_BED"
    assert still_deferred["reservation_id"] is None

    unit = fixtures.read_unit(env)
    assertions.assert_unit_counts(unit, held=0, occupied=0, available=1)
    assert unit["deferral_queue_depth"] == 1


def test_sweep_expires_the_hold_at_exactly_its_deadline(api):
    """PRD §2.5: "First, every bed reservation still in `HELD` whose `expires_at` is at or before the current clock instant is moved to `EXPIRED` with `released_reason` set to `HOLD_EXPIRED`, and its referral is moved to `DIVERTED` with `decision_reason` set to `HOLD_EXPIRED`."
    PRD §3.4: "A reservation whose `expires_at` is at or before the current clock instant is expired — at exactly `expires_at` it is expired, one second earlier it is not — yet its stored `status` stays `HELD` until the capacity sweep moves it to `EXPIRED` with `released_reason` `HOLD_EXPIRED` and diverts its referral `ACCEPTED → DIVERTED` with `decision_reason` `HOLD_EXPIRED`."

    Design: Corner/state_machines/sweep_expires_the_hold_then_promotes_the_queue
    """
    env = fixtures.setup_network()
    fixtures.patch_unit(env, staffed_bed_target=1)
    referral, accepted = fixtures.hold_bed(env, case_reference="CASE-N1")
    queued = fixtures.create_referral(env, case_reference="CASE-N2")
    validate_success(api.defer_referral(queued["id"], {}, env["intake_a"]))
    fixtures.set_clock("2026-08-01T04:00:00Z")

    resp = api.run_capacity_sweep(
        factories.capacity_sweep_payload(env["unit_a_id"]), env["admin"]
    )
    result = validate_success(resp)
    assertions.assert_sweep_result(
        result,
        holds_expired=1,
        escalations_expired=0,
        enrollments_lapsed=0,
        referrals_promoted=1,
        units_touched=1,
    )

    reservation = fixtures.read_reservation(env, accepted["reservation_id"])
    assert reservation["status"] == "EXPIRED"
    assert reservation["released_reason"] == "HOLD_EXPIRED"

    diverted = fixtures.read_referral(env, referral["id"])
    assert diverted["status"] == "DIVERTED"
    assert diverted["decision_reason"] == "HOLD_EXPIRED"


def test_sweep_promotes_the_deferred_case_onto_the_freed_bed(api):
    """PRD §2.5: "Fourth, for every unit whose bed picture the first three passes changed, the deferral-queue promotion of §3.4 is run."
    PRD §3.4: "Promotion then loops: while the unit's committed `available_bed_count` is at least 1 and the pool is non-empty, the top-ranked candidate is promoted `DEFERRED → ACCEPTED`, a `HELD` reservation is created for it exactly as an ordinary acceptance would (same waterfall `bed_class`, same `held_at`, same kind-dependent `expires_at`), its `decision_reason` is cleared back to null, the unit's `version` advances by one, the ledger is re-derived, and the loop continues."
    PRD §2.8: "When `available_bed_count` is at or below zero, the posture is `CLOSED`."

    Design: Corner/state_machines/sweep_expires_the_hold_then_promotes_the_queue
    """
    env = fixtures.setup_network()
    fixtures.patch_unit(env, staffed_bed_target=1)
    fixtures.hold_bed(env, case_reference="CASE-N1")
    queued = fixtures.create_referral(env, case_reference="CASE-N2")
    validate_success(api.defer_referral(queued["id"], {}, env["intake_a"]))
    fixtures.set_clock("2026-08-01T04:00:00Z")

    validate_success(
        api.run_capacity_sweep(
            factories.capacity_sweep_payload(env["unit_a_id"]), env["admin"]
        )
    )

    promoted = fixtures.read_referral(env, queued["id"])
    assert promoted["status"] == "ACCEPTED"
    assert promoted["decision_reason"] is None

    reservation = fixtures.read_reservation(env, promoted["reservation_id"])
    assert reservation["status"] == "HELD"
    assert reservation["bed_class"] == "STAFFED"
    assert reservation["held_at"].startswith("2026-08-01T04:00:00")
    assert reservation["expires_at"].startswith("2026-08-01T08:00:00")

    unit = fixtures.read_unit(env)
    assertions.assert_unit_counts(unit, held=1, occupied=0, available=0, posture="CLOSED")
    assert unit["deferral_queue_depth"] == 0
