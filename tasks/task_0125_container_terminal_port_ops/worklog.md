# Worklog — task_0125_container_terminal_port_ops

## Step 1: Create task directory — 2026-06-03T12:38:41.000Z

Task directory pre-allocated at `tasks/task_0125_container_terminal_port_ops` with empty `workspace/` subdir. Did not scan ./tasks/ for next index; used the provided pre-allocated directory. Difficulty: Expert.

## Step 2: Generate scaffold — 2026-06-03T13:05:00.000Z

Generated a complete, lint-clean Expert-level scaffold package. All three files written (SCAFFOLD.yaml §1.0–§1.7, SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8, SCAFFOLD_CORNER_DESIGN.yaml §1.9).

**Complexity profile:** primary archetype temporal_windowing + secondary quota_allocation; flat topology; branching state-machine shape; peer_roles; layers = cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency.

**Structural counts (Expert band):**
- Entities: 11 — Berth, Vessel, BerthWindow, Container, YardSlot, GateAppointment, CustomsHold, ReeferReading, EquipmentInterchangeReceipt, DemurrageInvoice, Clock
- State machines: 4 — BerthWindow (revert cycle BERTHED↔SCHEDULED), Container (parallel customs_status × handling_status dimensions with branching customs), GateAppointment (cyclic NO_SHOW↔BOOKED), DemurrageInvoice
- Calculations: 6 — demurrage_charge (tiered, dual-variant), berth_clash_check (half-open intervals), gate_slot_clash_check (buffered intervals), dwell_time_hours, reefer_excursion_flag, reefer_excursion_summary
- Endpoints: 47 (includes 13 FK reverse-reachability GETs forcing count above 20–32 nominal band — accepted per FK-reachability guidance, lint-clean)
- Error catalog: 18
- Roles: 6 (TerminalAdmin, BerthPlanner, YardPlanner, GateOperator, CustomsOfficer, ReeferTechnician — all opaque, peer-role model)
- Concurrency rules: 2 OCC (berth-window berth, container customs-clear)

**§1.8 Difficulty Design:** 18 instances = all 9 rules × 2.
**§1.9 Corner Design:** 55 instances = 50 active + 5 `excluded_because` stubs across all 9 claim-extraction-guide sections.

**Verification:** scaffold_lint.py reports VERDICT: clean lint (514 calls conform to §1.5; all 13 FKs reverse-reachable). All 18 errors triggerable; both OCC endpoints take expected_*_version and bump version; validation priorities unique/sorted 1–18; all formula-derived asserts pre-computed as literals (demurrage tier-straddle = 59000 cents/8 days, dwell = 60.5h, reefer excursion count=2/max-dev=2.5).

## Step 3: Copy INSTRUCTION.md — 2026-06-03T13:06:41.000Z

Copied ./INSTRUCTION.md → tasks/task_0125_container_terminal_port_ops/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-03T13:13:07.000Z

PRD generated at workspace/PRD.md (271 lines).

**Major sections:** §1 Introduction; §2 Global Specifications (RBAC, response structure, pagination, logical clock & half-open intervals, common resource properties, precision/rounding, OCC, validation precedence, state cascades, yard stacking safety); §3 Business Logic (8 subsections: provisioning, berth-window scheduling/working, containers & parallel state, gate flow, customs holds/clearances, demurrage accrual/invoicing, dwell time, reefer monitoring); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Documented counts:** 10 entities + Clock; 48 endpoint rows; 18 errors; 6 roles (TerminalAdmin, BerthPlanner, YardPlanner, GateOperator, CustomsOfficer, ReeferTechnician), all opaque identity.

**Hard Contract reports:** Field coverage PASS (48/48 entity fields, 34/34 request bodies, 8/8 query params); Rule coverage PASS (18 validations, 2 OCC, 4 state machines, 6 calculations); Path purity PASS (0 path tokens in §3).

**Confirmation:** doc-generator did not read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml — PRD generated solely from SCAFFOLD.yaml.

## Step 5: Generate unit tests — 2026-06-03T13:30:14.000Z

Generated complete test infrastructure by translating the two design indices, PRD-first.

**Counts:** 9 test files (test_01–test_09 under test_suite/) plus conftest.py. 86 test functions total: 36 from queue A (§1.8 Difficulty) + 50 from queue B (§1.9 Corner).

**Coverage (both audits pass):** Queue A — all 18 difficulty instances (9 rules × 2) each have exactly 2 tests. Queue B — all 50 non-stub corner instances each have ≥1 test. The 4 `excluded_because:` stubs NOT translated; all four cross-references resolve to real §1.8 instances.

