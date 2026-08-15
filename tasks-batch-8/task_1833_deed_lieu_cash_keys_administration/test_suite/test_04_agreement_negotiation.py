"""Settlement agreement negotiation: the provisional assistance quote, the
counter/re-offer cycle, offer expiry, OCC on case version, supersession, and
termination (PRD §2.7, §2.10, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_settlement_agreement,
    create_agreement_payload,
    create_draft_agreement,
    create_lien_payload,
    get_case,
    make_borrower_headers,
    set_clock,
    setup_accepted_agreement,
    setup_case_at_agreement_active,
    setup_case_at_terms_negotiation,
    validate_error,
    validate_paginated,
    validate_success,
)


def _draft_in_terms(api, loan_number, specialist_headers, **kwargs):
    """Drive a case to TERMS_NEGOTIATION and draft an agreement (vacate 2026-09-01)."""
    bundle = setup_case_at_terms_negotiation(loan_number=loan_number, **kwargs)
    agreement = create_draft_agreement(bundle["case"]["id"])
    return bundle, agreement


def test_tier_boundary_upb_9999999_vs_10000000(api, specialist_headers):
    """The tier boundary is inclusive of its lower bound: 9,999,999 cents lands in
    tier 1 (300,000) and 10,000,000 cents lands in tier 2 (500,000).

    PRD §3.5: "The tier base is selected by the loan's unpaid principal balance: under 10,000,000 cents ($100,000) the base is 300,000 cents; from 10,000,000 cents up to but not including 25,000,000 cents ($250,000) the base is 500,000 cents — each tier boundary is inclusive of its lower bound; from 25,000,000 cents up to but not including 50,000,000 cents ($500,000) the base is 750,000 cents; and at 50,000,000 cents or more the base is 1,150,000 cents."

    Design: Corner/calculations/tier_boundary_upb_exactly_100k
    """
    bundle_a, agreement_a = _draft_in_terms(
        api, "LN-C1a", specialist_headers,
        loan_overrides={"unpaid_principal_balance_cents": 9999999, "accrued_interest_cents": 0,
                        "escrow_advances_cents": 0, "foreclosure_fees_cents": 0, "note_annual_rate": 0.05,
                        "fair_market_value_cents": 9000000, "delinquency_days": 60},
        borrower_overrides={"full_name": "C. Alpha", "email": "ca@x.com", "hardship_type": "NONE",
                            "self_reported_condition_grade": "A"},
    )
    bundle_b, agreement_b = _draft_in_terms(
        api, "LN-C1b", specialist_headers,
        loan_overrides={"unpaid_principal_balance_cents": 10000000, "accrued_interest_cents": 0,
                        "escrow_advances_cents": 0, "foreclosure_fees_cents": 0, "note_annual_rate": 0.05,
                        "fair_market_value_cents": 9000000, "delinquency_days": 60},
        borrower_overrides={"full_name": "C. Beta", "email": "cb@x.com", "hardship_type": "NONE",
                            "self_reported_condition_grade": "A"},
    )
    assert agreement_a["provisional_assistance_cents"] == 300000, (
        f"UPB 9999999 must be tier 1 base 300000, got {agreement_a['provisional_assistance_cents']}"
    )
    assert agreement_b["provisional_assistance_cents"] == 500000, (
        f"UPB 10000000 must be tier 2 base 500000 (lower bound inclusive), got {agreement_b['provisional_assistance_cents']}"
    )


def test_assistance_floor_exact_at_second_home(api, specialist_headers):
    """SECOND_HOME halves tier 1 to exactly the 150,000 floor; the floor is
    inclusive and does not lift the result above itself.

    PRD §3.5: "The tier base is then multiplied by an occupancy multiplier drawn from the property's `occupancy_type` — 1.0 for `OWNER_OCCUPIED`, 0.8 for `TENANT_OCCUPIED`, 0.5 for `SECOND_HOME` — and that product is rounded half-up to whole cents, the only rounding step in the quote."
    PRD §3.5: "The result is then raised to a floor of 150,000 cents when it falls short, and only after that floor is applied is it capped at 1,200,000 cents — the floor is always applied before the cap."

    Design: Corner/calculations/assistance_floor_exact_at_second_home
    """
    bundle, agreement = _draft_in_terms(
        api, "LN-C2", specialist_headers,
        loan_overrides={"unpaid_principal_balance_cents": 5000000, "accrued_interest_cents": 0,
                        "escrow_advances_cents": 0, "foreclosure_fees_cents": 0, "note_annual_rate": 0.05,
                        "fair_market_value_cents": 4000000, "delinquency_days": 60},
        borrower_overrides={"full_name": "C. Two", "email": "c2@x.com", "hardship_type": "NONE",
                            "self_reported_condition_grade": "A"},
        property_overrides={"address_line": "12 Main St", "occupancy_type": "SECOND_HOME"},
    )
    assert agreement["provisional_assistance_cents"] == 150000, (
        f"max(round(300000*0.5)+0, 150000) must be exactly 150000, got {agreement['provisional_assistance_cents']}"
    )


def test_tier3_tenant_divorce_combination(api, specialist_headers):
    """Mid-band combination: tier 3 base 750,000 x 0.8 TENANT_OCCUPIED + 25,000
    DIVORCE bonus = 625,000 with no floor or cap engagement.

    PRD §3.5: "The provisional assistance quote is assembled in a pinned evaluation order: tier selection, then the occupancy multiplier, then rounding, then the hardship bonus, then the floor, then the cap."
    PRD §3.5: "A hardship bonus is added next, drawn from the borrower's `hardship_type`: 100,000 cents for `INVOLUNTARY_UNEMPLOYMENT`, 50,000 for `MEDICAL`, 25,000 for `DIVORCE`, and nothing for `NONE`."

    Design: Corner/calculations/tier3_tenant_divorce_combination
    """
    bundle, agreement = _draft_in_terms(
        api, "LN-C4", specialist_headers,
        loan_overrides={"unpaid_principal_balance_cents": 30000000, "accrued_interest_cents": 0,
                        "escrow_advances_cents": 0, "foreclosure_fees_cents": 0, "note_annual_rate": 0.05,
                        "fair_market_value_cents": 28000000, "delinquency_days": 60},
        borrower_overrides={"full_name": "C. Four", "email": "c4@x.com", "hardship_type": "DIVORCE",
                            "self_reported_condition_grade": "B"},
        property_overrides={"address_line": "13 Main St", "occupancy_type": "TENANT_OCCUPIED"},
    )
    assert agreement["provisional_assistance_cents"] == 625000, (
        f"round(750000*0.8) + 25000 must be 625000, got {agreement['provisional_assistance_cents']}"
    )


def test_cap_binds_after_floor_value(api, specialist_headers):
    """Tier 4 base 1,150,000 + 100,000 bonus = 1,250,000 exceeds the cap; the
    pinned floor-then-cap order yields exactly 1,200,000.

    PRD §3.5: "The result is then raised to a floor of 150,000 cents when it falls short, and only after that floor is applied is it capped at 1,200,000 cents — the floor is always applied before the cap."
    PRD §3.5: "The provisional assistance quote is assembled in a pinned evaluation order: tier selection, then the occupancy multiplier, then rounding, then the hardship bonus, then the floor, then the cap."

    Design: Difficulty/combinatorial_formula/assistance_cap_binds_after_tier_multiply_floor
    """
    bundle, agreement = _draft_in_terms(
        api, "LN-CF1", specialist_headers,
        loan_overrides={"unpaid_principal_balance_cents": 60000000, "accrued_interest_cents": 0,
                        "escrow_advances_cents": 0, "foreclosure_fees_cents": 0, "note_annual_rate": 0.05,
                        "fair_market_value_cents": 70000000, "delinquency_days": 120},
        borrower_overrides={"full_name": "C. Cap", "email": "c@x.com",
                            "hardship_type": "INVOLUNTARY_UNEMPLOYMENT", "self_reported_condition_grade": "A"},
        property_overrides={"address_line": "9 Cap Way"},
    )
    assert agreement["provisional_assistance_cents"] == 1200000, (
        f"min(max(1150000 + 100000, 150000), 1200000) must cap at 1200000, got {agreement['provisional_assistance_cents']}"
    )


def test_cap_binds_after_floor_agreement_readback(api, specialist_headers):
    """The capped quote persists on read: the draft is DRAFT on the SELF_REPORTED
    basis with no final amount yet.

    PRD §3.5: "Creation computes `provisional_assistance_cents` on the `SELF_REPORTED` condition basis, stamps `created_by_specialist_id` from the specialist's `X-User-ID`, starts `round_number` at 0, leaves `final_assistance_cents` null, and increments the case's `version`."
    PRD §3.5: "The result is then raised to a floor of 150,000 cents when it falls short, and only after that floor is applied is it capped at 1,200,000 cents — the floor is always applied before the cap."

    Design: Difficulty/combinatorial_formula/assistance_cap_binds_after_tier_multiply_floor
    """
    bundle, agreement = _draft_in_terms(
        api, "LN-CF1", specialist_headers,
        loan_overrides={"unpaid_principal_balance_cents": 60000000, "accrued_interest_cents": 0,
                        "escrow_advances_cents": 0, "foreclosure_fees_cents": 0, "note_annual_rate": 0.05,
                        "fair_market_value_cents": 70000000, "delinquency_days": 120},
        borrower_overrides={"full_name": "C. Cap", "email": "c@x.com",
                            "hardship_type": "INVOLUNTARY_UNEMPLOYMENT", "self_reported_condition_grade": "A"},
        property_overrides={"address_line": "9 Cap Way"},
    )
    reread = validate_success(api.get_agreement(agreement["id"], specialist_headers))
    assert_settlement_agreement(reread)
    assert reread["status"] == "DRAFT"
    assert reread["condition_basis"] == "SELF_REPORTED"
    assert reread["provisional_assistance_cents"] == 1200000
    assert reread["final_assistance_cents"] is None
    assert reread["round_number"] == 0
    assert reread["created_by_specialist_id"] == "spec_1"


def test_counter_reoffer_cycle_rounds(api, specialist_headers):
    """The OFFERED -> COUNTERED -> OFFERED loop increments round_number per
    re-offer and replaces vacate_date on each counter and re-offer.

    PRD §3.5: "The counter's `proposed_vacate_date` replaces the agreement's `vacate_date` and must itself satisfy the ten-day notice (`ERR_VACATE_DATE_TOO_SOON`); the provisional amount is left unchanged, and the agreement moves to `COUNTERED`."
    PRD §3.5: "The re-offer replaces `vacate_date` with the new input (the ten-day notice applies again), increments `round_number` by one, recomputes `provisional_assistance_cents` from scratch, resets `offer_expires_at` to now plus the new `offer_valid_days`, and returns the agreement to `OFFERED`."

    Design: Difficulty/non_linear_state_machine/agreement_counter_reoffer_cycle
    """
    bundle, agreement = _draft_in_terms(api, "LN-NL1", specialist_headers)
    borrower = make_borrower_headers(bundle["borrower"]["id"])
    validate_success(api.offer_agreement(agreement["id"], {"offer_valid_days": 10}, specialist_headers))

    counter1 = validate_success(api.counter_agreement(agreement["id"], {"proposed_vacate_date": "2026-09-10"}, borrower))
    assert counter1["status"] == "COUNTERED" and counter1["round_number"] == 0
    reoffer1 = validate_success(
        api.reoffer_agreement(agreement["id"], {"vacate_date": "2026-09-10", "offer_valid_days": 10}, specialist_headers)
    )
    assert reoffer1["status"] == "OFFERED" and reoffer1["round_number"] == 1
    assert reoffer1["vacate_date"] == "2026-09-10"

    validate_success(api.counter_agreement(agreement["id"], {"proposed_vacate_date": "2026-09-15"}, borrower))
    reoffer2 = validate_success(
        api.reoffer_agreement(agreement["id"], {"vacate_date": "2026-09-15", "offer_valid_days": 10}, specialist_headers)
    )
    assert reoffer2["status"] == "OFFERED" and reoffer2["round_number"] == 2
    assert reoffer2["vacate_date"] == "2026-09-15", "second re-offer replaces the vacate date again"


def test_counter_reoffer_cycle_acceptance(api, specialist_headers):
    """After two full negotiation cycles the borrower can still accept, bubbling
    the case to AGREEMENT_ACTIVE.

    PRD §3.5: "Acceptance moves the agreement from `OFFERED` to `ACCEPTED`."
    PRD §3.5: "Acceptance bubbles up: the case moves from `TERMS_NEGOTIATION` to `AGREEMENT_ACTIVE` with a version increment, and for deed-in-lieu cases the system creates a DeficiencyWaiver in `DRAFT` status — its `case_id` set from the case, its `loan_id` copied from the case, and its `projected_waiver_cents` computed per the projected variant described in §3.8."

    Design: Difficulty/non_linear_state_machine/agreement_counter_reoffer_cycle
    """
    bundle, agreement = _draft_in_terms(api, "LN-NL1", specialist_headers)
    borrower = make_borrower_headers(bundle["borrower"]["id"])
    validate_success(api.offer_agreement(agreement["id"], {"offer_valid_days": 10}, specialist_headers))
    validate_success(api.counter_agreement(agreement["id"], {"proposed_vacate_date": "2026-09-10"}, borrower))
    validate_success(api.reoffer_agreement(agreement["id"], {"vacate_date": "2026-09-10", "offer_valid_days": 10}, specialist_headers))
    validate_success(api.counter_agreement(agreement["id"], {"proposed_vacate_date": "2026-09-15"}, borrower))
    validate_success(api.reoffer_agreement(agreement["id"], {"vacate_date": "2026-09-15", "offer_valid_days": 10}, specialist_headers))

    accepted = validate_success(api.accept_agreement(agreement["id"], borrower))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["vacate_date"] == "2026-09-15"
    assert get_case(bundle["case"]["id"])["status"] == "AGREEMENT_ACTIVE"


def test_counter_replaces_vacate_date(api, specialist_headers):
    """A counter moves OFFERED -> COUNTERED, replaces vacate_date, and leaves the
    provisional amount untouched.

    PRD §3.5: "The counter's `proposed_vacate_date` replaces the agreement's `vacate_date` and must itself satisfy the ten-day notice (`ERR_VACATE_DATE_TOO_SOON`); the provisional amount is left unchanged, and the agreement moves to `COUNTERED`."

    Design: Corner/endpoints/counter_replaces_vacate_date
    """
    bundle, agreement = _draft_in_terms(api, "LN-P1", specialist_headers)
    offered = validate_success(api.offer_agreement(agreement["id"], {"offer_valid_days": 30}, specialist_headers))
    assert offered["provisional_assistance_cents"] == 550000

    countered = validate_success(
        api.counter_agreement(
            agreement["id"], {"proposed_vacate_date": "2026-09-10"},
            make_borrower_headers(bundle["borrower"]["id"]),
        )
    )
    assert countered["status"] == "COUNTERED"
    assert countered["vacate_date"] == "2026-09-10"
    assert countered["provisional_assistance_cents"] == 550000, "counter must not touch the provisional amount"


def test_negotiation_round_limit_rejected(api, specialist_headers):
    """After three re-offers (round_number == 3) a fourth is refused; the cycle is
    bounded.

    PRD §3.5: "A specialist answers a counter by re-offering: the agreement must be `COUNTERED`, and the negotiation-round cap applies — re-offering when `round_number` has already reached 3 is rejected with `ERR_NEGOTIATION_ROUND_LIMIT`."

    Design: Corner/validations/negotiation_round_limit_rejected
    """
    bundle, agreement = _draft_in_terms(api, "LN-V11", specialist_headers)
    borrower = make_borrower_headers(bundle["borrower"]["id"])
    validate_success(api.offer_agreement(agreement["id"], {"offer_valid_days": 30}, specialist_headers))

    for date in ("2026-09-10", "2026-09-15", "2026-09-20"):
        validate_success(api.counter_agreement(agreement["id"], {"proposed_vacate_date": date}, borrower))
        reoffer = validate_success(
            api.reoffer_agreement(agreement["id"], {"vacate_date": date, "offer_valid_days": 30}, specialist_headers)
        )
    assert reoffer["round_number"] == 3, f"three re-offers must reach round 3, got {reoffer['round_number']}"

    validate_success(api.counter_agreement(agreement["id"], {"proposed_vacate_date": "2026-09-25"}, borrower))
    resp = api.reoffer_agreement(agreement["id"], {"vacate_date": "2026-09-25", "offer_valid_days": 30}, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT.value)
    assert validate_success(api.get_agreement(agreement["id"], specialist_headers))["status"] == "COUNTERED"


def test_draft_agreement_superseded_by_new_draft(api, specialist_headers):
    """A second draft while the first is still DRAFT supersedes it; the new draft
    is the live one.

    PRD §3.5: "Only one active agreement may exist per case: creating a draft while another agreement of the same case is `OFFERED`, `COUNTERED`, or `ACCEPTED` is rejected with `ERR_ACTIVE_AGREEMENT_EXISTS`; an existing `DRAFT`, by contrast, is simply superseded — flipped to `SUPERSEDED` — when the new draft is created."

    Design: Corner/state_machines_workflow_completion/draft_agreement_superseded_by_new_draft
    """
    bundle, agreement_a = _draft_in_terms(api, "LN-W1", specialist_headers)
    case = get_case(bundle["case"]["id"])
    agreement_b = validate_success(
        api.create_agreement(
            bundle["case"]["id"],
            create_agreement_payload(case["version"], vacate_date="2026-09-10"),
            specialist_headers,
        ),
        201,
    )
    assert agreement_b["status"] == "DRAFT" and agreement_b["vacate_date"] == "2026-09-10"
    superseded = validate_success(api.get_agreement(agreement_a["id"], specialist_headers))
    assert superseded["status"] == "SUPERSEDED", f"prior DRAFT must flip to SUPERSEDED, got {superseded['status']}"


def test_active_agreement_exists_rejected(api, specialist_headers):
    """Creating a draft while one is OFFERED is rejected even with the fresh OCC
    version; only a DRAFT may be superseded.

    PRD §3.5: "Only one active agreement may exist per case: creating a draft while another agreement of the same case is `OFFERED`, `COUNTERED`, or `ACCEPTED` is rejected with `ERR_ACTIVE_AGREEMENT_EXISTS`; an existing `DRAFT`, by contrast, is simply superseded — flipped to `SUPERSEDED` — when the new draft is created."

    Design: Corner/validations/active_agreement_exists_rejected
    """
    bundle, agreement = _draft_in_terms(api, "LN-V10", specialist_headers)
    validate_success(api.offer_agreement(agreement["id"], {"offer_valid_days": 10}, specialist_headers))

    case = get_case(bundle["case"]["id"])  # fresh version after the offer
    resp = api.create_agreement(
        bundle["case"]["id"],
        create_agreement_payload(case["version"], vacate_date="2026-09-05"),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_AGREEMENT_EXISTS.value)
    untouched = validate_success(api.get_agreement(agreement["id"], specialist_headers))
    assert untouched["status"] == "OFFERED" and untouched["vacate_date"] == "2026-09-01"


def test_vacate_date_too_soon_rejected(api, specialist_headers):
    """The ten-day vacate notice binds at draft creation; the rejected write
    leaves the case untouched.

    PRD §3.5: "The vacate date must fall at least ten days after the current logical date, failing which the draft is rejected with `ERR_VACATE_DATE_TOO_SOON`."

    Design: Corner/validations/vacate_date_too_soon_rejected
    """
    bundle = setup_case_at_terms_negotiation(loan_number="LN-V13")  # clock at 2026-08-01
    case_before = get_case(bundle["case"]["id"])
    resp = api.create_agreement(
        bundle["case"]["id"],
        create_agreement_payload(case_before["version"], vacate_date="2026-08-05"),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VACATE_DATE_TOO_SOON.value)
    case_after = get_case(bundle["case"]["id"])
    assert case_after["version"] == case_before["version"], "a rejected draft must not advance the case version"
    assert case_after["status"] == "TERMS_NEGOTIATION"
    agreements = validate_paginated(api.list_case_agreements(bundle["case"]["id"], specialist_headers))[0]
    assert agreements == []


def test_occ_stale_case_version_on_agreement_create(api, specialist_headers):
    """The first create advances the case version; a second create carrying the
    pre-create version is a stale write and does not supersede the live DRAFT.

    PRD §2.7: "Creating a settlement agreement through `POST /property-solutions/cases/{id}/agreements` requires a non-optional `expected_case_version` input carrying the client's last observed `version` of the parent workout case; if that value does not match the case's current `version` — because another writer has advanced the case since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_case_version_on_agreement_create
    """
    bundle = setup_case_at_terms_negotiation(loan_number="LN-L1")
    case_id = bundle["case"]["id"]
    stale_version = get_case(case_id)["version"]

    first = validate_success(
        api.create_agreement(case_id, create_agreement_payload(stale_version, vacate_date="2026-09-01"),
                             specialist_headers),
        201,
    )
    assert first["status"] == "DRAFT"

    resp = api.create_agreement(
        case_id, create_agreement_payload(stale_version, vacate_date="2026-09-05"), specialist_headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    still_draft = validate_success(api.get_agreement(first["id"], specialist_headers))
    assert still_draft["status"] == "DRAFT", "the stale write must not supersede the live DRAFT"


def test_case_computed_read_after_accept(api, specialist_headers):
    """After acceptance the case reads remaining == provisional (550,000) and
    total_disbursed == 0.

    PRD §3.5: "Once an agreement exists, the case's `remaining_assistance_cents` is the agreement's applicable assistance — `final_assistance_cents` when it has been set on the `ACCEPTED` or `COMPLETED` agreement, otherwise `provisional_assistance_cents` — minus the case's `total_disbursed_cents`; until an agreement exists, `remaining_assistance_cents` is null."
    PRD §3.7: "A release adds the disbursement's `amount_cents` to the case's `total_disbursed_cents` — the running sum of `amount_cents` over the case's `RELEASED` disbursements — and recomputes `remaining_assistance_cents`."

    Design: Corner/endpoints/case_get_computed_read_after_accept
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-P2")
    case = get_case(bundle["case"]["id"])
    assert case["status"] == "AGREEMENT_ACTIVE"
    assert case["remaining_assistance_cents"] == 550000, (
        f"provisional basis minus zero disbursed must read 550000, got {case['remaining_assistance_cents']}"
    )
    assert case["total_disbursed_cents"] == 0


