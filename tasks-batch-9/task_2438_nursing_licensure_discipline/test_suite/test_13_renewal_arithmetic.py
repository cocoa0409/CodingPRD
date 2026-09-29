"""Credit quantisation, audit arithmetic, the fee ladder, and the evidence pool."""
from test_helpers import (
    ANALYST,
    CLOCK_DEFAULT_STAMP,
    ApiClient,
    ApiErrorId,
    assert_decimal_equals,
    assert_privilege_triple,
    assert_quarter_hour_quantised,
    assert_renewal_dimensions,
    ce_record_payload,
    decide_audit,
    determine_privilege,
    finalize_renewal,
    mint_license,
    pay_renewal,
    practice_hour_period,
    record_clean_screening,
    reread_license,
    reread_nurse,
    reread_renewal,
    residency_evidence_entry,
    run_sampling,
    seed_active_license,
    seed_application,
    seed_compact_board,
    seed_docs_requested_renewal,
    seed_licensed_renewal_context,
    seed_nurse,
    seed_program,
    seed_renewal,
    set_clock,
    submit_application,
    submit_audit_docs,
    submit_renewal,
    validate_error,
    validate_paginated,
    validate_success,
    verify_application_qualification,
    verify_ce_record,
    verify_renewal_ce,
)

WINDOW_END = "2028-08-01T00:00:00.000Z"


def test_each_ce_claim_is_quantised_to_a_quarter_hour_on_its_own(api: ApiClient):
    """PRD §3.4: "A successful create freezes the accounting window:
    `period_end_on` is set to the credential's current `expires_on` and is the
    exclusive upper bound of the window, while `period_start_on` is set to
    `period_end_on` walked back by the board's `renewal_period_months` and is the
    inclusive lower bound."

    PRD §3.4: "Every claim is converted to credit on its own, at creation, and
    the conversion is quantised: divide `minutes` by 60 to obtain hours, divide
    that by 0.25, round the result half up to a whole number, and multiply by
    0.25 again."

    PRD §3.4: "The product, carried to two decimal places, is stored as
    `credit_hours` on that record."

    PRD §3.4: "A new claim starts with `verification_status` `UNVERIFIED`;
    analyst staff later set it to `VERIFIED` or `REJECTED`, and each such
    verification advances that record's `version` by one."

    Design: Corner/calculations/ce_credit_hours_quantised_to_a_quarter_hour_round_half_up
    """
    ctx = seed_licensed_renewal_context(api, "DRAFT", 1200, clock=None)
    renewal_id = ctx["renewal_id"]
    assert ctx["renewal"]["period_start_on"] == CLOCK_DEFAULT_STAMP, (
        f"The window opens two years before expiry, got "
        f"{ctx['renewal']['period_start_on']}"
    )
    assert ctx["renewal"]["period_end_on"] == WINDOW_END

    fifty = validate_success(
        api.create_ce_record(
            renewal_id,
            ce_record_payload(provider_code="OHNA-100", category="LIVE_CONTACT",
                              minutes=50, completion_date="2027-03-15T00:00:00Z"),
            ANALYST,
        ),
        201,
    )
    fifty_five = validate_success(
        api.create_ce_record(
            renewal_id,
            ce_record_payload(provider_code="OHNA-100", category="LIVE_CONTACT",
                              minutes=55, completion_date="2027-03-16T00:00:00Z"),
            ANALYST,
        ),
        201,
    )

    assert_decimal_equals(fifty["credit_hours"], 0.75,
                          "credit_hours for 50 claimed minutes")
    assert_decimal_equals(fifty_five["credit_hours"], 1.00,
                          "credit_hours for 55 claimed minutes")
    assert_quarter_hour_quantised(fifty["credit_hours"])
    assert_quarter_hour_quantised(fifty_five["credit_hours"])
    for record in (fifty, fifty_five):
        assert record["verification_status"] == "UNVERIFIED", (
            f"A fresh claim awaits analyst review, got {record['verification_status']}"
        )

    claims, meta = validate_paginated(api.list_renewal_ce_records(renewal_id, ANALYST))
    assert meta["total_count"] == 2, (
        f"Two claims are on file, got {meta['total_count']}"
    )
    assert len(claims) == 2
    assert reread_renewal(api, renewal_id)["ce_credit_hours_provisional"] is None, (
        "The provisional total is only written at submit"
    )


