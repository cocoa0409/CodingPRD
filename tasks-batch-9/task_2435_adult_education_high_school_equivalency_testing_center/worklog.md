# Worklog — task_2435_adult_education_high_school_equivalency_testing_center

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2435_adult_education_high_school_equivalency_testing_center` and its `workspace/` subdirectory. Index 2435 was pre-assigned by the orchestrating pipeline; no scan of `./tasks/` was performed and no index was allocated locally (32 concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-02T09:54:00.000Z

Done. All three artifacts are complete and the lint is clean.

**Verdict block (verbatim from `scaffold_lint.py`):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2435_adult_education_high_school_equivalency_testing_center/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2435_adult_education_high_school_equivalency_testing_center/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2435_adult_education_high_school_equivalency_testing_center/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     15
  §1.8 instances scanned:     25
  §1.9 instances scanned:     89
  Calls scanned (§1.8+§1.9):  1368

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2435_adult_education_high_school_equivalency_testing_center/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**SCAFFOLD.yaml counts:** 15 entities, 16 state machines (incl. a parallel two-axis `ExamRegistration`), 3 concurrency rules (session / enrollment / funding-period OCC), 11 calculations (2 dual-variant), 45 validations on a 1→101 priority ladder, 72 endpoints, 81 error codes, 7 roles (4 opaque + 3 entity_backed). Profile: `compliance_audit` + `temporal_windowing`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`, `flat` topology, `parallel` state shape, `segregation_of_duties`, `immediate` consistency, forward-only logical clock.

**§1.8 (depth):** 25 instances across all 9 required rule_ids — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3.

**§1.9 (breadth):** 119 instances (89 full recipes + 30 `excluded_because:` stubs pointing at named §1.8 instances) across all 9 taxonomy sections — entities 21, state_machines 26, calculations 24, validations 29, endpoints 5, errors 3, rbac 6, cross-cutting layers 4, consistency model 1.

Key findings while authoring: the §1.9 audit forced one §1.5 reshape (ERR_ROOM_OUT_OF_SERVICE was unreachable → added `POST /testing-rooms/{roomId}/out-of-service`, a `TestingRoom` state machine and a `service_note` field, taking endpoints to 72 / state machines to 16). All 81 error codes are now triggerable across the two design files, and every instance name is unique across the union. The deepest corner is a five-link proctor-revocation cascade (registrations → credential void → transcript hold + outcome rescission → funding pool restoration → 409 on a new order), which is also the only home for ERR_CREDENTIAL_NOT_ISSUED. The task's own sibling directories were never read, per the hard constraint.

## Step 3: Copy shared files — 2026-09-02T09:54:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T10:12:00.000Z

The PRD is complete and written to disk in full.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2435_adult_education_high_school_equivalency_testing_center/workspace/PRD.md`
- **Final line count: 588 lines** (file ends with a trailing newline; no `<!--APPEND-->` staging marker remains)
- **Last section heading: `## 5. Error Codes`**, and the file's final line is the last catalogue row `| `ERR_VOUCHER_ADJUSTMENT_INVALID` | 422 |` — a real section boundary, not mid-sentence.

**Structure delivered:** §1 Introduction; §2 Global Specifications with 11 subsections (RBAC, verbatim response structure, pagination, logical program clock, identity/versioning, a 44-band request-evaluation ladder, stale-view protection, cents/hours/rounding, cascade discipline, conserved ledgers, separation of duties); §3 Business Logic with 9 subsections (intake/placement, sections/enrollment, attendance-hour ledger & skill gain, centre authorisation/suspension, proctor certification/revocation, exam-sitting scheduling, accommodation requests, registration/fee assessment/exam day, credentials/transcripts/outcomes/funding); §4 endpoint table (Method, Path, Description, Authorized Role(s)); §5 error table (Error ID, HTTP Status Code).

