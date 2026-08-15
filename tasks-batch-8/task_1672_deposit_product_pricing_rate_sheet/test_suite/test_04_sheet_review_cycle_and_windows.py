"""Sheet review loop, scheduling window semantics, and retirement guard
(PRD §2.5, §2.8, §3.2)."""
from test_helpers import (
    ApiErrorId,
    create_draft_sheet,
    create_effective_sheet,
    create_product,
    create_rate_sheet_payload,
    list_sheet_deployments,
    list_sheet_notices,
    open_account,
    promote_sheet_to_scheduled,
    review_sheet,
    schedule_sheet,
    single_tier,
    submit_sheet,
    validate_error,
    validate_success,
)


def test_sheet_return_loop_draft_and_recall(api):
    """PRD §3.2: "A decision of `RETURN` is the committee's universal
    send-back: from `COMMITTEE_REVIEW` the sheet returns to `DRAFT`; from
    `APPROVED` it returns to `COMMITTEE_REVIEW`; and from `SCHEDULED` it falls
    back to `APPROVED`, in which case the server deletes the sheet's `PENDING`
    and `FAILED` deployment rows and its `PENDING` disclosure notices,
    unwinding the scheduling artifacts."
    PRD §2.5: "`version` (integer): starts at 1 on creation and increments by
    exactly one on every mutation. State transitions, cascade-driven
    repricing, sweep-driven changes, and explicit edits all count as mutations
    — none of them is exempt."

    Design: Difficulty/non_linear_state_machine/rate_sheet_review_cycle_loop
    """
    product = create_product(product_code="RLP")
    sheet = create_draft_sheet(product["id"], tiers=single_tier(100))

    submit_sheet(sheet["id"])  # v2, COMMITTEE_REVIEW
    returned = review_sheet(sheet["id"], "RETURN", reason="rework tiers")
    assert returned["status"] == "DRAFT"
    assert returned["version"] == 3

    submit_sheet(sheet["id"])  # v4
    review_sheet(sheet["id"], "APPROVE")  # v5, APPROVED
    recalled = review_sheet(sheet["id"], "RETURN", reason="recall")
    assert recalled["status"] == "COMMITTEE_REVIEW"
    assert recalled["version"] == 6


def test_sheet_return_from_scheduled_cleans_up_artifacts(api):
    """PRD §3.2: "and from `SCHEDULED` it falls back to `APPROVED`, in which
    case the server deletes the sheet's `PENDING` and `FAILED` deployment rows
    and its `PENDING` disclosure notices, unwinding the scheduling artifacts."
    PRD §2.5: "`version` (integer): starts at 1 on creation and increments by
    exactly one on every mutation."

    Design: Difficulty/non_linear_state_machine/rate_sheet_review_cycle_loop
    """
    product = create_product(product_code="RLP")
    sheet = create_draft_sheet(product["id"], tiers=single_tier(100))
    submit_sheet(sheet["id"])                       # v2
    review_sheet(sheet["id"], "RETURN", reason="rework tiers")  # v3 DRAFT
    submit_sheet(sheet["id"])                       # v4
    review_sheet(sheet["id"], "APPROVE")            # v5 APPROVED
    review_sheet(sheet["id"], "RETURN", reason="recall")        # v6 COMMITTEE_REVIEW
    review_sheet(sheet["id"], "APPROVE")            # v7 APPROVED
    schedule_sheet(sheet["id"])                     # v8 SCHEDULED
    assert len(list_sheet_deployments(sheet["id"])) == 4
    assert len(list_sheet_notices(sheet["id"])) == 4

    pulled = review_sheet(sheet["id"], "RETURN", reason="pull from calendar")
    assert pulled["status"] == "APPROVED"
    assert pulled["version"] == 9
    assert list_sheet_deployments(sheet["id"]) == []
    assert list_sheet_notices(sheet["id"]) == []


