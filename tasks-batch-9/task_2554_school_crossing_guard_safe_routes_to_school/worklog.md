# Worklog — task_2554_school_crossing_guard_safe_routes_to_school

## Step 1: Create task directory — 2026-09-03T09:29:34.321Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2554_school_crossing_guard_safe_routes_to_school` and its `workspace/` subdirectory. Index 2554 was pre-assigned by the invoker; no scan of `./tasks/` was performed and no index was auto-allocated (concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-03T11:04:03.783Z

All three scaffold artifacts are complete and the mandated lint is clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2554_school_crossing_guard_safe_routes_to_school/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2554_school_crossing_guard_safe_routes_to_school/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2554_school_crossing_guard_safe_routes_to_school/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     11
  §1.8 instances scanned:     22
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  1216

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files**
- `SCAFFOLD.yaml` — 3204 lines (§1.0–§1.7 only; contains neither design key)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2706 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5038 lines (single key `scaffold_corner_design`)

**SCAFFOLD.yaml surface** — 11 entities, 11 state machines, 3 OCC rules (§1.2.1), 10 calculations (3 dual-variant), 35 validation rules, 50 endpoints (19 GET / 31 POST), 59 error codes, 6 roles; `difficulty_level: expert_plus`, topology `graph`, SM shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.

**§1.8 — 9 rules / 22 instances:** dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

**§1.9 — 9 sections / 79 instances** (full instances + `excluded_because` stubs): entities 8 (0 stubs), state_machines 13 (4), calculations 13 (8), validations 9 (5), endpoints 4 (1), errors 19 (8), rbac 6 (0), cross_cutting_complexity_layers 6 (2), consistency_model 1 (0). 101 instance names total across both design files, all globally unique; every stub cites an existing §1.8 instance and carries no `test_recipe`.

**Defects found and fixed during self-audit** (all internal-consistency, in addition to the three from earlier: unreachable `ERR_POST_SHIFT_NOT_PERMITTED`, `school_coverage_posture` counter mismatch, provably unreachable `ERR_NO_SCORED_PROJECT`):
- §1.2.1 `assignment-create-stale-post` prose cited a `current_assignment_count` field that GuardPost never declares → reworded to `coverage_status` / `open_gap_count`.
- Stale `complexity_profile.difficulty_level` comment (48 endpoints / 36 errors / 8 calculations / 10 SMs) → corrected to the real counts.
- Corner asserts corrected against §1.1: `hazard_score 6.00` → `1.66` (per-segment rounding), `PostAssignment.status PENDING` → `SCHEDULED`, `vacate_reason` → `vacated_reason`, `dispatch_round` → `dispatch_attempt_count`, `Intersection.status` (nonexistent) → `warrant_status == UNDER_STUDY`.
- Scripted audits now report 0 unknown `Entity.field` and 0 unknown `data.<field>` references across every assert in both design files.

## Step 3: Copy shared files — 2026-09-03T11:04:10.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T11:21:05.512Z

PRD generation for task 2554 is complete.

**Output:** `workspace/PRD.md`
**Line count:** 436 lines (101,673 bytes), written in eight chunked heredoc appends — no single giant Write, so no 64k truncation.

**Section list**
- `# School Crossing Safe Routes API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Program Roles and Access Control; 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 The Logical Program Clock; 2.5 Common Resource Properties and Append-Only Ledgers; 2.6 Resolving Paths and Foreign Keys; 2.7 Coverage Propagation: Post to School to Route; 2.8 Numeric Precision and Rounding; 2.9 Stale-Version Guards on Warrant, Roster and Grant Writes; 2.10 Rejection Precedence; 2.11 Conservation of Grant Funds (8 domain-named subsections after the 3 fixed ones)
- `## 3. Business Logic & Workflows` — 3.1 Schools, Crossing Windows and the Seasonal Calendar; 3.2 Crossing Locations, Crash History and Opening a Study; 3.3 Counting, Scoring and Adopting a Determination; 3.4 Building the Guard Workforce: Training, Equipment, Certification and Duty; 3.5 Activating Posts and Staffing Them; 3.6 Absences, Substitute Dispatch and the Cost of Coverage; 3.7 Recommended Walking Routes and Hazard Mapping; 3.8 Complaint Intake, Engineering Referral and Grant-Funded Projects; 3.9 Program Evaluation: Travel Tallies and the Mode-Share Trend (9 subsections)
- `## 4. API Endpoint Definitions` — 4-column table, **50 rows** (19 GET / 31 POST) verified by count
- `## 5. Error Code Catalogue` — 2-column table, **59 rows** verified by count; no audit footer

**Hard Contract reports**

