## Step 2: Generate Scaffold — 2026-08-15T00:30:11.000Z

## Task 1898 scaffold — complete

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1898_curriculum_approval_workflow_catalog/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys), scenario verbatim
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 18 instances (2 per rule)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 48 instances (39 live + 9 `excluded_because` stubs)

**Design summary**
- Profile: workflow orchestration (committee routing) + graph constraint (prereq DAG); layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers; graph topology, cyclic state shape, approval-chain roles, immediate consistency.
- 10 entities (Department, Term, Course, Proposal, DecisionRecord, RequisiteLink, CrossListing, TeachOutPlan, CatalogEdition, CatalogEntry), 36 endpoints (incl. `POST /curriculum/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default), 23 errors, 23 ordered validation rows, 8 state machines, 6 calculations, 2 OCC concurrency rules, 5 roles (DepartmentChair is `entity_backed:Department`; others opaque).
- Difficulty anchors: provisional-vs-final substantive-change score (30→65 across the >=50 accreditor threshold) and enrollment-vs-catalog teach-out completion (seq 5 vs 8); combinatorial formulas in mode (a) (multi-factor score = 55) and mode (b) (per-cohort rounding pinned: [16,9] → 1,200,000 cents vs 800,000 sum-first); cyclic Proposal RETURNED loop + CrossListing approve-either-order diamond with rescind; depth-3 deactivation cascade (Proposal→Course→RequisiteLink→dependent Course summary) and depth-2 publish cascade (Edition→Entries→Course.last_published + archive arm); priority conflicts state-vs-temporal and safety-vs-referential; half-open term adjacency vs closed+contiguous edition windows; course-number hold/release and term scheduled-count reassignment conservation invariants.

**Verification**
- `scaffold_lint.py` verdict block, verbatim:
  ```
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  ```
  (534 calls scanned across 18 §1.8 + 39 live §1.9 instances; 0 violations.)
- Additional mechanical checks passed: all YAML parses; instance names unique across both design files (66 total); every stub cites an existing §1.8 instance and carries no `test_recipe`; every rule has exactly 2 instances; no forbidden concurrency vocabulary; all list-order-dependent captures eliminated (added `course_number?` filter to `GET /curriculum/courses`); all formula-derived asserts precomputed as literals.
- Note: a pre-existing empty `workspace/` directory sits in the task dir (not created by this run); left untouched.

## Step 3: Copy Shared Files — 2026-08-15T00:30:45.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1898_curriculum_approval_workflow_catalog/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T00:36:46.000Z

**PRD generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1898_curriculum_approval_workflow_catalog/workspace/PRD.md`

**Structure:** §1 Introduction (3 paragraphs, user-pain-point angle) · §2 with 9 subsections (RBAC with per-role identity translation, verbatim §2.2 envelope block, pagination, common resource properties including the `DecisionRecord` `common_fields: false` exception, the logical clock with its `2026-08-01T00:00:00Z` startup default, OCC for the two guarded writes, nested retrieval, full 23-rule validation priority ordering, numeric precision) · §3 with 11 subsections organized by domain lifecycle (groundwork → course record → drafting → submission gate → committee gauntlet → scoring/notification → registrar approval/activation → teach-out → cross-listing → editions → audit log and read surfaces) · §4 endpoint table (4 columns, 36 endpoints) · §5 error catalogue (2 columns, 23 errors).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 67 required, 67 present, 0 missing
- endpoints[].request_body extras (to_iso8601, current_utc, expected_term_version, expected_proposal_version): 4 required, 4 present, 0 missing
- endpoints[].query_params (limit, offset + 16 filter names): 18 required, 18 present, 0 missing
- enum/state/role values: 48 required, 48 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose (§2.8 enumerates the full priority chain explicitly), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_*_version field + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 45 checked across 8 machines, 45 fully expressed (from/to states, preconditions paired with error IDs, side effects incl. cascades), 0 missing
- calculations[]: 6 checked, 6 fully expressed in precise prose (substantive_change_score both variants with all 9 constants; teach_out_completion_terms both variants with worked examples 3+ceil(3/2)=5 and 4+4=8; teach_out_resource_cost_cents with pinned per-cohort rounding and the 16/9 → 3 sections → 1,200,000 cents contrast; requisite_cycle_check reachability semantics; credit_hour_workload_check with 15 weeks / 45 Carnegie hours / 0.5 inclusive tolerance; edition_freeze_snapshot sweep), 0 missing
- validations[] conditions: 23 checked, 23 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (course-number uniqueness enforced at all 3 checkpoints; version increments stated per mutation), 0 missing
- entities[].fields[] structured content: defaults (proposed_requisites []), nullability (notification_sent_at, effective_term_id, committed_completion_sequence, resource_cost_cents, last_published_edition_id), and system-vs-input sources reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (4 approves, 4 returns, 4 rejects, 7 withdraws, 3 cross-listing rejects, 2 rescinds, 2 side-approvals, freeze pair) — equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 445
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. §2.2 verified byte-identical to the canonical source file. No pseudocode/operator leakage; the single "around" token is ordinary English ("statuses around the action"), not numeric approximation. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Step 5: Generate Unit Tests — 2026-08-15T01:07:05.000Z

All checks pass. The generation is complete.

## Summary

**Generated for task_1898_curriculum_approval_workflow_catalog:**

**`test_helpers/` (9 files)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1898_curriculum_approval_workflow_catalog/test_helpers/`:
- `types.py` — TypedDicts for all 10 entities (DecisionRecord correctly omits `updated_at`/`version` per the append-only rule) + 11 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (32 methods, all under `/curriculum`)
- `api_errors.py` — all 23 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions, with `assert_decision_record` enforcing the absent-`version`/`updated_at` audit shape
- `factories.py` — payload factories with canonical term/edition frames (all freeze instants after the 2026-08-01 logical-clock default) and workload-consistent defaults (3+6 hours → 3.0 computed credits)
- `constants.py` — scoring/teach-out/workload thresholds from the PRD
- `test_users.py` — `TEST_USERS` constants plus per-instance builders; `make_chair_headers(department_id)` for the entity-backed DepartmentChair identity threading
- `fixtures.py` — composite setups: full committee-gauntlet walkers, term freezing, create-and-activate NEW_COURSE lifecycle, committed teach-out pipelines, cross-listing pairs, read-side conveniences
- `__init__.py` — barrel re-exporting framework + domain names

**`test_suite/`** — `conftest.py` + 8 test files, **75 tests**, all collected by pytest:
1. `test_01_proposal_creation_envelope.py` (7) — creation validation, identity copying, 404, pagination, decision-record shape, 401
2. `test_02_terms_editions_and_catalog_time.py` (11) — term defaults, sequence/overlap/freeze rules, edition closed-interval contiguity, publish cascade depth-2, freeze-sweep filtering
3. `test_03_write_guards.py` (7) — RBAC, ownership, self-approval, both OCC rules
4. `test_04_submission_gate.py` (9) — double submit, credit workload, self-requisite, inactive requisite target, empty outcomes, term-window gating, state-vs-temporal priority
5. `test_05_scoring_and_notification.py` (10) — provisional vs final score (30→65), multi-factor 55, threshold exactly-50, notification-pending priority, NOTIFY gating/stamping
6. `test_06_decisions_withdrawal_term_ledgers.py` (11) — RETURNED resubmission cycle, terminal lockdowns, immediate consistency, withdraw/reassign term-count conservation, number-hold conservation
7. `test_07_courses_requisites_cross_listings.py` (8) — duplicate import, unlocked-term activation, DAG chain, cycle rejection, COREQUISITE exemption, cross-listing diamond with rescind, duplicate pair
8. `test_08_deactivation_and_teach_out.py` (12) — dual completion variants (5 vs 8), pinned per-cohort rounding (1,200,000 cents), constants, cohort-mismatch 400s, zero-cohort boundary, plan-gated retirement, depth-3 deactivation cascade

**Audit results:** every test's docstring ends with exactly one `Design:` tag resolving to a real instance; all 18 difficulty instances have ≥2 tests; all non-stub corner instances have ≥1 test; all 9 `excluded_because:` stubs untranslated with cross-references verified; 109/109 quoted citation spans match PRD.md verbatim (whitespace-normalized); no skip/xfail markers; no scaffold references; pyflakes clean.

**Two adjudications worth noting:**
1. **Skipped** `Corner/entities/create_proposal_extra_field_rejected` — the PRD's body-validation rule (§2.8) never states that unknown/client-supplied computed fields are rejected, so two PRD-only readers could legitimately diverge (ignore vs reject). Gap left as a gap per the Core rule.
2. **Reachability fixes without assertion changes** — four corner recipes (`prerequisite_chain_dag_accepted`, `prerequisite_cycle_activation_rejected`, `corequisite_edge_exempt_from_cycle`, `edition_freeze_sweep_filters_staged_entries`) as written submit a proposal against an already-frozen term, which the PRD's window rule (`ERR_PROPOSAL_WINDOW_CLOSED`) forbids. The generated tests route those proposals through a still-OPEN sibling term (the same pattern the difficulty index itself uses in `deactivation_activation_cascade_depth3`), with registrar approval assigning the frozen effective term. Every asserted outcome is unchanged from the design index.

## Step 6: Generate Implementation — 2026-08-15T01:07:05.000Z

Done. The implementation is complete and the full benchmark suite passes.

## Result

**55/55 tests passed, 0 failed, 0 errors** under `prd-bench-local-run --isolation per-test-server` (each test rebooted the server via `start.sh` — 55 clean fresh-process boots), plus a manual `bash start.sh` contract check from `./implementation/` confirming fresh boot, empty store, and the correct envelope.

## Deliverables

All in `/home/ubuntu/github/CodingPRD/tasks/task_1898_curriculum_approval_workflow_catalog/workspace/implementation/`:

- `start.sh` — guarded launcher (`exec python3 app.py`, pip install only if flask missing), binds `0.0.0.0:$PORT` (default 10000), foreground
- `app.py` — Flask entry, blueprint registration, envelope-wrapped error handlers (ApiError/404/405/500)
- `db.py` — in-memory store (empty at boot, no seeding), wall-clock timestamps (3-fractional-digit ISO Z), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, version/touch helpers
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, five roles, ERR_UNAUTHENTICATED/ERR_FORBIDDEN
- `helpers.py` — strict body shape validation (unknown-field rejection, typed kinds, strict date/datetime parsing), body-FK existence as ERR_VALIDATION, path-id resolution as ERR_NOT_FOUND, pagination (limit default 10/min 1/max 100, offset default 0), `scheduled_proposal_count`/`prerequisite_summary` computed at read
- `calc.py` — substantive-change score (PROVISIONAL vs FINAL variants, Decimal credit-delta ratio, prereq factor cap 20, threshold >= 50), credit-hour workload check (Decimal ROUND_HALF_UP, 1dp, inclusive 0.5 tolerance), teach-out provisional/committed sequences, per-cohort-ceil section cost, PREREQUISITE-only cycle reachability
- `routes_core.py`, `routes_proposals.py`, `routes_teachout.py`, `routes_catalog.py` — all 34 endpoints

## Key fidelity decisions (verified against tests/design docs)

- Validation priority follows PRD §2.8 exactly: type-specific submit completeness surfaces as ERR_VALIDATION *before* ownership/state; the window check is first among business rules only; ERR_ACCREDITOR_NOTIFICATION_PENDING (9) beats ERR_TEACH_OUT_NOT_COMMITTED (13); cycle check (15) precedes number-hold recheck (17) at activation
- Number holds are derived from in-flight NEW_COURSE proposals; activation re-checks excluding self
- Withdraw from APPROVED releases the hold and decrements the term count but does *not* remove PROPOSED links (scaffold side effects are explicit); withdraw from review stages does
- Every cascade mutation bumps the target's `version`/`updated_at` (e.g., dependent course hits version 3 in the depth-3 deactivation cascade); archived editions keep courses' `last_published_edition_id`
- Course-number pair on COURSE_CHANGE is required at submit but never applied to the course at activation (only title/credits/hours/outcomes overwrite)
- Terms use half-open intervals (adjacency allowed); editions use closed intervals with mandatory day-after contiguity and academic_year uniqueness among non-ARCHIVED

One environment note: the runner's per-test restart derives cwd from a `cd <dir> &&` prefix in `--start-command`, so it must be invoked with an absolute path (e.g. `--start-command "cd <abs impl dir> && bash start.sh"`); a relative `bash workspace/implementation/start.sh` fails to respawn. The implementation itself is unaffected.

## Step 7: Run Tests and Iterate — 2026-08-15T01:11:20.000Z

Clean 8-round parallel sweep — all rounds green on the first iteration. Exiting per protocol.

## Summary

**Iterations run: 1** (one 8-round parallel stability sweep; no fixes needed).

**Sweep result:** All 8 rounds completed with `passed == total == 75`, `failed == 0`, `errors == 0`, `skipped == 0`. That is 75 tests × 8 rounds = 600 test executions, each against a fresh server boot via `start.sh` (per-test-server isolation), with 8 rounds running concurrently on separate auto-allocated ports. Zero failures in any round means no correctness bugs and no timing/ordering flakiness surfaced.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Notes:**
- The task arrived already implemented (prior worklog entry claims a single 55/55 run; the suite now contains 75 tests, all passing). My audit read of PRD.md, all 8 test files, all test_helpers modules, and the full implementation (`app.py`, `db.py`, `calc.py`, `helpers.py`, `middleware.py`, `response.py`, `errors.py`, `routes_core.py`, `routes_proposals.py`, `routes_teachout.py`, `routes_catalog.py`) found the test assertions trace verbatim to PRD prose (each test docstring cites the exact PRD sentence), the helpers construct PRD-consistent identities (entity-backed `DepartmentChair` headers use `Department.id`; proposer calls reuse the stored `proposer_id` string), and the implementation encodes the PRD state machines, validation priority order (§2.8), dual-variant scoring (§3.6), pinned rounding orders (§2.9/§3.8), and cascades (§3.7/§3.10) with in-memory-only storage and no seeding.
- Result artifacts: `/home/ubuntu/github/CodingPRD/tasks/task_1898_curriculum_approval_workflow_catalog/workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — SKIPPED

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. PRD.md already determined every behavior the implementation exhibits; no PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-08-15T01:24:15.000Z

PRD_COMPLETED.md is complete. Summary:

**Files & delta**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_1898_curriculum_approval_workflow_catalog/workspace/PRD.md` — 290 lines, 46278 chars
- Produced: `/home/ubuntu/github/CodingPRD/tasks/task_1898_curriculum_approval_workflow_catalog/workspace/PRD_COMPLETED.md` — 292 lines, 49093 chars (**+2 lines, +2815 chars**)

**Counts**: 24 changes total — 20 ambiguity-pins, 4 mismatch-revisions. All inline inserts/revisions; no new sections.

**Changes** (impl paths relative to `workspace/implementation/`):

- §2.2 — revise — mismatch — error-envelope scope widened "(4xx status codes)" → "(4xx and 5xx status codes)" since the catch-all handler emits a 500 in the same envelope — `app.py:39-41`
- §2.2 — insert — ambiguity — new bullet: unknown path or unsupported method surfaces as `ERR_NOT_FOUND` (404); unexpected failure as `ERR_INTERNAL` (500) — `app.py:29-41`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_VALIDATION`; `has_more` ⇔ `offset + returned items < total_count` — `helpers.py:148-161`, `response.py:29`
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — `db.py:58-66`
- §2.5 — insert — ambiguity — offset-less `to_iso8601` read as UTC; set-call echoes supplied value verbatim as `current_utc`; `created_at`/`updated_at`/`api_request_timestamp` are wall-clock, logical clock governs only gating and `notification_sent_at` — `helpers.py:40-53`, `routes_core.py:22-29`, `db.py:22-24,52-53`
- §2.6 — revise — mismatch — stale-version trigger is any inequality with current version, not only "advanced beyond" — `routes_proposals.py:192-193`, `routes_core.py:142-143`
- §2.8 — insert — ambiguity — body-shape failures enumerated (non-JSON-object body, unknown field, missing/null required, mistyped value); explicit null on an optional field treated as absent — `helpers.py:17-27,78-98`
- §2.8 — insert — ambiguity — OCC check position pinned: after body validation; before overlap rule on term edit; after ownership and state checks on proposal edit — `routes_core.py:140-144`, `routes_proposals.py:186-193`
- §3.1 — insert — ambiguity — term date edit allowed in any lifecycle status — `routes_core.py:123-149` (no status check)
- §3.2 — insert — ambiguity — `prerequisite_summary` join pinned to single comma, no spaces (e.g. `CS 101,CS 201`) — `helpers.py:183-194`
- §3.2 — insert — ambiguity — empty `learning_outcomes` on direct import rejected with `ERR_VALIDATION` (not `ERR_LEARNING_OUTCOMES_REQUIRED`) — `routes_core.py:197-198`
- §3.3 — insert — ambiguity — `target_course_id` requirement binds at submission; drafts may be created with it null — `routes_proposals.py:84,208-225`
- §3.3 — insert — ambiguity — `declared_remaining_cohorts` on a non-DEACTIVATION proposal, or negative, rejected with `ERR_VALIDATION` — `routes_proposals.py:62-71`
- §3.5 — insert — ambiguity — decisions endpoint accepts exactly `APPROVE`/`RETURN`/`REJECT`/`NOTIFY`/`REASSIGN_TERM`; other action strings → `ERR_VALIDATION` — `routes_proposals.py:35,324-326`
- §3.5 — revise — mismatch — dept-stage ownership check applies to approve, return, AND reject (PRD said approval only) — `routes_proposals.py:342-344`
- §3.5 — revise — mismatch — withdrawal from `APPROVED` leaves `PROPOSED` links in place (PRD's "additionally" implied link removal); only hold release + count decrement — `routes_proposals.py:299-303`
- §3.6 — insert — ambiguity — target course with current `credit_hours` of zero never triggers the +25 credit-shift factor — `calc.py:66-72`
- §3.7 — insert — ambiguity — new-course activation sets `owning_department_id` to the proposal's `proposer_department_id` — `routes_proposals.py:507`
- §3.8 — insert — ambiguity — teach-out plan creatable in any proposal status; non-DEACTIVATION target → `ERR_VALIDATION`; second plan → `ERR_INVALID_STATE` — `routes_teachout.py:32-39`
- §3.9 — insert — ambiguity — self-pairing → `ERR_VALIDATION`; either course not `ACTIVE` at creation → `ERR_INVALID_STATE` — `routes_catalog.py:46-53`
- §3.9 — insert — ambiguity — cross-listing reject `rationale` accepted but not persisted — `routes_catalog.py:106-117`
- §3.10 — insert — ambiguity — edition's `included_entry_count` initialized to 0 at creation — `routes_catalog.py:179`
- §4 — insert — ambiguity — no-body action endpoints (submit, withdraw, activate, teach-out commit/complete, cross-listing approve/rescind, edition freeze/publish) reject any body field with `ERR_VALIDATION`; the two term-freeze actions ignore the body — `routes_proposals.py:232,296,461`, `routes_teachout.py:80,98`, `routes_catalog.py:76,124,190,224`, `routes_core.py:152-175`
- §5 — insert — ambiguity — `ERR_INTERNAL` | 500 row added to the error catalogue — `app.py:39-41`
