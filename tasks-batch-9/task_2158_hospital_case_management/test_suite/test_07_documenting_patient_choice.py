"""Documenting the patient's placement choice: the compliance attestation, the two
coverage gates, and the four-hop cascade a successful choice fires."""
from test_helpers import (
    CASE_MANAGER,
    ApiErrorId,
    document_choice_payload,
    make_liaison_headers,
    make_payer_rep_headers,
    open_barrier,
    place_offer,
    read_barriers,
    read_episode,
    read_offer,
    read_provider,
    read_referral,
    set_logical_clock,
    setup_choice_pending_referral,
    submit_authorization,
    validate_error,
    validate_success,
)

LAKESIDE = {
    "name": "Lakeside Choice", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}
MERIDIAN_AUTH_REQUIRED = {
    "name": "Meridian Health", "coinsurance_pct": 0.200,
    "snf_auth_required": True, "hh_auth_required": True, "auth_expiry_days": 30,
}


def _bed_availability_case(mrn):
    """A choice-pending SNF referral on an episode carrying one open
    BED_AVAILABILITY barrier that has accrued exactly 48 hours."""
    env = setup_choice_pending_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": mrn, "full_name": "Gio Petrova", "date_of_birth": "1947-02-14",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"daily_rate_cents": 30000},
    )
    env["bed_barrier"] = open_barrier(
        env["episode"]["id"], barrier_code="BED_AVAILABILITY", severity="HIGH",
        delay_reason_code="AWAITING_BED",
    )
    set_logical_clock("2026-08-03T00:00:00Z")
    return env


def test_documenting_a_choice_accepts_the_offer_and_places_the_referral(api):
    """PRD §3.5: "A successful documentation of choice fires a four-hop cascade. The
    chosen offer moves `OFFERED → ACCEPTED_BY_PATIENT`; its provider's
    `offers_accepted_count` increments and `acceptance_rate_pct` is recomputed; and the
    bed-hold interval stays occupied, so `held_bed_units` for that provider is unchanged."
    PRD §3.5: "The referral moves `CHOICE_PENDING → PLACED`, recording
    `chosen_bed_offer_id`, `choice_basis` and `patient_choice_attested`, and its `version`
    advances by one."

    Design: Difficulty/transitive_cascade/choice_documentation_cascade_depth_four_to_delay_union
    """
    env = _bed_availability_case("MRN-4001")

    placed = validate_success(
        api.document_choice(
            env["referral"]["id"],
            document_choice_payload(env["offer"]["id"], choice_basis="CLINICAL_MATCH"),
            CASE_MANAGER,
        )
    )

    assert placed["status"] == "PLACED"
    assert placed["chosen_bed_offer_id"] == env["offer"]["id"]
    assert placed["choice_basis"] == "CLINICAL_MATCH"
    assert placed["patient_choice_attested"] is True
    assert read_offer(env["offer"]["id"])["status"] == "ACCEPTED_BY_PATIENT"

    provider = read_provider(env["provider_a"]["id"])
    assert provider["held_bed_units"] == 1, "an accepted hold stays occupied"
    assert provider["offers_accepted_count"] == 1
    assert provider["acceptance_rate_pct"] == 100.0


def test_the_choice_cascade_resolves_the_bed_barrier_and_closes_the_delay_union(api):
    """PRD §3.5: "Then every barrier on the episode with `barrier_code` of
    `BED_AVAILABILITY` whose `status` is `OPEN` or `MITIGATING` moves to `RESOLVED` with
    `clock_stop_at` at the logical clock instant — and that resolution in turn recomputes
    the episode's `avoidable_delay_hours` and `barrier_posture`."
    PRD §3.3: "For each remaining barrier the interval starts at `clock_start_at` and ends
    at `clock_stop_at` when one is set, or at the logical clock now when the barrier is
    still running."
    PRD §3.3: "Consider the set of that episode's barriers whose `status` is `OPEN` or
    `MITIGATING`; `RESOLVED` and `WAIVED` rows never participate. When that set is empty,
    `barrier_posture` is `CLEAR`."

    Design: Difficulty/transitive_cascade/choice_documentation_cascade_depth_four_to_delay_union
    """
    env = _bed_availability_case("MRN-4002")

    validate_success(
        api.document_choice(
            env["referral"]["id"],
            document_choice_payload(env["offer"]["id"], choice_basis="CLINICAL_MATCH"),
            CASE_MANAGER,
        )
    )

    barrier = {row["id"]: row for row in read_barriers(env["episode"]["id"])}[
        env["bed_barrier"]["id"]
    ]
    assert barrier["status"] == "RESOLVED"
    assert barrier["clock_stop_at"] == "2026-08-03T00:00:00.000Z"

    episode = read_episode(env["episode"]["id"])
    assert episode["avoidable_delay_hours"] == 48.0, (
        "the closed [08-01, 08-03) interval is exactly 48 hours, got "
        f"{episode['avoidable_delay_hours']}"
    )
    assert episode["barrier_posture"] == "CLEAR"
    assert episode["case_status"] == "PLANNING", (
        "the cascade never touches the case_status axis"
    )