- **Contract 1 — Field-Name Coverage: PASS.** 170 distinct scaffold field names (entity `name:` declarations plus every endpoint `input:` token) checked against 452 backticked spans in the PRD; missing set is empty. Also verified: all 79 `enum {...}` members, all 11 entity names + 6 role names, and all 59 error ids appear.
- **Contract 2 — Rule Coverage: PASS.** All 35 validation priority bands (10/12/20/30/34/40/42/45/50x10/58x6/60x8/66x2/72) are rendered as ordered prose, with §2.10 giving the 13-band precedence ladder. All 3 `concurrency_rules` OCC guards (`expected_intersection_version`, `expected_guard_post_version`, `expected_grant_program_version`, all 412) are in §2.9 with their write sites. All 68 declared state-machine transitions across the 11 machines are covered (39 are expressed in prose rather than literal `A -> B` arrow form — e.g. the recertification self-loop, the `ON_LEAVE`/`RETURN` fork, posture threshold crossings, route retirement — each was individually re-read and confirmed). All 10 calculations including the 3 dual-variant ones (`warrant_score` GAP_ADEQUACY/EXPOSURE_INDEX, both `guard_reliability_score` variants, both `walk_bike_mode_share` variants) are stated with pinned evaluation order, caps, and rounding. Cross-entity side effects are covered in both directions: the finalize cascades (asymmetric WARRANTED / CONDITIONAL / NOT_WARRANTED branches), the reliability-breach cascade, the 4-link coverage propagation forward (absence create) and in reverse (accept, rescind), post supersede-vs-truncate, and the grant fund/withdraw mirror pair including complaint `REFERRED <-> RESOLVED`.
- **Contract 3 — §3 Path Purity: PASS.** Mechanical scan of the §3 region found 0 backticked spans containing `/`, 0 bare HTTP methods in backticks, 0 method+path combos, and 0 raw `/path`-shaped tokens outside backticks. §3 uses state-transition framing, role + action-verb framing, and capability descriptions only.

**Non-truncated tail confirmed.** The file ends at a real section boundary — the completed final row of the §5 Error Code Catalogue table. Last 3 lines verbatim:

```
| `ERR_GRANT_FUNDS_EXHAUSTED` | 402 |
| `ERR_PROJECT_NOT_FUNDED` | 409 |
| `ERR_CLOCK_MOVED_BACKWARD` | 422 |
```

**Constraint compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory under `tasks/` was read.

