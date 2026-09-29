"""Negotiated resolution: offers, the settlement floor, agreements and the stay cycle."""

from test_helpers import (
    ApiErrorId,
    advance_clock,
    agreement_for_offer,
    assert_installment_agreement,
    assert_settlement_offer,
    assert_sweep_summary_shape,
    create_settlement_offer_payload,
    create_verified_finding,
    draft_enforcement_action,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_debtor_headers,
    make_enforcement_officer_headers,
    read_action,
    read_agreement,
    read_finding,
    read_judgment,
    read_offer,
    record_misses,
    setup_active_agreement,
    setup_judgment,
    setup_perfected_judgment,
    setup_served_bank_levy,
    setup_stayed_judgment,
    tender_offer,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
CO = make_compliance_officer_headers("co-1")


# ==========================================================================
# Accepting an offer creates the agreement and stays enforcement
# ==========================================================================
def test_acceptance_snapshots_the_schedule_and_creates_the_active_agreement(api):
    """PRD §3.7: "`min_acceptable_cents` is the settlement floor: take a payoff
    replay of the judgment as of the current clock date, multiply its
    `total_payoff_cents` by 6,000 basis points — sixty percent — divide by ten
    thousand, and round down to a whole cent."
    PRD §3.7: "At creation the offer snapshots two derived figures.
    `monthly_cents` is `amount_cents` divided by `installment_count`, rounded
    **up** to a whole cent."
    PRD §3.7: "First an installment agreement is created in status `ACTIVE`,
    carrying the accepted offer's `judgment_id` and `settlement_offer_id`, with
    `total_cents` copied from the offer's `amount_cents`, `installment_count`
    copied from the offer, `monthly_cents` equal to `total_cents` divided by
    `installment_count` rounded up to a whole cent, `final_installment_cents`
    equal to `total_cents` less `monthly_cents` multiplied by one fewer than
    `installment_count`, `first_due_on` set to 30 days after the current clock
    date, `application_order_concession` copied from the offer, and
    `paid_to_date_cents`, `missed_count` and `reinstatement_count` all at 0."

    Design: Difficulty/transitive_cascade/settlement_acceptance_stay_cascade_depth_four
    """
    ctx = setup_served_bank_levy(
        finding_value_cents=900_000,
        court_case_number="CV-2026-0402",
        debtor_overrides={"weekly_disposable_earnings_cents": 100_000},
        filing_overrides={"fee_cents": 0},
    )
    offer = tender_offer(
        ctx["judgment"]["id"], CM,
        offered_by="CREDITOR", kind="INSTALLMENT",
        amount_cents=3_600_000, installment_count=12,
        application_order_concession="PRINCIPAL_FIRST",
    )
    assert_settlement_offer(offer)
    assert offer["min_acceptable_cents"] == 3_208_746
    assert offer["monthly_cents"] == 300_000
    assert offer["round_number"] == 1

    accepted = validate_success(
        api.accept_settlement_offer(
            offer["id"], make_debtor_headers(ctx["debtor"]["id"])
        )
    )
    assert accepted["status"] == "ACCEPTED"

    agreement = agreement_for_offer(offer["id"])
    assert_installment_agreement(agreement)
    assert agreement["status"] == "ACTIVE"
    assert agreement["total_cents"] == 3_600_000
    assert agreement["final_installment_cents"] == 300_000
    assert agreement["first_due_on"] == "2026-08-31"
    assert agreement["application_order_concession"] == "PRINCIPAL_FIRST"


def test_the_activated_agreement_stays_the_levy_without_releasing_its_funds(api):
    """PRD §3.7: "Second, because an agreement has become `ACTIVE`, the judgment's
    `application_order` is set to that agreement's `application_order_concession`
    and, **if and only if** the `enforcement_posture` is currently `ENFORCING`,
    the posture moves `ENFORCING → STAYED`."
    PRD §3.5: "When an installment agreement activates and drives the posture
    `ENFORCING → STAYED`, every enforcement action on that judgment sitting in
    `SERVED` moves `SERVED → SUSPENDED`, in `created_at` ascending order — and the
    money stays where it is: `levy_hold_cents` is untouched and the finding's
    custody split between `available_cents` and `frozen_cents` is left exactly as
    it was."

    Design: Difficulty/transitive_cascade/settlement_acceptance_stay_cascade_depth_four
    """
    ctx = setup_stayed_judgment(
        finding_value_cents=900_000,
        court_case_number="CV-2026-0405",
        concession="PRINCIPAL_FIRST",
        debtor_overrides={"weekly_disposable_earnings_cents": 100_000},
        filing_overrides={"fee_cents": 0},
    )

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["enforcement_posture"] == "STAYED"
    assert judgment["application_order"] == "PRINCIPAL_FIRST"

    action = read_action(ctx["action"]["id"])
    assert action["status"] == "SUSPENDED"
    assert action["levy_hold_cents"] == 725_000

    finding = read_finding(ctx["finding"]["id"])
    assert finding["frozen_cents"] == 725_000
    assert finding["available_cents"] == 175_000


# ==========================================================================
# The third miss defaults the agreement and resumes enforcement
# ==========================================================================
def test_the_first_two_misses_leave_the_agreement_active(api):
    """PRD §3.7: "A `CaseManager` records a missed instalment; each recording
    increments `missed_count` by one, and the third miss — the miss that brings
    `missed_count` to 3 — defaults the agreement, moving it `ACTIVE → DEFAULTED`."

    Design: Difficulty/transitive_cascade/agreement_default_resume_cascade_depth_three
    """
    ctx = setup_stayed_judgment(
        finding_value_cents=900_000,
        court_case_number="CV-2026-0403",
        concession="PRINCIPAL_FIRST",
        debtor_overrides={"weekly_disposable_earnings_cents": 100_000},
        filing_overrides={"fee_cents": 0},
    )
    agreement_id = ctx["agreement"]["id"]

    first = validate_success(api.record_installment_miss(agreement_id, CM))
    assert first["missed_count"] == 1
    assert first["status"] == "ACTIVE"

    second = validate_success(api.record_installment_miss(agreement_id, CM))
    assert second["missed_count"] == 2
    assert second["status"] == "ACTIVE"

    third = validate_success(api.record_installment_miss(agreement_id, CM))
    assert third["missed_count"] == 3
    assert third["status"] == "DEFAULTED"


def test_the_default_resumes_the_suspended_levy_with_its_hold_intact(api):
    """PRD §3.7: "That default returns the judgment's `enforcement_posture`
    `STAYED → ENFORCING`, reverts `application_order` to `STATUTORY_ORDER`,
    resumes every `SUSPENDED` enforcement action on the judgment to `SERVED` in
    `created_at` ascending order, replays the judgment's balances under the
    reverted application order — which genuinely changes `principal_balance_cents`
    and `accrued_interest_cents`, since the two orders produce different histories
    — and increments the judgment's `version` by one."
    PRD §3.5: "When that agreement later defaults and the posture returns `STAYED
    → ENFORCING`, every `SUSPENDED` action returns `SUSPENDED → SERVED`, again in
    `created_at` ascending order and again with no custody change."

    Design: Difficulty/transitive_cascade/agreement_default_resume_cascade_depth_three
    """
    ctx = setup_stayed_judgment(
        finding_value_cents=900_000,
        court_case_number="CV-2026-0406",
        concession="PRINCIPAL_FIRST",
        debtor_overrides={"weekly_disposable_earnings_cents": 100_000},
        filing_overrides={"fee_cents": 0},
    )
    record_misses(ctx["agreement"]["id"], 3)

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["enforcement_posture"] == "ENFORCING"
    assert judgment["application_order"] == "STATUTORY_ORDER"

    action = read_action(ctx["action"]["id"])
    assert action["status"] == "SERVED"
    assert action["levy_hold_cents"] == 725_000
    assert read_finding(ctx["finding"]["id"])["frozen_cents"] == 725_000


# ==========================================================================
# The agreement's own ACTIVE -> DEFAULTED -> ACTIVE cycle
# ==========================================================================
def test_three_misses_default_an_agreement_built_from_the_accepted_offer(api):
    """PRD §3.7: "A `CaseManager` records a missed instalment; each recording
    increments `missed_count` by one, and the third miss — the miss that brings
    `missed_count` to 3 — defaults the agreement, moving it `ACTIVE → DEFAULTED`."
    PRD §3.7: "First an installment agreement is created in status `ACTIVE`,
    carrying the accepted offer's `judgment_id` and `settlement_offer_id`, with
    `total_cents` copied from the offer's `amount_cents`, `installment_count`
    copied from the offer, `monthly_cents` equal to `total_cents` divided by
    `installment_count` rounded up to a whole cent, `final_installment_cents`
    equal to `total_cents` less `monthly_cents` multiplied by one fewer than
    `installment_count`, `first_due_on` set to 30 days after the current clock
    date, `application_order_concession` copied from the offer, and
    `paid_to_date_cents`, `missed_count` and `reinstatement_count` all at 0."

    Design: Difficulty/non_linear_state_machine/installment_agreement_active_defaulted_active_reinstatement_cycle
    """
    ctx = setup_active_agreement(court_case_number="CV-2026-0303")
    assert ctx["agreement"]["monthly_cents"] == 300_000
    assert ctx["agreement"]["first_due_on"] == "2026-08-31"

    defaulted = record_misses(ctx["agreement"]["id"], 3)
    assert defaulted["status"] == "DEFAULTED"
    assert defaulted["missed_count"] == 3


def test_reinstatement_returns_the_agreement_to_active_and_clears_the_misses(api):
    """PRD §3.7: "A `ComplianceOfficer` may reinstate a defaulted agreement, but
    only once: `reinstatement_count` must be strictly less than 1, and a second
    attempt is `ERR_REINSTATEMENT_LIMIT`."
    PRD §3.7: "Reinstatement resets `missed_count` to 0, increments
    `reinstatement_count` by one, moves the agreement `DEFAULTED → ACTIVE`,
    returns the posture `ENFORCING → STAYED`, re-applies the agreement's
    `application_order_concession` to the judgment's `application_order`, suspends
    every `SERVED` enforcement action on the judgment in `created_at` ascending
    order, and increments the judgment's `version` by one."
    PRD §3.7: "The agreement may therefore cycle `ACTIVE → DEFAULTED → ACTIVE`
    exactly once."

    Design: Difficulty/non_linear_state_machine/installment_agreement_active_defaulted_active_reinstatement_cycle
    """
    ctx = setup_active_agreement(court_case_number="CV-2026-0307")
    record_misses(ctx["agreement"]["id"], 3)

    reinstated = validate_success(
        api.reinstate_installment_agreement(ctx["agreement"]["id"], CO)
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["missed_count"] == 0
    assert reinstated["reinstatement_count"] == 1

    stored = read_agreement(ctx["agreement"]["id"])
    assert stored["status"] == "ACTIVE"
    assert read_judgment(ctx["judgment"]["id"])["application_order"] == "STATUTORY_ORDER"


# ==========================================================================
# The posture axis cycles while the lifecycle axis never moves
# ==========================================================================
def test_the_posture_climbs_to_enforcing_while_the_status_stays_active(api):
    """PRD §2.10: "A judgment carries two independent state dimensions on the same
    row, and confusing them is the most common modelling mistake in this domain."
    PRD §2.10: "The second is `enforcement_posture`, which starts at `NONE` and
    moves among `NONE`, `LIEN_PERFECTED`, `ENFORCING` and `STAYED` without ever
    terminating while the judgment lives."
    PRD §3.5: "If the `enforcement_posture` was `LIEN_PERFECTED` it moves
    `LIEN_PERFECTED → ENFORCING`, the judgment's `active_enforcement_count` is
    incremented by one, and the judgment's `version` is incremented by one."

    Design: Difficulty/non_linear_state_machine/judgment_posture_cycles_while_status_stays_active
    """
    ctx = setup_perfected_judgment(
        court_case_number="CV-2026-0308",
        debtor_overrides={"weekly_disposable_earnings_cents": 100_000},
        filing_overrides={"fee_cents": 0},
    )
    assert ctx["filing"]["priority_rank"] == 1
    assert ctx["judgment"]["enforcement_posture"] == "LIEN_PERFECTED"
    assert ctx["judgment"]["status"] == "ACTIVE"

    officer = make_enforcement_officer_headers("eo-1")
    finding = create_verified_finding(
        ctx["judgment"]["id"], "inv-1", estimated_value_cents=900_000
    )
    action = draft_enforcement_action(ctx["judgment"]["id"], finding["id"], "BANK_LEVY")
    validate_success(api.request_writ(action["id"], officer))
    validate_success(api.serve_writ(action["id"], "2026-08-01", officer))

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["enforcement_posture"] == "ENFORCING"
    assert judgment["status"] == "ACTIVE"


def test_the_posture_returns_to_enforcing_after_the_stay_ends(api):
    """PRD §2.10: "The posture axis is genuinely cyclic — it moves `ENFORCING` to
    `STAYED` and back to `ENFORCING` as agreements activate and default, and
    `ENFORCING` to `LIEN_PERFECTED` and back to `ENFORCING` as writs conclude and
    new ones are served."
    PRD §2.10: "The first is `status`, the lifecycle axis, which starts at
    `ACTIVE` and ends at either `SATISFIED` or `EXPIRED`; both of those are
    terminal and nothing revives a judgment from them."

    Design: Difficulty/non_linear_state_machine/judgment_posture_cycles_while_status_stays_active
    """
    ctx = setup_stayed_judgment(
        finding_value_cents=900_000,
        court_case_number="CV-2026-0301",
        concession="PRINCIPAL_FIRST",
        debtor_overrides={"weekly_disposable_earnings_cents": 100_000},
        filing_overrides={"fee_cents": 0},
    )
    assert read_judgment(ctx["judgment"]["id"])["enforcement_posture"] == "STAYED"

    record_misses(ctx["agreement"]["id"], 3)

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["enforcement_posture"] == "ENFORCING"
    assert judgment["status"] == "ACTIVE"
    assert read_agreement(ctx["agreement"]["id"])["status"] == "DEFAULTED"
    assert read_action(ctx["action"]["id"])["status"] == "SERVED"


# ==========================================================================
# The settlement floor
# ==========================================================================
def test_a_case_manager_cannot_accept_below_the_settlement_floor(api):
    """PRD §3.7: "The offer's `amount_cents` must be at least its snapshotted
    `min_acceptable_cents`, and a shortfall is `ERR_SETTLEMENT_BELOW_FLOOR` —
    except when the acting role is `ComplianceOfficer`, who alone may take a deal
    below the floor."

    Design: Corner/validations/accepting_below_the_settlement_floor_rejected_for_case_manager
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-4001", interest_rate_bps=0, filing_costs_cents=0
    )
    offer = tender_offer(
        ctx["judgment"]["id"],
        make_debtor_headers(ctx["debtor"]["id"]),
        offered_by="DEBTOR", kind="LUMP_SUM", amount_cents=2_000_000,
    )
    assert offer["min_acceptable_cents"] == 3_000_000

    validate_error(
        api.accept_settlement_offer(offer["id"], CM),
        ApiErrorId.ERR_SETTLEMENT_BELOW_FLOOR.value,
        422,
    )
    assert read_offer(offer["id"])["status"] == "OPEN"

    _rows, meta = validate_paginated(
        api.list_installment_agreements(CM, {"judgment_id": ctx["judgment"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_compliance_officer_alone_may_take_a_deal_below_the_floor(api):
    """PRD §3.7: "The offer's `amount_cents` must be at least its snapshotted
    `min_acceptable_cents`, and a shortfall is `ERR_SETTLEMENT_BELOW_FLOOR` —
    except when the acting role is `ComplianceOfficer`, who alone may take a deal
    below the floor."
    PRD §3.7: "Acceptance moves the offer `OPEN → ACCEPTED`, stamps `decided_at`,
    decrements the judgment's `open_offer_count` by one, and sets off the longest
    cascade in the system."

    Design: Corner/validations/compliance_officer_may_accept_below_the_settlement_floor
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-4002", interest_rate_bps=0, filing_costs_cents=0
    )
    offer = tender_offer(
        ctx["judgment"]["id"],
        make_debtor_headers(ctx["debtor"]["id"]),
        offered_by="DEBTOR", kind="LUMP_SUM", amount_cents=2_000_000,
    )

    accepted = validate_success(api.accept_settlement_offer(offer["id"], CO))
    assert accepted["status"] == "ACCEPTED"

    rows, meta = validate_paginated(
        api.list_installment_agreements(CO, {"judgment_id": ctx["judgment"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "ACTIVE"
    assert rows[0]["total_cents"] == 2_000_000


def test_the_floor_is_frozen_at_tender_and_never_requoted(api):
    """PRD §3.7: "That floor is frozen at creation and never re-quoted; interest
    that accrues between tender and acceptance does not move it."
    PRD §3.7: "`min_acceptable_cents` is the settlement floor: take a payoff
    replay of the judgment as of the current clock date, multiply its
    `total_payoff_cents` by 6,000 basis points — sixty percent — divide by ten
    thousand, and round down to a whole cent."

    Design: Corner/calculations/settlement_floor_is_snapshotted_at_tender_not_requoted_at_acceptance
    """
    ctx = setup_judgment(court_case_number="CV-2026-3005")
    offer = tender_offer(
        ctx["judgment"]["id"],
        make_debtor_headers(ctx["debtor"]["id"]),
        offered_by="DEBTOR", kind="LUMP_SUM",
        amount_cents=3_201_246, expires_at="2028-01-01T00:00:00Z",
    )
    assert offer["min_acceptable_cents"] == 3_201_246

    advance_clock("2027-08-01T00:00:00Z")

    fresh_quote = validate_success(api.get_payoff(ctx["judgment"]["id"], CM))
    assert fresh_quote["total_payoff_cents"] == 5_835_411
    assert read_offer(offer["id"])["min_acceptable_cents"] == 3_201_246

    accepted = validate_success(api.accept_settlement_offer(offer["id"], CM))
    assert accepted["status"] == "ACCEPTED"


def test_the_final_instalment_absorbs_the_rounding_remainder(api):
    """PRD §3.7: "First an installment agreement is created in status `ACTIVE`,
    carrying the accepted offer's `judgment_id` and `settlement_offer_id`, with
    `total_cents` copied from the offer's `amount_cents`, `installment_count`
    copied from the offer, `monthly_cents` equal to `total_cents` divided by
    `installment_count` rounded up to a whole cent, `final_installment_cents`
    equal to `total_cents` less `monthly_cents` multiplied by one fewer than
    `installment_count`, `first_due_on` set to 30 days after the current clock
    date, `application_order_concession` copied from the offer, and
    `paid_to_date_cents`, `missed_count` and `reinstatement_count` all at 0."
    PRD §2.6: "One quantity rounds upward to the nearest whole cent: the monthly
    installment."

    Design: Corner/calculations/installment_schedule_final_payment_absorbs_the_rounding_remainder
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-3004",
        original_principal_cents=4_000_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )
    offer = tender_offer(
        ctx["judgment"]["id"],
        make_debtor_headers(ctx["debtor"]["id"]),
        offered_by="DEBTOR", kind="INSTALLMENT",
        amount_cents=2_500_000, installment_count=7,
    )
    assert offer["min_acceptable_cents"] == 2_400_000
    assert offer["monthly_cents"] == 357_143

    validate_success(api.accept_settlement_offer(offer["id"], CM))

    agreement = agreement_for_offer(offer["id"])
    assert_installment_agreement(agreement)
    assert agreement["monthly_cents"] == 357_143
    assert agreement["final_installment_cents"] == 357_142
    assert agreement["installment_count"] == 7
    assert agreement["total_cents"] == 2_500_000


# ==========================================================================
# Negotiation discipline
# ==========================================================================
def test_a_fifth_round_counter_exhausts_the_negotiation(api):
    """PRD §3.7: "`round_number` is 1 for an opening offer and one more than the
    parent offer's `round_number` for a counter, and a counter whose `round_number`
    would exceed 4 is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` — four
    rounds is the whole negotiation."

    Design: Corner/validations/fifth_negotiation_round_returns_rounds_exhausted
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-4013", interest_rate_bps=0, filing_costs_cents=0
    )
    debtor_headers = make_debtor_headers(ctx["debtor"]["id"])
    judgment_id = ctx["judgment"]["id"]

    round_one = tender_offer(
        judgment_id, CM, offered_by="CREDITOR", amount_cents=4_500_000
    )
    round_two = tender_offer(
        judgment_id, debtor_headers, offered_by="DEBTOR",
        amount_cents=3_100_000, responds_to_offer_id=round_one["id"],
    )
    round_three = tender_offer(
        judgment_id, CM, offered_by="CREDITOR",
        amount_cents=4_200_000, responds_to_offer_id=round_two["id"],
    )
    round_four = tender_offer(
        judgment_id, debtor_headers, offered_by="DEBTOR",
        amount_cents=3_400_000, responds_to_offer_id=round_three["id"],
    )
    assert round_four["round_number"] == 4

    validate_error(
        api.create_settlement_offer(
            create_settlement_offer_payload(
                judgment_id, read_judgment(judgment_id)["version"],
                offered_by="CREDITOR", kind="LUMP_SUM", amount_cents=4_000_000,
                responds_to_offer_id=round_four["id"],
            ),
            CM,
        ),
        ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value,
        409,
    )
    assert read_offer(round_four["id"])["status"] == "OPEN"
    assert read_judgment(judgment_id)["open_offer_count"] == 1


def test_a_counter_from_the_same_side_is_refused(api):
    """PRD §3.7: "Sides must alternate: a counter whose `offered_by` equals the
    `offered_by` of the offer it responds to is refused with
    `ERR_SAME_PARTY_COUNTER`."

    Design: Corner/validations/counter_offer_from_the_same_party_is_rejected
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-4014", interest_rate_bps=0, filing_costs_cents=0
    )
    opening = tender_offer(
        ctx["judgment"]["id"], CM, offered_by="CREDITOR", amount_cents=4_500_000
    )

    validate_error(
        api.create_settlement_offer(
            create_settlement_offer_payload(
                ctx["judgment"]["id"],
                read_judgment(ctx["judgment"]["id"])["version"],
                offered_by="CREDITOR", kind="LUMP_SUM", amount_cents=4_300_000,
                responds_to_offer_id=opening["id"],
            ),
            CM,
        ),
        ApiErrorId.ERR_SAME_PARTY_COUNTER.value,
        409,
    )
    assert read_offer(opening["id"])["status"] == "OPEN"

    _rows, meta = validate_paginated(
        api.list_settlement_offers(CM, {"judgment_id": ctx["judgment"]["id"]})
    )
    assert meta["total_count"] == 1


def test_a_tender_replaying_a_stale_judgment_version_is_rejected(api):
    """PRD §2.7: "**Tendering a settlement offer** — `POST /settlement-offers` —
    must carry `expected_judgment_version` holding the client's last observed
    `version` of the target judgment."
    PRD §2.7: "If `expected_judgment_version` does not equal the judgment's
    current `version`, the request is rejected with `ERR_STALE_JUDGMENT_VERSION`
    and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_judgment_version_on_offer_create_returns_412
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-8001", interest_rate_bps=0, filing_costs_cents=0
    )
    first_seen_version = ctx["judgment"]["version"]

    opening = validate_success(
        api.create_settlement_offer(
            create_settlement_offer_payload(
                ctx["judgment"]["id"], first_seen_version,
                offered_by="CREDITOR", kind="LUMP_SUM", amount_cents=4_500_000,
            ),
            CM,
        ),
        201,
    )

    validate_error(
        api.create_settlement_offer(
            create_settlement_offer_payload(
                ctx["judgment"]["id"], first_seen_version,
                offered_by="DEBTOR", kind="LUMP_SUM", amount_cents=3_200_000,
                responds_to_offer_id=opening["id"],
            ),
            make_debtor_headers(ctx["debtor"]["id"]),
        ),
        ApiErrorId.ERR_STALE_JUDGMENT_VERSION.value,
        412,
    )

    assert read_offer(opening["id"])["status"] == "OPEN"
    assert read_judgment(ctx["judgment"]["id"])["open_offer_count"] == 1
    _rows, meta = validate_paginated(
        api.list_settlement_offers(CM, {"judgment_id": ctx["judgment"]["id"]})
    )
    assert meta["total_count"] == 1


def test_a_second_reinstatement_hits_the_reinstatement_ceiling(api):
    """PRD §3.7: "A `ComplianceOfficer` may reinstate a defaulted agreement, but
    only once: `reinstatement_count` must be strictly less than 1, and a second
    attempt is `ERR_REINSTATEMENT_LIMIT`."

    Design: Corner/validations/second_reinstatement_returns_reinstatement_limit
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-4016", interest_rate_bps=0, filing_costs_cents=0
    )
    offer = tender_offer(
        ctx["judgment"]["id"],
        make_debtor_headers(ctx["debtor"]["id"]),
        offered_by="DEBTOR", kind="INSTALLMENT",
        amount_cents=3_000_000, installment_count=12,
    )
    validate_success(api.accept_settlement_offer(offer["id"], CM))
    agreement = agreement_for_offer(offer["id"])

    record_misses(agreement["id"], 3)
    reinstated = validate_success(
        api.reinstate_installment_agreement(agreement["id"], CO)
    )
    assert reinstated["reinstatement_count"] == 1

    defaulted_again = record_misses(agreement["id"], 3)
    assert defaulted_again["status"] == "DEFAULTED"

    validate_error(
        api.reinstate_installment_agreement(agreement["id"], CO),
        ApiErrorId.ERR_REINSTATEMENT_LIMIT.value,
        409,
    )
    stored = read_agreement(agreement["id"])
    assert stored["status"] == "DEFAULTED"
    assert stored["reinstatement_count"] == 1


def test_the_sweep_kills_an_open_offer_at_its_expiry_instant(api):
    """PRD §2.5: "**Step 3 — stale offers.** Every settlement offer still in
    `OPEN` whose `expires_at` is at or before the new clock instant becomes
    `EXPIRED`."
    PRD §3.7: "And an offer nobody answers dies on the clock: the sweep moves any
    `OPEN` offer whose `expires_at` is at or before the new logical instant along
    `OPEN → EXPIRED`, stamping `decided_at` and decrementing `open_offer_count`."

    Design: Corner/state_machines/clock_sweep_expires_open_settlement_offer_at_its_instant
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-2009", interest_rate_bps=0, filing_costs_cents=0
    )
    offer = tender_offer(
        ctx["judgment"]["id"], CM,
        offered_by="CREDITOR", kind="LUMP_SUM",
        amount_cents=4_000_000, expires_at="2026-09-01T00:00:00Z",
    )
    assert offer["status"] == "OPEN"

    summary = advance_clock("2026-09-01T00:00:00Z")
    assert_sweep_summary_shape(summary)
    assert summary["expired_offer_count"] == 1

    assert read_offer(offer["id"])["status"] == "EXPIRED"
    assert read_judgment(ctx["judgment"]["id"])["open_offer_count"] == 0
