"""Who may do what on the buyout desk: exclusive verbs, shared writes and peer impostors.

Pricing, approval, origination, refusal responses and dispute adjudication are each held by
a named role, some verbs are shared between two roles, and two roles carry an entity identity
that must match the record they act on. These tests exercise the authorized caller and the
refused one side by side, so that a refusal is proved to be about identity rather than about
the verb being impossible.
"""

from test_helpers import (
    ApiErrorId,
    CarrierCreditTier,
    CapitalState,
    DealStage,
    DisputeStatus,
    DisputeType,
    OfferStatus,
    OutreachStatus,
    PM_APPROVER_USER_ID,
    PM_CLOSER_USER_ID,
    RofrNoticeStatus,
    RofrState,
    ServicingStatus,
    TenancyType,
    ValuationStatus,
    assert_pairwise_distinct,
    build_asset_graph,
    build_chain,
    close_payload,
    create_landowner,
    create_portfolio,
    create_tower_company,
    deal_payload,
    make_landowner_headers,
    make_tower_company_agent_headers,
    open_dispute,
    tenancy_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

RECORDING_REF = "BK1420-PG318"


# ---------------------------------------------------------------------------
# Approval and closing are both PortfolioManager verbs held by different users
# ---------------------------------------------------------------------------


def test_one_manager_approves_the_price_and_a_second_manager_records_the_closing(
    api, approving_manager_headers, closing_manager_headers
):
    """Manager pm-alice approves the pinned valuation and manager pm-bob closes the same deal,
    proving both exclusive operations belong to one role but to two different user ids.

    PRD 2.12: Pricing authority and closing authority are separated at the level of the individual user, not the role.
    PRD 2.12: Any other `PortfolioManager` may close it.
    PRD 3.7: The deal moves `CLEAR_TO_CLOSE → CLOSED` and records `closed_by_user_id`.
    Design: Corner/rbac/exclusive_operations_two_portfolio_managers_cover_approval_and_close
    """
    assert_pairwise_distinct([PM_APPROVER_USER_ID, PM_CLOSER_USER_ID], "PortfolioManager user ids")
    scenario = build_chain(api, "escrowed", approver_user_id=PM_APPROVER_USER_ID)
    assert scenario["valuation"]["status"] == ValuationStatus.APPROVED.value
    assert scenario["valuation"]["approved_by_user_id"] == PM_APPROVER_USER_ID

    closed = validate_success(
        api.close_deal(scenario.deal_id, close_payload(RECORDING_REF), headers=closing_manager_headers)
    )
    assert closed["stage"] == DealStage.CLOSED.value
    assert closed["capital_state"] == CapitalState.DISBURSED.value
    assert closed["closed_by_user_id"] == PM_CLOSER_USER_ID

    read_back = validate_success(api.get_deal(scenario.deal_id, headers=approving_manager_headers))
    assert read_back["stage"] == DealStage.CLOSED.value
    assert read_back["recording_ref"] == RECORDING_REF
    assert read_back["closed_by_user_id"] != scenario["valuation"]["approved_by_user_id"]


# ---------------------------------------------------------------------------
# Approving a valuation is closed to the analyst who created it
# ---------------------------------------------------------------------------


def test_analyst_cannot_approve_the_valuation_it_priced(api, analyst_headers):
    """The AcquisitionAnalyst that created a DRAFT valuation calls the approval endpoint, which
    lists only PortfolioManager, and is refused on the role gate with the draft left untouched.

    PRD 2.1: If both headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the refusal is `ERR_UNAUTHORIZED` (HTTP 403).
    Design: Corner/rbac/exclusive_operations_analyst_cannot_approve_the_valuation_it_created
    """
    scenario = build_chain(api, "valuation_draft")
    assert scenario["valuation"]["status"] == ValuationStatus.DRAFT.value

    refused = api.approve_valuation(scenario.valuation_id, headers=analyst_headers)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    drafts, draft_meta = validate_paginated(
        api.list_valuations(scenario.lease_stream_id, params={"status": ValuationStatus.DRAFT.value}, headers=analyst_headers)
    )
    assert draft_meta["total_count"] == 1
    assert drafts[0]["id"] == scenario.valuation_id
    assert drafts[0]["status"] == ValuationStatus.DRAFT.value
    assert drafts[0].get("approved_by_user_id") is None

    approved, approved_meta = validate_paginated(
        api.list_valuations(
            scenario.lease_stream_id, params={"status": ValuationStatus.APPROVED.value}, headers=analyst_headers
        )
    )
    assert approved_meta["total_count"] == 0
    assert approved == []


def test_portfolio_manager_approves_the_same_draft_the_analyst_was_refused(api, approving_manager_headers, analyst_headers):
    """The identical approval call from a PortfolioManager on the same DRAFT valuation succeeds,
    so the analyst's refusal was about the endpoint's role list and not about the draft's state.

    PRD 2.1: If both headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the refusal is `ERR_UNAUTHORIZED` (HTTP 403).
    PRD 3.4: Approval stamps `approved_by_user_id` from the acting `X-User-ID` and `approved_at` from the current instant, and demotes any previously approved valuation on the same stream: `APPROVED → SUPERSEDED`.
    Design: Corner/rbac/exclusive_operations_analyst_cannot_approve_the_valuation_it_created
    """
    scenario = build_chain(api, "valuation_draft")

    refused = api.approve_valuation(scenario.valuation_id, headers=analyst_headers)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    granted = validate_success(api.approve_valuation(scenario.valuation_id, headers=approving_manager_headers))
    assert granted["status"] == ValuationStatus.APPROVED.value
    assert granted["approved_by_user_id"] == PM_APPROVER_USER_ID
    assert granted["approved_at"] is not None


# ---------------------------------------------------------------------------
# Originating a deal is the analyst's verb, not the seller's
# ---------------------------------------------------------------------------


def test_landowner_cannot_originate_the_buyout_deal_on_its_own_stream(api, analyst_headers, manager_headers, admin_headers):
    """The stream's own Landowner posts a fully valid deal body naming its own stream and the
    approved valuation, and is refused because deal origination is not on its role's list.

    PRD 2.1: If both headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the refusal is `ERR_UNAUTHORIZED` (HTTP 403).
    PRD 3.5: An `AcquisitionAnalyst` opens one by supplying the `portfolio_id`, the `lease_stream_id`, and the `valuation_id` of the valuation being relied on, plus an `easement_type` of either `PERPETUAL_EASEMENT` or `LONG_TERM_EASEMENT`.
    Design: Corner/rbac/exclusive_operations_landowner_cannot_originate_a_deal_on_its_own_stream
    """
    scenario = build_chain(api, "valuation_approved")
    portfolio = create_portfolio(api)
    body = deal_payload(portfolio["id"], scenario.lease_stream_id, scenario.valuation_id)

    refused = api.create_deal(body, headers=scenario.landowner_headers)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    deals, deals_meta = validate_paginated(
        api.list_deals(params={"lease_stream_id": scenario.lease_stream_id}, headers=manager_headers)
    )
    assert deals_meta["total_count"] == 0
    assert deals == []

    untouched = validate_success(api.get_portfolio(portfolio["id"], headers=admin_headers))
    assert untouched["active_deal_count"] == 0
    assert untouched["committed_capital_cents"] == 0

    # The identical body from the authorized originator is accepted.
    opened = validate_success(api.create_deal(body, headers=analyst_headers), 201)
    assert opened["lease_stream_id"] == scenario.lease_stream_id
    assert opened["stage"] == DealStage.ORIGINATION.value
    assert opened["capital_state"] == CapitalState.UNCOMMITTED.value


# ---------------------------------------------------------------------------
# A servicing agent may cure a dispute but may not adjudicate it
# ---------------------------------------------------------------------------


def test_servicing_agent_cannot_uphold_a_dispute_reserved_to_the_administrator(
    api, servicing_headers, admin_headers
):
    """A ServicingAgent submits UPHOLD on an open access dispute; the verb belongs to the
    PlatformAdmin, so the refusal names the action-to-role mismatch and the admin then succeeds.

    PRD 2.1: When a caller is authorized for the endpoint in general but submits a verb reserved for a different role, the refusal is `ERR_ACTION_ROLE_MISMATCH` (HTTP 403) rather than the blanket `ERR_UNAUTHORIZED`.
    PRD 3.8: The dispute transition surface's `action` vocabulary splits three ways: a `ServicingAgent` may submit `START_CURE`, a `Landowner` may submit `CONFIRM_CURE` or `REOPEN`, and a `PlatformAdmin` may submit `UPHOLD` or `DISMISS`.
    Design: Corner/rbac/exclusive_operations_servicing_agent_cannot_uphold_a_dispute_it_is_allowed_to_cure
    """
    scenario = build_chain(api, "closed")
    dispute = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.ACCESS.value,
        description="gate padlocked, crews turned away twice",
    )
    assert dispute["status"] == DisputeStatus.OPEN.value

    refused = api.transition_dispute(dispute["id"], {"action": "UPHOLD"}, headers=servicing_headers)
    validate_error(refused, ApiErrorId.ERR_ACTION_ROLE_MISMATCH.value, 403)

    still_open = validate_success(api.get_dispute(dispute["id"], headers=servicing_headers))
    assert still_open["status"] == DisputeStatus.OPEN.value
    before = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=servicing_headers))
    assert before["servicing_status"] == ServicingStatus.PERFORMING.value

    upheld = validate_success(api.transition_dispute(dispute["id"], {"action": "UPHOLD"}, headers=admin_headers))
    assert upheld["status"] == DisputeStatus.UPHELD.value
    after = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=servicing_headers))
    assert after["servicing_status"] == ServicingStatus.IMPAIRED.value


