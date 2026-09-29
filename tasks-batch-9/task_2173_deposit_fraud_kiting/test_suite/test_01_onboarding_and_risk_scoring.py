"""Registering depositors, opening accounts, verifying funding, and risk scoring."""

from test_helpers import (
    ApiErrorId,
    assert_account_link,
    assert_customer,
    assert_deposit_account,
    assert_same_instant,
    declare_funding_source,
    link_accounts,
    new_account,
    new_customer,
    read_account,
    submit_verification,
    take_deposit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


# ===========================================================================
# The dual-variant new-account risk score on DepositAccount
# ===========================================================================
def test_provisional_at_open_forces_the_none_funding_posture(api, ops_admin_headers):
    """PRD §3.1: "The `PROVISIONAL_AT_OPEN` variant runs inside account opening,
    before any funding source or association edge can possibly exist for the new
    account; it *forces* the funding posture to none — the full 30 points — and
    *forces* the risk-bearing link count to zero, regardless of what a later read
    would find, and it writes `risk_score_basis` as `PROVISIONAL_AT_OPEN`."
    PRD §3.1: "The first term is the depositor's diligence tier: a `TIER_1` file
    contributes nothing, `TIER_2` contributes 15 points, and `TIER_3` contributes
    35 points."
    PRD §3.1: "The third term is the origination channel: `BRANCH` contributes
    nothing, `ONLINE` contributes 12 points, `MOBILE` contributes 18 points."
    PRD §3.1: "The band follows from the score with an inclusive comparison at
    both edges: a score of 60 or more is `HIGH`, a score of at least 35 but below
    60 is `ELEVATED`, and anything below 35 is `STANDARD`."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_at_open_versus_refreshed_on_deposit_account
    """
    customer = new_customer(
        legal_name="Dana Kesselring", tin_last4="3391", kyc_tier="TIER_3", watchlist_hit=False
    )

    response = api.create_account(
        {"customer_id": customer["id"], "product_type": "CHECKING", "open_channel": "ONLINE"},
        ops_admin_headers,
    )
    account = validate_success(response, 201)
    assert_deposit_account(account)

    # TIER_3 (35) + funding NONE (30) + ONLINE (12) = 77.
    assert account["risk_score"] == 77, (
        f"Expected the provisional score 35 + 30 + 12 = 77, got {account['risk_score']}"
    )
    assert account["risk_score_basis"] == "PROVISIONAL_AT_OPEN"
    assert account["risk_band"] == "HIGH", "77 is at or above 60, so the band is HIGH"
    assert account["lifecycle_status"] == "PENDING_FUNDING"


def test_refreshed_variant_rescores_as_the_funding_posture_advances(api, analyst_headers):
    """PRD §3.2: "Declaring the source also re-evaluates the account's risk under
    the `REFRESHED` variant, because the funding posture has just moved from none
    to pending, dropping the score by 10 points."
    PRD §3.2: "Because the account has left `PENDING_FUNDING`, the risk score is
    re-evaluated under the `REFRESHED` variant and `risk_score`, `risk_band`, and
    `risk_score_basis` are rewritten; the funding posture is now verified, so a
    further 20 points fall away."
    PRD §3.2: "Because a source has reached `VERIFIED`, the owning account
    transitions `PENDING_FUNDING → ACTIVE` — this transition fires only when the
    account is actually in `PENDING_FUNDING`, so a second source verifying later
    on an already-active account changes nothing about the lifecycle."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_at_open_versus_refreshed_on_deposit_account
    """
    customer = new_customer(
        legal_name="Dana Kesselring", tin_last4="3391", kyc_tier="TIER_3", watchlist_hit=False
    )
    account = new_account(customer["id"], product_type="CHECKING", open_channel="ONLINE")
    assert account["risk_score"] == 77

    source = declare_funding_source(account["id"], source_type="EXTERNAL_ACH", routing_last4="0219")
    pending = read_account(account["id"], analyst_headers)
    # TIER_3 (35) + funding PENDING (20) + ONLINE (12) = 67.
    assert pending["risk_score"] == 67, (
        f"A declared but unverified source is the pending posture: expected 67, "
        f"got {pending['risk_score']}"
    )
    assert pending["risk_score_basis"] == "REFRESHED"
    assert pending["lifecycle_status"] == "PENDING_FUNDING"

    submit_verification(source["id"], source["micro_deposit_cents"])

    verified = read_account(account["id"], analyst_headers)
    # TIER_3 (35) + funding VERIFIED (0) + ONLINE (12) = 47.
    assert verified["risk_score"] == 47, (
        f"Expected 47 once the funding posture is verified, got {verified['risk_score']}"
    )
    assert verified["risk_band"] == "ELEVATED", "47 sits at or above 35 and below 60"
    assert verified["risk_score_basis"] == "REFRESHED"
    assert verified["lifecycle_status"] == "ACTIVE"


# ===========================================================================
# The five-term assembly, its link cap and its confidence gate
# ===========================================================================
def _tier1_mobile_account_with_two_counterparts():
    customer = new_customer(
        legal_name="Perry Onslow", tin_last4="7788", kyc_tier="TIER_1", watchlist_hit=False
    )
    subject = new_account(customer["id"], product_type="CHECKING", open_channel="MOBILE")
    counterpart_x = new_account(customer["id"], product_type="SAVINGS", open_channel="BRANCH")
    counterpart_y = new_account(customer["id"], product_type="SAVINGS", open_channel="BRANCH")
    return customer, subject, counterpart_x, counterpart_y


def _add_six_risk_bearing_links(subject_id, counterpart_x_id, counterpart_y_id):
    for counterpart in (counterpart_x_id, counterpart_y_id):
        for link_type in ("SHARED_DEVICE", "SHARED_ADDRESS", "SHARED_PHONE"):
            link_accounts(subject_id, counterpart, link_type=link_type, confidence_bps=9000)


def test_link_contribution_is_capped_at_twenty_five_points(api, analyst_headers):
    """PRD §3.1: "The link term of the risk score counts every association edge
    that names the account being scored at *either* end — tail or head, in both
    directions — and that satisfies the same two conditions that make an edge
    risk-bearing. Each such edge contributes 5 points, and the total link
    contribution is capped at 25 points, so a sixth risk-bearing edge adds nothing."
    PRD §3.1: "The five terms are added, and the sum is then clamped into the
    range 0 through 100 — no result may fall below zero or exceed 100 — and that
    clamped value is the stored `risk_score`."

    Design: Difficulty/combinatorial_formula/risk_score_five_input_assembly_with_link_cap_and_confidence_gate
    """
    _customer, subject, counterpart_x, counterpart_y = _tier1_mobile_account_with_two_counterparts()

    # TIER_1 (0) + funding NONE (30) + MOBILE (18) = 48 at open.
    assert subject["risk_score"] == 48, (
        f"Expected the provisional score 0 + 30 + 18 = 48, got {subject['risk_score']}"
    )

    _add_six_risk_bearing_links(subject["id"], counterpart_x["id"], counterpart_y["id"])

    scored = read_account(subject["id"], analyst_headers)
    # 0 + 30 + 18 + min(25, 6 * 5) = 73.
    assert scored["risk_score"] == 73, (
        f"Six risk-bearing edges cap at 25 link points, so the score is 73, "
        f"got {scored['risk_score']}"
    )
    assert scored["risk_band"] == "HIGH"
    assert scored["risk_score_basis"] == "REFRESHED"


def test_confidence_gate_and_link_type_gate_keep_edges_out_of_the_link_term(api, analyst_headers):
    """PRD §3.1: "The server derives `is_risk_bearing`, which is true exactly when
    the `link_type` is one of `SHARED_DEVICE`, `SHARED_ADDRESS`, or `SHARED_PHONE`
    **and** `confidence_bps` is at least 6,000 — that is, a detection confidence
    of 60 percent or better on an identity-sharing signal."
    PRD §3.1: "A `TRANSFER_COUNTERPARTY` edge is never risk-bearing no matter how
    confident the detection."
    PRD §3.1: "The link term of the risk score counts every association edge that
    names the account being scored at *either* end — tail or head, in both
    directions — and that satisfies the same two conditions that make an edge
    risk-bearing."

    Design: Difficulty/combinatorial_formula/risk_score_five_input_assembly_with_link_cap_and_confidence_gate
    """
    _customer, subject, counterpart_x, counterpart_y = _tier1_mobile_account_with_two_counterparts()
    _add_six_risk_bearing_links(subject["id"], counterpart_x["id"], counterpart_y["id"])
    assert read_account(subject["id"], analyst_headers)["risk_score"] == 73

    below_gate = link_accounts(
        counterpart_y["id"], subject["id"], link_type="SHARED_DEVICE", confidence_bps=5999
    )
    assert_account_link(below_gate)
    assert below_gate["is_risk_bearing"] is False, (
        "5999 bps is below the 6,000 bps gate, so the edge is not risk-bearing"
    )

    wrong_type = link_accounts(
        counterpart_x["id"], subject["id"],
        link_type="TRANSFER_COUNTERPARTY", confidence_bps=10000,
    )
    assert wrong_type["is_risk_bearing"] is False, (
        "TRANSFER_COUNTERPARTY is never risk-bearing whatever the confidence"
    )

    after = read_account(subject["id"], analyst_headers)
    assert after["risk_score"] == 73, (
        f"Neither non-risk-bearing edge may move the score off 73, got {after['risk_score']}"
    )
    assert after["risk_band"] == "HIGH"
    assert after["risk_score_basis"] == "REFRESHED"


# ===========================================================================
# The risk-band boundary at exactly 60, reached through link creation
# ===========================================================================
def _tier3_account_with_pending_funding_and_counterpart():
    customer = new_customer(
        legal_name="Beatriz Nkemelu", tin_last4="8080", kyc_tier="TIER_3", watchlist_hit=False
    )
    subject = new_account(customer["id"], product_type="CHECKING", open_channel="BRANCH")
    declare_funding_source(subject["id"], source_type="EXTERNAL_ACH", routing_last4="9009")
    counterpart = new_account(customer["id"], product_type="SAVINGS", open_channel="BRANCH")
    return customer, subject, counterpart


def test_link_one_basis_point_below_the_gate_leaves_the_band_elevated(api, analyst_headers):
    """PRD §3.1: "The server derives `is_risk_bearing`, which is true exactly when
    the `link_type` is one of `SHARED_DEVICE`, `SHARED_ADDRESS`, or `SHARED_PHONE`
    **and** `confidence_bps` is at least 6,000 — that is, a detection confidence
    of 60 percent or better on an identity-sharing signal."
    PRD §3.1: "The band follows from the score with an inclusive comparison at
    both edges: a score of 60 or more is `HIGH`, a score of at least 35 but below
    60 is `ELEVATED`, and anything below 35 is `STANDARD`."

    Design: Difficulty/boundary_precision_check/risk_band_flips_to_high_at_exactly_sixty_on_account_link_creation
    """
    _customer, subject, counterpart = _tier3_account_with_pending_funding_and_counterpart()

    link_accounts(
        subject["id"], counterpart["id"], link_type="SHARED_ADDRESS", confidence_bps=5999
    )

    scored = read_account(subject["id"], analyst_headers)
    # TIER_3 (35) + funding PENDING (20) + BRANCH (0) + 0 link points = 55.
    assert scored["risk_score"] == 55, (
        f"A 5999 bps edge contributes nothing, so the score stays at 55, "
        f"got {scored['risk_score']}"
    )
    assert scored["risk_band"] == "ELEVATED", "55 is at or above 35 and below 60"


def test_link_at_exactly_six_thousand_basis_points_lifts_the_band_to_high(api, analyst_headers):
    """PRD §3.1: "The server derives `is_risk_bearing`, which is true exactly when
    the `link_type` is one of `SHARED_DEVICE`, `SHARED_ADDRESS`, or `SHARED_PHONE`
    **and** `confidence_bps` is at least 6,000 — that is, a detection confidence
    of 60 percent or better on an identity-sharing signal."
    PRD §3.1: "Each such edge contributes 5 points, and the total link
    contribution is capped at 25 points, so a sixth risk-bearing edge adds nothing."
    PRD §3.1: "The band follows from the score with an inclusive comparison at
    both edges: a score of 60 or more is `HIGH`, a score of at least 35 but below
    60 is `ELEVATED`, and anything below 35 is `STANDARD`."

    Design: Difficulty/boundary_precision_check/risk_band_flips_to_high_at_exactly_sixty_on_account_link_creation
    """
    _customer, subject, counterpart = _tier3_account_with_pending_funding_and_counterpart()
    link_accounts(
        subject["id"], counterpart["id"], link_type="SHARED_ADDRESS", confidence_bps=5999
    )
    assert read_account(subject["id"], analyst_headers)["risk_score"] == 55

    at_gate = link_accounts(
        subject["id"], counterpart["id"], link_type="SHARED_DEVICE", confidence_bps=6000
    )
    assert at_gate["is_risk_bearing"] is True, "6,000 bps is at the gate, which is inclusive"

    scored = read_account(subject["id"], analyst_headers)
    assert scored["risk_score"] == 60, (
        f"55 plus one 5-point risk-bearing edge is exactly 60, got {scored['risk_score']}"
    )
    assert scored["risk_band"] == "HIGH", "60 or more is HIGH under the inclusive comparison"


# ===========================================================================
# Depositor registration
# ===========================================================================
def test_registering_a_depositor_applies_the_declared_defaults(api, ops_admin_headers,
                                                               analyst_headers):
    """PRD §3.1: "`kyc_tier` records the know-your-customer diligence tier reached
    at onboarding and takes one of `TIER_1`, `TIER_2`, or `TIER_3`, where `TIER_1`
    is the most fully documented file and `TIER_3` the least; when the caller omits
    it, the depositor is recorded at `TIER_2`."
    PRD §3.1: "`watchlist_hit` is a boolean asserting that onboarding screening
    returned a sanctions or negative-news hit, and defaults to false when omitted."
    PRD §3.1: "A freshly registered depositor therefore reads back with
    `preservation_hold_active` false and `open_fraud_case_count` zero."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix; clients never
    supply it."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/create_customer_applies_declared_defaults_and_system_fields
    """
    response = api.create_customer(
        {"legal_name": "Minimal Depositor", "tin_last4": "0001"}, ops_admin_headers
    )
    customer = validate_success(response, 201)

    assert customer["kyc_tier"] == "TIER_2", "An omitted kyc_tier is recorded as TIER_2"
    assert customer["watchlist_hit"] is False, "An omitted watchlist_hit defaults to false"
    assert customer["version"] == 1

    reread = validate_success(api.get_customer(customer["id"], analyst_headers))
    assert_customer(reread)
    assert reread["preservation_hold_active"] is False
    assert reread["open_fraud_case_count"] == 0


def test_registering_a_depositor_without_a_legal_name_is_rejected(api, ops_admin_headers):
    """PRD §3.1: "Registration of a depositor is an `OperationsAdmin` activity and
    captures very little: a `legal_name` of 1 to 120 characters that may not be
    blank, and a `tin_last4` consisting of exactly four ASCII digits — the last
    four digits of the taxpayer identification number, which later doubles as the
    shared secret behind step-up verification."
    PRD §2.10: "**Body shape.** Every required field present, every value of its
    declared type, every enumeration value a declared member, every `_cents` field
    an integer inside its stated range, every timestamp a valid ISO 8601 UTC
    instant, `release_window_end_at` strictly after `release_effective_at`,
    `preservation_end_at` strictly after `preservation_start_at`, `response_due_at`
    strictly after the logical clock at creation time, a `return_reason` present
    when a settlement outcome is a return, and a `return_reason` present when a
    referral adjudication is a return. Any failure is `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/create_customer_without_legal_name_returns_invalid_request
    """
    response = api.create_customer({"tin_last4": "0002"}, ops_admin_headers)
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(error["error_id"], str) and isinstance(error["message"], str)


def test_opening_an_account_for_an_unknown_depositor_is_a_body_reference_404(api,
                                                                            ops_admin_headers):
    """PRD §2.10: "**Body reference existence.** Every entity `id` supplied in the
    request *body* resolves to a stored row — `customer_id` when opening an
    account, `from_account_id` and `to_account_id` when recording an association
    link, `drawee_account_id` when taking a deposit, and `primary_account_id` when
    opening a case manually — failing with `ERR_CUSTOMER_NOT_FOUND` or
    `ERR_ACCOUNT_NOT_FOUND` (HTTP 404) as appropriate."

    Design: Corner/entities/create_account_with_unrecognised_customer_id_returns_customer_not_found
    """
    response = api.create_account(
        {
            "customer_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "product_type": "CHECKING",
            "open_channel": "BRANCH",
        },
        ops_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_opening_an_account_ignores_client_supplied_system_fields(api, ops_admin_headers,
                                                                  analyst_headers):
    """PRD §3.1: "A new account starts with `lifecycle_status` `PENDING_FUNDING`
    and `access_posture` `NORMAL`, with `ledger_balance_cents`,
    `available_balance_cents`, `held_amount_cents`, `charged_off_amount_cents`,
    `ato_score`, and `step_up_failure_count` all zero, `ato_indicator_codes` an
    empty array, and `closure_scheduled_at` and `closure_reason` both null."
    PRD §3.1: "The `PROVISIONAL_AT_OPEN` variant runs inside account opening,
    before any funding source or association edge can possibly exist for the new
    account; it *forces* the funding posture to none — the full 30 points — and
    *forces* the risk-bearing link count to zero, regardless of what a later read
    would find, and it writes `risk_score_basis` as `PROVISIONAL_AT_OPEN`."
    PRD §3.1: "The band follows from the score with an inclusive comparison at
    both edges: a score of 60 or more is `HIGH`, a score of at least 35 but below
    60 is `ELEVATED`, and anything below 35 is `STANDARD`."

    Design: Corner/entities/deposit_account_lifecycle_and_balance_inputs_are_ignored_input_ignored
    """
    customer = new_customer(
        legal_name="Ignored Fields Depositor", tin_last4="0003",
        kyc_tier="TIER_2", watchlist_hit=False,
    )

    response = api.create_account(
        {
            "customer_id": customer["id"],
            "product_type": "CHECKING",
            "open_channel": "BRANCH",
            "lifecycle_status": "ACTIVE",
            "ledger_balance_cents": 999999,
            "risk_score": 1,
        },
        ops_admin_headers,
    )
    account = validate_success(response, 201)

    assert account["lifecycle_status"] == "PENDING_FUNDING", (
        "lifecycle_status is a server field; a new account always starts PENDING_FUNDING"
    )
    assert account["ledger_balance_cents"] == 0
    # TIER_2 (15) + funding NONE (30) + BRANCH (0) = 45.
    assert account["risk_score"] == 45, (
        f"Expected the server-computed 15 + 30 + 0 = 45, got {account['risk_score']}"
    )

    reread = read_account(account["id"], analyst_headers)
    assert reread["risk_band"] == "ELEVATED"
    assert reread["version"] == 1


def test_association_link_confidence_above_ten_thousand_is_rejected(api, analyst_headers):
    """PRD §2.6: "Percentages and ratios that are not money are integers too:
    `confidence_bps` on an association link is a whole number of basis points from
    0 through 10,000 inclusive, and `uncollected_ratio_bps` reported by a kiting
    scan is a whole number of basis points."
    PRD §2.10: "**Body shape.** Every required field present, every value of its
    declared type, every enumeration value a declared member, every `_cents` field
    an integer inside its stated range, every timestamp a valid ISO 8601 UTC
    instant, `release_window_end_at` strictly after `release_effective_at`,
    `preservation_end_at` strictly after `preservation_start_at`, `response_due_at`
    strictly after the logical clock at creation time, a `return_reason` present
    when a settlement outcome is a return, and a `return_reason` present when a
    referral adjudication is a return. Any failure is `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/account_link_confidence_out_of_range_returns_invalid_request
    """
    customer = new_customer(legal_name="Range Check Depositor", tin_last4="0004")
    first = new_account(customer["id"], product_type="CHECKING", open_channel="BRANCH")
    second = new_account(customer["id"], product_type="SAVINGS", open_channel="BRANCH")

    response = api.create_account_link(
        {
            "from_account_id": first["id"],
            "to_account_id": second["id"],
            "link_type": "SHARED_DEVICE",
            "confidence_bps": 10001,
        },
        analyst_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _rows, meta = validate_paginated(api.list_account_links(first["id"], analyst_headers))
    assert meta["total_count"] == 0, "The rejected request must not have created an edge"


def test_customer_account_listing_paginates_and_filters_by_lifecycle_status(api, analyst_headers):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters.
    `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset`
    defaults to 0 and has a minimum of 0."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside `meta`, where `total_count` is the number of rows matching
    the filter before pagination is applied and `has_more` is true exactly when
    rows remain beyond the current page."
    PRD §2.3: "Accounts owned by a customer may be filtered by `lifecycle_status`."

    Design: Corner/entities/customer_accounts_listing_paginates_with_limit_and_offset
    """
    customer = new_customer(legal_name="Paginated Depositor", tin_last4="0005")
    new_account(customer["id"], product_type="CHECKING", open_channel="BRANCH")
    new_account(customer["id"], product_type="SAVINGS", open_channel="ONLINE")
    new_account(customer["id"], product_type="MONEY_MARKET", open_channel="MOBILE")

    first_page, first_meta = validate_paginated(
        api.list_customer_accounts(customer["id"], analyst_headers, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"Expected 2 rows on a page of size 2, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_customer_accounts(customer["id"], analyst_headers, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    filtered, filtered_meta = validate_paginated(
        api.list_customer_accounts(
            customer["id"], analyst_headers, params={"lifecycle_status": "ACTIVE"}
        )
    )
    assert filtered_meta["total_count"] == 0, "All three accounts are still PENDING_FUNDING"
    assert filtered == []


# ===========================================================================
# Declaring a funding source
# ===========================================================================
def test_declaring_a_funding_source_mints_the_secret_and_skips_declared(api, ops_admin_headers,
                                                                        analyst_headers):
    """PRD §3.2: "The row is born in `DECLARED` status with `attempt_count` and
    `total_attempt_count` both at 0 and `verified_at` null, but `DECLARED` is
    never observable through the API: within the same request the server mints
    `micro_deposit_cents`, an integer from 1 through 99 inclusive, and advances
    `verification_status` to `MICRO_DEPOSIT_SENT`."
    PRD §3.2: "Declaring the source also re-evaluates the account's risk under the
    `REFRESHED` variant, because the funding posture has just moved from none to
    pending, dropping the score by 10 points."

    Design: Corner/state_machines/funding_source_is_micro_deposit_sent_on_creation_never_observably_declared
    """
    customer = new_customer(legal_name="Auto Transition Depositor", tin_last4="0007")
    account = new_account(customer["id"], product_type="CHECKING", open_channel="BRANCH")

    response = api.create_funding_source(
        account["id"], {"source_type": "EXTERNAL_ACH", "routing_last4": "1002"}, ops_admin_headers
    )
    source = validate_success(response, 201)

    assert source["verification_status"] == "MICRO_DEPOSIT_SENT", (
        "DECLARED is never observable: the creation response already reads MICRO_DEPOSIT_SENT"
    )
    assert source["attempt_count"] == 0
    assert isinstance(source["micro_deposit_cents"], int)
    assert 1 <= source["micro_deposit_cents"] <= 99, (
        f"The minted trial amount must lie in 1..99, got {source['micro_deposit_cents']}"
    )

    rows, meta = validate_paginated(api.list_funding_sources(account["id"], analyst_headers))
    assert meta["total_count"] == 1
    assert rows[0]["verification_status"] == "MICRO_DEPOSIT_SENT"
    assert rows[0]["total_attempt_count"] == 0

    reread = read_account(account["id"], analyst_headers)
    assert reread["lifecycle_status"] == "PENDING_FUNDING"
    # TIER_2 (15) + funding PENDING (20) + BRANCH (0) = 35.
    assert reread["risk_score"] == 35, (
        f"The refreshed pending-posture score is 35, got {reread['risk_score']}"
    )


# ===========================================================================
# Version trail on the deposit account
# ===========================================================================
def test_account_version_advances_on_every_request_that_mutates_the_row(api, ops_admin_headers,
                                                                        analyst_headers):
    """PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly 1 on every mutation of that row."
    PRD §2.4: "Version increments are not decorative — they are the observable
    signal that a cascade actually touched a row."
    PRD §3.2: "The account's `version` advances by 1 and its `updated_at` is
    refreshed."
    PRD §2.4: "`created_at` and `updated_at` are ISO 8601 UTC timestamps with
    three fractional digits, taken from the logical clock described in §2.5."

    Design: Corner/cross_cutting_complexity_layers/deposit_account_version_advances_on_every_mutating_request
    """
    customer = new_customer(legal_name="Version Trail Depositor", tin_last4="0045")

    account = validate_success(
        api.create_account(
            {"customer_id": customer["id"], "product_type": "CHECKING", "open_channel": "BRANCH"},
            ops_admin_headers,
        ),
        201,
    )
    assert account["version"] == 1, "A freshly created row starts at version 1"

    source = declare_funding_source(account["id"], routing_last4="1031")
    after_declaration = read_account(account["id"], analyst_headers)
    assert after_declaration["version"] > account["version"], (
        "Declaring a source rewrites the account's risk fields, so its version advances"
    )

    submit_verification(source["id"], source["micro_deposit_cents"])
    after_verification = read_account(account["id"], analyst_headers)
    assert after_verification["version"] > after_declaration["version"], (
        "Verification drives PENDING_FUNDING -> ACTIVE and advances the version"
    )

    take_deposit(account["id"], item_type="CHECK", amount_cents=30000)
    after_deposit = read_account(account["id"], analyst_headers)
    assert after_deposit["version"] > after_verification["version"], (
        "Posting the deposit rewrites the balances and advances the version"
    )
    assert_same_instant(
        after_deposit["updated_at"], fx.DEFAULT_LOGICAL_CLOCK_UTC, "updated_at"
    )


# ===========================================================================
# Trial-deposit verification: the retry loop and the lifetime budget
# ===========================================================================
def test_resend_restarts_the_per_secret_counter_and_keeps_the_lifetime_total(api,
                                                                             ops_admin_headers,
                                                                             analyst_headers):
    """PRD §3.2: "A **mismatched** submission is a state transition, not an error:
    it returns HTTP 200 with the updated funding source."
    PRD §3.2: "Every attempt, matching or not, increments both `attempt_count` and
    `total_attempt_count` by 1."
    PRD §3.2: "A re-send mints a fresh `micro_deposit_cents` in the same
    1-through-99 range, resets `attempt_count` to 0, leaves `total_attempt_count`
    untouched, and returns the status to `MICRO_DEPOSIT_SENT` — closing the retry
    loop `MICRO_DEPOSIT_SENT → FAILED_ATTEMPT → MICRO_DEPOSIT_SENT`."
    PRD §3.2: "A **matching** submission moves `verification_status` to `VERIFIED`
    and stamps `verified_at` from the logical clock, whether the source was in
    `MICRO_DEPOSIT_SENT` or in `FAILED_ATTEMPT` when the correct value finally
    arrived."

    Design: Corner/state_machines/funding_source_resend_loops_back_to_micro_deposit_sent_with_a_fresh_secret
    """
    customer = new_customer(legal_name="Retry Loop Depositor", tin_last4="0008")
    account = new_account(customer["id"], product_type="CHECKING", open_channel="BRANCH")
    source = declare_funding_source(account["id"], routing_last4="1003")

    mismatch_response = api.submit_verification_attempt(
        source["id"], {"micro_deposit_cents": 0}, ops_admin_headers
    )
    failed = validate_success(mismatch_response, 200)
    assert failed["verification_status"] == "FAILED_ATTEMPT", (
        "A mismatched trial amount is a transition, not an error"
    )
    assert failed["attempt_count"] == 1
    assert failed["total_attempt_count"] == 1

    resent = validate_success(api.resend_micro_deposits(source["id"], ops_admin_headers), 200)
    assert resent["verification_status"] == "MICRO_DEPOSIT_SENT"
    assert resent["attempt_count"] == 0, "A re-send resets the per-secret counter"
    assert resent["total_attempt_count"] == 1, "A re-send leaves the lifetime total untouched"
    assert 1 <= resent["micro_deposit_cents"] <= 99

    verified = submit_verification(source["id"], resent["micro_deposit_cents"])
    assert verified["verification_status"] == "VERIFIED"

    account_after = read_account(account["id"], analyst_headers)
    assert account_after["lifecycle_status"] == "ACTIVE"
    # TIER_2 (15) + funding VERIFIED (0) + BRANCH (0) = 15.
    assert account_after["risk_score"] == 15
    assert account_after["risk_band"] == "STANDARD"
    assert account_after["risk_score_basis"] == "REFRESHED"


def test_fifth_mismatched_attempt_blocks_the_source_for_good(api, ops_admin_headers,
                                                             analyst_headers):
    """PRD §3.2: "If instead the incremented `total_attempt_count` reaches five,
    the status becomes `BLOCKED`: the account stays in `PENDING_FUNDING`, and no
    further attempt and no re-send is ever accepted on that source."
    PRD §3.2: "If the lifetime budget still has room — that is, if the incremented
    `total_attempt_count` remains strictly below five — the status becomes
    `FAILED_ATTEMPT`, and a further mismatch from `FAILED_ATTEMPT` simply leaves it
    in `FAILED_ATTEMPT` with the counters advanced again."
    PRD §3.2: "Both funding operations share one state gate, reported as
    `ERR_FUNDING_INVALID_STATE` (HTTP 409). A verification attempt requires the
    source to be in `MICRO_DEPOSIT_SENT` or `FAILED_ATTEMPT`, so an attempt against
    a source that is `VERIFIED`, `BLOCKED`, or still nominally `DECLARED` is
    refused."

    Design: Corner/state_machines/funding_source_blocks_after_the_lifetime_attempt_budget_is_exhausted
    """
    customer = new_customer(legal_name="Blocked Funding Depositor", tin_last4="0009")
    account = new_account(customer["id"], product_type="CHECKING", open_channel="BRANCH")
    source = declare_funding_source(account["id"], routing_last4="1004")

    fourth = None
    for _ in range(4):
        fourth = validate_success(
            api.submit_verification_attempt(
                source["id"], {"micro_deposit_cents": 0}, ops_admin_headers
            ),
            200,
        )
    assert fourth["verification_status"] == "FAILED_ATTEMPT"
    assert fourth["total_attempt_count"] == 4

    fifth = validate_success(
        api.submit_verification_attempt(source["id"], {"micro_deposit_cents": 0}, ops_admin_headers),
        200,
    )
    assert fifth["verification_status"] == "BLOCKED", (
        "The fifth attempt exhausts the lifetime budget of five"
    )
    assert fifth["total_attempt_count"] == 5

    validate_error(
        api.submit_verification_attempt(source["id"], {"micro_deposit_cents": 0}, ops_admin_headers),
        ApiErrorId.ERR_FUNDING_INVALID_STATE.value,
    )
    validate_error(
        api.resend_micro_deposits(source["id"], ops_admin_headers),
        ApiErrorId.ERR_FUNDING_INVALID_STATE.value,
    )

    assert read_account(account["id"], analyst_headers)["lifecycle_status"] == "PENDING_FUNDING"


def test_duplicate_and_self_referential_association_edges_are_rejected(api, analyst_headers):
    """PRD §3.1: "Two structural rules guard edge creation. An account may not be
    linked to itself: if `from_account_id` equals `to_account_id`, the request is
    refused with `ERR_SELF_LINK` (HTTP 422). And the same triple of tail, head, and
    `link_type` may exist only once; a repeat is refused with `ERR_DUPLICATE_LINK`
    (HTTP 409). Note that the pair is directional and the type discriminates, so an
    edge from A to B of type `SHARED_DEVICE`, an edge from B to A of type
    `SHARED_DEVICE`, and an edge from A to B of type `SHARED_PHONE` are three
    distinct, all-permitted rows."
    PRD §3.1: "The server derives `is_risk_bearing`, which is true exactly when the
    `link_type` is one of `SHARED_DEVICE`, `SHARED_ADDRESS`, or `SHARED_PHONE`
    **and** `confidence_bps` is at least 6,000 — that is, a detection confidence of
    60 percent or better on an identity-sharing signal."

    Design: Corner/validations/duplicate_and_self_referential_account_links_are_rejected
    """
    customer = new_customer(legal_name="Link Uniqueness Depositor", tin_last4="0030")
    first = new_account(customer["id"], product_type="CHECKING", open_channel="BRANCH")
    second = new_account(customer["id"], product_type="SAVINGS", open_channel="BRANCH")

    original = link_accounts(
        first["id"], second["id"], link_type="SHARED_DEVICE", confidence_bps=8000
    )

    validate_error(
        api.create_account_link(
            {
                "from_account_id": first["id"],
                "to_account_id": second["id"],
                "link_type": "SHARED_DEVICE",
                "confidence_bps": 9500,
            },
            analyst_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_LINK.value,
    )

    validate_error(
        api.create_account_link(
            {
                "from_account_id": first["id"],
                "to_account_id": first["id"],
                "link_type": "SHARED_PHONE",
                "confidence_bps": 9500,
            },
            analyst_headers,
        ),
        ApiErrorId.ERR_SELF_LINK.value,
    )

    reversed_edge = validate_success(
        api.create_account_link(
            {
                "from_account_id": second["id"],
                "to_account_id": first["id"],
                "link_type": "SHARED_DEVICE",
                "confidence_bps": 8000,
            },
            analyst_headers,
        ),
        201,
    )
    assert reversed_edge["is_risk_bearing"] is True

    rows, meta = validate_paginated(api.list_account_links(first["id"], analyst_headers))
    assert meta["total_count"] == 2, "The reversed direction is a distinct, permitted edge"
    assert {row["id"] for row in rows} == {original["id"], reversed_edge["id"]}
