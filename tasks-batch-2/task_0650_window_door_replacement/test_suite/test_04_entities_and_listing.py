"""Entity creation, computed fields, defaults, CRUD, and FK reverse-reachability
listings.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    factories as F,
    fixtures as FX,
    ApiErrorId,
    TEST_USERS,
)

SALES = TEST_USERS["sales_consultant_headers"]
OPS = TEST_USERS["operations_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Entity creation, defaults, computed fields
# ---------------------------------------------------------------------------

def test_create_homeowner_returns_system_fields(api):
    """PRD §2.4: "the `version` field starts at 1 and increases by exactly 1 on
    every mutation."
    PRD §3.1: "A homeowner's `referral_credit_cents` is a derived total ... it
    begins at 0."

    Design: Corner/entities/create_homeowner_success_returns_201_and_system_fields
    """
    resp = api.create_homeowner(F.create_homeowner_payload(full_name="Ada", property_zip="30301"), ADMIN)
    data = validate_success(resp, 201)
    assert data["version"] == 1, data["version"]
    assert data["referral_credit_cents"] == 0, data["referral_credit_cents"]


def test_homeowner_agi_band_defaults_to_standard(api):
    """PRD §3.1: "A homeowner may optionally declare an `agi_band` — one of
    `LOW`, `STANDARD`, or `HIGH` — which defaults to `STANDARD` when omitted."

    Design: Corner/entities/homeowner_agi_band_defaults_to_standard
    """
    # Omit agi_band explicitly.
    payload = {"full_name": "Bo", "email": F.unique_email("bo"), "property_zip": "30301"}
    data = validate_success(api.create_homeowner(payload, ADMIN), 201)
    assert data["agi_band"] == "STANDARD", data["agi_band"]


def test_project_jurisdiction_code_computed_from_zip_west(api):
    """PRD §2.10: "a ZIP whose first digit is `9` maps to `WEST_STRICT`."
    PRD §3.1: "At creation the system reads the owning homeowner's
    `property_zip`, derives and pins `jurisdiction_code` ... and sets the
    project's `status` to `LEAD`."

    Design: Corner/entities/project_jurisdiction_code_computed_from_zip_west
    """
    homeowner = get_success_data(api.create_homeowner(F.create_homeowner_payload(full_name="West", property_zip="94016"), ADMIN))
    proj = validate_success(api.create_project(F.create_project_payload(homeowner["id"]), SALES), 201)
    assert proj["jurisdiction_code"] == "WEST_STRICT", proj["jurisdiction_code"]
    assert proj["status"] == "LEAD", proj["status"]


def test_opening_u_factor_and_energy_qualified_computed(api):
    """PRD §3.2: "From the glass package the system derives the opening's
    `u_factor`: `STANDARD` yields 0.40, `LOWE_DUAL` yields 0.27, and
    `LOWE_TRIPLE` yields 0.20, where a lower figure is better."
    PRD §3.2: "The opening's `energy_qualified` flag is true exactly when its
    `u_factor` is at most 0.30, and it defaults to false."
    PRD §3.2: "this raw amount is then rounded half-up to whole cents exactly
    once, per opening, to produce `unit_price_cents`."

    Design: Corner/entities/opening_u_factor_and_energy_qualified_computed
    """
    homeowner = FX.create_homeowner(api)
    project = FX.create_project_for(api, homeowner["id"])
    cons = get_success_data(api.create_consultation(project["id"], F.create_consultation_payload(project["id"]), SALES))
    # PICTURE 40x40 STANDARD: area 1600/144, raw = (1600/144)*3600 = 40000.0.
    opening = validate_success(api.create_opening(
        project["id"], cons["id"],
        F.create_opening_payload(cons["id"], product_type="PICTURE", width_in=40, height_in=40, glass_package="STANDARD"),
        SALES), 201)
    assert opening["u_factor"] == 0.40, opening["u_factor"]
    assert opening["energy_qualified"] is False, opening["energy_qualified"]
    assert opening["unit_price_cents"] == 40000, opening["unit_price_cents"]


def test_get_project_not_found_returns_404(api):
    """PRD §2.6: "the system validates each path identifier in strict
    left-to-right order, rejecting the request with `ERR_NOT_FOUND` at the first
    identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_project_not_found_returns_404
    """
    resp = api.get_project("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_project_missing_homeowner_id_returns_invalid_request(api):
    """PRD §3.11: "generic request-body validation — required fields present and
    field types, enums, and numeric ranges valid ... is applied to create
    endpoints and reported as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_project_missing_homeowner_id_returns_invalid_request
    """
    resp = api.create_project({}, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_create_opening_negative_width_returns_invalid_request(api):
    """PRD §3.11: "required fields present and field types, enums, and numeric
    ranges valid, such as `width_in` greater than 0 and a `term_months` drawn
    from the allowed set, is applied to create endpoints and reported as
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_opening_negative_width_returns_invalid_request
    """
    homeowner = FX.create_homeowner(api)
    project = FX.create_project_for(api, homeowner["id"])
    cons = get_success_data(api.create_consultation(project["id"], F.create_consultation_payload(project["id"]), SALES))
    resp = api.create_opening(
        project["id"], cons["id"],
        F.create_opening_payload(cons["id"], product_type="CASEMENT", width_in=0, height_in=40, glass_package="STANDARD"),
        SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_create_project_nonexistent_homeowner_returns_reference_not_found(api):
    """PRD §3.11: "foreign-key references carried in a request body — such as
    `homeowner_id`, `consultation_id`, `crew_id`, `opening_id`, and the referrer
    and referred project identifiers — must resolve to existing resources
    (`ERR_REFERENCE_NOT_FOUND`)."

    Design: Corner/entities/create_project_nonexistent_homeowner_returns_reference_not_found
    """
    resp = api.create_project(F.create_project_payload("11111111-1111-1111-1111-111111111111"), SALES)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 422)


def test_list_projects_pagination_envelope_fields_present(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_projects_pagination_envelope_fields_present
    """
    homeowner = FX.create_homeowner(api)
    FX.create_project_for(api, homeowner["id"])
    data, meta = validate_paginated(api.list_projects(ADMIN))
    assert meta["total_count"] >= 1, meta
    assert isinstance(meta["has_more"], bool), meta