def test_servicing_agent_refused_the_adjudication_verb_still_starts_the_cure(api, servicing_headers):
    """The same ServicingAgent whose UPHOLD is refused sends START_CURE on the same dispute and
    is served, which shows the endpoint's role gate had already passed for that caller.

    PRD 2.1: When a caller is authorized for the endpoint in general but submits a verb reserved for a different role, the refusal is `ERR_ACTION_ROLE_MISMATCH` (HTTP 403) rather than the blanket `ERR_UNAUTHORIZED`.
    PRD 3.8: **`START_CURE`** takes the case `OPEN → CURE_PENDING` or `REOPENED → CURE_PENDING`.
    Design: Corner/rbac/exclusive_operations_servicing_agent_cannot_uphold_a_dispute_it_is_allowed_to_cure
    """
    scenario = build_chain(api, "closed")
    dispute = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.ACCESS.value,
        description="gate padlocked, crews turned away twice",
    )

    refused = api.transition_dispute(dispute["id"], {"action": "UPHOLD"}, headers=servicing_headers)
    validate_error(refused, ApiErrorId.ERR_ACTION_ROLE_MISMATCH.value, 403)

    cured = validate_success(api.transition_dispute(dispute["id"], {"action": "START_CURE"}, headers=servicing_headers))
    assert cured["status"] == DisputeStatus.CURE_PENDING.value
    assert cured["cure_attempts"] == 1

    watchlisted = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=servicing_headers))
    assert watchlisted["servicing_status"] == ServicingStatus.WATCHLIST.value


