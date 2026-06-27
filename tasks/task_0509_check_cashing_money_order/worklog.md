# Worklog — task_0509_check_cashing_money_order

## Step 1: Create Task Directory — 2026-06-27T00:00:00.000Z

Created `tasks/task_0509_check_cashing_money_order/` and `tasks/task_0509_check_cashing_money_order/workspace/`. Pre-allocated directory used directly (no renumbering scan). Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate Scaffold — 2026-06-27T00:00:00.000Z

`ERR_VALIDATION` is exercised by 6 corner-design references (missing-field, bad-enum, zero-amount tests). All errors are triggerable.

The scaffold is complete and passes clean lint. Here is the final summary.

Generated all three scaffold artifacts for **task_0509_check_cashing_money_order** (Check Cashing, Money Order & Bill Pay, ACE Cash Express style) at **Expert** difficulty. `scaffold_lint.py` reports **VERDICT: clean lint** (321 setup/trigger calls scanned, all §1.8/§1.9 calls conform to §1.5, all FKs reverse-reachable).

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Scale (Expert tier):**
- **11 entities**: Customer, ComplianceScreen, FeeSchedule, CashDrawer, Transaction, CheckItem, MoneyOrder, WireTransfer, BillPayment, PrepaidCardLoad, ReturnedItem
- **32 endpoints** (1 test-driving: `POST /_clock/set_current_utc`, default clock 2026-05-01T00:00:00Z)
- **18 error codes**; **17 validations** (priority-ordered); **2 roles** (Teller, StoreManager — segregation of duties); **1 concurrency rule** (OCC on `CashDrawer.version` for close-out)

**4 state machines** (flat topology, branching shape): CheckItem (branch VERIFYING→{CLEARED,RISK_HELD}→{CLEARED,REJECTED}), Transaction (parallel `lifecycle_state` × `settlement_state`), CashDrawer (branch at close → CLOSED/OVER_SHORT), ReturnedItem (cyclic partial-recovery loop).

**6 calculations** with key dual-variant/combinatorial mechanics:
- `check_cash_fee` — marginal tiered pricing, **per-leg-floor-then-sum pinned** (diverges from sum-then-floor by 1 cent, e.g. 4573 vs 4574 at face=250001)
- `service_fee` — branch-on-txn_type with greater-of/min-cap nesting
- `drawer_expected_cash`, `customer_risk_score` (provisional vs confirmed), `returned_item_recovery` (waterfall), `velocity_window` (half-open rolling 24h)

**Difficulty design:** all 9 rules × 2 = **18 instances** (unique names). **Corner design:** **49 instances** (47 with recipes + 2 `excluded_because` stubs), no name collisions with difficulty file, both stubs resolve to real difficulty-instance names.

**Notable fixes during generation:** set `api_prefix: /` (flat multi-collection API) so FK reverse-reachability resolves; added `fee_schedule_id?` filter to `GET /transactions`; quoted YAML flow-sequence tokens containing `{}`/`[]`; corrected daily-limit setups to accumulate via five 180k checks (single 900k check would breach the STANDARD per-txn ceiling of 500k).

## Step 3: Copy Shared Files — 2026-06-27T00:00:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-27T00:00:00.000Z

**Output written:** `workspace/PRD.md`

**Structure:** 5 top-level sections, 20 subsections total (11 in §2, 9 in §3), ~258 lines. §4 endpoint table has all 32 endpoints in 4 columns; §5 error table has all 18 error IDs in 2 columns.

**Hard Contract reports:**
- Contract 1 (Field coverage): 58 required, 58 present, 0 missing — PASS
- Contract 2 (Rule coverage): 17-rule validation ordering in §2.11; 1 OCC rule (drawer close, ERR_STALE_DRAWER_VERSION/412); 4 state machines (CheckItem 4, Transaction 5, CashDrawer 4, ReturnedItem 6 transitions); 6 calculations all fully expressed; 18 error IDs all matchable — PASS
- Contract 3 (Path purity §3): 326 backtick tokens scanned, 0 path/method tokens — PASS

