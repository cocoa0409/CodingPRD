"""State machines that loop, that run two dimensions at once, or that branch apart."""

from test_helpers import (
    ERR_INFO_REQUEST_LIMIT_REACHED,
    assert_slot_conservation,
    candidate_sequence,
    chart_observation,
    cleared_referral,
    converted_case,
    evaluate_organ,
    find_offer,
    get_success_data,
    list_nok_contacts,
    observation_payload,
    open_match_run,
    open_nok_authorization,
    open_registry_authorization,
    read_authorization,
    read_case,
    read_referral,
    read_screening,
    record_nok_contact,
    register_organ,
    respond_to_offer,
    rule_screening,
    screened_referral,
    upload_document,
    validate_error,
)


# ---------------------------------------------------------------------------
# The information-request cycle, capped at two loops
# ---------------------------------------------------------------------------
def _screening_bounced(env, loops):
    """Bounce the screening ``loops`` times, closing each loop with a reassessment."""
    bundle = screened_referral(
        env,
        "2026-08-11T09:00:00Z",
        30,
        risk_factors=["HEMODIALYSIS_12MO"],
        patient_mrn="MRN-7401",
    )
    notes = ["social history incomplete", "confirm dialysis dates"]
    for index in range(loops):
        bounced = get_success_data(
            env.api.request_info(
                bundle.screening_id,
                env.director,
                {"info_request_note": notes[index]},
            )
        )
        assert bounced["status"] == "INFO_REQUESTED"
        assert bounced["info_request_count"] == index + 1
        current = read_screening(env, bundle.screening_id)
        bundle.screening = get_success_data(
            env.api.submit_risk_assessment(
                bundle.screening_id,
                {
                    "risk_factors": ["HEMODIALYSIS_12MO"],
                    "informant_reliability": "PRIMARY_NEXT_OF_KIN",
                    "expected_screening_version": current["version"],
                },
                env.coordinator,
            )
        )
        assert bundle.screening["status"] == "PENDING"
    return bundle


def test_each_info_request_loop_returns_the_screening_to_pending(env):
    """Two loops raise the counter and each fresh assessment closes the cycle.

    PRD 3.2: "The screening moves `PENDING → INFO_REQUESTED` and its
    `info_request_count` increases by one."
    PRD 3.2: "A fresh risk assessment closes the cycle by returning the
    screening `INFO_REQUESTED → PENDING`."

    Design: Difficulty/non_linear_state_machine/screening_info_request_cycle_capped_at_two_loops
    """
    bundle = _screening_bounced(env, loops=2)

    settled = read_screening(env, bundle.screening_id)
    assert settled["status"] == "PENDING"
    assert settled["info_request_count"] == 2


def test_third_info_request_is_refused_at_the_declared_budget(env):
    """A third bounce is refused and leaves the counter and the score untouched.

    PRD 3.2: "This is permitted at most twice per screening: an attempt made
    while `info_request_count` already stands at two is rejected with
    `ERR_INFO_REQUEST_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/screening_info_request_cycle_capped_at_two_loops
    """
    bundle = _screening_bounced(env, loops=2)

    refused = env.api.request_info(
        bundle.screening_id, env.director, {"info_request_note": "one more question"}
    )
    validate_error(refused, ERR_INFO_REQUEST_LIMIT_REACHED)

    settled = read_screening(env, bundle.screening_id)
    assert settled["info_request_count"] == 2
    assert settled["status"] == "PENDING"
    assert float(settled["risk_score"]) == 2.50


def test_screening_still_clears_after_the_cycle_is_exhausted(env):
    """Once the budget is spent the director may still rule the screening cleared.

    PRD 3.2: "A clearance moves the screening `PENDING → CLEARED` and
    propagates the referral `SCREENING → SCREEN_CLEARED`".

    Design: Difficulty/non_linear_state_machine/screening_info_request_cycle_capped_at_two_loops
    """
    bundle = _screening_bounced(env, loops=2)

    ruled = rule_screening(env, bundle.screening_id, "CLEARED", as_user="md-2")
    assert ruled["status"] == "CLEARED"
    assert ruled["decided_by_user_id"] == "md-2"
    assert read_referral(env, bundle.referral_id)["status"] == "SCREEN_CLEARED"


