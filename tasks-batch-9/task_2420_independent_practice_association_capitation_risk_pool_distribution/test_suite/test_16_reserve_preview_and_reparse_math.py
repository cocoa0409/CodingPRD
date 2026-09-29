"""The read-only settlement preview, the reserve self-loop, and reparse and void arithmetic.

Every scenario here is built from scratch through the public API because the
harness restarts the server before each test.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLAIMS_EXAMINER_HEADERS,
    IPA_ADMIN_HEADERS,
    IpaApiClient,
    assert_fields,
    assign_enrollee,
    build_approved_claim,
    build_final_scorecard,
    build_posted_file,
    build_reserving_scenario,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_enrollment_file,
    create_physician,
    create_pool,
    credential_physician,
    dispute_file,
    expected_completion_factor_reserve,
    expected_loss_ratio_bps,
    expected_pmpm_loss_ratio_reserve,
    expected_settlement_waterfall,
    append_row,
    list_file_remittances,
    list_pool_distributions,
    make_payer_representative_headers,
    parse_file,
    pay_claim_state,
    propose_settlement,
    read_agreement,
    read_claim,
    read_enrollee,
    read_file,
    read_pool,
    reconcile_file,
    reserve_pool,
    set_clock,
    sole_remittance,
    state_payload,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _preview(api: IpaApiClient, pool_id: str, headers: Json, **params: Any) -> Json:
    """Read the computed settlement projection for a pool."""
    response = api.get_settlement_preview(pool_id, headers, params or None)
    return validate_success(response, 200)


def _list_rows(api: IpaApiClient, file_id: str, **params: Any) -> List[Json]:
    query: Json = {"limit": 20, "offset": 0}
    query.update(params)
    response = api.list_enrollment_file_rows(file_id, IPA_ADMIN_HEADERS, query)
    rows, _meta = validate_paginated(response)
    return rows


def _resubmit_file(api: IpaApiClient, file_id: str, agreement_id: str) -> Json:
    """Take a disputed file back to RECEIVED as the payer."""
    response = api.set_enrollment_file_state(
        file_id,
        state_payload("RECEIVED"),
        make_payer_representative_headers(agreement_id),
    )
    return validate_success(response, 200)


def _void_claim(api: IpaApiClient, claim_id: str) -> Json:
    response = api.set_claim_state(
        claim_id, state_payload("VOIDED"), CLAIMS_EXAMINER_HEADERS
    )
    return validate_success(response, 200)


def _list_claims(api: IpaApiClient, **params: Any) -> List[Json]:
    query: Json = {"limit": 20, "offset": 0}
    query.update(params)
    response = api.list_claims(IPA_ADMIN_HEADERS, query)
    rows, _meta = validate_paginated(response)
    return rows


def _build_mixed_match_file(api: IpaApiClient) -> Json:
    """A parsed three-row file with one MATCHED row and two exception rows.

    One physician is left at ``CREDENTIALED`` so a row naming that physician's
    NPI cannot match, and one row names a member identifier no enrollee of the
    agreement carries.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        payer_name="Corner Match Cascade Health",
        base_pmpm_cents=20000,
        reconciliation_method="ROSTER_SNAPSHOT",
        institutional_pool_share_bps=4000,
        professional_pool_share_bps=6000,
    )
    active = create_active_physician(
        api,
        agreement["id"],
        npi="4200000001",
        full_name="Dr Active Match",
        specialty="PRIMARY_CARE",
    )
    inactive = create_physician(
        api,
        agreement["id"],
        npi="4200000002",
        full_name="Dr Still Credentialing",
        specialty="PRIMARY_CARE",
    )
    # keep the post-credentialing record: the creation response still reads
    # APPLICANT, and the row this physician backs must be an inactive-physician
    # exception rather than an unresolvable NPI.
    inactive = credential_physician(api, inactive["id"])

    enrollee = create_enrollee(
        api,
        agreement["id"],
        external_member_id="C2-0001",
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=10000,
    )
    assign_enrollee(api, enrollee["id"], active["id"])

    enrollment_file = create_enrollment_file(
        api,
        agreement["id"],
        coverage_month="2026-07",
        payer_file_reference="PFR-C2-2026-07",
    )
    append_row(
        api,
        enrollment_file["id"],
        "C2-0001",
        "4200000001",
        row_action="ADD",
        claimed_capitation_cents=20000,
    )
    append_row(
        api,
        enrollment_file["id"],
        "C2-9999",
        "4200000001",
        row_action="ADD",
        claimed_capitation_cents=33333,
    )
    append_row(
        api,
        enrollment_file["id"],
        "C2-0001",
        "4200000002",
        row_action="CHANGE",
        claimed_capitation_cents=44444,
    )
    parse_file(api, enrollment_file["id"])
    return {
        "agreement": agreement,
        "active": active,
        "inactive": inactive,
        "enrollee": enrollee,
        "file": read_file(api, enrollment_file["id"]),
    }


