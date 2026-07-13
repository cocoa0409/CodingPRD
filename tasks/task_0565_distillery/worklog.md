# Worklog — task_0565_distillery

## Step 1: Create Task Directory — 2026-07-08T00:00:00.000Z

Created `tasks/task_0565_distillery/` and `tasks/task_0565_distillery/workspace/` (index pre-assigned by orchestrator; no rescan). Scenario: Distillery & Spirits Production (DSP/TTB). Difficulty: Expert (passed to scaffold-generator only).

## Step 2: Generate Scaffold — 2026-07-08T00:00:00.000Z

Generated a fresh **Expert**-difficulty scaffold for the Distillery & Spirits Production (DSP/TTB) scenario. All three files parse cleanly and `scaffold_lint.py` returns **`VERDICT: clean lint`** (352 §1.8/§1.9 calls conform to §1.5; all FKs reverse-reachable).

**Design profile:** Ledger-reconciliation primary archetype × compliance/audit secondary; flat topology; parallel state-machine shape; peer-roles model; immediate consistency. Core mechanic is proof-gallon conservation across production/storage/processing/removed/losses accounts plus tiered CBMA federal excise.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **11 entities** — Distillery (root ledger + OCC version), MashBatch, DistillationRun, Barrel, LabelApplication (COLA), BottlingRun (also holds case inventory), TaxRemoval, ExciseReport, Customer, SalesOrder, TourBooking.
- **9 state machines** — including a cyclic LabelApplication (NEEDS_CORRECTION↔SUBMITTED) and a parallel-axis SalesOrder (payment × fulfillment).
- **6 calculations** — proof_gallons_gauge (VOLUME vs WEIGHT dual variant), angel_share_loss (decay), bottling_proof_gallons (pinned sum-then-round), excise_tax (tiered CBMA + provisional/final variants), proof_gallon_ledger (conservation identity), order_pricing.
- **18 ordered validations**, **51 endpoints** (includes mandatory single+list reads for FK reverse-reachability, action endpoints, a logical clock defaulting to `2026-05-01T00:00:00Z`, and a `/_ledger/set_cbma_ytd` test-driving seed), **18 errors**, **5 roles** (4 opaque operators + entity_backed Customer).
- **1 concurrency rule** — ExciseReport CREATE-with-supersede, OCC on `Distillery.version` → `ERR_STALE_VERSION` (412).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all **9 Difficulty Rules × 2 = 18 instances**, every numeric assert pre-computed in Python.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **22 active corner instances** plus **4 `excluded_because` stubs** referencing §1.8 instances by name.

## Step 3: Copy Shared Files — 2026-07-08T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0565_distillery/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-08T00:00:00.000Z

**Output:** `workspace/PRD.md` — 5 top-level sections, ~265 lines.
- §1 Introduction; §2 Global Specs (10 subsections: RBAC, response envelope, pagination, identity/versioning, logical clock, proof gallons/rounding/CBMA, bonded ledger + conservation invariant, cascade propagation, OCC for excise filings, referenced-resource resolution); §3 Business Logic (9 lifecycle subsections); §4 Endpoint table (52 endpoints incl. `_clock`/`_ledger`); §5 Error catalogue (18 errors).

**Hard contracts:** Field coverage PASS (0 missing), Rule coverage PASS (validation ordering, OCC, all state transitions, all 6 calculations, cascades, sibling symmetry), §3 path purity PASS. No worked-example test numbers copied in; both design YAMLs left unopened.

## Step 5: Generate Unit Tests — 2026-07-09T00:00:00.000Z

All files compile, all four corner stubs resolve to difficulty instances that I translated, and coverage is complete. Here is the summary.

## Summary

Generated complete test infrastructure for `task_0565_distillery` (Distillery/DSP-TTB API) driven **exclusively** from the two design indices.

### Files written

**`test_helpers/` (Stage 1 — 9 files):**
- `types.py` — 11 entity TypedDicts (all `common_fields: true`, so all carry `updated_at`/`version`) + 12 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~50 methods incl. `_clock`/`_ledger` test-driving)
- `api_errors.py` — 18-value `ApiErrorId` enum + HTTP status map, registered with the framework
- `assertions.py` — per-entity assertions + conservation-identity, bonded-total, and case-conservation invariant checkers
- `factories.py`, `constants.py`, `test_users.py` (opaque operator headers + entity-backed `make_customer_headers`), `fixtures.py` (composite chain `setup_completed_run` / `setup_paid_allocated_order` / tour + label helpers), `__init__.py` barrel export

