"""Matching a worker to transitional work: scoring, the eligibility floors and the
server-side selector."""
from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    assert_placement,
    auto_match_payload,
    create_placement_payload,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_new_placement_starts_on_both_dimensions_at_their_initial_states(api):
    """PRD §3.4: "The row lands with `placement_status` `PROPOSED`, `compliance_status` `COMPLIANT`, `reinjury_risk_variant` `BASELINE`, `progression_step` at zero, `logged_hours` an empty array, and `activated_on`, `ended_on`, `suspension_reason` and `decline_reason` all null."

    Design: Corner/state_machines/placement_starts_in_proposed_and_compliant
    """
    ctx = fixtures.setup_active_restriction_set()

    data = validate_success(
        api.create_placement(
            create_placement_payload(
                ctx["restriction_set_id"], ctx["job_id"], ctx["restriction_set_version"]
            ),
            fixtures.COORD,
        ),
        201,
    )

    assert_placement(data)
    assert data["placement_status"] == "PROPOSED"
    assert data["compliance_status"] == "COMPLIANT"
    assert data["activated_on"] is None
    assert data["ended_on"] is None
    assert data["progression_step"] == 0
    assert data["logged_hours"] == []


def test_match_score_combines_five_weighted_headroom_terms(api):
    """PRD §3.4: "The four pairings are `max_lift_lbs` against `demand_lift_lbs`, `max_continuous_standing_minutes` against `demand_standing_minutes`, `max_hours_per_day` against `demand_hours_per_day`, and `keyboard_minutes_per_hour` against `demand_keyboard_minutes_per_hour`. A fifth term reflects the job's ergonomic band: it is 1 minus the risk penalty for the job's `risk_class`, where the penalty is 0 for `LOW`, 0.35 for `MEDIUM` and 0.75 for `HIGH`. The five terms are combined with weights of 0.35 for lift, 0.20 for standing, 0.25 for hours, 0.10 for keyboarding and 0.10 for the risk term, and the weighted sum is scaled by 100 to give a raw score."
    PRD §3.4: "That raw score is then damped by the clinical severity of the restriction set: the damping multiplier is the lesser of 1.0 and the quotient of the pivot 60 divided by the greater of the set's `severity_index` and 1, so a set at or below a severity index of 60 is undamped while a more severe set pulls every score down proportionally."

    Design: Difficulty/combinatorial_formula/match_score_five_weight_headroom_with_severity_damping
    """
    ctx = fixtures.setup_active_restriction_set()
    assert ctx["restriction_set"]["severity_index"] == 60, (
        "lift 20 / standing 30 / hours 6 / no overhead / no driving scores 60"
    )

    data = validate_success(
        api.create_placement(
            create_placement_payload(
                ctx["restriction_set_id"], ctx["job_id"], ctx["restriction_set_version"]
            ),
            fixtures.COORD,
        ),
        201,
    )

    assert data["match_score"] == 51.39, (
        f"a LOW-risk job demanding 10/15/4/20 under this set scores 51.39, got "
        f"{data['match_score']}"
    )


def test_match_score_is_pinned_on_the_created_placement(api):
    """PRD §3.4: "The raw score multiplied by the damping multiplier is clamped into the range from 0 to 100 and then rounded half up to two decimal places — the clamp and the damping multiplication both precede that single rounding."
    PRD §3.4: "The score is pinned at creation and recomputed only when a progression review advances the placement or when a panel closes on a modify outcome."

    Design: Difficulty/combinatorial_formula/match_score_five_weight_headroom_with_severity_damping
    """
    ctx = fixtures.setup_proposed_placement()

    data = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))

    assert data["placement_status"] == "PROPOSED"
    assert data["match_score"] == 51.39, (
        f"the pinned score survives a plain read unchanged, got {data['match_score']}"
    )


