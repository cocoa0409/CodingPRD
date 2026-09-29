"""Damage claims: the two settlement variants, the denial-appeal-reinvestigation
cycle, the loss write-off cascade, and the filing and adjudication guards."""
from test_helpers import (
    CLAIM,
    TEST_USERS,
    ApiErrorId,
    adjudicate_claim,
    appeal_claim,
    assert_damage_claim,
    assert_exhibit_asset,
    check_in_crate,
    create_damage_claim_payload,
    file_claim,
    get_asset,
    get_claim,
    get_crate,
    get_refurb,
    get_warehouse,
    make_exhibitor_headers,
    open_investigation,
    open_refurb,
    receive_shipment,
    register_asset,
    register_crate,
    setup_claim_under_investigation,
    setup_show_ground,
    validate_error,
    validate_paginated,
    validate_success,
)

ADJUSTER = TEST_USERS["claims_adjuster_headers"]           # X-User-ID "adj-1"
ADJUSTER_ALT = TEST_USERS["claims_adjuster_alt_headers"]   # X-User-ID "adj-2"

LIST_VALUE_CENTS = 1500000
DECLARED_VALUE_CENTS = 900000
CRATE_WEIGHT_LBS = 1250
INCIDENT_AT = "2026-08-09T12:00:00Z"
FREIGHT_INCIDENT_AT = "2026-09-09T12:00:00Z"


# ---------------------------------------------------------------------------
# The two settlement variants on byte-identical inputs
# ---------------------------------------------------------------------------

# Two identical grade-B assets worth 1500000 cents, each packed in its own
# 1250 lb wood crate, both received on one ADVANCE_WAREHOUSE receipt that carries
# declared-value coverage, and one 900000 cent DAMAGE claim per asset already
# UNDER_INVESTIGATION. Two claims are built so that each one is adjudicated
# exactly once and the variants can be compared on identical inputs.
def _two_claims_on_a_covered_shipment():
    ground = setup_show_ground(with_warehouse=True)
    exhibitor_id = ground["exhibitor"]["id"]
    assets = [register_asset(exhibitor_id, condition_grade="B",
                             list_value_cents=LIST_VALUE_CENTS)
              for _ in range(2)]
    crates = [register_crate(exhibitor_id, crate_label=label,
                             weight_lbs=CRATE_WEIGHT_LBS, asset_id=asset["id"])
              for label, asset in zip(("ACME-C1", "ACME-C2"), assets)]
    shipment = receive_shipment(ground["show"]["id"], exhibitor_id,
                                [crate["id"] for crate in crates],
                                warehouse_id=ground["warehouse"]["id"],
                                declared_value_coverage=True)
    claims = []
    for asset, crate in zip(assets, crates):
        filed = file_claim(exhibitor_id, asset["id"], claim_type="DAMAGE",
                           declared_value_cents=DECLARED_VALUE_CENTS,
                           incident_at=FREIGHT_INCIDENT_AT, crate_id=crate["id"],
                           shipment_id=shipment["id"])
        claims.append(open_investigation(filed["id"]))
    ground["assets"] = assets
    ground["crates"] = crates
    ground["shipment"] = shipment
    ground["claims"] = claims
    return ground


def test_declared_value_variant_settles_at_depreciated_list_value_less_deductible():
    """PRD: "The lesser of the claim's `declared_value_cents` and the asset's
    `list_value_cents` is multiplied by one minus that depreciation fraction and
    rounded half up; a flat deductible of 25000 cents is then subtracted from the
    rounded figure; and the result is floored at zero rather than being allowed to
    go negative."
    PRD: "Under it, a depreciation fraction is read from the asset's
    `condition_grade`: grade `A` depreciates nothing, grade `B` depreciates ten
    percent, grade `C` twenty-five percent and grade `D` forty percent."
    PRD: "The deductible is subtracted after the rounding, never before it."

    Design: Difficulty/dual_variant_calc/claim_tariff_vs_declared_value_divergence
    """
    ground = _two_claims_on_a_covered_shipment()
    claim = adjudicate_claim(ground["claims"][0]["id"], "APPROVE",
                             coverage_basis="DECLARED_VALUE", headers=ADJUSTER)
    assert_damage_claim(claim)
    assert claim["status"] == "APPROVED", \
        f"An approved claim moves to APPROVED, got {claim['status']}"
    assert claim["coverage_basis"] == "DECLARED_VALUE", \
        f"The selected variant is recorded on the claim, got {claim['coverage_basis']}"
    persisted = get_claim(claim["id"])
    assert persisted["coverage_basis"] == "DECLARED_VALUE", \
        "The declared-value basis must survive the read back"
    assert persisted["settlement_cents"] == 785000, (
        "A 900000 cent declared value on a grade-B asset depreciates ten percent to "
        f"810000 and loses the {CLAIM['DECLARED_VALUE_DEDUCTIBLE_CENTS']} cent "
        f"deductible, settling at 785000, got {persisted['settlement_cents']}")


