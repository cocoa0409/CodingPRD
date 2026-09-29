"""Role authorization, sponsor scoping and segregation of duties."""

from test_helpers import (
    APPROVER_USER_ID,
    ApiErrorId,
    DUAL_ROLE_USER_ID,
    TEST_USERS,
    create_contract,
    create_property,
    create_sponsor,
    make_approver_headers,
    make_sponsor_contact_headers,
    read_contract,
    read_property,
    setup_contract_scenario,
    submit_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

SELLER = TEST_USERS["seller_headers"]
APPROVER = TEST_USERS["approver_headers"]


def test_peer_roles_cannot_perform_each_others_exclusive_operations(api):
    """PRD §2.1: "Once the caller is authenticated, the role is matched against
    the roles authorized for the requested endpoint in §4; a caller whose role is
    not listed there is rejected with `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §2.1: "A `SponsorshipSeller` builds the deal: registering sponsor brands,
    drafting contracts, adding clause entitlements and submitting the result for
    approval. A `ContractApprover` disposes of submitted deals by returning,
    countersigning, activating, terminating or closing them."

    Design: Corner/rbac/seller_cannot_countersign_and_approver_cannot_add_entitlement
    """
    scenario = setup_contract_scenario(
        stage="DRAFT",
        entitlement_specs=[],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    contract_id = scenario["contract"]["id"]
    clause = {
        "inventory_asset_id": scenario["asset"]["id"],
        "clause_ref": "4.2(a)",
        "promised_units": 10,
    }

    approver_writes_clause = api.create_entitlement(contract_id, clause, APPROVER)
    validate_error(approver_writes_clause, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert approver_writes_clause.status_code == 403

    validate_success(api.create_entitlement(contract_id, clause, SELLER), 201)
    submit_contract(contract_id)

    seller_countersigns = api.countersign_contract(
        contract_id,
        {"expected_property_version": read_property(scenario["property"]["id"])["version"]},
        SELLER,
    )
    validate_error(seller_countersigns, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert seller_countersigns.status_code == 403

    assert read_contract(contract_id)["status"] == "SUBMITTED"

    _, meta = validate_paginated(
        api.list_entitlements(SELLER, {"contract_id": contract_id})
    )
    assert meta["total_count"] == 1, (
        f"the refused write must not persist, got {meta['total_count']} clauses"
    )


def test_countersigner_may_not_be_the_operator_who_submitted(api):
    """PRD §2.10: "A contract may not be countersigned by the operator whose
    `X-User-ID` was recorded as `submitted_by_user_id` when the contract was last
    submitted, and a proof of performance may not be adjudicated by the operator
    whose `X-User-ID` was recorded as `captured_by_user_id` when the evidence was
    captured. In both cases the offending request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §3.5: "An accepted countersignature pins `rate_card_id` to the id of the
    property's published card — pinned once, never re-pinned, and unaffected by
    any later supersession — stamps `countersigned_by_user_id` with the caller's
    `X-User-ID`, writes the entitlement and contract money fields computed above,
    and drives the contract `SUBMITTED → COUNTERSIGNED`."

    Design: Corner/rbac/countersigner_equal_to_submitter_returns_segregation_of_duties
    """
    scenario = setup_contract_scenario(
        stage="SUBMITTED",
        seller_user_id=DUAL_ROLE_USER_ID,
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    contract_id = scenario["contract"]["id"]
    assert scenario["contract"]["submitted_by_user_id"] == DUAL_ROLE_USER_ID

    captured_version = read_property(scenario["property"]["id"])["version"]

    same_operator = api.countersign_contract(
        contract_id,
        {"expected_property_version": captured_version},
        make_approver_headers(DUAL_ROLE_USER_ID),
    )
    validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert same_operator.status_code == 403

    accepted = validate_success(
        api.countersign_contract(
            contract_id,
            {"expected_property_version": captured_version},
            APPROVER,
        )
    )
    assert accepted["status"] == "COUNTERSIGNED", (
        "the rejected attempt left the property version untouched, so the same "
        "captured version is still current for a different approver"
    )
    assert accepted["countersigned_by_user_id"] == APPROVER_USER_ID


def test_sponsor_contact_cannot_read_another_sponsors_contract(api):
    """PRD §2.1: "For `SponsorContact` the rule is different: `X-User-ID` is the
    `id` of the acting `Sponsor`, and every contract-scoped operation compares the
    contract's `sponsor_id` to `X-User-ID`."
    PRD §2.1: "A `SponsorContact` reading a single contract, requesting its
    ROI/ROO report, listing its surveys or filing a new survey against it must be
    the sponsor named on that contract; otherwise the request is rejected with
    `ERR_SPONSOR_SCOPE_VIOLATION` (403)."

    Design: Corner/rbac/sponsor_contact_cannot_read_another_sponsors_contract
    """
    prop = create_property()
    sponsor_a = create_sponsor(
        name="Zephyr Cola", category="BEVERAGE", contact_email="ops@zephyr.example"
    )
    sponsor_b = create_sponsor(
        name="Nimbus Motors", category="AUTOMOTIVE",
        contact_email="ops@nimbus.example",
    )
    contract_a = create_contract(sponsor_a["id"], prop["id"])

    intruder = api.get_contract(
        contract_a["id"], make_sponsor_contact_headers(sponsor_b["id"])
    )
    validate_error(intruder, ApiErrorId.ERR_SPONSOR_SCOPE_VIOLATION.value)
    assert intruder.status_code == 403

    owner = api.get_contract(
        contract_a["id"], make_sponsor_contact_headers(sponsor_a["id"])
    )
    own_contract = validate_success(owner)
    assert owner.status_code == 200
    assert own_contract["id"] == contract_a["id"]
