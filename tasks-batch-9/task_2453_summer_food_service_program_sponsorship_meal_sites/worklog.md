# Worklog — task_2453_summer_food_service_program_sponsorship_meal_sites

## Step 1: Create task directory — 2026-09-02T19:58:57.250Z

Created pre-assigned directories (index fixed by scenario number 2453; no auto-allocation performed):
- `/home/ubuntu/github/CodingPRD/tasks/task_2453_summer_food_service_program_sponsorship_meal_sites`
- `/home/ubuntu/github/CodingPRD/tasks/task_2453_summer_food_service_program_sponsorship_meal_sites/workspace`

## Step 2: Generate Scaffold — 2026-09-02T21:31:32.525Z

Done — all three artifacts are in place and the lint is clean.

**Verdict block (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2453_summer_food_service_program_sponsorship_meal_sites/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2453_summer_food_service_program_sponsorship_meal_sites/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2453_summer_food_service_program_sponsorship_meal_sites/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  1329

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all absolute, in `/home/ubuntu/github/CodingPRD/tasks/task_2453_summer_food_service_program_sponsorship_meal_sites/`): `SCAFFOLD.yaml` (169 KB), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (131 KB), `SCAFFOLD_CORNER_DESIGN.yaml` (310 KB). Top-level keys verified: SCAFFOLD.yaml = `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no `scaffold_*_design` keys); the two design files each carry exactly one top-level key.

**SCAFFOLD.yaml counts** — `api_prefix: /sfsp`; 12 entities (3 immutable append-only: AreaEligibilityRecord, MealCountEntry, HoldingLogEntry); 8 state machines (2 cyclic loops, Site with parallel approval_status × operating_status); 2 §1.2.1 OCC rules, both on `Sponsor.version` (`POST /sfsp/advance-payments`, `POST /sfsp/meal-claims` → 412 `ERR_STALE_SPONSOR_VERSION`); 10 calculations (3 dual-variant); 65 validations at priorities 1–65; 60 endpoints plus the clock endpoint; 65 error codes; 4 roles (StateAgencyReviewer, SponsorAdmin, SiteSupervisor, FieldMonitor) under `role_model: segregation_of_duties`; `difficulty_level: expert_plus`, `consistency_model: immediate`.

**§1.8** — 9 rules / 18 instances (2 per rule), covering dual-variant claim reimbursement, forecast peak-vs-decay, per-line-item rounding then summing, admin-cap ordering, parallel site dimensions, the edit-check failure cycle, the critical-finding cascade, priority-conflict ordering, boundary thresholds (62.50 % area eligibility, 240/241 holding minutes), interval semantics, and advance-recovery ledger conservation.

**§1.9** — all 9 claim-extraction-guide sections, 77 instances = **61 full `test_recipe`s + 16 `excluded_because` stubs**: entities 11, state_machines 12 (3 stubs), calculations 10 (5), validations 14 (2), endpoints 9 (1), errors 7, rbac 5, cross_cutting_complexity_layers 8 (5), consistency_model 1. Work completed this session: the last three rbac instances (segregation-of-duties review denial → 403 `ERR_SEGREGATION_OF_DUTIES` with mon_2 succeeding; unauthenticated 401 sweep proving priority 1 precedes 2 and 4; positive four-role exclusive-operations chain), the cross-cutting section (two real OCC stale-version tests — one per §1.2.1 rule — plus a `version` increments-once-per-mutation walk 1→5 and five layer stubs), the consistency_model `immediate` instance, and two added endpoint instances (a 14-GET read-breadth sweep and the sponsor-initiated day `void`).

**Coverage audit** (scripted over both design files):
- Endpoints: **60/60** exercised by a structured `call:` (the read sweep and the void instance closed the last 15, all GET-only plus `POST /sfsp/meal-service-days/{day_id}/void`).
- Errors: **65/65** declared codes triggered; no undeclared code referenced. (`ERR_XXX` exists only in the §1.0 envelope example and is not a real code.)
- Validations: **65/65** priorities cited in `grounds:` (priority 8 `ERR_SITE_NOT_FOUND` was the last gap; added to `line_item_link_requires_an_existing_site`).
- Calculations 10/10 and state machines 8/8 referenced; instance names **93 unique across §1.8 ∪ §1.9**, zero collisions; placeholder closure checked programmatically — **0 open `${var}`** in any payload, path or assert; both OCC `expected_sponsor_version` values are `${...}` captures.
- Fixes made while landing these: `counted_at` is not an input of `.../meal-counts`; `MealServiceDay` exposes scalar `reimbursable_meals`/`leftover_meals` (no `reimbursable_*_by_type`); `finalized_day_count` lives on `ClaimLineItem`, not `Site`; the day-state error is `ERR_SERVICE_DAY_STATE_INVALID`; two placeholder/capture mismatches in the read sweep and consistency instances.
- One stale comment corrected in `SCAFFOLD.yaml` (`complexity_profile`, line 57): it claimed "51 endpoints, 41 error codes, 9 calculations" and now reads "60 endpoints, 65 error codes, 10 calculations (3 with variants)".

The hard constraint was honoured: no sibling `tasks/task_*/` directory was listed, globbed, grepped or read at any point.

## Step 3: Copy Shared Files — 2026-09-02T21:31:57.688Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T21:50:33.241Z

PRD generation is complete.

**Output:** `workspace/PRD.md`
- **458 lines, 100,063 bytes**
- Generated from `SCAFFOLD.yaml` only. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Top-level sections in order**
1. `# SFSP Sponsorship & Meal Sites API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 Program Actors and Access Control; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination and List Ordering; 2.4 The Logical Program Clock; 2.5 Record Identity, Timestamps and Row Versioning; 2.6 Path Resolution and the Order of Rejection; 2.7 Cascade Discipline and Compensating Reversals; 2.8 Stale-Version Protection on the Sponsor Ledger; 2.9 Money, Meal Counts and Rounding Discipline; 2.10 Segregation of Duties in Compliance Review
4. `## 3. Business Logic & Workflows` — 3.1 Bringing a Sponsor Into the Program; 3.2 The Program-Year Budget; 3.3 Advance Payments and Their Recovery Standing; 3.4 Area Income Data and Site Eligibility; 3.5 A Site's Two Independent Status Axes; 3.6 The Day of Service; 3.7 Monitoring Visits, Findings and Corrective Actions; 3.8 The Monthly Claim; 3.9 Outreach Planning and the Attendance Forecast
5. `## 4. API Endpoints` (60-row table)
6. `## 5. Error Codes` (65-row table, in §2.6 precedence order)