**Scaffold-internal contradictions resolved** (recorded here, not in the PRD): initial certification training floor -> 12.0 hours (validation priority 50 + `ERR_TRAINING_HOURS_INSUFFICIENT` outvote the state machine's 8.0); `count_window_end` strictly later than `count_window_start` (field constraint + half-open semantics); count-session `session_date` window treated as closed (validation priority 58 + error catalogue outvote the transition precondition); `equipment_complete` certify precondition paired with `ERR_GUARD_EQUIPMENT_INCOMPLETE` (no error id was declared); intersection `crash_severity_points` restricted to pedestrian-involved crashes in the same 1095-day window as the project-scoring input set.

**Orchestrator verification:** independently confirmed 436 lines / 101,673 bytes, tail ends on the final `ERR_CLOCK_MOVED_BACKWARD` table row (a real section boundary, not mid-sentence), and grep for the difficulty instruction ("harder than expert", "expert level", "expert_plus") returns zero matches in PRD.md — no difficulty-instruction leakage.

## Step 5: Generate unit tests — 2026-09-03T13:04:00.000Z

The unit-test infrastructure for task 2554 is complete. Both output directories are at the task root (not under `workspace/`).

## Files

`test_helpers/` (Stage 1, 2442 lines)
`__init__.py` 43 · `api_client.py` 280 · `api_errors.py` 132 · `assertions.py` 363 · `constants.py` 113 · `factories.py` 289 · `fixtures.py` 631 · `test_users.py` 84 · `types.py` 507

`test_suite/` (Stage 2, 4375 lines incl. conftest)
`conftest.py` 55 · `test_01_warrant_studies_and_determinations.py` 210 (6 tests) · `test_02_guard_reliability_and_staffing_gates.py` 203 (6) · `test_03_post_activation_and_the_duty_calendar.py` 214 (5) · `test_04_substitute_dispatch_and_coverage_cost.py` 192 (6) · `test_05_coverage_propagation_and_advisory_holds.py` 254 (6) · `test_06_walking_route_hazard_and_publication_gates.py` 220 (6) · `test_07_project_scoring_and_award_fan_out.py` 276 (6) · `test_08_grant_ledger_and_deferral_loop.py` 205 (4) · `test_09_entity_shapes_and_input_validation.py` 280 (8) · `test_10_lifecycle_transitions_and_locks.py` 388 (9) · `test_11_derived_calculations.py` 289 (6) · `test_12_validation_edges_and_endpoint_contracts.py` 344 (7) · `test_13_error_codes.py` 663 (11) · `test_14_rbac_and_concurrency.py` 582 (10)

**Total: 96 tests.** All files `py_compile` clean; `test_14` also imports cleanly (so every helper symbol and all 21 `api.*` methods it calls exist).

## Design-index coverage

- **Queue A (§1.8 Difficulty): 22 / 22 instances translated, 0 skipped** — 45 tests, every instance carrying >=2 tagged tests (min 2).
- **Queue B (§1.9 Corner): 51 / 51 non-stub instances translated, 0 skipped** — 51 tests, exactly 1 per instance. Per section: entities 8, state_machines 9, calculations 5, consistency_model 1, validations 4, endpoints 3, errors 11, rbac 6, cross_cutting_complexity_layers 4.
- Citation auditor: `tests=96 tagged_ok=96 problems=0` — every test has exactly one `Design:` line as the last docstring line, every tag resolves to a real `name:` in the source yaml, and every quoted span >=20 chars is whitespace-normalized verbatim from `workspace/PRD.md`.

## Skip / partial list

1. **28 §1.9 `excluded_because` stubs** — left untranslated by design (they redirect to the §1.8 instance that already covers the claim, e.g. `corner_count_window_overlap_error_stub`, `corner_cascading_side_effects_layer_stub`, `corner_dual_variant_calculation_layer_stub`). 79 corner names total − 28 stubs = the 51 non-stub instances all covered.
2. **Partial: `Difficulty/.../warrant_count_window_half_open_overlap_with_thirty_day_cooloff`** — the design asserts the intersection retains `latest_warrant_score == 66.19` after a new study opens; PRD L181 states a new study "additionally clears `latest_warrant_score` back to null". The instance is translated; that single contradicting assertion is omitted rather than weakened.
3. **Partial: `Corner/errors/corner_assignment_eligibility_error_codes`** — the design's `ERR_GUARD_EQUIPMENT_INCOMPLETE` trigger requires a CERTIFIED guard holding only 2 of 3 equipment items, which PRD L215/L217 make unreachable (all three certification paths require `equipment_complete`, and "Nothing about a guard's certification or staffing is possible while that flag is false"). Translated for `ERR_GUARD_ON_LEAVE` and `ERR_ASSIGNMENT_OUTSIDE_SESSION`; the impossible trigger is omitted.
4. **Design assertion re-expressed (not dropped):** in `corner_cross_role_exclusive_operations_are_rejected` the design's absolute `isx_v + 2` version arithmetic is asserted as "intersection `version` unchanged across the rejected call" (captured before/after), which is what the PRD uniquely derives.

No test is marked skip/xfail and no placeholders were emitted. `workspace/implementation/` and all sibling task directories were left unread.

## Step 6: Generate implementation — 2026-09-03T12:26:00.000Z

The implementation is complete and verified.

## Files on disk — `workspace/implementation/`

| File | Lines | Role |
| --- | --- | --- |
| `app.py` | 59 | Flask app factory, 10 blueprint registrations, `ApiError`/`HTTPException` handlers, `app.run(host="0.0.0.0", port=$PORT or 10000)` |
| `start.sh` | (exec, 398 B) | `set -euo pipefail`, guarded `pip install` of flask, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `db.py` | 103 | In-memory `Store` of 11 dicts + logical clock (`CLOCK_EPOCH = 2026-08-01T00:00:00Z`), `base_entity`, once-per-request `touch`, `public`, stable `_seq` sort key |
| `timeutil.py` | 80 | ISO-8601 parse/format (3 fractional digits + `Z`), date/HH:MM helpers |
| `errors.py` | 81 | `ApiError` + `ERROR_STATUS` for all **59** PRD §5 error ids, `fail()` |
| `response.py` | 65 | `meta`/`response_type`/`data` envelope, `req_<20>` request ids, list envelope with `limit/offset/total_count/has_more` |
| `auth.py` | 40 | `X-User-ID`/`X-User-Role`, 6 roles, 401 before 403 |
| `validate.py` | 220 | Typed body readers, pagination (limit 1..100 / offset >= 0), query filters |
| `calc.py` | 323 | All Decimal/ROUND_HALF_UP math: warrant score variants, reliability, hazard score, substitute cost & urgency tiers, coverage rate/posture, benefit-cost score, mode-share variants, shift conflicts |
| `domain.py` | 520 | FK resolvers, cascades (post/assignment/school coverage, route advisory holds, reliability breach, crash aggregates, program balance), `advance_clock` sweep |
| `routes/` (10 modules) | 1906 | schools 148, intersections 152, studies 244, guards 165, posts 205, absences 312, walking_routes 140, complaints 51, grants 259, clock 30 |

Total 3197 lines. All 21 files pass `ast.parse`. `__pycache__` removed; the only files on disk are source — no DB, JSON, or cache artifacts, and nothing is ever seeded at boot.

## Endpoints: 50 implemented vs 50 declared in PRD §4

Extracted the method+path pairs from the PRD §4 table and diffed them against `app.url_map`: **exact match, zero differences in either direction** (`GET`/`POST` only; 8 grant/project endpoints and the clock endpoint were the ones added in this final pass).

## Smoke test — `PORT=18554 bash start.sh`

Ran a 60-call end-to-end scenario against the live server: school -> intersection -> crash record -> warrant study (4 count sessions, `AM_ARRIVAL`/`PM_DISMISSAL`) -> analyze (score 75.60, `WARRANTED`, `GAP_ADEQUACY`) -> SoD refusal 403 on self-finalize -> finalize by a second engineer -> guard post activate -> guard enroll/train/equip/certify -> assignment (OCC on post version) -> clock advance to 2026-09-02 (assignment `SCHEDULED -> ACTIVE`) -> absence (notice 31.25 h, tier `SHORT`) -> dispatch -> offer accept (`COVERED`, cost 3351¢) -> walking route draft + publish (hazard 3.15) -> complaint file + triage -> grant program -> project score (BCS 36.59) -> fund (committed 3 200 000 / remaining 1 800 000) -> withdraw (remaining back to 5 000 000) -> mode-share survey (raw 26.79 / weighted 17.86 / trend 8.29) -> all list endpoints with filters -> duty-status -> 403 wrong role -> 401 missing headers.

**FAILURES: 0.** No tracebacks or 5xx in the server log. Also verified: repeated GETs leave `version` at 1 (reads never bump), unrouted paths give a 404 envelope, `limit=0` gives `ERR_INVALID_REQUEST` 400, and a backwards clock set gives `ERR_CLOCK_MOVED_BACKWARD` 422. The server was killed by its exact pid (`kill 3864355`); port 18554 confirmed free. No pattern kill was used at any point.

Every early "failure" during smoke testing was the agent's scratch script guessing wrong field names/enums (`school_name`, `occurred_at`, `VEST`, `AM`, `PLACE_ON_LEAVE`); in each case the PRD was checked and the implementation was correct — the script was fixed, not the code.

## Step 7: Run tests and iterate — 2026-09-03T12:55:43.707Z

Clean sweep. All 8 rounds 96/96.

## Summary

**Iterations run:** 2 (each an 8-round parallel `setsid nohup` sweep, `--isolation per-test-server`).

**Iteration 1 baseline:** 75/96 in all 8 rounds — 21 failing tests, identical set every round (fully deterministic, no flakiness signal, no reaping pattern).

**Tests deleted:** none. Both failure clusters were test-side defects with the PRD rule intact and uniquely derivable, so STEP 1 kept every test and STEP 2/1c handled them.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `parse_instant()` and `assert_same_instant(actual, expected, label)`; rewrote `assert_clock_response()` to compare `current_utc` as an instant instead of as a raw string. Why: PRD §2.5 mandates *three fractional digits* for `created_at`/`updated_at` and §2.2 for `api_request_timestamp`, but never pins a serialization for the domain stamps (`activated_at`, `published_at`, `funded_at`, `recorded_at`, `offered_at`, `offer_expires_at`, `current_offer_expires_at`) or for `current_utc`. §2.4 only says the clock "reads exactly `2026-08-01T00:00:00Z`" — a statement about the clock's *value*, not about stamp formatting. The PRD-covered content is the *instant* (e.g. "`offer_expires_at` set to the logical clock plus 45 minutes"); the exact string form is not uniquely derivable, so per STEP 1c the covered assertion (instant) is kept at full strength and the uncovered one (byte-exact serialization) is dropped.

**Fixes applied to `test_suite/` (19 tests, all in the same category):** replaced byte-exact timestamp string comparisons with `assert_same_instant(...)` in `test_03` (1), `test_04` (3), `test_05` (2), `test_06` (1), `test_07` (1), `test_08` (2), `test_10` (3), `test_11` (2), `test_13` (3), `test_14` (1).

**Second cluster — undeclared enum members in request payloads (2 tests, `test_12_validation_edges_and_endpoint_contracts.py`):**
- `test_the_last_day_of_the_assignment_window_can_still_be_missed` sent `reason="PERSONAL"`, and `test_the_duplicate_gate_releases_once_the_first_report_is_rescinded` sent `reason="FAMILY_EMERGENCY"`. PRD §3.6 declares `reason` as one of `ILLNESS`, `FAMILY`, `WEATHER`, `TRAINING`, `UNEXCUSED`, so the implementation correctly returned `ERR_INVALID_REQUEST` from precedence band 3 before ever reaching the gate under test. Changed to `ILLNESS` / `FAMILY` respectively — the tests now actually exercise `ERR_ABSENCE_OUTSIDE_ASSIGNMENT` and `ERR_ABSENCE_DUPLICATE` as intended.

**Fixes applied to `implementation/`:** none. No implementation defect was found; no PRD-required check was removed or weakened, no endpoint/field/side-effect was added, and storage remains in-memory only.

**Audit performed alongside:** AST-scanned all of `test_suite/` and `test_helpers/` for any other undeclared enum literal across 14 enum-typed fields. Only intentional negative-test values remain (`control_type="ROUNDABOUT"` in the undeclared-enum test) plus free-text `rescind_reason` strings — no further latent payload bugs.

**Final sweep evidence** (all under `workspace/implementation/`):

| results file | passed/total |
| --- | --- |
| `results.1.json` | 96/96 |
| `results.2.json` | 96/96 |
| `results.3.json` | 96/96 |
| `results.4.json` | 96/96 |
| `results.5.json` | 96/96 |
| `results.6.json` | 96/96 |
| `results.7.json` | 96/96 |
| `results.8.json` | 96/96 |

**Orchestrator verification:** independently re-read all 8 `results.*.json` (each 30 KB, all written 12:53) and confirmed `passed=96 total=96 failed=0` in every one. Step 8 is NOT skipped — Step 7 applied test-side fixes (1 `test_helpers/` file, 21 tests across 11 `test_suite/` files), which mark PRD sites that failed to uniquely determine behavior the implementation had already chosen.

## Step 8: Finalize PRD — 2026-09-03T13:00:10.484Z

Done. `PRD_FINALIZED.md` is a 2-line patch of `PRD.md`.

**Line/byte counts:** PRD.md 436 lines / 101,673 B -> PRD_FINALIZED.md 436 lines / 102,534 B. Line delta 0 (0.00%); byte delta +861 (+0.85%). Two lines modified (82, 94); tail still ends at `| ERR_CLOCK_MOVED_BACKWARD | 422 |`.

## Changes

- **§2.4 (Logical Program Clock)** — *insert* — added two sentences after "Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`.": every UTC instant the server itself renders (`created_at`, `updated_at`, the domain stamps, `current_offer_expires_at`, `shift_start_utc`, `api_request_timestamp`, `current_utc`) is serialized as `YYYY-MM-DDTHH:MM:SS.sssZ` — ISO 8601 UTC, exactly three fractional digits, literal trailing `Z`, fractional digits present even on a whole second (so the unset clock renders `2026-08-01T00:00:00.000Z`); plus the one exception, a client-supplied instant stored without derivation (a complaint's `occurred_at`) is returned byte-for-byte as sent — `implementation/timeutil.py:8-16` (`fmt_dt`), `implementation/routes/clock.py:27`, `implementation/routes/intersections.py:127,140`.
- **§2.5 (Common Resource Properties)** — *revise* — `updated_at` bullet now reads "an ISO 8601 UTC timestamp **with three fractional digits**, refreshed from the logical clock..." (PRD pinned the digit count on `created_at` only) — `implementation/db.py:83,88`.

No PRD edit for the second Step 7 cluster (undeclared `reason` enum members in two `test_12` payloads): §3.6 line 247 already declares `ILLNESS`/`FAMILY`/`WEATHER`/`TRAINING`/`UNEXCUSED`, and §2.10 band 3 already states "every enum-typed field must name a declared member" ahead of band 10 (absence-date containment) and band 11 (absence duplication). The implementation matches the PRD exactly; that was a pure fixture bug.

## Per-edit pre-edit search log

**Edit 1 — §2.4 timestamp serialization**
- (a) Subject: the wire format of every datetime-valued field the server emits, and the boundary between server-minted and client-supplied instants.
- (b) Paths enumerated: grepped `fmt_dt|fmt_date` across all of `implementation/` — every emitting site routes through the single helper `timeutil.py:fmt_dt` (`db.py:52` `base_entity`, `db.py:83` and `db.py:88` both `touch` branches, `response.py:20` `api_request_timestamp`, `routes/clock.py:27` `current_utc`, `routes/posts.py:73` `activated_at`, `routes/walking_routes.py:120` `published_at`, `routes/grants.py:199` `funded_at`, `routes/absences.py:79` `shift_start_utc`, `:182` `offer_expires_at`/`current_offer_expires_at`, `:186` `offered_at`, and the four `recorded_at` ledgers at `routes/schools.py:124`, `routes/studies.py:114`, `routes/guards.py:96`, `routes/intersections.py:77`). Also grepped every `"*_at"`/`"*_utc"` string literal in the tree to catch fields no `fmt_dt` grep would show: that surfaced `occurred_at` (`routes/intersections.py:127-128,140` — read verbatim with `v.req_str`, only *additionally* parse-checked by `v.req_datetime`, stored unstripped and unnormalized; `routes/complaints.py` never rewrites it) and `am/pm_window_start/end_utc` (`routes/schools.py:47-50` — `HH:MM` clock times, not instants). Read `validate.py` to confirm `req_datetime` returns a parsed value that these two callsites discard. Confirmed `domain.py` imports `fmt_dt` but never calls it, and `fmt_dt(None)` returns `None` so nullable stamps (`published_at` on a DRAFT, `current_offer_expires_at` when no offer stands) stay null.
- (c) Adjustments made: (1) scoped the universal to "every UTC instant the server itself **renders**" rather than "every timestamp in a response body", so client-echoed `occurred_at` is not falsely swept in, and added the explicit `occurred_at` exception sentence; (2) used "instant" rather than "timestamp"/"stamp" so `fmt_date` fields (`session_start_date`, `crash_date`, `certified_on`, `absence_date`, `count_window_start`, ...) and the `HH:MM` school-window fields are untouched by the claim; (3) listed `shift_start_utc` in the *serialization* sentence only, deliberately not appending it to the PRD's pre-existing "derived from that clock's current value" list, since `_pinned_shift_start` (`routes/absences.py:102-113`) derives it from `absence_date` + the school's shift window, not from the clock.

**Edit 2 — §2.5 `updated_at` digit count**
- (a) Subject: the fractional-digit count on `updated_at` specifically.
- (b) Paths enumerated: grepped `updated_at` across all of `implementation/` — only four hits, all in `db.py` (`:56` initial value copied from the same `stamp` as `created_at`, `:83` the already-touched-this-request branch, `:88` the first-touch branch), every one of them `fmt_dt(now())`. No route module writes `updated_at` directly, so there is no divergent path.
- (c) No adjustment needed — the added clause is identical in form to the wording `created_at` already carries on the preceding line, and all three writers produce that format.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` yields 4 diff lines (2 revised lines) — the file is NOT byte-identical to PRD.md, both are 436 lines, and PRD_FINALIZED.md still ends on the final `ERR_CLOCK_MOVED_BACKWARD` catalogue row.

## Step 9: Complete PRD — 2026-09-03T13:32:16.265Z

Run as **three sequential file-partitioned passes** over `implementation/` (a single one-shot scan risks producing a PRD_COMPLETED.md byte-identical to its source, i.e. a scan that never happened). Each pass edited the SAME `workspace/PRD_COMPLETED.md` with targeted Edit calls only.

### Pass 1 — core + schools/intersections/studies (`app.py`, `auth.py`, `db.py`, `errors.py`, `response.py`, `timeutil.py`, `validate.py`, `routes/schools.py`, `routes/intersections.py`, `routes/studies.py`)

PRD_FINALIZED.md 436 lines / 102,534 chars -> PRD_COMPLETED.md 436 lines / 112,718 chars (+10,184 chars, 0 new lines, no new sections). **24 ambiguity-pins, 4 mismatch-revisions.**

- §2.1 — insert — ambiguity — header values are trimmed; whitespace-only counts as empty; padded role names still match — `auth.py:26-31`
- §2.1 — revise — **mismatch** — PRD claimed `SchoolLiaison`'s `X-User-ID` is compared to `school_id`; no endpoint does. Pinned: absence filing and offer response are the *only* two identity comparisons in the service; everything else is role-only — `auth.py:35`, `routes/absences.py:60,248`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A-Z0-9` (24 total) — `response.py:13-14`
- §2.3 — insert — ambiguity — `created_at` ties broken by an internal monotonic creation sequence, never exposed as a field — `db.py:98-99,95`
- §2.3 — insert — ambiguity — `limit`/`offset` integer grammar (optional `-` + digits after strip; `10.0`, `1e1`, `+5`, empty rejected); offset >= total_count yields empty page, not an error — `validate.py:203-213`, `response.py:45-50`
- §2.3 — insert — ambiguity — filter values matched literally/case-sensitively, never enum-validated (unknown value -> empty page); unknown query params ignored — `validate.py:216-220`, `routes/intersections.py:92-93`
- §2.4 — insert — ambiguity — sub-millisecond precision truncated, not rounded, on render — `timeutil.py:13-16`
- §2.5 — insert — **mismatch** — PRD said `version` increments on *every* mutation; impl caps it at +1 per request per resource (with `updated_at` refreshed each step), and conditional recomputations that change nothing write nothing (grant-program balance is the exception) — `db.py:75-88`, `domain.py:163-166,184-187,222-233,408-413,444`
- §2.6 — insert — ambiguity — trailing slash tolerated; malformed vs. unknown ids treated alike — `app.py:22`, `domain.py:20-26`
- §2.7 — insert — ambiguity — GETs never mutate/recompute/bump versions (guard read the stated exception) — `routes/schools.py:70-94`, `routes/intersections.py:55-59`
- §2.8 — insert — ambiguity — two/four-decimal figures are JSON numbers, so `100.00` renders `100.0` — `calc.py:36-41`, `routes/schools.py:63`
- §2.10 band 3 — insert — ambiguity — JSON `null` == absent; undeclared body fields ignored; empty string accepted for required strings; absent/empty body = `{}`, non-object body rejected; integral floats satisfy int fields, booleans satisfy neither int nor number; strict `YYYY-MM-DD`, datetime accepts `Z`/offset/naive/bare-date, `HH:MM` exactly five chars — `validate.py:12-36,49-58,83-91,107-113`, `timeutil.py:25-71`
- §3.1 — revise — **mismatch** — `enrollment_count` was said to be a mode-share denominator; it is stored and read by nothing (weighted variant divides by `enrollment_at_survey`) — `routes/schools.py:25,44`, `calc.py:307-309`
- §3.1 — insert — ambiguity — all four `HH:MM` windows required and echoed zero-padded; no ordering/disjointness enforced; only the two *start* times are ever read — `routes/schools.py:30-33,47-50`, `routes/absences.py:105-108`
- §3.1 — insert — ambiguity — `no_school_dates`/`early_dismissal_dates` keep supplied order, may repeat, need not lie in the season — `validate.py:162-174`
- §3.1 — insert — ambiguity — `early_dismissal_pm_offset_minutes` accepts any integer, positive included, unbounded — `routes/schools.py:36`
- §3.1 — insert — ambiguity — `baseline_walk_bike_mode_share_pct` stored unrounded at supplied precision — `routes/schools.py:54,147`
- §3.2 — insert — ambiguity — `lanes_crossed` (no upper bound) and `posted_school_zone` feed no calculation — `routes/intersections.py:31-32,41-42`
- §3.2 — insert — ambiguity — `involved_school_age` unused; future `crash_date` accepted and simply outside every window — `routes/intersections.py:69`, `domain.py:391-401`
- §3.3 — insert — ambiguity — `observed_minutes`/`adult_count` feed no term (no per-minute normalisation); duplicate `(session_date, period)` allowed and each counts once — `routes/studies.py:88-92,140-142`
- §3.3 — insert — ambiguity — `engineer_note` validated as a string then discarded, never persisted — `routes/studies.py:171`
- §3.3 — insert — ambiguity — `latest_warrant_score` selection ties broken toward the later-created study, and `warrant_status` is overwritten by the just-finalized study even when a newer one exists (the two fields can disagree) — `routes/studies.py:186-187,202-211`
- §3.3 — insert — ambiguity — reopening touches only study + intersection: posts stay `SUSPENDED`, assignments `VACATED`, guards `UNASSIGNED`, school posture and route holds untouched — `routes/studies.py:214-244`
- §3.8 (filing only) — insert — ambiguity — `occurred_at` must parse but is stored verbatim and unconstrained vs. the clock; omitted `reporter_contact` stores null — `routes/intersections.py:127-131,140`
- §3.9 — insert — ambiguity — `classrooms_reporting` unused; `survey_date` unconstrained; `term_code` may repeat — `routes/schools.py:101-103`
- §3.9 — insert — ambiguity — latest-survey ties on both `survey_date` and `recorded_at` resolve to the later-appended entry — `routes/schools.py:138-141`
- §4 (3 rows) — revise — ambiguity — intersection `warrant-studies`, `guard-posts` and `complaints` list endpoints accept an optional `status` filter that the table omitted — `routes/intersections.py:88,101,113`
- §5 preamble — insert — **mismatch** — catalogue claimed exhaustiveness; pinned the two HTTP-layer rejections outside it: unrouted path -> 404 `ERR_NOT_FOUND`, bad method -> 405 `ERR_INVALID_REQUEST`, both in the standard envelope — `app.py:32-44`

Verified §5's 59 rows match `errors.ERROR_STATUS` exactly in both directions, and §4 role lists match every `require(...)` in the three route modules. Left unpinned (with reasons): intra-band-3 field validation order (unobservable — same `error_id`), the defensive 500 catch-all (`app.py:46-48`, unreachable), dead `validate.reject_unknown_version_field`, and the `advance_clock`/guard-read specifics owned by pass 2.

### Pass 2 — workforce/duty/coverage (`routes/guards.py`, `routes/posts.py`, `routes/absences.py`, `routes/clock.py` + the reliability/cost/coverage parts of `calc.py`/`domain.py`)

112,718 -> 118,058 chars (+5,340), still 436 lines, no new sections. **16 ambiguity-pins, 5 mismatch-revisions** (17 Edit calls). Verified via an in-process Flask test client (no port bound, no process to kill).

- §2.4 — insert — ambiguity — clock is repositioned *before* the walk, so every `updated_at` the sweep writes carries the new instant — `domain.py:483-487`
- §2.4 — insert — ambiguity — an accepted call naming the clock's current instant still sweeps (verified `activated_assignment_count` 1 on a no-move call) — `routes/clock.py:21`, `domain.py:483`
- §2.4 — insert — ambiguity — both tests run in one pass, so an assignment whose whole window is already past goes `SCHEDULED -> ACTIVE -> ENDED` in one call and is counted in **both** totals with `version` +1 only — `domain.py:494-502`
- §2.4 — insert — ambiguity — the ending release leaves an `ON_LEAVE` guard where they are — `domain.py:260-261`
- §3.4 — insert — ambiguity — both hour counters carry the exact decimal sum (verified 1 + 0.1 + 0.2 = 1.3), and `training_date`/`curriculum_code` are discarded — a guard has no training ledger — `routes/guards.py:67-77`
- §3.4 — revise — **mismatch** — dropped "the reliability floor is checked before the training-hours gate" (the three status gates are mutually exclusive branches) and pinned that the equipment gate runs **last**, so short-hours + no-equipment reports `ERR_TRAINING_HOURS_INSUFFICIENT` — `routes/guards.py:114-135`
- §3.4 — insert — ambiguity — which variants each occasion recomputes: read / training / absence-create-cover-withdraw recompute both; clock advance and the reinstatement gate recompute rolling only — `routes/guards.py:59,80,120`, `domain.py:517`
- §3.5 — insert+revise — ambiguity+**mismatch** — new assignment also starts with `vacated_reason` null; "coverage_status moves from UNSTAFFED to COVERED" softened to the §2.7 recomputation, which stays `UNCOVERED` when any absence on the post is still open — `routes/posts.py:132-143`, `domain.py:169-187`
- §3.5 — insert — ambiguity — overlap runs first and spans every post, so supersession's incumbent is always a *different* guard (verified same guard -> `ERR_ASSIGNMENT_OVERLAP`); every live conflicting incumbent is resolved — `routes/posts.py:114-123,161`
- §3.5 — revise — **mismatch** — terminal states release the guard **unless** they are `ON_LEAVE`, and truncation releases nobody — `domain.py:255-265`, `routes/posts.py:177-181`
- §3.6 — revise+insert — **mismatch**+ambiguity — `early_dismissal_pm_offset_minutes` is a *signed* offset (default -120 moves earlier, positive moves later; AM/BOTH never displaced); `notice_hours` is the full-precision seconds/3600 quotient, not 2-dp (verified 70 min -> 1.1666666666666667) — `routes/absences.py:102-113,67-68`
- §3.6 — insert — ambiguity — `note` is stored/returned null when omitted — `routes/absences.py:33`
- §3.6 — insert — ambiguity — clock exactly at `current_offer_expires_at` counts as still live; dispatch never re-examines the parent assignment, so a report on an `ENDED`/`VACATED`/`SUPERSEDED` assignment stays dispatchable — `routes/absences.py:154-164`
- §3.6 — insert — ambiguity — the busy test consults live assignments only: a candidate's own absences and substitute duty already accepted elsewhere are ignored, so one guard can cover two reports on one day — `routes/absences.py:223`, `domain.py:455-473`
- §3.6 — insert — ambiguity — candidates sharing a `created_at` are settled by §2.3's creation sequence, earlier-enrolled first — `routes/absences.py:233`
- §3.6 — revise — **mismatch** — `UNCOVERED_GAP` is also reachable from a lapsed `OFFER_OUT`, with the `EXPIRED` rewrite / exclusion / offer-pointer clearing still applied before the empty pool is found — `routes/absences.py:166-179`
- §3.6 — insert — ambiguity — `ACCEPT` writes nothing to the substitute (duty status, assignments, reliability untouched); only the absent guard's figures are recomputed — `routes/absences.py:269-283`
- §3.6 — insert — ambiguity — withdrawal never unwinds a reliability suspension; the guard stays `SUSPENDED` with assignments `VACATED` until explicit reinstatement — `routes/absences.py:306-311`
- §4 preamble — insert — ambiguity — role membership is the only check on a read: a `CrossingGuard` may read any guard, assignment or absence report (verified 200 for a foreign guard); the two identity tests apply to writes only — `routes/guards.py:55`, `routes/posts.py:186`, `routes/absences.py:118`

Left unpinned (with reasons): failed reinstatement leaving a recomputed rolling score unversioned (unobservable — every read recomputes); terminal assignments' `coverage_state`/`open_absence_count` not recomputed (values identical either way); intra-helper ordering; post `open_gap_count` counting absences on terminal assignments (already covered by §2.7); pass-1/3 owned prose.

### Pass 3 — routes/hazard/complaint/grant (`routes/walking_routes.py`, `routes/complaints.py`, `routes/grants.py` + hazard/benefit-cost/balance parts of `calc.py`/`domain.py`)

118,058 -> 120,678 chars (+2,620), still 436 lines, no new sections. **10 ambiguity-pins, 1 mismatch-revision.** Changes confined to lines 159, 275, 281, 289, 291, 295, 297, 299, 301, 303 — passes 1/2 edits untouched.

- §3.7 ¶1 — insert — ambiguity — stored `segments` normalized to ascending `segment_order`, not submission order — `routes/walking_routes.py:76`
- §3.7 ¶4 — insert — ambiguity — publish-while-`SUSPENDED`: runs *after* supersession, sets `hold_reason=SCHOOL_COVERAGE_SUSPENDED`, keeps the `published_at` it just got, response reports `ADVISORY_HOLD`, prior same-code route still retired, `version` still +1 — `routes/walking_routes.py:119-139`
- §3.8 ¶3 — insert — ambiguity — on `REFER_TO_ENGINEERING` the intersection is not written at all (no `updated_at`/`version` move) — `routes/complaints.py:40-44`
- §3.8 ¶4 — insert — ambiguity — `fiscal_year` is any integer, never range-checked nor cross-checked against the deadline — `routes/grants.py:27`
- §3.8 ¶6 — insert — ambiguity — scoring derives the crash total on the spot, ignores stored `crash_severity_points`, writes nothing back — `routes/grants.py:145-146`
- §3.8 ¶7 — insert — ambiguity — the benefit/cost division consumes the already-rounded 4-dp `benefit_points` and `cost_factor` — `calc.py:293-294`, `routes/grants.py:150-157`
- §3.8 ¶8 — insert — ambiguity — `award_note` must be a string when present but is never persisted and appears in no response — `routes/grants.py:175`
- §3.8 ¶8 — revise — **mismatch** — PRD called `created_at` the "terminal tie-break"; impl adds the §2.3 monotonic creation sequence as a fourth key, so ranking is total and the later-created of an otherwise-identical pair is refused (verified `ERR_PROJECT_NOT_TOP_RANKED`) — `routes/grants.py:163-167`
- §3.8 ¶9 — insert — ambiguity — balance recomputed wholesale from the project set and always stamps the program (closes pass 1's dangling §2.5 forward-reference) — `domain.py:433-444`
- §3.8 ¶10 — insert — ambiguity — a re-award overwrites `funded_at` and leaves `withdrawal_reason` in place; a reopened complaint keeps its `referred_project_id` — `routes/grants.py:197-199,232,247-259`
- §2.11 — revise — ambiguity — the witnesses of a fund->withdraw round trip include the stored `withdrawal_reason`, not just program `version` + `funded_at` — `routes/grants.py:232`

**Final §4/§5 cross-check: clean.** Impl registers exactly 50 method+path pairs; the §4 table has exactly 50 rows, symmetric sets, and every row's Authorized Roles list matches the route's `require(...)` arguments (order included), resolved through the `READ_ROLES`/`PROGRAM_READ_ROLES`/`STUDY_LIST_ROLES`/`ROUTE_READ_ROLES` constants. §5 has 59 ids, identical to `errors.ERROR_STATUS` in both directions with identical statuses and order.

Left unpinned (with reasons): sub-check order inside one segment object (same `error_id`); `application_deadline` re-serialization (no-op given §2.10's date pin); withdrawal's state-check-vs-version-guard order and FK resolution order (already global in §2.10 bands 6/7 and §2.6); `_move_cited_complaint`'s unreachable no-op branch.

### Orchestrator verification

- `PRD.md` 436 lines / 101,673 B -> `PRD_FINALIZED.md` 436 / 102,534 B -> `PRD_COMPLETED.md` 436 / 120,678 B (+18.7% over PRD.md). `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 104 diff lines (52 revised lines) — **not** byte-identical, so the scan demonstrably ran.
- Heading count unchanged at 28 (no new sections were added by any pass), and the tail still ends on the final `ERR_CLOCK_MOVED_BACKWARD` catalogue row — no truncation.
- No `implementation/`, `test_suite/` or `test_helpers/` source file was modified after 12:49, and the green 8-round sweep ran at 12:53 — the 8x 96/96 evidence therefore covers exactly the artifacts now on disk. Steps 8 and 9 touched only PRD copies.
- Removed the `__pycache__` directories the verification passes left behind; `workspace/implementation/` holds source + the 8 `results.*.json` only (no DB/JSON/cache persistence).

PIPELINE COMPLETE.
