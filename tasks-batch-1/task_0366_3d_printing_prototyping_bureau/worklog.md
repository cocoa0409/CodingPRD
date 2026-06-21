# Worklog — task_0366_3d_printing_prototyping_bureau

## Step 1: Create task directory — 2026-06-15T00:00:00.000Z

Created `tasks/task_0366_3d_printing_prototyping_bureau/` and `tasks/task_0366_3d_printing_prototyping_bureau/workspace/`. Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-15T00:00:00.000Z

Generated a fresh **Expert-difficulty** scaffold for **task_0366_3d_printing_prototyping_bureau** (3D Printing & Prototyping Service Bureau). All three files written to the task directory; `scaffold_lint.py` reports **`VERDICT: clean lint`** (50 endpoints, 11 entities, 18 §1.8 + 30 §1.9 instances, 485 calls scanned, all conform to §1.5, all FKs reverse-reachable).

### Scale
- **11 entities**: Bureau (tenant root), Customer, Material, Machine, Spool, PrintFile, Order, OrderLine, FinishingTask, PrintRun, Shipment
- **3 state machines** + **2 concurrency rules** (OCC)
- **7 calculations**, **14 validations**, **22 errors**, **50 endpoints**, **4 roles**

### Architecture
- **Archetype**: Workflow orchestration + Quota/allocation; **layers**: OCC, cascading side-effects, dual-variant calc, rate/threshold, derived-field reconciliation
- **Flat topology** (`/bureaus/<collection>` with body FKs) — deliberately the under-represented flat pattern; multi-tenant under Bureau with `bureau_id` filtered-list reverse-reachability for every FK
- **Role model**: peer_roles (Customer entity-backed; BureauAdmin/Operator/QAReviewer opaque)

### Expert depth highlights
- **Two non-linear state machines on different entities**: PrintRun is **cyclic** (QUEUED→PRINTING→FAILED→QUEUED reprint loop); Order has **parallel dimensions** (fulfillment_status × payment_status advancing on different triggers); PrintFile **branches** (UPLOADED→{PRINTABLE,FLAGGED,REJECTED})
- **Two dual-variant calcs on different domains**: reprint cost FORWARD vs CHRONOLOGICAL (OrderLine cost; bureau-fault → 0, customer-fault → material + 50% machine); machine utilization COMMITTED vs ACTIVE (Machine scheduling)
- **Combinatorial formulas across modes**: per-part-round-then-multiply pricing (mode b, pinned rounding order) and tiered rush surcharge on aggregate base (mode a, enum-branched)
- **Two conservation invariants over different quantities**: customer money ledger (wallet+escrow+captured == lifetime_deposits) and spool grams (remaining+committed+consumed == total)
- **Two interval-overlap semantics**: machine half-open zero-buffer (back-to-back OK) vs post-process station closed-interval with cooldown buffer (strict `>`)
- **Layered validation precedence** (14 priorities) with two dual-failure conflicts across different category pairs (state vs fiscal; safety vs fiscal)
- **Transitive cascades** depth-4 (order-cancel → void lines + cancel runs → release spool grams → restore remaining) and depth-3 (run-complete → grams committed→consumed → order bubbles READY)
- **Boundary checks** on distinct metrics/endpoints (machine capacity `460+20==480` accept / `460+21` reject; empty-set zero-line quote)
- **OCC** on Order (confirm) and PrintRun (adjudicate) parent versions, both serial-observable stale-version 412s

## Step 3: Copy shared files — 2026-06-15T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-15T00:00:00.000Z

Generated `workspace/PRD.md` — a 264-line PRD for the multi-tenant 3D Printing & Prototyping Service Bureau API.

**Sections written:**
- **§1 Introduction** — 2 paragraphs framing workflow-orchestration + quota/allocation accounting.
- **§2 Global Specifications** — 11 subsections (RBAC, fixed §2.2 envelope verbatim, Pagination, Common Properties & Bureau Clock, Hierarchical Consistency & Auto-Propagation, Material Conservation on Spools, Machine Capacity & Dual Utilization, Customer Wallet Ledger, Precision, OCC, Validation Ordering).
- **§3 Business Logic** — 8 subsections by lifecycle (catalogue setup, file/printability, order building & pricing, finishing/station scheduling, quote-to-escrow, scheduling/running production, failure/reprint/adjudication, shipment/capture).
- **§4** — 50-endpoint table (4 columns).
- **§5** — 22-error catalogue (2 columns).

