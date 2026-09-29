"""Optimistic concurrency on the two exposure-sensitive writes: a second draft
against a supplier, and a second cash application against a chargeback.
"""
from test_helpers import (
    REQ_LBL_01,
    ApiErrorId,
    cash_application_payload,
    create_vendor,
    deduction_payload,
    read_chargeback,
    read_vendor,
    set_clock,
    setup_assessed_chargeback,
    validate_error,
    validate_paginated,
    validate_success,
)

PROGRAMME_START = "2026-08-01T00:00:00Z"


def test_stale_vendor_version_blocks_a_second_deduction_draft(api, accountant_headers):
    """PRD §2.9: "Opening a draft deduction against a vendor requires
    `expected_vendor_version`, a non-optional field carrying the client's last
    observed `version` of that `Vendor`. If the vendor's current `version` differs
    — because a chargeback was assessed, a dispute was decided, another deduction
    was drafted or posted, or a scorecard was finalized since the client last read
    the vendor — the create is rejected with `ERR_STALE_VERSION` (412)."
    PRD §2.9: "Several deductions legitimately stack against one payable, so a
    second draft is perfectly valid product behaviour; the check exists because
    every draft re-reads the vendor's open exposure, and a stale view of that
    exposure would let an accountant net more than the vendor actually owes."
    PRD §2.7: "Optimistic concurrency — the supplied `expected_vendor_version` or
    `expected_chargeback_version` matches the parent's current `version`; otherwise
    `ERR_STALE_VERSION` (412). See §2.9."
    PRD §3.9: "The deduction opens in `DRAFT` with `amount_cents` 0,
    `allocation_count` 0, `over_allocated_cents` 0, and `posted_at`,
    `posted_by_user_id`, `reversed_at` and `reversal_reason` all null; creating it
    increments the supplier's `version` by one, which is exactly why a client
    drafting a second deduction must re-read the supplier first."
    PRD §4: "An endpoint that brings a new resource row into existence answers
    `201` on success; every other successful call answers `200`, including the
    action endpoints that only advance an existing row's state."

    Design: Corner/complexity_layers/corner_occ_stale_vendor_version_blocks_a_second_deduction_draft
    """
    set_clock(PROGRAMME_START)
    vendor = create_vendor(legal_name="Staleview Stationery")
    first_seen_version = validate_success(
        api.get_vendor(vendor["id"], accountant_headers), 200
    )["version"]

    first_draft = validate_success(
        api.create_deduction(
            deduction_payload(
                vendor["id"], first_seen_version, invoice_reference="INV-A"
            ),
            accountant_headers,
        ),
        201,
    )
    assert first_draft["invoice_reference"] == "INV-A"
    assert first_draft["status"] == "DRAFT", (
        f"a new deduction opens in DRAFT, got {first_draft['status']}"
    )

    replayed = api.create_deduction(
        deduction_payload(vendor["id"], first_seen_version, invoice_reference="INV-B"),
        accountant_headers,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_VERSION.value, 412)

    _, meta = validate_paginated(
        api.list_deductions(accountant_headers, params={"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the stale replay must not have drafted anything, got total_count "
        f"{meta['total_count']}"
    )

    re_read_version = read_vendor(vendor["id"])["version"]
    assert re_read_version > first_seen_version, (
        f"drafting a deduction increments the supplier's version, "
        f"{re_read_version} should exceed {first_seen_version}"
    )

    second_draft = validate_success(
        api.create_deduction(
            deduction_payload(vendor["id"], re_read_version, invoice_reference="INV-B"),
            accountant_headers,
        ),
        201,
    )
    assert second_draft["status"] == "DRAFT", (
        f"stacking drafts is legal once the version is re-read, "
        f"got {second_draft['status']}"
    )

    _, meta = validate_paginated(
        api.list_deductions(accountant_headers, params={"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 2, (
        f"two drafts should now stand against the payable, got total_count "
        f"{meta['total_count']}"
    )


def test_stale_chargeback_version_blocks_a_second_cash_application(
    api, accountant_headers
):
    """PRD §2.9: "Applying vendor cash to a chargeback requires
    `expected_chargeback_version`, carrying the client's last observed `version` of
    that `Chargeback`. A mismatch with the chargeback's current `version` is
    rejected with `ERR_STALE_VERSION` (412). Partial cash applications legitimately
    stack on one chargeback, so a second application is valid product behaviour;
    the check exists because the over-application ceiling of rung 32 is computed
    from `outstanding_cents`, and a stale view of that field would let cash exceed
    the amount actually owed."
    PRD §2.7: "Optimistic concurrency — the supplied `expected_vendor_version` or
    `expected_chargeback_version` matches the parent's current `version`; otherwise
    `ERR_STALE_VERSION` (412). See §2.9."
    PRD §3.9: "The application creates an allocation with `source_type` `CASH`,
    `deduction_id` null, `effective_status` `EFFECTIVE` and `applied_at` stamped
    from the logical clock at creation, storing the applied amount in the
    allocation's `allocated_cents` field and the supplied reference in
    `remittance_reference`."
    PRD §3.9: "The chargeback's `recovered_cents` rises by the applied amount,
    `outstanding_cents` and `settlement_status` are re-derived, the chargeback's
    `version` increments, and the supplier's exposure figures are recomputed."
    PRD §3.5: "The flat component, `fixed_fee_cents`, is copied straight from the
    pinned requirement's `fixed_fee_cents`. A unit-recovery amount is formed by
    multiplying the requirement's `per_unit_recovery_cents` by the violation's
    `affected_units`. A handling-recovery amount is formed by multiplying the
    shipment's `invoice_value_cents` by the requirement's `handling_pct`, dividing
    by 100, and rounding the result half up to a whole number of cents before it
    is used anywhere."
    PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the
    unit-recovery amount plus the handling-recovery amount — both components are
    charged."
    PRD §3.5: "Otherwise the variant is `STANDARD` — which is always the case for
    a `TIER_1` requirement, and is also the case for a `TIER_2` or `TIER_3`
    requirement once a matching prior chargeback exists inside that 180-day
    lookback. Under `STANDARD`, `cost_recovery_cents` keeps the value the
    severity-tier branch produced, the raw amount is the flat fee plus that cost
    recovery, the requirement's `min_fee_cents` is applied as a floor to the raw
    amount, and the requirement's `cap_cents` is applied as a ceiling to the
    floored result; `gross_assessed_cents` is that floored-then-capped figure."
    PRD §3.9: "Its net assessed balance is `gross_assessed_cents` less
    `reversal_cents`; its `recovered_cents` is the sum of `allocated_cents` over
    its allocations whose `effective_status` is `EFFECTIVE`, with pending
    allocations under a draft deduction and reversed allocations under a reversed
    deduction both contributing nothing; its `outstanding_cents` is the net
    assessed balance less `recovered_cents`, floored at 0 so it never reads
    negative; and its `deduction_posted` is true exactly when at least one of its
    allocations has `source_type` `DEDUCTION` and belongs to a deduction whose
    `status` is `POSTED`, a flag that is independent of the settlement dimension."
    PRD §3.9: "The `settlement_status` is then chosen by the first matching branch
    of four, tested in this order: the chargeback is `WRITTEN_OFF` when the net
    assessed balance is zero or below; otherwise `RECOVERED` when
    `recovered_cents` has reached or exceeded the net assessed balance; otherwise
    `PARTIALLY_RECOVERED` when `recovered_cents` is above zero; otherwise
    `ASSESSED`."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's
    chargebacks whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED`
    only, of `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this figure
    entirely. `recovered_lifetime_cents` is the sum of `allocated_cents` over every
    allocation on any of the supplier's chargebacks whose `effective_status` is
    `EFFECTIVE`, with no filter on the chargeback's settlement state."
    PRD §4: "An endpoint that brings a new resource row into existence answers
    `201` on success; every other successful call answers `200`, including the
    action endpoints that only advance an existing row's state."

    Design: Corner/complexity_layers/corner_occ_stale_chargeback_version_blocks_a_second_cash_application
    """
    world = setup_assessed_chargeback(
        REQ_LBL_01,
        (),
        assessment_note="Assessed.",
        requirement_overrides={"min_evidence_count": 0},
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels.",
    )
    chargeback_id = world["chargeback"]["id"]
    assert world["chargeback"]["gross_assessed_cents"] == 38_000, (
        f"gross_assessed_cents should be 38000, got "
        f"{world['chargeback']['gross_assessed_cents']}"
    )

    first_seen_version = validate_success(
        api.get_chargeback(chargeback_id, accountant_headers), 200
    )["version"]

    first_application = validate_success(
        api.apply_cash(
            chargeback_id,
            cash_application_payload(
                10_000, first_seen_version, remittance_reference="WIRE-1"
            ),
            accountant_headers,
        ),
        201,
    )
    assert first_application["source_type"] == "CASH", (
        f"cash application mints a CASH allocation, got "
        f"{first_application['source_type']}"
    )
    assert read_chargeback(chargeback_id)["outstanding_cents"] == 28_000, (
        "38000 assessed less 10000 applied leaves 28000 outstanding"
    )

    replayed = api.apply_cash(
        chargeback_id,
        cash_application_payload(5_000, first_seen_version, remittance_reference="WIRE-2"),
        accountant_headers,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_VERSION.value, 412)
    assert read_chargeback(chargeback_id)["recovered_cents"] == 10_000, (
        "the refused replay must not move any money"
    )

    re_read_version = read_chargeback(chargeback_id)["version"]
    assert re_read_version > first_seen_version, (
        f"a cash application increments the chargeback's version, "
        f"{re_read_version} should exceed {first_seen_version}"
    )

    second_application = validate_success(
        api.apply_cash(
            chargeback_id,
            cash_application_payload(
                5_000, re_read_version, remittance_reference="WIRE-2"
            ),
            accountant_headers,
        ),
        201,
    )
    assert second_application["allocated_cents"] == 5_000, (
        f"the retried application should carry 5000, got "
        f"{second_application['allocated_cents']}"
    )

    final = read_chargeback(chargeback_id)
    assert final["recovered_cents"] == 15_000, (
        f"10000 plus 5000 recovered, got {final['recovered_cents']}"
    )
    assert final["outstanding_cents"] == 23_000, (
        f"38000 less 15000 leaves 23000, got {final['outstanding_cents']}"
    )
    assert final["settlement_status"] == "PARTIALLY_RECOVERED", (
        f"recovery below the net assessed balance is partial, got "
        f"{final['settlement_status']}"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["recovered_lifetime_cents"] == 15_000, (
        f"lifetime recovery should be 15000, got {vendor['recovered_lifetime_cents']}"
    )
    assert vendor["open_chargeback_cents"] == 23_000, (
        f"open exposure should be 23000, got {vendor['open_chargeback_cents']}"
    )