**Instances SKIPPED for PRD-first filter:** Zero. Every non-stub instance survived the two-condition filter — PRD prose (§2.7, §2.8, §3.1–§3.8) verbatim-covers and uniquely-derives every asserted rule, including the two precedence pairs (cross-entity-state beats slot-occupied on ground; invalid-state beats stacking on gate-out).

**Verification:** 86 tests collect cleanly; all helpers/suite py_compile OK; every docstring carries exactly one Design: tag; every PRD-quoted citation matches verbatim; no scaffold-leakage strings; no skip/skipif/xfail markers.

**test_helpers/ files:** __init__.py, types.py, api_client.py (51 endpoint methods), api_errors.py (18 errors), assertions.py, factories.py, constants.py, test_users.py (6 opaque-role headers), fixtures.py.

## Step 6: Generate implementation — 2026-06-03T13:30:14.000Z

Built complete Python + Flask implementation at workspace/implementation/.

**Source files (17):** start.sh (foreground, sentinel-guarded pip, exec python3 app.py), requirements.txt (flask==3.0.3), app.py (blueprint registration, error handlers, bind-retry loop, 0.0.0.0:$PORT), db.py (10 in-memory dicts, logical clock, calc constants), errors.py (18 error-IDs), response.py, middleware.py (@require auth+RBAC), routes/ (9: clock, berths, vessels, berth_windows, containers, yard_slots, gate_appointments, customs_holds, demurrage_invoices), services/ (7: common, serialize, lookups, demurrage, clash, metrics, __init__).

**Endpoints:** 47 implemented (exact scaffold match), all 6 roles, all 18 error codes.

**State machines & calculations:** Per-route precondition gates then side-effect blocks, validated in PRD precedence order (auth → path → FK → shape → uniqueness → state → cross-entity → safety → temporal → OCC). BerthWindow (SCHEDULED↔BERTHED revert, DEPARTED/CANCELLED); Container two parallel dimensions (handling ON_VESSEL→GROUNDED→GATED_OUT, customs PENDING→{HELD,CLEARED}); GateAppointment cyclic NO_SHOW↔BOOKED; DemurrageInvoice. Demurrage = integer cents, marginal day-bucket tiers (3×5000, 4×8000, then 12000), ceil partial-day (8-day=59000, 11-day=95000 verified). free_time_expires_at derived on read from discharge window actual_berth_at + free_time_days, reverts to null on unberth. Clash: half-open berth (adjacency allowed) vs buffered gate (30-min trailing, adjacency conflicts). Dwell/reefer use Decimal ROUND_HALF_UP (2dp dwell, 1dp max-dev; strict >2.0 excursion). OCC on berth (expected_berth_window_version) and customs-clear (expected_container_version) → 412 ERR_STALE_VERSION; EIRs and reefer readings append-only.

**Boot-contract confirmation:** start.sh reads $PORT (default 10000), binds 0.0.0.0, runs foreground via exec, guards pip with `python3 -c "import flask"`. In-memory dicts only — no SQLite/JSON/tmp. Verified fresh boots: all stores empty, clock defaults 2026-01-01T00:00:00.000Z, no seeded data.

## Step 7: Test & iterate to green — 2026-06-03T13:38:00.000Z

Two consecutive clean 8-round sweeps (16 rounds total), all 86/86. The infra flake is gone.

**Iterations run:** 3 sweeps (1 baseline + 2 confirmation). Baseline showed a consistent 85/86, with the single failure rotating between two test_03_yard_grounding.py tests across rounds.

**Diagnosis:** Failures were never a test-logic or implementation-logic problem. In every round the message was `API server ... could not be restarted before ...test_03_yard_grounding.py::...`, and the failing test always burned ~15.35s — the harness's full 15s restart-poll window. Known same-port bind-race under per-test-server isolation: harness SIGKILLs the prior server and immediately relaunches on the same port; the old listener's socket lingers a few hundred ms → fresh bind hit EADDRINUSE. The pre-existing app.py mitigation used a probe-bind-then-close pattern with a TOCTOU gap and could stall past the window under 8× concurrent CPU load.

**Tests deleted:** None. Both flaky tests are PRD-faithful (cite PRD §3.3 verbatim; request/identity/payload consistent with PRD role-to-resource model) — failure was purely infra, so STEP 1/2 keep them.

**Fixes applied to implementation/:**
- workspace/implementation/app.py — replaced fragile `_wait_for_port_free` probe (bind throwaway socket, close, then let Flask bind — TOCTOU race) with `_serve()`, which retries the actual `werkzeug.serving.make_server()` bind on OSError/EADDRINUSE (80 × 0.1s) then `serve_forever()`. Real bind retried directly, closing the race deterministically. Removed unused `socket` import.

