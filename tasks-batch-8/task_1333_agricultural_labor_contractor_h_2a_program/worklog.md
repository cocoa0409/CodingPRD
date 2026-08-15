# Worklog — task_1333_agricultural_labor_contractor_h_2a_program

## Step 1: Create Task Directory — 2026-08-12T22:14:00.000Z

Task directory `tasks/task_1333_agricultural_labor_contractor_h_2a_program/` and `workspace/` pre-created by pipeline dispatcher (per invocation args). Verified existence; skipped index scan as instructed.

## Step 2: Generate Scaffold — 2026-08-12T23:17:00.000Z

Scaffold generation complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1333_agricultural_labor_contractor_h_2a_program/` and the lint verdict is clean.

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     39
  Calls scanned (§1.8+§1.9):  1009

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Artifact counts**
- **SCAFFOLD.yaml** (§1.0–§1.7, no design keys): 15 entities, 13 state machines, 10 calculations, 10 ordered validation priorities, 72 endpoints, 69 error codes, 7 roles, 1 OCC concurrency rule. Fixed response envelope verbatim; logical clock endpoint with mandatory default `2026-08-01T00:00:00Z`.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): 18 instances — exactly 2 per each of the 9 difficulty rules.
- **SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): 39 active instances + 8 `excluded_because` stubs across sections entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency_model.

**Design highlights (harder-than-expert calibration)**
- Archetypes: compliance/audit primary + ledger-reconciliation secondary; layers: dual-variant calculation, cascading side effects, optimistic concurrency, rate/threshold triggers.
- Dual-variant calculations in two domains: wage reconciliation (provisional OPEN vs frozen FINAL — divergence pinned at 148000 vs 223000 cents) and audit penalties (provisional 570000 vs final 918000 with per-kind cap-then-sum-then-discount order pinned; counterfactual order yields different cents).
- Cyclic state machines on two entities: JobOrder SUBMITTED↔DEFICIENCY cure loop; VisaPetition FILED↔RFE loop with a hard 2-RFE cap.
- Transitive cascades from two triggers: transfer finalize (TransferRequest → source assignment TRANSFERRED_OUT → reconciliation truncation; plus target assignment + new OPEN reconciliation) and debarment (AuditCase → Grower DEBARRED → JobOrder WITHDRAWN → petition WITHDRAWN → worker reverted REGISTERED).
- Two overlap rules with different interval semantics: consular per-(consulate, date) point quota of 6 vs half-open-interval aggregate housing capacity plus a one-bed-per-worker rule.
- Boundary pins: certification exactly at start−30d allowed, one day later rejected; recruitment cutoff inclusive (2026-09-25 blocks, 2026-09-26 allows); inbound transport owed exactly at the 50% threshold date.
- All money literals in asserts were pre-computed by executing the pinned formulas in a Python oracle (workday counts exclude Sundays; guarantee on integer quarter-hours with floor; per-day round-half-up then sum — 1812 vs naive 1813).

No sibling task directories were inspected; everything was derived from the scenario text plus the skill specification.

## Step 3: Copy Shared Files — 2026-08-12T23:17:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1333_agricultural_labor_contractor_h_2a_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T23:37:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1333_agricultural_labor_contractor_h_2a_program/workspace/PRD.md`. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Section list

