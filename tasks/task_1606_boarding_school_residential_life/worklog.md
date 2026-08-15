# Worklog — task_1606_boarding_school_residential_life

## Step 1: Create task directory — 2026-08-14T01:18:00.000Z

Task directory `tasks/task_1606_boarding_school_residential_life/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions (no index scan, no other task dir touched).

## Step 2: Generate scaffold — 2026-08-14T02:16:03.000Z

All three artifacts are complete, parse cleanly, and pass the skill's mechanical lint with zero violations. Final summary:

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1606_boarding_school_residential_life/SCAFFOLD.yaml` (109 KB) — §1.0–§1.7 only
- `/home/ubuntu/github/CodingPRD/tasks/task_1606_boarding_school_residential_life/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (62 KB) — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1606_boarding_school_residential_life/SCAFFOLD_CORNER_DESIGN.yaml` (134 KB) — single top-level key `scaffold_corner_design`

### Counts
- **SCAFFOLD**: 19 entities, 12 state machines, 2 OCC concurrency rules, 11 calculations, 44 ordered validations, **94 endpoints**, **45 errors** (all referenced), 8 roles (7 entity-backed + opaque SchoolAdmin)
- **Difficulty design**: 19 instances — every rule ≥2; `combinatorial_formula` carries 3 (one per mode (a) tiered/nested-min-max, (b) per-line-vs-aggregate rounding, (c) pinned evaluation order)
- **Corner design**: 69 instances across all 9 claim-guide sections (entities 7, state_machines 12, calculations 6, validations 29, endpoints 1, errors 8, rbac 3, cross_cutting 2, consistency 1); 60 active + 9 `excluded_because` stubs citing §1.8 instances

### Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(94 endpoints, 19 entities, 19+60 instances, 720 calls scanned.) Additional scripted audits passed: file split, cross-file instance-name uniqueness (88 names), stub references, all 45 errors triggerable, no forbidden race vocabulary, envelope verbatim, OCC hard constraints.

### Notable design decisions
- **Profile**: compliance/audit primary + quota/allocation secondary; flat FK topology (per diversity guidance); cyclic machines (discipline appeal loop SANCTIONED→APPEALED→SANCTIONED with appeal cap, duty-swap SCHEDULED↔SWAP_PENDING, med-order ACTIVE↔HOLD) plus **parallel state dimensions on Student** (enrollment × standing).
- **Logical clock** `POST /reslife/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z` drives all sweeps: leave OVERDUE/EXPIRED, BreakPeriod lifecycle with cascades (housing auto-checkout, storage EXPIRED), duty-shift MISSED.
- **Two genuine OCC races**: assignment-create on `Student.version` (PROPOSED supersede) and duty-shift-create on `Dorm.version` (SCHEDULED supersede). Replay audit forced one scaffold fix: validation 38 (shift conflict) now excludes the to-be-superseded shift so the fresh-version retry succeeds.
- **Two engineered priority conflicts**: state(6) vs fiscal(40) on a cascade-cancelled leave, and safety(11) vs referential(14) on a held order — validation 10 deliberately excludes HOLD so `ERR_MEDICATION_ON_HOLD` provably wins over `ERR_DOSE_ALREADY_LOGGED`.
- **All numeric asserts pre-computed as literals**: allowance 7→4 across a standing flip; storage rounding 213+213=426 vs aggregate 425; break-housing pinned order 20000/426/2043/18383; compatibility 32→68 on questionnaire PATCH; curfew tiers 0/1/2 at exactly 22:30/22:45/22:46; standing boundary 9=GOOD / 10=PROBATION; dose-zero auto-COMPLETED.
- **Segregation of duties** throughout discipline (reporter ≠ hearing officer, MINOR outcome recorder, appeal decider) with dedicated negative tests; international students route family decisions Parent→Guardian→Dean-proxy with a guardian-suspension cascade that denies pending leaves.
- Mid-run repair handled: YAML flow `grounds:` lists containing `errors[...]` tokens were quote-wrapped programmatically and a leaked heredoc line removed; final parse + lint clean.

No sibling task under `tasks/` was inspected at any point; the scaffold was derived solely from the scenario text and the skill specification.

(Orchestrator note: the Step 2 subagent was interrupted once by an API connection error after writing SCAFFOLD.yaml and difficulty rules 1–3; it was resumed via SendMessage and completed rules 4–9, the full corner design, and the lint pass.)

## Step 3: Copy shared files — 2026-08-14T02:17:07.000Z

