"""Scoring, decay and penalty arithmetic of the DMCA takedown chain.

Every test builds its own world through the public API against a freshly
restarted server, then pins a single number the PRD derives uniquely.
"""
from test_helpers import (
    AGENT,
    INVESTIGATOR,
    NOTICE_WEIGHT_ACCURACY_STATEMENT,
    NOTICE_WEIGHT_CONTACT_EMAIL,
    OFFICER,
    TEST_DEFAULTS,
    assert_four_decimal_places,
    assert_instant_equals,
    assert_money_int,
    assert_two_decimal_places,
    claims_of_notice,
    create_account,
    create_active_reference_file,
    create_content_item,
    create_counter_notice,
    create_enrolled_rights_holder,
    create_misrepresentation_case,
    create_notice,
    create_notice_payload,
    create_processed_notice,
    get_account,
    get_claim,
    get_content_item,
    get_notice,
    get_rights_holder,
    get_success_data,
    list_account_strikes,
    list_account_termination_cases,
    make_abuse_investigator_headers,
    promote_tier,
    set_clock,
    setup_disabled_claim,
    setup_documented_provider,
    validate_counter_notice,
    validate_notice,
    validate_paginated,
    validate_success,
)

# A reference fingerprint sharing a 30-character leading run with the hosted
# material's fingerprint: 30 / 32 * 0.80 + 0.20 registration bonus = 0.9500.
_REFERENCE_FINGERPRINT_30_OF_32 = "0123456789abcdef0123456789abcd00"
_REGISTRATION_NUMBER = "SR0000991122"
_CLAIMED_URL = "https://northstar.example/v/1"


def _notice_payload_without(rights_holder_id, claimed_urls, *omitted_elements):
    """A statutorily complete notice payload with named elements left absent."""
    payload = create_notice_payload(rights_holder_id, claimed_urls)
    for element in omitted_elements:
        payload.pop(element, None)
    return payload


def _misrepresentation_cases_of(api, rights_holder_id):
    return validate_paginated(
        api.list_misrepresentation_cases(
            INVESTIGATOR, {"rights_holder_id": rights_holder_id}
        )
    )


def test_counter_notice_carrying_every_element_scores_exactly_one_hundred(api):
    """PRD §3.7: "Six elements carry weight, summing to 100: the signature
    contributes 20, material identification 20, the good-faith-mistake statement
    22, the contact address 26, consent to jurisdiction 6, and consent to service
    of process 6."

    Design: Corner/calculations/counter_notice_with_every_element_scores_exactly_one_hundred
    """
    scene = setup_disabled_claim()
    account, claim, item = scene["account"], scene["claim"], scene["item"]

    counter = create_counter_notice(claim["id"], account["id"])
    assert counter["completeness_score"] == 0
    assert counter["status"] == "RECEIVED"

    data = validate_success(
        api.validate_counter_notice(counter["id"], AGENT), expected_status=200
    )

    assert data["completeness_score"] == 100
    assert data["status"] == "VALIDATED"
    assert data["rejection_reason"] is None
    # account_id is copied from the owner of the claim's content item, never
    # taken from the payload.
    assert data["account_id"] == account["id"]

    assert get_claim(claim["id"])["status"] == "COUNTER_NOTICED"
    disputed_item = get_content_item(item["id"])
    assert disputed_item["dispute_status"] == "COUNTER_NOTICED"
    assert disputed_item["availability_status"] == "DISABLED"


