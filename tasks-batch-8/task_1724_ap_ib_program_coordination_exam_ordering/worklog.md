# Worklog — task_1724_ap_ib_program_coordination_exam_ordering

## Step 1: Create Task Directory — 2026-08-14T11:32:00.000Z

Task directory `tasks/task_1724_ap_ib_program_coordination_exam_ordering/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command. Step 1 treated as DONE; no index scan performed, no other task directories touched.

## Step 2: Generate Scaffold — 2026-08-14T12:26:00.000Z

All three artifacts are complete and verified. The `worklog.md` and `workspace/` entries predate my run (created 11:32–11:33 by the batch tooling); I left them untouched per the deliverable scope.

## Report

**Task**: Generate scaffold for `task_1724_ap_ib_program_coordination_exam_ordering` purely from the scenario + skill spec (no sibling tasks were read — only the skill's own SKILL.md, claim-extraction guide, template, and one skill-bundled example for format).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1724_ap_ib_program_coordination_exam_ordering/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys): 11 entities, 48 endpoints, 27 error codes, 7 calculations, 9 state machines, 1 OCC concurrency rule, 4 roles (ApCoordinator/Registrar opaque; Teacher/Student entity-backed with ownership rules; training attestation is Teacher-only for segregation of duties).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 18 instances (exactly 2 per rule × 9 rules), each with structured `setup_api_calls`/`trigger` chains and precomputed literal asserts.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 63 instances (48 full + 15 `excluded_because:` stubs, all citing existing §1.8 instances) across all nine claim-extraction sections.

**Design highlights**:
- Archetypes: compliance/audit (primary) + temporal windowing (secondary); flat topology; layers = optimistic concurrency (OCC `expected_exam_order_version` on `PATCH /exam-orders/{id}`), cascading side effects, dual-variant calculation, derived-field reconciliation.
- Rule differentiation: dual variants on ExamOrder invoice (estimate 29400 vs final 30900) vs Student balance (provisional 9800 vs projected 6200); combinatorial modes (a) multi-branch invoice (37800 literal) vs (b) pinned per-line rebate rounding (285 vs rejected 284); non-linear machines = TeacherAuthorization 730-day expiry/retrain cycle vs ExamRegistration parallel `registration_status × score_status`; cascades = clock-sweep depth-3 (TA→Course→Session→Proctor) vs fee-approval depth-2; priority conflicts = state>constraint vs safety>temporal; boundaries = order-deadline `>` timestamp equality vs inclusive seat-capacity equality; overlaps = room half-open vs proctor 30-minute buffer; invariants = money (balance+rebate) vs seat count.
- All money/date literals were executed and verified in Python before pinning (incl. `authorized_until` = 2026-09-01 + 730d = `2028-08-31T00:00:00Z`, retrain → `2030-08-31T00:00:00Z`; equity report 75.0/25.0/gap 50.0/growth 3).
- Logical clock endpoint declared with the mandatory default `2026-08-01T00:00:00Z`.

**Verification**: `scaffold_lint.py` verdict — "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5" (662 calls scanned). Additional audits passed: zero unbound `${var}` placeholders, no banned concurrency vocabulary, instance names unique across both files, all grounds resolve into §1.1–§1.7, all 27 error codes referenced and triggerable. One bug was caught and fixed during self-review (the subsidy-floor corner originally registered both exams late, which would have made the floored exam net 2400 instead of the asserted 0 — reordered so the floor case registers on time).

## Step 3: Copy Shared Files — 2026-08-14T12:27:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1724_ap_ib_program_coordination_exam_ordering/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T12:45:00.000Z

PRD generation complete. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1724_ap_ib_program_coordination_exam_ordering/workspace/PRD.md` (~50 KB, ends at §5 with no audit footer). The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.

**Document structure** (domain-derived, not example-derived):
- §1: 2-paragraph introduction from the coordinator's pain-point angle
- §2: nine subsections — RBAC with per-role `identity:` translations, verbatim §2.2 envelope block, pagination, the logical clock (default `2026-08-01T00:00:00Z`, expiry sweep on every advance), common resource properties, integer-cents/pinned-rounding discipline, OCC on the exam order, the 11-step validation cascade with explicit ordering, and derived-field/cascade reconciliation
- §3: eight subsections organized chronologically across the program year (cycle setup → teacher authorization loop → students/fee-reduction/registration → order draft-submit-lock-reconcile → rooms and proctors → exam day → scores/transcripts → equity report)
- §4: 48-row endpoint table (4 columns), §5: 27-row error table (2 columns)

