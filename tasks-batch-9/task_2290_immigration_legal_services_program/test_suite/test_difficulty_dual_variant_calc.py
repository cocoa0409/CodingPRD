"""Depth tests for the two variant-bearing calculations.

Both the urgency score and the readiness gate select a variant from the same
input -- the ``detained`` flag -- yet they behave oppositely, so a single-variant
implementation cannot satisfy both halves of either test below.
"""

from test_helpers import factories
from test_helpers.api_errors import ERR_BLOCKING_EVIDENCE_OUTSTANDING
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_readiness,
    created,
    ok,
)
from test_helpers.fixtures import accept_intake, minimal_world, new_client

# ---------------------------------------------------------------------------
# urgency_calendar_inclusive_vs_strict_statutory_anchor_divergence
# ---------------------------------------------------------------------------

_ASYLUM_FLAGS = {
    "statutory_deadline_date": "2026-11-30",
    "one_year_bar_applies": False,
    "prior_removal_order": False,
    "unaccompanied_minor": False,
}


def _setup_anchor_divergence(api):
    """One client, one sibling matter carrying a hearing, two identical intakes.

    The only difference between the two screened rows is ``detained``.
    """
    env = minimal_world(api, clock="2026-09-01T00:00:00.000Z")
    facility = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso SPC",
                jurisdiction_code="TX-ELP",
                visit_lead_time_hours=48,
                max_daily_visit_slots=2,
                expedited_filing_days=21,
                access_credential_required=False,
            ),
            headers=env.director,
        )
    )
    env["fac_id"] = facility["id"]

    # Alma Reyes: household 3, income 4000000 -> guideline 2572000 -> 155.52 percent.
    client_id = new_client(
        env,
        full_name="Alma Reyes",
        preferred_language_code="es",
        country_of_birth_code="GT",
        date_of_birth="1990-04-11",
        household_size=3,
        annual_household_income_cents=4000000,
    )
    env["client_id"] = client_id

    # The sibling matter M1 and its SCHEDULED MASTER_CALENDAR_HEARING on 2026-09-15.
    m1 = accept_intake(env, client_id, case_type="ADJUSTMENT_OF_STATUS", detained=False)
    created(
        api.create_event(
            factories.event_payload(
                m1["id"],
                event_type="MASTER_CALENDAR_HEARING",
                starts_at_utc="2026-09-15T14:00:00.000Z",
                ends_at_utc="2026-09-15T16:00:00.000Z",
                location_code="EOIRELP",
                assigned_representative_id=env["atty_a_id"],
            ),
            headers=env.director,
        )
    )

    # Two byte-identical ASYLUM_DEFENSIVE intakes differing only in `detained`.
    detained_intake = created(
        api.create_intake(
            factories.intake_payload(
                client_id,
                env["cycle_id"],
                case_type="ASYLUM_DEFENSIVE",
                detained=True,
                facility_id=facility["id"],
                **_ASYLUM_FLAGS
            ),
            headers=env.director,
        )
    )
    free_intake = created(
        api.create_intake(
            factories.intake_payload(
                client_id,
                env["cycle_id"],
                case_type="ASYLUM_DEFENSIVE",
                detained=False,
                **_ASYLUM_FLAGS
            ),
            headers=env.director,
        )
    )
    env.set(i2_id=detained_intake["id"], i3_id=free_intake["id"], m1_id=m1["id"])
    return env


def test_detained_screening_takes_calendar_inclusive_and_anchors_on_a_sibling_hearing(
    api,
):
    """A detained row reads a hearing that sits on a different matter of the client.

    CALENDAR_INCLUSIVE anchors on the earliest of the statutory deadline and any
    SCHEDULED hearing, so the 2026-09-15 hearing on the sibling matter beats the
    2026-11-30 statute and earns the full 25.00 horizon points.

    Design: Difficulty/dual_variant_calc/urgency_calendar_inclusive_vs_strict_statutory_anchor_divergence
    """
    env = _setup_anchor_divergence(api)

    screened = ok(api.screen_intake(env["i2_id"], headers=env.screener))

    assert_fields(
        screened,
        status="SCREENED",
        urgency_variant_applied="CALENDAR_INCLUSIVE",
        urgency_anchor_date="2026-09-15",
        urgency_tier="EMERGENCY",
        legal_eligibility_verdict="ELIGIBLE",
    )
    # ASYLUM_DEFENSIVE 40 + DETAINED 25 + horizon 30 * (1 - 14/84) == 25.00.
    assert_decimal_equals(screened["urgency_score"], "90.00", 2)
    assert_decimal_equals(env.client_row()["fpl_percent"], "155.52", 2)


