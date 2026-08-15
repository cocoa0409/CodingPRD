"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: ClientRep and QualityManager calls are entity-backed by
Client, so every helper that touches client-owned resources builds headers
from the real client id via make_client_rep_headers / make_quality_manager_headers.

Canonical statements: label drafts need the exact canonical
ingredient_statement_text / contains_text of the product's LOCKED recipe.
Helpers discover them through the computed-statement endpoint
(GET /api/recipes/{id}/ingredient-statement) unless the caller passes
explicit strings (needed for drafts created before any lock, and for tests
that deliberately draft wrong statements).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_artwork_audit_payload,
    create_audit_finding_payload,
    create_claim_payload,
    create_client_payload,
    create_ingredient_payload,
    create_label_version_payload,
    create_market_variant_payload,
    create_nutrient_panel_payload,
    create_product_payload,
    create_racc_assignment_payload,
    create_recipe_payload,
    create_lab_analysis_payload,
    review_lab_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_rep_headers,
    make_label_analyst_headers,
    make_quality_manager_headers,
    make_regulatory_reviewer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["label_analyst_headers"]
REVIEWER = TEST_USERS["regulatory_reviewer_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and transitions
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin only). Returns response data."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_client(name="Acme Foods", home_market_code="US_FDA"):
    """Onboard a client. Returns the client."""
    return get_success_data(
        api_client.create_client(create_client_payload(name=name,
                                                       home_market_code=home_market_code),
                                 ADMIN))


def create_product(client, include_household=True, **overrides):
    """Register a product under the client (ClientRep, own chain)."""
    return get_success_data(
        api_client.create_product(client["id"],
                                  create_product_payload(
                                      include_household=include_household,
                                      **overrides),
                                  make_client_rep_headers(client["id"])))


def create_ingredient(client, include_allergen_tags=False, **overrides):
    """Create an ingredient with its database nutrient profile."""
    return get_success_data(
        api_client.create_ingredient(client["id"],
                                     create_ingredient_payload(
                                         include_allergen_tags=include_allergen_tags,
                                         **overrides),
                                     make_client_rep_headers(client["id"])))


def create_recipe(product_id, client_id, lines, yield_factor=None, **overrides):
    """Create a formulation (born DRAFT). Returns the recipe."""
    return get_success_data(
        api_client.create_recipe(product_id,
                                 create_recipe_payload(lines,
                                                       yield_factor=yield_factor,
                                                       **overrides),
                                 make_client_rep_headers(client_id)))


def get_recipe(recipe_id):
    return get_success_data(api_client.get_recipe(recipe_id, ADMIN))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, ADMIN))


def get_label_version(label_version_id):
    return get_success_data(api_client.get_label_version(label_version_id, ADMIN))


def get_market_variants(label_version_id):
    return get_success_data(api_client.list_market_variants(label_version_id, ADMIN))


def lock_recipe(recipe_id, client_id):
    """Lock a DRAFT recipe (ClientRep, own chain). Returns the LOCKED recipe."""
    return get_success_data(
        api_client.lock_recipe(recipe_id, make_client_rep_headers(client_id)))


def create_and_lock_recipe(product_id, client_id, lines, yield_factor=None, **overrides):
    recipe = create_recipe(product_id, client_id, lines,
                           yield_factor=yield_factor, **overrides)
    return lock_recipe(recipe["id"], client_id)


def compute_panel(recipe_id, method="DATABASE"):
    """Compute a nutrient panel (LabelAnalyst). Returns the CURRENT panel."""
    return get_success_data(
        api_client.create_nutrient_panel(recipe_id,
                                         create_nutrient_panel_payload(method=method),
                                         ANALYST))


def create_racc_assignment(product_id, market_code="US_FDA"):
    """Determine serving size for a market (LabelAnalyst). Returns the assignment."""
    return get_success_data(
        api_client.create_racc_assignment(product_id,
                                          create_racc_assignment_payload(
                                              market_code=market_code),
                                          ANALYST))


def canonical_statements(recipe_id):
    """Computed canonical ingredient statement + Contains statement for the
    product's currently LOCKED recipe. Returns the full data dict with
    ingredient_statement_text, contains_text, and canonical_order."""
    return get_success_data(api_client.get_ingredient_statement(recipe_id, ADMIN))


