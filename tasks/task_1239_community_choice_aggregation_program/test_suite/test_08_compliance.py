"""Compliance filings: the two-key chain, the cyclic revision loop, the
zero-REC gate, terminal lockdown, and RPS attainment math."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_compliance_filing,
    attach_rec,
    create_account_spec,
    create_executed_contract,
    create_filing,
    create_filing_with_rec,
    file_filing,
    get_filing,
    make_compliance_officer_headers,
    prepare_filing,
    review_filing,
    setup_accepted_extract,
    setup_active_authority,
    setup_enrolled_accounts,
    setup_prepared_filing,
    setup_settled_extract,
    validate_error,
    validate_success,
)

CO = TEST_USERS["compliance_officer_headers"]
BD = TEST_USERS["board_director_headers"]
UL = TEST_USERS["utility_liaison_headers"]


def test_filing_revision_loop_reaches_accepted(api):
    """PRD §3.9: "The filing lifecycle is a two-key approval chain with a cyclic revision loop: `DRAFT → PREPARED → REVIEWED → FILED → ACCEPTED_BY_CPUC`, with `REJECTED_BY_CPUC` looping back to `DRAFT` and `WITHDRAWN` as a terminal exit off `DRAFT`."
    PRD §3.9: "A rejection is not the end: revising a rejected filing returns it to `DRAFT`, increments its `revision_count` by 1, and clears both `prepared_by` and `reviewed_by` so the new cycle requires a fresh two-key chain."

    Design: Difficulty/non_linear_state_machine/compliance_filing_revision_loop
    """
    setup_active_authority()
    filing, _rec, _contract = create_filing_with_rec(retirement_serial="WREGIS-0001")

    prepare_filing(filing["id"], "officer-ann")
    review_filing(filing["id"], "officer-bob")
    file_filing(filing["id"])
    validate_success(api.cpuc_reject_filing(filing["id"], {}, UL), 200)
    validate_success(api.revise_compliance_filing(filing["id"], {}, CO), 200)

    # Second pass through the full two-key chain.
    prepare_filing(filing["id"], "officer-ann")
    review_filing(filing["id"], "officer-bob")
    file_filing(filing["id"])
    accepted = validate_success(api.cpuc_accept_filing(filing["id"], {}, UL), 200)

    assert_compliance_filing(accepted)
    assert accepted["status"] == "ACCEPTED_BY_CPUC"
    assert accepted["revision_count"] == 1, (
        "exactly one REJECTED_BY_CPUC -> DRAFT cycle accumulated"
    )


def test_revise_clears_two_key_chain(api):
    """PRD §3.9: "A rejection is not the end: revising a rejected filing returns it to `DRAFT`, increments its `revision_count` by 1, and clears both `prepared_by` and `reviewed_by` so the new cycle requires a fresh two-key chain."

    Design: Difficulty/non_linear_state_machine/compliance_filing_revision_loop
    """
    setup_active_authority()
    filing, _rec, _contract = create_filing_with_rec(retirement_serial="WREGIS-0001")

    prepare_filing(filing["id"], "officer-ann")
    review_filing(filing["id"], "officer-bob")
    file_filing(filing["id"])
    validate_success(api.cpuc_reject_filing(filing["id"], {}, UL), 200)

    revised = validate_success(api.revise_compliance_filing(filing["id"], {}, CO), 200)
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert revised.get("prepared_by") is None, "prepared_by cleared for the new cycle"
    assert revised.get("reviewed_by") is None, "reviewed_by cleared for the new cycle"

    # The fresh chain runs again with two distinct officers.
    reprepared = prepare_filing(filing["id"], "officer-ann")
    assert reprepared["prepared_by"] == "officer-ann"
    reviewed = review_filing(filing["id"], "officer-bob")
    assert reviewed["status"] == "REVIEWED"
    assert reviewed["reviewed_by"] == "officer-bob"


def test_review_same_officer_rejected_sod(api):
    """PRD §3.9: "Review is a second `ComplianceOfficer` act, segregated from the first — the reviewer's id must differ from `prepared_by`, or `ERR_SEGREGATION_OF_DUTIES` — and stamps `reviewed_by`."

    Design: Difficulty/priority_pair_validation_conflict/safety_sod_vs_referential_on_rec_review
    """
    setup_active_authority()
    filing = setup_prepared_filing(officer_id="officer-ann",
                                   retirement_serial="WREGIS-0002")
    assert filing["status"] == "PREPARED"
    assert filing["prepared_by"] == "officer-ann"

    res = api.review_compliance_filing(
        filing["id"], {}, make_compliance_officer_headers("officer-ann")
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    after = get_filing(filing["id"])
    assert after["status"] == "PREPARED"
    assert after.get("reviewed_by") is None


def test_review_distinct_officer_succeeds(api):
    """PRD §3.9: "Review is a second `ComplianceOfficer` act, segregated from the first — the reviewer's id must differ from `prepared_by`, or `ERR_SEGREGATION_OF_DUTIES` — and stamps `reviewed_by`."

    Design: Difficulty/priority_pair_validation_conflict/safety_sod_vs_referential_on_rec_review
    """
    setup_active_authority()
    filing = setup_prepared_filing(officer_id="officer-ann",
                                   retirement_serial="WREGIS-0002")

    reviewed = validate_success(
        api.review_compliance_filing(
            filing["id"], {}, make_compliance_officer_headers("officer-bob")
        ),
        200,
    )
    assert reviewed["status"] == "REVIEWED"
    assert reviewed["reviewed_by"] == "officer-bob"
    assert reviewed["prepared_by"] == "officer-ann"


def test_prepare_zero_rec_rejected(api):
    """PRD §3.9: "For an `RPS_ANNUAL` filing, preparation is gated on substance: at least one REC retirement must already reference the filing, or the prepare is rejected with `ERR_ZERO_REC_CLAIM` — zero-REC claims are not preparable."

    Design: Difficulty/boundary_precision_check/zero_rec_claim_prepare_rejected
    """
    setup_active_authority()
    filing = create_filing(filing_type="RPS_ANNUAL", compliance_year=2026)

    res = api.prepare_compliance_filing(filing["id"], {}, CO)
    validate_error(res, ApiErrorId.ERR_ZERO_REC_CLAIM)

    assert get_filing(filing["id"])["status"] == "DRAFT"


def test_prepare_with_one_rec_succeeds(api):
    """PRD §3.9: "For an `RPS_ANNUAL` filing, preparation is gated on substance: at least one REC retirement must already reference the filing, or the prepare is rejected with `ERR_ZERO_REC_CLAIM` — zero-REC claims are not preparable."
    PRD §3.9: "The `rps_actual_pct` is the eligible energy divided by retail energy, rounded half up to four decimal places, and is 0 when retail energy is 0."

    Design: Difficulty/boundary_precision_check/zero_rec_claim_prepare_rejected
    """
    setup_active_authority()
    filing, _rec, _contract = create_filing_with_rec(
        compliance_year=2027, retired_mwh=100, retirement_serial="WREGIS-0003"
    )

    prepared = prepare_filing(filing["id"], "officer-ann")
    assert prepared["status"] == "PREPARED", (
        "exactly one attached retirement admits the prepare (count boundary 1)"
    )
    # No settled billing lines exist for 2027, so retail energy is zero.
    assert prepared["rps_actual_pct"] == 0
    assert prepared["rps_shortfall_mwh"] == 0


def test_file_skipping_review_invalid_state(api):
    """PRD §2.9: "5. **State-machine legality** — if the target's state machine has no transition for this trigger from its current state, the request yields `ERR_INVALID_STATE`."
    PRD §3.9: "The filing lifecycle is a two-key approval chain with a cyclic revision loop: `DRAFT → PREPARED → REVIEWED → FILED → ACCEPTED_BY_CPUC`, with `REJECTED_BY_CPUC` looping back to `DRAFT` and `WITHDRAWN` as a terminal exit off `DRAFT`."

    Design: Corner/state_machines/invalid_transition_skip_review_to_file
    """
    setup_active_authority()
    filing = setup_prepared_filing(officer_id="officer-ann",
                                   retirement_serial="WREGIS-9001")

    res = api.file_compliance_filing(filing["id"], {}, BD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    assert get_filing(filing["id"])["status"] == "PREPARED", (
        "PREPARED -> FILED is not a declared transition; the filing stays put"
    )


def test_cpuc_reject_after_accept_already_terminal(api):
    """PRD §2.9: "6. **Terminal lockdown** — triggers fired against a terminal-state resource (a `SETTLED` extract or remittance, a `TRUED_UP` pool, an `ACCEPTED_BY_CPUC` filing) yield `ERR_ALREADY_TERMINAL`, an audit-distinct code kept separate from `ERR_INVALID_STATE` so closed books are visibly closed."

    Design: Corner/errors/error_already_terminal_on_accepted_filing
    """
    setup_active_authority()
    filing, _rec, _contract = create_filing_with_rec(retirement_serial="WREGIS-9301")
    prepare_filing(filing["id"], "officer-ann")
    review_filing(filing["id"], "officer-bob")
    file_filing(filing["id"])
    accepted = validate_success(api.cpuc_accept_filing(filing["id"], {}, UL), 200)
    assert accepted["status"] == "ACCEPTED_BY_CPUC"

    res = api.cpuc_reject_filing(filing["id"], {}, UL)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)

    after = get_filing(filing["id"])
    assert after["status"] == "ACCEPTED_BY_CPUC"
    assert after["revision_count"] == 0


def test_renewable_attainment_shortfall_and_cap(api):
    """PRD §3.9: "The RPS-eligible energy is the smaller of the retired total and the attribute-weighted sum across the referenced contracts — each retirement's `retired_mwh` multiplied by its contract's `rps_eligible_pct`. The `rps_actual_pct` is the eligible energy divided by retail energy, rounded half up to four decimal places, and is 0 when retail energy is 0. The `rps_shortfall_mwh` is the amount by which the target — the authority's `rps_target_pct` times retail energy — exceeds the eligible energy, never below zero, rounded up to whole MWh."
    PRD §3.9: "Retail energy served is the sum of `usage_kwh` over every billing line whose parent extract is `SETTLED` and whose billing month falls inside the compliance year, converted kWh to MWh."

    Design: Corner/calculations/renewable_attainment_shortfall_and_cap
    """
    setup_active_authority(rps_target_pct=0.60)
    enrolled = setup_enrolled_accounts(
        specs=[
            create_account_spec(
                utility_account_number="U-6201",
                service_class="SMALL_COMMERCIAL",
                annual_kwh_estimate=1000000,
                annual_peak_kw=40.0,
            )
        ],
        target_service_classes=("SMALL_COMMERCIAL",),
    )
    account_id = enrolled["account_ids"][0]

    # 1,000,000 kWh = 1000 MWh of retail energy in a SETTLED 2026 extract.
    setup_settled_extract("2026-05", [(account_id, 1000000)])

    ppa = create_executed_contract(
        counterparty="Solaris Energy LLC", contract_type="PPA", rps_eligible_pct=1.0
    )
    rec_only = create_executed_contract(
        counterparty="GreenCert Traders",
        contract_type="REC_ONLY",
        capacity_mw=1.0,
        total_mwh=5000,
        price_dollars_per_mwh=2.0,
        rps_eligible_pct=0.5,
    )
    filing = create_filing(filing_type="RPS_ANNUAL", compliance_year=2026)
    attach_rec(filing["id"], ppa["id"], retired_mwh=500,
               retirement_serial="WREGIS-9101")
    attach_rec(filing["id"], rec_only["id"], retired_mwh=200,
               retirement_serial="WREGIS-9102")

    prepared = prepare_filing(filing["id"], "officer-ann")
    # eligible = min(500 + 200, 500*1.0 + 200*0.5) = min(700, 600) = 600 MWh
    # rps_actual_pct = 600 / 1000 = 0.6000; target 0.60 * 1000 = 600 -> shortfall 0
    assert prepared["rps_actual_pct"] == pytest.approx(0.6, abs=1e-9)
    assert prepared["rps_shortfall_mwh"] == 0
