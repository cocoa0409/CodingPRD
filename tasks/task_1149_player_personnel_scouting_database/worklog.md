# Worklog — task_1149_player_personnel_scouting_database

## Step 1: Create Task Directory — 2026-08-11T02:37:00.000Z

Pre-assigned output folder `tasks/task_1149_player_personnel_scouting_database` with `workspace/` subdirectory already existed (index pre-assigned by the runner, no auto-index scan performed). Recorded as done per orchestration instructions.

## Step 2: Generate Scaffold — 2026-08-11T03:12:00.000Z

All three scaffold artifacts are generated, lint-clean, and verified.

## Deliverables (in `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/`)

**SCAFFOLD.yaml** — §1.0–§1.7 only:
- **Profile**: access-control-matrix primary + workflow-orchestration secondary; flat topology, cyclic state shape, segregation-of-duties role model; layers = OCC, dual-variant calc, derived-field reconciliation, threshold triggers
- **14 entities** (Scout, Prospect with parallel `evaluation_status`×`flag_status` dimensions, ScoutingReport, VideoTag, ConfidentialFlag, DraftBoard, DraftBoardEntry, RosterNeed, FreeAgentTarget, Budget, InterviewSession, Facility, FacilityBooking, OutcomeRecord), all with canonical `FK -> X.id` prefixes and reverse-reachability GETs
- **8 state machines** incl. the report revision cycle (DRAFT→SUBMITTED→RETURNED→SUBMITTED→LOCKED), board freeze/unfreeze revert, and the HIGH-MEDICAL-escalation exclusion cascade
- **7 calculations** with pinned precision: cross-scout z-score normalization (provisional vs final variants), composite grade with round-per-contribution-then-sum order pinned, inclusive tier thresholds, 4-input fit score with clamps, cap-hit proration with pinned hit→committed→available→posture evaluation order, deterministic board rerank (composite DESC, fit DESC, created_at ASC — never id), dual-variant scout evaluation (RMSE 90.00 vs hit-rate 100.00 on identical data)
- **24 validation rows** across 9 priority bands, **23 error codes**, **55 endpoints** (incl. `/_clock/set_current_utc` with the mandatory `2026-05-01T00:00:00Z` default), 4 roles with `identity:` fields, 2 OCC concurrency rules (board reorder, budget adjustment)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 18 instances, 2 per rule, all with structured `setup_api_calls` chains, placeholder-closed captures, and formula-derived literals executed and verified in code (6.50/7.00 normalization split, 6.94 vs 6.95 rounding-order trap, 35.40 fit score, exact-availability sign boundary, 3→4 board-version cascade bump, 33333333/13333334 cent proration, rank-mass sum == 6 invariant, etc.)

**SCAFFOLD_CORNER_DESIGN.yaml** — 49 active instances across all nine claim-guide sections (defaults, computed-field input rejection, pagination, invalid/terminal transitions, priority ordering auth>existence, RBAC denials both directions of the medical/scouting segregation, MEDICAL detail redaction, OCC stale-version 412s, immediate consistency) plus 6 `excluded_because` stubs citing the covering §1.8 instance.

