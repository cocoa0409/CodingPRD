"""Write-off requests: tiers, fiscal gates, approval hierarchy, revise/rescind (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    approve_write_off,
    create_write_off_payload,
    director_headers,
    get_denial,
    make_queued_denial,
    make_write_off,
    manager_headers,
    reject_write_off_payload,
    rescind_write_off_payload,
    revise_write_off_payload,
    setup_catalog,
    specialist_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

TIER_RULE_CITE = (
    'PRD §3.6: "Second, the `approval_tier` is `STANDARD` when the gross exposure is 2500000 '
    'cents or less and `ESCALATED` otherwise — the tier is always keyed on the gross '
    'exposure, never on the recommended amount."'
)
APPROVAL_ORDER_CITE = (
    'PRD §3.6: "The request must be in `PENDING_MANAGER` or `ESCALATED_DIRECTOR`, else '
    '`ERR_WRITE_OFF_NOT_PENDING`. The denial must be in `QUEUED`, `IN_APPEAL`, '
    '`CLOSED_EXHAUSTED`, or `CLOSED_EXPIRED` — approving against a denial in any other '
    'status, including `RESOLVED_PAID`, fails with `ERR_DENIAL_INVALID_STATE`. The '
    'approver\'s `X-User-ID` must differ from `requested_by_user_id`, else '
    '`ERR_SEGREGATION_OF_DUTIES`. The requested amount is re-checked against the denial\'s '
    'current open balance, else `ERR_AMOUNT_EXCEEDS_OPEN_BALANCE`. Finally, authority: a '
    '`DenialsManager` may approve a `STANDARD`-tier request, while an `ESCALATED`-tier '
    'request requires a `RevenueCycleDirector`, else `ERR_APPROVAL_LIMIT_EXCEEDED`; a '
    'director may approve either tier."'
)


def _queued_pair(api, catalog, claims_and_amounts):
    """Two queued denials on the shared catalog. Returns {claim: denial}."""
    out = {}
    for claim, denied, billed in claims_and_amounts:
        out[claim] = make_queued_denial(
            catalog["payer"]["id"], catalog["code"]["id"],
            claim_number=claim, denied_amount_cents=denied, billed_amount_cents=billed,
        )
    return out


def test_writeoff_tier_derivation_standard_vs_escalated(api):
    """PRD §3.6: "Second, the `approval_tier` is `STANDARD` when the gross exposure is
    2500000 cents or less and `ESCALATED` otherwise — the tier is always keyed on the gross
    exposure, never on the recommended amount."
    PRD §3.6: "The request's initial `status` is `PENDING_MANAGER` for the `STANDARD` tier
    and `ESCALATED_DIRECTOR` for the `ESCALATED` tier, with `decision_reason` empty until a
    decision is recorded, and a `WRITE_OFF_REQUESTED` event is appended."

    Design: Difficulty/combinatorial_formula/writeoff_tier_exposure_evaluation_order
    """
    catalog = setup_catalog(levels=(1,))
    denials = _queued_pair(api, catalog, [
        ("CLM-401", 1500000, 1600000),
        ("CLM-402", 4000000, 4100000),
    ])
    w1 = make_write_off(denials["CLM-401"]["id"], 1500000, requester_user_id="spec-7")
    assert w1["approval_tier"] == "STANDARD"
    assert w1["status"] == "PENDING_MANAGER"
    w2 = make_write_off(denials["CLM-402"]["id"], 4000000,
                        reason_code="APPEALS_EXHAUSTED", requester_user_id="spec-7")
    assert w2["approval_tier"] == "ESCALATED"
    assert w2["status"] == "ESCALATED_DIRECTOR"


def test_writeoff_projection_uses_tier_multiplier(api):
    """PRD §3.6: "Third, a tier multiplier of 1.0 for `STANDARD` or 0.75 for `ESCALATED` is
    combined with the payer's overturn rate at the next appeal level, using exactly the rate
    and fallback ladder of the recovery projection in §3.3. Fourth, `projected_recovery_cents`
    is the gross exposure multiplied by that rate and the tier multiplier, rounded half-up to
    whole cents. Fifth, `recommended_writeoff_cents` is the gross exposure minus the
    projected recovery."
    PRD §3.3: "if the payer has no resolved appeals at all, use the default rate 0.50"

    Design: Difficulty/combinatorial_formula/writeoff_tier_exposure_evaluation_order
    """
    catalog = setup_catalog(levels=(1,))
    denials = _queued_pair(api, catalog, [
        ("CLM-401", 1500000, 1600000),
        ("CLM-402", 4000000, 4100000),
    ])
    w1 = make_write_off(denials["CLM-401"]["id"], 1500000, requester_user_id="spec-7")
    assert w1["projected_recovery_cents"] == 750000   # 1500000 * 0.50 * 1.0
    assert w1["recommended_writeoff_cents"] == 750000
    w2 = make_write_off(denials["CLM-402"]["id"], 4000000,
                        reason_code="APPEALS_EXHAUSTED", requester_user_id="spec-7")
    assert w2["projected_recovery_cents"] == 1500000  # 4000000 * 0.50 * 0.75
    assert w2["recommended_writeoff_cents"] == 2500000


def test_manager_approval_limit_exact_boundary_standard(api):
    """PRD §3.6: "Second, the `approval_tier` is `STANDARD` when the gross exposure is
    2500000 cents or less and `ESCALATED` otherwise — the tier is always keyed on the gross
    exposure, never on the recommended amount."
    PRD §3.6: "When the approval brings the open balance to zero, the denial resolves to
    `RESOLVED_WRITTEN_OFF` — from `QUEUED` or `IN_APPEAL` this also clears
    `next_appeal_deadline` to null, while a denial approved out of `CLOSED_EXHAUSTED` or
    `CLOSED_EXPIRED` already has no deadline — and its queue priority recomputes."

    Design: Difficulty/boundary_precision_check/manager_approval_limit_exact_boundary
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-1101", denied_amount_cents=2500000, billed_amount_cents=2600000,
    )
    request = make_write_off(denial["id"], 2500000, requester_user_id="spec-1")
    assert request["approval_tier"] == "STANDARD", "2500000 exactly is within the manager limit"
    approved = approve_write_off(request["id"], manager_headers("mgr-1"))
    assert approved["status"] == "APPROVED"
    denial = get_denial(denial["id"])
    assert denial["status"] == "RESOLVED_WRITTEN_OFF"
    assert denial["written_off_cents"] == 2500000
    assert denial["open_balance_cents"] == 0


