# Worklog — task_2211_placement_testing_course_placement_corequisite

## Step 1: Create task directory — 2026-09-01T01:55:55.142Z

Created `tasks/task_2211_placement_testing_course_placement_corequisite/` and `tasks/task_2211_placement_testing_course_placement_corequisite/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T11:32:00.000Z

All three artifacts are complete and lint-clean.

Generated in `/home/ubuntu/github/CodingPRD/tasks/task_2211_placement_testing_course_placement_corequisite/`:

**SCAFFOLD.yaml** (§1.0–§1.7, 3,532 lines) — `complexity_profile`: difficulty_level `beyond_expert`, primary archetype `graph_constraint`, secondary `quota_allocation`, layers [selector_policy, dual_variant_calculation, cascading_side_effects, optimistic_concurrency], entity_topology `graph`, state_machine_shape `cyclic`, role_model `segregation_of_duties`, consistency_model `immediate`.
- 12 entities (Course, CourseRequisite, PlacementRule, Student, TestAdministration, TestAttempt, PlacementDetermination, PlacementAppeal, PrerequisiteOverride, Section, Registration, ValidationStudy)
- 13 state-machine blocks / 73 transitions (Section carries two independent axes; PlacementDetermination has a parallel placement×evidence pair; PlacementAppeal has an INFO_REQUESTED loop)
- 3 optimistic-concurrency rules (Student→determination, Section→registration, Determination→appeal)
- 14 calculations, 30 validation rules in a single 1–30 priority ladder, 69 endpoints, 68 error codes, 7 roles
- 3 segregation-of-duties constraints (study proposer≠decider, appeal reviewer≠determination author, endorser≠reviewer)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8) — all 9 difficulty rule_ids, 25 instances: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2 (two five-hop chains), priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 3.

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9) — all 9 sections, 69 instances (49 with full `test_recipe`, 20 legitimate `excluded_because` stubs each citing a real §1.8 instance): Entities 11, State Machines 12, Calculations 11, Validations 13, Endpoints 5, Errors 8, RBAC 3, Cross-Cutting 5, Consistency Model 1. RBAC covers peer-role denial (403 answers ahead of the 404 lookup) plus both approval chains; Cross-Cutting covers all three OCC rules explicitly (zero §1.8 coverage there) and stubs the two layers already exhausted by §1.8; the Consistency Model instance proves the DISPUTED-evidence cascade (deny → seat release → waitlist promotion) is visible to the immediately following reads with the logical clock unchanged.

Verification: `scaffold_lint.py` reports `VERDICT: clean lint` over 1,230 scanned calls (69 endpoints, 12 entities, 25 §1.8 + 49 §1.9 instances); no duplicate instance names across the two design files; no stub carries a `test_recipe`; zero occurrences of the forbidden concurrency vocabulary in any of the three files. The hard constraint was honored — no sibling task directory was listed, read, or grepped.

## Step 3: Copy shared files — 2026-09-01T11:32:10.000Z

Verified `workspace/INSTRUCTION.md` is byte-identical to project-root `INSTRUCTION.md` (copied by the crashed prior run; no re-copy needed).

## Step 4: Generate PRD — 2026-09-01T11:52:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **518 lines, ~16,700 words**, ending at §5 with no audit footer.

**Structure:** §1 Introduction (3 paragraphs: multiple-measures mandate, the three design pressures, graph-not-hierarchy + logical clock) · §2 Global Specifications with 2.1 RBAC, 2.2 Response Structure (byte-for-byte from `section-2.2-response-structure.md`), 2.3 Pagination, and nine domain-derived cross-cutting subsections 2.4–2.12 (Common Resource Properties, Logical Clock, Numeric Precision, OCC, the 30-band Ordered Enforcement Stack, Reference Resolution, Segregation of Duties, Cascade Propagation, Conserved Quantities) · §3 Business Logic in nine narrative subsections 3.1–3.9 · §4 four-column endpoint table (69 rows) · §5 two-column error table (68 rows).

**Coverage vs scaffold:** 12/12 entities, 69/69 endpoints, 68/68 error IDs, 30/30 validation priority bands, 14/14 calculations (C1 selector policy, C2 round-per-weighted-term confidence, C3 validity/staleness plus the `appeal_override_bypass` variant, C4 scaled score, C5 retake tiers, C6 both seat variants, C7 direct-edge prerequisite closure, C8 term unit load, C9 strict/inclusive cohorts, C10 disproportionate impact, C11 equity throughput gap, C12–C14 the three conserved ledgers in §2.12), 13/13 state machines covering all 73 transitions, 3/3 OCC rules, 7/7 roles.

**Zero-Silence / Hard Contract self-audit (all three PASS; Contract 1 run twice — once against a pre-built inventory, once re-derived from the scaffold):**

```
Field coverage check:
- entities[].fields: 125 required, 125 present, 0 missing
- endpoints[].request_body: 73 required, 73 present, 0 missing
- endpoints[].query_params: 52 required, 52 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
- concurrency_rules[].occ_field: 3 required, 3 present, 0 missing
- union of unique identifiers: 144 required, 144 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write operation + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 73 checked, 73 fully expressed (preconditions paired to error IDs, every cascade hop numbered), 0 missing
- calculations[]: 14 checked, 14 fully expressed with constants embedded in business context, 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in prose, 0 missing
- errors[]: 68 checked, 68 named in prose in addition to the §5 table, 0 missing
- endpoints[].side_effects / applies_to: 69 checked, 69 expressed, 0 missing
- entities[].fields[] structured content: 125 checked, 125 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (confirm-to-ENROLLED vs confirm-to-WAITLISTED, strict vs inclusive cohort, committed_only vs paired_conservative, deliberate unpair vs cascaded PAIR_BROKEN, appeal GRANT vs DENY, APPEALED-to-FINAL vs APPEALED-to-PROVISIONAL, study APPROVE vs REJECT, session CLOSE vs CANCEL cascade), 8 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1427
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- raw (unbackticked) path or method mentions: 0
Status: PASS
```
No-pseudocode sweep: zero symbolic operators (`==`, `>=`, `+=`, `min()`, `round()`, `IN`) survive anywhere in the document; zero fuzzy quantifiers ("approximately", "roughly", "conservatively", "and so on", "TBD").

**Three internal scaffold inconsistencies resolved in favour of the §1.2 state-machine tables (the more detailed and doubly-attested source), flagged here for the worklog:** (1) session cancellation voids attempts in `BOOKED`/`CHECKED_IN` with `void_reason` `ADMIN_CORRECTION` — the endpoint blurb additionally listed `SCORED` with `PROCTOR_ERROR`, which both the TestAdministration and TestAttempt axes contradict; (2) the appeal-granted minted determination opens in `placement_state` `PROVISIONAL` (endpoint blurb said `FINAL`); (3) a deliberate unpair lands on `UNPAIRED` clearing `linked_section_id`, while only the cancellation cascade lands on `PAIR_BROKEN` retaining it (endpoint blurb said unpair produces `PAIR_BROKEN`) — the contrast is called out explicitly in §3.8. Appeal denial/withdrawal is documented with both return branches (`FINAL` when evidence is `VERIFIED`, else `PROVISIONAL`). The withheld design files were never opened.

## Step 6: Generate implementation — 2026-09-01T12:38:00.000Z

Implementation complete.

## Files created (final session increment)

- `routes/registrations.py` — 6 endpoints
- `routes/overrides.py` — 4 endpoints
- `routes/studies.py` — 5 endpoints
- `app.py` — Flask factory, 13 blueprints, `ApiError`/404/405/500 handlers, `PORT` default 10000

## Module layout

`workspace/implementation/`

```
start.sh              # exec python3 app.py, 0.0.0.0:$PORT (default 10000), guarded pip install
requirements.txt      # flask>=3.0.0
app.py                # app factory + error handlers, no seeding
db.py                 # in-memory Store: 12 dicts, logical clock @ 2026-08-01T00:00:00Z, base_row/touch/sort
constants.py          # every enum tuple + the 30 pinned numeric constants
errors.py             # 68-code ERROR_STATUS map, ApiError, fail()
response.py           # §2.2 envelope (object/array/error), Decimal->float, ISO-8601 ms
middleware.py         # bands 1-3 authentication / RBAC
validators.py         # band 4 body + strictly allowlisted query parsing, pagination
services/calc.py      # 14 calculations (selector, confidence, seats, prereq closure, study metrics, DI index, equity)
services/cascades.py  # every multi-hop cascade (enroll/promote/deny/drop, void, close/cancel, retire, activate, grant)
services/serialize.py # 12 serializers
routes/               # clock, students, courses, requisites, rules, administrations, attempts,
                      # determinations, appeals, sections, registrations, overrides, studies (+ common.py)