def test_tariff_liability_default_caps_settlement_at_the_cited_crate_weight():
    """PRD: "`settlement_cents` is then the smallest of three figures: the claim's
    `declared_value_cents`; the weight basis multiplied by 30 cents per pound and
    rounded half up; and a flat per-claim ceiling of 5000000 cents."
    PRD: "Its weight basis is the cited crate's `weight_lbs` when `crate_id` is
    non-null, and otherwise the asset's `shipping_weight_lbs`; weight is never
    summed across crates, only the single cited crate counts."
    PRD: "The **tariff liability** variant is the default and is the only one
    available when the cited shipment did not carry declared-value coverage."

    Design: Difficulty/dual_variant_calc/claim_tariff_vs_declared_value_divergence
    """
    ground = _two_claims_on_a_covered_shipment()
    claim = adjudicate_claim(ground["claims"][1]["id"], "APPROVE", headers=ADJUSTER)
    assert_damage_claim(claim)
    assert claim["status"] == "APPROVED", \
        f"An approved claim moves to APPROVED, got {claim['status']}"
    persisted = get_claim(claim["id"])
    assert persisted["coverage_basis"] == "TARIFF_LIABILITY", (
        "Adjudicating without a coverage_basis leaves the tariff default, got "
        f"{persisted['coverage_basis']}")
    assert persisted["settlement_cents"] == 37500, (
        f"A 1250 lb crate at {CLAIM['TARIFF_CENTS_PER_LB']} cents per pound caps "
        f"liability at 37500 cents, got {persisted['settlement_cents']}")


def test_identical_claims_diverge_between_the_two_settlement_variants():
    """PRD: "The weight cap bites hard — a 1250-pound crate caps liability at 37500
    cents no matter how valuable the property inside it was."
    PRD: "The lesser of the claim's `declared_value_cents` and the asset's
    `list_value_cents` is multiplied by one minus that depreciation fraction and
    rounded half up; a flat deductible of 25000 cents is then subtracted from the
    rounded figure; and the result is floored at zero rather than being allowed to
    go negative."
    PRD: "When `claim_type` is `DAMAGE`, the linked asset's `condition_grade` is
    downgraded by exactly one step along `A` to `B` to `C` to `D`, and a grade
    already at `D` stays at `D`."

    Design: Difficulty/dual_variant_calc/claim_tariff_vs_declared_value_divergence
    """
    ground = _two_claims_on_a_covered_shipment()
    value_claim = adjudicate_claim(ground["claims"][0]["id"], "APPROVE",
                                   coverage_basis="DECLARED_VALUE", headers=ADJUSTER)
    tariff_claim = adjudicate_claim(ground["claims"][1]["id"], "APPROVE",
                                    headers=ADJUSTER)
    assert value_claim["settlement_cents"] == 785000, (
        "The declared-value arm settles at 785000 cents, got "
        f"{value_claim['settlement_cents']}")
    assert tariff_claim["settlement_cents"] == 37500, (
        f"The tariff arm settles at 37500 cents, got {tariff_claim['settlement_cents']}")
    assert value_claim["settlement_cents"] > tariff_claim["settlement_cents"], \
        "Identical inputs must still diverge: coverage is worth more than the tariff"
    for asset_row in ground["assets"]:
        asset = get_asset(asset_row["id"])
        assert_exhibit_asset(asset)
        assert asset["condition_grade"] == "C", (
            "An approved DAMAGE claim downgrades a grade-B asset one step to C, got "
            f"{asset['condition_grade']}")


