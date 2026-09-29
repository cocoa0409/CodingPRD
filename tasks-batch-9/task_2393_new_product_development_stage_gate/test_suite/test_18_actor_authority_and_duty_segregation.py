"""Who is allowed to act, and the identity comparisons that keep duties apart."""
from test_helpers import (
    ALL_ROLE_HEADERS,
    NON_EXISTENT_UUID,
    add_forecast_line,
    build_user_headers,
    deliverable_by_type,
    intake_project,
    make_functional_reviewer_headers,
    make_gate_chair_headers,
    open_business_case,
    open_gate_review,
    project_version,
    read_project,
    schedule_gate_review,
    set_clock,
    setup_screened_project,
    submit_deliverable,
    validate_error,
    validate_paginated,
    validate_success,
)

_NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}

_IDEA_PROJECT = {
    "brand": "GrainWell",
    "category": "SNACK",
    "project_type": "LINE_EXTENSION",
    "strategic_fit_score": 8,
    "consumer_need_score": 7,
    "target_gross_margin_pct": 36,
    "category_attractiveness_score": 7,
    "development_budget_cap_usd": 300000.00,
}


def _headers_without_role(user_id):
    """The same headers a caller would send, minus the declared capacity."""
    headers = dict(build_user_headers(user_id, "InnovationLead"))
    headers.pop("X-User-Role")
    return headers


def _headers_without_user_id(role):
    """The same headers a caller would send, minus the acting identifier."""
    headers = dict(build_user_headers("lead-hp", role))
    headers.pop("X-User-ID")
    return headers


def _setup_duty_split():
    """A screened project whose manufacturing item is submitted and whose review is open."""
    ctx = setup_screened_project(
        category="SNACK",
        gate_overrides={"required_deliverable_types": ["MANUFACTURING_READINESS"],
                        "quorum_size": 2, "payback_months_max": 24},
        project_overrides=dict(_IDEA_PROJECT, name="Duty Split Bars"),
        owner_user_id="owner-sod", chair_user_id="chair-sod",
    )
    project_id = ctx["project"]["id"]
    item = deliverable_by_type(project_id, "MANUFACTURING_READINESS",
                              gate_id=ctx["gate2"]["id"])
    assert item is not None, "screening auto-created the gate's required checklist item"
    submitted = submit_deliverable(item["id"],
                                  evidence_url="https://npd.example/sod/manufacturing",
                                  submitter_user_id="sub-sod")
    review = schedule_gate_review(project_id, ctx["gate2"]["id"], chair_user_id="chair-sod",
                                  scheduled_at="2026-08-10T09:00:00Z")
    open_gate_review(review["id"], chair_user_id="chair-sod")
    return {"project_id": project_id, "item": submitted, "review": review}


