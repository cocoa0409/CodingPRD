# Worklog — task_1014_candle_soap_bath_dtc

## Step 1: Create task directory — 2026-07-14T03:43:00.000Z

Created `tasks/task_1014_candle_soap_bath_dtc/` and `tasks/task_1014_candle_soap_bath_dtc/workspace/`. Folder pre-assigned (no index scan performed).

## Step 2: Generate scaffold (Expert) — 2026-07-14T04:12:00.000Z

All three artifacts are generated, parse cleanly, honor the file split, and pass `scaffold_lint.py` with `VERDICT: clean lint`. Verified independently with `yaml.safe_load` (all 3 OK).

Generated an **Expert**-difficulty scaffold for scenario 1014 (Candle, Soap & Bath DTC):
- `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** primary archetype quota/allocation (batch inventory reserved→committed→released) blended with a pricing engine (bulk tiers, loyalty, drop/bundle pricing); flat topology; parallel state-machine shape; layers = rate/threshold triggers, cascading side effects, derived-field reconciliation, optimistic concurrency, selector policy.

**Counts:**
- **Entities: 10** — Product, Sku, Batch, Drop (embeds listings), Bundle (embeds items), Customer, Order, OrderLine, Return, Subscription.
- **Endpoints: 43** — one logical clock (`/_clock/set_current_utc`, default `2026-07-01T00:00:00Z`) plus per-entity CRUD/lifecycle and filtered-list reverse-reachability GETs for every FK.
- **Errors: 29** (Expert 18–30). **Calculations: 6.** **Roles: 3** (Customer entity-backed; MerchOps + PlatformAdmin opaque, hierarchical override).
- **State machines: 8** — Batch (branching + auto-transitions), Drop (clock-driven), Bundle, Customer, Order (**parallel** payment × fulfillment), OrderLine, Return (**branching**), Subscription (**cyclic** renew self-loop). One concurrency rule (OCC on `Order.version` at checkout, 412).

**Difficulty design:** 18 instances = 9 rules × 2, each differentiated per §0.5. All formula-derived asserts are pre-computed literals.

**Corner design:** 9 sections, 29 executable instances + 6 `excluded_because` stubs (each citing a real §1.8 instance).

Key modeling notes: loyalty bookkeeping uses per-line credit at checkout, per-voided-line reversal on recall, and revoke at return-settle so both conservation invariants hold; `api_prefix` set to empty to match the flat multi-collection topology.

## Step 3: Copy shared files — 2026-07-14T04:14:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1014_candle_soap_bath_dtc/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-14T04:20:00.000Z

PRD generated at `workspace/PRD.md` (295 lines). Did not open either withheld design file.
- Sections: 5 top-level (Introduction; Global Specifications 2.1–2.11; Business Logic 3.1–3.10; Endpoint Definitions; Error Code Catalogue).
- Endpoints documented: 43 (incl. `/_clock/set_current_utc`). Entities: all 10. Errors: 29.
- Field coverage: all 66 required identifiers present, PASS. Rule coverage: PASS. Path purity (§3): PASS.

Judgment call flagged by subagent: delivery-time loyalty balance — scaffold has internal tension (Order `fulfill` note "NO balance change" vs endpoint text "balance += (awarded − provisional)"). PRD §3.7 written to the invariant-preserving state-machine reading: `awarded_points` computed over non-voided lines, balance settled at that value (framings coincide when no recall intervenes).

## Step 5: Generate unit tests — 2026-07-14T04:33:00.000Z

Complete test infra in `test_helpers/` (9 files) + `test_suite/` (conftest + 8 test files, **65 tests**, all collect cleanly).
- Queue A (Difficulty): 36 tests — all 18 instances (9 rules × 2) covered by exactly 2 tests each.
- Queue B (Corner): 29 tests — all 29 non-stub instances covered by exactly 1 test each.
- Every test carries exactly one `Design:` tag; 36+29 tags map 1:1 to real instance names (no untagged/dual/dangling). All 84 PRD citations pass verbatim check.
- No instances skipped. 6 `excluded_because` stubs correctly not translated.
- Scoping decision: `product_create_returns_201_with_fields` — PRD §2.4 doesn't pin initial version integer (not uniquely derivable), so test asserts 201 + field-echo, not absolute version. Relative `version == expected + 1` on checkout (§3.7) is asserted.

## Step 6: Generate implementation — 2026-07-14T04:33:00.000Z

Complete Python + Flask implementation at `workspace/implementation/`. Files: `app.py` (single-file, all 43 endpoints), `requirements.txt` (Flask>=2.2), `start.sh` (executable; reads $PORT default 10000, binds 0.0.0.0, foreground). Verified: 43 registered routes == 43 endpoints; `ast.parse` OK; in-memory dicts wiped every boot; nothing seeded.

Verified end-to-end against a live server: auth/RBAC/ownership, catalog + computed `requires_safety_label`, batch cure-window conflict, safety-label gating, order build → OCC stale-version → checkout pricing → fulfill → return settle, subscription renewal, bulk discount tiers + free-ship + bulk-min, drop exclusive pricing/liveness/window-overlap, full recall cascade. Batch availability invariant holds after recall.

Key ambiguities resolved: `created_at`/`updated_at` from logical clock (not wall-clock); `version` starts at 1; unit-price override only for LIVE exclusive drops; ownership-vs-existence ordering per priority; pagination clamp with non-integer → ERR_VALIDATION; email uniqueness via ERR_VALIDATION; provisional loyalty over RESERVED lines floor-per-line-then-sum.

## Step 7: Run tests and iterate — 2026-07-14T04:40:00.000Z

**Clean first-sweep pass.** All 8 concurrent rounds green: 65/65 passed, 0 failed, 0 errors, no flakiness. Independently verified all 8 results.{1..8}.json show passed=65 total=65.
- Iterations run: 1 (single 8-round parallel sweep). No host saturation (no boot-timeout ERRORs); no fallback to 2-waves-of-4 needed.
- Tests deleted: none. Fixes to `test_helpers/`: none. Fixes to `implementation/`: none.
- Reusable sweep runner created at `run_sweep.sh`.

## Step 8: Finalize PRD — SKIPPED — 2026-07-14T04:40:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at the tested sites. No `PRD_FINALIZED.md` produced. Step 9 still runs (full impl scan).

## Step 9: Complete PRD — 2026-07-14T04:46:00.000Z

`PRD_COMPLETED.md` produced from PRD.md via full impl scan. 295→295 lines, +1,024 chars. Ambiguity-pins: 5, mismatch-revisions: 1. All in-paragraph inserts/revisions.
- §2.3 Pagination — insert — out-of-range limit/offset clamped to nearest bound, non-integer → ERR_VALIDATION, list tie-break by insertion/creation order (app.py:278-306).
- §2.10 Referential Existence — insert — non-resolving `order_line_id` → ERR_ORDER_NOT_FOUND (app.py:978).
- §3.3 Seasonal Drops — insert — `listings` may be empty, `is_exclusive` defaults false, only exclusive listing's `drop_price_cents` applied at pricing (app.py:690-710,410-418).
- §3.5 Customers — insert — duplicate email → ERR_VALIDATION (app.py:819-821).
- §3.7 Checkout — revise — mismatch: `provisional_points` computed over RESERVED lines only, not "every line" (app.py:1014,1048).
- §3.9 Subscription renewal — insert — renewal line `unit_price_cents` resolved as at line-add time (LIVE exclusive-drop price else list_price_cents) (app.py:1344,1368-1369).

Deliberately unchanged: order-line GET and list endpoints lack ownership check, but §2.1 scopes ownership to single-resource order/return/subscription actions and grants reads to all roles — permissible reading, left unpinned to avoid overreach.

---

## Pipeline complete — 2026-07-14T04:46:30.000Z

All 9 steps done. Final state: 65/65 tests pass across all 8 stability rounds. Task directory contains SCAFFOLD.yaml (+ 2 design files), worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/}.
