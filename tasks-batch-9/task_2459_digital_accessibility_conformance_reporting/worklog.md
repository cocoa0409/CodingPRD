# Worklog — task_2459_digital_accessibility_conformance_reporting

## Step 1: Create task directory — 2026-09-02T20:21:00.765Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2459_digital_accessibility_conformance_reporting` and `.../workspace` (pre-assigned path from the orchestrator invocation; no index scan/allocation performed).

## Step 2: Generate scaffold — 2026-09-02T21:42:19.954Z

All three scaffold artifacts for task 2459 are complete and the lint is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2459_digital_accessibility_conformance_reporting/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts**
- §1.1–§1.7 surface: 12 entities, 57 endpoints, 6 calculations, 10 state machines (parallel dimensions on ProductComponent and QuestionnaireResponse), 39 validation priorities, 67 errors, 5 roles, 2 `concurrency_rules`; profile `expert_plus`, topology `graph`, role model `segregation_of_duties`, consistency `immediate`.
- §1.8: **23 instances / 9 rule_ids** — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.
- §1.9: **64 corner instances across the guide's 9 sections** (48 with full `test_recipe`, 16 `excluded_because:` stubs): entities 11, state_machines 10, calculations 7, validations 8, endpoints 6, errors 12, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. All 16 stub `difficulty_instance` references resolve by name in the §1.8 file; all 87 instance names are unique across both design files.

**Lint verdict (verbatim):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2459_digital_accessibility_conformance_reporting/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2459_digital_accessibility_conformance_reporting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2459_digital_accessibility_conformance_reporting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     12
  §1.8 instances scanned:     23
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  674

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes for the worklog: one lint iteration was needed on the corner file (`captures.at = $.data.triaged_at` on `POST /complaints/{id}/triage` — `Complaint` declares no `triaged_at`; the instance now captures `accommodation_fulfilled_at`/`route` instead). The hard constraint was honored — no sibling `task_*/` directory was listed, read, or grepped; everything was derived from the verbatim scenario, `SKILL.md` §1.0–§1.9, and `references/claim-extraction-guide.md`. Numeric literals were pre-computed with `decimal.Decimal` ROUND_HALF_UP (e.g. intake risk `5 × 1.15 × 0.54 = 3.105 → 3.11`, coverage `45.00`/`20.00`, disclosure debt `1.50`).

## Step 3: Copy shared files — 2026-09-02T21:42:19.954Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T21:56:00.000Z

PRD generated and verified. All three hard contracts pass.

**Output:** `workspace/PRD.md` — 463 lines, ~100.5 KB, ends cleanly on the final row of the §5 error table.

**Structure (27 headings):**
- §1 Introduction (3 paragraphs: procurement pain point -> system scope -> two design commitments)
- §2 Global Specifications, 11 domain-derived subsections: 2.1 RBAC · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, byte-identical — programmatically confirmed) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Optimistic Concurrency on Parent Resources · 2.6 Path Resolution and Referential Existence · 2.7 Order of Validation (all 39 priorities as a strict ordered list) · 2.8 Precision, Rounding and Ordering of Arithmetic · 2.9 Derived Fields, Cascades and Version Semantics · 2.10 Uniqueness, Immutability and Enumerations · 2.11 Independence of Parallel State Dimensions
- §3 Business Logic, 11 subsections organised as a programme timeline (configuration -> inventory/design review -> benches & runs -> coverage -> per-criterion authoring/attestation -> conformance index -> report lifecycle -> posture gate -> known issues/trains/budget -> questionnaires -> complaints)
- §4 Endpoint table (4 columns) · §5 Error table (2 columns)