# ---------------------------------------------------------------------------
# Denial, appeal and re-adjudication
# ---------------------------------------------------------------------------

# A grade-A asset worth 1500000 cents packed in a 1250 lb crate, with a 900000
# cent DAMAGE claim filed by the exhibitor, investigated and then DENIED by adj-1.
def _denied_claim():
    ground = setup_claim_under_investigation(
        claim_overrides={"declared_value_cents": DECLARED_VALUE_CENTS,
                         "incident_at": INCIDENT_AT},
        asset_overrides={"list_value_cents": LIST_VALUE_CENTS},
        crate_weight_lbs=CRATE_WEIGHT_LBS)
    ground["claim"] = adjudicate_claim(ground["claim"]["id"], "DENY",
                                       note="Insufficient photographic evidence",
                                       headers=ADJUSTER)
    return ground


def test_denial_records_the_adjudicator_and_the_appeal_clears_it():
    """PRD: "A `DENY` moves the claim `UNDER_INVESTIGATION → DENIED` and leaves
    `settlement_cents` null."
    PRD: "Either decision requires the acting `X-User-ID` to differ from the claim's
    `filed_by_user_id`, and either decision records that operator as
    `adjudicated_by_user_id`."
    PRD: "The appeal moves the claim `DENIED → UNDER_INVESTIGATION`, increases
    `appeal_count` by one, and clears `adjudicated_by_user_id` back to null so that
    the next adjudication re-runs the segregation-of-duties check against whoever
    filed."

    Design: Difficulty/non_linear_state_machine/damage_claim_denial_appeal_reinvestigation_cycle
    """
    ground = _denied_claim()
    denied = ground["claim"]
    assert denied["status"] == "DENIED", \
        f"A DENY decision lands the claim in DENIED, got {denied['status']}"
    assert denied["adjudicated_by_user_id"] == "adj-1", (
        "The denying operator is recorded as adjudicated_by_user_id, got "
        f"{denied['adjudicated_by_user_id']}")
    assert denied["settlement_cents"] is None, \
        f"A denial leaves settlement_cents null, got {denied['settlement_cents']}"

    appealed = appeal_claim(denied["id"],
                            note="Freight bill and dock photographs attached",
                            exhibitor_id=ground["exhibitor"]["id"])
    assert_damage_claim(appealed)
    assert appealed["status"] == "UNDER_INVESTIGATION", (
        "The appeal reopens the investigation, got "
        f"{appealed['status']}")
    assert appealed["appeal_count"] == 1, \
        f"The first appeal takes appeal_count to 1, got {appealed['appeal_count']}"
    assert appealed["adjudicated_by_user_id"] is None, (
        "The appeal clears adjudicated_by_user_id back to null, got "
        f"{appealed['adjudicated_by_user_id']}")


def test_appealed_claim_reapproved_by_a_second_adjuster_settles_and_downgrades_asset():
    """PRD: "A claim resting in `DENIED` is not the end of the road: it may be
    appealed by the `Exhibitor` or a `ClaimsAdjuster`, supplying a mandatory `note`."
    PRD: "`settlement_cents` is then the smallest of three figures: the claim's
    `declared_value_cents`; the weight basis multiplied by 30 cents per pound and
    rounded half up; and a flat per-claim ceiling of 5000000 cents."
    PRD: "When `claim_type` is `DAMAGE`, the linked asset's `condition_grade` is
    downgraded by exactly one step along `A` to `B` to `C` to `D`, and a grade
    already at `D` stays at `D`."

    Design: Difficulty/non_linear_state_machine/damage_claim_denial_appeal_reinvestigation_cycle
    """
    ground = _denied_claim()
    claim_id = ground["claim"]["id"]
    appeal_claim(claim_id, note="Freight bill and dock photographs attached",
                 exhibitor_id=ground["exhibitor"]["id"])
    approved = adjudicate_claim(claim_id, "APPROVE", headers=ADJUSTER_ALT)
    assert approved["status"] == "APPROVED", (
        "The re-investigated claim is approved on the second pass, got "
        f"{approved['status']}")
    assert approved["appeal_count"] == 1, \
        f"Re-adjudication consumes no further appeal, got {approved['appeal_count']}"
    assert approved["adjudicated_by_user_id"] == "adj-2", (
        "The second adjudicator is recorded, got "
        f"{approved['adjudicated_by_user_id']}")
    persisted = get_claim(claim_id)
    assert persisted["settlement_cents"] == 37500, (
        "The 1250 lb crate caps the tariff settlement at 37500 cents, got "
        f"{persisted['settlement_cents']}")
    asset = get_asset(ground["asset"]["id"])
    assert_exhibit_asset(asset)
    assert asset["condition_grade"] == "B", (
        "Approval downgrades the grade-A asset one step to B, got "
        f"{asset['condition_grade']}")