def test_every_role_exclusive_write_refuses_a_neighbouring_role(
    api, portfolio_admin_headers, innovation_lead_headers, gate_chair_headers,
    functional_reviewer_headers, regulatory_approver_headers, rnd_lead_headers,
    sales_account_manager_headers,
):
    """Fifteen writes, each attempted by a plausible neighbour, all answer 403.

    PRD: "When both headers are present but the declared role is not among the roles authorised for
    the target operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403); this too
    precedes path resolution, so a wrong-role request against an unknown id answers 403, not 404."
    PRD: "2. **Role authorisation** — the declared role is authorised for the operation, else
    `ERR_UNAUTHORIZED` (403)."
    PRD: "Write authority is partitioned: `PortfolioAdmin` governs the configuration roots (stage
    gates, retailers, reset windows, pilot lines), the logical clock, condition expiry and
    post-launch reporting; `InnovationLead` owns project intake, consumer testing, business cases
    and forecast lines, and label drafting; `GateChair` holds go/no-go authority — screening,
    scheduling, opening and closing reviews, condition clearing, waivers, the launch date lock and
    launch execution; `FunctionalReviewer` decides submitted checklist items and casts ballots;
    `RegulatoryApprover` decides label approvals and may also occupy the `REGULATORY` gate seat;
    `RnDLead` owns formulation revisions, pilot runs and stability studies; `SalesAccountManager`
    owns trade presentation booking, presentation, outcome recording and withdrawal."

    Design: Corner/rbac/rbac_every_exclusive_write_refuses_the_wrong_role_returns_403
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-rb", name="Role Matrix Probe", **_IDEA_PROJECT)
    project_id = project["id"]

    attempts = [
        ("the clock setter is not the chair's", api.set_clock(
            {"to_iso8601": "2026-08-04T00:00:00Z"}, gate_chair_headers)),
        ("gate configuration is not the lead's", api.create_stage_gate(
            {"gate_number": 2, "category": "SNACK", "stage_from": "SCREENED",
             "stage_to": "PILOT_QUALIFIED", "required_deliverable_types": [],
             "quorum_size": 1, "veto_functions": [], "npv_hurdle_usd": 0.00,
             "payback_months_max": 24, "gross_margin_floor_pct": 0.00,
             "readiness_floor_index": 0.00}, innovation_lead_headers)),
        ("retailer registration is not sales' own", api.create_retailer(
            {"name": "Wrong Role Grocery", "channel": "GROCERY",
             "acv_contribution_pct": 20.00, "presentation_lead_days": 14},
            sales_account_manager_headers)),
        ("pilot line registration is not R&D's", api.create_pilot_line(
            {"plant_name": "Nowhere", "line_code": "NOW-01",
             "changeover_buffer_minutes": 120, "allergen_regime": "NONE",
             "hourly_cost_usd": 400.00}, rnd_lead_headers)),
        ("project intake is not the admin's", api.create_project(
            dict(_IDEA_PROJECT, name="Admin Cannot Create"), portfolio_admin_headers)),
        ("screening is not the lead's", api.screen_project(
            project_id, {"screening_notes": "Not my call."}, innovation_lead_headers)),
        ("concept testing is not R&D's", api.create_concept_test(
            project_id,
            {"test_type": "MONADIC", "sample_size": 200, "purchase_intent_top2_pct": 40.00,
             "uniqueness_pct": 30.00, "fielded_at": "2026-08-02T00:00:00Z"},
            rnd_lead_headers)),
        ("business cases are not the chair's", api.create_business_case(
            project_id,
            {"expected_project_version": project["version"], "variant_mode": "TOP_DOWN",
             "category_size_units_year": 1000000, "target_share_pct": 3.00,
             "cogs_per_unit_usd": 2.0000, "slotting_fees_usd": 0.00, "capex_usd": 50000.00,
             "discount_rate_pct": 10.00}, gate_chair_headers)),
        ("formulations are not the lead's", api.create_formulation(
            project_id,
            {"expected_project_version": project["version"], "spec_summary": "Not my call",
             "allergen_regime": "NONE", "target_shelf_life_days": 180,
             "unit_cost_usd": 2.0000}, innovation_lead_headers)),
        ("label drafting is not the approver's", api.create_label_approval(
            project_id,
            {"formulation_id": NON_EXISTENT_UUID, "label_version": "v1",
             "claims": ["Nothing"]}, regulatory_approver_headers)),
        ("trade booking is not the lead's", api.create_sell_in_presentation(
            project_id,
            {"retailer_id": NON_EXISTENT_UUID, "shelf_reset_window_id": NON_EXISTENT_UUID,
             "scheduled_at": "2026-09-01T09:00:00Z", "proposed_sku_count": 2},
            innovation_lead_headers)),
        ("convening a review is not a reviewer's", api.create_gate_review(
            project_id,
            {"gate_id": NON_EXISTENT_UUID, "scheduled_at": "2026-09-01T09:00:00Z"},
            functional_reviewer_headers)),
        ("the date lock is not the admin's", api.lock_launch_date(
            project_id,
            {"launch_date": "2026-11-10T00:00:00Z",
             "shelf_reset_window_id": NON_EXISTENT_UUID}, portfolio_admin_headers)),
        ("launch execution is not sales'", api.launch_project(
            project_id, {}, sales_account_manager_headers)),
        ("post-launch reporting is not the chair's", api.create_post_launch_period(
            project_id,
            {"period_index": 1, "actual_units": 100, "actual_net_revenue_usd": 100.00,
             "actual_gross_margin_usd": 10.00, "attainment_basis": "CUMULATIVE"},
            gate_chair_headers)),
    ]

    assert len(attempts) == 15, "every role-exclusive write family is covered once"
    for label, response in attempts:
        assert response.status_code == 403, f"{label}: expected a role refusal"
        validate_error(response, "ERR_UNAUTHORIZED", 403)
    untouched = read_project(project_id)
    assert untouched["dev_status"] == "IDEA"
    assert untouched["version"] == project["version"], "no refusal advanced the project row"


def test_the_refused_configuration_writes_leave_the_roots_and_the_clock_alone(
    api, portfolio_admin_headers, innovation_lead_headers, gate_chair_headers,
    rnd_lead_headers, sales_account_manager_headers,
):
    """The four refused root writes store nothing and the clock never moves.

    PRD: "2. **Role authorisation** — the declared role is authorised for the operation, else
    `ERR_UNAUTHORIZED` (403)."
    PRD: "Write authority is partitioned: `PortfolioAdmin` governs the configuration roots (stage
    gates, retailers, reset windows, pilot lines), the logical clock, condition expiry and
    post-launch reporting;"
    PRD: "A dedicated launch-readiness read exposes the live picture without storing anything new:
    the current `launch_readiness_pct`, a `blocking_deliverable_types` array listing the required
    readiness types not yet `APPROVED` in checklist order, the current `authorized_acv_pct`, the
    locked `launch_date` if any, and an `earliest_lockable_date` computed on every read as the
    current instant plus the 45-whole-day lock lead time."

    Design: Corner/rbac/rbac_every_exclusive_write_refuses_the_wrong_role_returns_403
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-rb", name="Role Matrix Probe", **_IDEA_PROJECT)

    validate_error(
        api.set_clock({"to_iso8601": "2026-08-04T00:00:00Z"}, gate_chair_headers),
        "ERR_UNAUTHORIZED", 403,
    )
    validate_error(
        api.create_stage_gate(
            {"gate_number": 2, "category": "SNACK", "stage_from": "SCREENED",
             "stage_to": "PILOT_QUALIFIED", "required_deliverable_types": [],
             "quorum_size": 1, "veto_functions": [], "npv_hurdle_usd": 0.00,
             "payback_months_max": 24, "gross_margin_floor_pct": 0.00,
             "readiness_floor_index": 0.00}, innovation_lead_headers),
        "ERR_UNAUTHORIZED", 403,
    )
    validate_error(
        api.create_retailer(
            {"name": "Wrong Role Grocery", "channel": "GROCERY",
             "acv_contribution_pct": 20.00, "presentation_lead_days": 14},
            sales_account_manager_headers),
        "ERR_UNAUTHORIZED", 403,
    )
    validate_error(
        api.create_pilot_line(
            {"plant_name": "Nowhere", "line_code": "NOW-01",
             "changeover_buffer_minutes": 120, "allergen_regime": "NONE",
             "hourly_cost_usd": 400.00}, rnd_lead_headers),
        "ERR_UNAUTHORIZED", 403,
    )

    for lister in (api.list_stage_gates, api.list_retailers, api.list_pilot_lines):
        _, meta = validate_paginated(lister(portfolio_admin_headers))
        assert meta["total_count"] == 0, "a refused root write stored nothing"
    _, projects_meta = validate_paginated(api.list_projects(portfolio_admin_headers))
    assert projects_meta["total_count"] == 1, "only the legitimately created project exists"
    readiness = validate_success(
        api.get_launch_readiness(project["id"], portfolio_admin_headers)
    )
    assert readiness["earliest_lockable_date"].startswith("2026-09-17"), (
        "the clock still stands 45 whole days before 2026-09-17, so the refused clock write "
        "had no effect"
    )