**Hard contract reports:**

```
Field coverage check:
- entities[].fields: 63 required, 63 present, 0 missing
- endpoints[].request_body/input: 12 required, 12 present, 0 missing
- endpoints[].query_params/path_params/common/nested-line fields: folded into the 75-name required set, 75 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in ordered §2.8 prose, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (PATCH edit + expected_exam_order_version + ERR_STALE_VERSION/412, no race framing), 0 missing
- state_machines[].transitions: 24 checked across 9 machines (incl. parallel score_status dimension), 24 fully expressed, 0 missing
- calculations[]: 7 checked (net fee, order invoice estimate/final, student balance provisional/projected, school rebate per-line-then-sum, equity participation, 730-day expiry with inclusive boundary, session seating), 7 fully expressed, 0 missing
- validations[] conditions: 27 error ids matchable to prose triggers in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all cascade chains expressed (approve→subsidy→balances/rebate/estimate; expiry→course→session→proctor; administer SAT/NO_SHOW split; resolve vs cancel-scores divergence), 0 missing
- entities[].fields[] structured content: defaults (accommodation_type NONE, room_supports_accommodations false), null-until fields (score, submitted_late, timestamps, final_total_cents), ranges (grade 9–12, rebate 0–10000bp, AP 1–5/IB 1–7) all reconstructible, 0 missing
- sibling-branch symmetry: SAT/NO_SHOW, resolve/cancel-scores, approve/deny/resubmit, provisional/projected, estimate/final all at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 420
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 block byte-identical to `section-2.2-response-structure.md`; §4 roles column matches scaffold `roles` for all 48 endpoints; §5 IDs/HTTP statuses match the scaffold error catalog exactly (27/27, no extras); no fuzzy words ("approximately", "about", …) and no pseudocode operators (`==`, `>=`, `min(`, `:=`, …) anywhere outside the verbatim JSON block.

## Step 5: Generate Unit Tests — 2026-08-14T13:20:00.000Z

Test generation complete. Outputs: `test_helpers/` (9 modules) and `test_suite/` (conftest + 9 test files, 84 test functions).

**Design-index-only translation** (no freelance scaffold walking): all 18 §1.8 difficulty instances received exactly 2 tests each (36 difficulty-tagged tests); all 48 non-stub §1.9 corner instances received exactly 1 test each (48 corner-tagged tests); the 15 `excluded_because:` stubs were not translated (all cross-references verified to resolve). Every test docstring carries verbatim PRD citations (C1–C3) and ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line (C4).

**PRD-first adjudications applied** (unique-derivability filter):
- No test asserts `version == 1` at creation or `created_at == updated_at` equality — PRD §2.5 lists the properties and the increment rule but pins neither the initial value nor same-instant rendering. Versions are captured dynamically and the exact +1 increment is asserted only where §3.4 pins it (order PATCH).
- Equity-report test asserts the PRD-named top-level fields (`total_exams` 4, `growth_exams` 3, `access_gap_pct` 50.0) and subgroup-array length 2; per-subgroup JSON key names are not named in §3.8 prose, so they are not asserted.
- Order-line `line_total_cents` composition is not pinned by §3.4 prose, so line assertions cover only the pinned fields (`ordered_count`, `fee_cents`, `late_fee_total_cents`) plus order-level totals.

**Verification**: all 84 docstring citations (134 quoted blocks) verified verbatim against `workspace/PRD.md` via whitespace-normalized substring grep; every asserted `error_id` is named in §2.8/§3 prose with its trigger condition (not just the §5 table); no `skip`/`skipif`/`xfail`/mock anywhere; `pyflakes` clean on `test_suite/`; `py_compile` clean; `pytest --collect-only` collects 84 tests with zero errors.

**Coverage mechanics notes**: entity-backed roles are threaded through `make_student_headers(entity_id)` / `make_teacher_headers(entity_id)` on every ownership-gated call (fixtures included); the proctor is always assigned while its session is still `SCHEDULED`; clock moves are monotonic within each test; the expiry boundary arithmetic (2026-09-01 + 730d = 2028-08-31; +730d = 2030-08-31) matches the precomputed literals.

## Step 5: Generate Unit Tests — 2026-08-14T13:30:00.000Z

All tasks complete. Final report:

## Generation complete — task_1724 AP/IB Program Coordination

**Stage 1 — `test_helpers/` (9 modules):**
- `types.py` — 12 entity TypedDicts (all entities carry the PRD §2.5 common fields), 13 status/field enums, 4-role `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with 33 methods covering every PRD §4 endpoint
- `api_errors.py` — all 27 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions, the §3.3 net-fee invariant, and `assert_instant_equal` (instant comparison tolerant of fractional-digit rendering, since the PRD pins instants, not serialization)
- `factories.py`, `constants.py` — payload factories + canonical cycle deadlines/fee constants (late 4000, unused 1500, reduction 3600, rebate 900bp, fee 9800)
- `test_users.py` — opaque coordinator/registrar constants plus mandatory `make_student_headers(id)` / `make_teacher_headers(id)` builders for the two entity-backed roles
- `fixtures.py` — composite lifecycle builders including `setup_sat_scenario` (proctor assigned while the session is still `SCHEDULED`, per the §3.5 state gate), `setup_released_registrations`, `setup_under_investigation`
- `__init__.py` — barrel export

**Stage 2 — `test_suite/` (conftest + 9 concern-grouped files, 84 tests):**
- **Queue A**: all 18 difficulty instances × exactly 2 tests = 36 `Design: Difficulty/...`-tagged tests
- **Queue B**: all 48 non-stub corner instances × 1 test = 48 `Design: Corner/...`-tagged tests; the 15 `excluded_because:` stubs were not translated (all cross-references verified to resolve into §1.8)

**PRD-first adjudications** (unique-derivability filter applied, tests scoped rather than weakened into placeholders):
- No `version == 1` literal and no `created_at == updated_at` equality — PRD §2.5 pins neither the initial version nor same-instant rendering; the exact `+1` version increment is asserted only on order PATCH where §3.4 states it
- Equity report asserts only the PRD-named fields (`total_exams`, `growth_exams`, `access_gap_pct`, array length) — §3.8 never names the per-subgroup JSON keys
- Order-line assertions cover only the PRD-pinned line fields (`ordered_count`, `fee_cents`, `late_fee_total_cents`) — `line_total_cents` composition is unstated

**Audits (all passed):** 134 quoted docstring blocks verified verbatim against `workspace/PRD.md` via whitespace-normalized grep; every asserted `error_id` is named in §2.8/§3 prose with its trigger; exactly one terminal `Design:` tag per docstring, all resolving to real instances; no `skip`/`skipif`/`xfail`/mocks; `pyflakes` clean on `test_suite/`; `pytest --collect-only` collects 84 tests with zero errors. Step 5 recorded in `worklog.md`.

## Step 6: Generate Implementation — 2026-08-14T13:30:00.000Z

Implementation complete. **All 84 tests pass under `prd-bench-local-run --isolation per-test-server`, verified in two consecutive full runs** (106s/111s, ~1.3s per test including fresh server reboot each time).

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_1724_ap_ib_program_coordination_exam_ordering/workspace/implementation/` — Python + Flask, in-memory store, all 48 endpoints:

- `start.sh` (executable, guarded `pip install`, `exec python3 app.py` on `0.0.0.0:$PORT`), `requirements.txt` (`flask>=2.2`)
- `app.py` (entry, error handlers, global request lock for atomicity), `db.py` (empty store per boot — no seeding), `errors.py` (all 27 catalog IDs with exact HTTP statuses), `response.py` (scaffold envelope: `meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination fields `limit/offset/total_count/has_more` in meta for lists), `middleware.py` (X-User-ID/X-User-Role auth, 4 roles), `validate.py`, `util.py` (logical clock, default `2026-08-01T00:00:00Z`)
- `routes/` — clock, cycles (+ equity-report, release-scores), courses, teachers, authorizations, students (+ statement), applications, registrations (+ cancel, post-to-transcript), orders (+ OCC PATCH, submit, lock, reconcile), sessions (+ administer, cancel), proctors, irregularities
- `services/` — `derived.py` (all calculation rules), `serialize.py`, `sweep.py` (expiry cascade), `core.py`
- `smoke_test.py` / `smoke_test2.py` — self-verification scripts replaying every pinned literal from the design files (not part of the build contract)

