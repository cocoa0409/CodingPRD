"""Application lifecycle, scoring formula variants, and the selection waterfall."""
from test_helpers import (
    ApiErrorId,
    close_program,
    create_application_payload,
    create_program,
    draft_application,
    get_application,
    make_applicant_headers,
    open_program,
    add_pool,
    add_rate,
    add_criterion,
    register_applicant,
    run_ranking,
    screen_in,
    setup_obligated_contract,
    setup_open_program,
    setup_screened_application,
    submit_application,
    api_client,
    assert_application,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]

THREE_CRITERIA = (
    ("SOIL_HEALTH", 1.0, 40),
    ("WATER_QUALITY", 1.0, 40),
    ("WILDLIFE", 0.5, 20),
)
THREE_CRITERIA_ANSWERS_PROV = {"SOIL_HEALTH": 40, "WATER_QUALITY": 30, "WILDLIFE": 10}
THREE_CRITERIA_ANSWERS_VERIF = {"SOIL_HEALTH": 20, "WATER_QUALITY": 10, "WILDLIFE": 10}


def test_application_initial_state_draft(api):
    """PRD §3.2: "A new application rests in `DRAFT`." PRD §3.3: "A candidate
    that fits moves to `SELECTED` with its `funded_pool_id` set to the assigned
    pool — a field that remains unset until this moment."

    Design: Corner/state_machines/application_initial_state_draft
    """
    ctx = setup_open_program()
    applicant = register_applicant()
    resp = api.create_application(
        create_application_payload(ctx["program"]["id"], applicant["id"]),
        make_applicant_headers(applicant["id"]),
    )
    application = validate_success(resp, 201)
    assert_application(application)
    assert application["status"] == "DRAFT"
    assert application.get("ranking_score") is None, "ranking_score unset until screening"
    assert application.get("funded_pool_id") is None, "funded_pool_id unset until ranking"