def create_label_draft(product_id, racc_assignment_id, nutrient_basis="DATABASE",
                       market_code="US_FDA", declared_format="TABULAR",
                       declared_type_size_in=0.0625,
                       ingredient_statement_text=None, contains_text=None,
                       statement_recipe_id=None, analyst_id="analyst-1"):
    """Create a label draft (LabelAnalyst), threading the product's live
    version into expected_product_version (OCC).

    When the statement texts are not given, they are discovered from the
    computed-statement endpoint of statement_recipe_id (the product's LOCKED
    recipe), which is exactly what submit-review will validate against.
    Returns the draft."""
    product = get_product(product_id)
    if ingredient_statement_text is None or contains_text is None:
        assert statement_recipe_id is not None, (
            "statement_recipe_id is required to discover canonical statements"
        )
        canonical = canonical_statements(statement_recipe_id)
        ingredient_statement_text = (ingredient_statement_text
                                     or canonical["ingredient_statement_text"])
        contains_text = contains_text or canonical["contains_text"]
    payload = create_label_version_payload(
        racc_assignment_id,
        product["version"],
        ingredient_statement_text,
        contains_text,
        market_code=market_code,
        nutrient_basis=nutrient_basis,
        declared_format=declared_format,
        declared_type_size_in=declared_type_size_in,
    )
    return get_success_data(
        api_client.create_label_version(product_id, payload,
                                        make_label_analyst_headers(analyst_id)))


def submit_label(label_version_id, analyst_id="analyst-1"):
    """Submit a DRAFT label for review. Returns the IN_REVIEW label."""
    return get_success_data(
        api_client.submit_label_review(label_version_id,
                                       make_label_analyst_headers(analyst_id)))


def approve_label(label_version_id, reviewer_id="reviewer-1"):
    """Approve an IN_REVIEW label (RegulatoryReviewer, id != prepared_by)."""
    return get_success_data(
        api_client.approve_label(label_version_id,
                                 make_regulatory_reviewer_headers(reviewer_id)))


def reject_label(label_version_id, reviewer_id="reviewer-1", reason="needs rework"):
    return get_success_data(
        api_client.reject_label(label_version_id,
                                make_regulatory_reviewer_headers(reviewer_id),
                                reason=reason))


def release_label(product_id, label_version_id, client_id):
    """Release an APPROVED label (QualityManager, own chain), threading the
    product's live version into expected_product_version (OCC)."""
    product = get_product(product_id)
    return get_success_data(
        api_client.release_label(label_version_id,
                                 {"expected_product_version": product["version"]},
                                 make_quality_manager_headers(client_id)))


def withdraw_label(label_version_id, client_id, reason="retailer hold"):
    return get_success_data(
        api_client.withdraw_label(label_version_id,
                                  make_quality_manager_headers(client_id),
                                  reason=reason))


def create_claim(label_version_id, claim_type="LOW_FAT", analyst_id="analyst-1"):
    """Declare an on-pack claim (LabelAnalyst); evaluation is synchronous."""
    return get_success_data(
        api_client.create_claim(label_version_id,
                                create_claim_payload(claim_type=claim_type),
                                make_label_analyst_headers(analyst_id)))


def list_claims(label_version_id):
    data, _meta = validate_paginated(api_client.list_claims(label_version_id, ADMIN))
    return data


def create_market_variant(label_version_id, market_code="CA_CFIA",
                          effective_start="2026-09-01T00:00:00Z",
                          effective_end=None, translated_contains_text=None,
                          analyst_id="analyst-1"):
    """Adapt a label to another market with an effective window. Returns the
    DRAFT variant."""
    return get_success_data(
        api_client.create_market_variant(
            label_version_id,
            create_market_variant_payload(
                effective_start,
                market_code=market_code,
                effective_end=effective_end,
                translated_contains_text=translated_contains_text),
            make_label_analyst_headers(analyst_id)))


def submit_lab_analysis(recipe_id, client_id, **overrides):
    """Submit a lab assay for a recipe (ClientRep, own chain)."""
    return get_success_data(
        api_client.create_lab_analysis(recipe_id,
                                       create_lab_analysis_payload(**overrides),
                                       make_client_rep_headers(client_id)))


def review_lab_analysis(lab_analysis_id, outcome="VALIDATED", reviewer_id="reviewer-1"):
    return get_success_data(
        api_client.review_lab_analysis(lab_analysis_id,
                                       review_lab_payload(outcome=outcome),
                                       make_regulatory_reviewer_headers(reviewer_id)))


def schedule_audit(client_id, product_id, label_version_id, facility_code="F1",
                   scheduled_start="2026-09-10T00:00:00Z",
                   scheduled_end="2026-09-12T00:00:00Z", scoring_method=None):
    """Schedule an artwork audit (ComplianceAuditor). Returns the SCHEDULED audit."""
    return get_success_data(
        api_client.create_artwork_audit(
            client_id,
            create_artwork_audit_payload(product_id, label_version_id,
                                         scheduled_start, scheduled_end,
                                         scoring_method=scoring_method,
                                         facility_code=facility_code),
            AUDITOR))


