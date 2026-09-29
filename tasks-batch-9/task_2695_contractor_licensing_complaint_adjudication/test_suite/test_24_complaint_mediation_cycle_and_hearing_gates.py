"""Complaint mediation cycle and hearing-gate corners.

Covers the consumer-facing half of the enforcement story: the screening act that
may only happen once, the terminal dismissal that no later request may reopen,
the mediation loop with its two-round ceiling, the settlement that closes a file
on the pleaded figure, and the calendar gate that stops an officer deciding an
appeal before the hearing has convened.
"""

from test_helpers import (
    assert_complaint,
    assert_citation,
    assert_disciplinary_hearing,
    assert_investigation,
    factories as F,
    fixtures as X,
    make_consumer_headers,
    make_hearing_officer_headers,
    make_investigator_headers,
    validate_error,
    validate_success,
)


def test_screening_a_complaint_a_second_time_is_refused(api, licensing_analyst_headers):
    """Screening happens once; the repeat request changes nothing it already stamped.

    "It is defined only from `RECEIVED`; screening an already-screened complaint
    draws `ERR_COMPLAINT_STATE_INVALID`."

    "Its `jurisdiction_basis` is stamped `UNLICENSED_PRACTICE` when no
    `license_id` was supplied, and `LICENSED_SUBJECT` otherwise."

    "Critically, `mediation_round_count` stays at zero and `mediation_deadline`
    stays null: **this branch never opens a mediation window**, which matters
    later because the remand rule counts rounds."

    Design: Corner/state_machines/corner_screening_a_complaint_twice_is_refused
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    consumer = X.register_consumer(
        api, full_name="Ida Idem", contact_email="ida@home.test", mailing_state="CA"
    )
    payload = {
        "consumer_id": consumer["id"],
        "subject_business_name": "No Licence Larry",
        "alleged_loss_cents": 400000,
        "contract_date": "2026-07-01",
        "description": "Paid for a panel upgrade never performed",
    }
    complaint = validate_success(
        api.create_complaint(payload, make_consumer_headers(consumer["id"])),
        expected_status=201,
    )
    screened = X.screen_accepted(api, complaint["id"])
    assert screened["status"] == "INVESTIGATION", (
        "an unlicensed subject goes straight to enforcement, got "
        f"{screened['status']!r}"
    )

    validate_error(
        api.screen_complaint(
            complaint["id"], F.screening_payload("ACCEPTED"), licensing_analyst_headers
        ),
        "ERR_COMPLAINT_STATE_INVALID",
        expected_status=409,
    )

    stored = validate_success(
        api.get_complaint(complaint["id"], licensing_analyst_headers)
    )
    assert_complaint(
        stored,
        status="INVESTIGATION",
        jurisdiction_basis="UNLICENSED_PRACTICE",
        mediation_round_count=0,
        mediation_deadline=None,
    )


def test_a_dismissed_complaint_cannot_be_withdrawn(api, licensing_analyst_headers):
    """A file the board never took jurisdiction of is closed for good.

    "A `REJECTED` finding requires a `rejection_reason` and drives the complaint
    `RECEIVED → DISMISSED_NO_JURISDICTION`, storing that narrative as
    `dismissal_reason` and leaving `jurisdiction_basis` null — the board never
    reached the merits, so it never characterised the basis."

    "Withdrawing an already-closed complaint draws
    `ERR_COMPLAINT_STATE_INVALID`."

    Design: Corner/state_machines/corner_withdrawing_a_dismissed_complaint_is_refused
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    consumer = X.register_consumer(
        api,
        full_name="Terry Terminal",
        contact_email="terry@home.test",
        mailing_state="CA",
    )
    payload = {
        "consumer_id": consumer["id"],
        "subject_business_name": "Out Of State Roofing",
        "alleged_loss_cents": 400000,
        "contract_date": "2026-07-01",
        "description": "Roof work performed in another state",
    }
    complaint = validate_success(
        api.create_complaint(payload, make_consumer_headers(consumer["id"])),
        expected_status=201,
    )
    dismissed = validate_success(
        api.screen_complaint(
            complaint["id"],
            F.screening_payload("REJECTED", rejection_reason="OUT_OF_STATE_WORK"),
            licensing_analyst_headers,
        )
    )
    assert dismissed["status"] == "DISMISSED_NO_JURISDICTION", (
        f"a rejected screening dismisses the file, got {dismissed['status']!r}"
    )

    validate_error(
        api.withdraw_complaint(
            complaint["id"], make_consumer_headers(consumer["id"])
        ),
        "ERR_COMPLAINT_STATE_INVALID",
        expected_status=409,
    )

    stored = validate_success(
        api.get_complaint(complaint["id"], licensing_analyst_headers)
    )
    assert_complaint(
        stored,
        status="DISMISSED_NO_JURISDICTION",
        dismissal_reason="OUT_OF_STATE_WORK",
        jurisdiction_basis=None,
    )


