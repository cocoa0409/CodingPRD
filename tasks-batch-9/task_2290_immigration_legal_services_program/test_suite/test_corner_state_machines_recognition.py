"""Breadth tests for the recognition, accreditation and grant-report machines.

The recognition lapse is the one transition that reaches four hops away, and its
reinstatement is deliberately incomplete. The accreditation term walks the
approved-expiring-renewal-approved cycle under the checkpoint sweep, and the
grant report closes its own generated-submitted-amended-generated loop with
byte-identical money on the second pass.
"""

from test_helpers import factories
from test_helpers.api_errors import ERR_REPORT_STATE_INVALID
from test_helpers.assertions import (
    assert_cents,
    assert_error,
    assert_fields,
    assert_null_fields,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import (
    accept_intake,
    add_supervisor_assignment,
    minimal_world,
    new_client,
    recognition_with_accredited_rep,
    set_clock,
)
from test_helpers.test_users import program_director_headers

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"


def _cycle_world(api, **overrides):
    """The FY26-H2 cycle at 2026-08-03T09:00Z, in Spanish and English."""
    settings = {
        "clock": _CLOCK_UTC,
        "cycle_label": "FY26-H2",
        "period_start_date": "2026-07-01",
        "period_end_date": "2026-12-31",
        "total_case_slots": 10,
        "reserved_detained_slots": 2,
        "languages": ["en", "es"],
    }
    settings.update(overrides)
    return minimal_world(api, **settings)


def _lapse_world(api):
    """One recognition, one accredited lead under a staff-attorney supervisor.

    Nina Rios is the matter's only ACTIVE LEAD and her authority is the PARTIAL
    accreditation, so the lapse reaches her assignment, the matter, the IN_REVIEW
    declaration and the near event. Ada Ortiz supervises as a STAFF_ATTORNEY, so
    her own authority comes from the bar and nothing of hers may move.
    """
    director = program_director_headers()
    env = _cycle_world(api)
    ada = created(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Ada Ortiz"), headers=director
        )
    )
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                effective_date="2026-01-01", expiry_date="2028-12-31"
            ),
            headers=director,
        )
    )
    nina = recognition_with_accredited_rep(
        env,
        full_name="Nina Rios",
        accreditation_type="PARTIAL",
        requested_forums=["USCIS", "ASYLUM_OFFICE"],
        recognition_id=recognition["id"],
    )

    client_id = new_client(env)
    matter = accept_intake(env, client_id, case_type="U_VISA")
    env.set(client_id=client_id, matter_id=matter["id"])

    sup_id = add_supervisor_assignment(env, ada["id"])
    lead = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                nina["representative_id"],
                env.matter_version(),
                role_on_case="LEAD",
            ),
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_assignment(
            lead["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )

    nina_headers = env.rep_headers(nina["representative_id"])
    declaration = created(
        api.create_declaration(
            factories.declaration_payload(matter["id"], lead["id"], language_code="es"),
            headers=nina_headers,
        )
    )
    ok(
        api.transition_declaration(
            declaration["id"], {"action": "SUBMIT_FOR_REVIEW"}, headers=nina_headers
        )
    )

    near = created(
        api.create_event(
            factories.event_payload(
                matter["id"],
                event_type="BIOMETRICS",
                starts_at_utc="2026-08-10T14:00:00.000Z",
                ends_at_utc="2026-08-10T15:00:00.000Z",
                location_code="ASCQUEENS",
                assigned_representative_id=nina["representative_id"],
            ),
            headers=env.supervisor,
        )
    )
    far = created(
        api.create_event(
            factories.event_payload(
                matter["id"],
                event_type="MASTER_CALENDAR_HEARING",
                starts_at_utc="2026-09-15T09:00:00.000Z",
                ends_at_utc="2026-09-15T10:00:00.000Z",
                location_code="EOIRCRT3",
                assigned_representative_id=ada["id"],
            ),
            headers=env.supervisor,
        )
    )

    env.set(
        rec_id=recognition["id"],
        ada_id=ada["id"],
        acc_rep_id=nina["representative_id"],
        accr_id=nina["accreditation_id"],
        sup_id=sup_id,
        lead_id=lead["id"],
        decl_id=declaration["id"],
        near_ev_id=near["id"],
        far_ev_id=far["id"],
    )
    return env


def test_one_lapse_call_walks_all_four_hops_and_stops_at_the_fourteenth_day(api):
    """Each hop reads what the hop before it wrote, and the last one is windowed.

    Hop 1 suspends the accreditation, which is the only reason hop 2 can derive
    AUTHORIZATION_SUSPENDED and suspend the lead; that suspension is the only
    reason hop 3 can see a matter with no ACTIVE LEAD; and only then does hop 4
    drag the IN_REVIEW declaration back and flag the event seven days out while
    leaving the one forty-three days out alone. The supervising attorney's own
    authority is his bar number, so his assignment is untouched and the filing
    dimension does not move at all.

    Design: Corner/state_machines/recognition_lapse_runs_all_four_cascade_hops_end_to_end
    """
    env = _lapse_world(api)

    lapsed = ok(
        api.transition_recognition(
            env["rec_id"], {"action": "LAPSE"}, headers=env.director
        )
    )
    assert_fields(
        lapsed,
        status="LAPSED",
        lapsed_at_utc=_CLOCK_UTC,
        suspended_accreditation_count=1,
    )
    assert_null_fields(lapsed, "conditional_reason_code")

    assert_fields(
        env.accreditation(env["accr_id"]),
        status="SUSPENDED_BY_RECOGNITION",
        decision_reason_code="RECOGNITION_LAPSE",
    )

    assert_fields(
        env.representative(env["acc_rep_id"]),
        authorization_status="AUTHORIZATION_SUSPENDED",
        active_case_load=0,
    )
    assert_fields(
        env.assignment(env["lead_id"]),
        status="SUSPENDED",
        release_reason_code="RECOGNITION_LAPSE",
    )
    assert_fields(
        env.representative(env["ada_id"]),
        authorization_status="AUTHORIZED_ATTORNEY",
        supervisee_count=0,
    )
    assert_fields(env.assignment(env["sup_id"]), status="ACTIVE")

    assert_fields(
        env.matter(),
        representation_status="COVERAGE_GAP",
        coverage_gap_flag=True,
        filing_status="PRE_FILING",
    )

    assert_fields(
        env.declaration(env["decl_id"]),
        status="REVISION_REQUESTED",
        revision_reason_code="SUPERVISION_REQUIRED",
        revision_round=1,
    )
    assert_fields(env.event(env["near_ev_id"]), coverage_gap_flag=True)
    assert_fields(env.event(env["far_ev_id"]), coverage_gap_flag=False)

    flagged = only_row(
        api.list_events(
            params={"matter_id": env["matter_id"], "coverage_gap_flag": True},
            headers=env.director,
        )
    )
    assert flagged["id"] == env["near_ev_id"]


def test_reinstatement_puts_the_staffing_back_but_never_unsays_the_revision(api):
    """The compensation is partial by design, and the gap is the point.

    The accreditation, the suspended assignment, the authorization, both counters
    and the matter's representation dimension all come back, because the clock is
    still inside both the recognition term and the accreditation term. The
    declaration stays in REVISION_REQUESTED with its round still at 1 and the
    event keeps its coverage flag: an implementation that reverses hop 4 fails
    here.

    Design: Corner/state_machines/recognition_reinstate_compensates_the_cascade_but_never_restores_the_declaration
    """
    env = _lapse_world(api)
    ok(
        api.transition_recognition(
            env["rec_id"], {"action": "LAPSE"}, headers=env.director
        )
    )

    reinstated = ok(
        api.transition_recognition(
            env["rec_id"], {"action": "REINSTATE"}, headers=env.director
        )
    )
    assert_fields(reinstated, status="ACTIVE", suspended_accreditation_count=0)
    assert_null_fields(reinstated, "lapsed_at_utc")

    assert_fields(
        env.accreditation(env["accr_id"]),
        status="APPROVED",
        expiry_date="2029-08-02",
        renewal_round=0,
    )
    assert_fields(
        env.representative(env["acc_rep_id"]),
        authorization_status="AUTHORIZED_ACCREDITED",
        active_case_load=1,
    )
    assert_fields(env.assignment(env["lead_id"]), status="ACTIVE")
    assert_null_fields(env.assignment(env["lead_id"]), "release_reason_code")
    assert_fields(env.representative(env["ada_id"]), supervisee_count=1)
    assert_fields(env.matter(), representation_status="SUPERVISED_STAFFED")

    # hop 4 is never compensated
    assert_fields(
        env.declaration(env["decl_id"]),
        status="REVISION_REQUESTED",
        revision_reason_code="SUPERVISION_REQUIRED",
        revision_round=1,
    )
    assert_fields(env.event(env["near_ev_id"]), coverage_gap_flag=True)


def test_the_term_ages_into_expiring_then_a_renewal_re_bases_it_from_today(api):
    """The 90-day window opens on an exact date, and the renewal re-clips the forums.

    A sweep one day before the window leaves the row APPROVED; the sweep on the
    ninetieth day before expiry moves it to EXPIRING, which still authorizes. The
    renewal then opens a round against the recognition's current forums, and the
    approval that closes it re-bases effective and expiry from the *current*
    clock -- 2029-05-04 plus 1095 days -- while the PARTIAL ceiling still throws
    the requested court forum away.

    Design: Corner/state_machines/accreditation_walks_approved_expiring_renewal_pending_approved_cycle
    """
    director = program_director_headers()
    env = _cycle_world(api)
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                effective_date="2026-01-01", expiry_date="2033-12-31"
            ),
            headers=director,
        )
    )
    nina = recognition_with_accredited_rep(
        env,
        full_name="Nina Rios",
        accreditation_type="PARTIAL",
        requested_forums=["USCIS"],
        recognition_id=recognition["id"],
    )
    accr_id = nina["accreditation_id"]
    assert_fields(
        env.accreditation(accr_id),
        status="APPROVED",
        effective_date="2026-08-03",
        expiry_date="2029-08-02",
        authorized_forums=["USCIS"],
        renewal_round=0,
    )

    set_clock(api, "2029-05-03T08:00:00.000Z")
    ok(api.checkpoint_cycle(env["cycle_id"], headers=director))
    assert_fields(env.accreditation(accr_id), status="APPROVED")

    set_clock(api, "2029-05-04T08:00:00.000Z")
    ok(api.checkpoint_cycle(env["cycle_id"], headers=director))
    assert_fields(env.accreditation(accr_id), status="EXPIRING")
    assert_fields(
        env.representative(nina["representative_id"]),
        authorization_status="AUTHORIZED_ACCREDITED",
    )

    rec_version = env.recognition(recognition["id"])["version"]
    renewed = ok(
        api.renew_accreditation(
            accr_id,
            {
                "expected_recognition_version": rec_version,
                "requested_forums": ["USCIS", "EOIR_IMMIGRATION_COURT"],
            },
            headers=env.supervisor,
        )
    )
    assert_fields(renewed, status="RENEWAL_PENDING")
    assert env.recognition(recognition["id"])["version"] == rec_version + 1

    approved = ok(
        api.transition_accreditation(
            accr_id,
            {"action": "APPROVE", "decision_reason_code": "CREDENTIALS_VERIFIED"},
            headers=env.supervisor,
        )
    )
    assert_fields(
        approved,
        status="APPROVED",
        renewal_round=1,
        effective_date="2029-05-04",
        expiry_date="2032-05-03",
        authorized_forums=["USCIS"],
        approved_by_representative_id=env["atty_b_id"],
    )