Copied `INSTRUCTION.md` to `tasks/task_1606_boarding_school_residential_life/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T02:24:07.000Z

Done. PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1606_boarding_school_residential_life/workspace/PRD.md`.

### Summary

**Output:** `workspace/PRD.md` — 374 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC, 2.2 Response Structure (verbatim block), 2.3 Pagination, 2.4 Logical Clock & Sweeps, 2.5 Common Resource Properties, 2.6 Validation Order, 2.7 OCC, 2.8 Derived Counters/Standing/Precision, 2.9 Cascading Consistency
- §3 Business Logic: 3.1 Terms/Dorms/Rooms, 3.2 People, 3.3 Assignments & Roommates, 3.4 Leave Requests, 3.5 Duty Shifts & Night Checks, 3.6 Health Center, 3.7 Discipline, 3.8 Breaks/Housing/Storage, 3.9 Sign Events & Curfew
- §4 Endpoint table (89 rows, 4 columns), §5 Error catalogue (45 rows, 2 columns)

**Zero-Silence audit (all PASS):**
- Contract 1 Field-Name Coverage: 125 required identifiers (entity fields + endpoint inputs + common fields + `current_utc`), 125 present in backticks, 0 missing (two-pass; second pass caught `early_bird` and decision-value enums `APPROVE`/`DENY`/`UPHOLD`/`OVERTURN`, now fixed).
- Contract 2 Rule Coverage: 44 validations with priority ordering expressed (global gauntlet in §2.6; hold-before-duplicate-dose in §3.6; OCC-before-shift-conflict in §2.7); 2 OCC rules with write-endpoint + occ-field + `ERR_STALE_VERSION`/412; all 11 state machines' transitions with preconditions paired to error IDs and all cascades (term close, withdrawal, guardian suspend, break close, SUSPENDED standing); all 9 calculations in reconstruction-safe prose (grade bases 4/4/6/8, standing multipliers 1.0/0.5/0 with floor-before-bonus and cap 10; compatibility weights 12/8/8/4 with floor 0; curfew ladder 0/1/2/3 at inclusive 15/60 minute boundaries; night-check tables for both kinds; 250-cent rate with 15% early-bird at 30 days and per-line round-half-up including the 426-vs-425 counterexample; pinned 4-step break-housing waterfall with 20000/5000 constants and EXPIRED-fee-retained semantics).
- Contract 3 §3 Path Purity: 538 backticked tokens in §3, zero paths, zero bare HTTP methods, zero method+path combos.

**Notable wording decisions:**
- Used "the enrollment transition with a `to_status`" and "the family decision carries a `decision` of `APPROVE` or `DENY`" style framing to keep request-body field names in §3 without endpoint paths.
- The scaffold's §1.7 prose "Parent/Guardian only for their own child/ward; DormParent dorm-scope" was split between §2.1 (identity binding) and §3.4/§3.5 (per-action scope checks), distinguishing `ERR_NO_CONFIRMED_RESIDENCY` (no residency at all) from ordinary `ERR_FORBIDDEN` scope failure (residency in another dorm).
- The early-bird boundary "at least 30 days before `starts_on`" preserves the scaffold's `<=` inclusivity; curfew "Friday or Saturday" weekend selection preserves the `{Fri, Sat}` set.
- Append-only entities (`SignEvent`, `NightCheck`, `MedicationAdministration`) are explicitly stated to lack `updated_at` and `version`, per `common_fields: false`.

## Step 5: Generate unit tests — 2026-08-14T03:05:00.000Z

All generation and self-checks complete. Final summary:

### Files written

