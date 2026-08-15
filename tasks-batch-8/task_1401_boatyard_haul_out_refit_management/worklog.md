# Worklog — task_1401_boatyard_haul_out_refit_management

## Step 1: Create Task Directory — 2026-08-13T03:43:57.323Z

Task directory `tasks/task_1401_boatyard_haul_out_refit_management/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher (Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-13T04:41:51.808Z

All checks pass. The scaffold is complete and lint-clean.

## Summary

Generated the full scaffold for **task_1401_boatyard_haul_out_refit_management** at `/home/ubuntu/github/CodingPRD/tasks/task_1401_boatyard_haul_out_refit_management/`:

**Complexity profile**: temporal windowing (primary) + pricing engine (secondary); layers: optimistic concurrency, cascading side effects, dual-variant calculation, ops-run checkpoint; flat topology, cyclic state machines, segregation-of-duties role model, immediate consistency.

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys):
- **12 entities**: Vessel, InsuranceCertificate, RefitJob, LiftSlot, YardRow, StandAssignment, WorkOrder, LaborEntry, Part, EnvironmentalEvent, ComplianceHold, LedgerEntry (LaborEntry/LedgerEntry append-only, `common_fields: false`)
- **9 state machines**: RefitJob (10 states, sea-trial-fail cycle + haul rebooking loop), WorkOrder (change-order cycle + hold loop), LiftSlot (with NO_SHOW), StandAssignment, Part, EnvironmentalEvent, ComplianceHold, InsuranceCertificate, LedgerEntry
- **10 calculations**: dual-variant storage accrual (DAILY marginal tiers × winter 0.85 multiplier, per-day rounding vs MONTHLY_CONTRACT 30-day blocks), dual-variant work-order cost (estimate vs actual with 1.15 subcontractor markup), per-line-then-sum rounding pinned, runoff ppm bands (>=100 violation), lift-slot overlap (half-open + 30-min buffer), stand occupancy (closed intervals, aggregate capacity, exact-fit allowed), ledger balance, 25% deposit requirement, insurance certificate selector (latest expiry, created_at tie-break)
- **19 validations** ordered auth → existence → shape → OCC → state → safety (moratorium, lift capacity, insurance, hold gate) → constraint → fiscal
- **47 endpoints** including `POST /yard/ops/run-daily-close` (pinned 4-step checkpoint, idempotent same-day) and `POST /yard/_clock/set_current_utc` (default 2026-08-01T00:00:00Z)
- **21 error codes**; **5 roles** (ServiceWriter, YardManager, EnvironmentalOfficer, Accountant, Owner — all opaque; Owner scoped via `vessel.owner_user_id`; hold create/release segregated by kind)
- **2 OCC concurrency rules**: `job-patch-stale-version`, `stand-assign-stale-row`

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 instances (2 per rule × 9 rules), all with structured setup chains and literal asserts precomputed via Python (21800 vs 56000 storage divergence; 11011 per-day vs 11008 sum-then-round; 30821 vs 30820 per-line rounding; depth-3 env cascade → hold → readiness revocation → splash cancel; depth-2 sea-trial cascade; state-vs-fiscal and safety-vs-constraint priority pairs; ppm 100.0 and stand exact-fit boundaries; insurance→job and workorder→job cross-deps; buffer-adjacency vs closed-interval overlap; stand-capacity and ledger-balance invariants).

**SCAFFOLD_CORNER_DESIGN.yaml**: 41 instances (39 active + 2 `excluded_because` stubs) across all 9 claim-extraction sections.

**Lint verdict** (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (47 endpoints, 12 entities, 18 §1.8 + 39 §1.9 instances, 643 calls scanned). One fix was needed post-draft: sub-resource GET paths normalized to the literal `{id}` placeholder for lint check (f). Additional audits: no forbidden concurrency vocabulary, all 59 instance names unique, zero unbound `${var}` placeholders.

## Step 3: Copy Shared Files — 2026-08-13T04:42:17.983Z

Copied `./INSTRUCTION.md` → `tasks/task_1401_boatyard_haul_out_refit_management/workspace/INSTRUCTION.md` (bash only, no subagent).

## Step 4: Generate PRD — 2026-08-13T04:49:06.959Z

The PRD is generated and all three hard contracts pass. Here is the summary.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1401_boatyard_haul_out_refit_management/workspace/PRD.md` — 300 lines.

