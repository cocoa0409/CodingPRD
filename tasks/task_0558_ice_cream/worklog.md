# Worklog — task_0558_ice_cream

## Step 1: Create task directory — 2026-07-08T00:00:00.000Z

Created `tasks/task_0558_ice_cream/` and `tasks/task_0558_ice_cream/workspace/` (index pre-assigned, no tasks/ scan performed).

## Step 2: Generate scaffold (Expert) — 2026-07-08T00:00:00.000Z

All checks pass. The three scaffold artifacts are complete and self-consistent.

Generated an **Expert**-difficulty PRD-benchmark scaffold for the Ice Cream / Frozen Dessert Shop scenario (task 0558):
- **SCAFFOLD.yaml** (§1.0–§1.7): 13 entities, 47 endpoints, 33 error codes, 12 validation priorities, 6 state machines, 9 calculations, 1 OCC concurrency rule, 4 RBAC roles.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): 18 instances = all 9 difficulty rules × 2.
- **SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): 49 breadth instances + 6 `excluded_because` stubs.

Design choices: primary archetype *Quota/allocation* (finite batch volume reserved/committed/wasted via FIFO-by-expiry) + secondary *Ledger reconciliation* (daily cash drawer + standard-vs-actual COGS); flat topology; branching+cyclic state machines; peer roles; layers = cascading side effects, dual-variant calc, rate/threshold triggers, optimistic concurrency.

Verification: `scaffold_lint.py` reports `VERDICT: clean lint` (359 calls, all §1.8/§1.9 calls conform to §1.5, all FKs reverse-reachable). All 73 instance names unique; every `grounds` reference resolves; numeric asserts computed round-half-up. Note: 47 endpoints sits above the Expert 20–32 guideline — deliberate to represent all 8 named sub-domains; difficulty carried by coupling, not surface size.

## Step 3: Copy shared files — 2026-07-08T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-08T00:00:00.000Z

All three Hard Contracts pass. PRD complete at `workspace/PRD.md`.

Field coverage: 93 required, 93 present, 0 missing — PASS.
Rule coverage: 12 validations, 1 OCC rule, 16 SM transitions, 9 calculations, all expressed — PASS.
Path purity (§3 only): 375 backtick tokens scanned, 0 path/method tokens — PASS.

Key flags:
- Scaffold references `DEPOSIT_PCT` and `STATION_CLEAN_BUFFER_MIN` without numeric values. PRD fixed them at **DEPOSIT_PCT = 0.20 (20%)** and **STATION_CLEAN_BUFFER_MIN = 30 minutes**. These are the only two places the PRD could diverge from withheld difficulty/corner design worked-example values.
- Structure: 10 §2 subsections + 8 §3 lifecycle subsections; §4 4-column table; §5 2-column table.

## Step 5: Generate unit tests — 2026-07-08T00:00:00.000Z

86 test functions, each carrying exactly one `Design:` tag (86 tags = 86 tests → no dual-tags, no untagged tests). Everything compiles.