def test_an_unattested_choice_is_refused_before_any_coverage_check(api):
    """PRD §3.5: "Then, **before any coverage or cost consideration whatsoever**, the
    compliance attestation is tested: `patient_choice_attested` must be true in the body,
    and a false or absent attestation is `ERR_CHOICE_NOT_ATTESTED` (HTTP 422). This
    ordering is deliberate — an unattested choice must never be masked by a coverage
    problem discovered later."

    Design: Difficulty/priority_pair_validation_conflict/attestation_safety_beats_authorization_fiscal_on_document_choice
    """
    env = setup_choice_pending_referral(
        payer=dict(MERIDIAN_AUTH_REQUIRED),
        patient={
            "mrn": "MRN-5001", "full_name": "Ida Whitmore", "date_of_birth": "1944-12-01",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"daily_rate_cents": 30000},
    )

    response = api.document_choice(
        env["referral"]["id"],
        document_choice_payload(
            env["offer"]["id"], patient_choice_attested=False,
            choice_basis="PATIENT_PREFERENCE",
        ),
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_CHOICE_NOT_ATTESTED, 422)
    assert response.json()["data"]["error_id"] != "ERR_AUTHORIZATION_REQUIRED"
    referral = read_referral(env["referral"]["id"])
    assert referral["status"] == "CHOICE_PENDING"
    assert referral["patient_choice_attested"] is False
    assert read_offer(env["offer"]["id"])["status"] == "OFFERED", "no side effect fired"


def test_the_coverage_gap_the_attestation_pre_empted_is_genuinely_present(api):
    """PRD §3.5: "Then, **before any coverage or cost consideration whatsoever**, the
    compliance attestation is tested: `patient_choice_attested` must be true in the body,
    and a false or absent attestation is `ERR_CHOICE_NOT_ATTESTED` (HTTP 422). This
    ordering is deliberate — an unattested choice must never be masked by a coverage
    problem discovered later."
    PRD §3.5: "Only after the attestation passes are the two coverage gates evaluated, and
    in this order: first, when the episode's payer requires authorization for the chosen
    level of care — `snf_auth_required` governing `SNF`, `IRF` and `LTACH`,
    `hh_auth_required` governing `HOME_HEALTH` — there must exist an authorization request
    on this episode for the chosen offer's provider whose `status` is `APPROVED` or
    `PARTIALLY_APPROVED` and whose `expires_at` is strictly later than the logical clock
    now, or the request is `ERR_AUTHORIZATION_REQUIRED` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/attestation_safety_beats_authorization_fiscal_on_document_choice
    """
    env = setup_choice_pending_referral(
        payer=dict(MERIDIAN_AUTH_REQUIRED),
        patient={
            "mrn": "MRN-5002", "full_name": "Ida Whitmore", "date_of_birth": "1944-12-01",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"daily_rate_cents": 30000},
    )

    attested = api.document_choice(
        env["referral"]["id"],
        document_choice_payload(env["offer"]["id"], choice_basis="PATIENT_PREFERENCE"),
        CASE_MANAGER,
    )
    validate_error(attested, ApiErrorId.ERR_AUTHORIZATION_REQUIRED, 422)

    unattested = api.document_choice(
        env["referral"]["id"],
        document_choice_payload(
            env["offer"]["id"], patient_choice_attested=False,
            choice_basis="PATIENT_PREFERENCE",
        ),
        CASE_MANAGER,
    )
    validate_error(unattested, ApiErrorId.ERR_CHOICE_NOT_ATTESTED, 422)
    assert read_referral(env["referral"]["id"])["status"] == "CHOICE_PENDING"