# ---------------------------------------------------------------------------
# Only the tower company standing over the site may answer its refusal notice
# ---------------------------------------------------------------------------


def test_a_stranger_tower_company_cannot_waive_another_holders_refusal_notice(api, analyst_headers, manager_headers):
    """An agent of an unrelated tower company waives a served refusal notice and is refused as a
    non-holder; the notice's true holder then waives the very same notice successfully.

    PRD 2.1: When `X-Role` is `TowerCompanyAgent`, `X-User-ID` is the `id` of the acting `TowerCompany` record; responding to a right-of-first-refusal notice compares the tower company that owns the notice's tower site to `X-User-ID`, and a mismatch is refused with `ERR_NOT_ROFR_HOLDER` (HTTP 403).
    PRD 3.6: Only the `TowerCompanyAgent` of the notice's own tower site may respond, submitting a `decision` of either `WAIVE` or `EXERCISE`, and only while the current instant is at or after `window_start` and strictly before `window_end`.
    Design: Corner/rbac/peer_roles_a_tower_company_agent_cannot_answer_another_holders_rofr_notice
    """
    scenario = build_chain(
        api,
        "title_ordered",
        tower_company={"rofr_required": True, "rofr_window_days": 30},
        serve_rofr=True,
    )
    notice_id = scenario["rofr_notice"]["id"]
    assert scenario["rofr_notice"]["status"] == RofrNoticeStatus.SERVED.value

    stranger = create_tower_company(
        api,
        legal_name="Crown Ridge Structures Inc",
        notice_email="notices@crownridge.example",
        rofr_required=True,
    )
    assert stranger["id"] != scenario.tower_company_id

    refused = api.respond_to_rofr_notice(
        notice_id, {"decision": "WAIVE"}, headers=make_tower_company_agent_headers(stranger["id"])
    )
    validate_error(refused, ApiErrorId.ERR_NOT_ROFR_HOLDER.value, 403)

    notices, notices_meta = validate_paginated(api.list_rofr_notices(scenario.deal_id, headers=analyst_headers))
    assert notices_meta["total_count"] == 1
    assert notices[0]["status"] == RofrNoticeStatus.SERVED.value
    mid_deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert mid_deal["rofr_state"] == RofrState.PENDING.value

    waived = validate_success(
        api.respond_to_rofr_notice(notice_id, {"decision": "WAIVE"}, headers=scenario.tower_agent_headers)
    )
    assert waived["status"] == RofrNoticeStatus.WAIVED.value
    assert waived["responded_by_user_id"] == scenario.tower_company_id
    settled_deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert settled_deal["rofr_state"] == RofrState.WAIVED.value


