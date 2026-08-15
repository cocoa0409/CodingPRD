# Worklog — task_1444_ach_origination_nacha_return_handling

Scenario: ACH Origination & NACHA Return Handling (originating depository bank): originator underwriting & exposure limit, file intake, validation & warehousing until effective date, return/NOC processing & re-presentment rules, unauthorized return rate monitoring & threshold breach, same-day ACH window & cutoff pricing, reversal request eligibility & timing, ODFI risk monitoring & originator suspension, settlement & GL reconciliation

Difficulty directive from user: "Generate task hard than expert level!" — relayed to scaffold generator as: target the Expert band and push difficulty-mechanism density to the maximum the skill permits.

## Step 1: Create Task Directory — 2026-08-13T07:40:00.000Z

Task directory `tasks/task_1444_ach_origination_nacha_return_handling/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per command args; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T08:50:00.000Z

Scaffold generation complete. All three artifacts are written and verified.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1444_ach_origination_nacha_return_handling/SCAFFOLD.yaml` (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1444_ach_origination_nacha_return_handling/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1444_ach_origination_nacha_return_handling/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

## Counts (Expert band, at ceiling)
- **Entities: 11** — Originator, CutoffWindow, AchFile, AchEntry, ReturnCase, NocRecord, ReversalRequest, ReturnRateSnapshot, RiskCase, SettlementBatch, GlPosting
- **Endpoints: 32** (exactly at the Expert ceiling), incl. the test-driving `POST /ach/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default
- **Error codes: 30** (at ceiling), every one referenced by a validation/transition and asserted by at least one design instance
- **Calculations: 5** — `unauthorized_return_rate` (threshold, dual-variant trailing-60d vs month-to-date), `outstanding_exposure` (dual-variant gross vs debit-only), `file_fee` (dual-variant quoted vs assessed; modes a+b), `batch_settlement_net` (mode c, pinned evaluation order + dispatch-time sweep snapshot), `banking_day_add`
- **State machines: 8** — cyclic AchEntry (SETTLED→RETURNED→TRANSMITTED, cap 2), cyclic Originator (ACTIVE↔WATCH↔SUSPENDED), branching-divergent RiskCase, plus AchFile, ReturnCase, NocRecord (clock-swept), ReversalRequest, compound SettlementBatch

## Archetypes / layers
- Primary: **compliance_audit**; secondary: **ledger_reconciliation**
- Layers: cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency (2 OCC rules: Originator PATCH, AchFile entries-append)
- Role model: **segregation_of_duties** (5 roles; reconciler ≠ dispatcher by user id, `ERR_SOD_VIOLATION`)

## Difficulty mechanisms pushed to max density
Dual-interpretation calculations in 3 entity domains; a 3-deep cascade (risk resolve → originator → files → entries) and a 2-deep cascade (unauthorized return → rate recompute → auto RiskCase); priority-conflict pairs on disjoint category pairs (state-vs-fiscal, safety-vs-temporal); exact boundaries ($1,000,000.00 same-day cap `>`; exactly 50 bps no-breach via a 200-entry fixture; exposure equality admitted; NOC/reversal banking-day edges); sibling-state-dependent transitions (REINSTATE lands WATCH or ACTIVE depending on current state).

## Audits
- All nine §0.5 rules satisfied with differentiation clauses honored; 21 §1.8 instances (≥2 per rule) + 35 active / 9 stub §1.9 instances; names unique across both files; every `${var}` placeholder bound by an earlier `captures:`; every formula-derived assert pre-computed in code (fee 1322/471, rounding trap 193 vs 192, expected/posted 3999426, trial balance 4700260, variance −2000000, rates 50/98/100/250/10000 bps, dates 2026-08-05/10/11).
- `scaffold_lint.py` final verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (32 endpoints, 11 entities, 544 calls scanned, 0 violations.)

No sibling task directories were inspected; the design was generated purely from the scenario text plus the skill specification.

## Step 3: Copy Shared Files — 2026-08-13T08:51:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1444_ach_origination_nacha_return_handling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T09:10:00.000Z

PRD generation complete.

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1444_ach_origination_nacha_return_handling/workspace/PRD.md` — 286 lines.

**Section structure:**
- §1 Introduction (2 paragraphs — ODFI accountability angle, no template opener)
- §2 Global Specifications: 2.1 RBAC (five roles, identity semantics for entity-backed `OriginatorOps` vs four opaque bank roles), 2.2 API Response Structure (**byte-verified verbatim** against `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Logical Clock & Banking-Day Calendar, 2.5 Common Resource Properties (incl. `updated_at`/`version` absence for ReturnRateSnapshot and GlPosting), 2.6 Request Validation Pipeline (explicit 11-category ordering), 2.7 OCC, 2.8 Integer-Cents/Rounding Discipline, 2.9 State Cascades & Aggregate Consistency
- §3 Business Logic (8 subsections): originator onboarding/underwriting, cutoff windows & rate card, file intake/warehousing/entry assembly, release & window assignment, batch dispatch/settle/GL reconciliation, returns/re-presentment/NOCs, reversals, return-rate surveillance & risk enforcement
- §4 Endpoint table (32 rows, 4 columns, roles verified against scaffold), §5 Error catalogue (30 rows, 2 columns, HTTP statuses verified against scaffold)

**Coverage confirmation (all three hard contracts PASS):**
- Contract 1 (field names): 84 required identifiers (all entity fields, request-body keys, query params `originator_id`/`status`/`settlement_batch_id`/`limit`/`offset`, clock I/O `to_iso8601`/`current_utc`) — all present in backticks, 0 missing.
- Contract 2 (rules): validation priority pipeline rendered as an explicit ordered list; both OCC rules (originator PATCH + entries-append) with `expected_*_version` semantics and `ERR_STALE_VERSION`/412; all 8 state machines' transitions with preconditions→error IDs and side effects (incl. suspension cascade, dispatch/settle cascades, ReturnCase/NOC/reversal siblings at equal density); all 5 calculations in precise prose (half-open 60-day vs closed MTD windows, strict >50 bps breach, per-entry round-half-up discount with pinned rounding order, 4-step batch net with dispatch-snapshot drift rule, Mon–Fri banking-day add); every `applies_to` scope and endpoint side effect expressed; all 30 error IDs appear in §2/§3 prose; all defaults/null-until semantics stated.
- Contract 3 (§3 path purity): 408 backticked tokens scanned, 0 path/method violations; no pseudocode operators or fuzzy quantifiers anywhere.

The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T10:00:00.000Z

All checks pass. The task is complete.

## Summary

**Files written in `test_helpers/` (9):**
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 13 enums + 11 entity TypedDicts (ReturnRateSnapshot/GlPosting correctly omit `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with 32 methods, one per PRD §4 endpoint
- `api_errors.py` — 30 error ids + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — 11 entity assertions + `assert_gl_trial_balance`
- `factories.py` — payload factories incl. `make_entry_batch` for 40/62/200-entry files
- `constants.py` — PRD thresholds (50 bps breach, $100k surcharge tier, $1M same-day cap, 6/5/2 banking-day windows)
- `test_users.py` — TEST_USERS + `make_originator_headers` (entity-backed) + opaque role builders
- `fixtures.py` — composite setup helpers (clock, windows, approval, OCC-version-threaded appends, release/dispatch/settle/reconcile, returns, NOCs, reversals, risk cases)

**Files written in `test_suite/` (15):** `conftest.py` + `test_01`…`test_14` grouped by concern (onboarding/OCC, intake, windows, fees, exposure, release/batch, returns/re-presentment, NOC, reversals, rate surveillance, risk/suspension, settlement/GL, RBAC/SoD, priority/boundaries).

**Counts:** 75 tests total — 40 queue-A (20 difficulty instances × 2), 35 queue-B (35 non-stub corner instances × 1).

**Skipped instances (1):**
- `Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_reversal` — the instance asserts `ERR_INVALID_REVERSAL_REASON` for `WRONG_AMOUNT` on a CREDIT entry, premised on a direction-based NACHA rule ("only DUPLICATE_ENTRY may reverse a credit") that appears nowhere in the PRD; PRD §3.7 admits all three reasons for any SETTLED entry, so the asserted outcome is neither PRD-covered nor uniquely derivable (a PRD-faithful implementation would return `ERR_REVERSAL_WINDOW_EXPIRED` for that recipe).

The 9 corner `excluded_because:` stubs were not translated (per policy); all their `difficulty_instance` cross-references resolve to real queue-A names.

**Notable adjudication:** `Corner/validations/append_with_undefined_window_kind_returns_no_eligible_window` was translated at file intake (not entries-append), because PRD §3.3 ("A CutoffWindow row must exist for the requested kind; if none does, intake fails with `ERR_NO_ELIGIBLE_WINDOW`") makes the recipe's setup unreachable — the same error/rule is asserted where the PRD makes it observable. Two-reader relaxations: initial `version` asserted as `int >= 1` (PRD never pins the seed), pre-release fields asserted via `.get() is None` ("remain unset" permits absent or null).

**Verification:** every emitted test's docstring ends with exactly one `Design:` tag resolving to a real instance (script-verified); all ≥12-character quoted citation spans grep verbatim against PRD.md; all files compile; pytest collects 75/75.

## Step 6: Generate Implementation — 2026-08-13T10:00:00.000Z

Implementation complete. Summary:

## Files written (20 files)
All under `/home/ubuntu/github/CodingPRD/tasks/task_1444_ach_origination_nacha_return_handling/workspace/implementation/`:

- `start.sh` — foreground launcher with guarded dependency install (`python3 -c "import flask, waitress"` no-op guard), `exec python3 app.py`, PORT env (default 10000), binds 0.0.0.0
- `requirements.txt` — flask, waitress
- `app.py` — Flask entry, 9 blueprints, ApiError/404/405/500 handlers
- `db.py` — in-memory dict stores (empty at boot, no seeding) + logical clock pinned to `2026-08-01T00:00:00Z`
- `errors.py` — `ApiError` + full 30-entry error catalog with exact HTTP statuses
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data`; error body uses `error_id`/`message`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (5 roles), `ERR_UNAUTHENTICATED`/`ERR_FORBIDDEN_ROLE`
- `util.py` — pagination (limit 1..100 default 10, offset default 0), body validators, YYYY-MM-DD/HH:MM/ISO8601 parsing, `Decimal` round-half-up
- `routes/`: clock, originators, risk_cases, files, entries, nocs, reversals, batches, windows
- `services/domain.py` — all business logic

## Endpoint count: 32 (full §1.5 table)
Clock set; originator POST/GET/PATCH; return-rate-snapshots POST/GET; risk-cases POST/GET + resolve; ach-files POST/GET/GET{id} + entries POST/GET + release + cancel; ach-entries GET + returns + representments + nocs + noc-records + reversals + reversal-requests + return-cases + close; noc apply; reversal advance; batch advance + reconcile + GET + gl-postings; cutoff-windows POST.

## Entities: 11
Originator, CutoffWindow, AchFile, AchEntry, ReturnCase, NocRecord, ReversalRequest, ReturnRateSnapshot (id+created_at only), RiskCase, SettlementBatch, GlPosting (id+created_at only).

## State machines: 8
Originator (PENDING_UNDERWRITING→ACTIVE/TERMINATED; WATCH/SUSPENDED/TERMINATED via risk resolution with divergent cascades), AchFile (WAREHOUSED→RELEASED/CANCELLED/REJECTED→DISPATCHED→SETTLED), AchEntry (WAREHOUSED→TRANSMITTED→SETTLED⇄RETURNED cycle capped at 2 re-presentments, →CLOSED/CANCELLED), ReturnCase (OPEN→REPRESENTED/FINAL), NocRecord (RECEIVED→OVERDUE via clock sweep →APPLIED with late_applied), ReversalRequest (REQUESTED→TRANSMITTED/CANCELLED→SETTLED), RiskCase (OPEN→RESOLVED), SettlementBatch (OPEN→DISPATCHED→SETTLED→RECONCILED).

## Calculations: 5
`banking_day_add` (Mon–Fri only, backs effective-date window, NOC +6bd, reversal +5bd, NEXT_DAY settlement date); `outstanding_exposure` (gross + debit-only variants, strictly-greater admission check with equality admitting); `file_fee` (quoted vs assessed rate cards, per-entry round-half-up discount then sum, $100k surcharge strictly-greater, file fee never discounted); `unauthorized_return_rate` (trailing-60d half-open window excluding exactly-60-day-old items, MTD closed window, round-half-up integer bps, strict >50bps breach, conditional RATE_BREACH auto-open); `batch_settlement_net` (pinned principal→fee→reflow order, dispatch-time snapshot vs settle-time posting producing reconciliation drift).

## Boot confirmation
Smoke-tested `PORT=18171 bash start.sh` from a fresh process: healthy 200 responses within 3s; verified store starts empty (`total_count: 0`), clock defaults to `2026-08-01T00:00:00.000Z`, and three end-to-end smoke suites pass (auth/RBAC/ownership, OCC 412s, window overlap/adjacency, intake temporal window, exposure admission equality, same-day $1M cap, window fallback assignment, dispatch/settle/reconcile with exact cent-level expected/posted nets, R01 re-presentment cap and code prohibition, NOC overdue sweep + late apply, reversal window expiry/duplicate/role gating, SoD violation, reconciliation-mismatch drift, suspend/terminate cascades with version bumps, rate-window boundary exclusion at exactly 60 days, debit-only rate scoping, envelope shapes).

## Step 7: Test-Fix Iteration Loop — 2026-08-13T10:15:00.000Z

Iteration 1 sweep (8 parallel rounds): 70/75 in every round; union = 5 stable failures (no flakiness).

Failures and fixes (all test-artifact bugs; implementation untouched):
1. `test_12_settlement_gl_reconciliation.py` (4 tests: `test_settle_posts_matching_net_and_reconciles`, `test_ledger_pairs_balance_across_swept_items`, `test_swept_representment_settles_and_nets_match`, `test_late_return_blocks_reconciliation`) — `NameError: settle_batch_ok is not defined`: the file used the helper at 4 call sites but omitted it from the `from test_helpers import (...)` list. Fix: added `settle_batch_ok` to the import list.
2. `test_13_rbac_sod.py::test_originator_cannot_cancel_another_originators_file` — setup failed with `ERR_NO_ELIGIBLE_WINDOW` (PRD 3.3: "A CutoffWindow row must exist for the requested kind; if none does, intake fails with ERR_NO_ELIGIBLE_WINDOW"). The test built its own two-originator setup instead of `setup_standard_environment` and forgot to define the NEXT_DAY CutoffWindow before file intake — a fixture-precondition violation, not an implementation bug. Fix: added `define_next_day_window()` to the test's imports and called it before `create_warehoused_file`.

Iteration 2 sweep (8 parallel rounds): 75/75 in all 8 rounds. No tests deleted; no assertions weakened; no implementation changes.

Verbatim subagent summary:

The sweep is clean — all 8 rounds pass 75/75 with zero failures. Exiting with the summary.

---

## Summary

**Iterations run:** 2 (iteration 1: 70/75 in all 8 rounds, union of 5 stable failures, no flakiness; iteration 2: 75/75 in all 8 rounds, zero failures).

**Tests deleted:** None.

**Fixes applied to `test_suite/` (2):**
1. `/home/ubuntu/github/CodingPRD/tasks/task_1444_ach_origination_nacha_return_handling/test_suite/test_12_settlement_gl_reconciliation.py` — added missing `settle_batch_ok` to the `from test_helpers import (...)` list. The file called the helper at 4 sites but never imported it, producing `NameError` in 4 tests (`test_settle_posts_matching_net_and_reconciles`, `test_ledger_pairs_balance_across_swept_items`, `test_swept_representment_settles_and_nets_match`, `test_late_return_blocks_reconciliation`). Pure mechanical test bug.
2. `/home/ubuntu/github/CodingPRD/tasks/task_1444_ach_origination_nacha_return_handling/test_suite/test_13_rbac_sod.py` (`test_originator_cannot_cancel_another_originators_file`) — added `define_next_day_window()` call (plus import) before `create_warehoused_file`. The test built a custom two-originator setup instead of `setup_standard_environment` and omitted the CutoffWindow precondition, so intake was correctly rejected per PRD §3.3 ("A CutoffWindow row must exist for the requested kind; if none does, intake fails with `ERR_NO_ELIGIBLE_WINDOW`"). STEP 2 fixture-precondition violation — fixed the test, not the implementation check.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful; both failure classes were test-artifact bugs.

## Step 8: Finalize PRD — 2026-08-13T10:30:00.000Z

## Step 8 Complete — PRD_FINALIZED.md produced (byte-identical copy; zero edits required)

**Both step_7_diff items are pure test-artifact bugs.** Neither reveals PRD silence nor PRD/implementation mismatch, so no PRD edits are warranted. `PRD_FINALIZED.md` at `/home/ubuntu/github/CodingPRD/tasks/task_1444_ach_origination_nacha_return_handling/workspace/PRD_FINALIZED.md` is a verified byte-identical copy of `PRD.md`.

### Line counts and delta
- `PRD.md`: 286 lines / 45,159 bytes
- `PRD_FINALIZED.md`: 286 lines / 45,159 bytes
- Delta: 0 lines, 0.0% — confirmed byte-identical via `cmp`

### Per-item analysis

**Item 1 — `test_suite/test_12_settlement_gl_reconciliation.py` missing `settle_batch_ok` import.**
- (a) Subject: test-file import list (Python `NameError` at 4 call sites).
- (b) Paths enumerated: `test_helpers/fixtures.py:183` (helper definition — exists and works), `test_suite/test_12_*.py:23` (import now present), call sites at lines 85, 128, 157, 251. No `implementation/` path is involved; the helper only wraps the standard settle endpoint whose behavior was already exercised by passing tests elsewhere.
- (c) Wording adjustment: none — this is a mechanical Python bug in test code with zero behavioral content. No PRD section touches test-file imports.

**Item 2 — `test_suite/test_13_rbac_sod.py` missing `define_next_day_window()` fixture precondition.**
- (a) Subject: file-intake precondition — a CutoffWindow row must exist for the requested kind, else `ERR_NO_ELIGIBLE_WINDOW`.
- (b) Paths enumerated and verified consistent with existing PRD text:
  - `implementation/routes/files.py:106-107` — intake raises `ERR_NO_ELIGIBLE_WINDOW` when `window_by_kind(requested_kind)` is `None` — exactly matches PRD §3.3 (line 154): *"A CutoffWindow row must exist for the requested kind; if none does, intake fails with `ERR_NO_ELIGIBLE_WINDOW`."*
  - `implementation/routes/files.py:204` — entry-append fee recomputation fails with `ERR_NO_ELIGIBLE_WINDOW` if the window row is missing — matches PRD §3.4 (line 162).
  - `implementation/routes/files.py:285` and `services/domain.py:595` — release-time window assignment rule fails with `ERR_NO_ELIGIBLE_WINDOW` — matches PRD §3.6 (line 170).
  - `implementation/errors.py:26,59` — error code maps to HTTP 422 — matches PRD error catalog (line 268).
  - Fixed test: `test_suite/test_13_rbac_sod.py:105-106` now calls `define_next_day_window()` before `create_warehoused_file(...)`, satisfying the precondition the PRD already pins.
- (c) Wording adjustment: none — the PRD already uniquely determines this behavior at every enumerated path; the step_7_diff itself classifies this as a "STEP 2 fixture-precondition violation — fixed the test, not the implementation check."

### Conclusion
Step 7 applied zero `implementation/` fixes, zero `test_helpers/` fixes, and deleted zero tests; the two `test_suite/` fixes were an import correction and a fixture-precondition correction. Since the implementation was already PRD-faithful and the PRD already pins the one behaviorally relevant site (§3.3), the correct finalized artifact is the unchanged copy. Step 9 may proceed against `PRD_FINALIZED.md` as-is.

## Step 9: Complete PRD — 2026-08-13T10:50:00.000Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1444_ach_origination_nacha_return_handling/workspace/PRD_COMPLETED.md` produced.

## Summary

**Source:** `PRD_FINALIZED.md` (existed; copied to `PRD_COMPLETED.md`, only the copy edited).
**Size:** 286 → 287 lines; 45,159 → 47,801 chars (+2,642 chars).
**Counts:** 19 ambiguity-pins, 1 mismatch-revision (20 total changes).

### Changes

- §2.2 (success envelope) — revise — ambiguity — pinned `api_request_timestamp` as wall-clock at response time, not the §2.4 logical clock — `implementation/response.py:17-19`.
- §2.2 (error envelope) — insert — ambiguity — pinned pre-handler failures: unmatched route → `ERR_NOT_FOUND` (404), unsupported method → `ERR_INVALID_REQUEST` (405), unexpected failure → `ERR_INTERNAL` (500) — `implementation/app.py:41-51`.
- §2.3 — insert — ambiguity — non-integer/out-of-band `limit` (1–100) or negative `offset` → `ERR_INVALID_REQUEST` — `implementation/util.py:24-51`.
- §2.3 — insert — ambiguity — pinned `has_more` formula: true iff `offset` + items-in-page < `total_count` — `implementation/response.py:35`.
- §2.4 (clock endpoint) — insert — ambiguity — missing/unparsable `to_iso8601` → `ERR_INVALID_REQUEST` — `implementation/routes/clock.py:20-21`, `implementation/util.py:159-172`.
- §2.4 (calendar) — insert — ambiguity — "today"/"current day" under the logical clock means the calendar date of the clock instant, banking day or not (governs effective-date window, release-date equality, reversal window, NOC sweep) — `implementation/db.py` clock + `domain.py:60-61,275`.
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — `implementation/db.py:95`.
- §2.5 — insert — ambiguity — a recomputation leaving a derived field unchanged is not a mutation (no `updated_at`/`version` bump) — `implementation/services/domain.py:113-126,229-243`, `implementation/routes/originators.py:155-161`.
- §2.6 step 5 — insert — ambiguity — body must be a JSON object, else `ERR_INVALID_REQUEST` — `implementation/util.py:64-70`.
- §3.1 — revise — ambiguity — APPROVE persists `fee_discount_bps` only when supplied (omitted discount keeps prior value); `exposure_limit_cents`/`fee_discount_bps` on a DECLINE are ignored — `implementation/routes/originators.py:117-123`.
- §3.1 — revise — mismatch — maintenance updates (no `decision`) are accepted from any non-TERMINATED status (incl. `PENDING_UNDERWRITING`, `SUSPENDED`, not just `ACTIVE`/`WATCH`); maintenance may set `exposure_limit_cents` to 0 (the >0 rule binds only APPROVE) — `implementation/routes/originators.py:104-129`.
- §3.3 — revise — ambiguity — `ERR_ORIGINATOR_NOT_ACTIVE` also covers an `X-User-ID` matching no originator record — `implementation/routes/files.py:83-89`.
- §3.3 — insert — ambiguity — `quoted_fee_cents` initialized at intake to the requested window's `file_fee_cents` (fee over the empty file) — `implementation/routes/files.py:119`.
- §3.3 — revise — ambiguity — `receiver_account` accepted as any non-empty string (no numeric-format check) — `implementation/routes/files.py:165`, `implementation/util.py:79-83`.
- §3.3 — insert — ambiguity — an empty `entries` list is valid: nothing persisted, but totals/quoted fee recomputed and file `version` still increments — `implementation/routes/files.py:158-237`.
- §3.5 — insert — ambiguity — a file with zero `assessed_fee_cents` posts no fee pair (every GL row must carry one nonzero leg) — `implementation/services/domain.py:499-502`.
- §3.5 — revise — ambiguity — `recon_variance_cents` is persisted on every reconcile attempt; a failed reconcile still refreshes `updated_at` and increments the batch `version` — `implementation/routes/batches.py:61-74`.
- §3.6 — insert — ambiguity — ReturnCase persists the supplied `return_code` — `implementation/routes/entries.py:82`.
- §3.6 — insert — ambiguity — NOC registration from an entry status other than SETTLED/RETURNED → `ERR_ENTRY_NOT_SETTLED` — `implementation/routes/entries.py:144-146`.
- §3.7 — insert — ambiguity — wrong-side reversal action (OriginatorOps `TRANSMIT` / OdfiOperations `CANCEL`) → `ERR_FORBIDDEN_ROLE` — `implementation/routes/reversals.py:38-41`.
- §3.8 — insert — ambiguity — resolved RiskCase's terminal status is named `RESOLVED` — `implementation/routes/risk_cases.py:70`.

All other implementation behaviors (endpoints, roles per endpoint, state machines, fee/exposure/rate formulas, sweep semantics, validation-pipeline ordering, error codes and HTTP statuses) were already uniquely pinned by the PRD and required no change.

## Pipeline Complete — 2026-08-13T10:50:00.000Z

All 9 steps done. Final 8-round parallel sweep: 75/75 passing in every round. Step 8: PRD_FINALIZED.md byte-identical (0 edits). Step 9: PRD_COMPLETED.md with 20 minimal pins (+2,642 chars over 286-line source).