def test_expired_strike_leaves_the_strike_points_input_set(api):
    """PRD §3.8: "Only strike records whose `status` is `ACTIVE` or `DECAYED` are
    included; those in `EXPIRED` or `VOIDED` are excluded entirely."

    Design: Corner/calculations/expired_strike_leaves_the_strike_points_input_set
    """
    scene = setup_disabled_claim()
    account_id = scene["account"]["id"]

    accrued, accrued_meta = list_account_strikes(account_id)
    assert accrued_meta["total_count"] == 1
    assert accrued[0]["status"] == "ACTIVE"

    # accrued_at 2026-08-01 plus the policy's strike_expiry_days of 365.
    set_clock("2027-08-01T00:00:00Z")

    settled = get_account(account_id)
    assert_two_decimal_places(settled["strike_points"], "strike_points")
    assert float(settled["strike_points"]) == 0.00
    assert settled["standing"] == "ACTIVE"
    assert settled["upload_restricted"] is False

    _, all_meta = list_account_strikes(account_id)
    assert all_meta["total_count"] == 1

    expired, expired_meta = list_account_strikes(
        account_id, params={"status": "EXPIRED"}
    )
    assert expired_meta["total_count"] == 1
    assert float(expired[0]["effective_points"]) == 0.0
    assert float(expired[0]["base_points"]) == 10.0

    _, active_meta = list_account_strikes(account_id, params={"status": "ACTIVE"})
    assert active_meta["total_count"] == 0
    _, decayed_meta = list_account_strikes(account_id, params={"status": "DECAYED"})
    assert decayed_meta["total_count"] == 0


def test_trusted_tier_weight_constant_doubles_the_strike_base_points(api):
    """PRD §3.6: "The record captures the `account_id` of the struck subscriber
    and the `claim_id` of the claim that produced it; `weight` is snapshotted from
    the complaining holder's `program_tier` at the moment of accrual — 1.0 for
    `STANDARD`, 1.5 for `VERIFIED`, 2.0 for `TRUSTED` — and `base_points` is the
    base of 10 points multiplied by that weight."

    Design: Corner/calculations/trusted_tier_weight_constant_doubles_the_strike_base_points
    """
    provider = setup_documented_provider()["provider"]
    account = create_account(provider["id"])
    item = create_content_item(
        account["id"],
        content_url=_CLAIMED_URL,
        fingerprint_hash=TEST_DEFAULTS["CONTENT_FINGERPRINT"],
    )
    holder = create_enrolled_rights_holder("VERIFIED")
    reference = create_active_reference_file(
        holder["id"],
        fingerprint_hash=_REFERENCE_FINGERPRINT_30_OF_32,
        registration_number=_REGISTRATION_NUMBER,
    )
    holder = promote_tier(holder["id"])
    assert holder["program_tier"] == "TRUSTED"

    notice = create_notice(holder["id"], [item["content_url"]])
    validated = validate_success(
        api.validate_notice(notice["id"], AGENT), expected_status=200
    )
    assert validated["compliance_variant"] == "STRICT_COMPLIANCE"
    assert validated["completeness_score"] == 100
    assert validated["status"] == "VALIDATED"

    validate_success(api.process_notice(notice["id"], AGENT), expected_status=200)

    strikes, strikes_meta = list_account_strikes(account["id"])
    assert strikes_meta["total_count"] == 1
    strike = strikes[0]
    assert float(strike["weight"]) == 2.0
    assert float(strike["base_points"]) == 20.0
    assert float(strike["effective_points"]) == 20.0
    assert strike["reason"] == "NOTICE_PROCESSED"
    assert strike["status"] == "ACTIVE"

    struck = get_account(account["id"])
    assert float(struck["strike_points"]) == 20.00
    assert struck["standing"] == "LIMITED"
    assert struck["upload_restricted"] is True

    _, cases_meta = list_account_termination_cases(account["id"])
    assert cases_meta["total_count"] == 0

    claims = claims_of_notice(notice["id"])
    assert len(claims) == 1
    assert claims[0]["reference_file_id"] == reference["id"]
    assert_four_decimal_places(claims[0]["match_confidence"], "match_confidence")
    assert float(claims[0]["match_confidence"]) == 0.95


