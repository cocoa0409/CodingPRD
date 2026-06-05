# Worklog — task_0057_etc_toll_road

## Step 1: Create task directory — 2026-05-30

Created `tasks/task_0057_etc_toll_road/` and `tasks/task_0057_etc_toll_road/workspace/`. Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate scaffold (Expert) — 2026-05-31

All three artifacts generated and lint-clean. Summary of what was produced.

### Generated: `task_0057_etc_toll_road` (Expert difficulty)

Three artifacts written: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (287 calls scanned)

#### Complexity profile
Primary archetype **pricing_engine** + secondary **compliance_audit**; layers: dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency, derived-field reconciliation. Flat topology (FK references), parallel state-machine shape, peer_roles, immediate consistency.

#### SCAFFOLD.yaml counts
- **Entities: 10** — Account, Vehicle, Transponder, TransponderBinding, HovWindow, Plaza, TollTransaction, Violation, InteropAgency, LedgerEntry (append-only, `common_fields:false`).
- **State machines: 5** — Account (lifecycle w/ DELINQUENT auto-flip), Transponder, TollTransaction split into **two parallel dimensions** (pricing_status × settlement_status), Violation (**cyclic** ASSESSED↔CONTESTED re-issue).
- **Concurrency rules: 2** (OCC) — binding-create-stale-vehicle (on Vehicle.version), reprice-stale-transaction (on TollTransaction.version).
- **Calculations: 6** — toll_pricing (transponder vs plate variants), trip_multi_segment_toll (pinned round-per-segment-then-sum), violation_fine (tiered escalation), auto_reload_amount (FIXED vs RESTORE_TO_TARGET variants), account_outstanding_fines, interop_home_share.
- **Validations: 18** (priority-ordered, categories auth→existence→state→business_*→concurrency→validation).
- **Endpoints: 43** (CRUD + action endpoints for pricing/settlement/violation pipeline/account lifecycle/HOV/interop, plus filtered-list & sub-resource GETs for FK reverse-reachability).
- **Errors: 19.**
- **Roles: 4** — AccountHolder (entity_backed:Account), TollOperator, InteropClerk, SystemAdmin (all opaque).

#### Difficulty design
**9 rules × 2 instances = 18 instances**, all 9 §0.5 rule_ids covered. All formula-derived asserts pre-computed as literals.

#### Corner design
**9 sections, 41 instances** with `excluded_because:` stubs where §1.8 already covers the corner.

**Key design notes:** Toll-by-Plate (PLATE non-interop) reads price but stay UNSETTLED awaiting manual settle or violation; TRANSPONDER reads and interop PLATE reads auto-settle/debit at price time (interop withholds a clearing fee). HOV exemption evaluated at price time against declared occupancy ≥ plaza minimum. Cross-state interop path debits the net (gross minus settlement fee).

## Step 3: Copy INSTRUCTION.md — 2026-05-31

