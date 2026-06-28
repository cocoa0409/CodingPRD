# Worklog — task_0497_standby_generator_service

## Step 1: Create Task Directory — 2026-06-25T11:42:31.000Z

Created `tasks/task_0497_standby_generator_service/` and `tasks/task_0497_standby_generator_service/workspace/` (pre-allocated path; auto ID scan skipped per orchestration args).

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-25T12:09:42.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` cleanly.

### Summary

Generated an **Expert-difficulty** scaffold for *Standby Generator Sales & Service (Generac-style)* into `tasks/task_0497_standby_generator_service/`:

**Files written**
- `SCAFFOLD.yaml` (§1.0–§1.7 + complexity profile + concurrency rules)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

**Scaffold contents**
- **Entities: 13** — Customer, Technician, GeneratorModel (immutable catalog), GeneratorProject (sales→install pipeline root), LoadAssessment, Unit (minted at activation; service/warranty/recall root), MaintenancePlan, MaintenanceVisit, ExerciseLog (append-only), WarrantyClaim, RepairDispatch, RecallCampaign, RecallRemediation (recall↔unit junction). Flat topology (`api_prefix: ""`), peer collections with FK links.
- **State machines: 9** — branching-with-revert (GeneratorProject), compound derived posture (Unit.operating_status), a parallel second axis on the same row (Unit.monitoring_health), cyclic suspend/resume (MaintenancePlan), revision-loop cycle (WarrantyClaim OPEN↔UNDER_REVIEW), oscillation cycle (RepairDispatch DISPATCHED↔IN_PROGRESS), fan-out + non-terminal OVERDUE (RecallRemediation), plus MaintenanceVisit and RecallCampaign.
- **Calculations: 6** — dual-variant load sizing (STAGGERED 25.0 kW vs FULL_LOAD 31.0 kW), dual-variant warranty refund (CALENDAR 216000 vs USAGE 200000), tiered+bundle plan price (66600), pinned per-line-then-sum repair invoice (436 vs 435), weighted compliance score with ≥70 threshold, fuel BTU adequacy gate.
- **Validations: 18** (priority-ordered, incl. two temporal-overlap rules with distinct interval semantics) • **Endpoints: 72** (incl. `/_clock/set_current_utc` default `2026-01-01T00:00:00Z`, filtered-list GETs for full FK reverse-reachability) • **Errors: 30** • **Roles: 5** (Anonymous, Customer + Technician entity_backed; ServiceManager + ComplianceOfficer opaque; segregation-of-duties on dispatch close) • **Concurrency rules: 2** (OCC on Unit.version and RepairDispatch.version).

**§1.8 Difficulty Design:** all **9 rules × 2 = 18 instances**, each grounded in §1.1–§1.7 with executable `setup_api_calls` chains and pre-computed literal asserts.

**§1.9 Corner Design:** **30 real corner instances** + 13 `excluded_because` stubs citing §1.8 instances by name. Total 43 entries across the 9 taxonomy sections.

**Lint:** `VERDICT: clean lint` — 495 calls scanned, all conform to §1.5; all 23 FKs have reverse-reachability GETs; zero unbound placeholders; OCC version inputs are dynamic; no forbidden concurrency vocabulary.

## Step 3: Copy Shared Files — 2026-06-25T12:10:15.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-25T12:16:51.000Z

Generated `workspace/PRD.md` (304 lines, ~6,960 words, 49,690 bytes) from `SCAFFOLD.yaml` only. Confirmed the two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were NOT read.

**Structure:** §1 Introduction; §2 Global Specifications (RBAC, response structure, pagination, common properties + logical clock, unit posture & hierarchical consistency, precision/rounding, OCC, validation ordering); §3 Business Logic (9 lifecycle subsections: onboarding → sizing → permit/install → activation → exercise/compliance → maintenance → warranty → repair/segregation → recall/decommission); §4 endpoint table (72 endpoints, 4 cols); §5 error table (30 errors, 2 cols). No audit footer.

**Hard Contracts — all PASS:** Contract 1 (Field-Name Coverage) 79/79 fields, 60/60 inputs, 14/14 path params, 0 missing; Contract 2 (Rule Coverage) all 6 calculations w/ constants + both OCC rules + all transitions/cascades + all 30 error IDs in prose & table; Contract 3 (§3 Path Purity) 463 backtick tokens, 0 path/method leaks. §2.2 byte-identical to canonical source.

## Step 5: Generate Unit Tests — 2026-06-25T12:37:55.000Z

Generated `test_helpers/` (9 files) + `test_suite/` (conftest + 4 files, **66 test functions**).

- **test_helpers/**: types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py, __init__.py.
- **test_suite/**: test_01_calculations.py (13), test_02_state_machines_and_cascades.py (16), test_03_validations_and_constraints.py (21), test_04_rbac_concurrency_invariants.py (16).
- **Coverage:** Queue A (Difficulty) all **18/18** instances translated (≥2 tests each, 36 tagged). Queue B (Corner) all **30/30** non-stub instances translated (≥1 test each). 0 skipped. All 13 `excluded_because` stubs correctly NOT translated.
- **Audits passed:** every test has exactly one verbatim `Design:` tag resolving to a real instance; all 90 PRD citations verbatim-greppable; no skip/xfail; no scaffold leakage; all files byte-compile; suite collects 66 tests.

## Step 6: Generate Implementation — 2026-06-25T12:37:55.000Z

Generated Python + Flask implementation in `workspace/implementation/` (start.sh + requirements.txt + app.py + 11 foundation/domain modules + routes/ package).

- **Entry:** `start.sh → app.py`; Flask blueprints, one route module per resource group; `calc.py`/`posture.py` business logic; flat in-memory dicts in `db.py`.
- **Logical clock:** module-level `_now` init `2026-01-01T00:00:00Z`; `POST /_clock/set_current_utc` (ServiceManager/ComplianceOfficer) parses instant, sets clock, runs `posture.sweep_all()` (SCHEDULED→MISSED past 7-day grace, remediations→OVERDUE past deadline, recompute every unit posture).
- **Storage:** in-memory dicts only, wiped on each boot. No seed/preload, no SQLite/JSON-on-disk/tmp (grep-verified). Two consecutive boots confirmed `total_count: 0`.
- Generator self-verified the install pipeline, all 6 calculations, posture transitions, recall cascade, OCC (412), segregation of duties, double-booking half-open boundary, and the full validation-ordering chain live against a running server.

> Note: scaffold reports 30 errors; both test-gen and impl-gen report 28 error IDs in use — to watch in Step 7 if any test references an error the impl lacks.

## Step 7: Run Tests and Iterate — 2026-06-25T12:44:00.000Z

All 8 parallel rounds green: 66/66 passed, 0 failed in every round.

**Iterations run:** 2 (initial sweep + 1 fix + verification sweep).

**Tests deleted:** None.

**Fixes applied to test_suite/:**
- `test_suite/test_01_calculations.py` — `test_compliance_score_below_threshold_degrades_monitoring`: rewrote the fixture setup so the unit first reaches `OK` before dropping to `DEGRADED`. The original setup activated a `monitoring_enabled` unit (minted at `monitoring_health=OFFLINE`, score 0) and only ever drove its `compliance_score` to 63, then asserted `monitoring_health == "DEGRADED"`. Per PRD §3.5, `monitoring_health` is a stateful transition graph: the only edge out of `OFFLINE` is `OFFLINE → OK` ("once monitoring is enabled and `compliance_score` is at least 70"), and `DEGRADED` is reachable only "From `OK`". A unit whose score never hits 70 stays `OFFLINE` — exactly what the PRD-faithful implementation returned. STEP 2 fixture-precondition violation (setup never established the `OK` precondition the asserted `OK → DEGRADED` edge requires), not an implementation bug. Fix: 7 SUCCESS logs + clock to 2026-03-12 → score 70 → `OFFLINE → OK`; then clock to 2026-04-30 → score 41 → `OK → DEGRADED`. Both phases now assert score and health. `OK → DEGRADED` is verbatim in PRD §3.5 and uniquely derivable, so STEP 1 kept the test.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None. `posture.recompute_monitoring` already models the PRD §3.5 transition graph correctly (no `OFFLINE → DEGRADED` edge); the failure was a test-fixture precondition bug.

**Final state:** 66/66 tests pass across all 8 concurrent rounds, deterministically.

## Step 8: Finalize PRD — 2026-06-25T12:47:34.000Z

Produced `workspace/PRD_FINALIZED.md` as a **verbatim copy of PRD.md (zero edits)**, confirmed byte-identical (both 49,690 bytes / 304 lines) via `diff -q`.

The single Step 7 item was a STEP 2 fixture-precondition bug, not a PRD silence or PRD/impl mismatch. Verified the `monitoring_health` transition graph (subject) against all impl paths: `posture.py:61-85` (`recompute_monitoring`), `posture.py:131-166` (`recompute_unit_posture` incl. DECOMMISSIONED/NON_COMPLIANT→OFFLINE forcing), `posture.py:40-58` + `calc.py:117-124` (compliance score, `HEALTH_THRESHOLD=70`), `routes/units.py:62-80` (PATCH inline recompute), `routes/projects.py:288` (activation mints OFFLINE), plus every recompute callsite (units/recall/maintenance/dispatch). PRD §3.5 already enumerates each source state's out-edge explicitly and uniquely determines the behavior, including the absence of an `OFFLINE → DEGRADED` edge by exclusion. No edits warranted.

## Step 9: Complete PRD — 2026-06-25T23:55:00.000Z

(Resumed after session-limit interruption; Step 9 re-run fresh from PRD_FINALIZED.md.)

- Source `PRD_FINALIZED.md`: 304 lines / 49690 chars. `PRD_COMPLETED.md`: 304 lines / 51713 chars. Char-delta +2023 visible chars (raw byte delta +2015 due to multibyte path content unaffected; net change = +2023 inserted/-15 removed). Line delta 0 (all edits in-paragraph).
- Counts: ambiguity-pins 11, mismatch-revisions 1.

Changes:
- §2.1 — insert — ambiguity — pinned that ownership/assignment checks apply only to mutations; read/list endpoints enforce role but not ownership (a Customer/Technician may read resources they do not own; lists are unfiltered) — routes/common.py:25-34 + e.g. routes/onboarding.py:67-72, routes/units.py:18-35.
- §2.3 — insert — ambiguity — pinned pagination clamping (limit <1→1, >100→100; negative offset→0) and non-integer limit/offset → ERR_INVALID_REQUEST rather than rejection/error otherwise — pagination.py:19-32.
- §2.3 — insert — ambiguity — pinned list-sort tie-break: equal creation timestamps broken by creation/mint order — db.py:83-84 (sorts by `(created_at, _seq)`).
- §2.4 — revise — ambiguity — "starts at its initial value" → "starts at 1 on creation" — db.py:72 (`rec["version"] = 1`).
- §3.1 — revise — mismatch — customer `phone` "defaulting to absent" → "defaulting to null, always present as a field" (impl always emits `phone: null`) — routes/onboarding.py:49, serialize.py:6.
- §3.3 — insert — ambiguity — pinned the permit REJECT path: records permit_number, sets permit_status REJECTED, no fuel check, stays SIZED, bumps version, returns 200 — routes/projects.py:199-203.
- §3.4 — revise — ambiguity — pinned that the activate `monitoring_enabled` toggle is stored as the minted unit's flag while `monitoring_health` stays OFFLINE at mint — routes/projects.py:287-288.
- §3.4 — insert — ambiguity — pinned register idempotency: re-registering an already-REGISTERED unit re-applies no bonus and no status change, though PATCH still bumps version — routes/units.py:54-63.
- §3.6 — insert — ambiguity — pinned `next_due_at` formula: plan creation instant + (visits_completed_ytd+1) cadence periods (12mo ANNUAL / 6mo SEMI_ANNUAL), each completed visit advances one period, day-of-month overflow clamped — posture.py:25-35 + timeutil.py:5-19.
- §3.7 — insert — ambiguity — pinned claim creation defaults: resolution null, refund_cents 0, refund_basis CALENDAR, dispatch_id null — routes/warranty.py:35-44.
- §3.7 — revise — ambiguity — DENY resolution: removed "(or leaves it null)" to pin `NO_FAULT_FOUND` — routes/warranty.py:113.
- §3.8 — revise — ambiguity — pinned that assigning a non-ACTIVE technician is rejected with `ERR_INVALID_STATE` — routes/dispatch.py:103-104.

**Pipeline complete — all 9 steps finished. Final: 66/66 tests passing across 8/8 stability rounds (Expert difficulty).**
