"""One request walked through the revision loop, with every off-ladder call refused by its own code."""
from test_helpers import (
    api_client, validate_error, ApiErrorId,
    setup_base, create_active_item, create_change_request, read_change_request,
    decide_change_request, review_change_request, approve_change_request,
    resubmit_change_request,
    item_lifecycle, read_item, read_department, read_facility, set_clock,
    ANALYST, ANALYST2, APPROVER, ANALYST_USER_ID, APPROVER_USER_ID,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-REQERR",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                         "allowed_revenue_code_values": []},
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)


def test_implement_reports_the_item_price_state_while_decisions_and_resubmits_report_the_request():
    """PRD §2.9: "13. Entity-state admissibility, one rank shared by nine mutually exclusive rules
    distinguished by target entity, so exactly one can fire for a given request:
    `ERR_INVALID_ITEM_LIFECYCLE_STATE` (409) for item lifecycle and reprice;
    `ERR_INVALID_ITEM_PRICE_STATE` (409) for change-request implementation;
    `ERR_INVALID_REQUEST_STATE` (409) for change-request decisions and resubmits;
    `ERR_INVALID_CYCLE_STATE` (409) for cycle lifecycle actions and entry creation;
    `ERR_INVALID_ENTRY_STATE` (409) for entry disposition; `ERR_INVALID_BATCH_STATE` (409) for batch
    reconcile, batch lifecycle and line append; `ERR_INVALID_FINDING_STATE` (409) for finding
    disposition; `ERR_INVALID_FILE_STATE` (409) for transparency-file lifecycle; and
    `ERR_INVALID_ANALYSIS_STATE` (409) for analysis sign-off."
    PRD §3.4: "Attempting to implement a `PRICE_CHANGE` request against an item whose `price_status` is
    not `REPRICE_PENDING` is `ERR_INVALID_ITEM_PRICE_STATE` (409)."
    PRD §3.5: "On success `revision_round` increases by 1, the payload's `justification` and any supplied
    `proposed_cost_basis_cents`, `proposed_revenue_code_id` and `proposed_description` overwrite the
    stored values, `projected_gross_charge_cents` and `projected_markup_ratio_bp` are recomputed,
    `reviewed_by_user_id` is cleared to null so that a fresh review decision is mandatory, and `status`
    returns to `SUBMITTED`."
    PRD §3.5: "For `PRICE_CHANGE` and `NEW_ITEM`, the target item's `price_status` moves to
    `REPRICE_PENDING` and `ChargeItem.version` advances by 1; `pinned_charge_item_version` is set to the
    *post-bump* version so that the later implementation can match it."
    PRD §3.5: "Three preconditions apply: the facility must not be `FROZEN` (`ERR_FACILITY_FROZEN`);
    `pinned_charge_item_version` must still equal the live `ChargeItem.version`, otherwise
    `ERR_PINNED_VERSION_STALE` (409) — and when that fails the pin is *not* refreshed and the request
    remains `APPROVED`, with nothing mutated; and for a `DEACTIVATION` request the target item must
    additionally satisfy the deactivation preconditions of §3.8, which surface here as
    `ERR_ITEM_IN_OPEN_BATCH` (409)."

    Design: Corner/errors/request_state_ladder_rejects_early_implement_early_resubmit_and_a_stale_pin
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    manager = base["manager_headers"]
    item = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                              code_type="CPT", code_value="93458", cost_basis_cents=100000,
                              medicare_rate_cents=50000, market_p75_cents=900000,
                              effective_from="2026-09-01T00:00:00Z")
    assert item["version"] == 5, "create, reprice, submit, approve, activate"
    assert item["price_status"] == "PRICED_CURRENT"

    request = create_change_request(base, item["id"], "PRICE_CHANGE",
                                    justification="Vendor raised the tray cost this quarter",
                                    proposed_cost_basis_cents=200000)
    assert request["status"] == "SUBMITTED"
    assert request["revision_round"] == 0
    assert request["projected_gross_charge_cents"] == 480000
    assert request["projected_markup_ratio_bp"] == 24000
    assert request["pinned_charge_item_version"] is None

    validate_error(
        api_client.implement_change_request(request["id"], ANALYST,
                                            {"implementation_note": "Too early"}),
        ApiErrorId.ERR_INVALID_ITEM_PRICE_STATE.value, 409,
    )
    validate_error(
        api_client.resubmit_change_request(
            request["id"], {"justification": "Nothing was requested to change yet"}, manager),
        ApiErrorId.ERR_INVALID_REQUEST_STATE.value, 409,
    )

    reviewed = review_change_request(request["id"], ANALYST,
                                     decision_note="Cost evidence attached")
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["reviewed_by_user_id"] == ANALYST_USER_ID
    validate_error(
        api_client.change_request_decision(request["id"], {"decision": "REVIEW"}, ANALYST2),
        ApiErrorId.ERR_INVALID_REQUEST_STATE.value, 409,
    )

    bounced = decide_change_request(request["id"], "REQUEST_CHANGES", ANALYST,
                                    decision_note="Attach the vendor quote")
    assert bounced["status"] == "CHANGES_REQUESTED"

    resubmitted = resubmit_change_request(
        request["id"], manager, justification="Vendor quote attached as requested",
        proposed_cost_basis_cents=200000)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["reviewed_by_user_id"] is None

    assert review_change_request(request["id"], ANALYST,
                                 decision_note="Quote verified")["status"] == "UNDER_REVIEW"
    approved = approve_change_request(request["id"], 5, APPROVER,
                                      decision_note="Approved for implementation")
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == APPROVER_USER_ID
    assert approved["pinned_charge_item_version"] == 6, "the pin is the post-bump version"

    pending = read_item(item["id"])
    assert pending["version"] == 6
    assert pending["price_status"] == "REPRICE_PENDING"

    deactivated = item_lifecycle(item["id"], "DEACTIVATE", ANALYST)
    assert deactivated["lifecycle_status"] == "INACTIVE"
    assert deactivated["version"] == 7
    assert deactivated["price_status"] == "REPRICE_PENDING", (
        "DEACTIVATE moves only the lifecycle dimension, so the price gate still passes"
    )

    for attempt in range(2):
        validate_error(
            api_client.implement_change_request(
                request["id"], ANALYST,
                {"implementation_note": "Applying the approved cost"} if attempt == 0 else None),
            ApiErrorId.ERR_PINNED_VERSION_STALE.value, 409,
        )
        after = read_change_request(request["id"])
        assert after["status"] == "APPROVED"
        assert after["pinned_charge_item_version"] == 6, "a failed implement never refreshes the pin"

    validate_error(
        api_client.resubmit_change_request(
            request["id"], {"justification": "Trying to revive an approved request"}, manager),
        ApiErrorId.ERR_INVALID_REQUEST_STATE.value, 409,
    )

    untouched = read_item(item["id"])
    assert untouched["cost_basis_cents"] == 100000, "nothing was ever implemented"
    assert untouched["gross_charge_cents"] == 240000
    assert untouched["version"] == 7, "the three rejected calls mutated nothing"
    final = read_change_request(request["id"])
    assert final["revision_round"] == 1
    assert read_department(base["department"]["id"])["open_request_count"] == 1, (
        "an APPROVED request still counts as open"
    )
    assert read_facility(base["facility"]["id"])["active_item_count"] == 0
