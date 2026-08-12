# Worklog — task_1215_maple_sugarbush_syrup_production

## Step 1: Create Task Directory — 2026-08-11T22:54:04.266Z

Task directory `tasks/task_1215_maple_sugarbush_syrup_production/` and its `workspace/` subdirectory were pre-assigned and already exist (per orchestrator instruction — Step 1 auto-index scan skipped). No files created by this step beyond this worklog.

Difficulty parameter from user (passed through to Step 2 only): "generate task hard than expert level!"

Scenario (verbatim, passed unmodified to Step 2):
1215. Maple Sugarbush & Syrup Production (Vermont sugarhouse): tap count & vacuum line monitoring, sap flow by weather window & collection scheduling, sugar content & boil-off yield calculation, grade classification & flavor evaluation, bulk drum vs retail packaging, certification (organic) & woods audit, lease agreements for tapping others' land, seasonal labor & short production window

## Step 2: Generate Scaffold — 2026-08-11T23:38:05.125Z

Scaffold generation complete for task 1215. Durable record follows.

## Task 1215 — Maple Sugarbush & Syrup Production: scaffold generated

**Output files (all exist, non-empty, file split honored):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/SCAFFOLD.yaml` — 82,576 bytes; §1.0–§1.7 only; no `scaffold_difficulty_design`/`scaffold_corner_design` keys (verified programmatically)
- `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 91,219 bytes; single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/SCAFFOLD_CORNER_DESIGN.yaml` — 148,985 bytes; single top-level key `scaffold_corner_design`

**Counts:** 14 entities, 70 endpoints, 38 error codes, 11 state machines, 10 calculations, 11 ordered validations, 4 roles, 2 OCC concurrency rules. §1.8: 18 instances (9 rules × 2). §1.9: 46 active + 3 `excluded_because` stubs across 8 sections (entities, state_machines, calculations, validations, endpoints, errors, roles, cross_cutting_complexity_layers). 1,066 recipe calls scanned.

**How "harder than expert" was realized** (Expert row treated as floor; density over volume):
- **Rule 1 (dual-variant)**: boil-off yield pins Rule-of-86 vs Rule-of-88.2 on the batch (3.81 vs 3.72 for identical inputs); lease royalty pins per-batch-double-rounded provisional (0.86) vs single-rounded final settlement (0.87) — different entity domains (production vs financial).
- **Rule 2 (combinatorial, distinct modes)**: mode (a) deterioration-adjusted volume-weighted brix with `max`/`min`/`floor(hours/24)` non-linearity (eff 1.6/2.8 → 2.05); mode (b) nested rounding order pinned (`round(round(245/86,2)×0.30,2)=0.86` ≠ single-round 0.85).
- **Rule 3**: 4 cyclic machines on 4 entities (Season OPEN↔SUSPENDED, TapLine ACTIVE↔LEAK, SyrupLot GRADED↔HELD, Lease DRAFT↔PENDING_AUDIT); instances exercise Season suspend/resume blocking collection and a live re-grade flipping GOLDEN→PROCESSING.
- **Rule 4**: depth-4 cascade (vacuum reading → line LEAK → bush taps_live → bush auto-demote LIVE→TAPPING → season aggregate) and depth-3 lease-terminate cascade (→ bush SHUTDOWN → lines PULLED → taps recompute), different triggers, hops spelled out in `side_effects`.
- **Rule 5**: state(p5) beats business_temporal(p7) on sap-run create; business_constraint(p8) beats business_fiscal(p10) on packaging create.
- **Rule 6**: finished_brix 66.0/65.9 legal-density boundary; exact-fit packaging (55.00 == 55.00 → EXHAUSTED at exactly 0.00).
- **Rule 7**: PackagingRun→SyrupLot and Lease→CertAudit cross-entity gates (plus Sugarbush→TapLine compound go-live, Season→batch evaporator-exclusion).
- **Rule 8**: weather-window half-open `[opens_at, closes_at)` adjacency vs cert-audit 14-day buffer — different interval semantics, different resources.
- **Rule 9**: sap-gallon conservation under batch cancel (60+40=100 → 100+0=100) and syrup-gallon conservation under fills (5.00+55.00=60.00 → 0.00+60.00).
- Plus: OCC on Season.version (window declaration) and Lease.version (amendment) per §1.2.1; segregation of duties (boiler ≠ grader); version-pinned taps_snapshot at lease activation; ops-run checkpoint sweep; logical clock with mandated default `2026-05-01T00:00:00Z` (fixtures in the Feb–Apr 2027 season); seasonal-labor window gating.

All formula-derived asserts are pre-computed literals (arithmetic embedded in the difficulty file header). Self-audit beyond lint: placeholder closure verified mechanically, name uniqueness across both design files, grounds resolution, error-reachability, enum closure, no forbidden race vocabulary.

**Lint:** `scaffold_lint.py` final verdict (verbatim):
```
Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  1066

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(One FK_REVERSE_UNREACHABLE finding — `FlavorEvaluation.evaluator_id -> CrewMember` — was fixed by adding `GET /sugarhouse/crew-members/{id}/evaluations`; re-run clean.)

