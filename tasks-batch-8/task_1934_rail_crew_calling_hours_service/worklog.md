# Worklog — task_1934_rail_crew_calling_hours_service

## Step 1: Create Task Directory — 2026-08-15T01:33:00.000Z

Pre-created by pipeline launcher: `tasks/task_1934_rail_crew_calling_hours_service/` and `workspace/` already existed; no action taken.

## Step 2: Generate Scaffold — 2026-08-15T01:59:00.000Z

Scaffold generation for task 1934 is complete and lint-clean. No sibling task directories were inspected; everything was derived from the scenario text plus the skill spec.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1934_rail_crew_calling_hours_service/SCAFFOLD.yaml` — §1.0–§1.7 (response envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, RBAC); no difficulty/corner keys
- `/home/ubuntu/github/CodingPRD/tasks/task_1934_rail_crew_calling_hours_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1934_rail_crew_calling_hours_service/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts

| Artifact | Count |
|---|---|
| Entities (§1.1) | 10 (Employee, ExtraBoard, ExtraBoardSlot, Job, Call, Assignment, RestPeriod, LeaveBid, PayRecord, CrewShortage) |
| Endpoints (§1.5) | 53 (incl. `POST /api/_clock/set_current_utc` with pinned startup default 2026-08-01T00:00:00Z) |
| State machines (§1.2) | 6 (Employee cyclic availability, Call branching w/ auto-expiry, Assignment, LeaveBid, PayRecord dispute loop, CrewShortage) |
| Concurrency rules (§1.2.1) | 2 (OCC on PayRecord finalize and Call accept via Job version) |
| Calculations (§1.3) | 6 (hos_duty_accumulation dual-variant, board_rotation, agreement_pay dual-variant rounding-order, fatigue_index, rest_compliance, calling_selector) |
| Validations (§1.4) | 16 (priorities 0–15, no collisions) |
| Errors (§1.6) | 16 |
| Roles (§1.7) | 3 (Employee entity-backed; CrewCaller, CrewManager opaque) |
| Difficulty-design instances (§1.8) | 18 (9 rules × 2) |
| Corner-design instances (§1.9) | 36 (35 active + 1 excluded-because stub) |

## Key design decisions