**`test_suite/` (Stage 2 — conftest + 7 test files):** 57 tests, all collect clean.

### Coverage
- **Queue A (Difficulty):** all 9 rules × 2 instances = **18/18 instances, each with exactly 2 tests** (36 tests).
- **Queue B (Corner):** **21/22 non-stub instances covered** (1 test each). The 4 `excluded_because` stubs correctly left untranslated — their cited difficulty owners are all covered.
- Every test docstring carries exactly one verbatim `Design:` tag (57 tags / 57 tests) plus a verbatim PRD citation.

### Skipped instance (1)
- **`Corner/validations/taxpaid_removal_rounding_drift_hits_insufficient_bonded_pg`** — SKIPPED (fails unique-derivability). The instance asserts a third 4-case TAXPAID removal (computes 4.8 pg) is rejected with `ERR_INSUFFICIENT_BONDED_PG` because "processing is at 4.7 pg." But PRD §2.7 defines the guarded quantity `bonded_total_pg = production + storage + processing`, and the setup fills only 15 pg from a 20-pg gauged run, leaving **5.0 pg permanently in `production_account_pg`**. So at the third removal bonded_total = 5.0 + 0 + 4.7 = **9.7 pg ≥ 4.8 pg**, and a faithful PRD-only implementer would let the removal succeed, not reject it. The asserted outcome contradicts the PRD, so no test was emitted (gap left as a gap, per the design-index-only contract).

No implementation code exists yet, so tests were validated by import/collection only (they assume a running server at `API_BASE_URL`, per the runner contract).

## Step 6: Generate Implementation — 2026-07-09T00:00:00.000Z

The implementation is complete and verified end-to-end.

## Summary

Generated a complete Python + Flask implementation of the Distillery & Spirits Production (DSP/TTB) API in `workspace/implementation/`.

### Files
- `app.py` (single-module server, ~1000 lines) — all routes, business logic, calculations, cascades, RBAC, and in-memory store
- `requirements.txt` — `Flask==3.0.3`
- `start.sh` — foreground launcher

### How start.sh works
Reads `$PORT` (default 10000), binds `0.0.0.0`. Guards the pip install with `if ! python3 -c "import flask"` so per-test reboots don't re-run install (avoids concurrent-reboot contention), then `exec python3 app.py`. The store is reset to empty on every process boot via module-level globals — no seeding, no disk persistence.

### Endpoints (all 52 from the table)
Full CRUD + state-transition coverage for Distillery, MashBatch, DistillationRun, Barrel, LabelApplication, BottlingRun, TaxRemoval, ExciseReport, Customer, SalesOrder, TourBooking, plus the two test-driving endpoints (`/dsp/_clock/set_current_utc`, `/dsp/_ledger/set_cbma_ytd`).