- **§1. Introduction** — 2 paragraphs (business context angle + system goals/segregation-of-duties angle); `/h2a` mount declared
- **§2. Global Specifications** — 9 subsections: 2.1 RBAC (7 roles, identity prose per role), 2.2 API Response Structure (emitted **byte-for-byte verbatim**, diff-verified against `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Server Logical Clock (default 2026-08-01T00:00:00Z, no wall-clock fallback), 2.5 Common Resource Properties (incl. explicit absence of `updated_at`/`version` on the two `common_fields: false` entities — HousingInspection, WorkLog), 2.6 Money/Dates/Workday Calendar (integer cents, round-half-up, Sunday-excluding workdays), 2.7 Nested Resource Retrieval (all 12 `ERR_*_NOT_FOUND` enumerated), 2.8 OCC (sole rule: `expected_job_order_version` → `ERR_STALE_JOB_ORDER_VERSION` 412), 2.9 Validation Priority Ordering (all 10 priorities in explicit evaluation order)
- **§3. Business Logic** — 9 subsections on a business-timeline grouping: 3.1 Growers/Wage Determinations, 3.2 Job Order Draft-to-Certify (+OCC patch, withdraw cascades), 3.3 Domestic Recruitment & Preference Window, 3.4 Workers/Petitions/Consular (+activation), 3.5 Housing, 3.6 Assignments & Work Logs, 3.7 Wage Reconciliation/Three-Quarters Guarantee/Close-Out, 3.8 Transfers, 3.9 Audit/Penalties/Debarment
- **§4. Endpoint Definitions** — 72/72 endpoints, 4 columns only (Method, Path, Description, Authorized Role(s))
- **§5. Error Code Catalogue** — 69/69 errors, 2 columns only

## Size

- **8,820 words, 388 lines** (66,446 bytes)

## Zero-Silence Rule audit (§1.1–§1.7 scaffold coverage)

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 104 required, 104 present, 0 missing
- `endpoints[].request_body`/`input`: 66 required, 66 present, 0 missing
- `endpoints[].query_params`: 19 required, 19 present, 0 missing
- `endpoints[].path_params`: 12 required, 12 present, 0 missing

**Contract 2 — Rule Coverage: PASS**
- Validation priorities: 10 checked, 10 expressed in explicit order in §2.9 (incl. fiscal-last tie-break)
- OCC rules: 1/1 expressed (write endpoint + `expected_job_order_version` + `ERR_STALE_JOB_ORDER_VERSION`/412, stale-read framing only)
- State-machine transitions: 40/40 fully expressed (from/to, preconditions paired with exact error IDs, all side effects incl. cascades — withdraw, debar, denial revert, housing vacate, abandonment auto-audit-case, transfer atomic cutover)
- Calculations: 10/10 in precise prose (workday count, derived terms with live/locked variants, recruitment window inclusive boundary, weekly reconciliation with pinned round-per-day-then-sum order, 3/4 guarantee with floor-on-quarters and no-clawback boundary, transport thresholds, consular 6-slot boundary, half-open housing overlap with adjacency exclusion, pinned penalty order with all base/cap/multiplier/discount constants, 365-day debarment term)
- Validation conditions: all matchable to error IDs in §2/§3 prose (69/69 error IDs appear in narrative, not just §5)
- Endpoint side effects / applies_to scopes: all expressed, incl. the 5 GrowerRep ownership scopes
- Field structured content (types, defaults, null-until semantics, computed derivations): reconstructible from prose
- Sibling-branch symmetry: PASS (HIRE/REJECT, APPROVE/DENY, COMPLETED/FOR_CAUSE, PASS/FAIL per unit state, 6 withdraw legs, transfer approve/reject/cancel)
- Aux checks: 74/74 enum/state values present verbatim; 7/7 roles present; no fuzzy words; no operator syntax/pseudocode in prose; 0 consecutive "The system" paragraph starters

**Contract 3 — §3 Path Purity: PASS**
- 719 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos

(Note: the first audit run produced false failures — triple-backtick fences in the verbatim §2.2 block shifted inline-code pairing parity, and `'## 3.'` substring-matched `'### 3.x'` headings. The final audit stripped fenced blocks and used heading-line regexes; results above are the corrected ones.)

## Step 5: Generate Unit Tests — 2026-08-13T00:14:00.000Z

Generation complete for task_1333. Summary:

**Test counts**
- Queue A (Difficulty): 18/18 instances covered, 36 tests (exactly 2 per instance)
- Queue B (Corner): 39/39 non-stub instances covered, 39 tests; 8 `excluded_because:` stubs not translated (all difficulty-instance pointers verified to resolve)
- Total: 75 tests, all carrying exactly one resolvable `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` docstring tag, all with verbatim-grep-verified PRD citations

**Instances skipped:** none beyond the 8 design-stub exclusions. Two partial adjudications under the PRD-first filter (assertion-level, instances still translated):
- `Corner/errors/temporal_guards_dates_and_windows_rejected`: dropped the create-time `ERR_INVALID_DATE_RANGE` sub-assertion — PRD §3.2 pins the inverted-dates check to *submission* ("work_end_date must not fall before work_start_date" is a submit precondition), so a create-time rejection is not uniquely derivable. The other three guards (inspection-future, undecided-applications, not-yet-started) are asserted.
- Absolute initial `version == 1` claims (in `job_order_creation_derives_terms`, `job_order_patch_occ_stale_version_rejected`, and the cure-cycle's `version == 5`) were relaxed to relative assertions — PRD §2.5 states version "increments with every modification" but never pins the initial value, so tests capture the observed version and assert increment-by-exactly-one instead.

**test_helpers/ (9 files):** `__init__.py` (barrel), `types.py` (15 entity TypedDicts incl. append-only HousingInspection/WorkLog without `updated_at`/`version`, 18 enums), `api_client.py` (56 endpoint methods under `/h2a`), `api_errors.py` (69 error IDs + HTTP map registered with the framework), `assertions.py` (15 entity assertions), `factories.py` (input-only payload factories, WD1/J1 defaults), `constants.py` (725 federal minimum, 30-day cert lead, RFE cap 2, consular quota 6, penalty bases/cap/discount, shared J1/J2 date literals, workday series), `test_users.py` (7 roles; `make_grower_rep_headers(grower_id)` for the entity-backed GrowerRep), `fixtures.py` (clock helper, per-entity creators, `create_recruiting_order`/`create_petitioning_order`, `setup_active_order_pipeline`, `setup_two_grower_scenario`, `setup_transfer_grower_approved`, `setup_approved_petition_with_linked_workers`, audit-case setup).

**test_suite/ (11 files):** `conftest.py` + `test_01_creation_identity_and_read_surface.py` (10), `test_02_job_order_lifecycle.py` (8), `test_03_domestic_recruitment.py` (6), `test_04_petitions_and_activation.py` (9), `test_05_consular_appointments.py` (6), `test_06_housing.py` (8), `test_07_assignments_and_worklogs.py` (7), `test_08_wage_reconciliation.py` (8), `test_09_transfers.py` (5), `test_10_audit_and_enforcement.py` (8). All pre-computed money/date literals (e.g. final total 612300, truncated-transfer recon 177600, penalty 918000, cap-before-sum 2000000, rounding-order discriminator 1812) copied verbatim from the design indices.

**Stage 2 lint verdict:** CLEAN — 75 tests collected by pytest, every Design tag resolves to a real instance, difficulty coverage 18/18 (≥2 each), corner coverage 39/39 (≥1 each), stubs 0 tests each, every ≥8-word citation substring greps verbatim in PRD.md, no skip/skipif/xfail markers.

## Step 6: Generate Implementation — 2026-08-13T00:14:00.000Z

Implementation complete. Summary:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1333_agricultural_labor_contractor_h_2a_program/workspace/implementation/`)