**Verification**: `scaffold_lint.py` verdict — "clean lint" (55 endpoints, 14 entities, 18 §1.8 + 49 §1.9 instances, 511 calls scanned, zero violations). One rule-replay bug was caught and fixed during authoring (the cascade instance originally created a report after the prospect reached BOARD_READY, which the scaffold's own state validation forbids). All pinned numeric assertions were re-executed in Python against the declared formulas and pass.

## Step 3: Copy Shared Files — 2026-08-11T03:14:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1149_player_personnel_scouting_database/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T03:19:00.000Z

Generated `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/workspace/PRD.md` (the PRD for the player personnel & scouting database task).

**Structure:**
- §1 Introduction (3 paragraphs + clock note)
- §2 Global Specifications (9 subsections: RBAC with identity-backed vs opaque roles, verbatim §2.2 response envelope, pagination, common resource properties with `VideoTag` exception, precision/rounding, OCC on `expected_board_version` and `expected_budget_version`, confidentiality segregation, left-to-right path validation, validation priority ordering 1–9)
- §3 Business Logic (9 subsections: scouts & baseline, prospect pool, report lifecycle + 4-hop lock cascade with normalized/composite/tier math, confidential flags lifecycle, draft board fit scoring + rerank + reorder, exclusion cascade, roster needs / free agency / budget cap-hit waterfall, interviews + facilities + 30-min buffer, post-draft outcomes + dual-variant scout evaluation)
- §4 Endpoint table (4 columns, all 42 endpoints)
- §5 Error catalogue (2 columns, all 23 errors)

**Hard contract results:**
- **Contract 1 (field coverage):** 71/71 required identifiers present (entities fields + endpoint inputs + query params + path params); 0 missing. Three FK names (`board_id`, `facility_id`, `report_id`) initially absent were added in narrative prose.
- **Contract 2 (rule coverage):** All 8 state machines' transitions with preconditions + side effects expressed; all 7 calculations (normalized_grade with provisional/final variants, composite with per-report-then-final rounding order, tier_assignment inclusive lower bounds, fit_score with P1=90/P2=70/P3=50/P4=30 base + 0.8 medical mult + 15.0 char deduction + 20.0 default base, cap hit waterfall with strict-less-than 10% posture, board_rerank composite DESC nulls-last / fit_score DESC / created_at ASC, scout_evaluation dual RMSE and hit-rate with HIT_GRADE_MIN 7.00 / HIT_OUTCOME_MIN 70 / RMSE_PENALTY 10); all 21 validations in priority order; both OCC rules named with endpoint + `expected_*_version` + `ERR_STALE_VERSION` (HTTP 412); all 23 error IDs surfaced in §2/§3 narrative; sibling-branch symmetry across escalate/resolve/pass/release cascade arms preserved.
- **Contract 3 (§3 path purity):** 457 backticked tokens scanned in §3; 0 path leaks, 0 bare HTTP methods, 0 method+path combos.

**Key constraint honored:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, read, grepped, or referenced in any way.

## Step 5: Generate Unit Tests — 2026-08-11T03:58:00.000Z

Note: the first Step 5 subagent turn ended mid-analysis with no files written; it was resumed via SendMessage and carried the generation to completion. Final returned summary verbatim below.

Task was already completed. All checks pass.

## Summary

**Files written to disk** under `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/`:

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — 14 entity TypedDicts + 14 status enums; VideoTag carries only `id` + `created_at` per PRD §2.4
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 endpoints)
- `api_errors.py` — `ApiErrorId` enum + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assert functions + common-fields helper
- `factories.py` — 14 payload factories, input fields only
- `constants.py` — thresholds from PRD §3 (NORMALIZE, TIER, FIT, POSTURE_FRACTION, FACILITY_BUFFER_MINUTES, SCOUT_EVAL, PAGINATION)
- `test_users.py` — shared headers for opaque roles + per-instance `make_area_scout_headers` / `make_scouting_director_headers` builders for entity-backed roles
- `fixtures.py` — composite helpers: `create_scout`/`create_director`, `create_and_lock_report`, `make_board_ready_prospect`, `make_drafted_prospect`, `advance_target_to_offered`, `create_offered_target`, `sign_target`, `schedule_interview`, `create_outcome`, etc. Identity threading via `make_*_headers(entity["id"])`.
- `__init__.py` — barrel export of framework generics + PRD-specific code

**Stage 2 — `test_suite/` (11 files, 87 tests):**
- `conftest.py` + `test_01_normalization_variants.py` (5) + `test_02_composite_and_fit.py` (6) + `test_03_state_machines.py` (14) + `test_04_cascades.py` (4) + `test_05_free_agency_budget.py` (11) + `test_06_calendar_overlap.py` (6) + `test_07_board_reorder.py` (7) + `test_08_validations.py` (10) + `test_09_rbac.py` (7) + `test_10_entities_and_envelope.py` (13)

**Instance coverage:**
- Queue A (Difficulty): **18/18** instances covered, each with ≥2 tests (some 3)
- Queue B (Corner): **42/42** non-stub instances covered with ≥1 test each
- Queue B stubs: **6/6** `excluded_because:` stubs correctly NOT translated; cross-references all resolve
- Orphan/untagged/dual-tagged tests: **0**
- Skipped instances (PRD-first filter): **none** — every instance found verbatim PRD coverage and unique derivability
- `pytest.mark.skip/skipif/xfail`: **0**

**Verification output:**
- `pytest test_suite/ --collect-only -q` → **87 tests collected in 0.16s**, no errors
- `pyflakes test_suite/ test_helpers/` (excluding intentional `__init__.py` barrel re-exports) → **clean**
- Citation audit: all 87 docstrings carry a verbatim PRD quote (validated by sliding-window grep against `PRD.md`) plus exactly one `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` tag that resolves to a real instance in the source yaml.