```

## Endpoint count

**69 of 69** declared endpoints registered (verified by enumerating `app.url_map`): clock 1, students 5, courses 6, course-requisites 4, placement-rules 5, test-administrations 5, test-attempts 7, placement-determinations 5, placement-appeals 9, sections 7, registrations 6, prerequisite-overrides 4, validation-studies 5.

## Boot and smoke confirmation

`bash start.sh` boots cleanly from a fresh process (`PORT=10777` and `PORT=10778` both exercised) and answers requests on `$PORT`. Three end-to-end smoke scripts, ~100 calls total, all returned the expected status codes with no `BAD` lines and no tracebacks:

1. Course/rule/determination/pairing/registration path — coreq pairing, confirm auto-creating the companion `ENROLLED` registration on the support section with cross-set `coreq_registration_id`, seat arithmetic (`available_seats` 2 -> 1), override issuance, `ERR_NOT_OVERRIDE_ISSUER` for a foreign instructor then a successful revoke, grading recomputing course `enrolled_count`, equity-summary returning grouped `placed`/`through`/`rate`.
2. Proctoring and appeals path — session schedule/open, attempt book/check-in (correctly rejected outside the sitting window, accepted inside)/score, determination evidence VERIFIED -> finalize, appeal file/start-review/endorse/GRANT minting the override determination, `ERR_STUDY_COHORT_EMPTY` when only an `APPEAL_OVERRIDE`-placed row exists.
3. Validation-study path — run reaching `COMPLETED` with `strict_cohort_size 1`, `strict_success_rate 1.0`, `inclusive_success_rate 1.0`, `disproportionate_impact_index 1.0`, `reference_group_key null` (no subgroup reaches n=10); idempotent re-run gives `run_count 2`; SoD-1 rejects the proposer as decider; APPROVE flips the candidate rule `DRAFT -> ACTIVE` with `activated_at` and supersedes the same-key rule (`v1 SUPERSEDED`, `v2 ACTIVE`).

Storage is in-memory dicts only — no SQLite, no JSON dump, no seeded or hardcoded entities; the only artifacts on disk after a run are `__pycache__` directories.

Key spec decisions carried into the new modules: registration-hold gate order follows §2.8 bands (stale version -> section OPEN -> override CONSUMED -> override EXPIRED -> duplicate), confirm follows bands 8/9/12/16/29/30 with `ERR_SECTION_FULL` only when seats and the 10-slot waitlist are both exhausted, `term_units_at_confirm` is written on both the enrolled and waitlisted branches, confirm does not trigger waitlist promotion (no seat is released), override revoke reports `ERR_OVERRIDE_CONSUMED` from `CONSUMED` before the issuer binding check, and study proposal withdraws an earlier `DRAFT`/`COMPLETED` study for the same candidate rule while a cohort-empty run leaves the prior state and version untouched.

## Step 5: Generate unit tests — 2026-09-01T13:55:00.000Z

Queue B is complete. Final state of the generated suite for task 2211:

## Files

**`test_helpers/`** (Stage 1, 9 files, unchanged this session)
`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