def log_finding(audit_id, severity="MAJOR", field_ref="NUTRITION_VALUES",
                on_pack_text="on-pack text", approved_text="approved text"):
    return get_success_data(
        api_client.create_audit_finding(audit_id,
                                        create_audit_finding_payload(
                                            severity=severity, field_ref=field_ref,
                                            on_pack_text=on_pack_text,
                                            approved_text=approved_text),
                                        AUDITOR))


# ---------------------------------------------------------------------------
# Tier 2: standard workspaces (client + product + ingredients + recipe)
# ---------------------------------------------------------------------------

def setup_wafer_workspace(product_overrides=None, label_overrides=None,
                          market_code="US_FDA", lock=True, with_panel=True,
                          with_racc=True, with_label=True, submit=False):
    """Client + one BAKED_GOOD product + single-ingredient 'Wafers' recipe
    (allergen-free, so the canonical Contains statement is the PRD-exact
    'Contains: None.') + optional lock / DATABASE panel / RACC assignment /
    label draft (+ optional submit).

    Returns a dict with every created entity and the per-instance headers.
    """
    client = create_client(home_market_code=market_code)
    product = create_product(client, **(product_overrides or {}))
    wafer = create_ingredient(client, name="Wafers")
    recipe = create_recipe(product["id"], client["id"],
                           [{"ingredient_id": wafer["id"], "quantity_g": 100}])
    ws = {
        "client": client, "product": product, "wafer": wafer, "recipe": recipe,
        "panel": None, "racc": None, "label": None,
        "admin_headers": ADMIN, "analyst_headers": ANALYST,
        "reviewer_headers": REVIEWER, "auditor_headers": AUDITOR,
        "client_rep_headers": make_client_rep_headers(client["id"]),
        "quality_manager_headers": make_quality_manager_headers(client["id"]),
    }
    if lock:
        ws["recipe"] = lock_recipe(recipe["id"], client["id"])
    if with_panel:
        ws["panel"] = compute_panel(ws["recipe"]["id"], method="DATABASE")
    if with_racc:
        ws["racc"] = create_racc_assignment(product["id"], market_code=market_code)
    if with_label:
        label_kw = {"market_code": market_code}
        label_kw.update(label_overrides or {})
        ws["label"] = create_label_draft(
            product["id"], ws["racc"]["id"],
            statement_recipe_id=ws["recipe"]["id"], **label_kw)
        if submit:
            ws["label"] = submit_label(ws["label"]["id"])
    return ws


def setup_cookie_workspace(market_code="US_FDA", nutrient_basis="DATABASE",
                           yield_factor=1.0, submit=False,
                           product_overrides=None, label_overrides=None):
    """Client + one BAKED_GOOD product (110 g, 27.5 g piece) + Wheat Flour
    (WHEAT) and Sugar ingredients + a 120 g / 40 g recipe, LOCKED + DATABASE
    panel + RACC assignment + label draft whose statements are discovered
    from the computed-statement endpoint.

    Returns a dict with every created entity and the per-instance headers.
    """
    client = create_client(home_market_code=market_code)
    product = create_product(client, **(product_overrides or {}))
    flour = create_ingredient(
        client, name="Wheat Flour", allergen_tags=["WHEAT"],
        kcal_per_100g=360, fat_g_per_100g=2.0, satfat_g_per_100g=0.3,
        chol_mg_per_100g=0, sodium_mg_per_100g=5, carb_g_per_100g=75,
        fiber_g_per_100g=3.0, sugar_g_per_100g=1.0, protein_g_per_100g=10)
    sugar = create_ingredient(
        client, name="Sugar",
        kcal_per_100g=387, fat_g_per_100g=0, satfat_g_per_100g=0,
        chol_mg_per_100g=0, sodium_mg_per_100g=0, carb_g_per_100g=100,
        fiber_g_per_100g=0, sugar_g_per_100g=100, protein_g_per_100g=0)
    recipe = create_and_lock_recipe(
        product["id"], client["id"],
        [{"ingredient_id": flour["id"], "quantity_g": 120},
         {"ingredient_id": sugar["id"], "quantity_g": 40}],
        yield_factor=yield_factor)
    panel = compute_panel(recipe["id"], method="DATABASE")
    racc = create_racc_assignment(product["id"], market_code=market_code)
    label_kw = {"market_code": market_code, "nutrient_basis": nutrient_basis}
    label_kw.update(label_overrides or {})
    label = create_label_draft(product["id"], racc["id"],
                               statement_recipe_id=recipe["id"], **label_kw)
    ws = {
        "client": client, "product": product, "flour": flour, "sugar": sugar,
        "recipe": recipe, "panel": panel, "racc": racc, "label": label,
        "admin_headers": ADMIN, "analyst_headers": ANALYST,
        "reviewer_headers": REVIEWER, "auditor_headers": AUDITOR,
        "client_rep_headers": make_client_rep_headers(client["id"]),
        "quality_manager_headers": make_quality_manager_headers(client["id"]),
    }
    if submit:
        ws["label"] = submit_label(label["id"])
    return ws


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts (label review/release, audits)
# ---------------------------------------------------------------------------

