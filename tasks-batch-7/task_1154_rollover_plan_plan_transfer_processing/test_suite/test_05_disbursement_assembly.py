"""Disbursement assembly: source allocation, withholding evaluation order,
verification and segregation-of-duties gates, and assembly idempotency."""
from test_helpers import (
    ApiErrorId,
    api_client,
    build_approved_direct_case,
    build_approved_indirect_case,
    complete_verification,
    get_case,
    open_verification,
    make_processor_headers,
    source_rows_by_type,
    validate_error,
    validate_success,
)

PROC2 = make_processor_headers("proc-2")


def _assemble(case_id, method="ACH", mover=PROC2):
    return api_client.assemble_disbursement(case_id, {"method": method}, mover)


def test_partial_allocation_per_source_largest_remainder(api):
    """PRD §3.6: "Each source's allocation is the floor of its raw share; the
    leftover cents — the gross minus the sum of the floors — are handed out one
    cent each to the sources with the largest fractional parts, ties broken by
    the pinned source-type order `AFTER_TAX`, then `EMPLOYER_PRETAX`, then
    `PRE_TAX`, then `ROTH`."
    PRD §3.6: "Assembly then creates a **Disbursement** in `PENDING` status
    carrying a snapshot trio — `gross_cents`, `withholding_cents`, and
    `net_cents` — for which the invariant `gross_cents` equals
    `withholding_cents` plus `net_cents` always holds, and debits each
    money-source row of the source account by its allocated amount, with
    account totals recomputing."

    Design: Difficulty/combinatorial_formula/partial_distribution_largest_remainder_rounding
    """
    bundle = build_approved_indirect_case(
        requested_amount_cents=1000000, clock="2026-05-01T00:00:00Z"
    )
    resp = _assemble(bundle["case"]["id"])
    validate_success(resp)
    rows = source_rows_by_type(bundle["account"]["id"])
    # Floor shares over vested 10,800,000: 740,740 / 111,111 / 92,592 / 55,555
    # (sum 999,998); the 2 leftover cents go to the largest fractional parts
    # (PRE_TAX .7407, ROTH .5926).
    assert rows["PRE_TAX"]["balance_cents"] == 8000000 - 740741
    assert rows["EMPLOYER_PRETAX"]["balance_cents"] == 2000000 - 111111
    assert rows["ROTH"]["balance_cents"] == 1000000 - 92593
    assert rows["AFTER_TAX"]["balance_cents"] == 600000 - 55555
    debited = 740741 + 111111 + 92593 + 55555
    assert debited == 1000000, f"allocation must sum to the gross exactly, got {debited}"
    # Basis travels pro-rata, rounded half-up per source:
    # ROTH round(92593 * 800000/1000000) = 74074; AFTER_TAX round(55555 * 500000/600000) = 46296.
    assert rows["ROTH"]["basis_cents"] == 800000 - 74074
    assert rows["AFTER_TAX"]["basis_cents"] == 500000 - 46296


def test_partial_allocation_case_amounts_and_snapshot(api):
    """PRD §3.6: "Basis travels pro-rata with each allocation: each source's
    basis share is its allocated cents times its row's `basis_cents` divided by
    its row's `balance_cents`, rounded half-up to a whole cent (zero when the
    row's balance is zero). The pinned order matters: floor-then-remainder per
    source first, and only then per-source basis rounding. The case locks
    `gross_cents` as the gross, `basis_portion_cents` as the sum of the basis
    shares, and `taxable_cents` as the gross minus the basis portion."
    PRD §3.6: "For an `INDIRECT_ROLLOVER_OUT`, withholding is mandatory and
    cannot be waived or reduced: `withholding_cents` is 20 percent of
    `taxable_cents`, rounded half-up to a whole cent."

    Design: Difficulty/combinatorial_formula/partial_distribution_largest_remainder_rounding
    """
    bundle = build_approved_indirect_case(
        requested_amount_cents=1000000, clock="2026-05-01T00:00:00Z"
    )
    resp = _assemble(bundle["case"]["id"])
    disb = validate_success(resp)
    assert disb["gross_cents"] == 1000000
    assert disb["withholding_cents"] == 175926
    assert disb["net_cents"] == 824074
    assert disb["gross_cents"] == disb["withholding_cents"] + disb["net_cents"]

    case = get_case(bundle["case"]["id"])
    assert case["basis_portion_cents"] == 120370, (
        f"basis portion must be 120370, got {case['basis_portion_cents']}"
    )
    assert case["taxable_cents"] == 879630, (
        f"taxable must be 879630, got {case['taxable_cents']}"
    )
    # withholding = round_half_up(879630 * 0.20) = 175926.
    assert case["withholding_cents"] == 175926
    assert case["net_cents"] == 824074