def test_a_missing_identity_header_is_refused_before_role_and_before_existence(api):
    """Six requests, each short a header, all answer 401 whatever else is wrong with them.

    PRD: "Every request — reads included — must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity that user is acting in. If either header
    is absent the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401), and this check runs
    ahead of everything else, including path resolution, so an unauthenticated request naming a
    non-existent resource still answers 401 rather than 404."
    PRD: "1. **Authentication** — both headers present, else `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/rbac_missing_identity_headers_are_rejected_before_role_and_existence
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-hp", name="Header Probe", **_IDEA_PROJECT)

    attempts = [
        ("listing projects without a declared role",
         api.list_projects(_headers_without_role("lead-hp"))),
        ("reading a project that exists without a declared role",
         api.get_project(project["id"], _headers_without_role("lead-hp"))),
        ("reading an unknown project with no identity at all",
         api.get_project(NON_EXISTENT_UUID, _NO_IDENTITY_HEADERS)),
        ("creating a project with a role but no acting user",
         api.create_project(dict(_IDEA_PROJECT, name="No User Header"),
                            _headers_without_user_id("InnovationLead"))),
        ("creating a project with no identity and an unusable body",
         api.create_project({"brand": "GrainWell", "category": "SNACK"},
                            _NO_IDENTITY_HEADERS)),
        ("screening with no identity at all",
         api.screen_project(project["id"], {"screening_notes": "No headers at all."},
                            _NO_IDENTITY_HEADERS)),
    ]

    for label, response in attempts:
        assert response.status_code == 401, f"{label}: expected an authentication refusal"
        validate_error(response, "ERR_UNAUTHENTICATED", 401)


def test_the_unauthenticated_screen_left_the_project_untouched(api, gate_chair_headers):
    """A 401 screen writes nothing, so the project is still an unscreened idea.

    PRD: "If either header is absent the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401),
    and this check runs ahead of everything else, including path resolution, so an unauthenticated
    request naming a non-existent resource still answers 401 rather than 404."
    PRD: "Screening is the only gate decided by a single actor rather than a ballot: a `GateChair`
    screens the idea, optionally attaching `screening_notes`, and the project's `dev_status` moves
    out of `IDEA` in one of two directions."

    Design: Corner/rbac/rbac_missing_identity_headers_are_rejected_before_role_and_existence
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-hp", name="Header Probe", **_IDEA_PROJECT)

    refused = api.screen_project(project["id"], {"screening_notes": "No headers at all."},
                                 _NO_IDENTITY_HEADERS)

    validate_error(refused, "ERR_UNAUTHENTICATED", 401)
    still_an_idea = read_project(project["id"])
    assert still_an_idea["dev_status"] == "IDEA"
    assert still_an_idea["screening_decision"] == "PENDING"
    assert still_an_idea["version"] == project["version"]
    _, meta = validate_paginated(api.list_projects(gate_chair_headers))
    assert meta["total_count"] == 1, "a properly authenticated read still sees the project"