# ---------------------------------------------------------------------------
# The loss cascade: claim -> asset -> crate -> warehouse -> work order
# ---------------------------------------------------------------------------

# A 1000 cwt warehouse holding exactly one 1250 lb crate, that crate packed with
# a grade-A asset worth 1500000 cents, an OPEN refurbishment work order against
# the same asset, and a 900000 cent LOSS claim citing the crate already
# UNDER_INVESTIGATION.
def _loss_claim_over_a_stored_crate():
    ground = setup_claim_under_investigation(
        claim_overrides={"claim_type": "LOSS",
                         "declared_value_cents": DECLARED_VALUE_CENTS,
                         "incident_at": INCIDENT_AT},
        asset_overrides={"list_value_cents": LIST_VALUE_CENTS},
        crate_weight_lbs=CRATE_WEIGHT_LBS,
        with_warehouse=True)
    warehouse_id = ground["warehouse"]["id"]
    ground["crate"] = check_in_crate(ground["crate"]["id"], warehouse_id)
    ground["refurb"] = open_refurb(ground["asset"]["id"], warehouse_id)
    return ground


def test_approved_loss_claim_settles_on_the_tariff_and_writes_the_asset_off():
    """PRD: "An `APPROVE` moves it `UNDER_INVESTIGATION → APPROVED`, requires the
    asset to be in neither `RETIRED` nor `WRITTEN_OFF`, and computes the settlement."
    PRD: "`settlement_cents` is then the smallest of three figures: the claim's
    `declared_value_cents`; the weight basis multiplied by 30 cents per pound and
    rounded half up; and a flat per-claim ceiling of 5000000 cents."
    PRD: "`RETIRED` is terminal, as is `WRITTEN_OFF`, which is reached only by
    cascade from an approved loss claim as described in §3.9."

    Design: Difficulty/transitive_cascade/loss_claim_writes_off_asset_loses_crate_and_frees_warehouse_weight
    """
    ground = _loss_claim_over_a_stored_crate()
    before = get_warehouse(ground["warehouse"]["id"])
    assert before["committed_cwt"] == 13, (
        "One 1250 lb crate rounds up to 13 committed hundredweight, got "
        f"{before['committed_cwt']}")

    claim = adjudicate_claim(ground["claim"]["id"], "APPROVE", headers=ADJUSTER)
    assert_damage_claim(claim)
    assert claim["status"] == "APPROVED", \
        f"The approved loss claim moves to APPROVED, got {claim['status']}"
    assert claim["settlement_cents"] == 37500, (
        "The cited 1250 lb crate caps the tariff settlement at 37500 cents, got "
        f"{claim['settlement_cents']}")
    asset = get_asset(ground["asset"]["id"])
    assert_exhibit_asset(asset)
    assert asset["status"] == "WRITTEN_OFF", (
        "Approving a LOSS claim writes the linked asset off, got "
        f"{asset['status']}")


