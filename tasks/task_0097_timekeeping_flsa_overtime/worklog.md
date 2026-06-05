# Worklog — task_0097_timekeeping_flsa_overtime

Scenario: 97. Timekeeping & FLSA Overtime: exempt/non-exempt classification, state Meal/Rest break, Overtime (>40/week), Double Time (CA daily >12), shift detention, Time Edit audit, Tipped Wage

Difficulty target (scaffold-generator only): Expert (10-15 entities, 20-32 endpoints, 18-30 error codes, 4+ state machines)

## Step 1: Create task directory — 2026-06-02T03:08:34.000Z

Created `tasks/task_0097_timekeeping_flsa_overtime/` and `tasks/task_0097_timekeeping_flsa_overtime/workspace/` (pre-assigned fixed path; no auto-scan/auto-increment per orchestrator instructions).

## Step 2: Generate scaffold — 2026-06-02T03:31:42.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` with a clean verdict.

Generated the three scaffold files for **task_0097_timekeeping_flsa_overtime** purely from the scenario description and the scaffold-generator spec (no sibling tasks consulted).

**Files written:** `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`), `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`).

**Counts actually produced vs Expert bands:**
- **Entities: 12** (band 10-15 ✓)
- **Endpoints: 45** (band 20-32 — over; structural, see note)
- **Error codes: 23** (band 18-30 ✓)
- **State machines: 5** — Shift, TimePunch, TimesheetWeek (cyclic), TipPool, PayrollRun (band 4+ ✓), including a reject→resubmit cycle and finalize/cancel forks
- Plus 7 calculations and 24 validations.

**Lint:** `VERDICT: clean lint` (518 calls scanned across 18 difficulty + 39 active corner instances). §1.8 has 9 rules × 2 = 18 instances; §1.9 has 39 active instances + 5 `excluded_because` stubs. Zero unbound `${var}` placeholders, all 62 instance names unique, all `grounds` resolve, all stub references resolve, no forbidden concurrency vocabulary.

**Notable design decisions:**
- **Dual-variant OT engine** is the core difficulty: CA daily method (>8h→1.5×, >12h→2.0× double-time, 7th-day rule) vs FLSA weekly method (>40/wk), with explicit non-double-counting (weekly OT only on hours not already daily-OT). All gross-wage literals computed in Python and pinned as exact integer cents (e.g., 14h CA day → 36000 cents; tipped true-up → 5360 cents; tip-pool floor+waterfall remainder exactly conserved).
- **Two OCC concurrency rules** on `TimesheetWeek.version` (approve and payroll-include), both framed as serial stale-version checks (412).
- **Segregation of duties** (editor/submitter of a timesheet cannot approve it) realizes the compliance/audit secondary archetype alongside the append-only immutable `TimeEdit` audit log.
- **Two distinct interval semantics** for Rule 8: punch overlap (closed-on-both-ends) vs shift overlap (half-open, adjacency allowed).
- Topology is **flat** (`api_prefix: ""`); each entity a top-level collection (prioritizes under-represented flat topology per §0.3).

**Caveat on endpoint count:** 45 exceeds the 20-32 band. Structural, not padding: 10-15 entities + lint FK reverse-reachability (every one of 17 FKs needs a discovery GET) forces ~22 read endpoints, on top of 23 irreducible mutation endpoints. Every non-load-bearing read trimmed; no further GET droppable without breaking lint check (f). Difficulty lives in calculations/state machines rather than surface size.

## Step 3: Copy shared files — 2026-06-02T03:32:02.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-02T03:36:35.000Z

Generated `workspace/PRD.md` — **246 lines** — from `SCAFFOLD.yaml` and the doc-generator skill spec.

**Major sections:** §1 Introduction (dual-variant CA-daily vs FLSA-weekly framing + segregation-of-duties + OCC). §2 Global Specs — 8 subsections: RBAC (PayrollAdmin/Supervisor/Employee), fixed §2.2 response envelope, pagination, common resource properties + append-only TimeEdit exception (no updated_at/version), money/time/rounding (round-half-up, round-then-sum), OCC on timesheet week, left-to-right existence resolution, full 24-rule validation ordering. §3 Business Logic — 9 lifecycle subsections (config, shift+punch lifecycle, audited edits/voids, missed-break premiums, tips/pooling/waterfall, dual-variant wage stack, tipped true-up, approval/segregation/revision loop, payroll runs). §4 Endpoint table (all 45). §5 Error catalogue (all 23).