Copied `./INSTRUCTION.md` → `tasks/task_0057_etc_toll_road/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-31

PRD generated at `workspace/PRD.md` (282 lines).

- **Top-level sections:** 5 (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue)
- **Subsections:** 19 total — 9 in §2, 10 in §3

### Hard Contract reports
Field coverage: 55/55 entity fields, 46/46 endpoint inputs/query_params — PASS.
Rule coverage: 18/18 validations, 2/2 OCC rejections, all 5 state machines, 6/6 calculations, 19 error IDs — PASS.
Path purity (§3): 334 backtick tokens, 0 path/method tokens — PASS.

### Notable coverage decisions
- §2.2 verbatim from canonical source.
- Parallel state machines pricing_status × settlement_status kept explicitly independent in §3.6/§3.7/§3.8.
- `ERR_UNRESOLVED_READ` (in error catalog, absent from priority validations) given a home in §3.6.
- Validation priority stated as explicit ordered list in §2.9 (business band priorities 6–16 in relative order).
- Scattering: OCC version fields in §2.6, workflows in §3.4/§3.7; pricing inputs split §3.6 + §3.5 (HOV occupancy).
- Neither DIFFICULTY nor CORNER design yaml opened.

## Step 5: Generate unit tests — 2026-05-31

Generated complete test infrastructure under design-index-only contract.

**Stage 1 — `test_helpers/` (9 files):** types.py, api_client.py, api_errors.py (18 error IDs + HTTP map), assertions.py, factories.py, constants.py, test_users.py (opaque roles + `make_account_holder_headers(account_id)` per-instance builder for entity_backed AccountHolder), fixtures.py (composite tiers), __init__.py.

**Stage 2 — `test_suite/` (conftest + 8 test files, 69 tests):**
- Queue A (Difficulty): 18/18 instances translated, 0 skipped, 36 tests.
- Queue B (Corner): 33/33 non-stub translated, 8 stubs excluded by design, 33 tests.

**Skips:** All 8 `excluded_because:` corner stubs correctly NOT translated; all 8 difficulty_instance cross-refs resolve. No PRD-first filter skips needed (PRD unusually complete — inclusive auto-reload boundary, half-open binding abutment, 15-min HOV buffer, round-per-segment-then-sum, full §2.9 validation priority order, every error trigger in prose).

**Verification:** All 17 files parse; every docstring ends with one verbatim `Design:` tag resolving to a real instance; coverage audit passes.

## Step 6: Generate implementation — 2026-05-31

Built complete Python + Flask in-memory implementation in `workspace/implementation/`.

**Files (16):** start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0), requirements.txt (Flask 3.0.3), app.py, db.py (in-memory Store), errors.py, response.py, middleware.py (X-User-Role/X-User-ID auth + role gating), util.py (round_half_up via Decimal, pagination default 10/max 100), serialize.py, services/core.py, routes/ (accounts, ledger, vehicles, transponders, bindings, hov, plazas, interop, transactions, violations).

**Endpoints: 42 implemented.**

**Notable:** validation priority per §2.9 exactly; integer cents + Decimal ROUND_HALF_UP; parallel pricing_status × settlement_status; cascades bump updated_at/version; OCC on exactly 2 writes (expected_vehicle_version for bindings, expected_transaction_version for reprice); LedgerEntry omits updated_at/version; no seeding (boots empty). Smoke-tested: pricing, HOV 15-min buffer (10min rejected, 15min allowed), violation cascade, stale-version, reprice, batch-trip.

## Step 7: Test and fix loop — 2026-05-31

All 8 parallel rounds pass cleanly (69/69 each → 68/68 after 1 deletion). Exiting.

**Iterations run:** 1 sweep to diagnose, 1 sweep to confirm (2 total).

**Tests deleted (1):**
- `test_ownership_mismatch_on_binding` (in `test_suite/test_07_validations_errors.py`) — **ERROR-PRECEDENCE collapse**. Test expected `ERR_OWNERSHIP_MISMATCH` (priority-6) but impl correctly returned `ERR_NOT_RESOURCE_OWNER` (priority-4). Per PRD §2.9, resource ownership (4) evaluated strictly before binding ownership-match (6). Binding endpoint is AccountHolder-only; priority 4 requires holder to own both transponder and vehicle, so their account_id values are necessarily equal — priority-6 mismatch can never fire. Assertion unreachable for any PRD-faithful impl; not repairable in test_helpers — deleted.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/start.sh` — gated `pip install` behind an `import flask` check so it only runs on true cold start. Under per-test-server isolation start.sh runs before every test; re-running pip install each restart added contention that pushed boot past the 15s restart-poll window during the 8× concurrent sweep, surfacing a spurious "API server could not be restarted" setup error on `test_account_missing_required_field`. Standalone single-server run already passed 69/69, confirming load-induced boot latency, not an app bug. No application logic changed.

**Key finding:** `test_account_missing_required_field` failure was pure boot-latency flakiness exposed only by the concurrent sweep. The ownership-mismatch test was a genuine unfair test (PRD precedence ordering makes the asserted error unreachable).

## Step 8: Finalize PRD — 2026-05-31

`PRD_FINALIZED.md` produced as a verbatim copy of `PRD.md` (282/282 lines, 0% delta). No changes — neither Step 7 diff item reveals PRD silence or PRD/impl mismatch.

1. Test deletion traces to validation ordering PRD §2.9 already states (ownership priority 4 preempts binding-match priority 6; impl `routes/bindings.py:36-40`/`:53-55`). PRD already determines this; no edit.
2. start.sh pip-install gating is pure infra/boot-timing; no PRD-observable behavior. No edit.

PRD_FINALIZED.md confirmed byte-identical to PRD.md.

## Step 9: Complete PRD — 2026-05-31

`PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` (282/282 lines, +2,049 chars; all edits in-paragraph). **9 ambiguity-pins, 0 mismatch-revisions** — no PRD passage contradicted impl; every gap was silence.

Changes:
- §2.3 Pagination — list ordering by creation order, internal `_seq` tiebreak on identical `created_at`.
- §3.2 suspend — optional `reason` accepted but not persisted.
- §3.2 reinstate — rejected with `ERR_INVALID_STATE` (409) when outstanding fines.
- §3.6 Record — captured plate stored uppercased; plate resolution by uppercased plate+state; transponder resolution via binding active at `read_at` (effective_from inclusive / effective_to exclusive).
- §3.6 transponder debit — `TOLL_DEBIT` carries `ref_transaction_id`, null `ref_violation_id`.
- §3.6 interop debit — `INTEROP_DEBIT` carries `ref_transaction_id`.
- §3.7 Reprice — same read method (no HOV/registration re-check), ledger entry only when delta non-zero, signed negative delta (credit on lower toll), auto-reload runs.
- §3.7 Manual settle — remainder is full `toll_cents`, ledger carries `ref_transaction_id`, entry skipped when `toll_cents` is 0.
- §3.7 Batch trip — no HOV, no owner resolution (null `vehicle_id`), all segments PRICED+SETTLED, single trip-total `TOLL_DEBIT` with null `ref_transaction_id`, 201 with array.
- §3.8 Pay violation — `VIOLATION_SETTLE` carries both `ref_violation_id` and `ref_transaction_id`.

Pipeline complete. Final test state: 8/8 parallel rounds passing, 68/68 tests.