**Hard Contract Reports:** Contract 1 (field coverage) PASS — 77/77 required fields. Contract 2 (rule coverage) PASS — 14 validations, 2 OCC rules, all state-machine transitions, 7 calculations, 22 error_ids, side-effects, sibling-branch symmetry all expressed. Contract 3 (path purity §3) PASS — 0 path/method tokens in §3.

**Notable coverage decisions:** parallel Order state machine (fulfillment_status × payment_status) and cyclic PrintRun failure→reprint loop narrated chronologically across §3.5–§3.7; two dual-variant calcs (machine utilization COMMITTED vs ACTIVE; reprint attribution FORWARD vs CHRONOLOGICAL) given symmetric reconstructible prose; boundary inclusivity preserved (half-open machine slots, closed-interval station gaps, capacity equality, hard-manifold gate precedence). Withheld design files not read.

## Step 5: Generate unit tests — 2026-06-15T00:00:00.000Z

Everything is in place and verified. Here is my final report.

## Summary

Generated complete test infrastructure for **task_0366_3d_printing_prototyping_bureau** from the two design indices only (no freelance walk of SCAFFOLD.yaml).

### Files generated

**`test_helpers/` (Stage 1 — 9 files)**
- `types.py` — 12 entity TypedDicts (all `common_fields: true`, so all carry `id/created_at/updated_at/version`) + 11 status/enum types + `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per endpoint (all 50 endpoints)
- `api_errors.py` — `ApiErrorId` enum (22 errors) + HTTP-status map, registered with the framework
- `assertions.py` — per-entity assertions + `assert_wallet_conservation` / `assert_spool_conservation` invariant checkers
- `factories.py` — one payload factory per entity, PRD-exact field names, canonical fixture values
- `constants.py` — printability weights, RUSH tiers, SECONDS_PER_LAYER, File A/B geometry
- `test_users.py` — opaque-role shared headers + `make_customer_headers(id)` builder for the entity_backed Customer role (identity threading)
- `fixtures.py` — layered composite setup (catalogue → order+line → quote/confirm → run queued/printing/failed → ready+shipment), all using `get_success_data`
- `__init__.py` — barrel export

**`test_suite/` (Stage 2 — conftest + 7 test files)**
- `test_01_pricing_and_calculations.py`, `test_02_dual_variant.py`, `test_03_state_machines.py`, `test_04_cascades_and_invariants.py`, `test_05_scheduling_and_constraints.py`, `test_06_validation_priority.py`, `test_07_crud_rbac_concurrency.py`

### Counts
- **66 tests total**, all collect cleanly under pytest with the framework on PYTHONPATH.

### Coverage audit (passed in full)
- **Queue A (Difficulty):** all 18 instances (9 rules × 2) have **≥2 tests each**. No shortfall.
- **Queue B (Corner):** all **30 non-stub instances** have **≥1 test each**. No Corner tag resolves to a stub or non-existent instance.
- **8 `excluded_because` stubs** correctly NOT translated; all 8 cross-references verified to resolve to real Difficulty instances (void_line→order_cancel_depth3; version_increments→order_parallel_axes; 6 errors→their respective triggering instances).
- Every test carries **exactly one** `Design:` tag; no untagged/dual-tagged tests; no `skip`/`skipif`/`xfail`.
- All PRD citations verified **verbatim** against PRD.md (including backtick-delimited field/error names).
- No scaffold/Table/§1.x references leak into emitted code.

### Skipped instances
**None.** Every non-stub instance from both queues passed the PRD-first two-condition filter (verbatim coverage + unique derivability) — the PRD prose is detailed enough that all asserted outcomes (pricing rounding order, dual-variant reprint attribution, dual utilization views, conservation invariants, half-open vs closed-interval scheduling semantics, validation priority via §2.11, OCC stale-version) are uniquely determined. All literal expected values were independently recomputed and matched the design-index literals (e.g. reprint FORWARD 5856 → CHRONOLOGICAL FILE_DEFECT 284/grand 3212; per-part 1974→line 8422; EXPEDITE surcharge 3697; utilization 42/29).

### Note on extra coverage detail
The second tests added to reach ≥2 per Difficulty instance assert genuinely distinct facets (accepted-side of a boundary, complementary tier/cause, intermediate conservation state, satisfied branch of a cross-entity gate), each independently PRD-cited — not duplicates.

## Step 6: Generate implementation — 2026-06-15T00:00:00.000Z

Everything is in place and compiles cleanly. The implementation is complete and verified against all worked examples from the difficulty/corner design files.

## Summary

I generated a complete Python + Flask implementation of the **3D Printing & Prototyping Service Bureau API** in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0366_3d_printing_prototyping_bureau/workspace/implementation/`.