- `start.sh` — executable; guarded pip install (no-op when Flask present), `exec python3 app.py` in foreground, reads `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, ApiError + catch-all error handlers, blueprint registration
- `store.py` — in-memory dicts keyed by id (15 entity tables), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, never wall-clock; **zero seeding at startup**
- `common.py` — response envelope (`meta.api_request_id`/`api_request_timestamp` 3-fractional-digit ISO, `response_type`, `data`, pagination fields `limit`/`offset`/`total_count`/`has_more` with defaults 10/0 clamped to [1,100]), auth decorator (priorities 1-2: `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 400, `ERR_UNAUTHORIZED_ROLE` 403), pagination, validators
- `calc.py` — all calculation rules
- `services.py` — 15 serializers + cascades (withdraw, debar, housing vacate, worker departure, abandonment audit-case creation, reconciliation recompute)
- `routes/{core,orders,people,housing,work,transfers,audit}.py` — endpoint handlers

## Endpoints: 72/72 implemented
Clock set; growers (create/list/refresh-status); wage determinations (create w/ supersession, list); job orders (create/list/get/PATCH+OCC/submit/flag-deficiency/certify/begin-recruitment/close-recruitment/activate/close/finalize/withdraw); domestic applications (create/list/decide); workers (create/list/get); visa petitions (create/list/get/file/link-worker/issue-rfe/respond-rfe/adjudicate); consular appointments (create/list/get/complete/cancel); housing units (create/list/get/inspections create+list/expire); housing assignments (create/list/get/vacate); worker assignments (create/list/get/start/end/report-abandonment); work logs (create/list); reconciliation (get/finalize); transfer requests (create/list/get/grower-approve/grower-reject/finalize/cancel); audit cases (create/list/get/issue-findings/close-no-action/assess-penalty/debar).

