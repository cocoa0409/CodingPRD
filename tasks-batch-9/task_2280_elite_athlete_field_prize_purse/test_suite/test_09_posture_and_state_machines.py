"""Declared transitions, their side effects, their initial states and the ops sweep."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    LIAISON,
    TECHNICAL,
    add_division_standard,
    add_purse_line,
    agent_counters,
    api_client,
    create_invitation,
    create_race_result_payload,
    certify_result,
    collect_sample,
    enroll_accepted_invitation,
    enroll_draft_invitation,
    enroll_offered_invitation,
    enter_result,
    lock_field,
    make_elites_director_headers,
    mark_raced,
    open_field,
    read_athlete,
    read_doping_test,
    read_edition,
    read_invitation,
    read_result,
    register_agent,
    register_athlete,
    reject_performance,
    reject_performance_payload,
    run_ops,
    schedule_doping_test,
    send_offer,
    set_clock,
    setup_configured_edition,
    setup_field_open_edition,
    submit_performance,
    validate_error,
    validate_paginated,
    verify_performance,
    verify_performance_payload,
)

ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}
OVERALL_MALE_FIRST = {"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}
SWEEP_OFFER = {"appearance_fee_cents": 700_000, "air_class": "ECONOMY",
               "hotel_nights": 2, "ground_transport": False}


def test_opening_the_field_flips_a_configured_edition_and_bumps_its_version():
    """A complete minimum configuration is all `PLANNING → FIELD_OPEN` needs.

    PRD §3.1: "Opening the field is the `ElitesDirector`'s first posture change,
    moving the edition `PLANNING → FIELD_OPEN`, and it is admitted only when the
    edition already has at least one division standard and at least one purse line in
    the `OVERALL` category; otherwise it is refused with
    `ERR_EDITION_CONFIG_INCOMPLETE`." PRD §2.5 fixes the counter: `version` is "a
    system-managed integer that starts at 1 on creation and increases by one on every
    mutation".

    Design: Corner/state_machines/corner_open_field_moves_edition_planning_to_field_open
    """
    scenario = setup_configured_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Open Field Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    version_before = scenario["edition"]["version"]

    opened = open_field(edition_id)
    assert opened["status"] == "FIELD_OPEN"
    assert opened["version"] == version_before + 1

    persisted = read_edition(edition_id)
    assert persisted["status"] == "FIELD_OPEN"
    assert persisted["appearance_committed_cents"] == 0, (
        "opening the field commits no money"
    )
    assert persisted["purse_allocated_cents"] == 0


def test_a_division_standard_alone_does_not_complete_the_configuration():
    """Both configuration kinds are required, and neither refusal moves the posture.

    PRD §2.11 priority 7: "**Configuration completeness.** Opening the field requires
    at least one `DivisionStandard` and at least one `OVERALL` purse line for that
    edition, else `ERR_EDITION_CONFIG_INCOMPLETE` (422). This guards the open-field
    operation only." PRD §3.1 adds that "A freshly created edition is in `PLANNING`".

    Design: Corner/state_machines/corner_open_field_precondition_requires_standards_and_purse_lines
    """
    scenario = setup_configured_edition(
        purse_lines=[],
        standards=[],
        name="Incomplete Config Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]

    nothing_configured = api_client.open_field(edition_id, DIRECTOR)
    validate_error(nothing_configured,
                   ApiErrorId.ERR_EDITION_CONFIG_INCOMPLETE.value, 422)
    assert read_edition(edition_id)["status"] == "PLANNING"

    add_division_standard(edition_id, **ELITE_MALE_STANDARD)
    standard_only = api_client.open_field(edition_id, DIRECTOR)
    validate_error(standard_only, ApiErrorId.ERR_EDITION_CONFIG_INCOMPLETE.value, 422)
    assert read_edition(edition_id)["status"] == "PLANNING", (
        "a standard alone leaves the edition where it was"
    )

    add_purse_line(edition_id, **OVERALL_MALE_FIRST)
    assert open_field(edition_id)["status"] == "FIELD_OPEN"


def test_sending_the_offer_fires_every_declared_side_effect_at_once():
    """One call stamps the clock, the deadline, the operator, the terms and round one.

    PRD §3.3: "Sending the offer writes the first **negotiation round**, with `side`
    set to `COMMITTEE` and `round_number` 1, mirrors the posted terms onto the
    invitation's four `current_` fields, stamps `offer_sent_at` from the logical clock,
    sets `response_deadline_at` to the logical clock plus the edition's
    `offer_response_days` days, records the acting operator in `negotiated_by_user_id`,
    and leaves the invitation in `OFFERED`." The dial was set explicitly, and PRD §3.1
    describes it: "`offer_response_days` is how long an offer or a counter stays open
    before it goes stale; it defaults to 14 and must lie between 1 and 60 inclusive."

    Design: Corner/state_machines/corner_offer_side_effects_stamp_deadline_round_and_negotiator
    """
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Side Effect Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
        offer_response_days=10,
    )
    enrolment = enroll_draft_invitation(
        scenario["edition"]["id"],
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900},
    )
    invitation_id = enrolment["invitation"]["id"]
    set_clock("2026-08-05T12:00:00Z")

    offered = send_offer(
        invitation_id, headers=make_elites_director_headers("director-7"),
        appearance_fee_cents=900_000, air_class="BUSINESS", hotel_nights=3,
        ground_transport=True, note="committee opening package",
    )
    assert offered["status"] == "OFFERED"
    assert offered["offer_sent_at"] == "2026-08-05T12:00:00.000Z"
    assert offered["response_deadline_at"] == "2026-08-15T12:00:00.000Z", (
        "the deadline is the clock plus the edition's ten response days"
    )
    assert offered["negotiated_by_user_id"] == "director-7"
    assert offered["current_appearance_fee_cents"] == 900_000
    assert offered["current_air_class"] == "BUSINESS"
    assert offered["current_hotel_nights"] == 3
    assert offered["current_ground_transport"] is True
    assert offered["round_count"] == 1

    rounds, meta = validate_paginated(
        api_client.list_negotiation_rounds(invitation_id, DIRECTOR)
    )
    assert meta["total_count"] == 1
    assert rounds[0]["round_number"] == 1
    assert rounds[0]["side"] == "COMMITTEE"
    assert rounds[0]["note"] == "committee opening package"


def test_an_offer_on_the_table_has_committed_no_appearance_money():
    """The valuation stays out of the ledger until the agent accepts.

    PRD §3.4: "In every status other than `ACCEPTED`, `guaranteed_commitment_cents`
    reads as zero." PRD §2.9 fixes the projection it feeds:
    "`appearance_committed_cents` is the sum of `guaranteed_commitment_cents` over the
    invitations of that edition whose `status` is `ACCEPTED`".

    Design: Corner/state_machines/corner_offer_side_effects_stamp_deadline_round_and_negotiator
    """
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Side Effect Ledger Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
        offer_response_days=10,
    )
    edition_id = scenario["edition"]["id"]
    enrolment = enroll_draft_invitation(
        edition_id,
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900},
    )
    set_clock("2026-08-05T12:00:00Z")

    offered = send_offer(
        enrolment["invitation"]["id"],
        headers=make_elites_director_headers("director-7"),
        appearance_fee_cents=900_000, air_class="BUSINESS", hotel_nights=3,
        ground_transport=True, note="committee opening package",
    )
    assert offered["guaranteed_commitment_cents"] == 0
    assert offered["full_exposure_cents"] == 0, (
        "full exposure is stamped only when the field locks"
    )

    edition = read_edition(edition_id)
    assert edition["appearance_committed_cents"] == 0
    assert edition["appearance_uncommitted_cents"] == 9_000_000


def test_the_posture_pipeline_admits_no_shortcut_out_of_planning():
    """Lock-field, mark-raced and certify-results are each illegal from `PLANNING`.

    PRD §2.6: "Each `RaceEdition` moves through a linear posture pipeline whose values
    are `PLANNING`, `FIELD_OPEN`, `FIELD_LOCKED`, `RACED`, `RESULTS_CERTIFIED` and
    `PURSE_SETTLED`." Locking is "moving the edition `FIELD_OPEN → FIELD_LOCKED`" per
    PRD §3.4, marking raced is "moving the edition `FIELD_LOCKED → RACED`" and
    certifying the edition is "moving it `RACED → RESULTS_CERTIFIED`" per PRD §3.7.
    PRD §2.6 fixes the refusal: "When the posture does not permit the operation, the
    rejection is `ERR_EDITION_STATE_INVALID`."

    Design: Corner/state_machines/corner_lock_field_from_planning_is_an_invalid_transition
    """
    scenario = setup_configured_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="No Shortcut Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    version_before = scenario["edition"]["version"]

    validate_error(api_client.lock_field(edition_id, DIRECTOR),
                   ApiErrorId.ERR_EDITION_STATE_INVALID.value, 409)
    validate_error(api_client.mark_raced(edition_id, TECHNICAL),
                   ApiErrorId.ERR_EDITION_STATE_INVALID.value, 409)
    validate_error(api_client.certify_results(edition_id, TECHNICAL),
                   ApiErrorId.ERR_EDITION_STATE_INVALID.value, 409)

    edition = read_edition(edition_id)
    assert edition["status"] == "PLANNING"
    assert edition["version"] == version_before, (
        "three rejected transitions mutated nothing"
    )


def test_every_state_machine_row_is_born_in_its_declared_initial_state():
    """Edition, performance record, invitation and doping test all start upstream.

    PRD §3.1: "A freshly created edition is in `PLANNING`, with
    `appearance_committed_cents` and `purse_allocated_cents` both at zero,
    `expired_offer_count` at zero, and `version` at 1." PRD §3.2: "New records begin
    with `verification_status` at `SUBMITTED` and `verified_seconds` at null." PRD §3.3:
    "A `DRAFT` invitation has `guaranteed_commitment_cents` at zero,
    `full_exposure_cents` at zero and `round_count` at zero, and its
    `current_appearance_fee_cents`, `current_air_class`, `current_hotel_nights`,
    `current_ground_transport`, `offer_sent_at`, `response_deadline_at`, `bib_number`
    and `negotiated_by_user_id` are all null." PRD §3.6: "A new test begins in
    `SCHEDULED` with `collected_at`, `collected_sample_ref` and `outcome_notes` all
    null."

    Design: Corner/state_machines/corner_initial_states_of_every_created_row
    """
    scenario = setup_configured_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Initial State Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    assert scenario["edition"]["status"] == "PLANNING"
    assert scenario["edition"]["expired_offer_count"] == 0
    open_field(edition_id)

    athlete = register_athlete(country_code="USA", whereabouts_filed=True)
    agent = register_agent(agency_name="Genesis Reps")

    record = submit_performance(athlete["id"], race_name="Qual IS",
                                performance_date="2026-03-01",
                                performance_seconds=7_900, division="ELITE",
                                sanctioning_ref="SB-IS-1", chip_timed=True)
    assert record["verification_status"] == "SUBMITTED"
    assert record["verified_seconds"] is None
    assert record["rejection_reason"] is None
    verify_performance(record["id"], 7_900)

    invitation = create_invitation(edition_id, athlete["id"], agent["id"],
                                   record["id"], "ELITE")
    assert invitation["status"] == "DRAFT"
    assert invitation["bib_number"] is None
    assert invitation["offer_sent_at"] is None
    assert invitation["response_deadline_at"] is None
    assert invitation["round_count"] == 0

    test = schedule_doping_test(athlete["id"], edition_id,
                               test_type="OUT_OF_COMPETITION",
                               window_start_at="2026-10-01T08:00:00Z",
                               window_end_at="2026-10-01T18:00:00Z",
                               sample_code="S-IS-1")
    assert test["status"] == "SCHEDULED"
    assert test["collected_at"] is None
    assert test["outcome_notes"] is None


def test_a_rejected_qualifying_time_can_never_be_re_adjudicated():
    """Neither a reversal to `VERIFIED` nor a second rejection is admitted.

    PRD §3.2: "A `decision` of `REJECTED` must be accompanied by a
    `rejection_reason`, which is stored; the record moves `SUBMITTED → REJECTED` and
    can never qualify an invitation again. Both target states are terminal, so a
    second verification attempt on an already-adjudicated record is refused with
    `ERR_INVALID_PERFORMANCE_STATE`."

    Design: Corner/state_machines/corner_rejected_performance_record_is_terminal
    """
    athlete = register_athlete(country_code="USA", gender="FEMALE",
                               birth_date="1995-01-15")
    record = submit_performance(athlete["id"], race_name="Qual TM",
                                performance_date="2026-03-01",
                                performance_seconds=8_800, division="ELITE",
                                sanctioning_ref="SB-TM-1", chip_timed=True)
    rejected = reject_performance(record["id"], "course not certified")
    assert rejected["verification_status"] == "REJECTED"

    reversal = api_client.verify_performance_record(
        record["id"], verify_performance_payload(8_800), TECHNICAL
    )
    validate_error(reversal, ApiErrorId.ERR_INVALID_PERFORMANCE_STATE.value, 409)

    second_rejection = api_client.verify_performance_record(
        record["id"], reject_performance_payload("second look"), TECHNICAL
    )
    validate_error(second_rejection, ApiErrorId.ERR_INVALID_PERFORMANCE_STATE.value,
                   409)


def test_the_original_rejection_reason_survives_both_refusals():
    """The filtered listing shows one row, still rejected, still carrying its reason.

    PRD §3.2: "An athlete's submitted performances may be listed and filtered by
    `verification_status` and `division`." The stored figure is untouched, because the
    record only ever moves `SUBMITTED → REJECTED` and "`verified_seconds` is set to
    that official figure" solely on a `VERIFIED` decision.

    Design: Corner/state_machines/corner_rejected_performance_record_is_terminal
    """
    athlete = register_athlete(country_code="USA", gender="FEMALE",
                               birth_date="1995-01-15")
    record = submit_performance(athlete["id"], race_name="Qual TM",
                                performance_date="2026-03-01",
                                performance_seconds=8_800, division="ELITE",
                                sanctioning_ref="SB-TM-1", chip_timed=True)
    reject_performance(record["id"], "course not certified")
    api_client.verify_performance_record(
        record["id"], verify_performance_payload(8_800), TECHNICAL
    )
    api_client.verify_performance_record(
        record["id"], reject_performance_payload("second look"), TECHNICAL
    )

    records, meta = validate_paginated(
        api_client.list_performance_records(
            athlete["id"], TECHNICAL, {"verification_status": "REJECTED"}
        )
    )
    assert meta["total_count"] == 1
    assert records[0]["verification_status"] == "REJECTED"
    assert records[0]["verified_seconds"] is None
    assert records[0]["rejection_reason"] == "course not certified"


def _raced_edition_with_one_provisional_result():
    """One bibbed ELITE MALE starter in a `RACED` edition, holding a provisional
    finish of 7,800 gun seconds."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Idempotency Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    entrant = enroll_accepted_invitation(
        edition_id, offer=SWEEP_OFFER, with_bib=True,
        athlete_overrides={"country_code": "USA", "whereabouts_filed": True},
        performance_overrides={"performance_seconds": 7_900},
    )
    lock_field(edition_id)
    set_clock("2026-11-01T09:00:00Z")
    mark_raced(edition_id)
    scenario["entrant"] = entrant
    scenario["result"] = enter_result(edition_id, entrant["invitation"]["id"],
                                      gun_seconds=7_800, net_seconds=7_798)
    return scenario