**Tail is complete** — ends on the final `| ERR_ADMIN_COST_EXCEEDS_BUDGET | 422 |` row of the §5 table, a real section boundary. Orchestrator independently verified: 458 lines, all 5 top-level sections present, no mid-sentence truncation. No regeneration needed.

```
Field coverage check:
- entities[].fields: 159 required, 159 present, 0 missing
- endpoints[].request_body: 80 required (59 distinct), 80 present, 0 missing
- endpoints[].query_params: 61 required (29 distinct), 61 present, 0 missing
- computed-read output fields: 20 required, 20 present, 0 missing
- common_fields (id, created_at, updated_at, version): 4 required, 4 present, 0 missing
- enum literal values in field constraints: 83 required, 83 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 65 checked, 65 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 59 checked (8 machines), 59 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 65 checked, 65 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 35 checked, 35 expressed, 0 missing
- entities[].fields[] structured content: 159 checked, 159 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1113
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scaffold contradictions resolved during generation** (all decided in favour of the more specific/normative source, and stated unambiguously in the prose so the implementer has one reading): advance offset and net payable are written at payment, not at edit-check; `deadline_date` is the last day of the *second* month after `claim_month`; a deficiency report opens *exactly one* corrective action (not one per finding); compliance flags increment only for `EXCEEDS_PRODUCTION`/`MISSING_MONITORING`; the first food-safety breach uses the §1.3 `discarded_meals` formula; `first_operating_date` is set when a day opens; reopening a `PAID` claim nulls (not zeroes) the payment fields; a `REINSTATED`-equivalent `APPROVED` decision against a suspended site is the reinstatement path. An explicit paragraph was added in §3.8 specifying the four forward `AdvancePayment` recovery transitions, which §3.3 and §3.8 had otherwise cross-referenced to each other.

## Step 5: Generate Unit Tests — 2026-09-02T22:29:47.181Z

The PRD-compliance suite for task 2453 is complete.

## Files created

`test_helpers/` (Stage 1, 9 files): `__init__.py`, `types.py`, `api_client.py` (one method per PRD endpoint, `/sfsp` prefix), `api_errors.py` (all 65 PRD error IDs + the §5 status map registered with the framework), `assertions.py`, `constants.py`, `factories.py`, `test_users.py`, `fixtures.py` (scenario builders).

`test_suite/` (Stage 2): `conftest.py` + 14 test files, **168 collected tests**:

| file | tests | file | tests |
|---|---|---|---|
| test_01_claim_reimbursement_math | 9 | test_08_state_transitions | 11 |
| test_02_forecast_and_boundaries | 8 (10 w/ params) | test_09_program_calculations | 9 |
| test_03_lifecycle_paths | 11 | test_10_validation_rules | 12 |
| test_04_cascades_and_precedence | 8 | test_11_endpoint_behaviour | 20 |
| test_05_cross_entity_gating | 10 | test_12_error_catalog | 25 |
| test_06_conservation_invariants | 7 | test_13_access_control | 15 |
| test_07_entity_contracts | 16 | test_14_concurrency_and_consistency | 5 |

## Coverage audit (scripted, all green)

- Queue A: **18/18** difficulty instances translated, every one with >=2 tests.
- Queue B: **60/61** non-stub corner instances translated (>=1 test each).
- 78 distinct `Design:` tags, 166 tagged tests; **zero** unknown/non-resolving tags, **zero** tags pointing at an `excluded_because:` stub (16 corner stubs correctly untranslated).
- All 192 docstring quotes verified verbatim against `workspace/PRD.md`; every docstring ends in exactly one `Design:` line. No `skip`/`xfail` anywhere. `py_compile` clean, all 14 modules import, pytest collects 168.

## The one skipped instance

`Corner/entities/claim_line_item_requires_matching_sponsor_site_hybrid_topology` — `ERR_SITE_SPONSOR_MISMATCH` appears in the PRD only in the §2.6 priority list (item 11) and the §5 status table; no prose states its trigger, and the plausible trigger collides with the earlier §2.2 ownership check (`ERR_NOT_RESOURCE_OWNER`, priority 5). Both filter conditions fail (unstated referential rule + error precedence), so it was dropped rather than weakened. A related sub-case in `Corner/rbac/sponsor_admin_cannot_act_on_another_sponsors_resources` was substituted for the same reason (replaced with the PRD-stated transitive ownership case).

## Two Stage-1 fixes applied after subagent reports

- `fixtures.decide_sponsor_application` / `decide_site_approval` were sending the reason as `decision_reason`; the PRD's request field is `reason` (§3.1/§3.5). Fixed — every reason-bearing decision through those helpers would otherwise have 422'd.
- `assert_meal_claim` demanded an integer `meals_rate_value_cents` unconditionally; now tolerates null, since the PRD never fixes a fresh DRAFT claim's value.

## PRD gaps / design-recipe conflicts worth relaying

- **Design recipes contradicted by the PRD (PRD won in every case):** `deadline_date` for a June claim is 2026-08-31 (second month, not first); open-revision sets the claim's payment fields to **null**, not 0; season-close `void_reason` is `SEASON_CLOSED`; visit-opened action `origin` is `VISIT_FINDING`; visit-cancel field is `reason`; `first_operating_date` is not stamped by an operating-axis move; `ERR_MEAL_SERVICE_WINDOW_CONFLICT` / `ERR_MONITOR_SCHEDULE_CONFLICT` / `ERR_MONITOR_DAILY_CAP_EXCEEDED` / `ERR_ELIGIBILITY_NOT_DETERMINED` / `ERR_DAY_HAS_OPEN_SERVICE` are 409, not 422.
- **Genuine PRD silences** (assertions dropped rather than guessed): initial values of a DRAFT claim's money fields and `claimed_*_cost_cents` (0 vs null); pre-payment `advance_offset_cents` / `net_payable_cents` on the reimbursement summary; the `variant` enum literal; whether `*_by_type` maps include zero-valued keys; whether a REVERSAL row stores its raw counts signed (so `non_reimbursable_meals` on a reversal is undetermined); `finding_code` has no enum; `Sponsor.site_count`, `MealClaim.line_item_count` and `MonitoringVisit.finding_count` do not exist in the PRD at all (list `total_count` used instead); boolean query-param encoding is unspecified.
- Timestamps are asserted at date/second precision where §2.5's three-fractional-digit rule only covers `created_at`/`updated_at`.

## Step 6: Generate Implementation — 2026-09-02T22:29:47.181Z

Implementation is complete and verified. Server was booted via `bash start.sh` on `PORT=18453`, both smoke suites passed, and the process has been killed (port 18453 is free).

## Files created

All under `workspace/implementation/` (4,116 lines total, 23 files):

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 76 |
| `db.py` | 214 |
| `errors.py` | 104 |
| `middleware.py` | 303 |
| `response.py` | 63 |
| `routes/__init__.py` | 0 |
| `routes/common.py` | 20 |
| `routes/sponsors.py` | 140 |
| `routes/budgets.py` | 186 |
| `routes/advances.py` | 179 |
| `routes/sites.py` | 298 |
| `routes/days.py` | 458 |
| `routes/visits.py` | 199 |
| `routes/corrective_actions.py` | 151 |
| `routes/claims.py` | 599 |
| `routes/clock.py` | 18 |
| `services/__init__.py` | 0 |
| `services/calculations.py` | 424 |
| `services/cascades.py` | 221 |
| `services/lookup.py` | 141 |
| `services/serializers.py` | 311 |

## Endpoints

**60 endpoints implemented — exactly matching the 60 declared in SCAFFOLD.yaml** (verified by counting `app.url_map` rules against `grep -c "^  - method:" SCAFFOLD.yaml`). 12 entities, 65 error codes, `api_prefix` `/sfsp`.

## Architecture / constraints honoured

- Storage is in-memory only: `db.Store` holds 12 plain dicts keyed by id plus a `next_seq` counter. No SQLite, no file writes, no `/tmp` cache.
- Zero seeding: every boot starts with empty collections and the logical clock at `2026-08-01T00:00:00Z`. All state is created through the declared endpoints.
- `start.sh` reads `$PORT` (default 8000), binds `0.0.0.0`, `threaded=False`, `use_reloader=False`, and `exec`s Flask in the foreground — safe for `--isolation per-test-server`.
- Nothing under `test_helpers/`, `test_suite/`, sibling `task_*/`, or the two design YAMLs was read.

## Verification

Two smoke suites (written outside the repo at `/tmp/sfsp_smoke.py`, `/tmp/sfsp_smoke2.py`) both pass from a fresh boot. Between them they exercise: envelope/meta shape, 401/403 ordering, `admin_cost_ratio` 0.1667, OCC 412 on both guarded endpoints, append-only rows omitting `version`, day classification (reimbursable 165, adult meals excluded, leftovers), holding minutes 270 with no breach on a non-open-air site, first-week due date, one action per report with alphabetical tie-break, segregation-of-duties 403, visit bubbling to CLOSED, per-type ROUND_HALF_UP (18813 + 44698 = 63511), admin cap 12000 -> final 72000, advance waterfall to PARTIALLY_RECOVERED, exact payment reversal on open-revision, suspension cascade + `ERR_CLAIM_HOLD_BLOCKING`, reinstatement that never un-voids days, CAMP allowance, food-safety breach, count reversals, attendance forecast, both edit-check failure codes, the compliance-flag threshold firing a `SYSTEM`-opened MAJOR action, escalation, the rejection ladder to CRITICAL -> suspension -> automatic reinstatement, demand timing, and the sponsor-termination cascade.

**One defect found and fixed this session:** `routes/corrective_actions.py` validated the `origin` query filter against `("VISIT_FINDING", "CLAIM_COMPLIANCE")`, but the PRD §3.8 and SCAFFOLD enum both say `COMPLIANCE_FLAG` (which is what `claims.py` actually writes). Filtering by the real value returned `400 ERR_INVALID_REQUEST`. Corrected to `("VISIT_FINDING", "COMPLIANCE_FLAG")`.

## PRD ambiguities resolved

1. **Actions per report** — one CorrectiveAction per report (not per finding, despite SCAFFOLD line 2878 saying "one per finding"); severity = highest present, `finding_code` = alphabetically first among the highest. PRD prose wins.
2. **Site approval-decision** — accepts both `REINSTATED` and `APPROVED` as the un-suspend decision.
3. **"Cleared for review"** — fails only on `PENDING_REVIEW`/`DENIED`; a SUSPENDED site reports `ERR_SITE_SUSPENDED`, not `ERR_SITE_NOT_APPROVED`.
4. **Edit-check writes** — only `final_reimbursement_cents`; `advance_offset_cents`/`net_payable_cents` are computed at pay time.
5. **Open-revision from PAID** — nulls `advance_offset_cents`, `net_payable_cents`, `paid_at` and `final_reimbursement_cents`.
6. **`first_operating_date`** — written only when a day reaches OPEN (as `min` of existing and the service date), never by `operating-status`.
7. **Escalation** — always raises `claim_hold`; suspends only when the site is APPROVED, with reason `CORRECTIVE_ACTION_ESCALATED`.
8. **Count reversals** — invalid unless `first/second/adult` exactly equal the target entry's, target is ORIGINAL, same day, same meal type, and not already reversed.
9. **Sponsor termination** — also raises `claim_hold` on already-denied sites.
10. **Void scope** — suspension voids PLANNED days dated >= clock plus all OPEN days; DENIED/termination void all PLANNED/OPEN; season close voids only PLANNED days dated >= clock.
11. **Budget timestamps** — `submitted_at`/`decided_at` are stored and serialized even though absent from the entity table.
12. **Day list filters** — `site_id`/`service_date`/`status` per PRD, plus a tolerated `food_safety_status`.
13. **Missing conditionally-required fields** — `ERR_INVALID_REQUEST` at gauntlet step 3; the 422 fiscal errors are reserved for genuine "exceeds" cases.
14. **`production_counts` key-set mismatch** — checked immediately after day existence (before ownership/state), since it is a body-shape error.
15. **Classification order** — iterates declared `meal_services` order first, then any extra counted types sorted alphabetically.
16. **`api_request_timestamp`** — sourced from the logical clock, so it moves with `_clock/set_current_utc`.
17. **Voiding a day** — recomputes `non_reimbursable_meals` to the full counted total.
18. **Open-revision `reason`** — required only on the PAID branch.
19. **`POST /meal-claims/{id}/line-items`** — site existence is checked before the claim's.
20. **FOLLOW_UP visits** — included in due-date recomputation when `first_operating_date` changes.
21. **Line-item per-type maps** — include the union of meal types seen on the contributing finalized days, retaining zeros.
22. **Reopening a claim** — resets each line and recomputes `meals_rate_value_cents` without disallowances.
23. **Reimbursement-summary `variant`** — PRELIMINARY for DRAFT/SUBMITTED/REVISION_OPENED, FINAL otherwise.
24. **`reason` on escalate/review** — required by the PRD but has no storage field, so it is validated then discarded.

## Step 7: Run Tests and Iterate — 2026-09-02T22:51:18.112Z

All 8 parallel rounds green at 168/168.

## Summary

**Iterations run:** 2 (iteration 1 sweep found 5 failures reproducing identically in all 8 rounds — no flakiness; iteration 2 sweep fully green).

**Tests deleted:** none. All 5 failures traced to test-artifact bugs (STEP 2), not PRD-silence, so nothing met the deletion criterion.

**Fixes applied to `test_helpers/`:**

- `test_helpers/assertions.py` — `assert_monitoring_visit`: the `highest_severity` enum-membership check now runs only when the field carries a value. PRD §3.7 writes `highest_severity` *only* at report-filing time ("sets `highest_severity` to `NONE`" / "to the greatest severity present") and says nothing about a `SCHEDULED`/`CONDUCTED` visit, whose faithful value is null. The unconditional check failed 3 tests (`test_monitor_visit_window_touching_previous_end_is_rejected`, `test_monitor_visit_window_one_minute_after_previous_end_is_accepted`, `test_first_week_visit_conducted_on_its_due_date_is_not_late`) with a bare `AssertionError`.
- `test_helpers/fixtures.py` — `setup_program_baseline`: files its default area eligibility record (`CT-0031`/`SCHOOL_DATA`) only when a site in the baseline will cite one (`site_count > 0` or explicit `area_overrides`). With `site_count=0` the caller files its own record, and the default collided with PRD §3.4's "(area_code, data_source) must be unique" rule — the implementation correctly returned `ERR_DUPLICATE_AREA_RECORD`, failing the `[CT-0031-50.0-AREA_ELIGIBLE]` boundary parametrization in setup.

**Fixes applied to `test_suite/`:**

- `test_suite/test_05_cross_entity_gating.py` — `test_open_day_succeeds_after_suspended_site_is_reinstated`: the `food_received_at` check now asserts the stored instant (`startswith("2026-06-20T07:30:00")`) instead of byte-exact equality with the submitted string. PRD §3.6 says only that opening "stores both supplied values" and never pins how a client-supplied instant is re-serialized; the implementation renders every timestamp in the §2.2 canonical three-fractional-digit form (`...T07:30:00.000Z`). The same suite already uses `startswith` for this exact field in `test_08_state_transitions.py:507`, so this restores internal consistency rather than weakening a PRD rule.

**Fixes applied to `implementation/`:** none — no failure traced to an implementation defect.

**Final clean sweep (8 parallel rounds, results.1–8.json in `workspace/implementation/`):**

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 168/168 | 168/168 | 168/168 | 168/168 | 168/168 | 168/168 | 168/168 | 168/168 |

0 failed, 0 errors, 0 skipped in every round; union of failing tests across all 8 rounds is empty.

**Orchestrator independent verification** (not the subagent's claim): all 8 `results.{1..8}.json` present on disk, each parsed as `passed=168 total=168 failed=0 errors=0 skipped=0`; zero `pytest.mark.skip` / `pytest.mark.xfail` occurrences anywhere in `test_suite/` or `test_helpers/`.

## Step 8: Finalize PRD — 2026-09-02T23:03:00.000Z

`PRD_FINALIZED.md` is written. Two edits, both traced to `<step_7_diff>` items; the third item (the `fixtures.py` duplicate-area-record collision) needed no PRD change because §3.4 already pins the `(area_code, data_source)` uniqueness rule and `ERR_DUPLICATE_AREA_RECORD` — it was a pure fixture bug.

## Line counts
- PRD.md: 458 lines / 14,019 words
- PRD_FINALIZED.md: 458 lines / 14,136 words
- Δ lines: 0 (0.00%); Δ words: +117 (+0.83%). Both edits are in-line extensions of existing sentences; no new sections, no reflow.

## Changes
- **§2.5 — insert — canonical rendering of all instants, including client-supplied ones.** Added that every instant a resource or response carries is rendered in the same ISO 8601 UTC form with exactly three fractional digits, that a client-supplied instant (`food_received_at`, `measured_at`) is normalised into that rendering rather than echoed byte-for-byte, and that calendar-date fields stay plain `YYYY-MM-DD`. — `implementation/db.py:45` (`to_iso`), `implementation/routes/days.py:179`, `implementation/routes/days.py:412`
- **§3.7 — revise — initial value of a visit's `findings` and `highest_severity`.** The "A new visit begins in `status` `SCHEDULED` with `is_late` false" sentence now also states both fields start null and are not written before the report is filed, so `SCHEDULED`/`CONDUCTED`/`CANCELLED` visits carry null in both. — `implementation/routes/visits.py:68-69` (creation), `:153`/`:168` (only writers)

## Per-edit pre-edit search log

**Edit 1 — §3.7 visit `findings` / `highest_severity`**
- (a) Subject: initial and pre-report values of `highest_severity` and its companion `findings` on a `MonitoringVisit`.
- (b) Paths enumerated: `grep -rn 'highest_severity'` and `grep -rn '"findings"'` over all of `implementation/` — the only writers are `routes/visits.py:69` (create → `None`), `:152-153` (no-deficiency branch → `[]` / `"NONE"`), `:167-168` (deficiency branch → array / greatest severity); read at `services/serializers.py:234-237`. Also read `routes/visits.py:116-131` (conduct — touches neither), `:185-199` (cancel — touches neither), and `services/cascades.py:142-146` (`recompute_visit_deadlines`, which only rewrites `due_date`), to confirm no cascade writes either field.
- (c) Adjustment: enumerated `CANCELLED` and `CONDUCTED` as well as `SCHEDULED` rather than writing only "a scheduled visit", since cancel/conduct leave both fields untouched; and phrased the enum claim as "takes a value from its enum only once a report has been filed" so the no-deficiency `NONE` value is not contradicted.

**Edit 2 — §2.5 instant rendering**
- (a) Subject: the serialized form of every timestamp the API emits, in particular an instant that arrived from the client.
- (b) Paths enumerated: `db.py:45-56` (`to_iso`, the single formatter), `db.py:59-74` (`parse_datetime`), `db.py:180-193` (`created_at`/`updated_at`), `middleware.py:181-187` (`field_datetime`), and every producer of an instant string found by `grep -rn 'now_iso()\|to_iso('`: `response.py:20` (`api_request_timestamp`), `routes/sponsors.py:88` (`approved_at`), `routes/budgets.py:117,184`, `routes/advances.py:150,176`, `routes/days.py:179` (`food_received_at`), `:308` (`recorded_at`), `:412` (`measured_at`), `:426` (`breach_at`), `routes/visits.py:128` (`conducted_at`), `routes/claims.py:305,489` (`submitted_at`, `paid_at`), `routes/clock.py:18` (`current_utc`). Also checked `grep -rn '_at"\] *='` for any assignment bypassing the formatter — only the null-outs at `claims.py:539,568`. Confirmed no instant is stored or returned in raw client form anywhere.
- (c) Adjustment: wrote the rule as a universal over instants instead of scoping it to §3.6's `food_received_at`, because `measured_at`, `breach_at` and `current_utc` behave identically; and added the closing clause excluding calendar-date fields so the sentence cannot be read as demanding a fractional-digit rendering for `due_date`, `deadline_date`, `service_date`, `scheduled_date`, `first_operating_date`, `determination_date` or `valid_through_date`, which the implementation emits as `YYYY-MM-DD`.

## Step 9: Complete PRD — 2026-09-03T01:00:00.000Z

**Orchestrator note on execution shape.** The first Step 9 subagent (single full-scan agent) was killed by an infrastructure API timeout while it was still reading the implementation; it had only performed the step-0 `cp`, leaving `PRD_COMPLETED.md` byte-identical to `PRD_FINALIZED.md` (100,819 B) with zero edits. Rather than retry the same oversized single pass, the orchestrator decided (autonomously, no user available) to re-run Step 9 as **three sequential passes over the same in-place file**, partitioned by implementation file so each subagent's context stayed small. Passes ran strictly one after another so there were no concurrent writes to `PRD_COMPLETED.md`; each later pass was told not to revert earlier edits and verified them on exit. Method and constraints per pass were the skill's Step 9 prompt verbatim, with scope narrowed to its file set. No pass read SCAFFOLD*.yaml or worklog.md.

- Pass A (app.py, db.py, errors.py, middleware.py, response.py, routes/common.py, routes/clock.py, services/lookup.py, services/serializers.py)
- Pass B (routes/sponsors.py, budgets.py, advances.py, sites.py + sponsor/budget/advance/site calculations)
- Pass C (routes/days.py, visits.py, corrective_actions.py, claims.py, services/cascades.py + day/claim/visit/forecast calculations)

### Pass A summary (verbatim)

**File size:** before: 458 lines / 100,819 bytes → after: 460 lines / 107,124 bytes (+2 lines, +6,305 bytes). **Counts:** 21 ambiguity-pins, 2 mismatch-revisions (23 edits).

- §2.1 — revise — ambiguity — empty-string header values also yield `ERR_UNAUTHENTICATED`; role match is exact/case-sensitive; `X-User-ID` unvalidated beyond non-empty — middleware.py:54-57
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — response.py:13-14
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from the logical clock, not the wall clock — response.py:20
- §2.2 — revise — ambiguity — pagination `meta` keys are absent from object and error responses — response.py:17-46
- §2.2 — revise — **mismatch** — error envelope covers 5xx as well as 4xx — app.py:58-66
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` rejected; an `offset` past the end returns an empty page with true `total_count` and `has_more` false — middleware.py:224-244, response.py:58-63
- §2.3 — revise — ambiguity — records tied on `created_at` are ordered by server creation sequence, never by `id` — db.py:208-214
- §2.3 — insert — ambiguity — filters are conjunctive/exact-equality; malformed enum/date/month/int/bool filter → `ERR_INVALID_REQUEST`; boolean filters accept `true/false/1/0` any case; id filters not existence-checked; unknown query params ignored — middleware.py:254-303
- §2.4 — insert — ambiguity — `to_iso8601` mandatory; response `data` carries only `current_utc`; clock may be set backwards, no monotonicity — routes/clock.py:12-18, db.py:26-27
- §2.5 — revise — ambiguity — cross-reference of the creation-order tie-break — db.py:208-210
- §2.5 — insert — ambiguity — client instants accepted with `Z`, numeric offset, or no zone; sub-millisecond precision truncated not rounded; `HH:MM` fields echoed as supplied — db.py:45-74, routes/days.py:60-61
- §2.5 — revise — ambiguity — `updated_at` equals `created_at` until the first mutation — db.py:183
- §2.5 — insert — ambiguity — representations carry exactly the declared fields, no server-internal bookkeeping, valueless fields present-and-null — serializers.py:12-311
- §2.6 — insert — ambiguity — gauntlet step 3 detail: absent/empty body = `{}`, non-JSON or non-object body rejected, `Content-Type` never inspected, explicit `null` == omitted, undeclared body fields ignored, strict typing, decimals as number-or-numeric-string with finiteness/range/scale checks — middleware.py:72-219
- §2.9 — insert — ambiguity — fractional quantities travel as JSON numbers; `0.2000` renders `0.2`, `50.00` renders `50.0` — serializers.py:92/105/146/150/215, calculations.py:90-96
- §3.2 — revise — ambiguity — the submission instant is stored in `submitted_at` — serializers.py:111
- §3.2 — revise — ambiguity — the approval decision instant is stored in `decided_at` — serializers.py:112
- §3.2 — revise — ambiguity — `decided_at` is stamped on every decision branch, not only approval — routes/budgets.py:184
- §3.3 — insert — ambiguity — which budget is consulted when a sponsor holds several: `APPROVED`/`AMENDMENT_PENDING` candidates ordered by `created_at`, preferring the sponsor's own `program_year`, else earliest-created — lookup.py:122-141
- §3.7 — insert — ambiguity — `is_late` is derived at read time and is always false for `CANCELLED`; a `SCHEDULED` visit's flag flips with the clock without a write — serializers.py:239, calculations.py:278-290
- §3.8 — revise — ambiguity — claim-side budget selection prefers a `program_year` matching the `claim_month` year first — lookup.py:122-141
- §4 — insert — ambiguity — trailing slash accepted on every path — app.py:22
- §5 — insert — **mismatch** — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), transport-level `ERR_INVALID_REQUEST` (400) and `ERR_INTERNAL` (500) exist outside the table and its priority order — app.py:42-66

