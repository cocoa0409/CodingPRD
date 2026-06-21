# Worklog — task_0321_window_cleaning_pressure_washing

## Step 1: Create task directory — 2026-06-13T03:49:29.000Z

Created `tasks/task_0321_window_cleaning_pressure_washing/` and `tasks/task_0321_window_cleaning_pressure_washing/workspace/`. Difficulty: Expert (to be passed to Step 2 scaffold-generator).

## Step 2: Generate scaffold (Expert) — 2026-06-13T04:15:07.000Z

Generated a complete Expert-tier scaffold at `tasks/task_0321_window_cleaning_pressure_washing/`. All three artifacts written and pass `scaffold_lint.py` with `VERDICT: clean lint`.

**Files (all three written, top-level keys correctly isolated):**
- `SCAFFOLD.yaml` (§1.0–§1.7) — 1803 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 1253 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 1682 lines

**Scaffold metrics (Expert tier):**
- **14 entities**: Account, Property, Quote, ServiceAgreement, Crew, Route, Visit, VisitAddOn, VisitPhoto, ReCleanRequest, Invoice, Deposit, WeatherAdvisory, LedgerEntry
- **7 state machines**: Quote (branching), ServiceAgreement (cyclic ACTIVE↔PAUSED), Route (linear), Visit (**parallel** schedule_status × billing_status, plus weather-reschedule self-loop), ReCleanRequest (branching), Crew (cyclic toggle), Deposit
- **5 calculations**: quote_amount (dual-variant pane vs sqft + tiered/rounding combinatorics), deposit_requirement (threshold), visit_charge (dual-variant estimate vs actual), invoice_settlement (waterfall), reclean_credit (threshold on photo-doc density)
- **24 validations** (priority-ordered), **25 errors**, **60 endpoints** (incl. one `/_clock` test-driving endpoint), **4 roles** (Customer entity-backed; Dispatcher/FieldCrew/Billing opaque — peer-role model)
- **1 concurrency rule**: OCC on `Route.version` for visit commit (412 stale-version)

**Design coverage:** §1.8 has 18 difficulty instances (2 per rule × 9 rules); §1.9 has 33 active corner instances + 1 `excluded_because` stub. All grounds resolve, all 52 instance names unique, all formula-derived asserts computed as literals and verified by code.

**Notable Expert-tier decisions:** flat topology (`api_prefix: ""`); parallel Visit state dimensions (schedule × billing); two temporal-overlap semantics (half-open route minute windows vs whole-calendar-day crew exclusivity); two conserved quantities (account cents, route booked-minutes); fixed two self-consistency traps (reclean_credit reachability, weather-reschedule new_planned_date input).

**Constraint honored:** no sibling `task_*/` directory was read.

## Step 3: Copy INSTRUCTION.md — 2026-06-13T04:15:07.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0321_window_cleaning_pressure_washing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T04:20:21.000Z

Generated `workspace/PRD.md` (311 lines, 5 top-level sections, 19 subsections). Did not open either withheld design file.

**Structure:** §2 cross-cutting subsections (ledger/balances, route capacity & crew exclusivity, OCC on route commit, quote expiry by logical clock, monetary precision, nested retrieval & referential integrity); §3 organized by business lifecycle (accounts/quoting, agreement conversion, deposits/crews, routing & commit, visit execution, weather/cancellation, billing, re-cleans, validation ordering §3.9).

**Hard Contracts — all PASS:** field coverage 66/66; rule coverage (24 validations, 1 OCC, 7 state machines, 5 calculations all with embedded constants, sibling-branch symmetry) 0 missing; path-purity (§3, 422 backtick tokens, 0 path/method leaks). §2.2 byte-for-byte match; §2.3 pagination defaults; 4 roles spelled exactly with identities translated (Customer→Account entity-backed; Dispatcher/FieldCrew/Billing opaque).

## Step 5: Generate unit tests — 2026-06-13T04:37:10.000Z

Generated test infrastructure in `test_helpers/` (9 files) and test cases in `test_suite/` (conftest + 7 files, **69 test functions**, 69 Design tags — every test tagged exactly once).