## State machines: 12 implemented
Grower (ACTIVE/SUSPENDED/DEBARRED + refresh reinstatement), WageDetermination (PUBLISHED→SUPERSEDED), JobOrder (10 states incl. deficiency cure loop and withdraw cascade), DomesticApplication (preference-window guarded REJECT), Worker (6 states), VisaPetition (FILED↔RFE loop, max 2 RFEs), ConsularAppointment, HousingUnit (UNINSPECTED/CERTIFIED/FAILED/EXPIRED recert loop), HousingAssignment, WorkerAssignment (incl. PLANNED FOR_CAUSE escape hatch, TRANSFERRED_OUT), WageReconciliation (OPEN→FINALIZED provisional/final variants), TransferRequest (PENDING→GROWER_APPROVED→APPROVED), AuditCase.

## Calculations: 10 implemented
Sunday-excluding workday calendar; job-order derived terms with **live-vs-locked wage pinning** (unsubmitted orders resolve to the successor PUBLISHED determination after supersession — verified); recruitment window (inclusive cutoff); weekly wage reconciliation (7-day weeks anchored at `work_start_date`, pinned per-day `round_half_up` then sum, Decimal arithmetic); three-quarters guarantee (integer quarter-hours, floor on 3/4); transport reimbursement (inclusive 50% threshold, abandonment/completion rules); consular capacity (6/day, CANCELLED/COMPLETED free slots); housing occupancy (half-open windows, aggregate capacity, one-bed-per-worker); audit penalty (provisional sum; final with willful ×2, per-kind cap before summation, then 10% good-faith round-half-up); debarment term (365 days/year, inclusive reinstatement boundary).

## Boot verification
Compiled clean; `bash start.sh` boots in ~2s on `$PORT` bound to `0.0.0.0`. Ran three smoke suites (170 checks total, each against a fresh process boot) covering the full lifecycle — order pipeline, deficiency cure, OCC 412, preference 422, RFE limits, consular outcomes, housing certification/capacity/overlap, transfer finalize atomicity (source TRANSFERRED_OUT with `ended_on = effective − 1`, new ACTIVE assignment + OPEN recon, housing vacate cascade), abandonment→auto-audit-case, penalty math (594000 with good faith), debar cascade, reinstatement, pagination clamping, and auth/RBAC failures — all passing (3 residual FAILs were stale expectations in my throwaway scripts, each re-verified as correct PRD-priority behavior in isolation). Validation priority ordering (auth → ownership → existence → state → safety → temporal → referential → constraint → field-domain/OCC) is enforced throughout.

## Step 7: Run Tests and Iterate — 2026-08-13T00:26:00.000Z

All 8 rounds pass 75/75. Clean sweep achieved.

## Summary

- **Iterations run**: 2 (initial sweep: 70/75 in all 8 rounds, identical failures — fully deterministic; post-fix sweep: 75/75 × 8 rounds, zero flakes).

- **Tests deleted**: none. Every failing assertion traced to a verbatim PRD sentence; all 5 failures were test-artifact bugs, not coverage/derivability gaps.

