"""CIP cost accumulation, capitalization policy thresholds, and project state
dependencies."""
from test_helpers import (
    ACCT,
    CTRL,
    ApiErrorId,
    assert_fixed_asset,
    capitalize_project,
    create_class,
    create_project,
    create_project_with_lines,
    post_cost_line,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_cost_line_on_cancelled_project_rejected(api):
    """PRD §3.1: "Both posting and reversing a line require the parent project to
    still be `OPEN`; against a `CAPITALIZED` or `CANCELLED` project the attempt
    is rejected with `ERR_PROJECT_NOT_OPEN`, and reversing a line that is not
    `POSTED` is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/cost_line_posting_requires_project_open
    """
    cls = create_class()
    project = create_project(cls["id"], project_code="PROJ-C",
                             name="Cancelled works")
    validate_success(api.cancel_project(project["id"], CTRL), 200)

    resp = api.create_cip_cost_line(
        {"project_id": project["id"], "amount_cents": 50000,
         "cost_type": "OTHER", "incurred_date": "2026-02-01"},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_OPEN, 409)


def test_rejected_cost_line_leaves_project_total_untouched(api):
    """PRD §3.1: "The project's `total_accumulated_cents` is, at all times,
    exactly the sum of `amount_cents` over that project's lines in status
    `POSTED`; reversed lines are excluded."
    PRD §3.1: "against a `CAPITALIZED` or `CANCELLED` project the attempt is
    rejected with `ERR_PROJECT_NOT_OPEN`"

    Design: Difficulty/cross_entity_state_dependency/cost_line_posting_requires_project_open
    """
    cls = create_class()
    project = create_project(cls["id"], project_code="PROJ-C2")
    validate_success(api.cancel_project(project["id"], CTRL), 200)

    resp = api.create_cip_cost_line(
        {"project_id": project["id"], "amount_cents": 50000,
         "cost_type": "OTHER", "incurred_date": "2026-02-01"},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_OPEN, 409)

    after = validate_success(api.get_capital_project(project["id"], ACCT), 200)
    assert after["status"] == "CANCELLED"
    assert after["total_accumulated_cents"] == 0
    lines, meta = validate_paginated(
        api.list_project_cost_lines(project["id"], ACCT)
    )
    assert meta["total_count"] == 0 and lines == [], "no CIPCostLine created"


def test_project_total_excludes_reversed_lines(api):
    """PRD §3.1: "The project's `total_accumulated_cents` is, at all times,
    exactly the sum of `amount_cents` over that project's lines in status
    `POSTED`; reversed lines are excluded."
    PRD §3.1: "the line moves from `POSTED` to the terminal status `REVERSED`,
    the project's `total_accumulated_cents` is recomputed (decreasing by the
    line's `amount_cents`), and the project's `version` increments with
    `updated_at` refreshed."

    Design: Difficulty/compensating_invariant/cip_posted_cost_conservation
    """
    cls = create_class()
    project, lines = create_project_with_lines(
        cls["id"], [100000, 150000, 200000], project_code="PROJ-D",
        name="Conservation",
    )
    assert project["total_accumulated_cents"] == 450000

    reversed_line = validate_success(
        api.reverse_cip_cost_line(lines[1]["id"], ACCT), 200
    )
    assert reversed_line["status"] == "REVERSED"

    after = validate_success(api.get_capital_project(project["id"], ACCT), 200)
    assert after["total_accumulated_cents"] == 300000, (
        "POSTED-only sum: 100000 + 200000; the REVERSED 150000 line is excluded"
    )
    assert after["version"] == project["version"] + 1


def test_capitalization_transfers_total_without_drift(api):
    """PRD §3.1: "On success the project transitions from `OPEN` to
    `CAPITALIZED`, its `capitalized_asset_id` is set to the new asset, and a
    `FixedAsset` is created in status `DRAFT` with `source` equal to
    `CIP_CAPITALIZATION`, the project's `asset_class_id`, and an
    `acquisition_cost_cents` equal to the project's accumulated total."
    PRD §3.1: "The project's `total_accumulated_cents` is, at all times, exactly
    the sum of `amount_cents` over that project's lines in status `POSTED`;
    reversed lines are excluded."

    Design: Difficulty/compensating_invariant/cip_posted_cost_conservation
    """
    cls = create_class()
    project, lines = create_project_with_lines(
        cls["id"], [100000, 150000, 200000], project_code="PROJ-D2"
    )
    api.reverse_cip_cost_line(lines[1]["id"], ACCT)

    capitalized = capitalize_project(project["id"], "A-970")
    assert capitalized["status"] == "CAPITALIZED"

    asset = validate_success(
        api.get_fixed_asset(capitalized["capitalized_asset_id"], ACCT), 200
    )
    assert_fixed_asset(asset)
    assert asset["acquisition_cost_cents"] == 300000, (
        "exact transfer of the POSTED-only sum, no drift"
    )
    assert asset["source"] == "CIP_CAPITALIZATION"
    assert asset["status"] == "DRAFT"

    after = validate_success(api.get_capital_project(project["id"], ACCT), 200)
    assert after["total_accumulated_cents"] == 300000, (
        "post-capitalize invariant: total still equals the POSTED-only sum"
    )


def test_capitalize_at_exact_threshold_creates_asset(api):
    """PRD §3.1: "the project's `total_accumulated_cents` must be at least the
    `capitalization_threshold_cents` of the project's asset class (else
    `ERR_BELOW_CAPITALIZATION_THRESHOLD`)"
    PRD §3.1: "On success the project transitions from `OPEN` to `CAPITALIZED`,
    its `capitalized_asset_id` is set to the new asset, and a `FixedAsset` is
    created in status `DRAFT` with `source` equal to `CIP_CAPITALIZATION`, the
    project's `asset_class_id`, and an `acquisition_cost_cents` equal to the
    project's accumulated total."

    Design: Difficulty/boundary_precision_check/capitalize_at_exact_threshold_succeeds
    """
    cls = create_class()
    project, _lines = create_project_with_lines(
        cls["id"], [100000, 150000], project_code="PROJ-A", name="At threshold"
    )
    assert project["total_accumulated_cents"] == 250000

    resp = api.capitalize_project(
        project["id"], {"asset_tag": "A-801", "description": "Threshold asset"},
        CTRL,
    )
    data = validate_success(resp, 200)
    assert data["status"] == "CAPITALIZED"

    asset = validate_success(
        api.get_fixed_asset(data["capitalized_asset_id"], ACCT), 200
    )
    assert asset["acquisition_cost_cents"] == 250000
    assert asset["source"] == "CIP_CAPITALIZATION"
    assert asset["status"] == "DRAFT"


def test_capitalize_one_cent_below_threshold_rejected(api):
    """PRD §3.1: "the project's `total_accumulated_cents` must be at least the
    `capitalization_threshold_cents` of the project's asset class (else
    `ERR_BELOW_CAPITALIZATION_THRESHOLD`)"

    Design: Difficulty/boundary_precision_check/capitalize_at_exact_threshold_succeeds
    """
    cls = create_class()
    project, _lines = create_project_with_lines(
        cls["id"], [249999], project_code="PROJ-B", name="Below threshold"
    )
    resp = api.capitalize_project(
        project["id"],
        {"asset_tag": "A-802", "description": "Below-threshold asset"},
        CTRL,
    )
    validate_error(resp, ApiErrorId.ERR_BELOW_CAPITALIZATION_THRESHOLD, 422)

    after = validate_success(api.get_capital_project(project["id"], ACCT), 200)
    assert after["status"] == "OPEN", (
        "failed fiscal check does not consume the project"
    )
    assert after["capitalized_asset_id"] is None


def test_capitalize_cancelled_project_returns_project_not_open(api):
    """PRD §2.10: "When multiple validation rules could reject the same request,
    the server evaluates them in a fixed priority order so the returned error is
    deterministic."
    PRD §2.10: "**(4) state** — the target entity must be in the required
    from-state (`ERR_INVALID_STATE`, `ERR_PROJECT_NOT_OPEN`,
    `ERR_ASSET_NOT_IN_SERVICE`, `ERR_ALREADY_DISPOSED`, `ERR_RUN_NOT_COUNTING`)"
    PRD §2.10: "**(8) monetary and field-value rules**
    (`ERR_BELOW_CAPITALIZATION_THRESHOLD`, `ERR_INVALID_AMOUNT`,
    `ERR_INVALID_SALVAGE_VALUE`, `ERR_INVALID_DISPOSAL_FIELDS`,
    `ERR_BONUS_NOT_ALLOWED`, `ERR_NO_IMPAIRMENT_INDICATED`,
    `ERR_INVALID_SCHEDULE_FIELDS`)"

    Design: Difficulty/priority_pair_validation_conflict/capitalize_state_error_beats_fiscal_error
    """
    cls = create_class()
    project, _lines = create_project_with_lines(
        cls["id"], [100000], project_code="PROJ-1", name="Small works"
    )
    validate_success(api.cancel_project(project["id"], CTRL), 200)

    # The cancelled project is also below the 250000 threshold: the priority-4
    # state failure must win over the priority-8 fiscal failure.
    resp = api.capitalize_project(
        project["id"], {"asset_tag": "A-901", "description": "Would-be asset"},
        CTRL,
    )
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_OPEN, 409)