def test_all_seven_roles_read_the_identical_project_payload(api):
    """The same project read answers 200 for each of the seven roles with one payload.

    PRD: "Seven roles exist, spelled exactly: `PortfolioAdmin`, `InnovationLead`, `GateChair`,
    `FunctionalReviewer`, `RegulatoryApprover`, `RnDLead`, and `SalesAccountManager`. Every one of
    the seven may call every read endpoint."
    PRD: "All seven roles may call every `GET` endpoint, shown below as "All roles"."

    Design: Corner/rbac/rbac_every_role_may_read_the_whole_project_graph
    """
    ctx = setup_screened_project(
        category="SNACK",
        project_overrides=dict(_IDEA_PROJECT, name="Read Sweep"),
        owner_user_id="lead-rs", chair_user_id="chair-rs",
    )
    project_id = ctx["project"]["id"]
    version_after_screening = ctx["project"]["version"]

    payloads = [validate_success(api.get_project(project_id, headers))
                for headers in ALL_ROLE_HEADERS]

    assert len(payloads) == 7, "one read per role"
    for payload in payloads[1:]:
        assert payload == payloads[0], "no role gets a filtered view of the project"
    assert payloads[0]["id"] == project_id
    assert payloads[0]["dev_status"] == ctx["project"]["dev_status"], (
        "every role sees the same development status the screening write returned"
    )
    assert project_version(project_id) == version_after_screening, "reads write nothing"