def test_loss_write_off_loses_the_crate_frees_warehouse_weight_and_cancels_refurb():
    """PRD: "When `claim_type` is `LOSS`, the chain is longer: the linked asset
    transitions to the terminal `WRITTEN_OFF`, which sends every crate packed with
    that asset whose `status` is neither `LOST` nor `RELEASED_TO_CARRIER` to `LOST`,
    which in turn recomputes the `committed_cwt` of whichever warehouses were
    holding those crates; and every refurbishment work order on that asset still
    `OPEN` or `IN_PROGRESS` moves to `CANCELLED`."
    PRD: "Either way, the crate's `warehouse_id` and `stored_since` are cleared to
    null and the holding warehouse's `committed_cwt` is recomputed downward."
    PRD: "Cancelling a work order is available from `OPEN` and from `IN_PROGRESS`,
    and also fires as a cascade when the asset is written off."

    Design: Difficulty/transitive_cascade/loss_claim_writes_off_asset_loses_crate_and_frees_warehouse_weight
    """
    ground = _loss_claim_over_a_stored_crate()
    assert get_warehouse(ground["warehouse"]["id"])["committed_cwt"] == 13, \
        "The warehouse holds 13 committed hundredweight before adjudication"

    claim = adjudicate_claim(ground["claim"]["id"], "APPROVE", headers=ADJUSTER)
    assert claim["status"] == "APPROVED", \
        f"Link 1: the loss claim is approved, got {claim['status']}"
    asset = get_asset(ground["asset"]["id"])
    assert asset["status"] == "WRITTEN_OFF", \
        f"Link 2: the linked asset is written off, got {asset['status']}"
    crate = get_crate(ground["crate"]["id"])
    assert crate["status"] == "LOST", (
        "Link 3: the crate packed with the written-off asset goes LOST, got "
        f"{crate['status']}")
    assert crate["warehouse_id"] is None, (
        "A crate declared LOST has its warehouse_id cleared to null, got "
        f"{crate['warehouse_id']}")
    warehouse = get_warehouse(ground["warehouse"]["id"])
    assert warehouse["committed_cwt"] == 0, (
        "Link 4: the holding warehouse recomputes committed_cwt from 13 down to 0, "
        f"got {warehouse['committed_cwt']}")
    refurb = get_refurb(ground["refurb"]["id"])
    assert refurb["status"] == "CANCELLED", (
        "The OPEN refurbishment work order on the written-off asset is cancelled, "
        f"got {refurb['status']}")


# ---------------------------------------------------------------------------
# Filing and adjudication guards
# ---------------------------------------------------------------------------

def test_third_appeal_is_refused_once_the_appeal_budget_is_exhausted(api):
    """PRD: "A claim may consume at most two appeals; a third is refused with
    `ERR_CLAIM_APPEAL_LIMIT`."
    PRD: "The claim appeal budget is not exhausted — otherwise
    `ERR_CLAIM_APPEAL_LIMIT` (409). Applies to `POST /damage-claims/{id}/appeal`."

    Design: Corner/state_machines/claim_appeal_limit_blocks_the_third_appeal
    """
    ground = _denied_claim()
    exhibitor_id = ground["exhibitor"]["id"]
    claim_id = ground["claim"]["id"]

    appeal_claim(claim_id, note="a1", exhibitor_id=exhibitor_id)
    adjudicate_claim(claim_id, "DENY", headers=ADJUSTER)
    second = appeal_claim(claim_id, note="a2", exhibitor_id=exhibitor_id)
    assert second["appeal_count"] == 2, \
        f"The second appeal exhausts the budget at 2, got {second['appeal_count']}"
    adjudicate_claim(claim_id, "DENY", headers=ADJUSTER)

    response = api.appeal_claim(claim_id, {"note": "a3"},
                                make_exhibitor_headers(exhibitor_id))
    validate_error(response, ApiErrorId.ERR_CLAIM_APPEAL_LIMIT, 409)
    after = get_claim(claim_id)
    assert after["status"] == "DENIED", \
        f"The refused appeal leaves the claim in DENIED, got {after['status']}"
    assert after["appeal_count"] == 2, \
        f"A refused appeal consumes no budget, got {after['appeal_count']}"
    assert after["settlement_cents"] is None, \
        f"A denied claim carries no settlement, got {after['settlement_cents']}"


