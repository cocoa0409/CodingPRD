## Step 2: Generate Scaffold — 2026-08-15T01:58:00.000Z

Scaffold generation complete for task 1927. All three artifacts are written and lint-clean.

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_1927_trade_order_management_allocation/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1927_trade_order_management_allocation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1927_trade_order_management_allocation/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**
- Entities: **14** (Account, Security, Broker, CommissionBudget, Restriction, Order, BlockOrder, Fill, AllocationPlan, Allocation, TradeError, SettlementInstruction, Position, AuditEvent)
- Endpoints: **57** (deliberately beyond the Expert 20–32 guideline per the harder-than-expert directive; includes one test-driving `POST /trading/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default)
- Calculations: **6** (block_average_price w/ PROVISIONAL vs FINAL_BATCH variants, allocation_quantity_split w/ PRO_RATA vs EQUAL_SPLIT, commission_per_line w/ pinned per-line-then-sum rounding, budget_accrual_check threshold, position_net_qty, settlement_schedule)
- State machines: **11** (Order with compliance re-check + attach/detach + correction loops; BlockOrder with parallel `status × allocation_status` dimensions; AllocationPlan DRAFT↔PROPOSED revision cycle + supersede; Allocation error cycle; SettlementInstruction fail/repair cycle; Restriction activate/suspend cycle; Account/Security/Broker suspend cycles; CommissionBudget, TradeError)
- Errors: **47**; Validations: 12 ordered priorities (incl. custom `request_shape` tier and pinned state sub-ordering); Roles: 6 (segregation_of_duties model, all opaque); OCC concurrency rules: 1 (`plan-create-stale-block`, 412 ERR_STALE_VERSION)

**Difficulty layers applied (§0.2, 4):** dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers. Archetype: compliance/audit + quota/allocation; flat topology; cyclic shape; segregation-of-duties role model.

**§1.8 instances:** 18 total — 2 per rule: dual_variant_calc (avg-price 1667/2200/1800 divergence; PRO_RATA vs EQUAL_SPLIT [100,300] vs [200,200]), combinatorial_formula (mode (a) largest-remainder [3,3,1] w/ deviation 2857bp; mode (b) per-line commission rounding 2+2≠3), non_linear_state_machine (Order loops; SettlementInstruction fail/repair retaining fail_count), transitive_cascade (plan-post chain plan→allocation→position/budget/order/instruction; fail-escalation SI→Account SUSPENDED→Order CANCELLED), priority_pair_validation_conflict (state-vs-fiscal; safety-vs-temporal), boundary_precision_check (budget exact-equality EXHAUSTED; empty-batch ERR_NOTHING_TO_ALLOCATE), cross_entity_state_dependency (Order→Security; BlockOrder→Broker), resource_temporal_overlap (half-open budget periods vs closed restriction windows with shared-endpoint conflict), compensating_invariant (WRONG_QTY block-quantity conservation 70+30=100; WRONG_ACCOUNT firm-position conservation Σ=100).

**§1.9 instances:** **52** (44 active + 8 `excluded_because:` stubs) across all nine guide sections, covering every error code, invalid-from transitions, terminal lockdowns, RBAC denials, pagination/filtering, audit-trail retention, OCC, and dismissal/price-correction compensation.

**Quality Checklist:** passed — machine lint verdict verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (851 calls scanned). Additional scripted audits passed: no forbidden race vocabulary, instance names unique across both files, zero unbound `${var}` placeholders, all grounds resolve to §1.1–§1.7, all enum states reachable, every error code referenced, endpoint roles ⊆ RBAC, stub references resolve. All formula-derived asserts were pre-computed as literals (VWAP 1667/1800/2200, deviations 714/2857/3333/10000bp, commissions 2/350/500/600, settle dates 2026-08-02/03, fail boundary 2026-08-03 vs 04).

## Step 3: Copy Shared Files — 2026-08-15T01:59:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1927_trade_order_management_allocation/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T02:03:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1927_trade_order_management_allocation/workspace/PRD.md` — **336 lines**. The two forbidden index files were never opened; no sibling task directories were inspected.

## Section list

- **§1 Introduction** (2 paragraphs: business pipeline context + system invariants/logical clock)
- **§2 Global Specifications** — 2.1 Role-Based Access Control · 2.2 API Response Structure (verified byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Versioning · 2.5 The Desk Logical Clock · 2.6 Money, Precision and Rounding · 2.7 Concurrency Control on Plan Creation · 2.8 Validation Priority and Error Ordering · 2.9 Resource Resolution and Path Semantics · 2.10 Audit Trail and Retention
- **§3 Business Logic & Workflows** (9 subsections, lifecycle grouping) — 3.1 Reference Data (Accounts/Securities/Brokers) · 3.2 Commission Budgets · 3.3 Restriction Rules · 3.4 Order Capture & Pre-Trade Compliance · 3.5 Block Assembly · 3.6 Routing, Fills & Average Price · 3.7 Allocation Plans (Propose/Approve/Post) · 3.8 Trade Errors & Corrections · 3.9 Settlement, Fail Escalation & Positions
- **§4 Endpoint Definitions** — 57-row table, 4 columns (Method / Path / Description / Authorized Roles)
- **§5 Error Code Catalogue** — 47-row table, 2 columns (Error ID / HTTP Status)

## Zero-Silence Rule / Hard Contract reports

**Contract 1 — Field-Name Coverage:** 89 unique identifiers required (all 14 entities' fields, all endpoint request-body keys, all query params, common fields, and response-only keys like `current_utc`/`checked_count`/`failed_instruction_ids`); 89 present in backticks, 0 missing. **PASS**

**Contract 2 — Rule Coverage:** all 11 state machines' transitions (incl. BlockOrder's 4 parallel `allocation_status` transitions and the COMPLIANCE_REJECTED self-loop/re-check siblings) expressed with preconditions + error IDs + side effects; all 6 calculations in reconstructible prose (both VWAP variants, both split methods with floor + largest-remainder ranking, fairness deviation with the 99999 cap and 200 bp tolerance, pinned per-line commission rounding, `==`-exhausts/`>`-rejects budget boundary, signed positions, strictly-greater overdue boundary); the 12-level validation priority ladder stated in §2.8 including the attach/detach and safety sub-orderings; the 1 OCC rule names endpoint + `expected_block_version` + `ERR_STALE_VERSION` (412); all 47 error IDs appear in §2/§3 narrative (not just §5); all 44 audit action tags named; sibling branches (cancel/retire/supersede/instruction-cancel from three states, three correction types) rendered with equal density. **PASS**

**Contract 3 — §3 Path Purity:** 215 distinct backticked tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. **PASS**

**One scaffold inconsistency resolved:** the `Allocation.commission_cents` field description divides by 1,000,000, while the authoritative `commission_per_line` calculation (with pinned constant `BP_DENOMINATOR: 10000` and basis-point semantics for `commission_rate_bp`) divides by 10,000. The PRD follows the calculations table ("divided by ten thousand"), which is the dimensionally correct reading and the table the test generator walks.

## Step 5: Generate Unit Tests — 2026-08-15T02:24:00.000Z

Generation complete. All artifacts are in place and self-audited.

## Summary

**Files generated**

`test_helpers/` (Stage 1):
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 14 status/type enums + 14 entity TypedDicts; Fill and AuditEvent correctly omit `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 45 methods, one per endpoint
- `api_errors.py` — `ApiErrorId` (46 ids) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions incl. hard absence of `version`/`updated_at` on fills/audit events
- `factories.py`, `constants.py` (FAIRNESS_TOLERANCE_BP=200, lags 1/2, FAIL_GRACE_DAYS=1, FAIL_ESCALATION_THRESHOLD=2, default clock), `test_users.py` (6 opaque roles + `NO_AUTH_HEADERS`)
- `fixtures.py` — composite chains: `setup_routed_block` / `setup_filled_block` / `setup_posted_plan` / `setup_flagged_error`, plan pipeline (`create_plan_for_block` reads the fresh block version for the OCC guard), settlement lifecycle, listing helpers

`test_suite/` (Stage 2): `conftest.py` + 9 numbered test files.

**Test counts**
- Queue A (Difficulty): 37 tests across all 18 instances (every instance ≥2; `plan_post_state_beats_fiscal` has 3 — conflict test, no-mutation test, and the fiscal-gate control).
- Queue B (Corner): 43 tests across 43 of 44 non-stub instances.
- Total: 80 test functions → 91 collected items (the 404 sweep is parametrized ×12). `pytest --collect-only` passes; all module imports verified against the real framework.

**Skipped instances (gaps left as gaps, no placeholders)**
1. `Corner/validations/plan_stale_batch_rejected_then_recovered_via_supersede` — **PRD contradiction (unique-derivability failure).** PRD §3.7 pins the stale-post rejection to "fills with `fill_seq` beyond `covered_to_seq` now exist **and the block is not yet `FILLED`**", but the instance's recipe posts when the block IS FILLED (50+50=100=total_qty). A literal-PRD implementer *allows* that post; the asserted `ERR_PLAN_STALE_BATCH` is the opposite of the uniquely-derived outcome. (The supersede sub-claim is already owned by `Corner/cross_cutting_complexity_layers/occ_plan_create_stale_version`.)
2. Sub-assertion drops within emitted tests (same filter, assertion level):
   - `account_create_applies_defaults` and `block_initial_state`: dropped the `version == 1` literal — PRD §2.4 pins "+1 per mutation" but never the initial value (0- or 1-based are both faithful). Initial versions are never asserted anywhere; fixtures read versions live.
   - `audit_trail_retention_and_filter`: dropped the "no update/delete endpoint exists" meta-assertion — PRD defines no observable response for such a call. The retention/filter/actor-stamping claims are asserted fully.

**Stub cross-references (queue B):** all 8 `excluded_because:` stubs resolve to real §1.8 instances (`avg_price_provisional_vs_final_batch`, `budget_half_open_period_overlap`, `restriction_closed_window_overlap`, `propose_empty_batch_boundary`, `compliance_check_requires_security_active`, `block_route_requires_broker_active`, `order_compliance_recheck_and_block_membership_cycles`, `plan_post_transitive_cascade`) and were not translated.

**Self-audit results**
- Tag audit (scripted): every test function carries exactly one `Design:` line; all 80 tags resolve to non-stub instances; no tag points at a stub; no untagged/dual-tagged tests. Queue A: 0 instances under-covered; Queue B: exactly the 1 documented skip.
- PRD-citation pass (scripted): all 85 quoted citations of ≥8 words survive a literal whitespace-normalized grep of `PRD.md`. Every asserted `error_id` is named in §2/§3 prose, not just the §5 table (including the priority-ordering claims, cited from §2.8's ladder).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold"/table references in generated comments or docstrings.
- Two-reader sensitive spots handled: `allocated_qty` injected on create asserted ignored+0 (§2.8 "ignored, not rejected"); correction-line price @1000 asserted only because every plausible reading converges on it; detachment asserted as raw 204 (§4 exception) rather than via envelope validator; ordering-dependent allocation assertions key lines by `order_id`, not list position.

## Step 6: Generate Implementation — 2026-08-15T02:24:00.000Z

Implementation complete for task_1927_trade_order_management_allocation. Summary:

## File list under `workspace/implementation/`

- `start.sh` — executable launcher (see below)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app: blueprint registration, global RLock around every request (safe under `threaded=True`), envelope-shaped 404/405/500 fallback handlers, `app.run(host="0.0.0.0", port=$PORT or 10000)`
- `db.py` — in-memory store: one dict per entity keyed by id, position index, global insertion sequence, desk logical clock (default exactly `2026-08-01T00:00:00Z`, monotone, never wall-clock)
- `errors.py` — `ApiError` + the full 47-entry error catalog with exact HTTP statuses
- `response.py` — envelope helpers: `meta.api_request_id` (`req_…`), `api_request_timestamp` (ISO 8601, 3 fractional digits), `response_type` object/array/error, list meta with `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401/403), role gating, body parsing (unknown fields ignored), pagination (default 10, clamped to [1,100]/≥0)
- `audit.py` — append-only AuditEvent writer (request-attributed and `"system"` variants)
- `services.py` — shared logic: order stat recompute, position upsert, budget lookup/accrual (EXHAUSTED at exact equality), account-suspension cascade, allocation split (floor + largest-remainder, fairness vs PRO_RATA ideal always, 99999 cap), VWAP (exact Decimal, ROUND_HALF_UP), per-line commission (`qty*price*rate_bp/10000`, per-line rounding pinned)
- `routes/` — `refdata.py` (accounts/securities/brokers + status), `budgets.py`, `restrictions.py`, `orders.py` (create/compliance-check/cancel), `blocks.py` (assemble/attach/detach/cancel/route/fills), `plans.py` (create-with-OCC/propose/approve/return/post + allocation reads), `corrections.py` (flag-error, correct, dismiss), `settlement.py` (instruct/settle/fail/repair/run-fail-monitor), `misc.py` (positions, audit-events, `_clock/set_current_utc`)

## Endpoint count

**57 endpoints** implemented — every row of the scaffold §1.5 / PRD §4 table, with the documented role gating, status codes (201 creates, 200 actions/reads, 204 detach), and validation priority ladder (auth → shape → existence L-to-R → SoD before state on approve → state → OCC → safety → constraint → temporal → referential → fiscal).

## start.sh behavior

`set -euo pipefail`; `cd` to its own dir; installs deps **only if `import flask` fails** (guarded so per-test reboots skip pip); `exec python3 app.py` in the foreground. Boots well within 60s.

## Boot confirmation

Smoke-tested `bash start.sh` on auto-allocated scratch ports across multiple fresh boots: two end-to-end suites (≈90 assertions) pass — full happy path (accounts → budgets → restrictions → orders → compliance → block → route → fills → plan → propose → approve → post → instructions → settle), plus multi-batch allocation with `FULL→PARTIAL` watermark regression and double version bump, WRONG_QTY correction with ERROR-account residual, dismiss restore, fail-escalation cascade (account suspension at fail_count 2), fail-monitor grace-day boundary, OCC 412, stale-batch 409, SoD-outranks-state 403, unfair-allocation 422, budget exhaustion at exact equality, and envelope/pagination/404 shapes. Server was killed after each run. Storage is module-level dicts only — no files, no seeding; every fresh process boots with `total_count: 0` everywhere.

Notable spec-fidelity decisions (PRD/scaffold-driven, worth knowing): stale-batch post is allowed when the block is already FILLED (pinned double-negative in the spec); a stale APPROVED plan recovers via supersede-by-new-plan (return only accepts PROPOSED); multi-batch propose treats still-attached ALLOCATED/UNDER_CORRECTION orders as members (otherwise the watermark machinery is unreachable); `ERR_STALE_VERSION` only on plan create; commission formula uses the PRD's `/10000` (the entity field's `/1,000,000` is a scaffold typo that PRD overrides).