**PRD structure:**
- §1 Introduction (2 paragraphs — business context + system coverage)
- §2 Global Specifications (9 subsections): 2.1 RBAC with per-role identity prose, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties & Versioning (incl. `common_fields: false` caveat for `LaborEntry`/`LedgerEntry`), 2.5 OCC (both rules), 2.6 Logical Yard Clock (startup default `2026-08-01T00:00:00Z`), 2.7 Monetary Precision & Rounding, 2.8 Job Ledger (kinds, categories, balance rule, void compensation), 2.9 Request Evaluation Order (the seven generic priority gates 1–7 in explicit order)
- §3 Business Logic (11 subsections, chronological lifecycle grouping): vessels/insurance → job intake → lift scheduling → stands → work orders → labor → parts → environmental events → holds → splash/sea-trial/deposits → statement/daily-close/storage-accrual
- §4 Endpoint table (4 columns × 47 endpoints)
- §5 Error catalogue (2 columns × 21 errors)

**Coverage audit — all three hard contracts PASS:**
- Contract 1 (field-name coverage): 103 required identifiers (entity fields, request bodies, query params, statement/daily-close/clock output fields, envelope fields) — 103 present in backticks, 0 missing.
- Contract 2 (rule coverage): 19 priority-ordered validations expressed (gates 1–7 in §2.9 with explicit ordering; business rules 8–19 scattered into the §3 workflows they guard, with applies-to scopes enumerated); 2 OCC rules with endpoint + `expected_*_version` field + `ERR_STALE_VERSION`/412 (no race framing); all 9 state machines' transitions (RefitJob 17, WorkOrder 11, LiftSlot 3, others) with preconditions paired to error IDs and every side-effect cascade; all 10 calculations (quoted_total, labor_line_cost with 1.15 markup, dual-variant work_order_cost and storage_accrual with all tier/winter/monthly constants, runoff thresholds with inclusive boundaries, lift overlap with 30-minute buffer and adjacency rule, stand closed-interval capacity with exactly-full-allowed boundary, ledger balance, deposit 25% rule with inclusive boundary, certificate selection with expiry-DESC/created_at-DESC tie-break); 6 sibling-branch groups rendered symmetrically (cancel from six states, DAILY vs MONTHLY_CONTRACT, PASS vs FAIL, RECEIVED vs REJECTED, HAUL_OUT vs SPLASH completion, three ppm bands).
- Contract 3 (§3 path purity): 519 backtick tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos.

**Deliberate information-scattering choices:**
- Endpoint inputs are split across subsections: e.g. lift-slot booking inputs (`job_id`, `kind`, `scheduled_start`, `scheduled_end`, `vessel_displacement_tons`) appear in §3.3, but the SPLASH-only deposit gate and readiness gate are deferred to §3.10; work-order quotation fields appear in §3.5 while the requote revision semantics and the subcontractor prohibition land in §3.5/§3.6 separately.
- Constants embedded in prose rather than tables: 60-ton lift rating, 100000000-cent liability floor (glossed as "one million dollars"), 50/65/85 cent-per-foot tiers, 0.85 winter multiplier, 1400-cent monthly block, 30-minute lift buffer, 50.0/100.0 ppm thresholds, 25% deposit, 10% handling fee, 1.15 markup — each stated inside its business sentence, with unit/context conversion ("one million dollars") used once.
- The four-hop violation cascade is told once in §3.8 and referenced (not repeated) from §3.9 and §3.10, forcing cross-subsection reconstruction; the same pattern is used for the readiness re-evaluation (defined in §3.10, triggered from §3.6 and §3.9).
- §2.2 emitted byte-verbatim from the canonical source file. §4 table carries no request/response schemas; §5 carries no trigger conditions — both force readers back into §2/§3 narrative.

## Step 5: Generate Unit Tests — 2026-08-13T05:20:08.671Z

All checks pass. Generation is complete.

## Summary