**Contract reports:**
```
Field coverage check:
- entities[].fields: 124 required, 124 present, 0 missing
- endpoints[].request_body/input: 92 required, 92 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose (§2.7 ordered list + per-workflow conditions), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_product_version / expected_component_version + ERR_STALE_PRODUCT_VERSION / ERR_STALE_COMPONENT_VERSION + 412), 0 missing
- state_machines[].transitions: 10 dimensions / 49 transitions checked, 49 fully expressed, 0 missing
- calculations[]: 6 checked (coverage, conformance index PROVISIONAL+CERTIFIED, risk score INTAKE_ESTIMATE+BOARD_REVIEW, budget waterfall, disclosure debt, posture), 6 fully expressed in operator-free prose with pinned rounding/evaluation order, 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 57 checked, 57 expressed, 0 missing
- entities[].fields[] structured content: 124 checked, 124 reconstructible (defaults, initial values, derivation formulas), 0 missing
- sibling-branch symmetry: 9 groups checked (withdraw APPROVED vs PUBLISHED, resolve COMMITTED vs PUBLISHED_COMMITTED, complaint close LINKED vs ACCOMMODATED, 4 design-review transitions, run void SCHEDULED vs COMPLETED, index variants, posture entry vs recovery, revise SUBMITTED vs ATTESTED, supersede from 3 states), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 921
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Endpoint coverage:** all 57 scaffold `(method, path)` pairs appear in §4, one row each (57 rows, 57 unique pairs, zero diff against the scaffold set). All 67 error IDs and statuses match the scaffold catalogue exactly and in order. Tables exist only in §4/§5 — §3 carries no schema tables or field lists.

**Two scaffold ambiguities resolved (worth noting for the test generator):**
1. `public_target_date` on `PUBLISHED_COMMITTED -> RESOLVED`: §1.2 says "retained for audit", §1.5 endpoint side-effects say "cleared". I followed the branch-specific state-machine wording (retained on the published branch; the committed branch never had one) and stated it explicitly as the sibling-difference sentence.
2. Two preconditions carry no scaffold `error_id` — voiding a `COMPLETED` run cited as a known issue's `resolution_run_id`, mapped to `ERR_RUN_NOT_ACTIONABLE` (priority-28 actionability); and `TRIAGED -> DEFERRED` requiring no release train, expressed as a descriptive condition rather than a new code. No error IDs were invented.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and the PRD contains no difficulty or meta-commentary.

**Orchestrator truncation check (required by invocation):** `wc -l -c` = 462 lines / 101168 bytes; tail ends on `| \`ERR_LEVEL_OR_SURFACE_UNSUPPORTED\` | 422 |`, a complete final row of the §5 error table — a real section boundary, not mid-sentence. Independently re-counted: 57 endpoint rows in §4, 67 error rows in §5. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T23:05:00.000Z

Generation is complete. Both queues are fully translated, pyflakes-clean, and 94 tests collect.

## Files written

Task root: `/home/ubuntu/github/CodingPRD/tasks/task_2459_digital_accessibility_conformance_reporting/`

**Stage 1 — `test_helpers/` (9 files):** `__init__.py` (barrel), `api_client.py` (57 endpoint methods + `set_clock`), `factories.py`, `fixtures.py`, `assertions.py`, `constants.py`, `test_users.py`, `types.py`, `api_errors.py`.

**Stage 2 — `test_suite/` (`conftest.py` + 18 modules, 94 tests):**
- Queue A (depth, §1.8) — `test_01_dual_variant_calculations.py` (4), `test_02_combinatorial_formulas.py` (6), `test_03_non_linear_state_machines.py` (6), `test_04_transitive_cascades.py` (6), `test_05_validation_precedence_pairs.py` (4), `test_06_boundary_precision.py` (6), `test_07_cross_entity_state_dependency.py` (6), `test_08_resource_temporal_overlap.py` (4), `test_09_compensating_invariants.py` (4) = **46 tests**.
- Queue B (breadth, §1.9) — `test_10_corner_entities.py` (11), `test_11_corner_state_machines.py` (7), `test_12_corner_calculations.py` (4), `test_13_corner_validations.py` (7), `test_14_corner_endpoints.py` (4), `test_15_corner_errors.py` (8), `test_16_corner_rbac.py` (3), `test_17_corner_cross_cutting.py` (3), `test_18_corner_consistency.py` (1) = **48 tests**.

## Coverage against the design indices

- Queue A: 23/23 difficulty instances, exactly 2 tests each (46). No difficulty stubs exist in that yaml.
- Queue B: 48/48 non-stub corner instances, 1 test each. The 16 `excluded_because:` stubs were not translated (each is already asserted by a queue-A instance) and no test tags one.
- **Instances skipped for PRD-gap reasons: none.** Every non-stub instance passed the two-condition filter.