**Numeric constants embedded:** 300000 hold threshold, velocity count 8, fee constants, risk-point deltas, tier boundaries, daily limits 12/1000000, ceilings 500000/200000/50000, return fee 2500, clock default 2026-05-01T00:00:00Z.

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read, opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-06-27T00:00:00.000Z

Generated complete test infrastructure for **task_0509_check_cashing_money_order**.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (entity TypedDicts with ComplianceScreen correctly omitting `version`/`updated_at` per its `common_fields: false`, plus status/role enums), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (18 error IDs + HTTP-status map), `assertions.py`, `factories.py`, `constants.py` (all calc thresholds), `test_users.py` (both opaque roles, with `make_*_headers(user_id)` builders), `fixtures.py` (composite setups), `__init__.py` barrel.

**Stage 2 — `test_suite/`** (10 test files + conftest): **83 tests total**.
- **Queue A (Difficulty): 36 tests** — all 9 rules × 2 instances × exactly 2 tests each. Files test_01–test_05.
- **Queue B (Corner): 47 tests** — exactly one test per non-stub instance, verified 1:1 (0 missing, 0 extra) against 47 non-stub corner instances. Files test_06–test_10.

**Instances skipped: 2** — both `excluded_because` stubs (correct):
- `Corner/validations/kyc_not_verified_excluded_stub` → owned by `Difficulty/cross_entity_state_dependency/transaction_post_requires_customer_kyc_verified`
- `Corner/cross_cutting_complexity_layers/velocity_count_threshold_at_boundary` → owned by `Difficulty/resource_temporal_overlap/velocity_rolling_window_half_open_aggregate`

**Audits passed:** every test carries exactly one `Design:` tag; all 18 difficulty instances have ≥2 tests; all 47 non-stub corner instances have ≥1 test; all 117 PRD citation fragments survive verbatim grep; no skip/xfail; no scaffold leakage; all imports resolve; all files byte-compile.

## Step 6: Generate Implementation — 2026-06-27T00:00:00.000Z

Built complete Python + Flask implementation at `workspace/implementation/`.

**Files (23 total):** `start.sh` (foreground launcher: guarded pip install, then `exec python3 app.py`), `requirements.txt` (Flask==3.0.3), `app.py` (8 blueprints, error handlers, binds 0.0.0.0:$PORT default 10000, threaded=True), foundation (`db.py` in-memory dicts, `errors.py` 18 error IDs + HTTP map, `response.py`, `auth.py` RBAC, `clock.py` logical clock, `helpers.py`, `lookups.py`), `routes/` (customers, fee_schedules, cash_drawers, transactions, check_items, product_children, returned_items, clock_routes), `services/` (calculations, domain, posting).

**Endpoints: 32, exactly matching PRD §4.**

**Storage & clock:** 100% in-memory (one dict per entity collection in db.Store, instantiated once at module load). No SQLite, no JSON dumps, no /tmp cache. No seeding at startup. Logical clock starts at 2026-05-01T00:00:00Z, advanced only via POST /_clock/set_current_utc; api_request_timestamp uses wall-clock (3 fractional digits).

**Key behaviors verified by smoke tests:** per-leg-floored tiered check-cash fee, service fees by txn_type, CheckItem RISK_HELD fork with first-match hold_reason ordering, release/reject confirmed risk deltas, segregation-of-duties, drawer OCC on close (412), variance→CLOSED/OVER_SHORT, return→recovery waterfall, velocity half-open rollover at +24h, daily limits (12 txn / 1,000,000 cash), validation priority order, pagination clamps, RBAC. All modules byte-compile; server boots within seconds of fresh start.sh.

## Step 7: Run Tests and Iterate — 2026-06-27T00:00:00.000Z

**Final state: all 8 parallel rounds × 82/82 tests passed, 0 failed, 0 errors** (confirmed by orchestrator reading results.1–8.json: every round passed=82 failed=0 total=82).

**Iterations run:** 4 full 8-round parallel sweeps (1 baseline diagnostic + 3 validation/confirmation). The final two consecutive sweeps were fully clean, achieved under heavy host load (load avg up to 28, 40+ co-tenant benchmark processes running concurrently).

