"""The rental order's two independent state dimensions and the four-column unit
ledger they drive: encumber, commit, release, and the identity that ties them."""
from test_helpers import (
    approve_order,
    as_instant,
    assign_consult,
    create_certified_nurse,
    create_consult,
    create_order,
    create_patient,
    create_surface,
    create_unit,
    deliver_order,
    get_success_data,
    read_unit_version,
    reconcile_order,
    return_order,
    set_clock,
    triage_consult,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_materials_headers


DIRECTOR = make_director_headers()
MATERIALS = make_materials_headers()


def _unit_patient_and_asset(api, cap, mrn, asset_tag, daily_rate_cents, unit_code="7W"):
    """A funded ward, an admitted patient on it and one available rental asset."""
    unit = create_unit(
        api,
        unit_code=unit_code,
        name="Seven West" if unit_code == "7W" else "Three East",
        bed_count=24,
        rental_budget_cap_cents=cap,
    )
    patient = create_patient(
        unit, api=api, mrn=mrn, admitted_at="2026-07-30T00:00:00Z"
    )
    surface = create_surface(
        api,
        asset_tag=asset_tag,
        surface_class="ALTERNATING_PRESSURE",
        daily_rate_cents=daily_rate_cents,
        vendor_name="AirBeds Inc",
    )
    return unit, patient, surface


def _ledger(api, unit_id):
    """The four money columns plus the version, as the server currently holds them."""
    return get_success_data(api.get_unit(unit_id, DIRECTOR))


def test_delivery_moves_one_dimension_and_reconciliation_moves_the_other(api):
    """The intermediate pairs (DELIVERED, ENCUMBERED) and (RETURNED, RECONCILED).

    PRD §3.8: "The order moves `fulfillment_status` `APPROVED → DELIVERED` and
    stores `delivered_at`. The `billing_status` is not touched and remains
    `ENCUMBERED`."
    PRD §3.8: "The order moves `billing_status` `COMMITTED → RECONCILED`,
    `fulfillment_status` is untouched, and no ledger amount moves at all, because
    `rental_committed_cents` already carries `actual_cost_cents` in both of those
    billing states."
    PRD §3.8: "The asset returns to `AVAILABLE` if and only if the logical clock has
    reached `available_from`."

    Design: Difficulty/non_linear_state_machine/order_billing_and_fulfillment_dimensions_advance_independently
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 500000, "MRN-D1", "BED-003", 20000
    )
    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
    )
    assert order["projected_cost_cents"] == 100000, "five tier-1 days at 20000"
    assert order["authorized_cost_cents"] == 105000, "plus a 5 percent fee of 5000"

    approved = approve_order(order, unit, api=api)
    assert approved["fulfillment_status"] == "APPROVED"
    assert approved["billing_status"] == "ENCUMBERED", "approve moves both dimensions"
    after_approve = _ledger(api, unit["id"])
    assert after_approve["rental_encumbered_cents"] == 105000
    assert after_approve["rental_available_cents"] == 395000

    delivered = deliver_order(order, "2026-08-01T00:00:00Z", api=api)
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["billing_status"] == "ENCUMBERED", (
        "the pair (DELIVERED, ENCUMBERED) is only reachable if the dimensions are "
        "genuinely separate"
    )
    assert _ledger(api, unit["id"])["rental_encumbered_cents"] == 105000, (
        "logistics moves no money"
    )

    returned = return_order(order, "2026-08-04T00:00:00Z", api=api)
    assert returned["fulfillment_status"] == "RETURNED"
    assert returned["billing_status"] == "COMMITTED"
    assert returned["actual_cost_cents"] == 63000, (
        "three realised days at 20000 is 60000, plus a 5 percent fee of 3000"
    )
    after_return = _ledger(api, unit["id"])
    assert after_return["rental_encumbered_cents"] == 0
    assert after_return["rental_committed_cents"] == 63000
    assert after_return["rental_released_cents"] == 42000
    assert after_return["rental_available_cents"] == 437000

    set_clock("2026-08-05T00:00:00Z", api=api)
    reconciled = reconcile_order(order, api=api)
    assert reconciled["billing_status"] == "RECONCILED"
    assert reconciled["fulfillment_status"] == "RETURNED", (
        "the pair (RETURNED, RECONCILED) proves reconcile touches dimension two only"
    )
    after_reconcile = _ledger(api, unit["id"])
    assert after_reconcile["rental_committed_cents"] == 63000, "reconcile moves no money"
    assert after_reconcile["rental_available_cents"] == 437000
    assert get_success_data(api.get_support_surface(surface["id"], MATERIALS))["status"] == (
        "AVAILABLE"
    ), "the clock 2026-08-05 is past available_from, which is the return plus 12 hours"


def test_each_dimension_is_separately_filterable_all_the_way_through(api):
    """One row, two independent status axes, and a listing that can see both.

    PRD §3.8: "This transition is the clearest demonstration that the dimensions are
    independent."
    PRD §3.8: "Orders can be listed with `patient_id`, `unit_id`,
    `support_surface_id`, `consult_request_id`, `fulfillment_status` and
    `billing_status` filters, and a single order can be read to inspect
    `billable_days`, `projected_cost_cents`, `vendor_service_fee_cents`,
    `authorized_cost_cents`, `actual_return_at`, `actual_cost_cents`,
    `delivered_at`, `denial_reason`, `requires_director_override` and
    `posture_hold_applied_at`."
    PRD §3.8: "The asset moves to `CLEANING` with `occupied_until` set to
    `actual_return_at` and `available_from` to 12 hours later, and is versioned."

    Design: Difficulty/non_linear_state_machine/order_billing_and_fulfillment_dimensions_advance_independently
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 500000, "MRN-D1", "BED-003", 20000
    )
    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
    )
    approve_order(order, unit, api=api)
    deliver_order(order, "2026-08-01T00:00:00Z", api=api)

    def ids_for(**params):
        rows, _meta = validate_paginated(
            api.list_support_surface_orders(MATERIALS, params)
        )
        return [row["id"] for row in rows]

    assert ids_for(fulfillment_status="DELIVERED") == [order["id"]]
    assert ids_for(billing_status="ENCUMBERED") == [order["id"]], (
        "the same row answers to a mid-flight fulfillment filter and an unmoved "
        "billing filter"
    )
    assert ids_for(fulfillment_status="RETURNED") == []
    assert ids_for(billing_status="COMMITTED") == []

    returned = return_order(order, "2026-08-04T00:00:00Z", api=api)
    assert as_instant(returned["actual_return_at"]) == as_instant("2026-08-04T00:00:00Z")
    assert as_instant(returned["delivered_at"]) == as_instant("2026-08-01T00:00:00Z")
    asset = get_success_data(api.get_support_surface(surface["id"], MATERIALS))
    assert asset["status"] == "CLEANING"
    assert as_instant(asset["occupied_until"]) == as_instant("2026-08-04T00:00:00Z")
    assert as_instant(asset["available_from"]) == as_instant("2026-08-04T12:00:00Z"), "twelve hours of reclean"

    reconcile_order(order, api=api)
    assert ids_for(fulfillment_status="RETURNED") == [order["id"]]
    assert ids_for(billing_status="RECONCILED") == [order["id"]]
    assert ids_for(billing_status="COMMITTED") == [], (
        "the billing axis advanced on its own while the fulfillment axis stood still"
    )
    assert ids_for(fulfillment_status="DELIVERED") == []


def test_an_early_return_splits_the_authorization_without_a_cent_of_drift(api):
    """Committed plus released reproduces the authorization exactly.

    PRD §3.1: "`rental_available_cents` is spendable headroom, recomputed on every
    ledger mutation as `rental_budget_cap_cents` less `rental_encumbered_cents` less
    `rental_committed_cents`; it may be exactly 0 but must never be negative, and
    every path that encumbers money checks it first."
    PRD §3.8: "The unit ledger then settles in one movement: `rental_encumbered_cents`
    falls by the order's `authorized_cost_cents`, `rental_committed_cents` rises by
    the order's `actual_cost_cents`, `rental_released_cents` rises by the amount by
    which `authorized_cost_cents` exceeded `actual_cost_cents` — or by nothing at all
    when the realised cost met or exceeded the authorization, since that release
    figure is never negative — and `rental_available_cents` is recomputed, with the
    unit versioned."

    Design: Difficulty/compensating_invariant/unit_rental_ledger_conserved_across_approve_and_release
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 500000, "MRN-M1", "BED-050", 30000
    )
    opening = _ledger(api, unit["id"])
    assert opening["rental_encumbered_cents"] == 0
    assert opening["rental_committed_cents"] == 0
    assert opening["rental_released_cents"] == 0
    assert opening["rental_available_cents"] == 500000
    assert opening["rental_available_cents"] == (
        opening["rental_budget_cap_cents"]
        - opening["rental_encumbered_cents"]
        - opening["rental_committed_cents"]
    ), "the identity holds before anything is spent"

    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-07T00:00:00Z",
        authorized_days=6,
    )
    assert order["projected_cost_cents"] == 180000, "six tier-1 days at 30000"
    assert order["authorized_cost_cents"] == 189000, "plus a 5 percent fee of 9000"

    approve_order(order, unit, api=api)
    encumbered = _ledger(api, unit["id"])
    assert encumbered["rental_encumbered_cents"] == 189000
    assert encumbered["rental_committed_cents"] == 0
    assert encumbered["rental_released_cents"] == 0
    assert encumbered["rental_available_cents"] == 311000
    assert encumbered["rental_available_cents"] == (
        encumbered["rental_budget_cap_cents"]
        - encumbered["rental_encumbered_cents"]
        - encumbered["rental_committed_cents"]
    )

    deliver_order(order, "2026-08-01T00:00:00Z", api=api)
    delivered_ledger = _ledger(api, unit["id"])
    for column in (
        "rental_encumbered_cents",
        "rental_committed_cents",
        "rental_released_cents",
        "rental_available_cents",
    ):
        assert delivered_ledger[column] == encumbered[column], (
            "logistics moves no money at all"
        )

    returned = return_order(order, "2026-08-05T00:00:00Z", api=api)
    assert returned["actual_cost_cents"] == 126000, (
        "four realised days at 30000 is 120000, plus a 5 percent fee of 6000"
    )
    settled = _ledger(api, unit["id"])
    assert settled["rental_encumbered_cents"] == 0, (
        "the encumbrance is reversed, not left standing and not driven negative"
    )
    assert settled["rental_committed_cents"] == 126000
    assert settled["rental_released_cents"] == 63000
    assert settled["rental_available_cents"] == 374000
    assert settled["rental_available_cents"] == (
        settled["rental_budget_cap_cents"]
        - settled["rental_encumbered_cents"]
        - settled["rental_committed_cents"]
    )
    assert (
        settled["rental_committed_cents"] + settled["rental_released_cents"]
        == order["authorized_cost_cents"]
    ), "126000 plus 63000 is exactly the 189000 that was authorized"
    assert returned["billing_status"] == "COMMITTED"
    assert returned["fulfillment_status"] == "RETURNED"


def test_a_late_return_commits_more_than_was_authorized_and_releases_nothing(api):
    """The release column is a floor at zero, never a negative correction.

    PRD §3.8: "The unit ledger then settles in one movement:
    `rental_encumbered_cents` falls by the order's `authorized_cost_cents`,
    `rental_committed_cents` rises by the order's `actual_cost_cents`,
    `rental_released_cents` rises by the amount by which `authorized_cost_cents`
    exceeded `actual_cost_cents` — or by nothing at all when the realised cost met or
    exceeded the authorization, since that release figure is never negative — and
    `rental_available_cents` is recomputed, with the unit versioned."
    PRD §3.1: "`rental_released_cents` is a lifetime, monotonically non-decreasing
    audit counter of money handed back to the unit by a denial, a consult
    cancellation, or a downward revision at return time; nothing is ever subtracted
    from it."

    Design: Difficulty/compensating_invariant/unit_rental_ledger_conserved_across_approve_and_release
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 500000, "MRN-M1", "BED-050", 30000
    )
    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-07T00:00:00Z",
        authorized_days=6,
    )
    assert order["authorized_cost_cents"] == 189000

    approve_order(order, unit, api=api)
    deliver_order(order, "2026-08-01T00:00:00Z", api=api)

    returned = return_order(order, "2026-08-08T00:00:00Z", api=api)
    assert returned["actual_cost_cents"] == 216300, (
        "seven realised days, all still tier 1, is 210000, and 210000 is at or above "
        "200000 so the fee is 3 percent, namely 6300"
    )
    settled = _ledger(api, unit["id"])
    assert settled["rental_encumbered_cents"] == 0
    assert settled["rental_committed_cents"] == 216300, (
        "the realised cost is committed in full even though it overran the "
        "authorization"
    )
    assert settled["rental_released_cents"] == 0, (
        "the release figure is never negative, so an overrun releases nothing"
    )
    assert settled["rental_available_cents"] == 283700
    assert settled["rental_available_cents"] == (
        settled["rental_budget_cap_cents"]
        - settled["rental_encumbered_cents"]
        - settled["rental_committed_cents"]
    ), "the identity survives an overrun untouched"


def test_a_denied_order_reports_its_state_and_never_its_price(api):
    """Both the state rule and the fiscal rule are violated; only the 409 may show.

    PRD §2.10 rung 12: "The rental order's `fulfillment_status` is a legal starting
    state: approve and deny require `REQUESTED`, deliver requires `APPROVED`, return
    requires `DELIVERED` — `ERR_ORDER_NOT_PENDING` (409), on
    `POST /support-surface-orders/{order_id}/approve`, `/deny`, `/deliver` and
    `/return`."
    PRD §2.10: "This ordering is normative: a request that violates two rules must
    surface the earlier one's code."
    PRD §3.8: "The `billing_status` is left at `UNBILLED`, because nothing was ever
    encumbered — this is not a release, and `rental_released_cents` does not move."

    Design: Difficulty/priority_pair_validation_conflict/order_state_beats_budget_on_approve
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 100000, "MRN-B1", "BED-030", 20000, unit_code="3E"
    )
    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
    )
    assert order["authorized_cost_cents"] == 105000, "100000 projected plus a 5000 fee"
    denied = validate_success(
        api.deny_support_surface_order(
            order["id"], {"denial_reason": "Attending withdrew the request."}, MATERIALS
        )
    )
    assert denied["fulfillment_status"] == "DENIED"
    assert denied["billing_status"] == "UNBILLED"
    unit_version = read_unit_version(unit["id"], api=api)
    assert _ledger(api, unit["id"])["rental_available_cents"] == 100000, (
        "105000 authorized against 100000 available, so the fiscal rule is live too"
    )

    response = api.approve_support_surface_order(
        order["id"], {"expected_unit_version": unit_version}, MATERIALS
    )
    validate_error(response, "ERR_ORDER_NOT_PENDING", expected_status=409)
    assert response.json()["data"]["error_id"] != "ERR_RENTAL_BUDGET_EXCEEDED"
    assert response.status_code != 402, "the fiscal rung must never be reached"

    after = get_success_data(api.get_support_surface_order(order["id"], MATERIALS))
    assert after["fulfillment_status"] == "DENIED"
    assert after["billing_status"] == "UNBILLED"
    ledger = _ledger(api, unit["id"])
    assert ledger["rental_encumbered_cents"] == 0
    assert ledger["rental_available_cents"] == 100000
    assert ledger["rental_released_cents"] == 0
    assert get_success_data(api.get_support_surface(surface["id"], MATERIALS))["status"] == (
        "AVAILABLE"
    )


def test_the_same_price_does_surface_a_payment_required_from_a_pending_order(api):
    """The fiscal rung was never satisfied — it was merely unreachable.

    PRD §2.10 rung 72: "The order's `authorized_cost_cents` does not exceed the
    unit's `rental_available_cents`, and a budget adjustment may not drive
    `rental_available_cents` below zero — `ERR_RENTAL_BUDGET_EXCEEDED` (402), on
    `POST /support-surface-orders/{order_id}/approve` and
    `POST /units/{unit_id}/budget-adjustments`."
    PRD §2.10: "Note in particular rung 12 versus rung 20 on rental approval: an
    order that is no longer `REQUESTED` reports `ERR_ORDER_NOT_PENDING` even when the
    supplied `expected_unit_version` is also stale, and rung 58's override
    requirement is reached only after the version check has passed."

    Design: Difficulty/priority_pair_validation_conflict/order_state_beats_budget_on_approve
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 100000, "MRN-B1", "BED-030", 20000, unit_code="3E"
    )
    twin_surface = create_surface(
        api,
        asset_tag="BED-031",
        surface_class="ALTERNATING_PRESSURE",
        daily_rate_cents=20000,
        vendor_name="AirBeds Inc",
    )
    denied_order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
    )
    pending_order = create_order(
        unit,
        patient,
        twin_surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
    )
    assert denied_order["authorized_cost_cents"] == 105000
    assert pending_order["authorized_cost_cents"] == 105000, "the same price exactly"
    validate_success(
        api.deny_support_surface_order(
            denied_order["id"],
            {"denial_reason": "Attending withdrew the request."},
            MATERIALS,
        )
    )
    unit_version = read_unit_version(unit["id"], api=api)

    validate_error(
        api.approve_support_surface_order(
            denied_order["id"], {"expected_unit_version": unit_version}, MATERIALS
        ),
        "ERR_ORDER_NOT_PENDING",
        expected_status=409,
    )
    validate_error(
        api.approve_support_surface_order(
            pending_order["id"], {"expected_unit_version": unit_version}, MATERIALS
        ),
        "ERR_RENTAL_BUDGET_EXCEEDED",
        expected_status=402,
    )

    ledger = _ledger(api, unit["id"])
    assert ledger["rental_encumbered_cents"] == 0, "neither refusal spent anything"
    assert ledger["rental_available_cents"] == 100000
    assert get_success_data(
        api.get_support_surface_order(pending_order["id"], MATERIALS)
    )["fulfillment_status"] == "REQUESTED", (
        "the affordable-looking order is still pending, so its 402 was about money"
    )


def test_cancelling_the_consult_hands_the_whole_encumbrance_back(api):
    """Three hops running the opposite way to the validation cascade.

    PRD §3.4: "The first hop sets the consult's `status` to `CANCELLED` and, when an
    `assigned_nurse_id` is present, reduces that nurse's `active_consult_load` by 1
    and versions the nurse row."
    PRD §3.4: "The third hop follows from the second: for every order whose billing
    moved to `RELEASED`, that order's unit has its `rental_encumbered_cents` reduced
    by the order's `authorized_cost_cents`, its `rental_released_cents` raised by the
    same `authorized_cost_cents`, its `rental_available_cents` recomputed, and its
    row versioned — the money is returned to headroom and simultaneously written into
    the lifetime release counter."
    PRD §3.3: "`mentored_consult_count` counts the nurse's consults whose `status` is
    `CLOSED`."

    Design: Difficulty/transitive_cascade/cancel_consult_cascades_order_release_to_unit_ledger
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 500000, "MRN-K1", "BED-020", 20000
    )
    nurse = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Partial thickness sacral wound.",
    )
    triage_consult(consult, nurse, api=api)
    assign_consult(consult, nurse, api=api)
    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
        consult_request_id=consult["id"],
    )
    assert order["authorized_cost_cents"] == 105000
    approve_order(order, unit, api=api)
    assert _ledger(api, unit["id"])["rental_encumbered_cents"] == 105000
    assert get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))[
        "active_consult_load"
    ] == 1

    cancelled = validate_success(
        api.cancel_consult_request(
            consult["id"],
            {"reason": "Patient refused the specialty surface and the consult."},
            DIRECTOR,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    nurse_after = get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))
    assert nurse_after["active_consult_load"] == 0
    assert nurse_after["mentored_consult_count"] == 0, (
        "a cancel is not a completed consult"
    )

    order_after = get_success_data(api.get_support_surface_order(order["id"], MATERIALS))
    assert order_after["billing_status"] == "RELEASED"
    assert order_after["fulfillment_status"] == "APPROVED", (
        "only orders still at REQUESTED are denied, and this one was already approved"
    )
    ledger = _ledger(api, unit["id"])
    assert ledger["rental_encumbered_cents"] == 0
    assert ledger["rental_released_cents"] == 105000
    assert ledger["rental_committed_cents"] == 0
    assert ledger["rental_available_cents"] == 500000
    assert get_success_data(api.get_support_surface(surface["id"], MATERIALS))["status"] == (
        "IN_USE"
    ), "the cascade releases money but does not reclaim the physical asset"
    assert get_success_data(api.get_patient(patient["id"], DIRECTOR))[
        "pending_outpatient_followup_count"
    ] == 0


def test_the_release_cascade_only_reaches_orders_naming_that_consult(api):
    """Two encumbrances on one ledger, one of them out of the cascade's reach.

    PRD §3.4: "The second hop follows from the cancellation: every rental order that
    names this consult in its `consult_request_id` and whose `billing_status` is
    `ENCUMBERED` has its `billing_status` moved `ENCUMBERED → RELEASED`, and every
    such order whose `fulfillment_status` is still `REQUESTED` additionally moves
    `REQUESTED → DENIED` with its `denial_reason` recorded as the literal string
    `CONSULT_CANCELLED`; each affected order row is versioned."
    PRD §3.8: "Together the encumber, commit, release and reconcile movements conserve
    the unit's money: what leaves `rental_encumbered_cents` always arrives either in
    `rental_committed_cents` or in `rental_released_cents`, and
    `rental_available_cents` always equals the cap less the encumbered and committed
    sums."

    Design: Difficulty/transitive_cascade/cancel_consult_cascades_order_release_to_unit_ledger
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 500000, "MRN-K1", "BED-020", 20000
    )
    unlinked_surface = create_surface(
        api,
        asset_tag="BED-021",
        surface_class="ALTERNATING_PRESSURE",
        daily_rate_cents=20000,
        vendor_name="AirBeds Inc",
    )
    nurse = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Partial thickness sacral wound.",
    )
    triage_consult(consult, nurse, api=api)
    assign_consult(consult, nurse, api=api)

    linked = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
        consult_request_id=consult["id"],
    )
    unlinked = create_order(
        unit,
        patient,
        unlinked_surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
    )
    assert unlinked["consult_request_id"] is None
    approve_order(linked, unit, api=api)
    approve_order(unlinked, unit, api=api)
    assert _ledger(api, unit["id"])["rental_encumbered_cents"] == 210000

    validate_success(
        api.cancel_consult_request(
            consult["id"], {"reason": "Family declined all specialty support."}, DIRECTOR
        )
    )

    assert get_success_data(api.get_support_surface_order(linked["id"], MATERIALS))[
        "billing_status"
    ] == "RELEASED"
    survivor = get_success_data(api.get_support_surface_order(unlinked["id"], MATERIALS))
    assert survivor["billing_status"] == "ENCUMBERED", (
        "an order that names no consult is outside the cascade's reach"
    )
    assert survivor["fulfillment_status"] == "APPROVED"

    ledger = _ledger(api, unit["id"])
    assert ledger["rental_encumbered_cents"] == 105000, "exactly one authorization left"
    assert ledger["rental_released_cents"] == 105000
    assert ledger["rental_committed_cents"] == 0
    assert ledger["rental_available_cents"] == 395000
    assert ledger["rental_available_cents"] == (
        ledger["rental_budget_cap_cents"]
        - ledger["rental_encumbered_cents"]
        - ledger["rental_committed_cents"]
    )


def test_reconciliation_is_guarded_on_billing_alone_at_every_step(api):
    """Fulfillment progress does not buy passage through the billing guard.

    PRD §3.8: "The order's `billing_status` must be `COMMITTED` — anything else,
    whether still `UNBILLED` or `ENCUMBERED`, or already terminal at `RELEASED` or
    `RECONCILED`, is refused with `ERR_ORDER_INVALID_BILLING_STATE` — and its
    `fulfillment_status` must be `RETURNED`."
    PRD §2.10 rung 13: "The rental order's `billing_status` is a legal starting state
    for the requested billing transition: reconcile requires `COMMITTED` —
    `ERR_ORDER_INVALID_BILLING_STATE` (409), on
    `POST /support-surface-orders/{order_id}/reconcile`."

    Design: Corner/state_machines/reconcile_before_return_rejected_on_billing_dimension
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 500000, "MRN-H1", "BED-081", 10000, unit_code="3E"
    )
    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-04T00:00:00Z",
        authorized_days=3,
    )
    assert order["projected_cost_cents"] == 30000, "three tier-1 days at 10000"
    assert order["authorized_cost_cents"] == 32400, (
        "30000 is below 50000, so the fee is 8 percent, namely 2400"
    )
    approve_order(order, unit, api=api)

    validate_error(
        api.reconcile_support_surface_order(order["id"], {}, MATERIALS),
        "ERR_ORDER_INVALID_BILLING_STATE",
        expected_status=409,
    )

    deliver_order(order, "2026-08-01T00:00:00Z", api=api)
    validate_error(
        api.reconcile_support_surface_order(order["id"], {}, MATERIALS),
        "ERR_ORDER_INVALID_BILLING_STATE",
        expected_status=409,
    )

    returned = return_order(order, "2026-08-04T00:00:00Z", api=api)
    assert returned["fulfillment_status"] == "RETURNED"
    assert returned["billing_status"] == "COMMITTED"
    assert returned["actual_cost_cents"] == 32400, "the realised span matched the plan"

    reconciled = validate_success(
        api.reconcile_support_surface_order(order["id"], {}, MATERIALS)
    )
    assert reconciled["billing_status"] == "RECONCILED"
    assert reconciled["fulfillment_status"] == "RETURNED"
    ledger = _ledger(api, unit["id"])
    assert ledger["rental_encumbered_cents"] == 0
    assert ledger["rental_committed_cents"] == 32400
    assert ledger["rental_released_cents"] == 0
    assert ledger["rental_available_cents"] == 467600
    assert get_success_data(api.get_support_surface(surface["id"], MATERIALS))["status"] == (
        "CLEANING"
    ), "the clock is still 2026-08-01, well before available_from 2026-08-04T12:00:00Z"


def test_forty_nine_hours_needs_three_authorized_days_and_three_is_enough(api):
    """The day count comes from the interval and the comparison is not strict.

    PRD §2.10 rung 70: "The order's computed `billable_days` does not exceed its
    `authorized_days` — `ERR_RENTAL_DAYS_EXCEED_AUTHORIZATION` (422), on
    `POST /support-surface-orders/{order_id}/approve`."
    PRD §3.8: "Orders in `REQUESTED`, `RETURNED` or `DENIED` do not block anything."
    PRD §3.8: "`authorized_days` is what the unit has agreed to pay for, at least 1
    and at most 120."

    Design: Corner/validations/rental_days_exceeding_authorization_rejected_then_passes_at_equality
    """
    unit, patient, surface = _unit_patient_and_asset(
        api, 200000, "MRN-Y1", "BED-202", 10000, unit_code="3E"
    )
    under_authorized = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-03T01:00:00Z",
        authorized_days=2,
    )
    exactly_authorized = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-03T01:00:00Z",
        authorized_days=3,
    )
    assert under_authorized["billable_days"] == 3
    assert exactly_authorized["billable_days"] == 3, (
        "the day count comes from the 49-hour interval, never from authorized_days"
    )
    unit_version = read_unit_version(unit["id"], api=api)

    validate_error(
        api.approve_support_surface_order(
            under_authorized["id"], {"expected_unit_version": unit_version}, MATERIALS
        ),
        "ERR_RENTAL_DAYS_EXCEED_AUTHORIZATION",
        expected_status=422,
    )
    assert get_success_data(
        api.get_support_surface_order(under_authorized["id"], MATERIALS)
    )["fulfillment_status"] == "REQUESTED"
    refused_ledger = _ledger(api, unit["id"])
    assert refused_ledger["rental_encumbered_cents"] == 0
    assert refused_ledger["version"] == unit_version, (
        "the refusal did not version the unit, so the token is still current"
    )

    approved = validate_success(
        api.approve_support_surface_order(
            exactly_authorized["id"], {"expected_unit_version": unit_version}, MATERIALS
        )
    )
    assert approved["fulfillment_status"] == "APPROVED", "3 does not exceed 3"
    ledger = _ledger(api, unit["id"])
    assert ledger["rental_encumbered_cents"] == 32400
    assert ledger["rental_available_cents"] == 167600
    assert get_success_data(api.get_support_surface(surface["id"], MATERIALS))["status"] == (
        "IN_USE"
    ), (
        "the two orders share one asset and one interval, yet no contention arose, "
        "because the refused order never left REQUESTED"
    )


def test_the_ceiling_is_the_headroom_and_it_guards_the_cap_from_both_sides(api):
    """Two individually affordable orders, one cap, and a one-cent sweep attempt.

    PRD §2.10 rung 72: "The order's `authorized_cost_cents` does not exceed the
    unit's `rental_available_cents`, and a budget adjustment may not drive
    `rental_available_cents` below zero — `ERR_RENTAL_BUDGET_EXCEEDED` (402), on
    `POST /support-surface-orders/{order_id}/approve` and
    `POST /units/{unit_id}/budget-adjustments`."
    PRD §3.1: "The adjustment adds `delta_cents` to `rental_budget_cap_cents` — a
    negative delta lowers the cap — and then recomputes `rental_available_cents`. An
    adjustment that would drive `rental_available_cents` below zero, because the unit
    has already encumbered or committed more than the reduced cap, is refused with
    `ERR_RENTAL_BUDGET_EXCEEDED` and leaves the cap untouched."

    Design: Corner/validations/budget_ceiling_passes_at_equality_then_rejects_order_and_negative_adjustment
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=52920,
    )
    patient = create_patient(
        unit, api=api, mrn="MRN-Z1", admitted_at="2026-07-31T00:00:00Z"
    )
    first_asset, second_asset = (
        create_surface(
            api,
            asset_tag=asset_tag,
            surface_class="FOAM_OVERLAY",
            daily_rate_cents=7000,
            vendor_name="AirBeds Inc",
        )
        for asset_tag in ("BED-203", "BED-204")
    )
    first_order, second_order = (
        create_order(
            unit,
            patient,
            asset,
            api=api,
            rental_start="2026-08-01T00:00:00Z",
            rental_end="2026-08-08T00:00:00Z",
            authorized_days=7,
        )
        for asset in (first_asset, second_asset)
    )
    assert first_order["authorized_cost_cents"] == 52920
    assert second_order["authorized_cost_cents"] == 52920

    first_version = read_unit_version(unit["id"], api=api)
    approved = validate_success(
        api.approve_support_surface_order(
            first_order["id"], {"expected_unit_version": first_version}, MATERIALS
        )
    )
    assert approved["fulfillment_status"] == "APPROVED", (
        "52920 does not exceed an available 52920, so equality passes"
    )
    spent = _ledger(api, unit["id"])
    assert spent["rental_encumbered_cents"] == 52920
    assert spent["rental_available_cents"] == 0, "headroom may sit at exactly zero"

    second_version = spent["version"]
    validate_error(
        api.approve_support_surface_order(
            second_order["id"], {"expected_unit_version": second_version}, MATERIALS
        ),
        "ERR_RENTAL_BUDGET_EXCEEDED",
        expected_status=402,
    )
    assert get_success_data(
        api.get_support_surface_order(second_order["id"], MATERIALS)
    )["fulfillment_status"] == "REQUESTED"
    assert get_success_data(api.get_support_surface(second_asset["id"], MATERIALS))[
        "status"
    ] == "AVAILABLE"
    assert _ledger(api, unit["id"])["version"] == second_version

    validate_error(
        api.create_budget_adjustment(
            unit["id"],
            {
                "delta_cents": -1,
                "reason": "Attempt to sweep one cent out of a fully encumbered ledger.",
            },
            DIRECTOR,
        ),
        "ERR_RENTAL_BUDGET_EXCEEDED",
        expected_status=402,
    )
    assert _ledger(api, unit["id"])["rental_budget_cap_cents"] == 52920, (
        "the refused adjustment left the cap untouched"
    )

    raised = validate_success(
        api.create_budget_adjustment(
            unit["id"],
            {"delta_cents": 52920, "reason": "Second specialty bed approved by finance."},
            DIRECTOR,
        )
    )
    assert raised["rental_budget_cap_cents"] == 105840
    assert raised["rental_available_cents"] == 52920

    third_version = read_unit_version(unit["id"], api=api)
    finally_approved = validate_success(
        api.approve_support_surface_order(
            second_order["id"], {"expected_unit_version": third_version}, MATERIALS
        )
    )
    assert finally_approved["fulfillment_status"] == "APPROVED", (
        "the order itself was never the problem"
    )
    assert finally_approved["billing_status"] == "ENCUMBERED"
    assert finally_approved["authorized_cost_cents"] == 52920
    final = _ledger(api, unit["id"])
    assert final["rental_encumbered_cents"] == 105840
    assert final["rental_available_cents"] == 0


