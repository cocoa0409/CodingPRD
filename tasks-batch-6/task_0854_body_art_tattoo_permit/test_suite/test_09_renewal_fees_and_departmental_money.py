"""Renewal applications, the tiered fee schedule and departmental money."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_net_departmental_fees,
    assert_renewal_application,
    cite_violation,
    create_active_artist,
    create_permitted_establishment,
    create_renewal_application_payload,
    create_submitted_renewal,
    establishment_version,
    file_sterilization_record,
    make_operator_headers,
    open_renewal_application,
    pay_renewal_application,
    read_establishment,
    review_renewal_application,
    start_inspection_at,
    submit_renewal_application,
    validate_error,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
CLERK = TEST_USERS["records_clerk_headers"]


def test_estimate_fee_rounds_each_line_before_summing_them(api):
    """PRD §3.9: "Each of those four raw lines is then multiplied by the county
    administrative multiplier of 1.075 and that product is rounded half up to a whole
    cent"
    PRD §3.9: "Summing the raw lines first and rounding once at the end is explicitly
    not the rule and produces a different subtotal in the general case."
    PRD §3.9: "is tiered: the first three artists are charged 7500 cents each, artists
    four through eight are charged 6000 cents each, and every artist beyond the eighth
    is charged 4500 cents each"
    PRD §3.9: "is 1050 cents for every artist in the count, untiered."

    Design: Difficulty/combinatorial_formula/renewal_fee_rounds_each_line_before_summing
    """
    establishment = create_permitted_establishment(
        name="Bluebird Body Art", street_address="77 Pine St",
        establishment_type="PIERCING",
    )
    create_active_artist(establishment["id"], "Sol Marek")
    application = open_renewal_application(establishment["id"])

    submitted = validate_success(
        api.submit_renewal_application(
            application["id"], make_operator_headers(establishment["id"])
        )
    )
    assert submitted["fee_estimate_cents"] == 36067, (
        "26875 + 8063 + 1129 per rounded line, got "
        f"{submitted['fee_estimate_cents']}"
    )
    assert submitted["fee_estimate_cents"] != 36066, (
        "36066 is the sum-then-round figure the specification rejects"
    )
    assert submitted["late_fee_applied"] is False


def test_submission_snapshots_the_active_roster_and_advances_the_cycle(api):
    """PRD §3.9: "Either way, submission stamps `submitted_at` with the current
    logical-clock instant, refreshes `artist_count_at_submit` from the establishment's
    current `active_artist_count`, increments `cycle_count` by one, clears
    `deficiency_code` back to null, and writes `fee_estimate_cents` and
    `late_fee_applied` from the estimate variant of the fee schedule."
    PRD §3.9: "The application is born `DRAFT` with `cycle_count` at zero,
    `payment_status` `UNPAID`, `late_fee_applied` false, `fee_paid_cents`,
    `fee_refunded_cents` and `fee_balance_due_cents` all zero, and `submitted_at`,
    `artist_count_at_submit`, `fee_estimate_cents`, `fee_final_cents`,
    `deficiency_code`, `decided_by_user_id` and `decided_at` all null."

    Design: Difficulty/combinatorial_formula/renewal_fee_rounds_each_line_before_summing
    """
    establishment = create_permitted_establishment(
        name="Bluebird Two", street_address="78 Pine St", establishment_type="PIERCING"
    )
    create_active_artist(establishment["id"], "Sol Marek")

    draft = open_renewal_application(establishment["id"])
    assert_renewal_application(draft)
    assert draft["status"] == "DRAFT"
    assert draft["cycle_count"] == 0
    assert draft["payment_status"] == "UNPAID"
    assert draft["fee_estimate_cents"] is None

    submitted = submit_renewal_application(draft["id"], establishment["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["cycle_count"] == 1
    assert submitted["artist_count_at_submit"] == 1
    assert submitted["fee_estimate_cents"] == 36067


def _estimate_versus_final_scenario():
    establishment = create_permitted_establishment(
        name="Needle & Thread", street_address="44 Oak Ave",
        establishment_type="COMBINED",
    )
    create_active_artist(establishment["id"], "Rae Lin")
    file_sterilization_record(establishment["id"], "2026-04-20T00:00:00Z", "PASS")

    application = create_submitted_renewal(establishment["id"])
    create_active_artist(establishment["id"], "Kai Vo")
    pay_renewal_application(application["id"], 36067)
    return establishment, application


def test_final_fee_re_reads_the_roster_and_diverges_from_the_estimate(api):
    """PRD §3.9: "variant is written to `fee_estimate_cents` at submission, using
    `artist_count_at_submit` as the artist count and `submitted_at` as the evaluation
    instant."
    PRD §3.9: "variant is written to `fee_final_cents` at approval, using the
    establishment's `active_artist_count` re-read at that moment as the artist count
    and `decided_at` as the evaluation instant."
    PRD §3.9: "An approval drives `SUBMITTED → APPROVED`, writes `fee_final_cents` and
    sets `fee_balance_due_cents` to `fee_final_cents` less `fee_paid_cents` floored at
    zero, and stamps `decided_by_user_id` and `decided_at`."

    Design: Difficulty/dual_variant_calc/renewal_fee_estimate_vs_final_diverge_on_artist_count
    """
    _establishment, application = _estimate_versus_final_scenario()
    assert application["fee_estimate_cents"] == 36067

    approved = review_renewal_application(application["id"], "APPROVE")
    assert approved["fee_final_cents"] == 45258, (
        "26875 + 16125 + 2258 for a roster of two, got "
        f"{approved['fee_final_cents']}"
    )
    assert approved["fee_balance_due_cents"] == 9191, (
        f"45258 less the 36067 already paid, got {approved['fee_balance_due_cents']}"
    )


def test_approved_renewal_extends_the_permit_term_by_a_full_year(api):
    """PRD §3.9: "Artists activated or deactivated between submission and approval move
    the count, and an approval recorded after `permit_expires_on` adds the late line
    even when the submission itself was on time, so the two figures differ for
    identical stored inputs."
    PRD §3.9: "In both cases `permit_issued_on` is set to the decision instant and
    `permit_expires_on` to exactly 365 days after that instant — the unused remainder
    of the old term is not carried forward, so an early renewal costs the operator the
    leftover days."

    Design: Difficulty/dual_variant_calc/renewal_fee_estimate_vs_final_diverge_on_artist_count
    """
    establishment, application = _estimate_versus_final_scenario()

    approved = review_renewal_application(application["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    assert approved["artist_count_at_submit"] == 1, (
        "The snapshot taken at submission does not move when the roster grows"
    )
    assert approved["late_fee_applied"] is False

    parent = read_establishment(establishment["id"])
    assert_instant_equals(
        parent["permit_expires_on"], "2027-05-01T00:00:00Z", "permit_expires_on"
    )
    assert parent["active_artist_count"] == 2


def _paid_then_denied_application():
    establishment = create_permitted_establishment(
        name="Ledger Ink", street_address="6 Cypress Ct"
    )
    before = read_establishment(establishment["id"])
    application = create_submitted_renewal(establishment["id"])
    paid = pay_renewal_application(application["id"], 26875)
    mid = read_establishment(establishment["id"])
    review_renewal_application(application["id"], "DENY")
    return establishment, application, before, paid, mid


def test_refund_after_denial_returns_the_money_on_the_application(api):
    """PRD §3.9: "A successful payment adds `amount_cents` to `fee_paid_cents`, sets
    `payment_status` to `PAID`, recomputes `fee_balance_due_cents` as `fee_final_cents`
    less `fee_paid_cents` floored at zero — a figure that stays at zero for as long as
    `fee_final_cents` is null — refreshes the establishment's `fees_paid_cents`, and
    increments the establishment's `version` by one."
    PRD §3.9: "The refund sets `fee_refunded_cents` equal to `fee_paid_cents` and
    `payment_status` to `REFUNDED`, then refreshes the establishment's
    `fees_refunded_cents` so that the difference between the establishment's
    `fees_paid_cents` and `fees_refunded_cents` returns to its pre-payment figure, and
    increments the establishment's `version` by one."

    Design: Difficulty/compensating_invariant/renewal_payment_then_refund_leaves_establishment_net_fees_at_zero
    """
    _establishment, application, before, paid, mid = _paid_then_denied_application()
    assert before["fees_paid_cents"] == 0 and before["fees_refunded_cents"] == 0
    assert paid["payment_status"] == "PAID"
    assert mid["fees_paid_cents"] == 26875 and mid["fees_refunded_cents"] == 0

    refunded = validate_success(api.refund_renewal_application(application["id"], CLERK))
    assert refunded["fee_paid_cents"] == 26875
    assert refunded["fee_refunded_cents"] == 26875
    assert refunded["payment_status"] == "REFUNDED"
    assert refunded["status"] == "DENIED"


def test_payment_and_refund_return_the_net_departmental_position_to_zero(api):
    """PRD §3.9: "The establishment's `fees_paid_cents` and `fees_refunded_cents` are
    simple sums of `fee_paid_cents` and `fee_refunded_cents` across every renewal
    application of that premises in any status."
    PRD §3.9: "The refund sets `fee_refunded_cents` equal to `fee_paid_cents` and
    `payment_status` to `REFUNDED`, then refreshes the establishment's
    `fees_refunded_cents` so that the difference between the establishment's
    `fees_paid_cents` and `fees_refunded_cents` returns to its pre-payment figure, and
    increments the establishment's `version` by one."

    Design: Difficulty/compensating_invariant/renewal_payment_then_refund_leaves_establishment_net_fees_at_zero
    """
    establishment, application, before, _paid, _mid = _paid_then_denied_application()
    assert_net_departmental_fees(before, 0)

    validate_success(api.refund_renewal_application(application["id"], CLERK))

    parent = read_establishment(establishment["id"])
    assert parent["fees_paid_cents"] == 26875
    assert parent["fees_refunded_cents"] == 26875
    assert_net_departmental_fees(parent, 0)


def _unpaid_application_with_open_critical():
    establishment = create_permitted_establishment(
        name="Fiscal Fault Studio", street_address="30 Aspen Dr"
    )
    file_sterilization_record(
        establishment["id"], "2026-04-25T00:00:00Z", "PASS", device_serial="AC-9"
    )
    inspection = start_inspection_at(
        establishment["id"], "2026-05-02T00:00:00Z", "2026-05-02T02:00:00Z"
    )
    cite_violation(
        inspection["id"], "BBP_001", "CRITICAL", "Unsheathed needles on counter."
    )
    application = create_submitted_renewal(establishment["id"])
    return establishment, application


def test_open_critical_violation_is_reported_before_the_unpaid_fee(api):
    """PRD §3.9: "Approval is guarded by five conditions evaluated in this order: the
    establishment's `open_critical_violation_count` must be zero, failing which the
    approval is rejected with `ERR_OPEN_CRITICAL_VIOLATION_BLOCKS_RENEWAL` (HTTP 409);
    the establishment's `sterilization_compliance_status` must be `COMPLIANT` or
    `DEFICIENT`, with `NONCOMPLIANT` rejected as `ERR_STERILIZATION_NONCOMPLIANT` (HTTP
    409); no enforcement action against that establishment may still be `ACTIVE`,
    failing which the rejection is `ERR_ACTIVE_ENFORCEMENT_BLOCKS_RENEWAL` (HTTP 409);
    both `attested_bbp_current` and `attested_sterilization_logs_complete` must be
    true, failing which the rejection is `ERR_RENEWAL_ATTESTATION_MISSING` (HTTP 422);
    and `payment_status` must be `PAID`, failing which the rejection is
    `ERR_RENEWAL_FEE_UNPAID` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/open_critical_safety_error_beats_unpaid_fee_fiscal_error_on_renewal_approve
    """
    _establishment, application = _unpaid_application_with_open_critical()
    assert application["payment_status"] == "UNPAID"

    response = api.review_renewal_application(
        application["id"], {"decision": "APPROVE"}, HO
    )
    error = validate_error(
        response, ApiErrorId.ERR_OPEN_CRITICAL_VIOLATION_BLOCKS_RENEWAL.value
    )
    assert response.status_code == 409, (
        "The safety gate wins, so the 402 the fee gate would carry never appears"
    )
    assert error["error_id"] != ApiErrorId.ERR_RENEWAL_FEE_UNPAID.value


def test_rejected_approval_leaves_the_fee_figures_and_counters_untouched(api):
    """PRD §3.9: "the establishment's `open_critical_violation_count` must be zero,
    failing which the approval is rejected with
    `ERR_OPEN_CRITICAL_VIOLATION_BLOCKS_RENEWAL` (HTTP 409)"
    PRD §3.4: "The open set is defined across every violation reachable through that
    establishment's inspections whose status is `ISSUED`, `CORRECTION_SUBMITTED` or
    `ESCALATED`, with the critical counter restricted further to rows whose `severity`
    is `CRITICAL`; no time window applies to either count."

    Design: Difficulty/priority_pair_validation_conflict/open_critical_safety_error_beats_unpaid_fee_fiscal_error_on_renewal_approve
    """
    establishment, application = _unpaid_application_with_open_critical()
    assert application["fee_estimate_cents"] == 26875

    blocked = api.review_renewal_application(
        application["id"], {"decision": "APPROVE"}, HO
    )
    validate_error(blocked, ApiErrorId.ERR_OPEN_CRITICAL_VIOLATION_BLOCKS_RENEWAL.value)

    stored = validate_success(api.get_renewal_application(application["id"], HO))
    assert stored["status"] == "SUBMITTED"
    assert stored["fee_final_cents"] is None

    parent = read_establishment(establishment["id"])
    assert parent["open_critical_violation_count"] == 1


def test_expedite_line_is_multiplied_and_rounded_on_its_own(api):
    """PRD §3.9: "is 10000 cents when `expedite_requested` is true and nothing when it
    is false."
    PRD §3.9: "Each of those four raw lines is then multiplied by the county
    administrative multiplier of 1.075 and that product is rounded half up to a whole
    cent"
    PRD §3.9: "Let the artist count be the number of practitioners at the premises
    holding `permit_status` `ACTIVE`; practitioners in `PENDING`, `PROBATION`,
    `SUSPENDED`, `INACTIVE` or `REVOKED` do not count."

    Design: Corner/calculations/renewal_fee_includes_expedite_line_when_requested
    """
    establishment = create_permitted_establishment(
        name="Expedite Ink", street_address="25 Twentyfifth St"
    )
    application = open_renewal_application(establishment["id"], expedite_requested=True)

    submitted = submit_renewal_application(application["id"], establishment["id"])
    assert submitted["fee_estimate_cents"] == 37625, (
        f"26875 base plus a 10750 expedite line, got {submitted['fee_estimate_cents']}"
    )
    assert submitted["artist_count_at_submit"] == 0
    assert submitted["expedite_requested"] is True
    assert submitted["late_fee_applied"] is False


def test_renewal_review_gates_surface_in_their_declared_order(api):
    """PRD §3.9: "Approval is guarded by five conditions evaluated in this order: the
    establishment's `open_critical_violation_count` must be zero, failing which the
    approval is rejected with `ERR_OPEN_CRITICAL_VIOLATION_BLOCKS_RENEWAL` (HTTP 409);
    the establishment's `sterilization_compliance_status` must be `COMPLIANT` or
    `DEFICIENT`, with `NONCOMPLIANT` rejected as `ERR_STERILIZATION_NONCOMPLIANT` (HTTP
    409); no enforcement action against that establishment may still be `ACTIVE`,
    failing which the rejection is `ERR_ACTIVE_ENFORCEMENT_BLOCKS_RENEWAL` (HTTP 409);
    both `attested_bbp_current` and `attested_sterilization_logs_complete` must be
    true, failing which the rejection is `ERR_RENEWAL_ATTESTATION_MISSING` (HTTP 422);
    and `payment_status` must be `PAID`, failing which the rejection is
    `ERR_RENEWAL_FEE_UNPAID` (HTTP 402)."
    PRD §3.9: "Every prior renewal application for the same premises sitting in
    `DRAFT`, `SUBMITTED` or `DEFICIENT` is moved to `SUPERSEDED`, each bumping its own
    `version` by one, and the establishment's own `version` increments by one as well."

    Design: Corner/validations/renewal_review_gates_fire_in_priority_order_sterilization_attestation_fee
    """
    establishment = create_permitted_establishment(
        name="Gate Order Ink", street_address="32 Thirtysecond St"
    )
    first = create_submitted_renewal(establishment["id"], attested_bbp_current=False)

    noncompliant = api.review_renewal_application(
        first["id"], {"decision": "APPROVE"}, HO
    )
    validate_error(noncompliant, ApiErrorId.ERR_STERILIZATION_NONCOMPLIANT.value)
    assert noncompliant.status_code == 409

    file_sterilization_record(
        establishment["id"], "2026-04-27T00:00:00Z", "PASS", device_serial="AC-11"
    )
    attestation = api.review_renewal_application(
        first["id"], {"decision": "APPROVE"}, HO
    )
    validate_error(attestation, ApiErrorId.ERR_RENEWAL_ATTESTATION_MISSING.value)
    assert attestation.status_code == 422

    second = create_submitted_renewal(establishment["id"])
    unpaid = api.review_renewal_application(second["id"], {"decision": "APPROVE"}, HO)
    validate_error(unpaid, ApiErrorId.ERR_RENEWAL_FEE_UNPAID.value)
    assert unpaid.status_code == 402

    superseded = validate_success(api.get_renewal_application(first["id"], HO))
    assert superseded["status"] == "SUPERSEDED"
    assert second["status"] == "SUBMITTED"
    assert second["fee_estimate_cents"] == 26875

    parent = read_establishment(establishment["id"])
    assert_instant_equals(
        parent["permit_expires_on"], "2027-05-01T00:00:00Z", "permit_expires_on"
    )


def test_partial_payment_and_premature_refund_are_rejected(api):
    """PRD §3.9: "The payment must settle the outstanding amount exactly: while the
    application is `SUBMITTED` or `DEFICIENT` the outstanding amount is
    `fee_estimate_cents` less `fee_paid_cents`, and once the application is `APPROVED`
    it is `fee_balance_due_cents`."
    PRD §3.9: "Any other figure is rejected with `ERR_FEE_AMOUNT_MISMATCH` (HTTP 422),
    and a payment against an application in any other status is rejected with
    `ERR_RENEWAL_STATE_INVALID` (HTTP 409)."
    PRD §3.9: "Returning money is the `RecordsClerk`'s exclusive act, and it is
    deliberately narrow: a refund requires `payment_status` of `PAID` and an
    application status of either `DENIED` or `SUPERSEDED`, and any other combination is
    rejected with `ERR_REFUND_NOT_ALLOWED` (HTTP 409)."

    Design: Corner/validations/renewal_payment_amount_mismatch_and_premature_refund_rejected
    """
    establishment = create_permitted_establishment(
        name="Money Gate Ink", street_address="36 Thirtysixth St"
    )
    application = create_submitted_renewal(establishment["id"])
    operator = make_operator_headers(establishment["id"])

    short = api.pay_renewal_application(
        application["id"], {"amount_cents": 20000}, operator
    )
    validate_error(short, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)
    assert short.status_code == 422

    early_refund = api.refund_renewal_application(application["id"], CLERK)
    validate_error(early_refund, ApiErrorId.ERR_REFUND_NOT_ALLOWED.value)
    assert early_refund.status_code == 409

    paid = validate_success(
        api.pay_renewal_application(application["id"], {"amount_cents": 26875}, operator)
    )
    assert paid["payment_status"] == "PAID"

    submitted_refund = api.refund_renewal_application(application["id"], CLERK)
    validate_error(submitted_refund, ApiErrorId.ERR_REFUND_NOT_ALLOWED.value)
    assert submitted_refund.status_code == 409

    stored = validate_success(api.get_renewal_application(application["id"], HO))
    assert stored["fee_paid_cents"] == 26875
    assert stored["fee_refunded_cents"] == 0
    assert read_establishment(establishment["id"])["fees_paid_cents"] == 26875


def test_renewal_resubmission_is_capped_at_three_cycles(api):
    """PRD §3.9: "It drives `DRAFT → SUBMITTED` from a fresh application and `DEFICIENT
    → SUBMITTED` from one the department sent back, and the second of those is capped:
    a resubmission is admissible only while `cycle_count` is strictly below 3, and
    beyond that ceiling it is rejected with `ERR_RENEWAL_CYCLE_LIMIT` (HTTP 409)."
    PRD §3.9: "A deficiency decision drives `SUBMITTED → DEFICIENT` and records the
    supplied `deficiency_code`, which is one of `MISSING_BBP_ATTESTATION`,
    `MISSING_STERILIZATION_ATTESTATION`, `OPEN_CRITICAL_VIOLATION` or
    `ARTIST_ROSTER_MISMATCH`, alongside `decided_by_user_id` and `decided_at`."

    Design: Corner/errors/renewal_cycle_limit_after_three_submissions
    """
    establishment = create_permitted_establishment(
        name="Renewal Loop Ink", street_address="46 Fortysixth St"
    )
    application = open_renewal_application(establishment["id"])
    operator = make_operator_headers(establishment["id"])

    first = submit_renewal_application(application["id"], establishment["id"])
    assert first["cycle_count"] == 1

    duplicate = api.submit_renewal_application(application["id"], operator)
    validate_error(duplicate, ApiErrorId.ERR_RENEWAL_STATE_INVALID.value)
    assert duplicate.status_code == 409

    review_renewal_application(
        application["id"], "MARK_DEFICIENT",
        deficiency_code="MISSING_STERILIZATION_ATTESTATION",
    )
    submit_renewal_application(application["id"], establishment["id"])
    review_renewal_application(
        application["id"], "MARK_DEFICIENT", deficiency_code="ARTIST_ROSTER_MISMATCH"
    )
    third = submit_renewal_application(application["id"], establishment["id"])
    assert third["cycle_count"] == 3

    marked = review_renewal_application(
        application["id"], "MARK_DEFICIENT", deficiency_code="OPEN_CRITICAL_VIOLATION"
    )
    assert marked["deficiency_code"] == "OPEN_CRITICAL_VIOLATION"

    over_limit = api.submit_renewal_application(application["id"], operator)
    validate_error(over_limit, ApiErrorId.ERR_RENEWAL_CYCLE_LIMIT.value)
    assert over_limit.status_code == 409

    stored = validate_success(api.get_renewal_application(application["id"], HO))
    assert stored["status"] == "DEFICIENT"
    assert stored["cycle_count"] == 3


def test_stale_establishment_version_blocks_a_second_renewal_create(api):
    """PRD §2.8: "Creating a renewal application requires
    `expected_establishment_version` carrying the client's last observed `version` of
    the target establishment. If that value does not equal the establishment's current
    `version` at the moment the write is applied, the create is rejected with
    `ERR_STALE_ESTABLISHMENT_VERSION` (HTTP 412)."
    PRD §3.9: "Every prior renewal application for the same premises sitting in
    `DRAFT`, `SUBMITTED` or `DEFICIENT` is moved to `SUPERSEDED`, each bumping its own
    `version` by one, and the establishment's own `version` increments by one as well."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_establishment_version_rejects_second_renewal_create
    """
    establishment = create_permitted_establishment(
        name="OCC Establishment Ink", street_address="53 Fiftythird St"
    )
    operator = make_operator_headers(establishment["id"])
    observed = establishment_version(establishment["id"])

    first = validate_success(
        api.create_renewal_application(
            create_renewal_application_payload(establishment["id"], observed), operator
        ),
        201,
    )

    stale = api.create_renewal_application(
        create_renewal_application_payload(establishment["id"], observed), operator
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ESTABLISHMENT_VERSION.value)
    assert stale.status_code == 412

    refreshed_version = establishment_version(establishment["id"])
    assert refreshed_version == observed + 1

    second = validate_success(
        api.create_renewal_application(
            create_renewal_application_payload(establishment["id"], refreshed_version),
            operator,
        ),
        201,
    )
    assert second["status"] == "DRAFT"

    superseded = validate_success(api.get_renewal_application(first["id"], HO))
    assert superseded["status"] == "SUPERSEDED"

    _, meta = validate_paginated(
        api.list_renewal_applications(
            HO, params={"establishment_id": establishment["id"]}
        )
    )
    assert meta["total_count"] == 2