def test_manager_approval_limit_one_cent_over_escalated(api):
    """PRD §3.6: "Finally, authority: a `DenialsManager` may approve a `STANDARD`-tier
    request, while an `ESCALATED`-tier request requires a `RevenueCycleDirector`, else
    `ERR_APPROVAL_LIMIT_EXCEEDED`; a director may approve either tier."

    Design: Difficulty/boundary_precision_check/manager_approval_limit_exact_boundary
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-1102", denied_amount_cents=2500001, billed_amount_cents=2600001,
    )
    request = make_write_off(denial["id"], 2500001, requester_user_id="spec-1")
    assert request["approval_tier"] == "ESCALATED", "2500001 is one cent over the limit"
    resp = api.approve_write_off(request["id"], manager_headers("mgr-1"))
    validate_error(resp, ApiErrorId.ERR_APPROVAL_LIMIT_EXCEEDED, expected_status=403)
    after = validate_success(api.get_write_off_request(request["id"], manager_headers("mgr-1")))
    assert after["status"] == "ESCALATED_DIRECTOR", "no partial approval"


def test_writeoff_approve_state_beats_fiscal(api):
    """PRD §2.8: "When a request violates several rules at once, the server evaluates the
    following gates in the order listed and returns the error from the first gate that fails
    — a lower-numbered gate always wins over a later one."
    PRD §3.6: "The request must be in `PENDING_MANAGER` or `ESCALATED_DIRECTOR`, else
    `ERR_WRITE_OFF_NOT_PENDING`."

    Design: Difficulty/priority_pair_validation_conflict/writeoff_approve_state_beats_fiscal
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-801", denied_amount_cents=4000000, billed_amount_cents=4100000,
    )
    request = make_write_off(denial["id"], 4000000, reason_code="APPEALS_EXHAUSTED",
                             requester_user_id="spec-7")
    assert request["status"] == "ESCALATED_DIRECTOR"
    validate_success(
        api.reject_write_off(
            request["id"], reject_write_off_payload("Insufficient documentation of exhaustion"),
            director_headers("dir-1"),
        )
    )
    resp = api.approve_write_off(request["id"], manager_headers("mgr-2"))
    err = validate_error(resp, ApiErrorId.ERR_WRITE_OFF_NOT_PENDING, expected_status=409)
    assert err["error_id"] != ApiErrorId.ERR_APPROVAL_LIMIT_EXCEEDED