**Hard Contracts all PASS:** Contract 1 Field-Name Coverage 65/65 identifiers + 31 enum/state values + 23 error IDs. Contract 2 Rule Coverage (both OCC entries, three-way segregation, all six calculations in prose, half-open vs closed interval distinction, round-then-sum, cascade side-effects). Contract 3 §3 Path Purity (127 tokens scanned, 0 path/method leaks).

**Confirmation:** Neither design YAML read; no sibling task consulted.

## Step 5: Generate unit tests — 2026-06-02T03:53:31.000Z

Generated complete test infrastructure from the unit-test-generator spec, working only from the four provided inputs.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (entity TypedDicts; `TimeEdit` append-only id+created_at only), `api_client.py` (one method per endpoint), `api_errors.py` (23 error IDs + HTTP-status map), `assertions.py`, `factories.py` (required-vs-optional per PRD), `constants.py`, `test_users.py` (opaque PayrollAdmin/Supervisor + entity-backed Employee; distinct sup-1/sup-2/sup-9 for segregation-of-duties), `fixtures.py` (CA/TX employers, closed-punch workers, submitted/approved/locked-week chains, tip-pool contributions, multi-day workers), barrel `__init__.py`.

**Stage 2 — `test_suite/`**: `conftest.py` + **6 test files, 75 tests total**.

**Coverage:** Queue A (Difficulty) **36 tests** — all 18 instances ×2 (each second test a distinct PRD-grounded observable). Queue B (Corner) **39 tests** — all 39 non-stub instances ≥1. **Skipped: 0** — all 18 Queue A + 39 Queue B passed the PRD-first two-condition filter. 5 `excluded_because` stubs correctly not translated.

**Verification:** all files compile; 75 tests collect cleanly; every test exactly one `Design:` tag; every docstring carries verbatim ≥8-word PRD citation; no skip/xfail/skipif; no scaffold terminology leaked.

**PRD-gap note honored:** PRD §2.4 says `version` "starts at its initial value" without pinning literal `1`, so absolute version literals not uniquely derivable — affected tests assert initial `status` + version-*increment* relations instead of absolute literal.

## Step 6: Generate implementation — 2026-06-02T03:53:31.000Z

Generated complete Python + Flask implementation at `workspace/implementation/`.

**Source files (13):** `start.sh` (executable launcher), `requirements.txt` (flask==3.0.3), `app.py` (blueprint registration, before_request auth, ApiError/404/405 envelope handlers, 0.0.0.0:$PORT default 10000, threaded=True), `db.py` (in-memory dicts keyed by id, base_fields id/created_at/updated_at/version, monotonic _seq for stable sort/tie-breaks), `errors.py` (ApiError + 23-entry error→HTTP map), `response.py` (success/array/error envelopes, req_-prefixed request id, ISO-8601 UTC 3-frac-digit timestamps), `middleware.py` (X-User-Role/X-User-ID auth, Employee entity-backed, require_role), `util.py` (typed parsers, ISO datetime/date parsing, pagination limit default 10/min 1/max 100 offset 0, public() serializer stripping _-fields), `routes/{config,shifts,breaks,tips,timesheets,payroll}.py`, `services/wages.py` (dual-variant wage stack) + `services/helpers.py` (lookups, week-date math, covering-week resolution).

**Endpoint count: 45** (matches PRD §4 / scaffold §1.5 exactly).

**start.sh pip-install guard:** cd's to own dir, guards install on cheap framework import — `if ! python3 -c "import flask"; then pip install -q -r requirements.txt; fi` — then `exec python3 app.py` (foreground, signals propagate). Skips install once deps present.

**Verification:** in-memory only, no seeding/SQLite/JSON-on-disk/tmp (grep confirmed). Smoke suites passed: auth/RBAC 401/403; CA daily-OT/DT (14.25h → regular 480/OT 240/DT 135 min, gross 37000¢); FLSA weekly-only (45h → OT 300 min); tip true-up (9870¢); EXEMPT zero-out; half-open shift overlap vs closed punch overlap at changeover; segregation of duties (submitter + punch-editor blocked from approval); OCC stale-version 412; frozen-timesheet guard; tip-pool waterfall; full payroll include/finalize lifecycle. `bash start.sh` boots binding 0.0.0.0.

