"""Breadth coverage of the derived-figure formulas of sections 3.1 to 3.10.

Each test pins one formula at the points where an implementation is most likely
to drift: the inclusive boundary, the rounding step, the clause ordering and the
tie-break. Values are asserted at the precision the PRD declares for the field.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_BLOCKING_EVIDENCE_OUTSTANDING,
    ERR_CLIENT_CALENDAR_CONFLICT,
    ERR_CONSENT_SCOPE_INSUFFICIENT,
    ERR_FACILITY_CREDENTIAL_EXPIRED,
    ERR_FACILITY_LEAD_TIME_NOT_MET,
    ERR_FACILITY_VISIT_SLOTS_EXHAUSTED,
    ERR_FORUM_GRANT_EMPTY,
    ERR_HOURS_OUT_OF_RANGE,
    ERR_INDIGENCY_CEILING_EXCEEDED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NO_SLOT_AVAILABLE,
    ERR_REPRESENTATIVE_CALENDAR_CONFLICT,
)
from test_helpers.assertions import (
    assert_cents,
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_matter_dimensions,
    assert_null_fields,
    assert_readiness,
    assert_row_count,
    assert_slot_conservation,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import (
    accept_intake,
    add_evidence,
    create_client,
    drive_evidence,
    minimal_world,
    template_a,
    template_b,
)
from test_helpers.test_users import (
    make_supervising_attorney_headers,
    program_director_headers,
)

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"


def test_the_indigency_ceiling_admits_exactly_200_00_percent_and_refuses_200_01(api):
    """The ceiling is inclusive, rounded, and enforced when a screening is opened.

    A single-person household is measured against the $15,080.00 base alone, so
    3,016,000 cents is exactly 200.00 percent and inside the ceiling while
    3,016,151 cents rounds to 200.01 and is outside it. The refusal happens at
    screening creation, not merely at the analytical step -- and it evaporates on
    a fee-exempt case type, where clause 3 of the eligibility ladder never runs.

    Design: Corner/calculations/fpl_percent_is_inclusive_at_exactly_200_00_and_excludes_200_01
    """
    env = minimal_world(api, clock=_CLOCK_UTC, total_case_slots=10, reserved_detained_slots=2)
    household = {
        "preferred_language_code": "en",
        "country_of_birth_code": "HN",
        "date_of_birth": "1988-02-02",
        "household_size": 1,
    }
    alma = create_client(
        env, full_name="Alma Diaz", annual_household_income_cents=3016000, **household
    )
    bruno = create_client(
        env, full_name="Bruno Vega", annual_household_income_cents=3016151, **household
    )
    assert_decimal_equals(alma["fpl_percent"], "200.00", 2)
    assert_decimal_equals(bruno["fpl_percent"], "200.01", 2)

    # exactly at the ceiling: the screening opens and the verdict is clean
    alma_intake = created(
        api.create_intake(
            factories.intake_payload(
                alma["id"], env["cycle_id"], case_type="NATURALIZATION"
            ),
            headers=env.screener,
        )
    )
    screened = ok(api.screen_intake(alma_intake["id"], headers=env.screener))
    assert_fields(screened, status="SCREENED", legal_eligibility_verdict="ELIGIBLE")

    # one cent-scaled step above it: refused at creation on a non-exempt type
    assert_error(
        api.create_intake(
            factories.intake_payload(
                bruno["id"], env["cycle_id"], case_type="NATURALIZATION"
            ),
            headers=env.screener,
        ),
        ERR_INDIGENCY_CEILING_EXCEEDED,
    )

    # the same client on a fee-exempt type is admitted and verdicts as ELIGIBLE
    bruno_intake = created(
        api.create_intake(
            factories.intake_payload(bruno["id"], env["cycle_id"], case_type="U_VISA"),
            headers=env.screener,
        )
    )
    bruno_screened = ok(api.screen_intake(bruno_intake["id"], headers=env.screener))
    assert_fields(bruno_screened, legal_eligibility_verdict="ELIGIBLE")
    assert_row_count(
        api.list_intakes(params={"client_id": bruno["id"]}, headers=env.director), 1
    )


def test_the_eligibility_ladder_reports_the_first_matching_clause_only(api):
    """Two clauses match at once and the earlier one is the verdict.

    A detained NATURALIZATION screening with a prior removal order at an
    unserved facility satisfies clause 1 and clause 2 together; the contract
    pins clause 1. Dropping the removal order drops the verdict to clause 2, and
    moving the same screening to a served jurisdiction clears the ladder
    entirely on identical income. The urgency figures are computed either way --
    an ineligible verdict does not suppress them.

    Design: Corner/calculations/eligibility_clause_order_prefers_no_relief_then_jurisdiction_over_later_clauses
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        total_case_slots=10,
        reserved_detained_slots=2,
        languages=["en", "es"],
    )
    unserved = created(
        api.create_facility(
            factories.facility_payload(
                name="Northview Processing",
                jurisdiction_code="NYELZ",
                visit_lead_time_hours=24,
                max_daily_visit_slots=2,
                expedited_filing_days=21,
            ),
            headers=env.director,
        )
    )
    served = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso Service Center",
                jurisdiction_code="TX-ELP",
                visit_lead_time_hours=24,
                max_daily_visit_slots=2,
                expedited_filing_days=21,
            ),
            headers=env.director,
        )
    )
    client = create_client(env)
    assert_decimal_equals(client["fpl_percent"], "77.76", 2)

    def screen(**fields):
        intake = created(
            api.create_intake(
                factories.intake_payload(
                    client["id"],
                    env["cycle_id"],
                    case_type="NATURALIZATION",
                    detained=True,
                    **fields
                ),
                headers=env.screener,
            )
        )
        return ok(api.screen_intake(intake["id"], headers=env.screener))

    # clause 1 and clause 2 both match; clause 1 is reported
    both = screen(facility_id=unserved["id"], prior_removal_order=True)
    assert_fields(
        both,
        legal_eligibility_verdict="INELIGIBLE_NO_RELIEF",
        urgency_tier="ROUTINE",
    )
    assert_decimal_equals(both["urgency_score"], "43.00", 2)

    # remove the clause-1 trigger and clause 2 surfaces
    jurisdiction = screen(facility_id=unserved["id"], prior_removal_order=False)
    assert_fields(
        jurisdiction,
        legal_eligibility_verdict="INELIGIBLE_JURISDICTION",
        urgency_tier="ROUTINE",
    )
    assert_decimal_equals(jurisdiction["urgency_score"], "33.00", 2)

    # a served jurisdiction clears the ladder on the same income
    eligible = screen(facility_id=served["id"], prior_removal_order=False)
    assert_fields(eligible, legal_eligibility_verdict="ELIGIBLE")