## Step 6: Generate Implementation — 2026-08-11T03:28:00.000Z

All edge cases behave per spec (exit 144 is just pkill terminating the backgrounded server). One check: the reorder with nonexistent entry returned ERR_NOT_FOUND — per PRD §2.8 existence (priority 4) precedes OCC and state, which is correct since `entry_id` is a body-supplied id that must resolve.

The implementation is complete and smoke-tested.

## Summary

Generated a complete Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/workspace/implementation/`:

**Files:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/workspace/implementation/start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"` so per-test reboots skip reinstall; `exec python3 app.py` in foreground
- `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/workspace/implementation/requirements.txt` — flask
- `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/workspace/implementation/app.py` — full single-file server (~1100 lines)

**Key design points honored from PRD/scaffold:**
- Envelope: `{meta:{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}, response_type, data:{...}}`; errors use `data.error_id`/`data.message` with `response_type:"error"`
- Auth: `X-User-ID`/`X-User-Role`; AreaScout/ScoutingDirector are entity-backed (Scout.level must be AREA/DIRECTOR), MedicalStaff/GeneralManager opaque; ownership checks `ERR_REPORT_NOT_OWNED`, flag clearance `ERR_FLAG_ACCESS_DENIED`
- Logical clock at `/_clock/set_current_utc`, default exactly `2026-05-01T00:00:00Z`, never wall-clock; timestamps rendered with 3 fractional digits
- All 40+ endpoints implemented with role gates per the RBAC matrix; in-memory store starts empty every boot
- Calculations with `Decimal` + `ROUND_HALF_UP`: normalized_grade (provisional vs final variant selected by presence of `locked_grade_mean`, snapshot at lock, round-then-clamp), composite with **per-report rounding before final sum**, tier inclusive-lower bounds (7.00→T2), fit_score (base 90/70/50/30 or 20 default, scheme multiplier from best LOCKED report, 0.8 resolved-HIGH-MEDICAL multiplier, −15 open/acknowledged CHARACTER deduction, clamp [0,100]), cap hit with half-up bonus proration in integer cents, posture TIGHT iff available strictly < 10% (exactly 10% = HEALTHY), scout evaluation (RMSE accuracy floored at 0; hit-rate on ≥7.00 predictions vs ≥70 percentile, null when no predictions; both null when eligible set empty)
- Cascades: lock (normalized → prospect composite/tier → fit_score recompute on OPEN boards only → rerank + board version bump); HIGH-MEDICAL escalation (EXCLUDED; deactivate entries on OPEN **and** FROZEN boards; rerank + version bump); scout weight change (recompute affected composites + rerank affected OPEN boards; scout version bump); sign/release (budget recompute + version bump)
- OCC: `expected_board_version` on reorder and `expected_budget_version` on adjustments → `ERR_STALE_VERSION` 412; reorder uses insert semantics with contiguous rank reassignment
- Validation ordering per PRD §2.9 (auth → authorization → schema → existence → state → safety → business → temporal → fiscal); temporal rules: interview half-open overlap (adjacency allowed), facility 30-minute buffer (exactly 30 min allowed)
- VideoTag has only `id`/`created_at` (no version/updated_at); MEDICAL flag `detail` redacted to null for non-MedicalStaff readers

Smoke-verified: auth rejection, clock default, scout/prospect/report/lock flow with correct normalized (8.75) and composite/tier (T1), fit_score 24.0, flag redaction per role, HIGH-MEDICAL escalation cascade (entry deactivated, board version bumped), cap-hit proration (10001/3 → 3334), sign gate, committed/available/posture recompute, stale-version 412, board-empty finalize 409, interview half-open adjacency vs overlap, facility 30-minute buffer boundary.

Orchestrator pre-sweep verification: implementation registers exactly the 55 (method, path) route pairs declared in SCAFFOLD.yaml `endpoints:` (normalized placeholder comparison — 0 missing, 0 extra); `app.py` parses clean.

## Step 7: Run Tests and Iterate — 2026-08-11T04:00:00.000Z

## Summary

**Iterations run:** 2 (initial sweep: 85/87 in all 8 rounds, same 2 failures everywhere — deterministic, not flaky; post-fix sweep: 87/87 × 8 rounds)