def test_writeoff_approve_state_failure_leaves_request_rejected(api):
    """PRD §3.6: "**Rejection** is available to both `DenialsManager` and
    `RevenueCycleDirector` from either pending status (else `ERR_WRITE_OFF_NOT_PENDING`). The
    supplied `reason` is stored as `decision_reason`, `decided_by_user_id` and `decided_at`
    are stamped, and a `WRITE_OFF_REJECTED` event is appended."
    PRD §3.6: "The request must be in `PENDING_MANAGER` or `ESCALATED_DIRECTOR`, else
    `ERR_WRITE_OFF_NOT_PENDING`."

    Design: Difficulty/priority_pair_validation_conflict/writeoff_approve_state_beats_fiscal
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-801", denied_amount_cents=4000000, billed_amount_cents=4100000,
    )
    request = make_write_off(denial["id"], 4000000, reason_code="APPEALS_EXHAUSTED",
                             requester_user_id="spec-7")
    rejected = validate_success(
        api.reject_write_off(
            request["id"], reject_write_off_payload("Insufficient documentation of exhaustion"),
            director_headers("dir-1"),
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["decision_reason"] == "Insufficient documentation of exhaustion"
    validate_error(
        api.approve_write_off(request["id"], manager_headers("mgr-2")),
        ApiErrorId.ERR_WRITE_OFF_NOT_PENDING,
    )
    after = validate_success(api.get_write_off_request(request["id"], manager_headers("mgr-2")))
    assert after["status"] == "REJECTED"


def test_writeoff_approve_sod_beats_fiscal(api):
    """PRD §2.8: "When a request violates several rules at once, the server evaluates the
    following gates in the order listed and returns the error from the first gate that fails
    — a lower-numbered gate always wins over a later one."
    PRD §2.8: "**Segregation of duties and ownership.** Write-off approval by the requester,
    and task verification by the implementer, are `ERR_SEGREGATION_OF_DUTIES` (403);
    write-off revision by anyone other than the original requester is `ERR_NOT_REQUEST_OWNER`
    (403)."

    Design: Difficulty/priority_pair_validation_conflict/writeoff_approve_sod_beats_fiscal
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-911", denied_amount_cents=4000000, billed_amount_cents=4100000,
    )
    request = make_write_off(denial["id"], 4000000, reason_code="APPEALS_EXHAUSTED",
                             requester_user_id="spec-9")
    assert request["status"] == "ESCALATED_DIRECTOR"
    # Approver carries the manager role but the same user id as the requester.
    resp = api.approve_write_off(request["id"], manager_headers("spec-9"))
    err = validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    assert err["error_id"] != ApiErrorId.ERR_APPROVAL_LIMIT_EXCEEDED


