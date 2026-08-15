"""Optimistic concurrency (expected-version gates), authentication cascade
head, and the scoped uniqueness rules."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_version_incremented,
    create_active_client,
    create_client_payload,
    create_coordinator,
    create_draft_assessment,
    create_fund,
    create_item,
    create_pantry_staff,
    create_reviewer,
    create_shelter_coordinator,
    create_submitted_grant,
    register_client,
    submit_assessment,
    validate_error,
    validate_success,
    verify_assessment,
)

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["hub_admin_headers"]


def test_missing_headers_returns_401_before_any_other_check(api):
    """PRD §2.6: "1. **Authentication** — header presence and identity
    resolution per §2.1; failures yield `ERR_UNAUTHENTICATED`." (step 1 of the
    cascade, ahead of path existence at step 3)
    PRD §2.1: "A request with a missing or unknown `X-User-Role`, a missing
    `X-User-ID` where the role requires one, or an entity-backed identity that
    fails to resolve ... is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_headers_returns_401_before_any_other_check
    """
    res = api.get_client(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_occ_assessment_verify_stale_client_version_rejected(api):
    """PRD §2.8: "**Assessment verification** requires
    `expected_client_version` carrying the client's current `version`. A
    successful verification legitimately supersedes the client's prior
    verified assessment and advances the client's `version` by one, so a
    verification carrying an older expected version is operating on a client
    snapshot the caller has not re-read and is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "Any other `VERIFIED` assessment of the same client is
    automatically superseded to `SUPERSEDED` ..."

    Design: Corner/complexity_layers/occ_assessment_verify_stale_client_version_rejected
    """
    _, coord = create_coordinator()
    # Capture the version BEFORE the first verification: the first verify
    # advances the client's version by one (PRD §2.8), leaving this snapshot
    # genuinely stale for the second verification below.
    client = register_client(**create_client_payload(alias_name="occ"))
    stale_version = client["version"]
    a1 = create_draft_assessment(client["id"], coord)
    submit_assessment(client["id"], a1["id"], coord)
    verify_assessment(
        client["id"], a1["id"], coord, expected_client_version=stale_version
    )
    a2 = create_draft_assessment(
        client["id"], coord,
        household_size=2, monthly_income_cents=90000, housing_status="COST_BURDENED",
        dependents_under_18=1, receives_snap=False, receives_childcare_subsidy=False,
        food_insecurity_score=2, consent_confidential=True,
    )
    submit_assessment(client["id"], a2["id"], coord)

    res = api.verify_assessment(
        client["id"], a2["id"], {"expected_client_version": stale_version}, coord
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    current = validate_success(api.get_client(client["id"], coord), 200)
    verified = validate_success(
        api.verify_assessment(
            client["id"], a2["id"],
            {"expected_client_version": current["version"]}, coord,
        ),
        200,
    )
    assert verified["status"] == "VERIFIED"
    a1_after = validate_success(api.get_assessment(a1["id"], coord), 200)
    assert a1_after["status"] == "SUPERSEDED"


def test_occ_pantry_item_patch_stale_version_rejected(api):
    """PRD §2.8: "**Pantry-item configuration updates** require
    `expected_item_version` carrying the item's current `version`. Restocks,
    checkouts, and void-restores legitimately advance the item's `version`
    between the caller's read and the write; a configuration update carrying a
    stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_pantry_item_patch_stale_version_rejected
    """
    _, pantry = create_pantry_staff()
    item = create_item("OCC Beans", point_cost=10, quantity_on_hand=4,
                       reorder_threshold=1, per_visit_limit=2)
    stale_version = item["version"]
    restocked = validate_success(
        api.restock_pantry_item(item["id"], {"quantity": 6}, pantry), 200
    )

    res = api.patch_pantry_item(
        item["id"],
        {"per_visit_limit": 3, "expected_item_version": stale_version},
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    patched = validate_success(
        api.patch_pantry_item(
            item["id"],
            {"per_visit_limit": 3, "expected_item_version": restocked["version"]},
            ADMIN,
        ),
        200,
    )
    assert patched["per_visit_limit"] == 3
    assert_version_incremented(patched["version"], restocked["version"])
    assert patched["quantity_on_hand"] == 10, "config PATCH never touches stock"


def test_occ_grant_approve_stale_fund_version_rejected(api):
    """PRD §2.8: "**Grant approval** requires `expected_fund_version` carrying
    the fund's current `version`. Any approval, disbursement, or approval
    expiry on the same fund legitimately moves `committed_cents` and advances
    the fund's `version`, so an approval carrying a stale value would size an
    award off a remaining-basis snapshot the caller no longer holds and is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_grant_approve_stale_fund_version_rejected
    """
    _, coord = create_coordinator()
    _, reviewer = create_reviewer()
    client, _, _ = create_active_client(coord, client_overrides={"alias_name": "of"})
    fund = create_fund("FY26-occ", allocated_cents=500000)
    stale_fund_version = fund["version"]

    g1 = create_submitted_grant(
        client, fund, category="RENT", requested_cents=30000,
        hardship_statement="one",
    )
    validate_success(api.begin_review(g1["id"], reviewer), 200)
    g2 = create_submitted_grant(
        client, fund, category="FOOD", requested_cents=30000,
        hardship_statement="two",
    )
    validate_success(api.begin_review(g2["id"], reviewer), 200)

    validate_success(
        api.approve_grant(g1["id"], {"expected_fund_version": stale_fund_version},
                          reviewer),
        200,
    )
    res = api.approve_grant(g2["id"], {"expected_fund_version": stale_fund_version},
                            reviewer)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    fund_now = validate_success(api.get_grant_fund(fund["id"], reviewer), 200)
    approved = validate_success(
        api.approve_grant(g2["id"], {"expected_fund_version": fund_now["version"]},
                          reviewer),
        200,
    )
    assert approved["status"] == "APPROVED"
    fund_end = validate_success(api.get_grant_fund(fund["id"], reviewer), 200)
    assert fund_end["committed_cents"] == 60000


def test_duplicate_creation_errors_batch(api):
    """PRD §3.6: "a `bed_label` unique within that site (duplicates are
    `ERR_DUPLICATE_BED_LABEL`)".
    PRD §3.7: "an `agency_name` that must be unique (duplicates are
    `ERR_DUPLICATE_AGENCY`)".
    PRD §3.5: "the pair of `fund_name` and `fiscal_year` must be unique, with
    duplicates rejected as `ERR_DUPLICATE_FUND`."
    PRD §3.3: "The `item_name` must be unique among items that are not
    discontinued — a name colliding with an `ACTIVE` item is rejected with
    `ERR_DUPLICATE_ITEM` ..."

    Design: Corner/errors/duplicate_creation_errors_batch
    """
    _, shelter = create_shelter_coordinator()
    create_item("DupItem", category="HYGIENE", point_cost=2, quantity_on_hand=1,
                reorder_threshold=0, per_visit_limit=1)
    validate_success(
        api.create_shelter_bed({"shelter_site": "Haven", "bed_label": "D1"}, shelter),
        201,
    )
    validate_success(
        api.create_partner_agency(
            {"agency_name": "Dup Agency", "service_categories": ["LEGAL_AID"],
             "weekly_capacity": 3},
            ADMIN,
        ),
        201,
    )
    validate_success(
        api.create_grant_fund(
            {"fund_name": "DupFund", "fiscal_year": 2026, "allocated_cents": 100000},
            ADMIN,
        ),
        201,
    )

    res = api.create_shelter_bed({"shelter_site": "Haven", "bed_label": "D1"}, shelter)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_BED_LABEL, expected_status=409)

    res = api.create_partner_agency(
        {"agency_name": "Dup Agency", "service_categories": ["MENTAL_HEALTH"],
         "weekly_capacity": 2},
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_AGENCY, expected_status=409)

    res = api.create_grant_fund(
        {"fund_name": "DupFund", "fiscal_year": 2026, "allocated_cents": 200000},
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_FUND, expected_status=409)

    res = api.create_pantry_item(
        {"item_name": "DupItem", "category": "SHELF_STABLE", "point_cost": 3,
         "quantity_on_hand": 5, "reorder_threshold": 1, "per_visit_limit": 2},
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ITEM, expected_status=409)