No sibling tasks under `tasks/` were read at any point.

## Step 3: Copy Shared Files — 2026-08-11T23:38:36.801Z

Copied `./INSTRUCTION.md` → `tasks/task_1215_maple_sugarbush_syrup_production/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-11T23:43:30.128Z

## PRD Generation Report — task_1215_maple_sugarbush_syrup_production

**File on disk:** `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/workspace/PRD.md` — exists, non-empty, **344 lines / 50,058 bytes**.

**Section coverage vs scaffold (all rendered):**
- **§1 Introduction** — 3 paragraphs, pain-point + business-context framing.
- **§2.1 RBAC** — 4 roles with exact spelling; `identity:` translated to prose for each (opaque for `SugarhouseManager`/`CertInspector`; entity-backed `CrewMember` for `FieldCrew`/`SugarMaker` with the `collected_by`/`boiled_by`/`evaluator_id` match rule).
- **§2.2 Response structure** — emitted verbatim from `section-2.2-response-structure.md` (byte-identical, including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, empty `data`).
- **§2.3 Pagination** — `limit` default 10, min 1, max 100; `offset` default 0; sort `created_at` ASC; meta fields enumerated.
- **§2.4 Common fields + logical clock** — UUID `id`, ISO 8601 `created_at`/`updated_at`, integer `version`; explicit carve-out for `VacuumReading`/`BatchIntake`/`FlavorEvaluation` (`common_fields: false`, no `updated_at`/`version`); logical clock initial value `2026-05-01T00:00:00Z`, `to_iso8601` / `current_utc` named.
- **§2.5 Precision** — round-half-up at 2 decimals; Rule-of-86 vs Rule-of-88.2 dual variant explained.
- **§2.6 OCC** — both `concurrency_rules` rendered: `expected_lease_version` on lease amend and `expected_season_version` on window declare, both rejected with `ERR_STALE_VERSION` (412).
- **§2.7 Validation priority** — all 11 priority tiers enumerated in order with their error IDs.
- **§2.8 Aggregates/rollups** — `taps_rollup` and `season_aggregates` formulas in prose; `gallons_remaining` / `unpackaged_gallons` derivations.
- **§2.9 Container sizes** — `DRUM_55` 55.0, `RETAIL_QUART` 0.25, `RETAIL_PINT` 0.125.
- **§3 Business Logic** — 10 subsections covering: season arc, sugarbush + tap-line + vacuum cascade, weather windows + sap runs, leases + terminate/expire cascade, crew, batches/intakes/start-boil/finish/cancel with full deterioration + dual-yield math, lease royalty provisional/final (double-round vs single-round, CONDEMNED exclusion), grading + flavor + segregation-of-duties + organic-grader gate, packaging + lot exhaustion, cert audits + `organic_certified` recompute. All 12 state machines and all 10 calculation rules are in narrative form.
- **§4 Endpoint table** — 71 rows, 4 columns (Method/Path/Description/Roles) only.
- **§5 Error catalogue** — 38 rows, 2 columns (Error ID/HTTP Status) only.

**Hard Contract self-check results:**
- **Contract 1 (Field-name coverage):** 97 required names (all `entities[].fields[].name` + all endpoint `input` keys + common fields + pagination + envelope tokens) — 97 present, 0 missing. **PASS.**
- **Contract 2 (Rule coverage):** validations[] 11/11 priorities expressed in §2.7 with per-endpoint scopes in §3; concurrency_rules 2/2 expressed with write-endpoint + OCC field + error ID; state_machines 12/12 transitions named with preconditions and side-effects; calculations 10/10 formulas in precise prose; all 38 error IDs surface in §2 or §3; endpoint side-effects (cascades, compensations, rollups) all narrated; structured field content (defaults, nullability, conditionally-required `per_tap_cents`/`share_pct`) reconstructible from prose. **PASS.**
- **Contract 3 (§3 path purity):** 479 backticked tokens scanned inside §3 — 0 paths starting with `/`, 0 bare HTTP methods, 0 method+path combos. **PASS.**

**Zero-Silence Rule adjudications made:**
- `common_fields: false` on `VacuumReading`, `BatchIntake`, `FlavorEvaluation` — explicitly stated in §2.4 that these carry only `id` and `created_at` (no `updated_at`/`version`).
- Conditional requiredness of `per_tap_cents` (iff `PER_TAP`) and `share_pct` (iff `SHARE_OF_SYRUP`, range > 0 and ≤ 50) — expressed in §3.4 with `ERR_VALIDATION`.
- Vacuum leak boundary semantics — leak gate is strict-below (`target − 2.0` exactly does *not* leak), repair gate is inclusive (`target − 0.5` exactly passes). Both stated explicitly in §3.2.
- Freeze-thaw boundary semantics — `forecast_min_f` of exactly 32.0 qualifies, `forecast_max_f` of exactly 38.0 qualifies (§3.3).
- Yield-variance auto-hold boundary — exactly 15.0% absolute variance triggers `HELD` with `quality_hold_auto=true` (§3.6).
- `taps_snapshot` is frozen at lease activation and never altered by later tap changes; `active_lease_id` is *not* cleared on terminate (history preserved) and `stand_type` stays `LEASED` (§3.4).
- Final royalty settlement excludes batches whose `SyrupLot` is `CONDEMNED`; final variant accumulates raw and rounds once at the end while provisional double-rounds per batch (§3.7).
- Sap deterioration: floor at 0.5 brix, cap at 1.0 brix total, 0.2 brix per full 24-hour day, partial days discarded; downstream math consumes the *stored rounded* `input_brix` (§3.6).
- Grade thresholds: exactly 75.0 → `GOLDEN`, 74.9 → `AMBER`; `flavor_score` below 70 or non-empty `defect_flags` forces `PROCESSING` (§3.8).
- Single-evaporator constraint (`ERR_EVAPORATOR_BUSY`) and the FILLING-only cancel rule ("BOILING batches cannot be cancelled — the sap is already cooked") both stated (§3.6).
- Half-open window interval `[opens_at, closes_at)` for both the OCC window-open check and the `ERR_WINDOW_OVERLAP` intersection test (§3.3).
- 14-day minimum spacing on audits per bush (§3.10).

**Confirmation:** `PRD.md` exists on disk at the requested output path, non-empty, and no read of `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` occurred.

## Step 5: Generate Unit Tests — 2026-08-12T00:16:52.159Z

All checks pass. Final report:

## Task 1215 test generation complete

**Directories on disk** (both confirmed via `ls`):
- `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/test_suite/`

**Coverage counts**
- Queue A (Difficulty, SCAFFOLD_DIFFICULTY_DESIGN.yaml): **18/18 instances translated, 36 tests** (exactly 2 per instance).
- Queue B (Corner, SCAFFOLD_CORNER_DESIGN.yaml): **46/46 non-stub instances translated, 46 tests** (1 each). The 3 `excluded_because:` stubs (`syrup_lot_exhausted_auto_transition`, `taps_rollup_leak_state_filter`, `occ_window_declare_happy_path`) were NOT translated; all three cross-references resolve to real difficulty instances.
- Total: **82 tests**.

**Instances skipped: none.** Every non-stub instance in both indices passed the PRD-first two-condition filter — PRD.md verbatim-covers and uniquely derives each asserted rule.

Sub-assertion derivability notes (instances kept, non-PRD-pinned literals dropped):
- `season_create_initial_state` — `version == 1` not asserted (PRD §2.4 says version "starts at its initial value" without naming the value); test asserts PLANNED + zeroed aggregates + UUID + integer version.
- `batch_intake_immutable_shape` and `fifo_autofill_order_and_partial_draw` — absolute `draw_sequence == 1/2` not asserted (PRD §3.6 pins only "per-batch monotone"); tests assert integer presence / strictly increasing order.
- `reconcile_blocked_by_ungraded_lot` — the corner recipe records the flavor evaluation AFTER season close, but the close cascade (PRD §3.1) releases all ACTIVE crew and §3.5 requires an ACTIVE evaluator; the test records the evaluation before close (lot stays UNGRADED until the post-close grade), preserving every asserted outcome.
- `syrup_lot_hold_regrade_cycle` — clock advanced between the two evaluations so "latest by evaluated_at" is deterministic under the logical clock.

**test_helpers/ inventory (9 files)**: `__init__.py` (barrel), `types.py` (17 status/role enums + 14 TypedDicts with correct common_fields branching — VacuumReading/BatchIntake/FlavorEvaluation omit `updated_at`/`version`), `api_client.py` (ApiClient(GenericApiClient), 55 endpoint methods), `api_errors.py` (ApiErrorId, 38-entry HTTP_STATUS_CODES registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + sap/syrup conservation invariants), `factories.py` (15 payload factories, input fields only), `constants.py` (Rule of 86/88.2, deterioration, grade/vacuum/freeze thresholds, CONTAINER_GALLONS), `test_users.py` (opaque manager/inspector constants + mandatory per-instance builders `make_fieldcrew_headers`/`make_sugarmaker_headers` for the entity-backed roles), `fixtures.py` (composite chain: `setup_open_season`, `setup_live_bush`, `declare_window`/`open_window`, `hire_active_crew`, `setup_live_operation`, `collect_confirmed_run`, batch/draw/boil/finish helpers, `setup_batch_x_filling`/`setup_batch_x_boiling` (60h/36h deterioration scenario), `setup_ungraded_lot`, `setup_single_run_graded_lot`, `setup_two_lots_for_grade_boundary`, `create_lease_on_bush`/`submit_and_activate_lease`, `setup_leased_live_operation` (SHARE 30%), `setup_organic_audit_outcome`, `schedule_cert_audit`/`record_cert_result`).

**test_suite/ inventory (13 files)**: `conftest.py` (api/manager/inspector/fieldcrew/sugarmaker fixtures), `test_01_resource_creation_and_reading.py` (8), `test_02_security_rbac.py` (4), `test_03_season_lifecycle.py` (6), `test_04_tap_lines_vacuum.py` (4), `test_05_leases_and_royalty.py` (11), `test_06_weather_windows_and_crew_gates.py` (6), `test_07_certification_compliance.py` (7), `test_08_sap_collection.py` (6), `test_09_batch_intakes_and_cancel.py` (6), `test_10_boil_and_yield.py` (10), `test_11_grading_quality_holds.py` (6), `test_12_packaging.py` (8).

**Audit results**
- Tag audit: PASS — 82 tests, each with exactly one `Design:` line as the last docstring line; all 36 queue-A tags resolve to difficulty instances (≥2 tests each), all 46 queue-B tags resolve to non-stub corner instances (≥1 each); zero untagged/dual-tagged/stub-tagged tests.
- PRD verbatim-citation audit: PASS — every ≥8-word quoted span in every docstring matches PRD.md literally after whitespace normalization (initial run caught 3 elided quotes; fixed, plus 15 more elisions cleaned for C3; re-audit clean).
- `py_compile`: PASS — all 22 .py files compile.
- No `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold" references in generated code.
- `pytest --collect-only` with PYTHONPATH set: **82 tests collected** cleanly against the installed `prd_bench_local_runner` framework.

