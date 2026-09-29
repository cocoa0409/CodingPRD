"""Depth tests for three conserved quantities and the operations that restore them.

Each test performs a mutation and then its compensating mutation, and reads the
identity rather than a single field: the slot triple against `total_case_slots`,
the two denormalized staffing counters against their defining counts, and the
money identities on a regenerated grant report.
"""

from test_helpers import factories
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields,
    assert_slot_conservation,
    created,
    ok,
    rows,
)
from test_helpers.fixtures import accept_intake, minimal_world, new_client

# ---------------------------------------------------------------------------
# intake_withdrawal_restores_slot_pools_without_touching_detained_reserve
# ---------------------------------------------------------------------------


def _setup_two_pools(api):
    """A 10-slot cycle reserving 3 detained seats, with one seat taken from each pool.

    The detained screening names a facility in a served jurisdiction so its
    eligibility verdict is not INELIGIBLE_JURISDICTION, and BOND_HEARING is
    fee-exempt so the income clause never fires either. Nothing is ever
    waitlisted, so the withdrawal cascade stops at hop 3 and no promotion
    re-consumes the freed seat.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        cycle_label="FY27-CONS",
        total_case_slots=10,
        reserved_detained_slots=3,
    )
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

    detained_client = new_client(
        env,
        full_name="Kofi Mensah",
        preferred_language_code="en",
        country_of_birth_code="GH",
        date_of_birth="1989-01-19",
        household_size=1,
        annual_household_income_cents=1200000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    general_client = new_client(
        env,
        full_name="Lucia Ferreira",
        preferred_language_code="en",
        country_of_birth_code="BR",
        date_of_birth="1990-02-20",
        household_size=1,
        annual_household_income_cents=1300000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    detained_matter = accept_intake(
        env,
        detained_client,
        case_type="BOND_HEARING",
        detained=True,
        decision_reason_code="ACCEPTED_DETAINED_PRIORITY",
        facility_id=facility["id"],
    )
    general_matter = accept_intake(
        env, general_client, case_type="ADJUSTMENT_OF_STATUS", detained=False
    )

    assignment = created(
        api.create_assignment(
            factories.assignment_payload(
                general_matter["id"],
                env["atty_a_id"],
                general_matter["version"],
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

    env.set(
        facility_id=facility["id"],
        cd_id=detained_client,
        cg_id=general_client,
        md_id=detained_matter["id"],
        mg_id=general_matter["id"],
        ig_intake=general_matter["intake_id_used"],
        id_intake=detained_matter["intake_id_used"],
        asg_g_id=assignment["id"],
    )
    return env


def test_withdrawing_the_general_seat_returns_it_to_the_general_pool_alone(api):
    """The triple moves from (1, 1, 8) to (0, 1, 9) and still sums to 10.

    A scalar counter decrement would land on (1, 0, 9) or (0, 0, 9), and an
    implementation that lets the general pool absorb the reserve would show the
    detained figure moving. The survivor keeps its DETAINED_RESERVED attribution.

    Design: Difficulty/compensating_invariant/intake_withdrawal_restores_slot_pools_without_touching_detained_reserve
    """
    env = _setup_two_pools(api)

    before = env.cycle()
    assert_fields(
        before,
        general_slots_consumed=1,
        detained_slots_consumed=1,
        available_slot_count=8,
        capacity_posture="OPEN",
        waitlisted_count=0,
    )
    assert_decimal_equals(before["utilization_ratio"], "0.2000", 4)
    assert_slot_conservation(before)
    assert env.matter(env["md_id"])["slot_pool_consumed"] == "DETAINED_RESERVED"
    assert env.matter(env["mg_id"])["slot_pool_consumed"] == "GENERAL"

    withdrawn = ok(api.withdraw_intake(env["ig_intake"], headers=env.screener))
    assert withdrawn["status"] == "WITHDRAWN"

    after = env.cycle()
    assert_fields(
        after,
        general_slots_consumed=0,
        detained_slots_consumed=1,
        available_slot_count=9,
        capacity_posture="OPEN",
        waitlisted_count=0,
    )
    assert_decimal_equals(after["utilization_ratio"], "0.1000", 4)
    assert_slot_conservation(after)

    survivor = env.matter(env["md_id"])
    assert survivor["slot_pool_consumed"] == "DETAINED_RESERVED", (
        "the freed seat came out of GENERAL, so the detained matter's "
        "attribution must be untouched"
    )
    assert survivor["representation_status"] == "UNSTAFFED"


def test_the_withdrawn_matter_leaves_the_counts_and_releases_its_lead(api):
    """Hop 2 and hop 3 of the cascade agree: the row closes and the counter drops.

    The matter must be excluded from both slot counters rather than merely
    flagged, and the representative's `active_case_load` returns to its
    pre-activation value.

    Design: Difficulty/compensating_invariant/intake_withdrawal_restores_slot_pools_without_touching_detained_reserve
    """
    env = _setup_two_pools(api)
    assert env.representative(env["atty_a_id"])["active_case_load"] == 1

    ok(api.withdraw_intake(env["ig_intake"], headers=env.screener))

    assert_fields(
        env.matter(env["mg_id"]),
        representation_status="WITHDRAWN_FROM",
        filing_status="CLOSED_NO_FILING",
        outcome="WITHDRAWN",
        closed_at_utc="2026-09-01T00:00:00.000Z",
    )
    assert_fields(
        env.assignment(env["asg_g_id"]),
        status="RELEASED",
        release_reason_code="CLIENT_WITHDREW",
    )
    assert env.representative(env["atty_a_id"])["active_case_load"] == 0
    assert env.cycle()["general_slots_consumed"] == 0


# ---------------------------------------------------------------------------
# activate_then_release_restores_caseload_and_supervisee_counters_exactly
# ---------------------------------------------------------------------------


def _caseload_sums(api, env):
    """(sum(active_case_load), sum(supervisee_count)) across every representative."""
    representatives = rows(api.list_representatives(headers=env.director))
    return (
        sum(row["active_case_load"] for row in representatives),
        sum(row["supervisee_count"] for row in representatives),
    )


def _defining_counts(api, env):
    """The two counts the sums must equal, read from the assignment rows."""
    assignments = rows(api.list_assignments(headers=env.director))
    active = [row for row in assignments if row["status"] == "ACTIVE"]
    return (
        len([row for row in active if row["role_on_case"] in ("LEAD", "CO_COUNSEL")]),
        len([row for row in active if row["supervision_link_id"] is not None]),
    )


def _setup_proposed_supervised_lead(api):
    """A PROPOSED accredited LEAD auto-linked to the matter's only ACTIVE SUPERVISOR.

    The supervisor's SUPERVISOR row is already ACTIVE, which is what makes it an
    auto-selection candidate, and it speaks the client's Spanish. Both counters
    are still 0 when the trigger begins, so the activation is the only thing that
    can move them.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=20,
        reserved_detained_slots=4,
        languages=["en", "es"],
    )
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                recognition_number="BIA-R-2026-0777",
                effective_date="2026-01-01",
                expiry_date="2029-12-31",
                authorized_forums=["USCIS"],
            ),
            headers=env.director,
        )
    )
    supervisor = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Sofia Marquez",
                languages=["en", "es"],
                max_case_load=12,
                max_supervisees=3,
            ),
            headers=env.director,
        )
    )
    accredited = created(
        api.create_representative(
            factories.accredited_rep_payload(
                full_name="Hector Delgado",
                languages=["en", "es"],
                max_case_load=8,
                max_supervisees=0,
                weekly_capacity_hours=35,
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
    ok(
        api.transition_accreditation(
            accreditation["id"],
            {"action": "APPROVE", "decision_reason_code": "CREDENTIALS_VERIFIED"},
            headers=env.attorney_headers(supervisor["id"]),
        )
    )

    client_id = new_client(
        env,
        full_name="Rosa Jimenez",
        preferred_language_code="es",
        country_of_birth_code="GT",
        date_of_birth="1987-09-09",
        household_size=3,
        annual_household_income_cents=2600000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    matter = accept_intake(
        env, client_id, case_type="ADJUSTMENT_OF_STATUS", detained=False
    )

    supervisor_row = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                supervisor["id"],
                matter["version"],
                role_on_case="SUPERVISOR",
            ),
            headers=env.director,
        )
    )
    ok(
        api.transition_assignment(
            supervisor_row["id"], {"action": "ACTIVATE"}, headers=env.director
        )
    )
    lead = created(
        api.create_assignment(
            factories.assignment_payload(
                matter["id"],
                accredited["id"],
                env.matter_version(matter["id"]),
                role_on_case="LEAD",
            ),
            headers=env.director,
        )
    )

    env.set(
        client_id=client_id,
        matter_id=matter["id"],
        sup_s_id=supervisor["id"],
        acc_rep_id=accredited["id"],
        asg_sup_id=supervisor_row["id"],
        asg_lead_id=lead["id"],
    )
    return env


def test_one_activation_moves_two_counters_on_two_different_representatives(api):
    """The lead's active_case_load and the supervisor's supervisee_count both rise.

    The supervisor's own active_case_load must stay 0: a SUPERVISOR row is not a
    LEAD or CO_COUNSEL row and so never counts toward the caseload sum, even
    though it is ACTIVE.

    Design: Difficulty/compensating_invariant/activate_then_release_restores_caseload_and_supervisee_counters_exactly
    """
    env = _setup_proposed_supervised_lead(api)

    assert_fields(
        env.assignment(env["asg_lead_id"]),
        status="PROPOSED",
        supervision_source="AUTO_SELECTED",
        supervision_link_id=env["asg_sup_id"],
    )
    assert _caseload_sums(api, env) == (0, 0)
    assert _caseload_sums(api, env) == _defining_counts(api, env)

    activated = ok(
        api.transition_assignment(
            env["asg_lead_id"], {"action": "ACTIVATE"}, headers=env.director
        )
    )
    assert_fields(
        activated, status="ACTIVE", activated_at_utc="2026-09-01T00:00:00.000Z"
    )

    assert env.representative(env["acc_rep_id"])["active_case_load"] == 1
    assert_fields(
        env.representative(env["sup_s_id"]), supervisee_count=1, active_case_load=0
    )
    assert _caseload_sums(api, env) == (1, 1)
    assert _caseload_sums(api, env) == _defining_counts(api, env)
    assert env.matter()["representation_status"] == "SUPERVISED_STAFFED"


def test_the_compensating_release_restores_both_counters_and_nothing_else(api):
    """Release decrements exactly the counters activation incremented.

    Forgetting supervisee_count leaves the supervisor permanently full; touching
    the supervisor's active_case_load pushes it negative against its defining
    count. The supervisor's own row survives ACTIVE, and the matter falls into
    COVERAGE_GAP because the released row was the only ACTIVE LEAD.

    Design: Difficulty/compensating_invariant/activate_then_release_restores_caseload_and_supervisee_counters_exactly
    """
    env = _setup_proposed_supervised_lead(api)
    ok(
        api.transition_assignment(
            env["asg_lead_id"], {"action": "ACTIVATE"}, headers=env.director
        )
    )

    released = ok(
        api.transition_assignment(
            env["asg_lead_id"],
            {"action": "RELEASE", "release_reason_code": "CASELOAD_REBALANCE"},
            headers=env.attorney_headers(env["sup_s_id"]),
        )
    )
    assert_fields(
        released,
        status="RELEASED",
        release_reason_code="CASELOAD_REBALANCE",
        released_at_utc="2026-09-01T00:00:00.000Z",
    )

    assert env.representative(env["acc_rep_id"])["active_case_load"] == 0
    assert_fields(
        env.representative(env["sup_s_id"]), supervisee_count=0, active_case_load=0
    )
    assert _caseload_sums(api, env) == (0, 0)
    assert _caseload_sums(api, env) == _defining_counts(api, env)

    assert_fields(
        env.assignment(env["asg_sup_id"]), status="ACTIVE", supervision_link_id=None
    )
    assert_fields(
        env.matter(), representation_status="COVERAGE_GAP", coverage_gap_flag=True
    )


# ---------------------------------------------------------------------------
# amend_then_regenerate_reproduces_byte_identical_allocation
# ---------------------------------------------------------------------------

_EXPECTED_MONEY = {
    "base_reimbursable_cents": 41625,
    "supervision_surcharge_cents": 0,
    "total_reimbursable_cents": 41625,
    "allocated_line_total_cents": 41625,
    "rounding_remainder_cents": 0,
}


def _assert_money_identities(report):
    """The three conservation identities of a generated report."""
    assert (
        report["allocated_line_total_cents"] == report["total_reimbursable_cents"]
    ), "the allocation must close exactly on total_reimbursable_cents"
    assert (
        report["total_reimbursable_cents"]
        == report["base_reimbursable_cents"] + report["supervision_surcharge_cents"]
    )
    assert (
        report["suppressed_case_count"]
        == report["cases_served_count"] - report["consent_verified_count"]
    )
    assert sum(report["outcomes_summary"].values()) == report["cases_served_count"]


def _setup_single_line_report(api):
    """One reported matter with 3.33 DIRECT hours and a DRAFT report over it.

    The client's consent scope is PROGRAM_ONLY while the report asks for
    DEIDENTIFIED_CASE_LEVEL, so the single case is suppressed for disclosure yet
    still contributes its full hours and money. The matter's outcome is never
    recorded, so the histogram is entirely NOT_YET_DECIDED.
    """
    env = minimal_world(
        api,
        clock="2026-09-01T00:00:00.000Z",
        total_case_slots=20,
        reserved_detained_slots=4,
    )
    client_id = new_client(
        env,
        full_name="Lucia Ferreira",
        preferred_language_code="en",
        country_of_birth_code="BR",
        date_of_birth="1990-02-20",
        household_size=1,
        annual_household_income_cents=1300000,
        confidentiality_consent_scope="PROGRAM_ONLY",
    )
    matter = accept_intake(
        env, client_id, case_type="ADJUSTMENT_OF_STATUS", detained=False
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
    ok(
        api.log_hours(
            assignment["id"],
            {"hours": 3.33, "hours_kind": "DIRECT", "service_date": "2026-09-01"},
            headers=env.rep_headers(env["atty_a_id"]),
        )
    )
    report = created(
        api.create_grant_report(
            factories.grant_report_payload(
                env["cycle_id"],
                disclosure_level="DEIDENTIFIED_CASE_LEVEL",
                period_start_date="2026-09-01",
                period_end_date="2026-09-30",
                grant_code="LSCIMM2027",
            ),
            headers=env.analyst,
        )
    )
    env.set(
        client_id=client_id,
        matter_id=matter["id"],
        asg_id=assignment["id"],
        report_id=report["id"],
        draft_version=report["version"],
    )
    return env


def test_the_first_generation_satisfies_all_three_money_identities(api):
    """41625 cents of base, a 0.00 tier, and a single line that needs no leftover cent.

    The suppressed case is the point: it contributes nothing to
    consent_verified_count and everything to the money, so suppression must not
    be implemented by dropping the line.

    Design: Difficulty/compensating_invariant/amend_then_regenerate_reproduces_byte_identical_allocation
    """
    env = _setup_single_line_report(api)

    assert_decimal_equals(
        env.assignment(env["asg_id"])["direct_hours_logged"], "3.33", 2
    )
    assert_decimal_equals(env.matter()["direct_hours_logged"], "3.33", 2)

    generated = ok(
        api.transition_grant_report(
            env["report_id"], {"action": "GENERATE"}, headers=env.analyst
        )
    )
    assert_fields(
        generated,
        status="GENERATED",
        generated_at_utc="2026-09-01T00:00:00.000Z",
        cases_served_count=1,
        consent_verified_count=0,
        suppressed_case_count=1,
        **_EXPECTED_MONEY
    )
    assert generated["outcomes_summary"]["NOT_YET_DECIDED"] == 1
    _assert_money_identities(generated)


def test_amending_and_regenerating_reproduces_every_money_field(api):
    """The full GENERATED -> SUBMITTED -> AMENDED -> GENERATED loop over one line set.

    An implementation that accumulates instead of recomputing doubles the base on
    the second GENERATE. amendment_round advances once and stays there, and the
    four transitions advance the report's version by exactly four.

    Design: Difficulty/compensating_invariant/amend_then_regenerate_reproduces_byte_identical_allocation
    """
    env = _setup_single_line_report(api)

    ok(
        api.transition_grant_report(
            env["report_id"], {"action": "GENERATE"}, headers=env.analyst
        )
    )
    submitted = ok(
        api.transition_grant_report(
            env["report_id"], {"action": "SUBMIT"}, headers=env.analyst
        )
    )
    assert_fields(
        submitted, status="SUBMITTED", submitted_at_utc="2026-09-01T00:00:00.000Z"
    )

    amended = ok(
        api.transition_grant_report(
            env["report_id"],
            {"action": "AMEND", "amendment_reason_code": "FUNDER_QUERY"},
            headers=env.analyst,
        )
    )
    assert_fields(
        amended,
        status="AMENDED",
        amendment_round=1,
        submitted_at_utc=None,
        **_EXPECTED_MONEY
    )

    regenerated = ok(
        api.transition_grant_report(
            env["report_id"], {"action": "GENERATE"}, headers=env.analyst
        )
    )
    assert_fields(
        regenerated,
        status="GENERATED",
        amendment_round=1,
        cases_served_count=1,
        **_EXPECTED_MONEY
    )
    _assert_money_identities(regenerated)
    assert regenerated["version"] == env["draft_version"] + 4, (
        "four transitions must advance the report version by exactly four"
    )