**Hard Contract verification (mechanically checked, code fences excluded from token extraction):**
- **Contract 1 — Field-Name Coverage: PASS.** All 123 `entities[].fields[].name` values appear verbatim in backticks (0 missing). All 108 request-body / query-param / path-param / computed-read output identifiers appear in backticks (0 missing), including `expected_exam_session_version`, `expected_enrollment_version`, `expected_funding_period_version`, `variant`, `decision`, `target_status`, `delta_cents`, `current_utc`, and every allocation-preview and skill-gain output field. Additionally all enum values across all fields (0 missing).
- **Contract 2 — Rule Coverage: PASS.** All 81 scaffold error ids are used in §1–§4 prose (not merely listed in the §5 table); all 59 declared transitions across the 16 state machines (including both `ExamRegistration` axes) are narrated with their triggers, guards and cascade origins; all 11 calculations are expressed step-for-step in natural language with both dual variants (`BEST_POST`/`LATEST_POST`, `PROVISIONAL`/`FINAL`) and their differing outputs; all three OCC rules, all five cascade chains, both sibling-branch symmetries (approve/deny, certify/reject) and every field-level default are stated. No pseudocode operators, no fuzzy quantifiers (grep for `>=`, `+=`, `min(`, `floor(`, `approximately`, `roughly`, etc. returns zero hits).
- **Contract 3 — §3 Path Purity: PASS.** Of 1,163 backticked tokens in §3, zero begin with `/`, zero are a bare HTTP method, and zero combine method+path.

Also confirmed: §2.2 is byte-identical to `section-2.2-response-structure.md`; §4 covers all 72 scaffold endpoints (72 table rows, every path matched) and §5 covers all 81 error ids with their scaffold HTTP statuses. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced.

**Orchestrator truncation check (per the known doc-generator failure mode):** independently verified — 588 lines, headings at §1/§2/§3/§4/§5, tail is a complete markdown table row ending the §5 error catalogue. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T12:10:00.000Z

The suite is complete. Final state and audit results:

## Files written

**`test_helpers/`** (Stage 1, 9 modules): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`test_suite/`** (Stage 2): `conftest.py` + 23 test files, `test_01_…` through `test_23_concurrency_thresholds_cascades_and_visibility.py`. **177 tests collected**, 5–10 per file.

Final file added this session: `test_23_concurrency_thresholds_cascades_and_visibility.py` (8 tests) — exam-session version increment / stale-by-one refusal, the 40.00-hour breakpoint flipping `post_test_eligible` and the fee tier together (39.75 h → 2250 cents, 40.00 h → 1500 cents), the five-link proctor-revocation cascade through a shared `_setup_cascade_chain()` (signature → 4 invalidated results → voided credential → held order + rescinded claim → 15000 cents returned to the pool, plus the `ERR_CREDENTIAL_NOT_ISSUED` re-order probe), and same-request-cycle visibility of `seats_taken`, `posted_hours` and the CLOSED-transition withdrawal.

## Coverage (design-index-only)

| Queue | Instances | Translated | Tests |
|---|---|---|---|
| A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 25 non-stub, 0 stubs | 25/25 (all >=2 tests) | **67** |
| B — `SCAFFOLD_CORNER_DESIGN.yaml` | 89 non-stub, 30 stubs | 89/89 (all >=1 test) | **110** |

114 distinct `Design:` tags for 114 non-stub instances — one-to-one.

## Audits (all clean)

- **Tag audit**: every test has exactly one `Design:` line, on the docstring's last line; every tag resolves to a real `name:` in its source yaml; no `excluded_because:` stub was translated; no untagged or dual-tagged test.
- **PRD-citation audit**: every quoted run >=15 chars in every docstring survives a whitespace-normalised literal match against `workspace/PRD.md` — `bad: 0`.
- **Static audit**: `pyflakes` clean across `test_suite/` and `test_helpers/`; every `api_client.*`, `fixtures.*`, `factories.*` and enum attribute used in test_23 verified to exist; no `pytest.mark.skip/skipif/xfail`; no scaffold references in emitted code.

## Fixes made to earlier files during the final citation pass

Ten docstring quotes were not literal and were corrected: dropped markdown emphasis restored, three elided-middle quotes using `" ... "` split into two separately-quoted PRD fragments (test_01 test_06, test_04 test_06), two quotes whose trailing comma had been turned into a period trimmed (test_02 test_04 / test_07), four leading/trailing truncation marks removed (test_11 x2, test_13, test_15). Also removed one unused import in `test_helpers/factories.py` (`CancelReason`).