# ---------------------------------------------------------------------------
# The donor case's two independent dimensions
# ---------------------------------------------------------------------------
def _case_with_first_observation(env):
    bundle = converted_case(env, "2026-08-12T09:00:00Z", patient_mrn="MRN-7501")
    chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-12T08:30:00Z",
            map_mmhg=65,
            pao2_fio2_ratio=320,
            sodium=148,
            urine_output_ml_per_kg_hr=0.7,
            pressor_count=2,
        ),
    )
    return bundle


def test_physiologic_dimension_advances_while_allocation_stands_still(env):
    """Charting vitals moves the body dimension and leaves placement alone.

    PRD 2.8: "A `DonorCase` carries two **independent** status dimensions.
    `physiologic_status` describes the donor's body and takes the values
    `STABILIZING`, `OPTIMIZED`, `DECOMPENSATING` and `LOST`."
    PRD 2.8: "Neither dimension constrains the other directly; a donor may be
    `DECOMPENSATING` while its liver sits in `OFFERS_IN_FLIGHT`."

    Design: Difficulty/non_linear_state_machine/donor_case_parallel_dimensions_advance_independently
    """
    bundle = _case_with_first_observation(env)

    case = read_case(env, bundle.case_id)
    assert case["physiologic_status"] == "OPTIMIZED"
    assert case["allocation_status"] == "NOT_STARTED"
    assert case["case_posture"] == "OPEN"
    assert case["viability_index"] == 75


def test_allocation_dimension_advances_while_physiology_stands_still(env):
    """Opening a run and then improving the vitals move the dimensions separately.

    PRD 3.5: "the case's `allocation_status` advances from `NOT_STARTED` to
    `MATCH_RUN_OPEN` on the first run generated on any organ of the case and
    then onward to `OFFERS_IN_FLIGHT` once a pending offer exists".
    PRD 3.4: "an index of at least 70 gives `OPTIMIZED`, an index of at least
    40 gives `STABILIZING`, and anything lower gives `DECOMPENSATING`".

    Design: Difficulty/non_linear_state_machine/donor_case_parallel_dimensions_advance_independently
    """
    bundle = _case_with_first_observation(env)
    bundle.organs["KIDNEY_LEFT"] = register_organ(
        env, bundle.case_id, "KIDNEY_LEFT"
    )
    bundle.organs["KIDNEY_LEFT"] = evaluate_organ(
        env, bundle.organ_id("KIDNEY_LEFT"), "ALLOCATABLE"
    )
    bundle.run = open_match_run(
        env,
        bundle.organ_id("KIDNEY_LEFT"),
        candidate_sequence(2, 60),
        primary_offer_slots=1,
    )

    after_run = read_case(env, bundle.case_id)
    assert after_run["allocation_status"] == "OFFERS_IN_FLIGHT"
    assert after_run["physiologic_status"] == "OPTIMIZED"

    improved = chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-12T08:50:00Z",
            map_mmhg=72,
            pao2_fio2_ratio=320,
            sodium=140,
            urine_output_ml_per_kg_hr=0.6,
            pressor_count=1,
        ),
    )
    assert improved["viability_index_snapshot"] == 90
    assert improved["dmg_bundle_met"] is True

    after_observation = read_case(env, bundle.case_id)
    assert after_observation["allocation_status"] == "OFFERS_IN_FLIGHT"
    assert after_observation["physiologic_status"] == "OPTIMIZED"
    assert after_observation["viability_index"] == 90


