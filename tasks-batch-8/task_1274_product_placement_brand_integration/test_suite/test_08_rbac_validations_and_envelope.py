"""Authentication, role authorization, ownership, segregation of duties,
compliance gates, the logical clock, and the response envelope
(PRD §2.1, §2.2, §2.3, §2.5, §2.8, §3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_airing_report_payload,
    create_brand,
    create_brand_payload,
    create_brief_payload,
    create_clearance_payload,
    create_disclosure_payload,
    create_episode,
    create_open_brief,
    create_opportunity,
    create_proposal,
    create_series,
    create_series_payload,
    create_shipment,
    decide_clearance_payload,
    get_episode,
    get_success_data,
    make_brand_rep_headers,
    proposal_decision_payload,
    setup_active_contract,
    setup_filed_report,
    setup_verified_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
PROD = TEST_USERS["production_headers"]
PROD_ALT = TEST_USERS["production_alt_headers"]
NETWORK = TEST_USERS["network_headers"]
CLEARANCE = TEST_USERS["clearance_headers"]
FILER = TEST_USERS["verifier_headers"]
VERIFIER = TEST_USERS["verifier_alt_headers"]


# ---------------------------------------------------------------------------
# Authentication & RBAC
# ---------------------------------------------------------------------------


def test_create_series_missing_auth_unauthenticated(api):
    """PRD §2.1: "A request in which either header is missing, or whose role
    value is not one of the declared roles below, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/create_series_missing_auth_unauthenticated
    """
    resp = api.create_series(
        create_series_payload(name="NoAuth Show"), headers={}
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_brandrep_cannot_create_series(api):
    """PRD §2.1: "A request whose role is declared but is not listed among the
    roles authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: POST /series is authorized for
    "AgencyAdmin" only.

    Design: Corner/rbac/brandrep_cannot_create_series
    """
    brand = create_brand()
    rep = make_brand_rep_headers(brand["id"])
    resp = api.create_series(create_series_payload(name="Rogue Show"), rep)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_manager_cannot_decide_clearance(api):
    """PRD §2.1: "A request whose role is declared but is not listed among the
    roles authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: POST /clearances/{id}/decide
    is authorized for "ClearanceOfficer" only.

    Design: Corner/rbac/manager_cannot_decide_clearance
    """
    brand = create_brand()
    series = create_series()
    episode = create_episode(series["id"])
    ep = get_success_data(api.get_episode(episode["id"], MANAGER))
    clearance = get_success_data(
        api.create_clearance(
            episode["id"], create_clearance_payload(brand["id"], ep["version"]), MANAGER
        )
    )
    resp = api.decide_clearance(clearance["id"], decide_clearance_payload("GRANT"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    rows = get_success_data(api.list_episode_clearances(episode["id"], MANAGER))
    by_id = {r["id"]: r for r in rows}
    assert by_id[clearance["id"]]["status"] == "REQUESTED", (
        f"rejected decision leaves the clearance REQUESTED, got {by_id[clearance['id']]['status']}"
    )


def test_brandrep_cannot_submit_other_brands_brief(api):
    """PRD §3.1: "The acting representative's `X-User-ID` must equal the
    brand's `id`; a representative of a different brand is turned away with
    `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/brandrep_cannot_submit_other_brands_brief
    """
    brand_a = create_brand(name="FizzCo", category="BEVERAGE")
    brand_b = create_brand(name="Snackly", category="FOOD")
    rep_b = make_brand_rep_headers(brand_b["id"])
    brief_b = get_success_data(
        api.create_brief(brand_b["id"], create_brief_payload(budget_cents=1000), rep_b)
    )
    rep_a = make_brand_rep_headers(brand_a["id"])
    resp = api.submit_brief(brief_b["id"], rep_a)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    from test_helpers import get_brief

    assert get_brief(brief_b["id"])["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Segregation of duties & compliance gates
# ---------------------------------------------------------------------------


def test_production_decider_cannot_be_episode_creator(api):
    """PRD §3.4: "the deciding representative's `X-User-ID` must differ from
    the episode's `created_by_user_id` — the person who created the episode may
    not decide on proposals targeting it — and a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/production_decider_cannot_be_episode_creator
    """
    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"], creator_headers=PROD)  # created by prod-1
    opportunity = create_opportunity(episode["id"])
    proposal = create_proposal(
        brief["id"], opportunity["id"], proposed_fee_cents=60_000,
        guaranteed_seconds=10, rate_cents_per_second=2000,
    )
    proposal = get_success_data(api.submit_proposal(proposal["id"], MANAGER))
    resp = api.production_decision(
        proposal["id"], proposal_decision_payload("APPROVE"), PROD
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    from test_helpers import get_proposal

    assert get_proposal(proposal["id"])["status"] == "PRODUCTION_REVIEW"


def test_verifier_cannot_verify_own_filing(api):
    """PRD §3.7: "Verification is a second analyst's job: the acting
    `VerificationAnalyst`'s `X-User-ID` must differ from the report's
    `filed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)".

    Design: Corner/validations/verifier_cannot_verify_own_filing
    """
    ctx = setup_filed_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[30],
        measured_verbal_mentions=2,
    )
    resp = api.verify_airing_report(ctx["report"]["id"], FILER)  # same analyst filed it
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    from test_helpers import get_success_data as _gs

    reports = _gs(api.list_episode_airing_reports(ctx["episode"]["id"], MANAGER))
    by_id = {r["id"]: r for r in reports}
    assert by_id[ctx["report"]["id"]]["status"] == "FILED", (
        f"report unchanged, got {by_id[ctx['report']['id']]['status']}"
    )


def test_verify_without_disclosure_ack_rejected(api):
    """PRD §3.7: "an `ACKNOWLEDGED` disclosure filing must exist for the
    contract (`ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, HTTP 422)".

    Design: Corner/validations/verify_without_disclosure_ack_rejected
    """
    # Disclosure is FILED but never ACKNOWLEDGED.
    ctx = setup_filed_report(
        acknowledge_disclosure=False,
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[30],
        measured_verbal_mentions=2,
    )
    resp = api.verify_airing_report(ctx["report"]["id"], VERIFIER)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)


def test_network_decision_before_production_returns_invalid_state(api):
    """PRD §3.4: "a `NetworkStandardsReviewer` decides a `NETWORK_REVIEW`
    proposal" — a proposal still in `PRODUCTION_REVIEW` is not in the from-
    state. PRD §2.8 stage 6: "the target entity is in a valid from-state for
    the requested transition (`ERR_INVALID_STATE`, HTTP 409)".

    Design: Corner/validations/network_decision_before_production_returns_invalid_state
    """
    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])
    proposal = create_proposal(
        brief["id"], opportunity["id"], proposed_fee_cents=60_000,
        guaranteed_seconds=10, rate_cents_per_second=2000,
    )
    proposal = get_success_data(api.submit_proposal(proposal["id"], MANAGER))
    assert proposal["status"] == "PRODUCTION_REVIEW"
    resp = api.network_decision(
        proposal["id"], proposal_decision_payload("APPROVE"), NETWORK
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Temporal gates & clock
# ---------------------------------------------------------------------------


def test_mark_aired_before_air_date_rejected(api):
    """PRD §2.5: "Marking an episode aired is refused with
    `ERR_AIR_DATE_NOT_REACHED` (HTTP 409) while the logical clock reads earlier
    than the episode's `air_date`."

    Design: Corner/validations/mark_aired_before_air_date_rejected
    """
    series = create_series()
    episode = create_episode(series["id"])  # air_date 2026-06-01; clock at default 2026-05-01
    get_success_data(api.lock_episode(episode["id"], PROD))
    resp = api.mark_episode_aired(episode["id"], PROD)
    validate_error(resp, ApiErrorId.ERR_AIR_DATE_NOT_REACHED)
    assert get_episode(episode["id"])["status"] == "LOCKED"


def test_airing_report_before_air_rejected(api):
    """PRD §3.7: "Filing requires the episode to be `AIRED` or `VERIFIED`;
    earlier it is rejected with `ERR_EPISODE_NOT_AIRED` (HTTP 409)."

    Design: Corner/errors/airing_report_before_air_rejected
    """
    ctx = setup_active_contract(
        proposed_fee_cents=60_000, guaranteed_seconds=10,
        guaranteed_verbal_mentions=0, estimated_exposure_seconds=25,
    )
    resp = api.create_airing_report(
        ctx["episode"]["id"],
        create_airing_report_payload(
            ctx["contract"]["id"],
            measured_segments_seconds=[10],
            measured_verbal_mentions=0,
        ),
        FILER,
    )
    validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_AIRED)


def test_file_disclosure_after_air_rejected(api):
    """PRD §3.8: "Filing the draft — which must happen before the episode airs,
    while the episode is still in `SCRIPT_REVIEW` or `LOCKED`"; "once the
    episode has aired, filing is rejected with `ERR_EPISODE_ALREADY_AIRED`."

    Design: Corner/validations/file_disclosure_after_air_rejected
    """
    from test_helpers import set_clock_payload

    ctx = setup_active_contract(
        proposed_fee_cents=60_000, guaranteed_seconds=10,
        guaranteed_verbal_mentions=0, estimated_exposure_seconds=25,
    )
    disclosure = get_success_data(
        api.create_disclosure(
            ctx["contract"]["id"], create_disclosure_payload(), MANAGER
        )
    )
    get_success_data(api.set_clock(set_clock_payload("2026-06-02T00:00:00Z"), ADMIN))
    get_success_data(api.mark_episode_aired(ctx["episode"]["id"], PROD))

    resp = api.file_disclosure(disclosure["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_EPISODE_ALREADY_AIRED)
    filings = get_success_data(api.list_contract_disclosures(ctx["contract"]["id"], MANAGER))
    by_id = {f["id"]: f for f in filings}
    assert by_id[disclosure["id"]]["status"] == "DRAFT", (
        f"filing stays DRAFT, got {by_id[disclosure['id']]['status']}"
    )


def test_clock_default_is_fixed_instant(api):
    """PRD §2.5: "Before any test-driving call has been made, the logical clock
    reads exactly 2026-05-01T00:00:00Z, and the server must not fall back to
    wall-clock time at any point."

    Design: Corner/cross_cutting/clock_default_is_fixed_instant
    """
    resp = api.create_brand(create_brand_payload(), ADMIN)
    data = validate_success(resp, expected_status=201)
    created = data["created_at"]
    # ISO 8601 with three fractional digits; the logical instant is fixed.
    assert created.startswith("2026-05-01T00:00:00"), (
        f"created_at must reflect the fixed logical clock 2026-05-01T00:00:00Z, got {created}"
    )


# ---------------------------------------------------------------------------
# Cross-entity referential & ownership on dispute
# ---------------------------------------------------------------------------


def test_continuity_record_with_foreign_shipment_rejected(api):
    """PRD §3.6: "The referenced shipment must belong to the same contract; a
    shipment of a different contract is rejected with
    `ERR_SHIPMENT_CONTRACT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/continuity_record_with_foreign_shipment_rejected
    """
    from test_helpers import create_continuity_record_payload

    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=2_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opp1 = create_opportunity(episode["id"], start=0, end=40)
    opp2 = create_opportunity(
        episode["id"], start=40, end=80, scene_description="Garage"
    )
    from test_helpers import request_and_grant_clearance

    request_and_grant_clearance(episode["id"], brand["id"])

    def _approved(opp):
        p = create_proposal(
            brief["id"], opp["id"], proposed_fee_cents=500_000,
            guaranteed_seconds=10, rate_cents_per_second=2000,
        )
        p = get_success_data(api.submit_proposal(p["id"], MANAGER))
        p = get_success_data(
            api.production_decision(p["id"], proposal_decision_payload("APPROVE"), PROD_ALT)
        )
        p = get_success_data(
            api.network_decision(p["id"], proposal_decision_payload("APPROVE"), NETWORK)
        )
        return p

    p1 = _approved(opp1)
    p2 = _approved(opp2)
    get_success_data(api.lock_episode(episode["id"], PROD))
    ct1 = get_success_data(api.create_contract_from_proposal(p1["id"], MANAGER))
    ct2 = get_success_data(api.create_contract_from_proposal(p2["id"], MANAGER))
    get_success_data(api.activate_contract(ct1["id"], MANAGER))
    get_success_data(api.activate_contract(ct2["id"], MANAGER))
    shipment = create_shipment(ct1["id"])

    resp = api.create_continuity_record(
        ct2["id"],
        create_continuity_record_payload(shipment["id"], note="wrong contract"),
        PROD,
    )
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_CONTRACT_MISMATCH)


def test_dispute_by_other_brand_forbidden(api):
    """PRD §3.7: "the owning `BrandRep` — resolved through the report's
    contract, its proposal, and that proposal's brief, with
    `ERR_FORBIDDEN_OWNERSHIP` for any other brand's representative".

    Design: Corner/errors/dispute_by_other_brand_forbidden
    """
    other_brand = create_brand(name="Snackly", category="FOOD")
    ctx = setup_verified_report(
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[30],
        measured_verbal_mentions=2,
    )
    other_rep = make_brand_rep_headers(other_brand["id"])
    resp = api.dispute_airing_report(ctx["report"]["id"], other_rep)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    reports = get_success_data(
        api.list_episode_airing_reports(ctx["episode"]["id"], MANAGER)
    )
    by_id = {r["id"]: r for r in reports}
    assert by_id[ctx["report"]["id"]]["status"] == "VERIFIED", (
        f"report unchanged, got {by_id[ctx['report']['id']]['status']}"
    )


# ---------------------------------------------------------------------------
# Envelope & pagination
# ---------------------------------------------------------------------------


def test_pagination_defaults_on_episode_list(api):
    """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may be at
    most 100; `offset` defaults to 0. List responses are always sorted by
    `created_at` ascending, and the `meta` object of a list response carries
    the pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/pagination_defaults_on_episode_list
    """
    series = create_series()
    create_episode(series["id"], episode_number=1, air_date="2026-06-01T20:00:00Z")
    create_episode(series["id"], episode_number=2, air_date="2026-06-08T20:00:00Z")

    resp = api.list_series_episodes(series["id"], MANAGER)
    rows, meta = validate_paginated(resp)
    body = resp.json()
    assert "api_request_id" in body["meta"], "meta carries api_request_id"
    assert "api_request_timestamp" in body["meta"], "meta carries api_request_timestamp"
    assert body["response_type"] == "array", f"got {body['response_type']}"
    assert meta["limit"] == 10, f"default limit 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"default offset 0, got {meta['offset']}"
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert meta["has_more"] is False, f"got {meta['has_more']}"
    assert len(rows) == 2


def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." PRD §2.2: "The `error_id` is
    a unique, machine-readable string that identifies the specific error." PRD
    §2.2: "The `message` provides a human-readable explanation of what went
    wrong." The error envelope fixes `"response_type": "error"` for 4xx
    responses.

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    resp = api.get_brand(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error", f"got {body['response_type']}"
    assert "error_id" in body["data"], "data carries error_id"
    assert "message" in body["data"], "data carries message"
    assert "api_request_id" in body["meta"], "meta carries api_request_id"


def test_fulfill_beyond_owed_returns_invalid_state(api):
    """PRD §3.8: "Attempting to fulfill an obligation that is already
    `FULFILLED` is rejected as an invalid state — fulfillment at or beyond the
    owed count is not possible, so `fulfilled_count` can never exceed
    `owed_count`."

    Design: Corner/errors/fulfill_beyond_owed_returns_invalid_state
    """
    ctx = setup_active_contract(
        proposed_fee_cents=60_000,
        guaranteed_seconds=10,
        guaranteed_verbal_mentions=0,
        cross_promo_owed_count=1,
        estimated_exposure_seconds=25,
    )
    promos = get_success_data(api.list_contract_cross_promos(ctx["contract"]["id"], MANAGER))
    promo = promos[0]
    promo = get_success_data(api.fulfill_cross_promo(promo["id"], MANAGER))
    assert promo["status"] == "FULFILLED", (
        f"precondition: 1 of 1 fulfilled, got {promo['status']}"
    )

    resp = api.fulfill_cross_promo(promo["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    promos = get_success_data(api.list_contract_cross_promos(ctx["contract"]["id"], MANAGER))
    assert promos[0]["fulfilled_count"] == 1, (
        f"no overshoot: fulfilled_count stays 1, got {promos[0]['fulfilled_count']}"
    )
