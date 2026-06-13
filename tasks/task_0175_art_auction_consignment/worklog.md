# Worklog — task_0175_art_auction_consignment

## Step 1: Create task directory — 2026-06-05T00:00:00.000Z

Created `tasks/task_0175_art_auction_consignment/` and `tasks/task_0175_art_auction_consignment/workspace/`.

## Step 2: Generate scaffold artifacts — 2026-06-05

Wrote SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8), and
SCAFFOLD_CORNER_DESIGN.yaml (§1.9) for the Art Auction House & Consignment
scenario at Expert difficulty (pricing-engine + ledger-reconciliation
archetypes; flat topology; parallel Lot state dimensions).

Profile: 12 entities, 7 state-machine blocks across 6 entities, 5 calculations,
15 validations, 52 endpoints, 18 errors, 6 roles, 2 concurrency rules.
Difficulty design: 18 instances (9 §0.5 rules × 2). Corner design: 41 instances
(35 active + 6 excluded_because stubs).

`scaffold_lint.py` → VERDICT: clean lint. Self-checks pass: all grounds resolve,
all ${var} placeholders bound, no name collisions, every error referenced, enum
closure holds, no forbidden concurrency vocabulary.

## Step 3: Copy shared files — 2026-06-05

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-05

Generated `workspace/PRD.md` for the Art Auction Consignment API (Expert-band: pricing engine + ledger reconciliation, parallel lot lifecycles, cascading side effects, OCC).

Structure: 5 top-level sections (Introduction; Global Specifications; Business Logic & Workflows; Endpoint Definitions; Error Code Catalogue), 18 `###` subsections (9 in §2, 9 in §3). ~289 lines.

Hard Contracts all PASS:
- Contract 1 (Field-Name Coverage): 59 required scaffold field names + request/query/path params, 0 missing.
- Contract 2 (Rule Coverage): all 18 error IDs, all 32 state enum values, both OCC rules (knock-down + invoice) with expected_lot_version + ERR_STALE_VERSION 412, 14-level validation priority ordering, both knock-down fork branches (SOLD/BOUGHT_IN), depth-3 disburse cascade + reverse-sale compensation, all 5 calculations with sum-exact-then-round-once pinning and all band/increment/floor/cap constants in cents + dollars.
- Contract 3 (§3 Path Purity): 422 §3 backtick tokens, 0 slash-prefixed, 0 bare HTTP methods, 0 method+path combos.

Did NOT read either withheld design file.

## Step 5: Generate unit tests — 2026-06-06

Test files: 9 (8 `test_*.py` + `conftest.py`) under `test_suite/`. Total tests: 71 functions, each carrying exactly one `Design:` tag traceable to its source instance.

Queue split:
- Queue A (Difficulty): 36 tests — all 18 difficulty instances (9 rules × 2) covered by 2 tests each.
- Queue B (Corner): 35 tests — all 35 non-stub corner instances covered by ≥1 test each.

Instances skipped: 6 — all `excluded_because:` stubs (cross-reference owning difficulty instances, all verified to resolve). No non-stub instances filtered out — every design-index claim covered verbatim by PRD and uniquely derivable.

test_helpers produced (9 files): `__init__.py`, `types.py`, `api_client.py` (one method per §4 endpoint), `api_errors.py` (18-error catalog), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (6 roles incl. per-instance builders for the two entity-backed roles), `fixtures.py` (composite chains: base scene → open lot → SOLD/CLOSED → INVOICED → PAID → STATEMENTED → SETTLED, live version-threading on every OCC-guarded write).

Validation: all 18 files compile; all imports + api calls resolve via AST check; all PRD citations verbatim; all calc literals (premium 325k/1,180k/25,523; royalty cap 1,250k; net 1,075k/1,062,500; min_next_bid 110k) re-derived from PRD; no scaffold refs, no skip/xfail.

## Step 6: Generate implementation — 2026-06-06

Generated Python + Flask implementation at `workspace/implementation/` (18 source files).

Files: `start.sh` (reads `$PORT` default 10000, binds `0.0.0.0`, `exec python3 app.py` foreground, guards pip install on `import flask`), `requirements.txt` (Flask==3.0.3), `app.py`, `db.py` (in-memory dicts keyed by id, coarse RLock), `errors.py` (18 IDs + ApiError), `response.py` (envelope meta/response_type/data, req_ ids, ISO-8601 UTC 3 fractional digits), `middleware.py` (X-User-ID/X-User-Role auth), `routes/` (premium_schedules, sellers, bidders, consignments, auction_sales+nested lot cataloging, lots, bids, paddle_registrations, settlement), `services/` (calculations Decimal/ROUND_HALF_UP marginal-tier premium + droit-de-suite royalty floor/cap + commission + banded min-next-bid; domain lot_count/outstanding-balance recompute + standing-high created_at tiebreak; common serialization/pagination/OCC split).

Endpoints: 52 implemented — exact 1:1 with PRD §4 (26 GET, 25 POST, 1 PATCH).

Self-verified: full lifecycle, calc worked examples (premium 156,000; royalty 24,000 cap-bound at 1,250,000; commission 60,000; net 516,000) + sum-exact-then-round-once rounding order; two parallel Lot dimensions (sale_status × settlement_status); cascades bump version/updated_at (open-bidding, terminate, disburse depth-3, reverse-sale); OCC split into validate_occ_field (priority-6 ERR_INVALID_REQUEST) before state + match_occ (priority-9 ERR_STALE_VERSION) after state/dependency. Store boots empty (no seeding). start.sh confirmed: reads $PORT, binds 0.0.0.0, foreground.

