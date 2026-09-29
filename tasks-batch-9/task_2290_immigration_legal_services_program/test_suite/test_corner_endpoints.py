"""Breadth tests for the shape of the endpoint surface itself.

The CRUD surface (there is exactly one PATCH and no DELETE anywhere), the
pagination envelope, the two multi-row sweeps, the link-only relink write, the
computed single read, and the conditional endpoints whose behaviour depends on
the row they land on rather than on the payload they carry.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_ASSIGNMENT_NOT_ACTIVE,
    ERR_BLOCKING_EVIDENCE_OUTSTANDING,
    ERR_FACILITY_CHANGE_AFTER_FILING,
    ERR_FACILITY_REQUIRED_FOR_DETAINED,
    ERR_MATTER_NOT_READY,
    ERR_SUPERVISION_LINK_INELIGIBLE,
    ERR_SUPERVISION_LINK_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_data_blocks_identical,
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_no_rows,
    assert_null_fields,
    assert_row_count,
    created,
    ok,
    only_row,
    rows,
)
from test_helpers.fixtures import (
    accept_intake,
    add_evidence,
    add_supervisor_assignment,
    drive_evidence,
    minimal_world,
    new_client,
    set_clock,
    template_a,
    template_b,
)
from test_helpers.test_users import (
    make_supervising_attorney_headers,
    program_director_headers,
)

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"
_MISSING_LINK_ID = "00000000-0000-4000-8000-000000000111"


# ---------------------------------------------------------------------------
# standard_crud_on_representatives_including_patch_recompute_and_pagination
# ---------------------------------------------------------------------------


def _three_representatives(api):
    """One of each supervision shape, created in a fixed order for pagination."""
    director = program_director_headers()
    ok(api.set_clock(_CLOCK_UTC, headers=director))
    ada = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Ada Ortiz",
                languages=["en", "es"],
                max_case_load=25,
                max_supervisees=10,
                bar_number="BAR-1001",
            ),
            headers=director,
        )
    )
    vic = created(
        api.create_representative(
            factories.volunteer_payload(
                full_name="Vic Lang",
                languages=["en"],
                max_case_load=5,
                max_supervisees=0,
            ),
            headers=director,
        )
    )
    gus = created(
        api.create_representative(
            factories.law_graduate_payload(
                full_name="Gus Reed",
                languages=["en"],
                max_case_load=5,
                max_supervisees=0,
            ),
            headers=director,
        )
    )
    return director, ada, vic, gus


def test_the_create_response_already_carries_every_derived_representative_field(api):
    """201 with the derived ladder resolved, and the single read reproduces it.

    ``authorization_status`` and ``supervision_required`` are never supplied, and
    the single read is a pure echo: no field of the create response is allowed to
    change when the row is fetched back with no write in between.

    Design: Corner/endpoints/standard_crud_on_representatives_including_patch_recompute_and_pagination
    """
    director, ada, vic, _gus = _three_representatives(api)

    assert_fields(
        ada,
        full_name="Ada Ortiz",
        rep_type="STAFF_ATTORNEY",
        languages=["en", "es"],
        max_case_load=25,
        max_supervisees=10,
        bar_number="BAR-1001",
        status="ACTIVE",
        authorization_status="AUTHORIZED_ATTORNEY",
        supervision_required=False,
        active_case_load=0,
        supervisee_count=0,
        version=1,
    )
    assert_decimal_equals(ada["weekly_capacity_hours"], "40.00", 2)
    assert_data_blocks_identical(
        ada,
        ok(api.get_representative(ada["id"], headers=director)),
        label="representative create vs single read",
    )

    # A volunteer never reaches the attorney rungs of the same ladder.
    assert_fields(
        vic,
        rep_type="PRO_BONO_VOLUNTEER",
        supervision_required=True,
        authorization_status="AUTHORIZED_SUPERVISED",
        bar_number=None,
    )


def test_pagination_reports_the_filtered_total_and_patch_recomputes_in_place(api):
    """limit/offset slice the page while total_count always describes the filter.

    There is no DELETE anywhere on this surface, so retirement is a status PATCH
    -- and that PATCH must return the re-derived ``authorization_status`` in its
    own response body rather than leaving it for the next read.

    Design: Corner/endpoints/standard_crud_on_representatives_including_patch_recompute_and_pagination
    """
    director, ada, vic, _gus = _three_representatives(api)

    first_page = api.list_representatives(params={"limit": 2, "offset": 0}, headers=director)
    assert len(rows(first_page)) == 2
    assert_row_count(first_page, 3)
    assert first_page.json()["meta"]["has_more"] is True

    second_page = api.list_representatives(params={"limit": 2, "offset": 2}, headers=director)
    assert len(rows(second_page)) == 1
    assert_row_count(second_page, 3)
    assert second_page.json()["meta"]["has_more"] is False

    filtered = api.list_representatives(
        params={"rep_type": "STAFF_ATTORNEY"}, headers=director
    )
    assert_row_count(filtered, 1)
    assert only_row(filtered)["full_name"] == "Ada Ortiz"

    widened = ok(
        api.update_representative(
            ada["id"],
            {"max_case_load": 30, "languages": ["en", "es", "pt"]},
            headers=director,
        )
    )
    assert_fields(
        widened,
        max_case_load=30,
        languages=["en", "es", "pt"],
        version=2,
        authorization_status="AUTHORIZED_ATTORNEY",
    )

    retired = ok(
        api.update_representative(vic["id"], {"status": "INACTIVE"}, headers=director)
    )
    assert_fields(retired, status="INACTIVE", authorization_status="UNAUTHORIZED")


# ---------------------------------------------------------------------------
# checkpoint_phase_order_is_normative_and_the_sweep_is_idempotent_at_a_fixed_clock
# ---------------------------------------------------------------------------

_SWEEP_CLOCK_UTC = "2026-09-04T09:00:00.000Z"


def _waitlist_a_client(env, full_name, dob):
    """Screen a fresh client's U_VISA intake and put it on the waitlist."""
    client_id = new_client(
        env,
        full_name=full_name,
        preferred_language_code="es",
        country_of_birth_code="GT",
        date_of_birth=dob,
        household_size=1,
        annual_household_income_cents=1000000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    intake = created(
        env.api.create_intake(
            factories.intake_payload(
                client_id,
                env["cycle_id"],
                case_type="U_VISA",
                detained=False,
                statutory_deadline_date="2026-12-01",
            ),
            headers=env.screener,
        )
    )
    ok(env.api.screen_intake(intake["id"], headers=env.screener))
    waitlisted = ok(
        env.api.decide_intake(
            intake["id"],
            {"decision": "WAITLIST", "decision_reason_code": "CAPACITY_FULL"},
            headers=env.supervisor,
        )
    )
    return waitlisted


def _document_withdraw_decision(env, matter_id, assignment_id):
    """Record and have the client acknowledge a WITHDRAW_CASE counseling record."""
    decision = created(
        env.api.create_informed_decision(
            factories.informed_decision_payload(
                matter_id,
                assignment_id,
                env.matter_version(matter_id),
                decision_type="WITHDRAW_CASE",
                counseling_language_code="es",
            ),
            headers=env.rep_headers(env["atty_a_id"]),
        )
    )
    ok(
        env.api.transition_informed_decision(
            decision["id"], {"action": "ACKNOWLEDGE"}, headers=env.portal
        )
    )
    return decision["id"]


def _one_free_seat_and_two_waitlisted_rows(api):
    """A full 2-slot cycle, one expired and one live waitlisted row, one free seat.

    The seat is freed by withdrawing the organization from a matter, which is the
    one closure path that explicitly does not promote anyone from the waitlist --
    so whatever promotion happens later is attributable to the sweep alone.

    TEMPLATE B rather than TEMPLATE A because the withdrawal is gated on a
    counseling record, and PRD 3.8 requires that "The matter must already carry at
    least one CERTIFIED declaration, otherwise ERR_DECLARATION_NOT_CERTIFIED".
    """
    env = template_b(
        api, clock=_CLOCK_UTC, total_case_slots=2, reserved_detained_slots=0
    )
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
    accept_intake(env, bea_id, case_type="U_VISA", detained=False)
    assert_fields(env.cycle(), general_slots_consumed=2, available_slot_count=0)

    w1 = _waitlist_a_client(env, "Cyd Mora", "1991-05-05")
    assert_fields(
        w1,
        status="WAITLISTED",
        waitlist_rank=1,
        waitlist_expires_at_utc="2026-09-02T09:00:00.000Z",
    )

    set_clock(api, _SWEEP_CLOCK_UTC)
    w2 = _waitlist_a_client(env, "Dov Sarr", "1992-06-06")
    assert_fields(
        w2,
        status="WAITLISTED",
        waitlist_rank=2,
        waitlist_expires_at_utc="2026-10-04T09:00:00.000Z",
    )

    _document_withdraw_decision(env, env["matter_id"], env["lead_id"])
    ok(
        api.withdraw_representation(
            env["matter_id"],
            {"reason_code": "CLIENT_REQUEST"},
            headers=env.supervisor,
        )
    )
    assert_fields(
        env.cycle(),
        general_slots_consumed=1,
        available_slot_count=1,
        waitlisted_count=2,
        capacity_posture="OPEN",
    )
    env.set(w1_id=w1["id"], w2_id=w2["id"])
    return env


def test_expiry_runs_before_promotion_so_the_expired_rank_one_row_is_skipped(api):
    """One free seat, two waitlisted rows, and the lower rank must not win it.

    W1 holds rank 1 but its window closed two days before the sweep runs, so
    phase 1 retires it and phase 2 can only see W2 -- which is promoted, mints a
    matter and takes the cycle straight back to a frozen 1.0000. Reversing the
    phases would have promoted W1 instead.

    Design: Corner/endpoints/checkpoint_phase_order_is_normative_and_the_sweep_is_idempotent_at_a_fixed_clock
    """
    env = _one_free_seat_and_two_waitlisted_rows(api)

    ok(api.checkpoint_cycle(env["cycle_id"], headers=env.director))

    expired = env.intake(env["w1_id"])
    assert_fields(expired, status="WAITLIST_EXPIRED")
    # Phase 1 clears exactly one field: PRD 3.10 says the row "moves to
    # WAITLIST_EXPIRED, its waitlist_rank is cleared, and the remaining waitlisted
    # rows are re-ranked" -- unlike the withdrawal branch of PRD 3.4, which names
    # both waitlist_rank and waitlist_expires_at_utc. The expiry stamp is left
    # alone here because nothing in the PRD asks phase 1 to erase it.
    assert_null_fields(expired, "waitlist_rank")
    assert_no_rows(
        api.list_matters(params={"intake_id": env["w1_id"]}, headers=env.director)
    )

    promoted = env.intake(env["w2_id"])
    assert_fields(
        promoted, status="ACCEPTED", decision_reason_code="ACCEPTED_ON_MERIT",
        decided_at_utc=_SWEEP_CLOCK_UTC,
    )
    assert_null_fields(promoted, "waitlist_rank", "waitlist_expires_at_utc")
    minted = only_row(
        api.list_matters(params={"intake_id": env["w2_id"]}, headers=env.director)
    )
    assert_fields(minted, filing_status="PRE_FILING", representation_status="UNSTAFFED")

    cycle = env.cycle()
    assert_fields(
        cycle,
        general_slots_consumed=2,
        detained_slots_consumed=0,
        available_slot_count=0,
        waitlisted_count=0,
        capacity_posture="FROZEN",
        checkpoint_epoch=2,
        last_checkpoint_utc=_SWEEP_CLOCK_UTC,
    )
    assert_decimal_equals(cycle["utilization_ratio"], "1.0000", 4)


def test_a_second_sweep_at_the_same_clock_moves_only_the_epoch(api):
    """Idempotent here means state-idempotent, not response-identical.

    Nothing is left for either phase to do, so no intake, matter or client moves
    a second time -- yet the epoch still increments, because it counts sweeps
    rather than changes.

    Design: Corner/endpoints/checkpoint_phase_order_is_normative_and_the_sweep_is_idempotent_at_a_fixed_clock
    """
    env = _one_free_seat_and_two_waitlisted_rows(api)
    ok(api.checkpoint_cycle(env["cycle_id"], headers=env.director))

    w1_before = env.intake(env["w1_id"])
    w2_before = env.intake(env["w2_id"])
    matter_before = only_row(
        api.list_matters(params={"intake_id": env["w2_id"]}, headers=env.director)
    )

    swept = ok(api.checkpoint_cycle(env["cycle_id"], headers=env.director))
    assert_fields(
        swept, checkpoint_epoch=3, last_checkpoint_utc=_SWEEP_CLOCK_UTC,
        waitlisted_count=0, available_slot_count=0,
    )
    assert_data_blocks_identical(w1_before, env.intake(env["w1_id"]), label="W1")
    assert_data_blocks_identical(w2_before, env.intake(env["w2_id"]), label="W2")
    assert_data_blocks_identical(
        matter_before,
        only_row(
            api.list_matters(params={"intake_id": env["w2_id"]}, headers=env.director)
        ),
        label="the promoted matter",
    )


# ---------------------------------------------------------------------------
# cross_reference_link_relink_supervision_moves_the_counter_between_two_supervisors
# ---------------------------------------------------------------------------


def _supervised_volunteer_world(api, with_proposed_second=False):
    """A Spanish-speaking client, three SUPERVISOR rows and one supervised LEAD.

    Bram Adler speaks only English, so he is outside the candidate pool for this
    client even though every other clause passes for him -- which is what makes
    him the right target for the eligibility probe. Cleo Park and Elsa Vidal are
    identical on the first three ordering keys, so the auto-selector must fall
    through to ``created_at`` and pick Cleo.
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        cycle_label="FY26-H2",
        period_start_date="2026-07-01",
        period_end_date="2026-12-31",
        total_case_slots=20,
        reserved_detained_slots=4,
        languages=["en", "es"],
    )
    supervisors = {}
    for key, name, languages in (
        ("cleo_id", "Cleo Park", ["en", "es"]),
        ("bram_id", "Bram Adler", ["en"]),
        ("elsa_id", "Elsa Vidal", ["en", "es"]),
    ):
        row = created(
            api.create_representative(
                factories.staff_attorney_payload(
                    full_name=name,
                    languages=languages,
                    max_case_load=25,
                    max_supervisees=10,
                ),
                headers=env.director,
            )
        )
        supervisors[key] = row["id"]
    volunteers = {}
    for key, name in (("vic_id", "Vic Lang"), ("wes_id", "Wes Duro")):
        row = created(
            api.create_representative(
                factories.volunteer_payload(
                    full_name=name,
                    languages=["en", "es"],
                    max_case_load=5,
                    max_supervisees=0,
                ),
                headers=env.director,
            )
        )
        volunteers[key] = row["id"]

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
    matter = accept_intake(env, client_id, case_type="U_VISA", detained=False)
    env.set(client_id=client_id, matter_id=matter["id"], **supervisors)
    env.set(**volunteers)

    env.set(
        cleo_sup_id=add_supervisor_assignment(env, supervisors["cleo_id"]),
        bram_sup_id=add_supervisor_assignment(env, supervisors["bram_id"]),
        elsa_sup_id=add_supervisor_assignment(env, supervisors["elsa_id"]),
    )

    vic_cc = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                volunteers["vic_id"],
                env.matter_version(),
                role_on_case="CO_COUNSEL",
            ),
            headers=env.supervisor,
        )
    )
    ok(
        api.transition_assignment(
            vic_cc["id"], {"action": "ACTIVATE"}, headers=env.supervisor
        )
    )
    env.set(vic_cc_id=vic_cc["id"])
    if with_proposed_second:
        wes_cc = created(
            api.create_assignment(
                factories.assignment_payload(
                    matter["id"],
                    volunteers["wes_id"],
                    env.matter_version(),
                    role_on_case="CO_COUNSEL",
                ),
                headers=env.supervisor,
            )
        )
        env.set(wes_cc_id=wes_cc["id"])
    return env


def test_an_explicit_link_is_held_to_the_full_auto_selection_predicate(api):
    """The client-language clause binds an explicitly named supervisor too.

    Bram Adler is a live, authorized, uncapped staff attorney holding an ACTIVE
    SUPERVISOR row on this very matter, and the only clause he fails is the
    client's Spanish -- so the ineligibility id is attributable to that clause
    alone. The other two guards are separable: a still-PROPOSED assignment
    reports the activity id, and a link that resolves to nothing reports its own
    404.

    Design: Corner/endpoints/cross_reference_link_relink_supervision_moves_the_counter_between_two_supervisors
    """
    env = _supervised_volunteer_world(api, with_proposed_second=True)

    assert_fields(
        env.assignment(env["vic_cc_id"]),
        status="ACTIVE",
        supervision_link_id=env["cleo_sup_id"],
        supervision_source="AUTO_SELECTED",
    )
    assert_fields(env.representative(env["cleo_id"]), supervisee_count=1)
    assert_fields(env.representative(env["bram_id"]), supervisee_count=0)

    assert_error(
        api.relink_supervision(
            env["vic_cc_id"],
            {"supervision_link_id": env["bram_sup_id"]},
            headers=env.supervisor,
        ),
        ERR_SUPERVISION_LINK_INELIGIBLE,
    )
    assert_fields(
        env.assignment(env["vic_cc_id"]),
        supervision_link_id=env["cleo_sup_id"],
        supervision_source="AUTO_SELECTED",
    )
    assert_fields(env.representative(env["cleo_id"]), supervisee_count=1)

    assert_error(
        api.relink_supervision(
            env["wes_cc_id"],
            {"supervision_link_id": env["cleo_sup_id"]},
            headers=env.supervisor,
        ),
        ERR_ASSIGNMENT_NOT_ACTIVE,
    )
    assert_error(
        api.relink_supervision(
            env["vic_cc_id"],
            {"supervision_link_id": _MISSING_LINK_ID},
            headers=env.supervisor,
        ),
        ERR_SUPERVISION_LINK_NOT_FOUND,
    )
    assert_fields(
        env.assignment(env["vic_cc_id"]), supervision_link_id=env["cleo_sup_id"]
    )


def test_relinking_conserves_the_supervisee_count_across_the_two_supervisors(api):
    """One write decrements the old supervisor and increments the new one.

    The sum over all supervisors stays at 1 -- the volunteer is supervised
    exactly once throughout -- and the link stops being an auto-selection, which
    is the whole point of the escape hatch: the previously selected supervisor
    can now be released.

    Design: Corner/endpoints/cross_reference_link_relink_supervision_moves_the_counter_between_two_supervisors
    """
    env = _supervised_volunteer_world(api)
    assignment_version = env.assignment(env["vic_cc_id"])["version"]
    cleo_version = env.representative(env["cleo_id"])["version"]
    elsa_version = env.representative(env["elsa_id"])["version"]
    assert_fields(env.representative(env["elsa_id"]), supervisee_count=0)

    relinked = ok(
        api.relink_supervision(
            env["vic_cc_id"],
            {"supervision_link_id": env["elsa_sup_id"]},
            headers=env.supervisor,
        )
    )
    assert_fields(
        relinked,
        supervision_link_id=env["elsa_sup_id"],
        supervision_source="EXPLICIT_LINK",
        version=assignment_version + 1,
    )
    assert_fields(
        env.representative(env["cleo_id"]),
        supervisee_count=0,
        version=cleo_version + 1,
    )
    assert_fields(
        env.representative(env["elsa_id"]),
        supervisee_count=1,
        version=elsa_version + 1,
    )


# ---------------------------------------------------------------------------
# computed_read_case_matter_exposes_both_dimensions_readiness_money_and_the_occ_token
# ---------------------------------------------------------------------------


def _matter_with_every_rollup_populated(api):
    """TEMPLATE B plus one VERIFIED required item, one REJECTED item and two hour logs.

    The two evidence rows are chosen so that the weighted numerator and the
    blocking count disagree: the rejected row is only SUPPORTING, so it drags the
    denominator and the blocking count without touching the strict checklist.
    """
    env = template_b(api, clock=_CLOCK_UTC)
    good_id, = add_evidence(env, [10], tier="REQUIRED", item_type="IDENTITY_DOCUMENT")
    drive_evidence(env, good_id, "RECEIVE", "VERIFY")
    bad_id, = add_evidence(env, [5], tier="SUPPORTING", item_type="MEDICAL_RECORD")
    drive_evidence(env, bad_id, "RECEIVE")
    drive_evidence(env, bad_id, "REJECT", disposition_reason_code="ILLEGIBLE")
    ok(
        api.log_hours(
            env["lead_id"],
            {"hours": "3.50", "hours_kind": "DIRECT", "service_date": "2026-08-03"},
            headers=env.lead_rep,
        )
    )
    ok(
        api.log_hours(
            env["cocounsel_id"],
            {"hours": "1.25", "hours_kind": "DIRECT", "service_date": "2026-08-03"},
            headers=env.supervisor,
        )
    )
    env.set(good_evidence_id=good_id, bad_evidence_id=bad_id)
    return env


def test_one_matter_read_carries_both_dimensions_the_rollups_and_the_occ_token(api):
    """The read computes nothing: every figure was fixed by an earlier write.

    The rollup is the load-bearing part -- 4.75 direct hours live on no single
    assignment, they are the sum of 3.50 on the LEAD and 1.25 on the CO_COUNSEL --
    and the version this read reports is accepted verbatim as the
    expected_matter_version of a decision write, which is what makes it the OCC
    token rather than an incidental counter.

    Design: Corner/endpoints/computed_read_case_matter_exposes_both_dimensions_readiness_money_and_the_occ_token
    """
    env = _matter_with_every_rollup_populated(api)

    matter = env.matter()
    assert_fields(
        matter,
        representation_status="STAFFED",
        filing_status="PRE_FILING",
        forum="USCIS",
        detained=False,
        readiness_ready_strict=True,
        evidence_blocking_count=1,
        interpretation_cost_cents=7125,
    )
    assert_null_fields(matter, "facility_id")
    # 10 verified points over the 15 counted points of both rows.
    assert_decimal_equals(matter["readiness_index_weighted"], "0.6667", 4)
    assert_decimal_equals(matter["direct_hours_logged"], "4.75", 2)
    assert_decimal_equals(matter["supervision_hours_logged"], "0.00", 2)

    listed = rows(api.list_evidence(params={"matter_id": env["matter_id"]}, headers=env.director))
    assert_row_count(
        api.list_evidence(params={"matter_id": env["matter_id"]}, headers=env.director), 2
    )
    by_id = {row["id"]: row for row in listed}
    assert_fields(by_id[env["good_evidence_id"]], status="VERIFIED", weight_points=10)
    assert_fields(by_id[env["bad_evidence_id"]], status="REJECTED", weight_points=5)

    occ_token = matter["version"]
    decision = created(
        api.create_informed_decision(
            factories.informed_decision_payload(
                env["matter_id"],
                env["lead_id"],
                occ_token,
                decision_type="FILE_AFFIRMATIVE",
                counseling_language_code="es",
            ),
            headers=env.lead_rep,
        )
    )
    assert_fields(decision, status="PENDING", language_match_verified=True)
    assert_null_fields(decision, "superseded_by_decision_id")
    assert env.matter()["version"] == occ_token + 1


# ---------------------------------------------------------------------------
# conditional_action_posture_override_only_downgrades_and_only_while_it_lasts
# ---------------------------------------------------------------------------

_OVERRIDE_UNTIL_UTC = "2026-08-10T00:00:00.000Z"


def _accept_routine(env, full_name, date_of_birth):
    """A ROUTINE non-detained U_VISA acceptance -- legal only while OPEN."""
    client_id = new_client(
        env,
        full_name=full_name,
        date_of_birth=date_of_birth,
        preferred_language_code="es",
        country_of_birth_code="GT",
        household_size=3,
        annual_household_income_cents=2000000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    return accept_intake(env, client_id, case_type="U_VISA", detained=False)


def _accept_urgent(env, full_name, date_of_birth):
    """An URGENT non-detained acceptance -- 42 for BOND_HEARING, 15 for the minor
    flag and 22.50 for a 21-day statutory horizon give 79.50, which is URGENT and
    therefore admissible under a RESTRICTED posture."""
    client_id = new_client(
        env,
        full_name=full_name,
        date_of_birth=date_of_birth,
        preferred_language_code="es",
        country_of_birth_code="GT",
        household_size=3,
        annual_household_income_cents=2000000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    return accept_intake(
        env,
        client_id,
        case_type="BOND_HEARING",
        detained=False,
        unaccompanied_minor=True,
        statutory_deadline_date="2026-08-24",
    )


def _cycle_at_eight_of_ten(api):
    """Ten general seats with eight consumed, so the ratio is exactly 0.8000."""
    env = template_a(
        api, clock=_CLOCK_UTC, total_case_slots=10, reserved_detained_slots=0
    )
    for index in range(7):
        _accept_routine(env, "Fill Uno{0}".format(index), "1990-01-0{0}".format(index + 1))
    return env


def _cycle_at_ten_of_ten(api):
    """The same cycle filled to the brim through two URGENT acceptances."""
    env = _cycle_at_eight_of_ten(api)
    _accept_urgent(env, "Urg Nine", "1992-05-09")
    _accept_urgent(env, "Urg Ten", "1992-05-10")
    return env


def test_an_override_that_changes_nothing_still_bumps_the_version(api):
    """Neither a restricted cycle nor an instant equal to the clock gains anything.

    The first call lands on a computed RESTRICTED posture, which the override is
    forbidden to soften further; the second names the logical clock itself, which
    is not strictly after the clock, so the freeze stands. Both are accepted with
    200 and both advance version, which is how the audit trail keeps the
    director's intervention even when the posture label never moved.

    Design: Corner/endpoints/conditional_action_posture_override_only_downgrades_and_only_while_it_lasts
    """
    env = _cycle_at_eight_of_ten(api)
    before = env.cycle()
    assert_decimal_equals(before["utilization_ratio"], "0.8000", 4)
    assert_fields(before, capacity_posture="RESTRICTED", general_slots_consumed=8)

    softened = ok(
        api.posture_override(
            env["cycle_id"],
            {
                "posture_override_until_utc": _OVERRIDE_UNTIL_UTC,
                "override_reason_code": "DIRECTOR_DISCRETION",
            },
            headers=env.director,
        )
    )
    assert_fields(
        softened,
        capacity_posture="RESTRICTED",
        posture_override_until_utc=_OVERRIDE_UNTIL_UTC,
        version=before["version"] + 1,
    )
    assert_decimal_equals(softened["utilization_ratio"], "0.8000", 4)

    _accept_urgent(env, "Urg Nine", "1992-05-09")
    _accept_urgent(env, "Urg Ten", "1992-05-10")
    full = env.cycle()
    assert_decimal_equals(full["utilization_ratio"], "1.0000", 4)
    assert_fields(full, capacity_posture="RESTRICTED", available_slot_count=0)

    expired_on_arrival = ok(
        api.posture_override(
            env["cycle_id"],
            {
                "posture_override_until_utc": _CLOCK_UTC,
                "override_reason_code": "DIRECTOR_DISCRETION",
            },
            headers=env.director,
        )
    )
    assert_fields(
        expired_on_arrival,
        capacity_posture="FROZEN",
        posture_override_until_utc=_CLOCK_UTC,
        version=full["version"] + 1,
    )
    assert_decimal_equals(expired_on_arrival["utilization_ratio"], "1.0000", 4)
    assert_decimal_equals(env.cycle()["utilization_ratio"], "1.0000", 4)


def test_the_downgrade_expires_by_the_clock_alone_with_no_further_call(api):
    """The stored instant stays on the row while the grant it once carried lapses.

    The last millisecond before the instant still reports RESTRICTED and the
    instant itself reports FROZEN again -- reached, not merely passed -- and
    nothing but two clock writes happened in between, so the posture is a
    function of the clock rather than a latched flag.

    Design: Corner/endpoints/conditional_action_posture_override_only_downgrades_and_only_while_it_lasts
    """
    env = _cycle_at_ten_of_ten(api)
    frozen = env.cycle()
    assert_fields(frozen, capacity_posture="FROZEN")
    assert_null_fields(frozen, "posture_override_until_utc")

    ok(
        api.posture_override(
            env["cycle_id"],
            {
                "posture_override_until_utc": _OVERRIDE_UNTIL_UTC,
                "override_reason_code": "DIRECTOR_DISCRETION",
            },
            headers=env.director,
        )
    )
    assert_fields(env.cycle(), capacity_posture="RESTRICTED")

    set_clock(api, "2026-08-09T23:59:59.999Z")
    assert_fields(env.cycle(), capacity_posture="RESTRICTED")

    set_clock(api, _OVERRIDE_UNTIL_UTC)
    lapsed = env.cycle()
    assert_fields(
        lapsed,
        capacity_posture="FROZEN",
        posture_override_until_utc=_OVERRIDE_UNTIL_UTC,
    )
    assert_decimal_equals(lapsed["utilization_ratio"], "1.0000", 4)


# ---------------------------------------------------------------------------
# set_facility_recompute_flips_both_the_deadline_and_the_readiness_gate_error_id
# ---------------------------------------------------------------------------


def _detained_matter_short_of_both_gates(api):
    """A detained EOIR matter at 0.7143 weighted readiness with one required item open.

    The three weights are chosen so the matter fails BOTH gates at once: 20
    verified points over 28 counted points is short of 0.7500, and the third item
    sitting at RECEIVED keeps the strict checklist open. That is what makes the
    pair of error ids attributable to the gate selection alone.
    """
    director = program_director_headers()
    set_clock(api, _CLOCK_UTC)
    facility = created(
        api.create_facility(
            factories.facility_payload(
                jurisdiction_code="TX-ELP",
                expedited_filing_days=21,
                max_daily_visit_slots=4,
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
        intake_fields={"statutory_deadline_date": "2026-09-30"},
    )
    env.set(facility_id=facility["id"])
    verified_a, verified_b, still_open = add_evidence(
        env, [10, 10, 8], tier="REQUIRED"
    )
    for item_id in (verified_a, verified_b, still_open):
        drive_evidence(env, item_id, "RECEIVE")
    drive_evidence(env, verified_a, "VERIFY")
    drive_evidence(env, verified_b, "VERIFY")
    ok(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "EVIDENCE_GATHERING"},
            headers=env.lead_rep,
        )
    )
    env.set(open_evidence_id=still_open)
    return env


def test_a_detained_matter_is_refused_the_weighted_gate_and_a_faceless_redetention(api):
    """Two independent refusals on the same matter, neither of which touches version.

    The expedited deadline is the decision date plus the facility's 21 days, and
    it beats the statutory bar, so the matter is governed by a deadline no
    screening ever supplied. The re-detention attempt then proves that the
    matter's own facility is not silently reused to satisfy the payload's missing
    facility_id.

    Design: Corner/endpoints/set_facility_recompute_flips_both_the_deadline_and_the_readiness_gate_error_id
    """
    env = _detained_matter_short_of_both_gates(api)

    before = env.matter()
    assert_fields(
        before,
        detained=True,
        facility_id=env["facility_id"],
        forum="EOIR_IMMIGRATION_COURT",
        filing_status="EVIDENCE_GATHERING",
        statutory_deadline_date="2026-09-30",
        expedited_deadline_date="2026-08-24",
        effective_filing_deadline_date="2026-08-24",
        readiness_ready_strict=False,
        evidence_blocking_count=1,
    )
    assert_decimal_equals(before["readiness_index_weighted"], "0.7143", 4)

    assert_error(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "READY_TO_FILE"},
            headers=env.lead_rep,
        ),
        ERR_MATTER_NOT_READY,
    )
    assert_fields(env.matter(), filing_status="EVIDENCE_GATHERING")

    assert_error(
        api.set_facility(env["matter_id"], {"detained": True}, headers=env.supervisor),
        ERR_FACILITY_REQUIRED_FOR_DETAINED,
    )
    assert_fields(
        env.matter(),
        detained=True,
        facility_id=env["facility_id"],
        version=before["version"],
    )


def test_releasing_detention_rewrites_the_deadline_and_swaps_the_error_id(api):
    """Byte-identical evidence, a different refusal -- purely because detained flipped.

    Nothing about the evidence changes across the release: the weighted index is
    still 0.7143 and the blocking count is still 1. What changes is which gate the
    next advance consults, and the endpoint records that choice in
    readiness_gate_applied even though the advance has not been attempted yet.

    Design: Corner/endpoints/set_facility_recompute_flips_both_the_deadline_and_the_readiness_gate_error_id
    """
    env = _detained_matter_short_of_both_gates(api)
    before = env.matter()

    released = ok(
        api.set_facility(env["matter_id"], {"detained": False}, headers=env.supervisor)
    )
    assert_fields(
        released,
        detained=False,
        forum="EOIR_IMMIGRATION_COURT",
        effective_filing_deadline_date="2026-09-30",
        readiness_gate_applied="CHECKLIST_STRICT_GATE",
        evidence_blocking_count=1,
        readiness_ready_strict=False,
        version=before["version"] + 1,
    )
    assert_null_fields(released, "facility_id", "expedited_deadline_date")
    assert_decimal_equals(released["readiness_index_weighted"], "0.7143", 4)

    assert_error(
        api.advance_filing(
            env["matter_id"],
            {"target_filing_status": "READY_TO_FILE"},
            headers=env.lead_rep,
        ),
        ERR_BLOCKING_EVIDENCE_OUTSTANDING,
    )
    assert_fields(env.matter(), filing_status="EVIDENCE_GATHERING")


# ---------------------------------------------------------------------------
# advance_filing_mints_a_filing_deadline_event_discoverable_only_through_the_list_endpoint
# ---------------------------------------------------------------------------

_RFE_DUE_DATE = "2026-10-15"


def _filed_matter(api):
    """A non-detained U_VISA matter driven all the way to FILED.

    One VERIFIED required item satisfies the strict checklist gate, and the
    FILE_AFFIRMATIVE decision is acknowledged by the client so that it reaches
    DOCUMENTED -- the filing edge accepts nothing less.
    """
    env = template_b(
        api, clock=_CLOCK_UTC, intake_fields={"statutory_deadline_date": "2026-12-01"}
    )
    item_id, = add_evidence(env, [10], tier="REQUIRED")
    drive_evidence(env, item_id, "RECEIVE", "VERIFY")
    decision = created(
        api.create_informed_decision(
            factories.informed_decision_payload(
                env["matter_id"],
                env["lead_id"],
                env.matter_version(),
                decision_type="FILE_AFFIRMATIVE",
                counseling_language_code="es",
            ),
            headers=env.lead_rep,
        )
    )
    ok(
        api.transition_informed_decision(
            decision["id"], {"action": "ACKNOWLEDGE"}, headers=env.portal
        )
    )
    for target in ("EVIDENCE_GATHERING", "READY_TO_FILE", "FILED"):
        ok(
            api.advance_filing(
                env["matter_id"],
                {"target_filing_status": target},
                headers=env.lead_rep,
            )
        )
    env.set(decision_id=decision["id"], verified_evidence_id=item_id)
    return env


def _filing_deadline_events(env):
    return rows(
        env.api.list_events(
            params={"matter_id": env["matter_id"], "event_type": "FILING_DEADLINE"},
            headers=env.director,
        )
    )


def test_the_rfe_edge_is_the_only_author_of_a_filing_deadline_event(api):
    """The initial filing mints nothing; the RFE receipt mints exactly one row.

    The transition response is a CaseMatter both times, so the event is invisible
    to the caller that caused it -- the list endpoint filtered on matter_id is the
    only channel through which it can be observed at all, and the row arrives at
    version 1 with the zero travel buffer its type dictates.

    Design: Corner/endpoints/advance_filing_mints_a_filing_deadline_event_discoverable_only_through_the_list_endpoint
    """
    env = _filed_matter(api)
    assert_fields(env.matter(), filing_status="FILED")
    assert_no_rows(
        api.list_events(
            params={"matter_id": env["matter_id"], "event_type": "FILING_DEADLINE"},
            headers=env.director,
        )
    )

    advanced = ok(
        api.advance_filing(
            env["matter_id"],
            {
                "target_filing_status": "RFE_PENDING",
                "rfe_response_due_date": _RFE_DUE_DATE,
            },
            headers=env.lead_rep,
        )
    )
    assert_fields(
        advanced,
        filing_status="RFE_PENDING",
        statutory_deadline_date=_RFE_DUE_DATE,
        effective_filing_deadline_date=_RFE_DUE_DATE,
    )
    assert "event_type" not in advanced, "the advance response is a matter, not an event"

    minted = only_row(
        api.list_events(
            params={"matter_id": env["matter_id"], "event_type": "FILING_DEADLINE"},
            headers=env.director,
        )
    )
    assert_fields(
        minted,
        event_type="FILING_DEADLINE",
        starts_at_utc="2026-10-15T00:00:00.000Z",
        location_code="MAIL",
        status="SCHEDULED",
        travel_buffer_minutes=0,
        version=1,
    )
    assert_null_fields(minted, "assigned_representative_id")


def test_the_return_to_filed_re_reads_the_blocking_count_and_closes_the_deadline(api):
    """One fresh required item is enough to hold the RFE response shut.

    The same request that failed succeeds after the item is waived -- waiving
    removes it from the required-open set -- which makes the FILED / RFE_PENDING
    pair an unbounded cycle. Coming back to FILED also completes the deadline
    event minted on the way out, and the facility guard keys on the filing status
    rather than on the payload, so even a no-op release is refused afterwards.

    Design: Corner/endpoints/advance_filing_mints_a_filing_deadline_event_discoverable_only_through_the_list_endpoint
    """
    env = _filed_matter(api)
    ok(
        api.advance_filing(
            env["matter_id"],
            {
                "target_filing_status": "RFE_PENDING",
                "rfe_response_due_date": _RFE_DUE_DATE,
            },
            headers=env.lead_rep,
        )
    )
    event_id = _filing_deadline_events(env)[0]["id"]

    fresh_id, = add_evidence(
        env, [10], tier="REQUIRED", item_type="COUNTRY_CONDITIONS"
    )
    assert_fields(env.matter(), evidence_blocking_count=1)
    assert_error(
        api.advance_filing(
            env["matter_id"], {"target_filing_status": "FILED"}, headers=env.lead_rep
        ),
        ERR_BLOCKING_EVIDENCE_OUTSTANDING,
    )
    assert_fields(env.matter(), filing_status="RFE_PENDING")

    drive_evidence(
        env,
        fresh_id,
        "WAIVE",
        disposition_reason_code="UNOBTAINABLE_COUNTRY_CONDITIONS",
    )
    assert_fields(env.matter(), evidence_blocking_count=0)
    refiled = ok(
        api.advance_filing(
            env["matter_id"], {"target_filing_status": "FILED"}, headers=env.lead_rep
        )
    )
    assert_fields(refiled, filing_status="FILED")

    completed = [row for row in _filing_deadline_events(env) if row["id"] == event_id]
    assert_fields(completed[0], status="COMPLETED")

    assert_error(
        api.set_facility(env["matter_id"], {"detained": False}, headers=env.supervisor),
        ERR_FACILITY_CHANGE_AFTER_FILING,
    )
    assert_fields(env.matter(), filing_status="FILED", detained=False)


# ---------------------------------------------------------------------------
# clock_startup_default_is_2026_08_01t00_00_00z_and_a_clock_write_fires_no_cascade
# ---------------------------------------------------------------------------

_STARTUP_CLOCK_UTC = "2026-08-01T00:00:00.000Z"
_FAR_FUTURE_UTC = "2032-01-01T00:00:00.000Z"


def test_the_clock_starts_at_its_declared_default_and_pushes_nothing_when_moved(api):
    """Nothing is sent to the clock endpoint before the first assertion.

    Two claims that are easy to get wrong together. The first entity written to an
    empty database is stamped 2026-08-01T00:00:00.000Z, so the server is not
    falling back to the host date -- and the accreditation term is measured from
    that same logical instant, giving 2029-07-31 rather than anything derived from
    today. The second claim is that jumping six years forward mutates nothing: the
    accreditation is still APPROVED at an unchanged version, and only the explicit
    checkpoint write pulls it to EXPIRED.

    Design: Corner/endpoints/clock_startup_default_is_2026_08_01t00_00_00z_and_a_clock_write_fires_no_cascade
    """
    director = program_director_headers()

    attorney = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Ada Ortiz", languages=["en", "es"], bar_number="BAR-1001"
            ),
            headers=director,
        )
    )
    assert_fields(attorney, created_at=_STARTUP_CLOCK_UTC)

    recognition = created(
        api.create_recognition(
            factories.recognition_payload(expiry_date="2030-01-01"), headers=director
        )
    )
    accredited = created(
        api.create_representative(
            factories.accredited_rep_payload(
                full_name="Nadia Rey", languages=["en", "es"], max_case_load=15
            ),
            headers=director,
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
            headers=director,
        )
    )
    approved = ok(
        api.transition_accreditation(
            accreditation["id"],
            {"action": "APPROVE"},
            headers=make_supervising_attorney_headers(attorney["id"]),
        )
    )
    assert_fields(
        approved,
        status="APPROVED",
        approved_by_representative_id=attorney["id"],
        authorized_forums=["USCIS"],
        effective_date="2026-08-01",
        expiry_date="2029-07-31",
    )
    assert_fields(
        ok(api.get_representative(accredited["id"], headers=director)),
        authorization_status="AUTHORIZED_ACCREDITED",
    )

    cycle = created(
        api.create_capacity_cycle(
            factories.cycle_payload(
                cycle_label="FY26-H2",
                period_start_date="2026-07-01",
                period_end_date="2026-12-31",
                total_case_slots=10,
                reserved_detained_slots=0,
            ),
            headers=director,
        )
    )
    assert_fields(
        cycle, checkpoint_epoch=1, last_checkpoint_utc=_STARTUP_CLOCK_UTC
    )

    assert ok(api.set_clock(_FAR_FUTURE_UTC, headers=director)) == {}, (
        "the clock endpoint returns an empty data object and no entity"
    )

    unchanged = ok(api.get_accreditation(accreditation["id"], headers=director))
    assert_fields(
        unchanged, status="APPROVED", version=approved["version"], expiry_date="2029-07-31"
    )
    # No row was mutated -- but authorization_status is purely derived, and PRD 3.5
    # clause 3 qualifies an accreditation only when its "expiry_date is on or after
    # the logical clock date", so reading it past 2029-07-31 yields UNAUTHORIZED
    # without the stored status having moved off APPROVED.
    assert_fields(
        ok(api.get_representative(accredited["id"], headers=director)),
        authorization_status="UNAUTHORIZED",
    )

    swept = ok(api.checkpoint_cycle(cycle["id"], headers=director))
    assert_fields(swept, checkpoint_epoch=2, last_checkpoint_utc=_FAR_FUTURE_UTC)
    assert_fields(
        ok(api.get_accreditation(accreditation["id"], headers=director)), status="EXPIRED"
    )
    assert_fields(
        ok(api.get_representative(accredited["id"], headers=director)),
        authorization_status="UNAUTHORIZED",
    )


# ---------------------------------------------------------------------------
# no_bulk_endpoint_exists_so_multi_row_effects_arrive_only_through_cascades
# ---------------------------------------------------------------------------


def _two_accredited_leads_under_one_recognition(api):
    """Two matters, each led by an accredited representative of the same recognition.

    Dov Halberstam supervises both, which is what lets two representatives whose
    ``supervision_required`` is true activate as LEADs at all -- and, being a staff
    attorney, he is the control the cascade must leave alone.
    """
    env = minimal_world(
        api,
        clock=_CLOCK_UTC,
        cycle_label="FY26-H2",
        period_start_date="2026-07-01",
        period_end_date="2026-12-31",
        total_case_slots=10,
        reserved_detained_slots=0,
        languages=["en", "es"],
    )
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(expiry_date="2030-01-01"), headers=env.director
        )
    )
    env.set(rec_id=recognition["id"])

    people = (("nadia", "Nadia Rey", "1990-04-11"), ("omar", "Omar Vale", "1988-02-19"))
    clients = (("nadia", "Rosa Mena", "1990-04-11"), ("omar", "Bea Rios", "1988-02-19"))
    for key, name, _dob in people:
        rep = created(
            api.create_representative(
                factories.accredited_rep_payload(
                    full_name=name, languages=["en", "es"], max_case_load=15
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
        env.set(**{key + "_id": rep["id"], key + "_acc_id": accreditation["id"]})

    for key, full_name, dob in clients:
        client_id = new_client(
            env,
            full_name=full_name,
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
                    matter["id"],
                    env[key + "_id"],
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
        env.set(
            **{
                key + "_matter_id": matter["id"],
                key + "_lead_id": lead["id"],
                key + "_sup_id": supervisor_id,
            }
        )
    return env


def test_the_widest_multi_row_write_still_returns_one_object_and_no_item_array(api):
    """A single-row request rewrites ten rows and reports a single recognition.

    There is no per-item status array and no partial-success envelope anywhere in
    the response, which is the shape a real bulk endpoint would need; the only
    aggregate the caller gets is suspended_accreditation_count. The cascade is also
    all-or-nothing in the other direction: the staff attorney supervising both
    matters draws his authority from the bar, so his assignments survive untouched
    in the same sweep that suspends both accredited leads.

    Design: Corner/endpoints/no_bulk_endpoint_exists_so_multi_row_effects_arrive_only_through_cascades
    """
    env = _two_accredited_leads_under_one_recognition(api)

    lapsed = ok(
        api.transition_recognition(
            env["rec_id"], {"action": "LAPSE"}, headers=env.director
        )
    )
    assert isinstance(lapsed, dict), "the response data block is one object, not a list"
    assert_fields(
        lapsed,
        status="LAPSED",
        lapsed_at_utc=_CLOCK_UTC,
        suspended_accreditation_count=2,
    )
    assert not any(
        key in lapsed for key in ("items", "results", "failures", "errors")
    ), "no per-item status array accompanies the multi-row write"

    for key in ("nadia", "omar"):
        assert_fields(
            env.accreditation(env[key + "_acc_id"]),
            status="SUSPENDED_BY_RECOGNITION",
            decision_reason_code="RECOGNITION_LAPSE",
        )
        assert_fields(
            env.representative(env[key + "_id"]),
            authorization_status="AUTHORIZATION_SUSPENDED",
            active_case_load=0,
        )
        assert_fields(
            env.assignment(env[key + "_lead_id"]),
            status="SUSPENDED",
            release_reason_code="RECOGNITION_LAPSE",
        )
        assert_fields(
            env.matter(env[key + "_matter_id"]),
            representation_status="COVERAGE_GAP",
            coverage_gap_flag=True,
        )
        assert_fields(env.assignment(env[key + "_sup_id"]), status="ACTIVE")

    assert_fields(
        env.representative(env["atty_b_id"]),
        authorization_status="AUTHORIZED_ATTORNEY",
        status="ACTIVE",
        supervisee_count=0,
    )