**Fidelity note flagged by impl-gen:** tipped true-up implemented without pre-rounding `direct_cash` (only `required_cents` and final make-up rounded), per PRD §2.5 "rounding happens only where the rules explicitly call for it."

## Step 7: Run tests and iterate — 2026-06-02T04:00:42.000Z

**Iterations run:** 2 (initial diagnostic sweep + one fix-and-verify sweep).

**Tests deleted:** None. All 5 failures traced to PRD-covered, uniquely-derivable rules with faulty test setups (STEP 2 test-bug fixes), not PRD-silent assertions.

**Fixes applied to test_helpers/:** None — all bugs were in the test functions' inline setup/assertions, not in shared fixtures.

**Fixes applied to test_suite/ (assertion/setup layer):**

1. `test_04_timesheet_workflow.py` — `test_punch_edit_cascades_into_timesheet_gross`: replaced illegal second `submit_week` (on already-SUBMITTED week → ERR_INVALID_STATE) with `api.get_timesheet_week`. PRD §3.3: punch-edit cascade recomputes a SUBMITTED week's wage fields *in place*; observe via GET, not re-submit (PRD only permits re-submit from REJECTED).

2. `test_04_timesheet_workflow.py` — `test_punch_edit_shrinking_punch_cascades_gross_down`: same fix, GET the week instead of re-submitting.

3. `test_04_timesheet_workflow.py` — `test_void_closed_punch_reconciles_gross_to_zero`: same fix; PRD §3.3 voiding cascades a recompute into the SUBMITTED week in place, GET surfaces reconciled gross.

4. `test_02_shift_and_punch_lifecycle.py` — `test_punch_overlap_strictly_inside_prior_interval_rejected`: setup scheduled a second shift 12:00–20:00 genuinely overlapping the first CLOSED shift's half-open 08:00–16:00 window → ERR_SHIFT_OVERLAP fired before the punch test. Moved second shift to back-to-back 16:00–20:00 (PRD §3.2 half-open adjacency) while keeping punch clock_in at 12:00 — still strictly inside prior CLOSED punch's interval → trips ERR_PUNCH_OVERLAP. Punch overlap independent of shift window in PRD and impl.

5. `test_06_access_and_listings.py` — `test_submit_without_wage_ruleset_rejected`: setup seeded a CLOSED punch in an NV worksite with no NV ruleset, but PRD §3.6 says submit *and shift creation* both require a governing ruleset → shift creation failed first. Removed the closed-punch step. `create_timesheet_week` requires no ruleset; ruleset gate (precedence 5) fires on submit before open-punch guard, so a punchless DRAFT week still surfaces ERR_NO_WAGE_RULESET on submit.

**Fixes applied to implementation/:** None. Implementation was already PRD-faithful on all 5 points (in-place SUBMITTED-week recompute, shift-overlap on non-CANCELLED shifts, shift-creation ruleset gate, submit precedence). All failures were test-setup bugs.

**Final sweep result:** All 8 parallel rounds passed == total = **75/75**. results.1.json … results.8.json present on disk, all green (verified by orchestrator).

## Step 8: Finalize PRD — 2026-06-02T04:03:29.000Z

Ran (not skipped: 5 test_suite/ fixes in Step 7 ⇒ skip condition of all-four-zero not met).

**Result: NO EDITS — PRD_FINALIZED.md is a verbatim copy of PRD.md** (246 → 246 lines, 0% delta; `diff -q` confirms identical, verified by orchestrator).

All 5 Step 7 fixes were pure test-setup (fixture/assertion) bugs where the implementation was already PRD-faithful and the PRD already uniquely determines the behavior. No PRD silence or PRD/impl mismatch at any of the 5 sites.