**test_helpers/ (Stage 1) — 9 files:** types.py (entity TypedDicts; VisitPhoto & LedgerEntry append-only: id+created_at only), api_client.py (one method per PRD §4 endpoint), api_errors.py (ApiErrorId enum + HTTP-status map), assertions.py, factories.py (input-field-only payloads, auto-unique contact_email), constants.py (pricing/threshold constants), test_users.py (opaque Dispatcher/FieldCrew/Billing headers + make_customer_headers(account_id) for entity-backed Customer), fixtures.py (composite chains quote→agreement→activate→scheduled→dispatched→in_progress→completed→invoiced, setup_visit_rescheduled_twice, setup_requested_reclean), __init__.py.

**Coverage:** Queue A (Difficulty): all **18** instances translated, each ≥2 tests, no skips (all PRD-covered & uniquely derivable). Queue B (Corner): all **33 non-stub** instances translated (≥1 test each); **1 skipped** — the `consistency_model / invoice_response_reflects_settlement_in_same_request` stub (carries `excluded_because`, no test_recipe; its difficulty cross-ref resolves correctly so intentionally not translated).

**Audits passed:** every difficulty instance ≥2 tests; every non-stub corner instance ≥1 test; no dangling/missing tags; all multi-word PRD citations verified verbatim; no skip/skipif/xfail; no scaffold/section-reference leakage; all imports resolve; all files compile. No gaps required skipping for PRD-coverage reasons.

## Step 6: Generate implementation — 2026-06-13T04:37:10.000Z

Generated complete Python + Flask implementation at `workspace/implementation/`. **60 endpoints** (matches scaffold §1.5 table, incl. `/_clock/set_current_utc`).

**Files:** start.sh, requirements.txt (Flask==3.0.3), app.py, db.py (14 empty dicts keyed by UUID), clock.py (ISO-8601 UTC + logical clock), errors.py (24-entry error→HTTP-status catalogue), response.py, auth.py (X-User-ID/X-User-Role + RBAC Customer/Dispatcher/FieldCrew/Billing), helpers.py (parsing/validation, pagination, ledger posting, derived-balance + route-minutes recompute, quote lazy-expiry), calc.py (Decimal/round-half-up for all 5 calculations), serialize.py, visit_ops.py, and six route blueprints (accounts/quotes/agreements/fleet/visits/billing).