## Step 7: Run tests and iterate — 2026-06-06

Iterations run: 2 (baseline sweep + 1 fix + confirming sweep). Final state: clean 8-round parallel sweep, 71/71 passing in every round.

Baseline: all 8 rounds deterministically identical — 70/71 passing, exactly one consistent failure: `test_stale_version_on_second_invoice_rejected` (expected `ERR_STALE_VERSION`, got `ERR_INVALID_STATE`). No flakiness; single deterministic bug.

Tests deleted: None.

Fixes applied to `test_helpers/`: None.

Fixes applied to `test_suite/`:
- `test_06_uniqueness_and_concurrency.py`, `test_stale_version_on_second_invoice_rejected` — relaxed exact-error assertion from `validate_error(resp, ERR_STALE_VERSION)` to `validate_error_is_one_of(resp, [ERR_STALE_VERSION, ERR_INVALID_STATE])`. ERROR PRECEDENCE SILENCE collapse pattern (STEP 1b). Second invoice on a lot whose first invoice already advanced settlement_status NONE→INVOICED (PRD §3 line 176) AND bumped version, tripping two checks. PRD §2.8 line 112 narrates this scenario yielding ERR_STALE_VERSION (supports "A is possible"), but PRD §2.9 line 118 ranks single-entity state precondition (ERR_INVALID_STATE) strictly ahead of OCC version match. A PRD-faithful implementer following §2.9 returns ERR_INVALID_STATE, so PRD does not uniquely determine which error surfaces. Per cardinal-rule exception, relaxed to validate_error_is_one_of (not deletion).

Fixes applied to `implementation/`: None — implementation already correctly follows PRD §2.9's stated precedence.

## Step 8: Finalize PRD — 2026-06-06

Produced `workspace/PRD_FINALIZED.md`. PRD.md = 288 lines; PRD_FINALIZED.md = 288 lines (1 line revised in place, 0% line-count change).

Changes (one bullet):
- §2.8 (Optimistic Concurrency Control) — revise — Rewrote the invoice OCC paragraph's misleading example. Original attributed the second-invoice "settlement dimension already advanced" scenario to ERR_STALE_VERSION, but impl returns ERR_INVALID_STATE because §2.9 precedence checks the single-entity SOLD/NONE precondition before the OCC version match. New wording pins: OCC fires only after the SOLD/NONE precondition and the sale-CLOSED dependency both pass; a second invoice on an already-advanced lot yields ERR_INVALID_STATE; ERR_STALE_VERSION surfaces only when those preconditions hold but the version is stale (e.g. a concurrent bump leaving the lot SOLD/NONE, such as after a reverse-sale re-opens the window). Impl: `routes/settlement.py:45-52`.

Pre-edit search log: subject = error surfacing on POST /lots/{id}/invoice with stale expected_lot_version. Enumerated routes/settlement.py issue_invoice (order: validate_occ_field → SOLD/NONE → sale CLOSED → match_occ), services/common.py match_occ + validate_occ_field, routes/lots.py reverse_sale (resets settlement NONE while leaving sale_status SOLD → OCC genuinely can re-fire), all match_occ/ERR_INVALID_STATE/ERR_STALE_VERSION callsites across every route (uniform state-before-OCC), §3.6 line 176. Wording kept the ERR_STALE_VERSION path alive and broadly phrased to avoid over-narrowing.

## Step 9: Complete PRD — 2026-06-06

Produced `workspace/PRD_COMPLETED.md` (minimal patch over PRD_FINALIZED.md). Source PRD_FINALIZED.md: 288 lines, 46,942 chars; PRD_COMPLETED.md: 288 lines, 48,727 chars (char-delta +1,785; line count unchanged — all edits in-paragraph).

Counts: ambiguity-pins 3, mismatch-revisions 1 (4 total changes).

Per-change:
- §2.1 RBAC — insert — ambiguity — PRD pinned only single-resource ERR_NOT_RESOURCE_OWNER; pinned that list/collection endpoints silently scope results to owned rows for entity-backed Seller/Bidder roles (empty array, never an ownership error) — routes/consignments.py:83-84, routes/lots.py:57-60, routes/bids.py:144-147,164-167, routes/settlement.py:167-168, routes/auction_sales.py:219-221.
- §3.1 Intake — insert — ambiguity — pinned country_code/email/legal_name/payout_iban validated only for presence and non-emptiness (no ISO/length checks) despite descriptive "ISO 3166-1 alpha-2" framing — routes/sellers.py:22-25, services/common.py:67-72.
- §3.3 Auction Sales — insert — ambiguity — pinned title/sale_date_utc/currency presence/non-empty only, no ISO-8601 date parse, no ISO 4217 currency check despite descriptive ISO framing — routes/auction_sales.py:31-34.
- §3.9 Reversal — revise — mismatch — PRD implied a SOLD/state precondition firing first; revised to match impl which has no sale_status/settlement_status precondition (never ERR_INVALID_STATE) and matches expected_lot_version (→ ERR_STALE_VERSION) before the already-paid-statement guard and before compensation — routes/lots.py:167-175.

No new sections; no behavior absent from implementation/ introduced.

## Pipeline complete — 2026-06-06

All 9 steps finished. Final state: 71/71 tests pass across an 8-round parallel stability sweep. Artifacts: SCAFFOLD.yaml + 2 design indices, workspace/{PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md}, test_helpers/ (9 files), test_suite/ (9 files, 71 tests), workspace/implementation/ (18 source files, 52 endpoints, in-memory Flask).
