# Worklog — task_2457_nonprofit_social_enterprise_transitional_employment

## Step 1: Create task directory — 2026-09-02T20:15:49.705Z

Created `tasks/task_2457_nonprofit_social_enterprise_transitional_employment/` and `tasks/task_2457_nonprofit_social_enterprise_transitional_employment/workspace/` at the pre-assigned path (index fixed by scenario number 2457; no index auto-allocation performed, per orchestration instructions).

## Step 2: Generate scaffold — 2026-09-02T22:07:51.603Z

All three scaffold artifacts are complete and the lint gate passes.

Verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2457_nonprofit_social_enterprise_transitional_employment/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2457_nonprofit_social_enterprise_transitional_employment/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2457_nonprofit_social_enterprise_transitional_employment/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  1071

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2457_nonprofit_social_enterprise_transitional_employment/`):
- `SCAFFOLD.yaml` (2,725 lines) — §1.0–§1.7 only; no design keys present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,757 lines) — single key `scaffold_difficulty_design`, 9 rule_ids × 2 = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (4,250 lines) — single key `scaffold_corner_design`, 9 sections, **69 instances** (53 full `test_recipe` + 16 `excluded_because` stubs): entities 11, state_machines 11, calculations 11, validations 11, endpoints 6, errors 9, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1.

Scaffold surface: `difficulty_level: expert_plus`; 12 entities / 49 endpoints / 51 error codes / 14 calculations (2 dual-variant) / 39 priority-ordered validations / 10 state machines / 2 OCC concurrency rules / 7 roles (2 entity-backed). Complexity profile: primary `ledger_reconciliation`, secondary `workflow_orchestration`, layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, ops_run_checkpoint]`, topology flat, state-machine shape cyclic, role model segregation_of_duties, consistency immediate.

Verified mechanically beyond the lint: no name collides across the two design files; every `excluded_because.difficulty_instance` citation resolves to a real `rule_id / name` pair and carries no `test_recipe`; all 51 error codes appear in at least one design instance (with an explicit coverage-map comment heading the `errors` section); every recipe has exactly `setup / setup_api_calls / trigger / assert`.

Design adjudications made this session:
- **PyYAML parse defects fixed in the artifacts themselves.** `input: [a, b?]` flow sequences do not parse under `yaml.safe_load` (`?` before `,`/`]` scans as a key indicator), so all 20 optional-field tokens across §1.5 are now quoted (`"mou_status?"`). Same class of bug for `$.data[0].id` inside flow mappings in both design files — now quoted. Without these the lint aborted at load time.
- **Lint check (f) forced one path rename.** `lint_fk_reverse_reachability` matches the sub-resource form against a literal `{id}` segment, so `GET /placements/{placementId}/retention-checkpoints` was unreachable for `RetentionCheckpoint.placement_id`; renamed to `GET /placements/{id}/retention-checkpoints` (plus the 4 §1.7 references). Chosen over adding a `GET /retention-checkpoints/{id}` + filtered-list pair, which would have pushed the endpoint count to 51 and churned the RBAC table.
- `ShiftAssignment` has no `cost_entry_id` and `CostEntry.source_activity_id` is FK→SupportActivity only, so the consistency-model instance discovers the auto-posted `TRAINEE_WAGES` entry via `GET /cost-entries?subsidy_period_id=…` and asserts `source_activity_id == null`.
- Priority-1 (`ERR_UNAUTHENTICATED`) probe retargeted from a non-existent `GET /business-lines` list to `GET /participants` (the scaffold intentionally has no business-line list; children are reached by filtered lists).
- Corner roster trimmed from ~80 to 69 to avoid a third/fourth copy of the graduation ladder; the `rate_threshold_triggers` layer row was skipped because that layer is not active in `complexity_layers`.
- Earlier standing adjudications (unchanged): 49 endpoints exceed the Expert band because check (f) forces a single-resource GET plus filtered list per FK-bearing child — mitigated by dropping a `StaffMember` entity (staff are opaque `X-User-ID`s), replacing an `OutcomeReport` entity with `GET /business-lines/{id}/outcome-summary`, and merging verify/dispute into `POST /placements/{id}/wage-verification`; `api_prefix: ""`; graduation thresholds scaled to 24.000 h / 180 support minutes / 2 coaching sessions so they are reachable in a two-shift chain; the separation cascade sets `RE_ENTRY_ELIGIBLE` unconditionally with the limit enforced only at priority 25, which is what keeps `ERR_RE_ENTRY_LIMIT_REACHED` reachable.

## Step 3: Copy shared files — 2026-09-02T22:08:17.189Z

