"""State-machine behaviour: initial states, declared transitions, cascades,
loop-back edges, terminal lockdown and every undeclared edge's own refusal.

Each test drives one declared machine edge (or one refused non-edge) and reads
the affected rows back through the declared endpoints.  Every precondition is
built inside the test, because the database is empty when the test starts.
"""

from test_helpers import (
    CLOCK_STARTUP_DEFAULT,
    MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
    ApiErrorId,
    api_client,
    assert_project_state,
    assert_unit_dimensions,
    factories,
    fixtures,
    get_success_data,
    make_resident_headers,
    same_calendar_day,
    same_instant,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, DEV, HCO, HCO2, PA

R2_TEN_UNIT_PROJECT = {
    "name": "Valid Transition",
    "zoning_district": "R-2",
    "total_units": 10,
    "approval_date": "2026-01-15",
}


# =============================================================================
# Shared scenario builders
# =============================================================================
def _path_elected_r2_project():
    """A 10-unit R-2 development screened SUBJECT with ONSITE elected."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    return fixtures.path_elected_project(
        "ONSITE", project_overrides=dict(R2_TEN_UNIT_PROJECT)
    )


def _two_unit_drawn_round():
    """A drawn two-unit round: three ranked applicants, two RESERVED units.

    Preference scores separate the pool without a tie: the second applicant
    claims both listed categories (200 points), the first claims one (100) and
    the third claims none (0).
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()
    project = fixtures.register_project(
        name="Draw Ward",
        zoning_district="R-2",
        total_units=20,
        approval_date="2026-01-15",
    )
    fixtures.screen_project(project["id"])
    fixtures.elect_path(project["id"], "ONSITE")
    agreement = fixtures.draft_agreement(project["id"])
    agreement = fixtures.record_agreement(
        agreement["id"], doc_number="DOC-DW-0001", recorded_at="2026-08-01"
    )
    unit_one = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="DW-101",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )
    unit_two = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="DW-102",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )
    plan = get_success_data(
        api_client.create_marketing_plan(
            factories.create_marketing_plan_payload(
                project["id"],
                lottery_open_at="2026-08-05T00:00:00Z",
                lottery_close_at="2026-08-20T00:00:00Z",
                preference_categories=["LIVE_WORK", "DISPLACED"],
            ),
            headers=DEV,
        )
    )
    plan = get_success_data(
        api_client.review_marketing_plan(
            plan["id"], "APPROVE", review_note="outreach plan accepted", headers=HCO
        )
    )
    event = get_success_data(
        api_client.create_lottery_event(
            factories.create_lottery_event_payload(
                plan["id"], units_offered=2, eligibility_level_bps=5000
            ),
            headers=PA,
        )
    )
    first = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    second = fixtures.register_household(
        applicant_name="Ines Novak", household_size=2, gross_annual_income_cents=5000000
    )
    third = fixtures.register_household(
        applicant_name="Jonas Wolf", household_size=3, gross_annual_income_cents=6200000
    )
    fixtures.set_clock("2026-08-10T00:00:00Z")
    fixtures.apply_to_lottery(first["id"], event["id"], ["LIVE_WORK"])
    fixtures.apply_to_lottery(second["id"], event["id"], ["LIVE_WORK", "DISPLACED"])
    fixtures.apply_to_lottery(third["id"], event["id"], [])
    fixtures.set_clock("2026-08-20T00:00:00Z")
    event_before_draw = get_success_data(
        api_client.get_lottery_event(event["id"], headers=PA)
    )
    plan_before_draw = get_success_data(
        api_client.get_marketing_plan(plan["id"], headers=HCO)
    )
    event = get_success_data(api_client.draw_lottery(event["id"], headers=PA))
    return {
        "event_before_draw": event_before_draw,
        "plan_before_draw": plan_before_draw,
        "project": project,
        "agreement": agreement,
        "unit_one": unit_one,
        "unit_two": unit_two,
        "marketing_plan": plan,
        "lottery_event": event,
        "first": first,
        "second": second,
        "third": third,
    }


def _monitored_rental_unit():
    """An OCCUPIED rental unit whose project is MONITORING, clock at 2027-03-01."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.occupied_rental_unit(
        certification_overrides={"effective_date": "2026-08-01"}
    )
    fixtures.set_clock("2027-03-01T00:00:00Z")
    return ctx


def _finding_issued_review():
    """The monitored unit carrying one FINDING_ISSUED rent-overcharge review."""
    ctx = _monitored_rental_unit()
    return fixtures.review_with_finding(
        165000,
        review_year=2027,
        ctx=ctx,
        review_overrides={"reported_income_cents": 6000000, "occupancy_verified": True},
        officer_headers=HCO,
    )


def _ownership_unit_ready_for_resale():
    """A restriction-recorded OWNERSHIP unit occupied by its seller household."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.restricted_ownership_unit(
        original_purchase_price_cents=32500000,
        restriction_recorded_at="2026-08-01",
        agreement_overrides={
            "resale_formula": "AMI_INDEXED",
            "owner_appreciation_share_bps": 2500,
            "max_refinance_ltv_bps": 9000,
        },
    )
    ctx["seller"] = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    ctx["seller_certification"] = fixtures.certify_income(
        ctx["seller"]["id"],
        ctx["unit"]["id"],
        contract_rent_cents=0,
        effective_date="2026-08-01",
    )
    ctx["buyer"] = fixtures.register_household(
        applicant_name="Ines Novak", household_size=2, gross_annual_income_cents=5000000
    )
    ctx["unit"] = fixtures.live_unit(ctx["unit"]["id"])
    return ctx


def _submit_resale(ctx, proposed_price_cents, broker_fee_cents=500000):
    """Submit a resale against a freshly read unit version, returning the raw response."""
    unit = fixtures.live_unit(ctx["unit"]["id"])
    payload = factories.create_resale_payload(
        unit["id"],
        unit["version"],
        proposed_price_cents=proposed_price_cents,
        appraised_value_cents=40000000,
        capital_improvements_cents=0,
        deferred_maintenance_cents=0,
        broker_fee_cents=broker_fee_cents,
    )
    return api_client.create_resale(payload, headers=HCO)