## Step 6: Generate Implementation — 2026-08-12T00:16:52.159Z

Implementation complete. Final report below (suitable for verbatim paste into worklog.md).

---

## Task 1215 — Maple Sugarbush & Syrup Production — Implementation Summary

### File inventory (under `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/workspace/implementation/`)

| Size (bytes) | Path |
|---|---|
| 2238 | app.py |
| 561 | db.py |
| 2495 | errors.py |
| 1912 | middleware.py |
| 16 | requirements.txt |
| 1998 | response.py |
| 0 | routes/__init__.py |
| 813 | routes/clock.py |
| 7309 | routes/seasons.py |
| 4753 | routes/sugarbushes.py |
| 14239 | routes/leases.py |
| 7844 | routes/tap_lines.py |
| 5683 | routes/weather_windows.py |
| 4753 | routes/crew.py |
| 7282 | routes/sap_runs.py |
| 11464 | routes/batches.py |
| 6933 | routes/syrup_lots.py |
| 4950 | routes/packaging.py |
| 3708 | routes/cert_audits.py |
| 0 | services/__init__.py |
| 24620 | services/core.py |
| 396 | start.sh |
| 5390 | util.py |

### Endpoint count
- SCAFFOLD §1.5 declared: **70** (method, path) pairs
- Registered in Flask: **70** — exact match, no extras, no missing

