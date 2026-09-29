"""The change-request revision cycle and the REJECTED branch of the UNDER_REVIEW fork."""
from test_helpers import (
    api_client, validate_success,
    setup_northgate_item_scenario,
    create_change_request, decide_change_request, resubmit_change_request,
    read_change_request, read_item, read_department,
    ANALYST, ANALYST2, APPROVER, ANALYST_USER_ID, ANALYST2_USER_ID,
)


def _submit(s):
    return create_change_request(
        s, s["item"]["id"], "PRICE_CHANGE",
        justification="Reagent vendor cost increase effective Q4 2026",
        proposed_cost_basis_cents=70000,
    )


def test_two_revision_rounds_clear_the_reviewer_and_recompute_the_projection():
    """PRD §3.5: "On success `revision_round` increases by 1, the payload's `justification`
    and any supplied `proposed_cost_basis_cents`, `proposed_revenue_code_id` and
    `proposed_description` overwrite the stored values, `projected_gross_charge_cents` and
    `projected_markup_ratio_bp` are recomputed, `reviewed_by_user_id` is cleared to null so
    that a fresh review decision is mandatory, and `status` returns to `SUBMITTED`."
    PRD §3.5: "The full cycle is therefore `UNDER_REVIEW → CHANGES_REQUESTED → SUBMITTED →
    UNDER_REVIEW`."
    PRD §3.5: "It records `reviewed_by_user_id` from `X-User-ID` and copies the payload's
    `decision_note` onto the request."
    PRD §3.5: "From `UNDER_REVIEW` the reviewer of record may bounce the request back,
    `UNDER_REVIEW → CHANGES_REQUESTED`, on the single precondition that `X-User-ID` equal the
    recorded `reviewed_by_user_id` — only the reviewer who took the request may return it,
    and anyone else receives `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/non_linear_state_machine/non_linear_state_machine__change_request_two_round_revision_cycle_then_reject_branch
    """
    s = setup_northgate_item_scenario(reprice=True)
    cr = _submit(s)
    assert cr["revision_round"] == 0
    assert cr["projected_gross_charge_cents"] == 168000, (
        f"70000 cents at 24000bp is 168000, got {cr['projected_gross_charge_cents']}"
    )

    round1 = decide_change_request(cr["id"], "REVIEW", ANALYST,
                                  decision_note="round 1 review opened")
    assert round1["status"] == "UNDER_REVIEW"
    assert round1["reviewed_by_user_id"] == ANALYST_USER_ID

    bounced = decide_change_request(cr["id"], "REQUEST_CHANGES", ANALYST,
                                   decision_note="supply cost documentation is incomplete")
    assert bounced["status"] == "CHANGES_REQUESTED"

    resub1 = resubmit_change_request(
        cr["id"], s["manager_headers"],
        justification="Attached vendor invoice; revised cost basis to 90000 cents",
        proposed_cost_basis_cents=90000,
    )
    assert resub1["status"] == "SUBMITTED"
    assert resub1["revision_round"] == 1
    assert resub1["reviewed_by_user_id"] is None, (
        "the resubmit must clear the reviewer so a fresh review is mandatory"
    )
    assert resub1["projected_gross_charge_cents"] == 216000

    round2 = decide_change_request(cr["id"], "REVIEW", ANALYST2,
                                   decision_note="round 2 review opened by a second analyst")
    assert round2["reviewed_by_user_id"] == ANALYST2_USER_ID, (
        "a different analyst may take the request on the second round"
    )
    decide_change_request(cr["id"], "REQUEST_CHANGES", ANALYST2,
                         decision_note="cost basis still unsupported at this magnitude")

    resub2 = resubmit_change_request(
        cr["id"], s["manager_headers"],
        justification="Final revision: fully loaded cost basis is 260000 cents per assay",
        proposed_cost_basis_cents=260000,
    )
    assert resub2["revision_round"] == 2
    assert resub2["projected_gross_charge_cents"] == 220000, (
        "the 18000bp band gives 468000 but the market cap of 220000 wins: got "
        f"{resub2['projected_gross_charge_cents']}"
    )
    assert resub2["projected_markup_ratio_bp"] == 8462, (
        "the DRAFT item contributes nothing to the snapshot, so the ratio is "
        f"220000 * 10000 / 260000 = 8462, got {resub2['projected_markup_ratio_bp']}"
    )


def test_reject_branch_records_no_approver_and_leaves_the_charge_item_untouched():
    """PRD §3.5: "Rejection, `UNDER_REVIEW → REJECTED`, is also an approver action, guarded
    only by `X-User-ID` differing from `submitted_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`). It sets `status` to `REJECTED`, leaves
    `approved_by_user_id` null, and records the payload's `decision_note`."
    PRD §3.5: "It also carries one compensating cascade: when the target item's
    `price_status` is `REPRICE_PENDING` and no *other* `APPROVED` change request targets that
    item, the item's `price_status` reverts to `PRICE_STALE` and `ChargeItem.version`
    advances by 1."
    PRD §2.11: "`open_request_count` (the number of its change requests whose `status` is one
    of `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED` or `APPROVED`)"

    Design: Difficulty/non_linear_state_machine/non_linear_state_machine__change_request_two_round_revision_cycle_then_reject_branch
    """
    s = setup_northgate_item_scenario(reprice=True)
    cr = _submit(s)

    decide_change_request(cr["id"], "REVIEW", ANALYST, decision_note="round 1 opened")
    decide_change_request(cr["id"], "REQUEST_CHANGES", ANALYST, decision_note="incomplete")
    resubmit_change_request(cr["id"], s["manager_headers"],
                           justification="Attached vendor invoice; 90000 cents",
                           proposed_cost_basis_cents=90000)
    decide_change_request(cr["id"], "REVIEW", ANALYST2, decision_note="round 2 opened")
    decide_change_request(cr["id"], "REQUEST_CHANGES", ANALYST2,
                         decision_note="still unsupported")
    resubmit_change_request(cr["id"], s["manager_headers"],
                           justification="Final revision: 260000 cents per assay",
                           proposed_cost_basis_cents=260000)
    decide_change_request(cr["id"], "REVIEW", ANALYST,
                         decision_note="round 3 re-opened by the original analyst")

    rejected = validate_success(
        api_client.change_request_decision(
            cr["id"],
            {"decision": "REJECT",
             "decision_note": "markup not defensible at the proposed cost basis"},
            APPROVER,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["approved_by_user_id"] is None, (
        "the reject branch never records an approver"
    )
    assert rejected["reviewed_by_user_id"] == ANALYST_USER_ID
    assert rejected["revision_round"] == 2
    assert rejected["projected_gross_charge_cents"] == 220000
    assert rejected["projected_markup_ratio_bp"] == 8462
    assert rejected["version"] == 9, (
        "create 1 plus eight successful transitions: got " f"{rejected['version']}"
    )
    assert read_change_request(cr["id"])["status"] == "REJECTED"

    item = read_item(s["item"]["id"])
    assert item["price_status"] == "PRICED_CURRENT", (
        "the item was never moved to REPRICE_PENDING, so the reject cascade is inert"
    )
    assert item["cost_basis_cents"] == 60000
    assert item["gross_charge_cents"] == 144000
    assert item["version"] == 2

    department = read_department(s["department"]["id"])
    assert department["open_request_count"] == 0, (
        "REJECTED is not one of the four open statuses"
    )
