# Worklog — task_0370_custom_picture_framing

## Step 1: Create Task Directory — 2026-06-15T00:00:00.000Z

Created `tasks/task_0370_custom_picture_framing/` and `tasks/task_0370_custom_picture_framing/workspace/` (bash, no subagent). Output folder pre-allocated; no ./tasks scan or index increment performed.

## Step 2: Generate Scaffold (Expert) — 2026-06-15T00:00:00.000Z

Generated an **Expert-difficulty** scaffold for **Custom Picture Framing** — three files, lint clean.

**Verdict block (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Profile:** primary archetype `pricing_engine` + secondary `workflow_orchestration`; layers dual-variant calculation, cascading side effects, derived-field reconciliation, optimistic concurrency; topology `flat`; state-machine shape `parallel`; role model `peer_roles`; consistency `immediate`.

**Scaffold counts (SCAFFOLD.yaml, §1.0–§1.7):**
- **Entities: 7** — Customer, Workbench, FramingOrder, FrameLine, ProductionTask, Payment, Notification (Notification is `common_fields:false` append-only).
- **State machines: 5 across 4 entities** — FramingOrder `production_status` (branching INTAKE↔QUOTED revision cycle + cancel/pickup branches) and `payment_status` (parallel dimension); FrameLine `line_status` (branching DRAFT→MEASURED / DRAFT→VOID); ProductionTask `task_status` (linear). 1 concurrency rule (OCC on FramingOrder.version for FrameLine add).
- **Calculations: 8** — `line_cost` (tiered/oversize + conservation-multiplier, NOMINAL/MEASURED variants), `quote_estimate_total` (sum-then-round), `final_invoice_total` (round-per-line), `deposit_required` (fragile floor + MIN), `turnaround_days`, `forward_no_show_risk`, `settled_reputation` (chronological per-step clamp), `order_ledger`.
- **Validations: 11** (priority-ordered, auth→fiscal). **Endpoints: 31.** **Errors: 27.** **Roles: 4** (FrameDesigner, FrameProductionTech, FrontDeskClerk opaque; Customer entity_backed).

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids × 2 instances = 18 instances, every formula-derived assert a pre-computed literal.

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:** 42 instances across all 9 claim-extraction sections; 61 total instance names, all unique.

**Key impl note:** `api_prefix` is `""` (root) — flat multi-collection topology, FK reverse-reachability via sub-resource GETs.

## Step 3: Copy Shared Files — 2026-06-15T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0370_custom_picture_framing/workspace/INSTRUCTION.md` (bash, no subagent).

## Step 4: Generate PRD — 2026-06-15T00:00:00.000Z

Generated `workspace/PRD.md` (255 lines) from the Custom Picture Framing scaffold (expert tier; pricing_engine + workflow_orchestration). Design files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) withheld per contract.

**Sections:** §1 Intro; §2 Global Specs (RBAC 4 roles, envelope, pagination, common props incl. Notification `common_fields:false`, nesting/left-to-right, validation priority 1–11, dual rounding disciplines, OCC, fragile/glass); §3 Business Logic (9 lifecycle subsections); §4 endpoint table (31); §5 error table (26).

**Coverage:** 7 entities; 31 endpoints; 8 calculations (line_cost NOMINAL/MEASURED, quote_estimate_total sum-then-round, final_invoice_total round-per-line, deposit_required, turnaround_days, forward_no_show_risk, settled_reputation chronological replay, order_ledger); 26 errors; 4 parallel state machines (production_status, payment_status, line_status, task_status) with cascades (pickup→customer scores, cancel→refund ledger).

**Hard Contracts — all PASS:** Contract 1 (Field-Name Coverage) 61 identifiers 0 missing; Contract 2 (Rule Coverage) all 26 errors in narrative, OCC stale-version rule expressed, validation priority stated, both rounding disciplines reconstructible; Contract 3 (§3 Path Purity) 308 tokens, 0 violations.