### State machines implemented
All 11 entity state machines with the exact from/to transitions, side effects, and cascade hops:
- **Season** (PLANNED/OPEN/SUSPENDED/CLOSED/RECONCILED): open, suspend, resume, close (with HOP1 cascades releasing crew, closing windows, voiding DRAFT runs), reconcile (final royalty settlement), run-sweep (closes expired windows, expires out-of-term leases with bush shutdown cascade)
- **Sugarbush** (PREP/TAPPING/LIVE/SHUTDOWN): begin-tapping, go-live (requires ≥1 non-PULLED line all ACTIVE), shutdown (cascade pulls all non-PULLED lines), system auto-regression LIVE→TAPPING when taps_live hits 0, lease terminate/expiry system cascade
- **TapLine** (INSTALLING/ACTIVE/LEAK/PULLED): activate, repair (hysteresis `target − 0.5` inclusive), pull, system leak trigger (strict `< target − 2.0`)
- **WeatherWindow** (FORECAST/OPEN/CLOSED): open (clock in half-open `[opens_at, closes_at)`), system close via run-sweep / season close
- **SapRun** (DRAFT/CONFIRMED/VOIDED): confirm, void (CONFIRMED→VOIDED blocked when `gallons_remaining != gallons_collected`)
- **EvaporatorBatch** (FILLING/BOILING/FINISHED/CANCELLED): start-boil (ERR_BATCH_EMPTY, ERR_EVAPORATOR_BUSY), finish (ERR_BRIX_BELOW_LEGAL ≥ 66.0), cancel (FILLING only, compensating intake draws back to runs)
- **SyrupLot** (UNGRADED/GRADED/HELD/CONDEMNED/EXHAUSTED): grade (from UNGRADED/HELD, requires ≥1 eval), hold, condemn, auto-EXHAUSTED at exactly `unpackaged_gallons == 0.00`
- **PackagingRun** (PLANNED/FILLED/CANCELLED): fill (re-checks lot GRADED + unpackaged), cancel
- **CrewMember** (HIRED/ACTIVE/RELEASED): activate (season OPEN + clock in window), release
- **CertAudit** (SCHEDULED/RECORDED): record-result (clock ≥ scheduled_for; ORGANIC recomputes bush organic_certified)
- **Lease** (DRAFT/PENDING_AUDIT/ACTIVE/TERMINATED/EXPIRED): submit-audit, PATCH amend (PENDING_AUDIT→DRAFT revision loop), activate (freezes taps_snapshot, attaches lease, sets stand_type=LEASED, PER_TAP accrual), terminate (bush shutdown cascade)