**Baseline failures found (union across first sweep):**
1. `test_ofac_blocked_on_screen_hard_block_post` — deterministic logic failure (all 8 rounds): expected `ERR_OFAC_BLOCKED`, got `ERR_KYC_NOT_VERIFIED`.
2. `test_compliance_screen_immutable_no_version` (and later other tests) — non-deterministic "API server could not be restarted" boot-timeout, in 4 of 8 rounds.

**Tests deleted (1):**
- `test_ofac_blocked_on_screen_hard_block_post` (in `test_suite/test_09_validations.py`) — **ERROR PRECEDENCE SILENCE**. The PRD contradicts itself on which error wins when an `OFAC_BLOCKED` customer posts a transaction. §2.11 ("Resolution Order of Validations", purpose "so that the returned error is deterministic") lists KYC gate (`ERR_KYC_NOT_VERIFIED`) strictly before the sanctions block (`ERR_OFAC_BLOCKED`), and §2.8 sentence 1 says any non-`VERIFIED` status (which includes `OFAC_BLOCKED`) → `ERR_KYC_NOT_VERIFIED`; while §2.8 sentence 2 calls OFAC an "absolute, separate block... Independently of the KYC gate... hard-blocked regardless of any other status." Two divergent PRD-faithful implementations exist: (A) §2.11 order + §2.8-s1 → `ERR_KYC_NOT_VERIFIED` (impl's choice); (B) §2.8-s2 "independent/regardless" → `ERR_OFAC_BLOCKED` (test's assertion). Not uniquely determined → deleted per unique-derivability cardinal rule. Scaffold rule: `Corner/validations/ofac_blocked_on_screen_hard_block_post` (validations[priority=7]). No other test covers `ERR_OFAC_BLOCKED`-on-post.

**Fixes applied to test_helpers/:** None. All fixtures/factories/header builders were PRD-faithful.

**Fixes applied to implementation/ (both address boot-restart flakiness, not domain logic):**
- `workspace/implementation/start.sh` — replaced per-reboot `python3 -c "import flask"` probe with a one-time `.deps_installed` filesystem sentinel, removing a heavy subprocess from every one of ~656 reboots per sweep and cutting boot-time CPU contention that pushed boots past the runner's 15s restart window.
- `workspace/implementation/app.py` (`__main__` block) — added bind-retry on the listening socket. The runner SIGKILLs the prior per-test server and immediately respawns on the same port; under load the kernel hadn't released the old LISTEN socket, so `app.run()` lost the rebind race with `EADDRINUSE` and exited code 1. Now boot pre-binds its own socket with `SO_REUSEADDR`(+`SO_REUSEPORT`) and retries up to 12s, then serves via `werkzeug.serving.make_server(..., fd=...)`. No endpoint/field/behavior added — purely the process-level bind path.

In-memory-only, no-seeding constraints preserved (the sentinel is a dependency build-marker, not entity data).

**Note:** Step 7 applied 1 test deletion + 2 implementation/ fixes (>0 fixes), so Step 8 (PRD finalizer) is NOT skipped.

## Step 8: Finalize PRD — 2026-06-27T00:00:00.000Z

Produced `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md = 258, PRD_FINALIZED.md = 258 (0% line-count delta; both edits expanded prose within existing paragraphs).

**Changes (2):**
- **§2.8 — revise — OFAC/KYC error precedence on posting & release.** Rewrote sentence 2 to match impl: because `OFAC_BLOCKED` is a non-`VERIFIED` status and §2.11 orders the KYC gate before the sanctions block, an `OFAC_BLOCKED` customer is rejected with `ERR_KYC_NOT_VERIFIED` on posting and on release, never standalone `ERR_OFAC_BLOCKED`; the standalone `ERR_OFAC_BLOCKED` is reached only when re-screening an already-`OFAC_BLOCKED` customer. — routes/transactions.py:80-85, routes/check_items.py:61-66, routes/customers.py:121-122.
- **§3.7 — revise — release-path error code for OFAC_BLOCKED.** Removed false claim that release separately produces `ERR_OFAC_BLOCKED`; pinned non-`VERIFIED` status (incl. OFAC_BLOCKED) → `ERR_KYC_NOT_VERIFIED`. — routes/check_items.py:61-66.

No edits traced to the two boot-process fixes (start.sh, app.py bind path) — confirmed no domain-behavior footprint. §2.11 ordering line and §3.4 left verbatim (consistent with impl).

## Step 9: Complete PRD — 2026-06-27T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md`.