def test_the_single_detained_flag_moves_the_score_fifty_points_and_two_tier_bands(api):
    """Two byte-identical screenings diverge on `detained` alone.

    Both name `ASYLUM_DEFENSIVE` with a statutory deadline of 2026-11-01, which
    is 90 days out and so beyond the 84-day span: the strict statutory geometry
    anchors there, earns no horizon points and scores 40.00 / ROUTINE. The
    calendar-inclusive geometry reaches across the client's other matter to her
    2026-08-17 hearing, 14 days out, earning exactly 25.00 horizon points on top
    of the 25 detention points for 90.00 / EMERGENCY.

    Design: Corner/calculations/urgency_dual_variant_detained_calendar_inclusive_scores_fifty_points_higher
    """
    env = template_a(api, clock=_CLOCK_UTC)
    facility = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso Service Center",
                jurisdiction_code="TX-ELP",
                visit_lead_time_hours=24,
                max_daily_visit_slots=2,
            ),
            headers=env.director,
        )
    )
    hearing = created(
        api.create_event(
            factories.event_payload(
                env["matter_id"],
                event_type="INDIVIDUAL_HEARING",
                starts_at_utc="2026-08-17T13:00:00.000Z",
                ends_at_utc="2026-08-17T15:00:00.000Z",
                location_code="EOIRCRT",
                assigned_representative_id=env["atty_a_id"],
            ),
            headers=env.supervisor,
        )
    )
    assert_fields(hearing, status="SCHEDULED", travel_buffer_minutes=60)
    assert_fields(env.matter(), filing_status="PRE_FILING")

    def screen(**fields):
        intake = created(
            api.create_intake(
                factories.intake_payload(
                    env["client_id"],
                    env["cycle_id"],
                    case_type="ASYLUM_DEFENSIVE",
                    statutory_deadline_date="2026-11-01",
                    **fields
                ),
                headers=env.screener,
            )
        )
        return ok(api.screen_intake(intake["id"], headers=env.screener))

    strict = screen(detained=False)
    assert_fields(
        strict,
        legal_eligibility_verdict="ELIGIBLE",
        urgency_variant_applied="STRICT_STATUTORY",
        urgency_anchor_date="2026-11-01",
        urgency_tier="ROUTINE",
    )
    assert_decimal_equals(strict["urgency_score"], "40.00", 2)

    calendar = screen(detained=True, facility_id=facility["id"])
    assert_fields(
        calendar,
        legal_eligibility_verdict="ELIGIBLE",
        urgency_variant_applied="CALENDAR_INCLUSIVE",
        urgency_anchor_date="2026-08-17",
        urgency_tier="EMERGENCY",
    )
    assert_decimal_equals(calendar["urgency_score"], "90.00", 2)
    delta = float(calendar["urgency_score"]) - float(strict["urgency_score"])
    assert_decimal_equals(delta, "50.00", 2)


