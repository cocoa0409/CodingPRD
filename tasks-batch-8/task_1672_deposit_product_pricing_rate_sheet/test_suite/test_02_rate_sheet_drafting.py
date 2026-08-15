"""Rate sheet drafting: defaults, uniqueness, tier structure, rate cap,
OCC-guarded edits, and basic state-machine rejections (PRD §2.7, §2.8, §3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_rate_sheet,
    create_draft_sheet,
    create_product,
    create_rate_sheet_payload,
    single_tier,
    submit_sheet,
    tier,
    validate_error,
    validate_success,
)


def test_rate_sheet_defaults_and_sheet_version_sequence(api, analyst_headers):
    """PRD §2.8: "Rate sheets are versioned per pair: `sheet_version` starts
    at 1 for the first sheet of a pair and increments by one for each
    subsequent sheet created for the same pair."
    PRD §3.1: "The server assigns its `sheet_version` as the next sequence
    number for the pair, and computes `total_projected_balance_cents` as the
    sum of the tiers' `projected_balance_cents`, recomputing it on creation
    and on every subsequent edit."
    PRD §2.8: "An omitted `end_date` defaults to `9999-12-31`, meaning
    open-ended."

    Design: Corner/entities/rate_sheet_defaults_and_sheet_version_sequence
    """
    product = create_product(product_code="DFT")
    tiers = [tier(0, 0, 1_000_000, 100, 2_000_000),
             tier(1, 1_000_000, -1, 150, 3_000_000)]
    resp = api.create_rate_sheet(
        create_rate_sheet_payload(product["id"], market_code="US-WEST", tiers=tiers),
        analyst_headers)
    sheet_west = validate_success(resp, 201)
    assert_rate_sheet(sheet_west)
    assert sheet_west["sheet_version"] == 1
    assert sheet_west["status"] == "DRAFT"
    assert sheet_west["end_date"] == "9999-12-31"
    assert sheet_west["total_projected_balance_cents"] == 5_000_000

    # A different market is a different pair: the sequence restarts at 1.
    resp = api.create_rate_sheet(
        create_rate_sheet_payload(product["id"], market_code="US-EAST",
                                  tiers=single_tier(100)),
        analyst_headers)
    sheet_east = validate_success(resp, 201)
    assert sheet_east["sheet_version"] == 1


def test_second_draft_sheet_for_pair_rejected(api, analyst_headers):
    """PRD §2.8: "Two uniqueness invariants hold per pair at all times: at
    most one sheet in `DRAFT` (a second attempt fails with
    `ERR_DRAFT_SHEET_EXISTS`), and at most one sheet in `EFFECTIVE`
    (activation atomically supersedes the incumbent, so the invariant is never
    violated even momentarily)."
    PRD §2.8: "Rate sheets are versioned per pair: `sheet_version` starts at 1
    for the first sheet of a pair and increments by one for each subsequent
    sheet created for the same pair."

    Design: Corner/validations/second_draft_sheet_for_pair_rejected
    """
    product = create_product(product_code="DR")
    first = create_draft_sheet(product["id"], tiers=single_tier(100))

    resp = api.create_rate_sheet(
        create_rate_sheet_payload(product["id"], effective_date="2026-09-01",
                                  tiers=single_tier(110)),
        analyst_headers)
    validate_error(resp, ApiErrorId.ERR_DRAFT_SHEET_EXISTS, 409)

    # Once the first sheet leaves DRAFT, a new DRAFT is allowed and the
    # per-pair sequence advances.
    submit_sheet(first["id"])
    resp = api.create_rate_sheet(
        create_rate_sheet_payload(product["id"], effective_date="2026-09-01",
                                  tiers=single_tier(110)),
        analyst_headers)
    second = validate_success(resp, 201)
    assert second["sheet_version"] == 2
    assert second["status"] == "DRAFT"


def test_tier_structure_gap_and_bounded_last_tier_rejected(api, analyst_headers):
    """PRD §3.1: "the rows must tile the balance axis contiguously from zero —
    the first lower bound is zero, each tier's lower bound equals the previous
    tier's upper bound, rates ascend without gaps or overlaps, `tier_index`
    values run 0 through n−1, and the final tier is unbounded. Any violation
    is rejected with `ERR_TIER_STRUCTURE_INVALID`."

    Design: Corner/calculations/tier_structure_gap_and_bounded_last_tier_rejected
    """
    product = create_product(product_code="TI")

    gap_tiers = [tier(0, 0, 1_000_000, 100), tier(1, 2_000_000, -1, 150)]
    resp = api.create_rate_sheet(
        create_rate_sheet_payload(product["id"], tiers=gap_tiers), analyst_headers)
    validate_error(resp, ApiErrorId.ERR_TIER_STRUCTURE_INVALID, 422)

    bounded_last = [tier(0, 0, 1_000_000, 100)]
    resp = api.create_rate_sheet(
        create_rate_sheet_payload(product["id"], market_code="US-EAST",
                                  tiers=bounded_last),
        analyst_headers)
    validate_error(resp, ApiErrorId.ERR_TIER_STRUCTURE_INVALID, 422)


def test_tier_rate_above_product_cap_rejected(api, analyst_headers):
    """PRD §3.1: "Independently, every tier's `rate_bp` must be at most the
    product's `rate_cap_bp`, on pain of `ERR_RATE_CAP_EXCEEDED`."

    Design: Corner/calculations/tier_rate_above_product_cap_rejected
    """
    product = create_product(product_code="CAP", rate_cap_bp=500)

    resp = api.create_rate_sheet(
        create_rate_sheet_payload(product["id"], tiers=single_tier(501)),
        analyst_headers)
    validate_error(resp, ApiErrorId.ERR_RATE_CAP_EXCEEDED, 422)

    # A rate exactly at the cap satisfies "at most the cap".
    resp = api.create_rate_sheet(
        create_rate_sheet_payload(product["id"], tiers=single_tier(500)),
        analyst_headers)
    sheet = validate_success(resp, 201)
    assert sheet["status"] == "DRAFT"


def test_patch_draft_sheet_recomputes_projected_total(api, analyst_headers):
    """PRD §3.1: "The server assigns its `sheet_version` as the next sequence
    number for the pair, and computes `total_projected_balance_cents` as the
    sum of the tiers' `projected_balance_cents`, recomputing it on creation
    and on every subsequent edit."
    PRD §3.1: "Every accepted edit bumps the sheet's `version` by one and
    refreshes `updated_at`."

    Design: Corner/endpoints/patch_draft_sheet_recomputes_projected_total
    """
    product = create_product(product_code="PD")
    sheet = create_draft_sheet(product["id"], tiers=single_tier(100, 1_000_000))
    assert sheet["version"] == 1

    new_tiers = [tier(0, 0, 1_000_000, 100, 4_000_000),
                 tier(1, 1_000_000, -1, 150, 6_000_000)]
    resp = api.patch_rate_sheet(
        sheet["id"],
        {"expected_sheet_version": sheet["version"], "margin_floor_bp": 15,
         "tiers": new_tiers},
        analyst_headers)
    patched = validate_success(resp, 200)
    assert patched["version"] == 2
    assert patched["margin_floor_bp"] == 15
    assert patched["total_projected_balance_cents"] == 10_000_000

    # Immediate consistency: a re-read observes the same recomputed total.
    reread = validate_success(api.get_rate_sheet(sheet["id"], analyst_headers))
    assert reread["total_projected_balance_cents"] == 10_000_000


def test_occ_sheet_patch_stale_version_returns_412(api, analyst_headers):
    """PRD §2.7: "Editing a DRAFT rate sheet (`PATCH /rate-sheets/{id}`)
    requires the non-optional field `expected_sheet_version`, carrying the
    sheet `version` the client last observed. If the sheet's current `version`
    has advanced past that value, the edit is rejected with
    `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite sheet edits
    it has not observed."

    Design: Corner/complexity_layers/occ_sheet_patch_stale_version_returns_412
    """
    product = create_product(product_code="OCC1")
    sheet = create_draft_sheet(product["id"], tiers=single_tier(100))
    observed_v1 = sheet["version"]

    resp = api.patch_rate_sheet(
        sheet["id"], {"expected_sheet_version": observed_v1, "margin_floor_bp": 5},
        analyst_headers)
    patched = validate_success(resp, 200)
    assert patched["version"] == observed_v1 + 1

    # Replaying the pre-edit version is stale now.
    resp = api.patch_rate_sheet(
        sheet["id"], {"expected_sheet_version": observed_v1, "margin_floor_bp": 9},
        analyst_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    # The fresh version succeeds and increments again.
    resp = api.patch_rate_sheet(
        sheet["id"], {"expected_sheet_version": patched["version"], "margin_floor_bp": 9},
        analyst_headers)
    repatched = validate_success(resp, 200)
    assert repatched["version"] == patched["version"] + 1
    assert repatched["margin_floor_bp"] == 9


def test_mutations_visible_in_same_response(api, analyst_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.5: "`version` (integer): starts at 1 on creation and increments by
    exactly one on every mutation."
    PRD §3.2: "Submission by a `PricingAnalyst` moves a sheet from `DRAFT` to
    `COMMITTEE_REVIEW` and fires the sheet's fiscal gate."

    Design: Corner/consistency_model/mutations_visible_in_same_response
    """
    product = create_product(product_code="IC")
    sheet = create_draft_sheet(product["id"], tiers=single_tier(100))
    resp = api.submit_rate_sheet(sheet["id"], analyst_headers)
    submitted = validate_success(resp, 200)
    assert submitted["status"] == "COMMITTEE_REVIEW"
    assert submitted["version"] == 2


def test_activate_from_draft_returns_sheet_invalid_state(api, analyst_headers):
    """PRD §3.2: "Activation by a `PricingAnalyst` moves `SCHEDULED` to
    `EFFECTIVE` and is the system's serialization point — the moment pricing
    truth changes for an entire product–market pair."
    PRD §2.10: "From-state validity: the target resource is in a state from
    which the requested transition exists — sheets surface
    `ERR_SHEET_INVALID_STATE`, offers `ERR_PROMO_INVALID_STATE`, exception
    requests `ERR_EXCEPTION_INVALID_STATE`, accounts
    `ERR_ACCOUNT_INVALID_STATE`, migration batches
    `ERR_MIGRATION_INVALID_STATE`, enrollments `ERR_ENROLLMENT_INVALID_STATE`,
    scans `ERR_SCAN_INVALID_STATE`, deployments `ERR_DEPLOYMENT_INVALID_STATE`,
    and notice re-resolution `ERR_NOTICE_ALREADY_RESOLVED` (all 409)."

    Design: Corner/state_machines/activate_from_draft_returns_sheet_invalid_state
    """
    product = create_product(product_code="IV1")
    sheet = create_draft_sheet(product["id"], effective_date="2026-08-01",
                               tiers=single_tier(100))
    resp = api.activate_rate_sheet(sheet["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_SHEET_INVALID_STATE, 409)

    reread = validate_success(api.get_rate_sheet(sheet["id"], analyst_headers))
    assert reread["status"] == "DRAFT"


def test_double_submit_returns_sheet_invalid_state(api, analyst_headers):
    """PRD §3.2: "Submission by a `PricingAnalyst` moves a sheet from `DRAFT`
    to `COMMITTEE_REVIEW` and fires the sheet's fiscal gate."
    PRD §2.10: "From-state validity: the target resource is in a state from
    which the requested transition exists — sheets surface
    `ERR_SHEET_INVALID_STATE`, offers `ERR_PROMO_INVALID_STATE`, exception
    requests `ERR_EXCEPTION_INVALID_STATE`, accounts
    `ERR_ACCOUNT_INVALID_STATE`, migration batches
    `ERR_MIGRATION_INVALID_STATE`, enrollments `ERR_ENROLLMENT_INVALID_STATE`,
    scans `ERR_SCAN_INVALID_STATE`, deployments `ERR_DEPLOYMENT_INVALID_STATE`,
    and notice re-resolution `ERR_NOTICE_ALREADY_RESOLVED` (all 409)."

    Design: Corner/state_machines/double_submit_returns_sheet_invalid_state
    """
    product = create_product(product_code="IV2")
    sheet = create_draft_sheet(product["id"], tiers=single_tier(100))
    submit_sheet(sheet["id"])
    resp = api.submit_rate_sheet(sheet["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_SHEET_INVALID_STATE, 409)


def test_review_decision_on_retired_sheet_returns_invalid_state(api, committee_headers):
    """PRD §3.2: "A decision attempted on a sheet in any other state is
    rejected with `ERR_SHEET_INVALID_STATE`."
    PRD §3.2: "`RETIRED` is terminal for every path into it."

    Design: Corner/state_machines/review_decision_on_retired_sheet_returns_invalid_state
    """
    product = create_product(product_code="IV3")
    sheet = create_draft_sheet(product["id"], tiers=single_tier(100))

    # DRAFT -> RETIRED is a valid committee action with no accounts attached.
    retired = validate_success(api.retire_rate_sheet(sheet["id"], committee_headers))
    assert retired["status"] == "RETIRED"

    resp = api.review_decision_rate_sheet(sheet["id"], {"decision": "APPROVE"},
                                          committee_headers)
    validate_error(resp, ApiErrorId.ERR_SHEET_INVALID_STATE, 409)