### Calculations implemented (decimal, ROUND_HALF_UP, 2dp)
- `weighted_input_brix`: deterioration = `min(1.0, 0.2 * floor(hours_held/24))`, floored at 0.5, volume-weighted average
- `boil_off_yield` dual variant: `estimated = sap_in * input_brix / 86` (Rule of 86) and `expected = sap_in * input_brix / 88.2` (Rule of 88.2), both computed at start-boil from the stored rounded `input_brix`
- `yield_variance_hold`: `round((measured − expected)/expected * 100, 2)`; `|variance| >= 15.0` forces lot HELD with `quality_hold_auto=true` (exactly 15.0 triggers)
- `grade_classification`: defect_flags non-empty or flavor_score < 70 → PROCESSING; else T≥75.0 GOLDEN / ≥50.0 AMBER / ≥25.0 DARK / else VERY_DARK
- `fifo_sap_allocation`: CONFIRMED runs ordered `collected_at ASC, created_at ASC`; partial fill allowed; empty set → ERR_NO_SAP_AVAILABLE
- `lease_royalty_accrual` dual variant: PER_TAP frozen `taps_snapshot * per_tap_cents` at activation; SHARE provisional per-batch double-rounded `(round(attr_sum/86, 2) * share/100) rounded`; SHARE final single-rounded volume-share `round(share/100 * Σ (bush_draw/sap_in * measured), 2)` excluding CONDEMNED lots
- `vacuum_leak_trigger`: LEAK at strictly `< target − 2.0` (exactly at threshold does not leak); repair gate inclusive `>= target − 0.5`
- `freeze_thaw_eligibility`: min ≤ 32.0 AND max ≥ 38.0 (both inclusive)
- `taps_rollup`: bush `taps_set` = SUM(ACTIVE, LEAK); bush `taps_live` = SUM(ACTIVE); season `taps_live` = SUM over non-SHUTDOWN bushes
- `season_aggregates`: `total_sap_gallons` = SUM(CONFIRMED); `total_syrup_gallons` = SUM(FINISHED)

### Validation priority tiers implemented (PRD §2.7 order)
1. **Auth presence** — X-User-Role + X-User-ID headers; role ∈ {SugarhouseManager, FieldCrew, SugarMaker, CertInspector} → ERR_UNAUTHENTICATED (401)
2. **Auth permission** — role gate per endpoint + entity-backed identity (FieldCrew/SugarMaker must match `collected_by`/`boiled_by`/`evaluator_id`) → ERR_UNAUTHORIZED_ROLE (403)
3. **Existence** — path ids and body FKs left-to-right → ERR_NOT_FOUND (404)
4. **OCC** — `expected_lease_version` on PATCH leases, `expected_season_version` on POST weather-windows → ERR_STALE_VERSION (412)
5. **State** — ERR_INVALID_STATE, ERR_SEASON_NOT_OPEN, ERR_SEASON_SUSPENDED, ERR_SUGARBUSH_NOT_LIVE, ERR_WINDOW_NOT_OPEN, ERR_CREW_NOT_ACTIVE, ERR_TAP_LINES_NOT_READY, ERR_VACUUM_STILL_LOW, ERR_BATCH_EMPTY, ERR_EVAPORATOR_BUSY, ERR_LOT_NOT_GRADED, ERR_LOT_NOT_GRADABLE (409)
6. **Compliance** — ERR_ORGANIC_AUDIT_REQUIRED, ERR_SEGREGATION_OF_DUTIES, ERR_GRADER_NOT_CERTIFIED, ERR_LEASE_NOT_ACTIVE (409)
7. **Temporal** — ERR_OUTSIDE_PRODUCTION_WINDOW, ERR_COLLECTED_OUTSIDE_WINDOW, ERR_AUDIT_NOT_DUE (422)
8. **Structural** — ERR_WINDOW_OVERLAP, ERR_NO_FREEZE_THAW, ERR_TAP_CAPACITY_EXCEEDED, ERR_BRIX_BELOW_LEGAL, ERR_GRADE_NOT_RETAIL_ELIGIBLE, ERR_AUDIT_TOO_CLOSE, ERR_LEASE_CONFLICT, ERR_SEASON_ALREADY_ACTIVE (422)
9. **Referential** — ERR_SEASON_HAS_OPEN_BATCHES, ERR_RECONCILE_BLOCKED, ERR_RUN_HAS_DRAWS (409)
10. **Quantity** — ERR_DRAW_EXCEEDS_REMAINING, ERR_INSUFFICIENT_UNPACKAGED, ERR_NO_SAP_AVAILABLE (422)
11. **Malformed** — ERR_VALIDATION (400)