## Verification performed

- Every `Design:` line is the single last docstring line; all 94 tags resolve to a real `name:` in the correct source yaml and the correct corner `section:` (checked programmatically); no dual tags, no untagged tests.
- Every `PRD §x: "…"` citation was machine-checked as a verbatim substring of `workspace/PRD.md` after whitespace flattening — 0 misses (two §3.2/§3.5 quotes in `test_17` and one §3.4 quote in `test_12` were rewritten to the PRD's exact sentences after failing this check).
- Every `from test_helpers import …` name verified present on the barrel; `python3 -m pyflakes test_suite/*.py` clean; `pytest --collect-only` collects 94 tests.

## Notable design-vs-PRD reconciliations (PRD wins)

- The corner recipes ask for `GET /standards` list assertions, but the PRD exposes no standards-list endpoint — re-expressed as `get_standard` reads (or, for the unauthenticated case, by re-registering the same `code` successfully to prove nothing was written).
- Invalid enum literals in the design yamls were corrected to PRD enumerations: `assessment_scope: "PARTIAL"` -> `SAMPLED`, `component_type: "SERVICE"` -> `DOCUMENTATION`.
- `KnownIssue.resolved_at` has no PRD-named field, so that assertion stays dropped; the issue resolved out of `PUBLISHED_COMMITTED` keeps `public_target_date` per PRD §3.9.
- The unauthenticated instance ("no identity headers at all") is exercised as the PRD states it ("If either header is absent"): one call missing `X-User-Role`, one missing `X-User-ID`, both 401.

## Step 6: Generate implementation — 2026-09-02T23:05:00.000Z

The implementation is complete and verified.

## Files written
Under `workspace/implementation/` (3,283 lines of Python total):

- **Core**: `app.py` (factory + ApiError/HTTPException/Exception handlers), `db.py` (in-memory `Store` of 12 dicts + logical clock, `new_row`/`touch`/`public`), `errors.py` (69-entry status catalog), `response.py` (envelope + list meta), `middleware.py` (`X-User-ID`/`X-User-Role` auth, role table, ProductOwner ownership), `validate.py` (enums, body/query shape checks, FK + path resolvers), `calc.py` (all 6 calculations, `Decimal` + ROUND_HALF_UP), `derive.py` (counters, coverage, posture cascade, disclosure debt refresh), `serialize.py` (derived `criteria_count` / `scheduled_run_count`)
- **Routes** (`routes/`): `standards.py` 5, `products.py` 8, `runs.py` 7, `assessments.py` 4, `reports.py` 8, `trains.py` 4, `issues.py` 7, `questionnaires.py` 6, `complaints.py` 7, `clock.py` 1
- **Launcher**: `start.sh` (executable, guarded `pip install`, `exec python3 app.py`, honours `PORT`, default 10000), `requirements.txt` (`flask>=3.0`)

## Endpoint coverage
**57 endpoints** — a set-diff of the live `url_map` against the PRD §4 table (57 rows, path params normalised) is empty in both directions.

## Verification
- **Boot**: three consecutive kill/relaunch cycles via `start.sh` each served traffic in ~0.8 s; `GET /products` returned `total_count 0` on every fresh boot, and a write in one boot was gone in the next (in-memory only, no seed data, no files written — `__pycache__` removed, nothing else on disk).
- **Smoke suite** (~110 assertions, full lifecycle: standard -> criteria -> product -> component -> bench -> runs -> complete -> assessments -> attest -> design review -> report submit/request-changes/approve/publish/withdraw -> train + budget allocate/deallocate -> issue triage/board-review/commit/resolve -> questionnaire submit/attest/revise -> complaint triage/link/fulfill/close -> run void): **0 failures**.
- **Calculation/posture probe**: **0 failures**, including screen-reader-only coverage 45.00 (0.45 weight x capped 1.0), provisional index 0.00 -> `RESTRICTED` with the OPEN->RESTRICTED cascade flipping the questionnaire to `STALE` with `update_due_at` = clock+30d, no cascade on the RESTRICTED->OPEN recovery, `ERR_PRODUCT_POSTURE_NOT_OPEN` (409) then `ERR_REPORT_NOT_PUBLISHED` (409) in the correct order, intake risk 40.00 -> board-review risk 68.00 (35 days aging), disclosure debt 10.00 `ELEVATED` -> 11.00 after a 33-day clock move -> 0.50 `STANDARD` after deferral.
- **Schema conformance**: every entity's response keys were diffed against `SCAFFOLD.yaml` — no missing fields; success criteria correctly carry only `id`/`created_at` (no `updated_at`/`version`) per PRD §2.6. Seven internal timestamps I had added that SCAFFOLD does not define (report submit/approve, design review, issue triage/board-review/resolve, complaint triage) were renamed with a `_` prefix so they stay internal and the payloads match SCAFFOLD exactly.
- **Envelope/pagination/error edges**: `req_` + 20 alnum ids, logical-clock timestamps, `has_more` arithmetic, `limit` 1..100 and negative `offset` -> `ERR_INVALID_REQUEST` 400, bad enum filter 400, malformed/array JSON body 400, unresolvable FK 404, unknown path 404, wrong method 405, missing/unknown role 401 `ERR_UNAUTHENTICATED`, unauthorized role 403 `ERR_UNAUTHORIZED`, both OCC paths 412, SoD 403 `ERR_SEGREGATION_OF_DUTIES`.

One note for the record: three initial mismatches during verification were all in my probe scripts (wrong error-id spellings and role assignments), not in the implementation — each was re-checked against the PRD text before the probe was corrected.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so the impl-gen subagent could not have read `test_suite/` (it did not exist at its spawn time).

## Step 7: Run tests and iterate — 2026-09-02T23:15:00.000Z

The task was already green on the first sweep — no fixes were needed.

## Summary

**Iterations run:** 1 (single 8-round parallel sweep, launched under `setsid nohup`, all rounds joined with `wait`).

**Tests deleted:** none. No test failed in any round, so no test entered the diagnostic protocol and no PRD-silence / unique-derivability adjudication was required.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `workspace/implementation/`:** none.

**Final sweep evidence** — all 8 `results.$i.json` present on disk at `workspace/implementation/` (~31 KB each, timestamped 23:06), each parsed:

| round | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 94/94 | 0 | 0 | 0 |
| 2 | 94/94 | 0 | 0 | 0 |
| 3 | 94/94 | 0 | 0 | 0 |
| 4 | 94/94 | 0 | 0 | 0 |
| 5 | 94/94 | 0 | 0 | 0 |
| 6 | 94/94 | 0 | 0 | 0 |
| 7 | 94/94 | 0 | 0 | 0 |
| 8 | 94/94 | 0 | 0 | 0 |

Per-round wall time ~168 s with `--isolation per-test-server` across 94 tests; the 8 concurrent rounds finished in roughly that same window. No flaky test surfaced — the union of non-passing tests across all 8 rounds is empty, and no round showed the `Terminated` / same-instant-death signature of reaped background rounds.

Notes on the artifact, for the record:
- The sweep log confirms the runner allocated a distinct port per round via the shared `ports.tsv` registry (round 8's release logged `port 37341 ... holders=8`), so no default-port collisions were in play.
- `workspace/implementation/start.sh` boots Flask on `$PORT` (default 10000) with a guarded `pip install`; storage is the in-memory `Store` in `db.py` with no seed data, consistent with the benchmark's in-memory-only rule.
- The 8 `results.*.json` files are left in place inside `workspace/implementation/` since that is where the prescribed sweep command writes them; they are runner output, not implementation state.

**Orchestrator independent verification (required — a Step 7 subagent claiming a clean sweep with no artifacts on disk is a known failure mode):** I re-listed and re-parsed the files myself rather than trusting the report. `ls` shows all 8 `results.{1..8}.json` (31320–31328 bytes, 23:06); a direct `json.load` of each yields `passed=94, failed=0, errors=0, skipped=0, total=94`. `workspace/sweep.log` contains 8 matching `Results: 94/94 passed, 0 failed, 0 errors, 0 skipped` lines and zero occurrences of `Terminated` — so the `setsid` wrapper held and no round was reaped. Sweep evidence confirmed genuine.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T23:15:00.000Z

Skip condition met exactly as the skill defines it: Step 7 exited on the first 8-round sweep with **0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at every site the test suite exercised, and there is no `<step_7_diff>` to hand off. No subagent was spawned and `workspace/PRD_FINALIZED.md` is intentionally absent. Step 9 will consequently start from `workspace/PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T23:35:00.000Z

Done. `PRD_COMPLETED.md` is complete and verified.

## Integrity check
- Source: `workspace/PRD.md` — 462 lines, 101,168 bytes
- Output: `workspace/PRD_COMPLETED.md` — 462 lines, 115,062 bytes (**+13,894 chars**, no line-count change: every change is an in-paragraph insert or revision, no new sections, no new table rows)
- §4 endpoint rows: **57** OK · §5 error rows: **67** OK · final line is `| \`ERR_LEVEL_OR_SURFACE_UNSUPPORTED\` | 422 |` OK
- 46 lines touched, 98 discrete text insertions

## Counts
- **ambiguity-pins: 57**
- **mismatch-revisions: 7**

## Changes

- §2.1 — insert — ambiguity — an `X-User-ID`/`X-User-Role` header present but empty is treated as absent (`ERR_UNAUTHENTICATED`) — middleware.py:28
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — response.py:9,12-13
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the logical clock, not host wall clock, 3 fractional digits — response.py:16-20, db.py:59
- §2.2 — insert — ambiguity — non-list 2xx `meta` carries only the two fields, no pagination keys — response.py:16-30
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`, not a silent default — validate.py:154-166
- §2.3 — insert — ambiguity — identifier filters matched literally and never existence-checked (empty page, not 404); `in_scope` accepts `true/false/1/0` case-insensitively; pagination applied after filtering and ordering — validate.py:171-200, routes/products.py:166-176
- §2.4 — insert — ambiguity — `created_at` is minted from the logical clock, so untouched-clock rows tie and fall back to insertion sequence — db.py:59,100-131
- §2.5 — insert — ambiguity — `expected_*_version` must be an integer >= 0; missing/non-integer/negative is step-6 `ERR_INVALID_REQUEST`, not a 412 — routes/reports.py:46, routes/assessments.py:44
- §2.6 — insert — ambiguity — body FK that is absent or non-string falls to step 6 rather than 404; optional FKs resolved only when supplied; per-endpoint FK resolution order fixed — validate.py:205-215, routes/complaints.py:42-48, routes/issues.py:43-45
- §2.7 — insert — ambiguity — component `ERR_CROSS_PRODUCT_REFERENCE` precedes criterion `ERR_CRITERION_STANDARD_MISMATCH` when one request checks both — routes/issues.py:56-64, routes/complaints.py:55-63
- §2.8 — insert — ambiguity — all two-decimal derived quantities serialise as bare JSON numbers, never strings — db.py:135-145
- §2.9 — revise — **mismatch** — withdrawal bumps product `version` on both branches; voiding bumps component+product even from `SCHEDULED`; explicit list of ops that rebuild derived fields without bumping `version`; benches never bump — routes/reports.py:322, routes/runs.py:228-236, routes/issues.py:153-158
- §2.9 — insert — ambiguity — scheduling a component's first run refreshes `updated_at` without bumping `version` — routes/runs.py:147, db.py:124
- §3.1 — insert — ambiguity — `criterion_number` capped at 40 chars — routes/standards.py:70
- §3.1 — insert — ambiguity — `disability_categories`/`surface_applicability` echoed in submitted order — routes/standards.py:75-97
- §3.1 — insert — ambiguity — recompute `reason` mandatory 1–2000, validated but not persisted or echoed — routes/products.py:114
- §3.2 — insert — ambiguity — new component carries `design_review_note` present and null — routes/products.py:152
- §3.2 — revise — **mismatch** — component creation triggers the full product recomputation (all counters, readiness, `assessed_criteria_count`, provisional index, posture) minus the cadence-lapse sweep, not just the in-scope counter and posture — routes/products.py:157, derive.py:201-215
- §3.2 — insert — ambiguity — `review_note` mandatory 1–2000 — routes/products.py:191
- §3.2 — insert — ambiguity — the design-review instant is internal only, not a response field — routes/products.py:202
- §3.3 — insert — ambiguity — `at_product_name` 1–120 chars — routes/runs.py:49
- §3.3 — insert — ambiguity — `scheduled_run_count` computed afresh per read (bench row never mutated); no bench list endpoint — serialize.py:22-27
- §3.3 — insert — ambiguity — a new run's `completed_at` is null — routes/runs.py:130-136
- §3.3 — insert — ambiguity — `scheduled_start`/`scheduled_end` echoed byte-for-byte unnormalised while comparisons use the denoted instants; `disability_categories_validated` in submitted order — routes/runs.py:130-135,194
- §3.3 — insert — ambiguity — booking checks follow §2.7 order (window -> scope 22 -> conflict 24 -> profile 33), so collision+wrong-profile yields `ERR_ENVIRONMENT_WINDOW_CONFLICT` — routes/runs.py:108-125
- §3.4 — insert — ambiguity — `EXCLUDED`/`PLANNED` components accrue evidence and coverage but never advance to `COMPLETE` — derive.py:72-100
- §3.4 — insert — ambiguity — `defects_found` optional; omitted leaves the prior value (null if never completed) — routes/runs.py:184-194
- §3.4 — insert — ambiguity — validated-category union always in canonical `VISION, HEARING, MOTOR, COGNITIVE` order — calc.py:123-135
- §3.4 — revise — **mismatch** — voiding a merely `SCHEDULED` run also bumps component+product `version` and still flips citing `ATTESTED` assessments to `NEEDS_REVALIDATION`; `void_reason` mandatory 1–2000 — routes/runs.py:212,226-236
- §3.5 — insert — ambiguity — `evidence_run_id` existence-checked only (need not be on the component, need not be `COMPLETED`) — routes/assessments.py:40-41
- §3.5 — insert — ambiguity — `remarks` bounds split across steps: >2000 always and <10 when `SUPPORTS` -> step-6 `ERR_INVALID_REQUEST`; <10 on other levels -> step-21 `ERR_REMARKS_REQUIRED` — routes/assessments.py:46-67
- §3.5 — insert — ambiguity — `remarks` stored as null when omitted under `SUPPORTS` — routes/assessments.py:81
- §3.5 — insert — ambiguity — `attestation_note` mandatory 1–2000 — routes/assessments.py:145
- §3.5 — insert — ambiguity — the 90-day freshness test compares full instants, not calendar dates — routes/assessments.py:170
- §3.5 — insert — ambiguity — attestation bumps only the product's `version`, not the component's — routes/assessments.py:179-183
- §3.5 — insert — ambiguity — qualifying-assessment tie-break is `created_at`, then `version`, then last inserted — calc.py:152-161
- §3.6 — insert — ambiguity — snapshot carries an entry for every criterion the rollup considered, excluded ones included, in `criterion_number` order — calc.py:200-220
- §3.6 — insert — ambiguity — entry shape: included -> numeric `weight` + level read back through 1.0/0.5/else; excluded -> `NOT_APPLICABLE` with `weight` null — calc.py:25-33,214
- §3.7 — insert — ambiguity — `submission_note` mandatory 1–2000; submission/approval instants internal only and notes never persisted — routes/reports.py:128,137,167,188
- §3.7 — insert — ambiguity — `change_request_note`/`approval_note` mandatory 1–2000, validated but not persisted — routes/reports.py:147,167
- §3.7 — revise — **mismatch** — review loop is `IN_REVIEW -> CHANGES_REQUESTED -> IN_REVIEW`; no transition returns a report to `DRAFT` — routes/reports.py:131
- §3.7 — insert — ambiguity — pinned assessments ordered `created_at` asc with insertion tie-break; approval leaves certified index null and snapshot empty — routes/reports.py:184-191
- §3.7 — revise — **mismatch** — publication runs the full product recomputation, not only `overdue_committed_blocker_count` — routes/reports.py:284
- §3.7 — insert — ambiguity — `withdrawal_reason` mandatory 1–2000 and, unlike the review notes, persisted — routes/reports.py:294,303
- §3.7 — revise — **mismatch** — withdrawing an `APPROVED` report still raises the product's `version`; withdrawal preserves `published_at`, channel, certified index, snapshot, `published_issue_count`, pinned lists, and superseded reports stay `SUPERSEDED` — routes/reports.py:301-322
- §3.9 — insert — ambiguity — a new issue's `public_target_date` is null — routes/issues.py:83
- §3.9 — insert — ambiguity — disclosure-debt rebuild is value-sensitive: unchanged debt+tier leaves the row entirely untouched — derive.py:182-191
- §3.9 — insert — ambiguity — triage/board-review/resolution notes mandatory 1–2000 and persisted; their instants internal only — routes/issues.py:138,150,166,175,233,250
- §3.9 — insert — ambiguity — deallocation `reason` mandatory 1–2000 not persisted; "affected" = any issue on the train whatever its state; already-`UNFUNDED` issues skipped (no `updated_at`/`version` move); `allocation_state` returns to `UNALLOCATED` even if all were skipped — routes/trains.py:141-158
- §3.10 — insert — ambiguity — the cited report's `state` is not examined at drafting, only at attestation — routes/questionnaires.py:37-49
- §3.10 — insert — ambiguity — new response has `correction_due_at` null; drafting leaves the product's counters, posture and `version` alone — routes/questionnaires.py:53-70
- §3.10 — insert — ambiguity — for both payload-free transitions an absent/empty body is fine and stray fields ignored, but a non-object body is `ERR_INVALID_REQUEST` — routes/questionnaires.py:105, routes/complaints.py:200
- §3.10 — insert — ambiguity — submission leaves the product's counters and posture alone — routes/questionnaires.py:105-120
- §3.10 — insert — ambiguity — `accuracy_attestation` mandatory 1–2000, validated but not persisted — routes/questionnaires.py:125
- §3.10 — insert — ambiguity — revision requires `answers_summary` 10–4000 as at drafting and deliberately keeps `last_attested_at`, so the staleness clock keeps running from attestation — routes/questionnaires.py:168-176
- §3.10 — insert — ambiguity — `update_due_at`/`correction_due_at` are full ISO 8601 instants carrying the clock's time of day, not date-only — routes/questionnaires.py:151, derive.py
- §3.10 — insert — ambiguity — a clock earlier than the staleness reference counts as zero days, never negative — calc.py:257-280
- §3.11 — insert — ambiguity — new complaint has `route` and all optional fields null; intake, triage and closure leave the product wholly untouched — routes/complaints.py:65-83,150-157,251-255
- §3.11 — insert — ambiguity — missing accommodation fields are step-6 `ERR_INVALID_REQUEST`, ahead of the step-13 from-state check — routes/complaints.py:129-143
- §3.11 — insert — ambiguity — on `REMEDIATION` the accommodation fields are shape-checked then discarded and the past-date rule never applies — routes/complaints.py:133-146
- §3.11 — insert — ambiguity — the complaint triage instant is internal only — routes/complaints.py:155
- §3.11 — revise — **mismatch** — linking an issue bumps the issue's `version` and runs the full product recomputation (not just posture) while leaving the product's `version` alone — routes/complaints.py:185-192
- §3.11 — insert — ambiguity — fulfilment rebuilds `accommodations_fulfilled_count` alone: no other counter, no posture re-derivation, no product `version` bump — routes/complaints.py:217, derive.py:126-129
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404, unmatched path), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) pinned inline as out-of-catalogue transport codes, plus trailing-slash insignificance — app.py:26,37-53

Note on method: the three transport codes were pinned in the §5 **preamble prose** rather than as table rows, precisely to keep the mandated 67-row count intact.

**Orchestrator independent verification:** re-measured myself — `PRD.md` 462 lines / 101,168 bytes vs `PRD_COMPLETED.md` 462 lines / 115,062 bytes; §4 carries 57 endpoint rows, §5 carries 67 error rows, and the file's last line is the complete `| \`ERR_LEVEL_OR_SURFACE_UNSUPPORTED\` | 422 |` row — a real section boundary, no truncation. `PRD_FINALIZED.md` confirmed absent, consistent with the Step 8 skip. Pipeline complete through Step 9.