- **Fixes applied to `test_suite/`**:
  - `test_05_consular_appointments.py::test_appointment_complete_twice_terminal_lockdown` — the fixture was invoked with default `start_assignments=True`, legitimately moving the worker VISA_ISSUED → WORKING via assignment start (PRD 3.6), which collided with the test's "terminal appointment side effects must not re-fire" assertion that the worker remains VISA_ISSUED. Passed `start_assignments=False` so the setup matches the asserted rule (PRD 3.4).
  - `test_06_housing.py::test_housing_lifecycle_and_guard_battery` — asserted `certification_valid_until == "2028-08-02"` for `certified_on = 2027-08-02`; PRD 3.5 pins "certified_on advanced by 365 days", and 2027-08-02 + 365d = 2028-08-01 (2028 is a leap year). Corrected the literal to `2028-08-01`.
  - `test_08_wage_reconciliation.py::test_provisional_variant_values_before_end` and `test_final_variant_adds_outbound_transport` — both asserted `makeup_pay_cents == 3550`, contradicting the tests' own comment `(88800-67500) + (59200-45000)` = 35500 and the PRD 3.7 weekly make-up formula. Corrected both literals to `35500`; the companion `total_due_cents` expectations (148000 / 223000) were already consistent with 35500.

- **Fixes applied to `test_helpers/`**:
  - `fixtures.py::setup_active_order_pipeline` — the returned `workers` dict held create-time `REGISTERED` snapshots for every passport except visa recipients (only those were refreshed after `complete_appointment`). A linked-but-not-yet-visa'd worker (server-side `PETITIONED`) was returned as stale `REGISTERED`, breaking `test_assignment_create_requires_worker_visa_issued`'s setup precondition. Added a final refresh of all worker snapshots before returning.

- **Fixes applied to `implementation/`**: none — the implementation was PRD-faithful in all 5 cases (365-day certification validity, per-day-round-then-sum weekly make-up math, worker state machine transitions).

## Step 8: Finalize PRD — 2026-08-13T01:05:00.000Z

The copy is in place. I made zero edits to it — here is the full justification.

## Summary

**Deliverable**: `/home/ubuntu/github/CodingPRD/tasks/task_1333_agricultural_labor_contractor_h_2a_program/workspace/PRD_FINALIZED.md` — byte-identical copy of `PRD.md`.

**Line counts / delta**: `PRD.md` 387 lines, `PRD_FINALIZED.md` 387 lines, 0.0% delta (`diff -q` confirms identical).

**Changes**: none. Every one of the 5 Step 7 fixes was a test-artifact bug asserting against behavior the PRD already pins verbatim; Step 7 applied zero implementation fixes and found the implementation PRD-faithful in all 5 cases. Per the method ("Patch PRD_FINALIZED.md only when impl pinned a choice PRD left open — not every item is a PRD silence"), no edit traced to a genuine PRD silence or PRD/impl mismatch, so any edit would have violated the minimal-change and NO-NEW-MISMATCH rules.

**Per-item pre-edit investigation log** (each candidate edit was investigated and rejected):

1. **test_05 `test_appointment_complete_twice_terminal_lockdown`** — (a) Subject: consular-appointment completion lockdown and worker state transitions. (b) Paths enumerated: `implementation/routes/people.py:326-354` (`complete_appointment`: non-`SCHEDULED` → `ERR_APPOINTMENT_INVALID_STATE` before any mutation; `ISSUED` moves only `PETITIONED`→`VISA_ISSUED`; `REFUSED` → `REGISTERED` + `petition_id=None`; `NO_SHOW` untouched), `people.py:357-367` (`cancel_appointment`), `routes/work.py:96-115` (`start_assignment` moves `VISA_ISSUED`→`WORKING` and creates the OPEN reconciliation). (c) No edit: PRD 3.4 verbatim-pins "only for a `SCHEDULED` appointment (else `ERR_APPOINTMENT_INVALID_STATE`)" and all three outcome transitions; PRD 3.6 verbatim-pins "moves the worker from `VISA_ISSUED` to `WORKING`". The failure was the fixture's `start_assignments=True` default; the PRD uniquely determines both legs.

