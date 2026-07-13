# Worklog — task_0815_elevator_inspection

## Step 1: Create task directory — 2026-07-10T08:01:00.000Z

Created `tasks/task_0815_elevator_inspection/` and `tasks/task_0815_elevator_inspection/workspace/` (pre-assigned directory, no index auto-scan).

## Step 2: Generate scaffold — 2026-07-10T08:32:00.000Z

All checks pass. The scaffold is complete and internally consistent.

Generated a fresh **Expert**-tier scaffold for the Elevator & Conveyance Inspection domain at `/home/ubuntu/github/CodingPRD/tasks/task_0815_elevator_inspection/`. Three files, all `yaml.safe_load`-clean, `scaffold_lint.py` reports **VERDICT: clean lint** (368 calls scanned, 0 violations), all grounds resolve, all names unique, and every computed literal was verified against the formulas in code.

**Design choices** (prioritized diversity axes): `compliance_audit` + `temporal_windowing` archetypes, **flat** entity topology (peer FK links, `api_prefix: ""`), **branching** state-machine shape, **segregation_of_duties** role model (accident-lead independence rule), layers = optimistic_concurrency / cascading_side_effects / dual_variant_calculation / scheduled_deferred_actions. Logical clock via `POST /_clock/set` (integer period-index months, startup default 0).

**SCAFFOLD.yaml counts:**
- Entities: **10** (Owner, Inspector, Device, Inspection, Deficiency, Citation, Certificate, OutOfServiceOrder, FeeInvoice, AccidentReport)
- State machines: **8** (Inspection branching, Citation cyclic contest loop, Certificate suspend/reinstate cycle, Device OOS cycle, AccidentReport branching, + Deficiency/OOO/FeeInvoice)
- Calculations: **6** (dual-variant fee_amount + accident_risk_score; combinatorial citation_fine (mode a) + device_outstanding_balance_cents (mode b, round-then-sum); certificate_expiry + next_inspection_due)
- Validations: **17** (priority-ordered, with the two priority-conflict pairs)
- Endpoints: **44**
- Errors: **44**
- Roles: **4** (Registrar/opaque, LicensedInspector/entity_backed:Inspector, SafetyAdministrator/opaque, BuildingOwner/entity_backed:Owner)
- Concurrency rules: **1** (certificate-issue-stale-device, OCC on Device.version, 412)

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids × 2 = **18 instances** (all 9 Difficulty Rules covered, each with a falsifiable distinguishing_aspect and pre-computed literal asserts).

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:** **26 active instances** + 6 `excluded_because` stubs (32 total), spanning entities/state_machines/calculations/validations/errors/rbac/cross_cutting/consistency_model — including the OCC stale-version test, RBAC + ownership denials, computed-field checks, cascade bubble-up, and certificate supersede.

## Step 3: Copy shared files — 2026-07-10T08:33:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0815_elevator_inspection/workspace/INSTRUCTION.md`.

## Step 2b: Scaffold constant-gap patch (orchestrator-initiated) — 2026-07-10T08:43:00.000Z

The Step-4 PRD generator flagged 4 constants REFERENCED by SCAFFOLD.yaml formulas but never given values. Orchestrator verified the gap was real and resumed the scaffold subagent to patch SCAFFOLD.yaml only (design files untouched).

Added 4 constant-bearing `calculations[]` entries (calc count 6 → 10):
1. `device_risk_class` → `RISK_CLASS: { PASSENGER_ELEVATOR: HIGH, FREIGHT_ELEVATOR: MEDIUM, ESCALATOR: HIGH, MOVING_WALK: MEDIUM, DUMBWAITER: LOW }`
2. `deficiency_resolution_due_period` → `RESOLUTION_GRACE_MONTHS: { MINOR: 6, MAJOR: 3, CRITICAL: 1 }`
3. `citation_due_period` → `CITATION_DUE_GRACE_MONTHS: 2`
4. `inspector_schedule_conflict_window` → `INSPECTION_BUFFER_PERIODS: 1`

`SEVERITY_WEIGHT`, `OPEN_CRITICAL_DEFICIENCY_BONUS`, `UNSUBSTANTIATED_FACTOR` were already declared — no change.

Consistency confirmed: RISK_CLASS anchors match every baked-in §1.8/§1.9 literal assert (PASSENGER→HIGH·1.5 → accident final 110, citation surcharge 8044/18044; ESCALATOR→HIGH → citation_fine mode_a 40000; DUMBWAITER→LOW → outstanding_balance mode_b 21451). `INSPECTION_BUFFER_PERIODS: 1` matches `inspector_halfopen_buffer_conflict`'s "12 < 12+1". No §1.8/§1.9 assert invalidated; design files not modified. `scaffold_lint.py` still clean; YAML safe_loads.