def test_writeoff_self_approve_leaves_request_pending(api):
    """PRD §3.6: "The approver's `X-User-ID` must differ from `requested_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/writeoff_approve_sod_beats_fiscal
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-911", denied_amount_cents=4000000, billed_amount_cents=4100000,
    )
    request = make_write_off(denial["id"], 4000000, reason_code="APPEALS_EXHAUSTED",
                             requester_user_id="spec-9")
    validate_error(
        api.approve_write_off(request["id"], manager_headers("spec-9")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    after = validate_success(api.get_write_off_request(request["id"], manager_headers("mgr-1")))
    assert after["status"] == "ESCALATED_DIRECTOR"


def test_writeoff_ceiling_checked_before_balance(api, specialist_headers):
    """PRD §3.6: "The fiscal gates of §2.8 then apply in their pinned sub-order: an amount
    above the system ceiling of 10000000 cents fails with `ERR_WRITE_OFF_EXCEEDS_CEILING`,
    and only then an amount above the denial's current `open_balance_cents` fails with
    `ERR_AMOUNT_EXCEEDS_OPEN_BALANCE`."

    Design: Corner/validations/writeoff_ceiling_checked_before_balance
    """
    catalog = setup_catalog(levels=())
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2302", denied_amount_cents=4000000, billed_amount_cents=4100000,
    )
    resp = api.create_write_off_request(
        create_write_off_payload(denial["id"], 10000001, reason_code="OTHER"),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_WRITE_OFF_EXCEEDS_CEILING, expected_status=422)


def test_writeoff_exceeds_open_balance_rejected(api, specialist_headers):
    """PRD §3.6: "The fiscal gates of §2.8 then apply in their pinned sub-order: an amount
    above the system ceiling of 10000000 cents fails with `ERR_WRITE_OFF_EXCEEDS_CEILING`,
    and only then an amount above the denial's current `open_balance_cents` fails with
    `ERR_AMOUNT_EXCEEDS_OPEN_BALANCE`."

    Design: Corner/validations/writeoff_exceeds_open_balance_rejected
    """
    catalog = setup_catalog(levels=())
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2303", denied_amount_cents=4000000, billed_amount_cents=4100000,
    )
    resp = api.create_write_off_request(
        create_write_off_payload(denial["id"], 4000001, reason_code="OTHER"),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_OPEN_BALANCE, expected_status=422)
    rows, meta = validate_paginated(
        api.list_write_off_requests(specialist_headers, params={"denial_case_id": denial["id"]})
    )
    assert meta["total_count"] == 0, "no write-off request is created"


def test_writeoff_pending_then_duplicate_rejected(api):
    """PRD §3.6: "A denial may carry at most one pending request — one in `PENDING_MANAGER`
    or `ESCALATED_DIRECTOR` — and a second attempt is rejected with
    `ERR_WRITE_OFF_ALREADY_PENDING`."

    Design: Corner/validations/writeoff_pending_then_duplicate_rejected
    """
    catalog = setup_catalog(levels=())
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2311",
    )
    first = make_write_off(denial["id"], 100000, requester_user_id="spec-1")
    resp = api.create_write_off_request(
        create_write_off_payload(denial["id"], 50000, reason_code="OTHER"),
        specialist_headers("spec-2"),
    )
    validate_error(resp, ApiErrorId.ERR_WRITE_OFF_ALREADY_PENDING, expected_status=409)
    after = validate_success(api.get_write_off_request(first["id"], specialist_headers("spec-1")))
    assert after["status"] == "PENDING_MANAGER"
    assert after["requested_amount_cents"] == 100000


def test_writeoff_revise_cycle_retiers(api):
    """PRD §3.6: "Only from `REJECTED` (else `ERR_WRITE_OFF_NOT_PENDING`), and only when the
    caller's `X-User-ID` equals `requested_by_user_id` (else `ERR_NOT_REQUEST_OWNER`), the
    specialist supplies a new `requested_amount_cents` that must again respect both the open
    balance and the 10000000-cent ceiling. The amount updates and the tier,
    `projected_recovery_cents`, and `recommended_writeoff_cents` are recomputed through the
    same fixed derivation; the request re-enters the pipeline at `PENDING_MANAGER` when the
    new tier is `STANDARD` or at `ESCALATED_DIRECTOR` when it is `ESCALATED`, appending a
    `WRITE_OFF_REVISED` event."

    Design: Corner/state_machines/writeoff_revise_cycle_retiers
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2108", denied_amount_cents=4000000, billed_amount_cents=4100000,
    )
    request = make_write_off(denial["id"], 4000000, reason_code="APPEALS_EXHAUSTED",
                             requester_user_id="spec-7")
    validate_success(
        api.reject_write_off(
            request["id"], reject_write_off_payload("Amount too large for current evidence"),
            director_headers("dir-1"),
        )
    )
    revised = validate_success(
        api.revise_write_off(
            request["id"], revise_write_off_payload(1000000), specialist_headers("spec-7"),
        )
    )
    assert revised["status"] == "PENDING_MANAGER"
    assert revised["approval_tier"] == "STANDARD"
    assert revised["projected_recovery_cents"] == 500000   # 1000000 * 0.50 * 1.0
    assert revised["recommended_writeoff_cents"] == 500000


