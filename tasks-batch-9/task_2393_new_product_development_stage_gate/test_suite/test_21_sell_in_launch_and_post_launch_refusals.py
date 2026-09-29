"""Trade presentation guards, the launch date lock ladder, launch timing and post-launch gates."""
import pytest

from test_helpers import (
    book_presentation,
    create_formulation,
    decide_deliverable,
    decide_label,
    deliverable_by_type,
    draft_label,
    intake_project,
    label_approval_payload,
    launch_lock_payload,
    open_business_case,
    open_case_with_line,
    open_reset_window,
    post_launch_period_payload,
    present_presentation,
    read_formulation,
    read_project,
    read_window,
    record_outcome,
    register_retailer,
    register_stage_gate,
    run_gate_session,
    screen_project,
    sell_in_presentation_payload,
    set_clock,
    setup_authorized_project,
    setup_cleared_formulation,
    setup_launch_locked_project,
    setup_launched_project,
    setup_pilot_qualified_project,
    submit_deliverable,
    submit_label,
    validate_error,
    validate_paginated,
    validate_success,
    waive_deliverable,
)

GROCERY_RETAILER = {"name": "MidStates Grocery", "channel": "GROCERY",
                    "acv_contribution_pct": 30.00, "presentation_lead_days": 14}
CLUB_RETAILER = {"name": "BulkClub Depot", "channel": "CLUB",
                 "acv_contribution_pct": 12.00, "presentation_lead_days": 14}
SNACK_WINDOW = {"category": "SNACK", "window_start": "2026-10-05T00:00:00Z",
                "window_end": "2026-11-30T00:00:00Z", "max_presentations": 2}
BEVERAGE_WINDOW = {"category": "BEVERAGE", "window_start": "2026-10-05T00:00:00Z",
                   "window_end": "2026-11-30T00:00:00Z", "max_presentations": 2}
PRESENT_AT = "2026-09-18T09:00:00Z"


def _qualified_snack_project_with_windows():
    """A pilot-qualified snack project, a grocery retailer and a club retailer."""
    ctx = setup_pilot_qualified_project(
        category="SNACK", project_type="LINE_EXTENSION",
        project_overrides={"name": "Toffee Crunch Bites"},
        owner_user_id="lead-si", chair_user_id="chair-si",
    )
    grocery = register_retailer(**GROCERY_RETAILER)
    club = register_retailer(**CLUB_RETAILER)
    ctx.update({
        "grocery": grocery,
        "club": club,
        "snack_window": open_reset_window(grocery["id"], **SNACK_WINDOW),
        "beverage_window": open_reset_window(grocery["id"], **BEVERAGE_WINDOW),
        "club_window": open_reset_window(club["id"], **SNACK_WINDOW),
    })
    return ctx