# =============================================================================
# Instance: recording_an_agreement_advances_it_and_cascades_the_project
# =============================================================================
def test_recording_advances_the_agreement_and_cascades_the_project():
    """Recording moves the agreement to RECORDED and drags its project along.

    PRD: "On success the agreement moves `DRAFT → RECORDED` with `doc_number` and `recorded_at` stored and its `version` incremented, and the recording cascades into the project: the project moves `PATH_ELECTED → AGREEMENT_RECORDED` and its `version` increments too."

    Design: Corner/state_machines/recording_an_agreement_advances_it_and_cascades_the_project
    """
    ctx = _path_elected_r2_project()
    project_id = ctx["project"]["id"]
    agreement = fixtures.draft_agreement(project_id)
    before = fixtures.live_project(project_id)
    assert_project_state(before, state="PATH_ELECTED")

    recorded = validate_success(
        api_client.record_agreement(
            agreement["id"], "DOC-VT-0001", "2026-08-01", headers=HCO
        )
    )

    assert recorded["state"] == "RECORDED"
    assert recorded["doc_number"] == "DOC-VT-0001"
    assert same_calendar_day(recorded["recorded_at"], "2026-08-01")
    assert recorded["version"] == 2

    after = fixtures.live_project(project_id)
    assert_project_state(after, state="AGREEMENT_RECORDED")
    assert after["version"] == before["version"] + 1
    # Recording changes state only: the obligation and the elected path stand.
    assert after["compliance_path"] == "ONSITE"
    assert after["required_affordable_units"] == 1


# =============================================================================
# Instance: newly_created_rows_sit_in_their_declared_initial_states
# =============================================================================
def test_a_fresh_agreement_starts_in_draft_with_no_recording_details():
    """Drafting an agreement leaves it DRAFT with both recording fields unset.

    PRD: "A fresh agreement sits in `state` `DRAFT` with `doc_number` and `recorded_at` unset."

    Design: Corner/state_machines/newly_created_rows_sit_in_their_declared_initial_states
    """
    ctx = _path_elected_r2_project()

    agreement = validate_success(
        api_client.create_agreement(
            factories.create_agreement_payload(ctx["project"]["id"]), headers=HCO
        ),
        expected_status=201,
    )

    assert agreement["state"] == "DRAFT"
    assert agreement["doc_number"] is None
    assert agreement["recorded_at"] is None
    assert agreement["version"] == 1
    # Drafting is not recording, so the project has not advanced.
    assert_project_state(fixtures.live_project(ctx["project"]["id"]), state="PATH_ELECTED")


def test_a_fresh_marketing_plan_starts_submitted_with_empty_review_bookkeeping():
    """A newly filed marketing plan is SUBMITTED and carries no review yet.

    PRD: "A fresh plan sits in `state` `SUBMITTED` with `revision_round` at 0 and `reviewed_by_user_id` and `review_note` unset."

    Design: Corner/state_machines/newly_created_rows_sit_in_their_declared_initial_states
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit()

    plan = validate_success(
        api_client.create_marketing_plan(
            factories.create_marketing_plan_payload(ctx["project"]["id"]), headers=DEV
        ),
        expected_status=201,
    )

    assert plan["state"] == "SUBMITTED"
    assert plan["revision_round"] == 0
    assert plan["reviewed_by_user_id"] is None
    assert plan["review_note"] is None
    assert plan["version"] == 1


def test_a_registered_household_starts_registered_with_no_lottery_attachment():
    """Registration yields a REGISTERED household with no score, rank or round.

    PRD: "A registered household starts in `state` `REGISTERED` with `preference_score` 0, `rank_position` null and `lottery_event_id` null."

    Design: Corner/state_machines/newly_created_rows_sit_in_their_declared_initial_states
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)

    household = validate_success(
        api_client.create_household(
            factories.create_household_payload(
                applicant_name="Hana Iyer",
                household_size=3,
                gross_annual_income_cents=6000000,
            ),
            headers=PA,
        ),
        expected_status=201,
    )

    assert household["state"] == "REGISTERED"
    assert household["preference_score"] == 0
    assert household["rank_position"] is None
    assert household["lottery_event_id"] is None
    assert household["version"] == 1


# =============================================================================
# Instance: the_draw_fans_side_effects_out_to_households_units_and_the_plan
# =============================================================================
def test_the_draw_records_its_own_bookkeeping_and_ranked_id_lists():
    """The drawn round stores both rank-ordered id lists and stamps who drew it.

    PRD: "The round itself moves `PENDING → DRAWN`, records the two id lists, stamps `drawn_at` with the current logical instant and `drawn_by_user_id` with the acting `X-User-ID`, leaves `round_seq` unchanged, and increments its `version`."

    Design: Corner/state_machines/the_draw_fans_side_effects_out_to_households_units_and_the_plan
    """
    ctx = _two_unit_drawn_round()
    event = ctx["lottery_event"]

    assert event["state"] == "DRAWN"
    assert event["selected_household_ids"] == [ctx["second"]["id"], ctx["first"]["id"]]
    assert event["waitlisted_household_ids"] == [ctx["third"]["id"]]
    assert same_instant(event["drawn_at"], "2026-08-20T00:00:00Z")
    assert event["drawn_by_user_id"] == PA["X-User-ID"]
    assert event["round_seq"] == ctx["event_before_draw"]["round_seq"] == 1
    assert event["version"] == ctx["event_before_draw"]["version"] + 1


def test_the_draw_cascades_down_onto_the_applicant_households():
    """Selection and waitlisting move every pooled household and rank it.

    PRD: "Each selected household moves `APPLIED → SELECTED` and each waitlisted household moves `APPLIED → WAITLISTED`, both with `rank_position` set, each bumping its own `version`."

    Design: Corner/state_machines/the_draw_fans_side_effects_out_to_households_units_and_the_plan
    """
    ctx = _two_unit_drawn_round()

    top = get_success_data(api_client.get_household(ctx["second"]["id"], headers=PA))
    runner_up = get_success_data(api_client.get_household(ctx["first"]["id"], headers=PA))
    waitlisted = get_success_data(api_client.get_household(ctx["third"]["id"], headers=PA))

    assert top["state"] == "SELECTED"
    assert top["rank_position"] == 1
    assert top["preference_score"] == 200
    assert runner_up["state"] == "SELECTED"
    assert runner_up["rank_position"] == 2
    assert runner_up["preference_score"] == 100
    assert waitlisted["state"] == "WAITLISTED"
    assert waitlisted["rank_position"] == 3
    assert waitlisted["preference_score"] == 0
    # Every household moved, so every household's own version advanced.
    for row, applied in ((top, ctx["second"]), (runner_up, ctx["first"]), (waitlisted, ctx["third"])):
        assert row["version"] > applied["version"]