**`test_suite/`** — 18 test modules + `conftest.py`, **154 tests, all collected cleanly** (`pytest --collect-only` -> 154).

Created this session:
- `test_suite/test_corner_errors.py` — 17 tests / 8 instances
- `test_suite/test_corner_rbac.py` — 6 tests / 3 instances
- `test_suite/test_corner_complexity_layers.py` — 6 tests / 3 instances
- `test_suite/test_corner_consistency_model.py` — 2 tests / 1 instance
- also removed one dead import (`new_section`) from `test_compensating_invariant.py`

## Test counts

| Queue | Tests | Instances |
|---|---|---|
| A — Difficulty (§1.8) | 65 | 25 / 25 |
| B — Corner (§1.9) | 89 | 49 / 49 non-stub |

Queue A per module: boundary_precision 8, combinatorial_formula 6, compensating_invariant 9, cross_entity_state_dependency 9, dual_variant_calc 5, non_linear_state_machine 8, priority_pair 7, resource_temporal_overlap 9, transitive_cascade 4.
Queue B per module: entities 14, state_machines 15, calculations 10, validations 13, endpoints 6, errors 17, rbac 6, complexity_layers 6, consistency_model 2.

## Coverage audit

- Every one of the 25 difficulty instances has >=2 tests (2 or 3 each); every one of the 49 non-stub corner instances has >=1 (11 have exactly 1, the rest 2–3). Distinct `Design:` tags = 74, matching 25 + 49 exactly.
- All 20 `excluded_because:` corner stubs left untranslated, as required.
- Zero untagged tests, zero multi-tagged tests, zero `skip`/`skipif`/`xfail`, zero unresolvable imports, zero non-existent `api_client` methods, zero unused imports, no occurrence of the word "scaffold" or of any scaffold section/table reference in generated code.

## Instances skipped

None — no instance failed the PRD-first filter outright. Individual assertion legs were dropped or corrected where the PRD does not uniquely derive (or actively contradicts) the design's expectation:

1. **`Errors/every_unknown_identifier_answers_its_own_typed_404...`** — the malformed-UUID -> `ERR_INVALID_REQUEST` leg was omitted: band 4's verbatim enumeration never mentions identifier syntax, so 400 is not derivable. The other 12 legs stand.
2. **`RBAC/no_role_may_reach_another_roles_exclusive_operation`** — the "Registrar issuing a prerequisite override -> `ERR_UNAUTHORIZED`" leg was dropped as PRD-contradicted: §4 lists `Instructor`, `Registrar` for `POST /prerequisite-overrides` and §2.1 says instructors "share the issuing and revoking of prerequisite overrides with the registrar's office." The remaining 7 exclusivity probes plus the shared-read leg are translated.
3. **`Errors/a_study_may_run_at_the_instant...`** — design asserts `strict_cohort_size == null` on a `DRAFT` study; §3.4 says a proposal opens with those four counters "all 0", so the assertion is `== 0`.
4. `level_rank: 105` (three instances) is outside §3.1's "integer from 1 to 100" -> `level_rank=100`.
5. Two grading recipes (`Errors/approval_is_blocked_by_disproportionate_impact...`, `RBAC/a_study_may_not_be_decided_by_the_hand_that_proposed_it`) grade sections that §3.9 requires to be `CLOSED` with the clock at/after `meets_end_at`. Sections were re-planned to meet 2026-06-01 so they can be closed and graded at the default clock, keeping `graded_at` inside the observation window and every asserted metric unchanged.
6. **`Complexity Layers/appeal_create_rejects_a_stale_determination_version`** — design uses `grounds: "MULTIPLE_MEASURES"`, not a declared enum member (§3.7: `NEW_TRANSCRIPT`, `TEST_IRREGULARITY`, `EL_PATHWAY`, `OTHER`); `NEW_TRANSCRIPT` substituted so the 412 is not pre-empted by band 4.
7. Positional `$.data[0]` assertions over rows minted in the same logical-clock instant (requisite listing, determination listing, section-registration listings) were replaced by `total_count` plus id->field maps, since §2.3's `created_at` ordering cannot break the tie.

## Step 7: Run tests and iterate — 2026-09-01T14:52:00.000Z

All 8 parallel rounds are green: **154/154 passed in every round, zero failures, zero flakiness** (union of failures across rounds = empty).

## Summary

**Iterations run:** 2 full 8-round sweeps (initial diagnostic sweep: 115/154 with an identical, fully deterministic 39-test failure set in all 8 rounds; final sweep: 154/154 in all 8 rounds), plus several fast targeted subset runs via a throwaway harness at `/tmp/dbg2211.sh`.

**Tests deleted:** none. No test asserted a scaffold-only rule outright.

**Fixes applied to `test_helpers/`:** none. No fixture constructed a PRD-inconsistent precondition.

**Fixes applied to `test_suite/`:**
- `test_suite/test_compensating_invariant.py` — `test_the_second_confirmation_waitlists_and_the_seat_ledger_balances`: `after_first["seats_held"] == 0` -> `== 1`. The second student's hold is still `PENDING` at that point and PRD §3.8 says "`seats_held` counts those in state `PENDING`"; the old value also broke the test's own quoted ledger identity.
- `test_suite/test_cross_entity_state_dependency.py` — `test_closing_the_session_marks_an_untouched_child_a_no_show`: `closed["seats_booked"] == 0` -> `== 1`. PRD §3.3 exposes `seats_booked` as attempts in state `BOOKED`, `CHECKED_IN` **or** `SCORED`, and `attempt_d` is `SCORED` before the close.
- `test_suite/test_corner_endpoints.py` — `test_the_placement_window_is_half_open_and_a_late_grade_is_not_throughput`: partial-coverage split (STEP 1c). Removed `group_count == 3` and the exact group-key list `["ASIAN","HISPANIC","WHITE"]`; kept every per-group `placed`/`through`/`rate`, the gap and the min/max keys, and added a covered ordering check (`keys == sorted(keys)`, `group_count == len(groups)`). Reason: PRD §3.9 says only that `disaggregation_key` "selects which student attribute forms the groups" and defines `placed` "for each group key" — it never states which keys populate the array, and its own live clauses "`rate` is null when `placed` is zero" and "A group is *scored* when its `placed` is at least one" only make sense if zero-placed groups can appear. So whether the boundary student (`MULTI`, determined exactly at the exclusive `window_end_at`, `placed == 0`) forms a fourth group is not uniquely derivable. Sibling test `test_a_single_scored_group_reports_a_null_gap_rather_than_zero` passes under both readings and was left untouched.

**Fixes applied to `implementation/`:**
- `workspace/implementation/response.py`, `jsonable`/`iso_seconds` — made datetime rendering key-aware. PRD §2.4 pins three fractional digits to `created_at`/`updated_at` only (plus `api_request_timestamp` in §2.2); §2.6 says every other datetime is merely "ISO 8601 UTC". This one change fixed 31 of the 39 failures.
- `workspace/implementation/services/cascades.py`, `dispute_registration_cascade` and `grant_appeal` (hop 3) — scoped the DENY sweep to the determination's own student. Previously another student's live rows on the same course were denied, which would have made PRD's hop 5 ("promotes `WAITLISTED` registrations to `ENROLLED` ... on every section that released a seat") dead code.
- `workspace/implementation/routes/determinations.py`, `evidence` — removed the student `version` bump. PRD §3.6 gives an evidence move only "recomputes the student's `advising_hold` and increments the determination's `version` by one"; `advising_hold` is derived on read, and the student version bump is enumerated for finalize alone.

Storage remains in-memory dicts with no startup seeding; no endpoint, field, side effect or header was added.

## Step 8: Finalize PRD — 2026-09-01T15:12:00.000Z