def _authorized_snack_project_with_a_waived_distribution_plan():
    """A LAUNCH_READY, AUTHORIZED snack project whose distribution readiness was waived.

    Gate 3 demands manufacturing and distribution readiness only; manufacturing is approved
    and distribution is waived, so the gate closes while launch readiness stays short.
    The project's pack artwork is left in DRAFT.
    """
    set_clock("2026-08-03T00:00:00Z")
    gate2 = register_stage_gate(gate_number=2, category="SNACK", stage_from="SCREENED",
                                stage_to="PILOT_QUALIFIED")
    gate3 = register_stage_gate(
        gate_number=3, category="SNACK", stage_from="PILOT_QUALIFIED",
        stage_to="LAUNCH_READY",
        required_deliverable_types=["MANUFACTURING_READINESS", "DISTRIBUTION_READINESS"],
    )
    project = intake_project(owner_user_id="lead-ll", name="Toffee Crunch Bites",
                             category="SNACK", project_type="LINE_EXTENSION")
    project_id = project["id"]
    screen_project(project_id, chair_user_id="chair-ll")
    case, line = open_case_with_line(project_id)
    formulation_ctx = setup_cleared_formulation(project_id, line_code="TOL-41")
    run_gate_session(project_id, gate2["id"],
                     votes=(("OPERATIONS", "APPROVE", "rev-ops-ll"),),
                     chair_user_id="chair-ll")

    manufacturing = deliverable_by_type(project_id, "MANUFACTURING_READINESS",
                                        gate_id=gate3["id"])
    submit_deliverable(manufacturing["id"], submitter_user_id="lead-ll-sub")
    decide_deliverable(manufacturing["id"], "APPROVE", decider_user_id="rev-ll-dec")
    distribution = deliverable_by_type(project_id, "DISTRIBUTION_READINESS",
                                       gate_id=gate3["id"])
    waive_deliverable(distribution["id"], reason="Third-party logistics contract carried over",
                      chair_user_id="chair-ll")
    run_gate_session(project_id, gate3["id"],
                     votes=(("OPERATIONS", "APPROVE", "rev-ops-ll"),),
                     chair_user_id="chair-ll")

    retailer = register_retailer(**GROCERY_RETAILER)
    snack_window = open_reset_window(retailer["id"], **SNACK_WINDOW)
    beverage_window = open_reset_window(retailer["id"], **BEVERAGE_WINDOW)
    label = draft_label(project_id, formulation_ctx["formulation"]["id"])
    presentation = book_presentation(project_id, retailer["id"], snack_window["id"],
                                     scheduled_at=PRESENT_AT, proposed_sku_count=4)
    set_clock(PRESENT_AT)
    present_presentation(presentation["id"])
    record_outcome(presentation["id"], "ACCEPTED", accepted_sku_count=4)

    return {
        "gate2": gate2,
        "gate3": gate3,
        "business_case": case,
        "forecast_line": line,
        "formulation": formulation_ctx["formulation"],
        "label_approval": label,
        "retailer": retailer,
        "snack_window": snack_window,
        "beverage_window": beverage_window,
        "presentation": presentation,
        "project": read_project(project_id),
    }


