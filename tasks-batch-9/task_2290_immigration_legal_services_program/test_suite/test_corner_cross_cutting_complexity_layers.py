"""Breadth tests for the layers that cut across every entity.

Optimistic concurrency on a shared parent, the ordered five-hop recognition-lapse
cascade, and the two variant-bearing calculations that behave oppositely under a
later change of the same flag.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_BLOCKING_EVIDENCE_OUTSTANDING,
    ERR_MATTER_NOT_READY,
    ERR_ROLE_NOT_PERMITTED,
    ERR_STALE_MATTER_VERSION,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_row_count,
    created,
    ok,
)
from test_helpers.fixtures import (
    accept_intake,
    add_evidence,
    add_supervisor_assignment,
    drive_evidence,
    minimal_world,
    new_client,
    recognition_with_accredited_rep,
    template_a,
    template_b,
)
from test_helpers.test_users import program_director_headers

# ---------------------------------------------------------------------------
# occ_case_assignment_create_rejects_a_stale_matter_token_and_version_moves_on
# _every_write
# ---------------------------------------------------------------------------


def test_the_matter_token_is_single_use_because_each_staffing_write_bumps_it(api):
    """The token captured when the matter was minted is already two generations old.

    The LEAD create bumped the matter once and its ACTIVATE bumped it again, so a
    caller holding the acceptance-time version is refused; the refusal leaves no
    assignment row and does not itself move the version, so the refreshed token
    works -- and then dies, because its own success advanced the version.

    Design: Corner/cross_cutting_complexity_layers/occ_case_assignment_create_rejects_a_stale_matter_token_and_version_moves_on_every_write
    """
    env = template_a(api)
    v_at_creation = env["matter_v1"]
    v_after_lead = env.matter_version()
    assert v_after_lead == v_at_creation + 2

    def cocounsel(token):
        return factories.assignment_payload(
            env["matter_id"], env["atty_b_id"], token, role_on_case="CO_COUNSEL"
        )

    stale = api.create_assignment(cocounsel(v_at_creation), headers=env.supervisor)
    assert_error(stale, ERR_STALE_MATTER_VERSION)
    assert_row_count(
        api.list_assignments(
            params={"matter_id": env["matter_id"]}, headers=env.director
        ),
        1,
    )
    assert env.matter_version() == v_after_lead

    accepted = created(
        api.create_assignment(cocounsel(v_after_lead), headers=env.supervisor)
    )
    assert_fields(accepted, role_on_case="CO_COUNSEL", status="PROPOSED")
    assert env.matter_version() == v_after_lead + 1

    reused = api.create_assignment(cocounsel(v_after_lead), headers=env.supervisor)
    assert_error(reused, ERR_STALE_MATTER_VERSION)
    assert_row_count(
        api.list_assignments(
            params={"matter_id": env["matter_id"]}, headers=env.director
        ),
        2,
    )


def test_a_child_write_kills_the_token_and_the_role_check_outranks_staleness(api):
    """An evidence transition -- nothing to do with staffing -- invalidates the token.

    That is the precise reason the guard exists, and it is also why the same stale
    token presented by a GrantAnalyst reports the role denial instead: the role
    check sits far ahead of the stale-version guards, which are evaluated last of
    all, so a caller with the wrong role never learns its token went stale.

    Design: Corner/cross_cutting_complexity_layers/occ_case_assignment_create_rejects_a_stale_matter_token_and_version_moves_on_every_write
    """
    env = template_a(api)
    item = created(
        api.create_evidence(
            factories.evidence_payload(
                env["matter_id"], tier="REQUIRED", weight_points=8
            ),
            headers=env.lead_rep,
        )
    )
    token = env.matter_version()
    ok(api.transition_evidence(item["id"], {"action": "RECEIVE"}, headers=env.lead_rep))
    assert env.matter_version() == token + 1

    def coordinator(version):
        return factories.assignment_payload(
            env["matter_id"],
            env["screener_id"],
            version,
            role_on_case="INTERPRETER_COORDINATOR",
        )

    stale = api.create_assignment(coordinator(token), headers=env.supervisor)
    assert_error(stale, ERR_STALE_MATTER_VERSION)

    wrong_role = api.create_assignment(coordinator(token), headers=env.analyst)
    assert_error(wrong_role, ERR_ROLE_NOT_PERMITTED)

    fresh = created(
        api.create_assignment(coordinator(env.matter_version()), headers=env.supervisor)
    )
    assert_fields(fresh, role_on_case="INTERPRETER_COORDINATOR", status="PROPOSED")
    assert_row_count(
        api.list_assignments(
            params={"matter_id": env["matter_id"]}, headers=env.director
        ),
        2,
    )


# ---------------------------------------------------------------------------
# occ_informed_decision_create_rejects_a_stale_matter_token_before_it
# _supersedes_prior_counseling
# ---------------------------------------------------------------------------


def _counseled_matter(api):
    """TEMPLATE B plus one acknowledged FILE_AFFIRMATIVE decision.

    The client's own acknowledgement is what makes the row DOCUMENTED, and only a
    DOCUMENTED row of the same decision_type is supersedable -- so this is the
    exact state in which a stale second create would silently retire counseling it
    never read.
    """
    env = template_b(api)
    token = env.matter_version()
    first = created(
        api.create_informed_decision(
            factories.informed_decision_payload(
                env["matter_id"], env["lead_id"], token
            ),
            headers=env.lead_rep,
        )
    )
    assert_fields(
        first,
        status="PENDING",
        language_match_verified=True,
        superseded_by_decision_id=None,
    )
    assert env.matter_version() == token + 1

    acknowledged = ok(
        api.transition_informed_decision(
            first["id"], {"action": "ACKNOWLEDGE"}, headers=env.portal
        )
    )
    assert_fields(acknowledged, status="DOCUMENTED")
    env.set(stale_token=token, dec1_id=first["id"])
    return env


def test_a_stale_token_is_refused_before_any_counseling_is_superseded(api):
    """The 412 lands ahead of the supersede, so the prior decision is left whole.

    The token offered is the one the caller held before the first decision was
    even created, which that create invalidated by advancing the matter's version.
    The refusal must not have retired the DOCUMENTED row on its way out: its
    status and its null superseded_by_decision_id are the proof.

    Design: Corner/cross_cutting_complexity_layers/occ_informed_decision_create_rejects_a_stale_matter_token_before_it_supersedes_prior_counseling
    """
    env = _counseled_matter(api)

    refused = api.create_informed_decision(
        factories.informed_decision_payload(
            env["matter_id"], env["cocounsel_id"], env["stale_token"]
        ),
        headers=env.supervisor,
    )
    assert_error(refused, ERR_STALE_MATTER_VERSION)

    assert_fields(
        env.informed_decision(env["dec1_id"]),
        status="DOCUMENTED",
        superseded_by_decision_id=None,
    )
    assert_row_count(
        api.list_informed_decisions(
            params={"matter_id": env["matter_id"]}, headers=env.director
        ),
        1,
    )


def test_the_refreshed_create_retires_the_prior_row_in_place(api):
    """Supersession rewrites the older row rather than deleting it.

    Nobody invokes a supersede action: creating a second decision of the same
    decision_type performs it, which is exactly why the operation carries a
    concurrency token at all.

    Design: Corner/cross_cutting_complexity_layers/occ_informed_decision_create_rejects_a_stale_matter_token_before_it_supersedes_prior_counseling
    """
    env = _counseled_matter(api)

    second = created(
        api.create_informed_decision(
            factories.informed_decision_payload(
                env["matter_id"], env["cocounsel_id"], env.matter_version()
            ),
            headers=env.supervisor,
        )
    )
    assert_fields(second, status="PENDING", superseded_by_decision_id=None)
    assert_fields(
        env.informed_decision(env["dec1_id"]),
        status="SUPERSEDED",
        superseded_by_decision_id=second["id"],
    )
    assert_row_count(
        api.list_informed_decisions(
            params={"matter_id": env["matter_id"]}, headers=env.director
        ),
        2,
    )


# ---------------------------------------------------------------------------
# dual_variant_urgency_is_frozen_at_screen_time_while_the_readiness_gate
# _variant_re_selects_on_every_read
# ---------------------------------------------------------------------------

_EXPECTED_INDEX = "0.7273"


def _detained_matter_short_of_both_gates(api):
    """A detained EOIR matter at 0.7273 weighted readiness with one open REQUIRED item.

    Sixteen verified points out of twenty-two counted is short of the weighted
    gate's 0.7500, and the one RECEIVED-but-unverified REQUIRED item keeps
    readiness_ready_strict false, so the SAME evidence set fails under either
    variant -- with a different error id. The declaration is CERTIFIED so that the
    gate itself, not the missing declaration, is what refuses the advance.
    """
    facility = created(
        api.create_facility(
            factories.facility_payload(
                name="El Paso Service Processing Center",
                jurisdiction_code="TX-ELP",
                expedited_filing_days=21,
                visit_lead_time_hours=48,
            ),
            headers=program_director_headers(),
        )
    )
    env = template_a(
        api,
        case_type="ASYLUM_DEFENSIVE",
        detained=True,
        facility_id=facility["id"],
        intake_fields={"statutory_deadline_date": "2026-09-30"},
    )
    template_b(env=env)

    items = add_evidence(env, [8, 8, 6])
    drive_evidence(env, items[0], "RECEIVE", "VERIFY")
    drive_evidence(env, items[1], "RECEIVE", "VERIFY")
    drive_evidence(env, items[2], "RECEIVE")

    ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "EVIDENCE_GATHERING"},
            headers=env.lead_rep,
        )
    )
    env.set(fac_id=facility["id"])
    return env


def test_the_detained_matter_is_scored_urgent_and_refused_by_the_weighted_gate(api):
    """Screening froze CALENDAR_INCLUSIVE at 74.29; the weighted gate wants 0.7500.

    Base 40 for ASYLUM_DEFENSIVE plus 25 for detention plus a horizon component of
    9.29 for the 58 whole days to the statutory bar clears the inclusive URGENT
    bound of 65.00. The advance is then refused by the weighted gate alone -- open
    REQUIRED items do not matter to that variant, only the index does.

    Design: Corner/cross_cutting_complexity_layers/dual_variant_urgency_is_frozen_at_screen_time_while_the_readiness_gate_variant_re_selects_on_every_read
    """
    env = _detained_matter_short_of_both_gates(api)

    screening = env.intake(env["intake_id"])
    assert_decimal_equals(screening["urgency_score"], "74.29", 2)
    assert_fields(
        screening,
        urgency_tier="URGENT",
        urgency_variant_applied="CALENDAR_INCLUSIVE",
        urgency_anchor_date="2026-09-30",
    )

    matter = env.matter()
    assert_decimal_equals(matter["readiness_index_weighted"], _EXPECTED_INDEX, 4)
    assert_fields(matter, readiness_ready_strict=False, detained=True)

    refused = api.advance_filing(
        env["matter_id"],
        {"target_filing_status": "READY_TO_FILE"},
        headers=env.lead_rep,
    )
    assert_error(refused, ERR_MATTER_NOT_READY)
    assert_fields(env.matter(), filing_status="EVIDENCE_GATHERING")


def test_releasing_the_client_flips_the_gate_but_never_re_scores_the_urgency(api):
    """One flag drives both variants, and they answer to it on opposite schedules.

    Clearing detention re-selects the readiness gate immediately -- the identical
    0.7273 index and the identical open item now fail with the other error id --
    while the screening's urgency variant, anchor and score are exactly what they
    were at screen time, with the 25 detention points not clawed back.
    Re-attaching the facility flips the gate straight back, so the gate is a pure
    function of the current flag.

    Design: Corner/cross_cutting_complexity_layers/dual_variant_urgency_is_frozen_at_screen_time_while_the_readiness_gate_variant_re_selects_on_every_read
    """
    env = _detained_matter_short_of_both_gates(api)

    released = ok(
        api.set_facility(
            env["matter_id"], {"detained": False}, headers=env.supervisor
        )
    )
    assert_fields(
        released,
        detained=False,
        facility_id=None,
        expedited_deadline_date=None,
        effective_filing_deadline_date="2026-09-30",
        readiness_gate_applied="CHECKLIST_STRICT_GATE",
    )
    assert_decimal_equals(released["readiness_index_weighted"], _EXPECTED_INDEX, 4)

    frozen = env.intake(env["intake_id"])
    assert_decimal_equals(frozen["urgency_score"], "74.29", 2)
    assert_fields(
        frozen,
        urgency_variant_applied="CALENDAR_INCLUSIVE",
        urgency_anchor_date="2026-09-30",
    )

    strict_refusal = api.advance_filing(
        env["matter_id"],
        {"target_filing_status": "READY_TO_FILE"},
        headers=env.lead_rep,
    )
    assert_error(strict_refusal, ERR_BLOCKING_EVIDENCE_OUTSTANDING)

    redetained = ok(
        api.set_facility(
            env["matter_id"],
            {"detained": True, "facility_id": env["fac_id"]},
            headers=env.supervisor,
        )
    )
    assert_fields(
        redetained,
        detained=True,
        expedited_deadline_date="2026-08-24",
        effective_filing_deadline_date="2026-08-24",
        readiness_gate_applied="EVIDENCE_WEIGHTED_GATE",
    )
    assert_decimal_equals(redetained["readiness_index_weighted"], _EXPECTED_INDEX, 4)

    weighted_refusal = api.advance_filing(
        env["matter_id"],
        {"target_filing_status": "READY_TO_FILE"},
        headers=env.lead_rep,
    )
    assert_error(weighted_refusal, ERR_MATTER_NOT_READY)


# ---------------------------------------------------------------------------
# cascading_side_effects_recognition_lapse_is_verified_hop_by_hop_and_is
# _ordering_sensitive
# ---------------------------------------------------------------------------

_CASCADE_CLOCK_UTC = "2026-08-03T09:00:00.000Z"


def _recognition_lapse_world(api):
    """One recognition carrying two accredited representatives and one led matter.

    The matter's only LEAD is the accredited representative Nadia Rey, supervised
    by the staff attorney Ben Cole, so the lapse can reach the matter at all. Every
    row that must NOT move is present too: Omar Vale's accreditation is REVOKED
    before the lapse and his assignment RELEASED, Ada Ortiz holds an ACTIVE
    CO_COUNSEL as a staff attorney, one declaration is already CERTIFIED, one
    event sits inside the 14-day window and one well outside it, and a second
    matter is already WITHDRAWN_FROM.
    """
    director = program_director_headers()
    env = minimal_world(
        api,
        clock=_CASCADE_CLOCK_UTC,
        cycle_label="FY26-H2",
        total_case_slots=10,
        reserved_detained_slots=2,
        languages=["en", "es"],
    )
    ada = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Ada Ortiz"), headers=director
        )
    )
    ben = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Ben Cole"), headers=director
        )
    )
    recognition = created(
        api.create_recognition(factories.recognition_payload(), headers=director)
    )
    nadia = recognition_with_accredited_rep(
        env, full_name="Nadia Rey", recognition_id=recognition["id"]
    )
    omar = recognition_with_accredited_rep(
        env, full_name="Omar Vale", recognition_id=recognition["id"]
    )
    ok(
        api.transition_accreditation(
            omar["accreditation_id"],
            {"action": "REVOKE", "decision_reason_code": "VOLUNTARY_SURRENDER"},
            headers=env.supervisor,
        )
    )

    client_id = new_client(env)
    matter = accept_intake(env, client_id, case_type="U_VISA")
    env.set(client_id=client_id, matter_id=matter["id"])

    ben_sup_id = add_supervisor_assignment(env, ben["id"])
    nadia_lead = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                nadia["representative_id"],
                env.matter_version(),
                role_on_case="LEAD",
            ),
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_assignment(
            nadia_lead["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )
    ada_cc = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"], ada["id"], env.matter_version(), role_on_case="CO_COUNSEL"
            ),
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_assignment(
            ada_cc["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )
    omar_cc = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                omar["representative_id"],
                env.matter_version(),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_assignment(
            omar_cc["id"],
            {"action": "RELEASE", "release_reason_code": "CASELOAD_REBALANCE"},
            headers=env.supervisor,
        )
    )

    ada_headers = env.rep_headers(ada["id"])
    decl_done = created(
        api.create_declaration(
            factories.declaration_payload(matter["id"], ada_cc["id"], language_code="es"),
            headers=ada_headers,
        )
    )
    session = created(
        api.create_session(
            factories.session_payload(matter["id"], language_code="es"),
            headers=director,
        )
    )
    ok(
        api.transition_session(
            session["id"], {"action": "COMPLETE", "actual_minutes": 45},
            headers=director,
        )
    )
    ok(
        api.transition_declaration(
            decl_done["id"], {"action": "SUBMIT_FOR_REVIEW"}, headers=ada_headers
        )
    )
    certified = ok(
        api.transition_declaration(
            decl_done["id"],
            {"action": "CERTIFY", "reviewer_assignment_id": ben_sup_id},
            headers=env.attorney_headers(ben["id"]),
        )
    )
    decl_open = created(
        api.create_declaration(
            factories.declaration_payload(matter["id"], ada_cc["id"], language_code="es"),
            headers=ada_headers,
        )
    )
    ok(
        api.transition_declaration(
            decl_open["id"], {"action": "SUBMIT_FOR_REVIEW"}, headers=ada_headers
        )
    )

    events = {}
    for key, day in (("evt_near_id", "2026-08-08"), ("evt_far_id", "2026-09-02")):
        row = created(
            api.create_event(
                factories.event_payload(
                    matter["id"],
                    event_type="BIOMETRICS",
                    starts_at_utc="{0}T14:00:00.000Z".format(day),
                    ends_at_utc="{0}T15:00:00.000Z".format(day),
                    assigned_representative_id=ada["id"],
                ),
                headers=director,
            )
        )
        events[key] = row["id"]

    bea_id = new_client(
        env,
        full_name="Bea Rios",
        date_of_birth="1988-02-19",
        household_size=1,
        annual_household_income_cents=1000000,
    )
    m2 = accept_intake(env, bea_id, case_type="U_VISA")
    ok(api.withdraw_intake(m2["intake_id_used"], headers=director))

    env.set(
        rec_id=recognition["id"],
        ada_id=ada["id"],
        ben_id=ben["id"],
        nadia_id=nadia["representative_id"],
        omar_id=omar["representative_id"],
        nadia_acc_id=nadia["accreditation_id"],
        omar_acc_id=omar["accreditation_id"],
        ben_sup_id=ben_sup_id,
        nadia_lead_id=nadia_lead["id"],
        ada_cc_id=ada_cc["id"],
        omar_cc_id=omar_cc["id"],
        decl_done_id=decl_done["id"],
        decl_open_id=decl_open["id"],
        certified_at=certified["certified_at_utc"],
        m2_id=m2["id"],
        **events
    )
    return env


def test_the_lapse_suspends_only_the_live_accreditation_and_re_derives_after_it(api):
    """Hops 0 to 2 read state the previous hop wrote, and skip the dead rows.

    The suspension count of 1 proves the REVOKED accreditation was never counted,
    and Nadia's AUTHORIZATION_SUSPENDED is only derivable after her accreditation
    was actually moved -- an implementation that re-derived first would still read
    AUTHORIZED_ACCREDITED. The staff attorneys' authority comes from the bar, so
    neither their status nor their assignments move at all.

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_recognition_lapse_is_verified_hop_by_hop_and_is_ordering_sensitive
    """
    env = _recognition_lapse_world(api)

    lapsed = ok(
        api.transition_recognition(
            env["rec_id"], {"action": "LAPSE"}, headers=env.director
        )
    )
    assert_fields(
        lapsed,
        status="LAPSED",
        lapsed_at_utc=_CASCADE_CLOCK_UTC,
        suspended_accreditation_count=1,
    )

    assert_fields(
        env.accreditation(env["nadia_acc_id"]),
        status="SUSPENDED_BY_RECOGNITION",
        decision_reason_code="RECOGNITION_LAPSE",
    )
    assert_fields(env.accreditation(env["omar_acc_id"]), status="REVOKED")

    assert_fields(
        env.representative(env["nadia_id"]),
        authorization_status="AUTHORIZATION_SUSPENDED",
        active_case_load=0,
    )
    assert_fields(
        env.representative(env["ada_id"]), authorization_status="AUTHORIZED_ATTORNEY"
    )
    assert_fields(
        env.representative(env["ben_id"]), authorization_status="AUTHORIZED_ATTORNEY"
    )

    assert_fields(
        env.assignment(env["nadia_lead_id"]),
        status="SUSPENDED",
        release_reason_code="RECOGNITION_LAPSE",
    )
    assert_fields(env.assignment(env["omar_cc_id"]), status="RELEASED")
    assert_fields(env.assignment(env["ada_cc_id"]), status="ACTIVE")
    assert_fields(env.assignment(env["ben_sup_id"]), status="ACTIVE")


def test_the_far_hops_reach_declarations_and_events_but_spare_the_settled_rows(api):
    """Hops 3 and 4 land in the same response, and each is conditional.

    The matter lost its only ACTIVE LEAD so it falls into COVERAGE_GAP, which is
    what drags the IN_REVIEW declaration back for revision and flags the event
    inside the 14-day lookahead. The already-withdrawn matter, the CERTIFIED
    declaration and the event thirty days out are all left exactly as they were.

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_recognition_lapse_is_verified_hop_by_hop_and_is_ordering_sensitive
    """
    env = _recognition_lapse_world(api)

    ok(
        api.transition_recognition(
            env["rec_id"], {"action": "LAPSE"}, headers=env.director
        )
    )

    assert_fields(
        env.matter(), representation_status="COVERAGE_GAP", coverage_gap_flag=True
    )
    assert_fields(
        env.matter(env["m2_id"]), representation_status="WITHDRAWN_FROM"
    )

    assert_fields(
        env.declaration(env["decl_open_id"]),
        status="REVISION_REQUESTED",
        revision_reason_code="SUPERVISION_REQUIRED",
        revision_round=1,
    )
    assert_fields(
        env.declaration(env["decl_done_id"]),
        status="CERTIFIED",
        certified_at_utc=env["certified_at"],
    )

    assert_fields(
        env.event(env["evt_near_id"]), status="SCHEDULED", coverage_gap_flag=True
    )
    assert_fields(
        env.event(env["evt_far_id"]), status="SCHEDULED", coverage_gap_flag=False
    )
