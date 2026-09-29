"""Rule-by-rule refusals and their boundaries: acceptance gauntlet, uniqueness
scoping, restatement targeting, blackout substitution, windowing holdbacks,
write-off ageing, clock monotonicity and request-shape precedence.

Each test drives the API to the exact state the rule guards, then checks both the
refusal identifier and the absence of any side effect from the refused call.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    accept_report,
    advance_clock,
    create_agreement_payload,
    create_blackout_rule_payload,
    create_mfn_clause_payload,
    create_subscriber_report_payload,
    agreement_version,
    attach_mfn_clause,
    clear_window,
    clock_payload,
    dispute_report,
    draft_agreement,
    draft_invoice,
    fetch_agreement,
    fetch_distributor,
    fetch_invoice,
    fetch_report,
    fetch_title,
    fetch_window,
    file_report,
    issue_invoice,
    make_distributor_liaison_headers,
    plan_window,
    read_clock,
    register_cleared_title,
    register_distributor,
    register_title,
    request_restatement,
    setup_executed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

FLAT_TELCO = {
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
}
FLAT_TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}


def _flat_telco_agreement(**term_overrides):
    """A 200,000-home TELCO operator with one EXECUTED agreement priced at a flat
    40.0000 cents per subscriber across a 2025-01-01 to 2028-12-31 term."""
    terms = dict(FLAT_TERMS)
    terms.update(term_overrides)
    return setup_executed_agreement(dict(FLAT_TELCO), terms)


class TestAcceptanceTermWindow:
    def test_accept_refuses_a_period_after_the_term_ends(self, api, revenue_accountant_headers):
        """PRD §3.4: "Last comes the term test: `period_month` must lie within the
        month of `term_start_date` through the month of `term_end_date` inclusive,
        or the response is `ERR_PERIOD_OUTSIDE_TERM`."
        PRD §3.4: "A new report opens in `SUBMITTED` with `license_fee_due_cents` 0,
        `audit_adjustment_cents` 0, `invoice_id` null, `accepted_at` null and
        `version` 1, and it increments the agreement's `version` by one."

        Design: Corner/validations/accept_rejects_period_outside_the_contract_term
        """
        distributor, agreement = _flat_telco_agreement()
        filed = file_report(
            agreement["id"],
            distributor["id"],
            period_month="2029-01",
            reported_subscribers=130_000,
            reported_tier="BASIC",
        )
        assert filed["status"] == "SUBMITTED", (
            "filing itself carries no term test, got " f"{filed['status']}"
        )
        assert filed["provisional_fee_cents"] == 5_200_000, (
            f"130,000 * 40.0000 * 1.00 is 5,200,000 cents, got {filed['provisional_fee_cents']}"
        )

        response = api.review_subscriber_report(
            filed["id"], {"action": "ACCEPT"}, revenue_accountant_headers
        )
        validate_error(response, ApiErrorId.ERR_PERIOD_OUTSIDE_TERM)

        after = fetch_report(filed["id"])
        assert after["status"] == "SUBMITTED", (
            f"a refused acceptance leaves the report SUBMITTED, got {after['status']}"
        )
        assert after["version"] == 1, (
            f"a refused acceptance is not a mutation, got version {after['version']}"
        )
        assert after["license_fee_due_cents"] == 0, (
            "the final fee was never stamped, got " f"{after['license_fee_due_cents']}"
        )
        assert after["accepted_at"] is None, "accepted_at stays null after a refusal"

        parent = fetch_agreement(agreement["id"])
        assert parent["recognized_revenue_cents"] == 0, (
            f"no revenue was recognised, got {parent['recognized_revenue_cents']}"
        )
        assert parent["penetration_compliance_status"] == "UNKNOWN", (
            "compliance is only evaluated on a successful acceptance, got "
            f"{parent['penetration_compliance_status']}"
        )

    def test_accept_allows_the_final_month_of_the_term(self, api):
        """PRD §3.4: "Last comes the term test: `period_month` must lie within the
        month of `term_start_date` through the month of `term_end_date` inclusive,
        or the response is `ERR_PERIOD_OUTSIDE_TERM`."
        PRD §3.4: "A successful acceptance stamps `billable_subscribers`,
        `rate_applied_cents_per_sub` and `license_fee_due_cents` under the final
        variant, sets `accepted_at` to the current logical instant, and moves the
        report `SUBMITTED → ACCEPTED`."

        Design: Corner/validations/accept_passes_when_period_is_the_final_term_month
        """
        distributor, agreement = _flat_telco_agreement()
        filed = file_report(
            agreement["id"],
            distributor["id"],
            period_month="2028-12",
            reported_subscribers=130_000,
            reported_tier="BASIC",
        )

        accepted = accept_report(filed["id"])
        assert accepted["status"] == "ACCEPTED", (
            "2028-12 is the month of term_end_date and therefore inside the inclusive "
            f"term window, got {accepted['status']}"
        )
        assert accepted["license_fee_due_cents"] == 5_200_000, (
            f"130,000 * 40.0000 * 1.00 is 5,200,000 cents, got {accepted['license_fee_due_cents']}"
        )
        assert accepted["rate_applied_cents_per_sub"] == pytest.approx(40.0000, abs=1e-6), (
            "a zero escalator prices every contract year at the base fee"
        )
        assert accepted["accepted_at"] is not None, "acceptance stamps accepted_at"

        parent = fetch_agreement(agreement["id"])
        assert parent["recognized_revenue_cents"] == 5_200_000, (
            f"the accepted fee is recognised, got {parent['recognized_revenue_cents']}"
        )
        assert parent["penetration_compliance_status"] == "COMPLIANT", (
            "0.6500 penetration clears the 0.50 floor, got "
            f"{parent['penetration_compliance_status']}"
        )


def test_second_accepted_report_for_one_period_is_refused_but_can_still_be_disputed(
    api, revenue_accountant_headers
):
    """PRD §3.4: "Next comes period uniqueness: if any other report for the same
    `agreement_id` and `period_month` already sits in `ACCEPTED` or
    `AUDIT_ADJUSTED`, the acceptance is refused with
    `ERR_DUPLICATE_ACCEPTED_PERIOD`."
    PRD §3.4: "Disputing a report moves it `SUBMITTED → DISPUTED`, and is
    admissible while the owning agreement's `lifecycle_status` is `EXECUTED` or
    `SUSPENDED`."

    Design: Corner/validations/second_accept_for_the_same_period_rejected
    """
    distributor, agreement = _flat_telco_agreement()
    liaison = make_distributor_liaison_headers(distributor["id"])
    winner = file_report(
        agreement["id"],
        headers=liaison,
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    loser = file_report(
        agreement["id"],
        headers=liaison,
        period_month="2026-06",
        reported_subscribers=140_000,
        reported_tier="BASIC",
    )

    accepted = accept_report(winner["id"])
    assert accepted["license_fee_due_cents"] == 5_200_000, (
        f"the first acceptance stands at 5,200,000 cents, got {accepted['license_fee_due_cents']}"
    )

    response = api.review_subscriber_report(
        loser["id"], {"action": "ACCEPT"}, revenue_accountant_headers
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACCEPTED_PERIOD)

    still_open = fetch_report(loser["id"])
    assert still_open["status"] == "SUBMITTED", (
        f"the refused report keeps its SUBMITTED status, got {still_open['status']}"
    )

    parent = fetch_agreement(agreement["id"])
    assert parent["recognized_revenue_cents"] == 5_200_000, (
        "only the winning acceptance recognised revenue, got "
        f"{parent['recognized_revenue_cents']}"
    )
    assert parent["consecutive_compliant_periods"] == 1, (
        "one compliant acceptance, not two, got " f"{parent['consecutive_compliant_periods']}"
    )

    disputed = dispute_report(loser["id"])
    assert disputed["status"] == "DISPUTED", (
        "period uniqueness blocks acceptance only; the dispute path stays open, got "
        f"{disputed['status']}"
    )


def test_restatement_target_must_be_a_restated_report_of_the_same_agreement_and_month(
    api,
):
    """PRD §3.4: "When `restatement_of_report_id` is supplied it must name a report
    of the *same* `agreement_id` and the *same* `period_month` whose `status` is
    `RESTATED`; anything else — a different agreement, a different month, or a
    report in any other status — is refused with `ERR_RESTATEMENT_TARGET_INVALID`."
    PRD §2.8: "Each unresolved reference produces the not-found code of the entity
    type it points at — a bad `content_title_id` or `substitute_content_title_id`
    yields `ERR_TITLE_NOT_FOUND`, a bad `subscriber_report_id` or
    `restatement_of_report_id` yields `ERR_REPORT_NOT_FOUND`, a bad
    `audit_engagement_id` or `engagement_id` yields `ERR_ENGAGEMENT_NOT_FOUND`."

    Design: Corner/validations/restatement_target_must_match_agreement_and_period
    """
    distributor, agreement = _flat_telco_agreement()
    liaison = make_distributor_liaison_headers(distributor["id"])

    original = file_report(
        agreement["id"],
        headers=liaison,
        period_month="2026-05",
        reported_subscribers=120_000,
        reported_tier="BASIC",
    )
    dispute_report(original["id"])
    restated = request_restatement(original["id"])
    assert restated["status"] == "RESTATED", (
        f"the target must be driven to RESTATED first, got {restated['status']}"
    )

    same_month_submitted = file_report(
        agreement["id"],
        headers=liaison,
        period_month="2026-05",
        reported_subscribers=121_000,
        reported_tier="BASIC",
    )
    assert same_month_submitted["status"] == "SUBMITTED", (
        f"a plain refiling opens in SUBMITTED, got {same_month_submitted['status']}"
    )

    wrong_month = api.create_subscriber_report(
        create_subscriber_report_payload(
            agreement["id"],
            agreement_version(agreement["id"]),
            period_month="2026-06",
            reported_subscribers=130_000,
            reported_tier="BASIC",
            restatement_of_report_id=original["id"],
        ),
        liaison,
    )
    validate_error(wrong_month, ApiErrorId.ERR_RESTATEMENT_TARGET_INVALID)

    wrong_status = api.create_subscriber_report(
        create_subscriber_report_payload(
            agreement["id"],
            agreement_version(agreement["id"]),
            period_month="2026-05",
            reported_subscribers=122_000,
            reported_tier="BASIC",
            restatement_of_report_id=same_month_submitted["id"],
        ),
        liaison,
    )
    validate_error(wrong_status, ApiErrorId.ERR_RESTATEMENT_TARGET_INVALID)

    unknown_target = api.create_subscriber_report(
        create_subscriber_report_payload(
            agreement["id"],
            agreement_version(agreement["id"]),
            period_month="2026-05",
            reported_subscribers=123_000,
            reported_tier="BASIC",
            restatement_of_report_id=NON_EXISTENT_UUID,
        ),
        liaison,
    )
    validate_error(unknown_target, ApiErrorId.ERR_REPORT_NOT_FOUND)

    _rows, meta = validate_paginated(
        api.list_subscriber_reports(
            liaison, params={"agreement_id": agreement["id"], "limit": 20}
        )
    )
    assert meta["total_count"] == 2, (
        "only the restated original and the plain refiling were persisted; the three "
        f"refused filings created nothing, got {meta['total_count']}"
    )


def test_contract_code_uniqueness_is_scoped_to_one_operator(api, affiliate_sales_exec_headers):
    """PRD §3.2: "An `AffiliateSalesExec` drafts an agreement by naming the operator
    it binds through `distributor_id`, a `contract_code` that must be unique among
    that operator's agreements (a collision is `ERR_DUPLICATE_CONTRACT_CODE`), the
    `term_start_date` and `term_end_date` bounding the term, a
    `base_license_fee_cents_per_sub` strictly greater than zero representing the
    year-one monthly per-subscriber fee, an `escalator_pct` between 0 and 0.15
    inclusive expressing the annual compounding increase (0.04 meaning four percent
    per contract year), a `penetration_floor_pct` strictly greater than 0 and at
    most 1 giving the minimum share of the operator's subscriber base that must
    receive the network, and a `committed_tier` naming the packaging tier the
    operator has committed to carry the network on."
    PRD §2.3: "Filter query parameters combine conjunctively: supplying both an
    agreement filter and a status filter returns only records satisfying both."

    Design: Corner/validations/contract_code_uniqueness_is_scoped_to_one_distributor
    """
    first_operator = register_distributor()
    second_operator = register_distributor()
    shared_code = "CARR-SCOPE-0001"

    original = draft_agreement(first_operator["id"], contract_code=shared_code)
    assert original["contract_code"] == shared_code

    collision = api.create_agreement(
        create_agreement_payload(first_operator["id"], contract_code=shared_code),
        affiliate_sales_exec_headers,
    )
    validate_error(collision, ApiErrorId.ERR_DUPLICATE_CONTRACT_CODE)

    reused = validate_success(
        api.create_agreement(
            create_agreement_payload(second_operator["id"], contract_code=shared_code),
            affiliate_sales_exec_headers,
        ),
        201,
    )
    assert reused["contract_code"] == shared_code, (
        "the same code is free for a different operator, since uniqueness is scoped "
        "to one operator's agreements"
    )
    assert reused["distributor_id"] == second_operator["id"]

    _rows, first_meta = validate_paginated(
        api.list_agreements(
            affiliate_sales_exec_headers,
            params={"distributor_id": first_operator["id"], "limit": 20},
        )
    )
    assert first_meta["total_count"] == 1, (
        "the collision persisted nothing for the first operator, got "
        f"{first_meta['total_count']}"
    )

    _all_rows, all_meta = validate_paginated(
        api.list_agreements(affiliate_sales_exec_headers, params={"limit": 20})
    )
    assert all_meta["total_count"] == 2, (
        f"two agreements exist in total, got {all_meta['total_count']}"
    )


def test_only_one_active_mfn_clause_may_be_attached_to_an_agreement(
    api, affiliate_sales_exec_headers
):
    """PRD §3.3: "An agreement may hold at most one clause in `ACTIVE` status, and
    attaching a second is refused with `ERR_MULTIPLE_ACTIVE_MFN_CLAUSES`."
    PRD §3.3: "A clause is created with `status` `ACTIVE`, `benchmark_status`
    `NOT_EVALUATED`, and `benchmark_rate_cents`, `benchmark_peer_agreement_id` and
    `last_reset_at` all null; creating it does **not** change the agreement's
    effective rate, because an unevaluated clause has nothing to cap with."
    PRD §3.3: "If there is no `ACTIVE` clause, or the `ACTIVE` clause's
    `benchmark_status` is `NOT_EVALUATED` or `NO_COMPARABLE`, the effective rate
    equals the escalated rate and `mfn_capped` is false."

    Design: Corner/validations/only_one_active_mfn_clause_per_agreement
    """
    _distributor, agreement = _flat_telco_agreement()

    clause = attach_mfn_clause(agreement["id"])
    assert clause["status"] == "ACTIVE", f"a new clause opens ACTIVE, got {clause['status']}"
    assert clause["benchmark_status"] == "NOT_EVALUATED", (
        f"a new clause has evaluated nothing, got {clause['benchmark_status']}"
    )
    assert clause["benchmark_peer_agreement_id"] is None, "no peer has been selected yet"
    assert clause["benchmark_rate_cents"] is None, "no benchmark rate has been computed yet"
    assert clause["last_reset_at"] is None, "the clause has never been reset"

    second = api.create_mfn_clause(
        create_mfn_clause_payload(agreement["id"]), affiliate_sales_exec_headers
    )
    validate_error(second, ApiErrorId.ERR_MULTIPLE_ACTIVE_MFN_CLAUSES)

    _rows, meta = validate_paginated(
        api.list_mfn_clauses(
            affiliate_sales_exec_headers,
            params={"agreement_id": agreement["id"], "limit": 20},
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused attachment persisted nothing, got {meta['total_count']}"
    )

    parent = fetch_agreement(agreement["id"])
    assert parent["mfn_capped"] is False, (
        "an unevaluated clause caps nothing, got mfn_capped " f"{parent['mfn_capped']}"
    )
    assert parent["effective_rate_cents_per_sub"] == pytest.approx(40.0000, abs=1e-6), (
        "the effective rate still equals the escalated rate, got "
        f"{parent['effective_rate_cents_per_sub']}"
    )


def test_substitute_title_is_required_only_while_substitution_is_required(
    api, rights_administrator_headers
):
    """PRD §3.6: "`substitution_required` defaults to true and states whether the
    operator must run substitute programming during the blackout; when it is true,
    `substitute_content_title_id` must be present and must name a title whose
    `rights_status` is `OWNED_CLEARED`, or the rule is refused with
    `ERR_SUBSTITUTION_TITLE_REQUIRED`."
    PRD §3.6: "A new rule opens in `SCHEDULED` with `enforced_at` null and
    `version` 1."

    Design: Corner/validations/substitute_title_required_only_when_substitution_is_required
    """
    _distributor, agreement = _flat_telco_agreement()
    uncleared = register_title()
    assert uncleared["rights_status"] == "PENDING_CLEARANCE", (
        f"a fresh title starts uncleared, got {uncleared['rights_status']}"
    )

    missing = api.create_blackout_rule(
        create_blackout_rule_payload(
            agreement["id"],
            blackout_start="2026-09-05T18:00:00Z",
            blackout_end="2026-09-05T22:00:00Z",
            substitution_required=True,
        ),
        rights_administrator_headers,
    )
    validate_error(missing, ApiErrorId.ERR_SUBSTITUTION_TITLE_REQUIRED)

    uncleared_substitute = api.create_blackout_rule(
        create_blackout_rule_payload(
            agreement["id"],
            blackout_start="2026-09-05T18:00:00Z",
            blackout_end="2026-09-05T22:00:00Z",
            substitution_required=True,
            substitute_content_title_id=uncleared["id"],
        ),
        rights_administrator_headers,
    )
    validate_error(uncleared_substitute, ApiErrorId.ERR_SUBSTITUTION_TITLE_REQUIRED)

    without_substitution = validate_success(
        api.create_blackout_rule(
            create_blackout_rule_payload(
                agreement["id"],
                blackout_start="2026-09-05T18:00:00Z",
                blackout_end="2026-09-05T22:00:00Z",
                substitution_required=False,
            ),
            rights_administrator_headers,
        ),
        201,
    )
    assert without_substitution["substitution_required"] is False
    assert without_substitution["status"] == "SCHEDULED", (
        f"a new rule opens SCHEDULED, got {without_substitution['status']}"
    )
    assert without_substitution["enforced_at"] is None, "enforced_at opens null"
    assert without_substitution["version"] == 1
    assert without_substitution["blackout_hours"] == pytest.approx(4.0, abs=0.01), (
        f"18:00Z to 22:00Z is 4 hours, got {without_substitution['blackout_hours']}"
    )

    _rows, meta = validate_paginated(
        api.list_blackout_rules(
            rights_administrator_headers,
            params={"agreement_id": agreement["id"], "limit": 20},
        )
    )
    assert meta["total_count"] == 1, (
        f"the two refused schedulings persisted nothing, got {meta['total_count']}"
    )


def test_streaming_clearance_needs_seven_whole_days_of_holdback(
    api, rights_administrator_headers
):
    """PRD §3.6: "The holdback test compares the window's `windowing_holdback_days`
    against the minimum for its platform, with an inclusive threshold: `LINEAR`
    requires 0 days, `VOD` requires 1 day, `STREAMING` requires 7 days, and
    `INTERNATIONAL` requires a full 30 days after the linear premiere."
    PRD §3.6: "Clearing a window moves it `PLANNED → CLEARED`, increments the
    title's `cleared_window_count` by one and re-derives
    `distribution_coverage_status`."

    Design: Corner/validations/streaming_window_clear_requires_seven_day_holdback
    """
    _distributor, agreement = _flat_telco_agreement()
    title = register_cleared_title(linear_premiere_at="2026-08-15T00:00:00Z")

    too_soon = plan_window(
        agreement["id"],
        title["id"],
        platform="STREAMING",
        window_start="2026-08-18T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
    )
    assert too_soon["windowing_holdback_days"] == 3, (
        "2026-08-15 to 2026-08-18 is three whole days, got "
        f"{too_soon['windowing_holdback_days']}"
    )
    refused = api.rights_window_lifecycle(
        too_soon["id"], {"action": "CLEAR"}, rights_administrator_headers
    )
    validate_error(refused, ApiErrorId.ERR_HOLDBACK_NOT_SATISFIED)
    assert fetch_window(too_soon["id"])["status"] == "PLANNED", (
        "a refused clearance leaves the window PLANNED"
    )

    on_threshold = plan_window(
        agreement["id"],
        title["id"],
        platform="STREAMING",
        window_start="2026-08-22T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
    )
    assert on_threshold["windowing_holdback_days"] == 7
    cleared_streaming = clear_window(on_threshold["id"])
    assert cleared_streaming["status"] == "CLEARED", (
        "seven days meets the inclusive STREAMING threshold, got "
        f"{cleared_streaming['status']}"
    )

    vod = plan_window(
        agreement["id"],
        title["id"],
        platform="VOD",
        window_start="2026-08-18T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
    )
    assert vod["windowing_holdback_days"] == 3
    cleared_vod = clear_window(vod["id"])
    assert cleared_vod["status"] == "CLEARED", (
        "three days clears the one-day VOD minimum, so the threshold is per platform, "
        f"got {cleared_vod['status']}"
    )

    parent_title = fetch_title(title["id"])
    assert parent_title["cleared_window_count"] == 2, (
        "only the two successful clearances counted, got "
        f"{parent_title['cleared_window_count']}"
    )
    assert parent_title["distribution_coverage_status"] == "MULTIPLATFORM", (
        "the cleared set holds two distinct platforms, got "
        f"{parent_title['distribution_coverage_status']}"
    )


def test_write_off_is_blocked_until_the_invoice_is_one_hundred_twenty_days_old(
    api, revenue_accountant_headers
):
    """PRD §3.8: "An uncollectable invoice can be written off from either `ISSUED` or
    `PARTIALLY_PAID`, but not before it has aged: the current logical instant must
    be at or after 120 days from `issued_at`, and an earlier attempt is refused with
    `ERR_WRITE_OFF_TOO_EARLY`."
    PRD §3.8: "A write-off reduces the operator's `receivable_balance_cents` by the
    uncollected remainder — `net_due_cents` less `paid_cents` — and adjusts
    `audit_recovery_balance_cents` identically for an audit-recovery invoice."
    PRD §3.8: "`WRITTEN_OFF` is terminal."
    PRD §2.8: "An `action` value that is not one of the declared transition names
    for that endpoint is a request-shape failure, `ERR_INVALID_REQUEST`; an `action`
    that is a declared name but is not legal from the entity's current state is a
    state failure with that entity's own invalid-state code."

    Design: Corner/validations/write_off_blocked_until_invoice_is_120_days_old
    """
    distributor, agreement = _flat_telco_agreement()
    report = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=130_000,
        reported_tier="BASIC",
    )
    accept_report(report["id"])
    invoice = draft_invoice(distributor["id"], agreement["id"], "2026-06")
    issued = issue_invoice(invoice["id"])
    assert issued["issued_at"].startswith("2026-08-01T00:00:00"), (
        f"issuance stamps the current logical instant, got {issued['issued_at']}"
    )
    assert issued["net_due_cents"] == 5_200_000, (
        f"the unoffset gross is due, got {issued['net_due_cents']}"
    )

    advance_clock("2026-11-28T00:00:00Z")
    too_early = api.invoice_lifecycle(
        invoice["id"], {"action": "WRITE_OFF"}, revenue_accountant_headers
    )
    validate_error(too_early, ApiErrorId.ERR_WRITE_OFF_TOO_EARLY)
    still_open = fetch_invoice(invoice["id"])
    assert still_open["status"] == "ISSUED", (
        "day 119 is one day short of the 120-day threshold, got "
        f"{still_open['status']}"
    )
    assert still_open["paid_cents"] == 0

    advance_clock("2026-11-29T00:00:00Z")
    written_off = validate_success(
        api.invoice_lifecycle(invoice["id"], {"action": "WRITE_OFF"}, revenue_accountant_headers)
    )
    assert written_off["status"] == "WRITTEN_OFF", (
        "2026-08-01 plus 120 days is 2026-11-29, and the threshold is inclusive, got "
        f"{written_off['status']}"
    )
    assert written_off["paid_cents"] == 0, "a write-off collects nothing"

    operator = fetch_distributor(distributor["id"])
    assert operator["receivable_balance_cents"] == 0, (
        "the whole uncollected remainder left the receivable, got "
        f"{operator['receivable_balance_cents']}"
    )

    after_terminal = api.invoice_lifecycle(
        invoice["id"],
        {"action": "RECORD_PAYMENT", "amount_cents": 1},
        revenue_accountant_headers,
    )
    validate_error(after_terminal, ApiErrorId.ERR_INVALID_INVOICE_STATE)


class TestClockMonotonicity:
    @pytest.mark.parametrize(
        "target,label",
        [
            ("2026-07-31T23:59:59Z", "one second before the startup instant"),
            ("2026-08-01T00:00:00Z", "exactly the startup instant"),
        ],
    )
    def test_clock_refuses_a_target_at_or_before_now(
        self, api, network_admin_headers, target, label
    ):
        """PRD §2.5: "Time may only move forward: a value less than or equal to the
        current logical time is rejected with `ERR_CLOCK_MUST_MOVE_FORWARD` (HTTP
        422)."
        PRD §2.5: "At startup that value is exactly `2026-08-01T00:00:00Z`, and the
        server never falls back to real wall-clock time for any decision: contract
        expiry, window activation, blackout expiry, holdback measurement, interest
        accrual, commitment forfeiture, write-off ageing and renewal-window tests
        all read `current_utc`."

        Design: Corner/validations/clock_must_move_strictly_forward
        """
        response = api.set_clock(clock_payload(target), network_admin_headers)
        validate_error(response, ApiErrorId.ERR_CLOCK_MUST_MOVE_FORWARD)

        clock = read_clock()
        assert clock["current_utc"].startswith("2026-08-01T00:00:00"), (
            f"a refused advance ({label}) leaves the clock where it was, got "
            f"{clock['current_utc']}"
        )
        assert clock["set_count"] == 0, (
            f"a refused advance is not an advance, got set_count {clock['set_count']}"
        )

    def test_clock_accepts_one_second_past_now(self, api, network_admin_headers):
        """PRD §2.5: "Time may only move forward: a value less than or equal to the
        current logical time is rejected with `ERR_CLOCK_MUST_MOVE_FORWARD` (HTTP
        422)."
        PRD §2.5: "A successful advance increments `set_count` by one and then runs
        a single sweep whose step order is pinned and observable:"

        Design: Corner/validations/clock_must_move_strictly_forward
        """
        advanced = validate_success(
            api.set_clock(clock_payload("2026-08-01T00:00:01Z"), network_admin_headers)
        )
        assert advanced["current_utc"].startswith("2026-08-01T00:00:01"), (
            f"one second later is strictly forward, got {advanced['current_utc']}"
        )
        assert advanced["set_count"] == 1, (
            f"the first successful advance sets the counter to 1, got {advanced['set_count']}"
        )


def test_unknown_action_is_a_shape_failure_before_the_path_is_resolved(
    api, revenue_accountant_headers
):
    """PRD §2.8: "An `action` value that is not one of the declared transition names
    for that endpoint is a request-shape failure, `ERR_INVALID_REQUEST`; an `action`
    that is a declared name but is not legal from the entity's current state is a
    state failure with that entity's own invalid-state code."
    PRD §5: "The rejection order among these codes is fixed by §2.8:
    authentication, then role authorisation, then request shape, then
    path-parameter existence, then body-reference existence, then revision guards,
    then segregation of duties and operator scope, then the entity's own state,
    then referenced-entity state, then referential integrity, then temporal rules,
    then fiscal rules."

    Design: Corner/validations/malformed_action_outranks_missing_path_resource
    """
    malformed = api.invoice_lifecycle(
        NON_EXISTENT_UUID, {"action": "SHRED"}, revenue_accountant_headers
    )
    validate_error(malformed, ApiErrorId.ERR_INVALID_REQUEST)

    unresolvable = api.invoice_lifecycle(
        NON_EXISTENT_UUID, {"action": "ISSUE"}, revenue_accountant_headers
    )
    validate_error(unresolvable, ApiErrorId.ERR_INVOICE_NOT_FOUND)
