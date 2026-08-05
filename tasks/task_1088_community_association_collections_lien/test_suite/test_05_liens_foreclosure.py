"""Lien recording gates (minimum, validation period, predecessor notice, dispute
pause), foreclosure referral gates (lien-required, SoD), error precedence, and
the foreclosure-sale charge-off cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, TEST_USERS,
    make_compliance_officer_headers,
    fixtures,
)

AGENT = TEST_USERS["collections_agent_headers"]
TRUSTEE = TEST_USERS["trust_accountant_headers"]
OFFICER1 = make_compliance_officer_headers("officer-1")
OFFICER2 = make_compliance_officer_headers("officer-2")


# --- boundary_precision_check / bp_lien_minimum_exact_ge (queue A, >=2 tests) ---

def test_lien_records_at_exact_minimum(api):
    """PRD §3.6: "Finally, the account's `total_balance_cents` must be at least the lien
    minimum of 180,000 cents (one thousand eight hundred dollars); below it, recording is
    refused with `ERR_LIEN_MINIMUM_NOT_MET`."
    PRD §3.6: "A recorded lien captures `recorded_amount_cents` as a snapshot of the
    account's `total_balance_cents` at the recording instant"

    Design: Difficulty/boundary_precision_check/bp_lien_minimum_exact_ge
    """
    base = fixtures.setup_sent_intent_to_lien(api, amount_cents=180000,
                                              sent_date="2026-01-01T00:00:00Z")
    fixtures.set_clock(api, "2026-01-31T00:00:00Z")
    lien = validate_success(api.create_lien({"account_id": base["account"]["id"]}, OFFICER1),
                            expected_status=201)
    assert lien["status"] == "RECORDED"
    assert lien["recorded_amount_cents"] == 180000


def test_lien_at_minimum_moves_account_to_lien(api):
    """PRD §3.6: "The lien opens in `RECORDED` — its `status` ranges over `RECORDED`,
    `STAYED`, `FORECLOSING`, and `RELEASED` — and moves the account from `DELINQUENT` to
    `LIEN`."

    Design: Difficulty/boundary_precision_check/bp_lien_minimum_exact_ge
    """
    base = fixtures.setup_sent_intent_to_lien(api, amount_cents=180000,
                                              sent_date="2026-01-01T00:00:00Z")
    fixtures.set_clock(api, "2026-01-31T00:00:00Z")
    validate_success(api.create_lien({"account_id": base["account"]["id"]}, OFFICER1),
                     expected_status=201)
    acct = get_success_data(api.get_account(base["account"]["id"], AGENT))
    assert acct["status"] == "LIEN"


# --- cross_entity_state_dependency / ce_lien_requires_notice_sent (queue A, >=2 tests) ---

def test_lien_without_sent_notice_rejected(api):
    """PRD §3.6: "A qualifying predecessor must exist: at least one notice of type
    `INTENT_TO_LIEN` on the account must be in `SENT`; absent that, the recording is refused
    with `ERR_DEMAND_NOTICE_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/ce_lien_requires_notice_sent
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    base = fixtures.setup_delinquent_account(api, amount_cents=200000)
    # INTENT_TO_LIEN drafted but never SENT
    get_success_data(api.create_notice(
        {"account_id": base["account"]["id"], "notice_type": "INTENT_TO_LIEN"}, AGENT))
    resp = api.create_lien({"account_id": base["account"]["id"]}, OFFICER1)
    validate_error(resp, ApiErrorId.ERR_DEMAND_NOTICE_REQUIRED.value)


def test_lien_refusal_leaves_account_delinquent_and_no_lien(api):
    """PRD §3.6: "A qualifying predecessor must exist: at least one notice of type
    `INTENT_TO_LIEN` on the account must be in `SENT`; absent that, the recording is refused
    with `ERR_DEMAND_NOTICE_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/ce_lien_requires_notice_sent
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    base = fixtures.setup_delinquent_account(api, amount_cents=200000)
    acct_id = base["account"]["id"]
    get_success_data(api.create_notice(
        {"account_id": acct_id, "notice_type": "INTENT_TO_LIEN"}, AGENT))
    validate_error(api.create_lien({"account_id": acct_id}, OFFICER1),
                   ApiErrorId.ERR_DEMAND_NOTICE_REQUIRED.value)
    acct = get_success_data(api.get_account(acct_id, AGENT))
    assert acct["status"] == "DELINQUENT"
    liens, _ = validate_paginated(api.list_liens(AGENT, params={"account_id": acct_id}))
    assert liens == []


# --- cross_entity_state_dependency / ce_referral_requires_lien_recorded (queue A, >=2) ---