def test_a_job_leaving_almost_no_headroom_is_refused_below_the_floor(api):
    """PRD §3.4: "At priority 20, an explicit creation whose computed `match_score` falls below the eligibility floor of 40.0 is refused with `ERR_MATCH_SCORE_BELOW_FLOOR` and HTTP 422 — a score exactly equal to 40.0 passes."

    Design: Corner/validations/match_score_below_floor_is_rejected
    """
    ctx = fixtures.setup_active_restriction_set()
    tight_job = fixtures.create_transitional_job(
        ctx["supervisor_id"], title="Edge Case Bench", seat_capacity=1,
        demand_lift_lbs=19, demand_standing_minutes=29, demand_hours_per_day=6,
        demand_keyboard_minutes_per_hour=44,
    )

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], tight_job["id"], ctx["restriction_set_version"]
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_MATCH_SCORE_BELOW_FLOOR, 422)


def test_a_baseline_risk_of_exactly_seventy_is_refused(api):
    """PRD §3.4: "At priority 21, an explicit creation whose `BASELINE` `reinjury_risk_score` reaches the escalation threshold of 70 or more is refused with `ERR_REINJURY_RISK_TOO_HIGH` and HTTP 422; only a score strictly below 70 is accepted."
    PRD §3.4: "Its structural term begins from a base determined by the job's `risk_class` — 12 for `LOW`, 28 for `MEDIUM`, 46 for `HIGH` — adds the restriction set's `severity_index` multiplied by 0.45, and adds 22.0 multiplied by a demand-pressure factor."

    Design: Difficulty/boundary_precision_check/baseline_reinjury_risk_admits_69_and_blocks_exactly_70
    """
    ctx = fixtures.setup_active_restriction_set()
    job_a = fixtures.create_transitional_job(
        ctx["supervisor_id"], title="Line Auditor A", seat_capacity=1,
        demand_lift_lbs=13, demand_standing_minutes=15, demand_hours_per_day=4,
        demand_keyboard_minutes_per_hour=20, hourly_rate_cents=1900, risk_class="MEDIUM",
    )

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], job_a["id"], ctx["restriction_set_version"],
            scheduled_hours_per_day=4,
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_REINJURY_RISK_TOO_HIGH, 422)


def test_a_baseline_risk_of_sixty_nine_is_admitted(api):
    """PRD §3.4: "At priority 21, an explicit creation whose `BASELINE` `reinjury_risk_score` reaches the escalation threshold of 70 or more is refused with `ERR_REINJURY_RISK_TOO_HIGH` and HTTP 422; only a score strictly below 70 is accepted."
    PRD §3.4: "That demand-pressure factor is the largest of four ratios, each the job's demand divided by the corresponding restriction limit: `demand_lift_lbs` over `max_lift_lbs`, `demand_standing_minutes` over `max_continuous_standing_minutes`, `demand_hours_per_day` over `max_hours_per_day`, and `demand_keyboard_minutes_per_hour` over `keyboard_minutes_per_hour`; the largest of the four is then clamped into the range from 0 to 1.5."

    Design: Difficulty/boundary_precision_check/baseline_reinjury_risk_admits_69_and_blocks_exactly_70
    """
    ctx = fixtures.setup_active_restriction_set()
    job_b = fixtures.create_transitional_job(
        ctx["supervisor_id"], title="Line Auditor B", seat_capacity=1,
        demand_lift_lbs=13, demand_standing_minutes=15, demand_hours_per_day=3,
        demand_keyboard_minutes_per_hour=20, hourly_rate_cents=1900, risk_class="MEDIUM",
    )

    data = validate_success(
        api.create_placement(
            create_placement_payload(
                ctx["restriction_set_id"], job_b["id"], ctx["restriction_set_version"],
                scheduled_hours_per_day=3,
            ),
            fixtures.COORD,
        ),
        201,
    )

    assert data["reinjury_risk_score"] == 69, (
        f"one demand hour less pulls the score to 69, got {data['reinjury_risk_score']}"
    )
    assert data["match_score"] == 46.81, (
        f"the MEDIUM band's 0.35 penalty gives 46.81, got {data['match_score']}"
    )
    assert data["placement_status"] == "PROPOSED"