def _money_fields(report):
    """The five money figures a generation must agree on with itself."""
    return {
        field: report[field]
        for field in (
            "base_reimbursable_cents",
            "supervision_surcharge_cents",
            "total_reimbursable_cents",
            "allocated_line_total_cents",
            "rounding_remainder_cents",
        )
    }


def test_a_draft_report_cannot_be_submitted_and_an_empty_generate_reports_zeroes(api):
    """SUBMIT has no edge from DRAFT, and an empty line set is not an error.

    The zero money fields of a fresh DRAFT already satisfy the submission
    equality, so the refusal can only come from the state machine itself, and the
    refused calls leave both the status and the amendment counter where they
    were. Generation over a cycle with no screenings at all then divides no hours
    by no hours: it returns zeroes.

    Design: Corner/state_machines/grant_report_submit_from_draft_is_invalid_and_empty_generate_zeroes_without_raising
    """
    env = _cycle_world(api)
    report = created(
        api.create_grant_report(
            factories.grant_report_payload(
                env["cycle_id"],
                disclosure_level="AGGREGATE_ONLY",
                period_start_date="2026-07-01",
                period_end_date="2026-12-31",
            ),
            headers=env.analyst,
        )
    )
    report_id = report["id"]

    def act(action, **extra):
        payload = {"action": action}
        payload.update(extra)
        return api.transition_grant_report(report_id, payload, headers=env.analyst)

    assert_error(act("SUBMIT"), ERR_REPORT_STATE_INVALID)
    still_draft = ok(api.get_grant_report(report_id, headers=env.analyst))
    assert_fields(still_draft, status="DRAFT")
    assert_null_fields(still_draft, "submitted_at_utc")

    assert_error(act("AMEND", amendment_reason_code="FUNDER_QUERY"), ERR_REPORT_STATE_INVALID)
    assert_fields(
        ok(api.get_grant_report(report_id, headers=env.analyst)),
        status="DRAFT",
        amendment_round=0,
    )

    generated = ok(act("GENERATE"))
    assert_fields(
        generated,
        status="GENERATED",
        cases_served_count=0,
        consent_verified_count=0,
        suppressed_case_count=0,
    )
    for field, value in _money_fields(generated).items():
        assert value == 0, "{0}: expected 0 on an empty line set, got {1!r}".format(
            field, value
        )


