"""Case filing, fee tiering, and the provisional/final administrative fee."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, make_admin_headers,
    create_case_payload,
    setup_issued_award, setup_hearing_case,
    create_award_payload,
)
from test_helpers.fixtures import ADMIN, get_case

ADM = make_admin_headers()


# ---------------------------------------------------------------------------
# Corner: entity creation / retrieval / listing / defaults / computed / system
# ---------------------------------------------------------------------------

def test_create_case_returns_201_with_computed_fee_fields(api):
    """PRD 3.1: "a `claim_amount_cents` below 1,000,000 cents is `TIER_1`". PRD 3.1:
    "a base administrative amount is looked up by tier — 75,000 cents for `TIER_1`".
    PRD 3.1: "A freshly filed case enters `FILED` status." PRD 3.1: "its
    `deposit_balance_cents` is 0."

    Design: Corner/entities/create_case_returns_201_with_computed_fee_fields
    """
    resp = api.create_case(create_case_payload(
        case_type="ARBITRATION", title="New Case", claim_amount_cents=500_000,
        panel_size=1), ADM)
    data = validate_success(resp, 201)
    assert data["status"] == "FILED"
    assert data["fee_tier"] == "TIER_1"
    assert data["filing_fee_cents"] == 75_000
    assert data["deposit_balance_cents"] == 0


def test_get_case_returns_stored_entity(api):
    """PRD 3.1: "the amount in controversy as `claim_amount_cents`". PRD 2.2: "The
    `data` field contains the resource object or an array of resource objects."

    Design: Corner/entities/get_case_returns_stored_entity
    """
    created = validate_success(api.create_case(create_case_payload(
        title="Readback", claim_amount_cents=2_000_000, panel_size=1), ADM), 201)
    data = validate_success(api.get_case(created["id"], ADM), 200)
    assert data["title"] == "Readback"
    assert data["claim_amount_cents"] == 2_000_000


def test_list_cases_paginated_returns_envelope(api):
    """PRD 2.3: "The `limit` parameter caps the number of items returned". PRD 2.3:
    "Each paginated response echoes `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/entities/list_cases_paginated_returns_envelope
    """
    validate_success(api.create_case(create_case_payload(title="One"), ADM), 201)
    validate_success(api.create_case(create_case_payload(title="Two"), ADM), 201)
    data, meta = validate_paginated(api.list_cases(ADM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_cases_filtered_by_status(api):
    """PRD 4 (endpoint): "List cases (paginated; optional status filter)". PRD 3.1:
    "the case may be abandoned from `FILED` to `WITHDRAWN` with no precondition."

    Design: Corner/entities/list_cases_filtered_by_status
    """
    validate_success(api.create_case(create_case_payload(title="Stays"), ADM), 201)
    gone = validate_success(api.create_case(create_case_payload(title="Gone"), ADM), 201)
    validate_success(api.transition_case(gone["id"], {"to_status": "WITHDRAWN"}, ADM), 200)
    data, _ = validate_paginated(api.list_cases(ADM, params={"status": "WITHDRAWN"}))
    assert all(item["status"] == "WITHDRAWN" for item in data)
    assert any(item["id"] == gone["id"] for item in data)


def test_list_cases_pagination_limit_zero_rejected(api):
    """PRD 2.3: "The `limit` parameter caps the number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100." PRD 2.3: "A `limit` or `offset` outside
    its allowed bounds is rejected with `ERR_PAGINATION_INVALID`."

    Design: Corner/validations/list_cases_pagination_limit_zero_rejected
    """
    resp = api.list_cases(ADM, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)


def test_get_case_nonexistent_id_returns_not_found(api):
    """PRD 2.8: "the first one that does not resolve produces `ERR_NOT_FOUND` (404)
    immediately".

    Design: Corner/entities/get_case_nonexistent_id_returns_not_found
    """
    resp = api.get_case("00000000-0000-0000-0000-000000000000", ADM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_case_missing_required_claim_amount_rejected(api):
    """PRD 2.8: "Structural validation — required fields present, types correct ... a
    violation yields `ERR_VALIDATION` (400)." PRD 3.1: "the amount in controversy as
    `claim_amount_cents` (an integer of at least zero)".

    Design: Corner/entities/create_case_missing_required_claim_amount_rejected
    """
    resp = api.create_case({"case_type": "ARBITRATION", "title": "NoClaim", "panel_size": 1}, ADM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_case_default_panel_and_strikes_applied(api):
    """PRD 3.1: "The `panel_size` is the number of neutrals who will decide the matter
    and must be either 1 or 3, defaulting to 1". PRD 3.1: "The `strikes_per_party` is
    the strike allowance each party may spend against the candidate list, an integer
    of at least zero, defaulting to 2."

    Design: Corner/entities/create_case_default_panel_and_strikes_applied
    """
    data = validate_success(api.create_case(
        {"case_type": "ARBITRATION", "title": "Defaults", "claim_amount_cents": 500_000}, ADM), 201)
    assert data["panel_size"] == 1
    assert data["strikes_per_party"] == 2


def test_create_case_client_fee_tier_input_ignored(api):
    """PRD 3.1: "the case's `fee_tier` is selected from the amount in controversy by
    threshold: a `claim_amount_cents` below 1,000,000 cents is `TIER_1`".

    Design: Corner/entities/create_case_client_fee_tier_input_ignored
    """
    data = validate_success(api.create_case(create_case_payload(
        title="Ignore", claim_amount_cents=500_000, panel_size=1, fee_tier="TIER_4"), ADM), 201)
    assert data["fee_tier"] == "TIER_1"


def test_create_case_system_status_input_ignored(api):
    """PRD 3.1: "A freshly filed case enters `FILED` status."

    Design: Corner/entities/create_case_system_status_and_version_input_ignored
    """
    data = validate_success(api.create_case(create_case_payload(
        title="Sys", claim_amount_cents=500_000, panel_size=1, status="CLOSED"), ADM), 201)
    assert data["status"] == "FILED"


def test_create_case_invalid_case_type_enum_rejected(api):
    """PRD 2.8: "An enum value that falls outside its declared set is reported as
    `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/create_case_invalid_case_type_enum_rejected
    """
    resp = api.create_case(create_case_payload(
        case_type="LITIGATION", title="BadEnum", claim_amount_cents=500_000, panel_size=1), ADM)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_create_case_panel_size_two_rejected(api):
    """PRD 2.8: "a case's `panel_size` equal to 1 or 3 ... a violation yields
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_case_panel_size_two_rejected
    """
    resp = api.create_case(create_case_payload(
        title="Panel2", claim_amount_cents=500_000, panel_size=2), ADM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_mediation_panel_three_rejected(api):
    """PRD 2.8: "a `MEDIATION` case restricted to a `panel_size` of 1; a violation
    yields `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_mediation_panel_three_rejected
    """
    resp = api.create_case(create_case_payload(
        case_type="MEDIATION", title="MedPanel3", claim_amount_cents=500_000, panel_size=3), ADM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Corner: filing-fee tier boundaries and multipliers
# ---------------------------------------------------------------------------

def test_filing_fee_below_tier2_floor_is_tier1(api):
    """PRD 3.1: "a `claim_amount_cents` below 1,000,000 cents is `TIER_1`". PRD 3.1: "a
    base administrative amount is looked up by tier — 75,000 cents for `TIER_1`".

    Design: Corner/calculations/filing_fee_below_tier2_floor_is_tier1
    """
    data = validate_success(api.create_case(create_case_payload(
        title="T1edge", claim_amount_cents=999_999, panel_size=1), ADM), 201)
    assert data["fee_tier"] == "TIER_1"
    assert data["filing_fee_cents"] == 75_000


def test_filing_fee_tier2_floor_inclusive(api):
    """PRD 3.1: "from 1,000,000 up to but not including 7,500,000 cents it is `TIER_2`".
    PRD 3.1: "175,000 cents for `TIER_2`". PRD 3.1: "Each tier floor is inclusive of
    its lower bound."

    Design: Corner/calculations/filing_fee_tier2_floor_inclusive
    """
    data = validate_success(api.create_case(create_case_payload(
        title="T2floor", claim_amount_cents=1_000_000, panel_size=1), ADM), 201)
    assert data["fee_tier"] == "TIER_2"
    assert data["filing_fee_cents"] == 175_000


def test_filing_fee_tier4_floor_inclusive(api):
    """PRD 3.1: "at 50,000,000 cents or above it is `TIER_4`". PRD 3.1: "700,000 cents
    for `TIER_4`". PRD 3.1: "Each tier floor is inclusive of its lower bound."

    Design: Corner/calculations/filing_fee_tier4_floor_inclusive
    """
    data = validate_success(api.create_case(create_case_payload(
        title="T4floor", claim_amount_cents=50_000_000, panel_size=1), ADM), 201)
    assert data["fee_tier"] == "TIER_4"
    assert data["filing_fee_cents"] == 700_000


def test_filing_fee_mediation_half_multiplier(api):
    """PRD 3.1: "multiplied by a case-type multiplier of 1.0 for an `ARBITRATION` case
    or 0.5 for a `MEDIATION` case". PRD 3.1: "75,000 cents for `TIER_1`".

    Design: Corner/calculations/filing_fee_mediation_half_multiplier
    """
    data = validate_success(api.create_case(create_case_payload(
        case_type="MEDIATION", title="MedFee", claim_amount_cents=500_000, panel_size=1), ADM), 201)
    assert data["fee_tier"] == "TIER_1"
    assert data["filing_fee_cents"] == 37_500


# ---------------------------------------------------------------------------
# Difficulty: combinatorial filing-fee formula (tier x case_type x panel)
# ---------------------------------------------------------------------------

def test_filing_fee_tier3_panel3_multiplier(api):
    """PRD 3.1: "from 7,500,000 up to but not including 50,000,000 cents it is `TIER_3`".
    PRD 3.1: "400,000 cents for `TIER_3` — then multiplied by a case-type multiplier of
    1.0 for an `ARBITRATION` case ... and by a panel multiplier of 1.5 when `panel_size`
    is 3 or 1.0 otherwise. Both multipliers are applied to the base and the single
    product is rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/filing_fee_tier_times_panel_multiplier
    """
    data = validate_success(api.create_case(create_case_payload(
        case_type="ARBITRATION", title="Panel3", claim_amount_cents=10_000_000, panel_size=3), ADM), 201)
    assert data["fee_tier"] == "TIER_3"
    assert data["filing_fee_cents"] == 600_000


def test_filing_fee_panel1_isolates_multiplier(api):
    """PRD 3.1: "400,000 cents for `TIER_3` — then multiplied by a case-type multiplier
    of 1.0 for an `ARBITRATION` case ... and by a panel multiplier of 1.5 when
    `panel_size` is 3 or 1.0 otherwise."

    Design: Difficulty/combinatorial_formula/filing_fee_tier_times_panel_multiplier
    """
    data = validate_success(api.create_case(create_case_payload(
        case_type="ARBITRATION", title="Panel1", claim_amount_cents=10_000_000, panel_size=1), ADM), 201)
    assert data["fee_tier"] == "TIER_3"
    assert data["filing_fee_cents"] == 400_000


# ---------------------------------------------------------------------------
# Difficulty: TIER_3 floor is inclusive (boundary precision, X and X-1)
# ---------------------------------------------------------------------------

def test_filing_fee_tier3_floor_is_inclusive(api):
    """PRD 3.1: "from 7,500,000 up to but not including 50,000,000 cents it is `TIER_3`".
    PRD 3.1: "Each tier floor is inclusive of its lower bound." PRD 3.1: "400,000 cents
    for `TIER_3`".

    Design: Difficulty/boundary_precision_check/filing_fee_tier3_floor_is_inclusive
    """
    data = validate_success(api.create_case(create_case_payload(
        title="Boundary", claim_amount_cents=7_500_000, panel_size=1), ADM), 201)
    assert data["fee_tier"] == "TIER_3"
    assert data["filing_fee_cents"] == 400_000


def test_filing_fee_one_below_tier3_floor_is_tier2(api):
    """PRD 3.1: "from 1,000,000 up to but not including 7,500,000 cents it is `TIER_2`".
    PRD 3.1: "175,000 cents for `TIER_2`". PRD 3.1: "Each tier floor is inclusive of its
    lower bound."

    Design: Difficulty/boundary_precision_check/filing_fee_tier3_floor_is_inclusive
    """
    data = validate_success(api.create_case(create_case_payload(
        title="BoundaryLow", claim_amount_cents=7_499_999, panel_size=1), ADM), 201)
    assert data["fee_tier"] == "TIER_2"
    assert data["filing_fee_cents"] == 175_000


# ---------------------------------------------------------------------------
# Difficulty: provisional filing fee vs final administrative fee (dual variant)
# ---------------------------------------------------------------------------

def test_filing_fee_and_final_admin_fee_values(api):
    """PRD 3.1: "the provisional `filing_fee_cents` is computed from that tier". PRD 3.9:
    "That bubble-up recomputes the case's `final_admin_fee_cents` from the awarded amount".
    PRD 3.9: "the tier is selected from the awarded `award_amount_cents` rather than the
    claimed amount".

    Design: Difficulty/dual_variant_calc/filing_fee_provisional_vs_final_admin_fee
    """
    ctx = setup_issued_award(api, claim_amount_cents=10_000_000, award_amount_cents=500_000)
    case = get_case(api, ctx["case"]["id"])
    assert case["filing_fee_cents"] == 400_000
    assert case["final_admin_fee_cents"] == 75_000


def test_filing_and_final_admin_fee_diverge(api):
    """PRD 3.9: "Because the tier is keyed on the award rather than the claim,
    `final_admin_fee_cents` diverges from `filing_fee_cents` whenever the award falls in
    a different tier than the claim."

    Design: Difficulty/dual_variant_calc/filing_fee_provisional_vs_final_admin_fee
    """
    ctx = setup_issued_award(api, claim_amount_cents=10_000_000, award_amount_cents=500_000)
    case = get_case(api, ctx["case"]["id"])
    assert case["filing_fee_cents"] != case["final_admin_fee_cents"]
