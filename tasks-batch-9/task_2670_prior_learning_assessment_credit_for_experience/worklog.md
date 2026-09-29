## Step 1: Create task directory — 2026-09-04T04:17:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2670_prior_learning_assessment_credit_for_experience and its workspace/ subdirectory. Index 2670 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-04T05:59:00.000Z

All three scaffold artifacts are complete, parse cleanly, and pass the linter.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2670_prior_learning_assessment_credit_for_experience/`):
- `SCAFFOLD.yaml` — 3099 lines. §1.0–§1.7 only: 14 entities, 4 state machines (PlaClaim carries three parallel dimensions: assessment_status / fee_status / credit_status), 2 §1.2.1 concurrency rules, 11 calculations, 43 priority-ordered validation rungs, 66 endpoints, 86 errors, 6 roles. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` (verified programmatically).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2100 lines. Single top-level key, 9 rule groups × 2 = 18 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4077 lines. Single top-level key, all 9 claim-extraction-guide sections, 54 instances: entities 12, state_machines 13 (8 full + 5 stubs), calculations 14 (6 + 8), validations 13 (10 + 3), endpoints 7 (4 + 3), errors 8, rbac 4, cross_cutting_complexity_layers 4 (1 + 3), consistency_model 1. 32 full `test_recipe` instances, 22 `excluded_because` stubs.

**Verification results**
- `scaffold_lint.py`: `VERDICT: clean lint` — 968 §1.8+§1.9 calls all conform to §1.5, and every §1.1 FK has reverse-reachability.
- Error-catalog coverage: 86/86 error ids referenced by at least one design instance (0 uncovered). The final gaps were closed by the new `rbac` section (ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_FORBIDDEN_STUDENT_SCOPE, ERR_FORBIDDEN_ASSESSOR_SCOPE, ERR_SEGREGATION_OF_DUTIES) plus an added ERR_CLAIM_NOT_AWARDED assert.
- All 22 stub citations resolve to a real §1.8 instance and use the `rule_id / instance_name` form; no stub carries a `test_recipe`; no instance-name collisions across the two design files.
- Every `claim_type` maps to a declared feature — e.g. `decay_function` is grounded in `assessment_sla_due_at.algorithm: decay_function`, `interval_merge` in the two window calculations.

**Bugs caught and fixed in this pass**
- The rbac assessor-scope instance asserted `AssessorAssignment.status == PENDING`; the declared `initial_state` is `ASSIGNED` (the error id `ERR_ASSIGNMENT_NOT_PENDING` is a misleading name for "not ASSIGNED"). Corrected to ASSIGNED.
- Stub prefixes `validation_priority_pair`, `cross_aggregate_state_gate`, `state_reentry_cycle` were invented rule ids; rewritten to the real `priority_pair_validation_conflict`, `cross_entity_state_dependency`, `non_linear_state_machine`, and three bare-name citations were qualified.
- A capture on `$.data.outcome_count` was invalid (Artifact declares only `outcome_mappings`); changed to `$.data.id`.
- Consistency-model coverage literal recomputed: OC1 PRIMARY (8000 bp × 10000) + OC2 SUPPORTING (2000 bp × 5000) → `provisional_coverage_bp` 9000, not 8000.

## Step 3: Copy shared files — 2026-09-04T05:59:30.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T06:20:00.000Z

The PRD is complete at `workspace/PRD.md` — 558 lines / ~129 KB, built through six incremental heredoc appends plus two small edits, ending cleanly at the last row of the §5 error table (no truncation, no audit footer).

**Structure**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications, 11 subsections: RBAC and the six roles; §2.2 pasted verbatim from `section-2.2-response-structure.md`; pagination; identity/timestamps/the two revision counters; the logical clock; basis points and rounding; the two optimistic-concurrency gates; path-resolution order; the full 43-rung validation ladder in priority order; cascades and derived counters; credit ceilings and the two capacity variants
- §3 Business Logic, 11 subsections: programme/courses/outcomes, the crosswalk, students and claim creation, portfolio evidence, submission/reservation/revision/withdrawal, assessor selection and SLAs, rubric scoring and completion, award/denial/unblock waterfall, appeals, fees and settlement, transcript posting and the graduation audit
- §4 66-endpoint table (Method, Path, Description, Roles); §5 86-error table

**Hard Contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** 153 required identifiers extracted from all 14 entities' `fields[].name`, every endpoint `input`/query/path parameter, and the graduation-audit, clock and sweep output objects. All 153 appear verbatim inside backticks. (The only unmatched `- name:` tokens in the scaffold were the six *calculation variant* names, which are not field identifiers.)
- **Contract 2 — Rule Coverage: PASS.** All 43 validation rungs enumerated in priority order with error IDs, statuses and `applies_to` scopes; both `concurrency_rules` fully expressed (write endpoint, `expected_student_version`/`expected_recommendation_version`, `ERR_STALE_*`, 412); all 11 calculations rendered in prose with every constant as a literal (fee bases 5000/15000/0/7500, 2500/credit, artifact tiers, 2500/6000/1500 bp, discount tiers 10000→500 and 25000→1000; SLA bases 72/240/96/96, multipliers 10000/12500/15000, 5000/8000 bp two-step rounding; buffer 24 h closed-interval vs half-open articulation windows; waterfall skip-and-continue ordering; retention schedule; audit order); every declared transition of all state-machine blocks covered including all system cascades; all 86 errors and all 66 endpoint side-effect sets covered.
- **Contract 3 — §3 Path Purity: PASS.** 1,323 backtick tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combinations; §3 also contains no un-backticked literal paths.