Stage 1 — `test_helpers/` (9 files): types.py (WasteEvent omits updated_at/version, append-only), api_client.py (46 endpoint methods), api_errors.py (32 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (four opaque roles → shared-constant headers; PRD 2.1 says X-User-ID never resolved to an entity), fixtures.py (composite flavor→batch→drawer→order→line + pre-order/catering builders), __init__.py.

Stage 2 — `test_suite/` (conftest + 11 test files, 86 tests):
- Difficulty queue (A): all 18 instances, ≥2 tests each (boundary/buffered-overlap got 3 for X-1/X/X+1).
- Corner queue (B): every non-stub instance ≥1 test.

Deliberate skips (gaps left as gaps, PRD-first filter):
- 6 `excluded_because` stubs — not translated.
- `list_batches_by_flavor_reverse_reachability` and `list_orderlines_by_order_reverse_reachability` — skipped: PRD never names flavor_id/order_id query-param semantics (C1/C2 fail).
- `safety_beats_constraint_on_line_add` — strict allergen-beats-headroom precedence NOT uniquely derivable (PRD 2.8 places both in single step 6 without order); translated as two isolated single-failure allergen tests instead. State-beats-temporal instance kept its precedence assertion (PRD 2.8 pins step 5 before 6).

## Step 6: Generate implementation — 2026-07-08T00:00:00.000Z

FIRST ATTEMPT FAILED (API ConnectionRefused, 0 files written). Retry succeeded.

Built complete Python + Flask impl at `workspace/implementation/`: app.py (~50 endpoints, in-memory dicts, business logic, state machines, calcs), errors.py (ApiError with error_id + HTTP status), requirements.txt (Flask==3.0.3), start.sh (reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py foreground, guarded pip install).

Storage in-memory only, no seeding, wipes on reboot. Key fidelity: response envelope meta/response_type/data with req_ ids + 3-digit ISO timestamps; pagination (default 10, clamp 1–100); RBAC (Manager/ShiftLead/Scooper/Baker) precedence auth→forbidden→existence→schema→state→business; logical clock via /_clock/set_current_utc; Decimal ROUND_HALF_UP money (per-line-tax-round-then-sum, dual COGS, deposit 20%, shrink allowance 5%, catering 2¢/ml); FIFO batch allocation (expiry asc), reservation/commit/waste accounting, stock_status >= par = IN_STOCK, 3-hop cascades AVAILABLE⇄DEPLETED; loyalty punch reset + refund reversal invariant; PreOrder OCC re-quote (ERR_STALE_VERSION 412); station 30-min buffer overlap; catering half-open cart overlap (touching allowed); drawer reconciliation BALANCED/OVER/SHORT; per-request single version bump.

Two low-confidence gap decisions (no dedicated error code): duplicate uniqueness + cart overflow both → ERR_VALIDATION (422).

## Step 7: Test and iterate to pass — 2026-07-08T00:00:00.000Z

All 8 rounds pass 86/86. Clean sweep.

**Iterations run:** 2 (baseline sweep + one fix + confirmation sweep).

**Failing test (union across all 8 baseline rounds):** `test_preorder_deposit_computed_on_confirm` — failed identically in every round (`assert 800 == 2000`), deterministic wrong assertion (not flaky).

**Diagnosis:**
- STEP 1a COVERAGE — PASS. PRD 3.6 verbatim: *"`deposit_cents` is set to `quoted_price_cents` multiplied by the deposit fraction of 0.20 (twenty percent), rounded half up to whole cents."*
- STEP 1b UNIQUE DERIVABILITY — PASS. The 0.20 fraction and round-half-up are stated constants.
- STEP 2 CONSISTENCY — TEST BUG. Test seeds `quoted_price_cents=4000`; PRD-correct deposit = 4000 × 0.20 = 800, but assertion demanded 2000. Implementation returned 800 (PRD-faithful); assertion contradicted its own cited sentence.

**Tests deleted:** none.
**Fixes to test_helpers/:** none.
**Fixes to test_suite/:** `test_01_catalog_crud.py::test_preorder_deposit_computed_on_confirm` — corrected deposit assertion `== 2000` → `== 800` to match PRD 3.6 `quoted_price_cents × 0.20` on the test's own `quoted_price_cents=4000` input. More faithful, no weakening (still exact-value check).
**Fixes to implementation/:** none — implementation already PRD-correct.

Final state: 8/8 rounds green, 86/86 passing each round.

## Step 8: Finalize PRD — 2026-07-08T00:00:00.000Z

PRD.md vs PRD_FINALIZED.md: 289 vs 289 lines — 0% delta (verbatim copy).

The sole Step 7 diff item was a test_suite assertion fix (deposit == 2000 → == 800), a pure test-fixture bug. Implementation was already PRD-faithful. Pre-edit search confirmed PRD 3.6 verbatim-covers and uniquely-derives `deposit_cents = quoted_price_cents × 0.20` round-half-up; verified impl paths app.py:1658 (confirm), :28 (DEPOSIT_PCT=0.20), :98 (rhu), :1607 (init 0), :1716 (cancel-refund), :636 (serializer) all consistent. No edits warranted → PRD_FINALIZED.md = verbatim copy of PRD.md.

## Step 9: Complete PRD — 2026-07-08T00:00:00.000Z

Source PRD_FINALIZED.md (289 lines, 42,010 chars) → PRD_COMPLETED.md (289 lines, 45,059 chars). Char delta +3,049. All in-paragraph inserts/revisions; no new sections.

Counts: ambiguity-pins = 10, mismatch-revisions = 3.

Changes:
- §3.1 Flavor — revise/mismatch — inactive flavor blocks only cake production, not POS lines (app.py:1665-1677 / 1219-1327).
- §3.4 Order totals — revise/mismatch — totals aggregate ACTIVE or COMMITTED lines; punches_earned same set (app.py:667-682).
- §3.5 Refund loyalty — revise/mismatch — decrement lifetime_scoops (floor 0), recompute credits=lifetime//10, punches=lifetime%10 (app.py:1514-1520).
- §2.3 Pagination — insert/ambiguity — clamp limit→[1,100], neg offset→0; non-integer → ERR_VALIDATION (app.py:295-318).
- §3.2 Waste — insert/ambiguity — MELT/SPILLAGE/TRIM_SHRINK zeroing AVAILABLE batch auto→DEPLETED (PREP untouched); EXPIRED_DISCARD mismatch → ERR_VALIDATION (app.py:1041-1044,1023-1027).
- §3.3 Order open — insert/ambiguity — creation validates drawer/loyalty existence only; drawer OPEN enforced at payment (app.py:1163-1198).
- §3.3 Allergen label — insert/ambiguity — line allergen_label deduplicated, sorted ascending (app.py:1273).
- §3.3 Line removal — insert/ambiguity — requires ACTIVE line on OPEN order; not-open→ERR_ORDER_NOT_OPEN, resolved→ERR_ORDER_LINE_NOT_FOUND (app.py:1337-1340).
- §3.4 Card payment — insert/ambiguity — CARD payment leaves tendered_cash_cents/change_cents null (app.py:1435-1436).
- §3.6 Requote — insert/ambiguity — non-QUOTED pre-order → ERR_PREORDER_INVALID_STATE, before version check (app.py:1642-1645).
- §3.7 Booking create — insert/ambiguity — requested_items non-empty, volume_ml>0, capacity/overlap before reserving (app.py:1770-1793).
- §3.7 Booking close — insert/ambiguity — actual volume_ml may be 0; unrequested/over-reserved → ERR_VALIDATION; actual<reserved commits FIFO, releases all reservations (app.py:1877-1905).
- §3.8 Drawer open — insert/ambiguity — counted_cash_cents/variance_cents null until close (app.py:1114-1115).

## Pipeline complete — 2026-07-08T00:00:00.000Z

All 9 steps done. Final: 86/86 tests passing across 8/8 stability rounds. Outputs: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (86 tests), workspace/implementation/ (Flask, in-memory).
