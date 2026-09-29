"""Closed PayerContract terms plus the notice buffer: abutting collides, a 30-day gap fails."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId,
    factories,
    set_clock, create_facility, create_payer_contract,
    CONTRACT,
)

SCOPE = dict(payer_code="BCBS_STATE", product_line="COMMERCIAL")


def _setup():
    set_clock("2026-01-15T00:00:00Z")
    facility = create_facility(
        name="Contract Regional", cms_certification_number="CCN-2193-K",
        rounding_mode="NEAREST_CENT", aggregate_markup_limit_bp=40000,
    )
    contract = create_payer_contract(
        facility["id"], reimbursement_method="PERCENT_OF_CHARGE",
        percent_of_charge_bp=4500,
        term_start_date="2026-01-01T00:00:00Z",
        term_end_date="2026-06-30T00:00:00Z",
        renegotiation_notice_days=30,
        **SCOPE,
    )
    return {"facility": facility, "contract": contract}


def _successor_payload(s, term_start_date):
    return factories.create_payer_contract_payload(
        s["facility"]["id"], reimbursement_method="PERCENT_OF_CHARGE",
        percent_of_charge_bp=4700,
        term_start_date=term_start_date,
        term_end_date="2026-12-31T00:00:00Z",
        renegotiation_notice_days=30,
        **SCOPE,
    )


def test_a_successor_term_starting_on_the_prior_end_date_collides():
    """PRD §3.6: "First, no other contract of the same `(facility_id, payer_code,
    product_line)` scope key whose `status` is `ACTIVE` or `EXPIRED` may have a
    `[term_start_date, term_end_date]` interval intersecting the new one; because both
    endpoints are inclusive, a prior term ending exactly on the new term's start date *does*
    collide, and the create is refused with `ERR_CONTRACT_TERM_OVERLAP` (409)."
    PRD §2.5: "A contract covers an instant when `term_start_date` is at or before it and
    `term_end_date` is at or after it; `term_end_date` is never null."
    PRD §2.5: "Because both endpoints are inclusive, abutting payer terms *do* overlap."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap__payer_contract_closed_abut_collides_then_exact_notice_gap_buffer_violation
    """
    s = _setup()
    assert s["contract"]["status"] == "ACTIVE", (
        "the clock sits inside the prior term, so it has not auto-expired"
    )
    assert s["contract"]["renegotiation_notice_days"] == 30

    validate_error(
        api_client.create_payer_contract(
            _successor_payload(s, "2026-06-30T00:00:00Z"), CONTRACT
        ),
        ApiErrorId.ERR_CONTRACT_TERM_OVERLAP.value,
        409,
    )

    rows, _meta = validate_paginated(
        api_client.list_payer_contracts(
            CONTRACT, params={"facility_id": s["facility"]["id"], **SCOPE}
        )
    )
    assert len(rows) == 1, "the refused successor was never persisted"


def test_a_clear_gap_of_exactly_the_notice_period_fails_but_one_day_more_passes():
    """PRD §3.6: "Second, for the same scope key, the gap between the prior term's
    `term_end_date` and the new term's `term_start_date` must be **strictly greater** than the
    prior term's `renegotiation_notice_days` in days; a gap of exactly
    `renegotiation_notice_days` days fails with `ERR_CONTRACT_TERM_BUFFER_VIOLATION` (409)."
    PRD §3.6: "`renegotiation_notice_days`, defaulting to 30, sets the clear gap this term
    demands before a successor term of the same scope may begin."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap__payer_contract_closed_abut_collides_then_exact_notice_gap_buffer_violation
    """
    s = _setup()
    validate_error(
        api_client.create_payer_contract(
            _successor_payload(s, "2026-07-30T00:00:00Z"), CONTRACT
        ),
        ApiErrorId.ERR_CONTRACT_TERM_BUFFER_VIOLATION.value,
        409,
    )

    accepted = validate_success(
        api_client.create_payer_contract(
            _successor_payload(s, "2026-07-31T00:00:00Z"), CONTRACT
        ),
        201,
    )
    assert accepted["term_start_date"].startswith("2026-07-31T00:00:00"), (
        "a gap of 31 days is strictly greater than the 30-day notice period"
    )
    assert accepted["status"] == "ACTIVE"

    incumbent = validate_success(
        api_client.get_payer_contract(s["contract"]["id"], CONTRACT), 200
    )
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["term_end_date"].startswith("2026-06-30T00:00:00")

    rows, _meta = validate_paginated(
        api_client.list_payer_contracts(
            CONTRACT, params={"facility_id": s["facility"]["id"], **SCOPE}
        )
    )
    assert len(rows) == 2, f"exactly the incumbent and its successor: got {len(rows)}"