### Output locations
- `test_helpers/` — `/home/ubuntu/github/CodingPRD/tasks/task_1401_boatyard_haul_out_refit_management/test_helpers/`:
  - `__init__.py` (barrel: framework generics + PRD-specific re-exports)
  - `types.py` (12 entity TypedDicts + status/role enums; `LaborEntry`/`LedgerEntry` correctly omit `updated_at`/`version` per PRD §2.4 append-only rule)
  - `api_client.py` (`ApiClient(GenericApiClient)`, one method per PRD §4 endpoint — 40 endpoint methods)
  - `api_errors.py` (21 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`)
  - `assertions.py` (per-entity asserts + `assert_statement` + `assert_ledger_balance_invariants`)
  - `factories.py` (12 payload factories, input fields only)
  - `constants.py` (lift capacity 60t, 30-min buffer, ppm 50/100, tier rates 50/65/85, winter 0.85, monthly 1400/30, markup 1.15, deposit 0.25, startup clock)
  - `test_users.py` (5 opaque roles; `make_owner_headers(user_id)` mandatory builder for ownership-gated Owner calls)
  - `fixtures.py` (~370 lines: primitive steps + `setup_job_on_hard`, `setup_job_ready_for_splash`, `setup_job_awaiting_trial`, `setup_two_jobs_different_billing_modes`, `setup_two_intake_jobs`, `setup_moratorium_scenario`; OCC versions always re-read before stand assignment)
- `test_suite/` — `conftest.py` (session `api` fixture + per-test connection-pool reset for per-test-server isolation + 5 role-header fixtures) and 5 test files:
  - `test_01_vessels_insurance_and_jobs.py` (12 tests)
  - `test_02_lift_slots_and_stands.py` (17 tests)
  - `test_03_work_orders_labor_parts.py` (19 tests)
  - `test_04_environmental_and_holds.py` (10 tests)
  - `test_05_splash_trial_storage_billing.py` (17 tests)

### Coverage
- **Queue A (Difficulty): 36 tests across all 16 instances — every instance has ≥2 tests.** Priority-pair instances were translated (not skipped) because PRD §2.9/§3.3 explicitly pins the gate order ("Only after all seven generic gates pass do the business rules of Section 3 apply" / "Three safety gates guard every booking, checked in this order").
- **Queue B (Corner): 39 tests across all 39 non-stub instances — one test each.** The 2 stubs (`statement_computed_read`, `statement_immediate_consistency`) were not translated; both `excluded_because` pointers resolve to `compensating_invariant/ledger_post_void_conserves_balance`, which owns the assertion with 2 tests.
- Total: **75 tests, all collected cleanly by pytest** (collection-only; no server was run).

### Skipped instances
None. One partial-literal deviation: `Corner/entities/vessel_creation_returns_201_with_system_fields` was translated, but its `version == 1` literal was dropped (PRD §2.4 states only "a `version` integer that increments by one on every mutation" — the initial value is not uniquely derivable, matching the precedent in earlier generated tasks). The test asserts id/created_at/updated_at presence, version-is-int, and field echoes instead.

### Self-check verdicts
- **Stage 1**: all helpers compile and import; client/factories/fixtures signatures verified by import smoke test.
- **Stage 2**: automated audit confirms — 0 untagged tests, 0 dual-tagged tests, 0 unresolvable tags, every queue-A instance ≥2 tests, every queue-B non-stub instance ≥1 test, no stub translated, no `skip`/`skipif`/`xfail` markers, no "scaffold" mentions in generated code, and every docstring PRD citation survives a whitespace-insensitive verbatim grep of `PRD.md` (0 misses).

## Step 6: Generate Implementation — 2026-08-13T05:20:08.671Z

Implementation complete and verified end-to-end (122/122 smoke checks pass on a fresh `bash start.sh` cold boot; store confirmed empty at boot).

## Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1401_boatyard_haul_out_refit_management/workspace/implementation/`):

