"""The catalogue's clinical-safety, topology, scheduling, clock and money codes."""
from test_helpers import (
    accept_offer,
    add_operating_room,
    add_segment,
    add_surgeon,
    adjudicate_claim,
    advance_clock,
    book_theatre,
    clear_both_domains,
    create_active_recipient,
    create_approved_donor,
    create_chain,
    create_donor,
    create_donor_cost_claim_payload,
    create_offer_payload,
    create_improvement_plan_payload,
    create_outcome_review,
    create_program,
    create_recipient,
    file_claim,
    finalize_review,
    follow_up_by_interval,
    follow_up_fields,
    get_chain,
    get_donor,
    get_recipient,
    get_segment,
    record_disclosure,
    refresh_program,
    send_offer,
    setup_committed_paired_loop,
    setup_donated_donor,
    setup_offered_segment,
    setup_paired_loop_participants,
    setup_program_with_staff,
    submit_medical_evaluation,
    update_recipient_status,
    validate_chain,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId


def _three_pair_participants():
    """Three ACTIVE recipients and three APPROVED directed donors, ready to loop."""
    env = setup_program_with_staff()
    env["recipient_one"] = create_active_recipient(
        env, mrn="R-001", abo_blood_type="A", age_years=44, cpra=0.85
    )
    env["recipient_two"] = create_active_recipient(
        env, mrn="R-002", abo_blood_type="B", age_years=51, cpra=0.1
    )
    env["recipient_three"] = create_active_recipient(
        env, mrn="R-003", abo_blood_type="AB", age_years=39, cpra=0.4
    )
    env["donor_one"] = create_approved_donor(
        env, intended_recipient_id=env["recipient_one"]["id"], mrn="D-001", age_years=41
    )
    env["donor_two"] = create_approved_donor(
        env, intended_recipient_id=env["recipient_two"]["id"], mrn="D-002", age_years=38
    )
    env["donor_three"] = create_approved_donor(
        env, intended_recipient_id=env["recipient_three"]["id"], mrn="D-003", age_years=45
    )
    return env


def _three_segment_loop(env):
    """D-001 gives to R-002, D-002 to R-003, D-003 back to R-001 — a closed loop."""
    chain = create_chain(env, "PAIRED_LOOP")
    first = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    second = add_segment(
        env,
        chain["id"],
        2,
        env["donor_two"]["id"],
        env["recipient_three"]["id"],
        predecessor_segment_id=first["id"],
    )
    third = add_segment(
        env,
        chain["id"],
        3,
        env["donor_three"]["id"],
        env["recipient_one"]["id"],
        predecessor_segment_id=second["id"],
    )
    env.update(
        {
            "chain": chain,
            "segment_one": first,
            "segment_two": second,
            "segment_three": third,
        }
    )
    return env


def test_err_cooling_off_not_elapsed_returns_422():
    """PRD §3.3: "Attesting requires that the current logical clock has reached
    `cooling_off_ends_at` — the boundary is inclusive, so exactly at that instant the
    attestation succeeds and one second earlier is refused with
    `ERR_COOLING_OFF_NOT_ELAPSED` — and that both `medical_status` and
    `psychosocial_status` are `CLEARED`, failing which the attestation is refused with
    `ERR_CLEARANCE_INCOMPLETE`."
    PRD §2.10: "Informed-consent safety — `ERR_COOLING_OFF_NOT_ELAPSED`,
    `ERR_CLEARANCE_INCOMPLETE` or `ERR_HARD_EXCLUSION_PRESENT`, 422."
    PRD §3.3: "It sets `attestation_at` to the current logical clock, computes
    `final_risk_index`, and derives the donor's `overall_status` into either `APPROVED` or
    `CONDITIONAL_APPROVED`."
    PRD §3.3: "It advances `disclosure_sequence` by 1, sets `disclosure_at` to the current
    logical clock, and re-derives `cooling_off_ends_at`."

    Design: Corner/errors/err_cooling_off_not_elapsed_returns_422
    """
    env = setup_program_with_staff()
    assert env["program"]["cooling_off_days"] == 7
    recipient = create_recipient(env, mrn="R-001")
    donor = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-001", age_years=41
    )
    clear_both_domains(env, donor["id"])
    disclosed = record_disclosure(env, donor["id"])
    assert disclosed["cooling_off_ends_at"].startswith("2026-08-08T00:00:00")
    advance_clock(env, "2026-08-07T23:59:59Z")

    response = api_client.record_advocacy_determination(
        donor["id"], {"outcome": "ATTESTED"}, env["advocate_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_COOLING_OFF_NOT_ELAPSED.value, expected_status=422
    )

    after = get_donor(env, donor["id"])
    assert after["cooling_off_ends_at"].startswith("2026-08-08T00:00:00")
    assert after["advocacy_status"] == "DISCLOSED"
    assert after["attestation_at"] is None
    assert after["overall_status"] == "EVAL_IN_PROGRESS"
    assert after["final_risk_index"] is None


def test_err_hard_exclusion_present_returns_422():
    """PRD §3.4: "A `CLEARED` outcome is refused with `ERR_HARD_EXCLUSION_PRESENT` while
    the evaluation's `hard_exclusion_count` is greater than 0 — a hard finding must be
    resolved by resubmission, not overridden."
    PRD §3.4: "`EX_BMI_TOO_HIGH` fires when `bmi` is strictly greater than 35.0."
    PRD §2.10: "Informed-consent safety — `ERR_COOLING_OFF_NOT_ELAPSED`,
    `ERR_CLEARANCE_INCOMPLETE` or `ERR_HARD_EXCLUSION_PRESENT`, 422."
    PRD §3.4: "Evaluations are listed with optional `donor_candidate_id`,
    `reviewer_staff_id`, `domain` and `status` filters plus `limit` and `offset`, and read
    individually to expose `exclusion_codes`, `hard_exclusion_count`, `risk_points` and
    `submission_count`."

    Design: Corner/errors/err_hard_exclusion_present_returns_422
    """
    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)
    evaluation = submit_medical_evaluation(env, donor["id"], bmi=36.0)
    assert evaluation["exclusion_codes"] == ["EX_BMI_TOO_HIGH"]
    assert evaluation["hard_exclusion_count"] == 1

    response = api_client.record_evaluation_determination(
        evaluation["id"], {"outcome": "CLEARED"}, env["reviewer_med_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_HARD_EXCLUSION_PRESENT.value, expected_status=422
    )

    reread = validate_success(
        api_client.get_donor_evaluation(evaluation["id"], env["reviewer_med_headers"])
    )
    assert reread["hard_exclusion_count"] == 1
    assert reread["exclusion_codes"] == ["EX_BMI_TOO_HIGH"]
    assert reread["risk_points"] == 0, "a hard finding contributes no soft points"
    assert reread["status"] == "SUBMITTED"
    assert get_donor(env, donor["id"])["medical_status"] == "PENDING"


def test_err_donor_not_approved_returns_422():
    """PRD §3.5: "Every segment's donor must have `overall_status` exactly `APPROVED` —
    `CONDITIONAL_APPROVED` is explicitly not enough, and the rejection is
    `ERR_DONOR_NOT_APPROVED`."
    PRD §2.10: "Participant eligibility — `ERR_DONOR_NOT_APPROVED`,
    `ERR_RECIPIENT_NOT_ACTIVE`, `ERR_DONOR_NOT_COMMITTED` or `ERR_DONOR_NOT_DONATED`,
    422."
    PRD §3.5: "**Validation.** Validating a chain takes no input fields and moves it from
    `DRAFT` to `VALIDATED`, recording `validated_at` at the current logical clock,
    recomputing `segment_count` and `is_closed_loop`, and incrementing the chain's
    `version`."
    PRD §3.4: "A new evaluation row starts at `SUBMITTED` with `submission_count` 1 and
    `determined_at` null, and the first evaluation row ever created for a donor moves that
    donor's `overall_status` from `REFERRED` to `EVAL_IN_PROGRESS`."

    Design: Corner/errors/err_donor_not_approved_returns_422
    """
    env = setup_program_with_staff()
    recipient_one = create_active_recipient(env, mrn="R-001", abo_blood_type="A")
    recipient_two = create_active_recipient(env, mrn="R-002", abo_blood_type="B")
    donor_one = create_approved_donor(
        env, intended_recipient_id=recipient_one["id"], mrn="D-001", age_years=41
    )
    donor_two = create_donor(
        env, intended_recipient_id=recipient_two["id"], mrn="D-002", age_years=38
    )
    submit_medical_evaluation(env, donor_two["id"])
    assert get_donor(env, donor_two["id"])["overall_status"] == "EVAL_IN_PROGRESS"
    chain = create_chain(env, "PAIRED_LOOP")
    first = add_segment(env, chain["id"], 1, donor_one["id"], recipient_two["id"])
    add_segment(
        env,
        chain["id"],
        2,
        donor_two["id"],
        recipient_one["id"],
        predecessor_segment_id=first["id"],
    )

    response = api_client.validate_chain(chain["id"], env["coordinator_headers"])

    validate_error(
        response, ApiErrorId.ERR_DONOR_NOT_APPROVED.value, expected_status=422
    )

    assert get_donor(env, donor_two["id"])["overall_status"] == "EVAL_IN_PROGRESS"
    after = get_chain(env, chain["id"])
    assert after["status"] == "DRAFT"
    assert after["validated_at"] is None


def test_err_donor_not_committed_returns_422():
    """PRD §3.6: "The segment's recipient must be `ACTIVE`, failing which the rejection is
    `ERR_RECIPIENT_NOT_ACTIVE`; the segment's donor must be `CHAIN_COMMITTED`, failing which
    the rejection is `ERR_DONOR_NOT_COMMITTED`."
    PRD §3.5: "On success the chain moves to `COMMITTED`, `committed_at` is set to the
    current logical clock, `committed_donor_count` becomes the number of distinct donors on
    non-withdrawn segments, every one of those donors moves from `APPROVED` to
    `CHAIN_COMMITTED`, and the chain's `version` increments."
    PRD §3.5: "Insertion deliberately does **not** check the chain's shape."
    PRD §3.5: "The new segment starts in `PLANNED` with every offer and planning field
    null."

    Design: Corner/errors/err_donor_not_committed_returns_422
    """
    env = setup_committed_paired_loop()
    assert env["chain"]["committed_donor_count"] == 2
    recipient_three = create_active_recipient(env, mrn="R-003", abo_blood_type="AB")
    donor_three = create_approved_donor(
        env, intended_recipient_id=recipient_three["id"], mrn="D-003", age_years=45
    )
    third = add_segment(
        env,
        env["chain"]["id"],
        3,
        donor_three["id"],
        recipient_three["id"],
        predecessor_segment_id=env["segment_two"]["id"],
    )

    response = api_client.send_segment_offer(
        third["id"],
        create_offer_payload("2026-08-16T07:00:00Z", "2026-08-16T13:00:00Z"),
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_DONOR_NOT_COMMITTED.value, expected_status=422
    )

    assert get_donor(env, donor_three["id"])["overall_status"] == "APPROVED", (
        "a post-commitment insertion does not retroactively commit a donor"
    )
    assert get_chain(env, env["chain"]["id"])["committed_donor_count"] == 2
    after = get_segment(env, third["id"])
    assert after["status"] == "PLANNED"
    assert after["planned_cit_minutes"] is None


def test_err_donor_not_donated_returns_422():
    """PRD §3.9: "The donor's `overall_status` must already be `DONATED`; filing for a donor
    who has not donated is refused with `ERR_DONOR_NOT_DONATED`."
    PRD §2.10: "Participant eligibility — `ERR_DONOR_NOT_APPROVED`,
    `ERR_RECIPIENT_NOT_ACTIVE`, `ERR_DONOR_NOT_COMMITTED` or `ERR_DONOR_NOT_DONATED`,
    422."
    PRD §3.3: "A new donor starts with `overall_status` `REFERRED`, `advocacy_status`
    `UNASSIGNED`, both `medical_status` and `psychosocial_status` at `PENDING`,
    `disclosure_sequence` 0, `deferral_count` 0, `medical_risk_points` and
    `psychosocial_risk_points` 0, and `screening_risk_index` 0; `advocate_staff_id`,
    `disclosure_at`, `cooling_off_ends_at`, `attestation_at`, `objection_reason_code`,
    `final_risk_index` and `donated_at` are all null."
    PRD §2.9: "A program's `donor_fund_committed_cents` is the sum of `fund_part_cents`
    over every donor cost claim whose donor belongs to that program and whose `status` is
    `ADJUDICATED`."

    Design: Corner/errors/err_donor_not_donated_returns_422
    """
    env = setup_program_with_staff()
    donor = create_donor(env, assign_advocate=False, mrn="D-001", age_years=41)
    assert donor["overall_status"] == "REFERRED"

    response = api_client.create_donor_cost_claim(
        create_donor_cost_claim_payload(
            donor["id"],
            claim_type="MEDICAL",
            coverage_source="RECIPIENT_INSURANCE",
            submitted_amount_cents=450000,
            service_from_on="2026-08-01",
            service_to_on="2026-08-02",
        ),
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_DONOR_NOT_DONATED.value, expected_status=422
    )

    after = get_donor(env, donor["id"])
    assert after["overall_status"] == "REFERRED"
    assert after["donated_at"] is None
    rows, meta = validate_paginated(
        api_client.list_donor_cost_claims(donor["id"], env["coordinator_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert refresh_program(env)["donor_fund_committed_cents"] == 0


def test_err_cross_program_reference_returns_422():
    """PRD §2.5: "Once every reference resolves, they must all belong to the same program."
    PRD §2.5: "A single request may not mix a staff member, recipient, donor, chain,
    segment, room, review or claim drawn from two different transplant programs; such a
    request is rejected with `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 422)."
    PRD §2.10: "Priority 14 guards five: chain validation, chain commitment, segment
    offer, cost-claim creation and cost-claim adjudication."
    PRD §2.5: "This is checked on every write endpoint that accepts more than one foreign
    key."

    Design: Corner/errors/err_cross_program_reference_returns_422
    """
    env = setup_program_with_staff(
        name="Northlake Transplant Center", center_code="NLT-01"
    )
    recipient = create_active_recipient(env, mrn="R-001", abo_blood_type="A")
    other_program = create_program(
        name="Southline Transplant Center", center_code="STL-02"
    )

    response = api_client.create_donor_candidate(
        {
            "program_id": other_program["id"],
            "intended_recipient_id": recipient["id"],
            "mrn": "D-001",
            "abo_blood_type": "O",
            "age_years": 41,
        },
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE.value, expected_status=422
    )

    for program_id in (other_program["id"], env["program_id"]):
        rows, meta = validate_paginated(
            api_client.list_donor_candidates(
                env["coordinator_headers"], params={"program_id": program_id}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0


def test_err_chain_too_short_returns_422():
    """PRD §3.5: "The chain must hold at least two such segments; a shorter chain fails
    `ERR_CHAIN_TOO_SHORT`, and this holds regardless of `chain_type`, so a single-segment
    chain can never validate."
    PRD §2.10: "Chain topology — `ERR_CHAIN_TOO_SHORT`,
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`, `ERR_CHAIN_LINKAGE_BROKEN`,
    `ERR_DUPLICATE_PARTICIPANT`, `ERR_ABO_INCOMPATIBLE`, `ERR_LOOP_NOT_CLOSED` or
    `ERR_NDD_START_INVALID`, 422."
    PRD §3.5: "**Validation.** Validating a chain takes no input fields and moves it from
    `DRAFT` to `VALIDATED`, recording `validated_at` at the current logical clock,
    recomputing `segment_count` and `is_closed_loop`, and incrementing the chain's
    `version`."

    Design: Corner/errors/err_chain_too_short_returns_422
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    add_segment(env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"])

    response = api_client.validate_chain(chain["id"], env["coordinator_headers"])

    validate_error(response, ApiErrorId.ERR_CHAIN_TOO_SHORT.value, expected_status=422)

    after = get_chain(env, chain["id"])
    assert after["segment_count"] == 1
    assert after["status"] == "DRAFT"
    assert after["validated_at"] is None


def test_err_chain_positions_not_contiguous_returns_422():
    """PRD §3.5: "The positions must be exactly the consecutive whole numbers from 1 up to
    `segment_count`, with no gap and no duplicate; positions of 1 and 3 fail
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`."
    PRD §2.10: "Chain topology — `ERR_CHAIN_TOO_SHORT`,
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`, `ERR_CHAIN_LINKAGE_BROKEN`,
    `ERR_DUPLICATE_PARTICIPANT`, `ERR_ABO_INCOMPATIBLE`, `ERR_LOOP_NOT_CLOSED` or
    `ERR_NDD_START_INVALID`, 422."
    PRD §3.5: "It considers only segments whose status is not `WITHDRAWN`, ordered by
    `position` ascending, and it enforces seven topology conditions plus two participant
    conditions."

    Design: Corner/errors/err_chain_positions_not_contiguous_returns_422
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    first = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    add_segment(
        env,
        chain["id"],
        3,
        env["donor_two"]["id"],
        env["recipient_one"]["id"],
        predecessor_segment_id=first["id"],
    )

    response = api_client.validate_chain(chain["id"], env["coordinator_headers"])

    validate_error(
        response,
        ApiErrorId.ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS.value,
        expected_status=422,
    )

    after = get_chain(env, chain["id"])
    assert after["segment_count"] == 2
    assert after["status"] == "DRAFT"
    rows, _meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"], params={"exchange_chain_id": chain["id"]}
        )
    )
    assert sorted(row["position"] for row in rows) == [1, 3]


def test_err_chain_linkage_broken_returns_422():
    """PRD §3.5: "The linkage must be exact: the first segment in the ordering must declare
    no `predecessor_segment_id`, and every subsequent segment's `predecessor_segment_id` must
    be the `id` of the segment immediately before it; a null predecessor on a second segment,
    or a predecessor pointing anywhere other than the previous position, fails
    `ERR_CHAIN_LINKAGE_BROKEN`."
    PRD §2.10: "Chain topology — `ERR_CHAIN_TOO_SHORT`,
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`, `ERR_CHAIN_LINKAGE_BROKEN`,
    `ERR_DUPLICATE_PARTICIPANT`, `ERR_ABO_INCOMPATIBLE`, `ERR_LOOP_NOT_CLOSED` or
    `ERR_NDD_START_INVALID`, 422."
    PRD §3.5: "**Validation.** Validating a chain takes no input fields and moves it from
    `DRAFT` to `VALIDATED`, recording `validated_at` at the current logical clock,
    recomputing `segment_count` and `is_closed_loop`, and incrementing the chain's
    `version`."

    Design: Corner/errors/err_chain_linkage_broken_returns_422
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    add_segment(env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"])
    second = add_segment(
        env, chain["id"], 2, env["donor_two"]["id"], env["recipient_one"]["id"]
    )
    assert second["predecessor_segment_id"] is None

    response = api_client.validate_chain(chain["id"], env["coordinator_headers"])

    validate_error(
        response, ApiErrorId.ERR_CHAIN_LINKAGE_BROKEN.value, expected_status=422
    )

    reread = get_segment(env, second["id"])
    assert reread["position"] == 2
    assert reread["predecessor_segment_id"] is None
    after = get_chain(env, chain["id"])
    assert after["status"] == "DRAFT"
    assert after["validated_at"] is None


def test_err_duplicate_participant_returns_422():
    """PRD §3.5: "No `donor_candidate_id` and no `recipient_candidate_id` may appear on more
    than one of those segments; a repeat is `ERR_DUPLICATE_PARTICIPANT`."
    PRD §2.10: "Chain topology — `ERR_CHAIN_TOO_SHORT`,
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`, `ERR_CHAIN_LINKAGE_BROKEN`,
    `ERR_DUPLICATE_PARTICIPANT`, `ERR_ABO_INCOMPATIBLE`, `ERR_LOOP_NOT_CLOSED` or
    `ERR_NDD_START_INVALID`, 422."
    PRD §3.5: "A donor of type `O` may give to a recipient of type `O`, `A`, `B` or `AB`."

    Design: Corner/errors/err_duplicate_participant_returns_422
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    first = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    add_segment(
        env,
        chain["id"],
        2,
        env["donor_two"]["id"],
        env["recipient_two"]["id"],
        predecessor_segment_id=first["id"],
    )

    response = api_client.validate_chain(chain["id"], env["coordinator_headers"])

    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_PARTICIPANT.value, expected_status=422
    )

    rows, _meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"], params={"exchange_chain_id": chain["id"]}
        )
    )
    assert [row["recipient_candidate_id"] for row in rows] == [
        env["recipient_two"]["id"],
        env["recipient_two"]["id"],
    ]
    assert get_chain(env, chain["id"])["status"] == "DRAFT"


def test_err_loop_not_closed_returns_422():
    """PRD §3.5: "A `PAIRED_LOOP` requires `is_closed_loop` to be true and fails
    `ERR_LOOP_NOT_CLOSED` otherwise; a two-segment closed loop is the minimum valid loop."
    PRD §3.5: "`is_closed_loop` is true exactly when the `recipient_candidate_id` of the
    last segment in the ordering equals the `intended_recipient_id` of the first segment's
    donor — the chain has given back to the person the first donor came in for."
    PRD §2.10: "Chain topology — `ERR_CHAIN_TOO_SHORT`,
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`, `ERR_CHAIN_LINKAGE_BROKEN`,
    `ERR_DUPLICATE_PARTICIPANT`, `ERR_ABO_INCOMPATIBLE`, `ERR_LOOP_NOT_CLOSED` or
    `ERR_NDD_START_INVALID`, 422."
    PRD §3.5: "A new chain starts in `DRAFT` with `segment_count` 0, `is_closed_loop`
    false, `total_planned_cit_minutes` 0 and `committed_donor_count` 0, and with
    `validated_at`, `committed_at` and `break_reason_code` all null."

    Design: Corner/errors/err_loop_not_closed_returns_422
    """
    env = setup_paired_loop_participants()
    recipient_three = create_active_recipient(env, mrn="R-003", abo_blood_type="AB")
    chain = create_chain(env, "PAIRED_LOOP")
    first = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    add_segment(
        env,
        chain["id"],
        2,
        env["donor_two"]["id"],
        recipient_three["id"],
        predecessor_segment_id=first["id"],
    )

    response = api_client.validate_chain(chain["id"], env["coordinator_headers"])

    validate_error(response, ApiErrorId.ERR_LOOP_NOT_CLOSED.value, expected_status=422)

    after = get_chain(env, chain["id"])
    assert after["chain_type"] == "PAIRED_LOOP"
    assert after["status"] == "DRAFT"
    assert after["validated_at"] is None
    assert after["total_planned_cit_minutes"] == 0


def test_err_ndd_start_invalid_returns_422():
    """PRD §3.5: "An `NDD_CHAIN` requires `is_closed_loop` to be false *and* requires the
    donor of the position-1 segment to have a null `intended_recipient_id`; either failure is
    `ERR_NDD_START_INVALID`."
    PRD §2.10: "Chain topology — `ERR_CHAIN_TOO_SHORT`,
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`, `ERR_CHAIN_LINKAGE_BROKEN`,
    `ERR_DUPLICATE_PARTICIPANT`, `ERR_ABO_INCOMPATIBLE`, `ERR_LOOP_NOT_CLOSED` or
    `ERR_NDD_START_INVALID`, 422."
    PRD §3.5: "Opening one requires only the owning `program_id` and a `chain_type` of
    either `PAIRED_LOOP` or `NDD_CHAIN`."

    Design: Corner/errors/err_ndd_start_invalid_returns_422
    """
    env = setup_paired_loop_participants()
    recipient_three = create_active_recipient(env, mrn="R-003", abo_blood_type="AB")
    chain = create_chain(env, "NDD_CHAIN")
    first = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    add_segment(
        env,
        chain["id"],
        2,
        env["donor_two"]["id"],
        recipient_three["id"],
        predecessor_segment_id=first["id"],
    )

    response = api_client.validate_chain(chain["id"], env["coordinator_headers"])

    validate_error(
        response, ApiErrorId.ERR_NDD_START_INVALID.value, expected_status=422
    )

    assert (
        get_donor(env, env["donor_one"]["id"])["intended_recipient_id"]
        == env["recipient_one"]["id"]
    ), "the position-1 donor is directed"
    after = get_chain(env, chain["id"])
    assert after["chain_type"] == "NDD_CHAIN"
    assert after["status"] == "DRAFT"
    assert after["validated_at"] is None


def test_err_donor_booking_missing_returns_422():
    """PRD §3.6: "And there must already exist an `ACTIVE` procedure booking for this
    segment whose `booking_role` is `DONOR_RECOVERY` and whose half-open window from
    `start_at` inclusive to `end_at` exclusive contains `planned_cross_clamp_at`; without one
    the offer is refused with `ERR_DONOR_BOOKING_MISSING`."
    PRD §2.10: "Cold-ischemia planning prerequisites — `ERR_DONOR_BOOKING_MISSING`,
    `ERR_IMPLANT_BOOKING_MISSING` or `ERR_PREDECESSOR_TIMING_INVALID`, 422."
    PRD §3.6: "A successful offer sets the segment to `OFFER_SENT`, stamps `offer_sent_at`
    with the current logical clock, sets `offer_response_deadline_at` to six hours after
    `offer_sent_at`, stores the three planned fields, writes `planned_cit_minutes`,
    recomputes the chain's `total_planned_cit_minutes`, and increments the segment's
    `version`."

    Design: Corner/errors/err_donor_booking_missing_returns_422
    """
    env = setup_committed_paired_loop()
    advance_clock(env, "2026-08-09T05:00:00Z")

    response = api_client.send_segment_offer(
        env["segment_one"]["id"],
        create_offer_payload("2026-08-09T07:00:00Z", "2026-08-09T13:00:00Z"),
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_DONOR_BOOKING_MISSING.value, expected_status=422
    )

    after = get_segment(env, env["segment_one"]["id"])
    assert after["status"] == "PLANNED"
    assert after["offer_sent_at"] is None
    assert after["planned_cit_minutes"] is None
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 0


def test_err_implant_booking_missing_returns_422():
    """PRD §3.7: "And an `ACTIVE` procedure booking with `booking_role` `RECIPIENT_IMPLANT`
    must exist for this segment, failing which the request is refused with
    `ERR_IMPLANT_BOOKING_MISSING`."
    PRD §2.10: "Cold-ischemia planning prerequisites — `ERR_DONOR_BOOKING_MISSING`,
    `ERR_IMPLANT_BOOKING_MISSING` or `ERR_PREDECESSOR_TIMING_INVALID`, 422."
    PRD §3.6: "`planned_cit_minutes` is computed when the offer is sent: it is the whole
    minutes between `planned_cross_clamp_at` and `planned_reperfusion_at`, truncated toward
    zero, plus a fixed forty-five-minute allowance for the final cross-match hold."
    PRD §3.6: "Accepting moves the segment to `ACCEPTED`, stamps `offer_responded_at` with
    the current logical clock, and increments the segment's `version` — nothing else
    changes."

    Design: Corner/errors/err_implant_booking_missing_returns_422
    """
    env = setup_committed_paired_loop()
    room = add_operating_room(env, "OR-1")
    booking = book_theatre(
        env,
        room["id"],
        env["segment_one"]["id"],
        "DONOR_RECOVERY",
        "2026-08-09T06:00:00Z",
        "2026-08-09T10:00:00Z",
    )
    advance_clock(env, "2026-08-09T06:00:00Z")
    offered = send_offer(
        env, env["segment_one"]["id"], "2026-08-09T07:00:00Z", "2026-08-09T13:00:00Z"
    )
    assert offered["planned_cit_minutes"] == 405
    accepted = accept_offer(env, env["segment_one"]["id"])
    assert accepted["status"] == "ACCEPTED"

    response = api_client.record_transplant_completion(
        env["segment_one"]["id"],
        {
            "actual_cross_clamp_at": "2026-08-09T07:05:00Z",
            "actual_reperfusion_at": "2026-08-09T13:00:00Z",
        },
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_IMPLANT_BOOKING_MISSING.value, expected_status=422
    )

    after = get_segment(env, env["segment_one"]["id"])
    assert after["status"] == "ACCEPTED"
    assert after["actual_cit_minutes"] is None
    assert after["planned_cit_minutes"] == 405
    donor = get_donor(env, env["donor_one"]["id"])
    assert donor["overall_status"] == "CHAIN_COMMITTED"
    assert donor["donated_at"] is None
    assert validate_success(
        api_client.get_procedure_booking(booking["id"], env["coordinator_headers"])
    )["status"] == "ACTIVE"


def test_err_predecessor_timing_invalid_returns_422():
    """PRD §3.6: "When the segment declares a `predecessor_segment_id`, its
    `planned_cross_clamp_at` must be at or after that predecessor's `planned_reperfusion_at`
    — one operation cannot start recovering an organ before the previous recipient in the
    chain has been reperfused — and a violation is `ERR_PREDECESSOR_TIMING_INVALID`."
    PRD §2.10: "Cold-ischemia planning prerequisites — `ERR_DONOR_BOOKING_MISSING`,
    `ERR_IMPLANT_BOOKING_MISSING` or `ERR_PREDECESSOR_TIMING_INVALID`, 422."
    PRD §3.6: "`total_planned_cit_minutes` on a chain is the sum of `planned_cit_minutes`
    over that chain's segments whose status is `OFFER_SENT`, `ACCEPTED` or `TRANSPLANTED`,
    accumulated in `position` ascending and, for ties, `created_at` ascending order."
    PRD §3.6: "`planned_cit_minutes` is computed when the offer is sent: it is the whole
    minutes between `planned_cross_clamp_at` and `planned_reperfusion_at`, truncated toward
    zero, plus a fixed forty-five-minute allowance for the final cross-match hold."

    Design: Corner/errors/err_predecessor_timing_invalid_returns_422
    """
    env = setup_committed_paired_loop()
    room_one = add_operating_room(env, "OR-1")
    room_three = add_operating_room(env, "OR-3")
    second_surgeon = add_surgeon(env)
    book_theatre(
        env,
        room_one["id"],
        env["segment_one"]["id"],
        "DONOR_RECOVERY",
        "2026-08-09T06:00:00Z",
        "2026-08-09T10:00:00Z",
    )
    book_theatre(
        env,
        room_three["id"],
        env["segment_two"]["id"],
        "DONOR_RECOVERY",
        "2026-08-09T09:00:00Z",
        "2026-08-09T11:00:00Z",
        surgeon_id=second_surgeon["id"],
    )
    advance_clock(env, "2026-08-09T05:00:00Z")
    first_offer = send_offer(
        env, env["segment_one"]["id"], "2026-08-09T07:00:00Z", "2026-08-09T13:00:00Z"
    )
    assert first_offer["planned_cit_minutes"] == 405

    response = api_client.send_segment_offer(
        env["segment_two"]["id"],
        create_offer_payload(
            "2026-08-09T09:30:00Z", "2026-08-09T11:00:00Z", planned_transport_minutes=60
        ),
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_PREDECESSOR_TIMING_INVALID.value, expected_status=422
    )

    after = get_segment(env, env["segment_two"]["id"])
    assert after["status"] == "PLANNED"
    assert after["offer_sent_at"] is None
    assert after["planned_cit_minutes"] is None
    assert get_segment(env, env["segment_one"]["id"])["planned_cit_minutes"] == 405
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 405


def test_err_offer_window_expired_returns_422():
    """PRD §3.6: "Either way the current logical clock must be at or before
    `offer_response_deadline_at`, and a late answer is refused with
    `ERR_OFFER_WINDOW_EXPIRED`."
    PRD §3.6: "A successful offer sets the segment to `OFFER_SENT`, stamps `offer_sent_at`
    with the current logical clock, sets `offer_response_deadline_at` to six hours after
    `offer_sent_at`, stores the three planned fields, writes `planned_cit_minutes`,
    recomputes the chain's `total_planned_cit_minutes`, and increments the segment's
    `version`."
    PRD §2.10: "Clock-relative windows — `ERR_OFFER_WINDOW_EXPIRED`,
    `ERR_FOLLOW_UP_NOT_DUE`, `ERR_EFFECTIVE_AT_OUT_OF_ORDER` or `ERR_CLOCK_NOT_MONOTONIC`,
    422."
    PRD §3.2: "`offer_decline_count` on a candidate is the number of that candidate's chain
    segments currently sitting at `DECLINED`."

    Design: Corner/errors/err_offer_window_expired_returns_422
    """
    env = setup_offered_segment()
    assert env["segment_one"]["status"] == "OFFER_SENT"
    assert env["segment_one"]["offer_response_deadline_at"].startswith(
        "2026-08-09T12:00:00"
    )
    advance_clock(env, "2026-08-09T12:01:00Z")

    response = api_client.record_offer_response(
        env["segment_one"]["id"], {"response": "ACCEPT"}, env["coordinator_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_OFFER_WINDOW_EXPIRED.value, expected_status=422
    )

    after = get_segment(env, env["segment_one"]["id"])
    assert after["offer_response_deadline_at"].startswith("2026-08-09T12:00:00")
    assert after["status"] == "OFFER_SENT"
    assert after["offer_responded_at"] is None
    assert after["decline_reason_code"] is None
    assert get_recipient(env, env["recipient_two"]["id"])["offer_decline_count"] == 0, (
        "an expired window is not a decline"
    )


def test_err_follow_up_not_due_returns_422():
    """PRD §3.7: "Submission is refused before the interval's `due_on` with
    `ERR_FOLLOW_UP_NOT_DUE`, and is refused entirely against a row whose status is already
    `WAIVED` or `SUBMITTED_COMPLETE` with `ERR_FOLLOW_UP_TERMINAL`; submission is accepted
    while the row is `DUE`, `INCOMPLETE` or `DELINQUENT`."
    PRD §3.7: "Each interval has a fixed required field count: a `SIX_MONTH` interval
    requires 12 fields, a `ONE_YEAR` interval requires 14, and a `TWO_YEAR` interval requires
    10, and that number is stored as `required_fields_count`."
    PRD §2.10: "Clock-relative windows — `ERR_OFFER_WINDOW_EXPIRED`,
    `ERR_FOLLOW_UP_NOT_DUE`, `ERR_EFFECTIVE_AT_OUT_OF_ORDER` or `ERR_CLOCK_NOT_MONOTONIC`,
    422."
    PRD §3.7: "When the denominator is zero the figure is 100.00 — a brand-new program with
    three future-dated rows reports the vacuous 100.00 rather than 0.00."

    Design: Corner/errors/err_follow_up_not_due_returns_422
    """
    env = setup_donated_donor()
    assert env["clock"] == "2026-08-09T06:00:00Z"
    six_month = follow_up_by_interval(env, env["donor_one"]["id"], "SIX_MONTH")
    assert six_month["due_on"].startswith("2027-02-05")

    response = api_client.submit_follow_up(
        six_month["id"],
        {"submitted_fields": follow_up_fields(12)},
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_FOLLOW_UP_NOT_DUE.value, expected_status=422
    )

    reread = follow_up_by_interval(env, env["donor_one"]["id"], "SIX_MONTH")
    assert reread["due_on"].startswith("2027-02-05")
    assert reread["required_fields_count"] == 12
    assert reread["status"] == "DUE"
    assert refresh_program(env)["follow_up_compliance_pct"] == 100.0, "no row is due yet"


def test_err_effective_at_out_of_order_returns_422():
    """PRD §3.2: "It must be at or after the `effective_at` of the candidate's most recent
    waitlist event — at the `WORKUP` starting point no event exists, so only the upper bound
    applies — and it must be at or before the current logical clock."
    PRD §3.2: "A value that precedes the latest event or lies in the clock's future is
    rejected with `ERR_EFFECTIVE_AT_OUT_OF_ORDER`."
    PRD §3.2: "From `APPROVED_NOT_LISTED` the candidate may be registered on the waitlist
    by moving to `ACTIVE`; the first time this happens the candidate's `registered_at` is set
    to the supplied `effective_at`, and later re-entries into `ACTIVE` leave `registered_at`
    alone."
    PRD §3.2: "The new candidate's `listing_status` starts at `WORKUP`, `active_days_total`
    at 0, `offer_decline_count` at 0, and `waitlist_priority_score` is computed immediately —
    with zero accumulated waiting time, since the candidate has never been active."

    Design: Corner/errors/err_effective_at_out_of_order_returns_422
    """
    env = setup_program_with_staff()
    advance_clock(env, "2026-08-05T00:00:00Z")
    recipient = create_recipient(env, mrn="R-001", abo_blood_type="A", age_years=44)
    update_recipient_status(
        env,
        recipient["id"],
        "APPROVED_NOT_LISTED",
        "WORKUP_COMPLETE",
        "2026-08-03T00:00:00Z",
    )

    response = api_client.create_recipient_status_update(
        recipient["id"],
        {
            "to_status": "ACTIVE",
            "reason_code": "LISTED",
            "effective_at": "2026-08-02T00:00:00Z",
        },
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_EFFECTIVE_AT_OUT_OF_ORDER.value, expected_status=422
    )

    after = get_recipient(env, recipient["id"])
    assert after["listing_status"] == "APPROVED_NOT_LISTED"
    assert after["registered_at"] is None
    assert after["active_days_total"] == 0
    _rows, meta = validate_paginated(
        api_client.list_waitlist_events(recipient["id"], env["coordinator_headers"])
    )
    assert meta["total_count"] == 1


def test_err_clock_not_monotonic_returns_422():
    """PRD §2.4: "An administrative capability sets the clock to a supplied `current_utc`
    instant; the clock may only move forward, and an attempt to set it to an earlier instant
    than its current reading is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."
    PRD §2.10: "Clock-relative windows — `ERR_OFFER_WINDOW_EXPIRED`,
    `ERR_FOLLOW_UP_NOT_DUE`, `ERR_EFFECTIVE_AT_OUT_OF_ORDER` or `ERR_CLOCK_NOT_MONOTONIC`,
    422."
    PRD §2.4: "Setting the clock mutates no entity and sweeps no delinquency — a separate
    compliance sweep does that work explicitly."
    PRD §2.4: "Every persisted resource exposes an `id` that is a server-minted UUID with
    no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three
    fractional digits."

    Design: Corner/errors/err_clock_not_monotonic_returns_422
    """
    env = setup_program_with_staff()
    advance_clock(env, "2026-08-10T00:00:00Z")

    response = api_client.set_clock(
        {"current_utc": "2026-08-05T00:00:00Z"}, env["admin_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value, expected_status=422
    )

    validate_success(
        api_client.set_clock(
            {"current_utc": "2026-08-10T00:00:00Z"}, env["admin_headers"]
        )
    )
    recipient = create_recipient(env, mrn="R-001")
    assert recipient["created_at"].startswith("2026-08-10T00:00:00"), (
        "the clock still stands where the refused call found it"
    )


def test_err_cit_limit_exceeded_returns_422():
    """PRD §3.6: "Both figures are compared against the same per-segment ceiling of 1,080
    minutes — eighteen hours — which means an identical clamp-to-reperfusion span can pass as
    an actual figure and fail as a planned one."
    PRD §3.6: "A planned figure of exactly 1,080 is accepted; 1,081 is refused with
    `ERR_CIT_LIMIT_EXCEEDED`."
    PRD §2.10: "Second, within priority 22 the per-segment ceiling is checked before the
    chain-wide budget, so a single over-long segment reports its own error even when the
    chain budget is also blown."
    PRD §3.6: "`planned_cit_minutes` is computed when the offer is sent: it is the whole
    minutes between `planned_cross_clamp_at` and `planned_reperfusion_at`, truncated toward
    zero, plus a fixed forty-five-minute allowance for the final cross-match hold."

    Design: Corner/errors/err_cit_limit_exceeded_returns_422
    """
    env = setup_committed_paired_loop()
    room = add_operating_room(env, "OR-1")
    book_theatre(
        env,
        room["id"],
        env["segment_one"]["id"],
        "DONOR_RECOVERY",
        "2026-08-09T05:00:00Z",
        "2026-08-09T07:00:00Z",
    )
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 0

    response = api_client.send_segment_offer(
        env["segment_one"]["id"],
        create_offer_payload(
            "2026-08-09T06:00:00Z", "2026-08-09T23:16:00Z", planned_transport_minutes=120
        ),
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_CIT_LIMIT_EXCEEDED.value, expected_status=422
    )

    refused = get_segment(env, env["segment_one"]["id"])
    assert refused["status"] == "PLANNED"
    assert refused["planned_cit_minutes"] is None
    assert refused["offer_sent_at"] is None
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 0

    retried = validate_success(
        api_client.send_segment_offer(
            env["segment_one"]["id"],
            create_offer_payload(
                "2026-08-09T06:00:00Z",
                "2026-08-09T23:15:00Z",
                planned_transport_minutes=120,
            ),
            env["coordinator_headers"],
        )
    )
    assert retried["planned_cit_minutes"] == 1080, "one minute earlier sits at the cap"


def test_err_chain_cit_budget_exceeded_returns_422():
    """PRD §3.6: "A total of exactly 2,400 minutes is accepted; 2,401 is refused with
    `ERR_CHAIN_CIT_BUDGET_EXCEEDED`."
    PRD §2.10: "Aggregate ischemia budgets — `ERR_CIT_LIMIT_EXCEEDED` then
    `ERR_CHAIN_CIT_BUDGET_EXCEEDED`, 422."
    PRD §3.6: "The check at offer time is **self-excluding**: it sums the *other*
    qualifying segments and adds this segment's own freshly computed `planned_cit_minutes`,
    so re-offering a segment never double-counts it."
    PRD §2.10: "Second, within priority 22 the per-segment ceiling is checked before the
    chain-wide budget, so a single over-long segment reports its own error even when the
    chain budget is also blown."
    PRD §3.6: "`total_planned_cit_minutes` on a chain is the sum of `planned_cit_minutes`
    over that chain's segments whose status is `OFFER_SENT`, `ACCEPTED` or `TRANSPLANTED`,
    accumulated in `position` ascending and, for ties, `created_at` ascending order."

    Design: Corner/errors/err_chain_cit_budget_exceeded_returns_422
    """
    env = _three_pair_participants()
    _three_segment_loop(env)
    validate_chain(env, env["chain"]["id"])
    committed = validate_success(
        api_client.commit_chain(env["chain"]["id"], env["coordinator_headers"])
    )
    assert committed["status"] == "COMMITTED"
    room_one = add_operating_room(env, "OR-1")
    room_two = add_operating_room(env, "OR-2")
    room_three = add_operating_room(env, "OR-3")
    surgeon_two = add_surgeon(env, npi="1000000007", full_name="Surgeon Two")
    surgeon_three = add_surgeon(env, npi="1000000008", full_name="Surgeon Three")
    book_theatre(
        env,
        room_one["id"],
        env["segment_one"]["id"],
        "DONOR_RECOVERY",
        "2026-08-23T05:00:00Z",
        "2026-08-23T07:00:00Z",
    )
    book_theatre(
        env,
        room_two["id"],
        env["segment_two"]["id"],
        "DONOR_RECOVERY",
        "2026-08-23T23:00:00Z",
        "2026-08-24T01:00:00Z",
        surgeon_id=surgeon_two["id"],
    )
    book_theatre(
        env,
        room_three["id"],
        env["segment_three"]["id"],
        "DONOR_RECOVERY",
        "2026-08-24T16:00:00Z",
        "2026-08-24T18:00:00Z",
        surgeon_id=surgeon_three["id"],
    )
    first = send_offer(
        env, env["segment_one"]["id"], "2026-08-23T06:00:00Z", "2026-08-23T23:15:00Z"
    )
    second = send_offer(
        env, env["segment_two"]["id"], "2026-08-23T23:15:00Z", "2026-08-24T16:30:00Z"
    )
    assert first["planned_cit_minutes"] == 1080
    assert second["planned_cit_minutes"] == 1080
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 2160

    response = api_client.send_segment_offer(
        env["segment_three"]["id"],
        create_offer_payload(
            "2026-08-24T16:30:00Z", "2026-08-25T09:45:00Z", planned_transport_minutes=120
        ),
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_CHAIN_CIT_BUDGET_EXCEEDED.value, expected_status=422
    )

    assert get_segment(env, env["segment_one"]["id"])["planned_cit_minutes"] == 1080
    assert get_segment(env, env["segment_two"]["id"])["planned_cit_minutes"] == 1080
    assert get_chain(env, env["chain"]["id"])["total_planned_cit_minutes"] == 2160, (
        "the refused segment is not added"
    )
    third = get_segment(env, env["segment_three"]["id"])
    assert third["status"] == "PLANNED"
    assert third["planned_cit_minutes"] is None
    assert third["offer_sent_at"] is None


def test_err_plan_not_required_returns_422():
    """PRD §3.8: "The parent review's `flag_level` must be `WATCH` or `FLAGGED`; filing
    against a review whose level is `NONE` is refused with `ERR_PLAN_NOT_REQUIRED`."
    PRD §3.8: "Creation puts the new plan in `SUBMITTED` with `decision_reason_code`,
    `decided_at` and `closed_at` all null, moves any existing plan of the same review whose
    status is `SUBMITTED` or `REJECTED` to `SUPERSEDED` — which the system will only do while
    no plan of that review has already reached `ACCEPTED` or `CLOSED` — and increments the
    parent review's `version` so that a competing writer holding the old value is now stale."
    PRD §3.8: "Otherwise `oe_ratio` is `observed_survivor_count` divided by
    `expected_survivor_count`, rounded half up to **four** decimal places, and `flag_level`
    is `FLAGGED` when `oe_ratio` is strictly below 0.85, `WATCH` when it is strictly below
    0.95 but not below 0.85, and `NONE` otherwise."
    PRD §3.8: "`expected_survivor_count` is `cohort_size` multiplied by
    `expected_survival_rate_used`, rounded half up to two decimal places."
    PRD §2.8: "Then: if an unanswered flagged review exists, the posture is `FROZEN`.
    Otherwise, if `follow_up_compliance_pct` is strictly below the program's
    `follow_up_compliance_threshold_pct`, or an open watch exists, or `cit_breach_count` is
    at least 2, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`."

    Design: Corner/errors/err_plan_not_required_returns_422
    """
    env = setup_program_with_staff()
    review = create_outcome_review(env, cohort_size=25, observed_survivor_count=20)
    finalized = finalize_review(env, review["id"])
    assert finalized["expected_survivor_count"] == 20.0
    assert finalized["oe_ratio"] == 1.0
    assert finalized["flag_level"] == "NONE"
    assert finalized["requires_improvement_plan"] is False

    response = api_client.create_improvement_plan(
        create_improvement_plan_payload(
            review["id"],
            finalized["version"],
            title="Voluntary quality initiative",
            milestone_count=3,
            target_completion_on="2026-12-31",
        ),
        env["quality_headers"],
    )

    validate_error(response, ApiErrorId.ERR_PLAN_NOT_REQUIRED.value, expected_status=422)

    rows, meta = validate_paginated(
        api_client.list_review_improvement_plans(review["id"], env["quality_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert refresh_program(env)["compliance_posture"] == "OPEN"


def test_err_donor_lifetime_cap_reached_returns_422():
    """PRD §3.9: "The headroom must be strictly greater than zero, and a claim arriving at
    zero headroom cannot be approved at all and is refused with
    `ERR_DONOR_LIFETIME_CAP_REACHED`."
    PRD §3.9: "Sum `adjudicated_reimbursement_cents` over this donor's claims whose
    `status` is `ADJUDICATED`; the donor's lifetime cap is 1,500,000 cents (fifteen thousand
    dollars), and the headroom is the cap minus that prior total."
    PRD §3.9: "The insurance bucket has a per-claim ceiling of 600,000 cents (six thousand
    dollars), but only when the claim's `coverage_source` is `RECIPIENT_INSURANCE`; for any
    other coverage source the insurance headroom is zero, so a claim filed against the
    program fund never touches insurance even where a ceiling would have existed."
    PRD §3.9: "For a `LOST_WAGES` claim the cap is the smaller of two figures:
    `lost_wage_days` multiplied by the program's `lost_wage_daily_cap_cents`, and the number
    of weeks — `lost_wage_days` divided by 7 and rounded **up** to a whole week — multiplied
    by the program's `lost_wage_weekly_cap_cents`."
    PRD §2.9: "Committed plus remaining always equals the pool, and remaining is always
    between 0 and the pool inclusive, after every adjudication, denial and reversal."

    Design: Corner/errors/err_donor_lifetime_cap_reached_returns_422
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    medical = file_claim(
        env,
        donor_id,
        claim_type="MEDICAL",
        coverage_source="RECIPIENT_INSURANCE",
        submitted_amount_cents=1000000,
    )
    first = adjudicate_claim(env, medical["id"])
    travel = file_claim(
        env,
        donor_id,
        claim_type="TRAVEL",
        coverage_source="NLDAC_GRANT",
        submitted_amount_cents=350000,
    )
    second = adjudicate_claim(env, travel["id"])
    wages = file_claim(
        env,
        donor_id,
        claim_type="LOST_WAGES",
        coverage_source="NLDAC_GRANT",
        submitted_amount_cents=200000,
        lost_wage_days=5,
    )
    third = adjudicate_claim(env, wages["id"])
    assert first["adjudicated_reimbursement_cents"] == 1000000
    assert second["grant_part_cents"] == 350000
    assert third["grant_part_cents"] == 150000
    fourth = file_claim(
        env, donor_id, claim_type="MEDICAL", submitted_amount_cents=100000
    )
    assert fourth["estimated_reimbursement_cents"] == 100000

    response = api_client.adjudicate_claim(
        fourth["id"], {"decision": "APPROVE"}, env["finance_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_DONOR_LIFETIME_CAP_REACHED.value, expected_status=422
    )

    assert first["insurance_part_cents"] == 600000
    assert first["fund_part_cents"] == 400000
    assert first["unfunded_cents"] == 0
    assert third["estimated_reimbursement_cents"] == 150000, "five days is the crossover"
    rows, _meta = validate_paginated(
        api_client.list_donor_cost_claims(donor_id, env["coordinator_headers"])
    )
    refused = [row for row in rows if row["id"] == fourth["id"]][0]
    assert refused["status"] == "SUBMITTED"
    assert refused["adjudicated_reimbursement_cents"] is None
    assert refused["unfunded_cents"] is None
    program = refresh_program(env)
    assert program["donor_fund_committed_cents"] == 400000
    assert program["donor_fund_remaining_cents"] == 4600000