def test_the_draw_pairs_marketing_units_with_selected_households_by_unit_number():
    """Units are reserved rank-for-rank in ascending unit_number order.

    PRD: "The project's units whose `occupancy_status` is `MARKETING`, taken in ascending `unit_number` order, are paired rank-for-rank with the selected households: each such unit moves `MARKETING → RESERVED` with `occupant_household_id` set to the household at the matching rank, incrementing its own `version`."

    Design: Corner/state_machines/the_draw_fans_side_effects_out_to_households_units_and_the_plan
    """
    ctx = _two_unit_drawn_round()

    first_unit = fixtures.live_unit(ctx["unit_one"]["id"])
    second_unit = fixtures.live_unit(ctx["unit_two"]["id"])

    assert first_unit["unit_number"] == "DW-101"
    assert_unit_dimensions(first_unit, occupancy_status="RESERVED")
    assert first_unit["occupant_household_id"] == ctx["second"]["id"]
    assert first_unit["version"] > ctx["unit_one"]["version"]

    assert second_unit["unit_number"] == "DW-102"
    assert_unit_dimensions(second_unit, occupancy_status="RESERVED")
    assert second_unit["occupant_household_id"] == ctx["first"]["id"]
    assert second_unit["version"] > ctx["unit_two"]["version"]


def test_the_draw_closes_the_marketing_plan_behind_the_round():
    """Running the draw retires the approved plan that authorised the round.

    PRD: "And the marketing plan behind the round moves `APPROVED → CLOSED`, incrementing its `version`."

    Design: Corner/state_machines/the_draw_fans_side_effects_out_to_households_units_and_the_plan
    """
    ctx = _two_unit_drawn_round()

    plan = get_success_data(
        api_client.get_marketing_plan(ctx["marketing_plan"]["id"], headers=HCO)
    )

    assert ctx["plan_before_draw"]["state"] == "APPROVED"
    assert plan["state"] == "CLOSED"
    assert plan["version"] == ctx["plan_before_draw"]["version"] + 1
    # Closing the plan is not a revision cycle.
    assert plan["revision_round"] == 0


# =============================================================================
# Instance: agreement_recording_enforces_path_and_backdating_preconditions
# =============================================================================
def test_recording_a_fee_path_agreement_is_refused_as_not_required():
    """A development discharging its obligation through fees records nothing.

    PRD: "The project's `compliance_path` must be `ONSITE` or `OFFSITE`, because a development discharging its obligation entirely through fees or a land dedication records no agreement at all; an attempt on an `IN_LIEU_FEE` or `LAND_DEDICATION` project is refused with `ERR_AGREEMENT_NOT_REQUIRED`."

    Design: Corner/state_machines/agreement_recording_enforces_path_and_backdating_preconditions
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.fee_path_project(project_overrides=dict(R2_TEN_UNIT_PROJECT))
    agreement = fixtures.draft_agreement(ctx["project"]["id"])
    assert agreement["state"] == "DRAFT"

    validate_error(
        api_client.record_agreement(
            agreement["id"], "DOC-FEE-0001", "2026-08-01", headers=HCO
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_REQUIRED.value,
    )

    unchanged = get_success_data(api_client.get_agreement(agreement["id"], headers=HCO))
    assert unchanged["state"] == "DRAFT"
    assert unchanged["doc_number"] is None
    assert unchanged["recorded_at"] is None
    assert unchanged["version"] == agreement["version"]
    assert_project_state(fixtures.live_project(ctx["project"]["id"]), state="PATH_ELECTED")


def test_recording_before_the_approval_date_is_refused_and_the_doc_number_survives():
    """Backdated recording is refused; the same doc_number then works on the boundary.

    PRD: "And the supplied `recorded_at` must fall on or after the project's `approval_date`, else `ERR_RECORDING_PREDATES_APPROVAL`."

    Design: Corner/state_machines/agreement_recording_enforces_path_and_backdating_preconditions
    """
    ctx = _path_elected_r2_project()
    agreement = fixtures.draft_agreement(ctx["project"]["id"])

    validate_error(
        api_client.record_agreement(
            agreement["id"], "DOC-BD-0001", "2026-01-14", headers=HCO
        ),
        ApiErrorId.ERR_RECORDING_PREDATES_APPROVAL.value,
    )
    refused = get_success_data(api_client.get_agreement(agreement["id"], headers=HCO))
    assert refused["state"] == "DRAFT"
    assert refused["version"] == agreement["version"]

    # The approval date itself is inclusive, and the refused attempt consumed
    # no doc_number, so the very same number records successfully.
    recorded = validate_success(
        api_client.record_agreement(
            agreement["id"], "DOC-BD-0001", "2026-01-15", headers=HCO
        )
    )
    assert recorded["state"] == "RECORDED"
    assert recorded["doc_number"] == "DOC-BD-0001"
    assert same_calendar_day(recorded["recorded_at"], "2026-01-15")
    assert recorded["version"] == 2
    assert_project_state(
        fixtures.live_project(ctx["project"]["id"]), state="AGREEMENT_RECORDED"
    )


# =============================================================================
# Instance: re_screening_a_screened_project_is_refused_not_reapplied
# =============================================================================
def test_re_screening_a_screened_project_is_refused_without_reapplying():
    """Screening runs only from DRAFT, so a screened project refuses a re-screen.

    PRD: "Because screening runs only from `DRAFT`, a second screening always requires an amendment first, and `screen_count` is the visible record of how many times the development has been through the mill."

    Design: Corner/state_machines/re_screening_a_screened_project_is_refused_not_reapplied
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.screened_project(
        project_overrides={
            "name": "Birch Yards",
            "zoning_district": "R-4",
            "total_units": 27,
            "approval_date": "2026-01-15",
        }
    )
    screened = ctx["project"]
    assert_project_state(screened, state="SCREENED_SUBJECT", applicability="SUBJECT")
    assert screened["screen_count"] == 1

    validate_error(
        api_client.screen_project(screened["id"], headers=HCO),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
    )

    after = fixtures.live_project(screened["id"])
    assert after["screen_count"] == 1
    assert after["version"] == screened["version"]
    assert after["required_affordable_units"] == 4
    assert after["fractional_obligation_bps"] == 500
    assert after["total_obligation_bps"] == 40500


