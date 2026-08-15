"""The landlord's consent decision: guards, branches, OCC, and the join (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    B1,
    CLOCK,
    MGR,
    build_conditional_grant,
    build_consent_pending_transfer,
    build_granted_transfer,
    build_submitted_transfer,
    create_party,
    decide_consent,
    decide_payload,
    get_lease,
    get_review_fresh,
    get_transfer,
    list_conditions,
    make_landlord_headers,
    make_tenant_headers,
    respond_condition,
    set_clock,
    validate_error,
    validate_success,
)

DIFFERENTIAL_CENTS = 10752000  # (6400 - 5200) cents/RSF x 8960 certified RSF


def test_decide_after_deadline_returns_window_lapsed(api):
    """PRD §3.5: "the decision must arrive at or before the transfer's `consent_deadline` (`ERR_CONSENT_WINDOW_LAPSED`, HTTP 409 — a decision at exactly the deadline is accepted, while one strictly after it is rejected and the review locks pending the deemed-approval evaluation)"

    Design: Corner/validations/decide_after_deadline_returns_window_lapsed
    """
    ctx1 = build_submitted_transfer(clock=CLOCK["MONDAY_SUBMIT"])
    ctx2 = build_submitted_transfer(clock=CLOCK["MONDAY_SUBMIT"])

    set_clock(CLOCK["MONDAY_DEADLINE"])
    review1 = decide_consent(ctx1["consent_review"]["id"], ctx1["pl"]["id"], "GRANTED")
    assert review1["decision"] == "GRANTED", "a decision at exactly the deadline is accepted"

    set_clock(CLOCK["JUST_AFTER_DEADLINE"])
    cr2 = ctx2["consent_review"]
    resp = api.decide_consent_review(
        cr2["id"], decide_payload("GRANTED", cr2["version"]),
        make_landlord_headers(ctx2["pl"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_WINDOW_LAPSED, 409)
    assert get_review_fresh(cr2["id"])["decision"] == "PENDING"


def test_denial_without_reason_code_rejected(api):
    """PRD §3.5: "A `DENIED` decision without a `denial_reason_code`, or one citing `INSUFFICIENT_CREDIT` while the credit review's `outcome` is not `FAIL`, is rejected with `ERR_DENIAL_REASON_INVALID` (HTTP 422): the leases administered here permit denial only on enumerated commercially-reasonable grounds."

    Design: Corner/errors/denial_without_reason_code_rejected
    """
    ctx = build_submitted_transfer()
    cr = ctx["consent_review"]
    resp = api.decide_consent_review(
        cr["id"], decide_payload("DENIED", cr["version"]),
        make_landlord_headers(ctx["pl"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DENIAL_REASON_INVALID, 422)
    assert get_review_fresh(cr["id"])["decision"] == "PENDING"


def test_credit_denial_rejected_when_credit_passed(api):
    """PRD §3.5: "A `DENIED` decision without a `denial_reason_code`, or one citing `INSUFFICIENT_CREDIT` while the credit review's `outcome` is not `FAIL`, is rejected with `ERR_DENIAL_REASON_INVALID` (HTTP 422)"

    Design: Difficulty/cross_entity_state_dependency/consent_decision_gated_on_credit_review_outcome_for_credit_denial
    """
    ctx = build_consent_pending_transfer()  # credit attested PASS at 7000 bps
    cr = ctx["consent_review"]
    resp = api.decide_consent_review(
        cr["id"],
        decide_payload("DENIED", cr["version"],
                       denial_reason_code="INSUFFICIENT_CREDIT"),
        make_landlord_headers(ctx["pl"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DENIAL_REASON_INVALID, 422)
    assert get_review_fresh(cr["id"])["decision"] == "PENDING"
    assert get_transfer(ctx["transfer"]["id"])["status"] == "CONSENT_PENDING"


def test_credit_denial_accepted_when_credit_failed(api):
    """PRD §3.4: "A `FAIL` does not itself deny the transfer; it arms the landlord's `INSUFFICIENT_CREDIT` denial ground, nothing more."
    PRD §3.5: "A valid denial moves the transfer from `SUBMITTED` or `CONSENT_PENDING` to the terminal `CONSENT_DENIED` and decrements the lease's `open_transfer_count` while incrementing its `version`."

    Design: Difficulty/cross_entity_state_dependency/consent_decision_gated_on_credit_review_outcome_for_credit_denial
    """
    ctx = build_consent_pending_transfer(rating_bps=5999)  # credit FAIL
    assert ctx["credit_review"]["outcome"] == "FAIL"

    review = decide_consent(ctx["consent_review"]["id"], ctx["pl"]["id"], "DENIED",
                            denial_reason_code="INSUFFICIENT_CREDIT")
    assert review["decision"] == "DENIED"
    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "CONSENT_DENIED"
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0


def test_state_dominates_duty_segregation_on_decide(api):
    """PRD §2.8: "the server evaluates them in one fixed order, and a failure at any step masks every later check: authentication first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of path-referenced resources (`ERR_NOT_FOUND`), then referential integrity of supplied foreign keys (`ERR_FK_MISMATCH`), then state validity for the invoked transition (`ERR_INVALID_STATE`), then segregation of duties (`ERR_DUTY_SEGREGATION`)"
    PRD §3.5: "The server evaluates the guards in order: the review must still be `PENDING` (`ERR_INVALID_STATE`), the caller's `X-User-ID` must equal the lease's `landlord_party_id` (`ERR_DUTY_SEGREGATION`)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_duty_segregation_on_decide
    """
    ctx = build_granted_transfer()  # review already decided GRANTED by the landlord of record
    pl2 = create_party("LANDLORD", "Landlord Two LLC", 9000)
    cr = get_review_fresh(ctx["consent_review"]["id"])

    resp = api.decide_consent_review(
        cr["id"],
        decide_payload("DENIED", cr["version"], denial_reason_code="USE_CONFLICT"),
        make_landlord_headers(pl2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_wrong_landlord_on_pending_review_is_duty_segregation(api):
    """PRD §2.9: "The landlord deciding a consent review must be the lease's landlord of record, with `X-User-ID` equal to the lease's `landlord_party_id`."
    PRD §3.5: "The server evaluates the guards in order: the review must still be `PENDING` (`ERR_INVALID_STATE`), the caller's `X-User-ID` must equal the lease's `landlord_party_id` (`ERR_DUTY_SEGREGATION`)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_duty_segregation_on_decide
    """
    ctx = build_submitted_transfer()
    pl2 = create_party("LANDLORD", "Landlord Two LLC", 9000)
    cr = ctx["consent_review"]

    resp = api.decide_consent_review(
        cr["id"], decide_payload("GRANTED", cr["version"]),
        make_landlord_headers(pl2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION, 403)
    assert get_review_fresh(cr["id"])["decision"] == "PENDING"


def test_stale_review_version_rejected_then_current_succeeds(api):
    """PRD §2.7: "Submitting a landlord consent decision (`POST /sublease-admin/consent-reviews/{id}/decide`) requires `expected_consent_review_version`, carrying the review `version` the landlord last observed. If the review's current `version` no longer matches, the decision is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412), since the decision would rest on a review record the landlord has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_review_version_on_decide
    """
    ctx = build_submitted_transfer()
    cr = ctx["consent_review"]
    v0 = cr["version"]
    landlord = make_landlord_headers(ctx["pl"]["id"])

    resp = api.decide_consent_review(
        cr["id"], decide_payload("GRANTED", v0 - 1), landlord,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_REVIEW_VERSION, 412)
    assert get_review_fresh(cr["id"])["decision"] == "PENDING", (
        "stale decision leaves the review untouched"
    )

    granted = validate_success(api.decide_consent_review(
        cr["id"], decide_payload("GRANTED", v0), landlord,
    ), 200)
    assert granted["decision"] == "GRANTED"
    assert granted["version"] == v0 + 1, "a decided review increments its version by one"


def test_mismatched_review_version_leaves_review_pending(api):
    """PRD §2.7: "If the review's current `version` no longer matches, the decision is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412), since the decision would rest on a review record the landlord has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_review_version_on_decide
    """
    ctx = build_submitted_transfer()
    cr = ctx["consent_review"]
    resp = api.decide_consent_review(
        cr["id"], decide_payload("DENIED", cr["version"] + 5,
                                 denial_reason_code="USE_CONFLICT"),
        make_landlord_headers(ctx["pl"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_REVIEW_VERSION, 412)
    review = get_review_fresh(cr["id"])
    assert review["decision"] == "PENDING"
    assert review.get("decided_at") is None
    assert get_transfer(ctx["transfer"]["id"])["status"] == "SUBMITTED"


def test_forbidden_role_asset_manager_cannot_decide(api):
    """PRD §2.1: "A well-formed request whose role is not on the invoked endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/errors/forbidden_role_asset_manager_cannot_decide
    """
    ctx = build_submitted_transfer()
    cr = ctx["consent_review"]
    resp = api.decide_consent_review(
        cr["id"], decide_payload("GRANTED", cr["version"]), MGR,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert get_review_fresh(cr["id"])["decision"] == "PENDING"


def test_tenant_cannot_decide_landlord_cannot_respond(api):
    """PRD §2.1: "A well-formed request whose role is not on the invoked endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.9: "The tenant responding to a consent condition must be the lease's tenant of record, with `X-User-ID` equal to the lease's `tenant_party_id`."

    Design: Corner/rbac/tenant_cannot_decide_consent_landlord_cannot_respond_conditions
    """
    ctx = build_submitted_transfer()
    cr = ctx["consent_review"]
    decide_consent(cr["id"], ctx["pl"]["id"], "GRANTED_WITH_CONDITIONS",
                   conditions=[{"condition_kind": "RESTORATION_REQUIRED",
                                "detail": "Restore demising walls"}])
    condition = list_conditions(cr["id"])[0]

    resp1 = api.decide_consent_review(
        cr["id"], decide_payload("GRANTED", cr["version"]),
        make_tenant_headers(ctx["pt"]["id"]),
    )
    validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    resp2 = api.respond_consent_condition(
        condition["id"], {"response": "ACCEPTED"},
        make_landlord_headers(ctx["pl"]["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    cond_after = validate_success(api.get_consent_condition(condition["id"], B1), 200)
    assert cond_after["status"] == "PENDING"


def test_condition_acceptance_join_grants_consent(api):
    """PRD §3.5: "When every condition of the review has reached `ACCEPTED`, the join fires: the transfer moves `CONSENT_PENDING → CONSENT_GRANTED` with the same side effects as an express grant — `consent_granted_at`, the differential computation against the certified measurement, and the liability flag."
    PRD §3.5: "The `liability_released` flag is true only when the `transfer_type` is `ASSIGNMENT` and the granted review carried `release_of_assignor` set to true; a `SUBLEASE` never releases tenant liability"

    Design: Corner/state_machines/condition_acceptance_join_grants_consent
    """
    ctx = build_conditional_grant()
    cond0, cond1 = ctx["conditions"]

    respond_condition(cond0["id"], ctx["pt"]["id"], "ACCEPTED")
    mid = get_transfer(ctx["transfer"]["id"])
    assert mid["status"] == "CONSENT_PENDING", "join incomplete while a condition is open"

    respond_condition(cond1["id"], ctx["pt"]["id"], "ACCEPTED")
    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "CONSENT_GRANTED"
    assert transfer["consent_granted_at"] is not None
    assert transfer["annual_rent_differential_cents"] == DIFFERENTIAL_CENTS
    assert transfer["liability_released"] is False, "a SUBLEASE never releases"

    review = get_review_fresh(ctx["consent_review"]["id"])
    assert review["conditions_imposed_count"] == 2


def test_reject_condition_then_rescind(api):
    """PRD §3.5: "Any single `REJECTED` condition instead arms rescission: while the transfer is still `CONSENT_PENDING`, the landlord may rescind, moving the review from `GRANTED_WITH_CONDITIONS` to `RESCINDED`, stamping `rescinded_at`, driving the transfer to `RESCINDED`, and decrementing the lease's `open_transfer_count` while incrementing its `version`."

    Design: Difficulty/non_linear_state_machine/consent_review_conditional_fork_join_and_rescind_cycle
    """
    ctx = build_conditional_grant()
    cond0, cond1 = ctx["conditions"]

    respond_condition(cond0["id"], ctx["pt"]["id"], "REJECTED")
    rescinded = validate_success(api.rescind_consent_review(
        ctx["consent_review"]["id"], make_landlord_headers(ctx["pl"]["id"]),
    ), 200)
    assert rescinded["decision"] == "RESCINDED"
    assert rescinded["rescinded_at"] is not None

    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "RESCINDED"

    sibling = validate_success(api.get_consent_condition(cond1["id"], B1), 200)
    assert sibling["status"] == "PENDING", (
        "the unresponded sibling condition is left pending through the rescind"
    )
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0


def test_conditional_grant_holds_transfer_pending(api):
    """PRD §3.5: "`GRANTED_WITH_CONDITIONS` requires at least one supplied condition — each an entry of `condition_kind` and free-text `detail`, the kind drawn from `RESTORATION_REQUIRED`, `ADDITIONAL_SECURITY`, `RENT_RESET_TO_MARKET`, or `RECAPTURE_RIGHT` — and creates one consent condition in `PENDING` per supplied entry, recording their number as `conditions_imposed_count`. The transfer does not advance yet: it remains in `CONSENT_PENDING` until the conditional-acceptance join resolves."

    Design: Difficulty/non_linear_state_machine/consent_review_conditional_fork_join_and_rescind_cycle
    """
    ctx = build_conditional_grant()
    review = get_review_fresh(ctx["consent_review"]["id"])
    assert review["decision"] == "GRANTED_WITH_CONDITIONS"
    assert review["conditions_imposed_count"] == 2

    conditions = list_conditions(review["id"])
    assert len(conditions) == 2
    assert all(c["status"] == "PENDING" for c in conditions)
    assert all(c["consent_review_id"] == review["id"] for c in conditions)

    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "CONSENT_PENDING", "the fork holds the transfer"


def test_assignment_release_only_with_landlord_election(api):
    """PRD §3.5: "The `liability_released` flag is true only when the `transfer_type` is `ASSIGNMENT` and the granted review carried `release_of_assignor` set to true; a `SUBLEASE` never releases tenant liability, and `release_of_assignor` defaults to false and is only meaningful for assignments."

    Design: Corner/state_machines/assignment_release_only_with_landlord_election
    """
    # A1: ASSIGNMENT with the release elected.
    ctx1 = build_granted_transfer(counterparty_kind="ASSIGNEE", attest=False,
                                  transfer_overrides={"transfer_type": "ASSIGNMENT"},
                                  decide_overrides={"release_of_assignor": True})
    assert get_transfer(ctx1["transfer"]["id"])["liability_released"] is True

    # A2: ASSIGNMENT without the release election.
    ctx2 = build_granted_transfer(counterparty_kind="ASSIGNEE", attest=False,
                                  transfer_overrides={"transfer_type": "ASSIGNMENT"},
                                  decide_overrides={"release_of_assignor": False})
    assert get_transfer(ctx2["transfer"]["id"])["liability_released"] is False

    # S3: SUBLEASE with the flag set — the type gate dominates the flag.
    ctx3 = build_granted_transfer(counterparty_kind="SUBTENANT", attest=False,
                                  decide_overrides={"release_of_assignor": True})
    assert get_transfer(ctx3["transfer"]["id"])["liability_released"] is False


def test_rent_differential_zero_floor_at_passthrough(api):
    """PRD §3.5: "The `annual_rent_differential_cents` is the per-RSF spread — the proposed rent minus the lease's `base_rent_per_rsf_annual_cents`, both annual cents per rentable square foot — multiplied by the certified, non-superseded measurement's `rentable_sf`, with the whole differential clamped at zero when the spread is zero or negative: a sublease at or below the pass-through rent yields zero differential and zero profit share, and the integer-cent result needs no rounding."

    Design: Corner/calculations/rent_differential_zero_floor_at_or_below_passthrough
    """
    ctx = build_granted_transfer(attest=False, transfer_overrides={
        "proposed_rent_per_rsf_annual_cents": 5200,  # equal to the lease base rent
    })
    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "CONSENT_GRANTED"
    assert transfer["annual_rent_differential_cents"] == 0


def test_immediate_consistency_on_decide_response(api):
    """PRD §2.10: "State changes propagate across aggregate boundaries immediately, inside the same request that triggers them: certifying a revised measurement supersedes its predecessor, a second recognition signature advances both the transfer and the instrument, and finalizing a settlement debits the lease."
    PRD §3.5: "A decided review stamps `decided_at`, records the caller as `reviewer_landlord_id`, and increments the review's `version` by one; the decision drives the parent transfer across entity boundaries."

    Design: Corner/consistency_model/immediate_consistency_on_decide_response
    """
    ctx = build_consent_pending_transfer()
    cr = ctx["consent_review"]
    decided = validate_success(api.decide_consent_review(
        cr["id"], decide_payload("GRANTED", cr["version"]),
        make_landlord_headers(ctx["pl"]["id"]),
    ), 200)
    assert decided["decision"] == "GRANTED"
    assert decided["decided_at"] is not None
    assert decided["reviewer_landlord_id"] == ctx["pl"]["id"]

    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "CONSENT_GRANTED", "no eventual lag on the parent"
    assert transfer["annual_rent_differential_cents"] == DIFFERENTIAL_CENTS


def test_terminal_consent_denied_lockdown(api):
    """PRD §3.5: "A valid denial moves the transfer from `SUBMITTED` or `CONSENT_PENDING` to the terminal `CONSENT_DENIED` and decrements the lease's `open_transfer_count` while incrementing its `version`."
    PRD §3.9: "Withdrawal belongs to the originating broker alone — a withdrawer whose `X-User-ID` differs from the transfer's `broker_user_id` is rejected as `ERR_DUTY_SEGREGATION` — and its consequences depend on how far the transfer had travelled."

    Design: Corner/state_machines/terminal_consent_denied_lockdown
    """
    ctx = build_consent_pending_transfer()
    decide_consent(ctx["consent_review"]["id"], ctx["pl"]["id"], "DENIED",
                   denial_reason_code="USE_CONFLICT")
    tr_id = ctx["transfer"]["id"]
    assert get_transfer(tr_id)["status"] == "CONSENT_DENIED"

    resp = api.withdraw_transfer_request(tr_id, B1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_transfer(tr_id)["status"] == "CONSENT_DENIED", "denial is terminal"

    cr = get_review_fresh(ctx["consent_review"]["id"])
    resp2 = api.decide_consent_review(
        cr["id"], decide_payload("GRANTED", cr["version"]),
        make_landlord_headers(ctx["pl"]["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE, 409)

    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0
