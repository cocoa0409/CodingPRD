"""The item lifecycle dimension: submission, its non-idempotence, and approval from DRAFT."""
from test_helpers import (
    api_client, validate_error, ApiErrorId,
    setup_base, create_item, item_lifecycle, read_item, read_facility, set_clock,
    ANALYST, APPROVER,
)

ITEM = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def _setup():
    """A DRAFT, never-repriced item in an OPEN facility."""
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(
        facility_overrides={
            "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
            "rounding_mode": "NEAREST_CENT",
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={
            "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
            "allowed_revenue_code_values": [],
        },
    )
    base["item"] = create_item(base, **ITEM)
    return base


def test_submission_moves_only_the_lifecycle_dimension():
    """PRD §3.3: "`DRAFT → PENDING_REVIEW` is the analyst's submission for review. Beyond posture
    it re-checks the revenue-code mapping legality (`ERR_REVENUE_CODE_MAPPING_INVALID`) and the
    department whitelist (`ERR_DEPARTMENT_REVENUE_CODE_NOT_ALLOWED`) — the same two rules enforced
    at creation, re-evaluated because reference data may have moved in between. It sets
    `lifecycle_status` to `PENDING_REVIEW` and touches nothing in the pricing dimension: the two
    dimensions are independent and this transition does not read or write `price_status`."
    PRD §3.3: "Every one of them is gated on the facility not being `FROZEN`, and every one of
    them advances the item's `version` by 1."
    PRD §2.11: "Items in `DRAFT`, `PENDING_REVIEW`, `APPROVED`, `INACTIVE` or `ARCHIVED` never
    contribute to any facility aggregate."

    Design: Corner/state_machines/item_submit_for_review_moves_draft_to_pending_review_only
    """
    base = _setup()
    assert base["item"]["version"] == 1

    submitted = item_lifecycle(base["item"]["id"], "SUBMIT_FOR_REVIEW", ANALYST,
                               note="Ready for pricing review")
    assert submitted["lifecycle_status"] == "PENDING_REVIEW"
    assert submitted["price_status"] == "PRICE_STALE", "the pricing dimension is untouched"
    assert submitted["gross_charge_cents"] == 0
    assert submitted["version"] == 2

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 0
    assert facility["aggregate_gross_charge_cents"] == 0
    assert facility["chargemaster_posture"] == "OPEN"


def test_replaying_the_same_submission_is_refused_rather_than_absorbed():
    """PRD §3.3: "An action that is not declared out of the item's current `lifecycle_status` —
    archiving directly from `ACTIVE`, approving from `DRAFT`, and so on — is
    `ERR_INVALID_ITEM_LIFECYCLE_STATE` (409)."
    PRD §2.4: "Most entities additionally carry `updated_at` (same format as `created_at`,
    refreshed on every mutation) and `version` (an integer that starts at 1 on creation and
    increases by exactly 1 on every mutation of that row)."

    Design: Corner/state_machines/item_submit_for_review_twice_second_call_rejected_not_idempotent
    """
    base = _setup()
    first = item_lifecycle(base["item"]["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    assert first["version"] == 2

    validate_error(
        api_client.charge_item_lifecycle(
            base["item"]["id"], {"action": "SUBMIT_FOR_REVIEW"}, ANALYST
        ),
        ApiErrorId.ERR_INVALID_ITEM_LIFECYCLE_STATE.value,
        409,
    )

    item = read_item(base["item"]["id"])
    assert item["lifecycle_status"] == "PENDING_REVIEW"
    assert item["version"] == 2, (
        "the refused replay performed no write, so the version counter did not move"
    )


def test_approving_straight_from_draft_reports_the_state_error_not_the_price_error():
    """PRD §2.9: "13. Entity-state admissibility, one rank shared by nine mutually exclusive rules
    distinguished by target entity, so exactly one can fire for a given request:
    `ERR_INVALID_ITEM_LIFECYCLE_STATE` (409) for item lifecycle and reprice"
    PRD §3.3: "`PENDING_REVIEW → APPROVED` is a `PricingCommitteeApprover` action, and here the
    two dimensions finally meet. Two additional preconditions apply beyond posture, evaluated in
    this order: the pricing dimension must already be settled, meaning `price_status` must equal
    `PRICED_CURRENT`, otherwise `ERR_ITEM_PRICE_NOT_CURRENT` (409)"

    Design: Corner/state_machines/item_approve_from_draft_rejected_invalid_lifecycle_state
    """
    base = _setup()
    assert base["item"]["price_status"] == "PRICE_STALE", (
        "the never-repriced item would also breach the lower-ranked price-state rule"
    )
    resp = api_client.charge_item_lifecycle(
        base["item"]["id"], {"action": "APPROVE"}, APPROVER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ITEM_LIFECYCLE_STATE.value, 409)
    assert (resp.json().get("data") or {}).get("error_id") != (
        ApiErrorId.ERR_ITEM_PRICE_NOT_CURRENT.value
    ), "rank 13 must mask the rank-49 price-state rule"

    item = read_item(base["item"]["id"])
    assert item["lifecycle_status"] == "DRAFT"
    assert item["approved_by_user_id"] is None
    assert item["version"] == 1