def test_naming_an_unknown_job_is_refused_before_any_business_rule(api):
    """PRD §2.6: "Priority 5 then resolves every foreign-key id supplied in a request body or query string — this is what catches an unknown `treating_provider_id` when a clinician files restrictions, an unknown `restriction_set_id` or `transitional_job_id` when a placement is created either explicitly or by the selector, an unknown `supervisor_id` when a job-bank entry is added, and unknown filter ids on the placement, restriction-set and wage-ledger listings — answering with `ERR_PROVIDER_NOT_FOUND`, `ERR_RESTRICTION_SET_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_SUPERVISOR_NOT_FOUND` or `ERR_WAGE_ENTRY_NOT_FOUND` as appropriate."

    Design: Corner/entities/placement_create_with_unknown_job_id_returns_job_not_found
    """
    ctx = fixtures.setup_active_restriction_set()

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], UNKNOWN_UUID, ctx["restriction_set_version"]
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_JOB_NOT_FOUND, 404)


def test_a_paused_bank_entry_cannot_receive_a_new_placement(api):
    """PRD §3.3: "Only an `OPEN` entry is bookable: naming a `PAUSED` or `RETIRED` job on an explicit placement creation is refused at priority 30 with `ERR_JOB_NOT_OPEN` and HTTP 409, and non-`OPEN` entries are silently invisible to the selector."

    Design: Corner/errors/paused_job_cannot_receive_a_new_placement
    """
    ctx = fixtures.setup_active_restriction_set()
    fixtures.get_success_data(
        api.update_transitional_job(ctx["job_id"], {"job_status": "PAUSED"}, fixtures.COORD)
    )

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], ctx["job_id"], ctx["restriction_set_version"]
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_JOB_NOT_OPEN, 409)


def test_the_selector_takes_the_highest_scoring_eligible_job(api):
    """PRD §3.4: "Surviving candidates are ranked by `match_score` from highest to lowest. Ties are broken first by ergonomic band, preferring `LOW` over `MEDIUM` over `HIGH`; then by `hourly_rate_cents` from highest to lowest, because a higher transitional wage yields a smaller wage differential; and finally by `created_at` ascending — never by `id`. The single top-ranked job is taken and a placement is created against it with exactly the side effects of the explicit route."

    Design: Corner/endpoints/auto_match_selects_the_highest_scoring_eligible_job
    """
    ctx = fixtures.setup_active_restriction_set()
    medium_job = fixtures.create_transitional_job(
        ctx["supervisor_id"], title="Line Auditor", seat_capacity=1,
        demand_lift_lbs=13, demand_standing_minutes=15, demand_hours_per_day=3,
        demand_keyboard_minutes_per_hour=20, hourly_rate_cents=1900, risk_class="MEDIUM",
    )

    data = validate_success(
        api.auto_match_placement(
            auto_match_payload(ctx["restriction_set_id"], ctx["restriction_set_version"]),
            fixtures.COORD,
        ),
        201,
    )

    assert data["transitional_job_id"] == ctx["job_id"], (
        "the 51.39-scoring LOW-risk sorter outranks the 46.81-scoring MEDIUM auditor"
    )
    assert data["transitional_job_id"] != medium_job["id"]
    assert data["match_score"] == 51.39


def test_the_selector_creates_nothing_when_no_candidate_survives(api):
    """PRD §3.4: "Should the candidate set be empty after filtering, no placement row is created at all and the request answers `ERR_NO_ELIGIBLE_JOB` with HTTP 422 at priority 31."
    PRD §3.4: "the candidate set is built by applying every one of the following predicates to the whole job bank: the job's `job_status` is `OPEN`"

    Design: Corner/endpoints/auto_match_with_no_candidates_returns_no_eligible_job
    """
    ctx = fixtures.setup_active_restriction_set()
    fixtures.get_success_data(
        api.update_transitional_job(ctx["job_id"], {"job_status": "PAUSED"}, fixtures.COORD)
    )

    resp = api.auto_match_placement(
        auto_match_payload(ctx["restriction_set_id"], ctx["restriction_set_version"]),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_JOB, 422)
    listed, _ = validate_paginated(api.list_claim_placements(ctx["claim_id"], fixtures.COORD))
    assert listed == [], "no placement row is created at all"