**Fixes applied to test_helpers/:**
- test_helpers/api_client.py — added an `_request` override on this task's ApiClient that sets `Connection: close` and retries once on requests.ConnectionError. Defensive against the second known per-test-server flake (keep-alive pool reusing a socket to a just-killed server → intermittent BadStatusLine/ConnectionError). No assertion/test behavior changed.

**Final sweep (subagent):** Two back-to-back 8-round parallel sweeps (16 rounds), every round passed == total == 86. Test total: 86.

Note: both fixes are infrastructure-only (process lifecycle / HTTP connection management) — neither reveals a PRD silence or PRD/impl behavioral mismatch. No test_suite/ fixes, no implementation logic fixes, no deletions.

**Orchestrator verification sweeps (post-fix confidence):** Per memory note (bind-race/keep-alive flakes need ~48 rounds before trusting green), orchestrator ran 3 additional independent 8-round parallel sweeps (A, B, C). All 24 rounds green (86/86, 0 failed). Cumulative post-fix: 40 consecutive green rounds (16 subagent + 24 orchestrator). No flake recurrence.

## Step 8: Finalize PRD — 2026-06-03T13:50:00.000Z

PRD_FINALIZED.md produced as a verbatim, byte-identical copy of PRD.md (MD5 match, 271 lines, 0% delta).

**Changes:** Zero. The <step_7_diff> contained exactly two fixes, both INFRASTRUCTURE-ONLY (app.py port-bind TOCTOU→retry-on-EADDRINUSE; api_client.py Connection:close + retry-once). Subagent independently read both fix sites and confirmed neither touches PRD-describable API behavior — app.py:77-106 is process/port lifecycle (PRD specifies no startup/port/bind semantics); api_client.py:14-30 is HTTP connection hygiene in a test helper that relays calls unchanged. The two flaky test_03 tests were neither deleted nor modified. HARD SCOPE left nothing to patch; per method, no edits were invented to justify the step. NO-NEW-MISMATCH rule satisfied vacuously (zero edits).

Note: Step 8 was run (not skipped) because the literal skip condition was not met — Step 7 did not exit on the first sweep and recorded 1 implementation/ fix + 1 test_helpers/ fix. The run confirmed there was no behavioral PRD-silence/mismatch to finalize.

## Step 9: Complete PRD — 2026-06-03T14:04:20.000Z

PRD_COMPLETED.md produced via full PRD-vs-implementation/ scan. Source PRD_FINALIZED.md (271 lines, 42,502 chars) → PRD_COMPLETED.md (271 lines, 47,383 chars; +4,881 chars; line count unchanged — all edits in-paragraph).

**Counts:** 19 paragraphs revised — 14 ambiguity-pins, 5 mismatch-revisions.

**Most material corrections (the 5 mismatches):**
- §2.6 Precision — reefer deviation compared at full numeric precision, not rounded to one-tenth first (services/metrics.py:47-50).
- §2.7 OCC (berth) — state precondition checked BEFORE version comparison → non-SCHEDULED window yields ERR_INVALID_STATE not ERR_STALE_VERSION; corrected misleading cancel/depart example (routes/berth_windows.py:129-137).
- §2.7 OCC (customs-clear) — state precedes version check → HELD/GATED_OUT container yields ERR_INVALID_STATE; corrected place-hold example to still-PENDING stale path via grounding (routes/containers.py:185-193).
- §3.5 Direct clearance — reordered prose to put PENDING/not-GATED_OUT state check before version comparison (routes/containers.py:189-193).

**Key ambiguity-pins:** pagination clamping + has_more formula (§2.3); berth status default AVAILABLE (§3.1); yard slot registration does not enforce tier/below correspondence (§3.1); explicit guard orderings (state→OCC→berth-closed→conflict on berth; appointment→container→customs→stacking on fulfill); free_time_expires_at/demurrage_due_cents derived on read from window actual_berth_at, reverts on unberth, read does not bump version (§3.3); response-object identity for cascade ops (ground returns container, fulfill returns appointment); container version increments on customs_status change (§3.5); demurrage quote leaves version/updated_at unchanged (§3.6); reefer reading not gated on is_reefer, null setpoint → is_excursion false, max_deviation_c 0.0 with no setpoint (§3.8).

## Pipeline complete — 2026-06-03T14:04:20.000Z

Final state: 86/86 tests passing across 40 consecutive post-fix green rounds. All artifacts present: SCAFFOLD.yaml + 2 design indices, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ + test_suite/ (86 tests), workspace/implementation/ (47 endpoints), results.{1..8}.json (final green sweep). Expert difficulty.