Copied `./INSTRUCTION.md` → `tasks/task_2457_nonprofit_social_enterprise_transitional_employment/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T22:22:10.000Z

PRD generated and verified complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2457_nonprofit_social_enterprise_transitional_employment/workspace/PRD.md`

**Completeness check (per the anti-truncation constraint):** 441 lines. Last section is **§5. Error Code Catalogue**, and the file ends at a real boundary — the final table row `| `ERR_PARTNER_QUOTA_EXCEEDED` | 409 Conflict |` — not mid-sentence or mid-table.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (pasted byte-identical from `section-2.2-response-structure.md`, verified programmatically) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Versions · 2.5 The Logical Clock · 2.6 The Rejection Ladder · 2.7 Path and Reference Resolution · 2.8 Numeric Precision and Rounding · 2.9 Version Guards on Enrollment and Ledger Posting · 2.10 Interval Conventions · 2.11 Cascade Discipline
- §3 Business Logic & Workflows — 3.1 Selecting and Launching a Business Line · 3.2 Referral Intake and Eligibility Screening · 3.3 Enrollment, Slot Occupancy and the Program Cycle · 3.4 The Trading Calendar: Shifts, Seating and Supervision Limits · 3.5 Completing Work, Recording Quality, and the Wage Cost Trail · 3.6 Support Services, Coaching, and Graduation Readiness · 3.7 Placement with Outside Employers and Wage Evidence · 3.8 Retention Follow-Up and the Ops Sweep · 3.9 Subsidy Accounting, True Cost and Funder Reporting
- §4 Endpoint Definitions — intro paragraph + 4-column table, **49 rows**
- §5 Error Code Catalogue — 2-column table, **51 rows**