### OCC rules implemented
- **lease-amend-stale-version** on PATCH `/sugarhouse/leases/{id}`: `expected_lease_version` required, mismatch → 412
- **weather-window-declare-stale-season** on POST `/sugarhouse/weather-windows`: `expected_season_version` required, mismatch → 412; declaration increments Season.version by 1

### Storage
In-memory only: module-level dicts in `db.py` (`seasons`, `sugarbushes`, `leases`, `tap_lines`, `vacuum_readings`, `weather_windows`, `crew_members`, `sap_runs`, `batches`, `batch_intakes`, `syrup_lots`, `flavor_evaluations`, `packaging_runs`, `cert_audits`). No SQLite, no JSON files, no /tmp cache. Every boot starts completely empty; logical clock resets to `2026-05-01T00:00:00Z`. No seeding anywhere.

### Smoke boot result
- Port used: **18743** (and 18744/18745 for additional passes)
- Booted via `cd workspace/implementation && PORT=18743 bash start.sh` (backgrounded, then killed by PID)
- Endpoints curled:
  - `POST /sugarhouse/_clock/set_current_utc` → **200**, returned `{"current_utc":"2027-02-15T10:00:00.000Z"}`
  - `POST /sugarhouse/seasons` (manager auth) → **201**, PLANNED, version 1, aggregates zeroed
  - `POST /sugarhouse/seasons` (no auth) → **401** ERR_UNAUTHENTICATED
  - `POST /sugarhouse/seasons` (FieldCrew role) → **403** ERR_UNAUTHORIZED_ROLE
  - `GET /sugarhouse/seasons/{bogus-uuid}` → **404** ERR_NOT_FOUND
  - `POST /sugarhouse/seasons` (missing fields) → **400** ERR_VALIDATION
- Full lifecycle also exercised end-to-end: season → bush → line → activate → leak cascade → repair → window declare/open → crew activate → sap run → confirm → batch → manual intake + auto-fill → start-boil (est 10.17 / exp 9.92 dual yield) → finish (−59.68% variance → HELD auto-hold) → flavor eval → grade GOLDEN → packaging fill → lot EXHAUSTED → close → reconcile → RECONCILED. All worked.
- Server process killed by PID (`kill $PID`); no `pkill` used.

### start.sh contract confirmation
- **Foreground**: uses `exec python3 app.py` (PID 1 of the shell chain stays the server)
- **$PORT honored**: `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- **Binds 0.0.0.0**: explicit host arg
- **Dependency install guarded**: `if ! python3 -c "import flask"` — no-op once Flask present, safe under per-test-server reboot concurrency
- **Executable**: yes (`chmod +x`)
- **Runs from `./implementation/`**: `cd "$(dirname "$0")"` ensures cwd regardless of caller

## Step 7: Run Tests and Iterate — 2026-08-12T00:26:21.557Z

Orchestrator pre-sweep verification: implementation registers exactly the 70 (method, path) route pairs SCAFFOLD.yaml §1.5 declares — sets match exactly, no missing, no extras.

Clean exit condition reached — all 8 rounds pass 82/82 with the sweep process exited.

## Summary

- **Iterations run:** 2 (sweep 1: 81/82 across all 8 rounds with one deterministic failure; sweep 2 after fix: clean).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/test_suite/test_07_certification_compliance.py` — `test_segregation_of_duties_boiler_grades_own_lot`: added `ctx["boiler"] = grader` before the batch operations. Why: the test intentionally creates the batch with `boiled_by == grader` (PRD §3.6 "any `crew_role` may boil"), but `draw_from_run`/`start_boil`/`finish_batch` in fixtures.py act as `ctx["boiler"]` (Bob Boiler). PRD §2.1 states verbatim: "when a `SugarMaker` caller creates or operates an evaporator batch, the request's `boiled_by` field must equal `X-User-ID`" — so the implementation correctly rejected Bob Boiler drawing into Gail Grader's batch with `ERR_UNAUTHORIZED_ROLE`. Rebinding `ctx["boiler"]` to the grader makes the setup consistent with PRD §2.1 while preserving the intended assertion (`ERR_SEGREGATION_OF_DUTIES` when the grader then evaluates their own lot, PRD §3.8).
- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful (identity check enforced on batch create + all batch operations at `workspace/implementation/routes/batches.py:44,121,149,199,224,270` via `middleware.enforce_entity_identity`).
- **Final sweep evidence (per-round passed/total):** round 1: 82/82, round 2: 82/82, round 3: 82/82, round 4: 82/82, round 5: 82/82, round 6: 82/82, round 7: 82/82, round 8: 82/82.

