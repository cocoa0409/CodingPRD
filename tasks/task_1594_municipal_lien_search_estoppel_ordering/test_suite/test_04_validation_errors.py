"""Validation claims: each rule from the PRD pipeline exercised in an isolated
scenario where only that rule can fail."""
import pytest

from test_helpers import (
    HEADERS_WITHOUT_ROLE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    FINDINGS_EMPTY,
    UTILITY_ONLY_DEPARTMENTS,
    complete_all_tasks,
    create_association,
    create_department,
    create_jurisdiction,
    create_jurisdiction_payload,
    create_search_order,
    create_search_order_payload,
    create_statute,
    file_discrepancy,
    get_delivery,
    get_estoppel,
    get_order,
    identify_order,
    list_order_estoppels,
    list_order_tasks,
    make_provider_admin_headers,
    make_qa_reviewer_headers,
    make_research_analyst_headers,
    make_title_agent_headers,
    patch_order_payload,
    place_estoppel,
    receive_estoppel,
    set_clock,
    setup_config_a,
    setup_identified_order,
    setup_in_verification,
    setup_ready_for_delivery,
    setup_with_ready_delivery,
    submit_order,
    validate_error,
    validate_success,
    verify_order,
)

ADMIN = make_provider_admin_headers()
AGENT = make_title_agent_headers("agent_1")
ANALYST = make_research_analyst_headers("analyst_1")
QA = make_qa_reviewer_headers("qa_1")


def test_missing_user_role_header_rejected(api):
    """PRD 2.1: "Every request carries two headers: `X-User-ID`, identifying the
    acting operator, and `X-User-Role`, naming the caller's role. A request
    missing either header, or carrying a malformed one, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    set_clock()
    response = api.create_jurisdiction(
        create_jurisdiction_payload(code="FL-ORA", name="Orange"),
        HEADERS_WITHOUT_ROLE,
    )
    validate_error(response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_identify_on_missing_order_returns_not_found(api):
    """PRD 3.3: "A `ResearchAnalyst` identifies the governing jurisdiction for an
    order in `INTAKE`, which must reference an existing, `ACTIVE` jurisdiction —
    a missing one surfaces as `ERR_NOT_FOUND`, an inactive one as
    `ERR_INVALID_STATE_TRANSITION`."
    PRD 2.8: "whether every referenced resource — path identifiers and body
    references alike, spanning jurisdictions, statutes, departments, associations,
    orders, tasks, estoppels, discrepancies, and deliveries — actually exists
    (`ERR_NOT_FOUND`)"

    Design: Corner/validations/identify_missing_order_returns_not_found
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    response = api.identify_jurisdiction(
        NON_EXISTENT_UUID, {"jurisdiction_id": jurisdiction["id"]}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value)


def test_association_fee_above_cap_rejected(api):
    """PRD 3.1: "At registration, the quoted fee is checked against the fee cap
    of the statute window covering the current clock date for that jurisdiction;
    a quote above the in-force cap is rejected with
    `ERR_FEE_EXCEEDS_STATUTORY_CAP`."

    Design: Corner/validations/association_fee_above_in_force_cap_rejected
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    create_statute(jurisdiction["id"])
    response = api.create_association(
        {
            "jurisdiction_id": jurisdiction["id"],
            "name": "Pricey HOA",
            "management_company": "Pricey Mgmt",
            "estoppel_fee_cents": 15000,
            "estoppel_validity_days": 30,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_FEE_EXCEEDS_STATUTORY_CAP.value)


def test_identify_without_statute_in_force_rejected(api):
    """PRD 3.3: "A statute window must cover the current clock date for that
    jurisdiction; if none does, the call fails with `ERR_NO_STATUTE_IN_FORCE`."
    PRD 3.2: "The order is born in `INTAKE`, and its `title_agent_id` is copied
    from the caller's `X-User-ID`; the `jurisdiction_id` and `statute_id` remain
    null until jurisdiction identification."

    Design: Corner/validations/identify_without_statute_in_force_returns_error
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    create_statute(jurisdiction["id"], effective_from="2027-01-01")
    order = create_search_order("P-K6")

    response = api.identify_jurisdiction(
        order["id"], {"jurisdiction_id": jurisdiction["id"]}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_NO_STATUTE_IN_FORCE.value)
    current = get_order(order["id"])
    assert current["status"] == "INTAKE"
    assert current.get("statute_id") is None


