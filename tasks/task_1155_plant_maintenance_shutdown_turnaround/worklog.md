# Worklog — task_1155_plant_maintenance_shutdown_turnaround

## Step 1: Create Task Directory — 2026-08-11T00:00:00.000Z

Task directory and workspace/ subdirectory were pre-assigned and already exist: `tasks/task_1155_plant_maintenance_shutdown_turnaround/workspace`. Step 1 treated as done per invocation instructions (no auto-index scan run).

## Step 2: Generate Scaffold — 2026-08-11T05:02:00.000Z

All three artifacts are written and lint-clean. Summary:

### Files

| File | Size |
|---|---|
| `SCAFFOLD.yaml` | 97,845 B |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 78,658 B (single top-level key `scaffold_difficulty_design`) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 140,143 B (single top-level key `scaffold_corner_design`) |

### SCAFFOLD.yaml counts
- **14 entities** (Turnaround, WorkItem, WorkItemDependency, Contractor, Worker, Shift, ShiftAssignment, Permit, Isolation, DiscoveryWork, LayDownArea, StagingReservation, DailyReport, PunchItem) — graph topology with a self-referential dependency DAG and Permit↔Isolation many-to-many
- **14 state machines** (incl. parallel `cost_posture` dimension on Turnaround; cyclic rework/appeal/suspend loops)
- **8 calculations** — incl. dual-variant `eac_cost_forecast` (PROVISIONAL vs COMMITTED) and `fatigue_eligibility` (PENALTY_WEIGHTED vs HOURS_LEDGER), pinned per-line-then-sum rounding, and pinned exclude-the-candidate overhead tier order
- **12 validations** (auth → authz → existence → OCC → shape → cross-scope → state → SoD → safety → temporal → constraint → fiscal)
- **79 endpoints** (incl. `POST /_clock/set_current_utc` with the mandatory `2026-05-01T00:00:00Z` default, and full FK reverse-reachability GETs)
- **33 error codes**, **6 roles** (segregation-of-duties model; ContractorSupervisor is `entity_backed:Contractor`, rest opaque), **2 OCC concurrency rules** (work-item estimate, laydown reservation)

### Difficulty design: 19 instances across all 9 rules (≥2 each; rule 2 has 3 — one per mode a/b/c)
All numeric asserts pre-computed from the formulas (e.g., 10h NIGHT hazard line = 129030¢; two 0.1h hazard lines round per-line to 1956¢ vs 1955¢ sum-then-round; overhead tier divergence 11900¢ vs 17850¢; rest gap 10h admitted / 9h rejected; closed-interval isolation touch conflicts only when EXCLUSIVE involved; approve/void money ledger 0→74800→0; reserve/stage/release space ledger 0→120→120→0).

### Corner design: 51 active instances + 12 `excluded_because` stubs across all 9 taxonomy sections (entities, state_machines, calculations, validations, endpoints, rbac, cross_cutting_layers, consistency_model, errors); every one of the 33 error codes is exercised by at least one active instance or stub.

### Verification
`scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (901 calls scanned). Additionally audited: no forbidden race vocabulary, zero duplicate instance names across both design files, zero dangling grounds references, all `excluded_because` citations resolve to real difficulty instances. Two chain bugs found and fixed during replay (a missing second mobilize step in `shift_lock_lifecycle`, and the api_prefix/segment-derivation mismatch that required root-mounted collections plus two extra reverse-GET endpoints). No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-11T05:02:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1155_plant_maintenance_shutdown_turnaround/workspace/INSTRUCTION.md` (1,424 B).

## Step 4: Generate PRD — 2026-08-11T05:25:00.000Z

All checks pass. The PRD is complete on disk.

**Output:** `workspace/PRD.md` — 62,997 bytes, 371 lines.