def test_the_narrow_approver_roles_read_the_rest_of_the_project_graph(
    api, regulatory_approver_headers, sales_account_manager_headers, rnd_lead_headers
):
    """A case, its forecast lines and the readiness view open for roles that cannot write them.

    PRD: "Seven roles exist, spelled exactly: `PortfolioAdmin`, `InnovationLead`, `GateChair`,
    `FunctionalReviewer`, `RegulatoryApprover`, `RnDLead`, and `SalesAccountManager`. Every one of
    the seven may call every read endpoint."
    PRD: "`launch_readiness_pct` is `0.00` when the denominator is zero"

    Design: Corner/rbac/rbac_every_role_may_read_the_whole_project_graph
    """
    ctx = setup_screened_project(
        category="SNACK",
        project_overrides=dict(_IDEA_PROJECT, name="Read Sweep"),
        owner_user_id="lead-rs", chair_user_id="chair-rs",
    )
    project_id = ctx["project"]["id"]
    case = open_business_case(project_id, variant_mode="TOP_DOWN",
                             category_size_units_year=2000000, target_share_pct=4.00,
                             cogs_per_unit_usd=2.0000, slotting_fees_usd=0.00,
                             capex_usd=50000.00, discount_rate_pct=10.00)
    add_forecast_line(case["id"], channel="MASS", store_count=1000,
                      base_velocity_units_per_store_week=2.00, promo_weeks=0,
                      promo_lift_pct=0.00, list_price_usd=4.0000)

    read_case = validate_success(
        api.get_business_case(case["id"], regulatory_approver_headers)
    )
    lines, lines_meta = validate_paginated(
        api.list_forecast_lines(case["id"], sales_account_manager_headers)
    )
    readiness = validate_success(api.get_launch_readiness(project_id, rnd_lead_headers))

    assert read_case["id"] == case["id"], (
        "the regulatory approver reads a case it may never write"
    )
    assert lines_meta["total_count"] == 1
    assert [line["channel"] for line in lines] == ["MASS"]
    assert readiness["launch_readiness_pct"] == 0.00, (
        "no gate demands a readiness type, so the denominator is zero"
    )
    assert isinstance(readiness["blocking_deliverable_types"], list)


def test_a_submitter_wearing_the_reviewer_role_cannot_approve_their_own_item(api):
    """The self-approval bar compares identifiers, so an independent reviewer succeeds.

    PRD: "A checklist item's decider may not be its submitter. If the acting `X-User-ID` equals the
    item's `submitted_by_user_id`, the decision is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`
    (403)."
    PRD: "Once the item really is `SUBMITTED`, a decider whose identifier equals
    `submitted_by_user_id` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`."
    PRD: "A `FunctionalReviewer` decides a `SUBMITTED` item by supplying a `decision` and an
    optional `comment`; the item moves `SUBMITTED → APPROVED` or `SUBMITTED → REJECTED` and the
    acting identifier is recorded as `decided_by_user_id`."

    Design: Corner/rbac/rbac_segregation_of_duties_keys_on_user_identity_not_role
    """
    ctx = _setup_duty_split()
    assert ctx["item"]["submitted_by_user_id"] == "sub-sod"

    self_approval = api.decide_deliverable(
        ctx["item"]["id"],
        {"decision": "APPROVE", "comment": "Signing off on my own pack."},
        make_functional_reviewer_headers("sub-sod"),
    )
    still_submitted = validate_success(
        api.get_deliverable(ctx["item"]["id"], make_functional_reviewer_headers("sub-sod"))
    )
    independent = api.decide_deliverable(
        ctx["item"]["id"],
        {"decision": "APPROVE", "comment": "Independent review."},
        make_functional_reviewer_headers("rev-sod"),
    )

    validate_error(self_approval, "ERR_SELF_APPROVAL_FORBIDDEN", 403)
    assert still_submitted["status"] == "SUBMITTED"
    approved = validate_success(independent)
    assert approved["status"] == "APPROVED", "the reviewer role was never the problem"
    assert approved["decided_by_user_id"] == "rev-sod"