def test_the_audited_total_admits_only_verified_accredited_in_window_claims(
    api: ApiClient,
):
    """PRD §3.4: "Both variants ignore claims whose `verification_status` is
    `REJECTED`."

    PRD §3.4: "The **provisional** total, written to `ce_credit_hours_provisional`
    at submit, admits a claim whose `verification_status` is `UNVERIFIED` or
    `VERIFIED`, does not look at `provider_accredited` at all, and does not check
    the accounting window; it is therefore an upper bound."

    PRD §3.4: "The **audited** total, written to `ce_credit_hours_audited` at
    continuing-education verification, admits a claim only when its
    `verification_status` is `VERIFIED`, its `provider_accredited` is true, and
    its `completion_date` falls inside the half-open accounting window — at or
    after `period_start_on` and strictly before `period_end_on`."

    PRD §3.4: "Whatever it computes is written to `ce_credit_hours_audited`, and
    the result branches the filing dimension: a total at or above the board's
    `ce_hours_required` moves `renewal_status` from `SUBMITTED` to `CE_VERIFIED`,
    while a total below it moves `SUBMITTED` to `CE_DEFICIENT`."

    Design: Corner/calculations/audited_ce_total_excludes_rejected_unaccredited_and_out_of_window_records
    """
    ctx = seed_licensed_renewal_context(api, "DRAFT", 1200, clock=None)
    renewal_id = ctx["renewal_id"]

    def claim(**fields):
        return validate_success(
            api.create_ce_record(renewal_id, ce_record_payload(**fields), ANALYST), 201
        )

    live_in_window = claim(provider_code="OHNA-100", category="LIVE_CONTACT",
                           minutes=1800, completion_date="2027-03-15T00:00:00Z")
    self_study_unreviewed = claim(provider_code="OHNA-101", category="SELF_STUDY",
                                  minutes=360,
                                  completion_date="2027-04-01T00:00:00Z")
    self_study_rejected = claim(provider_code="OHNA-102", category="SELF_STUDY",
                                minutes=120, completion_date="2027-05-01T00:00:00Z")
    unaccredited = claim(provider_code="SHADY-1", provider_accredited=False,
                         category="LIVE_CONTACT", minutes=300,
                         completion_date="2027-06-01T00:00:00Z")
    before_window = claim(provider_code="OHNA-103", category="LIVE_CONTACT",
                          minutes=600, completion_date="2026-07-01T00:00:00Z")

    assert_decimal_equals(live_in_window["credit_hours"], 30.00, "1800 minutes")
    assert_decimal_equals(self_study_unreviewed["credit_hours"], 6.00, "360 minutes")
    pay_renewal(api, renewal_id)
    submitted = submit_renewal(api, renewal_id)
    assert_decimal_equals(
        submitted["ce_credit_hours_provisional"], 53.00,
        "provisional total over five unreviewed claims, self-study 8.00 under cap",
    )

    verify_ce_record(api, live_in_window["id"], "VERIFIED")
    verify_ce_record(api, self_study_rejected["id"], "REJECTED")
    verify_ce_record(api, unaccredited["id"], "VERIFIED")
    verify_ce_record(api, before_window["id"], "VERIFIED")

    audited = verify_renewal_ce(api, renewal_id)

    assert_decimal_equals(audited["ce_credit_hours_audited"], 30.00,
                          "audited total, only the accredited in-window claim")
    assert_renewal_dimensions(audited, "CE_VERIFIED", "NOT_SELECTED")

    rejected, rejected_meta = validate_paginated(
        api.list_renewal_ce_records(renewal_id, ANALYST,
                                    params={"verification_status": "REJECTED"})
    )
    assert rejected_meta["total_count"] == 1
    assert [record["id"] for record in rejected] == [self_study_rejected["id"]]
    unreviewed, unreviewed_meta = validate_paginated(
        api.list_renewal_ce_records(renewal_id, ANALYST,
                                    params={"verification_status": "UNVERIFIED"})
    )
    assert unreviewed_meta["total_count"] == 1
    assert [record["id"] for record in unreviewed] == [self_study_unreviewed["id"]]


