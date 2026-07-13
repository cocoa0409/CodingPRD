"""Restoration costing (quoted vs assessed variants), workshop half-open slot conflicts,
and assessment state / existence guards."""
import test_helpers as th


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / restoration_quoted_vs_assessed_cost
# ---------------------------------------------------------------------------
def test_restoration_request_computes_quoted_cost(api):
    """PRD §3.8: "`quoted_cost_cents` is the reported area multiplied by the per-square-centimetre
    service rate — 2 cents for `CLEANING`, 6 cents for `REPAIR`, and 9 cents for `REFINISH`."

    Design: Difficulty/dual_variant_calc/restoration_quoted_vs_assessed_cost
    """
    ctx = th.setup_requested_restoration(
        service_type="REPAIR", reported_area_cm2=1000,
        cemetery_over={"requires_permit": True, "permit_fee_cents": 12000},
    )
    assert ctx["restoration"]["quoted_cost_cents"] == 6000, ctx["restoration"]


def test_restoration_assessment_computes_assessed_cost_with_severe_surcharge(api):
    """PRD §3.8: "Otherwise the assessed cost is the measured area multiplied by the service rate,
    plus a flat surcharge of 5,000 cents when the `condition` is `SEVERE`."

    Design: Difficulty/dual_variant_calc/restoration_quoted_vs_assessed_cost
    """
    ctx = th.setup_requested_restoration(
        service_type="REPAIR", reported_area_cm2=1000,
        cemetery_over={"requires_permit": True, "permit_fee_cents": 12000},
    )
    payload = th.assess_restoration_payload(
        ctx["workshop"]["id"], 1200, "SEVERE", "2026-03-10T09:00:00Z", "2026-03-10T11:00:00Z"
    )
    rest = th.validate_success(
        api.assess_restoration(ctx["restoration"]["id"], payload, th.TEST_USERS["shop_manager_headers"])
    )
    assert rest["assessed_cost_cents"] == 12200, rest
    assert rest["status"] == "ASSESSED", rest
    assert rest["assessed_cost_cents"] != rest["quoted_cost_cents"], rest


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / workshop_halfopen_slot_overlap
# ---------------------------------------------------------------------------
def test_workshop_overlapping_slot_returns_conflict(api):
    """PRD §2.7: "A new fabrication or restoration slot occupies the interval from its start up to
    but not including its end; it may not overlap any interval already committed on that same
    workshop, where the committed set is every `SCHEDULED` fabrication job plus every `ASSESSED`
    restoration job on the workshop."

    Design: Difficulty/resource_temporal_overlap/workshop_halfopen_slot_overlap
    """
    ctx = th.setup_workshop_with_assessed_restoration_and_pending(
        a_start="2026-03-10T09:00:00Z", a_end="2026-03-10T12:00:00Z", second_reported=600,
        cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    payload = th.assess_restoration_payload(
        ctx["workshop"]["id"], 600, "NORMAL", "2026-03-10T10:00:00Z", "2026-03-10T11:00:00Z"
    )
    resp = api.assess_restoration(ctx["restoration_pending"]["id"], payload, th.TEST_USERS["shop_manager_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_WORKSHOP_SLOT_CONFLICT.value)
    still = th.validate_success(api.get_restoration(ctx["restoration_pending"]["id"], th.TEST_USERS["shop_manager_headers"]))
    assert still["status"] == "REQUESTED", still


def test_workshop_adjacent_touching_slot_accepted(api):
    """PRD §2.7: "Because the interval is half-open, two slots that merely touch — one ending at
    the exact instant the next begins — are permitted."

    Design: Difficulty/resource_temporal_overlap/workshop_halfopen_slot_overlap
    """
    ctx = th.setup_workshop_with_assessed_restoration_and_pending(
        a_start="2026-03-10T09:00:00Z", a_end="2026-03-10T12:00:00Z", second_reported=600,
        cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    # New slot begins at 12:00 — the exact instant the committed [09:00,12:00) slot ends.
    payload = th.assess_restoration_payload(
        ctx["workshop"]["id"], 600, "NORMAL", "2026-03-10T12:00:00Z", "2026-03-10T13:00:00Z"
    )
    rest = th.validate_success(
        api.assess_restoration(ctx["restoration_pending"]["id"], payload, th.TEST_USERS["shop_manager_headers"])
    )
    assert rest["status"] == "ASSESSED", rest


# ---------------------------------------------------------------------------
# Corner: state_machines / assess_restoration_twice_returns_not_requested
# ---------------------------------------------------------------------------
def test_assess_already_assessed_restoration_returns_not_requested(api):
    """PRD §3.8: "A `ShopManager` then assesses the job, which must be `REQUESTED` (otherwise
    `ERR_RESTORATION_NOT_REQUESTED`)".

    Design: Corner/state_machines/assess_restoration_twice_returns_not_requested
    """
    ctx = th.setup_assessed_restoration(
        service_type="CLEANING", reported_area_cm2=400, measured_area_cm2=400, condition="NORMAL",
        a_start="2026-03-10T09:00:00Z", a_end="2026-03-10T10:00:00Z",
        cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    payload = th.assess_restoration_payload(
        ctx["workshop"]["id"], 400, "NORMAL", "2026-03-11T09:00:00Z", "2026-03-11T10:00:00Z"
    )
    resp = api.assess_restoration(ctx["restoration"]["id"], payload, th.TEST_USERS["shop_manager_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_RESTORATION_NOT_REQUESTED.value)


# ---------------------------------------------------------------------------
# Corner: errors / assess_unknown_restoration_returns_not_found
# ---------------------------------------------------------------------------
def test_assess_unknown_restoration_returns_not_found(api):
    """PRD §2.10: "existence is validated left to right, and the first identifier that does not
    resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or
    `ERR_RESTORATION_NOT_FOUND` as appropriate."

    Design: Corner/errors/assess_unknown_restoration_returns_not_found
    """
    payload = th.assess_restoration_payload(
        th.NON_EXISTENT_UUID, 100, "NORMAL", "2026-03-10T09:00:00Z", "2026-03-10T10:00:00Z"
    )
    resp = api.assess_restoration(th.NON_EXISTENT_UUID, payload, th.TEST_USERS["shop_manager_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_RESTORATION_NOT_FOUND.value)