def _build_disputed_file(api: IpaApiClient) -> Json:
    """A one-row July file driven RECEIVED to PARSED to RECONCILED to DISPUTED."""
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        payer_name="Corner Reparse Health",
        base_pmpm_cents=20000,
        reconciliation_method="ROSTER_SNAPSHOT",
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=0,
    )
    physician = create_active_physician(
        api,
        agreement["id"],
        npi="4500000001",
        full_name="Dr Reparse",
        specialty="PRIMARY_CARE",
    )
    enrollee = create_enrollee(
        api,
        agreement["id"],
        external_member_id="C6-0001",
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=10000,
    )
    assign_enrollee(api, enrollee["id"], physician["id"])

    set_clock(api, "2026-08-01T00:00:00Z")
    enrollment_file = create_enrollment_file(
        api,
        agreement["id"],
        coverage_month="2026-07",
        payer_file_reference="PFR-C6-2026-07",
    )
    append_row(
        api,
        enrollment_file["id"],
        "C6-0001",
        "4500000001",
        row_action="ADD",
        claimed_capitation_cents=20000,
    )
    parse_file(api, enrollment_file["id"])
    reconcile_file(api, enrollment_file["id"])
    first_remittance = sole_remittance(api, enrollment_file["id"])
    dispute_file(api, enrollment_file["id"], agreement["id"], "Roster disagreement")
    return {
        "agreement": agreement,
        "physician": physician,
        "enrollee": enrollee,
        "file": read_file(api, enrollment_file["id"]),
        "first_remittance": first_remittance,
    }


def _build_two_approved_claims(api: IpaApiClient) -> Json:
    """A pool funded at 20000 with two approved but unpaid claims of 8000 and 12000."""
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        payer_name="Corner Void Reversal Health",
        base_pmpm_cents=20000,
        reconciliation_method="ROSTER_SNAPSHOT",
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=0,
        stop_loss_attachment_cents=5000000,
    )
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    physician = create_active_physician(
        api,
        agreement["id"],
        npi="4900000001",
        full_name="Dr Void Reversal",
        specialty="PRIMARY_CARE",
    )
    enrollee = create_enrollee(
        api,
        agreement["id"],
        external_member_id="C9-0001",
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=10000,
    )
    assign_enrollee(api, enrollee["id"], physician["id"])

    set_clock(api, "2026-08-01T00:00:00Z")
    build_posted_file(
        api,
        agreement["id"],
        [
            {
                "external_member_id": "C9-0001",
                "physician_npi": "4900000001",
                "claimed_capitation_cents": 20000,
            }
        ],
        coverage_month="2026-07",
    )
    smaller = build_approved_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        8000,
        downstream_provider_name="Cedar Hollow Clinic",
        service_date="2026-07-10T00:00:00Z",
    )
    larger = build_approved_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        12000,
        downstream_provider_name="Cedar Hollow Surgical",
        service_date="2026-07-20T00:00:00Z",
    )
    return {
        "agreement": agreement,
        "pool": read_pool(api, pool["id"]),
        "physician": physician,
        "enrollee": enrollee,
        "smaller": smaller,
        "larger": larger,
    }


# ---------------------------------------------------------------------------
# Instance: settlement_preview_selects_ibnr_variant_from_override_without_mutating_pool
# ---------------------------------------------------------------------------