def test_referral_against_released_lien_rejected(api):
    """PRD §3.6: "Referral also requires that a `RECORDED` lien exist on the account
    (`ERR_LIEN_REQUIRED`)"

    Design: Difficulty/cross_entity_state_dependency/ce_referral_requires_lien_recorded
    """
    base = fixtures.setup_recorded_lien(api, amount_cents=200000,
                                        sent_date="2026-01-01T00:00:00Z",
                                        record_date="2026-02-01T00:00:00Z", officer_id="officer-1")
    lien_id = base["lien"]["id"]
    validate_success(api.transition_lien(lien_id, "RELEASED", OFFICER1))
    resp = api.create_foreclosure_referral(
        {"account_id": base["account"]["id"], "lien_id": lien_id, "attorney_name": "Roe LLP"},
        OFFICER2)
    validate_error(resp, ApiErrorId.ERR_LIEN_REQUIRED.value)


def test_released_lien_is_released_state(api):
    """PRD §3.6: "A `ComplianceOfficer` may manually release a `RECORDED` lien to `RELEASED`."

    Design: Difficulty/cross_entity_state_dependency/ce_referral_requires_lien_recorded
    """
    base = fixtures.setup_recorded_lien(api, amount_cents=200000,
                                        sent_date="2026-01-01T00:00:00Z",
                                        record_date="2026-02-01T00:00:00Z", officer_id="officer-1")
    lien_id = base["lien"]["id"]
    released = validate_success(api.transition_lien(lien_id, "RELEASED", OFFICER1))
    assert released["status"] == "RELEASED"


# --- priority_pair_validation_conflict / pp_temporal_beats_minimum (queue A, >=2 tests) ---

def test_validation_period_outranks_lien_minimum(api):
    """PRD §2.7: "10. **Validation-period elapse** — the FDCPA validation period has run since
    the intent-to-lien notice was sent, else `ERR_VALIDATION_PERIOD_ACTIVE` (409)."
    PRD §2.7: "12. **Lien minimum** — the account balance meets the lien-recording minimum,
    else `ERR_LIEN_MINIMUM_NOT_MET` (422)."

    Design: Difficulty/priority_pair_validation_conflict/pp_temporal_beats_minimum
    """
    # balance 100000 (< 180000 min) AND validation period not elapsed (0 days)
    base = fixtures.setup_sent_intent_to_lien(api, amount_cents=100000,
                                              sent_date="2026-05-01T00:00:00Z")
    resp = api.create_lien({"account_id": base["account"]["id"]}, OFFICER1)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PERIOD_ACTIVE.value)


def test_temporal_conflict_leaves_account_delinquent(api):
    """PRD §2.7: "the first failure determines the error returned"
    PRD §3.6: "Given a sent intent-to-lien notice, the FDCPA validation period must have
    fully elapsed — (now minus that notice's `sent_date`) at least 30 days — else
    `ERR_VALIDATION_PERIOD_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/pp_temporal_beats_minimum
    """
    base = fixtures.setup_sent_intent_to_lien(api, amount_cents=100000,
                                              sent_date="2026-05-01T00:00:00Z")
    acct_id = base["account"]["id"]
    validate_error(api.create_lien({"account_id": acct_id}, OFFICER1),
                   ApiErrorId.ERR_VALIDATION_PERIOD_ACTIVE.value)
    acct = get_success_data(api.get_account(acct_id, AGENT))
    assert acct["status"] == "DELINQUENT"


# --- priority_pair_validation_conflict / pp_dispute_beats_demand (queue A, >=2 tests) ---

def _account_with_disputed_intent(api):
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    base = fixtures.setup_delinquent_account(api, amount_cents=200000)
    acct_id = base["account"]["id"]
    notice = get_success_data(api.create_notice(
        {"account_id": acct_id, "notice_type": "INTENT_TO_LIEN"}, AGENT))
    validate_success(api.transition_notice(notice["id"], "SENT", AGENT))
    fixtures.set_clock(api, "2026-05-05T00:00:00Z")
    validate_success(api.transition_notice(notice["id"], "DISPUTED", AGENT))
    return acct_id


def test_dispute_pause_outranks_predecessor(api):
    """PRD §2.7: "8. **FDCPA dispute pause** — while any notice on the account is `DISPUTED`,
    lien recording and foreclosure referral are blocked, else `ERR_ACTIVE_DISPUTE` (409)."
    PRD §2.7: "9. **Predecessor existence** — the required predecessor resource exists
    (checked *before* any temporal elapse test), else `ERR_DEMAND_NOTICE_REQUIRED` or
    `ERR_LIEN_REQUIRED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/pp_dispute_beats_demand
    """
    acct_id = _account_with_disputed_intent(api)
    resp = api.create_lien({"account_id": acct_id}, OFFICER1)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_DISPUTE.value)