def test_non_detained_screening_takes_strict_statutory_and_clamps_the_horizon_to_zero(
    api,
):
    """The non-detained twin ignores the calendar entirely and clamps to 0.00 points.

    STRICT_STATUTORY anchors on 2026-11-30, whose 90-day horizon exceeds the
    84-day window, so the horizon term goes negative and is floored at zero --
    a divergence of exactly 50.00 points from its detained twin.

    Design: Difficulty/dual_variant_calc/urgency_calendar_inclusive_vs_strict_statutory_anchor_divergence
    """
    env = _setup_anchor_divergence(api)

    detained_row = ok(api.screen_intake(env["i2_id"], headers=env.screener))
    free_row = ok(api.screen_intake(env["i3_id"], headers=env.screener))

    assert_fields(
        free_row,
        status="SCREENED",
        urgency_variant_applied="STRICT_STATUTORY",
        urgency_anchor_date="2026-11-30",
        urgency_tier="ROUTINE",
    )
    assert_decimal_equals(free_row["urgency_score"], "40.00", 2)
    # 25 detained points plus 25.00 horizon points only CALENDAR_INCLUSIVE can earn.
    assert_decimal_equals(
        float(detained_row["urgency_score"]) - float(free_row["urgency_score"]),
        "50.00",
        2,
    )


# ---------------------------------------------------------------------------
# readiness_weighted_gate_passes_then_strict_gate_blocks_after_release
# ---------------------------------------------------------------------------


def _setup_gate_flip(api):
    """A detained matter sitting exactly on the weighted floor with one open REQUIRED.

    Verified 12 of 16 counted weight points gives readiness_index_weighted
    0.7500 -- exactly the weighted floor -- while the single REQUESTED REQUIRED
    item keeps readiness_ready_strict false.
    """
    env = minimal_world(api, clock="2026-09-01T00:00:00.000Z")
    facility = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso SPC",
                jurisdiction_code="TX-ELP",
                visit_lead_time_hours=48,
                max_daily_visit_slots=2,
                expedited_filing_days=21,
                access_credential_required=False,
            ),
            headers=env.director,
        )
    )
    reviewer = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Rina Castellanos", max_case_load=20, max_supervisees=5
            ),
            headers=env.director,
        )
    )

    # 'en' speaker: interpreter_required false, so no read-back gates certification.
    client_id = new_client(
        env,
        full_name="Peter Nakamura",
        preferred_language_code="en",
        country_of_birth_code="PH",
        date_of_birth="1988-02-03",
        household_size=1,
        annual_household_income_cents=2000000,
    )
    env["client_id"] = client_id

    matter = accept_intake(
        env,
        client_id,
        case_type="VAWA_SELF_PETITION",
        detained=True,
        decision_reason_code="ACCEPTED_DETAINED_PRIORITY",
        facility_id=facility["id"],
        statutory_deadline_date="2026-12-15",
    )
    env["matter_id"] = matter["id"]

    lead = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"], env["atty_a_id"], matter["version"], role_on_case="LEAD"
            ),
            headers=env.director,
        )
    )
    ok(api.transition_assignment(lead["id"], {"action": "ACTIVATE"}, headers=env.director))
    cocounsel = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                reviewer["id"],
                env.matter_version(),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.director,
        )
    )
    ok(
        api.transition_assignment(
            cocounsel["id"], {"action": "ACTIVATE"}, headers=env.director
        )
    )

    # Counted denominator 16, verified numerator 12: one REQUIRED 4-point item is
    # left in REQUESTED while both SUPPORTING items are driven to VERIFIED.
    required_item = created(
        api.create_evidence(
            factories.evidence_payload(
                matter["id"], tier="REQUIRED", weight_points=4, due_date="2026-10-01"
            ),
            headers=env.director,
        )
    )
    for weight, item_type in ((5, "COUNTRY_CONDITIONS"), (7, "WITNESS_STATEMENT")):
        item = created(
            api.create_evidence(
                factories.evidence_payload(
                    matter["id"],
                    tier="SUPPORTING",
                    weight_points=weight,
                    item_type=item_type,
                    due_date="2026-10-01",
                ),
                headers=env.director,
            )
        )
        ok(api.transition_evidence(item["id"], {"action": "RECEIVE"}, headers=env.director))
        ok(api.transition_evidence(item["id"], {"action": "VERIFY"}, headers=env.director))

    declaration = created(
        api.create_declaration(
            factories.declaration_payload(
                matter["id"], lead["id"], language_code="en", word_count=1200
            ),
            headers=env.director,
        )
    )
    ok(
        api.transition_declaration(
            declaration["id"],
            {"action": "SUBMIT_FOR_REVIEW"},
            headers=env.rep_headers(env["atty_a_id"]),
        )
    )
    ok(
        api.transition_declaration(
            declaration["id"],
            {"action": "CERTIFY", "reviewer_assignment_id": cocounsel["id"]},
            headers=env.attorney_headers(reviewer["id"]),
        )
    )
    ok(
        api.advance_filing(
            matter["id"],
            {"target_filing_status": "EVIDENCE_GATHERING"},
            headers=env.director,
        )
    )
    env.set(
        lead_id=lead["id"],
        cocounsel_id=cocounsel["id"],
        decl_id=declaration["id"],
        required_item_id=required_item["id"],
    )
    return env