def test_full_vested_evaluation_order_case_amounts(api):
    """PRD §3.6: "gross first, then basis portion, then taxable as gross minus
    basis, then withholding, then net as gross minus withholding. Net never
    feeds back into taxable — taxable depends only on gross and basis."
    PRD §3.6: "The gross is then the elected `requested_amount_cents` when
    present — a *partial* election — or, when null, the *full vested* sum of all
    rows' vested cents."

    Design: Difficulty/combinatorial_formula/gross_up_evaluation_order
    """
    bundle = build_approved_indirect_case(clock="2026-06-01T00:00:00Z")  # full vested
    validate_success(_assemble(bundle["case"]["id"], method="WIRE"))
    case = get_case(bundle["case"]["id"])
    assert case["gross_cents"] == 10800000, f"gross {case['gross_cents']}"
    assert case["basis_portion_cents"] == 1300000, f"basis {case['basis_portion_cents']}"
    assert case["taxable_cents"] == 9500000, (
        f"taxable depends only on gross and basis: {case['taxable_cents']}"
    )
    assert case["withholding_cents"] == 1900000, (
        f"withholding = round_half_up(9500000 * 0.20): {case['withholding_cents']}"
    )
    assert case["net_cents"] == 8900000, f"net = gross - withholding: {case['net_cents']}"


def test_full_vested_snapshot_and_forfeiture(api):
    """PRD §3.6: "A *full-vested* election additionally forfeits the unvested
    employer remainder: `forfeiture_cents` is set to the unvested portion of the
    `EMPLOYER_PRETAX` rows (balance minus vested for those rows) and the
    unvested employer balance is zeroed."
    PRD §3.6: "Assembly then creates a **Disbursement** in `PENDING` status
    carrying a snapshot trio — `gross_cents`, `withholding_cents`, and
    `net_cents` — for which the invariant `gross_cents` equals
    `withholding_cents` plus `net_cents` always holds"

    Design: Difficulty/combinatorial_formula/gross_up_evaluation_order
    """
    bundle = build_approved_indirect_case(clock="2026-06-01T00:00:00Z")
    resp = _assemble(bundle["case"]["id"], method="WIRE")
    disb = validate_success(resp)
    assert (disb["gross_cents"], disb["withholding_cents"], disb["net_cents"]) == (
        10800000,
        1900000,
        8900000,
    ), f"disbursement snapshot must mirror the locked case amounts, got {disb}"

    case = get_case(bundle["case"]["id"])
    # Unvested employer remainder: 2,000,000 - 1,200,000 = 800,000.
    assert case["forfeiture_cents"] == 800000, (
        f"unvested employer remainder forfeited must be 800000, got {case['forfeiture_cents']}"
    )
    rows = source_rows_by_type(bundle["account"]["id"])
    assert rows["EMPLOYER_PRETAX"]["balance_cents"] == 0, (
        "unvested employer balance must be zeroed on a full-vested election"
    )