**Section list:**
- §1 Introduction (2 paragraphs: business context + strictness posture around money/safety/time)
- §2 Global Specifications — 2.1 RBAC (6 roles with `identity` translations, `ContractorSupervisor` entity-backed by `Contractor`), 2.2 API Response Structure (byte-identical verbatim block, diff-verified), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 The Logical Clock (startup default `2026-05-01T00:00:00Z`, never wall-clock), 2.5 Common Resource Properties (`WorkItemDependency` exception: only `id`/`created_at`), 2.6 Money/Hours/Rounding discipline, 2.7 OCC (both rules, `ERR_STALE_VERSION` 412), 2.8 Validation Order (12-tier cascade in priority order), 2.9 Nested Resource Retrieval, 2.10 Cascade Discipline
- §3 Business Logic — 9 subsections (work-list & freeze, mobilization & badging, shifts & fatigue gate, isolations & permits, field execution, discovery authorization, lay-down staging, cost reporting & forecast & ops-run, phase advancement & punch list & handover)
- §4 Endpoint table (79 rows, 4 columns)
- §5 Error catalogue (33 rows, 2 columns)

**Coverage:** every scaffold section was rendered to prose — all 14 entities, all 17 state machines (69 transitions with preconditions + side effects), all 8 calculations with constants and pinned evaluation orders (work rank, critical-path float, tiered labor cost with round-then-cap, pinned per-line-then-sum with the 977.5→1956 example, overhead tier keyed on excluding-this-report base, dual-variant EAC with posture machine, dual-variant fatigue with the 22-ledger-hours/score-20 divergence, aggregate lay-down occupancy with inclusive equality), both OCC rules, all 12 validation priority tiers, all 33 error IDs, all 6 roles, all 79 endpoints, and the test-driving clock.

**Hard Contract Reports:**
- Field coverage check: entities[].fields 87/87 present; endpoints request_body/input/output-shape 73/73 present — PASS
- Rule coverage check: validations 12/12, OCC rejections 2/2, transitions 69/69, calculations 8/8, validation conditions 12/12, endpoint side_effects 79/79, structured fields 87/87, sibling-branch symmetry 8/8 — PASS
- Path purity check (§3 only): 670 backtick tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path tokens — PASS
- Supplementary: all 33 error IDs, 6 role names, 54 state values, 70 enum values in backticks; zero fuzzy words; zero operator-syntax in §3; document ends at §5 with no audit footer.

Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate Unit Tests — 2026-08-11T06:20:00.000Z

Note: the first Step 5 subagent wrote all of test_helpers/ plus test_suite/conftest.py but its context was cut off before emitting the test files; a bounded continuation subagent (same spec) wrote the 9 test_*.py files. Combined result:

**test_helpers/ (9 files):** `__init__.py` (956 B), `types.py` (7,907 B), `api_client.py` (12,869 B), `api_errors.py` (3,423 B), `assertions.py` (7,335 B), `factories.py` (5,704 B), `constants.py` (979 B), `test_users.py` (1,879 B), `fixtures.py` (14,514 B).

**test_suite/ (9 test files, 89 tests):** test_01_turnaround_basics.py (12), test_02_scope_freeze_and_dependencies.py (6), test_03_mobilization_and_badging.py (5), test_04_shifts_assignments_fatigue.py (10), test_05_permits_and_isolations.py (9), test_06_discovery_workflow.py (11), test_07_laydown_staging.py (5), test_08_daily_reports_and_costs.py (16), test_09_execution_to_handover.py (15).

**Coverage:** Queue A (Difficulty): 19/19 instances translated, exactly 2 tests each = 38 tests, no skips. Queue B (Corner): 51/51 non-stub instances translated = 51 tests; 12 `excluded_because` stubs not translated. Design-tag audit PASS (89/89 tagged, all resolve). PRD verbatim-citation audit PASS (132 quoted spans, all whitespace-normalized literal matches against PRD.md). py_compile PASS on all files. No skip/xfail anywhere.

**Notable decisions:** (1) helper bug fixed — `fixtures.py` `approve_report()` used `make_controller_headers` without importing it; (2) `laydown_occupancy_excludes_released` — corner YAML's pre-computed "version == 4" contradicts PRD (§2.5 version starts at 1; §3.7 +1 per reserve, +1 per release, none on stage → uniquely 5); test asserts PRD-derived 5; (3) `shift_lock_lifecycle` — recipe's post-lock attempt reused a worker already on that shift (would hit `ERR_SHIFT_OVERLAP` tier 10 before `ERR_SHIFT_LOCKED` tier 11); test uses a second badged worker so `ERR_SHIFT_LOCKED` is the unique derivable outcome; (4) priority-conflict instances translated (not skipped) because PRD §2.8 explicitly pins evaluation cascade order, making the winning error uniquely derivable.

