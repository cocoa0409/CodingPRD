"""The two declared cascades, hop by hop, inside the single triggering request."""

from test_helpers import (
    assert_slot_conservation,
    assert_team_ledger,
    book_operation,
    candidate_sequence,
    chart_observation,
    converted_case,
    create_team,
    evaluate_organ,
    find_offer,
    list_offers,
    observation_payload,
    open_match_run,
    read_authorization,
    read_case,
    read_hospital,
    read_operation,
    read_organ,
    read_referral,
    read_run,
    read_team,
    record_nok_contact,
    register_organ,
    rescinded_authorization_case,
    respond_to_offer,
)

RESCISSION_CLOCK = "2026-08-14T07:00:00Z"
DECOMPENSATION_CLOCK = "2026-08-15T09:00:00Z"


# ---------------------------------------------------------------------------
# The rescission cascade, five hops deep
# ---------------------------------------------------------------------------
def _authorized_liver_with_booked_theatre(env):
    """A kin-authorized liver accepted by a centre with an operating room booked."""
    bundle = rescinded_authorization_case(env, "LIVER", RESCISSION_CLOCK)
    bundle.run = open_match_run(
        env,
        bundle.only_organ_id,
        candidate_sequence(2, 120),
        primary_offer_slots=1,
    )
    bundle.refresh_offers()
    respond_to_offer(env, bundle.run_id, find_offer(bundle.offers, 1)["id"], "ACCEPT")
    bundle.team = create_team(
        env, specialty="ABDOMINAL", turnaround_buffer_minutes=90
    )
    bundle.operation = book_operation(
        env,
        bundle.case_id,
        bundle.team["id"],
        "2026-08-14T08:00:00Z",
        "2026-08-14T12:00:00Z",
    )
    assert bundle.operation["or_minutes"] == 240
    return bundle


def _object_at_rank_one(env, bundle):
    record_nok_contact(
        env,
        bundle.authorization_id,
        "SPOUSE",
        "OBJECTION",
        contact_note="spouse located and objects",
    )
    return read_authorization(env, bundle.authorization_id)


def test_higher_rank_objection_rescinds_the_packet_and_closes_its_parents(env):
    """Hops one and two: the packet rescinds, the referral and case close.

    PRD 3.3: "the packet moves `AUTHORIZED → RESCINDED` with `rescinded_reason`
    set to `HIGHER_RANK_OBJECTION`".
    PRD 3.3: "Hop two moves the referral `CONVERTED → NOT_CONVERTED`, decrements
    the hospital's `converted_donor_count` by one, and moves the donor case's
    `allocation_status` to `CLOSED` with `closed_reason`
    `AUTHORIZATION_RESCINDED`, which drives `case_posture` to `FROZEN`."

    Design: Difficulty/transitive_cascade/authorization_rescission_cascade_depth_five
    """
    bundle = _authorized_liver_with_booked_theatre(env)

    rescinded = _object_at_rank_one(env, bundle)
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["rescinded_reason"] == "HIGHER_RANK_OBJECTION"

    assert read_referral(env, bundle.referral_id)["status"] == "NOT_CONVERTED"
    assert read_hospital(env, bundle.hospital_id)["converted_donor_count"] == 0

    case = read_case(env, bundle.case_id)
    assert case["allocation_status"] == "CLOSED"
    assert case["closed_reason"] == "AUTHORIZATION_RESCINDED"
    assert case["case_posture"] == "FROZEN"


