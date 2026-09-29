"""Breadth tests for the role gate, the row gate and the segregation pairs.

Three separate mechanisms are probed here and each is kept attributable to
exactly one rule: the endpoint role list (priority 2), the row-level actor scope
(priority 3) and the two-person controls, which key on ``X-User-ID`` rather than
on the declared role. Every denial is paired either with a byte-level proof that
nothing moved or with the identical request from a permitted caller.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_ACTOR_NOT_ON_CASE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REPRESENTATIVE_INACTIVE,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
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
    Env,
    accept_intake,
    minimal_world,
    new_client,
    template_a,
    template_b,
)
from test_helpers.test_users import (
    make_client_portal_headers,
    make_intake_screener_headers,
    program_director_headers,
)

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"

# A well-formed identifier that resolves to nothing, used to prove the role gate
# is evaluated before any path id is looked up.
_MISSING_CYCLE_ID = "00000000-0000-4000-8000-0000000000cc"
_MISSING_MATTER_ID = "00000000-0000-4000-8000-0000000000dd"


# ---------------------------------------------------------------------------
# program_director_exclusive_operations_are_denied_to_all_five_other_roles
# ---------------------------------------------------------------------------


def _director_world(api):
    """TEMPLATE A plus one ACTIVE recognition, so every director lever has a target.

    TEMPLATE A leaves exactly three representatives on the roster and exactly one
    capacity cycle, which is what makes the "nothing was created" halves of these
    denials countable.
    """
    env = template_a(api, clock=_CLOCK_UTC)
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                effective_date="2026-01-01",
                expiry_date="2030-01-01",
                authorized_forums=[
                    "USCIS",
                    "ASYLUM_OFFICE",
                    "EOIR_IMMIGRATION_COURT",
                    "BIA",
                ],
            ),
            headers=env.director,
        )
    )
    env.set(rec_id=recognition["id"])
    return env


def test_the_clock_and_the_capacity_levers_are_denied_to_four_other_roles(api):
    """One lever per role, so no denial can be explained by a different rule.

    The screener is refused the clock, the supervising attorney the cycle
    create, the case representative the posture override and the analyst the
    checkpoint -- and the override request names a fabricated cycle id yet still
    reports the role denial, because endpoint role membership is evaluated
    before any identifier in the URL is resolved. A single permitted checkpoint
    at the end reads the clock back out and settles both open questions at once.

    Design: Corner/rbac/program_director_exclusive_operations_are_denied_to_all_five_other_roles
    """
    env = _director_world(api)

    assert_error(
        api.set_clock("2026-09-01T00:00:00.000Z", headers=env.screener),
        ERR_ROLE_NOT_PERMITTED,
    )

    assert_error(
        api.create_capacity_cycle(
            factories.cycle_payload(
                cycle_label="FY27-H1",
                period_start_date="2027-01-01",
                period_end_date="2027-06-30",
                total_case_slots=10,
                reserved_detained_slots=2,
            ),
            headers=env.supervisor,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    assert_row_count(api.list_capacity_cycles(headers=env.director), 1)

    assert_error(
        api.posture_override(
            _MISSING_CYCLE_ID,
            {
                "posture_override_until_utc": "2026-09-01T00:00:00.000Z",
                "override_reason_code": "DIRECTOR_DISCRETION",
            },
            headers=env.rep_headers(env["atty_a_id"]),
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    assert_error(
        api.checkpoint_cycle(env["cycle_id"], headers=env.analyst),
        ERR_ROLE_NOT_PERMITTED,
    )
    # The cycle was created with checkpoint_epoch at 1, so the director's sweep
    # reaching 2 proves the analyst's sweep never ran; and the sweep stamps
    # last_checkpoint_utc from the logical clock, which is still where TEMPLATE A
    # left it, so the screener's clock call never landed either.
    swept = ok(api.checkpoint_cycle(env["cycle_id"], headers=env.director))
    assert_fields(swept, checkpoint_epoch=2, last_checkpoint_utc=_CLOCK_UTC)


def test_the_registry_roster_and_matter_levers_are_denied_to_their_own_actors(api):
    """The denials hold even for callers who own the row they are reaching for.

    A representative may not raise its own cap, the lead on the matter may not
    move its own facility, and the analyst naming a fabricated matter id still
    gets the role denial rather than a 404 -- the second proof that the role gate
    precedes existence resolution.

    Design: Corner/rbac/program_director_exclusive_operations_are_denied_to_all_five_other_roles
    """
    env = _director_world(api)

    assert_error(
        api.create_facility(
            factories.facility_payload(
                facility_code="PHX-ICE",
                facility_name="Phoenix ICE",
                jurisdiction_code="AZ-ELO",
            ),
            headers=env.portal,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    assert_no_rows(api.list_facilities(headers=env.director))

    assert_error(
        api.create_representative(
            factories.staff_attorney_payload(full_name="Mallory Doe", languages=["en"]),
            headers=env.supervisor,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    assert_row_count(api.list_representatives(headers=env.director), 3)

    assert_error(
        api.update_representative(
            env["atty_a_id"],
            {"max_case_load": 99},
            headers=env.rep_headers(env["atty_a_id"]),
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    assert_fields(env.representative(env["atty_a_id"]), max_case_load=25)

    assert_error(
        api.transition_recognition(
            env["rec_id"], {"action": "LAPSE"}, headers=env.supervisor
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    assert_fields(
        env.recognition(env["rec_id"]),
        status="ACTIVE",
        suspended_accreditation_count=0,
    )
    assert_null_fields(env.recognition(env["rec_id"]), "lapsed_at_utc")

    assert_error(
        api.set_facility(
            env["matter_id"],
            {"detained": False},
            headers=env.rep_headers(env["atty_a_id"]),
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    assert_error(
        api.withdraw_representation(
            _MISSING_MATTER_ID,
            {"withdrawal_reason_code": "CLIENT_REQUEST"},
            headers=env.analyst,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )


# ---------------------------------------------------------------------------
# client_portal_user_acknowledge_is_exclusive_and_row_scoped_to_its_own_client_id
# ---------------------------------------------------------------------------


def _counselled_matter_with_a_foreign_client(api):
    """TEMPLATE B plus a PENDING FILE_AFFIRMATIVE decision, plus an unrelated client.

    Bea Rios never appears on the matter, so her portal identity is the foreign
    identity the row gate must reject. The decision is counselled in Spanish by
    Rosa's own lead, which is what makes ``language_match_verified`` true and
    leaves the acknowledgement's only remaining obstacle the identity of the
    caller.
    """
    env = template_b(api, clock=_CLOCK_UTC)
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
    decision = created(
        api.create_informed_decision(
            factories.informed_decision_payload(
                env["matter_id"],
                env["lead_id"],
                env.matter_version(),
                decision_type="FILE_AFFIRMATIVE",
                counseling_language_code="es",
            ),
            headers=env.rep_headers(env["atty_a_id"]),
        )
    )
    assert_fields(decision, status="PENDING", language_match_verified=True)
    env.set(bea_id=bea_id, dec_id=decision["id"])
    return env


def test_no_representative_role_may_acknowledge_on_the_clients_behalf(api):
    """The counselling representative is not even on the transition endpoint.

    Its supervisor and the program director are on that endpoint -- they may
    revoke -- yet acknowledgement is available solely to the ClientPortalUser, so
    all three attempts leave the decision PENDING with no acknowledgement stamp.

    Design: Corner/rbac/client_portal_user_acknowledge_is_exclusive_and_row_scoped_to_its_own_client_id
    """
    env = _counselled_matter_with_a_foreign_client(api)

    assert_error(
        api.transition_informed_decision(
            env["dec_id"],
            {"action": "ACKNOWLEDGE"},
            headers=env.rep_headers(env["atty_a_id"]),
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    # The supervising attorney and the director sit on this endpoint for REVOKE,
    # so their ACKNOWLEDGE is refused at the action level: the contract fixes the
    # outcome (the decision does not become DOCUMENTED) without fixing which of
    # the two 403 ids is reported, so only the outcome is asserted.
    for headers in (env.supervisor, env.director):
        refused = api.transition_informed_decision(
            env["dec_id"], {"action": "ACKNOWLEDGE"}, headers=headers
        )
        assert refused.status_code >= 400, (
            "ACKNOWLEDGE is available solely to a ClientPortalUser, got "
            "{0}".format(refused.status_code)
        )
    assert_fields(env.informed_decision(env["dec_id"]), status="PENDING")
    assert_null_fields(env.informed_decision(env["dec_id"]), "acknowledged_at_utc")


def test_a_foreign_portal_user_is_row_scoped_and_the_owner_acknowledges_once(api):
    """Bea Rios is refused the row and shown an empty list rather than a 404.

    The role gate passes for her -- the ClientPortalUser owns this operation --
    so the refusal is the row gate one priority later, and the existence of
    another household's decision is never disclosed. Rosa Mena then succeeds on
    the byte-identical request, and her second attempt fails on state rather than
    on permission, because acknowledgement is not idempotent.

    Design: Corner/rbac/client_portal_user_acknowledge_is_exclusive_and_row_scoped_to_its_own_client_id
    """
    env = _counselled_matter_with_a_foreign_client(api)
    foreign = make_client_portal_headers(env["bea_id"])

    assert_error(
        api.transition_informed_decision(
            env["dec_id"], {"action": "ACKNOWLEDGE"}, headers=foreign
        ),
        ERR_ACTOR_NOT_ON_CASE,
    )
    assert_no_rows(
        api.list_informed_decisions(
            params={"matter_id": env["matter_id"]}, headers=foreign
        )
    )

    acknowledged = ok(
        api.transition_informed_decision(
            env["dec_id"], {"action": "ACKNOWLEDGE"}, headers=env.portal
        )
    )
    assert_fields(
        acknowledged, status="DOCUMENTED", acknowledged_at_utc=_CLOCK_UTC
    )

    assert_error(
        api.transition_informed_decision(
            env["dec_id"], {"action": "ACKNOWLEDGE"}, headers=env.portal
        ),
        ERR_INVALID_STATE_TRANSITION,
    )
    assert_fields(
        env.informed_decision(env["dec_id"]),
        status="DOCUMENTED",
        acknowledged_at_utc=_CLOCK_UTC,
    )


# ---------------------------------------------------------------------------
# grant_analyst_is_read_only_on_case_substance_and_case_representative_is_row_scoped
# ---------------------------------------------------------------------------


def _two_matters_with_disjoint_leads(api):
    """M1 led by Ada Ortiz and M2 led by Ben Cole, with no overlap between them.

    Ada holds no assignment of any status on M2, which is the precondition the
    row gate needs, and every matter has a lead so neither is in COVERAGE_GAP.
    """
    env = template_a(api, clock=_CLOCK_UTC)
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
    m2 = accept_intake(env, bea_id, case_type="U_VISA", detained=False)
    m2_lead = created(
        api.create_assignment(
            factories.assignment_payload(
                m2["id"], env["atty_b_id"], m2["version"], role_on_case="LEAD"
            ),
            headers=env.director,
        )
    )
    ok(
        api.transition_assignment(
            m2_lead["id"], {"action": "ACTIVATE"}, headers=env.director
        )
    )
    env.set(bea_id=bea_id, m2_id=m2["id"], m2_lead_id=m2_lead["id"])
    return env


def _identity_document(env, matter_id, **overrides):
    fields = {
        "item_type": "IDENTITY_DOCUMENT",
        "tier": "REQUIRED",
        "weight_points": 10,
        "requires_translation": False,
    }
    fields.update(overrides)
    return factories.evidence_payload(matter_id, **fields)


def test_the_grant_analyst_is_refused_every_case_write_and_served_every_case_read(api):
    """The read/write split inside one role, on the very same collections.

    The assignment create carries a token that is two versions stale, and the
    response must still be the role denial: role membership sits at priority 2
    and the stale-version guard at the very end of priority 6, so a GrantAnalyst
    never learns whether its token was current. Its reads are unfiltered, because
    an opaque identity has no row scope to filter against.

    Design: Corner/rbac/grant_analyst_is_read_only_on_case_substance_and_case_representative_is_row_scoped
    """
    env = _two_matters_with_disjoint_leads(api)

    assert_error(
        api.create_evidence(
            _identity_document(env, env["matter_id"]), headers=env.analyst
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    assert env.matter_version() > env["matter_v1"], "the token below must be stale"
    assert_error(
        api.create_assignment(
            factories.assignment_payload(
                env["matter_id"],
                env["atty_b_id"],
                env["matter_v1"],
                role_on_case="CO_COUNSEL",
            ),
            headers=env.analyst,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    assert_row_count(api.list_matters(headers=env.analyst), 2)
    assert_row_count(
        api.list_assignments(
            params={"matter_id": env["matter_id"]}, headers=env.analyst
        ),
        1,
    )
    assert_row_count(api.list_evidence(headers=env.analyst), 0)


def test_a_representative_is_refused_the_matter_it_holds_no_row_on(api):
    """Byte-identical evidence creates, one per matter, with opposite outcomes.

    Ada Ortiz holds no assignment of any status on M2, so her write there is
    refused with the row-scope id rather than a 404 -- M2's existence is not
    disclosed -- while the same request on her own matter lands.

    Design: Corner/rbac/grant_analyst_is_read_only_on_case_substance_and_case_representative_is_row_scoped
    """
    env = _two_matters_with_disjoint_leads(api)
    ada = env.rep_headers(env["atty_a_id"])

    assert_error(
        api.create_evidence(_identity_document(env, env["m2_id"]), headers=ada),
        ERR_ACTOR_NOT_ON_CASE,
    )
    assert_no_rows(api.list_evidence(params={"matter_id": env["m2_id"]}, headers=env.director))

    created(api.create_evidence(_identity_document(env, env["matter_id"]), headers=ada))
    item = only_row(
        api.list_evidence(params={"matter_id": env["matter_id"]}, headers=env.director)
    )
    assert_fields(item, matter_id=env["matter_id"], weight_points=10)


def test_the_row_gate_outranks_the_representatives_own_employment_gate(api):
    """Going INACTIVE strips write authority without releasing the assignment.

    On her own matter, where her ACTIVE LEAD still exists, the row gate passes
    and the employment gate one priority later fires; on M2 both gates fail at
    once and the row gate wins, which is only visible because the two ids differ.

    Design: Corner/rbac/grant_analyst_is_read_only_on_case_substance_and_case_representative_is_row_scoped
    """
    env = _two_matters_with_disjoint_leads(api)
    ada = env.rep_headers(env["atty_a_id"])

    patched = ok(
        api.update_representative(
            env["atty_a_id"], {"status": "INACTIVE"}, headers=env.director
        )
    )
    assert_fields(patched, status="INACTIVE", authorization_status="UNAUTHORIZED")
    assert_fields(env.assignment(env["lead_id"]), status="ACTIVE")

    assert_error(
        api.create_evidence(
            _identity_document(
                env, env["matter_id"], item_type="MEDICAL_RECORD", tier="SUPPORTING",
                weight_points=5,
            ),
            headers=ada,
        ),
        ERR_REPRESENTATIVE_INACTIVE,
    )
    assert_error(
        api.create_evidence(
            _identity_document(
                env, env["m2_id"], item_type="MEDICAL_RECORD", tier="SUPPORTING",
                weight_points=5,
            ),
            headers=ada,
        ),
        ERR_ACTOR_NOT_ON_CASE,
    )
    assert_no_rows(api.list_evidence(headers=env.director))


# ---------------------------------------------------------------------------
# segregation_of_duties_screener_cannot_decide_and_nobody_approves_its_own_accreditation
# ---------------------------------------------------------------------------


def _two_screenings_screened_by_different_people(api):
    """Rosa's intake screened by Nadia Okonjo and Bea's by Dov Halberstam.

    Both screeners are staff attorneys, so either may also present as a
    SupervisingAttorney on the decide endpoint: the role gate is satisfied for
    both of them on both rows, and the only thing that can separate the four
    combinations is the identity stamped in ``screener_representative_id``.
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        cycle_label="FY26-H2",
        period_start_date="2026-07-01",
        period_end_date="2026-12-31",
        total_case_slots=10,
        reserved_detained_slots=2,
        languages=["en", "es"],
    )
    rows_by_key = {}
    people = (
        ("rosa", "Rosa Mena", "1990-04-11", 3, 2000000, env["screener_id"]),
        ("bea", "Bea Rios", "1988-02-19", 1, 1000000, env["atty_b_id"]),
    )
    for key, name, dob, household, income, screened_by in people:
        client_id = new_client(
            env,
            full_name=name,
            preferred_language_code="es",
            country_of_birth_code="GT",
            date_of_birth=dob,
            household_size=household,
            annual_household_income_cents=income,
            confidentiality_consent_scope="PROGRAM_ONLY",
        )
        screener_headers = make_intake_screener_headers(screened_by)
        intake = created(
            api.create_intake(
                factories.intake_payload(
                    client_id,
                    env["cycle_id"],
                    case_type="U_VISA",
                    detained=False,
                    statutory_deadline_date="2026-12-01",
                ),
                headers=screener_headers,
            )
        )
        screened = ok(api.screen_intake(intake["id"], headers=screener_headers))
        assert_fields(
            screened, status="SCREENED", screener_representative_id=screened_by
        )
        rows_by_key[key] = intake["id"]
    env.set(
        rosa_intake_id=rows_by_key["rosa"], bea_intake_id=rows_by_key["bea"]
    )
    return env


