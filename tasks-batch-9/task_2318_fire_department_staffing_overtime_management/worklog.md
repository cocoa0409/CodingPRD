# Worklog — task_2318_fire_department_staffing_overtime_management

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2318_fire_department_staffing_overtime_management/` and `workspace/` subdirectory. Task directory name was pre-allocated by the caller (no index scan performed).

## Step 2: SCAFFOLD.yaml (§1.0–§1.7) — 2026-09-01

11 entities, 7 state machines, 3 concurrency rules, 20 calculations, 18 ordered validations (priorities 1–18), 46 endpoints, 38 error codes, 4 roles (segregation_of_duties). `domain_name: fire-staffing-overtime`, `api_prefix: /fire-ops`. Complexity profile: primary `quota_allocation`, secondary `compliance_audit`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy, rate_threshold_triggers]`, topology `flat`, shape `cyclic`, consistency `immediate`.

## Step 3: SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 2026-09-01

18 instances, exactly 2 per each of the nine §0.5 difficulty rules. Fixes applied while authoring: 15 setup calls moved from `StaffingOfficer` to `CompanyOfficer` + `as_user_id` on seat endpoints; a rotation-violation trigger changed from `OVERTIME` to `REGULAR` (priority 10 only applies to REGULAR/KELLY_RELIEF); `hiring_order_selector` gained a `ROSTER_TYPE_FOR_MODE` mapping plus `FLSA_MAX_PERIOD_HOURS: 288` (it had compared `roster_type` against `hiring_mode` across two different enums).

## Step 4: SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 2026-09-01

84 instances across the nine claim-extraction sections (67 with full test recipes, 17 `excluded_because` stubs citing the §1.8 instance that already covers the corner): entities 12, state_machines 15, calculations 16, validations 17, endpoints 6, errors 8, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. Authored in three chunks and concatenated.

## Step 5: Audits — 2026-09-01

`scaffold_lint.py` → `VERDICT: clean lint` (46 endpoints, 11 entities, 18 §1.8 instances, 67 §1.9 recipe instances, 828 calls checked). Independent audits: all 38 error codes referenced by §1.8/§1.9; all 46 §1.5 endpoints appear as structured calls; instance names unique across both design files; no stub carries a `test_recipe` and every cited `difficulty_instance` resolves.

## Step 2: Generate Scaffold (subagent) — 2026-09-01T17:40:00.000Z

Scaffold complete at `/home/ubuntu/github/CodingPRD/tasks/task_2318_fire_department_staffing_overtime_management/`. No sibling task was read at any point — everything derives from the scenario text plus the generator skill's own spec (SKILL.md, `references/claim-extraction-guide.md`, `scaffold_lint.py`).

**Files**
- `SCAFFOLD.yaml` (§1.0–§1.7, 13 top-level keys, neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)
- `worklog.md` updated with the five build steps

**SCAFFOLD.yaml counts** — 11 entities, 7 state machines, 3 concurrency rules (`assignment-create`, `company-closure`, `availability-set`, all ERR_STALE_VERSION/412), 20 calculations, 18 ordered validations (priority 1 unauthenticated → 18 OT budget gate), 46 endpoints, 38 error codes, 4 roles. `domain_name: fire-staffing-overtime`, `api_prefix: /fire-ops`. Profile: primary `quota_allocation`, secondary `compliance_audit`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy, rate_threshold_triggers]`, topology `flat`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`. Domain mechanics: FLSA 7(k) 27-day period with the 204-hour threshold and 288-hour cap, four-platoon rotation with Kelly days, minimum crew staffing with closure-priority company closure, hiring rosters with pass limits, mandatory holdover/callback, seniority-ordered leave adjudication against staffing floors, encumbrance ledger, dual-variant OT forecasting, academy hiring signal.

**§1.8** — 18 instances, exactly 2 per each of the nine difficulty rules.

**§1.9** — 84 instances: 67 with full test recipes plus 17 `excluded_because` stubs. By section: entities 12, state_machines 15 (12+3), calculations 16 (12+4), validations 17 (12+5), endpoints 6, errors 8 (4+4), rbac 4, cross_cutting_complexity_layers 5 (4+1), consistency_model 1. Section/claim_type values are restricted to the claim-extraction guide's vocabulary; fixtures use disjoint stations 60–135 so instances never share state.

