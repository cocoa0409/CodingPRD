# Worklog — task_1201_tank_cleaning_terminal_services

## Step 1: Create task directory — 2026-08-11T19:23:00.000Z

Pre-assigned output folder `tasks/task_1201_tank_cleaning_terminal_services` with `workspace/` subdirectory already exists (per orchestration instructions). Step 1 auto-index scan skipped as instructed; directory verified present and empty.

## Step 2: Generate scaffold — 2026-08-11T20:27:00.000Z

Scaffold generation complete. All three artifacts are on disk and lint-clean.

**Files** (under `/home/ubuntu/github/CodingPRD/tasks/task_1201_tank_cleaning_terminal_services/`):
- `SCAFFOLD.yaml` — 110,180 bytes (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 115,941 bytes (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 196,344 bytes (single top key `scaffold_corner_design`)

**Counts**
- Entities: 16 (flat topology under `/ops`, all FKs canonical with reverse-reachability GETs)
- State machines: 12 (CleaningJob 18-state cyclic with rework loop, pause/resume + recovery edge; EntryPermit parallel status×atmosphere dims; cyclic WasteProfile/Inspection/RepairOrder/WastewaterBatch/Contractor; system-swept cert expiry and window OVERRUN)
- Calculations: 12 (incl. dual-variant sludge estimate + contractor score; combinatorial modes (a) flush min/max tiers, (b) pinned per-line waste rounding, (c) circular-looking invoice tier order)
- Validations: 33 (priorities 1–33; state<OCC<safety<temporal<referential<constraint<fiscal)
- Endpoints: 107 (incl. `POST /ops/_clock/set_current_utc` with mandated default 2026-05-01T00:00:00Z)
- Errors: 35 (all referenced by ≥1 validation or transition)
- Roles: 7 (segregation-of-duties model; ContractorSupervisor and API653Inspector entity-backed; 4 SoD user-id pairings)
- §1.8: 19 instances (9 rules, ≥2 each; combinatorial has 3); 1,278 total recipe calls lint-verified
- §1.9: 64 instances (52 active + 12 `excluded_because` stubs) across all 9 guide sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Two issues found and fixed during the audit: an unreachable `ERR_INSPECTION_NOT_ACCEPTED` (removed, priorities renumbered, §1.8 grounds updated, plus a `PAUSED → GAS_FREE_PENDING` recovery edge added so permit-resume errors stay reachable), and a missing `window_id?` filter on `GET /ops/cleaning-jobs`. Name uniqueness, forbidden-vocabulary, and grounds-resolvability checks all pass.

## Step 3: Copy shared files — 2026-08-11T20:28:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1201_tank_cleaning_terminal_services/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-11T20:45:00.000Z

PRD generation complete. The output file exists at `/home/ubuntu/github/CodingPRD/tasks/task_1201_tank_cleaning_terminal_services/workspace/PRD.md` — 61,012 bytes, 369 lines.

## Section list

- **§1. Introduction** (2 paragraphs: business context + platform scope)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (7 roles, entity-backed identity prose for `ContractorSupervisor`/`API653Inspector`, opaque for the rest)
  - 2.2 API Response Structure (emitted byte-for-byte verbatim from `section-2.2-response-structure.md` — verified)
  - 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields)
  - 2.4 Resource Identity, Timestamps, and Versioning (incl. append-only `SafetyEvent` exception)
  - 2.5 The Logical Clock and Time-Driven Sweeps (startup default 2026-05-01T00:00:00Z, cert-expiry and window-OVERRUN sweeps)
  - 2.6 Optimistic Concurrency Control (all 3 OCC rules with exact `expected_*_version` fields, `ERR_STALE_VERSION`/412)
  - 2.7 Units, Precision, and Rounding Discipline (incl. pinned per-line rounding and invoice waterfall rounding)
  - 2.8 Scheduling Intervals and Calendar Discipline (half-open intervals, 24h tank buffer, overlap-before-buffer, inspector adjacency)
  - 2.9 Atmospheric Safety Envelope and Certificate Validity (strict/inclusive bounds, 12h + one 6h revalidation)
  - 2.10 Segregation of Duties (all 4 segregated hand-offs)
  - 2.11 Validation Order and Error Semantics (global 5-layer pipeline)
- **§3. Business Logic & Workflows** (9 subsections: terminal landscape; contractor governance/safety score; window booking; job draft/schedule; heel/sludge/waste; gas-free/entry/permits/pause-resume; inspection/findings/repair/rework; flush/mass-balance/RTS/cancellation; wastewater)
- **§4. Endpoint Definitions** (107-row table, 4 columns only)
- **§5. Error Code Catalogue** (35-row table, 2 columns only)

## Line count
369 lines (61,012 bytes).

## Zero-Silence Rule audit (Hard Contracts 1–3): all three hard contracts PASS (field coverage 77/77 + 64/64 + 18/18; rule coverage incl. all 33 validations, 3/3 OCC, all state-machine transitions/cascades, 12/12 calculations; path purity: 581 backtick tokens in §3, 0 path tokens). No sibling tasks or withheld design files were consulted.

## Step 5: Generate unit tests — 2026-08-11T21:18:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files): `__init__.py` (barrel export), `types.py` (15 entity TypedDicts + 16 enums; SafetyEvent correctly omits `updated_at`/`version` per common_fields:false), `api_client.py` (ApiClient subclassing GenericApiClient, one method per endpoint incl. `/ops/_clock/set_current_utc`), `api_errors.py` (35 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity structural assertions, lenient on nullable computed fields), `factories.py` (input-field-only payload factories), `constants.py` (all PRD calculation thresholds), `test_users.py` (shared opaque-role headers + mandatory `make_contractor_supervisor_headers`/`make_inspector_headers` builders for the two entity-backed roles), `fixtures.py` (composable ctx-chain: `new_ctx` → `create_job` → `schedule_job` → `activate_window_and_take_oos` → `record_heel` → `create_approved_profile` → `add_shipment` → `record_sludge` → gas-free/cert → `add_permit` → entry → inspection → flush → RTS; composite stages through `setup_ctx_rts_pending`; OCC versions always re-fetched, never hard-coded).

**`test_suite/`** (14 files): `conftest.py` + `test_01_…` through `test_13_…` grouped by concern (config/envelope, contractor governance, windows, job draft/schedule, calculations, waste, gas-free/entry, inspection/repair, cascades/rework, wastewater, RBAC, OCC/consistency).

## Counts
- **Total tests: 93** (pytest collects cleanly; all files compile)
- **Queue A (Difficulty): 42 tests / 19 instances** — every instance has ≥2 tests
- **Queue B (Corner): 51 tests / 51 non-stub instances** — every non-stub instance has ≥1 test
- **12 corner stubs** correctly not translated; all 12 `difficulty_instance` cross-references resolve

## Skipped instances (1)
- `Corner/entities/job_computed_field_input_ignored` — PRD never states that client-supplied values for computed fields are ignored; an implementer could faithfully reject unknown fields with 400 instead (unique-derivability failure). Not weakened, not emitted.

## Notable PRD-faithfulness adaptation
- `Difficulty/dual_variant_calc/contractor_score_rolling_vs_lifetime`: the recipe's second `qualify` call on an already-QUALIFIED contractor would hit the state-transition layer (qualify is defined only from APPLICANT), not the score error. Translated as three isolated tests instead: ROLLING variant → QUALIFIED at 97.00 (old INCIDENT excluded), LIFETIME variant → QUALIFIED at 87.00 (all events counted), LIFETIME with threshold 90 → `ERR_CONTRACTOR_NOT_QUALIFIED`.

## Stage 2 tag audit
- 93/93 test docstrings end with exactly one `Design:` line as the final line; 0 untagged, 0 dual-tagged, 0 unresolved tags
- 128 PRD citations extracted from docstrings — 100% survive whitespace-normalized literal grep of `PRD.md`
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; gaps stay gaps

## Step 6: Generate implementation — 2026-08-11T21:18:00.000Z

Done. Implementation complete and verified.

## Summary

**Output directory**: `/home/ubuntu/github/CodingPRD/tasks/task_1201_tank_cleaning_terminal_services/workspace/implementation/`

**File list** (sizes in bytes):
| File | Size | Role |
|---|---|---|
| `start.sh` | 396 | Launcher (executable) |
| `requirements.txt` | 11 | `flask>=2.2` |
| `app.py` | 1,286 | Flask app, blueprint registration (`url_prefix="/ops"`), envelope-shaped 404/405/error handlers, `0.0.0.0:$PORT` (default 10000) |
| `core.py` | 10,521 | In-memory `Store`, logical clock (default 2026-05-01T00:00:00Z), response envelope, error catalog constants, auth (`X-User-ID`/`X-User-Role`, 7 roles), pagination (`limit`/`offset`/`total_count`/`has_more`), validation helpers |
| `calc.py` | 6,273 | All §1.3 calculations with `Decimal` + ROUND_HALF_UP/CEILING (sludge estimate, safety score with ROLLING_12MO/LIFETIME variants, flush volume, changeover matrix, per-line pinned disposal rounding, invoice waterfall, mass balance, gas-free limits) |
| `services.py` | 5,316 | Cascades: cert-death (permits suspend → job PAUSED or → GAS_FREE_PENDING → inspections cancel), permit-suspend pause, RTS-gate revert, shipped-solids/waste-cost recomputes, clock sweeps (cert EXPIRED, window OVERRUN) |
| `routes_registry.py` | 10,112 | Terminals, products, tanks, contractors (+qualify/suspend/reinstate/bar), safety events, inspectors, `_clock/set_current_utc` |
| `routes_jobs.py` | 25,598 | CleaningJob full lifecycle (18 routes) + ServiceWindow calendar (OCC, overlap/24h-buffer) |
| `routes_waste.py` | 9,815 | WasteProfile review cycle + reclassify cascade; WasteShipment conveyor |
| `routes_entry.py` | 11,770 | GasFreeCertificate issue/revalidate/revoke; EntryPermit lifecycle + parallel atmosphere dimension |
| `routes_inspect.py` | 12,624 | Inspection booking (inspector OCC, adjacency allowed), findings, repair-order cycle |
| `routes_wastewater.py` | 6,108 | WastewaterBatch lab/authorize/discharge with SoD and daily-capacity bucket |

**Verification results**:
1. **Route table**: 107 declared (method, path) pairs in SCAFFOLD.yaml §1.5 vs 107 registered Flask routes — **exact match, zero missing, zero extra** (programmatic diff). [Orchestrator re-verified against live `app.url_map`: 107 declared vs 107 registered non-static routes, exact match; only extra is Flask's built-in `/static/<path:filename>` default.]
2. **Syntax**: `py_compile` passes on all 10 `.py` files.
3. **start.sh contract**: reads `$PORT` (default 10000), binds `0.0.0.0`, runs in foreground via `exec`, dependency install guarded by `python3 -c "import flask"` so per-test reboots skip pip.
4. **Isolation**: fresh-process boot confirmed — all 16 collections return `total_count=0`, clock at the spec'd default, no SQLite/JSON/tmp persistence anywhere (dicts only, no seeding).
5. **Behavioral smoke**: ~150 end-to-end checks passed against live boots, covering the full happy path (terminal→tank→contractor→window→job→heel→profile→shipment→sludge→cert→permit→entry→inspection→finding→repair→accept→flush→RTS→invoice→return-to-service) plus edge paths: OCC 412s, overlap-before-buffer ordering, adjacency rules (blocked on tanks, allowed on inspectors), strict/inclusive gas-free bounds, SoD on all four segregated hand-offs, cert revoke/expiry cascades (both PAUSED and GAS_FREE_PENDING branches), manual-suspend pause with gated resume, rework loop, reclassify→void→RTS-revert cascade, LIFETIME vs ROLLING_12MO scoring, discharge limits/capacity, invoice tiers, and envelope/pagination shape.

One bug was caught and fixed during verification: `services.py` referenced `db.jobs` instead of `db.cleaning_jobs` (3 sites), which broke the clock sweep. All checks pass after the fix.

## Step 7: Run tests and iterate — 2026-08-11T21:35:00.000Z

Clean sweep: all 8 rounds pass 93/93 with zero failures and zero errors.

## Summary

**Iterations run:** 2 (initial sweep surfaced 7 deterministic failures, identical across all 8 rounds; fix round; verification sweep clean 8/8).

**Tests deleted:** None.

**Fixes applied to `test_suite/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1201_tank_cleaning_terminal_services/test_suite/test_06_calculations.py` — added missing `setup_ctx_flush_verified` to the `from test_helpers import (...)` list. Three `TestJobInvoiceWaterfall` tests referenced the fixture without importing it (`NameError`). The fixture itself was correct and exported from `test_helpers`; PRD §3.8 verbatim-covers the tier rules asserted.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1201_tank_cleaning_terminal_services/test_suite/test_03_contractor_governance.py` — `TestThresholdBoundary` (both tests): the setup recorded a `VIOLATION` with `severity_weight=15`, violating PRD §3.2's verbatim bound "a `severity_weight` that is an integer from 1 to 10 inclusive", so the PRD-faithful implementation correctly returned `ERR_INVALID_REQUEST`. Rebuilt the 15.00-point deduction from two in-range events (10 + 5), preserving the exact asserted scores (85.00 at-threshold, 84.75 below). STEP 2 fixture-side fix; no assertion weakened.

3. `/home/ubuntu/github/CodingPRD/tasks/task_1201_tank_cleaning_terminal_services/test_suite/test_08_gas_free_and_entry.py` — `test_active_permit_blocks_complete_entry_and_cancel`: the cancel assertion expected `ERR_JOB_HAS_ACTIVE_PERMIT` from `ENTRY_IN_PROGRESS`, but PRD §3.8 defines cancellation only from `DRAFT/SCHEDULED/TANK_OOS/HEEL_REMOVED/SLUDGE_REMOVED/GAS_FREE_PENDING/GAS_FREE_CERTIFIED/PAUSED` ("from any other status the request is an invalid transition") and scopes `ERR_JOB_HAS_ACTIVE_PERMIT` verbatim to "From `GAS_FREE_CERTIFIED` or `PAUSED`, a job holding any `ACTIVE` entry permit…". The test's docstring had also misquoted PRD by dropping that state scoping. Fixed the test to keep the PRD §3.6-covered `ERR_PERMITS_NOT_CLOSED` completion assertion at `ENTRY_IN_PROGRESS`, and to exercise the cancel gate from `GAS_FREE_CERTIFIED` with an `ACTIVE` permit (corrected docstring quote included).

**Fixes applied to `implementation/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1201_tank_cleaning_terminal_services/workspace/implementation/routes_registry.py` — `_score_gate`: the qualification gate computed the score under the terminal's `score_variant` but discarded it, returning the stored field that `refresh_contractor_score` maintains under the default `ROLLING_12MO`. Per PRD §3.2 ("the contractor's score is computed under that terminal's variant"; "under `LIFETIME` every event counts regardless of age"), `_score_gate` now persists the per-terminal computed score onto `contractor["safety_score"]`, so the qualify/reinstate response carries the score actually evaluated (87.00 under `LIFETIME` vs 97.00 under `ROLLING_12MO` for the same history). No PRD-required check was removed or weakened; storage remains in-memory only.

**Final state:** 8/8 parallel rounds, each 93 passed / 93 total, 0 failed, 0 errors.

**Orchestrator verification:** read all 8 `results.{i}.json` from disk — each shows passed=93/93, failed=0, errors=0.

## Step 8: Finalize PRD — 2026-08-11T21:40:00.000Z

Both files are 368 lines (in-place line revisions, 0% line-count delta). Done.

## Summary

**Line counts:** PRD.md = 368 lines; PRD_FINALIZED.md = 368 lines; 0% delta (two in-place sentence revisions, no lines added or removed).

**Changes (one edit, two sentence revisions within §3.2):**

- **§3.2 — revise —** "Every event write recomputes the contractor's score." now also pins that the stored `safety_score` field is refreshed at that moment under the default `ROLLING_12MO` variant, regardless of any terminal's pinned variant — `implementation/services.py:16-21` (`refresh_contractor_score` hard-codes `"ROLLING_12MO"`), called from `implementation/routes_registry.py:268`.
- **§3.2 — revise —** qualification/reinstatement paragraph now pins that on success the score just computed under the named terminal's variant is stored back onto the contractor's `safety_score` field, so the response carries exactly the evaluated score — `implementation/routes_registry.py:175-184` (`_score_gate`, the Step 7 impl fix), exercised by qualify (line 197) and reinstate (line 226).

**Step 7 diff items not resulting in edits (with verification):**
- Test fix 1 (`test_06_calculations.py` import): pure test-code bug, no PRD semantics.
- Test fix 2 (`test_03_contractor_governance.py` severity_weight 15): fixture violated PRD §3.2's verbatim 1–10 bound; impl enforces it at `routes_registry.py:258-260`. PRD already correct.
- Test fix 3 (`test_08_gas_free_and_entry.py` cancel from `ENTRY_IN_PROGRESS`): impl at `routes_jobs.py:480-490` matches PRD §3.8 verbatim — cancel defined only from the eight listed states (`ERR_INVALID_STATE_TRANSITION` otherwise) and `ERR_JOB_HAS_ACTIVE_PERMIT` explicitly scoped to `GAS_FREE_CERTIFIED`/`PAUSED`. PRD wording is unambiguous; no edit.

**Pre-edit search log (mandatory for the edit):**
- (a) Subject: the semantics of the contractor's stored `safety_score` field — when it is written, and under which score variant.
- (b) Enumerated impl paths (all read/grepped): `routes_registry.py:142-153` (create → 100.00); `routes_registry.py:175-184` (`_score_gate` — computes under terminal variant, persists on success); `routes_registry.py:187-200` (qualify) and `216-229` (reinstate) — the only two `_score_gate` callsites; `routes_registry.py:248-269` (safety-event create → `refresh_contractor_score`); `services.py:7-21` (`contractor_score`, `refresh_contractor_score` — stored recompute always `ROLLING_12MO`); `routes_jobs.py:160-189` (schedule gate — computes under terminal variant for the threshold check but never writes the field); `calc.py:108-130` (pure computation, no storage).
- (c) Wording adjustment: scoped the store-back sentence to "On a successful qualification or reinstatement" only, and scoped the event-write refresh to "the default `ROLLING_12MO` variant" — because the schedule gate (`routes_jobs.py:173-177`) evaluates the per-terminal variant without persisting it, and event writes ignore terminal variants entirely. A broader claim (e.g., "the stored score always reflects the evaluating terminal's variant") would have mis-described both paths.

## Step 9: Complete PRD — 2026-08-11T21:48:00.000Z

Done. PRD_COMPLETED.md exists at `/home/ubuntu/github/CodingPRD/tasks/task_1201_tank_cleaning_terminal_services/workspace/PRD_COMPLETED.md` with all 14 edits applied inline. (Note: the first Step 9 subagent turn was truncated before writing the file; a resumed continuation applied all 14 edits and emitted this summary. Orchestrator verified on disk: 368 lines, 64,458 chars, diff vs PRD_FINALIZED.md = 42 changed lines.)

## Exit summary

**File stats**: PRD_FINALIZED.md = 368 lines / 61,447 chars; PRD_COMPLETED.md = 368 lines / 64,458 chars. Char-delta = **+3,011**. Line count unchanged (all changes are in-paragraph inserts/revisions; no new sections).

**Counts**: 9 ambiguity-pins, 5 mismatch-revisions (14 change units total).

**Changes**:

- §2.3 — insert — ambiguity — pinned pagination-parameter validation failures (`ERR_INVALID_REQUEST` 400 for non-integer limit/offset, limit outside 1–100, negative offset), `created_at` tie-break by creation sequence, and exact-equality filter semantics — `implementation/core.py:202-245` (paginate/apply_filters), `core.py:233-235` (sorted_all).
- §2.4 — insert — ambiguity — pinned initial `version` = 1 at creation and `updated_at` == `created_at` at creation — `implementation/core.py:128-136` (create_entity).
- §2.5 — insert — ambiguity — clock set unconditionally to any supplied instant (no monotonicity), sweeps run on every set with certificate sweep before window sweep, unlinked `ACTIVE` window treated as not-returned-to-service, and naive (offset-less) timestamps interpreted as UTC — `implementation/routes_registry.py:319-328` (set_clock), `services.py:119-136` (sweep_clock), `core.py:107-122` (parse_dt).
- §2.9 — revise — mismatch — qualified the blanket `ERR_NO_VALID_GAS_FREE_CERT` rule: at entry-permit activation and resumption, every anchoring-certificate failure (missing, non-VALID, or expired) is `ERR_CERT_EXPIRED` — `implementation/routes_entry.py:208-211`, `241-244`.
- §2.11 — revise — mismatch — corrected the pipeline order to match impl: auth → role admission → path-id existence (left-to-right) → body field-shape validation (required/type/enum/interval) → body-FK existence → entity-backed ownership → OCC → state legality → business rules; numeric range checks applied where each endpoint reads the value — e.g. `implementation/routes_jobs.py:217-224` (existence before ownership, negativity after state), `routes_registry.py:253-260` (shape before FK existence, weight range after).
- §3.1 — revise — mismatch — product `code` and tank `tank_number` uniqueness are conventional only; the server does not enforce either — `implementation/routes_registry.py:67-80` (create_product), `99-118` (create_tank).
- §3.2 — insert — ambiguity — `severity_weight` 1–10 range check applied after contractor existence; a failed qualification leaves the stored `safety_score` unchanged — `implementation/routes_registry.py:257-260`, `175-184` (_score_gate raises before assignment).
- §3.4 — insert — ambiguity — negative `heel_volume_liters_sounding`/`base_service_fee_cents` and non-boolean `lines_included` rejected with `ERR_INVALID_REQUEST` at draft; the scheduling score check does not write the computed score back to the contractor record — `implementation/routes_jobs.py:51-59`, `171-177`.
- §3.5 — insert — ambiguity (x3 in one edit set) — metered-liter negativity check applied after the `TANK_OOS` state check; shipment line `kg`/`rate_cents_per_kg` must be non-negative; clarified that `DELIVERED`→`VOIDED` occurs both by direct call and via the reclassification cascade (RECONCILED never voided) — `implementation/routes_jobs.py:221-223`, `routes_waste.py:163-169`, `266-279`.
- §3.6 — revise — mismatch — atmosphere auto-clear path: only revalidation of the permit's own anchoring certificate returns `RETEST_REQUIRED` permits to `CLEAR`; a superseding certificate never re-anchors permits (`cert_id` is immutable for the permit's life) and does not clear atmospheres — `implementation/routes_entry.py:100-108` (revalidate), `46-50` (create_cert supersedes without touching permits).
- §3.6 — insert — ambiguity — revalidation and revocation are defined only from `VALID` (any other status is an invalid transition); requesting gas-free from `PAUSED` while a `VALID` certificate exists fails as an invalid transition — `implementation/routes_entry.py:92-93`, `117-118`, `routes_jobs.py:278-283`.
- §3.7 — insert — ambiguity — "the accepted inspection" (for rework, flush, and RTS gates) means the most recently accepted inspection when several exist across rework cycles — `implementation/services.py:105-111` (accepted_inspection takes max by `_seq`).
- §3.8 — insert — ambiguity — return-to-service moves the linked window to `COMPLETED` whether it stood `ACTIVE` or had already been swept to `OVERRUN` — `implementation/routes_jobs.py:434-437`.
- §3.9 — insert — ambiguity — batch `volume_liters` > 0 check applied after existence and ownership; submit-lab pH/TPH range validation runs before the `COLLECTED` state check — `implementation/routes_wastewater.py:26-31`, `70-77`.