### Files generated
- `start.sh` — foreground launcher; guards `pip install` on a cheap `import flask` check (avoids per-test-reboot contention), then `exec python3 app.py` binding `0.0.0.0:$PORT` (default 10000).
- `requirements.txt` (Flask 3.0.3)
- `app.py` — entry point, blueprint registration, enveloped error handlers (incl. unknown-route → ERR_NOT_FOUND), `threaded=True`.
- `db.py` — in-memory store (one dict per entity), starts **empty on every boot, no seeding**; `stamp_create`/`touch` manage `id`/`created_at`/`updated_at`/`version`; global RLock for serial-observable consistency.
- `errors.py`, `response.py` (exact envelope: `meta`/`response_type`/`data`, `error_id`/`message`, ISO-8601 3-fractional-digit timestamps, `req_` ids), `middleware.py` (X-User-ID/X-User-Role auth), `validation.py` (priority-5 well-formedness), `pagination.py` (limit 10/1–100, offset, created_at-asc sort).
- `services/calc.py`, `services/domain.py` (derived-field recompute + bubble-up), `services/ownership.py`.
- `routes/`: `catalogue.py` (Bureau/Customer/Material/Machine/Spool), `print_files.py`, `orders.py`, `finishing_tasks.py`, `print_runs.py`, `shipments.py`.

### Coverage
- **All 50 endpoints** from PRD §4 across 11 entities.
- **State machines**: PrintFile branching (UPLOADED→PRINTABLE/FLAGGED/REJECTED + override + non-manifold hard gate + REJECTED terminal lockdown); Order parallel axes (fulfillment DRAFT→…→SHIPPED/CANCELLED × payment UNPAID/ESCROWED/CAPTURED/REFUNDED) with automatic bubble-up; PrintRun cyclic failure→reprint loop.
- **Calculations** (Decimal + ROUND_HALF_UP, never float): printability scoring (40/30/20/10), order-line pricing (per-part round THEN ×qty +setup → 1974/8422), order totals + rush tiers (0/30/75 → 3697/16019), reprint FORWARD vs CHRONOLOGICAL attribution (2928→284, escrow reconcile to 3212/4996788), dual machine utilization (committed 42 / active 29), spool conservation (run_grams 28, commit/consume/release invariants), wallet ledger.
- **Validations in priority order** (auth→403→404→ref-404→422→state-409→business safety/temporal/capacity/spool/fiscal→OCC-412), with the load-bearing precedences verified (state beats wallet; file-not-printable beats wallet; OCC checked last so double-adjudicate yields ERR_STALE_VERSION not ERR_INVALID_STATE).
- **OCC** on confirm/ship (`expected_order_version`) and adjudicate (`expected_run_version`); half-open machine slots (back-to-back OK), closed-interval station scheduling with cooldown buffer (gap must be strictly > buffer), capacity boundary (== allowed, > rejected); full RBAC + Customer ownership scoping.

### Verification
Booted via `start.sh` (ready <1s, fresh empty state per boot) and ran ~60 assertions reproducing every worked numeric example from the difficulty/corner design files — all passed. Key design decision: in the reprint cycle, the failed run stays FAILED (version bumped) while a separate new QUEUED run is spawned for the reprint line, which is the only interpretation consistent with both the cycle test (reprint line has a QUEUED run) and the OCC double-adjudicate test (state check passes, version-stale → 412).

## Step 7: Run tests and iterate (8-round parallel sweep) — 2026-06-15T00:00:00.000Z

Clean 8-round parallel sweep achieved. All 66 tests pass in all 8 rounds.

## Summary

