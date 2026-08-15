"""Filing fees: quoted-vs-charged evaluation instants, tiered/county/expedited formula,
half-up rounding, per-kind deltas, and the additional-debtor tier boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_preparation,
    create_draft_attempt,
    create_filing_request,
    create_in_review_request,
    create_ready_request,
    create_ucc3_request,
    get_client_account,
    get_filing,
    get_request,
    seed_jurisdiction_profile,
    setup_active_initial_filing,
    setup_client_world,
    submit_attempt,
    submit_intake,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_amendment_kind_fee_delta_applied(api):
    """PRD §3.4: "The subtotal is the profile's `base_fee_cents`, plus the profile's
    `per_additional_debtor_fee_cents` multiplied by the request's
    `additional_debtor_count`, plus the profile's `county_surcharge_cents` when the
    request's `filing_office` is `COUNTY` (nothing when it is `STATE`), plus a flat
    per-kind delta — zero cents for `NEW_UCC1`, 1,000 cents for `AMENDMENT`, 1,500
    cents for `CONTINUATION`, and 500 cents for `TERMINATION`."
    PRD §3.3: "Approval is also the quoting instant. The system evaluates the
    filing-fee formula of §3.4 against the jurisdiction profile's values in effect at
    that instant and snapshots the result onto `quoted_fee_cents`."

    Design: Corner/calculations/amendment_kind_fee_delta_applied
    """
    ctx = setup_active_initial_filing()
    amendment = create_ucc3_request(
        "AMENDMENT", ctx["client"], ctx["debtor"], ctx["secured_party"],
        ctx["filing"]["id"])
    submit_intake(amendment["id"], user_id="spec-1")
    approved = approve_preparation(amendment["id"])
    assert approved["quoted_fee_cents"] == 11000, (
        f"STATE STANDARD amendment quotes 10000 + 1000, got {approved['quoted_fee_cents']}"
    )


def test_quoted_fee_snapshots_profile_at_approval(api):
    """PRD §3.3: "Approval is also the quoting instant. The system evaluates the
    filing-fee formula of §3.4 against the jurisdiction profile's values in effect at
    that instant and snapshots the result onto `quoted_fee_cents`."
    PRD §3.1: "Because quoted and charged fees read the profile at different instants
    (§3.3 and §3.4), a mid-flight profile update is precisely what makes the two
    figures diverge."

    Design: Difficulty/dual_variant_calc/fee_quote_vs_charged_after_profile_update
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"],
                                   world["secured_party"])
    assert request["quoted_fee_cents"] == 10000, (
        f"quote must snapshot the profile at approval, got {request['quoted_fee_cents']}"
    )
    # Mid-flight profile update: base fee rises after the quote was snapshotted.
    validate_success(
        api.update_jurisdiction_profile(
            world["profile"]["id"], {"base_fee_cents": 12000}, ADMIN),
        expected_status=200)
    reread = get_request(request["id"])
    assert reread["quoted_fee_cents"] == 10000, (
        "the quoted fee is a frozen snapshot and must not be rewritten by the update"
    )