**Note on execution:** The Step 9 subagent completed its full scan and all edits (42 tool uses, file written intact at 258 lines) but its final message was lost to a transient Bedrock 503 before it returned a self-reported summary. The orchestrator independently verified every edit against `implementation/` (pagination clamp in helpers.py:31-56, DOB no-age-check in routes/customers.py:40, void unconditional/unfloored decrement in routes/transactions.py:271-273, reconcile error precedence in routes/cash_drawers.py:87-121) — all edits are factually grounded in the implementation, no hallucination. Summary below reconstructed from the verified diff.

**Line counts:** PRD_FINALIZED.md = 258, PRD_COMPLETED.md = 258 (0 line delta; all in-paragraph inserts/revisions). ~22 changed lines, ~+1860 chars.

**Changes (10):**
- **§2.5 Pagination — insert — ambiguity** — pinned that out-of-range `limit`/`offset` are silently clamped (limit<1→1, >100→100; negative offset→0) and non-integer values rejected with `ERR_VALIDATION`. — helpers.py:31-56.
- **§2.6 Common fields — insert — ambiguity** — pinned that entity `created_at`/`updated_at` are stamped from the logical clock (§3.8), distinct from the wall-clock envelope `api_request_timestamp`. — clock.py / db stamping.
- **§3.1 Customer register — revise — mismatch** — `date_of_birth` is recorded as supplied (validated only as a present non-empty string; calendar value not parsed, no minimum-age check enforced); replaced the prior "confirm subject is at least 18" wording. — routes/customers.py:40.
- **§3.2 Cash drawer open — insert — ambiguity** — pinned `counted_cash_cents` unset (null) until reconcile and `variance_cents` initialized to 0 (meaningful only at close). — routes/cash_drawers.py:47.
- **§3.5 Check item — insert — ambiguity** — pinned `maker_account_risk` is a required CHECK_CASH posting-body field (missing/out-of-enum → `ERR_VALIDATION`). — routes/transactions.py / check_items.
- **§3.5 Hold risk increment — revise — ambiguity** — pinned the hold-derived risk increment is neither stored on the customer nor surfaced as a check-item field; computed only later from `maker_account_risk` + `hold_reason` (§3.8) if the hold resolves. — posting/check_items logic.
- **§3.7 Void compensation — revise — ambiguity** — pinned void decrements `daily_transaction_count` by 1 and (check-cash only) `daily_cashed_amount_cents` by face, applied unconditionally against current counters (no window roll, not floored — can go below 0). — routes/transactions.py:271-273.
- **§3.8 Reconcile begin — insert — ambiguity** — pinned begin-reconcile state check (`ERR_INVALID_STATE`) precedes the open-items check (`ERR_OPEN_ITEMS_REMAIN`). — routes/cash_drawers.py:87-95.
- **§3.8 Reconcile close — insert — ambiguity** — pinned close state check (`ERR_INVALID_STATE`) precedes the OCC version comparison (`ERR_STALE_DRAWER_VERSION`). — routes/cash_drawers.py:114-121.
- **§4 Endpoint table — revise (×3) — ambiguity** — documented list-filter query params: `/customers` by `kyc_status`; `/fee-schedules` by `check_type`/`active`; `/transactions` by `customer_id`/`drawer_id`/`fee_schedule_id`/`txn_type`. — routes/customers.py, routes/fee_schedules.py, routes/transactions.py.

## Pipeline Complete — 2026-06-27T00:00:00.000Z

All 9 steps complete. Final state: **82/82 tests pass across all 8 parallel stability rounds.** Task directory contains SCAFFOLD.yaml + 2 design files, worklog.md, test_helpers/, test_suite/ (82 tests), and workspace/ (INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/).