def test_a_denied_authorization_does_not_unlock_the_choice(api):
    """PRD §3.5: "Only after the attestation passes are the two coverage gates evaluated,
    and in this order: first, when the episode's payer requires authorization for the
    chosen level of care — `snf_auth_required` governing `SNF`, `IRF` and `LTACH`,
    `hh_auth_required` governing `HOME_HEALTH` — there must exist an authorization request
    on this episode for the chosen offer's provider whose `status` is `APPROVED` or
    `PARTIALLY_APPROVED` and whose `expires_at` is strictly later than the logical clock
    now, or the request is `ERR_AUTHORIZATION_REQUIRED` (HTTP 422)"
    PRD §3.6: "Denial is reachable from either `SUBMITTED` or `PENDED`, sets
    `approved_days` to 0, records the `denial_reason` and `decided_at`, and leaves
    `expires_at` null."

    Design: Difficulty/cross_entity_state_dependency/document_choice_blocked_until_authorization_is_live
    """
    env = setup_choice_pending_referral(
        payer=dict(MERIDIAN_AUTH_REQUIRED),
        patient={
            "mrn": "MRN-7101", "full_name": "Pia Grant", "date_of_birth": "1941-01-25",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"daily_rate_cents": 30000},
    )
    authorization = submit_authorization(
        env["episode"]["id"], env["provider_a"]["id"],
        level_of_care="SNF", requested_days=14, billed_daily_rate_cents=30000,
    )
    denied = validate_success(
        api.decide_authorization(
            authorization["id"],
            {"decision": "DENY", "denial_reason": "INCOMPLETE_CLINICALS"},
            make_payer_rep_headers(env["payer"]["id"]),
        )
    )
    assert denied["status"] == "DENIED"

    response = api.document_choice(
        env["referral"]["id"],
        document_choice_payload(env["offer"]["id"], choice_basis="PATIENT_PREFERENCE"),
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_REQUIRED, 422)
    assert read_referral(env["referral"]["id"])["status"] == "CHOICE_PENDING"
    assert read_offer(env["offer"]["id"])["status"] == "OFFERED"