**Audits**
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (18 §1.8 + 67 §1.9 instances, 828 calls checked).
- All 38 error codes are reached by §1.8/§1.9. The 12 that §1.8 and the earlier corner chunks left uncovered (UNAUTHENTICATED, FORBIDDEN_ROLE, NOT_RESOURCE_OWNER, SEGREGATION_OF_DUTIES, the four aggregate-specific 404s, RESOURCE_NOT_FOUND, STALE_VERSION, VACANCY_NOT_OFFERABLE, NO_ELIGIBLE_CANDIDATE) are now asserted in the errors/rbac/complexity-layer instances.
- All 46 declared endpoints appear as structured calls (a late gap on five read endpoints — roster list, offer list, leave list, trade list, vacancy detail — was closed with one added Listing instance at station 135).
- Instance names unique across both design files; no stub carries a `test_recipe`; every `excluded_because.difficulty_instance` resolves to a real §1.8 name.

Deliberate above-Expert sizing: 46 endpoints and 18 chained validation priorities, with the hardest corners being the stale-version check preempting closure justification, the injury-leave six-hop cascade ending in the academy signal, and the selector where fairness hours override seniority.

## Step 3: Copy shared files — 2026-09-01T17:40:30.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-01T17:55:00.000Z

PRD generated at `workspace/PRD.md`.

**Size:** 424 lines. Ends at §5 with no audit footer.