## Line counts
- `PRD.md`: 518 lines / 16,672 words / 120,761 chars
- `PRD_FINALIZED.md`: 518 lines / 16,995 words / 122,863 chars
- Line delta: **0%** (all six edits are inline inside existing paragraphs); word delta **+1.94%**, char delta **+1.73%**.

## Changes (one bullet each)
- **§2.6** — revise — pinned datetime rendering precision: `created_at`, `updated_at`, `api_request_timestamp` and the clock endpoint's `current_utc` echo always carry three fractional digits; every other datetime renders at the precision its instant carries (no fractional part on a whole second, three digits otherwise, finer components truncated to ms) — `implementation/response.py:31,34-44`, `implementation/routes/clock.py:34`.
- **§3.6 (evidence axis)** — insert — an evidence move does not mutate the student row (`version`/`updated_at` unchanged) because `advising_hold` is derived on read; explicit carve-out from §2.4, with the operations that *do* bump the student version enumerated — `implementation/routes/determinations.py:193-204` (vs `:145` finalize).
- **§3.6 (landing on `DISPUTED`)** — revise — the DENY sweep is scoped to registrations held by that determination's own `student_id`; other students' rows on the same courses untouched — `implementation/services/cascades.py:136`.
- **§3.6 (void chain, hop 3)** — revise — same student scoping on the third hop — `implementation/services/cascades.py:124-140` (invoked at `:168`).
- **§3.7 (grant chain, hop 3)** — revise — same student scoping on the supersession-unwind hop — `implementation/services/cascades.py:434`.
- **§3.9 (equity report)** — insert — the `groups` array is formed from the whole student roster (one entry per distinct rendered key across all students, zero-`placed` groups included); `group_count` = number of entries; empty roster -> no groups — `implementation/services/calc.py:589-595,619-626,645`.

## Per-edit pre-edit search log

1. **§2.6 datetime rendering.** (a) Subject: how datetimes are serialised in responses. (b) Enumerated: `response.py` `iso`/`iso_seconds`/`jsonable`/`ok`/`ok_list`/`error`/`_request_timestamp`; grepped every call site of `iso(`/`iso_seconds`/`jsonable` repo-wide — only `routes/clock.py:34` calls `iso` directly; all serialisers in `services/serialize.py` hand raw `datetime` objects through key-aware `jsonable`; `db.base_row`/`touch` set `created_at`/`updated_at` from the logical clock; `validators.parse_datetime` normalises inbound values to UTC. (c) Adjustment: the initial draft ("everything except `created_at`/`updated_at` drops the fractional part") would have mis-described `routes/clock.py:34`, which renders `current_utc` through `iso` and therefore always emits three digits — added `current_utc` (and `api_request_timestamp`) to the always-three-digits list, and phrased the rest as "at the precision its own instant carries" so client-supplied sub-second instants stay covered.

2. **§3.6 evidence move / student version.** (a) Subject: which rows an evidence move mutates, and whether recomputing a read-derived field bumps a version. (b) Enumerated: `routes/determinations.py` evidence (`:149-204`), finalize (`:126-146`), create (`:85-96`); grepped every `touch(` in `routes/` and `services/` — student rows are touched by measures update (`routes/students.py:122`), scoring and void (`routes/attempts.py:163`, `services/cascades.py:157`), session close/cancel (`cascades.py:190,208`), appeal file/deny/withdraw (`routes/appeals.py:104,249,274`), grant (`cascades.py:443`); read `calc.student_computed`, `calc.section_computed`, `calc.course_computed`, `calc.admin_computed`, `serialize.registration` (all read-derived) and `calc.recompute_registration_prerequisite` (stored, touched only when the value changes). (c) Adjustments, two: (i) I did **not** narrow §2.4's "recomputation of a derived field is a mutation" sentence — doing so would have contradicted the student version bumps in void, session close/cancel and the appeal transitions, which the PRD never enumerates individually; the carve-out is stated locally on the evidence axis instead. (ii) My first draft said "the appeal transitions of §3.7 still perform it" — that over-claimed, since start-review/request-info/resubmit/endorse (`routes/appeals.py:149,168,189,211`) never touch the student; narrowed to "filing, deciding and withdrawing", and softened the qualifier to "reaches into a student's placement or attempt picture" so a session close that only produces `NO_SHOW` rows (which touches the student without changing any derived count) is not excluded.

3. **§3.6 `DISPUTED` sweep scoping.** (a) Subject: which registrations a determination-level DENY sweep selects. (b) Enumerated: `cascades.dispute_registration_cascade` (`:124-140`) and both its callers (`routes/determinations.py:198`, `cascades.void_attempt:168`) — both pass a determination row, so the `student_id` filter is uniform; `cascades.deny_registration`, `deny_counterparts_and_release_overrides` (counterparts are the same student by construction in `enroll_registration:58-69`); contrasted with `cascades.cancel_section:317-321`, which is section-scoped and deliberately spans all students (PRD §3.8 wording left untouched). (c) Wording kept as "held by that determination's own `student_id`" rather than "the appealing student" so it reads correctly for both the direct evidence move and the void cascade.