def test_amending_the_project_reopens_screening_and_rederives_the_obligation():
    """Amendment clears the screening outputs so a second screening can run.

    PRD: "In every case the screening outputs are cleared: `applicability` returns to `PENDING`, `required_affordable_units`, `fractional_obligation_bps` and `total_obligation_bps` return to 0, `compliance_path` and `ordinance_id` are cleared to null, `compliance_posture` returns to `PENDING`, and the project's `version` increments — including on the self-transition, where the clears are no-ops on a project that was never screened but the version bump still happens, which is exactly what a subsequent re-screen depends on."

    Design: Corner/state_machines/re_screening_a_screened_project_is_refused_not_reapplied
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.screened_project(
        project_overrides={
            "name": "Birch Yards",
            "zoning_district": "R-4",
            "total_units": 27,
            "approval_date": "2026-01-15",
        }
    )

    amended = validate_success(
        api_client.patch_project(ctx["project"]["id"], {"total_units": 30}, headers=DEV)
    )

    assert_project_state(
        amended, state="DRAFT", applicability="PENDING", compliance_posture="PENDING"
    )
    assert amended["ordinance_id"] is None
    assert amended["compliance_path"] is None
    assert amended["required_affordable_units"] == 0
    assert amended["fractional_obligation_bps"] == 0
    assert amended["total_obligation_bps"] == 0
    assert amended["screen_count"] == 1
    assert amended["version"] == ctx["project"]["version"] + 1

    rescreened = validate_success(
        api_client.screen_project(ctx["project"]["id"], headers=HCO)
    )
    assert_project_state(rescreened, state="SCREENED_SUBJECT", applicability="SUBJECT")
    assert rescreened["screen_count"] == 2
    # 30 units at 1500 bps is 45000 raw: four whole units and a 5000 residual
    # that rounds up into a fifth.
    assert rescreened["required_affordable_units"] == 5
    assert rescreened["fractional_obligation_bps"] == 0
    assert rescreened["total_obligation_bps"] == 50000
    assert rescreened["version"] == 4


# =============================================================================
# Instance: a_closed_out_project_and_its_released_agreement_accept_no_writes
# =============================================================================
def test_close_out_releases_the_recorded_agreement():
    """Passing every gate retires the project and releases its recorded agreement.

    PRD: "When all four gates pass, the project moves `MONITORING → CLOSED_OUT` and every regulatory agreement of that project still in `state` `RECORDED` moves `RECORDED → RELEASED`, each incrementing its own `version`."

    Design: Corner/state_machines/a_closed_out_project_and_its_released_agreement_accept_no_writes
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.occupied_rental_unit()
    assert_project_state(
        ctx["project"], state="MONITORING", compliance_posture="COMPLIANT_ONSITE"
    )
    recorded = get_success_data(
        api_client.get_agreement(ctx["agreement"]["id"], headers=HCO)
    )
    assert recorded["state"] == "RECORDED"

    closed = validate_success(
        api_client.close_out_project(ctx["project"]["id"], headers=PA)
    )

    assert_project_state(closed, state="CLOSED_OUT")
    assert closed["version"] == ctx["project"]["version"] + 1
    released = get_success_data(
        api_client.get_agreement(ctx["agreement"]["id"], headers=HCO)
    )
    assert released["state"] == "RELEASED"
    assert released["version"] == recorded["version"] + 1


def test_a_closed_out_project_refuses_a_second_close_out():
    """CLOSED_OUT is terminal, so close-out cannot be replayed against it.

    PRD: "A `ProgramAdministrator` or `HousingComplianceOfficer` closes out a project in `state` `MONITORING` only; any other state is refused with `ERR_INVALID_PROJECT_STATE`."

    Design: Corner/state_machines/a_closed_out_project_and_its_released_agreement_accept_no_writes
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.occupied_rental_unit()
    closed = get_success_data(api_client.close_out_project(ctx["project"]["id"], headers=PA))

    validate_error(
        api_client.close_out_project(ctx["project"]["id"], headers=HCO),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
    )

    after = fixtures.live_project(ctx["project"]["id"])
    assert_project_state(after, state="CLOSED_OUT")
    assert after["version"] == closed["version"]


def test_a_closed_out_project_refuses_amendment_and_new_units_while_reads_still_work():
    """Neither amendment nor unit creation reaches a retired project.

    PRD: "Screening is permitted only from `DRAFT`; amendment only from `DRAFT`, `SCREENED_SUBJECT`, `SCREENED_EXEMPT`, `PATH_ELECTED` or `AGREEMENT_RECORDED`; path election only from `SCREENED_SUBJECT`; agreement recording only from `PATH_ELECTED`; unit creation only from `PATH_ELECTED`, `AGREEMENT_RECORDED` or `MONITORING`; close-out only from `MONITORING`."

    Design: Corner/state_machines/a_closed_out_project_and_its_released_agreement_accept_no_writes
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.occupied_rental_unit()
    closed = get_success_data(api_client.close_out_project(ctx["project"]["id"], headers=PA))

    validate_error(
        api_client.patch_project(ctx["project"]["id"], {"total_units": 12}, headers=DEV),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
    )
    validate_error(
        api_client.create_unit(
            factories.create_unit_payload(
                ctx["project"]["id"], ctx["agreement"]["id"], unit_number="102"
            ),
            headers=DEV,
        ),
        ApiErrorId.ERR_INVALID_PROJECT_STATE.value,
    )

    # Reads survive the lockdown, and nothing moved.
    still_closed = fixtures.live_project(ctx["project"]["id"], headers=AUDITOR)
    assert_project_state(still_closed, state="CLOSED_OUT")
    assert still_closed["total_units"] == 10
    assert still_closed["version"] == closed["version"]


