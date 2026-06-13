# Worklog — task_0325_house_painting_contractor

## Step 1: Create task directory — 2026-06-13T05:35:35.000Z

Created pre-allocated directory `tasks/task_0325_house_painting_contractor/` and `workspace/` subdir. Index 0325 was pre-assigned by the user (no auto-increment scan performed, per instruction).

## Step 2: Generate scaffold (Expert) — 2026-06-13T06:05:22.000Z

All three files are in place with correct top-level key separation, and the lint verdict is clean. The scaffold is complete.

## Summary

Generated all three scaffold artifacts for **task_0325 House Painting Contractor** at **Expert** difficulty, into `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0325_house_painting_contractor/`. `scaffold_lint.py` returns **`VERDICT: clean lint`** (all 363 §1.8/§1.9 calls conform to §1.5; all 16 FKs reverse-reachable).

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Profile:** primary archetype *pricing_engine* + secondary *temporal_windowing*; layers dual-variant-calculation, cascading-side-effects, optimistic-concurrency, rate/threshold-triggers, derived-field-reconciliation. **Flat topology** (`api_prefix: /painting`, all entities flat collections with FK fields in bodies + filtered-list GETs) — the diversity-prioritized shape the lint's check (f) requires.
- **13 entities:** PaintProduct, CrewMember, Equipment, WeatherWindow, Project, Surface, ColorSelection, LineItem, ChangeOrder, CrewAssignment, Payment, Walkthrough, WarrantyClaim.
- **6 state machines:** Project carries **parallel axes** (`workflow_status` × `payment_status`); ChangeOrder is **cyclic** (REJECTED→DRAFT revise loop); Walkthrough is **branching-with-revert** (FAILED→PENDING); plus CrewAssignment, ColorSelection, WarrantyClaim. 1 concurrency rule (OCC `expected_project_version` on change-order create, CREATE-with-supersede).
- **7 calculations:** material_estimate (ceil gallons), labor_estimate (tiered prep multiplier, fractional cents via SQFT_PER_HOUR=160 / rate=6550), project_totals (frozen-estimate vs live-final dual variant + pinned round-per-line-then-sum), deposit_due, change_order_delta, weather_suitability (temp ≥50 / precip ≤30), warranty_payout (provisional vs final dual variant).
- **14 validations** (priority-ordered, 8 categories), **58 endpoints** (incl. `/_clock/set_current_utc` test-driving), **55 errors**, **4 roles** (Estimator, ProjectManager, Customer, CrewMember — all `opaque`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rules × 2 = **18 instances**, every formula-derived assert pre-computed to a literal (e.g. estimate 21101 vs final 8913; labor rounding 13101 vs 13100; gallons 2 vs 3 at exact coverage; warranty inclusive at exact expiry). Dual-variant and cascade rules span different entity domains (Project vs WarrantyClaim; ChangeOrder cascade vs Walkthrough cascade); overlap rules use distinct interval semantics (crew buffer-gap vs equipment aggregate-capacity); conserved quantities differ (money vs scheduled-day count).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** breadth walk of the claim-extraction taxonomy across all 9 sections — **34 active corner instances + 4 `excluded_because` stubs** (each citing a real §1.8 instance) covering creation/not-found/listing/required-fields/system-fields/immutability, invalid-transition/precondition/terminal-lockdown/cascade, calc constants/precision, cross-entity & conditional validations, FK reverse-reachability, error triggers, RBAC denials, OCC (stale + happy-path) and derived-field reconciliation, and the immediate consistency model.

All grounds references resolve, no forbidden concurrency vocabulary, no design keys leaked into SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-06-13T06:05:48.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0325_house_painting_contractor/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T06:11:30.000Z

Generated `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0325_house_painting_contractor/workspace/PRD.md` — a prose PRD for the House Painting Contractor API (349 lines).

**Document metrics**
- 5 top-level sections (Introduction; Global Specifications; Business Logic & Workflows; Endpoint Definitions; Error Code Catalogue)
- §2 has 9 domain-derived subsections (RBAC, response structure, pagination, common properties, derived/hierarchical consistency, nested-id resolution, OCC, monetary precision, resource-utilization accounting)
- §3 has 12 lifecycle/process subsections (catalog setup → project founding → estimate freeze → color → scheduling → work/walkthrough → completion → money axis → change orders → cancellation → warranty → validation ordering)
- §4 table: 58 endpoints (4 columns), matching the scaffold's 58 exactly; §5 table: 55 error codes (2 columns)

**Hard contract results (all PASS)**
- Contract 1 — Field-Name Coverage: 77/77 required identifiers present verbatim in backticks (all entity fields, request-body keys incl. `expected_project_version` and `to_iso8601`, query params `limit`/`offset` and all filters), 0 missing.
- Contract 2 — Rule Coverage: OCC rule (framed in stale-version terms, no race wording); priority-1-through-6 ordering plus crew-assignment sub-order (skill→double-booking→equipment→weather); all 6 calculations with constants in prose (PREP_FACTOR 1.0/1.25/1.6/2.0, 160 sqft/hr, 6550 cents/hr, 0.20 touch-up fraction, weather 50°F/30% boundaries with inclusivity); dual-variant pricing (frozen estimate vs live revised vs final EXECUTED total; provisional vs final warranty payout); per-line-item-then-sum round-half-up; depth-3 change-order cascade; cancel/complete compensating releases; cancel refund cascade; walkthrough→completion cascade requiring PAID_IN_FULL; warranty ordered checks; Payment's missing `version`/`updated_at`.
- Contract 3 — §3 Path Purity: 424 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP-method tokens, 0 method+path combos.

Every scaffold entity, state machine, calculation, validation, endpoint, error code, and role is covered in prose. The withheld design YAMLs were not opened.

## Step 5: Generate unit tests — 2026-06-13T06:25:28.000Z

Generated complete test infrastructure for **task_0325 (House Painting Contractor)** under `test_helpers/` and `test_suite/`.

**Test files: 8** (1 conftest + 7 test modules)
- `test_01_crud_and_validation.py` — CRUD, 404s, pagination, system fields, payment immutability, FK existence
- `test_02_estimate_and_calculations.py` — material/labor calcs, rounding order, gallon & weather boundaries
- `test_03_state_machine_transitions.py` — project/walkthrough/color preconditions, cancel cascade, parallel axes
- `test_04_change_orders.py` — cyclic revise, depth-3 cascade, reject invariant, changeable guard, OCC
- `test_05_scheduling_constraints.py` — crew double-book, equipment capacity, skill/weather, day-count conservation
- `test_06_payments_and_warranty.py` — dual-variant totals/payouts, completion cascade, warranty boundary, fiscal/state priority
- `test_07_rbac.py` — role denials and invalid user context

**Test functions emitted: 71**

**Queue A (Difficulty): 18/18 instances translated** (0 skipped), every instance covered by ≥2 tests (`gallons_ceil_at_exact_coverage_boundary` got 3 via X-1/X/X+1 boundary precision). All 9 rules × 2 instances passed the PRD-first two-condition filter.

**Queue B (Corner): 34/34 non-stub instances translated** (0 skipped), each covered by ≥1 test. The **4 `excluded_because:` stubs were NOT translated** (their assertions are owned by the cited difficulty instances).

**No skips/xfail.** All `Design:` tags resolve to real instances (no dangling/dual tags). All quoted PRD citations verified verbatim against PRD.md.

**test_helpers modules created (9):** `types.py` (Payment correctly omits `version`/`updated_at`), `api_client.py` (one method per endpoint incl. `/_clock/set_current_utc`), `api_errors.py` (57 error IDs + HTTP map), `assertions.py`, `factories.py`, `constants.py` (canonical numeric fixtures 8913/21101/6330/47300/983/19650), `test_users.py` (4 opaque-role shared constants), `fixtures.py` (tiered composite setups with clock pinning), and `__init__.py` barrel export. All 17 files pass `ast.parse`.

## Step 6: Generate implementation — 2026-06-13T06:25:28.000Z

Generated a complete Python + Flask implementation at `workspace/implementation/`.

### Files (line counts)
- `app.py` (1391) — entry point, all 58 route handlers, error handlers, state machines, cascades
- `services.py` (356) — entity factories, common-field/version management, existence resolvers, line-item & total recompute, utilization accounting, month arithmetic, serialization
- `errors.py` (85) — `ApiError` + full error_id→HTTP-status catalog (PRD §5)
- `calc.py` (78) — Decimal round-half-up calcs: material/labor estimate, deposit, weather, warranty payouts, skill ranks
- `db.py` (60) — in-memory `Store` singleton + pinnable `Clock`
- `response.py` (60) — success/array/error envelope helpers
- `pagination.py` (39) — limit/offset parsing & clamping
- `middleware.py` (29) — auth header extraction + role checks
- `requirements.txt` (1) — `flask==3.0.3`; `start.sh` (10) — launcher

### Endpoints: 58 spec endpoints (57 under `/painting/*` + `/_clock/set_current_utc`), exactly matching PRD §4. One extra `GET /` health route for boot verification only.

### In-memory store & OCC
- **Store**: module-level `Store()` singleton in `db.py`, one Python dict per collection keyed by UUID id; monotonic `_seq` for stable list ordering. Created empty at import; **never seeded**.
- **OCC**: only OCC write is `POST /painting/change-orders` carrying non-optional `expected_project_version`; server compares vs `Project.version`, returns `ERR_STALE_PROJECT_VERSION` (412) on mismatch. Every entity except `Payment` carries `version` (starts 1, +1 per mutation via `touch()`); `Payment` is append-only ledger (only `id`/`created_at`). Approving a change order applies surface mutation, recomputes live `revised_total_cents`/`balance_due_cents` (frozen estimate untouched), records `applied_project_version`, bumps `Project.version`.

### start.sh contract — confirmed: reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`, guards `pip install` on `import flask`, no data seeded at boot (fresh boot returns empty collections).

### Self-verification (agent, not the harness): 36/36 happy-path + numeric-fixture checks and 16/16 edge cases passed against a locally booted server.

## Step 7: Test & iterate to green — 2026-06-13T06:30:26.000Z

All 8 parallel rounds pass cleanly: 71/71 in every round. The loop is complete.

## Summary

**Iterations run:** 2 (initial sweep + one fix + confirming sweep).

**Diagnosis:** The initial 8-round sweep was consistently 70/71, with exactly one test failing in all 8 rounds: `test_balance_due_reconciles_after_approved_change_order` (test_04_change_orders.py). The failure was a setup-phase HTTP 412 `ERR_STALE_PROJECT_VERSION` raised at the `create_submitted_change_order` step.

Root cause traced through the protocol:
- STEP 1a/1b: The asserted rule (balance = revised_total − amount_paid; deposit frozen) is verbatim-covered by PRD §3.8 and §3.9, and the expected values (revised_total 56213, balance 53539, deposit 2674) are uniquely derivable. Test stays.
- STEP 2: TEST BUG. The test captured `project["version"]` right after `setup_estimated_project()`, then called `pay_deposit(...)`, then authored the change order with that captured version. But paying a deposit mutates the project (`amount_paid_cents`, `balance_due_cents`, `payment_status`), and per PRD §2.5 every mutation increments the project's `version`. The implementation correctly bumps the version (`svc.touch(project)` in the payment handler, app.py:1134) and the OCC check (§2.7) correctly rejected the stale version. The fixture was issuing a request inconsistent with PRD — a test bug, not an implementation bug. (This is why the sibling tests that author a change order without an intervening `pay_deposit` all passed.)

**Fixes applied to `test_suite/`:** `test_04_change_orders.py`, `test_balance_due_reconciles_after_approved_change_order` — inserted a `api.get_project(...)` re-fetch after `pay_deposit` and used the fresh `version` when authoring the change order, so the OCC precondition reflects the post-deposit project version per §2.5/§2.7. The fix makes the test more faithful to PRD, not less.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful.

**Tests deleted:** None — the single failing test had full PRD coverage and unique derivability; the defect was a stale-version precondition in the test setup.

Final state: all 8 parallel rounds pass 71/71 with no flakiness.

## Step 8: Finalize PRD — 2026-06-13T06:32:22.000Z

**Verdict: zero edits.** The single Step 7 diff item revealed no PRD silence and no PRD/impl mismatch — it was a pure test-fixture bug (stale `version` captured before a deposit-payment mutation), already fixed in `test_suite/`. `PRD_FINALIZED.md` is a verbatim copy of `PRD.md` (349 lines, 0% delta; `diff` confirms identical).

**Pre-edit search log (run on the diff item's subject to justify the no-edit verdict):**
(a) Subject: project `version` bump on the deposit-payment mutation, and the OCC stale-version check on change-order creation (`ERR_STALE_PROJECT_VERSION`, 412).
(b) Impl paths enumerated: `services.py:45-49` (`touch()` bumps `version` + `updated_at` on every mutation, PRD §2.4/§2.5); `app.py:1134` (`create_payment` calls `svc.touch(project)` after DEPOSIT & FINAL payments, PRD §2.5); `app.py:1128-1129` (deposit recomputes `amount_paid_cents`/`balance_due_cents`, PRD §3.8); `app.py:637,657-658` (`create_change_order` reads non-optional `expected_project_version`, rejects with `ERR_STALE_PROJECT_VERSION` on mismatch — grep confirms sole OCC-gated write, PRD §2.7/§3.9); `app.py:802,805` (approval sets `applied_project_version` then bumps `version`, PRD §3.9).
(c) Wording adjustment: none (no edit committed). All enumerated paths already verbatim-covered by PRD as written.

## Step 9: Complete PRD — eliminate residual ambiguity & mismatch — 2026-06-13T06:35:59.000Z

Full PRD-vs-implementation scan starting from `PRD_FINALIZED.md`. Produced `PRD_COMPLETED.md`.

**File sizes:** source `PRD_FINALIZED.md` 349 lines / 50,876 chars → `PRD_COMPLETED.md` 349 lines / 51,893 chars (**+1,017 chars**; all edits in-paragraph, no line-count change).

**Change counts:** 5 total — 4 ambiguity-pins, 1 mismatch-revision.

**Per-change log:**
- §2.3 Pagination — insert — ambiguity — Pinned that out-of-range/malformed pagination params are silently normalized (limit clamped 1..100, negative offset → 0, non-integer → default) rather than rejected — `implementation/pagination.py:24-33`
- §3.2 Founding a Project — insert — mismatch — PRD said "every computed monetary total at 0"; pinned that `final_total_cents` and `warranty_expires_at` are instead initialized to `null` until completion — `implementation/app.py:280,285`
- §3.2 Labor estimate — insert — ambiguity — Pinned the `labor_hours` JSON shape: serialized as integer when whole, otherwise float — `implementation/calc.py:58-62`
- §3.7 Walkthrough Outcome — insert — ambiguity — Pinned that on a pass the walkthrough's `status` always moves to literal `PASSED` — `implementation/app.py:1213,1138`
- §3.11 Touch-Up Warranty — insert — ambiguity — Pinned that `logged_touchup_hours` may be integer or fractional (boolean rejected), recorded verbatim, and `final_payout_cents`/`logged_touchup_hours` are `null` until resolution — `implementation/app.py:1355-1358`, `implementation/calc.py:77-78`

**Left unchanged (PRD already pins or impl matches):** error catalogue/HTTP codes, validation priority ordering, RBAC role tables, all monetary formulas, state-machine transitions and guard errors, conserved utilization counters, crew double-booking buffer-day rule, equipment peak-overlap rule, weather boundaries, OCC stale-version check, payment-axis transitions, cancellation/completion cascades. `warranty_months`/`forecast_temp_f` have no range validation in impl (consistent with §3.12).

---

## Pipeline complete — 2026-06-13T06:35:59.000Z

All 9 steps finished. Final test state: **71/71 passing across all 8 parallel stability-sweep rounds** under `prd-bench-local-run --isolation per-test-server`. Deliverables: SCAFFOLD trio, PRD.md → PRD_FINALIZED.md (verbatim) → PRD_COMPLETED.md (5 pins), 71-test suite (8 files) + test_helpers (9 modules), Flask implementation (10 files, 58 endpoints, in-memory store).