## Key design decisions

- **Derived-at-read architecture**: counts, balances, subsidy/net fee, rebate, seats_reserved, and DRAFT order lines/estimate compute from the live store at serialization, so every downstream recompute is visible immediately (PRD §2.9). Stored eager mutations only for state-machine transitions, each bumping `version`/`updated_at` on touched resources (cascade: TA expiry → course suspension → session cancel → proctor release).
- **Pinned literals all verified**: rebate 285 (per-line round-half-up, rejected sum-then-round 284), estimate 37800 multibranch, estimate-vs-final 29400/30900 divergence, provisional/projected 9800/6200, equity 75.0/25.0/gap 50.0/growth 3, `authorized_until` = +730 days with inclusive `>=` boundary, deadline equality on-time (`>` strict), capacity equality fits, proctor 30-min buffer vs room half-open adjacency.
- **Validation cascade**: auth (401) → role (403) → path existence (404) → ownership (403) → shape (400, unknown fields rejected) → body FK (422) → state (409/412) → safety (422) → temporal → uniqueness/quota → fiscal (422) → transactional score-release record gate (HELD → `ERR_IRREGULARITY_OPEN`, other non-PENDING → `ERR_INVALID_STATE`, nothing written on rejection).
- **OCC on `PATCH /exam-orders/{id}`**: `expected_exam_order_version` required (400 if missing), stale → 412; state gate beats the negative-quantity constraint (matches the difficulty instance).
- Domain timestamps (`training_completed_at`, `submitted_at`, etc.) render from the logical clock as `YYYY-MM-DDTHH:MM:SSZ` at second precision; `created_at`/`updated_at` use the runner-validated 3-fractional-digit ISO format; `version` starts at 1.