def test_rescission_marks_the_organ_non_transplantable_and_bypasses_its_offers(env):
    """Hops three and four: the organ is written off and its offers are bypassed.

    PRD 3.3: "takes every organ of the case whose status is `PENDING_EVAL`,
    `ALLOCATABLE`, `OFFERING` or `ACCEPTED` to `NON_TRANSPLANTABLE` with
    `nontransplantable_reason` `AUTHORIZATION_RESCINDED`, clears each one's
    `accepted_offer_id` to null".
    PRD 3.3: "takes every offer on those runs whose status is `QUEUED`,
    `PENDING` or `ACCEPTED` to `BYPASSED` with `bypass_reason` `CASE_CLOSED`,
    resetting each run's `pending_offer_count` to zero and its `slots_free` to
    that run's `primary_offer_slots`".

    Design: Difficulty/transitive_cascade/authorization_rescission_cascade_depth_five
    """
    bundle = _authorized_liver_with_booked_theatre(env)
    # A second organ carries a run that is still `OPEN` with live offers, which
    # is the precondition hop four names: "match runs still in `OPEN`". The
    # liver's own run was already closed by the acceptance.
    bundle.organs["KIDNEY_LEFT"] = evaluate_organ(
        env,
        register_organ(env, bundle.case_id, "KIDNEY_LEFT")["id"],
        "ALLOCATABLE",
    )
    kidney_run = open_match_run(
        env,
        bundle.organ_id("KIDNEY_LEFT"),
        candidate_sequence(2, 120),
        primary_offer_slots=2,
    )
    assert kidney_run["status"] == "OPEN"

    _object_at_rank_one(env, bundle)

    for organ_type in ("LIVER", "KIDNEY_LEFT"):
        organ = read_organ(env, bundle.organ_id(organ_type))
        assert organ["status"] == "NON_TRANSPLANTABLE"
        assert organ["nontransplantable_reason"] == "AUTHORIZATION_RESCINDED"
        assert organ["accepted_offer_id"] is None

    closed = read_run(env, kidney_run["id"])
    assert closed["status"] == "CLOSED"
    assert closed["closed_reason"] == "CASE_CLOSED"
    assert closed["pending_offer_count"] == 0
    assert closed["slots_free"] == closed["primary_offer_slots"]
    assert_slot_conservation(closed)

    for offer in list_offers(env, kidney_run["id"]):
        assert offer["status"] == "BYPASSED"
        assert offer["bypass_reason"] == "CASE_CLOSED"

    # The liver's accepted offer is the `ACCEPTED` member of hop four's bypass
    # set; the run that acceptance already closed keeps its own closed reason.
    accepted_run = read_run(env, bundle.run_id)
    assert accepted_run["status"] == "CLOSED"
    assert accepted_run["pending_offer_count"] == 0
    assert accepted_run["slots_free"] == accepted_run["primary_offer_slots"]
    assert_slot_conservation(accepted_run)

    accepted_offer = find_offer(list_offers(env, bundle.run_id), 1)
    assert accepted_offer["status"] == "BYPASSED"
    assert accepted_offer["bypass_reason"] == "CASE_CLOSED"


def test_rescission_cancels_the_operation_and_releases_the_or_ledger(env):
    """Hop five: the theatre booking is cancelled and its minutes go back.

    PRD 3.3: "takes every recovery operation of the case whose status is
    `SCHEDULED` to `CANCELLED` with `cancelled_reason` `CASE_CLOSED`, which
    decrements the booking team's `booked_or_minutes` by that operation's
    `or_minutes` and its `scheduled_operation_count` by one".

    Design: Difficulty/transitive_cascade/authorization_rescission_cascade_depth_five
    """
    bundle = _authorized_liver_with_booked_theatre(env)
    assert_team_ledger(read_team(env, bundle.team["id"]), 240, 1)

    _object_at_rank_one(env, bundle)

    operation = read_operation(env, bundle.operation["id"])
    assert operation["status"] == "CANCELLED"
    assert operation["cancelled_reason"] == "CASE_CLOSED"
    assert_team_ledger(read_team(env, bundle.team["id"]), 0, 0)


# ---------------------------------------------------------------------------
# The decompensation cascade, four hops deep
# ---------------------------------------------------------------------------
def _optimized_case_offering_a_heart(env):
    bundle = converted_case(
        env,
        DECOMPENSATION_CLOCK,
        organ_types=["HEART", "KIDNEY_RIGHT"],
        patient_mrn="MRN-7801",
    )
    chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-15T08:35:00Z",
            map_mmhg=65,
            pao2_fio2_ratio=320,
            sodium=148,
            urine_output_ml_per_kg_hr=0.7,
            pressor_count=2,
        ),
    )
    for organ_type in ("HEART", "KIDNEY_RIGHT"):
        bundle.organs[organ_type] = evaluate_organ(
            env, bundle.organ_id(organ_type), "ALLOCATABLE"
        )
    bundle.run = open_match_run(
        env,
        bundle.organ_id("HEART"),
        candidate_sequence(2, 60),
        primary_offer_slots=2,
    )
    bundle.refresh_offers()
    assert len(bundle.offers) == 2
    return bundle