def test_a_single_eligible_filing_still_draws_a_quota_of_one(api: ApiClient):
    """PRD §3.5: "The draw size follows the board's `audit_sample_rate_bp` as a
    basis-point rate: multiply `audit_sample_rate_bp` by the eligible count,
    divide by 10000, and round the quotient **up** to the next whole number."

    PRD §3.5: "The quota is therefore at least 1 whenever the eligible pool is
    non-empty and the rate is non-zero — a five-percent rate over three eligible
    filings still draws one."

    PRD §3.5: "It gains 20.00 when the attested hours sit on a thin margin,
    tested by integer cross-multiplication: `attested_practice_hours` multiplied
    by 100 is strictly less than the board's `practice_hours_required` multiplied
    by 110 — that is, the attestation is under one hundred ten percent of the
    requirement."

    PRD §3.5: "When no filing is eligible, the pass still succeeds:
    `eligible_count`, `quota`, and `selected_count` are all 0 and
    `selected_renewal_application_ids` is an empty array."

    Design: Corner/calculations/audit_sampling_quota_uses_the_ceiling_of_the_rate_basis_points
    """
    ctx = seed_licensed_renewal_context(api, "CE_VERIFIED", 1000, clock=None)
    filing = ctx["renewal"]
    assert filing["late_days"] == 0, (
        f"The filing was paid before expiry, got {filing['late_days']}"
    )
    assert filing["fee_applied_cents"] == 12000
    assert filing["renewal_status"] == "CE_VERIFIED"

    draw = run_sampling(api, ctx["board_id"])

    assert draw["eligible_count"] == 1
    assert draw["quota"] == 1, (
        f"500 basis points of one filing rounds up to 1, got {draw['quota']}"
    )
    assert draw["selected_count"] == 1
    assert draw["selected_renewal_application_ids"] == [ctx["renewal_id"]]

    sampled = reread_renewal(api, ctx["renewal_id"])
    assert sampled["audit_status"] == "SELECTED"
    assert_decimal_equals(sampled["audit_risk_score"], 20.00,
                          "risk score from the thin-margin weight alone")

    second_pass = run_sampling(api, ctx["board_id"])
    assert second_pass["eligible_count"] == 0, (
        "The only filing is no longer NOT_SELECTED"
    )
    assert second_pass["quota"] == 0
    assert second_pass["selected_count"] == 0
    assert second_pass["selected_renewal_application_ids"] == []


def test_each_audited_employment_period_is_floored_before_the_periods_are_summed(
    api: ApiClient,
):
    """PRD §3.5: "It moves `audit_status` from `SELECTED` to `DOCS_REQUESTED`, or
    from `DOCS_SUBMITTED` back to `DOCS_REQUESTED` when a submission arrives
    incomplete, and each demand increments `doc_request_cycle_count` and clears
    `practice_hour_periods` back to an empty array — a fresh demand discards
    whatever was submitted before."

    PRD §3.5: "That period's contribution is its `hours` multiplied by the
    overlap days, divided by the period days, and then rounded **down** to a
    whole number of hours."

    PRD §3.5: "The contributions are floored individually and only then summed,
    and the sum is written to `verified_practice_hours`."

    PRD §3.5: "If `verified_practice_hours` is at or above the board's
    `practice_hours_required`, `audit_status` moves from `DOCS_SUBMITTED` to
    `PASSED`; otherwise it moves to `FAILED`."

    Design: Corner/calculations/practice_hour_attainment_floors_each_partial_period_before_summing
    """
    ctx = seed_docs_requested_renewal(api, 1000, clock=None)
    requested = ctx["renewal"]
    assert requested["audit_status"] == "DOCS_REQUESTED"
    assert requested["doc_request_cycle_count"] == 1
    assert requested["practice_hour_periods"] == [], (
        "The demand clears whatever periods were on file"
    )

    periods = [
        practice_hour_period("2026-06-01T00:00:00Z", "2026-09-01T00:00:00Z", 1000,
                             "Mercy General Hospital"),
        practice_hour_period("2028-07-01T00:00:00Z", "2028-10-01T00:00:00Z", 1000,
                             "Saint Luke Medical Center"),
        practice_hour_period("2027-01-01T00:00:00Z", "2027-07-01T00:00:00Z", 300,
                             "Lakeside Clinic"),
    ]
    submitted = submit_audit_docs(api, ctx["renewal_id"], periods)
    assert submitted["audit_status"] == "DOCS_SUBMITTED"
    assert [period["employer_name"] for period in submitted["practice_hour_periods"]] == [
        "Mercy General Hospital", "Saint Luke Medical Center", "Lakeside Clinic"
    ], "The submitted array is stored wholesale, in submission order"
    assert [period["hours"] for period in submitted["practice_hour_periods"]] == \
        [1000, 1000, 300]

    decided = decide_audit(api, ctx["renewal_id"])

    assert decided["verified_practice_hours"] == 972, (
        "Each period is floored on its own — 336 plus 336 plus 300 — so the "
        f"summed-then-floored 973 is wrong; got {decided['verified_practice_hours']}"
    )
    assert decided["audit_status"] == "PASSED", (
        f"972 clears the 960-hour requirement, got {decided['audit_status']}"
    )
    granted = finalize_renewal(api, ctx["renewal_id"], "RENEWED")
    assert granted["renewal_status"] == "RENEWED"