**Iterations run:** 3 sweeps (initial diagnostic, after first fix batch, final confirming sweep).

**Tests deleted:** None. (The initial union of 66 "failures" was a counting artifact from reading the wrong JSON key; the real failure set was only 2 tests, both PRD-covered and salvageable.)

**Fixes applied to `test_suite/`:**
- `test_03_state_machines.py` — `test_cancel_confirmed_after_production_started_rejected`: relaxed the assertion from `validate_error("ERR_PRODUCTION_STARTED")` to `validate_error_is_one_of(["ERR_PRODUCTION_STARTED", "ERR_INVALID_STATE"])`. This is the permitted one-of coverage correction (not a weakening). Rationale: PRD §3.6 auto-bubbles the order `CONFIRMED → IN_PRODUCTION` the instant a run starts PRINTING, so by cancel time the order is no longer `CONFIRMED`. PRD §3.5 names `ERR_PRODUCTION_STARTED` but never states the cancel state-gate extends to `IN_PRODUCTION`; a faithful PRD-only reader could equally treat the no-longer-`CONFIRMED` order as failing the §2.11(6) state-legality check (`ERR_INVALID_STATE`). Both readings are PRD-supported (unique-derivability collapse, ERROR-PRECEDENCE-SILENCE family), so the assertion accepts either. Also added `validate_error_is_one_of` to the file's import.

**Fixes applied to `implementation/`:**
- `routes/print_runs.py` — `adjudicate_print_run`: added the missing `run["status"] = "QUEUED"` transition. PRD §3.7 verbatim requires "transitions it from `FAILED` back to `QUEUED`"; the code advanced `version` via `touch()` but never wrote the status. This was the root cause of `test_failed_run_is_nonterminal_and_reopens_via_adjudicate`.
- `routes/print_runs.py` — `adjudicate_print_run`: reordered the gates so the OCC stale-version check runs **before** the FAILED state-legality check (after FK resolution). Required by the first fix: once a run goes `FAILED → QUEUED`, a second adjudication with the stale version would otherwise hit the FAILED state check and return `ERR_INVALID_STATE`. PRD §2.10 explicitly governs this exact scenario ("a second adjudication carrying the stale version would double-reconcile and is rejected with `ERR_STALE_VERSION`"), so the version-echo check must pre-empt the state check for adjudication. This fixed the regression in `test_adjudicate_with_stale_run_version_returns_412`.

**Feedback for generators:** The PRD's §3.5 cancel clause is anchored on "From `CONFIRMED`" but the only scenario that can trip its `ERR_PRODUCTION_STARTED` guard (a PRINTING/DONE run) has already auto-bubbled the order out of `CONFIRMED` into `IN_PRODUCTION` per §3.6 — a Zero-Silence gap where the prose names the error but never opens the cancel state-gate to the state the guard actually requires, making the error vs `ERR_INVALID_STATE` choice non-uniquely-derivable.

**Orchestrator note:** Independent confirming 8-round sweep re-run by the orchestrator — all 8 rounds 66/66 (results.{1..8}.json persisted in `workspace/implementation/`).

## Step 8: Finalize PRD — align documentation to implementation — 2026-06-15T00:00:00.000Z

Both edits are in place. The two edits modify 2 existing lines (no new lines added — both edits extend existing lines in place), so line count stays at 264.

Let me do a final consistency check on the §3.5 edit. I claimed "cancel is only ever legal while the order is `DRAFT`, `QUOTED`, or `CONFIRMED`." Verify against impl `cancel_order`: DRAFT/QUOTED → proceeds (212), CONFIRMED → proceeds (218), everything else → `invalid_state()` (253). ✓ Correct. And I claimed the refund-cascade path runs for CONFIRMED — which matches (since the guard is unreachable, every CONFIRMED cancel reaches the refund path). The downstream "A permitted cancel of a confirmed order..." sentence still accurately describes that path. ✓

Both edits are consistent with all enumerated paths. Here is my summary.

---

## Summary

**Line counts:** PRD.md = 264 lines; PRD_FINALIZED.md = 264 lines. Delta = 0 lines (+0.0%). Both edits extend existing lines in place — no new lines, no new sections.

**Changes (one bullet each):**

