"""State-machine entry states, transition side effects and terminal-state guards."""

from test_helpers import (
    CLOCK_START,
    CREDIT_MANAGER,
    PRO_DESK_ASSOCIATE,
    SKU_SHINGLE_BUNDLE,
    SKU_TRIM_PACK,
    STORE_OPERATIONS,
    TAX_COMPLIANCE_OFFICER,
    ApiErrorId,
    assert_credit_line,
    assert_job_quote,
    assert_rebate_accrual,
    assert_will_call_staging,
    counter_offer_line_price,
    create_delivery_appointment_payload,
    create_delivery_truck,
    create_draft_order,
    create_job_quote_payload,
    create_pro_account,
    create_quote_line_payload,
    create_store,
    create_will_call_staging_payload,
    file_tax_exempt_certificate,
    freeze_credit_line,
    list_rebate_accruals,
    make_contractor_admin_headers,
    read_credit_line,
    read_pro_account,
    read_pro_order,
    read_store_stock,
    setup_account_with_credit_line,
    setup_credited_return,
    setup_invoiced_will_call_order,
    setup_pro_desk,
    setup_reserved_order,
    setup_store_with_stock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_tax_exempt_certificate,
)


def _instant_equals(actual: str, expected: str) -> bool:
    """True when two ISO 8601 UTC strings denote the same instant."""

    def normalise(value: str) -> str:
        assert isinstance(value, str) and value.endswith(
            "Z"
        ), f"expected a UTC ISO 8601 instant, got {value!r}"
        core = value[:-1]
        if "." in core:
            core = core.split(".")[0]
        return core

    return normalise(actual) == normalise(expected)


def _rate_equals(actual, expected: float) -> bool:
    """Rates are decimal fractions; compare them without floating-point noise."""
    return isinstance(actual, (int, float)) and abs(float(actual) - expected) < 1e-9


# --------------------------------------------------------------------------- #
# Job quote entry state and submission                                        #
# --------------------------------------------------------------------------- #


def test_new_job_quote_opens_in_draft_with_no_negotiation_history(api):
    """PRD §3.5: "A new quote opens in `status` `DRAFT` with `round_count` at 0 and `revision_count` at 0."
    PRD §3.5: "Both fields are null until the first counter-offer lands."
    PRD §2.5: "**`version`** (integer): a monotonically increasing counter that starts at 1 when the record is created and increases by one on every mutation."
    PRD §4: "Endpoints that create a new resource respond with `201 Created`; every other successful call responds with `200 OK`."

    Design: Corner/state_machines/job_quote_starts_in_draft_with_no_negotiation_history
    """
    store, _ = setup_store_with_stock([(SKU_SHINGLE_BUNDLE, 600)])
    account = create_pro_account(store["id"], business_name="Cycle Roofing")
    headers = make_contractor_admin_headers(account["id"])

    response = api.create_job_quote(
        create_job_quote_payload(
            account["id"], store["id"], job_name="ROOF-A", requested_term_days=30
        ),
        headers,
    )
    quote = validate_success(response, expected_status=201)

    assert_job_quote(quote)
    assert quote["status"] == "DRAFT"
    assert quote["round_count"] == 0
    assert quote["revision_count"] == 0
    assert quote["negotiated_total_cents"] is None
    assert quote["discount_depth_pct"] is None
    assert quote["version"] == 1


