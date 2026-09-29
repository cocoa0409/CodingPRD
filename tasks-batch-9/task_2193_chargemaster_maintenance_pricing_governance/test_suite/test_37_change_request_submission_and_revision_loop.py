"""The change request's initial state and the hard stop at the third accepted resubmit."""
from test_helpers import (
    api_client, validate_success, validate_error, factories, ApiErrorId,
    setup_base, create_item, create_change_request, read_change_request,
    review_change_request, decide_change_request, resubmit_change_request,
    read_department, set_clock,
    assert_change_request,
    ANALYST, ANALYST_USER_ID, MANAGER_USER_ID,
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
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    base["item"] = create_item(base, **ITEM)
    return base


def test_a_fresh_request_is_submitted_at_revision_round_zero_with_its_dry_run_computed():
    """PRD §3.5: "Submission creates the request in `SUBMITTED` with `revision_round` at 0,
    `submitted_by_user_id` set from `X-User-ID`, `version` 1, and `reviewed_by_user_id`,
    `approved_by_user_id`, `pinned_charge_item_version` and `decision_note` all null. Two dry-run
    figures are computed immediately: `projected_gross_charge_cents`, from the gross-charge
    arithmetic of §3.2 applied to the proposed inputs, and `projected_markup_ratio_bp`, from the
    markup-compliance projection."
    PRD §3.5: "The owning department's `open_request_count` is then recomputed."
    PRD §3.2: "First, the item under evaluation is *excluded* from the facility snapshot: the
    snapshot numerator is the facility's `aggregate_gross_charge_cents` less the item's own
    `gross_charge_cents` if and only if the item's `lifecycle_status` is `ACTIVE` (and less nothing
    otherwise), and the snapshot denominator is the facility's `aggregate_cost_basis_cents` less the
    item's own `cost_basis_cents` under the same condition."

    Design: Corner/state_machines/change_request_initial_state_is_submitted_with_revision_round_zero
    """
    base = _setup()
    resp = api_client.create_change_request(
        factories.create_change_request_payload(
            base["department"]["id"], base["item"]["id"], "PRICE_CHANGE",
            justification="Supply contract renegotiated upward in Q3",
            proposed_cost_basis_cents=200000,
            proposed_description="CARDIAC CATH BASIC V2",
        ),
        base["manager_headers"],
    )
    request = validate_success(resp, 201)
    assert_change_request(request)
    assert request["status"] == "SUBMITTED"
    assert request["revision_round"] == 0
    assert request["submitted_by_user_id"] == MANAGER_USER_ID
    assert request["reviewed_by_user_id"] is None
    assert request["approved_by_user_id"] is None
    assert request["pinned_charge_item_version"] is None
    assert request["decision_note"] is None
    assert request["projected_gross_charge_cents"] == 480000, (
        "a proposed cost of 200000 sits in the 24000bp band; the 60000 floor and 990000 cap are "
        "both inert"
    )
    assert request["projected_markup_ratio_bp"] == 24000, (
        "the DRAFT target contributes nothing to the snapshot, so the ratio is 480000/200000"
    )
    assert request["version"] == 1

    department = read_department(base["department"]["id"])
    assert department["open_request_count"] == 1


def test_the_third_resubmit_is_the_last_one_accepted():
    """PRD §3.5: "Two preconditions guard it: `X-User-ID` must equal the owning department's
    `manager_user_id` (`ERR_DEPARTMENT_SCOPE_VIOLATION`), and `revision_round` must be strictly
    less than 3 (`ERR_REVISION_LIMIT_EXCEEDED`, HTTP 409). Read that boundary carefully — a request
    already at `revision_round` 3 is refused, while a request at `revision_round` 2 succeeds and
    lands at 3; the third resubmit is the last accepted one."
    PRD §3.5: "On success `revision_round` increases by 1, the payload's `justification` and any
    supplied `proposed_cost_basis_cents`, `proposed_revenue_code_id` and `proposed_description`
    overwrite the stored values, `projected_gross_charge_cents` and `projected_markup_ratio_bp` are
    recomputed, `reviewed_by_user_id` is cleared to null so that a fresh review decision is
    mandatory, and `status` returns to `SUBMITTED`."
    PRD §2.4: "`version` (an integer that starts at 1 on creation and increases by exactly 1 on
    every mutation of that row)"

    Design: Corner/state_machines/change_request_fourth_resubmit_at_revision_round_three_rejected
    """
    base = _setup()
    request = create_change_request(
        base, base["item"]["id"], "PRICE_CHANGE",
        justification="Supply cost drifted; please reprice",
        proposed_cost_basis_cents=120000,
    )
    assert request["revision_round"] == 0

    rounds = []
    for attempt in range(3):
        review_change_request(request["id"], ANALYST)
        decide_change_request(request["id"], "REQUEST_CHANGES", ANALYST,
                              decision_note="Attach the signed contract page.")
        resubmitted = resubmit_change_request(
            request["id"], base["manager_headers"],
            justification=f"Revision {attempt + 1} of the same price change request",
            proposed_cost_basis_cents=120000,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["reviewed_by_user_id"] is None, (
            "each resubmit clears the reviewer so a fresh review is mandatory"
        )
        rounds.append(resubmitted["revision_round"])
    assert rounds == [1, 2, 3], "three accepted resubmits, one round each"

    review_change_request(request["id"], ANALYST)
    bounced = decide_change_request(request["id"], "REQUEST_CHANGES", ANALYST,
                                   decision_note="Still short of the committee's bar.")
    assert bounced["status"] == "CHANGES_REQUESTED"
    assert bounced["revision_round"] == 3
    assert bounced["version"] == 12, (
        "one create plus eleven decisions and resubmits, each a single mutation"
    )

    validate_error(
        api_client.resubmit_change_request(
            request["id"],
            {"justification": "Fourth attempt at the same price change request",
             "proposed_cost_basis_cents": 120000},
            base["manager_headers"],
        ),
        ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value,
        409,
    )

    final = read_change_request(request["id"])
    assert final["revision_round"] == 3, "the refused fourth resubmit incremented nothing"
    assert final["status"] == "CHANGES_REQUESTED"
    assert final["version"] == 12
    assert final["reviewed_by_user_id"] == ANALYST_USER_ID