### Key design decisions (all read from PRD/scaffold, nothing hardcoded)
- **Response envelope**: `meta`/`response_type`/`data`; error body `error_id`/`message`; pagination `limit`/`offset`/`total_count`/`has_more` in `meta`.
- **Auth**: `X-User-Role` (401 if missing/unrecognized) + `X-User-ID`; operator roles opaque, `Customer` entity-backed with ownership checks (403). Fixed guard order: auth → role → existence(404, left-to-right FK) → ownership → validation(422) → state(409) → business rules.
- **Logical clock**: default `2026-05-01T00:00:00Z`, never wall-clock; drives `created_at`/`fill_date`/`removal_date`/aging/CBMA buckets. Timestamps ISO-8601 UTC with 3 fractional digits.
- **Money/PG precision**: `Decimal` with `ROUND_HALF_UP` throughout; proof gallons to 0.1, excise to whole cents. Implemented both gauge variants (VOLUME direct, WEIGHT ÷7.28), sum-then-round bottling PG, pro-rated removal PG, and CBMA reduced/standard tier split.
- **Cascades**: verified 4-hop production cascade (bottling COMPLETE → barrel EMPTIED → run CLOSED → mash ARCHIVED) and cascade B (SOLD_OUT removal auto-cancels PENDING orders), each mutated entity independently bumping its own `updated_at`/`version`.
- **Dual-axis SalesOrder** (payment × fulfillment) and **OCC** on excise filing (`expected_distillery_version` vs `Distillery.version`, 412 `ERR_STALE_VERSION`). Distillery `version` bumps only when its fields actually change (e.g., non-TAXPAID removals don't bump it).
- Conservation invariant maintained by construction across all ledger events.
- List ordering by `(created_at, insertion-seq)` for stable ordering under the fixed clock.

### Verification
Ran full end-to-end drivers covering: gauge (VOLUME=100.0 PG, WEIGHT=100.0 PG, WEIGHT-with-0→422), ledger accounts, angel's share (12mo→5.0/95.0), bottling completion (21.4 bottled / 73.6 loss), the production cascade, TAXPAID excise (10.7 PG → 2889¢), cascade B, three-tier ship gating, tour overlap/capacity errors, Customer ownership 403/200, pagination meta, and OCC stale-version 412. All matched expected values.

Note: several unrelated stray servers from other tasks were occupying low ports during testing; I confirmed correct behavior by binding a verified-free port. My test server has been shut down and its port freed.

## Step 7: Run Tests and Iterate — 2026-07-08T22:15:55.000Z

All 8 parallel rounds passed cleanly (57/57, zero failures, zero errors in every round). The task is already in a passing, stable state — no diagnostic protocol steps were triggered.

## Summary

- **Iterations run:** 1 (the initial 8-round parallel stability sweep passed clean, so no further iterations were needed).
- **Tests deleted:** None. No test failed in any of the 8 rounds, so no PRD-silence / unique-derivability deletions were warranted.
- **Fixes applied to `test_helpers/`:** None.
- **Fixes applied to `implementation/`:** None.

Result: all 8 concurrent rounds reported `passed == total == 57` with 0 failed and 0 errors, confirming a stable (non-flaky) pass. Verified via `workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — SKIPPED — 2026-07-08T22:15:55.000Z

Skipped per the skill's skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at the Step 7 sites, so no `PRD_FINALIZED.md` was produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-07-08T22:15:55.000Z

Done. All edits are in-paragraph inserts/revisions; no new sections or paragraphs added.

## Summary

- Source `PRD.md`: 265 lines / 40,265 chars. `PRD_COMPLETED.md`: 265 lines / 41,311 chars. Char delta: **+1,046**.
- Counts: **9 ambiguity-pins**, **1 mismatch-revision**.

### Changes
- **2.1 (RBAC)** — insert — ambiguity — Customer list operations are auto-narrowed to own rows (rather than 403'd) since a list has no single target row — `app.py:1366-1367, 1501-1502`.
- **2.2 (Response Structure)** — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall-clock — `app.py:189, 108-109`.
- **2.3 (Pagination)** — insert — ambiguity — rows sharing a `created_at` are tie-broken by insertion sequence (`_seq`) — `app.py:394`.
- **2.6 (CBMA Ledger)** — revise — ambiguity — `set_cbma_ytd` requires a non-negative value and rounds it to the nearest tenth (round-half-up) — `app.py:563-564`.
- **3.4 (COLA Lifecycle)** — revise — ambiguity — `correction_notes` on a `RETURN` decision is optional; when omitted it is left unset — `app.py:927-932`.
- **3.5 (Bottling Runs)** — insert — ambiguity — `scheduled_end` must be strictly after `scheduled_start`, else `ERR_VALIDATION` — `app.py:970-971`.
- **3.6 (Tax Removal)** — revise — ambiguity — a run that is not `COMPLETED` is rejected with `ERR_INVALID_STATE` (error id was unnamed for this precondition) — `app.py:1132-1133`.
- **3.8 (Sales Order)** — revise — mismatch — `unit_price_cents` is a non-negative integer with zero accepted (the general "positive quantities" rule would imply rejection) — `app.py:1333`.
- **3.9 (Tour Bookings)** — insert — ambiguity — `end_time` must be strictly after `start_time`, else `ERR_VALIDATION` — `app.py:1470-1471`.
- **3.9 (Tour Bookings)** — revise — ambiguity — "within 30 minutes" is strictly less than 30 minutes; starts exactly 30 minutes apart do not conflict — `app.py:1527`.

### Notes on behaviors deliberately left unchanged
- `state_code`/`dsp_permit_number` are validated only as non-empty strings (no two-letter length check); I treated "two-letter" as domain description, not a validation contract, and left it — flag if you'd prefer it pinned.
- `ttb_id` is server-minted with an opaque `TTB-<hex>` format; PRD already says the server "assigns" it, so no format pin was added.
- Barrel fill does not guard `fill_proof_gallons` against the run's `remaining_proof_gallons`; PRD claims no such guard, so this absence is not a mismatch.