def test_submitting_a_quote_snapshots_list_prices_and_advances_to_submitted(api):
    """PRD §3.5: "Submission takes the quote from `DRAFT` to `SUBMITTED` and is the moment list prices are frozen."
    PRD §3.5: "On success, every line's `list_unit_price_cents` is copied from the originating store's stock position for that SKU, every line's `line_list_subtotal_cents` is set to that unit price multiplied by the line's `qty_units`, the quote's `list_subtotal_cents` is set to the sum of those line figures, and the quote's `version` increments."
    PRD §3.5: "Both fields are null until the first counter-offer lands."

    Design: Corner/state_machines/quote_submit_snapshots_list_prices_and_advances_to_submitted
    """
    store, _ = setup_store_with_stock([(SKU_SHINGLE_BUNDLE, 600)])
    account = create_pro_account(store["id"], business_name="Cycle Roofing")
    headers = make_contractor_admin_headers(account["id"])
    quote = validate_success(
        api.create_job_quote(
            create_job_quote_payload(
                account["id"], store["id"], job_name="ROOF-A", requested_term_days=30
            ),
            headers,
        ),
        expected_status=201,
    )
    line = validate_success(
        api.create_quote_line(
            quote["id"], create_quote_line_payload(SKU_SHINGLE_BUNDLE, 8), headers
        ),
        expected_status=201,
    )

    submitted = validate_success(
        api.submit_job_quote(quote["id"], headers), expected_status=200
    )

    assert submitted["status"] == "SUBMITTED"
    assert submitted["list_subtotal_cents"] == 15_992
    assert submitted["version"] == 2

    priced_line = validate_success(
        api.get_quote_line(line["id"], headers), expected_status=200
    )
    assert priced_line["list_unit_price_cents"] == 1_999
    assert priced_line["line_list_subtotal_cents"] == 15_992
    assert priced_line["negotiated_unit_price_cents"] is None


def test_submitting_a_quote_without_lines_is_refused_and_leaves_it_in_draft(api):
    """PRD §3.5: "It is refused if the quote has no lines at all (`ERR_NO_QUOTE_LINES`), if any line's `sku` has lost its stock position at the originating store (`ERR_SKU_NOT_STOCKED`), or if the owning account is on hold (`ERR_ACCOUNT_ON_HOLD`)."
    PRD §3.5: "A quote may carry only one line per SKU, and a line whose `sku` has no stock position at the originating store is refused with `ERR_SKU_NOT_STOCKED`."
    PRD §3.5: "A new quote opens in `status` `DRAFT` with `round_count` at 0 and `revision_count` at 0."

    Design: Corner/state_machines/submit_quote_without_lines_returns_no_quote_lines
    """
    store, _ = setup_store_with_stock([(SKU_SHINGLE_BUNDLE, 600)])
    account = create_pro_account(store["id"], business_name="Cycle Roofing")
    headers = make_contractor_admin_headers(account["id"])
    quote = validate_success(
        api.create_job_quote(
            create_job_quote_payload(
                account["id"], store["id"], job_name="ROOF-A", requested_term_days=30
            ),
            headers,
        ),
        expected_status=201,
    )

    line_less = api.submit_job_quote(quote["id"], headers)
    validate_error(line_less, ApiErrorId.ERR_NO_QUOTE_LINES.value, expected_status=422)

    unstocked = api.create_quote_line(
        quote["id"], create_quote_line_payload(SKU_TRIM_PACK, 4), headers
    )
    validate_error(unstocked, ApiErrorId.ERR_SKU_NOT_STOCKED.value, expected_status=422)

    unchanged = validate_success(
        api.get_job_quote(quote["id"], headers), expected_status=200
    )
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == 1

    lines, _ = validate_paginated(api.list_quote_lines_of_quote(quote["id"], headers))
    assert lines == []


