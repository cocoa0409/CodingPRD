"""Breadth tests for the error catalogue and the order it is consulted in.

Each test here pins one error id against the id an implementation is most likely
to return instead: a body-borne foreign key against the generic 404, a state gate
against the link gate that would have fired next, one member of a two-directional
conditional against the other, and a report-scoped OCC token against the
matter-scoped one.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_ASSIGNMENT_MATTER_MISMATCH,
    ERR_CONSENT_SCOPE_INSUFFICIENT,
    ERR_COUNSELING_LANGUAGE_UNVERIFIED,
    ERR_DECLARATION_NOT_CERTIFIED,
    ERR_DERIVATIVE_CLIENT_MISMATCH,
    ERR_INTAKE_NOT_ACCEPTED,
    ERR_INTERPRETER_LANGUAGE_MISMATCH,
    ERR_INTERPRETER_SOURCE_MISMATCH,
    ERR_LEAD_ALREADY_ASSIGNED,
    ERR_NO_ELIGIBLE_SUPERVISOR,
    ERR_RECOGNITION_NOT_FOUND,
    ERR_REPORT_PERIOD_INVALID,
    ERR_REPORT_STATE_INVALID,
    ERR_REPRESENTATIVE_NOT_FOUND,
    ERR_STALE_RECOGNITION_VERSION,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_no_rows,
    assert_null_fields,
    assert_row_count,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import (
    accept_intake,
    add_supervisor_assignment,
    minimal_world,
    new_client,
    set_clock,
    template_a,
)

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"
_MISSING_RECOGNITION_ID = "00000000-0000-4000-8000-0000000000aa"
_MISSING_REPRESENTATIVE_ID = "00000000-0000-4000-8000-0000000000bb"


# ---------------------------------------------------------------------------
# err_recognition_not_found_and_err_representative_not_found_from_path_and_body_ids
# ---------------------------------------------------------------------------


def test_a_dangling_key_in_the_body_reports_the_same_id_as_a_dangling_path(api):
    """Four body fields and two path segments, one entity-specific id each.

    The body route is the one an implementation forgets: a dangling
    ``representative_id``, ``interpreter_representative_id`` or
    ``assigned_representative_id`` must not degrade into the generic 404 or into a
    validation complaint. And when both foreign keys of one accreditation payload
    dangle, the representative wins, because it precedes the recognition in the
    existence order.

    Design: Corner/errors/err_recognition_not_found_and_err_representative_not_found_from_path_and_body_ids
    """
    env = template_a(api, clock=_CLOCK_UTC)
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(expiry_date="2030-01-01"), headers=env.director
        )
    )
    accredited = created(
        api.create_representative(
            factories.accredited_rep_payload(
                full_name="Nadia Rey", languages=["en", "es"], max_case_load=15
            ),
            headers=env.director,
        )
    )

    assert_error(
        api.get_recognition(_MISSING_RECOGNITION_ID, headers=env.director),
        ERR_RECOGNITION_NOT_FOUND,
    )
    assert_error(
        api.get_representative(_MISSING_REPRESENTATIVE_ID, headers=env.director),
        ERR_REPRESENTATIVE_NOT_FOUND,
    )

    assert_error(
        api.create_accreditation(
            factories.accreditation_payload(
                accredited["id"],
                _MISSING_RECOGNITION_ID,
                accreditation_type="PARTIAL",
                requested_forums=["USCIS"],
            ),
            headers=env.director,
        ),
        ERR_RECOGNITION_NOT_FOUND,
    )
    assert_error(
        api.create_accreditation(
            factories.accreditation_payload(
                _MISSING_REPRESENTATIVE_ID,
                _MISSING_RECOGNITION_ID,
                accreditation_type="PARTIAL",
                requested_forums=["USCIS"],
            ),
            headers=env.director,
        ),
        ERR_REPRESENTATIVE_NOT_FOUND,
    )

    # A STAFF source needs an interpreter, so the existence check is reached before
    # the source-shape check that would otherwise have complained.
    assert_error(
        api.create_session(
            factories.session_payload(
                env["matter_id"],
                language_code="es",
                purpose="INTAKE",
                interpreter_source="STAFF",
                interpreter_representative_id=_MISSING_REPRESENTATIVE_ID,
                scheduled_start_utc="2026-08-05T14:00:00.000Z",
                scheduled_end_utc="2026-08-05T15:00:00.000Z",
            ),
            headers=env.lead_rep,
        ),
        ERR_REPRESENTATIVE_NOT_FOUND,
    )
    assert_error(
        api.create_event(
            factories.event_payload(
                env["matter_id"],
                event_type="BIOMETRICS",
                starts_at_utc="2026-08-20T14:00:00.000Z",
                ends_at_utc="2026-08-20T15:00:00.000Z",
                location_code="ELPASC",
                assigned_representative_id=_MISSING_REPRESENTATIVE_ID,
            ),
            headers=env.lead_rep,
        ),
        ERR_REPRESENTATIVE_NOT_FOUND,
    )

    assert_no_rows(api.list_accreditations(headers=env.director))
    assert_no_rows(
        api.list_sessions(params={"matter_id": env["matter_id"]}, headers=env.director)
    )
    assert_no_rows(
        api.list_events(params={"matter_id": env["matter_id"]}, headers=env.director)
    )
    assert recognition["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# err_intake_not_accepted_outranks_err_derivative_client_mismatch_on_the_accept_branch
# ---------------------------------------------------------------------------


def _screen_only(env, client_id, case_type, **fields):
    """Open and screen an intake, stopping before any decision."""
    payload = factories.intake_payload(
        client_id, env["cycle_id"], case_type=case_type, detained=False
    )
    payload.update(fields)
    intake = created(env.api.create_intake(payload, headers=env.screener))
    ok(env.api.screen_intake(intake["id"], headers=env.screener))
    return intake["id"]


def _derivative_world(api):
    """Rosa's accepted matter plus three further screenings, one of them declined."""
    env = template_a(api, clock=_CLOCK_UTC)
    bea_id = new_client(
        env,
        full_name="Bea Rios",
        date_of_birth="1988-02-19",
        preferred_language_code="es",
        country_of_birth_code="GT",
        household_size=1,
        annual_household_income_cents=1000000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    declined_id = _screen_only(
        env, bea_id, "U_VISA", statutory_deadline_date="2026-12-01"
    )
    ok(
        api.decide_intake(
            declined_id,
            {"decision": "DECLINE", "decision_reason_code": "OUTSIDE_SERVICE_AREA"},
            headers=env.supervisor,
        )
    )
    env.set(
        bea_id=bea_id,
        declined_intake_id=declined_id,
        bea_screened_id=_screen_only(
            env, bea_id, "ADJUSTMENT_OF_STATUS", statutory_deadline_date="2026-12-01"
        ),
        rosa_screened_id=_screen_only(
            env, env["client_id"], "ASYLUM_AFFIRMATIVE", statutory_deadline_date="2026-12-01"
        ),
    )
    return env


def test_the_acceptance_state_gate_pre_empts_the_derivative_link_gate(api):
    """The identical payload reports two different ids from two different origins.

    A declined screening carrying a cross-client principal link reports the state
    gate, because state is evaluated before the business check that would have
    caught the link; the same link against a merely screened row then reveals the
    mismatch. Neither refusal consumes a slot, which is what proves the accept
    branch aborted before its only slot-consuming step.

    Design: Corner/errors/err_intake_not_accepted_outranks_err_derivative_client_mismatch_on_the_accept_branch
    """
    env = _derivative_world(api)
    principal_id = env["matter_id"]
    consumed_before = env.cycle()["general_slots_consumed"]

    assert_error(
        api.decide_intake(
            env["declined_intake_id"],
            {
                "decision": "ACCEPT",
                "decision_reason_code": "ACCEPTED_ON_MERIT",
                "principal_matter_id": principal_id,
            },
            headers=env.supervisor,
        ),
        ERR_INTAKE_NOT_ACCEPTED,
    )
    assert_fields(env.intake(env["declined_intake_id"]), status="DECLINED")
    assert_no_rows(
        api.list_matters(
            params={"intake_id": env["declined_intake_id"]}, headers=env.director
        )
    )

    assert_error(
        api.decide_intake(
            env["bea_screened_id"],
            {
                "decision": "ACCEPT",
                "decision_reason_code": "ACCEPTED_ON_MERIT",
                "principal_matter_id": principal_id,
            },
            headers=env.supervisor,
        ),
        ERR_DERIVATIVE_CLIENT_MISMATCH,
    )
    assert_fields(env.intake(env["bea_screened_id"]), status="SCREENED")
    assert_fields(env.cycle(), general_slots_consumed=consumed_before)


def test_a_same_client_derivative_link_is_stored_and_read_back_by_its_own_filter(api):
    """Rosa may hold a derivative of her own principal matter.

    The link is write-only from the caller's point of view -- the decide response
    is the screening, never the minted matter -- so the self-referential
    ``principal_matter_id`` filter on the matter list is the only channel through
    which the stored link can be observed.

    Design: Corner/errors/err_intake_not_accepted_outranks_err_derivative_client_mismatch_on_the_accept_branch
    """
    env = _derivative_world(api)
    principal_id = env["matter_id"]

    decided = ok(
        api.decide_intake(
            env["rosa_screened_id"],
            {
                "decision": "ACCEPT",
                "decision_reason_code": "ACCEPTED_ON_MERIT",
                "principal_matter_id": principal_id,
            },
            headers=env.supervisor,
        )
    )
    assert_fields(decided, status="ACCEPTED", decided_at_utc=_CLOCK_UTC)

    derivative = only_row(
        api.list_matters(
            params={"principal_matter_id": principal_id}, headers=env.director
        )
    )
    assert_fields(
        derivative,
        principal_matter_id=principal_id,
        client_id=env["client_id"],
        intake_id=env["rosa_screened_id"],
        forum="ASYLUM_OFFICE",
        representation_status="UNSTAFFED",
        filing_status="PRE_FILING",
    )
    assert_fields(env.matter(principal_id), principal_matter_id=None)


# ---------------------------------------------------------------------------
# err_lead_already_assigned_counts_suspended_leads_and_err_assignment_matter_mismatch
# ---------------------------------------------------------------------------


def _two_matters_each_with_its_own_lead(api):
    """M1 led by Ada Ortiz and M2 led by Ben Cole, both ACTIVE."""
    env = template_a(api, clock=_CLOCK_UTC)
    bea_id = new_client(
        env,
        full_name="Bea Rios",
        date_of_birth="1988-02-19",
        preferred_language_code="es",
        country_of_birth_code="GT",
        household_size=3,
        annual_household_income_cents=2000000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    second = accept_intake(env, bea_id, case_type="U_VISA", detained=False)
    other_lead = created(
        api.create_assignment(
            factories.assignment_payload(
                second["id"], env["atty_b_id"], second["version"], role_on_case="LEAD"
            ),
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_assignment(
            other_lead["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )
    env.set(bea_id=bea_id, m2_id=second["id"], m2_lead_id=other_lead["id"])
    return env


def test_a_suspended_lead_still_occupies_the_only_lead_slot(api):
    """Suspending the incumbent leaves the matter leadless and still unreplaceable.

    The uniqueness set spans PROPOSED, ACTIVE and SUSPENDED, so the coverage-gap
    trap is real: an operator who suspends a lead in order to swap in a
    replacement finds the seat still occupied. The refused create also leaves the
    concurrency token untouched, which is why the same token is accepted again on
    the second attempt.

    Design: Corner/errors/err_lead_already_assigned_counts_suspended_leads_and_err_assignment_matter_mismatch
    """
    env = _two_matters_each_with_its_own_lead(api)
    token = env.matter_version()

    assert_error(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"], env["atty_b_id"], token, role_on_case="LEAD"
            ),
            headers=env.supervisor,
        ),
        ERR_LEAD_ALREADY_ASSIGNED,
    )
    assert_fields(env.matter(), version=token)

    suspended = ok(
        api.transition_assignment(
            env["lead_id"],
            # PRD 3.6: "Both require a release_reason_code when the actor is a
            # SupervisingAttorney", and the swap attempt is a rebalance.
            {"action": "SUSPEND", "release_reason_code": "CASELOAD_REBALANCE"},
            headers=env.supervisor,
        )
    )
    assert_fields(suspended, status="SUSPENDED")

    assert_error(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"],
                env["atty_b_id"],
                env.matter_version(),
                role_on_case="LEAD",
            ),
            headers=env.supervisor,
        ),
        ERR_LEAD_ALREADY_ASSIGNED,
    )
    assert_row_count(
        api.list_assignments(
            params={"matter_id": env["matter_id"]}, headers=env.director
        ),
        1,
    )


def test_an_active_assignment_of_the_wrong_matter_is_a_mismatch_not_a_miss(api):
    """The preparer assignment exists and is ACTIVE -- it simply belongs elsewhere.

    Neither a 404 nor the not-active id would be correct here, and getting this
    wrong is easy because both of those checks sit next to the mismatch check on
    the same field.

    Design: Corner/errors/err_lead_already_assigned_counts_suspended_leads_and_err_assignment_matter_mismatch
    """
    env = _two_matters_each_with_its_own_lead(api)
    assert_fields(env.assignment(env["m2_lead_id"]), status="ACTIVE", matter_id=env["m2_id"])

    assert_error(
        api.create_declaration(
            factories.declaration_payload(
                env["matter_id"], env["m2_lead_id"], language_code="es"
            ),
            headers=env.supervisor,
        ),
        ERR_ASSIGNMENT_MATTER_MISMATCH,
    )
    assert_no_rows(
        api.list_declarations(
            params={"matter_id": env["matter_id"]}, headers=env.director
        )
    )
    assert_no_rows(
        api.list_declarations(params={"matter_id": env["m2_id"]}, headers=env.director)
    )


# ---------------------------------------------------------------------------
# err_interpreter_source_mismatch_and_language_mismatch_are_two_distinct_rejections
# ---------------------------------------------------------------------------


def test_one_interpreter_field_is_refused_from_both_directions_then_for_its_languages(api):
    """STAFF without an interpreter and CONTRACT with one report the same id.

    The two-directional conditional is the trap: an implementation that only
    checks the required direction lets the CONTRACT booking through. Only once the
    shape is legal does the interpreter's own ``languages`` array come under
    examination, which is why naming a monolingual English interpreter reports the
    source id under CONTRACT but the language id under STAFF.

    Design: Corner/errors/err_interpreter_source_mismatch_and_language_mismatch_are_two_distinct_rejections
    """
    env = template_a(api, clock=_CLOCK_UTC)
    monolingual = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Dov Adler", bar_number="BAR-5005", languages=["en"]
            ),
            headers=env.director,
        )
    )

    def book(**fields):
        return api.create_session(
            factories.session_payload(
                env["matter_id"],
                language_code="es",
                purpose="INTAKE",
                scheduled_start_utc="2026-08-05T14:00:00.000Z",
                scheduled_end_utc="2026-08-05T15:00:00.000Z",
                **fields
            ),
            headers=env.lead_rep,
        )

    assert_error(book(interpreter_source="STAFF"), ERR_INTERPRETER_SOURCE_MISMATCH)
    assert_error(
        book(interpreter_source="CONTRACT", interpreter_representative_id=monolingual["id"]),
        ERR_INTERPRETER_SOURCE_MISMATCH,
    )
    assert_error(
        book(interpreter_source="STAFF", interpreter_representative_id=monolingual["id"]),
        ERR_INTERPRETER_LANGUAGE_MISMATCH,
    )
    assert_no_rows(
        api.list_sessions(params={"matter_id": env["matter_id"]}, headers=env.director)
    )