# ---------------------------------------------------------------------------
# Tenancy capture is shared between the analyst and the servicing agent
# ---------------------------------------------------------------------------


def test_analyst_and_servicing_agent_both_add_tenancies_to_the_same_stream(
    api, analyst_headers, servicing_headers, manager_headers
):
    """Both roles that hold the tenancy write add a carrier to one stream, the shared read returns
    both rows, and the quality score counts the servicing agent's colocation alongside the anchor.

    PRD 3.3: Either an `AcquisitionAnalyst` or a `ServicingAgent` may add one, supplying the `carrier_name`, a `carrier_credit_tier` drawn from `INVESTMENT_GRADE`, `CROSSOVER`, and `SPECULATIVE`, a `tenancy_type` of either `ANCHOR` or `COLOCATION`, a `monthly_rent_share_cents` figure of zero or more, and the `term_end_date` on which that carrier's occupancy runs out.
    PRD 3.3: `active_tenancy_count` counts the tenancies in `ACTIVE` or `HOLDOVER`.
    PRD 3.3: 1. Take the tenancy's base credit points from its `carrier_credit_tier`: forty points for `INVESTMENT_GRADE`, twenty-five for `CROSSOVER`, ten for `SPECULATIVE`.
    PRD 3.3: 2. Multiply those base points by the type multiplier for its `tenancy_type`: one exactly for `ANCHOR`, six tenths for `COLOCATION`.
    PRD 3.3: The stream's `tenancy_quality_score` is then the sum of the **two-decimal figures produced at step five** — not the sum of the whole-number `quality_points` values written onto the tenancies — with that sum rounded half up to a whole number and finally clamped into the inclusive range from zero to one hundred.
    Design: Corner/rbac/shared_operations_analyst_and_servicing_agent_both_add_tenancies_to_one_stream
    """
    scenario = build_asset_graph(api, tenancies=())
    assert scenario["lease_stream"]["active_tenancy_count"] == 0

    anchor = validate_success(
        api.create_tenancy(scenario.lease_stream_id, tenancy_payload(), headers=analyst_headers), 201
    )
    after_first = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))
    assert after_first["tenancy_quality_score"] == 40

    colocation = validate_success(
        api.create_tenancy(
            scenario.lease_stream_id,
            tenancy_payload(
                carrier_name="Meridian Mobile",
                carrier_credit_tier=CarrierCreditTier.SPECULATIVE.value,
                tenancy_type=TenancyType.COLOCATION.value,
                monthly_rent_share_cents=90_000,
            ),
            headers=servicing_headers,
        ),
        201,
    )
    assert_pairwise_distinct([anchor["id"], colocation["id"]], "tenancy ids")

    rows, rows_meta = validate_paginated(api.list_tenancies(scenario.lease_stream_id, headers=servicing_headers))
    assert rows_meta["total_count"] == 2
    assert [row["carrier_name"] for row in rows] == ["Vantage Wireless", "Meridian Mobile"]

    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=manager_headers))
    assert stream["active_tenancy_count"] == 2
    # 40.00 for the investment-grade anchor plus 10 x 0.6 = 6.00 for the speculative colocation.
    assert stream["tenancy_quality_score"] == 46
    assert stream["version"] > after_first["version"]


# ---------------------------------------------------------------------------
# Outreach suppression is a shared write and a wider read
# ---------------------------------------------------------------------------