def test_the_owner_cannot_vote_although_the_chair_user_may(api):
    """One identifier is barred from the ballot box and another is welcome.

    PRD: "A project's owner may not vote at its own gate. If the acting `X-User-ID` equals the
    project's `owner_user_id`, the ballot is rejected with `ERR_OWNER_CANNOT_VOTE` (403)."
    PRD: "The acting user's opaque identifier is captured as `owner_user_id`, which is what later
    bars that same person from voting at the project's gates."
    PRD: "The same holds for `InnovationLead`, `GateChair`, `FunctionalReviewer`,
    `RegulatoryApprover`, `RnDLead` and `SalesAccountManager` — for all seven roles, `X-User-ID` is
    an opaque string, never a foreign key."

    Design: Corner/rbac/rbac_segregation_of_duties_keys_on_user_identity_not_role
    """
    ctx = _setup_duty_split()
    review_id = ctx["review"]["id"]
    assert read_project(ctx["project_id"])["owner_user_id"] == "owner-sod"

    owner_ballot = api.cast_gate_vote(
        review_id,
        {"function": "MARKETING", "vote": "APPROVE", "rationale": "My own project."},
        make_functional_reviewer_headers("owner-sod"),
    )
    _, empty_meta = validate_paginated(
        api.list_gate_votes(review_id, make_gate_chair_headers("chair-sod"))
    )
    chair_ballot = api.cast_gate_vote(
        review_id,
        {"function": "OPERATIONS", "vote": "APPROVE", "rationale": "Capacity confirmed."},
        make_functional_reviewer_headers("chair-sod"),
    )

    validate_error(owner_ballot, "ERR_OWNER_CANNOT_VOTE", 403)
    assert empty_meta["total_count"] == 0, "the owner's refused ballot was never stored"
    cast = validate_success(chair_ballot, 201)
    assert cast["voter_user_id"] == "chair-sod", "casting a ballot is not itself forbidden"
    _, meta = validate_paginated(
        api.list_gate_votes(review_id, make_gate_chair_headers("chair-sod"))
    )
    assert meta["total_count"] == 1


def test_a_chair_who_voted_cannot_close_and_a_fresh_chair_meets_the_quorum_bar(api):
    """The duty bar answers first; only once a clean chair closes does quorum speak.

    PRD: "A chair who voted may not close the review. If the acting `X-User-ID` already appears as
    the `voter_user_id` of any `GateVote` on the review being closed, the close is rejected with
    `ERR_CHAIR_CANNOT_VOTE_AND_CLOSE` (403)."
    PRD: "`vote_count` must be at least the gate's `quorum_size`, else `ERR_QUORUM_NOT_MET` (409) —
    and because quorum is checked **before the decision is derived**, a lone `REJECT` ballot under
    quorum reports the quorum error rather than killing the project."
    PRD: "8. **Segregation of duties** — the three rules of §2.1, answering 403. Because this band
    follows state, a decide attempted on a `PENDING` checklist item reports the state error rather
    than the self-approval error."

    Design: Corner/rbac/rbac_segregation_of_duties_keys_on_user_identity_not_role
    """
    ctx = _setup_duty_split()
    review_id = ctx["review"]["id"]
    validate_success(
        api.cast_gate_vote(
            review_id,
            {"function": "OPERATIONS", "vote": "APPROVE", "rationale": "Capacity confirmed."},
            make_functional_reviewer_headers("chair-sod"),
        ),
        201,
    )

    close_by_voter = api.close_gate_review(review_id, {}, make_gate_chair_headers("chair-sod"))
    mid_flight = validate_success(
        api.get_gate_review(review_id, make_gate_chair_headers("chair-sod"))
    )
    close_by_clean_chair = api.close_gate_review(review_id, {},
                                                make_gate_chair_headers("chair2-sod"))

    validate_error(close_by_voter, "ERR_CHAIR_CANNOT_VOTE_AND_CLOSE", 403)
    assert mid_flight["status"] == "IN_SESSION"
    assert mid_flight["vote_count"] == 1
    validate_error(close_by_clean_chair, "ERR_QUORUM_NOT_MET", 409)
    unmoved = read_project(ctx["project_id"])
    assert unmoved["dev_status"] == "SCREENED"
    assert unmoved["next_gate_number"] == 2