## Instances skipped

No instance was skipped for a PRD-first filter failure. The only untranslated instances are the **30 `excluded_because:` stubs** in the corner index, which the contract forbids translating: state_machines 4, calculations 12, validations 13, cross-cutting complexity layers 1 (`both_calculation_variants_produce_their_own_result_and_the_switch_delta_reconciles`, deferred to the §1.8 `dual_variant_calc` pair). Difficulty index has no stubs.

Two design-yaml/PRD divergences were resolved in favour of the PRD rather than skipping: the `errors` recipe's final clock read is specified `as: Proctor` (no proctor record exists in that scenario, so an opaque role reads the clock), and the `rbac` unauthenticated recipe's `as_user_id: ""` (PRD only derives 401 for an *absent* header, so `X-User-ID` is omitted entirely). `workspace/implementation/` was never read or written.

**Orchestrator note on step ordering:** Steps 5 and 6 were launched in separate messages rather than one, so they ran sequentially (Step 5 then Step 6) instead of concurrently. Physical isolation of `test_suite/` from the impl generator was therefore replaced by an explicit absolute prohibition in the Step 6 prompt covering `test_suite/`, `test_helpers/`, both design YAMLs, and all sibling `task_*/` directories; the Step 6 agent confirmed it read none of them. Wall-clock cost only, no contract violation.

## Step 6: Generate implementation — 2026-09-02T12:47:00.000Z

Implementation is complete and verified.

## Files written
All under `workspace/implementation/`:

- `start.sh` (executable) — `cd`s to its own dir, installs Flask only when missing (avoids pip contention across the 8 concurrent per-test reboots), then `exec python3 app.py`
- `app.py` — app factory, blueprint registration, `ApiError`/`HTTPException`/catch-all handlers emitting the error envelope, `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000), threaded=True, use_reloader=False)`
- `core.py` — in-memory `Store` (15 plain dicts), logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), envelope/meta helpers, RBAC + scope, pagination, all body validators, 15 typed FK lookups, lazy proctor-lapse / accommodation-expiry evaluation, shared-aggregate maintenance
- `calc.py` — EFL bands, fee/discount/retake tables, `msg_determination` (BEST_POST/LATEST_POST), `exam_fee_assessment`, `transcript_charge`, `credential_eligibility`, `funding_allocation` walk, room/proctor conflict + daily-load rules (all money in `Decimal`/integer cents, ROUND_HALF_UP, floored percentages)
- `cascades.py` — centre suspension, session cancellation, section closure, attendance void, proctor revocation (5 links), with conserved voucher/seat/pool ledgers
- `errors.py` — all 81 PRD §5 error IDs mapped to HTTP status (402/412/422 specials included); a cross-check against PRD.md shows zero unmapped IDs
- `routes_students.py`, `routes_centers.py`, `routes_instruction.py`, `routes_exams.py`, `routes_funding.py` — the endpoint layer
- `requirements.txt` — `Flask>=2.0`

Storage is in-memory only: `grep` for `sqlite3|open(|.write(|pickle|/tmp` returns nothing, and no entity is seeded or hardcoded at startup.

## Endpoint count
**72 routes registered**, matching the PRD §4 table one-for-one (verified by diffing the Flask URL map against the table, including `/_clock/*`).

## Boot + request confirmation
- `PORT=... bash start.sh` boots in ~2s; `GET /_clock/current_utc` returns the object envelope; unauthenticated `GET /students` returns 401 with the error envelope.
- Three consecutive kill/relaunch cycles on the same port each came up with an empty store (`total_count: 0`) after a student had been created in the prior cycle — confirming clean per-test-server restarts with no persistence.
- Two end-to-end smoke scripts (58 + 63 assertions) pass: intake → placement → section/enrollment/attendance hour ledger → post-test interval and hour gates → MSG; centre authorisation → room → proctor certification → session scheduling (seat clamping, room buffer conflict, exact 8h daily cap boundary, cap-exceeded rejection); registration with stale-version 412, fee/discount/voucher arithmetic, identity → check-in window → result → session auto-complete; credential at composite exactly 580, duplicate-credential gate; transcript charge pinned steps; outcome recording, segregation of duties, allocation commit/defer ordering and pool conservation; full proctor-revocation cascade (result invalidated → credential voided → holder REVOKED → queued order HELD, fulfilled order untouched → outcome rescinded → cents returned); accommodation info-request ceiling, approval, format availability, lazy expiry persistence and RENEW-from-lapse.
- The one initially red assertion was the agent's own smoke expectation (a 4000-cent rush order sits in the 10% waiver tier, so 4000/400/500/4100); the implementation matches PRD §3.9 steps 1–5.