def test_declared_value_above_the_asset_list_value_is_refused(api):
    """PRD: "`declared_value_cents` may not exceed the asset's `list_value_cents`,
    or the filing is refused with `ERR_DECLARED_VALUE_EXCEEDS_ASSET`."
    PRD: "The declared value does not exceed the asset's list value — otherwise
    `ERR_DECLARED_VALUE_EXCEEDS_ASSET` (422). Applies to `POST /damage-claims`."

    Design: Corner/validations/claim_declared_value_above_asset_list_value_rejected
    """
    ground = setup_show_ground()
    exhibitor_id = ground["exhibitor"]["id"]
    asset = register_asset(exhibitor_id, list_value_cents=LIST_VALUE_CENTS)
    crate = register_crate(exhibitor_id, weight_lbs=CRATE_WEIGHT_LBS,
                           asset_id=asset["id"])

    payload = create_damage_claim_payload(exhibitor_id, asset["id"],
                                          declared_value_cents=2000000,
                                          incident_at=INCIDENT_AT,
                                          crate_id=crate["id"])
    response = api.create_damage_claim(payload, make_exhibitor_headers(exhibitor_id))
    validate_error(response, ApiErrorId.ERR_DECLARED_VALUE_EXCEEDS_ASSET, 422)

    rows, meta = validate_paginated(
        api.list_damage_claims(ADJUSTER, params={"asset_id": asset["id"]}))
    assert rows == [], f"The refused filing must persist no claim, got {rows}"
    assert meta["total_count"] == 0, (
        "No claim exists against the asset after the rejection, got "
        f"{meta['total_count']}")


def test_declared_value_basis_without_coverage_is_refused(api):
    """PRD: "The **declared value** variant is selected by supplying
    `coverage_basis` as `DECLARED_VALUE` at adjudication, and requires the claim to
    name a `shipment_id` whose shipment carries `declared_value_coverage` true;
    selecting it without such a shipment is refused with
    `ERR_COVERAGE_BASIS_UNAVAILABLE`."
    PRD: "The requested coverage basis is available — otherwise
    `ERR_COVERAGE_BASIS_UNAVAILABLE` (422). Applies to
    `POST /damage-claims/{id}/adjudication`."

    Design: Corner/validations/declared_value_basis_without_coverage_rejected
    """
    ground = setup_show_ground(with_warehouse=True)
    exhibitor_id = ground["exhibitor"]["id"]
    asset = register_asset(exhibitor_id, condition_grade="B",
                           list_value_cents=LIST_VALUE_CENTS)
    crate = register_crate(exhibitor_id, weight_lbs=CRATE_WEIGHT_LBS,
                           asset_id=asset["id"])
    shipment = receive_shipment(ground["show"]["id"], exhibitor_id, [crate["id"]],
                                warehouse_id=ground["warehouse"]["id"],
                                declared_value_coverage=False)
    filed = file_claim(exhibitor_id, asset["id"], claim_type="DAMAGE",
                       declared_value_cents=DECLARED_VALUE_CENTS,
                       incident_at=FREIGHT_INCIDENT_AT, crate_id=crate["id"],
                       shipment_id=shipment["id"])
    claim = open_investigation(filed["id"])

    response = api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE", "coverage_basis": "DECLARED_VALUE"},
        ADJUSTER)
    validate_error(response, ApiErrorId.ERR_COVERAGE_BASIS_UNAVAILABLE, 422)

    after = get_claim(claim["id"])
    assert after["status"] == "UNDER_INVESTIGATION", (
        "The refused adjudication leaves the claim under investigation, got "
        f"{after['status']}")
    assert after["settlement_cents"] is None, (
        "The 785000 cent value arm is unreachable without coverage, got "
        f"{after['settlement_cents']}")


