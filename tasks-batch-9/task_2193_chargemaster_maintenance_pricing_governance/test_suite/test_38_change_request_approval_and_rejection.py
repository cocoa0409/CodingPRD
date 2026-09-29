"""Approval's post-bump pin, and the rejection cascade that a sibling approval suppresses."""
from test_helpers import (
    validate_success, api_client,
    setup_base, create_active_item, create_change_request, read_change_request,
    review_change_request, decide_change_request, approve_change_request,
    read_item, read_facility, read_department, set_clock,
    ANALYST, ANALYST_USER_ID, APPROVER, APPROVER_USER_ID, MANAGER_USER_ID,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
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

ITEM = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def _setup():
    """An ACTIVE, PRICED_CURRENT item at gross 240000 and version 5."""
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    base["item"] = create_active_item(base, **ITEM)
    assert base["item"]["version"] == 5
    assert base["item"]["gross_charge_cents"] == 240000
    assert base["item"]["price_status"] == "PRICED_CURRENT"
    return base


def test_approval_pins_the_version_that_its_own_bump_produced():
    """PRD §3.5: "For `PRICE_CHANGE` and `NEW_ITEM`, the target item's `price_status` moves to
    `REPRICE_PENDING` and `ChargeItem.version` advances by 1; `pinned_charge_item_version` is set to
    the *post-bump* version so that the later implementation can match it."
    PRD §3.5: "First — after the generic state admissibility check and before every business rule —
    the supplied `expected_charge_item_version` must equal the live `ChargeItem.version`, otherwise
    `ERR_STALE_ITEM_VERSION` (HTTP 412)."
    PRD §3.2: "Third, `projected_markup_ratio_bp` is the sum of snapshot and proposed gross charge,
    multiplied by 10000, divided by the sum of snapshot and proposed cost, rounded half up — and
    defined as 0 when that denominator is 0."

    Design: Corner/state_machines/change_request_approve_pins_post_bump_item_version_and_flips_price_status
    """
    base = _setup()
    request = create_change_request(
        base, base["item"]["id"], "PRICE_CHANGE",
        justification="Catheter supply contract repriced for FY27",
        proposed_cost_basis_cents=300000,
    )
    assert request["projected_gross_charge_cents"] == 540000, (
        "a proposed cost of 300000 reaches the 18000bp band"
    )
    assert request["projected_markup_ratio_bp"] == 18000, (
        "the ACTIVE item is excluded from the snapshot first, leaving 540000 over 300000"
    )
    review_change_request(request["id"], ANALYST)

    approved = approve_change_request(
        request["id"], 5, APPROVER, decision_note="Committee approved 2026-09-01"
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == APPROVER_USER_ID
    assert approved["reviewed_by_user_id"] == ANALYST_USER_ID
    assert approved["submitted_by_user_id"] == MANAGER_USER_ID
    assert approved["pinned_charge_item_version"] == 6, (
        "the approver supplied 5 as the expected version; the pin records the post-bump 6"
    )
    assert approved["version"] == 3, "one create, one review, one approval"

    item = read_item(base["item"]["id"])
    assert item["price_status"] == "REPRICE_PENDING"
    assert item["lifecycle_status"] == "ACTIVE", "the lifecycle dimension is untouched"
    assert item["version"] == 6
    assert item["gross_charge_cents"] == 240000, "approval decides nothing about the price yet"
    assert read_facility(base["facility"]["id"])["aggregate_gross_charge_cents"] == 240000


def test_rejection_leaves_reprice_pending_alone_while_a_sibling_approval_stands():
    """PRD §3.5: "It also carries one compensating cascade: when the target item's `price_status`
    is `REPRICE_PENDING` and no *other* `APPROVED` change request targets that item, the item's
    `price_status` reverts to `PRICE_STALE` and `ChargeItem.version` advances by 1."
    PRD §3.5: "It sets `status` to `REJECTED`, leaves `approved_by_user_id` null, and records the
    payload's `decision_note`."
    PRD §2.11: "`open_request_count` (the number of its change requests whose `status` is one of
    `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED` or `APPROVED`)"

    Design: Corner/state_machines/change_request_reject_cannot_revert_price_status_while_a_sibling_is_approved
    """
    base = _setup()
    request_a = create_change_request(
        base, base["item"]["id"], "PRICE_CHANGE",
        justification="First proposal against the same catheter line",
        proposed_cost_basis_cents=300000,
    )
    review_change_request(request_a["id"], ANALYST)
    approved_a = approve_change_request(request_a["id"], 5, APPROVER)
    assert approved_a["pinned_charge_item_version"] == 6
    assert read_item(base["item"]["id"])["price_status"] == "REPRICE_PENDING"

    request_b = create_change_request(
        base, base["item"]["id"], "PRICE_CHANGE",
        justification="Second, competing proposal for the same item",
        proposed_cost_basis_cents=150000,
    )
    review_change_request(request_b["id"], ANALYST)
    rejected = decide_change_request(
        request_b["id"], "REJECT", APPROVER,
        decision_note="Superseded by the approved request",
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["approved_by_user_id"] is None
    assert rejected["decision_note"] == "Superseded by the approved request"
    assert rejected["version"] == 3

    assert read_change_request(request_a["id"])["status"] == "APPROVED"
    item = read_item(base["item"]["id"])
    assert item["price_status"] == "REPRICE_PENDING", (
        "another APPROVED request still targets the item, so the revert is suppressed"
    )
    assert item["version"] == 6, "the suppressed cascade wrote nothing to the item"
    assert item["cost_basis_cents"] == 100000

    department = read_department(base["department"]["id"])
    assert department["open_request_count"] == 1, "only the APPROVED sibling still counts"


def test_the_rejection_response_is_a_well_formed_object_envelope():
    """PRD §2.2: "All successful API responses (those with 2xx status codes) follow this standard
    envelope format in their JSON body" — `meta`, `response_type` and `data`.
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list
    of resources."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the
    created or updated resource object in the data field."
    PRD §3.5: "Rejection, `UNDER_REVIEW → REJECTED`, is also an approver action, guarded only by
    `X-User-ID` differing from `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/state_machines/change_request_reject_cannot_revert_price_status_while_a_sibling_is_approved
    """
    base = _setup()
    request = create_change_request(
        base, base["item"]["id"], "PRICE_CHANGE",
        justification="Proposal that the committee will decline",
        proposed_cost_basis_cents=150000,
    )
    review_change_request(request["id"], ANALYST)
    resp = api_client.change_request_decision(
        request["id"], {"decision": "REJECT", "decision_note": "Declined on the merits"}, APPROVER
    )
    body = resp.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}
    assert body["response_type"] == "object"
    rejected = validate_success(resp, 200)
    assert rejected["status"] == "REJECTED"

    item = read_item(base["item"]["id"])
    assert item["price_status"] == "PRICED_CURRENT", (
        "the item never entered REPRICE_PENDING, so there is nothing for the cascade to revert"
    )
    assert item["version"] == 5
