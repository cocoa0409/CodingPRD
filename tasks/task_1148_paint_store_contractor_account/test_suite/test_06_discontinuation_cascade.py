"""Bulletin take-effect discontinuation cascade: product -> formulas -> spec
lines -> spec sheets (PRD §3.3), plus the approval gate against discontinued
products (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_product,
    assert_product_bulletin,
    assert_spec_line,
    assert_spec_sheet,
    assert_tint_formula,
    create_publish_bulletin,
    create_product,
    create_spec_sheet_with_line,
    create_tint_formula_payload,
    get_first_spec_line,
    set_logical_clock,
    setup_approved_spec_with_line,
    submit_spec_sheet,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
WRITER = TEST_USERS["spec_writer_headers"]

EFFECTIVE_DATE = "2026-06-01T00:00:00Z"


def _setup_cascade_scenario(api):
    """OLD product (tintable, with an ACTIVE formula) + NEW replacement;
    APPROVED sheet specifying OLD; published bulletin effective 2026-06-01
    with the clock advanced to the effective date."""
    p_old = create_product(sku="P-OLD", name="Legacy Flat", category="FLAT",
                           voc_gpl=100, list_price_cents=10_000, tintable=True)
    p_new = create_product(sku="P-NEW", name="Successor Flat", category="FLAT",
                           voc_gpl=120, list_price_cents=11_000, tintable=True)
    resp = api.create_tint_formula(
        create_tint_formula_payload(p_old["id"], color_code="SW 1000",
                                    name="Legacy White",
                                    shots=[{"colorant_code": "W1",
                                            "ounces_128ths": 16}]),
        ADMIN)
    formula = validate_success(resp, expected_status=201)
    sheet, line = setup_approved_spec_with_line(
        p_old["id"], project_code="PRJ-DC", specified_qty=5)
    bulletin = create_publish_bulletin(
        p_old["id"], p_new["id"], effective_date=EFFECTIVE_DATE,
        title="P-OLD discontinuation")
    set_logical_clock(EFFECTIVE_DATE)
    return p_old, p_new, formula, sheet, line, bulletin


def test_take_effect_discontinues_product_and_retires_formulas(api):
    """PRD §3.3: "Take-effect fires a four-hop cascade: **hop 1** transitions
    the subject product `ACTIVE` to `DISCONTINUED` and copies the bulletin's
    replacement into the product's `replacement_product_id`; **hop 2**, caused
    by the product mutation itself, retires every `ACTIVE` tint formula of
    that product and flags every spec line referencing that product on a sheet
    whose `status` is `SUBMITTED` or `APPROVED` by setting its `obsoleted`
    flag true; ... and the bulletin itself stamps `effected_at` — likewise
    null until take-effect — from the logical clock."

    Design: Difficulty/transitive_cascade/bulletin_effect_discontinuation_chain
    """
    p_old, p_new, formula, sheet, line, bulletin = _setup_cascade_scenario(api)
    resp = api.take_effect_product_bulletin(bulletin["id"], ADMIN)
    effected = validate_success(resp, expected_status=200)
    assert_product_bulletin(effected)
    assert effected["status"] == "EFFECTIVE"
    product_after = validate_success(api.get_product(p_old["id"], ADMIN))
    assert_product(product_after)
    assert product_after["status"] == "DISCONTINUED", (
        f"hop 1 must discontinue the subject product, got {product_after['status']}")
    assert product_after["replacement_product_id"] == p_new["id"], (
        "hop 1 copies the bulletin's replacement into the product")
    formula_after = validate_success(api.get_tint_formula(formula["id"], ADMIN))
    assert formula_after["status"] == "RETIRED", (
        f"hop 2 retires the product's ACTIVE formulas, got {formula_after['status']}")
    line_after = validate_success(api.get_spec_line(line["id"], WRITER))
    assert line_after["obsoleted"] is True, (
        "hop 2 flags spec lines of the discontinued product on non-terminal sheets")


def test_cascade_drives_approved_sheet_to_needs_revision(api):
    """PRD §3.3: "**hop 3**, caused by the spec-line mutations, pushes every
    `APPROVED` sheet holding at least one newly obsoleted line into
    `NEEDS_REVISION` (see §3.5)". PRD §2.9: "Several operations mutate more
    than one entity in a single cascade — a discontinuation bulletin hops from
    product to formulas to spec lines to spec sheets ... Every hop of every
    cascade is spelled out with the owning workflow in Section 3, and every
    entity mutated along the way takes its own `version` increment."

    Design: Difficulty/transitive_cascade/bulletin_effect_discontinuation_chain
    """
    p_old, p_new, formula, sheet, line, bulletin = _setup_cascade_scenario(api)
    validate_success(api.take_effect_product_bulletin(bulletin["id"], ADMIN))
    sheet_after = validate_success(api.get_spec_sheet(sheet["id"], WRITER))
    assert_spec_sheet(sheet_after)
    assert sheet_after["status"] == "NEEDS_REVISION", (
        f"hop 3: the SpecLine mutation itself drives the APPROVED sheet to "
        f"NEEDS_REVISION, got {sheet_after['status']}")


def _setup_blocked_approval(api):
    """SUBMITTED sheet specifying OLD2; bulletin discontinuing OLD2 already
    EFFECTIVE at 2026-06-01."""
    p_old = create_product(sku="P-OLD2", name="Legacy NF", category="NON_FLAT",
                           voc_gpl=100, list_price_cents=9000)
    p_new = create_product(sku="P-NEW2", name="Successor NF", category="NON_FLAT",
                           voc_gpl=110, list_price_cents=9500)
    sheet = create_spec_sheet_with_line(p_old["id"], project_code="PRJ-BLK",
                                        specified_qty=3)
    line = get_first_spec_line(sheet["id"])
    submit_spec_sheet(sheet["id"])
    bulletin = create_publish_bulletin(p_old["id"], p_new["id"],
                                       effective_date=EFFECTIVE_DATE,
                                       title="P-OLD2 discontinuation")
    set_logical_clock(EFFECTIVE_DATE)
    validate_success(api.take_effect_product_bulletin(bulletin["id"], ADMIN))
    return sheet, line


def test_approval_blocked_by_discontinued_product(api):
    """PRD §3.5: "Approval is a version-pinning gate: every line's product
    must still be `ACTIVE`, so a sheet referencing a discontinued product
    cannot be approved and fails with `ERR_PRODUCT_DISCONTINUED` (HTTP 422) —
    the sheet's live product references are pinned at approval."

    Design: Difficulty/cross_entity_state_dependency/spec_approve_blocked_by_discontinued_product
    """
    sheet, line = _setup_blocked_approval(api)
    resp = api.approve_spec_sheet(sheet["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED)


def test_blocked_sheet_stays_submitted_with_obsoleted_line(api):
    """PRD §3.3: "**hop 3**, caused by the spec-line mutations, pushes every
    `APPROVED` sheet holding at least one newly obsoleted line into
    `NEEDS_REVISION` (see §3.5)". PRD §3.5: "A sheet can also reach
    `NEEDS_REVISION` without human action: when a discontinuation bulletin
    obsoletes one of its lines while the sheet is `APPROVED` (§3.3, hop 3),
    the sheet itself transitions `APPROVED` to `NEEDS_REVISION`."

    The cascade re-routes only APPROVED sheets: a SUBMITTED sheet whose line
    was obsoleted stays SUBMITTED (with the obsoleted flag set), and its
    approval is what the version-pinning gate rejects.

    Design: Difficulty/cross_entity_state_dependency/spec_approve_blocked_by_discontinued_product
    """
    sheet, line = _setup_blocked_approval(api)
    resp = api.approve_spec_sheet(sheet["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED)
    sheet_after = validate_success(api.get_spec_sheet(sheet["id"], WRITER))
    assert sheet_after["status"] == "SUBMITTED", (
        f"the cascade only re-routes APPROVED sheets, so this sheet stays "
        f"SUBMITTED, got {sheet_after['status']}")
    line_after = validate_success(api.get_spec_line(line["id"], WRITER))
    assert line_after["obsoleted"] is True, (
        "hop 2 flagged the SUBMITTED sheet's line obsoleted")