**Tests deleted:** none — both failing tests traced to verbatim PRD prose with unique derivability.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/test_suite/test_05_free_agency_budget.py` — `TestBudgetPostureBoundary` (both tests). The fixture math contradicted PRD §3.7 ("`TIGHT` whenever available is strictly less than one-tenth of the sum of base cap and rollover ... `HEALTHY` otherwise"). The tests treated 20% as the threshold: `test_available_exactly_ten_percent_is_healthy` signed 80000000 leaving available 20000000 while claiming "exactly 10%" (assertion passed only coincidentally, never exercising the equality boundary), and `test_one_cent_below_ten_percent_is_tight` asserted available 19999999 → TIGHT, which a PRD-faithful implementation correctly reports as HEALTHY. Fixed fixtures: first test now signs 90000000 → available 10000000 (genuine exactly-10% boundary → HEALTHY); second signs 90000000 + 1 → available 9999999 (one cent below 10% → TIGHT). Docstring arithmetic corrected to match.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/workspace/implementation/app.py` — `reorder_board_entries()`: removed the schema-level `minimum=1` on `new_rank` (which produced `ERR_VALIDATION`/400) and moved the lower bound into the business-constraint check `if new_rank < 1 or new_rank > active_entry_count` raising `ERR_RANK_OUT_OF_BOUNDS`/422. PRD §3.5 binds the entire "between 1 and the board's `active_entry_count` inclusive" range to `ERR_RANK_OUT_OF_BOUNDS`, and §2.9 level 3's "integers non-negative where declared" would not reject 0 anyway; §2.9 level 7 explicitly lists reorder bounds under `ERR_RANK_OUT_OF_BOUNDS`.

**Verification:** 8-round parallel sweep after fixes → all rounds 87/87 passed.

Orchestrator disk verification after subagent exit: all 8 `results.{1..8}.json` present, each `passed: 87, total: 87, failed: 0`.

## Step 8: Finalize PRD — 2026-08-11T04:01:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/workspace/PRD_FINALIZED.md` exists and is a verbatim copy of PRD.md — **zero content edits** was the correct minimal patch, because neither Step-7 item revealed a PRD silence or a PRD mismatch with the *current* implementation.

## Line counts / delta

- `PRD.md`: 332 lines; `PRD_FINALIZED.md`: 332 lines; delta 0 lines, 0.0%.

## Changes

None. Both `<step_7_diff>` items resolved to PRD prose that already uniquely determines current impl behavior:

- **§3.7 (budget posture boundary)** — no change — the Step-7 item was a pure test-fixture bug (tests used a 20% threshold); PRD §3.7 already says "`TIGHT` whenever available is strictly less than one-tenth of the sum of base cap and rollover ... `HEALTHY` otherwise — available equal to exactly one-tenth of that sum is `HEALTHY`", which is exactly what the impl computes — `implementation/app.py:514-515` (`threshold = (base+rollover) * POSTURE_FRACTION`; `TIGHT if available < threshold else HEALTHY`, `POSTURE_FRACTION = Decimal("0.10")` at app.py:387).
- **§3.5 / §2.9 (reorder `new_rank` bounds)** — no change — the Step-7 item was an *implementation* bug (schema-level `minimum=1` → `ERR_VALIDATION`/400) that Step 7 fixed to conform to already-unambiguous PRD prose: §3.5 binds the entire "between 1 and the board's `active_entry_count` inclusive" range to `ERR_RANK_OUT_OF_BOUNDS`, and §2.9 level 7 lists reorder bounds under `ERR_RANK_OUT_OF_BOUNDS`. Current impl matches: `as_int(new_rank, "new_rank")` with **no** minimum (app.py:1549), then `if new_rank < 1 or new_rank > b["active_entry_count"]` → `ERR_RANK_OUT_OF_BOUNDS`/422 (app.py:1564-1565). Editing the PRD to describe the old behavior would have created a *new* mismatch with the fixed impl.

## Per-edit pre-edit search log (no edits committed; analysis per considered Step-7 item)

