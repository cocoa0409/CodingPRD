# Worklog — task_2700_board_recruitment_director_onboarding

## Step 1: Create task directory — 2026-09-04T08:41:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2700_board_recruitment_director_onboarding` and its `workspace/` subdirectory. Index 2700 was pre-assigned by the orchestrating command (no auto-allocation scan performed, since up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T10:11:00.000Z

Done. All three scaffold artifacts for task 2700 are complete, parse cleanly, and pass the linter.

## Files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2700_board_recruitment_director_onboarding/SCAFFOLD.yaml` | 3527 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2700_board_recruitment_director_onboarding/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1819 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2700_board_recruitment_director_onboarding/SCAFFOLD_CORNER_DESIGN.yaml` | 3372 |

## SCAFFOLD.yaml (§1.0–§1.7 only — contains neither design key)

Top-level keys: `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`. `api_prefix: /governance`.

- 17 entities, 14 state machines, 2 OCC concurrency rules (§1.2.1)
- 12 calculations (2 dual-variant), 38 validations across 15 priority bands
- 75 endpoints, 61 errors (all 61 triggered by at least one design instance), 6 roles

## Design indices

- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: single key `scaffold_difficulty_design`, 9 rule_ids x 2 instances = **18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- `SCAFFOLD_CORNER_DESIGN.yaml`: single key `scaffold_corner_design`, **86 instances** across all 9 claim-extraction sections — entities 13, state_machines 18, calculations 16, validations 14, endpoints 5, errors 9, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. 62 carry full `test_recipe`s; 24 are `excluded_because` stubs citing §1.8 instances by name. All 104 instance names are unique across both files.

