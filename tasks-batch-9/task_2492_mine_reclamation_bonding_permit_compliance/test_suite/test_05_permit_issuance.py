"""The issuance decision and the gates an application must clear to pass it."""
from test_helpers import (
    BOND_SPECIALIST_ACCEPTER,
    PERMIT_REVIEWER,
    ApiErrorId,
    api_client as api,
    assert_money,
    assert_permit,
    chain_applied,
    chain_bond_posted,
    create_permit_revision_payload,
    file_estimate,
    propose_instrument,
    refresh_permit,
    validate_error,
    validate_paginated,
    validate_success,
)

CEDAR_BLUFF_OPERATOR = {
    "legal_name": "Cedar Bluff Minerals",
    "tangible_net_worth": 18000000.00,
    "fixed_assets_in_state": 9000000.00,
    "total_liabilities": 6000000.00,
    "net_income_prior_year": 900000.00,
    "elected_financial_test": "NET_WORTH_TEST",
}
CEDAR_BLUFF_SITE = {"name": "Cedar Bluff Pit", "county": "Barbour", "total_acres": 350.00}


def _cedar_bluff_with_submitted_estimate():
    """An application whose only cost estimate is still in SUBMITTED."""
    ctx = chain_applied(
        operator_overrides=CEDAR_BLUFF_OPERATOR,
        site_overrides=CEDAR_BLUFF_SITE,
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "FORESTLAND"},
    )
    ctx["filed_estimate"] = file_estimate(
        ctx["permit"]["id"], ctx["operator_headers"], direct_cost_per_acre=6000.00
    )
    return ctx


def test_issue_without_an_accepted_estimate_is_refused():
    """An `ACCEPTED` cost estimate must exist for the permit, checked at priority
    11 and reported as `ERR_NO_ACCEPTED_ESTIMATE`.

    Design: Difficulty/cross_entity_state_dependency/permit_issue_gated_on_accepted_estimate_state
    """
    ctx = _cedar_bluff_with_submitted_estimate()
    assert ctx["filed_estimate"]["status"] == "SUBMITTED", "the estimate is merely filed"

    response = api.decide_permit(ctx["permit"]["id"], {"decision": "ISSUE"}, PERMIT_REVIEWER)
    validate_error(response, ApiErrorId.ERR_NO_ACCEPTED_ESTIMATE, 409)

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["status"] == "APPLICATION_SUBMITTED", "the refused decision moved nothing"
    assert permit["issued_at"] is None, "issued_at is still unstamped"
    assert permit["version"] == ctx["permit"]["version"], "no mutation, no version bump"


def test_issue_succeeds_once_the_estimate_is_accepted_and_the_bond_covers_it():
    """`APPLICATION_SUBMITTED → ISSUED` sets `status` to `ISSUED`, stamps
    `issued_at` with the logical clock's current value, recomputes
    `compliance_posture`, and increments the permit's `version` by 1.

    Design: Difficulty/cross_entity_state_dependency/permit_issue_gated_on_accepted_estimate_state
    """
    ctx = _cedar_bluff_with_submitted_estimate()
    permit_id = ctx["permit"]["id"]

    refused = api.decide_permit(permit_id, {"decision": "ISSUE"}, PERMIT_REVIEWER)
    validate_error(refused, ApiErrorId.ERR_NO_ACCEPTED_ESTIMATE, 409)

    guard = refresh_permit(permit_id)["version"]
    validate_success(
        api.accept_estimate(
            ctx["filed_estimate"]["id"],
            {"expected_permit_version": guard},
            PERMIT_REVIEWER,
        )
    )
    proposed = propose_instrument(
        permit_id, ctx["operator_headers"], instrument_type="CASH", face_amount=900000.00
    )
    validate_success(api.accept_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER))

    issued = validate_success(
        api.decide_permit(permit_id, {"decision": "ISSUE"}, PERMIT_REVIEWER)
    )
    assert_permit(issued)
    assert issued["status"] == "ISSUED", "the same request now succeeds"
    assert issued["issued_at"] is not None, "issuance stamps issued_at"
    assert_money(issued["bond_required_amount"], 865998.00, "bond_required_amount")
    assert_money(issued["bond_held_amount"], 900000.00, "bond_held_amount")
    assert_money(issued["bond_deficiency_amount"], 0.00, "bond_deficiency_amount")
    assert issued["compliance_posture"] == "COMPLIANT", "the covered bond leaves it compliant"