def test_application_missing_parcel_rejected(api):
    """PRD §3.2: "The drafting payload names the target `program_id`, the
    `applicant_id` — which, because the drafter acts in the `Applicant` role,
    must equal the actor's `X-User-ID` or the request fails with
    `ERR_APPLICANT_NOT_OWNER` — the `parcel_id` the practices will apply to, a
    non-empty `planned_practices` list of practice-code-and-quantity pairs (an
    empty list is rejected with `ERR_INVALID_REQUEST`), and a
    `self_reported_answers` map of criterion codes to claimed points."

    Design: Corner/entities/application_missing_required_parcel_rejected
    """
    program = create_program()
    applicant = register_applicant()
    payload = create_application_payload(program["id"], applicant["id"])
    del payload["parcel_id"]
    resp = api.create_application(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_submit_with_unregistered_parcel_rejected(api):
    """PRD §3.2: "The `parcel_id` must be an element of the applicant's
    registered `parcel_ids`, or submission fails with
    `ERR_PARCEL_NOT_REGISTERED` (HTTP 422)."

    Design: Corner/validations/parcel_not_registered_rejected
    """
    ctx = setup_open_program(pools=(("GENERAL", 100000),))
    applicant = register_applicant(parcel_ids=("P-1",))
    application = draft_application(
        ctx["program"]["id"], applicant, parcel_id="P-999",
        planned=(("FENCE", 10),), self_reported_answers={"SOIL_HEALTH": 5},
    )
    resp = api.submit_application(
        application["id"], make_applicant_headers(applicant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_REGISTERED)


def test_screen_in_requires_verified_answers(api):
    """PRD §3.3: "A decision of `SCREENED_IN` requires a `verified_answers`
    payload — the planner's verified map of criterion codes to points — and
    triggers two computations."

    Design: Corner/validations/screen_in_without_verified_answers_rejected
    """
    ctx = setup_open_program(pools=(("GENERAL", 100000),))
    applicant = register_applicant(parcel_ids=("P-1",))
    application = draft_application(
        ctx["program"]["id"], applicant, planned=(("FENCE", 10),),
        self_reported_answers={"SOIL_HEALTH": 5},
    )
    submit_application(application["id"], applicant["id"])
    resp = api.screen_application(application["id"], {"decision": "SCREENED_IN"}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_withdraw_obligated_application_rejected(api):
    """PRD §3.2: "withdrawal moves an application from `DRAFT`, `SUBMITTED`, or
    `SCREENED_IN` to `WITHDRAWN`, is available only to the owning applicant,
    and from any other state is rejected with
    `ERR_APPLICATION_NOT_WITHDRAWABLE` (HTTP 409)."

    Design: Corner/state_machines/withdraw_obligated_application_rejected
    """
    ctx = setup_obligated_contract()
    assert ctx["application"]["status"] == "SELECTED"
    obligated_app = get_application(ctx["application"]["id"])
    assert obligated_app["status"] == "OBLIGATED"

    resp = api.withdraw_application(
        ctx["application"]["id"], make_applicant_headers(ctx["applicant"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_WITHDRAWABLE)

    # The rejected transition leaks no side effects into the pool.
    from test_helpers import get_pool
    pool = get_pool(ctx["pool"]["id"])
    assert pool["obligated_cents"] == 300000, "no side effects from rejected withdraw"


def test_provisional_score_computed_at_submit(api):
    """PRD §3.2: "A successful submission computes the application's
    `provisional_score` by running the ranking formula of §3.3 over the
    self-reported answers." PRD §3.3: "The base score sums, over every ranking
    criterion of the program, the criterion's `weight` multiplied by the
    smaller of the awarded points and the criterion's `max_points`; answers
    absent from the answer set contribute zero. A tier bonus is then keyed on
    the base alone: a base of at least 60 earns 10 bonus points, a base of at
    least 40 but below 60 earns 5, and a base below 40 earns nothing."

    Design: Difficulty/dual_variant_calc/ranking_provisional_vs_verified_divergence
    """
    ctx = setup_open_program(
        rates=(("COVER_CROP", "ACRE", 15000, 18000, 5),), criteria=THREE_CRITERIA
    )
    applicant = register_applicant(parcel_ids=("P-100",))
    application = draft_application(
        ctx["program"]["id"], applicant,
        planned=(("COVER_CROP", 10),),
        self_reported_answers=THREE_CRITERIA_ANSWERS_PROV,
    )
    submitted = submit_application(application["id"], applicant["id"])
    # base = 40*1.0 + 30*1.0 + min(10,20)*0.5 = 75; tier HIGH -> +10 -> 85.
    assert submitted["provisional_score"] == 85, (
        f"provisional_score over self-reported answers: expected 85, got {submitted['provisional_score']}"
    )


def test_verified_score_diverges_from_provisional(api):
    """PRD §3.3: "First, the verified answers are recorded and the ranking
    formula runs over them, storing the result as `ranking_score`; because
    planner-adjusted points usually differ from producer claims, the verified
    score generally differs from the `provisional_score` computed at
    submission." PRD §3.3: "`estimated_obligation_cents` sums the planned
    practices, each priced as its quantity multiplied by the applicable rate —
    the schedule's `hu_rate_cents` when the applicant is historically
    underserved, `standard_rate_cents` otherwise — with each practice line
    rounded half-up to whole cents before the lines are summed, never the
    reverse."

    Design: Difficulty/dual_variant_calc/ranking_provisional_vs_verified_divergence
    """
    ctx = setup_open_program(
        rates=(("COVER_CROP", "ACRE", 15000, 18000, 5),), criteria=THREE_CRITERIA
    )
    applicant = register_applicant(parcel_ids=("P-100",))
    application = draft_application(
        ctx["program"]["id"], applicant,
        planned=(("COVER_CROP", 10),),
        self_reported_answers=THREE_CRITERIA_ANSWERS_PROV,
    )
    submitted = submit_application(application["id"], applicant["id"])
    assert submitted["provisional_score"] == 85

    screened = screen_in(submitted["id"], THREE_CRITERIA_ANSWERS_VERIF)
    # verified base = 20*1.0 + 10*1.0 + min(10,20)*0.5 = 35; tier <40 -> +0 -> 35.
    assert screened["ranking_score"] == 35, (
        f"ranking_score over verified answers: expected 35, got {screened['ranking_score']}"
    )
    assert screened["provisional_score"] == 85
    assert screened["ranking_score"] != screened["provisional_score"], (
        "same application, two formula variants, different results"
    )
    # estimated obligation: 10 ac x standard 15000 = 150000.
    assert screened["estimated_obligation_cents"] == 150000


def test_tier_bonus_applies_at_base_60(api):
    """PRD §3.3: "A tier bonus is then keyed on the base alone: a base of at
    least 60 earns 10 bonus points, a base of at least 40 but below 60 earns 5,
    and a base below 40 earns nothing. Evaluation order is pinned — base first,
    tier lookup second, addition third, cap fourth — so the bonus is never
    re-derived from an already-bonused total."

    Design: Difficulty/combinatorial_formula/ranking_tier_bonus_keyed_on_base_not_final
    """
    ctx = setup_open_program(
        rates=(("COVER_CROP", "ACRE", 15000, 18000, 5),), criteria=THREE_CRITERIA
    )
    applicant = register_applicant(legal_name="B Two", parcel_ids=("P-101",))
    application = draft_application(
        ctx["program"]["id"], applicant, planned=(("COVER_CROP", 1),),
        self_reported_answers={"SOIL_HEALTH": 40, "WATER_QUALITY": 20, "WILDLIFE": 0},
    )
    submit_application(application["id"], applicant["id"])
    screened = screen_in(
        application["id"], {"SOIL_HEALTH": 40, "WATER_QUALITY": 20, "WILDLIFE": 0}
    )
    # base = 40 + 20 + 0 = 60 -> tier HIGH -> 60 + 10 = 70.
    assert screened["ranking_score"] == 70


def test_tier_bonus_not_retriggered_by_bonused_total(api):
    """PRD §3.3: "A tier bonus is then keyed on the base alone: a base of at
    least 60 earns 10 bonus points, a base of at least 40 but below 60 earns 5,
    and a base below 40 earns nothing. Evaluation order is pinned — base first,
    tier lookup second, addition third, cap fourth — so the bonus is never
    re-derived from an already-bonused total."

    Design: Difficulty/combinatorial_formula/ranking_tier_bonus_keyed_on_base_not_final
    """
    ctx = setup_open_program(
        rates=(("COVER_CROP", "ACRE", 15000, 18000, 5),), criteria=THREE_CRITERIA
    )
    applicant = register_applicant(legal_name="C Three", parcel_ids=("P-102",))
    application = draft_application(
        ctx["program"]["id"], applicant, planned=(("COVER_CROP", 1),),
        self_reported_answers={"SOIL_HEALTH": 40, "WATER_QUALITY": 10, "WILDLIFE": 10},
    )
    submit_application(application["id"], applicant["id"])
    screened = screen_in(
        application["id"], {"SOIL_HEALTH": 40, "WATER_QUALITY": 10, "WILDLIFE": 10}
    )
    # base = 40 + 10 + 5 = 55 -> tier MID -> 55 + 5 = 60; NOT re-tiered to 70.
    assert screened["ranking_score"] == 60


def test_waterfall_skips_oversized_candidate(api):
    """PRD §3.3: "A candidate that fits no pool becomes `NOT_SELECTED`, and is
    skipped rather than fatal: a later, smaller application may still find
    room." PRD §3.3: "Selection writes no pool balances. The waterfall instead
    carries a running shadow availability per pool, starting from each pool's
    `available_cents` at the beginning of the run and decremented by each
    selection, so that earlier selections within the same run constrain later
    ones".

    Design: Corner/calculations/ranking_waterfall_skip_and_shadow
    """
    ctx = setup_open_program(
        pools=(("GENERAL", 900000),),
        rates=(
            ("COVER_CROP", "ACRE", 15000, 18000, 5),
            ("WATERING_FACILITY", "EACH", 250000, 300000, 10),
        ),
        criteria=THREE_CRITERIA,
    )
    app_specs = [
        # (name, parcel, planned, answers) — scores 90 / 60 / 35.
        ("A", "P-500", (("COVER_CROP", 40),), {"SOIL_HEALTH": 40, "WATER_QUALITY": 30, "WILDLIFE": 20}),
        ("B", "P-501", (("WATERING_FACILITY", 2),), {"SOIL_HEALTH": 30, "WATER_QUALITY": 20, "WILDLIFE": 10}),
        ("C", "P-502", (("WATERING_FACILITY", 1),), {"SOIL_HEALTH": 20, "WATER_QUALITY": 10, "WILDLIFE": 10}),
    ]
    app_ids = {}
    for name, parcel, planned, answers in app_specs:
        applicant = register_applicant(legal_name=name, parcel_ids=(parcel,))
        app_obj = draft_application(
            ctx["program"]["id"], applicant, planned=planned,
            self_reported_answers=answers,
        )
        submit_application(app_obj["id"], applicant["id"])
        screened = screen_in(app_obj["id"], answers)
        app_ids[name] = screened["id"]

    close_program(ctx["program"]["id"])
    result = run_ranking(ctx["program"]["id"])
    assert result["ranked_count"] == 3
    assert result["selected_count"] == 2
    assert result["not_selected_count"] == 1

    app_a = get_application(app_ids["A"])
    app_b = get_application(app_ids["B"])
    app_c = get_application(app_ids["C"])
    assert app_a["status"] == "SELECTED"
    assert app_a["funded_pool_id"] == ctx["pool"]["id"]
    assert app_b["status"] == "NOT_SELECTED", (
        "B (500000) exceeds the 300000 shadow remainder and is skipped"
    )
    assert app_c["status"] == "SELECTED", (
        "C (250000) still fits the 300000 shadow remainder"
    )
    assert app_c["funded_pool_id"] == ctx["pool"]["id"]

    # Selection writes no pool balances: shadow accounting only.
    from test_helpers import get_pool
    pool = get_pool(ctx["pool"]["id"])
    assert pool["obligated_cents"] == 0
    assert pool["available_cents"] == 900000


def test_tie_break_by_estimated_obligation_then_created_at(api):
    """PRD §3.3: "Candidates are considered in descending `ranking_score`
    order, with ties broken by ascending `estimated_obligation_cents` and then
    by ascending `created_at`; the application `id` is never consulted as a
    tiebreaker."

    Design: Corner/calculations/ranking_tie_break_estimated_obligation_then_created_at
    """
    ctx = setup_open_program(
        pools=(("GENERAL", 300000),),
        rates=(
            ("FENCE", "FOOT", 300, 360, 10),
            ("WATERING_FACILITY", "EACH", 250000, 300000, 10),
        ),
        criteria=THREE_CRITERIA,
    )
    answers = {"SOIL_HEALTH": 30, "WATER_QUALITY": 10, "WILDLIFE": 10}
    # X created first, estimate 300000; Y created second, estimate 250000.
    app_x = register_applicant(legal_name="X", parcel_ids=("P-600",))
    x = draft_application(ctx["program"]["id"], app_x, planned=(("FENCE", 1000),),
                          self_reported_answers=answers)
    submit_application(x["id"], app_x["id"])
    app_y = register_applicant(legal_name="Y", parcel_ids=("P-601",))
    y = draft_application(ctx["program"]["id"], app_y,
                          planned=(("WATERING_FACILITY", 1),),
                          self_reported_answers=answers)
    submit_application(y["id"], app_y["id"])

    sx = screen_in(x["id"], answers)
    sy = screen_in(y["id"], answers)
    # Both: base = 30 + 10 + 5 = 45 -> tier MID -> 50. Exact tie.
    assert sx["ranking_score"] == 50
    assert sy["ranking_score"] == 50
    assert sx["estimated_obligation_cents"] == 300000
    assert sy["estimated_obligation_cents"] == 250000

    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])

    final_x = get_application(x["id"])
    final_y = get_application(y["id"])
    assert final_y["status"] == "SELECTED", (
        "tie on score breaks by ascending estimated_obligation, so Y (250000) goes first"
    )
    assert final_x["status"] == "NOT_SELECTED", (
        "X (created first) loses the tie despite created_at precedence coming later"
    )


def test_hu_pool_priority_then_general_fallback(api):
    """PRD §3.3: "a historically underserved applicant is first tried against
    the HU pool matching the applicant's category — a beginning farmer maps to
    `HU_BEGINNING_FARMER`, a socially disadvantaged producer to
    `HU_SOCIALLY_DISADVANTAGED`, a limited-resource producer to
    `HU_LIMITED_RESOURCE`, and a veteran to `HU_VETERAN` — and then against
    the `GENERAL` pool, while a non-HU applicant considers only the `GENERAL`
    pool."

    Design: Corner/calculations/hu_pool_priority_then_general_fallback
    """
    ctx = setup_open_program(
        pools=(("HU_LIMITED_RESOURCE", 200000), ("GENERAL", 1000000),),
    )
    hu_pool, general_pool = ctx["pools"][0], ctx["pools"][1]
    ctx = setup_screened_application(
        ctx, hu_category="LIMITED_RESOURCE", parcel_ids=("P-200",),
        legal_name="H", planned=(("FENCE", 1000),),
    )
    screened = ctx["application"]
    # HU rate class used for the estimate: 1000 ft x 360 = 360000.
    assert screened["estimated_obligation_cents"] == 360000

    close_program(ctx["program"]["id"])
    run_ranking(ctx["program"]["id"])

    final = get_application(screened["id"])
    assert final["status"] == "SELECTED"
    assert final["funded_pool_id"] == general_pool["id"], (
        "HU pool (200000) does not fit 360000; falls through to the GENERAL pool"
    )
    assert final["funded_pool_id"] != hu_pool["id"]
