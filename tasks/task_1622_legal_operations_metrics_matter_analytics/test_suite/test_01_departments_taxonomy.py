"""Department configuration defaults, taxonomy rules, and business-key uniqueness."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_department,
    create_department,
    create_fiscal_period,
    create_practice_area,
    create_matter_type,
    create_firm,
    create_counsel,
    create_matter,
    create_matter_payload,
    setup_matter_graph,
    validate_success,
    validate_error,
    ANALYST,
)


def test_department_create_applies_governance_defaults(api, manager_headers):
    """PRD §3.1: "`budget_warning_pct` defaults to 0.8 — when consumption reaches
    eighty percent of a budget's allocation, that budget's posture flips to
    `WARNING`. `budget_critical_pct` defaults to 0.95 and must sit strictly above
    the warning level; reaching it marks the budget `CRITICAL`."
    PRD §3.1: "`deflection_target_pct`, defaulting to 0.30, sets the department's
    self-service deflection goal"

    Design: Corner/entities/department_create_with_defaults
    """
    dept = validate_success(
        api.create_department({"name": "Default-Legal-Defaults"}, manager_headers), 201
    )
    assert_department(dept)
    assert dept["budget_warning_pct"] == 0.8
    assert dept["budget_critical_pct"] == 0.95
    assert dept["deflection_target_pct"] == 0.3


def test_matter_number_unique_across_fiscal_periods(api):
    """PRD §3.3: "A `LegalOpsAnalyst` opens a matter by supplying its
    `matter_number` — a unique business key in the format LGL-YYYY-NNNNN — along
    with a `title`, the `practice_area_id` and `matter_type_id` classifying it,
    the `fiscal_period_id` of the period in which it opens, and the
    `lead_counsel_id` of the responsible in-house lawyer."
    PRD §3.1: "Uniqueness is enforced across the board at creation time with
    `ERR_DUPLICATE`: the department `name`, each practice-area `code`, each
    matter-type `code` within its practice area, each firm `name`, each counsel
    `email`, each matter `matter_number`, the pairing of `firm_id` and
    `invoice_number` on invoices, and the pairing of `fiscal_period_id` with
    `snapshot_label` on dashboards."

    Design: Difficulty/resource_temporal_overlap/matter_number_temporal_windowed_uniqueness
    """
    create_department()
    fp1 = create_fiscal_period(label="FY2026", start_date="2026-01-01", end_date="2026-12-31")
    fp2 = create_fiscal_period(label="FY2027", start_date="2027-01-01", end_date="2027-12-31")
    pa = create_practice_area(code="LIT", display_name="Litigation")
    mt = create_matter_type(pa["id"], code="LIT-C", display_name="Commercial")
    firm = create_firm()
    counsel = create_counsel()

    first = create_matter(
        pa["id"], mt["id"], fp1["id"], counsel["id"],
        matter_number="LGL-2026-00001", primary_firm_id=firm["id"],
    )
    assert first["matter_number"] == "LGL-2026-00001"

    # Same matter_number in a DIFFERENT fiscal period still collides — the key
    # space is global, not windowed per period.
    res = api_client.create_matter(
        create_matter_payload(
            pa["id"], mt["id"], fp2["id"], counsel["id"],
            matter_number="LGL-2026-00001", primary_firm_id=firm["id"],
        ),
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE)


def test_matter_number_duplicate_within_same_period_rejected(api):
    """PRD §3.1: "Uniqueness is enforced across the board at creation time with
    `ERR_DUPLICATE`: the department `name`, each practice-area `code`, each
    matter-type `code` within its practice area, each firm `name`, each counsel
    `email`, each matter `matter_number`, the pairing of `firm_id` and
    `invoice_number` on invoices, and the pairing of `fiscal_period_id` with
    `snapshot_label` on dashboards."

    Design: Difficulty/resource_temporal_overlap/matter_number_temporal_windowed_uniqueness
    """
    graph = setup_matter_graph(
        activate=False, assignment_hours=None,
        matter_overrides={"matter_number": "LGL-2026-00009"},
    )
    res = api_client.create_matter(
        create_matter_payload(
            graph["practice_area"]["id"],
            graph["matter_type"]["id"],
            graph["fiscal_period"]["id"],
            graph["counsel"]["id"],
            matter_number="LGL-2026-00009",
            primary_firm_id=graph["firm"]["id"],
        ),
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE)


def test_matter_type_under_missing_practice_area_returns_404(api, manager_headers):
    """PRD §2.10: "the server validates the identifiers strictly left to right and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier
    that does not resolve to an existing resource."

    Design: Corner/entities/matter_type_requires_valid_practice_area_parent
    """
    create_department()
    res = api.create_matter_type(
        NON_EXISTENT_UUID, {"code": "X1", "display_name": "Y"}, manager_headers
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_get_missing_matter_returns_404(api, analyst_headers):
    """PRD §2.12: "3. Existence — path identifiers, validated left to right, and
    body-supplied references yield `ERR_NOT_FOUND`."

    Design: Corner/entities/entity_get_not_found_returns_404
    """
    create_department()
    res = api.get_matter(NON_EXISTENT_UUID, analyst_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_get_missing_spend_line_returns_404(api, analyst_headers):
    """PRD §2.8: "The ledger is read-only through the API; rows can be listed and
    filtered by `matter_id`, `fiscal_period_id`, `firm_id`, `invoice_id`,
    `source_status`, or `reversal_of_id`."
    PRD §2.12: "3. Existence — path identifiers, validated left to right, and
    body-supplied references yield `ERR_NOT_FOUND`."

    Design: Corner/entities/spend_line_immutable_no_update_endpoint
    """
    res = api.get_spend_line(NON_EXISTENT_UUID, analyst_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_duplicate_practice_area_code_rejected(api, manager_headers):
    """PRD §3.1: "A practice area carries a stable `code` — two to eight uppercase
    alphanumeric characters, unique across all practice areas — plus a
    human-readable `display_name`, and begins life `ACTIVE`."
    PRD §3.1: "Uniqueness is enforced across the board at creation time with
    `ERR_DUPLICATE`"

    Design: Corner/validations/duplicate_practice_area_code_returns_duplicate
    """
    create_department()
    validate_success(
        api.create_practice_area({"code": "LIT", "display_name": "Litigation"}, manager_headers),
        201,
    )
    res = api.create_practice_area({"code": "LIT", "display_name": "Litigation 2"}, manager_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE)


def test_matter_taxonomy_mismatch_rejected(api):
    """PRD §3.3: "Creation is guarded, in order, by the taxonomy rule — the
    referenced matter type must belong to the referenced practice area, else
    `ERR_TAXONOMY_MISMATCH` (HTTP 422) — then by the calendar gate
    (`ERR_PERIOD_CLOSED` when the period is neither `OPEN` nor `REOPENED`), then
    by entity activity (`ERR_ENTITY_INACTIVE`, HTTP 422, when the practice area is
    not `ACTIVE`), then by uniqueness of `matter_number`, and finally by the
    amount rule: a negative `budget_cents` is `ERR_INVALID_AMOUNT` (HTTP 422)."

    Design: Corner/validations/taxonomy_mismatch_returns_error
    """
    create_department()
    fp = create_fiscal_period()
    pa1 = create_practice_area(code="LIT", display_name="Litigation")
    pa2 = create_practice_area(code="CORP", display_name="Corporate")
    mt = create_matter_type(pa1["id"], code="LIT-C", display_name="Commercial")
    firm = create_firm()
    counsel = create_counsel()

    # matter type belongs to pa1; matter names pa2 -> taxonomy mismatch
    res = api_client.create_matter(
        create_matter_payload(
            pa2["id"], mt["id"], fp["id"], counsel["id"], primary_firm_id=firm["id"]
        ),
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_TAXONOMY_MISMATCH)