**Six scaffold self-contradictions resolved** (decided once and applied consistently): appeal limit = 1 (validation rung 33 / `ERR_APPEAL_LIMIT_REACHED` over the state machine's "2"); appeal window strictly before `appeal_deadline_at`; `OVERTURNED` sends the claim to `AWARDED` with `assessor_recommendation` `PASS` (both state machines outvote the endpoint's "SCORED"), with `CAP_BLOCKED`/`PLA_CAP` as the no-capacity landing since no error code exists for it; `credits_awarded` in the award body defaults to `credits_requested`; payment field is `method` (endpoint identifier wins over the SM's `payment_method`); `effective_pla_cap_credits` = min(programme ceiling, residency headroom).

The two withheld design files were never opened or grepped, and no sibling task directory was read.

**Orchestrator verification (truncation guard):** `wc -l` = 558; tail ends at the final `ERR_APPEAL_FEE_UNPAID | 402` table row — a real section boundary. Independently counted 66 endpoint rows in §4 and 86 error rows in §5, matching the scaffold catalogues. No regeneration needed.

## Step 6: Generate implementation — 2026-09-04T07:00:00.000Z

The implementation is complete, boots clean, and passed two end-to-end smoke passes with zero unexpected responses.

## Files (all under `workspace/implementation/`)

| file | lines | file | lines |
|---|---|---|---|
| `start.sh` (exec) | 8 | `routes/claims.py` | 550 |
| `requirements.txt` | 1 | `routes/articulation.py` | 317 |
| `app.py` | 64 | `routes/appeals.py` | 256 |
| `errors.py` | 113 | `routes/assignments.py` | 241 |
| `db.py` | 113 | `routes/people.py` | 232 |
| `util.py` | 193 | `routes/portfolios.py` | 207 |
| `middleware.py` | 117 | `routes/catalog.py` | 200 |
| `response.py` | 73 | `routes/invoices.py` | 87 |
| `serializers.py` | 175 | `routes/system.py` | 32 |
| `services/invoice.py` | 206 | `services/sla.py` | 149 |
| `services/selection.py` | 143 | `services/capacity.py` | 132 |
| `services/coverage.py` | 55 | `routes/__init__.py`, `services/__init__.py` | 0 |

Total 3664 lines. All 65 PRD endpoints are registered (verified against the §4 table by dumping `url_map`). Storage is process-memory dicts only — no SQLite, no JSON dump, no `/tmp` cache; `find` confirms no non-source files are produced, and nothing is seeded (a fresh boot returns `total_count: 0` on all eleven list endpoints and the clock reads exactly `2026-08-01T00:00:00Z`).

## Smoke verification (random high port, killed by its own PID; port confirmed free afterwards, no pattern kill used)

Pass 1 (portfolio channel, 40 calls): clock set + monotonicity refusal, program/course/outcomes, student/assessor, claim → portfolio → artifact → portfolio submit (coverage 10000 bp) → claim submit → invoice `22500/500 bp/21375` → fee-gate 402 → overpayment 422 → `FINANCIAL_AID` 422 → payment → auto-selected assignment (`sla_hours` 240) → accept → rubric range/duplicate/incomplete/inconsistent guards → complete (verified 9000, PASS) → stale-version 412 → award → posting → graduation audit (both cap variants) → reversal → sweep.

Pass 2 (credential channel + appeals, 46 calls): recommendation → rule → publish gate → SOD 409 → stale-recommendation 412 → approve (pin 1) → rush `CREDIT_BY_EXAM` claim (`sla_hours` 36) → invoice `15625/500 bp/14844` → named assignment + already-assigned 409 → FAIL completion (verified 3750) → deny → appeal filing (prior scorers snapshotted; invoice repriced to 20544, `PAID → PARTIALLY_PAID`) → appeal-fee 402 → prior-scorer reviewer 409 → auto-selected panel reviewer → `credits_awarded` forbidden 400 → REMAND (claim back to `UNDER_ASSESSMENT` with the four fields cleared, `AUTO_REPLACEMENT` assignment created, 6000-cent refund leaving the **300-cent positive residue unswept** exactly as §3.9 requires) → clock advance + SLA sweep (breach → revoke, `EXPEDITED`, `-2344` service credit, overpayment auto-refunded back to `PAID`, `NO_ELIGIBLE_ASSESSOR` hold) → withdrawal from `UNDER_ASSESSMENT` (5000 bp retention: 6309 retained / 6308 refunded, residue into `waived_cents`, student `fee_paid_net_cents` 6309).

## Spec fixes made this session
- `services/capacity.py::cap_block_cascade` now revokes blocked siblings' open assignments with `revoke_reason` `CAP_BLOCKED` (§3.8 hop).
- `util.TERMINAL_ASSESSMENT_STATES` reduced to the three states §3.5 declares (`SUPERSEDED` removed).
- `services/invoice.py::recompute` gained `extra_refund`, applied **before** the excess sweep so the remand's ordered 6000 cents is never overridden (§3.10 step four).
- Claim submit with no portfolio row now returns rung 34 `ERR_PORTFOLIO_NO_ARTIFACTS` (422) rather than a 404 — rung 16 is explicitly scoped away from claim submission, so rung 34 is the only declared portfolio failure there.
- Appeal read/list roles corrected to include `FacultyAssessor` per the §4 table.

**Orchestrator note:** the subagent reported "65 PRD endpoints" while the §4 table has 66 rows; recorded here as a discrepancy for Step 7 to surface if any test hits a missing route.

## Step 5: Generate unit tests — 2026-09-04T08:16:00.000Z

Both remaining files are written and the suite is complete and verified.

## What was added this session

**`test_suite/test_16_corner_rbac.py`** (751 lines, 9 tests) — the four §1.9 `rbac` instances:
- rung 1 vs rung 2: seven malformed/unresolvable header shapes all answer 401, including an unresolvable `Student` id on a PlaCoordinator-only endpoint (401, not 403); the three opaque roles accept any identifier while the three backed roles need a real row (a Student id offered as `FacultyAssessor`, and vice versa, are 401); seven off-list calls on non-existent path ids all answer 403, proving rung 2 precedes the 404 family.
- rung 3: a peer student is refused all four scoped reads and six scoped writes, the owner and the coordinator succeed, and the owner then walks the claim to SUBMITTED.
- rung 4: E-9002 is refused accept/decline/rubric-score/complete (rubric-score is 403, not the rung-17 409), may still *read* the assignment, list it and read E-9001's rubric score, and is still refused `complete` once the rubric is complete and consistent.
- rung 20: the reviewing officer's self-approval is 409 with the rule untouched, a different officer with the identical payload gets APPROVED/pin 1; a stale `expected_recommendation_version` from either officer answers 412 first (rung 13 above rung 20).

**`test_17_corner_cross_cutting.py`** (435 lines, 4 tests) — the OCC instance (a Registrar PATCH stales the coordinator's token → 412, nothing written, refreshed read succeeds; replaying a successful award is 412 not 409, a current token on an AWARDED claim is 409, an omitted token is 400 — rungs 8 < 12 < 14; three reads leave `version` flat) and the consistency instance (the submit response itself carries SUBMITTED/INVOICED/9000/STANDARD/`submitted_at`, the invoice is fully priced on the next call, ledger and audit are immediate, repeated reads identical; award and posting responses match the very next student read and graduation audit).

## Final state

`test_helpers/` 9 files, 1885 lines. `test_suite/` conftest + 17 files, 9695 lines, **113 tests** (36 queue A across test_01–09, 77 queue B across test_10–17).

Verification: every file `ast.parse`-clean and importable; `bad_cite=0 orphan=0 untagged=0 dual=0`; coverage cross-check against both yamls shows **all 18 queue-A instances and all 54 non-stub queue-B instances tagged, 72 distinct tags, zero stub instances covered, zero tags without a matching instance**; no `skip`/`xfail`/TODO anywhere; unused imports cleared (`assert_sla` in test_01, `PriorityTier` in test_07, `pytest` in test_10); `ls -d workspace/test_*` matches nothing; `workspace/implementation/` and sibling task dirs were never read.

## Design-vs-PRD adjudications made this session (each annotated in-code)

- §4 declares no `GET /programs` collection, so the design's "still shows exactly 1 program" is asserted through the single readable programme row at `version` 1.
- The design's empty-`X-User-ID` probes were dropped: the PRD only requires both headers *present*, so "empty is 401" is not uniquely derived.
- The design's rbac list-scoping claim ("`GET /pla-claims` as S-1002 returns an empty array") is a **gap** — rung 3 does not cover list endpoints and nothing else derives filtering. Not weakened, not stubbed.
- The peer-student artifact read and the claim-creation-on-another's-behalf probes are grounded in §2.1's explicit field enumeration (rung 3's applies-to list omits both); the on-behalf probe uses a fresh course so the duplicate-claim rule cannot answer instead.
- The design's appeal-side SoD sub-assertion is not restated here: naming a prior scorer (409) and a non-panel member (`ERR_ASSESSOR_NOT_ELIGIBLE`, per the earlier adjudication) are already covered in test_14, and "an AppealReviewer deciding an appeal they scored" is **unreachable** — the assign gate can never seat a prior scorer, and a non-assigned decider has no PRD-named code.
- Consistency instance: the design's "the portfolio was locked in the same request (`LOCKED`, `locked_at`)" is wrong — §3.4 locks the portfolio only "When the assessor finishes scoring", and `Portfolio` has no `locked_at` field; the test asserts SUBMITTED with the frozen 9000 and `submitted_at` at the epoch.
- OCC instance: the missing-token refusal is 400 `ERR_INVALID_REQUEST` (rung 8's own literal), not the design's 422; the `expected_student_version` 0/-1 probe was dropped as not uniquely derived (no declared range for that field).

**Orchestrator note:** Step 5 and Step 6 were launched concurrently in a single assistant message, so the impl generator could not see `test_suite/` (it did not exist at its spawn time). Verified `ls -d workspace/test_*` matches nothing — no stray test dirs under workspace/.


## Step 8 — iterate-until-green (3 parallel 8-round sweeps)

Sweep 1: 113 total / 98 passed / 9 failed / 6 errors, identical in all 8 rounds (deterministic, no reaping signature, no load noise). Sweep 2: 112/113 in all 8 rounds. Sweep 3: **113/113 in all 8 rounds.**

Endpoint audit: PRD §4's 66 `| METHOD | path |` rows diffed against the implementation's 66 `@bp.<method>` registrations (after normalising `<var>`→`{var}`) — zero differences, so the earlier "65 endpoints registered" note was a miscount and no route was missing.

No test was deleted. Fifteen failures, all traced to a verbatim PRD sentence:

test_suite/ fixes (STEP 2 — assertion or payload was not faithful to PRD):
- test_15 `_program`/`_course`/`_student`: hardcoded kwargs collided with `**overrides` (6 setup TypeErrors) → merge into a `fields` dict before the single `fx.*` call.
- test_15 `test_a_body_reference_and_a_foreign_child_report_the_row_that_failed`: `artifact_count` is one per mapped outcome, so CS150's two-outcome portfolio holds 2 → `artifact_count=len(scenario["outcomes"])`.
- test_15 `test_the_articulation_reference_family_is_checked_in_the_declared_order`: the three non-`PORTFOLIO` payloads omitted `attempt_date`, which §3.3 says "is likewise required for every source other than `PORTFOLIO`", so rung 8 answered ahead of rung 9b → supply `attempt_date` (the convention every other non-portfolio payload in the suite already follows).
- test_17 `test_the_concurrency_gate_is_read_before_the_terminal_and_shape_rungs`: awarding an `AWARDED` claim is not uniquely determined (§3.5's "any attempt to advance" vs rung 14's applies-to list, which omits awarding, leaving rung 15a's `ERR_CLAIM_NOT_SCORED`) → relaxed to `validate_error_is_one_of([ERR_CLAIM_ALREADY_TERMINAL, ERR_CLAIM_NOT_SCORED])` with the 409 still asserted. test_15 asserts the same operation as `ERR_CLAIM_NOT_SCORED`, so the suite had contradicted itself.
- test_09 `test_reversal_restores_the_ledger_exactly_and_frees_only_the_upper_division_hold`: expected `pla_upper_division_committed=0` after the reversal, but §3.3 counts the freed 3-credit `UPPER` sibling ("aggregates ... the credits requested ... for claims in `SUBMITTED`"), the waterfall's own upper-headroom test would be inert within a pass otherwise, and the cap-blocking cascade it mirrors takes `credits_requested` out of that counter → 3.
- test_09 `test_the_pla_cap_hold_survives_the_reversal_and_the_re_posting`: with 3 of the 6 upper-division credits handed to the freed sibling, rung 38 ("Applies to awarding a claim and posting to the transcript") refuses the 6-credit re-post → assert `ERR_UPPER_DIVISION_CAP_EXCEEDED` (409) and that the refusal wrote nothing.
- test_10 `test_program_creation_computes_the_cap_from_the_binding_arm` and `test_student_system_fields_are_server_generated`: three `assert_instant(created_at/updated_at, CLOCK_EPOCH)` assertions dropped under STEP 1c. §2.4 fixes only the rendering of the two row-audit stamps and §2.5 scopes the logical clock to "all deadline, validity-window and service-level comparisons", so their source is not uniquely derivable; replaced with the verbatim §2.4 shape rule plus, for the student, the check that the client-supplied `created_at` was not echoed. Every other assertion in both tests was kept.

test_helpers/ fixes:
- assertions.py: new `assert_instant_shape` asserting §2.4's "ISO 8601 UTC timestamps with three fractional digits" for stamps whose source the PRD leaves open.

implementation/ fixes:
- routes/claims.py `create_claim`: added rung 3's body-scope check — §2.1 "a claim's `student_id` ... must equal `X-User-ID`; otherwise the request fails with `ERR_FORBIDDEN_STUDENT_SCOPE` (403)". A peer student could previously open a claim for someone else.
- routes/claims.py `submit_claim`: rung 34 (`ERR_PORTFOLIO_NO_ARTIFACTS`) now precedes the portfolio-status check, because rung 16's applies-to list covers "adding an artifact, deleting an artifact and submitting a portfolio" and not claim submission, while rung 34 covers "submitting a portfolio and submitting a claim".
- middleware.py: new `scoped_artifact` (§2.1 "an artifact's grandparent claim's `student_id` ... must equal `X-User-ID`"), judging scope on an existing row before the 404, exactly as `scoped_claim`/`scoped_portfolio`/`scoped_invoice` do.
- routes/portfolios.py `read_artifact`: uses `scoped_artifact`; `GET /artifacts/{id}` previously returned 200 to a peer student.

## Step 7: Run tests and iterate — 2026-09-04T09:15:00.000Z

(Note: the Step 7 subagent appended its own section above under the mislabelled heading "## Step 8 — iterate-until-green"; that heading refers to this step, not to Step 8. The subagent's returned summary is reproduced verbatim below as the authoritative record.)

GREEN — three iterations, final sweep is 113/113 in all 8 parallel rounds.

## Summary

**Iterations run: 3** (each a parallel 8-round `setsid nohup` stability sweep, all rounds joined with `wait`)
- Sweep 1: `113 total / 98 passed / 9 failed / 6 errors` — byte-identical in all 8 rounds (deterministic; no reaping signature, no load noise)
- Sweep 2: `113 / 112 / 1 / 0` in all 8 rounds
- Sweep 3: **`113 / 113 / 0 / 0` in all 8 rounds** (~216 s per round)

**Tests deleted: none.** All 15 failures traced to a verbatim PRD sentence. Three assertions were dropped under STEP 1c (partial coverage) rather than deleting their tests:
- `test_10_corner_entities.py` — three `assert_instant(created_at/updated_at, CLOCK_EPOCH)` assertions in `test_program_creation_computes_the_cap_from_the_binding_arm` and `test_student_system_fields_are_server_generated`. Category: **source silence** — §2.4 fixes only the *rendering* of the two row-audit stamps ("ISO 8601 UTC timestamps with three fractional digits") and §2.5 scopes the logical clock to "all deadline, validity-window and service-level comparisons", so a faithful implementer may stamp them from wall clock. Replaced with the verbatim §2.4 shape rule plus, for the student, a check that the client-supplied `created_at` was not echoed. Every other assertion in both tests kept.

**Fixes applied to `test_suite/`** (STEP 2 — assertion/payload was not faithful to PRD):
- `test_15_corner_errors.py` `_program`/`_course`/`_student` builders — hardcoded kwargs collided with `**overrides` (the 6 setup `TypeError`s); merged into a `fields` dict before the single `fx.*` call.
- `test_15` `test_a_body_reference_and_a_foreign_child_report_the_row_that_failed` — `artifact_count` is one per mapped outcome, so CS150's two-outcome portfolio holds 2; asserted `len(scenario["outcomes"])`.
- `test_15` `test_the_articulation_reference_family_is_checked_in_the_declared_order` — the three non-`PORTFOLIO` payloads omitted `attempt_date`, which §3.3 says "is likewise required for every source other than `PORTFOLIO`", so rung 8 answered ahead of rung 9b; supplied `attempt_date` (the convention every other non-portfolio payload in the suite already uses).
- `test_17_corner_cross_cutting.py` `test_the_concurrency_gate_is_read_before_the_terminal_and_shape_rungs` — awarding an `AWARDED` claim is not uniquely determined (§3.5's "any attempt to advance" vs rung 14's applies-to list, which omits awarding, leaving rung 15a); relaxed to the sanctioned `validate_error_is_one_of([ERR_CLAIM_ALREADY_TERMINAL, ERR_CLAIM_NOT_SCORED])`, 409 still asserted. `test_15` asserts the identical operation as `ERR_CLAIM_NOT_SCORED`, so the suite had contradicted itself.
- `test_09_compensating_invariants.py` `test_reversal_restores_the_ledger_exactly_...` — expected `pla_upper_division_committed=0`; §3.3 counts the freed 3-credit `UPPER` sibling ("aggregates … the credits requested … for claims in `SUBMITTED`"), the waterfall's own upper-headroom test would be inert within a pass otherwise, and the cap-blocking cascade it "mirrors" explicitly removes `credits_requested` from that counter → 3.
- `test_09` `test_the_pla_cap_hold_survives_the_reversal_and_the_re_posting` — with 3 of the 6 upper-division credits handed to the freed sibling, rung 38 ("Applies to awarding a claim **and posting to the transcript**") refuses the 6-credit re-post; now asserts `ERR_UPPER_DIVISION_CAP_EXCEEDED` (409) and that the refusal wrote nothing.

**Fixes applied to `test_helpers/`:**
- `assertions.py` — new `assert_instant_shape()` asserting §2.4's three-fractional-digit UTC rendering, for stamps whose source the PRD leaves open.

**Fixes applied to `implementation/`:**
- `routes/claims.py::create_claim` — added rung 3's body-scope check (§2.1 "a claim's `student_id` … must equal `X-User-ID`; otherwise … `ERR_FORBIDDEN_STUDENT_SCOPE` (403)"); a peer student could open a claim for someone else.
- `routes/claims.py::submit_claim` — rung 34 (`ERR_PORTFOLIO_NO_ARTIFACTS`) now precedes the portfolio-status check, since rung 16's applies-to list covers artifact add/delete and portfolio submit but *not* claim submit, while rung 34 covers "submitting a portfolio and submitting a claim".
- `middleware.py` — new `scoped_artifact()` (§2.1 "an artifact's grandparent claim's `student_id` … must equal `X-User-ID`"), judging scope on an existing row before the 404, matching `scoped_claim`/`scoped_portfolio`/`scoped_invoice`.
- `routes/portfolios.py::read_artifact` — now uses `scoped_artifact`; `GET /artifacts/{id}` previously returned 200 to a peer student.

**Other findings:** the "65 vs 66 endpoints" note was a miscount — diffing PRD §4's 66 route rows against the implementation's 66 `@bp.<method>` registrations (with `<var>`→`{var}` normalised) shows zero differences, so no route was missing. Storage remains in-memory dicts only (no SQLite, no file dumps, no `/tmp` cache). `results.*.json`, `sweep.log`, `__pycache__` and `.pytest_cache` cleaned up.

**Orchestrator verification:** because the subagent deleted its own `results.*.json`, the orchestrator re-ran the full 8-round `setsid nohup` sweep itself to confirm the green claim independently and to leave the per-round artifacts on disk as the skill's output spec requires. Result recorded below.

**Orchestrator sweep result (independent re-run, 8 rounds under `setsid nohup`, `--isolation per-test-server`):** all 8 rounds `113 / 113`, 0 failed, 0 errors. `workspace/implementation/results.{1..8}.json` are on disk. Step 7's green claim confirmed.

## Step 8: Finalize PRD — 2026-09-04T09:13:00.000Z

`workspace/PRD_FINALIZED.md` is written.

## Size
- PRD.md: 558 lines / 129,080 bytes. PRD_FINALIZED.md: 558 lines / 132,760 bytes.
- Line count delta 0% (10 lines revised in place, no lines added/removed); byte delta +2.85%.

## Changes (10 revised lines, 8 edits)

- **§2.4 (line 88)** — revise — `created_at`/`updated_at` are server-generated, never taken from the body (a client-supplied `created_at` is ignored), and are read from real wall-clock time, not the §2.5 logical clock; `api_request_timestamp` likewise — `implementation/db.py:44,47`, `util.py:126`, `response.py:16`
- **§2.9 rung 3 (line 134)** — revise — applies-to list gains "creating a claim" (body `student_id` scope-checked ahead of the body-reference rung, when supplied as a string) and "reading one artifact"; list endpoints are not scope-filtered — `routes/claims.py:96-98`, `routes/portfolios.py:193`, `middleware.py:102-112`
- **§2.9 rung 16 (line 147)** — revise — claim submission is deliberately absent from rung 16 even though it inspects portfolio `status`; its portfolio checks sit at rung 34 and below — `routes/claims.py:284-292`
- **§2.9 rung 34 (line 165)** — revise — on claim submission a `PORTFOLIO`-source claim with no portfolio row at all also fails this rung — `routes/claims.py:289`
- **§2.9 rung 38 (line 169)** — revise — the counter is read with this claim's own already-made contribution excluded (pointer to §3.8/§3.11) — `routes/claims.py:438,509-513`, `services/capacity.py:45-49`
- **§3.5 (line 264)** — revise — order and error codes of the two portfolio preconditions on claim submit: missing portfolio or zero artifacts → `ERR_PORTFOLIO_NO_ARTIFACTS` (422), never a 404, even when the portfolio is also not `SUBMITTED`; only a portfolio clearing the floor in a non-`SUBMITTED` status → `ERR_PORTFOLIO_NOT_SUBMITTABLE` (409) — `routes/claims.py:284-292`
- **§3.5 (line 278)** — revise — the terminal-claim refusal is scoped to rung 14's exhaustive list; awarding / posting / reversal are absent and answer with their own rung-15 errors (`ERR_CLAIM_NOT_SCORED`, `ERR_CLAIM_NOT_AWARDED`, `ERR_CREDIT_NOT_POSTED`) — `routes/claims.py:420-421,489-493,539-540` (no `_not_terminal` call in those three)
- **§3.8 waterfall (line 332)** — revise — a released `UPPER` candidate's `credits_requested` also re-enters `pla_upper_division_committed`, and the running upper-division headroom is reduced by it — `services/capacity.py:96-98`
- **§3.11 (line 378)** — revise — posting's upper-division re-check excludes this claim's own contribution: subtracted out on a first posting, read as-is on a re-posting of a `REVERSED` claim, so a re-post can fail where the original passed — `routes/claims.py:509-513`
- **§3.11 (line 380)** — revise — `pla_upper_division_committed` untouched by a first posting, raised by `credits_awarded` on a re-posting — `routes/claims.py:525-526`

## Per-edit pre-edit search log

1. **§2.4 timestamps.** (a) Subject: source of every timestamp the system stamps. (b) Grepped `real_now|db.clock|clock_raw` across all of `implementation/`; read `db.py:new_row`, `util.py:touch/fmt_dt`, `response.py:16`; grepped `created_at|updated_at` across `routes/` and `serializers.py` to confirm no route ever reads either from the body. Clean split: `created_at`/`updated_at`/`api_request_timestamp` wall-clock; `submitted_at`, `appeal_deadline_at`, `accepted_at`, `rubric_submitted_at`, `filed_at`, appeal `assigned_at`, `decided_at`, assignment `assigned_at`/`due_at`/`at_risk_at` all `db.clock`. (c) Deliberately did **not** write "all timestamps"; named only the two row-audit stamps plus the envelope stamp, and pointed at §3 for the logical-clock instants rather than enumerating them. Left §2.5's "never against wall-clock time" (a claim about *comparisons*) untouched.

2. **Rung 3 list.** (a) Subject: student-ownership scope enforcement. (b) Grepped `scoped_claim|scoped_portfolio|scoped_artifact|scoped_invoice|enforce_student_scope` across `routes/`; read `middleware.py` in full and `routes/invoices.py:27-59`. Enforcing: create/read/submit/withdraw claim, read/submit portfolio, add/delete artifact, read artifact, read invoice, pay invoice, waive (coordinator-only, inert), file appeal, graduation audit. Not enforcing: `create_portfolio`, and every list endpoint. (c) Added "whenever it is supplied as a string" so the wording does not claim the check fires when `student_id` is absent or non-string (impl then falls through to rungs 7/8), and added "List endpoints are not scope-filtered" so the addition of "reading one artifact" is not read as covering `GET /artifacts`.

3. **Rung 16 note.** (a) Subject: which operations consult portfolio `status` and at what rung. (b) Read `routes/portfolios.py::submit_portfolio` (rung 16 *before* rung 34), `add_artifact`, `delete_artifact`, and `routes/claims.py::submit_claim` (rung 34 *before* the status check). (c) Phrased as "claim submission is absent from that list" rather than restating an order, so the rung-16 ordering inside `submit_portfolio` — which is the reverse — is not contradicted.

4. **Rung 34 note.** (a) Subject: the artifact floor's treatment of a missing portfolio. (b) Read `routes/claims.py:285-290` (`portfolio is None or artifact_count < 1`) and `routes/portfolios.py:100` (portfolio always exists there, path-resolved). (c) Scoped the addition to "on claim submission", since the missing-row case cannot arise on portfolio submission.

5. **Rung 38 note.** (a) Subject: the upper-division sub-cap formula. (b) Read `services/capacity.py::upper_division_remaining` and `own_reservation`; every callsite — `claims.py:298` (submit), `claims.py:438` (award), `claims.py:509-513` (posting, its own inline variant), `capacity.py:82` (waterfall, raw counter), and confirmed `routes/appeals.py` OVERTURNED runs **no** rung-38 check at all. (c) Wrote "whatever contribution this same claim has already made to it excluded" — deliberately loose — because the excluded quantity differs by callsite (`credits_requested` at award/submit, `credits_awarded` on a first posting, nothing on a re-post or in the waterfall). Did not touch §2.11's flat "single number in both variants" sentence, and did not extend the note to the appeal-overturn path, which has no such check.

6. **§3.5 portfolio preconditions.** (a) Subject: claim-submit portfolio gate. (b) Read `routes/claims.py:284-292` plus `db.portfolio_of_claim`, and cross-read `submit_portfolio` for contrast. (c) Named both error codes with their HTTP statuses and added "never with a 404", matching the impl's explicit rejection of the 404 route; kept it inside the claim-submit paragraph so portfolio submission is unaffected.

7. **§3.5 terminal states.** (a) Subject: where `ERR_CLAIM_ALREADY_TERMINAL` is raised. (b) Grepped/read every `_not_terminal` callsite (`submit_claim`, `withdraw_claim`, `request_revision`, `deny_claim`) plus the two inline copies (`routes/assignments.py:41`, `routes/appeals.py:53`) — exactly rung 14's six operations; confirmed `award_claim`, `post_transcript`, `reverse_transcript` have none. (c) First draft said a terminal claim gets `ERR_CREDIT_NOT_POSTED` on reversal — **wrong**, because reversal of an `AWARDED`+`POSTED` claim is the normal success path and posting *requires* the terminal `AWARDED` state. Rewrote to say reversal reads only the `credit_status` dimension and that the credit dimension does its work on an already-terminal claim, so the sentence no longer implies the credit endpoints reject terminal claims.

8. **§3.8 waterfall / §3.11 posting.** (a) Subject: every write to `pla_upper_division_committed`. (b) Enumerated and read all nine: `capacity.take_reservation`, `release_reservation`, `unblock_waterfall:96-98`, `cap_block_cascade:125-126`, `claims.award_claim:451-452`, `post_transcript:525-526`, `reverse_transcript:549-550`, `appeals.py:222-223` (OVERTURNED), `appeals.py:244` (REMANDED via `take_reservation`). (c) Anchored the §3.11 claims to `credit_status` (`REVERSED` vs. first posting) rather than to "re-posting" generically, and left §3.3's descriptive aggregate formula alone — §3.11's explicit reversal subtraction already governs the reversed-but-`AWARDED` case, so widening §3.3 would have created a new contradiction.

**Orchestrator verification:** PRD_FINALIZED.md is not byte-identical to PRD.md (558 lines, +2.85% bytes) and ends at the same real section boundary (final §5 error row).

## Step 9: Complete PRD — 2026-09-04T10:23:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` (a single-pass Step 9 has historically no-op'd and left PRD_COMPLETED.md byte-identical to its source). Pass A: the cross-cutting core modules. Pass B: `routes/catalog.py`, `routes/people.py`, `routes/claims.py`, `routes/portfolios.py`. Pass C: the remaining routes plus all of `services/`.

**Size:** PRD_FINALIZED.md 558 lines / 132,760 bytes → PRD_COMPLETED.md 560 lines / 151,169 bytes (**+2 lines, +18,409 chars**). Heading count 30 in both, heading lists diff-empty — no new sections. Last line is still the final §5 error-table row. 61 top-level paragraphs differ from PRD_FINALIZED.md.

**Counts:** pass A 8 ambiguity-pins / 1 mismatch-revision; pass B 21 / 7; pass C 29 / 11. **Total 58 ambiguity-pins, 19 mismatch-revisions across 77 changes.**

### Pass A — core modules (app.py, db.py, util.py, errors.py, middleware.py, response.py, serializers.py)
- §2.1 — insert — ambiguity — an `X-User-Role` outside the six named roles is not entity-backed, so it clears rung 1 and is rejected at rung 2 with `ERR_UNAUTHORIZED` (403), not `ERR_UNAUTHENTICATED` — `middleware.py:41-52`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly twenty uppercase-alphanumeric characters — `util.py:41-43`
- §2.3 — insert — ambiguity — `offset` may not be negative; a non-base-ten-integer value is `ERR_INVALID_REQUEST`; an empty-string parameter is treated as absent and defaults; `offset` has no upper bound and an out-of-range offset yields an empty `data` array with `has_more` false — `response.py:54-73`, `response.py:36-47`
- §2.3 — insert — ambiguity — all list orderings are stable and fall back to row-creation order when the declared keys tie — `db.py:52-57`, `db.py:38-49`
- §2.4 — insert — ambiguity — logical-clock-stamped domain instants render with three fractional digits, while client-supplied instants (`effective_from`, `effective_to`, `attempt_date`, `current_utc`) are echoed verbatim without normalisation; `version` advances at most once per row per request; a no-op amendment still advances `version` — `util.py:80-90`, `util.py:111-126`, `routes/system.py:19-26`
- §2.9 rung 3 — revise — mismatch — ownership can only be judged against an existing row, so a path identifier resolving to nothing answers with its rung-6 404 rather than a scope failure — `middleware.py:81-130`
- §2.9 rung 8 — insert — ambiguity — JSON `null` counts as absent (optional → default, required → missing), except the two deliberately nullable amendment fields (`pla_pass_threshold_bp`, recommendation `effective_to`) which `null` clears; integer fields reject booleans and fractional numbers; string fields must be non-empty — `util.py:139-180`, `routes/catalog.py:101`, `routes/articulation.py:76-82`
- §3.10 — insert — ambiguity — the invoice representation reports the claim's `fee_status` under the same field name, so the two can never read as disagreeing — `serializers.py:168-175`, `routes/invoices.py:20-24`
- §4 — insert — ambiguity — an unrouted path or an unsupported method answers HTTP 404 with `error_id` `ERR_NOT_FOUND` — `app.py:37-43`, `errors.py:34`
- Pass A notes: no serializer field-set mismatches found; `errors.py` `ERROR_STATUS` matches the §5 table exactly (only extra code is `ERR_NOT_FOUND`, pinned in §4 prose rather than as a new §5 row); `util.rhu` sign handling, the clock epoch, and all `util.py` constants were already uniquely pinned.

### Pass B — catalog / people / claims / portfolios routes
- §2.9 rung 3 — revise — mismatch — pass A's "existing row" wording carved out the graduation audit (scope check on the raw path segment, so a Student gets `ERR_FORBIDDEN_STUDENT_SCOPE` even for a nonexistent student) and noted portfolio creation is not scope-checked at all — `people.py:101-103`, `portfolios.py:41-49`
- §2.9 rung 10 — insert — ambiguity — an empty `learning_outcomes` array is reported at this rung, not the shape rung — `catalog.py:117-132`
- §2.9 rungs 21/22 — revise — ambiguity — applies-to lists extended to claim submission, plus note that submission reuses `ERR_ARTICULATION_NOT_APPROVED` for the separate hold gate — `claims.py:256-257,68-71`
- §2.9 rungs 24/25 — insert — ambiguity — intra-rung order pinned (source-membership before course eligibility; enrolment before programme status) — `claims.py:264-269`
- §2.9 rung 37 — revise — mismatch — award lower bound of 1 added; level match pinned as asymmetric (only an UPPER course requires an UPPER recommendation) — `claims.py:429-436`
- §2.9 rung 42 — revise — mismatch — fee rung applies to assignment, award (PAID/WAIVED) and posting (PAID/WAIVED/REFUNDED/RETAINED), not assignment alone — `claims.py:444,518`
- §3.1 — insert — ambiguity — duplicate `program_code` is `ERR_INVALID_REQUEST` — `catalog.py:51-52`
- §3.1 — insert — ambiguity — `allowed_source_types` must be a JSON array; empty, unrecognised or repeated member is `ERR_INVALID_REQUEST` — `catalog.py:22-33`
- §3.1 — insert — ambiguity — amendment re-checks `residency_min_credits` against post-amendment `total_credits_required` — `catalog.py:87-91`
- §3.1 — revise — mismatch — `course_code` is 1-32 chars in any alphabet (not pattern-constrained) and its duplicate check runs after outcome validation; `department_code` allows digits — `catalog.py:140-151`
- §3.1 — revise — mismatch — omitted `mastery_threshold_bp` stores null and 7000 is applied at judging time, not written at creation — `catalog.py:126-129`
- §3.3 — insert — ambiguity — `student_number` 1-32 chars, duplicate is `ERR_INVALID_REQUEST` — `people.py:30,42-43`
- §3.3 — insert — ambiguity — `attempt_date` is optional (not forbidden) on a PORTFOLIO claim and is never window-checked there — `claims.py:135-138`
- §3.4 — insert — ambiguity — an artifact mapping naming a nonexistent outcome yields `ERR_OUTCOME_NOT_IN_COURSE`, never `ERR_OUTCOME_NOT_FOUND` (unlike rubric scores) — `portfolios.py:132-135`
- §3.4 — insert — ambiguity — portfolio submission also bumps the parent claim's `version` — `portfolios.py:110-112`
- §3.4 — revise — mismatch — withdrawal voids a portfolio from DRAFT, SUBMITTED or REVISION_REQUESTED and leaves LOCKED/VOIDED untouched — `claims.py:359-361`
- §3.5 — insert — ambiguity — submission from any other non-terminal state is `ERR_CLAIM_NOT_DRAFT`, plus the full nine-condition evaluation order — `claims.py:249-250,256-300`
- §3.5 — insert — ambiguity — both the course-credits and rule-credits bounds report `ERR_INVALID_CREDIT_REQUEST` — `claims.py:259-262`
- §3.5 — insert — ambiguity — the `hold_reason` gate is tested first and answers `ERR_ARTICULATION_NOT_APPROVED` for any non-null value — `claims.py:256-257`
- §3.5 — insert — ambiguity — upper-division cap excludes the claim's own existing commitment; a parking submission releases a held reservation and leaves the invoice untouched — `claims.py:298,305-320`
- §3.5 — insert — ambiguity — withdrawal from SCORED/DENIED/APPEAL_PENDING is `ERR_CLAIM_NOT_DRAFT`; terminal states are caught a rung earlier — `claims.py:348-349`
- §3.5 — insert — ambiguity — withdrawal settlement yields `REFUNDED` only when the refunded half is positive, else `WAIVED` — `claims.py:366`, `services/invoice.py:202`
- §3.6 — revise — ambiguity — `employee_number` 1-32 chars with duplicate → `ERR_INVALID_REQUEST`; `department_code` same domain as a course's; `max_concurrent_assignments` defaults to 10 — `people.py:155,159,169-170`
- §3.6 — insert — ambiguity — `appeal_panel_member` filter accepts true/false/1/0 in any case, empty as absent, else `ERR_INVALID_REQUEST` — `people.py:203-209`
- §3.8 — insert — ambiguity — a FAIL recommendation fails as `ERR_CLAIM_NOT_SCORED` — `claims.py:421`
- §3.8 — insert — ambiguity — `credits_awarded` of 0 is `ERR_AWARD_EXCEEDS_RECOMMENDATION`; the fee gate is the last check, so a cap breach outranks non-payment — `claims.py:431-444`
- §3.11 — revise — mismatch — `posted_term` is 1-32 chars; posting accepts PAID/WAIVED/REFUNDED/RETAINED and tests the fee last — `claims.py:487,518`
- §2.3 — insert — ambiguity — list filters use exact case-sensitive equality with no enum/id validation, empty string means absent, multiple filters AND together, unknown params ignored, sole exception the boolean assessor filter — verified across every list route

### Pass C — articulation / appeals / assignments / invoices / system routes + all services
- §2.9 r4 — insert — ambiguity — appeal-decision reviewer-identity check answers `ERR_FORBIDDEN_ASSESSOR_SCOPE`, after the row resolves and only when a reviewer exists — `routes/appeals.py:175`
- §2.9 r21 / r22 — insert — ambiguity — overturning an appeal added to both applies-to lists — `routes/appeals.py:160,164`
- §2.9 r25 — insert — ambiguity — overturn runs the programme test alone, not the enrolment test — `routes/appeals.py:212`
- §2.9 r31b — insert — ambiguity — acceptance also answers `ERR_ASSESSOR_INACTIVE`, behind the assignment-state rung — `routes/assignments.py:99`
- §2.9 r37 — insert — ambiguity — the level half also guards submit-for-review — `routes/articulation.py:220`
- §3.2 — insert — ambiguity — `credential_code` is 1–32 chars; duplicate `(source_type, credential_code)` is `ERR_INVALID_REQUEST` tested after all other field domains — `routes/articulation.py:24,33`
- §3.2 — insert — ambiguity — publish's `effective_to` ordering failure is `ERR_INVALID_REQUEST` (400), after the `DRAFT` from-state check — `routes/articulation.py:92`
- §3.2 — insert — ambiguity — amend's from-state precedes field validation; both counters advance on a no-op body; publication's ordering check is not re-run — `routes/articulation.py:68`
- §3.2 — insert — ambiguity — rule drafting's `awarded_credits > recommended_credits` is `ERR_INVALID_REQUEST` (400) — `routes/articulation.py:184`
- §3.2 — insert — ambiguity — submit-for-review's three gates in order with `ERR_RECOMMENDATION_NOT_PUBLISHED` / `ERR_INVALID_REQUEST` / `ERR_LEVEL_MISMATCH` — `routes/articulation.py:214`
- §3.2 — insert — ambiguity — the institutional hold leaves the portfolio untouched (no reopen, no portfolio `revision_round`/`version`) — `routes/articulation.py:102` vs `routes/claims.py:391`
- §3.2 — insert — ambiguity — an already-`SUSPENDED` rule keeps its `suspend_reason` on retirement; `DRAFT`/`UNDER_REVIEW` rules are untouched — `routes/articulation.py:135`
- §3.2 — revise — mismatch — retirement hop four bumps the student's `version` only when `fee_paid_net_cents` actually moves — `services/invoice.py:115`
- §3.6 — revise — mismatch — the fee gate is rung 42, tested after selection, so an unusable assessor outranks an unpaid fee — `routes/assignments.py:59`
- §3.6 — revise — mismatch — named-candidate precedence replaces "failing only": segregation → already-assigned → inactive → other eligibility → capacity — `services/selection.py:88`
- §3.6 — revise — mismatch — posture recomputes only for live assignments, on listing/acceptance/sweep; a single read does not recompute — `services/sla.py:62`, `routes/assignments.py:68,81`
- §3.6 — insert — ambiguity — terminal assignments freeze both `elapsed_bp` and `sla_state` at the instant they left the live pair — `services/sla.py:71`
- §3.6 — insert — ambiguity — acceptance's inactive-assessor refusal is `ERR_ASSESSOR_INACTIVE` (409) behind the from-state check — `routes/assignments.py:96`
- §3.6 — insert — ambiguity — `decline_reason` is required and non-empty — `routes/assignments.py:114`
- §3.6 — revise — mismatch — a single read leaves posture as stored; a listing refreshes before filtering, so `sla_state` filters match fresh values — `routes/assignments.py:81`
- §3.6 — insert — ambiguity — the sweep snapshots candidates (`evaluated_count`), never evaluates its own replacements, and counts `AT_RISK` exclusive of `BREACHED` — `services/sla.py:101`
- §3.6 — insert — ambiguity — `credited_invoice_ids` names every breached claim's existing invoice regardless of effect; `WAIVED`/`REFUNDED`/`RETAINED` survive repricing — `services/sla.py:134`, `services/invoice.py:97`
- §3.8 — revise — mismatch — the cap-blocking cascade fires when reserved-inclusive remaining is 0 or below (the nuance pass B deferred) — `services/capacity.py:114`
- §3.9 — insert — ambiguity — an already-open appeal answers `ERR_APPEAL_LIMIT_REACHED` (409) — `routes/appeals.py:65`
- §3.9 — insert — ambiguity — `prior_scorer_assessor_ids` = assessors of `SCORING_COMPLETE` assignments, in `created_at` order, duplicates collapsed — `routes/appeals.py:31`
- §3.9 — revise — mismatch — the `ERR_APPEAL_FEE_UNPAID` gate is the last rung, after the reviewer resolves; a missing invoice counts as unsettled — `routes/appeals.py:141`
- §3.9 — insert — ambiguity — reviewers are exempt from §3.6's permanent per-claim exclusion; capacity uses the claim's current turnaround from the clock; no assignment row, no `active_assignment_count` — `services/selection.py:53`, `routes/appeals.py:129`
- §3.9 — insert — ambiguity — decide ordering: panel membership before lookup, then `ERR_FORBIDDEN_ASSESSOR_SCOPE` (skipped while reviewer is null), then segregation after the status check — `routes/appeals.py:171`
- §3.9 — revise — mismatch — uphold's `PAID → RETAINED` is conditional, not a precondition, and does not bump the claim's `version`/`updated_at` — `routes/appeals.py:202`
- §3.9 — insert — ambiguity — overturn's programme failure is `ERR_PROGRAM_INACTIVE`, ahead of the crosswalk pair; enrolment is not re-checked — `routes/appeals.py:212`
- §3.9 — insert — ambiguity — overturn's `credits_awarded` is any integer ≥ 1, with no `credits_requested`/rule ceiling re-applied — `routes/appeals.py:184`
- §3.9 — insert — ambiguity — a full refund with no net cash lands on `WAIVED`, not `REFUNDED` — `services/invoice.py:202`
- §3.9 — revise — mismatch — overturn's cascade fires at remaining 0 or below — `services/capacity.py:114`
- §3.9 — revise — mismatch — remand's re-taken reservation also raises `pla_upper_division_committed` for an `UPPER` course — `services/capacity.py:57`
- §3.9 — insert — ambiguity — the remand's money side still runs on the `CAP_BLOCKED` branch — `routes/appeals.py:251`
- §3.10 — insert — ambiguity — `amount_cents` must be an integer of at least 1 — `routes/invoices.py:54`
- §3.10 — revise — mismatch — suspend waiver (`INVOICED`/`PARTIALLY_PAID`, `total − net`) separated from retire waiver (`+PAID`, whole `total_cents`) — `routes/articulation.py:145,270`, `services/invoice.py:172`
- §3.10 — insert — ambiguity — settlement lands on `REFUNDED` when the refund is positive and `WAIVED` when zero; negative balances sweep into `refunded_cents` — `services/invoice.py:188`
- §3.10 — insert — ambiguity — `waive_reason` is required and non-empty but is not stored — `routes/invoices.py:79`
- Pass C deliberately left under-determined rather than over-claimed: elapsed-ms truncation inside `elapsed_bp`, an `sla_hours` of 0, a `PAID` invoice holding a positive balance, and two live assignments on one claim both breaching in a single sweep.

**Orchestrator verification:** `cmp` confirms PRD_COMPLETED.md is not byte-identical to PRD_FINALIZED.md (+18,409 chars); heading counts match (no new sections); the file still ends at the final §5 error row; and `find implementation -name '*.py' -newer implementation/results.1.json` is empty, so no implementation file changed after the verified 8/8 green sweep — the 113/113 result still describes the shipped implementation.