def test_identify_with_foreign_association_rejected(api):
    """PRD 3.3: "When the order carries an `association_id`, the association must
    belong to the identified jurisdiction, failing with
    `ERR_ASSOCIATION_JURISDICTION_MISMATCH` otherwise."

    Design: Corner/validations/association_jurisdiction_mismatch_on_identify
    """
    set_clock()
    jurisdiction_a = create_jurisdiction(code="FL-DADE", name="Miami-Dade")
    jurisdiction_b = create_jurisdiction(code="FL-BROW", name="Broward")
    create_statute(jurisdiction_a["id"])
    create_statute(jurisdiction_b["id"])
    association_b = create_association(
        jurisdiction_b["id"], name="Broward HOA", management_company="B Mgmt"
    )
    order = create_search_order("P-L7", association_id=association_b["id"])

    response = api.identify_jurisdiction(
        order["id"], {"jurisdiction_id": jurisdiction_a["id"]}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_ASSOCIATION_JURISDICTION_MISMATCH.value)
    assert get_order(order["id"])["status"] == "INTAKE"


def test_place_quote_one_cent_over_cap_rejected(api):
    """PRD 3.5: "Placing it is a `ResearchAnalyst` action carrying the
    association's quoted `fee_quoted_cents`, which must be strictly greater than
    zero and no greater than the fee cap of the order's pinned statute; a quote
    outside that band — including any positive quote when the pinned cap is 0,
    since the statute then requires a free letter — is rejected with
    `ERR_QUOTE_EXCEEDS_STATUTORY_CAP`."

    Design: Corner/validations/place_quote_above_pinned_cap_rejected
    """
    ctx = setup_identified_order("P-M8", departments=UTILITY_ONLY_DEPARTMENTS)
    estoppel = ctx["estoppels"][0]
    response = api.place_estoppel(
        estoppel["id"], {"fee_quoted_cents": 12001}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_QUOTE_EXCEEDS_STATUTORY_CAP.value)
    assert get_estoppel(estoppel["id"])["status"] == "DRAFT"


def test_place_quote_exactly_at_cap_accepted(api):
    """PRD 3.5: "Placing it is a `ResearchAnalyst` action carrying the
    association's quoted `fee_quoted_cents`, which must be strictly greater than
    zero and no greater than the fee cap of the order's pinned statute"
    PRD 3.5: "When the letter arrives while the estoppel is `ORDERED`, receipt is
    on time: `received_at` is stamped, `late_delivery` is set false,
    `current_fee_cents` becomes the quoted fee — clamped as the lesser of
    `fee_quoted_cents` and the pinned cap, though placement already guarantees
    the quote is within cap — and `lifetime_fees_cents` grows by that amount."

    Design: Corner/validations/fee_cap_boundary_exact_quote_accepted
    """
    ctx = setup_identified_order(
        "P-N9",
        departments=UTILITY_ONLY_DEPARTMENTS,
        config_overrides={"association_overrides": {"estoppel_fee_cents": 12000}},
    )
    estoppel = ctx["estoppels"][0]
    placed = place_estoppel(estoppel["id"], 12000)
    assert placed["status"] == "ORDERED"
    received = receive_estoppel(estoppel["id"], 45000)
    assert received["current_fee_cents"] == 12000, (
        "A quote exactly equal to the 12000 cap is within the band and charges "
        "in full on on-time receipt"
    )