## Step 6: Generate Implementation — 2026-08-11T06:20:30.000Z

Implementation complete and verified. Files under `workspace/implementation/`: `start.sh` (396 B, guarded pip install + `exec python3 app.py` foreground), `requirements.txt` (14 B), `app.py` (1,517 B), `db.py` (1,355 B, in-memory dicts, empty at boot), `clock.py` (435 B, logical clock default `2026-05-01T00:00:00Z`), `errors.py` (1,407 B), `response.py` (1,134 B), `helpers.py` (4,769 B), `serialize.py` (1,589 B), `util.py` (1,372 B), `services/computed.py` (5,784 B), `services/ranking.py` (3,721 B), `services/pricing.py` (2,301 B), `routes/` (13 modules, ~57 KB).

**Route correspondence:** 79 Flask (method, path) rules vs 79 SCAFFOLD endpoints — exact match, verified programmatically against the YAML.

**Smoke tests (3 fresh boots, each killed after):** (1) boot → 401 without headers; 404 envelope; 201 turnaround create with correct envelope/defaults; (2) full ranking flow: freeze-scope computes rank scores (A-risk 5495 → FROZEN pos 1 critical-path; C-risk 1000 → DEFERRED), pagination meta, clock set roundtrip, cost-summary both forecast variants — caught and fixed one real bug (freeze-scope was not setting `status: SCOPE_FROZEN`); (3) end-to-end lifecycle: advance → contractor invite → mobilize → worker register/vet/badge → MOBILIZED → EXECUTION; start blocked with `ERR_PERMIT_NOT_ACTIVE`; isolation PLANNED→ISOLATED→VERIFIED; permit REQUESTED→ISSUED→ACTIVE; start succeeds; permit REVOKED cascades item to ON_HOLD with version bumps.