**Per-item verification (subject + impl paths enumerated):**
1. Punch-edit cascade into SUBMITTED week (in-place recompute) — `routes/shifts.py:272-352` edit_punch, `services/helpers.py:34-45` covering_week_for_punch, `services/wages.py:246` recompute_timesheet, `db.py:51-54` touch. PRD §3.3 + §2.6 already pin it incl. week-version bump.
2. Shrinking-edit cascade direction — same code path (recompute_timesheet direction-agnostic); PRD §3.6 math. No silence.
3. Void CLOSED punch reconciles SUBMITTED-week gross to zero — `routes/shifts.py:369-409` void_punch. PRD §3.3 pins it.
4. Punch overlap strictly inside prior CLOSED punch's interval — `routes/shifts.py:130-188` open_punch (closed-both-ends check, no shift-window constraint). PRD §3.2 pins inclusive ends; PRD never constrains clock_in to shift window.
5. Submit/shift-creation ruleset gate; create-week needs no ruleset — `routes/shifts.py:57-59`, `routes/timesheets.py:140-143` (submit gate before open-punch guard) + `:71-102` create (no gate). PRD §3.6 + §2.8 precedence pin all.

## Step 9: Complete PRD — 2026-06-02T04:08:49.000Z

Full PRD-vs-implementation/ scan (always runs). Source: `PRD_FINALIZED.md` (verbatim copy of PRD.md), 246 lines / 38,756 chars → `PRD_COMPLETED.md` 246 lines / 41,158 chars (**+2,382 chars**, 0 line-count change; all in-paragraph inserts/revisions).

**Counts: 9 changes — 5 ambiguity-pins, 4 mismatch-revisions.**

- **§2.8 Validation Ordering** — revise — mismatch — malformed/missing-field (`ERR_INVALID_REQUEST`) and non-negativity (`ERR_VALIDATION`) checked at body-parse time *before* existence lookup; pinned as parsing-level exceptions masking a later 404 — `routes/config.py:177-182`, `routes/breaks.py:54-59`, `routes/tips.py:39-43`.
- **§3.2 Punch open** — insert — ambiguity — open-time overlap test: new `clock_in` within existing CLOSED punch's `[clock_in, clock_out]` inclusive — `routes/shifts.py:153-163`.
- **§3.3 Audited edit** — insert — ambiguity — `TimeEdit` row records `field`; punch `workday_date` re-derived from post-edit `clock_in`; punch `version` bumps on every successful edit — `routes/shifts.py:316-337`.
- **§3.4 Break premium** — insert — ambiguity — `ERR_EXEMPT_NOT_ELIGIBLE` fires only when not-`taken` + `EXEMPT` + matching premium enabled on governing rule set; otherwise EXEMPT missed break records `premium_owed` false — `routes/breaks.py:71-80`.
- **§3.6 Timesheet week open** — insert — ambiguity — "align with workweek boundary" = date's day-of-week equals `workweek_start_dow`; non-aligned rejected with `ERR_INVALID_REQUEST` — `routes/timesheets.py:19-27, 82-84`.
- **§3.6 Regular rate** — insert — ambiguity — regular rate is zero when total worked hours zero (div-by-zero guard) — `services/wages.py:161-164`.
- **§3.7 Tipped true-up** — insert — ambiguity — rounding shape: direct cash exact, tips integer cents, required floor rounded, final shortfall rounded half-up → `tip_true_up_cents` — `services/wages.py:237-243`.
- **§3.8 Approval** — revise — mismatch — segregation-of-duties checked before stale-version OCC; tie-break `ERR_SEGREGATION_OF_DUTIES` wins — `routes/timesheets.py:170-182`.
- **§3.9 Payroll lock + run open** — revise — mismatch — (a) `period_end < period_start` → `ERR_INVALID_REQUEST`; (b) order run-state → week-state → outside-period → OCC; tie-break `ERR_WEEK_OUTSIDE_PERIOD` wins over stale version — `routes/payroll.py:23-26, 74-88`.

No new sections; no invented behavior. Tests used only as auxiliary cross-reference.

---

## Pipeline complete — 2026-06-02T04:08:49.000Z

All 9 steps finished. Final state: **75/75 tests passing across all 8 parallel stability rounds.** Task artifacts complete: SCAFFOLD.yaml + 2 design YAMLs, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ + test_suite/ (75 tests), workspace/implementation/ (Flask, 45 endpoints, in-memory), results.{1..8}.json all green.