def test_the_horizon_curve_caps_floors_and_rounds_at_two_decimals(api):
    """Four screenings pin the horizon component at its interesting points.

    A deadline already past earns the full 30-point ceiling; a deadline exactly
    84 days out earns 0.00 because the span is the floor; 83 days out earns
    30/84 = 0.357142..., which must be reported as a two-decimal 40.36; and no
    deadline at all leaves the anchor null and the component at zero.

    Design: Corner/calculations/urgency_horizon_points_cap_and_span_boundary_and_pre_add_rounding
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        total_case_slots=10,
        reserved_detained_slots=2,
        languages=["en", "es"],
    )
    client = create_client(env)

    def screen(**fields):
        intake = created(
            api.create_intake(
                factories.intake_payload(
                    client["id"],
                    env["cycle_id"],
                    case_type="ASYLUM_DEFENSIVE",
                    detained=False,
                    **fields
                ),
                headers=env.screener,
            )
        )
        return ok(api.screen_intake(intake["id"], headers=env.screener))

    past = screen(statutory_deadline_date="2026-07-01")
    assert_fields(past, urgency_tier="URGENT", urgency_anchor_date="2026-07-01")
    assert_decimal_equals(past["urgency_score"], "70.00", 2)

    at_span = screen(statutory_deadline_date="2026-10-26")
    assert_fields(at_span, urgency_tier="ROUTINE", urgency_anchor_date="2026-10-26")
    assert_decimal_equals(at_span["urgency_score"], "40.00", 2)

    inside_span = screen(statutory_deadline_date="2026-10-25")
    assert_fields(inside_span, urgency_tier="ROUTINE")
    assert_decimal_equals(inside_span["urgency_score"], "40.36", 2)

    no_anchor = screen()
    assert_decimal_equals(no_anchor["urgency_score"], "40.00", 2)
    assert no_anchor["urgency_anchor_date"] is None, no_anchor["urgency_anchor_date"]
    for row in (past, at_span, inside_span, no_anchor):
        assert_fields(row, urgency_variant_applied="STRICT_STATUTORY")


def test_the_general_pool_runs_dry_while_the_reservation_still_holds_a_seat(api):
    """A free seat in the reserved block is invisible to a non-detained accept.

    Five slots with one reserved leave four general seats. The fourth general
    acceptance takes utilization to exactly 0.8000 -- restricted at the inclusive
    boundary -- and the fifth is refused for want of a slot even though
    `available_slot_count` still reports 1, because the waterfall for a
    non-detained screening contains the general pool alone. A detained
    BOND_HEARING then drains the reservation and freezes the cycle.

    Design: Corner/calculations/waterfall_rejects_general_intake_while_reserved_block_keeps_a_free_slot
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        total_case_slots=5,
        reserved_detained_slots=1,
        languages=["en", "es"],
    )
    facility = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso Service Center", jurisdiction_code="TX-ELP"
            ),
            headers=env.director,
        )
    )
    client = create_client(env)
    for _ in range(4):
        accept_intake(env, client["id"], case_type="U_VISA")

    restricted = env.cycle()
    assert_fields(
        restricted,
        general_slots_consumed=4,
        detained_slots_consumed=0,
        available_slot_count=1,
        capacity_posture="RESTRICTED",
    )
    assert_decimal_equals(restricted["utilization_ratio"], "0.8000", 4)
    assert_slot_conservation(restricted)

    # the fifth general accept: slot availability is reported before the posture
    fifth = created(
        api.create_intake(
            factories.intake_payload(client["id"], env["cycle_id"], case_type="U_VISA"),
            headers=env.screener,
        )
    )
    ok(api.screen_intake(fifth["id"], headers=env.screener))
    assert_error(
        api.decide_intake(
            fifth["id"],
            {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
            headers=env.supervisor,
        ),
        ERR_NO_SLOT_AVAILABLE,
    )
    assert_fields(env.intake(fifth["id"]), status="SCREENED")
    assert_fields(env.cycle(), available_slot_count=1, general_slots_consumed=4)

    # a detained screening reaches the reserved pool the general one cannot see
    detained = created(
        api.create_intake(
            factories.intake_payload(
                client["id"],
                env["cycle_id"],
                case_type="BOND_HEARING",
                detained=True,
                facility_id=facility["id"],
            ),
            headers=env.screener,
        )
    )
    screened = ok(api.screen_intake(detained["id"], headers=env.screener))
    assert_fields(screened, legal_eligibility_verdict="ELIGIBLE", urgency_tier="URGENT")
    accepted = ok(
        api.decide_intake(
            detained["id"],
            {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
            headers=env.supervisor,
        )
    )
    assert_fields(accepted, status="ACCEPTED")
    minted = only_row(
        api.list_matters(params={"intake_id": detained["id"]}, headers=env.director)
    )
    assert_fields(minted, detained=True, slot_pool_consumed="DETAINED_RESERVED")

    frozen = env.cycle()
    assert_fields(
        frozen,
        general_slots_consumed=4,
        detained_slots_consumed=1,
        available_slot_count=0,
        capacity_posture="FROZEN",
    )
    assert_decimal_equals(frozen["utilization_ratio"], "1.0000", 4)
    assert_slot_conservation(frozen)
    assert_row_count(
        api.list_matters(params={"cycle_id": env["cycle_id"]}, headers=env.director), 5
    )
    assert_fields(env.client_row(client["id"]), open_matter_count=5, status="ACTIVE")


def test_leaving_detention_flips_the_readiness_gate_and_the_error_id_with_it(api):
    """Identical evidence passes one gate and fails the other.

    A detained matter sits at exactly 0.7500 weighted readiness with one open
    required item: the weighted gate is inclusive at that boundary, so the
    advance succeeds. Releasing the client from detention through set-facility
    changes no evidence at all, yet the next identical advance is refused -- and
    refused with `ERR_BLOCKING_EVIDENCE_OUTSTANDING` rather than the detained
    gate's `ERR_MATTER_NOT_READY`. Verifying the open item then satisfies the
    strict checklist gate.

    Design: Corner/calculations/readiness_gate_flips_error_id_when_the_client_leaves_detention_at_exactly_0_7500
    """
    director = program_director_headers()
    ok(api.set_clock(_CLOCK_UTC, headers=director))
    facility = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso Service Center",
                jurisdiction_code="TX-ELP",
                visit_lead_time_hours=24,
                max_daily_visit_slots=2,
                expedited_filing_days=21,
            ),
            headers=director,
        )
    )
    env = template_b(
        api,
        clock=_CLOCK_UTC,
        case_type="ASYLUM_DEFENSIVE",
        detained=True,
        facility_id=facility["id"],
    )

    # 8 open REQUIRED points against 24 verified SUPPORTING points: exactly 0.7500
    required_id, = add_evidence(env, [8], tier="REQUIRED", item_type="POLICE_REPORT")
    for item_id in add_evidence(
        env, [8, 8, 8], tier="SUPPORTING", item_type="COUNTRY_CONDITIONS"
    ):
        drive_evidence(env, item_id, "RECEIVE", "VERIFY")
    ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "EVIDENCE_GATHERING"},
            headers=env.supervisor,
        )
    )
    detained_matter = env.matter()
    assert_fields(
        detained_matter,
        detained=True,
        forum="EOIR_IMMIGRATION_COURT",
        interpretation_cost_cents=7125,
    )
    assert_readiness(
        detained_matter, index="0.7500", ready_strict=False, blocking_count=1
    )

    # the weighted gate is inclusive at 0.7500 even with a required item open
    ready = ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "READY_TO_FILE"},
            headers=env.supervisor,
        )
    )
    assert_fields(
        ready,
        filing_status="READY_TO_FILE",
        readiness_gate_applied="EVIDENCE_WEIGHTED_GATE",
    )
    ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "EVIDENCE_GATHERING"},
            headers=env.supervisor,
        )
    )

    # release from detention: the evidence is untouched, the gate is not
    released = ok(
        api.set_facility(env["matter_id"], {"detained": False}, headers=env.supervisor)
    )
    assert_fields(released, detained=False)
    for field in ("facility_id", "expedited_deadline_date", "effective_filing_deadline_date"):
        assert released[field] is None, "{0}: {1!r}".format(field, released[field])
    assert_readiness(released, index="0.7500", ready_strict=False)

    assert_error(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "READY_TO_FILE"},
            headers=env.supervisor,
        ),
        ERR_BLOCKING_EVIDENCE_OUTSTANDING,
    )
    assert_matter_dimensions(env.matter(), filing_status="EVIDENCE_GATHERING")

    # verifying the open required item satisfies the strict gate instead
    drive_evidence(env, required_id, "RECEIVE", "VERIFY")
    assert_readiness(env.matter(), index="1.0000", ready_strict=True, blocking_count=0)
    strict = ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "READY_TO_FILE"},
            headers=env.supervisor,
        )
    )
    assert_fields(
        strict,
        filing_status="READY_TO_FILE",
        readiness_gate_applied="CHECKLIST_STRICT_GATE",
    )


