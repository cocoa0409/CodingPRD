"""Which refusal wins when one request breaks several rules at once."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    add_forecast_line,
    deliverable_by_type,
    intake_project,
    make_functional_reviewer_headers,
    make_gate_chair_headers,
    open_business_case,
    open_gate_review,
    open_reset_window,
    project_version,
    read_project,
    read_window,
    register_retailer,
    register_stage_gate,
    schedule_gate_review,
    screen_project,
    set_clock,
    setup_pilot_qualified_project,
    setup_screened_project,
    validate_error,
    validate_paginated,
    validate_success,
    waive_deliverable,
)


def test_a_misspelled_enum_is_reported_before_the_unresolvable_gate_reference(api, gate_chair_headers):
    """A checklist item naming both a bad type and a missing gate answers 400, not 404.

    PRD: "4. **Request shape** — the body parses, required fields are present, enum values are
    legal, numbers lie inside their declared ranges and datetimes are ISO 8601. Otherwise
    `ERR_INVALID_REQUEST` (400). Shape validation runs before any body-borne foreign key is
    resolved, so a request that both omits a required field and names a non-existent parent
    answers 400."
    PRD: "The following closed vocabularies are used throughout and any other value is a shape
    violation answering `ERR_INVALID_REQUEST`."
    PRD: "5. **Body foreign-key existence** — every identifier supplied in the body resolves,
    checked left to right in the order the fields are declared for that operation. Answers the
    matching 404 code. This band applies to gate-review scheduling, checklist creation and
    prerequisite setting, pilot-run booking, label drafting, trade-presentation booking and the
    launch date lock."

    Design: Corner/validations/val_invalid_enum_beats_unknown_body_fk_rejected
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(
        owner_user_id="lead-p45", name="Toffee Crunch Bites", brand="GrainWell",
        category="SNACK", project_type="LINE_EXTENSION", strategic_fit_score=8,
        consumer_need_score=7, target_gross_margin_pct=36, category_attractiveness_score=7,
        development_budget_cap_usd=500000.00,
    )

    misspelled = api.create_deliverable(
        project["id"],
        {"gate_id": NON_EXISTENT_UUID, "deliverable_type": "MANUFACTURING_READYNESS",
         "owner_function": "OPERATIONS"},
        gate_chair_headers,
    )
    legal_enum = api.create_deliverable(
        project["id"],
        {"gate_id": NON_EXISTENT_UUID, "deliverable_type": "PILOT_SCALE_UP_REPORT",
         "owner_function": "OPERATIONS"},
        gate_chair_headers,
    )

    validate_error(misspelled, "ERR_INVALID_REQUEST", 400)
    validate_error(legal_enum, "ERR_STAGE_GATE_NOT_FOUND", 404)
    _, meta = validate_paginated(
        api.list_deliverables(gate_chair_headers, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 0, "neither refusal stored a checklist item"
    assert project_version(project["id"]) == project["version"], (
        "a refused create never advances the project row"
    )


def test_an_unknown_project_in_the_path_outranks_an_unusable_body(api, gate_chair_headers,
                                                                 innovation_lead_headers):
    """Writes aimed at a project that does not exist answer 404 before the body is read.

    PRD: "Many operations can fail several ways at once. The server always evaluates checks in the
    following thirteen bands and answers with the **first** violated rule, so the reported error is
    a deterministic function of request and state rather than of implementation order."
    PRD: "3. **Path existence** — every identifier in the URL resolves to a stored row, resolved
    outer to inner, so a nested path with two unknown identifiers reports the outer resource
    first."

    Design: Corner/validations/val_unknown_path_id_beats_invalid_body_not_found
    """
    set_clock("2026-08-03T00:00:00Z")
    intake_project(
        owner_user_id="lead-p34", name="Toffee Crunch Bites", brand="GrainWell",
        category="SNACK", project_type="LINE_EXTENSION", strategic_fit_score=8,
        consumer_need_score=7, target_gross_margin_pct=36, category_attractiveness_score=7,
        development_budget_cap_usd=500000.00,
    )

    missing_fields = api.create_deliverable(
        NON_EXISTENT_UUID, {"owner_function": "BAKING"}, gate_chair_headers
    )
    out_of_range = api.create_concept_test(
        NON_EXISTENT_UUID,
        {"test_type": "MONADIC", "sample_size": 0, "purchase_intent_top2_pct": 700.00,
         "uniqueness_pct": -5.00, "fielded_at": "not-a-date"},
        innovation_lead_headers,
    )

    validate_error(missing_fields, "ERR_PROJECT_NOT_FOUND", 404)
    validate_error(out_of_range, "ERR_PROJECT_NOT_FOUND", 404)
    _, meta = validate_paginated(api.list_projects(gate_chair_headers))
    assert meta["total_count"] == 1, "the one real project is the only stored project"


def test_an_unresolvable_gate_reference_outranks_the_killed_project_state(api, gate_chair_headers):
    """On a killed project the 404 comes first and the 409 waits behind it.

    PRD: "5. **Body foreign-key existence** — every identifier supplied in the body resolves,
    checked left to right in the order the fields are declared for that operation. Answers the
    matching 404 code. This band applies to gate-review scheduling, checklist creation and
    prerequisite setting, pilot-run booking, label drafting, trade-presentation booking and the
    launch date lock."
    PRD: "6. **State** — the subject row and its governing parents admit the requested transition,
    else the entity's `ERR_..._INVALID_STATE` code (409). State is checked **before** optimistic
    concurrency, so a stale version supplied against an already-terminal row reports the state
    error rather than 412."
    PRD: "a score one cent below the floor sets `screening_decision` to `REJECTED` and moves
    `dev_status` `IDEA → KILLED` instead."

    Design: Corner/validations/val_unknown_body_fk_beats_killed_project_state_not_found
    """
    set_clock("2026-08-03T00:00:00Z")
    gate2 = register_stage_gate(category="SNACK", payback_months_max=24)
    project = intake_project(
        owner_user_id="lead-p56", name="Toffee Crunch Thins", brand="GrainWell",
        category="SNACK", project_type="LINE_EXTENSION", strategic_fit_score=6,
        consumer_need_score=6, target_gross_margin_pct=23.99, category_attractiveness_score=6,
        development_budget_cap_usd=500000.00,
    )
    killed = screen_project(project["id"], chair_user_id="chair-p56",
                            screening_notes="Margin too thin to carry the slot.")
    assert killed["screening_score"] == pytest.approx(59.99, abs=0.01)
    assert killed["screening_decision"] == "REJECTED"
    assert killed["dev_status"] == "KILLED"

    unknown_gate = api.create_deliverable(
        project["id"],
        {"gate_id": NON_EXISTENT_UUID, "deliverable_type": "PILOT_SCALE_UP_REPORT",
         "owner_function": "OPERATIONS"},
        gate_chair_headers,
    )
    real_gate = api.create_deliverable(
        project["id"],
        {"gate_id": gate2["id"], "deliverable_type": "PILOT_SCALE_UP_REPORT",
         "owner_function": "OPERATIONS"},
        gate_chair_headers,
    )

    validate_error(unknown_gate, "ERR_STAGE_GATE_NOT_FOUND", 404)
    validate_error(real_gate, "ERR_PROJECT_INVALID_STATE", 409)
    _, meta = validate_paginated(
        api.list_deliverables(gate_chair_headers, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 0, "the killing branch created no checklist at all"


def test_the_owner_is_refused_for_who_he_is_not_for_the_seat_he_duplicates(api):
    """The owner's duplicate ballot answers 403 while a bystander's answers 409.

    PRD: "A project's owner may not vote at its own gate. If the acting `X-User-ID` equals the
    project's `owner_user_id`, the ballot is rejected with `ERR_OWNER_CANNOT_VOTE` (403)."
    PRD: "Only one ballot per `function` per review is permitted: a second ballot naming a seat
    that already voted is rejected with `ERR_DUPLICATE_FUNCTION_VOTE` (409)."
    PRD: "8. **Segregation of duties** — the three rules of §2.1, answering 403. Because this band
    follows state, a decide attempted on a `PENDING` checklist item reports the state error rather
    than the self-approval error."
    PRD: "9. **Business safety** (409) — gate sequencing, single-open-review, unresolved
    conditions, quorum, one ballot per function, prerequisite satisfaction, prerequisite
    acyclicity, the regulatory waiver prohibition, duplicate checklist types, duplicate channel
    lines, configuration uniqueness, pilot line window conflicts and reset window capacity."

    Design: Corner/validations/val_owner_disqualification_beats_duplicate_function_vote_returns_403
    """
    ctx = setup_screened_project(
        category="SNACK", gate_overrides={"quorum_size": 2, "payback_months_max": 24},
        project_overrides={"name": "Toffee Crunch Bites", "brand": "GrainWell"},
        owner_user_id="lead-sod", chair_user_id="chair-sod",
    )
    project_id = ctx["project"]["id"]
    assert ctx["project"]["owner_user_id"] == "lead-sod", (
        "the creating header, not the body, decides who owns the project"
    )
    review = schedule_gate_review(project_id, ctx["gate2"]["id"], chair_user_id="chair-sod",
                                  scheduled_at="2026-08-12T09:00:00Z")
    open_gate_review(review["id"], chair_user_id="chair-sod")
    validate_success(
        api.cast_gate_vote(
            review["id"],
            {"function": "MARKETING", "vote": "APPROVE", "rationale": "Brand fit is clear."},
            make_functional_reviewer_headers("rev-mkt-sod"),
        ),
        201,
    )

    owner_ballot = api.cast_gate_vote(
        review["id"],
        {"function": "MARKETING", "vote": "APPROVE", "rationale": "Agreeing with myself."},
        make_functional_reviewer_headers("lead-sod"),
    )
    bystander_ballot = api.cast_gate_vote(
        review["id"],
        {"function": "MARKETING", "vote": "REJECT",
         "rationale": "Second opinion on the same function."},
        make_functional_reviewer_headers("rev-two-sod"),
    )

    validate_error(owner_ballot, "ERR_OWNER_CANNOT_VOTE", 403)
    validate_error(bystander_ballot, "ERR_DUPLICATE_FUNCTION_VOTE", 409)
    _, meta = validate_paginated(
        api.list_gate_votes(review["id"], make_functional_reviewer_headers("rev-mkt-sod"))
    )
    assert meta["total_count"] == 1, "only the one legitimate MARKETING ballot was stored"
    closing = validate_success(
        api.get_gate_review(review["id"], make_functional_reviewer_headers("rev-mkt-sod"))
    )
    assert closing["vote_count"] == 1
    assert closing["status"] == "IN_SESSION", "quorum of two is still unmet"


def test_borrowing_another_retailers_window_is_reported_before_the_lead_time(
    api, sales_account_manager_headers
):
    """Referential agreement is settled before the calendar on a trade booking.

    PRD: "Then the three referential rules of §2.11 apply: the window must belong to the named
    retailer (`ERR_WINDOW_RETAILER_MISMATCH`), the window's `category` must equal the project's
    `category` (`ERR_WINDOW_CATEGORY_MISMATCH`), and the retailer's `channel` must appear as the
    `channel` of a forecast line on the project's authoritative business case
    (`ERR_CHANNEL_NOT_FORECAST`) — binding the sell-in plan back to the volume the business case
    promised."
    PRD: "Finally the trade-presentation timing rule: `scheduled_at` must precede the window's
    `window_start` by at least the retailer's `presentation_lead_days` whole days, else
    `ERR_PRESENTATION_LEAD_TIME_VIOLATION` (409)."

    Design: Corner/validations/val_window_ownership_beats_presentation_lead_time
    """
    ctx = setup_pilot_qualified_project(
        category="SNACK", gate_overrides={"payback_months_max": 24},
        project_overrides={"name": "Toffee Crunch Bites", "brand": "GrainWell"},
        owner_user_id="lead-wo", chair_user_id="chair-wo",
    )
    grocery = register_retailer(name="MidStates Grocery", channel="GROCERY",
                               acv_contribution_pct=30.00, presentation_lead_days=14)
    mass = register_retailer(name="ValueMart", channel="MASS", acv_contribution_pct=25.00,
                             presentation_lead_days=14)
    grocery_window = open_reset_window(grocery["id"], category="SNACK",
                                       window_start="2026-10-05T00:00:00Z",
                                       window_end="2026-11-30T00:00:00Z", max_presentations=2)
    mass_window = open_reset_window(mass["id"], category="SNACK",
                                    window_start="2026-10-05T00:00:00Z",
                                    window_end="2026-11-30T00:00:00Z", max_presentations=2)
    assert ctx["project"]["dev_status"] == "PILOT_QUALIFIED"

    borrowed_window = api.create_sell_in_presentation(
        ctx["project"]["id"],
        {"retailer_id": grocery["id"], "shelf_reset_window_id": mass_window["id"],
         "scheduled_at": "2026-10-01T09:00:00Z", "proposed_sku_count": 4},
        sales_account_manager_headers,
    )
    own_window = api.create_sell_in_presentation(
        ctx["project"]["id"],
        {"retailer_id": grocery["id"], "shelf_reset_window_id": grocery_window["id"],
         "scheduled_at": "2026-10-01T09:00:00Z", "proposed_sku_count": 4},
        sales_account_manager_headers,
    )

    validate_error(borrowed_window, "ERR_WINDOW_RETAILER_MISMATCH", 409)
    validate_error(own_window, "ERR_PRESENTATION_LEAD_TIME_VIOLATION", 409)
    _, meta = validate_paginated(
        api.list_sell_in_presentations(sales_account_manager_headers,
                                       params={"project_id": ctx["project"]["id"]})
    )
    assert meta["total_count"] == 0, "neither refused booking was stored"
    assert read_window(grocery_window["id"])["booked_slot_count"] == 0
    assert read_window(mass_window["id"])["booked_slot_count"] == 0


def test_an_incomplete_checklist_masks_the_missed_financial_hurdle(api):
    """Two 422s on the same close are separated only by their order of evaluation.

    PRD: "Both passing branches — and only the passing branches — must clear three further bars,
    evaluated in this order: `deliverable_completeness_pct` must be exactly `100.00`, else
    `ERR_DELIVERABLE_CHECKLIST_INCOMPLETE` (422); `readiness_index` must be at least the gate's
    `readiness_floor_index`, else `ERR_GATE_READINESS_BELOW_FLOOR` (422); and the authoritative
    business case must clear all three financial hurdles, else
    `ERR_BUSINESS_CASE_HURDLE_NOT_MET` (422)."
    PRD: "Within bands 12 and 13, a passing gate close evaluates checklist completeness first,
    then the readiness floor, then the financial hurdles — so an incomplete checklist masks a low
    readiness index, and a low readiness index masks a missed hurdle."
    PRD: "A `WAIVED` item counts as **satisfied** for gate checklist completeness but contributes
    **nothing** to launch readiness — waiving a manufacturing readiness plan lets a gate close but
    will never let a launch date lock."
    PRD: "A gate's passing branches require the project's authoritative case to clear all three of
    the gate's bars together: `npv_usd` at or above `npv_hurdle_usd`, `payback_months` at or below
    `payback_months_max`, and `gross_margin_pct` at or above `gross_margin_floor_pct`."

    Design: Corner/validations/val_checklist_completeness_beats_hurdle_on_close
    """
    ctx = setup_screened_project(
        category="SNACK",
        gate_overrides={"required_deliverable_types": ["PILOT_SCALE_UP_REPORT"],
                        "quorum_size": 1, "npv_hurdle_usd": 9999999.00,
                        "payback_months_max": 24},
        project_overrides={"name": "Toffee Crunch Bites", "brand": "GrainWell"},
        owner_user_id="lead-cc", chair_user_id="chair-cc",
    )
    project_id = ctx["project"]["id"]
    case = open_business_case(project_id, variant_mode="BOTTOM_UP",
                             category_size_units_year=5000000, target_share_pct=3.00,
                             cogs_per_unit_usd=3.2000, slotting_fees_usd=50000.00,
                             capex_usd=300000.00, discount_rate_pct=9.00)
    line = add_forecast_line(case["id"], channel="GROCERY", store_count=2400,
                             base_velocity_units_per_store_week=1.20, promo_weeks=4,
                             promo_lift_pct=30.00, list_price_usd=5.7500)
    assert line["channel"] == "GROCERY", "the case has the one channel line it needs"
    pending_item = deliverable_by_type(project_id, "PILOT_SCALE_UP_REPORT",
                                       gate_id=ctx["gate2"]["id"])
    assert pending_item is not None and pending_item["status"] == "PENDING"
    review = schedule_gate_review(project_id, ctx["gate2"]["id"], chair_user_id="chair-cc",
                                  scheduled_at="2026-08-12T09:00:00Z")
    open_gate_review(review["id"], chair_user_id="chair-cc")
    validate_success(
        api.cast_gate_vote(
            review["id"],
            {"function": "OPERATIONS", "vote": "APPROVE",
             "rationale": "Scale-up looks feasible."},
            make_functional_reviewer_headers("rev-ops-cc"),
        ),
        201,
    )
    chair_headers = make_gate_chair_headers("chair-cc")

    paperwork_first = api.close_gate_review(review["id"], {}, chair_headers)
    still_open = validate_success(api.get_gate_review(review["id"], chair_headers))
    waive_deliverable(pending_item["id"], reason="Scale-up evidence accepted verbally",
                      chair_user_id="chair-cc")
    money_second = api.close_gate_review(review["id"], {}, chair_headers)

    validate_error(paperwork_first, "ERR_DELIVERABLE_CHECKLIST_INCOMPLETE", 422)
    assert still_open["status"] == "IN_SESSION"
    assert still_open["decision"] is None
    assert still_open["closed_at"] is None
    validate_error(money_second, "ERR_BUSINESS_CASE_HURDLE_NOT_MET", 422)
    settled_case = validate_success(api.get_business_case(case["id"], chair_headers))
    assert settled_case["npv_usd"] < 9999999.00, "the hurdle is missed by a wide margin"
    assert settled_case["payback_months"] <= 24, "payback was never the failing bar"
    assert settled_case["gross_margin_pct"] >= 0.00, "the margin floor was never the failing bar"
    assert settled_case["status"] == "COMPUTED", "no partial gate-close effect leaked"
    refused = read_project(project_id)
    assert refused["dev_status"] == "SCREENED"
    assert refused["next_gate_number"] == 2


def test_only_the_three_declared_writes_carry_a_version_token(api, innovation_lead_headers,
                                                              gate_chair_headers):
    """A concept test and a checklist item need no token while a stale case answers 412.

    PRD: "The declared field is **not optional**; omitting it is a shape violation answering
    `ERR_INVALID_REQUEST`. No other endpoint in this API accepts a version field, and none may be
    added."
    PRD: "Opening a business case under a project requires `expected_project_version` in the body,
    carrying the client's last observed `InnovationProject.version`. If it does not equal the
    project's stored `version` at validation time, the create is rejected with
    `ERR_PROJECT_VERSION_CONFLICT` (HTTP 412)."

    Design: Corner/validations/val_occ_scope_limited_to_declared_version_carrying_writes
    """
    set_clock("2026-08-03T00:00:00Z")
    gate2 = register_stage_gate(category="SNACK", payback_months_max=24)
    project = intake_project(
        owner_user_id="lead-os", name="Toffee Crunch Bites", brand="GrainWell",
        category="SNACK", project_type="LINE_EXTENSION", strategic_fit_score=8,
        consumer_need_score=7, target_gross_margin_pct=36, category_attractiveness_score=7,
        development_budget_cap_usd=500000.00,
    )
    version_at_intake = project["version"]
    screened = screen_project(project["id"], chair_user_id="chair-os",
                              screening_notes="Into stage 2.")
    assert screened["version"] > version_at_intake, "screening advanced the project row"

    concept_test = validate_success(
        api.create_concept_test(
            project["id"],
            {"test_type": "MONADIC", "sample_size": 300, "purchase_intent_top2_pct": 80.00,
             "uniqueness_pct": 40.00, "fielded_at": "2026-07-01T00:00:00Z"},
            innovation_lead_headers,
        ),
        201,
    )
    checklist_item = validate_success(
        api.create_deliverable(
            project["id"],
            {"gate_id": gate2["id"], "deliverable_type": "CONSUMER_CONCEPT_TEST",
             "owner_function": "MARKETING"},
            gate_chair_headers,
        ),
        201,
    )
    stale_case = api.create_business_case(
        project["id"],
        {"expected_project_version": version_at_intake, "variant_mode": "TOP_DOWN",
         "category_size_units_year": 4000000, "target_share_pct": 4.00,
         "cogs_per_unit_usd": 2.5000, "slotting_fees_usd": 0.00, "capex_usd": 100000.00,
         "discount_rate_pct": 10.00},
        innovation_lead_headers,
    )

    assert "expected_project_version" not in concept_test
    assert "expected_project_version" not in checklist_item
    validate_error(stale_case, "ERR_PROJECT_VERSION_CONFLICT", 412)


def test_a_refused_version_conflict_consumes_no_version_and_stores_nothing(
    api, innovation_lead_headers, gate_chair_headers
):
    """After the 412 the project sits on the same version and the retry is accepted.

    PRD: "`version` is an integer that starts at 1 on insert and increments by one on every
    accepted write to that row."
    PRD: "The project's first case takes `case_type` `PRELIMINARY`; every later case takes
    `FINAL`."

    Design: Corner/validations/val_occ_scope_limited_to_declared_version_carrying_writes
    """
    set_clock("2026-08-03T00:00:00Z")
    gate2 = register_stage_gate(category="SNACK", payback_months_max=24)
    project = intake_project(
        owner_user_id="lead-os", name="Toffee Crunch Bites", brand="GrainWell",
        category="SNACK", project_type="LINE_EXTENSION", strategic_fit_score=8,
        consumer_need_score=7, target_gross_margin_pct=36, category_attractiveness_score=7,
        development_budget_cap_usd=500000.00,
    )
    version_at_intake = project["version"]
    screen_project(project["id"], chair_user_id="chair-os", screening_notes="Into stage 2.")
    concept_test = validate_success(
        api.create_concept_test(
            project["id"],
            {"test_type": "MONADIC", "sample_size": 300, "purchase_intent_top2_pct": 80.00,
             "uniqueness_pct": 40.00, "fielded_at": "2026-07-01T00:00:00Z"},
            innovation_lead_headers,
        ),
        201,
    )
    checklist_item = validate_success(
        api.create_deliverable(
            project["id"],
            {"gate_id": gate2["id"], "deliverable_type": "CONSUMER_CONCEPT_TEST",
             "owner_function": "MARKETING"},
            gate_chair_headers,
        ),
        201,
    )
    version_before_conflict = project_version(project["id"])
    case_body = {"variant_mode": "TOP_DOWN", "category_size_units_year": 4000000,
                 "target_share_pct": 4.00, "cogs_per_unit_usd": 2.5000,
                 "slotting_fees_usd": 0.00, "capex_usd": 100000.00,
                 "discount_rate_pct": 10.00}

    validate_error(
        api.create_business_case(
            project["id"],
            dict(case_body, expected_project_version=version_at_intake),
            innovation_lead_headers,
        ),
        "ERR_PROJECT_VERSION_CONFLICT",
        412,
    )
    assert project_version(project["id"]) == version_before_conflict, (
        "a refused write does not consume a version"
    )
    retry = validate_success(
        api.create_business_case(
            project["id"],
            dict(case_body, expected_project_version=version_before_conflict),
            innovation_lead_headers,
        ),
        201,
    )

    assert retry["case_type"] == "PRELIMINARY"
    _, meta = validate_paginated(
        api.list_business_cases(project["id"], innovation_lead_headers)
    )
    assert meta["total_count"] == 1, "the refused attempt stored nothing"
    validate_success(api.get_deliverable(checklist_item["id"], gate_chair_headers))
    surviving, _ = validate_paginated(
        api.list_concept_tests(project["id"], innovation_lead_headers)
    )
    assert [item["id"] for item in surviving] == [concept_test["id"]], (
        "the untokened children are unaffected by the intervening 412"
    )
