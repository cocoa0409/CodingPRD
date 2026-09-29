"""The two version guards, and the promotion that lands inside the creating request."""

from test_helpers import (
    ERR_STALE_VERSION,
    allocatable_organ,
    assert_instant_equals,
    assert_two_decimal_value,
    candidate,
    create_hospital,
    create_referral,
    find_offer,
    list_offers,
    match_run_payload,
    open_screening,
    read_case,
    read_organ,
    read_run,
    read_screening,
    risk_assessment_payload,
    submit_assessment,
    validate_error,
    validate_success,
)

SCREENING_CLOCK = "2026-09-09T08:00:00Z"
SCREENING_TRIGGER = "2026-09-09T07:30:00Z"
ALLOCATION_CLOCK = "2026-09-09T09:00:00Z"


# ---------------------------------------------------------------------------
# Optimistic concurrency on the screening write
# ---------------------------------------------------------------------------
def test_stale_screening_version_blocks_a_resubmitted_risk_assessment(env):
    """Resubmission is legal, so only the replayed version can explain the refusal.

    PRD 2.7: "Resubmitting an assessment is perfectly valid — a coordinator
    reaches a better informant and supersedes the earlier scoring — so no state
    precondition forbids it; the only guard is that the assessment was composed
    against the screening the client actually read."
    PRD 2.7: "If `expected_screening_version` does not equal the screening's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412
    Precondition Failed)."
    PRD 2.4: "`version`, an integer that starts at 1 and increments by one on
    every mutation."
    PRD 3.2: "The seven scored factors and their weights are `IV_DRUG_USE_12MO`
    at 6.50"
    PRD 3.2: "leaves a screening that was already in `PENDING` in `PENDING`, and
    increments the screening's `version` by one."
    PRD 3.2: "Only the factors in the current request body count: the prior
    assessment on the screening is **fully replaced**, never merged."

    Design: Corner/cross_cutting_complexity_layers/stale_screening_version_blocks_a_resubmitted_risk_assessment
    """
    env.set_clock(SCREENING_CLOCK)
    hospital = create_hospital(
        env,
        name="Mercy General",
        hospital_code="MERCY",
        timely_referral_window_minutes=60,
    )
    referral = create_referral(
        env, hospital["id"], SCREENING_TRIGGER, patient_mrn="MRN-8101"
    )
    screening = open_screening(env, referral["id"])
    first_version = screening["version"]
    assert first_version == 1

    first = submit_assessment(
        env,
        screening["id"],
        first_version,
        risk_factors=["TATTOO_UNREGULATED_12MO"],
    )
    assert_two_decimal_value(first["risk_score"], 1.50)
    assert first["version"] == 2

    stale = env.api.submit_risk_assessment(
        screening["id"],
        risk_assessment_payload(first_version, ["IV_DRUG_USE_12MO"]),
        env.coordinator,
    )
    validate_error(stale, ERR_STALE_VERSION, 412)

    untouched = read_screening(env, screening["id"])
    assert_two_decimal_value(untouched["risk_score"], 1.50)
    assert untouched["version"] == 2
    assert untouched["status"] == "PENDING"

    retried = submit_assessment(
        env,
        screening["id"],
        untouched["version"],
        risk_factors=["IV_DRUG_USE_12MO"],
    )
    assert_two_decimal_value(retried["risk_score"], 6.50)
    assert retried["version"] == 3
    assert retried["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Optimistic concurrency on the match-run write
# ---------------------------------------------------------------------------
def test_stale_organ_version_blocks_a_superseding_match_run(env):
    """A supersede is legal from OFFERING, so the guard is the version alone.

    PRD 2.7: "Generating a later run legitimately supersedes the organ's earlier
    open run — the organ is re-listed after fresh donor data arrives — so again no
    state precondition blocks it; the guard is only that the requester's view of
    the organ is current."
    PRD 2.7: "If `expected_organ_version` does not equal the organ's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412
    Precondition Failed). Because a successful match-run generation itself
    increments the organ's `version` by one, a client that generates two runs back
    to back must re-read the organ in between."
    PRD 3.5: "assigns `run_number` as one more than the highest existing run
    number on that organ — so the first run on an organ is number 1"
    PRD 3.5: "If the organ already had a run in `OPEN`, that prior run moves `OPEN
    → SUPERSEDED` with `closed_reason` `SUPERSEDED_BY_NEW_RUN`, and its offers in
    `QUEUED` or `PENDING` move to `BYPASSED`"
    PRD 3.5: "The organ must be in `ALLOCATABLE` or `OFFERING`, otherwise
    `ERR_ORGAN_NOT_ALLOCATABLE`"
    PRD 3.5: "The organ moves `ALLOCATABLE → OFFERING` as soon as at least one
    offer is promoted"

    Design: Corner/cross_cutting_complexity_layers/stale_organ_version_blocks_a_superseding_match_run
    """
    bundle = allocatable_organ(env, "KIDNEY_RIGHT", ALLOCATION_CLOCK)
    organ_id = bundle.organ_id("KIDNEY_RIGHT")
    version_before_first_run = read_organ(env, organ_id)["version"]

    first_run = validate_success(
        env.api.create_match_run(
            organ_id,
            match_run_payload(
                version_before_first_run,
                [candidate(1, "CTR-A", "CAND-A", 240)],
                primary_offer_slots=1,
            ),
            env.alloc,
        ),
        201,
    )
    assert first_run["run_number"] == 1
    assert first_run["status"] == "OPEN"

    stale = env.api.create_match_run(
        organ_id,
        match_run_payload(
            version_before_first_run,
            [candidate(1, "CTR-B", "CAND-B", 240)],
            primary_offer_slots=1,
        ),
        env.alloc,
    )
    validate_error(stale, ERR_STALE_VERSION, 412)

    organ_now = read_organ(env, organ_id)
    assert organ_now["status"] == "OFFERING"
    assert organ_now["version"] > version_before_first_run
    assert read_run(env, first_run["id"])["status"] == "OPEN"

    second_run = validate_success(
        env.api.create_match_run(
            organ_id,
            match_run_payload(
                organ_now["version"],
                [candidate(1, "CTR-B", "CAND-B", 240)],
                primary_offer_slots=1,
            ),
            env.alloc,
        ),
        201,
    )
    assert second_run["run_number"] == 2
    assert second_run["status"] == "OPEN"

    superseded = read_run(env, first_run["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["closed_reason"] == "SUPERSEDED_BY_NEW_RUN"
    assert read_organ(env, organ_id)["status"] == "OFFERING"


# ---------------------------------------------------------------------------
# The promotion is inside the creating request, not after it
# ---------------------------------------------------------------------------
def test_match_run_creation_response_already_shows_the_promotion(env):
    """Three candidates, two default slots, and the 201 body already reports the fill.

    PRD 3.5: "an optional `primary_offer_slots` integer from 1 through 3 declaring
    how many offers may sit pending at once — primary plus backups — which defaults
    to 2"
    PRD 3.5: "Generation creates one offer per candidate in status `QUEUED`, sets
    the run's `candidate_count` to the number created, stamps `generated_at` from
    the logical clock"
    PRD 3.5: "Generation then immediately runs the promotion selector described in
    §3.6."
    PRD 3.5: "and the case's `allocation_status` advances from `NOT_STARTED` to
    `MATCH_RUN_OPEN` on the first run generated on any organ of the case and then
    onward to `OFFERS_IN_FLIGHT` once a pending offer exists"
    PRD 3.6: "Fourth, the fill: while the run's `pending_offer_count` is below its
    `primary_offer_slots` and the pool is non-empty, the ranked head is taken, its
    status set to `PENDING`, its `offered_at` stamped from the logical clock, its
    `expires_at` set to that instant plus its own `acceptance_clock_minutes`, the
    run's `pending_offer_count` incremented by one and its `slots_free`
    decremented by one."
    PRD 3.6: "Third, ranking: candidates are ordered by `sequence_position`
    ascending, with `created_at` ascending as a tie-break that is unreachable
    while positions are unique within a run; the resource `id` is never
    consulted."

    Design: Corner/consistency_model/match_run_creation_response_already_shows_the_promotion
    """
    bundle = allocatable_organ(env, "PANCREAS", ALLOCATION_CLOCK)
    organ_id = bundle.organ_id("PANCREAS")
    assert read_case(env, bundle.case_id)["allocation_status"] == "NOT_STARTED"

    run = validate_success(
        env.api.create_match_run(
            organ_id,
            match_run_payload(
                read_organ(env, organ_id)["version"],
                [
                    candidate(1, "CTR-A", "CAND-A", 90),
                    candidate(2, "CTR-B", "CAND-B", 90),
                    candidate(3, "CTR-C", "CAND-C", 90),
                ],
            ),
            env.alloc,
        ),
        201,
    )
    assert run["status"] == "OPEN"
    assert run["primary_offer_slots"] == 2
    assert run["candidate_count"] == 3
    assert run["pending_offer_count"] == 2
    assert run["slots_free"] == 0

    offers = list_offers(env, run["id"])
    assert [offer["sequence_position"] for offer in offers] == [1, 2, 3]
    assert find_offer(offers, 1)["status"] == "PENDING"
    assert find_offer(offers, 2)["status"] == "PENDING"
    assert find_offer(offers, 3)["status"] == "QUEUED"
    assert_instant_equals(find_offer(offers, 1)["offered_at"], ALLOCATION_CLOCK)
    assert_instant_equals(
        find_offer(offers, 1)["expires_at"], "2026-09-09T10:30:00Z"
    )
    assert_instant_equals(
        find_offer(offers, 2)["expires_at"], "2026-09-09T10:30:00Z"
    )

    assert read_case(env, bundle.case_id)["allocation_status"] == "OFFERS_IN_FLIGHT"
    assert read_organ(env, organ_id)["status"] == "OFFERING"