def test_auto_selection_prefers_headroom_over_creation_order_and_drops_the_wrong_language(api):
    """The four-key ranking is exercised at its second key.

    Ada and Cleo both supervise nobody, so the first key ties and the second --
    descending headroom -- must pick Cleo's ceiling of 5 over Ada's 2, even
    though Ada was created first and would win the final `created_at` key. Dov
    has the largest headroom of all but does not speak the client's language, so
    the eligibility filter removes him before any ranking happens.

    Design: Corner/calculations/supervisor_auto_selection_uses_headroom_tiebreak_not_creation_order
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        total_case_slots=10,
        reserved_detained_slots=2,
        languages=["en", "es"],
    )
    ada = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Ada Ortiz", max_supervisees=2),
            headers=env.director,
        )
    )
    cleo = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Cleo Park", max_supervisees=5),
            headers=env.director,
        )
    )
    dov = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Dov Adler", languages=["en"], max_supervisees=20
            ),
            headers=env.director,
        )
    )
    volunteer = created(
        api.create_representative(
            factories.volunteer_payload(full_name="Vic Lang", languages=["en", "es"]),
            headers=env.director,
        )
    )
    client = create_client(env)
    matter = accept_intake(env, client["id"], case_type="U_VISA")
    env["matter_id"] = matter["id"]

    supervisor_ids = {}
    for rep in (ada, cleo, dov):
        row = created(
            api.create_assignment(
                factories.assignment_payload(
                    matter["id"],
                    rep["id"],
                    env.matter_version(),
                    role_on_case="SUPERVISOR",
                ),
                headers=env.supervisor,
            )
        )
        ok(api.transition_assignment(row["id"], {"action": "ACTIVATE"}, headers=env.supervisor))
        supervisor_ids[rep["full_name"]] = row["id"]

    lead = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"], volunteer["id"], env.matter_version(), role_on_case="LEAD"
            ),
            headers=env.supervisor,
        )
    )
    assert_fields(
        lead,
        status="PROPOSED",
        supervision_source="AUTO_SELECTED",
        supervision_link_id=supervisor_ids["Cleo Park"],
    )
    assert lead["supervision_link_id"] not in (
        supervisor_ids["Ada Ortiz"],
        supervisor_ids["Dov Adler"],
    ), lead["supervision_link_id"]

    activated = ok(
        api.transition_assignment(lead["id"], {"action": "ACTIVATE"}, headers=env.supervisor)
    )
    assert_fields(activated, status="ACTIVE")
    assert_matter_dimensions(env.matter(), representation_status="SUPERVISED_STAFFED")
    assert_fields(env.representative(cleo["id"]), supervisee_count=1)
    assert_fields(env.representative(ada["id"]), supervisee_count=0)
    assert_fields(env.representative(dov["id"]), supervisee_count=0)
    assert_fields(
        env.representative(volunteer["id"]),
        active_case_load=1,
        authorization_status="AUTHORIZED_SUPERVISED",
    )


def test_each_session_is_rounded_before_the_matter_total_is_summed(api):
    """Per-session rounding, the 30-minute floor, the zero rate and a cancellation.

    Two Haitian-Creole contract sessions each bill 5,462.5 cents before rounding,
    which is 5,463 apiece and 10,926 together -- summing the unrounded halves
    first would report 10,925. A one-minute telephonic session still bills the
    30-minute floor, a staff interpreter bills nothing across three and a half
    hours, and a cancelled session never enters the total at all.

    Design: Corner/calculations/interpretation_cost_rounds_per_session_then_sums_to_14026
    """
    env = template_a(api, clock=_CLOCK_UTC)
    interpreter = created(
        api.create_representative(
            factories.volunteer_payload(full_name="Vic Lang", languages=["en", "ht"]),
            headers=env.director,
        )
    )

    def book(**fields):
        # the shared window, which a caller may override for its own session
        fields.setdefault("scheduled_start_utc", "2026-08-03T07:00:00.000Z")
        fields.setdefault("scheduled_end_utc", "2026-08-03T08:00:00.000Z")
        return created(
            api.create_session(
                factories.session_payload(env["matter_id"], **fields),
                headers=env.supervisor,
            )
        )

    def complete(session_id, minutes):
        return ok(
            api.transition_session(
                session_id,
                {"action": "COMPLETE", "actual_minutes": minutes},
                headers=env.lead_rep,
            )
        )

    rare_one = book(language_code="ht", interpreter_source="CONTRACT", purpose="HEARING_PREP")
    rare_two = book(
        language_code="ht", interpreter_source="CONTRACT", purpose="RIGHTS_COUNSELING"
    )
    telephonic = book(language_code="es", interpreter_source="TELEPHONIC", purpose="INTAKE")
    in_house = book(
        language_code="ht",
        interpreter_source="STAFF",
        purpose="HEARING_PREP",
        interpreter_representative_id=interpreter["id"],
    )
    cancelled = book(
        language_code="ht",
        interpreter_source="CONTRACT",
        purpose="HEARING_PREP",
        scheduled_start_utc="2026-08-05T07:00:00.000Z",
        scheduled_end_utc="2026-08-05T08:00:00.000Z",
    )

    first = complete(rare_one["id"], 22)
    assert_fields(first, status="COMPLETED", billed_minutes=30, billable_cents=5463)
    second = complete(rare_two["id"], 22)
    assert_fields(second, billed_minutes=30, billable_cents=5463)
    assert_fields(env.matter(), interpretation_cost_cents=10926)

    floored = complete(telephonic["id"], 1)
    assert_fields(floored, billed_minutes=30, billable_cents=3100)
    free = complete(in_house["id"], 210)
    assert_fields(free, billed_minutes=210, billable_cents=0)
    voided = ok(
        api.transition_session(
            cancelled["id"],
            {"action": "CANCEL", "closure_reason_code": "INTERPRETER_UNAVAILABLE"},
            headers=env.lead_rep,
        )
    )
    assert_fields(voided, status="CANCELLED", billed_minutes=0, billable_cents=0)

    assert_fields(env.matter(), interpretation_cost_cents=14026)
    assert_row_count(
        api.list_sessions(
            params={"matter_id": env["matter_id"], "status": "COMPLETED"},
            headers=env.director,
        ),
        4,
    )


def test_the_travel_buffer_comes_from_the_existing_event_and_dies_at_a_shared_location(api):
    """The buffer that governs is the one belonging to the event already booked.

    Ada's individual hearing carries a 60-minute buffer, so a 30-minute
    biometrics appointment at a different location is blocked until the hearing's
    end plus 60 -- the candidate's own stored `travel_buffer_minutes` of 30 is a
    decoy that never enters the scan. One millisecond before that boundary is
    refused; the boundary itself is accepted, because the geometry is half-open.
    At the hearing's own location the buffer collapses to nothing and a start
    exactly at its end is clear.

    Design: Corner/calculations/representative_buffer_is_taken_from_the_existing_event_and_zeroed_by_a_shared_location
    """
    env = template_a(api, clock=_CLOCK_UTC)
    ada = env["atty_a_id"]

    def book(starts, ends, location, event_type="BIOMETRICS"):
        return api.create_event(
            factories.event_payload(
                env["matter_id"],
                event_type=event_type,
                starts_at_utc=starts,
                ends_at_utc=ends,
                location_code=location,
                assigned_representative_id=ada,
                client_conflict_waived=True,
            ),
            headers=env.director,
        )

    hearing = created(
        book(
            "2026-09-10T14:00:00.000Z",
            "2026-09-10T15:00:00.000Z",
            "EOIRCRT",
            event_type="INDIVIDUAL_HEARING",
        )
    )
    assert_fields(hearing, travel_buffer_minutes=60, status="SCHEDULED")

    # one millisecond inside the existing event's 60-minute shadow
    assert_error(
        book("2026-09-10T15:59:59.999Z", "2026-09-10T16:30:00.000Z", "USCISASC"),
        ERR_REPRESENTATIVE_CALENDAR_CONFLICT,
    )

    # exactly at end + 60 the half-open comparison lets it through
    at_boundary = created(
        book("2026-09-10T16:00:00.000Z", "2026-09-10T16:30:00.000Z", "USCISASC")
    )
    assert_fields(at_boundary, travel_buffer_minutes=30, status="SCHEDULED")

    # sharing the hearing's location zeroes the buffer entirely
    same_place = created(
        book("2026-09-10T15:00:00.000Z", "2026-09-10T15:30:00.000Z", "EOIRCRT")
    )
    assert_fields(
        same_place, status="SCHEDULED", reschedule_count=0, travel_buffer_minutes=30
    )
    assert same_place["continued_from_event_id"] is None, same_place[
        "continued_from_event_id"
    ]
    assert_row_count(
        api.list_events(
            params={"matter_id": env["matter_id"], "assigned_representative_id": ada},
            headers=env.director,
        ),
        3,
    )


def test_the_client_geometry_is_closed_crosses_matters_and_loses_to_the_representative_one(api):
    """The client scan uses the opposite boundary convention and runs second.

    Rosa's two matters carry events assigned to two different representatives, so
    only the client geometry can see the pair. It is fully closed: a candidate
    starting at the exact millisecond the other ends collides, and one
    millisecond later is clear. A filing deadline is exempt on either side and
    books squarely inside the occupied window. A candidate that trips both
    geometries reports the representative conflict.

    Design: Corner/calculations/client_geometry_is_fully_closed_crosses_matters_and_yields_to_the_representative_geometry
    """
    env = template_a(api, clock=_CLOCK_UTC)
    second = accept_intake(env, env["client_id"], case_type="NATURALIZATION")
    second_lead = created(
        api.create_assignment(
            factories.assignment_payload(
                second["id"], env["atty_b_id"], second["version"], role_on_case="LEAD"
            ),
            headers=env.director,
        )
    )
    ok(api.transition_assignment(second_lead["id"], {"action": "ACTIVATE"}, headers=env.director))
    first_event = created(
        api.create_event(
            factories.event_payload(
                env["matter_id"],
                event_type="BIOMETRICS",
                starts_at_utc="2026-09-14T09:00:00.000Z",
                ends_at_utc="2026-09-14T10:00:00.000Z",
                location_code="USCISASC",
                assigned_representative_id=env["atty_a_id"],
            ),
            headers=env.director,
        )
    )
    assert_fields(first_event, status="SCHEDULED", client_conflict_waived=False)

    def book(starts, ends, representative_id, event_type="BIOMETRICS", location="USCISASC"):
        return api.create_event(
            factories.event_payload(
                second["id"],
                event_type=event_type,
                starts_at_utc=starts,
                ends_at_utc=ends,
                location_code=location,
                assigned_representative_id=representative_id,
            ),
            headers=env.director,
        )

    # closed endpoints: a start at the other event's end collides
    assert_error(
        book("2026-09-14T10:00:00.000Z", "2026-09-14T11:00:00.000Z", env["atty_b_id"]),
        ERR_CLIENT_CALENDAR_CONFLICT,
    )

    # a filing deadline is exempt on the candidate side
    deadline = created(
        book(
            "2026-09-14T09:30:00.000Z",
            "2026-09-14T09:31:00.000Z",
            env["atty_b_id"],
            event_type="FILING_DEADLINE",
            location="MAIL",
        )
    )
    assert_fields(deadline, status="SCHEDULED", travel_buffer_minutes=0)

    # one millisecond past the closed endpoint is clear, and the deadline is
    # exempt on the existing side too
    clear = created(
        book("2026-09-14T10:00:00.001Z", "2026-09-14T11:00:00.000Z", env["atty_b_id"])
    )
    assert_fields(clear, status="SCHEDULED")

    # both geometries trip at once: the representative id is the one reported
    assert_error(
        book("2026-09-14T09:30:00.000Z", "2026-09-14T09:45:00.000Z", env["atty_a_id"]),
        ERR_REPRESENTATIVE_CALENDAR_CONFLICT,
    )
    assert_row_count(
        api.list_events(params={"matter_id": env["matter_id"]}, headers=env.director), 1
    )
    assert_row_count(
        api.list_events(params={"matter_id": second["id"]}, headers=env.director), 2
    )


def test_the_facility_geometry_counts_visits_per_date_after_lead_time_and_credential(api):
    """A facility visit clears three separate hurdles before it is booked.

    The lead time is pinned to the millisecond against the logical clock, the
    credential comparison is made at UTC-date granularity so a credential
    expiring on the event's own date still counts, and the facility geometry is a
    per-date count rather than an interval test -- so a second visit eleven hours
    later on the same date is refused while one the next day is fine.

    Design: Corner/calculations/facility_visit_lead_time_credential_and_per_date_slot_aggregate
    """
    env = template_a(api, clock=_CLOCK_UTC)
    facility = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso SPC {0}".format(env["cycle_id"][:8]),
                jurisdiction_code="TX-ELP",
                visit_lead_time_hours=48,
                max_daily_visit_slots=1,
                expedited_filing_days=21,
                access_credential_required=True,
            ),
            headers=env.director,
        )
    )
    # a credential expiring exactly on the event date, and one far in the future
    assert_fields(
        ok(
            api.update_representative(
                env["atty_a_id"],
                {"facility_access_credential_expires_on": "2026-08-05"},
                headers=env.director,
            )
        ),
        facility_access_credential_expires_on="2026-08-05",
    )
    ok(
        api.update_representative(
            env["screener_id"],
            {"facility_access_credential_expires_on": "2026-12-31"},
            headers=env.director,
        )
    )
    assert_null_fields(env.representative(env["atty_b_id"]), "facility_access_credential_expires_on")

    def visit(starts, ends, representative_id):
        return api.create_event(
            factories.event_payload(
                env["matter_id"],
                event_type="FACILITY_VISIT",
                starts_at_utc=starts,
                ends_at_utc=ends,
                location_code="TXELPDET",
                facility_id=facility["id"],
                assigned_representative_id=representative_id,
                client_conflict_waived=True,
            ),
            headers=env.director,
        )

    # one millisecond short of clock + 48h
    assert_error(
        visit("2026-08-05T08:59:59.999Z", "2026-08-05T10:00:00.000Z", env["atty_a_id"]),
        ERR_FACILITY_LEAD_TIME_NOT_MET,
    )

    # lead time satisfied, but Ben Cole holds no credential at all
    assert_error(
        visit("2026-08-05T09:00:00.000Z", "2026-08-05T10:00:00.000Z", env["atty_b_id"]),
        ERR_FACILITY_CREDENTIAL_EXPIRED,
    )

    # exactly at the boundary, with a credential expiring on the event's date
    first = created(
        visit("2026-08-05T09:00:00.000Z", "2026-08-05T10:00:00.000Z", env["atty_a_id"])
    )
    assert_fields(first, status="SCHEDULED", travel_buffer_minutes=90)

    # eleven hours later, a different representative: the aggregate still bites
    assert_error(
        visit("2026-08-05T20:00:00.000Z", "2026-08-05T21:00:00.000Z", env["screener_id"]),
        ERR_FACILITY_VISIT_SLOTS_EXHAUSTED,
    )

    # the UTC calendar date of starts_at_utc opens a fresh slot
    second = created(
        visit("2026-08-06T20:00:00.000Z", "2026-08-06T21:00:00.000Z", env["screener_id"])
    )
    assert_fields(second, status="SCHEDULED")
    booked = assert_row_count(
        api.list_events(
            params={"facility_id": facility["id"], "status": "SCHEDULED"},
            headers=env.director,
        ),
        2,
    )
    assert sorted(row["id"] for row in booked) == sorted([first["id"], second["id"]])


def test_hours_are_rounded_at_every_accumulation_not_once_at_the_end(api):
    """Rounding half up after each entry is normative, and it is observable.

    Logging 0.005, 1.005 and 2.335 hours in sequence lands on 3.36; deferring the
    rounding to a single pass over 3.345 would land on 3.35. The same endpoint
    reports its numeric bound, its zero floor and its kind/role cross-check under
    one shared error id.

    Design: Corner/calculations/hours_rollup_rounds_at_every_accumulation_step_not_once_at_the_end
    """
    env = template_a(api, clock=_CLOCK_UTC)
    lead_id = env["lead_id"]
    rep = env.rep_headers(env["atty_a_id"])

    def log(hours, hours_kind="DIRECT", service_date="2026-08-03"):
        return api.log_hours(
            lead_id,
            {"hours": hours, "hours_kind": hours_kind, "service_date": service_date},
            headers=rep,
        )

    assert_decimal_equals(ok(log(0.005))["direct_hours_logged"], "0.01", 2)
    # round(0.01 + 1.005) == 1.02, never round(1.01)
    assert_decimal_equals(ok(log(1.005))["direct_hours_logged"], "1.02", 2)
    assert_decimal_equals(ok(log(2.335))["direct_hours_logged"], "3.36", 2)
    matter = env.matter()
    assert_decimal_equals(matter["direct_hours_logged"], "3.36", 2)
    assert_decimal_equals(matter["supervision_hours_logged"], "0.00", 2)

    assert_error(log(12.01), ERR_HOURS_OUT_OF_RANGE)
    assert_error(log(0), ERR_HOURS_OUT_OF_RANGE)
    # SUPERVISION time against a LEAD assignment shares the range error id
    assert_error(log(1.5, hours_kind="SUPERVISION"), ERR_HOURS_OUT_OF_RANGE)
    assert_decimal_equals(env.assignment(lead_id)["direct_hours_logged"], "3.36", 2)

    # exactly the ceiling is accepted
    assert_decimal_equals(
        ok(log(12, service_date="2026-08-04"))["direct_hours_logged"], "15.36", 2
    )
    assert_decimal_equals(env.matter()["direct_hours_logged"], "15.36", 2)


def test_the_surcharge_tier_opens_at_the_boundary_and_the_spare_cent_goes_to_the_older_line(api):
    """A base of exactly 500,000 cents takes the 0.06 rate, not 0.00.

    Two matters at 12.01 and 27.99 direct hours are rounded to cents per matter
    before being summed, landing the base precisely on the tier's inclusive lower
    bound. The tier is read from the base alone, so the 530,000-cent total never
    feeds back into the rate. Both ideal shares then end in exactly half a cent,
    so a single leftover cent is distributed and the allocation still closes on
    the total.

    Design: Corner/calculations/grant_rollup_tier_boundary_then_largest_remainder_gives_the_extra_cent_to_the_older_matter
    """
    env = template_a(api, clock=_CLOCK_UTC)
    second = accept_intake(env, env["client_id"], case_type="NATURALIZATION")
    second_lead = created(
        api.create_assignment(
            factories.assignment_payload(
                second["id"], env["atty_b_id"], second["version"], role_on_case="LEAD"
            ),
            headers=env.director,
        )
    )
    ok(api.transition_assignment(second_lead["id"], {"action": "ACTIVATE"}, headers=env.director))

    def log(assignment_id, representative_id, hours):
        return ok(
            api.log_hours(
                assignment_id,
                {"hours": hours, "hours_kind": "DIRECT", "service_date": "2026-08-03"},
                headers=env.rep_headers(representative_id),
            )
        )

    log(env["lead_id"], env["atty_a_id"], 12)
    log(env["lead_id"], env["atty_a_id"], 0.01)
    for hours in (12, 12, 3.99):
        log(second_lead["id"], env["atty_b_id"], hours)
    assert_decimal_equals(env.matter()["direct_hours_logged"], "12.01", 2)
    assert_decimal_equals(env.matter(second["id"])["direct_hours_logged"], "27.99", 2)

    report = created(
        api.create_grant_report(
            factories.grant_report_payload(
                env["cycle_id"],
                disclosure_level="AGGREGATE_ONLY",
                period_start_date="2026-08-01",
                period_end_date="2026-08-31",
                grant_code="EOIRLOP26",
            ),
            headers=env.analyst,
        )
    )
    assert_fields(report, status="DRAFT", base_reimbursable_cents=0, amendment_round=0)

    generated = ok(
        api.transition_grant_report(report["id"], {"action": "GENERATE"}, headers=env.analyst)
    )
    assert_fields(
        generated,
        status="GENERATED",
        cases_served_count=2,
        version=2,
    )
    # round(12500 * 12.01) + round(12500 * 27.99), rounded per matter
    assert_cents(generated, "base_reimbursable_cents", 500000)
    # exactly at SURCHARGE_TIER_1_MIN the 0.06 rate applies
    assert_cents(generated, "supervision_surcharge_cents", 30000)
    assert_cents(generated, "total_reimbursable_cents", 530000)
    # ideals of 159132.5 and 370867.5: one leftover cent, allocation still closes
    assert_cents(generated, "allocated_line_total_cents", 530000)
    assert generated["rounding_remainder_cents"] == 1, generated["rounding_remainder_cents"]
    assert generated["outcomes_summary"] == {"NOT_YET_DECIDED": 2}, generated[
        "outcomes_summary"
    ]


def test_waiving_evidence_raises_the_index_and_keeps_the_required_population(api):
    """A waived row leaves the denominator, so the index climbs.

    Waiving an unverified supporting item raises the index because the counted
    set shrinks on both sides of the fraction, and waiving the last open required
    item flips strict readiness to true even though nothing further was ever
    verified -- the required population still counts the waived row, so the
    at-least-one-required guard holds. Waiving a verified item, the other
    direction the index could move, is not reachable: `VERIFIED` is not one of
    the four legal source states for a waiver.

    Design: Corner/calculations/waiving_evidence_moves_the_index_in_both_directions_yet_keeps_required_total
    """
    env = template_a(api, clock=_CLOCK_UTC)
    # weight_points is capped at 10 per item, so the recipe's 24/8/12/6 shape is
    # carried by 10/4/8/3 -- the same 18/25, 18/22 and 18/18 fractions.
    r1 = add_evidence(env, [10], tier="REQUIRED", item_type="IDENTITY_DOCUMENT")[0]
    r2 = add_evidence(env, [4], tier="REQUIRED", item_type="POLICE_REPORT")[0]
    s1 = add_evidence(env, [8], tier="SUPPORTING", item_type="MEDICAL_RECORD")[0]
    s2 = add_evidence(env, [3], tier="SUPPORTING", item_type="COUNTRY_CONDITIONS")[0]
    drive_evidence(env, r1, "RECEIVE", "VERIFY")
    drive_evidence(env, s1, "RECEIVE", "VERIFY")

    before = env.matter()
    assert_readiness(before, index="0.7200", ready_strict=False, blocking_count=1)
    baseline_version = before["version"]

    def waive(item_id):
        return api.transition_evidence(
            item_id,
            {"action": "WAIVE", "disposition_reason_code": "UNOBTAINABLE_COUNTRY_CONDITIONS"},
            headers=env.supervisor,
        )

    # waiving the unverified supporting item: 18/22 rounded half up at 4dp
    assert_fields(ok(waive(s2)), status="WAIVED")
    assert_readiness(env.matter(), index="0.8182", ready_strict=False, blocking_count=1)

    # waiving the last open required item: a WAIVED REQUIRED row still counts
    # toward the required population, so strict readiness becomes reachable
    assert_fields(ok(waive(r2)), status="WAIVED")
    assert_readiness(env.matter(), index="1.0000", ready_strict=True, blocking_count=0)

    # the verified required item cannot be waived at all
    assert_error(waive(r1), ERR_INVALID_STATE_TRANSITION)
    after = env.matter()
    assert_readiness(after, index="1.0000", ready_strict=True, blocking_count=0)
    assert after["version"] == baseline_version + 2, after["version"]
    assert_row_count(
        api.list_evidence(
            params={"matter_id": env["matter_id"], "status": "WAIVED"},
            headers=env.supervisor,
        ),
        2,
    )


def test_the_reporting_window_is_inclusive_and_withdrawal_leaves_the_line_set_entirely(api):
    """The population is keyed off the accepted screening's decision date.

    A one-day period reports only the intakes decided that day: Rosa's, decided
    four weeks earlier, is out, and Ivo's, decided the following day, is out. A
    withdrawn matter is removed from the line set rather than suppressed, so it
    lowers the served count and appears in neither consent counter. Suppression
    then follows the disclosure ladder, and at the identified level an
    insufficient scope refuses generation outright instead of suppressing.

    Design: Corner/calculations/partition_window_is_inclusive_excludes_withdrawn_and_gates_on_the_consent_ladder
    """
    env = template_a(api, clock=_CLOCK_UTC)
    ok(api.set_clock("2026-08-31T12:00:00.000Z", headers=env.director))
    luis = create_client(
        env,
        full_name="Luis Diaz",
        country_of_birth_code="HN",
        date_of_birth="1988-02-02",
        household_size=2,
        annual_household_income_cents=1500000,
        confidentiality_consent_scope="FUNDER_AGGREGATE",
    )
    ana = create_client(
        env,
        full_name="Ana Sol",
        country_of_birth_code="SV",
        date_of_birth="1992-03-03",
        household_size=2,
        annual_household_income_cents=1500000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    eva = create_client(
        env,
        full_name="Eva Roth",
        preferred_language_code="en",
        country_of_birth_code="RO",
        date_of_birth="1979-07-07",
        household_size=1,
        annual_household_income_cents=1200000,
        confidentiality_consent_scope="FUNDER_IDENTIFIED",
    )
    ivo = create_client(
        env,
        full_name="Ivo Kral",
        preferred_language_code="en",
        country_of_birth_code="CZ",
        date_of_birth="1985-05-05",
        household_size=1,
        annual_household_income_cents=1000000,
        confidentiality_consent_scope="FUNDER_IDENTIFIED",
    )
    accept_intake(env, luis["id"])
    accept_intake(env, ana["id"])
    eva_matter = accept_intake(env, eva["id"], case_type="NATURALIZATION")
    ok(api.withdraw_intake(eva_matter["intake_id_used"], headers=env.screener))
    assert_matter_dimensions(
        env.matter(eva_matter["id"]),
        representation_status="WITHDRAWN_FROM",
        filing_status="CLOSED_NO_FILING",
    )
    assert_fields(env.matter(eva_matter["id"]), outcome="WITHDRAWN")

    ok(api.set_clock("2026-09-01T12:00:00.000Z", headers=env.director))
    accept_intake(env, ivo["id"])

    def one_day_report(disclosure_level):
        return created(
            api.create_grant_report(
                factories.grant_report_payload(
                    env["cycle_id"],
                    disclosure_level=disclosure_level,
                    period_start_date="2026-08-31",
                    period_end_date="2026-08-31",
                ),
                headers=env.analyst,
            )
        )

    # a period whose start equals its end is legal inside the cycle window
    deid = one_day_report("DEIDENTIFIED_CASE_LEVEL")
    identified = one_day_report("IDENTIFIED_WITH_CONSENT")

    generated = ok(
        api.transition_grant_report(deid["id"], {"action": "GENERATE"}, headers=env.analyst)
    )
    assert_fields(
        generated,
        status="GENERATED",
        cases_served_count=2,
        consent_verified_count=1,
        suppressed_case_count=1,
    )
    assert generated["outcomes_summary"] == {"NOT_YET_DECIDED": 2}, generated[
        "outcomes_summary"
    ]

    # IDENTIFIED_WITH_CONSENT admits only FUNDER_IDENTIFIED, and Luis is one step short
    assert_error(
        api.transition_grant_report(
            identified["id"], {"action": "GENERATE"}, headers=env.analyst
        ),
        ERR_CONSENT_SCOPE_INSUFFICIENT,
    )
    untouched = ok(api.get_grant_report(identified["id"], headers=env.analyst))
    assert_fields(
        untouched,
        status="DRAFT",
        version=1,
        cases_served_count=0,
        consent_verified_count=0,
        suppressed_case_count=0,
        base_reimbursable_cents=0,
        total_reimbursable_cents=0,
        allocated_line_total_cents=0,
    )


def test_the_forum_follows_the_case_type_and_the_effective_deadline_is_the_earlier_candidate(api):
    """Where the client sits never moves the forum, and null is not an early date.

    A detained affirmative-asylum matter is still an asylum-office matter, and a
    non-detained bond hearing is still an immigration-court matter. The detained
    matter carries both a statutory and an expedited candidate and resolves to
    the earlier expedited one; the other carries neither candidate and resolves
    to null rather than collapsing onto a dropped candidate.

    Design: Corner/calculations/forum_is_case_type_driven_and_the_effective_deadline_is_the_min_of_candidates
    """
    env = template_a(api, clock=_CLOCK_UTC)
    facility = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso SPC {0}".format(env["cycle_id"][:8]),
                jurisdiction_code="TX-ELP",
                expedited_filing_days=21,
                access_credential_required=False,
            ),
            headers=env.director,
        )
    )
    detained_matter = accept_intake(
        env,
        env["client_id"],
        case_type="ASYLUM_AFFIRMATIVE",
        detained=True,
        facility_id=facility["id"],
        statutory_deadline_date="2026-09-30",
    )
    bond_matter = accept_intake(env, env["client_id"], case_type="BOND_HEARING")

    detained_row = env.matter(detained_matter["id"])
    assert_fields(
        detained_row,
        forum="ASYLUM_OFFICE",
        detained=True,
        facility_id=facility["id"],
        statutory_deadline_date="2026-09-30",
        # decision date 2026-08-03 plus expedited_filing_days 21
        expedited_deadline_date="2026-08-24",
        # the earlier of the two non-null candidates
        effective_filing_deadline_date="2026-08-24",
    )

    bond_row = env.matter(bond_matter["id"])
    assert_fields(bond_row, forum="EOIR_IMMIGRATION_COURT", detained=False)
    assert_null_fields(
        bond_row,
        "facility_id",
        "statutory_deadline_date",
        "expedited_deadline_date",
        "effective_filing_deadline_date",
    )


def test_the_forum_grant_is_a_three_way_intersection_sorted_alphabetically(api):
    """Requested, recognised and type-capped forums must all agree.

    A partial accreditation requesting all four forums under a recognition
    holding three still reaches only the two below the partial ceiling, returned
    in alphabetical rather than request order. A full accreditation is capped by
    the recognition instead. And a partial request for the court alone intersects
    to nothing, which is refused rather than granted empty.

    Design: Corner/calculations/forum_grant_is_a_triple_intersection_with_a_partial_type_ceiling
    """
    director = program_director_headers()
    ok(api.set_clock(_CLOCK_UTC, headers=director))
    approver = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Ada Ortiz", bar_number="BAR-1001"),
            headers=director,
        )
    )
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                effective_date="2026-01-01",
                expiry_date="2030-01-01",
                authorized_forums=["USCIS", "ASYLUM_OFFICE", "EOIR_IMMIGRATION_COURT"],
            ),
            headers=director,
        )
    )
    assert_fields(recognition, status="ACTIVE")

    def accredited_rep(full_name):
        return created(
            api.create_representative(
                factories.accredited_rep_payload(full_name=full_name), headers=director
            )
        )

    def accreditation(representative_id, accreditation_type, requested_forums):
        row = created(
            api.create_accreditation(
                factories.accreditation_payload(
                    representative_id,
                    recognition["id"],
                    accreditation_type=accreditation_type,
                    requested_forums=requested_forums,
                ),
                headers=director,
            )
        )
        assert_fields(row, status="PENDING", authorized_forums=[], renewal_round=0)
        assert_null_fields(row, "effective_date", "expiry_date")
        return row

    all_four = ["USCIS", "BIA", "EOIR_IMMIGRATION_COURT", "ASYLUM_OFFICE"]
    rep_partial = accredited_rep("Nadia Rey")
    rep_full = accredited_rep("Omar Vale")
    rep_empty = accredited_rep("Pia Lund")
    acc_partial = accreditation(rep_partial["id"], "PARTIAL", all_four)
    acc_full = accreditation(rep_full["id"], "FULL", all_four)
    acc_empty = accreditation(rep_empty["id"], "PARTIAL", ["EOIR_IMMIGRATION_COURT"])
    approve_headers = make_supervising_attorney_headers(approver["id"])

    def approve(accreditation_id):
        return api.transition_accreditation(
            accreditation_id, {"action": "APPROVE"}, headers=approve_headers
        )

    # the PARTIAL ceiling drops the court even though the recognition holds it
    granted_partial = ok(approve(acc_partial["id"]))
    assert_fields(
        granted_partial,
        status="APPROVED",
        authorized_forums=["ASYLUM_OFFICE", "USCIS"],
        # the logical clock date plus 1095 days, across the 2028 leap day
        effective_date="2026-08-03",
        expiry_date="2029-08-02",
        approved_by_representative_id=approver["id"],
        renewal_round=0,
    )

    # the FULL ceiling admits all four, so the recognition is what binds
    granted_full = ok(approve(acc_full["id"]))
    assert_fields(
        granted_full,
        status="APPROVED",
        authorized_forums=["ASYLUM_OFFICE", "EOIR_IMMIGRATION_COURT", "USCIS"],
        effective_date="2026-08-03",
        expiry_date="2029-08-02",
    )
    for representative_id in (rep_partial["id"], rep_full["id"]):
        assert_fields(
            ok(api.get_representative(representative_id, headers=director)),
            authorization_status="AUTHORIZED_ACCREDITED",
        )

    # partial ceiling against a court-only request: the intersection is empty
    assert_error(approve(acc_empty["id"]), ERR_FORUM_GRANT_EMPTY)
    assert_fields(
        ok(api.get_accreditation(acc_empty["id"], headers=director)),
        status="PENDING",
        authorized_forums=[],
    )
    assert_fields(
        ok(api.get_representative(rep_empty["id"], headers=director)),
        authorization_status="UNAUTHORIZED",
    )


def test_the_authorization_ladder_is_first_match_across_all_four_representative_types(api):
    """Suspension short-circuits the ladder before any type branch is reached.

    A staff attorney is authorised by the bar alone and never by an accreditation;
    an accredited representative holding only a pending accreditation is
    unauthorised, because the qualifying filter is an explicit enum set; and both
    non-attorney families land on supervised authority with no credential at all.
    Suspending the attorney overrides its valid bar number, while making the
    volunteer inactive falls through to a different id entirely.

    Design: Corner/calculations/authorization_status_ladder_is_first_match_across_all_four_rep_types
    """
    director = program_director_headers()
    ok(api.set_clock(_CLOCK_UTC, headers=director))
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(effective_date="2026-01-01", expiry_date="2030-01-01"),
            headers=director,
        )
    )
    attorney = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Ada Ortiz", bar_number="BAR-1001"),
            headers=director,
        )
    )
    accredited = created(
        api.create_representative(
            factories.accredited_rep_payload(full_name="Nadia Rey"), headers=director
        )
    )
    volunteer = created(
        api.create_representative(
            factories.volunteer_payload(full_name="Vic Lang"), headers=director
        )
    )
    graduate = created(
        api.create_representative(
            factories.law_graduate_payload(full_name="Gus Reed"), headers=director
        )
    )
    pending = created(
        api.create_accreditation(
            factories.accreditation_payload(
                accredited["id"],
                recognition["id"],
                accreditation_type="PARTIAL",
                requested_forums=["USCIS"],
            ),
            headers=director,
        )
    )
    assert_fields(pending, status="PENDING")

    def read(representative_id):
        return ok(api.get_representative(representative_id, headers=director))

    # clause 2: the bar alone, with no accreditation anywhere in sight
    assert_fields(
        read(attorney["id"]),
        authorization_status="AUTHORIZED_ATTORNEY",
        supervision_required=False,
    )
    # clause 3: PENDING is outside {APPROVED, EXPIRING, RENEWAL_PENDING}, and no
    # SUSPENDED_BY_RECOGNITION row exists to reach the middle branch
    assert_fields(
        read(accredited["id"]),
        authorization_status="UNAUTHORIZED",
        supervision_required=True,
    )
    # clause 4: both non-attorney families need only an ACTIVE status
    assert_fields(
        read(volunteer["id"]),
        authorization_status="AUTHORIZED_SUPERVISED",
        supervision_required=True,
    )
    assert_fields(
        read(graduate["id"]),
        authorization_status="AUTHORIZED_SUPERVISED",
        supervision_required=True,
    )

    # clause 1 dominates: the still-valid bar number does not survive suspension
    suspended = ok(
        api.update_representative(attorney["id"], {"status": "SUSPENDED"}, headers=director)
    )
    assert_fields(
        suspended,
        status="SUSPENDED",
        authorization_status="AUTHORIZATION_SUSPENDED",
        bar_number="BAR-1001",
        version=attorney["version"] + 1,
    )
    # INACTIVE is not SUSPENDED, so clause 4 fails its own ACTIVE test instead
    sidelined = ok(
        api.update_representative(volunteer["id"], {"status": "INACTIVE"}, headers=director)
    )
    assert_fields(
        sidelined,
        status="INACTIVE",
        authorization_status="UNAUTHORIZED",
        version=volunteer["version"] + 1,
    )