def test_weighted_gate_admits_the_matter_at_exactly_the_weighted_floor(api):
    """While detained, 0.7500 clears the weighted floor even with a REQUIRED item open.

    The EVIDENCE_WEIGHTED_GATE reads only the index, so readiness_ready_strict
    false and one blocking item do not stop READY_TO_FILE.

    Design: Difficulty/dual_variant_calc/readiness_weighted_gate_passes_then_strict_gate_blocks_after_release
    """
    env = _setup_gate_flip(api)

    before = env.matter()
    assert_readiness(before, index="0.7500", ready_strict=False, blocking_count=1)

    advanced = ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "READY_TO_FILE"},
            headers=env.director,
        )
    )
    assert_fields(
        advanced,
        filing_status="READY_TO_FILE",
        readiness_gate_applied="EVIDENCE_WEIGHTED_GATE",
    )


def test_releasing_the_client_flips_the_gate_and_the_same_evidence_set_now_blocks(api):
    """The identical transition is refused after set-facility releases the client.

    The variant selector re-reads ``detained`` on every recomputation, so the
    unchanged 0.7500 index is now judged by CHECKLIST_STRICT_GATE and answers
    with a different error id.

    Design: Difficulty/dual_variant_calc/readiness_weighted_gate_passes_then_strict_gate_blocks_after_release
    """
    env = _setup_gate_flip(api)

    ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "READY_TO_FILE"},
            headers=env.director,
        )
    )
    reverted = ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "EVIDENCE_GATHERING"},
            headers=env.director,
        )
    )
    assert reverted["filing_status"] == "EVIDENCE_GATHERING"

    released = ok(
        api.set_facility(env["matter_id"], {"detained": False}, headers=env.director)
    )
    assert_fields(
        released, detained=False, facility_id=None, expedited_deadline_date=None
    )

    blocked = api.advance_filing(
        env["matter_id"],
        {"target_filing_status": "READY_TO_FILE"},
        headers=env.director,
    )
    assert_error(blocked, ERR_BLOCKING_EVIDENCE_OUTSTANDING)

    after = env.matter()
    assert after["filing_status"] == "EVIDENCE_GATHERING"
    assert_readiness(
        after, index="0.7500", ready_strict=False, gate="CHECKLIST_STRICT_GATE"
    )
    # No item was waived, so the denominator never moved.
    assert env.evidence_item(env["required_item_id"])["status"] == "REQUESTED"
    assert_fields(
        env.declaration(env["decl_id"]), status="CERTIFIED", readback_completed=False
    )