def test_accepted_quote_refuses_a_further_counter_offer(api):
    """PRD §3.5: "Acceptance by the `ContractorAdmin` moves the quote from `APPROVED` to `ACCEPTED` and starts the clock on price protection."
    PRD §3.5: "The term the contractor actually gets is the **lesser** of what was asked and what the tier permits: `term_days` is set to the smaller of `requested_term_days` and the `max_quote_term_days` of the tier persisted on the account at the acceptance instant — 15 days at `MEMBER`, 30 at `GOLD`, 60 at `PLATINUM`, 90 at `DIAMOND`."
    PRD §3.5: "`term_start` is set to the current clock instant and `term_end` to `term_start` advanced by `term_days` days."
    PRD §3.5: "`ACCEPTED`, `EXPIRED` and `WITHDRAWN` are the quote's three terminal states."
    PRD §2.11: "**Generic state guard** — the target resource is in a state the requested transition is declared to leave from, otherwise `ERR_INVALID_STATE`."
    PRD §2.11: "This is what rejects a repeated trigger and any trigger issued from a terminal state."
    PRD §3.5: "The quote's `negotiated_total_cents` becomes the sum of those line figures, and its `discount_depth_pct` is recomputed as the amount given away divided by the list value — that is, `list_subtotal_cents` less `negotiated_total_cents`, divided by `list_subtotal_cents` — rounded half up to four decimal places."

    Design: Corner/state_machines/accepted_quote_is_terminal_and_rejects_a_further_counter_offer
    """
    store, _ = setup_store_with_stock([(SKU_SHINGLE_BUNDLE, 600)])
    account = create_pro_account(store["id"], business_name="Cycle Roofing")
    headers = make_contractor_admin_headers(account["id"])
    quote = validate_success(
        api.create_job_quote(
            create_job_quote_payload(
                account["id"], store["id"], job_name="ROOF-A", requested_term_days=30
            ),
            headers,
        ),
        expected_status=201,
    )
    line = validate_success(
        api.create_quote_line(
            quote["id"], create_quote_line_payload(SKU_SHINGLE_BUNDLE, 8), headers
        ),
        expected_status=201,
    )
    submitted = validate_success(
        api.submit_job_quote(quote["id"], headers), expected_status=200
    )
    validate_success(
        api.counter_offer_job_quote(
            quote["id"],
            [counter_offer_line_price(line["id"], 1_500)],
            30,
            submitted["version"],
            PRO_DESK_ASSOCIATE,
        ),
        expected_status=200,
    )
    validate_success(
        api.approve_job_quote(quote["id"], CREDIT_MANAGER), expected_status=200
    )
    accepted = validate_success(
        api.accept_job_quote(quote["id"], headers), expected_status=200
    )

    assert accepted["status"] == "ACCEPTED"
    assert accepted["negotiated_total_cents"] == 12_000
    assert _rate_equals(accepted["discount_depth_pct"], 0.2496)
    assert accepted["round_count"] == 1
    assert accepted["term_days"] == 15
    assert _instant_equals(accepted["term_start"], "2026-08-01T00:00:00Z")
    assert _instant_equals(accepted["term_end"], "2026-08-16T00:00:00Z")

    negotiated_line = validate_success(
        api.get_quote_line(line["id"], headers), expected_status=200
    )
    assert negotiated_line["negotiated_unit_price_cents"] == 1_500

    further_round = api.counter_offer_job_quote(
        quote["id"],
        [counter_offer_line_price(line["id"], 1_400)],
        30,
        accepted["version"],
        PRO_DESK_ASSOCIATE,
    )
    validate_error(further_round, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    after = validate_success(api.get_job_quote(quote["id"], headers), expected_status=200)
    assert after["status"] == "ACCEPTED"
    assert after["version"] == accepted["version"]


# --------------------------------------------------------------------------- #
# Will-call staging                                                           #
# --------------------------------------------------------------------------- #


def test_staging_the_same_bay_twice_is_refused_on_the_second_call(api):
    """PRD §3.8: "The server computes `expires_at` as `stage_start` advanced by `stage_hours` hours."
    PRD §3.8: "Staging drives the order's `fulfillment_status` from `RESERVED` to `STAGED` and increments both the staging's and the order's `version`."
    PRD §2.11: "**Generic state guard** — the target resource is in a state the requested transition is declared to leave from, otherwise `ERR_INVALID_STATE`."
    PRD §2.11: "This is what rejects a repeated trigger and any trigger issued from a terminal state."
    PRD §3.1: "`reserved_units` is always the sum of `qty_units` across the reservations at that store for that SKU whose status is `HELD` or `ALLOCATED`, and `available_units` is `on_hand_units` less `reserved_units`; both are recomputed whenever a reservation is created, released or consumed, and reads of a position always show live figures."

    Design: Corner/state_machines/staging_the_same_will_call_bay_twice_second_call_returns_invalid_state
    """
    desk = setup_pro_desk(
        skus=[(SKU_SHINGLE_BUNDLE, 600)],
        store_overrides={"will_call_bay_slots": 2, "max_stage_hours": 48},
        account_overrides={"business_name": "Double Stage Co"},
    )
    store, account, stocks = desk["store"], desk["account"], desk["stocks"]
    order, _, reservations = setup_reserved_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    for reservation in reservations:
        validate_success(
            api.allocate_reservation(reservation["id"], STORE_OPERATIONS),
            expected_status=200,
        )
    staging = validate_success(
        api.create_will_call_staging(
            create_will_call_staging_payload(
                order["id"],
                store["id"],
                stage_start="2026-08-01T09:00:00Z",
                stage_hours=24,
            ),
            STORE_OPERATIONS,
        ),
        expected_status=201,
    )

    staged = validate_success(
        api.stage_will_call_staging(staging["id"], STORE_OPERATIONS), expected_status=200
    )
    assert_will_call_staging(staged)
    assert staged["status"] == "STAGED"
    assert _instant_equals(staged["expires_at"], "2026-08-02T09:00:00Z")
    assert staged["version"] == 2
    assert read_pro_order(order["id"], account["id"])["fulfillment_status"] == "STAGED"

    repeat = api.stage_will_call_staging(staging["id"], STORE_OPERATIONS)
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    stock = read_store_stock(stocks[SKU_SHINGLE_BUNDLE]["id"])
    assert stock["on_hand_units"] == 600
    assert stock["reserved_units"] == 10
    assert stock["available_units"] == 590


# --------------------------------------------------------------------------- #
# Order cancellation is terminal                                              #
# --------------------------------------------------------------------------- #


def test_cancelled_order_refuses_submit_reserve_and_a_second_cancellation(api):
    """PRD §3.6: "Cancellation is the order's escape hatch, available to a `ContractorAdmin` from `DRAFT`, `SUBMITTED`, `RESERVED` and `STAGED`, and rejected with `ERR_INVALID_STATE` from `FULFILLED` or from an already-cancelled order."
    PRD §3.6: "It carries a `reason_code` recorded as `cancel_reason_code`, drives `fulfillment_status` to `CANCELLED`, and increments the order's `version`."
    PRD §3.6: "A new order sits at `fulfillment_status` `DRAFT` and `credit_status` `UNBILLED`, with every money field null until it is priced."
    PRD §2.11: "This is what rejects a repeated trigger and any trigger issued from a terminal state."

    Design: Corner/state_machines/cancelled_order_cannot_be_submitted_reserved_or_cancelled_again
    """
    desk = setup_pro_desk(
        skus=[(SKU_SHINGLE_BUNDLE, 600)],
        account_overrides={"business_name": "One Way Out LLC"},
    )
    store, account = desk["store"], desk["account"]
    headers = desk["admin_headers"]
    order, _ = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )

    cancelled = validate_success(
        api.cancel_pro_order(order["id"], "CUSTOMER_CHANGE", headers),
        expected_status=200,
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"

    validate_error(
        api.submit_pro_order(order["id"], headers),
        ApiErrorId.ERR_INVALID_STATE.value,
        expected_status=409,
    )
    validate_error(
        api.reserve_pro_order(order["id"], PRO_DESK_ASSOCIATE),
        ApiErrorId.ERR_INVALID_STATE.value,
        expected_status=409,
    )
    validate_error(
        api.cancel_pro_order(order["id"], "CUSTOMER_CHANGE", headers),
        ApiErrorId.ERR_INVALID_STATE.value,
        expected_status=409,
    )

    final = read_pro_order(order["id"], account["id"])
    assert final["fulfillment_status"] == "CANCELLED"
    assert final["credit_status"] == "UNBILLED"
    assert final["cancel_reason_code"] == "CUSTOMER_CHANGE"
    assert final["total_cents"] is None

    reservations, _ = validate_paginated(
        api.list_reservations(STORE_OPERATIONS, params={"pro_order_id": order["id"]})
    )
    assert reservations == []


# --------------------------------------------------------------------------- #
# Certificate supersession and revocation                                     #
# --------------------------------------------------------------------------- #


def test_verifying_a_newer_certificate_supersedes_the_incumbent(api):
    """PRD §3.4: "A successful verification moves `status` from `PENDING` to `VERIFIED`, stamps `verified_at` with the current clock instant, and increments the certificate's `version`."
    PRD §3.4: "It also supersedes the incumbent: any other certificate of the same account and the same `state_code` that was in `VERIFIED` moves to `SUPERSEDED`."
    PRD §3.4: "That derived array holds exactly those `state_code` values for which the account has a certificate whose `status` is `VERIFIED` and whose `expires_on` is strictly after the current clock date — the same strict comparison, applied continuously, so a verified certificate silently drops out of the array on the day it expires without any transition being recorded against it."
    PRD §3.4: "A `TaxComplianceOfficer` revoking a certificate supplies a `reason_code`, which is stored as `revoke_reason_code`; the certificate moves from `VERIFIED` to `REVOKED`, its `version` increments, and `tax_exempt_state_codes` is recomputed without it."

    Design: Corner/state_machines/verifying_a_newer_certificate_supersedes_the_prior_verified_one
    """
    store = create_store(state_code="IL")
    account = create_pro_account(store["id"], business_name="Resale Supply Co")
    first = file_tax_exempt_certificate(
        account["id"],
        state_code="IL",
        certificate_number="C-1",
        expires_on="2027-01-01",
    )
    verify_tax_exempt_certificate(first["id"])
    second = file_tax_exempt_certificate(
        account["id"],
        state_code="IL",
        certificate_number="C-2",
        expires_on="2028-01-01",
    )

    verified = validate_success(
        api.verify_tax_exempt_certificate(second["id"], TAX_COMPLIANCE_OFFICER),
        expected_status=200,
    )
    assert verified["status"] == "VERIFIED"
    assert _instant_equals(verified["verified_at"], CLOCK_START)

    superseded = validate_success(
        api.get_tax_exempt_certificate(first["id"], TAX_COMPLIANCE_OFFICER),
        expected_status=200,
    )
    assert superseded["status"] == "SUPERSEDED"
    assert read_pro_account(account["id"])["tax_exempt_state_codes"] == ["IL"]

    revoked = validate_success(
        api.revoke_tax_exempt_certificate(
            second["id"], "AUDIT_FAILURE", TAX_COMPLIANCE_OFFICER
        ),
        expected_status=200,
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoke_reason_code"] == "AUDIT_FAILURE"
    assert read_pro_account(account["id"])["tax_exempt_state_codes"] == []


# --------------------------------------------------------------------------- #
# Two-handed credit recovery                                                  #
# --------------------------------------------------------------------------- #


def test_account_reinstate_is_refused_while_its_credit_line_is_still_frozen(api):
    """PRD §3.3: "Both paths do the same three things — they move `status` from `ACTIVE` to `FROZEN`, they increment the line's `version`, and they cascade into the owning account, driving its `status` from `ACTIVE` to `HOLD`."
    PRD §3.3: "That is a separate act on the **account**, moving its `status` from `HOLD` to `ACTIVE` and incrementing its `version`, and it is refused with `ERR_CREDIT_LINE_FROZEN` while the account's credit line is still frozen."
    PRD §3.3: "Reinstating the **credit line** moves it from `FROZEN` back to `ACTIVE`, clears `frozen_reason_code` and increments its `version`, but it is guarded twice: a line that is already `ACTIVE` is rejected with `ERR_CREDIT_LINE_NOT_FROZEN`, and a genuinely frozen line whose `exposure_cents` is still at or above the freeze threshold is rejected with `ERR_UTILIZATION_STILL_HIGH` — the manager must first bring exposure down, by settling invoices or crediting returns, before the line will come back."
    PRD §3.3: "Reinstating the line does **not** by itself lift the account's hold."

    Design: Corner/state_machines/account_reinstate_while_credit_line_still_frozen_returns_credit_line_frozen
    """
    scenario = setup_account_with_credit_line(
        tier_code="MEMBER",
        limit_cents=500_000,
        terms_days=30,
        account_overrides={"business_name": "Held Builders"},
    )
    account, credit_line = scenario["account"], scenario["credit_line"]
    freeze_credit_line(credit_line["id"], "MANUAL")

    blocked = api.reinstate_pro_account(account["id"], CREDIT_MANAGER)
    validate_error(
        blocked, ApiErrorId.ERR_CREDIT_LINE_FROZEN.value, expected_status=409
    )
    assert read_pro_account(account["id"])["status"] == "HOLD"

    reinstated_line = validate_success(
        api.reinstate_credit_line(credit_line["id"], CREDIT_MANAGER),
        expected_status=200,
    )
    assert reinstated_line["status"] == "ACTIVE"
    assert reinstated_line["frozen_reason_code"] is None
    assert read_pro_account(account["id"])["status"] == "HOLD"

    reinstated_account = validate_success(
        api.reinstate_pro_account(account["id"], CREDIT_MANAGER), expected_status=200
    )
    assert reinstated_account["status"] == "ACTIVE"


def test_reinstating_an_already_active_credit_line_is_refused(api):
    """PRD §3.3: "Reinstating the **credit line** moves it from `FROZEN` back to `ACTIVE`, clears `frozen_reason_code` and increments its `version`, but it is guarded twice: a line that is already `ACTIVE` is rejected with `ERR_CREDIT_LINE_NOT_FROZEN`, and a genuinely frozen line whose `exposure_cents` is still at or above the freeze threshold is rejected with `ERR_UTILIZATION_STILL_HIGH` — the manager must first bring exposure down, by settling invoices or crediting returns, before the line will come back."
    PRD §3.3: "An account may hold at most one credit line; a second attempt is rejected with `ERR_CREDIT_LINE_EXISTS`."
    PRD §3.3: "A new line opens with `exposure_cents` at 0, `available_cents` equal to `limit_cents`, `status` `ACTIVE` and `frozen_reason_code` null."
    PRD §3.3: "`available_cents` is `limit_cents` less `exposure_cents`."
    PRD §2.11: "**Credit line already active** — a reinstatement targets a line that is actually frozen, otherwise `ERR_CREDIT_LINE_NOT_FROZEN`."

    Design: Corner/state_machines/reinstating_an_already_active_credit_line_returns_credit_line_not_frozen
    """
    scenario = setup_account_with_credit_line(
        tier_code="MEMBER",
        limit_cents=500_000,
        terms_days=30,
        account_overrides={"business_name": "Already Fine Fencing"},
    )
    account, credit_line = scenario["account"], scenario["credit_line"]

    not_frozen = api.reinstate_credit_line(credit_line["id"], CREDIT_MANAGER)
    validate_error(
        not_frozen, ApiErrorId.ERR_CREDIT_LINE_NOT_FROZEN.value, expected_status=409
    )

    duplicate = api.create_credit_line(
        {"pro_account_id": account["id"], "limit_cents": 500_000, "terms_days": 30},
        CREDIT_MANAGER,
    )
    validate_error(
        duplicate, ApiErrorId.ERR_CREDIT_LINE_EXISTS.value, expected_status=409
    )

    unchanged = read_credit_line(credit_line["id"])
    assert_credit_line(unchanged)
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["limit_cents"] == 500_000
    assert unchanged["exposure_cents"] == 0
    assert unchanged["available_cents"] == 500_000
    assert unchanged["version"] == 1


def test_credit_line_reinstate_is_refused_while_exposure_sits_at_the_freeze_threshold(
    api,
):
    """PRD §3.3: "Its threshold is 90 percent of the limit: the freeze threshold in cents is `limit_cents` multiplied by nine tenths, rounded half up to a whole cent."
    PRD §3.3: "Reinstating the **credit line** moves it from `FROZEN` back to `ACTIVE`, clears `frozen_reason_code` and increments its `version`, but it is guarded twice: a line that is already `ACTIVE` is rejected with `ERR_CREDIT_LINE_NOT_FROZEN`, and a genuinely frozen line whose `exposure_cents` is still at or above the freeze threshold is rejected with `ERR_UTILIZATION_STILL_HIGH` — the manager must first bring exposure down, by settling invoices or crediting returns, before the line will come back."
    PRD §3.3: "It is the sum of `total_cents` across the account's orders whose `credit_status` is `AUTHORIZED` or `INVOICED`, less the sum of `credited_refund_cents` across those same orders."
    PRD §3.6: "An order that had been authorized has its `credit_status` driven from `AUTHORIZED` to `VOIDED`, after which the credit line's `exposure_cents` and `available_cents` are recomputed — this is the compensating leg that returns the authorized amount to the contractor's headroom."
    PRD §2.11: "**Utilization still high** — a frozen line being reinstated has exposure strictly below its freeze threshold, otherwise `ERR_UTILIZATION_STILL_HIGH`."

    Design: Corner/state_machines/reinstate_blocked_while_utilization_still_at_the_freeze_threshold
    """
    scenario = setup_account_with_credit_line(
        tier_code="MEMBER",
        limit_cents=100_000,
        terms_days=30,
        skus=[(SKU_SHINGLE_BUNDLE, 600)],
        account_overrides={"business_name": "Tight Line Framing"},
    )
    store, account, credit_line = (
        scenario["store"],
        scenario["account"],
        scenario["credit_line"],
    )
    headers = scenario["admin_headers"]
    order, _ = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 42)],
        payment_method="CREDIT_LINE",
        delivery_mode="WILL_CALL",
    )
    submitted = submit_order(order["id"], account["id"])
    assert submitted["total_cents"] == 90_885

    exposed = read_credit_line(credit_line["id"])
    assert exposed["exposure_cents"] == 90_885
    assert exposed["available_cents"] == 9_115

    freeze_credit_line(credit_line["id"], "MANUAL")

    blocked = api.reinstate_credit_line(credit_line["id"], CREDIT_MANAGER)
    validate_error(
        blocked, ApiErrorId.ERR_UTILIZATION_STILL_HIGH.value, expected_status=409
    )
    assert read_credit_line(credit_line["id"])["status"] == "FROZEN"

    validate_success(
        api.cancel_pro_order(order["id"], "CUSTOMER_CHANGE", headers),
        expected_status=200,
    )
    assert read_pro_order(order["id"], account["id"])["credit_status"] == "VOIDED"

    released = read_credit_line(credit_line["id"])
    assert released["exposure_cents"] == 0
    assert released["available_cents"] == 100_000

    reinstated = validate_success(
        api.reinstate_credit_line(credit_line["id"], CREDIT_MANAGER),
        expected_status=200,
    )
    assert reinstated["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Booking a fulfilment channel before sourcing                                #
# --------------------------------------------------------------------------- #


def test_booking_a_bay_or_a_truck_for_a_draft_order_is_refused(api):
    """PRD §3.8: "Both channels also insist that the order has actually been sourced — booking either against an order whose `fulfillment_status` is anything other than `RESERVED` is refused with `ERR_ORDER_NOT_RESERVED`, which is the specialized form the two booking endpoints use in place of the generic state guard."
    PRD §2.11: "**Order not reserved** — a will-call staging or a delivery appointment is being booked for an order whose `fulfillment_status` is `RESERVED`, otherwise `ERR_ORDER_NOT_RESERVED`."
    PRD §2.11: "This too is a specialization evaluated ahead of rung 13, and it applies only to *booking* a staging or an appointment; marking a staging physically staged and confirming an appointment keep the generic guard."
    PRD §3.6: "A new order sits at `fulfillment_status` `DRAFT` and `credit_status` `UNBILLED`, with every money field null until it is priced."

    Design: Corner/state_machines/booking_a_bay_or_a_truck_for_a_draft_order_returns_order_not_reserved
    """
    desk = setup_pro_desk(
        skus=[(SKU_SHINGLE_BUNDLE, 600)],
        store_overrides={"will_call_bay_slots": 2, "max_stage_hours": 48},
        account_overrides={"business_name": "Premature Booking Co"},
    )
    store, account = desk["store"], desk["account"]
    truck = create_delivery_truck(
        store["id"],
        truck_code="T-1",
        lift_gate_equipped=True,
        access_types_supported=["CURBSIDE"],
        turnaround_buffer_minutes=30,
    )
    order, _ = create_draft_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )

    bay = api.create_will_call_staging(
        create_will_call_staging_payload(
            order["id"], store["id"], stage_start="2026-08-01T09:00:00Z", stage_hours=6
        ),
        STORE_OPERATIONS,
    )
    validate_error(bay, ApiErrorId.ERR_ORDER_NOT_RESERVED.value, expected_status=409)

    appointment = api.create_delivery_appointment(
        create_delivery_appointment_payload(order["id"], truck["id"]), STORE_OPERATIONS
    )
    validate_error(
        appointment, ApiErrorId.ERR_ORDER_NOT_RESERVED.value, expected_status=409
    )

    stagings, _ = validate_paginated(
        api.list_will_call_stagings(
            STORE_OPERATIONS, params={"pro_order_id": order["id"]}
        )
    )
    assert stagings == []

    appointments, _ = validate_paginated(
        api.list_delivery_appointments(
            STORE_OPERATIONS, params={"pro_order_id": order["id"]}
        )
    )
    assert appointments == []

    assert read_pro_order(order["id"], account["id"])["fulfillment_status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Rebate accrual close fork                                                   #
# --------------------------------------------------------------------------- #


def test_closing_a_fully_clawed_back_accrual_voids_it_instead_of_making_it_payable(api):
    """PRD §3.9: "The rates are 0.0 percent at `MEMBER`, 1.0 percent at `GOLD`, 2.0 percent at `PLATINUM` and 3.0 percent at `DIAMOND`."
    PRD §3.9: "A `CreditManager` **closes** an accrual, which stamps `closed_at` with the current clock, increments the accrual's `version`, and branches on the money: `payout_status` goes from `ACCRUING` to `PAYABLE` when `payable_cents` is strictly positive, and from `ACCRUING` to `VOIDED` when `payable_cents` is exactly zero, which happens when clawbacks have consumed the whole accrual."
    PRD §3.9: "Voiding recomputes the account's `rebate_accrued_cents`, since a `VOIDED` accrual leaves the base."
    PRD §3.9: "`PAID` and `VOIDED` are the accrual's terminal states, and neither is ever touched again."
    PRD §2.11: "This is what rejects a repeated trigger and any trigger issued from a terminal state."
    PRD §3.9: "Finally, `refund_total_cents` is the net goods figure plus `tax_refund_cents`."

    Design: Corner/state_machines/closing_a_fully_clawed_back_accrual_routes_to_voided_not_payable
    """
    scenario = setup_account_with_credit_line(
        tier_code="GOLD",
        limit_cents=1_000_000,
        terms_days=30,
        skus=[(SKU_SHINGLE_BUNDLE, 600)],
        account_overrides={
            "business_name": "Gold Standard Exteriors",
            "baseline_volume_cents": 5_000_000,
        },
    )
    store, account = scenario["store"], scenario["account"]
    bundle = setup_invoiced_will_call_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 100)],
        stage_start="2026-08-01T09:00:00Z",
        stage_hours=24,
    )
    order_line = bundle["order_lines"][0]

    credited = setup_credited_return(
        bundle["order"]["id"], account["id"], [(order_line["id"], 100)], "OVER_ORDERED"
    )
    assert credited["gross_refund_cents"] == 189_900
    assert credited["refund_total_cents"] == 205_567

    accruals = list_rebate_accruals(account["id"])
    assert len(accruals) == 1
    accrual_id = accruals[0]["id"]

    closed = validate_success(
        api.close_rebate_accrual(accrual_id, CREDIT_MANAGER), expected_status=200
    )
    assert_rebate_accrual(closed)
    assert closed["accrued_cents"] == 1_899
    assert closed["clawed_back_cents"] == 1_899
    assert closed["payable_cents"] == 0
    assert closed["payout_status"] == "VOIDED"
    assert _instant_equals(closed["closed_at"], CLOCK_START)

    refreshed_account = read_pro_account(account["id"])
    assert refreshed_account["rebate_accrued_cents"] == 0
    assert refreshed_account["trailing_volume_cents"] == 5_000_000
    assert refreshed_account["tier_code"] == "GOLD"

    pay_out = api.pay_out_rebate_accrual(accrual_id, "ACH-0001", CREDIT_MANAGER)
    validate_error(pay_out, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