## Step 7: Run Tests and Iterate — 2026-08-14T13:45:00.000Z

Clean sweep confirmed. The exit condition is met: all 8 rounds have `passed == total` (84/84 each).

**Summary**

- **Iterations run**: 1 (a single 8-round parallel stability sweep; no fixes were needed).
- **Sweep result**: All 8 rounds passed 84/84 tests with 0 failures and 0 errors. Union of failing tests across rounds: empty. No flakiness detected.
- **Tests deleted**: None.
- **Fixes applied to `test_helpers/`**: None.
- **Fixes applied to `implementation/`**: None.

The existing implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1724_ap_ib_program_coordination_exam_ordering/workspace/implementation/` (Flask, in-memory store, per-test-server isolation via `start.sh`) was already stable: the worklog recorded two consecutive clean full runs at implementation time, and this 8-round concurrent sweep (672 per-test server reboots under ~15 load average) confirms no timing-sensitive or flaky behavior. Key stability properties verified in the code: process-global in-memory dict wiped per boot (no disk persistence), a single global request `threading.RLock` making every mutation atomic, guarded `pip install` in `start.sh` to avoid boot-time contention across concurrent rounds, and pinned-rounding/derived-at-read arithmetic matching the PRD §2.6/§2.9 contracts.

## Step 8: Finalize PRD — 2026-08-14T13:46:00.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-14T14:05:00.000Z

The diff is exactly the intended minimal patch: 12 edited paragraphs, no lines added or removed, no new sections. Final verification of the numbers and summary follows.

**File statistics**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_1724_ap_ib_program_coordination_exam_ordering/workspace/PRD.md` — 287 lines, 50,823 chars
- Produced: `/home/ubuntu/github/CodingPRD/tasks/task_1724_ap_ib_program_coordination_exam_ordering/workspace/PRD_COMPLETED.md` — 287 lines, 55,719 chars (char-delta +4,896; all changes are in-paragraph inserts/revisions, zero new sections)

**Counts**: 8 ambiguity-pins, 6 mismatch-revisions (14 logical changes in 12 edited passages).