class TestSettlementPreviewVariantSelection:
    def test_the_override_changes_the_projection_on_identical_stored_data(self, api):
        """PRD §3.7: "The preview accepts an optional `ibnr_method_override` so the effect of the other reserving convention can be inspected, and it returns `gross_claims_cents`, `stop_loss_recovery_cents`, `ibnr_reserve_cents`, `net_claims_cents`, `raw_surplus_cents`, `surplus_ratio_bps`, `surplus_tier`, `admin_fee_bps`, `admin_fee_cents`, `distributable_surplus_cents` and `shared_savings_pool_cents`."

        Design: Corner/calculations/settlement_preview_selects_ibnr_variant_from_override_without_mutating_pool
        """
        built = build_reserving_scenario(api)
        reserve_pool(api, built["pool"]["id"])

        defaulted = _preview(api, built["pool"]["id"], IPA_ADMIN_HEADERS)
        assert_fields(
            defaulted,
            {
                "gross_claims_cents": 13520,
                "stop_loss_recovery_cents": 0,
                "ibnr_reserve_cents": 3380,
                "net_claims_cents": 16900,
                "raw_surplus_cents": 3100,
                "surplus_ratio_bps": 1550,
                "surplus_tier": "TIER_3",
                "admin_fee_bps": 1000,
                "admin_fee_cents": 310,
                "distributable_surplus_cents": 2790,
                "shared_savings_pool_cents": 1674,
            },
        )
        assert defaulted["ibnr_reserve_cents"] == expected_completion_factor_reserve(
            13520, 8000
        )

        overridden = _preview(
            api,
            built["pool"]["id"],
            make_payer_representative_headers(built["agreement"]["id"]),
            ibnr_method_override="PMPM_LOSS_RATIO",
        )
        assert_fields(
            overridden,
            {
                "ibnr_reserve_cents": 1480,
                "net_claims_cents": 15000,
                "raw_surplus_cents": 5000,
                "surplus_ratio_bps": 2500,
                "surplus_tier": "TIER_3",
                "admin_fee_cents": 500,
                "distributable_surplus_cents": 4500,
                "shared_savings_pool_cents": 2700,
            },
        )
        assert overridden["ibnr_reserve_cents"] == expected_pmpm_loss_ratio_reserve(
            13520, 15000, 10000
        )
        # An implementation that ignored the override would answer 3380 twice.
        assert overridden["ibnr_reserve_cents"] != defaulted["ibnr_reserve_cents"]

    def test_neither_preview_writes_anything_through_to_the_pool(self, api):
        """PRD §3.7: "Before committing to a settlement, an `IpaAdmin` or the agreement's `PayerRepresentative` may ask for a settlement preview — a computed, read-only projection that re-runs the settlement waterfall against the pool's current ledger without changing any state, so that the pre-fee tier decision is observable before a proposal is made."

        Design: Corner/calculations/settlement_preview_selects_ibnr_variant_from_override_without_mutating_pool
        """
        built = build_reserving_scenario(api)
        reserved = reserve_pool(api, built["pool"]["id"])

        _preview(api, built["pool"]["id"], IPA_ADMIN_HEADERS)
        _preview(
            api,
            built["pool"]["id"],
            make_payer_representative_headers(built["agreement"]["id"]),
            ibnr_method_override="PMPM_LOSS_RATIO",
        )

        after = read_pool(api, built["pool"]["id"])
        assert_fields(
            after,
            {
                "status": "RESERVED",
                "ibnr_reserve_cents": 3380,
                "ibnr_method_used": "COMPLETION_FACTOR",
                "version": reserved["version"],
            },
        )
        assert after["ibnr_reserve_cents"] == reserved["ibnr_reserve_cents"]
        assert list_pool_distributions(api, built["pool"]["id"]) == []


# ---------------------------------------------------------------------------
# Instance: pool_reserve_self_loop_replaces_ibnr_under_the_other_variant
# ---------------------------------------------------------------------------


