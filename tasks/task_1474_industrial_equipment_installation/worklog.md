# Worklog — task_1474_industrial_equipment_installation

## Step 1: Create Task Directory — 2026-08-13T10:42:00.000Z

Task directory `tasks/task_1474_industrial_equipment_installation/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T12:20:00.000Z

All checks pass. Final lint verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_1474_industrial_equipment_installation/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_1474_industrial_equipment_installation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_1474_industrial_equipment_installation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    43
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  605

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1474_industrial_equipment_installation/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (envelope, complexity profile, entities, state machines, concurrency rule, calculations, validations, endpoints, errors, roles)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key

**Counts:** 10 entities · 10 state-machine entries (9 entities with machines; Project carries two parallel dimensions) · 6 calculations · 29 validations · 43 endpoints · 29 error codes · 5 roles · 1 OCC concurrency rule · **18 §1.8 instances** (2 per rule) · **46 active §1.9 instances + 10 excluded_because stubs** (56 total entries).

**Verification beyond lint:** every formula-derived assert literal was executed in Python and matches (e.g., TM invoice 238320 vs lump-sum 450000; retainage-on-summed-gross 27668 vs per-line 27669; weekly-OT split 2/3 → 65750); placeholder closure check found zero unbound `${var}` across both design files; all 29 errors are triggerable by at least one recipe; all `excluded_because` stubs resolve to real §1.8 instance names; no forbidden concurrency vocabulary.

**Notable design decisions:**
- **Archetype:** workflow orchestration + compliance/audit; flat topology (creation via FK in body, nested GETs as read views), cyclic state shapes, segregation-of-duties role model (labor submitter ≠ approver; PM submits checklist, CustomerRep signs off).
- **Endpoint count (43) exceeds the Expert guideline band (20–32)** deliberately: the scenario mandates eight distinct concerns, and FK reverse-reachability adds 9 read endpoints; the write surface itself is ~30 tightly-coupled actions. Documented here as a conscious calibration trade-off.
- **Single `POST /projects/{id}/advance`** endpoint drives the 4-hop project phase chain with per-hop preconditions, instead of 4 named action endpoints.
- **Crane fleet is a string reference (`crane_ref`), not an entity** — overlap pool is fleet-wide; capacity check lives on RiggingPlan (`weight_check_passed`), keeping the entity count at 10.
- **Two true dual-variant pairs on different domains:** invoice TM-vs-lump-sum (billing) and labor daily-vs-weekly OT (payroll); the Rule-2 combinatorial instances use mode (a) (4-input tiered labor formula) and mode (b) (pinned round-per-component-then-sum retainage order).
- **Cascades:** safety-plan suspend → project hold → auto-reject SUBMITTED labor → rollup re-eval (depth 3); rigging-plan create-with-supersede → old plan SUPERSEDED → project pin cleared → ISSUED permits CANCELLED (depth 3) — the latter guarded by the scaffold's single OCC rule (`expected_project_version`, ERR_STALE_VERSION/412).
- **Logical clock** `POST /v1/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default drives lockout auto-activation/expiry, lift-permit expiry, foundation-cure, and lift-window membership.

## Step 3: Copy Shared Files — 2026-08-13T12:23:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1474_industrial_equipment_installation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T12:48:00.000Z

File written: `workspace/PRD.md` — 285 lines.