**Change log** (section — insert/revise — class — what changed — impl ref):

- §2.3 — insert — ambiguity — pinned pagination validation (`limit`/`offset` non-integer or out of range → `ERR_INVALID_REQUEST` 400), the `has_more` formula (`offset + returned < total_count`), exact-match filter semantics, and ignored unknown query params — implementation/routes/helpers.py:8-43, implementation/response.py:23-34
- §2.4 — insert — ambiguity — clock accepts any target instant (backward set not rejected, never revives EXPIRED); all datetime inputs normalized to UTC at one-second precision and echoed as `YYYY-MM-DDTHH:MM:SSZ` — implementation/util.py:34-63, implementation/routes/clock.py:13-21
- §2.5 — insert — ambiguity — `version` starts at 1 on creation; `created_at`/`updated_at` are wall-clock (not logical-clock) timestamps — implementation/services/core.py:6-13, implementation/util.py:18-21
- §2.5 — revise — mismatch — "mutation is read broadly" no longer counts derived-field reconciliation as a version-bumping mutation; derived figures are read-time computed and never bump the owner's `version`/`updated_at` — implementation/services/core.py:18-20, implementation/services/derived.py (no touch on derived owners anywhere)
- §2.7 — insert — ambiguity — OCC version check runs before the DRAFT-state gate (stale version on a non-DRAFT order → 412, not 409) — implementation/routes/orders.py:124-131
- §2.8 step 2 — revise — mismatch — role-list membership is step 2; entity-backed ownership is enforced where its entity becomes available (raw `student_id` pre-shape on creations; right after path resolution on path-identified resources; after the `session_id` reference for irregularity filings) — implementation/middleware.py:26-31, implementation/routes/applications.py:33-44, implementation/routes/registrations.py:36-46, implementation/routes/irregularities.py:35-45
- §2.8 step 3 — revise — mismatch — undefined paths and unsupported methods yield `ERR_NOT_FOUND` 404; the 13 empty-body action endpoints apply the no-payload-fields shape check *before* path resolution, while `PATCH /exam-orders/{id}`, administer, and release-scores resolve the path first — implementation/app.py:47-53, e.g. implementation/routes/cycles.py:66-76 vs implementation/routes/orders.py:84-89
- §2.8 step 4 — insert — ambiguity — required strings must be non-blank; an optional field explicitly null is treated as omitted; the score program-range check runs right after step-5 reference resolution (course-dependent) — implementation/validate.py:23-77, implementation/routes/cycles.py:117-131
- §2.9 — revise — mismatch — cascade version-bumps apply only to resources whose stored fields are rewritten (expiring authorization, cancelled sessions, released assignments), not to resources merely exposing recomputed derived figures (course status/counts) — implementation/services/sweep.py:23-39
- §3.2 — revise — mismatch — course listing actually accepts `subject_code` and `program` filters in addition to `cycle_id` and `status` — implementation/routes/courses.py:52-61
- §3.4 — insert — ambiguity — order `lines` cover every course in the cycle, ordered by course creation ascending — implementation/services/derived.py:163-183
- §3.4 — insert — ambiguity — PATCH may omit `adjustments` (leaves them unchanged, still bumps `version`); duplicate `course_id` within one edit → 400; cross-cycle adjustment course → 400 after the 422 resolution check — implementation/routes/orders.py:91-123,133-143
- §3.6 — insert — ambiguity — irregularity `details` is a required string that may be empty — implementation/routes/irregularities.py:34, implementation/validate.py:30-34
- §3.7 — revise — mismatch — pinned the actual release gate order (entry shape → registration references → program-range → timing → record gate); listed registrations are looked up globally (not required to belong to the addressed cycle, whose `score_release_at` still gates timing); any `PENDING` record may be released, including a not-yet-administered `REGISTERED` registration's — replacing the false "necessarily SAT" claim — implementation/routes/cycles.py:93-152

Everything else in the implementation (all 41 endpoints' role lists, state machines, fee/rebate/balance math, estimate/final invoice formulas, sweep cascade, envelope shapes, error catalogue, seeded clock instant) was already uniquely pinned by the PRD and needed no change.