def test_dispute_pause_blocks_lien_account_stays_delinquent(api):
    """PRD §3.6: "The account must not be under a bankruptcy stay (`ERR_AUTOMATIC_STAY`) and
    must have no `DISPUTED` notice (`ERR_ACTIVE_DISPUTE`)."

    Design: Difficulty/priority_pair_validation_conflict/pp_dispute_beats_demand
    """
    acct_id = _account_with_disputed_intent(api)
    validate_error(api.create_lien({"account_id": acct_id}, OFFICER1),
                   ApiErrorId.ERR_ACTIVE_DISPUTE.value)
    acct = get_success_data(api.get_account(acct_id, AGENT))
    assert acct["status"] == "DELINQUENT"


# --- Queue B ---

def test_lien_below_minimum_rejected(api):
    """PRD §3.6: "Finally, the account's `total_balance_cents` must be at least the lien
    minimum of 180,000 cents (one thousand eight hundred dollars); below it, recording is
    refused with `ERR_LIEN_MINIMUM_NOT_MET`."

    Design: Corner/validations/lien_minimum_below_threshold_rejected
    """
    base = fixtures.setup_sent_intent_to_lien(api, amount_cents=179999,
                                              sent_date="2026-01-01T00:00:00Z")
    fixtures.set_clock(api, "2026-01-31T00:00:00Z")
    resp = api.create_lien({"account_id": base["account"]["id"]}, OFFICER1)
    validate_error(resp, ApiErrorId.ERR_LIEN_MINIMUM_NOT_MET.value)


def test_validation_period_29_days_still_active(api):
    """PRD §3.6: "Given a sent intent-to-lien notice, the FDCPA validation period must have
    fully elapsed — (now minus that notice's `sent_date`) at least 30 days — else
    `ERR_VALIDATION_PERIOD_ACTIVE`."

    Design: Corner/validations/validation_period_29_days_active
    """
    base = fixtures.setup_sent_intent_to_lien(api, amount_cents=200000,
                                              sent_date="2026-01-01T00:00:00Z")
    fixtures.set_clock(api, "2026-01-30T00:00:00Z")  # 29 days
    resp = api.create_lien({"account_id": base["account"]["id"]}, OFFICER1)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PERIOD_ACTIVE.value)


def test_same_officer_referral_sod_denied(api):
    """PRD §3.6: "the officer creating the referral must differ from the officer who recorded
    the referenced lien — if `referred_by_user_id` would equal that lien's
    `recorded_by_user_id`, the referral is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/same_officer_lien_and_referral_sod_denied
    """
    base = fixtures.setup_recorded_lien(api, amount_cents=200000,
                                        sent_date="2026-01-01T00:00:00Z",
                                        record_date="2026-02-01T00:00:00Z", officer_id="officer-1")
    resp = api.create_foreclosure_referral(
        {"account_id": base["account"]["id"], "lien_id": base["lien"]["id"],
         "attorney_name": "Firm B"}, OFFICER1)  # same officer-1 that recorded the lien
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_trust_accountant_cannot_record_lien(api):
    """PRD §2.1: "A syntactically authenticated request that attempts an operation its role is
    not permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/trust_accountant_cannot_record_lien_unauthorized
    """
    assoc, acct = fixtures.setup_account(api, {"name": "Urn HOA"})
    resp = api.create_lien({"account_id": acct["id"]}, TRUSTEE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_foreclosure_sale_charges_off_and_waives(api):
    """PRD §3.6: "Completing a sale (`FILED → SALE_COMPLETED`), again barred under bankruptcy
    (`ERR_AUTOMATIC_STAY`), moves the account from `FORECLOSURE` to `CHARGED_OFF` — which
    itself waives every `OPEN` or `PARTIAL` assessment on the account — and releases the
    referenced lien from `FORECLOSING` to `RELEASED`."

    Design: Corner/state_machines/foreclosure_sale_charges_off_and_waives
    """
    base = fixtures.setup_filed_referral(api, amount_cents=200000,
                                         sent_date="2026-01-01T00:00:00Z",
                                         record_date="2026-02-01T00:00:00Z")
    ref_id = base["referral"]["id"]
    sale = validate_success(api.transition_foreclosure_referral(ref_id, "SALE_COMPLETED", OFFICER2))
    assert sale["status"] == "SALE_COMPLETED"
    acct = get_success_data(api.get_account(base["account"]["id"], AGENT))
    assert acct["status"] == "CHARGED_OFF"
    asm = get_success_data(api.get_assessment(base["assessment"]["id"], AGENT))
    assert asm["status"] == "WAIVED"
    lien = get_success_data(api.get_lien(base["lien"]["id"], AGENT))
    assert lien["status"] == "RELEASED"