## Step 4: Generate PRD — 2026-07-10T08:48:00.000Z

Generated `workspace/PRD.md`.

- **Line count:** 285 lines
- **Sections:** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties & Logical Clock, 2.5 OCC & Certificate Supersession, 2.6 Outstanding Balance Ledger, 2.7 Precision, 2.8 Out-of-Service Propagation, 2.9 Validation Ordering); §3 Business Logic (9 subsections); §4 Endpoint table; §5 Error catalogue.
- **Endpoint count covered: 44 / 44** including `/_clock/set`.
- Contract 1 (Field-Name Coverage): PASS. Contract 2 (Rule Coverage): PASS — both dual-variant calcs, tiered citation_fine, pinned rounding-order balance aggregation, OCC rule + `expected_device_version`/`ERR_STALE_DEVICE_VERSION`/412, both cascades, segregation-of-duties, validation priority ordering. Contract 3 (§3 Path Purity): PASS. All 32 state values, 25 enum values, every error ID present.

### Step 4b: Constant-value pin patch (after Step 2b scaffold fix)

PRD.md was generated before the scaffold constants existed, so it named them abstractly. Resumed the PRD subagent for a minimal 4-Edit patch:

| Section | Constant pinned | Value now in prose |
| --- | --- | --- |
| §3.1 | `RISK_CLASS` | full 5-entry map; plus note that `risk_class` feeds the risk multiplier in both the citation-fine and accident-risk-score calcs |
| §3.4 | `INSPECTION_BUFFER_PERIODS` | buffer of 1 period; exact strict-`<` overlap test spelled out |
| §3.5 | `RESOLUTION_GRACE_MONTHS` | 6 / 3 / 1 months for MINOR / MAJOR / CRITICAL |
| §3.6 | `CITATION_DUE_GRACE_MONTHS` | `due_period` = `issued_period` + 2 months |

Pre-existing constants re-verified concrete: SEVERITY_WEIGHT (10/30/60/100), OPEN_CRITICAL_DEFICIENCY_BONUS (20), UNSUBSTANTIATED_FACTOR (0.25), RISK_MULTIPLIER (1.5/1.2/1.0), INTERVAL_MONTHS (12/12/6/6/24), REGISTRATION_FEE_CENTS (10000), BASE_RENEWAL_FEE_CENTS (30000/25000/40000/35000/15000), LATE_RATE_PER_MONTH, LATE_CAP_RATIO, BASE_FINE_CENTS (5000/20000/50000), REPEAT_SURCHARGE_CENTS (10000, cap count 3), FINE_CAP_CENTS (100000), OUTSTANDING_INDEX_RATE (0.0725).

Orchestrator independently verified: grep for every constant SYMBOL returns 0 matches in PRD.md; endpoint count still 44; 285 lines.

**Known residual ambiguity (accepted):** Certificate `EXPIRED` is a declared terminal state with no state-machine transition producing it; PRD describes it as read-time reclassification once the clock passes `expiry_period`. No §1.8/§1.9 instance asserts `EXPIRED`, so no test depends on it.

## Step 5: Generate unit tests — 2026-07-10T09:10:00.000Z

Generated complete test infrastructure for the Elevator & Conveyance Inspection API (Expert task) from the two design indices only — no freelance walking of SCAFFOLD.yaml.

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — 10 entity TypedDicts (all `common_fields: true` → carry `id/created_at/updated_at/version`) + 14 status/enum types + `UserRole`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (clock, owners, inspectors, devices, inspections, deficiencies, citations, certificates, OOS orders, fee-invoices, accident-reports).
- `api_errors.py` — full `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque Registrar/SafetyAdmin constants + `make_licensed_inspector_headers`/`make_building_owner_headers` builders for the entity-backed roles), `fixtures.py` (composite setup: fee-paid/active devices, inspection lifecycle, cited deficiencies, posted certificates, cascades), `__init__.py` barrel.
- Verified: all helpers import cleanly against the installed `prd_bench_local_runner.testing` framework.

### Stage 2 — `test_suite/` (conftest + 9 test files, 62 tests)
- **Queue A (Difficulty): all 18 instances emitted, 2 tests each = 36 tests.** Second test per instance is a genuinely distinct assertion (side-effect split, boundary X±1 contrast, or validation-precedence "loser error not surfaced" proof).
- **Queue B (Corner): all 26 active instances emitted, 1 test each = 26 tests.** The 6 `excluded_because` stubs were correctly NOT translated (verified each `difficulty_instance` cross-reference resolves).

### Skips
**None.** Every one of the 44 non-stub instances passed the PRD-first two-condition filter — each asserted rule (error_id, threshold, transition, calc result, side effect) has a verbatim PRD sentence that uniquely derives the outcome. The two validation-priority-conflict instances are derivable because PRD §2.9 pins the evaluation order and §3.4/§3.7 narrate the competing guards in that same sequence.

### Verification performed
- All 10 helper modules + 10 suite modules import without error.
- Coverage audit: 18 difficulty ×2, 26 corner ×1, 6 stubs untranslated, all 44 unique Design tags resolve to real instance `name:` values; no dual/untagged tests.
- Citation audit: all 73 quoted PRD spans are verbatim (whitespace-normalized, backtick-exact) against `workspace/PRD.md`.

## Step 6: Generate implementation — 2026-07-10T09:10:00.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`.