def test_a_worker_may_not_create_a_placement(api):
    """PRD §2.1: "When a caller's role is not listed among an endpoint's authorized roles in §4, the request is refused with `ERR_UNAUTHORIZED` and HTTP 403."
    PRD §4: "| POST | `/rtw/placements` | Create a transitional placement against an explicitly named job. | `RTWCoordinator`, `ProgramAdmin` |"

    Design: Corner/rbac/employee_role_cannot_create_a_placement
    """
    ctx = fixtures.setup_active_restriction_set()

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], ctx["job_id"], ctx["restriction_set_version"]
        ),
        ctx["employee_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_a_second_placement_carrying_the_pre_create_set_version_is_refused(api):
    """PRD §2.7: "Creating a placement — whether against an explicitly named job or through the server-side selector — requires `expected_restriction_set_version`, carrying the client's last observed `version` of the referenced `RestrictionSet`. If it does not equal that set's current `version`, the creation is rejected with `ERR_STALE_RESTRICTION_SET_VERSION` and HTTP 412."
    PRD §3.4: "Creation computes `match_score`, the `BASELINE` `reinjury_risk_score`, the premium split of §3.6 and `projected_weekly_cost_cents`, raises the referenced set's `active_placement_count`, and raises that set's `version` by 1."

    Design: Corner/cross_cutting_layers/stale_restriction_set_version_rejects_a_second_placement
    """
    ctx = fixtures.setup_proposed_placement()
    stale_version = ctx["restriction_set_version"]

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], ctx["job_id"], stale_version,
            start_date="2026-08-28", end_date="2026-09-15",
        ),
        fixtures.COORD,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_RESTRICTION_SET_VERSION, 412)

    fresh_version = fixtures.current_restriction_set_version(ctx["restriction_set_id"])
    assert fresh_version == stale_version + 1, "the first creation raised the set's version by 1"
    retried = validate_success(
        api.create_placement(
            create_placement_payload(
                ctx["restriction_set_id"], ctx["job_id"], fresh_version,
                start_date="2026-08-28", end_date="2026-09-15",
            ),
            fixtures.COORD,
        ),
        201,
    )
    assert retried["placement_status"] == "PROPOSED"
    restriction_set = validate_success(
        api.get_restriction_set(ctx["restriction_set_id"], fixtures.COORD)
    )
    assert restriction_set["active_placement_count"] == 2


def test_the_placement_listing_carries_the_pagination_envelope(api):
    """PRD §2.3: "Successful list responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object, alongside the standard `api_request_id` and `api_request_timestamp`."
    PRD §2.3: "Rows are returned ordered by `created_at` ascending. Where two rows share an identical `created_at`, the tie is broken by the order in which they were inserted by the request that produced them; the `id` of a row is never used as an ordering key anywhere in this system."
    PRD §3.4: "listed program-wide with optional `claim_id`, `restriction_set_id`, `transitional_job_id`, `supervisor_id`, `placement_status` and `compliance_status` filters."

    Design: Corner/entities/placements_list_returns_pagination_envelope_fields
    """
    ctx = fixtures.setup_proposed_placement()
    fixtures.add_second_placement(ctx, start_date="2026-08-28", end_date="2026-09-15")

    resp = api.list_placements(
        fixtures.COORD, params={"claim_id": ctx["claim_id"], "limit": 1, "offset": 0}
    )

    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
    assert data[0]["id"] == ctx["placement_id"], "the earlier created_at comes first"
    assert resp.json()["response_type"] == "array"


def test_the_claim_sub_resource_lists_that_claims_placements(api):
    """PRD §3.4: "listed under their claim with an optional `placement_status` filter"
    PRD §2.3: "Rows are returned ordered by `created_at` ascending. Where two rows share an identical `created_at`, the tie is broken by the order in which they were inserted by the request that produced them; the `id` of a row is never used as an ordering key anywhere in this system."

    Design: Corner/endpoints/claim_placements_sub_resource_returns_array
    """
    ctx = fixtures.setup_active_placement()

    resp = api.list_claim_placements(ctx["claim_id"], fixtures.COORD)

    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == ctx["placement_id"]
    assert data[0]["placement_status"] == "ACTIVE"
    assert resp.json()["response_type"] == "array"