def test_acceptance_advances_allocation_and_leaves_the_body_dimension_intact(env):
    """An acceptance settles placement without disturbing physiology or posture.

    PRD 3.6: "The case's `allocation_status` advances `OFFERS_IN_FLIGHT →
    ALLOCATED` and its `organs_accepted_count` increases by one."
    PRD 2.11: "for each match run, `pending_offer_count` plus `slots_free`
    always equals `primary_offer_slots`".

    Design: Difficulty/non_linear_state_machine/donor_case_parallel_dimensions_advance_independently
    """
    bundle = _case_with_first_observation(env)
    bundle.organs["KIDNEY_LEFT"] = register_organ(
        env, bundle.case_id, "KIDNEY_LEFT"
    )
    evaluate_organ(env, bundle.organ_id("KIDNEY_LEFT"), "ALLOCATABLE")
    bundle.run = open_match_run(
        env,
        bundle.organ_id("KIDNEY_LEFT"),
        candidate_sequence(2, 60),
        primary_offer_slots=1,
    )
    chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-12T08:50:00Z",
            map_mmhg=72,
            pao2_fio2_ratio=320,
            sodium=140,
            urine_output_ml_per_kg_hr=0.6,
            pressor_count=1,
        ),
    )

    offers = bundle.refresh_offers()
    assert find_offer(offers, 1)["status"] == "PENDING"
    assert find_offer(offers, 2)["status"] == "QUEUED"

    respond_to_offer(env, bundle.run_id, find_offer(offers, 1)["id"], "ACCEPT")

    case = read_case(env, bundle.case_id)
    assert case["allocation_status"] == "ALLOCATED"
    assert case["physiologic_status"] == "OPTIMIZED"
    assert case["case_posture"] == "OPEN"
    assert case["viability_index"] == 90
    assert case["dmg_bundle_met_count"] == 1
    assert case["observation_count"] == 2
    assert case["organs_accepted_count"] == 1

    run = bundle.refresh_run()
    assert run["pending_offer_count"] == 0
    assert run["slots_free"] == 1
    assert_slot_conservation(run)


# ---------------------------------------------------------------------------
# The two authorization branches and their disjoint side effects
# ---------------------------------------------------------------------------
def test_registry_branch_arrives_documentation_complete(env):
    """A registry hit files its own screenshot and needs no relative contacted.

    PRD 3.3: "its `required_document_types` becomes the single-member list
    containing `REGISTRY_SCREENSHOT`, that same `REGISTRY_SCREENSHOT` is added
    to `document_types_present` because the supplied reference is filed
    automatically, and `documentation_complete` becomes true".
    PRD 3.3: "The packet moves `PENDING_REGISTRY → REGISTRY_CONFIRMED`, its
    `authorization_basis` becomes `FIRST_PERSON_REGISTRY`".

    Design: Difficulty/non_linear_state_machine/authorization_registry_versus_nok_branch_side_effects
    """
    bundle = cleared_referral(env, "2026-08-13T09:00:00Z", patient_mrn="MRN-7601")
    packet = open_registry_authorization(
        env, bundle.referral_id, registry_document_ref="REG-7601"
    )

    assert packet["status"] == "REGISTRY_CONFIRMED"
    assert packet["authorization_basis"] == "FIRST_PERSON_REGISTRY"
    assert packet["required_document_types"] == ["REGISTRY_SCREENSHOT"]
    assert packet["document_types_present"] == ["REGISTRY_SCREENSHOT"]
    assert packet["documentation_complete"] is True
    assert packet["consent_recorded_by_user_id"] is None


def test_registry_branch_finalization_is_vacuous_on_segregation_of_duties(env):
    """With no consent-taker recorded, the opening specialist may finalize.

    PRD 2.9: "The second check is vacuous on the registry branch of
    authorization: a packet confirmed from the first-person registry never
    records a consent-taker, so `consent_recorded_by_user_id` is null and any
    specialist may finalize it."

    Design: Difficulty/non_linear_state_machine/authorization_registry_versus_nok_branch_side_effects
    """
    bundle = cleared_referral(env, "2026-08-13T09:00:00Z", patient_mrn="MRN-7601")
    packet = open_registry_authorization(
        env, bundle.referral_id, registry_document_ref="REG-7601"
    )

    finalized = get_success_data(
        env.api.finalize_authorization(packet["id"], env.auth_one)
    )
    assert finalized["status"] == "AUTHORIZED"
    assert finalized["finalized_by_user_id"] == "auth-1"