**Hard Contract 1 — Field-Name Coverage: PASS.** Machine-checked twice (second pass fixed a false negative caused by the ```json fences confusing backtick pairing). All 12 entities' field names, all `common_fields` (`id`/`created_at`/`updated_at`/`version`), all 12 path-param identifiers plus the nested `id`, all request-body identifiers (including `expected_business_line_version`, `expected_subsidy_period_version`, the four `verified_*` screening inputs, `separation_type`, `action`, `decision`, `to_iso8601`, `retention_measure`, `allocation_basis`), all query-param filters, and all response-only identifiers (`current_utc`, `swept_at`, `missed_checkpoint_count`, `exited_participant_count`, `released_assignment_count`, and the 9 outcome-summary output fields) appear verbatim in backticks. Zero missing. The only scaffold `name:` values absent are the 12 internal *calculation* names (e.g. `subsidy_draw`, `open_period_selector`) and the 37 symbolic *constant* names (e.g. `QUALITY_INCIDENT_LIMIT`, `REST_BUFFER_MINUTES`) — deliberately omitted per the skill's rule that constants be embedded as literal values in business statements; every one of their values is written out in prose.

**Hard Contract 2 — Rule Coverage: PASS.** All 51 error IDs present (the scaffold's 52nd match, `ERR_XXX`, is a placeholder inside the response-envelope illustration). All 10 state machines with every declared transition, precondition and side effect; the full 39-rung priority ladder with each rule's `applies_to` scope enumerated in §2.6; both `concurrency_rules` in §2.9 with their 412 codes and the reason a version guard is the only possible detector; all 14 calculations including both dual-variant ones (allocation `HOURS` vs `REVENUE` with the divergent worked ledger, and outcome measurement `COHORT_BASED` vs `POINT_IN_TIME` with the 0.0000-vs-1.0000 divergence); the pinned orderings (per-assignment wage rounding before summation, allocation-before-margin-before-tier-before-draw); the multi-hop cascades (5-hop period close/cap suspension, 5-hop separation, 4-hop checkpoint confirmation, 3-pass ops sweep) each with deterministic processing order and tie-breakers; sibling-branch asymmetry made explicit (review APPROVED enforces the viability gate / REJECTED requires a reason instead; screening `ELIGIBLE` enforces floors / `WAITLISTED` and `INELIGIBLE` do not; VERIFY vs DISPUTE; VOLUNTARY vs INVOLUNTARY; voiding PLANNED vs DELIVERED). All 47 enum values across every enumerated field verified present.

**Hard Contract 3 — §3 Path Purity: PASS.** Machine-checked: 0 backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method + path. All HTTP contract lives in §4; §3 uses state-transition framing and role+action verbs throughout.

**Constraint compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. The two worked examples in the PRD (the 5503+3666=9169 labour-cost rounding and the 0.2308/85810 vs 0.3276/116766 allocation split) come from `SCAFFOLD.yaml` itself and were independently arithmetic-verified.

**Orchestrator verification (anti-truncation guard):** independently confirmed 441 lines, 27 headings ending at `## 5. Error Code Catalogue`, file terminating on a complete table row, and 51 distinct `ERR_` ids present versus 52 in SCAFFOLD (delta = the `ERR_XXX` envelope placeholder). Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T23:54:28.165641725Z

The suite is complete. Final state:

## Files written

**`test_helpers/`** (Stage 1 infrastructure, PRD-derived only): `__init__.py`, `api_client.py` (49 endpoint methods), `api_errors.py` (51 codes + HTTP status map), `types.py` (all enums), `constants.py` (logical clocks + unknown UUIDs), `test_users.py`, `factories.py` (payload builders), `fixtures.py` (~60 composed program fixtures, all function-scoped), `assertions.py` (shape/rounding/ledger helpers), `test_suite/conftest.py`.

**`test_suite/`** — 22 files, 146 test functions, 154 collected tests:

| file | tests | file | tests |
|---|---|---|---|
| test_01_subsidy_allocation_and_draw | 6 | test_12_compensating_actions | 5 |
| test_02_outcome_summary_retention_measures | 4 | test_13_entity_shapes_and_defaults | 11 |
| test_03_shift_labor_cost_rounding | 3 | test_14_referral_and_participant_transitions | 11 |
| test_04_participant_re_entry_cycle | 3 | test_15_placement_and_retention_transitions | 8 |
| test_05_placement_state_dimensions | 3 | test_16_scoring_and_ledger_calculations | 12 |
| test_06_period_close_cascade | 4 | test_17_validation_ladder_and_ownership | 13 |
| test_07_retention_checkpoint_confirmation | 4 | test_18_ops_run_and_read_only_analysis | 7 |
| test_08_rejection_ladder_precedence | 4 | test_19_missing_rows_and_temporal_guards | 9 |
| test_09_boundary_thresholds | 4 | test_20_intake_gates_and_placement_floors | 10 |
| test_10_cross_entity_state_dependency | 5 | test_21_role_boundaries | 8 |
| test_11_scheduling_overlap_rules | 4 | test_22_version_counters_and_immediate_reads | 8 |

Files 01–12 translate queue A (difficulty); 13–22 translate queue B (corner), grouped by section: entities → 13, state machines → 14/15, calculations → 16, validations → 17, endpoints → 18, errors → 19/20, rbac → 21, cross-cutting layers + consistency model → 22.

## Instances translated vs skipped

- **Difficulty index: 18 non-stub instances, all 18 translated**, each with ≥2 tests.
- **Corner index: 69 instances — 53 non-stub, all 53 translated** with ≥1 test; **16 `excluded_because` stubs emitted nothing** (5 calculations, 5 validations, 3 endpoints, 1 errors, 2 cross-cutting — all marked `covered_by_difficulty` in the source yaml).
- **No instance was skipped for lack of PRD grounding**, and no test is weakened, marked skip/skipif/xfail, or left as a placeholder.

## Audit results (scripted, both mandatory passes)

- **PRD-citation pass:** every quoted sentence in every docstring matches `PRD.md` exactly once under whitespace normalization — 0 failures across all 146 tests. No `skip`/`skipif`/`xfail`/`pytest.skip` anywhere in the suite.
- **Scaffold-citation pass:** exactly one `Design:` line per test, always the last docstring line; **0 dangling tags** (every tag resolves to a real non-stub instance); **0 under-covered instances**; no dual tags.
- `pytest --collect-only` succeeds cleanly (154 tests); every file byte-compiles, imports, and is free of unused imports.
- No scaffold/design vocabulary leaks into test names, comments or prose.

## Notable PRD-vs-recipe conflicts resolved in the PRD's favour

Several corner recipes contradicted `PRD.md`; the PRD won in every case, and the affected sub-assertions were either corrected or dropped rather than weakened:

- `ERR_HIRE_DATE_BEFORE_GRADUATION` is **422**, not the recipe's 409 (PRD §2.6 rung 16 and §4).
- Non-existent fields dropped: `retention_confirmed_days`, placement `missed_checkpoint_count` (only the sweep report carries it), `cost_entry_id`, `created_by_user_id`. Renamed to PRD-exact: `support_minutes_total` → `support_activity_minutes`, `coaching_session_count` → `delivered_coaching_count`, `transitional_hours_total` → `transitional_hours_worked`, `gross_cost_cents` → `total_cost_cents`.
- State names corrected: retention checkpoints rest in `SCHEDULED` (not "PENDING"); a planned support activity is `PLANNED` (not "SCHEDULED").
- Version-counter assertions are written as **relative deltas** rather than absolute `1/2/3`, because the PRD defines `version` only as "increments by one on every mutation" and never fixes the initial value — absolute values are not uniquely derivable.

The isolation constraint was respected throughout: nothing under `workspace/implementation/` was read or written; the suite is written against `PRD.md` alone.

## Step 6: Generate implementation — 2026-09-02T23:55:02.506657926Z

Implementation complete and verified. All work is under `/home/ubuntu/github/CodingPRD/tasks/task_2457_nonprofit_social_enterprise_transitional_employment/workspace/implementation/`.

## Files written (2824 lines total)

| File | Lines | Role |
|---|---|---|
| `store.py` | 159 | in-memory dict store (12 kinds), logical clock (`CLOCK_EPOCH = 2026-08-01T00:00:00Z`), `create_record` / `touch` / `set_fields`, ISO-week + date helpers, deterministic `(created_at, _seq)` ordering |
| `errors.py` | 77 | `ApiError`, all 51 error ids → HTTP status, default messages, `fail()` |
| `response.py` | 83 | envelope (`meta` / `response_type` / `data`), `req_` + 20-alnum request id, timestamp from the logical clock, pagination reader (limit 1..100 default 10) |
| `constants.py` | 134 | every declared enum, weight, floor, cap, FPL table, wage band, tier threshold |
| `calc.py` | 208 | all 14 calculations incl. both dual-variant ones, Decimal + ROUND_HALF_UP, null-on-zero-denominator |
| `shapes.py` | 188 | rung-5 shape/enum/range/datetime validators (booleans rejected where numbers are declared) |
| `auth.py` | 68 | rung 1/2/3/4: authentication, role lists, `must_get` (per-type 404s), ownership guard |
| `serialize.py` | 109 | exact per-entity field tuples, ISO-8601 with 3 fractional digits, Decimal → JSON number |
| `derive.py` | 368 | derived fields, allocation engine, ledger posting/voiding, every cascade |
| `routes/intake.py` | 439 | lines, partners, referrals, participants (17 endpoints) |
| `routes/trading.py` | 360 | shifts, seating, completion/release, support activities (13) |
| `routes/placements.py` | 350 | employers, placements, wage verification, separation, checkpoints, ops sweep (10) |
| `routes/ledger.py` | 211 | subsidy periods, close, true-cost analysis, cost entries, clock (9) |
| `app.py` | 53 | blueprint wiring, `g.touched_rows` per request, envelope error handlers, `0.0.0.0:$PORT`, `threaded=False` |
| `routes/__init__.py`, `start.sh`, `requirements.txt` | 1 / 15 / 1 | launcher: guarded pip install, `export PORT="${PORT:-10000}"`, `exec python3 app.py` (foreground) |

**49 endpoints implemented** — I diffed the registered Flask URL map against the 49 `method`/`path` pairs in SCAFFOLD.yaml: 0 missing, 0 extra. Storage is dicts only (no file, sqlite, or /tmp artifact); a restart resets the clock to the epoch and every list endpoint to `total_count: 0`; boot to first served request is ~0.55 s; nothing is seeded.

## Verification performed
Three HTTP suites against servers launched via `start.sh` on `$PORT` — all pass:
- **Happy path + envelope/auth** (~90 assertions): full chain line → review → launch → partner → referral → screen (`fpl_ratio 0.7952`, `eligibility_score 81.4`, `BAND_A`) → enroll → period → shift → seat → complete → auto-posted ledger entry → coaching → certify → graduate → placement → 4 checkpoints → wage verify/dispute/re-verify → 180-day confirm → `ALUMNI_RETAINED` → outcome summary (both retention measures) → sweep; plus 20 error codes and pagination/meta shape.
- **PRD §3.9 worked example reproduced exactly**: hours basis `mission_share 0.2308` / `mission_cost_cents 85810`; revenue basis `0.3276` / `116766`; per-entry rounding then sum; what-if analysis persists nothing and bumps no version.
- **Cascades/sweeps**: viability gate, MOU/quota gates (trailing 30-day window), waitlist re-screen, rest buffer, line-wide supervision ceiling (incl. overlapping parallel shift), seat capacity, shift auto-close, both void branches with ledger compensation, 5-hop separation cascade (VOIDED checkpoints, employer PROBATION at 3 / TERMINATED at 5, `at_risk_flag` fan-out, `FAILED_EARLY` → `RE_ENTRY_ELIGIBLE`), full re-entry cycle twice then `ERR_RE_ENTRY_LIMIT_REACHED`, subsidy-cap suspension (line SUSPENDED → future shifts CANCELLED → seats RELEASED/`SHIFT_CANCELLED`), and all three sweep passes incl. idempotency.

`pyflakes` is clean; no `__pycache__` or other artifacts left in the directory.

## Interpretation decisions where the prose is ambiguous
1. **Version discipline**: exactly one `version` increment per mutated row per request (tracked in `g.touched_rows`); newly created rows stay at 1; `set_fields` bumps only when a value actually changes — so a "recomputed" side effect that yields the same value does not bump.
2. **`scheduled_hours_current_week`** is answered from the logical clock **at read time** (its window is pinned to the clock's ISO week), so moving the clock cannot leave a stale figure; mutations still store the same value.
3. **`POST /participants`**: the rung-6 state check fires only when the referral is not `ELIGIBLE` *and* no participant references it, keeping rung-24 `ERR_REFERRAL_ALREADY_ENROLLED` reachable.
4. **Rung-6 placement for undeclared-source states** not otherwise covered: participant not `GRADUATED` on placement creation, participant outside {`TRANSITIONAL_EMPLOYED`,`READY_FOR_GRADUATION`,`PLACED`} on support delivery, placement not `ACTIVE` on checkpoint confirm, and graduating while still holding an `ASSIGNED` seat → all `ERR_INVALID_STATE_TRANSITION` at the rung-6 position (state before the rung-10 SOD check).
5. **Bounds that the ladder does not name** are rung-5 `ERR_INVALID_REQUEST` (422): `separation_date` within `[hire_date, now]`, `period_end > period_start`, `ends_at > starts_at`, `starting_wage`/`min_starting_wage` >= 1500. The 1500–2200 trainee band is only ever `ERR_TRAINEE_WAGE_OUT_OF_RANGE` (rung 35).
6. **Wage-verification role pairing** is enforced at the rung-2 position by peeking at `action`: `VERIFY` requires `EmployerPartner`, `DISPUTE` requires `CaseManager` (applied only when `action` is exactly one of those two, so a bad enum still yields 422).
7. **Ownership** is applied to exactly the five declared operations, deliberately *not* to the checkpoint listing, `GET /placements/{id}`, or `GET /employers/{id}`.
8. **List filters**: identifier filters resolve at rung 3 (404 with the per-type code); enum filter values and pagination fail at rung 5 (422).
9. **Checkpoint confirm hop 2'** applies whenever `still_employed` is true and the placement is not `DISPUTED`, but it overwrites `verified_wage_cents_per_hour` only when the checkpoint actually supplied one — a null answer never clobbers existing evidence. Checkpoint wages accept any integer >= 0 (no 1500 floor is declared there, unlike the `VERIFY` action).
10. **Shift auto-close** is evaluated only after the complete/release endpoints, per its declared trigger — not inside the sweep or the suspension cascade.
11. Midnight alignment of `hire_date` / `period_start` / `period_end` is documented in the prose but not declared as a constraint, so it is **not** enforced; the outcome-summary window defaults to `[launched_at (fallback created_at), logical now]`.
12. Undeclared method/path combinations return the standard envelope with `ERR_INVALID_REQUEST` (405/404); Flask runs single-threaded with `strict_slashes = False` for determinism.

## Step 7: Run tests and iterate — 2026-09-03T00:24:15.754209913Z

Confirmed — no lingering `prd-bench-local-run` processes for this task; those matches are the parent pipeline and my own poll commands. The sweep genuinely completed with all 8 rounds green.

## Summary

**Iterations run:** 2 (initial diagnostic sweep + verification sweep after the fix).

**Final result:** all 8 parallel rounds green at **154/154**. Verified `results.1.json` … `results.8.json` exist on disk and parse.

### Tests deleted
None. Every failing test traced to a verbatim PRD sentence and was uniquely derivable.

### Fixes applied to `test_helpers/`
None — the fixtures were PRD-faithful.

### Fixes applied to `implementation/`
- **`workspace/implementation/routes/placements.py`**, `create_placement()` — changed `weekly_hours` validation from `shapes.req_int(...)` to `shapes.req_number(...)`, keeping the same 1–60 bounds.

### Diagnosis

The first sweep was perfectly deterministic — the same 3 tests failed in all 8 rounds, all in `test_20_intake_gates_and_placement_floors.py::TestPlacementGateOrder`, all with `Expected error_id 'ERR_HIRE_DATE_BEFORE_GRADUATION'/'ERR_WAGE_BELOW_EMPLOYER_FLOOR', got 'ERR_INVALID_REQUEST'`. No flakiness signal and no load artifact, so this was a real defect.

Root cause: the shared helper `TestPlacementGateOrder._attempt` sends `weekly_hours=32.0` (a float). The implementation validated that field with `req_int`, which rejects any non-`int`, so rung 5 (request shape) fired and pre-empted the rung 16 / 36 / 37 gates the tests were actually exercising. One upstream shape check was masquerading as three independent gate-ordering bugs.

Applying the protocol:
- **STEP 1a/1b** — PRD §3.7 (line 279) states the hire-date rule and both wage floors, in order, verbatim. Uniquely derivable, so the tests stay.
- **STEP 2** — the payload is PRD-faithful. PRD declares only a range for this field: "`weekly_hours`, the contracted weekly hours at the outside employer, from 1 through 60." `32.0` sits inside that range, and `weekly_hours` appears in **none** of §2.8's type lists — not the integer/money list, not the "Counts are integers throughout" clause, and not the 3-decimal hours list (which names `duration_hours`, `actual_hours`, `transitional_hours_worked`, `scheduled_hours_current_week`, `trainee_hours`, `supervisor_hours`). So the test is faithful and the fixture needed no change.
- **STEP 3** — the integer-only constraint traced to no PRD sentence, so it was an over-strict implementation check rather than a PRD-required one, and relaxing it did not weaken any PRD-mandated gate. The range bounds (1–60), which *are* PRD-stated, were preserved.

I checked before changing the type that no test reads `weekly_hours` back out of a response (only `test_20` references it, as request input), and that `serialize.jsonable` already maps `Decimal` to a JSON number — so the looser parse carries no serialization risk.

**Orchestrator verification:** independently parsed all 8 `results.*.json` (identical mtime 00:13:52, i.e. one coherent sweep) — every round `passed == total == 154`. Grep confirms 0 occurrences of `pytest.mark.skip` / `pytest.mark.xfail` / `pytest.skip` anywhere in `test_suite/` or `test_helpers/`, so the green sweep is not skip-assisted. Step 8 will run (1 `implementation/` fix > 0).

## Step 8: Finalize PRD — 2026-09-03T00:31:43.872030568Z

Done. `PRD_FINALIZED.md` created with exactly one edit.

## Line counts
- `PRD.md`: 441 lines; `PRD_FINALIZED.md`: 441 lines. **%-delta: 0.0%** (1 line revised in place, 1/441 = 0.23% of lines touched; +178 characters).

## Changes
- **§3.7 (line 279) — revise** — pinned `weekly_hours` as a general number (not integer-only) inside 1–60, accepted fractional and stored unrounded — `implementation/routes/placements.py:66`

Everything else in `PRD.md` is verbatim. The Step 7 diff contained no test deletions and no `test_helpers/` fixes, so there was nothing else in scope.

## Per-edit pre-edit search log

**Edit 1 — §3.7 `weekly_hours` numeric type**

(a) **Subject identified:** the accepted numeric domain, range semantics, persistence and serialization of the `weekly_hours` field on placement creation.

(b) **Impl paths enumerated (grepped `weekly_hours` across all of `implementation/`, `test_suite/`, `test_helpers/`; only three non-artifact hits exist):**
- `implementation/routes/placements.py:66-68` — the sole validation/ingest site: `shapes.req_number(payload, "weekly_hours", C.MIN_WEEKLY_HOURS, C.MAX_WEEKLY_HOURS)` with `places` omitted.
- `implementation/shapes.py:70-97` — `req_number` / `_as_number`: rejects `bool`, accepts `int | float | Decimal`, coerces via `calc.dec`, bounds are **inclusive** (`< dec(minimum)` / `> dec(maximum)`), and with `places=None` performs **no** `rhu` quantization. Contrasted against `req_int`/`_as_int` (line 60) to confirm the only behavioral delta is the type gate, not the bounds.
- `implementation/constants.py:109-110` — `MIN_WEEKLY_HOURS = 1`, `MAX_WEEKLY_HOURS = 60`, matching the PRD's existing "from 1 through 60" verbatim, so no range wording needed changing.
- `implementation/calc.py:14-19` (`dec`) — `Decimal(str(value))`, so a supplied `32.5` is preserved exactly; nothing normalizes or truncates.
- `implementation/routes/placements.py:87` — write into `create_record("placements", ...)`, value stored as returned.
- `implementation/serialize.py:56` (`FIELDS["placements"]`) and `serialize.py:78-88` (`jsonable`) — `Decimal` → `float`, i.e. echoed as a JSON number.
- **Off-Step-7 paths checked for hidden integer assumptions:** all of `calc.py` (no function consumes `weekly_hours`; the hours-bearing formulas use `duration_hours`, `actual_hours`, `trainee_hours`, `supervisor_hours`), `derive.py`/`ledger.py`/`trading.py`/`intake.py` (no reference), the separation and ops-sweep cascades (§3.8, `placements.py`), and the funder report (§3.9) — none read the field, so no arithmetic, comparison, or aggregation can be perturbed by a non-integer value. There is also no update/patch endpoint for `weekly_hours`, so `create_placement` is the only writer.
- **PRD-side consistency checks:** §2.8's money/count/hours/score/rate lists (line 158-165) — `weekly_hours` appears in none, so the new sentence contradicts nothing; and rung 5 of §2.6 (line 112), which says "integers inside their declared ranges" — it constrains integer fields only and does not claim every ranged field is an integer, so it needed no amendment.

(c) **Wording adjustment made:** two. First, I dropped a candidate phrase "stored and echoed as supplied" because `jsonable` renders every `Decimal` through `float()`, so an integer input `32` is echoed as `32.0`; "echoed as supplied" would have been a false claim about the response encoding. I narrowed it to "carried onto the placement unrounded", which describes the persistence step accurately and stays silent on the JSON encoding. Second, I declined to add "inclusive" as a standalone clarifier or to restate the bounds, since the existing "from 1 through 60" already matches the inclusive comparisons in `_as_number` — re-specifying it would have been churn without pinning anything. I also deliberately used "a number rather than a count" instead of enumerating accepted JSON types, leaving the bool/string rejection to the general rung-5 shape rule rather than risking an over-narrow type list.

## Step 9: Complete PRD — 2026-09-03T00:51:55.903348353Z

`PRD_COMPLETED.md` is written.

## Counts

- **Source** `PRD_FINALIZED.md`: 441 lines / 98,306 chars
- **Output** `PRD_COMPLETED.md`: 442 lines / 107,129 chars (**+8,765 chars**, +1 line)
- 36 edit sites: **28 ambiguity-pins**, **8 mismatch-revisions**

Walked all 4 route modules (49 endpoints), `derive.py`, `calc.py`, `store.py`, `shapes.py`, `serialize.py`, `response.py`, `auth.py`, `errors.py`, `constants.py`. All 49 paths, 51 error codes and the two worked examples in §3.5/§3.9 already agree with impl arithmetic (verified by hand: 9169 vs 9168; 0.2308/85810 and 0.3276/116766).

## Changes

- §2.2 — revise — ambiguity — `api_request_timestamp` comes from the logical clock, not real time — `response.py:26`
- §2.2 — insert — ambiguity — unrouted path / wrong method yields `ERR_INVALID_REQUEST` at the transport status (404/405), not 422 — `app.py:35-39`
- §2.3 — revise — ambiguity — `created_at` ties broken by row insertion order — `store.py:153`
- §2.3 — revise — ambiguity — `has_more` formula; non-integer / negative pagination values are `ERR_INVALID_REQUEST`; empty string = absent — `response.py:44,58-79`
- §2.4 — revise — **mismatch** — a recomputation mutates only when a value actually changes; one version step per row per request; a row created in the request stays at `version` 1 — `store.py:116-135`
- §2.5 — revise — ambiguity — clock may be set backwards; `data` is `{current_utc}` as a 3-fraction-digit string — `routes/ledger.py:205-211`
- §2.6 r2 — insert — **mismatch** — wage-verification role depends on `action` (`VERIFY`→EmployerPartner, `DISPUTE`→CaseManager), decided *before* placement existence — `routes/placements.py:151-156`
- §2.6 r5 — revise — ambiguity — added the shape rules impl enforces (12h shift cap, `cost_cents`/`amount_cents` > 0, 1500 floors on placement/employer wages, `separation_date` bounds, non-empty `voided_reason`, `verified_wage` >=1500 on VERIFY); wage < 1500 → `ERR_INVALID_REQUEST` — `shapes.py`, `routes/trading.py:37`, `routes/placements.py:31,62,164,190-193`
- §2.6 r24 — insert — **mismatch** — consumed-referral rung displaces rung 6 — `routes/intake.py:309-318`
- §2.8 — insert — ambiguity — decimals serialised as JSON numbers — `serialize.py:83-84`
- §2.10 — revise — ambiguity — shift interval violations are `ERR_INVALID_REQUEST` — `routes/trading.py:35-38`
- §2.10 — revise — **mismatch** — period `00:00:00Z` is convention only; only strict ordering enforced — `routes/ledger.py:31-34`
- §2.10 — revise — **mismatch** — `hire_date` `00:00:00Z` not enforced; `due_date` inherits its time of day — `routes/placements.py:61,102`
- §3.1 — revise — ambiguity — `target_gross_margin_pct` stored rounded to 4 dp — `routes/intake.py:37`
- §3.1 — revise — ambiguity — launch precondition failures report `ERR_INVALID_STATE_TRANSITION` — `routes/intake.py:93-96`
- §3.1 — insert — ambiguity — posture recomputation rewrites all three fields together — `derive.py:74-88`
- §3.2 — revise — ambiguity — `declared_barrier_codes` is a required key (empty array allowed) — `routes/intake.py:198`
- §3.2 — revise — ambiguity — the four verified screening inputs are required and share the submitted bounds — `routes/intake.py:262-265`
- §3.3 — insert — **mismatch** — second enrollment against a referral reports `ERR_REFERRAL_ALREADY_ENROLLED`, never the state error — `routes/intake.py:309-318`
- §3.4 — revise — ambiguity — `supervisor_user_id` is a non-empty opaque string — `routes/trading.py:40`
- §3.4 — insert — **mismatch** — `scheduled_hours_current_week` is re-answered from the clock at read time — `serialize.py:98-104`
- §3.5 — revise — ambiguity — `actual_hours` quantized to 3 dp before any comparison; `>0` is a shape rule — `routes/trading.py:204-206`
- §3.5 — insert — ambiguity — pinned completion-cascade hop order (period → participant → shift → line → auto-close) — `routes/trading.py:230-234`
- §3.6 — revise — ambiguity — delivery re-runs the *whole* allocation (incl. `trainee_hours`, `mission_share`, entry allocations) — `derive.py:314-328`
- §3.6 — insert — ambiguity — `voided_reason` required on both void branches — `routes/trading.py:338`
- §3.6 — revise — ambiguity — void re-runs the whole allocation; a `DELIVERED` activity with no `POSTED` entry still voids with no ledger movement — `routes/trading.py:341-352`
- §3.6 — insert — ambiguity — an outstanding `ASSIGNED` seat at graduation reports `ERR_INVALID_STATE_TRANSITION`, ahead of segregation of duties — `routes/intake.py:395-402`
- §3.6 — insert — ambiguity — delivery's participant-status gate reports `ERR_INVALID_STATE_TRANSITION` — `routes/trading.py:314-318`
- §3.7 — insert — **mismatch** — `starting_wage_cents_per_hour` < 1500 is a shape failure before both wage floors — `routes/placements.py:62`
- §3.7 — insert — ambiguity — `separation_date` bounds are `ERR_INVALID_REQUEST`, decided before the state check — `routes/placements.py:190-195`
- §3.8 — revise — ambiguity — `still_employed` required bool; checkpoint `verified_wage_cents_per_hour` optional, non-negative, no 1500 floor — `routes/placements.py:236-237`
- §3.8 — revise — **mismatch** — hop 2 also fires idempotently from `VERIFIED`, and leaves the placement's existing verified wage when the checkpoint carried none — `routes/placements.py:257-262`
- §3.8 — revise — ambiguity — sweep participant order (`created_at` asc), swept releases skip auto-close, null `eligible_re_entry_at` skipped, pass-3 posture re-derive — `routes/placements.py:310-355`
- §3.8 — insert — ambiguity — sweep counters' scope; bad `business_line_id` → `ERR_BUSINESS_LINE_NOT_FOUND` — `routes/placements.py:283-341`
- §3.9 — revise — ambiguity — `supervisor_hours` stored at 3 dp; period instants' `00:00:00Z` not enforced — `routes/ledger.py:31-35`
- §3.9 — revise — ambiguity — true-cost read recomputes from live rows and writes nothing; `revenue_cents` 0 counts as available — `routes/ledger.py:87-101`, `derive.py:252-280`
- §3.9 — revise — ambiguity — close hop 5 release order, shift `assigned_count` re-derive, no auto-close on cancelled shifts — `derive.py:357-367`
- §3.9 — revise — **mismatch** — outcome-summary window defaults to `launched_at` falling back to `created_at`; query instants used as given — `routes/intake.py:107-109`
- §3.9 — revise — ambiguity — null `wage_progression_pct` contributes 0 to the average but counts in the divisor — `routes/intake.py:133-139`
- §4 table — revise — ambiguity — wage-verification row notes the per-action role split — `routes/placements.py:151-156`

**Orchestrator verification:** `PRD_COMPLETED.md` is 442 lines, ends on a complete final table row of §5, retains all 51 `ERR_` ids, and its heading set is byte-identical to `PRD_FINALIZED.md` (no new sections added). Step 9 touched no `.py` file under `implementation/`, `test_suite/`, or `test_helpers/` (verified by mtime), so the Step 7 green sweep (8/8 rounds at 154/154) remains valid for the delivered artifact.

**PIPELINE COMPLETE** — Steps 1 through 9 all executed; `workspace/PRD_COMPLETED.md` written.
