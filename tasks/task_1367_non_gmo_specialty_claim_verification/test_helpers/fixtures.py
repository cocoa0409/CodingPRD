"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"setup failed" errors instead of confusing assertion failures. Every helper
builds its preconditions from scratch against an empty database (the harness
restarts the server before each test).

Identity threading: BrandRep is entity-backed — every brand-owned write uses
make_brand_rep_headers(brand["id"]) with the real Brand.id, never the shared
TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .factories import (
    create_claim_standard_payload,
    create_brand_payload,
    create_product_payload,
    create_ingredient_payload,
    create_affidavit_payload,
    create_sampling_plan_payload,
    create_sample_payload,
    create_record_result_payload,
    create_facility_audit_payload,
    create_audit_report_payload,
    create_enforcement_case_payload,
)
from .test_users import TEST_USERS, make_brand_rep_headers

ADMIN = TEST_USERS["verifier_admin_headers"]
LAB_1 = TEST_USERS["lab_analyst_1_headers"]
LAB_2 = TEST_USERS["lab_analyst_2_headers"]
OFFICER_1 = TEST_USERS["officer_1_headers"]
OFFICER_2 = TEST_USERS["officer_2_headers"]

_AFF_FROM = "2026-01-01T00:00:00Z"
_AFF_UNTIL = "2028-01-01T00:00:00Z"


# ─── Tier 1: single-entity creation ─────────────────────────────────────────

def create_standard(**overrides):
    """Create a claim standard. Returns the standard dict."""
    return get_success_data(
        api_client.create_claim_standard(create_claim_standard_payload(**overrides), ADMIN)
    )


def create_brand(**overrides):
    """Register a brand. Returns the brand dict."""
    return get_success_data(
        api_client.create_brand(create_brand_payload(**overrides), ADMIN)
    )


def create_product(brand, standard, **overrides):
    """Enroll a product as the owning BrandRep. Returns the product dict (DRAFT)."""
    return get_success_data(
        api_client.create_product(
            create_product_payload(brand["id"], standard["id"], **overrides),
            make_brand_rep_headers(brand["id"]),
        )
    )


def add_ingredient(product_id, brand_id, name="Soy", crop_type="HIGH_RISK",
                   declared_weight_pct=100.00):
    """Add an ingredient as the owning BrandRep. Returns the ingredient dict."""
    return get_success_data(
        api_client.create_ingredient(
            create_ingredient_payload(
                product_id, name=name, crop_type=crop_type,
                declared_weight_pct=declared_weight_pct,
            ),
            make_brand_rep_headers(brand_id),
        )
    )


def add_accepted_affidavit(ingredient_id, brand_id, supplier_name="S",
                           valid_from=_AFF_FROM, valid_until=_AFF_UNTIL):
    """Submit an affidavit and have it reviewed ACCEPTED. Returns the affidavit."""
    aff = get_success_data(
        api_client.create_affidavit(
            create_affidavit_payload(
                ingredient_id, supplier_name=supplier_name,
                valid_from=valid_from, valid_until=valid_until,
            ),
            make_brand_rep_headers(brand_id),
        )
    )
    return get_success_data(
        api_client.review_affidavit(aff["id"], {"decision": "ACCEPTED"}, ADMIN)
    )


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, ADMIN))


# ─── Tier 2/3: product pipeline progression ──────────────────────────────────

def create_product_under_evaluation(
    name="P1", gtin="G-P1", annual_volume_units=100,
    ingredient_specs=({"name": "Soy", "crop_type": "HIGH_RISK",
                       "declared_weight_pct": 100.00},),
    with_affidavits=True, affidavit_valid_until=_AFF_UNTIL,
    brand=None, standard=None,
):
    """
    Create standard (if needed), brand (if needed), product with the given
    ingredient specs, ACCEPTED affidavits for each ingredient (optional), then
    submit + begin-evaluation. Returns a dict with standard, brand, product,
    ingredients.
    """
    standard = standard or create_standard()
    brand = brand or create_brand(name=f"B-{gtin}", contact_email=f"{gtin}@x.com")
    product = create_product(brand, standard, name=name, gtin=gtin,
                             annual_volume_units=annual_volume_units)
    ingredients = []
    for spec in ingredient_specs:
        ing = add_ingredient(product["id"], brand["id"], **spec)
        ingredients.append(ing)
        if with_affidavits:
            add_accepted_affidavit(ing["id"], brand["id"],
                                   valid_until=affidavit_valid_until)
    rep = make_brand_rep_headers(brand["id"])
    get_success_data(api_client.submit_product(product["id"], rep))
    product = get_success_data(api_client.begin_evaluation(product["id"], ADMIN))
    return {
        "standard": standard,
        "brand": brand,
        "product": product,
        "ingredients": ingredients,
    }