def test_screening_an_unknown_project_answers_403_for_the_wrong_role_and_404_for_the_right_one(
    api, innovation_lead_headers, gate_chair_headers
):
    """Authorisation is decided from the endpoint alone and leaks no existence information.

    PRD: "When both headers are present but the declared role is not among the roles authorised for
    the target operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403); this too
    precedes path resolution, so a wrong-role request against an unknown id answers 403, not 404."
    PRD: "3. **Path existence** — every identifier in the URL resolves to a stored row, resolved
    outer to inner, so a nested path with two unknown identifiers reports the outer resource
    first."

    Design: Corner/rbac/rbac_role_refusal_precedes_path_existence_returns_403
    """
    set_clock("2026-08-03T00:00:00Z")

    wrong_role = api.screen_project(
        NON_EXISTENT_UUID, {"screening_notes": "Wrong role, unknown id."},
        innovation_lead_headers,
    )
    right_role = api.screen_project(
        NON_EXISTENT_UUID, {"screening_notes": "Right role, unknown id."},
        make_gate_chair_headers("chair-rp"),
    )

    validate_error(wrong_role, "ERR_UNAUTHORIZED", 403)
    validate_error(right_role, "ERR_PROJECT_NOT_FOUND", 404)
    _, meta = validate_paginated(api.list_projects(gate_chair_headers))
    assert meta["total_count"] == 0, "no project ever existed to be found"


def test_post_launch_reporting_on_an_unknown_project_refuses_the_role_before_the_lookup(
    api, portfolio_admin_headers, sales_account_manager_headers
):
    """The same unknown project answers 403 to sales and 404 to the portfolio admin.

    PRD: "When both headers are present but the declared role is not among the roles authorised for
    the target operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403); this too
    precedes path resolution, so a wrong-role request against an unknown id answers 403, not 404."
    PRD: "3. **Path existence** — every identifier in the URL resolves to a stored row, resolved
    outer to inner, so a nested path with two unknown identifiers reports the outer resource
    first."

    Design: Corner/rbac/rbac_role_refusal_precedes_path_existence_returns_403
    """
    set_clock("2026-08-03T00:00:00Z")
    period = {"period_index": 1, "actual_units": 10, "actual_net_revenue_usd": 10.00,
              "actual_gross_margin_usd": 1.00, "attainment_basis": "CUMULATIVE"}

    wrong_role = api.create_post_launch_period(NON_EXISTENT_UUID, period,
                                               sales_account_manager_headers)
    right_role = api.create_post_launch_period(NON_EXISTENT_UUID, period,
                                               portfolio_admin_headers)

    validate_error(wrong_role, "ERR_UNAUTHORIZED", 403)
    validate_error(right_role, "ERR_PROJECT_NOT_FOUND", 404)
    _, meta = validate_paginated(api.list_projects(portfolio_admin_headers))
    assert meta["total_count"] == 0, "no project ever existed to be found"