def test_nok_branch_refuses_finalization_until_both_documents_are_filed(env):
    """The consent alone leaves the packet incomplete and records the deficiency.

    PRD 3.3: "its `required_document_types` becomes the two-member list
    containing `SIGNED_CONSENT_FORM` and `WITNESS_ATTESTATION`, and
    `documentation_complete` becomes false".
    PRD 3.3: "the packet moves `NOK_CONSENTED → DOCUMENT_DEFICIENT` — the state
    change **is** recorded — and the caller nonetheless receives
    `ERR_AUTHORIZATION_DOCUMENTATION_INCOMPLETE`".

    Design: Difficulty/non_linear_state_machine/authorization_registry_versus_nok_branch_side_effects
    """
    bundle = cleared_referral(env, "2026-08-13T09:00:00Z", patient_mrn="MRN-7602")
    packet = open_nok_authorization(env, bundle.referral_id)

    assert packet["status"] == "NOK_REQUIRED"
    assert packet["authorization_basis"] == "LEGAL_NEXT_OF_KIN"
    assert packet["required_document_types"] == [
        "SIGNED_CONSENT_FORM",
        "WITNESS_ATTESTATION",
    ]
    assert packet["documentation_complete"] is False

    record_nok_contact(
        env,
        packet["id"],
        "SPOUSE",
        "CONSENT",
        contact_note="consent by telephone",
    )
    consented = read_authorization(env, packet["id"])
    assert consented["status"] == "NOK_CONSENTED"
    assert consented["consenting_rank"] == 1
    assert consented["highest_rank_attempted"] == 1

    refused = env.api.finalize_authorization(packet["id"], env.auth_two)
    validate_error(refused, "ERR_AUTHORIZATION_DOCUMENTATION_INCOMPLETE")
    assert read_authorization(env, packet["id"])["status"] == "DOCUMENT_DEFICIENT"


def test_nok_branch_closes_the_deficiency_cycle_and_finalizes(env):
    """Filing the two documents returns the packet and lets a second specialist finalize.

    PRD 3.3: "An upload onto a packet in `DOCUMENT_DEFICIENT` returns it
    `DOCUMENT_DEFICIENT → NOK_CONSENTED`, closing the deficiency cycle".
    PRD 3.3: "on the `LEGAL_NEXT_OF_KIN` basis, it is true exactly when both
    `SIGNED_CONSENT_FORM` and `WITNESS_ATTESTATION` appear in
    `document_types_present` **and** `witness_name` is non-null".

    Design: Difficulty/non_linear_state_machine/authorization_registry_versus_nok_branch_side_effects
    """
    bundle = cleared_referral(env, "2026-08-13T09:00:00Z", patient_mrn="MRN-7602")
    packet = open_nok_authorization(env, bundle.referral_id)
    record_nok_contact(
        env, packet["id"], "SPOUSE", "CONSENT", contact_note="consent by telephone"
    )
    env.api.finalize_authorization(packet["id"], env.auth_two)

    after_consent_form = upload_document(env, packet["id"], "SIGNED_CONSENT_FORM")
    assert after_consent_form["status"] == "NOK_CONSENTED"
    assert after_consent_form["documentation_complete"] is False

    after_attestation = upload_document(
        env, packet["id"], "WITNESS_ATTESTATION", witness_name="R. Vega"
    )
    assert after_attestation["documentation_complete"] is True

    finalized = get_success_data(
        env.api.finalize_authorization(packet["id"], env.auth_two)
    )
    assert finalized["status"] == "AUTHORIZED"
    assert finalized["finalized_by_user_id"] == "auth-2"


def test_the_two_branches_carry_disjoint_side_effects(env):
    """The registry packet gains no relatives and the kin packet no screenshot.

    PRD 3.3: "returned a match for the decedent. The two branches carry
    deliberately **disjoint** consequences."
    PRD 3.3: "This branch arrives documentation-complete and needs no relatives
    contacted at all."

    Design: Difficulty/non_linear_state_machine/authorization_registry_versus_nok_branch_side_effects
    """
    registry_bundle = cleared_referral(
        env, "2026-08-13T09:00:00Z", patient_mrn="MRN-7601"
    )
    registry_packet = open_registry_authorization(
        env, registry_bundle.referral_id, registry_document_ref="REG-7601"
    )

    kin_bundle = cleared_referral(env, "2026-08-13T09:00:00Z", patient_mrn="MRN-7602")
    kin_packet = open_nok_authorization(env, kin_bundle.referral_id)
    record_nok_contact(
        env, kin_packet["id"], "SPOUSE", "CONSENT", contact_note="consent by telephone"
    )
    upload_document(env, kin_packet["id"], "SIGNED_CONSENT_FORM")
    upload_document(
        env, kin_packet["id"], "WITNESS_ATTESTATION", witness_name="R. Vega"
    )

    assert list_nok_contacts(env, registry_packet["id"]) == []
    assert len(list_nok_contacts(env, kin_packet["id"])) == 1

    kin_final = read_authorization(env, kin_packet["id"])
    assert "REGISTRY_SCREENSHOT" not in kin_final["document_types_present"]
    registry_final = read_authorization(env, registry_packet["id"])
    assert registry_final["document_types_present"] == ["REGISTRY_SCREENSHOT"]