def _credential_with_draft_filing(api: ApiClient, board_id: str, program_id: str,
                                  **nurse_fields):
    """One nurse, one credential expiring 2028-08-01, and one DRAFT renewal
    opened while the clock still stands at issuance."""
    nurse = seed_nurse(api, board_id, **nurse_fields)
    application = seed_application(api, nurse["id"], board_id, program_id)
    submit_application(api, application["id"])
    verify_application_qualification(api, application["id"])
    record_clean_screening(api, application["id"])
    credential = mint_license(api, application["id"])
    filing = seed_renewal(api, credential["id"], clock=None,
                          attested_practice_hours=1200)
    return {
        "nurse_id": nurse["id"],
        "license_id": credential["id"],
        "renewal_id": filing["id"],
    }


def test_the_lateness_surcharge_prices_the_first_day_of_each_band(api: ApiClient):
    """PRD §3.4: "The lateness surcharge then follows four bands: no surcharge at
    all when `late_days` is 0; the board's `late_fee_tier1_cents` when
    `late_days` is 1 through 30 inclusive; the board's `late_fee_tier2_cents`
    when `late_days` is 31 through the board's `renewal_grace_period_days`
    inclusive; and the board's `reinstatement_fee_cents` once `late_days` exceeds
    the grace period."

    PRD §3.4: "`fee_applied_cents` is then set to the board's
    `renewal_base_fee_cents` plus the lateness surcharge plus the failed-audit
    surcharge."

    PRD §3.4: "Any `fee_credit_cents` the nurse is holding is applied first and
    reduced by the portion it satisfies, and the nurse's `fee_paid_total_cents`
    is increased by the full `fee_applied_cents`."

    PRD §3.4: "Assessment is subject to the same renewability gate as creation,
    so an assessment attempt on a credential outside the renewable window is
    refused with `ERR_LICENSE_NOT_RENEWABLE`."

    PRD §3.3: "With the default settings, a credential expires on its
    `expires_on` instant, remains renewable for 60 days of grace, and lapses
    irretrievably 90 days after expiry."

    Design: Corner/calculations/renewal_fee_walks_the_on_time_tier_one_tier_two_and_reinstatement_buckets
    """
    board = seed_compact_board(api)
    program = seed_program(api, board["id"])
    first_band = _credential_with_draft_filing(
        api, board["id"], program["id"],
        full_name="Nurse Tier Zero", birth_year=1988, ssn_last4="1001")
    second_band = _credential_with_draft_filing(
        api, board["id"], program["id"],
        full_name="Nurse Tier Two", birth_year=1989, ssn_last4="1002")
    beyond_grace = _credential_with_draft_filing(
        api, board["id"], program["id"],
        full_name="Nurse Reinstated", birth_year=1990, ssn_last4="1003")

    set_clock(api, "2028-08-02T00:00:00Z")
    day_one = pay_renewal(api, first_band["renewal_id"])
    set_clock(api, "2028-09-01T00:00:00Z")
    day_thirty_one = pay_renewal(api, second_band["renewal_id"])
    set_clock(api, "2028-10-01T00:00:00Z")
    refused = api.pay_renewal_application(beyond_grace["renewal_id"], ANALYST)

    assert day_one["late_days"] == 1
    assert day_one["fee_applied_cents"] == 17000, (
        f"Base 12000 plus the first-tier 5000, got {day_one['fee_applied_cents']}"
    )
    assert day_thirty_one["late_days"] == 31
    assert day_thirty_one["fee_applied_cents"] == 24000, (
        "Day 31 opens the second tier, so base 12000 plus 12000; got "
        f"{day_thirty_one['fee_applied_cents']}"
    )
    validate_error(refused, ApiErrorId.ERR_LICENSE_NOT_RENEWABLE.value)

    for filing, expected in ((day_one, 17000), (day_thirty_one, 24000)):
        assert filing["fee_paid_cents"] == expected, (
            "Assessment and receipt happen in the same act"
        )
    assert reread_nurse(api, first_band["nurse_id"])["fee_paid_total_cents"] == 17000
    assert reread_nurse(api, second_band["nurse_id"])["fee_paid_total_cents"] == 24000
    assert reread_nurse(api, beyond_grace["nurse_id"])["fee_paid_total_cents"] == 0
    for context in (first_band, second_band, beyond_grace):
        nurse = reread_nurse(api, context["nurse_id"])
        assert nurse["fee_credit_cents"] == 0, (
            f"No filing was superseded or denied, got {nurse['fee_credit_cents']}"
        )
        credential = reread_license(api, context["license_id"])
        assert credential["license_status"] == "EXPIRED", (
            "Lapse only fires 90 days after expiry, so at 2028-10-01 the "
            f"credential is still EXPIRED; got {credential['license_status']}"
        )


