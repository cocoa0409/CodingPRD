# Worklog — task_2266_event_security_crowd_management

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2266_event_security_crowd_management/` and `tasks/task_2266_event_security_crowd_management/workspace/` (directory name pre-allocated by the invoking command; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T00:00:00.000Z

All three scaffold artifacts for task 2266 are complete and lint-clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2266_event_security_crowd_management/`):
- `SCAFFOLD.yaml` — 3,347 lines; top-level keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 4,881 lines; single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 19,808 lines; single top-level key `scaffold_corner_design`

**Final lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2266_event_security_crowd_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2266_event_security_crowd_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2266_event_security_crowd_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  2857

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**

| Table | Count |
|---|---|
| §1.1 entities | 13 (Venue, VenueZone, SecurityEvent, RiskAssessment, StaffingPlan, Post, Guard, Subcontractor, PostAssignment, ScreeningLane, DensityReading, Incident, AfterActionReview) |
| §1.2 state machines | 10 (+ 3 §1.2.1 concurrency rules) |
| §1.3 calculations | 16 |
| §1.4 validations | 39 (priority-ordered, 1–39) |
| §1.5 endpoints | 48 |
| §1.6 errors | 51 |
| §1.7 roles | 8 (SecurityDirector, RiskAnalyst, StaffingCoordinator, CredentialAuditor, PostSupervisor, IncidentCommander, SubcontractorLiaison, SystemOperator) |

**Complexity profile:** primary `quota_allocation`, secondary `compliance_audit`, layers `[cascading_side_effects, optimistic_concurrency, rate_threshold_triggers, ops_run_checkpoint]`, topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, difficulty `expert_plus`.

**§1.8 difficulty design:** 9 rule blocks / **24 instances** — dual-basis & window ambiguity, rounding/order-of-operations, multi-hop cascades, priority-pair ordering, threshold boundaries, empty collections, cross-entity state dependencies, interval/overlap semantics, ledger restoration.

**§1.9 corner design:** **101 instances = 75 real + 26 `excluded_because` stubs**, across all nine claim-extraction sections — entities 12, state_machines 21, calculations 17, validations 30, endpoints 5, errors 2, rbac 7, cross_cutting_complexity_layers 6, consistency_model 1.

## Step 3: Copy shared files — 2026-09-01T00:00:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_2266_event_security_crowd_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T00:00:00.000Z

PRD generated and verified.

**Output**: `workspace/PRD.md` — **468 lines**.

**Sections**: §1 Introduction (3 paragraphs, business-pain framing); §2 Global Specifications with 11 subsections (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Record Identity/Audit Fields/Logical Clock, 2.5 The Order in Which a Request Is Judged — the full 39-rank validation ladder with `applies_to` enumerations, 2.6 Version Pinning and Stale-Write Rejection, 2.7 Gate Posture, 2.8 Cascade Discipline, 2.9 Arithmetic/Precision/Rounding, 2.10 Nested Paths and Referential Scoping, 2.11 Conserved Quantities); §3 Business Logic with 9 lifecycle subsections; §4 Endpoint Definitions (48 rows, 4 columns); §5 Error Code Catalogue (51 rows, 2 columns).

**Field coverage check:** entities[].fields 167/167; endpoints[].input 162/162; PASS
**Rule coverage check:** validations 39/39 in rank order (all 51 error IDs verbatim); OCC rules 3/3; state machine transitions 79/79 across 10 machines; calculations 16/16 with pinned evaluation order; endpoint side_effects 24/24 as hop-by-hop cascades; entity field structured content 167/167 incl. DensityReading `common_fields: false`; sibling-branch symmetry 6 groups, 0 asymmetric; PASS
**Path purity check (§3):** 1120 backtick tokens scanned, 0 paths / 0 bare methods / 0 method+path; PASS

§2.2 block byte-identical to the skill's canonical section. Withheld design files never opened; no sibling task read.

## Step 5: Generate unit tests — 2026-09-01T00:00:00.000Z

Generation is complete. Both stages are written and verified.