def _decompensate(env, bundle):
    return chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-15T08:55:00Z",
            map_mmhg=55,
            pao2_fio2_ratio=180,
            sodium=160,
            urine_output_ml_per_kg_hr=0.3,
            pressor_count=3,
        ),
    )


def test_decompensation_drops_the_index_and_restricts_the_posture(env):
    """Hops one and two: the new snapshot lands and the posture becomes restricted.

    PRD 3.4: "Hop one sets the case's `viability_index` to the new snapshot and
    `physiologic_status` to `DECOMPENSATING`. Hop two re-derives `case_posture`
    from `OPEN` to `RESTRICTED`."

    Design: Difficulty/transitive_cascade/physiologic_decompensation_cascade_depth_four
    """
    bundle = _optimized_case_offering_a_heart(env)
    assert read_case(env, bundle.case_id)["physiologic_status"] == "OPTIMIZED"

    observation = _decompensate(env, bundle)
    assert observation["viability_index_snapshot"] == 20

    case = read_case(env, bundle.case_id)
    assert case["viability_index"] == 20
    assert case["physiologic_status"] == "DECOMPENSATING"
    assert case["case_posture"] == "RESTRICTED"
    assert case["allocation_status"] == "OFFERS_IN_FLIGHT"


def test_decompensation_holds_thoracic_organs_and_spares_abdominal_ones(env):
    """Hop three: the heart is pulled back under a hold, the kidney is untouched.

    PRD 3.4: "takes every organ on the case whose `organ_type` is `HEART`,
    `LUNG_LEFT` or `LUNG_RIGHT` and whose status is `ALLOCATABLE` or `OFFERING`,
    sets its `viability_hold` to true and returns its status to `PENDING_EVAL`;
    abdominal organs are untouched".

    Design: Difficulty/transitive_cascade/physiologic_decompensation_cascade_depth_four
    """
    bundle = _optimized_case_offering_a_heart(env)
    _decompensate(env, bundle)

    heart = read_organ(env, bundle.organ_id("HEART"))
    assert heart["viability_hold"] is True
    assert heart["status"] == "PENDING_EVAL"

    kidney = read_organ(env, bundle.organ_id("KIDNEY_RIGHT"))
    assert kidney["viability_hold"] is False
    assert kidney["status"] == "ALLOCATABLE"


def test_decompensation_closes_the_thoracic_run_and_bypasses_its_offers(env):
    """Hop four: the heart's open run closes and both live offers are bypassed.

    PRD 3.4: "takes each of their match runs still in `OPEN` to `CLOSED` with
    `closed_reason` `VIABILITY_HOLD`, and takes every offer on those runs whose
    status is `QUEUED` or `PENDING` to `BYPASSED` with `bypass_reason`
    `VIABILITY_HOLD`, resetting each run's `pending_offer_count` to zero and its
    `slots_free` to that run's `primary_offer_slots`".

    Design: Difficulty/transitive_cascade/physiologic_decompensation_cascade_depth_four
    """
    bundle = _optimized_case_offering_a_heart(env)
    _decompensate(env, bundle)

    run = read_run(env, bundle.run_id)
    assert run["status"] == "CLOSED"
    assert run["closed_reason"] == "VIABILITY_HOLD"
    assert run["pending_offer_count"] == 0
    assert run["slots_free"] == 2
    assert_slot_conservation(run)

    for offer in list_offers(env, bundle.run_id):
        assert offer["status"] == "BYPASSED"
        assert offer["bypass_reason"] == "VIABILITY_HOLD"
