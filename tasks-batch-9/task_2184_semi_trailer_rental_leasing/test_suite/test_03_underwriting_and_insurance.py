"""Opening a contract: draft shape, underwriting scores and the certificate of
insurance that has to span the whole window."""


from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_customer,
    agreement_payload,
    file_certificate,
    find_chargeback,
    open_agreement,
    read_agreement,
    read_customer,
    read_damage_assessment,
    setup_approved_chargeback,
    setup_reference_data,
    submit_for_underwriting,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def test_new_contract_lands_in_draft_with_nothing_pinned(api):
    """PRD §3.4: "A newly opened contract begins in status `DRAFT`, with
    `purchase_option_status` at `NOT_OFFERED` and `allocated_unit_count` at zero."
    PRD §3.5: "The contract advances `PENDING_ALLOCATION → RESERVED`, pins
    `rate_card_id`, writes `quoted_total_cents`, and increments its `version` by 1."

    Design: Corner/state_machines/agreement_created_in_draft_with_no_pinned_rate_card
    """
    ctx = setup_reference_data()

    agreement = validate_success(
        api.create_agreement(
            agreement_payload(ctx["customer_id"], ctx["branch_id"],
                              ctx["trailer_type_id"]),
            ADMIN,
        ),
        201,
    )
    assert agreement["status"] == "DRAFT"
    assert agreement["purchase_option_status"] == "NOT_OFFERED"
    assert agreement["allocated_unit_count"] == 0
    assert agreement["version"] == 1

    stored = read_agreement(agreement["id"])
    assert stored.get("rate_card_id") is None
    assert stored.get("insurance_certificate_id") is None
    assert stored.get("quoted_total_cents") is None
    assert stored.get("final_total_cents") is None