def test_double_accept_rejected(api, specialist_headers):
    """A second accept on an ACCEPTED agreement is a state error; exactly one
    waiver exists and the case stays AGREEMENT_ACTIVE.

    PRD §3.5: "Acceptance moves the agreement from `OFFERED` to `ACCEPTED`."
    PRD §2.10: "Fifth, state: the target resource must be in a state from which the requested transition exists, and terminal states reject all actions; failures surface as the per-entity 409 errors — `ERR_CASE_INVALID_STATE`, `ERR_LOAN_INVALID_STATE`, `ERR_LISTING_INVALID_STATE`, `ERR_TITLE_INVALID_STATE`, `ERR_LIEN_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_APPOINTMENT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_DISBURSEMENT_INVALID_STATE`, `ERR_RECORDING_INVALID_STATE`, `ERR_EVICTION_INVALID_STATE`, and `ERR_WAIVER_INVALID_STATE`."

    Design: Corner/state_machines/double_accept_rejected
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-S4")
    borrower = make_borrower_headers(bundle["borrower"]["id"])

    resp = api.accept_agreement(bundle["agreement"]["id"], borrower)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE.value)

    assert get_case(bundle["case"]["id"])["status"] == "AGREEMENT_ACTIVE"
    waivers = validate_paginated(api.list_case_deficiency_waivers(bundle["case"]["id"], specialist_headers))[0]
    assert len(waivers) == 1, "acceptance must not create a second waiver"


def _setup_expired_offer_with_lien(api, specialist_headers, title_officer_headers):
    """Offer an agreement with 1-day validity, reopen the commitment with a
    newly discovered lien, then advance the clock past expiry."""
    bundle = setup_case_at_terms_negotiation(loan_number="LN-PP2")
    agreement = create_draft_agreement(bundle["case"]["id"])
    validate_success(api.offer_agreement(agreement["id"], {"offer_valid_days": 1}, specialist_headers))
    validate_success(
        api.add_lien(
            bundle["title_commitment"]["id"],
            create_lien_payload(lienholder_name="HOA Corp", amount_cents=50000, position=2),
            title_officer_headers,
        ),
        201,
    )
    set_clock("2026-08-03T00:00:00Z")  # offer_expires_at (2026-08-02) has passed
    return bundle, agreement


def test_expired_offer_accept_reports_offer_expired(api, specialist_headers, title_officer_headers):
    """On accept, the temporal expiry guard outranks the referential lien gate:
    the error is ERR_OFFER_EXPIRED, not ERR_JUNIOR_LIENS_OUTSTANDING.

    PRD §2.10: "On agreement acceptance, offer expiry is checked before junior-lien clearance — the temporal guard outranks the referential one."
    PRD §3.5: "Its guards run in a pinned order: the agreement must be `OFFERED` (`ERR_AGREEMENT_INVALID_STATE`), ownership must hold (`ERR_FORBIDDEN`), and the offer must not have lapsed (`ERR_OFFER_EXPIRED`) — this temporal check is evaluated before any lien-clearance check."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_accept
    """
    bundle, agreement = _setup_expired_offer_with_lien(api, specialist_headers, title_officer_headers)
    resp = api.accept_agreement(agreement["id"], make_borrower_headers(bundle["borrower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)


def test_expired_offer_flips_agreement_expired(api, specialist_headers, title_officer_headers):
    """The failed accept flips the agreement to EXPIRED; the case stays in
    TERMS_NEGOTIATION.

    PRD §3.5: "An `OFFERED` agreement flips to `EXPIRED` when it is read or acted upon after `offer_expires_at` has passed: on an accept or counter the expiry guard reports `ERR_OFFER_EXPIRED` and the agreement then flips to `EXPIRED`, while plain reads flip it silently."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_accept
    """
    bundle, agreement = _setup_expired_offer_with_lien(api, specialist_headers, title_officer_headers)
    resp = api.accept_agreement(agreement["id"], make_borrower_headers(bundle["borrower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)

    expired = validate_success(api.get_agreement(agreement["id"], specialist_headers))
    assert expired["status"] == "EXPIRED", f"failed accept must flip the offer EXPIRED, got {expired['status']}"
    assert get_case(bundle["case"]["id"])["status"] == "TERMS_NEGOTIATION"


def test_terminate_accepted_reverts_case(api, specialist_headers, workout_manager_headers):
    """Manager termination of an ACCEPTED agreement reverts the case to
    TERMS_NEGOTIATION for renegotiation.

    PRD §3.5: "A `WorkoutManager` may terminate an `ACCEPTED` agreement — termination from any other state is refused with `ERR_AGREEMENT_INVALID_STATE` — moving it to `TERMINATED`; when the case is in `AGREEMENT_ACTIVE` at that moment, the case reverts from `AGREEMENT_ACTIVE` to `TERMS_NEGOTIATION` so that terms can be renegotiated."

    Design: Corner/state_machines_workflow_completion/terminate_accepted_reverts_case_to_negotiation
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-W4")
    assert bundle["case"]["status"] == "AGREEMENT_ACTIVE"

    terminated = validate_success(api.terminate_agreement(bundle["agreement"]["id"], workout_manager_headers))
    assert terminated["status"] == "TERMINATED"
    assert get_case(bundle["case"]["id"])["status"] == "TERMS_NEGOTIATION"