def create_plan(product_id, risk_point="INGREDIENT_INTAKE"):
    """Create a sampling plan against the product's current version.
    Returns the plan dict."""
    version = get_product(product_id)["version"]
    return get_success_data(
        api_client.create_sampling_plan(
            create_sampling_plan_payload(
                product_id, version, risk_point=risk_point,
            ),
            ADMIN,
        )
    )


def collect_sample(plan_id, ingredient_id):
    """Collect a sample under a plan. Returns the COLLECTED sample dict."""
    return get_success_data(
        api_client.create_sample(create_sample_payload(plan_id, ingredient_id), LAB_1)
    )


def confirm_sample(plan_id, ingredient_id, result_gmo_pct=0.10):
    """Collect + record + confirm (recorder lab-1, confirmer lab-2).
    Returns the CONFIRMED sample dict."""
    sample = collect_sample(plan_id, ingredient_id)
    get_success_data(
        api_client.record_sample_result(
            sample["id"], create_record_result_payload(result_gmo_pct=result_gmo_pct), LAB_1
        )
    )
    return get_success_data(api_client.confirm_sample(sample["id"], LAB_2))


def create_passed_audit(brand_id, facility_name="F1", auditor_id="aud-1",
                        lots=None, scheduled_date="2026-08-05T00:00:00Z"):
    """Schedule + submit-report + decide PASSED. Returns the PASSED audit."""
    audit = get_success_data(
        api_client.create_facility_audit(
            create_facility_audit_payload(
                brand_id, facility_name=facility_name, auditor_id=auditor_id,
                scheduled_date=scheduled_date,
            ),
            ADMIN,
        )
    )
    get_success_data(
        api_client.submit_audit_report(
            audit["id"],
            create_audit_report_payload(
                lots=lots or [{"lot_code": "L1", "input_qty": 200, "recovered_qty": 190}]
            ),
            build_user_headers(auditor_id, "Auditor"),
        )
    )
    return get_success_data(
        api_client.decide_audit(audit["id"], {"decision": "PASSED"}, ADMIN)
    )


# ─── Tier 5: full verification lifecycle ─────────────────────────────────────

def create_verified_product(name="P1", gtin="G-P1", annual_volume_units=100,
                            ingredient_name="Soy", result_gmo_pct=0.10,
                            affidavit_valid_until="2028-06-01T00:00:00Z"):
    """
    Full chain to VERIFIED: standard + brand + product + one HIGH_RISK 100%
    ingredient + ACCEPTED affidavit + submit + begin-evaluation + INTAKE plan
    (required 1) + one confirmed compliant sample + PASSED audit + decide
    VERIFIED. Returns dict with every artifact.
    """
    ctx = create_product_under_evaluation(
        name=name, gtin=gtin, annual_volume_units=annual_volume_units,
        ingredient_specs=({"name": ingredient_name, "crop_type": "HIGH_RISK",
                           "declared_weight_pct": 100.00},),
        affidavit_valid_until=affidavit_valid_until,
    )
    product = ctx["product"]
    brand = ctx["brand"]
    ingredient = ctx["ingredients"][0]
    plan = create_plan(product["id"], risk_point="INGREDIENT_INTAKE")
    sample = confirm_sample(plan["id"], ingredient["id"], result_gmo_pct=result_gmo_pct)
    audit = create_passed_audit(brand["id"])
    product = get_success_data(
        api_client.decide_product(product["id"], {"decision": "VERIFIED"}, ADMIN)
    )
    licenses = get_success_data(
        api_client.list_licenses(ADMIN, params={"product_id": product["id"]})
    )
    return {
        "standard": ctx["standard"],
        "brand": brand,
        "product": product,
        "ingredient": ingredient,
        "plan": plan,
        "sample": sample,
        "audit": audit,
        "license": licenses[0],
    }


# ─── Enforcement helpers ─────────────────────────────────────────────────────

def open_case(product_id, source="CONSUMER_COMPLAINT", description="d",
              opener_headers=None):
    """Open an enforcement case. Returns the OPENED case dict."""
    return get_success_data(
        api_client.create_enforcement_case(
            create_enforcement_case_payload(
                product_id, source=source, description=description,
            ),
            opener_headers or OFFICER_1,
        )
    )


def substantiate_case(case_id, sanction="WARNING", resolver_headers=None):
    """Resolve a case as SUBSTANTIATED with the given sanction. Returns the case."""
    return get_success_data(
        api_client.resolve_enforcement_case(
            case_id, {"outcome": "SUBSTANTIATED", "sanction": sanction},
            resolver_headers or OFFICER_2,
        )
    )


def set_clock(to_iso8601):
    """Advance the logical clock."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )
