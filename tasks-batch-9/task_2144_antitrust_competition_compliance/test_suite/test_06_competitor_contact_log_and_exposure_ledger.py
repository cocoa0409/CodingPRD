"""The competitor contact log: how a contact is priced, how the remediation
cycle turns, and how clearing and escalating move the unit's exposure ledger.
"""
from test_helpers import (
    COUNSEL, ApiErrorId, adjust_exposure, assert_contact,
    assert_exposure_ledger_identity, contact_clearance_payload,
    contact_escalation_payload, create_contact_payload, create_trained_employee,
    log_contact, make_counsel_headers, make_employee_headers,
    open_contact_review, order_remediation, read_business_unit, read_contact,
    register_business_unit, register_employee, respond_remediation,
    run_assessment, set_clock, validate_error, validate_paginated,
    validate_success,
)

SEVERE_UNIT = {
    "name": "Coatings North America",
    "market_code": "NA-COAT",
    "market_share_bps": 5000,
    "interaction_point_count": 2,
    "competitor_overlap_pct": 10,
    "exposure_budget_points": 200,
}

HEAVY_CONTACT = {
    "competitor_name": "Novamer GmbH",
    "contact_channel": "IN_PERSON_UNSTRUCTURED",
    "topic_tags": ["CUSTOMER_ALLOCATION", "BID", "BENCHMARKING"],
    "pricing_topic": True,
    "occurred_at": "2026-07-28T15:30:00Z",
}


def _severe_band_unit_with_pricing_delegate():
    unit = register_business_unit(**SEVERE_UNIT)
    trained = create_trained_employee(
        unit["id"], role_category="PRICING",
        code="AT-PRICE-101",
        title="Pricing Communications and Competition Law",
        target_role_categories=["SALES", "PRICING"], duration_minutes=90,
        validity_days=365, is_mandatory=True)
    assessment = run_assessment(unit["id"], "BASELINE")
    return unit, trained["employee"], assessment


def test_contact_raw_score_cap_applies_before_the_band_multiplier(api):
    """PRD §3.6: "The summed raw score is then capped at 20 — and this cap
    applies to the raw sum **before** the band multiplier, never after. Only
    then is the unit's band multiplier applied: 1.0 at `LOW`, 1.25 at
    `MODERATE`, 1.5 at `HIGH`, 2.0 at `SEVERE`."
    PRD §3.6: "Topic-tag points are summed — 2 for `CAPACITY`, 2 for `BID`, 3
    for `CUSTOMER_ALLOCATION`, 3 for `TERRITORY`, 0 for `STANDARDS`, and 1 for
    `BENCHMARKING` — and that sum alone is capped at 5, with an empty tag array
    contributing 0."
    PRD §3.6: "If `pricing_topic` is true, 6 further points are added — the
    single largest raw term, because pricing conversation is the conduct the
    programme most wants surfaced."

    Design: Difficulty/combinatorial_formula/contact_exposure_nonlinear_stack_with_pre_multiplier_cap
    """
    set_clock()
    unit, employee, assessment = _severe_band_unit_with_pricing_delegate()
    assert assessment["market_risk_index"] == 78.00
    assert assessment["risk_band"] == "SEVERE"

    data = validate_success(api.create_contact(
        create_contact_payload(unit["id"], employee["id"], **HEAVY_CONTACT),
        make_employee_headers(employee["id"])), 201)

    assert_contact(data)
    assert data["exposure_points_charged"] == 40.00, (
        "the 21-point raw sum is capped at 20 and only then doubled")


def test_band_multiplier_in_force_at_log_time_is_frozen_onto_the_contact(api):
    """PRD §3.6: "The multiplier in force at log time is frozen onto the contact
    as `band_multiplier_applied`, and the product, rounded half up to 2 decimal
    places, becomes the contact's `exposure_points_charged`."
    PRD §3.6: "On success the contact is stored, the unit's ledger is
    recomputed, posture is recomputed, and the unit's `version` increments by
    1."
    PRD §2.8: "Both thresholds are inclusive at the lower edge: a ledger reading
    of exactly 40.00 is `RESTRICTED`, and exactly 80.00 is `FROZEN`."

    Design: Difficulty/combinatorial_formula/contact_exposure_nonlinear_stack_with_pre_multiplier_cap
    """
    set_clock()
    unit, employee, _assessment = _severe_band_unit_with_pricing_delegate()

    data = validate_success(api.create_contact(
        create_contact_payload(unit["id"], employee["id"], **HEAVY_CONTACT),
        make_employee_headers(employee["id"])), 201)

    assert data["band_multiplier_applied"] == 2.0

    stored_unit = read_business_unit(unit["id"])
    assert stored_unit["exposure_points"] == 40.00
    assert stored_unit["posture"] == "RESTRICTED"


def test_remediation_cycle_repeats_and_overwrites_the_response(api):
    """PRD §3.6: "From `UNDER_REVIEW`, counsel may order remediation, supplying
    `instructions` that land in `remediation_instructions` and moving the
    contact to `REMEDIATION_REQUIRED`. The employee — and only the employee who
    logged it — answers with a `response` recorded into `remediation_response`,
    moving `REMEDIATION_REQUIRED → UNDER_REVIEW` again. That loop `UNDER_REVIEW
    → REMEDIATION_REQUIRED → UNDER_REVIEW` may repeat as many times as counsel
    needs."

    Design: Difficulty/non_linear_state_machine/competitor_contact_remediation_revision_cycle
    """
    set_clock()
    unit = register_business_unit()
    employee = register_employee(unit["id"], role_category="LEGAL")
    contact = log_contact(unit["id"], employee["id"], competitor_name="Rivex SA",
                          contact_channel="WRITTEN_FORMAL", topic_tags=["STANDARDS"])
    open_contact_review(contact["id"])

    first_order = order_remediation(
        contact["id"], "Produce the full written thread and the distribution list")
    assert first_order["status"] == "REMEDIATION_REQUIRED"
    respond_remediation(contact["id"], employee["id"],
                        "Thread attached; distribution list pending")
    second_order = order_remediation(
        contact["id"], "Distribution list still missing - resubmit")
    assert second_order["status"] == "REMEDIATION_REQUIRED", (
        "the loop may repeat as many times as counsel needs")
    second_response = respond_remediation(
        contact["id"], employee["id"],
        "Distribution list attached - four internal recipients only")

    assert second_response["status"] == "UNDER_REVIEW"
    assert second_response["remediation_response"] == (
        "Distribution list attached - four internal recipients only")


def test_clearing_after_two_remediation_rounds_zeroes_the_charge(api):
    """PRD §3.6: "Clearing, which takes `notes`, moves `UNDER_REVIEW → CLEARED`
    and compensates in full: the contact's `exposure_points_charged` is
    subtracted from the unit's ledger, the charge itself is reset to 0.00, the
    unit's `version` increments by 1, and posture is recomputed — which may thaw
    a frozen unit down to `RESTRICTED` or `OPEN`."

    Design: Difficulty/non_linear_state_machine/competitor_contact_remediation_revision_cycle
    """
    set_clock()
    unit = register_business_unit()
    employee = register_employee(unit["id"], role_category="LEGAL")
    contact = log_contact(unit["id"], employee["id"], competitor_name="Rivex SA",
                          contact_channel="WRITTEN_FORMAL", topic_tags=["STANDARDS"])
    open_contact_review(contact["id"])
    order_remediation(contact["id"], "Produce the full written thread")
    respond_remediation(contact["id"], employee["id"], "Thread attached")
    order_remediation(contact["id"], "Distribution list still missing - resubmit")
    respond_remediation(contact["id"], employee["id"], "Distribution list attached")

    data = validate_success(api.clear_contact(
        contact["id"],
        contact_clearance_payload("No competitively sensitive content"), COUNSEL))

    assert data["status"] == "CLEARED"
    assert data["exposure_points_charged"] == 0.00
    stored_unit = read_business_unit(unit["id"])
    assert stored_unit["exposure_points"] == 0.00
    assert stored_unit["posture"] == "OPEN"


def test_logging_a_contact_adds_its_charge_on_top_of_the_adjusted_ledger(api):
    """PRD §2.8: "Each business unit carries a running antitrust exposure ledger
    in `exposure_points`."
    PRD §2.8: "The unit's `manual_exposure_adjustment_points`, which is itself
    the running sum of every `points_delta` the service has accepted on that
    unit."
    PRD §3.6: "Channel points follow: 3 for an unstructured in-person meeting, 2
    for a trade show, 1 for a phone call, 1 for an email, and 0 for formal
    written correspondence."

    Design: Difficulty/compensating_invariant/contact_clearance_restores_exposure_points_exactly
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=200)
    employee = register_employee(unit["id"], role_category="LEGAL")
    adjust_exposure(unit["id"], 12,
                    "Opening balance carried over from the legacy register")

    data = validate_success(api.create_contact(
        create_contact_payload(unit["id"], employee["id"],
                               contact_channel="TRADE_SHOW",
                               topic_tags=["CAPACITY"]),
        make_employee_headers(employee["id"])), 201)

    assert data["exposure_points_charged"] == 8.00
    stored_unit = read_business_unit(unit["id"])
    assert stored_unit["exposure_points"] == 20.00
    assert stored_unit["manual_exposure_adjustment_points"] == 12.00


def test_clearing_a_contact_restores_the_ledger_with_no_drift(api):
    """PRD §2.8: "Its value is the sum of three terms, rounded half up to 2
    decimal places and then floored at 0.00 so it can never go negative:"
    PRD §2.8: "Because the adjustment total is kept as its own running sum
    rather than folded into the ledger, the identity closes exactly and no drift
    accumulates across recomputations."
    PRD §3.6: "Clearing, which takes `notes`, moves `UNDER_REVIEW → CLEARED` and
    compensates in full: the contact's `exposure_points_charged` is subtracted
    from the unit's ledger, the charge itself is reset to 0.00, the unit's
    `version` increments by 1, and posture is recomputed — which may thaw a
    frozen unit down to `RESTRICTED` or `OPEN`."

    Design: Difficulty/compensating_invariant/contact_clearance_restores_exposure_points_exactly
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=200)
    employee = register_employee(unit["id"], role_category="LEGAL")
    adjust_exposure(unit["id"], 12,
                    "Opening balance carried over from the legacy register")
    contact = log_contact(unit["id"], employee["id"],
                          contact_channel="TRADE_SHOW", topic_tags=["CAPACITY"])
    open_contact_review(contact["id"])

    cleared = validate_success(api.clear_contact(
        contact["id"],
        contact_clearance_payload(
            "Booth conversation was confined to published capacity data"),
        COUNSEL))

    assert cleared["status"] == "CLEARED"
    assert cleared["exposure_points_charged"] == 0.00
    stored_unit = read_business_unit(unit["id"])
    assert stored_unit["exposure_points"] == 12.00
    assert stored_unit["manual_exposure_adjustment_points"] == 12.00
    assert stored_unit["posture"] == "OPEN"
    assert_exposure_ledger_identity(stored_unit, [read_contact(contact["id"])], [])


def test_a_newly_logged_contact_opens_in_logged_and_is_priced_at_once(api):
    """PRD §3.6: "The contact opens in `LOGGED`."
    PRD §3.6: "The log is priced immediately, once, at log time. The raw score
    starts at a base of 4 points."
    PRD §3.6: "Role points close the raw score: 2 for a `SALES` employee, 3 for
    `PRICING`, 0 for `LEGAL`, and 1 for `OTHER`."

    Design: Corner/state_machines/competitor_contact_initial_state_is_logged
    """
    set_clock()
    unit = register_business_unit()
    employee = register_employee(unit["id"], role_category="LEGAL")

    data = validate_success(api.create_contact(
        create_contact_payload(unit["id"], employee["id"]),
        make_employee_headers(employee["id"])), 201)

    assert_contact(data)
    assert data["status"] == "LOGGED"
    assert data["exposure_points_charged"] == 5.00, "base 4 plus 1 for an email"
    assert data["band_multiplier_applied"] == 1.0
    assert read_business_unit(unit["id"])["exposure_points"] == 5.00


def test_clearing_a_contact_that_is_still_logged_is_rejected(api):
    """PRD §3.6: "Two terminal outcomes end the cycle, and they are financial
    opposites. Clearing, which takes `notes`, moves `UNDER_REVIEW → CLEARED` and
    compensates in full: the contact's `exposure_points_charged` is subtracted
    from the unit's ledger, the charge itself is reset to 0.00, the unit's
    `version` increments by 1, and posture is recomputed — which may thaw a
    frozen unit down to `RESTRICTED` or `OPEN`."
    PRD §2.7: "**Transition legality.** The target resource is in a state from
    which the requested transition is declared — otherwise `ERR_INVALID_STATE`,
    HTTP 409. Applies to every transition endpoint, and covers every attempt
    from a terminal state and every repeat of an already-applied transition."

    Design: Corner/state_machines/competitor_contact_clearance_from_logged_state_is_rejected
    """
    set_clock()
    unit = register_business_unit()
    employee = register_employee(unit["id"], role_category="LEGAL")
    contact = log_contact(unit["id"], employee["id"])

    resp = api.clear_contact(
        contact["id"], contact_clearance_payload("Nothing to see here"), COUNSEL)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409
    stored = read_contact(contact["id"])
    assert stored["status"] == "LOGGED"
    assert stored["exposure_points_charged"] == 5.00
    assert read_business_unit(unit["id"])["exposure_points"] == 5.00


def test_second_escalation_is_rejected_and_never_doubles_the_charge_twice(api):
    """PRD §3.6: "Escalating, which takes a `reason`, moves `UNDER_REVIEW →
    ESCALATED` and does the reverse. The surcharge is the contact's current
    `exposure_points_charged` multiplied by one less than the escalation
    multiplier of 2.0 — in other words, an amount equal to the existing charge,
    rounded half up to 2 decimal places — added to `exposure_points_charged` so
    the charge is doubled, and added to the unit's ledger, with the unit's
    `version` incrementing by 1."
    PRD §2.7: "**Transition legality.** The target resource is in a state from
    which the requested transition is declared — otherwise `ERR_INVALID_STATE`,
    HTTP 409. Applies to every transition endpoint, and covers every attempt
    from a terminal state and every repeat of an already-applied transition."

    Design: Corner/state_machines/competitor_contact_second_escalation_is_rejected_as_idempotency_guard
    """
    set_clock()
    unit = register_business_unit()
    employee = register_employee(unit["id"], role_category="LEGAL")
    contact = log_contact(unit["id"], employee["id"])
    open_contact_review(contact["id"])
    escalated = validate_success(api.escalate_contact(
        contact["id"],
        contact_escalation_payload(
            "Email thread shows a discount coordination attempt"),
        COUNSEL))
    assert escalated["exposure_points_charged"] == 10.00

    resp = api.escalate_contact(
        contact["id"], contact_escalation_payload("Escalating again by mistake"),
        COUNSEL)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409
    assert read_contact(contact["id"])["exposure_points_charged"] == 10.00
    assert read_business_unit(unit["id"])["exposure_points"] == 10.00


def test_cleared_contacts_leave_the_ledger_input_set(api):
    """PRD §2.8: "The sum of `exposure_points_charged` over the unit's
    competitor contacts whose `status` is `LOGGED`, `UNDER_REVIEW`,
    `REMEDIATION_REQUIRED` or `ESCALATED`. Contacts in `CLEARED` are excluded,
    and because clearing a contact also zeroes its own charge, a cleared contact
    drops out of the sum from both directions."

    Design: Corner/calculations/exposure_ledger_excludes_cleared_contacts_from_the_running_sum
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=200)
    employee = register_employee(unit["id"], role_category="LEGAL")
    c1 = log_contact(unit["id"], employee["id"], competitor_name="Rivex SA")
    c2 = log_contact(unit["id"], employee["id"], competitor_name="Novamer GmbH",
                     occurred_at="2026-07-21T10:00:00Z")
    c3 = log_contact(unit["id"], employee["id"], competitor_name="Kelmar BV",
                     occurred_at="2026-07-22T10:00:00Z")
    open_contact_review(c2["id"])
    assert read_business_unit(unit["id"])["exposure_points"] == 15.00

    cleared = validate_success(api.clear_contact(
        c2["id"], contact_clearance_payload("Routine supplier logistics only"),
        COUNSEL))

    assert cleared["status"] == "CLEARED"
    assert cleared["exposure_points_charged"] == 0.00
    assert read_contact(c1["id"])["exposure_points_charged"] == 5.00
    assert read_contact(c3["id"])["exposure_points_charged"] == 5.00
    assert read_business_unit(unit["id"])["exposure_points"] == 10.00


def test_contact_that_would_breach_the_exposure_budget_is_refused(api):
    """PRD §3.6: "Before the contact is accepted, the service checks that the
    unit's `exposure_points` plus this contact's computed charge would stay
    within `exposure_budget_points`; if it would not, the log is refused with
    `ERR_EXPOSURE_BUDGET_EXCEEDED` and nothing is written."
    PRD §2.7: "**Exposure budget.** The unit's `exposure_points` plus the points
    this contact would be charged is no greater than the unit's
    `exposure_budget_points` — otherwise `ERR_EXPOSURE_BUDGET_EXCEEDED`, HTTP
    422."

    Design: Corner/validations/contact_log_exceeding_exposure_budget_is_refused
    """
    set_clock()
    unit = register_business_unit(name="Tiny Budget Unit", market_code="EU-TINY",
                                  exposure_budget_points=10)
    employee = register_employee(unit["id"], role_category="LEGAL")
    log_contact(unit["id"], employee["id"], competitor_name="Rivex SA")

    second = validate_success(api.create_contact(
        create_contact_payload(unit["id"], employee["id"],
                               competitor_name="Novamer GmbH",
                               occurred_at="2026-07-21T10:00:00Z"),
        make_employee_headers(employee["id"])), 201)
    assert second["exposure_points_charged"] == 5.00, (
        "a ledger landing on exactly the budget is still within it")
    assert read_business_unit(unit["id"])["exposure_points"] == 10.00

    third = api.create_contact(
        create_contact_payload(unit["id"], employee["id"],
                               competitor_name="Kelmar BV",
                               occurred_at="2026-07-22T10:00:00Z"),
        make_employee_headers(employee["id"]))
    validate_error(third, ApiErrorId.ERR_EXPOSURE_BUDGET_EXCEEDED.value)
    assert third.status_code == 422

    _rows, meta = validate_paginated(api.list_contacts(
        COUNSEL, params={"business_unit_id": unit["id"]}))
    assert meta["total_count"] == 2, "the refused log writes nothing"


def test_contact_list_status_filter_narrows_the_result_set(api):
    """PRD §3.6: "Contacts may be listed filtered by unit, employee and
    `status`."
    PRD §2.3: "Filter query parameters are documented with the workflows they
    serve and are additive: supplying several narrows the result set to rows
    satisfying all of them."
    PRD §2.3: "`total_count` counts the rows matching the filters before the
    window is applied, and `has_more` is true exactly when rows remain beyond
    the current window."

    Design: Corner/endpoints/contact_list_status_filter_returns_only_matching_rows
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=200)
    employee = register_employee(unit["id"], role_category="LEGAL")
    logged = log_contact(unit["id"], employee["id"], competitor_name="Rivex SA")
    escalated = log_contact(unit["id"], employee["id"],
                            competitor_name="Novamer GmbH",
                            occurred_at="2026-07-21T10:00:00Z")
    open_contact_review(escalated["id"])
    validate_success(api.escalate_contact(
        escalated["id"],
        contact_escalation_payload("Thread reveals coordinated quoting"), COUNSEL))

    rows, meta = validate_paginated(api.list_contacts(
        COUNSEL, params={"status": "ESCALATED", "business_unit_id": unit["id"]}))
    ids = [row["id"] for row in rows]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert escalated["id"] in ids and logged["id"] not in ids

    _all_rows, all_meta = validate_paginated(api.list_contacts(
        COUNSEL, params={"business_unit_id": unit["id"]}))
    assert all_meta["total_count"] == 2

    page, page_meta = validate_paginated(api.list_contacts(
        COUNSEL, params={"status": "ESCALATED", "business_unit_id": unit["id"],
                         "limit": 1, "offset": 1}))
    assert page == []
    assert page_meta["total_count"] == 1
    assert page_meta["has_more"] is False


def test_escalation_response_already_carries_the_recomputed_charge(api):
    """PRD §3.6: "Escalating, which takes a `reason`, moves `UNDER_REVIEW →
    ESCALATED` and does the reverse. The surcharge is the contact's current
    `exposure_points_charged` multiplied by one less than the escalation
    multiplier of 2.0 — in other words, an amount equal to the existing charge,
    rounded half up to 2 decimal places — added to `exposure_points_charged` so
    the charge is doubled, and added to the unit's ledger, with the unit's
    `version` incrementing by 1."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/consistency_model/cascade_results_are_visible_in_the_same_response_envelope
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=200)
    employee = register_employee(unit["id"], role_category="LEGAL")
    contact = log_contact(unit["id"], employee["id"])
    open_contact_review(contact["id"])
    version_before = read_business_unit(unit["id"])["version"]

    resp = api.escalate_contact(
        contact["id"],
        contact_escalation_payload("Thread reveals coordinated quoting"), COUNSEL)
    data = validate_success(resp)

    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert data["exposure_points_charged"] == 10.00

    stored_unit = read_business_unit(unit["id"])
    assert stored_unit["exposure_points"] == 10.00
    assert stored_unit["version"] > version_before