def test_writeoff_rescind_restores_denial(api, director_headers):
    """PRD §3.6: "The denial returns to exactly the status captured in
    `denial_status_before`: a denial restored to `QUEUED` regains its level-1 filing deadline
    in `next_appeal_deadline` and recomputes its priority; one restored to `IN_APPEAL` has
    its deadline rebuilt from the appeal-deadline schedule using the latest outcome date and
    likewise recomputes priority; one restored to `CLOSED_EXHAUSTED` or `CLOSED_EXPIRED`
    keeps a null deadline and simply rejoins the closed population."
    PRD §3.6: "only from `APPROVED` (else `ERR_WRITE_OFF_NOT_PENDING`), a
    `RevenueCycleDirector` supplies a `reason`, which is stored in `decision_reason`, and the
    request settles in its terminal `RESCINDED` status. The denial's `written_off_cents`
    decreases by the rescinded amount, `open_balance_cents` recomputes per §2.9"

    Design: Corner/state_machines/writeoff_rescind_restores_denial
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2109", denied_amount_cents=100000, billed_amount_cents=120000,
    )
    request = make_write_off(denial["id"], 100000, requester_user_id="spec-1")
    approve_write_off(request["id"], manager_headers("mgr-1"))
    assert get_denial(denial["id"])["status"] == "RESOLVED_WRITTEN_OFF"
    rescinded = validate_success(
        api.rescind_write_off(
            request["id"], rescind_write_off_payload("Payer agreed to reprocess after all"),
            director_headers,
        )
    )
    assert rescinded["status"] == "RESCINDED"
    denial = get_denial(denial["id"])
    assert denial["status"] == "QUEUED"
    assert denial["written_off_cents"] == 0
    assert denial["open_balance_cents"] == 100000
    assert denial["next_appeal_deadline"] == "2026-09-30"


def test_immediate_visibility_after_writeoff_approve(api):
    """PRD §2.5: "All mutations are immediately consistent: a change applied by a request is
    visible in that request's own response body and in every subsequent read."
    PRD §3.6: "On approval the request snapshots the denial's current status into
    `denial_status_before`, stamps `decided_by_user_id` and `decided_at`, adds the approved
    amount to the denial's `written_off_cents`, and appends a `WRITE_OFF_APPROVED` event"

    Design: Corner/consistency_model/immediate_visibility_after_writeoff_approve
    """
    catalog = setup_catalog(levels=())
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2701", denied_amount_cents=100000, billed_amount_cents=120000,
    )
    request = make_write_off(denial["id"], 100000, requester_user_id="spec-1")
    approved = validate_success(
        api.approve_write_off(request["id"], manager_headers("mgr-1"))
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == "mgr-1"
    denial = get_denial(denial["id"])
    assert denial["written_off_cents"] == 100000
    assert denial["status"] == "RESOLVED_WRITTEN_OFF"


def test_specialist_cannot_approve_writeoff(api):
    """PRD §2.8: "**Authorization.** The authenticated role must appear in the endpoint's
    authorized role list, else `ERR_FORBIDDEN` (403). Applies to every endpoint."
    PRD §4: "| POST | `/rcm/write-off-requests/{id}/approve` | Approve a pending write-off
    request within the actor's tier authority | DenialsManager, RevenueCycleDirector |"

    Design: Corner/rbac/specialist_cannot_approve_writeoff
    """
    catalog = setup_catalog(levels=())
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2503", denied_amount_cents=100000, billed_amount_cents=120000,
    )
    request = make_write_off(denial["id"], 100000, requester_user_id="spec-1")
    resp = api.approve_write_off(request["id"], specialist_headers("spec-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    after = validate_success(api.get_write_off_request(request["id"], specialist_headers("spec-2")))
    assert after["status"] == "PENDING_MANAGER"