**Constraint compliance:** in-memory dicts only (no open()/sqlite/pickle//tmp/JSON-dump; no seeding; store provably empty at boot). Validation cascade follows PRD §2.8 priority order including scaffold quirks (OCC before shape; headcount before shift-locked; system-forced holds do not suspend other permits; computed aggregates recomputed from input sets, never delta-adjusted). All money via Decimal ROUND_HALF_UP; per-line rounding pinned before cap and summation. No sibling tasks, test_helpers/, test_suite/, or difficulty/corner design files were read.

## Step 7: Run Tests and Iterate — 2026-08-11T06:35:00.000Z

Clean 8-round parallel sweep: **89/89 passed in every round, 0 failed, 0 errors.** No tests were deleted; all four failures were test-side bugs.

- **Iterations run:** 2 (initial sweep: 85/89 × 8 rounds, same 4 tests failing deterministically in every round; post-fix sweep: 89/89 × 8 rounds clean).
- **Tests deleted:** None. Every failing test traced to a verbatim PRD rule; the defects were in how the tests expressed those rules.
- **Fixes applied to `test_helpers/`:** None.
- **Fixes applied to `test_suite/`:**
  - `test_01_turnaround_basics.py` — `test_clock_set_echoes_installed_logical_time`: STEP 1b/1c partial-coverage fix. PRD §2.4 pins only "the response echoes the new time as `current_utc`" — the byte format is not uniquely derivable (a faithful reader can normalize to the 3-fractional-digit UTC format §2.2/§2.5 establish for server timestamps, which the implementation does). Kept the covered assertion (field echoes the installed instant, compared as a parsed datetime); dropped the uncovered byte-exact-format assertion.
  - `test_02_scope_freeze_and_dependencies.py` — `test_freeze_scope_marks_zero_float_chain_critical`: STEP 2 test-mistranslation fix. The test asserted the whole X→M→N chain is critical-path (classic-CPM assumption), but the PRD §3.1 formula it quotes — float = project length − the item's own path length — yields float(X)=0, float(M)=40, float(N)=64, float(Y)=76 on the test's own numbers, so only the chain head X is critical. Assertions corrected to the PRD-derived outcome (implementation was already PRD-faithful).
  - `test_09_execution_to_handover.py` — two fixes: (1) `test_start_from_frozen_rejected` asserted `status == "FROZEN"` on the fixture's stale creation-time snapshot (PROPOSED); now re-fetches the item post-freeze before asserting. (2) `test_run_ops_expires_permits_and_releases_reservations` used `issue_permit` without importing it (`NameError`); added it to the `test_helpers` import list.
- **Fixes applied to `implementation/`:** None. The implementation was PRD-faithful in all four cases (canonical timestamp echo, PRD float formula, state machine, OCC/state-gate behavior all verified correct against PRD prose).

Orchestrator verification: all 8 `results.{1..8}.json` present on disk, each passed=89 total=89 failed=0 errors=0.

## Step 8: Finalize PRD — 2026-08-11T06:40:00.000Z

PRD_FINALIZED.md written to disk.

**Line counts:** PRD.md 371 lines, PRD_FINALIZED.md 371 lines — 0.0% line-count delta (the single change is an inline revision within one existing sentence; the diff is exactly one line).

### Changes (one total)

- **§2.4 (The Logical Clock)** — revise — pinned the byte rendering of the clock-set echo: `current_utc` is "rendered as an ISO 8601 UTC timestamp with three fractional digits — the same format §2.2 pins for server-generated timestamps — rather than by repeating the request string verbatim." — `implementation/routes/clock_routes.py:19` (returns `fmt_iso(to)`), formatter at `implementation/util.py:34-37`.

### Step 7 items evaluated

- **`test_01` clock-echo (§2.4):** genuine PRD silence — PRD pinned only that the response "echoes the new time as `current_utc`"; the implementation normalizes the installed instant to UTC with exactly three fractional digits rather than echoing request bytes. Patched (above).
- **`test_02` zero-float chain (§3.1):** pure test mistranslation. `implementation/services/ranking.py:97-100` computes exactly the formula §3.1 already pins (float = project length − own path length; critical iff float == 0). PRD kept verbatim — no edit.
- **`test_09` stale-snapshot fixture and missing-import NameError:** pure test bugs, no behavioral content — no PRD edits.

### Per-edit pre-edit search log

**Edit 1 (§2.4 clock echo):** (a) Subject: wire rendering of `current_utc` in the `POST /_clock/set_current_utc` response. (b) Paths enumerated: `routes/clock_routes.py:12-19` (sole producer — repo-wide grep confirmed no other endpoint returns `current_utc`, no GET clock route); `util.py:34-37` `fmt_iso`; `util.py:12-31` `parse_iso`; `helpers.py:100-104` `as_dt`; `response.py:19` `api_request_timestamp`; `db.py:38` `created_at`/`updated_at`; all other `fmt_iso` echo sites (`routes/isolations.py:57-58`, `routes/shifts.py:42-43`, `routes/permits.py:57-58`, `routes/laydown.py:94-95`, `routes/turnarounds.py:49-50`); PRD §4 clock table row. (c) Wording scoped narrowly to the `current_utc` echo only; format expressed by reference to §2.2's already-pinned server-timestamp format; added "not verbatim" clause; input-acceptance rules remain under-determined, matching the original PRD.

## Step 9: Complete PRD — 2026-08-11T06:50:00.000Z

PRD_COMPLETED.md written to disk.

**Source vs output**: PRD_FINALIZED.md 371 lines / 63,185 chars → PRD_COMPLETED.md 371 lines / 67,413 chars (char-delta +4,228; all edits are inline paragraph inserts/revisions — no new sections, no new lines).

**Counts**: 17 ambiguity-pins, 1 mismatch-revision (18 edited passages total).

- §2.3 Pagination — insert — ambiguity — pinned limit/offset failure modes: non-integer or limit < 1 or negative offset → ERR_INVALID_REQUEST; limit > 100 silently clamps to 100; created_at ties broken by creation order — implementation/helpers.py:129-167, implementation/db.py:30-44
- §2.8 step 2 Authorization — revise — mismatch — literal cascade ordering (authz before existence before shape) is impossible for entity/payload-keyed ownership; pinned impl: path-keyed ownership (mobilize, register-worker) runs before existence, entity-keyed (cancel assignment, submit report) right after the existence load, payload-keyed (assignment worker_id) right after shape validation — implementation/routes/contractors.py:62-111, implementation/routes/assignments.py:40-54, implementation/routes/reports.py:122-128, implementation/routes/shifts.py:105-125
- §2.8 step 4 Stale version — insert — ambiguity — a missing or non-integer expected-version field surfaces as ERR_INVALID_REQUEST (shape tier), not ERR_STALE_VERSION — implementation/routes/work_items.py:113-118, implementation/routes/laydown.py:72-77
- §2.8 step 6 Cross-scope — insert — ambiguity — unresolvable body-referenced identifiers yield ERR_CROSS_SCOPE_REFERENCE, never ERR_NOT_FOUND — implementation/routes/shifts.py:121-125, reports.py:56-64, work_items.py:143-145,202-204, permits.py:46-50, discoveries.py:41-44, punch.py:30-32
- §3.1 Re-estimation — insert — ambiguity — the estimate request is a full replacement: all three fields (estimated_hours, estimated_cost_cents, risk_class) required alongside expected_work_item_version — implementation/routes/work_items.py:117-122
- §3.1 Dependencies — insert — ambiguity — lag_hours must be a non-negative integer; fractional lag rejected ERR_INVALID_REQUEST — implementation/routes/work_items.py:141-142
- §3.1 Freeze — insert — ambiguity — scope_cutoff_count of zero is admissible and freezes no items — implementation/routes/turnarounds.py:74-75,84-86
- §3.2 Worker registration — insert — ambiguity — registration carries no turnaround-phase precondition — implementation/routes/contractors.py:104-126
- §3.2 Badge transitions — insert — ambiguity — no turnaround-phase or contractor-mobilization precondition; only the badge-state pair (and cap on reinstatement) gates it — implementation/routes/workers.py:67-92
- §3.3 Shift planning/lock — insert — ambiguity — planning and locking a shift are legal in any turnaround phase — implementation/routes/shifts.py:22-52,88-102
- §3.3 Fatigue — insert — ambiguity — on a starts_at tie in the projected penalty walk, the candidate orders last among tied shifts — implementation/services/computed.py:168-175
- §3.3 Assignment completion — insert — ambiguity — actual_hours must be a non-negative number — implementation/routes/assignments.py:27
- §3.4 Isolation planning — insert — ambiguity — plannable in any turnaround phase; DEISOLATED isolations never participate in the conflict check — implementation/routes/isolations.py:26-50
- §3.4 Permit request — revise — ambiguity — "scoped work item" replaced: the request imposes no work-item status and no turnaround-phase precondition; the finished-work refusal exists only at activation from ISSUED — implementation/routes/permits.py:28-67,115-122
- §3.5 Hold/complete/verify — insert — ambiguity — no turnaround-phase precondition on any of the three — implementation/routes/work_items.py:237-280
- §3.5 Work-item completion — insert — ambiguity — actual_hours must be a non-negative number — implementation/routes/work_items.py:260
- §3.6 Discovery triage/decision/appeal — insert — ambiguity — none carries a turnaround-phase precondition — implementation/routes/discoveries.py:99-188
- §3.6 Authorization cascade — insert — ambiguity — addendum item's title is `Discovery addendum: {description}`; system_area copied from the origin item, empty string when none — implementation/routes/discoveries.py:148-149
- §3.7 Lay-down areas — insert — ambiguity — area creation legal in any phase; staging a reservation leaves the area's version untouched; neither staging nor releasing is phase-gated — implementation/routes/laydown.py:26-45,120-147
- §3.8 Daily reports — insert — ambiguity — line hours strictly positive, hazard_flag a JSON boolean; drafting/submission/approval/rejection/voiding all phase-independent — implementation/routes/reports.py:26-203
- §3.8 Ops-run — insert — ambiguity — auto-release bumps the affected area's version per released reservation; run-ops itself has no phase gate — implementation/routes/turnarounds.py:188-223
- §3.9 Handover — insert — ambiguity — operations_acknowledged must be the JSON boolean true; truthy non-booleans (1, "true") rejected — implementation/routes/turnarounds.py:155-157

Everything else walked (all 13 route modules, services/{computed,ranking,pricing}.py, response/errors/util/clock/db core) matched the PRD uniquely as written.

## Pipeline Complete — 2026-08-11T06:50:30.000Z

All 9 steps done. workspace/PRD_COMPLETED.md exists; final 8-round sweep 89/89 × 8 clean; worklog reaches Step 9.
