"""Refund claims: interest variants, OCC on return version, supersession."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_taxpayer_headers, make_admin_headers,
    create_active_taxpayer, create_jurisdiction, create_filed_return,
    set_clock, create_open_refund_claim, get_refund_claim, get_return,
    create_refund_claim_payload, create_return_line,
)


def test_refund_interest_statutory_delay_variant(api):
    """PRD §3.7: "When the `reason` is `TAXPAYER_ERROR`, interest is a statutory-delay
    variant that only begins after a 90-day grace period from the claim's filing date:
    the chargeable days are the days from the claim's `created_at` date to the approval
    date on the logical clock, less 90, floored at zero, and the `interest_cents` is the
    principal `claim_amount_cents` multiplied by 3 basis points, divided by 10000,
    multiplied by those chargeable days, rounded half-up; a claim approved within the
    grace period earns zero interest."

    Design: Difficulty/dual_variant_calc/refund_interest_variant_statutory_vs_overpayment
    """
    set_clock(api, "2026-01-01T00:00:00Z")
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    filed = create_filed_return(api, tp["id"], lines=[line])
    claim = create_open_refund_claim(api, tp["id"], filed["id"], filed["version"],
                                     claim_amount_cents=50000, reason="TAXPAYER_ERROR",
                                     overpayment_date="2026-01-01T00:00:00Z")
    set_clock(api, "2026-06-01T00:00:00Z")
    approved = validate_success(api.approve_refund_claim(claim["id"], make_admin_headers()))
    assert approved["interest_cents"] == 915
    assert approved["refund_total_cents"] == 50915


def test_refund_interest_overpayment_date_variant(api):
    """PRD §3.7: "When the `reason` is `AUDIT_ADJUSTMENT`, interest accrues from the
    `overpayment_date` with no grace: the days are counted from `overpayment_date` to the
    approval date, and the `interest_cents` is the principal multiplied by 3 basis points,
    divided by 10000, multiplied by those days, rounded half-up."

    Design: Difficulty/dual_variant_calc/refund_interest_variant_statutory_vs_overpayment
    """
    set_clock(api, "2026-01-01T00:00:00Z")
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    filed = create_filed_return(api, tp["id"], lines=[line])
    claim = create_open_refund_claim(api, tp["id"], filed["id"], filed["version"],
                                     claim_amount_cents=50000, reason="AUDIT_ADJUSTMENT",
                                     overpayment_date="2026-01-01T00:00:00Z")
    set_clock(api, "2026-06-01T00:00:00Z")
    approved = validate_success(api.approve_refund_claim(claim["id"], make_admin_headers()))
    assert approved["interest_cents"] == 2265
    assert approved["refund_total_cents"] == 52265


def test_stale_return_version_on_refund_create_rejected(api):
    """PRD §2.7: "a create-refund request must carry `expected_return_version` equal to
    the target return's current `version`. If another writer has advanced the return's
    `version` since the client last read it — for instance because a prior refund claim
    was filed and superseded, which itself advances the return — the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_return_version_on_refund_create
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    filed = create_filed_return(api, tp["id"], jurisdiction_id=jur["id"])
    stale_version = filed["version"]
    # First create succeeds and advances the return's version.
    create_open_refund_claim(api, tp["id"], filed["id"], stale_version, claim_amount_cents=5000)
    # Second create still carrying the stale version is refused.
    resp = api.create_refund_claim(
        create_refund_claim_payload(tp["id"], filed["id"], stale_version,
                                    claim_amount_cents=6000),
        make_taxpayer_headers(tp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_refund_create_supersedes_prior_open_claim(api):
    """PRD §3.7: "Filing a claim supersedes any prior `RefundClaim` on the same return
    still in `OPEN`, driving that prior claim to `SUPERSEDED`, and it advances the return's
    `version`".

    Design: Corner/cross_cutting_complexity_layers/refund_create_supersedes_prior_open_claim
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    filed = create_filed_return(api, tp["id"], jurisdiction_id=jur["id"])
    claim1 = create_open_refund_claim(api, tp["id"], filed["id"], filed["version"],
                                      claim_amount_cents=5000)
    fresh_version = get_return(api, filed["id"])["version"]
    resp = api.create_refund_claim(
        create_refund_claim_payload(tp["id"], filed["id"], fresh_version,
                                    claim_amount_cents=6000),
        make_taxpayer_headers(tp["id"]),
    )
    claim2 = validate_success(resp, expected_status=201)
    assert get_refund_claim(api, claim1["id"])["status"] == "SUPERSEDED"
    assert claim2["status"] == "OPEN"
