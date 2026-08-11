"""Supersede side effects: tint-formula revisions (PRD §3.4) and
single-approval-per-project on spec sheets (PRD §3.5)."""
from test_helpers import (
    TEST_USERS,
    assert_tint_formula,
    create_product,
    create_spec_sheet_with_line,
    create_tint_formula_payload,
    submit_spec_sheet,
    approve_spec_sheet,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
WRITER = TEST_USERS["spec_writer_headers"]


def test_new_formula_revision_supersedes_prior(api):
    """PRD §3.4: "Formulas carry a per-(product, color) `revision` sequence
    starting at 1: when a `StoreAssociate` or `CorporateAdmin` creates a
    formula for a `(product_id, color_code)` pair that already has an `ACTIVE`
    formula, the prior formula is retired to `RETIRED` and the new formula's
    `supersedes_formula_id` points at it; the new formula's `revision` is the
    prior maximum plus one, or 1 for the first formula of the pair — and a
    first formula, having no predecessor, carries a null
    `supersedes_formula_id`. Formulas created directly this way have `source`
    `LIBRARY`."

    Design: Corner/state_machines/formula_revision_supersedes_prior
    """
    product = create_product(sku="P-SUP", name="Base", list_price_cents=5000,
                             tintable=True)
    resp = api.create_tint_formula(
        create_tint_formula_payload(product["id"], color_code="SW 3000",
                                    name="V1",
                                    shots=[{"colorant_code": "R1",
                                            "ounces_128ths": 8}]),
        ADMIN)
    f1 = validate_success(resp, expected_status=201)
    assert f1["revision"] == 1
    assert f1["supersedes_formula_id"] is None, (
        "a first formula, having no predecessor, carries a null supersedes link")
    resp = api.create_tint_formula(
        create_tint_formula_payload(product["id"], color_code="SW 3000",
                                    name="V2",
                                    shots=[{"colorant_code": "R1",
                                            "ounces_128ths": 12}]),
        ADMIN)
    f2 = validate_success(resp, expected_status=201)
    assert_tint_formula(f2)
    f1_after = validate_success(api.get_tint_formula(f1["id"], ADMIN))
    assert f1_after["status"] == "RETIRED", (
        f"the prior ACTIVE formula is retired, got {f1_after['status']}")
    assert f2["status"] == "ACTIVE"
    assert f2["revision"] == 2, (
        f"the new revision is the prior maximum plus one, got {f2['revision']}")
    assert f2["supersedes_formula_id"] == f1["id"], (
        "the new formula's supersedes link points at the retired predecessor")
    assert f2["source"] == "LIBRARY"


def _setup_two_submitted_sheets(api, product_id):
    """Two DRAFT->SUBMITTED sheets for the same project code."""
    s1 = create_spec_sheet_with_line(product_id, project_code="PRJ-SS",
                                     specified_qty=5, title="V1")
    submit_spec_sheet(s1["id"])
    s2 = create_spec_sheet_with_line(product_id, project_code="PRJ-SS",
                                     specified_qty=7, title="V2")
    submit_spec_sheet(s2["id"])
    return s1, s2


def test_second_approval_supersedes_first_sheet(api):
    """PRD §3.5: "A successful approval stamps `approved_at` from the logical
    clock and enforces single-approval-per-project: at most one sheet per
    `project_code` may be `APPROVED` at any time, so any *other* `APPROVED`
    sheet for the same project transitions `APPROVED` to the terminal
    `SUPERSEDED`, and the newly approved sheet's `supersedes_spec_sheet_id`
    records that sheet's id (null when none existed)."

    Design: Corner/state_machines/second_approval_supersedes_first_sheet
    """
    product = create_product(sku="P-SS", name="Can", list_price_cents=5000)
    s1, s2 = _setup_two_submitted_sheets(api, product["id"])
    approve_spec_sheet(s1["id"])
    approve_spec_sheet(s2["id"])
    s1_after = validate_success(api.get_spec_sheet(s1["id"], WRITER))
    s2_after = validate_success(api.get_spec_sheet(s2["id"], WRITER))
    assert s1_after["status"] == "SUPERSEDED", (
        f"the previously APPROVED sheet for the project is superseded, "
        f"got {s1_after['status']}")
    assert s2_after["status"] == "APPROVED"
    assert s2_after["supersedes_spec_sheet_id"] == s1["id"], (
        "the newly approved sheet records the superseded sheet's id")