def test_strike_points_round_per_strike_before_summing(api):
    """PRD §3.8: "The strike's contribution is the base of 10 points multiplied by
    the strike's snapshotted `weight` and then by its decay factor, **rounded half
    up to two decimal places for that strike alone**."

    Design: Corner/calculations/strike_points_round_per_strike_before_summing
    """
    provider = setup_documented_provider()["provider"]
    account = create_account(provider["id"])
    first_item = create_content_item(account["id"])
    second_item = create_content_item(account["id"])
    holder = create_enrolled_rights_holder("VERIFIED")

    notice = create_processed_notice(
        holder["id"], [first_item["content_url"], second_item["content_url"]]
    )
    assert notice["matched_claim_count"] == 2
    assert notice["unmatched_url_count"] == 0

    # 200 days after accrual: floor(200 / 90) = decay step 2, factor 0.325,
    # and strike_expiry_days 365 has not been reached.
    validate_success(
        api.set_clock("2027-02-17T00:00:00Z", OFFICER), expected_status=200
    )

    decayed, decayed_meta = list_account_strikes(
        account["id"], params={"status": "DECAYED"}
    )
    assert decayed_meta["total_count"] == 2
    for strike in decayed:
        assert float(strike["weight"]) == 1.5
        assert float(strike["base_points"]) == 15.0
        assert_two_decimal_places(strike["effective_points"], "effective_points")
        assert float(strike["effective_points"]) == 4.88

    ledger = get_account(account["id"])
    assert float(ledger["strike_points"]) == 9.76
    assert float(ledger["strike_points"]) != 9.75
    assert ledger["standing"] == "ACTIVE"
    assert ledger["upload_restricted"] is False