def test_failed_capitalize_leaves_project_and_assets_untouched(api):
    """PRD §3.1: "the project must be `OPEN` (else `ERR_PROJECT_NOT_OPEN`)"
    PRD §3.1: "a `Controller` may cancel an `OPEN` project: the project moves
    from `OPEN` to `CANCELLED`, no asset is created, and its posted cost lines
    remain `POSTED` as an audit trail — the project is simply written off."

    Design: Difficulty/priority_pair_validation_conflict/capitalize_state_error_beats_fiscal_error
    """
    cls = create_class()
    project, _lines = create_project_with_lines(
        cls["id"], [100000], project_code="PROJ-1B", name="Small works"
    )
    validate_success(api.cancel_project(project["id"], CTRL), 200)

    resp = api.capitalize_project(
        project["id"], {"asset_tag": "A-901", "description": "Would-be asset"},
        CTRL,
    )
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_OPEN, 409)

    after = validate_success(api.get_capital_project(project["id"], ACCT), 200)
    assert after["status"] == "CANCELLED"
    assets, meta = validate_paginated(api.list_fixed_assets(ACCT))
    assert meta["total_count"] == 0 and assets == [], (
        "no FixedAsset with asset_tag A-901 exists"
    )


def test_zero_amount_cost_line_rejected(api):
    """PRD §3.1: "An `AssetAccountant` posts a line by naming the `project_id`,
    an `amount_cents` strictly greater than zero (anything else is
    `ERR_INVALID_AMOUNT`), a `cost_type` of `MATERIAL`, `LABOR`,
    `VENDOR_INVOICE`, or `OTHER`, and the `incurred_date` on which the cost was
    incurred."

    Design: Corner/validations/zero_amount_cost_line_rejected
    """
    cls = create_class()
    project = create_project(cls["id"], project_code="PROJ-Z", name="Zero line")
    resp = api.create_cip_cost_line(
        {"project_id": project["id"], "amount_cents": 0, "cost_type": "OTHER",
         "incurred_date": "2026-01-01"},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT, 422)

    after = validate_success(api.get_capital_project(project["id"], ACCT), 200)
    assert after["total_accumulated_cents"] == 0


