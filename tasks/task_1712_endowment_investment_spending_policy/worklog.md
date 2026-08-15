# Worklog — task_1712_endowment_investment_spending_policy

## Step 1: Create Task Directory — 2026-08-14T10:01:00.000Z

Task directory `tasks/task_1712_endowment_investment_spending_policy/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions. Difficulty target: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-14T11:19:00.000Z

All three artifacts are written and lint-clean. Summary:

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1712_endowment_investment_spending_policy/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (111 KB); no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

**Counts**: 14 entities · 12 state machines (10 entities; Fund carries two parallel machines: lifecycle × spending posture) · 11 calculations · 30 validations (priorities 1–30) · 73 endpoints · 30 errors · 5 roles (all `opaque`, segregation-of-duties model) · 2 OCC concurrency rules · 19 §1.8 difficulty instances (every rule ≥2; combinatorial_formula has 3 — one per mode a/b/c) · 46 active §1.9 corner instances + 9 `excluded_because` stubs.

**Lint verdict (verbatim)**: "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." (985 calls scanned across both design files.)

**Notable design decisions**:
- **Integer-exact unitization**: prices in millicents, units in micro-units (value = units × price / 1e9), inception price 100000, and a pinned price floor of 1 millicent for the pathological MV=0-with-units case. All §1.8 numeric asserts were precomputed by hand (e.g., gift estimate 50000000000 vs actual 41666666667; band cap 807300 clamping raw 830050; Dietz 1200 vs simple 1500 bps; per-gift rounding 6666 vs 6667 micro-units).
- **Epoch-driven determinism**: no wall-clock anywhere — quarters advance only via valuation finalize (ops-run checkpoint), so no `/_clock` endpoint was needed.
- **The layered core**: `quarter_close_pipeline` pins a 9-step evaluation order (price from pre-flow units → lapse sweep → unitization → HGV → underwater/posture → exception expiry cascade → drift → epoch), which anchors the Rule 2(c), Rule 4 depth-3 cascade (finalize → exception EXPIRED → distribution reverts → posture flips), and Rule 9 sweep-conservation instances.
- **Two genuinely different OCC races** (§1.2.1): finalize and policy-adopt on `EndowmentPool.version`, each replayed with strictly sequential requests (suspend/resume or a prior adopt supplies the version bump).
- **Distinct interval semantics for Rule 8**: half-open strictly-increasing policy effective-year windows vs inclusive closed manager-coverage intervals (terminated managers still block their historical quarters; adjacency `end+1` allowed).
- **Compliance-heavy validation lattice**: donor-purpose safety before fiscal caps, state before safety, uniqueness before windows, OCC at priority 8; every one of the 30 error codes has at least one triggering recipe.
- Replay audit caught and fixed pre-lint: an activation-deadlock (pledged corpus now counts PLEDGED gifts), a stale OCC capture in the review-loop instance, an off-by-one in manager coverage_end (added the Q3 finalize), the TERM-maturity inception-price interaction (moved the crash to Q2, term_end=3), and a dead `VALUATION_REVERSAL` enum value (removed).

## Step 3: Copy Shared Files — 2026-08-14T11:22:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1712_endowment_investment_spending_policy/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T11:35:00.000Z

PRD generation is complete. Summary follows.

---

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1712_endowment_investment_spending_policy/workspace/PRD.md` — **341 lines**.

### Section list
- **§1. Introduction** (2 paragraphs, business-context angle)
- **§2. Global Specifications** — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination; 2.4 Common Resource Properties and Monetary Conventions; 2.5 Pool Epochs, Quarters, and the Inception Price; 2.6 Pool Posture as a Global Gate; 2.7 Optimistic Concurrency Control on the Pool; 2.8 Validation Evaluation Order; 2.9 Uniqueness and Duplicate Detection
- **§3. Business Logic & Workflows** — 12 subsections organized by entity-lifecycle/process: 3.1 Pools/Funds/Donor Restrictions; 3.2 Gifts; 3.3 Spending Policy Versions; 3.4 Quarterly Valuation & Close Pipeline; 3.5 Spending Distributions; 3.6 Underwater Policy Exceptions; 3.7 Program Payouts & Lapse Sweep; 3.8 Corpus Redemption; 3.9 Target Allocations & Drift; 3.10 Managers & Performance Streaks; 3.11 Annual Reporting; 3.12 Unit Ledger
- **§4. Endpoint Definitions** — 4-column table, all 68 scaffold endpoints
- **§5. Error Code Catalogue** — 2-column table, all 30 error IDs