def setup_approved_wafer_label(**kwargs):
    """Wafer workspace with the label submitted and APPROVED."""
    kwargs["submit"] = True
    ws = setup_wafer_workspace(**kwargs)
    ws["label"] = approve_label(ws["label"]["id"])
    return ws


def setup_released_wafer_label(**kwargs):
    """Wafer workspace with the label APPROVED and RELEASED."""
    ws = setup_approved_wafer_label(**kwargs)
    ws["label"] = release_label(ws["product"]["id"], ws["label"]["id"],
                                ws["client"]["id"])
    return ws


def setup_released_label_with_audit(scoring_method=None, facility_code="F1",
                                    scheduled_start="2026-09-10T00:00:00Z",
                                    scheduled_end="2026-09-12T00:00:00Z", **kwargs):
    """Released wafer label + one SCHEDULED artwork audit."""
    ws = setup_released_wafer_label(**kwargs)
    ws["audit"] = schedule_audit(ws["client"]["id"], ws["product"]["id"],
                                 ws["label"]["id"], facility_code=facility_code,
                                 scheduled_start=scheduled_start,
                                 scheduled_end=scheduled_end,
                                 scoring_method=scoring_method)
    return ws


def setup_lab_claim_workspace():
    """Cookie workspace on the LAB basis: lab analysis LR-100 VALIDATED,
    LAB panel CURRENT, LAB-basis label IN_REVIEW, and a LOW_FAT claim that
    evaluates ELIGIBLE (fat per RACC 0.77 <= 3.0).

    Returns the workspace dict with lab1 and claim entries added.
    """
    client = create_client()
    product = create_product(client)
    flour = create_ingredient(
        client, name="Wheat Flour", allergen_tags=["WHEAT"],
        kcal_per_100g=360, fat_g_per_100g=2.0, satfat_g_per_100g=0.3,
        chol_mg_per_100g=0, sodium_mg_per_100g=5, carb_g_per_100g=75,
        fiber_g_per_100g=3.0, sugar_g_per_100g=1.0, protein_g_per_100g=10)
    sugar = create_ingredient(
        client, name="Sugar",
        kcal_per_100g=387, fat_g_per_100g=0, satfat_g_per_100g=0,
        chol_mg_per_100g=0, sodium_mg_per_100g=0, carb_g_per_100g=100,
        fiber_g_per_100g=0, sugar_g_per_100g=100, protein_g_per_100g=0)
    recipe = create_and_lock_recipe(
        product["id"], client["id"],
        [{"ingredient_id": flour["id"], "quantity_g": 120},
         {"ingredient_id": sugar["id"], "quantity_g": 40}])
    lab1 = submit_lab_analysis(recipe["id"], client["id"], lab_report_ref="LR-100")
    lab1 = review_lab_analysis(lab1["id"], outcome="VALIDATED")
    panel = compute_panel(recipe["id"], method="LAB")
    racc = create_racc_assignment(product["id"], market_code="US_FDA")
    label = create_label_draft(product["id"], racc["id"], nutrient_basis="LAB",
                               statement_recipe_id=recipe["id"])
    label = submit_label(label["id"])
    claim = create_claim(label["id"], "LOW_FAT")
    return {
        "client": client, "product": product, "flour": flour, "sugar": sugar,
        "recipe": recipe, "lab1": lab1, "panel": panel, "racc": racc,
        "label": label, "claim": claim,
        "admin_headers": ADMIN, "analyst_headers": ANALYST,
        "reviewer_headers": REVIEWER, "auditor_headers": AUDITOR,
        "client_rep_headers": make_client_rep_headers(client["id"]),
        "quality_manager_headers": make_quality_manager_headers(client["id"]),
    }