# =============================================================================
# Instance: the_occupancy_loop_runs_occupied_to_vacant_and_back
# =============================================================================
def test_the_expiry_sweep_vacates_the_unit_and_leaves_the_household_certified():
    """An expiring rental term empties the unit without un-certifying the household.

    PRD: "Every `IncomeCertification` still in state `CERTIFIED` whose `expires_at` is now strictly in the past transitions to `EXPIRED`, and each such expiry vacates its unit: the unit's `occupancy_status` moves from `OCCUPIED` to `VACANT`, its `current_rent_cents` is reset to 0, its `occupant_household_id` is cleared to null, and the owning project's `compliance_posture` is recomputed."

    Design: Corner/state_machines/the_occupancy_loop_runs_occupied_to_vacant_and_back
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.occupied_rental_unit(
        certification_overrides={"effective_date": "2026-08-01"}
    )
    assert_unit_dimensions(ctx["unit"], occupancy_status="OCCUPIED")
    assert same_calendar_day(ctx["certification"]["expires_at"], "2027-08-01")

    sweep = fixtures.set_clock("2027-08-02T00:00:00Z")

    assert sweep["certifications_expired"] == 1
    expired = get_success_data(
        api_client.get_certification(ctx["certification"]["id"], headers=HCO)
    )
    assert expired["state"] == "EXPIRED"
    vacated = fixtures.live_unit(ctx["unit"]["id"])
    assert_unit_dimensions(vacated, occupancy_status="VACANT")
    assert vacated["current_rent_cents"] == 0
    assert vacated["occupant_household_id"] is None
    # The ceiling is a property of the unit, not of the tenancy that just ended.
    assert vacated["max_allowed_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS
    # CERTIFIED is the household's terminal state; the sweep does not touch it.
    household = get_success_data(
        api_client.get_household(ctx["household"]["id"], headers=PA)
    )
    assert household["state"] == "CERTIFIED"


def test_a_fresh_certification_returns_the_vacant_unit_to_occupied():
    """A vacated unit re-fills from VACANT with the direct-placement side effects.

    PRD: "From `VACANT` the unit moves `VACANT → OCCUPIED` with the same side effects as the `PLANNED` branch."

    Design: Corner/state_machines/the_occupancy_loop_runs_occupied_to_vacant_and_back
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.occupied_rental_unit(
        certification_overrides={"effective_date": "2026-08-01"}
    )
    fixtures.set_clock("2027-08-02T00:00:00Z")
    vacated = fixtures.live_unit(ctx["unit"]["id"])
    assert_unit_dimensions(vacated, occupancy_status="VACANT")
    successor_household = fixtures.register_household(
        applicant_name="Ines Novak", household_size=3, gross_annual_income_cents=6000000
    )

    certification = validate_success(
        api_client.create_certification(
            factories.create_certification_payload(
                successor_household["id"],
                ctx["unit"]["id"],
                certified_income_cents=6000000,
                contract_rent_cents=141000,
                effective_date="2027-08-02",
            ),
            headers=HCO,
        ),
        expected_status=201,
    )

    assert certification["state"] == "CERTIFIED"
    assert certification["is_recertification"] is False
    assert same_calendar_day(certification["expires_at"], "2028-08-01")
    reoccupied = fixtures.live_unit(ctx["unit"]["id"])
    assert_unit_dimensions(reoccupied, occupancy_status="OCCUPIED")
    assert reoccupied["occupant_household_id"] == successor_household["id"]
    assert reoccupied["current_rent_cents"] == 141000
    assert reoccupied["version"] > vacated["version"]
    assert (
        get_success_data(
            api_client.get_household(successor_household["id"], headers=PA)
        )["state"]
        == "CERTIFIED"
    )
    # The project was already MONITORING, so the loop does not move it again.
    assert_project_state(fixtures.live_project(ctx["project"]["id"]), state="MONITORING")