**start.sh:** reads $PORT (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`, pip install guarded behind `import flask` check. Verified live (HTTP 201 within ~3s).

**Storage:** in-memory only (plain dicts), no SQLite/JSON/tmp, no entity seeding at startup (every store dict initializes empty per boot). Self-verified ~70 assertions covering pricing engine, deposits, charges, waterfall, reclean credit, parallel dimensions, state machines, OCC, overlap semantics, capacity/skill/region/date guards, cascades, recurrence, lazy expiry, auth/RBAC — all passed.

## Step 7: Test and iterate to PASS — 2026-06-13T04:42:58.000Z

**Iterations run:** 2 sweeps (initial baseline + 1 verification after fixes). Final state: 8/8 parallel rounds green, 69/69 tests passing each round, zero flakiness.

**Baseline:** 5 tests failed identically in all 8 rounds — not flaky, but two distinct deterministic test-code bugs.

**Tests deleted:** None. Every failing test traces verbatim to PRD prose and uniquely determines its assertion; all failures were test-side bugs, not PRD-silence or non-derivability.

**Fixes applied to test_suite/ (test-code bugs, STEP 2 — the test setup was inconsistent with PRD, and the PRD-faithful implementation was correctly rejecting it):**

1. `test_suite/test_03_cascades_and_invariants.py` — added the missing local `_list(res)` helper (`return body["data"], body["meta"]`). `test_complete_recurring_visit_next_visit_starts_unscheduled` called `_list(...)` at line 106 but the helper was never defined or imported in this file (it exists in test_01 and test_02), producing `NameError: name '_list' is not defined`. Pure Python bug; the assertions themselves (next visit `UNSCHEDULED`, `planned_date` = first date + interval) trace to PRD §3.5.

2. `test_suite/test_04_scheduling_constraints.py` — inserted the missing `accept_quote` call before `create_service_agreement` in 4 window-overlap tests (`test_overlapping_visit_window_rejected`, `test_overlapping_window_does_not_change_route_booked_minutes`, `test_abutting_visit_windows_commit_successfully`, `test_abutting_visit_commits_when_endpoints_touch`). Each built its second visit via `create_sent_quote` (DRAFT→SENT only) and then tried to convert a SENT quote directly. PRD §3.2 states "An `ACCEPTED` quote is the gateway... Converting it creates a `ServiceAgreement`," so the implementation correctly rejected the SENT-quote conversion with `ERR_INVALID_STATE`. The two priority-conflict tests in the same file already performed the accept step; these 4 simply omitted it.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None — the implementation was already PRD-faithful; both bugs were in the test suite.

## Step 8: Finalize PRD — 2026-06-13T04:45:18.000Z

**Outcome: No PRD edits warranted. `PRD_FINALIZED.md` equals `PRD.md` verbatim** (identical MD5 `3c91239ace1209627f12c2e119570504`, 311 lines each, 0% delta).

Both Step 7 diff items were pure test-code bugs (a missing Python `_list` helper and missing `accept_quote` calls), not PRD-silence or PRD/impl mismatch. The implementation is already PRD-faithful at both sites, and PRD prose already uniquely determines the behavior the restored assertions check.

**Per-fix-site verification:**
- Fix 1 (test_03 missing `_list`, PRD §3.5 recurrence next-visit): impl `routes_visits.py:113-159` (complete_visit recurrence branch) + `visit_ops.py:20-39` (generate_visit hard-sets schedule_status=UNSCHEDULED, consistent across all 3 callsites: agreement activation, recurrence, re-clean remedy). Restored assertions (next visit UNSCHEDULED; planned_date = completed date + interval 14 → 2026-07-15; visits_generated_count increment) match impl and trace verbatim to PRD §3.5. The Step 7 failure was a NameError — pure Python bug.
- Fix 2 (test_04 missing `accept_quote`, PRD §3.2 ACCEPTED gateway): impl `routes_agreements.py:33-71` (convert_quote) raises ERR_INVALID_STATE for any non-ACCEPTED status (SENT included). The 4 fixed tests built SENT quotes and tried to convert directly; impl correctly rejected. Pure test-fixture bug.

No new mismatch introduced.

## Step 9: Complete PRD — 2026-06-13T04:49:13.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation/ scan. Source `PRD_FINALIZED.md`: 311 lines, 48,163 chars → `PRD_COMPLETED.md`: 311 lines, 48,442 chars (**+279 chars**, no line-count change — all edits in-paragraph).

**Change counts:** ambiguity-pins: 2, mismatch-revisions: 1.

**Per-change log:**
- §2.4 (Common Resource Properties) — insert — ambiguity — pinned `version` initial value as `1` — `db.py:55`; cross-checked by `test_07:32`.
- §2.4 (Common Resource Properties) — revise — mismatch — PRD claimed a derived-field recompute *always* bumps `updated_at`/`version`; impl only touches the owning record when the recomputed value actually differs. Revised to make the bump conditional on a value change — `helpers.py:167-170` (recompute_account), `helpers.py:187-189` (recompute_route_minutes), both gated by `if stored != recomputed`.
- §3.1 (Accounts/Quoting Engine) — insert — ambiguity — PRD said `contact_email` "must be unique" but never pinned the rejection error; impl raises `ERR_INVALID_REQUEST` (400) on collision — `routes_accounts.py:28-30`.

**Scope note:** Walked every endpoint, calculation (calc.py), validation-ordering branch, state guard, ledger/derived-field recompute, response shape. Most behaviors already uniquely pinned (pricing tiers, deposit threshold, reschedule/reclean credits, waterfall ordering, OCC, window half-open overlap, §3.9 validation-priority chain, append-only entity shapes, 201/200 split). §3.4 narrative lists ERR_ROUTE_NOT_PLANNING before ERR_AGREEMENT_NOT_ACTIVE while impl checks agreement-active first, but §3.9's explicit priority order already pins agreement-active first and impl follows §3.9 — internally resolved, left untouched.

## Pipeline complete — 2026-06-13T04:49:13.000Z

Final verification: all 8 stability-sweep rounds report `passed=69 / total=69`. Task directory contains SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 7 files, 69 tests), workspace/ (INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ with results.{1..8}.json all green).