class TestReserveSelfLoopReplacesTheReserve:
    def test_the_self_loop_recomputes_the_reserve_under_the_other_variant(self, api):
        """PRD §3.7: "Reserving may be repeated as often as the finance team likes — the pool supports a self-loop from `RESERVED` back to `RESERVED`, permitted when `status` is `RESERVED`, which recomputes `ibnr_method_used` and `ibnr_reserve_cents` in exactly the same way."

        Design: Corner/calculations/pool_reserve_self_loop_replaces_ibnr_under_the_other_variant
        """
        built = build_reserving_scenario(api)

        first = reserve_pool(api, built["pool"]["id"])
        assert_fields(
            first,
            {
                "status": "RESERVED",
                "ibnr_method_used": "COMPLETION_FACTOR",
                "ibnr_reserve_cents": 3380,
            },
        )

        looped = reserve_pool(
            api, built["pool"]["id"], ibnr_method_override="PMPM_LOSS_RATIO"
        )
        assert_fields(
            looped,
            {
                "status": "RESERVED",
                "ibnr_method_used": "PMPM_LOSS_RATIO",
                "ibnr_reserve_cents": 1480,
            },
        )
        assert looped["version"] == first["version"] + 1
        assert first["ibnr_reserve_cents"] - looped["ibnr_reserve_cents"] == 1900

    def test_the_replaced_reserve_moves_the_whole_settlement_waterfall(self, api):
        """PRD §3.7: "Re-reserving the same pool data under the other method genuinely changes the answer, which is the point of the loop."

        Design: Corner/calculations/pool_reserve_self_loop_replaces_ibnr_under_the_other_variant
        """
        built = build_reserving_scenario(api)
        build_final_scorecard(
            api,
            built["physician"]["id"],
            measurement_period="2026",
            hedis_composite_bps=9000,
            access_score_bps=8000,
            patient_experience_bps=7000,
        )
        reserve_pool(api, built["pool"]["id"])
        reserve_pool(api, built["pool"]["id"], ibnr_method_override="PMPM_LOSS_RATIO")

        proposed = propose_settlement(api, built["pool"]["id"])
        expected = expected_settlement_waterfall(20000, 13520, 0, 1480)
        assert_fields(
            proposed,
            {
                "ibnr_reserve_cents": 1480,
                "raw_surplus_cents": 5000,
                "surplus_tier": "TIER_3",
                "admin_fee_cents": 500,
                "distributable_surplus_cents": 4500,
                "shared_savings_pool_cents": 2700,
            },
        )
        # Settling off the first, stale reserve would have produced the
        # 3100/310/1674 triple instead.
        assert proposed["raw_surplus_cents"] != 3100
        assert proposed["admin_fee_cents"] != 310
        assert proposed["shared_savings_pool_cents"] != 1674
        assert proposed["shared_savings_pool_cents"] == expected["shared_savings_pool_cents"]

        distributions = list_pool_distributions(api, built["pool"]["id"])
        assert len(distributions) == 1
        assert_fields(
            distributions[0],
            {
                "physician_id": built["physician"]["id"],
                "withhold_share_cents": 0,
                "shared_savings_cents": 2700,
                "net_distribution_cents": 2700,
                "status": "PROPOSED",
            },
        )


# ---------------------------------------------------------------------------
# Instance: enrollment_file_claimed_capitation_excludes_unmatched_and_exception_rows
# ---------------------------------------------------------------------------