def test_a_remand_re_arms_mediation_and_parks_the_open_case(
    api, licensing_analyst_headers
):
    """Sending a case back to the table opens a second window and closes nothing.

    "The complaint moves `RECEIVED → MEDIATION`, its `jurisdiction_basis` is
    stamped `LICENSED_SUBJECT`, its `mediation_round_count` is set to 1, and its
    `mediation_deadline` is set to the clock date advanced by thirty days — the
    window in which the current mediation attempt must produce something."

    "A remand raises `mediation_round_count` by one, sets `mediation_deadline`
    to the clock date advanced by thirty days, and leaves every investigation on
    the complaint that is still `OPEN` open — the case is parked, not closed."

    Design: Corner/state_machines/corner_remanding_to_mediation_bumps_the_round_count_and_parks_the_case
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = X.mint_active_license(
        api,
        legal_name="Loop Electric LLC",
        contact_email="loop@x.test",
        full_name="Lou Loop",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )
    consumer = X.register_consumer(
        api, full_name="Lena Loop", contact_email="lena@home.test", mailing_state="CA"
    )

    X.set_clock(api, "2026-09-01T00:00:00Z")
    complaint = X.file_complaint(
        api,
        consumer["id"],
        ctx.license_id,
        alleged_loss_cents=500000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Subpanel left energised and open",
    )
    screened = X.screen_accepted(api, complaint["id"])
    assert screened["status"] == "MEDIATION", (
        f"a mediation-required trade mediates first, got {screened['status']!r}"
    )
    assert screened["mediation_round_count"] == 1, (
        f"screening opens the first round, got {screened['mediation_round_count']}"
    )
    failed = X.fail_mediation(api, complaint["id"])
    assert failed["status"] == "INVESTIGATION", (
        f"a failed attempt hands the file to enforcement, got {failed['status']!r}"
    )
    investigation = X.open_investigation(
        api,
        complaint_id=complaint["id"],
        subject_license_id=ctx.license_id,
        investigator_user_id="inv-41",
    )

    remanded = validate_success(
        api.remand_to_mediation(
            complaint["id"],
            {"remand_reason": "Licensee offered to re-pull the permit"},
            make_investigator_headers("inv-41"),
        )
    )
    assert_complaint(
        remanded,
        status="MEDIATION",
        mediation_round_count=2,
        mediation_deadline="2026-10-01",
    )

    stored_case = validate_success(
        api.get_investigation(investigation["id"], licensing_analyst_headers)
    )
    assert_investigation(stored_case, status="OPEN", closed_on=None)


def test_a_second_remand_hits_the_two_round_ceiling(api, licensing_analyst_headers):
    """Two attempts at the table are all a complaint gets.

    "Two conditions guard it, both reported as `ERR_MEDIATION_ROUNDS_EXHAUSTED`:
    the complaint's `mediation_round_count` must be strictly below two, and no
    citation may yet exist on any investigation of the complaint."

    Design: Corner/state_machines/corner_a_second_remand_is_refused_by_the_mediation_round_cap
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = X.mint_active_license(
        api,
        legal_name="Capped Electric LLC",
        contact_email="cap@x.test",
        full_name="Cap Capman",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )
    consumer = X.register_consumer(
        api, full_name="Cass Capman", contact_email="cass@home.test", mailing_state="CA"
    )

    X.set_clock(api, "2026-09-01T00:00:00Z")
    complaint = X.file_complaint(
        api,
        consumer["id"],
        ctx.license_id,
        alleged_loss_cents=500000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Service upgrade abandoned mid-job",
    )
    X.screen_accepted(api, complaint["id"])
    X.fail_mediation(api, complaint["id"])
    investigation = X.open_investigation(
        api,
        complaint_id=complaint["id"],
        subject_license_id=ctx.license_id,
        investigator_user_id="inv-51",
    )
    validate_success(
        api.remand_to_mediation(
            complaint["id"],
            {"remand_reason": "First remand"},
            make_investigator_headers("inv-51"),
        )
    )
    back = X.fail_mediation(api, complaint["id"])
    assert back["status"] == "INVESTIGATION", (
        f"the second attempt also fails out to enforcement, got {back['status']!r}"
    )

    validate_error(
        api.remand_to_mediation(
            complaint["id"],
            {"remand_reason": "Second remand"},
            make_investigator_headers("inv-51"),
        ),
        "ERR_MEDIATION_ROUNDS_EXHAUSTED",
        expected_status=409,
    )

    stored = validate_success(
        api.get_complaint(complaint["id"], licensing_analyst_headers)
    )
    assert_complaint(stored, status="INVESTIGATION", mediation_round_count=2)

    stored_case = validate_success(
        api.get_investigation(investigation["id"], licensing_analyst_headers)
    )
    assert_investigation(stored_case, status="OPEN")