## Step 5: Generate Unit Tests — 2026-06-15T00:00:00.000Z

**Stage 1 — `test_helpers/` (9 files):** types.py (entity TypedDicts; Notification omits version/updated_at), api_client.py (one method per endpoint), api_errors.py (24-error catalog), assertions.py, factories.py, constants.py, test_users.py (opaque staff roles + make_customer_headers for entity-backed Customer), fixtures.py (lifecycle helpers: quoted/deposit-paid/in-production/ready/picked-up, fragile, multi-line), __init__.py.

**Stage 2 — `test_suite/` (7 files + conftest), 78 test functions:**
- **Queue A (Difficulty): 36 tests** — all 18 instances × 9 rule_ids, exactly 2 tests each.
- **Queue B (Corner): 42 tests** — all 42 non-stub instances, exactly 1 test each.

**Instances skipped:** none of the non-stub instances. The single `excluded_because` stub (`errors/task_complete_when_order_not_in_production_returns_error`) correctly NOT translated.

**Verification:** all files byte-compile; 78 verbatim `Design:` tags (36 Difficulty + 42 Corner) exactly match YAML instance names; every PRD citation verified verbatim; no skip/xfail; no scaffold leakage; Customer ownership reads thread real customer_id via make_customer_headers. (Runner not installed in subagent env — static/compile verification only.)

## Step 6: Generate Implementation — 2026-06-15T00:00:00.000Z

**Stack:** Python 3 + Flask 3.0.3, in-memory dict storage only (no SQLite/disk). Store empty on every boot; **no seeding**.

**Files (`workspace/implementation/`):** start.sh (cd, flask-import guard, `exec python3 app.py`), app.py (blueprints, ApiError/404/405/Exception handlers, `host=0.0.0.0 port=$PORT threaded=True`), db.py (in-memory Store, UUID/now_iso/req_ helpers), errors.py (24 codes + HTTP statuses), response.py (exact envelope), middleware.py (X-User-ID/X-User-Role, RBAC), validate.py (body + pagination), services/calc.py (7 calcs, Decimal+ROUND_HALF_UP), services/domain.py (stamping/touch/serializers/cascades), routes/ (customers, workbenches, orders, frame_lines, production_tasks, payments, notifications).

**Endpoints:** all 31 from PRD §4. **Calculations:** line_cost NOMINAL/MEASURED (non-additive oversize tiers 80→40,120→95; conservation 1.20×; +45 labor), quote_estimate_total sum-then-round (rush 1.15, loyalty), final_invoice_total round-per-line, deposit_required (fragile floor 0.50, MIN 25.00), turnaround_days (base 14, rush 7, +5 fragile), forward_no_show_risk (open×5 + ready-unpaid×15, clamp 100), settled_reputation (chronological replay ONTIME −10/ABANDON +20, per-step clamp), order_ledger.

**Smoke-verified:** full lifecycle; OCC 412; fragile→glass-bench; glass-bench buffer conflict vs assembly half-open overlap; cancel cascade (tasks RELEASED, refund, REFUNDED, scores); pickup/cancel score recompute; RBAC + Customer ownership; validation precedence (401>403>404>400>412>409state>409ref>409fragile/conflict>402); all 24 error codes; pagination meta. **start.sh:** reads $PORT (default 10000), binds 0.0.0.0 foreground via exec.

## Step 7: Run Tests and Iterate — 2026-06-16T00:00:00.000Z

All clean: 0 skipped, 78/78 passed in every one of the 8 concurrent rounds.

## Summary

**Iterations run:** 1 (the first 8-round parallel sweep passed cleanly, satisfying the exit condition immediately).

**Sweep result:** All 8 concurrent rounds reported `passed=78, total=78, failed=0, errors=0, skipped=0`. The union of failing tests across all 8 rounds is empty, so there is no flakiness signal — no timing-sensitive concurrency, fixture-ordering, or port-collision failures surfaced under the ~8× peak-load sweep.