def _overlap_scenario():
    """S1 EFFECTIVE over [2026-08-15, 2026-09-01); S2 APPROVED over
    [2026-09-01, 2026-10-01) for the same pair."""
    product = create_product(product_code="OVL")
    s1 = create_effective_sheet(
        product_id=product["id"], effective_date="2026-08-15",
        sheet_overrides={"end_date": "2026-09-01"},
        tiers=single_tier(100))["sheet"]
    s2 = create_draft_sheet(product["id"], effective_date="2026-09-01",
                            end_date="2026-10-01", tiers=single_tier(110))
    submit_sheet(s2["id"])
    s2 = review_sheet(s2["id"], "APPROVE")
    return product, s1, s2


def test_sheet_window_adjacency_is_allowed(api, analyst_headers):
    """PRD §3.2: "Adjacency — the new `effective_date` landing exactly on
    another sheet's `end_date` — is always allowed."
    PRD §2.8: "A sheet prices accounts over a half-open effective window that
    begins on `effective_date` (inclusive) and ends on `end_date`
    (exclusive)."

    Design: Difficulty/resource_temporal_overlap/sheet_window_half_open_adjacency_allowed
    """
    _, s1, s2 = _overlap_scenario()
    assert s1["end_date"] == "2026-09-01"
    assert s2["effective_date"] == "2026-09-01"
    scheduled = validate_success(api.schedule_rate_sheet(s2["id"], analyst_headers))
    assert scheduled["status"] == "SCHEDULED"


def test_sheet_window_overlap_rejected(api, analyst_headers):
    """PRD §3.2: "The sheet's half-open window must not overlap any other
    sheet for the same pair that is in `SCHEDULED` — unconditionally. It may
    overlap the incumbent `EFFECTIVE` sheet only in chronological succession,
    that is, when the new sheet's `effective_date` is strictly later than the
    incumbent's; the incumbent is then superseded and truncated at activation.
    Adjacency — the new `effective_date` landing exactly on another sheet's
    `end_date` — is always allowed. Any other overlap is rejected with
    `ERR_EFFECTIVE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/sheet_window_half_open_adjacency_allowed
    """
    product, s1, s2 = _overlap_scenario()
    schedule_sheet(s2["id"])  # S2 SCHEDULED over [2026-09-01, 2026-10-01)

    # S3 overlaps EFFECTIVE S1 but starts earlier: not chronological
    # succession.
    s3 = create_draft_sheet(product["id"], effective_date="2026-08-10",
                            end_date="2026-08-20", tiers=single_tier(105))
    submit_sheet(s3["id"])
    review_sheet(s3["id"], "APPROVE")
    resp = api.schedule_rate_sheet(s3["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_EFFECTIVE_WINDOW_OVERLAP, 409)

    # S4 overlaps SCHEDULED S2: SCHEDULED-window overlap is unconditional.
    s4 = create_draft_sheet(product["id"], effective_date="2026-09-20",
                            tiers=single_tier(115))
    submit_sheet(s4["id"])
    review_sheet(s4["id"], "APPROVE")
    resp = api.schedule_rate_sheet(s4["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_EFFECTIVE_WINDOW_OVERLAP, 409)


def test_retire_effective_sheet_with_attached_accounts_blocked(api, committee_headers,
                                                               analyst_headers):
    """PRD §3.2: "Retirement is a `PricingCommittee` action available from
    `DRAFT`, `EFFECTIVE`, or `SUPERSEDED`, guarded by a single precondition:
    no DepositAccount may reference the sheet under any `rate_source` —
    attempting to retire a sheet with accounts still attached is rejected with
    `ERR_SHEET_INVALID_STATE`."

    Design: Corner/endpoints/retire_effective_sheet_with_attached_accounts_blocked
    """
    setup = create_effective_sheet(effective_date="2026-08-15", tiers=single_tier(100),
                                   product_overrides={"product_code": "RB"})
    open_account(setup["product_id"], opening_balance_cents=1_000_000,
                 customer_ref="CRB2")
    resp = api.retire_rate_sheet(setup["sheet"]["id"], committee_headers)
    validate_error(resp, ApiErrorId.ERR_SHEET_INVALID_STATE, 409)

    reread = validate_success(api.get_rate_sheet(setup["sheet"]["id"], analyst_headers))
    assert reread["status"] == "EFFECTIVE"