**Stage 1 — `test_helpers/`** (9 files, at `/home/ubuntu/github/CodingPRD/tasks/task_1606_boarding_school_residential_life/test_helpers/`):
- `types.py` — 26 status/role enums + 19 entity TypedDicts; append-only `SignEvent`/`NightCheck`/`MedicationAdministration` correctly omit `updated_at`/`version` (PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~66 methods, all under `/reslife`)
- `api_errors.py` — 45 `ApiErrorId` members + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_standing_matches_points` (§2.8 thresholds)
- `factories.py`, `constants.py` (allowance tiers, standing thresholds, 250¢/rate, 20000¢ room charge, 5000¢ deposit cap, 168h appeal window, 2h/6h sign-out window)
- `test_users.py` — `TEST_USERS` + 7 per-instance `make_*_headers` builders (all non-admin roles are entity-backed; fixtures thread real entity ids)
- `fixtures.py` — composite setup helpers (state progression, confirmed residency, leave lifecycle to APPROVED, duty shifts with fresh OCC version reads, MINOR/MAJOR sanction paths, break/storage/international-student scenarios)
- `__init__.py` — barrel export

**Stage 2 — `test_suite/`**: `conftest.py` + 7 test files (`test_01` envelope/students/guardians, `test_02` housing/assignments, `test_03` leave requests, `test_04` duty shifts/night checks, `test_05` health center, `test_06` discipline, `test_07` breaks/storage/curfew).

### Tests emitted

- **Queue A (Difficulty): 38 tests** — exactly 2 per instance × 19/19 instances, 0 under-covered.
- **Queue B (Corner): 62 tests** over **60/60** non-stub instances (2 instances got a second test where the recipe asserts both a rejection leg and a success leg).
- **Stubs: 9 not translated** (1 calculations + 8 errors); all `excluded_because` cross-references verified to resolve to real difficulty instances.

### Instances skipped

**None.** Every instance passed the PRD-first two-condition filter. Notably, both `priority_pair_validation_conflict` instances were kept because PRD §2.6 (state-before-fiscal) and §3.6 (hold-error-before-duplicate-dose) state the precedence explicitly in prose.

### Self-check results

- **Stage 1**: all files parse; `test_helpers` imports cleanly against the framework; every `api.*` call and `from test_helpers import` in the suite resolves.
- **Stage 2 tag audit**: all 100 tests carry exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line as the final docstring line; every tag resolves to a real non-stub instance; no untagged/dual-tagged/stub-pointing tests.
- **PRD citation audit (C1/C2/C3)**: 141 quoted fragments extracted from docstrings — 100% survive whitespace-normalized literal grep of `workspace/PRD.md` (3 initial failures fixed: a fused §2.2 bullet pair, an ellipsized §2.6 quote expanded to the full sentence, and a spurious article in the §3.2 gender quote).
- **Error-id audit**: all 44 asserted error ids appear in PRD prose, not just the §5 table.
- **Cleanliness**: no `skip`/`skipif`/`xfail` markers; no scaffold references in generated code; `pytest --collect-only` collects all 100 tests without error.

## Step 6: Generate implementation — 2026-08-14T03:05:30.000Z

Implementation complete and verified. Summary:

### Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1606_boarding_school_residential_life/workspace/implementation/`:

- `start.sh` — executable launcher; guarded dependency install (`python3 -c "import flask"` check so per-test reboots skip pip), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — entry point (imports `server.app`, runs on `$PORT`); kept separate from the app object to avoid the `__main__` double-registration trap
- `server.py` — Flask app object + error handlers (`ApiError`, 404/405, catch-all)
- `db.py` — in-memory `STORE` dicts (empty at every boot, no seeding), logical clock initialized to exactly `2026-08-01T00:00:00Z`, ISO-8601 3-fractional-digit timestamp formatting, ID/sequence generation
- `errors.py` — full 45-entry error catalog with HTTP statuses
- `helpers.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields only on lists), pagination (limit default 10/min 1/max 100, offset 0, sorted by `created_at` ascending with insertion-order tiebreak), auth (`X-User-ID`/`X-User-Role`, 8 roles), typed field validators
- `services.py` — derived counters (occupancy, wards, dose ledger, used_cuft), weekend allowance, compatibility score, late-points ladders, standing reevaluation with SUSPENDED leave-cancel cascade, term-close/withdrawal/break-close cascades, clock sweeps, all serializers
- `routes_core.py` — clock, terms, dorms, rooms, parents, guardians, staff, students, dorm assignments
- `routes_flow.py` — leave requests, sign events, duty shifts, night checks
- `routes_health_discipline.py` — medication orders/administrations, discipline cases, break periods/housing, storage

### Coverage

- **Endpoints: 66/66** from PRD §4 implemented (95 Flask route rules counting method+path pairs)
- **Errors: 45/45** from the PRD §5 / scaffold §1.6 catalog implemented with exact IDs and HTTP statuses
- Validation pipeline follows the scaffold priority order: 401 auth → 403 role/identity → 404 path+body FK → 400 missing/malformed → 422 domain → 409 state → numbered business rules (medication HOLD outranks duplicate-dose; OCC before shift-conflict; confirm-time order per PRD §3.3 narrative)

### Architecture notes

- Pure in-memory dict store; state resets every boot. Logical clock never reads wall time; `POST /reslife/_clock/set_current_utc` runs all sweeps (break lifecycle with housing/storage cascades, leave EXPIRED/OVERDUE, shift MISSED).
- OCC: `expected_student_version` on assignment create, `expected_dorm_version` on duty-shift create → `ERR_STALE_VERSION` 412.
- Derived fields (occupancy, `doses_remaining`, `used_cuft`, `weekend_leaves_used`/allowance, provisional points) computed on read; `version` bumps only on material mutations including cascaded writes; append-only `SignEvent`/`NightCheck`/`MedicationAdministration` carry only `id`+`created_at`.
- Money math uses `Decimal` with ROUND_HALF_UP per reservation line (212.5→213, matching the spec's 426-vs-425 example); break-housing fee uses the pinned 4-step evaluation order.

### Verification

- Three smoke suites (~180 assertions) covering CRUD, all state machines, cascades (term close, withdrawal, guardian suspend, break close, SUSPENDED standing), OCC, roommate scoring, allowance exhaustion, curfew ladders, swap conflicts, medication hold/witness/auto-COMPLETED, discipline appeal loop, storage fees — all pass on fresh boots.
- `prd-bench-local-run --isolation per-test-server` against a 4-test probe suite: **4/4 passed**, confirming clean boot-per-test, PORT env handling, and cross-restart state isolation.

One notable bug caught during verification: routes were originally registered via `from app import app` while running `python3 app.py`, which double-imports the module and serves a route-less app object — fixed by moving the app object into `server.py`.

## Step 7: Run tests and iterate — 2026-08-14T03:20:00.000Z

Clean 8-round sweep achieved. Final summary:

**Iterations run: 2** (round 1: 80/100 in all 8 rounds — 20 distinct failures, fully deterministic; round 2 after fixes: 100/100 in all 8 rounds, zero flakiness)

**Tests deleted: none.** Every failing test traced to a verbatim PRD rule with unique derivability; all failures were genuine bugs.

**Fixes applied to `test_helpers/` (1):**
- `test_helpers/fixtures.py` — `setup_leave_approved()` gained an explicit `destination="Boston"` parameter forwarded to `file_leave`. Previously a caller's `destination=` kwarg leaked through `**kwargs` into `setup_confirmed_residency` → `make_student()`, raising `TypeError: make_student() got an unexpected keyword argument 'destination'`. (Fixed `test_day_pass_does_not_consume_weekend_allowance`.)

**Fixes applied to `implementation/` (2):**
- `workspace/implementation/db.py` — `new_id()` changed from `uuid.uuid4().hex` (32 undelimited hex chars) to `str(uuid.uuid4())` (canonical hyphenated 8-4-4-4-12 form). PRD §2.5 requires "`id` (a server-minted UUID with no type prefix)"; "no type prefix" forbids prefixes like `stu_`, not the canonical UUID string form that `is_valid_uuid` validates. This single fix resolved 18 of the 20 failures.
- `workspace/implementation/routes_flow.py` — `night_check_create()` now rejects recording on a terminal shift (`COMPLETED`/`MISSED`/`CANCELLED`) with `ERR_INVALID_STATE`, placed after payload well-formedness and before the business-rule checks per the §2.6 gauntlet. PRD §3.5 states "`COMPLETED`, `MISSED`, and `CANCELLED` are terminal" and night checks are recorded "During the shift". (Fixed `test_night_check_on_completed_shift_rejected`.)

**Final state:** 8/8 parallel rounds at 100/100 tests passing under `--isolation per-test-server`.

## Step 8: Finalize PRD — 2026-08-14T03:35:00.000Z

Done. PRD_FINALIZED.md is written with exactly two targeted edits.

### Summary

**Line counts:** PRD.md 374 lines; PRD_FINALIZED.md 374 lines — 0% delta (2 lines revised in place, none added or removed).

**Changes:**
- §2.5 — revise — pinned resource `id` as "a server-minted UUID rendered in the canonical hyphenated 8-4-4-4-12 string form, with no type prefix" (was: "a server-minted UUID with no type prefix", which admitted both `uuid4().hex` and `str(uuid4())`) — `implementation/db.py:45-46`.
- §3.5 — revise — extended the terminal-states sentence: "recording a night check against a shift in any of these terminal states is rejected with `ERR_INVALID_STATE` (HTTP 409) — the state-legality check of the §2.6 gauntlet" — `implementation/routes_flow.py:530-532`.
- The `test_helpers/fixtures.py` `setup_leave_approved()` fix is a pure fixture bug (kwargs leak); no PRD edit.

**Per-edit pre-edit search log:**

*Edit 1 (§2.5 UUID form):*
- (a) Subject: server-minted resource `id` string format.
- (b) Enumerated: `db.py:45-46` (`new_id()` — sole ID factory); `services.py:45-53` (`new_common`/`new_event` — the only two entity constructors, reached from all 17 creation sites across `routes_core.py`, `routes_flow.py`, `routes_health_discipline.py`); serializers (`_base`, `ser_sign_event`, `ser_night_check`, `ser_med_admin`) pass `id` through verbatim; `db.py:71-74` `new_request_id()` is a separate `req_`-prefixed meta-envelope id already pinned in §2.2, outside this sentence's scope; input-side lookups (`get_or_404`, `check_fk`) do plain key lookups with no format validation.
- (c) Wording keeps the original "no type prefix" clause and adds only the canonical-form pin; it constrains what the server mints, not what it accepts (impl validates nothing on input), so no off-site path is mis-described.

*Edit 2 (§3.5 night check on terminal shift):*
- (a) Subject: recording a night check against a terminal-state duty shift.
- (b) Enumerated: `routes_flow.py:517-563` `night_check_create` — the only NightCheck-creation path; rejection sits after `check_fk`/`req_string`/`req_enum` (well-formedness) and before term/enrollment/duplicate/residency business rules, matching §2.6's placement of `ERR_INVALID_STATE`; `routes_flow.py:455-476` `shift_request_swap` and `479-496` `shift_swap_respond` — SWAP_PENDING is a non-terminal state NOT in the rejected set, so checks remain recordable on SWAP_PENDING shifts by the current assignee; `routes_flow.py:500-514` `shift_complete` (separate state rule, untouched); `services.py:343-348` MISSED sweep; `services.py:367-371` `shift_bed_checks_complete` (read-only); `night_check_list`/`night_check_get` (read-only).
- (c) Deliberately avoided "only on a SCHEDULED shift" phrasing — impl permits recording on SWAP_PENDING — and instead pinned exactly the three named terminal states; placement is delegated to the §2.6 gauntlet reference rather than a bespoke ordering sentence, matching the impl's actual check position.

## Step 9: Complete PRD — 2026-08-14T04:05:00.000Z

All edits applied and verified for coherence. The task is complete.

### Summary

**Files:** `workspace/PRD_FINALIZED.md` (374 lines / 54,671 chars) → `workspace/PRD_COMPLETED.md` (377 lines / 60,414 chars; **+3 lines, +5,743 chars**).

**Counts:** 33 ambiguity-pins, 5 mismatch-revisions (38 change sites total; several bullets bundle co-located sub-pins).

#### Mismatch revisions (PRD described behavior impl does not exhibit)

- **§2.1 — revise — mismatch —** RBAC ordering: PRD claimed ownership scoping runs before existence resolution; impl universally loads the resource first (404) and scopes after. Revised to "authentication first, role authorization second, existence third, scoping fourth" with endpoint exceptions pinned in §3.4/§3.5 — `helpers.py:121-143`, e.g. `routes_core.py:492-498`, `routes_flow.py:487-490`.
- **§2.6 — revise — mismatch —** Gauntlet rewritten to impl's actual order (auth → role + staff-identity binding → path existence), with three verified invariants (body FKs before structural; structural before from-state; from-state before business) and the dean-proxy identity-binding exception pinned — all route files.
- **§3.1 — revise — mismatch —** `room_number` "unique within the dorm" softened: impl never enforces uniqueness (`routes_core.py:194-209`).
- **§3.5 — revise — mismatch —** shift assignee `staff_id`: PRD said "naming a dorm parent"; impl validates existence only, not role/`is_active` (`routes_flow.py:388-391`).
- **§3.8 — revise — mismatch —** `used_cuft` "tracks exactly that sum" (per unit+break) revised: impl sums `volume_cuft` over all `RESERVED`/`CHECKED_IN` reservations of the unit across every break (`services.py:141-146`).

#### Ambiguity pins (PRD silent; pinned to impl)

- **§2.1 — insert ×3 —** Student read scoping + acting-student-missing → `ERR_NOT_FOUND` (`routes_flow.py:43-48`); Parent read scoping (`routes_core.py:495-496`); Guardian read scoping without status re-check (`routes_core.py:497-498`).
- **§2.2 — insert —** undefined path/method → standard envelope with `ERR_NOT_FOUND` 404 (`server.py:21-28`).
- **§2.3 — insert —** non-integer `limit`/`offset` fall back to defaults, out-of-range values clamp; `created_at` ties broken by creation order; `has_more` = `offset + returned < total_count` (`helpers.py:78-103`).
- **§2.4 — revise —** clock may be set forward or backward (`routes_core.py:46`).
- **§2.5 — revise/insert —** `version` starts at 1 (`services.py:47`); client-supplied temporal fields echoed verbatim, server-stamped ones canonical 3-fractional-digit UTC (`routes_flow.py:113-114`, `services.py:511-523`).
- **§2.6 — insert —** storage capacity-before-sealed added to the named canonical orderings (`routes_health_discipline.py:675-679`).
- **§2.7 — insert —** OCC check sits after structural, before state/business; a successful create increments the parent's version (`routes_core.py:606-608,641`; `routes_flow.py:397-399,421`).
- **§2.8 — insert —** demerit-point changes alone don't bump student `version`/`updated_at`; a standing change does (`services.py:191-206`).
- **§3.1 — revise/insert ×2 —** activation only from `UPCOMING` else `ERR_INVALID_STATE` (`routes_core.py:95-96`); malformed curfew → `ERR_INVALID_FIELD_VALUE` (`routes_core.py:121-125`); close-for-break requires `OPEN` dorm and an `ACTIVE` break else `ERR_INVALID_STATE` (`routes_core.py:168-172`).
- **§3.2 — insert ×3 —** `max_wards` outside 1–10 → `ERR_INVALID_FIELD_VALUE`; approve only from `PENDING`, suspend from `PENDING`/`APPROVED` (`routes_core.py:289-291,324-325,336-337`); new student is `ENROLLED`/`GOOD`/0 points (`routes_core.py:454-455`); domestic non-null `guardian_id` → `ERR_INVALID_FIELD_VALUE` (`routes_core.py:431-433`).
- **§3.2 — revise —** graduation reachable only from `ENROLLED`; `WITHDRAWN`/`GRADUATED` terminal (`routes_core.py:550-557`).
- **§3.3 — insert ×2 —** linking dissolves both sides' prior roommate links and does not re-validate the source assignment's status (`routes_core.py:631-640,736-747`); questionnaire-driven compatibility recompute does not bump assignment versions (`routes_core.py:524-536`).
- **§3.4 — insert ×4 —** filing order: overlap → in-past → allowance (`routes_flow.py:98-108`); `decided_by_parent_id` stamped on either family outcome, dean proxy included (`routes_flow.py:181`); dorm-decision order state → residency → scope → standing/allowance, and `decided_by_staff_id` stamped on denial too (`routes_flow.py:200-224`); `late_return_minutes` reads 0 until return (`routes_flow.py:118`).
- **§3.4 — revise —** sign-out grace window inclusive at both ends (`routes_flow.py:253`).
- **§3.5 — insert —** swap-respond: `SWAP_PENDING` state check fires before the target-identity check (`routes_flow.py:487-490`).
- **§3.6 — insert —** witness check fires before the duplicate-dose check (`routes_health_discipline.py:155-165`).
- **§3.7 — insert ×2 / revise ×2 —** case opens with `points_assessed` 0, `appeal_count` 0, hearing/decision fields null (`routes_health_discipline.py:230-238`); reporter check fires before hearing-required check (`:333-339`); non-active-dean hearing officer → `ERR_INVALID_FIELD_VALUE` (`:300-305`); sanctioned outcome defaults `points_assessed` to `points_proposed` and leaves `sanction_type` null when omitted (`:344-346`).
- **§3.8 — revise ×2 / insert ×1 —** break-housing filing ignores break status, approval gated to `UPCOMING`/`ACTIVE` (else `ERR_INVALID_STATE`), denial always recordable, fee figures 0 until approval (`routes_health_discipline.py:499-515,559-574`); storage reservation requires `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`) and ignores break status, capacity check before sealed check (`:664-679`); early-bird measured against 00:00 UTC of `starts_on`, 30-day boundary inclusive (`:681-683`).

**Method note:** every endpoint, transition, formula, validation, error, default, side effect, serializer field, and ordering in `implementation/` (9 modules) was walked against the PRD; roles/filters in the §4 table, both OCC flows, all sweep rules, and all calculation constants were verified to already match — no changes needed there. Tests were used only as auxiliary cross-reference (e.g., confirming the inclusive early-bird boundary and OCC placement), never as authority.