### Module layout
- `start.sh` — foreground launcher; reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap `import flask` check, `exec python3 app.py`.
- `app.py` — app factory, blueprint registration, `ApiError`/HTTPException/fallback error handlers.
- `store.py` — in-memory dicts keyed by id + logical clock (`current_period_index` default 0); no disk, no seeding. Fresh process = empty state.
- `constants.py` — all lookup tables (risk class, intervals, fees, fines, severity weights, buffers).
- `errors.py`, `envelope.py` (meta/response_type/data envelope), `auth.py` (X-User-ID/X-User-Role, 4 roles), `common.py` (body/enum/int validation, pagination, lookups).
- `services/logic.py` — derived quantities (outstanding balance, active counts, current cert), the four calculations with `Decimal` round-half-up, citation issuance, OOS activation/lift propagation, and all serializers.
- `routes/` — 11 modules (clock, owners, inspectors, devices, inspections, deficiencies, citations, certificates, oos, fees, accidents).

### Route count
- `grep -rhoE "@[a-z_]+\.route\(" | wc -l` → **44**; Flask `url_map` (excluding static) → **44 rules**; SCAFFOLD.yaml declares **44**. Match confirmed.

### Verification (all 4 required checks)
1. `app.py` exists ✓  2. Every `.py` passes `ast.parse` ✓  3. Registered routes = 44 vs scaffold's 44 ✓
4. `PORT=18815 bash start.sh` booted and served; `POST /_clock/set {"to_period_index":0}` returned HTTP 200 with proper envelope.

### Behavioral spot-checks (all correct)
- Auth precedence: missing headers → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; wrong role → `ERR_INSUFFICIENT_PERMISSIONS`.
- Registration billing gate: auto REGISTRATION invoice (10000); `activate` → `ERR_REGISTRATION_FEE_UNPAID` until paid, then ACTIVE, balance 0.
- FAIL-with-CRITICAL depth-3 cascade (ESCALATOR/HIGH): citation `fine_amount_cents=75000`, `surcharged_amount_cents=80438`, device→OUT_OF_SERVICE, `active_oos_count=1`, inspector `active_assignment_count` 1→0.
- Certificate OCC: stale version → `ERR_STALE_DEVICE_VERSION` (412); correct version issues, sets `current_certificate_id`, device version advances; owner posts → POSTED.
- OOS propagation: order → cert SUSPENDED; lift (count→0) → device ACTIVE, cert reinstated POSTED.
- Accident scoring (SEVERE/HIGH substantiated): `final_risk_score=90` (60×1.5), copied to device.

Key design decision: computed fields (`outstanding_balance_cents`, `active_oos_count`, `active_assignment_count`, `current_certificate_id`, effective OVERDUE/EXPIRED statuses) are derived at read time from entity status rather than maintained incrementally, eliminating ledger-drift bugs while satisfying the pinned per-citation round-then-sum rounding order.

### Orchestrator independent verification (Steps 5+6)
44 route decorators == 44 scaffold endpoints; `app.py` + `start.sh` present; all impl/test/helper `.py` pass `ast.parse`; 11 route modules present; no sqlite/`/tmp`/`json.dump`/pickle persistence; no module-level entity seeding; 62 tests carrying exactly 62 `Design:` tags (1:1).

## Step 7: Run tests and iterate — 2026-07-10T09:20:00.000Z

All 8 rounds are clean: 62/62 passed, 0 failed, 0 errors, and zero non-passing test records across every round. No diagnostic protocol was needed — no test failed in any round.