def _accept(env, intake_id, actor_id):
    return env.api.decide_intake(
        intake_id,
        {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
        headers=env.attorney_headers(actor_id),
    )


def test_the_screener_of_a_row_may_not_decide_it_but_may_decide_another(api):
    """The two-person control is per row, which is what a role denial could not be.

    Nadia Okonjo is refused on the screening she assessed and accepted on the one
    she did not, and Dov Halberstam is refused and accepted in exactly the
    mirrored pair -- so the same two identities are each other's valid
    counterparties in opposite directions, and no slot was committed by the
    refusal.

    Design: Corner/rbac/segregation_of_duties_screener_cannot_decide_and_nobody_approves_its_own_accreditation
    """
    env = _two_screenings_screened_by_different_people(api)

    assert_error(
        _accept(env, env["rosa_intake_id"], env["screener_id"]),
        ERR_SEGREGATION_OF_DUTIES,
    )
    assert_fields(env.intake(env["rosa_intake_id"]), status="SCREENED")
    assert_null_fields(
        env.intake(env["rosa_intake_id"]), "decided_by_representative_id", "decided_at_utc"
    )
    assert_fields(env.cycle(), general_slots_consumed=0, detained_slots_consumed=0)

    accepted_bea = ok(_accept(env, env["bea_intake_id"], env["screener_id"]))
    assert_fields(
        accepted_bea,
        status="ACCEPTED",
        decided_by_representative_id=env["screener_id"],
        decided_at_utc=_CLOCK_UTC,
    )

    assert_error(
        _accept(env, env["bea_intake_id"], env["atty_b_id"]),
        ERR_SEGREGATION_OF_DUTIES,
    )
    accepted_rosa = ok(_accept(env, env["rosa_intake_id"], env["atty_b_id"]))
    assert_fields(
        accepted_rosa,
        status="ACCEPTED",
        decided_by_representative_id=env["atty_b_id"],
    )
    assert_fields(env.cycle(), general_slots_consumed=2)


def test_no_representative_approves_its_own_accreditation(api):
    """Nadia Rey is refused her own approval, and a colleague's approval lands.

    The refusal must be the segregation id even though she would also fail the
    approver's credential clause -- she is an ACCREDITED_REP, not a staff
    attorney -- because the no-self-approval clause is stated first. Nothing on
    the row moves: the term dates are still absent and her authorization is still
    UNAUTHORIZED.

    Design: Corner/rbac/segregation_of_duties_screener_cannot_decide_and_nobody_approves_its_own_accreditation
    """
    env = _two_screenings_screened_by_different_people(api)
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                effective_date="2026-01-01",
                expiry_date="2030-01-01",
                authorized_forums=[
                    "USCIS",
                    "ASYLUM_OFFICE",
                    "EOIR_IMMIGRATION_COURT",
                    "BIA",
                ],
            ),
            headers=env.director,
        )
    )
    nadia_rey = created(
        api.create_representative(
            factories.accredited_rep_payload(
                full_name="Nadia Rey", languages=["en", "es"], max_case_load=15,
                max_supervisees=0,
            ),
            headers=env.director,
        )
    )
    accreditation = created(
        api.create_accreditation(
            factories.accreditation_payload(
                nadia_rey["id"],
                recognition["id"],
                accreditation_type="FULL",
                requested_forums=[
                    "USCIS",
                    "ASYLUM_OFFICE",
                    "EOIR_IMMIGRATION_COURT",
                    "BIA",
                ],
            ),
            headers=env.director,
        )
    )
    assert_fields(accreditation, status="PENDING", renewal_round=0)
    before_version = env.representative(nadia_rey["id"])["version"]

    assert_error(
        api.transition_accreditation(
            accreditation["id"],
            {"action": "APPROVE"},
            headers=env.attorney_headers(nadia_rey["id"]),
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    assert_fields(env.accreditation(accreditation["id"]), status="PENDING")
    assert_null_fields(
        env.accreditation(accreditation["id"]),
        "approved_by_representative_id",
        "effective_date",
        "expiry_date",
    )
    assert_fields(
        env.representative(nadia_rey["id"]),
        authorization_status="UNAUTHORIZED",
        version=before_version,
    )

    approved = ok(
        api.transition_accreditation(
            accreditation["id"],
            {"action": "APPROVE"},
            headers=env.attorney_headers(env["atty_b_id"]),
        )
    )
    # 2026-08-03 plus 1095 days, and the granted forums are the intersection of
    # the request, the recognition and the FULL ceiling, sorted alphabetically.
    assert_fields(
        approved,
        status="APPROVED",
        approved_by_representative_id=env["atty_b_id"],
        effective_date="2026-08-03",
        expiry_date="2029-08-02",
        authorized_forums=["ASYLUM_OFFICE", "BIA", "EOIR_IMMIGRATION_COURT", "USCIS"],
        renewal_round=0,
    )
    assert_fields(
        env.representative(nadia_rey["id"]),
        authorization_status="AUTHORIZED_ACCREDITED",
        version=before_version + 1,
    )


# ---------------------------------------------------------------------------
# program_director_opaque_identity_can_never_be_a_segregation_of_duties_counterparty
# ---------------------------------------------------------------------------


def test_the_opaque_director_opens_and_then_decides_the_same_screening(api):
    """An identity that is never compared to any row cannot collide with one.

    The director opens the screening and then commits program resources to it --
    the two halves the screen/decide control forbids for an entity-backed actor --
    and the second half returns 200 rather than the segregation 403, because the
    opaque operator id can never equal ``screener_representative_id``. The same
    run exercises the director's exclusive levers positively, which is the mirror
    image of the denial sweeps above.

    Design: Corner/rbac/program_director_opaque_identity_can_never_be_a_segregation_of_duties_counterparty
    """
    director = program_director_headers()
    env = Env(api)
    ok(api.set_clock(_CLOCK_UTC, headers=director))
    cycle = created(
        api.create_capacity_cycle(
            factories.cycle_payload(
                cycle_label="FY26-H2",
                period_start_date="2026-07-01",
                period_end_date="2026-12-31",
                total_case_slots=10,
                reserved_detained_slots=2,
            ),
            headers=director,
        )
    )
    created(
        api.create_facility(
            factories.facility_payload(
                facility_code="EL-PASO-SPC",
                facility_name="El Paso Service Processing Center",
                jurisdiction_code="TX-ELP",
            ),
            headers=director,
        )
    )
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                effective_date="2026-01-01",
                expiry_date="2030-01-01",
                authorized_forums=["USCIS", "ASYLUM_OFFICE"],
            ),
            headers=director,
        )
    )
    ada = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Ada Ortiz", languages=["en", "es"]
            ),
            headers=director,
        )
    )
    nadia = created(
        api.create_representative(
            factories.accredited_rep_payload(
                full_name="Nadia Rey", languages=["en", "es"], max_case_load=15,
                max_supervisees=0,
            ),
            headers=director,
        )
    )
    client = created(
        api.create_client(
            factories.client_payload(
                full_name="Rosa Mena",
                preferred_language_code="es",
                country_of_birth_code="GT",
                date_of_birth="1990-04-11",
                household_size=3,
                annual_household_income_cents=2000000,
                confidentiality_consent_scope="PROGRAM_ONLY",
            ),
            headers=director,
        )
    )
    env.set(cycle_id=cycle["id"], client_id=client["id"])

    opened = created(
        api.create_intake(
            factories.intake_payload(
                client["id"],
                cycle["id"],
                case_type="U_VISA",
                detained=False,
                statutory_deadline_date="2026-12-01",
            ),
            headers=director,
        )
    )
    assert_null_fields(opened, "screener_representative_id")

    screened = ok(
        api.screen_intake(
            opened["id"], headers=make_intake_screener_headers(ada["id"])
        )
    )
    assert_fields(
        screened,
        status="SCREENED",
        screener_representative_id=ada["id"],
        legal_eligibility_verdict="ELIGIBLE",
    )
    assert_decimal_equals(env.client_row(client["id"])["fpl_percent"], "77.76", 2)

    decided = ok(
        api.decide_intake(
            opened["id"],
            {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
            headers=director,
        )
    )
    assert_fields(decided, status="ACCEPTED", decided_at_utc=_CLOCK_UTC)
    matter = only_row(
        api.list_matters(params={"intake_id": opened["id"]}, headers=director)
    )
    assert_fields(
        matter, representation_status="UNSTAFFED", filing_status="PRE_FILING"
    )

    accreditation = created(
        api.create_accreditation(
            factories.accreditation_payload(
                nadia["id"],
                recognition["id"],
                accreditation_type="PARTIAL",
                requested_forums=["USCIS"],
            ),
            headers=director,
        )
    )
    assert_fields(accreditation, status="PENDING", authorized_forums=[])

    patched = ok(
        api.update_representative(
            nadia["id"], {"weekly_capacity_hours": "20.00"}, headers=director
        )
    )
    assert_decimal_equals(patched["weekly_capacity_hours"], "20.00", 2)

    overridden = ok(
        api.posture_override(
            cycle["id"],
            {
                "posture_override_until_utc": "2026-08-31T00:00:00.000Z",
                "override_reason_code": "DIRECTOR_DISCRETION",
            },
            headers=director,
        )
    )
    # The override is strictly a downgrade, so an OPEN cycle stays OPEN while the
    # timestamp is nonetheless stored.
    assert_fields(
        overridden,
        posture_override_until_utc="2026-08-31T00:00:00.000Z",
        capacity_posture="OPEN",
    )

    swept = ok(api.checkpoint_cycle(cycle["id"], headers=director))
    assert_fields(swept, checkpoint_epoch=2, last_checkpoint_utc=_CLOCK_UTC)