**Tests deleted:** None. Every test passed; the diagnostic protocol (STEP 0–3) was never triggered because there were no failures to triage.

**Fixes applied to `test_helpers/`:** None needed.

**Fixes applied to `implementation/`:** None needed.

The implementation at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0370_custom_picture_framing/workspace/implementation/` already satisfies the full PRD-derived test suite. Key correctness areas confirmed passing across the sweep: the dual sum-then-round vs. round-per-line pricing disciplines, per-line cost formula with tiered oversize/conservation multiplier, the deposit floor and turnaround rules, the parallel production/payment state machines, OCC on frame-line add, the validation-priority ordering (state-beats-fiscal, fragile-beats-temporal), workbench half-open overlap and glass-bench clean-buffer boundaries, the cancel refund/release cascades, customer no-show-risk and settled-reputation scoring, RBAC/ownership, and append-only notifications. Storage is in-memory only (process-local dicts wiped on each `start.sh` reboot under per-test-server isolation), with no startup seeding.

No further action required — the loop exits on a clean 8-round parallel sweep.

## Step 8: Finalize PRD — SKIPPED — 2026-06-16T00:00:00.000Z

Skipped per SKILL skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at every Step 7 site, so no `PRD_FINALIZED.md` is produced. Step 9 (full impl scan) still runs and starts from PRD.md.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-16T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-`implementation/` scan, starting from `PRD.md` (no `PRD_FINALIZED.md` since Step 8 skipped).

**File comparison:**
- `PRD.md`: 255 lines, 41,414 chars
- `PRD_COMPLETED.md`: 255 lines, 43,095 chars
- Char delta: **+1,681**; line count unchanged (all edits in-paragraph / in-table-cell, no new sections or paragraphs)

**Change counts:** 7 ambiguity-pins, 0 mismatch-revisions. (No outright PRD-vs-impl contradictions were found; all gaps were PRD silence on behavior the implementation actually exhibits.)

**Per-change list:**

- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` is silently clamped into range (limit→[1,100], offset→[0,∞)) rather than rejected; non-integer values rejected with `ERR_INVALID_REQUEST` — `validate.py:96-118`
- §2.3 Pagination — insert — ambiguity — list ordering breaks `created_at` ties on `id` ascending — `services/domain.py:38,44,54` and every route's `sort(key=lambda ...: (x["created_at"], x["id"]))` (e.g. `routes/customers.py:56`)
- §3.2 Intake (measure/void line) — insert — ambiguity — measuring or voiding a line not in `DRAFT` is rejected with `ERR_INVALID_STATE`, with the `ERR_ORDER_NOT_EDITABLE` order-editability check evaluated first — `routes/frame_lines.py:143-148, 174-178`
- §3.5 Order Ledger (apply payment) — insert — ambiguity — client `kind` restricted to `{DEPOSIT, BALANCE}` (else `ERR_INVALID_REQUEST`; `REFUND` is system-only) and `amount` must have at most two decimal places (else `ERR_INVALID_REQUEST`) — `routes/payments.py:16,26-33,43`
- §3.6 Production (complete task) — insert — ambiguity — order-state check (`ERR_ORDER_NOT_IN_PRODUCTION`) precedes task-state check; completing a non-`SCHEDULED` task (`COMPLETED`/`RELEASED`) is rejected with `ERR_INVALID_STATE` — `routes/production_tasks.py:133-138`
- §3.9 Notifications — insert — ambiguity — channel selection prefers `EMAIL` when the customer has a non-empty email (with `sent_to`=email), falling back to `SMS`+phone only when no email — `routes/orders.py:403-421`
- §4 Endpoint table (List FramingOrders) — insert — ambiguity — "filterable" pinned to optional exact-match `customer_id` and/or `reorder_of_order_id` query params; unrecognized params ignored — `routes/orders.py:104-109`

**Pipeline complete.** All 9 steps recorded; final artifacts present (`PRD_COMPLETED.md`, 8× passing `results.{1..8}.json`).