# ---------------------------------------------------------------------------
# CRUD update and fetch
# ---------------------------------------------------------------------------

def test_patch_opening_glass_package_recomputes_price(api):
    """PRD §3.2: "The consultant may later revise an opening's `glass_package`,
    which recomputes `u_factor`, `energy_qualified`, and the per-opening price."

    Design: Corner/endpoints/patch_opening_glass_package_recomputes_price
    """
    homeowner = FX.create_homeowner(api)
    project = FX.create_project_for(api, homeowner["id"])
    cons = get_success_data(api.create_consultation(project["id"], F.create_consultation_payload(project["id"]), SALES))
    # CASEMENT 48x72 STANDARD: area 3456/144 = 24 sqft; raw 24*4800 = 115200.
    opening = get_success_data(api.create_opening(
        project["id"], cons["id"],
        F.create_opening_payload(cons["id"], product_type="CASEMENT", width_in=48, height_in=72, glass_package="STANDARD"),
        SALES))
    assert opening["unit_price_cents"] == 115200, opening["unit_price_cents"]
    # Patch to LOWE_TRIPLE: u_factor 0.20, qualified true, raw 24*(4800+1800)=158400.
    patched = validate_success(api.patch_opening(opening["id"], {"glass_package": "LOWE_TRIPLE"}, SALES), 200)
    assert patched["u_factor"] == 0.20, patched["u_factor"]
    assert patched["energy_qualified"] is True, patched["energy_qualified"]
    assert patched["unit_price_cents"] == 158400, patched["unit_price_cents"]


def test_get_single_crew_returns_stored_data(api):
    """PRD §3.7: "registered by an `OperationsCoordinator` or `PlatformAdmin`
    with a display `name`, a `home_jurisdiction` of `WEST_STRICT`,
    `NORTHEAST_STD`, or `CENTRAL_LIGHT`, and a `daily_capacity_openings` value
    that must be at least 1."

    Design: Corner/endpoints/get_single_crew_returns_stored_data
    """
    crew = FX.create_crew(api, name="Crew G", home_jurisdiction="NORTHEAST_STD", daily_capacity_openings=4)
    fetched = validate_success(api.get_crew(crew["id"], OPS), 200)
    assert fetched["daily_capacity_openings"] == 4, fetched["daily_capacity_openings"]
    assert fetched["home_jurisdiction"] == "NORTHEAST_STD", fetched["home_jurisdiction"]


# ---------------------------------------------------------------------------
# FK reverse-reachability listings
# ---------------------------------------------------------------------------

def test_list_manufacture_orders_by_project(api):
    """PRD §3.4: "Hop two auto-creates a `ManufactureOrder` in `QUEUED` status,
    recording its `project_id` and `quote_id`."

    Design: Corner/entities/list_manufacture_orders_by_project_fk_reverse
    """
    base = FX.setup_accepted_quote(api)
    data, _ = validate_paginated(api.list_manufacture(base["project"]["id"], OPS))
    matching = [mo for mo in data if mo["quote_id"] == base["quote"]["id"]]
    assert len(matching) == 1, f"expected exactly one MO with quote_id, got {len(matching)}"


def test_list_install_jobs_by_crew(api):
    """PRD §3.7: "At scheduling the system copies the `opening_count` from the
    accepted quote's consultation `total_opening_count`, and that count is what
    the job consumes against crew capacity."

    Design: Corner/entities/list_install_jobs_by_crew_fk_reverse
    """
    base = FX.setup_scheduled_install(api)
    crew_id = base["crew"]["id"]
    data, _ = validate_paginated(api.list_install_jobs_flat(OPS, params={"crew_id": crew_id}))
    assert any(j["crew_id"] == crew_id for j in data), f"no install job with crew_id {crew_id}"