def test_charged_fee_reads_profile_at_submission(api):
    """PRD §3.3: "The quoted and charged fees are the same formula evaluated at two
    different instants — approval and submission — and differ only in which profile
    values they read."
    PRD §3.4: "On success the fee is locked onto the attempt as `charged_fee_cents`,
    the client's `fees_charged_total_cents` increases by `charged_fee_cents`,
    `submitted_at` is set to the current instant, the attempt moves `DRAFT` →
    `SUBMITTED`, the parent request moves `READY` → `IN_PROCESS`, and a `SUBMITTED`
    event is appended."

    Design: Difficulty/dual_variant_calc/fee_quote_vs_charged_after_profile_update
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"],
                                   world["secured_party"])
    quoted = request["quoted_fee_cents"]
    validate_success(
        api.update_jurisdiction_profile(
            world["profile"]["id"], {"base_fee_cents": 12000}, ADMIN),
        expected_status=200)
    attempt = create_draft_attempt(request["id"], secured_amount_cents=500000)
    submitted = submit_attempt(attempt["id"])
    assert quoted == 10000
    assert submitted["charged_fee_cents"] == 12000, (
        f"charged fee must read the profile at submission, got "
        f"{submitted['charged_fee_cents']}"
    )
    assert submitted["charged_fee_cents"] - quoted == 2000, (
        "the two evaluation instants diverge by exactly the base-fee delta"
    )
    assert submitted["effectiveness_status"] == "SUBMITTED"
    assert get_client_account(world["client"]["id"])["fees_charged_total_cents"] == 12000


def test_county_tiered_expedited_fee_charged(api):
    """PRD §3.4: "The subtotal is the profile's `base_fee_cents`, plus the profile's
    `per_additional_debtor_fee_cents` multiplied by the request's
    `additional_debtor_count`, plus the profile's `county_surcharge_cents` when the
    request's `filing_office` is `COUNTY` (nothing when it is `STATE`), plus a flat
    per-kind delta — zero cents for `NEW_UCC1`, 1,000 cents for `AMENDMENT`, 1,500
    cents for `CONTINUATION`, and 500 cents for `TERMINATION`."
    PRD §3.4: "When `service_level` is `EXPEDITED`, that integer subtotal is multiplied
    by one and a half and the product is rounded half-up to whole cents in a single
    final step, with per-component rounding before summation forbidden; `STANDARD`
    service is charged the unmultiplied subtotal."

    Design: Difficulty/combinatorial_formula/fee_county_tiered_expedited_multi_input
    """
    world = setup_client_world()
    request = create_ready_request(
        world["client"], world["debtor"], world["secured_party"],
        collateral_class="FIXTURE", county_name="LOS_ANGELES",
        service_level="EXPEDITED", additional_debtor_count=2)
    assert request["filing_office"] == "COUNTY", (
        "FIXTURE collateral is in the CA county class list and must resolve to COUNTY"
    )
    attempt = create_draft_attempt(request["id"], secured_amount_cents=500000)
    submitted = submit_attempt(attempt["id"])
    # (10000 + 2*1500 + 2500 + 0) * 1.5 = 23250
    assert submitted["charged_fee_cents"] == 23250, (
        f"expected 23250, got {submitted['charged_fee_cents']}"
    )
    assert submitted["filing_office"] == "COUNTY"
    assert submitted["county_name"] == "LOS_ANGELES"


def test_county_tiered_expedited_fee_quoted(api):
    """PRD §3.3: "Approval is also the quoting instant. The system evaluates the
    filing-fee formula of §3.4 against the jurisdiction profile's values in effect at
    that instant and snapshots the result onto `quoted_fee_cents`."
    PRD §3.4: "When `service_level` is `EXPEDITED`, that integer subtotal is multiplied
    by one and a half and the product is rounded half-up to whole cents in a single
    final step, with per-component rounding before summation forbidden".

    Design: Difficulty/combinatorial_formula/fee_county_tiered_expedited_multi_input
    """
    world = setup_client_world()
    request = create_in_review_request(
        world["client"], world["debtor"], world["secured_party"],
        collateral_class="FIXTURE", county_name="LOS_ANGELES",
        service_level="EXPEDITED", additional_debtor_count=2)
    approved = approve_preparation(request["id"])
    # (10000 + 2*1500 + 2500 + 0) * 1.5 = 23250 — the same formula at the quote instant.
    assert approved["quoted_fee_cents"] == 23250, (
        f"expected quoted 23250, got {approved['quoted_fee_cents']}"
    )
    assert approved["filing_office"] == "COUNTY"


def test_expedited_rounding_half_up_single_pass(api):
    """PRD §3.4: "When `service_level` is `EXPEDITED`, that integer subtotal is
    multiplied by one and a half and the product is rounded half-up to whole cents in
    a single final step, with per-component rounding before summation forbidden".

    Design: Difficulty/combinatorial_formula/fee_expedited_rounding_half_up_single_pass
    """
    world = setup_client_world()
    request = create_ready_request(
        world["client"], world["debtor"], world["secured_party"],
        service_level="EXPEDITED")
    # Raise the base to an odd value so the 1.5x product lands on a half cent.
    validate_success(
        api.update_jurisdiction_profile(
            world["profile"]["id"], {"base_fee_cents": 10001}, ADMIN),
        expected_status=200)
    attempt = create_draft_attempt(request["id"], secured_amount_cents=500000)
    submitted = submit_attempt(attempt["id"])
    # 10001 * 1.5 = 15001.5 -> 15002 by the single final half-up rounding.
    assert submitted["charged_fee_cents"] == 15002, (
        f"half-up rounding of 15001.5 must yield 15002, got "
        f"{submitted['charged_fee_cents']}"
    )


def test_expedited_rounded_fee_flows_to_ledger(api):
    """PRD §3.4: "On success the fee is locked onto the attempt as
    `charged_fee_cents`, the client's `fees_charged_total_cents` increases by
    `charged_fee_cents`".
    PRD §2.7: "The single multiplication in the fee formula — the expedited uplift —
    is applied once to the integer subtotal, and the product is rounded half-up to
    whole cents in one final rounding step; rounding any component before summation is
    forbidden."

    Design: Difficulty/combinatorial_formula/fee_expedited_rounding_half_up_single_pass
    """
    world = setup_client_world()
    request = create_ready_request(
        world["client"], world["debtor"], world["secured_party"],
        service_level="EXPEDITED")
    validate_success(
        api.update_jurisdiction_profile(
            world["profile"]["id"], {"base_fee_cents": 10001}, ADMIN),
        expected_status=200)
    attempt = create_draft_attempt(request["id"], secured_amount_cents=500000)
    submitted = submit_attempt(attempt["id"])
    assert submitted["effectiveness_status"] == "SUBMITTED"
    client = get_client_account(world["client"]["id"])
    assert client["fees_charged_total_cents"] == 15002, (
        "the rounded half-up fee is exactly what the ledger is debited"
    )
    assert get_request(request["id"])["status"] == "IN_PROCESS"


def test_quote_no_surcharge_at_zero_additional_debtors(api):
    """PRD §3.4: "The subtotal is the profile's `base_fee_cents`, plus the profile's
    `per_additional_debtor_fee_cents` multiplied by the request's
    `additional_debtor_count`".
    PRD §3.2: "`additional_debtor_count` (the number of debtors beyond the primary,
    zero or more, defaulting to 0)".

    Design: Difficulty/boundary_precision_check/fee_debtor_count_tier_zero_vs_one
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"],
                                   world["secured_party"])
    assert request["additional_debtor_count"] == 0, "the default of 0 must apply"
    assert request["quoted_fee_cents"] == 10000, (
        f"count 0 adds no surcharge: expected 10000, got {request['quoted_fee_cents']}"
    )


def test_quote_one_surcharge_at_one_additional_debtor(api):
    """PRD §3.4: "The subtotal is the profile's `base_fee_cents`, plus the profile's
    `per_additional_debtor_fee_cents` multiplied by the request's
    `additional_debtor_count`".

    Design: Difficulty/boundary_precision_check/fee_debtor_count_tier_zero_vs_one
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"],
                                   world["secured_party"],
                                   additional_debtor_count=1)
    assert request["quoted_fee_cents"] == 11500, (
        f"count 1 adds exactly one 1500 surcharge: expected 11500, got "
        f"{request['quoted_fee_cents']}"
    )