- `start.sh` — executable; guarded dependency install (`pip install` only if `flask` not importable), `exec python3 app.py` in foreground; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0,<4.0 (Flask 3.1.3 already present on host, so install is a no-op at boot)
- `app.py` — Flask app factory, global RLock per request, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND`; catch-all 500), route registration
- `db.py` — in-memory stores (12 dicts, empty at boot, no seeding), UUID ids, strictly-monotonic wall-clock `created_at`/`updated_at` (3 fractional digits), `touch()` for version bumps
- `clock.py` — logical clock, starts exactly `2026-08-01T00:00:00Z`, settable only via the test-driving endpoint
- `errors.py`, `response.py`, `middleware.py`, `validation.py`, `money.py` — error catalog (all 21 IDs with exact HTTP codes), `meta`/`response_type`/`data` envelope with pagination fields, `X-User-ID`/`X-User-Role` auth + role + ownership gates, shape validators (strict types, bools rejected as ints), Decimal round-half-up helpers
- `routes/`: `vessels.py`, `insurance.py`, `jobs.py`, `lift_slots.py`, `yard.py` (rows+stands), `work_orders.py` (+labor), `parts.py`, `compliance.py` (events+holds), `ledger.py`, `ops.py` (daily close + clock)
- `services/`: `insurance.py` (certificate selection), `lifecycle.py` (cascades/readiness), `storage.py` (accrual/statement/deposit/balance), `overlap.py` (lift buffer conflict, closed-interval stand capacity)

**Entity/endpoint coverage**: all 12 entities and all 47 endpoints from the scaffold table, with exact role matrices (including kind-segregated holds and Owner ownership scoping on vessel/job/work-order/part/statement reads and approve/request-change/part-create writes).

**State machines implemented**: RefitJob (11 states incl. rebooking loop HAUL_SCHEDULED→INTAKE, readiness transitions, sea-trial PASS/FAIL, daily-close closure), WorkOrder (change-order cycle ESTIMATE→APPROVED→IN_PROGRESS→CHANGE_REQUESTED→ESTIMATE, hold-driven ON_HOLD/resume, cancel cascade), LiftSlot (BOOKED→COMPLETED/CANCELLED/NO_SHOW with window enforcement), StandAssignment, Part (inspect with fee), EnvironmentalEvent (ppm-computed initial status, remediate), ComplianceHold (manual release only for MANUAL source), InsuranceCertificate (daily-close expiry), LedgerEntry (void compensation). Validation gates run in the PRD §2.9 order: auth → role → ownership → existence → shape → OCC → state → business rules (moratorium → capacity → insurance → conflict → deposit for bookings).

**Calculations implemented**: quoted total (labor-product-only rounding), labor line cost (1.15 subcontractor markup, per-line round-then-sum), tiered DAILY storage (50/65/85 cents-per-foot by lay-day index, 0.85 winter multiplier Nov 1–Mar 31, per-day rounding), MONTHLY_CONTRACT 30-day blocks (1400 cents/ft on lay days 1,31,61,…), runoff thresholds (≥100 violation, ≥50 advisory, inclusive boundary), lift-slot overlap (30-min buffer, strict-inequality adjacency allowed), closed-interval stand capacity (exactly-full allowed), ledger balance, 25% deposit requirement (inclusive boundary), certificate selection (expiry DESC, created_at DESC tie-break), and the four-step daily close in pinned order with same-day idempotency.

**Known limitations / judgment calls** (PRD-ambiguous points): initial `version` is 1 at creation; nullable system fields (e.g. `hauled_at`, `source_work_order_id`) serialize as JSON null rather than being omitted; slot `scheduled_start`/`scheduled_end` and the clock's `current_utc` echo the exact input string; out-of-range `limit`/`offset` return 400; invalid list-filter enum values return an empty list (200); duplicate yard-row `code` returns 400 ERR_VALIDATION (no dedicated error ID exists); owner-supplied part fee of 0 cents posts no charge (amounts must be positive); PATCH/job-child-creation against terminal jobs returns ERR_INVALID_STATE per the explicit endpoint rules (ERR_ALREADY_TERMINAL reserved for state-transition endpoints).

## Step 7: Run Tests and Iterate — 2026-08-13T05:33:41.518Z

The 8-round parallel stability sweep is clean: every round reports 75/75 passed, 0 failed, 0 errors. Exit condition met.

## Summary

- **Iterations run:** 2 sweeps (16 parallel rounds total).

- **Sweep 1 result:** 7 distinct tests failed across rounds 1-2-4-5-6-7 (rounds 3 and 8 were fully green). Every failure was infrastructure-flavored, not a logic failure:
  - 6 rounds had "API server could not be restarted" setup errors (the runner's 15-second per-test boot-poll window exhausted under ambient load).
  - 1 round had a mid-test `ConnectionResetError(104)`.
  - Root cause: host contention — several sibling task pipelines (tasks 1392/1395/1398, …) were running their own 8-round sweeps concurrently (load average 35-41 on 32 cores), and each `start.sh` boot paid for two full Python interpreter starts (the `python3 -c "import flask"` dependency precheck plus `exec python3 app.py`), stretching occasional boots past the poll window.
  - Verification: all 7 union tests were rerun standalone against a freshly booted server — every one passed deterministically, confirming no implementation or test bug.

- **Tests deleted:** none. Audited all failing tests plus the full suite against PRD.md — every assertion traces to a verbatim PRD sentence (error IDs, boundaries, cascade hops, rounding pins), and unique derivability held for each; no PRD-silent or two-reader-divergent tests found.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:** one file —
  - `/home/ubuntu/github/CodingPRD/tasks/task_1401_boatyard_haul_out_refit_management/workspace/implementation/start.sh`: added a `.deps_ok` sentinel so the flask dependency check runs only on first boot; per-test reboots now go straight to `exec python3 app.py`, halving boot-time interpreter spawns under the concurrent sweep. No application logic changed.

- **Final state:** sweep 2 — all 8 rounds, 75/75 passed, 0 failed, 0 errors.

## Step 8: Finalize PRD — 2026-08-13T05:35:54.836Z

All verification is complete. No edits are warranted — the single Step 7 fix is launcher-internal and reveals zero PRD silence or mismatch.

**Verification evidence:**
- `implementation/start.sh` (the only Step 7-touched file): the change wraps the flask import check / pip install in a `.deps_ok` first-boot sentinel; the final `exec python3 app.py` is unchanged, so application startup behavior is identical on every boot.
- PRD grep for launcher/boot/install/pip/flask/port terms: only false-positive substring hits ("port" inside "reports" on lines 208, 210). The PRD makes no statement about the launcher.
- PRD §2.6's only startup-related claim ("At server startup the logical clock is exactly `2026-08-01T00:00:00Z`") is implemented in `implementation/clock.py:1` — application code, untouched by Step 7, still executed on every boot via `exec python3 app.py`.
- `INSTRUCTION.md` confirms the launcher contract (dependency install, foreground exec, port binding) is governed by the instructions, not the PRD: "All API requirements are defined in `PRD.md`."
- `diff PRD.md PRD_FINALIZED.md` → identical.

**Summary on exit:**

- **Line counts:** PRD.md = 300 lines; PRD_FINALIZED.md = 300 lines; 0% delta (byte-identical copy at `/home/ubuntu/github/CodingPRD/tasks/task_1401_boatyard_haul_out_refit_management/workspace/PRD_FINALIZED.md`).
- **Changes:** none. Zero bullets — no insert or revise was made.
- **Decision-level search log (in lieu of per-edit logs, since no edits were committed):**
  - (a) Subject: Step 7's `.deps_ok` dependency-check caching in `start.sh`.
  - (b) Impl paths enumerated and read: `implementation/start.sh` (full file — the Step 7 site); `implementation/app.py` (entry point, global lock, error handlers — confirmed unchanged and unaffected); `implementation/clock.py` (logical-clock initialization, the PRD's only startup-coupled behavior, §2.6); `implementation/` directory listing (no other launcher-adjacent files); PRD.md full read + targeted grep for launcher/startup vocabulary; `INSTRUCTION.md` (to confirm launcher mechanics are outside PRD scope).
  - (c) Wording adjustment: none needed — there is no PRD sentence to adjust because the PRD is silent on launcher internals by design, and that silence is correct (the launcher contract lives in INSTRUCTION.md). Pinning launcher behavior into the PRD would itself violate the no-invented-behavior rule.

Explicit conclusion per the task note: the correct output is a PRD_FINALIZED.md identical in behavioral content to PRD.md, and it is.

## Step 9: Complete PRD — 2026-08-13T05:52:14.943Z

The diff confirms 22 lines revised inline (44 changed lines total: 22 old + 22 new), line count unchanged at 300, no new sections or paragraphs. All pins verified against the code. Final report:

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1401_boatyard_haul_out_refit_management/workspace/PRD_COMPLETED.md`