def test_a_future_dated_residency_document_leaves_the_declared_state_in_force(
    api: ApiClient,
):
    """PRD §3.3: "The candidate pool is every entry of the nurse's
    `residency_evidence` whose `effective_date` is at or before the logical
    clock."

    PRD §3.3: "If the candidate pool is empty — because the array is empty, or
    because every entry's `effective_date` is still in the future — the
    determination falls back to the nurse's `declared_primary_state`."

    PRD §3.3: "The result is written to three fields:
    `multistate_privilege_status`, which is one of `NOT_ELIGIBLE`,
    `SINGLE_STATE`, `MULTISTATE`, or `PRIVILEGE_REVOKED`; `privilege_variant`,
    which records whether `RESIDENCY_DECLARED` or `RESIDENCY_EVIDENCED` was used;
    and `privilege_basis_state`, which records the primary state of residence the
    determination resolved to."

    PRD §3.3: "It returns `license_id`, `credential_type`, `license_status`,
    `encumbrance_status`, `multistate_privilege_status`, `privilege_variant`, and
    `privilege_basis_state` from the credential, alongside the inputs that
    produced them: `board_state_code` and `board_compact_member` from the issuing
    board, and `declared_primary_state` and `evidenced_primary_state` from the
    nurse — the latter being the state the evidence-ranked pool would resolve to
    right now."

    Design: Corner/calculations/privilege_evidence_pool_with_only_future_dated_rows_falls_back_to_declared_state
    """
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-13",
            "program_name": "Maumee BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8700,
        },
        nurse_overrides={
            "full_name": "Iris Calloway",
            "birth_year": 1992,
            "ssn_last4": "3390",
            "declared_primary_state": "OH",
            "residency_evidence": [
                residency_evidence_entry("DRIVER_LICENSE", "MI",
                                         "2030-01-01T00:00:00Z"),
            ],
        },
    )
    assert_privilege_triple(ctx["license"], "MULTISTATE", "RESIDENCY_DECLARED", "OH")

    resolved = determine_privilege(api, ctx["license_id"], "RESIDENCY_EVIDENCED")

    assert_privilege_triple(resolved, "MULTISTATE", "RESIDENCY_EVIDENCED", "OH")
    nurse = reread_nurse(api, ctx["nurse_id"])
    assert len(nurse["residency_evidence"]) == 1, (
        "A determination reads the evidence array and never rewrites it"
    )
    assert nurse["residency_evidence"][0]["state_code"] == "MI"

    summary = validate_success(api.get_privilege_summary(ctx["license_id"], ANALYST))
    assert summary["evidenced_primary_state"] == "OH", (
        "Every document is still future-dated, so the evidenced pool resolves to "
        f"the declared state; got {summary['evidenced_primary_state']}"
    )
    assert summary["declared_primary_state"] == "OH"
    assert summary["board_state_code"] == "OH"
    assert summary["board_compact_member"] is True