2. **test_06 housing certification literal** — (a) Subject: `certification_valid_until` computation and its two enforcement gates. (b) Paths enumerated: `implementation/services.py:176-193` (`ser_housing_unit`: `certified_on + timedelta(days=365)`, emitted only while `CERTIFIED`, else null), `routes/housing.py:117-131` (`expire_housing_unit`: same +365, expiry allowed only when clock strictly later), `routes/housing.py:156-163` (move-in gate: same +365, rejection when clock past it). (c) No edit: PRD 3.5 pins "`certified_on` advanced by 365 days" — an unambiguous day-count advance matching `timedelta(days=365)`; the test's `2028-08-02` literal was a leap-year miscount (2027-08-02 + 365d = 2028-08-01). All three impl sites use the identical formula, consistent with the single PRD sentence.

3. **test_08 `test_provisional_variant_values_before_end` / `test_final_variant_adds_outbound_transport`** — (a) Subject: weekly make-up pay formula, per-day rounding order, `total_due_cents` composition. (b) Paths enumerated: `implementation/calc.py:112-211` (`recon_compute`: workweeks anchored at `work_start_date` clipped to `work_end_date`; per-day `rhu(quarters*floor, 4)` summed within the week; `makeup = max(0, wk_floor - wk_piece)` per week, summed), plus all recompute callsites: `services.py:336-354`, `routes/work.py:217-220` (work-log creation), `work.py:96-115` (start), `services.py:381-397` (end), `routes/transfers.py:168-171,183` (transfer finalize), `routes/work.py:245-258` (finalize-reconciliation). (c) No edit: PRD 3.7 verbatim-pins the weekly make-up formula ("the amount by which the weekly floor exceeds the weekly piece earnings, or zero... the make-up pay sums to `makeup_pay_cents`"), the rounding order ("round each day first, then sum within the week; summing hours first and rounding once... is non-conformant"), and the `total_due_cents` sum. The `3550` literals were typos contradicting the tests' own comment arithmetic `(88800-67500)+(59200-45000)=35500`.

4. **fixtures.py `setup_active_order_pipeline` worker refresh** — (a) Subject: worker status after petition linking. (b) Path enumerated: `implementation/routes/people.py:157-178` (`link_worker`: requires `REGISTERED`, sets `PETITIONED` + `petition_id`). (c) No edit: PRD 3.4 verbatim-pins "Linking moves the worker to `PETITIONED` and sets the worker's `petition_id` to the petition." Pure helper staleness bug; server behavior never in doubt.

Key finding for the caller: a fresh implementer reading `PRD.md` already receives a uniquely-determining specification at every site Step 7 touched — the clean 75/75 sweep was achieved entirely by correcting test literals, a fixture default, and stale helper snapshots, so `PRD_FINALIZED.md` is intentionally a zero-patch copy.

## Step 9: Complete PRD — 2026-08-13T01:40:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1333_agricultural_labor_contractor_h_2a_program/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (source, identical to `PRD.md`) — 387 lines / 66,446 chars. `PRD_COMPLETED.md` — 387 lines / 70,028 chars. Char delta: +3,582 across 21 edited lines (all in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** 20 ambiguity-pins (PRD silent or admitting multiple readings), 1 mismatch-revision (penalty-cap grouping).

**Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.1 — insert — ambiguity — whitespace-only auth headers count as empty — `implementation/common.py:157`
- §2.3 — revise — ambiguity — `limit`/`offset` clamped into 1–100 / ≥0 rather than rejected; non-integer → `ERR_INVALID_REQUEST`; sort ties broken by creation order; `has_more` defined as `offset + returned < total_count` — `implementation/common.py:120-141`
- §2.3 — revise — ambiguity — replaced "for example" filter list with the exhaustive per-endpoint filter sets (adds `status` filters on most lists, `worker_id`/`petition_id` on appointments, `grower_id` on housing units/audit cases; pins that inspection/work-log/reconciliation lists take no filters) — `implementation/routes/*.py` list handlers
- §2.4 — revise — ambiguity — clock set accepts any ISO 8601 instant (offsets converted to UTC, offset-less read as UTC, backward sets allowed), invalid/missing → `ERR_INVALID_REQUEST`; `current_utc` echoes fractional digits only when sub-second precision present — `implementation/common.py:50-55,71-83`; `implementation/routes/core.py:16-22`
- §2.5 — insert — ambiguity — resources are created with `version` 1 — `implementation/common.py:198`
- §2.5 — insert — ambiguity — optional `note` payloads on RFE issue/respond, transfer reject, and abandonment report are accepted but never persisted (audit-case creation `note` is stored) — `implementation/routes/people.py:183-206`; `implementation/routes/transfers.py:129-142`; `implementation/routes/work.py:144-163`; `implementation/routes/audit.py:41-46`
- §2.9 — insert — ambiguity — required string fields validated only for presence/type (no length/format checks; empty strings accepted) — `implementation/common.py:217-221`
- §3.1 — insert — ambiguity — grower `state_code` "two-letter" shape is descriptive, not validated — `implementation/routes/core.py:35-37`
- §3.1 — revise — ambiguity — wage-determination `prevailing_piece_rate_cents_per_unit` must be a positive integer when present; `piece_unit_name` is independently optional — `implementation/routes/core.py:98-106`
- §3.2 — revise — ambiguity — job-order `offered_piece_rate_cents_per_unit` must be a positive integer when present — `implementation/routes/orders.py:39-41`
- §3.2 — insert — ambiguity — `work_end_date` ≥ `work_start_date` (`ERR_INVALID_DATE_RANGE`) also enforced at creation and on every update; submission check is a backstop — `implementation/routes/orders.py:46-50,147-151`
- §3.2 — insert — ambiguity — PATCH ignores non-patchable payload fields; version match verified before the merged post-update values are fully revalidated against creation's domain rules — `implementation/routes/orders.py:138-154`
- §3.4 — insert — ambiguity — link-worker returns the petition object; only the worker record is modified — `implementation/routes/people.py:175-178`
- §3.5 — insert — ambiguity — inspection flips apply from any current status: PASS on `CERTIFIED` re-certifies and refreshes `certified_on`; FAIL on `FAILED`/`EXPIRED` leaves `FAILED` with `certified_on` null — `implementation/routes/housing.py:96-101`
- §3.5 — insert — ambiguity — successful expiry also clears `certified_on` to null — `implementation/routes/housing.py:128-129`
- §3.5 — insert — ambiguity — housing move-in: `worker_id` not cross-checked against the assignment's worker; `move_in_date` validity check runs before the capacity/overlap counts — `implementation/routes/housing.py:138-183`
- §3.6 — insert — ambiguity — ending with clock date before `started_on` surfaces as `ERR_INVALID_REQUEST`, evaluated before `end_reason` validation — `implementation/routes/work.py:126-131`
- §3.7 — insert — ambiguity — order finalization: an assignment that never started owns no reconciliation and cannot block `CLOSED` — `implementation/routes/orders.py:282-288`
- §3.8 — insert — ambiguity — transfer `worker_id` recorded as supplied, not cross-checked against the source assignment's worker — `implementation/routes/transfers.py:24-85`
- §3.9 — revise — mismatch — final penalty caps each finding entry independently at 1,000,000 cents; duplicate `violation_code` entries are never merged into a per-kind total — `implementation/calc.py:241-249`
- §3.9 — insert — ambiguity — debarring an already-`DEBARRED` grower changes nothing grower-side (`debarment_ends_on` preserved, no cascade) while the case still resolves — `implementation/services.py:419-425`

All other impl behaviors (envelope shapes, error catalog statuses, state machines, recon math, cascades, OCC, validation priority ordering) were verified to already be uniquely pinned by the PRD and left untouched.