def test_a_window_from_another_category_is_refused_on_the_right_retailer(
    api, sales_account_manager_headers
):
    """The grocery retailer owns the window, but a beverage reset takes no snack project.

    PRD: "Then the three referential rules of §2.11 apply: the window must belong to the named
    retailer (`ERR_WINDOW_RETAILER_MISMATCH`), the window's `category` must equal the project's
    `category` (`ERR_WINDOW_CATEGORY_MISMATCH`), and the retailer's `channel` must appear as the
    `channel` of a forecast line on the project's authoritative business case
    (`ERR_CHANNEL_NOT_FORECAST`) — binding the sell-in plan back to the volume the business case
    promised."

    Design: Corner/errors/err_sell_in_ladder_guards_window_channel_timing_and_outcome
    """
    ctx = _qualified_snack_project_with_windows()

    response = api.create_sell_in_presentation(
        ctx["project"]["id"],
        sell_in_presentation_payload(ctx["grocery"]["id"], ctx["beverage_window"]["id"],
                                     scheduled_at=PRESENT_AT, proposed_sku_count=4),
        sales_account_manager_headers,
    )

    validate_error(response, "ERR_WINDOW_CATEGORY_MISMATCH", 409)
    assert read_window(ctx["beverage_window"]["id"])["booked_slot_count"] == 0
    project = read_project(ctx["project"]["id"])
    assert project["commercial_status"] == "NOT_STARTED"
    _, meta = validate_paginated(
        api.list_sell_in_presentations(sales_account_manager_headers,
                                      params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 0


def test_a_retailer_whose_channel_is_not_forecast_is_refused(
    api, sales_account_manager_headers
):
    """The club window matches the category, but no forecast line promises club volume.

    PRD: "Then the three referential rules of §2.11 apply: the window must belong to the named
    retailer (`ERR_WINDOW_RETAILER_MISMATCH`), the window's `category` must equal the project's
    `category` (`ERR_WINDOW_CATEGORY_MISMATCH`), and the retailer's `channel` must appear as the
    `channel` of a forecast line on the project's authoritative business case
    (`ERR_CHANNEL_NOT_FORECAST`) — binding the sell-in plan back to the volume the business case
    promised."

    Design: Corner/errors/err_sell_in_ladder_guards_window_channel_timing_and_outcome
    """
    ctx = _qualified_snack_project_with_windows()
    assert ctx["forecast_line"]["channel"] == "GROCERY"

    response = api.create_sell_in_presentation(
        ctx["project"]["id"],
        sell_in_presentation_payload(ctx["club"]["id"], ctx["club_window"]["id"],
                                     scheduled_at=PRESENT_AT, proposed_sku_count=4),
        sales_account_manager_headers,
    )

    validate_error(response, "ERR_CHANNEL_NOT_FORECAST", 409)
    assert read_window(ctx["club_window"]["id"])["booked_slot_count"] == 0
    accepted = validate_success(
        api.create_sell_in_presentation(
            ctx["project"]["id"],
            sell_in_presentation_payload(ctx["grocery"]["id"], ctx["snack_window"]["id"],
                                         scheduled_at=PRESENT_AT, proposed_sku_count=4),
            sales_account_manager_headers,
        ),
        201,
    )
    assert accepted["status"] == "PLANNED", "the forecast grocery channel is admissible"
    assert read_window(ctx["snack_window"]["id"])["booked_slot_count"] == 1


def test_a_presentation_cannot_be_reported_before_its_scheduled_instant(
    api, sales_account_manager_headers
):
    """Too early is not due; the scheduled instant itself works; a repeat is out of state.

    PRD: "A `PLANNED` presentation is marked as presented once the current instant has reached
    its `scheduled_at`; earlier attempts answer `ERR_PRESENTATION_NOT_DUE` (409)."

    PRD: "**State** — the subject row and its governing parents admit the requested transition,
    else the entity's `ERR_..._INVALID_STATE` code (409)."

    Design: Corner/errors/err_sell_in_ladder_guards_window_channel_timing_and_outcome
    """
    ctx = _qualified_snack_project_with_windows()
    booked = book_presentation(ctx["project"]["id"], ctx["grocery"]["id"],
                               ctx["snack_window"]["id"], scheduled_at=PRESENT_AT,
                               proposed_sku_count=4)

    validate_error(
        api.present_sell_in_presentation(booked["id"], {}, sales_account_manager_headers),
        "ERR_PRESENTATION_NOT_DUE",
        409,
    )
    assert validate_success(
        api.get_sell_in_presentation(booked["id"], sales_account_manager_headers)
    )["status"] == "PLANNED"

    set_clock(PRESENT_AT)
    presented = validate_success(
        api.present_sell_in_presentation(booked["id"], {}, sales_account_manager_headers)
    )

    assert presented["status"] == "PRESENTED", "the scheduled instant itself is due"
    validate_error(
        api.present_sell_in_presentation(booked["id"], {}, sales_account_manager_headers),
        "ERR_PRESENTATION_INVALID_STATE",
        409,
    )
    assert read_project(ctx["project"]["id"])["commercial_status"] == "PRESENTED"


def test_accepted_skus_may_not_exceed_the_proposed_count(api, sales_account_manager_headers):
    """Five accepted against four proposed is refused; four exactly is authorised.

    PRD: "`ACCEPTED` requires `accepted_sku_count` to be present and to not exceed
    `proposed_sku_count`; one more than proposed answers `ERR_ACCEPTED_SKU_EXCEEDS_PROPOSED` (422)
    while equality is accepted."

    Design: Corner/errors/err_sell_in_ladder_guards_window_channel_timing_and_outcome
    """
    ctx = _qualified_snack_project_with_windows()
    booked = book_presentation(ctx["project"]["id"], ctx["grocery"]["id"],
                               ctx["snack_window"]["id"], scheduled_at=PRESENT_AT,
                               proposed_sku_count=4)
    set_clock(PRESENT_AT)
    present_presentation(booked["id"])

    response = api.record_sell_in_outcome(
        booked["id"], {"outcome": "ACCEPTED", "accepted_sku_count": 5},
        sales_account_manager_headers,
    )

    validate_error(response, "ERR_ACCEPTED_SKU_EXCEEDS_PROPOSED", 422)
    refused = validate_success(
        api.get_sell_in_presentation(booked["id"], sales_account_manager_headers)
    )
    assert refused["status"] == "PRESENTED"
    assert refused["accepted_sku_count"] is None
    assert read_project(ctx["project"]["id"])["commercial_status"] == "PRESENTED"

    settled = validate_success(
        api.record_sell_in_outcome(booked["id"],
                                   {"outcome": "ACCEPTED", "accepted_sku_count": 4},
                                   sales_account_manager_headers)
    )

    assert settled["status"] == "ACCEPTED"
    assert settled["accepted_sku_count"] == 4
    project = read_project(ctx["project"]["id"])
    assert project["commercial_status"] == "AUTHORIZED"
    assert project["authorized_acv_pct"] == pytest.approx(30.00, abs=0.01)


def test_the_lock_refuses_a_window_from_another_category_first(api, gate_chair_headers):
    """The category rule is the first of the five lock conditions to bite.

    PRD: "Five substantive conditions then apply, in band order. The window's `category` must
    equal the project's `category`, else `ERR_WINDOW_CATEGORY_MISMATCH` (409)."

    Design: Corner/errors/err_launch_lock_ladder_runs_window_label_dates_then_readiness
    """
    ctx = _authorized_snack_project_with_a_waived_distribution_plan()

    response = api.lock_launch_date(
        ctx["project"]["id"],
        launch_lock_payload("2026-11-10T00:00:00Z", ctx["beverage_window"]["id"]),
        gate_chair_headers,
    )

    validate_error(response, "ERR_WINDOW_CATEGORY_MISMATCH", 409)
    project = read_project(ctx["project"]["id"])
    assert project["launch_date"] is None
    assert project["shelf_reset_window_id"] is None
    assert project["commercial_status"] == "AUTHORIZED"
    assert project["dev_status"] == "LAUNCH_READY"


def test_the_lock_refuses_an_unapproved_label_before_it_looks_at_the_dates(
    api, gate_chair_headers
):
    """With artwork still in DRAFT, a date outside the window still reports the label error.

    PRD: "An `APPROVED` or `CONDITIONAL` label approval must exist on the project's current
    formulation, else `ERR_LABEL_NOT_APPROVED` (409) — regulatory, claims and label clearance
    genuinely gates commercialisation."

    Design: Corner/errors/err_launch_lock_ladder_runs_window_label_dates_then_readiness
    """
    ctx = _authorized_snack_project_with_a_waived_distribution_plan()
    assert ctx["label_approval"]["status"] == "DRAFT"

    response = api.lock_launch_date(
        ctx["project"]["id"],
        launch_lock_payload("2026-12-15T00:00:00Z", ctx["snack_window"]["id"]),
        gate_chair_headers,
    )

    validate_error(response, "ERR_LABEL_NOT_APPROVED", 409)
    assert read_project(ctx["project"]["id"])["launch_date"] is None
    assert read_formulation(ctx["formulation"]["id"])["status"] == "SHELF_LIFE_CLEARED"


def test_with_the_label_cleared_containment_outranks_the_lock_lead_time(
    api, gate_chair_headers
):
    """A date outside the window reports containment; a date inside it reports lead time.

    PRD: "The `launch_date` must fall inside the closed interval from the window's
    `window_start` to its `window_end`, both endpoints inclusive, else
    `ERR_LAUNCH_DATE_OUTSIDE_WINDOW` (409)."

    PRD: "The `launch_date` must be at least 45 whole days after the current instant, else
    `ERR_LOCK_LEAD_TIME_VIOLATION` (409); because containment is checked first, a date both
    outside the window and too soon reports the containment error."

    Design: Corner/errors/err_launch_lock_ladder_runs_window_label_dates_then_readiness
    """
    ctx = _authorized_snack_project_with_a_waived_distribution_plan()
    submit_label(ctx["label_approval"]["id"])
    cleared = decide_label(ctx["label_approval"]["id"], "APPROVE")
    assert cleared["status"] == "APPROVED"

    validate_error(
        api.lock_launch_date(
            ctx["project"]["id"],
            launch_lock_payload("2026-12-15T00:00:00Z", ctx["snack_window"]["id"]),
            gate_chair_headers,
        ),
        "ERR_LAUNCH_DATE_OUTSIDE_WINDOW",
        409,
    )
    validate_error(
        api.lock_launch_date(
            ctx["project"]["id"],
            launch_lock_payload("2026-10-10T00:00:00Z", ctx["snack_window"]["id"]),
            gate_chair_headers,
        ),
        "ERR_LOCK_LEAD_TIME_VIOLATION",
        409,
    )

    project = read_project(ctx["project"]["id"])
    assert project["launch_date"] is None
    assert project["commercial_status"] == "AUTHORIZED"


def test_a_waived_readiness_item_leaves_the_launch_lock_incomplete(
    api, gate_chair_headers, portfolio_admin_headers
):
    """A waiver satisfies gate completeness but leaves launch readiness at 58.33.

    PRD: "The denominator is the sum of the weights over that required set; the numerator is the
    sum of the weights over those required types whose checklist item is `APPROVED`, and a
    `WAIVED` item contributes nothing to the numerator even though it satisfies gate
    completeness."

    PRD: "And `launch_readiness_pct` must be exactly `100.00`, else
    `ERR_LAUNCH_READINESS_INCOMPLETE` (422) — manufacturing, distribution, marketing and sales
    must all be approved before a date can be committed to a retailer."

    Design: Corner/errors/err_launch_lock_ladder_runs_window_label_dates_then_readiness
    """
    ctx = _authorized_snack_project_with_a_waived_distribution_plan()
    submit_label(ctx["label_approval"]["id"])
    decide_label(ctx["label_approval"]["id"], "APPROVE")

    response = api.lock_launch_date(
        ctx["project"]["id"],
        launch_lock_payload("2026-11-10T00:00:00Z", ctx["snack_window"]["id"]),
        gate_chair_headers,
    )

    validate_error(response, "ERR_LAUNCH_READINESS_INCOMPLETE", 422)
    readiness = validate_success(
        api.get_launch_readiness(ctx["project"]["id"], portfolio_admin_headers)
    )
    assert readiness["launch_readiness_pct"] == pytest.approx(58.33, abs=0.01)
    assert readiness["blocking_deliverable_types"] == ["DISTRIBUTION_READINESS"]
    assert readiness["launch_date"] is None
    project = read_project(ctx["project"]["id"])
    assert project["commercial_status"] == "AUTHORIZED"
    assert project["launch_date"] is None


def test_the_launch_cannot_be_pulled_forward_of_the_locked_date(api, gate_chair_headers):
    """The launch is refused before the locked date and accepted the instant it arrives.

    PRD: "A `GateChair` launches the project once the current instant has reached the locked
    `launch_date`; pulling the date forward answers `ERR_LAUNCH_DATE_NOT_REACHED` (409)."

    PRD: "`dev_status` goes `LAUNCH_READY → LAUNCHED` and `commercial_status` goes
    `LAUNCH_LOCKED → SHIPPED` in the same write."

    Design: Corner/errors/err_launch_and_period_guards_hold_the_clock_and_the_sequence
    """
    ctx = setup_launch_locked_project()
    assert ctx["project"]["commercial_status"] == "LAUNCH_LOCKED"

    validate_error(api.launch_project(ctx["project"]["id"], {}, gate_chair_headers),
                   "ERR_LAUNCH_DATE_NOT_REACHED", 409)
    held = read_project(ctx["project"]["id"])
    assert held["dev_status"] == "LAUNCH_READY"
    assert held["commercial_status"] == "LAUNCH_LOCKED"

    set_clock(ctx["launch_date"])
    launched = validate_success(
        api.launch_project(ctx["project"]["id"], {}, gate_chair_headers)
    )

    assert launched["dev_status"] == "LAUNCHED"
    assert launched["commercial_status"] == "SHIPPED"


def test_post_launch_periods_must_arrive_as_the_existing_count_plus_one(
    api, portfolio_admin_headers
):
    """Period 2 cannot open the history and period 1 cannot be reported twice.

    PRD: "and `period_index` must be exactly the project's existing period count plus one, else
    `ERR_PERIOD_SEQUENCE_VIOLATION` (409), so periods arrive in order with no gaps and no
    repeats."

    PRD: "The plan basis is `plan_units_per_period`, the locked case's `annual_units` divided by
    the four periods in a year, rounded half up to two decimal places."

    Design: Corner/errors/err_launch_and_period_guards_hold_the_clock_and_the_sequence
    """
    ctx = setup_launched_project()
    project_id = ctx["project"]["id"]

    validate_error(
        api.create_post_launch_period(project_id, post_launch_period_payload(2),
                                      portfolio_admin_headers),
        "ERR_PERIOD_SEQUENCE_VIOLATION",
        409,
    )
    first = validate_success(
        api.create_post_launch_period(project_id, post_launch_period_payload(1),
                                      portfolio_admin_headers),
        201,
    )
    assert first["period_index"] == 1
    assert first["plan_units_per_period"] == pytest.approx(38304.00, abs=0.01)

    validate_error(
        api.create_post_launch_period(project_id, post_launch_period_payload(1),
                                      portfolio_admin_headers),
        "ERR_PERIOD_SEQUENCE_VIOLATION",
        409,
    )
    _, meta = validate_paginated(
        api.list_post_launch_periods(project_id, portfolio_admin_headers)
    )
    assert meta["total_count"] == 1, "no gap and no repeat ever entered the history"


def test_a_case_raised_after_the_gate_lock_leaves_the_locked_row_untouched(
    api, gate_chair_headers, portfolio_admin_headers
):
    """The locked case survives, the new draft takes authority, and the launch still runs.

    PRD: "Opening a new case supersedes the project's previous case: a prior case in `DRAFT`
    moves `DRAFT → SUPERSEDED`, and a prior case in `COMPUTED` moves `COMPUTED → SUPERSEDED` —
    but only if it is not `LOCKED`. A `LOCKED` case is never superseded, which is precisely why
    raising a new case after a gate lock leaves the project without a locked authoritative case
    and blocks post-launch reporting (§3.9)."

    Design: Corner/errors/err_post_launch_requires_a_locked_authoritative_case
    """
    ctx = setup_authorized_project()
    project_id = ctx["project"]["id"]
    locked = validate_success(
        api.get_business_case(ctx["business_case"]["id"], portfolio_admin_headers)
    )
    assert locked["status"] == "LOCKED"

    displacing = open_business_case(project_id)

    assert displacing["case_type"] == "FINAL"
    assert displacing["status"] == "DRAFT"
    assert validate_success(
        api.get_business_case(ctx["business_case"]["id"], portfolio_admin_headers)
    )["status"] == "LOCKED", "the locked case was never superseded"

    lockedin = validate_success(
        api.lock_launch_date(project_id,
                             launch_lock_payload("2026-11-05T00:00:00Z", ctx["window"]["id"]),
                             gate_chair_headers)
    )
    assert lockedin["commercial_status"] == "LAUNCH_LOCKED"
    set_clock("2026-11-05T00:00:00Z")
    launched = validate_success(api.launch_project(project_id, {}, gate_chair_headers))
    assert launched["dev_status"] == "LAUNCHED"
    assert launched["commercial_status"] == "SHIPPED"


def test_post_launch_reporting_is_refused_for_want_of_a_locked_authoritative_case(
    api, gate_chair_headers, portfolio_admin_headers
):
    """A correctly numbered first period is still refused because authority moved to a draft.

    PRD: "Two gates precede the arithmetic: the project's authoritative business case must be in
    `status` `LOCKED`, else `ERR_NO_LOCKED_BUSINESS_CASE` (409) — which bites both when no gate
    ever locked a case and when a newer case was raised after the lock, displacing the locked one
    as authoritative; and `period_index` must be exactly the project's existing period count plus
    one, else `ERR_PERIOD_SEQUENCE_VIOLATION` (409), so periods arrive in order with no gaps and
    no repeats."

    Design: Corner/errors/err_post_launch_requires_a_locked_authoritative_case
    """
    ctx = setup_authorized_project()
    project_id = ctx["project"]["id"]
    open_business_case(project_id)
    validate_success(
        api.lock_launch_date(project_id,
                             launch_lock_payload("2026-11-05T00:00:00Z", ctx["window"]["id"]),
                             gate_chair_headers)
    )
    set_clock("2026-11-05T00:00:00Z")
    validate_success(api.launch_project(project_id, {}, gate_chair_headers))

    response = api.create_post_launch_period(project_id, post_launch_period_payload(1),
                                             portfolio_admin_headers)

    validate_error(response, "ERR_NO_LOCKED_BUSINESS_CASE", 409)
    _, meta = validate_paginated(
        api.list_post_launch_periods(project_id, portfolio_admin_headers)
    )
    assert meta["total_count"] == 0, "the refused period was never stored"
    project = read_project(project_id)
    assert project["post_launch_decision"] is None
    assert project["dev_status"] == "LAUNCHED"


def test_a_label_must_describe_a_formulation_of_its_own_project(
    api, innovation_lead_headers, portfolio_admin_headers
):
    """Naming a sibling project's revision is a mismatch, not a not-found.

    PRD: "The named formulation must belong to the project the draft is created under, else
    `ERR_FORMULATION_PROJECT_MISMATCH` (409)."

    Design: Corner/errors/err_label_ladder_guards_ownership_then_conditional_payload
    """
    set_clock("2026-08-03T00:00:00Z")
    mine = intake_project(owner_user_id="lead-lb", name="Toffee Crunch Bites",
                          category="SNACK", project_type="LINE_EXTENSION")
    theirs = intake_project(owner_user_id="lead-lb2", name="Salted Caramel Wafers",
                            category="SNACK", project_type="LINE_EXTENSION")
    create_formulation(mine["id"])
    borrowed = create_formulation(theirs["id"])

    response = api.create_label_approval(
        mine["id"], label_approval_payload(borrowed["id"]), innovation_lead_headers
    )

    validate_error(response, "ERR_FORMULATION_PROJECT_MISMATCH", 409)
    _, meta = validate_paginated(
        api.list_label_approvals(portfolio_admin_headers, params={"project_id": mine["id"]})
    )
    assert meta["total_count"] == 0, "the refused draft was never stored"
    assert read_formulation(borrowed["id"])["status"] == "DRAFT"


def test_a_conditional_regulatory_decision_must_name_the_unsupported_claims(
    api, regulatory_approver_headers, portfolio_admin_headers
):
    """Approving with changes needs the flagged claims; an empty or absent list is refused.

    PRD: "`APPROVE_WITH_CHANGES` moves it `IN_REVIEW → CONDITIONAL` and requires a non-empty
    `unsupported_claims` array naming the claims that were not substantiated — an empty or absent
    list answers `ERR_UNSUPPORTED_CLAIMS_REQUIRED` (422)."

    Design: Corner/errors/err_label_ladder_guards_ownership_then_conditional_payload
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-uc", name="Toffee Crunch Bites",
                             category="SNACK", project_type="LINE_EXTENSION")
    ctx = setup_cleared_formulation(project["id"], line_code="TOL-41")
    label = draft_label(project["id"], ctx["formulation"]["id"],
                        claims=["Toffee crunch, no artificial colours", "High in fibre"])
    submit_label(label["id"])

    validate_error(
        api.decide_label_approval(
            label["id"], {"decision": "APPROVE_WITH_CHANGES", "unsupported_claims": []},
            regulatory_approver_headers,
        ),
        "ERR_UNSUPPORTED_CLAIMS_REQUIRED",
        422,
    )
    validate_error(
        api.decide_label_approval(label["id"], {"decision": "APPROVE_WITH_CHANGES"},
                                  regulatory_approver_headers),
        "ERR_UNSUPPORTED_CLAIMS_REQUIRED",
        422,
    )
    held = validate_success(api.get_label_approval(label["id"], portfolio_admin_headers))
    assert held["status"] == "IN_REVIEW"
    assert held["unsupported_claims"] == []

    conditional = validate_success(
        api.decide_label_approval(
            label["id"],
            {"decision": "APPROVE_WITH_CHANGES", "unsupported_claims": ["High in fibre"]},
            regulatory_approver_headers,
        )
    )

    assert conditional["status"] == "CONDITIONAL"
    assert len(conditional["unsupported_claims"]) == 1
    assert conditional["unsupported_claims"] == ["High in fibre"]