def test_certifying_a_result_twice_is_refused_and_leaves_the_row_alone():
    """Certification is a transition, not a setter that can be reapplied.

    PRD §3.7: "A `TechnicalOfficial` moves a result `PROVISIONAL → CERTIFIED` while
    the edition is `RACED`; a result that is not `PROVISIONAL` cannot be certified."
    PRD §2.11 priority 8 puts that refusal at HTTP 409: "**Target entity state.** The
    target entity is in a state that permits the requested transition".

    Design: Corner/state_machines/corner_double_certify_race_result_rejected_as_non_idempotent
    """
    scenario = _raced_edition_with_one_provisional_result()
    result_id = scenario["result"]["id"]

    certified = certify_result(result_id)
    assert certified["certification_status"] == "CERTIFIED"
    version_after_certification = certified["version"]

    repeat = api_client.certify_race_result(result_id, TECHNICAL)
    assert repeat.status_code == 409, (
        "CERTIFIED is not a legal from-state for certification"
    )

    assert read_result(result_id)["version"] == version_after_certification, (
        "the refused repeat did not mutate the row"
    )


def test_one_invitation_may_never_hold_a_second_result_row():
    """A fresh finish posted against the same invitation is a duplicate.

    PRD §3.7: "Only one result may exist per invitation, and a second is refused with
    `ERR_DUPLICATE_RESULT`."

    Design: Corner/state_machines/corner_double_certify_race_result_rejected_as_non_idempotent
    """
    scenario = _raced_edition_with_one_provisional_result()
    result_id = scenario["result"]["id"]
    certified = certify_result(result_id)

    duplicate = api_client.create_race_result(
        create_race_result_payload(scenario["edition"]["id"],
                                   scenario["entrant"]["invitation"]["id"],
                                   gun_seconds=7_801, net_seconds=7_799),
        TECHNICAL,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESULT.value, 409)

    surviving = read_result(result_id)
    assert surviving["version"] == certified["version"]
    assert surviving["gun_seconds"] == 7_800
    assert surviving["certification_status"] == "CERTIFIED"


