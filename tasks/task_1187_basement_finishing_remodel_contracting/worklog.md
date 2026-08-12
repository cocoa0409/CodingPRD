# Worklog — task_1187_basement_finishing_remodel_contracting

## Step 1: Create Task Directory — 2026-08-11T14:47:00.000Z

Task directory `tasks/task_1187_basement_finishing_remodel_contracting/` and its `workspace/` subdirectory were pre-assigned and pre-created by the pipeline driver (index 1187 pinned by caller). Verified both exist; Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-11T15:20:00.000Z

Scaffold generation complete for task 1187 (Basement Finishing & Remodel Contracting). All three artifacts are on disk and `scaffold_lint.py` reports a clean lint.

### Output files
- `SCAFFOLD.yaml` — 1042 lines, §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 667 lines, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 903 lines, single top-level key `scaffold_corner_design`

### Counts
- Entities: **14** (Contractor, Homeowner, Subcontractor, Project, MoistureAssessment, DesignPackage, Permit, AllowanceLine, ChangeOrder, WorkPhase, DailySiteLog, Inspection, Certificate, WarrantyClaim)
- State machines: **9** (all except DailySiteLog, which is append-only with `common_fields: false`); cyclic loops on MoistureAssessment / DesignPackage / Permit, block-restore loop on WorkPhase
- Calculations: **9** (moisture_risk_score dual-variant, egress_ceiling_compliance, change_order_pricing per-line rounding, project_price dual-variant, phase_sequence_gate topological, zone_schedule_overlap, daily_crew_capacity, cleanup_strike_escalation, warranty_coverage decay)
- Endpoints: **53** (incl. `POST /_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z)
- Errors: **26**; Validations: 26 ordered priorities; Roles: 5; Concurrency rules: 1 (OCC on Project.version for change-order create-with-supersede)
- Difficulty-design instances (§1.8): **18** — exactly 2 per rule across all nine §0.5 rules, every rule honoring its differentiation clause (verified programmatically)
- Corner-design instances (§1.9): **37 active + 12 excluded_because stubs** (49 total), spanning entities / state_machines / calculations / validations / endpoints / rbac / cross_cutting_complexity_layers / consistency_model

### Difficulty parameter application ("harder than expert")
Pushed past the Expert band on every axis while keeping coupling dense rather than merely voluminous: 14 entities (Expert: 10–15), 53 endpoints (Expert: 20–32), 26 errors (Expert: 18–30), 9 calculations with 2 dual-variant pairs, 9 state machines with cycles and guarded transitions (Expert: 4+). Hardness levers per §0.4: dual-variant calcs on two different entity domains (moisture scoring vs project pricing), a depth-4 transitive cascade (site-log violation → strike count → project suspension → phase block → inspection cancel), two validation-priority conflict pairs on different error-category pairs, two temporal-overlap rules with different interval semantics (zone adjacency + 2-day drywall dust buffer vs aggregate daily crew capacity ≤ 4 in an occupied home), two compensating invariants (allowance reserve/release conservation; contract-price debit/credit netting), version-pinned permits (design id + revision), rolling-14-day strike window with resume re-anchoring, and clock-driven permit/certificate expiry sweeps.

### Verification
- `scaffold_lint.py` verdict: **clean lint** — all 617 §1.8/§1.9 calls conform to §1.5; all FKs reverse-reachable (3 initial FK violations fixed by adding `approved_design_id?` filter and sub-resource GETs for design-packages/permits and subcontractor site-logs)
- Programmatic self-checks passed: instance-name uniqueness (67 names, zero dupes), 9×2 rule coverage, grounds resolvability against §1.1–§1.7, zero forbidden concurrency vocabulary, all 26 errors triggerable, stub `difficulty_instance` refs all resolve, file split honored
- All formula-derived asserts are pre-computed literals verified by executing the formulas (e.g., markup rounding 116+118=234 vs 235 sum-first; slab 5.0 ACCEPTED vs 5.01 REJECTED; provisional 5,010,000 vs final 5,012,000; warranty 50% proration 90,000 / cap-then-prorate 100,000 / recurrence override 180,000; warranty_end 2026-06-10 + 730d = 2028-06-09 accounting for leap day)

## Step 3: Copy Shared Files — 2026-08-11T15:21:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1187_basement_finishing_remodel_contracting/workspace/INSTRUCTION.md` (1424 bytes, verified on disk).

## Step 4: Generate PRD — 2026-08-11T15:38:00.000Z

All checks pass. The three "around" hits are figurative ("Around those physical realities...", "traveled around the negotiation loop", "tightens this around drywall"), not numeric approximations, so the no-fuzzy-words rule is intact. The PRD is complete and verified at `workspace/PRD.md` (313 lines).

**Summary**

- **Output**: `workspace/PRD.md` — 313 lines, ~7,350 words.
- **Section count**: 5 top-level sections (Introduction; Global Specifications; Business Logic & Workflows; Endpoint Definitions; Error Code Catalogue) with 9 subsections in §2 (2.1–2.9, incl. verbatim §2.2) and 9 subsections in §3 (3.1–3.9, organized by lifecycle timeline).
- **Entity coverage**: 14/14 — every entity field appears in backticks (Contract 1: 112/112 required identifiers present, 0 missing, incl. nested array keys like `net_clear_sqft`, `unit_cost_cents`, `allowance_line_id`, and endpoint-only inputs like `expected_project_version`, `to_iso8601`, `remediation_note`). `DailySiteLog`'s absence of `updated_at`/`version` stated explicitly.
- **State machine coverage**: 9/9 machines, all 31 state values and every transition expressed (corridor advances with version increments, reopen/revision/correction loops, block-restore cycle, cancel cascades, sweeps); AllowanceLine correctly described as field-driven with no status machine.
- **Calculation coverage**: 9/9 — both moisture variants with exact thresholds/bands and the 0-vs-40 worked contrast; egress R1/R2/R3 with doubling trick and R1-first ordering; pinned per-line rounding with the 234-vs-235 example; PROVISIONAL/FINAL pricing with pinned 5-step evaluation order and the 100000-cent contingency example; DAG gate with `created_at`-ascending promotion; half-open zone overlap with symmetric 2-day drywall buffer; inclusive crew cap of 4; 14-day strike window with resume anchoring and threshold 3; warranty tiers (100/100/50) with 1.5-lb recurrence override, 200000-cent cap, round-half-up.
- **Endpoint coverage**: 53/53 rows in the §4 table (4 columns only), byte-identical method+path match to scaffold; status-code rules (201 create / 200 modify) stated.
- **Error coverage**: 26/26 in §5 (2 columns, statuses verified against scaffold) and 26/26 mentioned with trigger conditions in §2/§3 prose; full 26-priority validation pipeline expressed as an ordered list in §2.6 with a relative-priority summary.
- **Contract reports**: Contract 1 PASS (0 missing); Contract 2 PASS (priority ordering, OCC rule with 412/`ERR_STALE_PROJECT_VERSION`, all cascades and applies_to scopes, field defaults/nullability, sibling symmetry); Contract 3 PASS (477 §3 backtick tokens, 0 path/method violations). §2.2 emitted byte-verbatim from the source file.
- **No design-index leak**: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no other `task_*/` directory was inspected; every number and rule in the PRD derives solely from `SCAFFOLD.yaml`.

## Step 5: Generate Unit Tests — 2026-08-11T16:00:00.000Z

Generation complete and verified. Summary:

### Helper files (`test_helpers/`, all 9 present)
- `__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 14 status/kind/role enums, 14 entity TypedDicts (DailySiteLog correctly omits `updated_at`/`version` per common_fields:false)
- `api_client.py` — `ApiClient(GenericApiClient)` with 40 methods, one per PRD §4 endpoint, plus module-level `api_client`
- `api_errors.py` — all 26 `ApiErrorId` members with §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators + `assert_allowance_conservation` invariant
- `factories.py` — 15 payload factories (input fields only, unique-name generation)
- `constants.py` — `THRESHOLDS` (all calculation constants: slab/RH tiers, 5.7/44 egress, 0.15 markup, 0.10 contingency, 2-day drywall buffer, crew cap 4, noise 65, strike 3/14d, 365/730 warranty, 1.5 lbs recurrence, 200000 cap, 180d permit), `DEFAULT_LOGICAL_CLOCK`
- `test_users.py` — `TEST_USERS` (opaque PlatformAdmin/Inspector canonical; entity-backed fallbacks) + `make_{contractor,homeowner,subcontractor}_headers(user_id)` builders
- `fixtures.py` — 5-tier composites: `setup_intake_project` → `setup_design_project` → `setup_permitting_project` → `setup_scheduling_project` → `setup_in_progress_project` → `setup_suspended_project` / `setup_completed_project`, plus `create_change_order_fresh` (OCC version threading), `file_violation_log`, `set_logical_clock` — all identity-threaded per-instance

### Test files (`test_suite/`)
`conftest.py` + `test_01_projects_and_envelope.py` (7), `test_02_moisture_assessments.py` (7), `test_03_design_packages.py` (7), `test_04_permits.py` (6), `test_05_allowances_and_pricing.py` (7), `test_06_change_orders.py` (7), `test_07_work_phases.py` (9), `test_08_site_logs_strikes.py` (10), `test_09_inspections_certification_warranty.py` (8), `test_10_rbac_security.py` (5).

### Counts
- **Total tests: 73** (36 queue A + 37 queue B)
- **Queue A: 18/18 difficulty instances covered, 2 tests each (36)**
- **Queue B: 36/37 non-stub corner instances covered (37 tests; `warranty_proration_cap_and_invalid_amount` split across 2 tests, same tag). All 12 `excluded_because:` stubs correctly untranslated; all stub cross-references resolve to real difficulty instances.**

### Skipped instances (1, with reason)
- `Corner/entities/project_create_extra_field_rejected` — fails unique derivability: PRD §3.1 says `contractor_id` "never arrives through the request body" but never states unknown/system fields are *rejected* with `ERR_INVALID_REQUEST`; a PRD-faithful implementer could silently ignore the field and return 201. No test emitted (gap left as gap).

### Verification results
- `python3 -m py_compile` over all 21 generated files: **OK**
- **Tag audit: all 73 `Design:` lines resolve to real instances**; zero unresolved, zero dual-tagged, zero untagged, zero stub leakage
- **PRD citation audit: all 112 quoted segments across all docstrings match PRD.md verbatim** (whitespace-normalized literal containment)
- Zero `pytest.mark.skip`/`skipif`/`xfail`; zero scaffold/section-table references in generated code

## Step 6: Generate Implementation — 2026-08-11T16:02:00.000Z

Implementation complete. Summary:

### Files created (all under `workspace/implementation/`)
- `start.sh` (executable, foreground `exec python3 app.py`, reads `$PORT` default 10000, binds `0.0.0.0`, guarded `pip install` — no-op when flask is importable)
- `requirements.txt` (flask>=3.0)
- `app.py` — entry point, ApiError/404/405/500 envelope handlers
- `db.py` — in-memory dict stores (empty at boot, no seeding), logical clock defaulting to exactly `2026-05-01T00:00:00Z`, UUID ids, 3-fractional-digit ISO timestamps
- `errors.py` — ApiError + all 26 catalog error IDs with their HTTP statuses
- `response.py` — envelope: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp`, `response_type` object/array/error, pagination fields `limit/offset/total_count/has_more` in meta
- `validation.py` — auth headers `X-User-Role`/`X-User-ID`, role gating, lenient body parse, deferred priority-26 shape validators, pagination (limit default 10, clamped 1..100; offset default 0)
- `services.py` — all calculations and cascades
- `serializers.py` — exact per-entity field sets (DailySiteLog: only `id`+`created_at`, no version/updated_at)
- `routes/` — `common.py`, `anchors.py`, `projects.py`, `assessments.py`, `designs.py`, `permits.py`, `money.py` (allowances + change orders), `phases.py`, `logs.py`, `inspections.py`, `warranty.py`, `clock.py`

### Route diff result
Scaffold declares 53 (method, path) pairs; Flask registers 53; programmatic diff: **EXACT MATCH** (no missing, no extra). Orchestrator re-verified independently after subagent exit by importing `app.py` and diffing `url_map` against scaffold endpoints: 53 vs 53, MISSING=[], EXTRA=[].

### State machines implemented
Project (INTAKE corridor, SUSPENDED detour, CANCELLED cascade, version+1 per advance), MoistureAssessment (DRAFT→ACCEPTED/REJECTED, REJECTED→DRAFT reopen forcing VERIFICATION + clearing score), DesignPackage (revision loop, supersede-on-approve, `approved_design_id` pinning), Permit (DRAFT/CORRECTIONS_REQUIRED→UNDER_REVIEW, ISSUED/CORRECTIONS decisions, EXPIRED sweep, CLOSED on final pass, amendment_count), ChangeOrder (PROPOSED→APPROVED/REJECTED/WITHDRAWN/SUPERSEDED with draw reserve/release/convert), WorkPhase (PLANNED/READY/IN_PROGRESS/BLOCKED with pre_block_status capture/restore, CANCELLED), Inspection (REQUESTED→PASSED/FAILED/CANCELLED, FINAL-pass certification cascade), Certificate (ACTIVE→EXPIRED sweep), WarrantyClaim (UNDER_REVIEW→APPROVED/DENIED).

### Calculations implemented
moisture_risk_score (SCREENING/VERIFICATION variants, band cutoffs, kind-specific acceptance), egress_ceiling_compliance (R1 Decimal 5.7/44, R2 doubled-area, R3, R1-reported-before-R2/R3 ordering), change_order_pricing (pinned per-line round-half-up ×1.15 — verified 1×101+1×103 → 234), project_price (PROVISIONAL/FINAL variants, 10% contingency on unselected budget-minus-drawn summed then rounded — verified base+10000 with one unselected 100000-cent line), phase_sequence_gate (existence/non-CANCELLED/same-project preds, cycle DFS, created_at-ASC successor promotion), zone_schedule_overlap (half-open intervals, touching endpoints OK, symmetric 2-day DRYWALL buffer — verified), daily_crew_capacity (aggregate ≤4 inclusive — verified 3+2 rejected), cleanup_strike_escalation (violation rule, 14-day trailing window, resume re-anchor, threshold-3 suspension with strike_applied — verified end-to-end), warranty_coverage (recurrence override ≥baseline+1.5 → 100%, 365/730 decay, award = round_half_up(min(claimed, 200000)·pct/100) — verified 150000 award).

### Errors implemented
All 26 catalog IDs with scaffold HTTP statuses, enforced in PRD §2.6 priority order (auth → role → ownership → path → body refs → OCC 412 → project-state gate → from-state/terminal → business 10–25 → shape 26 last). Smoke-verified: ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_REFERENCED_NOT_FOUND, ERR_INVALID_CLAIM_AMOUNT, ERR_INVALID_REQUEST, ERR_STALE_PROJECT_VERSION, ERR_ALLOWANCE_OVERDRAW, ERR_EGRESS_NONCOMPLIANT, ERR_CEILING_NONCOMPLIANT, ERR_ZONE_SCHEDULE_OVERLAP, ERR_CREW_CAPACITY_EXCEEDED, ERR_FUTURE_WORK_DATE.

### Verification results
- `python3 -m py_compile` over all 14 .py files: OK
- Boot test: `PORT=19871 bash start.sh` in background responded within ~1s; unknown route → 404 envelope; fresh second boot (PORT=19872) showed empty store (`total_count: 0`) and clock at `2026-05-01T00:00:00.000Z`, proving clean per-process state with no seeding
- End-to-end corridor smoke-tested: contractor/homeowner/sub registration → project → assessment accept → design approve → permit issue → phase start → 3 strikes → SUSPENDED cascade → resume → completion → FINAL pass → certificate (warranty 2026-05-02→2028-05-01) → warranty claim → approval with award

One fidelity note: on failed permit submits the compliance flags are still computed and persisted per PRD §3.4 ("on every submission … computed and persisted").

## Step 7: Run Tests and Iterate — 2026-08-11T16:15:00.000Z

All 8 rounds pass: 73/73 in every round, verdict `ALL_8_PASS`.

### Summary

- **Iterations run:** 2 (initial sweep: 1 deterministic failure in all 8 rounds; post-fix sweep: clean 8/8).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:** one logical bug, three edits:
  - `workspace/implementation/services.py` — `strike_count()`: the pre-resume log exclusion compared raw logical-clock datetimes (`log["_created_dt"] <= project["_last_resumed_dt"]`). Because PRD's logical clock never advances between requests, the three pre-resume violation logs, the resume, and the post-resume log in `test_strike_window_excludes_pre_resume_logs` all share the identical instant `2026-06-05T00:00:00Z`, so the `<=` check wrongly excluded the post-resume log (`strike_count` 0, expected 1). Replaced with insertion-sequence comparison (`log["_seq"] <= project["_last_resumed_seq"]`), the only faithful way to distinguish "created before/after the resume" (PRD §3.7: "logs created before the resume are excluded from the count") under a static logical clock. Added `next_seq` to the db imports.
  - `services.py` — `resume_project()`: now stamps `project["_last_resumed_seq"] = next_seq()` alongside `_last_resumed_dt`.
  - `workspace/implementation/routes/projects.py` — project creation initializes `"_last_resumed_seq": None` for schema consistency.

Diagnostic trail: STEP 1a — rule is PRD-verbatim (PRD.md lines 206 and 210). STEP 1b — unique derivability holds: under the mandated deterministic logical clock, request/insertion order is the only workable reading of "created after the last resume" (a strict-timestamp reading would make the §3.7 exclusion rule unimplementable for same-instant logs). STEP 2 — test and `setup_suspended_project` fixture are PRD-faithful (clock 2026-06-05, in-window violation dates 06-03/04/05, post-resume log work_date 06-05 in-window). STEP 3 — implementation fix as above.

Orchestrator verification after subagent exit: all 8 `results.{1..8}.json` files present on disk, each `passed=73 total=73` — independently confirmed ALL_8_CONFIRMED.

## Step 8: Finalize PRD — 2026-08-11T16:20:00.000Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md 313 lines, PRD_FINALIZED.md 313 lines — 0 lines / 0.00% line delta; +363 characters (+0.70%). Exactly one paragraph revised inline; nothing else touched.

### Changes (one bullet per change)

- **§3.7 (Site Discipline, strike window paragraph, line 206)** — revise — replaced "counting, once the project has been resumed, only logs created after the last resume **timestamp**" with "…only logs created after the last resume. 'Created after the last resume' is decided by the order in which requests are processed, not by comparing clock timestamps: the logical clock may not advance between requests, so pre-resume logs, the resume, and post-resume logs can all carry the same clock instant, and a log filed in a later request than the resume counts while one filed in an earlier request does not." — impl: `implementation/services.py:183` (`log["_seq"] <= project["_last_resumed_seq"]`), stamped at `services.py:336` (`resume_project`) and `routes/logs.py:51` (log filing), initialized at `routes/projects.py:49`.

Rationale: this was the sole Step 7 implementation fix. The PRD's literal phrase "created after the last resume timestamp" invited a timestamp comparison, which is what the original (buggy) implementation did — `log["_created_dt"] <= project["_last_resumed_dt"]` — and which is unimplementable under the mandated static logical clock (all requests share one instant, e.g. `2026-06-05T00:00:00Z`). The implementation's concrete choice — global insertion-sequence comparison — was not uniquely determined by the PRD text, so it is now pinned. No test deletions, no test_suite/test_helpers fixes existed to trace.

### Per-edit pre-edit search log

- **Edit 1 (§3.7 line 206)**
  - **(a) Subject:** how `strike_count` discriminates logs created before vs. after the most recent resume.
  - **(b) Impl paths enumerated and read/grepped:** `services.py:167-186` (`strike_count` — the Step 7 site); `services.py:331-343` (`resume_project` — stamps `last_resumed_at`, `_last_resumed_dt`, `_last_resumed_seq`); `routes/projects.py:39-53` (creation initializes all three to `None`); `routes/projects.py:73-86` (resume endpoint gates); `routes/logs.py:47-67` (log filing assigns `_seq`, recomputes count, suspends at 3); `serializers.py:50-51` (`strike_count` recomputed on every project read via the same rule); `db.py:29-41` (single global monotonic `_seq`; clock static between requests). Off-subject `_seq` tiebreak uses checked and excluded: `routes/common.py:43,52` (§2.3 list ordering), `services.py:268` (§3.6 successor promotion), `services.py:380` (§3.9 baseline assessment) — all are `created_at`-first tiebreaks the PRD already covers with "created_at ascending, never by identifier", and Step 7 did not touch them. Adjacent PRD sentences verified consistent and left verbatim: line 210 ("logs created before the resume are excluded") is true under insertion-order reading; §2.5 line 87 (clock governs the trailing strike window) still holds for the `work_date` window; line 142 and endpoint-table line 238 unaffected.
  - **(c) Wording adjustment:** scoped the new sentence strictly to the quoted phrase "Created after the last resume" so it makes no claim about `created_at` tiebreaks elsewhere; retained "once the project has been resumed" to match the `last_resumed_at is not None` gate; framed the rule as request-processing order (not "timestamp") so both the public `last_resumed_at` stamping (line 210, unchanged) and the internal sequence comparison remain consistent with every enumerated path.

## Step 9: Complete PRD — 2026-08-11T16:28:00.000Z

PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md`.

**Size delta:** PRD_FINALIZED.md 313 lines / 52,115 chars → PRD_COMPLETED.md 313 lines / 53,834 chars (+0 lines, +1,719 chars). 12 changes total: 9 ambiguity-pins, 3 mismatch-revisions.

**Change log:**

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit→[1,100], negative offset→0); non-integer values get `ERR_INVALID_REQUEST` — impl `validation.py:50-67`.
- §2.3 — insert — ambiguity — list sort ties on identical `created_at` broken by creation (insertion) order, never identifier — impl `routes/common.py:49-52`.
- §2.6 items 8/9 — revise — mismatch — swapped the order so the terminal guard runs before the from-state check (impl checks terminal first on every transition endpoint); extended the terminal enumeration with `ACCEPTED` moisture assessment and `COMPLETED`/`CANCELLED` work phase; scoped the project terminal guard to the project's own transitions with a carve-out for child ops (allowance selection, change-order decisions, claim creation under `COMPLETED`) that still bump project `version` — impl `routes/assessments.py:100-103,131-134`, `routes/phases.py:140-141,158-159,186-187`, `routes/money.py:65-79,217-225`.
- §3.2 — revise — ambiguity — reopening an `ACCEPTED` assessment yields `ERR_ALREADY_TERMINAL`; other non-`REJECTED` states yield `ERR_INVALID_STATE` — impl `routes/assessments.py:131-134`.
- §3.4 — revise — ambiguity — `amendment_count` increments only when a resubmission clears freshness/egress/ceiling and moves to `UNDER_REVIEW`; a failed resubmission still recomputes and persists both flags but leaves count and `CORRECTIONS_REQUIRED` status unchanged — impl `routes/permits.py:104-124`.
- §3.4 — revise — ambiguity — final pass closes *every* `ISSUED` permit of the project, not a singular one — impl `routes/inspections.py:129-132`.
- §3.5 — insert — ambiguity — `allowance_draws[].allowance_line_id` must reference a line of the same project — impl `routes/money.py:126-129`.
- §3.5 — insert — ambiguity — multiple draws against the same line within one order are summed for the `remaining_cents` limit — impl `routes/money.py:140-151`.
- §3.8 — revise — ambiguity — certification cascade closes every `ISSUED` permit — impl `routes/inspections.py:129-132`.
- §3.8 — revise — mismatch — replaced "a project holds at most one certificate": each passing `FINAL` result creates its own certificate, so multiple outstanding `FINAL` requests can yield several certificates — impl `routes/inspections.py:115-128` (no uniqueness guard).
- §4 endpoint table — revise — mismatch — certificates list description changed from "(at most one)" to "(one per passed `FINAL` result)" — same impl ref.
- §3.9 — insert — ambiguity — `moisture_recurrence_confirmed` is computed and persisted at filing alongside the `coverage_pct` preview; both recomputed at decision — impl `routes/warranty.py:76-89,119-127`.

Everything else in the impl (endpoint set, roles, error catalog, scoring formulas, R1/R2/R3, pricing/rounding order, strike window mechanics, cascade side effects, serializer field shapes, validation priority order 1–26) matched the finalized PRD as already uniquely pinned.
