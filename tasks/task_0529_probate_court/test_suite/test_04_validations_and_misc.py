"""Validation gates, referential integrity, reverse-lookup listing, versioning,
and immediate consistency (Corner queue: validations, errors, endpoints,
cross_cutting_complexity_layers, consistency_model sections)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_estate, create_petition,
    create_estate_with_appointed_pr, create_independent_estate_with_appointed_pr,
    add_beneficiary, list_asset, appraise_asset, marshal_asset,
    advance_open_to_accounting, file_final_accounting,
    propose_distribution, approve_distribution, pay_distribution,
    file_claim, allow_claim,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
REP = TEST_USERS["representative_headers"]


# --------------------------------------------------------------------------- #
# validations section
# --------------------------------------------------------------------------- #
def test_final_file_with_unpaid_claim_returns_claims_unpaid(api):
    """PRD §3.10: "a `FINAL` report may be filed only when every `ALLOWED` claim
    under the estate has already been `PAID`, failing which it is rejected with
    `ERR_CLAIMS_UNPAID`."

    An ACCOUNTING estate with an ALLOWED-but-unpaid SECURED claim cannot file FINAL.

    Design: Corner/validations/final_file_with_unpaid_claim_returns_claims_unpaid
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    claim = file_claim(est["id"], "SECURED", 100_000, "Bank")
    allow_claim(est["id"], claim["id"], 100_000)
    advance_open_to_accounting(est["id"])   # -> ACCOUNTING (claim ALLOWED, unpaid)

    acct = get_success_data(api.create_accounting(
        {"estate_id": est["id"], "report_type": "FINAL"}, REP))
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.file_accounting(acct["id"], {"expected_estate_version": v}, REP)
    validate_error(resp, ApiErrorId.ERR_CLAIMS_UNPAID)
    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["status"] == "ACCOUNTING", (
        f"estate should stay ACCOUNTING, got {est_after['status']}")


def test_distribution_approve_exceeds_residue_returns_error(api):
    """PRD §3.9: "when the `proposed_amount_cents` does not exceed the estate's
    `residue_cents`, failing which it is rejected with
    `ERR_DISTRIBUTION_EXCEEDS_RESIDUE`."

    Residue is 1,000,000; approving a 1,500,000 distribution is rejected.

    Design: Corner/validations/distribution_approve_exceeds_residue_returns_error
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    ben = add_beneficiary(est["id"], share_bps=10_000)
    asset = list_asset(est["id"], "CASH", 1_000_000, "Cash")
    appraise_asset(est["id"], asset["id"], 1_000_000)
    advance_open_to_accounting(est["id"])
    marshal_asset(est["id"], asset["id"])
    file_final_accounting(est["id"])            # -> DISTRIBUTING, residue 1000000

    dist = propose_distribution(est["id"], ben["id"], 1_500_000)
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.approve_distribution(dist["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_EXCEEDS_RESIDUE)
    dist_after = get_success_data(api.get_distribution(dist["id"], CLERK))
    assert dist_after["status"] == "PROPOSED"


def test_existence_checked_before_state_on_grant(api):
    """PRD §2.6: "an `id` embedded in a URL must resolve to an existing resource
    within scope, and if it does not, the request fails with `ERR_NOT_FOUND`
    (HTTP 404)." PRD §2.11: "Existence of path-scoped resources is checked next
    (`ERR_NOT_FOUND`)".

    Granting a non-existent petition id yields ERR_NOT_FOUND — existence is
    evaluated ahead of the stateful checks.

    Design: Corner/validations/existence_checked_before_state_on_grant
    """
    est = create_estate(gross_estate_value_cents=300_000)
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.grant_petition(NON_EXISTENT_UUID, {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# --------------------------------------------------------------------------- #
# errors section (only the non-stub instance is translated)
# --------------------------------------------------------------------------- #
def test_pay_distribution_insufficient_marshaled_funds(api):
    """PRD §3.9: "requires that the estate's `marshaled_cash_cents` be at least the
    `proposed_amount_cents`, failing which it is `ERR_INSUFFICIENT_MARSHALED_FUNDS`."

    A first paid distribution drains the 700000 pool to 300000; paying a second
    APPROVED distribution of 400000 then fails for insufficient funds.

    Design: Corner/errors/insufficient_marshaled_funds_error
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    ben = add_beneficiary(est["id"], share_bps=10_000)
    asset = list_asset(est["id"], "CASH", 700_000, "Cash")
    appraise_asset(est["id"], asset["id"], 700_000)
    advance_open_to_accounting(est["id"])
    marshal_asset(est["id"], asset["id"])
    file_final_accounting(est["id"])            # -> DISTRIBUTING, pool 700000

    dist_paid = propose_distribution(est["id"], ben["id"], 400_000)
    dist_target = propose_distribution(est["id"], ben["id"], 400_000)
    approve_distribution(est["id"], dist_paid["id"])
    approve_distribution(est["id"], dist_target["id"])
    pay_distribution(est["id"], dist_paid["id"], receipt_reference="R1")  # pool -> 300000

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.pay_distribution(
        dist_target["id"], {"receipt_reference": "R2", "expected_estate_version": v}, REP)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MARSHALED_FUNDS)
    dist_after = get_success_data(api.get_distribution(dist_target["id"], CLERK))
    assert dist_after["status"] == "APPROVED"