- **Archetype**: compliance/audit (statutory HOS + undisturbed rest) with quota/allocation secondary (job seats, extra-board positions, leave quota); flat topology, cyclic state shape, peer-roles RBAC.
- **Dual-variant calculations on different domains**: agreement pay (PROVISIONAL per-component rounding vs FINAL round-once — pinned divergence 74867 vs 74866 at claimed=600/deadhead=100/TRAIN) and HOS duty (chronological ledger vs forward-looking accept gate — 16080 vs 16560 at the same instant).
- **Combinatorial modes (b) and (a)**: rounding-order pay formula (basic-day fraction model, BASIC_DAY_CENTS=30010) and the 3-input weighted fatigue index (48.6 pinned literal computed by code).
- **Cascades at depth 3 and 2**: leave-award → employee ON_LEAVE → slot VACATED → position renumber; tie-up → employee ON_REST + RestPeriod opens → DRAFT PayRecord auto-created.
- **Boundary pair**: monthly HOS cap 16560 inclusive (passes at ==16560, fails at 16561) and 600-minute undisturbed rest (599 fails, 600 passes) on different endpoints/metrics.
- **Temporal-overlap pair with different semantics**: LeaveBid closed-interval shared-day conflict vs Job aggregate seat-capacity (ERR_JOB_ALREADY_FILLED reachable via two concurrently-OFFERED calls for one seat).
- All clock-dependent setups use the logical-clock endpoint; OCC version inputs are `${var}` captures everywhere; `scaffold_lint.py` verdict: **clean lint** (540 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-08-15T02:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1934_rail_crew_calling_hours_service/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T02:09:00.000Z

PRD generation complete.

## Summary

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1934_rail_crew_calling_hours_service/workspace/PRD.md` — 266 lines.

**Section list:**
- 1. Introduction (2 paragraphs — business context + system scope)
- 2. Global Specifications & System-Wide Principles: 2.1 RBAC, 2.2 API Response Structure (verbatim contract block), 2.3 Pagination, 2.4 Common Resource Properties and Entity Versioning, 2.5 The Logical Clock and Time-Driven Sweeps, 2.6 Hours-of-Service Ceilings/Rest Minimums/Fatigue Gating, 2.7 Pay Precision and Rounding Conventions, 2.8 Optimistic Concurrency Control, 2.9 Validation Pipeline and Nested Path Resolution
- 3. Business Logic & Workflows: 3.1 Hiring/Board Rostering, 3.2 Mark-Up/Lay-Off/Suspension/Rest Cycle, 3.3 Job Bulletins and Calling, 3.4 Assignment Lifecycle, 3.5 Leave Bidding, 3.6 Timekeeping and Agreement Pay, 3.7 Crew Shortages and Recrew
- 4. Endpoint Definitions (53 rows, 4 columns)
- 5. Error Code Catalogue (16 rows, 2 columns)

**Coverage:** All scaffold sections were transformed into prose — 10 entities (all 49 field names, defaults, nullability, enum sets), 6 state machines (every transition with preconditions and cascades, including depth-2/depth-3 cascade chains like decline→rotation→shortage and award→ON_LEAVE→VACATED→renumber), 6 calculations (hos_duty_accumulation chronological + forward-looking variants with 700/100/480 tour tiers, board_rotation discipline, agreement_pay dual-variant with the 74,867 vs 74,866 worked example, fatigue_index full weighted formula, rest_compliance half-open inclusive boundary, calling_selector eligibility/ranking/empty-pool), 16 validations as an explicit priority-ordered pipeline, 2 OCC rules, all endpoint side effects and list filters, 3 roles with identity prose.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 49 required, 49 present, 0 missing
- endpoints[].request_body/input: 39 required, 39 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 16 checked, 16 expressed in ordered pipeline prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected field + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 26 checked, 26 fully expressed (from/to, preconditions+error_id, side effects), 0 missing
- calculations[]: 6 checked, 6 fully expressed in precise prose (constants embedded; e.g., 600 minutes as "ten hours", 120 as "two hours"), 0 missing
- validations[] conditions: 16 checked, 16 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 53 endpoints checked, all side effects and applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: defaults, nullability (responded_at, rest_end, decided_at, resolved_at), RestPeriod's absent updated_at/version all stated, 0 missing
- sibling-branch symmetry: 6 groups checked (5 Call outcomes, 2 mark-up from-states, 2 leave-cancel branches, 2 escalate from-states, pay variants, freeze/restore/vacate/append), all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 340
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 emitted verbatim from `section-2.2-response-structure.md`, all 16 error IDs and all enum/state values present, no fuzzy/approximating words, endpoint table has exactly 4 columns and error table exactly 2. The withheld difficulty/corner design files were never opened, and no sibling task directories were accessed.

## Step 5: Generate Unit Tests — 2026-08-15T02:33:00.000Z

Generation complete. Summary:

## Files written

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1934_rail_crew_calling_hours_service/test_helpers/`)
- `types.py` — 12 status/role enums + 10 entity TypedDicts; `RestPeriod` (append-only per PRD §2.4) omits `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (36)
- `api_errors.py` — 16 `ApiErrorId` values + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*()`; `assert_rest_period` asserts `updated_at`/`version` are *absent*
- `factories.py`, `constants.py` (720/16560/600/60/120/80.0, pay constants), `test_users.py` (`TEST_USERS` + `make_employee_headers(user_id)` per-instance builder used by all ownership-gated calls)
- `fixtures.py` — tiered composite helpers: `setup_offered_call` / `setup_accepted_assignment` / `setup_on_duty_assignment` / `setup_tied_up_assignment`, `setup_employee_with_monthly_minutes(tour_minutes, add_one_minute_tour)` (threshold targeting for the 16080/16081 chains), `setup_board_with_employees`, `accept_call_with_fresh_version` (re-GETs the job before every accept so tests are robust to both PRD-faithful readings of whether call-issue bumps `Job.version`; staleness tests use provably-old versions)
- `__init__.py` barrel