class TestClaimedCapitationCountsMatchedRowsOnly:
    def test_only_matched_rows_contribute_to_the_claimed_total(self, api):
        """PRD §3.5: "And `claimed_capitation_cents` is the sum of `claimed_capitation_cents` over the file's rows whose `match_status` is `MATCHED` and whose `row_action` is `ADD`, `CHANGE` or `TERM`."

        Design: Corner/calculations/enrollment_file_claimed_capitation_excludes_unmatched_and_exception_rows
        """
        built = _build_mixed_match_file(api)
        parsed = built["file"]

        assert_fields(
            parsed,
            {
                "status": "PARSED",
                "row_count": 3,
                "matched_row_count": 1,
                "exception_row_count": 2,
                "claimed_capitation_cents": 20000,
            },
        )
        # None of the totals that would follow from counting an exception row.
        assert parsed["claimed_capitation_cents"] not in (53333, 64444, 97777)
        assert (
            parsed["exception_row_count"]
            == parsed["row_count"] - parsed["matched_row_count"]
        )

    def test_the_match_cascade_labels_the_two_exception_rows_distinctly(self, api):
        """PRD §3.5: "Otherwise, if the physician was found but that physician's `credential_status` is neither `ACTIVE` nor `NOTICE_GIVEN`, it is `EXCEPTION_PHYSICIAN_INACTIVE`."

        Design: Corner/calculations/enrollment_file_claimed_capitation_excludes_unmatched_and_exception_rows
        """
        built = _build_mixed_match_file(api)
        file_id = built["file"]["id"]

        matched = _list_rows(api, file_id, match_status="MATCHED")
        assert len(matched) == 1
        assert matched[0]["external_member_id"] == "C2-0001"
        assert matched[0]["physician_npi"] == "4200000001"
        assert matched[0]["claimed_capitation_cents"] == 20000

        unmatched = _list_rows(api, file_id, match_status="UNMATCHED")
        assert len(unmatched) == 1
        assert unmatched[0]["external_member_id"] == "C2-9999"

        inactive = _list_rows(api, file_id, match_status="EXCEPTION_PHYSICIAN_INACTIVE")
        assert len(inactive) == 1
        assert inactive[0]["external_member_id"] == "C2-0001"
        assert inactive[0]["physician_npi"] == "4200000002"
        assert inactive[0]["row_action"] == "CHANGE"

        assert built["inactive"]["credential_status"] == "CREDENTIALED"
        assert _list_rows(api, file_id, match_status="MATCHED_ENROLLEE_ONLY") == []


# ---------------------------------------------------------------------------
# Instance: enrollment_file_reparse_after_dispute_recomputes_match_status
# ---------------------------------------------------------------------------


class TestReparseAfterDispute:
    def test_resubmission_rewinds_the_counters_and_every_row_match_status(self, api):
        """PRD §3.5: "The file's `status` returns to `RECEIVED`; `matched_row_count`, `exception_row_count` and `claimed_capitation_cents` are all reset to 0; and every row's `match_status` resets to `UNMATCHED` so that a subsequent parse recomputes them from scratch."

        Design: Corner/calculations/enrollment_file_reparse_after_dispute_recomputes_match_status
        """
        built = _build_disputed_file(api)
        file_id = built["file"]["id"]

        resubmitted = _resubmit_file(api, file_id, built["agreement"]["id"])
        assert_fields(
            resubmitted,
            {
                "status": "RECEIVED",
                "row_count": 1,
                "matched_row_count": 0,
                "exception_row_count": 0,
                "claimed_capitation_cents": 0,
            },
        )
        rewound = _list_rows(api, file_id)
        assert len(rewound) == 1
        assert rewound[0]["match_status"] == "UNMATCHED"

        reparsed = parse_file(api, file_id)
        assert_fields(
            reparsed,
            {
                "status": "PARSED",
                "row_count": 1,
                "matched_row_count": 1,
                "exception_row_count": 0,
                "claimed_capitation_cents": 20000,
            },
        )
        assert _list_rows(api, file_id)[0]["match_status"] == "MATCHED"

    def test_the_second_reconciliation_mints_an_entirely_new_remittance(self, api):
        """PRD §3.5: "A file may accumulate several remittances across dispute and resubmit cycles, and each is individually addressable."

        Design: Corner/calculations/enrollment_file_reparse_after_dispute_recomputes_match_status
        """
        built = _build_disputed_file(api)
        file_id = built["file"]["id"]
        first_id = built["first_remittance"]["id"]

        assert read_agreement(api, built["agreement"]["id"])["accrued_capitation_cents"] == 0

        _resubmit_file(api, file_id, built["agreement"]["id"])
        parse_file(api, file_id)
        reconcile_file(api, file_id)

        remittances = list_file_remittances(api, file_id)
        assert len(remittances) == 2
        by_id = {row["id"]: row for row in remittances}
        assert by_id[first_id]["status"] == "DISPUTED"

        fresh = [row for row in remittances if row["id"] != first_id]
        assert len(fresh) == 1
        assert_fields(
            fresh[0],
            {
                "status": "RECONCILED",
                "coverage_month": "2026-07",
                "expected_capitation_cents": 20000,
                "claimed_capitation_cents": 20000,
                "variance_cents": 0,
            },
        )

        agreement = read_agreement(api, built["agreement"]["id"])
        assert agreement["accrued_capitation_cents"] == 20000
        assert agreement["capitation_posture"] == "WITHHELD"