def test_admin_suppresses_outreach_and_analyst_clears_it_for_the_servicing_agent_to_read(
    api, admin_headers, analyst_headers, servicing_headers
):
    """The PlatformAdmin suppresses a landowner's outreach and the AcquisitionAnalyst clears the
    same flag and corrects the email, after which a ServicingAgent read sees the restored values.

    PRD 3.2: A `PlatformAdmin` or `AcquisitionAnalyst` may patch a landowner to correct `contact_email`, and may pass a `suppress_outreach` boolean.
    PRD 3.2: Setting `suppress_outreach` to true forces `outreach_status` to `DO_NOT_CONTACT`, which is the one value the progression logic never produces on its own; setting it back to false restores whatever value the offer and deal progression implies.
    PRD 3.2: Its `outreach_status` is initialized to `NEW` and thereafter tracks the progression of offers and deals through `CONTACTED`, `NEGOTIATING`, `UNDER_CONTRACT`, and `CLOSED`.
    Design: Corner/rbac/shared_operations_admin_and_analyst_both_patch_the_landowner_the_servicing_agent_reads
    """
    owner = create_landowner(api)
    assert owner["outreach_status"] == OutreachStatus.NEW.value

    suppressed = validate_success(api.update_landowner(owner["id"], {"suppress_outreach": True}, headers=admin_headers))
    assert suppressed["outreach_status"] == OutreachStatus.DO_NOT_CONTACT.value

    restored = validate_success(
        api.update_landowner(
            owner["id"],
            {"suppress_outreach": False, "contact_email": "trustee@hollis.example"},
            headers=analyst_headers,
        )
    )
    assert restored["outreach_status"] == OutreachStatus.NEW.value
    assert restored["contact_email"] == "trustee@hollis.example"

    read_by_servicer = validate_success(api.get_landowner(owner["id"], headers=servicing_headers))
    assert read_by_servicer["outreach_status"] == OutreachStatus.NEW.value
    assert read_by_servicer["contact_email"] == "trustee@hollis.example"

    # The shared read carries no write grant with it.
    refused = api.update_landowner(owner["id"], {"contact_email": "servicer@hollis.example"}, headers=servicing_headers)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


# ---------------------------------------------------------------------------
# Only the addressed landowner may accept the offer
# ---------------------------------------------------------------------------


def test_an_unrelated_landowner_cannot_accept_the_offer_written_to_another_owner(api, manager_headers):
    """A second, unrelated Landowner accepts an offer addressed to the stream's owner and is
    refused on ownership, leaving the deal uncommitted; the real owner's identical ACCEPT lands.

    PRD 2.1: When `X-Role` is `Landowner`, `X-User-ID` is the `id` of the acting `Landowner` record; ownership checks on any resource that references a `Landowner` compare the resource's landowner reference to `X-User-ID`, walking from an `Offer` through its deal to the deal's lease stream and from a `DisputeCase` through its lease stream, and a mismatch is refused with `ERR_NOT_DEAL_LANDOWNER` (HTTP 403).
    PRD 3.5: Only the deal's own landowner may accept, and only while the current instant is strictly before `expires_at`.
    Design: Corner/rbac/peer_roles_a_landowner_cannot_accept_the_offer_addressed_to_another_landowner
    """
    scenario = build_chain(api, "offer_sent")
    stranger = create_landowner(
        api, legal_name="Bramble Ridge Trust", entity_type="TRUST", contact_email="trustee@bramble.example"
    )
    assert stranger["id"] != scenario.landowner_id

    refused = api.transition_offer(
        scenario.offer_id, {"action": "ACCEPT"}, headers=make_landowner_headers(stranger["id"])
    )
    validate_error(refused, ApiErrorId.ERR_NOT_DEAL_LANDOWNER.value, 403)

    mid_deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert mid_deal["stage"] == DealStage.NEGOTIATION.value
    assert mid_deal["capital_state"] == CapitalState.UNCOMMITTED.value

    accepted = validate_success(
        api.transition_offer(scenario.offer_id, {"action": "ACCEPT"}, headers=scenario.landowner_headers)
    )
    assert accepted["status"] == OfferStatus.ACCEPTED.value

    closed_deal_state = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert closed_deal_state["stage"] == DealStage.DILIGENCE.value
    assert closed_deal_state["capital_state"] == CapitalState.RESERVED.value

    offers, offers_meta = validate_paginated(api.list_offers(scenario.deal_id, headers=manager_headers))
    assert offers_meta["total_count"] == 1
    assert offers[0]["status"] == OfferStatus.ACCEPTED.value