def test_the_amend_regenerate_loop_reproduces_the_money_exactly(api):
    """The second pass over an unchanged line set must be byte-identical.

    Ten direct hours at 12,500 cents put the base at 125,000, which sits below the
    first surcharge threshold, so the rate is 0.00 and the single line takes the
    whole total with no leftover cent. AMEND then reopens the row -- counter up,
    submission stamp gone -- and the regeneration reproduces every money figure,
    because the largest-remainder pass is deterministic.

    Design: Corner/state_machines/grant_report_amend_regenerate_cycle_reproduces_identical_money_fields
    """
    env = _cycle_world(api)
    client_id = new_client(env)
    matter = accept_intake(env, client_id, case_type="U_VISA")
    env.set(client_id=client_id, matter_id=matter["id"])

    lead = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"], env["atty_a_id"], env.matter_version(), role_on_case="LEAD"
            ),
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_assignment(
            lead["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )
    ok(
        api.log_hours(
            lead["id"],
            {"hours": 10.00, "hours_kind": "DIRECT", "service_date": "2026-08-03"},
            headers=env.supervisor,
        )
    )

    report = created(
        api.create_grant_report(
            factories.grant_report_payload(
                env["cycle_id"],
                disclosure_level="AGGREGATE_ONLY",
                period_start_date="2026-07-01",
                period_end_date="2026-12-31",
            ),
            headers=env.analyst,
        )
    )
    report_id = report["id"]

    def act(action, **extra):
        payload = {"action": action}
        payload.update(extra)
        return ok(api.transition_grant_report(report_id, payload, headers=env.analyst))

    first = act("GENERATE")
    assert_fields(
        first,
        status="GENERATED",
        cases_served_count=1,
        consent_verified_count=1,
        suppressed_case_count=0,
    )
    assert first["outcomes_summary"]["NOT_YET_DECIDED"] == 1, first["outcomes_summary"]
    assert first["outcomes_summary"].get("GRANTED", 0) == 0, first["outcomes_summary"]
    assert_cents(first, "base_reimbursable_cents", 125000)
    assert_cents(first, "supervision_surcharge_cents", 0)
    assert_cents(first, "total_reimbursable_cents", 125000)
    assert_cents(first, "allocated_line_total_cents", 125000)
    assert_cents(first, "rounding_remainder_cents", 0)

    submitted = act("SUBMIT")
    assert_fields(submitted, status="SUBMITTED", submitted_at_utc=_CLOCK_UTC)

    amended = act("AMEND", amendment_reason_code="FUNDER_QUERY")
    assert_fields(amended, status="AMENDED", amendment_round=1)
    assert_null_fields(amended, "submitted_at_utc")

    second = act("GENERATE")
    assert_fields(
        second, status="GENERATED", amendment_round=1, cases_served_count=1
    )
    assert _money_fields(second) == _money_fields(first), (
        "regeneration over an unchanged line set drifted: {0} vs {1}".format(
            _money_fields(first), _money_fields(second)
        )
    )