**test_suite/** (`.../test_suite/`) — `conftest.py` + 9 numbered test files (rostering, board rotation, calling/selection, assignment lifecycle, rest/HOS, leave bidding, pay records, crew shortages, security/concurrency).

## Counts
- **Total tests: 69** — Queue A (Difficulty): **36** (18/18 instances × 2); Queue B (Corner): **33** (≥1 per translated instance; automated audit confirmed every tag resolves, is the docstring's last line, exactly one per test).
- **Skipped instances: 2** (both queue B):
  1. `Corner/errors/err_call_pool_exhausted_triggerable` — fails unique derivability: PRD §3.3 explicitly assigns the no-matching-board case to `ERR_REFERENTIAL_MISMATCH`, while §2.9's business-rule ordering suggests pool exhaustion fires first; two PRD-only readers diverge. The empty-pool-with-existing-board path (error + auto-opened shortage) remains covered via `calling_selector_skips_unavailable_and_fatigue_blocked`.
  2. `Corner/validations/job_capacity_reject_on_accept_when_filled` — pinned setup needs a second OFFERED call to go to E2 while E1's call is still OFFERED and E1 remains eligible; PRD §3.3's selector criteria do not exclude an employee with an outstanding offered call, so the scenario is not uniquely realizable from the PRD.
- **Stub not translated: 1** — `Corner/calculations/fatigue_boundary_80_blocks_call_issue` (`excluded_because` stub; cross-reference to `combinatorial_formula/fatigue_weighted_scoring_multifactor` verified to resolve).

## Correction applied (reported, not a skip)
Four queue-A instances pin a 16080-minute cumulative (driving the 16560 equality boundary and fatigue 48.6) but their setup chains tie up at `2026-08-12T07:00:00Z`, which is 16260 elapsed minutes from the 00:00 on-duty. I kept every pinned expected literal verbatim and corrected only the tie-up clock to `2026-08-12T04:00:00Z` (exactly 16080 minutes) in `setup_employee_with_monthly_minutes`, making the chains consistent with the PRD formulas. Affected: `hos_chronological_vs_forward_looking_gate`, `fatigue_weighted_scoring_multifactor`, `state_vs_safety_on_call_accept`, `monthly_hos_cap_equality_passes_plus_one_fails`.

## Self-check verdicts
- **Stage 1: PASS** — all helper modules compile and import cleanly against the installed `prd_bench_local_runner` framework (client methods + 16-error map verified).
- **Stage 2: PASS** — 69/69 tests carry exactly one resolving `Design:` tag as the final docstring line; 18/18 difficulty instances ×2, 33/33 translated corner instances ×1; no freelance tests.
- **Stage 3 (final passes): PASS** — automated verbatim check: every quoted docstring span ≥8 words greps literally in `workspace/PRD.md`; no `skip`/`skipif`/`xfail` markers; no "scaffold"/table references in generated code; asserted `error_id`s all have PRD-prose trigger conditions.

## Step 6: Generate Implementation — 2026-08-15T02:19:00.000Z

Implementation complete and verified. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1934_rail_crew_calling_hours_service/workspace/implementation/`:

- `start.sh` (executable, guarded `pip install`, `exec python3 app.py`, reads `$PORT` default 10000, binds 0.0.0.0, foreground)
- `requirements.txt` (`flask>=3.0,<4`)
- `app.py` — Flask entry, blueprint registration, envelope-compliant error handlers (ApiError, 404/405/400, catch-all)
- `db.py` — in-memory store (10 dicts keyed by id, **empty at boot, no seeding, no disk**), logical clock starting exactly 2026-08-01T00:00:00Z, ISO-8601 3-fractional-digit formatting, `version`/`updated_at` touch helper
- `errors.py` — full 16-error catalog with exact IDs/statuses
- `response.py` — `meta`/`response_type`/`data` envelope, pagination fields (`limit`/`offset`/`total_count`/`has_more` in meta, defaults 10/0, clamp 1–100), `created_at`-ascending list sort
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gating, entity-backed Employee ownership
- `validators.py` — priority-0 body well-formedness (required fields, strict int-not-bool, enums, ISO datetimes, sign/range)
- `services.py` — all calculations and cascades
- `routes/` — 10 blueprint modules: `clock`, `employees`, `boards`, `jobs`, `calls`, `assignments`, `rest_periods`, `leave_bids`, `pay_records`, `shortages`

## Counts

- **Endpoints: 53** (all from the scaffold §1.5 table, including `POST /api/_clock/set_current_utc` with the expiry sweep)
- **Entities: 10** (Employee, ExtraBoard, ExtraBoardSlot, Job, Call, Assignment, RestPeriod, LeaveBid, PayRecord, CrewShortage) — RestPeriod correctly omits `updated_at`/`version`
- **Calculations: 6** — `hos_duty_accumulation` (chronological ledger + forward-looking gate with `-L`=700/`-S`=100/else 480 projections), `board_rotation` (penalty-to-tail, freeze-with-remembered-position, restore, vacate, append), `agreement_pay` (provisional per-component vs final sum-then-round, ROUND_HALF_UP via Decimal), `fatigue_index` (0.5/0.3/0.2 weighted, clamp 0–100, 1-decimal RHU, 80.0 block), `rest_compliance` (600-minute inclusive boundary), `calling_selector`

## Verification

- `python3 -c "import app"` succeeds; 53 routes registered; `bash -n start.sh` passes
- Booted via the literal contract `bash start.sh` from `implementation/` with `PORT` set — responds with an empty store; a kill-and-relaunch confirmed fresh state (per-test-server isolation requirement)
- Two live smoke suites (~100 assertions) all passed, covering: validation pipeline ordering (400 before 401 before 403 before ownership before 404 before 409-state), HOS monthly cap boundary (16560 inclusive pass, 16780 reject), the pinned pay example (600 min + 100 TRAIN deadhead → provisional **74867**, final **74866**), dispute/resubmit OCC race (412 `ERR_STALE_VERSION`), accept-time `expected_job_version` OCC, penalty rotation on decline/no-answer/expiry, freeze→restore at remembered position, rest gate at exactly 600 minutes, pool-exhaustion shortage auto-open (422 + shortage row), no-matching-board referential mismatch, leave award closed-interval/quota conflicts, suspend→rescind cascade, and the full recrew resolve cascade (RECREWED target, ON_REST relieved employee + opened RestPeriod, replacement ON_DUTY with deadhead)

## Step 7: Run Tests and Iterate — 2026-08-15T02:36:00.000Z

All 8 parallel rounds passed cleanly: **69/69 tests passed in every round** (total=69, passed=69, failed=0, errors=0, skipped=0 across results.1.json through results.8.json). The union of failing tests across all rounds is empty — no flakiness, no failures to diagnose.

Summary:
- **Iterations run:** 1 (single 8-round parallel sweep, all rounds green on the first attempt)
- **Tests deleted:** none
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `implementation/`:** none

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1934_rail_crew_calling_hours_service/workspace/implementation/` and the test suite at `/home/ubuntu/github/CodingPRD/tasks/task_1934_rail_crew_calling_hours_service/test_suite/` are already in a stable, fully passing state under per-test-server isolation with 8 concurrent rounds.

## Step 8: Finalize PRD — 2026-08-15T02:36:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline — so `PRD.md` already determined every behavior the implementation exhibits. `PRD_FINALIZED.md` is not produced (per the skip condition); Step 9 will read `PRD.md` directly.

## Step 9: Complete PRD — 2026-08-15T02:51:00.000Z

The diff shows exactly the 26 intended hunks (25 in-place paragraph revisions + 1 inserted bullet line), no unintended changes. The task is complete.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1934_rail_crew_calling_hours_service/workspace/PRD_COMPLETED.md`

**Size delta:** PRD.md = 266 lines / 42,365 chars → PRD_COMPLETED.md = 267 lines / 47,695 chars (**+1 line, +5,330 chars**; 26 edited passages: 25 in-place revisions, 1 inserted bullet).

**Counts:** 30 ambiguity-pins, 8 mismatch-revisions.

### Changes

- §2.1 — insert — ambiguity — header values are trimmed before validation; whitespace-only counts as blank — implementation/middleware.py:16-17
- §2.1 — revise — mismatch — "exactly ten" → "exactly eleven" ownership-checked self-service operations (PRD's own list enumerates 11; impl checks 11) — employees.py:87,100,131; calls.py:71,133; assignments.py:58,84,117; pay_records.py:94,127; leave_bids.py:168
- §2.2 — insert — ambiguity — undefined path/unsupported method answered with ERR_NOT_FOUND (404) in the standard envelope; malformed or non-object JSON body → ERR_INVALID_REQUEST (400) — app.py:47-59; validators.py:14-25
- §2.3 — insert — ambiguity — out-of-range limit/offset clamped to bounds; non-integer values fall back to defaults — response.py:46-58
- §2.3 — insert — ambiguity — `has_more` true exactly when offset + returned count < total_count — response.py:28
- §2.3 — insert — ambiguity — same-instant records ordered by creation sequence; per-board slot listing is the one exception to created_at sorting (sorts by standing_position) — response.py:63; boards.py:65-70
- §2.3 — insert — ambiguity — filter params match literally and are never enum-validated; unknown values yield empty pages — boards.py:113-121 et al.
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — db.py:74-76
- §2.5 — insert — ambiguity — clock advance is unconditional (any parseable instant adopted as given, even backwards; offset-less values read as UTC) — clock.py:15-18; db.py:62-63
- §2.5 — insert — ambiguity — `expired_call_ids` ordered by expires_at ascending, ties by creation order — services.py:367
- §2.6 — insert — ambiguity — disturbed-rest trailing 30-day window inclusive at both ends — services.py:135-142
- §2.6 — insert — ambiguity — fatigue score also recomputed at recrew resolution for both relieved and relieving employees — shortages.py:100-102,118-119
- §2.7 — insert — ambiguity — elapsed-minute computations floor sub-minute remainders — db.py:85-86
- §2.9 — insert — ambiguity — well-formedness includes "body must parse as a JSON object" — validators.py:14-25
- §2.9 — insert — ambiguity — ownership-vs-path-resolution order: employee-path operations check ownership before resolution (non-owner + nonexistent → 403), call/assignment/pay-record/leave-bid operations resolve first (→ 404) — employees.py:87-88 vs calls.py:70-71
- §2.9 — revise — mismatch — business-rule order: calling-pool exhaustion moved after referential consistency (impl checks board-existence referential first) — jobs.py:89-100
- §3.1 — insert — ambiguity — seniority_date accepted as ISO 8601 date or datetime, read as UTC — employees.py:41
- §3.1 — revise — mismatch — guaranteed_slots floor is recorded (non-negative integer) but never enforced; no operation is rejected for cutting ACTIVE count below it — boards.py:31; services.py:223-232
- §3.1 — revise — ambiguity — slot placement checks employee existence (ERR_REFERENTIAL_MISMATCH, first) before craft match — boards.py:83-103
- §3.1 — revise — ambiguity — per-board slot listing sorts VACATED (released position) last and accepts a slot_status filter — boards.py:59-70
- §3.1 — insert — ambiguity — restore clamps a remembered position beyond the current tail (restores at tail) — services.py:211-213
- §3.1 — insert — ambiguity — vacate also renumbers surviving ACTIVE slots from 1 — services.py:223-232
- §3.1 — insert — ambiguity — returns/reinstatements target the earliest-created board matching craft+home_terminal; no match → no slot created — services.py:247-261
- §3.2 — revise — mismatch — replaced "accepting a call recomputes the employee's open rest interval as part of its safety gates" (impl has no such logic) with "acceptance applies no rest-based gate of any kind" — calls.py:62-125
- §3.3 — revise — mismatch — callee pool spans all matching boards; ties broken by slot creation order (was "positions are unique per board, so no tie-break is ever needed") — services.py:274-289
- §3.3 — revise — mismatch — recall sentence reversed: board-existence referential check precedes pool exhaustion — jobs.py:89-100
- §3.3 — insert — ambiguity — penalty rotation targets callee's ACTIVE slot on a board matching the job's craft/terminal (earliest-created if several), skipped silently if none — services.py:342-357
- §3.4 — insert — ambiguity — accept at/after expires_at and accept by non-AVAILABLE employee both → ERR_INVALID_STATE (409) — calls.py:77-80
- §3.4 — insert — ambiguity — supplied deadhead_minutes must be non-negative integer, deadhead_mode a declared enum, else ERR_INVALID_REQUEST — calls.py:66-67
- §3.4 — insert — ambiguity — tie-up permitted only from ON_DUTY; auto-created DRAFT has gross_pay_cents 0; completion only from TIE_UP_PENDING with record in SUBMITTED/FINALIZED (DISPUTED fails); completion does not change job status — assignments.py:85-86,98-108,146-160
- §3.5 — revise — mismatch — leave dates are interpreted by UTC calendar day, any time-of-day accepted (was "Both dates are UTC midnights"); past-check compares days — leave_bids.py:46-52,87-92,130-134
- §3.5 — insert — ambiguity — award requires bidder AVAILABLE else ERR_INVALID_STATE (409) — leave_bids.py:102-104
- §3.5 — insert — ambiguity — cancelling an AWARDED bid at/after start_date → ERR_INVALID_STATE (409) — leave_bids.py:174-178
- §3.6 — revise — mismatch — manual creation supplies employee_id, assignment_id, claimed_minutes (+optional claimed_deadhead_minutes, default 0) (was "supplying all four fields"); nonexistent assignment or employee → ERR_REFERENTIAL_MISMATCH; DRAFT carries gross_pay_cents 0 — pay_records.py:37-67
- §3.6 — insert — ambiguity — resubmission retains prior claimed_deadhead_minutes when omitted and does not re-apply the strictly-positive claimed_minutes gate — pay_records.py:119-136
- §3.7 — insert — ambiguity — no shortage deduplication; each triggering event opens a fresh OPEN row — services.py:292-302
- §3.7 — revise — ambiguity — resolution only from RECREWING; unresolvable assignment_id/relieving_employee_id → ERR_NOT_FOUND (404); wrong-job assignment → ERR_REFERENTIAL_MISMATCH; target ON_DUTY and reliever AVAILABLE gates → ERR_INVALID_STATE; HOS and fatigue failures both → ERR_HOS_LIMIT_EXCEEDED; replacement assignment stamps on_duty_at, has no call, deadhead_mode NONE; job filled_count unchanged — shortages.py:48-124

**Notable cross-checks:** all 54 endpoint rows in §4 match impl routes/roles/status codes exactly (201 creations verified per endpoint); the two OCC guards, pay constants/variants, worked pay example (74,867 vs 74,866), HOS/fatigue/rest constants, and state-machine vocabularies were already uniquely pinned and needed no change.