def test_abuse_score_at_the_auto_open_floor_opens_a_case_with_a_null_opener(api):
    """PRD §3.9: "At **40 or more**, the system opens one misrepresentation case
    against the holder on its own initiative, selecting the holder's most recent
    claim whose `status` is `DISABLED`, `COUNTER_NOTICED`, `RESTORATION_SCHEDULED`
    or `UPHELD`, ranked by `disabled_at` descending and then by `created_at`
    descending, and setting `opened_by_user_id` to null to mark the case as
    system-opened."

    Design: Corner/calculations/abuse_score_at_the_auto_open_floor_opens_a_case_with_a_null_opener
    """
    scene = setup_disabled_claim()
    holder, first_claim = scene["rights_holder"], scene["claim"]
    assert holder["notices_processed"] == 1

    deficient = get_success_data(
        api.create_notice(
            _notice_payload_without(
                holder["id"],
                [scene["item"]["content_url"]],
                "material_identification",
            ),
            AGENT,
        )
    )

    rejected = validate_success(
        api.validate_notice(deficient["id"], AGENT), expected_status=200
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "CORE_ELEMENT_MISSING:material_identification"

    complainant = get_rights_holder(holder["id"])
    assert complainant["rejected_count"] == 1
    assert complainant["notices_processed"] == 1
    assert complainant["withdrawn_count"] == 0
    assert complainant["misrepresentation_count"] == 0
    assert_two_decimal_places(complainant["abuse_score"], "abuse_score")
    assert float(complainant["abuse_score"]) == 40.00
    assert complainant["enrollment_status"] == "ENROLLED"

    cases, cases_meta = _misrepresentation_cases_of(api, holder["id"])
    assert cases_meta["total_count"] == 1
    case = cases[0]
    assert case["status"] == "OPEN"
    assert case["claim_id"] == first_claim["id"]
    assert case["opened_by_user_id"] is None
    assert case["affected_claim_count"] == 0
    assert case["disabled_day_count"] == 0
    assert_money_int(case["total_penalty_cents"], "total_penalty_cents")
    assert case["total_penalty_cents"] == 0


def test_restoration_window_skips_the_weekend_and_the_september_holiday(api):
    """PRD §3.7: "A day is a business day when it falls Monday through Friday and
    its UTC date is not one of the provider's fixed holidays, which are 7 September
    2026, 26 and 27 November 2026, 25 December 2026 and 1 January 2027."

    Design: Corner/calculations/restoration_window_skips_the_weekend_and_the_september_holiday
    """
    scene = setup_disabled_claim()
    account, claim, item = scene["account"], scene["claim"], scene["item"]

    # Inside the claim's 30-day counter-notice window, which runs to 2026-08-31.
    set_clock("2026-08-20T00:00:00Z")
    counter = create_counter_notice(claim["id"], account["id"])
    validate_counter_notice(counter["id"])

    set_clock("2026-09-01T00:00:00Z")
    data = validate_success(
        api.forward_counter_notice(counter["id"], AGENT), expected_status=200
    )

    assert data["status"] == "FORWARDED"
    assert_instant_equals(data["forwarded_at"], "2026-09-01T00:00:00Z", "forwarded_at")
    assert_instant_equals(
        data["restoration_earliest_at"],
        "2026-09-16T00:00:00Z",
        "restoration_earliest_at",
    )
    assert_instant_equals(
        data["restoration_deadline_at"],
        "2026-09-22T00:00:00Z",
        "restoration_deadline_at",
    )

    scheduled_claim = get_claim(claim["id"])
    assert scheduled_claim["status"] == "RESTORATION_SCHEDULED"
    assert_instant_equals(
        scheduled_claim["restoration_due_at"],
        "2026-09-16T00:00:00Z",
        "restoration_due_at",
    )
    assert get_content_item(item["id"])["dispute_status"] == "RESTORATION_PENDING"


def test_strike_decay_factor_engages_at_exactly_decay_step_days(api):
    """PRD §3.8: "`ACTIVE → DECAYED` fires when the gap between the logical clock
    and the strike's `accrued_at` is at least `decay_step_days` and still less than
    `strike_expiry_days`; the transition recomputes that strike's
    `effective_points` with the applicable decay factor and recomputes the
    account's `strike_points`."

    Design: Corner/calculations/strike_decay_factor_engages_at_exactly_decay_step_days
    """
    provider = setup_documented_provider()["provider"]
    account = create_account(provider["id"])
    first_item = create_content_item(account["id"])
    second_item = create_content_item(account["id"])
    holder = create_enrolled_rights_holder()

    create_processed_notice(
        holder["id"], [first_item["content_url"], second_item["content_url"]]
    )

    # 89 days after accrual: floor(89 / 90) is still decay step 0, factor 1.0.
    validate_success(
        api.set_clock("2026-10-29T00:00:00Z", OFFICER), expected_status=200
    )
    still_active, still_active_meta = list_account_strikes(
        account["id"], params={"status": "ACTIVE"}
    )
    assert still_active_meta["total_count"] == 2
    for strike in still_active:
        assert float(strike["effective_points"]) == 10.0
    undecayed = get_account(account["id"])
    assert float(undecayed["strike_points"]) == 20.00
    assert undecayed["standing"] == "LIMITED"
    assert undecayed["upload_restricted"] is True

    # 90 days after accrual: decay step 1, factor 0.65.
    validate_success(
        api.set_clock("2026-10-30T00:00:00Z", OFFICER), expected_status=200
    )
    decayed, decayed_meta = list_account_strikes(
        account["id"], params={"status": "DECAYED"}
    )
    assert decayed_meta["total_count"] == 2
    for strike in decayed:
        assert float(strike["effective_points"]) == 6.50
    _, expired_meta = list_account_strikes(account["id"], params={"status": "EXPIRED"})
    assert expired_meta["total_count"] == 0

    relieved = get_account(account["id"])
    assert float(relieved["strike_points"]) == 13.00
    assert relieved["standing"] == "ACTIVE"
    assert relieved["upload_restricted"] is False


def test_misrepresentation_penalty_at_exactly_the_tier_one_floor(api):
    """PRD §3.9: "The surcharge tier is then selected **from the base amount** and
    never re-selected afterwards: the rate is 0.20 when `base_penalty_cents` is at
    least 500000, otherwise 0.10 when it is at least 100000, and otherwise zero."

    Design: Corner/calculations/misrepresentation_penalty_at_exactly_the_tier_one_floor
    """
    provider = setup_documented_provider()["provider"]
    account = create_account(provider["id"])
    items = [create_content_item(account["id"]) for _ in range(4)]
    holder = create_enrolled_rights_holder()

    notice = create_processed_notice(
        holder["id"], [item["content_url"] for item in items]
    )
    claims = claims_of_notice(notice["id"])
    assert len(claims) == 4

    case = create_misrepresentation_case(
        holder["id"], claims[0]["id"], investigator_user_id="inv-1"
    )
    assert case["status"] == "OPEN"

    data = validate_success(
        api.substantiate_misrepresentation_case(
            case["id"], make_abuse_investigator_headers("inv-2")
        ),
        expected_status=200,
    )

    assert data["status"] == "SUBSTANTIATED"
    assert data["affected_claim_count"] == 4
    assert data["disabled_day_count"] == 0
    assert_money_int(data["base_penalty_cents"], "base_penalty_cents")
    assert_money_int(data["surcharge_cents"], "surcharge_cents")
    assert_money_int(data["total_penalty_cents"], "total_penalty_cents")
    assert data["base_penalty_cents"] == 100000
    assert data["surcharge_cents"] == 10000
    assert data["total_penalty_cents"] == 110000
    assert data["opened_by_user_id"] == "inv-1"
    assert data["substantiated_by_user_id"] == "inv-2"

    complainant = get_rights_holder(holder["id"])
    assert complainant["misrepresentation_count"] == 1
    assert float(complainant["abuse_score"]) == 60.00
    assert complainant["enrollment_status"] == "ENROLLED"
    assert complainant["program_tier"] == "STANDARD"


def test_notice_element_weights_sum_to_one_hundred_with_no_drift(api):
    """PRD §3.5: "Seven elements carry weight, and their weights sum to exactly
    100: the signature contributes 8, work identification 18, material
    identification 20, the contact address 10, the good-faith statement 18, the
    accuracy statement 8, and the authority statement 18."

    Design: Corner/calculations/notice_element_weights_sum_to_one_hundred_and_each_absence_subtracts_its_own_weight
    """
    setup_documented_provider()
    holder = create_enrolled_rights_holder()
    urls = [_CLAIMED_URL]

    complete = create_notice(holder["id"], urls)
    without_contact = get_success_data(
        api.create_notice(
            _notice_payload_without(holder["id"], urls, "contact_email"), AGENT
        )
    )
    without_contact_and_accuracy = get_success_data(
        api.create_notice(
            _notice_payload_without(
                holder["id"], urls, "contact_email", "accuracy_statement"
            ),
            AGENT,
        )
    )
    unsworn = get_success_data(
        api.create_notice(
            _notice_payload_without(holder["id"], urls, "sworn_under_penalty"), AGENT
        )
    )

    scored_a = validate_success(
        api.validate_notice(complete["id"], AGENT), expected_status=200
    )
    scored_b = validate_success(
        api.validate_notice(without_contact["id"], AGENT), expected_status=200
    )
    scored_c = validate_success(
        api.validate_notice(without_contact_and_accuracy["id"], AGENT),
        expected_status=200,
    )
    scored_d = validate_success(
        api.validate_notice(unsworn["id"], AGENT), expected_status=200
    )

    assert scored_a["completeness_score"] == 100
    assert scored_a["status"] == "VALIDATED"
    assert scored_a["rejection_reason"] is None

    assert scored_b["completeness_score"] == 100 - NOTICE_WEIGHT_CONTACT_EMAIL == 90
    assert scored_b["status"] == "REJECTED"
    assert scored_b["rejection_reason"] == "SCORE_BELOW_THRESHOLD"

    assert scored_c["completeness_score"] == 90 - NOTICE_WEIGHT_ACCURACY_STATEMENT == 82
    assert scored_c["status"] == "REJECTED"
    assert scored_c["rejection_reason"] == "SCORE_BELOW_THRESHOLD"

    # sworn_under_penalty carries no weight of its own; the substantial variant
    # ignores it entirely.
    assert scored_d["completeness_score"] == 100
    assert scored_d["status"] == "VALIDATED"
    assert scored_d["rejection_reason"] is None

    for scored in (scored_a, scored_b, scored_c, scored_d):
        assert isinstance(scored["completeness_score"], int)
        assert scored["compliance_variant"] == "SUBSTANTIAL_COMPLIANCE"
    for scored in (scored_b, scored_c):
        assert not scored["rejection_reason"].startswith("CORE_ELEMENT_MISSING")

    complainant = get_rights_holder(holder["id"])
    assert complainant["rejected_count"] == 2
    assert complainant["notices_processed"] == 0
    assert float(complainant["abuse_score"]) == 80.00

    # No claim exists to attach a system-opened case to.
    _, cases_meta = _misrepresentation_cases_of(api, holder["id"])
    assert cases_meta["total_count"] == 0


def test_tier_promotion_switches_the_variant_forward_without_rewriting_the_earlier_verdict(api):
    """PRD §3.3: "It sets the weight that future strike records from this holder
    will carry — 1.0 at `STANDARD`, 1.5 at `VERIFIED`, 2.0 at `TRUSTED` — and
    reaching `TRUSTED` additionally means every future notice from this holder is
    scored under the stricter of the two statutory compliance variants described in
    Section 3.5."

    Design: Corner/calculations/tier_promotion_switches_the_variant_forward_without_rewriting_the_earlier_verdict
    """
    provider = setup_documented_provider()["provider"]
    account = create_account(provider["id"])
    item = create_content_item(
        account["id"],
        content_url=_CLAIMED_URL,
        fingerprint_hash=TEST_DEFAULTS["CONTENT_FINGERPRINT"],
    )
    holder = create_enrolled_rights_holder()

    earlier = get_success_data(
        api.create_notice(
            _notice_payload_without(
                holder["id"], [item["content_url"]], "accuracy_statement"
            ),
            AGENT,
        )
    )
    earlier_verdict = validate_success(
        api.validate_notice(earlier["id"], AGENT), expected_status=200
    )
    assert earlier_verdict["completeness_score"] == 92
    assert earlier_verdict["compliance_variant"] == "SUBSTANTIAL_COMPLIANCE"
    assert earlier_verdict["status"] == "VALIDATED"

    promote_tier(holder["id"])
    create_active_reference_file(
        holder["id"],
        fingerprint_hash=_REFERENCE_FINGERPRINT_30_OF_32,
        registration_number=_REGISTRATION_NUMBER,
    )
    assert promote_tier(holder["id"])["program_tier"] == "TRUSTED"

    unchanged = get_notice(earlier["id"])
    assert unchanged["completeness_score"] == 92
    assert unchanged["compliance_variant"] == "SUBSTANTIAL_COMPLIANCE"
    assert unchanged["status"] == "VALIDATED"
    assert unchanged["rejection_reason"] is None

    processed = validate_success(
        api.process_notice(earlier["id"], AGENT), expected_status=200
    )
    assert processed["matched_claim_count"] == 1
    assert processed["unmatched_url_count"] == 0

    strikes, strikes_meta = list_account_strikes(account["id"])
    assert strikes_meta["total_count"] == 1
    assert float(strikes[0]["weight"]) == 2.0
    assert float(strikes[0]["base_points"]) == 20.0
    assert float(strikes[0]["effective_points"]) == 20.0

    struck = get_account(account["id"])
    assert float(struck["strike_points"]) == 20.00
    assert struck["standing"] == "LIMITED"

    claims = claims_of_notice(earlier["id"])
    assert len(claims) == 1
    assert float(claims[0]["match_confidence"]) == 0.95

    later = get_success_data(
        api.create_notice(
            _notice_payload_without(
                holder["id"], [item["content_url"]], "accuracy_statement"
            ),
            AGENT,
        )
    )
    later_verdict = validate_success(
        api.validate_notice(later["id"], AGENT), expected_status=200
    )
    assert later_verdict["compliance_variant"] == "STRICT_COMPLIANCE"
    assert later_verdict["completeness_score"] == 92
    assert later_verdict["status"] == "REJECTED"
    assert later_verdict["rejection_reason"] == "SCORE_BELOW_THRESHOLD"

    complainant = get_rights_holder(holder["id"])
    assert complainant["notices_processed"] == 1
    assert complainant["rejected_count"] == 1
    assert float(complainant["abuse_score"]) == 40.00

    cases, cases_meta = _misrepresentation_cases_of(api, holder["id"])
    assert cases_meta["total_count"] == 1
    assert cases[0]["claim_id"] == claims[0]["id"]
    assert cases[0]["opened_by_user_id"] is None