Orchestrator post-verification: all 8 `results.{i}.json` files on disk independently parsed — every round passed=82 total=82 failed=0 errors=0.

## Step 8: Finalize PRD — 2026-08-12T00:29:20.590Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/workspace/PRD_FINALIZED.md` written with exactly one in-place revision.

**Line counts / delta:** PRD.md 344 lines, PRD_FINALIZED.md 344 lines — 0.0% delta (one line revised in place, no lines added or removed).

**Changes:**
- §2.1 — revise — split the SugarMaker batch-identity clause into two pinned cases: batch creation compares the request body's `boiled_by`; operating an existing batch (drawing/auto-filling intakes, starting the boil, finishing, cancelling) compares the batch's *persisted* `boiled_by` — `implementation/routes/batches.py:44,121,149,199,224,270` via `implementation/middleware.py:41-51`.

**Why an edit was needed (not a zero-edit outcome):** PRD §2.1's original "creates or operates an evaporator batch, the request's `boiled_by` field" admits a reading where only creation is constrained, since no operate-request carries a `boiled_by` body field — exactly the looser reading the Step 7 fixture embodied before its rebind. The implementation enforces identity on all five batch write operations against the persisted field, so the ambiguity was pinned. The Step 7 item itself was a pure test_suite fixture fix; no implementation or test_helpers changes were involved.