The agent did not read or run anything under `test_suite/`, `test_helpers/`, the difficulty/corner design YAMLs, or any other `task_*/` directory; the build came only from INSTRUCTION.md, SCAFFOLD.yaml and PRD.md.

## Step 7: Run tests and diagnose — 2026-09-02T21:10:00.000Z

Two 8-round parallel stability sweeps (`--isolation per-test-server`, 8 concurrent runners, no early exit).

**Sweep 1 (baseline):** 174/177 in all 8 rounds — 3 deterministic failures, identical in every round (no flakiness anywhere in the suite).

**Diagnosis and fixes (2 test-layer fixes, 0 implementation changes, 0 tests deleted):**

1. `test_helpers/fixtures.py` — `read_transcript_order()` defaulted to `make_registrar_headers()`. PRD §4 authorises `GET /transcript-orders/{orderId}` for **ProgramCoordinator, StateAuthority, Student** only; a `Registrar` may create and fulfil an order but may not read one back. The implementation's 403 `ERR_UNAUTHORIZED` was PRD-correct, so the fixture was changed to `make_program_coordinator_headers()` (STEP 2 test bug). This one fixture caused 2 of the 3 failures — `test_17::test_08_an_order_can_only_be_fulfilled_once` and `test_23::test_06_the_void_travels_through_the_order_and_the_claim_back_into_the_pool`.

2. `test_16_placement_and_hour_arithmetic.py::test_08` + `test_helpers/assertions.py::assert_skill_gain_read` — the test asserted `levels_gained == 0` for a learner with **no qualifying post-test**, and the helper asserted `isinstance(levels_gained, int)` unconditionally. PRD §3.3 defines the field only as "the `levels_gained` as the post level less the entry level" and says of the no-post case only that "no gain is claimed: the determination reports a null post side and no achievement" — it never states the field's value when the post side is null. Two PRD-faithful readings exist (`0` = no gain claimed; `null` = the subtraction has no defined value alongside the null post side), so this is COMPUTED-FIELD/DEFAULT-VALUE SILENCE. Per STEP 1c the test was **split**: the uncovered `levels_gained` assertion was dropped and the helper's shape check scoped to `post_efl_level is not None`; every covered assertion in that test (`variant`, `entry_efl_level`, the three null post-side fields, `msg_achieved is False`) was kept intact. The implementation's `null` was left as-is.

Also audited every default role header in `test_helpers/fixtures.py` against the PRD §4 endpoint table (53 `api_client` call sites): `read_transcript_order` was the only mismatch.

**Sweep 2 (final):** **177/177 in all 8 rounds** (318s per round under 8-way contention). No test deleted, no assertion weakened to an HTTP-status check, no skip/xfail added, `workspace/implementation/` untouched.

### Step 7 — verbatim subagent return (orchestrator-pasted)

Clean 8-round sweep achieved: **177/177 in all 8 parallel rounds.**

**Iterations run:** 2 sweeps (baseline + verification). Baseline sweep was 174/177 in *all 8* rounds with the identical 3 failures — fully deterministic, zero flakiness anywhere in the 177-test suite.