def test_a_zero_length_window_is_a_shape_failure_and_a_staff_session_bills_nothing(api):
    """An end instant equal to the start is not a session, and STAFF accrues no money.

    The interval bound is stated as strictly-after, so equality is a validation
    failure rather than a degenerate but legal booking; the successful STAFF
    booking that follows shows the money columns sitting at zero from birth rather
    than at null.

    Design: Corner/errors/err_interpreter_source_mismatch_and_language_mismatch_are_two_distinct_rejections
    """
    env = template_a(api, clock=_CLOCK_UTC)

    assert_error(
        api.create_session(
            factories.session_payload(
                env["matter_id"],
                language_code="es",
                purpose="INTAKE",
                interpreter_source="STAFF",
                interpreter_representative_id=env["atty_a_id"],
                scheduled_start_utc="2026-08-05T15:00:00.000Z",
                scheduled_end_utc="2026-08-05T15:00:00.000Z",
            ),
            headers=env.lead_rep,
        ),
        ERR_VALIDATION,
    )

    booked = created(
        api.create_session(
            factories.session_payload(
                env["matter_id"],
                language_code="es",
                purpose="INTAKE",
                interpreter_source="STAFF",
                interpreter_representative_id=env["atty_a_id"],
                scheduled_start_utc="2026-08-05T14:00:00.000Z",
                scheduled_end_utc="2026-08-05T15:00:00.000Z",
            ),
            headers=env.lead_rep,
        )
    )
    assert_fields(booked, status="SCHEDULED", billed_minutes=0, billable_cents=0)
    assert_null_fields(booked, "actual_minutes")
    assert_row_count(
        api.list_sessions(params={"matter_id": env["matter_id"]}, headers=env.director), 1
    )
    assert env.matter()["interpretation_cost_cents"] == 0