def test_submitting_a_contract_twice_is_rejected(api):
    """PRD §3.4: "Three conditions gate it, and a contract in any status other than
    `DRAFT` is rejected with `ERR_AGREEMENT_NOT_DRAFT`."
    PRD §3.4: "A successful submission freezes that score into
    `underwriting_risk_score` on the contract — the number is a snapshot and is
    never re-evaluated afterwards — and increments the contract's `version` by 1."

    Design: Corner/state_machines/agreement_submit_twice_rejects_second_call
    """
    ctx = setup_reference_data()
    agreement = open_agreement(ctx)
    first = submit_for_underwriting(ctx, agreement["id"])
    assert first["version"] == 2

    response = api.submit_agreement(agreement["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_DRAFT.value)

    stored = read_agreement(agreement["id"])
    assert stored["status"] == "PENDING_INSURANCE"
    assert stored["version"] == 2, "a rejected call advances no version"


def test_contract_end_date_equal_to_start_date_is_an_invalid_range(api):
    """PRD §3.4: "The window is half-open: `start_date` is inclusive, `end_date` is
    exclusive, and the end date must be strictly after the start date — an end date
    equal to or before the start date is rejected with `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/agreement_end_date_not_after_start_date_returns_invalid_date_range
    """
    ctx = setup_reference_data()

    response = api.create_agreement(
        agreement_payload(ctx["customer_id"], ctx["branch_id"], ctx["trailer_type_id"],
                          start_date="2026-08-20", end_date="2026-08-20"),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    from test_helpers import validate_paginated
    _, meta = validate_paginated(api.list_agreements(ADMIN, params={"limit": 100}))
    assert meta["total_count"] == 0


def test_certificate_limit_below_the_class_requirement_is_insufficient(api):
    """PRD §3.4: "If one does exist but its `physical_damage_limit_cents` is below
    the `required_physical_damage_limit_cents` declared on the contract's equipment
    class, verification is rejected with `ERR_INSURANCE_LIMIT_INSUFFICIENT`; a
    limit exactly equal to the requirement is sufficient."

    Design: Corner/validations/insurance_limit_below_type_requirement_returns_limit_insufficient
    """
    ctx = setup_reference_data()
    add_customer(ctx, "customer_two", legal_name="Second Fleet Co",
                 dot_number="DOT-222", credit_tier="A", with_certificate=False)
    thin = file_certificate(
        ctx["customer_two_id"], carrier_name="Thin Cover Mutual",
        policy_number="P-THIN", physical_damage_limit_cents=1_000_000,
    )

    agreement = validate_success(
        api.create_agreement(
            agreement_payload(ctx["customer_two_id"], ctx["branch_id"],
                              ctx["trailer_type_id"]),
            ADMIN,
        ),
        201,
    )
    validate_success(api.submit_agreement(agreement["id"], ADMIN))

    response = api.verify_agreement_insurance(agreement["id"], ADMIN)
    error = validate_error(response, ApiErrorId.ERR_INSURANCE_LIMIT_INSUFFICIENT.value)
    assert error["error_id"] != ApiErrorId.ERR_INSURANCE_INVALID.value

    stored = read_agreement(agreement["id"])
    assert stored["status"] == "PENDING_INSURANCE"
    assert stored.get("insurance_certificate_id") is None
    assert validate_success(
        api.get_insurance_certificate(thin["id"], ADMIN)
    )["status"] == "ACTIVE"


def test_verifying_insurance_on_a_draft_contract_is_rejected(api):
    """PRD §3.4: "Insurance verification is performed by a `FleetAdmin` or by the
    originating yard's `BranchManager` and advances the contract `PENDING_INSURANCE
    → PENDING_ALLOCATION`. A contract in any other status is rejected with
    `ERR_AGREEMENT_NOT_PENDING_INSURANCE`."

    Design: Corner/errors/verify_insurance_on_draft_agreement_reports_not_pending_insurance
    """
    ctx = setup_reference_data()
    agreement = open_agreement(ctx)

    response = api.verify_agreement_insurance(agreement["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_PENDING_INSURANCE.value)

    stored = read_agreement(agreement["id"])
    assert stored["status"] == "DRAFT"
    assert stored.get("insurance_certificate_id") is None


def test_certificate_lapses_to_expired_on_the_next_read_after_the_clock_moves(api):
    """PRD §3.2: "The move from `ACTIVE` to `EXPIRED` is not driven by any request:
    it is evaluated lazily, on every read of the certificate and on every reference
    to it during insurance verification, and it fires as soon as the clock date has
    passed the certificate's `expiry_date`."
    PRD §2.4: "The server starts with that logical clock fixed at
    `2026-08-01T00:00:00Z` and never falls back to real time."

    Design: Corner/state_machines/certificate_auto_expires_on_read_after_clock_advance
    """
    ctx = setup_reference_data()
    short = file_certificate(ctx["customer_id"], carrier_name="Short Cover Mutual",
                            policy_number="P-SHORT", expiry_date="2026-08-31")

    before = validate_success(api.get_insurance_certificate(short["id"], ADMIN))
    assert before["status"] == "ACTIVE"

    validate_success(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN)
    )

    after = validate_success(api.get_insurance_certificate(short["id"], ADMIN))
    assert after["status"] == "EXPIRED", "the flip needs no mutating call"
    assert after.get("revoked_reason") is None


def test_revoking_an_already_revoked_certificate_is_rejected(api):
    """PRD §3.2: "Revocation demands that the certificate be in status `ACTIVE`; a
    certificate in any other status — including one that has already lapsed to
    `EXPIRED` — is rejected with `ERR_CERTIFICATE_NOT_ACTIVE`."
    PRD §3.2: "it moves `ACTIVE → REVOKED` and records the supplied `reason` into
    `revoked_reason`."

    Design: Corner/errors/revoke_an_already_revoked_certificate_reports_not_active
    """
    ctx = setup_reference_data()
    validate_success(
        api.revoke_insurance_certificate(
            ctx["certificate_id"], {"reason": "carrier cancelled the policy"}, ADMIN
        )
    )

    response = api.revoke_insurance_certificate(
        ctx["certificate_id"], {"reason": "second attempt"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE.value)

    stored = validate_success(api.get_insurance_certificate(ctx["certificate_id"], ADMIN))
    assert stored["status"] == "REVOKED"
    assert stored["revoked_reason"] == "carrier cancelled the policy"


def test_risk_score_clamps_at_100_and_blocks_the_next_submission(api):
    """PRD §3.2: "Both finally clamp the result: the reported score is never below
    0 and never above 100."
    PRD §3.4: "Finally, the lessee's risk score under the underwriting snapshot
    variant must be no greater than 85; a score of 86 or above is rejected with
    `ERR_RISK_SCORE_TOO_HIGH`, while a score of exactly 85 passes."

    Design: Corner/calculations/underwriting_risk_score_capped_at_100_blocks_agreement_submit
    """
    ctx = setup_reference_data(
        customer={"legal_name": "Heavy Risk Carriers", "dot_number": "DOT-333",
                  "credit_tier": "C", "credit_limit_cents": 20_000_000},
        certificate={"policy_number": "P-C"},
    )
    scn = setup_approved_chargeback(
        ctx=ctx,
        line_items=[{"severity": "MAJOR", "quantity": 5, "unit_cost_cents": 100000,
                     "description": "frame rail damage"}],
    )
    assert scn["assessment"]["insured_portion_cents"] == 550000
    assert scn["assessment"]["customer_liable_cents"] == 250000
    assert scn["chargeback_amount"] == 270000

    review = validate_success(api.get_customer_risk_review(ctx["customer_id"], ADMIN))
    assert review["base_points"] == 45, "tier C contributes a base of 45 points"
    assert review["risk_score"] == 100, "45 + 54 + 3 = 102 raw, clamped to 100"

    second = validate_success(
        api.create_agreement(
            agreement_payload(ctx["customer_id"], ctx["branch_id"],
                              ctx["trailer_type_id"],
                              start_date="2026-10-01", end_date="2026-10-11"),
            ADMIN,
        ),
        201,
    )
    response = api.submit_agreement(second["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_RISK_SCORE_TOO_HIGH.value)

    stored = read_agreement(second["id"])
    assert stored["status"] == "DRAFT"
    assert stored.get("underwriting_risk_score") is None


def _short_cover_scenario():
    """A lessee holding only a certificate that lapses before the contract ends."""
    ctx = setup_reference_data(
        certificate={"carrier_name": "Short Cover Mutual", "policy_number": "P-SHORT",
                     "expiry_date": "2026-08-31"},
    )
    agreement = open_agreement(ctx)
    submit_for_underwriting(ctx, agreement["id"])
    ctx["agreement"] = agreement
    ctx["agreement_id"] = agreement["id"]
    return ctx


def test_insurance_verification_refuses_a_certificate_that_lapses_mid_contract(api):
    """PRD §3.4: "The server looks for a certificate belonging to the contract's
    lessee whose `status` is `ACTIVE`, whose `effective_date` is on or before the
    contract's `start_date`, and whose `expiry_date` is on or after the contract's
    `end_date` — coverage must span the entire contract window. If no such
    certificate exists, verification is rejected with `ERR_INSURANCE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/agreement_insurance_verification_gated_by_certificate_coverage_window
    """
    ctx = _short_cover_scenario()

    response = api.verify_agreement_insurance(ctx["agreement_id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_INSURANCE_INVALID.value)

    stored = read_agreement(ctx["agreement_id"])
    assert stored["status"] == "PENDING_INSURANCE", (
        "a refused verification leaves the contract where it stood"
    )
    assert stored.get("insurance_certificate_id") is None


def test_insurance_verification_pins_the_certificate_that_spans_the_window(api):
    """PRD §3.4: "When more than one certificate qualifies, the server pins the one
    with the greatest `expiry_date`, breaking a tie by taking the earlier
    `created_at`. That certificate's identifier is written to the contract's
    `insurance_certificate_id` and stays pinned for the life of the contract, and
    the contract's `version` increments by 1."
    PRD §3.4: "Insurance verification is performed by a `FleetAdmin` or by the
    originating yard's `BranchManager` and advances the contract `PENDING_INSURANCE
    → PENDING_ALLOCATION`."

    Design: Difficulty/cross_entity_state_dependency/agreement_insurance_verification_gated_by_certificate_coverage_window
    """
    ctx = _short_cover_scenario()
    short_id = ctx["certificate_id"]
    validate_error(
        api.verify_agreement_insurance(ctx["agreement_id"], ADMIN),
        ApiErrorId.ERR_INSURANCE_INVALID.value,
    )

    long_cert = file_certificate(ctx["customer_id"], policy_number="P-LONG",
                                 expiry_date="2027-01-01")

    agreement = validate_success(
        api.verify_agreement_insurance(ctx["agreement_id"], ADMIN)
    )
    assert agreement["status"] == "PENDING_ALLOCATION"
    assert agreement["insurance_certificate_id"] == long_cert["id"]
    assert agreement["insurance_certificate_id"] != short_id
    assert read_agreement(ctx["agreement_id"])["insurance_certificate_id"] == long_cert["id"]


def _two_chargeback_history():
    """One APPROVED chargeback of 108000 and one still-PENDING chargeback of 81000
    against the same lessee, so the two scoring variants see different exposure."""
    scn = setup_approved_chargeback()
    assert scn["chargeback_amount"] == 108000

    from test_helpers import open_assessment, submit_assessment
    second = open_assessment(
        scn,
        line_items=[{"severity": "MINOR", "quantity": 3, "unit_cost_cents": 25000,
                     "description": "floor gouges"}],
    )
    scn["assessment_two"] = submit_assessment(second["id"])
    scn["assessment_two_id"] = second["id"]
    scn["chargeback_two"] = find_chargeback(second["id"])
    return scn


def test_underwriting_snapshot_ignores_unadjudicated_exposure(api):
    """PRD §3.2: "It is deliberately blind to unadjudicated exposure: its
    chargeback total sums `amount_cents` over only those of the lessee's
    chargebacks whose status is `APPROVED` or `SETTLED`, and its assessment count
    counts only damage assessments in status `APPROVED` that are reachable from
    that lessee's contract unit lines."
    PRD §3.2: "Both then add two points for every full one hundred dollars — that
    is, every full 10000 cents — of chargeback exposure, computed by dividing the
    qualifying chargeback total in cents by 10000, discarding the remainder, and
    multiplying the whole-number result by 2."

    Design: Difficulty/dual_variant_calc/customer_risk_underwriting_snapshot_vs_renewal_review_diverge
    """
    scn = _two_chargeback_history()

    second_agreement = validate_success(
        api.create_agreement(
            agreement_payload(scn["customer_id"], scn["branch_id"],
                              scn["trailer_type_id"],
                              start_date="2026-10-01", end_date="2026-10-11"),
            scn["customer_headers"],
        ),
        201,
    )
    submitted = validate_success(
        api.submit_agreement(second_agreement["id"], scn["customer_headers"])
    )
    assert submitted["underwriting_risk_score"] == 48, (
        "tier B base 25 + 20 points on the 108000 APPROVED chargeback "
        "+ 3 points for the single APPROVED assessment"
    )
    assert read_agreement(second_agreement["id"])["underwriting_risk_score"] == 48
    assert read_damage_assessment(scn["assessment_id"])["status"] == "APPROVED"
    assert read_damage_assessment(scn["assessment_two_id"])["status"] == "SUBMITTED"


def test_renewal_review_sees_more_exposure_than_the_underwriting_snapshot(api):
    """PRD §3.2: "Its chargeback total is drawn from a wider status set —
    `PENDING`, `DISPUTED`, `APPROVED` and `SETTLED` — and each such chargeback is
    weighted before summing: a chargeback whose age in days, measured from the
    calendar date of its `created_at` to the clock date, is strictly greater than
    180 days contributes half its `amount_cents` with the remainder discarded,
    while a chargeback 180 days old or newer contributes its full `amount_cents`."
    PRD §3.2: "Because it sees unadjudicated exposure that the snapshot variant
    ignores, for identical data with an outstanding unadjudicated chargeback the
    renewal review returns a strictly higher number than the underwriting
    snapshot."

    Design: Difficulty/dual_variant_calc/customer_risk_underwriting_snapshot_vs_renewal_review_diverge
    """
    scn = _two_chargeback_history()

    second_agreement = validate_success(
        api.create_agreement(
            agreement_payload(scn["customer_id"], scn["branch_id"],
                              scn["trailer_type_id"],
                              start_date="2026-10-01", end_date="2026-10-11"),
            scn["customer_headers"],
        ),
        201,
    )
    snapshot = validate_success(
        api.submit_agreement(second_agreement["id"], scn["customer_headers"])
    )["underwriting_risk_score"]

    review = validate_success(api.get_customer_risk_review(scn["customer_id"], ADMIN))
    assert review["customer_id"] == scn["customer_id"]
    assert review["weighted_chargeback_cents"] == 189000
    assert review["risk_score"] == 67, (
        "tier B base 25 + 36 points on 189000 of exposure "
        "+ 6 points for two qualifying assessments"
    )
    assert review["risk_score"] > snapshot
    assert review["outstanding_chargeback_cents"] == 189000
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 189000