def test_claim_citing_a_crate_packed_with_a_different_asset_is_refused(api):
    """PRD: "When a `crate_id` is supplied, that crate must be packed with the
    claimed asset and the asset must belong to the claiming exhibitor, or the filing
    is refused with `ERR_CLAIM_REFERENCE_MISMATCH`."
    PRD: "The cited crate is packed with the claimed asset and the asset belongs to
    the claimant — otherwise `ERR_CLAIM_REFERENCE_MISMATCH` (422). Applies to
    `POST /damage-claims`."

    Design: Corner/validations/claim_citing_crate_of_a_different_asset_rejected
    """
    ground = setup_show_ground()
    exhibitor_id = ground["exhibitor"]["id"]
    asset_a = register_asset(exhibitor_id, list_value_cents=LIST_VALUE_CENTS)
    asset_b = register_asset(exhibitor_id, list_value_cents=LIST_VALUE_CENTS)
    register_crate(exhibitor_id, crate_label="ACME-C1",
                   weight_lbs=CRATE_WEIGHT_LBS, asset_id=asset_a["id"])
    crate_b = register_crate(exhibitor_id, crate_label="ACME-C2", weight_lbs=4000,
                             asset_id=asset_b["id"])

    payload = create_damage_claim_payload(exhibitor_id, asset_a["id"],
                                          declared_value_cents=DECLARED_VALUE_CENTS,
                                          incident_at=INCIDENT_AT,
                                          crate_id=crate_b["id"])
    response = api.create_damage_claim(payload, make_exhibitor_headers(exhibitor_id))
    validate_error(response, ApiErrorId.ERR_CLAIM_REFERENCE_MISMATCH, 422)

    rows, meta = validate_paginated(
        api.list_damage_claims(ADJUSTER, params={"exhibitor_id": exhibitor_id}))
    assert rows == [], f"No claim may be written on the mismatch, got {rows}"
    assert meta["total_count"] == 0, (
        "The exhibitor holds no claim after the rejection, got "
        f"{meta['total_count']}")


def test_adjuster_who_filed_the_claim_cannot_adjudicate_it(api):
    """PRD: "Either decision requires the acting `X-User-ID` to differ from the
    claim's `filed_by_user_id`, and either decision records that operator as
    `adjudicated_by_user_id`."
    PRD: "Three decisions may not be taken by the operator who originated the thing
    being decided: approving or rejecting a change order (the acting `X-User-ID`
    must differ from that change order's `created_by_user_id`), adjudicating a
    damage claim (must differ from `filed_by_user_id`), and voiding an invoice (must
    differ from `issued_by_user_id`)."
    PRD: "Claims are born `FILED` with `coverage_basis` defaulting to
    `TARIFF_LIABILITY`, `settlement_cents` null, `appeal_count` at 0,
    `filed_by_user_id` taken from the acting `X-User-ID` and `adjudicated_by_user_id`
    null."

    Design: Corner/rbac/claims_adjuster_cannot_adjudicate_a_claim_they_filed
    """
    # `actor` binds file_claim's own parameter, so adj-1 files on the exhibitor's
    # behalf and becomes the claim's filed_by_user_id.
    ground = setup_claim_under_investigation(
        claim_overrides={"actor": "adjuster",
                         "declared_value_cents": DECLARED_VALUE_CENTS,
                         "incident_at": INCIDENT_AT},
        asset_overrides={"list_value_cents": LIST_VALUE_CENTS},
        crate_weight_lbs=CRATE_WEIGHT_LBS)
    claim = ground["claim"]
    assert claim["filed_by_user_id"] == "adj-1", (
        "The filing adjuster is recorded as filed_by_user_id, got "
        f"{claim['filed_by_user_id']}")

    response = api.adjudicate_claim(claim["id"], {"decision": "APPROVE"}, ADJUSTER)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    blocked = get_claim(claim["id"])
    assert blocked["status"] == "UNDER_INVESTIGATION", (
        "The blocked adjudication moves nothing, got "
        f"{blocked['status']}")
    assert blocked["settlement_cents"] is None, \
        f"No settlement is computed, got {blocked['settlement_cents']}"

    approved = validate_success(
        api.adjudicate_claim(claim["id"], {"decision": "APPROVE"}, ADJUSTER_ALT))
    assert approved["status"] == "APPROVED", (
        "A second adjuster may take the same decision, got "
        f"{approved['status']}")
    assert approved["adjudicated_by_user_id"] == "adj-2", (
        "The deciding operator is recorded, got "
        f"{approved['adjudicated_by_user_id']}")
    assert approved["settlement_cents"] == 37500, (
        "The 1250 lb crate caps the tariff settlement at 37500 cents, got "
        f"{approved['settlement_cents']}")
