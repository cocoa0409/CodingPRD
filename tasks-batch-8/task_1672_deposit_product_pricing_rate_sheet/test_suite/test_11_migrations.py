"""Grandfathered-rate migration: execution cascade, auto-retire bubble-up,
and state gates on both ends (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_draft_sheet,
    create_effective_sheet,
    create_migration_batch,
    create_product,
    execute_migration,
    list_account_notices,
    open_account,
    promote_sheet_to_scheduled,
    deploy_all,
    send_all_notices,
    set_clock,
    single_tier,
    tier,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["analyst_headers"]
ADMIN = TEST_USERS["admin_headers"]
BANKER = TEST_USERS["banker_headers"]

OLD_TIERS = [tier(0, 0, 500_000, 300), tier(1, 500_000, 5_000_000, 375),
             tier(2, 5_000_000, -1, 430)]
NEW_TIERS = [tier(0, 0, 500_000, 280), tier(1, 500_000, 5_000_000, 360),
             tier(2, 5_000_000, -1, 410)]


def _cd_product(code: str):
    return create_product(product_code=code, product_class="CD", term_months=12,
                          tier_application="WHOLE_BALANCE", rate_cap_bp=900,
                          allows_promos=False, allows_exceptions=True)


def _grandfathered_pair(api, code="CDM", with_accounts=True):
    """S-OLD EFFECTIVE 2026-08-15 (OLD_TIERS) with term-CD accounts, then
    S-NEW EFFECTIVE 2026-09-01 (NEW_TIERS): activation grandfathered the
    accounts onto S-OLD."""
    product = _cd_product(code)
    s_old = create_effective_sheet(product_id=product["id"],
                                   effective_date="2026-08-15", tiers=OLD_TIERS)["sheet"]
    a3 = a4 = None
    if with_accounts:
        a3 = open_account(product["id"], opening_balance_cents=30_000_000,
                          customer_ref="CM3", channel="BRANCH")
        a4 = open_account(product["id"], opening_balance_cents=400_000,
                          customer_ref="CM4", channel="BRANCH")
    s_new = create_draft_sheet(product["id"], effective_date="2026-09-01",
                               tiers=NEW_TIERS)
    promote_sheet_to_scheduled(s_new["id"])
    deploy_all(s_new["id"])
    send_all_notices(s_new["id"])
    set_clock("2026-09-01")
    s_new = validate_success(api.activate_rate_sheet(s_new["id"], ANALYST))
    return product, s_old, s_new, a3, a4


def test_migration_executes_and_reprices_accounts(api, admin_headers, banker_headers):
    """PRD §3.7: "The execution cascade then walks every account with
    `sheet_id` on the source sheet and `rate_source` `GRANDFATHERED`: accounts
    whose lifecycle is not `CLOSED` move to `SHEET` pricing on the target
    sheet — `sheet_id` re-pointed, base and current rates recomputed, version
    bumped — while `CLOSED` accounts are skipped and tallied in
    `skipped_count`. `migrated_count` records how many accounts moved. Each
    migrated account whose rate drops by ten basis points or more receives a
    `RATE_CHANGE_ADVERSE` notice due five days after execution."

    Design: Difficulty/transitive_cascade/migration_cascade_bubble_up
    """
    _, s_old, s_new, a3, a4 = _grandfathered_pair(api)
    batch = create_migration_batch(s_old["id"], s_new["id"])
    executed = execute_migration(batch["id"], "EXECUTE")
    assert executed["status"] == "COMPLETED"
    assert executed["migrated_count"] == 2
    assert executed["skipped_count"] == 0

    a3_now = validate_success(api.get_deposit_account(a3["id"], banker_headers))
    assert a3_now["sheet_id"] == s_new["id"]
    assert a3_now["rate_source"] == "SHEET"
    assert a3_now["current_rate_bp"] == 410  # was frozen at 430

    a4_now = validate_success(api.get_deposit_account(a4["id"], banker_headers))
    assert a4_now["sheet_id"] == s_new["id"]
    assert a4_now["current_rate_bp"] == 280  # was frozen at 300

    # Both drops are exactly 20 bp >= 10: adverse notices due five days after
    # the execution date (2026-09-01).
    for acc in (a3, a4):
        adverse = [n for n in list_account_notices(acc["id"])
                   if n["notice_type"] == "RATE_CHANGE_ADVERSE"]
        assert len(adverse) == 1
        assert adverse[0]["required_by_date"] == "2026-09-06"


def test_migration_auto_retires_drained_source(api, analyst_headers):
    """PRD §3.7: "And when the cascade leaves no `GRANDFATHERED` accounts on
    the source sheet, the source sheet retires itself to `RETIRED`
    automatically — the machine's answer to grandfathered-sheet attrition."

    Design: Difficulty/transitive_cascade/migration_cascade_bubble_up
    """
    _, s_old, s_new, _, _ = _grandfathered_pair(api)
    before = validate_success(api.get_rate_sheet(s_old["id"], analyst_headers))
    assert before["status"] == "SUPERSEDED"

    batch = create_migration_batch(s_old["id"], s_new["id"])
    execute_migration(batch["id"], "EXECUTE")

    after = validate_success(api.get_rate_sheet(s_old["id"], analyst_headers))
    assert after["status"] == "RETIRED"


def _draft_target_scenario(api):
    """S1 EFFECTIVE for P-CDX; S2 merely DRAFT; no accounts. The planned batch
    points S1 -> S2."""
    product = _cd_product("CDX")
    s1 = create_effective_sheet(product_id=product["id"],
                                effective_date="2026-08-15",
                                tiers=single_tier(300))["sheet"]
    s2 = create_draft_sheet(product["id"], effective_date="2026-09-01",
                            tiers=single_tier(280))
    batch = create_migration_batch(s1["id"], s2["id"])
    return product, s1, s2, batch


def test_migration_execute_requires_superseded_source(api, admin_headers):
    """PRD §3.7: "Executing the batch with action `EXECUTE` enforces, in
    order: the batch is `PLANNED` and the source sheet is `SUPERSEDED` (else
    `ERR_MIGRATION_INVALID_STATE`); the target sheet is `EFFECTIVE` (else
    `ERR_MIGRATION_TARGET_NOT_EFFECTIVE`); and source and target share the
    same product and market (else `ERR_INVALID_REQUEST`)."

    Design: Difficulty/cross_entity_state_dependency/migration_requires_target_effective_source_superseded
    """
    _, _, _, batch = _draft_target_scenario(api)
    # Source still EFFECTIVE (and target still DRAFT): the state gate fires.
    resp = api.execute_migration_batch(batch["id"], {"action": "EXECUTE"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_MIGRATION_INVALID_STATE, 409)


def test_migration_execute_succeeds_once_target_activates(api, admin_headers,
                                                          analyst_headers):
    """PRD §3.7: "Executing the batch with action `EXECUTE` enforces, in
    order: the batch is `PLANNED` and the source sheet is `SUPERSEDED` (else
    `ERR_MIGRATION_INVALID_STATE`); the target sheet is `EFFECTIVE` (else
    `ERR_MIGRATION_TARGET_NOT_EFFECTIVE`); and source and target share the
    same product and market (else `ERR_INVALID_REQUEST`)."
    PRD §3.7: "And when the cascade leaves no `GRANDFATHERED` accounts on the
    source sheet, the source sheet retires itself to `RETIRED` automatically —
    the machine's answer to grandfathered-sheet attrition."

    Design: Difficulty/cross_entity_state_dependency/migration_requires_target_effective_source_superseded
    """
    product, s1, s2, batch = _draft_target_scenario(api)
    # Drive S2 to EFFECTIVE; activation supersedes S1.
    promote_sheet_to_scheduled(s2["id"])
    deploy_all(s2["id"])
    send_all_notices(s2["id"])
    set_clock("2026-09-01")
    validate_success(api.activate_rate_sheet(s2["id"], analyst_headers))

    executed = validate_success(api.execute_migration_batch(
        batch["id"], {"action": "EXECUTE"}, admin_headers))
    assert executed["status"] == "COMPLETED"
    assert executed["migrated_count"] == 0  # the pair never had accounts

    source = validate_success(api.get_rate_sheet(s1["id"], analyst_headers))
    assert source["status"] == "RETIRED"  # no GRANDFATHERED accounts remain


def test_migration_target_not_effective_alone(api, admin_headers):
    """PRD §3.7: "Executing the batch with action `EXECUTE` enforces, in
    order: the batch is `PLANNED` and the source sheet is `SUPERSEDED` (else
    `ERR_MIGRATION_INVALID_STATE`); the target sheet is `EFFECTIVE` (else
    `ERR_MIGRATION_TARGET_NOT_EFFECTIVE`); and source and target share the
    same product and market (else `ERR_INVALID_REQUEST`)."

    Design: Corner/validations/migration_target_not_effective_alone
    """
    _, s_old, s_new, _, _ = _grandfathered_pair(api, code="MT",
                                                with_accounts=False)
    # Source properly SUPERSEDED; a third sheet is only DRAFT.
    product_id = validate_success(api.get_rate_sheet(s_new["id"], ANALYST))["product_id"]
    s3 = create_draft_sheet(product_id, effective_date="2026-10-01",
                            tiers=single_tier(290))
    batch = create_migration_batch(s_old["id"], s3["id"])
    resp = api.execute_migration_batch(batch["id"], {"action": "EXECUTE"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_MIGRATION_TARGET_NOT_EFFECTIVE, 422)


def test_abort_completed_migration_returns_invalid_state(api, admin_headers):
    """PRD §3.7: "A batch may instead be aborted, action `ABORT` moving
    `PLANNED → ABORTED` with no account effects; `COMPLETED` and `ABORTED` are
    both terminal."
    PRD §2.10: "From-state validity: the target resource is in a state from
    which the requested transition exists — sheets surface
    `ERR_SHEET_INVALID_STATE`, offers `ERR_PROMO_INVALID_STATE`, exception
    requests `ERR_EXCEPTION_INVALID_STATE`, accounts
    `ERR_ACCOUNT_INVALID_STATE`, migration batches
    `ERR_MIGRATION_INVALID_STATE`, enrollments `ERR_ENROLLMENT_INVALID_STATE`,
    scans `ERR_SCAN_INVALID_STATE`, deployments `ERR_DEPLOYMENT_INVALID_STATE`,
    and notice re-resolution `ERR_NOTICE_ALREADY_RESOLVED` (all 409)."

    Design: Corner/state_machines/abort_completed_migration_returns_invalid_state
    """
    _, s_old, s_new, _, _ = _grandfathered_pair(api, code="IV9",
                                                with_accounts=False)
    batch = create_migration_batch(s_old["id"], s_new["id"])
    executed = execute_migration(batch["id"], "EXECUTE")
    assert executed["status"] == "COMPLETED"

    resp = api.execute_migration_batch(batch["id"], {"action": "ABORT"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_MIGRATION_INVALID_STATE, 409)
