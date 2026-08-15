"""Difficulty queue A — cross_entity_state_dependency (2 instances, 4 tests)."""

from test_helpers import (
    ADOPS,
    FINANCE,
    ApiErrorId,
    create_ad_copy,
    create_advertiser,
    create_campaign,
    get_campaign,
    get_invoice,
    make_advertiser_headers,
    review_ad_copy,
    setup_measured_delivery,
    submit_ad_copy,
    transition_make_good,
    validate_error,
    validate_success,
)


def _setup_submitted_copy_gate():
    """Direct advertiser; DRAFT campaign; one PRODUCED_AUDIO copy SUBMITTED but
    not yet APPROVED."""
    advertiser = create_advertiser(name="GateCo", category="FINTECH")
    owner = make_advertiser_headers(advertiser["id"])
    campaign = create_campaign(advertiser["id"], name="CG",
                               flight_start="2026-08-01T00:00:00Z",
                               flight_end="2026-09-01T00:00:00Z",
                               booked_impressions=100, cpm_cents=1000)
    copy = create_ad_copy(campaign["id"], owner, kind="PRODUCED_AUDIO",
                          script_text="spot")
    copy = submit_ad_copy(copy["id"], owner)
    return {"advertiser": advertiser, "owner": owner, "campaign": campaign,
            "copy": copy}


def _setup_offered_makegood_gate():
    """Direct advertiser; campaign booked 1000 cpm 2000 with 800 measured
    deliveries; ENDED; invoice DRAFT (shortfall 200); MakeGood OFFERED."""
    ctx = setup_measured_delivery(
        booked_impressions=1000, cpm_cents=2000, downloads=800,
        reserved_impressions=500, category="AUTOMOTIVE",
        end_campaign_too=True, create_invoice_too=True,
    )
    assert ctx["make_good"] is not None, "Setup failed: expected an OFFERED MakeGood"
    assert ctx["make_good"]["status"] == "OFFERED"
    return ctx


# =========================================================================
# campaign_activation_requires_approved_copy
# =========================================================================

def test_activate_without_approved_copy_fails(api):
    """PRD §3.2: "Activation moves a campaign `DRAFT → ACTIVE` or resumes it `PAUSED → ACTIVE`; either requires the advertiser to be `ACTIVE` and at least one of the campaign's ad copies to be `APPROVED`, failing with `ERR_ADVERTISER_SUSPENDED` or `ERR_NO_APPROVED_COPY` respectively, and activation attempted from any other state fails with `ERR_CAMPAIGN_NOT_ACTIVATABLE`."

    Design: Difficulty/cross_entity_state_dependency/campaign_activation_requires_approved_copy
    """
    ctx = _setup_submitted_copy_gate()
    resp = api.transition_campaign(ctx["campaign"]["id"], {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_COPY)
    assert get_campaign(ctx["campaign"]["id"])["status"] == "DRAFT"


def test_activate_succeeds_once_copy_reaches_approved(api):
    """PRD §3.2: "either requires the advertiser to be `ACTIVE` and at least one of the campaign's ad copies to be `APPROVED`, failing with `ERR_ADVERTISER_SUSPENDED` or `ERR_NO_APPROVED_COPY` respectively, and activation attempted from any other state fails with `ERR_CAMPAIGN_NOT_ACTIVATABLE`."

    Design: Difficulty/cross_entity_state_dependency/campaign_activation_requires_approved_copy
    """
    ctx = _setup_submitted_copy_gate()
    resp = api.transition_campaign(ctx["campaign"]["id"], {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_COPY)
    # PRODUCED_AUDIO is reviewed by AdOps.
    review_ad_copy(ctx["copy"]["id"], "APPROVE", ADOPS)
    resp = api.transition_campaign(ctx["campaign"]["id"], {"action": "ACTIVATE"}, ADOPS)
    campaign = validate_success(resp)
    assert campaign["status"] == "ACTIVE"


# =========================================================================
# invoice_issue_blocked_by_offered_makegood
# =========================================================================

def test_issue_blocked_while_makegood_offered(api):
    """PRD §3.7: "While any make-good of the campaign is `OFFERED`, issuing the invoice is blocked with `ERR_MAKE_GOOD_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/invoice_issue_blocked_by_offered_makegood
    """
    ctx = _setup_offered_makegood_gate()
    resp = api.transition_invoice(ctx["invoice"]["id"], {"action": "ISSUE"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_MAKE_GOOD_OUTSTANDING)
    assert get_invoice(ctx["invoice"]["id"])["status"] == "DRAFT"


def test_issue_succeeds_after_makegood_declined_with_credit(api):
    """PRD §3.7: "**Declining** the offer grants cash instead: the still-`DRAFT` invoice recomputes with `make_good_credit_cents` set to the shortfall charge above, and `agency_commission_cents` and `net_cents` recomputed in the pinned order."
    PRD §3.7: "While any make-good of the campaign is `OFFERED`, issuing the invoice is blocked with `ERR_MAKE_GOOD_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/invoice_issue_blocked_by_offered_makegood
    """
    ctx = _setup_offered_makegood_gate()
    resp = api.transition_invoice(ctx["invoice"]["id"], {"action": "ISSUE"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_MAKE_GOOD_OUTSTANDING)
    transition_make_good(
        ctx["make_good"]["id"], "DECLINE",
        make_advertiser_headers(ctx["advertiser"]["id"]),
    )
    resp = api.transition_invoice(ctx["invoice"]["id"], {"action": "ISSUE"}, FINANCE)
    invoice = validate_success(resp)
    assert invoice["status"] == "ISSUED"
    # round_half_up(200 * 2000 / 1000) == 400 granted at DECLINE.
    assert invoice["make_good_credit_cents"] == 400, (
        f"Decline credit must be 400, got {invoice['make_good_credit_cents']}"
    )
