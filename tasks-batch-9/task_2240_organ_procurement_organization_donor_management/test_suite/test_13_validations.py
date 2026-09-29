"""Each declared validation gate on its violation limb and on its satisfaction limb."""

from test_helpers import (
    AUTH_USER_2,
    AUTH_USER_3,
    ERR_ACCEPTANCE_CLOCK_ELAPSED,
    ERR_AUTHORIZATION_DOCUMENTATION_INCOMPLETE,
    ERR_AUTHORIZATION_NOT_CONTACTABLE,
    ERR_AUTHORIZATION_NOT_FINALIZABLE,
    ERR_AUTHORIZATION_NOT_OPENABLE,
    ERR_DISPOSITION_NOT_ALLOWED,
    ERR_EMPTY_MATCH_RUN,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_SEQUENCE,
    ERR_INVALID_TIME_WINDOW,
    ERR_MATCH_RUN_NOT_OPEN,
    ERR_NO_ACCEPTED_ORGANS,
    ERR_NOK_HIERARCHY_VIOLATION,
    ERR_OBSERVATION_IN_FUTURE,
    ERR_OFFER_NOT_PENDING,
    ERR_OFFER_RUN_MISMATCH,
    ERR_ORGAN_NOT_ALLOCATABLE,
    ERR_ORGAN_NOT_EVALUABLE,
    ERR_ORGAN_NOT_RECOVERED,
    ERR_REFERRAL_BEFORE_TRIGGER,
    ERR_SCREENING_NOT_CLEARED,
    ERR_TEAM_SPECIALTY_MISMATCH,
    ERR_VIABILITY_HOLD_ACTIVE,
    allocatable_organ,
    assert_append_only_identity,
    assert_slot_conservation,
    assert_team_ledger,
    assert_two_decimal_value,
    authorized_referral,
    candidate,
    candidate_sequence,
    cleared_referral,
    converted_case,
    create_asset,
    create_case,
    create_hospital,
    create_referral,
    create_team,
    death_referral_payload,
    disposition_payload,
    donor_case_payload,
    evaluate_organ,
    find_offer,
    finalize_authorization,
    get_success_data,
    list_authorizations,
    list_offers,
    make_authorization_specialist_headers,
    match_run_payload,
    nok_authorization_payload,
    nok_contact_payload,
    observation_payload,
    offer_response_payload,
    offering_organ,
    open_match_run,
    open_nok_authorization,
    open_registry_authorization,
    read_asset,
    read_authorization,
    read_case,
    read_hospital,
    read_organ,
    read_referral,
    read_run,
    read_team,
    record_disposition,
    record_nok_contact,
    recovery_operation_payload,
    registry_authorization_payload,
    respond_to_offer,
    restricted_case,
    rule_screening,
    screened_referral,
    transport_payload,
    upload_document,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Authorization openability, contactability and finalizability
# ---------------------------------------------------------------------------
def test_authorization_before_clearance_and_a_second_open_packet_are_rejected(env):
    """A packet needs a cleared referral, and a live packet blocks a second one.

    PRD 3.3: "An `AuthorizationSpecialist` opens the authorization packet on a
    referral in `SCREEN_CLEARED` for which no non-terminal authorization already
    exists — a packet in `DECLINED`, `UNABLE_TO_LOCATE` or `RESCINDED` is
    terminal and does not block a fresh attempt."
    PRD 3.3: "Any other referral status, or a live packet already present, yields
    `ERR_AUTHORIZATION_NOT_OPENABLE`."
    PRD 3.3: "The packet is created in `PENDING_REGISTRY` and immediately branches
    on the submitted `registry_hit` boolean"

    Design: Corner/validations/authorization_before_clearance_and_a_second_open_packet_are_rejected
    """
    bundle = screened_referral(env, "2026-09-05T08:00:00Z", 30, patient_mrn="MRN-5001")
    assert read_referral(env, bundle.referral_id)["status"] == "SCREENING"

    too_early = env.api.create_authorization(
        bundle.referral_id,
        registry_authorization_payload(registry_document_ref="REG-5001"),
        env.auth_one,
    )
    validate_error(too_early, ERR_AUTHORIZATION_NOT_OPENABLE)

    rule_screening(env, bundle.screening_id, "CLEARED")
    packet = open_registry_authorization(
        env, bundle.referral_id, registry_document_ref="REG-5001"
    )
    assert packet["status"] == "REGISTRY_CONFIRMED"
    assert read_referral(env, bundle.referral_id)["status"] == "AUTH_PENDING"

    second = env.api.create_authorization(
        bundle.referral_id,
        nok_authorization_payload(),
        env.auth_one,
    )
    validate_error(second, ERR_AUTHORIZATION_NOT_OPENABLE)

    assert [row["id"] for row in list_authorizations(env, bundle.referral_id)] == [
        packet["id"]
    ]


def test_next_of_kin_contact_on_a_registry_packet_is_rejected(env):
    """The hierarchy is walked only on the kin branch; the registry branch refuses it.

    PRD 3.3: "Contacts are accepted only while the packet is in `NOK_REQUIRED`,
    with one exception: an `OBJECTION` is also accepted while the packet is
    `AUTHORIZED`. Any other combination is rejected with
    `ERR_AUTHORIZATION_NOT_CONTACTABLE`."
    PRD 3.3: "The server derives the statutory `rank` from the relationship: a
    `SPOUSE` is rank 1, an `ADULT_CHILD` rank 2, a `PARENT` rank 3, a `SIBLING`
    rank 4, a `GRANDPARENT` rank 5 and a `LEGAL_GUARDIAN` rank 6, where 1 is the
    highest-priority class."
    PRD 2.4: "Three resources are append-only records rather than managed
    aggregates, and they carry **only** `id` and `created_at`"

    Design: Corner/validations/next_of_kin_contact_on_a_registry_packet_is_rejected
    """
    registry_bundle = cleared_referral(
        env, "2026-09-05T08:00:00Z", 30, patient_mrn="MRN-5101"
    )
    registry_packet = open_registry_authorization(
        env, registry_bundle.referral_id, registry_document_ref="REG-5101"
    )

    refused = env.api.create_nok_contact(
        registry_packet["id"],
        nok_contact_payload("SPOUSE", "CONSENT"),
        env.auth_one,
    )
    validate_error(refused, ERR_AUTHORIZATION_NOT_CONTACTABLE)
    assert read_authorization(env, registry_packet["id"])["status"] == (
        "REGISTRY_CONFIRMED"
    )

    kin_bundle = cleared_referral(
        env, "2026-09-05T08:00:00Z", 30, patient_mrn="MRN-5102"
    )
    kin_packet = open_nok_authorization(env, kin_bundle.referral_id)
    contact = validate_success(
        env.api.create_nok_contact(
            kin_packet["id"],
            nok_contact_payload("SPOUSE", "CONSENT"),
            env.auth_one,
        ),
        201,
    )
    assert contact["rank"] == 1
    assert_append_only_identity(contact)
    assert read_authorization(env, kin_packet["id"])["status"] == "NOK_CONSENTED"


def test_finalize_gates_reject_pre_consent_then_incomplete_documentation(env):
    """Finalizing from NOK_REQUIRED is refused; from NOK_CONSENTED it opens the cycle.

    PRD 3.3: "Finalizing is accepted from `REGISTRY_CONFIRMED`, `NOK_CONSENTED`
    or `DOCUMENT_DEFICIENT`, and from any other status yields
    `ERR_AUTHORIZATION_NOT_FINALIZABLE`."
    PRD 3.3: "Where `documentation_complete` is false and the packet sits in
    `NOK_CONSENTED`, finalization opens the deficiency cycle instead: the packet
    moves `NOK_CONSENTED → DOCUMENT_DEFICIENT` — the state change **is** recorded
    — and the caller nonetheless receives
    `ERR_AUTHORIZATION_DOCUMENTATION_INCOMPLETE`."
    PRD 3.3: "Where `documentation_complete` is true, the packet moves to
    `AUTHORIZED` and the acting specialist is recorded in
    `finalized_by_user_id`"

    Design: Corner/validations/finalize_gates_reject_pre_consent_then_incomplete_documentation
    """
    bundle = cleared_referral(env, "2026-09-05T08:00:00Z", 30, patient_mrn="MRN-5201")
    packet = open_nok_authorization(env, bundle.referral_id)
    assert packet["status"] == "NOK_REQUIRED"

    before_consent = env.api.finalize_authorization(
        packet["id"], make_authorization_specialist_headers(AUTH_USER_2)
    )
    validate_error(before_consent, ERR_AUTHORIZATION_NOT_FINALIZABLE)
    assert read_authorization(env, packet["id"])["status"] == "NOK_REQUIRED"

    record_nok_contact(env, packet["id"], "SPOUSE", "CONSENT")
    assert read_authorization(env, packet["id"])["status"] == "NOK_CONSENTED"

    incomplete = env.api.finalize_authorization(
        packet["id"], make_authorization_specialist_headers(AUTH_USER_2)
    )
    validate_error(incomplete, ERR_AUTHORIZATION_DOCUMENTATION_INCOMPLETE)
    assert read_authorization(env, packet["id"])["status"] == "DOCUMENT_DEFICIENT"

    upload_document(env, packet["id"], "SIGNED_CONSENT_FORM")
    complete = upload_document(
        env, packet["id"], "WITNESS_ATTESTATION", witness_name="R. Alvarez"
    )
    assert complete["documentation_complete"] is True
    assert complete["status"] == "NOK_CONSENTED"

    finalized = finalize_authorization(env, packet["id"], as_user=AUTH_USER_2)
    assert finalized["status"] == "AUTHORIZED"
    assert finalized["finalized_by_user_id"] == AUTH_USER_2


def test_consent_at_rank_two_before_exhausting_rank_one_is_rejected(env):
    """Rank two may speak only once rank one has been declined or unreachable.

    PRD 3.3: "A `CONSENT` or a `DECLINE` recorded at a given rank is admissible
    only when **every** rank numerically better than it — that is, every rank
    strictly lower in number — already has a contact on this packet whose
    response was `DECLINE` or `UNREACHABLE`."
    PRD 3.3: "a consent recorded at rank 2 while no rank-1 contact exists is
    rejected with `ERR_NOK_HIERARCHY_VIOLATION`"
    PRD 3.3: "The packet's `highest_rank_attempted` — the numerically lowest rank
    for which a contact row exists, updated as the smaller of its current value
    and the new contact's rank — is a reporting field only and never relaxes this
    admissibility check."
    PRD 3.3: "A `CONSENT` moves the packet `NOK_REQUIRED → NOK_CONSENTED`, sets
    `consenting_rank` to the consenting relative's rank, and records the acting
    specialist in `consent_recorded_by_user_id`."

    Design: Corner/validations/consent_at_rank_two_before_exhausting_rank_one_is_rejected
    """
    bundle = cleared_referral(env, "2026-09-05T08:00:00Z", 30, patient_mrn="MRN-5301")
    packet = open_nok_authorization(env, bundle.referral_id)

    out_of_order = env.api.create_nok_contact(
        packet["id"],
        nok_contact_payload("ADULT_CHILD", "CONSENT"),
        env.auth_one,
    )
    validate_error(out_of_order, ERR_NOK_HIERARCHY_VIOLATION)
    assert read_authorization(env, packet["id"])["status"] == "NOK_REQUIRED"

    spouse = record_nok_contact(env, packet["id"], "SPOUSE", "UNREACHABLE")
    assert spouse["rank"] == 1

    child = record_nok_contact(
        env, packet["id"], "ADULT_CHILD", "CONSENT", as_user=AUTH_USER_3
    )
    assert child["rank"] == 2

    consented = read_authorization(env, packet["id"])
    assert consented["status"] == "NOK_CONSENTED"
    assert consented["consenting_rank"] == 2
    assert consented["highest_rank_attempted"] == 1
    assert consented["consent_recorded_by_user_id"] == AUTH_USER_3


# ---------------------------------------------------------------------------
# Conversion gates
# ---------------------------------------------------------------------------
def test_second_donor_case_on_an_already_converted_referral_is_rejected(env):
    """The conversion gate re-reads the referral, so a fresh code cannot get past it.

    PRD 3.4: "The referral must be in `AUTH_PENDING` and its screening must be in
    `CLEARED`, otherwise `ERR_SCREENING_NOT_CLEARED`."
    PRD 3.4: "On success the referral advances `AUTH_PENDING → CONVERTED` and the
    hospital's `converted_donor_count` increases by one."
    PRD 2.10: "**Unique-key availability** — `ERR_DUPLICATE_KEY`, on `POST
    /opo/hospital-partners`, `POST /opo/recovery-teams`, `POST
    /opo/transport-assets`, `POST /opo/donor-cases` and `POST
    /opo/donor-cases/{id}/organs`."

    Design: Corner/validations/second_donor_case_on_an_already_converted_referral_is_rejected
    """
    bundle = authorized_referral(
        env, "2026-09-05T08:00:00Z", 30, patient_mrn="MRN-5501"
    )
    first = create_case(
        env, bundle.referral_id, bundle.authorization_id, donor_code="D-5501"
    )
    assert read_referral(env, bundle.referral_id)["status"] == "CONVERTED"
    assert read_hospital(env, bundle.hospital_id)["converted_donor_count"] == 1

    second = env.api.create_donor_case(
        donor_case_payload(
            bundle.referral_id, bundle.authorization_id, donor_code="D-5502"
        ),
        env.donor,
    )
    validate_error(second, ERR_SCREENING_NOT_CLEARED)

    rows, meta = validate_paginated(
        env.api.list_donor_cases(env.donor, {"referral_id": bundle.referral_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]


# ---------------------------------------------------------------------------
# Organ state gates
# ---------------------------------------------------------------------------
def test_organ_state_gates_reject_evaluation_match_run_and_transport(env):
    """Three organs in three states each draw their own status-specific refusal.

    PRD 3.5: "Evaluation is accepted only from status `PENDING_EVAL`, otherwise
    `ERR_ORGAN_NOT_EVALUABLE`."
    PRD 3.5: "The organ must be in `ALLOCATABLE` or `OFFERING`, otherwise
    `ERR_ORGAN_NOT_ALLOCATABLE`, and a thoracic organ on a restricted case is
    refused with `ERR_POSTURE_RESTRICTED`."
    PRD 3.7: "The organ must be in status `RECOVERED`, otherwise
    `ERR_ORGAN_NOT_RECOVERED`, which guarantees its `cross_clamp_at` is already
    set."
    PRD 3.7: "`active_leg_count` starts at zero and always reflects the number of
    organs assigned to that asset whose status is `RECOVERED`, that is, in
    transit."

    Design: Corner/validations/organ_state_gates_reject_evaluation_match_run_and_transport
    """
    clock = "2026-09-06T08:00:00Z"
    bundle = converted_case(
        env,
        clock,
        30,
        organ_types=["LIVER", "KIDNEY_RIGHT", "KIDNEY_LEFT"],
        patient_mrn="MRN-6001",
    )
    asset = create_asset(env, asset_code="VAN-1")

    bundle.organs["LIVER"] = evaluate_organ(
        env, bundle.organ_id("LIVER"), "ALLOCATABLE"
    )
    evaluate_organ(env, bundle.organ_id("KIDNEY_LEFT"), "ALLOCATABLE")
    bundle.run = open_match_run(
        env,
        bundle.organ_id("KIDNEY_LEFT"),
        candidate_sequence(1, 240),
        primary_offer_slots=1,
    )
    bundle.refresh_offers()
    respond_to_offer(env, bundle.run_id, bundle.offers[0]["id"], "ACCEPT")
    assert read_organ(env, bundle.organ_id("KIDNEY_LEFT"))["status"] == "ACCEPTED"

    not_evaluable = env.api.submit_organ_evaluation(
        bundle.organ_id("LIVER"), {"decision": "ALLOCATABLE"}, env.director
    )
    validate_error(not_evaluable, ERR_ORGAN_NOT_EVALUABLE)
    assert read_organ(env, bundle.organ_id("LIVER"))["status"] == "ALLOCATABLE"

    pending_kidney = read_organ(env, bundle.organ_id("KIDNEY_RIGHT"))
    assert pending_kidney["status"] == "PENDING_EVAL"
    not_allocatable = env.api.create_match_run(
        pending_kidney["id"],
        match_run_payload(pending_kidney["version"], candidate_sequence(1, 240)),
        env.alloc,
    )
    validate_error(not_allocatable, ERR_ORGAN_NOT_ALLOCATABLE)

    not_recovered = env.api.dispatch_transport(
        bundle.organ_id("KIDNEY_LEFT"),
        transport_payload(
            asset["id"], "2026-09-06T12:00:00Z", "2026-09-06T14:00:00Z"
        ),
        env.logistics,
    )
    validate_error(not_recovered, ERR_ORGAN_NOT_RECOVERED)

    settled = read_organ(env, bundle.organ_id("KIDNEY_LEFT"))
    assert settled["status"] == "ACCEPTED"
    assert settled["transport_asset_id"] is None
    assert read_asset(env, asset["id"])["active_leg_count"] == 0


# ---------------------------------------------------------------------------
# Candidate list well-formedness
# ---------------------------------------------------------------------------
def test_empty_and_non_contiguous_candidate_lists_are_rejected(env):
    """An empty list and a gap at position two are separate codes; the third call opens.

    PRD 3.5: "An empty `candidates` array is rejected with
    `ERR_EMPTY_MATCH_RUN`; positions that repeat or that are not contiguous
    starting at 1 are rejected with `ERR_INVALID_SEQUENCE`."
    PRD 3.5: "an optional `primary_offer_slots` integer from 1 through 3
    declaring how many offers may sit pending at once — primary plus backups —
    which defaults to 2"
    PRD 3.5: "assigns `run_number` as one more than the highest existing run
    number on that organ — so the first run on an organ is number 1"
    PRD 3.5: "Generation creates one offer per candidate in status `QUEUED`, sets
    the run's `candidate_count` to the number created, stamps `generated_at` from
    the logical clock"

    Design: Corner/validations/empty_and_non_contiguous_candidate_lists_are_rejected
    """
    bundle = allocatable_organ(env, "HEART", "2026-09-06T08:00:00Z")
    organ = read_organ(env, bundle.only_organ_id)

    empty = env.api.create_match_run(
        organ["id"], match_run_payload(organ["version"], []), env.alloc
    )
    validate_error(empty, ERR_EMPTY_MATCH_RUN)

    gapped = env.api.create_match_run(
        organ["id"],
        match_run_payload(
            organ["version"],
            [
                candidate(1, "CTR-A", "CAND-A", 240),
                candidate(3, "CTR-C", "CAND-C", 240),
            ],
        ),
        env.alloc,
    )
    validate_error(gapped, ERR_INVALID_SEQUENCE)

    run = validate_success(
        env.api.create_match_run(
            organ["id"],
            match_run_payload(
                organ["version"],
                [
                    candidate(1, "CTR-A", "CAND-A", 240),
                    candidate(2, "CTR-B", "CAND-B", 240),
                ],
            ),
            env.alloc,
        ),
        201,
    )
    assert run["run_number"] == 1
    assert run["candidate_count"] == 2
    assert run["primary_offer_slots"] == 2
    assert run["pending_offer_count"] == 2
    assert run["slots_free"] == 0
    assert_slot_conservation(run)


# ---------------------------------------------------------------------------
# Offer status, run status and the acceptance clock
# ---------------------------------------------------------------------------
def test_queued_decline_and_closed_run_advance_are_rejected(env):
    """A queued offer cannot be declined and a closed run cannot be advanced.

    PRD 3.6: "An `ACCEPT` or a `DECLINE` requires the offer to be in `PENDING`,
    and a `WITHDRAW_ACCEPTANCE` requires it to be in `ACCEPTED`; any other
    combination yields `ERR_OFFER_NOT_PENDING`."
    PRD 3.6: "Advancing a run requires it to be in `OPEN`, otherwise
    `ERR_MATCH_RUN_NOT_OPEN`."
    PRD 3.6: "the run moves `OPEN → CLOSED` with `closed_reason` `ACCEPTED`, and
    every other offer on the run whose status is `QUEUED` or `PENDING` moves to
    `BYPASSED` with `bypass_reason` `PEER_ACCEPTED`"

    Design: Corner/validations/queued_decline_and_closed_run_advance_are_rejected
    """
    bundle = offering_organ(
        env,
        "KIDNEY_LEFT",
        "2026-09-06T08:00:00Z",
        candidate_count=2,
        primary_offer_slots=1,
        acceptance_clock_minutes=240,
    )
    queued = find_offer(bundle.offers, 2)
    assert queued["status"] == "QUEUED"

    refused = env.api.respond_to_offer(
        bundle.run_id, queued["id"], offer_response_payload("DECLINE"), env.alloc
    )
    validate_error(refused, ERR_OFFER_NOT_PENDING)

    respond_to_offer(env, bundle.run_id, find_offer(bundle.offers, 1)["id"], "ACCEPT")
    closed = read_run(env, bundle.run_id)
    assert closed["status"] == "CLOSED"
    assert closed["closed_reason"] == "ACCEPTED"

    stale_advance = env.api.advance_match_run(bundle.run_id, env.alloc)
    validate_error(stale_advance, ERR_MATCH_RUN_NOT_OPEN)

    after = find_offer(list_offers(env, bundle.run_id), 2)
    assert after["status"] == "BYPASSED"
    assert after["bypass_reason"] == "PEER_ACCEPTED"


def test_responding_with_an_offer_from_another_run_is_rejected(env):
    """An offer answered through a sibling run's path leaves the offer untouched.

    PRD 3.6: "The offer addressed must have a `match_run_id` equal to the run
    named in the path, otherwise `ERR_OFFER_RUN_MISMATCH`."
    PRD 3.6: "Whatever the decision, `responded_at` is stamped from the logical
    clock and the acting specialist is recorded in `responded_by_user_id`."
    PRD 2.10: "**Offer belongs to the path's run** — `ERR_OFFER_RUN_MISMATCH`, on
    `POST /opo/match-runs/{id}/offers/{offerId}/respond`."

    Design: Corner/validations/responding_with_an_offer_from_another_run_is_rejected
    """
    bundle = allocatable_organ(
        env,
        "KIDNEY_LEFT",
        "2026-09-06T08:00:00Z",
        extra_organ_types=["KIDNEY_RIGHT"],
    )
    evaluate_organ(env, bundle.organ_id("KIDNEY_RIGHT"), "ALLOCATABLE")

    left_run = open_match_run(
        env,
        bundle.organ_id("KIDNEY_LEFT"),
        candidate_sequence(1, 240),
        primary_offer_slots=1,
    )
    right_run = open_match_run(
        env,
        bundle.organ_id("KIDNEY_RIGHT"),
        candidate_sequence(1, 240),
        primary_offer_slots=1,
    )
    right_offer = list_offers(env, right_run["id"])[0]
    assert right_offer["status"] == "PENDING"

    mismatched = env.api.respond_to_offer(
        left_run["id"], right_offer["id"], offer_response_payload("ACCEPT"), env.alloc
    )
    validate_error(mismatched, ERR_OFFER_RUN_MISMATCH)

    untouched = list_offers(env, right_run["id"])[0]
    assert untouched["status"] == "PENDING"
    assert untouched["responded_at"] is None
    assert untouched["responded_by_user_id"] is None
    assert read_organ(env, bundle.organ_id("KIDNEY_RIGHT"))["status"] == "OFFERING"


def test_accepting_after_the_acceptance_clock_elapsed_is_rejected(env):
    """One minute past the default sixty-minute clock the acceptance is refused.

    PRD 3.6: "An `ACCEPT` requires that the acceptance clock has not run out —
    the logical clock must be strictly before the offer's `expires_at`, and
    reaching or passing it yields `ERR_ACCEPTANCE_CLOCK_ELAPSED`."
    PRD 3.5: "an optional `acceptance_clock_minutes` from 5 through 240 stating
    how long that centre gets to answer once its offer is promoted, defaulting to
    60"
    PRD 3.6: "its `offered_at` stamped from the logical clock, its `expires_at`
    set to that instant plus its own `acceptance_clock_minutes`"
    PRD 3.6: "First, on an advance, the expiry sweep: every offer of this run
    whose status is `PENDING` and whose `expires_at` has been reached by the
    logical clock becomes `EXPIRED`."

    Design: Corner/validations/accepting_after_the_acceptance_clock_elapsed_is_rejected
    """
    bundle = offering_organ(
        env,
        "LIVER",
        "2026-09-06T09:00:00Z",
        candidate_count=1,
        primary_offer_slots=1,
        acceptance_clock_minutes=None,
    )
    offer = bundle.offers[0]
    assert offer["acceptance_clock_minutes"] == 60
    assert offer["status"] == "PENDING"

    env.set_clock("2026-09-06T10:01:00Z")
    elapsed = env.api.respond_to_offer(
        bundle.run_id, offer["id"], offer_response_payload("ACCEPT"), env.alloc
    )
    validate_error(elapsed, ERR_ACCEPTANCE_CLOCK_ELAPSED)

    still_pending = list_offers(env, bundle.run_id)[0]
    assert still_pending["status"] == "PENDING"

    run = read_run(env, bundle.run_id)
    assert run["status"] == "OPEN"
    assert run["pending_offer_count"] == 1
    assert read_organ(env, bundle.only_organ_id)["accepted_offer_id"] is None


# ---------------------------------------------------------------------------
# Recovery-operation gates
# ---------------------------------------------------------------------------
def test_recovery_booking_without_an_accepted_organ_is_rejected(env):
    """An allocatable organ is not an accepted one, so the theatre stays unbooked.

    PRD 3.7: "The case must have at least one organ in status `ACCEPTED`,
    otherwise `ERR_NO_ACCEPTED_ORGANS`."
    PRD 3.7: "A new team starts with `booked_or_minutes` and
    `scheduled_operation_count` at zero."
    PRD 2.11: "for each recovery team, `booked_or_minutes` is always exactly the
    sum of `or_minutes` over that team's operations whose status is `SCHEDULED`
    or `COMPLETED`"

    Design: Corner/validations/recovery_booking_without_an_accepted_organ_is_rejected
    """
    bundle = allocatable_organ(env, "LIVER", "2026-09-06T08:00:00Z")
    team = create_team(env, team_code="ABD-1", specialty="ABDOMINAL")
    assert_team_ledger(team, 0, 0)

    refused = env.api.create_recovery_operation(
        bundle.case_id,
        recovery_operation_payload(
            team["id"], "2026-09-06T12:00:00Z", "2026-09-06T15:00:00Z"
        ),
        env.logistics,
    )
    validate_error(refused, ERR_NO_ACCEPTED_ORGANS)

    assert_team_ledger(read_team(env, team["id"]), 0, 0)
    rows, meta = validate_paginated(
        env.api.list_recovery_operations(
            env.logistics, {"donor_case_id": bundle.case_id}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_team_specialty_then_or_window_gates_reject_the_booking(env):
    """A thoracic team cannot take a liver and a zero-length window is not a window.

    PRD 3.7: "The team's specialty must cover **every** organ type in that
    accepted set: a `THORACIC` team covers `HEART`, `LUNG_LEFT` and
    `LUNG_RIGHT`; an `ABDOMINAL` team covers the remaining types; a `MULTIORGAN`
    team covers all of them. A gap in coverage yields
    `ERR_TEAM_SPECIALTY_MISMATCH`."
    PRD 3.7: "The end must fall strictly after the start, otherwise
    `ERR_INVALID_TIME_WINDOW`."
    PRD 3.7: "On success the operation is created in status `SCHEDULED` with
    `cross_clamp_at` and `cancelled_reason` null, its `or_minutes` computed as
    the whole minutes from `or_start_at` to `or_end_at`, and its
    `organ_types_covered` pinned to the `organ_type` values of the case's
    accepted organs as they stand at scheduling time."
    PRD 3.7: "The team's `booked_or_minutes` increases by that `or_minutes` and
    its `scheduled_operation_count` by one."

    Design: Corner/validations/team_specialty_then_or_window_gates_reject_the_booking
    """
    clock = "2026-09-07T08:00:00Z"
    bundle = allocatable_organ(env, "LIVER", clock)
    bundle.run = open_match_run(
        env, bundle.only_organ_id, candidate_sequence(1, 240), primary_offer_slots=1
    )
    bundle.refresh_offers()
    respond_to_offer(env, bundle.run_id, bundle.offers[0]["id"], "ACCEPT")
    assert read_organ(env, bundle.only_organ_id)["status"] == "ACCEPTED"

    thoracic = create_team(env, team_code="THX-1", specialty="THORACIC")
    abdominal = create_team(env, team_code="ABD-1", specialty="ABDOMINAL")

    mismatch = env.api.create_recovery_operation(
        bundle.case_id,
        recovery_operation_payload(
            thoracic["id"], "2026-09-07T12:00:00Z", "2026-09-07T15:00:00Z"
        ),
        env.logistics,
    )
    validate_error(mismatch, ERR_TEAM_SPECIALTY_MISMATCH)

    zero_length = env.api.create_recovery_operation(
        bundle.case_id,
        recovery_operation_payload(
            abdominal["id"], "2026-09-07T12:00:00Z", "2026-09-07T12:00:00Z"
        ),
        env.logistics,
    )
    validate_error(zero_length, ERR_INVALID_TIME_WINDOW)

    operation = validate_success(
        env.api.create_recovery_operation(
            bundle.case_id,
            recovery_operation_payload(
                abdominal["id"], "2026-09-07T12:00:00Z", "2026-09-07T15:00:00Z"
            ),
            env.logistics,
        ),
        201,
    )
    assert operation["status"] == "SCHEDULED"
    assert operation["or_minutes"] == 180
    assert operation["organ_types_covered"] == ["LIVER"]
    assert operation["cross_clamp_at"] is None
    assert operation["cancelled_reason"] is None

    assert_team_ledger(read_team(env, abdominal["id"]), 180, 1)
    assert_team_ledger(read_team(env, thoracic["id"]), 0, 0)


# ---------------------------------------------------------------------------
# Disposition companion codes
# ---------------------------------------------------------------------------
def test_research_and_tissue_dispositions_require_their_own_code(env):
    """Each referral disposition demands its own code; the other one will not do.

    PRD 3.8: "An organ in `NON_TRANSPLANTABLE` may be referred onward:
    `RESEARCH_REFERRED` requires a non-null `research_protocol_code`, which is
    stored on the organ, and `TISSUE_REFERRED` requires a non-null
    `tissue_processor_code`, likewise stored."
    PRD 3.8: "A disposition that does not match the organ's status, that omits
    its required code, or that runs into the rescission bar is rejected with
    `ERR_DISPOSITION_NOT_ALLOWED`."
    PRD 3.8: "the latter counting organs in `NON_TRANSPLANTABLE`,
    `RESEARCH_REFERRED` or `TISSUE_REFERRED`"

    Design: Corner/validations/research_and_tissue_dispositions_require_their_own_code
    """
    clock = "2026-09-07T08:00:00Z"
    bundle = converted_case(
        env, clock, 30, organ_types=["LIVER", "KIDNEY_LEFT"], patient_mrn="MRN-6701"
    )
    liver = evaluate_organ(
        env,
        bundle.organ_id("LIVER"),
        "NON_TRANSPLANTABLE",
        nontransplantable_reason="ANATOMIC_ANOMALY",
    )
    kidney = evaluate_organ(
        env,
        bundle.organ_id("KIDNEY_LEFT"),
        "NON_TRANSPLANTABLE",
        nontransplantable_reason="VIABILITY_FAILURE",
    )
    assert liver["status"] == "NON_TRANSPLANTABLE"
    assert kidney["status"] == "NON_TRANSPLANTABLE"

    missing_code = env.api.record_disposition(
        liver["id"], disposition_payload("RESEARCH_REFERRED"), env.director
    )
    validate_error(missing_code, ERR_DISPOSITION_NOT_ALLOWED)

    wrong_code = env.api.record_disposition(
        kidney["id"],
        disposition_payload("TISSUE_REFERRED", research_protocol_code="PROTO-9"),
        env.director,
    )
    validate_error(wrong_code, ERR_DISPOSITION_NOT_ALLOWED)

    referred = record_disposition(
        env, liver["id"], "RESEARCH_REFERRED", research_protocol_code="PROTO-9"
    )
    assert referred["status"] == "RESEARCH_REFERRED"
    assert referred["research_protocol_code"] == "PROTO-9"

    processed = record_disposition(
        env, kidney["id"], "TISSUE_REFERRED", tissue_processor_code="TP-4"
    )
    assert processed["status"] == "TISSUE_REFERRED"
    assert processed["tissue_processor_code"] == "TP-4"

    assert read_case(env, bundle.case_id)["organs_nontransplantable_count"] == 2


# ---------------------------------------------------------------------------
# The two safety gates in their inverted order
# ---------------------------------------------------------------------------
def test_viability_hold_outranks_restricted_posture_on_evaluation(env):
    """Both gates are violated at once and the more specific hold error wins.

    PRD 2.10: "**Active viability hold** — `ERR_VIABILITY_HOLD_ACTIVE`, on `POST
    /opo/organs/{id}/evaluation`. This check is deliberately ordered **before**
    the posture gate that follows it, because the hold is the more specific fact:
    a held organ always sits on a restricted case, so the coarser posture error
    would otherwise mask it."
    PRD 3.5: "Declaring an organ `ALLOCATABLE` additionally requires
    `viability_hold` to be false — a still-held organ yields
    `ERR_VIABILITY_HOLD_ACTIVE` — and requires the case's posture to be `OPEN`."
    PRD 3.4: "sets its `viability_hold` to true and returns its status to
    `PENDING_EVAL`; abdominal organs are untouched"

    Design: Corner/validations/viability_hold_outranks_restricted_posture_on_evaluation
    """
    bundle = restricted_case(env, "HEART", "KIDNEY_RIGHT", "2026-09-07T09:00:00Z")

    case = read_case(env, bundle.case_id)
    assert case["physiologic_status"] == "DECOMPENSATING"
    assert case["case_posture"] == "RESTRICTED"

    heart = read_organ(env, bundle.organ_id("HEART"))
    assert heart["status"] == "PENDING_EVAL"
    assert heart["viability_hold"] is True

    held = env.api.submit_organ_evaluation(
        heart["id"], {"decision": "ALLOCATABLE"}, env.director
    )
    validate_error(held, ERR_VIABILITY_HOLD_ACTIVE)

    unchanged = read_organ(env, heart["id"])
    assert unchanged["status"] == "PENDING_EVAL"
    assert unchanged["viability_hold"] is True


# ---------------------------------------------------------------------------
# Temporal orderings against the logical clock
# ---------------------------------------------------------------------------
def test_referral_timestamps_before_the_clinical_trigger_are_rejected(env):
    """A future trigger and a death pronounced before it both fail; the ordered one lands.

    PRD 3.1: "The stamped `referred_at` must not precede `trigger_event_at`, and
    `death_pronounced_at`, when supplied, must not precede `trigger_event_at`
    either. A violation of either ordering is rejected with
    `ERR_REFERRAL_BEFORE_TRIGGER`."
    PRD 3.1: "The server stamps `referred_at` from the logical clock and the new
    referral enters status `RECEIVED`."
    PRD 2.4: "All domain time is read from a **logical clock**, never from
    wall-clock time."

    Design: Corner/validations/referral_timestamps_before_the_clinical_trigger_are_rejected
    """
    env.set_clock("2026-09-07T08:00:00Z")
    hospital = create_hospital(
        env, hospital_code="MERCY", timely_referral_window_minutes=60
    )

    future_trigger = env.api.create_death_referral(
        death_referral_payload(
            hospital["id"], "2026-09-07T09:00:00Z", patient_mrn="MRN-6901"
        ),
        env.coordinator,
    )
    validate_error(future_trigger, ERR_REFERRAL_BEFORE_TRIGGER)

    death_before_trigger = env.api.create_death_referral(
        death_referral_payload(
            hospital["id"],
            "2026-09-07T07:30:00Z",
            patient_mrn="MRN-6902",
            death_pronounced_at="2026-09-07T07:00:00Z",
        ),
        env.coordinator,
    )
    validate_error(death_before_trigger, ERR_REFERRAL_BEFORE_TRIGGER)

    accepted = validate_success(
        env.api.create_death_referral(
            death_referral_payload(
                hospital["id"],
                "2026-09-07T07:30:00Z",
                patient_mrn="MRN-6903",
                death_pronounced_at="2026-09-07T07:45:00Z",
            ),
            env.coordinator,
        ),
        201,
    )
    assert accepted["status"] == "RECEIVED"
    assert accepted["referred_at"].startswith("2026-09-07T08:00:00")

    rows, meta = validate_paginated(
        env.api.list_death_referrals(
            env.coordinator, {"hospital_partner_id": hospital["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["patient_mrn"] for row in rows] == ["MRN-6903"]


def test_observation_recorded_after_the_clock_is_rejected(env):
    """One minute ahead of the clock is refused; the same payload lands once it moves.

    PRD 3.4: "The `recorded_at` instant must not be after the logical clock,
    otherwise `ERR_OBSERVATION_IN_FUTURE`."
    PRD 3.4: "its `viability_index`, `dmg_bundle_met_count`, `observation_count`,
    `organ_count`, `organs_accepted_count`, `organs_recovered_count` and
    `organs_nontransplantable_count` all start at zero"
    PRD 3.4: "otherwise an index of at least 70 gives `OPTIMIZED`, an index of at
    least 40 gives `STABILIZING`, and anything lower gives `DECOMPENSATING`."

    Design: Corner/validations/observation_recorded_after_the_clock_is_rejected
    """
    bundle = converted_case(env, "2026-09-07T09:00:00Z", 30, patient_mrn="MRN-7001")
    env.set_clock("2026-09-07T10:00:00Z")

    payload = observation_payload(
        "2026-09-07T10:01:00Z",
        map_mmhg=65,
        pao2_fio2_ratio=300,
        sodium=130,
        urine_output_ml_per_kg_hr=0.4,
        pressor_count=0,
    )
    in_future = env.api.create_observation(bundle.case_id, payload, env.donor)
    validate_error(in_future, ERR_OBSERVATION_IN_FUTURE)

    untouched = read_case(env, bundle.case_id)
    assert untouched["observation_count"] == 0
    assert untouched["viability_index"] == 0

    env.set_clock("2026-09-07T10:01:00Z")
    charted = validate_success(
        env.api.create_observation(bundle.case_id, payload, env.donor), 201
    )
    assert charted["viability_index_snapshot"] == 70

    settled = read_case(env, bundle.case_id)
    assert settled["observation_count"] == 1
    assert settled["physiologic_status"] == "OPTIMIZED"


# ---------------------------------------------------------------------------
# Pagination bounds
# ---------------------------------------------------------------------------
def test_pagination_bounds_are_enforced_before_any_row_is_read(env):
    """Zero, one hundred and one, and minus one all fail; the closed interval passes.

    PRD 2.3: "`limit` caps the number of items returned; it defaults to 10, its
    minimum accepted value is 1, and its maximum accepted value is 100."
    PRD 2.3: "A `limit` that is not an integer or falls outside 1 through 100
    inclusive, or an `offset` that is not an integer or is negative, is rejected
    with `ERR_INVALID_PAGINATION` (400 Bad Request)."
    PRD 2.3: "where `total_count` is the number of matching rows before the limit
    and offset are applied and `has_more` indicates whether further rows remain
    beyond the current page"
    PRD 2.3: "Unless a specific endpoint states otherwise, list results are
    sorted by `created_at` in ascending order."

    Design: Corner/validations/pagination_bounds_are_enforced_before_any_row_is_read
    """
    env.set_clock("2026-09-07T08:00:00Z")
    hospital = create_hospital(
        env, hospital_code="MERCY", timely_referral_window_minutes=60
    )
    create_referral(
        env, hospital["id"], "2026-09-07T07:30:00Z", patient_mrn="MRN-7101"
    )
    create_referral(
        env,
        hospital["id"],
        "2026-09-07T07:40:00Z",
        patient_mrn="MRN-7102",
        age_years=41,
        gcs_score=4,
        cause_of_death_category="HEAD_TRAUMA",
    )

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            env.api.list_death_referrals(env.coordinator, params),
            ERR_INVALID_PAGINATION,
        )

    rows, meta = validate_paginated(
        env.api.list_death_referrals(env.coordinator, {"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert rows[0]["patient_mrn"] == "MRN-7101"

    page_two, page_two_meta = validate_paginated(
        env.api.list_death_referrals(env.coordinator, {"limit": 1, "offset": 1})
    )
    assert page_two_meta["total_count"] == 2
    assert page_two_meta["has_more"] is False
    assert [row["patient_mrn"] for row in page_two] == ["MRN-7102"]


# ---------------------------------------------------------------------------
# The satisfaction limb of the increased-risk protocol
# ---------------------------------------------------------------------------
def test_standard_risk_acceptance_needs_no_increased_risk_acknowledgement(env):
    """A 6.50 score pins the donor STANDARD, so the bare ACCEPT succeeds in full.

    PRD 3.6: "It also enforces the increased-risk protocol: when the donor case's
    `risk_tier_snapshot` is `INCREASED_RISK`, the accepting centre must have set
    `increased_risk_ack` to true, and omitting it yields
    `ERR_INCREASED_RISK_ACK_REQUIRED`; a `STANDARD` donor needs no
    acknowledgement."
    PRD 3.2: "Finally `risk_tier` becomes `INCREASED_RISK` when `risk_score` is
    at least 12.00 and `STANDARD` otherwise."
    PRD 3.4: "`risk_tier_snapshot` is pinned from the screening's `risk_tier` at
    this moment, taking the value `STANDARD` or `INCREASED_RISK`, and never
    changes thereafter"
    PRD 3.6: "the organ moves `OFFERING → ACCEPTED` with its `accepted_offer_id`
    set to the accepting offer"
    PRD 3.6: "The case's `allocation_status` advances `OFFERS_IN_FLIGHT →
    ALLOCATED` and its `organs_accepted_count` increases by one."

    Design: Corner/validations/standard_risk_acceptance_needs_no_increased_risk_acknowledgement
    """
    bundle = offering_organ(
        env,
        "KIDNEY_LEFT",
        "2026-09-07T09:00:00Z",
        candidate_count=1,
        primary_offer_slots=1,
        acceptance_clock_minutes=240,
        risk_factors=["IV_DRUG_USE_12MO"],
    )
    assert_two_decimal_value(bundle.screening["risk_score"], 6.50)
    assert bundle.screening["risk_tier"] == "STANDARD"
    assert read_case(env, bundle.case_id)["risk_tier_snapshot"] == "STANDARD"

    offer = bundle.offers[0]
    accepted = get_success_data(
        env.api.respond_to_offer(
            bundle.run_id, offer["id"], {"decision": "ACCEPT"}, env.alloc
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["increased_risk_ack"] is False

    organ = read_organ(env, bundle.only_organ_id)
    assert organ["status"] == "ACCEPTED"
    assert organ["accepted_offer_id"] == offer["id"]

    case = read_case(env, bundle.case_id)
    assert case["allocation_status"] == "ALLOCATED"
    assert case["organs_accepted_count"] == 1
