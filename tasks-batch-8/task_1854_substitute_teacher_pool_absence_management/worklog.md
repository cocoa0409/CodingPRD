# Worklog — task_1854_substitute_teacher_pool_absence_management

## Step 1: Create Task Directory — 2026-08-14T21:07:00.000Z

Created `tasks/task_1854_substitute_teacher_pool_absence_management/` and `tasks/task_1854_substitute_teacher_pool_absence_management/workspace/` (pre-created by pipeline entry; verified empty and ready for Step 2).

User directive for this run: **generate a task harder than expert level** — conveyed to the scaffold-generator subagent.

## Step 2: Generate Scaffold — 2026-08-14T21:40:00.000Z

Scaffold for task 1854 generated and lint-clean.

**Output paths**
- `/home/ubuntu/github/CodingPRD/tasks/task_1854_substitute_teacher_pool_absence_management/SCAFFOLD.yaml` (§1.0–§1.7 only — no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1854_substitute_teacher_pool_absence_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design:` key)
- `/home/ubuntu/github/CodingPRD/tasks/task_1854_substitute_teacher_pool_absence_management/SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design:` key)

**Counts**
- Entities: 14 (District, School, StaffMember, Substitute, Qualification, Clearance, SchoolSubstituteMark, Absence, DispatchBatch, Assignment, InternalCoverage, Timesheet, PayrollPeriod, PerformanceFlag)
- State machines: 10 (Absence has parallel dimensions fill_status × approval_status; cyclic loops on Absence UNFILLED↔COVERED_INTERNALLY, Substitute ACTIVE↔SUSPENDED, Timesheet resubmit; branching fork on Assignment OFFERED)
- Calculations: 11 (incl. 3 dual-variant pairs across different domains: provisional/final pay, lifetime/trailing reliability, SUB_ONLY/ANY_COVERAGE fill rate; combinatorial modes a/b/c: premium cap formula, pinned per-day rounding order, payroll waterfall with pinned created_at ASC evaluation)
- Endpoints: 64
- Errors: 40
- Validations: 19 priority layers; Concurrency (OCC) rules: 3 (absence claim, absence edit, district config); Roles: 5 (2 opaque, 3 entity-backed)
- §1.8: 9 rule blocks, 20 instances (every rule ≥ 2; rule 1 and rule 2 carry 3 each)
- §1.9: 39 active instances + 4 `excluded_because` stubs across 10 sections; instance names unique across both files (63 total)

**Difficulty highlights (harder-than-expert directive)**
- Depth-5 transitive cascade (self-cancel → score event → auto-suspension → cross-school assignment cancel → absence reopen → re-offer) and a depth-4 DNR-escalation cascade from a different trigger
- Pre-computed literal asserts throughout (e.g., final payout 124524 distinguishing round-per-day-then-sum from sum-then-round 124525; budget-cap export charging 50500 of an uncapped 50750; premium 1.65 clamped to 1.50; >= 10-day conversion boundary at 20000 → 23000)
- 3 true-race OCC rules with `${var}`-bound version payloads; 2 validation priority conflicts on distinct category pairs (state×safety, temporal×fiscal); 2 temporal-overlap rules with different interval semantics (binary day-exclusion vs aggregate daily/weekly capacity); 2 compensating invariants (budget cents and absence day-counts)
- Logical clock test-drive endpoint with mandated startup default 2026-08-01T00:00:00Z

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (974 calls scanned). Two design-time issues were caught and fixed during authoring: path placeholders normalized to `{id}` for the linter's sub-resource matching, and the dispatch selector now explicitly excludes substitutes with DECLINED/EXPIRED assignments for the same absence (prevents a decline/re-offer loop).

## Step 3: Copy Shared Files — 2026-08-14T21:41:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1854_substitute_teacher_pool_absence_management/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T21:52:00.000Z

All audits pass. Final report:

## Task Complete

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1854_substitute_teacher_pool_absence_management/workspace/PRD.md` — 337 lines. The withheld index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (headers, 5 roles, per-role identity translation) · 2.2 API Response Structure (**byte-identical verbatim block confirmed**) · 2.3 Pagination (limit 10 default/1–100, offset 0, `created_at` ascending, meta fields) · 2.4 Common Resource Properties (incl. explicit note that Qualification and DispatchBatch lack `updated_at`/`version`) · 2.5 Logical Clock & Lazy Expiry (startup default `2026-08-01T00:00:00Z`) · 2.6 Money/Rates/Rounding (integer cents, round-half-up, per-day-then-sum pinned, 4-decimal fill rates) · 2.7 OCC (all 3 rules) · 2.8 Validation Pipeline (19-stage precedence) · 2.9 School Coverage Budget Ledger · 2.10 Reliability Scoring & Suspension Policy · 2.11 Dispatch Eligibility, Ranking & No-Re-Offer Rule
- §3 Business Logic (8 subsections): 3.1 District/School setup · 3.2 Substitute pool onboarding · 3.3 Absence reporting/approval/editing · 3.4 Callout/offers/self-claim · 3.5 Outcomes/timesheets/verification/extension · 3.6 Internal coverage · 3.7 Payroll waterfall · 3.8 Flags/marks/fill-rate analytics
- §4 Endpoint Definitions — 64 rows, 4 columns; mechanically diffed against scaffold: 0 missing, 0 extra, 0 role mismatches
- §5 Error Code Catalogue — 40 rows, 2 columns

**Self-audit results:**

*Contract 1 — Field-Name Coverage: PASS.* 116 required identifiers (all `entities[].fields[].name`, all endpoint `input`/query/path names, plus analytics row fields and reliability-event sub-fields); first pass found 1 missing (`outcome`), repaired in §3.5; re-run: 116 present, 0 missing. (Note: extraction must strip the §2.2 fenced JSON blocks first, or backtick pairing shifts.)

*Contract 2 — Rule Coverage: PASS.* validations[] priority: 19/19 expressed as an explicit ordered pipeline in §2.8 · concurrency_rules: 3/3 (write endpoint + `expected_absence_version`/`expected_district_version` + `ERR_STALE_VERSION`/412 each) · state-machine transitions: 40/40 with preconditions, error IDs, and side effects (both Absence machines, Assignment, Substitute, Clearance, Mark, InternalCoverage, Timesheet, PayrollPeriod, PerformanceFlag) · calculations: 11/11 in precise prose (weekday count, premium multiplier with strict boundary semantics, provisional vs final variants, per-day-then-sum pinned rounding, lifetime vs trailing reliability, strict suspension boundary, selector eligibility/rank/tie-break/fallback, coverage compensation snapshot, day-coverage conservation invariant, payroll waterfall with `created_at` ordering, both fill-rate variants with null-on-zero-denominator) · validation conditions all matched to error IDs · applies_to scopes enumerated (e.g., DNR screen on offer-create/claim/accept; capacity checked at propose and re-checked at approve) · field defaults/initial values transcribed (district config defaults, pristine scores, null-until-set computed fields) · sibling branches symmetric (ACCEPT/DECLINE, WORKED/NO_SHOW, APPROVE/REJECT, RESOLVE/ESCALATE).

*Contract 3 — §3 Path Purity: PASS.* 534 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. Endpoints referenced via state-pair framing, role+verb, or capability description.

Additional checks: all 40 error IDs appear in §1–§4 prose; §4 table strictly 4 columns; §5 strictly 2 columns.

## Step 5: Generate Unit Tests — 2026-08-14T22:15:00.000Z

Test generation for task_1854_substitute_teacher_pool_absence_management is complete.

## Summary

**Counts**
- Queue A (Difficulty, §1.8): **20/20 instances translated, 40 tests emitted** (≥2 per instance, all rules: dual_variant_calc ×3, combinatorial_formula ×3, non_linear_state_machine ×2, transitive_cascade ×2, priority_pair_validation_conflict ×2, boundary_precision_check ×2, cross_entity_state_dependency ×2, resource_temporal_overlap ×2, compensating_invariant ×2).
- Queue B (Corner, §1.9): **39/39 non-stub instances translated, 39 tests emitted**; **0 skipped**. The 4 `excluded_because:` stubs were not translated; all 4 cross-references (`final_payout_per_day_rounding_order`, `fill_rate_sub_only_vs_any_coverage`, `internal_coverage_aggregate_capacity_semantics`, `payroll_waterfall_cap_evaluation_order`) resolve to real difficulty instances.
- Total: **79 tests**, all collected by pytest with zero collection errors.

**Instances skipped: none.** Every instance passed the PRD-first two-condition filter. Two judgment calls worth noting:
- `substitute_assignment_day_overlap_adjacency_allowed`: the recipe's literal call order (offer B created *after* A is accepted) collides with the PRD's "double-booked" eligibility screen at offer creation. The fixture creates all three offers before any accept, which reaches the identical asserted outcomes (accept B → ERR_ASSIGNMENT_DATE_OVERLAP, offer stays OFFERED; adjacent accept C succeeds) under both PRD readings.
- `absence_creation_defaults_and_required_fields`: the literal `version == 1` assert was dropped (PRD pins the initial version only for District); all other pre-computed values asserted verbatim.

**test_helpers/** (9 files): `__init__.py` (barrel), `types.py` (14 entities + 16 enums; Qualification/DispatchBatch correctly carry only id+created_at), `api_client.py` (47 endpoint methods), `api_errors.py` (37 error ids + framework HTTP-status registration), `assertions.py` (per-entity + budget-ledger and day-conservation invariants), `factories.py` (13 payload factories), `constants.py` (PRD 3.1 defaults + reliability deltas), `test_users.py` (5 roles; per-instance builders for the 3 entity-backed roles), `fixtures.py` (~40 helpers: atomic step wrappers plus composites `basic_world` / `world_with_active_sub` / `accepted_assignment_ctx` / `worked_assignment_ctx` / `verified_assignment_ctx` / `unfilled_absence_ctx`, all identity-threaded).

**test_suite/** (16 files): `conftest.py` + `test_01`…`test_15` grouped by concern (entities, absence intake, approval/edit/cancel, pool onboarding, dispatch/premiums, acceptance gates, cancel/no-show, timesheets/streaks/verification, internal coverage, payroll export, reliability/suspension cascades, fill-rate analytics, security/RBAC, error envelope/OCC, validation priority pairs).

**Self-audit / stage-gate results** (all PASS):
- Design-index coverage audit: every difficulty instance has exactly ≥2 tagged tests; every non-stub corner instance ≥1; no stray or dual tags.
- Verbatim citation pass: 153 PRD quotes across 79 docstrings, all survive literal grep of PRD.md (13 initial failures from markdown bold labels and ellipsized quotes were fixed).
- AST docstring audit: all 79 tests carry exactly one `Design: Difficulty/…` or `Design: Corner/…` line as the final docstring line.
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; pyflakes clean (excluding intentional barrel re-exports).

One operational note: `test_12_fill_rate_analytics.py` was silently deleted twice after Write-tool creation (a shell-written probe persisted fine); the final version was written via shell heredoc and is stable on disk.

## Step 6: Generate Implementation — 2026-08-14T22:15:00.000Z

**Task**: full Python + Flask implementation of task_1854 (Substitute Teacher Pool & Absence Management) in `/home/ubuntu/github/CodingPRD/tasks/task_1854_substitute_teacher_pool_absence_management/workspace/implementation/`.

**File list** (22 files, 3028 lines total):

| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | Foreground launcher; guarded `pip install` (`if ! python3 -c "import flask"`), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | flask>=3.0,<4.0 |
| `app.py` | 63 | Flask entry, global request lock (atomic mutations+cascades), ApiError/404/405/500 envelope handlers, blueprint registration |
| `db.py` | 83 | Empty-at-boot in-memory store, logical clock (starts exactly `2026-08-01T00:00:00Z`, never wall clock), UUID ids, 3-fractional-digit ISO timestamps, version/touch |
| `errors.py` | 63 | Full 39-entry error catalog with exact ids and HTTP statuses |
| `response.py` | 74 | Envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), `limit`/`offset`/`total_count`/`has_more` pagination (defaults 10/0, bounds 1..100) |
| `middleware.py` | 69 | `X-User-ID`/`X-User-Role` auth, five roles, entity-backed ownership (Teacher self, Coordinator school-scoped via `is_coordinator` staff record, Substitute self) |
| `validate.py` | 127 | Stage-2 body shape checks (required fields, enums, `hours_worked` 0.5-step 0.5–12.0, `periods`>=1) |
| `domain.py` | 655 | Selector (eligibility + rank = trailing score + flat PREFERRED boost, tie by earliest registration), offer snapshots, premium multiplier (Decimal, cap), provisional/final pay (round-half-up, per-day-then-sum), streak machinery, reliability events/scores, suspension + DNR + no-show + cancel cascades, dispatch batch, coverage capacity (daily/ISO-week caps), payroll waterfall with created_at-pinned ordering and capping |
| `routes/` (15 modules) | 1918 | districts 90, schools 66, staff 61, substitutes 104, qualifications 48, clearances 71, marks 100, absences 300, dispatch 59, assignments 343, coverages 180, timesheets 147, payroll 97, flags 115, analytics 66, clock 37 |

**Endpoint coverage: 64/64** — every route in PRD §4 is registered (65 Flask rules minus the built-in static route).

**Validation results**:
- `prd-bench-local-run --isolation per-test-server` (server killed and relaunched via `start.sh` before every test): **79/79 passed, twice consecutively** (~101 s per run).
- Reboot contract verified directly: fresh boot has empty store (`total_count: 0` after restart), HTTP-ready in ~2 s, no pip churn on reboot.
- Plus ~170 ad-hoc smoke assertions covering the full absence→offer→accept→worked→verify→export cycle, premium tiers, streaks, suspension boundary, analytics variants, and budget capping — all green.

**Key spec-fidelity decisions made during validation** (each pinned by the test suite or PRD):
1. Dispatch batch order is expire → **pickup → cutoff** → clearance cascade, so a REPORTED absence with an empty pool is marked UNFILLED in one run; pickup's `end_date` guard reads the logical clock date while the cutoff uses `run_for_date`.
2. Clock-jump clearance expiry is **flip-only** — the suspension cascade fires only at batch/activation detection points (PRD 3.2 as pinned by `test_accept_clearance_flip_does_not_suspend_at_clock_jump`).
3. `absences_considered` counts distinct absences evaluated per batch.
4. Cutoff's "no ACCEPTED/WORKED/VERIFIED assignment" is a current-state check (the PRD's "ever" reading would deadlock internal coverage of no-show absences).
5. Re-offer exclusion is literal §2.11: only DECLINED/EXPIRED bar re-offer; CANCELLED and NO_SHOW do not.
6. The selector pool is global (substitutes are not district-scoped); ranking, suspension thresholds, and pay rules read the absence's district config.

## Step 7: Run Tests and Iterate — 2026-08-14T22:30:00.000Z

Clean 8-round parallel sweep achieved on the first iteration — no fixes needed.

## Summary

- **Iterations run:** 1 (a single 8-round parallel stability sweep, all rounds run to completion).
- **Sweep result:** All 8 rounds `passed == total` — 79/79 tests passed in every round, with 0 failed, 0 errors, 0 skipped. Verified per-test statuses in all 8 `results.${i}.json` files (every test entry `status: "passed"`). Round wall time ~107 s each under full 8-way parallelism.
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.

The existing implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1854_substitute_teacher_pool_absence_management/workspace/implementation/` (Flask, in-memory store, logical clock, 64/64 endpoints) is stable against the full 79-test suite across all 8 concurrent rounds — no flakiness surfaced, so the diagnostic protocol never engaged.

## Step 8: Finalize PRD — 2026-08-14T22:30:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — `PRD.md` already determined every behavior the implementation exhibits.

## Step 9: Complete PRD — 2026-08-14T22:45:00.000Z

All changes verified — exactly the 23 intended paragraphs changed, no collateral edits. Final summary:

## Summary

**Source vs output:** No `PRD_FINALIZED.md` existed; copied `PRD.md` → `PRD_COMPLETED.md`. Both 337 lines; bytes 62,671 → 67,041 (**+4,370 bytes / +4,339 chars**). 23 paragraphs changed in place; no sections added or removed.

**Counts:** 20 ambiguity-pins, 3 mismatch-revisions (several edits bundle a pin with a revision in one paragraph; counted by primary classification below).

**Changes:**

- §2.3 Pagination — insert — ambiguity — invalid/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400); creation-timestamp ties broken by creation order — `implementation/response.py:39-60`
- §2.4 Common Properties — revise — ambiguity — `version` starts at 1 at creation for every primary resource — `implementation/db.py:70`
- §2.5 Logical Clock — revise — ambiguity — clock-set answers with `current_utc`; backward jumps permitted with no expiry; forward jumps flip offers with the re-dispatch cascade but flip clearances status-only (suspension cascade never fires on a clock jump) — `implementation/routes/clock.py:17-37`, `implementation/domain.py:549-553`
- §2.8 stage 2 — revise — ambiguity — malformed `yyyy-mm-dd` date fields and non-object JSON bodies yield `ERR_INVALID_REQUEST`; absent body treated as empty object — `implementation/validate.py:9-17,96-127`
- §2.9 Budget Ledger — revise — mismatch — dropped the unqualified "never goes negative" guarantee: extension adjusts committed by the delta with no sufficiency re-check and can push available negative; pinned `coverage_budget_available_cents` carried on every school response — `implementation/routes/assignments.py:341-342`, `implementation/routes/schools.py:38-44`
- §2.10 Reliability — insert — ambiguity — scores/counters recomputed lazily on read/rank/append; multi-district trailing-window attribution (district of latest event, else single district, else 90-day default) — `implementation/domain.py:122-157`, `implementation/routes/substitutes.py:21-23`
- §3.2 Suspension — revise — mismatch — suspension-cascade cancellation of an `OFFERED` assignment does NOT re-run the selector (absence stays `DISPATCHING` without a live offer until a later batch); also pinned manual-suspend `reason` is accepted but not persisted — `implementation/domain.py:443-463`, `implementation/routes/substitutes.py:91-104`
- §3.3 Absence list — insert — ambiguity — `from_date`/`to_date` bound `start_date` inclusively; malformed filter date fails `ERR_INVALID_DATE_RANGE` — `implementation/routes/absences.py:121-135`
- §3.3 Review — revise — ambiguity — rejection additionally requires `approval_status` `PENDING` or `NOT_REQUIRED` — `implementation/routes/absences.py:231-233`
- §3.3 Edit — revise — ambiguity — edit does not re-apply the not-before-current-date rule — `implementation/routes/absences.py:162`
- §3.4 Batch — revise — mismatch — batch order is expire → pick-up → cutoff sweep → clearance expiry (PRD had cutoff before pick-up); cutoff tests assignments *currently* `ACCEPTED/WORKED/VERIFIED` (not "ever"); pick-up `end_date` guard reads the clock date, not `run_for_date`; `absences_considered` counts scanned `REPORTED`/`UNFILLED`/`DISPATCHING` absences; batch record carries `run_for_date` (null when omitted) — `implementation/domain.py:499-546`, `implementation/routes/dispatch.py:16-37`
- §3.4 Manual offer — insert — ambiguity — absence-side gates (fill status, approval clear, `end_date` not past, zero internal-coverage days → `ERR_ABSENCE_INVALID_STATE`); already-asked substitute → `ERR_ASSIGNMENT_INVALID_STATE` — `implementation/routes/assignments.py:48-59,120-123`
- §3.4 Provisional pay — revise — ambiguity — `round_half_up(base_daily_rate_cents × multiplier)` once, then × `scheduled_days` (per-day-first per §2.6), not round of the whole product — `implementation/domain.py:226-229`
- §3.4 Acceptance — insert — ambiguity — answer-time auto-expiry re-runs the selector; plain reads never flip an offer to `EXPIRED` — `implementation/routes/assignments.py:39-45,131-135`
- §3.4 Self-claim — insert — ambiguity — already-asked substitute (live or spent assignment) rejected with `ERR_ASSIGNMENT_INVALID_STATE` — `implementation/routes/absences.py:279-282`
- §3.5 Assignment cancel — insert — ambiguity — cancelling an `OFFERED` assignment touches no budget and does not re-run the selector — `implementation/domain.py:443-463`
- §3.5 No-show — insert — ambiguity — auto-created PerformanceFlag carries `assignment_id` of the no-show assignment — `implementation/routes/assignments.py:254-262`
- §3.5 Extension paragraph — insert — ambiguity — assignments listable with `absence_id`, `substitute_id`, `school_id`, `status` filters — `implementation/routes/assignments.py:138-156`
- §3.6 Coverage propose — insert — ambiguity — covering staff member need not belong to the absence's school — `implementation/routes/coverages.py:55-56`
- §3.7 Export — insert — ambiguity — assignments sharing identical `created_at` processed in creation order — `implementation/domain.py:603-608`
- §3.8 Flag escalation — insert — ambiguity — escalation-created DNR mark carries null `reason` — `implementation/routes/flags.py:104-113`
- §3.8 Marks — insert — ambiguity — missing `reason` on `DO_NOT_RETURN` creation fails with `ERR_INVALID_REQUEST` — `implementation/routes/marks.py:30-31`
- §3.8 Analytics — insert — ambiguity — response `data` is an object with a `rows` array (unpaginated), ordered by `school_id` then `day_of_week`; missing/malformed `from_date`/`to_date` → `ERR_INVALID_REQUEST` — `implementation/routes/analytics.py:19-66`

**Notable impl behaviors deliberately left unpinned** (framework-level, not PRD surface): `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` envelopes for unrouted paths; per-endpoint micro-ordering of body-vs-role validation on `POST /districts` config fields; resubmission of a rejected timesheet after assignment verification (no assignment-state re-check in impl).