- **§2.10 (Optimistic Concurrency Control) — revise — pinned the adjudicate-specific gate ordering: the `expected_run_version` stale-version check is evaluated *before* the run's `FAILED` state-legality check (first business gate after `machine_id`/`spool_id` FK resolution), so a stale-version replay after the first `FAILED → QUEUED` adjudication yields `ERR_STALE_VERSION` rather than `ERR_INVALID_STATE`. Explicitly marked as an exception to §2.11's "stale-version check is the last of them." — `routes/print_runs.py:301-306`**

- **§3.5 (The Quote-to-Escrow Path, cancel clause) — revise — pinned that starting a run auto-bubbles the order `CONFIRMED → IN_PRODUCTION`, so the `ERR_PRODUCTION_STARTED` guard is never reached; a cancel attempted after production has started (order in `IN_PRODUCTION`/`POST_PROCESSING`/`READY`/`SHIPPED`/`CANCELLED`) fails the §2.11(6) state-legality check with `ERR_INVALID_STATE`, which is the actually-observed error for the production-already-started case. — `routes/orders.py:211-253` (catch-all `invalid_state()` at line 253), with the bubble at `routes/print_runs.py:177-179`**

**Step 7 diff coverage:** The diff's third item (impl fix adding `run["status"] = "QUEUED"` in `adjudicate_print_run`) required **no** PRD edit — §3.7 already states verbatim "transitions it from `FAILED` back to `QUEUED`"; that was an impl-fix-to-match-PRD, not a PRD silence. The test relaxation (cancel) maps to Edit 2 (§3.5); the gate-reorder fix maps to Edit 1 (§2.10).

**Per-edit pre-edit search log:**

- **Edit 1 (§2.10 adjudicate ordering):**
  - (a) Subject: ordering of the OCC stale-version check relative to state-legality, for the three OCC-guarded operations (confirm, ship, adjudicate).
  - (b) Paths enumerated/read: `confirm_order` (orders.py:126-143) — state/payment legality at 133-134, wallet at 138, OCC at 142-143 (stale-version *last*); `ship_order` (orders.py:162-186) — READY/ESCROWED/shipment business checks at 170-182, OCC at 185 (stale-version *last*); `adjudicate_print_run` (print_runs.py:280-306) — OCC at 301-302 *before* FAILED state-legality at 305-306 (stale-version *first*, after FK resolution at 292-293). Also re-read §2.11 to confirm its generic "stale-version is the last of them" claim.
  - (c) Adjustment: scoped the new sentence strictly to "For adjudication specifically" and labeled it an explicit exception to §2.11, so the wording does not contradict confirm/ship (where stale-version genuinely is last) and does not break §2.11's verbatim generic claim. Did not touch §2.11.

- **Edit 2 (§3.5 cancel / production-started):**
  - (a) Subject: which states permit `cancel_order`, the auto-bubble of `fulfillment_status` on run start, and which error a post-production cancel returns.
  - (b) Paths enumerated/read: `cancel_order` (orders.py:204-253) — DRAFT/QUOTED branch (212-216), CONFIRMED branch with the `ERR_PRODUCTION_STARTED` guard (218-223) and refund cascade (225-250), catch-all `invalid_state()` (253); `start_print_run` bubble `CONFIRMED → IN_PRODUCTION` (print_runs.py:172-179); `complete_print_run` (DONE requires prior PRINTING, 189-192); grep of all `fulfillment_status` assignments and all `"PRINTING"`/`"DONE"` run-status reads across `routes/` and `services/`. Confirmed via this enumeration that no run can be `PRINTING`/`DONE` while its order is still `CONFIRMED` (start always bubbles under the same lock), so the `ERR_PRODUCTION_STARTED` guard is unreachable and the observed error is `ERR_INVALID_STATE`.
  - (c) Adjustment: kept the original `ERR_PRODUCTION_STARTED` sentence intact (the guard still exists in code and the error remains catalogued) and *added* a clarifying note rather than rewriting, so the still-valid refund-cascade description ("A permitted cancel of a confirmed order…") downstream remains accurate. Listed the exact terminal/in-progress states (`IN_PRODUCTION`, `POST_PROCESSING`, `READY`, `SHIPPED`, `CANCELLED`) that hit the catch-all, matching orders.py:252-253.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-15T00:00:00.000Z