# ---------------------------------------------------------------------------
# err_declaration_not_certified_then_err_counseling_language_unverified_on_informed_decision
# ---------------------------------------------------------------------------


def _matter_with_an_in_review_declaration(api):
    """TEMPLATE B stopped one step short of CERTIFY, plus a completed 'pt' session."""
    env = template_a(api, clock=_CLOCK_UTC)
    matter_v = env.matter_version()
    cocounsel = created(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"], env["atty_b_id"], matter_v, role_on_case="CO_COUNSEL"
            ),
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_assignment(
            cocounsel["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )
    declaration = created(
        api.create_declaration(
            factories.declaration_payload(
                env["matter_id"], env["lead_id"], language_code="es"
            ),
            headers=env.lead_rep,
        )
    )
    readback = created(
        api.create_session(
            factories.session_payload(env["matter_id"], language_code="es"),
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_session(
            readback["id"],
            {"action": "COMPLETE", "actual_minutes": 45},
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_declaration(
            declaration["id"], {"action": "SUBMIT_FOR_REVIEW"}, headers=env.lead_rep
        )
    )
    portuguese = created(
        api.create_session(
            factories.session_payload(
                env["matter_id"],
                language_code="pt",
                purpose="RIGHTS_COUNSELING",
                interpreter_source="CONTRACT",
                scheduled_start_utc="2026-08-03T08:00:00.000Z",
                scheduled_end_utc="2026-08-03T08:45:00.000Z",
            ),
            headers=env.lead_rep,
        )
    )
    ok(
        api.transition_session(
            portuguese["id"],
            {"action": "COMPLETE", "actual_minutes": 45},
            headers=env.lead_rep,
        )
    )
    env.set(
        cocounsel_id=cocounsel["id"],
        decl_id=declaration["id"],
        sess_id=readback["id"],
        pt_sess_id=portuguese["id"],
    )
    return env


def test_a_declaration_in_review_counts_for_nothing_at_counseling_time(api):
    """The gate demands a CERTIFIED declaration, and IN_REVIEW is not close enough.

    The counseling language here matches the client's own, so nothing but the
    declaration gate can fire -- and the refusal must leave the matter's
    concurrency token exactly where it was, since the very same token is what the
    caller will retry with after certifying.

    Design: Corner/errors/err_declaration_not_certified_then_err_counseling_language_unverified_on_informed_decision
    """
    env = _matter_with_an_in_review_declaration(api)
    assert_fields(env.declaration(env["decl_id"]), status="IN_REVIEW", readback_completed=True)
    before = env.matter_version()

    assert_error(
        api.create_informed_decision(
            factories.informed_decision_payload(
                env["matter_id"],
                env["lead_id"],
                before,
                counseling_language_code="es",
            ),
            headers=env.lead_rep,
        ),
        ERR_DECLARATION_NOT_CERTIFIED,
    )
    assert_fields(env.matter(), version=before)
    assert_no_rows(
        api.list_informed_decisions(
            params={"matter_id": env["matter_id"]}, headers=env.director
        )
    )

    certified = ok(
        api.transition_declaration(
            env["decl_id"],
            {"action": "CERTIFY", "reviewer_assignment_id": env["cocounsel_id"]},
            headers=env.supervisor,
        )
    )
    assert_fields(certified, status="CERTIFIED", certified_at_utc=_CLOCK_UTC)
    assert_fields(env.matter(), version=before + 1)


def test_the_named_session_must_carry_the_counseling_language_not_the_clients(api):
    """A completed 'es' session does not license counseling delivered in 'pt'.

    The verification rule reads the session's language against the *counseling*
    language, so the read-back session that certified the declaration is useless
    here while the Portuguese rights-counseling session satisfies the gate
    outright. The last call then pins the fiscal ordering: an empty risks array is
    reported ahead of the now-stale concurrency token.

    Design: Corner/errors/err_declaration_not_certified_then_err_counseling_language_unverified_on_informed_decision
    """
    env = _matter_with_an_in_review_declaration(api)
    ok(
        api.transition_declaration(
            env["decl_id"],
            {"action": "CERTIFY", "reviewer_assignment_id": env["cocounsel_id"]},
            headers=env.supervisor,
        )
    )
    token = env.matter_version()

    def counsel(**fields):
        return api.create_informed_decision(
            factories.informed_decision_payload(
                env["matter_id"], env["lead_id"], token, **fields
            ),
            headers=env.lead_rep,
        )

    assert_error(
        counsel(counseling_language_code="pt"), ERR_COUNSELING_LANGUAGE_UNVERIFIED
    )
    assert_error(
        counsel(counseling_language_code="pt", readback_session_id=env["sess_id"]),
        ERR_COUNSELING_LANGUAGE_UNVERIFIED,
    )

    accepted = created(
        counsel(counseling_language_code="pt", readback_session_id=env["pt_sess_id"])
    )
    assert_fields(
        accepted,
        status="PENDING",
        language_match_verified=True,
        readback_session_id=env["pt_sess_id"],
        counseling_language_code="pt",
    )
    assert_null_fields(accepted, "superseded_by_decision_id")
    assert_fields(env.matter(), version=token + 1)

    # The token is now stale, but consent sufficiency is consulted before it.
    assert_error(
        counsel(counseling_language_code="es", risks_disclosed=[]),
        ERR_CONSENT_SCOPE_INSUFFICIENT,
    )
    assert_row_count(
        api.list_informed_decisions(
            params={"matter_id": env["matter_id"]}, headers=env.director
        ),
        1,
    )


# ---------------------------------------------------------------------------
# err_no_eligible_supervisor_when_the_matter_carries_no_supervisor_assignment_at_all
# ---------------------------------------------------------------------------


def test_the_supervisor_pool_is_empty_for_three_successive_reasons(api):
    """No supervisor row, then a merely proposed one, then a monolingual one.

    Every clause of the selection predicate is mandatory, so the pool can be
    emptied three different ways in a row without the matter ever changing; and
    because a staff attorney is exempt from the gate entirely, the same empty pool
    accepts a co-counsel on the very next call.

    Design: Corner/errors/err_no_eligible_supervisor_when_the_matter_carries_no_supervisor_assignment_at_all
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        cycle_label="FY26-H2",
        languages=["en", "es"],
    )
    client_id = new_client(
        env,
        full_name="Rosa Mena",
        date_of_birth="1990-04-11",
        preferred_language_code="es",
        country_of_birth_code="GT",
        household_size=3,
        annual_household_income_cents=2000000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    matter = accept_intake(env, client_id, case_type="U_VISA", detained=False)
    env.set(client_id=client_id, matter_id=matter["id"])

    monolingual = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Dov Adler", bar_number="BAR-5005", languages=["en"]
            ),
            headers=env.director,
        )
    )
    volunteer = created(
        api.create_representative(
            factories.volunteer_payload(
                full_name="Vic Lang", languages=["en", "es"], max_case_load=5
            ),
            headers=env.director,
        )
    )
    assert_fields(env.representative(volunteer["id"]), supervision_required=True)
    assert_fields(
        env.representative(monolingual["id"]),
        supervision_required=False,
        authorization_status="AUTHORIZED_ATTORNEY",
    )

    def propose_volunteer_lead():
        return api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                volunteer["id"],
                env.matter_version(),
                role_on_case="LEAD",
            ),
            headers=env.supervisor,
        )

    # (1) the matter carries no SUPERVISOR assignment at all
    token = env.matter_version()
    assert_error(propose_volunteer_lead(), ERR_NO_ELIGIBLE_SUPERVISOR)
    assert_fields(env.matter(), version=token)
    assert_no_rows(
        api.list_assignments(params={"matter_id": matter["id"]}, headers=env.director)
    )

    supervisor_row = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                monolingual["id"],
                env.matter_version(),
                role_on_case="SUPERVISOR",
            ),
            headers=env.supervisor,
        )
    )
    assert_fields(
        supervisor_row, status="PROPOSED", supervision_source="NOT_REQUIRED"
    )
    assert_null_fields(supervisor_row, "supervision_link_id")

    # (2) the sole supervisor row is still PROPOSED
    assert_error(propose_volunteer_lead(), ERR_NO_ELIGIBLE_SUPERVISOR)

    ok(
        api.transition_assignment(
            supervisor_row["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )

    # (3) the supervisor is now ACTIVE but does not speak the client's language
    assert_error(propose_volunteer_lead(), ERR_NO_ELIGIBLE_SUPERVISOR)

    exempt = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                env["atty_a_id"],
                env.matter_version(),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.supervisor,
        )
    )
    assert_fields(exempt, status="PROPOSED", supervision_source="NOT_REQUIRED")
    assert_null_fields(exempt, "supervision_link_id")
    assert_row_count(
        api.list_assignments(params={"matter_id": matter["id"]}, headers=env.director), 2
    )
    assert_fields(env.representative(monolingual["id"]), supervisee_count=0)


# ---------------------------------------------------------------------------
# err_report_period_invalid_and_err_report_state_invalid_across_the_full_report_lifecycle
# ---------------------------------------------------------------------------


def test_the_period_gate_has_three_failure_shapes_and_one_legal_single_day(api):
    """Reversed dates, a start before the window, an end after it -- then start == end.

    All three refusals name the period id even though the first pair of dates sits
    entirely inside the cycle window and the second and third are each off by a
    single day at opposite ends of an inclusive window. The degenerate one-day
    period is explicitly legal, and the row it produces is zero everywhere.

    Design: Corner/errors/err_report_period_invalid_and_err_report_state_invalid_across_the_full_report_lifecycle
    """
    env = template_a(api, clock=_CLOCK_UTC)

    def open_report(start, end):
        return api.create_grant_report(
            factories.grant_report_payload(
                env["cycle_id"],
                disclosure_level="AGGREGATE_ONLY",
                period_start_date=start,
                period_end_date=end,
            ),
            headers=env.analyst,
        )

    assert_error(open_report("2026-09-30", "2026-09-01"), ERR_REPORT_PERIOD_INVALID)
    assert_error(open_report("2026-06-30", "2026-09-01"), ERR_REPORT_PERIOD_INVALID)
    assert_error(open_report("2026-09-01", "2027-01-01"), ERR_REPORT_PERIOD_INVALID)
    assert_no_rows(
        api.list_grant_reports(params={"cycle_id": env["cycle_id"]}, headers=env.analyst)
    )

    opened = created(open_report("2026-07-01", "2026-07-01"))
    assert_fields(
        opened,
        status="DRAFT",
        amendment_round=0,
        outcomes_summary={},
        cases_served_count=0,
        consent_verified_count=0,
        suppressed_case_count=0,
        base_reimbursable_cents=0,
        supervision_surcharge_cents=0,
        total_reimbursable_cents=0,
        allocated_line_total_cents=0,
        rounding_remainder_cents=0,
    )
    assert_null_fields(opened, "generated_at_utc", "submitted_at_utc")


def test_an_empty_line_set_generates_and_submits_and_only_then_refuses(api):
    """A period containing no accepted matter is a legal, zero-valued report.

    Generation over an empty line set must not raise, and the SUBMIT guard --
    allocated equals total -- is satisfied at zero, so an empty report goes all the
    way to SUBMITTED. Generation is legal only from DRAFT and AMENDED, so the same
    action reports the state id from GENERATED and again from SUBMITTED, and the
    round trip through AMEND reproduces the money byte for byte.

    Design: Corner/errors/err_report_period_invalid_and_err_report_state_invalid_across_the_full_report_lifecycle
    """
    env = template_a(api, clock=_CLOCK_UTC)
    report = created(
        api.create_grant_report(
            factories.grant_report_payload(
                env["cycle_id"],
                disclosure_level="AGGREGATE_ONLY",
                period_start_date="2026-07-01",
                period_end_date="2026-07-01",
            ),
            headers=env.analyst,
        )
    )

    def act(action, **fields):
        payload = {"action": action}
        payload.update(fields)
        return api.transition_grant_report(report["id"], payload, headers=env.analyst)

    generated = ok(act("GENERATE"))
    assert_fields(
        generated,
        status="GENERATED",
        generated_at_utc=_CLOCK_UTC,
        cases_served_count=0,
        outcomes_summary={},
        base_reimbursable_cents=0,
        supervision_surcharge_cents=0,
        total_reimbursable_cents=0,
        allocated_line_total_cents=0,
        rounding_remainder_cents=0,
        version=report["version"] + 1,
    )
    assert_error(act("GENERATE"), ERR_REPORT_STATE_INVALID)
    assert_fields(ok(api.get_grant_report(report["id"], headers=env.analyst)), status="GENERATED")

    submitted = ok(act("SUBMIT"))
    assert_fields(submitted, status="SUBMITTED", submitted_at_utc=_CLOCK_UTC)

    assert_error(act("GENERATE"), ERR_REPORT_STATE_INVALID)

    amended = ok(act("AMEND", amendment_reason_code="FUNDER_QUERY"))
    assert_fields(amended, status="AMENDED", amendment_round=1)
    assert_null_fields(amended, "submitted_at_utc")

    regenerated = ok(act("GENERATE"))
    assert_fields(
        regenerated,
        status="GENERATED",
        cases_served_count=0,
        base_reimbursable_cents=0,
        total_reimbursable_cents=0,
        allocated_line_total_cents=0,
        amendment_round=1,
    )


# ---------------------------------------------------------------------------
# err_stale_recognition_version_on_renew_is_a_separate_412_from_the_matter_occ_token
# ---------------------------------------------------------------------------

_EXPIRING_CLOCK_UTC = "2029-06-01T09:00:00.000Z"


def test_the_renew_token_guards_the_recognition_not_the_accreditation(api):
    """A transition on the parent recognition invalidates the renewal token.

    The accreditation's own lifecycle is untouched between the two attempts, so an
    implementation that guards the row being written -- the natural reading -- lets
    the first renewal through. The refreshed token then succeeds from a CONDITIONAL
    recognition, and the grant is deliberately not recomputed: the term still
    carries the single forum the original approval granted.

    Design: Corner/errors/err_stale_recognition_version_on_renew_is_a_separate_412_from_the_matter_occ_token
    """
    env = template_a(api, clock=_CLOCK_UTC)
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(expiry_date="2030-01-01"), headers=env.director
        )
    )
    accredited = created(
        api.create_representative(
            factories.accredited_rep_payload(
                full_name="Nadia Rey", languages=["en", "es"], max_case_load=15
            ),
            headers=env.director,
        )
    )
    accreditation = created(
        api.create_accreditation(
            factories.accreditation_payload(
                accredited["id"],
                recognition["id"],
                accreditation_type="PARTIAL",
                requested_forums=["USCIS"],
            ),
            headers=env.director,
        )
    )
    approved = ok(
        api.transition_accreditation(
            accreditation["id"], {"action": "APPROVE"}, headers=env.supervisor
        )
    )
    # 2026-08-03 plus 1095 days.
    assert_fields(
        approved,
        status="APPROVED",
        effective_date="2026-08-03",
        expiry_date="2029-08-02",
        authorized_forums=["USCIS"],
        renewal_round=0,
    )

    # The 90-day window opens on 2029-05-04, so phase 3 ages the term.
    set_clock(api, _EXPIRING_CLOCK_UTC)
    ok(api.checkpoint_cycle(env["cycle_id"], headers=env.director))
    assert_fields(env.accreditation(accreditation["id"]), status="EXPIRING")

    stale_token = env.recognition(recognition["id"])["version"]
    conditioned = ok(
        api.transition_recognition(
            recognition["id"],
            {"action": "CONDITION", "conditional_reason_code": "STAFFING_DEFICIENCY"},
            headers=env.director,
        )
    )
    assert_fields(
        conditioned,
        status="CONDITIONAL",
        conditional_reason_code="STAFFING_DEFICIENCY",
        suspended_accreditation_count=0,
        version=stale_token + 1,
    )
    aged = env.accreditation(accreditation["id"])
    assert_fields(aged, status="EXPIRING")

    assert_error(
        api.renew_accreditation(
            accreditation["id"],
            {
                "expected_recognition_version": stale_token,
                "requested_forums": ["USCIS", "ASYLUM_OFFICE"],
            },
            headers=env.supervisor,
        ),
        ERR_STALE_RECOGNITION_VERSION,
    )
    assert_fields(
        env.accreditation(accreditation["id"]),
        status="EXPIRING",
        version=aged["version"],
        authorized_forums=["USCIS"],
    )

    fresh_token = env.recognition(recognition["id"])["version"]
    renewed = ok(
        api.renew_accreditation(
            accreditation["id"],
            {
                "expected_recognition_version": fresh_token,
                "requested_forums": ["USCIS", "ASYLUM_OFFICE"],
            },
            headers=env.supervisor,
        )
    )
    assert_fields(
        renewed,
        status="RENEWAL_PENDING",
        authorized_forums=["USCIS"],
        renewal_round=0,
    )
    assert_fields(
        env.recognition(recognition["id"]),
        status="CONDITIONAL",
        version=fresh_token + 1,
    )


# ---------------------------------------------------------------------------
# err_invariant_violation_never_fires_because_the_three_conservation_assertions_hold
# ---------------------------------------------------------------------------


def _two_accredited_leads_with_hours(api):
    """Two accredited-rep-led matters under one recognition, 4.00 hours logged on each."""
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        cycle_label="FY26-H2",
        total_case_slots=10,
        reserved_detained_slots=2,
        languages=["en", "es"],
    )
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(expiry_date="2030-01-01"), headers=env.director
        )
    )
    people = [("Nadia Rey", "Rosa Mena", "1990-04-11"), ("Omar Vale", "Bea Rios", "1988-02-19")]
    leads = []
    for rep_name, client_name, dob in people:
        rep = created(
            api.create_representative(
                factories.accredited_rep_payload(
                    full_name=rep_name, languages=["en", "es"], max_case_load=15
                ),
                headers=env.director,
            )
        )
        accreditation = created(
            api.create_accreditation(
                factories.accreditation_payload(
                    rep["id"],
                    recognition["id"],
                    accreditation_type="FULL",
                    requested_forums=["USCIS"],
                ),
                headers=env.director,
            )
        )
        ok(
            api.transition_accreditation(
                accreditation["id"], {"action": "APPROVE"}, headers=env.supervisor
            )
        )
        client_id = new_client(
            env,
            full_name=client_name,
            date_of_birth=dob,
            preferred_language_code="es",
            country_of_birth_code="GT",
            household_size=3,
            annual_household_income_cents=2000000,
            confidentiality_consent_scope="PROGRAM_ONLY",
        )
        matter = accept_intake(env, client_id, case_type="U_VISA", detained=False)
        env["matter_id"] = matter["id"]
        supervisor_id = add_supervisor_assignment(env, env["atty_b_id"])
        lead = created(
            api.create_assignment(
                factories.assignment_payload(
                    matter["id"], rep["id"], env.matter_version(), role_on_case="LEAD"
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
                {"hours": "4.00", "hours_kind": "DIRECT", "service_date": "2026-08-03"},
                headers=env.rep_headers(rep["id"]),
            )
        )
        leads.append(
            {
                "rep_id": rep["id"],
                "matter_id": matter["id"],
                "lead_id": lead["id"],
                "supervisor_assignment_id": supervisor_id,
                "accreditation_id": accreditation["id"],
            }
        )
    env.set(recognition_id=recognition["id"], leads=leads)
    return env


def test_the_heaviest_cascade_and_the_report_over_it_both_return_success(api):
    """A lapse touching ten rows, then a money report over its wreckage: no 5xx.

    The three conservation sums are all readable afterwards: the cycle's two
    consumption counters plus its available count still equal the total even though
    both matters fell into a coverage gap, the caseload and supervisee sums both
    collapse to zero exactly as the assignments left ACTIVE, and the report's
    allocated line total lands on the total to the cent with nothing left over.

    Design: Corner/errors/err_invariant_violation_never_fires_because_the_three_conservation_assertions_hold
    """
    env = _two_accredited_leads_with_hours(api)
    first, second = env["leads"]
    before = env.cycle()
    assert_fields(
        before,
        general_slots_consumed=2,
        detained_slots_consumed=0,
        available_slot_count=8,
        capacity_posture="OPEN",
    )
    assert_decimal_equals(before["utilization_ratio"], "0.2000", 4)
    for lead in (first, second):
        assert_decimal_equals(env.matter(lead["matter_id"])["direct_hours_logged"], "4.00", 2)

    lapsed = ok(
        api.transition_recognition(
            env["recognition_id"], {"action": "LAPSE"}, headers=env.director
        )
    )
    assert_fields(lapsed, status="LAPSED", suspended_accreditation_count=2)

    # Slot conservation: a coverage gap is not a withdrawal, so nothing was freed.
    after = env.cycle()
    assert_fields(
        after,
        general_slots_consumed=2,
        detained_slots_consumed=0,
        available_slot_count=8,
    )
    assert (
        after["general_slots_consumed"]
        + after["detained_slots_consumed"]
        + after["available_slot_count"]
        == after["total_case_slots"]
    ), "slot conservation must hold across the lapse cascade"

    # Caseload conservation: both sums fall to zero with the assignments.
    for lead in (first, second):
        assert_fields(
            env.representative(lead["rep_id"]),
            active_case_load=0,
            authorization_status="AUTHORIZATION_SUSPENDED",
        )
        assert_fields(env.assignment(lead["lead_id"]), status="SUSPENDED")
        assert_fields(
            env.matter(lead["matter_id"]),
            representation_status="COVERAGE_GAP",
            coverage_gap_flag=True,
        )
    assert_fields(env.representative(env["atty_b_id"]), supervisee_count=0)

    # Allocation conservation over the two coverage-gap matters.
    report = created(
        api.create_grant_report(
            factories.grant_report_payload(
                env["cycle_id"],
                disclosure_level="AGGREGATE_ONLY",
                period_start_date="2026-08-01",
                period_end_date="2026-12-31",
            ),
            headers=env.analyst,
        )
    )
    generated = ok(
        api.transition_grant_report(
            report["id"], {"action": "GENERATE"}, headers=env.analyst
        )
    )
    assert_fields(
        generated,
        status="GENERATED",
        cases_served_count=2,
        consent_verified_count=2,
        suppressed_case_count=0,
        outcomes_summary={"NOT_YET_DECIDED": 2},
        base_reimbursable_cents=100000,
        supervision_surcharge_cents=0,
        total_reimbursable_cents=100000,
        allocated_line_total_cents=100000,
        rounding_remainder_cents=0,
    )
    assert (
        generated["allocated_line_total_cents"] == generated["total_reimbursable_cents"]
    ), "allocation conservation must hold exactly"