Section coverage:
- §1 Introduction — 2 paragraphs from the scenario (precision installation chain + commercial/labor/safety dimensions).
- §2 (9 subsections) — 2.1 RBAC (all 5 roles, `X-User-ID`/`X-User-Role`, per-role opaque-identity prose); 2.2 response envelope (byte-verbatim canonical block, diff-verified); 2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields); 2.4 common resource properties (UUID `id`, 3-fractional-digit timestamps, `version`; Invoice's append-only exception stated explicitly); 2.5 logical clock (startup default 2026-08-01T00:00:00Z, never wall-clock); 2.6 full validation-priority ordering in prose; 2.7 OCC (`expected_project_version` → `ERR_STALE_VERSION`/412, no other endpoint takes a version field); 2.8 precision/rounding (integer cents, round-half-up per component then sum, retainage on summed gross, second-precision datetimes, equality-passes comparisons); 2.9 fleet-shared cranes, feeder pools, cascades, left-to-right nested retrieval.
- §3 (9 subsections) — 3.1 project creation/commercial terms + work-phase chain; 3.2 site survey (anchor tolerance, 7-day cure); 3.3 safety plan lifecycle + suspend/resume/close cascades + lockout windows (30-minute buffer, clock transitions, manual release); 3.4 rigging plans (OCC, revision counter, open-plan constraint, supersede cascade, review gates, revise loop); 3.5 lift permits (fleet-wide half-open overlap, road permit conditional, execution window + charge, cancel/expire release); 3.6 alignment records (STANDARD/PRECISION tolerances 5.0/2.0 mils, 1.0/0.5 mils/in); 3.7 commissioning checklist (items, counters, triple submit gate, customer sign-off); 3.8 labor costing (class rates 8500/5600/9800/7200, night 1.10, OT 1.5, fringe 2100, DAILY 8h vs WEEKLY 40h cumulative splits fully in prose, segregation of duties, payroll reversal); 3.9 invoicing (TM and LUMP_SUM variants, retainage + release, NTE cap, FINAL uniqueness, billable-work rule, cost rollups).
- §4 — 43 endpoints in a 4-column table with the 201/200 status-code paragraph.
- §5 — all 29 error IDs in a 2-column table.

Hard-contract results: Contract 1 PASS (96/96 field/input/query names in backticks — one miss, `project_id`, found and repaired, plus checklist item subfields `checked`/`checked_at` hardened); Contract 2 PASS (priority ordering, OCC, all transitions/side-effects, all six calculations with constants embedded, all applies_to scopes, defaults/nullables, sibling-branch symmetry all expressed); Contract 3 PASS (zero path/method backtick tokens in §3). No pseudocode operators, no fuzzy words.

Unrenderable elements: none. One scaffold nuance worth noting: validation priority 7 (schema) deliberately follows priorities 4–6 (stale-version, state, segregation) — the PRD preserves this non-standard ordering in §2.6 as written in the scaffold. The withheld difficulty/corner design files were never opened.

## Step 5: Generate Unit Tests — 2026-08-13T13:40:00.000Z

**Files written**

**`test_helpers/` (9 files)**:
- `types.py` — 10 status/field enums + 10 entity TypedDicts; `Invoice` correctly omits `updated_at`/`version` (append-only per PRD §2.4).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (39 methods incl. `_clock/set_current_utc`); module-level `api_client` singleton.
- `api_errors.py` — `ApiErrorId` enum (29 errors) + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` shape checkers (invoice asserts absence of `updated_at`/`version`) + project rollup invariants.
- `factories.py` — payload factories; `None` override removes a key (used to test omitted optional fields and missing required fields).
- `constants.py` — class rates (8500/5600/9800/7200), OT multipliers, fringe 2100, OT thresholds 8/40, alignment tolerances, MIN_CURE_DAYS 7, lockout buffer 30 min, clock defaults.
- `test_users.py` — `TEST_USERS` shared headers for all 5 opaque roles, `ANONYMOUS_HEADERS`, and `make_<role>_headers(user_id)` builders (needed for the segregation-of-duties X-User-ID assertions).
- `fixtures.py` — composite setups: `setup_project_mobilized/installing/with_approved_rigging/commissioning/completed`, `create_active_safety_plan`, `create_accepted_site_survey` (clock-driven cure), `create_approved_rigging_plan` (reads current version for OCC), `create_executed_lift_permit`, `setup_submitted/signed_off_checklist`, `create_approved_labor_entry`, `setup_tm_billable_scenario`, plus list/find read-back helpers. All use `get_success_data`.

**`test_suite/` (11 files, 83 test functions / 84 collected incl. parametrization):**
conftest.py (session `api` + 5 role-header fixtures) and test_01 through test_10 (4/8/9/10/9/8/10/9/12/4 tests).

**Coverage**
- Queue A (Difficulty): 36 tests — all 18 instances × exactly 2 tests each.
- Queue B (Corner): 47 tests — all 46 non-stub instances covered ≥1 (`occ_stale_version_rejected` has 2: stale-reject + current-version-success).
- 10 `excluded_because:` stubs (7 errors + 3 complexity_layers) not translated; all cross-references verified to resolve to real difficulty instances.

**Skipped instances**
None. Every non-stub instance passed the PRD-first two-condition filter — PRD.md verbatim-covers every asserted rule, including the two priority pairs (§2.6 pipeline order covers state-before-fiscal and safety-before-temporal). One recipe note: `invoice_retainage_rounding_on_summed_gross`'s setup chain leaves the project AWARDED, which would trip the PROGRESS phase gate (PRD §3.9); the test adds the minimal safety-plan + advance-to-MOBILIZED steps so the asserted retainage arithmetic (27668 vs per-line 27669) is reachable.

**Validation results**
- py_compile + import check: all 20 files compile; `test_helpers` imports cleanly.
- pytest `--collect-only`: 84 tests collected, no errors.
- Tag audit: every test docstring ends with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance; coverage counts meet §2.1 targets (A ≥2, B ≥1, stubs 0).
- Citation audit: every ≥8-word quoted span in every docstring survives whitespace-normalized literal match against PRD.md (two initial failures from writing "section 3.3/3.4" instead of "§3.3/§3.4" were fixed).
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code comments.

## Step 6: Generate Implementation — 2026-08-13T14:35:00.000Z

**Files written (all under `workspace/implementation/`)**

- `start.sh` — guarded launcher (skips pip when Flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — Flask assembly, envelope error handlers (ApiError/404/405/500), global request lock
- `db.py` — in-memory dicts for all 10 entities + logical clock (default `2026-08-01T00:00:00Z`); **no seeding of any kind** (verified: fresh reboot yields `total_count=0`)
- `errors.py`, `response.py`, `middleware.py`, `util.py`, `validators.py`, `helpers.py` — error catalog, `meta`/`response_type`/`data` envelope with list pagination fields, `X-User-ID`/`X-User-Role` auth + RBAC, Decimal/time helpers, priority-ordered field validators
- `serialize.py` — wire shapes + live project rollups (`foundation_cured` computed at read time against the logical clock)
- `calc.py` — `labor_cost` (per-component round-half-up-then-sum, DAILY_OT 8h split, WEEKLY_OT 40h cumulative split over same-worker ISO-week entries in SUBMITTED/APPROVED/INVOICED) and `alignment_verdict` (STANDARD 5.0/1.0, PRECISION 2.0/0.5, equality passes)
- `routes/` — `projects`, `site_surveys`, `safety`, `lockouts`, `rigging`, `lifts`, `alignments`, `checklists`, `labor`, `invoices`, `clock` (all 36 endpoints)

**Architecture coverage**

- State machines: Project work_status chain with per-hop gates + parallel hold_status; safety plan lifecycle with the 3-hop suspend cascade (hold → auto-reject SUBMITTED labor with `rejection_reason="SAFETY_HOLD"` → single project version bump) and resume/close compensation; lockout clock transitions (SCHEDULED→ACTIVE/EXPIRED, manual release only); rigging plan OCC create (`expected_project_version` → 412) with supersede cascade (old plan SUPERSEDED, pin cleared, ISSUED permits CANCELLED, project version bump **only when a pin existed** — per PRD §3.4/§2.4 over the scaffold's unconditional side-effect wording); lift permit window execution and clock expiry; checklist IN_PROGRESS→SUBMITTED→SIGNED_OFF with the alignment gate (priority 14) checked **before** completeness (priority 21) per PRD §2.6; labor DRAFT/SUBMITTED/APPROVED/REJECTED/INVOICED with segregation-of-duties and APPROVED→REJECTED compensation.
- Calculations: labor_cost (frozen at creation), invoice_amount (TM actuals sweep → INVOICED marking, NTE cap; LUMP_SUM cumulative-target-minus-prior-gross; retainage rounded once on summed gross; FINAL releases all prior retainage and is exempt from NO_BILLABLE_WORK), anchor/foundation checks (7-day cure, equality passes), cost rollups, fleet-wide half-open crane overlap (adjacency allowed), 30-minute per-feeder lockout buffer.
- Validation order follows the scaffold priority table exactly (auth → RBAC → existence → OCC → state → SoD → schema → safety → referential → singleton → measurement → temporal → fiscal → open-plan-last).

**Notable judgment call (flagged for Step 7 adjudication)**

The shipped test suite is internally inconsistent on `hours_worked`: `test_labor_entry_invalid_hours_rejected` requires 25 → 400 on a DAILY_OT project, while `test_weekly_ot_accumulation_across_entries` requires 38 → 201 on a WEEKLY_OT project (the corner-design file explicitly scripts the 38h entry and its 402800-cent total). The only consistent discriminator is `ot_basis`, so the implementation applies the daily cap of 24 to DAILY_OT projects and 168 (7×24) to WEEKLY_OT projects. This passes both tests; it is the single deviation from the literal PRD "(0, 24]" bound.

Step 6 subagent also ran the full suite twice under per-test-server isolation during generation: 84/84 passing both runs.

## Step 7: Run Tests and Iterate — 2026-08-13T15:05:00.000Z

All 8 rounds pass 84/84 after the fixes (the "FAIL: None" lines are an artifact of an ad-hoc parser — the results schema has no per-test `outcome` key; the authoritative counts are `passed=84 total=84 failed=0` in every round).

## Summary

- **Iterations run:** 2 full 8-round parallel sweeps. Sweep 1 (pre-fix): 84/84 in all 8 rounds. Sweep 2 (post-fix): 84/84 in all 8 rounds — clean, stable, no flakiness.

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None. (Note: `test_helpers/assertions.py::assert_labor_entry` already encodes the PRD-verbatim `0 < hours_worked <= 24` bound — it was the source of truth that exposed the one anomalous test.)

- **Fixes applied to `test_suite/`:** `test_suite/test_06_labor_costing.py::test_weekly_ot_accumulation_across_entries` — the test issued `hours_worked=38` in a single entry on a WEEKLY_OT project and expected 201, violating PRD's verbatim per-entry bound. Rewrote it to accumulate the 38 prior hours via two PRD-legal entries (24h Mon 2026-08-10 + 14h Tue 2026-08-11, both SUBMITTED), preserving the covered assertion verbatim: the trailing 5h entry (Wed 2026-08-12) still splits `regular_hours=2 / overtime_hours=3 / total_cost_cents=65750` per the PRD weekly-threshold formula. Why: keep the PRD-covered weekly-accumulation rule while removing the request PRD forbids (STEP 1c / STEP 2).

- **Fixes applied to `implementation/`:** `workspace/implementation/routes/labor.py::create_labor_entry` — removed the ot_basis-conditional cap (`24 if DAILY_OT else 168`) and restored the unconditional `req_num(body, "hours_worked", gt=0, le=24)`. Why: the 168h WEEKLY_OT exception traces to no PRD sentence; PRD states "the `hours_worked` that date (greater than zero and at most twenty-four)" with no regime qualification.

- **Verdict on the hours_worked/ot_basis judgment call:** Both a **test bug** and an **implementation deviation**, not PRD silence. PRD is not silent — it pins "(0, 24]" verbatim and unconditionally, and the scaffold's own assertion helper (`assert_labor_entry`) encodes that same unconditional bound. Under the two-reader test, a faithful PRD-only implementer would cap every entry at 24h and `test_weekly_ot_accumulation_across_entries` would fail on that implementation → unique derivability collapses for the "38h single entry accepted" expectation (ENUM-MEMBERSHIP-ONLY-style overreach: PRD says WEEKLY_OT changes the *split threshold basis*, never that it relaxes the *per-entry input bound*). The weekly-accumulation rule itself is PRD-covered and remains fully tested; only the PRD-illegal request vehicle was replaced. The implementation's 168h branch was a compensating capability with no verbatim PRD trace and was removed per the cardinal rule. Both fixes verified stable across the full 8-round sweep.

## Step 8: Finalize PRD — 2026-08-13T15:20:00.000Z

`PRD_FINALIZED.md` exists at `workspace/PRD_FINALIZED.md` and is byte-identical to `PRD.md` — the justified outcome for this Step 7 round.

**Line counts / delta:** PRD.md = 285 lines, PRD_FINALIZED.md = 285 lines, 0% delta (byte-identical, confirmed by `diff -q`).

**Changes:** None. Zero edits.

**Per-item justification (both Step 7 items resolve without PRD edits):**

- **`test_suite/test_06_labor_costing.py::test_weekly_ot_accumulation_across_entries` (test fix)** — Pure fixture bug, not PRD silence. The pre-fix test issued `hours_worked=38` in a single entry, violating PRD §3.8's verbatim per-entry bound "the `hours_worked` that date (greater than zero and at most twenty-four)". The rewrite accumulates 38 prior hours via two PRD-legal entries (24h Mon + 14h Tue, both SUBMITTED) and preserves the covered assertion (trailing 5h splits `regular=2 / overtime=3 / total_cost_cents=65750`) — which matches `implementation/calc.py:38-50` exactly. PRD already determines this behavior; prose kept verbatim.

- **`implementation/routes/labor.py::create_labor_entry` (impl fix)** — Impl deviation corrected *toward* the PRD, not a PRD gap. Step 7 removed the ot_basis-conditional cap (`24 if DAILY_OT else 168`) and restored unconditional `req_num(body, "hours_worked", gt=0, le=24)` at `labor.py:33`. Since the implementation now matches PRD §3.8's existing verbatim text, there is nothing to patch — editing the PRD here would only risk introducing a new mismatch.

**Per-edit pre-edit search log:** No edits were committed. The mandatory enumeration was still performed for both candidate edit subjects to justify the identical-file conclusion:

- **Subject: per-entry `hours_worked` bound.** Paths enumerated: `implementation/routes/labor.py:33` (unconditional `gt=0, le=24` — the Step 7 fix site), `labor.py:49` (raw echo onto row), `implementation/serialize.py:181` (output echo), `implementation/calc.py:33-34` (DAILY_OT 8h split), `calc.py:38-50` (WEEKLY_OT accumulation consuming stored `hours_worked`), `implementation/validators.py:64-73` + `_bounds` at `validators.py:43-51` (`gt` exclusive / `le` inclusive → exactly the interval `(0, 24]`), and `test_helpers/assertions.py:142` (`0 < hours_worked <= 24`). No `ot_basis`-conditional bound remains anywhere (grep for `168` across impl: zero hits). All paths consistent with PRD §3.8's unconditional wording; no wording adjustment needed, no edit made.
- **Subject: weekly-OT threshold formula.** Paths enumerated: `implementation/calc.py:36-50` — ISO week derived via `date.isocalendar()` (Mon–Sun, matching PRD "ISO week, Monday through Sunday"), prior total counts only same-worker entries in `SUBMITTED`/`APPROVED`/`INVOICED` (PRD verbatim), and `regular = max(0, min(prior + hours, 40) − min(prior, 40))` with `overtime = hours − regular` (PRD's formula verbatim). Fully consistent with PRD §3.8; no edit made.

**Key finding:** This is the explicitly-blessed degenerate outcome — Step 7's only fixes were a test bug (PRD-illegal request vehicle) and an implementation deviation restored to PRD-verbatim behavior. No PRD silence or persistent PRD/impl mismatch remains, so a fresh implementer reading `PRD_FINALIZED.md` (identical to `PRD.md`) already gets the uniquely-determined behavior the current implementation exhibits.

## Step 9: Complete PRD — 2026-08-13T15:45:00.000Z

All 20 diff hunks are at intended locations. PRD_COMPLETED.md is complete.

**Source:** `PRD_FINALIZED.md` (285 lines / 46,903 chars) → `workspace/PRD_COMPLETED.md` (288 lines / 48,678 chars; +3 lines, +1,775 chars).

**Counts:** 24 ambiguity-pins, 2 mismatch-revisions (26 changes total, 20 diff hunks).

**Changes:**

- §1 — revise — mismatch — "retainage withheld on every non-final invoice" → withheld on every invoice (incl. FINAL's own gross), prior withholdings released at final billing — `implementation/routes/invoices.py:83-86`
- §2.1 — insert — ambiguity — a missing `X-User-ID` header is also rejected with `ERR_UNAUTHENTICATED` — `implementation/middleware.py:17`
- §2.2 — insert — ambiguity — unmatched route/method → `ERR_NOT_FOUND` (404) in the error envelope; unexpected faults → `ERR_INTERNAL` (500) — `implementation/app.py:33-45`
- §2.3 — insert — ambiguity — `offset` may not be negative; non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` — `implementation/validators.py:118-137`
- §2.3 — insert — ambiguity — `created_at` sort ties break by insertion order — `implementation/helpers.py:78`
- §2.3 — insert — ambiguity — `has_more` is true exactly when `offset` + `limit` < `total_count` — `implementation/response.py:38`
- §2.5 — insert — ambiguity — clock set applies unconditionally, even to an earlier instant — `implementation/routes/clock.py:18-19`
- §2.6 — insert — ambiguity — schema layer requires the body to be a JSON object — `implementation/validators.py:12-13`
- §3.1 — insert — ambiguity — `equipment_hourly_rate_cents` is a required integer ≥ 0 — `implementation/routes/projects.py:28`
- §3.1 — insert — ambiguity — `retainage_pct` (0.10) and `ot_basis` (DAILY_OT) defaults apply when omitted or null — `implementation/routes/projects.py:29-36`
- §3.2 — insert — ambiguity — `survey_date` is a `YYYY-MM-DD` calendar date — `implementation/routes/site_surveys.py:28`, `validators.py:99-106`
- §3.4 — revise — mismatch — `reviewer_note` is recorded on either review outcome, not only on rejection — `implementation/routes/rigging.py:130`
- §3.4 — insert — ambiguity — revise retains unsupplied fields, including a previously recorded `reviewer_note` — `implementation/routes/rigging.py:145-156`
- §3.5 — insert — ambiguity — `road_permit_required` is a required boolean on every booking request — `implementation/routes/lifts.py:40`
- §3.6 — insert — ambiguity — alignment recording is not phase-gated; allowed in any work phase — `implementation/routes/alignments.py:19-49`
- §3.7 — insert — ambiguity — checklist creation also fails with `ERR_INVALID_STATE` in `COMPLETED`, not only earlier phases — `implementation/routes/checklists.py:29-31`
- §3.7 — insert — ambiguity — the `items` array may be empty — `implementation/routes/checklists.py:35-36`
- §3.7 — insert — ambiguity — `checked_at` records the current logical time; re-checking an item refreshes it; duplicate `item_key` marks the first match — `implementation/routes/checklists.py:96-109`
- §3.7 — insert — ambiguity — `signoff_note` is validated as a string but not stored on the checklist — `implementation/routes/checklists.py:150-152`, `serialize.py:156-168`
- §3.8 — insert — ambiguity — `work_date` is a `YYYY-MM-DD` calendar date — `implementation/routes/labor.py:30`
- §3.8 — insert — ambiguity — WEEKLY_OT prior-hour totals count the worker's entries across all projects — `implementation/calc.py:40-47`
- §3.8 — insert — ambiguity — `reason` is required on every labor rejection — `implementation/routes/labor.py:131`
- §3.9 — insert — ambiguity — `period_start`/`period_end` are `YYYY-MM-DD` dates; end earlier than start → `ERR_VALIDATION` — `implementation/routes/invoices.py:37-40`
- §3.9 — insert — ambiguity — the invoice echoes the request's `progress_pct` (null on TM invoices) — `implementation/routes/invoices.py:95`, `serialize.py:203`
- §3.9 — insert — ambiguity — `labor_entry_ids`/`lift_permit_ids` are listed in `created_at` ascending order — `implementation/routes/invoices.py:56-63,101-102`
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 catalogue row — `implementation/app.py:43-45`

Everything else in the implementation (endpoint inventory, role table, state machines, pipeline ordering, all calculation formulas and constants, cascade side effects, version/touch semantics, append-only invoice shape) was already uniquely pinned by the PRD and left untouched.
