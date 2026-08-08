"""Agreement drafting, optimistic concurrency, signatures, and activation gating."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_leaseholder_headers, make_landlord_headers,
    setup_scenario, current_listing_version,
)


def _draft_payload(application_id, expected_version,
                   start="2026-06-10", end="2026-08-31"):
    return {"application_id": application_id, "expected_listing_version": expected_version,
            "occupancy_start_date": start, "occupancy_end_date": end}


def test_duplicate_signature_same_role_rejected(api):
    """PRD §3.5: "A role that has already signed cannot sign again; a repeat is rejected
    with `ERR_DUPLICATE_SIGNATURE`."

    Design: Corner/state_machines/duplicate_signature_same_role_rejected
    """
    ctx = setup_scenario(api, stage="drafted")
    lh = make_leaseholder_headers(ctx["leaseholder"]["id"])
    ll = make_landlord_headers(ctx["landlord"]["id"])
    validate_success(api.send_for_signature(ctx["agreement"]["id"], lh))
    validate_success(api.create_signature(ctx["agreement"]["id"], {"signer_role": "LANDLORD"}, ll), 201)
    resp = api.create_signature(ctx["agreement"]["id"], {"signer_role": "LANDLORD"}, ll)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SIGNATURE.value)


def test_activate_non_executed_agreement_rejected(api):
    """PRD §3.5: "Activation requires the agreement to be `EXECUTED` (else
    `ERR_AGREEMENT_NOT_EXECUTED`)".

    Design: Corner/state_machines/activate_non_executed_agreement_rejected
    """
    ctx = setup_scenario(api, stage="drafted")  # agreement still DRAFT
    resp = api.activate_agreement(ctx["agreement"]["id"], make_leaseholder_headers(ctx["leaseholder"]["id"]))
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED.value)


def test_occ_stale_listing_version_rejected(api):
    """PRD §2.6: "If that value does not match the listing's current `version`, the
    create is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412), and no agreement is
    drafted."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_listing_version_on_agreement_create
    """
    ctx = setup_scenario(api, stage="matched")
    lh = make_leaseholder_headers(ctx["leaseholder"]["id"])
    v_pre = current_listing_version(api, ctx["listing"]["id"])
    validate_success(api.create_agreement(_draft_payload(ctx["application"]["id"], v_pre), lh), 201)
    # Second draft still carries the pre-supersede version -> stale.
    resp = api.create_agreement(_draft_payload(ctx["application"]["id"], v_pre), lh)
    validate_error(resp, ApiErrorId.ERR_STALE_LISTING_VERSION.value)


def test_occ_current_version_supersedes_prior_draft(api):
    """PRD §2.6: "a successful agreement draft against an OPEN listing legitimately voids
    any prior non-terminal agreement on that same listing and increments the listing's
    `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_listing_version_supersedes_prior_draft
    """
    ctx = setup_scenario(api, stage="matched")
    lh = make_leaseholder_headers(ctx["leaseholder"]["id"])
    v_pre = current_listing_version(api, ctx["listing"]["id"])
    agr_a = validate_success(api.create_agreement(_draft_payload(ctx["application"]["id"], v_pre), lh), 201)
    v_cur = current_listing_version(api, ctx["listing"]["id"])
    agr_b = validate_success(api.create_agreement(_draft_payload(ctx["application"]["id"], v_cur), lh), 201)

    assert agr_b["status"] == "DRAFT", f"new draft must be DRAFT, got {agr_b['status']}"
    a_after = validate_success(api.get_agreement(agr_a["id"], TEST_USERS["admin_headers"]))
    assert a_after["status"] == "VOID", f"superseded prior draft must be VOID, got {a_after['status']}"


class TestActivateRequiresSettlementFunded:
    """Difficulty: cross_entity_state_dependency — an EXECUTED agreement cannot activate
    until its Settlement is FUNDED."""

    def test_activate_with_pending_settlement_rejected(self, api):
        """PRD §3.5: "its settlement to be `FUNDED` (else `ERR_SETTLEMENT_NOT_FUNDED`)".

        Design: Difficulty/cross_entity_state_dependency/activate_requires_settlement_funded
        """
        ctx = setup_scenario(api, stage="executed")  # EXECUTED, settlement still PENDING
        resp = api.activate_agreement(ctx["agreement"]["id"], make_leaseholder_headers(ctx["leaseholder"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FUNDED.value)

    def test_activate_after_funding_succeeds(self, api):
        """PRD §3.5: "An executed agreement is activated by the owning `Leaseholder`,
        moving it from `EXECUTED` to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/activate_requires_settlement_funded
        """
        ctx = setup_scenario(api, stage="funded")  # EXECUTED + settlement FUNDED
        resp = api.activate_agreement(ctx["agreement"]["id"], make_leaseholder_headers(ctx["leaseholder"]["id"]))
        data = validate_success(resp)
        assert data["status"] == "ACTIVE", f"funded executed agreement must activate, got {data['status']}"