def test_the_second_approver_must_re_read_the_ledger_before_committing(api):
    """Nothing but the optimistic-concurrency token stands between these two orders.

    PRD §2.6: "Approving a support surface rental order requires a non-optional
    `expected_unit_version` field in the payload, carrying the `version` the client
    last observed on the unit whose rental ledger will be charged. If it does not
    equal that unit's current `version`, the approval is rejected with
    `ERR_STALE_UNIT_VERSION` (HTTP 412)."
    PRD §2.6: "Two distinct requested orders on the same unit each satisfy every
    state precondition on their own and each would appear affordable against the
    ledger the client read; this check forces the second approver to re-read
    `rental_available_cents` before committing more of the same budget."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_unit_version_on_approve_rejected_then_accepted_after_reread
    """
    unit = create_unit(
        api,
        unit_code="OCC-U2",
        name="OCC Probe Surgical",
        bed_count=24,
        rental_budget_cap_cents=200000,
    )
    patient = create_patient(
        unit,
        api=api,
        mrn="OCCMRN0002",
        admitted_at="2026-07-31T00:00:00Z",
        comorbidity_count=1,
        device_related_risk=False,
        ostomy_present=False,
    )
    first_asset, second_asset = (
        create_surface(
            api,
            asset_tag=asset_tag,
            surface_class="ALTERNATING_PRESSURE",
            daily_rate_cents=10000,
            vendor_name="Probe Rentals",
        )
        for asset_tag in ("OCC-S1", "OCC-S2")
    )
    first_order, second_order = (
        create_order(
            unit,
            patient,
            asset,
            api=api,
            rental_start="2026-08-02T00:00:00Z",
            rental_end="2026-08-05T00:00:00Z",
            authorized_days=3,
        )
        for asset in (first_asset, second_asset)
    )
    assert first_order["authorized_cost_cents"] == 32400
    assert second_order["authorized_cost_cents"] == 32400

    stale_token = read_unit_version(unit["id"], api=api)
    first_approved = validate_success(
        api.approve_support_surface_order(
            first_order["id"], {"expected_unit_version": stale_token}, MATERIALS
        )
    )
    assert first_approved["fulfillment_status"] == "APPROVED"
    assert first_approved["billing_status"] == "ENCUMBERED"
    assert get_success_data(api.get_support_surface(first_asset["id"], MATERIALS))[
        "status"
    ] == "IN_USE"
    after_first = _ledger(api, unit["id"])
    assert after_first["rental_encumbered_cents"] == 32400
    assert after_first["rental_committed_cents"] == 0
    assert after_first["rental_released_cents"] == 0
    assert after_first["rental_available_cents"] == 167600
    assert after_first["version"] == stale_token + 1

    validate_error(
        api.approve_support_surface_order(
            second_order["id"], {"expected_unit_version": stale_token}, MATERIALS
        ),
        "ERR_STALE_UNIT_VERSION",
        expected_status=412,
    )
    refused = get_success_data(
        api.get_support_surface_order(second_order["id"], MATERIALS)
    )
    assert refused["fulfillment_status"] == "REQUESTED", (
        "167600 of headroom against 32400 authorized, so only the token could refuse it"
    )
    assert refused["billing_status"] == "UNBILLED"
    assert get_success_data(api.get_support_surface(second_asset["id"], MATERIALS))[
        "status"
    ] == "AVAILABLE"
    unchanged = _ledger(api, unit["id"])
    assert unchanged["rental_encumbered_cents"] == 32400
    assert unchanged["version"] == stale_token + 1

    fresh_token = read_unit_version(unit["id"], api=api)
    assert fresh_token == stale_token + 1
    second_approved = validate_success(
        api.approve_support_surface_order(
            second_order["id"], {"expected_unit_version": fresh_token}, MATERIALS
        )
    )
    assert second_approved["fulfillment_status"] == "APPROVED"
    assert second_approved["billing_status"] == "ENCUMBERED"
    assert get_success_data(api.get_support_surface(second_asset["id"], MATERIALS))[
        "status"
    ] == "IN_USE"
    final = _ledger(api, unit["id"])
    assert final["rental_encumbered_cents"] == 64800
    assert final["rental_available_cents"] == 135200
    assert final["version"] == stale_token + 2, (
        "one bump per accepted approve and none for the refused one"
    )