def test_capitalized_asset_discoverable_both_directions(api):
    """PRD §3.1: "On success the project transitions from `OPEN` to
    `CAPITALIZED`, its `capitalized_asset_id` is set to the new asset, and a
    `FixedAsset` is created in status `DRAFT` with `source` equal to
    `CIP_CAPITALIZATION`, the project's `asset_class_id`, and an
    `acquisition_cost_cents` equal to the project's accumulated total."
    PRD §3.1: "Projects can be listed and filtered by `asset_class_id`, by
    `capitalized_asset_id`, or by `status`."

    Design: Corner/endpoints/capitalized_asset_discoverable_both_directions
    """
    cls = create_class()
    project, _lines = create_project_with_lines(
        cls["id"], [300000], project_code="PROJ-DISC", name="Discoverable"
    )
    data = capitalize_project(project["id"], "A-060", "From CIP")
    asset_id = data["capitalized_asset_id"]
    assert data["status"] == "CAPITALIZED"
    assert asset_id is not None

    projects, meta = validate_paginated(
        api.list_capital_projects(ACCT, params={"capitalized_asset_id": asset_id})
    )
    assert meta["total_count"] == 1
    assert [p["id"] for p in projects] == [project["id"]]

    asset = validate_success(api.get_fixed_asset(asset_id, ACCT), 200)
    assert asset["source"] == "CIP_CAPITALIZATION"
    assert asset["status"] == "DRAFT"
    assert asset["acquisition_cost_cents"] == 300000
    assert asset["asset_tag"] == "A-060"


def test_filtered_lists_scope_results(api):
    """PRD §4: "List cost lines of a project" — the per-project cost-line
    sub-resource returns only that project's lines.
    PRD §3.1: "Costs flow onto the project as **CIP cost lines**. An
    `AssetAccountant` posts a line by naming the `project_id`"

    Design: Corner/endpoints/filtered_lists_scope_results
    """
    cls = create_class()
    p1 = create_project(cls["id"], project_code="PROJ-F1", name="Filter 1")
    p2 = create_project(cls["id"], project_code="PROJ-F2", name="Filter 2")
    post_cost_line(p1["id"], 100, incurred_date="2026-01-01")
    post_cost_line(p1["id"], 200, cost_type="LABOR", incurred_date="2026-01-02")
    post_cost_line(p2["id"], 300, cost_type="OTHER", incurred_date="2026-01-03")

    lines, meta = validate_paginated(api.list_project_cost_lines(p1["id"], CTRL))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert sorted(line["amount_cents"] for line in lines) == [100, 200]
    assert all(line["project_id"] == p1["id"] for line in lines), (
        "no cross-contamination from PROJ-F2"
    )