Integrity: all sections §1–§5 present and in order; §5 still holds its 65 rows; file still ends at `| ERR_ADMIN_COST_EXCEEDS_BUDGET | 422 |`. Note for later passes: the §5 table was verified byte-for-byte against `errors.py::ERROR_STATUS` (65 ids, identical statuses and order), so no error-code work remains.

### Pass B summary (verbatim)

**File size:** before 460 lines / 107,124 bytes → after 460 lines / 112,890 bytes (all inserts in-paragraph). **Counts:** 24 ambiguity-pins, 2 mismatch-revisions.

- §3.1 — insert — ambiguity — `application-submit` takes no request body; a body sent with it is ignored — routes/sponsors.py:57
- §3.1 — insert — ambiguity — a `reason` sent with an `APPROVED` sponsor decision is ignored; `approved_at` is never cleared, so a `TERMINATED` sponsor keeps it — routes/sponsors.py:86-94
- §3.1 — insert — ambiguity — the termination cascade's `claim_hold` is site-level only, not propagated to claim line items (unlike §3.5's suspension) — services/cascades.py:116-128
- §3.2 — insert — ambiguity — budget `program_year` must be ≥ 2020, and the equality with the sponsor's year is compared only after sponsor resolution and ownership, reported as `ERR_INVALID_REQUEST` — routes/budgets.py:34,41-42
- §3.2 — insert — ambiguity — fields a decision branch does not require are accepted and ignored — routes/budgets.py:161-183
- §3.2 — insert — ambiguity — an approved ceiling of 0 is legal; negative is `ERR_INVALID_REQUEST` — routes/budgets.py:130-135
- §3.3 — insert — ambiguity — no uniqueness on (sponsor, `request_month`); repeats accepted — routes/advances.py:32-61
- §3.3 — insert — ambiguity — the four approval gates fire in §2.6 order (budget → exceeds-requested → cap → advance-eligibility), not the order §3.3 narrates — routes/advances.py:112-124
- §3.3 — insert — ambiguity — `approved_amount_cents` of 0 is a legal approval — routes/advances.py:99
- §3.3 — insert — ambiguity — `disburse` takes no request body — routes/advances.py:137
- §3.3 — insert — ambiguity — a non-positive outstanding balance also reports `ERR_DEMAND_TOO_EARLY` — routes/advances.py:172-173
- §3.4 — insert — ambiguity — no ordering enforced between `determination_date` and `valid_through_date` — routes/sponsors.py:115-116
- §3.4 — insert — ambiguity — the (`area_code`,`data_source`) uniqueness is exact, case-sensitive string equality — routes/sponsors.py:118-120
- §3.4 — insert — ambiguity — `operating_start_date`/`operating_end_date` mandatory, may be equal, end-before-start is step-3 `ERR_INVALID_REQUEST` before sponsor resolution — routes/sites.py:40-41,58-59
- §3.4 — insert — ambiguity — the type-irrelevant field is accepted and stored, a named area record is still resolved, and the determination ignores it — routes/sites.py:62-64,88,156-189
- §3.4 — insert — ambiguity — non-array / empty / unknown-member / duplicate `approved_meal_types` are step-3 `ERR_INVALID_REQUEST`, distinct from `ERR_MEAL_TYPE_COUNT_EXCEEDED` — routes/sites.py:49-57 vs 75-83
- §3.4 — insert — ambiguity — the eligibility determination takes no body and always bumps `updated_at`/`version`, even on an identical re-run — routes/sites.py:152,191-193
- §3.5 — insert — ambiguity — for approval from `PENDING_REVIEW` the sponsor gate runs before the two eligibility gates — routes/sites.py:227-235
- §3.5 — insert — ambiguity — `DENIED` from `PENDING_REVIEW` fires no cascade — routes/sites.py:244-247
- §3.5 — insert — ambiguity — suspension's line-item hop only re-versions rows that actually change — services/cascades.py:59-71, db.py:196-205
- §3.5 — insert — ambiguity — same only-what-changes rule for reinstatement — services/cascades.py:90-96
- §3.5 — insert — ambiguity — denial from `SUSPENDED` voids planned days irrespective of `service_date`, keeps `claim_hold` true, no second line-item pass — services/cascades.py:99-104
- §3.5 — insert — ambiguity — on the operating axis, `ERR_SITE_STATE_INVALID` precedes `ERR_SITE_NOT_APPROVED`/`ERR_SITE_SUSPENDED` — routes/sites.py:263-269
- §3.9 — insert — ambiguity — `service_date` and `method` are mandatory query parameters, rejected at step 3 before the path `site_id` resolves — routes/sites.py:287-294
- §3.9 — insert — ambiguity — `most_recent_production_meals` reads 0 when the most recent window day carries no `production_counts` — services/calculations.py:411-412
- §4 (sponsors row) — revise — **mismatch** — the decision endpoint also accepts `TERMINATED` — routes/sponsors.py:71
- §4 (sites list row) — revise — **mismatch** — description omitted the `area_eligibility_record_id` filter the endpoint implements — routes/sites.py:126,135-139