**Source vs output:** PRD_FINALIZED.md — 300 lines / 45,800 chars; PRD_COMPLETED.md — 300 lines / 48,840 chars. Char-delta: **+3,040** across **22 inline-revised lines** (zero added sections or paragraphs).

**Counts:** 27 ambiguity-pins, 2 mismatch-revisions.

### Changes

- **§2.3** — insert — ambiguity — out-of-range or non-integer `limit`/`offset` rejected with ERR_VALIDATION (400) — validation.py:125-147
- **§2.3** — insert — ambiguity — `has_more` true exactly when `offset` + returned item count < `total_count` — response.py:34
- **§2.3** — insert — ambiguity — list filters match by exact equality; unrecognized values yield empty page (200), never an error — lift_slots.py:117-120 (same pattern in all list routes)
- **§2.4** — insert — ambiguity — `version` starts at 1 at creation — vessels.py:48 and every create route
- **§2.4** — insert — ambiguity — `created_at`/`updated_at` are wall-clock UTC; the logical clock governs only named business dates — db.py:37-43
- **§2.4** — insert — ambiguity — valueless fields always serialize as JSON null, never omitted — db.py:46-48, storage.py:31-32
- **§2.6** — insert — ambiguity — clock endpoint's `current_utc` echoes the exact submitted `to_iso8601` string — ops.py:83
- **§2.6** — insert — ambiguity — submitted datetimes may carry any offset (naive read as UTC) and are normalized internally; calendar-date fields are strict `YYYY-MM-DD` — validation.py:89-118
- **§2.7** — revise — mismatch — replaced "evaluated at one decimal place" with direct comparison of the unrounded measured value against the threshold — compliance.py:61-66
- **§2.8** — revise — mismatch — `source_work_order_id`/`source_part_id` are present on every ledger entry, null when inapplicable (was "absent on any other entry") — storage.py:23-35
- **§2.8** — insert — ambiguity — ledger-entry listing accepts optional `kind` and `status` filters — ledger.py:51-57
- **§2.9** — insert — ambiguity — a nonexistent reference cannot be ownership-scoped, so it surfaces ERR_NOT_FOUND even for an Owner caller — vessels.py:58-59, jobs.py:93-94
- **§3.1** — insert — ambiguity — Owner single-vessel fetch is ownership-scoped (ERR_OWNERSHIP_MISMATCH) — vessels.py:55-60
- **§3.1** — insert — ambiguity — no ordering constraint imposed between `effective_date` and `expiry_date` at certificate creation — insurance.py:25-26
- **§3.2** — insert — ambiguity — new-job defaults: `lay_days` 0, `open_hold_count` 0, `scope_notes` null when omitted, lifecycle dates null — jobs.py:66-85
- **§3.2** — insert — ambiguity — PATCH semantics: omitted fields unchanged, null `billing_mode` treated as omitted, present `scope_notes` replaces (explicit null clears) — jobs.py:120-130
- **§3.2** — insert — ambiguity — cancel `reason` accepted but not persisted — jobs.py:156
- **§3.3** — insert — ambiguity — stored/returned `scheduled_start`/`scheduled_end` echo the exact submitted strings; comparisons use parsed UTC instants — lift_slots.py:91-92
- **§3.3** — insert — ambiguity — booking a slot against a terminal job yields ERR_ALREADY_TERMINAL — lift_slots.py:54-55
- **§3.3** — insert — ambiguity — temporal-conflict check runs before the deposit check on splash bookings — lift_slots.py:77-84
- **§3.4** — insert — ambiguity — duplicate yard-row `code` rejected with ERR_VALIDATION (400) — yard.py:45-47
- **§3.5** — insert — ambiguity — requote retains the recorded `change_note` — work_orders.py:182-188
- **§3.6** — insert — ambiguity — `subcontractor_name` on YARD_CREW lines: optional, string-validated, stored as given, else null — work_orders.py:225-230,246
- **§3.7** — insert — ambiguity — a computed zero handling fee (0 `declared_value_cents`) posts no ledger charge — parts.py:100-107
- **§3.8** — insert — ambiguity — auto-violation hold carries a system-generated `note` referencing the source event — compliance.py:88-92, lifecycle.py:47-64
- **§3.9** — revise — ambiguity — manual hold created with "a null `source_event_id`" (was "no `source_event_id`") — compliance.py:146, lifecycle.py:58
- **§3.10** — insert — ambiguity — sea-trial `notes` accepted but not persisted — jobs.py:178
- **§3.10** — revise — ambiguity — a `failed_work_order_id` that is not a COMPLETE work order of this job (including another job's work order) yields ERR_INVALID_STATE — jobs.py:195-197
- **§3.11** — insert — ambiguity — daily close accepts and ignores an optional request body — ops.py:23
- **§3.11** — insert — ambiguity — checkpoint identifier lists are in creation order of the underlying records — ops.py:29-63

### Hint verification

All eight reported judgment calls verified against code and now pinned: version=1 (all create routes), null serialization (db.py `pub` + storage.py:31-32), slot `scheduled_start`/`scheduled_end` and clock `current_utc` exact-string echoes (lift_slots.py:91-92, ops.py:83), out-of-range `limit`/`offset` → 400 (validation.py:136-146), invalid list-filter values → empty 200 (all list routes), duplicate row `code` → 400 (yard.py:47), zero owner-part fee → no charge (parts.py:102). The terminal-job hint held for PATCH and all child-creation endpoints (already pinned in PRD prose) with one exception found during verification: lift-slot booking against a terminal job returns ERR_ALREADY_TERMINAL (lift_slots.py:54-55), which I pinned explicitly in §3.3 rather than adopting the hint's generalization.
