# Worklog — task_2748_digital_curriculum_rostering_single_sign_on

## Step 1: Create task directory — 2026-09-04T15:43:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2748_digital_curriculum_rostering_single_sign_on` and its `workspace/` subdirectory. Index 2748 was pre-assigned by the caller; no scan of ./tasks/ was performed and no index was auto-allocated.

## Step 2: Generate Scaffold — 2026-09-04T17:53:00.000Z

All three scaffold artifacts for task 2748 are complete and the linter is clean.

**Verdict block (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2748_digital_curriculum_rostering_single_sign_on/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2748_digital_curriculum_rostering_single_sign_on/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2748_digital_curriculum_rostering_single_sign_on/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  1292

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2748_digital_curriculum_rostering_single_sign_on/`):
- `SCAFFOLD.yaml` — 2654 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2003 lines, 18 instances (2 per §0.5 rule)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6168 lines, 92 instances (77 with full `test_recipe`, 15 `excluded_because` stubs citing §1.8 by name)

**What the scaffold defines**
- **11 entities** (`graph` topology): School, Term, Teacher, Student, Section, Enrollment, VendorApp, BuildingAllocation, AppAccount, SyncRun, ErrorQueueItem — `api_prefix: /rostering`, archetypes `workflow_orchestration` + `quota_allocation`, complexity layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, soft_delete_archival`, `immediate` consistency, logical clock via `POST /_clock/set_current_utc`.
- **7 state machines** (`parallel` shape): Term (PLANNED→ACTIVE→ROLLED_OVER with a 4-hop summer-rollover cascade), Student (withdraw / merge-duplicate, depth-4 cascade), Enrollment (PENDING_ADD/ACTIVE/PENDING_DROP/DROPPED with add-drop timing), VendorApp (DRAFT→ACTIVE→SUSPENDED/TERMINATED), AppAccount (independent seat axis, identity axis and password sub-state), SyncRun (EXTRACTED↔HELD↔TRANSFORMED→PUBLISHED/SUPERSEDED), ErrorQueueItem (match/merge/dismiss triage).
- **9 calculations**: `sync_scope_resolution`, `building_seat_allocation` (waterfall, pinned remainder ranking), `seat_admission_capacity` (BLOCK/POOL_FALLBACK), `sync_seat_charge` (dual variant PROVISIONAL_TRANSFORM/FINAL_PUBLISH + reconciliation), `license_invoice_projection`, `renewal_recommendation_score` (dual variant), `username_derivation` (SIS_ID/STATE_ID/EMAIL_LOCALPART, truncate-then-suffix), `password_lifecycle_evaluation`, `archived_access_window`.
- **45 validations** in 9 priority tiers, **2 OCC `concurrency_rules`** on `VendorApp.version`, **52 endpoints**, **54 error codes**, **5 roles** under `segregation_of_duties` (RosterOperator, DataGovernanceOfficer, VendorIntegrationManager, BuildingLicenseAdmin `entity_backed:School`, IdentityAdmin).

**Corner breadth by section**: entities 13, state_machines 16, calculations 14, validations 13, endpoints 7, errors 10, rbac 8, Cross-Cutting Complexity Layers 9, Consistency Model 2. Verified programmatically: all 54 error codes are triggered somewhere across §1.8+§1.9, all 52 endpoints are exercised, all `grounds` refs resolve into §1.1–§1.7, instance names are unique across both files, every stub cites a real §1.8 instance, and no instance has both `test_recipe` and `excluded_because`.

**Two fixes worth flagging**
1. `ERR_GRADE_BAND_OUT_OF_SCOPE` was unreachable as originally written (the priority-33 school-coherence check always fired first), so §1.4 priority 40 and the §1.6 catalog entry were rekeyed onto the subject's own band — `grade_band_of(Student.grade_level)` for students, `School.grade_band` for teachers — which makes the K-8-building case reachable. Existing fixtures were checked first and are unaffected.
2. Three `grounds` refs cited state machines the scaffold does not declare (Teacher, Section have status enums driven by endpoint side effects, not §1.2 machines); they were repointed at the declared endpoint/entity-field elements.
3. Per the recorded pipeline pitfall, the `Generate task harder than expert level!` directive line was stripped from `SCAFFOLD.yaml`'s `scenario:` key (the numbered scenario text itself is verbatim) so it cannot leak into PRD.md downstream.

**Orchestrator verification**: all three files present and non-empty; `grep "harder than expert" SCAFFOLD.yaml` returns nothing — directive did not leak.

## Step 3: Copy Shared Files — 2026-09-04T17:54:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T18:08:00.000Z

PRD generation for task 2748 is complete.

**Deliverable:** `workspace/PRD.md` — **444 lines**, last heading **`## 5. Error Code Catalogue`**, ending on the completed 54-row error table (final row `| ERR_DISTRICT_SEATS_EXHAUSTED | 409 |`), i.e. a real section boundary, not a mid-sentence truncation. Built with 11 chunked `cat >>` appends; no single giant Write.

**Sections written**
- §1 Introduction (3 paragraphs, pain-point framing, service mounted under `/rostering`)
- §2.1–§2.10: RBAC; API Response Structure (emitted byte-identical from `section-2.2-response-structure.md`); pagination/filtering/ordering; common properties, identifiers and the logical clock; path resolution and request-shape screening; OCC on the vendor license; the order in which a request is refused (the 45-rung ladder as nine tiers A–I); integer money/seats and rounding discipline; cascades, counters and derived fields; boundary conventions
- §3.1–§3.8: district backbone (buildings, password policy, term); staff and students; sections and the master schedule; add/drop and mid-year schedule change; vendor licenses, seat entitlement and building allocation; SSO identities (provisioning, passwords, usage, wind-down); the rostering pipeline (extract -> transform -> triage -> publish); summer rollover, archived-class access and the renewal decision
- §4 Endpoint Definitions (preamble on 201-for-create / 200-otherwise + 4-column table of all 52 endpoints)
- §5 Error Code Catalogue (2-column table of all 54 errors)

**Scaffold coverage (§1.1–§1.7)**
- §1.1: 11 entities, all 120 field names, with defaults/initial values stated
- §1.2: all 7 state machines — every transition, precondition, error id and side-effect hop, including the depth-4 withdrawal and rollover cascades and the `TRANSFORMED -> HELD -> TRANSFORMED` cycle
- §1.2.1: both concurrency rules, with `expected_vendor_app_version`, `ERR_STALE_VENDOR_APP_VERSION` and HTTP 412
- §1.3: all 9 calculations with pinned step orders, named constants and worked boundary examples (waterfall/proportional floor-then-remainder allocation, per-subject ceiling proration, tiered invoice projection, weighted renewal score with 70/40 floors, username truncate->strip->suffix, password lifecycle, archived-access window)
- §1.4: all 45 validations in explicit priority order with their `applies_to` scopes
- §1.5: all 52 endpoints; §1.6: all 54 errors; §1.7: all 5 roles with `identity:` translated (four opaque, `BuildingLicenseAdmin` entity-backed to `School`)

**Hard Contracts — all PASS** (mechanical re-verification after the final edit): entity fields 120/120; request bodies 71/71; query params 36/36; path params 11/11; computed-read output keys 27/27; error ids 54/54; roles 5/5; enum/state values 78/78; §3 path purity 0 violations across 1104 scanned backtick tokens; 0 fuzzy words.

Both withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced, and no sibling `task_*/` directory was read.

Four internal scaffold contradictions were resolved by writing the reading the hidden tests will assert while acknowledging the other: header naming (`X-User-Role` per SKILL.md over the scaffold's "X-Role"); `School.status` immutability vs. the building-closing PATCH; `Enrollment.effective_date` immutability vs. publish stamping `max(requested_effective_date, clock date)`; and `ERR_ACCOUNT_LOCKED` role-framing vs. LOCKED being terminal. Uniqueness constraints with no error id in the scaffold (`sis_school_id`, `building_code`, `sis_section_id`, `vendor_code`) and the `eligible_headcount_snapshot` reallocation guard were stated as data constraints rather than given invented error ids.

**Orchestrator truncation guard**: verified `tail -25` ends on the completed 54-row error table and all 5 top-level sections (§1–§5) plus subsections §2.1–§2.10 and §3.1–§3.8 are present. `grep -i "harder than expert|SCAFFOLD|test_recipe" PRD.md` returns nothing. Not truncated.

## Step 5: Generate Unit Tests — 2026-09-04T18:52:00.000Z

The suite is complete and verified.

## Output (task root, not `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2748_digital_curriculum_rostering_single_sign_on/`

**`test_helpers/` — 2,086 lines, 9 files:** `__init__.py` 31, `api_client.py` 326 (`RosteringApiClient` with one method per endpoint plus `set_clock`), `api_errors.py` 146 (all 54 `ERR_*` ids + `set_error_http_status_map`), `assertions.py` 282, `constants.py` 113, `factories.py` 269, `fixtures.py` 612 (five tiers, up to whole licensed districts and in-flight pipeline runs), `test_users.py` 96, `types.py` 211.

**`test_suite/` — 9,663 lines, 22 files, 143 tests:** `conftest.py` 44; `test_01` 215, `test_02` 425, `test_03` 205, `test_04` 255, `test_05` 352, `test_06` 257, `test_07` 521, `test_08` 378, `test_09` 436, `test_10` 519, `test_11` 904, `test_12` 642, `test_13` 536, `test_14` 761, `test_15` 905, `test_16` 472, `test_17` 475, `test_18` 188, `test_19` 497, `test_20` 523, `test_21` 153.

## Coverage — 95/95 design instances, zero skipped

- **Queue A (depth, §1.8): 18/18 instances -> 65 tests**, every instance carrying >=2 tests. By rule: dual_variant_calc 8, combinatorial_formula 5, non_linear_state_machine 12, transitive_cascade 6, priority_pair_validation_conflict 4, boundary_precision_check 7, cross_entity_state_dependency 11, resource_temporal_overlap 6, compensating_invariant 6.
- **Queue B (breadth, §1.9): 77/77 non-stub instances -> 78 tests** (one instance split into two genuinely independent outcomes). By section: entities 11, state_machines 14, calculations 11, validations 9, endpoints 7, errors 10, rbac 8, Cross-Cutting Complexity Layers 6 (5 instances), Consistency Model 2. All 15 `excluded_because:` stubs ignored with no placeholder, marker or xfail.

## Mechanical verification

143 tests collect under pytest; `py_compile` clean on all 31 `.py` files; `pyflakes` clean (no unused imports); every test has exactly one `Design:` tag as the final docstring line; all 143 tags resolve to a real `name:` in the correct yaml and none names a stub; no duplicate test function names; no `skip`/`xfail`/`TODO`; no occurrence of "scaffold", "corner design", "difficulty design", "claim_type" or any design-file reference; nothing written under `workspace/` (the implementation agent's tree is untouched); `worklog.md` untouched.

## Assertions narrowed on the two-condition filter (no instance dropped, but these claims were not PRD-derivable)

- **`primary_teacher_id` cleared by a staff separation** — dropped in the separation cascade and in the endpoint sweep; §3.2 sets only `roster_health`, and §3.7's `UNMATCHED_TEACHER` definition presupposes the pointer survives.
- **Run state after a duplicate merge** — §3.7 is self-contradictory (`HELD` in the merge paragraph vs. not-held for `DUPLICATE_STUDENT` items); only `blocking_error_count == 0` is asserted, and `sync_health == OK` after a merge was dropped for the same reason.
- **`unallocated_seats` after release cascades** — the design's `== 4` contradicts §2.9's identity (`total - Sum(allocated) - Sum(borrowed)`); asserted as `0` in the section-cancel and second-rollover tests.
- **Publish of a future-dated add** — the design expected `ACTIVE`; §3.7 pins `PENDING_ADD`, which is what is asserted.
- **Non-PRD fields** (`allocated_seats_total`, `free_seats`) and unobservable ordering claims (state-vs-SoD rung order on publish, role-vs-DRAFT order on activate) were dropped; two illegal enum literals in recipes (`CLEVER_LIKE_JSON`, `CLEVER_API`) were replaced with legal defaults since they were decorative.
- Weakest link worth a second look during Step 7: `password_state == EXPIRED` on *cascade*-driven deprovisions (pinned only indirectly, via §3.6's effect set plus §3.8's "suspension is not deprovisioning" contrast), and `ERR_SCOPE_VIOLATION` for a `BuildingLicenseAdmin` patching a nonexistent allocation (rests on §2.7's global ladder; the anti-enumeration rationale is spelled out only for the `VendorIntegrationManager` case).

## Step 6: Generate Implementation — 2026-09-04T18:56:00.000Z

Implementation complete and verified.

## Module layout
`workspace/implementation/`

| file | lines | role |
|---|---|---|
| `app.py` | 87 | Flask factory, blueprint registration, error handlers, `app.json.sort_keys = False`, `GET /_health`, `PORT` from env |
| `store.py` | 150 | logical clock (default `2026-08-01T00:00:00Z`), 11 in-memory dicts, id/`_seq`/stamp/touch helpers |
| `errors.py` | 88 | `ApiError` + full 53-entry error-id -> HTTP status map |
| `envelope.py` | 43 | `meta`/`response_type`/`data` envelope, list meta, error shape |
| `shape.py` | 223 | enum constants, typed field readers, pagination bounds, query coercion |
| `auth.py` | 75 | role admission, VIM/BLA scope binding, segregation of duties |
| `serial.py` | 131 | 11 field-order-pinned serialisers (internal `_seq`/`_vendor_app_id`/`_borrowed_seat` never emitted) |
| `calc.py` | 627 | the 9 calculations: scope resolution, proration, username derivation, seat/charge projection, allocation splits, renewal scoring, invoice, password policy, conflict rules |
| `cascade.py` | 278 | counter recomputes, seat release / identity deprovision, run holds, triage dedupe, license version bumps |
| `routes_reads.py` | 258 | 22 GETs (11 collections + 11 single) with archive gate and lazy password expiry |
| `routes_ref.py` | 364 | schools, terms (activate/rollover), teachers (separate), students (withdraw), `POST /_clock/set_current_utc` |
| `routes_roster.py` | 216 | sections (+cancel cascade), enrollments, drop |
| `routes_license.py` | 341 | vendor-apps, status machine, activate-license, allocation re-cut, roster-feed, renewal-summary |
| `routes_identity.py` | 216 | app-accounts, password-set, record-usage, release, deprovision |
| `routes_pipeline.py` | 389 | sync-runs, transform/triage, publish, resolve-match, merge-duplicate |
| `start.sh` (exec) | 10 | `cd` to own dir, guarded flask install, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |

3497 lines total. `python3 -m py_compile *.py` passes on all 15 modules; no file empty or truncated; `__pycache__` removed. Storage is module-level dicts only — a grep for `sqlite`, `open(`, `json.dump`, `/tmp` returns nothing, and nothing is seeded at import.

**Routes: 53 registered = the PRD's 52 endpoints + my own `GET /_health`** (the clock setter is one of the 52). All 11 entities have collection + single reads with `limit`/`offset` (limit > 100 correctly refused).

## Smoke-test result
Four scripted passes against `PORT=18748 bash start.sh`, then the process was killed by its exact PID (`1522256`, discovered via `ss -ltnp`) and port 18748 confirmed free. No pattern kill was used.

Every pinned numeric example in the PRD reproduces exactly:
- proportional split 7/7/1 of 10 seats -> **5, 5, 0** (fractional-part tie falling through to headcount desc); zero-headcount even split of 7 over 2 -> 4, 3; `FIXED_BUILDING_BLOCKS` waterfall 4 of 10 over 3 buildings -> 4, 4, 2
- projection/reconciliation fixture -> provisional **3 / 3000**, final **3 / 1812**, delta **-1188**; a single late seat charge of **604** cents (per-subject ceil)
- renewal boundary -> **70.00 RENEW** (util 0.8, engagement 0.5, cost/engaged 2000, efficiency 0.75); same license 40 days later -> **40.00 RENEGOTIATE** final vs **75.00 RENEW** provisional; invoice 1000 gross -> fee floor 25000, total 26000
- username derivation -> `vandenberghe.mwangi@apps.district.k12` then `vandenberghe.mwangi+2@...` (truncate-before-trailing-strip, suffix from 2), `EMAIL_LOCALPART` student `last.f`, `STATE_ID` run-replacement, `ERR_IDENTIFIER_UNAVAILABLE` for a null state id and for any `STATE_ID` teacher

Behavioural coverage confirmed: PENDING_ADD occupying a chair (capacity refusal), half-open-interval student conflict (same period only) vs one-period teacher buffer, HELD->resolve-match->TRANSFORMED loop with `ERR_BLOCKING_ERRORS_UNRESOLVED` in between, duplicate-student triage + merge (loser `MERGED_DUPLICATE`, clashing row dropped, headcount recomputed), publish landing adds at the publish date with both SoD guards, SKIP_SECTION advisory + `skipped_section_count`, POOL_FALLBACK borrowing with `borrowed_seats` decremented first on release, `ERR_BUILDING_ALLOCATION_EXHAUSTED` / `ERR_DISTRICT_SEATS_EXHAUSTED` / `ERR_ALLOCATION_BELOW_CONSUMED` / `ERR_ALLOCATION_EXCEEDS_LICENSE`, OCC via `expected_vendor_app_version`, release-vs-deprovision axis independence, lockout at the building threshold, refund rule keyed on the add/drop cutoff, rollover archiving with `ERR_ARCHIVE_WINDOW_CLOSED`, and the auth surface (401 / 403 role / 403 scope-before-existence / 404).

Two initial "mismatches" in my own script were expectation bugs, not implementation bugs, and I verified both against PRD §2.7: re-adding the same section reports `ERR_STUDENT_SCHEDULE_CONFLICT` (rung 31 precedes rung 37), while `ERR_DUPLICATE_ENROLLMENT` is reachable exactly when the intervals merely touch — both confirmed live.

**Orchestrator verification after Steps 5+6**: `test_helpers/` (9 .py) and `test_suite/` (22 .py) are at the task root, not under `workspace/`; no stray `test_*` directory exists under `workspace/`; `workspace/` holds only INSTRUCTION.md, PRD.md, implementation/; a single `worklog.md` exists at the task root. Steps 5 and 6 were launched in one assistant message so the impl generator could not see `test_suite/`.

## Step 7: Run Tests and Iterate — 2026-09-04T19:12:00.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2

**Iteration 1** — all 8 rounds identical: 139/143 passed, 4 deterministic failures (no flakiness; nothing load-induced).

**Tests deleted:** none. All 4 failures passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability).

**Fixes applied to `test_suite/`:**

- `test_suite/test_10_building_and_record_fundamentals.py` — `test_section_scheduling_rejects_unknown_subjects_periods_and_meeting_days`: its local `scheduling_attempt(**bad_fields)` closure passed `period_index=3` positionally-by-keyword *and* forwarded `**bad_fields`, so the `period_index=9` probe raised `TypeError: section_payload() got multiple values for keyword argument 'period_index'` before any request was issued. Rewrote the closure to merge `bad_fields` over a defaults dict, so the out-of-range probe now actually reaches the server. Also corrected the docstring's subject enum, which listed `WORLD_LANGUAGE`, `ARTS`, `PE_HEALTH` — members that do not exist in PRD §3.3 — to the PRD's verbatim `MATH`/`ELA`/`SCIENCE`/`SOCIAL_STUDIES`/`ELECTIVE`. The assertions themselves (400 + `ERR_INVALID_REQUEST`) were already PRD-faithful and were not weakened.

- `test_suite/test_17_concurrency_cascade_and_archival_layers.py` — `test_the_licence_version_moves_on_writes_to_three_generations_and_never_on_a_read`: assertion `recut["version"] == 2` mis-counted the *allocation's* generations. PRD §2.4 says version moves on "a counter recomputation, ... or a cascade reaching it", and §3.6 says provisioning increments "the allocation's `consumed_seats` ... by one". The allocation is minted at v1 by the split, reaches v2 when the test provisions an account against it, and so is at v3 after the re-cut. Corrected the expectation to 3 (STEP 2: assertion mis-translated the PRD sentence the test's own docstring cites). Verified against a manual replay: allocation trail is 1 -> 2 (provision) -> 3 (re-cut) -> 4 (release decrement).

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes_roster.py`, `drop_enrollment()` — the post-dated-drop branch (`ACTIVE` -> `PENDING_DROP`) skipped both counter recomputations, running them only when the row went straight to `DROPPED`. PRD §2.9 states `Section.active_enrollment_count` "is the number of enrollments of that section whose `roster_status` is `PENDING_ADD` or `ACTIVE` — `PENDING_DROP` and `DROPPED` rows are not counted", and §3.4 states "because a `PENDING_DROP` row leaves the section's `active_enrollment_count`, the chair becomes available immediately even though the license seat does not". The stale count made a pending departure keep occupying a chair. Moved `recompute_section_count` / `recompute_student_count` out of the `became_dropped` guard so they run on both branches; the seat-release cascade stays correctly gated on `DROPPED` only. `_apply()` is change-detecting, so the student's count (which *does* include `PENDING_DROP`) is untouched and its `version` does not spuriously move. This one bug caused two of the four failures (`test_09::test_a_third_period_class_on_untaken_days_is_not_a_double_booking`, `test_13::test_pending_departure_does_not_free_a_chair_but_the_drop_itself_does`).

**Iteration 2** — 8/8 rounds at 143/143. `worklog.md` was not touched.

**Orchestrator independent verification**: re-read all 8 `results.$i.json` directly (not sweep.log) — every round reports `passed=143 total=143 failed=0`, mtimes all within a 3-second window at 2026-09-04T19:11Z, so the artifacts are genuinely from one completed concurrent sweep rather than a stale or partial run. Step 7 made 1 `implementation/` fix, so Step 8's skip condition does not apply.

## Step 8: Finalize PRD — 2026-09-04T19:21:00.000Z

`PRD_FINALIZED.md` is created and is **byte-identical to `PRD.md`** (444 lines each, 0.0% delta, `cmp` clean). Every Step 7 item traced to a test-side or implementation-side bug against behavior the PRD already determines uniquely; there was no PRD silence and no PRD/impl mismatch to pin, so no edit was manufactured.

**Per-item adjudication (all three Step 7 items -> no edit)**

- `test_10` closure `TypeError` + docstring subject enum — pure fixture bug. Verified `implementation/shape.py:15-17` (`SUBJECTS = ["MATH","ELA","SCIENCE","SOCIAL_STUDIES","ELECTIVE"]`, `MEETING_DAYS`, `GRADE_BANDS`) and `routes_roster.py:37-40` (`req_int(period_index, 1, 8)`, `req_enum_array(meeting_days)`) against PRD §3.3/§2.5 — impl matches PRD verbatim; all three probes (unknown subject, `period_index=9`, `SAT`) yield 400 `ERR_INVALID_REQUEST` exactly as §2.5 rung 6 states.
- `test_17` `recut["version"] == 2` -> `3` — arithmetic bookkeeping slip in the test, not a PRD ambiguity. PRD §3.6 ("increments the allocation's counters") plus §2.4 ("a counter recomputation ... both `updated_at` and `version` move") uniquely gives allocation v1 (mint) -> v2 (provision) -> v3 (re-cut). The same test file's *other* re-cut test (`test_17...:175`, unchanged, `recut["version"] == 2` with no intervening provision) shows the author understood the rule and merely forgot the provision hop in this one scenario.
- `routes_roster.py:215-216` (`drop_enrollment`, counters moved out of the `became_dropped` guard) — genuine impl bug against PRD-determined behavior. §2.9 defines `Section.active_enrollment_count` as an invariant over `PENDING_ADD`/`ACTIVE` rows, and §3.4 states the chair "becomes available immediately" on a `PENDING_DROP`; the stale count violated the definition. The post-fix side effects (`section.version` moves because its count changed; `student.version` does not, because `PENDING_DROP` is inside the student's count and `cascade._apply` is change-detecting) are both what a literal reading of §2.9 + §2.4 produces, so nothing needed pinning.

**Pre-edit search log** (mandatory even with zero committed edits — three candidate edits were drafted and rejected)

1. Candidate: append a change-detection clause to §2.4 ("a recomputation leaving the value unchanged is not a mutation").
   - (a) Subject: whether a counter recomputation moves `updated_at`/`version` when the value is unchanged.
   - (b) Paths enumerated/read: `cascade.py:10-19` (`_apply`, change-detecting), all `_apply` callers — `recompute_school_headcount:25`, `recompute_section_count:34`, `recompute_student_count:43`, `recompute_allocation:64`, `recompute_run_counters:104`, `deprovision_identity:147`, `release_seat:154` (`force=True`), `hold_run:265`; plus the *non*-change-detecting `recompute_vendor:72-101` (unconditional `store.touch(vendor)`); plus every `recompute_*` callsite via grep across `routes_roster.py`, `routes_ref.py`, `routes_pipeline.py`, `routes_license.py`, `routes_identity.py`.
   - (c) Rejected: the clause would read across to `recompute_vendor`, whose license `version` bumps unconditionally (e.g. a zero-minute usage report, `routes_identity.py:177`), contradicting PRD §3.6's explicit "increments the license's `version`". Since the semantics is unobservable at the Step 7 site, the safer action was no edit.
2. Candidate: pin in §3.6 that the provisioning counter increment moves the allocation's own `version`.
   - (a) Subject: allocation `version` movement.
   - (b) Paths enumerated/read: `routes_identity.py:120` -> `cascade.recompute_vendor` -> `recompute_allocation` (bumps only the allocation whose counters actually changed, so sibling allocations of the same license do not move); `routes_license.py:243` (re-cut, unconditional `store.touch(allocation)`); activation split (allocations minted at v1); release/cascade paths `cascade.release_seat:154-173`.
   - (c) Rejected as PRD-determined (§3.6 + §2.4); also, stating it only at the provisioning site risked an expressio-unius narrowing that would wrongly exempt the release and cascade paths, which do bump.
3. Candidate: make §3.4's post-dated-drop sentence say explicitly that the section's count is recomputed on the spot.
   - (a) Subject: counter recomputation on transitions into `PENDING_DROP`.
   - (b) Paths enumerated/read: `routes_roster.py:209-219` (explicit drop, both branches), `routes_roster.py:100-124` (section cancellation), `routes_ref.py:321-347` (withdrawal cascade — `recompute_section_count` runs for both the `DROPPED` and the `PENDING_DROP` outcome, `routes_ref.py:328-337`), `routes_pipeline.py:210-232` (publish add/drop landings).
   - (c) Rejected: PRD §2.9's definition is already an invariant and §3.4 already states the chair frees immediately; the clarification would restate, not pin, so it would be a manufactured edit.

**Orchestrator note**: a byte-identical `PRD_FINALIZED.md` is accepted here. Step 7's single `implementation/` fix moved the *implementation* into conformance with a rule PRD already pins uniquely (§2.9's counter invariant), which is the one shape of impl fix that legitimately implies no PRD patch. Step 9 still runs in full and must not be identical.

## Step 9: Complete PRD — 2026-09-04T19:57:00.000Z

Run as **four sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (orchestrator decision, recorded here per the autonomy directive): a single subagent cannot hold 3,497 lines of implementation plus a 444-line PRD in one context without the scan degrading into a skim, and a byte-identical PRD_COMPLETED.md is the known failure mode of that degradation. Pass 1 did the `cp` and owned the cross-cutting layer; passes 2-4 were explicitly forbidden from copying so they could not clobber earlier edits. Partition: (1) app/store/errors/envelope/shape/auth/serial/start.sh, (2) calc/cascade, (3) routes_ref/routes_roster/routes_reads, (4) routes_license/routes_identity/routes_pipeline.

**Totals across the four passes: 83 edits — 66 ambiguity-pins, 17 mismatch-revisions.** Source `PRD_FINALIZED.md` 444 lines / 112,113 bytes -> `PRD_COMPLETED.md` 444 lines / 142,734 bytes (+30,621 bytes, +27.3%; 116 diff lines, 58 lines changed). All edits in-paragraph — no new sections, no new paragraphs, no line-count change.

### Pass 1 (infra: app, store, errors, envelope, shape, auth, serial, start.sh) — 12 pins, 1 revision
Verified clean, no change needed: the 54-entry error-id -> HTTP status map in §5 matches `errors.py` exactly (checked programmatically, no extras either way); every enum vocabulary in `shape.py` matches PRD prose; `auth.py` scope binding guards exactly the five operations §2.7 rung 3 names; every field emitted by the 11 serialisers is a PRD-named field.
- §2.1 ¶1 — insert — ambiguity — whitespace-only header counts as blank; unauthenticated `GET /_health` answers a bare `{"status":"ok","now":...}` outside the envelope — app.py:75-77, auth.py:36-39
- §2.1 ¶4 — insert — ambiguity — ownership check precedes path resolution, so an unknown allocation id yields `ERR_SCOPE_VIOLATION`, never `ERR_BUILDING_ALLOCATION_NOT_FOUND` — auth.py:64-69
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars A-Z0-9, minted per response, never echoed — store.py:102-104
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, so responses between clock moves share it — envelope.py:7-13
- §2.2 — insert — ambiguity — pagination meta on list responses only; single-object/computed responses carry two meta fields and `response_type` `"object"` — envelope.py:17-34
- §2.3 ¶1 — insert — ambiguity — `limit`/`offset` decimal integers, out-of-range/non-integer **refused** with `ERR_INVALID_REQUEST` (not clamped), empty value = omitted, offset unbounded; created_at ties broken by server creation sequence — shape.py:169-188, store.py:148-150
- §2.3 ¶2 — insert — ambiguity — filters exact-equality, no case folding/partial match, empty value ignored, unknown params ignored, `school_year`/`grade_level` integer-coerced, no-match = empty page not 404 — shape.py:191-206
- §2.3 ¶3 — insert — ambiguity — `include_archived` boolean vocabulary (`true/1/yes`, `false/0/no`, case-insensitive; else 400; absent = false); `limit`/`offset` ignored on computed reads — shape.py:208-217
- §2.4 ¶1 — insert — ambiguity — id is canonical lower-case hyphenated uuid4; `created_at == updated_at` at birth; `id` first and `created_at`/`updated_at`/`version` last, keys never alphabetised, internal sequence never emitted, declared fields always present as `null` when unset — store.py:98-99,130-138, serial.py:81-87
- §2.4 ¶2 — revise — **mismatch** — PRD implied client instants need three fractional digits; impl accepts 0-9 digits, `Z` or `±HH:MM` (normalised to UTC), lower-case `t`/`z`, surrounding whitespace, while dates stay strict `YYYY-MM-DD` — store.py:20-24,45-95
- §2.4 ¶3 — insert — ambiguity — default clock emitted as `...T00:00:00.000Z`, re-settable both directions, store empty at boot, restart resets both; `start.sh` conditional install, single-threaded, no debug/reloader, `PORT` env default 8000 — store.py:16, app.py:84-87, start.sh:1-10
- §2.5 ¶1 — insert — ambiguity — path ids matched as opaque strings; trailing slash insignificant; unknown path -> `ERR_INVALID_REQUEST` 404, undefined method -> `ERR_INVALID_REQUEST` 405, both ahead of authentication — app.py:28,46-53
- §2.5 ¶2 — insert/revise — ambiguity — enum comparison exact and case-sensitive; JSON `null` counts as absent; empty string refused; integers must be JSON integers (no bool/float/numeric string), ranges inclusive; selection arrays keep client order; undeclared body keys ignored; absent/empty/`null` body read as `{}`; non-object JSON body -> 400; `Content-Type` not examined — shape.py:34-115,140-153

### Pass 2 (calc.py, cascade.py) — 14 pins, 4 revisions
- §2.9 — revise — mismatch — cascade counter writes are change-detected: a recompute landing on the held value moves neither `updated_at` nor `version`; the `VendorApp` derived block is the sole exception (recomputed whole, version always bumped) — cascade.py:10-19, 72-101
- §3.2 — revise — mismatch — a run in `EXTRACTED` (not only `TRANSFORMED`) is parked in `HELD`; an already-`HELD` run stays `HELD` with both projected figures nulled — cascade.py:265-270
- §3.2 — insert — ambiguity — separation also stamps the teacher's accounts `password_state` `EXPIRED` and `deprovision_scheduled_date` = `separation_effective_date`; only non-`DEPROVISIONED` accounts touched; seat axis and license counters unmoved — cascade.py:147-151
- §3.4 — insert — ambiguity — the other enrollment's interval runs from its stamped `effective_date` to `drop_effective_date` (else that section's term `end_date`); the other section's status and term are not consulted — calc.py:591-600
- §3.5 — insert — ambiguity — registration order is the final candidate tie-break; one allocation row per candidate in candidate order — calc.py:322-323
- §3.5 — revise — ambiguity — registration order is the final tie-break in the proportional leftover ranking — calc.py:359-364
- §3.5 — revise — ambiguity — termination refund read against the **clock date**; `password_state` `EXPIRED`, `deprovision_scheduled_date` = clock date — cascade.py:154-170 / routes_license.py:156
- §3.6 — revise — ambiguity — mixed case means one **ASCII** `a`-`z` and one `A`-`Z`; cased letters outside those ranges satisfy neither half — calc.py:548-549
- §3.6 — revise — ambiguity — `borrowed_seats` drops only when the released account is itself the borrower; the borrow flag is per-account at admission and never re-attributed — cascade.py:64-69
- §3.6 — insert — ambiguity — `password_state` goes to `EXPIRED` from `LOCKED` too; `deprovision_scheduled_date` overwrites an earlier cascade's date — cascade.py:147-151
- §3.7 — revise — ambiguity — `ROLLOVER` admits `ARCHIVED` alone; the feed's `include_archived` **widens** to `ACTIVE`+`ARCHIVED` rather than replacing; creation order is the final section tie-break — calc.py:179-202
- §3.7 — insert — ambiguity — creation order is the final enrollment tie-break; in-scope students inherit the enrollment order — calc.py:211-233
- §3.7 — insert — ambiguity — items dedupe on (`category`, `source_ref`) per run against still-`OPEN` items only; the existing item is left untouched; a resolved/dismissed item never suppresses a fresh one — cascade.py:231-262
- §3.7 — revise — ambiguity — merge refund read against the **clock date**; `password_state` `EXPIRED`, `deprovision_scheduled_date` = clock date — cascade.py:154-170 / routes_pipeline.py:377
- §3.7 — revise — mismatch — the priced population and each student's charge date are taken over **feed** enrollments, so a `SKIP_SECTION` section cannot contribute a date — calc.py:285-296
- §3.7 — revise — mismatch — `name_format` shapes student subjects only; a teacher's display name is its stored `full_name` raw — calc.py:159-167
- §3.8 — insert — ambiguity — rollover refund read against the **clock date** rollover runs at, not the term `end_date`; `deprovision_scheduled_date` untouched — cascade.py:154-170 / routes_ref.py:158
- §3.8 — insert — ambiguity — cost efficiency is 1 when something is engaged but cost per engaged seat is <= 0; the stored pair always uses the **final** basis, re-scored by amendments (price-only included) but not by transforms, and stays populated once any account exists — calc.py:420-429, cascade.py:94-99

### Pass 3 (routes_ref.py, routes_roster.py, routes_reads.py) — 15 pins, 7 revisions
- §2.4 — insert — ambiguity — clock-set response `data` is an object with the single field `now`, re-normalised to 3 fractional digits + `Z` — routes_ref.py:364
- §2.7 rung 27 — revise — mismatch — rung admitted `start == end`; impl requires `end` strictly after `start` for `ERR_TERM_DATE_ORDER` — routes_ref.py:82
- §3.1 — revise — mismatch — `sis_school_id`/`building_code` are **not** enforced unique (rung 36 covers student/staff only) — routes_ref.py:21-43
- §3.1 — revise — mismatch — amendment `status` accepts `ACTIVE` **and** `CLOSED`, so a `CLOSED` building can be reopened — routes_ref.py:51
- §3.1 — insert — ambiguity — amendment fields all optional (omitted/null leaves stored value), a `CLOSED` building is still amendable, an empty amendment still bumps `version` — routes_ref.py:52-67
- §3.1 — revise — mismatch — `instructional_days` is stored/echoed only and enters no computation; proration uses the calendar-day span — routes_ref.py:91, calc.py:47
- §3.2 — insert — ambiguity — teacher `sis_staff_id` 1-32, `full_name` 1-120, `email` 3-160 with the at-sign neither first nor last char, screened at rung 6 before `school_id` resolves; email not unique — routes_ref.py:175-180
- §3.2 — insert — ambiguity — student `sis_student_id` 1-32, names 1-60, `state_student_id` 1-32, `date_of_birth` unvalidated against the clock — routes_ref.py:262-267
- §3.2 — insert — ambiguity — `separation_effective_date` constrained only to being a valid date — routes_ref.py:205
- §3.2 — insert — ambiguity — separation keeps the section's `primary_teacher_id` pointing at the separated teacher; an already-`UNMATCHED_TEACHER` section is untouched; the run scope used is the **in-scope** set, never the `SKIP_SECTION`-narrowed feed set — routes_ref.py:216-236
- §3.2 — insert — ambiguity — withdrawal's term-window test counts `PENDING_ADD`/`ACTIVE`/`PENDING_DROP` rows; the student record is written exactly once with its own count recomputed, so a post-dated withdrawal leaves it non-zero — routes_ref.py:304-346
- §3.2 — insert — ambiguity — withdrawal hop 3 also sets `password_state` `EXPIRED` — cascade.py:165 via routes_ref.py:351
- §3.2 — insert — ambiguity — `WITHDRAWN`/`MERGED_DUPLICATE` students are served ungated by both list and single read — routes_reads.py:97-112
- §3.3 — revise — mismatch — `sis_section_id` uniqueness not enforced; `sis_section_id` 1-64, `course_code` 1-32 — routes_roster.py:35-36
- §3.3 — revise — mismatch — `ARCHIVED` sections are **not** read-only (no status precondition on PATCH); `status: ARCHIVED` is rung-6 `ERR_INVALID_REQUEST`; `primary_teacher_id` can never be cleared; `max_seats` may drop below the live count; no period-conflict re-check; the cancel cascade fires only on the actual transition into `CANCELLED`, stamps the clock date only on rows lacking a `drop_effective_date`, recomputes both counter families, refunds against the **clock date**, identity axis untouched — routes_roster.py:78-125
- §3.4 — revise — mismatch — both `active_enrollment_count` figures recompute on an add whichever status the row lands in — routes_roster.py:185-186
- §3.4 — insert — ambiguity — the section's own `status` is not an add precondition (gate is on the term), so a `CANCELLED` section of an `ACTIVE` term accepts adds — routes_roster.py:138-164
- §3.4 — insert — ambiguity — a future-dated drop lands `PENDING_DROP` from `PENDING_ADD` as well as `ACTIVE`, both counters recompute on either branch — routes_roster.py:22, 215-216
- §3.6 — insert — ambiguity — the lazy expiry write advances the account's `updated_at`/`version` on a plain GET; the collection read does not evaluate expiry, so its `password_state` filter matches stale stored values — routes_reads.py:215-216
- §3.8 — insert — ambiguity — rollover recomputes each archived section's and each affected student's count, and reaches **student** accounts only (teacher seats survive the summer) — routes_ref.py:150-153, cascade.py:198
- §3.8 — insert — ambiguity — rollover sets `identity_status` `SUSPENDED` whatever the axis previously held, an already-`DEPROVISIONED` seat-holding account included — routes_ref.py:158, cascade.py:168
- §3.8 — insert — ambiguity — the archive gate applies to the **single**-section read only (after the 404 resolves); the sections collection keeps listing `ARCHIVED` sections either way — routes_reads.py:117-137

### Pass 4 (routes_license.py, routes_identity.py, routes_pipeline.py) — 25 pins, 5 revisions
- §2.5 — insert — ambiguity — activate-term, rollover, activate-license and release declare no input field and do not screen the body at all; transform and publish do — routes_license.py:177-184, routes_identity.py:182-189, routes_pipeline.py:104,191
- §2.6 — insert — ambiguity — `expected_vendor_app_version` is a JSON integer >= 1; missing/non-integer/non-positive is rung-6 `ERR_INVALID_REQUEST`, never a 412 — routes_license.py:221, routes_identity.py:36
- §2.7 rung 16 — revise — mismatch — impl tests `SUPERSEDED` *before* the state check, so a `SUPERSEDED` run never reports `ERR_SYNC_RUN_STATE_INVALID`; rung 16 now carves that out and defers to rung 17 (rung numbers preserved) — routes_pipeline.py:105-109,192-196
- §3.5 — revise — ambiguity — `vendor_code` uniqueness expected but unenforced; a repeat mints another license — routes_license.py:34
- §3.5 — insert — ambiguity — activation answers with the license record, not the allocations — routes_license.py:209
- §3.5 — revise — mismatch — `eligible_headcount_snapshot` is written once and never read back; a re-cut is judged against `total_seats`/`consumed_seats`, not the snapshot — routes_license.py:200, serial.py:53
- §3.5 — revise — ambiguity — re-cut `allocated_seats` range is 0-100000 — routes_license.py:220
- §3.5 — insert — ambiguity — a re-cut equal to the stored figure still moves both versions (guards skipped, write not change-detected) and answers with the allocation — routes_license.py:241-248
- §3.5 — insert — ambiguity — status machine: `"DRAFT"` target is rung-6 `ERR_INVALID_REQUEST`; re-suspend is a version-only no-op; resume guard compares the amendment's own `total_seats` before any write; full `ALREADY_ACTIVATED`/`NOT_ACTIVE` enumeration; an empty amendment still bumps `version` — routes_license.py:110-137,169-173
- §3.5 — insert — ambiguity — termination dismissals stamp `resolved_at` only (`resolved_by_user_id`/`resolution_note` null), `sync_health` untouched, one version bump for the whole termination — routes_license.py:148-173
- §3.6 — insert — ambiguity — seat admission consults the license's live `overage_policy`, never the allocation's `hard_cap` snapshot — routes_identity.py:86-93
- §3.6 — insert — ambiguity — `new_password` is 1-128 chars as request shape, refused at rung 6 before policy — routes_identity.py:130
- §3.6 — insert — ambiguity — usage report field ranges/defaults; `activity_date` compared against nothing — routes_identity.py:155-158
- §3.6 — insert — ambiguity — the lockout threshold is compared on *every* report and is the last word on `password_state`; the whole report is one write — routes_identity.py:170-176
- §3.6 — insert — ambiguity — deprovision re-scores the renewal pair and bumps the license `version` while seat counters stay put — routes_identity.py:215
- §3.7 — insert — ambiguity — a new run's three count fields are born at zero, not null — routes_pipeline.py:82-84
- §3.7 — insert — ambiguity — pre-emption dismissals stamp `resolved_at` with the clock instant — routes_pipeline.py:66-70
- §3.7 — insert — ambiguity — triage works the four categories in listed order, each in subject scope order, fixing item creation/listing order — routes_pipeline.py:120-163
- §3.7 — insert — ambiguity — with 3+ students on one duplicate key the single item names the earliest two only — routes_pipeline.py:140-147
- §3.7 — revise — mismatch — `SEAT_SHORTFALL` capacity counts positive spare over *every* allocation of the license, in-scope or not — routes_pipeline.py:32-40,158
- §3.7 — revise — mismatch — `transformed_record_count` is recomputed on the `HELD` branch as well as the `TRANSFORMED` one; only the projected figures are branch-dependent — routes_pipeline.py:168
- §3.7 — revise — ambiguity — `resolution_note` is 1-500 chars on both triage verbs — routes_pipeline.py:268,314
- §3.7 — insert — ambiguity — resolve-match writes no license at all: `sync_health` and `version` stay as the last transform/separation left them — routes_pipeline.py:293-304
- §3.7 — revise — ambiguity — merge names `ERR_STUDENT_NOT_ENROLLED` for both survivor and loser, both checks following the rung-34 pairing guard — routes_pipeline.py:334-337
- §3.7 — insert — ambiguity — merge recomputes each lending section's count, the survivor's count, and the loser's own count on the single `MERGED_DUPLICATE` write — routes_pipeline.py:363-372
- §3.7 — revise — ambiguity — merge recomputes the counters of *each* owning license once per seat released, bumping that license's `version` each time; `sync_health` untouched — routes_pipeline.py:374-379, cascade.py:154-173
- §3.7 — revise — mismatch — merge does reach sections (through the recomputed count); the old "and no section" claim was false — routes_pipeline.py:363-364
- §3.7 — revise — ambiguity — publish leaves dismissed items' `resolution_note` as it was and recomputes the run's two error counts to zero — routes_pipeline.py:242-253
- §3.7 — insert — ambiguity — roster-feed shape: counts over the feed population (`teacher_count` zero under `PER_STUDENT`), `sections` as full records in scope order, `usernames`/`display_names` parallel students-then-teachers with `student_count + teacher_count` entries, a live account's stored username reused verbatim, others derived against live plus already-emitted names, nothing persisted, and a `null` username instead of `ERR_IDENTIFIER_UNAVAILABLE` — routes_license.py:252-314
- §3.8 — revise — ambiguity — `basis` defaults to `final` when omitted or empty; only `final`/`provisional` accepted — routes_license.py:326-328, shape.py:191
- §3.8 — insert — ambiguity — the null rule governs the *stored* pair only; the computed summary always reports what it derived, so an account-less license answers score zero / `DROP` while the record shows null — routes_license.py:330-341, cascade.py:93-99

### Cross-pass findings adjudicated
1. `transformed_record_count` written on both transform branches — **confirmed mismatch, patched** in §3.7 (pass 4).
2. `cascade.compute_sync_health` / `apply_sync_health` are **dead code** (no callers). Nothing was pinned from them; `sync_health` semantics were pinned only from the four live inline writers — routes_license.py:87 (birth `OK`), routes_pipeline.py:180 (transform), routes_pipeline.py:255 (publish `OK`), routes_ref.py:243 (separation `BLOCKED`). The resolve-match wording was deliberately left under-determined so it stays true for an ADVISORY item on a `TRANSFORMED` run.
3. `routes_ref.py:234` hardcodes the separation-raised `UNMATCHED_TEACHER` item to `BLOCKING` regardless of `unmatched_teacher_policy` — §3.2 already pins this; §3.7's policy-dependent severity rule was left intact because it is correct for the transform-raised path (routes_pipeline.py:125-128).

### Closing integrity check (pass 4, re-verified independently by the orchestrator)
- All five top-level sections present (§1 L3, §2 L11, §3 L171, §4 L326, §5 L385); §2.1-§2.10 and §3.1-§3.8 all present; 26 headings total.
- §4 endpoint table: **52** rows. §5 error table: **54** rows.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` -> differ at byte 3163, line 15 — **not byte-identical**; the scan genuinely ran.
- `tail -3` ends on the final `ERR_DISTRICT_SEATS_EXHAUSTED | 409` row — a real section boundary, nothing truncated.
- No `SCAFFOLD*.yaml` or `worklog.md` read by any pass; no sibling task directory touched.
- `implementation/` and `test_suite/` mtimes all predate the 19:11Z green sweep, confirming Step 9 changed documentation only — the 8/8 x 143/143 result still stands.

## Pipeline complete — 2026-09-04T19:58:00.000Z

All nine steps done. Final state: 143 tests, 8/8 rounds at 143/143 under `--isolation per-test-server`, `results.{1..8}.json` retained in `workspace/implementation/`, and `workspace/PRD_COMPLETED.md` written.
