"""Offer construction: computed cost views, band, initial state, audit shape."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_offer, assert_offer_event, event_types,
    create_offer_payload, create_candidate_payload,
    create_draft_requisition, create_open_requisition, create_candidate_recruited,
    create_standard_peers, create_draft_offer,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]
CA = TEST_USERS["comp_analyst_headers"]


def test_offer_create_computed_fields(api):
    """PRD §3.3: "First `bonus_target_cents` is the base times
    `bonus_target_pct`, rounded half up to whole cents. Then the benefits load
    is thirty percent of the sum of base and bonus, again rounded half up to
    whole cents. Then annualized equity is `equity_shares` times
    `equity_fmv_cents` divided across a four-year vest, rounded half up to whole
    cents." and "The **cash view**, exposed as `cash_only_annual_cost_cents`, is
    base plus `bonus_target_cents` plus the sign-on total plus the relocation
    total ... The **budget view**, exposed as `fully_loaded_annual_cost_cents`,
    adds annualized equity and the benefits load on top of the cash view."
    PRD §3.3: "sets the offer to `DRAFT`, initializes `clearance_posture` to
    `NOT_STARTED`, `round_count` to zero".
    PRD §3.2: "The first offer created for a candidate moves them `PROSPECT →
    IN_PROCESS` automatically".

    Design: Corner/entities/offer_create_computed_fields
    """
    req = create_open_requisition(HM)
    cand = create_candidate_recruited(REC, full_name="Cand CE")
    resp = api.create_offer(
        create_offer_payload(
            requisition_id=req["id"], candidate_id=cand["id"],
            base_cents=20000000, bonus_target_pct=0.10,
            equity_shares=10000, equity_fmv_cents=2500,
        ),
        REC,
    )
    offer = validate_success(resp, expected_status=201)
    assert_offer(offer)
    assert offer["bonus_target_cents"] == 2000000
    assert offer["cash_only_annual_cost_cents"] == 22000000
    # 22000000 + 6250000 annualized equity + 6600000 benefits
    assert offer["fully_loaded_annual_cost_cents"] == 34850000
    assert offer["band"] == "IN_BAND"
    assert offer["round_count"] == 0
    assert offer["clearance_posture"] == "NOT_STARTED"
    assert offer["status"] == "DRAFT"
    cand_after = validate_success(api.get_candidate(cand["id"], REC))
    assert cand_after["status"] == "IN_PROCESS"


def test_offer_initial_state_draft(api):
    """PRD §3.3: "sets the offer to `DRAFT`, initializes `clearance_posture` to
    `NOT_STARTED`, `round_count` to zero, `original_submitted_base_cents` and
    `expires_at` to null".

    Design: Corner/state_machines/offer_initial_state_draft
    """
    req = create_open_requisition(HM)
    cand = create_candidate_recruited(REC, full_name="Cand IS")
    resp = api.create_offer(
        create_offer_payload(requisition_id=req["id"], candidate_id=cand["id"], base_cents=18000000),
        REC,
    )
    offer = validate_success(resp, expected_status=201)
    assert offer["status"] == "DRAFT"
    assert offer["expires_at"] is None
    assert offer["original_submitted_base_cents"] is None
    assert offer["round_count"] == 0
    assert offer["version"] == 1


def test_offer_create_missing_required_field_returns_invalid_request(api):
    """PRD §3.3: "The payload names the `requisition_id` and `candidate_id`".
    PRD §2.10 tier 2: "Required fields present ... else `ERR_INVALID_REQUEST`"
    — the shape check fires before existence (tier 5), so the bogus
    requisition_id is never consulted.

    Design: Corner/entities/offer_create_missing_required_field_returns_invalid_request
    """
    cand = create_candidate_recruited(REC, full_name="Cand M1")
    payload = {
        "requisition_id": "00000000-0000-0000-0000-000000000000",
        "base_cents": 18000000,
        "bonus_target_pct": 0,
        "equity_shares": 0,
        "equity_fmv_cents": 0,
    }
    resp = api.create_offer(payload, REC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_offer_event_immutable_shape(api):
    """PRD §2.5: "The audit-trail resource, OfferEvent, is the sole exception:
    it is append-only and immutable, so it carries `id` and `created_at` only —
    `updated_at` and `version` are absent."
    PRD §2.9: "ordered by a `sequence` that starts at 1 and increases
    monotonically per offer".
    PRD §3.3: "appends the `OFFER_CREATED` audit event."

    Design: Corner/entities/offer_event_immutable_shape
    """
    req = create_open_requisition(HM)
    cand = create_candidate_recruited(REC, full_name="Cand EV")
    offer = create_draft_offer(req, cand, REC, base_cents=18000000)
    events = get_success_data(api.list_offer_events(offer["id"], REC))
    assert len(events) == 1
    first = events[0]
    assert_offer_event(first)
    assert first["event_type"] == "OFFER_CREATED"
    assert first["sequence"] == 1
    assert first["actor_user_id"] == "rec-1"


def test_occ_offer_patch_stale_version(api):
    """PRD §2.7: "`PATCH /api/offers/{id}` — revising an offer's terms —
    requires the request to carry `expected_offer_version` holding the offer's
    `version` as the client last observed it. If the offer's current `version`
    has advanced beyond that value ... the request is rejected with
    `ERR_STALE_OFFER_VERSION` (HTTP 412)".
    PRD §3.3: "increments the offer's `version` by one".

    Design: Corner/complexity_layers/occ_offer_patch_stale_version
    """
    req = create_open_requisition(HM)
    cand = create_candidate_recruited(REC, full_name="Cand OC")
    offer = create_draft_offer(req, cand, REC, base_cents=18000000)
    v1 = offer["version"]
    first = validate_success(
        api.patch_offer(offer["id"], {"expected_offer_version": v1, "base_cents": 18500000}, REC)
    )
    assert first["version"] == v1 + 1
    assert first["base_cents"] == 18500000
    resp = api.patch_offer(offer["id"], {"expected_offer_version": v1, "base_cents": 18600000}, REC)
    validate_error(resp, ApiErrorId.ERR_STALE_OFFER_VERSION)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["base_cents"] == 18500000


def test_bonus_rounding_half_up(api):
    """PRD §2.6: "Where a monetary derivation requires rounding, the rule is
    round half up to whole cents, applied at each pinned step of the
    derivation".
    PRD §3.3: "First `bonus_target_cents` is the base times `bonus_target_pct`,
    rounded half up to whole cents. Then the benefits load is thirty percent of
    the sum of base and bonus, again rounded half up to whole cents."

    Design: Corner/calculations/bonus_rounding_half_up
    """
    req = create_open_requisition(HM)
    cand = create_candidate_recruited(REC, full_name="Cand BR")
    resp = api.create_offer(
        create_offer_payload(
            requisition_id=req["id"], candidate_id=cand["id"],
            base_cents=10000100, bonus_target_pct=0.075, equity_shares=0, equity_fmv_cents=0,
        ),
        REC,
    )
    offer = validate_success(resp, expected_status=201)
    # 10000100 * 0.075 = 750007.5 -> round half up -> 750008
    assert offer["bonus_target_cents"] == 750008
    assert offer["cash_only_annual_cost_cents"] == 10750108
    # benefits = round_half_up(0.30 * 10750108) = 3225032; equity 0
    assert offer["fully_loaded_annual_cost_cents"] == 13975140