## Step 7: Run Tests and Iterate — 2026-08-15T02:37:00.000Z

**Exit condition met: all 8 parallel rounds pass — 91/91 in every round.**

## Iterations run
3 eight-round sweeps:
1. **Sweep 1**: 87/91 × 8 — 4 deterministic failures (identical in all rounds).
2. **Sweep 2**: 90–91/91 — the 4 semantic fixes held in all rounds; surfaced 7 transport flakes (`ConnectionResetError`/`IncompleteRead`/`RemoteDisconnected`, one per round, all in long-chain test_08 settlement tests).
3. **Sweep 3**: 91/91 × 8 — clean.

## Tests deleted
None.

## Fixes applied to `test_suite/`
- **`test_03_blocks_fills_and_execution_guards.py::test_overfill_rejected`** — setup fix (STEP 2). The test filled the block to `FILLED` then sent another fill, so the PRD-pinned priority ladder (§2.8: state legality #6 before constraint satisfaction #9; §3.6: fills only against `WORKING`/`PARTIALLY_FILLED`) uniquely determines `ERR_INVALID_STATE`, not the asserted `ERR_OVERFILL`. Reworked to exercise the overfill rule where it uniquely fires: partial fill 60/100, rejected 41 (`ERR_OVERFILL` kept exact), then exact-landing fill 40 → `FILLED` (preserving the PRD's "lands exactly on `total_qty` is accepted" clause).
- **`test_05_plan_posting_cascade.py`** — added missing `post_plan` import (NameError; pure test bug).
- **`test_07_trade_errors_and_corrections.py::test_positions_budgets_and_order_recomputed`** — assertion fix 70 → 100 (STEP 2). PRD §3.8 verbatim: both WRONG_QTY correction lines inherit the original's `order_id` and land `POSTED`; §3.7's recompute sums `alloc_qty` over the order's lines in {POSTED, SETTLED, ERROR_FLAGGED} → 70+30=100 is uniquely determined.
- **`test_07_trade_errors_and_corrections.py::test_second_flag_on_open_error_rejected`** — relaxed exact `ERR_ERROR_ALREADY_OPEN` to `validate_error_is_one_of([ERR_ERROR_ALREADY_OPEN, ERR_INVALID_STATE])` (STEP 1b ERROR PRECEDENCE SILENCE, the sanctioned coverage correction). A line with an OPEN trade error is always `ERROR_FLAGGED`, so both §3.8 rules trip simultaneously and the PRD names both without ordering them.

## Fixes applied to `test_helpers/`
- **`api_client.py::ApiClient.__init__`** — set `session.headers["Connection"] = "close"`. Under per-test-server isolation the server restarts before every test; pooled keep-alive connections from the prior server instance left dead sockets, and the first POST reuse failed with spurious connection errors (urllib3 does not retry POSTs on dropped connections). Fresh connection per request eliminates the flake class; zero assertion changes.

## Fixes applied to `implementation/`
None — the implementation was PRD-faithful on every semantic failure; all failures traced to test artifacts or harness transport.

## Step 8: Finalize PRD — 2026-08-15T02:41:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1927_trade_order_management_allocation/workspace/PRD_FINALIZED.md` is written.

## Line counts / %-delta

- PRD.md: 336 lines, 55,753 chars
- PRD_FINALIZED.md: 336 lines, 55,933 chars — delta +180 chars (+0.32%), zero line-count change (insert made inline within the existing §3.8 paragraph)

## Changes (one bullet per change)

- **§3.8 (Trade Errors and Correction Accounting, flag paragraph)** — insert — added one sentence pinning flag-guard evaluation order: "The from-state guard is evaluated first: a line carrying an OPEN trade error is itself always `ERROR_FLAGGED`, so a repeated flag against such a line surfaces `ERR_INVALID_STATE`." — `implementation/routes/corrections.py:27-31` (from-state check at line 27 precedes the OPEN-error scan at lines 29-31).

## Step 7 diff items that produced NO edit (with verification)

- **test_03 overfill rework** — PRD already uniquely determines behavior: §2.8 ladder rungs #6 (state) < #8 (security gate) < #9 (constraint/overfill) < #10 (temporal) plus §3.6's "fills against a block in any other state are rejected `ERR_INVALID_STATE`". Impl `routes/blocks.py:167-177` evaluates exactly in ladder order (state → security → overfill → fill-before-route), so a fill against a `FILLED` block is `ERR_INVALID_STATE` by the PRD as written. Verbatim kept.
- **test_07 recompute 70 → 100** — PRD §3.8 already says correction lines are "each ... inheriting the original's `plan_id` and `order_id`" (both the primary and the ERROR-account residual), and §3.7 pins the order recompute over lines in {POSTED, SETTLED, ERROR_FLAGGED}; 70+30=100 is uniquely determined. Impl matches: `routes/corrections.py:191-195` sets `order_id = orig["order_id"]` on every correction line; `services.py:43-55` (`recompute_order_stats`, `COUNTING_LINE_STATUSES`) sums over exactly that set. Verbatim kept.
- **test_05 `post_plan` import** — pure test bug (NameError); no behavioral surface. No edit.
- **test_helpers `api_client.py` `Connection: close`** — harness transport fix for per-test-server isolation; no API-contract surface. No edit.

## Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)

**Edit 1 (§3.8 flag-guard ordering):**
- (a) Subject: evaluation order of the two guards at `POST /trading/allocations/{allocationId}/flag-error` — the from-state guard (line must be `POSTED` → `ERR_INVALID_STATE`) versus the already-open guard (no OPEN trade error on the line → `ERR_ERROR_ALREADY_OPEN`).
- (b) Impl paths enumerated and read/grepped: `routes/corrections.py:18-49` (`flag_error` — grep-confirmed it is the only creator of `trade_errors` records and the only raiser of `ERR_ERROR_ALREADY_OPEN`; full check order is request shape → existence → line-state at :27-28 → OPEN-error scan at :29-31); `routes/corrections.py:81-210` (`correct_trade_error` — flips error OPEN→RESOLVED and line ERROR_FLAGGED→REVERSED atomically at :170/:205); `routes/corrections.py:213-229` (`dismiss_trade_error` — flips error OPEN→DISMISSED and line ERROR_FLAGGED→POSTED atomically at :220/:224), together establishing the invariant "line has OPEN error ⟺ line is `ERROR_FLAGGED`", so a second flag always hits the state guard first and the `ERR_ERROR_ALREADY_OPEN` branch is unreachable on reachable inputs; `errors.py:54` (catalogue entry untouched); `services.py:10` and `services.py:75-86` (`ERROR_FLAGGED` membership in counting statuses and correction-context clearing — not described by the edit); `middleware.py`/auth layers (preempt nothing relevant); §2.8 rung 6's named-mismatch list ("`ERR_ERROR_ALREADY_OPEN` at flag") — confirmed the new sentence does not contradict it, since it pins only the order when both guards trip, without declaring the named code dead.
- (c) Wording adjustment: scoped the sentence to the flag operation only and phrased the invariant as observational ("a line carrying an OPEN trade error is itself always `ERROR_FLAGGED`") rather than claiming the already-open check never fires — this keeps §2.8 rung 6 and the §5 catalogue consistent while pinning the impl's observable choice (`ERR_INVALID_STATE` wins) for every reachable input.

## Step 9: Complete PRD — 2026-08-15T02:48:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1927_trade_order_management_allocation/workspace/PRD_COMPLETED.md` — a 15-hunk minimal patch over `PRD_FINALIZED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 336 lines / 56,213 chars → `PRD_COMPLETED.md` 337 lines / 58,077 chars (+1 line, +1,864 chars).

**Counts:** 13 ambiguity-pins, 3 mismatch-revisions (16 edits in 15 hunks).

**Ambiguity-pins (insert):**
- §2.2 — insert — ambiguity — error envelope also frames below-routing failures: unmatched path → 404 `ERR_NOT_FOUND`, wrong method → 405 `ERR_METHOD_NOT_ALLOWED`, server fault → 500 `ERR_INTERNAL`, outside the §5 catalogue — implementation/app.py:43-54
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit into [1,100], offset to ≥0); non-integer values rejected `ERR_INVALID_REQUEST` — implementation/middleware.py:82-97
- §2.7 — insert — ambiguity — `expected_block_version` required only to be an integer, no positivity constraint (non-matching → 412 regardless of sign) — implementation/routes/plans.py:36-38
- §2.8 rung 3 — insert — ambiguity — uniqueness of `account_code`/`ticker`/`broker_code` enforced at request-shape rung as `ERR_INVALID_REQUEST` — implementation/routes/refdata.py:27-29, 80-82, 129-131
- §2.8 rung 9 — insert — ambiguity — non-empty-block constraint applies "at routing or plan proposal" — implementation/routes/plans.py:93-95
- §3.1 — insert — ambiguity — provided `currency` must be a non-empty string (omitted → USD) — implementation/routes/refdata.py:71-73
- §3.1 — insert — ambiguity — `commission_rate_bp` accepts any positive number, integer or fractional — implementation/routes/refdata.py:121-123, implementation/util.py:86-88
- §3.4 — insert — ambiguity — compliance-check legal only from `PENDING_COMPLIANCE`/`COMPLIANCE_REJECTED`; any other state → `ERR_INVALID_STATE` — implementation/routes/orders.py:103-105
- §3.5 — insert — ambiguity — attach responds 200 with the updated order — implementation/routes/blocks.py:83
- §3.7 — revise — ambiguity — at propose, `ERR_EMPTY_BLOCK` is evaluated before `ERR_NOTHING_TO_ALLOCATE` — implementation/routes/plans.py:93-99
- §3.8 — revise — ambiguity — WRONG_ACCOUNT: differs-from-original (`ERR_INVALID_REQUEST`, request-shape rung) evaluated before target-ACTIVE (`ERR_ACCOUNT_SUSPENDED`) — implementation/routes/corrections.py:103-114
- §3.8 — insert — ambiguity — correction budget gate for the original line's own account nets the original `commission_cents` out of the accrual before adding recomputed commissions — implementation/routes/corrections.py:160-162
- §3.9 — insert — ambiguity — repair retains the last `fail_reason` as well as `fail_count` — implementation/routes/settlement.py:122-131