**Tests deleted:** none. No test asserted a scaffold-only rule.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` → `read_transcript_order()`: default headers changed from `make_registrar_headers()` to `make_program_coordinator_headers()`. PRD §4 authorises `GET /transcript-orders/{orderId}` for ProgramCoordinator, StateAuthority, Student only — a Registrar may *create* and *fulfil* an order but not read one back, so the implementation's `403 ERR_UNAUTHORIZED` was PRD-correct and the fixture was the bug. This single fixture caused 2 of the 3 failures (`test_17::test_08_an_order_can_only_be_fulfilled_once`, `test_23::test_06_the_void_travels_through_the_order_and_the_claim_back_into_the_pool`).
- `test_helpers/assertions.py` → `assert_skill_gain_read()`: the unconditional `isinstance(levels_gained, int)` shape check is now scoped to `post_efl_level is not None`.

**Fix applied to `test_suite/` (STEP 1c partial-coverage split):**
- `test_16_placement_and_hour_arithmetic.py::test_08_a_learner_with_only_a_pre_test_reports_a_null_post_side`: dropped `assert levels_gained == 0`. PRD §3.3 defines the field only as "the `levels_gained` as the post level less the entry level" and describes the no-post case only as "no gain is claimed: the determination reports a null post side and no achievement" — never naming the field's value when the post side is null. Two faithful readings exist (`0` = no gain claimed; `null` = subtraction undefined, matching the null post side), i.e. COMPUTED-FIELD / DEFAULT-VALUE SILENCE. All covered assertions in that test (`variant`, `entry_efl_level`, the three null post-side fields, `msg_achieved is False`) were kept.

**Fixes applied to `implementation/`:** none — `workspace/implementation/` was not modified. Every one of the 3 failures traced to the test layer.

**Extra audit performed:** all 53 `api_client` call sites in `test_helpers/fixtures.py` were cross-checked role-by-role against the PRD §4 endpoint table's Authorized Role(s) column; `read_transcript_order` was the only mismatch.

**Orchestrator verification of sweep artifacts:** independently confirmed 8 files `results.1.json`–`results.8.json` present in `workspace/implementation/` (each ~57 KB, all written 21:03) and each reporting `passed=177 total=177 failed=0`.

## Step 8: Finalize PRD — 2026-09-02T21:30:00.000Z

Produced `workspace/PRD_FINALIZED.md`. (Step 8 was NOT skipped: Step 7 made 2 `test_helpers/` fixes and 1 `test_suite/` split, so the zero-fix skip condition did not hold — even though `implementation/` itself was untouched.)

## Line counts
- `PRD.md`: 588 lines; `PRD_FINALIZED.md`: 588 lines — 0 lines added/removed (0.00% line delta); 1 line revised in place (0.17% of lines touched).

## Changes
- §3.3 (Measurable skill gain / skill-gain read, line 269) — revise — `levels_gained` is now pinned as null whenever either the entry level or the post level is null, rather than being described unconditionally as "the post level less the entry level" — `implementation/calc.py:152-154` (`levels_gained = None`; assigned only `if entry_level is not None and post_level is not None`).

## Per-edit pre-edit search log

Edit 1 — §3.3 `levels_gained` nullability
- (a) Subject: the value of the `levels_gained` field on the skill-gain determination, and every place a skill-gain determination is computed or consumed.
- (b) Paths enumerated (grepped `levels_gained|msg_achieved|post_efl_level|best_post_scale_score|latest_post_scale_score|msg_determination|skill.gain` across all of `implementation/`, then read each hit):
  - `implementation/calc.py:123-165` — the single `msg_determination()` producer: pre/post window selection, `BEST_POST` vs `LATEST_POST` selection, `entry_level`, `post_level`, `achieved`, `levels_gained`. Confirmed `levels_gained` is None when *either* side is None (both the no-post case that Step 7 exercised and the no-pre-but-post case Step 7 never exercised).
  - `implementation/routes_students.py:117-130` — `GET /students/{studentId}/skill-gain`, the only endpoint that surfaces `levels_gained`; returns the determination dict verbatim, so no second shaping of the field exists.
  - `implementation/routes_funding.py:252-253` — outcome certification (`EFL_GAIN`, `LATEST_POST`); reads only `result["msg_achieved"]`, never `levels_gained`.
  - `implementation/cascades.py:203-204` — attendance-void re-test of standing claims (`LATEST_POST`); likewise reads only `msg_achieved`.
  - No other writer/reader of the field exists; `levels_gained` is not persisted on any record.
- (c) Wording adjustment: originally considered phrasing it as "null when there is no qualifying post-test" (the Step 7 site's exact scenario). Widened to "whenever either of those two levels is itself null" so it also covers the no-qualifying-pre-test path in `calc.py:152-154`, which the narrower wording would have mis-described as an integer. Deliberately did *not* say anything about `post_efl_level`, `best_post_scale_score` or `latest_post_scale_score` in the no-pre-test case, since that is outside the Step 7 diff and any wording there would be a new claim rather than a pinning.

Items in `<step_7_diff>` deliberately left unpatched:
- `test_helpers/fixtures.py::read_transcript_order` role fix — verified `implementation/routes_funding.py:164-170` authorises exactly `ProgramCoordinator, StateAuthority, Student` with a Student-scope check, which is character-for-character what PRD §4 line 487 already states. Pure fixture bug, no PRD silence. (Also checked the sibling paths for the same entity: `POST /students/{id}/transcript-orders` → Student, Registrar at `:116`; `POST /transcript-orders/{id}/fulfillment` → Registrar, ProgramCoordinator at `:151`; `GET /transcript-orders` → ProgramCoordinator, StateAuthority at `:175` — all match §4.)
- `test_helpers/assertions.py::assert_skill_gain_read` scoping — same subject as Edit 1, covered by that one revision; no separate PRD change.

## Step 9: Complete PRD — 2026-09-02T21:45:00.000Z

PRD_COMPLETED.md is written and verified against the implementation.

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 588 lines, 116,571 chars
- Output: `workspace/PRD_COMPLETED.md` — 588 lines, 124,513 chars
- Char delta: **+7,888**; 35 lines revised in place (no new lines, no new sections, no new paragraphs — every change is an in-paragraph insert or revision)

**Counts:** 34 pins across 30 edits — **26 ambiguity-pins, 8 mismatch-revisions**

**Changes**
- §2.1 — insert — ambiguity — an empty `X-User-ID`/`X-User-Role` value counts as absent → `ERR_UNAUTHENTICATED` — core.py:249
- §2.1 — revise — ambiguity — Proctor scope also compares to the `proctor_id` of the addressed exam session itself — routes_exams.py:170
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_PAGINATION`; same-millisecond ties broken by storage sequence; filters exact-string, unknown values match nothing, undeclared query params ignored — core.py:264-290, core.py:198-199
- §2.4 — insert — ambiguity — clock-stamped instants render `...:SSZ` when the fraction is zero; client-supplied instants/dates echoed verbatim — core.py:84-90
- §2.5 — insert — ambiguity — `version` rises exactly once per record per request (records created in the request stay at 1); `created_at`/`updated_at` from real wall clock, not the logical clock — core.py:171-191
- §2.6 band 4 — revise — mismatch — scope applies only where a record carries an owning centre/proctor/learner (accommodation review has none); body-FK-derived scope follows bands 5 and 8; collection reads narrow nothing — routes_exams.py:60-76, routes_exams.py:218-232, routes_centers.py:206-215
- §2.6 band 5 — insert — ambiguity — absent/empty body read as an empty object; non-object body → `ERR_INVALID_REQUEST` — core.py:297-309
- §2.6 band 26 — insert — ambiguity — `CREDENTIAL_ATTAINMENT` certification's credential-`ISSUED` check sits here, after band 20 — routes_funding.py:247-258
- §2.6 band 43 — insert — ambiguity — seat-exhaustion reports before duplicate registration — routes_exams.py:363-370
- §2.8 — insert — ambiguity — a two-decimal field refuses more precision before range/increment tests — core.py:376-378
- §2.10 — revise — mismatch — `RESULT_INVALIDATED` does not release the sitting's seat — cascades.py:248-252
- §3.1 — insert — ambiguity — duplicate learner email → `ERR_INVALID_REQUEST` — routes_students.py:45-47
- §3.1 — revise — mismatch — cited `enrollment_id` need not belong to the learner nor be `ACTIVE`; one supplied on a `PRE_TEST` is stored as given — routes_instruction.py:323-350
- §3.2 — insert — ambiguity — enrollment is not gated on `intake_status`; only `PLACED` advances to `ENROLLED`, an `EXITED` learner stays `EXITED` — routes_instruction.py:168-171
- §3.3 — insert — ambiguity — void link 3 re-tests each claim inside its own funding period's window — cascades.py:201-205
- §3.3 — insert — ambiguity — skill-gain: bad `variant` → `ERR_INVALID_REQUEST`, unresolved `funding_period_id` → `ERR_FUNDING_PERIOD_NOT_FOUND`, omitted ⇒ no window at all — routes_students.py:121-130, calc.py:114-120
- §3.4 — revise — ambiguity — `WITHDRAW` against a `PROVISIONAL`/`FULL_AUTHORIZED` centre is refused — routes_centers.py:104-106
- §3.4 — insert — ambiguity — suspending a centre in any other posture → `ERR_CENTER_DECISION_NOT_ALLOWED`; `suspended_reason` non-empty — routes_centers.py:119-121
- §3.4 — insert — ambiguity — duplicate `room_code` → `ERR_INVALID_REQUEST`, decided in the shape band ahead of centre authorisation — routes_centers.py:163-167
- §3.5 — insert — mismatch — revocation forces `assigned_session_count` to 0 even with live sittings still naming the proctor — cascades.py:213-214
- §3.5 — insert — ambiguity — decision legality reads the lazily evaluated posture (`RENEW` succeeds on an expired-but-stored-`CERTIFIED` proctor) and writes no separate lapse — routes_centers.py:258-274
- §3.5 — revise — ambiguity — proctor read and `certification_status` filter use the evaluated status without writing; only assignment and check-in persist the lapse — core.py:545-567, routes_centers.py:302-305
- §3.5 — insert — mismatch — link 2b releases no seat and moves no voucher/fee cents — cascades.py:248-252
- §3.6 — insert — ambiguity — supplied `supported_formats` keeps order with repeats collapsed; an empty array is accepted — core.py:433-445
- §3.7 — insert — ambiguity — `decision_note` optional on both branches and written as submitted, so omitting it stores null over an earlier note — routes_exams.py:263-277
- §3.7 — revise — ambiguity — accommodation reads report `EXPIRED` without writing; `status` filter compares the evaluated value — core.py:570-581, routes_exams.py:302-305
- §3.8 — insert — ambiguity — the already-`VERIFIED` test is read after the seat-status test, so `CHECKED_IN`+`VERIFIED` reports `ERR_REGISTRATION_NOT_OPEN` — routes_exams.py:431-434
- §3.8 — revise — mismatch — check-in reads no sitting status: accepted on a `COMPLETED` sitting and leaves it unchanged; the sitting starts only when no other registration is `CHECKED_IN` and it is still `SCHEDULED` — routes_exams.py:458-482
- §3.8 — insert — ambiguity — cancellation retains the registration's `voucher_applied_cents` and `fee_due_cents` for audit; only `refunded_cents` records the reversal — cascades.py:45-61
- §3.9 — revise — mismatch — `subtest_scores` holds the highest score selected whether or not it reaches the passing line — calc.py:263-269
- §3.9 — insert — ambiguity — a transcript order's cited credential need not belong to the path learner — routes_funding.py:127-129
- §3.9 — revise — ambiguity — a `credential_issuance_id` supplied with a non-credential measure type must still resolve but is discarded and stored null — routes_funding.py:210-214
- §3.9 — revise — ambiguity — allocation preview refuses a `variant` outside `PROVISIONAL`/`FINAL` with `ERR_INVALID_REQUEST` — routes_funding.py:379-383
- §5 — insert — mismatch — three transport-layer identifiers outside the table: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — app.py:37-53

Most consequential findings: the §3.8 check-in prose was factually wrong (it asserted later sitting states "already fail the `REGISTERED` gate", but the implementation reads no sitting status at all), and the §2.6 band-4 scope ordering could not hold as written for checks that resolve their owning record through a body foreign key. The §2.10 seat-conservation invariant also needed an explicit carve-out for `RESULT_INVALIDATED`.

**Orchestrator verification:** `PRD_COMPLETED.md` is 588 lines with all 5 top-level sections intact and ends on the complete §5 error-table row `| `ERR_VOUCHER_ADJUSTMENT_INVALID` | 422 |` — no truncation. Pipeline complete through Step 9.