4. **§3.6 void-chain hop 3.** (a) Subject: same DENY sweep, as reached from the void chain. (b) Enumerated: `cascades.void_attempt:145-169` (hops 1-5), `calc.renumber_attempts`, `dispute_registration_cascade`, `settle`/`promote_waitlist` (hop 5, whose reachability was the reason for the Step 7 fix). (c) None.

5. **§3.7 grant-chain hop 3.** (a) Subject: the supersession-unwind sweep. (b) Enumerated: `cascades.grant_appeal:382-445` (course set difference `old_courses - new_courses`, `student_id` filter at `:434`), `deny_counterparts_and_release_overrides`, `settle`, and `routes/appeals.py:238-241` (sole caller). Confirmed the existing sentence "A course that appears on both the old and the new placement keeps its registrations untouched" still matches `dropped_courses`. (c) None.

6. **§3.9 equity group formation.** (a) Subject: which group keys populate the equity report's `groups`/`group_count`. (b) Enumerated: `calc.equity_summary:586-650` (buckets built from `db.students.values()`, sorted by key, `group_count = len(groups)`, `rate` null at `placed == 0`, `scored = placed >= 1`, min/max keys from scored groups only), `calc._group_key:574-583`, `routes/courses.py` equity endpoint (`disaggregation_key` enum-validated, window strictly ordered, non-paginated), `constants.DISAGGREGATION_KEYS`; also checked `calc.disproportionate_impact:546-569`, which groups the *study's* strict cohort (cohort rows only, never the roster) to be sure the new sentence could not bleed into §3.4. (c) Scoped the sentence explicitly to the equity report's `groups`/`group_count`, and added the empty-roster and single-key cases so the claim stays true when the roster renders fewer keys than the enum allows (`FIRST_GENERATION`/`PELL` do not always emit both `TRUE` and `FALSE`).

## Step 9: Complete PRD — 2026-09-01T16:05:00.000Z