# --------------------------------------------------------------------------- #
# endpoints section
# --------------------------------------------------------------------------- #
def test_create_representative_invalid_petition_ref_returns_invalid_reference(api):
    """PRD §2.6: "Foreign-key references supplied in a request body — a
    `petition_id`, a `representative_id`, or a `beneficiary_id` — are held to a
    stricter rule: they must resolve to an entity that lives under the same estate
    as the resource being created or acted upon. A body reference that names a real
    entity belonging to a different estate is rejected with `ERR_INVALID_REFERENCE`
    (HTTP 422)."

    A representative under estate B naming a petition_id from estate A is rejected.

    Design: Corner/endpoints/create_representative_invalid_petition_ref_returns_invalid_reference
    """
    est_a = create_estate(gross_estate_value_cents=300_000, decedent_name="A")
    pet_a = create_petition(est_a["id"])
    est_b = create_estate(gross_estate_value_cents=300_000, decedent_name="B")
    resp = api.create_representative({
        "estate_id": est_b["id"], "petition_id": pet_a["id"],
        "full_name": "R", "representative_user_id": "pr-x",
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)


def test_list_claims_filtered_by_estate_id(api):
    """PRD §2.5: "peer resources are located by filtered list queries rather than by
    nested URLs." PRD §4: `GET /claims` "List creditor claims; filter by
    estate/class/status".

    Design: Corner/endpoints/list_claims_filtered_by_estate_id
    """
    est = create_estate(gross_estate_value_cents=300_000)
    claim = file_claim(est["id"], "GENERAL", 100_000, "C")
    data, meta = validate_paginated(api.list_claims(CLERK, params={"estate_id": est["id"]}))
    ids = [c["id"] for c in data]
    assert claim["id"] in ids, (
        f"filtered list should contain claim {claim['id']}, got {ids}")
    assert all(c["estate_id"] == est["id"] for c in data), (
        "every claim in the filtered list should belong to the estate")


# --------------------------------------------------------------------------- #
# cross_cutting_complexity_layers section
# --------------------------------------------------------------------------- #
def test_estate_version_increments_on_grant(api):
    """PRD §2.4: an integer `version` that "begins at 1 and increments by one on
    each mutation of that resource." PRD §3.2: "and `Estate.version` increments by
    one" on grant.

    A DRAFT estate starts at version 1; granting its petition bumps it to 2.

    Design: Corner/cross_cutting_complexity_layers/estate_version_increments_on_every_mutation
    """
    est = create_estate(gross_estate_value_cents=300_000)
    pet = create_petition(est["id"])
    assert est["version"] == 1
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(api.grant_petition(pet["id"], {"expected_estate_version": v}, JUDGE))
    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["version"] == 2, (
        f"estate version should be 2 after grant, got {est_after['version']}")


# --------------------------------------------------------------------------- #
# consistency_model section
# --------------------------------------------------------------------------- #
def test_appraise_reflects_inventory_total_immediately(api):
    """PRD §3.6: "On appraisal, the estate's `inventory_total_cents` is recomputed
    as the sum of `appraised_value_cents` over every asset whose status is
    `APPRAISED`, `MARSHALED`, `LIQUIDATED`, or `DISTRIBUTED`".

    After appraising an asset to 800000, an immediately-following read of the estate
    shows inventory_total_cents == 800000 with no lag.

    Design: Corner/consistency_model/appraise_reflects_inventory_total_same_request_chain
    """
    est, pet, rep = create_independent_estate_with_appointed_pr()
    asset = list_asset(est["id"], "REAL_PROPERTY", 500_000, "X")
    appraise_asset(est["id"], asset["id"], 800_000)
    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["inventory_total_cents"] == 800_000, (
        f"inventory should immediately reflect 800000, got "
        f"{est_after['inventory_total_cents']}")