**Item 1 — budget posture (test fixture fix)**
- (a) Subject: `posture` threshold semantics (TIGHT/HEALTHY boundary at one-tenth of base+rollover).
- (b) Paths enumerated: `recompute_budget()` app.py:506-515 (sole computation); all four callsites — create_budget app.py:1876, sign app.py:1816, release app.py:1835, adjustment app.py:1912; serializer `budget_out` app.py:735-737; constant app.py:387. All share the single Decimal-exact `<`-comparison.
- (c) No wording adjustment made — PRD §3.7 prose ("strictly less than one-tenth ... exactly one-tenth ... is `HEALTHY`") is verbatim-consistent with every enumerated path, including the fresh-budget case ("typically HEALTHY": base=rollover=0 → 0 < 0 false → HEALTHY). Item was a fixture bug, not PRD silence.

**Item 2 — reorder `new_rank` lower bound (impl fix)**
- (a) Subject: error code/status for out-of-range `new_rank` (schema `ERR_VALIDATION`/400 vs business `ERR_RANK_OUT_OF_BOUNDS`/422).
- (b) Paths enumerated: `reorder_board_entries` app.py:1539-1578 (the *only* consumer of `new_rank` — grep for `new_rank|ERR_RANK_OUT_OF_BOUNDS` returns only lines 1545-1572); `as_int` helper app.py:287-292 and every `minimum=` callsite (app.py:1282-1283, 1550, 1709-1711, 1865-1866, 1899, 2006, 2087-2089) to confirm which fields carry PRD-"declared" non-negativity/positivity (`start_sec`, money cents, `contract_years`≥1, `capacity`≥1, `games_started`, `outcome_percentile`, OCC version fields) — `new_rank` is not among them; also confirmed no other endpoint performs rank-bound checks (rerank is cascade-only, takes no client rank).
- (c) No wording adjustment made — PRD §3.5 ("`new_rank` must lie between 1 and the board's `active_entry_count` inclusive ... violations are rejected with `ERR_RANK_OUT_OF_BOUNDS`") plus §2.9 level 7 ("reorder bounds" under `ERR_RANK_OUT_OF_BOUNDS`) plus §2.9 level 3 ("integers non-negative **where declared**" — `new_rank` has no such declaration anywhere in the PRD) uniquely derive the current impl behavior for every enumerated case: missing/non-integer → `ERR_VALIDATION`; 0, negative, or > `active_entry_count` → `ERR_RANK_OUT_OF_BOUNDS`/422. Step 7 itself classified this as "unique derivability" (no tests deleted; impl fixed, not tests).