### Scaffold coverage
Fully covered: `entities` (all 14, including `UnitLedgerEntry`'s `common_fields: false` called out explicitly), `state_machines` (all 11 machines, every transition with preconditions + side effects + cross-entity cascades), `calculations` (all 9 — unit price both variants, gift unitization with tie-break ordering, Modified Dietz + flow-blind simple return with exact integer arithmetic and multiply-before-divide, excess streaks with exact-equality thresholds, smoothed base with pinned round-per-quarter-then-average-then-round order, distribution amount with cap-then-floor nested clamp, redemption units with dust rule, underwater flag with strict-less-than boundary, allocation drift with strict-greater-than breach, lapse sweep with conservation identity, and the pinned 9-step quarter close pipeline including the pre-flow-units circularity resolution), `validations` (all 30 priorities enumerated in explicit evaluation order in §2.8, each with its `error_id`; every `applies_to` scope enumerated), `concurrency_rules` (OCC on finalize/supersede/adopt with `expected_pool_version` and `ERR_STALE_POOL_VERSION`/412, no race framing), `response_envelope`, `endpoints`, `errors`, and all 5 `roles` with opaque-identity prose.

### Hard-contract results
- **Contract 1 (Field-Name Coverage):** PASS — 120 required, 120 present, 0 missing. First pass missed 7 path-param names (`valuation_id`, `gift_id`, `exception_id`, `payout_id`, `allocation_id`, `report_id`, `entry_id`); repaired by adding one natural sentence each in the owning §3 subsection; second pass clean.
- **Contract 2 (Rule Coverage):** PASS — validation priority ordering expressed as an explicit ordered list (not text order); both OCC rules name write operation + `expected_pool_version` + `ERR_STALE_POOL_VERSION` + 412; all cross-entity side effects stated (supersede rollback, exception exercise/expiry/rescission cascades, sweep gift creation, donor/fund compensation on cancel/rescind); all applies_to scopes enumerated; structured field content (defaults, nullability, initial values) placed on owning entities; sibling branches (cancel by role, three exception exits, drift both directions, four streak transitions, partial vs full spending reports) rendered with equal density.
- **Contract 3 (§3 Path Purity):** PASS — 635 backticked tokens scanned in §3, 0 path-like, 0 bare HTTP methods, 0 method+path combos. Endpoints referenced via state-transition framing and role+verb throughout.

### Coverage-audit findings (rules surfaced into prose for the Zero-Silence Rule)
- The seven pure path-param identifiers noted above had no natural narrative anchor and were added inline in their owning workflow subsections.
- `UnitLedgerEntry` lacks `updated_at`/`version` (`common_fields: false`) — stated explicitly in §2.4.
- The OCC validation (priority 8) covers **three** endpoints (finalize, supersede, adopt) while `concurrency_rules` names only two — both surfaces were reconciled by listing all three in §2.7.
- Validation 9's check text mentions corpus redemption but its `applies_to` is payouts only; the corpus-redemption class rule is carried by priority 12/`ERR_CORPUS_INVIOLABLE` — placed in §3.8 accordingly.
- The two exemption formulas (distribution-side: `current_quarter_index >= term_end_quarter_index`; posture-side: finalized quarter reaching the term end) were both rendered precisely in their respective subsections rather than collapsed.
- Preliminary unit price floor (`max(1, ...)`) appears only in the calculation's second paragraph — surfaced in §3.4 alongside the final-price floor.

[Orchestrator note: subagent summary said "68 endpoints" but PRD §4 table contains all 73 scaffold endpoints (verified by grep); the "68" was a summary misstatement.]


## Step 5: Generate Unit Tests — 2026-08-14T12:10:00.000Z

All 84 tests collect cleanly. Generation complete. Final summary:

## Deliverables

**`test_helpers/`** (Stage 1): `types.py` (14 entity TypedDicts — `UnitLedgerEntry` correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (54 endpoint methods), `api_errors.py` (29 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (all five roles are opaque per PRD §2.1, so shared constants plus `make_*_headers` builders for segregation-sensitive flows), `fixtures.py` (atomic step helpers + composite world builders: `setup_pool_world`, `setup_zero_manager_pool`, `setup_funded_world`, `setup_underwater_world`, `setup_exception_world`, `setup_distributed_world`, `setup_disbursed_payout_world`, and `finalize_open_quarter` with fresh OCC version reads), `__init__.py` barrel.

**`test_suite/`** (Stage 2): `conftest.py` + 10 test files, 84 tests, all collecting under pytest.

## Counts

- **Queue A (Difficulty): 38 tests** — all 19 instances × 2 tests each; zero skipped.
- **Queue B (Corner): 46 tests** — all 46 non-stub instances × 1 test each; zero skipped for coverage/derivability failure.
- Per file: test_01=9, test_02=8, test_03=7, test_04=8, test_05=9, test_06=6, test_07=5, test_08=12, test_09=11, test_10=9.

## Skipped instances

Only the 9 `excluded_because:` stubs, whose difficulty cross-references all resolve (verified programmatically): `smoothed_base_excludes_quarters_before_first_unitization`, `computed_fund_market_value_visible_on_read_after_finalize`, the 5 `errors` section stubs, `dual_variant_calculation_layer_coverage`, `transitive_cascade_layer_coverage`.

## Assertion-level relaxations (instances still translated; noted for the record)

1. `Corner/entities/pool_creation_applies_system_defaults` — dropped the `version == 1` sub-assertion: PRD §2.4 pins "increments by 1 on every mutation" but never states the initial value, so two PRD-only readers could diverge. The five other defaults are verbatim-covered and asserted.
2. `Corner/cross_cutting_complexity_layers/occ_finalize_rejected_with_stale_pool_version_then_recovers` — absolute `version == 4` replaced with PRD-derived relative increments (`+2` across suspend/resume per §2.6, `+1` after finalize per §3.4).
3. `Difficulty/compensating_invariant/pool_unit_identity_conserved_across_unitize_redeem_and_corpus_redeem` — ledger `amount_cents` sign assertion dropped (PRD says "signed cash value" without pinning redemption sign convention); `units_delta_micro == -10000000000` retained as uniquely derivable.

## Self-audit verdicts

- **Stage 1**: PASS — helpers import cleanly against the framework; all generic utilities come from `prd_bench_local_runner.testing`; `set_error_http_status_map` registered at import.
- **Stage 2**: PASS — 84/84 tests carry exactly one terminal `Design:` tag; all tags resolve to real instances (0 stub-pointing or unresolved tags); queue A ≥2 and queue B ≥1 coverage verified; every quoted citation fragment survives a whitespace-normalized literal grep of PRD.md (0 misses); no `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; pytest collects all 84 tests with no errors.

## Step 6: Generate Implementation — 2026-08-14T12:15:00.000Z

All verification is complete. Final summary:

## Implementation Summary — task_1712_endowment_investment_spending_policy

### Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1712_endowment_investment_spending_policy/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 70 | Flask entry, blueprint registration, error handlers, `0.0.0.0:$PORT` |
| `db.py` | 49 | In-memory store (14 dicts keyed by id), version/timestamp helpers |
| `errors.py` | 45 | All 30 error IDs with HTTP statuses, `ApiError` |
| `response.py` | 48 | Envelope: `meta`/`response_type`/`data`, pagination meta |
| `middleware.py` | 24 | `X-User-ID`/`X-User-Role` auth + role check |
| `util.py` | 109 | ISO-8601 3-digit timestamps, Decimal ROUND_HALF_UP math, body validators |
| `constants.py` | 28 | Scaffold constants + enums |
| `routes/pools.py` 97 · `policies.py` 153 · `valuations.py` 253 · `donors.py` 42 · `funds.py` 229 · `gifts.py` 176 · `distributions.py` 325 · `exceptions.py` 192 · `payouts.py` 161 · `allocations.py` 143 · `managers.py` 145 · `manager_reports.py` 130 · `reports.py` 218 · `ledger.py` 28 | | Route handlers with PRD §2.8 validation priority order |
| `services/calc.py` | 81 | Unit prices, Dietz/simple returns, streak thresholds, MV |
| `services/spending.py` | 128 | Applicable-policy lookup, smoothed base (per-quarter round → average → round), band clamp, underwater gate |
| `services/pipeline.py` | 314 | 9-step quarter-close pipeline, supersede rollback, ledger emission, exception cascades |
| `services/domain.py` | 166 | Pool posture gate (SUSPENDED blocked set / TERMINATED read-only), exemption, pagination/filter helper |

### Endpoint coverage
**73/73** routes from PRD §4 implemented (verified via Flask url_map count).

### Calculations & state machines
- `services/calc.py`: preliminary/final unit price (inception 100000, floor 1 millicent, pre-flow units), Modified Dietz + flow-blind simple returns (exact integer arithmetic, ×before÷), excess streaks with exact-equality auto-transitions (ENGAGED→WATCHLIST at 3, →PROBATION at 6, recovery at nonneg 2).
- `services/spending.py`: applicable policy (max effective ≤ FY among ADOPTED/SUPERSEDED), smoothed base via ledger replay with pinned rounding order, band clamp (cap then floor), underwater/exception final amount.
- `services/pipeline.py`: pinned 9-step finalize (price → lapse sweep at age ≥ 4 with `SWEEP-<payout_id>` reinvestment gifts → per-gift unitization ordered created_at/external_ref → HGV → MV/underwater → posture NORMAL↔SPENDING_SUSPENDED → exception expiry at FY-last-quarter with distribution reversion → allocation drift with ack reset → epoch advance + pool version bump); supersede rollback restoring pool epoch/price/MV and allocation drift snapshot; exercise/expiry/rescission cascades.
- State machines for all 14 entities incl. parallel Fund dimensions (`fund_status` × `spending_posture`), OCC `expected_pool_version` (ERR_STALE_POOL_VERSION 412) on finalize/supersede/adopt, segregation-of-duties (3-person exception rule) at priority 3, and the full §2.8 validation ordering.

### Verification
- `prd-bench-local-run --isolation per-test-server`: **77/84 passed**. The 7 failures are test-suite authoring bugs, not implementation defects: `test_02` uses `receive_gift` without importing it (4 tests), `test_04` uses `setup_pool_world` without importing it (1 test), `test_05`'s module-level helper `_setup_terminated_manager_world()` references the `api` fixture as a global (2 tests). All calculation-heavy tests pass (Dietz divergence, per-gift rounding, band clamps, supersede lock/rollback, exception expiry cascade, lapse sweep conservation, drift band equality, streak thresholds).
- Two additional custom end-to-end smoke suites (auth envelope, suspension gate, OCC, underwater exception lifecycle, sweep, supersede, corpus redemption, termination gates, pagination) pass 100%.

### start.sh contract
Reads `$PORT` (default 10000), binds `0.0.0.0`, runs in foreground via `exec python3 app.py`, and guards the pip install behind `python3 -c "import flask"` so per-test reboots are no-ops. Storage is purely in-memory dicts; nothing is seeded at startup — every boot is completely fresh.

## Step 7: Run Tests and Iterate — 2026-08-14T12:25:00.000Z

**Summary**

- **Iterations run:** 1 (single 8-round parallel stability sweep executed after the initial fixes; no further iterations required).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1712_endowment_investment_spending_policy/test_suite/test_02_funds_gifts_donors.py` — tests `test_gift_receive_transitions_pending_to_received`-adjacent block plus `test_receive_is_idempotent_on_already_received_gift`, `test_donor_total_gifts_sum_across_received_gifts`, `test_donor_total_ignores_pending_gifts`, and 2 others calling bare `receive_gift(...)`: added missing `receive_gift` to the `from test_helpers import (...)` block; 6 bare calls raised `NameError`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1712_endowment_investment_spending_policy/test_suite/test_04_quarter_close_and_valuation_governance.py` — test at line ~191 (`ctx = setup_pool_world(pool_name="Pool RC")`): added missing `setup_pool_world` to the `from test_helpers import (...)` block; bare call raised `NameError`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1712_endowment_investment_spending_policy/test_suite/test_05_manager_performance.py` — module-level helper `_setup_terminated_manager_world()` referenced the `api` pytest fixture as a global inside `api.terminate_manager(...)`; changed signature to `_setup_terminated_manager_world(api)` and updated both callers (`test_manager_coverage_adjacent_start_after_termination_engages`, `test_manager_coverage_start_inside_closed_interval_conflicts`) to pass the fixture through. Pure authoring fix; no assertion altered in any file.

- **Final 8-round sweep results (passed/total per round):**
  - Round 1: 84/84
  - Round 2: 84/84
  - Round 3: 84/84
  - Round 4: 84/84
  - Round 5: 84/84
  - Round 6: 84/84
  - Round 7: 84/84
  - Round 8: 84/84

Union of failures across all 8 rounds: empty. All prior 7 failures traced to the three test-suite authoring bugs above (verified, not taken on trust); hand-off attribution was accurate.

## Step 8: Finalize PRD — 2026-08-14T12:35:00.000Z

Step 8 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1712_endowment_investment_spending_policy/workspace/PRD_FINALIZED.md` is written and is **byte-identical to PRD.md** — no edits were warranted.

**Line counts / %-delta:** PRD.md = 341 lines, PRD_FINALIZED.md = 341 lines, delta = 0%.

**Changes:** none.

**Rationale — per Step 7 item investigation:**

1. **test_02_funds_gifts_donors.py (missing `receive_gift` import)** — Pure authoring fix. `receive_gift` at `test_helpers/fixtures.py:174` is a thin wrapper: `get_success_data(api_client.receive_gift(gift_id, DEV))`. The bare calls raised `NameError` only because the name was absent from the test's import block; the same tests exercise `api.receive_gift(...)` with explicit headers elsewhere (lines 112, 150, 178). No behavioral choice was left open by the PRD — the endpoint's semantics were never in question. Pre-edit search (subject: receive-gift behavior): enumerated the helper, the api_client method (`test_helpers/api_client.py:96`), and all test callsites — all consistent with PRD as written; no wording change needed.

2. **test_04_quarter_close_and_valuation_governance.py (missing `setup_pool_world` import)** — Pure authoring fix. `setup_pool_world` at `test_helpers/fixtures.py:371` is a composite world-builder (pool + 100% single-class target allocation + optional engaged manager). The bare call at line ~192 raised `NameError`; adding the import changed no assertion. No PRD silence. Pre-edit search (subject: pool world setup / target allocations / engaged manager): enumerated the helper body and its callees — behavior is test scaffolding, not an API surface the PRD specifies; no wording change needed.

3. **test_05_manager_performance.py (`_setup_terminated_manager_world(api)` fixture pass-through)** — Pure pytest fixture plumbing: the module-level helper referenced the `api` fixture as a global; the fix threads it as a parameter through both callers. No assertion touched, no behavioral implication. Pre-edit search (subject: manager termination and coverage-conflict behavior): enumerated `api.terminate_manager` callsites (line 152, 198) and both caller tests — all consistent with PRD as written; no wording change needed.

No implementation fixes, no test deletions, and no test_helpers fixes occurred in Step 7, and the final 8-round sweep was 84/84 with an empty failure union. Per the instructions, no edits were manufactured.

## Step 9: Complete PRD — 2026-08-14T13:00:00.000Z

All edits are in place. The diff shows exactly 21 hunks and no unintended changes. Task complete.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (341 lines / 63,162 chars) → `PRD_COMPLETED.md` (342 lines / 66,012 chars), char-delta **+2,850**. One line was added (a new bullet in §2.2); all other changes are inline in-paragraph revisions.

**Counts**: 20 ambiguity-pins, 3 mismatch-revisions (21 diff hunks; some hunks carry two pins).

**Ambiguity-pins** (PRD silent → pinned to impl behavior):

- §2.1 — revise — whitespace-only header values count as empty — `implementation/middleware.py:14`
- §2.2 — insert — transport-level failures use the error envelope: unsupported method → `ERR_NOT_FOUND` at HTTP 405; unexpected failure → `ERR_INVALID_REQUEST` at HTTP 500 — `implementation/app.py:55-66`
- §2.3 — revise — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST`, `offset` ≥ 0; `created_at` sort ties broken by insertion order; §4 filters are exact-match, conjunctive, unparseable numeric filter matches nothing — `implementation/services/domain.py:98-158`
- §2.4 — revise — `version` starts at 1 at creation; `updated_at` refreshed on every mutation — `implementation/db.py:32-44`
- §2.6 — revise — a `TERMINATED` pool rejects every pool-scoped mutation with `ERR_POOL_SUSPENDED` (HTTP 409) — `implementation/services/domain.py:44-48`
- §2.8 — revise — body-shape check (4) includes well-formed JSON object bodies — `implementation/util.py:37-55`
- §3.2 — insert — gifts may be recorded against `DRAFT` or `ACTIVE` funds; a `TERMINATED` fund rejects recording with `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/gifts.py:40-44`
- §3.4 — revise — a new valuation is born with `final_pool_market_value_cents` null — `implementation/routes/valuations.py:63`
- §3.4 — revise — supersede request carries `revised_pool_market_value_cents` of at least 0 — `implementation/routes/valuations.py:167`
- §3.4 — insert — supersede rollback also refreshes each fund's `market_value_cents`/`is_underwater` at the restored price — `implementation/services/pipeline.py:312-314`
- §3.4 — insert — supersede responds HTTP 201 carrying the corrective `PRELIMINARY` valuation — `implementation/routes/valuations.py:253`
- §3.5 — revise — a new distribution is born with `proposed_by_user_id` and `approved_by_user_id` null — `implementation/routes/distributions.py:90-91`
- §3.5 — insert — distribute with zero `final_amount_cents` is rejected with `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/distributions.py:243-247`
- §3.5 — revise — either authorized role may cancel `PROJECTED`/`PROPOSED`/`REVISION_REQUESTED`; `DISTRIBUTED`/`CANCELLED` cannot be cancelled; a `DevelopmentOfficer` cancelling `APPROVED` gets `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/distributions.py:292-313`
- §3.6 — revise — expiry cascade reverts linked `APPROVED` distributions to `PROPOSED` with `applied_exception_id` and `approved_by_user_id` cleared — `implementation/services/pipeline.py:60-75`
- §3.7 — insert — payouts sweep in ascending `created_at` order; the sweep gift's `provisional_units_estimate_micro` is computed from the pool's pre-close `current_unit_price_millicents` — `implementation/services/pipeline.py:111-134`
- §3.8 — revise — corpus redemption requires an `ACTIVE` fund and a positive integer `amount_cents` (≥ 1) — `implementation/routes/funds.py:187-193`
- §3.9 — revise — within-`items` duplicates rejected with `ERR_DUPLICATE_RECORD`; unchanged matching rows left untouched; new rows start `actual_pct_bps` 0 / `IN_BAND` / `drift_acknowledged` false; response is HTTP 200 `response_type: "array"` of the full post-replacement rows in `created_at` order with no pagination fields in `meta` — `implementation/routes/allocations.py:49-104`, `implementation/response.py:20-25`
- §3.10 — revise — `flows` may be omitted entirely, defaulting to an empty array — `implementation/routes/manager_reports.py:23-25`
- §3.11 — insert — a supplied `fund_id` must reference a fund of the report's pool, else `ERR_INVALID_REQUEST` — `implementation/routes/reports.py:52-58`

**Mismatch-revisions** (PRD described different behavior → aligned to impl):

- §3.4 (pipeline step 2) — revise — cross-reference `(§3.8)` corrected to `(§3.7)` (the lapse sweep lives in §3.7, not Corpus Redemption) — `implementation/services/pipeline.py:110`
- §3.4 (pipeline step 7) — revise — cross-reference `(§3.7)` corrected to `(§3.6)` (exception expiry lives in §3.6) — `implementation/services/pipeline.py:208`
- §3.12 — revise — `reference_id` enumeration corrected: `GiftContribution` for `GIFT_UNITIZE`, swept `ProgramPayout` for `REINVEST_UNITIZE`, `SpendingDistribution` for `DISTRIBUTION_REDEEM`, and **the `Fund` itself for `CORPUS_REDEEM`** (PRD had listed a "superseding `UnitValuation`" that never occurs and omitted the Fund) — `implementation/routes/funds.py:222-225`, `implementation/services/pipeline.py:165-169`, `implementation/routes/distributions.py:264-271`

Verification notes: validation-ordering (§2.8) was checked against every route's actual check sequence and already matches; the §2.6 SUSPENDED blocked-set was verified endpoint-by-endpoint (including the negative space — fund create, gift create/cancel/rescind, exception workflow, manager register/decline/terminate, report workflow, spending reports, and drift acknowledgement are all allowed on a `SUSPENDED` pool, matching the PRD's exact blocked set). No changes were needed in §2.5, §2.7, §2.9, §3.3, §3.10 (Dietz/streak math), or the §4/§5 tables.