def test_denial_without_a_reason_rejected():
    """The `decision` and `denial_reason` fields are coupled: a `DENY` requires a
    `denial_reason` that is present and non-empty, and any decision that is not
    `DENY` requires that `denial_reason` be absent entirely; either violation is
    `ERR_DECISION_REASON_REQUIRED`.

    Design: Corner/validations/permit_denial_without_reason_rejected
    """
    ctx = chain_applied(
        operator_overrides={
            "legal_name": "Reasonless Denial Mining",
            "tangible_net_worth": 10800000.00,
            "fixed_assets_in_state": 5300000.00,
            "total_liabilities": 4150000.00,
            "net_income_prior_year": 210000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Reasonless Pit", "county": "Sheridan", "total_acres": 165.00},
        mining_plan_acres=70.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
    )

    response = api.decide_permit(ctx["permit"]["id"], {"decision": "DENY"}, PERMIT_REVIEWER)
    validate_error(response, ApiErrorId.ERR_DECISION_REASON_REQUIRED, 422)

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["status"] == "APPLICATION_SUBMITTED", "the permit is undecided"
    assert permit["denial_reason"] is None, "nothing was stored"
    assert permit["version"] == 1, "the version has not moved off its initial value"


def test_issue_with_a_discounted_surety_below_the_requirement_rejected():
    """The permit's `bond_held_amount` must be at least its
    `bond_required_amount`, checked last at priority 15 and reported as
    `ERR_BOND_BELOW_REQUIRED`.

    Design: Corner/errors/permit_issue_with_discounted_surety_below_required_rejected
    """
    ctx = chain_bond_posted(
        operator_overrides={
            "legal_name": "Short Bond Mining",
            "tangible_net_worth": 12250000.00,
            "fixed_assets_in_state": 6090000.00,
            "total_liabilities": 4345000.00,
            "net_income_prior_year": 354000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Short Bond Pit", "county": "Nye", "total_acres": 243.00},
        mining_plan_acres=120.00,
        instrument_type="SURETY",
        face_amount=900000.00,
        instrument_overrides={
            "rating": "A", "surety_company_name": "Cordillera Surety",
        },
    )
    # face 900000.00 x the A multiplier 0.90 credits only 810000.00.
    assert_money(ctx["instrument"]["credited_amount"], 810000.00, "credited_amount")
    assert_money(ctx["instrument"]["face_amount"], 900000.00, "face_amount")
    assert_money(ctx["permit"]["bond_deficiency_amount"], 55998.00, "bond_deficiency_amount")

    response = api.decide_permit(ctx["permit"]["id"], {"decision": "ISSUE"}, PERMIT_REVIEWER)
    validate_error(response, ApiErrorId.ERR_BOND_BELOW_REQUIRED, 409)

    permit = refresh_permit(ctx["permit"]["id"])
    assert permit["status"] == "APPLICATION_SUBMITTED", "the permit is not issued"
    assert permit["issued_at"] is None
    assert permit["compliance_posture"] == "BOND_DEFICIENT"


def test_denied_permit_admits_no_revision():
    """Revisions may only be filed against a permit whose `status` is `ISSUED` or
    `RECLAMATION_PHASE`, else `ERR_PERMIT_STATE_INVALID`, and filing is
    ownership-checked.

    Design: Corner/state_machines/denied_permit_rejects_revision_creation
    """
    ctx = chain_applied(
        operator_overrides={
            "legal_name": "Turned Down Mining",
            "tangible_net_worth": 10500000.00,
            "fixed_assets_in_state": 5200000.00,
            "total_liabilities": 4100000.00,
            "net_income_prior_year": 200000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Turned Down Pit", "county": "Sheridan", "total_acres": 160.00},
        mining_plan_acres=70.00,
        permit_overrides={"post_mining_land_use": "CROPLAND"},
    )
    permit_id = ctx["permit"]["id"]

    denied = validate_success(
        api.decide_permit(
            permit_id,
            {
                "decision": "DENY",
                "denial_reason": "The mining plan omits an approved sediment control design.",
            },
            PERMIT_REVIEWER,
        )
    )
    assert denied["status"] == "DENIED", "DENIED is terminal"
    assert denied["denial_reason"] == (
        "The mining plan omits an approved sediment control design."
    )
    assert denied["issued_at"] is None, "a denial leaves issued_at null"

    response = api.create_permit_revision(
        create_permit_revision_payload(
            permit_id,
            revision_type="SEQUENCE_CHANGE",
            sequence_note="Reverse the pit advance direction.",
        ),
        ctx["operator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_STATE_INVALID, 409)

    _, meta = validate_paginated(
        api.list_permit_revisions_for_permit(permit_id, PERMIT_REVIEWER)
    )
    assert meta["total_count"] == 0, "no revision row was stored"
