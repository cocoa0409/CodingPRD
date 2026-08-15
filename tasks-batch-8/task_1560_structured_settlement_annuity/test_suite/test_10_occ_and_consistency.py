"""Optimistic concurrency control on the two guarded write endpoints, and immediate
read-after-write consistency (PRD §2.7, §3.4)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_funded_agreement, setup_active_case, add_draft_schedule, activate_schedule,
    get_agreement, get_policy, issue_payment,
    create_commutation_request_payload,
    TEST_USERS,
)

CASE_MGR = TEST_USERS["case_manager_headers"]
OPS = TEST_USERS["operations_specialist_headers"]
READER = TEST_USERS["reader_headers"]


# --- Schedule activation OCC on the agreement version (PRD §2.7) ----------------------

def _setup_two_draft_schedules():
    """Funded agreement; s1 (payment 30000 due 2027-01-01) and s2 (31000 due
    2027-02-01) both DRAFT. Returns (ctx, s1, s2)."""
    ctx = setup_funded_agreement(agreement_overrides={"case_number": "OC-001"})
    add_draft_schedule(ctx, [{"due_date": "2027-01-01", "base_amount_cents": 30000}])
    s1 = ctx["schedule"]
    ctx2 = {"agreement": get_agreement(ctx["agreement"]["id"]), "payee": ctx["payee"]}
    add_draft_schedule(ctx2, [{"due_date": "2027-02-01", "base_amount_cents": 31000}],
                       schedule_overrides={"effective_from_date": "2026-03-01",
                                           "escalation_anchor_date": "2026-03-01"})
    return ctx, s1, ctx2["schedule"]


def test_schedule_activate_stale_agreement_version_rejected(api):
    """PRD §2.7: "If the agreement's version has advanced since the client last read it
    — an intervening activation, a payment transition that recomputed ledger totals, a
    status change — the activation is rejected with `ERR_STALE_AGREEMENT_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_schedule_activate_stale_version_rejected
    """
    ctx, s1, s2 = _setup_two_draft_schedules()
    agreement = get_agreement(ctx["agreement"]["id"])
    stale_version = agreement["version"]

    first = validate_success(api.activate_payment_schedule(
        s1["id"], {"expected_settlement_agreement_version": stale_version}, CASE_MGR))
    assert first["status"] == "ACTIVE", "the fresh version is accepted"

    # s1's activation advanced agreement.version past the value this client holds.
    resp = api.activate_payment_schedule(
        s2["id"], {"expected_settlement_agreement_version": stale_version}, CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)


def test_schedule_activate_with_refreshed_version_succeeds(api):
    """PRD §2.7: "the activation request must carry
    `expected_settlement_agreement_version` equal to the agreement's current `version`"
    — re-reading and resubmitting with the fresh version succeeds.

    Design: Corner/cross_cutting_layers/occ_schedule_activate_stale_version_rejected
    """
    ctx, s1, s2 = _setup_two_draft_schedules()
    activate_schedule(ctx, schedule_id=s1["id"])
    agreement = get_agreement(ctx["agreement"]["id"])
    second = validate_success(api.activate_payment_schedule(
        s2["id"], {"expected_settlement_agreement_version": agreement["version"]}, CASE_MGR))
    assert second["status"] == "ACTIVE"


# --- Commutation creation OCC on the policy version (PRD §2.7) -------------------------

def _setup_commutation_occ_case():
    return setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": "OC-002"},
        policy_overrides={"commutation_rider": "DEATH_AND_HARDSHIP"})


def test_commutation_create_stale_policy_version_rejected(api):
    """PRD §2.7: "The creation request must therefore carry
    `expected_annuity_policy_version` equal to the policy's current `version`; a
    mismatch is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412)".
    PRD §3.7: "Creation itself advances the policy's `version`".

    Design: Corner/cross_cutting_layers/occ_commutation_create_stale_version_rejected
    """
    ctx = _setup_commutation_occ_case()
    policy = get_policy(ctx["policy"]["id"])
    stale_version = policy["version"]

    first = validate_success(api.create_commutation_request(
        create_commutation_request_payload(ctx["policy"]["id"], ctx["agreement"]["id"],
                                           "HARDSHIP", stale_version), CASE_MGR), 201)
    assert first["status"] == "REQUESTED", "the first create succeeded with the fresh version"

    resp = api.create_commutation_request(
        create_commutation_request_payload(ctx["policy"]["id"], ctx["agreement"]["id"],
                                           "HARDSHIP", stale_version), CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_STALE_POLICY_VERSION)


def test_commutation_create_with_refreshed_version_succeeds(api):
    """PRD §2.7: "a mismatch is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412) and
    the client must re-read the policy before retrying."
    PRD §3.7: "Creation itself advances the policy's `version` — the anchor that makes
    the optimistic-concurrency check on a subsequent request meaningful".

    Design: Corner/cross_cutting_layers/occ_commutation_create_stale_version_rejected
    """
    ctx = _setup_commutation_occ_case()
    policy = get_policy(ctx["policy"]["id"])
    validate_success(api.create_commutation_request(
        create_commutation_request_payload(ctx["policy"]["id"], ctx["agreement"]["id"],
                                           "HARDSHIP", policy["version"]), CASE_MGR), 201)

    refreshed = get_policy(ctx["policy"]["id"])
    assert refreshed["version"] > policy["version"], "creation advanced the policy version"
    second = validate_success(api.create_commutation_request(
        create_commutation_request_payload(ctx["policy"]["id"], ctx["agreement"]["id"],
                                           "HARDSHIP", refreshed["version"]), CASE_MGR), 201)
    assert second["status"] == "REQUESTED"


# --- Immediate consistency on cascade reads (PRD §3.4) ---------------------------------

def test_immediate_consistency_on_cascade_reads(api):
    """PRD §3.4: "Marking cleared — an operations specialist confirming the funds were
    honored — requires `ISSUED` (`ERR_PAYMENT_NOT_ISSUED`) and moves the payment to
    `CLEARED`: the agreement's `paid_total_cents` grows by the payment's `amount_cents`,
    `outstanding_liability_cents` shrinks by the same, the agreement's `version`
    increments, and the exhaustion check runs — if no non-terminal payments remain, the
    linked policy becomes `EXHAUSTED` and the agreement follows to `CLOSED`."

    Design: Corner/consistency_model/immediate_consistency_on_cascade_reads
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2026-08-10", "base_amount_cents": 40000}],
        clock_to="2026-08-10T00:00:00Z",
        agreement_overrides={"case_number": "ER-013"})
    payment = ctx["payments"][0]
    issue_payment(payment["id"], method="EFT", user_id="ops-1")

    cleared = validate_success(api.mark_payment_cleared(payment["id"], OPS))
    assert cleared["status"] == "CLEARED", "the mutation response itself shows CLEARED"

    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["paid_total_cents"] == 40000
    assert agreement["outstanding_liability_cents"] == 0
    assert agreement["status"] == "CLOSED", (
        "the exhaustion cascade is visible on the immediate re-read"
    )