## Lint

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    75
  §1.1 entities declared:     17
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  767
```

Fixes made this session: appended the final `rbac` / `cross_cutting_complexity_layers` / `consistency_model` sections; then the first lint run reported 3 `(f) FK_REVERSE_UNREACHABLE` violations (`IndependenceScreen.candidate_id`, `OnboardingItem.director_id`, `DirectorCompensationAward.director_id`). The linter's sub-resource form requires a literal `{id}` placeholder, which this scaffold's named placeholders (`{candidate_id}`, `{director_id}`) don't satisfy, so I added the filtered-list form instead — `GET /governance/screens`, `GET /governance/onboarding-items`, `GET /governance/comp-awards`, each with the FK as an optional filter (endpoint count 72 → 75) — and updated the `SeatedDirector` / `GovernanceStaff` role read lists to match. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-04T10:11:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T10:28:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — 565 lines, 15,022 words, written incrementally (one Write + heredoc appends), ending cleanly on the final row of the §5 error table with no footer or audit section.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim contract) · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock · 2.5 Path Resolution Order · 2.6 The Governing Policy Record · 2.7 Monetary Precision, Rounding and Percentage Discipline · 2.8 Version Echo Requirements · 2.9 Cascading Recomputation and Derived-State Propagation · 2.10 Validation Ordering and Rejection Precedence · 2.11 Enumerated Vocabularies
- §3 Business Logic & Workflows (9 subsections) — 3.1 Skills Matrix & Board Gap Analysis · 3.2 Sourcing the Candidate Pipeline · 3.3 Independence Screening & Determination · 3.4 Interviews, Reference Checks & Candidate Readiness · 3.5 Conflict Clearance · 3.6 Assembling the Nomination Slate · 3.7 Committee Deliberation, Filing & the Election Record · 3.8 Onboarding, Committee Seating & Continuing Education · 3.9 Director Compensation, Compliance Monitoring & the Governance Policy Record
- §4 API Endpoints (4-column table: Method, Path, Description, Authorized Role(s))
- §5 Error Codes (2-column table: Error ID, HTTP Status Code)

**Coverage (all verified programmatically against SCAFFOLD.yaml)**
- Entities 17/17 · Endpoints 75/75 (75 table rows, each with its exact role list) · State machines 14/14 · Calculations 12/12 · Validations 38/38 · Errors 61/61 (61 table rows) · Roles 6/6

**Hard Contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** Two independent passes. Pass 1 (token-level, code fences excluded): 177/177 entity field names and 139/139 endpoint identifiers (request-body/input fields, path params, computed-read output keys) appear in backticks — 0 missing. Pass 2 (stricter: exact backtick span or `Entity.field` form): 0 missing on both sets. Also 103/103 enum values, 61/61 error ids and 6/6 role names appear as exact backticked tokens.
- **Contract 2 — Rule Coverage: PASS.** Validation priorities rendered as a 21-step ordering ladder in §2.10 with intra-rank tiebreaks (quorum before approval; independence floor before universal-proxy minimum; fiscal budget last) and full `applies_to` enumeration for the enum (12), range (7), interval (4), body-id (8), no-active-policy (9), ownership (4) and uniqueness (10 rules) checks. Both `concurrency_rules` documented in §2.8 as pure stale-version framing with `expected_slate_version`/`expected_committee_version`, `ERR_STALE_SLATE_VERSION`/`ERR_STALE_COMMITTEE_VERSION` and 412; no banned wording anywhere in the document. Both five-hop cascades (adverse screen determination; record-election) written hop-by-hop, plus the departure and posture cascades. All 12 calculation formulas in reconstructable prose with pinned rounding/comparison order (per-nominee fee rounding before summation; offset tier keyed on `pre_offset_total_cents`; readiness cap before penalty; ownership base excluding equity; fixed compliance leg order; fixed conflict first-failure order). Every transition's from/to, preconditions, error code and side effects covered; sibling branches kept symmetric.
- **Contract 3 — §3 Path Purity: PASS.** Scanned every backtick span in §3 (62,596 chars): 0 tokens beginning with `/`, 0 bare HTTP methods, 0 method+path combinations, and 0 raw `/governance…` mentions outside backticks.

One scaffold inconsistency noted (not a blocker): `DirectorSkillRating.self_rating`/`validated_rating` carry an entity constraint of 0..4 while validation priority 12 and the endpoint descriptions state 1..5. The PRD follows the validation/endpoint text (1 through 5), since that is the rule the tests assert.

**Orchestrator truncation check (per the known doc-generator failure mode):** `tail -25` confirms PRD.md ends on a complete `| ERR_SEARCH_FEE_BUDGET_EXCEEDED | 422 |` table row at a real section boundary — the §5 error table's last entry, with all 61 error rows present. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T11:20:00.000Z

Test suite complete and statically verified.

## Output

**`test_helpers/` — 2509 lines, 9 files** (unchanged from Stage 1 except two fixes below): `types.py` 620, `factories.py` 447, `fixtures.py` 495, `api_client.py` 366, `assertions.py` 206, `api_errors.py` 150, `constants.py` 136, `test_users.py` 84, `__init__.py` 20.

**`test_suite/` — 7830 lines, 22 files, 164 tests** (`conftest.py` 33 + 21 test files):

| file | lines | tests | file | lines | tests |
|---|---|---|---|---|---|
| test_01_independence_determination | 176 | 3 | test_12_temporal_overlap | 456 | 7 |
| test_02_skills_matrix_gap_analysis | 156 | 5 | test_13_ledger_invariants | 376 | 7 |
| test_03_search_firm_placement_fees | 177 | 5 | test_20_entity_corners | 646 | 18 |
| test_04_compensation_awards | 185 | 6 | test_21_state_machine_corners | 801 | 15 |
| test_05_candidate_lifecycle | 252 | 6 | test_22_calculation_corners | 571 | 8 |
| test_06_director_dimensions | 269 | 6 | test_23_endpoint_corners | 303 | 5 |
| test_07_screen_cascade | 340 | 6 | test_24_validation_corners | 1034 | 22 |
| test_08_departure_cascade | 219 | 6 | test_25_error_corners | 156 | 6 |
| test_09_validation_precedence | 392 | 7 | test_26_rbac_corners | 319 | 6 |
| test_10_boundaries | 283 | 7 | test_27_consistency_corners | 413 | 7 |
| test_11_cross_entity_state | 273 | 6 | | | |

## Coverage

- **Queue A (§1.8 difficulty): 18/18 instances translated, 0 skipped, 77 tests** — every instance carries 3-6 tests.
- **Queue B (§1.9 corner): 61/62 non-stub instances translated, 1 skipped, 87 tests.**
- **24 `excluded_because:` stubs**: no tests emitted; every `difficulty_instance:` cross-reference was checked and resolves to a real instance under the named `rule_id`.
- **The one skip:** `Corner/entities/policy_optional_knobs_fall_back_to_their_declared_defaults` — default-value Silence. PRD §3.9 says only that "every threshold field is optional and falls back to the default declared for it" and lists the 24 names; it never publishes the numeric defaults the instance asserts. The optionality claim itself is still exercised (two tests adopt a policy whose body is only `cycle_year` + `effective_from` and get 201); the unpublished numbers are not asserted.

## Audits run (all clean)

A programmatic audit over every emitted test confirms: exactly one `PRD:` quote per docstring, each a literal `grep -F`-survivable substring of `workspace/PRD.md` of ≥8 words on one physical line; exactly one `Design:` line, last in the docstring, resolving to a real `rule_id`/`section` + instance `name`, never to a stub; no forbidden references ("scaffold", "§", design-index prose); no `skip`/`xfail`/placeholder anywhere. Plus: 164 tests collect under pytest, `compileall` clean, `pyflakes` clean on `test_suite/`, no duplicate test names, and a signature checker validated every `client.*`/`fixtures.*`/`factories.*`/`assertions.*` call against the frozen helpers (0 problems).

## Defects found and fixed

1. **`validate_error` argument order** — the real signature is `(response, expected_error_id, expected_status=None)`; my brief to the partition agents documented it reversed. Found and mechanically swapped **47 calls** across 6 files, then re-audited.
2. **`fixtures.cast_ballot` asserted HTTP 200** for `POST /governance/slates/{slate_id}/votes`, a creation endpoint (PRD line 419: "Creation endpoints return HTTP 201"). Fixed to 201, then cross-checked *every* one of the 75 client methods' asserted status against the endpoint contract with a negative-controlled checker: 0 remaining mismatches.
3. **`fixtures.finalize_award` was missing**; added.
4. **Charitable-materiality zero-threshold trap in `test_01`** — a screen with `company_gross_revenue_cents` 0 gives a 0 charitable threshold, and the PRD says the factor fails "at or above" it, so nil contributions *fail* and `qualitative_fail_count` would be 2, not the 1 the design index asserts. Fixed by stating a positive issuer revenue so both readings coincide and the design's 1 is PRD-derived.

## PRD problems worth escalating

- **PRD §3.2 contradicts itself on overboarding**: "A new seat that takes a director past their limit moves `compliance_status` ... to `OVERBOARDED`" versus "Attempting to record a seat that would take the subject past the applicable limit is separately refused with `ERR_OVERBOARDING_LIMIT_EXCEEDED`". Both use the same test, so `OVERBOARDED` is unreachable via a directorship POST. Three separate instances hit this; each reaches the pre-state by recording seats under a looser limit and then tightening the policy, which is derivable under either reading.
- **Design-index assertions that contradict the PRD** were resolved toward the PRD and are worth a look during finalization: HTTP 400 asserted where the PRD error table says 422 (`ERR_VALUE_OUT_OF_RANGE`, `ERR_DIRECTORSHIP_SUBJECT_INVALID`, `ERR_SOURCE_CHANNEL_MISMATCH`, `ERR_INVALID_INTERVAL`); `Director.is_independent` default `false` vs the PRD's `true`; `fee_model` default `CONTINGENCY` (not in the vocabulary — PRD says `RETAINER`); committee codes `FINANCE`/`AUDIT2` and item category `COMMITTEE_ORIENTATION` outside their closed enums; a `NOT_RENOMINATED` transition for a director who was never a nominee.
- Non-derivable **sub-assertions** inside otherwise-translated instances were dropped rather than weakened (candidate-side `external_public_board_count` re-derivation, which §3.2 scopes to director subjects; a specific `readiness_score` breakdown; stored interlock counts after a *refused* add; fractional-second rendering of client-supplied instants; the relative order of two rows created at the same frozen clock instant).

The suite has **not** been executed against a live server — `workspace/implementation/` belongs to the concurrently running implementation generator and was never read or written. Nothing outside `test_helpers/` and `test_suite/` at the task root was modified.

## Step 6: Generate implementation — 2026-09-04T11:28:00.000Z

The implementation is complete. Final report:

## Deliverable

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 86 | Flask factory, all 10 blueprints under `/governance`, error handlers (ApiError, 400/404/405/415, catch-all 500), `PORT` boot |
| `store.py` | 136 | 17 in-memory dicts, UUID ids, logical clock, `touch` (one version bump per request via `flask.g`) |
| `envelope.py` | 85 | `meta`/`response_type`/`data` envelope, `req_`+20-char id, ms UTC timestamps, offset pagination |
| `errors.py` | 86 | 61-code catalogue → HTTP status mapping, `fail()` |
| `payload.py` | 167 | JSON body parse, typed `required`/`optional`, enum/range/min/interval/date checks |
| `authz.py` | 72 | `X-User-ID`/`X-User-Role`, 6 roles, `require`, `require_director_owner` |
| `calc.py` | 406 | Decimal ROUND_HALF_UP arithmetic: readiness, screen factors, fees, comp waterfall, interlock/overboarding, `require_policy` |
| `derive.py` | 489 | All recompute cascades: slate + tally, nominee settle, firm ledger, onboarding, compliance, gap analysis, clock refresh, item seeding |
| `vocab.py` | 79 | Every enum tuple |
| `routes/common.py` | 107 | `need` (per-entity 404 codes), filters, ordering, `emit`/`emit_list` |
| `routes/policy_routes.py` | 269 | 10 endpoints (policy, skill categories, search firms, external companies, clock) |
| `routes/director_routes.py` | 210 | 9 |
| `routes/candidate_routes.py` | 243 | 8 |
| `routes/screen_routes.py` | 154 | 6 |
| `routes/directorship_routes.py` | 137 | 4 |
| `routes/interview_routes.py` | 170 | 5 |
| `routes/committee_routes.py` | 199 | 8 |
| `routes/slate_routes.py` | 580 | 14 |
| `routes/onboarding_routes.py` | 127 | 6 |
| `routes/comp_routes.py` | 112 | 5 |
| `start.sh` | 10 | reads `$PORT`, binds 0.0.0.0, foreground `exec python3 app.py`, installs Flask only if missing |

Total 3,924 lines across 21 modules + `requirements.txt`. `python3 -m compileall` clean; `__pycache__` removed.

**Endpoints: 75/75** (`grep -c "^@bp\."` per module sums to exactly 75).

## Organization
- **State machines**: each transition endpoint validates its own source-state set inline and raises the entity-specific `ERR_*_STATE_INVALID`; all cross-entity consequences live in `derive.py` so a single client act fans out consistently (screen determination and record-election are five-hop cascades; departure notice is three-hop).
- **Calculations**: `calc.py` only — every money/percentage value is `Decimal` with ROUND_HALF_UP, per-nominee fees rounded then integer-summed, tiered placement fees, comp waterfall, ownership test, readiness score.
- **Validations**: uniform ladder order enforced by call sequence in each route — role → payload types/enums/ranges → interval → path 404 → body 404 → policy presence → OCC (`expected_slate_version` / `expected_committee_version`, 412) → state → safety guidelines → uniqueness → temporal → capacity/threshold → budget last.
- **Storage**: process-local dicts, all 17 collections verified empty on a fresh boot; nothing seeded, no disk or `/tmp` persistence.

## Smoke test
Two full end-to-end suites, each against a cold `PORT=18700 bash start.sh` process, both ending `FAILURES: none`:
1. 46-step happy path: policy → firm → candidate → screen → interview → reference check → conflict clearance → slate → nominees (TIER1 fee 7,500,000 cents, firm ledger committed 7,500,000 / net payable 6,500,000) → stale-version 412 → review → ballots → quorum + 100% approval → APPROVE → file → record-election (mints one ONBOARDING director with 3 seeded items, flips the un-renominated incumbent) → onboarding gate (`ERR_ONBOARDING_INCOMPLETE` then seat) → comp award + finalize → committee.
2. 60-step edge path: clock monotonicity (`ERR_CLOCK_NOT_MONOTONIC`), gap analysis with/without policy, skill-rating validation, overboarding refusal + `OVERBOARDED` → committee `SUSPENDED` → end seat → `COMPLIANT` → `AT_STRENGTH` reverse cascade, assignment overlap/seats-exhausted/revoke, nominee void → candidate `DEFERRED`, contested/universal-proxy flags, recusal + interviewer bar + not-resource-owner 403s, decide REJECT (back to DRAFT, revision_count 1, tally reset) and ABANDON (nominees voided, cycle year freed), departure notice cascade, waive, pagination meta.

Envelope, per-entity 404 codes, 405, and 401 shapes all verified by curl. The port-18700 process was killed by recorded PID (no pattern-kill) and port 18700 is confirmed free.

One real bug was found and fixed by smoke testing: `routes/screen_routes.py` reused one state tuple for both opening and submitting a screen, so submitting a legitimately `SCREENING` candidate's screen was refused; it now uses `SUBMITTABLE = ("SCREENING", "NOMINATED")` for submit and `SCREENABLE = ("SOURCED", "NOMINATED")` for open.

## Step 7: Run tests and iterate — 2026-09-04T12:10:00.000Z

All 8 rounds of the final sweep report `passed == total` (164/164 each). Results files are on disk in `workspace/implementation/results.1.json` … `results.8.json`.

## Summary

**Iterations run:** 2 sweeps (1 reconnaissance sweep, killed and superseded once fixes landed, plus fast single-round full-suite probes for diagnosis; 1 final clean 8-round parallel sweep — all 8 rounds 164/164, ~313 s each).

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence that uniquely determined the asserted outcome, so all three defects were implementation bugs.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper constructed a precondition inconsistent with PRD.

**Fixes applied to `implementation/`:**

1. `routes/policy_routes.py` → `adopt_policy()`: removed a `ERR_DUPLICATE_RESOURCE` refusal when an `ACTIVE` policy already held the requested `cycle_year`. PRD §3.9 makes adoption a two-part act ("every prior policy whose `status` is `ACTIVE` becomes `SUPERSEDED`, and the new row is created `ACTIVE`"), so the "only one `ACTIVE` policy per `cycle_year`" clause is an invariant maintained by the supersede step; PRD §2.10 enumerates the *ten* `ERR_DUPLICATE_RESOURCE` rules and policy adoption is not among them. Symptom: any test adopting a second policy in the same cycle year (`test_01::test_each_screen_keeps_the_standard_in_force_when_it_was_submitted`) died at setup with 409.

2. `store.py` (`LOGICAL_CLOCK_EPOCH_TEXT`, `Store.clock_text`, `clock_instant()`) + `routes/policy_routes.py` (`set_clock` now records `db.clock_text = current_utc`): the twelve server-written domain instants listed in PRD §2.4 (`submitted_at`, `determined_at`, `completed_at`, `activated_at`, `ended_at`, `voided_at`, `cast_at`, `filed_at`, `election_recorded_at`, `validated_at`, `finalized_at`, `retirement_notice_at`) now carry the clock's own reading rather than being re-serialised into the three-fractional-digit form. PRD states the clock "reads exactly `2026-08-01T00:00:00Z`" and that each of those fields *is* the logical clock instant, while reserving the "three fractional digits" format spec for `created_at`/`updated_at`/`api_request_timestamp` only (those are unchanged). Symptom: 7 tests failing `expected '2026-08-01T00:00:00Z', got '2026-08-01T00:00:00.000Z'`.

3. `routes/interview_routes.py` → `schedule_interview()`: scheduling the first session out of `SCREEN_PASSED` now also advances the *candidate's* `interview_round` to the new round number, not just the session's. Required by PRD §3.4 — a later session "inside the same round" is numbered from "the candidate's current `interview_round`", which only agrees with the first session's number if the candidate's counter moved. Symptom: `test_12::test_the_refused_booking_leaves_no_phantom_session_or_round` and `test_21::test_each_interview_completion_re_derives_the_candidate_interview_aggregates` asserting candidate `interview_round == 1`, got 0.

No implementation check required by PRD was removed or weakened, no assertion was relaxed, no endpoint/field/side-effect was added without a verbatim PRD sentence, and storage remains in-memory dicts with nothing seeded at boot.

**Orchestrator verification:** independently re-read all 8 `results.*.json` — every round reports `passed=164 failed=0 total=164`. Confirmed, not taken on the subagent's word.

## Step 8: Finalize PRD — 2026-09-04T12:01:00.000Z

Done. Three edits to `workspace/PRD_FINALIZED.md`, one per Step 7 implementation fix.

**Size:** PRD.md 565 lines / 115,514 bytes → PRD_FINALIZED.md 565 lines / 116,576 bytes (line count identical — the PRD is one-paragraph-per-line; byte delta +1,062, **+0.92%**). Three paragraphs revised, no sections added.

**Changes**

- **§2.4 (Common Resource Properties and the Logical Clock)** — revise — the twelve server-written domain instants now explicitly carry the clock's own reading verbatim (`2026-08-01T00:00:00Z` before any move; afterwards the exact `current_utc` string supplied, character for character), *not* re-serialised into the three-fractional-digit form reserved for `created_at`/`updated_at`/`api_request_timestamp` — `implementation/store.py:18,47,75-77` + `implementation/routes/policy_routes.py:265`.
- **§3.4 (Interviews…)** — insert — opening a round from `SCREEN_PASSED` also advances the *candidate's* `interview_round` to the new number in the same write; scheduling for a candidate already `INTERVIEWING` leaves it alone — `implementation/routes/interview_routes.py:95-116`.
- **§3.9 (…Governance Policy Record)** — revise — "only one `ACTIVE` policy may hold a given `cycle_year`" is pinned as an invariant maintained by the supersede step, not a precondition: a second adoption in the same cycle year is accepted and never reports `ERR_DUPLICATE_RESOURCE` — `implementation/routes/policy_routes.py:95-119`.

**Per-edit pre-edit search log**

1. *Clock instant format.* (a) Subject: the textual form of every server-written instant and the clock's stored reading. (b) Enumerated: grepped all of `clock_instant|clock_text|wall_now|iso_ms|clock_date|db.clock` and all twelve field names across `implementation/*.py` + `routes/*.py`. Every writer of the twelve fields goes through `clock_instant()` → `db.clock_text` (screen submit/determine `screen_routes.py:114,130`; interview complete `:152`; onboarding complete `:99`; assignment activate/end `committee_routes.py:177,193` and cascade `derive.py:422`; nominee void `derive.py:373`; ballot cast `slate_routes.py:386`; file `:478`; election record `:543`; rating validate `director_routes.py:208`; retirement notice `:143`; award finalize `comp_routes.py:107`). `db.clock_text` is written only in `Store.__init__` and `set_clock`. `created_at`/`updated_at`/`api_request_timestamp` use `wall_now()` (host time, three digits) — untouched. `clock_date()` (comparisons) and `derive.py:140`'s `str(completed_at)[0:4]` year-prefix read both remain valid under either textual form. (c) Adjustment: scoped the sentence to *format* only and left the host-time provenance of `created_at`/`updated_at` unstated, since the impl does not source those from the logical clock; added "most recent accepted move" so a refused non-monotonic move is not implied to change the reading.

2. *Candidate `interview_round`.* (a) Subject: every mutation of `Candidate.interview_round`. (b) Enumerated by grep: `candidate_routes.py:103` (born 0), `:168-173` (reopen-interviews gate `>= 3` then +1), `:226` (reopen-screening resets to 0), `interview_routes.py:96/98` (session number) and `:116` (candidate advance). (c) Adjustment: confined the new sentence to the scheduling operation ("Opening a round this way") and added the explicit no-op clause for an already-`INTERVIEWING` candidate, so the sentence cannot be read as overriding the reopen-interviews increment (already in §3.4) or the reopen-screening reset to 0.

3. *Policy adoption uniqueness.* (a) Subject: `ERR_DUPLICATE_RESOURCE` applicability and the ACTIVE-per-`cycle_year` clause on policy adoption. (b) Enumerated: `policy_routes.py:73-119` (`adopt_policy` — no duplicate check at all; only `ERR_CYCLE_YEAR_NOT_ADVANCED` against `governing_policy()`'s `effective_from`, then the blanket supersede loop), and every other `ERR_DUPLICATE_RESOURCE` site to confirm the ten §2.10 rules stay intact: `policy_routes.py:153` (skill category `code`), `:204` (search firm `name`), `:240` (external company `name`), plus grep of the code across `director_routes.py`, `directorship_routes.py`, `screen_routes.py`, `committee_routes.py`, `slate_routes.py`, `comp_routes.py`. (c) Adjustment: worded the exclusion narrowly ("policy adoption is not one of the uniqueness rules of §2.10") instead of touching §2.10's ten-rule list, so the other duplicate rules are neither redefined nor contradicted; also kept `ERR_CYCLE_YEAR_NOT_ADVANCED` prose verbatim since the impl still enforces it.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` is non-empty — the finalizer really edited the copy.

## Step 9: Complete PRD — 2026-09-04T13:05:00.000Z

**Orchestrator decision (recorded per the AUTONOMY clause):** Step 9 was run as **three sequential, module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, rather than a single subagent. Rationale: a single agent scanning all 21 implementation modules against a 565-line PRD reliably runs out of working context and exits having written a byte-identical copy (the scan never actually happens). Partitioning by implementation module keeps each pass's slice small enough to walk exhaustively, and running the passes sequentially (never concurrently) prevents two agents from making conflicting edits to the same file. Pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from re-copying, since that would have destroyed the earlier passes' edits.

Slices: **pass 1** = app.py, store.py, envelope.py, errors.py, payload.py, authz.py, vocab.py, routes/common.py, routes/policy_routes.py, routes/director_routes.py. **pass 2** = routes/candidate_routes.py, routes/screen_routes.py, routes/directorship_routes.py, routes/interview_routes.py, calc.py. **pass 3** = routes/committee_routes.py, routes/slate_routes.py, routes/onboarding_routes.py, routes/comp_routes.py, derive.py.

### Pass 1 (core + policy + director) — 23 changes: 18 ambiguity-pins, 5 mismatch-revisions

`cp PRD_FINALIZED.md PRD_COMPLETED.md` confirmed as the first action; all subsequent work was individual `Edit` calls. 565 lines both; 116,576 → 123,127 chars (+6,551); diff touches 23 lines.

- §3.9 Adopting a governance policy — insert — ambiguity — PRD declared thresholds "fall back to the default declared for it" but **never declared any default**; now enumerates all 24 defaults (`authorized_seats` 9, `independence_min_pct` 66.67, `independence_standard` BRIGHT_LINE, floor 100000000, 2.0/3/5/2.0, boards 4/2, interlock 2, retirement 75, tenure 15, interviews 3, quorum 3, approval 66.67, retainer 12000000, 1500000, 2500000, equity 20000000, multiple 5.0, grace 5, hours 8.0, readiness 60.0) plus per-field range bounds → `ERR_VALUE_OUT_OF_RANGE`, `effective_from` stored verbatim, and that `ERR_CYCLE_YEAR_NOT_ADVANCED` is skipped on first adoption — policy_routes.py:42-119
- §2.4 version bullet — insert — ambiguity — a row's `version` advances at most once per request however many writes touch it, while `updated_at` refreshes on each — store.py:100-112
- §2.4 logical clock — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from the host's real clock, not the logical clock, and are never rewritten when it moves — store.py:71-72, envelope.py:23
- §2.4 logical clock — revise — ambiguity — `recomputed_director_count` is the total number of director rows (stale statuses included; excluded only from the compliance leg), and `data` carries exactly those two fields — policy_routes.py:266-271
- §2.3 pagination — revise — mismatch — `limit`/`offset` are clamped (1..100, ≥0) and unparseable values fall back to defaults; pagination never errors, and `meta` reports clamped values — envelope.py:57-77
- §2.3 ordering — insert — ambiguity — all list orderings stable, ties broken by in-process creation order, never by `id` — routes/common.py:98-108
- §2.3 meta — insert — ambiguity — `has_more` formula, `total_count` counted post-filter/pre-window, plus full filter semantics (param named after the field, empty/unknown params ignored, exact string match, boolean truthy set `true/1/yes/y`, non-integer int filter → empty page) — envelope.py:35-42, routes/common.py:63-85
- §2.10 step 4 — insert — ambiguity — empty body = `{}`, non-object body → `ERR_INVALID_REQUEST`, explicit `null` = absent, no type coercion (integer rejects `3.0`/strings; bool satisfies neither), unparseable date/instant is a step-4 `ERR_INVALID_REQUEST`, date fields accept a longer instant and read its date part — payload.py:16-57, 119-152
- §2.1 headers — revise — ambiguity — whitespace-only headers are `ERR_UNAUTHENTICATED`; values stripped, role matched case-sensitively — authz.py:45-57
- §2.2 envelope — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — envelope.py:18-19
- §2.4 opening — insert — ambiguity — all state is process-local in-memory and a fresh process holds no rows — store.py:1-54
- §5 intro — insert — ambiguity — four transport-level codes outside the catalogue: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INVALID_REQUEST` 400, `ERR_INTERNAL` 500 — app.py:54-76
- §4 intro — insert — ambiguity — trailing slash is insignificant — app.py:45
- §3.8 Seating — revise — ambiguity — refusal is when already-`SEATED` count plus one exceeds `authorized_seats` — director_routes.py:117-121
- §3.8 Seating — insert — ambiguity — a direct `SEATED` load bypasses the seat ceiling; director `email` need not be unique; created-director defaults — director_routes.py:41-83
- §3.8 Departure — revise — mismatch — `effective_on` is validated but not persisted or echoed — director_routes.py:134-135
- §3.1 skill ratings — insert — ambiguity — validation has no state gate; an already-`VALIDATED` rating may be re-validated, overwriting — director_routes.py:198-210
- §3.1 categories — revise — ambiguity — duplicate `code` compared exactly/case-sensitively — policy_routes.py:151-153
- §3.1 gap analysis — revise — ambiguity — an omitted or empty `variant` selects `SELF_REPORTED` — policy_routes.py:180-183
- §3.2 search firms — revise — ambiguity — `name` uniqueness exact/case-sensitive; both fee tiers required — policy_routes.py:195-204
- §3.2 external companies — revise — ambiguity — `name` uniqueness exact/case-sensitive; `ticker` a required string — policy_routes.py:229-240
- §4 table (4 cells) — insert — ambiguity — exact filter parameter names for `GET /policies`, `/skill-categories`, `/directors`, `/skill-ratings` — policy_routes.py:131-172, director_routes.py:95-195

Verified non-issues: error-code→HTTP map matches §5 exactly; ownership-before-404 order on `GET /search-firms/{firm_id}` already follows §2.10; enum→range→policy ordering matches the ladder; `SkillCategory`/`ExternalCompany` correctly omit `updated_at`/`version`.

### Pass 2 (candidate + screen + directorship + interview + calc) — 25 changes: 18 ambiguity-pins, 7 mismatch-revisions

Confirmed no re-copy; opened the existing file and patched in place with 25 `Edit` calls; all 8 spot-checked pass-1 pins still present. 123,127 → 132,281 chars (+9,154), 0 line delta.

- §2.6 governing policy — insert — ambiguity — final tiebreak after `effective_from`/`created_at` is insertion order, later row first — calc.py:81
- §2.10 step 6 — insert — ambiguity — added candidate sourcing (`target_annual_comp_cents` ≥ 0) to the guarded list; unguarded cent/count inputs noted — candidate_routes.py:60, screen_routes.py:46
- §2.10 step 7 — insert — mismatch — the external-directorship interval compares against stored `start_on`, so it runs after that row's 404 but before its state precondition — directorship_routes.py:126
- §2.10 step 11 — insert — ambiguity — several body identifiers in one request resolve in the order the list gives — directorship_routes.py:65, interview_routes.py:72
- §3.2 candidate intake — revise — mismatch — candidate `email` is not unique; all four intake fields required — candidate_routes.py:50
- §3.2 candidate intake — revise — ambiguity — `shareholder_proponent_name` unconstrained/persisted on identifier channels; coherence runs before id resolution; `target_annual_comp_cents` never negative — candidate_routes.py:63
- §3.2 outside seats — revise — mismatch — the `ERR_OVERBOARDING_LIMIT_EXCEEDED` pre-check applies only to a director subject, runs before the duplicate rule, and is skipped (with compliance) when no `ACTIVE` policy exists; a candidate subject re-derives only its board count — directorship_routes.py:70
- §3.3 screen creation — insert — ambiguity — new screen carries both fail counts 0 and `disqualifying_factor_code` null — derive.py:479
- §3.3 supplemental re-screen — insert — ambiguity — candidate row not written on the `NOMINATED` branch; state precondition precedes the one-open-screen rule — screen_routes.py:56
- §3.3 submit — revise — mismatch — governing policy demanded before the screen and candidate state checks — screen_routes.py:100
- §3.3 determination — revise — mismatch — no governing-screen concept; last determination wins; determination needs no policy and recomputes nothing — screen_routes.py:127
- §3.3 favourable branch — insert — ambiguity — no nominee `is_independent`/slate rollup rewrite; a candidate at any other status keeps its status — screen_routes.py:136
- §3.3 adverse branch hop 2 — insert — ambiguity — origin outside `SCREENING`/`NOMINATED` keeps status and reason code, no interview cancellation, nominee-void hop still runs — screen_routes.py:146
- §3.4 scheduling — insert — ambiguity — candidate must be `SCREEN_PASSED` or `INTERVIEWING`; interviewer needs no `service_status` — interview_routes.py:74
- §3.4 segregation of duties — revise — mismatch — both tests read the named `interviewer_director_id`, not the acting user; referral test = candidate's `referring_director_id`; ballot test = non-`VOIDED` nominees × `CAST` votes; referral first, both before double-booking — interview_routes.py:78
- §3.4 completing — insert — ambiguity — no ownership check, no candidate-state precondition, count spans all rounds — interview_routes.py:139
- §3.4 cancelling — insert — ambiguity — `SCHEDULED`-only precondition, score/recommendation/completed_at stay null, candidate row untouched — interview_routes.py:168
- §3.4 reference check — insert — ambiguity — completed sessions counted across rounds; state before count; count gate skipped when no `ACTIVE` policy — candidate_routes.py:139
- §3.4 reopen interviews — insert — ambiguity — no body; interview rollups, `adverse_reference_found` and `readiness_score` all left standing — candidate_routes.py:172
- §3.4 readiness — insert — ambiguity — the 15.00 penalty is applied with no floor at zero — calc.py:188
- §3.5 conflict clearance — revise — mismatch — policy checked before the candidate-state precondition — candidate_routes.py:183
- §3.6 reopen screening — insert — ambiguity — nothing else rewound; fresh screen takes all factual defaults; not measured against the one-open-screen rule; no policy / no `deferred_cycle_year` also gives `ERR_CANDIDATE_STATE_INVALID` — candidate_routes.py:218
- §3.9 governing award — insert — ambiguity — null `finalized_at` sorts as empty string; final tiebreak is insertion order — calc.py:404
- §3.9 ownership leg — insert — ambiguity — whole-year date advance clamps 29 Feb to the 28th — calc.py:55
- §4 endpoint table (6 rows) — revise — ambiguity — exact filter parameter names for candidates / candidate screens / screens / external-directorships / interviews plus ordering, and `POST /interviews` retargeted to "any recorded director"

Flagged: PRD §2.1's `SeatedDirector` bullet still mentions an interview's `interviewer_director_id` as an ownership comparison target, which is vacuous because interview completion carries no ownership check — pinned explicitly in §3.4 rather than editing §2.1. A negative `readiness_score` appears unreachable in practice, so that pin is worded as a property of the formula rather than a reachable scenario.

### Pass 3 (committee + slate + onboarding + comp + derive) — 44 changes: 33 ambiguity-pins, 11 mismatch-revisions

Confirmed no re-copy (49 in-place `Edit` calls, no `Write`); `cmp` reports the files DIFFERENT; 8 pass-1/2 pins spot-checked and intact; all 140 endpoint-table rows still have 6 fields, backticks balanced, 20 `###` sections. 132,281 → 145,298 chars (+13,017), +2 lines.

- §2.9 — revise — mismatch — "Every row touched by a cascade is a mutated row" narrowed to rows a cascade actually *moves*; a no-op recompute bumps neither `updated_at` nor `version` — derive.py:29-38
- §2.9 — revise — mismatch — transitive-cascade hop 4 scoped to slates whose own nominee set changed, with the return-to-draft conditional on `COMMITTEE_REVIEW` — derive.py:353-368
- §2.9 — insert — ambiguity — fee-driven widening: a firm's re-tiering re-derives other slates' rollups only, never returning them to draft or advancing `revision_count` — derive.py:357-363
- §2.10 step 4 — revise — mismatch — date/instant parse runs after the enum and range checks of steps 5-6 — committee_routes.py:90-93, onboarding_routes.py:38-41, comp_routes.py:37-41
- §2.10 step 6 — revise — ambiguity — range-guarded operation list extended (candidate sourcing, committee charter, slate open, nominee add, item add, award create) — slate_routes.py:68-70, committee_routes.py:48-49, onboarding_routes.py:39, comp_routes.py:37-39
- §2.10 uniqueness — revise — mismatch — "ten distinct rules" → fourteen, adding slate `ballot_order`, `Committee.code`, `Committee.name`, single ACTIVE CHAIR, `OnboardingItem.module_code` — slate_routes.py:199-202, committee_routes.py:50-54 & 167-171, onboarding_routes.py:43-47
- §3.5 — insert — ambiguity — incumbent-subject safety semantics (own ACTIVE public seats, `is_sitting_ceo_elsewhere` limit, own `birth_date`, self excluded from the interlock population, nothing written to the director row) — slate_routes.py:123-155
- §3.6 — revise — ambiguity — slate `cycle_year` at least 2000; the advancement test is skipped with no ACTIVE policy and never reports `ERR_NO_ACTIVE_POLICY` — slate_routes.py:68, 75-79
- §3.6 — insert — ambiguity — duplicate-subject before duplicate-`ballot_order`; readiness floor before the `authorized_seats` ceiling — slate_routes.py:194-212
- §3.6 — insert — ambiguity — candidate's `interlock_shared_board_count`/`external_public_board_count` written back on add; incumbent row untouched; an add is not a revision — slate_routes.py:243-253
- §3.6 — revise — ambiguity — fee ordering's final tiebreak is insertion order, and the row being added sorts last among ties — derive.py:244, 268-284
- §3.6 — insert — ambiguity — `independence_shortfall` derives false with no ACTIVE policy — derive.py:296-297
- §3.7 — revise — mismatch — submit-for-review: fourth code named (`ERR_SEARCH_FEE_BUDGET_EXCEEDED`), `ERR_NO_ACTIVE_POLICY`, and rollups re-derived before the three preconditions rather than only on success — slate_routes.py:299-321
- §3.7 — insert — ambiguity — interviewer conflict scoped to `SCHEDULED`/`COMPLETED` sessions against counted nominees' candidates, after recusal and before the duplicate-ballot rule — slate_routes.py:336-378
- §3.7 — insert — ambiguity — `quorum_met` derives false with no ACTIVE policy — derive.py:326-327
- §3.7 — insert — ambiguity — `ABANDON` re-derives rollups and all six tally figures; `revision_count` untouched — slate_routes.py:449-462
- §3.7 — revise — ambiguity — filing reports `ERR_UNIVERSAL_PROXY_MINIMUM`, reads stored rollups without re-deriving, bumps `version` — slate_routes.py:466-480
- §3.7 — insert — ambiguity — record-election ladder: non-string element → `ERR_INVALID_REQUEST`; cross-slate id → `ERR_NOMINEE_NOT_FOUND`; FILED state before the `CONFIRMED` test; `seat_count` ceiling last — slate_routes.py:515-538
- §3.7 hop 2 — insert — ambiguity — nominees walked in ascending `ballot_order`; non-`CONFIRMED` rows skipped; duplicate ids elect once — slate_routes.py:547-560
- §3.7 hop 3 — insert — ambiguity — full minted-director field set — slate_routes.py:483-508
- §3.7 — revise — mismatch — "Two further consequences" → "Three", adding post-election firm-ledger and slate-rollup re-derivation and the untouched `revision_count` — slate_routes.py:574-579
- §3.8 — revise — ambiguity — `due_on` validated then stored verbatim; adding an item re-derives only the onboarding dimension; no policy required — onboarding_routes.py:40-60
- §3.8 — insert — ambiguity — complete-item ownership check sits after item resolution (404 beats the 403) because it compares a stored field — onboarding_routes.py:93-94
- §3.8 — revise — ambiguity — whitespace-only `waiver_reason` → `ERR_INVALID_REQUEST` ahead of item existence; waive re-derives onboarding + education but not compliance — onboarding_routes.py:114-127
- §3.8 — revise — ambiguity — `min_seats` at least 1 and never compared with `authorized_seats` — committee_routes.py:49
- §3.8 — insert — ambiguity — assignment independence guideline weighed before the overlap test — committee_routes.py:102-114
- §3.8 — revise — mismatch — activation re-tests charter independence, and the duplicate-CHAIR rule precedes `ERR_COMMITTEE_SEATS_EXHAUSTED`; director status weighed before committee status — committee_routes.py:157-175
- §3.8 — revise — ambiguity — education hours: four-digit-year comparison, half-up to two decimals, missing `completed_at` contributes nothing, 0.00 with no policy — derive.py:130-143
- §3.9 — insert — ambiguity — award-creation gate order, policy demanded before the per-cycle uniqueness rule — comp_routes.py:37-50
- §3.9 — insert — mismatch — finalize writes the director row unconditionally, advancing `updated_at`/`version` even when `shares_held` was already equal — comp_routes.py:109-110
- §3.9 — insert — ambiguity — with no ACTIVE policy the compliance derivation is abandoned and the posture retained, never reset to `COMPLIANT` — derive.py:168-170
- §3.9 — insert — ambiguity — a posture change propagates to every committee holding an ACTIVE assignment of that director; a no-move propagates nothing — derive.py:190-194
- §4 (11 endpoint rows) — revise — mismatch/ambiguity — three `comp-awards` rows' role lists corrected to include CommitteeChair/CommitteeMember (no ownership check on the by-id read); filter names and orderings pinned for committees, assignments, slates, slate-nominees, votes, and both onboarding-item listings

Deliberately left under-determined: the residue a failed `decide_slate` may leave after its pre-gate recompute (only reachable when stored rollups were already stale), and the id-based tiebreak inside the record-election walk (unobservable, since `ballot_order` is unique among non-`VOIDED` rows).

### Orchestrator verification

- `PRD_COMPLETED.md` is **567 lines / 145,298 chars** vs `PRD_FINALIZED.md`'s 565 lines / 116,576 chars — `cmp` confirms they are NOT byte-identical, so the scan genuinely ran (the known Step 9 no-op failure mode did not occur). 92 total pins/revisions across the three passes.
- `tail` confirms the document still ends on the complete `| ERR_SEARCH_FEE_BUDGET_EXCEEDED | 422 |` row at the §5 table boundary — not truncated by any pass.
- `find ... -newermt '2026-09-04 11:51'` over `workspace/implementation/`, `test_suite/` and `test_helpers/` returns nothing: Steps 8 and 9 edited only PRD documents, so the verified 8-round 164/164 sweep result still describes the artifacts on disk. No re-run required.

## Pipeline complete

All nine steps finished. Final state: 17 entities / 75 endpoints / 164 tests, 8/8 sweep rounds at 164/164, `PRD.md` → `PRD_FINALIZED.md` (3 edits) → `PRD_COMPLETED.md` (92 further pins).
