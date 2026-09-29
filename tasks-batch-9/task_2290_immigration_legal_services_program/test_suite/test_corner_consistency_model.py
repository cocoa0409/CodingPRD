"""Breadth tests for the immediate-consistency contract.

Every write returns its own consequences already computed, and a refused write
leaves every denormalized counter exactly where it was. Both halves are read by
comparing a write response against an immediate re-read with no sweep, no clock
move and no compensating call in between.
"""

from test_helpers import factories
from test_helpers.api_errors import ERR_NO_SLOT_AVAILABLE
from test_helpers.assertions import (
    assert_data_blocks_identical,
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_no_rows,
    assert_null_fields,
    created,
    ok,
)
from test_helpers.fixtures import accept_intake, minimal_world, new_client

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"


def _staffed_matter_world(api):
    """A cycle at 2026-08-03 with one accepted U_VISA matter under an ACTIVE LEAD.

    The lead is a staff attorney, so the matter reaches STAFFED, which is what
    lets evidence be received against it.
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        cycle_label="FY26-H2",
        period_start_date="2026-08-01",
        period_end_date="2026-12-31",
        total_case_slots=20,
        reserved_detained_slots=4,
    )
    client_id = new_client(
        env,
        full_name="Rosa Mena",
        preferred_language_code="es",
        country_of_birth_code="GT",
        date_of_birth="1990-04-11",
        household_size=3,
        annual_household_income_cents=2000000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    matter = accept_intake(
        env,
        client_id,
        case_type="U_VISA",
        detained=False,
        statutory_deadline_date="2026-12-01",
    )
    assignment = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                env["atty_a_id"],
                matter["version"],
                role_on_case="LEAD",
            ),
            headers=env.director,
        )
    )
    ok(
        api.transition_assignment(
            assignment["id"], {"action": "ACTIVATE"}, headers=env.director
        )
    )
    env.set(client_id=client_id, matter_id=matter["id"], asg_id=assignment["id"])
    return env


def test_a_write_response_already_carries_its_own_derived_fields(api):
    """The client create returns fpl_percent and the screen returns the urgency figures.

    Nothing is computed at intake-open time, so the values that appear on the
    screen response cannot be attributed to a background job, and an immediate
    re-read of either row is identical field for field.

    Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_final_inside_the_writing_response
    """
    env = _staffed_matter_world(api)

    written = created(
        api.create_client(
            factories.client_payload(
                full_name="Bea Rios",
                preferred_language_code="ht",
                country_of_birth_code="HT",
                date_of_birth="1988-02-19",
                household_size=1,
                annual_household_income_cents=3016000,
            ),
            headers=env.screener,
        )
    )
    assert_decimal_equals(written["fpl_percent"], "200.00", 2)
    assert_fields(
        written, interpreter_required=True, confidentiality_consent_scope="PROGRAM_ONLY"
    )
    assert_data_blocks_identical(
        written, env.client_row(written["id"]), label="client create vs immediate read"
    )

    opened = created(
        api.create_intake(
            factories.intake_payload(
                written["id"],
                env["cycle_id"],
                case_type="BOND_HEARING",
                detained=False,
                statutory_deadline_date="2026-09-30",
            ),
            headers=env.screener,
        )
    )
    # PRD 3.3: "A newly created screening carries legal_eligibility_verdict of
    # PENDING, no urgency_score, no urgency_tier and no urgency_variant_applied."
    assert_fields(opened, legal_eligibility_verdict="PENDING")
    assert_null_fields(
        opened, "urgency_score", "urgency_tier", "urgency_variant_applied"
    )

    screened = ok(api.screen_intake(opened["id"], headers=env.screener))
    # 42 base for BOND_HEARING plus 30 * (1 - 58/84) == 9.29 for the 58-day horizon.
    assert_decimal_equals(screened["urgency_score"], "51.29", 2)
    assert_fields(
        screened,
        legal_eligibility_verdict="ELIGIBLE",
        urgency_tier="ELEVATED",
        urgency_variant_applied="STRICT_STATUTORY",
        urgency_anchor_date="2026-09-30",
    )
    assert_data_blocks_identical(
        screened, env.intake(opened["id"]), label="screen vs immediate read"
    )


def test_a_child_transition_has_already_moved_the_parent_rollups(api):
    """Verifying evidence and completing a session both land on the matter at once.

    The readiness figures move from 0.0000 to 1.0000 on the call after VERIFY, and
    the matter's interpretation_cost_cents equals the session's own billable_cents
    on the very next read -- no sweep, no clock move, no re-save of the matter.

    Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_final_inside_the_writing_response
    """
    env = _staffed_matter_world(api)

    item = created(
        api.create_evidence(
            factories.evidence_payload(
                env["matter_id"],
                item_type="IDENTITY_DOCUMENT",
                tier="REQUIRED",
                weight_points=10,
            ),
            headers=env.rep_headers(env["atty_a_id"]),
        )
    )
    before = env.matter()
    assert_decimal_equals(before["readiness_index_weighted"], "0.0000", 4)
    assert_fields(before, readiness_ready_strict=False, evidence_blocking_count=1)

    ok(
        api.transition_evidence(
            item["id"], {"action": "RECEIVE"}, headers=env.rep_headers(env["atty_a_id"])
        )
    )
    ok(
        api.transition_evidence(
            item["id"], {"action": "VERIFY"}, headers=env.rep_headers(env["atty_a_id"])
        )
    )
    after = env.matter()
    assert_decimal_equals(after["readiness_index_weighted"], "1.0000", 4)
    assert_fields(after, readiness_ready_strict=True, evidence_blocking_count=0)

    session = created(
        api.create_session(
            factories.session_payload(
                env["matter_id"],
                language_code="es",
                interpreter_source="CONTRACT",
                purpose="HEARING_PREP",
                # PRD 3.7: "Completing requires ... the logical clock at or after
                # scheduled_start_utc", and the clock stands at 09:00 here.
                scheduled_start_utc="2026-08-03T08:00:00.000Z",
                scheduled_end_utc="2026-08-03T10:00:00.000Z",
            ),
            headers=env.rep_headers(env["atty_a_id"]),
        )
    )
    completed = ok(
        api.transition_session(
            session["id"],
            {"action": "COMPLETE", "actual_minutes": 45},
            headers=env.rep_headers(env["atty_a_id"]),
        )
    )
    # 'es' is a common language, so 9500 * 45/60 == 7125 with no surcharge.
    assert_fields(completed, billed_minutes=45, billable_cents=7125)
    assert env.matter()["interpretation_cost_cents"] == 7125


def test_a_refused_accept_leaves_every_capacity_counter_byte_identical(api):
    """The general pool is empty while available_slot_count still reports 2.

    A non-detained applicant may not draw on the detained reservation, so the
    accept is refused -- and the refusal must not have reserved and released a
    seat: every cycle counter, the cycle's own version, the client's
    open_matter_count and the screening's state are all exactly as before.

    Design: Corner/consistency_model/immediate_consistency_a_rejected_write_leaves_no_partially_applied_counter
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        cycle_label="FY26-H2",
        period_start_date="2026-08-01",
        period_end_date="2026-12-31",
        total_case_slots=5,
        reserved_detained_slots=2,
    )
    for index, name in enumerate(("Ana Uno", "Ben Dos", "Cleo Tres"), start=1):
        filler = new_client(
            env,
            full_name=name,
            preferred_language_code="es",
            country_of_birth_code="GT",
            date_of_birth="199{0}-03-0{0}".format(index),
            household_size=1,
            annual_household_income_cents=1000000,
            confidentiality_consent_scope="PROGRAM_ONLY",
        )
        accept_intake(env, filler, case_type="U_VISA", detained=False)

    bea_id = new_client(
        env,
        full_name="Bea Rios",
        preferred_language_code="es",
        country_of_birth_code="GT",
        date_of_birth="1988-02-19",
        household_size=1,
        annual_household_income_cents=1000000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    intake = created(
        api.create_intake(
            factories.intake_payload(
                bea_id,
                env["cycle_id"],
                case_type="U_VISA",
                detained=False,
                statutory_deadline_date="2026-12-01",
            ),
            headers=env.screener,
        )
    )
    ok(api.screen_intake(intake["id"], headers=env.screener))

    cycle_before = env.cycle()
    assert_fields(
        cycle_before,
        general_slots_consumed=3,
        detained_slots_consumed=0,
        available_slot_count=2,
        waitlisted_count=0,
        capacity_posture="OPEN",
    )
    assert_decimal_equals(cycle_before["utilization_ratio"], "0.6000", 4)
    client_before = env.client_row(bea_id)

    refused = api.decide_intake(
        intake["id"],
        {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
        headers=env.supervisor,
    )
    assert_error(refused, ERR_NO_SLOT_AVAILABLE)

    assert_data_blocks_identical(
        cycle_before, env.cycle(), label="cycle across the refused accept"
    )
    assert_data_blocks_identical(
        client_before, env.client_row(bea_id), label="client across the refused accept"
    )
    assert_fields(env.intake(intake["id"]), status="SCREENED")
    assert_null_fields(
        env.intake(intake["id"]), "decided_by_representative_id", "decided_at_utc"
    )
    assert_no_rows(api.list_matters(params={"client_id": bea_id}, headers=env.director))