def test_withholding_zero_when_fully_basis_amounts(api):
    """PRD §3.6: "The case locks `gross_cents` as the gross,
    `basis_portion_cents` as the sum of the basis shares, and `taxable_cents` as
    the gross minus the basis portion."
    PRD §3.6: "For an `INDIRECT_ROLLOVER_OUT`, withholding is mandatory and
    cannot be waived or reduced: `withholding_cents` is 20 percent of
    `taxable_cents`, rounded half-up to a whole cent."

    Design: Difficulty/boundary_precision_check/withholding_zero_when_fully_basis
    """
    bundle = build_approved_indirect_case(
        balances=[{"source_type": "AFTER_TAX", "balance_cents": 600000,
                   "basis_cents": 600000, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    resp = _assemble(bundle["case"]["id"])
    disb = validate_success(resp)
    assert disb["gross_cents"] == 600000
    case = get_case(bundle["case"]["id"])
    assert case["basis_portion_cents"] == 600000, "basis covers the gross entirely"
    assert case["taxable_cents"] == 0, f"taxable must be 0, got {case['taxable_cents']}"
    # 20% of zero is exactly zero — never negative, never fractional.
    assert case["withholding_cents"] == 0, (
        f"withholding on zero taxable must be exactly 0, got {case['withholding_cents']}"
    )


def test_withholding_zero_when_fully_basis_net_equals_gross(api):
    """PRD §3.6: "The case locks `withholding_cents` and `net_cents` (gross
    minus withholding)."
    PRD §3.6: "for which the invariant `gross_cents` equals `withholding_cents`
    plus `net_cents` always holds"

    Design: Difficulty/boundary_precision_check/withholding_zero_when_fully_basis
    """
    bundle = build_approved_indirect_case(
        balances=[{"source_type": "AFTER_TAX", "balance_cents": 600000,
                   "basis_cents": 600000, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    resp = _assemble(bundle["case"]["id"])
    disb = validate_success(resp)
    assert disb["net_cents"] == 600000 == disb["gross_cents"], (
        f"net must equal gross when withholding collapses to zero: {disb}"
    )
    assert disb["gross_cents"] == disb["withholding_cents"] + disb["net_cents"]


def test_allocation_excludes_zero_balance_sources(api):
    """PRD §3.6: "The eligible source set is the rows with a positive
    `balance_cents` — all four source types for outbound cases."
    PRD §3.6: "Each source's raw share is the exact rational value gross times
    that source's vested cents, divided by the total vested cents."

    Design: Corner/calculations/allocation_excludes_zero_balance_sources
    """
    bundle = build_approved_indirect_case(
        balances=[
            {"source_type": "PRE_TAX", "balance_cents": 0, "basis_cents": 0, "vested_pct": 100},
            {"source_type": "ROTH", "balance_cents": 1000000, "basis_cents": 800000, "vested_pct": 100},
            {"source_type": "AFTER_TAX", "balance_cents": 600000, "basis_cents": 500000, "vested_pct": 100},
        ],
        requested_amount_cents=800000,
        clock="2026-06-01T00:00:00Z",
    )
    resp = _assemble(bundle["case"]["id"])
    disb = validate_success(resp)
    # Vested pool is 1,600,000 (zero-balance PRE_TAX excluded): exact shares
    # ROTH 500,000 and AFTER_TAX 300,000 with no remainder.
    rows = source_rows_by_type(bundle["account"]["id"])
    assert rows["PRE_TAX"]["balance_cents"] == 0, "zero-balance source must be untouched"
    assert rows["ROTH"]["balance_cents"] == 500000
    assert rows["AFTER_TAX"]["balance_cents"] == 300000

    case = get_case(bundle["case"]["id"])
    assert case["basis_portion_cents"] == 650000  # 400,000 (ROTH) + 250,000 (AFTER_TAX)
    assert case["taxable_cents"] == 150000
    assert disb["gross_cents"] == 800000
    assert disb["withholding_cents"] == 30000
    assert disb["net_cents"] == 770000


def test_issue_disbursement_returns_disbursement_resource(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §3.6: "Assembly then creates a **Disbursement** in `PENDING` status
    carrying a snapshot trio — `gross_cents`, `withholding_cents`, and
    `net_cents`"

    Design: Corner/endpoints/issue_disbursement_returns_disbursement_resource
    """
    bundle = build_approved_indirect_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    resp = _assemble(bundle["case"]["id"])
    body = resp.json()
    assert body["response_type"] == "object", f"single-resource envelope, got {body['response_type']}"
    assert "api_request_id" in body["meta"] and "api_request_timestamp" in body["meta"]
    disb = validate_success(resp)
    assert disb["status"] == "PENDING"
    assert disb["method"] == "ACH"
    assert disb["gross_cents"] == 500000


def test_second_disbursement_assembly_rejected(api):
    """PRD §3.6: "no non-`CANCELLED` disbursement may already exist for the case
    (else `ERR_DISBURSEMENT_ALREADY_EXISTS`)"
    PRD §3.7: "a disbursement in `PENDING` or `RETURNED` may be cancelled,
    transitioning to the terminal `CANCELLED` status with full compensation"

    Design: Corner/endpoints/second_disbursement_assembly_rejected
    """
    bundle = build_approved_indirect_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    case_id = bundle["case"]["id"]
    first = validate_success(_assemble(case_id))

    resp = _assemble(case_id, method="WIRE")
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_ALREADY_EXISTS, expected_status=409)

    validate_success(api_client.cancel_disbursement(first["id"], PROC2))
    second = validate_success(_assemble(case_id, method="WIRE"))
    assert second["status"] == "PENDING"
    assert second["id"] != first["id"], "re-assembly after cancellation mints a new disbursement"


def test_sod_same_processor_cannot_issue_own_approval(api):
    """PRD §2.6: "When a `RolloverProcessor` approves eligibility, the server
    records that operator's `X-User-ID` on the case as `eligibility_decided_by`.
    Thereafter, the four money-movement capabilities — assembling an outbound
    disbursement for an eligible case, executing a plan-to-plan transfer,
    executing an in-plan Roth conversion, and posting inbound rollover credit —
    each require that the acting operator's `X-User-ID` differ from the case's
    stored `eligibility_decided_by`. A violation is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_same_processor_cannot_issue_own_approval
    """
    bundle = build_approved_indirect_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    case = get_case(bundle["case"]["id"])
    assert case["eligibility_decided_by"] == "proc-1", (
        f"approver anchor must be proc-1, got {case['eligibility_decided_by']}"
    )

    resp = api_client.assemble_disbursement(
        case["id"], {"method": "ACH"}, make_processor_headers("proc-1")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

    disb = validate_success(api_client.assemble_disbursement(
        case["id"], {"method": "ACH"}, make_processor_headers("proc-2")
    ))
    assert disb["status"] == "PENDING", "a distinct processor may assemble the disbursement"


def test_direct_issue_blocked_while_verification_pending(api):
    """PRD §3.6: "for a `DIRECT_ROLLOVER_OUT` an `OUTBOUND` verification on the
    case must already stand at `VERIFIED` (else `ERR_VERIFICATION_NOT_VERIFIED`)."
    PRD §3.5: "The verification is born `PENDING` and completes when a processor
    records an `outcome` of `VERIFIED` or `FAILED`"

    Design: Difficulty/cross_entity_state_dependency/direct_issue_requires_verification_verified
    """
    bundle = build_approved_direct_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    ver = open_verification(bundle["case"]["id"], "OUTBOUND", method="PLAN_LETTER")
    assert ver["status"] == "PENDING"

    resp = _assemble(bundle["case"]["id"], method="WIRE")
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_NOT_VERIFIED, expected_status=409)


def test_direct_issue_unblocked_after_verification_verified(api):
    """PRD §3.6: "for a `DIRECT_ROLLOVER_OUT` an `OUTBOUND` verification on the
    case must already stand at `VERIFIED` (else `ERR_VERIFICATION_NOT_VERIFIED`)."
    PRD §3.6: "For a `DIRECT_ROLLOVER_OUT` — trustee-to-trustee movement —
    withholding is zero, as it is for transfers and conversions."

    Design: Difficulty/cross_entity_state_dependency/direct_issue_requires_verification_verified
    """
    bundle = build_approved_direct_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
    )
    ver = open_verification(bundle["case"]["id"], "OUTBOUND", method="PLAN_LETTER")
    complete_verification(ver["id"], "VERIFIED")

    disb = validate_success(_assemble(bundle["case"]["id"], method="WIRE"))
    assert disb["status"] == "PENDING", "the identical request succeeds once VERIFIED"
    assert disb["withholding_cents"] == 0, "direct trustee-to-trustee movement withholds zero"