**Stage 1 — `test_helpers/`**: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`, plus `test_suite/conftest.py`.

**Stage 2 — `test_suite/`, 18 modules, 123 tests:**

| Queue A (§1.8, difficulty) | | Queue B (§1.9, corner) | |
|---|---|---|---|
| `test_01_dual_variant_derivations.py` | 4 | `test_10_entity_surface.py` | 12 |
| `test_02_combinatorial_formulas.py` | 6 | `test_11_state_machines.py` | 14 |
| `test_03_non_linear_state_paths.py` | 6 | `test_12_calculations.py` | 11 |
| `test_04_transitive_cascades.py` | 6 | `test_13_validations.py` | 19 |
| `test_05_validation_precedence.py` | 6 | `test_14_endpoints.py` | 5 |
| `test_06_boundary_precision.py` | 6 | `test_15_not_found_errors.py` | 2 |
| `test_07_cross_entity_state.py` | 6 | `test_16_role_permissions.py` | 7 |
| `test_08_temporal_overlap.py` | 4 | `test_17_optimistic_concurrency.py` | 4 |
| `test_09_conserved_ledgers.py` | 4 | `test_18_consistency.py` | 1 |

**Coverage against the two design indices**
- Queue A: 48 tests over 24 live difficulty instances — exactly 2 per instance, the required minimum.
- Queue B: 75 tests over 75 live corner instances — 1 per instance.
- Uncovered live instances: 0. Every non-stub instance in §1.8 and §1.9 is translated.

**Instances not translated**: only the 26 corner instances carrying `excluded_because:` (the design's own stubs). No `excluded_because` stubs exist in the difficulty design. No live instance was dropped for the PRD-first filter — every one had verbatim PRD coverage that uniquely derives its asserted outcome; nothing weakened, skipped or xfailed.

**Verification**: 123 `Design:` tags, each the last docstring line, exactly one per test, all resolving to live instances; every test carries exactly one `PRD: "…"` citation that is a literal substring of `workspace/PRD.md`; every `test_helpers` import exported and referenced; no `pytest.mark.skip/xfail`; no banned vocabulary; `pytest --collect-only -q` → 123 tests collected, no import/syntax errors. Nothing under `workspace/implementation/` read or written; no sibling task opened.

## Step 6: Generate implementation — 2026-09-01T00:00:00.000Z

Implementation complete and verified.

**Files written** (all under `workspace/implementation/`): `start.sh` (guarded `pip install`, `exec python3 app.py`), `requirements.txt` (`flask>=2.0`), `app.py` (app factory, blueprint registration, `ApiError` handler, envelope-wrapped 400/404/405/415/500 handlers, `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000))`), `db.py` (in-memory `Store` — 13 dicts, all empty on boot; logical clock defaulting to `2026-08-01T00:00:00Z`; ISO parse/format; `make_record`/`touch`/`apply_fields`/`sorted_records`), `errors.py` (51 error ids → HTTP status), `response.py`, `valid.py` (rank-5 body + query validation), `auth.py` (8 roles, per-action authority groups, SoD, entity-backed PostSupervisor/SubcontractorLiaison standing), `calc.py` (all 12 calculations, Decimal + half-up/ceil/floor), `serial.py` (explicit per-entity field projections), `engine.py` (post/plan/event/lane derivations, cascades, pricing, supersede/void/close cascades, after-action metrics, credential-expiry sweep), and `routes/` (`__init__.py` with `/event-security` prefix and un-prefixed clock, `_common.py`, `venues.py`, `events.py`, `assessments.py`, `plans.py`, `posts.py`, `vendors.py`, `guards.py`, `assignments.py`, `lanes.py`, `readings.py`, `incidents.py`, `reviews.py`, `clock.py`).

**Endpoint coverage**: 48 routes implemented. Programmatic diff of Flask's `url_map` against PRD §4 → 48 vs 48, zero missing, zero extra (paths and methods identical).

**Boot + behaviour verification**: `PORT=18266 bash start.sh` boots in ~1s; `GET /event-security/security-events` returns the correct list envelope. A second fresh boot confirmed every collection starts empty (`total_count: 0`) — no seeding, no file/SQLite/JSON/tmp persistence (grep-verified). Two end-to-end smoke suites (~110 assertions) passed with 0 failures, covering venue/zone `max_safe_occupancy`, event creation + OCC PATCH (412 on stale), assessment SUBMIT/REJECT/REVISE/APPROVE with SoD 403 and the full derived block (score 3.75→T1, 100.00→T4, ticketed-basis switch), plan create under `expected_event_version`, posts (span-of-control 422, duplicate code 400, OCC 412), subcontracted/night/overtime pricing (`SUBCONTRACT` 19313¢, `EMPLOYEE_OT` 22000¢), publish floors, CONFIRM ladder, coverage-summary (9 fields, conserved ledger), activate, brief/check-in/no-show/relieve via PostSupervisor standing, lane OPEN/HOLD/CLOSE + throughput (270 pph), DOORS_OPEN gates, density readings (3-decimal density/ratio/rolling mean, instantaneous vs rolling `effective_level` switch at 3 readings), all incident branches (TRIAGE metrics, ESCALATE 422 on non-escalating, MEDICAL_HANDOFF, EJECT, critical LE_HANDOFF → ingress HOLD → lanes HOLD → posture FROZEN, compensating release on RESOLVE, CLOSE_UNFOUNDED), suspend/resume, close cascade (assignments COMPLETED/RELIEVED with billed cost, lanes/posts/plan CLOSED), review DRAFT→SUBMITTED→RETURNED→DRAFT→SUBMITTED→FINALIZED with SoD 403 and event CLOSED→DEBRIEFED, clock sweep (expired guards + voided assignments), vendor suspend/terminate cascades, guard reject/disqualify voiding, and 401/403/404/405/400 edge cases. Both test servers killed after verification; `__pycache__` removed.

Notable interpretation decisions: PRD §2.5 rank order wins over SCAFFOLD precondition order; duplicate `zone_code`/`post_code` → `ERR_INVALID_REQUEST` 400; liaison ownership violations → `ERR_ROLE_NOT_PERMITTED` 403; unmapped temporal/state preconditions → `ERR_INVALID_STATE`; gate interlock applied only where §2.5 rank 13 lists it (so plan LOCK/CLOSE stay reachable while an event is frozen); `is_ingress_zone` not enforced on lane creation (no such validation in either spec).

## Step 7: Run tests and iterate — 2026-09-01T00:00:00.000Z

All 8 parallel rounds pass 123/123.

**Iterations run:** 4 sweeps (8 parallel rounds each). Iteration 1: 100/123 in every round (23 deterministic failures). Iteration 2: 121–122/123. Iteration 3: 122–123/123 with host interference. Iteration 4: **123/123 in all 8 rounds.**

**Tests deleted:** none. Every failing test's rule traced to a verbatim PRD sentence and was uniquely derivable, so all 23 were resolved by fixing the test artifact or the implementation.

**Fixes applied to `test_helpers/`**
- `factories.py` — `_merge()`: the `OMIT` sentinel is now honoured in the base dict as well as in overrides. `post_assignment_payload(post_id, guard_id=OMIT)` previously raised `TypeError: got multiple values for argument 'guard_id'` because the payload key collides with a declared positional parameter.
- `assertions.py` — `assert_budget_conserved()`: skips the `budget_remaining + committed == budget_cents` identity when `budget_cents` is absent from the payload. PRD §3.4 lists exactly nine figures on the coverage-summary read and `budget_cents` is not one of them, so `assert_ledger(summary, …)` was raising `KeyError` in 6 tests.

**Fixes applied to `test_suite/`** (assertion/fixture mis-translations of PRD)
- `test_08_temporal_overlap.py` — `_split_shift_world()` pre-created the overlapping `a3` row before `a2` was confirmed. PRD §3.6 counts `TENTATIVE` rows in the double-booking set, so the PRD-faithful server correctly refused `a2`'s confirmation. `a3` is now created after `a2` is committed (which is also what the test's own ledger expectation of 16500/7.50 requires).
- `test_13_validations.py` — `test_nothing_can_be_written_through_a_superseded_plan` read `expected_post_version` *before* the supersession closed the post, so §2.5 rank 9 (`ERR_STALE_POST_VERSION`) pre-empted rank 11. The version is now pinned after the supersession.
- `test_13_validations.py` / `test_18_consistency.py` — both asserted `gate_posture == RESTRICTED` on an event still in `RISK_ASSESSED`. PRD §2.7's pre-plan variant skips clause 3 in `PLANNING`/`RISK_ASSESSED`, so the value is `OPEN` (test_13 asserts `status == RISK_ASSESSED` two lines earlier).
- `test_14_endpoints.py` — lane `version` expectation corrected 2 → 3: creation is 1, the operator check-in re-derives `assigned_operator_count` 0→1 (§3.7) which is a derived-field-only mutation that increments `version` (§2.4), and the `OPEN` transition is the third.
- `test_10_entity_surface.py` — removed the stray positional `"unused"` argument in the `guard_id=OMIT` call.

**Fixes applied to `implementation/`**
- `db.py` — added `format_clock()` / `clock_iso()`, rendering the logical clock the way PRD §2.4 quotes it (`2026-08-01T00:00:00Z`, fraction only when sub-second precision is supplied). `created_at`/`updated_at` keep `format_iso()`'s three fractional digits, which §2.4 pins explicitly for them alone.
- `routes/assignments.py`, `routes/guards.py`, `routes/incidents.py`, `engine.py` — the seven fields §2.4 names as "stamped with the logical clock value" (`verified_at`, `briefed_at`, `check_in_at`, `relieved_at`, `reported_at`, `triaged_at`, `resolved_at`) now use `clock_iso()`. They were emitting `…T00:00:00.000Z` while the same clock value was reported as `…T00:00:00Z` on `current_utc` — 9 tests tripped on that inconsistency.
- `routes/clock.py` — `current_utc` now renders via `clock_iso()` instead of echoing the raw request string.
- `routes/plans.py` — `coverage_summary()` no longer returns `staffing_plan_id`; PRD §3.4 enumerates the nine figures the computed read exposes and that key traces to no PRD sentence.

**Note on the interference seen mid-run:** iteration 3 lost 5 of 8 rounds to raw `ConnectionResetError` / server `SIGTERM` (exit 143) at boot, all inside one ~15-second window, with the port registry reporting 24 concurrent holders from other pipelines on the host. No assertion failed in those rounds; iteration 4 reproduced 123/123 eight times over, so this was host-level process interference rather than a defect in the artifacts.

Orchestrator verification: all 8 `results.{1..8}.json` read back as `passed == total == 123`.

## Step 8: Finalize PRD — 2026-09-01T00:00:00.000Z

Done. `PRD_FINALIZED.md` written with two edits.

**Size**: `PRD.md` 468 lines / 101,748 bytes; `PRD_FINALIZED.md` 468 lines / 103,173 bytes. Line delta 0%; byte delta +1.40% (both edits are in-paragraph appends).

**Changes**
- §2.4 (Record Identity, Audit Fields and the Logical Clock) — revise — pinned the *rendering* of the logical clock: the seven clock-stamped fields (`verified_at`, `briefed_at`, `check_in_at`, `relieved_at`, `reported_at`, `triaged_at`, `resolved_at`) and `current_utc` all render as a UTC `Z` instant with no fractional part on a whole second (three digits only when the clock was set with sub-second precision), `current_utc` reports the normalised value rather than echoing the request string, while `created_at`/`updated_at` keep three fractional digits and client-supplied instants are echoed verbatim — `db.py:72` (`format_clock`), `db.py:137` (`clock_iso`), `routes/clock.py:24`.
- §3.4 (The Staffing Plan…) — revise — pinned the coverage-summary computed read to exactly nine keys (no plan identifier, no `budget_cents`, no `billed_cost_cents`, no audit fields) — `routes/plans.py:99-113`.

**Per-edit pre-edit search log**

Edit 1 — §2.4 clock rendering
- (a) Subject: the string form of every timestamp the server *generates* (as opposed to echoes), specifically the logical clock.
- (b) Paths enumerated/read: `db.py:58 format_iso`, `db.py:72 format_clock`, `db.py:128-139 now/now_iso/clock_iso`, `db.py:146-162 make_record`/`touch` (`created_at`/`updated_at` → `now_iso`, 3 digits always); every `*_at` writer found by `grep -rn '_at"\] *='`: `routes/assignments.py:224,245,269`, `routes/guards.py:173` (+`:181` null-clear), `routes/incidents.py:71,159,229,246`, `engine.py:505` (relief inside event-close cascade), `engine.py:602` (`verified_at = None` on expiry sweep); `routes/clock.py:14-28` (`current_utc`, incl. `parse_iso` offset normalisation); `response.py:25-37` (`api_request_timestamp`, own 3-digit formatter, untouched); `serial.py` field tuples enumerating every output timestamp (only the 7 stamps, `COMMON`, `observed_at`, `doors_open_at`/`event_start_at`/`event_end_at`, `credential_expires_on`, `insurance_expires_on`); raw-echo store sites via `grep -rn '\[0\],' routes/` (`events.py:75-77`, `posts.py:161-162,245`, `assignments.py:69-70`, `lanes.py:51-52`, `readings.py:76`, `guards.py:76,143,146`, `vendors.py:46`).
- (c) Adjustment: first draft was a bare "the clock is rendered without a fractional part" — a false universal, since `created_at`/`updated_at`/`api_request_timestamp` keep three digits and client instants are echoed byte-for-byte. Re-scoped to "those eight fields" with two explicit carve-outs (audit fields; client-supplied instants incl. lane/post/assignment windows, `observed_at`, `credential_expires_on`, `insurance_expires_on`). Added "normalised to UTC from whatever offset the operator supplied" after reading `parse_iso`, so a `+02:00` clock set is not mis-described.

Edit 2 — §3.4 coverage-summary payload
- (a) Subject: response shape of `GET /event-security/staffing-plans/{id}/coverage-summary`, and by adjacency the plan resource read sharing these field names.
- (b) Paths enumerated/read: `routes/plans.py:99-113` (only builder; nine literal keys, `supervisor_coverage_ok` computed live via `engine._supervisor_coverage_ok`), `serial.py:77-95 PLAN` + `serial.py:246 plan()` (plan resource read — has `id`, `budget_cents`, `billed_cost_cents`, `COMMON` audit fields, and lacks `supervisor_coverage_ok`), `engine.recompute_plan`/`_supervisor_coverage_ok`, PRD §4 row for the endpoint (left as-is; no conflict).
- (c) Adjustment: sentence constrains only "that computed read", never "the plan"; the negative list names `budget_cents`/`billed_cost_cents`/identity/audit fields as absent from the summary without implying anything about the plan resource, which does carry all four. Deliberately did not add a claim about `supervisor_coverage_ok` being absent from the plan resource — true, but not traceable to a `<step_7_diff>` item, so out of scope.

**Items deliberately left unpatched** (PRD already uniquely determines them, or pure fixture bugs): the `OMIT`-sentinel and stray-positional-arg fixes; `TENTATIVE` rows in the double-booking set (§3.6 verbatim); rank 9 pre-empting rank 11 (§2.5); `gate_posture == OPEN` in `RISK_ASSESSED` (§2.7 pre-plan variant); the lane `version` 2→3 recount (follows from §3.7 + §2.4); `assert_budget_conserved`'s `budget_cents` guard (subsumed by Edit 2).

## Step 9: Complete PRD — 2026-09-01T00:00:00.000Z

All edits applied. Final state verified.

**Files**: source `workspace/PRD_FINALIZED.md` — 468 lines, 102,767 chars (103,173 bytes); output `workspace/PRD_COMPLETED.md` — 468 lines, 111,197 chars (111,641 bytes). Char delta **+8,430** (+8,468 bytes); line delta 0 — every change is an in-paragraph insert or revision on an existing line (27 lines touched), no new sections, no new paragraphs, no reordering.

**Counts:** 39 changes total — **34 ambiguity-pins**, **5 mismatch-revisions**.

**Changes**
- §2.1 Roles — insert — ambiguity — liaison ownership violations refused with `ERR_ROLE_NOT_PERMITTED` (403), tested after the body `subcontractor_id` / path guard resolves — `routes/guards.py:58-65,130-134`
- §2.1 Roles — insert — ambiguity — a `PostSupervisor`'s `X-User-ID` is resolved against the guard table (`ERR_GUARD_NOT_FOUND`) only on the duty-events endpoint — `routes/assignments.py:119-120`
- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`, negative `offset`, or out-of-enum filter value is `ERR_INVALID_REQUEST` (not clamped); empty string treated as absent — `valid.py:154-186`
- §2.3 Pagination — insert — ambiguity — `total_count` counts the whole filtered set; `has_more` is `offset + len(page) < total_count` — `response.py:49-55`
- §2.5 rank 4 — revise — mismatch — rank splits: `ERR_GUARD_NOT_FOUND` at rank 4 before the path assignment, `ERR_NOT_POST_SUPERVISOR` after path resolution but still before rank 5 body fields — `routes/assignments.py:119-136`
- §2.5 rank 7 — insert — ambiguity — `venue_id` / `ERR_VENUE_NOT_FOUND` added to the body-FK list — `routes/events.py:63`
- §2.5 rank 13 — revise — mismatch — gate interlock guards only plan `PUBLISH`/`RECALL`/`ACTIVATE` and event `BRIEF`/`DOORS_OPEN` (plus the listed roster/lane writes); explicit negative list added — `routes/plans.py:129-215`, `routes/events.py:152-190`, `routes/lanes.py:104`
- §3.1 Zones — insert — ambiguity — duplicate `zone_code` is `ERR_INVALID_REQUEST` (400), tested after the path venue resolves — `routes/venues.py:69-76`
- §3.2 Event creation — insert — ambiguity — both attendance ceilings are `ERR_INVALID_REQUEST` (400), tested after `ERR_VENUE_NOT_FOUND` — `routes/events.py:63-68`
- §3.2 Event patch — insert — ambiguity — all three fields optional pure overwrites (never cleared), no lifecycle precondition, capacity checked before version pinning, no-op still bumps `version` — `routes/events.py:117-141`
- §3.2 Assessment creation — insert — ambiguity — `revision_number` always starts at 1, whole derived block null, `attendance_basis` already `EXPECTED`, no event-status/gate gate — `routes/assessments.py:82-103`
- §3.2 Rejection — insert — ambiguity — `REJECT` has no event-status or gate precondition of its own — `routes/assessments.py:186-193`
- §3.2 Revision — insert — ambiguity — `REVISE` does **not** clear the derived block — `routes/assessments.py:195-202`
- §3.4 Post creation — insert — ambiguity — `reports_to_post_id`/`lane_id` are scope-checked only, never conditioned on `post_type` — `routes/posts.py:105-130`
- §3.4 Post creation — insert — ambiguity — duplicate `post_code` is `ERR_INVALID_REQUEST` (400), after ranks 7-8 and before rank 10 — `routes/posts.py:132-138`
- §3.4 Post patch — insert — ambiguity — optional fields; window rule and both capacity rules evaluated on the *merged* values after path resolution, self excluded from the zone aggregate — `routes/posts.py:198-246`
- §3.4 Activation — insert — ambiguity — requires event `status == RISK_ASSESSED` (`ERR_INVALID_STATE`), and `ERR_PLAN_HAS_NO_POSTS` is judged first — `routes/plans.py:173-180`
- §3.4 Lock — insert — ambiguity — requires the event live (`BRIEFED`/`DOORS_OPEN`/`IN_PROGRESS`/`SUSPENDED`) else `ERR_INVALID_STATE` — `routes/plans.py:191-200`
- §3.4 Plan close — insert — ambiguity — direct `CLOSE` legal only from `LOCKED`, re-derives posts/coverage/ledger and the event gate, does not move the event `status` — `routes/plans.py:206-215`
- §3.4 Lock/close — insert — ambiguity — neither consults the gate interlock — `routes/plans.py:129-131,191-215`
- §3.5 Vendor decisions — insert — ambiguity — transition legality judged before insurance expiry; all three actions recompute `verified_guard_count` before the `version` write — `routes/vendors.py:74-100`
- §3.5 Re-certification — insert — ambiguity — from `VERIFIED` body credential fields ignored; from `REJECTED` both overwritten with `is_supervisor_qualified` re-derived; from `EXPIRED` expiry required (`ERR_INVALID_REQUEST` if absent, `ERR_GUARD_CREDENTIAL_INVALID` if not future) and `credential_level` ignored — `routes/guards.py:135-153`
- §3.5 Credential actions — insert — ambiguity — all four recompute the owning vendor's `verified_guard_count` — `routes/guards.py:154,175,184,191`
- §3.5 Expiry sweep — insert — ambiguity — sweep also recomputes the counts of vendors that lost a guard — `engine.py:606-609`
- §3.5 Clock endpoint — insert — ambiguity — `data` carries exactly `current_utc` plus the two counters; sweep runs on every call including a backwards move (counters zero) — `routes/clock.py:20-28`
- §3.6 Cancellation — insert — ambiguity — `cancellation_reason` is optional; omitted leaves it null — `routes/assignments.py:137-138,209-210`
- §3.7 Doors open — insert — ambiguity — no current plan ⇒ `ERR_EXIT_POSTS_UNSTAFFED`; a missing pinned assessment ⇒ zero lanes required — `routes/events.py:229-231,249-258`
- §3.7 Event clock gates — insert — ambiguity — `START` before `event_start_at`, `CLOSE` before `event_end_at`, `RESUME` with open criticals all give `ERR_INVALID_STATE` (409) — `routes/events.py:199-220`
- §3.7 Lane creation — revise — mismatch — zone scoping is venue-membership only; `is_ingress_zone` is never consulted — `routes/lanes.py:36-41`
- §3.7 Lane reopen — insert — ambiguity — from `HOLD`, non-zero `open_critical_incident_count` is `ERR_INVALID_STATE`, and no event-`status` requirement applies — `routes/lanes.py:92-106`
- §3.7 Check-in — insert — ambiguity — unreached 30-minute lead time is `ERR_INVALID_STATE` (409) — `routes/assignments.py:241-243`
- §3.7 Check-in — insert — ambiguity — runs only the lane refresh, no upward post/plan/event cascade — `routes/assignments.py:247`
- §3.7 No-show — insert — ambiguity — unelapsed 15-minute grace is `ERR_INVALID_STATE` (409) — `routes/assignments.py:254-256`
- §3.7 Relief — insert — ambiguity — null `check_in_at` is `ERR_INVALID_STATE` (409) — `routes/assignments.py:266-267`
- §3.7 Relief pricing — insert — ambiguity — `pay_basis` and `night_differential_applies` are not rewritten at relief; only `billed_hours`/`billed_cost_cents` are written — `engine.py:387-401`
- §3.8 Incident report — insert — ambiguity — nullable stamps start null, `sla_breached` starts boolean `false`, and reporting has no event-status or gate precondition — `routes/incidents.py:62-83`
- §3.9 Close cascade — insert — ambiguity — relieved rows are repriced on delivered time (`billed_hours`/`billed_cost_cents` roll into the plan) and lanes behind their posts are refreshed — `engine.py:502-514`
- §3.9 Close cascade — revise — mismatch — the current plan closes only from `ACTIVATED` or `LOCKED`; a `DRAFT`/`PUBLISHED` current plan is not driven to `CLOSED` and its posts stay open — `engine.py:520-529`
- §3.9 Review creation — revise — mismatch — opening a review has no event-`status` precondition; only the single-open-review rule applies, and `CLOSED` is enforced at submission — `routes/reviews.py:28-32`

**Deliberate non-changes:** all §2.9 formulas, the §3.3 staffing matrix, the §2.7/§2.8 ladders and traversal order, and every GET role set in §4 were verified against `calc.py`/`engine.py`/`routes/` and already matched. Framework-level `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` mapping in `app.py` was left unpinned because documenting it would require new rows in the §5 catalogue, which the minimal-patch constraint forbids.