# =============================================================================
# Instance: invalid_transitions_across_the_marketing_and_lottery_track
# =============================================================================
def test_a_pending_round_refuses_a_redraw_it_never_earned():
    """Redrawing is reachable only from DRAWN, never from a round still PENDING.

    PRD: "The lottery round's `state` permits the operation — drawing only from `PENDING`, redrawing only from `DRAWN`, and accepting an application only while `PENDING` — else `ERR_LOTTERY_STATE_INVALID`."

    Design: Corner/state_machines/invalid_transitions_across_the_marketing_and_lottery_track
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.lottery_with_applicants(
        applicants=[{"applicant_name": "Hana Iyer", "preference_claims": ["LIVE_WORK"]}]
    )
    pending = get_success_data(
        api_client.get_lottery_event(ctx["lottery_event"]["id"], headers=PA)
    )
    assert pending["state"] == "PENDING"

    validate_error(
        api_client.redraw_lottery(pending["id"], "no draw has been run yet", headers=PA),
        ApiErrorId.ERR_LOTTERY_STATE_INVALID.value,
    )

    unchanged = get_success_data(api_client.get_lottery_event(pending["id"], headers=PA))
    assert unchanged["state"] == "PENDING"
    assert unchanged["round_seq"] == pending["round_seq"]
    assert unchanged["redraw_reason"] is None
    assert unchanged["selected_household_ids"] == []
    assert unchanged["waitlisted_household_ids"] == []
    assert unchanged["version"] == pending["version"]


def test_a_closed_plan_refuses_review_resubmission_and_new_rounds():
    """The plan's terminal CLOSED state shuts all three plan-driven operations.

    PRD: "The marketing plan's `state` permits the operation — review only from `SUBMITTED`, resubmission only from `REVISION_REQUESTED`, and opening a lottery round only against an `APPROVED` plan — else `ERR_PLAN_NOT_APPROVED`."

    Design: Corner/state_machines/invalid_transitions_across_the_marketing_and_lottery_track
    """
    ctx = _two_unit_drawn_round()
    closed_plan = get_success_data(
        api_client.get_marketing_plan(ctx["marketing_plan"]["id"], headers=HCO)
    )
    assert closed_plan["state"] == "CLOSED"

    validate_error(
        api_client.review_marketing_plan(closed_plan["id"], "APPROVE", headers=HCO),
        ApiErrorId.ERR_PLAN_NOT_APPROVED.value,
    )
    validate_error(
        api_client.resubmit_marketing_plan(
            closed_plan["id"],
            {
                "lottery_open_at": "2026-10-01T00:00:00Z",
                "lottery_close_at": "2026-10-31T00:00:00Z",
                "preference_categories": ["LIVE_WORK"],
            },
            headers=DEV,
        ),
        ApiErrorId.ERR_PLAN_NOT_APPROVED.value,
    )
    validate_error(
        api_client.create_lottery_event(
            factories.create_lottery_event_payload(closed_plan["id"], units_offered=1),
            headers=PA,
        ),
        ApiErrorId.ERR_PLAN_NOT_APPROVED.value,
    )

    after = get_success_data(api_client.get_marketing_plan(closed_plan["id"], headers=HCO))
    assert after["state"] == "CLOSED"
    assert after["revision_round"] == 0
    assert after["version"] == closed_plan["version"]


def test_a_redraw_returns_the_round_to_pending_and_raises_the_round_counter():
    """Redrawing is a loop back to PENDING that raises round_seq exactly once.

    PRD: "On success the round moves `DRAWN → PENDING`, `round_seq` increases by one, both `selected_household_ids` and `waitlisted_household_ids` are emptied, `redraw_reason` stores the supplied reason, and the round's `version` increments."

    Design: Corner/state_machines/invalid_transitions_across_the_marketing_and_lottery_track
    """
    ctx = _two_unit_drawn_round()
    drawn = ctx["lottery_event"]

    redrawn = validate_success(
        api_client.redraw_lottery(
            drawn["id"], "duplicate applications discovered in the pool", headers=PA
        )
    )

    assert redrawn["state"] == "PENDING"
    assert redrawn["round_seq"] == 2
    assert redrawn["selected_household_ids"] == []
    assert redrawn["waitlisted_household_ids"] == []
    assert redrawn["redraw_reason"] == "duplicate applications discovered in the pool"
    assert redrawn["version"] == drawn["version"] + 1


def test_a_redraw_rolls_every_ranked_household_back_to_applied():
    """Both selected and waitlisted households return to APPLIED unranked.

    PRD: "Every household attached to this round whose `state` is `SELECTED` or `WAITLISTED` returns to `APPLIED` — `SELECTED → APPLIED` and `WAITLISTED → APPLIED` — with `rank_position` cleared to null and its own `version` bumped."

    Design: Corner/state_machines/invalid_transitions_across_the_marketing_and_lottery_track
    """
    ctx = _two_unit_drawn_round()
    ranked = [
        get_success_data(api_client.get_household(ctx[key]["id"], headers=PA))
        for key in ("second", "first", "third")
    ]
    assert [row["state"] for row in ranked] == ["SELECTED", "SELECTED", "WAITLISTED"]

    get_success_data(
        api_client.redraw_lottery(
            ctx["lottery_event"]["id"], "outreach period reopened", headers=PA
        )
    )

    for before in ranked:
        after = get_success_data(api_client.get_household(before["id"], headers=PA))
        assert after["state"] == "APPLIED"
        assert after["rank_position"] is None
        assert after["version"] == before["version"] + 1
        # The household stays attached to the round it is waiting on.
        assert after["lottery_event_id"] == ctx["lottery_event"]["id"]


def test_a_redraw_returns_the_reserved_units_to_marketing():
    """Clearing the selection releases the units it had reserved.

    PRD: "Every unit whose `occupancy_status` is `RESERVED` and whose `occupant_household_id` was in the cleared selection returns `RESERVED → MARKETING` with `occupant_household_id` cleared to null."

    Design: Corner/state_machines/invalid_transitions_across_the_marketing_and_lottery_track
    """
    ctx = _two_unit_drawn_round()
    reserved_one = fixtures.live_unit(ctx["unit_one"]["id"])
    reserved_two = fixtures.live_unit(ctx["unit_two"]["id"])
    assert_unit_dimensions(reserved_one, occupancy_status="RESERVED")
    assert_unit_dimensions(reserved_two, occupancy_status="RESERVED")

    get_success_data(
        api_client.redraw_lottery(
            ctx["lottery_event"]["id"], "selection voided for review", headers=PA
        )
    )

    for before in (reserved_one, reserved_two):
        after = fixtures.live_unit(before["id"])
        assert_unit_dimensions(after, occupancy_status="MARKETING")
        assert after["occupant_household_id"] is None
        assert after["version"] > before["version"]


def test_reapplying_an_applied_household_hits_the_household_state_guard():
    """A household already in the pool cannot apply to the reopened round again.

    PRD: "The household's `state` permits the operation — applying only from `REGISTERED`, and being certified only from `REGISTERED` or `SELECTED`, since an already `CERTIFIED` household holds a live placement and is not certified again — else `ERR_HOUSEHOLD_STATE_INVALID`."

    Design: Corner/state_machines/invalid_transitions_across_the_marketing_and_lottery_track
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.lottery_with_applicants(
        applicants=[{"applicant_name": "Hana Iyer", "preference_claims": ["LIVE_WORK"]}]
    )
    # The plan is APPROVED, the round is PENDING and the window is open, so the
    # household's own state is the first rung this second application can fail.
    assert (
        get_success_data(
            api_client.get_marketing_plan(ctx["marketing_plan"]["id"], headers=HCO)
        )["state"]
        == "APPROVED"
    )
    assert (
        get_success_data(
            api_client.get_lottery_event(ctx["lottery_event"]["id"], headers=PA)
        )["state"]
        == "PENDING"
    )
    reapplying = get_success_data(
        api_client.get_household(ctx["households"][0]["id"], headers=PA)
    )
    assert reapplying["state"] == "APPLIED"

    validate_error(
        api_client.apply_household(
            reapplying["id"],
            ctx["lottery_event"]["id"],
            preference_claims=["LIVE_WORK"],
            headers=make_resident_headers(reapplying["id"]),
        ),
        ApiErrorId.ERR_HOUSEHOLD_STATE_INVALID.value,
    )

    unchanged = get_success_data(api_client.get_household(reapplying["id"], headers=PA))
    assert unchanged["state"] == "APPLIED"
    assert unchanged["version"] == reapplying["version"]


# =============================================================================
# Instance: invalid_transitions_across_the_monitoring_review_track
# =============================================================================
def test_a_finding_issued_review_refuses_clearing_and_escalation():
    """Disposal of a finding is reachable only after a cure has been submitted.

    PRD: "The monitoring review's `state` permits the operation — cure submission only from `FINDING_ISSUED` or `ESCALATED`, cure clearing and escalation only from `CURE_SUBMITTED` — else `ERR_REVIEW_STATE_INVALID`."

    Design: Corner/state_machines/invalid_transitions_across_the_monitoring_review_track
    """
    ctx = _finding_issued_review()
    review = ctx["monitoring_review"]
    assert review["state"] == "FINDING_ISSUED"
    assert_unit_dimensions(ctx["unit"], compliance_status="FINDING_OPEN")

    # A second officer acts, so segregation of duties is satisfied and the
    # review's own state is the first rung either attempt can fail.
    validate_error(
        api_client.clear_cure(review["id"], headers=HCO2),
        ApiErrorId.ERR_REVIEW_STATE_INVALID.value,
    )
    validate_error(
        api_client.escalate_review(review["id"], headers=HCO2),
        ApiErrorId.ERR_REVIEW_STATE_INVALID.value,
    )

    after = get_success_data(api_client.get_monitoring_review(review["id"], headers=HCO))
    assert after["state"] == "FINDING_ISSUED"
    assert after["cleared_by_user_id"] is None
    assert after["version"] == review["version"]
    assert_unit_dimensions(
        fixtures.live_unit(ctx["unit"]["id"]), compliance_status="FINDING_OPEN"
    )