def _edition_awaiting_its_ops_sweep():
    """A `FIELD_OPEN` edition holding one `OFFERED`, one `ACCEPTED` and one
    `COUNTERED` invitation, plus one uncollected and one collected test for the
    offered athlete, observed from a clock a month past every deadline."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Ops Sweep Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Sweep Sports", license_code="AGT-SW-1")
    common = {"agent": agent, "athlete_overrides": {"country_code": "USA",
                                                    "whereabouts_filed": True}}

    lapsing = enroll_offered_invitation(
        edition_id, offer=SWEEP_OFFER,
        performance_overrides={"performance_seconds": 7_900}, **common
    )
    accepted = enroll_accepted_invitation(
        edition_id, offer=SWEEP_OFFER,
        performance_overrides={"performance_seconds": 7_910}, **common
    )
    countered = enroll_offered_invitation(
        edition_id, offer=SWEEP_OFFER,
        performance_overrides={"performance_seconds": 7_920}, **common
    )
    agent_counters(
        countered["invitation"]["id"], agent["id"], appearance_fee_cents=900_000,
        air_class="BUSINESS", hotel_nights=4, ground_transport=True,
    )
    countered["invitation"] = read_invitation(countered["invitation"]["id"])

    uncollected = schedule_doping_test(
        lapsing["athlete"]["id"], edition_id, test_type="OUT_OF_COMPETITION",
        window_start_at="2026-08-10T08:00:00Z",
        window_end_at="2026-08-10T18:00:00Z", sample_code="S-SW-1",
    )
    collected = schedule_doping_test(
        lapsing["athlete"]["id"], edition_id, test_type="OUT_OF_COMPETITION",
        window_start_at="2026-08-12T08:00:00Z",
        window_end_at="2026-08-12T18:00:00Z", sample_code="S-SW-2",
    )
    collect_sample(collected["id"], "COC-SW-2", at_iso8601="2026-08-12T09:00:00Z")

    set_clock("2026-09-01T00:00:00Z")
    scenario["lapsing"] = lapsing
    scenario["accepted"] = accepted
    scenario["countered"] = countered
    scenario["uncollected"] = uncollected
    scenario["collected"] = collected
    return scenario


def test_the_sweep_expires_both_open_deals_and_spares_the_accepted_one():
    """`OFFERED` and `COUNTERED` both lapse; the accepted deal is never swept.

    PRD §3.9: "Every invitation of the edition in `OFFERED` or in `COUNTERED` whose
    `response_deadline_at` lies strictly before the logical clock moves to `EXPIRED`,
    and the edition's `expired_offer_count` grows by one for each." The accepted
    invitation keeps the valuation frozen at acceptance, which PRD §3.4 builds from
    "a flat allowance keyed to `current_air_class`: 120,000 cents for `ECONOMY`" and a
    hotel component of "32,000 cents per night multiplied by the number of nights".

    Design: Corner/state_machines/corner_run_ops_sweep_cascades_expiry_and_missed_tests
    """
    scenario = _edition_awaiting_its_ops_sweep()

    swept = run_ops(scenario["edition"]["id"])
    assert swept["expired_offer_count"] == 2

    assert read_invitation(scenario["lapsing"]["invitation"]["id"])["status"] == (
        "EXPIRED"
    )
    assert read_invitation(scenario["countered"]["invitation"]["id"])["status"] == (
        "EXPIRED"
    )

    accepted = read_invitation(scenario["accepted"]["invitation"]["id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["guaranteed_commitment_cents"] == 884_000, (
        "700,000 fee plus 120,000 economy air plus two nights at 32,000"
    )


def test_the_sweep_misses_the_uncollected_test_and_recomputes_the_ledger():
    """The second and third steps run in the same call as the first.

    PRD §3.9: "Every doping test in `SCHEDULED` whose `window_end_at` lies strictly
    before the logical clock moves to `MISSED`, and for each one the athlete's
    `missed_test_count` is incremented and the athlete's `version` is incremented with
    it." PRD §3.6 confirms the sweep is the only such path: "Overdue tests are not
    resolved by adjudication but by the operational sweep of §3.9, which moves a
    `SCHEDULED` test past its window end to `MISSED`." PRD §3.9 then "recomputes the
    edition's ledger projections in full".

    Design: Corner/state_machines/corner_run_ops_sweep_cascades_expiry_and_missed_tests
    """
    scenario = _edition_awaiting_its_ops_sweep()

    swept = run_ops(scenario["edition"]["id"])
    assert swept["appearance_committed_cents"] == 884_000, (
        "the two expiries contributed nothing to the recomputed ledger"
    )
    assert swept["appearance_uncommitted_cents"] == 8_116_000

    assert read_doping_test(scenario["uncollected"]["id"])["status"] == "MISSED"
    assert read_doping_test(scenario["collected"]["id"], LIAISON)["status"] == (
        "COLLECTED"
    ), "a collected test is outside the sweep's input set"

    athlete = read_athlete(scenario["lapsing"]["athlete"]["id"])
    assert athlete["missed_test_count"] == 1