# ---------------------------------------------------------------------------
# Instance: pool_paid_claims_running_total_correct_after_void_reversal
# ---------------------------------------------------------------------------


class TestPaidClaimsRunningTotalAfterVoid:
    def test_each_payment_advances_the_running_total_and_the_loss_ratio(self, api):
        """PRD §3.5: "Otherwise `loss_ratio_bps` is `paid_claims_cents` multiplied by 10000 and divided by `funded_cents`, rounded half up to whole basis points."

        Design: Corner/calculations/pool_paid_claims_running_total_correct_after_void_reversal
        """
        built = _build_two_approved_claims(api)
        pool_id = built["pool"]["id"]

        assert read_pool(api, pool_id)["funded_cents"] == 20000
        assert read_pool(api, pool_id)["paid_claims_cents"] == 0

        pay_claim_state(api, built["smaller"]["id"])
        after_first = read_pool(api, pool_id)
        assert_fields(
            after_first,
            {
                "paid_claims_cents": 8000,
                "loss_ratio_bps": 4000,
                "deficit_flag": False,
                "stop_loss_eligible_enrollee_count": 0,
            },
        )
        assert after_first["loss_ratio_bps"] == expected_loss_ratio_bps(20000, 8000)

        pay_claim_state(api, built["larger"]["id"])
        after_second = read_pool(api, pool_id)
        assert_fields(
            after_second,
            {
                "paid_claims_cents": 20000,
                "loss_ratio_bps": 10000,
                "deficit_flag": True,
            },
        )
        assert after_second["loss_ratio_bps"] == expected_loss_ratio_bps(20000, 20000)
        assert read_enrollee(api, built["enrollee"]["id"])["cumulative_paid_claims_cents"] == 20000
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "UNDER_REVIEW"
        )

    def test_the_void_removes_exactly_what_the_payment_added(self, api):
        """PRD §3.6: "The void removes exactly what the payment added: the pool's `paid_claims_cents` decreases by `paid_cents`, the enrollee's `cumulative_paid_claims_cents` decreases by `paid_cents`, and only then is `paid_cents` itself cleared to null."

        Design: Corner/calculations/pool_paid_claims_running_total_correct_after_void_reversal
        """
        built = _build_two_approved_claims(api)
        pool_id = built["pool"]["id"]

        pay_claim_state(api, built["smaller"]["id"])
        pay_claim_state(api, built["larger"]["id"])
        assert read_pool(api, pool_id)["paid_claims_cents"] == 20000

        voided = _void_claim(api, built["larger"]["id"])
        assert_fields(voided, {"status": "VOIDED", "paid_cents": None})
        assert read_claim(api, built["larger"]["id"])["allowed_cents"] == 12000

        after = read_pool(api, pool_id)
        assert_fields(
            after,
            {
                "paid_claims_cents": 8000,
                "loss_ratio_bps": 4000,
                "deficit_flag": False,
                "stop_loss_eligible_enrollee_count": 0,
            },
        )
        # The running total is the sum over surviving PAID claims, not a
        # difference of gross payments and reversals.
        surviving = _list_claims(api, pool_id=pool_id, status="PAID")
        assert len(surviving) == 1
        assert surviving[0]["id"] == built["smaller"]["id"]
        assert sum(row["paid_cents"] for row in surviving) == after["paid_claims_cents"]

        assert read_enrollee(api, built["enrollee"]["id"])["cumulative_paid_claims_cents"] == 8000
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"] == "CURRENT"
        )