## Step 9: Complete PRD — 2026-08-11T04:12:00.000Z

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1149_player_personnel_scouting_database/workspace/PRD_COMPLETED.md`

**Line counts / char delta:** PRD_FINALIZED.md 332 lines / 46,510 chars → PRD_COMPLETED.md 334 lines / 51,157 chars (+2 lines, +4,647 chars; 60 diff lines).

**Counts:** 14 ambiguity-pins, 1 mismatch-revision (duplicate board entry; plus one validation-order correction folded into the §2.9 ambiguity insert — flag-creation schema runs before flag-type clearance).

**Changes (one bullet each):**

- §1 — insert — ambiguity — logical clock drives all server-emitted timestamps (`created_at`, `updated_at`, `api_request_timestamp`); clock endpoint accepts ISO 8601 with `Z` or numeric offset (normalized to UTC); unparseable `to_iso8601` → `ERR_VALIDATION` — implementation/app.py:31-48, 831-844.
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit`/`offset` → `ERR_VALIDATION` — app.py:315-337.
- §2.3 — insert — ambiguity — `total_count` is post-filter pre-pagination count; `has_more` ⇔ offset + page size < total_count; filters are exact-equality, unmatched filters yield empty pages; non-integer `season_year` filter → `ERR_VALIDATION` — app.py:162-166, 340-343, 1657-1662, 1741-1746.
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — app.py:350-356.
- §2.5 — revise — ambiguity — >2-decimal rejection is `ERR_GRADE_OUT_OF_RANGE` on report grades but `ERR_VALIDATION` on scout statistics; `weight` is not grade-scale, any positive number accepted and stored rounded half-up to 2 decimals — app.py:864-865, 875-876, 891, 1117-1121.
- §2.6 — insert — ambiguity — OCC version fields must be non-negative integers; missing/non-integer/negative → `ERR_VALIDATION` — app.py:1546-1550, 1896-1899.
- §2.9 — insert — ambiguity + order-pin — resource-dependent authorization checks presuppose existence (404 first); on flag creation, payload schema checks (priority 3) run before flag-type clearance, so a malformed flag payload yields `ERR_VALIDATION` not `ERR_FLAG_ACCESS_DENIED`; OCC check runs after existence and before state guards — app.py:1275-1279, 1326-1343, 1395-1398, 1551-1565, 1900-1910.
- §3.1 — insert — ambiguity — scout stats bounds/decimals violations → `ERR_VALIDATION`; name/level/statistics immutable after registration (no update endpoint; only `weight` mutable) — app.py:852-898 (only mutation endpoint is `/weight`).
- §3.1 — insert — ambiguity — weight change: non-numeric or non-positive `new_weight` → `ERR_WEIGHT_INVALID`; accepted value stored rounded half-up to 2 decimals — app.py:966-974.
- §3.2 — revise — ambiguity — `position` stored verbatim with no case/format validation — app.py:1008-1010.
- §3.2 — insert — ambiguity — mark-drafted from non-`BOARD_READY` → `ERR_INVALID_STATE`; advance `to_state` outside {EVALUATED, BOARD_READY, ARCHIVED} → `ERR_VALIDATION` — app.py:1062-1064, 1091-1092.
- §3.2 — insert — ambiguity — flag created against a prospect already `UNDER_REVIEW` or `EXCLUDED` leaves `flag_status` unchanged — app.py:1354-1357.
- §3.3 — revise — ambiguity — >2-decimal `raw_grade`/`scheme_fit` → `ERR_GRADE_OUT_OF_RANGE` (not generic validation) — app.py:1117-1121.
- §3.3 — insert — ambiguity — lock rejected with `ERR_INVALID_STATE` when the applicable mean/stdev pair is not established — app.py:1251-1261.
- §3.4 — insert — ambiguity — flag creation moves `flag_status` to `UNDER_REVIEW` only from `CLEAR`/`CLEARED`; `EXCLUDED` is kept — app.py:1355-1357.
- §3.4 — insert — ambiguity — `resolution_note` defaults to empty string (also its pre-resolution value) — app.py:1351, 1414-1419.
- §3.5 — revise — mismatch — no per-prospect uniqueness on board entries: adding the same prospect twice creates a second active entry (dropped the "one per prospect" claim) — app.py:1505-1536 (no duplicate check).
- §3.5 — insert — ambiguity — board `season_year` is an integer; multiple boards may coexist per season — app.py:1462.
- §3.5 — insert — ambiguity — scheme multiplier is 0.0 when the prospect has no locked report (fit clamps to 0.0) — app.py:463-464, 478-483.
- §3.5 — insert — ambiguity — successful manual reorder returns the updated board object — app.py:1577-1578.
- §3.7 — insert — ambiguity — integer `season_year` on needs/targets/budgets; non-negative integer cents for `base_cap_cents`/`rollover_cents`/`base_salary_cents`/`signing_bonus_cents`; `contract_years` integer ≥ 1 — app.py:1635, 1708-1711, 1864-1866.
- §3.7 — insert — ambiguity — target advance `to_state` outside {EVALUATING, APPROVED, OFFERED} (including SIGNED/PASSED/RELEASED) → `ERR_VALIDATION` — app.py:1770-1772.
- §3.7 — insert — ambiguity — rollover delta is a signed integer; adjustment driving `rollover_cents` below zero is also rejected with `ERR_BUDGET_EXCEEDED` — app.py:1898, 1905-1907.
- §3.8 — insert — ambiguity — interview/booking timestamps stored and returned normalized to UTC with three fractional digits; `EXCLUDED` does not block interview scheduling and scheduling is not gated on `evaluation_status` — app.py:1942, 1955-1956, 2054-2055.
- §3.9 — insert — ambiguity — `outcome_percentile` and `season_year` are integers; multiple outcome records per prospect (even per season) permitted; season_year ties in the evaluation read break to earliest-created — app.py:2086-2091, 2097-2105, 925.
- §3.9 — insert — ambiguity — response field names `rmse_accuracy` / `hit_rate_accuracy`; hit-rate is `null` when the eligible set is non-empty but has no predictions — app.py:944-956.
- §4 endpoint table — revise — ambiguity — board-entries list orders active entries by rank ascending then inactive by `created_at` ascending; `active` filter accepts true/1/false/0 case-insensitive, else `ERR_VALIDATION` — app.py:1491-1501.

Orchestrator disk verification: PRD_COMPLETED.md present (334 lines). Note: Steps 8/9 edit documentation only — no code or test artifacts changed after the final all-green 8-round sweep.