def test_a_cure_submitted_review_refuses_a_second_cure():
    """Once a cure is on file the submission route closes until disposal.

    PRD: "It is permitted from `FINDING_ISSUED` or `ESCALATED` only; any other review state is refused with `ERR_REVIEW_STATE_INVALID`."

    Design: Corner/state_machines/invalid_transitions_across_the_monitoring_review_track
    """
    ctx = _finding_issued_review()
    review = ctx["monitoring_review"]

    cured = validate_success(api_client.submit_cure(review["id"], 140000, headers=DEV))

    assert cured["state"] == "CURE_SUBMITTED"
    assert cured["corrected_rent_cents"] == 140000
    unit = fixtures.live_unit(ctx["unit"]["id"])
    assert_unit_dimensions(unit, compliance_status="CURE_PENDING")
    assert unit["current_rent_cents"] == 140000

    validate_error(
        api_client.submit_cure(review["id"], 139000, headers=DEV),
        ApiErrorId.ERR_REVIEW_STATE_INVALID.value,
    )

    after = get_success_data(api_client.get_monitoring_review(review["id"], headers=HCO))
    assert after["state"] == "CURE_SUBMITTED"
    assert after["corrected_rent_cents"] == 140000
    assert after["version"] == cured["version"]
    assert fixtures.live_unit(ctx["unit"]["id"])["current_rent_cents"] == 140000


def test_a_cleared_cure_is_terminal_and_refuses_escalation():
    """CURED closes the review for good, escalation included.

    PRD: "**Clearing the cure** moves the review `CURE_SUBMITTED → CURED`, storing `cleared_by_user_id`, and cascades the unit `CURE_PENDING → COMPLIANT` with the project's `compliance_posture` recomputed."

    Design: Corner/state_machines/invalid_transitions_across_the_monitoring_review_track
    """
    ctx = _finding_issued_review()
    review = get_success_data(
        api_client.submit_cure(ctx["monitoring_review"]["id"], 140000, headers=DEV)
    )

    cleared = validate_success(api_client.clear_cure(review["id"], headers=HCO2))

    assert cleared["state"] == "CURED"
    assert cleared["cleared_by_user_id"] == HCO2["X-User-ID"]
    assert cleared["version"] == review["version"] + 1
    assert_unit_dimensions(
        fixtures.live_unit(ctx["unit"]["id"]), compliance_status="COMPLIANT"
    )

    validate_error(
        api_client.escalate_review(review["id"], headers=HCO),
        ApiErrorId.ERR_REVIEW_STATE_INVALID.value,
    )
    after = get_success_data(api_client.get_monitoring_review(review["id"], headers=HCO))
    assert after["state"] == "CURED"
    assert after["version"] == cleared["version"]


def test_a_review_with_no_findings_is_born_compliant_and_leaves_the_unit_alone():
    """A clean annual review lands COMPLIANT without touching the unit.

    PRD: "If `finding_types` comes out empty the review moves `RECORDED → COMPLIANT`, its `cure_deadline` stays null, its `penalty_at_base_cents` stays 0, and **the unit's `compliance_status` does not change at all**."

    Design: Corner/state_machines/invalid_transitions_across_the_monitoring_review_track
    """
    ctx = _monitored_rental_unit()
    before = fixtures.live_unit(ctx["unit"]["id"])
    assert_unit_dimensions(before, compliance_status="COMPLIANT")

    review = validate_success(
        api_client.create_monitoring_review(
            factories.create_monitoring_review_payload(
                ctx["unit"]["id"],
                review_year=2027,
                reported_rent_cents=140000,
                reported_income_cents=6000000,
                occupancy_verified=True,
            ),
            headers=HCO,
        ),
        expected_status=201,
    )

    assert review["state"] == "COMPLIANT"
    assert review["finding_types"] == []
    assert review["cure_deadline"] is None
    assert review["penalty_at_base_cents"] == 0
    after = fixtures.live_unit(ctx["unit"]["id"])
    assert_unit_dimensions(after, compliance_status="COMPLIANT")
    assert after["version"] == before["version"]


def test_a_compliant_review_refuses_both_cure_submission_and_escalation():
    """The other terminal review state is just as closed as CURED.

    PRD: "The monitoring review's `state` permits the operation — cure submission only from `FINDING_ISSUED` or `ESCALATED`, cure clearing and escalation only from `CURE_SUBMITTED` — else `ERR_REVIEW_STATE_INVALID`."

    Design: Corner/state_machines/invalid_transitions_across_the_monitoring_review_track
    """
    ctx = _monitored_rental_unit()
    review = get_success_data(
        api_client.create_monitoring_review(
            factories.create_monitoring_review_payload(
                ctx["unit"]["id"],
                review_year=2027,
                reported_rent_cents=140000,
                reported_income_cents=6000000,
                occupancy_verified=True,
            ),
            headers=HCO,
        )
    )
    assert review["state"] == "COMPLIANT"

    validate_error(
        api_client.submit_cure(review["id"], 139000, headers=DEV),
        ApiErrorId.ERR_REVIEW_STATE_INVALID.value,
    )
    validate_error(
        api_client.escalate_review(review["id"], headers=HCO2),
        ApiErrorId.ERR_REVIEW_STATE_INVALID.value,
    )

    after = get_success_data(api_client.get_monitoring_review(review["id"], headers=HCO))
    assert after["state"] == "COMPLIANT"
    assert after["corrected_rent_cents"] is None
    assert after["version"] == review["version"]