Done. The full sweep is complete and the §2.8 cross-check found no remaining band-vs-local-order contradiction (the one structural conflict — a handful of operations whose §3 gate order departs from strictly ascending bands — is now resolved by an explicit precedence clause in §2.8's preamble).

## Metrics

| | PRD_FINALIZED.md (source) | PRD_COMPLETED.md |
|---|---|---|
| Lines | 518 | 519 (+1) |
| Characters | 122,509 | 142,943 (**+20,434**) |

- Changed passages: **60** (14 pure inserts, 46 in-paragraph revisions; no new sections, no new paragraphs except one bullet appended to §2.2's existing bullet list)
- **Ambiguity-pins: 42** — PRD was silent, now pinned to what impl does
- **Mismatch-revisions: 18** — PRD asserted something impl contradicts

## Changes

- §2.1 — revise — mismatch — proctor binding narrowed: it applies to session status, check-in and score only; void and no-show carry no assigned-proctor binding; Registrar override-revoke exempt from issuer binding — `routes/attempts.py:168,181`, `routes/overrides.py:93`
- §2.2 — insert — ambiguity — unrouted path -> 404 `ERR_INVALID_REQUEST`, bad method -> 405, trailing slash insignificant — `app.py:59-65`
- §2.3 — revise — ambiguity — undeclared query params and unknown body fields rejected; non-object body rejected; absent/empty body read as `{}` — `validators.py:105-135,173`
- §2.3 — insert — ambiguity — every tie broken by internal row-creation sequence, never by `id`; names the two listings that override default ordering — `db.py:72-78`
- §2.4 — insert — ambiguity — `created_at` stamped from the logical clock, not host time — `db.py:52-62`
- §2.4 — revise — ambiguity — `updated_at` also refreshed from the logical clock — `db.py:64-70`
- §2.4 — revise — ambiguity — `version` is 1 on a fresh row; no resource omits `updated_at`/`version` — `db.py:52-70`
- §2.4 — revise — **mismatch** — a recomputation is a mutation **only when a stored value actually changes**; no-op renumber/prereq recompute touches nothing — `services/calc.py:419-427,144-161`
- §2.5 — insert — ambiguity — clock defaults to `2026-08-01T00:00:00Z`, accepts any instant (non-monotonic), echoes `current_utc` — `db.py:31-39`, `routes/clock.py:17`
- §2.5 — insert — ambiguity — sweep's recompute hop runs only if an override actually expired; unchanged status not touched; `EXPIRED` never returns to `ISSUED` — `routes/clock.py:17-45`
- §2.8 — insert — ambiguity — an explicit gate order stated in §3 for one operation prevails over the band order — cross-cutting (`routes/*.py`)
- §2.8 — revise — ambiguity — band 4 covers unknown body fields *and* undeclared query parameters — `validators.py:120,173`
- §2.11 — insert — ambiguity — promotion by `created_at` asc, renumber by `created_at` asc, and each disturbed section's `version` bumped exactly once after all promotions — `services/cascades.py:18-31,78-90`
- §3.1 — revise — ambiguity — already-`RETIRED` course refused `ERR_INVALID_STATE`; withdrawn study note is the literal `candidate rule retired` — `routes/courses.py:107`, `services/cascades.py:263-266`
- §3.1 — insert — ambiguity — neither endpoint course need be `ACTIVE`; duplicate test runs among `ACTIVE` edges only — `routes/requisites.py:36-73`
- §3.1 — revise — **mismatch** — edge retirement requires `ACTIVE` (else `ERR_INVALID_STATE`), and hop 2 recomputes registrations **whether or not** hop 1 revoked anything — `routes/requisites.py:98`, `services/cascades.py:223-235`
- §3.2 — revise — ambiguity — a measures revision increments `version` even when it supplies no fields or identical values — `routes/students.py:111-124`
- §3.2 — revise — ambiguity — scoped determination listing adds creation-sequence tiebreak and explicitly overrides §2.3 ordering — `routes/students.py:127-137`
- §3.3 — revise — **mismatch** — any of the three authorized roles may drive any declared session transition; proctor binding applies only when the acting role is `Proctor`; the `ends_at` window check applies only to `SCHEDULED -> OPEN` and only after the binding check — `routes/administrations.py:133-160`
- §3.3 — revise — ambiguity — close/cancel null each moved attempt's `next_eligible_at`; close also renumbers and recomputes surviving `SCORED` gates — `services/cascades.py:172-210`
- §3.3 — revise — ambiguity — booking has no resource-owner binding; a `BOOKED` attempt already carries a live ordinal; five booking gates pinned in order (bookable -> waiting period -> budget -> already-open -> capacity) — `routes/attempts.py:40-92`
- §3.3 — revise — ambiguity — check-in tests attempt state first and the clock window last of four; scoring tests state first and imposes **no** clock window — `routes/attempts.py:117-135,138-165`
- §3.3 — revise — **mismatch** — voiding is unbound by any assigned-proctor check and refuses non-`SCORED` with `ERR_INVALID_STATE`; no-show renumbers nothing and has no session/proctor precondition — `routes/attempts.py:168-190`
- §3.4 — revise — ambiguity — activation gate order pinned (own status -> retired-course, target before coreq -> coreq integrity -> measure completeness); coreq retirement check applies whenever `coreq_course_id` is non-null — `routes/rules.py:146-169`
- §3.4 — revise — **mismatch** — already-`RETIRED` rule refused `ERR_INVALID_STATE`; study withdrawal happens only from `DRAFT`/`ACTIVE`, not from `SUPERSEDED`; note is the literal `candidate rule retired` — `routes/rules.py:172`, `services/cascades.py:295-306`
- §3.4 — revise — ambiguity — propose check order (window shape -> rule 404 -> subject mismatch -> candidate status); supersession note literal `superseded by a newer study`; study carries no `decided_at` — `routes/studies.py:43-85`
- §3.4 — revise — ambiguity — run requires study in `DRAFT`/`COMPLETED` first (`ERR_INVALID_STATE`); a failed run leaves `version`/`updated_at` untouched; success bumps `version` exactly once — `routes/studies.py:108-132`
- §3.4 — revise — ambiguity — governing determination tiebreak extended to creation sequence — `services/calc.py:484-496`
- §3.4 — revise — **mismatch** — decide checks state before anything; candidate-rule-`DRAFT` is checked **before** SoD-1 and the metric floors after it; a null metric counts as below floor; `inclusive_success_rate` never consulted; rejection leaves the rule untouched whatever its status — `routes/studies.py:135-166`
- §3.5 — revise — ambiguity — cited-attempt tie extended to creation sequence — `services/calc.py:171-186`
- §3.5 — revise — ambiguity — selector's final tie falls to creation sequence — `services/calc.py:188-216`
- §3.5 — revise — **mismatch** — minting supersedes **every** `PROVISIONAL`/`FINAL` sibling (not just one), in `created_at` order, and leaves `APPEALED` untouched — `routes/determinations.py:85-95`
- §3.6 — revise — ambiguity — finalize distinguishes `ERR_DETERMINATION_SUPERSEDED` from `ERR_INVALID_STATE` for `APPEALED`/`FINAL` — `routes/determinations.py:132-139`
- §3.6 — revise — **mismatch** — the evidence `note` is validated but never persisted; the SUPERSEDED check precedes the declared-transition test; an evidence move does **not** mutate the student row (declared exception to §2.4) — `routes/determinations.py:149-204`
- §3.6 — revise — ambiguity — void clears the voided attempt's own `next_eligible_at` to null — `services/cascades.py:145-151`
- §3.7 — revise — **mismatch** — filing gate order is actionable -> EL grounds -> window (not window before grounds); withdrawal-on-refile note is the literal `superseded by a newer appeal` with `decided_at` = clock — `routes/appeals.py:54-107`
- §3.7 — revise — **mismatch** — start-review accepts `SUBMITTED` only; `INFO_REQUESTED` re-entry happens via resubmit — `routes/appeals.py:133-151`
- §3.7 — revise — ambiguity — resubmit tests state first, then ownership, then the 14-day window; `reviewed_by_user_id` untouched — `routes/appeals.py:173-191`
- §3.7 — revise — ambiguity — a supplied endorsement note is written into `decision_note`; an omitted note leaves it unchanged; state checked ahead of the other two gates — `routes/appeals.py:194-213`
- §3.7 — revise — **mismatch** — decide order is state -> SoD-2 -> reviewer ownership (ownership last, not first) — `routes/appeals.py:216-251`
- §3.7 — revise — ambiguity — where several `ACTIVE COREQUISITE` edges exist, the earliest by `created_at`/creation sequence supplies `coreq_course_id` — `services/cascades.py:389-396`
- §3.7 — revise — ambiguity — withdrawal note is the literal `appeal withdrawn` with `decided_at` = clock; ownership checked after the state test — `routes/appeals.py:254-274`
- §3.8 — insert — ambiguity — no room-occupancy rule, no turnaround buffer, no uniqueness on `course_id`/`term_code`/`room_code` — `routes/sections.py:43-69`
- §3.8 — revise — ambiguity — the self-hold exclusion applies to the row's own section only; the linked half's `seats_held` is taken as it stands — `services/calc.py:335-353`
- §3.8 — revise — ambiguity — pair order (primary `pairing_state` -> both `PLANNED` -> integrity -> geometry); both versions bump; response body is the primary section — `routes/sections.py:96-144`
- §3.8 — insert — ambiguity — unpair order (`PAIRED` -> `PRIMARY` role -> status), response body is the primary — `routes/sections.py:147-179`
- §3.8 — revise — ambiguity — `PAIR_BROKEN` retains `role_in_pair` as well as `linked_section_id` — `services/cascades.py:323-332`
- §3.8 — revise — ambiguity — declared-transition test precedes every other gate; `PLANNED` target always `ERR_INVALID_STATE`; any bad origin for an `OPEN` target reports `ERR_SECTION_NOT_CLOSED` — `routes/sections.py:182-223`
- §3.8 — insert — ambiguity — cancellation promotes **no** waitlist anywhere; each touched section's `version` bumps exactly once — `services/cascades.py:311-339`
- §3.9 — revise — ambiguity — hold gate order (`ERR_SECTION_NOT_OPEN` -> override state -> override expiry -> duplicate); no resource-owner binding on the hold — `routes/registrations.py:45-93`
- §3.9 — revise — **mismatch** — only the override the registration itself presents can waive an edge; an unpresented matching waiver waives nothing, so two unsatisfied blocking edges can never both be cleared — `services/calc.py:383-417`
- §3.9 — revise — **mismatch** — confirm order is state -> section OPEN -> placement actionable -> prerequisite -> course mismatch (prerequisite **before** mismatch); closure re-evaluated live and not written back — `routes/registrations.py:134-177`
- §3.9 — insert — ambiguity — companion minted only when `coreq_registration_id` is null, copies the combined `term_units_at_confirm`, `override_id` null, prereq may read `UNMET`; waitlisted branch writes units and leaves the override `ISSUED` — `services/cascades.py:35-76`
- §3.9 — insert — ambiguity — promotion re-runs none of confirmation's gates — `services/cascades.py:78-90`
- §3.9 — revise — **mismatch** — a student may drop their own `ENROLLED` row (not just holds), a `Registrar` any row; the section test precedes the ownership test — `routes/registrations.py:180-196`
- §3.9 — revise — ambiguity — grading's clock check runs last of three and reports `ERR_INVALID_STATE`; `success` reads `false`, never null, on an ungraded row — `routes/registrations.py:199-218`, `services/serialize.py:54-58`
- §3.9 — insert — ambiguity — `expires_at` is not compared to the clock at issuance, so an already-expired override may be issued — `routes/overrides.py:37-67`
- §3.9 — revise — **mismatch** — consumption reads only the override's `state`, never `expires_at`, so an override that lapsed between hold and confirm is still consumed; revoke order is CONSUMED -> state -> issuer binding; unchanged recompute leaves the row alone — `services/cascades.py:43-47`, `routes/overrides.py:93-110`
- §3.9 — revise — **mismatch** — the equity window need not be closed (future windows report fine); window-shape check runs after the `course_id` 404; groups drawn from the whole roster — `routes/courses.py:123-137`, `services/calc.py:586-650`
- §4 — revise — **mismatch** — start-review endpoint row corrected to `SUBMITTED -> UNDER_REVIEW` only — `routes/appeals.py:133-151`