**Mismatch-revisions:**
- §3.7 — revise — mismatch — member orders at propose are attached orders in `BLOCKED`, `ALLOCATED`, or `UNDER_CORRECTION` (not "still BLOCKED"), enabling later-batch proposals — implementation/services.py:11, 95-100
- §3.7 — revise — mismatch — post gate order: per-line account-ACTIVE (`ERR_ACCOUNT_SUSPENDED`) fires before staleness (`ERR_PLAN_STALE_BATCH`), then budget gates; prose previously sequenced staleness first — implementation/routes/plans.py:181-191
- §3.7 — revise — mismatch — posting a later batch over an already-`ALLOCATED` order keeps its status, recomputes stats and bumps `version`, but writes no second `ORDER_ALLOCATED` event — implementation/routes/plans.py:228-239

**Verified already-pinned (no change):** full RBAC matrix, envelope shapes (204 detach exception included), all 48 catalogue error ids/HTTP statuses match `errors.py` exactly, logical-clock semantics and monotone rule, restriction closed-window/overlap math, attach/detach/route guard ordering vs §2.8 ladder, fill seq/VWAP/overfill rules, split + fairness formulas (incl. 99999 cap, 200bp tolerance), supersedure cascade, budget half-open overlap/exact-equality exhaustion, correction sequencing and error-account tie-break, settlement lag/fail-monitor grace/escalation threshold, position accounting, and audit trail actor/"system" attribution.