- **Iterations run:** 1 full 8-round sweep (two waves of four). All 8 rounds passed on the first sweep.
- **Tests deleted:** None. No test failed unique-derivability or coverage checks because no test failed at all.
- **Fixes applied to `test_helpers/`:** None.
- **Fixes applied to `implementation/`:** None.
- **Final result (passed/total per round):**
  - results.1: 62/62 · results.2: 62/62 · results.3: 62/62 · results.4: 62/62
  - results.5: 62/62 · results.6: 62/62 · results.7: 62/62 · results.8: 62/62
  - All 8 rounds: 62 passed, 0 failed, 0 errors, 0 skipped.

### Environment note (harness artifact, not a task bug)
Early sweep invocations died with **exit 144** and produced no `results.json` — this was **not** host saturation or a start.sh problem. Root cause: `pkill -f 'prd-bench-local-run'` / `pkill -f 'tasks/task_0815_elevator_inspection.*app.py'` matched the killer shell's **own** command line (the pattern text appears verbatim in the Bash invocation), so `pkill` terminated its own parent shell → exit 144. Fix: move the sweep into a script file (`/tmp/sweep.sh`) so the shell's command line is just `bash /tmp/sweep.sh` (no matching pattern) and narrow the reap pattern to `python3 app.py`. With that, the sweep ran cleanly. No changes were made to `implementation/`, `test_suite/`, `test_helpers/`, or `start.sh`.

### Orchestrator independent verification (Step 7)
Re-parsed all 8 `results.*.json`: every file reports `passed=62 total=62 failed=0 errors=0`, and a scan of each file's per-test `results[]` array found 0 records with status != passed.

## Step 8: Finalize PRD — SKIPPED — 2026-07-10T09:21:00.000Z

Skip condition met per the pipeline spec: Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. `PRD.md` already determined every behavior the implementation exhibits at every site the test suite exercised. No `PRD_FINALIZED.md` is produced; Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-10T09:27:00.000Z

Done. All three edits applied cleanly; line count preserved (285), 44-endpoint table and section numbering intact.

**Line counts:** PRD.md 285 lines / 45,085 chars → PRD_COMPLETED.md 285 lines / 46,159 chars (**+1,068 chars**, zero net line change — all edits are in-paragraph).

**Counts:** ambiguity-pins: 2, mismatch-revisions: 1.

**Changes (one bullet each):**
- **§3.7** — revise — mismatch — Certificate `EXPIRED` was worded as a real terminal transition; pinned it as a read-time, presentational reclassification applied only to a stored `ISSUED`/`POSTED` cert when `current_period_index` is strictly past `expiry_period`, that does not mutate stored status (so `ISSUED`-only guards like posting still fire) and never touches `SUSPENDED`/`REVOKED`/`SUPERSEDED` — `services/logic.py:51-54`, honoured by list filter `routes/certificates.py:102`.
- **§3.1** — revise — ambiguity — `current_certificate_id` was described as a stored field "set on issuance"; pinned it as read-time-derived (the `id` of the cert whose *effective* status is currently `ISSUED`/`POSTED`, else null), reverting to null while the cert is suspended/expired/revoked/superseded — `services/logic.py:86-90`.
- **§3.3** — insert — ambiguity — decommission cascade was silent on `assigned_inspector_id`; pinned that (unlike the standalone §3.4 cancel, which clears it) the cascade leaves each cancelled inspection's `assigned_inspector_id` in place — `routes/devices.py:113-117`.

**Verified as already-pinned (no change needed):** fee-invoice `OVERDUE` read-time reclassification (§3.2 already correct, matches `logic.py:45-48`); `outstanding_balance_cents`, `active_oos_count`, `active_assignment_count` are computed live in the serializer but are observationally identical to the PRD's stated aggregation/counter rules in every reachable state, so no prose divergence. All calculation formulas (citation fine, fee late-penalty, accident risk score), validation-ordering (esp. certificate issuance guard order §3.7/§2.9), schedule-conflict and OOS-overlap interval math, cascade side effects, and 201/200 response codes match the implementation exactly.

### Orchestrator independent verification (Step 9)
`PRD_COMPLETED.md` present, 285 lines, 44 endpoint rows, 24 headings (identical to `PRD.md`); `diff` shows exactly 3 changed lines (6 diff sides) — a genuinely minimal patch. `PRD_FINALIZED.md` correctly absent.

---

# Pipeline complete — all 9 steps done (Step 8 skipped by rule).