**Sections**
- §1 Introduction — 3 paragraphs (operational pain point, system scope, the two non-negotiable design properties: deterministic selection, exact encumbrance accounting).
- §2 Global Specifications & System-Wide Principles — 11 subsections: 2.1 RBAC (`X-User-ID`/`X-User-Role`, four roles, opaque vs entity-backed identity resolution), 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`), 2.3 Pagination and List Ordering (limit 10/1/100, offset 0, all 11 per-collection orderings, all filter params), 2.4 Common Resource Properties, 2.5 The Logical Duty Clock (default `2026-08-01T00:00:00Z`), 2.6 Validation Precedence (the full 18-band ladder), 2.7 Optimistic Concurrency (three rules, both version fields, 412), 2.8 Rotation Calendar (platoon + Kelly slot arithmetic), 2.9 Hours/Cents/Rounding (three load-bearing rounding rules), 2.10 Encumbrance Ledger and Budget Posture (ledger invariant, basis-point bands), 2.11 Derived Staffing State and Cascade Propagation.
- §3 Business Logic & Workflows — 9 subsections: 3.1 station/apparatus/member/roster setup plus availability, 3.2 shift open + publish (vacancy materialisation, both publish branches), 3.3 seating gauntlet, 3.4 leave adjudication batch + revoke, 3.5 trades, 3.6 hiring order, 3.7 offer response + ops-run checkpoint, 3.8 company closure, 3.9 work periods, completion, and both analytics.
- §4 Endpoint Definitions — 46 rows, exactly 4 columns, preceded by the 201-create/200-otherwise paragraph.
- §5 Error Code Catalogue — 38 rows, exactly 2 columns.

**Contract 1 — Field-Name Coverage: PASS.** 134 identifiers checked (all `entities[].fields[].name`, all endpoint `input`/`query_params`/`path_params`, plus the computed-read output fields for overtime-forecast, academy-hiring-signal and leave-adjudication). Two passes run: pass 1 confirmed all 134 appear inside backticks; pass 2 confirmed 128 appear as standalone backticked tokens and flagged the six path params (`hiring_roster_id`, `shift_assignment_id`, `leave_request_id`, `trade_request_id`, `overtime_offer_id`, `work_period_id`) as appearing only inside §4 path cells — fixed by naming them explicitly in §2.6's 404-family paragraph. Final count: 134/134 standalone. All 4 common fields (`id`, `created_at`, `updated_at`, `version`) covered.

**Contract 2 — Rule Coverage: PASS.** All 18 validation priorities present in order with their error IDs and tie-break notes; all 3 OCC rules with per-rule justification; all 17 calculations traced (rotation calendar, required_staffing, certification multiset coverage, leave floor, posture branch order, vacancy generation, leave adjudication order, hiring-order selector for all three modes, continuous-duty merge, two-step offer pricing, ledger invariant, three-step budget gate, basis-point posture, hour ledger, FLSA dual-basis, both forecast variants, academy signal, closure selector, expiry sweep, seat capacity); every state transition covered including sibling-branch symmetry (DRAFT→HIRING vs DRAFT→STAFFED, HIRING→COMPLETED vs STAFFED→COMPLETED, staffing-run self-loops on both source states, all three trade decisions, both forecast methods); all cascade hop orders stated; all field defaults, types, bounds and uniqueness constraints stated. Verified all 38 error IDs appear in §1–§3 prose (not only in the §5 table) and all 74 enum values appear in backticks in prose.

**Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 beginning with `/`; zero bare HTTP method tokens; zero method+path combos; zero `/fire-ops` mentions. §3 uses state-transition framing, role+action verbs and capability descriptions throughout. Endpoint paths appear only in §2.5, §2.7 and the §4 table.

**Other audits:** no pseudocode operators (`==`, `>=`, `+=`, `!=`, `IN {`, `min(`, `max(`, `round(`, `ceil(`, `div`, `mod`, capitalised `AND`/`OR`/`NOT`) anywhere outside the fixed §2.2 JSON block; no fuzzy quantifiers; §2.2 byte-identical to source.

**Two scaffold inconsistencies encountered and resolved:**
1. `Vacancy.driver_source_id` — the field declaration and the relationship-pattern list both say null when `driver` is `VACANT_POSITION`, while the vacancy-generation calculation assigns the apparatus id. I went with the doubly-attested reading (null) and stated it explicitly in §3.2.
2. `WorkPeriod.scheduled_hours` vs `adjusted_scheduled_hours` — the entity descriptions define `scheduled_hours` as seat hours *plus* the adjustment accumulator, while the FLSA calculation defines a separate "adjusted_scheduled_hours" variable as scheduled hours plus adjustments (double-counting under the entity reading). I unified on the self-consistent entity framing (`scheduled_hours` already includes `adjusted_scheduled_hours`; the 288 cap and the projection both read that combined figure) and phrased the hiring-order cap identically so both readings agree numerically.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

## Step 6: Generate Implementation (subagent) — 2026-09-01T18:20:00.000Z

46 routes registered, and the implementation is complete and verified end-to-end.

## Files written

All under `workspace/implementation/` (20 files):

- `start.sh` (executable), `requirements.txt` (`flask>=3.0`)
- `app.py` — Flask app, `strict_slashes=False`, global `RLock` in `before_request` + `db.begin()`, `ApiError`/`HTTPException`/generic handlers, `PORT` env (default 10000), binds `0.0.0.0`
- `store.py` — in-memory dicts keyed by id, logical clock, request-scoped dirty set for `version` bumps
- `errors.py` (38 error codes → HTTP status), `envelope.py`, `auth.py`, `validation.py`, `calc.py` (Decimal/ROUND_HALF_UP arithmetic), `domain.py` (shared service layer: recomputation, cascades, selectors, 18-band checks)
- `routes/`: `__init__.py`, `common.py`, `master.py`, `members.py`, `duty_shifts.py`, `assignments.py`, `leave.py`, `trades.py`, `vacancies.py`, `offers.py`

## Endpoints

**46 routes** = 1 clock + 5 station (incl. `overtime-forecast`, `academy-hiring-signal`) + 3 apparatus + 4 firefighter + 3 hiring-roster + 8 duty-shift (`publish`, `staffing-run`, `leave-adjudication`, `company-closure`, `complete`) + 4 shift-assignment + 4 leave-request + 5 trade-request + 3 vacancy + 3 overtime-offer + 3 work-period.

## Boot confirmation

`PORT=10777 bash start.sh` from a cold process serves on the first probe: `GET /fire-ops/work-periods` → `200` with `data: []`, `total_count: 0` — empty, unseeded store, correct pagination meta, clock at the default `2026-08-01T00:00:00.000Z`. No `.db`/`.json`/`.sqlite` artifacts are created anywhere in the tree.

## End-to-end verification (live HTTP)

Exercised the full lifecycle and confirmed correct behavior at each step: station/apparatus/firefighter/roster creation; duty shift create (platoon rotation `2026-08-05` → A, Kelly slot 7, `required_staffing` 10, `leave_floor_headcount` 8); pre-publish seating; `publish` → 9 vacancies ordered by `closure_priority` (engine 10 → hazmat 20 → ladder 30); VOLUNTARY offer (cert-premium pricing 116712 cents, `expires_at` = clock + 120 min) → station `ot_committed_cents` tracks it → ACCEPT creating the OVERTIME seat; DECLINE charging `ot_pass_count`; MANDATORY_HOLDOVER (`offer_hours` floored to mode minimum, `expires_at` null, status MANDATED, seat + vacancy FILLED immediately); trade propose → countersign → RETURN_FOR_REVISION (back to PROPOSED, `revision_count` 1) → re-countersign → APPROVE (seat re-badged to counterparty as TRADE with premium 0); leave adjudication (SICK non-discretionary approved with backfill LEAVE vacancy + seat RELIEVED; BEREAVEMENT correctly denied on the floor); `revoke` restoring the seat and cancelling the backfill; injury cascade creating an INJURY vacancy; three successive closures (ladder → hazmat → refused); both forecast variants and the academy signal; work-period FLSA fields and payroll adjustment; `complete` posting premium to `ot_actual_cents` and zeroing committed.

Correct negative paths observed: `ERR_STALE_VERSION`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_CERTIFICATION_NOT_HELD`, `ERR_NO_ELIGIBLE_CANDIDATE`, `ERR_VACANCY_NOT_OFFERABLE`, `ERR_STAFFING_FLOOR_BREACH`, `ERR_LEAVE_NOT_REVOCABLE`, `ERR_CLOSURE_NOT_JUSTIFIED`, `ERR_FLSA_WORK_PERIOD_CAP_EXCEEDED`, `ERR_SHIFT_NOT_ELAPSED`, `ERR_SHIFT_NOT_HIRING`, plus 401 (missing *and* out-of-enum role), 403 `ERR_FORBIDDEN_ROLE`, 404 `ERR_STATION_NOT_FOUND`, 400 `ERR_INVALID_REQUEST` (missing field, `limit=0`, `offset=-1`, bad `method` param).

## Notable design decisions

1. **PRD is authoritative over SCAFFOLD.yaml** wherever they diverge.
2. **`POST /fire-ops/shift-assignments` rejects only COMPLETED shifts** — PRD §3.2 requires seating on DRAFT shifts so `publish` can count pre-existing seats (verified: DRAFT seat consumed a would-be vacancy, publish emitted 9 not 10).
3. **`/complete` freezes derived staffing fields** (no `recompute_shift`), matching the scaffold's exhaustive side-effect list; recomputing would leave a completed shift at `assigned_headcount` 0 / CRITICAL.
4. **`ot_committed_cents` is recomputed from the PRD §2.10 invariant** (OFFERED offers + SCHEDULED premium seats) after every relevant mutation rather than kept as a running tally, so no ledger drift; `ot_actual_cents` accrues only at completion.
5. **Version bumping via a request-scoped dirty set** flushed in `db.commit()`; new entities stay at `version` 1 (`db.untouch()` cancels creation-time recomputation bumps), and endpoints contractually required to bump call `db.touch(shift)` explicitly.
6. **Work periods are fully recomputed from source data** each time (scheduled/worked/leave hours, projected/final FLSA hours, premium on OPEN→scheduled / CLOSED→worked basis) rather than incrementally adjusted.
7. **Precedence reconciliations** where bands interleave: OCC before state; ownership before state; on `/offer` state → roster → selector → (candidate ? rest → capacity : capacity → no-eligible-candidate) → price → budget, with the FLSA cap as a pool filter rather than a raised error; MANDATORY_HOLDOVER bypasses the budget gate.
8. **Concurrency**: `threaded=True` plus a process-global re-entrant lock serializing request bodies, so cascades are atomic.

## Step 5: Generate Unit Tests (subagent) — 2026-09-01T19:10:00.000Z

The suite is complete.

## Files written

**Infrastructure — `test_helpers/`** (9 modules): `__init__.py` (package façade re-exporting the framework helpers plus local ones), `api_client.py` (`ApiClient` over every PRD endpoint, returning raw responses), `api_errors.py` (`ApiErrorId` for all 38 codes + expected-status map), `types.py` (`Role` and enum sets), `constants.py`, `factories.py` (payload builders), `fixtures.py` (~50 composite world-builders), `test_users.py` (role headers; entity-backed for `CompanyOfficer`/`Firefighter`), `assertions.py`.

**Tests — `test_suite/`** (18 modules, 126 test functions, **127 collected** — one parametrised case in test_10):

| Queue | Modules | Tests |
|---|---|---|
| A (Difficulty §1.8) | `test_01`…`test_09` | 36 (4 per rule) |
| B (Corner §1.9) | `test_10_entity_surface` 12, `test_11_state_machines` 14, `test_12_calculations` 12, `test_13_validations` 17, `test_14_endpoints` 10, `test_15_errors` 7, `test_16_rbac` 8, `test_17_cross_cutting` 8, `test_18_consistency` 2 | 90 |

New this session: `test_15_errors.py` (401/403 header split, `ERR_FORBIDDEN_ROLE` on seating as analyst, `ERR_NOT_RESOURCE_OWNER` on leave-for-a-colleague and answering another's offer, the eight per-class 404 codes), `test_16_rbac.py` (all four roles' own operations; five cross-role denials; the two analytics reads shared by the office roles only; trade-decision segregation of duties), `test_17_cross_cutting.py` (stale versions on all three OCC writes; the injury-leave cascade through to the academy signal; the third-decline pass limit emptying the pool; fairness hours outranking seniority), `test_18_consistency.py` (the acceptance cascade visible to the very next reads).

## Audits (all passing)

- **Tag audit**: every one of the 126 test functions carries **exactly one** `Design:` line; 85 distinct tags; zero untagged, zero dual-tagged, zero tags outside the design indices, zero tags pointing at `excluded_because:` stubs.
- **Coverage audit**: 85 non-stub instances exist (18 difficulty + 67 corner) and **all 85 are covered** — every difficulty instance has exactly 2 tests, every corner instance >=1. Nothing under-covered.
- **PRD-citation audit**: scripted extraction of every quoted fragment in every docstring, normalised and matched against `workspace/PRD.md` — zero unverified fragments (the two flagged strings are regex artefacts from adjacent citations, manually confirmed). No docstring mentions the scaffold or design; no `skip`/`xfail` anywhere.
- `python -m py_compile` clean on all modules; `pyflakes` clean on `test_suite/`; `pytest --collect-only` collects 127.

## Instances not translated

The 17 `excluded_because:` stubs only (state_machines 3, calculations 4, validations 5, errors 4, cross_cutting 1) — each is explicitly redirected by the design to a difficulty instance that already asserts it. **No non-stub instance was skipped**, so there are no PRD-filter gaps to report.

## Design-vs-PRD divergences resolved in favour of the PRD

Three corner recipes pinned `adjusted_scheduled_hours` where the PRD §3.9 definition (`scheduled_hours` = assignment sum **plus** `adjusted_scheduled_hours`) gives the other field: the clean-seat case (asserted adjusted 0 / scheduled 24), the offer-acceptance cap case (adjusted 270 / scheduled 270), the RBAC hour-adjustment case (adjusted 10 / scheduled 34) and the consistency case (adjusted 0 / scheduled 24). One design recipe also read an apparatus as `CompanyOfficer` without enrolling anyone, so a captain was added to give that header a real member id.

## Step 7: Run Tests and Iterate (subagent) — 2026-09-02T09:05:00.000Z

Verified clean. Final state confirmed:

- All 8 result files in the final sweep: `total=127, passed=127, failed=0, errors=0, skipped=0`; 127 distinct test names across the union.
- Zero REAL (assertion-level) failures in the discarded-attempt archive too.
- No stray `results.*.json`, `__pycache__`, `.bak`, or leftover server processes in the task tree; driver exited.
- Determinism grep re-confirmed: no `time.sleep`, `datetime.now`, `utcnow`, `time.time()`, `sqlite`, file writes, or `json.dump` anywhere in `implementation/` — storage stays in-memory Python dicts, nothing seeded.

## Summary

**Iterations run:** Numerous full 8-round parallel sweeps (sweeps 1–3, 20–33, 40–41), each round `prd-bench-local-run --isolation per-test-server` over the full 127-test suite, launched as two waves of four with `--timeout 240 --test-timeout 60`, plus per-round re-runs of any round the host aborted or starved. Final result: **sweep 41, all 8 rounds 127/127**.

**Tests deleted:** None. Every one of the 127 tests traced to a verbatim PRD.md sentence and passed under a PRD-faithful implementation; no PRD-silence or unique-derivability collapse pattern was found.

**Fixes applied to `test_helpers/`:** None. The one fixture-class bug lived in the test module itself.

**Fixes applied to `test_suite/`:**
- `test_suite/test_12_calculations.py` — module-level helper `_station_ready_to_hire_one_shift` hardcoded `seniority_rank=1` and was invoked twice inside `TestBudgetPostureBandBoundary::test_the_same_encumbrance_bands_within_or_watch_on_either_side_of_the_line`, so the second `create_firefighter` returned `400 ERR_INVALID_REQUEST - seniority_rank must be unique department-wide`. PRD §3.1 states verbatim that `seniority_rank` is "unique department-wide", so the implementation check is PRD-faithful and the test setup was wrong (STEP 2). Parametrised the helper (`seniority_rank=1` default, docstring citing PRD 3.1), threaded it into the `fx.create_firefighter` call, and passed `seniority_rank=2` at the second call site. An AST scan confirmed this was the suite's only instance of the pattern.

**Fixes applied to `implementation/`:** None — the artifact is byte-identical to its original state. A temporary `app.py` hardening (`BaseWSGIServer.request_queue_size = 128`) added in an earlier session was **reverted**, because its only evidence was a load-induced `ConnectionResetError(104)`, i.e. harness noise rather than a defect.

**Key finding on sweep noise:** every non-pass observed across all sweeps classified as runner-side infrastructure, never an assertion failure — overwhelmingly `subprocess.TimeoutExpired` on the harness's own per-test `lsof -ti:<port> -sTCP:LISTEN` port cleanup (whose `timeout=5` is hardcoded in `pytest_plugin.py::_kill_port` with no CLI knob), plus a few pytest-timeout setup aborts and connection resets. Root cause was host oversubscription by concurrent foreign pipelines (load average peaked near 440 on 32 cores with 550+ foreign runner processes). As load fell from 376 to ~110, per-round pass counts climbed monotonically to a full 127/127 in all eight rounds with no artifact change.

**One noted-but-unchanged observation** (deterministic, no test fails on it, so STEP 3 does not apply): `workspace/implementation/routes/members.py` lines 138–142, inside the `INJURY_LEAVE` branch of `set_availability`, reopens any vacancy already filled by the cancelled seat *in addition to* creating the PRD-mandated new `INJURY` vacancy. PRD line 202 enumerates only the new-vacancy side effect, while PRD line 224 does establish reopening for the un-seat pathway — a faithful reader could argue either way, so it was left untouched.

**Orchestrator note:** mid-loop, the orchestrator inspected `results.2.json` directly and confirmed that 104/104 failures in that sweep were `subprocess.TimeoutExpired` on the runner's own `lsof` port-cleanup step, and relayed to the subagent that such entries are harness noise to be excluded from the failure union (with instructions to stagger the 8 rounds into two waves of four and raise `--timeout`/`--test-timeout`). This prevented misdiagnosis of contention artifacts as test/implementation defects.

## Step 8: Finalize PRD (subagent) — 2026-09-02T09:20:00.000Z

Done. `PRD_FINALIZED.md` created at `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 424 lines; `PRD_FINALIZED.md`: 424 lines — 0% line-count delta; 2 lines revised in place (0.47% of lines touched), no lines added or removed, no new sections.

## Changes
- **§3.1 (Members / enrolment, line 196)** — revise — pinned the enforcement of the `seniority_rank` uniqueness constraint: a duplicate is refused with `ERR_INVALID_REQUEST` (400), the comparison spans all existing members regardless of `employment_status`, and the test is applied *after* `station_id`/`acting_supervisor_id` resolution rather than with the §2.6 shape band — `implementation/routes/members.py:39-48`.
- **§3.1 (Availability changes, line 202)** — revise — pinned the two undocumented parts of the `INJURY_LEAVE` cascade: any vacancy whose `filled_by_assignment_id` is a cancelled seat moves to `OPEN` with the field cleared (in addition to the new `INJURY` vacancy), and the new `INJURY` vacancy copies `apparatus_id`/`required_certification` from the vacated seat and takes a continuing `seat_index` — `implementation/routes/members.py:132-151`, `implementation/domain.py:280-304`.

## Per-edit pre-edit search log

**Edit 1 — subject: uniqueness-constraint enforcement on member enrolment (error code + evaluation position).**
- (b) Paths enumerated: `grep -rn "unique"` across `implementation/` (2 hits: `routes/members.py:47`, `routes/master.py:245`); `grep -rn "ERR_INVALID_REQUEST"` across `implementation/` (all business-uniqueness/derived-shape refusals — `master.py:43` fiscal date order, `master.py:102` forecast `method`, `master.py:234` cert-list length, `master.py:244` `unit_designation`, `master.py:311` roster triple, `duty_shifts.py:34` one-shift-per-station-per-date, `members.py:47` seniority — all 400 via `errors.py:8`); read `routes/members.py:16-72` for the exact check position (after `domain.require` on station and supervisor); read `routes/master.py` create_apparatus/create_roster and `routes/duty_shifts.py` create_duty_shift to confirm every sibling uniqueness rule also yields `ERR_INVALID_REQUEST`; `grep -rn "seniority_rank"` to confirm no other write path validates or mutates the field (remaining hits are ordering keys in `members.py:99`, `domain.py:493/504/514`, `duty_shifts.py:159`).
- (c) Adjustment: scoped the sentence to enrolment/`seniority_rank` only rather than stating a general rule for all uniqueness constraints (even though all siblings do return `ERR_INVALID_REQUEST`), and scoped the ordering claim to the two references this endpoint actually resolves; added "whatever that member's `employment_status`" because the impl loop excludes nothing (a `SEPARATED` member still blocks the rank).

**Edit 2 — subject: reopening of a vacancy whose filling seat is removed, and the field derivation of a cascade-created vacancy.**
- (b) Paths enumerated: `grep -rn "filled_by_assignment_id"` across `implementation/` — writers are `assignments.py:101` (seat fills vacancy), `assignments.py:165-168` (cancel reopens → `OPEN`, cleared), `members.py:139-142` (INJURY_LEAVE reopens → `OPEN`, cleared), `offers.py:113` and `vacancies.py:155` (mandated holdover / offer accept set FILLED), `domain.py:286` (creation default null); read `routes/duty_shifts.py` leave-adjudication (`:192-205`) and `complete` (`:283-294`), `routes/leave.py` revoke (`:100-113`), and `duty_shifts.py` company-closure (`:258-261`) to confirm no *other* seat-removal path reopens a filled vacancy — the RELIEVED path creates a `LEAVE` vacancy without reopening, close-out/closure/revocation only touch `OPEN`/`OFFERING` vacancies via `domain.cancel_vacancy_and_rescind`; read `domain.create_vacancy` and `domain.next_seat_index` to verify the copied fields and the seat-count semantics, and compared against §3.4's existing verbatim phrasing of the same helper.
- (c) Adjustment: wrote "moves to `OPEN`" rather than "`FILLED → OPEN`" because the impl sets the status unconditionally; confined the reopening clause to the `INJURY_LEAVE` branch so it cannot be read as a general rule for `RELIEVED` seats (which do not reopen); reused §3.4's exact "a `seat_index` continuing that company's seat count for the shift" wording so the two callers of `next_seat_index` stay described identically; stated the two-open-vacancies consequence conditionally ("a cancelled seat that had *itself* filled a vacancy") since a seat that filled none yields only one.

## Step 9: Complete PRD (subagent) — 2026-09-02T09:40:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Source vs. output

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 424 | 424 |
| chars | 89,795 | 100,359 |

Char delta **+10,564** (net +10,476 by byte read). 36 lines changed, all in-paragraph; **no new sections, no new paragraphs, no line-count change**.

## Counts
- **ambiguity-pins: 35**
- **mismatch-revisions: 3**

## Changes

- §2.2 Success envelope — insert — ambiguity — `api_request_id` is `req_` + 20 upper-case alnum; `api_request_timestamp` reads the *logical* clock, not wall clock; `response_type` is `"object"` for computed reads / batch summaries / the clock capability — `envelope.py:20,26,55`, `store.py:52`
- §2.3 Pagination — insert — ambiguity — non-integer / out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST` 400, evaluated after 401/403; `total_count` pre-window, `has_more` semantics — `envelope.py:63-99`
- §2.3 Ordering — insert — ambiguity — store insertion order is the tie-break *beyond* `created_at` (which is clock-stamped and therefore often equal) — `store.py:106-108`
- §2.3 Filters — insert — ambiguity — string-equality match, null field never matches, undeclared query params ignored — `routes/common.py:12-26`
- §2.4 Common properties — insert — ambiguity — `version` starts at 1; `updated_at` == `created_at` on creation; both read the logical clock — `store.py:63-71`
- §2.4 Recomputation — **revise** — **mismatch** — PRD said recomputation is unconditionally a mutation; impl bumps nothing when every derived field is unchanged (names trade approval and voluntary/callback dispatch as the two no-op cases) — `domain.py:187-193,275`, `store.py:89-96`
- §2.5 Logical clock — insert — ambiguity — `now` required, offset forms accepted and converted; returns `data` of `{"now": <ISO ms>}` — `routes/master.py:16-22`
- §2.10 Ledger — **revise** — **mismatch** — "at every observable point" narrowed: ledger is re-derived from scratch, and leave adjudication is the one path that leaves it un-swept — `domain.py:197-225`, `routes/duty_shifts.py:209-213`
- §2.10 Posture — insert — ambiguity — zero `fiscal_ot_budget_cents` bands directly: `WITHIN` at zero consumption, `OVER` above, never `WATCH` — `calc.py:178-179`
- §3.1 Apparatus — insert — ambiguity — `status` suppliable at registration; cert-length test runs *before* station resolution, `unit_designation` uniqueness (`ERR_INVALID_REQUEST`) *after* — `routes/master.py:227-246`
- §3.1 Hiring rosters — insert — ambiguity — duplicate triple → `ERR_INVALID_REQUEST` 400, after station resolution — `routes/master.py:302-313`
- §3.1 Availability — insert — ambiguity — only `INJURY_LEAVE` and `ACTIVE` cascade; `SEPARATED` / omitted status touches nothing — `routes/members.py:129-165`
- §3.2 Opening a shift — insert — ambiguity — duplicate station+date → `ERR_INVALID_REQUEST`, before the rotation check; `version` 1; the *whole* derived set (incl. `staffing_gap`, `certification_gap_count`, `open_vacancy_count`) computed at `DRAFT` — `routes/duty_shifts.py:28-59`
- §3.3 Seating — insert — ambiguity — admissible from `DRAFT`/`HIRING`/`STAFFED`; only `COMPLETED` refuses, with `ERR_SHIFT_NOT_HIRING`, checked right after the version check — `routes/assignments.py:49-52`
- §3.3 Seat creation — **revise** — **mismatch** — `projected_premium_cents` is *always* zero on this endpoint whatever the `assignment_type`; non-zero premiums come only from offer acceptance and mandated holdover — `routes/assignments.py:92`
- §3.3 Vacancy match — insert — ambiguity — ties broken by lowest `seat_index`, then `created_at` — `routes/assignments.py:15-23`
- §3.3 Un-seating — insert — ambiguity — `reason` required non-empty; the `CANCELLED` seat retains its premium/hours/certification and the ledger credit is by re-derivation — `routes/assignments.py:147,161`
- §3.4 Filing — insert — ambiguity — no shift-status gate and no seat required — `routes/leave.py:28-35`
- §3.4 Adjudication — insert — ambiguity — requires `HIRING`/`STAFFED` (`ERR_SHIFT_NOT_HIRING`); batch opens by re-deriving the shift — `routes/duty_shifts.py:149-153`
- §3.4 Decision index — insert — ambiguity — stamped on denied requests too; multi-seat member → earliest seat by `created_at` — `routes/duty_shifts.py:172-180`
- §3.4 Approval cascade — insert — ambiguity — no hop touches the station; relieved overtime premium stays in `ot_committed_cents` — `routes/duty_shifts.py:209-213`
- §3.4 Response — insert — ambiguity — reported floor is the opening figure, resulting figures post-recompute; shift version bumps even on an empty queue — `routes/duty_shifts.py:152,213-227`
- §3.5 Trade proposal — insert — ambiguity — neither proposal nor countersignature is gated by shift status — `routes/trades.py:47-56,106-114`
- §3.5 Countersign — insert — ambiguity — traded seat = requester's earliest `SCHEDULED` seat; with no seat, `NONE` cert and 24 hours are substituted — `routes/trades.py:117-119`
- §3.5 Decision — insert — ambiguity — `note` may be omitted/null/empty; segregation precedes the state test (403 over 409) — `routes/trades.py:158,162-168`
- §3.5 Approve — insert — ambiguity — recomputation is a no-op so the shift's `version`/`updated_at` don't move; nothing but the seat is re-checked — `routes/trades.py:184-208`
- §3.6 Dispatch input — insert — ambiguity — `offer_hours` required, no declared bounds — `routes/vacancies.py:55`
- §3.6 Ceilings — insert — ambiguity — measured on payable hours; capacity is evaluated even with an empty pool, so it outranks `ERR_NO_ELIGIBLE_CANDIDATE` — `routes/vacancies.py:87-92`
- §3.6 Voluntary/callback dispatch — insert — ambiguity — the shift record is untouched (no version move); only the station is re-derived — `routes/vacancies.py:132-165`
- §3.7 Offer response — insert — ambiguity — `response` enum is `ACCEPT` / `DECLINE` — `validation.py:23`
- §3.7 Decline — insert — ambiguity — the pass is charged identically for callback offers (voluntary hours charged, `ot_pass_count`, `PASSED` flip) — `domain.py:344-358`
- §3.8 Closure — insert — ambiguity — `justification` required non-empty and stored nowhere; posture read as stored, not re-derived — `routes/duty_shifts.py:240,247`
- §3.9 Covering period — insert — ambiguity — any status; earlier-created wins ties; no covering window → zero-hour base, cap unbreachable — `domain.py:76-85`, `domain.py:425-429`
- §3.9 Hour adjustment — insert — ambiguity — `adjustment_hours` unbounded (negatives allowed), `reason` required non-empty, no period-status gate, cap test only on the `SCHEDULED` basis — `routes/members.py:212-229`
- §3.9 Close-out — insert — ambiguity — "involved members" = anyone holding an assignment in *any* status; leave-only members excluded; successor enters at `version` 1 — `routes/duty_shifts.py:283-325`
- §3.9 Forecast — insert — ambiguity — `method` is a query param; bad value → `ERR_INVALID_REQUEST`, but *after* the station 404 — `routes/master.py:98-104`
- §3.9 Run rate — insert — ambiguity — `elapsed_days` <= 0 yields `daily_run_rate_cents` 0 with no division — `routes/master.py:151-154`
- §4 Preamble — insert — ambiguity — the offer dispatch returns 201 with the offer; per-endpoint `data` record named; leave adjudication is the sole summary payload — `routes/vacancies.py:166`, `envelope.py:44-55`

## Final verification (orchestrator) — 2026-09-02T09:45:00.000Z

Re-ran a full 8-round `--isolation per-test-server` sweep after Step 7 exited (Step 7 had cleaned up its own result files). Seven rounds returned 127/127 immediately; round 8 returned 126/127 with a single `requests.exceptions.ConnectionError: RemoteDisconnected` on `test_a_countersignature_one_second_later_is_refused` — a load-induced connection reset with no assertion involved. Re-running round 8 alone returned 127/127. Final on-disk state: `results.{1..8}.json` all `passed=127, total=127, failed=0, errors=0, skipped=0`.