def test_a_fresh_approval_unlocks_the_identical_choice_request(api):
    """PRD §3.6: "Approval is reachable from either `SUBMITTED` or `PENDED`; it sets
    `approved_days` equal to `requested_days`, sets `decided_at` to the logical clock
    instant, and sets `expires_at` to that instant plus the payer's `auth_expiry_days` in
    days."
    PRD §2.10: "`Episode.authorized_days_total` is the sum of `approved_days` across that
    episode's authorization requests in `APPROVED` or `PARTIALLY_APPROVED` status; an
    approval credits it and an expiry debits the same number of days back out."
    PRD §3.5: "second, that same authorization's `approved_days` must be at least the
    referral's `projected_stay_days`, or the request is `ERR_AUTHORIZATION_INSUFFICIENT`
    (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/document_choice_blocked_until_authorization_is_live
    """
    env = setup_choice_pending_referral(
        payer=dict(MERIDIAN_AUTH_REQUIRED),
        patient={
            "mrn": "MRN-7102", "full_name": "Pia Grant", "date_of_birth": "1941-01-25",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"daily_rate_cents": 30000},
    )
    first = submit_authorization(
        env["episode"]["id"], env["provider_a"]["id"],
        level_of_care="SNF", requested_days=14, billed_daily_rate_cents=30000,
    )
    validate_success(
        api.decide_authorization(
            first["id"], {"decision": "DENY", "denial_reason": "INCOMPLETE_CLINICALS"},
            make_payer_rep_headers(env["payer"]["id"]),
        )
    )
    blocked = api.document_choice(
        env["referral"]["id"],
        document_choice_payload(env["offer"]["id"], choice_basis="PATIENT_PREFERENCE"),
        CASE_MANAGER,
    )
    validate_error(blocked, ApiErrorId.ERR_AUTHORIZATION_REQUIRED, 422)

    second = submit_authorization(
        env["episode"]["id"], env["provider_a"]["id"],
        level_of_care="SNF", requested_days=14, billed_daily_rate_cents=30000,
    )
    approved = validate_success(
        api.decide_authorization(
            second["id"], {"decision": "APPROVE"},
            make_payer_rep_headers(env["payer"]["id"]),
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_days"] == 14

    placed = validate_success(
        api.document_choice(
            env["referral"]["id"],
            document_choice_payload(env["offer"]["id"], choice_basis="PATIENT_PREFERENCE"),
            CASE_MANAGER,
        )
    )
    assert placed["status"] == "PLACED"
    assert read_offer(env["offer"]["id"])["status"] == "ACCEPTED_BY_PATIENT"
    assert read_episode(env["episode"]["id"])["authorized_days_total"] == 14


def test_a_partial_approval_short_of_the_projected_stay_blocks_the_choice(api):
    """PRD §3.5: "second, that same authorization's `approved_days` must be at least the
    referral's `projected_stay_days`, or the request is `ERR_AUTHORIZATION_INSUFFICIENT`
    (HTTP 422)."
    PRD §3.6: "Partial approval is likewise reachable from either `SUBMITTED` or `PENDED`
    and requires the supplied `approved_days` to be at least 1 and strictly fewer than
    `requested_days`; it carries exactly the same ledger and barrier consequences as a full
    approval, using the smaller day count."
    PRD §3.6: "Step two reads the volume-discount tier from that **pre-discount** gross and
    from nothing else: a gross of fifteen thousand dollars or more sets
    `volume_discount_pct` to 0.05, otherwise a gross of five thousand dollars or more sets
    it to 0.03, otherwise it is 0.00."

    Design: Corner/errors/partial_authorization_below_projected_stay_returns_authorization_insufficient
    """
    env = setup_choice_pending_referral(
        payer=dict(MERIDIAN_AUTH_REQUIRED),
        patient={
            "mrn": "MRN-E102", "full_name": "Cai Abara", "date_of_birth": "1947-03-03",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        referral={"requested_level_of_care": "SNF", "projected_stay_days": 14,
                  "needed_by": "2026-08-20T00:00:00Z"},
        offer={"daily_rate_cents": 30000},
    )
    authorization = submit_authorization(
        env["episode"]["id"], env["provider_a"]["id"],
        level_of_care="SNF", requested_days=14, billed_daily_rate_cents=30000,
    )
    partial = validate_success(
        api.decide_authorization(
            authorization["id"], {"decision": "PARTIAL", "approved_days": 10},
            make_payer_rep_headers(env["payer"]["id"]),
        )
    )
    assert partial["status"] == "PARTIALLY_APPROVED"
    assert partial["approved_days"] == 10
    assert partial["gross_projection_cents"] == 375000, (
        "the billed 30000 marked up to 37500 over 10 approved days"
    )
    assert partial["volume_discount_pct"] == 0.00
    assert partial["authorized_amount_cents"] == 375000

    response = api.document_choice(
        env["referral"]["id"],
        document_choice_payload(env["offer"]["id"], choice_basis="ONLY_AVAILABLE"),
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_INSUFFICIENT, 422)
    assert response.json()["data"]["error_id"] != "ERR_AUTHORIZATION_REQUIRED"
    assert read_referral(env["referral"]["id"])["status"] == "CHOICE_PENDING"
    assert read_offer(env["offer"]["id"])["status"] == "OFFERED"


def test_three_machines_report_three_different_state_errors_after_a_placement(api):
    """PRD §3.5: "The referral must be in `CHOICE_PENDING`, or the request is
    `ERR_INVALID_REFERRAL_STATE`."
    PRD §3.4: "A liaison may withdraw its own outstanding offer, which moves it to
    `WITHDRAWN`, decrements that provider's `held_bed_units`, and makes the hold interval
    immediately reusable; withdrawing an offer that belongs to another provider is
    `ERR_NOT_OWNER`, and withdrawing one that is no longer `OFFERED` is
    `ERR_INVALID_OFFER_STATE`."
    PRD §3.6: "Deciding a request that is neither `SUBMITTED` nor `PENDED` is
    `ERR_INVALID_AUTHORIZATION_STATE`."

    Design: Corner/errors/wrong_state_actions_return_state_specific_errors
    """
    env = setup_choice_pending_referral(
        payer=dict(MERIDIAN_AUTH_REQUIRED),
        patient={
            "mrn": "MRN-E104", "full_name": "Eda Chukwu", "date_of_birth": "1945-05-05",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"daily_rate_cents": 30000},
    )
    payer_rep = make_payer_rep_headers(env["payer"]["id"])
    authorization = submit_authorization(
        env["episode"]["id"], env["provider_a"]["id"],
        level_of_care="SNF", requested_days=14, billed_daily_rate_cents=30000,
    )
    validate_success(api.decide_authorization(authorization["id"], {"decision": "APPROVE"}, payer_rep))
    validate_success(
        api.document_choice(
            env["referral"]["id"],
            document_choice_payload(env["offer"]["id"], choice_basis="CLINICAL_MATCH"),
            CASE_MANAGER,
        )
    )

    repeat_choice = api.document_choice(
        env["referral"]["id"],
        document_choice_payload(env["offer"]["id"], choice_basis="CLINICAL_MATCH"),
        CASE_MANAGER,
    )
    validate_error(repeat_choice, ApiErrorId.ERR_INVALID_REFERRAL_STATE, 409)

    withdraw = api.withdraw_offer(
        env["offer"]["id"], make_liaison_headers(env["provider_a"]["id"])
    )
    validate_error(withdraw, ApiErrorId.ERR_INVALID_OFFER_STATE, 409)

    redecide = api.decide_authorization(
        authorization["id"], {"decision": "DENY", "denial_reason": "OUT_OF_NETWORK"}, payer_rep
    )
    validate_error(redecide, ApiErrorId.ERR_INVALID_AUTHORIZATION_STATE, 409)

    assert read_referral(env["referral"]["id"])["status"] == "PLACED"
    assert read_offer(env["offer"]["id"])["status"] == "ACCEPTED_BY_PATIENT"
    final_auth = validate_success(api.get_authorization(authorization["id"], CASE_MANAGER))
    assert final_auth["status"] == "APPROVED"
    assert final_auth["approved_days"] == 14
    assert read_provider(env["provider_a"]["id"])["held_bed_units"] == 1


def test_the_choice_cascade_is_visible_in_its_own_response_and_immediate_reads(api):
    """PRD §3.5: "Every **other** offer of the same round still in `OFFERED` moves to
    `DECLINED_BY_PATIENT`; each decline decrements that provider's `held_bed_units` by one
    and releases its hold interval for reuse, and each declining provider's
    `acceptance_rate_pct` is recomputed even though neither its numerator nor its
    denominator moved."
    PRD §3.5: "The referral moves `CHOICE_PENDING → PLACED`, recording
    `chosen_bed_offer_id`, `choice_basis` and `patient_choice_attested`, and its `version`
    advances by one."
    PRD §3.5: "This value is advice only: it never constrains which offer a patient may
    choose."

    Design: Corner/consistency_model/choice_cascade_is_visible_in_the_same_response_and_immediate_reads
    """
    env = setup_choice_pending_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-H001", "full_name": "Ola Mbeki", "date_of_birth": "1941-10-10",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"daily_rate_cents": 30000},
    )
    offer_a = env["offer"]
    version = read_referral(env["referral"]["id"])["version"]
    offer_b = place_offer(
        env["referral"]["id"], env["provider_b"]["id"], version, daily_rate_cents=28000
    )
    before = validate_success(api.get_referral(env["referral"]["id"], CASE_MANAGER))
    assert before["recommended_bed_offer_id"] == offer_a["id"], (
        "Cedar outranks Birch at 48 points to 45"
    )

    body = validate_success(
        api.document_choice(
            env["referral"]["id"],
            document_choice_payload(offer_b["id"], choice_basis="FAMILY_PREFERENCE"),
            CASE_MANAGER,
        )
    )

    assert body["status"] == "PLACED", "the response body itself already shows the cascade"
    assert body["chosen_bed_offer_id"] == offer_b["id"]
    assert body["choice_basis"] == "FAMILY_PREFERENCE"

    assert read_offer(offer_a["id"])["status"] == "DECLINED_BY_PATIENT"
    assert read_offer(offer_b["id"])["status"] == "ACCEPTED_BY_PATIENT"

    declining = read_provider(env["provider_a"]["id"])
    assert declining["held_bed_units"] == 0
    assert declining["offers_accepted_count"] == 0
    assert declining["acceptance_rate_pct"] == 0.0

    chosen = read_provider(env["provider_b"]["id"])
    assert chosen["held_bed_units"] == 1
    assert chosen["offers_accepted_count"] == 1
    assert chosen["acceptance_rate_pct"] == 100.0