**Pre-edit search log (the single edit):**
- (a) Subject: SugarMaker entity-backed identity (`X-User-ID` vs `boiled_by`) on evaporator batch create/operate.
- (b) Impl paths enumerated and read/grepped: `middleware.py:41-51` (`enforce_entity_identity` — no-op for opaque roles SugarhouseManager/CertInspector); `routes/batches.py:44` (create, body field), `:121` (POST intakes, persisted `batch["boiled_by"]`), `:149` (auto-fill, persisted), `:199` (start-boil, persisted), `:224` (finish, persisted), `:270` (cancel, persisted); batch read endpoints `batches.py:59-84,182-191` (ALL_ROLES, no identity check); `routes/syrup_lots.py:57-78` (grade — role-only, no identity enforcement, correctly outside the edit's scope), `syrup_lots.py:124` (`evaluator_id` identity — clause kept verbatim), `routes/sap_runs.py:52` (FieldCrew `collected_by` — separate sentence, kept verbatim).
- (c) Wording adjustments from the search: scoped the operate-clause to "a `SugarMaker` caller" so manager callers (opaque, never compared per middleware) are not mis-described; enumerated exactly the five enforcing write operations and no reads, matching the impl's enforcement set; used "the batch's persisted `boiled_by`" rather than "the request's" for operate-requests since none carry that body field.

## Step 9: Complete PRD — 2026-08-12T00:44:27.428Z

## Summary

**PRD_COMPLETED.md exists on disk** at `/home/ubuntu/github/CodingPRD/tasks/task_1215_maple_sugarbush_syrup_production/workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md = 344 lines / 50,254 bytes → PRD_COMPLETED.md = 348 lines / 55,154 bytes (char-delta +4,900; +4 lines from two inserted paragraphs in §2.2 and §2.7; all other changes are in-paragraph). No new sections; §1–§5 structure untouched.

**Counts:** 31 changes total — 29 ambiguity-pins, 2 mismatch-revisions.

**Changes (one per bullet):**
- §2.2 — revise — mismatch — `api_request_timestamp` pinned as server wall clock, explicitly not the logical clock — response.py:19-24
- §2.2 — insert — ambiguity — undefined route/unsupported method → `ERR_NOT_FOUND` 404; non-JSON body → `ERR_VALIDATION` 400 — app.py:42-52, util.py:123-130
- §2.3 — revise — ambiguity — limit/offset must be integers, offset ≥ 0, filters narrow before pagination, `total_count` is post-filter, list ties broken by `id`, `has_more` = offset + returned rows < total_count — util.py:93-118, response.py:40
- §2.4 — revise — ambiguity — `version` starts at 1 — services/core.py:51
- §2.4 — revise — mismatch — clock-set parsing pinned (any ISO 8601, missing offset read as UTC, normalized); entity timestamps logical-stamped; envelope `api_request_timestamp` named the wall-clock exception (replacing the vacuous "envelope's `created_at`" claim) — routes/clock.py:21-26, util.py:30-40
- §2.5 — insert — ambiguity — quantities serialize as JSON numbers, never strings — util.py:79-88
- §2.6 — insert — ambiguity — `expected_lease_version` required, integer, else `ERR_VALIDATION` — routes/leases.py:145-149
- §2.6 — insert — ambiguity — `expected_season_version` required, integer, else `ERR_VALIDATION` — routes/weather_windows.py:37,44-46
- §2.7 — insert — ambiguity — ordering refinements: malformed body rejected at body-read (after auth + path-id resolution); create endpoints finish field validation before body FK lookups (weather-windows resolves `season_id` first); OCC integer check precedes version compare; SoD precedes organic-handling within category 6 — all routes; weather_windows.py:40-49; syrup_lots.py:143-156
- §3.1 — revise — ambiguity — `year` integer; `YYYY-MM-DD` dates; `closes_on` may equal `opens_on` — routes/seasons.py:35-45
- §3.1 — revise — ambiguity — run-sweep invocable in any season status — routes/seasons.py:165-191
- §3.2 — revise — ambiguity — vacuum reading accepted in any line status (incl. INSTALLING/LEAK/PULLED) — routes/tap_lines.py:154-186
- §3.2 — revise — ambiguity — `latest_vacuum_inhg` null until first reading — services/core.py:113
- §3.2 — revise — ambiguity — repair with no readings → `ERR_VACUUM_STILL_LOW` — routes/tap_lines.py:129-130
- §3.3 — revise — ambiguity — `closes_at`-after-`opens_at` checked after version guard, before freeze-thaw/overlap; declaration not season-status gated; instants stored/returned UTC-normalized — routes/weather_windows.py:29-89
- §3.3 — revise — ambiguity — collector's season not cross-checked; field validation before `collected_by` identity and FK lookups — routes/sap_runs.py:43-63
- §3.3 — revise — ambiguity — confirm uses the `ERR_SEASON_NOT_OPEN`/`ERR_SEASON_SUSPENDED` split — routes/sap_runs.py:137-140
- §3.3 — insert — ambiguity — re-voiding a VOIDED run → `ERR_INVALID_STATE` — routes/sap_runs.py:152-153
- §3.4 — revise — ambiguity — term dates `YYYY-MM-DD`; `per_tap_cents` integer > 0; all create-time field validation before bush lookup; new-lease defaults (`taps_snapshot`/`settled_royalty_gallons` null, accrued fields zero) — routes/leases.py:51-106, services/core.py:85-103
- §3.4 — insert — ambiguity — amend: absent fields unchanged; basis switch requires new basis's royalty field explicitly in the same request; term ordering re-validated on amended values — routes/leases.py:159-245
- §3.5 — revise — ambiguity — crew activation SUSPENDED split — routes/crew.py:87-90
- §3.6 — revise — ambiguity — `evaporator_capacity_gal` integer > 0; creation not season-status gated; boiler's season not cross-checked; new batch's seven computed fields null — routes/batches.py:31-56, services/core.py:171-187
- §3.6 — revise — ambiguity — `draw_sequence` starts at 1, +1 per intake; auto-fill only while FILLING, `target_gallons` > 0, responds with updated batch — routes/batches.py:87-90,139-179
- §3.6 — revise — ambiguity — intake `effective_brix` null until boil starts — services/core.py:199
- §3.6 — revise — ambiguity — new lot's `grade`/`light_transmittance_pct` null — services/core.py:211-212
- §3.6 — insert — ambiguity — finish response carries the updated batch — routes/batches.py:262
- §3.7 — revise — ambiguity — provisional accrual only onto leases in ACTIVE/TERMINATED/EXPIRED — services/core.py:474-477
- §3.8 — revise — ambiguity — evaluator's season not cross-checked; integer `flavor_score`; `defect_flags` list of strings; evaluations recordable on UNGRADED/HELD/GRADED, rejected on CONDEMNED/EXHAUSTED with `ERR_LOT_NOT_GRADABLE` — routes/syrup_lots.py:109-137
- §3.8 — revise — ambiguity — manager-placed hold does not set `quality_hold_auto` (written only at lot creation) — routes/syrup_lots.py:81-91, services/core.py:214
- §3.9 — revise — ambiguity — `units_filled`/`filled_gallons` null until fill — services/core.py:239-240
- §3.10 — revise — ambiguity — `scheduled_for` `YYYY-MM-DD`; `result` null until recorded — routes/cert_audits.py:33-37, services/core.py:252

Method notes: the subagent walked all 12 route modules plus `services/core.py`, `middleware.py`, `response.py`, `util.py`, `errors.py`, `app.py` endpoint-by-endpoint against every PRD passage (states, gates, rollups, formulas, rounding, OCC, error mapping, response shapes, defaults, ordering). Endpoint table §4 and error catalogue §5 matched impl exactly; tests were used only as cross-reference (e.g. run-sweep `closes_at <= clock` inclusivity), never as authority. The two true mismatches both concerned the envelope timestamp (PRD implied logical-clock stamping; impl uses wall clock).
