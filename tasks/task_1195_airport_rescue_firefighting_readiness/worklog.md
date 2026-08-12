# Worklog — task_1195_airport_rescue_firefighting_readiness

## Step 1: Create Task Directory — 2026-08-11T17:26:00.000Z

Task directory `tasks/task_1195_airport_rescue_firefighting_readiness/` and its `workspace/` subdirectory were pre-assigned and already exist. Index 1195 assigned externally (Step 1 auto-index scan skipped per instructions). Treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-11T18:19:00.000Z

All three scaffold artifacts are generated and the lint verdict is clean. Summary:

## Task 1195 — ARFF Readiness scaffold: complete

**Output files**
- `/home/ubuntu/github/CodingPRD/tasks/task_1195_airport_rescue_firefighting_readiness/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1195_airport_rescue_firefighting_readiness/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design:` key)
- `/home/ubuntu/github/CodingPRD/tasks/task_1195_airport_rescue_firefighting_readiness/SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design:` key)

**Counts**
- Entities: **16** (flat topology under `/arff`, peers linked by FK)
- Endpoints: **70**
- State machines: **12** (cyclic vehicle readiness, cyclic report review loop, branching drills/requests/notifications/inspections, auto-transitions for agreement expiry and notification overdue)
- Calculations: **9** (incl. two dual-variant rules: agent capacity rated-vs-measured, staffing roster-vs-deployment-ready)
- Validations: 10 ordered priority rows; Errors: **67**; Roles: 5 (Firefighter is `entity_backed:Firefighter`, rest opaque; SoD rule on report accept)
- Concurrency: 1 OCC rule (`expected_profile_version` on `POST /arff/index-determinations`, 412 `ERR_STALE_PROFILE_VERSION`)
- §1.8 difficulty instances: **18** (exactly 2 per rule, all nine §0.5 rules; every rule's differentiation clause pinned in `distinguishing_aspect`)
- §1.9 corner instances: **46 active + 3 `excluded_because:` stubs** across all nine claim-extraction-guide sections (incl. three multi-error "battery" fixtures so every catalog error is triggered by at least one test)

**Design adjudications made**
- Notification creation is **transition-based** (fires only when `effective_index` crosses from >= certificated to < certificated, none open): build-up of a never-compliant airport does not spam notifications. Two recipes (dv_agent_capacity, sm_notification_overdue) were restructured to a comply-then-degrade flow to match.
- Drill windows use **half-open** `[start,end)` overlap (adjacency allowed); mutual-aid agreement windows use **closed** inclusive overlap (touching dates conflict) — Rule 8's two interval semantics.
- Agent-expense rounding pinned as **round-per-line-then-sum** (fixture computes 1183c vs 1182c for the other order).
- Training currency pinned to calendar-month arithmetic (`month_index` diff <= 12, inclusive), with a 12-vs-13 boundary instance.
- `ERR_PROFILE_NOT_COMPLIANT` is reachable only via aircraft-register growth (required index rises above effective without a downgrade notification) — the inspection battery exercises exactly that path.
- Logical-clock endpoint declared with the mandatory default `2026-05-01T00:00:00Z`; clock-set drives all time-derived re-evaluation (currency lapse, agreement expiry, overdue).

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (70 endpoints, 16 entities, 18+46 instances, 794 calls scanned).

Orchestrator verification: all three files exist and parse as valid YAML (SCAFFOLD.yaml 83356 B, SCAFFOLD_DIFFICULTY_DESIGN.yaml 81766 B, SCAFFOLD_CORNER_DESIGN.yaml 112743 B).

## Step 3: Copy Shared Files — 2026-08-11T18:19:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1195_airport_rescue_firefighting_readiness/workspace/INSTRUCTION.md` (1424 B).

## Step 4: Generate PRD — 2026-08-11T18:29:00.000Z

All three contracts PASS.

## Summary

**PRD line count:** 365 lines

**Section coverage:**
- §1 Introduction (3 paragraphs): System goals, business context, role diversity
- §2.1 User and Role-Based Access Control — headers, all 5 roles with identity prose (opaque vs entity_backed)
- §2.2 API Response Structure — verbatim from `section-2.2-response-structure.md`
- §2.3 Pagination — `limit` (default 10, min 1, max 100), `offset` (default 0), `created_at` ascending sort, meta fields
- §2.4 Common Resource Properties — `id` UUID, `created_at`, `updated_at`, `version` semantics, profile version bump triggers
- §2.5 Logical Clock — initial value `2026-05-01T00:00:00Z`, `to_iso8601` parameter, time-derived field re-evaluation
- §2.6 Singleton Profile — `ERR_PROFILE_ALREADY_EXISTS`, `ERR_PROFILE_NOT_FOUND`, index ordering
- §2.7 Precision and Rounding — round-half-up per line then sum, 2-decimal gallons
- §2.8 OCC on Index Determination — `expected_profile_version`, `ERR_STALE_PROFILE_VERSION` (HTTP 412)
- §2.9 Nested Resource Retrieval — left-to-right path-id validation
- §2.10 Validation Ordering — priority 1 through 8 enumerated in order
- §3.1 Profile bootstrap and aircraft register — index_band thresholds, qualifies_for_index rule, required_index_by_aircraft aggregation with tie-breaks
- §3.2 Vehicle fleet and equipment-supported index — measured-basis formula, VEH_REQ/WATER_REQ constants, 1.2 gal/lb substitution, 50% cap, rated-basis variant
- §3.3 OOS events, recheck, notifications — open/restore lifecycle, notification create rule, `EQUIPMENT`-vs-`STAFFING` cause
- §3.4 Firefighter roster and currency — `month_index` arithmetic, 12-month window, suspend/reactivate cascades, STAFF_REQ table
- §3.5 Effective index and compliance — minimum semantics, COMPLIANT/DOWNGRADED/NONCOMPLIANT derivation, notification create/resolve triggers
- §3.6 Index determinations — OCC, three business rules (qualifying / largest / new index >= required), supersede cascade
- §3.7 Response drills — half-open window, overlap rejection, 180s/240s thresholds inclusive
- §3.8 Incidents and alert escalation — alert-level ordering, response gate by index, controlled_at stamping, open-requests block
- §3.9 Mutual-aid agreements and requests — closed-window semantics, activation/termination, auto-expiry, three referential gates
- §3.10 Incident reports and review loop — 200-char narrative, 10-day window, 137/89 per-unit costs, author-only and not-author rules, RETURNED->DRAFT reset
- §3.11 Post-incident reviews — at-most-one-OPEN, zero-actions close gate
- §3.12 Annual FAA inspection — unique year, three PASS gates
- §4 Endpoint table — 4 columns, 68 endpoints
- §5 Error catalogue — 2 columns, 67 errors

**Contract reports:**
- Contract 1 (Field-Name Coverage): 82 required, 82 present, 0 missing — **PASS**
- Contract 2 (Rule Coverage): 67 errors expressed, 38 state-machine transitions fully expressed with from/to states, 51 enum values present (the one "null" enum member is conveyed in prose as "null until executed/concluded"), 5 roles present with identity prose — **PASS**
- Contract 3 (§3 Path Purity): 639 backticked tokens in §3, 0 path tokens, 0 bare HTTP methods, 0 combined method+path — **PASS**

**Ambiguities resolved:**
1. The `Scheduled_start >= scheduled_end` rejection is mapped to `ERR_DRILL_WINDOW_INVALID` (per the error catalogue's dual meaning: "scheduled_start >= scheduled_end, or execute attempted before scheduled_start").
2. The `null` enum value in `outcome` and `concluded_outcome` fields is conveyed in prose ("null until executed", "null until concluded") rather than as a backticked literal — this matches the scaffold's semantics where the value is genuinely absent until set.
3. `cause` enum tie-breaking (`EQUIPMENT` wins ties when both equipment and staffing are below certificated) is stated explicitly in §3.5.
4. The scaffold's reference to "logical clock advance" as a notification trigger is grounded in §2.5's `to_iso8601` clock-set operation; notification auto-OVERDUE evaluation is stated to occur on clock advance "and on every read" per the scaffold's `downgrade_cure_deadline` algorithm.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1195_airport_rescue_firefighting_readiness/workspace/PRD.md`

## Step 5: Generate Unit Tests — 2026-08-11T19:05:00.000Z

All work is complete. Final summary:

## Summary

**Task 1195 (Airport Rescue & Firefighting Readiness) test infrastructure generated.**

### Tests generated

**Queue A (Difficulty / SCAFFOLD_DIFFICULTY_DESIGN):** 18/18 instances covered, 2 tests each = **36 tests**.

**Queue B (Corner / SCAFFOLD_CORNER_DESIGN):** 46/46 non-stub instances covered, **73 tests** (some instances exercised by multiple assertion-focused tests).

**Corner stubs (NOT translated, per spec):**
- `calc_agent_expense_constants_applied` (owned by `cf_agent_expense_per_line_rounding`)
- `val_priority_pair_respond_state_vs_safety` (owned by `pp_respond_state_beats_index_safety`)
- `x_cascade_oos_full_chain` (owned by `tc_oos_equipment_downgrade_chain`)

**Skipped instances:** 0 — every non-stub instance passed the PRD-first two-condition filter.

### Files written

**test_helpers/** (8 files, `/home/ubuntu/github/CodingPRD/tasks/task_1195_airport_rescue_firefighting_readiness/test_helpers/`):
- `types.py` — 15 TypedDicts + status enums + UserRole
- `api_client.py` — ApiClient subclass with one method per PRD endpoint
- `api_errors.py` — ApiErrorId enum + HTTP status map registered with framework
- `assertions.py` — per-entity `assert_*` validators
- `factories.py` — payload factories (input fields only)
- `constants.py` — index thresholds, STAFF_REQ/VEH_REQ/WATER_REQ, currency months, drill thresholds, cost constants
- `test_users.py` — TEST_USERS dict + per-instance builders (incl. `make_firefighter_headers` for entity-backed role)
- `fixtures.py` — composite helpers: `setup_compliant_index_c_airport`, `create_controlled_incident`, `create_draft_report`/`create_submitted_report`/`create_accepted_report`, `create_active_agreement`, `create_certified_drill`, `open_oos_event`/`restore_oos_event`, etc.
- `__init__.py` — barrel export (framework generics + PRD-specific)

**test_suite/** (12 files, `/home/ubuntu/github/CodingPRD/tasks/task_1195_airport_rescue_firefighting_readiness/test_suite/`):
- `conftest.py`
- `test_01_profile_and_aircraft.py` — profile bootstrap, band edges, required-index filtering, pagination
- `test_02_vehicle_fleet_readiness.py` — latest_readiness recency, system fields, required fields, sub-resource scoping, readiness computed view, immediate consistency
- `test_03_staffing_training.py` — deployable compound, max-anchor semantics, FAIL exclusion, future-date rejection, 12-month boundary, min-semantics
- `test_04_drills.py` — drill initial state, terminal lockdowns, 180/240 boundaries, half-open adjacency, window invalid/expired, existence-beats-state
- `test_05_index_recompute_notifications.py` — OOS equipment chain, training-record staffing chain, readiness cycle, OOS restore invariants, suspend/reactivate invariants, notification lifecycle
- `test_06_incidents_mutual_aid.py` — incident terminal lockdown, mutual-aid request creation gates, decline branch, close blocked, agreement closed-interval overlap, auto-expiry, alert escalation, state-beats-safety priority
- `test_07_reports_reviews.py` — review revision loop, per-line rounding, report window, author-only gates, self-approval forbidden, error battery
- `test_08_inspections.py` — inspection blocked by PENDING/OVERDUE notification, error battery, conclude PASS gates
- `test_09_determinations_occ.py` — determination gates (qualifying/longest/index-below-required), OCC stale rejected, fresh version supersedes
- `test_10_rbac_and_validations.py` — missing auth header, uniqueness, envelope shapes, RBAC denials/reads, suspend/training gates, 5.0-departures boundary
- `test_11_dual_variant_calculations.py` — measured vs rated basis divergence, roster vs deployment-ready divergence, substitution cap binding

### Stage 2 lint verdict

- All 18 difficulty instances have ≥2 tagged tests.
- All 46 non-stub corner instances have ≥1 tagged test.
- 0 bad/dangling Design tags; every tag resolves to a real instance.
- 0 stub translations.
- 0 `pytest.mark.skip` / `skipif` / `xfail` markers.
- Every test docstring carries a verbatim PRD citation; all citations survive literal grep against `workspace/PRD.md`.
- Every docstring ends with exactly one `Design:` line.
- All files compile; all modules import cleanly against the installed `prd_bench_local_runner.testing` framework.

**Lint verdict: PASS.**

## Step 6: Generate Implementation — 2026-08-11T19:05:00.000Z

Implementation complete and verified. Summary:

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_1195_airport_rescue_firefighting_readiness/workspace/implementation/`:

- `start.sh` — guarded launcher (skips `pip install` when Flask already importable, `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — app factory, blueprint registration, auth + time-derived re-evaluation in `before_request`, error handlers producing the standard envelope
- `db.py` — in-memory store (empty at boot, no seeding), logical clock (default `2026-05-01T00:00:00Z`, never wall-clock), ISO-8601 3-fractional-digit timestamps, UUID ids, version/touch helpers
- `errors.py` — all 67 error IDs from the catalog + `ApiError`
- `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), `limit`/`offset`/`total_count`/`has_more` pagination (defaults 10/0, clamped 1..100, `created_at` ascending sort)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gating, typed body-field validators
- `services/calc.py` — index bands, required/supported/effective index derivation (Decimal arithmetic, dry-chem substitution cap 50% of WATER_REQ, descending E→A walk), training currency via `month_index`, drill thresholds, per-line round-half-up agent expense (Decimal ROUND_HALF_UP), notification create/resolve/overdue rules, time-derived re-evaluation
- `routes/` — 11 blueprints: `profile.py` (clock, profile, readiness view with rated/roster audit variants), `aircraft.py`, `fleet.py` (vehicles, readiness checks, OOS open/restore), `roster.py` (firefighters, training records, Firefighter own-id ownership), `drills.py`, `determinations.py` (OCC via `expected_profile_version` → 412), `incidents.py`, `mutual_aid.py`, `notifications.py`, `reports.py` (report review loop + post-incident reviews), `inspections.py`

## Endpoint count
**70 endpoints** registered (matches the scaffold endpoint table exactly).

## State machines implemented
12 machines: ArffVehicle (IN_SERVICE ⇄ OUT_OF_SERVICE), OutOfServiceEvent (OPEN → RESTORED), Firefighter (ACTIVE ⇄ SUSPENDED), ResponseDrill (SCHEDULED → EXECUTED → CERTIFIED/FAILED), IndexDetermination (ACTIVE → SUPERSEDED with exactly-one-ACTIVE invariant), AlertIncident (REPORTED → RESPONDING → CONTROLLED → CLOSED, plus strictly-increasing alert-level self-transitions), MutualAidAgreement (DRAFT → ACTIVE → TERMINATED, system EXPIRED), MutualAidRequest (REQUESTED → DEPLOYED → RELEASED, REQUESTED → DECLINED), IndexDowngradeNotification (PENDING ⇄ OVERDUE → ACKNOWLEDGED/RESOLVED), IncidentReport (DRAFT → SUBMITTED → ACCEPTED / SUBMITTED → RETURNED →(PATCH) DRAFT, with `review_cycle_count`), PostIncidentReview (OPEN → CLOSED gated on zero open actions), FaaInspection (SCHEDULED → IN_PROGRESS → FINDINGS_ISSUED → CLOSED_PASS with 3 compliance gates / CLOSED_FAIL).

## Boot verification
`bash start.sh` boots cleanly in ~2s on a fresh port; verified twice with cold restarts (fresh empty store each time — no carry-over state, no seeding). A 60-assertion end-to-end smoke run passed with zero failures, covering: envelope shape, auth/RBAC, singleton profile, aircraft banding/qualification, equipment/staffing index derivation, OOS → notification create → recheck-gated restore → notification resolve, drill windows (half-open overlap, inclusive 180/240 thresholds), OCC 412, determination supersede + `ERR_INDEX_BELOW_REQUIRED`, report 200-char/10-day gates, author/self-approval 403s, review close gating, closed-window agreement overlap, alert-level coverage, close blocked by open requests, inspection PASS gates, and clock-driven agreement expiry + training-lapse NONCOMPLIANT + STAFFING-cause notification.

## Step 6b: Route-Parity Verification (orchestrator) — 2026-08-11T19:06:00.000Z

Extracted all 70 (method, path) pairs from SCAFFOLD.yaml §1.5 and compared against the live Flask `url_map` from a booted `create_app()`: scaffold=70, impl=70, missing=0, extra=0 — PARITY OK.

## Step 7: Run Tests and Iterate — 2026-08-11T19:20:00.000Z

All 8 parallel rounds pass 109/109. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (initial sweep: 105/109 × 8 rounds, identical 3 failures in every round; post-fix sweep: 109/109 × 8 rounds).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:**
  - `test_02_vehicle_fleet_readiness.py::TestVehicleSystemFieldsIgnored::test_vehicle_system_fields_input_ignored` (line 98): assertion `created_at == "2026-05-01T00:00:00Z"` contradicted PRD §2.4 verbatim ("Both timestamps are ISO 8601 UTC with three fractional digits"). Corrected expected value to `"2026-05-01T00:00:00.000Z"`.
  - `test_05_index_recompute_notifications.py::TestReadinessRecheckRequired::test_restore_without_pass_recheck_rejected`: setup bug — `setup_compliant_index_c_airport()` records PASS readiness checks at the default clock, and the OOS event was opened at the same clock instant, so a qualifying recheck (checked_at at-or-after started_at, PRD §3.3) existed and the PRD-faithful implementation correctly allowed the restore. Added `set_clock("2026-05-02T00:00:00Z")` after setup so the pre-existing checks strictly predate the event's `started_at`, making "no qualifying recheck" actually true.

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/db.py`: added `fmt_clock(dt)` — renders a logical-clock stamp the way the clock itself reads per PRD §2.5 ("the clock reads exactly `2026-05-01T00:00:00Z`"), i.e., no forced fractional digits (fraction only if the clock value carries them). `fmt_ts` retained for `created_at`/`updated_at` per §2.4.
  - Switched all logical-clock-stamped fields from `fmt_ts` to `fmt_clock`: `checked_at` and OOS `started_at`/`restored_at` in `routes/fleet.py`; `reported_at`/`controlled_at` in `routes/incidents.py`; `executed_at` in `routes/drills.py`; `notified_at`/`cure_deadline` in `services/calc.py`. This fixed `test_02 ...::TestImmediateConsistency::test_computed_fields_visible_in_write_response` which asserts `checked_at == "2026-05-01T00:00:00Z"` — the PRD §2.5-faithful reading ("stamped from the logical clock" = the clock's exact reading), while §2.4's three-fractional-digit rule names only `created_at`/`updated_at`.

No PRD-required checks were weakened; internal datetime comparisons (`_checked_dt >= _started_dt` etc.) were untouched, so state-machine and recheck semantics are unchanged.

Orchestrator verification: all 8 `results.{1..8}.json` files exist on disk; every round reports passed=109 total=109 — ALL 8 ROUNDS PASS.

## Step 8: Finalize PRD — 2026-08-11T19:35:00.000Z

Done. PRD_FINALIZED.md is written with a single, surgical edit.

**Line counts / delta:** PRD.md = 365 lines; PRD_FINALIZED.md = 365 lines (0.0% — one line revised in place).

**Changes:**
- §2.5 (The Logical Clock) — revise — added `cure_deadline` to the clock-stamped field list and pinned the serialization of clock-stamped fields: they render the clock's exact reading (no fractional digits on whole-second clock values, e.g. `2026-05-01T00:00:00Z`; three fractional digits only when the clock value carries a fractional second), and clarified that §2.4's three-fractional-digit rule governs `created_at`/`updated_at` only — `implementation/db.py:49-57` (`fmt_clock`), call sites `routes/fleet.py:104,129,160`, `routes/incidents.py:42,94`, `routes/drills.py:97`, `services/calc.py:199-200`; contrast path `db.py:43-46` (`fmt_ts` for `created_at`/`updated_at` via `base_entity`/`touch` at `db.py:92,103`).

**Step-7 items not turned into edits (with reason):**
- `test_02 ... test_vehicle_system_fields_input_ignored` fix — pure test bug; PRD §2.4 already pins three fractional digits for `created_at`/`updated_at` verbatim and impl matches (`db.py:43-46, 92, 103`).
- `test_05 ... test_restore_without_pass_recheck_rejected` setup fix — pure fixture bug; PRD §3.3 already pins the at-or-after recheck rule and impl matches (`routes/fleet.py` `_checked_dt >= _started_dt` comparison).

**Pre-edit search log (the one edit):**
- (a) Subject: serialization format of logical-clock-stamped datetime fields.
- (b) Paths enumerated and read/grepped: `db.py` (`fmt_clock` def L49-57, `fmt_ts` def L43-46, `base_entity` L92, `touch` L103, `DEFAULT_CLOCK` L5); all `fmt_clock` call sites — `routes/fleet.py:104` (`checked_at`), `routes/fleet.py:129` (`started_at`), `routes/fleet.py:160` (`restored_at`), `routes/incidents.py:42` (`reported_at`), `routes/incidents.py:94` (`controlled_at`), `routes/drills.py:97` (`executed_at`), `services/calc.py:199-200` (`notified_at`, `cure_deadline`); the clock endpoint `routes/profile.py:17-29` (`current_utc` echoes the raw supplied string — untouched by the edit since PRD already says "echoes"); envelope timestamp `response.py:18,24,34` (wall clock, three fractional digits — matches §2.2, out of scope); caller-supplied date/datetime fields stored verbatim (`drills.py:46-47` `scheduled_start`/`scheduled_end`, `roster.py:130` `completed_on`, `mutual_aid.py:54-55` `start_date`/`end_date`, `inspections.py:40` `scheduled_on` — not clock-stamped, so explicitly excluded by the edit's "clock-stamped field" scoping); all remaining reads of the stamped fields are `None` initializations or internal `_dt`/`_cure_dt` datetime comparisons, no alternate rendering.
- (c) Wording adjustments: (1) scoped the rule to "clock-stamped fields" and named the full set including `cure_deadline` (which impl stamps via `fmt_clock` at `calc.py:200` but PRD §2.5's list omitted), so caller-supplied raw-string fields are not swept in; (2) stated both directions (no fraction on whole seconds; exactly three digits when the clock carries a fraction) to match `fmt_clock`'s `if dt.microsecond` branch without overclaiming sub-millisecond precision; (3) added an explicit carve-out sentence keeping §2.4's three-fractional-digit rule bound to `created_at`/`updated_at`, so the new sentence cannot be read as relaxing §2.4.

## Step 9: Complete PRD — 2026-08-11T19:55:00.000Z

All pins are in place. Final verification: confirm the file diff counts one more time and that the "ten 24-hour days" claim matches impl (`timedelta(days=10)` on datetime — yes, exact timestamp arithmetic).

Done. Summary:

## Summary

**Source file**: `PRD_FINALIZED.md` (365 lines) → `PRD_COMPLETED.md` (367 lines), char delta **+3627**.

**Counts**: 17 ambiguity-pins, 2 mismatch-revisions (19 total edits).

### Changes

- §2.1 — insert — ambiguity — Firefighter own-id rule scoped to single-record reads and nested per-firefighter sublists; top-level lists remain readable by all roles — `implementation/routes/roster.py:26-30, 56-63`
- §2.2 — insert — ambiguity — Missing/invalid JSON body treated as empty object; fallback errors `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — `implementation/middleware.py:38-40`, `implementation/app.py:38-48`
- §2.3 — revise — ambiguity — `limit`/`offset` must be integers else `ERR_VALIDATION_FAILED` 400; out-of-range values clamped (not rejected); sort ties broken by creation order; filters exact-equality, conjunctive, unknown values yield empty page except aircraft `in_scheduled_service` which validates true/false — `implementation/response.py:43-68`, `implementation/routes/aircraft.py:51-58`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` stamped from the logical clock (never wall clock), always 3 fractional digits; profile version bumps unconditionally (+1) on each listed cascade, only the clock-driven recompute is conditional on change — `implementation/db.py:91-104`, `implementation/services/calc.py:217-251`
- §2.5 — revise — ambiguity — Clock-set accepts any parseable ISO 8601 instant (backward moves allowed); response echoes the supplied `to_iso8601` string verbatim — `implementation/routes/profile.py:17-29`
- §2.6 — insert — ambiguity — Other resources may be created before the profile exists; recompute cascades are no-ops while profile absent — `implementation/services/calc.py:223-225`, all route creators
- §2.8 — insert — ambiguity — `expected_profile_version` pinned as an integer field — `implementation/routes/determinations.py:29-32`
- §3.1 — revise — ambiguity — Non-empty `airport_code`; profile `version` remains 1 after creation; aircraft `model_name` non-empty, `length_ft` > 0, `avg_daily_departures` ≥ 0, `in_scheduled_service` must be boolean when supplied — `implementation/routes/profile.py:32-55`, `implementation/routes/aircraft.py:23-44`
- §3.2 — insert — ambiguity — Vehicle `call_sign` non-empty — `implementation/routes/fleet.py:30`
- §3.2 — insert — ambiguity — Negative measured quantities rejected with `ERR_VALIDATION_FAILED` 400 (distinct from the 422 over-capacity error) — `implementation/routes/fleet.py:89-96`
- §3.2 — insert — ambiguity — Readiness view also echoes the six profile posture fields plus `open_notification_id` (earliest-created open notification or null); `effective_water_gal_at_certificated_index` rounded half-up to 2 decimals — `implementation/routes/profile.py:70-95`
- §3.3 — insert — ambiguity — OOS `reason` is required but may be an empty string — `implementation/routes/fleet.py:121`
- §3.3 — revise — mismatch — Acknowledging an already-`ACKNOWLEDGED` notification is also rejected with `ERR_NOTIFICATION_NOT_ACKNOWLEDGEABLE` (PRD only named `RESOLVED`) — `implementation/routes/notifications.py:42-44`
- §3.4 — insert — ambiguity — `employee_no` and `full_name` non-empty — `implementation/routes/roster.py:37-38`
- §3.7 — revise — mismatch — Drill execution window endpoints are inclusive: only a reading strictly after `scheduled_end` yields `ERR_DRILL_WINDOW_EXPIRED` (PRD's half-open wording implied `scheduled_end` excluded); arrival seconds pinned as non-negative integers — `implementation/routes/drills.py:84-94`
- §3.8 — insert — ambiguity — Respond with no profile treats `effective_index` as `NONE` → `ERR_INDEX_INSUFFICIENT_FOR_ALERT` — `implementation/routes/incidents.py:76-80`
- §3.9 — insert — ambiguity — `partner_airport_code` non-empty; `units_requested` pinned as integer ≥ 1 — `implementation/routes/mutual_aid.py:35`, `implementation/routes/incidents.py:159`
- §3.10 — revise — ambiguity — Report on `REPORTED`/`RESPONDING` incident rejected with `ERR_INCIDENT_NOT_CONTROLLED` 409; each expenditure line's `vehicle_id` must reference an existing vehicle (`ERR_VEHICLE_NOT_FOUND` 404); 10-day window is exact timestamp arithmetic (ten 24-hour days); narrative 200-char minimum enforced only at creation, not on edit — `implementation/routes/reports.py:86-103, 125-150`
- §3.11 — insert — ambiguity — `corrective_actions_open` pinned as non-negative integer — `implementation/routes/reports.py:205-208`
- §3.12 — insert — ambiguity — `inspection_year` pinned as integer; `findings_count` as non-negative integer; PASS conclude with no profile at all rejected with `ERR_PROFILE_NOT_FOUND` 404 at the third gate — `implementation/routes/inspections.py:29-32, 78-81, 117-118`

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1195_airport_rescue_firefighting_readiness/workspace/PRD_COMPLETED.md`

Orchestrator verification: PRD_COMPLETED.md exists (367 lines, 55280 B). All pipeline steps complete.