def test_a_settlement_closes_the_complaint_on_the_agreed_figure(
    api, licensing_analyst_headers
):
    """A settled mediation records the cash received and leaves the pleaded loss alone.

    "A `SETTLED` outcome requires a `settlement_amount_cents` of at least one
    cent and moves the complaint `MEDIATION → CLOSED_RESOLVED`, storing that
    figure as the cash the consumer actually received."

    Design: Corner/state_machines/corner_mediation_settlement_closes_the_complaint_and_stores_the_amount
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = X.mint_active_license(
        api,
        legal_name="Settle Electric LLC",
        contact_email="set@x.test",
        full_name="Seth Settle",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )
    consumer = X.register_consumer(
        api, full_name="Sue Settle", contact_email="sue@home.test", mailing_state="CA"
    )

    X.set_clock(api, "2026-09-01T00:00:00Z")
    complaint = X.file_complaint(
        api,
        consumer["id"],
        ctx.license_id,
        alleged_loss_cents=500000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Fixtures wired but not trimmed out",
    )
    X.screen_accepted(api, complaint["id"])

    settled = validate_success(
        api.record_mediation_outcome(
            complaint["id"],
            F.mediation_outcome_payload("SETTLED", settlement_amount_cents=250000),
            licensing_analyst_headers,
        )
    )
    assert settled["status"] == "CLOSED_RESOLVED", (
        f"a settlement resolves the file, got {settled['status']!r}"
    )

    stored = validate_success(
        api.get_complaint(complaint["id"], licensing_analyst_headers)
    )
    assert_complaint(
        stored,
        settlement_amount_cents=250000,
        alleged_loss_cents=500000,
        mediation_round_count=1,
    )


def test_deciding_a_hearing_before_it_convenes_is_refused(
    api, licensing_analyst_headers
):
    """The bench cannot rule on a hearing whose start time has not arrived.

    "The gates fire in order: the hearing must be `SCHEDULED` (otherwise
    `ERR_HEARING_STATE_INVALID`) and its citation must be `HEARING_SCHEDULED`;
    the actor's `X-User-ID` must equal `presiding_officer_user_id` (otherwise
    `ERR_NOT_PRESIDING_OFFICER`); the clock timestamp must be at or after
    `scheduled_start_utc`, since a hearing cannot be decided before it convenes
    (otherwise `ERR_HEARING_NOT_CONVENED`); and the penalty-substitution rules
    must hold — `modified_penalty_cents` must be supplied for a `MODIFY`
    decision, must be omitted for `AFFIRM` and `VACATE`, and must never exceed
    the statutory ceiling of 1,500,000 cents, with any violation reporting
    `ERR_PENALTY_EXCEEDS_STATUTORY_MAX`."

    "The **hazard multiplier** is one plus a quarter for each tier above the
    first, so a `hazard_tier` of 1 gives one, a tier of 2 gives one and a
    quarter, and a tier of 3 gives one and a half."

    Design: Corner/state_machines/corner_deciding_a_hearing_before_it_convenes_is_refused
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c20_classification(api)
    ctx = X.mint_active_license(
        api,
        classification,
        legal_name="Convene Air LLC",
        contact_email="conv@x.test",
        full_name="Connie Convene",
        verified_experience_months=60,
        declared_net_worth_cents=400000,
    )
    consumer = X.register_consumer(
        api, full_name="Cal Convene", contact_email="calc@home.test", mailing_state="CA"
    )

    X.set_clock(api, "2026-09-01T00:00:00Z")
    _, _, citation = X.substantiated_citation(
        api,
        ctx,
        consumer["id"],
        severity="SERIOUS",
        violation_code="B-7109",
        correction_due_date="2026-10-15",
        alleged_loss_cents=500000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        investigator_user_id="inv-21",
    )
    assert citation["civil_penalty_cents"] == 312500, (
        "a SERIOUS licensed citation in a tier-2 trade assesses 312500, got "
        f"{citation['civil_penalty_cents']}"
    )
    hearing = X.appealed_citation_with_hearing(
        api,
        citation["id"],
        ctx.licensee_id,
        "2026-09-10T14:00:00Z",
        "2026-09-10T16:00:00Z",
        presiding_officer_user_id="ho-31",
    )

    validate_error(
        api.decide_hearing(
            hearing["id"],
            F.hearing_decision_payload("AFFIRM", findings_summary="Decided early"),
            make_hearing_officer_headers("ho-31"),
        ),
        "ERR_HEARING_NOT_CONVENED",
        expected_status=422,
    )

    stored_hearing = validate_success(
        api.get_hearing(hearing["id"], licensing_analyst_headers)
    )
    assert_disciplinary_hearing(stored_hearing, status="SCHEDULED", decision=None)

    stored_citation = validate_success(
        api.get_citation(citation["id"], licensing_analyst_headers)
    )
    assert_citation(
        stored_citation,
        status="HEARING_SCHEDULED",
        civil_penalty_cents=312500,
        penalty_variant="INITIAL_ASSESSMENT",
    )