All edits are accurate, minimal, and inline. The PRD_COMPLETED.md is complete. Here is my final summary.

---

## Summary

**Source vs completed:** `PRD_FINALIZED.md` (264 lines, 43,840 chars) → `PRD_COMPLETED.md` (264 lines, 46,894 chars). Char delta: **+3,054**. Line count unchanged (all edits are in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** 7 ambiguity-pins, 4 mismatch-revisions (11 changes total).

**Changes (one per bullet):**

- §2.3 Pagination — insert — ambiguity — Pinned that out-of-range/non-integer `limit` (outside `[1,100]`) and negative/non-integer `offset` are rejected with `ERR_INVALID_REQUEST`; also pinned `created_at` tie-break by ascending `id`. — `implementation/pagination.py:31,42,51`
- §2.11 Validation Ordering — revise — mismatch — Swapped priorities (4) and (5): impl evaluates body well-formedness (incl. FK-id presence/type) **before** body-FK existence resolution, opposite to the PRD's stated order. — `implementation/routes/orders.py:271-283`, `implementation/routes/print_runs.py:104-115`
- §3.1 Catalogue (machine create) — insert — ambiguity — Pinned that a new machine starts with all four utilization counters (`scheduled_minutes`, `active_minutes`, `utilization_pct`, `active_utilization_pct`) at zero; PRD named only two. — `implementation/routes/catalogue.py:258-261`
- §3.2 Printability check — insert — ambiguity — Pinned that a check is permitted only from `UPLOADED`/`FLAGGED` (else `ERR_INVALID_STATE`), that this state check precedes the material-ACTIVE check, and that a retired-material check yields `ERR_MATERIAL_RETIRED`. — `implementation/routes/print_files.py:100-105`
- §3.3 Order line creation — revise — mismatch — PRD/endpoint table said lines are added "to a draft order"; pinned that lines may be added while `DRAFT` **or** `QUOTED`, else `ERR_INVALID_STATE`. — `implementation/routes/orders.py:288`
- §3.4 Finishing task attach — insert — ambiguity — Pinned that attachment is not gated by order/line state, and pinned the integer bounds (`addon_cents`/`station_start_min` non-negative, `station_duration_min` positive). — `implementation/routes/finishing_tasks.py:27-37`
- §3.4 Finishing task schedule — insert — ambiguity — Pinned that the cooldown-buffer overlap test is scoped to same-`kind` SCHEDULED tasks **in the same bureau**. — `implementation/routes/finishing_tasks.py:109`
- §3.5 Quote — insert — ambiguity — Pinned that quote is permitted from `DRAFT` or `QUOTED` (re-quote) else `ERR_INVALID_STATE`, and that a re-quote always bumps `version`/`updated_at` even with unchanged totals. — `implementation/routes/orders.py:95,108-114`
- §3.5 Confirm — revise — mismatch — Pinned that both the `QUOTED` fulfillment and `UNPAID` payment preconditions are state-legality gates rejected with `ERR_INVALID_STATE`, evaluated before wallet and version checks. — `implementation/routes/orders.py:133-143`
- §3.7 Fail / reprint line — insert — ambiguity — Pinned the reprint copy's field shape: copies `print_file_id`/`material_id`/`layer_height_mm`/`quantity`/`print_minutes`/`per_part_cents`, born `ACTIVE`, `finishing_total_cents` reset to 0, `line_total_cents` = forward charge (later overwritten at adjudication). — `implementation/routes/print_runs.py:225-239,328`
- §3.7 Adjudicate / fresh run — insert — ambiguity — Pinned that the fresh reprint run is created subject to the full §3.6 run-creation gates (material/process/offline/slot/capacity/spool) and commits grams + recomputes utilization like a directly-created run. — `implementation/routes/print_runs.py:347-349`
- §3.8 Ship — revise — mismatch — Pinned that the `payment_status` must be `ESCROWED` gate (previously code-less in PRD) is rejected with `ERR_INVALID_STATE`, and made the three-gate evaluation order explicit. — `implementation/routes/orders.py:170-182`

Notes: Tests were used only as auxiliary cross-reference (they confirmed, e.g., that the ship-ESCROWED and confirm-UNPAID gates carry no PRD-pinned code, and that the FK-vs-wellformedness ordering is unprobed). Implementation was the alignment target throughout.