# =============================================================================
# Instance: invalid_transitions_and_supersession_across_the_resale_track
# =============================================================================
def test_a_submitted_resale_refuses_the_rofr_fork_and_closing():
    """From SUBMITTED only price approval is reachable; the later routes refuse.

    PRD: "The resale transaction's `state` permits the operation — price approval from `SUBMITTED`, the right-of-first-refusal decision from `PRICE_APPROVED`, buyer certification from `ROFR_WAIVED`, closing from either `BUYER_CERTIFIED` or `ROFR_EXERCISED` — else `ERR_RESALE_STATE_INVALID`."

    Design: Corner/state_machines/invalid_transitions_and_supersession_across_the_resale_track
    """
    ctx = _ownership_unit_ready_for_resale()
    resale = validate_success(_submit_resale(ctx, 32000000), expected_status=201)
    assert resale["state"] == "SUBMITTED"

    validate_error(
        api_client.rofr_decision(resale["id"], "WAIVE", headers=PA),
        ApiErrorId.ERR_RESALE_STATE_INVALID.value,
    )
    validate_error(
        api_client.certify_buyer(
            resale["id"],
            ctx["buyer"]["id"],
            ctx["seller_certification"]["id"],
            headers=HCO2,
        ),
        ApiErrorId.ERR_RESALE_STATE_INVALID.value,
    )
    validate_error(
        api_client.close_resale(resale["id"], headers=HCO),
        ApiErrorId.ERR_RESALE_STATE_INVALID.value,
    )

    after = get_success_data(api_client.get_resale(resale["id"], headers=HCO))
    assert after["state"] == "SUBMITTED"
    assert after["rofr_deadline"] is None
    assert after["buyer_household_id"] is None
    assert after["closed_at"] is None
    assert after["version"] == resale["version"]


def test_a_fresh_submission_supersedes_the_open_transaction():
    """A second submission on the same unit retires the first one.

    PRD: "Submission also copies `seller_household_id` from the unit's `occupant_household_id`, sets `state` to `SUBMITTED`, moves any other `SUBMITTED` resale of the same unit `SUBMITTED → SUPERSEDED`, and increments the unit's `version` by one — which is why a second submission must supply a freshly read `expected_unit_version`."

    Design: Corner/state_machines/invalid_transitions_and_supersession_across_the_resale_track
    """
    ctx = _ownership_unit_ready_for_resale()
    before = fixtures.live_unit(ctx["unit"]["id"])
    first = validate_success(_submit_resale(ctx, 32000000), expected_status=201)
    assert first["seller_household_id"] == ctx["seller"]["id"]
    after_first = fixtures.live_unit(ctx["unit"]["id"])
    assert after_first["version"] == before["version"] + 1

    second = validate_success(_submit_resale(ctx, 31500000), expected_status=201)

    assert second["state"] == "SUBMITTED"
    assert second["seller_household_id"] == ctx["seller"]["id"]
    superseded = get_success_data(api_client.get_resale(first["id"], headers=HCO))
    assert superseded["state"] == "SUPERSEDED"
    assert superseded["version"] == first["version"] + 1
    assert fixtures.live_unit(ctx["unit"]["id"])["version"] == after_first["version"] + 1


def test_price_approval_opens_the_right_of_first_refusal_window():
    """Approval advances the transaction and starts the city's 30-day clock.

    PRD: "Approval moves the transaction `SUBMITTED → PRICE_APPROVED`, stamps `price_approved_at` with the current logical instant and `price_approved_by_user_id` with the acting `X-User-ID`, and opens the city's right of first refusal by setting `rofr_deadline` to `price_approved_at` plus 30 days."

    Design: Corner/state_machines/invalid_transitions_and_supersession_across_the_resale_track
    """
    ctx = _ownership_unit_ready_for_resale()
    resale = validate_success(_submit_resale(ctx, 32000000), expected_status=201)

    approved = validate_success(
        api_client.approve_resale_price(resale["id"], headers=HCO)
    )

    assert approved["state"] == "PRICE_APPROVED"
    assert same_instant(approved["price_approved_at"], "2026-08-01T00:00:00Z")
    assert approved["price_approved_by_user_id"] == HCO["X-User-ID"]
    assert same_instant(approved["rofr_deadline"], "2026-08-31T00:00:00Z")
    assert approved["version"] == resale["version"] + 1


def test_an_explicit_waiver_moves_the_transaction_to_rofr_waived():
    """A waived right of first refusal hands the sale back to the private market.

    PRD: "`WAIVE` moves the transaction `PRICE_APPROVED → ROFR_WAIVED` and the private sale proceeds."

    Design: Corner/state_machines/invalid_transitions_and_supersession_across_the_resale_track
    """
    ctx = _ownership_unit_ready_for_resale()
    resale = validate_success(_submit_resale(ctx, 32000000), expected_status=201)
    approved = get_success_data(
        api_client.approve_resale_price(resale["id"], headers=HCO)
    )

    waived = validate_success(
        api_client.rofr_decision(resale["id"], "WAIVE", headers=PA)
    )

    assert waived["state"] == "ROFR_WAIVED"
    # This waiver was a decision, not the clock's own doing.
    assert waived["rofr_auto_waived"] is False
    assert waived["version"] == approved["version"] + 1
    # The city declined to buy, so the unit's frozen basis is untouched.
    unit = fixtures.live_unit(ctx["unit"]["id"])
    assert unit["original_purchase_price_cents"] == 32500000
    assert_unit_dimensions(unit, restriction_state="RECORDED")


def test_a_waived_resale_refuses_a_second_decision_re_approval_and_closing():
    """ROFR_WAIVED admits buyer certification alone, and nothing else.

    PRD: "The resale transaction's `state` permits the operation — price approval from `SUBMITTED`, the right-of-first-refusal decision from `PRICE_APPROVED`, buyer certification from `ROFR_WAIVED`, closing from either `BUYER_CERTIFIED` or `ROFR_EXERCISED` — else `ERR_RESALE_STATE_INVALID`."

    Design: Corner/state_machines/invalid_transitions_and_supersession_across_the_resale_track
    """
    ctx = _ownership_unit_ready_for_resale()
    resale = validate_success(_submit_resale(ctx, 32000000), expected_status=201)
    get_success_data(api_client.approve_resale_price(resale["id"], headers=HCO))
    waived = get_success_data(api_client.rofr_decision(resale["id"], "WAIVE", headers=PA))

    validate_error(
        api_client.rofr_decision(resale["id"], "EXERCISE", headers=PA),
        ApiErrorId.ERR_RESALE_STATE_INVALID.value,
    )
    validate_error(
        api_client.approve_resale_price(resale["id"], headers=HCO2),
        ApiErrorId.ERR_RESALE_STATE_INVALID.value,
    )
    validate_error(
        api_client.close_resale(resale["id"], headers=HCO),
        ApiErrorId.ERR_RESALE_STATE_INVALID.value,
    )

    after = get_success_data(api_client.get_resale(resale["id"], headers=HCO))
    assert after["state"] == "ROFR_WAIVED"
    assert after["closed_at"] is None
    assert after["version"] == waived["version"]
