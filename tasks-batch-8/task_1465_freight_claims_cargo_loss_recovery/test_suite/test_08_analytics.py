"""Analytics: carrier claim-ratio window variants (lifetime vs trailing 12
months), claim-aging bucket boundary precision, and default list pagination."""
from test_helpers import (
    assert_claim,
    create_assignment_payload,
    create_carrier_payload,
    create_claim_payload,
    create_document_payload,
    create_lane_payload,
    create_settlement_payload,
    create_shipment_payload,
    get_claim,
    get_success_data,
    set_clock,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _ratio_for(api, carrier_id, window):
    resp = api.get_carrier_claim_ratio(
        CLERK, params={"carrier_id": carrier_id, "window": window}
    )
    rows, _meta = validate_paginated(resp)
    matches = [r for r in rows if r.get("id") == carrier_id]
    assert len(matches) == 1, f"Expected exactly one ratio row for carrier, got {rows}"
    return matches[0]["claim_ratio_bp"]


def _file_claim(api, carrier_id, lane_id, *, ship_date, delivery_date,
                declared, claimed, submit_clock):
    """Register a shipment, open a claim with required docs, submit it."""
    shipment = get_success_data(
        api.create_shipment(
            create_shipment_payload(
                carrier_id,
                lane_id,
                ship_date=ship_date,
                delivery_date=delivery_date,
                declared_value_cents=declared,
            ),
            CLERK,
        )
    )
    claim = get_success_data(
        api.create_claim(
            create_claim_payload(
                shipment["id"], claim_type="LOSS", claimed_amount_cents=claimed
            ),
            CLERK,
        )
    )
    docs = []
    for kind in ("BOL", "COMMERCIAL_INVOICE"):
        docs.append(
            get_success_data(
                api.attach_document(
                    claim["id"],
                    create_document_payload(document_kind=kind, captured_at=ship_date),
                    CLERK,
                )
            )
        )
    set_clock(submit_clock)
    claim = get_success_data(api.submit_claim(claim["id"], CLERK))
    return shipment, claim, docs


def _setup_paid_old_and_declined_new(api):
    """One claim FILED 2025-02-01 then PAID; a second FILED 2026-06-10 then
    DECLINED. Reading clock ends at 2026-08-01."""
    set_clock("2024-12-01T00:00:00Z")
    carrier = get_success_data(api.create_carrier(create_carrier_payload(), MANAGER))
    lane = get_success_data(api.create_lane(create_lane_payload(), MANAGER))
    get_success_data(
        api.create_assignment(
            create_assignment_payload(
                carrier["id"],
                lane["id"],
                effective_from="2024-01-01T00:00:00Z",
                effective_to="2027-01-01T00:00:00Z",
            ),
            MANAGER,
        )
    )
    # Old claim: first FILED event at 2025-02-01, then paid in full.
    _s_old, claim_old, docs_old = _file_claim(
        api,
        carrier["id"],
        lane["id"],
        ship_date="2025-01-15T00:00:00Z",
        delivery_date="2025-01-20T00:00:00Z",
        declared=50_000,
        claimed=40_000,
        submit_clock="2025-02-01T00:00:00Z",
    )
    get_success_data(api.acknowledge_claim(claim_old["id"], ADJUSTER))
    for doc in docs_old:
        get_success_data(api.verify_document(claim_old["id"], doc["id"], ADJUSTER))
    get_success_data(
        api.create_assessment(claim_old["id"], {"negligence_flag": "CARRIER_NEGLIGENT"}, ADJUSTER)
    )
    get_success_data(api.post_reserve(claim_old["id"], {"amount_cents": 40_000}, FINANCE))
    version = get_claim(claim_old["id"])["version"]
    settlement = get_success_data(
        api.create_settlement(
            claim_old["id"], create_settlement_payload(40_000, version), ADJUSTER
        )
    )
    get_success_data(api.accept_settlement(claim_old["id"], settlement["id"], MANAGER))
    assert get_claim(claim_old["id"])["filing_status"] == "PAID"
    # New claim: first FILED event at 2026-06-10, then declined (never paid).
    _s_new, claim_new, docs_new = _file_claim(
        api,
        carrier["id"],
        lane["id"],
        ship_date="2026-06-01T00:00:00Z",
        delivery_date="2026-06-05T00:00:00Z",
        declared=30_000,
        claimed=20_000,
        submit_clock="2026-06-10T00:00:00Z",
    )
    get_success_data(api.acknowledge_claim(claim_new["id"], ADJUSTER))
    for doc in docs_new:
        get_success_data(api.verify_document(claim_new["id"], doc["id"], ADJUSTER))
    get_success_data(
        api.create_assessment(claim_new["id"], {"negligence_flag": "ACT_OF_GOD"}, ADJUSTER)
    )
    version = get_claim(claim_new["id"])["version"]
    get_success_data(
        api.decline_claim(claim_new["id"], {"expected_claim_version": version}, ADJUSTER)
    )
    set_clock("2026-08-01T00:00:00Z")
    return carrier


class TestCarrierClaimRatioWindows:
    def test_lifetime_window_counts_all_filed_claims(self, api):
        """PRD §3.9: "Per carrier, `claims_filed_count` counts claims that ever entered `SUBMITTED` — established from the event stream, counting only the first `FILED` event per claim so that a resubmission after withdrawal never double-counts — while `claims_paid_count` counts claims currently in `PAID` or `CLOSED_WITH_PAYMENT`; `claim_ratio_bp` is the paid count multiplied by 10,000 and divided by the filed count, with a denominator of zero treated as one so that a carrier with no filings reports a ratio of zero, rounded half-up to whole basis points."
        PRD §3.9: "The carrier-ratio analytic accepts a `window` selector: `TRAILING_12M` restricts the input set to claims whose first `FILED` event falls within the trailing 365 days up to the current logical time, while `LIFETIME` — the default — applies no time filter."

        Design: Difficulty/dual_variant_calc/claim_ratio_trailing_12m_vs_lifetime
        """
        carrier = _setup_paid_old_and_declined_new(api)
        # LIFETIME: 1 paid out of 2 ever-filed -> round(1*10000/2) = 5000 bp.
        assert _ratio_for(api, carrier["id"], "LIFETIME") == 5_000

    def test_trailing_12m_window_excludes_old_filings(self, api):
        """PRD §3.9: "The carrier-ratio analytic accepts a `window` selector: `TRAILING_12M` restricts the input set to claims whose first `FILED` event falls within the trailing 365 days up to the current logical time, while `LIFETIME` — the default — applies no time filter."
        PRD §3.9: "Per carrier, `claims_filed_count` counts claims that ever entered `SUBMITTED` — established from the event stream, counting only the first `FILED` event per claim so that a resubmission after withdrawal never double-counts — while `claims_paid_count` counts claims currently in `PAID` or `CLOSED_WITH_PAYMENT`; `claim_ratio_bp` is the paid count multiplied by 10,000 and divided by the filed count, with a denominator of zero treated as one so that a carrier with no filings reports a ratio of zero, rounded half-up to whole basis points."

        Design: Difficulty/dual_variant_calc/claim_ratio_trailing_12m_vs_lifetime
        """
        carrier = _setup_paid_old_and_declined_new(api)
        # TRAILING_12M from 2026-08-01 covers [2025-08-01, 2026-08-01]: the paid
        # claim (first FILED 2025-02-01) falls outside; only the declined claim
        # remains -> 0 paid of 1 filed -> 0 bp. LIFETIME reports 5000 bp for the
        # same carrier, so the two variants diverge on identical inputs.
        assert _ratio_for(api, carrier["id"], "TRAILING_12M") == 0
        assert _ratio_for(api, carrier["id"], "LIFETIME") == 5_000


class TestClaimAgingBuckets:
    def _setup_three_aged_claims(self, api):
        set_clock("2026-05-01T00:00:00Z")
        carrier = get_success_data(api.create_carrier(create_carrier_payload(), MANAGER))
        lane = get_success_data(api.create_lane(create_lane_payload(), MANAGER))
        get_success_data(
            api.create_assignment(
                create_assignment_payload(
                    carrier["id"],
                    lane["id"],
                    effective_from="2025-01-01T00:00:00Z",
                    effective_to="2027-01-01T00:00:00Z",
                ),
                MANAGER,
            )
        )
        # Ages at the 2026-08-01 reading clock: 29, 30, and 91 days.
        _file_claim(
            api, carrier["id"], lane["id"],
            ship_date="2026-06-15T00:00:00Z", delivery_date="2026-06-20T00:00:00Z",
            declared=10_000, claimed=5_000, submit_clock="2026-07-03T00:00:00Z",
        )
        _file_claim(
            api, carrier["id"], lane["id"],
            ship_date="2026-06-10T00:00:00Z", delivery_date="2026-06-15T00:00:00Z",
            declared=10_000, claimed=5_000, submit_clock="2026-07-02T00:00:00Z",
        )
        _file_claim(
            api, carrier["id"], lane["id"],
            ship_date="2026-04-20T00:00:00Z", delivery_date="2026-04-25T00:00:00Z",
            declared=10_000, claimed=5_000, submit_clock="2026-05-02T00:00:00Z",
        )
        set_clock("2026-08-01T00:00:00Z")

    def test_aging_boundary_thirty_days_lands_in_higher_bucket(self, api):
        """PRD §3.9: "Every claim in one of the six working statuses — `SUBMITTED`, `ACKNOWLEDGED`, `UNDER_REVIEW`, `OFFERED`, `DECLINED`, or `APPEALED` — is aged by taking the elapsed time between its `filing_received_at` and the current logical time and rounding down to whole days. A claim younger than 30 days falls in `B0_30`; from 30 up to but not including 60 days it falls in `B31_60`; from 60 up to but not including 90 days, `B61_90`; and 90 days or older, `B91_PLUS`. Boundaries land in the higher bucket — a claim exactly 30 days old is `B31_60`, not `B0_30`."

        Design: Difficulty/combinatorial_formula/claim_aging_bucket_boundary_precision
        """
        self._setup_three_aged_claims(api)
        data = validate_success(api.get_claim_aging(CLERK), 200)
        # Ages 29 and 30 days: 29 -> B0_30; exactly 30 -> B31_60.
        assert data["B0_30"] == 1
        assert data["B31_60"] == 1
        assert data["B61_90"] == 0

    def test_aging_ninety_plus_bucket_counts_oldest_claim(self, api):
        """PRD §3.9: "Every claim in one of the six working statuses — `SUBMITTED`, `ACKNOWLEDGED`, `UNDER_REVIEW`, `OFFERED`, `DECLINED`, or `APPEALED` — is aged by taking the elapsed time between its `filing_received_at` and the current logical time and rounding down to whole days. A claim younger than 30 days falls in `B0_30`; from 30 up to but not including 60 days it falls in `B31_60`; from 60 up to but not including 90 days, `B61_90`; and 90 days or older, `B91_PLUS`. Boundaries land in the higher bucket — a claim exactly 30 days old is `B31_60`, not `B0_30`."

        Design: Difficulty/combinatorial_formula/claim_aging_bucket_boundary_precision
        """
        self._setup_three_aged_claims(api)
        data = validate_success(api.get_claim_aging(CLERK), 200)
        # The claim filed 2026-05-02 is 91 days old at 2026-08-01 -> B91_PLUS.
        assert data["B91_PLUS"] == 1
        assert (
            data["B0_30"] + data["B31_60"] + data["B61_90"] + data["B91_PLUS"] == 3
        )


class TestClaimListPagination:
    def test_list_claims_default_pagination(self, api, clerk_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_claims_pagination_default
        """
        set_clock("2026-06-01T00:00:00Z")
        carrier = get_success_data(api.create_carrier(create_carrier_payload(), MANAGER))
        lane = get_success_data(api.create_lane(create_lane_payload(), MANAGER))
        get_success_data(
            api.create_assignment(
                create_assignment_payload(carrier["id"], lane["id"]), MANAGER
            )
        )
        for _ in range(12):
            shipment = get_success_data(
                api.create_shipment(
                    create_shipment_payload(carrier["id"], lane["id"]), CLERK
                )
            )
            claim = get_success_data(
                api.create_claim(
                    create_claim_payload(
                        shipment["id"], claim_type="LOSS", claimed_amount_cents=500
                    ),
                    CLERK,
                )
            )
            assert_claim(claim)
        resp = api.list_claims(clerk_headers)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 12
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(data) == 10
        assert meta["has_more"] is True