def test_missed_item_before_delivery_rejected(api):
    """PRD 3.8: "A `MISSED_ITEM` claim is only meaningful after delivery: filing
    one before the order is delivered, or on a `CANCELLED` order, is refused
    with `ERR_DISCREPANCY_NOT_APPLICABLE`."

    Design: Corner/validations/missed_item_pre_delivery_returns_not_applicable
    """
    ctx = setup_identified_order(
        "P-O1", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    response = api.create_discrepancy(
        {
            "search_order_id": ctx["order"]["id"],
            "subject_type": "SEARCH_ORDER",
            "subject_id": ctx["order"]["id"],
            "discrepancy_type": "MISSED_ITEM",
            "claimed_amount_cents": 5000,
            "description": "missed lien",
        },
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_DISCREPANCY_NOT_APPLICABLE.value)


@pytest.mark.parametrize("claimed", [0, 25000001])
def test_claim_amount_outside_band_rejected(api, claimed):
    """PRD 3.8: "The claim amount must be strictly greater than zero and no
    greater than 25000000 cents; anything outside that band fails with
    `ERR_CLAIM_AMOUNT_INVALID`."

    Design: Corner/validations/claim_amount_bounds_enforced
    """
    ctx = setup_identified_order(
        f"P-P2-{claimed}", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    response = api.create_discrepancy(
        {
            "search_order_id": ctx["order"]["id"],
            "subject_type": "RESEARCH_TASK",
            "subject_id": task["id"],
            "discrepancy_type": "BALANCE_MISMATCH",
            "claimed_amount_cents": claimed,
            "description": "out of band",
        },
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_AMOUNT_INVALID.value)


def test_discrepancy_subject_from_other_order_rejected(api):
    """PRD 3.8: "The subject must belong to the named order — a task or estoppel
    from another order, or a mismatched order reference, fails with
    `ERR_SUBJECT_NOT_IN_ORDER`."

    Design: Corner/validations/subject_outside_order_rejected
    """
    ctx = setup_config_a(departments=UTILITY_ONLY_DEPARTMENTS, with_association=False)
    order_one = create_search_order("P-Q3")
    order_two = create_search_order("P-Q4")
    identify_order(order_one["id"], ctx["jurisdiction"]["id"])
    identify_order(order_two["id"], ctx["jurisdiction"]["id"])
    other_task = list_order_tasks(order_two["id"])[0]

    response = api.create_discrepancy(
        {
            "search_order_id": order_one["id"],
            "subject_type": "RESEARCH_TASK",
            "subject_id": other_task["id"],
            "discrepancy_type": "BALANCE_MISMATCH",
            "claimed_amount_cents": 5000,
            "description": "wrong order's task",
        },
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_SUBJECT_NOT_IN_ORDER.value)


def test_second_ready_delivery_rejected(api):
    """PRD 3.6: "With the order `READY_FOR_DELIVERY`, a `QAReviewer` creates a
    delivery for it; the creation is refused with `ERR_ORDER_NOT_DELIVERABLE`
    when the order is in any other state and with `ERR_DELIVERY_ALREADY_PENDING`
    when a `READY` delivery already exists for the order."

    Design: Corner/validations/delivery_already_pending_rejected
    """
    ctx = setup_with_ready_delivery(
        "P-R5",
        departments=UTILITY_ONLY_DEPARTMENTS,
        with_association=False,
        findings_per_task=[FINDINGS_EMPTY],
    )
    first = ctx["delivery"]
    assert first["status"] == "READY"
    response = api.create_delivery({"search_order_id": ctx["order"]["id"]}, QA)
    validate_error(response, ApiErrorId.ERR_DELIVERY_ALREADY_PENDING.value)
    assert get_delivery(first["id"])["status"] == "READY"


def test_verify_with_wrong_payoff_total_rejected(api):
    """PRD 3.6: "Verification is performed by a `QAReviewer` who independently
    computes the payoff and submits it as `verified_payoff_total_cents`. If that
    figure differs from the order's computed `total_payoff_cents`, verification
    fails with `ERR_PAYOFF_MISMATCH`."

    Design: Corner/validations/payoff_mismatch_on_verification
    """
    ctx = setup_in_verification(
        "P-S6",
        departments=UTILITY_ONLY_DEPARTMENTS,
        with_association=False,
        findings_per_task=[FINDINGS_EMPTY],
    )
    response = api.verify_payoff(
        ctx["order"]["id"], {"verified_payoff_total_cents": 999}, QA
    )
    validate_error(response, ApiErrorId.ERR_PAYOFF_MISMATCH.value)
    assert get_order(ctx["order"]["id"])["status"] == "VERIFICATION"


def test_closing_date_in_past_rejected(api):
    """PRD 3.2: "A `closing_date` earlier than the current clock date is
    rejected with `ERR_CLOSING_DATE_PASSED`."

    Design: Corner/validations/closing_date_in_past_rejected
    """
    set_clock()
    response = api.create_search_order(
        create_search_order_payload("P-T7", closing_date="2026-07-01"), AGENT
    )
    validate_error(response, ApiErrorId.ERR_CLOSING_DATE_PASSED.value)


def test_deliver_after_closing_passed_rejected(api):
    """PRD 3.6: "Releasing it to the title agent requires the order still to be
    `READY_FOR_DELIVERY` (again `ERR_ORDER_NOT_DELIVERABLE` otherwise) and the
    `closing_date` to be on or after the current clock date
    (`ERR_CLOSING_DATE_PASSED` otherwise)."

    Design: Corner/validations/deliver_after_closing_date_rejected
    """
    ctx = setup_with_ready_delivery(
        "P-U8",
        departments=UTILITY_ONLY_DEPARTMENTS,
        findings_per_task=[FINDINGS_EMPTY],
        order_overrides={"closing_date": "2026-08-05"},
    )
    delivery = ctx["delivery"]
    set_clock("2026-08-06T00:00:00Z")

    response = api.deliver_delivery(delivery["id"], QA)
    validate_error(response, ApiErrorId.ERR_CLOSING_DATE_PASSED.value)
    assert get_delivery(delivery["id"])["status"] == "READY"
    assert get_order(ctx["order"]["id"])["status"] == "READY_FOR_DELIVERY"


def test_rush_with_unsupportive_department_rejected(api):
    """PRD 3.2: "Every `ACTIVE` department of the candidate jurisdiction must
    support rush, or creation fails with `ERR_RUSH_NOT_SUPPORTED`."

    Design: Corner/validations/rush_not_supported_department_blocks_order
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    create_statute(jurisdiction["id"])
    create_department(
        jurisdiction["id"],
        dept_type="UTILITY",
        name="Water & Sewer",
        research_fee_cents=5000,
        rush_surcharge_cents=2500,
        supports_rush=False,
    )
    response = api.create_search_order(
        create_search_order_payload(
            "P-V9",
            order_class="RUSH",
            service_date="2026-08-10",
            jurisdiction_id=jurisdiction["id"],
        ),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_RUSH_NOT_SUPPORTED.value)


def test_duplicate_active_department_type_rejected(api):
    """PRD 3.1: "Only one `ACTIVE` department of each `dept_type` may exist per
    jurisdiction; a duplicate active type is refused with
    `ERR_DUPLICATE_DEPARTMENT_TYPE`."

    Design: Corner/validations/duplicate_department_type_rejected
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    create_department(
        jurisdiction["id"], dept_type="UTILITY", name="Water & Sewer",
        research_fee_cents=5000,
    )
    response = api.create_department(
        {
            "jurisdiction_id": jurisdiction["id"],
            "dept_type": "UTILITY",
            "name": "Water Division 2",
            "research_fee_cents": 6000,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_DEPARTMENT_TYPE.value)


def test_patch_closing_beyond_estoppel_validity_reverts_order(api):
    """PRD 3.7: "Moving the `closing_date` re-evaluates estoppel staleness
    immediately: any `RECEIVED` estoppel whose `valid_through` now falls before
    the new closing date pulls an order in `VERIFICATION` or
    `READY_FOR_DELIVERY` back to `RESEARCH_IN_PROGRESS` with its payoff
    verification cleared, and a new date earlier than the clock date is refused
    with `ERR_CLOSING_DATE_PASSED`."

    Design: Corner/validations/patch_closing_past_estoppel_validity_reverts_ready_order
    """
    # Estoppel received 2026-08-01 + 30 validity days -> valid_through 2026-08-31.
    ctx = setup_ready_for_delivery(
        "P-W11",
        departments=UTILITY_ONLY_DEPARTMENTS,
        findings_per_task=[FINDINGS_EMPTY],
    )
    estoppel = ctx["estoppels"][0]
    assert estoppel["valid_through"] == "2026-08-31"
    current = get_order(ctx["order"]["id"], AGENT)

    response = api.patch_search_order(
        ctx["order"]["id"],
        patch_order_payload(current["version"], closing_date="2026-09-05"),
        AGENT,
    )
    patched = validate_success(response, 200)
    assert patched["status"] == "RESEARCH_IN_PROGRESS", (
        "Closing past the received estoppel's valid_through must pull a "
        "READY_FOR_DELIVERY order back to RESEARCH_IN_PROGRESS"
    )
    assert patched.get("payoff_verified_by_user_id") is None
    # No clock sweep ran, so the estoppel itself stays RECEIVED.
    assert get_estoppel(estoppel["id"])["status"] == "RECEIVED"