Integrity: sections intact; tail intact; Pass A edits spot-verified still present; no §5 row touched.

### Pass C summary (verbatim)

**File size:** before 460 lines / 112,890 bytes → after 460 lines / 124,270 bytes (all in-paragraph). **Counts:** 19 ambiguity-pins, 11 mismatch-revisions (30 pins across 23 Edit operations).

- §2.3 — revise — mismatch — service-day filter enumeration was missing `food_safety_status` — routes/days.py:128
- §3.6 ¶planning — insert — ambiguity — `planned_meals` is an integer ≥0, stored and never read by any calculation; each element must be an object, extras discarded — routes/days.py:50,57-64
- §3.6 ¶planning — insert — ambiguity — planning consults neither site status axis (only ownership) — routes/days.py:67-68
- §3.6 ¶planning — insert — ambiguity — `breach_at` and `void_reason` null at creation — routes/days.py:99,107
- §3.6 ¶open — insert — ambiguity — `production_counts` must be an object of non-negative integers; the key-set check runs after day resolution but before ownership and state; stored map rewritten in declared order — routes/days.py:151-178
- §3.6 ¶open — revise — mismatch — opening runs classification once (counted totals 0, `leftover_meals` = whole production); site re-versioned only when `first_operating_date` moves; the deadline sweep covers **every non-`CANCELLED`** visit (PRD said only `FIRST_WEEK`/`FULL_REVIEW`), runs on every open, writes nothing for `is_late`, and skips re-versioning a visit whose `due_date` is unchanged — routes/days.py:180-195, services/cascades.py:142-146
- §3.6 ¶classification — insert — ambiguity — meal types counted but not declared are classified after the declared ones in ascending order, and collapse to 0 reimbursable on a `SELF_PREP` day — services/calculations.py:137-141,178-186
- §3.6 ¶close — insert — ambiguity — close rewrites the three counted totals too, takes no body, gates on neither site axis nor `food_safety_status` — routes/days.py:200-217
- §3.6 ¶finalize — insert — ambiguity — finalize takes no body and changes only `status` — routes/days.py:220-231
- §3.6 ¶void — insert — mismatch — voiding rewrites `non_reimbursable_meals` to the whole counted total, re-versions the site row, leaves counted totals / `discarded_meals` / `leftover_meals` standing — services/cascades.py:15-25, routes/days.py:248-249
- §3.7 ¶schedule — insert — ambiguity — scheduling ignores both site status axes; `monitor_user_id` need not be the caller and is never validated — routes/visits.py:26-37
- §3.7 ¶schedule — revise — mismatch — a new visit is not necessarily `is_late` false: read-time derivation reports true immediately if `due_date` is already past — routes/visits.py:76, services/serializers.py:239
- §3.7 ¶conduct — insert — ambiguity — conduct takes no body — routes/visits.py:118
- §3.7 ¶report — insert — ambiguity — finding elements must be objects, only the two members retained, order preserved, duplicates allowed — routes/visits.py:139-145
- §3.7 ¶report — revise — mismatch — the `CRITICAL` suspension fires only when the site is `APPROVED`, and `suspension_reason` is literal `CRITICAL_FINDING:` + `finding_code` — services/cascades.py:190-191
- §3.7 ¶reject — insert — ambiguity — the rejection `reason` is required but never stored — routes/corrective_actions.py:89
- §3.7 ¶escalate — revise — mismatch — `reason` never stored; the non-`APPROVED` branch raises `claim_hold` only, propagating `hold_flag`/`blocking_hold_count` to live line items, and writes nothing when the hold was already up — routes/corrective_actions.py:145-149, services/cascades.py:131-136
- §3.8 ¶create — insert — ambiguity — `claim_month` is not restricted to the summer months (unlike an advance's `request_month`) — routes/claims.py:91
- §3.8 ¶create — insert — ambiguity — the claim's full set of initial null/0/false field values — routes/claims.py:113-134
- §3.8 ¶line-items — insert — mismatch — the missing `ERR_SITE_SPONSOR_MISMATCH` rule, and that the site's `approval_status` is never consulted — routes/claims.py:185-186
- §3.8 ¶line-items — insert — ambiguity — both claimed-meals maps share one key set, ascending, including types whose total is 0 — routes/claims.py:67-70
- §3.8 ¶submit — revise — mismatch — `ERR_CLAIM_HAS_NO_LINE_ITEMS` and `ERR_CLAIM_HOLD_BLOCKING` are evaluated **before** `ERR_BUDGET_NOT_APPROVED`, inverting §2.6's group order on this endpoint — routes/claims.py:271-280
- §3.8 ¶submit — insert — ambiguity — re-aggregation re-versions only lines whose figures actually moved, and touches only four fields — routes/claims.py:289-300
- §3.8 ¶rule 2 — insert — ambiguity — the `FOOD_SAFETY_BREACH` map carries a 0 key for every type the breaching days classified — routes/claims.py:349-356
- §3.8 ¶rule 3 — insert — ambiguity — the `EXCEEDS_PRODUCTION` map is sparse (positive excesses only) — routes/claims.py:366-373
- §3.8 ¶compliance — revise — mismatch — the raised `claim_hold` propagates to live line items, and the trip fires only on the flag bringing the count to exactly 2 — routes/claims.py:417-430, services/cascades.py:131-136
- §3.8 ¶pay — insert — ambiguity — pay takes no body; both preconditions report `ERR_CLAIM_STATE_INVALID` — routes/claims.py:458-461
- §3.8 ¶reopen — revise — mismatch — `reason` optional from `EDIT_CHECK_FAILED`, mandatory from `PAID`, tested after the status check, never stored; lines re-versioned unconditionally; claim `meals_rate_value_cents`/`disallowed_meal_count` restored — routes/claims.py:527-544, 500-509
- §3.8 ¶reopen — insert — mismatch — the paid branch writes the claim row twice, so `version` advances by 2 (vs 1 on the failed branch); `submitted_at`/`preliminary_reimbursement_cents` survive — routes/claims.py:551,570
- §3.8 ¶summary — insert — ambiguity — `variant` status mapping (`PRELIMINARY` for DRAFT/SUBMITTED/REVISION_OPENED, `FINAL` otherwise); the four intermediates always computed by the final variant with null costs read as 0 — routes/claims.py:580-599

Handed-off `db.apply_changes` item — resolved: `write_day_totals` (calculations.py:210-224) has no caller anywhere, so that `apply_changes` site is dead code and nothing was invented for it. `cascades.py:56` was already pinned by Pass B's only-what-changes rule in §3.5, now referenced from the two new call paths (§3.7 escalation, §3.8 compliance hold); `cascades.py:146` (visit `due_date`) is pinned in §3.6's opening paragraph. §2.7 needed no change.

Integrity: §1–§5 and all 19 subsections §2.1–§3.9 present at their original line numbers; file still ends at `| ERR_ADMIN_COST_EXCEEDS_BUDGET | 422 |`; §5 still holds all 65 rows; Passes A/B edits verified still present.

### Step 9 aggregate (orchestrator-verified)

- `PRD.md` 458 lines / 100,063 B → `PRD_FINALIZED.md` 458 lines / 100,819 B → `PRD_COMPLETED.md` **460 lines / 124,270 B** (+2 lines, +23,451 B over PRD_FINALIZED, +23.3 %).
- Totals across the three passes: **64 ambiguity-pins, 15 mismatch-revisions** (79 pins).
- Orchestrator independently verified: `PRD_COMPLETED.md` contains all five `##` sections (§1 Introduction, §2 Global Specifications, §3 Business Logic, §4 API Endpoints, §5 Error Codes) at lines 3/11/149/321/388, 25 headings total, and ends at the final §5 table row — no truncation.
- Orchestrator independently verified: **no file under `implementation/` was modified after Step 7's green sweep** (`find implementation -name '*.py' -newermt '2026-09-02 23:00'` is empty), so the recorded 8×168/168 result still describes the shipped implementation. Steps 8 and 9 touched documentation only.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` written; all nine steps done.
